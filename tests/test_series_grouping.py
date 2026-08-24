"""Issue #34 direction B -- grid stacking, the SERVER half: the grouped listing mode
(/api/next/library?group=series) that folds the FULL filtered set into dial-in series
UNITS, and the ?series=<sid> filter that "opens a stack" to one series' members. Pins:
  * ?series=<sid> returns exactly that series' members, honours an added filter
    (rating), an unknown sid is an empty result (not an error), and never leaks a
    non-member;
  * ?group=series unit counting: a 3-task series + 5 standalone images + a 1-task
    2-image batch is 7 UNITS, not 14 rows; the series unit carries the series key
    (count_tasks from the series, count_images = survivors), singletons carry none;
    unit paging (page_size=3 -> 3+3+1);
  * cover selection: the newest MATCHING member, preferring an image over a video
    poster (a series whose newest member is a video still covers with its newest
    image);
  * filter interaction: a filter that removes SOME members still shows the series
    (cover among survivors, count_images = survivors); a filter that removes ALL
    members drops the unit;
  * regression: without group=series the payload is byte-identical to before -- one
    card per row, no series key;
  * the route keeps its LOGIN tier and adds NO new endpoint (group/series are params
    on the existing api_next_library).
"""
import json

import moonglade_gallery as G
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _seed(tmp_path, rows):
    """Save rows to tmp_path/catalog.db. Every row gets a non-empty filename (the
    catalog filter requires it) but NO file is written -- the grouped/series paths
    are pure catalog reads, so this stays fast even at 20k rows."""
    full = [{f: "" for f in CATALOG_FIELDS}
            | {"filename": "pic_%s.png" % r["media_id"]} | r for r in rows]
    save_catalog(tmp_path / "catalog.db", full)
    return tmp_path / "catalog.db"


def _client(tmp_path):
    return login_test_client(create_app(tmp_path))


def _task(tid, prompt, ts, mids, model_id="M1", model_name="Model One",
          is_video="", ratings=None):
    """All rows of one task: same task_id/prompt/timestamp/model, one row per output.
    `mids` may be plain ids (images) or, with is_video/ratings, carry per-row flags."""
    out = []
    for m in mids:
        out.append({"media_id": m, "task_id": tid, "prompt_full": prompt,
                    "created_at": ts, "model_id": model_id, "model_name": model_name,
                    "is_video": is_video,
                    "rating": (ratings or {}).get(m, "")})
    return out


# The prompt every dial-in test series shares (title resolves to "Frost queen").
_P = "frost queen, glacial crown, aurora sky"


def _seed_mixed(tmp_path):
    """One 3-task series (7 images, sid 'X1') + 5 standalone single-image tasks + one
    1-task 2-image batch = 14 rows / 7 units. Task ids are chosen so each series' tasks
    are CONSECUTIVE in task_id order (the engine chains consecutive tasks) and distinct
    models keep the standalones from chaining into each other or the batch."""
    rows = []
    # series X: 3 tasks, same model + prompt (rerolls chain), 30-min gaps.
    rows += _task("X1", _P, "2026-08-20T10:00:00Z", ["x1a", "x1b", "x1c"])
    rows += _task("X2", _P, "2026-08-20T10:30:00Z", ["x2a", "x2b"])
    rows += _task("X3", _P, "2026-08-20T11:00:00Z", ["x3a", "x3b"],
                  ratings={"x3a": "5"})            # one rated member, for the ?series test
    # a 1-task batch (2 images) -- its own model, sorts between X and Z.
    rows += _task("Y1", "a lone batch, two outputs", "2026-08-20T09:00:00Z",
                  ["y1a", "y1b"], model_id="MY", model_name="Batch Model")
    # 5 standalone single-image tasks, each a distinct model (never chain).
    stamps = ["2026-08-20T12:00:00Z", "2026-08-20T08:00:00Z", "2026-08-20T07:00:00Z",
              "2026-08-20T06:00:00Z", "2026-08-20T05:00:00Z"]
    for i, ts in enumerate(stamps, 1):
        rows += _task("Z%d" % i, "solo subject %d only" % i, ts, ["z%d" % i],
                      model_id="MZ%d" % i, model_name="Solo %d" % i)
    return _seed(tmp_path, rows)


_SERIES_MIDS = {"x1a", "x1b", "x1c", "x2a", "x2b", "x3a", "x3b"}


# --- ?series=<sid> : open a stack -------------------------------------------------------

def test_series_filter_returns_exactly_that_series_members(tmp_path):
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?series=X1&page_size=200").get_json()
    assert d["total"] == 7
    assert {it["media_id"] for it in d["items"]} == _SERIES_MIDS
    # never a non-member (no Y/Z rows leak in)
    assert not ({it["media_id"] for it in d["items"]} & {"y1a", "y1b", "z1", "z5"})
    # the ungrouped stack view is plain cards -- no series key on any
    assert all("series" not in it for it in d["items"])


def test_series_filter_honours_an_additional_filter(tmp_path):
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    # only x3a carries rating 5; rating_min=3 must intersect with the series membership
    d = cli.get("/api/next/library?series=X1&rating_min=3&page_size=200").get_json()
    assert [it["media_id"] for it in d["items"]] == ["x3a"]
    assert d["total"] == 1


def test_series_filter_unknown_sid_is_empty_not_an_error(tmp_path):
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    r = cli.get("/api/next/library?series=NOPExx&page_size=200")
    assert r.status_code == 200
    d = r.get_json()
    assert d["items"] == [] and d["total"] == 0
    # a member's own task id is NOT a series id either (sid is the FIRST task's id)
    assert cli.get("/api/next/library?series=X2").get_json()["total"] == 0


# --- ?group=series : the grouped listing ------------------------------------------------

def test_group_series_units_not_rows(tmp_path):
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?group=series&page_size=200").get_json()
    # 14 rows fold to 7 units: 1 series + 5 standalones + 1 batch
    assert d["total"] == 7
    assert len(d["items"]) == 7
    series_units = [it for it in d["items"] if "series" in it]
    assert len(series_units) == 1
    s = series_units[0]["series"]
    assert s["sid"] == "X1"
    assert s["count_tasks"] == 3            # the dial's full step count
    assert s["count_images"] == 7           # all 7 members survive (no filter)
    assert s["title"] == "Frost queen"
    # the series unit's cover is one of the series' own images
    assert series_units[0]["media_id"] in _SERIES_MIDS
    # every other unit is a plain card (batch + standalones), no series key
    singles = [it for it in d["items"] if "series" not in it]
    assert len(singles) == 6
    # the batch collapsed to ONE unit (its two outputs are not two cards here)
    assert len({it["media_id"] for it in d["items"]}) == 7


def test_group_series_pages_over_units(tmp_path):
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    p1 = cli.get("/api/next/library?group=series&page_size=3&page=1").get_json()
    p2 = cli.get("/api/next/library?group=series&page_size=3&page=2").get_json()
    p3 = cli.get("/api/next/library?group=series&page_size=3&page=3").get_json()
    assert (p1["total"], p1["pages"]) == (7, 3)
    assert [len(p1["items"]), len(p2["items"]), len(p3["items"])] == [3, 3, 1]
    # units page without overlap and cover all 7
    seen = [it["media_id"] for it in p1["items"] + p2["items"] + p3["items"]]
    assert len(seen) == len(set(seen)) == 7
    # exactly one series unit across the whole paged set, and it is on page 1
    # (its position = its newest member X3 @ 11:00, behind only Z1 @ 12:00)
    assert sum("series" in it for it in p1["items"]) == 1
    assert all("series" not in it for it in p2["items"] + p3["items"])


# --- the batch marker (STEP 0) ----------------------------------------------------------

def test_group_series_marks_a_batch_but_not_a_singleton(tmp_path):
    """A folded ("task", tid) unit with >=2 surviving images carries batch{task_id,count}
    and NO series key -- the grid renders it as a BATCH stack that opens via the existing
    View-batch path (?batch=task_id). A 1-image task carries neither key: a plain
    singleton, indistinguishable from an ungrouped card. Distinct models keep the two
    tasks from chaining into a series."""
    rows = []
    rows += _task("B1", "a four output batch", "2026-08-20T10:00:00Z",
                  ["b1a", "b1b", "b1c", "b1d"], model_id="MB", model_name="Batch Four")
    rows += _task("S1", "one lone output only", "2026-08-20T09:00:00Z",
                  ["s1"], model_id="MS", model_name="Solo One")
    _seed(tmp_path, rows)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?group=series&page_size=50").get_json()
    assert d["total"] == 2
    # the 4-image batch: ONE card, batch.count == 4 (all survivors), no series key
    batch = next(it for it in d["items"] if "batch" in it)
    assert batch["batch"] == {"task_id": "B1", "count": 4}
    assert "series" not in batch
    assert batch["media_id"] in {"b1a", "b1b", "b1c", "b1d"}   # cover is one of its own
    # the singleton: neither a batch nor a series marker
    single = next(it for it in d["items"] if it["media_id"] == "s1")
    assert "batch" not in single and "series" not in single


# --- cover selection --------------------------------------------------------------------

def test_series_cover_is_newest_image_even_when_newest_member_is_a_video(tmp_path):
    """A 3-task series ending in a VIDEO: the newest member overall is the video, but
    the cover must be the newest IMAGE (review item 4: prefer an image over a video
    poster)."""
    rows = []
    rows += _task("V1", _P, "2026-08-20T10:00:00Z", ["i1"])              # image
    rows += _task("V2", _P, "2026-08-20T10:30:00Z", ["i2"])              # newest IMAGE
    rows += _task("V3", _P, "2026-08-20T11:00:00Z", ["v3"], is_video="1")  # newest MEMBER
    _seed(tmp_path, rows)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?group=series&page_size=50").get_json()
    unit = next(it for it in d["items"] if "series" in it)
    assert unit["media_id"] == "i2"          # newest image, not v3 (the newest member)
    assert unit["is_video"] is False
    assert unit["series"]["count_tasks"] == 3 and unit["series"]["count_images"] == 3


# --- filter interaction -----------------------------------------------------------------

def _seed_filter_case(tmp_path):
    """series R (2 tasks: r_lo rating1, r_hi rating5) -- a filter removes SOME; series Q
    (2 tasks: both rating1) -- a filter removes ALL; standalone K (rating5) survives.
    Distinct models keep Q and R apart."""
    rows = []
    rows += _task("Q1", "alpha subject, beta clause", "2026-08-20T10:00:00Z", ["q1"],
                  model_id="MQ", model_name="Q", ratings={"q1": "1"})
    rows += _task("Q2", "alpha subject, beta clause", "2026-08-20T10:30:00Z", ["q2"],
                  model_id="MQ", model_name="Q", ratings={"q2": "1"})
    rows += _task("R1", _P, "2026-08-20T10:00:00Z", ["r_lo"],
                  model_id="MR", model_name="R", ratings={"r_lo": "1"})
    rows += _task("R2", _P, "2026-08-20T10:30:00Z", ["r_hi"],
                  model_id="MR", model_name="R", ratings={"r_hi": "5"})
    rows += _task("K1", "kestrel solo portrait", "2026-08-20T11:00:00Z", ["keep"],
                  model_id="MK", model_name="K", ratings={"keep": "5"})
    return _seed(tmp_path, rows)


def test_filter_keeps_a_series_with_a_surviving_member_and_drops_one_without(tmp_path):
    _seed_filter_case(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?group=series&rating_min=3&page_size=50").get_json()
    by_sid = {it["series"]["sid"]: it for it in d["items"] if "series" in it}
    # series R survives (r_hi rating 5): present, cover among survivors, counts honest
    assert "R1" in by_sid
    assert by_sid["R1"]["media_id"] == "r_hi"       # cover chosen among survivors
    assert by_sid["R1"]["series"]["count_tasks"] == 2   # full dial size
    assert by_sid["R1"]["series"]["count_images"] == 1  # only the survivor counts
    # series Q is entirely below the threshold -> the unit is absent
    assert "Q1" not in by_sid
    # only R's unit + the standalone K survive the filter
    assert d["total"] == 2
    assert {it["media_id"] for it in d["items"]} == {"r_hi", "keep"}


# --- regression: group off is byte-identical --------------------------------------------

def test_without_group_the_payload_is_unchanged(tmp_path):
    """The default (no group=series) path is one card per ROW, no series key -- exactly
    what /api/next/library returned before direction B. Pins the full card dict for a
    fully-populated row so a drift in the shared card builder fails loudly."""
    _seed(tmp_path, [{
        "media_id": "900", "task_id": "T", "is_video": "", "is_nsfw": "1",
        "model_name": "Model One", "created_at": "2026-08-20T10:00:00Z",
        "rating": "4", "width": "512", "height": "768", "prompt_full": "a b c",
        "source": "online", "title": "My Title", "batch_index": "1", "batch_size": "2",
    }])
    cli = _client(tmp_path)
    d = cli.get("/api/next/library").get_json()
    assert len(d["items"]) == 1
    it = d["items"][0]
    assert "series" not in it
    assert it == {
        "media_id": "900", "thumb": "/thumbs/900.jpg", "is_video": False,
        "is_nsfw": True, "model": "Model One", "date": "2026-08-20",
        "created_at": "2026-08-20T10:00:00Z", "rating": 4, "w": "512", "h": "768",
        "prompt": "a b c", "source": "online", "filename": "pic_900.png",
        "task_id": "T", "title": "My Title", "batch_index": "1", "batch_size": "2",
    }


def test_group_off_returns_every_row_and_no_series_key(tmp_path):
    """The mixed catalog ungrouped is all 14 rows as individual cards -- grouping is
    strictly opt-in, so a series' members are NOT collapsed when group is absent."""
    _seed_mixed(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?page_size=200").get_json()
    assert d["total"] == 14
    assert len(d["items"]) == 14
    assert all("series" not in it for it in d["items"])
    assert _SERIES_MIDS <= {it["media_id"] for it in d["items"]}


# --- tier / no new route ----------------------------------------------------------------

def test_group_and_series_are_params_not_a_new_route(tmp_path):
    """group/series ride on api_next_library -- no new endpoint, so no ROUTE_TIERS
    change: the url_map has exactly one rule for /api/next/library and it is
    api_next_library."""
    app = create_app(tmp_path)
    rules = [r for r in app.url_map.iter_rules() if str(r) == "/api/next/library"]
    assert len(rules) == 1
    assert rules[0].endpoint == "api_next_library"


def test_grouped_listing_inherits_the_login_tier(tmp_path):
    """An anonymous LAN request to the grouped listing is refused exactly like the base
    route -- group=series is not a way around the LOGIN gate -- and works once signed in."""
    _seed_mixed(tmp_path)
    anon = create_app(tmp_path).test_client()
    LAN = "192.168.1.50"
    r = anon.get("/api/next/library?group=series", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401
    cli = _client(tmp_path)
    assert cli.get("/api/next/library?group=series").status_code == 200


# --- the fold, unit-tested without a request --------------------------------------------

def test_fold_series_units_keys_and_order():
    """The pure fold: a multi-task series -> one ('series', sid) unit; any other task
    -> one ('task', tid) unit (siblings collapse); a blank task_id -> its own
    ('row', media_id) unit; unit order is first-appearance."""
    by_task = {"X1": ("X1", 1), "X2": ("X1", 2)}
    rows = [
        {"media_id": "a", "task_id": "X1", "created_at": "t3", "is_video": ""},
        {"media_id": "b", "task_id": "Z", "created_at": "t2", "is_video": ""},
        {"media_id": "c", "task_id": "Z", "created_at": "t2", "is_video": ""},  # sibling
        {"media_id": "d", "task_id": "X2", "created_at": "t1", "is_video": ""},  # folds -> X1
        {"media_id": "e", "task_id": "", "created_at": "t0", "is_video": ""},   # import
        {"media_id": "f", "task_id": "", "created_at": "t0", "is_video": ""},   # import
    ]
    unit_order, members = G.fold_series_units(rows, by_task)
    assert unit_order == [("series", "X1"), ("task", "Z"), ("row", "e"), ("row", "f")]
    assert len(members[("series", "X1")]) == 2   # a + d
    assert len(members[("task", "Z")]) == 2      # b + c (batch collapses)
    assert len(members[("row", "e")]) == 1


def test_fold_skips_blank_media_id_rows_like_the_ungrouped_path():
    """A row with no media_id makes no card -- exactly as the ungrouped listing skips
    it. Two such rows must NOT weld into one ('row','') unit, and none may open a unit
    (a blank cover would later be dropped, leaving total > items)."""
    rows = [
        {"media_id": "a", "task_id": "Z", "created_at": "t1", "is_video": ""},
        {"media_id": "", "task_id": "", "created_at": "t0", "is_video": ""},   # no id
        {"media_id": None, "task_id": "", "created_at": "t0", "is_video": ""},  # no id
    ]
    unit_order, members = G.fold_series_units(rows, {})
    assert unit_order == [("task", "Z")]          # only the real row; no ('row','') unit
    assert ("row", "") not in members

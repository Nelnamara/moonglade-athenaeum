"""The hand/face Fix surface: how its output is NAMED, what metadata it can honestly
carry, and how it gets priced. All mocked -- no network, no spend.

A Fix is submitted over POST /v2/task/fixer with a body of just {mediaId, boxes}, but what
PixAI creates from it is an ordinary taskKind=chat generation whose `chat` block carries a
`fixer` sub-block. Every test below turns on that one fact: the REST body is what we send,
the chat/fixer task is what comes back, and all three gaps (boilerplate filenames, blank
metadata, no cost preview) came from treating the returned task like a normal generation."""
import pathlib
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import gallery as moonglade_gallery
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


REFERENCE_PRO = core.EDIT_MODELS["reference-pro"]["model_id"]

# The prompt PixAI writes into a fixer task itself. It is a FIXED template -- identical on
# every Fix ever submitted -- which is exactly why naming the output from it produced a
# folder of indistinguishable 60-character files.
FIX_BOILERPLATE = ("Image 2 shows the areas in Image 1 that need fixing. Please repair the "
                   "marked hands and faces while keeping everything else unchanged.")


def _fixer_task(*, boxes=None, source="700", outputs=None, top_model=True):
    """A getTaskById-shaped Fix task, matching a real one: the boxes live under
    chat.fixer, the source media id is repeated at both levels, and PixAI's own fixed
    prompt template sits in `prompts`."""
    boxes = boxes if boxes is not None else [{"x": 10, "y": 20, "width": 30, "height": 40,
                                              "tag": "hand"}]
    params = {
        "priority": 1000, "width": 1024, "height": 1536,
        "prompts": FIX_BOILERPLATE, "mediaId": source,
        "chat": {"fixer": {"boxes": boxes}, "mediaId": source,
                 "modelId": REFERENCE_PRO, "prompts": FIX_BOILERPLATE},
        "isPrivate": False, "enablePreview": False, "hidePrompts": False,
    }
    if top_model:
        params["modelId"] = REFERENCE_PRO
    return {"createdAt": "2026-07-25T12:00:00Z", "parameters": params,
            "outputs": outputs if outputs is not None else {"mediaId": "M9"}}


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---------------------------------------------------------------------------
# 1. Naming -- a Fix output is named from its SOURCE, never from the template prompt
# ---------------------------------------------------------------------------

def test_fixer_block_only_matches_a_real_fix():
    assert core.fixer_block(_fixer_task())["boxes"][0]["tag"] == "hand"
    # an instruct Edit is also a chat task, but carries no fixer sub-block
    assert core.fixer_block({"parameters": {"chat": {"prompts": "make it night"}}}) is None
    assert core.fixer_block({"parameters": {"prompts": "a druid"}}) is None
    assert core.fixer_block(None) is None


def test_fix_marker_names_the_regions_that_were_repaired():
    assert core.fix_marker([{"tag": "face"}]) == "fix-face"
    assert core.fix_marker([{"tag": "hand"}]) == "fix-hand"
    # stable order regardless of the order the boxes were drawn in, and deduped
    assert core.fix_marker([{"tag": "hand"}, {"tag": "face"}, {"tag": "hand"}]) == "fix-face-hand"
    # an untagged box degrades to a plain marker rather than guessing which it was
    assert core.fix_marker([{}]) == "fix"
    assert core.fix_marker([]) == "fix"


def test_build_fix_stem_name_keeps_the_media_id_last():
    """Invariant 7 (the shared media_id -> file matcher) is what resume and every
    already_downloaded() check rely on: the readable text may be anything, but the file
    must still end in `_<media_id>`."""
    stem = core.build_fix_stem_name("a night elf druid", [{"tag": "face"}], "T1", "M9", 60)
    assert stem == "a_night_elf_druid_fix-face_T1_M9"
    assert stem.endswith("_M9")


def test_build_fix_stem_name_marker_survives_a_long_source_label():
    """The length cap applies to the source slug ONLY. If the marker could be truncated
    away, a long-prompted source would produce exactly the unreadable name this scheme
    exists to replace."""
    stem = core.build_fix_stem_name("x" * 200, [{"tag": "hand"}], "T1", "M9", 20)
    assert "_fix-hand_T1_M9" in stem
    assert stem.startswith("x" * 20 + "_")


def test_build_fix_stem_name_without_a_source_label():
    assert core.build_fix_stem_name("", [{"tag": "face"}], "T1", "M9", 60) == "fix-face_T1_M9"


def _stub_collect(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, m: ("https://cdn/" + m, {"width": 1024, "height": 1536}))
    monkeypatch.setattr(core, "download",
                        lambda s, url, stem, **k: ("ok", stem.with_suffix(".jpg")))
    monkeypatch.setattr(moonglade_gallery, "make_thumbnail", lambda *a, **k: None)


def test_collect_names_a_fix_from_its_source_image_not_the_template(monkeypatch, tmp_path):
    """The observed bug: a Fix landed as
    images/Image_2_shows_the_areas_in_Image_1_that_need_fixing_Please_r_<task>_<media>.jpg.
    Every Fix output got that same name because the fixer prompt is a fixed template."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="700", filename="images/a_night_elf_druid_T0_700.jpg",
                       prompt_preview="a night elf druid, moonlight")])
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task())
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/a_night_elf_druid_moonlight_fix-hand_T1_M9.jpg"
    assert "Image_2_shows" not in row["filename"]


def test_collect_falls_back_to_the_source_media_id_when_it_is_not_in_the_catalog(
        monkeypatch, tmp_path):
    """A Fix run on an image this backup has never seen (a fresh upload) still must not
    inherit the template name -- the source media_id is at least a real handle."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task(source="700"))
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/700_fix-hand_T1_M9.jpg"


def test_collect_still_names_an_ordinary_generation_from_its_prompt(monkeypatch, tmp_path):
    """No-regression: only the fixer family changes. A normal generation keeps
    build_stem_name's <prompt>_<task>_<media>."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: {
        "parameters": {"prompts": "a night elf druid", "modelId": "V1"},
        "outputs": {"mediaId": "M9", "seed": 42}})
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["filename"] == "images/a_night_elf_druid_T1_M9.jpg"


# ---------------------------------------------------------------------------
# 2. Metadata -- fill what the task really carries, leave the rest an honest em-dash
# ---------------------------------------------------------------------------

def test_extract_full_meta_reads_a_fixer_tasks_model():
    fm = core.extract_full_meta(_fixer_task())
    assert fm["model_id"] == REFERENCE_PRO
    assert fm["model_name"] == "Reference Pro"


def test_extract_full_meta_falls_back_to_the_chat_blocks_model_id():
    """build_chat_edit_parameters sets modelId INSIDE the chat block and nowhere else, so a
    chat task built by this app has no top-level modelId at all."""
    fm = core.extract_full_meta(_fixer_task(top_model=False))
    assert fm["model_id"] == REFERENCE_PRO


def test_extract_full_meta_invents_no_seed_sampler_steps_or_cfg_for_a_fix():
    """A fixer task has no outputs.detailParameters and no seed. Those fields stay empty --
    the detail page's em-dash is the honest answer; a borrowed number would be a lie."""
    fm = core.extract_full_meta(_fixer_task())
    assert fm["seed"] == "" and fm["steps"] == ""
    assert fm["sampler"] == "" and fm["cfg_scale"] == ""


def test_collect_writes_the_fix_model_and_leaves_the_rest_empty(monkeypatch, tmp_path):
    """The catalog row is what the detail page renders. Model was an em-dash because the
    collect path never wrote model_id/model_name at all."""
    _stub_collect(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: _fixer_task())
    core.collect_generation(object(), "T1", str(tmp_path))
    row = next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
               if r["media_id"] == "M9")
    assert row["model_id"] == REFERENCE_PRO and row["model_name"] == "Reference Pro"
    assert row["width"] == "1024" and row["height"] == "1536"     # dimensions already survived
    assert row["seed"] == "" and row["steps"] == ""
    assert row["sampler"] == "" and row["cfg_scale"] == ""


# ---------------------------------------------------------------------------
# 3. Pricing -- PixAI's own Fix price route, off the exact submit body (#93)
#
# On 2026-10-21 PixAI launched Hand Fix and Face Fix, priced per pass, and GET
# /v2/task-price stopped answering the chat.fixer shape this app used to synthesize (400 at
# chat.fixer.passes). PixAI's POST /v2/task/fixer/price takes the very {mediaId, boxes} body
# the Fix submit sends, and its server refuses face and hand boxes in one Fix. So the badge
# quotes the submit body itself, and a two-kind body is refused before any network call.
# ---------------------------------------------------------------------------

FACE = {"x": 1, "y": 2, "width": 3, "height": 4, "tag": "face"}
HAND = {"x": 5, "y": 6, "width": 7, "height": 8, "tag": "hand"}


def _tripwire(name):
    def _boom(*a, **k):
        raise AssertionError("reached " + name + " -- this must be refused before any network call")
    return _boom


def _record_posts(monkeypatch, answer=None):
    """Every _rest_post call, as (path, body). The price route answers `answer`; the spend
    route answers a task id."""
    posts = []

    def fake_post(s, path, body, **k):
        posts.append((path, body))
        if path == "/task/fixer":
            return {"id": "F1"}
        return answer if answer is not None else {"actualPrice": 4800, "originalPrice": 8000}
    monkeypatch.setattr(core, "_rest_post", fake_post)
    return posts


def test_fix_body_is_the_submit_body(monkeypatch):
    """ONE builder: what build_fixer_body returns is byte for byte the body submit_fixer
    POSTs to /v2/task/fixer -- including the boxes the cleaner drops, an upper-case tag,
    and a 21st box."""
    boxes = [{"x": 5, "y": 6, "width": 7, "height": 8, "tag": "Hand"},   # upper-case: kept
             {"x": 1, "y": 1, "width": 0, "height": 5, "tag": "hand"},   # zero width: dropped
             {"x": 1, "y": 1, "width": 5, "height": 5, "tag": "elbow"}]  # not a fixer tag
    boxes += [dict(HAND, x=i) for i in range(20)]                        # 21 usable in all
    posts = _record_posts(monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    assert core.submit_fixer(object(), "700", boxes) == "F1"
    (path, sent), = posts
    assert path == "/task/fixer"
    body = core.build_fixer_body("700", boxes)
    assert sent == body
    assert set(sent) == {"mediaId", "boxes"}, "never cusPrompts, never anything else"
    assert sent["mediaId"] == "700"
    assert len(sent["boxes"]) == 20 and sent["boxes"][0]["tag"] == "hand"
    assert all(b["width"] > 0 and b["tag"] == "hand" for b in sent["boxes"])


def test_a_box_off_the_top_or_left_is_clipped_not_shifted():
    """#93 review F3: x -160 width 360 covers 0..200 of the picture. Shifting it to x 0 kept
    the width and repaired 0..360; the part on the picture is 0..200."""
    out = core.clean_fix_boxes([{"x": -160, "y": -10, "width": 360, "height": 210, "tag": "face"}])
    assert out == [{"x": 0, "y": 0, "width": 200, "height": 200, "tag": "face"}]
    # wholly off the picture: nothing left, so the box is dropped
    assert core.clean_fix_boxes([{"x": -50, "y": 5, "width": 50, "height": 9, "tag": "hand"}]) == []
    # an in-picture box is untouched
    assert core.clean_fix_boxes([HAND]) == [HAND]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_box_is_dropped_not_raised(bad, monkeypatch):
    box = {"x": bad, "y": 1, "width": 5, "height": 5, "tag": "face"}
    assert core.clean_fix_boxes([box, FACE]) == [FACE]
    monkeypatch.setattr(core, "_rest_post", _tripwire("_rest_post"))
    assert core.price_fixer(object(), {"mediaId": "700", "boxes": [box]}) is None


@pytest.mark.parametrize("raw", ["Infinity", "-Infinity", "NaN"])
def test_a_non_finite_box_on_the_routes_is_a_note_and_never_sent(raw, tmp_path, monkeypatch):
    """Python's json reads Infinity and NaN, so a hand-rolled request can carry them."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    body = '{"mode":"fix","source":"700","boxes":[{"x":%s,"y":1,"width":5,"height":5,"tag":"face"}]}' % raw
    d = cli.post("/api/price", data=body, content_type="application/json").get_json()
    assert d["cost"] is None and "box" in d["note"]
    f = cli.post("/api/fix", data=body, content_type="application/json").get_json()
    assert "task_id" not in f
    assert seen["posts"] == []


def test_fix_body_refuses_no_usable_box():
    with pytest.raises(core.PixAIError, match="drag a box"):
        core.build_fixer_body("700", [])
    with pytest.raises(core.PixAIError, match="drag a box"):
        core.build_fixer_body("700", [{"x": 1, "y": 1, "width": 5, "height": 5, "tag": "elbow"}])


def test_fix_body_refuses_two_kinds():
    with pytest.raises(core.PixAIError, match="one kind") as err:
        core.build_fixer_body("700", [FACE, HAND])
    assert str(err.value) == core.FIX_ONE_KIND
    # case does not smuggle a second kind past the check
    with pytest.raises(core.PixAIError, match="one kind"):
        core.build_fixer_body("700", [dict(FACE, tag="FACE"), dict(HAND, tag="Hand")])
    # ...and one kind, however many boxes, is fine
    assert len(core.build_fixer_body("700", [FACE, dict(FACE, x=9)])["boxes"]) == 2


def test_submit_fixer_refuses_two_kinds_before_any_network(monkeypatch):
    monkeypatch.setattr(core, "_rest_post", _tripwire("_rest_post"))
    monkeypatch.setattr(core, "_session_for_create", _tripwire("_session_for_create"))
    with pytest.raises(core.PixAIError, match="one kind"):
        core.submit_fixer(object(), "700", [FACE, HAND])
    # READ_ONLY is still checked FIRST: the refusal a read-only install sees is READ_ONLY's.
    monkeypatch.setattr(core, "READ_ONLY", True)
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        core.submit_fixer(object(), "700", [FACE, HAND])


def _price_client(tmp_path, monkeypatch, answer=None):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", _tripwire("price_task (GET /v2/task-price)"))
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: seen.setdefault("card_checked", True)
                        and {"id": "c1", "total": 9})
    seen["posts"] = _record_posts(monkeypatch, answer)
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="700", filename="a_700.png",
                       created_at="2026-07-25T00:00:00")])
    return login_client(tmp_path), seen


def test_price_route_quotes_on_the_fixer_price_route(tmp_path, monkeypatch):
    """The quote and the spend for one payload: the SAME boxes; the media id differs on
    purpose. The picture is on disk (the normal case -- the backup IS the files), so the
    spend's resolver uploads it and sends the upload-kind id, while the quote names the
    catalog id (no media resolver on /api/price: it would upload once per keystroke).
    PixAI's Fix price does not move with the picture, so the number holds."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    (tmp_path / "a_700.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    uploads = []
    monkeypatch.setattr(core, "upload_media", lambda s, fp: uploads.append(fp) or "U-UPLOADED-1")
    payload = {"mode": "fix", "source": "700", "boxes": [FACE]}
    d = cli.post("/api/price", json=payload).get_json()
    assert d["cost"] == 4800 and d["original_cost"] == 8000
    assert d["fix_pass"] == "face" and d["fix_boxes"] == 1
    assert d["free"] is False
    (path, priced), = seen["posts"]
    assert path == "/task/fixer/price"
    assert uploads == [], "a quote never uploads"
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    r = cli.post("/api/fix", json=payload).get_json()
    assert r.get("task_id") == "F1", r
    (spend_path, sent), = seen["posts"][1:]
    assert spend_path == "/task/fixer"
    assert len(uploads) == 1, "the spend uploaded the local picture first"
    assert sent["boxes"] == priced["boxes"] == [FACE], "the boxes quoted are the boxes sent"
    assert priced["mediaId"] == "700", "the quote names the catalog id"
    assert sent["mediaId"] == "U-UPLOADED-1", "the spend names the uploaded picture"
    assert set(sent) == set(priced) == {"mediaId", "boxes"}


def test_price_route_omits_the_list_price_unless_it_is_higher(tmp_path, monkeypatch):
    cli, _ = _price_client(tmp_path, monkeypatch,
                           answer={"actualPrice": 8000, "originalPrice": 8000})
    d = cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": [HAND]}).get_json()
    assert d["cost"] == 8000 and "original_cost" not in d and d["fix_pass"] == "hand"


def test_fix_price_never_touches_the_spend_route(tmp_path, monkeypatch):
    import inspect
    assert core._FIXER_PRICE_PATH == "/task/fixer/price"
    assert core._FIXER_PRICE_PATH != "/task/fixer"
    # price_fixer takes no path: nothing a caller hands it can turn the quote into a spend
    assert list(inspect.signature(core.price_fixer).parameters) == ["session", "body"]
    # it rides the session it is handed -- never the mirror's create session
    monkeypatch.setattr(core, "_session_for_create", _tripwire("_session_for_create"))
    cli, seen = _price_client(tmp_path, monkeypatch)
    cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": [FACE]})
    assert seen["posts"] and all(p != "/task/fixer" for p, _ in seen["posts"])
    # a quote is not a spend: READ_ONLY still answers it
    monkeypatch.setattr(core, "READ_ONLY", True)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": [FACE]}).get_json()
    assert d["cost"] == 4800
    assert all(p == "/task/fixer/price" for p, _ in seen["posts"])


@pytest.mark.parametrize("exc", [core.PixAIError("400 bad"),
                                 requests.ConnectionError("dropped"),
                                 ValueError("not json")])
def test_fix_price_fails_soft(exc, tmp_path, monkeypatch):
    cli, seen = _price_client(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(core, "_rest_post", boom)
    r = cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": [FACE]})
    d = r.get_json()
    assert r.status_code == 200 and "error" not in d
    assert d["cost"] is None and d["free"] is False and "original_cost" not in d
    assert core.price_fixer(object(), {"mediaId": "700", "boxes": [FACE]}) is None


@pytest.mark.parametrize("answer", [{}, {"originalPrice": 8000}, [], None, {"actualPrice": "n/a"}])
def test_fix_price_without_a_price_is_no_price(answer, monkeypatch):
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: answer)
    assert core.price_fixer(object(), {"mediaId": "700", "boxes": [FACE]}) is None


def test_price_fixer_refuses_a_hand_built_body_before_any_network(monkeypatch):
    monkeypatch.setattr(core, "_rest_post", _tripwire("_rest_post"))
    for body in ({"mediaId": "700", "boxes": [FACE, HAND]}, {"mediaId": "700", "boxes": []},
                 {"mediaId": "", "boxes": [FACE]}, {}, None):
        assert core.price_fixer(object(), body) is None


def test_price_route_two_kinds_is_a_note_not_a_price(tmp_path, monkeypatch):
    cli, seen = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700",
                                     "boxes": [FACE, HAND]}).get_json()
    assert d["cost"] is None and d["free"] is False
    assert d["note"] == core.FIX_ONE_KIND
    assert seen["posts"] == [], "no network call for a body PixAI refuses"


def test_fix_route_two_kinds_is_refused_before_any_network(tmp_path, monkeypatch):
    """A hand-rolled /api/fix with face and hand boxes: refused, nothing sent -- and under
    READ_ONLY the refusal is READ_ONLY's."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    d = cli.post("/api/fix", json={"mode": "fix", "source": "700",
                                   "boxes": [FACE, HAND]}).get_json()
    assert "one kind" in d["error"] and "task_id" not in d
    assert seen["posts"] == []
    monkeypatch.setattr(core, "READ_ONLY", True)
    d = cli.post("/api/fix", json={"source": "700", "boxes": [FACE, HAND]}).get_json()
    assert "READ_ONLY" in d["error"]
    assert seen["posts"] == []


def test_price_route_never_claims_a_free_card_covers_a_fix(tmp_path, monkeypatch):
    """POST /v2/task/fixer accepts only {mediaId, boxes} -- it has no kaisuukenId field, so
    no free card can ever be spent on a Fix. Running the card check anyway would paint
    "FREE - a card covers this" over an action about to charge full credits."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700",
                                     "boxes": [{"x": 1, "y": 2, "width": 3, "height": 4,
                                                "tag": "hand"}]}).get_json()
    assert d["free"] is False and d["cards"] is None
    assert "card_checked" not in seen


def test_an_identical_fix_inside_the_window_is_refused_before_any_network(tmp_path, monkeypatch):
    """#93 review F4, the server half: a double tap (or a stale tab, or a retried POST) of the
    same Fix is refused before the upload and the spend; a different Fix is not, and the same
    one is accepted again once the window has passed."""
    from moonglade import gallery as g
    cli, seen = _price_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    clock = [1000.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])
    payload = {"source": "700", "boxes": [FACE]}
    assert cli.post("/api/fix", json=payload).get_json().get("task_id") == "F1"
    r = cli.post("/api/fix", json=payload)
    msg = r.get_json()["error"]
    assert r.status_code == 409 and "a few seconds ago" in msg
    assert "sent" not in msg.split(";")[0], "the refusal must not claim the first one was sent"
    assert [p for p, _ in seen["posts"]] == ["/task/fixer"], "the repeat sent nothing"
    # the same boxes in a different case/order of keys are the same Fix
    r = cli.post("/api/fix", json={"source": "700", "boxes": [dict(FACE, tag="FACE")]})
    assert r.status_code == 409
    # a different Fix goes through
    assert cli.post("/api/fix", json={"source": "700", "boxes": [dict(FACE, x=9)]}).get_json().get("task_id") == "F1"
    # ...and the first one again, once the window is over
    clock[0] += 11
    assert cli.post("/api/fix", json=payload).get_json().get("task_id") == "F1"
    assert [p for p, _ in seen["posts"]] == ["/task/fixer"] * 3


def _failing_then_ok(monkeypatch, exc):
    """_rest_post that raises `exc` on the first spend POST and answers a task id after."""
    posts = []

    def fake_post(s, path, body, **k):
        posts.append(path)
        if len(posts) == 1:
            raise exc
        return {"id": "F2"}
    monkeypatch.setattr(core, "_rest_post", fake_post)
    return posts


def _rest_refusal(status):
    return core.PixAIRestError("REST POST /task/fixer -> %d: refused" % status, status=status, body=None)


@pytest.mark.parametrize("status", [400, 402, 403, 422, 429])
def test_a_retry_after_pixais_4xx_refusal_goes_straight_through(status, tmp_path, monkeypatch):
    """PixAI refused the first submit (insufficient balance and the like): nothing was created
    or charged, so the repeat record is dropped and an immediate retry is not refused."""
    cli, _ = _price_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    posts = _failing_then_ok(monkeypatch, _rest_refusal(status))
    payload = {"source": "700", "boxes": [FACE]}
    first = cli.post("/api/fix", json=payload).get_json()
    assert "task_id" not in first and first["error"]
    again = cli.post("/api/fix", json=payload)
    assert again.status_code == 200 and again.get_json().get("task_id") == "F2"
    assert posts == ["/task/fixer", "/task/fixer"]


def test_a_retry_after_a_refusal_before_any_send_goes_straight_through(tmp_path, monkeypatch):
    """The mirror refusing before the POST (nothing left the machine) drops the record too."""
    cli, _ = _price_client(tmp_path, monkeypatch)
    calls = []

    def mirror(s):
        calls.append(1)
        if len(calls) == 1:
            raise core.PixAIError("Mirror mode is on but no mirror session is available")
        return s
    monkeypatch.setattr(core, "_session_for_create", mirror)
    posts = _record_posts(monkeypatch)
    payload = {"source": "700", "boxes": [FACE]}
    assert "task_id" not in cli.post("/api/fix", json=payload).get_json()
    assert posts == []
    assert cli.post("/api/fix", json=payload).get_json().get("task_id") == "F1"


@pytest.mark.parametrize("exc", [requests.ReadTimeout("read timed out"),
                                 requests.ConnectionError("connection reset"),
                                 "5xx", "408", "no-id"])
def test_a_retry_after_an_unknown_outcome_is_still_refused(exc, tmp_path, monkeypatch):
    """A timeout, a dropped connection, a 5xx or 408 after the send, or a 2xx with no task id:
    PixAI may have created -- and charged -- the Fix, so the immediate retry is refused."""
    cli, _ = _price_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    if exc == "5xx":
        exc = _rest_refusal(502)
    elif exc == "408":
        exc = _rest_refusal(408)
    if exc == "no-id":
        posts = []
        monkeypatch.setattr(core, "_rest_post", lambda s, path, body, **k: posts.append(path) or {})
    else:
        posts = _failing_then_ok(monkeypatch, exc)
    payload = {"source": "700", "boxes": [FACE]}
    assert "task_id" not in cli.post("/api/fix", json=payload).get_json()
    again = cli.post("/api/fix", json=payload)
    assert again.status_code == 409 and "a few seconds ago" in again.get_json()["error"]
    assert posts == ["/task/fixer"], "the retry sent nothing"


def test_read_only_refuses_the_fix_route_before_its_upload(tmp_path, monkeypatch):
    """The spend's resolver uploads the local picture -- a network call -- so READ_ONLY must
    refuse before build_request runs it, not only inside submit_fixer."""
    cli, seen = _price_client(tmp_path, monkeypatch)
    (tmp_path / "a_700.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(core, "upload_media", _tripwire("upload_media"))
    monkeypatch.setattr(core, "READ_ONLY", True)
    d = cli.post("/api/fix", json={"source": "700", "boxes": [FACE]}).get_json()
    assert "READ_ONLY" in d["error"] and "task_id" not in d
    assert seen["posts"] == []


def test_price_route_fix_without_a_box_is_a_note_not_a_price(tmp_path, monkeypatch):
    cli, seen = _price_client(tmp_path, monkeypatch)
    d = cli.post("/api/price", json={"mode": "fix", "source": "700", "boxes": []}).get_json()
    assert d["cost"] is None and "box" in d["note"]
    d2 = cli.post("/api/price", json={"mode": "fix", "source": ""}).get_json()
    assert d2["cost"] is None and d2["note"]
    assert seen["posts"] == []


def _collect_fix(monkeypatch, tmp_path, fixer):
    _stub_collect(monkeypatch, tmp_path)
    task = _fixer_task(source="700")
    task["parameters"]["chat"]["fixer"] = fixer
    monkeypatch.setattr(core, "_task_detail_query", lambda s, t: task)
    core.collect_generation(object(), "T1", str(tmp_path))
    return next(r for r in moonglade_gallery.load_catalog(tmp_path / "catalog.db")
                if r["media_id"] == "M9")["filename"]


def test_collect_names_a_passes_only_fix(monkeypatch, tmp_path):
    """A v4.1 Fix task may carry chat.fixer.passes instead of boxes; it is still named for
    the kind it repaired, never a bare `fix`."""
    name = _collect_fix(monkeypatch, tmp_path,
                        {"passes": [{"tag": "face", "imageSize": "1K", "boxCount": 2}]})
    assert "_fix-face_" in name


def test_collect_names_a_fix_carrying_boxes_and_passes(monkeypatch, tmp_path):
    name = _collect_fix(monkeypatch, tmp_path,
                        {"boxes": [{"x": 1, "y": 1, "width": 9, "height": 9, "tag": "hand"}],
                         "passes": [{"tag": "hand", "imageSize": "2K", "boxCount": 1}]})
    assert "_fix-hand_" in name


# ---------------------------------------------------------------------------
# 3b. The Fix surface's own badge + confirm
#
# The classic template (and its inline fixCost()/editCost()) was cut; the shipped Fix
# surface is now gallery/src/components/FixTab.jsx, with the desktop Edit counterpart in
# EditTab.jsx and the mobile Edit hook in gen/useEditGenerate.js. The contracts below are
# the SAME ones the classic tests pinned -- ported to the React sources, which is how this
# suite already reads shipped front-end behavior (see test_branding.py's LoginPage.jsx
# assertions).
# ---------------------------------------------------------------------------

_GALLERY_SRC = pathlib.Path(__file__).resolve().parents[2] / "gallery" / "src"


def _src(rel):
    return (_GALLERY_SRC / rel).read_text(encoding="utf-8")


def _price_build(src):
    """A cost surface's build() -- the payload builder it hands the shared price probe.

    Since 2026-08-22 the debounce, the /api/price call, the sequence guard and the abort
    live in gen/usePriceProbe.js (one module for all six cost lines); each host keeps only
    a `build` useCallback saying WHAT to price and when there is nothing to price. Every
    such helper closes on its deps array -- `}, [...]` -- and that token never appears
    inside the body, so slicing to the first `}, [` captures the whole thing."""
    i = src.index("const build = useCallback(")
    return src[i:src.index("}, [", i)]


def _probe_src():
    return _src("gen/usePriceProbe.js")


def _transport_src():
    """The one price transport (2026-08-23). The POST came out of the hook: usePriceProbe
    still owns the debounce, the sequence guard, the verdict and the teardown abort, but the
    request -- and the {response}-vs-{failed} split the spend gate reads -- lives in
    gen/priceRequest.js, which the Loom's own price sites ride too."""
    return _src("gen/priceRequest.js")


def test_fix_surface_mounts_the_shared_cost_badge():
    src = _src("components/FixTab.jsx")
    # Ported 2026-08-08 (no-vanilla campaign step 4): the vanilla <mg-cost-badge> custom
    # element became the shared React <CostBadge> (forwardRef, same setPrice/setChecking/clear
    # via costRef). A Fix is the one spend surface a free card can NEVER cover, so it must
    # still carry the shared cost renderer, not a bespoke one.
    assert "import CostBadge from" in src
    assert "<CostBadge ref={costRef}" in src, (
        "the Fix surface no longer mounts <CostBadge> -- it would be the only spend "
        "surface without the shared cost renderer")
    assert "onClick={run}" in src   # and a submit button wired to run()


def test_fix_cost_asks_the_server_and_hardcodes_nothing():
    src = _src("components/FixTab.jsx")
    body = _price_build(src)
    assert 'mode: "fix"' in body
    # The request itself is not this surface's: the host rides the shared probe, and the
    # probe rides the one price transport -- the only /api/price caller under gallery/src.
    assert "usePriceProbe" in src
    assert '"/api/price"' in _transport_src()
    assert "requestPrice" in _probe_src(), (
        "the probe must get its request from gen/priceRequest.js, not hand-roll one again")
    assert "8000" not in body and "8,000" not in body, (
        "the badge hardcodes the measured price instead of calling /api/price -- it would "
        "go silently wrong the moment PixAI reprices a Fix")


def test_fix_confirm_still_gates_the_submit_and_no_longer_denies_a_price():
    src = _src("components/FixTab.jsx")
    assert "window.confirm(" in src
    assert src.index("window.confirm(") < src.index('submitTask("/api/fix"')
    head = src[:src.index("window.confirm(")]
    # The confirm quotes the SETTLED figure, not a blanket cannot-be-priced denial. Since
    # 2026-08-22 that figure is the probe's last /api/price answer, and the identity gate is
    # what guarantees it belongs to THESE boxes -- it replaced the old flush-the-debounce-
    # and-await dance, which existed only because the number could still be in flight.
    assert "probe.response" in head
    assert "if (!probe.canSubmit) { probe.refresh(); return; }" in head, (
        "the confirm may only open once a verdict for this payload has settled")
    assert "no cost preview is available" not in src, (
        "the confirm still tells the owner a Fix cannot be priced -- it can, and the "
        "badge beside the button is showing the number")


def test_badge_and_submit_send_the_same_boxes():
    """The badge has to quote the request the button sends. Both go through the one
    display-to-original-pixel scaler (editCore.js's scaleBoxes); two copies of that
    arithmetic is how a price stops matching the thing being priced."""
    core_src = _src("gen/editCore.js")
    i = core_src.index("export function scaleBoxes(")
    assert "naturalWidth" in core_src[i:i + 400]
    src = _src("components/FixTab.jsx")
    # Since the dock fidelity pass (2026-08-16) the element handed to scaleBoxes is
    # scaleEl() -- the live <img> when it is laid out, else the last real measurement
    # (the ▲-collapsed dock hides the picture with display:none, and a 0-wide element
    # would submit display pixels as original pixels). Same invariant: ONE scaler, the
    # SAME element expression, in the price body and the submit body alike.
    # Four since #93 review F1/F3: the price body, run()'s can-it-measure guard, the submit
    # body and ✦ Fix's off check -- every one the same call on the same element expression.
    assert src.count("scaleBoxes(boxes, scaleEl())") == 4, (
        "the price body and the submit body no longer share the one scaleBoxes call each "
        "-- the badge would price a request the server never receives")
    assert "scaleBoxes(boxes, imgRef" not in src and "scaleBoxes(boxes, measured" not in src

"""The community read-only surface (scoped 2026-09-04, built 2026-09-06).

Four things land together here and each one rests on the same probe:

  * views RIDE --sync-artworks instead of being fetched live per My Art open;
  * My Art draws a per-card count and comparison bar on EVERY published card;
  * the panel reports a real LIFETIME views total and can sort by it;
  * a "blow-up" rule names a work whose recent pace has left its own normal behind.

PROBE_2026-09-06 (read-only, run against the live account before any of this was written)
settled two facts that the code cannot check for itself, so the fixtures below are shaped
like the probe's own answers rather than like something convenient:

  1. The AD-HOC bulk `artworks(authorId, first:N)` query ACCEPTS a `views` field. The
     persisted `listArtworks` the sync already pages does not carry it and cannot be edited
     to (fixed hash). `viewCount` / `viewsCount` / `totalViews` / `impressions` are all
     rejected by name -- `views` is the only spelling. 101 published works came back in
     three paced pages of 40.

  2. READING A VIEW COUNT REGISTERS A VIEW. Reading one page of 40 twice moved all 40 rows
     by exactly +1; a read that does not select `views` moved nothing. So two consecutive
     sweeps ALWAYS differ by at least the one view the sweep itself caused, and a spike
     rule that does not subtract it reports a permanent trickle on every work in the
     library. That subtraction is SPIKE_SELF_READ, and
     test_a_sweeps_own_read_is_never_a_spike is what holds it in place.
"""
from types import SimpleNamespace

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, load_catalog, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---------------------------------------------------------------------------
# The mechanism: views riding the artworks sync
# ---------------------------------------------------------------------------

def _session(user_id):
    """A stand-in the transport adapter passes straight through -- `_is_pixai_client` is
    the marker `_client_of` looks for, exactly as tests/fake_pixai.py uses it. Without it
    the object gets WRAPPED in a real PixAIClient and the user_id under test is the
    wrapper's (empty) one, not this."""
    return SimpleNamespace(_is_pixai_client=True, user_id=user_id)


def _bulk_page(rows, has_next=False, cursor=""):
    """One page shaped exactly like the probe's own response."""
    return {"artworks": {
        "edges": [{"node": {"id": aid, "views": v}} for aid, v in rows],
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}


def test_bulk_views_pages_the_whole_library(mocker):
    """The probe's real shape: 101 works over three pages of 40, cursor-followed.

    A hundred works cost three calls this way. The design it replaces cost one call per
    work per panel open."""
    pages = [
        _bulk_page([("aw%d" % i, i * 10) for i in range(0, 40)], True, "c1"),
        _bulk_page([("aw%d" % i, i * 10) for i in range(40, 80)], True, "c2"),
        _bulk_page([("aw%d" % i, i * 10) for i in range(80, 101)], False, ""),
    ]
    seen = []

    def fake(session, doc, variables=None, retries=None):
        seen.append(variables)
        return pages[len(seen) - 1]

    mocker.patch.object(core, "gql_adhoc", side_effect=fake)
    views, complete = core.artwork_views_bulk(
        _session("u1"), page_size=40, delay=0)

    assert complete is True
    assert len(views) == 101 and views["aw100"] == 1000
    assert len(seen) == 3
    assert [v["after"] for v in seen] == [None, "c1", "c2"]     # cursor really followed
    assert all(v["a"] == "u1" for v in seen)                    # authorId, not userId


def test_bulk_views_reports_a_failed_page_as_incomplete(mocker):
    """A page that refuses does not raise and does not lie: whatever was collected is
    real and comes back, flagged as partial. Same contract as the listing half's own B15
    behaviour -- a partial answer must never be presentable as a whole one."""
    mocker.patch.object(core, "gql_adhoc", side_effect=[
        _bulk_page([("aw1", 100), ("aw2", 200)], True, "c1"),
        core.PixAIError("page 2 refused"),
    ])
    views, complete = core.artwork_views_bulk(
        _session("u1"), page_size=2, delay=0)
    assert complete is False
    assert views == {"aw1": 100, "aw2": 200}


def test_bulk_views_selects_the_only_field_name_that_exists():
    """`views` is the spelling, and the probe ruled the alternatives out by name
    (`viewCount`, `viewsCount`, `totalViews`, `impressions` all answered "Cannot query
    field ... on type Artwork"). Pinned because the query document is the one place a
    plausible-looking rename would fail silently -- an unknown field is a validation
    error, and artwork_views_bulk fails SOFT on those, so every count would quietly
    become blank rather than wrong."""
    import inspect
    src = inspect.getsource(core.artwork_views_bulk)
    assert "node { id views }" in src
    for dead in ("viewCount", "viewsCount", "totalViews", "impressions"):
        assert dead not in src


def test_sync_artworks_writes_views_and_keeps_the_previous_reading(tmp_path, mocker, pixai):
    """End to end: two sweeps, and the SECOND one is what makes a spike computable.

    Sweep 1 fills `views` and leaves `views_prev` blank -- there is nothing before it.
    Sweep 2 slides sweep 1's reading down into `views_prev` and takes the fresh one, which
    is the whole reason the column exists."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="x_m1.png")])
    mocker.patch.object(core, "USER_ID", "u1")
    conn = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "T",
                                "visibility": "PUBLIC", "isNsfw": False,
                                "likedCount": 3, "commentCount": 1,
                                "aesScore": 6.0, "tacks": []}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)
    mocker.patch.object(core, "artwork_views_bulk", return_value=({"aw1": 400}, True))
    args = SimpleNamespace(out=str(tmp_path), token=None, delay=0)

    res = core.run_sync_artworks(args)
    assert res["views"] == 1 and res["views_complete"] is True
    row = {r["media_id"]: r for r in load_catalog(db)}["m1"]
    assert row["views"] == "400" and row["views_prev"] == ""       # nothing came before
    first_at = row["views_at"]
    assert first_at                                                # stamped

    core.artwork_views_bulk.return_value = ({"aw1": 465}, True)
    core.run_sync_artworks(args)
    row = {r["media_id"]: r for r in load_catalog(db)}["m1"]
    assert row["views"] == "465"
    assert row["views_prev"] == "400" and row["views_prev_at"] == first_at


def test_no_views_skips_the_sweep_entirely(tmp_path, mocker, pixai):
    """--no-views is the opt-out, and it exists because the read is not free: a sweep
    adds one view to every published work. A run that only wants fresh titles and like
    counts should be able to have them without touching the owner's own numbers."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="x_m1.png")])
    mocker.patch.object(core, "USER_ID", "u1")
    mocker.patch.object(core, "artwork_list_gql", return_value={
        "edges": [{"node": {"id": "aw1", "mediaId": "m1", "visibility": "PUBLIC",
                            "likedCount": 0, "commentCount": 0, "tacks": []}}],
        "pageInfo": {"hasPreviousPage": False}})
    swept = mocker.patch.object(core, "artwork_views_bulk")

    res = core.run_sync_artworks(SimpleNamespace(
        out=str(tmp_path), token=None, delay=0, no_views=True))

    swept.assert_not_called()
    assert res["views"] == 0
    assert {r["media_id"]: r for r in load_catalog(db)}["m1"]["views"] == ""


def test_a_failed_sweep_does_not_fail_the_whole_sync(tmp_path, mocker, pixai):
    """The views sweep is a SUPPLEMENTARY read in its own guard, like /api/account's
    credit-split call. `fail` on this run means the artwork LISTING is partial -- a real
    "the numbers below are not your whole library" warning. A views sweep that could not
    reach PixAI says nothing about that, and must not borrow the alarm."""
    save_catalog(tmp_path / "catalog.db", [_row(media_id="m1", filename="x_m1.png")])
    mocker.patch.object(core, "USER_ID", "u1")
    mocker.patch.object(core, "artwork_list_gql", return_value={
        "edges": [{"node": {"id": "aw1", "mediaId": "m1", "visibility": "PUBLIC",
                            "likedCount": 0, "commentCount": 0, "tacks": []}}],
        "pageInfo": {"hasPreviousPage": False}})
    mocker.patch.object(core, "artwork_views_bulk", return_value=({}, False))

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["matched"] == 1
    assert res["fail"] == 0                      # the sync itself succeeded
    assert res["views_complete"] is False        # and the sweep says so on its own line


def test_fold_views_leaves_a_row_alone_when_the_sweep_missed_it(tmp_path):
    """A partial sweep must not blank the rows it did not reach. fold_views is only ever
    called for a work the sweep actually returned; handed None it is a no-op, so a row
    keeps the last reading anyone actually took."""
    row = {"views": "300", "views_at": "2026-09-01T00:00:00Z",
           "views_prev": "250", "views_prev_at": "2026-08-01T00:00:00Z"}
    assert core.fold_views(dict(row), None, "2026-09-06T00:00:00Z") == row


# ---------------------------------------------------------------------------
# THE BLOW-UP RULE
# ---------------------------------------------------------------------------

def _work(views, prev, prev_at="2026-09-05T00:00:00Z", at="2026-09-06T00:00:00Z",
          made="2026-07-06T00:00:00Z"):
    """One published work with a 24-hour window and (by default) a 62-day life."""
    return {"media_id": "m", "artwork_id": "aw", "title": "A Work",
            "created_at": made, "views": views, "views_prev": prev,
            "views_at": at, "views_prev_at": prev_at}


def test_the_first_sweep_of_a_library_announces_nothing():
    """THE NO-ANNOUNCE BASELINE CASE. A library swept once has a view count and no
    history whatsoever -- there is no previous reading, so there is no pace to compare
    against and nothing honest to say. Silence is the answer, not a spike computed
    against zero (which would make every work in a freshly swept library "blow up" at
    once, on the very run that first looked at them)."""
    assert g.views_spike(_work("5000", "")) is None
    assert g.views_spike(_work("", "")) is None            # never swept at all


def test_a_sweeps_own_read_is_never_a_spike():
    """PROBE_2026-09-06's measured cost, held in place.

    Reading the counter increments it, so a work nobody looked at still reads +1 between
    two sweeps. Without SPIKE_SELF_READ every work in the library shows a permanent
    trickle -- and the rule's whole claim is that it fires on real attention."""
    assert g.SPIKE_SELF_READ == 1
    assert g.views_spike(_work("1001", "1000")) is None          # exactly the self-read
    assert g.views_spike(_work("1002", "1000")) is None          # +1 real: still nothing


def test_a_quiet_work_that_takes_off_is_a_spike():
    """1000 views over 62 days is ~0.67/hour. 200 in a day is ~8.3/hour -- twelve times
    its own normal, and past the absolute floor. That is the shape of the thing the owner
    asked to be told about."""
    s = g.views_spike(_work("1201", "1000"))
    assert s is not None
    assert s["gained"] == 200                    # 201 raw, minus the sweep's own read
    assert s["window_hours"] == 24.0
    assert s["multiple"] >= 3.0
    assert s["title"] == "A Work"


def test_steady_traffic_is_not_a_spike():
    """Twenty new views in a day on a work already averaging sixteen a day is a work
    doing what it always does. Popularity is not a blow-up."""
    assert g.views_spike(_work("1021", "1000")) is None


def test_a_busy_work_needs_a_real_surge_to_count():
    """The rule is relative to the WORK, not to the library. A piece pulling 60 views a
    day does not get to spike on 25 of them just because 25 clears the floor -- but
    quadruple its own pace and it does."""
    busy = dict(made="2026-08-07T00:00:00Z")          # 30 days old
    assert g.views_spike(_work("1826", "1800", **busy)) is None      # +25, its usual pace
    assert g.views_spike(_work("2101", "1800", **busy)) is not None  # +300 in a day


def test_the_absolute_floor_keeps_small_numbers_quiet():
    """A near-dormant work tripling from 3 views to 9 is technically a large multiple and
    is not news. The floor is what stops the rule from being a random-number generator at
    the bottom of the library."""
    assert g.SPIKE_MIN_GAIN == 25
    s = g.views_spike(_work("9", "3", made="2026-01-01T00:00:00Z"))
    assert s is None


def test_a_counter_that_goes_backwards_is_never_a_spike():
    """PixAI recounting, or a work unpublished and republished, can move the number down.
    A negative gain is clamped, never rendered as a spike with a nonsense multiple."""
    assert g.views_spike(_work("900", "1000")) is None


def test_an_unusable_window_is_declined_rather_than_guessed():
    """No timestamps, or a window that runs backwards, means the rate cannot be computed.
    The rule declines: a spike is a claim about a RATE, and inventing the denominator
    would make the claim up."""
    assert g.views_spike(_work("1201", "1000", at="", prev_at="")) is None
    assert g.views_spike(_work("1201", "1000", at="2026-09-01T00:00:00Z",
                               prev_at="2026-09-05T00:00:00Z")) is None


def test_two_sweeps_minutes_apart_cannot_manufacture_a_spike():
    """Running --sync-artworks twice in a row makes the window ~0, and dividing by it
    would turn any gain at all into an enormous rate. The window is floored at an hour."""
    s = g.views_spike(_work("1201", "1000",
                            prev_at="2026-09-06T00:00:00Z", at="2026-09-06T00:01:00Z"))
    assert s is None or s["window_hours"] >= g.SPIKE_MIN_WINDOW_H


def test_published_spikes_reads_the_catalog_and_ranks_them(tmp_path):
    """The route's own source: a pure local read over swept rows, hottest first, capped.
    Capped because this feeds ONE corner note -- a note naming twenty works is a feed."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="m1", artwork_id="aw1", title="Rocket", is_published="1",
             created_at="2026-07-06T00:00:00Z", views="1401", views_prev="1000",
             views_at="2026-09-06T00:00:00Z", views_prev_at="2026-09-05T00:00:00Z"),
        _row(media_id="m2", artwork_id="aw2", title="Warm", is_published="1",
             created_at="2026-07-06T00:00:00Z", views="1101", views_prev="1000",
             views_at="2026-09-06T00:00:00Z", views_prev_at="2026-09-05T00:00:00Z"),
        _row(media_id="m3", artwork_id="aw3", title="Quiet", is_published="1",
             created_at="2026-07-06T00:00:00Z", views="1001", views_prev="1000",
             views_at="2026-09-06T00:00:00Z", views_prev_at="2026-09-05T00:00:00Z"),
        _row(media_id="m4", artwork_id="aw4", title="Unswept", is_published="1",
             created_at="2026-07-06T00:00:00Z"),
    ])
    hits = g.published_spikes(db)
    assert [h["title"] for h in hits] == ["Rocket", "Warm"]     # Quiet and Unswept silent
    assert hits[0]["gained"] == 400
    assert g.published_spikes(db, limit=1) == hits[:1]


def test_the_route_carries_the_spikes_and_the_sweep_stamp(tmp_path, pixai):
    """What the corner note is fed. `views_at` is the sweep's identity -- the client
    announces once per sweep, not once per boot, and that is the field it remembers."""
    from tests.test_web_pick import _authed_client
    cli = _authed_client(tmp_path, [
        _row(media_id="m1", artwork_id="aw1", title="Rocket", filename="a_m1.png",
             is_published="1", created_at="2026-07-06T00:00:00Z",
             views="1401", views_prev="1000",
             views_at="2026-09-06T00:00:00Z", views_prev_at="2026-09-05T00:00:00Z"),
    ])
    d = cli.get("/api/your-art").get_json()
    assert d["views_at"] == "2026-09-06T00:00:00Z"
    assert len(d["spikes"]) == 1 and d["spikes"][0]["title"] == "Rocket"


def test_a_library_with_no_spikes_carries_an_empty_list(tmp_path, pixai):
    """The ordinary case, and the one the note must stay silent through."""
    from tests.test_web_pick import _authed_client
    cli = _authed_client(tmp_path, [
        _row(media_id="m1", artwork_id="aw1", title="Steady", filename="a_m1.png",
             is_published="1", created_at="2026-07-06T00:00:00Z",
             views="1005", views_prev="1000",
             views_at="2026-09-06T00:00:00Z", views_prev_at="2026-09-05T00:00:00Z"),
    ])
    assert cli.get("/api/your-art").get_json()["spikes"] == []


# ---------------------------------------------------------------------------
# Followers / following
#
# No route test lives here on purpose: /api/account has carried `followers`/`following`
# since the CLI's --account dashboard, and tests/test_web_pick.py's
# test_account_route_sums_cards_and_coverage already asserts both. What was missing was
# never the data -- it was that no SCREEN read it. Both surfaces the owner asked for (the
# chip beside the credits chip, the account popup's balance strip) are frontend-only reads
# of that same payload, and are pinned by loom/test/community-surface.test.js.
# ---------------------------------------------------------------------------

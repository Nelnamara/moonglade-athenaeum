"""The 2026-09-03 ultrareview's server-correctness cluster.

Each test pins one finding by the property that was actually wrong, not by the shape of
the fix -- so a future rewrite that reintroduces the bug fails here even if the code looks
nothing like today's.
"""
import json
import time

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client, _SEALED_DONOR

# Same marker the sibling roster tests use. This test used to RETURN EARLY when the donor
# was absent, which counts as a pass and hides it from conftest's donor-skip warning --
# the one thing that warning exists to make visible.
needs_donor = pytest.mark.skipif(not _SEALED_DONOR.is_file(),
                                 reason="sealed-definitions donor (private repo) not present")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path, rows=()):
    save_catalog(tmp_path / "catalog.db", list(rows))
    return login_test_client(create_app(tmp_path))


def _csrf(cli):
    return cli.get("/api/myart/items").get_json()["csrf"]


# ---- finding 4+14: one board, every reader ----------------------------------

def test_every_contest_reader_shares_one_board_snapshot(tmp_path, monkeypatch):
    """Four readers used four different page depths, so a contest past row ~50 was listed
    by /api/contests and then refused as "unknown contest" by the enter route. One
    snapshot, read at full depth, serves them all -- and costs ONE upstream call."""
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def _list(session, active_only=True, **k):
        calls.append(k.get("max_pages"))
        return [{"id": "c1", "slug": "s1", "title": "Deep one", "type": "community",
                 "prize_amount": 0, "active": True, "end_at": "", "result_at": "", "url": ""}]
    monkeypatch.setattr(core, "list_contests", _list)
    monkeypatch.setattr(core, "contest_enter", lambda s, slug, aid: {"success": True})
    cli = _client(tmp_path)
    assert cli.get("/api/contests").get_json()["contests"]
    cli.get("/api/contest/mine")
    r = cli.post("/api/contest/enter", json={"slug": "s1", "artwork_id": "aw1",
                                             "confirm": True, "csrf": _csrf(cli)})
    assert r.status_code == 200 and r.get_json()["entered"] is True
    assert len(calls) == 1, "every reader must share the one memoized board: %r" % (calls,)
    assert calls[0] is None, "the shared read takes list_contests' own full depth"


def test_the_board_memo_serves_both_list_variants(tmp_path, monkeypatch):
    """?all=1 is derived from the same snapshot rather than a second upstream read."""
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests", lambda s, **k: calls.append(1) or [
        {"id": "a", "slug": "a", "title": "Running", "type": "official",
         "prize_amount": 0, "active": True},
        {"id": "b", "slug": "b", "title": "Ended", "type": "community",
         "prize_amount": 0, "active": False}])
    cli = _client(tmp_path)
    running = cli.get("/api/contests").get_json()
    every = cli.get("/api/contests", query_string={"all": "1"}).get_json()
    assert [c["id"] for c in running["contests"]] == ["a"]
    assert [c["id"] for c in every["contests"]] == ["a", "b"]
    assert len(calls) == 1


# ---- finding 5: entry-key identity ------------------------------------------

def test_a_nested_artwork_id_survives_normalization():
    """The identity bug. An entry row can carry its artwork as a nested object; stripping
    it left only the ENTRY id, so the sweep keyed the same real entry differently from the
    enter/publish paths -- two keys, one entry, in a grow-only set."""
    rows = core._contest_rows([{"id": "entry-1", "artwork": {"id": "art-9", "title": "x"},
                                "authorId": "u1"}])
    assert rows[0]["artworkId"] == "art-9"
    assert rows[0]["id"] == "entry-1"          # the entry id is still there, unchanged
    assert "artwork" not in rows[0]            # ...and the nested object still does not ride along
    # an explicit flat artworkId always wins over the nested one
    rows = core._contest_rows([{"id": "e", "artworkId": "flat", "artwork": {"id": "nested"}}])
    assert rows[0]["artworkId"] == "flat"


def test_the_sweep_keys_entries_by_artwork_not_entry_id(tmp_path, monkeypatch, pixai):
    """End to end: the sweep must produce the SAME key the enter path would."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        {"id": "c1", "slug": "s1", "active": True, "result_at": "", "end_at": ""}])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: core._contest_rows(
                            [{"id": "entry-1", "artwork": {"id": "art-9"}}]))
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    g._contest_detection_sync(tmp_path)
    assert g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"] == ["c1:art-9"]


def test_the_sweep_heals_a_legacy_double_key(tmp_path, monkeypatch, pixai):
    """The REAL migration, in the one place it can be made safely.

    Before the artwork id was preserved, the sweep keyed an entry by its ENTRY id while the
    enter and publish paths keyed the same entry by its ARTWORK id -- one entry, two keys,
    in a set that only grows. It cannot be untangled from the keys alone. But when upstream
    hands back a row carrying BOTH ids, it has just told us they name the same entry, and
    that is the moment -- the only moment -- the stale key can be discarded honestly."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    # a store poisoned the old way: the entry id, from a pre-fix sweep
    g.telem_set_add("contest_entry_keys", "c1:entry-1", out_dir=tmp_path)
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 1
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        {"id": "c1", "slug": "s1", "active": True, "result_at": "", "end_at": ""}])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: core._contest_rows(
                            [{"id": "entry-1", "artwork": {"id": "art-9"}}]))
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    g._contest_detection_sync(tmp_path)
    # one entry, one key -- the true one
    assert g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"] == ["c1:art-9"]
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 1


def test_the_sweep_leaves_an_unpaired_key_alone(tmp_path, monkeypatch, pixai):
    """The limit of the migration, asserted rather than assumed: with only one id on the
    row there is nothing to prove, so nothing is discarded. An entry made on another device
    is not evidence that some other key is stale."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    g.telem_set_add("contest_entry_keys", "c1:somebody-else", out_dir=tmp_path)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        {"id": "c1", "slug": "s1", "active": True, "result_at": "", "end_at": ""}])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: [{"artworkId": "art-9"}])   # no entry id
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    g._contest_detection_sync(tmp_path)
    assert sorted(g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"]) == [
        "c1:art-9", "c1:somebody-else"]


def test_set_discard_is_narrow_and_honest(tmp_path):
    """The primitive itself. These sets are grow-only on purpose -- a metric that can fall
    can un-earn an achievement -- so the one exception reports whether it actually did
    anything and does nothing at all when the key is not there."""
    g.telem_set_add("contest_entry_keys", "c1:a", out_dir=tmp_path)
    assert g.telem_set_discard("contest_entry_keys", "c1:nope", out_dir=tmp_path) is False
    assert g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"] == ["c1:a"]
    assert g.telem_set_discard("contest_entry_keys", "c1:a", out_dir=tmp_path) is True
    assert g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"] == []
    # an absent set is not an error
    assert g.telem_set_discard("never_existed", "x", out_dir=tmp_path) is False


# ---- finding 6: the requires fixed point ------------------------------------

def test_a_meta_of_a_meta_earns_in_one_pass():
    """The stale-snapshot shape, built deliberately: a meta whose prereq is ANOTHER meta,
    with no threshold pre-satisfying anything. One snapshot taken before the loop could
    never see the inner meta earn, so the outer one never earned at all."""
    roster = [
        {"id": "leaf-a", "metric": "images", "threshold": 1, "tier": "common",
         "name": "A", "icon": "", "desc": "", "hidden": False, "banner_reward": False},
        {"id": "leaf-b", "metric": "images", "threshold": 1, "tier": "common",
         "name": "B", "icon": "", "desc": "", "hidden": False, "banner_reward": False},
        {"id": "inner-meta", "metric": "meta", "threshold": 2, "tier": "epic",
         "name": "Inner", "icon": "", "desc": "", "hidden": False, "banner_reward": False,
         "requires": ["leaf-a", "leaf-b"]},
        {"id": "outer-meta", "metric": "meta", "threshold": 1, "tier": "legendary",
         "name": "Outer", "icon": "", "desc": "", "hidden": False, "banner_reward": False,
         "requires": ["inner-meta"]},
    ]
    import unittest.mock as _mock
    with _mock.patch.object(g, "_roster", lambda: roster), \
         _mock.patch.object(g, "_skins", lambda: []), \
         _mock.patch.object(g, "_skin_unlock", lambda: {}), \
         _mock.patch.object(g, "_ladder_tracks", lambda: []):
        by = {a["id"]: a for a in g.compute_achievements({"images": 1})["achievements"]}
    assert by["inner-meta"]["earned"] is True
    assert by["outer-meta"]["earned"] is True, "a meta of a meta must resolve in one call"
    assert by["outer-meta"]["current"] == 1


@needs_donor
def test_the_real_roster_still_resolves_its_metas(tmp_path):
    """The live roster, through the real path -- the fixed point must not change what the
    shipped metas do. Self-computing: satisfies every threshold and asserts every
    requires-meta earns."""
    assert [a for a in g._roster() if a.get("requires")], "the roster really has metas"
    full = {a["metric"]: 10 ** 9 for a in g._roster()}
    by = {a["id"]: a for a in g.compute_achievements(full)["achievements"]}
    for a in g._roster():
        if a.get("requires"):
            assert by[a["id"]]["earned"], a["id"]


# ---- finding 7: dates ---------------------------------------------------------

def test_series_ts_parses_a_date_only_value():
    """A contest end date with no time component read as NO DATE -- no countdown, and the
    recency window skipped it entirely."""
    ts = g._series_ts("2026-09-20")
    assert ts is not None
    import datetime as _dt
    got = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc)
    assert (got.year, got.month, got.day, got.hour) == (2026, 9, 20, 0)


def test_series_ts_respects_a_utc_offset():
    """The offset was truncated and the time read as UTC -- a deadline wrong by hours."""
    plus = g._series_ts("2026-09-20T12:00:00+09:00")
    utc = g._series_ts("2026-09-20T12:00:00Z")
    assert plus is not None and utc is not None
    assert utc - plus == 9 * 3600, "+09:00 is nine hours AHEAD of UTC"
    minus = g._series_ts("2026-09-20T12:00:00-05:00")
    assert minus - utc == 5 * 3600
    # the existing shapes are untouched
    assert abs(g._series_ts("2026-09-20T12:00:00.545Z") - utc - 0.545) < 1e-6
    assert g._series_ts("2026-09-20T12:00:00") == utc
    assert g._series_ts("") is None and g._series_ts("nonsense") is None


# ---- finding 8: publish-and-enter records its own entry ----------------------

def test_publish_and_enter_records_the_entry_itself(tmp_path, monkeypatch):
    """It answered entered:true and wrote nothing, leaning on a sweep that silently no-ops
    when the lock is held -- so the entry existed on PixAI and nowhere locally."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "resolve_tack_ids", lambda s, tags: ([], []))
    monkeypatch.setattr(core, "task_media_index", lambda s, t, m: 0)
    monkeypatch.setattr(core, "publish_artwork_from_task",
                        lambda s, t, **kw: {"id": "newart1"})
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        {"id": "c7", "slug": "ice-pop", "title": "Ice", "type": "community",
         "prize_amount": 0, "active": True}])
    monkeypatch.setattr(core, "contest_enter", lambda s, slug, aid: {"success": True})
    # hold the sweep lock: the kick MUST no-op, which is exactly the case that lost the record
    assert g._contest_sync_lock.acquire(False)
    try:
        cli = _client(tmp_path, [_row(media_id="m1", task_id="t1", filename="x_m1.png",
                                      created_at="2026-07-01T00:00:00")])
        d = cli.post("/api/myart/publish",
                     json={"action": "publish", "media_id": "m1", "confirm": True,
                           "challenge": "c7", "csrf": _csrf(cli)}).get_json()
        assert d["published"] is True and d["entered"] is True
    finally:
        g._contest_sync_lock.release()
    assert g.load_telemetry(tmp_path)["sets"]["contest_entry_keys"] == ["c7:newart1"]


# ---- finding 12: the sync route ---------------------------------------------

def test_sync_requires_csrf(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [])
    cli = _client(tmp_path)
    r = cli.post("/api/contest/sync", json={})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]


def test_sync_returns_immediately_and_runs_off_thread(tmp_path, monkeypatch):
    """It ran a 30-90s paced sweep INSIDE the request, holding the connection. Now it
    answers at once and the work happens on its own thread."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    started = {"n": 0}
    real = g.threading.Thread

    def _capture(target=None, args=(), kwargs=None, daemon=None):
        started["n"] += 1
        # Run the body inline so the lock the route took is released the way a real thread
        # would release it -- a stub that swallows start() wedges the module lock, which is
        # how the route's own leak-on-failed-start was found.
        return type("T", (), {"start": lambda self_: target(*args, **(kwargs or {}))})()
    cli = _client(tmp_path)
    monkeypatch.setattr(g.threading, "Thread", _capture)
    d = cli.post("/api/contest/sync", json={"csrf": _csrf(cli)}).get_json()
    monkeypatch.setattr(g.threading, "Thread", real)
    assert d["started"] is True and "contest_entries" in d
    assert started["n"] == 1


def test_sync_reports_recent_and_busy_without_starting_work(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [])
    cli = _client(tmp_path)
    token = _csrf(cli)
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": time.time()})
    d = cli.post("/api/contest/sync", json={"csrf": token}).get_json()
    assert d["started"] is False and d["skipped"] == "recent"
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    assert g._contest_sync_lock.acquire(False)
    try:
        d = cli.post("/api/contest/sync", json={"csrf": token}).get_json()
        assert d["started"] is False and d["busy"] is True
    finally:
        g._contest_sync_lock.release()


def test_mine_exposes_the_sync_watch_flags(tmp_path, monkeypatch):
    """What the client watches instead of holding a request open."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [])
    cli = _client(tmp_path)
    d = cli.get("/api/contest/mine").get_json()
    assert d["sync_running"] is False and "last_sync_at" in d
    assert g._contest_sync_lock.acquire(False)
    try:
        assert cli.get("/api/contest/mine").get_json()["sync_running"] is True
    finally:
        g._contest_sync_lock.release()


# ---- finding: READ_ONLY on the entry paths (verification, not a fix) --------

def test_entering_a_contest_is_read_only_guarded(mock_session, monkeypatch):
    """CLAUDE.md's contract: an account-changing call checks READ_ONLY before the network.
    Both entry paths funnel through contest_enter, so this is where it has to hold."""
    monkeypatch.setattr(core, "READ_ONLY", True)
    import pytest
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        core.contest_enter(mock_session, "slug", "art1")
    mock_session.post.assert_not_called()


# ---- finding: jobs_concurrent counts generations ----------------------------

def test_jobs_concurrent_counts_only_generations(tmp_path, monkeypatch):
    """It counted every non-terminal row -- panel jobs, imports, CLI runs -- so a sync
    beside an import could satisfy a rung nobody had earned."""
    core.append_job_event(tmp_path, "gen-1", status="running", type="generate")
    core.append_job_event(tmp_path, "panel-1", status="running", type="panel")
    core.append_job_event(tmp_path, "imp-1", status="running", type="import")
    cli = _client(tmp_path)
    monkeypatch.setattr(core, "generation_status",
                        lambda s, t: {"phase": "running", "paid_credit": 0})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli.get("/api/task-status", query_string={"task_id": "gen-1"})
    assert g.telemetry_metrics(tmp_path).get("jobs_concurrent", 0) == 1


# ---- finding: the artwork_id index ------------------------------------------

def test_artwork_id_is_indexed(tmp_path):
    """The docstring claimed an indexed lookup; there was no index, and the call runs two
    or three times per contest overlay open."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", artwork_id="aw1", filename="a.png")])
    with g.catalog(db) as con:
        names = {r[1] for r in con.execute("PRAGMA index_list(catalog)").fetchall()}
    assert "idx_artwork_id" in names

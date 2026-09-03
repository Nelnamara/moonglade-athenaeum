"""The overlay-open perf pass (2026-09-03): the three memos that stopped every overlay
open from paying for a full library walk, a live board pull, and a paced contest sweep.

Each test asserts the BEHAVIOUR the memo has to keep -- a cached answer is still a correct
answer, and an invalidation really invalidates -- rather than timing anything. Self-computing
where a roster or a metric is involved; no roster facts.
"""
import time

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return tmp_path / "catalog.db"


def _client(tmp_path, rows=()):
    save_catalog(tmp_path / "catalog.db", list(rows))
    return login_test_client(create_app(tmp_path))


def _fresh_metrics_cache(monkeypatch):
    monkeypatch.setattr(g, "_ACH_METRICS_CACHE", {})


# ---- the achievement-metrics memo -------------------------------------------

def test_metrics_are_memoized_between_calls(tmp_path, monkeypatch):
    """The Folio, the Panel and every ach re-check all ask for this bundle, and four of
    its passes read every matching row. Asking twice must cost one read."""
    _fresh_metrics_cache(monkeypatch)
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png", rating="5",
                               created_at="2026-01-01T00:00:00")])
    first = g.achievement_metrics(db)
    calls = {"n": 0}
    real = g.catalog_counts

    def _counted(p):
        calls["n"] += 1
        return real(p)
    monkeypatch.setattr(g, "catalog_counts", _counted)
    again = g.achievement_metrics(db)
    assert calls["n"] == 0, "a second call inside the window must not recompute"
    assert again == first


def test_the_memo_hands_out_copies_not_its_own_dict(tmp_path, monkeypatch):
    """Callers .update() the result with telemetry metrics. Handing out the cached dict
    itself would let the first caller's telemetry leak into every later reader."""
    _fresh_metrics_cache(monkeypatch)
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png",
                               created_at="2026-01-01T00:00:00")])
    a = g.achievement_metrics(db)
    a["images"] = 999999
    a["injected"] = True
    b = g.achievement_metrics(db)
    assert b.get("injected") is None and b["images"] != 999999


def test_a_changed_catalog_invalidates_the_memo(tmp_path, monkeypatch):
    """Invalidation is IMMEDIATE, on the cheap (COUNT(*), MAX(media_id)) key -- no time
    floor. One of this bundle's consumers is the achievement gate, where earning something
    unlocks its art: "your banner shows up within thirty seconds" would be a bug, not a
    bounded staleness. tests/test_unlock_split.py is the test that catches it."""
    _fresh_metrics_cache(monkeypatch)
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png",
                               created_at="2026-01-01T00:00:00")])
    before = g.achievement_metrics(db)["images"]
    save_catalog(db, [_row(media_id="1", filename="a_1.png", created_at="2026-01-01T00:00:00"),
                      _row(media_id="2", filename="b_2.png", created_at="2026-01-02T00:00:00")])
    assert g.achievement_metrics(db)["images"] == before + 1


def test_a_gate_reads_a_catalog_that_changed_one_line_ago(tmp_path, monkeypatch):
    """The regression a time floor caused, pinned directly: an achievement earned now must
    be measurable now, because unlocking its art depends on this bundle."""
    _fresh_metrics_cache(monkeypatch)
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png",
                               created_at="2026-01-01T00:00:00")])
    g.achievement_metrics(db)                                  # warm the memo
    save_catalog(db, [_row(media_id=str(i), filename="a_%d.png" % i,
                           created_at="2026-01-0%dT00:00:00" % ((i % 9) + 1))
                      for i in range(1, 6)])
    assert g.achievement_metrics(db)["images"] == 5


def test_use_cache_false_always_reads_for_real(tmp_path, monkeypatch):
    _fresh_metrics_cache(monkeypatch)
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png",
                               created_at="2026-01-01T00:00:00")])
    g.achievement_metrics(db)
    g._ACH_METRICS_CACHE[str(db)]["metrics"]["images"] = 4242
    assert g.achievement_metrics(db, use_cache=False)["images"] != 4242


def test_the_achievements_route_still_answers_correctly(tmp_path, monkeypatch):
    """The memo and the single-telemetry-parse refactor must not change one number the
    route reports. Driven through the real route, twice -- the second is the cached path."""
    _fresh_metrics_cache(monkeypatch)
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2026-01-01T00:00:00")])
    first = cli.get("/api/achievements").get_json()
    second = cli.get("/api/achievements").get_json()
    assert first["metrics"] == second["metrics"]
    assert first["metrics"]["images"] == 1


def test_telemetry_metrics_accepts_a_preloaded_store(tmp_path):
    """The parameter that collapsed three parses into one. Passing the store in must give
    the identical answer to letting it load its own."""
    g.telem_bump("edits", 3, out_dir=tmp_path)
    loaded = g.load_telemetry(tmp_path)
    assert g.telemetry_metrics(tmp_path, telem=loaded) == g.telemetry_metrics(tmp_path)
    assert g.telemetry_metrics(tmp_path, telem=loaded)["edits"] == 3


def test_first_sync_complete_accepts_a_preloaded_store(tmp_path):
    g.telem_flag("first_sync_done", out_dir=tmp_path)
    loaded = g.load_telemetry(tmp_path)
    assert g.first_sync_complete(tmp_path, tmp_path / "catalog.db", telem=loaded) is True


# ---- the contest-board memo -------------------------------------------------

def _board_stub(monkeypatch, calls):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def _list(session, active_only=True, **k):
        calls.append(active_only)
        return [{"id": "c1", "slug": "s1", "title": "One", "type": "official",
                 "prize_amount": 0, "active": True}]
    monkeypatch.setattr(core, "list_contests", _list)


def test_the_contest_board_is_memoized(tmp_path, monkeypatch):
    """Four surfaces mount this on open. They must share one pull, not take one each."""
    monkeypatch.setattr(g, "_contests_cache", {})
    calls = []
    _board_stub(monkeypatch, calls)
    cli = _client(tmp_path)
    first = cli.get("/api/contests").get_json()
    for _ in range(4):
        assert cli.get("/api/contests").get_json() == first
    assert len(calls) == 1


def test_both_board_variants_come_off_the_one_snapshot(tmp_path, monkeypatch):
    """?all=1 used to be a SECOND cached read at a different depth. Since the ultrareview
    there is one board -- read at full depth, filtered per variant -- so the running-only
    view and the everything view can never disagree about what exists."""
    monkeypatch.setattr(g, "_contests_cache", {})
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests", lambda s, **k: calls.append(1) or [
        {"id": "a", "slug": "a", "title": "Running", "type": "official",
         "prize_amount": 0, "active": True},
        {"id": "b", "slug": "b", "title": "Ended", "type": "community",
         "prize_amount": 0, "active": False}])
    cli = _client(tmp_path)
    assert [c["id"] for c in cli.get("/api/contests").get_json()["contests"]] == ["a"]
    everything = cli.get("/api/contests", query_string={"all": "1"}).get_json()
    assert [c["id"] for c in everything["contests"]] == ["a", "b"]
    assert len(calls) == 1, "one upstream read serves both variants"


def test_the_board_memo_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_contests_cache", {})
    calls = []
    _board_stub(monkeypatch, calls)
    cli = _client(tmp_path)
    cli.get("/api/contests")
    g._contests_cache["board"]["at"] -= (g.CONTESTS_TTL + 1)
    cli.get("/api/contests")
    assert len(calls) == 2


def test_a_board_failure_is_not_cached(tmp_path, monkeypatch):
    """An offline blip must not pin an empty board for the whole TTL."""
    monkeypatch.setattr(g, "_contests_cache", {})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_contests",
                        lambda s, **k: (_ for _ in ()).throw(core.PixAIError("board down")))
    cli = _client(tmp_path)
    d = cli.get("/api/contests").get_json()
    assert d["contests"] == [] and d["error"]
    calls = []
    _board_stub(monkeypatch, calls)
    assert cli.get("/api/contests").get_json()["contests"], "the failure must not stick"
    assert len(calls) == 1


# ---- the sweep recency guard ------------------------------------------------

def test_a_recent_sweep_short_circuits(tmp_path, monkeypatch, pixai):
    """The guard the spec asked for and never got: opening the overlay fired a full paced
    sweep every time."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    calls = []
    monkeypatch.setattr(core, "list_contests", lambda s, **k: calls.append(1) or [])
    assert g._contest_detection_sync(tmp_path) is True     # the real one
    assert len(calls) == 1
    assert g._contest_detection_sync(tmp_path) is True     # ...and the skip
    assert len(calls) == 1, "a sweep inside the window must not walk the board again"


def test_force_bypasses_the_recency_guard(tmp_path, monkeypatch, pixai):
    """The publish kick is confirming an entry it was just told about -- it can never be
    answered with 'we looked recently'."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": time.time()})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    calls = []
    monkeypatch.setattr(core, "list_contests", lambda s, **k: calls.append(1) or [])
    assert g._contest_detection_sync(tmp_path, force=True) is True
    assert len(calls) == 1


def test_a_failed_sweep_does_not_count_as_recent(tmp_path, monkeypatch, pixai):
    """Only a completed sweep buys the quiet window; a failure must be retried."""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)

    def _boom(*a, **k):
        raise core.PixAIError("the board is unreachable")
    monkeypatch.setattr(core, "list_contests", _boom)
    assert g._contest_detection_sync(tmp_path) is False
    assert g._contest_sync_last_ok["at"] == 0.0
    calls = []
    monkeypatch.setattr(core, "list_contests", lambda s, **k: calls.append(1) or [])
    assert g._contest_detection_sync(tmp_path) is True
    assert len(calls) == 1


def test_the_sync_route_tells_the_client_it_skipped(tmp_path, monkeypatch, pixai):
    """The client's re-pull is pointless after a skip, and it should be told rather than
    left to infer it from an unchanged number. (The route answers immediately now, so the
    first call is run inline to make the sweep actually happen.)"""
    monkeypatch.setattr(g, "_contest_sync_last_ok", {"at": 0.0})
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [])
    cli = _client(tmp_path)
    token = cli.get("/api/myart/items").get_json()["csrf"]
    real = g.threading.Thread
    monkeypatch.setattr(g.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None: type(
                            "T", (), {"start": lambda self_: target(*args, **(kwargs or {}))})())
    first = cli.post("/api/contest/sync", json={"csrf": token}).get_json()
    monkeypatch.setattr(g.threading, "Thread", real)
    assert first["started"] is True and "skipped" not in first
    second = cli.post("/api/contest/sync", json={"csrf": token}).get_json()
    assert second["started"] is False and second["skipped"] == "recent"
    assert "contest_entries" in second

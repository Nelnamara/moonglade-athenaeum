"""The overlay-open perf pass: the memos that stopped every overlay open from paying for a
full library walk, a live board pull, and a paced contest sweep (2026-09-03), plus
/api/health's own memo (2026-09-04).

Each test asserts the BEHAVIOUR the memo has to keep -- a cached answer is still a correct
answer, and an invalidation really invalidates -- rather than timing anything. Self-computing
where a roster or a metric is involved; no roster facts.
"""
import threading
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


# ---- the /api/health memo (2026-09-04) --------------------------------------
#
# collection_health() walks the whole library off disk. The route had a 120s TTL, which was
# wrong in both directions at once -- a change made 5s ago stayed invisible for two minutes,
# and a first open after two idle minutes paid the full walk with the user watching. It is
# now keyed on the CATALOG FILE with no time floor (the _ACH_METRICS_CACHE ruling, same
# reasoning), serves the previous answer while it recomputes, and is primed off-thread at
# boot. These pin all three of those, plus the ?fresh=1 bypass.


def _walk_stub(monkeypatch, calls, gate=None):
    """Stand in for the real library walk, counting calls and (optionally) blocking every
    call after the first on `gate` -- which is what makes 'served while recomputing'
    assertable without timing anything."""
    def _fake(out_dir, db_path):
        calls.append(1)
        if gate is not None and len(calls) > 1:
            assert gate.wait(10), "the gated walk was never released"
        return {"total_files": len(calls), "catalog_rows": len(calls)}
    monkeypatch.setattr(g, "collection_health", _fake)


def _settle(pred, timeout=10.0):
    """Wait for a background refresh to land. Polls a predicate rather than sleeping a
    guessed interval, so it is fast when it is fast and still honest on a slow machine."""
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_the_health_walk_is_memoized_between_opens(tmp_path, monkeypatch):
    """The walk that made Health 'VERY slow' at 35k images. Asking twice against an
    unchanged catalog must cost one walk."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls = []
    _walk_stub(monkeypatch, calls)
    first = g.health_cached(tmp_path, db)
    assert g.health_cached(tmp_path, db) == first
    assert g.health_cached(tmp_path, db) == first
    assert len(calls) == 1, "an unchanged catalog must be served from memory"


def test_a_changed_catalog_invalidates_the_health_memo(tmp_path, monkeypatch):
    """No time floor: the key is the catalog file itself, so a write invalidates at once
    rather than at the end of some window."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls = []
    _walk_stub(monkeypatch, calls)
    g.health_cached(tmp_path, db)
    save_catalog(db, [_row(media_id="1", filename="a_1.png"),
                      _row(media_id="2", filename="b_2.png")])
    g.health_cached(tmp_path, db)                      # notices, kicks the refresh
    assert _settle(lambda: len(calls) == 2), "a changed catalog must re-walk"
    assert _settle(lambda: g.health_cached(tmp_path, db)["catalog_rows"] == 2)


def test_the_stale_answer_is_served_WHILE_it_recomputes(tmp_path, monkeypatch):
    """The point of the whole design: the request that notices the catalog moved is not the
    one that pays for the new walk. It gets the previous payload straight back."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls, gate = [], threading.Event()
    _walk_stub(monkeypatch, calls, gate)
    try:
        first = g.health_cached(tmp_path, db)          # nothing cached: this one blocks
        save_catalog(db, [_row(media_id="1", filename="a_1.png"),
                          _row(media_id="2", filename="b_2.png")])
        served = g.health_cached(tmp_path, db)         # the walk behind this is still stuck
        assert served is first, "the previous payload must come back, not a fresh walk"
        assert _settle(lambda: len(calls) == 2), "the refresh must actually have started"
    finally:
        gate.set()
    assert _settle(lambda: g._HEALTH_CACHE["payload"] is not first)
    assert g.health_cached(tmp_path, db)["catalog_rows"] == 2


def test_a_burst_of_opens_starts_ONE_recompute(tmp_path, monkeypatch):
    """Single-flight. Six surfaces can ask inside the same second; six library walks is the
    stall this memo exists to remove, not a smaller version of it."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls, gate = [], threading.Event()
    _walk_stub(monkeypatch, calls, gate)
    try:
        g.health_cached(tmp_path, db)
        save_catalog(db, [_row(media_id="1", filename="a_1.png"),
                          _row(media_id="2", filename="b_2.png")])
        for _ in range(6):
            g.health_cached(tmp_path, db)
        assert _settle(lambda: len(calls) == 2)
        time.sleep(0.05)
        assert len(calls) == 2, "one recompute, however many readers noticed"
    finally:
        gate.set()
    assert _settle(lambda: not g._HEALTH_BUSY["on"])


def test_fresh_forces_a_real_walk(tmp_path, monkeypatch):
    """?fresh=1 is the explicit user refresh; it must never be answered from the memo."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls = []
    _walk_stub(monkeypatch, calls)
    g.health_cached(tmp_path, db)
    g.health_cached(tmp_path, db, fresh=True)
    assert len(calls) == 2
    assert g.health_cached(tmp_path, db)["total_files"] == 2, "and it re-seeds the memo"


def test_the_boot_prime_warms_the_memo(tmp_path, monkeypatch):
    """A perfect memo still leaves the FIRST open of a session slow -- the one that is
    actually noticed. main() primes it off-thread once the socket is bound."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    calls = []
    _walk_stub(monkeypatch, calls)
    g._health_prime(tmp_path, db).join(10)
    assert len(calls) == 1, "the prime does the walk"
    assert g.health_cached(tmp_path, db)["total_files"] == 1
    assert len(calls) == 1, "so the first real open walks nothing at all"


def test_the_prime_survives_a_library_it_cannot_walk(tmp_path, monkeypatch):
    """A boot nicety must never be able to stop the server from starting."""
    def _boom(out_dir, db_path):
        raise OSError("the library is on a disconnected drive")
    monkeypatch.setattr(g, "collection_health", _boom)
    g._health_prime(tmp_path, tmp_path / "catalog.db").join(10)
    assert g._HEALTH_CACHE["payload"] is None


def test_a_missing_catalog_still_memoizes(tmp_path, monkeypatch):
    """A library with no catalog.db yet is a real state (a fresh install), and os.stat
    raises there. It must answer, and answer from the memo the second time."""
    calls = []
    _walk_stub(monkeypatch, calls)
    assert g._health_key(tmp_path / "catalog.db") is None
    g.health_cached(tmp_path, tmp_path / "catalog.db")
    g.health_cached(tmp_path, tmp_path / "catalog.db")
    assert len(calls) == 1


def test_the_health_route_still_answers_correctly(tmp_path):
    """Driven through the real route with the real walk, twice -- the second is the cached
    path, and it must report the same numbers rather than a differently-shaped answer."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2026-01-01T00:00:00")])
    first = cli.get("/api/health").get_json()
    second = cli.get("/api/health").get_json()
    assert first == second
    assert first["catalog_rows"] == 1


def test_the_health_route_picks_up_a_changed_catalog(tmp_path):
    """End to end, no stubs: write the catalog and the route stops answering with the old
    numbers -- eventually by way of one stale answer, never permanently."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2026-01-01T00:00:00")])
    assert cli.get("/api/health").get_json()["catalog_rows"] == 1
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2026-01-01T00:00:00"),
                  _row(media_id="2", filename="b_2.png", created_at="2026-01-02T00:00:00")])
    cli.get("/api/health")                       # may legitimately serve the stale answer
    assert _settle(lambda: cli.get("/api/health").get_json()["catalog_rows"] == 2)


def test_fresh_on_the_route_never_serves_a_stale_answer(tmp_path):
    """The client sends ?fresh=1 only on an explicit user refresh, and that one must be
    true the instant it answers -- no stale-then-behind."""
    cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                  created_at="2026-01-01T00:00:00")])
    cli.get("/api/health")
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2026-01-01T00:00:00"),
                  _row(media_id="2", filename="b_2.png", created_at="2026-01-02T00:00:00")])
    assert cli.get("/api/health", query_string={"fresh": "1"}).get_json()["catalog_rows"] == 2


def test_collection_health_itself_stays_uncached(tmp_path):
    """The cache lives outside the computation, as it always has: the classic /health page
    and every test calling collection_health() directly get a real read every time."""
    db = _seed(tmp_path, [_row(media_id="1", filename="a_1.png")])
    g.health_cached(tmp_path, db)                                  # warm the memo
    save_catalog(db, [_row(media_id="1", filename="a_1.png"),
                      _row(media_id="2", filename="b_2.png")])
    assert g.collection_health(tmp_path, db)["catalog_rows"] == 2

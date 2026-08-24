"""The live-event WebSocket watcher (--watch). The real graphql-transport-ws transport is
mocked so nothing touches the network: we verify the handshake frames we SEND and that a
`next` frame is dispatched to on_event."""
import asyncio
import json

import websockets

import moonglade_backup as core


class _FakeWS:
    """Stands in for a graphql-transport-ws connection: an async context manager that
    records sent frames and replays a scripted server sequence from recv()."""
    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self._i = 0

    async def send(self, m):
        self.sent.append(json.loads(m))

    async def recv(self):
        if self._i >= len(self.script):
            raise AssertionError("recv() called past the scripted frames")
        f = self.script[self._i]
        self._i += 1
        return f

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _run(monkeypatch, script):
    ws = _FakeWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    asyncio.run(core._watch_events_async("Bearer sk-x", got.append, None))
    return ws, got


def test_watch_handshake_and_dispatch(monkeypatch):
    script = [
        json.dumps({"type": "connection_ack"}),
        json.dumps({"type": "next", "payload": {"data": {"personalEvents": {
            "taskUpdated": {"id": "T1", "status": "completed", "mediaId": "M1",
                            "media": {"urls": [{"url": "https://cdn/x"}]}},
            "newNotification": None}}}}),
        json.dumps({"type": "complete"}),
    ]
    ws, got = _run(monkeypatch, script)
    # we sent connection_init (with the token) then a subscribe for personalEvents
    assert ws.sent[0]["type"] == "connection_init"
    assert ws.sent[0]["payload"]["Authorization"] == "Bearer sk-x"
    assert ws.sent[1]["type"] == "subscribe"
    assert "personalEvents" in ws.sent[1]["payload"]["query"]
    # on_event saw the 'subscribed' marker then the real taskUpdated event
    assert got[0].get("__meta__") == "subscribed"
    tu = [e for e in got if e.get("taskUpdated")]
    assert tu and tu[0]["taskUpdated"]["status"] == "completed"


def test_watch_answers_ping_and_raises_on_error(monkeypatch):
    # server ping -> we must pong; then an error frame must raise (subscription rejected)
    script = [
        json.dumps({"type": "connection_ack"}),
        json.dumps({"type": "ping"}),
        json.dumps({"type": "error", "payload": [{"message": "bad field"}]}),
    ]
    ws = _FakeWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    try:
        asyncio.run(core._watch_events_async("Bearer x", lambda e: None, None))
        assert False, "expected PixAIError on the error frame"
    except core.PixAIError as e:
        assert "rejected" in str(e)
    assert any(m.get("type") == "pong" for m in ws.sent)   # replied to the ping


def test_watch_backup_mirrors_completed_only(monkeypatch, tmp_path):
    """--watch-backup mirrors a task the instant it hits 'completed' (and only then), once."""
    import threading
    from types import SimpleNamespace

    # feed a full lifecycle through a fake transport, synchronously
    async def fake_watch(auth, on_event, seconds):
        on_event({"__meta__": "subscribed"})
        on_event({"taskUpdated": {"id": "T9", "status": "waiting"}})
        on_event({"taskUpdated": {"id": "T9", "status": "running"}})
        on_event({"taskUpdated": {"id": "T9", "status": "completed", "mediaId": "M9"}})
        on_event({"taskUpdated": {"id": "T9", "status": "completed", "mediaId": "M9"}})  # dup
    monkeypatch.setattr(core, "_watch_events_async", fake_watch)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())

    class _FakeThread:   # run the mirror synchronously so the test is deterministic
        def __init__(self, target=None, args=(), daemon=None):
            self._t, self._a = target, args
        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    calls = []
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: calls.append(tid) or {"saved": 4})

    args = SimpleNamespace(token=None, watch_seconds=0, watch_backup=True, out=str(tmp_path))
    core.run_watch(args)
    assert calls == ["T9"]   # mirrored exactly once, only on 'completed' (waiting/running ignored)


class _Sess:
    headers = {"Authorization": "Bearer sk-x"}


def test_watch_no_ack_raises(monkeypatch):
    ws = _FakeWS([json.dumps({"type": "connection_error", "payload": "nope"})])
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    try:
        asyncio.run(core._watch_events_async("Bearer x", lambda e: None, None))
        assert False, "expected PixAIError when no connection_ack"
    except core.PixAIError as e:
        assert "handshake" in str(e).lower()


# --- Staleness watchdog ----------------------------------------------------------
# The real incident this guards against: the WebSocket never errored and never sent
# a close frame -- it just stopped producing ANY frame, including PixAI's own
# keepalive pings, for ~21 minutes while real generations were finishing. Before this
# fix, the receive loop's `await ws.recv()` had no timeout at all, so a socket in
# that state hung the loop forever: `connected` stayed True and `last_error` stayed
# None indefinitely (verified live via `/api/watch/status`), and nothing in
# `_watch_loop`'s outer reconnect/backoff logic ever ran because no exception was
# ever raised to trigger it.

class _SilentAfterAckWS(_FakeWS):
    """Answers the connection_ack handshake normally, then goes silent forever on
    every subsequent recv() -- exactly a zombie connection that looks open but
    produces nothing, not even a ping."""
    async def recv(self):
        if self._i < len(self.script):
            return await super().recv()
        # No more scripted frames: block far longer than any timeout under test,
        # so this only resolves if something is broken and the wait_for around it
        # failed to cancel us.
        await asyncio.sleep(10)
        raise AssertionError("recv() blocked past its wait_for timeout -- the "
                              "staleness watchdog did not fire")


def test_watch_raises_when_connection_goes_stale_despite_looking_healthy(monkeypatch):
    """Fail-first case: reproduces 'connected but silently dead'. A tiny
    _WS_STALE_TIMEOUT stands in for the real several-minute one so the test itself
    stays fast; the mechanism under test is the same either way -- ws.recv() is
    awaited with a timeout, and a lapse raises WatchStaleError instead of hanging."""
    monkeypatch.setattr(core, "_WS_STALE_TIMEOUT", 0.05)
    ws = _SilentAfterAckWS([json.dumps({"type": "connection_ack"})])
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    try:
        asyncio.run(core._watch_events_async("Bearer x", got.append, None))
        assert False, "expected WatchStaleError when the socket goes silent"
    except core.WatchStaleError as e:
        assert "no frame" in str(e).lower()             # says what happened
        assert str(core._WS_STALE_TIMEOUT) in str(e)    # names the timeout it hit
        # WatchStaleError must still be a PixAIError so nothing that already does a
        # bare `except PixAIError` (or `except Exception`, like _watch_loop) needs
        # to change to start handling it.
        assert isinstance(e, core.PixAIError)
    # subscribed fired first -- this is genuinely the "looked connected" case, not a
    # handshake failure.
    assert got and got[0].get("__meta__") == "subscribed"


def test_watch_pings_reset_the_staleness_clock(monkeypatch):
    """Companion/negative case: a steady trickle of frames -- even bare keepalive
    pings, no real taskUpdated events -- must NOT trip the watchdog, since a quiet
    account (no generations running) is a normal, healthy state, not a stale one."""
    # THE NUMBERS ARE THE TEST -- do not "simplify" them.
    #
    # The watchdog is a per-frame `asyncio.wait_for(ws.recv(), timeout=_WS_STALE_TIMEOUT)`, so
    # what proves the clock RESETS per frame is: every individual gap stays under the timeout
    # while the TOTAL run comfortably exceeds it. A cumulative clock would lapse partway
    # through. Raising the timeout without also lengthening the script would make this pass
    # even with the reset logic deleted -- vacuous, not robust.
    #
    # Ratios chosen for that meaning AND against CI flake. This previously ran a 0.05s timeout
    # against a 0.01s pace: only a 5x per-frame margin, which a loaded runner (three suites in
    # parallel) overshoots, failing a test about staleness for reasons that have nothing to do
    # with staleness. Now 0.02s per frame against a 0.5s timeout -- a 25x margin, so a single
    # frame would have to stall 25x its sleep to trip it -- while 40 frames total ~0.8s, still
    # well past the 0.5s timeout a cumulative clock would have hit around frame 25.
    PACE, TIMEOUT, PINGS = 0.02, 0.5, 40
    assert PACE * PINGS > TIMEOUT, "script must outlast the timeout or this proves nothing"
    monkeypatch.setattr(core, "_WS_STALE_TIMEOUT", TIMEOUT)
    script = [json.dumps({"type": "connection_ack"})]
    script += [json.dumps({"type": "ping"})] * PINGS
    script += [json.dumps({"type": "complete"})]

    class _PacedWS(_FakeWS):
        async def recv(self):
            await asyncio.sleep(PACE)   # well inside the timeout -- never lets it lapse
            return await super().recv()

    ws = _PacedWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    asyncio.run(core._watch_events_async("Bearer x", got.append, None))   # must not raise
    assert any(m.get("type") == "pong" for m in ws.sent)   # still answered every ping


def test_mirror_and_reconcile_agree_on_what_done_means():
    """The live mirror's COLLECT branch and its RECONCILE branch read the same event, so they
    must agree on which statuses mean finished.

    They did not. Collect matched `status == _WS_DONE_STATUS` -- one exact string -- while
    reconcile accepted `status in _GEN_DONE`, which is five. A done-status PixAI spelled any
    other way would therefore resolve the Activity row while silently NOT mirroring the file,
    which looks exactly like the "my video never came into the gallery" report that found this
    (2026-07-26) and is just as invisible after the fact.

    Asserted against the source because the branch lives inside a nested on_event closure in a
    background thread, which no unit test can reach directly. A source check that pins the
    intent beats no check at all here."""
    import pathlib as _p
    src = _p.Path(__file__).resolve().parent.parent / "moonglade_gallery.py"
    text = src.read_text(encoding="utf-8")

    i = text.index("def _watch_loop()")
    loop = text[i:i + 4000]

    assert "if status in core._GEN_DONE and tid and tid not in backed:" in loop, (
        "the mirror's collect branch must accept every _GEN_DONE status, not one exact string")
    assert "status == core._WS_DONE_STATUS" not in loop, (
        "the single-status collect trigger is back -- see this test's docstring")

    # And the constant it now shares really is the broader set.
    assert core._WS_DONE_STATUS in core._GEN_DONE
    assert len(core._GEN_DONE) > 1


def test_catchup_sweep_is_bounded_rate_limited_and_off_thread():
    """The mirror back-fills what it missed while disconnected, and does so safely.

    A push mirror is blind whenever its socket is down, and reconnecting does not replay the gap
    -- so before this, a drop stranded those generations until someone ran a manual sync. The
    owner's objection was the right one: he should not have to press a button for it.

    But this is UNATTENDED network activity on his machine, so the guardrails matter as much as
    the feature. This test pins the guardrails at SOURCE level; its behavioural companion
    (test_catchup_backfills_absent_media_skips_present_and_rate_limits) drives the same closure
    through the app.extensions["mg_watch_catchup"] seam and proves the gap-fill / skip / rate-limit
    actually run. _watch_catchup is invoked only from a background thread the suite never starts
    (MOONGLADE_DISABLE_WATCH), so both angles are worth keeping."""
    import pathlib as _p
    src = _p.Path(__file__).resolve().parent.parent / "moonglade_gallery.py"
    text = src.read_text(encoding="utf-8")

    assert "def _watch_catchup(reason):" in text

    i = text.index("def _watch_catchup(reason):")
    body = text[i:i + 3200]

    # Bounded: one page, never a history walk. WATCH_CATCHUP_TASKS is the page size passed to
    # page_variables; the account id now rides the client (USER_ID retired from page_variables),
    # so the catchup threads it explicitly rather than leaning on a module global.
    assert "WATCH_CATCHUP_TASKS = 30" in text
    assert "core.page_variables(" in body
    assert "WATCH_CATCHUP_TASKS, core._client_of(session).user_id" in body

    # Rate-limited: a reconnect storm must not become a request storm.
    assert "WATCH_CATCHUP_MIN_GAP" in body and "_catchup_at" in body

    # Only collects what is genuinely absent -- re-collecting present media is pure waste.
    assert "if all(get_row(db_path, m) for m in mids):" in body

    # Paced, so it stays polite to PixAI's servers.
    assert "_time.sleep(1.0)" in body

    # Cannot kill the watcher thread that calls it.
    assert "except Exception as e:" in body

    # Only finished tasks are candidates.
    assert "core._GEN_DONE" in body

    # And it is invoked OFF the WebSocket event loop, at both trigger points.
    assert 'threading.Thread(target=_watch_catchup, args=("startup",), daemon=True).start()' in text
    assert 'threading.Thread(target=_watch_catchup, args=("reconnect",),' in text


def test_catchup_does_not_run_in_the_test_suite():
    """Belt and braces: the sweep must never fire during tests, or the suite would hit PixAI with
    whatever real credentials are on the machine. It is reachable only from the watcher thread,
    which conftest disables via MOONGLADE_DISABLE_WATCH."""
    import os
    assert os.environ.get("MOONGLADE_DISABLE_WATCH") == "1"


def test_catchup_backfills_absent_media_skips_present_and_rate_limits(monkeypatch, tmp_path):
    """BEHAVIOURAL companion to the source-level guard above: actually EXECUTE the self-heal
    sweep through the mg_watch_catchup seam and prove the recovery the ROADMAP requires —
    "the piece must appear on its own, no manual sync." It must:
      - COLLECT a finished task whose media the catalog is missing (the gap-fill);
      - SKIP a finished task already present (idempotent — re-collecting is pure waste),
        a non-done task, and a done task with no media;
      - RATE-LIMIT: a second sweep inside WATCH_CATCHUP_MIN_GAP is a no-op, even though the
        gap notionally still exists.
    (The live stop-server / generate-while-down / restart recipe stays the owner's to run;
    this pins the logic that recipe exercises so it can't silently regress.)"""
    import time
    import moonglade_gallery as mg
    from moonglade_gallery import create_app

    app = create_app(tmp_path)
    catchup = app.extensions["mg_watch_catchup"]        # the new seam

    # One page of recent tasks: finished+absent (collect), finished+present (skip),
    # running (skip), finished+no-media (skip).
    edges = [
        {"node": {"id": "T_absent", "status": "completed"}},
        {"node": {"id": "T_present", "status": "completed"}},
        {"node": {"id": "T_running", "status": "running"}},
        {"node": {"id": "T_nomedia", "status": "completed"}},
    ]
    media = {"T_absent": ["M_absent"], "T_present": ["M_present"],
             "T_running": ["M_run"], "T_nomedia": []}
    present = {"M_present"}                             # only this media is already catalogued

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core, "find_connection", lambda *a, **k: {"edges": edges})
    monkeypatch.setattr(core, "media_ids_for", lambda node: media.get(str(node.get("id")), []))
    monkeypatch.setattr(mg, "get_row", lambda db_path, m: (object() if m in present else None))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)   # keep the paced sweep fast

    collected = []
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: collected.append(str(tid)) or {"saved": 1})

    catchup("startup")
    assert collected == ["T_absent"]     # ONLY the finished task whose media was missing

    # Rate limit: a second sweep inside WATCH_CATCHUP_MIN_GAP does nothing — the gap still
    # "exists" (get_row still reports M_absent absent), but the floor suppresses the sweep.
    catchup("reconnect")
    assert collected == ["T_absent"]     # no second collection

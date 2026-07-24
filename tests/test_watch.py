"""The live-event WebSocket watcher (--watch). The real graphql-transport-ws transport is
mocked so nothing touches the network: we verify the handshake frames we SEND and that a
`next` frame is dispatched to on_event."""
import asyncio
import json

import websockets

import pixai_gallery_backup as core


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
    monkeypatch.setattr(core, "_WS_STALE_TIMEOUT", 0.05)
    script = [json.dumps({"type": "connection_ack"})]
    script += [json.dumps({"type": "ping"})] * 5   # each one comfortably under 0.05s apart
    script += [json.dumps({"type": "complete"})]

    class _PacedWS(_FakeWS):
        async def recv(self):
            await asyncio.sleep(0.01)   # well inside the timeout -- never lets it lapse
            return await super().recv()

    ws = _PacedWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    asyncio.run(core._watch_events_async("Bearer x", got.append, None))   # must not raise
    assert any(m.get("type") == "pong" for m in ws.sent)   # still answered every ping

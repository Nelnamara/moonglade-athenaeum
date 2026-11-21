"""The REST task stream (3.22, design section 4). Offline: a fake session stands in for
GET /v2/events/task_updated, a fake clock and sleep drive the backoff, and nothing opens a socket."""
import logging
import threading

import pytest
import requests

from moonglade import task_feed as tf


# P2's recorded framing: `: connected`, `: keep-alive` comments, a data event, an idle `done`.
P2_LINES = [
    ": connected", "",
    ": keep-alive", "",
    'data: {"type":"task_updated","data":{"id":"T1","status":"running",'
    '"updatedAt":"2026-11-19T10:00:00.000Z","outputs":{"mediaIds":["M1"]}}}', "",
    "event: done", 'data: {"reason":"idle"}', "",
]


class _Resp:
    def __init__(self, status=200, lines=(), raises=None, text=""):
        self.status_code, self._lines, self._raises, self.text = status, list(lines), raises, text
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        for ln in self._lines:
            yield ln
        if self._raises is not None:
            raise self._raises

    def close(self):
        self.closed = True


class _Sess:
    """Records every call. Only `get` exists: a POST/PUT/PATCH/DELETE would be an AttributeError."""
    def __init__(self, *resps):
        self.resps, self.calls = list(resps), []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resps.pop(0)


def _rig(*resps, frames=None, clock=None):
    clock = clock if clock is not None else {"t": 0.0}
    sess = _Sess(*resps)
    status = tf.new_stream_status()
    got, asked, slept = [], [], []
    stream = tf.TaskStream(
        make_session=lambda: sess, on_task=got.append,
        request_catchup=asked.append, status=status, lock=threading.Lock(),
        clock=lambda: clock["t"], sleep=slept.append, rand=lambda: 0.5,
        idle_wait=lambda s: slept.append(("idle", s)) or False,
        log=logging.getLogger("test.task_stream"))
    return stream, sess, status, got, asked, slept, clock


def test_sse_parser_reads_p2_frames():
    p = tf.SSEParser()
    events = [e for e in (p.feed(l) for l in P2_LINES) if e]
    assert p.comments == 2
    assert [e["event"] for e in events] == ["message", "done"]
    assert events[1]["data"] == '{"reason":"idle"}'


def test_adapter_shapes_the_frame_the_watcher_reads():
    f = tf.adapt_task_frame({"type": "task_updated", "data": {
        "id": 7, "status": "completed", "updatedAt": "2026-11-19T10:00:00Z",
        "outputs": {"mediaIds": ["A", "B"]}}})
    assert f == {"id": "7", "status": "completed", "updatedAt": "2026-11-19T10:00:00Z", "mediaId": "A"}
    v = tf.adapt_task_frame({"data": {"id": "9", "status": "completed", "videoMediaId": "V"}})
    assert v["mediaId"] == "V"
    assert tf.adapt_task_frame({"data": {"status": "x"}}) is None
    assert tf.adapt_task_frame("nope") is None


def test_stale_frame_rule():
    a = {"id": "1", "status": "running", "updatedAt": "2026-11-19T10:00:05Z"}
    older = {"id": "1", "status": "waiting", "updatedAt": "2026-11-19T10:00:01Z"}
    assert tf.is_stale_frame(a, older)
    same_instant_lower = {"id": "1", "status": "waiting", "updatedAt": "2026-11-19T10:00:05Z"}
    assert tf.is_stale_frame(a, same_instant_lower)
    newer = {"id": "1", "status": "completed", "updatedAt": "2026-11-19T10:00:09Z"}
    assert not tf.is_stale_frame(a, newer)
    assert not tf.is_stale_frame(a, dict(a))          # a duplicate passes (collectors are single-flight)
    assert not tf.is_stale_frame(None, a)


def test_an_open_stream_is_get_only_with_the_45s_read_timeout_and_asks_for_a_catchup():
    stream, sess, status, got, asked, slept, _ = _rig(_Resp(lines=P2_LINES))
    assert stream.cycle() == ("idle", 0)
    (url, kw), = sess.calls
    assert url == tf.TASK_STREAM_URL
    assert kw["timeout"] == (10, 45) and kw["stream"] is True and kw["allow_redirects"] is False
    assert kw["headers"]["Accept"] == "text/event-stream"
    assert asked == ["stream-connect"]
    assert got == [{"id": "T1", "status": "running", "updatedAt": "2026-11-19T10:00:00.000Z", "mediaId": "M1"}]
    assert status["state"] == "idle" and status["last_end_reason"] == "idle"
    assert status["failures"] == 0 and status["last_event_at"] is not None


def test_a_stale_frame_is_not_dispatched():
    lines = [
        'data: {"data":{"id":"T","status":"running","updatedAt":"2026-11-19T10:00:09Z"}}', "",
        'data: {"data":{"id":"T","status":"waiting","updatedAt":"2026-11-19T10:00:01Z"}}', "",
        "event: done", 'data: {"reason":"idle"}', "",
    ]
    stream, _s, _st, got, *_ = _rig(_Resp(lines=lines))
    stream.cycle()
    assert [g["status"] for g in got] == ["running"]


def test_idle_end_is_not_a_failure_and_reopens_after_ten_minutes():
    stream, sess, status, got, asked, slept, _ = _rig(
        _Resp(lines=P2_LINES), _Resp(status=401, text="{}"))
    stream.run()
    assert status["failures"] == 0
    assert ("idle", tf.STREAM_IDLE_REOPEN_S) in slept
    assert len(sess.calls) == 2           # reopened once, then the 401 stopped it


def test_a_create_or_sweep_wakes_an_idle_stream():
    stream, *_ = _rig()
    assert not stream.wake.is_set()
    stream.request_reopen("create")
    assert stream.wake.is_set()


@pytest.mark.parametrize("status,body", [(401, "{}"), (400, '{"message":"Unknown client platform"}'),
                                         (200, None)])
def test_auth_refusals_stop_the_stream_and_say_so(status, body):
    if body is None:                                   # an in-stream UNAUTHORIZED error event
        resp = _Resp(lines=["event: error", 'data: {"code":"UNAUTHORIZED"}', ""])
    else:
        resp = _Resp(status=status, text=body)
    stream, sess, st, *_ = _rig(resp)
    stream.run()
    assert st["state"] == "stopped" and "API key" in st["stopped_reason"]
    assert len(sess.calls) == 1 and stream.stopped


def test_429_is_capped_not_a_failure_and_backs_off_from_30s():
    stream, sess, st, got, asked, slept, _ = _rig(_Resp(status=429, text="TOO_MANY_STREAMS"))
    kind, wait = stream.cycle()
    assert kind == "wait" and wait == pytest.approx(30.0)      # rand=0.5 -> factor 1.0
    assert st["failures"] == 0 and st["capped"] == 1 and st["state"] == "capped"
    assert asked == []


def test_503_backs_off_from_1s_doubling_to_30s():
    stream, sess, st, *_ = _rig(*[_Resp(status=503) for _ in range(8)])
    waits = [stream.cycle()[1] for _ in range(8)]
    assert waits[:3] == pytest.approx([1.0, 2.0, 4.0])
    assert max(waits) == pytest.approx(30.0)
    assert st["failures"] == 8


def test_a_45s_silence_raises_and_counts_as_a_failure_when_young():
    stream, sess, st, got, asked, slept, clock = _rig(
        _Resp(raises=requests.exceptions.ReadTimeout("Read timed out")))
    kind, wait = stream.cycle()
    assert kind == "wait" and st["failures"] == 1 and st["last_end_reason"] == "silent"


def test_p2s_broken_chunked_ending_after_a_healthy_run_is_a_drop_not_a_failure():
    clock = {"t": 0.0}

    class _Late(_Resp):
        def iter_lines(self, decode_unicode=False):
            clock["t"] += 63.0                        # P2: dropped at 63 s
            raise requests.exceptions.ChunkedEncodingError("Connection broken")
            yield
    stream, sess, st, *_ = _rig(_Late(), clock=clock)
    kind, wait = stream.cycle()
    assert kind == "wait" and wait == pytest.approx(1.0)
    assert st["failures"] == 0 and st["last_end_reason"] == "dropped"


def test_the_stream_never_writes_the_websockets_status_fields(tmp_path):
    """T-F10: frames go through the watcher's handler, which touches only events_seen and
    last_event_at; connected, last_error and last_close_at stay the socket's."""
    from moonglade.gallery import create_app
    from moonglade.catalog import CATALOG_FIELDS, save_catalog
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}])
    app = create_app(tmp_path)
    ws = app.extensions["mg_watch_status"]
    before = {k: ws[k] for k in ("connected", "last_error", "last_close_at", "connected_at",
                                 "last_close", "reconnects")}
    stream = app.extensions["mg_task_stream"]
    sess = _Sess(_Resp(lines=[
        'data: {"data":{"id":"RUN1","status":"running","updatedAt":"2026-11-19T10:00:00Z"}}', "",
        "event: done", 'data: {"reason":"idle"}', ""]))
    stream.make_session = lambda: sess
    stream.request_catchup = lambda reason: None
    assert stream.cycle() == ("idle", 0)
    assert {k: ws[k] for k in before} == before
    assert ws["events_seen"] == 1
    assert ws["task_stream"]["state"] == "idle"


def test_the_websocket_document_is_notifications_only():
    assert "taskUpdated" not in tf._WS_SUBSCRIPTION
    assert "newNotification { id title createdAt userId }" in tf._WS_SUBSCRIPTION


def test_the_stream_client_sends_nothing_but_gets():
    import inspect
    src = inspect.getsource(tf.TaskStream)
    for verb in (".post(", ".put(", ".patch(", ".delete(", "rest_post", "mutate"):
        assert verb not in src
    assert src.count("sess.get(") == 1

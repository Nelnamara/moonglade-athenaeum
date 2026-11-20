"""
moonglade/task_feed.py
======================
The live task feed: PixAI's WebSocket event push (`_watch_events_async`, its subscription,
staleness and heartbeat constants) and `--watch` (`run_watch`). Moved verbatim out of
moonglade/backup.py in the 3.22 split (phase 5).

It collects a finished task through `_gen_road.collect_generation`, the way the engine did once
the road moved out. The names it reads from the engine (_make_session, PixAIError,
WatchStaleError) are imported from moonglade.backup inside each function that uses them, at
call time, so a test's patch of backup's binding still reaches them and importing this module
never imports the engine.
"""
import json
import sys
import time

from moonglade import gen_road as _gen_road
from moonglade import paths as _paths



# --- Live event push (WebSocket) ------------------------------------------------
# PixAI pushes personal events over a graphql-transport-ws WebSocket at
# wss://gw.pixai.art/graphql -- a SEPARATE transport from the api.pixai.art HTTP API.
# The `personalEvents` subscription (no args) streams two channels: `taskUpdated`
# (your generations changing state) and `newNotification`. Listening is READ-ONLY and
# far gentler on PixAI than periodic polling. Confirmed reachable with the same Bearer
# token the tool already holds (see ../moonglade-internal/private/APP_OPERATIONS_FULL.md).
#
# STATUS: this `--watch` command is the shipped live monitor. With --watch-backup it
# is also the event-driven backup mode -- each task's 'completed' frame (confirmed
# lifecycle below) triggers an immediate download + catalog, instead of waiting on
# the next polling pass.
_WS_URI = "wss://gw.pixai.art/graphql"
# 3.22: notifications only. The site removed `taskUpdated` from its own document, and a
# server that drops a field we ask for answers with an `error` frame, which would take the
# gift box's push down with it. Task changes ride the REST stream (TaskStream, below).
_WS_SUBSCRIPTION = (
    "subscription Watch { personalEvents { "
    "newNotification { id title createdAt userId } } }")
# Confirmed lifecycle: waiting -> running -> completed. The
# 'completed' frame is the one carrying a populated mediaId, so that's when we mirror.
_WS_DONE_STATUS = "completed"

# How long the receive loop below will wait for the NEXT frame off the wire --
# a `next` event, a `newNotification`, or even just a server `ping` keepalive --
# before deciding the connection is a zombie and forcing a reconnect. This is
# NOT "no taskUpdated in N seconds" (an account can be legitimately idle for
# hours between generations); it is "nothing at all arrived, including PixAI's
# own keepalive pings", which is what a genuinely dead-but-not-yet-errored
# socket looks like -- exactly the incident this guards against: `connected`
# stayed True and `last_error` stayed None for ~21 minutes while real
# generations finished and produced zero `taskUpdated` frames.
#
# Picking the number: the two things we actually know are (1) real generations
# in the incident finished in under a minute on PixAI's side, so any live
# session doing real work produces frames on a sub-minute cadence, not a
# multi-minute one; and (2) the failure was silent for ~21 minutes, so the
# threshold needs to be decisively shorter than that to matter, while staying
# well clear of ordinary lulls (a slow multi-minute video render between
# frames, a user idling between submissions) so a healthy connection is never
# cycled just for being briefly quiet. 240s (4 minutes) sits in the middle of
# that gap: an order of magnitude past any real per-frame cadence we've
# observed (so no thrash under normal bursty use), but leaves ~5x headroom
# before it would matter compared to tonight's ~20-minute silent gap, and
# lines up with the same magnitude as this app's other liveness clocks
# (--poll-timeout's 300s generate default; JOBS_ORPHAN_SWEEP_AGE's much
# coarser 30-minute sweep is a different, slower-moving safety net, not a
# reason to match it here).
_WS_STALE_TIMEOUT = 240

# OUR OWN KEEPALIVE (2026-09-29). The clock above assumed PixAI pings an idle
# subscription. It does not: every idle stretch in the logs since 2026-09-04 reads
# "connected and subscribed" followed, exactly 240s later, by "socket went silent",
# with the catch-up sweep then finding nothing missed -- a healthy, quiet account
# declared dead every four minutes, and the Control Panel read "Reconnecting ...
# treating the connection as dead" for the minute of backoff after each one. The
# protocol lets EITHER side ping, and the receiver must answer with a pong, so after
# this many seconds of quiet the client sends its own graphql-transport-ws `ping`;
# the server's `pong` is a frame like any other and resets the stale clock. A
# connection that answers nothing -- not even our ping -- still goes stale at
# _WS_STALE_TIMEOUT exactly as before. (The websockets library's own RFC 6455 pings
# are control frames recv() never returns, so they cannot reset this clock.)
_WS_HEARTBEAT = 60


async def _watch_events_async(auth_header, on_event, seconds):
    """Connect, handshake, subscribe to personalEvents, and dispatch each `next` frame's
    payload to on_event(dict). Replies to server pings, and after `_WS_HEARTBEAT` seconds
    of quiet sends a ping of its own (see that constant). Runs until `seconds` elapses
    (None = until cancelled). Read-only: sends only connection_init / subscribe / ping /
    pong / complete.

    Every frame off the wire -- a `next`, a `ping`, the `pong` to our ping, anything --
    resets a `_WS_STALE_TIMEOUT`-second clock. If that clock lapses, raises WatchStaleError
    instead of waiting forever on a socket that reports no error but has gone
    silent (see `_WS_STALE_TIMEOUT`'s comment for why that happens and how the
    number was picked). WatchStaleError is just another exception out of this
    coroutine, so any caller that already reconnects on failure -- `_watch_loop`
    in moonglade/gallery.py's outer while-True/backoff, and `run_watch` below's own
    try/except -- handles it for free with no special-casing needed at the call
    site; it exists only so a caller that WANTS to tell "went stale" apart from
    "socket errored" can."""
    from moonglade.backup import PixAIError, WatchStaleError
    import asyncio
    import websockets
    async def _run():
        async with websockets.connect(
                _WS_URI, subprotocols=["graphql-transport-ws"],
                additional_headers={"Origin": "https://pixai.art"}) as ws:
            await ws.send(json.dumps({"type": "connection_init",
                                      "payload": {"Authorization": auth_header}}))
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if ack.get("type") != "connection_ack":
                raise PixAIError("WebSocket handshake failed (no connection_ack): {!r}".format(ack))
            await ws.send(json.dumps({"id": "watch", "type": "subscribe",
                                      "payload": {"query": _WS_SUBSCRIPTION}}))
            on_event({"__meta__": "subscribed"})
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _WS_STALE_TIMEOUT
            while True:
                # Wait for the next frame, but never past the staleness deadline, and never
                # longer than one heartbeat: a quiet heartbeat sends our ping and waits on.
                left = deadline - loop.time()
                wait = min(_WS_HEARTBEAT, max(left, 0))
                try:
                    # recv() is cancellation-safe in websockets' asyncio client: a timed-out
                    # wait loses no frame, the next recv() returns it.
                    raw = await asyncio.wait_for(ws.recv(), timeout=wait)
                except asyncio.TimeoutError:
                    if wait >= left:
                        # Converted to a WatchStaleError HERE, not left as a bare
                        # asyncio.TimeoutError, so it can never be mistaken for (or
                        # accidentally swallowed by) the outer bounded-run timeout
                        # below, which catches that same exception type for a
                        # completely different reason (the `seconds` run budget).
                        raise WatchStaleError(
                            "no frame from PixAI in {}s (not even a reply to our keepalive "
                            "ping) -- treating the connection as dead".format(_WS_STALE_TIMEOUT))
                    await ws.send(json.dumps({"type": "ping"}))
                    continue
                deadline = loop.time() + _WS_STALE_TIMEOUT
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "ping":
                    await ws.send(json.dumps({"type": "pong"})); continue
                if mtype == "error":
                    raise PixAIError("subscription rejected: {}".format(
                        json.dumps(msg.get("payload"))))
                if mtype == "complete":
                    break
                if mtype == "next":
                    ev = (((msg.get("payload") or {}).get("data") or {})
                          .get("personalEvents") or {})
                    on_event(ev)
    if seconds:
        try:
            await asyncio.wait_for(_run(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
    else:
        await _run()


def run_watch(args):
    """CLI: live-monitor your PixAI events over the push WebSocket (read-only). Prints each
    taskUpdated / newNotification as it arrives. With --watch-backup, a task reaching
    'completed' is downloaded + cataloged the instant it finishes -- event-driven backup
    (the polling loop becomes a fallback, not the default). This is the 'live mirror' mode."""
    from moonglade.backup import _make_session
    import asyncio
    import threading
    session = _make_session(getattr(args, "token", None))
    auth = session.headers.get("Authorization")
    if not auth:
        print("No Authorization token on the session -- check your API key.")
        return
    seconds = getattr(args, "watch_seconds", 0) or None
    do_backup = bool(getattr(args, "watch_backup", False))
    out_dir = getattr(args, "out", _paths.DEFAULT_LIBRARY_DIR) or _paths.DEFAULT_LIBRARY_DIR
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):
        return str(t).encode(enc, "replace").decode(enc, "replace")

    seen = {"n": 0, "saved": 0}
    backed = set()   # task ids already mirrored this session (a 'completed' can repeat)

    def _mirror(tid):
        """Download + catalog one finished task off the event loop (own session per thread)."""
        try:
            res = _gen_road.collect_generation(_make_session(getattr(args, "token", None)), tid, out_dir)
            n = res.get("saved") or 0
            seen["saved"] += n
            print("      -> mirrored task {}: {} file(s) {}".format(
                tid, n, "[video]" if res.get("is_video") else ""))
        except Exception as e:
            print("      -> backup of task {} failed: {}".format(tid, _safe(str(e)[:140])))

    def on_event(ev):
        if ev.get("__meta__") == "subscribed":
            mode = "mirroring completed tasks -> {}".format(out_dir) if do_backup else "monitor only"
            print("[*] connected + subscribed to personalEvents ({}). Listening".format(mode)
                  + (" for {}s".format(seconds) if seconds else " (Ctrl-C to stop)") + "...\n")
            return
        seen["n"] += 1
        tu = ev.get("taskUpdated")
        nn = ev.get("newNotification")
        if tu:
            urls = (((tu.get("media") or {}).get("urls")) or [])
            url = (urls[0].get("url") if urls else "") or ""
            status = tu.get("status")
            tid = str(tu.get("id") or "")
            print("  [taskUpdated] status={:<14} task={} media={} {}".format(
                _safe(status), tid or "-", tu.get("mediaId") or "-", _safe(url)[:70]))
            if do_backup and status == _WS_DONE_STATUS and tid and tid not in backed:
                backed.add(tid)
                threading.Thread(target=_mirror, args=(tid,), daemon=True).start()
        if nn:
            print("  [notification] {} — {}".format(
                _safe(nn.get("title")), (nn.get("createdAt") or "")[:19]))
        if not tu and not nn:
            print("  [event] " + _safe(json.dumps(ev))[:200])

    # 3.22: task changes ride the REST stream now (the socket carries notifications only),
    # so the CLI runs the same client beside the socket and feeds its frames to on_event.
    import logging
    import threading as _th
    from moonglade import mirror as _mirror_mod
    stream = TaskStream(
        make_session=lambda: _mirror_mod.present_as_web(_make_session(getattr(args, "token", None))),
        on_task=lambda frame: on_event({"taskUpdated": frame}),
        request_catchup=lambda reason: None,
        status=new_stream_status(), lock=_th.Lock(), log=logging.getLogger(__name__))
    _th.Thread(target=stream.run, daemon=True).start()

    print("Watching PixAI live events at {} and {} (read-only; gentler than polling).".format(
        _WS_URI, TASK_STREAM_URL))
    try:
        asyncio.run(_watch_events_async(auth, on_event, seconds))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("\nWatch ended: {}".format(_safe(str(e)[:200])))
        return
    msg = "\nStopped. Saw {} event(s)".format(seen["n"])
    if do_backup:
        msg += ", mirrored {} file(s)".format(seen["saved"])
    print(msg + ".")


# --- The REST task stream (3.22) --------------------------------------------------
# PixAI's site now reads task changes from `GET /v2/events/task_updated`, a server-sent
# event stream (design 4, probe P2). GET only, on its own thread, on the API key presenting
# as the website (the app identity dropped at 63 s in P2; the Mirror JWT is reserved for the
# create POST). It keeps its own status record and never writes the WebSocket's fields.
TASK_STREAM_URL = "https://gw.pixai.art/v2/events/task_updated"
# P2 measured a `: keep-alive` comment every 15 s, so three missed ones is a dead socket.
TASK_STREAM_TIMEOUT = (10, 45)
STREAM_BACKOFF_FIRST = 1.0
STREAM_BACKOFF_MAX = 30.0
STREAM_CAPPED_FROM = 30.0       # TOO_MANY_STREAMS: back off from here (doubling to 4x)
STREAM_IDLE_REOPEN_S = 600      # an idle end reopens on a create, a sweep, or after this
STREAM_HEALTHY_S = 30           # a connection that lived this long proved itself
STREAM_JITTER = 0.25            # +/- fraction applied to every backoff
_FRAME_MEMORY = 500             # tasks whose last frame the stale rule remembers

_RANK = {"waiting": 0, "pending": 0, "queued": 0, "running": 1}


def new_stream_status():
    """The stream's own record (`_watch_status["task_stream"]`)."""
    return {"state": "off", "last_event_at": None, "last_end_reason": None,
            "failures": 0, "capped": 0, "last_error": None, "connected_at": None,
            "stopped_reason": None}


class SSEParser:
    """Server-sent events, one line at a time. `feed(line)` returns a completed event dict
    ({"event", "data", "id"}) when a blank line closes one, else None. Comment lines (`: ...`,
    P2's `: connected` and `: keep-alive`) carry nothing and are only counted."""

    def __init__(self):
        self.comments = 0
        self._reset()

    def _reset(self):
        self._event, self._data, self._id = None, [], None

    def feed(self, line):
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.rstrip("\r\n")
        if line == "":
            if not self._data and self._event is None:
                self._reset()
                return None
            ev = {"event": self._event or "message", "data": "\n".join(self._data),
                  "id": self._id}
            self._reset()
            return ev
        if line.startswith(":"):
            self.comments += 1
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "data":
            self._data.append(value)
        elif field == "id":
            self._id = value
        return None


def adapt_task_frame(frame):
    """A stream event (`{type: "task_updated", data: <REST task>}`, or the bare task) in the
    shape the watcher's frame handler reads for `taskUpdated`: id, status, updatedAt and
    mediaId (outputs.mediaIds[0], else videoMediaId). None for anything that is not a task."""
    if not isinstance(frame, dict):
        return None
    task = frame.get("data") if isinstance(frame.get("data"), dict) else frame
    if not isinstance(task, dict) or not task.get("id"):
        return None
    outputs = task.get("outputs") if isinstance(task.get("outputs"), dict) else {}
    ids = outputs.get("mediaIds")
    media = ids[0] if isinstance(ids, list) and ids else None
    media = media or outputs.get("videoMediaId") or task.get("videoMediaId") or task.get("mediaId")
    return {"id": str(task["id"]), "status": task.get("status"),
            "updatedAt": task.get("updatedAt"), "mediaId": media}


def _rank(status):
    s = str(status or "").lower()
    if s in _RANK:
        return _RANK[s]
    return 2 if s else -1          # any terminal spelling outranks the live ones


def _stamp(value):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def is_stale_frame(last, new):
    """True when `new` (an adapted frame) is older than `last` for the same task: by
    `updatedAt` first, then, at the same instant, by status rank. Equal is a duplicate and
    passes (the collectors are single-flight)."""
    if not last:
        return False
    a, b = _stamp(last.get("updatedAt")), _stamp(new.get("updatedAt"))
    if a is not None and b is not None and a != b:
        return b < a
    return _rank(new.get("status")) < _rank(last.get("status"))


def classify_refusal(status, body):
    """How a refused open reads: "auth" (stop), "capped" (TOO_MANY_STREAMS) or "retry"."""
    up = str(body or "").upper()
    if status == 429 or "TOO_MANY_STREAMS" in up:
        return "capped"
    if status == 401 or "UNAUTHORIZED" in up or "UNKNOWN CLIENT PLATFORM" in up:
        return "auth"
    return "retry"


class TaskStream:
    """The REST task stream's client. Every collaborator is passed in, so a test drives it
    with a fake session, clock and sleep and never opens a socket.

    make_session()  -> a client/session on the API key presenting as the website
    on_task(frame)  -> the watcher's frame handler, called with an adapted task frame
    request_catchup(reason) -> asks the one sweep worker (non-blocking)
    status/lock     -> the `_watch_status["task_stream"]` dict and the lock guarding it"""

    def __init__(self, make_session, on_task, request_catchup, status, lock, clock=None,
                 sleep=None, rand=None, idle_wait=None, log=None):
        import logging
        import random
        import threading
        import time
        self.make_session, self.on_task = make_session, on_task
        self.request_catchup, self.status, self.lock = request_catchup, status, lock
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.rand = rand or random.random
        self.wake = threading.Event()
        self.idle_wait = idle_wait or (lambda s: self.wake.wait(s))
        self.log = log or logging.getLogger(__name__)
        self.backoff = STREAM_BACKOFF_FIRST
        self.capped_n = 0
        self.last_frame = {}
        self.stopped = False

    # -- state + log: every transition is recorded -----------------------------
    def _set(self, state, level="info", msg=None, **fields):
        with self.lock:
            old = self.status.get("state")
            self.status.update(fields)
            self.status["state"] = state
        text = "task stream: {}{}".format(state, " -- " + msg if msg else "")
        if old != state or msg:
            getattr(self.log, level)(text)

    def request_reopen(self, reason):
        """Ask an idle stream to reopen now (a create, or a sweep that saw an unfinished
        task). Harmless in any other state."""
        self.log.info("task stream: reopen requested (%s)", reason)
        self.wake.set()

    def _jitter(self, seconds):
        return seconds * (1 - STREAM_JITTER + 2 * STREAM_JITTER * self.rand())

    def _fail(self, err, lived=None):
        """A connection that did not last. Not a failure when it had proved itself."""
        if lived is not None and lived >= STREAM_HEALTHY_S:
            self.backoff = STREAM_BACKOFF_FIRST
            wait = self._jitter(STREAM_BACKOFF_FIRST)
            self._set("reconnecting", msg="dropped after {}s ({}) -- reopening in {:.1f}s".format(
                round(lived), err, wait), last_error=err)
            return wait
        wait = self._jitter(self.backoff)
        self.backoff = min(self.backoff * 2, STREAM_BACKOFF_MAX)
        with self.lock:
            self.status["failures"] += 1
        self._set("backoff", "warning", "{} -- retrying in {:.1f}s".format(err, wait),
                  last_error=err)
        return wait

    def _handle_event(self, ev):
        """One SSE event. Returns None to keep reading, ("end", reason) or ("error", kind)."""
        import json
        name = ev["event"]
        try:
            obj = json.loads(ev["data"]) if ev["data"] else {}
        except ValueError:
            self.log.warning("task stream: an event with unreadable data was skipped")
            return None
        if name == "done":
            return ("end", obj.get("reason") if isinstance(obj, dict) else None)
        if name == "error":
            return ("error", classify_refusal(None, json.dumps(obj)))
        frame = adapt_task_frame(obj)
        if frame is None:
            return None
        if is_stale_frame(self.last_frame.get(frame["id"]), frame):
            return None
        self.last_frame[frame["id"]] = frame
        if len(self.last_frame) > _FRAME_MEMORY:
            self.last_frame.pop(next(iter(self.last_frame)))
        with self.lock:
            self.status["last_event_at"] = time.time()
        self.on_task(frame)
        return None

    def _stop(self, why, error):
        self.stopped = True
        self._set("stopped", "error", why, last_error=error,
                  stopped_reason="PixAI refused the task feed: check the API key. "
                                 "The catch-up sweep still runs.")
        return ("stop", 0)

    def _capped(self):
        wait = self._jitter(STREAM_CAPPED_FROM * (2 ** min(self.capped_n, 2)))
        self.capped_n += 1
        with self.lock:
            self.status["capped"] += 1
        self._set("capped", "warning", "too many streams -- retrying in {:.0f}s".format(wait))
        return ("wait", wait)

    def cycle(self):
        """One connection's life. Returns ("stop", 0), ("idle", 0) or ("wait", seconds)."""
        import requests
        self.wake.clear()
        self._set("connecting")
        opened = None
        try:
            client = self.make_session()
            sess = getattr(client, "session", client)
            resp = sess.get(TASK_STREAM_URL, headers={"Accept": "text/event-stream"},
                            stream=True, timeout=TASK_STREAM_TIMEOUT, allow_redirects=False)
        except Exception as e:
            return ("wait", self._fail("{}: {}".format(type(e).__name__, str(e)[:160])))
        try:
            status = getattr(resp, "status_code", 0)
            if status != 200:
                try:
                    body = resp.text[:400]
                except Exception:
                    body = ""
                kind = classify_refusal(status, body)
                if kind == "auth":
                    return self._stop("refused (HTTP {}); the catch-up sweep continues".format(status),
                                      "HTTP {}".format(status))
                if kind == "capped":
                    return self._capped()
                return ("wait", self._fail("HTTP {}".format(status)))
            opened = self.clock()
            self.capped_n = 0
            with self.lock:
                self.status["failures"] = 0
                self.status["connected_at"] = time.time()
                self.status["last_error"] = None
            self._set("open")
            self.request_catchup("stream-connect")
            try:
                resp.encoding = "utf-8"
            except Exception:
                pass
            parser = SSEParser()
            for line in resp.iter_lines(decode_unicode=True):
                ev = parser.feed(line if line is not None else "")
                if ev is None:
                    continue
                out = self._handle_event(ev)
                if out is None:
                    continue
                if out[0] == "end":
                    reason = out[1]
                    with self.lock:
                        self.status["last_end_reason"] = reason or "done"
                    if reason == "idle":
                        self._set("idle", msg="ended idle after {}s".format(
                            round(self.clock() - opened)))
                        return ("idle", 0)
                    self.backoff = STREAM_BACKOFF_FIRST
                    self._set("reconnecting", msg="ended ({}) -- reopening".format(reason or "done"))
                    return ("wait", self._jitter(STREAM_BACKOFF_FIRST))
                if out[1] == "auth":
                    return self._stop("the stream reported an auth error; the catch-up sweep continues",
                                      "auth error event")
                if out[1] == "capped":
                    return self._capped()
                return ("wait", self._fail("stream error event", self.clock() - opened))
            # The body closed with no `done` event: a dropped stream.
            with self.lock:
                self.status["last_end_reason"] = "closed"
            return ("wait", self._fail("closed by the server", self.clock() - opened))
        except (requests.exceptions.RequestException, OSError) as e:
            silent = isinstance(e, requests.exceptions.ReadTimeout) or "timed out" in str(e).lower()
            err = "no data for {}s".format(TASK_STREAM_TIMEOUT[1]) if silent else type(e).__name__
            with self.lock:
                self.status["last_end_reason"] = "silent" if silent else "dropped"
            lived = (self.clock() - opened) if opened is not None else None
            return ("wait", self._fail(err, lived))
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def run(self, max_cycles=None):
        n = 0
        while not self.stopped:
            kind, wait = self.cycle()
            n += 1
            if kind == "stop" or (max_cycles and n >= max_cycles):
                break
            if kind == "idle":
                woke = self.idle_wait(STREAM_IDLE_REOPEN_S)
                self.log.info("task stream: reopening after idle (%s)",
                              "requested" if woke else "10 minutes")
            else:
                self.sleep(wait)

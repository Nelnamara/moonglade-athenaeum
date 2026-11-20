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
_WS_SUBSCRIPTION = (
    "subscription Watch { personalEvents { "
    "taskUpdated { id status updatedAt mediaId media { id urls { url } } priority userId } "
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

    print("Watching PixAI live events at {} (read-only; gentler than polling).".format(_WS_URI))
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

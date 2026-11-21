"""
moonglade/watch_plans.py
========================
The live mirror's two timing decisions, as pure functions: when to reconnect after a drop
(`watch_reconnect_plan`) and when to read back what finished while it was gone
(`catchup_plan`), their WATCH_* constants, and `watch_close_info`, the close record the Panel
keeps. The threads that act on them are moonglade/web_threads.py's. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""


# ---- The live mirror: when to reconnect, and when to catch up (#60) -------------------------
# PROBE_2026-10-02 (bridge-live-inbox-studio, task 2): PixAI neither idles sockets out nor caps
# their life. Drops are PixAI-side events that end several connections at once, cleanly
# (`complete`) or with no close frame at all, whatever their ping state -- so no keep-alive can
# prevent them. What the app controls is the gap after each one: how long it waits to reconnect,
# and whether it reads back what finished while it was gone. Both decisions are pure functions
# here, driven as tables by dev/tests/test_watch.py.

# A connection that subscribed and then lived at least one heartbeat (core._WS_HEARTBEAT) has
# proved itself; when it ends, the cause is PixAI's, not ours, and the reconnect comes at once.
WATCH_HEALTHY_S = 60
# "At once" in human terms. 1 s, not 0, so that no bug anywhere else can ever spin this loop.
WATCH_RECONNECT_WAIT = 1
# The ladder for everything else (a refused handshake, a drop seconds after subscribing).
WATCH_BACKOFF_FIRST = 5
WATCH_BACKOFF_MAX = 60
# The periodic backstop sweeps every this many seconds, and skips while a SUCCESSFUL sweep is
# younger than it.
WATCH_CATCHUP_MIN_GAP = 300
# No two sweeps start closer than this. A connect-triggered sweep inside it WAITS (it is never
# skipped: its gap is new); a periodic one inside it is skipped (it is only a backstop).
WATCH_SWEEP_FLOOR = 60
# `subscribed` fires when the subscribe frame is SENT. PixAI acknowledges nothing, so when the
# subscription actually starts delivering is unobservable; the sweep waits this long after the
# send before reading. A task finishing in that instant is delivered by the socket once the
# subscription is live, or found by this read, or -- if the subscription took longer than this to
# go live -- by the next periodic sweep. Unlikely, never silent for longer than one backstop.
WATCH_SUBSCRIBE_SETTLE = 2
# A task whose collect failed is left alone this long before a sweep tries it again.
WATCH_COLLECT_RETRY_S = 300


def watch_reconnect_plan(backoff, lived_s):
    """How long to wait before reconnecting, and the backoff to carry: `(wait_s, next_backoff)`.

    `lived_s` is how long the connection lived after it subscribed, or None if it never did.
    A healthy connection (lived >= WATCH_HEALTHY_S) reconnects after WATCH_RECONNECT_WAIT and
    resets the ladder, however it ended -- a clean `complete`, a stale watchdog, or a drop with no
    close frame. Everything else waits the current step and climbs 5/15/45/60. Healthy reconnects
    are therefore at least a minute apart by construction, which is the storm bound."""
    if lived_s is not None and lived_s >= WATCH_HEALTHY_S:
        return WATCH_RECONNECT_WAIT, WATCH_BACKOFF_FIRST
    return backoff, min(backoff * 3, WATCH_BACKOFF_MAX)


def catchup_plan(reason, now, last_started, last_ok, not_before=0.0):
    """Whether the catch-up worker may sweep now: ("run", 0), ("wait", seconds) or ("skip", 0).

    `last_started` is when the previous sweep started (None: never), `last_ok` when the last
    SUCCESSFUL one started (a failed read is not coverage), `not_before` the settle deadline the
    latest subscribe set. All on one monotonic clock.

    A connect-triggered sweep ("startup", "reconnect") is never skipped -- its gap is new, and
    skipping it is how a task that finished during a drop used to wait five minutes for the next
    periodic sweep. It waits for the settle deadline and for WATCH_SWEEP_FLOOR after the previous
    sweep, then reads. The periodic backstop skips while a successful sweep is younger than
    WATCH_CATCHUP_MIN_GAP, or any attempt younger than the floor."""
    if reason == "periodic":
        if last_ok is not None and now - last_ok < WATCH_CATCHUP_MIN_GAP:
            return ("skip", 0)
        if last_started is not None and now - last_started < WATCH_SWEEP_FLOOR:
            return ("skip", 0)
        return ("run", 0)
    wait = (not_before or 0.0) - now
    if last_started is not None:
        wait = max(wait, last_started + WATCH_SWEEP_FLOOR - now)
    return ("wait", wait) if wait > 0 else ("run", 0)


def watch_close_info(exc, redact=None):
    """How a live connection ended, from the exception that ended it, for the status record and
    the log. A websockets ConnectionClosed carries the Close frame it received (`rcvd`) and sent
    (`sent`): none either way is an abrupt drop ("no close frame received or sent"), today's usual
    kind. Anything else is an error before or around the socket. `redact` is create_app's
    host-path redactor, applied to the close reason. Never raises."""
    try:
        if hasattr(exc, "rcvd") and hasattr(exc, "sent"):
            frame = exc.rcvd or exc.sent
            if frame is None:
                return {"kind": "abrupt", "code": None, "reason": ""}
            return {"kind": "closed", "code": getattr(frame, "code", None),
                    "reason": (redact or str)(str(getattr(frame, "reason", "") or ""))[:80]}
    except Exception:                              # noqa: BLE001
        pass
    return {"kind": "error", "type": type(exc).__name__}

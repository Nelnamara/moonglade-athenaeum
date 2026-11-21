"""
moonglade/ach_beacon.py
=======================
The feat beacon's nonce, debounce and rate limit: the nonce table and its lock (`_ach_lock`,
`_ach_nonces`), the debounce and rate tables, and `_ach_mint`, `_ach_consume`, `_ach_debounced`
and `_ach_rate_ok`. One table for the whole server: the page render and the Loom shell mint,
and moonglade/routes_ach.py's beacon routes mint and spend, all in this module's tables. (The
`_ach_lock` that routes_ach binds in register is create_app's own lock, a different object.)
Moved verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""
import secrets
import threading
import time


# ---- the feat-beacon nonce, debounce and rate limit (2026-09-07) ------------------------
# What replaced the LOCALHOST gate on /api/ach-event. The gate's problem was that the
# beacon is the ONLY witness a feat gesture happened, so any signed-in session could POST
# a feat event from a console and arm the feat. Loopback made the gesture witnessable
# but cost every phone and LAN device the three feats outright. The owner's call
# (2026-09-07): "triggered should be obtainable easily on a phone just like desktop. For
# sure build the nonce."
#
# So the witness moves from WHERE the request came from to WHETHER IT CAME FROM A PAGE THE
# SERVER RENDERED. A nonce is minted into each render, is good for exactly one event inside
# 60 seconds, and is bound to the session it was minted for. A console POST has no nonce; a
# replayed one is already spent; one lifted from another session's page is not this
# session's to spend. That is a real (if soft) witness, and unlike loopback it is one a
# phone passes.
#
# Process-local by design, exactly like _login_attempts: one process, `python -m
# moonglade.gallery`. Under a multi-worker server each worker would keep its own table
# and a nonce minted by worker A would read as unknown at worker B -- the page would refresh
# once and carry on, so the failure mode is a wasted round trip, not a lost feat.
_ACH_NONCE_TTL_S = 60.0       # a nonce is good for one event inside this window
_ACH_NONCE_MAX = 4000         # hard cap on the table (sweep-first, then evict oldest)
_ACH_DEBOUNCE_S = 0.15        # the same (session, event) inside this counts once
_ACH_RATE_MAX = 30            # beacon calls per session per window (mint + event both count)
_ACH_RATE_WINDOW_S = 60.0
_ach_lock = threading.Lock()
_ach_nonces = {}   # nonce -> (issued_at, sid)
_ach_last = {}     # (sid, event) -> epoch of the last event that COUNTED
_ach_rate = {}     # sid -> [epoch, ...] of calls inside the rolling window


def _ach_sweep(now):
    """Drop expired nonces, stale debounce stamps and spent rate rows. The caller holds
    _ach_lock. Runs on every mint AND every check, so the tables cannot grow between two
    cold periods -- there is no other reaper."""
    for nonce, (issued, _sid) in list(_ach_nonces.items()):
        if now - issued > _ACH_NONCE_TTL_S:
            _ach_nonces.pop(nonce, None)
    for key, stamp in list(_ach_last.items()):
        if now - stamp > _ACH_RATE_WINDOW_S:
            _ach_last.pop(key, None)
    for sid, hits in list(_ach_rate.items()):
        fresh = [t for t in hits if now - t <= _ACH_RATE_WINDOW_S]
        if fresh:
            _ach_rate[sid] = fresh
        else:
            _ach_rate.pop(sid, None)


def _ach_mint(sid, now=None):
    """A fresh nonce for `sid`. Sweeps first; if the table is somehow still at its cap
    (a burst inside one 60s window), evicts the oldest entries rather than growing --
    an unbounded dict fed by any logged-in session is a memory vector, and losing the
    oldest nonce costs its page one refresh."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        overflow = len(_ach_nonces) - _ACH_NONCE_MAX + 1
        if overflow > 0:
            for nonce, _rec in sorted(_ach_nonces.items(), key=lambda kv: kv[1][0])[:overflow]:
                _ach_nonces.pop(nonce, None)
        nonce = secrets.token_urlsafe(16)
        _ach_nonces[nonce] = (now, sid)
        return nonce


def _ach_consume(nonce, sid, now=None):
    """True when `nonce` was minted for THIS session and is still inside its window.
    A match is spent whether or not it had expired (one event per nonce, always). A
    nonce belonging to another session is NOT spent -- refusing it is right, but burning
    it would let any logged-in session invalidate another's page at will."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        rec = _ach_nonces.get(nonce) if nonce else None
        if not rec:
            return False
        issued, owner = rec
        if owner != sid:
            return False
        _ach_nonces.pop(nonce, None)
        return (now - issued) <= _ACH_NONCE_TTL_S


def _ach_debounced(sid, event, now=None):
    """True when the same (session, event) already counted less than _ACH_DEBOUNCE_S ago.
    Records this event's stamp when it is not.

    This is a WALL-CLOCK gap and nothing else: it cannot see whether one gesture fired
    twice or a person tapped twice, so the window is the whole of the distinction. At the
    400ms it shipped with on 2026-09-07 it was not one -- a phone user tapping the narrator
    at an ordinary ~3 taps/sec had every second REAL poke discarded, so Triggered wanted
    about ten taps instead of five, while this docstring, the route's, and useFolio.js's
    all claimed separate clicks were never touched. Narrowed to 150ms the same day: a
    double-fired DOM event arrives inside a few milliseconds, and a hand cannot tap the
    same control twice inside 150ms, so the window now catches what those comments say it
    catches. Faster than a hand, not faster than a bug.

    A double fire also means one nonce sent twice -- the twin that loses the race is
    refused 403 as consumed, BEFORE reaching here. That refusal must stay silent on the
    client: gallery/src/notify/achNonce.js (and the Loom shell's own mgAchDocs) refresh and
    retry only when their nonce is missing or older than the 60s window, never on the
    immediate twin, or the retry would arrive with a fresh nonce and count the gesture a
    second time on any round trip slower than this window."""
    now = time.time() if now is None else now
    with _ach_lock:
        prev = _ach_last.get((sid, event))
        if prev is not None and (now - prev) < _ACH_DEBOUNCE_S:
            return True
        _ach_last[(sid, event)] = now
        return False


def _ach_rate_ok(sid, now=None):
    """False once `sid` has spent its 30 beacon calls in the rolling minute. Counts the
    call it admits, so a mint and an event draw on the same budget -- five pokes plus the
    odd refresh is nowhere near it, a scripted replay loop is."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        hits = [t for t in _ach_rate.get(sid, ()) if now - t <= _ACH_RATE_WINDOW_S]
        if len(hits) >= _ACH_RATE_MAX:
            _ach_rate[sid] = hits
            return False
        hits.append(now)
        _ach_rate[sid] = hits
        return True

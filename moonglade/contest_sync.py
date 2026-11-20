"""
moonglade/contest_sync.py
=========================
The contest board and its sync: the memoized board, the detection sweep that reads entries
and wins back from PixAI into the telemetry sets, and the verified-wins pass. The I/O half of
moonglade/contest_wins.py, which stays pure. Moved verbatim out of moonglade/gallery.py in the
3.21.0 split (phase 3).

It reaches telemetry as `_telemetry.X`, the way the gallery did once telemetry moved out. The
one name it needs from the gallery (the path redactor) is imported inside each function that
uses it, never at the top, so importing this module never imports the gallery.
"""
import threading
import time

from moonglade import contest_wins
from moonglade import contests as _contests
from moonglade import pixai_client as _pixai_client
from moonglade import series as _series
from moonglade import telemetry as _telemetry

# --- contest detection sweep ---------------------------------------------------------
# The two ladder signals this app cannot see for itself: an entry made on pixai.art never
# touches this process at all, and NOTHING local ever hears "you won" -- there is no local
# event to hook. So both are read back FROM PixAI, into the very same dedupe sets the entry
# paths write, which is what makes the sweep safe to run as often as it likes: re-seeing an
# entry adds nothing, and an entry the app made itself is the same key the poll finds.
#
# Bounded on purpose: two pages of the board, every RUNNING contest, and at most
# _CONTEST_SYNC_MAX ended ones from inside the recent window. The historical board is long
# and its old rows cannot change, so sweeping all of it would be a request storm for
# nothing -- but a running contest is where entries actually happen, so the cap must never
# be what drops one.
# The contest board, memoized per variant (see api_contests). Module-level so every
# surface that mounts a contest list shares one answer rather than each paying its own
# round trip on open.
CONTESTS_TTL = 90.0
_contests_cache = {}
_contests_cache_lock = threading.Lock()


def contest_board(core, session, force=False, full=False):
    """The WHOLE contest board, memoized for CONTESTS_TTL -- and the one read every
    consumer goes through.

    Before this there were four different boards. /api/contests read six pages; the
    sweep read two; the enter route, the publish-and-enter hook and /api/contest/mine
    each read ONE. So a contest past row ~50 was visible in the list and then refused by
    the enter route as "unknown contest", and My entries rendered its rows with blank
    titles -- the same contest, present or absent depending on which code asked. The
    publish hook's one-page read was the worst of them: it happens AFTER the publish is
    already committed, so failing to find the contest there means an artwork published
    and silently not entered.

    One snapshot, read the full depth (list_contests' own default), filtered by whoever
    needs less. Costs no more upstream than the single widest read did, and every caller
    now agrees about what exists."""
    now = time.time()
    with _contests_cache_lock:
        ent = _contests_cache.get("board")
        if not force and ent and (now - ent["at"]) < CONTESTS_TTL:
            return ent["rows"]
    meta = {}
    rows = _contests.list_contests(session, active_only=False, meta=meta,
                                   cache_path=_contests.contest_cache_path(), full=full)
    with _contests_cache_lock:
        _contests_cache["board"] = {"at": time.time(), "rows": rows, "meta": meta}
    return rows


def contest_board_meta():
    """How the memoized board's walk ended (list_contests' `meta`: truncated, limit,
    total_count ...), or {} when nothing is cached. A copy, so a caller cannot edit the memo."""
    with _contests_cache_lock:
        ent = _contests_cache.get("board")
        return dict((ent or {}).get("meta") or {})

# How long a completed sweep counts as recent enough to skip. The spec asked for this
# and it never got built: opening the Contests overlay fired a full sweep EVERY time --
# a paced walk over the board plus a per-contest entries read, on the open of a window
# whose data changes on the order of days. A forced sweep (the publish kick, which is
# confirming an entry made seconds ago) ignores this entirely.
CONTEST_SYNC_RECENT_S = 600.0
_contest_sync_last_ok = {"at": 0.0}
_CONTEST_SYNC_MAX = 40
_CONTEST_SYNC_RECENT_DAYS = 45
_CONTEST_SYNC_PAUSE = 0.35          # paced: be polite to their servers
_CONTEST_SYNC_STARTUP_DELAY = 20.0  # let the app finish booting before any network work
_contest_sync_lock = threading.Lock()


def _contest_sync_is_recent(contest, now=None):
    """True when a contest's result/end date parses AND lands inside the recent window --
    "finished, but recently enough that its result is still worth one look".

    An absent or unparseable date is deliberately NOT recent: the sweep would rather miss
    a stale contest than fall back to polling the entire history every startup. A date in
    the future is not recent either -- that contest is either still running (kept by the
    `active` flag instead) or its dates disagree with its status, which is not a reason to
    poll for winners that cannot exist yet."""
    now = time.time() if now is None else now
    window = _CONTEST_SYNC_RECENT_DAYS * 86400.0
    for key in ("result_at", "end_at"):
        ts = _series._series_ts(contest.get(key))
        if ts is not None and 0 <= (now - ts) <= window:
            return True
    return False


def _contest_detection_sync(out_dir, force=False):
    """Read this account's contest entries and wins back from PixAI into telemetry.
    Returns True when the sweep ran, False when it gave up.

    Per kept contest: the owner's own entries (`/contest/{slug}/artwork/{userId}`) become
    contest_entry_keys. WINS ARE NOT READ HERE ANY MORE (L3): a win is a verified fact, and
    the automatic check that establishes it (contest_win_pass, below) reads the winners list
    once per contest at the result time and then daily, matching the entry's artwork id and
    an integer tier rank. This sweep used to match the author alone, which recorded a win
    with no artwork, no tier and no receipt, and read the winners list a second time.

    `force` drops the recent-window filter (every row the board returns is kept, ended ones
    still capped). The publish kick uses it: the app has just been TOLD an entry was made,
    and the point of that sweep is to confirm it against PixAI rather than take the client's
    word -- so a contest the window would have skipped must not be what hides it.

    FAIL-SOFT TOP TO BOTTOM, and that is the point rather than an afterthought: this runs on
    a background thread and from a route, and a poll that can raise is a poll that can break
    the very thing it exists to observe. A per-contest failure skips that contest and the
    sweep continues; anything else ends the sweep. Both are LOGGED, not swallowed silently:
    a detection sweep that quietly stops working looks exactly like an account that stopped
    entering contests, and nothing else in the app would ever say otherwise.

    Sealing: only counts ever leave the telemetry store, and nothing written to the store is
    ever logged -- the log lines carry an exception type and a redacted message, no keys."""
    from moonglade.gallery import _redact_host_paths_cli
    import logging as _logging
    log = _logging.getLogger(__name__)
    # RUN-RECENCY GUARD. A sweep that just ran has nothing new to learn: the board moves
    # over days and an entry made in the last ten minutes was either made HERE (in which
    # case the publish kick forced its own sweep) or on the website, where ten more
    # minutes of latency costs nothing. Without this, every Contests overlay open paid a
    # paced walk of the board plus a read per contest. `force` bypasses it completely --
    # that caller is confirming a specific entry it was just told about.
    if not force:
        age = time.time() - _contest_sync_last_ok.get("at", 0.0)
        if age < CONTEST_SYNC_RECENT_S:
            return True
    try:
        from moonglade import backup as core
        session = core._make_session(None)
        uid = str(_pixai_client._client_of(session).user_id or "")
        if not uid:
            log.info("contest sweep: no account id resolved -- nothing to poll")
            return False
        active, ended = [], []
        for c in contest_board(core, session) or []:
            if not isinstance(c, dict):
                continue
            # A RUNNING contest is never capped out: it is the only kind an entry can still
            # be made into, so dropping one to a cap would blind the sweep to live activity.
            # The cap exists for the ended tail, which is long and cannot change.
            if c.get("active"):
                active.append(c)
            elif (force or _contest_sync_is_recent(c)) and len(ended) < _CONTEST_SYNC_MAX:
                ended.append(c)
        for i, c in enumerate(active + ended):
            if i:
                time.sleep(_CONTEST_SYNC_PAUSE)
            try:
                cid = str(c.get("id") or "")
                slug = str(c.get("slug") or "")
                if not cid or not slug:
                    continue
                for row in _contests.contest_my_entries(session, slug, uid) or []:
                    # MIGRATION, deliberate and narrow. Before 2026-09-03 this keyed by the
                    # ENTRY id when the artwork id was nested (and therefore stripped), so
                    # an old store can hold "cid:<entry id>" for a piece now keyed
                    # "cid:<artwork id>" -- one entry counted twice, forever, in a set that
                    # otherwise only grows. When upstream hands us BOTH ids we can prove
                    # they are the same entry, which is the only moment that judgement is
                    # safe to make, so the stale key is discarded here and nowhere else.
                    # The by-user row's shape is UNVERIFIED against a real entry (the probe
                    # that mapped this endpoint found no owner entries to compare), so the
                    # explicit artwork field is preferred and the row id is only the
                    # fallback -- they may or may not be the same value.
                    row = row or {}
                    art_id = str(row.get("artworkId") or "")
                    row_id = str(row.get("id") or "")
                    rid = art_id or row_id
                    if rid:
                        _telemetry.telem_set_add("contest_entry_keys", "%s:%s" % (cid, rid),
                                      out_dir=out_dir)
                    # Both ids present and different: upstream has just told us they name
                    # the same entry, so a stored key under the OLD identity is a duplicate
                    # of the one just written, not a second entry. This is the only place
                    # that can know, so this is the only place that heals it.
                    if art_id and row_id and art_id != row_id:
                        _telemetry.telem_set_discard("contest_entry_keys", "%s:%s" % (cid, row_id),
                                          out_dir=out_dir)
            except Exception as e:                           # one bad contest, not the sweep
                log.warning("contest sweep: one contest failed: %s: %s", type(e).__name__,
                            _redact_host_paths_cli(out_dir, str(e))[:200])
                continue
        # The board this sweep just read also tells the win check when each contest's results
        # land; a result time that moved is followed here (local, no network).
        try:
            contest_win_refresh(out_dir, contest_board(core, session) or [])
        except Exception:                                     # noqa: BLE001
            pass
        # Only a sweep that actually completed counts as recent -- a failed one must not
        # buy ten minutes of silence.
        _contest_sync_last_ok["at"] = time.time()
        return True
    except Exception as e:
        log.warning("contest sweep: gave up: %s: %s", type(e).__name__,
                    _redact_host_paths_cli(out_dir, str(e))[:200])
        return False


def _contest_sync_kick(out_dir, force=False):
    """Run one sweep under the single-flight lock, or skip if one is already running.

    The lock is the whole contract: the startup sweep, the publish kick and the manual route
    all reach the same work, and a caller that loses the race has nothing to do -- the sweep
    already in flight reads the same account from the same board. Returns whether it ran."""
    if not _contest_sync_lock.acquire(False):
        return False
    try:
        return _contest_detection_sync(out_dir, force=force)
    finally:
        _contest_sync_lock.release()


# --- verified contest wins (L3) ------------------------------------------------------
# A contest win is a fact PixAI states, so it is recorded only when PixAI's own winners list
# says so: the entry's artwork id is in the list, its `entry.rank` is an integer, and the
# author is this account. The rules live in moonglade/contest_wins.py (pure, tested); this is
# the part that reads and writes.
#
#   * THE AUTOMATIC CHECK (contest_win_pass). For each contest the account entered, per the
#     app's own entry record: one GET of the winners list at the contest's result time, then
#     once a day for up to 14 days. An EMPTY list is undecided, never "lost". It stops early
#     when the contest's rewardStatus is "distributed" and the entries are settled. It rides
#     the scheduler's existing 60-second tick (see _contest_win_tick in create_app), reads
#     nothing at import and nothing when a page opens, and is single-flight.
#   * THE CHECK BUTTON (contest_win_check, POST /api/contest/check). The owner pastes an
#     entry's link; one GET of that contest's winners; verified only when matched. The link is
#     kept as the receipt.
#
# Both are GETs. Neither can write to PixAI: there is no such call on this road.
_CW_PAUSE = 1.0                     # between two contests inside one pass
_CW_BOARD_BACKOFF_S = 900.0         # a failed board read is not asked again for a quarter hour
_cw_lock = threading.Lock()         # single flight, like the entry sweep's
_cw_state = {"board_retry_at": 0.0, "manual": {}}


def _cw_sections(d):
    """The two sub-records of telemetry's `contest_results` section, made real dicts in place
    (a hostile file can hold anything there) -> (wins, checks)."""
    res = d.get("contest_results")
    if not isinstance(res, dict):
        res = d["contest_results"] = {}
    for k in ("wins", "checks"):
        if not isinstance(res.get(k), dict):
            res[k] = {}
    return res["wins"], res["checks"]


def _cw_edit(out_dir, fn):
    """fn(wins, checks) under the telemetry lock. Fail-soft, like every telemetry write."""
    _telemetry._telem_mutate(out_dir, lambda d: fn(*_cw_sections(d)))


def _cw_inputs(d):
    """(entries, legacy_wins, wins, checks) read from a loaded telemetry bundle. Copies:
    nothing here writes through them."""
    sets = d.get("sets") if isinstance(d.get("sets"), dict) else {}
    entries = contest_wins.entries_by_contest(sets.get("contest_entry_keys"))
    legacy = sets.get("contest_win_keys")
    legacy = [str(x) for x in legacy] if isinstance(legacy, list) else []
    res = d.get("contest_results") if isinstance(d.get("contest_results"), dict) else {}
    wins = res.get("wins") if isinstance(res.get("wins"), dict) else {}
    checks = res.get("checks") if isinstance(res.get("checks"), dict) else {}
    checks = {str(k): dict(v) for k, v in checks.items() if isinstance(v, dict)}
    return entries, legacy, wins, checks


def contest_win_due(out_dir, now=None):
    """Whether anything is worth waking the check for. LOCAL ONLY -- one small file read and
    some arithmetic, so the 60-second tick can ask it every minute for nothing."""
    now = time.time() if now is None else now
    try:
        entries, legacy, wins, checks = _cw_inputs(_telemetry.load_telemetry(out_dir))
    except Exception:                                         # noqa: BLE001
        return False
    plan = contest_wins.plan_pass(entries, legacy, wins, checks, now)
    if plan["due"]:
        return True
    # A seed needs the contest board; a board that just failed is left alone for a while.
    return bool(plan["seed"] or plan["legacy"]) and now >= _cw_state["board_retry_at"]


def contest_win_refresh(out_dir, board, now=None):
    """Follow contests whose result time moved (local; no network). `board` is the list of
    contest rows list_contests returns. Only rows that have not been checked yet move."""
    now = time.time() if now is None else now
    by_id = {str(c.get("id")): c for c in (board or []) if isinstance(c, dict) and c.get("id")}
    if not by_id:
        return

    def _do(wins, checks):
        for cid, st in checks.items():
            c = by_id.get(str(cid))
            if isinstance(st, dict) and c:
                contest_wins.refresh_state(st, contest_wins.parse_ts(c.get("result_at")),
                                           str(c.get("slug") or ""), now)
    _cw_edit(out_dir, _do)


def contest_win_pass(out_dir, now=None, pause=None):
    """ONE automatic pass. Returns {ran, checked, recorded, errors} (for the log and the tests).

    Decided from the local record first (moonglade.contest_wins.plan_pass): nothing due and
    nothing to seed means no network at all. Otherwise the contest board is read ONCE (the
    memoized snapshot every contest surface shares) to give new contests their schedule and
    to learn each due contest's rewardStatus, and then each due contest's winners list is
    read ONCE, `_CW_PAUSE` apart. A failed read is logged, pushed an hour out and never
    retried in a loop; one bad contest does not stop the pass."""
    from moonglade.gallery import _redact_host_paths_cli
    import logging as _logging
    from moonglade import backup as core
    log = _logging.getLogger(__name__)
    out = {"ran": False, "checked": [], "recorded": 0, "errors": 0}
    clock = (lambda: now) if now is not None else time.time
    pause = _CW_PAUSE if pause is None else pause
    entries, legacy, wins, checks = _cw_inputs(_telemetry.load_telemetry(out_dir))
    plan = contest_wins.plan_pass(entries, legacy, wins, checks, clock())
    if not (plan["seed"] or plan["legacy"] or plan["due"]):
        return out
    try:
        session = core._make_session(None)
        uid = str(_pixai_client._client_of(session).user_id or "")
    except Exception as e:                                    # noqa: BLE001
        log.warning("contest win check: no session: %s: %s", type(e).__name__,
                    _redact_host_paths_cli(out_dir, str(e))[:200])
        return out
    if not uid:
        log.info("contest win check: no account id resolved -- nothing to verify")
        return out
    out["ran"] = True
    board = {}
    if clock() >= _cw_state["board_retry_at"]:
        try:
            board = {str(c.get("id")): c for c in (contest_board(core, session) or [])
                     if isinstance(c, dict) and c.get("id")}
        except Exception as e:                                # noqa: BLE001
            _cw_state["board_retry_at"] = clock() + _CW_BOARD_BACKOFF_S
            log.warning("contest win check: the board read failed: %s: %s", type(e).__name__,
                        _redact_host_paths_cli(out_dir, str(e))[:200])
    # -- give every entered contest (and every unverified legacy win) a schedule row
    fresh = {}
    if board:
        for cid in list(plan["seed"]) + [c for c in plan["legacy"] if c not in plan["seed"]]:
            c = board.get(cid)
            is_legacy = cid in plan["legacy"]
            if c is None and cid not in entries:
                continue                         # a legacy win for a contest we cannot see
            anchor = None if is_legacy else contest_wins.parse_ts((c or {}).get("result_at"))
            fresh[cid] = contest_wins.new_state((c or {}).get("slug") or "", anchor, clock(),
                                                legacy=is_legacy)
    if fresh:
        _cw_edit(out_dir, lambda w, ch: [ch.setdefault(k, v) for k, v in fresh.items()])
        checks.update({k: v for k, v in fresh.items() if k not in checks})
    now_t = clock()
    due = [cid for cid, st in checks.items()
           if (cid in entries or st.get("legacy")) and contest_wins.is_due(st, now_t)]
    for i, cid in enumerate(due):
        if i and pause:
            time.sleep(pause)
        st = dict(checks[cid])
        c = board.get(cid) or {}
        slug = str(st.get("slug") or c.get("slug") or "")
        t = clock()
        try:
            if not slug:
                raise ValueError("no slug known for this contest")
            rows = _contests.contest_winners(session, slug)          # one GET, nothing else
        except Exception as e:                                # noqa: BLE001
            out["errors"] += 1
            log.warning("contest win check: one contest failed: %s: %s", type(e).__name__,
                        _redact_host_paths_cli(out_dir, str(e))[:200])
            contest_wins.after_error(st, t)

            def _fail(w, ch, cid=cid, st=st):
                ch[cid] = st
            _cw_edit(out_dir, _fail)
            continue
        st["slug"] = slug
        res = contest_wins.verify(rows, uid, entries.get(cid) or None)
        contest_wins.after_read(st, t, res, c.get("reward_status"))
        fresh_wins = res["wins"]

        def _ok(w, ch, cid=cid, st=st, fresh_wins=fresh_wins, t=t):
            ch[cid] = st
            for win in fresh_wins:
                contest_wins.record_win(w, cid, win, "auto", t,
                                        contest_wins.artwork_url(win["artwork_id"]))
        _cw_edit(out_dir, _ok)
        out["checked"].append(cid)
        out["recorded"] += len(fresh_wins)
    return out


def contest_win_kick(out_dir, now=None):
    """Start one pass OFF-THREAD if anything is due, under a single-flight lock. The tick calls
    this every minute and it costs a local file read when there is nothing to do. Returns
    whether a pass was started."""
    from moonglade.gallery import _redact_host_paths_cli
    if not contest_win_due(out_dir, now):
        return False
    if not _cw_lock.acquire(False):
        return False

    def _go():
        try:
            contest_win_pass(out_dir, now)
        except Exception as e:                                # noqa: BLE001
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "contest win check: gave up: %s: %s", type(e).__name__,
                _redact_host_paths_cli(out_dir, str(e))[:200])
        finally:
            _cw_lock.release()
    try:
        threading.Thread(target=_go, daemon=True).start()
    except Exception:                                         # noqa: BLE001
        _cw_lock.release()
        return False
    return True


def contest_win_check(out_dir, body, now=None):
    """The Check button. Returns (http status, payload). Verified ONLY when matched.

    `body` carries `url` (a pasted pixai.art link: an entry's, or a contest's), and optionally
    `contest_id` (a contest from the account's own entries) and `slug` (a contest typed in).
    The artwork read the app already has does not carry the artwork's contest, so the contest
    comes from the row's pick, a contest link, a typed slug, or the contest the app recorded
    the linked artwork in -- in that order (moonglade.contest_wins.plan_manual). Then ONE GET
    of that contest's winners. A miss says what did not match; nothing is recorded on a miss.
    """
    from moonglade.gallery import _redact_host_paths_cli
    from moonglade import backup as core
    cw = contest_wins
    now = time.time() if now is None else now
    url_text = str((body or {}).get("url") or "").strip()
    cid_in = str((body or {}).get("contest_id") or "").strip()
    slug_in = str((body or {}).get("slug") or "").strip()

    def _say(state, entry="", **extra):
        p = {"verified": False, "state": state, "message": cw.message(state, entry), "wins": []}
        p.update(extra)
        return 200, p

    parsed = {"ok": True, "receipt": "", "artwork_id": "", "slug": ""}
    if url_text:
        parsed = cw.parse_evidence(url_text)
        if not parsed["ok"]:
            return _say(parsed["reason"])
    elif not (cid_in or slug_in):
        return _say("no_link")
    entries, _legacy, _wins, checks = _cw_inputs(_telemetry.load_telemetry(out_dir))
    lazy = {"board": None}

    def _board():
        """The contest board by id, read at most once and only if a lookup needs it."""
        if lazy["board"] is None:
            try:
                sess = core._make_session(None)
                lazy["board"] = {str(c.get("id")): c for c in (contest_board(core, sess) or [])
                                 if isinstance(c, dict) and c.get("id")}
            except Exception:                                 # noqa: BLE001
                lazy["board"] = {}
        return lazy["board"]

    def _slug_of(cid):
        st = checks.get(str(cid)) or {}
        return str(st.get("slug") or (_board().get(str(cid)) or {}).get("slug") or "")

    def _cid_of(slug):
        for k, st in checks.items():
            if st.get("slug") == slug:
                return k
        for k, c in _board().items():
            if c.get("slug") == slug:
                return k
        return ""

    plan = cw.plan_manual(parsed, cid_in, slug_in, entries, _slug_of, _cid_of)
    if not plan["ok"]:
        return _say(plan["reason"])
    slug, cid = plan["slug"], plan["cid"]
    last = _cw_state["manual"].get(slug)
    if last is not None and 0 <= now - last < cw.MANUAL_COOLDOWN_S:
        return _say("cooldown", cid=cid, slug=slug)
    _cw_state["manual"][slug] = now
    ids = plan["entry_ids"]
    entry = ids[0] if ids and len(ids) == 1 else ""
    try:
        session = core._make_session(None)
        uid = str(_pixai_client._client_of(session).user_id or "")
        if not uid:
            raise ValueError("no account id resolved")
        rows = _contests.contest_winners(session, slug)              # one GET, nothing else
    except Exception as e:                                    # noqa: BLE001
        return _say("failed", entry, cid=cid, slug=slug,
                    detail=_redact_host_paths_cli(out_dir, str(e))[:200])
    res = cw.verify(rows, uid, ids)
    if not res["wins"]:
        return _say(res["outcome"], entry, cid=cid, slug=slug, decided=res["decided"])
    reward = str(((_board().get(cid) if cid else None) or {}).get("reward_status") or "")

    def _do(w, ch):
        for win in res["wins"]:
            cw.record_win(w, cid or slug, win, "check", now,
                          parsed["receipt"] or cw.artwork_url(win["artwork_id"]))
        st = ch.get(cid)
        if isinstance(st, dict) and st.get("status") == cw.PENDING:
            cw.after_read(st, now, res, reward)
    _cw_edit(out_dir, _do)
    listed = [{"artwork_id": x["artwork_id"], "tier": x["tier"], "prize_amount": x["prize"],
               "label": cw.tier_label(x["tier"], x["prize"])} for x in res["wins"]]
    return 200, {"verified": True, "state": "verified", "message": cw.message("verified"),
                 "wins": listed, "cid": cid, "slug": slug,
                 "receipt_url": parsed["receipt"] or cw.artwork_url(res["wins"][0]["artwork_id"])}


def _cw_check_view(state, now):
    """Where the daily check stands for one contest, for the My-entries row: {state, last_at,
    next_at, until, decided}. `state` is "none" (no schedule yet), "pending", "settled" or
    "expired"; times are epoch seconds (0 when not applicable)."""
    if not isinstance(state, dict):
        return {"state": "none", "last_at": 0, "next_at": 0, "until": 0, "decided": False}
    status = contest_wins.effective_status(state, now)
    return {"state": status, "last_at": float(state.get("last_at") or 0.0),
            "next_at": float(state.get("next_at") or 0.0) if status == contest_wins.PENDING else 0,
            "until": contest_wins.deadline(state), "decided": bool(state.get("decided"))}

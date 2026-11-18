"""
moonglade/telemetry.py
======================
Telemetry: the persisted counters behind every achievement metric that is not a cheap catalog
count (the telem_* bumps, flags, sets and day marks, the file lock they share, the vigil and
session-hour flags, telemetry_metrics and the sweep). Moved verbatim out of
moonglade/gallery.py in the 3.21.0 split (phase 3).

The names it needs from elsewhere (the catalog opener, the branding readers, the achievement
state) are imported inside each function that uses them, never at the top, so importing this
module never imports the gallery.
"""
import json
import os
import sqlite3
import threading

from moonglade import contest_wins
from moonglade import paths as _paths

# ---------------------------------------------------------------------------
# Telemetry: the persisted counters behind every achievement metric that is NOT
# a cheap catalog COUNT (edits run, pieces culled, distinct days, feat events...).
# One JSON file beside achievements.json; every write is lock-guarded and
# fail-soft so a telemetry hiccup can NEVER break a backup, a gen, or a page.
# Call sites bump via telem_*(); out_dir defaults to the process-wide value set
# once by create_app()/the CLI so deep call sites need no plumbing.
# ---------------------------------------------------------------------------
_TELEM_LOCK = threading.Lock()
_TELEM_OUT = None            # set by set_telemetry_out(); None -> bare bumps no-op


def _telemetry_path(out_dir):
    return _paths.records_path(out_dir, "telemetry.json")


def set_telemetry_out(out_dir):
    """Point the bare telem_* helpers at this install's out_dir (server + CLI)."""
    global _TELEM_OUT
    _TELEM_OUT = out_dir


_TELEM_EMPTY = {"counters": {}, "maxima": {}, "sets": {}, "flags": {}, "days": [],
                "day_lists": {}, "baselines": {}, "contest_results": {}}
# `baselines` is the ONE section telemetry_metrics() deliberately ignores: it is
# not a metric, it is remembered STATE -- a snapshot of what was already on disk
# the first time a detector looked, so a later comparison can tell "this was
# always here" from "this is new". Today the only detector using it is the coded
# branding tree's, and its keys are _BASELINE_GOODS plus the identity of the app
# folder whose tree was snapshotted (_baseline_key): this file lives in the
# LIBRARY, the tree does not, so one library can legitimately hold one snapshot
# per app folder it has been pointed at. A dict of named snapshots rather than a
# bare map, so a second detector can never have to rename the first one's key.
#
# `contest_results` is the other structured section (L3, moonglade/contest_wins.py): the
# VERIFIED contest wins ({"wins": {contest_id: {artwork_id: record}}}) and the schedule of the
# automatic win check ({"checks": {contest_id: row}}). The contest-win metric counts `wins`
# and nothing else; the flat `contest_win_keys` set an older sweep wrote is left in place,
# untouched, as the record that a contest was once believed won.


def load_telemetry(out_dir):
    """The persisted counter bundle. Missing/corrupt file -> empty defaults."""
    try:
        d = json.loads(_telemetry_path(out_dir).read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not a dict")
    except (OSError, ValueError):
        d = {}
    out = {}
    for k, dflt in _TELEM_EMPTY.items():
        v = d.get(k)
        if isinstance(v, type(dflt)):
            out[k] = v
        else:
            out[k] = dict(dflt) if isinstance(dflt, dict) else list(dflt)
    return out


def _save_telemetry(out_dir, data):
    """Atomic write (tmp + os.replace, the same idiom as download's .part) so a
    reader can never see a half-written file -- a torn read would fail-soft to
    empty defaults and the next mutate would persist that wipe."""
    try:
        p = _telemetry_path(out_dir)
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _telem_file_lock(out_dir):
    """Best-effort CROSS-PROCESS lock (the server + a Panel CLI job can both bump
    the same ledger). O_EXCL lockfile, short spin, stale takeover; on timeout we
    proceed anyway -- a rarely-lost bump beats a blocked backup. Returns the lock
    path if acquired (caller unlinks), else None."""
    return _excl_lockfile(_telemetry_path(out_dir).with_suffix(".lock"))


def _excl_lockfile(lock, wait_s=2.0, stale_s=10.0):
    """The O_EXCL lockfile behind _telem_file_lock, shared with the per-account prefs
    store: create `lock` exclusively, spinning up to `wait_s`; a lock older than
    `stale_s` is a crashed writer's and is taken over. Returns the lock path if
    acquired (the caller unlinks it), else None -- what a None MEANS is the caller's
    call: telemetry proceeds anyway, the prefs store refuses the write."""
    import time as _t
    deadline = _t.monotonic() + wait_s
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock
        except FileExistsError:
            try:                       # a crashed writer's lock goes stale fast
                if _t.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if _t.monotonic() > deadline:
                return None
            _t.sleep(0.02)
        except OSError:
            return None


def _telem_mutate(out_dir, fn):
    """Load-mutate-save under both locks (thread + process). fn(data) edits in
    place. Fail-soft: telemetry must never break a backup, a gen, or a page."""
    out_dir = out_dir if out_dir is not None else _TELEM_OUT
    if out_dir is None:
        return
    try:
        with _TELEM_LOCK:
            lock = _telem_file_lock(out_dir)
            try:
                d = load_telemetry(out_dir)
                fn(d)
                _save_telemetry(out_dir, d)
            finally:
                if lock is not None:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
    except Exception:
        pass


def telem_bump(key, n=1, out_dir=None):
    """counters[key] += n (e.g. 'edits', 'culled', 'uploads', 'narrator_pokes')."""
    _telem_mutate(out_dir, lambda d: d["counters"].__setitem__(
        key, int(d["counters"].get(key, 0) or 0) + int(n)))


def telem_max(key, value, out_dir=None):
    """maxima[key] = max(old, value) (e.g. 'lora_stacked')."""
    _telem_mutate(out_dir, lambda d: d["maxima"].__setitem__(
        key, max(int(d["maxima"].get(key, 0) or 0), int(value))))


def telem_set_discard(key, value, out_dir=None):
    """sets[key] -= {value}. Returns True when something was actually removed.

    These sets are GROW-ONLY by design -- they are the ladder's memory, and a metric that
    can fall is a metric that can un-earn an achievement. This exists for the one case
    that is not a retraction but a CORRECTION: a key written under an identity the app has
    since learned was wrong, where the true key is being written in the same breath. The
    count does not fall; a duplicate of something already counted stops being counted
    twice. Every caller must be able to prove the two keys are the same thing, and the
    removal is logged."""
    removed = {"n": 0}

    def _discard(d):
        cur = d["sets"].get(key)
        if not isinstance(cur, list):
            return
        v = str(value)
        if v in cur:
            cur.remove(v)
            removed["n"] = 1
        d["sets"][key] = cur
    _telem_mutate(out_dir, _discard)
    if removed["n"]:
        import logging as _logging
        _logging.getLogger(__name__).info(
            "telemetry: discarded one superseded %s key", key)
    return bool(removed["n"])


def telem_set_add(key, value, out_dir=None):
    """sets[key] |= {value} (e.g. 'video_modes', 'tools', 'loras')."""
    def _add(d):
        cur = d["sets"].get(key)
        if not isinstance(cur, list):
            cur = []
        v = str(value)
        if v and v not in cur:
            cur.append(v)
        d["sets"][key] = cur
    _telem_mutate(out_dir, _add)


def telem_set_add_many(key, values, out_dir=None):
    """sets[key] |= set(values), in ONE write. Returns how many were new. A caller with a
    batch (a Runs read, a bulk delete) must not rewrite the store once per member, and a
    batch with nothing new does not write at all."""
    vals = [str(v) for v in (values or []) if str(v)]
    if not vals:
        return 0
    target = out_dir if out_dir is not None else _TELEM_OUT
    if target is None:
        return 0
    have = load_telemetry(target)["sets"].get(key)
    have = set(have) if isinstance(have, list) else set()
    if not (set(vals) - have):
        return 0
    added = {"n": 0}

    def _add(d):
        cur = d["sets"].get(key)
        if not isinstance(cur, list):
            cur = []
        seen = set(cur)
        for v in vals:
            if v not in seen:
                cur.append(v)
                seen.add(v)
                added["n"] += 1
        d["sets"][key] = cur
    _telem_mutate(out_dir, _add)
    return added["n"]


def telem_flag(key, out_dir=None):
    """flags[key] = 1, once (e.g. 'konami_triggered'). Idempotent."""
    _telem_mutate(out_dir, lambda d: d["flags"].__setitem__(key, 1))


def telem_mark_day(out_dir=None, keys=None):
    """Record today (idempotent) in the distinct-days ledger. `keys=None` marks the legacy
    flat `days` list -- byte-identical to before (The Vigil / days_used). Otherwise mark today
    under each named per-key list in `day_lists` (e.g. gen_days / curation_days / active_days),
    for the streak + long-watch metrics. A given key records a day at most once."""
    import datetime as _dt
    today = _dt.date.today().isoformat()

    def _mark(d):
        if keys is None:
            if today not in d["days"]:
                d["days"].append(today)
            return
        dl = d.setdefault("day_lists", {})
        if not isinstance(dl, dict):
            dl = {}
            d["day_lists"] = dl
        for k in keys:
            lst = dl.get(k)
            if not isinstance(lst, list):
                lst = []
            if today not in lst:
                lst.append(today)
            dl[k] = lst
    _telem_mutate(out_dir, _mark)


def _best_day_streak(days):
    """Best-ever run of consecutive calendar days in an ISO-date list. A later gap never
    un-earns an already-reached streak (the metric is a high-water mark, like the maxima).
    A malformed/empty list -> 0; unparseable dates are skipped."""
    import datetime as _dt
    dates = set()
    for s in (days or []):
        try:
            dates.add(_dt.date.fromisoformat(str(s)))
        except (TypeError, ValueError):
            continue
    if not dates:
        return 0
    one = _dt.timedelta(days=1)
    best = 0
    for d in dates:
        if (d - one) in dates:
            continue                       # not a run start
        run, cur = 1, d
        while (cur + one) in dates:
            cur += one
            run += 1
        if run > best:
            best = run
    return best


def vigil_status(days, today=None):
    """The Vigil chip's numbers (Folio for completionists, O5): {"day": int, "best": int}.

    `days` is the ISO-date list of days that had at least one generation collected (the
    `gen_days` ledger, marked by the server's LOCAL date, date.today(); Seven Candles read it
    too until 2026-10-02 and counts the catalog's in-app rows now).

    `day` is the run of consecutive generation days that ends today -- or ends yesterday when
    today has none YET, because a day that has not finished is not a missed one. A run that
    ended before yesterday is over: the chip starts again at day 1. It is never 0 and never
    says a word about a miss; there is no message, no toast and no state to explain, only a
    smaller number. `best` is the longest run ever recorded, and is never below `day`.

    A malformed list, a date in the future or an unparseable entry is skipped, never raised."""
    import datetime as _dt
    if today is None:
        today = _dt.date.today()
    elif isinstance(today, str):
        today = _dt.date.fromisoformat(today)
    dates = set()
    for s in (days or []):
        try:
            d = _dt.date.fromisoformat(str(s))
        except (TypeError, ValueError):
            continue
        if d <= today:
            dates.add(d)
    one = _dt.timedelta(days=1)
    anchor = today if today in dates else (today - one if (today - one) in dates else None)
    run = 0
    if anchor is not None:
        cur = anchor
        while cur in dates:
            run += 1
            cur -= one
    day = max(1, run)
    return {"day": day, "best": max(day, _best_day_streak([d.isoformat() for d in dates]))}


def telemetry_metrics(out_dir, telem=None):
    """Flatten the telemetry store into the achievement metric namespace.
    Counters/maxima pass through, sets become cardinalities, flags become 0/1.

    `telem` lets a caller that has ALREADY loaded the store hand it in rather than
    making this parse the file again. /api/achievements needed the store three times
    over (here, in first_sync_complete, and for compute's `sets`) and was reading and
    JSON-parsing it three times per request; it now loads once and passes it through.
    Absent, the behaviour is exactly as before."""
    d = load_telemetry(out_dir) if telem is None else telem
    m = {}
    for src in (d["counters"], d["maxima"]):
        for k, v in src.items():
            try:
                m[k] = int(v or 0)
            except (TypeError, ValueError):
                m[k] = 0
    # Counted from the catalog now (achievement_metrics), and the merge everywhere is
    # catalog-then-telemetry: an old or hand-edited counter of the same name would win it,
    # so these names never come out of the store (owner 2026-10-02, evidence-based counts).
    for k in CATALOG_EVIDENCE_METRICS:
        m.pop(k, None)
    sets = d["sets"]

    def _card(key):                 # hostile-but-valid JSON must not len()-crash
        v = sets.get(key)
        return len(v) if isinstance(v, list) else 0
    m["video_modes_used"] = _card("video_modes")
    m["tools_used"] = _card("tools")
    m["enhance_workflows_distinct"] = _card("enhance_workflows")
    # The Academy (loras_trained): training runs PIXAI reports as finished, recorded by id
    # when Runs is listed (api_train_runs) -- not accepted submits, so a failed run, its
    # retry and a replayed request add nothing. The old submit counter is not read.
    m["loras_trained"] = _card("trained_runs")
    # The Great Sweep (culled): the count kept before 2026-10-02 (no longer written) plus
    # each picture removed since, ONCE -- keyed by what was removed, so deleting, restoring
    # and deleting the same picture again is one.
    m["culled"] = int(m.get("culled", 0) or 0) + _card("culled_keys")
    # Folio expansion set-cardinalities (count only -- the underlying scene ids / preset
    # names never leave the store).
    m["scenes_used"] = _card("scenes")                        # Doorwarden
    m["bridge_gens"] = _card("bridge_gen_tasks")              # Speak, Friend: distinct bridge tasks (re-poll-safe)
    # Contests. ONE dedupe set per metric is the whole rule: the publish-time hook, the
    # explicit entry route and the detection poll all write the SAME keys, so the same
    # image in the same contest can never count twice no matter which path saw it, an
    # entry made off-app still lands, and a failed submit writes nothing. Values are
    # "{contest_id}:{artwork_id}" / "{contest_id}" and never leave the store -- only the
    # count does. Deliberately NOT also counters: the assignment below would shadow a
    # same-named counter, and one source of truth is the point.
    m["contest_entries"] = _card("contest_entry_keys")
    # VERIFIED wins only (L3). `contest_win_keys` is what the old sweep wrote when a winners
    # row merely carried this account's authorId: no artwork id, no tier, no receipt. That set
    # is kept on disk but no longer counted; a win counts once a check has matched the entry's
    # artwork id to a row with an integer rank (moonglade.contest_wins.verify).
    _cres = d.get("contest_results")
    m["contest_wins"] = contest_wins.verified_count(
        _cres.get("wins") if isinstance(_cres, dict) else None)
    # Blades of Gondolin (enhance_tools_complete): mastery of all SIX gen-drawer enhance tools.
    # The five non-emotion presets each count once used; Change Emotion counts only when EVERY
    # emotion in the universe has been used. The preset keys and the emotion-universe size come
    # from core -- never hardcoded -- and ONLY the computed count is exposed (the underlying tool
    # keys and emotion keys never leave the store). Silent-soft: an absent/bad core resolves to 0.
    try:
        from moonglade import backup as _core
        _non_emotion = set()
        for pp in getattr(_core, "BRIDGE_ENHANCE_PRESETS", ()):
            _k = str(pp.get("key") or "").strip()
            if _k and _k != "emotion":
                _non_emotion.add(_k)
        _tools = sets.get("enhance_tools")
        _tools = set(_tools) if isinstance(_tools, list) else set()
        _universe = len(getattr(_core, "ENHANCE_EMOTION_PROMPTS", ()) or ())
        _emotion_done = _universe > 0 and _card("enhance_emotions") >= _universe
        m["enhance_tools_complete"] = len(_tools & _non_emotion) + (1 if _emotion_done else 0)
    except Exception:
        m["enhance_tools_complete"] = 0
    for k, v in d["flags"].items():
        m[k] = 1 if v else 0
    m["days_used"] = len(d["days"])
    # Keyed day-lists -> the streak + long-watch metrics. Each per-key list is validated
    # here (a hostile file could store a non-list) before it is measured.
    dl = d.get("day_lists") if isinstance(d.get("day_lists"), dict) else {}

    def _days(key):
        v = dl.get(key)
        return v if isinstance(v, list) else []
    # (gen_streak is the catalog's now -- achievement_metrics; the gen_days ledger still
    # feeds the Vigil chip.)
    m["curation_streak"] = _best_day_streak(_days("curation_days"))    # Lamplighter
    m["distinct_active_days"] = len(set(_days("active_days")))         # Long Vigil / Unbroken Watch
    return m


# Metrics achievement_metrics() counts from the catalog that used to be telemetry counters.
# telemetry_metrics() drops these names, so an old counter cannot shadow the catalog's count.
CATALOG_EVIDENCE_METRICS = ("edits", "lora_used", "lora_stacked", "lora_distinct", "gen_streak")


# ---- the `session_hour` flag: a NEW generation made in its window ----------------------
# Owner, 2026-10-02: the honor on this metric is earned by a NEW in-app generation actually
# MADE in its local hour window -- never by opening a page then (what /api/achievements used
# to check), and never retroactively by a generation made before this rule. So the flag is
# stamped at the one moment a generation is new: when this server collects it into the
# catalog (_collect_single_flight), and only when PixAI's own timestamp on the row
# (created_at, UTC) is in the window AND recent. "Recent" is what makes it new: collecting or
# importing an old task that dates from the window is not evidence of anything tonight.
SESSION_HOUR_WINDOW = (2, 4)              # local hours, [start, end)
SESSION_HOUR_FRESH_S = 6 * 3600           # older than this when collected is not new
_SESSION_HOUR_SKEW_S = 300                # PixAI's clock may run a little ahead of ours


def _utc_now():
    """The real clock, aware, in UTC -- one seam so a test can stand at any hour."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)


def session_hour_generation(created_at, now=None):
    """True when `created_at` -- a catalog row's PixAI timestamp, ISO UTC -- is a generation
    made inside SESSION_HOUR_WINDOW local time AND new as of `now` (aware; default the real
    clock). Unparseable or blank -> False, never raises."""
    import datetime as _dt
    raw = str(created_at or "").strip()
    if not raw:
        return False
    try:
        t = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_dt.timezone.utc)        # the catalog stores UTC
        age = ((now or _utc_now()) - t).total_seconds()
        hour = t.astimezone().hour
    except (ValueError, OverflowError, OSError, TypeError):
        return False
    if age < -_SESSION_HOUR_SKEW_S or age > SESSION_HOUR_FRESH_S:
        return False
    lo, hi = SESSION_HOUR_WINDOW
    return lo <= hour < hi


def stamp_session_hour(db_path, media_ids, out_dir, now=None):
    """Set the `session_hour` flag when any of `media_ids` -- just collected -- is an in-app
    row (source api/local) session_hour_generation() accepts. True when it stamped. Reads the
    catalog only; fail-soft."""
    from moonglade.gallery import catalog
    ids = [str(x) for x in (media_ids or []) if str(x).strip()]
    if not ids:
        return False
    try:
        with catalog(db_path) as con:
            rows = con.execute(
                "SELECT created_at FROM catalog WHERE source IN ('api','local') "
                "AND media_id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
    except sqlite3.Error:
        return False
    if any(session_hour_generation(r[0], now) for r in rows):
        telem_flag("session_hour", out_dir=out_dir)
        return True
    return False


def first_sync_complete(out_dir, db_path, telem=None):
    """True once the first FULL library sync has finished -- the gate that stops the
    achievement unlock toasts from firing mid-first-sync. `first-light` is metric
    images>=1, so without this gate it pops the instant image #1 lands, seconds into a
    fresh install's very first sync (and every image rung crosses the same way). While
    this is False, /api/achievements withholds `newly` and leaves `seen` untouched, so
    the rungs earned during the first sync fire together AFTER it completes, not during.

    Set by `--sync`'s completion (telem flag 'first_sync_done') -- the CLI path AND the
    wizard's sync job both run `--sync`, so one setter covers both. Refined 2026-09-07
    (owner report): --sync used to set it on EVERY exit, so a first backup stopped
    part-way plus a two-page Sync claimed a finished first sync over a mostly-empty
    library. It is now set only once that library's walk has reached the end of history
    (moonglade.backup.WALK_END_FLAG), so this gate says what its name says.

    Backfill for PRE-EXISTING installs so they neither suppress nor spam: keyed on
    prior achievement recognition (`seen`/`earned_at` present), NOT on images>0. An
    images-based backfill would re-fire the bug -- during a fresh first sync the image
    count climbs above zero, so it would flip the flag mid-sync. Any install that has
    ever surfaced an achievement has a non-empty `seen`/`earned_at`; a fresh mid-first-
    sync install cannot (the gate keeps `seen` empty until completion). The rare install
    with a real library but a pristine achievement state simply resolves on its next
    `--sync`."""
    from moonglade.achievements import load_ach_state
    try:
        d = load_telemetry(out_dir) if telem is None else telem
        if d["flags"].get("first_sync_done"):
            return True
        st = load_ach_state(out_dir)
        if st.get("seen") or st.get("earned_at"):
            telem_flag("first_sync_done", out_dir=out_dir)
            return True
    except Exception:                                    # never let the gate crash the route
        return True                                      # fail OPEN: a broken gate must not hide trophies forever
    return False


def sweep_telemetry(out_dir):
    """Set the state-derived flags whose 'event' may predate the telemetry
    layer: art in the coded branding tree that this install's baseline does not
    account for, and the eclipse mark animation. Once set they stay set. Cheap;
    called by the API on a once-a-day cadence.

    A BACKSTOP, and it asks the same question the same way: the coded-tree check
    here is literally _branding_tree_has_new_art(), the one detector
    sweep_branding_drops() runs on every /api/achievements fetch. One function,
    two callers, one answer -- an earlier arrangement had this backstop applying
    a narrower rule of its own (a loose marks.json entry with loose art), which
    could contradict the wide scan in both directions: it saw a registered mark
    the scan had already accepted as a default, and it was blind to a drop
    anywhere outside the marks folder.

    Nothing is written into the tree and nothing is adopted here -- the scan is
    read-only, and the only writes are the telemetry flags themselves."""
    from moonglade.branding import _branding_tree_has_new_art, load_branding
    try:
        if _branding_tree_has_new_art(out_dir):
            telem_flag("branding_custom_file", out_dir=out_dir)
        if load_branding(out_dir).get("anim") == "eclipse":
            telem_flag("eclipse_anim_triggered", out_dir=out_dir)
    except Exception:
        pass

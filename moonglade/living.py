"""
moonglade/living.py
===================
The Living Library: the in-process artworks sweep (the published-works refresh, its
single-flight lock, kicks and refusal note), the scheduled job list the Panel runs, and the
views-spike and published-totals readers. Moved verbatim out of moonglade/gallery.py in the
3.21.0 split (phase 3).

The names it needs from the gallery (the catalog opener, the artwork-meta writer, the path
redactor) are imported from moonglade.gallery inside each function that uses them, never at
the top, so importing this module never imports the gallery.
"""
import sqlite3
import threading
import time

from moonglade import pixai_client as _pixai_client
from moonglade import series as _series

# ======================================================================================
# THE LIVING LIBRARY (2026-09-06)
# ======================================================================================
# "It's not just a backup dump. It's a living library that should update itself and its
# data without my need to clicky click." -- the owner, 2026-09-04. Scoped in
# ../moonglade-internal/scopes/SCOPE_2026-09-04_living-library.md and answered by him on
# 2026-09-06; this is that scope's five answers in code.
#
# Two halves, and they are deliberately different animals:
#
#   * THE ARTWORKS SWEEP (below) is IN-PROCESS, modelled line for line on the contest
#     sweep above -- one single-flight lock, a "ran recently" guard, a boot kick and a
#     FORCED publish kick. It is in-process because it must be quiet: it runs every
#     fifteen minutes, and a subprocess would occupy the Panel's one job slot, spawn a
#     python, and write a row into the Activity ledger on every one of those ticks.
#     It announces only when it CHANGED something.
#
#   * THE JOB LIST (further down) is the existing scheduler, widened from one
#     {action, interval_hours} pair to several. Each entry still runs through
#     _panel_run -- the same whitelisted argv, the same one-job-at-a-time slot, the same
#     destructive/advanced refusal. A schema change, not a redesign.
#
# BOTH obey the standing rule "the library stands still -- nothing moves the owner's view
# except his own hands" (DECISIONS.md, 2026-09-05, which names living-library jobs as an
# inheritor by name). Neither half has any path to the gallery's own loaders: a finished
# job ANNOUNCES through the toast/Activity idiom the jobs ledger already drives, and never
# rebuilds the page, the search, the address or the selection. dev/tests/test_living_library.py
# walks these functions' source to keep it that way.

ARTWORKS_SWEEP_S = 900.0        # owner call 3: "15 Works, I was going to say 20. Go with 15"
                                # -- the sweep's own recent-guard; the TICK's cadence is the
                                # row's interval_s, which defaults to ARTWORKS_SWEEP_DEFAULT_S
ARTWORKS_SWEEP_DEFAULT_S = 6 * 3600.0   # 2026-11-18, owner: "Some of these items run too god
                                        # damned often" -- the sweep was every 15 minutes; the
                                        # publish kick and the boot kick still run it at once
ARTWORKS_YOUNG_DAYS = 90        # owner call 4: works this young ride EVERY sweep
ARTWORKS_DEEP_S = 172800.0      # owner call 4: older works refresh at most once per 48h
ARTWORKS_GRACE = 2              # consecutive spent pages before stopping -- run_download's
                                # own `update_grace` default (moonglade/backup.py), mirrored
ARTWORKS_PAGE = 50              # artwork list page size run_sync_artworks already uses
ARTWORKS_PAUSE = 0.4            # paced: run_sync_artworks' own inter-page delay
ARTWORKS_MAX_PAGES = 1000       # a hard stop (50,000 published works at 50 a page), so a
                                # pageInfo that never says "no more" cannot turn a
                                # background sweep into an endless walk. Reaching it is
                                # reported as INCOMPLETE, never as a finish.
ARTWORKS_STARTUP_DELAY = 25.0   # after the contest sweep's 20s, so the two never race at boot
_artworks_lock = threading.Lock()
# `at` is the last sweep that COMPLETED (the recent-guard); `deep_at` is the last one that
# was allowed to refresh works older than ARTWORKS_YOUNG_DAYS. Both are mirrored into
# schedule.json by the sweep itself so they survive a restart -- an in-memory-only deep
# stamp would make every boot a full walk, which is exactly what the tier exists to avoid.
# `kicks` counts how many times a TRIGGER asked for a sweep -- boot, tick, publish, Run
# now -- whether or not one actually started. It is the only record that a trigger fired
# at all: a kick that stands down (a Panel job in the slot, the background gate off, a
# sweep already in flight) leaves no other trace anywhere, which made "did the publish
# route really ask?" unanswerable except by reading the source.
_artworks_state = {"at": 0.0, "deep_at": 0.0, "changed": 0, "pages": 0, "kicks": 0}
# Whether the sweep has already said, in plain words, why it could not read the published
# list. A sweep that is refused every fifteen minutes says so ONCE and then stays quiet at
# debug level; the first sweep that reads the whole list again clears it.
_artworks_refusal = {"reported": False}


def _note_artworks_refusal(log, out_dir, page, err):
    """Say why the sweep could not read the published list: once, in plain words, with the
    reason PixAI or the network gave (folder paths hidden), then quietly while it lasts."""
    from moonglade.redact import _redact_host_paths_cli
    reason = _redact_host_paths_cli(out_dir, str(err))[:300]
    if _artworks_refusal["reported"]:
        log.debug("artworks sweep: page %d still cannot be read: %s", page, reason)
        return
    _artworks_refusal["reported"] = True
    log.warning(
        "artworks sweep: the app cannot read your published artworks from PixAI (page %d), "
        "so their titles, likes and tags are not refreshing. Reason: %s. The sweep tries "
        "again on its schedule; this is said once until a read works again.", page, reason)


def published_index(db_path):
    """media_id -> (artwork_id, created_epoch_or_None) for every catalog row that already
    claims an artwork. The sweep's whole idea of "do I already know this work, and is it
    young?" -- one indexed read, no network, ~36k rows of two small values."""
    from moonglade.catalog import catalog
    idx = {}
    try:
        with catalog(db_path) as con:
            for r in con.execute(
                    "SELECT media_id, artwork_id, created_at FROM catalog "
                    "WHERE COALESCE(artwork_id,'') != ''"):
                idx[str(r["media_id"])] = (str(r["artwork_id"] or ""),
                                           _series._series_ts(r["created_at"]))
    except sqlite3.Error:
        return {}
    return idx


def published_local_ids(db_path):
    """Every media_id the catalog holds -- the sweep's "is there a local row at all?" set.

    The companion to published_index, and the difference between the two is the whole of
    the short-circuit's convergence. published_index only holds rows that ALREADY claim an
    artwork, so a work missing from it is either brand new (a downloaded generation just
    published) or permanently unmatched (published on the website, never downloaded here).
    The sweep cannot write the second kind at all -- apply_artwork_meta only UPDATEs rows
    that exist -- so treating it as "might be new" made it hold the walk open forever.

    One indexed column scan, no row bodies, the same shape published_index already is."""
    from moonglade.catalog import catalog
    ids = set()
    try:
        with catalog(db_path) as con:
            for r in con.execute("SELECT media_id FROM catalog"):
                ids.add(str(r["media_id"]))
    except sqlite3.Error:
        return set()
    return ids


def artworks_page_needed(nodes, index, now, deep, local=None):
    """Does this page of artwork-list nodes contain anything this sweep needs to write?

    THE SHORT-CIRCUIT AND THE TIER, in one predicate -- and the reason a quiet sweep costs
    one or two pages instead of the whole walk. `run_download --update` stops after
    `update_grace` consecutive pages whose every media_id was already on disk
    (moonglade/backup.py's `page_new`); the artwork list pages newest-first exactly like the
    generation feed, so the same stop works here. What "already known" means is where the
    owner's tier (call 4) lives:

      * an artwork with no catalog row claiming its artwork_id, but WITH a local row ->
        NEEDED. Newly published work is why the sweep exists, and it arrives at the
        newest end.
      * an artwork with NO LOCAL ROW AT ALL -> spent, not needed. This one is the
        difference between a sweep that converges and one that does not. Such a work is
        published on PixAI and was never downloaded here, so apply_artwork_meta has
        nothing to update and the sweep can never write it -- no number of pages will
        change that. Read as "never merged" it was NEEDED on every sweep forever, and a
        run of them before the stable tail meant every fifteen-minute sweep walked the
        whole published history rather than the one or two pages the design promises.
        `local` (published_local_ids) is what tells "brand new" from "confirmed miss";
        without it the old, non-converging answer stands.
      * a work younger than ARTWORKS_YOUNG_DAYS -> NEEDED on every sweep. Its like and
        comment counts are the ones still moving.
      * an older work -> needed only when `deep`, i.e. when ARTWORKS_DEEP_S has passed
        since the last deep pass. That is "older than 90 days refresh at most once every
        48 hours" stated as a walk rather than as ~36k per-row timestamps: the sweep
        always starts at the newest end, so one global stamp says the same thing and
        costs one integer instead of a schema migration.

    A node with no mediaId is ignored rather than treated as new -- it can never be
    matched to a row, so it must not be able to hold the walk open forever."""
    young_s = ARTWORKS_YOUNG_DAYS * 86400.0
    for node in nodes or []:
        mid = str((node or {}).get("mediaId") or "")
        vmid = str((node or {}).get("videoMediaId") or "")
        known = index.get(mid) or index.get(vmid)
        if not known:
            if local is not None and mid not in local and vmid not in local:
                continue                     # confirmed miss: no row here to write
            return True                      # never merged this artwork -> fetch it
        if deep:
            return True                      # the 48h pass refreshes every age
        ts = known[1]
        if ts is None or (now - ts) <= young_s:
            # No parseable creation date is treated as YOUNG on purpose: the sweep would
            # rather pay for a row it could not date than silently stop refreshing it.
            return True
    return False


def artworks_sweep(out_dir, db_path, force=False, now=None, log_event=None):
    """One pass of the published-artwork sweep. Returns {changed, pages, artworks, deep,
    incomplete} -- or None when it refused to run (recent enough, and not forced).

    THE THREE TRIGGERS, exactly the contest sweep's: a boot kick, a periodic kick from the
    scheduler's own 60-second tick, and a FORCED kick the instant something is published,
    unpublished or re-tagged from this app. Same lock discipline, same "PixAI is the truth,
    the client's word is not" stance -- the publish route already wrote what it believes
    into the catalog; this reads back what PixAI actually says.

    Writes go through apply_artwork_meta: one narrow UPDATE per row it actually saw,
    eleven PixAI-owned columns, no full-catalog rewrite. Nothing here can create, move or
    delete a row or a file.

    `log_event` is the announcement seam (the create_app closure's _log_job). It is called
    ONLY when the sweep changed something -- a fifteen-minute heartbeat that wrote a row
    into the Activity ledger every time would bury the events that matter under its own
    noise. It is the ONLY thing this function tells the browser; there is no path from
    here to the gallery's loaders."""
    from moonglade.catalog_verbs import apply_artwork_meta
    from moonglade.redact import _redact_host_paths_cli
    import logging as _logging
    import uuid as _uuid
    from moonglade import backup as core
    log = _logging.getLogger(__name__)
    now = time.time() if now is None else now
    if not force and (now - _artworks_state["at"]) < ARTWORKS_SWEEP_S:
        return None
    deep = (now - _artworks_state["deep_at"]) >= ARTWORKS_DEEP_S
    try:
        session = core._make_session(None)
        if not _pixai_client._client_of(session).user_id:
            log.info("artworks sweep: no account id resolved -- nothing to read")
            return None
    except Exception as e:                                   # noqa: BLE001
        log.warning("artworks sweep: no session: %s: %s", type(e).__name__,
                    _redact_host_paths_cli(out_dir, str(e))[:200])
        return None

    index = published_index(db_path)
    local = published_local_ids(db_path)
    metas, before, pages, artworks, spent = [], None, 0, 0, 0
    incomplete = refused = False
    while True:
        if pages >= ARTWORKS_MAX_PAGES:
            # A hard stop, so a pageInfo that never says "no more" cannot turn a background
            # sweep into an endless walk. Reaching it is INCOMPLETE, not a finish: the tail
            # of the history was never read, so this run must not stamp the 48-hour tier as
            # satisfied and must not buy itself fifteen minutes of quiet.
            log.warning("artworks sweep: hit the %d-page cap -- the walk is incomplete",
                        ARTWORKS_MAX_PAGES)
            incomplete = True
            break
        try:
            conn = core.artwork_list_gql(session, before=before, last=ARTWORKS_PAGE, retries=0)
        except core.ArtworkListRefused as e:
            # A page that cannot be read. Whatever was collected is real and is written
            # below; the run is simply incomplete, and an incomplete sweep must NOT buy
            # fifteen minutes of silence -- see the `at` stamp at the end, which only a
            # clean finish reaches. The reason is said once, not on every sweep.
            _note_artworks_refusal(log, out_dir, pages + 1, e)
            incomplete = refused = True
            break
        pages += 1
        edges = conn.get("edges") or []
        if not edges:
            break
        nodes = [(e.get("node", e) or {}) for e in edges]
        if artworks_page_needed(nodes, index, now, deep, local=local):
            spent = 0
            for node in nodes:
                # PER NODE, not per page or per run. extract_artwork_meta reads a dict PixAI
                # sent us -- a shape this app does not control and has already seen change
                # (isSensitive and the nsfwPredict block both arrived without notice). One
                # malformed node raising here used to abort the whole walk through
                # artworks_sweep_kick's catch-all, discarding every meta collected so far
                # AND leaving the run unstamped. A skip costs one row until the next sweep;
                # the alternative costs the entire pass, every fifteen minutes, forever.
                try:
                    meta = core.extract_artwork_meta(node)
                    if meta.get("media_id"):
                        metas.append(meta)
                        artworks += 1
                    vmid = str(node.get("videoMediaId") or "")
                    if vmid:
                        # The animation's own row is keyed by its mp4's media_id (#20), so
                        # it wants the same metadata under that key.
                        vmeta = dict(meta)
                        vmeta["media_id"] = vmid
                        metas.append(vmeta)
                except Exception as e:                       # noqa: BLE001
                    log.warning("artworks sweep: skipping a malformed artwork node: %s: %s",
                                type(e).__name__, str(e)[:160])
        else:
            spent += 1
            if spent >= ARTWORKS_GRACE:
                break
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
        time.sleep(ARTWORKS_PAUSE)

    if not refused and _artworks_refusal["reported"]:
        # Every page this sweep asked for was read: the earlier refusal is over, and the
        # next one is worth saying again.
        _artworks_refusal["reported"] = False
        log.info("artworks sweep: your published artworks can be read from PixAI again")

    changed = 0
    if metas:
        try:
            changed = apply_artwork_meta(db_path, metas)
        except sqlite3.Error as e:
            log.warning("artworks sweep: catalog write failed: %s", str(e)[:200])
    # ONLY A CLEAN FINISH STAMPS, exactly as the contest sweep's own last_ok does. A run
    # that stopped on a failed page or hit the page cap never saw the tail of the history:
    # buying itself fifteen minutes of quiet would delay the retry, and stamping the
    # 48-hour tier would tell the next two days' worth of sweeps that old works had been
    # refreshed when they had not.
    #
    # Stamped with `now` -- the moment the sweep DECIDED, not the moment it finished. Two
    # reasons: a deep pass can take minutes, and measuring the guard from the end would let
    # every sweep drift later than the cadence the owner set; and `now` is the same clock
    # the tier and the guard were read from, so the function has exactly one idea of time
    # (which is what makes a mock clock able to prove any of this).
    if not incomplete:
        _artworks_state["at"] = now
        if deep:
            _artworks_state["deep_at"] = now
    _artworks_state["changed"] = changed
    _artworks_state["pages"] = pages
    if changed and log_event:
        # THE ANNOUNCEMENT, and the whole of it. The Activity card already polls /api/jobs;
        # a finished sweep lands there as a row exactly like a Panel job does. It does not
        # touch the grid, the page, the address or the selection -- the library stands still.
        try:
            log_event("living-artworks-" + _uuid.uuid4().hex[:12], status="done",
                      type="panel", action="artworks-sweep",
                      label="Published-artwork sweep — {} row(s) refreshed".format(changed),
                      rc=0)
        except Exception:                                    # noqa: BLE001
            pass
    return {"changed": changed, "pages": pages, "artworks": artworks, "deep": deep,
            "incomplete": incomplete}


def artworks_sweep_fresh(interval_s, now):
    """Has a sweep COMPLETED inside this cadence already? The boot kick's answer to the
    tick, and the reason the tick's kick is not unconditionally forced.

    THE BOOT DOUBLE-SWEEP this closes: the boot kick fires 25 seconds after start
    (ARTWORKS_STARTUP_DELAY) and the first tick lands 35 seconds after that, with the sweep
    row's last_run still unset -- so it read as due, and a forced kick re-ran the whole
    thing. On a fresh install that is the FIRST-BOOT DEEP WALK (every page of the published
    history, 0.4s apiece) twice inside one minute, over a library that could not have
    changed in between.

    Measured against _artworks_state["at"], which ONLY A CLEAN FINISH stamps -- so a run of
    failing sweeps can never read as fresh, and the retry keeps its cadence. Module-level
    and a plain function of (interval, now) for the same reason living_due and
    artworks_page_needed are: a timer that cannot be read on a mock clock cannot be
    proven."""
    return (now - _artworks_state["at"]) < max(1.0, float(interval_s or ARTWORKS_SWEEP_S))


def artworks_sweep_in_flight():
    """Is a published-artwork sweep running in THIS process right now?

    THE SECOND DIRECTION of the sweep-vs-Panel-job exclusion, and the whole of the shared
    state it needs. `_artworks_job_busy` (in create_app) already lets the sweep stand down
    for a catalog-writing Panel job; this is the same question asked the other way round,
    so a Panel job can stand down for a sweep. One lock answers both -- there is no second
    flag to keep in step.

    A non-blocking probe: acquire-and-release rather than `locked()`, because a plain
    `locked()` read is the same information with no memory barrier discipline, and this is
    read from a different thread than the one that holds it. Never blocks, so a caller
    holding another lock cannot deadlock on it."""
    if _artworks_lock.acquire(False):
        _artworks_lock.release()
        return False
    return True


def artworks_sweep_kick(out_dir, db_path, force=False, log_event=None, busy=None):
    """Run one artworks sweep under the single-flight lock, or skip if one is running.

    The lock is the whole contract, the same way it is for the contest sweep: the boot
    kick, the fifteen-minute tick, the publish kick and the Run now button all reach the
    same work, and a caller that loses the race has nothing to do. Returns the sweep's
    result dict, or None when it did not run.

    `busy` is the caller's "a catalog-writing Panel job is in the slot" check
    (create_app's _artworks_job_busy), and it is asked HERE, after the lock, rather than
    only before the kick. Before the lock there was a window: the kick read the slot, found
    it free, and a Panel job claimed it before this sweep actually started. Asked inside the
    lock it is the same instant _panel_run's own probe finds this lock held, so whichever of
    the two arrives first, the other one stands down. Passed in rather than imported because
    the slot is a create_app closure and this function is module-level and testable."""
    from moonglade.redact import _redact_host_paths_cli
    import logging as _logging
    if not _artworks_lock.acquire(False):
        return None
    try:
        if busy is not None and busy():
            return None
        return artworks_sweep(out_dir, db_path, force=force, log_event=log_event)
    except Exception as e:                                   # noqa: BLE001 -- a sweep must
        _logging.getLogger(__name__).warning(               # never kill its caller
            "artworks sweep: gave up: %s: %s", type(e).__name__,
            _redact_host_paths_cli(out_dir, str(e))[:200])
        return None
    finally:
        _artworks_lock.release()


# --- the job list -------------------------------------------------------------------
# schedule.json used to hold exactly ONE {action, interval_hours} pair: you could schedule
# one Panel action on one cadence, and that is the whole reason a published piece could
# vanish from My Art -- nothing on the machine ever re-read PixAI's list of published works
# unless a button was pressed. It now holds a LIST (owner call 1), each entry with its own
# cadence and its own last-run. The legacy pair SURVIVES UNTOUCHED as the "standing order"
# the Panel's ledger already draws; the list is additive, so no existing schedule changes
# meaning and no existing setting is rewritten under the owner.
#
# `interval_s`, not interval_hours: the artworks sweep is a fifteen-MINUTE job, and hours
# cannot say that. The legacy pair keeps its own hours field and its own clamp.
STALE_BACKSTOP_S = 60 * 86400.0     # owner call 5: a full-cost job runs by itself ONLY when
                                    # it has not run in 60 days -- a staleness backstop,
                                    # not a calendar slot.
LIVING_JOBS = (
    # action              interval        on by default   what it is
    {"action": "artworks-sweep", "interval_s": ARTWORKS_SWEEP_DEFAULT_S, "enabled": True,
     "label": "Published-artwork sweep",
     "note": "reads back what PixAI says you have published — short-circuits after two "
             "known pages, so it usually costs one or two"},
    {"action": "sync", "interval_s": 12 * 3600.0, "enabled": True, "then": "backfill-phash",
     "label": "Sync now", "note": "pull new + fill metadata, then backfill perceptual hashes"},
    # THE VIEW READ ON ITS OWN TIMER (owner's call, 2026-09-06). It is the one part of the
    # published-artwork refresh that COSTS something: asking PixAI how many views a work
    # has adds one to that number, for every published work, every time. Riding the
    # metadata refresh's cadence made that a daily +1 across the whole library. On its own
    # row it is the owner's to set, to turn off, and to see -- and the fifteen-minute
    # sweep still never reads a view count at all.
    {"action": "sync-artwork-views", "interval_s": 7 * 86400.0, "enabled": True,
     "label": "View counts",
     "note": "weekly — reads how many views each published work has. Asking adds one "
             "view to each, so this is the only job that touches those numbers"},
    {"action": "sync-videos", "interval_s": 24 * 3600.0, "enabled": True,
     "label": "Sync i2v videos", "note": "nightly — downloads mp4s for your animated works"},
    {"action": "reconcile-deleted", "interval_s": 7 * 86400.0, "enabled": True,
     "label": "Reconcile deleted", "note": "weekly — flags rows whose task is gone from PixAI"},
    {"action": "sync-similar", "interval_s": 24 * 3600.0, "enabled": True, "needs": "torch",
     "label": "Top up Similar",
     "note": "nightly, when the ML stack is installed. Heavy: don't run it beside GPU- or RAM-heavy programs."},
)
# THE STALENESS BACKSTOP (owner call 5). These three are the scope's "safe but wasteful on
# a timer" row: full re-walk, rebuild Similar, rebuild thumbnails. They have no incremental
# form, so they are never on a short cadence -- but a library whose Similar index or
# thumbnails have not been rebuilt in two months is drifting, and the owner asked for a
# floor under that. Sixty days, measured from the last run of THAT job.
#
# A job with no recorded run does NOT fire: the first tick that sees one stamps `now` as
# its baseline and runs nothing. Otherwise every fresh install would open by re-walking its
# whole history, rebuilding every thumbnail and re-embedding every image -- the exact
# opposite of a backstop.
LIVING_STALE_JOBS = (
    {"action": "resync-full", "interval_s": STALE_BACKSTOP_S, "enabled": True,
     "label": "Full re-walk", "note": "only if it has not run in 60 days"},
    {"action": "rebuild-similar", "interval_s": STALE_BACKSTOP_S, "enabled": True,
     "needs": "torch", "label": "Rebuild Similar",
     "note": "only if it has not run in 60 days. Heavy: don't run it beside GPU- or RAM-heavy programs."},
    {"action": "rebuild-thumbs", "interval_s": STALE_BACKSTOP_S, "enabled": True,
     "label": "Rebuild ALL thumbnails", "note": "only if it has not run in 60 days"},
)
LIVING_ALL = LIVING_JOBS + LIVING_STALE_JOBS
# THE DEFAULTS THAT RAN TOO OFTEN (owner, 2026-11-18: "Some of these items run too god damned
# often"). A saved row still at one of these OLD defaults -- never set by hand -- moves to the
# new default the next time the schedule is read; a cadence the owner picked in the Panel
# carries `chosen` and is never touched, whatever its value.
#   artworks-sweep   15 min -> 6 hours  (publishing still kicks it at once)
#   sync             6 hours -> 12 hours (the live mirror keeps new work coming in between)
LIVING_RETIRED_DEFAULTS = {"artworks-sweep": (900.0,), "sync": (6 * 3600.0,)}
LIVING_BY_ACTION = {j["action"]: j for j in LIVING_ALL}
LIVING_STALE_ACTIONS = frozenset(j["action"] for j in LIVING_STALE_JOBS)
# THE ONE THING AN IN-PROCESS LOCK CANNOT COVER: a SUBPROCESS. Every Panel action runs as
# its own interpreter (_panel_run -> subprocess.Popen of the CLI) with its own SQLite
# connection, so _artworks_lock -- a threading.Lock in the server process -- is invisible to
# it. These are the actions whose subprocess writes the same catalog rows the sweep writes:
#
#   sync / resync-full / test-pull -> run_download, which builds rows and save_catalog()s
#                                     them (carry-protected, but a carry still restores from
#                                     a snapshot taken when the job STARTED)
#   sync-videos                    -> run_sync_videos, same shape
#   sync-artworks                  -> run_sync_artworks, the sweep's own full re-walk
#
# The sweep defers to any of them rather than trying to interleave narrow UPDATEs with a
# job that is rebuilding rows from its own older snapshot. Deferring costs at most one
# cadence; the alternative costs whichever writer lost the race. Nothing DESTRUCTIVE is in
# here, because nothing destructive is reachable from the tick in the first place.
ARTWORKS_TOUCHING_ACTIONS = frozenset({"sync", "resync-full", "test-pull",
                                       "sync-videos", "sync-artworks"})
# The sweep is not a PANEL_ACTIONS key -- it is in-process, and the CLI has no
# short-circuiting equivalent to spawn. Named here so every caller agrees.
LIVING_SWEEP_ACTION = "artworks-sweep"
LIVING_MIN_INTERVAL_S = 60.0
LIVING_MAX_INTERVAL_S = 120 * 86400.0


def _torch_present():
    """Is the ML stack installed? `find_spec`, never `import torch` -- moonglade.similar's
    own is_available() imports it, which costs seconds and hundreds of MB, and this is
    asked on a sixty-second tick."""
    try:
        import importlib.util
        return importlib.util.find_spec("torch") is not None
    except Exception:                                        # noqa: BLE001
        return False


def living_clamp_interval(action, value, default=None):
    """One job's cadence, clamped to what this build actually allows. The ONE place that
    rule lives, so the settings route and the schedule-file normalizer cannot disagree.

    THE SIXTY-DAY FLOOR IS SERVER-SIDE, and that is the whole point of this function. The
    staleness backstop (full re-walk, rebuild Similar, rebuild ALL thumbnails) is a floor
    under a job with no incremental form -- the price of running one is the whole library,
    every time -- so it is not a dial. The Panel renders no cadence selector for those rows
    for exactly that reason. But "the client draws no control" has never been an
    enforcement: schedule.json is a plain file the owner can open, and /api/panel/schedule
    takes a jobs patch. Either could ask for a full re-walk every sixty SECONDS, and before
    this the server would have written it down and the tick would have obeyed. So the floor
    lives here, where a hand-edited file and a hand-rolled POST both have to pass through
    it, rather than in the UI that happens not to offer it."""
    spec = LIVING_BY_ACTION.get(action) or {}
    if default is None:
        default = spec.get("interval_s", LIVING_MIN_INTERVAL_S)
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    floor = STALE_BACKSTOP_S if action in LIVING_STALE_ACTIONS else LIVING_MIN_INTERVAL_S
    return max(floor, min(v, LIVING_MAX_INTERVAL_S))


def living_merge(saved):
    """Normalize whatever is in schedule.json against the shipped list.

    Unknown actions are DROPPED (a hand-edited or downgraded file must not be able to name
    a job this build does not have), missing ones are added at their defaults, intervals
    are clamped THROUGH living_clamp_interval (so a hand-edited file cannot put a full
    re-walk on a one-minute timer any more than a POST can), and the shipped order is what
    comes back so the Panel's rows never reshuffle under the owner. This is the same
    discipline the legacy pair already had -- the loop re-checks PANEL_ACTIONS rather than
    trusting the file."""
    by_action = {}
    for row in (saved or []):
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "")
        if action in LIVING_BY_ACTION:
            by_action[action] = row
    out = []
    for spec in LIVING_ALL:
        row = by_action.get(spec["action"]) or {}
        chosen = row.get("chosen") is True
        stored = row.get("interval_s")
        try:
            if (not chosen and stored is not None
                    and float(stored) in LIVING_RETIRED_DEFAULTS.get(spec["action"], ())):
                stored = None                     # an old default, never picked: the new one
        except (TypeError, ValueError):
            pass
        interval = living_clamp_interval(
            spec["action"],
            stored if stored is not None else spec["interval_s"],
            default=spec["interval_s"])
        try:
            last = None if row.get("last_run") in (None, "") else float(row["last_run"])
        except (TypeError, ValueError):
            last = None
        merged = {
            "action": spec["action"],
            "enabled": bool(row["enabled"]) if "enabled" in row else bool(spec["enabled"]),
            "interval_s": interval,
            "last_run": last,
        }
        if chosen:
            merged["chosen"] = True
        out.append(merged)
    return out


def living_due(jobs, now, torch=None, is_runnable=None):
    """THE CADENCE, as one pure function of (jobs, now) -- which is what makes every timer
    in this feature testable on a mock clock instead of a real sleep.

    Returns (due, baselined): the actions that should fire on this tick, and the STALENESS
    jobs whose last_run was unknown and has just been baselined to `now` (they do not fire;
    the caller persists the stamp so they fire sixty days from now instead of on the first
    tick of a fresh install).

    One job per tick, at most -- the list returns in shipped order and the caller takes the
    first it can actually start, because there is exactly one Panel job slot and a tick that
    tried to start four things would spawn one and silently drop three.

    `is_runnable` is the caller's PANEL_ACTIONS check (non-destructive, non-advanced, real
    key). It is a parameter and not a lookup so this stays importable and pure."""
    due, baselined = [], []
    stale_actions = {j["action"] for j in LIVING_STALE_JOBS}
    torch = _torch_present() if torch is None else torch
    for row in jobs or []:
        action = row.get("action")
        spec = LIVING_BY_ACTION.get(action)
        if not spec or not row.get("enabled"):
            continue
        if spec.get("needs") == "torch" and not torch:
            continue
        if action in stale_actions and row.get("last_run") in (None, ""):
            baselined.append(action)          # first sight: stamp, do not run
            continue
        if is_runnable is not None and not is_runnable(action):
            continue
        if (now - (row.get("last_run") or 0)) >= row.get("interval_s", 0):
            due.append(action)
    return due, baselined


# --- THE BLOW-UP RULE (owner's addition to the community scope, 2026-09-06) -------------
#
# The ask, verbatim: "if something BLOWS up can there be a trigger or metric for that?"
#
# What makes this answerable honestly rather than decoratively is that a raw view count
# cannot say it. 40 new views is enormous for a work that has sat at 3/day for a month and
# unremarkable for one pulling 200/day. So the rule compares a work's RECENT PACE against
# ITS OWN lifetime pace, and gates that ratio behind an absolute floor so a quiet work
# going from 1 view to 4 does not get to shout.
#
# THE SELF-READ SUBTRACTION is the part that keeps it from lying. PROBE_2026-09-06 measured
# that selecting `views` increments the counter for every artwork the query returns -- so
# two consecutive sweeps ALWAYS differ by at least one view that the sweep itself caused.
# Without SPIKE_SELF_READ every single work in the library shows a permanent +1 trickle,
# and any threshold low enough to be sensitive would fire on the owner's own looking.
#
# Every constant here is a judgement call, deliberately conservative, and meant to be
# tuned once the owner has watched it against a real week.
SPIKE_MIN_GAIN = 25            # real new views in the window, below which nothing is a spike
SPIKE_RATE_MULTIPLE = 3.0      # the window's pace must beat the work's lifetime pace by this
SPIKE_MIN_WINDOW_H = 1.0       # floor on the window, so a double-sync minutes apart can't divide by ~0
SPIKE_MIN_LIFETIME_H = 24.0    # floor on the work's age, so a day-old work has no absurd baseline
SPIKE_SELF_READ = 1            # views the sweep's own read added -- measured, not assumed


def views_spike(row):
    """Is this published work blowing up? -> a dict describing the spike, or None.

    Pure and side-effect free: it reads one catalog row's four view columns plus
    created_at and answers from those alone, so it unit-tests without a database and
    without a network. Callers decide what to do about a spike; this only names one.

    Returns None -- deliberately, and these are the cases that matter most:
      * never swept, or swept only ONCE (no `views_prev`). A first sweep has nothing to
        compare against and must announce nothing. This is the no-announce baseline case.
      * the window's real gain (after SPIKE_SELF_READ) is under SPIKE_MIN_GAIN.
      * the work's own lifetime pace is >= a third of the window's pace -- i.e. it is
        simply popular, not blowing up.
      * a counter that went DOWN or sideways (PixAI recount, a work re-published):
        clamped to zero gain, never a negative "spike".
      * an unusable window (no timestamps, or one that runs backwards) -- a spike is a
        claim about a RATE, and the denominator is never invented.
      * for the ratio test only, a creation date that will not parse: there is no
        lifetime to measure the window against.

    A PREVIOUS READING OF 0 IS A SPIKE, not a None (owner's call, 2026-09-06). Going from
    nothing to something is the plainest "a quiet picture suddenly found an audience" there
    is, and the rule used to decline it outright: a zero baseline gives the ratio nothing
    to divide by, and the guard read that as a reason for silence rather than as the ratio
    simply not applying. It now clears on the absolute floor alone -- SPIKE_MIN_GAIN is
    what keeps it honest at the bottom of the library -- and reports `multiple: None`,
    because there is no usual pace to be a multiple OF. Callers must not print a number
    there; spikeStore.js says "up from nothing" instead. A BLANK previous reading is
    unchanged and still silent: that is "never swept twice", not "swept and saw zero".
    """
    def _int(v):
        try:
            return int(str(v).strip() or "")
        except (TypeError, ValueError):
            return None

    now_v, prev_v = _int(row.get("views")), _int(row.get("views_prev"))
    if now_v is None or prev_v is None:
        return None                                  # never swept, or only once: silence
    gained = max(0, now_v - prev_v - SPIKE_SELF_READ)
    if gained < SPIKE_MIN_GAIN:
        return None

    t_now, t_prev = _series._series_ts(row.get("views_at")), _series._series_ts(row.get("views_prev_at"))
    if t_now is None or t_prev is None or t_now <= t_prev:
        return None                                  # unusable window; never guess one
    window_h = max(SPIKE_MIN_WINDOW_H, (t_now - t_prev) / 3600.0)
    rate = gained / window_h                         # real views per hour, this window

    t_made = _series._series_ts(row.get("created_at"))
    if prev_v <= 0:
        # THE BLOW-UP FROM ZERO. The floor above is the whole gate here: there is no pace
        # to beat, so the ratio test is skipped rather than failed, and `multiple` is None
        # because there is no usual pace to be a multiple of.
        baseline, multiple = 0.0, None
    else:
        if t_made is None:
            return None                              # no lifetime: nothing to compare to
        lifetime_h = max(SPIKE_MIN_LIFETIME_H, (t_prev - t_made) / 3600.0)
        baseline = prev_v / lifetime_h               # the work's own all-time views/hour
        if baseline <= 0 or rate < baseline * SPIKE_RATE_MULTIPLE:
            return None
        multiple = round(rate / baseline, 1)

    return {
        "media_id": row.get("media_id") or "",
        "artwork_id": row.get("artwork_id") or "",
        "title": (row.get("title") or "").strip(),
        "views": now_v,
        "gained": gained,
        "window_hours": round(window_h, 1),
        "rate_per_hour": round(rate, 2),
        "baseline_per_hour": round(baseline, 3),
        "multiple": multiple,
    }


def top_published_rows(db_path, limit=12, order="likes"):
    """The owner's top published artworks -> rows with artwork_id + engagement + views.

    `order` is "likes" (the historical default) or "views". Views are now a CATALOG
    column filled by --sync-artworks, not twelve live calls made while the panel opens;
    a library that has never been swept simply reads views=0 with views_at blank, which
    is what lets the panel say "not swept yet" instead of drawing a bar of zeroes."""
    from moonglade.catalog import catalog
    col = "views" if order == "views" else "likes"
    with catalog(db_path) as con:
        try:
            rows = con.execute(
                "SELECT media_id, artwork_id, title, prompt_preview, aes_score, created_at, "
                "CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) AS likes, "
                "CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER) AS comments, "
                "CAST(COALESCE(NULLIF(views,''),'0') AS INTEGER) AS views, "
                "views AS views_raw, views_prev, views_at, views_prev_at "
                "FROM catalog WHERE is_published = '1' AND COALESCE(artwork_id,'') != '' "
                "ORDER BY {} DESC, likes DESC, comments DESC LIMIT ?".format(col),
                (int(limit),)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []


def published_totals(db_path):
    """At-a-glance totals across ALL the owner's published artworks (from --sync-artworks).

    `views` here is the real LIFETIME total across the whole published library -- the
    thing the panel could not show while views were fetched live for a top twelve. It
    sums only rows that have actually been swept; `views_rows` says how many that was,
    so a partially-swept library reports an honest subtotal rather than a total that
    silently counts blanks as zero.

    ONE ROW PER ARTWORK, and that is not a nicety. An ANIMATED artwork is two catalog
    rows -- the poster keyed by `mediaId` and the mp4 keyed by `videoMediaId` -- and both
    the sync and the sweep write the SAME artwork_id, likes, comments and views onto both
    on purpose (#20: the Animations tab needs the mp4 row tagged). Summing every published
    row therefore doubled the count, the likes, the comments and the headline lifetime
    views for every animation in the library. The dedup key is the artwork_id; a published
    row that has never been merged has none, so it keys on its own media_id and still
    counts exactly once rather than folding every unmerged row under one blank key.

    Which of an animation's two rows represents it does not matter here -- they carry the
    same PixAI-owned numbers by construction -- so the lowest rowid is representative
    enough. published_spikes, which shows a media_id to the owner, is fussier."""
    from moonglade.catalog import catalog
    with catalog(db_path) as con:
        try:
            r = con.execute(
                "SELECT COUNT(*) AS c, "
                "COALESCE(SUM(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),0) AS likes, "
                "COALESCE(SUM(CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER)),0) AS comments, "
                "COALESCE(SUM(CASE WHEN COALESCE(views,'') != '' "
                "                  THEN CAST(views AS INTEGER) ELSE 0 END),0) AS views, "
                "COALESCE(SUM(CASE WHEN COALESCE(views,'') != '' THEN 1 ELSE 0 END),0) AS views_rows, "
                "MAX(COALESCE(views_at,'')) AS views_at "
                "FROM catalog WHERE is_published = '1' AND rowid IN ("
                "  SELECT MIN(rowid) FROM catalog WHERE is_published = '1' "
                "  GROUP BY CASE WHEN COALESCE(artwork_id,'') = '' "
                "                THEN 'mid:' || media_id ELSE 'aid:' || artwork_id END)"
            ).fetchone()
            return {"count": int(r[0] or 0), "likes": int(r[1] or 0), "comments": int(r[2] or 0),
                    "views": int(r[3] or 0), "views_rows": int(r[4] or 0),
                    "views_at": r[5] or ""}
        except sqlite3.Error:
            return {"count": 0, "likes": 0, "comments": 0,
                    "views": 0, "views_rows": 0, "views_at": ""}


def published_spikes(db_path, limit=5):
    """Every published work that views_spike() calls a blow-up, hottest first.

    A pure catalog read over the swept rows -- no network, no live call. Capped because
    this feeds a corner note, not a feed: the owner asked to be TOLD when something takes
    off, and a note naming twenty works tells him nothing.

    ONE SLOT PER ARTWORK. An animation is two rows carrying the same numbers (see
    published_totals), so both spiked identically and ONE work could fill a two-slot note
    twice while a genuinely different spiking work never appeared at all. The poster row
    wins the slot over the mp4 -- the note names a picture, and the still is what the
    owner recognises. A row that has never been merged has no artwork_id and keys on its
    own media_id, so it is never folded in with any other."""
    from moonglade.catalog import catalog
    with catalog(db_path) as con:
        try:
            rows = con.execute(
                "SELECT media_id, artwork_id, title, created_at, views, views_prev, "
                "views_at, views_prev_at, is_video FROM catalog "
                "WHERE is_published = '1' AND COALESCE(views_prev,'') != '' "
                "ORDER BY CASE WHEN COALESCE(is_video,'') = '1' THEN 1 ELSE 0 END, "
                "         rowid").fetchall()
        except sqlite3.Error:
            return []
    seen, hits = set(), []
    for r in rows:
        row = dict(r)
        key = "aid:" + str(row.get("artwork_id") or "") if row.get("artwork_id") \
            else "mid:" + str(row.get("media_id") or "")
        if key in seen:
            continue                                 # the same work's other row
        seen.add(key)
        s = views_spike(row)
        if s:
            hits.append(s)
    # A blow-up from ZERO has no multiple to rank by -- and is the most dramatic thing on
    # the list, so it sorts to the top rather than to the bottom of a None comparison.
    hits.sort(key=lambda s: (float("inf") if s["multiple"] is None else s["multiple"],
                             s["gained"]), reverse=True)
    return hits[:int(limit)]

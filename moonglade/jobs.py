"""
moonglade/jobs.py
=================
The job log behind the web Jobs card: jobs.jsonl, append-only, written by the server, panel
subprocesses and the command line, replayed and collapsed by job id on read, swept of orphans
and compacted. Moved verbatim out of moonglade/backup.py in the 3.21.0 split (phase 2).

The two names it needs from the engine (the Windows-safe atomic replace and the host-path
redaction backup re-exports from the gallery) are imported from moonglade.backup inside each
function that uses them, never at the top, so importing this module never imports the engine.
"""
import json
import os
import threading
import time

from moonglade import paths as _paths


# ---------------------------------------------------------------------------
# Job log: an APPEND-ONLY activity registry that the web "Jobs" card reads.
# Several processes write it -- the Flask server, panel subprocesses, and the
# CLI run straight from a terminal -- so every writer just opens in "a" mode
# and appends ONE json line recording a job's current state. Readers replay the
# tail and collapse by job_id (last event wins; a terminal done/failed never
# reverts to running). Append-only sidesteps the read-modify-write races a
# single mutated JSON blob would have across processes. It doubles as a plain
# debug dump -- open jobs.jsonl and read it. Consumed by moonglade/gallery.py.
# ---------------------------------------------------------------------------
JOBS_LOG_NAME = "jobs.jsonl"
JOBS_KEEP = 50                 # show at most this many most-recent jobs
JOBS_MAX_AGE = 24 * 3600       # drop FINISHED jobs older than this (seconds)
_JOBS_TERMINAL = ("done", "failed", "done_with_errors")
_JOBS_COMPACT_AT = 2000        # rewrite the raw log once it passes this many lines

# How stale a 'running' job has to be before the ongoing /api/jobs reconciliation
# sweep (resolve_orphan_jobs, called with min_age=this from moonglade/gallery.py's
# api_jobs()) will re-ask PixAI for its real status. This is a *different* clock
# from --poll-timeout: --poll-timeout (300s generate / 600s video, see argparse
# defaults) bounds how long the CLI waits on ONE task it's actively watching --
# it's "the task itself timed out". This bounds something else: "the client
# stopped watching" (a closed tab, a dead Generate card, a crashed browser) while
# the task itself may still be legitimately in flight. Picking --poll-timeout's
# own 300s here would false-flag any real generation slower than 5 minutes --
# ordinary for video -- as an orphan on every single /api/jobs poll (the web
# generate path never re-stamps a running job's `ts` past its initial submit
# event, so nothing else naturally resets that clock). 1800s (30 minutes) is
# comfortably past every known real generation time (routine within minutes;
# --poll-timeout only waits up to 600s even for video) while still surfacing a
# genuine orphan same-day, far short of JOBS_MAX_AGE's 24h silent drop-from-view.
JOBS_ORPHAN_SWEEP_AGE = 30 * 60

# Serializes the ONE non-append writer of jobs.jsonl (maybe_compact_jobs' whole-file
# rewrite) against every other thread in this process, exactly like _accounts_lock does
# for AUTH_USERS and for the same reproduced reason: moonglade/gallery.py runs
# threaded=True, so two /api/jobs polls (two tabs, or the gallery plus the Loom) can both
# see the log cross _JOBS_COMPACT_AT and start rewriting it at the same moment. Appends
# don't need this -- they're one "a"-mode line and safe across processes by design.
_jobs_compact_lock = threading.Lock()


def _jobs_path(out_dir):
    return _paths.records_path(out_dir, JOBS_LOG_NAME)


def append_job_event(out_dir, job_id, status=None, **fields):
    """Append ONE job event to jobs.jsonl (append-only; safe from many processes).
    Each call records a job's CURRENT state; readers collapse by job_id. Known
    fields: type, label, done, total, media_ids, error, source, dismissed, count
    (requested image count, image-gen registrations only). `ts` is stamped here.
    Fails soft -- logging a job must never break the job.

    Every STRING field is capped at 200 chars here, at the one write choke point
    every job event from every source funnels through (web routes' own _log_job
    wrapper, the Panel's subprocess reader, the CLI's own job logging). Found
    2026-07-21: _cli_job_finish wrote a caught exception's str(e) here with NO cap
    at all -- the only error-write in either module missing one -- fed by blanket
    `except Exception` wrappers around whole download/sync runs, so an unbounded
    message (a long traceback, an arbitrarily large error string) could land here
    verbatim and later get served back to any LOGIN caller via /api/jobs. 200
    matches the str(e)[:200] convention already used at every other error-serving
    site in this app, rather than inventing a new limit.

    This bounds SIZE, not CONTENT -- a short message can still contain a host path
    (`C:\\Users\\...` easily fits in 200 chars). Redacting host detail out of error
    text generally is a separate, larger, deliberately deferred piece of work (see
    the 2026-07-21 audit, S3) -- a first attempt at that used a regex that
    stopped redacting at the first space, silently leaving a spaced username
    exposed, which is exactly the kind of narrow-looking fix that is easy to get
    subtly wrong. This closes the "totally unbounded" half safely tonight without
    reopening that harder problem."""
    if not job_id:
        return
    rec = {"ts": time.time(), "job_id": str(job_id)}
    if status is not None:
        rec["status"] = status
    for k, v in fields.items():
        if v is None:
            continue
        rec[k] = v[:200] if isinstance(v, str) else v
    try:
        with _jobs_path(out_dir).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI-side job logging: gives a command run straight from a terminal
# (python -m moonglade --sync / --update / --generate / ...) the SAME
# jobs.jsonl activity trail a panel-spawned subprocess already gets from
# moonglade/gallery.py's _panel_run/_panel_reader (job_id "panel-<uuid>") and
# delete_tasks_bulk (job_id "bulkdel-<uuid>") -- this is the "cli-<uuid>" flavor.
# Deliberately a no-op under the Control Panel itself (MOONGLADE_PROGRESS=1): the
# panel already logs its OWN "panel-<uuid>" job for that exact subprocess, so
# creating a second "cli-<uuid>" job here would just double the Jobs card entry
# for one real run. Every call is fail-soft -- a logging problem must NEVER
# crash, block, or change the outcome of the real command.
# ---------------------------------------------------------------------------

def _cli_job_start(out_dir, label):
    """Start a 'cli-<uuid>' job for a bare-terminal run. Returns the job_id, or None
    when under the panel (see module note above) or if logging itself fails."""
    if os.environ.get("MOONGLADE_PROGRESS") == "1":
        return None
    try:
        import uuid
        job_id = "cli-" + uuid.uuid4().hex[:12]
        append_job_event(out_dir, job_id, status="running", type="cli", label=label)
        return job_id
    except Exception:                                       # noqa: BLE001 -- fail-soft logging
        return None


def _cli_job_finish(out_dir, job_id, error=None, warn=0, warn_detail=None):
    """Terminal event for a _cli_job_start job. No-op if no job was started.

    `warn` (D-4): a partial-failure count from a run that otherwise completed (some
    files failed to download after retries, but the run itself didn't raise). Logged
    as its own terminal status, "done_with_errors", distinct from both "done" (clean)
    and "failed" (the run itself raised) -- so a scheduled/automated caller, or the
    Panel's Jobs tray, can tell "ran but lost files" apart from either extreme instead
    of everything but a hard crash collapsing into a silent "done".

    `warn_detail` (B15): overrides the default "file(s) failed to download" noun
    phrase for a caller whose `warn` count isn't about downloaded files -- e.g.
    run_sync_artworks, where it can mean a page fetch that failed mid-pagination or
    a failed video download. The done_with_errors status/marker mechanism itself is
    unchanged; only the human-readable detail text differs."""
    if not job_id:
        return
    try:
        from moonglade.redact import _redact_host_paths_cli
        if error is not None:
            append_job_event(out_dir, job_id, status="failed",
                             error=_redact_host_paths_cli(out_dir, str(error))[:200])
        elif warn:
            detail = warn_detail or "file(s) failed to download"
            append_job_event(out_dir, job_id, status="done_with_errors",
                             error="{} {}".format(warn, detail))
        else:
            append_job_event(out_dir, job_id, status="done")
    except Exception:                                       # noqa: BLE001 -- fail-soft logging
        pass


def _reconstruct_jobs(out_dir):
    """Replay the whole log, collapsing by job_id. Returns (jobs_by_id, first_seen_order,
    raw_line_count). A terminal (done/failed) job is sticky: a later non-terminal event (a
    stale/interleaved heartbeat) can neither revert its status nor inject progress fields
    onto it -- only an explicit dismiss is honored once a job has finished.

    `started_at` (owner field-report 2026-07-23: two stuck generations, no way to recover
    their task id without server access) -- the FIRST event's `ts` is the job's true
    registration time, but every later event's `cur.update(rec)` used to blindly overwrite
    `ts` with its own, so by the time a job reached a terminal state the original start
    time was gone, and "time spent" was not reconstructable client-side. Stamped here, once,
    off the first event seen for a job_id, and never touched again by later merges (later
    events don't carry their own `started_at` key, so `cur.update(rec)` can't clobber it).
    `rec.setdefault` (not a plain assignment) also makes this correct across compaction: a
    compacted log's single surviving line for a job already HAS a real `started_at` baked
    in from a prior reconstruction, and re-deriving it from that line's own `ts` (the last
    known event, not the true start) would be wrong -- setdefault leaves an already-present
    value alone."""
    jobs, order, n = {}, [], 0
    try:
        with _jobs_path(out_dir).open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                n += 1
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                jid = rec.get("job_id")
                if not jid:
                    continue
                cur = jobs.get(jid)
                if cur is None:
                    rec.setdefault("started_at", rec.get("ts"))
                    jobs[jid] = rec
                    order.append(jid)
                elif cur.get("status") in _JOBS_TERMINAL and rec.get("status") not in _JOBS_TERMINAL:
                    # finished job + a stale heartbeat: ignore all of it EXCEPT an explicit
                    # dismiss (which is exactly how a done/failed job gets cleared).
                    if "dismissed" in rec:
                        cur["dismissed"] = rec["dismissed"]
                else:
                    cur.update(rec)
    except OSError:
        return {}, [], 0
    return jobs, order, n


def _job_expired(job, now, max_age):
    """A job is expired once there's been no activity (its last event's ts) for max_age.
    This applies to RUNNING jobs too: a 'running' entry with no heartbeat for a full day is
    a zombie (the tab closed, or a blip hit before the done poll) -- ageing it out keeps the
    card honest and stops orphaned entries leaking into the log forever."""
    return bool(max_age) and (now - float(job.get("ts") or 0)) > max_age


def _select_jobs(jobs, order, now, keep, max_age):
    """The single canonical selection used by BOTH read_jobs and maybe_compact_jobs, so the
    card and the on-disk compaction can never disagree about which jobs survive. Drops
    dismissed + expired; keeps ALL surviving running jobs (never capped away mid-flight);
    caps only the FINISHED history to `keep`. Returns newest-first; ties break by first-seen
    order (stable), which is identical at both call sites."""
    live, done = [], []
    for jid in order:                       # order = first-seen -> a stable, shared tiebreak
        j = jobs[jid]
        if j.get("dismissed") or _job_expired(j, now, max_age):
            continue
        (live if j.get("status") not in _JOBS_TERMINAL else done).append(j)
    live.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    done.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    if keep:
        done = done[:keep]                  # cap the finished history only, never running
    merged = live + done
    merged.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    return merged


def read_jobs(out_dir, keep=JOBS_KEEP, max_age=JOBS_MAX_AGE, now=None):
    """Current job list for the web card: newest-first, collapsed by job_id, dismissed
    removed, stale jobs aged out, finished history capped to keep (running never capped).
    Each job carries both `ts` (its most recent event) and `started_at` (its registration
    event -- see `_reconstruct_jobs`), so a caller can compute elapsed time for a running
    job (now - started_at) or a finished one (ts - started_at) without a backend change."""
    jobs, order, _n = _reconstruct_jobs(out_dir)
    if not jobs:
        return []
    return _select_jobs(jobs, order, time.time() if now is None else now, keep, max_age)


def resolve_orphan_jobs(out_dir, status_fn, min_age=0, now=None):
    """Resolve jobs stuck at 'running' by asking `status_fn(task_id)` for their true state
    and appending a terminal event when it has finished. Only PixAI-task-keyed generate
    jobs (job_id is the numeric task id) are checked -- panel/delete jobs are local and
    self-report. `status_fn` returns 'running' | 'done' | 'failed' (a raised exception on
    one job is skipped, not fatal). Fixes jobs orphaned when a Generate card was closed
    before its poll resolved. Returns the number of jobs resolved to a terminal state.

    `min_age` (seconds, default 0): skip jobs whose last event is younger than this --
    don't even call `status_fn`. 0 means "ask about every non-terminal generate job right
    now", which is what the ONE-SHOT call at live-mirror watcher startup wants (catch
    anything left stuck from a prior server session, immediately). A real `min_age`
    (JOBS_ORPHAN_SWEEP_AGE) is for the ONGOING reconciliation sweep api_jobs() runs on
    every poll -- see that constant's comment for why 300s/--poll-timeout is the wrong
    number to reuse here.

    Two behaviors below are gated on `min_age` being truthy, so the min_age=0 (startup)
    call keeps its exact original behavior -- unchanged from before this parameter
    existed, still exactly what every pre-existing test pins:

    - A `status_fn` call that comes back genuinely still 'running' for an aged-in job
      writes a lightweight 'running' heartbeat, refreshing that job's `ts`. This is the
      only RECURRING writer for a web-submitted generate job: api_task_status()'s own
      'running' branch writes at most twice per job (once when it first sees it queued,
      once when a worker starts it -- the queue/render phase the Activity tray renders),
      deliberately de-duped so it can never become a per-poll heartbeat. So without this,
      once a job crosses min_age it would get re-asked on literally every subsequent
      /api/jobs poll for as long as it keeps genuinely running -- a real video generation
      easily outlives 30 minutes. The heartbeat resets the min_age clock, so a
      still-genuinely-running job is only re-checked once per min_age, not once per poll.
    - A `status_fn` call that RAISES for an aged-in job is recorded as 'stale' -- a
      distinct, visible, non-terminal status meaning "still stuck, and we couldn't reach
      PixAI to find out why" -- instead of silently left untouched. Un-gated (min_age=0),
      a single transient blip on a job that's merely SECONDS old would immediately get
      branded 'stale', which is wrong -- that's exactly the "transient blip" case
      api_task_status()'s own except-clause deliberately declines to treat as terminal.
      Gating on min_age means only a job that has ALREADY been stuck a while, and is now
      ALSO unreachable, gets the marker."""
    resolved = 0
    now = time.time() if now is None else now
    for j in read_jobs(out_dir):
        if j.get("status") in _JOBS_TERMINAL:
            continue
        jid = str(j.get("job_id") or "")
        if j.get("type") != "generate" or not jid.isdigit():
            continue
        if min_age and (now - float(j.get("ts") or 0)) < min_age:
            continue
        try:
            phase = status_fn(jid)
        except Exception:                          # noqa: BLE001 -- one bad lookup must not stop the rest
            if min_age:
                append_job_event(out_dir, jid, status="stale",
                                 error="couldn't reach PixAI to verify this job's real status")
            continue
        started = None
        if isinstance(phase, dict):
            # Tolerate a caller handing us generation_status()'s whole
            # {status, phase, paid_credit} dict rather than the phase string. A real
            # caller did exactly that and this loop silently matched nothing for every
            # job, every time. Raising instead would not have helped -- the per-job
            # `except Exception` above swallows errors by design, so a contract
            # violation here is INVISIBLE rather than loud. Accepting both shapes is
            # what actually makes that failure mode impossible.
            started = phase.get("started")
            phase = phase.get("phase")
        if phase in _JOBS_TERMINAL:
            append_job_event(out_dir, jid, status=phase,
                             error=("task " + phase if phase == "failed" else None))
            resolved += 1
        elif started is False:
            # A task PixAI accepted, queued, and never assigned a worker. It stays
            # NON-TERMINAL for ~60 minutes before being reaped, so the branch above never
            # fires and the heartbeat below would keep the card spinning as though work
            # were happening -- which is exactly how five of the owner's generations died
            # unnoticed between 2026-07-21 and 07-24 (all `cancelled`, all
            # outputs.reason="waiting timeout", none ever dispatched).
            #
            # `stale` is reused rather than inventing a state: it already renders a warning
            # glyph + message in the tracker, and it is deliberately NOT in _JOBS_TERMINAL,
            # so if PixAI does eventually start the task a later done/failed still wins.
            # Tested `started is False`, never `not started`: a caller that omits the field
            # reports None, and "unknown" must not brand every in-flight job stale.
            append_job_event(out_dir, jid, status="stale",
                             error="PixAI accepted this job but has not started it -- no "
                                   "worker has picked it up. Unstarted tasks are cancelled "
                                   "and refunded at about 60 minutes.")
        elif min_age:
            append_job_event(out_dir, jid, status="running")   # refresh ts; see docstring
    return resolved


# Job-id prefixes for work the SERVER PROCESS itself owns -- it spawns these and nothing else
# will ever report them finished. Deliberately EXCLUDES "cli-": a CLI job belongs to a separate
# process with its own lifetime that the server knows nothing about, so sweeping one would mark a
# genuinely-running terminal command as dead. Numeric ids are PixAI generate tasks and belong to
# resolve_orphan_jobs() instead. "integrity-" is the Broken files list's fix run (a thread in
# the server, moonglade.integrity.FixRunner).
_JOBS_SERVER_OWNED_PREFIXES = ("panel-", "import-", "bulkdel-", "integrity-")


def resolve_interrupted_local_jobs(out_dir, now=None):
    """Mark server-owned jobs left non-terminal by a previous process as failed. Returns the count.

    Call this ONCE at server startup. The rule needs no age heuristic and no clock comparison,
    which is what makes it reliable: at the moment the server boots it has not yet created any
    job of its own, so every server-owned job still sitting at a non-terminal status necessarily
    belongs to a process that is gone. There is nothing left to ask, and nothing will ever arrive.

    This closes a real gap. resolve_orphan_jobs() reaps only PixAI-task-keyed generate jobs -- its
    docstring notes that panel/delete jobs "are local and self-report", which is true right up
    until the process is killed. Then the terminal event is simply never written, and the Job
    Tracker shows "running" forever. Owner's production case (2026-07-26): `panel-3d49d9bffea2`,
    a Similar-index rebuild killed by a machine-wide memory exhaustion, still displaying as
    running after the reboot. The silent-death detection shipped 2026-07-25 does not cover this
    class at all, because it is built around asking PixAI about a task id that these jobs do not
    have.

    Uses the existing "failed" status and an `error` message rather than inventing an
    "interrupted" state: failed is already terminal, already rendered by the tracker, and already
    carries a message -- and the job did, in fact, fail. A new status would need matching UI in
    mg-notify.js and a new entry in _JOBS_TERMINAL for no gain.

    ONE known imprecision, stated rather than hidden: a panel job runs as a SUBPROCESS, so if the
    server is restarted while one is genuinely still running, this marks it failed early. That
    self-corrects -- _reconstruct_jobs() only blocks a NON-terminal record from overwriting a
    terminal one, so the subprocess's own later "done" still lands (verified at the
    `cur.get("status") in _JOBS_TERMINAL` branch). Recording the owning pid on each event would
    remove the imprecision entirely; it is not worth the extra surface for a case that resolves
    itself."""
    n = 0
    for j in read_jobs(out_dir, now=now):
        if j.get("status") in _JOBS_TERMINAL:
            continue
        jid = str(j.get("job_id") or "")
        if not jid.startswith(_JOBS_SERVER_OWNED_PREFIXES):
            continue
        append_job_event(
            out_dir, jid, status="failed",
            error="Interrupted -- the app stopped before this finished. Nothing was corrupted; "
                  "run it again when you're ready.")
        n += 1
    return n


def maybe_compact_jobs(out_dir, keep=JOBS_KEEP, max_age=JOBS_MAX_AGE):
    """Opportunistically rewrite jobs.jsonl down to exactly the records _select_jobs keeps,
    so the append-only log can't grow without bound. Only fires once the raw file passes
    _JOBS_COMPACT_AT lines. Uses the SAME selection as read_jobs, so compaction can never
    delete a job the card is currently showing, nor drop an in-flight running job. A
    concurrent append from another process during the rewrite could be lost -- acceptable
    for a display/paper-trail log, and rare (compaction only). Called by the web reader."""
    from moonglade.backup import _atomic_replace
    # Whole thing under _jobs_compact_lock: the count check and the rewrite have to be one
    # step, or two concurrent pollers both pass the threshold test and rewrite together. The
    # scratch file is pid-stamped like _save_config's for the cross-PROCESS half of the same
    # race -- a panel subprocess compacting at the same instant would otherwise be writing
    # into the very file this one is about to rename, truncating the log to a hybrid.
    with _jobs_compact_lock:
        jobs, order, n = _reconstruct_jobs(out_dir)
        if n <= _JOBS_COMPACT_AT:
            return
        kept = _select_jobs(jobs, order, time.time(), keep, max_age)
        kept.reverse()                      # write oldest-first so append order stays chronological
        path = _jobs_path(out_dir)
        tmp = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                for j in kept:
                    fh.write(json.dumps(j, separators=(",", ":")) + "\n")
            _atomic_replace(tmp, path)      # transient Windows sharing violation != lost compaction
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

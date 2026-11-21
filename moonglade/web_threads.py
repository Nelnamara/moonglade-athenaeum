"""moonglade/web_threads.py -- the gallery's background work: the Control Panel's job runner
(PANEL_ACTIONS, the one job slot and its lock, the log reader), the job log, the schedule and the
living library's timers with the scheduler thread, the release check, the contest-win and Mirror
renewal ticks, the watch (the live task stream, the catch-up, the mirror of finished generations,
the single-flight collect, the orphan-job reconcile) with its thread and the contest and artworks
startup syncs, the asset container's fetch job and the Loom export job's state.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was, so every thread starts exactly when it did, once,
behind its MOONGLADE_DISABLE_* switch. Names the block reads from create_app's setup and the front
door come in through ctx (the bound-from-ctx lines below), and the names other code reads back go
out through ctx (the provided-to-ctx lines at the end), so every closure on both sides holds the
one same object: the job slot, the locks, the schedule state, the single-flight guards and the
job log. gallery's own names are imported inside the function that reads them, at call time, so a
test's patch of moonglade.gallery still reaches the thread.
"""
import json
import os
import sys
import threading
import time

from flask import jsonify

from moonglade import assets as moonglade_assets
from moonglade import branding as _branding
from moonglade import contest_sync as _contest_sync
from moonglade import gen_road as _gen_road
from moonglade import jobs as _jobs
from moonglade import living as _living
from moonglade import mirror as _mirror
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import task_feed as _task_feed
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import updater as _updater


def register(app, ctx):
    # -- bound from ctx (split_move) --
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    # ------------------------------------------------------------------
    # Control Panel: run maintenance CLI ops as background jobs with live
    # logs. Each action is a WHITELISTED argv against the CLI, `python -m moonglade`
    # (never an arbitrary command); destructive ones require confirm=True.
    # One job at a time. Localhost-gated at the routes. Runs the CLI as a
    # subprocess (isolation from the Flask process + natural stdout capture, so
    # the unmodified CLI script's own print output streams straight to the
    # Jobs card) with cwd = the checkout dir (where config.json lives).
    # ------------------------------------------------------------------
    # The CLI is the package's module (3.20), run from the app's folder: `-m` finds the
    # package through the working directory, and config.json lives there.
    _cli_module = ["-m", "moonglade"]
    _cli_dir = str(_paths.APP_ROOT)

    # The asset container's first-run fetch (2026-08-10, moonglade-internal/DECISIONS.md "The
    # asset container, re-scoped from scratch"). A real streamed-download job,
    # not a subprocess like PANEL_ACTIONS below -- one instance per server
    # process, single-flight (AssetFetchJob.start() itself), deliberately
    # UI-agnostic: the Setup Wizard drives it as a phase; a standalone boot
    # check can drive the identical endpoints for a past-wizard install
    # missing the container. _container_path() is a module-level function
    # (defined above, beside branding_root()) so this binds the real, current
    # app root -- not a value frozen at import time.
    _asset_job = moonglade_assets.AssetFetchJob(_branding._container_path())

    _panel_lock = threading.Lock()
    _panel_job = {"status": "idle", "action": "", "label": "", "lines": [],
                  "rc": None, "started_at": None, "progress": None,
                  "proc": None, "cancelled": False, "warn_count": 0}
    # Test seam, same rationale as app.extensions["mg_watch_catchup"] below: the job slot
    # is a closure, so every refusal that depends on it -- Restart's, and now the
    # updater's -- has no other way to be driven end to end. Exposes the STATE, not a
    # setter: a test occupies the slot exactly as _panel_run does, by marking it running.
    app.extensions["mg_panel_job"] = _panel_job
    _PROG_PREFIX = "~=MGPROG=~"        # matches PANEL_PROGRESS_PREFIX in moonglade/backup.py
    _WARN_PREFIX = "~=MGWARN=~"        # matches PANEL_WARN_PREFIX in moonglade/backup.py (D-4)
    # The Loom's ffmpeg export job (trim + concat finished shots -> one mp4).
    _export_lock = threading.Lock()
    # `warning` is distinct from `error`: the export SUCCEEDS but came out different from what
    # was asked for (today: no audio track, because a missing ffprobe made every clip's length
    # unreadable). That has to reach the owner's screen, not just the log -- a silent downgrade
    # on a missing dependency is how someone ships a silent cut without ever learning why.
    _export_job = {"status": "idle", "progress": 0, "elapsed": 0.0,
                   "out": "", "error": "", "warning": "", "proc": None, "cancelled": False}
    _export_dir = _paths.loom_root(out_dir) / "exports"
    # action -> {args (extra flags), label, destructive}
    # action -> {args, label, destructive, panel_visible}. panel_visible=False actions
    # are still valid for /api/panel/run and the scheduler dropdown, but don't render as
    # a Maintenance button -- they're full-feed-scan jobs meant to run periodically in
    # the background, not be clicked after every pull. --sync itself now folds
    # fix-models + backfill-full-meta internally (see the CLI's --sync handler), so
    # those two are gone as standalone actions entirely.
    PANEL_ACTIONS = {
        "sync":          {"args": ["--sync"], "label": "Sync now — pull new + fill metadata", "destructive": False},
        "stats":         {"args": ["--catalog-stats"], "label": "Catalog stats", "destructive": False},
        "audit":         {"args": ["--audit"], "label": "Duplicate audit (read-only)", "destructive": False},
        # The "full audit" checkbox in the UI does NOT append a flag to the action above --
        # it selects this separate whitelisted entry. Same for dedup-delete below. Keeping
        # the client to a fixed set of action KEYS is what preserves the property the
        # whole runner is built on (see _panel_run: "a WHITELISTED argv, never an
        # arbitrary command"); letting a checkbox contribute argv would erode it.
        "audit-full":    {"args": ["--audit"], "label": "Duplicate audit (full — byte-compare, slower)", "destructive": False},
        "verify-dupes":  {"args": ["--verify-dupes"],
                          "label": "Verify _duplicates/ is safe to delete", "destructive": False},
        # The integrity pass (moonglade/integrity.py): read-only, it writes only its own two
        # report files. A deliberate click runs the quick tier AND the structural checks
        # (scope 2+3, owner question 2's recommendation); Health's tiles read the result.
        "verify-library": {"args": ["--verify-library", "--verify-deep"],
                           "label": "Verify library integrity (read-only)", "destructive": False},
        # Listed BEFORE rebuild so the non-destructive, usually-correct action reads first.
        # "Rebuild" drops the table and re-embeds everything; this adds only what is missing and
        # cannot lose existing rows. After an interrupted build the top-up resumes -- reaching for
        # rebuild there costs ~3x the time AND discards every row that survived.
        "sync-similar":  {"args": ["--sync-similar"],
                          "label": "Top up the Similar index (adds only what's missing; "
                                   "heavy: don't run it beside GPU- or RAM-heavy programs)",
                          "destructive": False},
        "rebuild-similar": {"args": ["--rebuild-similar"],
                            "label": "Rebuild the Similar index (slow, needs pixeltable; "
                                     "heavy: don't run it beside GPU- or RAM-heavy programs)",
                            "destructive": False},
        # Same trust class as sync-similar/rebuild-similar just above: computes and writes
        # a catalog column only (phash), no image files touched, so not destructive despite
        # being a real disk-scanning/CPU pass. Feeds the near_duplicate tier of
        # GET /api/duplicates (near_duplicate_groups(), this module).
        "backfill-phash": {"args": ["--backfill-phash"],
                           "label": "Backfill perceptual hashes (near-duplicate detection)",
                           "destructive": False},
        # --- Advanced sync (web parity step 2): the sync variants the bare "Sync now"
        # (an INCREMENTAL --sync, i.e. --update --full-meta) can't do. Each is its own
        # whitelisted KEY, exactly like audit-full/dedup-delete -- never argv the client
        # assembles. `advanced: True` routes them to the Panel's own "Advanced" section and
        # keeps them OUT of the scheduler dropdown (a full re-walk on a timer is a foot-gun,
        # and test-pull's N has no home there). All three are read/append, never destructive.
        "resync-full":   {"args": ["--full-meta"],
                          "label": "Full re-walk — re-pull ALL history + metadata (non-incremental)",
                          "destructive": False, "advanced": True},
        "inventory":     {"args": ["--count"],
                          "label": "Inventory count — tally account vs. backup (read-only, no download)",
                          "destructive": False, "advanced": True},
        # The ONLY parameterised action. `int_param` means _panel_run appends a single
        # server-validated, clamped integer (the N for --max) -- not an arbitrary string,
        # the same discipline as the scheduler's interval_hours. int_range bounds it.
        "test-pull":     {"args": ["--max"], "int_param": True, "int_range": (1, 200),
                          "int_default": 20,
                          "label": "Test pull — fetch the N most-recent tasks",
                          "destructive": False, "advanced": True},
        # (Export CSV isn't here on purpose -- in the browser it's a real DOWNLOAD via /export-csv,
        #  not a subprocess that writes catalog.csv into the backup folder.)
        "organize-dry":  {"args": ["--organize", "--dry-run"], "label": "Organize — preview (dry run)", "destructive": False},
        "dedup-dry":     {"args": ["--dedup"], "label": "Dedup — preview (dry run)", "destructive": False},
        # --- full-feed scans: they re-walk the WHOLE history every run, with no
        # --update-style short-circuit. That is why they were originally scheduler-only.
        # They now HAVE buttons (web parity: nothing should need the CLI), but the labels
        # say "full re-walk" out loud so the cost is visible before clicking rather than
        # discovered afterwards. ---
        # A SCHEDULED RUN OF THIS ONE DOES NOT READ VIEW COUNTS (owner's call,
        # 2026-09-06). Asking PixAI how many views a work has ADDS ONE to that number, for
        # every published work the sweep returns -- so an unattended refresh on a timer is
        # a daily +1 across the whole library, forever, that nobody asked for. `scheduled_args`
        # is what splits the two cases without splitting the action: a Run now click is the
        # owner asking by hand and still reads views; every automatic start (the living
        # library's list, the legacy standing order, a follow-on in a `then` chain) appends
        # --no-views. The counts have their own weekly job instead -- see
        # "sync-artwork-views" below and LIVING_JOBS.
        "sync-artworks":     {"args": ["--sync-artworks"],
                              "scheduled_args": ["--no-views"],
                              "label": "Sync published-artwork metadata (full re-walk)",
                              "destructive": False},
        # The view read on its own timer, and nothing else: no listing re-walk, just the
        # counts. Its own key rather than a flag the client can add, the same discipline
        # audit-full and dedup-delete follow. No Panel button (panel_visible False) -- it
        # is a "Runs itself" row with its own Run now, and a second button for the same
        # work in the manual grid would invite running it twice.
        "sync-artwork-views": {"args": ["--sync-artworks", "--views-only"],
                               "label": "View counts — read how many views your published "
                                        "works have (adds one view to each)",
                               "destructive": False, "panel_visible": False},
        "sync-videos":       {"args": ["--sync-videos"],
                              "label": "Sync i2v videos — back up mp4s (full re-walk)",
                              "destructive": False},
        # reconcile-deleted deliberately keeps NO button: --sync already runs it as its
        # final step (see run_sync's pipeline), so a button would be a second path to
        # work that just happened, inviting someone to run it and wonder why nothing
        # changed. It stays schedulable for anyone who wants it on its own cadence.
        "reconcile-deleted": {"args": ["--reconcile-deleted"], "label": "Reconcile deleted (flag cloud-removed rows)", "destructive": False, "panel_visible": False},
        # --- destructive: require confirm=true ---
        "organize":      {"args": ["--organize"], "label": "Organize into month folders", "destructive": True},
        # organize's inverse: replays organize_manifest.csv backwards, then deletes the
        # manifest. Destructive for exactly the reason organize is -- it MOVES the owner's
        # files on the server's own disk -- and there is no second manifest to undo the undo.
        "undo-organize": {"args": ["--undo-organize"],
                          "label": "Undo organize — move files back to their old paths",
                          "destructive": True},
        "dedup-apply":   {"args": ["--dedup", "--apply"], "label": "Dedup — quarantine dupes to _duplicates/", "destructive": True},
        # DELETES rather than quarantining, so it is strictly more dangerous than
        # dedup-apply and carries the same destructive=True (confirm + localhost-only).
        # Deliberately a separate key, not a flag the client can add -- see audit-full.
        "dedup-delete":  {"args": ["--dedup", "--apply", "--dedup-delete"],
                          "label": "Dedup — DELETE dupes outright (no _duplicates/ safety net)",
                          "destructive": True},
        # The Tidy tab's last duplicates step (2026-11-19): the files in _duplicates/ to the
        # Recycle Bin. moonglade/organize.py's cmd_empty_duplicates holds every gate itself --
        # only after an all-clear --verify-dupes, only if _duplicates/ is exactly what that
        # check passed, checked again on the spot, READ_ONLY refuses, no send2trash refuses --
        # so this key adds only the Panel's own confirm + localhost-only, like its siblings.
        "empty-dupes":   {"args": ["--empty-duplicates", "--apply"],
                          "label": "Empty _duplicates/ to the Recycle Bin (after a clean Verify)",
                          "destructive": True},
        # The write-enabled twin of verify-dupes above (--restore-orphans does nothing on
        # its own -- it only takes effect alongside --verify-dupes). Its own key rather
        # than a checkbox on verify-dupes, same reason as audit-full. Recovery, not loss --
        # it moves quarantined files with no surviving keeper back into images/ -- but
        # still an unlogged file move on the host, so it's gated like the rest.
        "restore-orphans": {"args": ["--verify-dupes", "--restore-orphans"],
                            "label": "Verify quarantine + restore orphans to images/",
                            "destructive": True},
        "rebuild-thumbs": {"args": ["--rebuild-thumbs"],
                           "label": "Rebuild ALL thumbnails — uniform quality + video posters",
                           "destructive": True},
    }

    def _panel_reader(proc, then=None):
        with _panel_lock:
            jid = _panel_job.get("job_id")
        last_pct = -1
        warn_n = 0
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if line.startswith(_PROG_PREFIX):
                # progress marker (not log): "<prefix>done|total|new" -> drive the bar
                try:
                    done, total, new = (int(x) for x in line[len(_PROG_PREFIX):].split("|"))
                    with _panel_lock:
                        _panel_job["progress"] = {"done": done, "total": total, "new": new,
                                                  "pct": round(min(done / total, 1.0) * 100, 1) if total else None}
                    if jid and total:                    # mirror into the Activity card, throttled
                        pct = int(min(done / total, 1.0) * 100)
                        if pct != last_pct:              # ~once per 1% tick, not every line
                            last_pct = pct
                            _log_job(jid, status="running", done=done, total=total)
                except (ValueError, ZeroDivisionError):
                    pass
                continue
            if line.startswith(_WARN_PREFIX):
                # D-4: "<prefix>N" -- N files failed after retries, run otherwise completed.
                # Not a log line -- keep it out of the visible transcript, same as _PROG_PREFIX.
                try:
                    warn_n = int(line[len(_WARN_PREFIX):])
                except ValueError:
                    pass
                continue
            with _panel_lock:
                _panel_job["lines"].append(line)
                if len(_panel_job["lines"]) > 800:       # ring buffer
                    del _panel_job["lines"][:-800]
        proc.stdout.close()
        rc = proc.wait()
        with _panel_lock:
            cancelled = _panel_job.get("cancelled")
            status = ("cancelled" if cancelled else
                      "failed" if rc != 0 else
                      "done_with_errors" if warn_n else "done")
            _panel_job["rc"] = rc
            _panel_job["status"] = status
            _panel_job["warn_count"] = warn_n
            _panel_job["progress"] = None                # clear the bar when the job ends
            _panel_job["proc"] = None
        if jid:                                          # cancelled/done both close the card row cleanly
            # rc rides the terminal event for the same reason `action` rides the start
            # one: the ledger's result column shows the design's own "… · rc 0" format
            # (Control Panel.dc.html:106/517), and until now a successful run's exit
            # code was simply never written anywhere.
            _log_job(jid, status=("failed" if status == "failed" else
                                  "done_with_errors" if status == "done_with_errors" else "done"),
                     rc=rc,
                     error=("exited {}".format(rc) if status == "failed" else
                           "{} file(s) failed to download".format(warn_n) if status == "done_with_errors"
                           else None))
        # THE CHAIN (the living library's "Backfill phash after each Sync"). The follow-on
        # starts only after this one has genuinely finished -- the slot was released three
        # lines up -- and only when the first job SUCCEEDED: chaining a phash backfill onto
        # a sync that failed would just be a second failure. Best-effort by design: if the
        # slot has already been claimed by the owner's own click in the meantime, the
        # follow-on is simply skipped. Both halves are idempotent, so the next scheduled
        # sync brings it around again; blocking here to wait for the slot would pin this
        # reader thread on a job it has no business owning.
        if then and status == "done":
            try:
                # A follow-on nobody clicked: scheduled, so it takes the action's own
                # unattended argv (the view-count opt-out) exactly as the tick would.
                _panel_run(then, scheduled=True)
            except Exception:                             # noqa: BLE001
                pass

    def _panel_run(action, int_arg=None, then=None, scheduled=False):
        """Start one whitelisted Panel job as a subprocess.

        `scheduled` means NOBODY CLICKED THIS. It is the living library's tick, the legacy
        standing order, or a follow-on in a `then` chain -- and it is the one difference
        that can change the argv, through the action's own `scheduled_args`. Today that is
        the view-count opt-out on "sync-artworks" (owner's call, 2026-09-06: a view read
        adds one view to every published work, so an unattended refresh must not do it).
        Declared per action rather than decided here, so "what does an automatic run do
        differently" is answerable by reading the action table."""
        from moonglade.gallery import _NO_WINDOW
        import subprocess
        spec = PANEL_ACTIONS[action]
        # Worker count is a persisted panel setting (schedule.json), so BOTH manual
        # clicks and the scheduled run use it. Harmless on jobs that ignore --workers
        # (organize/dedup/audit); speeds up the ones that don't (sync's pull + backfill).
        try:
            workers = max(1, min(int(_load_sched().get("workers") or 4), 16))
        except (TypeError, ValueError):
            workers = 4
        action_args = list(spec["args"])
        if spec.get("int_param"):
            # The ONLY variable part of any panel argv, and it is a single bounded
            # integer, never a caller string: clamp int_arg into the action's declared
            # range (falling back to its default when absent, e.g. a stray scheduler
            # call), then append it. This is what lets test-pull carry an N without
            # eroding _panel_run's "a WHITELISTED argv, never an arbitrary command".
            lo, hi = spec["int_range"]
            try:
                n = max(lo, min(int(int_arg), hi))
            except (TypeError, ValueError):
                n = spec.get("int_default", lo)
            action_args = action_args + [str(n)]
        if scheduled:
            action_args = action_args + list(spec.get("scheduled_args") or [])
        argv = [sys.executable] + _cli_module + ["--out", str(out_dir), "-v",
                "--workers", str(workers)] + action_args
        # MOONGLADE_PROGRESS makes the CLI emit machine progress markers we parse above.
        # PYTHONIOENCODING: the reader below decodes this pipe as UTF-8, but a child whose
        # stdout is a pipe picks the locale encoding (cp1252 on this box), so any non-ASCII
        # the CLI prints arrived as a replacement character in the transcript. Sync's
        # closing line now carries an em dash (2026-09-07), so make the two agree at the
        # source rather than mangling the one sentence that says whether the walk finished.
        env = dict(os.environ, MOONGLADE_PROGRESS="1", PYTHONIOENCODING="utf-8")
        import uuid
        job_id = "panel-" + uuid.uuid4().hex[:12]
        # CLAIM the single job slot -- check and mark in ONE lock acquisition, BEFORE any
        # subprocess exists; returns False (having spawned nothing) when it's already
        # taken. The check used to live at the caller and the mark down here after Popen,
        # so two near-simultaneous starts (a double-click, two tabs, the scheduler firing
        # as the owner clicks) both passed the check, both spawned, and the second's
        # update() overwrote the first's proc handle: one subprocess orphaned, invisible
        # to /api/panel/cancel, and for a destructive action walking the same files as
        # its twin -- exactly what "one job runs at a time" exists to prevent.
        with _panel_lock:
            if _panel_job["status"] == "running":
                return False
            # THE SECOND DIRECTION of the sweep exclusion, claimed under the SAME lock that
            # claims the slot -- which is what makes the pair airtight rather than merely
            # narrow. The sweep takes _artworks_lock and only THEN reads this slot
            # (artworks_sweep_kick's `busy`); this reads _artworks_lock while holding the
            # slot's own lock. So one of the two always sees the other, whichever order
            # they arrive in, and the loser stands down. The probe never blocks, so holding
            # _panel_lock across it cannot deadlock.
            #
            # Without this, run_download's per-page save silently reverted every column the
            # sweep wrote: it rebuilds each row from a snapshot taken when the JOB started,
            # and the upsert writes the whole row back.
            if action in _living.ARTWORKS_TOUCHING_ACTIONS and _living.artworks_sweep_in_flight():
                return False
            _panel_job.update(status="running", action=action, label=spec["label"],
                              lines=["$ " + " ".join(action_args)], rc=None,
                              started_at=None, progress=None, proc=None, cancelled=False,
                              job_id=job_id, warn_count=0)
        try:
            proc = subprocess.Popen(argv, cwd=_cli_dir, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    encoding="utf-8", errors="replace", env=env,
                                    creationflags=_NO_WINDOW)
            if proc is None:
                # A spawn that hands back nothing is a failed spawn: the reader thread
                # would otherwise die on `proc.stdout` and leave the slot "running".
                raise RuntimeError("could not start the job: no process was created")
        except Exception:
            # Release the slot on a failed spawn, or one bad launch wedges the Panel for
            # the life of the process (nothing would ever clear a "running" with no proc).
            with _panel_lock:
                _panel_job.update(status="failed", proc=None)
            raise
        with _panel_lock:
            _panel_job["proc"] = proc
        # `action` rides the start event so the reconstructed job carries the machine
        # key alongside the display label -- the Panel's run-history ledger needs it
        # for per-action last-run lookups and its "run again" control. Merge semantics
        # (_reconstruct_jobs' cur.update) keep it through every later event.
        #
        # `scheduled` rides it for the same reason and by the same merge: the client cannot
        # tell an unattended run from a clicked one, and from the owner's walk (2026-09-07)
        # it must -- an automatic job produces NO completion toast at all, only the Activity
        # line (gallery/src/notify/jobsStore.js's toastTransitions). Written once, on the
        # START event; cur.update carries it onto the terminal event the reader writes.
        # `or None` rather than the bare False because append_job_event drops None fields,
        # so a clicked run's row is byte-for-byte what it has always been -- absence means
        # "somebody pressed this", which is what every row written before today means too.
        _log_job(job_id, status="running", type="panel", label=spec["label"], action=action,
                 scheduled=(scheduled or None))
        threading.Thread(target=_panel_reader, args=(proc,), kwargs={"then": then},
                         daemon=True).start()
        return True

    def _update_busy():
        """The updater's phase while it is mid-flight, else "". The other half of the
        mutual exclusion the apply route already enforces one way: an update refuses to
        start while a job runs, so a job (or a Stop, or a Restart) must equally refuse to
        start while an update runs. Pulling code out from under a running job and
        restarting a server mid-pull are the same class of mistake in both directions.

        The updater's OWN restart is exempt by construction: it calls
        _schedule_server_exit directly rather than going through the route, because it
        already re-checks the very gates that route applies."""
        phase = _updater.update_state()["phase"]
        return phase if phase in ("backup", "pulling", "deps", "restarting") else ""

    def _update_busy_refusal():
        return jsonify({"error": "an update is in progress (%s) — wait for it to finish; "
                                 "the server restarts itself when it is done."
                                 % _update_busy()}), 409

    def _job_busy():
        """The running job's label, or "" when the slot is free -- the server-side half of
        the rule the Panel already draws (Stop and Restart carry class 'jobbtn', which
        poll() disables while a job runs). Returned as a label rather than a bool so the
        refusal can name what is in the way."""
        with _panel_lock:
            return _panel_job["label"] if _panel_job["status"] == "running" else ""

    # ---- Automated tasks: run a SAFE job on an interval while the app is open ----
    # Persisted to out_dir/_moonglade/records/schedule.json. Only non-destructive actions are schedulable.
    # An in-process daemon: fires while the gallery is running (it is NOT an OS-level
    # cron -- for always-on, point Windows Task Scheduler at `--update` instead).
    _sched_lock = threading.Lock()

    def _log_job(job_id, **fields):
        """Append a job event to the library's jobs.jsonl (_moonglade/records/) for the Jobs card. Fails soft --
        activity logging must never break the request that triggered it."""
        try:
            from moonglade import backup as _core
            _jobs.append_job_event(out_dir, job_id, **fields)
        except Exception:
            pass

    def _sched_path():
        return _paths.records_path(out_dir, "schedule.json")

    def _load_sched():
        """schedule.json, normalized. The legacy quartet (enabled/action/interval_hours/
        last_run) is UNCHANGED -- it is still the one "standing order" the Panel's ledger
        draws and /api/panel/schedule writes. `jobs` is the living library's list, added
        beside it rather than replacing it, so a schedule saved by an older build keeps
        meaning exactly what it meant. `artworks_deep_at` is the sweep's 48-hour tier
        stamp: it lives here so a restart does not turn every boot into a full walk."""
        s = None
        try:
            if _sched_path().exists():
                loaded = json.loads(_sched_path().read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    s = loaded
        except (OSError, ValueError):
            pass
        if s is None:
            s = {"enabled": False, "action": "sync", "interval_hours": 6,
                 "last_run": None, "workers": 4}
        s["jobs"] = _living.living_merge(s.get("jobs"))
        try:
            s["artworks_deep_at"] = float(s.get("artworks_deep_at") or 0.0)
        except (TypeError, ValueError):
            s["artworks_deep_at"] = 0.0
        return s

    def _save_sched(s):
        """Written whole (S4): a temp beside it, then os.replace -- the stamps rewrite this
        file every few minutes, and a torn write must never lose the owner's schedule."""
        p = _sched_path()
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        try:
            tmp.write_text(json.dumps(s), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    def _sched_stamp(**fields):
        """Re-read under the lock, apply `fields`, save. The read-modify-write every
        stamping caller needs: `s` in a loop body was loaded up to a minute ago, so
        writing that whole copy back would silently revert any setting the owner saved
        through /api/panel/schedule in the meantime."""
        with _sched_lock:
            s = _load_sched()
            for k, v in fields.items():
                s[k] = v
            _save_sched(s)
            return s

    def _living_stamp(action, when):
        """Record one living job's last run, under the same re-read-first discipline."""
        with _sched_lock:
            s = _load_sched()
            for row in s["jobs"]:
                if row["action"] == action:
                    row["last_run"] = when
            _save_sched(s)

    # THE ONE PLACE THE AUTOMATION POLICY LIVES. Everything the loop is allowed to start
    # by itself passes through here, and nothing else does.
    #
    #   * The artworks sweep is in-process, reads PixAI and writes eleven columns of rows
    #     it already has. Always runnable.
    #   * An INTERVAL job must be a real PANEL_ACTIONS key that is neither destructive nor
    #     advanced -- the existing refusal, carried over word for word from the single-job
    #     scheduler. A full re-walk on a six-hour timer is a foot-gun; test-pull needs an N
    #     the scheduler cannot supply; and nothing destructive is ever automatic.
    #   * The STALENESS BACKSTOP is the one deliberate widening, and it is a CLOSED set:
    #     exactly the three jobs the owner named in call 5 (full re-walk, rebuild Similar,
    #     rebuild thumbnails), each only after sixty days without a run. The scope's own
    #     safety audit puts all three in "safe but wasteful on a timer" -- idempotent,
    #     non-destructive to originals, carry-proven -- and separates them from the four
    #     that must stay manual (organize, undo organize, dedup quarantine/delete, restore
    #     orphans), which are NOT in this set and can never enter it: the set is a literal
    #     in this file, not anything a client, a config file or a route can name.
    #
    #     TWO OF THE THREE ARE FLAGGED IN PANEL_ACTIONS, and it is worth being exact about
    #     what that widening actually costs, because "nothing destructive is ever automatic"
    #     is a promise this file has to keep:
    #       - `resync-full` is advanced=True. "Advanced" means "not a thing to put on a
    #         SHORT timer" (a full re-walk every six hours is a foot-gun) -- a sixty-day
    #         floor is the case that flag was guarding for, not against. It is read/append
    #         and deletes nothing.
    #       - `rebuild-thumbs` is destructive=True. That flag is the confirm + localhost
    #         GATE on a job that deletes and re-renders every thumbnail; thumbnails are
    #         DERIVED files, regenerated from the originals, and no original, catalog row,
    #         rating or collection can be reached by it. It is why the scope's audit lists
    #         it under "safe but wasteful" and NOT under "must stay manual", and why the
    #         owner named it in call 5. It is the one action where the code flag and the
    #         scope's automation classification differ, and this comment is the whole of
    #         that difference -- the four jobs that can really lose the owner's data are
    #         still unreachable from here by construction.
    _LIVING_STALE_ACTIONS = _living.LIVING_STALE_ACTIONS      # the module-level literal, verbatim

    def _living_runnable(action):
        if action == _living.LIVING_SWEEP_ACTION:
            return True
        if action not in PANEL_ACTIONS:
            return False
        if action in _LIVING_STALE_ACTIONS:
            return True
        spec = PANEL_ACTIONS[action]
        return not spec["destructive"] and not spec.get("advanced")

    def _standing_runnable(action):
        """Can the LEGACY standing-order scheduler actually start this action?

        Its own tick's refusal, stated once so three readers agree: a real PANEL_ACTIONS
        key, not destructive, not advanced. (The staleness backstop's widening belongs to
        the living library's list, not to this path -- the legacy scheduler has always
        refused an advanced action outright.)"""
        spec = PANEL_ACTIONS.get(action)
        return bool(spec) and not spec["destructive"] and not spec.get("advanced")

    def _standing_action(s):
        """The action the legacy standing order is really running, or None.

        NAMING ONE IS NOT RUNNING ONE, and that gap is what made a job disappear from both
        schedulers. `resync-full` could be SAVED here (the route only rejected unknown and
        destructive keys) while _scheduler_loop's own tick refused to start it for being
        advanced -- and _living_tick then stood aside for it, forever, while the Panel told
        the owner "the standing order below runs this one". The save route rejects an
        advanced action now; this is the backstop for a schedule.json written by an older
        build or by hand, so such a row falls through to the living library instead of
        vanishing from both."""
        action = s.get("action") if s.get("enabled") else None
        return action if action and _standing_runnable(action) else None

    def _artworks_job_busy():
        """The artworks-touching Panel job in the slot right now, or "" when there is none.

        WHY THE IN-PROCESS LOCK IS NOT ENOUGH, and why this exists beside it. _artworks_lock
        makes the sweep single-flight within THIS process, which is all a threading.Lock can
        ever do. Every Panel action, though, runs as a SUBPROCESS: _panel_run spawns the CLI
        with subprocess.Popen, so it is a separate interpreter with its own SQLite connection
        and no possible knowledge of a lock object living in the server's memory. A sweep and
        a `--sync` can therefore be writing the same rows at the same instant and neither
        lock will notice; SQLite's own file locking serialises the two STATEMENTS, which is a
        different and much weaker promise than serialising the two JOBS.

        So the sweep defers, by looking at the one piece of shared state that does cross the
        boundary: the Panel's single job slot, which this process owns and fills before it
        spawns anything (_panel_run claims it under _panel_lock, before Popen). Reading it is
        the whole mechanism -- there is no new lock, no new file, and no new state.

        Returns the action name (so a refusal can say what is in the way) rather than a
        bool, exactly as _job_busy and _update_busy already do."""
        with _panel_lock:
            if _panel_job["status"] != "running":
                return ""
            action = _panel_job.get("action") or ""
        return action if action in _living.ARTWORKS_TOUCHING_ACTIONS else ""

    def _artworks_kick(force=False, scheduled=False):
        """Fire one published-artwork sweep OFF-THREAD -- the one entry point all four
        triggers use (boot, the fifteen-minute tick, the publish kick, Run now).

        `scheduled` means NOBODY CLICKED THIS, exactly as it does on _panel_run -- and it
        is passed per trigger rather than derived from `force`, which looks like the same
        question and is not: three of the four triggers force past the fifteen-minute
        guard, and only ONE of those three (Run now) is a click. It rides the sweep's own
        `log_event` onto the row it writes, so an unattended sweep lands in the Activity
        window without a corner toast (owner's walk, 2026-09-07).

        Off-thread because none of the four can afford to wait on it: the publish kick
        happens inside a route that has already committed an irreversible publish, Run now
        must answer the click, and the tick must not stall the release check while a
        once-per-48-hours deep pass walks the whole published history at 0.4s a page.

        The single-flight lock inside artworks_sweep_kick is what makes that safe: a
        trigger that loses the race has nothing to do, because the sweep already in flight
        reads the same account from the same list.

        Rides MOONGLADE_DISABLE_WATCH (as _bg_release_check) for the same reason the live
        mirror, the contest sweep and the release check do: it is background work that
        reaches PixAI with whatever real credentials this machine's config.json holds, and
        the suite's conftest sets that flag precisely so no test can make that request.

        DEFERS to a catalog-writing Panel job (see _artworks_job_busy for why the sweep's
        own lock cannot see one). ALL FOUR triggers defer, the publish kick included: the
        job in the slot is itself re-reading PixAI into these rows, so the kick would be
        racing a writer to publish the same truth. Nothing is lost by waiting -- the next
        tick sweeps, and a `--sync` or a `--sync-artworks` writes the publish back itself.

        Returns whether a sweep was actually started."""
        _living._artworks_state["kicks"] += 1        # a trigger asked; see the counter's own note
        if not _bg_release_check:
            return False
        if _artworks_job_busy():
            return False

        def _go():
            try:
                # Seed the 48-hour tier stamp from disk before deciding, then write back
                # whatever this sweep concluded -- so a restart cannot turn every boot into
                # a deep walk, and a deep walk that just happened is remembered.
                with _sched_lock:
                    saved = float(_load_sched().get("artworks_deep_at") or 0.0)
                if saved > _living._artworks_state["deep_at"]:
                    _living._artworks_state["deep_at"] = saved
                # The sweep bypasses _panel_run entirely (it is in-process work, not a
                # subprocess in the job slot), so this wrapper is where its row learns
                # whether anybody asked for it. Same `or None` as _panel_run's: a Run now
                # writes the row it always wrote.
                def _sweep_log(job_id, **fields):
                    _log_job(job_id, scheduled=(scheduled or None), **fields)

                _living.artworks_sweep_kick(out_dir, db_path, force=force, log_event=_sweep_log,
                                    busy=_artworks_job_busy)
                _sched_stamp(artworks_deep_at=_living._artworks_state["deep_at"])
            except Exception:                                # noqa: BLE001
                pass
        threading.Thread(target=_go, daemon=True).start()
        return True

    def _living_run(action):
        """Start one living job. Returns whether it actually started -- a False means the
        Panel's single slot was taken, and the tick simply tries again in sixty seconds."""
        if action == _living.LIVING_SWEEP_ACTION:
            # ALWAYS "started": the tick's own fifteen-minute cadence is the authority
            # here, so a sweep that declines (one already in flight, no resolvable account)
            # must not make the loop retry every sixty seconds forever. Forced past the
            # sweep's OWN fifteen-minute recent-guard, because the cadence the owner set on
            # this row is the one that governs here and it may be shorter than that guard --
            # the tick decides freshness itself, in artworks_sweep_fresh, before it gets
            # here (and that is what stops the first tick repeating the boot kick).
            # Scheduled: this IS the living library's tick, the same as the _panel_run
            # branch below it.
            _artworks_kick(force=True, scheduled=True)
            return True
        return _panel_run(action, then=_living.LIVING_BY_ACTION.get(action, {}).get("then"),
                          scheduled=True)

    # Read ONCE, here, exactly as the live-mirror gate is read once further down: a daemon
    # that re-read the environment every minute could catch the instant BETWEEN two tests
    # (the suite sets this flag per-test) and make a real GitHub request out of a run that
    # must never touch the network.
    _bg_release_check = os.environ.get("MOONGLADE_DISABLE_WATCH") != "1"

    def _update_check_tick():
        """The updater's background cadence, riding the scheduler's existing 60-second
        heartbeat rather than a timer thread of its own. The standing rule -- "web surfaces
        register jobs, they never add a second poll loop" (DECISIONS.md 2026-07-24) -- reads
        just as literally on this side of the wire: there is already one periodic tick in
        this process, so the hourly check joins it instead of becoming a second one.
        run_update_tick owns the hour; this is only the heartbeat that asks it.

        CHECK AND ANNOUNCE. There is no path from here to run_update or /api/update/apply,
        and a test walks this function's source to keep it that way.

        Rides MOONGLADE_DISABLE_WATCH (as _bg_release_check, sampled above) for the same
        reason the live-mirror watcher and the contest sweep do: it is background work that
        reaches the network, and the suite's conftest sets that flag precisely so
        create_app() cannot make a real request."""
        if not _bg_release_check:
            return
        try:
            from moonglade import backup as _core
            _updater.run_update_tick(_core.__version__)
        except Exception:              # noqa: BLE001 -- a check must never kill the loop
            pass

    def _contest_win_tick():
        """The verified-contest-wins check (L3), on the scheduler's existing 60-second heartbeat
        like the release check above: no thread or timer of its own. All this does each minute
        is contest_win_kick's local look at the schedule (one small file read, no network); a
        pass starts only when a contest's check is actually due, off-thread and single-flight,
        because a pass paces itself between contests.

        Rides MOONGLADE_DISABLE_WATCH (as _bg_release_check, sampled above) for the same reason
        the contest sweep and the release check do: it reaches PixAI with this machine's real
        credentials, and the suite's conftest sets that flag precisely so create_app() cannot
        make that request."""
        if not _bg_release_check:
            return
        try:
            _contest_sync.contest_win_kick(out_dir)
        except Exception:              # noqa: BLE001 -- a check must never kill the loop
            pass

    _mirror_renew_seen = {"last": None}

    def _mirror_renew_tick():
        """The Mirror token's background renewal (#71), on the scheduler's existing 60-second
        heartbeat like the release check and the contest-wins check: no thread or timer of its
        own. core.mirror_renew_tick keeps its own 15-minute cadence and is offline unless the
        token is due, so all this does most minutes is a clock comparison.

        Rides MOONGLADE_DISABLE_WATCH (as _bg_release_check, sampled above) for the same reason
        the contest sweep and the release check do: a renewal reaches PixAI with this machine's
        real credentials, and the suite's conftest sets that flag precisely so create_app()
        cannot make that request.

        Logs a renewal, and a failure once per run of failures (not every tick); never the
        token -- only days left and the failure's fixed reason word."""
        if not _bg_release_check:
            return
        try:
            import logging as _logging
            from moonglade import backup as _core
            out = _mirror.mirror_renew_tick()
            _log = _logging.getLogger(__name__)
            if out == "renewed":
                left = _mirror.jwt_days_left(_mirror.load_mirror_state().get("jwt") or "")
                _log.info("mirror: renewed the PixAI web session in the background via %s "
                          "(%s days left)", _mirror._mirror_renewal.get("last_road") or "jwt",
                          left)
            elif out == "failed" and _mirror_renew_seen["last"] != "failed":
                _log.warning("mirror: couldn't renew the PixAI web session (%s); retrying "
                             "with backoff", _mirror._mirror_renewal.get("last_reason") or "failed")
            if out in ("renewed", "failed"):
                _mirror_renew_seen["last"] = out
        except Exception:              # noqa: BLE001 -- a renewal must never kill the loop
            pass

    # Test seam: the gate is the thing worth proving at runtime (the suite runs with it off).
    app.extensions["mg_mirror_renew_tick"] = _mirror_renew_tick

    def _living_tick():
        """THE LIVING LIBRARY'S HEARTBEAT -- the job LIST, riding the same sixty-second tick
        as everything else in this process. No new thread, no second poll loop: the standing
        rule ("web surfaces register jobs, they never add a second poll loop", DECISIONS.md
        2026-07-24) reads the same on this side of the wire, which is why the release check
        already lives on this tick too.

        Its own function, above _scheduler_loop and called from it, for two reasons: the
        loop body must stay free of nested defs and thread spawns (a test walks it), and the
        sweep genuinely does need to be off-thread -- its once-per-48-hours deep pass walks
        the whole published history at 0.4s a page, and stalling the tick for minutes would
        stall the release check and the whole job list with it.

        ONE JOB PER TICK. There is exactly one Panel slot, and a tick that started four
        things would spawn one and silently drop three. The list is in shipped order, so the
        first due job that can actually start is the one that goes.

        THE GATE IS THIS FUNCTION; the work is _living_tick_once below. Split so the loop's
        heartbeat keeps its gate while the decision itself can be driven directly on a
        stubbed subprocess seam -- a job list whose one-per-tick rule is only ever asserted
        by reading source text is a rule nothing proves at runtime."""
        if not _bg_release_check:
            # The same gate the contest sweep and the live mirror ride, for the same
            # reason: this reaches PixAI with the machine's real credentials, and the
            # suite's conftest sets that flag precisely so create_app() cannot.
            return
        _living_tick_once()

    def _living_tick_once():
        """One pass of the job list -- see _living_tick above for the whole account."""
        try:
            import time as _t
            with _sched_lock:
                s = _load_sched()
            # The sweep's 48-hour tier stamp survives restarts through schedule.json --
            # re-seed the in-memory state from it on the first tick that reads a newer one,
            # so a boot does not turn every start into a deep walk.
            if s.get("artworks_deep_at", 0.0) > _living._artworks_state["deep_at"]:
                _living._artworks_state["deep_at"] = float(s["artworks_deep_at"])
            now = _t.time()
            due, baselined = _living.living_due(s["jobs"], now, is_runnable=_living_runnable)
            for action in baselined:
                # First sight of a staleness job: stamp `now` as its floor and run nothing.
                # A fresh install must not open by re-walking its whole history.
                _living_stamp(action, now)
            if not due:
                return
            if _update_busy():
                return                          # an update is mid-flight -- next tick
            # The legacy standing order still owns whatever action it names, so the list
            # never doubles up on it: two paths starting the same job would just take
            # turns losing the single slot. The row is NOT silently skipped on screen --
            # /api/panel/schedule marks it `deferred` and the Panel says so in the row's
            # own note line, because a row displaying a cadence it is not running is a lie
            # the owner has no way to catch.
            standing = _standing_action(s)
            for action in due:
                if action == standing:
                    continue
                if action == _living.LIVING_SWEEP_ACTION:
                    # Belt and braces around the subprocess the sweep's own lock cannot
                    # see, and around the boot kick it would otherwise repeat. Neither is
                    # stamped: last_run must keep meaning "when this job last ran", so a
                    # deferral retries on the next tick instead of buying a whole cadence
                    # of silence.
                    if _artworks_job_busy():
                        continue
                    row = next((r for r in s["jobs"] if r.get("action") == action), None)
                    if _living.artworks_sweep_fresh((row or {}).get("interval_s"), now):
                        continue
                if _living_run(action):
                    _living_stamp(action, now)
                    return                      # one job per tick
        except Exception:              # noqa: BLE001 -- a bad schedule must not kill the loop
            pass

    # Test seam, same rationale as app.extensions["mg_panel_job"] above: the job list's
    # decision and the automation policy are closures over out_dir/db_path, so calling them
    # is the only way to prove at RUNTIME that two due jobs start exactly ONE subprocess,
    # or that `organize` is refused by the policy rather than merely absent from a list.
    # Exposes the functions, not a way around any gate: _artworks_kick keeps its own
    # background-network gate, so nothing here can reach PixAI.
    app.extensions["mg_living"] = {"tick": _living_tick_once,
                                   "runnable": _living_runnable}

    def _scheduler_loop():
        import time as _time
        while True:
            _time.sleep(60)
            # Outside the schedule's own try/continue chain below: whether an AUTOMATED
            # TASK is due has nothing to do with whether the release check is, and the
            # first `continue` down there (schedule disabled -- the default) would
            # otherwise skip the update tick on every install that never set one up.
            _update_check_tick()
            # Same place, same reason: contest wins are verified on this heartbeat too.
            _contest_win_tick()
            # And the Mirror token's background renewal (#71), for the same reason.
            _mirror_renew_tick()
            # Same reason, same place: the living library's job list is not the legacy
            # standing order, and that `continue` would skip it on every install that
            # never configured one.
            _living_tick()
            try:
                # Same lock /api/panel/schedule writes under -- reading the file while a
                # save is mid-write otherwise hands this loop a truncated (or stale) copy.
                with _sched_lock:
                    s = _load_sched()
                action = s.get("action")
                if not s.get("enabled") or action not in PANEL_ACTIONS \
                        or PANEL_ACTIONS[action]["destructive"] \
                        or PANEL_ACTIONS[action].get("advanced"):
                    # advanced actions are manual-run only (a full re-walk on a timer is a
                    # foot-gun; test-pull needs an N the scheduler can't supply) -- backstop
                    # to the dropdown already hiding them, in case an old schedule names one.
                    continue
                interval = max(1, int(s.get("interval_hours") or 6)) * 3600
                if _time.time() - (s.get("last_run") or 0) < interval:
                    continue
                if _update_busy():
                    continue                   # an update is mid-flight -- next tick
                # Same follow-on table the tick and the manual click read: an owner whose
                # standing order was already set to "sync" (the schedule's own default
                # action) runs that job through THIS path forever, and the list's own
                # "sync" row is permanently deferred to it -- so without this the chain
                # never fired for him at all.
                if not _panel_run(action,
                                  then=_living.LIVING_BY_ACTION.get(action, {}).get("then"),
                                  scheduled=True):
                    continue                   # panel busy -- retry on the next tick
                # Re-read under the lock before stamping: `s` was loaded up to a minute
                # ago, so writing that whole copy back would silently revert any setting
                # the owner saved through /api/panel/schedule in the meantime. The lock
                # can't span _panel_run -- it calls _load_sched() itself for `workers`.
                with _sched_lock:
                    s = _load_sched()
                    s["last_run"] = _time.time()
                    _save_sched(s)
            except Exception:              # noqa: BLE001 -- a bad schedule must not kill the loop
                pass

    # MOONGLADE_DISABLE_SCHEDULER=1 leaves the loop unstarted -- set by the test suite's
    # conftest for the whole run, the way MOONGLADE_DISABLE_WATCH keeps the watcher off. The
    # loop never stops once started, so every app a test built used to leave one ticking for
    # the rest of the run, where it could wake inside a later test (issue #77). Tests that are
    # about the scheduler call its ticks directly. The launcher never sets it.
    if os.environ.get("MOONGLADE_DISABLE_SCHEDULER") != "1":
        threading.Thread(target=_scheduler_loop, daemon=True, name="mg-scheduler").start()

    # ---- Live-mirror watcher: event-driven backup over PixAI's push WebSocket -----
    # Keeps the CLI's --watch/--watch-backup machinery (moonglade/backup.py)
    # connected for as long as the gallery runs, auto-reconnecting with backoff on any
    # drop. Each generation is downloaded + cataloged the INSTANT it completes -- this
    # is what makes --update a fallback instead of the only way gens land locally.
    # Read-only listening + free downloads (no credits spent). Always-on by design.
    #
    # Staleness watchdog (2026-07-23): a real incident showed `connected` reading
    # True with no error for ~21 minutes while the socket had actually gone silent
    # -- no exception, no close frame, nothing to trip the reconnect logic below on
    # its own. core._watch_events_async now times out waiting on each individual
    # frame (core._WS_STALE_TIMEOUT, currently 4 minutes -- see that constant's own
    # comment for how the number was chosen) and raises core.WatchStaleError, which
    # lands in this loop's `except` below exactly like any other dropped connection
    # and gets reconnected the same way -- no separate thread, no polling, no new
    # control flow, just a bound on how long `await ws.recv()` is allowed to block.
    _watch_lock = threading.Lock()
    _watch_status = {"connected": False, "last_event_at": None, "mirrored": 0,
                      "events_seen": 0, "last_error": None, "started_at": None,
                      # New fields (additive -- see api_watch_status()): how many times
                      # the staleness watchdog below has had to force a reconnect, and
                      # when the most recent one happened. Existing readers of this dict
                      # (the Panel's watch-status UI, tests) only read the fields they
                      # already know about, so this is safe to add without touching them.
                      "stale_reconnects": 0, "last_stale_reconnect_at": None,
                      # #60: how the last connection ended and how long it lived, so the next
                      # drop investigation is a read of /api/watch/status, not a probe.
                      # `last_close` is watch_close_info's dict; the Panel does not draw these.
                      "connected_at": None, "last_close_at": None, "last_close": None,
                      "last_connection_s": None, "reconnects": 0,
                      # 3.22: the REST task stream's OWN record (moonglade.task_feed). The
                      # stream never writes the WebSocket's fields above.
                      "task_stream": _task_feed.new_stream_status()}

    # ---- Single-flight collect (per task id, in-process) -------------------------
    # THREE uncoordinated collectors live in this process: the always-on live-mirror
    # watcher below, /api/task-status's done-poll, and /api/import-task (whose
    # already-catalogued precheck narrows the window but cannot close it). Two of them
    # landing on the same just-finished task seconds apart used to run
    # core.collect_generation twice concurrently: download() skipped the second copy,
    # but both passes then ran video_faststart on the same clip, and the two
    # concurrent ffmpeg remuxes corrupted it (see video_faststart's docstring). Now
    # the first entrant per task id runs the real collect while any later entrant
    # waits, then answers from the catalog instead of re-downloading. In-process only
    # by design: the CLI's --watch-backup is a separate process, which is exactly why
    # video_faststart's unique temp name is the load-bearing cross-process guard --
    # this layer just stops the gallery process from double-collecting at all.
    _collect_mu = threading.Lock()          # guards the in-flight map itself
    _collect_inflight = {}                  # task_id -> {"lock", "waiters", "done"}

    def _collected_from_catalog(tid):
        """A finished collect's outcome, re-read from the catalog, in
        collect_generation's return shape (saved=0: THIS caller downloaded nothing)."""
        from moonglade.gallery import task_media
        rows = task_media(db_path, tid)
        if not rows:
            return None
        return {"media_ids": [r["media_id"] for r in rows], "saved": 0,
                "is_video": any(str(r["is_video"] or "") == "1" for r in rows)}

    def _collect_single_flight(core, session, tid, force=False):
        """core.collect_generation, but never twice for the same task id -- concurrently
        OR later.

        The concurrent half was always here. The LATER half was the data-loss hole: the
        in-flight entry is dropped once its last waiter leaves, so a second poll of the
        same finished task (a relaunch re-polling a done job, which is ordinary use) found
        no entry and re-ran the collect. That re-download rebuilt the catalog rows from a
        blank template and upserted them, blanking artwork_id, is_published, title, rating,
        collections and the rest -- the owner lost a published piece's artwork_id to
        exactly this, live, 2026-09-03.

        So: if the task's media are already in the catalog, that IS the answer. No
        download, no upsert, nothing to lose. `force=True` keeps a deliberate re-collect
        available (no caller needs one today). This mirrors api_import_task's own
        pre-check; the row-level carry in moonglade.backup is the second belt."""
        tid = str(tid)
        with _collect_mu:
            ent = _collect_inflight.get(tid)
            if ent is None:
                ent = _collect_inflight[tid] = {"lock": threading.Lock(),
                                                "waiters": 0}
            ent["waiters"] += 1
        try:
            with ent["lock"]:
                if not force:
                    # ALREADY COLLECTED -- by a concurrent call that just finished, or by
                    # any earlier one. Either way the media is downloaded and catalogued,
                    # so report that instead of re-downloading (and, for a video,
                    # re-remuxing) over the top of it. If nothing is catalogued (every
                    # download failed, or this is the first pass), fall through and collect
                    # for real.
                    got = _collected_from_catalog(tid)
                    if got is not None:
                        return got
                got = _gen_road.collect_generation(session, tid, str(out_dir))
                # Seven Candles (gen_streak) + The Long Vigil (active_days): a gen collected
                # into the archive marks today. Keyed day-lists, idempotent, silent-soft --
                # telemetry must never break a collect.
                try:
                    _telemetry.telem_mark_day(out_dir=out_dir, keys=("gen_days", "active_days"))
                except Exception:
                    pass
                # A NEW generation is collected only here (the early return above answers
                # for one already in the catalog), so this is where `session_hour` is
                # earned: by PixAI's own timestamp on what was just made, never a page load.
                try:
                    _telemetry.stamp_session_hour(db_path, (got or {}).get("media_ids"), out_dir)
                except Exception:
                    pass
                # bridge_gen_tasks is NOT written here: owner ruling 2026-09-03 -- the metric
                # counts the bridge's TOOLS only (enhance runs, AI-Tool scene runs), never an
                # ordinary generation that merely routes through the mirror. The two writers
                # that remain are the enhance and scene terminals.
                return got
        finally:
            with _collect_mu:
                ent["waiters"] -= 1
                if ent["waiters"] <= 0:
                    _collect_inflight.pop(tid, None)   # keep the map from growing forever

    def _log_mirrored_media(tid, got):
        """Record WHAT the watcher just collected against the job we already track, in the
        EXACT event shape /api/task-status's done branch writes (status='done', media_ids,
        is_video) -- so a reader of jobs.jsonl can't tell which collector produced it.

        The bug this closes (owner's production jobs.jsonl, 2026-07-24, two back-to-back
        generations): TWO writers can mark a generation terminal, and only one of them used
        to say what the task produced. /api/task-status's done branch logs media_ids;
        _reconcile_job, firing off the same WebSocket event, logs a BARE done. While the
        browser was still collecting gen #1 (several full-size downloads), the push event
        for gen #2 arrived and _reconcile_job won the race -- so gen #2's job went terminal
        carrying no media_ids, and nothing ever revisited it (the orphan sweep only
        re-checks jobs stuck at 'running'; this one was already 'done'). Its four images
        were downloaded and catalogued perfectly -- no data was lost -- but the Activity
        card rendered blank forever, because the tray (gallery/src/notify/ActivityTray.jsx,
        formerly static/mg-notify.js) builds its thumbnail from
        `(j.media_ids||[])[0]`. _watch_mirror had the answer in hand the whole time
        (_collect_single_flight returns {media_ids, saved, is_video}) and discarded it.
        Now whichever writer wins the race, the media ids get recorded.

        `duration` is deliberately NOT logged even though collect_generation returns one
        for videos: /api/task-status only puts it in its HTTP response, never in the job
        log, and the two writers must stay indistinguishable in the log.

        Three deliberate abstentions:
          * EMPTY media_ids writes nothing at all -- an empty list is indistinguishable
            from a real result to the tray, and would blank an entry another writer had
            already filled in correctly. Recording nothing beats recording nothing-shaped.
          * a task with NO job entry of its own writes nothing -- the same contract
            _reconcile_job keeps ("never invents one for a task generated on the website"),
            or every pixai.art generation would sprout a new Activity row here.
          * a job that ALREADY carries media_ids writes nothing -- there's nothing to add,
            and that's the common non-racing case (the browser poll got there first), so
            skipping keeps one event per generation instead of two.

        Unlike _close_orphan_if_resolved this does NOT require the job to be non-terminal:
        a job already sitting at a bare 'done' is precisely the case being fixed. Reads the
        raw reconstructed log for the same reason that helper does (an entry read_jobs()
        would already be hiding past JOBS_MAX_AGE still gets its media recorded), and skips
        a dismissed job rather than resurrecting it with a new event. Fails soft, and
        cannot raise into _watch_mirror's daemon thread: mirroring must never break,
        or lose its 'mirrored' count, because logging did."""
        try:
            from moonglade import backup as _core
            mids = (got or {}).get("media_ids") or []
            if not mids:
                return
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            j = jobs_by_id.get(str(tid))
            if not j or j.get("dismissed") or (j.get("media_ids") or []):
                return
            _log_job(str(tid), status="done", media_ids=mids,
                     is_video=got.get("is_video", False))
        except Exception:                          # noqa: BLE001 -- logging must not break mirroring
            pass

    def _watch_mirror(tid):
        """Download + catalog one finished task off the watcher's event loop (own
        session per call, matching the CLI's --watch-backup pattern), then record what it
        collected in the job log -- see _log_mirrored_media for why throwing that answer
        away left a raced generation's Activity card permanently blank.

        Deliberately does NOT write a terminal 'failed' when the collect raises, matching
        the reasoning in api_task_status's catch-all `except` (a false terminal failure
        bricks the card for a generation that actually succeeded) -- and the case for
        abstaining is STRONGER here than there. api_task_status treats EmptyOutputsError as
        terminal because it asked PixAI for the task's status itself and got 'done' from
        the same read-your-writes surface the detail query then answered from: two
        consistent reads. This path's 'done' arrives on a different channel entirely (the
        WS push), so an empty-outputs read moments later is just as plausibly the detail
        query lagging the push as a genuinely empty task -- and writing 'failed' off it
        would overwrite a perfectly good done+media_ids event in read_jobs()'s
        last-event-wins merge. The authoritative failure writers stay /api/task-status and
        the orphan sweep; a mirror problem is recorded where it belongs, in
        _watch_status['last_error'] (surfaced by /api/watch/status and the Panel) --
        and ALSO in the persistent log (added 2026-08-05): last_error alone is
        in-memory-only, gone on restart and invisible to anyone reading moonglade.log
        after the fact. Found live: a task stuck failing every catch-up sweep for
        hours produced nothing but repeated "N finished task(s) were never mirrored"
        warnings in the log (that wording is historic -- the sweep says "are missing media
        from the catalog" since 2026-09-07) -- true, but silent about WHY, because the actual
        exception only ever reached last_error. A restart cleared the symptom (fresh
        process, fresh attempt) without anyone learning the cause."""
        import logging as _logging
        from moonglade import backup as core
        _log = _logging.getLogger(__name__)
        try:
            session = core._make_session(None)
            got = _collect_single_flight(core, session, tid)
            with _watch_lock:
                _watch_status["mirrored"] += 1
        except Exception as e:
            with _watch_lock:
                _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
            _log.warning("live mirror: failed to mirror task %s: %s: %s",
                         tid, type(e).__name__, _redact_host_paths(str(e))[:200])
            return False
        # Outside the except above ON PURPOSE: _log_mirrored_media swallows its own
        # failures, and keeping it out of that handler makes it structurally impossible for
        # a logging problem to be reported as a mirror error on the watch-status line.
        _log_mirrored_media(tid, got)
        # Whether it collected: the catch-up sweep marks a task backed only on a True (#60).
        return True

    # The closures above are unreachable from outside create_app; the test suite
    # drives the watcher-mirror path through this seam (conftest disables the real
    # watcher thread via MOONGLADE_DISABLE_WATCH).
    app.extensions["mg_watch_mirror"] = _watch_mirror

    def _reconcile_job(tid, ws_status):
        """Resolve OUR Activity/job log for a task straight from a live event, so a
        generation whose Generate-card poller was closed (you navigated into the panel)
        still lands as done/failed instead of hanging at 'running' forever. Only touches a
        job we already track -- never invents one.

        That last clause used to read "never invents one for a task generated on the
        website", and the abstention was the whole point (2026-07-06). It still describes
        THIS function exactly -- what changed on 2026-09-07 is that a website run now HAS a
        row by the time this runs, written by _website_job_seen below off the same event.
        So this closes a website row without knowing or caring that it is one."""
        from moonglade import backup as core
        try:
            term = "failed" if ws_status in _task_reads._GEN_FAIL else "done"
            j = next((x for x in _jobs.read_jobs(out_dir)
                      if str(x.get("job_id")) == str(tid)), None)
            if j and j.get("status") not in ("done", "failed"):
                _log_job(str(tid), status=term,
                         error=(ws_status if term == "failed" else None))
        except Exception:                          # noqa: BLE001 -- reconciling must not kill the watcher
            pass

    # ---- A run started on pixai.art gets an Activity row of its own -------------------
    # Owner ruling, 2026-09-07: "I often have things going from the app and website, so the
    # generations I start on the website I would like to see on the app with the usual
    # spinner." A website run is to look like an app run in the Activity window -- spinner
    # while it renders, its pictures once the mirror lands them -- and differ only by a
    # source mark.
    #
    # This REVERSES the 2026-07-06 contract the two writers above were built to keep
    # (_reconcile_job's "never invents one for a task generated on the website",
    # _log_mirrored_media's matching abstention "or every pixai.art generation would sprout a
    # new Activity row"). That was the right call while nothing on this side had anything to
    # build a row FROM; the socket's own taskUpdated frame supplies one now, so a website run
    # can be a real row instead of an unexplained arrival in the library.
    #
    # The reversal is SCOPED to the two paths that hold a live frame -- the event stream and
    # the catch-up sweep. Neither _reconcile_job nor _log_mirrored_media gained the power to
    # invent: they still touch only what they find already logged, so _watch_mirror called on
    # its own for an untracked task still writes nothing at all (pinned by
    # dev/tests/test_jobs.py::test_mirror_never_invents_a_job_for_a_task_we_do_not_track).
    #
    # THE JOB ID IS THE TASK ID, exactly as an app run's is (see _note_gen_phase's writer and
    # _reconcile_job / _log_mirrored_media, which both look a job up by str(tid)). That is the
    # whole derivation: it makes the event writer and the catch-up writer converge on ONE row
    # instead of two, and it lets every existing terminal writer close a website row without
    # needing to know such a thing exists.
    _WEBSITE_JOB_SOURCE = "pixai"     # the app's own rows carry source "web"; this is the other one
    _WEBSITE_JOB_LABEL = "From the website"
    # PixAI's task lifecycle is waiting -> running -> completed (_WS_SUBSCRIPTION's own note in
    # moonglade/backup.py). The pre-dispatch spellings are the same set core._never_dispatched()
    # keys on, so "accepted, no worker yet" means the same thing here as it does there -- and
    # that is precisely what the app's own rows record as started:false.
    _WEBSITE_QUEUED_STATUSES = ("waiting", "pending", "queued")

    def _website_job_label(frame):
        """The row's label: the prompt's first words when the frame carries any, else a plain
        "From the website".

        NOTE (2026-09-07): the live subscription does NOT ask for `parameters` --
        _WS_SUBSCRIPTION selects id/status/updatedAt/mediaId/media/priority/userId
        (moonglade/backup.py) -- so today every live frame takes the fallback. Written as a
        read of whatever the frame happens to carry rather than as a widening of that query,
        deliberately: PixAI answers a subscription it dislikes with an `error` frame, which
        _watch_events_async RAISES on, which would take the whole live mirror down. Widening
        it is a probe-first change of its own, not a side effect of this one. The catch-up's
        task nodes come through the same helper, so whichever path first carries a prompt
        gets a real label for free.

        Reads both spellings, and both nestings, for the same reason video_outputs() does: an
        i2v / reference-video task keeps its prompt inside its own block, never at the top."""
        params = (frame or {}).get("parameters")
        if not isinstance(params, dict):
            return _WEBSITE_JOB_LABEL
        text = params.get("prompts") or params.get("prompt") or ""
        if not text:
            inner = params.get("referenceVideo") or params.get("i2vPro") or {}
            if isinstance(inner, dict):
                text = inner.get("prompt") or inner.get("prompts") or ""
        words = str(text or "").split()
        if not words:
            return _WEBSITE_JOB_LABEL
        return " ".join(words[:8])[:60].rstrip() or _WEBSITE_JOB_LABEL

    def _website_job_seen(tid, ws_status, frame=None, terminal=False):
        """Give a task with NO row of its own the row the ruling above asks for, and keep the
        queued/rendering phase of one we already invented in step with the live frame.

        Reads the RAW reconstructed log rather than read_jobs(), for the same reason
        _log_mirrored_media does: a row the owner dismissed, or one already aged past
        JOBS_MAX_AGE, is still a row. Inventing a second one for that task would resurrect
        what he cleared and would be exactly the "two rows for one run" the shared job id
        exists to prevent.

        An APP run is left completely alone. It already has a row -- its Generate card
        registers one through /api/jobs the moment the gen is submitted -- so the create
        branch never fires for it, and the phase branch refuses anything whose source is not
        ours. (The one window where that is not yet true is the sliver between PixAI accepting
        an app submit and the browser's own POST landing. If a `waiting` frame wins that race
        we write the row first and the browser's POST then merges source "web" over ours --
        _reconstruct_jobs merges later events onto the current one -- so the row self-corrects
        to an app row rather than staying mislabelled.)

        `terminal` is the catch-up's case: the task finished while we were not listening, so
        there is no spinner left to run and the row is born done.

        Fails soft. This runs on the WebSocket's own event loop and in the catch-up's daemon
        thread, and neither may die because logging did."""
        from moonglade import backup as core
        try:
            tid = str(tid or "")
            if not tid:
                return
            started = str(ws_status or "").lower() not in _WEBSITE_QUEUED_STATUSES
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            j = jobs_by_id.get(tid)
            if j is None:
                if terminal:
                    # Born done -- and _log_mirrored_media then adds the media it collects to
                    # this same row, which is precisely the "job already sitting at a bare
                    # 'done'" case that helper was written for.
                    _log_job(tid, status="done", type="generate",
                             label=_website_job_label(frame), source=_WEBSITE_JOB_SOURCE)
                else:
                    _log_job(tid, status="running", type="generate",
                             label=_website_job_label(frame), source=_WEBSITE_JOB_SOURCE,
                             started=started)
                return
            # A row exists. Only ever nudge OUR OWN invention, only while it is still running,
            # and only when the phase actually changed -- the terminal writers (_reconcile_job,
            # _log_mirrored_media) own everything from done/failed onward.
            if (j.get("source") != _WEBSITE_JOB_SOURCE or j.get("dismissed")
                    or j.get("status") in _jobs._JOBS_TERMINAL
                    or bool(j.get("started")) == started):
                return
            _log_job(tid, status="running", started=started)
        except Exception:                          # noqa: BLE001 -- logging must not kill the watcher
            pass

    def _reconcile_orphan_jobs(min_age=0):
        """Ask PixAI the real status of any job still marked 'running' and resolve stale
        ones (read-only; no spend). Catches jobs orphaned when the app closed or a
        Generate card was dismissed before its poll resolved -- e.g. a task that failed
        while nobody was watching. Session is built lazily so a log with no qualifying
        running generate jobs costs nothing.

        `min_age` defaults to 0 -- check EVERYTHING immediately -- for the one-shot call
        at watcher startup (_watch_loop, below): anything still 'running' from a prior
        server session deserves an immediate look. api_jobs() below calls this on every
        poll with min_age=core.JOBS_ORPHAN_SWEEP_AGE instead, so a job only just
        submitted (still being actively polled by its own Generate card) is never asked
        about at all -- see resolve_orphan_jobs()'s and JOBS_ORPHAN_SWEEP_AGE's own
        docstrings for why 0 there would be wrong (re-checks a live video gen on every
        poll) and why --poll-timeout's 300s would ALSO be wrong (false-flags one)."""
        from moonglade import backup as core
        box = {"s": None}
        def _status(tid):
            if box["s"] is None:
                box["s"] = core._make_session(None)
            # The WHOLE dict, deliberately -- and this line has now been wrong in both
            # directions, so read before changing it.
            #
            # Originally the dict was passed through while resolve_orphan_jobs compared
            # the return against ("done","failed"): the comparison never matched, the
            # reaper resolved NOTHING, and it returned 0 forever while looking healthy.
            # The fix at the time was to send `["phase"]` instead. The reaper has since
            # been taught to accept BOTH shapes, and it now needs more than the phase: it
            # reads `started` to spot a task PixAI accepted but never dispatched (which
            # stays non-terminal for ~60min and otherwise spins silently). Sending the
            # bare string again would make that branch dead code in production while
            # every unit test around it still passed, because those call the library
            # function directly with their own stub.
            #
            # Guarded end-to-end by dev/tests/test_jobs.py's
            # test_api_jobs_endpoint_marks_a_never_started_orphan_stale, which drives the
            # real endpoint rather than the library function.
            return _task_reads.generation_status(box["s"], tid)
        try:
            _jobs.resolve_orphan_jobs(out_dir, _status, min_age=min_age)
        except Exception:                          # noqa: BLE001
            pass

    # How many recent tasks a catch-up examines. One page, deliberately: this runs unattended on
    # every reconnect, and a history walk on a flapping connection would hammer PixAI for no
    # benefit. Anything older than this page is what --sync / --update are for.
    WATCH_CATCHUP_TASKS = 30
    # THE ONE SWEEP WORKER (#60). Every trigger -- a subscribe (the first one is the startup
    # sweep), the periodic backstop -- only ASKS, through _request_catchup; one worker thread at
    # a time decides with catchup_plan and sweeps. phase: idle -> pending (a worker exists and
    # is waiting) -> running (it is reading or collecting). `_catchup_lock` guards ONLY these
    # flags: it is never held across a sleep or a network call, because _request_catchup runs on
    # the websocket's own event loop and must never block it. `started` / `ok` are the worker
    # clock's start times of the last sweep and of the last SUCCESSFUL one (a failed read is not
    # coverage); `not_before` is the settle deadline the latest subscribe set.
    _catchup_lock = threading.Lock()
    _catchup_state = {"phase": "idle", "reason": None, "rerun": False, "not_before": 0.0,
                      "started": None, "ok": None}
    # task id -> worker-clock time its collect last failed; skipped for WATCH_COLLECT_RETRY_S.
    _catchup_failed = {}

    def _spawn_daemon(fn):
        threading.Thread(target=fn, daemon=True).start()

    # The worker's clock, sleep and thread starter. Late-bound lambdas, so a patched
    # time.sleep reaches them; a test swaps them for a fake clock and an inline spawn rather
    # than patching time.monotonic, which asyncio.run reads. Exposed below.
    _catchup_env = {"clock": lambda: time.monotonic(), "sleep": lambda s: time.sleep(s),
                    "spawn": _spawn_daemon}

    def _watch_catchup(reason):
        """THE SWEEP: collect finished tasks the mirror never saw. Returns whether its read
        succeeded (the worker counts only a successful read as coverage).

        A push mirror is blind while disconnected, and reconnecting does not replay what it
        missed -- so without this, anything that completed during a drop is stranded until
        someone runs a manual sync. That is the gap; this closes it.

        Bounded and idempotent by construction: one page of recent tasks, and a task is skipped
        unless the catalog is actually missing its media. Collection goes through the SAME
        _watch_mirror the event path uses, so its single-flight guard prevents a task being
        collected twice. A task whose collect fails is left alone for WATCH_COLLECT_RETRY_S, and
        a task joins _watch_backed only after a collect that worked.

        NOT rate-limited here any more (#60): when a sweep may run is catchup_plan's decision,
        applied by _catchup_worker -- the only caller in the running app. This body is what the
        mg_watch_catchup seam drives.

        Never raises -- a failed catch-up must not kill the thread that called it."""
        from moonglade.gallery import get_row, get_row_by_task
        from moonglade.watch_plans import WATCH_COLLECT_RETRY_S
        import logging as _logging
        import time as _time
        from moonglade import backup as core
        _log = _logging.getLogger(__name__)
        try:
            session = core._make_session(None)
            # The feed's one road (core.gql: the full document, #89), as every other reader.
            data = core.gql(session, core.page_variables(
                WATCH_CATCHUP_TASKS, _pixai_client._client_of(session).user_id))
            conn = core.find_connection(data)
            edges = (conn or {}).get("edges") or []
            missed = []
            nodes = {}
            unfinished = False
            for edge in edges:
                node = edge.get("node", edge)
                tid = str(node.get("id") or "")
                _st = str(node.get("status") or "").lower()
                if _st and _st not in _task_reads._GEN_DONE and _st not in _task_reads._GEN_FAIL \
                        and _st not in ("cancelled", "canceled"):
                    unfinished = True
                if not tid or str(node.get("status") or "") not in _task_reads._GEN_DONE:
                    continue
                failed_at = _catchup_failed.get(tid)
                if failed_at is not None and \
                        _catchup_env["clock"]() - failed_at < WATCH_COLLECT_RETRY_S:
                    continue          # its collect failed moments ago; retried after the window
                # Absent from the catalog is the ONLY trigger. A task whose media is already
                # here needs nothing, and re-collecting it would be pure waste.
                #
                # Asked of the ids the catalog is actually KEYED by (2026-09-07). This test
                # used to run on media_ids_for, which is every id the summary
                # NAMES -- and on the two commonest shapes those are ids no row ever holds:
                # a batch task's `mediaId` is the composite preview grid (the members are
                # the batch), and a video task's is the poster still (the row is keyed by
                # the mp4). So the test was false forever for both, and every sweep relisted
                # the same finished tasks and re-collected them for nothing -- the owner's
                # "the app no longer picks up tracking of generations run from the website".
                # The skip-only-when-really-present ruling is unchanged; this is the id set
                # it always meant.
                if core._is_video_task_node(node):
                    # A summary names none of a video's cataloged ids, so ask by task: its
                    # video row carries this task id.
                    if get_row_by_task(db_path, tid):
                        continue
                    missed.append(tid)
                    continue
                mids = [str(m) for m in (core.cataloged_media_ids(node) or [])]
                if not mids:
                    continue
                # EVERY one, so a half-collected batch is still finished off.
                if all(get_row(db_path, m) for m in mids):
                    continue
                missed.append(tid)
                nodes[tid] = node
            if unfinished:
                # An unfinished task: an idle task stream reopens to watch it finish.
                _task_stream.request_reopen("sweep")
            if not missed:
                _log.info("live mirror: catch-up after %s -- nothing missed", reason)
                return True
            _log.warning(
                "live mirror: catch-up after %s -- %d finished task(s) are missing media "
                "from the catalog, collecting now: %s",
                reason, len(missed), ", ".join(missed[:10]))
            for tid in missed:
                # The Activity row this task never got, the socket having been down when it
                # finished (see _website_job_seen). Before the mirror, and born done.
                _website_job_seen(tid, "completed", nodes.get(tid), terminal=True)
                if _watch_mirror(tid):
                    # Backed only once collected: a late `completed` frame for it now starts
                    # no second mirror thread. A failed one is NOT backed, so the event path
                    # or a later sweep can still bring it in.
                    _watch_backed.add(tid)
                    _catchup_failed.pop(tid, None)
                else:
                    _catchup_failed[tid] = _catchup_env["clock"]()
                _time.sleep(1.0)          # paced -- be polite to their servers
            return True
        except Exception as e:
            # A failed read (PixAI's refusal, HistoryPageRefused, included) is one plain line,
            # and is not coverage: the sweep runs again on its clock.
            _log.warning("live mirror: catch-up after %s failed: %s: %s",
                         reason, type(e).__name__, _redact_host_paths(str(e))[:200])
            return False

    # Test seam (same rationale as mg_watch_mirror above): the self-heal sweep is a closure
    # only ever called from the watcher thread, which the suite disables (MOONGLADE_DISABLE_WATCH).
    # Exposing it lets a test drive the gap-fill / skip / rate-limit BEHAVIOUR end to end, not
    # just grep the source for its guardrails.
    app.extensions["mg_watch_catchup"] = _watch_catchup

    def _request_catchup(reason):
        """Ask for a sweep. NON-BLOCKING: called from _watch_on_event on the websocket's own
        event loop, so it takes the flag lock for a moment and at most starts the one worker.

        A connect ("startup" for the first subscribe, "reconnect" after a drop) pushes the
        settle deadline out to WATCH_SUBSCRIBE_SETTLE after now. If a worker is pending, the
        request is absorbed -- that worker reads after this deadline, so after this subscribe --
        and a connect upgrades a pending periodic sweep to a connect one (never skipped). If a
        worker is running, a connect sets `rerun`: the gap it opened is read once more when the
        current sweep finishes. A periodic ask while anything is pending or running is moot."""
        from moonglade.watch_plans import WATCH_SUBSCRIBE_SETTLE
        env = _catchup_env
        with _catchup_lock:
            if reason != "periodic":
                _catchup_state["not_before"] = max(_catchup_state["not_before"],
                                                   env["clock"]() + WATCH_SUBSCRIBE_SETTLE)
            phase = _catchup_state["phase"]
            if phase == "running":
                if reason != "periodic":
                    _catchup_state["rerun"] = True
                return
            if phase == "pending":
                if reason != "periodic":
                    _catchup_state["reason"] = reason
                return
            _catchup_state.update(phase="pending", reason=reason)
        try:
            env["spawn"](_catchup_worker)
        except Exception:                          # noqa: BLE001 -- a thread that never started
            with _catchup_lock:                    # must not leave `pending` wedged forever
                _catchup_state.update(phase="idle", reason=None)

    def _catchup_worker():
        """The one sweep worker -- see _catchup_state. Decides with the pure catchup_plan under
        the flag lock, then sleeps or sweeps with the lock RELEASED.

        It goes idle INSIDE the same locked block that decides it is finished: a request that
        arrives after that block starts a new worker, and one that arrives before it sees
        `running` and sets `rerun`, which that block reads. No gap in between can lose a
        request. An unexpected crash still leaves the phase idle (the `finally`), so it can
        never wedge every later request behind a worker that no longer exists."""
        from moonglade.watch_plans import catchup_plan
        env = _catchup_env
        finished = False
        try:
            while True:
                with _catchup_lock:
                    reason = _catchup_state["reason"]
                    verdict, wait = catchup_plan(reason, env["clock"](),
                                                 _catchup_state["started"], _catchup_state["ok"],
                                                 _catchup_state["not_before"])
                    if verdict == "skip":
                        _catchup_state.update(phase="idle", reason=None, rerun=False)
                        finished = True
                        return
                    if verdict == "run":
                        started = env["clock"]()
                        _catchup_state.update(phase="running", rerun=False, started=started)
                if verdict == "wait":
                    env["sleep"](wait)
                    continue
                ok = _watch_catchup(reason)
                with _catchup_lock:
                    if ok:
                        _catchup_state["ok"] = started
                    if _catchup_state["rerun"]:
                        _catchup_state.update(phase="pending", reason="reconnect", rerun=False)
                        continue
                    _catchup_state.update(phase="idle", reason=None, rerun=False)
                    finished = True
                    return
        finally:
            if not finished:
                with _catchup_lock:
                    _catchup_state.update(phase="idle", reason=None, rerun=False)

    # Test seams for the worker (#60): the request entry point, its state, and its clock /
    # sleep / spawn, so a test drives the coalescing on a fake clock with an inline worker.
    app.extensions["mg_watch_request_catchup"] = _request_catchup
    app.extensions["mg_watch_catchup_state"] = _catchup_state
    app.extensions["mg_watch_catchup_env"] = _catchup_env

    def _periodic_catchup():
        """Backstop for the connect-triggered sweeps, which fire off a WS lifecycle event --
        so a connection that stays nominally "subscribed" for a long stretch never gets a fresh
        sweep. Found live: PixAI's personalEvents push simply did not fire for an
        app-submitted generation (a website-submitted one, same session, did) -- no error, no
        disconnect, nothing to react to, so reconnect-triggered catch-up alone left it
        undiscovered. This loop asks the same worker on a fixed clock, so discovery never
        depends entirely on the socket's own reconnect cadence."""
        from moonglade.watch_plans import WATCH_CATCHUP_MIN_GAP
        import time as _time
        while True:
            _time.sleep(WATCH_CATCHUP_MIN_GAP)
            _request_catchup("periodic")

    # Task ids already mirrored this process's lifetime (a 'completed' event can repeat, and
    # a reconnect can replay one). Process-scoped, not per-connection: it lived inside
    # _watch_loop before 2026-09-07 and meant exactly this then too.
    _watch_backed = set()
    # Test seam (#60): the sweep adds a task here only after a collect that worked.
    app.extensions["mg_watch_backed"] = _watch_backed

    def _watch_inbox(ev):
        """Sessions R + Y (R4b): the socket's `newNotification` bumps the gift box's badge, and
        a (re)subscribe is when the client re-reads the count. Counted in moonglade.inbox's
        memory -- a push by its id only, never its title -- and carried to every open tab by
        /api/jobs. No network here (this runs on the socket's event loop), and it can never
        be the mirror's problem."""
        try:
            from moonglade import inbox as moonglade_inbox
            if ev.get("__meta__") == "subscribed":
                moonglade_inbox.note_connected()
            elif ev.get("newNotification"):
                moonglade_inbox.note_push(ev.get("newNotification"))
        except Exception:                                  # noqa: BLE001
            pass

    def _watch_on_event(ev):
        """Everything the live mirror does with ONE frame off the socket.

        Lifted out of _watch_loop's inner `while True` on 2026-09-07 -- same body, same
        order, now a closure a test can call directly. The reason it had to move is the
        website-row ruling of that day: the row is written HERE, off the frame, and the rule
        that a website run must be indistinguishable from an app run in the Activity window
        is a claim about a SEQUENCE of frames (waiting -> running -> completed + the mirror
        receipt), which nothing could exercise while this lived in a background thread's
        inner loop. dev/tests/test_watch.py's fake event stream drives it through the
        mg_watch_on_event seam; the source-level pin on the collect/reconcile agreement moved
        with it."""
        import logging as _logging
        import time as _time
        from moonglade import backup as core
        _log = _logging.getLogger(__name__)
        _watch_inbox(ev)
        if ev.get("__meta__") == "subscribed":
            with _watch_lock:
                _watch_status["connected"] = True
                _watch_status["last_error"] = None
                _watch_status["connected_at"] = _time.time()
                after_a_drop = _watch_status["last_close_at"] is not None
            _log.info("live mirror: connected and subscribed")
            # Every connect covers a window we were blind for: the gap since the last
            # connection ended, or -- on the first one -- the whole time the app was closed
            # (this IS the startup sweep; it no longer has a thread of its own). "Subscribed"
            # means the subscribe frame was SENT; PixAI acknowledges nothing, so the sweep
            # waits WATCH_SUBSCRIBE_SETTLE before it reads (see that constant for what is and
            # is not covered). Never skipped, never blocking: _request_catchup only sets a
            # flag or starts the one worker, because this runs on the websocket's event loop.
            _request_catchup("reconnect" if after_a_drop else "startup")
            return
        tu = ev.get("taskUpdated")
        if not tu:
            return
        with _watch_lock:
            _watch_status["events_seen"] += 1
            _watch_status["last_event_at"] = _time.time()
        status = tu.get("status")
        tid = str(tu.get("id") or "")
        # The website run's own Activity row (owner ruling 2026-09-07) -- FIRST, and
        # synchronously on this callback. The mirror thread started just below records what
        # it collected through _log_mirrored_media, which writes only for a task that
        # ALREADY has a row, so the row has to exist before that thread does. An app run
        # already has one and is left untouched; see _website_job_seen.
        if tid:
            _website_job_seen(tid, status, tu)
        # `in _GEN_DONE`, not `== _WS_DONE_STATUS`. This branch used to match ONE
        # exact string while the reconcile branch below accepts five, off the same
        # event -- so a done-status PixAI spells any other way would skip mirroring
        # while still resolving the Activity row. Every task checked on 2026-07-26
        # reports "completed", so this was not that day's cause, but the asymmetry
        # produces exactly that symptom and is just as invisible.
        if status in _task_reads._GEN_DONE and tid and tid not in _watch_backed:
            _watch_backed.add(tid)
            _log.info("live mirror: task %s reported %s -- mirroring", tid, status)
            threading.Thread(target=_watch_mirror, args=(tid,), daemon=True).start()
        # Reconcile the Activity log from the SAME event stream, so a job resolves
        # even if the Generate card that was polling /api/task-status is gone.
        if tid and (status in _task_reads._GEN_DONE or status in _task_reads._GEN_FAIL):
            _reconcile_job(tid, status)

    # Test seam (same rationale as mg_watch_mirror / mg_watch_catchup above): the frame
    # handler is only ever called from the WebSocket the suite never opens.
    app.extensions["mg_watch_on_event"] = _watch_on_event

    def _stream_session():
        """The REST task stream's client: the API key presenting as the website (design 4
        item 2). Never the Mirror JWT, which is reserved for the create POST."""
        from moonglade import backup as core
        return _mirror.present_as_web(core._make_session(None))

    # The stream's frames reach the SAME handler the socket's taskUpdated frames did.
    _task_stream = _task_feed.TaskStream(
        make_session=_stream_session,
        on_task=lambda frame: _watch_on_event({"taskUpdated": frame}),
        request_catchup=lambda reason: _request_catchup(reason),
        status=_watch_status["task_stream"], lock=_watch_lock)
    app.extensions["mg_task_stream"] = _task_stream

    def _watch_cycle(state):
        """ONE connection's life: connect, run until it ends, record how it ended, and wait as
        long as watch_reconnect_plan says. `state` carries what outlives a connection -- the
        backoff -- plus the clock and sleep, passed in so a test drives cycles on a fake clock
        (asyncio.run reads time.monotonic, so that is never patched).

        Every way a connection ends goes through the same rule (#60): before, a drop with no
        close frame never reset the backoff, so after a few of PixAI's batch drops every
        reconnect waited 60 s, while a clean end logged the climbed number and waited 5.

        The mirror's state used to exist ONLY in _watch_status, in memory, readable solely
        through /api/watch/status while the process lived. So when a generation failed to
        mirror there was no way to answer "was it connected at the time?" -- not from the log,
        not afterwards, not at all. Every transition below is recorded in
        local/logs/moonglade.log. Transitions and mirrored tasks only, never per-event:
        this stream can carry a lot of traffic and a per-event line would bury the signal."""
        from moonglade.watch_plans import watch_close_info, watch_reconnect_plan
        import asyncio
        import logging as _logging
        import time as _time
        from moonglade import backup as core
        _log = _logging.getLogger(__name__)
        clock = state["clock"]
        attempt = {"subscribed_at": None}

        def _on(ev):
            if ev.get("__meta__") == "subscribed":
                attempt["subscribed_at"] = clock()
            # The frame handler itself is _watch_on_event, above -- see its docstring for
            # why it is a create_app closure rather than a nested one.
            _watch_on_event(ev)

        err = ""
        try:
            # _make_session raises PixAIError (caught below) when no credentials
            # are configured -- it never returns a session with a blank auth
            # header, so there's nothing else to check here before subscribing.
            session = core._make_session(None)
            auth = session.headers.get("Authorization")
            asyncio.run(_task_feed._watch_events_async(auth, _on, None))
            close = {"kind": "clean"}
        except core.WatchStaleError as e:
            # core._watch_events_async's own recv() timeout fired: the socket
            # reported no error and `connected` was already True, but nothing --
            # not even a keepalive ping -- arrived for core._WS_STALE_TIMEOUT
            # seconds. This is the exact failure this watchdog exists for (see
            # the module docstring above): a connection that LOOKS healthy on
            # every existing signal while silently seeing nothing. Recorded in
            # its own counter/timestamp, distinct from `last_error`'s generic
            # reconnect noise, so this specific failure mode stays visible in
            # /api/watch/status instead of looking like an ordinary drop.
            with _watch_lock:
                _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
                _watch_status["stale_reconnects"] += 1
                _watch_status["last_stale_reconnect_at"] = _time.time()
            close = {"kind": "stale"}
        except Exception as e:
            err = "{}: {}".format(type(e).__name__, _redact_host_paths(str(e))[:200])
            with _watch_lock:
                _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
            close = watch_close_info(e, _redact_host_paths)
        sub = attempt["subscribed_at"]
        lived = (clock() - sub) if sub is not None else None
        # A stale connection had subscribed and lived a full stale window, so the rule treats it
        # as healthy and reconnects at once -- the Panel no longer reads "Reconnecting" for a
        # whole minute after one.
        wait, state["backoff"] = watch_reconnect_plan(state["backoff"], lived)
        with _watch_lock:
            _watch_status["connected"] = False
            _watch_status["last_close_at"] = _time.time()
            _watch_status["last_close"] = close
            _watch_status["last_connection_s"] = round(lived) if lived is not None else None
            _watch_status["reconnects"] += 1
        age = "{}s".format(round(lived)) if lived is not None else "before subscribing"
        if close["kind"] == "clean":
            _log.info("live mirror: disconnected cleanly after %s -- reconnecting in %ss",
                      age, wait)
        elif close["kind"] == "stale":
            # WARNING, not info: this is the failure mode where the socket looked healthy
            # on every signal while seeing nothing. Since #60 the catch-up after the
            # reconnect reads back whatever finished during the silence.
            _log.warning("live mirror: socket went silent (no traffic for %ss) -- "
                         "reconnecting in %ss; the catch-up reads back anything that "
                         "completed during the silence.",
                         getattr(_task_feed, "_WS_STALE_TIMEOUT", "?"), wait)
        else:
            _log.warning("live mirror: %s (close %s) after %s -- reconnecting in %ss",
                         err, close.get("code") if close.get("kind") == "closed"
                         else close.get("kind"), age, wait)
        state["sleep"](wait)

    # Test seams (#60): one connection's life on a fake clock, and the status it writes.
    app.extensions["mg_watch_cycle"] = _watch_cycle
    app.extensions["mg_watch_status"] = _watch_status

    def _watch_loop():
        from moonglade.watch_plans import WATCH_BACKOFF_FIRST
        import logging as _logging
        import time as _time
        _log = _logging.getLogger(__name__)
        with _watch_lock:
            _watch_status["started_at"] = _time.time()
        _log.info("live mirror: starting")
        _reconcile_orphan_jobs()   # clear any job left hanging at 'running' from a prior session
        # No separate startup sweep (#60): the first subscribe asks the one sweep worker for it,
        # and it reads after the subscription is live rather than racing it.
        threading.Thread(target=_periodic_catchup, daemon=True).start()
        threading.Thread(target=_task_stream.run, daemon=True).start()
        state = {"backoff": WATCH_BACKOFF_FIRST, "clock": _time.monotonic,
                 "sleep": _time.sleep}
        while True:
            _watch_cycle(state)

    def _contest_sync_startup():
        """One contest detection sweep shortly after boot. Entries made on pixai.art, and
        any win decided while the app was closed, are invisible to this process until
        something reads them back -- and startup is the only moment guaranteed to follow
        such a gap. Sleeps first so it never competes with the app's own boot work, and goes
        through the same single-flight wrapper every other trigger uses, so a manual sync
        and this one can never overlap. No `force`: at boot there is no specific entry to
        confirm, so the recent window is exactly the right bound."""
        time.sleep(_contest_sync._CONTEST_SYNC_STARTUP_DELAY)
        _contest_sync._contest_sync_kick(out_dir)

    def _artworks_sync_startup():
        """THE BOOT KICK -- one published-artwork sweep shortly after start.

        This is the trigger that answers the incident the whole living library was scoped
        from: a piece published from the app vanished from My Art because nothing on the
        machine ever re-read PixAI's list of published works. Publishing is written to the
        LOCAL catalog only, so the other install learns of it exactly when something reads
        PixAI back -- and startup is the one moment guaranteed to follow a gap in which the
        app was closed.

        Sleeps past the contest sweep's own delay so the two never compete at boot, and
        goes through the same single-flight wrapper every other trigger uses. No `force`:
        at boot there is no specific publish to confirm, so the recent-guard is exactly the
        right bound, and a restart loop cannot become a request storm. Scheduled: starting
        the app is not asking for a sweep, so it announces itself in the Activity window
        and nowhere else (owner's walk, 2026-09-07)."""
        time.sleep(_living.ARTWORKS_STARTUP_DELAY)
        _artworks_kick(force=False, scheduled=True)

    # MOONGLADE_DISABLE_WATCH=1 skips auto-start -- set by the test suite's conftest so
    # create_app() (called by ~every test) never opens a real WebSocket to PixAI using
    # whatever real credentials happen to be in this machine's config.json. The contest
    # sweep rides the SAME gate rather than inventing a second env var: it is background
    # work that reaches PixAI with those same real credentials, which is the entire reason
    # that gate exists.
    if os.environ.get("MOONGLADE_DISABLE_WATCH") != "1":
        threading.Thread(target=_watch_loop, daemon=True).start()
        threading.Thread(target=_contest_sync_startup, daemon=True).start()
        threading.Thread(target=_artworks_sync_startup, daemon=True).start()

    # -- provided to ctx (split_move) --
    ctx.PANEL_ACTIONS = PANEL_ACTIONS
    ctx._LIVING_STALE_ACTIONS = _LIVING_STALE_ACTIONS
    ctx._artworks_job_busy = _artworks_job_busy
    ctx._artworks_kick = _artworks_kick
    ctx._asset_job = _asset_job
    ctx._collect_single_flight = _collect_single_flight
    ctx._export_dir = _export_dir
    ctx._export_job = _export_job
    ctx._export_lock = _export_lock
    ctx._job_busy = _job_busy
    ctx._living_runnable = _living_runnable
    ctx._load_sched = _load_sched
    ctx._log_job = _log_job
    ctx._panel_job = _panel_job
    ctx._panel_lock = _panel_lock
    ctx._panel_run = _panel_run
    ctx._reconcile_orphan_jobs = _reconcile_orphan_jobs
    ctx._save_sched = _save_sched
    ctx._sched_lock = _sched_lock
    ctx._standing_action = _standing_action
    ctx._standing_runnable = _standing_runnable
    ctx._task_stream = _task_stream
    ctx._update_busy = _update_busy
    ctx._update_busy_refusal = _update_busy_refusal
    ctx._watch_lock = _watch_lock
    ctx._watch_status = _watch_status
    # -- end --

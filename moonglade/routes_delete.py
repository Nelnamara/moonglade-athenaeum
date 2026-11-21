"""moonglade/routes_delete.py -- the delete routes: the per-image cloud delete (preview, then
confirm against the plan the preview showed), the local delete, the bulk task delete's preview
and its off-thread single-flight run, and the Trash panel (list, restore, delete forever, empty),
with their helpers and the bulk delete's lock.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was. Names the block reads from create_app's setup, the
front door and the background block (the job log, the host-path redactor) come in through ctx
(the bound-from-ctx lines below), so every closure on both sides holds the one same object.
gallery's own names are imported inside the function that reads them, at call time, so a test's
patch of moonglade.gallery still reaches the route.
"""
import threading
import time

from flask import jsonify, request

from moonglade import cloud_delete as _cloud_delete
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.web_tiers import LOCALHOST, LOGIN, tier
    # -- bound from ctx (split_move) --
    _log_job = ctx._log_job
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    thumb_dir = ctx.thumb_dir
    # -- end --

    # Bulk cloud-delete runs OFF-THREAD (it's irreversible and can be many network calls)
    # and reports to the Activity card via the job log. Single-flight so two runs can never
    # interleave their deletes.
    _bulkdel_lock = threading.Lock()
    _bulkdel_running = {"on": False}

    def _batch_sibling_count(task_id):
        """How many catalog rows share this task, for the Details view's own display.

        NOT what the delete dialog is worded from -- that has to come from the live read
        (/api/delete-image with confirm false), because this number counts LOCAL rows and
        cannot see a sibling deleted from PixAI's own website."""
        from moonglade.catalog_verbs import task_media_count
        return task_media_count(db_path, task_id)

    def _delete_image_rows(plan, task_id, media_id):
        """Which catalog rows this delete takes with it, as [{media_id, filename}].

        Per-image: the one named image. Whole-task: every row of the task EXCEPT the ones
        whose image PixAI had already deleted -- their local copy is the only copy left
        anywhere, and removing the generation record on PixAI does not change that. The
        branch comes off the plan the delete itself reported, never off a local count."""
        from moonglade.catalog_verbs import task_media
        from moonglade.catalog import get_row
        if plan.plan == "per-image":
            row = get_row(db_path, media_id) or {}
            return [{"media_id": media_id, "filename": row.get("filename") or ""}]
        if plan.plan == "whole-task":
            keep = {str(m) for m in plan.keep_media}
            return [{"media_id": str(r["media_id"]), "filename": r.get("filename") or ""}
                    for r in task_media(db_path, task_id)
                    if str(r["media_id"]) not in keep]
        return []

    def _delete_image_message(plan, rows, task_id=""):
        """The dialog's own words, in plain language, off the live read.

        Every number here is PixAI's answer about this task, never a count of local rows --
        save one fallback: when the live read carried no artworkIds at all, whether the
        generation is published comes from the catalog's artwork_id over the task's whole
        membership (SCOPE_2026-09-26 E5). Only the whole-task branch says anything about
        published artwork: that branch sends the whole-task delete, the delete PixAI's
        contract says takes the linked artwork with it. What a one-image deleteBatchMedia
        does to an artwork is unknown, so the per-image branch makes no claim."""
        from moonglade.gallery import Path
        from moonglade.catalog_verbs import myart_coverage, published_delete_note, task_media
        if plan.plan == "per-image":
            n = plan.live_siblings
            return ("This removes only this image from PixAI. {} other image{} in its "
                    "batch stay.".format(n, "" if n == 1 else "s"))
        if plan.plan == "whole-task":
            names = [Path(r["filename"] or r["media_id"]).name for r in rows]
            shown = ", ".join(names[:6]) + (
                " and {} more".format(len(names) - 6) if len(names) > 6 else "")
            msg = ("This is the last image of its generation on PixAI, so PixAI removes "
                   "the whole generation record. Locally, {} file{} move{} to your trash "
                   "folder: {}.".format(len(names), "" if len(names) == 1 else "s",
                                        "s" if len(names) == 1 else "", shown))
            if plan.keep_media:
                msg += (" The {} image{} of this generation you already deleted on PixAI "
                        "stay here — your copy is the only one left.".format(
                            len(plan.keep_media),
                            "" if len(plan.keep_media) == 1 else "s"))
            members = task_media(db_path, task_id) if task_id else []
            if plan.artwork_ids is not None:
                # Capped at the task's size ON PIXAI, never at the rows this library holds:
                # the delete takes PixAI's whole batch, and a library missing some of its
                # images must not under-count what may go with it. On this branch that batch
                # is this, the last live image, plus every member already deleted there.
                published = min(len(plan.artwork_ids),
                                max(1, len(members), len(plan.keep_media) + 1))
                unchecked = False
            else:
                published = sum(1 for r in members if str(r.get("artwork_id") or "").strip())
                unchecked = not myart_coverage(db_path)["artworks"]
            note = published_delete_note(published, unchecked)
            if note:
                msg += " " + note
            return msg
        return plan.reason

    @app.route("/api/delete-image", methods=["POST"])
    @tier(LOCALHOST)
    def api_delete_image():
        """Delete ONE image from its task on PixAI -- in TWO phases, ask then act.

        The finer-grained partner to /delete-tasks-bulk, which is task-level: deleting any
        image there takes the whole batch. Same trust tier and for the same reason --
        LOCALHOST-only, because this destroys on the owner's real cloud account, and a
        logged-in LAN session unlocks browsing and spending, not irreversible deletion.

        `POST {media_id, confirm: false}` is the PREVIEW: it reads the live task and answers
        `{plan, reason, live_siblings, local_rows, message}` with nothing deleted. The dialog
        is worded from THAT answer. It has to be: which mutation PixAI accepts, and how many
        images of the batch survive, are facts only PixAI holds -- the local catalog cannot
        see a sibling deleted from PixAI's own website, and for years this dialog promised
        "the rest of its batch stays" on deletes that took the whole generation.

        `POST {media_id, confirm: true, plan}` DELETES. It reads and routes again, and
        refuses when the fresh plan differs from the one the dialog showed, so the user
        cannot be made to agree to one thing and get another. `confirm` must be present
        either way: the typed-DELETE prompt is the client's half of the same gate, and a
        route that acted on a body without it would make that prompt decorative.

        Local purge follows the cloud delete, exactly as the task-level path does, so cloud
        and catalog never drift. Order matters: if the cloud call fails, nothing local is
        touched and the image is still there to try again. WHICH rows go is the plan's to
        say (`_delete_image_rows`), never this route's to re-derive from local counts.

        A CONFIRMED delete writes one Activity row (`del-<hex>`, `type: "delete"`) -- owner's
        walk 2026-09-07, "single delete did NOT show in the Activity tracker". A bulk delete
        has written one since it existed (`_start_bulk_delete`'s `bulkdel-<hex>`), so the
        finer-grained partner writes the same kind of row for the same event, and this
        library's whole record of what left it stops depending on which button was used. The
        PREVIEW writes nothing: nothing happened, and a row per dialog-open is noise.
        """
        from moonglade.gallery import purge_media_local
        from moonglade.catalog_verbs import mark_cloud_deleted
        from moonglade.catalog import get_row
        from moonglade import backup as core          # lazy: avoid import cycle
        import uuid
        body = request.get_json(silent=True) or {}
        if "confirm" not in body:
            return jsonify({"error": "not confirmed"}), 400
        preview = not body.get("confirm")

        def _log_delete(status, label, error=None):
            """The one Activity row this delete leaves behind.

            Born terminal, unlike the bulk delete's two events: a single delete is one
            mutation and there is no progress to report between them. Everything else follows
            _start_bulk_delete exactly -- `type: "delete"` so the tray labels it Delete, and
            NO `scheduled` field, because the owner pressed this button and a job you press
            toasts its outcome (jobsStore.js's toastTransitions swallows only `scheduled`
            rows). `media_ids` carries the one image so the row can show its thumbnail, and it
            is written BEFORE the local purge, while that thumbnail is still on disk.

            Never on the preview -- callers check that themselves rather than this swallowing
            it, so the one caller that must not log reads as a decision at its own call site.
            """
            _log_job("del-" + uuid.uuid4().hex[:12], status=status, type="delete",
                     label=label, error=error, media_ids=[mid] if mid else None)
        mid = str(body.get("media_id") or "").strip()
        row = get_row(db_path, mid) if mid else None
        if not row:
            return jsonify({"error": "No such image in the catalog."}), 200
        tid = str(row.get("task_id") or "").strip()
        if not tid:
            # An imported local file has no PixAI task behind it, so there is nothing on
            # their side to delete. Saying so beats a confusing API error, and points at the
            # control that DOES apply to it.
            return jsonify({"error": "This image was imported from your computer \u2014 PixAI "
                                     "has no copy to delete. Use Delete to remove it here."}), 200
        if not preview and not str(body.get("plan") or "").strip():
            # A confirm carries the plan it confirms. Without one there is nothing to hold
            # the fresh read against, so it is refused here, before any call to PixAI.
            return jsonify({"error": _cloud_delete.NO_CONFIRMED_PLAN, "plan": "refuse"}), 400
        try:
            # _make_session takes a REQUIRED positional; every other call site in this
            # file passes None. Omitting it raised TypeError on every click, which the
            # except below turned into a 200 error body -- so the feature was dead while
            # looking like a PixAI-side failure.
            _core_session = core._make_session(None)
            if preview:
                plan = _cloud_delete.plan_image_delete(_core_session, tid, mid)
            else:
                plan = _cloud_delete.delete_image_routed(_core_session, tid, mid,
                                                confirmed_plan=body.get("plan") or None)
        except Exception as e:                        # noqa: BLE001
            line = _redact_host_paths(str(e))[:240]
            if not preview:
                # A delete he pressed that came back with an error is exactly the outcome the
                # tracker must not be silent about -- READ_ONLY, a PixAI 500, a lost token.
                _log_delete("failed", "PixAI delete failed", error=line)
            return jsonify({"error": line}), 200

        # The read this plan was made from is the only place the app learns that PixAI has
        # dropped an image, so every row it names is marked here -- on the preview as much as
        # on the confirm, and whichever branch the plan took. Nothing local is removed by it:
        # a marked row is one whose local copy is now the only copy anywhere, and it stays.
        # It cannot be left to --backfill-full-meta, which only re-fetches a row missing its
        # prompt or model detail: a complete row is never revisited, so in the ordinary case
        # that pass would never set this at all.
        for gone_media, when in plan.keep_media_deleted_at:
            mark_cloud_deleted(db_path, gone_media, when)

        if plan.plan == "refuse":
            answer = {"plan": "refuse", "reason": plan.reason, "live_siblings": 0,
                      "local_rows": [], "message": plan.reason}
            if not preview:
                answer["error"] = plan.reason
                # A refusal is a real outcome of a button he pressed, not a non-event: the
                # image is still on PixAI and the row says in the plan's own words why.
                _log_delete("failed", "Refused: " + plan.reason, error=plan.reason)
            return jsonify(answer), 200

        rows = _delete_image_rows(plan, tid, mid)
        if preview:
            return jsonify({"plan": plan.plan, "reason": plan.reason,
                            "live_siblings": plan.live_siblings,
                            "local_rows": [r["media_id"] for r in rows],
                            "message": _delete_image_message(plan, rows, tid)})

        # The cloud delete has already fired and cannot be taken back, so the row goes in now
        # -- what it records is what PixAI did, in the plan's own words. A local purge that
        # fails afterwards is a different fact and comes back through this route's own error
        # contract; it does not make the PixAI delete un-happen, so it does not rewrite this.
        _log_delete("done", "Deleted 1 image from PixAI" if plan.plan == "per-image"
                    else "Deleted the whole generation from PixAI (last image)")

        purged, failed = [], []
        for r in rows:
            try:
                purge_media_local(out_dir, thumb_dir, db_path, r["media_id"], r["filename"])
                purged.append(r["media_id"])
            except OSError as e:
                # The cloud delete above already happened and cannot be taken back, so a
                # local purge that fails has to come back through this route's own error
                # contract rather than a 500: the row (and the file) are still here, now
                # pointing at an image PixAI no longer has, and only the user can decide to
                # retry. The loop keeps going -- one file the OS will not release must not
                # strand the rest of a whole-task purge.
                failed.append(_redact_host_paths(str(e))[:160])
        try:                                     # The Great Sweep: each removed picture once
            _telemetry.telem_set_add_many("culled_keys", ["media:" + m for m in purged], out_dir=out_dir)
        except Exception:                        # noqa: BLE001
            pass
        if failed:
            return jsonify({"error": "Deleted on PixAI, but {} local file{} could not be "
                                     "moved to the trash folder: {}".format(
                                         len(failed), "" if len(failed) == 1 else "s",
                                         "; ".join(failed[:3])),
                            "plan": plan.plan, "local_rows": purged}), 200
        return jsonify({"ok": True, "media_id": mid, "task_id": tid, "plan": plan.plan,
                        "local_rows": purged})

    @app.route("/api/delete-local", methods=["POST"])
    @tier(LOGIN)
    def api_delete_local():
        """JSON twin of /delete-bulk (and /delete/<id>) for fetch()-driven clients:
        quarantine the selected media to out_dir/_deleted/ through the SAME
        purge_media_local path the page routes use, so /api/trash/restore undoes it,
        minus the redirect-with-banner plumbing. LOGIN tier, exactly like the page
        routes it mirrors: local quarantine is reversible library curation, not
        cloud destruction (that is /api/delete-tasks, a different tier). The page
        routes stay -- classic still posts forms at them.

        Deduped via dict.fromkeys for the same reason /api/delete-preview does it:
        the count describes FILES quarantined, so a repeated id must not inflate it.
        Per-file OSError keeps the loop going, exactly as /delete-bulk's does -- one
        file the OS won't release must not strand the rest -- and comes back as a
        `failed` count with ok=false instead of a delerr banner.

        ARCHIVE-ONLY PICTURES: WARN, DON'T BLOCK (#66; the owner's ruling on the 2026-10-03
        walk -- keeping them back was tedious). A row PixAI no longer has (is_archive_only)
        holds the only copy anywhere, and it goes with the rest: the Trash's Restore puts the
        file AND its whole catalog row back (restore_quarantined_media, from the snapshot
        purge_media_local writes first). What the bulk confirm needs is the count BEFORE it
        asks, so `preview: true` answers {"preview": true, "count", "archive_only"} -- the rows
        the delete would take and how many of them are the only copy -- and touches nothing."""
        from moonglade.gallery import purge_media_local
        from moonglade.catalog import get_row, is_archive_only
        body = request.get_json(silent=True) or {}
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        if body.get("preview") is True:
            rows = [r for r in (get_row(db_path, m) for m in media_ids) if r]
            return jsonify({"preview": True, "count": len(rows),
                            "archive_only": sum(1 for r in rows if is_archive_only(r))})
        purged, failed = [], 0
        for mid in media_ids:
            row = get_row(db_path, mid)
            if not row:
                continue
            try:
                purge_media_local(out_dir, thumb_dir, db_path, mid, row.get("filename"))
                purged.append(mid)
            except OSError:
                failed += 1
        try:              # The Great Sweep: each removed picture once (a restore + re-delete is one)
            _telemetry.telem_set_add_many("culled_keys", ["media:" + m for m in purged], out_dir=out_dir)
        except Exception:                                    # noqa: BLE001
            pass
        return jsonify({"ok": failed == 0, "count": len(purged), "failed": failed})

    def _purge_local(media_id, filename):
        """Remove a media's catalog row + thumbnail; quarantine its file to _deleted/
        (recoverable) rather than destroying it."""
        from moonglade.gallery import purge_media_local
        purge_media_local(out_dir, thumb_dir, db_path, media_id, filename)

    def _rows_the_bulk_purge_must_keep(session, task_id, rows):
        """Which of one task's local rows the bulk delete must leave exactly where they are.

        The same rule the single-image path follows through ImageDeletePlan.keep_media, and
        it is here for the same reason: an image the owner deleted on PixAI's own website is
        gone THERE, so this library's copy is the only one left anywhere. PixAI removing the
        generation record does not change that, and neither does deleting its siblings --
        so those rows and their files stay, and the whole-task purge walks around them.

        Two sources, deliberately both:
          * the live task, read once here. It fails SOFT: a read that could not be made must
            never WIDEN what a purge takes, so a blip leaves the catalog's own answer standing
            rather than replacing it with silence.
          * `cloud_deleted_at` on the rows themselves, which stands whether or not the read
            worked -- it was written the last time the app read this task.

        The read is also where the marker gets WRITTEN: every member PixAI reports deleted
        has its own row stamped here, so the catalog learns it from the read the delete was
        making anyway rather than from a network call of its own.

        Returns a set of media ids. Called BEFORE the cloud delete fires -- afterwards the
        generation record is gone and there is nothing left to read."""
        from moonglade.catalog_verbs import mark_cloud_deleted
        from moonglade import backup as core   # lazy: avoid import cycle
        keep = {str(r["media_id"]) for r in rows
                if str(r.get("cloud_deleted_at") or "").strip()}
        try:
            task = _task_reads.task_detail_gql(session, str(task_id)) if session is not None else None
        except Exception:                            # noqa: BLE001 -- fail soft, see above
            task = None
        batch = ((task or {}).get("outputs") or {}).get("batch")
        for mid in _cloud_delete.deleted_batch_media(batch):
            keep.add(str(mid))
            stamp = str((_cloud_delete.batch_entry(batch, mid) or {}).get("deletedAt") or "")
            if stamp:
                mark_cloud_deleted(db_path, mid, stamp)
        return keep

    def _preview_live_gone(task_ids):
        """Ask PixAI, once per task, which of these tasks' images it has already dropped.

        The preview's whole job is to say what "Delete from PixAI" would take before it
        fires, and until 2026-09-07 it answered entirely from the local catalog -- which
        cannot know about an image the owner deleted on PixAI's own website. The delete
        itself has always known (_rows_the_bulk_purge_must_keep reads every task and keeps
        those rows back), so the preview over-reported the blast radius against the one
        thing it was supposed to describe exactly. This is that same read, moved forward.

        Read-only ON PIXAI, and it stays that way: getTaskById, nothing else. It does
        write `cloud_deleted_at` on the rows the read finds already deleted, exactly as
        the delete's own read does (mark_cloud_deleted) -- REFINING this function's own
        2026-09-07 note, which held that a confirm dialog the owner may well cancel is no
        place to mutate the catalog from. It is, for this one column. The preview's whole
        promise is "that file stays in your backup, because this is the last copy of it
        anywhere", and a promise made from an answer nobody wrote down is only as good as
        the SECOND read that has to be made at delete time: if that one fails where this
        one succeeded, _rows_the_bulk_purge_must_keep falls back to the catalog, finds
        nothing, and purges the very rows this dialog named. Stamping here makes the
        catalog the one place both reads answer from, so the preview can only ever become
        a source of the same truth, never a different one. The stamp is not a deletion and
        does not become one if the owner cancels: `cloud_deleted_at` records what PIXAI
        did to its own copy, which is true whatever this dialog decides, and every path
        that reads it (the keep-back, the single-image plan) only ever keeps a row.

        FAILS SOFT, and in the SAFE direction. A task whose read raises, comes back
        empty, or never answers inside the budget is `unverified`: it keeps its local rows
        and is counted as if nothing had been read, so a blip can only ever make the
        preview say MORE will be deleted than really will. It can never quietly shrink an
        irreversible action's reported scope.

        WHY AN EMPTY ANSWER IS "unverified" AND NOT "already gone whole" -- this differs
        from the brief that ordered the work, on the module's own evidence. The ruling
        said a task the read cannot find at all should be reported as already gone whole.
        It cannot be: core.task_detail_gql collapses a transport failure to None (it
        catches PixAIError/RequestException and returns None), and the 2026-09-06
        read-only probe recorded at moonglade/backup.py's DELETING ONE IMAGE header found
        that "getTaskById still resolves a whole-task-deleted task, so it cannot be used
        to ask whether a task is gone". So None means "no answer", never "gone", and
        reading it as gone would take a network blip and turn it into a smaller reported
        delete -- the one direction this file's fail-soft rule forbids. What CAN be
        established, and is, is per-image: a deleted batch member keeps its place and
        gains `deletedAt`.

        retries=1, not the default 3: the caller here is a confirm dialog the owner is
        watching, and the fallback is a visible "could not be checked" rather than the
        lost-generation sentence task_detail_gql's own retries exist to prevent. Each read
        also gets the budget's REMAINING time as its socket timeout, so the confirm dialog
        is bounded by DELETE_PREVIEW_LIVE_BUDGET_S rather than by the transport's 60s.

        Returns (gone_by_task, unverified, artworks_by_task) -- {task_id: {media_id, ...}}
        for every task that answered, the set of task ids that did not, and {task_id:
        ((artwork_id, ...), batch_size)} for every answered task whose read carried
        `artworkIds` -- batch_size being the task's image count ON PIXAI -- (the
        published-artwork count the dialog words, SCOPE_2026-09-26 E5; a task missing from it
        falls back to the catalog, see api_delete_preview)."""
        from moonglade.gallery import DELETE_PREVIEW_LIVE_BUDGET_S, DELETE_PREVIEW_LIVE_WORKERS
        from moonglade import backup as core   # lazy: avoid import cycle
        ids = [str(t) for t in task_ids]
        try:
            session = core._make_session(None)
        except Exception:                            # noqa: BLE001 -- no key, bad config
            # Nothing to read WITH. Every task is unverified; the preview still answers
            # from the catalog exactly as it did before this existed.
            return {}, set(ids), {}

        # THE CEILING IS WALL-CLOCK, and it is enforced in three places because one is not
        # enough (2026-09-07, correcting the same day's build, which checked it only here):
        #   * before a read STARTS -- the budget is spent, don't start another;
        #   * on the read ITSELF -- each one is given no more socket time than the budget
        #     has left, so a connection that stalls after the handshake cannot run out the
        #     transport's own 60s (and then retry for another 60);
        #   * on the COLLECTION -- as_completed stops at the deadline and the pool is left
        #     to drain on its own, so a worker still in flight cannot hold the route.
        # Anything not back by then is `unverified`, exactly like a read that failed.
        deadline = time.monotonic() + DELETE_PREVIEW_LIVE_BUDGET_S

        def _one(tid):
            from moonglade.catalog_verbs import mark_cloud_deleted
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return tid, None                     # budget spent: don't start another
            try:
                task = _task_reads.task_detail_gql(session, tid, retries=1, timeout=remaining)
            except Exception:                        # noqa: BLE001 -- fail soft, see above
                return tid, None
            if task is None:
                return tid, None
            batch = (task.get("outputs") or {}).get("batch")
            gone_ids = {str(m) for m in _cloud_delete.deleted_batch_media(batch) if m}
            # WRITE IT DOWN, right here, with the same verb the delete's own read uses.
            # See the docstring: this is what stops the delete-time read's failure from
            # taking the rows this preview is about to promise would stay.
            for mid in gone_ids:
                stamp = str((_cloud_delete.batch_entry(batch, mid) or {}).get("deletedAt") or "")
                if stamp:
                    mark_cloud_deleted(db_path, mid, stamp)
            # The same read already carries the task's published artworks -- no second call --
            # and the task's size on PixAI, which is what the artwork count is capped at.
            return tid, (gone_ids, _cloud_delete.task_artwork_ids(task),
                         len(batch) if isinstance(batch, list) else 0)

        # Every task starts unverified and EARNS its way out, so a task whose worker never
        # answers -- the case the deadline exists for -- is counted the safe way by default
        # rather than by remembering to add it.
        gone, unverified, artworks = {}, set(ids), {}
        from concurrent.futures import (ThreadPoolExecutor, as_completed,
                                        TimeoutError as _FutureTimeout)
        # NOT a `with` block: its __exit__ is shutdown(wait=True), which waits for every
        # in-flight read and would put the whole ceiling back where it was.
        ex = ThreadPoolExecutor(max_workers=DELETE_PREVIEW_LIVE_WORKERS)
        try:
            futures = [ex.submit(_one, tid) for tid in ids]
            try:
                for fut in as_completed(futures,
                                        timeout=max(0.0, deadline - time.monotonic())):
                    try:
                        tid, res = fut.result()
                    except Exception:                # noqa: BLE001 -- a dead worker is unverified
                        continue
                    if res is not None:
                        gone[tid], aw, batch_n = res
                        if aw is not None:
                            artworks[tid] = (aw, batch_n)
                        unverified.discard(tid)
            except _FutureTimeout:
                pass                                 # the ceiling; the rest stay unverified
        finally:
            # Don't wait. A stalled read is already bounded by its own socket timeout and
            # writes nothing anyone is still listening to; the route answers now.
            ex.shutdown(wait=False, cancel_futures=True)
        return gone, unverified, artworks

    def _preview_entry(row, selected_ids, gone_ids=()):
        """One /api/delete-preview media entry: what it is, whether the user actually
        picked it, and the media_id whose thumbnail exists on disk -- or None for
        `thumb`, so the client renders an id chip instead of a broken image. Videos fall
        back to their still-frame poster's thumb exactly as the gallery grid does (older
        sync runs never generated the video's own).

        `already_gone` (2026-09-07) is the live read's answer for this one image: PixAI has
        already dropped it, so the delete will leave this row and its file alone
        (_rows_the_bulk_purge_must_keep). Always present and False when nothing was read,
        so the strip never has to guess which of the two it is looking at."""
        mid = row["media_id"]
        thumb = None
        if (thumb_dir / "{}.jpg".format(mid)).exists():
            thumb = mid
        elif row["is_video"] == "1" and row["poster_media_id"]:
            poster = row["poster_media_id"]
            if (thumb_dir / "{}.jpg".format(poster)).exists():
                thumb = poster
        return {"media_id": mid, "is_video": row["is_video"] == "1",
                "selected": mid in selected_ids, "thumb": thumb,
                "already_gone": mid in gone_ids}

    @app.route("/api/delete-preview", methods=["POST"])
    @tier(LOCALHOST, message="deleting from PixAI is localhost-only")
    def api_delete_preview():
        """What "Delete from PixAI" would actually take, listed image by image, before
        anything fires. Read-only in the sense that matters: it deletes nothing, here or
        on PixAI. It is no longer offline, and no longer writes NOTHING either -- the one
        thing it records is `cloud_deleted_at` on the rows PixAI says it has already
        dropped, so the delete keeps them back whether or not its own read works
        (_preview_live_gone). See THE LIVE CHECK below.

        Deleting on PixAI is TASK-level -- selecting one image of a batch deletes the
        whole batch, cloud AND local. The confirm dialog said that in prose but never
        showed WHICH siblings, so the single irreversible action in this app was also
        the only one whose real scope the user could not see before committing to it.
        This resolves the selection through the delete_preview_rows catalog verb,
        which shares its target resolution with /api/delete-tasks deliberately, and
        then expands each task to its full catalog membership.

        LOCALHOST, mirroring the action it previews rather than the data it reads. The
        catalog rows themselves are ordinary LOGIN-tier browsing material (a LAN
        session can already list a whole batch via ?batch=<task_id>), so this is not
        about hiding them -- it is that the preview exists only as step one of a
        LOCALHOST flow whose button a LAN session cannot even see, and a preview
        reachable at a lower tier than its action is a gap waiting to be mistaken for
        an entry point. Weakens nothing: /delete-tasks-bulk still re-checks for itself.

        Truncation is DISPLAY-only (DELETE_PREVIEW_TASK_CAP): `totals` always describes
        the entire selection, because the totals are what the user reads to decide.

        THE LIVE CHECK (owner, 2026-09-07). "One live read per selected task, capped at
        40; above that the preview says it is an estimate, and the delete still keeps back
        what the live read finds." At or below DELETE_PREVIEW_LIVE_CAP every selected task
        is read back from PixAI (_preview_live_gone), so an image the owner deleted on
        PixAI's own website is reported as ALREADY GONE instead of being counted among the
        files this delete will take -- which is what the catalog alone could never know,
        and what made the preview disagree with the delete it was previewing. Above the
        cap nothing is read and `estimate` says so.

        `totals` is UNCHANGED in meaning: it is still the full membership of the blast
        radius. The four new fields sit beside it, top-level, so nothing that reads
        `totals` today can be surprised:
          live_checked  how many tasks really were read back
          unverified    how many could not be (a blip, no credentials, or the budget)
          already_gone  IMAGES PixAI has already dropped -- subtract from totals.media for
                        "will be deleted"
          estimate      True when the selection was over the cap and nothing was read

        PUBLISHED ARTWORK (2026-09-26, SCOPE_2026-09-26 E5). PixAI's own contract says its
        task delete "soft-deletes a task ...: its linked artwork is deleted" -- and every
        task this dialog previews goes by the whole-task delete. Two more fields say how
        much published work that may take, for the dialog to put in one sentence:
          published            artworks across the selection's tasks: each task's LIVE
                               `artworkIds` off the read above (capped at the task's image
                               count on PixAI, or its library rows if that is more), else --
                               over the live cap, or a task that did not answer -- the
                               catalog rows of that task carrying an artwork_id. A blank
                               artwork_id is "not known", never "not published".
          published_unchecked  True when some task fell back to the catalog AND the catalog
                               records no artwork at all (the artworks sync has never filled
                               it), so publication was simply not checked.
          published_unchecked_tasks  how many tasks that is (0 when checked), so a dialog
                               that also has a live count can say "K of the N tasks were not
                               checked" instead of contradicting the count."""
        from moonglade.gallery import DELETE_PREVIEW_LIVE_CAP, DELETE_PREVIEW_TASK_CAP
        from moonglade.catalog_verbs import delete_preview_rows, myart_coverage
        body = request.get_json(silent=True) or {}
        # dict.fromkeys: deduped, order preserved. The blast radius is a set of FILES, so
        # a repeated id must not inflate "you picked N" (or drive `unselected` negative)
        # just because a caller sent the same one twice.
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400

        blast = delete_preview_rows(db_path, media_ids)
        sel_rows, task_ids = blast["sel_rows"], blast["task_ids"]
        local_only = blast["local_only"]
        selected = {r["media_id"] for r in sel_rows}

        # The live check, before the loop that spends it. Over the cap it does not happen
        # at all -- estimate, and the modal says so.
        estimate = len(task_ids) > DELETE_PREVIEW_LIVE_CAP
        gone_by_task, unverified, artworks_by_task = (
            ({}, set(), {}) if estimate else _preview_live_gone(task_ids))

        tasks, total_media, already_gone = [], 0, 0
        published, from_catalog = 0, 0
        for tid in task_ids:
            members = blast["members_by_task"].get(tid, [])
            total_media += len(members)
            # Published artwork, over the task's FULL membership (the delete takes the whole
            # task, not just the picked rows) -- see the docstring. The live count is capped at
            # the task's size ON PIXAI (or its library rows, if more): a library that never
            # collected some of a task's images must not under-count what the delete may take.
            if tid in artworks_by_task:
                aw, batch_n = artworks_by_task[tid]
                published += min(len(aw), max(1, len(members), batch_n))
            else:
                from_catalog += 1
                published += sum(1 for m in members
                                 if str(m.get("artwork_id") or "").strip())
            # A task that answered: the union of what the read says PixAI has dropped and
            # what the catalog was already told the last time anything read this task --
            # exactly the two sources _rows_the_bulk_purge_must_keep keeps back from, so
            # the count the owner reads here is the count the delete will honour. A task
            # that did NOT answer contributes nothing: it stands on its local rows whole,
            # which can only over-report the delete, never under-report it.
            gone = set()
            if tid in gone_by_task:
                gone = set(gone_by_task[tid])
                gone |= {str(m["media_id"]) for m in members
                         if str(m["cloud_deleted_at"] or "").strip()}
                gone &= {str(m["media_id"]) for m in members}
                already_gone += len(gone)
            if len(tasks) >= DELETE_PREVIEW_TASK_CAP:
                continue          # keep counting, stop describing
            tasks.append({"task_id": tid,
                          "unverified": tid in unverified,
                          "media": [_preview_entry(m, selected, gone) for m in members]})
        # Imports have no task, so nothing about them is task-level -- but they ARE
        # part of what the button removes, and the dialog has to show them or its
        # file count won't add up. Capped on the same DISPLAY budget as the tasks.
        local_entries = [_preview_entry(m, selected) for m in blast["local_rows"]]
        # The tasks whose publication nobody could answer: they fell back to a catalog the
        # artworks sync has never filled.
        published_unchecked_tasks = (
            from_catalog if from_catalog and not myart_coverage(db_path)["artworks"] else 0)

        return jsonify({
            "tasks": tasks,
            "local_only": local_entries,
            "truncated": (len(task_ids) > len(tasks)
                          or len(local_only) > len(local_entries)),
            # The live check's own answer, beside `totals` rather than inside it (see the
            # docstring). live_checked + unverified == len(task_ids) whenever it ran.
            "live_checked": len(gone_by_task),
            "unverified": len(unverified),
            "already_gone": already_gone,
            "estimate": estimate,
            "published": published,
            "published_unchecked": bool(published_unchecked_tasks),
            "published_unchecked_tasks": published_unchecked_tasks,
            "totals": {
                "selected": len(sel_rows),
                "tasks": len(task_ids),
                "media": total_media + len(local_only),
                "unselected": total_media + len(local_only) - len(sel_rows),
                "local_only": len(local_only),
            },
        })

    def _start_bulk_delete(task_ids, local_only, purge_local=True):
        """The shared engine behind BOTH /delete-tasks-bulk (form/redirect) and
        /api/delete-tasks (JSON) -- extracted from the former verbatim so the two
        routes cannot drift in what they actually DO, only in how they answer.
        Kicks the delete off-thread, reporting to the Activity card exactly as
        before.

        Returns (job_id, total, err): started when err is None; otherwise err is
        "busy" (a bulk delete is already running -- single-flight held) or
        "thread" (the worker thread could not start; single-flight released and
        the failure already logged to the job card). Callers check total > 0
        themselves -- this helper assumes there is work.

        purge_local=False is the JSON route's cloud-only mode (cloud gone, local files
        + catalog intact: what the removed --delete-task command used to do). It
        drops the local_only imports HERE, not in the caller, because with no
        cloud side they would otherwise be pure local purges -- exactly what the
        flag says not to do."""
        import uuid
        from moonglade import backup as core   # lazy: avoid import cycle
        if not purge_local:
            local_only = []
        total = len(task_ids) + len(local_only)

        # Single-flight: never let two bulk deletes interleave their cloud calls.
        with _bulkdel_lock:
            if _bulkdel_running["on"]:
                return None, total, "busy"
            _bulkdel_running["on"] = True

        job_id = "bulkdel-" + uuid.uuid4().hex[:12]
        label = ("Delete {} task(s) from PixAI".format(len(task_ids)) if task_ids
                 else "Purge {} local item(s)".format(len(local_only)))
        _log_job(job_id, status="running", type="delete", label=label, done=0, total=total)

        def _work():
            from moonglade.catalog_verbs import task_media
            deleted = failed = removed = done = 0
            kept = []
            step = max(1, total // 50)          # throttle progress writes (~every 2%)
            def _tick():
                if done % step == 0 or done == total:
                    _log_job(job_id, status="running", done=done, total=total)
            try:
                session = core._make_session(None) if task_ids else None
                for tid in task_ids:
                    # BEFORE the cloud delete: once the generation record is gone there is
                    # nothing left to read, and this is the read that says which local rows
                    # hold the only copy of their image left anywhere.
                    rows = task_media(db_path, tid) if purge_local else []
                    keep = (_rows_the_bulk_purge_must_keep(session, tid, rows)
                            if purge_local else set())
                    try:
                        _cloud_delete.delete_task(session, tid)          # cloud delete (irreversible)
                        deleted += 1
                    except Exception:                            # noqa: BLE001
                        failed += 1
                        done += 1; _tick(); continue
                    if purge_local:
                        for m in rows:
                            if str(m["media_id"]) in keep:
                                # PixAI had already deleted this one; this library holds the
                                # last copy in existence. Named on the card, never purged.
                                kept.append(str(m["media_id"]))
                                continue
                            try:
                                _purge_local(m["media_id"], m["filename"]); removed += 1
                            except OSError:
                                # This task's cloud delete has ALREADY fired, so one file the
                                # OS won't let go of must not take the whole loop down with it:
                                # every task still queued would be left deleted on PixAI but
                                # live in the catalog, and nothing would say so.
                                failed += 1
                    done += 1; _tick()
                for r in local_only:
                    try:
                        _purge_local(r["media_id"], r.get("filename")); removed += 1
                    except OSError:
                        failed += 1
                    done += 1; _tick()
                summary = "Deleted {} · purged {} local · {} failed".format(deleted, removed, failed)
                if kept:
                    # Said out loud rather than left as a silent difference in the numbers:
                    # these files are still in the library on purpose.
                    summary += " · kept {} file{} PixAI had already deleted".format(
                        len(kept), "" if len(kept) == 1 else "s")
                # ANY failure is a non-clean result -- surface it RED on the card. Don't bury
                # "3 failed" inside a green 'done': those tasks still exist on PixAI (drift).
                status = "failed" if failed else "done"
                _log_job(job_id, status=status, label=summary, done=total, total=total,
                         kept_media=(kept or None),
                         error=(summary if failed else None))
            except Exception as e:                               # noqa: BLE001
                _log_job(job_id, status="failed", error=_redact_host_paths(str(e))[:200])
            finally:
                with _bulkdel_lock:
                    _bulkdel_running["on"] = False

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception as e:                               # noqa: BLE001 -- OS thread exhaustion, etc.
            with _bulkdel_lock:                              # never wedge single-flight forever
                _bulkdel_running["on"] = False
            _log_job(job_id, status="failed", error="could not start delete thread: " + _redact_host_paths(str(e))[:160])
            return None, total, "thread"
        return job_id, total, None

    @app.route("/api/delete-tasks", methods=["POST"])
    @tier(LOCALHOST, message="deleting from PixAI is localhost-only")
    def api_delete_tasks():
        """JSON twin of /delete-tasks-bulk: same LOCALHOST tier (and for the same
        reason -- this MUTATES THE OWNER'S REAL CLOUD ACCOUNT, irreversibly), same
        delete_targets selection so /api/delete-preview keeps describing
        exactly what this route then does, and the same off-thread worker via
        _start_bulk_delete -- which routes every cloud delete through
        core.delete_task (POST /v2/task/{id}/delete on the API key), the single-attempt
        _check_read_only'd choke point the page route uses, never gql_adhoc. The page
        route stays until classic's demolition.

        Body: {task_ids: [...]} OR {media_ids: [...]} (task_ids win when both are
        sent -- they are already the unit the delete operates on), plus optional
        purge_local (default true, the page behavior: purge follows cloud so
        catalog and account never drift; false = cloud-only, what the removed
        --delete-task command used to do, and imports are then left alone entirely).

        _check_read_only fires HERE, before the job even starts, on top of the one
        inside delete_task: failing fast with one readable refusal beats
        spawning a job whose every task then fails red on the Activity card."""
        from moonglade.catalog_verbs import delete_targets
        from moonglade import backup as core   # lazy: avoid import cycle
        body = request.get_json(silent=True) or {}
        purge_local = bool(body.get("purge_local", True))
        task_ids = sorted({str(t).strip() for t in (body.get("task_ids") or [])
                           if str(t).strip()})
        local_only = []
        if not task_ids:
            media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
            if not media_ids:
                return jsonify({"error": "no task_ids or media_ids given"}), 400
            _sel_rows, task_ids, local_only = delete_targets(db_path, media_ids)
        if not purge_local:
            local_only = []          # cloud-only mode: imports have no cloud side
        if not (task_ids or local_only):
            return jsonify({"ok": True, "count": 0, "job_id": None,
                            "tasks": 0, "local_only": 0})
        if task_ids:
            try:
                core._check_read_only("delete tasks from your PixAI account")
            except core.PixAIError as e:
                return jsonify({"error": _redact_host_paths(str(e))[:240]}), 403
        job_id, total, err = _start_bulk_delete(task_ids, local_only,
                                                purge_local=purge_local)
        if err == "busy":
            return jsonify({"error": "a bulk delete is already running -- "
                                     "see the Activity card"}), 409
        if err:
            return jsonify({"error": "could not start bulk delete -- try again"}), 500
        return jsonify({"ok": True, "count": total, "job_id": job_id,
                        "tasks": len(task_ids), "local_only": len(local_only)})

    # -------------------------------------------------------------------
    # Trash / quarantine panel -- the floating panel opened from the Control
    # Panel (NOT a routed page of its own). See the 2026-07-21 audit's
    # restore-panel row for the decided design (floating overlay, directory
    # scan, restore=LOGIN, delete-forever/empty=LOCALHOST+typed confirm).
    # -------------------------------------------------------------------

    @app.route("/api/trash/list")
    @tier(LOGIN)
    def api_trash_list():
        """List out_dir/_deleted/ for the Control Panel's Trash panel -- a directory
        scan, not a catalog query (purge_media_local's whole point is that the
        catalog row is already gone by the time a file lands here). Paginated
        (?page=&limit=) so a ~12k-file quarantine never costs more than one page's
        worth of thumbnail work per request -- see list_quarantined()'s and
        _ensure_trash_thumbs()'s docstrings. Thumbnails are generated on demand for
        exactly the page returned and then served by the EXISTING /thumbs/<media_id>.jpg
        route (no new serving route needed -- see _ensure_trash_thumbs()). LOGIN tier:
        seeing what's recoverable is the same trust level as browsing the live
        gallery, not a destructive action."""
        from moonglade.gallery import _ensure_trash_thumbs, _list_quarantined
        try:
            page = max(1, int(request.args.get("page") or 1))
            limit = max(1, min(int(request.args.get("limit") or 60), 200))
        except ValueError:
            page, limit = 1, 60
        items, total, total_bytes, archive_only_total = _list_quarantined(
            out_dir, page=page, page_size=limit)
        _ensure_trash_thumbs(out_dir, thumb_dir, items)
        for it in items:
            it["thumb"] = "/thumbs/{}.jpg".format(it["media_id"])
        # `archive_only` per file and `archive_only_total` for the whole trash (#66): the
        # typed-DELETE confirms of Delete forever and Empty trash name how many files are
        # the only copy anywhere before they go for good (Empty takes every page, so the
        # page alone cannot answer it).
        return jsonify({"items": items, "total": total, "total_bytes": total_bytes,
                        "archive_only_total": archive_only_total,
                        "page": page, "limit": limit})

    @app.route("/api/trash/restore", methods=["POST"])
    @tier(LOGIN)
    def api_trash_restore():
        """Restore one or more quarantined files back into the library. LOGIN tier --
        recovering something you (or anyone signed in) deleted is not the same trust
        question as permanently destroying it. Matches the decided design in
        the 2026-07-21 audit: restore=LOGIN, delete-forever/empty=LOCALHOST."""
        from moonglade.gallery import restore_quarantined_media
        body = request.get_json(silent=True) or {}
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        restored, errors = [], []
        for mid in media_ids:
            res = restore_quarantined_media(out_dir, thumb_dir, db_path, mid)
            if res.get("ok"):
                restored.append(mid)
            else:
                errors.append({"media_id": mid, "error": res.get("error", "unknown error")})
        if restored:
            _telemetry.telem_bump("trash_restored", len(restored), out_dir=out_dir)
        return jsonify({"restored": restored, "errors": errors})

    @app.route("/api/trash/delete-forever", methods=["POST"])
    @tier(LOCALHOST)
    def api_trash_delete_forever():
        """Permanently destroy one or more SELECTED quarantined files -- no more
        recovery after this. LOCALHOST-only (the owner physically at the machine),
        same trust tier as /delete-tasks-bulk and the Panel's other destructive
        actions, and requires confirm=true in the body on top of that -- the same
        belt-and-suspenders shape api_panel_run already uses for its destructive
        actions. The client's own typed "DELETE" prompt (Trash.deleteSelected() in
        the Panel template, mirroring confirmBulkDeleteCloud()'s existing pattern) is
        what actually stands between a misclick and data loss; confirm=true here just
        proves the client meant to send the request at all, it is not itself the
        security boundary -- the LOCALHOST check is."""
        from moonglade.gallery import delete_quarantined_forever
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        n = sum(1 for mid in media_ids
               if delete_quarantined_forever(out_dir, thumb_dir, mid))
        _telemetry.telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    @app.route("/api/trash/empty", methods=["POST"])
    @tier(LOCALHOST)
    def api_trash_empty():
        """Empty the ENTIRE trash -- every file under out_dir/_deleted/, not just a
        selection. Same LOCALHOST + confirm=true contract as
        api_trash_delete_forever() (see its docstring); the client demands the same
        typed "DELETE" word first (Trash.emptyAll())."""
        from moonglade.gallery import empty_trash
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        n = empty_trash(out_dir, thumb_dir)
        _telemetry.telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    # -- provided to ctx (split_move) --
    ctx._batch_sibling_count = _batch_sibling_count
    # -- end --

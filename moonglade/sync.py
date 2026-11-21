"""
moonglade/sync.py
=================
The download and the backfills: the --delay default and the pace gate, the worker pool
(`_parallel_map`), the metadata, full-meta, lineage and perceptual-hash backfills, the time
capsule, the walk-end marker, `run_download` and --rebuild-thumbs. Moved verbatim out of
moonglade/backup.py in the 3.22 split (phase 4).

The names it reads from the engine (PixAIError, _make_session, _ensure_db, the progress and
count helpers, PANEL_WARN_PREFIX, _TRUSTSTORE_ACTIVE, vlog and the catalog's load/save calls,
which tests patch there) are imported from moonglade.backup inside each function that uses
them, at call time, so a test's patch of backup's binding still reaches them and importing
this module never imports the engine.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

from moonglade import account_api as _account_api
from moonglade import full_meta as _full_meta
from moonglade import history as _history
from moonglade import media_fetch as _media_fetch
from moonglade import models as _models
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade.catalog import init_db
from moonglade.scan import QUARANTINE_EXCLUDE_ANYWHERE, scan_library


class _DefaultDelay(float):
    """The argparse DEFAULT for `--delay`, tagged so "nobody said anything" can be told from
    "the user asked for this".

    A plain float cannot answer that question. `args.delay == 0.4` is true both when the flag
    was never typed and when it was typed as `--delay 0.4`, and `parser.get_default("delay")`
    only re-derives the same 0.4 -- so any comparison-based test silently overrides a
    deliberate choice that happens to match the shipped default. argparse runs `type=float`
    over a value it took from the COMMAND LINE and leaves the `default=` object untouched
    otherwise, so the tag survives exactly when the user was silent, which is the fact we
    need. A float subclass rather than a None-and-fill-in-later default because `args.delay`
    is read as a number in a dozen places (`time.sleep(args.delay)`, the `{:g}` banner, every
    `_parallel_map(delay=...)` call); every one of them keeps working unchanged.

    Only the parallel download stage asks -- see run_download. Everything else honours
    --delay's default exactly as it always has."""
    __slots__ = ()


DEFAULT_DELAY = _DefaultDelay(0.4)


def _delay_was_chosen(args):
    """True when `--delay` was actually typed (or a caller deliberately set one).

    A synthesized args namespace -- the tests, and any in-process caller that builds one --
    carries a plain float, which reads as a deliberate choice. That is the right default for
    a caller that went to the trouble of naming a delay; the one caller that must NOT be
    re-paced, the Control Panel's Sync job, reaches run_download by spawning the CLI with
    `--workers N` and no `--delay` at all, so it comes through argparse and lands on the
    sentinel. A namespace with no `delay` at all named nothing either, so it reads as not
    chosen -- answering True there would send the caller straight into an AttributeError
    reaching for the value it just claimed existed."""
    d = getattr(args, "delay", None)
    return d is not None and not isinstance(d, _DefaultDelay)


def _pace_gate(delay, *, clock=None, sleep=None):
    """Return a zero-arg callable that blocks until the caller owns the next request slot.

    One global slot at a time: each caller reads the next free slot, waits for it, and books
    the one after it, so a WHOLE thread pool starts at most one request per `delay` seconds
    no matter how many threads are in it. The obvious alternative -- sleeping `delay` inside
    each worker -- is not the same thing and is not enough: it still bursts at
    workers x rate, which is exactly the impoliteness the flag was passed to prevent.

    A falsy `delay` returns a no-op, so a caller can install the gate unconditionally and pay
    nothing (not even a lock acquisition) when the user asked for no pacing.

    Lifted out of _parallel_map's inner closure on 2026-07-27, when run_download's own inline
    pool -- the DEFAULT `--workers 4` path, and the highest-traffic code in the whole tool --
    turned out to apply no pacing at all to its per-image resolve/download calls. The fix for
    that must not be a second, subtly different copy of this clock: two pacing
    implementations drift, and the one that drifts is the one nobody is looking at.

    NOTE that run_download installs this gate only when the user EXPLICITLY passed --delay;
    a defaulted --delay gets `_pace_gate(0)`, i.e. the no-op. _parallel_map's own callers are
    unaffected and pace as they always did. Read run_download's comment before assuming a
    default backup is throttled by this -- it is not.

    `clock`/`sleep` are injectable for deterministic tests only: the pacing unit tests drive
    the gate with a frozen clock and a recording sleep so they assert on the slots BOOKED,
    not on real wall-clock gaps (which measured scheduling jitter and flaked under load).
    Production passes neither and resolves `time.monotonic`/`time.sleep` at call time, so the
    behaviour -- including anything that monkeypatches `core.time` -- is exactly as before.
    """
    if not delay:
        return lambda: None
    gate = threading.Lock()
    next_start = [0.0]

    def _wait():
        with gate:
            now = (clock or time.monotonic)()
            wait = max(0.0, next_start[0] - now)
            next_start[0] = max(now, next_start[0]) + delay
        if wait:
            (sleep or time.sleep)(wait)

    return _wait


def _parallel_map(items, work_fn, workers=1, progress=None, delay=0.0, on_error=None):
    """Run work_fn(item) over items, yielding (item, result) as each finishes.

    workers<=1 runs serially, sleeping `delay` between items. Higher uses a bounded thread
    pool for latency-bound network calls -- and STILL honours `delay`, as a global floor on
    the interval between request starts, not a per-thread one. It used to be dropped
    entirely on the parallel path ("concurrency itself paces"), which meant `--workers 8`
    turned a deliberately paced request stream into eight threads firing as fast as they
    completed. Being polite to PixAI's servers is a standing rule of this project, and it
    should not switch itself off because a flag was passed. The pace is global, so raising
    --workers now buys latency hiding up to that ceiling rather than a bigger burst; lower
    --delay if you genuinely want more throughput, and know that you are choosing it.

    A worker's exception yields a None result rather than crashing the run -- but it is
    NEVER swallowed silently: `on_error(item, exc)` is called with it first. It used to be
    discarded, and a real 17,289-task backfill consequently reported "16,044 failed" with no
    reason attached to any of them, which is a number you cannot act on.

    progress(done, total, 0) is called on THIS thread, so the caller may safely mutate
    shared state in the yield body.
    """
    items = list(items)
    total = len(items)
    if workers <= 1:
        for i, it in enumerate(items):
            try:
                res = work_fn(it)
            except Exception as e:                       # noqa: BLE001 -- reported, not hidden
                res = None
                if on_error:
                    on_error(it, e)
            yield it, res
            if progress:
                progress(i + 1, total, 0)
            if delay:
                time.sleep(delay)
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    pace = _pace_gate(delay)   # one global slot per item -- see _pace_gate

    def _paced(it):
        pace()
        return work_fn(it)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_paced, it): it for it in items}
        for fut in as_completed(futs):
            it = futs[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:                       # noqa: BLE001 -- reported, not hidden
                res = None
                if on_error:
                    on_error(it, e)
            yield it, res
            if progress:
                progress(done, total, 0)


def run_backfill_meta(args):
    """Fill in missing url/width/height for catalog rows via resolve_media().
    Safe to re-run -- skips rows that already have all three fields."""
    from moonglade.backup import _ensure_db, load_catalog, _make_session, save_catalog
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    rows = load_catalog(db_path)

    to_fill = [r for r in rows if not (r.get("url") and r.get("width") and r.get("height"))]
    print("Found {:,} rows missing url/width/height (out of {:,} total).".format(
        len(to_fill), len(rows)))
    if not to_fill:
        print("Nothing to backfill.")
        return

    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Resolving with {} parallel workers.".format(workers))
    updated = failed = 0
    _prog = getattr(args, "progress", None)
    for row, res in _parallel_map(to_fill, lambda r: _media_fetch.resolve_media(session, r["media_id"]),
                                  workers, _prog, delay=args.delay):
        url, info = res if res else (None, {})
        if url:
            row["url"] = url
            row["width"] = str(info.get("width") or "")
            row["height"] = str(info.get("height") or "")
            updated += 1
        else:
            failed += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  {:,}/{:,}  updated {:,}  failed {:,}  ".format(
                updated + failed, len(to_fill), updated, failed))
            sys.stdout.flush()

    print("\nWriting catalog...")
    save_catalog(db_path, to_fill)
    print("Done. Updated {:,} rows, {:,} still missing.".format(updated, failed))


# How many completed tasks between catalog flushes in run_backfill_full_meta. Small enough that
# an interrupted 36k-image run loses at most this many tasks of work (~1-2 min at normal pace),
# large enough that the flush I/O stays a rounding error next to the getTaskById fetch time.
_BACKFILL_CHECKPOINT_TASKS = 500


def run_backfill_full_meta(args):
    """Fill catalog rows from the task detail read + the model version read: the core
    prompt_full/natural_prompt/seed/steps/sampler/cfg_scale/model_id/model_name, plus
    url/width/height from the task's media object as a free side effect. steps/sampler/cfg
    also fall back to the model VERSION preset when the task recorded none (issue #18).

    Re-fetch is gated by _needs() (see below), which is why the extra surfaces are opt-in --
    each widens the set of already-detailed rows that get re-fetched:
      --with-loras    rows missing the `loras` column (predate LoRA tracking)
      --with-credit   rows missing `paid_credit` (predate cost tracking)
      --with-surface  rows missing the 15 issue-#18 surface columns (inference_profile,
                      quality_tag, render_seconds, backend, retry_count, moderation, ...) --
                      the ONLY way a pre-#18 row that already has prompt + model ever gains
                      them, since it otherwise passes every _needs() gate and is skipped.
    Safe to re-run -- each pass skips rows already carrying what it targets."""
    from moonglade.backup import (_ensure_db, load_catalog, _make_session,
                                  save_catalog_over_snapshot)
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))

    rows = load_catalog(db_path)
    # As loaded, so a checkpoint save keeps a rating or collection set while this runs.
    snapshot = {r["media_id"]: dict(r) for r in rows if r.get("media_id")}
    with_loras = getattr(args, "with_loras", False)
    with_credit = getattr(args, "with_credit", False)
    with_surface = getattr(args, "with_surface", False)

    # Work per unique task_id (one API call covers all media in that task).
    # --with-loras also re-processes rows that have full meta but a blank `loras`
    # column (e.g. backfilled before LoRA tracking existed). It re-fetches their
    # getTaskById to extract parameters.lora.
    # --with-credit is the same pattern for `paid_credit` (added 2026-07-23):
    # getTaskById returns paidCredit for historical tasks, so rows cataloged before
    # cost tracking existed can recover their real spend. Opt-in, like --with-loras,
    # because it re-fetches every not-yet-costed task (long run on a big catalog).
    # These four come ONLY from a getTaskById fetch -- the listing feed carries neither.
    # A row holding none of them has never seen a task detail, whatever else it holds.
    _DETAIL_ONLY = ("model_id", "steps", "sampler", "cfg_scale")

    def _needs(r):
        if not r.get("prompt_full"):
            return True
        # prompt_full alone is NOT proof the detail was fetched. Rows exist carrying a
        # prompt and a seed and nothing else -- no model, no steps, no sampler, no CFG --
        # and while prompt_full was the sole sentinel every one of them was skipped
        # forever: the sweep printed "Nothing to backfill" over a catalog that could not
        # say which model made any of it. Measured on a real catalog before this changed:
        # 788/800 rows had a prompt, 5/800 had a model id, and a backfill was a no-op.
        # A task that genuinely returns none of the four is re-fetched on a later sweep
        # too; that is a bounded, idempotent cost, and far cheaper than the silence.
        if not any((r.get(c) or "").strip() for c in _DETAIL_ONLY):
            return True
        if with_loras and r.get("task_id") and not r.get("loras"):
            return True
        if with_credit and r.get("task_id") and not r.get("paid_credit"):
            return True
        # --with-surface is the same opt-in pattern for the 15 issue-#18 surface columns
        # (inference_profile, quality_tag, render_seconds, backend, retry_count, moderation,
        # ...). A pre-#18 row that DID reach detail (it has prompt_full + a model id) passes
        # every gate above and so was skipped forever, never gaining a single surface column
        # -- exactly the rows the whole surface capture exists to enrich. `updated_at` is the
        # sentinel: it is one of the 15, every real getTaskById carries it, and nothing wrote
        # it before #18, so a blank updated_at on a row that has a task_id means "this row
        # predates surface capture." A row already enriched has it set and is skipped; a task
        # that genuinely returns no updatedAt re-fetches each run (bounded, idempotent -- the
        # same deal the _DETAIL_ONLY sweep already makes). Opt-in because on a big historical
        # catalog it re-fetches nearly every task once.
        if with_surface and r.get("task_id") and not (r.get("updated_at") or "").strip():
            return True
        return False
    needs_fill = [r for r in rows if _needs(r)]
    # Named separately in the count below because it is the case that used to be invisible.
    stalled = [r for r in needs_fill
               if r.get("prompt_full")
               and not any((r.get(c) or "").strip() for c in _DETAIL_ONLY)]
    # The surface-only re-admits: rows that already reached detail (prompt + model) yet carry
    # no surface columns. Called out for the same reason `stalled` is -- it is the population
    # --with-surface exists to reach, and staying silent about its size hid whether the flag did
    # anything on a given catalog.
    surface_only = [r for r in needs_fill
                    if with_surface and r.get("task_id") and r.get("prompt_full")
                    and any((r.get(c) or "").strip() for c in _DETAIL_ONLY)
                    and not (r.get("updated_at") or "").strip()]
    task_ids = list(dict.fromkeys(r["task_id"] for r in needs_fill if r.get("task_id")))
    print("Found {:,} rows to fill across {:,} unique tasks{}{}{}.".format(
        len(needs_fill), len(task_ids), " (incl. LoRAs)" if with_loras else "",
        " (incl. credit costs)" if with_credit else "",
        " (incl. #18 surface)" if with_surface else ""))
    if stalled:
        print("  {:,} of them have a prompt but no model/steps/sampler/CFG -- these were "
              "skipped by every earlier backfill.".format(len(stalled)))
    if surface_only:
        print("  {:,} of them already had prompt + model but no #18 surface data (profile, "
              "quality tag, render time, backend, moderation...) -- re-fetched for it.".format(
                  len(surface_only)))
    if not task_ids:
        print("Nothing to backfill.")
        return

    # Fetch and cache full meta per task_id (parallelizable -- each task is an
    # independent getTaskById round-trip).
    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Fetching with {} parallel workers.".format(workers))

    def _fetch_task(tid):
        task_data = _full_meta._task_for_full_meta(session, tid)
        fm = _full_meta.extract_full_meta(task_data)
        if fm.get("model_id"):
            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
        fm["loras"] = _full_meta.resolve_loras(session, task_data)
        _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18: model-preset steps/sampler/cfg
        media_obj = (task_data or {}).get("media") or {}
        if media_obj:
            by_v = {str(u.get("variant", "")).upper(): u["url"]
                    for u in (media_obj.get("urls") or []) if isinstance(u, dict) and u.get("url")}
            for pref in ("PUBLIC", "ORIGINAL", "ORIG", "FULL", "THUMBNAIL"):
                if pref in by_v:
                    fm["_media_url"] = by_v[pref]
                    break
            fm["_media_width"] = str(media_obj.get("width") or "")
            fm["_media_height"] = str(media_obj.get("height") or "")
        return fm

    fetched = failed = 0
    _prog = getattr(args, "progress", None)
    # Failures are counted BY REASON. A bare total is unactionable: the same "16,044 failed"
    # covers a rotated hash, an expired key, a rate limit and a genuinely deleted task, and
    # those have four different answers.
    err_kinds = {}

    def _note_error(tid, exc):
        key = "{}: {}".format(type(exc).__name__, str(exc).strip().splitlines()[0][:120]
                              if str(exc).strip() else "(no message)")
        err_kinds[key] = err_kinds.get(key, 0) + 1

    errored = 0

    # Index the catalog by task id ONCE so each task's meta applies straight to its own rows as
    # it streams back -- no whole-catalog task_cache held across the run. The rows already carry
    # their load-time local columns (they came from load_catalog), so re-saving one preserves
    # its rating/collections/art_tags/etc.
    rows_by_task = {}
    for row in rows:
        rows_by_task.setdefault(str(row.get("task_id") or ""), []).append(row)

    def _apply(tid, fm):
        """Fill one task's catalog rows from its full meta; return the rows it actually changed
        (so only those get written at the next checkpoint)."""
        changed = []
        for row in rows_by_task.get(str(tid), ()):
            hit = False
            # fm is per-TASK; batch_index/batch_size are per-ROW (issue #33) -- resolve
            # this row's own from the outputs.batch list fm parked under _batch.
            fmr = _full_meta._with_batch_position(fm, row.get("media_id"))
            for f in _full_meta._FULL_META_FIELDS:
                if not row.get(f) and fmr.get(f):
                    row[f] = fmr[f]; hit = True
            # Backfill url/width/height from task media as bonus
            if not row.get("url") and fm.get("_media_url"):
                row["url"] = fm["_media_url"]; hit = True
            if not row.get("width") and fm.get("_media_width"):
                row["width"] = fm["_media_width"]; hit = True
            if not row.get("height") and fm.get("_media_height"):
                row["height"] = fm["_media_height"]; hit = True
            if hit:
                changed.append(row)
        return changed

    # Persist AS WE GO, not once at the very end. A 36k-image catalog is tens of thousands of
    # getTaskById calls -- an hour-plus run -- and the old single end-save meant a Ctrl-C or a
    # dropped connection at minute 50 wrote NOTHING, so the whole run was lost. Now every
    # _BACKFILL_CHECKPOINT_TASKS completed tasks the rows filled so far are flushed, so an
    # interrupted run keeps its progress and a rerun resumes where it stopped (the rows already
    # filled now fail _needs() and are skipped). Only backfill-CHANGED rows are written, never
    # the untouched majority -- so an image the owner just rated in the gallery mid-run is not
    # re-saved from a stale snapshot, which NARROWS the concurrent-edit window the end-save had.
    pending = []

    def _checkpoint():
        if pending:
            save_catalog_over_snapshot(db_path, pending, snapshot, blank_keeps=False)
            pending.clear()

    for tid, fm in _parallel_map(task_ids, _fetch_task, workers, _prog, delay=args.delay,
                                 on_error=_note_error):
        fm = fm or {}
        if fm.get("prompt_full"):
            fetched += 1
        else:
            failed += 1
        pending.extend(_apply(tid, fm))
        if (fetched + failed) % _BACKFILL_CHECKPOINT_TASKS == 0:
            _checkpoint()
        if not _prog and workers <= 1:
            sys.stdout.write("\r  Tasks {:,}/{:,}  fetched {:,}  failed {:,}  ".format(
                fetched + failed, len(task_ids), fetched, failed))
            sys.stdout.flush()

    _checkpoint()   # flush the final partial batch
    print()         # end the \r progress line before the summary below
    # "failed" used to mean two unrelated things at once: the fetch threw, or it returned
    # fine and simply carried no prompt (a deleted task, or a kind that records none). Those
    # have completely different answers, and reporting one number for both had us guessing
    # at a 16,044 and then at a 157. Counted apart now.
    errored = sum(err_kinds.values())
    empty = failed - errored
    print("Done. Fetched {:,} tasks, {:,} failed, catalog updated.".format(fetched, failed))
    if empty > 0:
        print("  {:,} of those returned fine but carried no prompt -- a deleted task, or a "
              "kind that records none. Nothing is wrong with them.".format(empty))
    if err_kinds:
        print("Why they failed:")
        for kind, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:5]:
            print("  {:>7,}  {}".format(n, kind))
        worst = max(err_kinds.values())
        if worst >= 20 and failed > fetched:
            # A majority-failure run is not a partial success, and re-running it unchanged
            # just repeats it. Say so, and say the two things that are actually true: it is
            # resumable, so nothing already fetched is refetched, and a slower pace is the
            # first thing to try when a server is pushing back.
            print("  Most of this run failed. Nothing fetched was lost -- the backfill is "
                  "resumable and skips what it already filled -- but re-running it exactly "
                  "as it was will fail the same way.")
            print("  If that reason looks like the server pushing back, try a gentler pace: "
                  "--workers 2 --delay 1")


def run_backfill_lineage(args):
    """--backfill-lineage: fill source_media_id/derive_kind for rows that already have full
    meta (so --backfill-full-meta's own _needs() gate would never revisit them) but predate
    lineage tracking. Same per-task getTaskById + source_media_of_task as the forward path
    (extract_full_meta), just re-scoped to target ONLY the two lineage columns so a catalog
    that's already fully backfilled doesn't need a second full re-fetch to gain lineage.
    Safe to re-run -- skips rows that already have EITHER column set (an original txt2img
    legitimately has both blank forever, so "blank" alone can't be the skip signal; a task_id
    already visited is tracked instead so an original is never re-fetched every run)."""
    from moonglade.backup import _ensure_db, load_catalog, _make_session, save_catalog
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))

    rows = load_catalog(db_path)
    # A task is "done" once ANY of its rows carries a real source_media_id OR the persisted
    # lineage_checked marker (a confirmed original -- "blank" alone is ambiguous with "never
    # checked", which is exactly what lineage_checked exists to disambiguate).
    done_tasks = {r["task_id"] for r in rows
                  if r.get("task_id") and (r.get("source_media_id") or r.get("lineage_checked"))}
    task_ids = list(dict.fromkeys(
        r["task_id"] for r in rows if r.get("task_id") and r["task_id"] not in done_tasks))
    print("Found {:,} unfiled tasks to check for lineage.".format(len(task_ids)))
    if not task_ids:
        print("Nothing to backfill.")
        return

    workers = max(1, getattr(args, "workers", 1) or 1)

    def _fetch(tid):
        task_data = _task_reads.task_detail_gql(session, tid)
        src, kind = _account_api.source_media_of_task(task_data)
        return (src or "", kind or "")

    task_lineage = {}
    found = checked = 0
    _prog = getattr(args, "progress", None)
    err_kinds = {}

    def _note_error(tid, exc):
        key = "{}: {}".format(type(exc).__name__, str(exc).strip().splitlines()[0][:120]
                              if str(exc).strip() else "(no message)")
        err_kinds[key] = err_kinds.get(key, 0) + 1

    for tid, res in _parallel_map(task_ids, _fetch, workers, _prog, delay=args.delay,
                                  on_error=_note_error):
        if res is None:
            # The fetch RAISED (network blip, rate limit, PixAI 500) -- _parallel_map
            # calls on_error and then still yields the item with res=None. Leaving the
            # task OUT of task_lineage keeps lineage_checked unstamped so the next run
            # retries it; folding it in as ("", "") would stamp the error as a confirmed
            # original and permanently exclude the task from every future run.
            continue
        src, kind = res
        task_lineage[tid] = (src, kind)
        checked += 1
        if src:
            found += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  Tasks {:,}/{:,}  derived {:,}  ".format(
                checked, len(task_ids), found))
            sys.stdout.flush()

    print("\nApplying to catalog rows...")
    for row in rows:
        tid = row.get("task_id")
        if tid not in task_lineage:
            continue
        src, kind = task_lineage[tid]
        if src:
            row["source_media_id"] = src
            row["derive_kind"] = kind
        # No source image -- a confirmed original, not "not yet checked". Persisted (a real
        # catalog column) so this task is skipped on every future run instead of re-fetched
        # forever -- see this command's docstring.
        row["lineage_checked"] = "1"

    save_catalog(db_path, rows)
    errored = sum(err_kinds.values())
    print("Done. Checked {:,} tasks, {:,} carried a derivation source, {:,} errored. "
          "Catalog updated.".format(checked, found, errored))
    if err_kinds:
        print("Why they failed:")
        for kind, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:5]:
            print("  {:>7,}  {}".format(n, kind))


def run_backfill_phash(args):
    """--backfill-phash: compute a perceptual difference-hash (compute_dhash(), a 64-bit
    dHash -- see its docstring in moonglade/gallery.py) for every catalog row missing
    one. IMAGE ROWS ONLY: is_video='1' rows are skipped by design -- the near-duplicate
    tier this feeds (near_duplicate_groups(), moonglade/gallery.py) is scoped to images,
    matching the same image-only scope every other duplicate tier already has.

    Purely local, CPU-bound Pillow work -- no network call, so --delay/politeness pacing
    (that flag exists to be polite to PixAI's servers) does not apply here. --workers
    still parallelizes it via a thread pool (Pillow releases the GIL during decode, same
    reasoning build_thumbnails() already uses). --max caps how many rows THIS RUN
    processes (0 = all) -- useful for scoping a first pass on a large library, or a small
    disposable verification run, before committing to hashing the whole thing.

    Safe to re-run -- skips rows that already have a phash. A row whose image file can't
    be found on disk and a row whose file exists but Pillow can't decode are counted
    SEPARATELY from each other (and from the video rows skipped by design), so the
    summary can say WHY a row wasn't filled rather than just how many weren't -- the
    same "don't collapse different failure reasons into one number" lesson
    run_backfill_full_meta's docstring already explains."""
    from moonglade.backup import _ensure_db
    out = Path(args.out)
    db_path = _ensure_db(out)
    from moonglade.thumbs import compute_dhash
    from moonglade.catalog_verbs import find_image_file
    from moonglade.catalog import load_catalog, save_catalog

    rows = load_catalog(db_path)
    videos = [r for r in rows if str(r.get("is_video") or "") == "1"]
    to_fill = [r for r in rows
              if not r.get("phash") and str(r.get("is_video") or "") != "1"]
    found_n = len(to_fill)
    max_n = int(getattr(args, "max", 0) or 0)
    capped = bool(max_n and found_n > max_n)
    if capped:
        to_fill = to_fill[:max_n]
    print("Found {:,} image rows missing a perceptual hash (out of {:,} total catalog "
          "rows, {:,} video rows skipped by design).".format(found_n, len(rows), len(videos)))
    if capped:
        print("  Capped to the first {:,} by --max.".format(max_n))
    if not to_fill:
        print("Nothing to backfill.")
        return {"filled": 0, "unresolved": 0, "unreadable": 0, "total": len(rows)}

    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Hashing with {} parallel workers.".format(workers))

    def _one(row):
        path = find_image_file(out, row["media_id"], row.get("filename"))
        if not path:
            return None, "unresolved"
        h = compute_dhash(path)
        return (h, "ok") if h else (None, "unreadable")

    filled = unresolved = unreadable = 0
    _prog = getattr(args, "progress", None)
    for row, res in _parallel_map(to_fill, _one, workers, _prog, delay=0):
        h, status = res if res else (None, "unreadable")
        if h:
            row["phash"] = h
            filled += 1
        elif status == "unresolved":
            unresolved += 1
        else:
            unreadable += 1
        if not _prog and workers <= 1:
            sys.stdout.write(
                "\r  {:,}/{:,}  hashed {:,}  unresolved {:,}  unreadable {:,}  ".format(
                    filled + unresolved + unreadable, len(to_fill), filled, unresolved, unreadable))
            sys.stdout.flush()

    print("\nWriting catalog...")
    save_catalog(db_path, to_fill)
    print("Done. Hashed {:,} rows. {:,} had no resolvable file on disk, {:,} couldn't be "
          "decoded.".format(filled, unresolved, unreadable))
    return {"filled": filled, "unresolved": unresolved, "unreadable": unreadable, "total": len(rows)}


def _check_time_capsule(created_at, out_dir):
    """A hidden anniversary feat: fires when a NEWLY-downloaded piece is old enough,
    only on the download event, never on a full-catalog rescan (old rows already
    on disk must not earn it). Fail-soft; never slows the download loop.

    The feat's NAME, roast, criteria label and points are sealed in the container. The
    trigger's comparison constant (below) and its flag name are NOT -- they run in the
    public download loop with no container, so they are an accepted, un-sealable residual
    plaintext leak (recorded as such in the sealing definition-of-done). Do not describe
    them as sealed; the spoiler-leak guard can't catch a bare integer either."""
    try:
        from datetime import datetime
        s = str(created_at or "")[:19]
        if not s:
            return
        if (datetime.now() - datetime.fromisoformat(s)).days > 730:
            from moonglade.telemetry import telem_flag
            telem_flag("old_piece_backed_up", out_dir=out_dir)
    except Exception:
        pass


# THE WALK-END MARKER (owner report, 2026-09-07). "This should have picked up where it
# left off and continued pulling 37k images." One fact, per library: has any pass over
# this history ever reached the oldest page? Everything --update's early stop assumes
# rests on it, and until 2026-09-07 nothing recorded it, so a first backup stopped
# part-way left two known pages at the newest end and every later Sync read those two as
# "the whole library is already here".
#
# It lives in the library's own telemetry.json -- the same store `first_sync_done` uses --
# and NOT in config.json: it is a fact about this backup folder, not a setting of the app,
# and two out_dirs must never share it. Fail-soft both ways, and the READ fails to False on
# purpose: an unreadable marker means "keep walking", which costs pages, where the opposite
# default means silently declaring an unfinished library finished.
WALK_END_FLAG = "walk_reached_end"


def walk_end_reached(out_dir):
    """True once some pass over this library has seen pageInfo.hasPreviousPage == False."""
    try:
        from moonglade import gallery as _mg
        return bool(_telemetry.load_telemetry(out_dir)["flags"].get(WALK_END_FLAG))
    except Exception:
        return False


def mark_walk_end_reached(out_dir):
    """Record that a pass walked all the way to the oldest page. Idempotent."""
    try:
        from moonglade import gallery as _mg
        _telemetry.telem_flag(WALK_END_FLAG, out_dir=out_dir)
    except Exception:
        pass


def run_download(args, progress=None):
    """Run the full paginated download + catalog loop.

    progress: optional callable(done: int, total: int) invoked after each
    image is processed (downloaded or skipped). Used by the GUI progress bar.
    When stdout is a real terminal and no progress callback is provided, a
    \r-overwriting ASCII progress bar is printed instead.
    """
    from moonglade.backup import (_ensure_db, _format_size, load_catalog, _make_session,
                                  PANEL_WARN_PREFIX, PixAIError, _progress_line, _quick_count,
                                  save_catalog_over_snapshot, _TRUSTSTORE_ACTIVE, vlog)
    out = Path(args.out)
    img_dir = out / "images"
    raw_path = _paths.records_path(out, "raw_tasks.jsonl")
    db_path  = out / "catalog.db"

    # Ensure the catalog db exists + is schema-migrated (raises if none; no CSV auto-seed, #19)
    try:
        db_path = _ensure_db(out)
    except PixAIError:
        # Fresh install with no prior catalog — create empty db
        init_db(db_path)

    # Load existing catalog so prior-session rows are never lost
    known = {r["media_id"]: r for r in load_catalog(db_path) if r.get("media_id")}
    if known:
        print("Loaded {} existing catalog entries.\n".format(len(known)))

    use_full_meta = getattr(args, "full_meta", False)

    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))

    img_dir.mkdir(parents=True, exist_ok=True)

    # ONE fast tree walk at startup (the shared scan_library: os.scandir, ~free
    # stat() on Windows, excluded subtrees pruned before descending): seed the
    # progress count AND build the on-disk media_id index. Resume is then an
    # O(1) dict lookup instead of an O(whole-tree) rglob per media_id -- the
    # latter made follow-up runs scale quadratically with collection size. This
    # walk happens BEFORE any network call and is the whole of INVARIANT 2's base
    # case, so it stays one walk and one dict.
    # QUARANTINE_EXCLUDE_ANYWHERE prunes gallery/ thumbnails, _duplicates/ and
    # _deleted/ by NAME at any depth -- this walker's own reading of the exclusion
    # set (named disagreement 2), not the top-level-subtree one the rglob walkers
    # use. B11 (audit 2026-07-21): without the _deleted/ prune a locally-purged
    # media_id is still indexed as "already done", so resume/--update never
    # re-downloads it.
    already_done = 0
    disk_bytes = 0
    on_disk_by_mid = {}   # media_id -> Path of an existing full-res image

    if out.exists():
        _t_scan = time.monotonic()
        for e in scan_library(out, kinds=("image",),
                              exclude=QUARANTINE_EXCLUDE_ANYWHERE):
            # A zero-byte file (an interrupted download that got far enough to create
            # the file but not to write it) must NOT count as "already done" here --
            # indexing it means it is skipped FOREVER: no --update/--sync ever
            # re-attempts a media_id already in this index, and
            # reconcile_catalog_with_disk's strict matcher (moonglade/gallery.py) finds
            # nothing wrong either, so the row's filename is left pointing at a dead
            # file with no signal to the user. A stat() race (size is None) is treated
            # as fine, matching prior behaviour -- we can't tell either way, and this
            # index has always erred toward "already done" on an unreadable stat.
            # This is INVARIANT 3 living at the caller, which is why scan_library
            # reports `size` instead of applying a zero-byte rule of its own.
            if e.size == 0:
                continue
            already_done += 1
            if e.size is not None:
                disk_bytes += e.size
            on_disk_by_mid.setdefault(e.media_id, e.path)
        vlog("startup disk scan: {} image files ({}) indexed in {:.2f}s".format(
            already_done, _format_size(disk_bytes), time.monotonic() - _t_scan))
    # Progress counts items as the walk visits them (skips included), starting at
    # zero -- it must NOT be seeded with already_done, or the on-disk images get
    # counted twice (seed + re-check) and the bar overshoots past 100%.
    processed = 0

    if already_done:
        print("Resuming: {} image files already on disk ({}).\n".format(
            already_done, _format_size(disk_bytes)))

    # Progress denominator: avoid a full-history NETWORK pre-count on every run.
    # For a populated library the catalog size is an instant, good-enough estimate
    # (the progress bar already tolerates over/under). Only walk the API to count
    # on a fresh library (empty catalog) or when the user asks for --accurate-count.
    if getattr(args, "accurate_count", False) or not known:
        total_images = _quick_count(session)
    else:
        total_images = max(already_done, len(known))
        print("Library size (catalog estimate): ~{} images "
              "(use --accurate-count for an exact API count)\n".format(total_images))

    def _tick():
        nonlocal processed
        processed += 1
        if progress:
            progress(processed, total_images, dl["ok"])
        elif sys.stdout.isatty():
            # _CONSOLE_LOCK: this is THE writer a pool thread's TLS paragraph races with --
            # _tick runs on the main thread as futures complete, resolve_media runs on the
            # workers. See _console_block.
            with _media_fetch._CONSOLE_LOCK:
                sys.stdout.write(_progress_line(processed, total_images, dl["ok"]))
                sys.stdout.flush()

    if progress:
        progress(processed, total_images, 0)

    print("Walking your generation history (newest -> oldest)...")
    raw_f = open(raw_path, "w", encoding="utf-8")

    _full_meta_cache = {}  # task_id -> full meta dict

    before = None
    seen = 0
    written = set()   # media_ids written this session
    dl = {"ok": 0, "skip": 0, "missing": 0, "fail": 0}
    page = 0
    update_mode = getattr(args, "update", False)
    update_grace = getattr(args, "update_grace", 2)
    consecutive_known_pages = 0
    # THE RESUME GATE (owner report, 2026-09-07). This REFINES the incremental-stop ruling
    # rather than reversing it: a run of already-on-disk pages still ends the walk, but only
    # once this library has PROVEN where the end of history is (walk_end_reached above).
    # Without that proof the walk pages to the true end exactly as a full re-walk does --
    # still skipping every file already on disk, so it costs page listings, not downloads --
    # which is what makes a first backup that was stopped part-way finish on the next Sync
    # instead of stopping after the two pages it happened to have.
    end_known = walk_end_reached(out)
    reached_end = False      # this run saw pageInfo.hasPreviousPage == False
    stopped_early = False    # this run took the consecutive-known-pages stop

    # Parallel downloads: only for the common flat-download case. collect_only does
    # no downloads, so it falls back to the serial path.
    workers = max(1, getattr(args, "workers", 1) or 1)
    parallel = (workers > 1
                and not getattr(args, "collect_only", False))
    # --delay is documented as a politeness throttle that applies to most commands, not just
    # to the serial download loop -- but the parallel branch below paced only the page listing
    # and the per-task full-meta fetch, and fired every resolve_media + download back-to-back
    # with nothing in between, so a user who asked for pacing did not get it on the one stage
    # that makes the most requests (M07, 2026-07-27).
    #
    # It is honoured here only when the user actually TYPED --delay. The first repair paced
    # the pool off the argparse default and so re-paced every existing install that had never
    # asked for anything: at the shipped 0.4s that is a hard global ceiling of 2.5 images/sec
    # regardless of --workers, which turns this file's own documented `--workers 8
    # --page-size 500  # fast full backfill` into a ~2-hour download stage for a 17k library
    # where it used to be ~35 minutes, and quietly makes the Control Panel's Download-workers
    # selector decorative (the panel spawns the CLI with --workers N and no --delay). A
    # throttle nobody asked for is not politeness, it is a silent 3-6x regression -- so the
    # DEFAULT keeps today's full-speed behaviour and `--delay <n>` (including `--delay 0.4`,
    # typed) buys the documented contract. See _DefaultDelay for how the two are told apart.
    #
    # When it IS on: same global-slot semantics as _parallel_map -- one request start per
    # delay across the whole pool, NOT per thread -- so --workers still buys latency hiding
    # rather than a bigger burst, and the gate is built ONCE for the run so the pace survives
    # page boundaries. Each image books ONE slot, covering its resolve_media and its download
    # together; that is a deliberate choice and it is NOT the same rate as the serial branch,
    # which sleeps once per SUCCESSFULLY downloaded image and not at all for a missing one.
    _paced_downloads = _delay_was_chosen(args)
    _pace_image = _pace_gate(args.delay if _paced_downloads else 0)
    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print("Parallel downloads: {} workers{}.\n".format(
            workers,
            (", paced to one image per {:g}s across the pool (--delay)".format(args.delay)
             if _paced_downloads and args.delay else "")))

    def _row_for(meta, mid, full_meta, filename="", url="", w="", h=""):
        return {
            "task_id": meta["task_id"], "media_id": mid,
            "filename": filename, "url": url, "width": w, "height": h,
            "prompt_preview": meta["prompt_preview"],
            "status": meta["status"], "created_at": meta["created_at"],
            # full_meta is per-TASK; batch_index/batch_size are per-ROW (issue #33)
            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
        }

    try:
        while True:
            page += 1
            conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
                args.page_size, _pixai_client._client_of(session).user_id, before)))
            if not conn:
                print("No connection; stopping.")
                break
            edges = conn.get("edges", [])
            if not edges:
                break
            print("Page {}: {} tasks (total {})".format(page, len(edges), seen + len(edges)))

            page_rows = []  # rows accumulated this page; upserted after each page
            page_new = 0    # media_ids on this page NOT already on disk (for --update)

            if parallel:
                # Pass 1 (serial, local): emit raw json, handle on-disk skips, and
                # build a worklist of media_ids that actually need fetching.
                worklist = []
                for edge in edges:
                    node = edge.get("node", edge)
                    raw_f.write(json.dumps(node, ensure_ascii=False) + "\n")
                    if _history._is_video_task_node(node):
                        continue   # video task: its poster still is NOT a standalone image
                    meta = _history.extract_meta(node)
                    all_mids = _history.media_ids_for(node)
                    full_meta = {}
                    if use_full_meta:
                        tid = meta["task_id"]
                        if tid not in _full_meta_cache:
                            task_data = _full_meta._task_for_full_meta(session, tid)
                            fm = _full_meta.extract_full_meta(task_data)
                            if fm.get("model_id"):
                                fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
                            fm["loras"] = _full_meta.resolve_loras(session, task_data)
                            _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18
                            _full_meta_cache[tid] = fm
                            time.sleep(args.delay)
                        full_meta = _full_meta_cache.get(tid, {})
                    for mid in all_mids:
                        existing = on_disk_by_mid.get(mid)
                        if existing:
                            dl["skip"] += 1
                            k = known.get(mid, {})
                            row = _row_for(meta, mid, full_meta,
                                           filename=existing.name, url=k.get("url", ""),
                                           w=k.get("width", ""), h=k.get("height", ""))
                            row["prompt_preview"] = k.get("prompt_preview") or meta["prompt_preview"]
                            row["status"] = k.get("status") or meta["status"]
                            row["created_at"] = k.get("created_at") or meta["created_at"]
                            page_rows.append(row)
                            written.add(mid)
                            _tick()
                            continue
                        page_new += 1
                        stem = img_dir / _history.build_stem_name(
                            meta["prompt_preview"], meta["task_id"], mid,
                            args.name_length, args.name_sep)
                        worklist.append({"meta": meta, "mid": mid, "stem": stem,
                                         "full_meta": full_meta})

                # Pass 2 (parallel): resolve + download. Only the per-item network
                # and file write run in threads; all shared state is mutated here
                # in the main thread as futures complete.
                def _work(item):
                    # Blocks on a pool thread until this image's slot comes up -- but only
                    # when the user typed --delay. Left at its default (and with --delay 0)
                    # this is a no-op call on a `lambda: None`, so the pool runs exactly as
                    # fast as it did before the gate existed.
                    _pace_image()
                    url, info = _media_fetch.resolve_media(session, item["mid"])
                    if not url:
                        return item, "missing", "", info, None
                    status, path = _media_fetch.download(
                        session, url, item["stem"],
                        convert=getattr(args, "convert", None),
                        jpeg_quality=getattr(args, "jpeg_quality", 92),
                        jpeg_bg=getattr(args, "jpeg_bg", "white"),
                        keep_webp=getattr(args, "keep_webp", False))
                    return item, status, url, info, path

                if worklist:
                    with ThreadPoolExecutor(max_workers=workers) as ex:
                        for fut in as_completed([ex.submit(_work, it) for it in worklist]):
                            item, status, url, info, path = fut.result()
                            meta, mid, full_meta = item["meta"], item["mid"], item["full_meta"]
                            w, h = info.get("width", ""), info.get("height", "")
                            if status == "missing":
                                dl["missing"] += 1
                                page_rows.append(_row_for(meta, mid, full_meta, w=w, h=h))
                            else:
                                dl[status] += 1
                                page_rows.append(_row_for(
                                    meta, mid, full_meta,
                                    filename=path.name if path else "", url=url, w=w, h=h))
                                if path and status in ("ok", "skip"):
                                    on_disk_by_mid[mid] = path
                                if status == "ok":
                                    _check_time_capsule(meta.get("created_at"), out)
                            written.add(mid)
                            _tick()

                if page_rows:
                    save_catalog_over_snapshot(db_path, page_rows, known)
                seen += len(edges)
                if args.max and seen >= args.max:
                    print("Reached --max limit.")
                    break
                if update_mode:
                    if page_new == 0:
                        consecutive_known_pages += 1
                        # `end_known`: the resume gate. See where it is set, above.
                        if end_known and consecutive_known_pages >= update_grace:
                            print("\n--update: {} consecutive pages already on disk; "
                                  "stopping (older items are already downloaded)."
                                  .format(consecutive_known_pages))
                            stopped_early = True
                            break
                    else:
                        consecutive_known_pages = 0
                raw_f.flush()
                pi = conn.get("pageInfo", {})
                if not pi.get("hasPreviousPage"):
                    reached_end = True
                    break
                before = pi.get("startCursor")
                time.sleep(args.delay)
                continue

            for edge in edges:
                node = edge.get("node", edge)
                raw_f.write(json.dumps(node, ensure_ascii=False) + "\n")
                if _history._is_video_task_node(node):
                    continue   # video task: its poster still is NOT a standalone image
                meta = _history.extract_meta(node)
                all_mids = _history.media_ids_for(node)

                # Fetch full task detail once per task_id (cached; batches cost 1 call)
                full_meta = {}
                if use_full_meta:
                    tid = meta["task_id"]
                    if tid not in _full_meta_cache:
                        task_data = _full_meta._task_for_full_meta(session, tid)
                        fm = _full_meta.extract_full_meta(task_data)
                        if fm.get("model_id"):
                            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
                        fm["loras"] = _full_meta.resolve_loras(session, task_data)
                        _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18
                        _full_meta_cache[tid] = fm
                        time.sleep(args.delay)
                    full_meta = _full_meta_cache.get(meta["task_id"], {})

                task_folder = img_dir
                for idx, mid in enumerate(all_mids):
                    existing = (None if getattr(args, "collect_only", False)
                                else on_disk_by_mid.get(mid))
                    if existing:
                        dl["skip"] += 1
                        k = known.get(mid, {})
                        page_rows.append({
                            "task_id":        k.get("task_id") or meta["task_id"],
                            "media_id":       mid,
                            "filename":       existing.name,
                            "url":            k.get("url", ""),
                            "width":          k.get("width", ""),
                            "height":         k.get("height", ""),
                            "prompt_preview": k.get("prompt_preview") or meta["prompt_preview"],
                            "status":         k.get("status") or meta["status"],
                            "created_at":     k.get("created_at") or meta["created_at"],
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), k),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    page_new += 1  # this media_id is not yet on disk
                    stem_name = _history.build_stem_name(
                        meta["prompt_preview"], meta["task_id"], mid,
                        args.name_length, args.name_sep)
                    stem = task_folder / stem_name
                    url, info = _media_fetch.resolve_media(session, mid)
                    w, h = info.get("width", ""), info.get("height", "")
                    if not url:
                        dl["missing"] += 1
                        page_rows.append({
                            "task_id": meta["task_id"], "media_id": mid,
                            "filename": "", "url": "", "width": w, "height": h,
                            "prompt_preview": meta["prompt_preview"],
                            "status": meta["status"], "created_at": meta["created_at"],
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    if getattr(args, "collect_only", False):
                        page_rows.append({
                            "task_id": meta["task_id"], "media_id": mid,
                            "filename": "", "url": url, "width": w, "height": h,
                            "prompt_preview": meta["prompt_preview"],
                            "status": meta["status"], "created_at": meta["created_at"],
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    status, path = _media_fetch.download(
                        session, url, stem,
                        convert=getattr(args, "convert", None),
                        jpeg_quality=getattr(args, "jpeg_quality", 92),
                        jpeg_bg=getattr(args, "jpeg_bg", "white"),
                        keep_webp=getattr(args, "keep_webp", False))
                    dl[status] += 1
                    _tick()
                    page_rows.append({
                        "task_id": meta["task_id"], "media_id": mid,
                        "filename": path.name if path else "",
                        "url": url, "width": w, "height": h,
                        "prompt_preview": meta["prompt_preview"],
                        "status": meta["status"], "created_at": meta["created_at"],
                        **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
                    })
                    written.add(mid)
                    if path and status in ("ok", "skip"):
                        on_disk_by_mid[mid] = path  # keep index current within the run
                    if status == "ok":
                        _check_time_capsule(meta.get("created_at"), out)
                        time.sleep(args.delay)

            # Upsert this page's rows so progress is durable even on interrupt. Each row
            # is merged over the row the catalog holds NOW, not over `known` (read when
            # the run started): a re-pull never blanks local curation, and a rating,
            # collection or delete made in the gallery during the run is not undone.
            if page_rows:
                save_catalog_over_snapshot(db_path, page_rows, known)

            # Count TASKS, not pages -- exactly as the parallel branch above does. Counting
            # one per page made every single-worker run (which is what --collect-only always
            # is) overshoot --max by a whole page size and print a "Tasks seen" total that
            # was really a page count.
            seen += len(edges)

            raw_f.flush()
            if args.max and seen >= args.max:
                print("Reached --max limit.")
                break

            # Incremental --update: pages come newest -> oldest, so once we hit
            # a run of pages where everything is already on disk, the rest of the
            # history is older and already downloaded -> stop early. The grace
            # window tolerates occasional gaps (a few missing/failed items).
            # Gated on `end_known` since 2026-09-07 -- "already on disk" only implies
            # "already downloaded" for a library whose tail was reached at least once.
            if update_mode:
                if page_new == 0:
                    consecutive_known_pages += 1
                    if end_known and consecutive_known_pages >= update_grace:
                        print("\n--update: {} consecutive pages already on disk; "
                              "stopping (older items are already downloaded)."
                              .format(consecutive_known_pages))
                        stopped_early = True
                        break
                else:
                    consecutive_known_pages = 0

            pi = conn.get("pageInfo", {})
            if not pi.get("hasPreviousPage"):
                reached_end = True
                break
            before = pi.get("startCursor")
            time.sleep(args.delay)

    finally:
        raw_f.close()

    if reached_end:
        # ONLY a page that actually reported "no previous page" arms the marker. A --max
        # cut-off, a --update early stop, an empty/absent connection and a run killed
        # mid-page all leave it exactly as it was -- which is the whole point: the marker
        # is proof the tail was seen, not a record that a walk happened.
        mark_walk_end_reached(out)
        end_known = True

    if not progress and sys.stdout.isatty() and processed:
        print()  # move past the \r progress bar line

    print("\nDone. Tasks seen: {}".format(seen))
    print("Images -> downloaded {}, skipped {}, missing {}, failed {}".format(
        dl["ok"], dl["skip"], dl["missing"], dl["fail"]))
    print("Catalog: {}\nRaw: {}\nImages: {}".format(db_path, raw_path, img_dir))
    if dl["fail"]:
        # D-4: exit code is UNCHANGED by design (still 0 -- a partial failure must not
        # break a Task Scheduler wrapper over one transient blip). This is purely a
        # louder, harder-to-miss console notice, plus (below) a machine-readable marker
        # for anything watching stdout (the Panel subprocess reader).
        print("\n*** FINISHED WITH ERRORS: {} file(s) failed to download after retries "
              "-- just re-run, finished files are skipped. Exit code is still 0 by "
              "design. ***".format(dl["fail"]))
        if os.environ.get("MOONGLADE_PROGRESS") == "1":
            print("{}{}".format(PANEL_WARN_PREFIX, dl["fail"]), flush=True)
    # How the walk ENDED, alongside what it moved -- the counters were already the return
    # value (D-4), and --sync's closing line is the one caller that has to tell "walked to
    # the end" from "caught up" apart (2026-09-07). Extra keys only; dl["ok"]/["skip"]/
    # ["missing"]/["fail"] mean exactly what they meant.
    dl["pages"] = page
    dl["reached_end"] = reached_end
    dl["stopped_early"] = stopped_early
    dl["end_known"] = end_known
    return dl


def run_rebuild_thumbs(args):
    """--rebuild-thumbs: one uniform thumbnail pass over the whole catalog.
    Images are re-rendered from their originals at today's size/quality settings and
    REPLACED IN PLACE -- each one rendered to a temp file beside its destination and
    os.replace()d over the old one (make_thumbnail), so the gallery never goes blank
    mid-run and an interruption can never leave a truncated .jpg sitting at a real
    thumbnail's name for the exists-check to mistake for a finished one. This is what
    kills years of quality drift. Poster-less videos get a local ffmpeg frame extract,
    and thumbs whose media left the catalog are swept."""
    from moonglade.backup import _ensure_db
    out = Path(args.out)
    db_path = _ensure_db(out)
    from moonglade.thumbs import build_thumbnails
    from moonglade.catalog import load_catalog
    thumb_dir = out / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    rows = load_catalog(db_path)
    known = {r.get("media_id") for r in rows if r.get("media_id")}
    swept = 0
    for f in thumb_dir.glob("*.jpg"):
        if f.stem not in known:
            try:
                f.unlink()
                swept += 1
            except OSError:
                pass
    if swept:
        print("Swept {:,} orphaned thumbnails (media no longer in the catalog).".format(swept))
    print("Rebuilding thumbnails for {:,} catalog rows (images overwritten in place; "
          "poster-less videos get an ffmpeg frame; existing video posters kept)...".format(len(rows)))
    _prog = getattr(args, "progress", None)
    build_thumbnails(rows, out, thumb_dir, force=True,
                     progress_cb=((lambda d, t, _p: _prog(d, t)) if _prog else None),
                     workers=max(1, int(getattr(args, "workers", 4) or 4)))
    print("\nThumbnail rebuild complete.")
    return {"swept": swept, "rows": len(rows)}

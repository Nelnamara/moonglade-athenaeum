"""
moonglade/library_runs.py
=========================
The library's own runs: --sync-artworks and --sync-videos, --faststart-videos, --import-local,
--fix-models (with the live-row model and LoRA labels), --reconcile-deleted (the feed counts and
the reconcile stamp), the similar-image rebuild and sync, --search and --catalog-stats (with
the metadata coverage summary). Moved verbatim out of moonglade/backup.py in the 3.22 split
(phase 4).

The names it reads from the engine (the error classes, READ_ONLY and _read_only_now,
_make_session, _ensure_db, _atomic_replace, _parallel_map, the progress helpers, vlog, the
artwork readers and the catalog's load/save calls, which tests patch there) are imported from
moonglade.backup inside each function that uses them, at call time, so a test's patch of
backup's binding still reaches them and importing this module never imports the engine.
"""
import datetime
import json
import os
import sys
import time
from pathlib import Path

from moonglade import full_meta as _full_meta
from moonglade import gen_params as _gen_params
from moonglade import history as _history
from moonglade import media_fetch as _media_fetch
from moonglade import media_tools as _media_tools
from moonglade import models as _models
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import task_reads as _task_reads
from moonglade.catalog import catalog_csv_text, init_db
from moonglade.catalog_verbs import apply_artwork_meta, apply_artwork_views
from moonglade.curation import query_catalog
from moonglade.scan import (DELETED_DIRNAME, DUPLICATES_DIRNAME, GALLERY_DIRNAME,
                            IMPORT_EXCLUDE, _VIDEO_EXTS, media_id_of, scan_library)


def run_sync_artworks(args):
    """Page the owner's published artworks (artwork_list_gql) and merge their
    metadata (title, published flag, NSFW flag, likes, comments, aes score, tags)
    onto matching catalog rows by media_id. Published artworks are a subset of
    generations, so unmatched/undownloaded ones are simply skipped.

    The merge is a set of NARROW per-row UPDATEs (apply_artwork_meta) of the eleven
    PixAI-owned columns, not a read-modify-write of the whole table -- see the long note
    at the merge itself for why that distinction is the difference between a refresh and
    a silent revert of everything another writer did while this walk was running.

    Returns {"artworks", "matched", "videos", "fail"} (B15) -- "fail" counts a
    pagination fetch that failed mid-run (artwork_list_gql raises ArtworkListRefused with
    the reason, and the first page's refusal ends the run) plus any video that failed to
    download after retries; a non-zero
    "fail" means this run is INCOMPLETE even though it didn't raise. Callers should
    thread it into _cli_job_finish(warn=...) the same way run_download's own callers
    thread dl['fail']."""
    from moonglade.backup import (ArtworkListRefused, _ensure_db, _make_session, PANEL_WARN_PREFIX,
                                  _parallel_map, PixAIError, READ_ONLY, _read_only_now)
    from moonglade.account_api import artwork_list_gql, artwork_views_bulk, extract_artwork_meta
    out = Path(args.out)
    db_path = _ensure_db(out)
    # Build the session FIRST -- _make_session auto-resolves USER_ID from the API key when it
    # isn't pinned in config.json. (Checking before this was the bug: it hard-failed on a config
    # that never lists USER_ID even though the key can resolve it.)
    session = _make_session(getattr(args, "token", None))
    if not _pixai_client._client_of(session).user_id:
        raise PixAIError("USER_ID is missing and could not be resolved from your API key. "
                         "Add USER_ID to config.json as a fallback.")

    # VIEWS-ONLY: the narrow run behind the Panel's own "View counts" job (owner's call,
    # 2026-09-06). The view read is the one part of this command that COSTS something --
    # one view on every published work -- so it gets its own cadence rather than riding
    # whatever cadence the metadata refresh happens to be on. In this mode the listing is
    # not walked at all: the counts join the catalog by artwork_id, which apply_artwork_meta
    # wrote on some earlier run, so nothing here needs the listing to have just happened.
    # It beats --no-views on purpose: a run whose whole purpose is the counts must not be
    # talked out of them by a flag the Panel adds for the OTHER job.
    views_only = bool(getattr(args, "views_only", False))

    by_mid = {}                      # media_id -> artwork fields
    by_video_mid = {}                # videoMediaId -> artwork fields. An animation's
                                     # catalog row is keyed by its MP4's media_id (is_video
                                     # '1'), not the poster mediaId that `by_mid` holds, so
                                     # without this map the video row never receives an
                                     # artwork_id and the Animations tab stays empty (#20).
    videos = []                      # (video_media_id, title) for animated artworks
    with_videos = getattr(args, "with_videos", False)
    artworks = 0
    before = None
    page = 0
    incomplete = False               # B15: True if pagination stopped on a failed
                                      # fetch rather than legitimately running out of pages
    _prog = getattr(args, "progress", None)
    if views_only:
        print("Reading view counts only -- the artwork listing is not walked this run.")
    else:
        print("Syncing published artworks...")
    while not views_only:
        page += 1
        try:
            conn = artwork_list_gql(session, before=before, last=50)
        except ArtworkListRefused as e:
            if page == 1:
                raise PixAIError(
                    "Could not read your published artworks, so nothing was synced. "
                    "{}.".format(e)) from e
            # B15: a page after the first that cannot be read is not "no more pages". Treat
            # it exactly like the download-retry-exhausted case: whatever was already
            # collected is real and worth keeping, but the run is INCOMPLETE, not a clean
            # finish -- it must not report a total that looks whole. The reason is printed
            # with it, so the run says why it stopped.
            incomplete = True
            print("\n  page {} could not be read ({}) -- stopping pagination early. "
                  "Results below are INCOMPLETE, not a full sync.".format(page, e))
            break
        edges = conn.get("edges", [])
        if not edges:
            break
        for edge in edges:
            node = edge.get("node", edge)
            meta = extract_artwork_meta(node)
            if meta["media_id"]:
                by_mid[meta["media_id"]] = meta
                artworks += 1
            vmid = node.get("videoMediaId")
            if vmid:
                videos.append((str(vmid), meta.get("title") or node.get("id")))
                by_video_mid[str(vmid)] = meta      # tag the animation's own row too (#20)
        print("  page {}: {} artworks (total {})".format(page, len(edges), artworks))
        if _prog:
            _prog(artworks, artworks, 0)
        pi = conn.get("pageInfo", {})
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
        time.sleep(getattr(args, "delay", 0.4))

    # VIEWS SWEEP (2026-09-06). A SECOND, ad-hoc pass over the same library, because the
    # listing above never selects `views` (reading one counts as a view) -- see
    # artwork_views_bulk.
    # Runs only when the listing itself found something (no point pricing a sweep against a
    # library we failed to enumerate).
    #
    # A SUPPLEMENTARY READ IN ITS OWN GUARD, exactly like /api/account's credit-split call:
    # it must never turn a successful metadata sync into a failed run. `incomplete` above
    # means one specific thing -- the ARTWORK LISTING is partial, so the counts printed
    # below are not the whole library -- and a views sweep that could not reach PixAI says
    # nothing about that. It reports itself separately (`views_complete` in the return) and
    # merges whatever it did get; the rows it missed keep their previous reading.
    views_map, views_ok = {}, False
    want_views = views_only or (artworks and not getattr(args, "no_views", False))
    if want_views and (READ_ONLY or _read_only_now()):
        # READ_ONLY IS A PROMISE ABOUT THE ACCOUNT, and this read changes it. Asking PixAI
        # how many views a work has ADDS ONE to that number, for every work the query
        # returns -- there is no way to look without it counting -- so the sweep is an
        # account-touching call and belongs on the same side of the switch as publishing
        # and deleting. Refused out loud rather than silently, and the metadata half below
        # keeps working: READ_ONLY has never stopped browsing, backing up or searching.
        # Skipped rather than raised, because the rest of this run is a plain read and
        # taking it down with the sweep would be its own bug.
        print("READ_ONLY is set in config.json -- skipping the view-count sweep. "
              "Reading a view count adds one to it on PixAI, so it is a change to your "
              "own numbers there, not just a look.")
        want_views = False
    if want_views:
        print("Sweeping view counts (bulk artworks query)...")
        views_map, views_ok = artwork_views_bulk(
            session, delay=getattr(args, "delay", 0.4))
        print("  views for {} artwork(s){}".format(
            len(views_map), "" if views_ok else "  -- INCOMPLETE, a page failed"))

    # THE MERGE -- narrow per-row UPDATEs, never a whole-catalog round trip.
    #
    # This used to be `load_catalog -> edit the matched rows in memory -> save_catalog`:
    # read all ~36k rows, then upsert EVERY column of EVERY row back from a snapshot taken
    # after a walk that can run for minutes. That is correct only while this process is the
    # library's ONLY writer -- and since the living library (2026-09-06) it plainly is not.
    # The artworks sweep writes these same rows every fifteen minutes, on every publish and
    # at boot; the owner's ratings and collections land from the browser at any moment. Any
    # write that landed between this run's read and its save was silently reverted, across
    # EVERY column of EVERY row -- ratings and collections included, which this sync has no
    # business touching at all. It is the same lost-update class the September carry fixes
    # closed for the download writers, still open here because this function predates them.
    #
    # apply_artwork_meta (moonglade.gallery) is the row-level twin the sweep already uses:
    # one UPDATE per artwork actually seen, of exactly the eleven PixAI-owned columns
    # extract_artwork_meta fills, keyed by media_id. Rows this sync never saw are not
    # written at all, so they cannot be reverted; a locally-authored column is not in the
    # statement, so it cannot be reached. It also never invents a row, so "unmatched
    # artworks have no downloaded image" still holds by construction rather than by the
    # merge loop happening not to add any.
    #
    # `matched` means exactly what it always did: SQLite's rowcount for an UPDATE is the
    # number of rows whose WHERE matched, which is the number of catalog rows this artwork
    # listing reached.
    metas = {}
    for vmid, m in by_video_mid.items():
        # An animation's catalog row is keyed by its MP4's media_id, not the poster
        # `mediaId` the node carries (#20) -- so it wants the same metadata under THAT key.
        metas[vmid] = dict(m, media_id=vmid)
    for mid, m in by_mid.items():
        # A still's own row wins any collision between the two maps, exactly as the old
        # `by_mid.get(...) or by_video_mid.get(...)` did.
        metas[mid] = m
    matched = apply_artwork_meta(db_path, list(metas.values())) if metas else 0

    # The views half of the same merge, in its own narrow statement (apply_artwork_views).
    # It runs AFTER the meta write on purpose: the sweep is keyed by ARTWORK id and the
    # catalog row is keyed by media_id, so the artwork_id apply_artwork_meta has just
    # written is the join -- including for an animation, whose mp4 row learns its
    # artwork_id from the re-keying above (#20). Rows the sweep missed are not in the map
    # and are not written, so a partial sweep leaves the last reading anyone took.
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    viewed = apply_artwork_views(db_path, views_map, now_iso) if views_map else 0
    if not views_only:
        print("\nArtworks fetched: {}.  Matched to catalog rows: {}.  "
              "(Unmatched artworks have no downloaded image.)".format(artworks, matched))
    if viewed:
        print("View counts written to {} row(s).  Note: reading a view count registers "
              "a view, so this sweep added 1 to each.".format(viewed))

    # Optionally download animated-artwork video files (videoMediaId) into videos/.
    vids_ok = 0
    vids_failed = 0                  # B15: real failures after retries, not "missing"
    if with_videos and videos:
        vdir = out / "videos"
        vdir.mkdir(parents=True, exist_ok=True)
        workers = max(1, getattr(args, "workers", 1) or 1)
        print("\nDownloading {} animated artwork video(s) -> videos/ {}...".format(
            len(videos), "({} workers) ".format(workers) if workers > 1 else ""))

        def _fetch_video(item):
            vmid, title = item
            if _history.already_downloaded_video(out, vmid):
                return "skip"
            url, info = _media_fetch.resolve_media(session, vmid)
            if not url:
                return "missing"
            stem = vdir / _history.build_stem_name(title or "", "", vmid,
                                          getattr(args, "name_length", 60),
                                          getattr(args, "name_sep", "_"))
            status, path = _media_fetch.download(session, url, stem)
            return status

        for item, status in _parallel_map(videos, _fetch_video, workers, _prog,
                                          delay=getattr(args, "delay", 0.4)):
            if status in ("ok", "skip"):
                vids_ok += 1
            elif status == "missing":
                print("  no media url for video {} ({})".format(item[0], item[1]))
            elif status == "fail":
                # download() already retried internally before giving up -- same
                # terminal "fail" status run_download's own dl['fail'] counts.
                vids_failed += 1
                print("  FAILED video {} ({})".format(item[0], item[1]))
        print("Videos saved/present: {} of {}.".format(vids_ok, len(videos)))
    elif videos and not with_videos:
        print("({} animated artworks have video; re-run with --with-videos to download them.)"
              .format(len(videos)))

    # B15: same "done_with_errors" visibility run_download's own callers already get --
    # a loud console notice plus the same machine-readable marker for the Panel
    # subprocess reader (this function is run as its own subprocess by the "sync-artworks"
    # Panel action, exactly like a plain download). Exit code is unaffected by design,
    # same rationale as run_download's own end-of-run notice.
    fail = (1 if incomplete else 0) + vids_failed
    if fail:
        detail = []
        if incomplete:
            detail.append("artwork listing stopped early after a page fetch failed")
        if vids_failed:
            detail.append("{} video(s) failed to download after retries".format(vids_failed))
        print("\n*** FINISHED WITH ERRORS: {} -- exit code is still 0 by design. ***"
              .format("; ".join(detail)))
        if os.environ.get("MOONGLADE_PROGRESS") == "1":
            print("{}{}".format(PANEL_WARN_PREFIX, fail), flush=True)

    return {"artworks": artworks, "matched": matched, "videos": vids_ok, "fail": fail,
            "views": viewed, "views_complete": views_ok}


def run_sync_videos(args):
    """Back up image-to-video generations. The task listing exposes only a video's
    THUMBNAIL media id; the real video media id lives in getTaskById ->
    outputs.videos[].mediaId, and its mp4 URL in the GraphQL media object's
    fileUrl. So: find i2v tasks (i2vProModel set in the summary), fetch each task,
    resolve + download the mp4 into videos/, and catalog it as a video row
    (is_video=1) with the still frame as its poster."""
    from moonglade.backup import (_ensure_db, load_catalog, _make_session, _parallel_map,
                                  save_catalog_over_snapshot)
    out = Path(args.out)
    db_path = _ensure_db(out)
    # Pre-pass snapshot of the existing rows, keyed by media_id: the rows built
    # below start from an all-blank CATALOG_FIELDS template, so upserting them raw
    # blanked every locally-owned column (rating, collections, art_tags, title,
    # is_published, aes_score, blurhash) on EVERY re-run of this sync. Handed to
    # build_catalog_row, which carries those columns forward for every capture path.
    known = {r["media_id"]: r for r in load_catalog(db_path) if r.get("media_id")}
    session = _make_session(getattr(args, "token", None))
    vdir = out / "videos"
    workers = max(1, getattr(args, "workers", 1) or 1)
    name_length = getattr(args, "name_length", 60)
    name_sep = getattr(args, "name_sep", "_")
    _prog = getattr(args, "progress", None)

    # 1. Page the whole feed; collect the cheap i2v task summaries.
    print("Scanning generation history for image-to-video tasks...")
    i2v_nodes, before, scanned = [], None, 0
    while True:
        conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
            getattr(args, "page_size", 250) or 250,
            _pixai_client._client_of(session).user_id, before)))
        if not conn:
            break
        edges = conn.get("edges") or []
        if not edges:
            break
        for e in edges:
            n = e.get("node") or {}
            scanned += 1
            if n.get("i2vProModel"):
                i2v_nodes.append(n)
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
    print("Found {} image-to-video task(s) across {} generations.".format(
        len(i2v_nodes), scanned))
    if not i2v_nodes:
        return {"i2v_tasks": 0, "videos": 0}
    vdir.mkdir(parents=True, exist_ok=True)

    # Generate a gallery poster thumbnail for a video (keyed by the VIDEO media
    # id) from its still frame, so previews work without a separate image backup.
    from moonglade.thumbs import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    poster_tmp = out / "gallery" / "_postertmp"

    def _ensure_video_thumb(video_media_id, poster_media_id, video_path=None):
        thumb_path = thumb_dir / "{}.jpg".format(video_media_id)
        if thumb_path.exists():
            return
        try:
            # Preferred: thumbnail the PixAI still-frame poster.
            if poster_media_id:
                url, _info = _media_fetch.resolve_media(session, poster_media_id)
                if url:
                    poster_tmp.mkdir(parents=True, exist_ok=True)
                    status, path = _media_fetch.download(session, url, poster_tmp / str(poster_media_id))
                    if status in ("ok", "skip") and path:
                        make_thumbnail(path, thumb_path)
                        try:
                            path.unlink()
                        except OSError:
                            pass
            # Fallback (no poster, e.g. older i2v): first frame of the mp4 via ffmpeg.
            if not thumb_path.exists() and video_path:
                _media_tools.video_poster_thumb(video_path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the sync
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(video_media_id, e))

    # 2. Per task: getTaskById -> video outputs -> fileUrl -> download mp4.
    def _do_task(node):
        task = _task_reads.task_detail_gql(session, node["id"])
        outs, shared = _full_meta.video_outputs(task)
        detail = ((task or {}).get("outputs") or {}).get("detailParameters") or {}
        params = (task or {}).get("parameters") or {}
        full_meta = _full_meta.extract_full_meta(task)   # issue #18: the full generation surface (video row)
        rows = []
        for o in outs:
            vmid = o["video_media_id"]
            hit = [p for p in vdir.glob("*_{}.*".format(vmid))
                   if not p.name.endswith(".part") and p.stat().st_size > 0]
            if hit:
                path, status = hit[0], "skip"
            else:
                fm = _full_meta.media_file_gql(session, vmid)
                url = fm.get("fileUrl")
                if not url:
                    rows.append("missing")
                    continue
                stem = vdir / _history.build_stem_name(
                    shared.get("prompt") or node.get("promptsPreview", ""),
                    node["id"], vmid, name_length, name_sep)
                status, path = _media_fetch.download(session, url, stem)
            if status in ("ok", "skip") and path:
                full = _full_meta.build_catalog_row(
                    vmid, fm=full_meta, known=known,   # fm: issue #18 (no preset fill: video)
                    task_id=str(node["id"]),
                    filename=str(path.relative_to(out)).replace("\\", "/"),
                    prompt_full=shared.get("prompt", ""),
                    # NOT prompt_full[:100]: the summary node carries its own preview.
                    prompt_preview=(node.get("promptsPreview") or "")[:100],
                    seed=str(o.get("seed") or ""),
                    created_at=node.get("createdAt", ""),   # a listed task always has one
                    width=str(detail.get("width") or ""),
                    height=str(detail.get("height") or ""),
                    model_id=str(params.get("modelId") or ""),
                    negative_prompt=shared.get("negative_prompt", ""),   # video block, not top level
                    status="completed",
                    is_video="1",
                    poster_media_id=o.get("poster_media_id", ""),
                    paid_credit=_full_meta._paid_credit_str(task),   # actual cost, task-level
                    video_duration=str(shared.get("duration") or ""),
                )
                _ensure_video_thumb(vmid, o.get("poster_media_id"), path)
                _media_tools.video_faststart(path)                # iOS needs moov at the front to stream
                rows.append(full)
            else:
                rows.append(status)
        return rows

    print("Resolving + downloading videos -> videos/ {}...".format(
        "({} workers) ".format(workers) if workers > 1 else ""))
    new_rows, ok, missing = [], 0, 0
    for node, result in _parallel_map(i2v_nodes, _do_task, workers, _prog,
                                      delay=getattr(args, "delay", 0.4)):
        for item in (result or []):
            if isinstance(item, dict):
                new_rows.append(item); ok += 1
            elif item == "missing":
                missing += 1
    if new_rows:
        save_catalog_over_snapshot(db_path, new_rows, known)   # carried in build_catalog_row; merged over the rows as they are NOW
    print("Videos saved/present: {}{}.".format(
        ok, " | {} had no resolvable file url".format(missing) if missing else ""))
    return {"i2v_tasks": len(i2v_nodes), "videos": ok}


# _VIDEO_EXTS is the LIBRARY SCAN section's `"video"` kind, imported at the top of
# this file with the rest of the shared base -- one spelling of the video extension
# set instead of the three this file, the gallery's health walk and the loom bundle
# each used to keep.


def _under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def run_faststart_videos(args):
    """Rewrite every non-faststart mp4 under videos/ so iOS can stream them (lossless
    -c copy +faststart). Idempotent -- skips files already faststart. Touches only the
    video files, never the catalog. Fixes the 'plays on desktop, error 4 on iPhone' bug
    for the existing library; new videos are faststarted at collect time automatically.

    Every video lands in exactly ONE of fixed / skipped / failed, and each failure is named.
    A clip video_faststart refused used to land in NONE of them, so the summary quietly read
    fixed+skipped < total -- and the user, who ran this command precisely because a video
    would not play on their phone, had no way to tell which file was still broken, or even
    that any still was (M04, 2026-07-27).

    'failed' means ffmpeg was asked and could not: nothing else. The first version of this
    accounting asked `_mp4_is_faststart` itself and then treated a False from video_faststart
    as a refusal -- but video_faststart re-asks the same question, and wiki/Backing-Up.md
    blesses running this sweep while the gallery or a live watch is collecting, so the live
    mirror remuxing that clip (or a Trash purge removing it) in between the two checks made
    the sweep print 'FAILED <name> -- still not iOS-playable' about a file that had just been
    FIXED. One question, asked once, by `_video_faststart_attempt`: whatever it says the
    outcome is, is the outcome. A clip someone else repaired BEFORE this sweep reached it
    counts as already-OK; one repaired AFTER we looked gets a harmless second remux and
    counts as rewritten. Neither is a failure, and that is the whole point."""
    out = Path(args.out)
    vdir = out / "videos"
    vids = sorted(p for p in vdir.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".m4v")) if vdir.exists() else []
    if not _media_tools.ffmpeg_path():
        print("ffmpeg not found on PATH; cannot faststart.")
        return {"fixed": 0, "skipped": 0, "failed": 0, "total": len(vids)}
    print("Faststart pass over {} video(s) in {}...".format(len(vids), vdir), flush=True)
    fixed = skipped = 0
    failures = []
    for i, p in enumerate(vids, 1):
        outcome = _media_tools._video_faststart_attempt(p)
        if outcome == _media_tools.FASTSTART_REWROTE:
            fixed += 1
            print("  [{}/{}] faststart -> {}".format(i, len(vids), p.name), flush=True)
        elif outcome == _media_tools.FASTSTART_REFUSED:
            failures.append(p)
            print("  [{}/{}] FAILED {} -- still not iOS-playable (re-run with -v for "
                  "ffmpeg's own reason)".format(i, len(vids), p.name), flush=True)
        else:
            skipped += 1
    print("Done: {} rewritten, {} already OK, {} failed ({} total).".format(
        fixed, skipped, len(failures), len(vids)))
    for p in failures:
        print("  still not faststart: {}".format(p))
    return {"fixed": fixed, "skipped": skipped, "failed": len(failures),
            "total": len(vids)}


def run_import_local(args):
    """Catalog non-PixAI media so it shows + plays in the gallery (source='local').

    Two modes:
      * No dir (or a dir already inside the backup): scan the backup folder and
        catalog any image/video NOT already in the catalog -- i.e. files you
        dropped into videos/ or anywhere under the backup.
      * External dir: copy each media file into the backup (videos/ or imported/)
        then catalog it.

    Idempotent: files already cataloged (by relative path) are skipped, so it's
    safe to re-run. Images get a gallery thumbnail; videos play via the catalog
    filename (no still to thumbnail, so they show a placeholder + the video badge)."""
    from moonglade.backup import load_catalog, PixAIError, save_catalog_over_snapshot, vlog
    import shutil
    from moonglade.thumbs import make_thumbnail
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # import can seed a fresh, download-free backup
    thumb_dir = out / "gallery" / "thumbs"

    raw = getattr(args, "import_local", None)
    src = Path(raw) if raw else out
    if not src.exists():
        raise PixAIError("import path not found: {}".format(src))
    try:
        _s, _o = src.resolve(), out.resolve()
        external = not _under(_s, _o) and _s != _o
        scan_root_is_out = (_s == _o)
    except OSError:
        external = False
        scan_root_is_out = (src == out)

    _prog = getattr(args, "progress", None)
    catalog_rows = load_catalog(db_path)
    existing = {(r.get("filename") or "").replace("\\", "/")
                for r in catalog_rows if r.get("filename")}
    # Also key on media_id: an already-backed-up PixAI file is named after its
    # media id, so media_id_of() of an organized file matches an existing row even
    # though its on-disk path no longer equals the stored `filename` string. This
    # is what stops --import-local from re-cataloging the whole backup as 'local'.
    existing_mids = {r.get("media_id") for r in catalog_rows if r.get("media_id")}
    # The same snapshot as a media_id -> row map, for build_catalog_row's carry. Free
    # (catalog_rows is already in hand). Belt-and-braces here rather than load-bearing:
    # the two guards above mean an already-cataloged file is skipped before it ever
    # reaches the builder, so there is nothing to carry -- but the guarantee lives in
    # the builder for every path, not in each caller's memory.
    known = {r["media_id"]: r for r in catalog_rows if r.get("media_id")}

    # IMPORT_EXCLUDE = the shared quarantine set plus legacy branding/ (named
    # disagreement 5) -- app chrome that must never be catalogued as gallery
    # content, and, for _deleted/, B11 (audit 2026-07-21): purge_media_local()
    # clears a purged image's catalog row when it moves the file there, so without
    # the exclusion the scan finds an orphaned file with no existing row/media_id
    # match and resurrects it as a brand-new source='local' row.
    #
    # Those names only mean anything relative to the backup root, so they apply
    # exactly when the scan root IS the backup root. An external source folder --
    # or a subfolder of the backup handed in explicitly -- excludes nothing, which
    # is what the old `if not external and _under(p, out / "gallery")` chain
    # amounted to: it tested paths rooted at `out`, which could not match anything
    # under a different root.
    excl = IMPORT_EXCLUDE if scan_root_is_out else ()

    print("Scanning {} for media (this can take a moment on a large backup)...".format(src),
          flush=True)
    candidates = []
    for e in scan_library(src, kinds=("image", "video"), exclude=excl):
        candidates.append(e.path)
        if len(candidates) % 5000 == 0:
            vlog("scanned {} media files so far...".format(len(candidates)))
    total = len(candidates)
    print("Found {} media file(s); cataloging new ones...".format(total), flush=True)

    rows, made, skipped = [], 0, 0
    for idx, p in enumerate(candidates):
        if _prog:
            _prog(idx + 1, total, 0)
        is_vid = p.suffix.lower() in _VIDEO_EXTS
        if external:
            dest_dir = out / ("videos" if is_vid else "imported")
            dest_dir.mkdir(parents=True, exist_ok=True)
            mid = _history.local_media_id(p)
            if not mid:
                skipped += 1              # unreadable source; nothing to copy or key on
                continue
            # Decided BEFORE the copy, not after: the id comes from the source's own
            # bytes, so content already in the library can be recognised without
            # writing anything. Copying first and skipping later left the file sitting
            # in imported/ with no row pointing at it.
            if mid in existing_mids:
                skipped += 1
                continue
            # The stored name ends in the CONTENT hash, so a destination that already
            # exists holds the same bytes -- there is nothing to overwrite and nothing
            # to lose. Naming by basename alone silently threw away the second of two
            # different files that happened to share a name (image.png / 00001.png out
            # of separate folders is ordinary, not a corner case) while still counting
            # it as imported, so the loss only surfaced once the original was gone.
            dest = dest_dir / _history.build_local_name(p, mid)
            if not dest.exists():
                shutil.copy2(p, dest)
            stored = dest
        else:
            stored = p
            mid = _history.local_media_id(stored)
            if not mid:
                skipped += 1
                continue
        rel = str(stored.relative_to(out)).replace("\\", "/")
        if rel in existing or mid in existing_mids or media_id_of(stored) in existing_mids:
            skipped += 1                  # already cataloged (by path, content, or PixAI id)
            continue
        existing_mids.add(mid)            # two sources, one content: catalog it once
        try:
            # UTC + Z, matching the PixAI-sourced rows' `createdAt` format below --
            # `created_at` is sorted as a plain string (_SORT_SQL has no datetime()
            # wrapping), so a naive LOCAL-time stamp here reads as hours "older" than
            # a same-moment UTC one west of Greenwich, silently outranked by anything
            # PixAI collected since (a local save at 23:0X PDT sorted behind rows
            # timestamped 06:05 UTC the "next" day, an hour earlier in real time).
            created = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(stored.stat().st_mtime))
        except OSError:
            created = ""
        rows.append(_full_meta.build_catalog_row(
            mid, known=known, filename=rel, source="local",
            status="imported", created_at=created,
            prompt_preview=stored.stem[:100],       # no prompt: name the file after itself
            is_video="1" if is_vid else ""))        # no fm: a local file has no task
        if is_vid:
            _media_tools.video_poster_thumb(stored, thumb_dir / "{}.jpg".format(mid))  # ffmpeg, optional
            _media_tools.video_faststart(stored)                  # iOS needs moov at the front to stream
        else:
            make_thumbnail(stored, thumb_dir / "{}.jpg".format(mid))
        made += 1
        vlog("imported {} ({})".format(rel, "video" if is_vid else "image"))

    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
    print("Imported {} new local file(s){}; {} already cataloged.".format(
        made, " (copied into the backup)" if external else "", skipped))
    # Anything imported before content-addressing came in still carries its original
    # basename and a path-derived id. Bring those onto the same scheme here rather
    # than leaving the library split across two conventions.
    migrated, mig_skipped = _history.migrate_local_filenames(out, db_path, thumb_dir)
    if migrated or mig_skipped:
        print("Renamed {} earlier import(s) to the current naming{}.".format(
            migrated,
            "; {} left alone (locked or already present)".format(mig_skipped)
            if mig_skipped else ""))
    # media_ids of the rows created THIS run -- the web importer uses them to tag an
    # optional collection; CLI callers that only read imported/skipped are unaffected.
    return {"imported": made, "skipped": skipped,
            "media_ids": [r["media_id"] for r in rows]}


def _resolved_loras(session, task):
    """The task's LoRAs as a readable string, for a row being catalogued live.

    extract_full_meta returns `loras: ""` on purpose and documents that the caller fills it;
    --backfill-full-meta does, and the live capture did not, so a generation's LoRAs were
    blank until a backfill happened past. Resolution is name lookups behind model_name_gql's
    process cache, so a batch costs one call per distinct LoRA at most. A failure costs the
    label, never the row.
    """
    try:
        return _full_meta.resolve_loras(session, task) or ""
    except Exception:                                  # noqa: BLE001
        return ""


def _resolved_model_name(session, fm, model_id):
    """The model's human-readable name for a row being catalogued live.

    extract_full_meta sets model_name only for a chat task (Edit/Fix, resolved locally from
    EDIT_MODELS); for an ordinary generation it is blank and the caller is expected to fill
    it -- which the backfill does and the live capture did not. Falls back to whatever
    extract_full_meta had, then to blank, so a lookup failure costs the label and never the
    row.
    """
    have = str((fm or {}).get("model_name") or "").strip()
    if have:
        return have
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    try:
        return _models.model_name_gql(session, mid) or ""
    except Exception:                                  # noqa: BLE001
        return ""


def _edit_model_label(session, fm, model_id):
    """The model name to store on an EDIT (chat-task) row -- resolvable, never a dead end.

    This used to be `fm.get("model_name", "") or "Edit"`. extract_full_meta fills model_name
    for a chat task only from the local EDIT_MODELS table, so an edit made with any model NOT
    in those two hardcoded entries -- `--edit-image --params-json` with a newer modelId, or
    `--task-id` recovering a chat task made on PixAI's web UI after this table was last
    updated -- landed the literal string "Edit" in the catalog. That string is worse than
    blank: `_needs_model_fix` sees a non-empty, non-digit name that differs from the model_id,
    calls the row resolved, and --fix-models never queues it. The row showed the generic
    "Edit" forever, having also lost WHICH edit model made it, and no re-run could repair it
    (M17, 2026-07-27).

    So an unknown edit model goes through the same _resolved_model_name every ordinary
    generation uses. Whatever that returns is recoverable: a real name is the answer; the id
    (its soft-failure return) and "" both make `_needs_model_fix` hand the row to
    --fix-models on the next run.

    "Edit" survives for the one case it was ever right about -- a chat task carrying NO model
    id at all, where there is nothing to resolve and nothing for --fix-models to queue
    regardless (it returns '' for an id-less row), so a generic label costs nothing and beats
    an empty Model field."""
    mid = str(model_id or "").strip()
    if not mid:
        return str((fm or {}).get("model_name") or "").strip() or "Edit"
    return _resolved_model_name(session, fm, mid)


def _needs_model_fix(row):
    """Return the model version-id to resolve if this row's model_name is missing
    or still a raw numeric id; else ''. Handles the case where model_name was
    set to the numeric id (the model lookup failed on an earlier run).

    Only a NUMERIC id is ever handed to the version lookup. A video row collected before
    2026-09-26 stored the engine NAME ("tbkv1.0.1", "v4.0.1") in model_id, and this passed it
    to getGenerationModelByVersionId as if it were a version id -- a lookup that can only
    fail (retried and printed every --sync) or answer "unresolved", which --relabel-removed
    then stamps permanently (PROBE_2026-09-26 V09). Those rows are repaired offline by the
    gallery's catalog migration instead. A video row WITH a numeric id and a blank name is
    filled like any other row: video model names are dynamic (owner ruling 3, 2026-09-26) --
    unless the id is not its engine's own (_video_model_id_fits): --sync-videos files a v2.7 /
    v3.0.1 clip under the IMAGE checkpoint its task carried, and titling that would put an
    image model's name on a video row (review V-R2)."""
    mid = (row.get("model_id") or "").strip()
    name = (row.get("model_name") or "").strip()
    if not mid and name.isdigit():
        mid = name  # model_name itself is the numeric id
    if not mid or not mid.isdigit():
        return ""
    if (str(row.get("is_video") or "").strip() == "1"
            and not _gen_params._video_model_id_fits(row.get("video_model"), mid)):
        return ""
    if not name or name == mid or name.isdigit():
        return mid
    return ""


def run_fix_models(args):
    """Re-resolve human-readable model names for catalog rows whose model_name is
    blank or still a numeric version-id (e.g. saved while the model lookup was failing).
    One API call per distinct model id (cached)."""
    from moonglade.backup import (_ensure_db, load_catalog, _make_session, _parallel_map,
                                  save_catalog_over_snapshot)
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    rows = load_catalog(db_path)
    # As loaded: the save at the end merges over the rows as they are THEN (a Sync step).
    snapshot = {r["media_id"]: dict(r) for r in rows if r.get("media_id")}

    to_resolve = {}   # version_id -> rows needing it
    for r in rows:
        vid = _needs_model_fix(r)
        if vid:
            to_resolve.setdefault(vid, []).append(r)

    if not to_resolve:
        print("No model names need fixing -- catalog already has readable names.")
        return {"fixed": 0, "models": 0, "unresolved": 0}

    relabel = getattr(args, "relabel_removed", False)
    removed_label = "Unknown or removed model"
    workers = max(1, getattr(args, "workers", 1) or 1)
    print("Resolving {} distinct model id(s) across {} rows{}...".format(
        len(to_resolve), sum(len(v) for v in to_resolve.values()),
        " ({} workers)".format(workers) if workers > 1 else ""))
    _prog = getattr(args, "progress", None)
    fixed = relabeled = unresolved = 0
    # Ids whose lookup FAILED (network/timeout/5xx), as opposed to answering "no such model".
    # --relabel-removed writes a permanent label that _needs_model_fix then reads as
    # "resolved", so a run must never act on a failure it could simply leave for the next one
    # (M18, 2026-07-27). _parallel_map calls on_error before yielding that item, so the set
    # is always populated by the time the loop body below tests it.
    lookup_failed = set()

    def _note_lookup_failure(vid, exc):
        lookup_failed.add(vid)
        print("  model {} could not be checked ({}) -- left untouched for the next run".format(
            vid, str(exc)[:160]))

    for vid, name in _parallel_map(sorted(to_resolve),
                                   lambda v: _models.model_name_gql(session, v, strict=True),
                                   workers, _prog, delay=getattr(args, "delay", 0.4),
                                   on_error=_note_lookup_failure):
        if name and name != vid and not str(name).isdigit():
            for r in to_resolve[vid]:
                r["model_name"] = name
                fixed += 1
        elif vid in lookup_failed:
            # Not counted as unresolved either: "unresolved" means PixAI answered and had no
            # name, and the summary's model tally is derived from it. This id simply was not
            # examined, and re-running --fix-models will pick the same rows up again because
            # nothing was written over them.
            continue
        else:
            unresolved += 1
            if relabel:
                for r in to_resolve[vid]:
                    r["model_name"] = removed_label  # model_id kept for reference
                    relabeled += 1
                print("  {} unresolved -> '{}'".format(vid, removed_label))
            else:
                print("  could not resolve model {} (left as-is)".format(vid))

    if fixed or relabeled:
        save_catalog_over_snapshot(db_path, rows, snapshot, blank_keeps=False)
    print("\nFixed {} row(s) across {} model(s); {} id(s) unresolved{}{}.".format(
        fixed, len(to_resolve) - unresolved - len(lookup_failed), unresolved,
        " (relabeled {} rows to '{}')".format(relabeled, removed_label) if relabeled else "",
        "; {} id(s) not checked -- lookup failed, re-run to finish them".format(
            len(lookup_failed)) if lookup_failed else ""))
    return {"fixed": fixed, "relabeled": relabeled,
            "models": len(to_resolve) - unresolved - len(lookup_failed),
            "unresolved": unresolved, "lookup_failed": len(lookup_failed)}


# When the archive-only flags were last rewritten: the Broken files list's LOST line says "gone
# from your PixAI history as of <date>", and this is that date (Session W, W5a).
RECONCILE_STAMP = "reconcile_stamp.json"


# The task statuses that end with no picture at all: nothing to back up, ever.
_NO_PICTURE_STATUSES = frozenset({"failed", "cancelled", "canceled", "rejected", "error"})


def feed_counts(nodes, have_task_ids):
    """What a full walk of the live feed says about backing it up (the header's Backed up pill,
    moonglade.gallery.backup_coverage). `nodes` are the feed's task summaries, `have_task_ids`
    the catalog's task ids. Returns {live, no_picture, in_progress, missing}:
      no_picture   a failed or cancelled generation -- PixAI made no picture, so there is
                   nothing to fetch and nothing will ever fix it; the pill does not count it
      in_progress  still queued or running (counted once it finishes)
      missing      finished with a picture, and not in the catalog: what Sync now fetches."""
    have = set(have_task_ids or ())
    live = no_picture = in_progress = missing = 0
    for node in nodes or ():
        tid = str(node.get("id") or "")
        if not tid:
            continue
        live += 1
        st = str(node.get("status") or "").strip().lower()
        if st in _NO_PICTURE_STATUSES:
            no_picture += 1
        elif st and st != "completed":
            in_progress += 1
        elif not _history.media_ids_for(node):
            no_picture += 1                  # finished, but PixAI lists no picture for it
        elif tid not in have:
            missing += 1
    return {"live": live, "no_picture": no_picture, "in_progress": in_progress,
            "missing": missing}


def read_reconcile_stamp(out):
    """reconcile_stamp.json as a dict, or {} when there is none or it will not read."""
    try:
        doc = json.loads(_paths.records_path(out, RECONCILE_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _stamp_reconcile(out, flagged, cleared, counts=None):
    """Write reconcile_stamp.json among the library's records, atomically. Advisory, like the
    reconcile itself: a disk that refuses it costs the date on a LOST line, nothing more.
    `counts` (feed_counts) rides along for the Backed up pill."""
    from moonglade.backup import _atomic_replace
    doc = {"reconciled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "flagged": flagged, "cleared": cleared}
    for k, v in (counts or {}).items():
        doc[k] = int(v)
    dest = _paths.records_path(out, RECONCILE_STAMP)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        _atomic_replace(tmp, dest)
    except OSError:
        pass


def run_reconcile_deleted(args):
    """Find catalog rows whose PixAI task no longer exists in your live feed -- i.e.
    generations you deleted on the website -- and flag them (deleted_remote='1') so
    the gallery can surface them for a local prune. Closes the cloud->local delete
    drift. Advisory: re-running refreshes the flags. Skips imports (no task) and
    very-recent rows (a fresh generation may not have propagated to the feed yet)."""
    from moonglade.backup import (_ensure_db, load_catalog, _make_session, PixAIError,
                                  save_catalog, vlog)
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    _prog = getattr(args, "progress", None)

    print("Scanning your live PixAI feed for existing task ids...")
    # `complete` is set ONLY by a page saying there is nothing older. Every row missing from
    # `live` is flagged below, so a walk that stopped anywhere else (no page in the answer, an
    # empty page while PixAI says older ones exist) must flag nothing: a partial `live` would
    # mark tasks that still exist on PixAI as deleted, and the gallery offers those for a
    # bulk local Delete.
    live, before, page, complete = set(), None, 0, False
    nodes = []                         # every summary, for feed_counts (the Backed up pill)
    while True:
        conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
            getattr(args, "page_size", 250) or 250,
            _pixai_client._client_of(session).user_id, before)))
        if not conn:
            break
        edges = conn.get("edges") or []
        pi = conn.get("pageInfo") or {}
        if not edges:
            complete = not pi.get("hasPreviousPage")
            break
        for e in edges:
            node = e.get("node") or {}
            tid = node.get("id")
            if tid:
                live.add(str(tid))
                nodes.append(node)
        page += 1
        vlog("reconcile: page {}, {} live tasks so far".format(page, len(live)))
        if not pi.get("hasPreviousPage"):
            complete = True
            break
        before = pi.get("startCursor")
    if not complete:
        raise PixAIError("Live feed ended early -- nothing was flagged.")
    print("Live tasks in your feed: {:,}".format(len(live)))
    if not live:
        raise PixAIError("Live feed returned no tasks -- aborting so we don't flag "
                         "your whole catalog by mistake.")

    grace = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 2 * 86400))
    rows = load_catalog(db_path)
    flagged = cleared = 0
    for r in rows:
        tid = (r.get("task_id") or "").strip()
        gone = (tid and tid not in live and (r.get("source") or "") != "local"
                and (r.get("created_at") or "") < grace)
        was = r.get("deleted_remote") == "1"
        if gone and not was:
            r["deleted_remote"] = "1"; flagged += 1
        elif not gone and was:
            r["deleted_remote"] = ""; cleared += 1
        else:
            r["deleted_remote"] = "1" if gone else ""
    save_catalog(db_path, rows)
    counts = feed_counts(nodes, {(r.get("task_id") or "").strip() for r in rows})
    _stamp_reconcile(out, flagged, cleared, counts)
    print("Flagged {:,} row(s) as deleted-on-PixAI; cleared {:,} stale flag(s).".format(
        flagged, cleared))
    print("Review in the gallery: Source -> 'Deleted on PixAI', then bulk Delete (local).")
    return dict(counts, live=len(live), flagged=flagged, cleared=cleared)


class DiskCounts(tuple):
    """(originals_count, originals_bytes, thumbnail_count), with the TRASH carried alongside.

    A real 3-tuple, so every `n, b, thumbs = _count_backup_images(out)` call site keeps
    unpacking exactly as it always did; the `_deleted/` totals ride as attributes because a
    fourth slot would have broken that contract. Same trick, and the same reason, as
    ClaimsResult above: the caller that wants the extra fact can ask for it, and the ones
    that don't are untouched.

    Why the extra fact exists at all: quarantined files were simply DROPPED from the scan
    (M06's fix), and dropping them silently would trade one wrong number for another --
    'Image files on disk' would stop matching what `du` says about the folder, with nothing
    on screen explaining the gap. --catalog-stats is the command the wiki points at for
    deciding what to clean up, and 'N files are already in the trash, purge to reclaim X' is
    the single most actionable line that scan can produce."""

    def __new__(cls, originals, originals_bytes, thumbs, trashed=0, trashed_bytes=0):
        self = super().__new__(cls, (originals, originals_bytes, thumbs))
        self.trashed = trashed
        self.trashed_bytes = trashed_bytes
        return self


def _count_backup_images(out):
    """Count the ORIGINAL image files on disk, split from preview thumbnails. The naive
    rglob-for-_IMAGE_EXTS double-counts because gallery/thumbs/<id>.jpg is one .jpg per image --
    which made 'files on disk' look ~2x the catalog. Excludes gallery/ (thumbs), _duplicates/
    (quarantined) and _deleted/ (the soft-delete quarantine). Returns a DiskCounts:
    (originals_count, originals_bytes, thumbnail_count) plus .trashed / .trashed_bytes.

    `_deleted/` was NOT excluded until M06 (2026-07-27), while run_download's own disk
    scanner in this file has excluded all three for longer (B11, audit 2026-07-21). Soft-
    deleted images are still real files pending a purge, so counting them as part of the
    active library inflated exactly the number a user reads before deciding what to delete --
    on the screen the wiki's 'Reclaiming disk space' section sends them to. They are now
    reported SEPARATELY rather than dropped, so the total still accounts for the whole
    folder."""
    out = Path(out)
    # The one walker that does NOT want the quarantine trees pruned -- it counts
    # them into separate columns instead of dropping them, so it asks for
    # `exclude=()` and splits on the entry's own top-level folder against the
    # shared dirnames. Case-normalized because the old `dir in p.parents` test was
    # (Path comparison is case-insensitive on Windows).
    _norm = os.path.normcase
    _gallery, _deleted, _dupes = (_norm(GALLERY_DIRNAME), _norm(DELETED_DIRNAME),
                                  _norm(DUPLICATES_DIRNAME))
    _records = _norm(_paths.LIBRARY_APP_DIRNAME)
    n = b = thumbs = trashed = trashed_bytes = 0
    for e in scan_library(out, kinds=("image",), exclude=()):
        top = _norm(e.rel.parts[0]) if len(e.rel.parts) > 1 else ""
        if top == _gallery:
            thumbs += 1
        elif top == _deleted:
            trashed += 1
            trashed_bytes += e.size or 0
        elif top == _dupes:
            pass                       # quarantined duplicates: neither live nor trash
        elif top == _records:
            pass                       # the app's own folder (_moonglade/), never pictures
        else:
            n += 1
            b += e.size or 0
    return DiskCounts(n, b, thumbs, trashed, trashed_bytes)


def run_rebuild_similar(args):
    """--rebuild-similar: drop + re-embed the visual-similarity ('Similar') index from
    scratch off the on-disk backup. Cures a corrupted/duplicate-index table by building
    ONE clean named index. Uses the shared progress callback (terminal bar + Control Panel
    marker). No network; needs torch/pixeltable. Run it when the gallery is NOT serving
    Similar queries (both touch the same embedded Postgres)."""
    try:
        from moonglade import similar as ps
    except Exception as e:
        sys.exit("Similar index unavailable (pixeltable/torch not installed): {}".format(e))
    if not ps.is_available():
        sys.exit("Similar index needs torch -- install the ML deps (torch/transformers/pixeltable).")
    out = Path(args.out)
    if not out.exists():
        sys.exit("No backup dir at {}.".format(out))
    print("Rebuilding the Similar index from {} -- drops the old table, re-embeds every image.".format(out))
    n = ps.rebuild(ps.scan_dir(out), progress=getattr(args, "progress", None))
    print()  # finish the \r progress line
    print("Similar index rebuilt: embedded {:,} images ({:,} in index, {} skipped).".format(
        n, ps.count(), ps.sync.last_errors))


def run_sync_similar(args):
    """--sync-similar: TOP UP the visual-similarity index -- embed only images it doesn't
    already have. The incremental counterpart to --rebuild-similar.

    This exists because sync() was always incremental (it skips media_ids already in the index)
    while the only way to reach it was rebuild(), which DROPS the table first. So the sole
    available action was also the most destructive one, and after an interrupted build the
    obvious move threw away every row that had survived.

    Measured on the owner's library, 2026-07-26, after a machine-wide memory exhaustion killed a
    rebuild at 75%: topping up the missing 8,706 images took 11.7 min, against ~38 min to
    re-embed all 35,106 from scratch -- and it could not lose the 26,400 rows already there,
    whereas a fresh rebuild dying again would have left strictly less than it started with.

    Prefer this. Reach for --rebuild-similar only to cure an index that is actually broken
    (duplicate/corrupt), not merely incomplete. No network; needs torch/pixeltable. Run it while
    the gallery is NOT serving Similar queries -- both use the same embedded Postgres."""
    try:
        from moonglade import similar as ps
    except Exception as e:
        sys.exit("Similar index unavailable (pixeltable/torch not installed): {}".format(e))
    if not ps.is_available():
        sys.exit("Similar index needs torch -- install the ML deps (torch/transformers/pixeltable).")
    out = Path(args.out)
    if not out.exists():
        sys.exit("No backup dir at {}.".format(out))
    before = ps.count()
    print("Topping up the Similar index from {} -- {:,} already indexed, embedding only what's "
          "missing.".format(out, before))
    n = ps.sync(ps.scan_dir(out), progress=getattr(args, "progress", None))
    print()  # finish the \r progress line
    after = ps.count()
    if not n:
        print("Similar index already complete: {:,} images, nothing to add.".format(after))
    else:
        print("Similar index topped up: embedded {:,} new images ({:,} -> {:,} in index, "
              "{} skipped).".format(n, before, after, ps.sync.last_errors))


def _one_line(text, width):
    t = " ".join(str(text or "").split())
    return t if len(t) <= width else t[:width - 1].rstrip() + "\u2026"


def run_search(args):
    """--search / --export-csv: the gallery's own search, from the command line. Reads
    catalog.db only -- no network, nothing written except the CSV a caller names. The query
    goes through the SAME parser the search box uses (moonglade.gallery.query_catalog)."""
    from moonglade.backup import _ensure_db, load_catalog
    try:     # a prompt with characters the console cannot show must not stop the listing
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    out = Path(args.out)
    db_path = _ensure_db(out)
    q = (getattr(args, "search", None) or "").strip()
    if q:
        rows, _ = query_catalog(db_path, q=q, page=1, page_size=None, sort="newest")
    else:
        rows = load_catalog(db_path)
    csv_path = getattr(args, "export_csv", "")
    if csv_path:
        # newline="" so the file's line endings are the CSV writer's own, as the download's are
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(catalog_csv_text(rows))
        print("Wrote {} row(s) to {}".format(len(rows), csv_path))
        if not q:
            return
    limit = int(getattr(args, "limit", 50) or 0)
    shown = rows[:limit] if limit > 0 else rows
    if getattr(args, "search_json", False):
        print(json.dumps([{"media_id": r.get("media_id", ""), "created_at": r.get("created_at", ""),
                           "model": r.get("model_name", ""), "rating": r.get("rating", ""),
                           "prompt": r.get("prompt_full") or r.get("prompt_preview") or ""}
                          for r in shown], ensure_ascii=False, indent=2))
        return
    for r in shown:
        print("{}  {}  {}  {}  {}".format(
            r.get("media_id", ""), str(r.get("created_at", ""))[:10],
            _one_line(r.get("model_name", ""), 24) or "-",
            ("%s*" % r["rating"]) if r.get("rating") else "-",
            _one_line(r.get("prompt_full") or r.get("prompt_preview"), 70)))
    if len(shown) < len(rows):
        print("... {} of {} match(es) shown; --limit 0 for all, --export-csv PATH for a file".format(
            len(shown), len(rows)))
    else:
        print("{} match(es)".format(len(rows)))


def run_catalog_stats(args):
    """Summarize the existing catalog (no network needed)."""
    from moonglade.backup import _ensure_db, _format_size, load_catalog
    out = Path(args.out)
    db_path = _ensure_db(out)
    _prog = getattr(args, "progress", None)
    rows = load_catalog(db_path)
    n = len(rows)
    total = downloaded = missing = pending = 0
    for i, row in enumerate(rows):
        total += 1
        if row.get("filename"):
            downloaded += 1
        elif not row.get("url"):
            missing += 1
        else:
            pending += 1
        if _prog and (i % 1000 == 0 or i + 1 == n):
            _prog(i + 1, n)
    # paid_credit is a TASK-level cost stamped on each of the task's media rows --
    # tally once per task_id (a 4-image batch is ONE spend), never per row. Rows
    # with '' never tracked a cost and stay out of the tally entirely.
    task_cost = {}
    for row in rows:
        pc = (row.get("paid_credit") or "").strip()
        tid = row.get("task_id") or row.get("media_id")
        if pc and tid not in task_cost:
            try:
                task_cost[tid] = int(float(pc))
            except ValueError:
                pass
    print("Catalog: {}".format(db_path))
    print("Total image entries : {}".format(total))
    print("  downloaded files  : {}".format(downloaded))
    print("  resolved, pending : {}".format(pending))
    print("  no URL (missing)  : {}".format(missing))
    if task_cost:
        print("Credits tracked     : {:,} spent across {:,} tasks ({:,} free)".format(
            sum(task_cost.values()), len(task_cost),
            sum(1 for v in task_cost.values() if v == 0)))
    _print_meta_coverage(rows, total)
    counts = _count_backup_images(out)
    disk_count, disk_bytes, thumb_count = counts
    if disk_count:
        print("Image files on disk : {}  ({})".format(disk_count, _format_size(disk_bytes)))
    if thumb_count:
        print("  + {} preview thumbnails (gallery/thumbs, not originals)".format(thumb_count))
    # The trash is real disk space that is NOT part of the library, and this screen is where
    # a user decides what to reclaim -- so it is named and costed rather than folded into the
    # library total (which is what it used to be) or dropped without a word (M06).
    if counts.trashed:
        print("  + {} soft-deleted in {}/ ({}) -- purge in the gallery's Trash to reclaim"
              .format(counts.trashed, DELETED_DIRNAME, _format_size(counts.trashed_bytes)))


# Columns whose EMPTINESS unambiguously means "never fetched". Deliberately NOT `loras`
# or `negative_prompt`: a generation with no LoRAs and no negative prompt stores those blank
# too, so a blank one cannot be told apart from one that was never filled, and reporting them
# as a coverage gap would send you off to re-fetch tasks that are already complete.
#
# `paid_credit` IS unambiguous despite free generations existing -- a free task stores "0",
# and only a never-tracked one stores "".
_META_COVERAGE = (
    ("full metadata", "prompt_full", "--backfill-full-meta"),
    ("model id", "model_id", "--backfill-full-meta"),
    ("model name", "model_name", "--backfill-full-meta"),
)


def _print_meta_coverage(rows, total):
    """How much of the catalog actually carries its metadata, and what a sweep would cost.

    Without this the stats screen can say "35,133 entries, all downloaded" about a catalog in
    which not one row knows which model made it -- the counters only ever described FILES.
    Coverage is what decides whether a sweep is due, and the unique-task count is what it
    costs: metadata is fetched once per task, so a 4-image batch is one call, not four.
    """
    if not total:
        return
    print("Metadata coverage   :")
    worst_missing_tasks = 0
    for label, col, fix in _META_COVERAGE:
        have = sum(1 for r in rows if (r.get(col) or "").strip())
        gap = [r for r in rows if not (r.get(col) or "").strip()]
        tasks = len({r.get("task_id") for r in gap if r.get("task_id")})
        worst_missing_tasks = max(worst_missing_tasks, tasks)
        line = "  {:<17}: {:,} / {:,} ({:.0f}%)".format(label, have, total,
                                                        100.0 * have / total)
        if gap:
            line += "  -- {:,} missing across {:,} tasks".format(len(gap), tasks)
        print(line)
    # Locally imported files have no PixAI task behind them, so they can NEVER carry a model
    # and are not a gap to chase. Counted separately rather than silently deflating the
    # percentages above, which would make a complete catalog look permanently short.
    local = sum(1 for r in rows if (r.get("source") or "").strip() == "local")
    if local:
        print("  {:<17}: {:,} imported locally -- no PixAI task, so no model to fetch"
              .format("of which", local))
    if worst_missing_tasks:
        print("  Fill them with    : --backfill-full-meta --workers 8"
              "   (resumable; skips rows already filled)")
    costed = sum(1 for r in rows if (r.get("paid_credit") or "").strip())
    if costed < total:
        print("  Cost history      : add --with-credit to recover spend on older tasks")

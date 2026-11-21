#!/usr/bin/env python3
"""
moonglade/gallery.py
================
Local Flask web gallery for your PixAI backup collection.

Reads catalog.db (SQLite) and serves a browseable, filterable, paginated image
gallery at http://localhost:5000 . Supports single and bulk delete (removes
image file, thumbnail, and catalog row).

Requirements:
    pip install flask pillow

Usage (from the app's folder; normally the launcher, Moonglade Launcher, starts it):
    python -m moonglade.gallery
    python -m moonglade.gallery --out pixai_backup --port 5000
"""

import argparse
import csv
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from moonglade import about as _about
from moonglade import account_prefs as _account_prefs
from moonglade import ach_beacon as _ach_beacon
from moonglade import achievements as _achievements
from moonglade import assets as moonglade_assets
from moonglade import branding as _branding
from moonglade import cards as _cards
from moonglade import catalog as _catalog
from moonglade import catalog_search as _catalog_search
from moonglade import catalog_verbs as _catalog_verbs
from moonglade import cloud_delete as _cloud_delete
from moonglade import container as moonglade_container
from moonglade import contest_sync as _contest_sync
from moonglade import contest_wins
from moonglade import contests as _contests
from moonglade import curation as _curation
from moonglade import dupes as _dupes
from moonglade import gen_cli as _gen_cli
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import health as _health
from moonglade import jobs as _jobs
from moonglade import living as _living
from moonglade import loom_files as _loom_files
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import name_hunt as _name_hunt
from moonglade import organize as _organize
from moonglade import pages as _pages
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import pricing as _pricing
from moonglade import redact as _redact
from moonglade import scan as _scan
from moonglade import scenes as _scenes
from moonglade import series as _series
from moonglade import hostcheck as _hostcheck
from moonglade import settings as _settings
from moonglade import task_feed as _task_feed
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import train_guard as _train_guard
from moonglade import training as _training
from moonglade import updater as _updater
from moonglade import secure_files as _secure_files
from moonglade import watch_plans as _watch_plans
from moonglade import web_policy as _web_policy
from moonglade import web_sessions as _web_sessions
from moonglade import web_tiers as _web_tiers

try:
    from flask import (Flask, g as _flask_g, jsonify, redirect, render_template_string, request,
                       send_file, send_from_directory, session, url_for)
    from flask.sessions import SecureCookieSessionInterface
except ImportError:
    sys.exit("Flask is required for the gallery server.\n"
             "Install it with:  pip install flask")

try:
    from PIL import Image
except ImportError:
    Image = None  # thumbnails will be skipped with a warning

# Windows-only: every subprocess this app spawns (ffmpeg/ffprobe thumbnail work,
# the PowerShell shortcut writer, git for the build stamp, the Panel's CLI jobs)
# would otherwise briefly flash a console window into view. 0x08000000 is the
# stable Win32 CREATE_NO_WINDOW value (same constant subprocess.CREATE_NO_WINDOW
# exposes on Windows) -- hardcoded so this doesn't need `subprocess` imported at
# module scope just for this. Evaluates to 0 (no-op) on non-Windows platforms.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# DELETED_DIRNAME (the recoverable-purge folder) is defined in the LIBRARY SCAN
# section above, beside the other directory names every walker shares.

# How many tasks /api/delete-preview describes image-by-image before it stops and just
# counts the rest. A DISPLAY bound only -- the totals it returns are always exact for
# the whole selection. 24 tasks is up to ~100 thumbnails, which is already more than
# anyone reads in a confirm dialog; selecting a thousand images would otherwise build a
# megabyte of JSON and a thumbnail wall the modal cannot scroll through.
DELETE_PREVIEW_TASK_CAP = 24

# How many selected tasks /api/delete-preview will READ BACK FROM PIXAI before it stops
# checking and says the counts are an estimate (owner, 2026-09-07: "one live read per
# selected task, capped at 40; above that the preview says it is an estimate, and the
# delete still keeps back what the live read finds").
#
# Unlike DELETE_PREVIEW_TASK_CAP above -- a DISPLAY bound -- this one changes what the
# numbers MEAN. At or below it the preview is exact against the cloud: an image the owner
# deleted on PixAI's own website is reported as already gone rather than counted among the
# files this delete will take. Above it nothing is read and the modal says so, which is
# honest and costs nothing; the delete itself still reads every task before it acts
# (_rows_the_bulk_purge_must_keep), so nothing is at risk either way.
#
# 40 is the owner's number. Note it is ABOVE the display cap, deliberately: tasks 25-40 are
# never drawn as strips but their images are still counted, and the totals are what he reads
# to decide.
DELETE_PREVIEW_LIVE_CAP = 40
# The same pool width build_thumbnails() has used for its own fan-out (workers=8). 40 reads
# eight at a time is five rounds, not forty round trips in a row.
DELETE_PREVIEW_LIVE_WORKERS = 8
# A wall-clock ceiling on the whole fan-out, and a real one (2026-09-07): _preview_live_gone
# spends it three ways -- it starts no read after the deadline, gives each read a socket
# timeout no longer than the budget has LEFT, and stops collecting at the deadline without
# waiting for the pool to drain. The first of those was the whole enforcement until this
# date, which bounded only when a read STARTED: one connection that stalled after the
# handshake could run out the transport's own 60s and then retry for another, so the route
# could block for ~2 minutes against the 12 it promised. Whatever has not answered by the
# deadline is reported unverified, exactly like a read that failed.
#
# api.js's deletePreview carries a fetch timeout a little ABOVE this (DELETE_PREVIEW_MS),
# so the dialog always gets an answer -- the server's, in the ordinary case, and the
# client's plain "PixAI did not answer in time" only if the server itself goes silent.
DELETE_PREVIEW_LIVE_BUDGET_S = 12.0


def _trash_meta_path(out_dir, media_id):
    """Sidecar path for a quarantined item's snapshotted catalog row (see
    _snapshot_before_purge). Lives beside the quarantined file itself, keyed by
    media_id rather than filename so it's a one-line lookup from either direction."""
    return Path(out_dir) / _scan.DELETED_DIRNAME / "{}.json".format(media_id)


def _read_trash_meta(out_dir, media_id):
    """The snapshotted row for a quarantined media_id, or None if it predates this
    feature (2026-07-24) or the write failed at purge time. Never raises -- a
    missing/corrupt sidecar just means the trash panel falls back to bare
    filename/mtime, not an error."""
    p = _trash_meta_path(out_dir, media_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _snapshot_before_purge(db_path, out_dir, media_id):
    """Write out_dir/_deleted/<media_id>.json with the row's own fields (rating,
    collections, prompt, task_id, ...) BEFORE delete_from_catalog() removes it for
    good. the 2026-07-21 audit's scoping note on the restore-panel row: "ratings/
    collections on old purges are gone (no manifest existed -- a purge-time snapshot
    for future deletes is part of the build)" -- this is that snapshot. The trash
    panel's restore path reads it back to reinsert a FULL row instead of a bare
    media_id/filename stub; its list path reads it for a real deleted_at instead of
    guessing from file mtime. Best-effort: a write failure must never block the
    purge itself, same fail-soft contract as the file-move/thumb-unlink around it."""
    import time
    row = _catalog.get_row(db_path, media_id)
    if not row:
        return
    snap = dict(row)
    snap["_deleted_at"] = time.time()
    try:
        _trash_meta_path(out_dir, media_id).write_text(
            json.dumps(snap), encoding="utf-8")
    except OSError:
        pass


def purge_media_local(out_dir, thumb_dir, db_path, media_id, filename, quarantine=True):
    """Remove a media's catalog row + (regenerable) thumbnail, and either move its
    file to out_dir/_deleted/ (default, recoverable) or hard-delete it. Returns the
    new quarantine location (Path) when moved, else None.

    Raises OSError if the file could not be moved/removed, WITHOUT touching the
    catalog row -- see the move itself for why. Callers must handle that: the row is
    still there and so is the file, so nothing was lost, but nothing was deleted
    either and the user has to be told.

    When quarantining, also snapshots the about-to-be-deleted catalog row to a JSON
    sidecar (see _snapshot_before_purge) so a later restore can recover more than a
    bare filename. Skipped in hard-delete mode (quarantine=False): nothing is left
    to restore, so there's nothing worth snapshotting."""
    out_dir = Path(out_dir)
    img = _catalog_verbs.find_image_file(out_dir, media_id, filename)
    moved = None
    if img and img.exists():
        if quarantine:
            qdir = out_dir / _scan.DELETED_DIRNAME
            qdir.mkdir(parents=True, exist_ok=True)
            dest = qdir / img.name
            if dest.exists():                       # don't clobber an earlier delete
                dest = qdir / "{}_{}{}".format(img.stem, media_id, img.suffix)
            _snapshot_before_purge(db_path, out_dir, media_id)
            # Deliberately NOT caught: a failed move (antivirus or a sync client holding
            # the file for a moment, or a library on a different volume than out_dir,
            # which makes this rename cross-device) leaves the file exactly where it
            # was. Swallowing it and clearing the row anyway orphaned the file -- gone
            # from the gallery AND absent from _deleted/, so the trash panel, which
            # scans that directory, could never offer back a delete the UI had already
            # promised was recoverable.
            img.replace(dest)                       # atomic move on the same volume
            moved = dest
        else:
            img.unlink()                            # same contract: no row drop if it fails
    tp = Path(thumb_dir) / "{}.jpg".format(media_id)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass
    _catalog.delete_from_catalog(db_path, media_id)
    return moved


def compute_dhash(img_path, hash_size=_dupes.DHASH_SIZE):
    """Perceptual difference-hash (dHash) of an image, Pillow-only (no numpy/scipy
    dependency -- this codebase already ships Pillow for thumbnails, so no new
    dependency was added for this).

    Algorithm (well-known, ~15 lines): shrink to (hash_size+1) x hash_size, convert to
    grayscale, then for each row encode whether pixel[i] is brighter than pixel[i+1] as
    one bit. That is `hash_size * hash_size` bits total (64 for the default size=8),
    returned as a lowercase hex string. Unlike a byte/SHA hash (Class B, identical_file),
    a dHash is ROBUST to recompression and resizing -- the exact "upscaled or
    recompressed version of the same image" case byte-hashing misses, because shrinking
    to 8x8 washes out compression artifacts and interpolation noise while preserving the
    image's coarse gradient structure. Two dHashes of visually similar images differ in
    only a handful of the 64 bits (measured via Hamming distance -- see
    near_duplicate_groups() below); two unrelated images typically differ in ~32 (half),
    since the bits approach random relative to each other.

    Returns a 16-char hex string, or None if the image can't be opened/decoded (Pillow
    missing, corrupt file, unsupported format) -- callers must treat None as "unknown",
    never as a hash that happens to be empty."""
    if Image is None:
        return None
    try:
        with Image.open(img_path) as im:
            im = im.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
            pixels = list(im.getdata())
    except Exception:
        return None
    width = hash_size + 1
    bits = 0
    for row in range(hash_size):
        offset = row * width
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return "{:0{width}x}".format(bits, width=hash_size * hash_size // 4)


# A picture the thumbnailer cannot draw (3.21.2, L3). An SVG is a vector document, never
# opened by Pillow and never rasterised here (3.21.1 keeps it a plain file, served only as an
# image or a download), so it has no thumbnail by design: a missing one is not a fault, and
# nothing may offer to "rebuild" it. The same holds for any picture type this Pillow cannot open.
_THUMBLESS_EXTS = frozenset({".svg"})


def thumbnail_renders(path):
    """True when make_thumbnail can draw a thumbnail for the picture at `path` (judged by its
    extension, so a missing file is judged the same). False for an SVG, and for a picture type
    this Pillow does not open. Without Pillow at all nothing renders, but the raster types
    still count as thumbnail-bearing, so a library check keeps reporting their thumbnails."""
    global _PIL_EXTS
    ext = Path(str(path or "")).suffix.lower()
    if ext in _THUMBLESS_EXTS:
        return False
    if Image is None or not ext:
        return True
    if _PIL_EXTS is None:
        try:
            _PIL_EXTS = frozenset(k.lower() for k in Image.registered_extensions())
        except Exception:                                    # noqa: BLE001 -- fail to today's
            return True
    return ext in _PIL_EXTS


_PIL_EXTS = None                                  # Pillow's openable extensions, read once


# See-through pictures (RGBA/LA/P-with-transparency) used to lose their alpha to a bare
# convert("RGB") and showed a black box with junk colours. They are flattened onto a dim
# checkerboard instead (owner's pick, 3.22 walk): 12px squares at the thumbnail's FINAL
# size, top-left square CHECKER_A. Opaque pictures keep the old convert path untouched.
CHECKER_A = (46, 49, 72)
CHECKER_B = (32, 35, 54)
CHECKER_SQUARE = 12
# One-time rebuild marker (see build_thumbnails): its presence means every see-through
# thumbnail already on disk was cut by the checkerboard-aware code.
CHECKER_MARKER = ".checkerboard-v1"


def _see_through_rgba(im):
    """The picture as RGBA when it has any genuinely see-through pixel, else None.
    A fully opaque RGBA (or a palette image whose transparent index is unused) is NOT
    see-through, so it keeps today's exact convert("RGB") path."""
    if im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 255:
            return rgba
    return None


def _checkerboard(size):
    from PIL import ImageDraw
    w, h = size
    board = Image.new("RGB", (w, h), CHECKER_B)
    draw = ImageDraw.Draw(board)
    n = CHECKER_SQUARE
    for ty in range(0, h, n):
        for tx in range(0, w, n):
            if ((tx // n) + (ty // n)) % 2 == 0:
                draw.rectangle([tx, ty, min(tx + n, w) - 1, min(ty + n, h) - 1], fill=CHECKER_A)
    return board


def thumb_rgb(im, size, resample=None):
    """`im` shrunk to fit `size` as an RGB image ready for a JPEG. Opaque: exactly the old
    convert-then-thumbnail. See-through: shrunk as RGBA, then pasted (alpha as the mask)
    onto the checkerboard laid out at the final size."""
    resample = Image.LANCZOS if resample is None else resample
    rgba = _see_through_rgba(im)
    if rgba is None:
        out = im.convert("RGB")
        out.thumbnail(size, resample)
        return out
    rgba.thumbnail(size, resample)
    board = _checkerboard(rgba.size)
    board.paste(rgba.convert("RGB"), (0, 0), rgba.getchannel("A"))
    return board


def _could_be_see_through(im):
    """Header-only test: the mode or the `transparency` info says the picture MAY have
    see-through pixels. Reads no pixel data, so an opaque RGB/L original costs one header read."""
    return im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in im.info


def source_is_see_through(img_path):
    """True when the original file has see-through pixels (a GIF is judged on its first
    frame, the one make_thumbnail draws). False on any read problem. The header (mode and
    `transparency` info) is looked at first; the alpha is decoded only for those candidates."""
    if Image is None:
        return False
    try:
        with Image.open(img_path) as im:
            if not _could_be_see_through(im):
                return False                 # opened on frame 0: no n_frames scan, no decode
            return _see_through_rgba(im) is not None
    except Exception:
        return False


def make_thumbnail(img_path, thumb_path):
    """Render one gallery thumbnail. ATOMIC: Pillow writes a same-directory temp file and
    the finished JPEG is os.replace()d into position -- the idiom download's own `.part`
    file, the telemetry ledger and every other persistence path in this app already use.

    Saving straight onto the final path was the bug. A kill, a crash or a full disk part-way
    through `im.save` left a TRUNCATED .jpg sitting at the real name, and every "is it built
    yet?" check in this app is `thumb_path.exists()` -- so a half-written thumbnail is
    treated as done and never rebuilt. That was survivable while the only way to run a
    thumbnail pass was to press a button and watch it; it stopped being survivable when
    --rebuild-thumbs joined the sixty-day staleness backstop (2026-09-06) and became
    something that starts by itself, unattended, with nobody to notice a torn file. Sixty
    days is now how long a corrupt thumbnail can sit there.

    The swap also keeps the OLD thumbnail readable until the new one is complete, which is
    what makes --rebuild-thumbs' "the gallery never goes blank mid-run" literally true
    rather than nearly true."""
    if Image is None:
        return False
    tmp = None
    try:
        from moonglade import backup as core
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory (os.replace is only atomic within one filesystem) and pid-tagged,
        # so two processes rebuilding the same library cannot collide on one temp name.
        # It does not end in .jpg, so --rebuild-thumbs' orphan sweep (thumb_dir.glob
        # ("*.jpg")) cannot mistake a live temp file for a stale thumbnail.
        tmp = thumb_path.with_name(thumb_path.name + ".tmp-%d" % os.getpid())
        with Image.open(img_path) as im:
            # A GIF (Edit Pro's animation, 3.22 S5) is drawn from its FIRST frame, a still:
            # how the grid animates one is the look board's call, never this file's.
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            im = thumb_rgb(im, _catalog.THUMB_SIZE, Image.LANCZOS)
            im.save(tmp, "JPEG", quality=_catalog.THUMB_QUALITY)
        # _atomic_replace, not a bare os.replace: on Windows an antivirus or the Search
        # Indexer briefly opens a file the instant it is created, and renaming it then
        # raises PermissionError for a few hundred ms. Same helper download() uses.
        core._atomic_replace(tmp, thumb_path)
        return True
    except Exception:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def make_video_thumbnail(video_path, thumb_path):
    """Poster fallback for videos PixAI gave no poster frame: extract an early
    frame via ffmpeg (already a dependency for Loom export), then run it through
    the SAME Pillow thumbnail path as images so size/quality stay uniform.
    Returns False (never raises) when ffmpeg is missing or the extract fails.

    Picks a REPRESENTATIVE early frame, not a fixed timestamp. A clip that fades
    in from black used to get a black poster, because the old `-ss 0.5` landed
    inside the fade (owner, 2026-08-22). ffmpeg's `thumbnail` filter scans a batch
    of frames and keeps the one closest to the batch average -- near-solid frames
    (a fade, a flash) lose that contest by construction. The window is the first
    ~3s (72 frames at 24fps) so the poster still reads as the clip's opening,
    not a random mid-clip moment. The literal-first-frame fallback stays for
    clips too short for the filter to get a batch.

    ffmpeg is reached through moonglade.backup's media_tools section -- one cached
    availability probe, one place that owns the no-window flag, the timeouts and the
    "never raises" rule. This used to run its own uncached shutil.which() per file
    and two differently-shaped subprocess.run() calls."""
    from moonglade import backup as core
    import tempfile
    if Image is None or not _media_tools.ffmpeg_path():
        return False
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        r = _media_tools.run_ffmpeg(["-y", "-loglevel", "error", "-i", str(video_path),
                             "-vf", "thumbnail=72", "-frames:v", "1", tmp],
                            timeout=_media_tools.THUMB_TIMEOUT)
        if not r.ok or not os.path.getsize(tmp):
            # clips shorter than the seek point: take the literal first frame
            r = _media_tools.run_ffmpeg(["-y", "-loglevel", "error", "-i", str(video_path),
                                 "-frames:v", "1", tmp],
                                timeout=_media_tools.THUMB_RETRY_TIMEOUT)
        if not r.ok or not os.path.getsize(tmp):
            return False
        return make_thumbnail(Path(tmp), thumb_path)
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Trash / quarantine panel -- list, restore, permanently delete
# ---------------------------------------------------------------------------
# the 2026-07-21 audit's restore-panel row, scoped 2026-07-23: _deleted/ has ~12k
# files with no restore UI even though the delete confirm promises "recoverable".
# These are directory-scan helpers, deliberately NOT catalog queries -- the whole
# point of purge_media_local is that the catalog row is already gone by the time a
# file lands here, so there is nothing in catalog.db left to query.

def _find_quarantined_file(out_dir, media_id):
    """The actual media file (never a .json sidecar) in _deleted/ for media_id, or
    None. media_id_of() on a bare "<media_id>.json" sidecar resolves to the same
    media_id as the real file (its stem IS the media_id), so this explicitly
    restricts the extension to real media -- a naive media_id_of() match alone would
    pick either file depending on directory order."""
    from moonglade import backup as core
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return None
    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
    for p in qdir.glob("*"):
        if p.is_file() and p.suffix.lower() in media_exts and _scan.media_id_of(p) == media_id:
            return p
    return None


def list_quarantined(out_dir, page=1, page_size=60):
    """Directory-scan listing of out_dir/_deleted/, newest-deleted-first, paginated.

    Not backed by the catalog (see module note above). Sidecar '<media_id>.json'
    files (written by purge_media_local since 2026-07-24) supply an exact deleted_at
    plus prompt/rating/collections/etc; older quarantined files -- or any sidecar
    write that failed -- fall back to the file's own mtime.

    mtime is only ever a FALLBACK, never the primary sort key when a sidecar
    exists -- found live-verifying this feature: purge_media_local moves a file
    into _deleted/ with img.replace(dest), a same-volume rename, and a rename does
    NOT update a file's mtime on Windows/NTFS (mtime tracks content writes, not
    moves). So a quarantined file's mtime is really "when it was originally
    downloaded", not "when it was deleted" -- sorting a batch of freshly-purged
    items (which DO have an accurate sidecar) by mtime alone silently reordered
    them by download date instead, which a synthetic multi-item live check caught
    immediately (an older-downloaded, just-deleted image sorted BELOW a
    newer-downloaded one deleted earlier the same session).

    All sidecars are read up front to build that sort key -- NOT deferred to just
    the current page the way thumbnail generation is (see _ensure_trash_thumbs) --
    but this stays cheap: sidecars only exist for files purged since 2026-07-24, a
    small and slowly-growing set, never the ~12k-file legacy backlog they're
    scanned alongside (which has no sidecars to read at all, by definition -- nothing
    wrote one before this feature existed). Only os.scandir() + stat() (metadata
    only, no content read) touches every file in the backlog; JSON parsing is
    bounded by however many sidecars actually exist. Returns (items, total, total_bytes).

    Each item also carries `archive_only` (#66): True when its sidecar snapshot says PixAI no
    longer has that picture, so the file in the trash is the only copy anywhere. The Trash's
    Delete forever / Empty trash name how many before they destroy them. A file with no
    sidecar (everything quarantined before 2026-07-24) is not claimed to be one: nothing
    recorded says so. _list_quarantined also hands back the count across the WHOLE trash,
    not just this page, because Empty trash takes every file."""
    items, total, total_bytes, _only = _list_quarantined(out_dir, page, page_size)
    return items, total, total_bytes


def _list_quarantined(out_dir, page=1, page_size=60):
    """list_quarantined's body, plus a fourth value: how many media files in the whole trash
    are the only copy (their sidecar snapshot passes is_archive_only). See list_quarantined."""
    from moonglade import backup as core
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return [], 0, 0, 0

    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
    entries = []
    meta_by_id = {}
    with os.scandir(qdir) as it:
        for e in it:
            if not e.is_file():
                continue
            if e.name.lower().endswith(".json"):
                mid = Path(e.name).stem
                meta = _read_trash_meta(out_dir, mid)
                if meta:
                    meta_by_id[mid] = meta
                continue
            if Path(e.name).suffix.lower() not in media_exts:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            entries.append((e.name, st.st_size, st.st_mtime))

    total = len(entries)
    total_bytes = sum(s for _, s, _ in entries)
    only_total = sum(1 for name, _s, _m in entries
                     if _catalog.is_archive_only(meta_by_id.get(_scan.media_id_of(name))))

    def _sort_key(entry):
        name, _size, mtime = entry
        meta = meta_by_id.get(_scan.media_id_of(name))
        return (meta or {}).get("_deleted_at") or mtime

    entries.sort(key=_sort_key, reverse=True)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    page_entries = entries[start:start + page_size]

    items = []
    for name, size, mtime in page_entries:
        media_id = _scan.media_id_of(name)
        is_video = Path(name).suffix.lower() in core._VIDEO_EXTS
        meta = meta_by_id.get(media_id)
        deleted_at = (meta or {}).get("_deleted_at") or mtime
        prompt = ((meta or {}).get("prompt_full") or (meta or {}).get("prompt_preview") or "")
        items.append({
            "media_id": media_id, "filename": name, "size": size,
            "deleted_at": deleted_at, "is_video": "1" if is_video else "",
            "prompt": prompt[:2000], "has_meta": bool(meta),
            "archive_only": _catalog.is_archive_only(meta),
        })
    return items, total, total_bytes, only_total


def _ensure_trash_thumbs(out_dir, thumb_dir, items, workers=6):
    """Generate thumbnails for exactly the quarantined items on ONE page -- reuses
    make_thumbnail()/make_video_thumbnail() (the same two functions build_thumbnails()
    calls for the live catalog), not new image-resize logic. Can't reuse
    build_thumbnails() itself: its file resolution (find_image_file /
    find_files_for_media_id) deliberately EXCLUDES _deleted/ -- a quarantined file
    must never resolve as a live survivor (INVARIANT 6) -- so it would never find
    anything sitting in the trash to begin with. Threaded like build_thumbnails() for
    the same reason it is: a page that happens to be video-heavy would otherwise pay
    each ffmpeg extract's cost serially, and this runs synchronously inside a
    request. purge_media_local already frees each media_id's thumb_dir slot when it
    quarantines the file, so writing back into that SAME slot means the existing,
    unmodified /thumbs/<media_id>.jpg route serves the result -- no new serving
    route needed."""
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    work = []
    for it in items:
        thumb_path = Path(thumb_dir) / "{}.jpg".format(it["media_id"])
        if thumb_path.exists():
            continue
        work.append((qdir / it["filename"], thumb_path, it["is_video"] == "1"))
    if not work:
        return

    def _one(item):
        src, thumb_path, is_vid = item
        if not src.exists():
            return False
        return (make_video_thumbnail(src, thumb_path) if is_vid
                else make_thumbnail(src, thumb_path))

    if len(work) > 1 and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed([ex.submit(_one, it) for it in work]):
                try:
                    fut.result()
                except Exception:
                    pass
    else:
        for it in work:
            _one(it)


def restore_quarantined_media(out_dir, thumb_dir, db_path, media_id):
    """Move a quarantined file back out of _deleted/ and reinsert its catalog row.

    Restores to out_dir/images/<filename> -- purge_media_local only ever remembered
    the bare filename (see its own docstring), never the original month/batch
    subfolder, so this is the same flat default location a fresh download or
    --import-local would use; find_image_file()/find_files_for_media_id() already
    search the whole tree, so the gallery works identically regardless of which
    subfolder a file lives under.

    If a purge-time sidecar exists (every purge since 2026-07-24), the FULL row --
    rating, collections, prompt, task_id, everything -- comes back. Older quarantined
    files (or a sidecar write that failed) get a minimal row: media_id/filename plus
    is_video read off the file's own extension, so the file is visible in the gallery
    again -- and a video comes back as a video -- even though its history is genuinely
    gone (there was never a manifest before this feature -- see
    the 2026-07-21 audit's scoping note on this row). A live re-fetch of the
    task via getTaskById (mentioned as possible in that same note) is deliberately
    NOT attempted here: it would turn a local file-move into a network call with its
    own failure modes, for metadata that's "nice to have" on a handful of pre-feature
    orphans, not "needed to make the file visible again".

    Returns {"ok": True, "media_id":, "filename":} or {"ok": False, "error":}."""
    from moonglade import backup as core
    out_dir = Path(out_dir)
    src = _find_quarantined_file(out_dir, media_id)
    if not src:
        return {"ok": False, "error": "not found in trash"}

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / src.name
    if dest.exists():                             # a same-named live file already exists
        dest = images_dir / "{}_{}{}".format(src.stem, media_id, src.suffix)
    try:
        src.replace(dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    meta = _read_trash_meta(out_dir, media_id)
    # Deliberately NOT moonglade.backup.build_catalog_row: this is a RESTORE, not a
    # capture. The sidecar already holds the whole row the user owned -- rating,
    # collections, title, published state -- and there is no task, no extract_full_meta
    # surface, and (purge_media_local deleted the row) nothing in the catalog to carry
    # forward. Seeding from the saved row is the inverse of the builder's contract
    # (blank template + task fields + carry), so it stays its own thing. Issue #19.
    row = {f: (meta.get(f, "") if meta else "") for f in _catalog.CATALOG_FIELDS}
    row["media_id"] = media_id
    row["filename"] = dest.name
    # Only a sidecar carries is_video, and the ~12k legacy files in _deleted/ have none
    # (nothing wrote one before 2026-07-24), so restoring a legacy VIDEO left the flag
    # blank and the gallery served it back as a broken image instead of a player. The
    # extension is the same signal list_quarantined() reads for exactly this reason.
    if not row["is_video"]:
        row["is_video"] = "1" if dest.suffix.lower() in core._VIDEO_EXTS else ""
    _catalog.save_catalog(db_path, [row])

    meta_path = _trash_meta_path(out_dir, media_id)
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass
    return {"ok": True, "media_id": media_id, "filename": dest.name}


def delete_quarantined_forever(out_dir, thumb_dir, media_id):
    """Permanently unlink a quarantined file + its sidecar meta + any thumbnail the
    trash panel generated for it while it sat in _deleted/. Irreversible -- the
    caller (api_trash_delete_forever) is LOCALHOST + confirm=true for exactly this
    reason. Returns True if a media file was actually removed."""
    out_dir = Path(out_dir)
    src = _find_quarantined_file(out_dir, media_id)
    removed = False
    if src:
        try:
            src.unlink()
            removed = True
        except OSError:
            pass
    meta_path = _trash_meta_path(out_dir, media_id)
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass
    tp = Path(thumb_dir) / "{}.jpg".format(media_id)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass
    return removed


def empty_trash(out_dir, thumb_dir):
    """Permanently wipe EVERY file in out_dir/_deleted/ -- the nuclear option behind
    LOCALHOST + confirm=true + the client's own typed-DELETE prompt
    (api_trash_empty()). Same per-item cleanup as delete_quarantined_forever(), just
    walked once instead of media_id-by-media_id. Returns the number of MEDIA files
    removed (sidecars don't count toward the number shown to the owner)."""
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return 0
    from moonglade import backup as core
    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
    removed = 0
    for p in list(qdir.glob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in media_exts:      # sidecar .json (or stray junk)
            try:
                p.unlink()
            except OSError:
                pass
            continue
        mid = _scan.media_id_of(p)
        tp = Path(thumb_dir) / "{}.jpg".format(mid)
        if tp.exists():
            try:
                tp.unlink()
            except OSError:
                pass
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Duplicate Review -- resolve/undo (the destructive half of GET /api/duplicates
# above, which stays read-only). Mirrors the trash panel's own shape immediately
# above -- a moved file plus a JSON sidecar recording enough to undo it -- rather
# than inventing a new pattern, but keyed by the file's OWN quarantine location,
# not media_id: a same_media group can quarantine more than one copy of the SAME
# media_id in a single resolve, so media_id alone is not a unique key here the
# way it is for trash (purge_media_local never has two files under one media_id
# to quarantine at once -- the live catalog holds exactly one file per media_id).
# The original path is recorded EXPLICITLY and undo restores to that EXACT
# location -- unlike trash's restore, which only ever remembered a bare filename
# and always restores into a flat images/ folder -- because cmd_dedup's own
# quarantine (moonglade/organize.py's cmd_dedup) preserves the source's
# real subfolder structure under _duplicates/, and this feature's undo is
# specified to put a file back exactly where it came from.
# ---------------------------------------------------------------------------
# DUPLICATES_DIRNAME (the dedup quarantine folder) is defined in the LIBRARY SCAN
# section above, beside the other directory names every walker shares.


def _quarantine_meta_path(dest):
    """Sidecar path for one quarantined duplicate's undo record, living beside
    the moved file itself (same 'metadata rides next to the file' idea as
    trash's _trash_meta_path above)."""
    return dest.with_name(dest.name + ".undo.json")


def _resolve_under(out_dir, rel_path):
    """A client-submitted relative path, turned into a real absolute Path
    strictly inside out_dir -- or None if it's blank, absolute, or escapes via
    '..'/a symlink. Every client-supplied path this feature touches goes
    through this before it is ever stat'd or moved."""
    rel_path = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel_path:
        return None
    out_dir = Path(out_dir).resolve()
    candidate = (out_dir / rel_path).resolve()
    return candidate if _scan._is_under(candidate, out_dir) else None


def _reconcile_one_row_after_move(out_dir, db_path, media_id, row):
    """Targeted, single-row version of moonglade.organize.reconcile_catalog_with_disk
    -- point media_id's catalog row at whatever copy is still actually on disk,
    without rescanning/rewriting the whole catalog (that function's own approach,
    fine for a batch CLI run, is wasteful for a single synchronous HTTP request).
    Used when a duplicate quarantine or undo changes what's on disk for a
    media_id whose row is being KEPT (e.g. a same_media loser's row, still
    pointing at a keeper that survives elsewhere). No-op if nothing changed, and
    a no-op if the media_id has no surviving file at all (that case is the
    caller's row-delete branch instead, not this function's job)."""
    from moonglade import backup as core
    matches = _scan.find_files_for_media_id(out_dir, media_id)
    if not matches:
        return
    survivor = matches[0]
    rel_surv = survivor.relative_to(out_dir)
    bucket = _organize._bucket_of(rel_surv)
    new_batch = (rel_surv.parts[1] if bucket == "batches" and len(rel_surv.parts) > 2
                else ("" if bucket != "batches" else row.get("batch", "")))
    if row.get("filename") != survivor.name or row.get("batch", "") != new_batch:
        row = dict(row)
        row["filename"] = survivor.name
        row["batch"] = new_batch
        _catalog.save_catalog(db_path, [row])


def quarantine_duplicate_file(out_dir, thumb_dir, db_path, media_id, rel_path, group_id):
    """Move ONE duplicate loser out of the live tree into out_dir/_duplicates/,
    mirroring cmd_dedup()'s DEFAULT (--apply without --dedup-delete) behavior at
    moonglade/organize.py's cmd_dedup -- quarantine, never hard-delete,
    same collision-suffix rule (dest already exists -> "_dup" inserted before the
    extension). Called once per file by the /api/duplicates/resolve route, which
    has already re-verified the (group_id, media_id, path) triple names a real
    duplicate pair (see _validate_duplicate_pair) -- this function trusts that
    and only handles the mechanics: the move, the catalog reconciliation, and
    the undo sidecar. --dedup-delete's hard-delete behavior is not reachable
    through this function under any argument.

    _check_read_only() fires FIRST, before any path is even resolved -- the same
    position submit_generation/submit_fixer/delete_task/claim_reward give it
    (moonglade/backup.py's own contract for every account/filesystem mutation
    this app makes). READ_ONLY in config.json refuses this the same way it
    refuses those.

    Catalog handling depends on whether media_id has ANY other live copy left
    after the move (find_files_for_media_id, which already excludes
    _duplicates/_deleted -- invariant 6):
      * no survivor  -> same situation as a trash purge: the row is removed
        (delete_from_catalog) and a FULL snapshot goes into the sidecar so
        undo can reinsert it, exactly like purge_media_local/
        restore_quarantined_media above.
      * a survivor exists (e.g. the keeper of a same_media group, still on disk
        under the SAME media_id) -> the row must NOT be deleted -- the media_id
        is still alive. Only a targeted filename/batch reconcile runs
        (_reconcile_one_row_after_move), the same fix
        reconcile_catalog_with_disk applies after a CLI --dedup, just scoped to
        this one row instead of a full rescan.

    Returns {"ok": True, "media_id", "original_path", "quarantine_path", "size",
    "row_deleted"} or {"ok": False, "error": "..."} -- never raises."""
    from moonglade import backup as core
    try:
        core._check_read_only("quarantine a duplicate file (Duplicate Review resolve)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    # .resolve() to match exactly what _resolve_under() resolved `src` against below --
    # otherwise a caller passing an out_dir that differs from its own .resolve() (a
    # symlink, a trailing slash) makes src.relative_to(out_dir) raise ValueError even
    # though src is genuinely inside it.
    out_dir = Path(out_dir).resolve()
    src = _resolve_under(out_dir, rel_path)
    if src is None:
        return {"ok": False, "error": "invalid path"}
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    deleted_root = out_dir / _scan.DELETED_DIRNAME
    if _scan._is_under(src, quarantine_root) or _scan._is_under(src, deleted_root):
        return {"ok": False, "error": "already quarantined"}
    if not src.is_file():
        return {"ok": False, "error": "file not found: {}".format(rel_path)}

    rel = src.relative_to(out_dir)
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    row_before = _catalog.get_row(db_path, media_id) if media_id else None

    dest = quarantine_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():                                   # don't clobber an earlier quarantine
        dest = dest.with_name(dest.stem + "_dup" + dest.suffix)
    try:
        src.replace(dest)                                # atomic move, same volume
    except OSError as e:
        return {"ok": False, "error": str(e)}

    row_deleted = False
    if row_before:
        survivors = _scan.find_files_for_media_id(out_dir, media_id)
        if not survivors:
            _catalog.delete_from_catalog(db_path, media_id)
            row_deleted = True
            tp = Path(thumb_dir) / "{}.jpg".format(media_id)
            if tp.exists():
                try:
                    tp.unlink()
                except OSError:
                    pass
        else:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row_before)

    rel_dest = str(dest.relative_to(out_dir)).replace("\\", "/")
    rel_orig = str(rel).replace("\\", "/")
    import time
    sidecar = {
        "media_id": str(media_id),
        "original_path": rel_orig,
        "quarantine_path": rel_dest,
        "group_id": group_id,
        "quarantined_at": time.time(),
        "row_deleted": row_deleted,
        "catalog_row": row_before if row_deleted else None,
    }
    try:
        _quarantine_meta_path(dest).write_text(json.dumps(sidecar), encoding="utf-8")
    except OSError:
        pass    # best-effort, same fail-soft contract as trash's own snapshot write

    return {"ok": True, "media_id": str(media_id), "original_path": rel_orig,
            "quarantine_path": rel_dest, "size": size, "row_deleted": row_deleted}


def restore_quarantined_duplicate(out_dir, thumb_dir, db_path, quarantine_path):
    """Reverse ONE quarantine_duplicate_file() call: move the file back to its
    EXACT original recorded location (not a generic default folder -- unlike
    trash's restore_quarantined_media, this tier's undo is specified to put a
    file back exactly where it came from) and restore whatever the catalog
    snapshot says.

    Fails honestly -- never a silent no-op, never a write to some OTHER
    location -- when:
      * no sidecar/file exists for quarantine_path (missing/stale record, or it
        was never a real quarantined duplicate to begin with)
      * the original location is occupied by a DIFFERENT file that showed up
        there since (a re-download, a re-organize, a fresh import)

    Same _check_read_only() gate, in the same first-statement position, as
    quarantine_duplicate_file().

    Returns {"ok": True, "media_id", "restored_path"} or
    {"ok": False, "error": "..."} -- never raises."""
    from moonglade import backup as core
    try:
        core._check_read_only("undo a duplicate quarantine (Duplicate Review undo)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(out_dir).resolve()   # match _resolve_under()'s own resolution -- see
                                        # quarantine_duplicate_file()'s identical comment
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    src = _resolve_under(out_dir, quarantine_path)
    if src is None or not _scan._is_under(src, quarantine_root):
        return {"ok": False, "error": "not a quarantined-duplicate path"}
    meta_path = _quarantine_meta_path(src)
    if not src.is_file() or not meta_path.exists():
        return {"ok": False, "error": "no undo record for this file "
                                      "(missing, already restored, or stale)"}
    try:
        sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "undo record is unreadable/corrupt"}

    original_path = str(sidecar.get("original_path") or "")
    dest = _resolve_under(out_dir, original_path)
    if dest is None:
        return {"ok": False, "error": "recorded original path is invalid"}
    if dest.exists():
        return {"ok": False, "error": "original location is occupied by another "
                                      "file now -- refusing to overwrite it"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    media_id = str(sidecar.get("media_id") or "")
    if sidecar.get("row_deleted") and sidecar.get("catalog_row"):
        _catalog.save_catalog(db_path, [sidecar["catalog_row"]])
    elif media_id:
        row = _catalog.get_row(db_path, media_id)
        if row:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row)

    try:
        meta_path.unlink()
    except OSError:
        pass

    return {"ok": True, "media_id": media_id,
            "restored_path": str(dest.relative_to(out_dir)).replace("\\", "/")}


def _validate_duplicate_pair(out_dir, db_path, match_type, keep, remove):
    """Re-verify, at request time, that `keep` and every item in `remove`
    genuinely form the duplicate relationship match_type claims -- never trust
    the client's group_id/keep/remove alone; a client could otherwise pair a
    real duplicate's catalog metadata with an unrelated file path and use this
    route to quarantine anything. Cheap and TARGETED (touches only the specific
    files/rows named, never a full-library rescan) rather than recomputing GET
    /api/duplicates' whole detection pass. Returns (True, "") or
    (False, "<reason>") -- the whole group is refused together on failure,
    since a partially-verified group is not a safe partial resolve.

    near_duplicate is checked as a direct keep<->remove pairwise Hamming
    distance, not full group membership: near_duplicate_groups() can chain a
    group together transitively (A near B, B near C, but A and C individually
    over threshold) via union-find. A remove item that is only transitively
    linked to the chosen keeper is refused here as a known, documented
    simplification -- resolving it means picking a keeper it IS directly close
    to, not a gap in the detection logic."""
    from moonglade import backup as core
    out_dir = Path(out_dir)

    def _real(entry):
        """Resolve+validate one {media_id, path} member: a real file, strictly
        inside out_dir, whose OWN filename encodes the claimed media_id."""
        if not isinstance(entry, dict):
            return None
        mid = str(entry.get("media_id") or "").strip()
        path = _resolve_under(out_dir, entry.get("path"))
        if not mid or path is None or not path.is_file():
            return None
        if _scan.media_id_of(path) != mid:
            return None
        return mid, path

    k = _real(keep)
    if k is None:
        return False, "keeper does not resolve to a real file"
    keep_mid, keep_path = k

    checked = []
    for item in remove:
        r = _real(item)
        if r is None:
            return False, "a remove item does not resolve to a real file"
        checked.append(r)
    if not checked:
        return False, "nothing to remove"

    if match_type == "same_media":
        if any(mid != keep_mid for mid, _ in checked):
            return False, "same_media resolve must keep and remove copies of the SAME media_id"
        return True, ""

    if match_type == "identical_file":
        for mid, path in checked:
            if not core._same_bytes(keep_path, path):
                return False, "keeper and {} are no longer byte-identical".format(mid)
        return True, ""

    if match_type == "same_seed":
        keep_row = _catalog.get_row(db_path, keep_mid)
        if not keep_row or not keep_row.get("seed") or not keep_row.get("prompt_full"):
            return False, "keeper has no seed/prompt to match against"
        for mid, _ in checked:
            row = _catalog.get_row(db_path, mid)
            if not row or row.get("seed") != keep_row.get("seed") \
                    or row.get("prompt_full") != keep_row.get("prompt_full"):
                return False, "{} no longer shares (seed, prompt) with the keeper".format(mid)
        return True, ""

    if match_type == "near_duplicate":
        keep_row = _catalog.get_row(db_path, keep_mid)
        keep_phash = (keep_row or {}).get("phash") or ""
        try:
            keep_bits = int(keep_phash, 16)
        except ValueError:
            return False, "keeper has no usable phash"
        for mid, _ in checked:
            row = _catalog.get_row(db_path, mid)
            phash = (row or {}).get("phash") or ""
            try:
                dist = bin(keep_bits ^ int(phash, 16)).count("1")
            except ValueError:
                return False, "{} has no usable phash".format(mid)
            if dist > _dupes.NEAR_DUP_HAMMING_THRESHOLD:
                return False, ("{} is no longer within the near-duplicate threshold "
                              "of the keeper").format(mid)
        return True, ""

    return False, "unknown group type '{}'".format(match_type)


def probe_has_audio(path, timeout=None):
    """True if the media file has at least one audio stream (ffprobe). Fails soft to
    False (never raises) -- a probe failure means the Loom export treats the clip as
    silent and pads it, which is safe; it must never crash the export.

    Gallery-side face of moonglade.backup's `media_tools.has_audio`, which answers three
    ways: True, False, and None for "ffprobe could not look at all". The export's contract
    is the two-way one, so the unanswerable case reads as silent -- deliberately, and in
    this one place rather than at each of the export's own branches. `timeout=None` takes
    media_tools' probe policy; the number does not live here any more."""
    from moonglade import backup as core
    return bool(_media_tools.has_audio(path, timeout=timeout))


def probe_duration(path, timeout=None):
    """Real duration in seconds via ffprobe, or None on failure (missing ffprobe,
    unreadable file, non-numeric output). Never raises.

    Gallery-side face of moonglade.backup's `media_tools.duration` -- see it for why
    there is only one implementation of this question now, and why it answers at full
    precision. `timeout=None` takes media_tools' probe policy."""
    from moonglade import backup as core
    return _media_tools.duration(path, timeout=timeout)


def build_thumbnails(rows, out_dir, thumb_dir, force=False, progress_cb=None, workers=8,
                     recheck=True):
    """Generate JPEG thumbnails for rows that have a file. CPU-bound (Pillow),
    so a thread pool gives a real multi-core speedup (Pillow releases the GIL
    during decode/encode). workers<=1 runs serially. Each worker writes a distinct
    thumb file; progress is reported on the calling thread.

    Videos are included ONLY when their thumb is missing (the collected PixAI
    poster made it already when one existed): a poster-less video gets a local
    ffmpeg frame-extract instead of staying blank forever. `force` deliberately
    does NOT overwrite an existing video thumb -- the poster came from the
    network and can't be regenerated from the local file.

    `recheck` (default True) runs the one-time see-through re-check inline for the batch
    jobs (--sync, --rebuild-thumbs, after an update). The gallery start passes False so a
    missing-thumbnail build is all it waits for, and schedules recheck_see_through_thumbnails()
    to run behind the started server instead."""
    from moonglade import backup as core
    if Image is None:
        print("Warning: Pillow not installed -- thumbnails will not be generated.")
        return
    total = 0
    done = 0
    work = []
    # ONE-TIME REBUILD (3.22 walk): thumbnails cut before the checkerboard existed flattened
    # see-through pictures to a black box, and "is it built?" is thumb_path.exists(), so they
    # would never be redone. Until the marker file is written, every already-built IMAGE
    # thumbnail is re-checked ONCE against its original and only the see-through ones are
    # recut (opaque thumbnails are left alone). A forced rebuild recuts everything anyway.
    marker = thumb_dir / CHECKER_MARKER
    recheck = recheck and not force and not marker.exists()
    for row in rows:
        if not row.get("filename"):
            continue
        is_vid = row.get("is_video") == "1"
        total += 1
        thumb_path = thumb_dir / "{}.jpg".format(row["media_id"])
        if thumb_path.exists() and (is_vid or not force):
            if recheck and not is_vid and thumbnail_renders(row.get("filename")):
                work.append((row["media_id"], thumb_path, row.get("filename"), is_vid, True))
            else:
                done += 1
            continue
        if not is_vid and not thumbnail_renders(row.get("filename")):
            done += 1            # an SVG has no thumbnail by design: skipped, not a failure (L3)
            continue
        work.append((row["media_id"], thumb_path, row.get("filename"), is_vid, False))

    def _one(item):
        mid, thumb_path, filename, is_vid, only_if_see_through = item
        if only_if_see_through:
            src = _catalog_verbs.find_image_file(out_dir, mid, filename)
            if not src or not source_is_see_through(src):
                return True              # opaque (or unreadable): the old thumbnail stands
            return bool(make_thumbnail(src, thumb_path))
        if is_vid:
            vp = Path(out_dir) / (filename or "")
            if not vp.exists():
                # exts=_VIDEO_EXTS, not the matcher's image-only default: this fallback
                # exists for a video whose stored filename is stale or blank, and an
                # image-only match can never find one, so the row stayed thumbless.
                m = _scan.find_files_for_media_id(Path(out_dir), mid, exts=core._VIDEO_EXTS)
                vp = m[0] if m else None
            return bool(vp and make_video_thumbnail(vp, thumb_path))
        img_path = _catalog_verbs.find_image_file(out_dir, mid, filename)
        return bool(img_path and make_thumbnail(img_path, thumb_path))

    def _tick():
        pct = int(done / total * 100) if total else 100
        if progress_cb:
            progress_cb(done, total, pct)
        else:
            print("\r  Thumbnails: {}/{} ({:d}%)  ".format(done, total, pct),
                  end="", flush=True)

    if work and workers and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed([ex.submit(_one, it) for it in work]):
                try:
                    if fut.result():
                        done += 1
                except Exception:
                    pass
                _tick()
    else:
        for it in work:
            if _one(it):
                done += 1
            _tick()
    if recheck or force:
        _write_checker_marker(thumb_dir)
    if total and not progress_cb:
        print()


def _write_checker_marker(thumb_dir):
    try:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / CHECKER_MARKER).write_text(
            "see-through thumbnails sit on a checkerboard\n", encoding="utf-8")
    except OSError:
        pass


def recheck_see_through_thumbnails(rows, out_dir, thumb_dir, workers=2, cancel=None):
    """The one-time see-through re-check (3.22 walk) as its own pass, for running BEHIND a
    started gallery. Every already-built image thumbnail is checked against its original
    (header first, alpha only for candidates) and only see-through ones are recut. The marker
    is written ONLY when every item was handled; a cancel (`cancel.is_set()`), a worker error
    or a failed recut leaves no marker, so the pass simply runs again next start. Returns True
    when the marker was written, False otherwise (including: nothing to do, marker already there)."""
    marker = thumb_dir / CHECKER_MARKER
    if Image is None or marker.exists():
        return False
    items = []
    for row in rows:
        fn = row.get("filename")
        if not fn or row.get("is_video") == "1" or not thumbnail_renders(fn):
            continue
        thumb_path = thumb_dir / "{}.jpg".format(row["media_id"])
        if thumb_path.exists():
            items.append((row["media_id"], thumb_path, fn))

    def _one(item):
        if cancel is not None and cancel.is_set():
            return False
        mid, thumb_path, fn = item
        src = _catalog_verbs.find_image_file(out_dir, mid, fn)
        if not src or not source_is_see_through(src):
            return True                  # opaque (or unreadable): the old thumbnail stands
        return bool(make_thumbnail(src, thumb_path))

    ok = True
    if workers and workers > 1 and items:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_one, items):
                ok = ok and res
    else:
        for it in items:
            ok = _one(it) and ok
    if not ok or (cancel is not None and cancel.is_set()):
        return False
    _write_checker_marker(thumb_dir)
    return True


def start_see_through_recheck(rows, out_dir, thumb_dir, workers=2, cancel=None):
    """Run recheck_see_through_thumbnails() on a daemon thread (the same off-thread startup
    idiom as _health_prime / _outside_prime), after the server is listening. Returns the thread,
    or None when the marker says there is nothing to do."""
    if (thumb_dir / CHECKER_MARKER).exists():
        return None

    def _run():
        try:
            recheck_see_through_thumbnails(rows, out_dir, thumb_dir, workers=workers, cancel=cancel)
        except Exception:                # noqa: BLE001 -- background polish, never a crash
            pass
    th = threading.Thread(target=_run, daemon=True, name="moonglade-thumb-recheck")
    th.start()
    return th


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------


def _build_stamp():
    """Version + short git SHA of the code THIS process loaded, computed once at
    startup. If you pull without restarting, this keeps showing the OLD sha -- which
    is precisely how you tell a stale server from a fresh one. Fails soft."""
    try:
        from moonglade import backup as _core
        ver = getattr(_core, "__version__", "?")
    except Exception:
        ver = "?"
    sha = ""
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_paths.APP_ROOT),
            stderr=subprocess.DEVNULL, timeout=4,
            creationflags=_NO_WINDOW).decode().strip()
    except Exception:
        sha = ""
    return "v{}".format(ver) + (" · {}".format(sha) if sha else "")


DEFAULT_LIBRARY_DIR = _paths.DEFAULT_LIBRARY_DIR    # relative: anchored to the app folder
DEFAULT_HOST = _settings.DEFAULT_HOST
DEFAULT_PORT = _settings.DEFAULT_PORT
DEFAULT_BONJOUR_NAME = _settings.DEFAULT_BONJOUR_NAME


def resolve_library_dir(explicit=None):
    """Where the library lives: an explicit --out for this one start, then settings.json's
    library_dir (the Control Panel's library folder), then the default beside the app --
    moonglade.settings.library_path(), the one resolver the server, the command line and the
    MCP server share (S8). Explicit beats stored on purpose: a one-off `--out somewhere` must
    neither be overridden by the shared setting nor quietly rewrite it. Returns a string.

    settings.json is read once per change of the file, so the value the Panel saved before a
    restart is the one the restarted server opens."""
    return str(_settings.library_path(explicit))


def resolve_server_settings(host_arg=None, port_arg=None):
    """Bind host/port + Bonjour discovery settings: an explicit --host/--port for this one
    start wins, else settings.json's host/port/bonjour (the Control Panel's Bonjour chip),
    else the defaults (moonglade.settings.server). Bonjour defaults OFF -- broadcast is
    opt-in, flipped on from the chip. A stored host that cannot be bound falls back to the
    default rather than crash the bind at startup."""
    return _settings.server(host_arg, port_arg)


def _supervised():
    """True when the server was started by the managed launcher (Moonglade Launcher), which sets
    MOONGLADE_SUPERVISED=1 and relaunches on exit code 42. Restart is only offered when True."""
    return os.environ.get("MOONGLADE_SUPERVISED") == "1"


# New on every server start: a notice keyed by it is said once per start in every open tab
# (gallery/src/notify/serverNotice.js remembers the key it last showed).
_SERVER_START = secrets.token_hex(8)
_SERVER_BOOT = time.monotonic()      # for "up" in the line the server writes when it stops


# THINGS OUTSIDE THE APP THAT NAME ITS OLD FILES (moonglade.outside; DECISIONS 2026-10-07,
# pick 5): a scheduled task, a Claude tools registration or a shortcut still running
# moonglade_backup.py, moonglade_mcp.py or Serve Gallery.pyw. A real start (main()) looks
# once, off the request path, and the notice offers **Fix them** to a tab on this machine.
# None until that look has run -- and in every app a test builds, since only main() looks.
_OUTSIDE = {"items": None}
_OUTSIDE_FIXING = threading.Lock()


def _outside_scan():
    """Look outside the app now and keep what was found. Never raises."""
    from moonglade import outside as moonglade_outside
    try:
        items = moonglade_outside.find()
    except Exception:                                   # noqa: BLE001 -- nothing found, then
        items = []
    _OUTSIDE["items"] = items
    return items


def _outside_prime():
    """main()'s one call: the look runs on its own thread (schtasks can take seconds), after
    the server is up."""
    threading.Thread(target=_outside_scan, daemon=True, name="moonglade-outside-scan").start()


def _shortcut_icon_bytes(stem):
    """A mark's .ico bytes by its file stem (mark_4), for a shortcut whose old icon is gone:
    the loose cut, else the pack's. Only a plain stem is ever looked up."""
    if not re.match(r"^[A-Za-z0-9_-]+$", stem or ""):
        return None
    return _branding._branding_bytes(_branding._role_rel("marks", stem + ".ico"))


def server_notice(local=False):
    """The notice every open tab shows once per server start (the /api/jobs poll carries it;
    gallery/src/notify/serverNotice.js shows the corner toast), or None. Read only.

    Today it is the one about things outside the app that still name its old files, and only
    for a tab on this machine (`local`): the fix rewrites this machine's tasks, configs and
    shortcuts, and its route is LOCALHOST. `fix` names the toast's button; the poll adds the
    session's CSRF token to it."""
    items = _OUTSIDE.get("items")
    if not local or not items:
        return None
    from moonglade import outside as moonglade_outside
    title, msg = moonglade_outside.notice_words(items)
    return {"key": _SERVER_START, "title": title, "msg": msg,
            "fix": {"label": moonglade_outside.fix_label(items)}}


# The running werkzeug server, so a web Stop/Restart handler can shut it down GRACEFULLY instead
# of hard-killing the process. main() stashes the server here right before it blocks in
# serve_forever(); _schedule_server_exit() records the intended exit code and asks the server to
# stop. main()'s `finally` then runs real cleanup (the IPv6 companion, and -- once it lands --
# the mDNS goodbye) and returns `code` to `sys.exit(main())`, which the supervisor reads
# (0 = stop, 42 = relaunch). This replaces the old os._exit() hard kill, which skipped every
# cleanup hook; os._exit() survives only as the fallback for the impossible "no server stashed"
# case so Stop/Restart can never go inert.
_SERVER_CONTROL = {"srv": None, "companion": None, "exit_code": 0}
_EXIT_LOCK = threading.Lock()


def _schedule_server_exit(code):
    """Ask the running server to stop with `code` (0 = stop; 42 = the supervisor's 'relaunch
    me' signal), letting the current HTTP response flush first. Factored out so tests can assert
    the intended exit code without actually killing the test process. First-wins: once a stop is
    scheduled, a second control click within the flush window is ignored, so two near-simultaneous
    clicks (Stop then Restart) can't race the exit code non-deterministically."""
    with _EXIT_LOCK:
        if _SERVER_CONTROL.get("exit_scheduled"):
            return
        _SERVER_CONTROL["exit_scheduled"] = True
        _SERVER_CONTROL["exit_code"] = code

    def _die():
        import time
        # Let THIS response finish writing on its own (daemon) request thread before the process
        # exits -- shutdown() stops ACCEPTING, but the exit that follows still kills daemon
        # threads, so the flush window is still wanted even with graceful shutdown.
        time.sleep(0.4)
        srv = _SERVER_CONTROL.get("srv")
        if srv is not None:
            srv.shutdown()                    # unblocks main()'s serve_forever() -> cleanup + return code
        else:
            os._exit(code)                    # fallback: server was never stashed (shouldn't happen)
    threading.Thread(target=_die, daemon=True).start()


RESTART_EXIT_CODE = 42        # the supervisor's "relaunch me" signal (see _schedule_server_exit)


# WHY THE SERVER ENDED (#95). A Stop, a Restart or an update leaves a request line in
# moonglade.log and nothing in serve.log, the file the launcher points at; so each now writes its
# reason when it asks (_note_server_exit) and main()'s `finally` writes one line saying what ended
# it (server_exit_reason). They are kept OUT of _schedule_server_exit, whose signature and body
# the tests pin.
def _clean_for_log(text, limit=100):
    """Text a client controls (a user name, a browser string) made safe for one log line: printable
    ASCII only, so no newline can forge a second line, a double quote turned into a single one
    so a value cannot close its own quotes, and cut to `limit`."""
    return re.sub(r'[^\x20-\x7e]|"', lambda m: "'" if m.group() == '"' else "?",
                  str(text or ""))[:limit]


def _span_words(seconds):
    """45s, 3m05s, 3h12m05s -- hours only when there are hours, minutes only when there are."""
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        s = 0
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    if h:
        return "%dh%02dm%02ds" % (h, m, sec)
    if m:
        return "%dm%02ds" % (m, sec)
    return "%ds" % sec


def _note_server_exit(why):
    """Remember who or what asked for the exit that is about to happen, and log it. First wins,
    like _schedule_server_exit: a second click keeps the first reason."""
    with _EXIT_LOCK:
        if _SERVER_CONTROL.get("exit_why"):
            return
        _SERVER_CONTROL["exit_why"] = why
    import logging as _logging
    _logging.getLogger(__name__).info("server exit requested: %s", why)


def server_exit_reason(scheduled, code, why, interrupted, errored=True):
    """The sentence for why the server is ending (pure): what main()'s `finally` writes.
    `errored`: an exception is leaving the serve loop (False when the loop returned)."""
    if scheduled and code == RESTART_EXIT_CODE:
        return "Restart requested " + (why or "(no details recorded)")
    if scheduled:
        return "Stop requested " + (why or "(no details recorded)")
    if interrupted:
        return "Ctrl+C in a terminal"
    if not errored:
        return "the server loop ended on its own, with no Stop or Restart asked for"
    return ("an unhandled error ended the server loop (its traceback follows in moonglade.log "
            "as CRITICAL, and in this file)")


def _install_signal_note():
    """Off Windows only: a SIGTERM or SIGHUP is logged, then the default action runs as it
    would have (the handler restores the default and sends the signal again). On Windows nothing
    is installed: a pythonw process is never handed one. Main thread only."""
    if sys.platform == "win32":
        return
    import signal
    import logging as _logging

    def _note(signum, frame):
        try:
            name = signal.Signals(signum).name
        except Exception:                               # noqa: BLE001
            name = str(signum)
        try:
            _logging.getLogger(__name__).info("server received %s", name)
        except Exception:                               # noqa: BLE001
            pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            if signal.getsignal(sig) is not signal.SIG_DFL:
                continue                  # ignored (nohup) or handled by someone: left as it is
            signal.signal(sig, _note)
        except (ValueError, OSError):
            pass


def _power_in_progress():
    """"stop" or "restart" once _schedule_server_exit has been called and the process has not
    yet gone, else "". This is the server's own record that a Stop/Restart is under way: the
    Control Panel reads it off /api/panel/status when it mounts, so a panel reopened (or a
    page remounted) after the click picks the reconnect watch back up instead of showing an
    idle panel (#84). It lives in the process and dies with it, so a fresh process always
    starts at "" -- there is no stale marker to clear."""
    with _EXIT_LOCK:
        if not _SERVER_CONTROL.get("exit_scheduled"):
            return ""
        return "restart" if _SERVER_CONTROL.get("exit_code") == RESTART_EXIT_CODE else "stop"


class _PerRequestSecureSessions(SecureCookieSessionInterface):
    """Flask's signed-cookie sessions, with the cookie's Secure flag taken from the request
    that sets it: Secure over HTTPS, not over this PC's plain-HTTP loopback (see create_app)."""

    def get_cookie_secure(self, app):
        try:
            return bool(request.is_secure)
        except RuntimeError:                       # no request (never, in save_session)
            return bool(app.config.get("SESSION_COOKIE_SECURE"))


def create_app(out_dir: Path):
    # Both named explicitly, because Flask's defaults are this MODULE's folder and both
    # belong to the app folder (moonglade.paths), wherever the module sits: root_path is
    # what send_from_directory()/send_file() join a RELATIVE path onto -- the default
    # library, `pixai_backup`, is one -- and static_folder serves /static/.
    app = Flask(__name__, root_path=str(_paths.APP_ROOT),
                static_folder=str(_paths.static_dir()))

    # A job the SERVER owns cannot outlive the server, so anything still marked running when we
    # boot is from a process that is gone -- nothing will ever report it finished. Sweep those to
    # a terminal state now, or the Job Tracker shows a phantom "running" row forever (owner hit
    # exactly this after a 2026-07-26 machine reset: panel-3d49d9bffea2, a Similar rebuild killed
    # mid-flight, still displaying as running after the reboot). resolve_orphan_jobs() cannot
    # cover these -- it works by asking PixAI about a task id that local jobs do not have.
    # Fails soft: a startup nicety must never be able to stop the server from starting. But it
    # REPORTS the failure rather than swallowing it -- a silent `except: pass` here is how a sweep
    # that never actually ran would look identical to one with nothing to do. `core` is imported
    # locally because this module has no module-level alias for it, and there is no module-level
    # logger either; moonglade.logs.setup_logging() configures the root logger.
    import logging as _logging
    try:
        from moonglade import backup as _core
        _swept = _jobs.resolve_interrupted_local_jobs(out_dir)
        if _swept:
            _logging.getLogger(__name__).info(
                "Marked %d interrupted job(s) from a previous session as failed.", _swept)
    except Exception:
        _logging.getLogger(__name__).warning(
            "interrupted-job sweep skipped", exc_info=True)

    # ---- Session-based auth: secret key + cookie hardening ------------------
    # AUTH_SECRET_KEY is generated once (secrets.token_hex(32)) and persisted to
    # config.json by get_or_create_secret_key() -- reused on every subsequent start
    # so restarting the server doesn't silently log everyone out. See
    # _is_authorized_request() below for the gate this session backs, and
    # /login /logout for the routes that populate it.
    from moonglade import backup as _core_auth
    app.secret_key = _core_auth.get_or_create_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS can never read the session cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site POST/nav CSRF vectors
    # Secure PER REQUEST (2026-11-19): the cookie is marked Secure whenever the request that
    # sets it came over HTTPS -- every other device on the home network since moonglade.tls --
    # so a browser never sends it back over plain http://. This PC's own loopback may stay
    # plain HTTP, and a Secure cookie set there would be dropped by the browser and break
    # sign-in, so the flag follows the request rather than one app-wide setting.
    app.session_interface = _PerRequestSecureSessions()
    import datetime as _dt
    app.permanent_session_lifetime = _dt.timedelta(days=_web_policy.SESSION_IDLE_LIFETIME_DAYS)
    # The app-wide body ceiling (finding 9): routes that take big files raise it for themselves.
    app.config["MAX_CONTENT_LENGTH"] = _web_policy.REQUEST_MAX_BYTES
    # Which plain-HTTP visits the request gate sends to https:// (moonglade.tls's TLS_* names).
    # main() sets it from the listener it opened; a test sets it to try a mode.
    app.config.setdefault("MG_TLS_MODE", "off")
    app.config.setdefault("MG_TLS_FINGERPRINT", "")

    db_path = out_dir / "catalog.db"
    build_stamp = _build_stamp()
    _catalog.init_db(db_path)
    _catalog.migrate(db_path)          # say the schema upgrade out loud at the entry point --
                              # catalog() would do it lazily anyway, and the per-process
                              # memo makes this call free for every later open
    _telemetry.set_telemetry_out(out_dir)     # bare telem_* bumps land in this install's ledger
    _catalog_verbs.backfill_batches(out_dir, db_path)
    thumb_dir = out_dir / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    _branding.ensure_branding_discovery_tree()   # the empty slot folders, created if absent
    # Banner renders are brought up to date ONCE, here, rather than lazily on a
    # request: /branding/<flat> is PUBLIC tier, and an anonymous LAN GET must not
    # be able to schedule a decode-crop-resize-save. Ordered after the scaffold
    # so a legacy install's role tree has already been folded into the coded
    # dirs, and after main()'s root-flat migration (which runs before create_app)
    # so a just-migrated flat is already stamped 'migrated' and is left alone.
    # Regenerates only a MISSING render or one whose record says its slot's pick
    # moved -- see _ensure_banner_flat.
    _branding._ensure_banner_renders(out_dir, db_path=db_path)
    # NOTE: two startup steps are deliberately NOT here, both because they write
    # somewhere branding_root() addresses rather than somewhere out_dir does, and
    # create_app() is called by ~every test with the tree unpatched: the root-flat
    # migration (_migrate_root_banner_flats), which MOVES a real render out of the
    # real coded tree, and the slot-pick record (_record_slot_resolution), which
    # rewrites settings.json's branding slots. Both run from main(), the one place
    # that knows this is a real server start. The ensure pass above only READS
    # those picks; everything it writes is under out_dir.
    #
    # The scaffold call above is additive; its ONE known exception is the
    # legacy-root migration it runs first (_migrate_legacy_branding_root), which
    # folds a pre-coded-tree install's own role-named `branding/` tree into the
    # coded dirs -- a move, never a delete, and the reason that migration is
    # described as additive-or-move-only. It predates this rule and stays here
    # because an install that still has that old tree is unusable until it runs.
    # Nothing else create_app() does relocates a file in the coded tree.

    # -- split: routes_gate (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import routes_gate as _routes_gate
    ctx = _SimpleNamespace(
        build_stamp=build_stamp,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_gate.register(app, ctx)
    MIRROR_CONNECT_PAGE = ctx.MIRROR_CONNECT_PAGE
    _account_is_member = ctx._account_is_member
    _ach_sid = ctx._ach_sid
    _check_csrf = ctx._check_csrf
    _csp_nonce = ctx._csp_nonce
    _entitlements = ctx._entitlements
    _gen_session = ctx._gen_session
    _input_media_id = ctx._input_media_id
    _is_local_request = ctx._is_local_request
    _noncify = ctx._noncify
    _note_power_request = ctx._note_power_request
    _redact_host_paths = ctx._redact_host_paths
    # -- end --

    # -- split: web_threads (split_move) --
    from moonglade import web_threads as _web_threads
    ctx = _SimpleNamespace(
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _web_threads.register(app, ctx)
    PANEL_ACTIONS = ctx.PANEL_ACTIONS
    _LIVING_STALE_ACTIONS = ctx._LIVING_STALE_ACTIONS
    _artworks_job_busy = ctx._artworks_job_busy
    _artworks_kick = ctx._artworks_kick
    _asset_job = ctx._asset_job
    _collect_single_flight = ctx._collect_single_flight
    _export_dir = ctx._export_dir
    _export_job = ctx._export_job
    _export_lock = ctx._export_lock
    _job_busy = ctx._job_busy
    _living_runnable = ctx._living_runnable
    _load_sched = ctx._load_sched
    _log_job = ctx._log_job
    _panel_job = ctx._panel_job
    _panel_lock = ctx._panel_lock
    _panel_run = ctx._panel_run
    _reconcile_orphan_jobs = ctx._reconcile_orphan_jobs
    _save_sched = ctx._save_sched
    _sched_lock = ctx._sched_lock
    _standing_action = ctx._standing_action
    _standing_runnable = ctx._standing_runnable
    _task_stream = ctx._task_stream
    _update_busy = ctx._update_busy
    _update_busy_refusal = ctx._update_busy_refusal
    _watch_lock = ctx._watch_lock
    _watch_status = ctx._watch_status
    # -- end --

    # -- split: routes_panel (split_move) --
    from moonglade import routes_panel as _routes_panel
    ctx = _SimpleNamespace(
        PANEL_ACTIONS=PANEL_ACTIONS,
        _LIVING_STALE_ACTIONS=_LIVING_STALE_ACTIONS,
        _artworks_job_busy=_artworks_job_busy,
        _artworks_kick=_artworks_kick,
        _check_csrf=_check_csrf,
        _collect_single_flight=_collect_single_flight,
        _gen_session=_gen_session,
        _is_local_request=_is_local_request,
        _job_busy=_job_busy,
        _living_runnable=_living_runnable,
        _load_sched=_load_sched,
        _log_job=_log_job,
        _note_power_request=_note_power_request,
        _panel_job=_panel_job,
        _panel_lock=_panel_lock,
        _panel_run=_panel_run,
        _redact_host_paths=_redact_host_paths,
        _save_sched=_save_sched,
        _sched_lock=_sched_lock,
        _standing_action=_standing_action,
        _standing_runnable=_standing_runnable,
        _update_busy=_update_busy,
        _update_busy_refusal=_update_busy_refusal,
        _watch_lock=_watch_lock,
        _watch_status=_watch_status,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_panel.register(app, ctx)
    # -- end --

    # -- split: routes_delete (split_move) --
    from moonglade import routes_delete as _routes_delete
    ctx = _SimpleNamespace(
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_delete.register(app, ctx)
    _batch_sibling_count = ctx._batch_sibling_count
    # -- end --

    # -- split: routes_recipes (split_move) --
    from moonglade import routes_recipes as _routes_recipes
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
    )
    _routes_recipes.register(app, ctx)
    _read_only_flag = ctx._read_only_flag
    _recipe_user_id = ctx._recipe_user_id
    _recipes = ctx._recipes
    # -- end --

    # -- split: routes_library (split_move) --
    from moonglade import routes_library as _routes_library
    ctx = _SimpleNamespace(
        _batch_sibling_count=_batch_sibling_count,
        _check_csrf=_check_csrf,
        _csp_nonce=_csp_nonce,
        _gen_session=_gen_session,
        _is_local_request=_is_local_request,
        _read_only_flag=_read_only_flag,
        _recipe_user_id=_recipe_user_id,
        _recipes=_recipes,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_library.register(app, ctx)
    _find_local_video_file = ctx._find_local_video_file
    _loom_complete_clip = ctx._loom_complete_clip
    # -- end --


    # -- split: routes_account (split_move) --
    from moonglade import routes_account as _routes_account
    ctx = _SimpleNamespace(
        _asset_job=_asset_job,
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_account.register(app, ctx)
    _load_presets = ctx._load_presets
    # -- end --


    # -- split: routes_community (split_move) --
    from moonglade import routes_community as _routes_community
    ctx = _SimpleNamespace(
        _artworks_kick=_artworks_kick,
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_community.register(app, ctx)
    # -- end --


    # -- split: routes_train (split_move) --
    from moonglade import routes_train as _routes_train
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_train.register(app, ctx)
    # -- end --


    # -- split: routes_ach (split_move) --
    from moonglade import routes_ach as _routes_ach
    ctx = _SimpleNamespace(
        _ach_sid=_ach_sid,
        _check_csrf=_check_csrf,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_ach.register(app, ctx)
    # -- end --


    # -- split: routes_mirror (split_move) --
    from moonglade import routes_mirror as _routes_mirror
    ctx = _SimpleNamespace(
        MIRROR_CONNECT_PAGE=MIRROR_CONNECT_PAGE,
        _check_csrf=_check_csrf,
        _is_local_request=_is_local_request,
        _noncify=_noncify,
        _redact_host_paths=_redact_host_paths,
    )
    _routes_mirror.register(app, ctx)
    # -- end --


    # -- split: routes_branding (split_move) --
    from moonglade import routes_branding as _routes_branding
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_branding.register(app, ctx)
    # -- end --


    # -- split: web_loom_store (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import web_loom_store as _web_loom_store
    ctx = _SimpleNamespace(
        out_dir=out_dir,
    )
    _web_loom_store.register(app, ctx)
    _LOOM_ID_RE = ctx._LOOM_ID_RE
    _LOOM_REV_MISSING = ctx._LOOM_REV_MISSING
    _LoomUnreadable = ctx._LoomUnreadable
    _legacy_loom_kv_dir = ctx._legacy_loom_kv_dir
    _legacy_loom_kv_path = ctx._legacy_loom_kv_path
    _loom_bed_path = ctx._loom_bed_path
    _loom_beds_dir = ctx._loom_beds_dir
    _loom_beds_unreadable_answer = ctx._loom_beds_unreadable_answer
    _loom_board_saved = ctx._loom_board_saved
    _loom_journal_finish_task = ctx._loom_journal_finish_task
    _loom_journal_live_for = ctx._loom_journal_live_for
    _loom_journal_load = ctx._loom_journal_load
    _loom_journal_lock = ctx._loom_journal_lock
    _loom_journal_note = ctx._loom_journal_note
    _loom_kv_dir = ctx._loom_kv_dir
    _loom_kv_path = ctx._loom_kv_path
    _loom_kv_text = ctx._loom_kv_text
    _loom_kv_write = ctx._loom_kv_write
    _loom_lock = ctx._loom_lock
    _loom_migrate = ctx._loom_migrate
    _loom_rev_of = ctx._loom_rev_of
    _loom_send_note = ctx._loom_send_note
    _loom_sending_now = ctx._loom_sending_now
    _loom_sends_append = ctx._loom_sends_append
    _loom_sends_lines = ctx._loom_sends_lines
    _loom_sends_lock = ctx._loom_sends_lock
    _loom_store_bed = ctx._loom_store_bed
    _loom_tomb_path = ctx._loom_tomb_path
    _loom_unused_beds = ctx._loom_unused_beds
    # -- end --

    # -- split: routes_generate (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import routes_generate as _routes_generate
    ctx = _SimpleNamespace(
        _LOOM_ID_RE=_LOOM_ID_RE,
        _account_is_member=_account_is_member,
        _check_csrf=_check_csrf,
        _collect_single_flight=_collect_single_flight,
        _entitlements=_entitlements,
        _gen_session=_gen_session,
        _input_media_id=_input_media_id,
        _is_local_request=_is_local_request,
        _load_presets=_load_presets,
        _log_job=_log_job,
        _loom_complete_clip=_loom_complete_clip,
        _loom_journal_finish_task=_loom_journal_finish_task,
        _loom_send_note=_loom_send_note,
        _reconcile_orphan_jobs=_reconcile_orphan_jobs,
        _redact_host_paths=_redact_host_paths,
        _task_stream=_task_stream,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_generate.register(app, ctx)
    _QUOTED_FREE_GONE = ctx._QUOTED_FREE_GONE
    _Reached = ctx._Reached
    _log_gen_failure = ctx._log_gen_failure
    _note_card_sent = ctx._note_card_sent
    _send_claim = ctx._send_claim
    _send_failed = ctx._send_failed
    _send_key = ctx._send_key
    _send_settle = ctx._send_settle
    _source_format_lookup = ctx._source_format_lookup
    _video_duration_lookup = ctx._video_duration_lookup
    # -- end --

    # -- split: routes_import (split_move) --
    from moonglade import routes_import as _routes_import
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        _source_format_lookup=_source_format_lookup,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_import.register(app, ctx)
    # -- end --

    # -- split: routes_loom (split_move) --
    from moonglade import routes_loom as _routes_loom
    ctx = _SimpleNamespace(
        _LOOM_ID_RE=_LOOM_ID_RE,
        _LOOM_REV_MISSING=_LOOM_REV_MISSING,
        _LoomUnreadable=_LoomUnreadable,
        _QUOTED_FREE_GONE=_QUOTED_FREE_GONE,
        _Reached=_Reached,
        _ach_sid=_ach_sid,
        _check_csrf=_check_csrf,
        _export_dir=_export_dir,
        _export_job=_export_job,
        _export_lock=_export_lock,
        _find_local_video_file=_find_local_video_file,
        _gen_session=_gen_session,
        _input_media_id=_input_media_id,
        _legacy_loom_kv_dir=_legacy_loom_kv_dir,
        _legacy_loom_kv_path=_legacy_loom_kv_path,
        _log_gen_failure=_log_gen_failure,
        _loom_bed_path=_loom_bed_path,
        _loom_beds_dir=_loom_beds_dir,
        _loom_beds_unreadable_answer=_loom_beds_unreadable_answer,
        _loom_board_saved=_loom_board_saved,
        _loom_complete_clip=_loom_complete_clip,
        _loom_journal_live_for=_loom_journal_live_for,
        _loom_journal_load=_loom_journal_load,
        _loom_journal_lock=_loom_journal_lock,
        _loom_journal_note=_loom_journal_note,
        _loom_kv_dir=_loom_kv_dir,
        _loom_kv_path=_loom_kv_path,
        _loom_kv_text=_loom_kv_text,
        _loom_kv_write=_loom_kv_write,
        _loom_lock=_loom_lock,
        _loom_migrate=_loom_migrate,
        _loom_rev_of=_loom_rev_of,
        _loom_send_note=_loom_send_note,
        _loom_sending_now=_loom_sending_now,
        _loom_sends_append=_loom_sends_append,
        _loom_sends_lines=_loom_sends_lines,
        _loom_sends_lock=_loom_sends_lock,
        _loom_store_bed=_loom_store_bed,
        _loom_tomb_path=_loom_tomb_path,
        _loom_unused_beds=_loom_unused_beds,
        _noncify=_noncify,
        _note_card_sent=_note_card_sent,
        _redact_host_paths=_redact_host_paths,
        _send_claim=_send_claim,
        _send_failed=_send_failed,
        _send_key=_send_key,
        _send_settle=_send_settle,
        _source_format_lookup=_source_format_lookup,
        _video_duration_lookup=_video_duration_lookup,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_loom.register(app, ctx)
    # -- end --


    # Flask's own `static` endpoint is the one route this module does not define,
    # so it is the one that cannot carry a @tier at its `def`. It is declared
    # here rather than skipped: /static/ is gated by the front door exactly like
    # everything else, and `if rule.endpoint == "static": continue` is the single
    # most common way a catch-all route rule grows a hole.
    _web_tiers.declare_endpoint_tier(app, "static", _web_tiers.LOGIN)

    # Every registered rule must now carry a tier -- checked here, at app
    # creation, not in CI. See assert_every_route_declares_a_tier().
    _web_tiers.assert_every_route_declares_a_tier(app)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# The line the server prints (to serve.log, under the launcher) before a move's stop sentence:
# the launcher shows the last such line when its server stops as it starts (S10).
PREPARE_MARK = "[prepare] "
# How long a server must serve before its start counts as clean (S1).
CLEAN_SERVE_S = 600.0


def _count_clean_start(prepared):
    """Count this server's start as clean (moonglade.setup.Prepared.count_clean_start) and log
    what that did. Never raises."""
    try:
        rep = prepared.count_clean_start()
        rep.log()
    except Exception:                                   # noqa: BLE001 -- bookkeeping only
        pass


def _say_port_refused(owner, port):
    who = ("another Moonglade server is ALREADY serving"
           if owner == "moonglade" else "something else is listening")
    print("\nRefusing to start: {} on port {}.\n".format(who, port), file=sys.stderr)
    if owner == "moonglade":
        print("  Open the one that's already running:  http://localhost:{}/\n"
              .format(port), file=sys.stderr)
    if _supervised():
        # Started by Moonglade Launcher, which passes no flags: the port and the switches are
        # in settings.json, and that is where the way out is.
        settings = _paths.settings_path()
        print("  Find it:  netstat -ano | findstr :{}      (then: taskkill /F /PID <pid>)\n"
              "  Or use a different port: set \"port\" to {} in {} (the launcher passes\n"
              "  no flags), then start Moonglade again.\n"
              "\n"
              "  Starting anyway would bind a SECOND server to the same port -- Windows\n"
              "  allows that -- and requests would land on either one at random. Add\n"
              "  \"--allow-port-reuse\" to \"launch_args\" in the same file if you genuinely\n"
              "  want that.\n".format(port, port + 1, settings), file=sys.stderr)
        return
    print("  Find it:  netstat -ano | findstr :{}      (then: taskkill /F /PID <pid>)\n"
          "  Or just use a different port:  --port {}\n"
          "\n"
          "  Starting anyway would bind a SECOND server to the same port -- Windows\n"
          "  allows that -- and requests would land on either one at random. Pass\n"
          "  --allow-port-reuse if you genuinely want that.\n".format(port, port + 1),
          file=sys.stderr)


def _say_port_unbindable(port, err):
    """The server could not open its port at all (a Windows excluded port range, a privileged
    port, another program that holds it exclusively): the same way out as a taken port."""
    print("\nRefusing to start: Moonglade can't open port {} ({}).\n".format(
        port, getattr(err, "strerror", None) or err), file=sys.stderr)
    if _supervised():
        print("  Use a different port: set \"port\" to {} in {} (the launcher passes no\n"
              "  flags), then start Moonglade again.\n".format(port + 1, _paths.settings_path()),
              file=sys.stderr)
    else:
        print("  Use a different port:  --port {}\n".format(port + 1), file=sys.stderr)
    print("  On Windows a port can be held back by the system (an excluded range); list those\n"
          "  with:  netsh int ipv4 show excludedportrange protocol=tcp\n", file=sys.stderr)


def _port_taken_early(args, planned):
    """S1: is this start's port already taken, judged before the move runs? `planned` is
    moonglade.setup.peek_server(): the host, port and launch switches this start will use
    once the settings are in place. Says why on stderr, as the later check does."""
    if getattr(args, "allow_port_reuse", False) or \
            "--allow-port-reuse" in (planned.get("launch_args") or []):
        return False
    owner = port_owner(planned["host"], planned["port"])
    if owner:
        _say_port_refused(owner, planned["port"])
        return True
    return False


def port_owner(host, port, timeout=0.4):
    """Who, if anyone, is already listening on (host, port)?

    Returns "" if the port is free, "moonglade" if the thing answering is one of
    our own servers, and "other" if something is listening but isn't us.

    This exists because `app.run()` will NOT tell you. Werkzeug's dev server sets
    allow_reuse_address, and on Windows SO_REUSEADDR does something Unix does not:
    it lets a second socket bind a port that is ACTIVELY SERVING, rather than only
    reclaiming one stuck in TIME_WAIT. Both processes then hold :PORT and requests
    land on whichever the OS feels like -- so you edit a file, reload, and get the
    OLD server's response with no error anywhere. That is not hypothetical; it has
    burned this project twice (the old state doc's verification notes), each time
    costing a debugging session chasing a "fix that didn't work" which had in fact
    worked perfectly in a process nobody was talking to.

    `Moonglade Launcher.pyw` already probes the X-Moonglade header to decide "one of our
    servers is already up here" before launching. That check lived ONLY in the
    launcher, so `python -m moonglade.gallery --port N` -- how every script, test
    harness and background agent starts this thing -- walked straight past it.
    Same probe, moved to where it cannot be bypassed.

    The header is the right signal rather than the status code: /api/ping sits
    behind the login gate and answers 401, so "did it 200" would read a live
    gated server as a dead port (see dev/tests/test_web_auth.py's
    test_every_response_carries_the_server_marker, which pins exactly this)."""
    import socket
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.create_connection((probe_host, port), timeout=timeout):
            pass
    except OSError:
        return ""                      # nothing there -- free to bind
    # Something is listening. Ask whether it is ours. Any failure here (HTTPS on
    # the other end, a non-HTTP service, a hang) means "listening but not
    # identifiably ours", which is still a refusal -- never a green light.
    try:
        from urllib.request import urlopen
        with urlopen("http://{}:{}/api/ping".format(probe_host, port), timeout=timeout) as r:
            return "moonglade" if r.headers.get("X-Moonglade") else "other"
    except Exception as e:                                  # noqa: BLE001
        hdrs = getattr(e, "headers", None)                  # HTTPError IS a response
        if hdrs is not None and hdrs.get("X-Moonglade"):
            return "moonglade"
        return "other"


def prepare_tls(host, https_everywhere, bonjour_name, hostname=None, lan_ip=None):
    """HTTPS for this start (moonglade.tls): (mode, ssl context or None, the authority's SHA-256
    fingerprint, the plain sentence when there is no HTTPS). A bind other devices can reach, or
    --https, gets the certificate; anything at all that goes wrong making or loading it -- a
    PC name the certificate format cannot carry, a missing package, an unwritable folder --
    means plain HTTP and one line saying why, never a server that does not start."""
    import logging as _log_mod
    from moonglade import bonjour as moonglade_bonjour
    from moonglade import tls as _tls
    if not (https_everywhere or moonglade_bonjour.is_lan_bind(host)):
        return _tls.TLS_OFF, None, "", ""
    try:
        if hostname is None:
            import socket as _socket
            hostname = _socket.gethostname()
        ip = moonglade_bonjour.lan_ip() if lan_ip is None else lan_ip
        cert_p, key_p = _tls.ensure_certificate(
            dns_names=[hostname, hostname + ".local",
                       moonglade_bonjour.hostname_label(bonjour_name) + ".local"],
            ip_addresses=[ip or ""])
        ctx = _tls.server_context(cert_p, key_p)
        return (_tls.TLS_ALL if https_everywhere else _tls.TLS_LAN), ctx, _tls.fingerprint(), ""
    except Exception as e:                              # noqa: BLE001 -- HTTPS never stops a start
        problem = (str(e) if isinstance(e, _tls.TLSUnavailable) else
                   "Moonglade couldn't set up HTTPS ({}: {}).".format(type(e).__name__,
                                                                     str(e)[:200]))
        print("{}\nServing plain HTTP: another device's traffic is not encrypted, and "
              "Connect from PixAI works only on this PC.".format(problem))
        _log_mod.getLogger(__name__).warning("HTTPS off for this start: %s", problem)
        return _tls.TLS_OFF, None, "", problem


def main():
    # prog: the usage line names the command as it is typed (3.20).
    ap = argparse.ArgumentParser(prog="python -m moonglade.gallery",
                                 description="Local PixAI gallery server.")
    # default=None, not "pixai_backup": argparse cannot tell "the user typed the default"
    # from "the user typed nothing". None is the only value that means "not specified", and
    # then the library, host and port come from local/settings.json (the Control Panel).
    ap.add_argument("--out", default=None,
                    help="library folder for this start. Defaults to the library folder set in "
                         "the Control Panel, or pixai_backup beside the app. An explicit --out "
                         "here always wins, and is never stored.")
    ap.add_argument("--port", type=int, default=None,
                    help="bind port for this start (default: the Control Panel's Bonjour chip, "
                         "or 5000)")
    ap.add_argument("--host", default=None,
                    help="bind address for this start (default: the Control Panel's Bonjour "
                         "chip, or 127.0.0.1; use 0.0.0.0 for LAN). An explicit --host always "
                         "wins.")
    ap.add_argument("--allow-port-reuse", action="store_true",
                    help="start even if something is already listening on --port. Off by "
                         "default because Windows lets a SECOND server bind an actively "
                         "serving port, after which requests hit either one at random.")
    ap.add_argument("--https", action="store_true",
                    help="serve EVERY connection over HTTPS, this PC's own included. Other "
                         "devices on the home network get HTTPS without it whenever the server "
                         "listens there; this switch adds this PC. One self-signed certificate, "
                         "made once in local\\ (needs the 'cryptography' package); a browser "
                         "shows a one-time certificate warning")
    ap.add_argument("--rebuild-thumbs", action="store_true",
                    help="regenerate all thumbnails even if they already exist")
    ap.add_argument("--skip-thumbs", action="store_true",
                    help="don't build catalog thumbnails on startup (fast boot; missing "
                         "ones show 'no preview'). Per-generation thumbs are still made.")
    ap.add_argument("--open-browser", action="store_true",
                    help="open the gallery in your default browser ~1.5s after the server "
                         "starts (manual convenience for a terminal launch; the double-click "
                         "'Moonglade Launcher' does NOT pass this -- it polls the server "
                         "until it actually answers and opens the browser itself)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show INFO-level log lines (request activity, startup steps) on the "
                         "console too -- the log FILE in local/logs/ always captures them "
                         "regardless of this flag")
    args = ap.parse_args()
    from moonglade import setup as moonglade_setup
    # S1: a second server bows out BEFORE the move, so it never moves anything under a running
    # one. The port is read without changing anything (moonglade.setup.peek_server: the
    # stored settings, or the ones an older version left, read the way the merge will read
    # them); the full check below runs again once the settings are in place.
    if _port_taken_early(args, moonglade_setup.peek_server(args.host, args.port)):
        return 2
    # B2: the move runs FIRST -- the settings merge and the install half, then the library's --
    # before anything below reads a setting, a record or a log. A move that cannot finish (a
    # lock held past its wait, a file in use) stops the start with its plain sentence: the new
    # homes would otherwise read empty. The sentence goes to stderr (serve.log under the
    # launcher) behind PREPARE_MARK, which the launcher looks for to show it (S10).
    try:
        prepared = moonglade_setup.prepare("server", explicit_out=args.out)
    except moonglade_setup.MoveStopped as e:
        print("\n" + PREPARE_MARK + str(e) + "\n", file=sys.stderr)
        return 3
    # The launch switches settings.json keeps (launch_args, S17) apply to every start; this
    # start's own command line adds to them.
    stored = _settings.launch_args()
    if stored:
        args = ap.parse_args(stored + sys.argv[1:])
    # settings.json is the source of truth for host/port + Bonjour (the Control Panel's chip
    # writes it); an explicit --host/--port still overrides. Fill args in place so the rest of
    # main() -- port_owner, the companion gate, make_server, the cookie name -- is unchanged.
    _srv = resolve_server_settings(args.host, args.port)
    args.host, args.port = _srv["host"], _srv["port"]

    out_dir = Path(prepared.library)
    from moonglade import logs as moonglade_logging
    moonglade_logging.setup_logging(verbose=args.verbose)
    _install_signal_note()
    prepared.log()
    # A fresh clone has neither the (git-ignored) output folder nor a catalog -- refusing
    # to start here used to be the ONLY thing a brand-new user saw: a console exit, before
    # the web app's own first-run wizard (paste a key, run the first sync) ever had a
    # chance to render. Create the folder and an empty, schema-initialized catalog instead
    # and let the server boot; the wizard banner is what guides them from there.
    folder_was_there = out_dir.is_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # A library folder that was missing when prepare() looked but was here by now (a NAS waking
    # up, a drive put back) was not looked at: do it now, before anything reads it, or this
    # session would serve an un-moved library over empty spend guards. A folder this very
    # mkdir made holds nothing to move.
    if folder_was_there:
        try:
            prepared.late_library()
        except moonglade_setup.MoveStopped as e:
            print("\n" + PREPARE_MARK + str(e) + "\n", file=sys.stderr)
            return 3

    db_path = out_dir / "catalog.db"

    # No catalog yet -> schema-init an empty db and boot; the setup wizard guides from
    # there. The legacy catalog.csv auto-seed was retired 2026-08-24 (#19).
    if _catalog._db_is_empty(db_path):
        _catalog.init_db(db_path)
        print("No catalog yet in {} -- starting anyway. "
              "Use the setup wizard on the gallery's home page, "
              "or run `python -m moonglade --sync` yourself.".format(out_dir))

    thumb_dir = out_dir / "gallery" / "thumbs"
    print("Loading catalog...")
    rows = _catalog.load_catalog(db_path)
    if args.skip_thumbs:
        print("Skipping thumbnail build (--skip-thumbs).")
    else:
        print("Building thumbnails (new only — use --rebuild-thumbs to force all)...")
        # recheck=False: the gallery must not wait on the one-time see-through re-check (it
        # opens every original); it is scheduled behind the started server below instead.
        build_thumbnails(rows, out_dir, thumb_dir, force=args.rebuild_thumbs, recheck=False)

    # Secrets at rest (app security review 2026-11-19, finding 5): the copies already on disk
    # are limited to this user's account once per start; every later write does the same.
    _secure_files.restrict_existing_secrets()

    # HTTPS on the home network (finding 1; moonglade.tls). A server other devices can reach
    # speaks HTTPS to them with ONE certificate made once in local\ (its fingerprint shown in
    # the Control Panel's LAN card), while this PC's own loopback keeps plain HTTP; --https
    # makes every client, this PC included, use https://. Both protocols answer on the same
    # port, so the address only changes its scheme. Without the 'cryptography' package (or
    # with a certificate that can't be saved) it serves plain HTTP and says so.
    from moonglade import bonjour as moonglade_bonjour
    from moonglade import tls as _tls
    tls_mode, tls_ctx, tls_fp, tls_problem = prepare_tls(
        args.host, bool(getattr(args, "https", False)), _srv["bonjour_name"])
    # The scheme this PC's own address uses, and the one other devices use.
    scheme = "https" if tls_mode == _tls.TLS_ALL else "http"
    lan_scheme = "https" if tls_mode != _tls.TLS_OFF else "http"

    # REFUSE to become the second server on this port -- see port_owner()'s docstring
    # for why the OS will happily let us, and what that silently costs.
    if not getattr(args, "allow_port_reuse", False):
        owner = port_owner(args.host, args.port)
        if owner:
            _say_port_refused(owner, args.port)
            return 2

    # One-time, and only on a REAL start: move any rendered banner flat still
    # sitting at the coded root into this install's banner cache. Here rather
    # than in create_app() because it is the only startup step that WRITES
    # destructively to the coded tree, and create_app() is what every test
    # builds -- see _migrate_root_banner_flats' own docstring. The scaffold call
    # is additive and idempotent (create_app runs it again, to no effect); it is
    # repeated here so a legacy install's role-tree migration happens BEFORE the
    # flats are looked for, not after.
    _branding.ensure_branding_discovery_tree()
    _branding._migrate_root_banner_flats(out_dir)
    # Same rule, same reason: this WRITES settings.json's branding slots, which
    # are not out_dir-scoped, so it stays out of create_app().
    # Ordered last of the three -- after the scaffold, so a legacy install's
    # assets are already in the coded dirs to resolve against, and before
    # create_app(), so its ensure pass stamps renders with a recorded pick.
    _branding._record_slot_resolution(out_dir)
    # The pack's Explorer file type, per-user and fail-soft (register_pack_file_type). After
    # the rename and the scaffold, so the pack and a custom mark's .ico are where it looks.
    _branding.register_pack_file_type(out_dir)
    app = create_app(out_dir)
    app.config["MG_TLS_MODE"] = tls_mode
    app.config["MG_TLS_FINGERPRINT"] = tls_fp
    app.config["MG_TLS_PROBLEM"] = tls_problem
    url = "{}://{}:{}/".format(
        scheme, "localhost" if args.host == "0.0.0.0" else args.host, args.port)
    print("\nGallery ready ->  {}".format(url))
    import logging as _ready_logging
    _ready_logging.getLogger(__name__).info("server started: pid %d, supervised %s, https %s",
                                            os.getpid(), _supervised(), tls_mode)
    if tls_mode != _tls.TLS_OFF:
        _lan = moonglade_bonjour.lan_ip()
        if tls_mode == _tls.TLS_LAN and _lan:
            print("Other devices: https://{}:{}/".format(_lan, args.port))
        print("(self-signed HTTPS: a browser shows a one-time certificate warning; check it "
              "shows this SHA-256 fingerprint:\n {})".format(tls_fp))
    print("Press Ctrl+C to stop.\n")
    if getattr(args, "open_browser", False):
        # fire just after app.run() starts blocking (a timer thread is the only way to
        # run code after a blocking call starts)
        import threading, webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # Per-port session cookie. Browsers scope cookies by HOST ONLY -- localhost:5757 and
    # localhost:5057 share one cookie jar entry -- so two Moonglade instances with the
    # default "session" name and different secrets evict each other's login on every
    # sign-in (discovered 2026-07-29: a sandbox and the run-copy silently logged each
    # other out all evening). Naming the cookie by port lets instances coexist. Costs one
    # re-login per instance when this ships, then never again.
    app.config["SESSION_COOKIE_NAME"] = "moonglade_session_{}".format(args.port)
    # Per-port session cookie. Browsers scope cookies by HOST ONLY -- localhost:5757 and
    # localhost:5057 share one cookie jar entry -- so two Moonglade instances with the
    # default "session" name and different secrets evict each other's login on every
    # sign-in (discovered 2026-07-29: a sandbox and the run-copy silently logged each
    # other out all evening). Naming the cookie by port lets instances coexist. Costs one
    # re-login per instance when this ships, then never again.
    app.config["SESSION_COOKIE_NAME"] = "moonglade_session_{}".format(args.port)
    # Companion IPv6 loopback listener -- the fix for "the Lightbox/Details sometimes
    # load slowly" (owner report, diagnosed live 2026-08-06). Chrome resolves
    # `localhost` dual-stack and tries IPv6 ::1 FIRST; bound only to 127.0.0.1, every
    # FRESH connection burns ~300ms failing that attempt before falling back to IPv4
    # (measured: connect 312ms vs 39ms of actual server work on /api/detail).
    # Keep-alive reuse hides it, every new connection pays it -- hence "sometimes."
    # A second werkzeug server on [::1], same port, same app, makes the browser's
    # first attempt succeed instead. The main IPv4 bind below is UNTOUCHED (LAN via
    # --host 0.0.0.0 keeps working exactly as before); an explicit non-loopback
    # --host skips this; no IPv6 stack on the machine -> fail-soft, nothing changes.
    # Both listeners are moonglade.tls's server (Werkzeug's threaded server, answering HTTPS
    # and plain HTTP on one port; plain only when tls_ctx is None), read once here so a test
    # that stands a fake in for moonglade.tls.make_server replaces both.
    _make_server = _tls.make_server
    if args.host in ("127.0.0.1", "0.0.0.0", "localhost"):
        try:
            import threading as _threading
            _srv6 = _make_server("::1", args.port, app, tls_context=tls_ctx)
            _SERVER_CONTROL["companion"] = _srv6
            _threading.Thread(target=_srv6.serve_forever, daemon=True,
                              name="moonglade-ipv6-loopback").start()
        except Exception:
            pass                     # IPv6 unavailable -- IPv4-only, as ever
    # Graceful serving: hold the server object (not app.run()'s fire-and-forget) so a web
    # Stop/Restart can srv.shutdown() it and let the `finally` below run real cleanup -- the same
    # make_server the [::1] companion above already uses. serve_forever() blocks until shutdown()
    # (web Stop/Restart) or Ctrl+C; the pending exit code then rides `sys.exit(main())` to the
    # supervisor (0 = stop, 42 = relaunch).
    try:
        srv = _make_server(args.host, args.port, app, tls_context=tls_ctx)
    except OSError as e:
        _say_port_unbindable(args.port, e)
        return 2
    _SERVER_CONTROL["srv"] = srv
    _SERVER_CONTROL["exit_code"] = 0
    # S1: this start counts toward deleting the move's safety snapshots only once it has
    # served for a while (CLEAN_SERVE_S), or when it is stopped cleanly (below) -- never for
    # a server that refused its port or fell over as it started.
    import threading as _count_threading
    _count_timer = _count_threading.Timer(CLEAN_SERVE_S, _count_clean_start, (prepared,))
    _count_timer.daemon = True
    _count_timer.start()
    # mDNS / Bonjour LAN advertising (opt-in, fail-soft). Register after make_server has bound
    # the socket, so the advertised service is immediately reachable; the goodbye fires in the
    # finally below -- which now actually runs, thanks to step 1's graceful shutdown. The
    # advertiser (and the running host/port/scheme with it) is stashed so the Control Panel's
    # Bonjour chip can toggle or re-point it live, no restart.
    # The scheme stashed and advertised is the one OTHER devices use (https:// once
    # moonglade.tls is on), since they are who the broadcast and the LAN card's address are for.
    _bonjour = moonglade_bonjour.BonjourAdvertiser()
    _SERVER_CONTROL["bonjour"] = _bonjour
    _SERVER_CONTROL["serving"] = {"host": args.host, "port": args.port, "scheme": lan_scheme}
    try:
        if _srv["bonjour_enabled"] and moonglade_bonjour.is_lan_bind(args.host):
            if _bonjour.start(_srv["bonjour_name"], args.port, lan_scheme):
                print("Bonjour: broadcasting as {}  ({}://{}:{}/)".format(
                    _bonjour.hostname, lan_scheme, _bonjour.hostname, args.port))
    except Exception:                    # noqa: BLE001 -- advertising must never stop the server
        pass
    # Warm the Health memo off-thread, now that the socket is bound and requests can already
    # be served. AFTER startup, never blocking it: this is a daemon thread doing a disk walk,
    # and its only job is to make the FIRST Health open of the session a memory read instead
    # of a full library walk with the user watching. See _health_prime / health_cached.
    _health._health_prime(out_dir, db_path)
    # Look for things outside the app that still name its old files (a scheduled task, a
    # Claude registration, a shortcut): off-thread, for the notice (server_notice).
    _outside_prime()
    # The one-time see-through thumbnail check, behind the started server, two workers.
    if not args.skip_thumbs and not args.rebuild_thumbs:
        start_see_through_recheck(rows, out_dir, thumb_dir)
    clean_stop = False
    interrupted = False
    try:
        srv.serve_forever()
        clean_stop = True
    except KeyboardInterrupt:
        clean_stop = True            # Ctrl+C on a terminal launch -> clean stop (exit 0)
        interrupted = True
    finally:
        # First, and wrapped: one line saying what ended the server (#95), in serve.log (a
        # flushed print: the console handler passes warnings only) and in moonglade.log. A
        # failure here can never stop the cleanup below.
        try:
            _stop_code = _SERVER_CONTROL.get("exit_code", 0)
            _stop_sched = bool(_SERVER_CONTROL.get("exit_scheduled"))
            if not clean_stop and not _stop_sched:
                _stop_code = 1               # an error is leaving: Python exits with 1
            _stop_why = server_exit_reason(_stop_sched, _stop_code,
                                           _SERVER_CONTROL.get("exit_why", ""), interrupted,
                                           errored=not clean_stop)
            _stop_up = _span_words(time.monotonic() - _SERVER_BOOT)
            import logging as _stop_logging
            _stop_logging.getLogger(__name__).info(
                "server stopping: %s (pid %d, up %s, exit code %d)",
                _stop_why, os.getpid(), _stop_up, _stop_code)
            print("[server] %s stopping: %s (pid %d, up %s, exit code %d)" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), _stop_why, os.getpid(), _stop_up,
                _stop_code), flush=True)
        except Exception:                    # noqa: BLE001 -- a log line only
            pass
        _count_timer.cancel()
        # A Stop (exit 0) is a clean start's end; a Restart (42) counts only through the
        # timer, so a run of quick Restarts never deletes the snapshots.
        if clean_stop and _SERVER_CONTROL.get("exit_code", 0) == 0:
            _count_clean_start(prepared)
        b = _SERVER_CONTROL.get("bonjour")
        if b is not None:
            b.stop()                 # mDNS goodbye -- devices drop moonglade.local promptly
        companion = _SERVER_CONTROL.get("companion")
        if companion is not None:
            try:
                companion.shutdown()
            except Exception:
                pass
            try:
                companion.server_close()
            except Exception:
                pass
        try:
            srv.server_close()
        except Exception:
            pass
    return _SERVER_CONTROL.get("exit_code", 0)


if __name__ == "__main__":
    # ONE SERVER (split phase 4). `python -m moonglade.gallery` runs this file as __main__, an
    # unregistered module. Code that moved out of create_app reaches gallery with a call-time
    # `from moonglade.gallery import ...`, which would load a SECOND copy whose _SERVER_CONTROL,
    # _OUTSIDE and exit record main() never set. So main() runs in the registered module, the one
    # every importer (and the test suite) gets; this copy only defined names and is not used again.
    # The engine's version of the same fix is moonglade/__main__.py (dev/tests/test_cli_one_engine.py).
    # sys.exit(...) rather than a bare call: main()'s return code (0 stop, 42 restart, 2 and 3
    # refusals) is the launcher's contract.
    import moonglade.gallery as _server
    sys.exit(_server.main())

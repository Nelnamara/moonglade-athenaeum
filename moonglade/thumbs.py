"""
moonglade/thumbs.py
===================
Thumbnails and media probes: `compute_dhash`, the thumbnail writers (`make_thumbnail`,
`make_video_thumbnail`, `thumb_rgb` and the see-through checkerboard), `build_thumbnails`, the
see-through recheck (its marker file and the background thread `start_see_through_recheck`
starts when it is called, never at import), and `probe_has_audio` / `probe_duration`. Moved
verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

It reads THUMB_SIZE and THUMB_QUALITY from moonglade.catalog and find_image_file from
moonglade.catalog_verbs, and nothing from the gallery or the engine.
"""
import os
import threading
from pathlib import Path

from moonglade import catalog as _catalog
from moonglade import catalog_verbs as _catalog_verbs
from moonglade import dupes as _dupes
from moonglade import media_tools as _media_tools
from moonglade import scan as _scan

try:
    from PIL import Image
except ImportError:
    Image = None  # thumbnails will be skipped with a warning


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


def probe_has_audio(path, timeout=None):
    """True if the media file has at least one audio stream (ffprobe). Fails soft to
    False (never raises) -- a probe failure means the Loom export treats the clip as
    silent and pads it, which is safe; it must never crash the export.

    Gallery-side face of moonglade.backup's `media_tools.has_audio`, which answers three
    ways: True, False, and None for "ffprobe could not look at all". The export's contract
    is the two-way one, so the unanswerable case reads as silent -- deliberately, and in
    this one place rather than at each of the export's own branches. `timeout=None` takes
    media_tools' probe policy; the number does not live here any more."""
    return bool(_media_tools.has_audio(path, timeout=timeout))


def probe_duration(path, timeout=None):
    """Real duration in seconds via ffprobe, or None on failure (missing ffprobe,
    unreadable file, non-numeric output). Never raises.

    Gallery-side face of moonglade.backup's `media_tools.duration` -- see it for why
    there is only one implementation of this question now, and why it answers at full
    precision. `timeout=None` takes media_tools' probe policy."""
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

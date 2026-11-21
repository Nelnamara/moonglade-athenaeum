"""
moonglade/media_fetch.py
========================
Fetching the media: the variant preference and `resolve_media` (with the media-CDN TLS
message, said once, and the console lock that keeps it whole beside the progress bar),
`ext_from_ct`, `embed_metadata`, `convert_image`, `download` and the feed's `page_variables`.
Moved verbatim out of moonglade/backup.py in the 3.22 split (phase 4). `_atomic_replace` stays
in the engine.

The names it reads from the engine (MEDIA_BASE, PixAIError, _atomic_replace, _ssl_help, vlog)
are imported from moonglade.backup inside each function that uses them, at call time, so a
test's patch of backup's binding still reaches them and importing this module never imports
the engine.
"""
import os
import sys
import threading
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")


# ---------------------------------------------------------------------------
# Media URL + variant detection + download
# ---------------------------------------------------------------------------
# Preference order of variant labels inside the media object's "urls" list.
URL_VARIANT_PREFERENCE = ["PUBLIC", "ORIGINAL", "ORIG", "FULL", "THUMBNAIL", "STILL_THUMBNAIL"]

# Said-it-once latch for the media-CDN TLS message below. resolve_media runs inside worker
# pools (_parallel_map, the download workers), so the latch is taken under a lock -- two
# threads failing at the same instant must not both print the paragraph.
_MEDIA_TLS_LOCK = threading.Lock()
_media_tls_warned = False

# Serialises MULTI-LINE console output against the \r-overwriting progress bar.
#
# run_download draws that bar from the MAIN thread while resolve_media runs on pool threads,
# so a worker printing a paragraph mid-run could interleave with a redraw and leave the
# terminal reading "  [====>    ] 12/17000 checked  MEDIA CDN TLS verification failed:" with
# the rest of the guidance smeared across the next few bar frames -- the one message the user
# most needs to read whole, shredded by the one thing guaranteed to be printing at the time
# (M01, 2026-07-27). Held only around the write itself, never across network or file I/O, so
# it can never become a throughput gate; an RLock so a future nested writer cannot deadlock.
_CONSOLE_LOCK = threading.RLock()


def _console_block(text):
    """Write a multi-line message as ONE locked, flushed unit, clear of the progress bar.

    The leading newline breaks off whatever partial `\\r` bar frame is on the current line;
    without it the message starts halfway along the bar. Everything the message has to say
    goes in a single write under _CONSOLE_LOCK so no redraw can land inside it."""
    with _CONSOLE_LOCK:
        sys.stdout.write("\n" + text.rstrip("\n") + "\n")
        sys.stdout.flush()


def _warn_media_tls_once(exc):
    """Print `_ssl_help()`'s actionable guidance for a MEDIA-CDN TLS failure -- once a process.

    gql() and download() answer requests.exceptions.SSLError with
    `raise PixAIError(_ssl_help())`, because one such failure there ends the operation and
    the user needs to be told it is a fixable LOCAL trust problem (the corporate
    proxy/antivirus interception that `truststore.inject_into_ssl()` exists for), not a
    PixAI outage. resolve_media could not do the same: it is called once per image inside
    loops that must keep walking past a genuinely-missing media object, and its soft
    `(None, {})` return is the contract those callers are written against -- so it printed
    nothing, the caller printed "no url for media <id>", and a TLS problem that would fail
    EVERY image in the library was indistinguishable from PixAI simply not having that one
    (M01, 2026-07-27). Hence: same message, printed rather than raised.

    Once, not per image: MEDIA_BASE is a single host, so if its TLS handshake fails it fails
    for all of them -- a 17,000-image backup would otherwise repeat this paragraph 17,000
    times and bury the very thing it is trying to say. The per-image `vlog` line still
    records each failure individually, and vlog reaches the rotating file log whether or not
    -v is on, so nothing is lost by saying the paragraph once.

    The latch is per PROCESS, and for the CLI that is the same thing as per run. It is NOT
    the same thing inside the long-lived gallery server, which resolves media for months on
    one process: there the paragraph appears on the server console the first time and never
    again, even if the trust problem is fixed and returns. Named rather than fixed because
    the honest fix is not a timer -- every failure is already in moonglade.log, which is the
    surface a server operator reads, and a re-arming console paragraph would print on a
    console nobody is watching. The message below says "process" for that reason; do not
    reword it to "run".

    Printed as one locked block, not three `print`s: see _console_block."""
    from moonglade.backup import _ssl_help
    global _media_tls_warned
    with _MEDIA_TLS_LOCK:
        if _media_tls_warned:
            return
        _media_tls_warned = True
    _console_block(
        "  MEDIA CDN TLS verification failed: {}\n".format(str(exc)[:200])
        + _ssl_help() + "\n"
        + "  Every image resolve will fail the same way until this is fixed -- this is a "
          "local trust problem, NOT PixAI missing your images. (Said once per process; "
          "every individual failure is in the log.)\n")


def resolve_media(session, mid):
    """Fetch the media object and return (best_full_res_url, info_dict).

    Reads the object's `urls` list and picks the highest-quality variant
    (PUBLIC = full-resolution original on PixAI). Returns (None, {}) on failure.

    Fails SOFT on purpose -- callers page through whole libraries and a media object that
    genuinely no longer exists must not end the run. The one failure that is not really
    "this image is missing" is a TLS handshake failure against the media CDN, which is a
    fixable local problem affecting every image at once; that one gets `_ssl_help()`
    printed (once) before the same soft return, see `_warn_media_tls_once`.
    """
    from moonglade.backup import MEDIA_BASE, vlog
    _t = time.monotonic()
    try:
        r = session.get(MEDIA_BASE.format(id=mid), timeout=30)
        r.raise_for_status()
        obj = r.json()
    except requests.exceptions.SSLError as e:
        # Must precede the RequestException clause -- SSLError is a subclass of it, so the
        # broader handler below would otherwise swallow this case exactly as before.
        _warn_media_tls_once(e)
        vlog("resolve_media {} FAILED (TLS) in {:.2f}s ({})".format(
            mid, time.monotonic() - _t, e))
        return None, {}
    except (requests.RequestException, ValueError) as e:
        vlog("resolve_media {} FAILED in {:.2f}s ({})".format(
            mid, time.monotonic() - _t, e))
        return None, {}
    urls = obj.get("urls") or []
    by_variant = {}
    for u in urls:
        if isinstance(u, dict) and u.get("url"):
            by_variant[str(u.get("variant", "")).upper()] = u["url"]
    chosen, variant = None, ""
    for pref in URL_VARIANT_PREFERENCE:
        if pref in by_variant:
            chosen, variant = by_variant[pref], pref
            break
    if not chosen and by_variant:
        variant, chosen = next(iter(by_variant.items()))
    # `variant` says which copy `chosen` is: the Broken files re-download (moonglade.integrity)
    # must never take a THUMBNAIL fallback for an original. Every other caller ignores it.
    info = {"width": obj.get("width"), "height": obj.get("height"),
            "type": obj.get("type", ""), "variant": variant}
    vlog("resolve_media {} -> {} {}x{} in {:.2f}s".format(
        mid, "url" if chosen else "NO-URL",
        info.get("width"), info.get("height"), time.monotonic() - _t))
    return chosen, info


def ext_from_ct(ct):
    ct = (ct or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"
    if "svg" in ct:
        return ".svg"
    if "gif" in ct:
        return ".gif"
    if "avif" in ct:
        return ".avif"
    # Animated artworks resolve to video files
    if "mp4" in ct:
        return ".mp4"
    if "webm" in ct:
        return ".webm"
    if "quicktime" in ct or "mov" in ct:
        return ".mov"
    return ".png"


def embed_metadata(path, fields):
    """Embed prompt/IDs/date into the image file itself.

    PNG -> text chunks (lossless re-save). JPEG -> EXIF ImageDescription with
    quality='keep' (no recompression). WebP and others -> skipped ('unsupported').
    Returns a short status note. Never raises.

    The re-save goes to a same-directory temp and is then renamed over the original
    through _atomic_replace(), like every other on-disk writer here. Writing back
    over the source directly meant a crash, a power loss or a full disk partway
    through left a truncated image and NO original to fall back on -- this file is
    the backup, so an in-place rewrite is the one copy of the picture. The temp
    name ends in .part so the resume/organize scans that already ignore .part
    leftovers never mistake one for a finished download."""
    from moonglade.backup import _atomic_replace
    try:
        from PIL import Image, PngImagePlugin
    except ImportError:
        return "pillow-missing"
    ext = path.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg"):
        return "unsupported"
    pairs = [(str(k), str(v)) for k, v in fields.items() if v not in (None, "")]
    tmp = path.with_name("{}.meta-{}.part".format(path.name, os.getpid()))
    try:
        if ext == ".png":
            with Image.open(path) as im:
                im.load()
                meta = PngImagePlugin.PngInfo()
                for k, v in pairs:
                    meta.add_text(k, v)
                im.save(tmp, "PNG", pnginfo=meta, optimize=True)
        else:
            with Image.open(path) as im:
                im.load()
                exif = im.getexif()
                desc = "; ".join("{}={}".format(k, v) for k, v in pairs)
                exif[0x010E] = desc[:1500]  # ImageDescription
                im.save(tmp, "JPEG", quality="keep", exif=exif)
        _atomic_replace(tmp, path)
        return "ok"
    except Exception as e:
        try:
            if tmp.exists():
                tmp.unlink()   # the temp is unique to THIS call -- only ever our own leftover
        except OSError:
            pass
        return "error: {}".format(str(e)[:60])


def convert_image(path, target, jpeg_quality=92, jpeg_bg="white", keep_original=False):
    """Convert an image file to target format ('png' or 'jpeg').

    Returns (final_path, note). Requires Pillow. On any failure, leaves the
    original untouched and returns it with an explanatory note.
    """
    try:
        from PIL import Image
    except ImportError:
        return path, "pillow-missing"
    target = target.lower()
    out_ext = ".jpg" if target in ("jpg", "jpeg") else ".png"
    if path.suffix.lower() == out_ext:
        return path, "already"
    out_path = path.with_suffix(out_ext)
    try:
        with Image.open(path) as im:
            if target in ("jpg", "jpeg"):
                # JPEG has no alpha: flatten onto a background.
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size,
                                   (0, 0, 0) if jpeg_bg == "black" else (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.save(out_path, "JPEG", quality=jpeg_quality, optimize=True)
            else:
                im.save(out_path, "PNG", optimize=True)
    except Exception as e:
        # Clean up a partial output; keep the original.
        try:
            if out_path.exists() and out_path != path:
                out_path.unlink()
        except OSError:
            pass
        return path, "convert-error: {}".format(str(e)[:80])
    if not keep_original and out_path != path:
        try:
            path.unlink()
        except OSError:
            pass
    return out_path, "ok"


def download(session, url, stem, retries=3, convert=None,
             jpeg_quality=92, jpeg_bg="white", keep_webp=False, progress=None):
    """stem is a Path WITHOUT extension. Returns (status, final_path_or_None).

    `progress`, when given, is called as progress(bytes_so_far, content_length) after each
    chunk is written (content_length 0 when the response sends none): the Broken files list's
    byte bar (Session W) rides it. It only watches; it changes nothing about the download."""
    from moonglade.backup import _atomic_replace, PixAIError, _ssl_help, vlog
    existing = [p for p in stem.parent.glob(stem.name + ".*")
                if not p.name.endswith(".part") and p.stat().st_size > 0]
    if existing:
        return ("skip", existing[0])
    _t = time.monotonic()
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with session.get(url, stream=True, timeout=120) as r:
                if r.status_code == 404:
                    vlog("download {} -> missing (404) in {:.2f}s".format(
                        stem.name, time.monotonic() - _t))
                    return ("missing", None)
                r.raise_for_status()
                ext = ext_from_ct(r.headers.get("Content-Type"))
                dest = stem.with_name(stem.name + ext)
                # Unique per process AND thread, still ending in .part (every scan skips that):
                # two collectors mirroring one account would otherwise share one temp name.
                tmp = dest.with_name("{}.{}-{}.part".format(
                    dest.name, os.getpid(), threading.get_ident()))
                dest.parent.mkdir(parents=True, exist_ok=True)   # fresh backup dir may lack images/
                # Content-Length is only comparable to bytes-written when the body is NOT
                # content-encoded: requests decompresses gzip/br inside iter_content, so a
                # compressed response's header counts different bytes than we write.
                expect = int(r.headers.get("Content-Length") or 0)
                enc = (r.headers.get("Content-Encoding") or "identity").strip().lower()
                nbytes = 0
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=65536):
                        fh.write(chunk)
                        nbytes += len(chunk)
                        if progress:
                            progress(nbytes, expect if enc == "identity" else 0)
                if nbytes == 0:
                    # A 200 with an empty body -- a truncated connection, not a real
                    # image. Promoting this to `dest` would create a permanent,
                    # unrecoverable zero-byte file: the startup resume index treats any
                    # non-.part file with the right extension as "already done" (see the
                    # matching guard there), so it would never be retried by --update,
                    # --sync, or a full re-walk. Fail this attempt instead, through the
                    # same retry/backoff path as any other network failure below.
                    tmp.unlink()
                    vlog("download {} -> empty response body ({:.2f}s), retrying".format(
                        stem.name, time.monotonic() - _t))
                    raise requests.RequestException("empty response body")
                if expect and enc == "identity" and nbytes != expect:
                    # The connection was cut MID-body but the chunk stream ended
                    # "cleanly", so no exception fired -- promoting this .part would
                    # create a permanent truncated file (a video that stops playing
                    # mid-way), invisible to resume forever after, exactly like the
                    # zero-byte case above. Fail the attempt through the same
                    # retry/backoff path instead.
                    tmp.unlink()
                    vlog("download {} -> short body ({:,} of {:,} bytes, {:.2f}s), retrying".format(
                        stem.name, nbytes, expect, time.monotonic() - _t))
                    raise requests.RequestException(
                        "short body: got {} of {} bytes".format(nbytes, expect))
                _atomic_replace(tmp, dest)   # retry a transient Windows lock on the .part file
                vlog("download {} -> {:,} bytes in {:.2f}s".format(
                    dest.name, nbytes, time.monotonic() - _t))
            if convert:
                dest, note = convert_image(dest, convert, jpeg_quality,
                                           jpeg_bg, keep_original=keep_webp)
                if note == "pillow-missing":
                    raise PixAIError("--convert needs Pillow. Run:  pip install pillow\n"
                                     "(The image downloaded fine; just install Pillow and "
                                     "re-run -- finished files are skipped.)")
                if note.startswith("convert-error"):
                    print("    convert warning for {}: {}".format(dest.name, note))
            return ("ok", dest)
        except requests.exceptions.SSLError:
            raise PixAIError(_ssl_help())
        except requests.RequestException as e:
            if attempt == retries:
                print("    FAILED {} ({})".format(url, e))
                return ("fail", None)
            time.sleep(delay); delay *= 2
        except OSError as e:
            # A DISK failure -- a full volume, a read-only path, or the PermissionError
            # _atomic_replace re-raises once its retries are exhausted -- is not a network
            # problem, so there is nothing to back off from; it just has to be REPORTED.
            # Uncaught it escapes the whole function, and callers that hand this to
            # _parallel_map without an `on_error` drop the failed worker silently: the
            # image is simply absent from a backup that still finishes and reports success.
            # Reporting it through the same ("fail", None) channel as a network failure
            # means every existing caller counts it the way it already counts those.
            # (requests.RequestException subclasses OSError, so this clause must stay BELOW
            # it or it would swallow every network error before that one is reached.)
            print("    FAILED {} ({})".format(url, e))
            return ("fail", None)


def page_variables(page_size, user_id, before=None):
    """History-feed query variables for `listUserTaskSummaries`.

    `user_id` is passed in explicitly -- every call site already holds the session/client
    this run authenticated as, so it reads `_client_of(session).user_id` and hands it here.
    This helper no longer reaches for the module-level `USER_ID` global (it had no session
    parameter, which is what made that global hard to retire): the account id now travels on
    the client, not in a global the whole module shared."""
    v = {"last": page_size, "userId": user_id}
    if before:
        v["before"] = before
    return v

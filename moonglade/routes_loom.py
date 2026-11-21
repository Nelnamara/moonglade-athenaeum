"""moonglade/routes_loom.py -- the Loom's routes: the page and its vendored scripts, the board store
(/api/loom/get, set, list, delete), the handoff and frame imports, the video frames and their
thumbs, the Loom's quote and send (/api/loom/spend, /api/loom/generate) with the submit status and
abandon, the music beds, and the exports (EDL, the render export and its job, the bundle out and
in).

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once. Names the block reads from code still inside create_app or from the
families split out before it (the Loom store, the create routes) come in through ctx (the
bound-from-ctx lines below), so every closure on both sides holds the one same object. gallery's
own names are imported inside the function that reads them, at call time, so a test's patch of
moonglade.gallery still reaches the route.
"""
import json
import math
import os
import re
import secrets
import threading
import time

from flask import jsonify, request, send_file, send_from_directory, session

from moonglade import account_prefs as _account_prefs
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import health as _health
from moonglade import media_tools as _media_tools
from moonglade import paths as _paths
from moonglade import scan as _scan
from moonglade import telemetry as _telemetry
from moonglade import full_meta as _full_meta
from moonglade import account_api as _account_api


def register(app, ctx):
    from moonglade.loom_files import LOOM_EXPORT_SWEEP_AGE_S
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _LOOM_ID_RE = ctx._LOOM_ID_RE
    _LOOM_REV_MISSING = ctx._LOOM_REV_MISSING
    _LoomUnreadable = ctx._LoomUnreadable
    _QUOTED_FREE_GONE = ctx._QUOTED_FREE_GONE
    _Reached = ctx._Reached
    _ach_sid = ctx._ach_sid
    _check_csrf = ctx._check_csrf
    _export_dir = ctx._export_dir
    _export_job = ctx._export_job
    _export_lock = ctx._export_lock
    _find_local_video_file = ctx._find_local_video_file
    _gen_session = ctx._gen_session
    _input_media_id = ctx._input_media_id
    _legacy_loom_kv_dir = ctx._legacy_loom_kv_dir
    _legacy_loom_kv_path = ctx._legacy_loom_kv_path
    _log_gen_failure = ctx._log_gen_failure
    _loom_bed_path = ctx._loom_bed_path
    _loom_beds_dir = ctx._loom_beds_dir
    _loom_beds_unreadable_answer = ctx._loom_beds_unreadable_answer
    _loom_board_saved = ctx._loom_board_saved
    _loom_complete_clip = ctx._loom_complete_clip
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
    _noncify = ctx._noncify
    _note_card_sent = ctx._note_card_sent
    _redact_host_paths = ctx._redact_host_paths
    _send_claim = ctx._send_claim
    _send_failed = ctx._send_failed
    _send_key = ctx._send_key
    _send_settle = ctx._send_settle
    _source_format_lookup = ctx._source_format_lookup
    _video_duration_lookup = ctx._video_duration_lookup
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    thumb_dir = ctx.thumb_dir
    # -- end --

    @app.route("/loom/vendor/<path:fname>")
    @tier(LOGIN)
    def loom_vendor(fname):
        """Serve the Loom's vendored JS (React/ReactDOM UMD builds) from
        loom/vendor/ so the page paints with zero network calls. Path-safe; absent
        files 404. Not gated by _is_authorized_request() -- these are static library
        files, not gallery data, and /loom itself already enforces authorization above."""
        from flask import send_from_directory, abort
        vdir = _paths.loom_vendor().resolve()
        try:
            target = (vdir / fname).resolve()
            target.relative_to(vdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(str(vdir), fname, max_age=31536000)

    @app.route("/loom/dist/<path:fname>")
    @tier(LOGIN)
    def loom_dist(fname):
        """Serve the esbuild-bundled Loom (loom/dist/, built by `npm run build` in
        loom/) -- the Loom's SOLE delivery path since the Babel-standalone retirement
        (2026-08-08). Same path-safety pattern as loom_vendor(). Absent files 404;
        loom() below treats a missing bundle as 'not built yet' and says so (503).
        max_age=0 (unlike the vendor libs) since this output changes every rebuild."""
        from flask import send_from_directory, abort
        ddir = _paths.loom_dist().resolve()
        try:
            target = (ddir / fname).resolve()
            target.relative_to(ddir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(str(ddir), fname, max_age=0)

    @app.route("/loom")
    @tier(LOGIN)
    def loom():
        """Serve the Seedance video-storyboard tool inside the gallery, persisted to the
        backend (window.storage swapped for /api/loom/*). Authorized only.

        Bundle-ONLY since 2026-08-08 (the vanilla static/ -> React campaign): serves the
        pre-built esbuild bundle (loom/dist/master-storyboard.bundle.js, `npm run build` in
        loom/). The old in-browser Babel-standalone transpile was retired here -- the bundle
        is a real module build, so shared modules (loom-core, loom-mutations, the art-filter
        engine, ...) are plain imports esbuild resolves, with no hand-inlining. A checkout
        that hasn't built the bundle gets a clear message, not a silent fallback; the
        committed bundle + the CI staleness guard keep it current."""
        from moonglade.pages import LOOM_PAGE_BUNDLE, _upscale_const_js
        from moonglade.ach_beacon import _ach_mint
        loom_dir = _paths.loom_dir()
        bundle_file = loom_dir / "dist" / "master-storyboard.bundle.js"
        if not bundle_file.is_file():
            return ("The Loom bundle is not built. Run `npm run build` in loom/ to "
                    "generate loom/dist/master-storyboard.bundle.js."), 503
        # __ACH_NONCE__ is the Read the Manual beacon's per-render nonce (2026-09-07
        # ruling). token_urlsafe is [A-Za-z0-9_-] only, so it cannot break out of the
        # double-quoted JS string it lands in.
        return (_noncify(LOOM_PAGE_BUNDLE.replace("__UPSCALE_CONST__", _upscale_const_js()))
                                .replace("__ACH_NONCE__", _ach_mint(_ach_sid())))

    @app.route("/api/loom/get")
    @tier(LOGIN)
    def loom_get():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        key = request.args.get("key") or ""
        with _loom_lock:
            _loom_migrate()
            try:
                text, _layer = _loom_kv_text(user, key)
            except _LoomUnreadable:
                # Session P (review F15): a board that exists but will not read is NOT a
                # missing board -- the Loom would seed a blank one over it.
                return jsonify({"error": "unreadable", "value": None}), 500
            if text is None:
                return jsonify({"value": None, "missing": True, "rev": _LOOM_REV_MISSING})
            return jsonify({"value": json.loads(text), "rev": _loom_rev_of(text)})

    @app.route("/api/loom/set", methods=["POST"])
    @tier(LOGIN)
    def loom_set():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        p = request.get_json(silent=True) or {}
        k = p.get("key")
        if not k:
            return jsonify({"ok": False}), 400
        base_rev = p.get("base_rev")
        with _loom_lock:
            _loom_migrate()
            # Compare-and-swap (Session P, BUILD-w5-p §3.5): with a base_rev, the write lands
            # only if the board is still the one the tab last read or wrote -- the check and
            # the write are one step under this lock. Without one, today's last-writer-wins
            # (ACTIVE_KEY, thumbs, every other caller).
            if base_rev is not None:
                try:
                    cur_text, _layer = _loom_kv_text(user, k)
                    cur_rev = _loom_rev_of(cur_text)
                except _LoomUnreadable:
                    cur_text, cur_rev = None, "unreadable"
                if str(base_rev) != cur_rev:
                    return jsonify({"conflict": True, "rev": cur_rev,
                                    "value": json.loads(cur_text) if cur_text is not None else None}), 409
            try:
                _loom_kv_write(user, k, p.get("value"))
            except OSError as e:
                return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:120]}), 500
            rev = _loom_rev_of(json.dumps(p.get("value")))
        return jsonify({"ok": True, "rev": rev})

    @app.route("/api/loom/list")
    @tier(LOGIN)
    def loom_list():
        from urllib.parse import unquote
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        pre = request.args.get("prefix") or ""
        with _loom_lock:
            _loom_migrate()
            # Union of the account's own keys and the legacy shared keys it hasn't
            # overridden yet -- mirrors _loom_kv_read's per-key fallback, so "list"
            # never omits a board a bare "get" on the same key would still return.
            own_keys = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.json")}
            legacy_keys = {unquote(f.stem) for f in _legacy_loom_kv_dir().glob("*.json")}
            # Minus anything this account has deleted. Without it a legacy board the
            # account never saved its own copy of stayed in the list forever: the delete
            # had nothing of its own to unlink, so it reported success and changed nothing.
            buried = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.deleted")}
            keys = (own_keys | legacy_keys) - buried
        return jsonify({"keys": sorted(k for k in keys if k.startswith(pre))})

    @app.route("/api/loom/delete", methods=["POST"])
    @tier(LOGIN)
    def loom_delete():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        k = (request.get_json(silent=True) or {}).get("key")
        with _loom_lock:
            _loom_migrate()
            if k:
                # Unlinks only the account's OWN copy, never the legacy shared file --
                # matches _view_presets: the legacy layer is never written back to, so one
                # account tidying its board list cannot remove a board out from under
                # another.
                # That alone was not enough. A board the account had merely INHERITED from
                # the legacy layer has no own copy to unlink, so this reported success and
                # changed nothing: the next read fell straight back through to the legacy
                # file and the board returned. Every board predating the per-account split
                # was undeletable that way, while a freshly created one deleted perfectly
                # -- which reads as the list showing the same board twice. The gap was
                # known and judged not to bite a single owner; it does. Hence the tombstone
                # this comment used to propose.
                try:
                    _loom_kv_path(user, k).unlink()
                except FileNotFoundError:
                    pass    # already gone -- deleting a nonexistent key is still a success
                except OSError as e:
                    # A real failure (locked file, read-only mount, permissions) used to fall
                    # into the same bare `except OSError: pass` as "already gone" above, so
                    # {"ok": true} came back even though the file is still sitting there --
                    # matches loom_set's own OSError handling just above in this file.
                    return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:120]}), 500
                # Bury it only when the legacy layer would otherwise hand it straight back.
                # Fails soft: an unwritable tombstone leaves the old behaviour (the board
                # reappears), which is exactly what happened before and is not worth
                # turning a working delete into an error.
                if _legacy_loom_kv_path(k).exists():
                    try:
                        _loom_tomb_path(user, k).write_text("", encoding="utf-8")
                    except OSError:
                        pass
        return jsonify({"ok": True})

    @app.route("/api/loom/handoff", methods=["POST"])
    @tier(LOGIN)
    def loom_handoff():
        """Frame handoff: given a generated shot's video media_id, extract its LAST frame,
        upload it, and return the new frame media_id -- which the storyboard sets as the
        next shot's opening frame, chaining clips into one continuous scene. The clip must
        already be downloaded locally (it is, right after Generate-shot cataloged it).
        Login required; the upload is free.

        The frame is THUMBNAILED as well as uploaded, as /api/loom/import-frames does: the
        new media id is in no catalog, and /thumbs/<id>.jpg serves from disk with no
        fetch-on-miss, so every surface that draws the open frame by its id -- the Video
        drawer's frame box, the board card, Deep Focus -- drew a broken picture (owner walk
        2026-09-30). The thumbnail is written from the very PNG that was uploaded; a failed
        thumbnail never fails the handoff (the frame is still PixAI's).

        The answer also says where the frame came from: `at` (seconds) and `at_end` (it was
        the clip's last frame), so the splice and Re-anchor record the true source time."""
        from moonglade.thumbs import make_thumbnail
        body = request.get_json(silent=True) or {}
        mid = str(body.get("video_media_id") or "").strip()
        if not mid:
            return jsonify({"error": "video_media_id required"}), 400
        # Trim-aware: the previous shot's trimOut is where its cut actually ends, so hand
        # off the frame AT that point, not the untrimmed clip's real final frame. None/absent
        # -> the clip isn't trimmed, take the true last frame.
        try:
            trim_out = body.get("trim_out")
            trim_out = float(trim_out) if trim_out is not None else None
        except (TypeError, ValueError):
            trim_out = None
        # Spend review N2 (the verdict on open call 3): the upload below is free but it is a
        # WRITE to the PixAI account, so READ_ONLY refuses it -- first, before the session's
        # USER_ID lookup, so a READ_ONLY install talks to nobody (as /api/loom/generate does).
        from moonglade import backup as _core
        try:
            _core._check_read_only("upload a hand-off frame to your PixAI account")
        except _core.PixAIError as e:
            return jsonify({"error": str(e)[:300]}), 200
        try:
            core, session = _gen_session()
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "clip not downloaded yet -- generate/collect it first"}), 200
            fdir = _paths.loom_root(out_dir) / "_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            png = fdir / (mid + "_last.png")
            if not _media_tools.extract_last_frame(str(vid), str(png), at_seconds=trim_out):
                return jsonify({"error": "could not extract the last frame (ffmpeg)"}), 200
            frame_mid = core.upload_media(session, str(png))
            make_thumbnail(png, thumb_dir / (str(frame_mid) + ".jpg"))
            # media_tools.duration answers at full precision; 2dp is this route's own
            # display choice for the Edit Bay's reel, made where it is visible.
            _dur = _media_tools.duration(str(vid))
            dur = round(_dur, 2) if _dur is not None else None
            # WHERE the frame came from, by the primitive's own rule (frame_seek_point): the
            # trim point it seeked to, or -- the clip's last frame -- the clip's length (None
            # when it could not be measured). The Loom's anchor records this (owner walk
            # 2026-09-30: a frame spliced from E·01's end was recorded "at 0.0 s", because the
            # card did not know its clip's length).
            seek = _media_tools.frame_seek_point(trim_out, _dur)
            at_end = seek is None
            at = dur if at_end else round(seek, 2)
            return jsonify({"frame_media_id": str(frame_mid), "duration": dur,
                            "at": at, "at_end": at_end})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/loom/import-frames", methods=["POST"])
    @tier(LOGIN)
    def loom_import_frames():
        """Give an IMPORTED clip the two stills it never had.

        A shot generated on the board gets its opening frame from whatever was fed in.
        An imported clip arrives already rendered, so nothing ever produced those stills
        and Deep Focus shows two empty slots -- even though the frames are sitting in the
        very file we already hold. ffmpeg has them: frame 0, and the last frame.

        Both are UPLOADED as well as thumbnailed, so they are real media ids rather than
        decoration: the close frame is then a valid continuity hand-off into the next shot,
        exactly like a generated shot's. Thumbnails are written because /thumbs/<id>.jpg
        serves from disk with no fetch-on-miss fallback, so an un-thumbnailed frame would
        render as a blank box. Login required; the upload is free.

        Partial success is a real outcome and is returned as one: if only one end extracts
        or uploads, that end still lands. The board fills whichever frames come back."""
        from moonglade.thumbs import make_thumbnail
        body = request.get_json(silent=True) or {}
        mid = str(body.get("video_media_id") or "").strip()
        if not mid:
            return jsonify({"error": "video_media_id required"}), 400
        try:
            core, session = _gen_session()
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "clip not downloaded yet -- collect it first"}), 200
            fdir = _paths.loom_root(out_dir) / "_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            out = {}
            # at_seconds=0.0 is the FIRST frame through the same primitive (it takes the
            # explicit-seek branch); None keeps the EOF-relative path for the last frame.
            for key, at in (("first", 0.0), ("last", None)):
                png = fdir / ("{}_{}.png".format(mid, key))
                if not _media_tools.extract_last_frame(str(vid), str(png), at_seconds=at):
                    continue
                try:
                    fmid = str(core.upload_media(session, str(png)))
                except Exception:                              # noqa: BLE001
                    continue                                   # one end failing is not fatal
                make_thumbnail(png, thumb_dir / (fmid + ".jpg"))
                out[key + "_media_id"] = fmid
            if not out:
                return jsonify({"error": "could not extract frames (ffmpeg)"}), 200
            return jsonify(out)
        except Exception as e:                                 # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/loom/video-duration")
    @tier(LOGIN)
    def loom_video_duration():
        """Real duration (seconds) of an already-catalogued video, via ffprobe on the local
        file -- fallback for the Footage tab's import-as-footage picker (loom/master-
        storyboard.jsx's importPickedFootage) when the catalog's own video_duration column
        is blank (rows predating that column, or whose request-duration was never captured
        -- see CATALOG_FIELDS/video_duration). Shares _find_local_video_file and
        media_tools.duration with /api/loom/handoff (the latter also powers the Edit Bay's
        reel) -- same resolver, same probing utility, nothing new invented. Read-only,
        local-file-only -- no PixAI session needed. Login required, matching every other
        /api/loom/* route."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"error": "media_id required", "duration": None}), 400
        try:
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "video file not found locally", "duration": None}), 200
            _dur = _media_tools.duration(str(vid))   # 2dp is this route's display choice, not the probe's
            return jsonify({"duration": round(_dur, 2) if _dur is not None else None})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "duration": None}), 200

    # ---- THE CONTINUITY RIBBON'S FRAMES (Session P, NOTES P9; BUILD-w5-p §5.2; review F18) ----
    # One small still from a LOCAL clip, for the ribbon's close-frame / next-open-frame pairs:
    # ffmpeg on this machine through the app's one frame primitive (core.frame_at), scaled to
    # LOOM_FRAME_WIDTH, cached as out_dir/_moonglade/loom/_frames/<mid>_<frame>.png. Unlike
    # /api/loom/handoff there is NO upload and no PixAI session at all -- it cannot spend and it
    # never talks to PixAI. The time is quantised to a 24 fps frame (at most 24 files per second
    # of clip, whatever the trims do), and the cache is LRU-capped by count and bytes on every
    # write, touching only files of exactly the ribbon's name shape.
    _loom_frame_lock = threading.Lock()

    def _loom_frame_sweep(fdir):
        """Keep the newest-used ribbon frames within LOOM_FRAME_CACHE_MAX_FILES files and
        LOOM_FRAME_CACHE_MAX_BYTES bytes; remove the rest. Other files in _frames are never
        counted or touched. Returns the names removed."""
        from moonglade.loom_files import (LOOM_FRAME_CACHE_MAX_BYTES, LOOM_FRAME_CACHE_MAX_FILES,
                                          LOOM_FRAME_FILE_RE)
        found = []
        try:
            for f in fdir.iterdir():
                if not LOOM_FRAME_FILE_RE.match(f.name):
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                found.append((st.st_mtime, f.name, st.st_size, f))
        except OSError:
            return []
        found.sort(key=lambda x: (x[0], x[1]), reverse=True)   # most recently used first
        removed, count, total = [], 0, 0
        for _mtime, name, size, f in found:
            count += 1
            total += size
            if count <= LOOM_FRAME_CACHE_MAX_FILES and total <= LOOM_FRAME_CACHE_MAX_BYTES:
                continue
            try:
                f.unlink()
                removed.append(name)
            except OSError:
                pass
        return removed

    @app.route("/api/loom/frame")
    @tier(LOGIN)
    def loom_frame():
        """GET ?mid=<media id>&at=<seconds> -> a PNG of that clip's frame at `at`, ~160 px wide.
        ?mid=<media id>&end=1 (and no `at`) -> the clip's TRUE last frame, measured from the
        file (GitHub #63: a take whose length was never recorded is closed at its real end,
        not at the shot's planned length).
        400 for a malformed mid or time; 404 when the clip is not on this machine or no frame
        could be produced (no ffmpeg here, a broken file) -- the ribbon then shows its
        placeholder tint. Login required; local only."""
        from moonglade.gallery import Image
        from moonglade.loom_files import (LOOM_FRAME_FPS, LOOM_FRAME_MAX_SECONDS, LOOM_FRAME_WIDTH,
                                          LOOM_MEDIA_ID_RE)
        from moonglade.web_policy import harden_file_response
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        mid = (request.args.get("mid") or "").strip()
        if not LOOM_MEDIA_ID_RE.match(mid):
            return jsonify({"error": "mid must be a media id"}), 400
        if "end" in request.args:
            if request.args.get("end") != "1" or "at" in request.args:
                return jsonify({"error": "end=1 asks for the clip's last frame, and takes no time"}), 400
            frame, seek = "end", None
        else:
            try:
                at = float(request.args.get("at", ""))
            except (TypeError, ValueError):
                return jsonify({"error": "at must be a number of seconds"}), 400
            if not math.isfinite(at) or at < 0 or at > LOOM_FRAME_MAX_SECONDS:
                return jsonify({"error": "at is out of range"}), 400
            frame = int(round(at * LOOM_FRAME_FPS))
            seek = frame / float(LOOM_FRAME_FPS)
        fdir = _paths.loom_root(out_dir) / "_frames"
        png = fdir / "{}_{}.png".format(mid, frame)
        if png.is_file():
            try:
                os.utime(png, None)            # used now: the LRU keeps it
            except OSError:
                pass
            return harden_file_response(send_file(str(png), mimetype="image/png", max_age=3600))
        # A COMPLETE library file only (Invariant 3): a .part download or a zero-byte file is
        # never read -- the same resolver the EDL zip uses.
        vid = _loom_complete_clip(mid)
        if vid is None:
            return jsonify({"error": "that clip is not on this machine"}), 404
        fdir.mkdir(parents=True, exist_ok=True)
        tag = secrets.token_hex(6)
        raw = fdir / ".raw-{}-{}.png".format(tag, frame)
        small = fdir / ".small-{}-{}.png".format(tag, frame)
        try:
            if not _media_tools.frame_at(str(vid), seek, str(raw)):
                return jsonify({"error": "no frame could be taken from that clip (is ffmpeg installed?)"}), 404
            src = raw
            if Image is not None:
                try:
                    with Image.open(str(raw)) as im:
                        w, h = im.size
                        rgb = im.convert("RGB")
                    if w > LOOM_FRAME_WIDTH:
                        rgb = rgb.resize((LOOM_FRAME_WIDTH, max(1, int(round(h * LOOM_FRAME_WIDTH / float(w))))))
                    rgb.save(str(small), "PNG")
                    src = small
                except Exception:                              # noqa: BLE001
                    return jsonify({"error": "that frame could not be read"}), 404
            os.replace(str(src), str(png))
        finally:
            for t in (raw, small):
                try:
                    t.unlink()
                except OSError:
                    pass
        with _loom_frame_lock:
            _loom_frame_sweep(fdir)
        if not png.is_file():
            return jsonify({"error": "the frame cache is full"}), 404
        return harden_file_response(send_file(str(png), mimetype="image/png", max_age=3600))

    # ---- FRAMES SPLICED BEFORE 3.15.0 (GitHub #62) -------------------------------------------
    # 3.15.0 writes a thumbnail when a splice uploads a frame, but a frame spliced earlier is a
    # PixAI media id in no catalog with no thumbs/<id>.jpg -- and /thumbs/<id>.jpg (the shared
    # gallery route) never fetches on a miss -- so the board card, Deep Focus and the drawer's
    # frame box drew a broken picture. The Loom posts a board's frame ids once per session on
    # open; each missing one is filled ONCE from PixAI: a read of the media object
    # (core.media_thumbnail_url, as /api/train/thumb does), then the picture from the PixAI image
    # CDN only (pixai_cdn_url_ok, the proxy's own guard). Two reads, no write to PixAI, nothing
    # that spends, so no _check_read_only. One at a time with a pause, under one lock across
    # tabs. A frame PixAI cannot give back is remembered as gone until restart, so reopening a
    # board never asks again; a missing PixAI session is not a verdict and is not remembered.
    _loom_frame_thumbs_lock = threading.Lock()
    _loom_frame_gone = set()

    def _loom_fetch_frame_thumb(core, sess, mid):
        """Fill thumbs/<mid>.jpg from PixAI. True when it is there afterwards."""
        from moonglade.thumbs import make_thumbnail
        from moonglade.scenes import pixai_cdn_url_ok
        import requests as _req
        url = _account_api.media_thumbnail_url(sess, mid)
        if not url or not pixai_cdn_url_ok(url):
            return False
        r = _req.get(url, timeout=20)
        if r.status_code != 200 or not r.content:
            return False
        fdir = _paths.loom_root(out_dir) / "_frames"
        fdir.mkdir(parents=True, exist_ok=True)
        src = fdir / (".frame-thumb-{}-{}".format(mid, secrets.token_hex(4)))
        dest = thumb_dir / (mid + ".jpg")
        try:
            src.write_bytes(r.content)
            return bool(make_thumbnail(src, dest)) and dest.is_file()
        finally:
            try:
                src.unlink()
            except OSError:
                pass

    @app.route("/api/loom/frame-thumbs", methods=["POST"])
    @tier(LOGIN)
    def loom_frame_thumbs():
        """{csrf, media_ids: [up to LOOM_FRAME_THUMBS_MAX digit ids]} -> {have, fetched, gone}:
        already on this machine / filled from PixAI now / PixAI could not give it back (the
        Loom then says "Frame not on this machine. Splice again." instead of a broken picture)."""
        from moonglade.loom_files import (LOOM_FRAME_THUMBS_MAX, LOOM_FRAME_THUMBS_PAUSE_S,
                                          LOOM_FRAME_THUMB_ID_RE)
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        ids = body.get("media_ids")
        if not isinstance(ids, list) or len(ids) > LOOM_FRAME_THUMBS_MAX:
            return jsonify({"error": "media_ids must be a list of at most %d ids" % LOOM_FRAME_THUMBS_MAX}), 400
        ids = [str(x).strip() for x in ids]
        if any(not LOOM_FRAME_THUMB_ID_RE.match(x) for x in ids):
            return jsonify({"error": "media_ids must be PixAI media ids"}), 400
        have, fetched, gone = [], [], []
        with _loom_frame_thumbs_lock:
            todo = []
            for mid in dict.fromkeys(ids):
                if (thumb_dir / (mid + ".jpg")).is_file():
                    have.append(mid)
                elif mid in _loom_frame_gone:
                    gone.append(mid)
                else:
                    todo.append(mid)
            if todo:
                try:
                    core, sess = _gen_session()
                except Exception:                              # noqa: BLE001
                    core = sess = None
                for i, mid in enumerate(todo):
                    if core is None:
                        gone.append(mid)                       # no session: not a verdict, not remembered
                        continue
                    if i:
                        time.sleep(LOOM_FRAME_THUMBS_PAUSE_S)
                    try:
                        ok = _loom_fetch_frame_thumb(core, sess, mid)
                    except Exception:                          # noqa: BLE001
                        ok = False
                    if ok:
                        fetched.append(mid)
                    else:
                        gone.append(mid)
                        _loom_frame_gone.add(mid)
        return jsonify({"have": have, "fetched": fetched, "gone": gone})

    @app.route("/api/loom/spend", methods=["POST"])
    @tier(LOGIN)
    def loom_spend():
        """What a Loom board has ALREADY spent: the renders it SENT (2026-11-18). Local only --
        no PixAI session, no network. The historical sibling of /api/price, which quotes what
        unrendered shots would cost.

        The answer is read from the board's send record (loom_sends_fold) and nothing else:
        not from the media ids its cards point at. Counting those is what broke the figure
        over and over -- every clip attached to a shot that was not a render paid for here
        (a linked or imported video, a remix, a seeded example, a split's twin) had to be
        fenced out one writer at a time. A send is recorded when it happens, so none of them
        can count.

        On the first read of a board saved before the record existed, its one backfill runs
        (loom_backfill_sends): the real task ids its takes and the journal kept. Each send
        with no settled charge is then looked up in the catalog by task id; a charge found
        there is written into the record, so it no longer depends on the catalog row.

        Answers {"sends": [{"task_id": str|null, "card": str, "kind": str,
        "cost": int|null}]}: an int is PixAI's charge for that send (0: a free card covered
        it), null a send whose charge is not known (not collected yet, or a send with no
        clear answer from PixAI)."""
        from moonglade.catalog_verbs import (loom_backfill_sends, loom_cost, loom_sends_fold,
                                             paid_credit_for_tasks)
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        p = request.get_json(silent=True) or {}
        board = str(p.get("board_id") or "")
        if not _LOOM_ID_RE.match(board):
            return jsonify({"error": "board_id required"}), 400
        # The journal first, under its own lock, released before the record's is taken.
        with _loom_journal_lock:
            entries = [dict(e) for e in _loom_journal_load(user)["subs"].values()]
        with _loom_sends_lock:
            st = loom_sends_fold(_loom_sends_lines(user))
            new = []
            if board not in st["backfilled"]:
                saved = _loom_board_saved(user, board)
                known = {s.get("task_id") for s in st["sends"].values() if s.get("task_id")}
                new = loom_backfill_sends(saved or {}, board, known, entries, at=time.time())
                new.append({"board": board, "backfilled": time.time()})
                _loom_sends_append(user, new)
                st = loom_sends_fold(_loom_sends_lines(user))
            mine = [s for s in st["sends"].values()
                    if s.get("board") == board and not s.get("void")]
            open_tids = [s["task_id"] for s in mine if s.get("task_id") and s.get("cost") is None]
            if open_tids:
                found = paid_credit_for_tasks(db_path, open_tids)
                costs = []
                for tid in open_tids:
                    c = loom_cost(found.get(tid))
                    if c is not None:
                        costs.append({"task_id": tid, "cost": c})
                if costs:
                    _loom_sends_append(user, costs)
                    st = loom_sends_fold(_loom_sends_lines(user))
                    mine = [s for s in st["sends"].values()
                            if s.get("board") == board and not s.get("void")]
        mine.sort(key=lambda s: float(s.get("at") or 0))
        return jsonify({"sends": [{"task_id": s.get("task_id") or None,
                                   "card": str(s.get("card") or ""),
                                   "kind": s.get("kind"),
                                   "cost": s.get("cost") if isinstance(s.get("cost"), int) else None}
                                  for s in mine]})

    @app.route("/api/loom/generate", methods=["POST"])
    @tier(LOGIN)
    def loom_generate():
        """Generate a storyboard SHOT on PixAI (the video 'Copy shot' -> 'Generate shot').
        Resolves the shot's @-ordered images (upload data-URLs / pass media_ids) -> the PixAI
        video provider adapter -> card auto-apply (V4.0 = free) -> async submit. Login required
        (any session, local or LAN).

        Session P (BUILD-w5-p §3.2; review F2, F3, F13, F16, N3) -- the guard order:
          1. front door (LOGIN);
          2. the Loom's own keys are POPPED so they never reach build_request, /api/price or
             PixAI: loom_target {board_id, card_id}, submit_id, expect_free;
          3. READ_ONLY, before the PixAI session is even made (no USER_ID lookup, no upload,
             no card check) -- a READ_ONLY install talks to nobody before refusing;
          4-6. ONE critical section under the journal lock: a replayed submit_id answers its
             recorded outcome, a shot that already has a render out answers 409, a picture
             that cannot be sent (an imported local_ id) is refused, and only then is
             "sending" appended -- two POSTs racing each other cannot both pass;
          7. the existing road: resolve_img -> build_request -> core.submit (READ_ONLY
             again -> free card -> before_send -> ONE gql_mutate);
          8. the outcome is journalled as submitted | refused | not_sent | may_have_started
             from whether the mutation was reached (on_send) and whether PixAI's answer was
             a definite refusal. A lost answer is NEVER recorded as a refusal: that would free
             the shot for a second paid render while the first may exist.
        A body with none of the keys (the gallery's own Video tab) skips 4-6 and 8 and is
        today's request."""
        from moonglade import backup as _core
        p = request.get_json(silent=True) or {}
        target = p.pop("loom_target", None)
        submit_id = p.pop("submit_id", None)
        expect_free = bool(p.pop("expect_free", False))
        # A draft render has no shot yet, so it names its board alone (2026-11-18): it is a
        # render sent from that board, and the board's send record counts it.
        draft_board = p.pop("loom_board", None)
        user = str(session.get("user") or "")
        journalled = submit_id is not None or target is not None
        board_id = card_id = None
        if journalled:
            if not isinstance(submit_id, str) or not _LOOM_ID_RE.match(submit_id):
                return jsonify({"error": "This render has no valid submit id, so nothing was sent."}), 400
            if target is not None:
                t = target if isinstance(target, dict) else {}
                board_id, card_id = str(t.get("board_id") or ""), str(t.get("card_id") or "")
                if not _LOOM_ID_RE.match(board_id) or not _LOOM_ID_RE.match(card_id):
                    return jsonify({"error": "This render names no valid shot, so nothing was sent."}), 400
        # Which board's send record a send from here goes into: the shot's board, or a
        # draft's own board. None for the gallery's Video tab, which is not a board.
        send_board, send_card = (board_id, card_id) if board_id else (None, "")
        if journalled and not send_board and isinstance(draft_board, str) \
                and _LOOM_ID_RE.match(draft_board):
            send_board = draft_board
        sending_key = (_account_prefs._account_key(user), submit_id) if journalled else None
        try:
            _core._check_read_only(_gen_road._SUBMIT_ACTION_DEFAULT)
        except _core.PixAIError as e:
            return jsonify({"error": str(e)[:300]}), 200
        # 3.21.2 (L1): the gallery's own Video tab (no Loom keys) is a single send, held like
        # the others. A journalled Loom render keeps its journal's own states and is not held
        # here.
        video_key = None if journalled else _send_key("video", p)
        if video_key is not None:
            held = _send_claim(video_key, claim=False)
            if held:
                return held

        # Pictures the road cannot send (review F16). resolve_img below turns anything that is
        # not a catalog id or a data: thumbnail into "", and the render then went out WITHOUT
        # that frame -- paid for, and wrong. Refusing is not a new spend.
        unsendable = [str(x) for x in (p.get("images") or [])
                      if str(x or "").strip() and not str(x).strip().isdigit()
                      and not str(x).strip().startswith("data:")]
        # Spend review S6: the same for the reference VIDEOS and AUDIO. Only catalog ids are
        # sent for those (see video_ids / audio_ids below); anything else -- an imported local_
        # video above all -- was silently dropped, and the render went out, priced and charged,
        # without the reference the card showed.
        unsendable_av = [str(x) for k in ("video_refs", "audio_refs") for x in (p.get(k) or [])
                         if str(x or "").strip() and not str(x).strip().isdigit()]
        # 3.22 S5: an SVG or a GIF is never a video frame (PixAI's rule), by the catalog's
        # recorded format, then the extension, or a data: thumbnail's own type -- refused
        # with the same not_sent journal entry, before resolve_img uploads anything.
        frame_why = next((w for w in (_gen_params.source_refusal(_source_format_lookup(x),
                                                                 "video")
                                      for x in (p.get("images") or []) if str(x or "").strip())
                          if w), "")
        if frame_why:
            unsendable = [frame_why]
            unsendable_msg = frame_why
        elif unsendable:
            unsendable_msg = ("One of this shot's pictures can't be sent to PixAI (an imported "
                              "picture). Nothing was sent.")
        elif unsendable_av:
            unsendable = unsendable_av
            unsendable_msg = ("One of this shot's reference videos or audio can't be sent to PixAI "
                              "(an imported file). Nothing was sent.")
        else:
            unsendable_msg = ""
        if journalled:
            with _loom_journal_lock:
                idx = _loom_journal_load(user)
                prev = idx["subs"].get(submit_id)
                if prev:
                    st = prev.get("state")
                    if st == "submitted" and prev.get("task_id"):
                        return jsonify({"task_id": prev["task_id"], "replay": True})
                    if st == "sending":
                        return jsonify({"state": "sending", "unclear": True,
                                        "error": "This render is still being sent."}), 409
                    if st == "may_have_started":
                        return jsonify({"state": "may_have_started", "unclear": True,
                                        "error": prev.get("error") or "No clear answer from PixAI."})
                    if st == "abandoned":
                        return jsonify({"state": "abandoned",
                                        "error": "This render was released; press Render again."})
                    return jsonify({"state": st or "refused", "replay": True,
                                    "error": prev.get("error") or "This render was not sent."})
                if board_id:
                    live = _loom_journal_live_for(user, board_id, card_id)
                    if live:
                        tid = str(live.get("task_id") or "")
                        return jsonify({
                            "error": "This shot is already rendering"
                                     + (" (task …%s)." % tid[-6:] if tid else "."),
                            "busy_task_id": tid or None}), 409
                if unsendable:
                    msg = unsendable_msg
                    _loom_journal_note(user, submit_id, board=board_id, card=card_id,
                                       state="not_sent", error=msg)
                    return jsonify({"error": msg})
                _loom_journal_note(user, submit_id, board=board_id, card=card_id, state="sending")
                _loom_sending_now.add(sending_key)
        elif unsendable:
            return jsonify({"error": unsendable_msg})

        attempt = {"sent": False}

        def _on_send(_params):
            attempt["sent"] = True

        def _before_send(params):
            # Review F13: the confirm skipped because the shot priced FREE; if the card that
            # quote found is gone by now, sending would charge credits nobody confirmed.
            # The rule is gen_road's (3.22, DESIGN_3.22 3.4); the wording stays the Loom's.
            if expect_free:
                _gen_road.refuse_if_quoted_free_gone(
                    params,
                    "The free card this render was priced with was used elsewhere, so it would "
                    "spend credits. Nothing was sent. Press Render again to see the new price."
                    if journalled else _QUOTED_FREE_GONE)

        # The gallery's own Video tab (no Loom keys) is held to the same rule when its badge
        # said FREE (2026-11-18): before, the guard rode only a journalled Loom render.
        hooks = ({"before_send": _before_send, "on_send": _on_send} if journalled
                 else {"before_send": _before_send} if expect_free else {})
        # The Video tab's spend mark (3.21.2, L1): never reached (nothing sent) told apart from
        # reached with an unclear answer (may have started). Observation only.
        video_mark = _Reached()
        held_key = None

        def _journal(**fields):
            if journalled:
                with _loom_journal_lock:
                    _loom_journal_note(user, submit_id, **fields)

        try:
            import base64
            import hashlib
            core, session_ = _gen_session()
            updir = _paths.loom_root(out_dir) / "_uploads"
            updir.mkdir(parents=True, exist_ok=True)

            # I2V/FLF take a catalog media_id DIRECTLY; R2V still uploads. Measured 2026-07-26,
            # twice over. First by running the identical job on PixAI's own site and reading its
            # submit shape back with --dump-params (task 2038288375164786990, free): it sent
            # i2vPro.mediaId=747704233721405654 and tailMediaId=747643660108554296, BOTH rows in
            # this catalog -- generation OUTPUTS used as i2v INPUTS -- and the video rendered.
            # Then by surveying the owner's own history via getTaskById: 5 of 5 i2vPro tasks used
            # in-catalog ids, across three models, 2026-06-08 through 2026-07-22, including two
            # on 2026-07-20 itself.
            #
            # _input_media_id() assumes the opposite for every path, and its own cited evidence
            # shows why that overreached: `invalid_media_id` / `invalid_reference_image_media_id`
            # -- the second is the REFERENCE-VIDEO field. The requirement was real for R2V's
            # referenceImageMediaIds and got applied everywhere by a shared helper.
            #
            # For i2v it is worse than unnecessary. Uploading turns an image PixAI already holds
            # and already vetted into a BRAND-NEW upload, which its content scanner then checks
            # -- and that is what refused this owner's video with 403 NSFW_DETECTED while the
            # same frames sailed through on the website. The upload was manufacturing the
            # rejection. R2V uploaded too until the 2026-08-22 probe showed its field accepts
            # catalog ids as well -- see resolve_img.

            def resolve_img(val):
                s = str(val or "").strip()
                if not s:
                    return ""
                if s.isdigit():
                    # A catalog id passes through for EVERY mode. R2V was the last holdout,
                    # uploading on the belief that referenceImageMediaIds refuses a
                    # generation output. PROBED 2026-08-22 (getTaskById, 10 of the owner's own
                    # completed R2V tasks, read-only): two completed with ONLY in-library ids
                    # (one with six), four completed with library AND upload ids in the same
                    # submit. The field accepts catalog ids; the all-upload tasks were this
                    # very code re-uploading. (moonglade-internal/probes/
                    # PROBE_2026-08-22_r2v-refs-and-video-fields.md) If PixAI ever refuses
                    # an id synchronously, the upload-and-retry below catches it; see the
                    # note there on why the July refusal may have been asynchronous.
                    return s
                if s.startswith("data:"):             # a Loom thumbnail -> upload it
                    try:
                        head, b64 = s.split(",", 1)
                        raw = base64.b64decode(b64)
                    except Exception:
                        return ""
                    ext = ".png" if "png" in head[:24] else ".jpg"
                    fp = updir / (hashlib.sha1(raw).hexdigest()[:16] + ext)
                    if not fp.exists():
                        fp.write_bytes(raw)
                    return core.upload_media(session_, str(fp))
                return ""                             # a bare filename/URL we can't fetch

            resolved = [(str(x or "").strip(), resolve_img(x)) for x in (p.get("images") or [])]
            image_ids = [rid for _raw, rid in resolved if rid]
            video_ids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip().isdigit()]
            audio_ids = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip().isdigit()]

            def _request_for(imgs):
                # The ONE video road: build_request(mode="video") builds the shot the
                # Loom's own cost badge priced through /api/price, and core.submit is
                # the READ_ONLY + free-card choke. Frames are resolved HERE (data-URL
                # upload / catalog passthrough -- see resolve_img) and handed in already
                # resolved, so the request carries exactly the ids that go out.
                # The video-length lookup is the same one /api/price's resolver carries, so
                # the Loom's submit cannot send a shorter inputVideoDurations than its badge
                # quoted (2026-09-26).
                return _gen_road.build_request({**p, "images": imgs,
                                           "video_refs": video_ids,
                                           "audio_refs": audio_ids}, mode="video",
                                          resolve=_gen_road.RequestResolver(
                                              video_duration=_video_duration_lookup,
                                              source_format=_source_format_lookup))

            req = _request_for(image_ids)
            params = req.parameters      # bound for _log_gen_failure's locals().get()
            if video_key is not None:
                held = _send_claim(video_key)
                if held:
                    return held
                held_key = video_key
            try:
                attempt["sent"] = False
                task_id = _gen_road.submit(session_, req, **hooks)["task_id"]
            except core.PixAIError as e:
                # SURVEYED, not guessed. getTaskById across the owner's own video history
                # (2026-07-26, read-only, no credits) found EVERY i2vPro task carrying an
                # in-catalog media id -- 5 of 5, zero uploads, across v3.2 / v4.0 / v4.0.1 and
                # spanning 2026-06-08 to 2026-07-22. Two of them are dated 2026-07-20, the very
                # day the "catalog ids are refused" bug was recorded, and they rendered fine.
                #
                # So PixAI never changed and i2vPro has always accepted a generation-OUTPUT id.
                # The July conclusion was generalised from the R2V error name
                # `invalid_reference_image_media_id`, and the resulting shared helper made every
                # gallery i2v re-upload its frame for a week.
                #
                # This fallback is therefore INSURANCE, not a coin-flip: cheap, already tested,
                # and it keeps a spend path working if that July observation turns out to be real
                # under some condition this survey did not cover.
                #
                # The passthrough attempt is what MATTERS for NSFW work: uploading converts an
                # image PixAI already holds and already vetted into a brand-new upload, and the
                # content scanner then refuses it (403 NSFW_DETECTED, no task) while the very
                # same frames pass on the website. The upload was manufacturing the rejection.
                #
                # Safe ONLY when PixAI answered with a GraphQL error and REJECTED the task (a
                # definite refusal, checked below), so there is nothing created and nothing
                # charged to duplicate. A partial success is not that (spend review S1).
                # Both error names: `invalid_media_id` (i2vPro) and
                # `invalid_reference_image_media_id` (R2V's own field). The passthrough now
                # applies to every mode (probe 2026-08-22), so the fallback does too.
                #
                # HONEST SCOPE (adversarial review 2026-08-22): this only catches a
                # SYNCHRONOUS GraphQL rejection. The 2026-07-20 failures came "with a full
                # refund", which means those tasks were created and charged, then failed
                # ASYNCHRONOUSLY -- a path that surfaces through the poll's failure_reason
                # (_task_failure_reason), never through this except. So this is a free
                # belt-and-braces for a sync refusal, not a guarantee; the user-facing
                # safety net for an async refusal is the poll reporting the reason.
                err = str(e)
                if "invalid_media_id" not in err and "invalid_reference_image_media_id" not in err:
                    raise
                # Spend review S1: the error TEXT is not enough. A GraphQL answer can carry
                # `errors` AND a resolved `data` at once -- a partial success, where the task
                # was created and charged -- and it can name invalid_media_id all the same.
                # Only a definite refusal created nothing; anything else goes to the classifier
                # below and is journalled may_have_started, never submitted a second time.
                if not _gen_road.definite_refusal(e):
                    raise
                # Spend review N1: the refused first attempt sent nothing that exists, so from
                # here "sent" describes the fallback alone. A re-upload that fails below is
                # then journalled not_sent, not may_have_started (which held the shot for 6 h
                # over a render that was never created).
                attempt["sent"] = False
                video_mark.v = False          # the refused first try made nothing (L1)
                _logging_ = __import__("logging")
                _logging_.getLogger(__name__).info(
                    "passthrough refused (%s); uploading frames and retrying", err[:80])
                # Session P (BUILD-w5-p open call 5, owner-confirmed 2026-09-29): KEPT, and
                # journalled. A GraphQL refusal creates nothing, so this second core.submit is
                # not a re-send of a render that may exist -- but it IS a second attempt, and
                # the journal says so, so the owner's spend review can see every one.
                _journal(fallback=("invalid_reference_image_media_id"
                                   if "invalid_reference_image_media_id" in err
                                   else "invalid_media_id"))
                # Re-resolve ONLY the catalog (digit) ids through the upload path. Anything
                # else -- a Loom data: thumbnail already uploaded on the first pass, a bare
                # filename that resolved to "" -- keeps its first-pass result. Re-running
                # the raw payload here threw the thumbnail's upload away and sent the
                # base64 blob as a media id (adversarial review, 2026-08-22).
                image_ids = [m for m in ((_input_media_id(core, session_, raw) if raw.isdigit() else rid)
                                         for raw, rid in resolved) if m]
                req = _request_for(image_ids)
                params = req.parameters   # rebound for the failure log below
                attempt["sent"] = False
                task_id = _gen_road.submit(session_, req, **hooks)["task_id"]
            try:                       # Master of the Loom + Storyweaver telemetry
                mode = str(p.get("mode") or "R2V").upper()
                if mode in ("I2V", "FLF", "R2V"):
                    _telemetry.telem_set_add("video_modes", mode.lower(), out_dir=out_dir)
                if str(p.get("origin") or "") == "loom-shot":
                    _telemetry.telem_bump("storyboards", out_dir=out_dir)
            except Exception:
                pass
            _send_settle(held_key, "sent")
            _note_card_sent(task_id, req.parameters)         # 2.4 rule 7's terminal check
            _journal(state="submitted", task_id=str(task_id))
            if send_board:
                # THE SEND RECORD: the one source of the board's "spent" figure. A free card
                # attached by the card step is a charge of 0; otherwise the charge is read off
                # the catalog once PixAI reports it.
                _loom_send_note(user, board=send_board, card=send_card, task_id=str(task_id),
                                submit_id=submit_id,
                                cost=0 if (req.parameters or {}).get("kaisuukenId") else None)
            return jsonify({"task_id": task_id, "uploaded": len(image_ids)})
        except Exception as e:
            if not journalled:
                # The Video tab: the single sends' rule (3.21.2, L1) -- an unknown outcome is
                # said plainly and held; anything else carries its state, as before.
                unclear, msg, state = _send_failed("/api/loom/generate", e, video_mark.v,
                                                   locals().get("params"), held_key,
                                                   task_id=locals().get("task_id"))
                return unclear or (jsonify({"error": msg, "state": state}), 200)
            created = locals().get("task_id")
            if created:
                # The render WAS created; only the bookkeeping after it failed (3.21.2 review).
                # The journal says so (submitted), and the answer is the success it is.
                try:
                    _journal(state="submitted", task_id=str(created))
                except Exception:                            # noqa: BLE001
                    pass
                _send_failed("/api/loom/generate", e, True, None, None, task_id=created)
                return jsonify({"task_id": created})
            msg = _log_gen_failure("/api/loom/generate", e, locals().get("params"))[:300]
            if not attempt["sent"]:
                state = "not_sent"
            elif getattr(e, "refused", False) or _gen_road.definite_refusal(e):
                state = "refused"
            else:
                state = "may_have_started"
            _journal(state=state, error=msg)
            if state == "may_have_started" and send_board:
                # Sent with no clear answer: the board may have spent on it, and nobody can say
                # what. It counts as unknown until the owner releases it (submit-abandon).
                _loom_send_note(user, board=send_board, card=send_card, task_id=None,
                                submit_id=submit_id, cost=None)
            if state == "may_have_started":
                return jsonify({"error": msg, "unclear": True, "state": state}), 200
            return jsonify({"error": msg, "state": state}), 200
        finally:
            # Spend review B1: this request is no longer sending, whatever became of it. The
            # outcome was journalled above first, so there is no moment when the id is out of
            # the set while the journal still says "sending" for a live request.
            if sending_key is not None:
                with _loom_journal_lock:
                    _loom_sending_now.discard(sending_key)

    @app.route("/api/loom/submit-status")
    @tier(LOGIN)
    def loom_submit_status():
        """What the journal knows about one Loom render (Session P, BUILD-w5-p §3.3): the
        client asks this -- never re-POSTs -- when its own POST got no answer. Local only.
        {state: sending | submitted | refused | not_sent | may_have_started | abandoned |
        unknown, task_id?, error?, finished?, sending?}

        `sending: true` (GitHub #86) is added when the request is still running in THIS
        process -- the same set submit-abandon consults to refuse a release. The journal's
        `state: "sending"` alone cannot tell a live send from one that died with an earlier
        process, so a reloaded tab reads this flag to stop offering a release the server
        would refuse. A read only: it changes nothing about what submit-abandon allows."""
        user = str(session.get("user") or "")
        sid = str(request.args.get("submit_id") or "")
        if not _LOOM_ID_RE.match(sid):
            return jsonify({"state": "unknown"})
        with _loom_journal_lock:
            e = dict(_loom_journal_load(user)["subs"].get(sid) or {})
            live = (_account_prefs._account_key(user), sid) in _loom_sending_now
        if not e:
            return jsonify({"state": "unknown"})
        out = {"state": e.get("state") or "unknown"}
        for k in ("task_id", "error", "finished"):
            if e.get(k):
                out[k] = e[k]
        if live and out["state"] == "sending":
            out["sending"] = True
        return jsonify(out)

    @app.route("/api/loom/submit-abandon", methods=["POST"])
    @tier(LOGIN)
    def loom_submit_abandon():
        """The owner checked Activity and releases a shot whose render was never confirmed
        (Session P, review F8): records `abandoned`, so the one-render-per-shot check stops
        blocking it. Never re-sends, never calls PixAI. A render the journal knows was SENT
        (it has a task id) cannot be released -- the client adopts that task instead."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "bad csrf"}), 403
        user = str(session.get("user") or "")
        sid = str(body.get("submit_id") or "")
        if not _LOOM_ID_RE.match(sid):
            return jsonify({"error": "submit_id required"}), 400
        with _loom_journal_lock:
            e = _loom_journal_load(user)["subs"].get(sid) or {}
            # Spend review B1: a render whose request is still running in this process is not
            # unclear, it is slow. Releasing it would free the shot for a second paid render
            # while this one is still inside core.submit. (A send that died with an earlier
            # process is not in the set, so it can still be released.)
            if (_account_prefs._account_key(user), sid) in _loom_sending_now:
                return jsonify({"error": "This render is still being sent. Wait for PixAI's answer, "
                                         "then check again.", "sending": True}), 409
            if e.get("state") == "submitted" and e.get("task_id"):
                return jsonify({"error": "That render was sent (task …%s), so it can't be released."
                                         % str(e["task_id"])[-6:], "task_id": e["task_id"]}), 409
            _loom_journal_note(user, sid, state="abandoned")
            # Released: nothing was made, so its unknown leaves the board's send record.
            with _loom_sends_lock:
                _loom_sends_append(user, [{"submit_id": sid, "void": True, "at": time.time()}])
        return jsonify({"ok": True})


    def _run_export(cmd, out_path, total_sec):
        """Run the ffmpeg concat in a thread, parsing time= for progress. The output
        (--pix_fmt yuv420p h264) is a normal mp4 the browser can play + download.

        This is the one media invocation that stays a Popen rather than going through
        media_tools' run_ffmpeg: the export streams ffmpeg's stderr line by line to drive
        a progress bar, and a run_* that waits for the process to finish cannot report
        progress on a job that takes minutes. It still takes its BINARY and its no-window
        FLAG from media_tools (cmd[0] is core.ffmpeg_path(), set by the caller), so the
        two things that drifted between call sites are still decided in one place."""
        import subprocess, collections, re as _re
        tpat = _re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE,
                                    text=True, bufsize=1, encoding="utf-8", errors="replace",
                                    creationflags=_media_tools.NO_WINDOW)
            with _export_lock:
                _export_job["proc"] = proc
            # ffmpeg's last few non-progress lines are its whole explanation on a refusal;
            # keep them so a failed export says why instead of only "ffmpeg exited N".
            tail = collections.deque(maxlen=4)
            for line in iter(proc.stderr.readline, ""):
                m = tpat.search(line)
                if not m and line.strip():
                    tail.append(line.strip())
                if m:
                    el = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    with _export_lock:
                        _export_job["elapsed"] = round(el, 1)
                        _export_job["progress"] = min(99, int(el / total_sec * 100)) if total_sec else 0
            rc = proc.wait()
            with _export_lock:
                _export_job["proc"] = None
                if _export_job.get("cancelled"):
                    _export_job["status"] = "cancelled"
                elif rc == 0 and out_path.exists():
                    _export_job.update(status="done", progress=100, out=out_path.name)
                else:
                    why = _redact_host_paths(" | ".join(tail))[-300:]
                    _export_job.update(status="failed",
                                       error=("ffmpeg exited %d: %s" % (rc, why)) if why
                                       else "ffmpeg exited %d" % rc)
        except Exception as e:
            with _export_lock:
                _export_job.update(status="failed", error=_redact_host_paths(str(e))[:200], proc=None)

    # ==== THE MUSIC BED (Session P, P3) ======================================================
    # One local audio file per storyboard, never uploaded and never sent to PixAI. These routes
    # store, stream and (only on the owner's confirmed ask) sweep bed files; putting a bed on a
    # board, levelling it and removing it are board edits the Loom saves through /api/loom/set.
    # None of them can reach a render: dev/tests/test_loom_p_routes.py runs every one with the
    # spend functions booby-trapped and walks their source for the names.
    @app.route("/api/loom/bed", methods=["POST"])
    @tier(LOGIN)
    def api_loom_bed_upload():
        """multipart {csrf, board, file} -> {file, name, dur, bytes}. The 50 MB cap is enforced
        BEFORE the body is read (the declared length) and while it is read (a hard stream
        limit); the type is sniffed from the bytes, never the file name; the file is stored
        under the sha1 of its bytes, atomically, and an identical bed is not rewritten."""
        from moonglade.loom_files import (LOOM_BED_FORM_SLACK, LOOM_BED_MAX_BYTES, _unlink_quiet,
                                          sniff_audio_ext)
        import tempfile
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        cap_msg = "A music bed can be up to %d MB." % (LOOM_BED_MAX_BYTES // (1024 * 1024))
        length = request.content_length
        if length is None:
            return jsonify({"error": "The upload did not say how big it is."}), 411
        if length > LOOM_BED_MAX_BYTES + LOOM_BED_FORM_SLACK:
            return jsonify({"error": cap_msg}), 413
        # A hard limit on what the form parser may read, whatever the declared length claims.
        request.max_content_length = LOOM_BED_MAX_BYTES + LOOM_BED_FORM_SLACK
        try:
            form, files = request.form, request.files
        except Exception:                                   # RequestEntityTooLarge, a torn body
            return jsonify({"error": cap_msg}), 413
        if not _check_csrf(form):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        board = str(form.get("board") or "")
        if board and not _LOOM_ID_RE.match(board):
            return jsonify({"error": "bad board id"}), 400
        f = files.get("file")
        if f is None:
            return jsonify({"error": "no file"}), 400
        tmp_dir = _loom_beds_dir(user)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=str(tmp_dir))
        total, head = 0, b""
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = f.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > LOOM_BED_MAX_BYTES:
                        raise ValueError("too big")
                    if len(head) < 64:
                        head = (head + chunk)[:64]
                    out.write(chunk)
            ext = sniff_audio_ext(head)
            if total == 0 or ext is None:
                raise TypeError("not audio")
            name = _loom_store_bed(user, tmp, ext)
        except ValueError:
            _unlink_quiet(tmp)
            return jsonify({"error": cap_msg}), 413
        except TypeError:
            _unlink_quiet(tmp)
            return jsonify({"error": "That isn't an audio file the Loom can use (mp3, wav, m4a, aac, ogg or flac)."}), 415
        except OSError as e:
            _unlink_quiet(tmp)
            return jsonify({"error": _redact_host_paths(str(e))[:120]}), 500
        dur = None
        try:
            d = _media_tools.duration(str(_loom_beds_dir(user) / name))
            dur = round(d, 3) if d else None
        except Exception:
            dur = None
        display = re.sub(r"[\x00-\x1f\x7f]", "", os.path.basename(str(f.filename or "")))[:120] or "music bed"
        return jsonify({"file": name, "name": display, "dur": dur, "bytes": total})

    @app.route("/api/loom/bed", methods=["GET"])
    @tier(LOGIN)
    def api_loom_bed_get():
        """?file=<sha1>.<ext> -> the caller's own bed, streamed (HTTP Range for seeking).
        The name must match the pattern AND resolve inside the caller's own bed folder."""
        from moonglade.loom_files import LOOM_BED_MIMES
        from moonglade.web_policy import harden_file_response
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        name = request.args.get("file") or ""
        p = _loom_bed_path(user, name)
        if p is None:
            return jsonify({"error": "no such music bed"}), 404
        return harden_file_response(
            send_file(str(p), mimetype=LOOM_BED_MIMES.get(p.suffix.lstrip("."), "application/octet-stream"),
                      conditional=True, max_age=3600), p.name)

    @app.route("/api/loom/beds/unused")
    @tier(LOGIN)
    def api_loom_beds_unused():
        """The caller's bed files no board of the account references (ruling 15: they are
        never deleted automatically; this is what the owner's explicit sweep offers).
        {files: [{file, bytes}], count, bytes, h}. Read-only."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        try:
            rows = _loom_unused_beds(user)
        except _LoomUnreadable as e:
            return _loom_beds_unreadable_answer(user, e)
        total = sum(b for (_n, b) in rows)
        return jsonify({"files": [{"file": n, "bytes": b} for (n, b) in rows],
                        "count": len(rows), "bytes": total, "h": _health._fmt_size(total)})

    @app.route("/api/loom/beds/sweep", methods=["POST"])
    @tier(LOGIN)
    def api_loom_beds_sweep():
        """{csrf, files: [...]} -> deletes ONLY the named beds that are still unused when it
        looks again (a board saved in between keeps its bed). {removed, kept}."""
        from moonglade.loom_files import LOOM_BED_FILE_RE
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        want = body.get("files")
        if not isinstance(want, list) or len(want) > 500:
            return jsonify({"error": "files must be a list"}), 400
        want = [str(x) for x in want]
        if any(not LOOM_BED_FILE_RE.match(x) for x in want):
            return jsonify({"error": "bad bed file name"}), 400
        try:
            unused = {n for (n, _b) in _loom_unused_beds(user)}
        except _LoomUnreadable as e:
            return _loom_beds_unreadable_answer(user, e)
        removed, kept = [], []
        for n in want:
            p = _loom_bed_path(user, n)
            if p is None or n not in unused:
                kept.append(n)
                continue
            try:
                p.unlink()
                removed.append(n)
            except OSError:
                kept.append(n)
        return jsonify({"ok": True, "removed": removed, "kept": kept})

    # ==== THE EDITOR HANDOFF EXPORT (Session P, P4) ============================================
    # One zip: the .edl and .csv the Loom planned (loom/src/loom-edl-core.js), every selected
    # take's clip under its {code}_t{take}.mp4 name, the bed when there is one (ruling 8), and
    # MISSING.txt for any clip that is not a complete file here. Local files only; never PixAI.
    _loom_exports_dir = _paths.loom_root(out_dir) / "_exports"
    # A leftover from an export whose download never closed (a client abort, a Windows file
    # handle) is swept on the next start once it is an hour old (review F18).
    try:
        for _old in (_loom_exports_dir.glob("*.zip") if _loom_exports_dir.is_dir() else []):
            try:
                if time.time() - _old.stat().st_mtime > LOOM_EXPORT_SWEEP_AGE_S:
                    _old.unlink()
            except OSError:
                pass
    except OSError:
        pass

    @app.route("/api/loom/export-edl", methods=["POST"])
    @tier(LOGIN)
    def api_loom_export_edl():
        """{csrf, name, edl, csv, clips: [{mid, file}], bed_file?, bed_name?} -> a zip download.
        Every name is validated against the pattern the planner uses, every mid against the
        media-id grammar, the bed against the caller's own folder (F19); the zip is written to
        out_dir/_moonglade/loom/_exports/<uuid>.zip, streamed, and deleted when the response closes."""
        from moonglade.loom_files import (LOOM_EDL_BED_NAME_RE, LOOM_EDL_CLIP_RE,
                                          LOOM_EDL_MAX_CLIPS, LOOM_EDL_MAX_CSV_CHARS,
                                          LOOM_EDL_MAX_EDL_CHARS, LOOM_MEDIA_ID_RE, _unlink_quiet,
                                          loom_edl_zip_stem)
        import uuid
        import zipfile
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        edl, csv_text = body.get("edl"), body.get("csv")
        if not isinstance(edl, str) or not isinstance(csv_text, str) or not edl.strip():
            return jsonify({"error": "edl and csv are required"}), 400
        if len(edl) > LOOM_EDL_MAX_EDL_CHARS or len(csv_text) > LOOM_EDL_MAX_CSV_CHARS:
            return jsonify({"error": "That edit decision list is too large."}), 413
        clips = body.get("clips")
        if not isinstance(clips, list) or len(clips) > LOOM_EDL_MAX_CLIPS:
            return jsonify({"error": "clips must be a list"}), 400
        seen, plan = set(), []
        for c in clips:
            if not isinstance(c, dict):
                return jsonify({"error": "bad clip"}), 400
            mid, fname = str(c.get("mid") or ""), str(c.get("file") or "")
            if not LOOM_MEDIA_ID_RE.match(mid) or not LOOM_EDL_CLIP_RE.match(fname):
                return jsonify({"error": "bad clip name or id: %s" % re.sub(r"[^A-Za-z0-9_.-]", "", fname)[:40]}), 400
            if fname.lower() in seen:
                return jsonify({"error": "two clips share the name %s" % fname}), 400
            seen.add(fname.lower())
            plan.append((mid, fname))
        stem = loom_edl_zip_stem(body.get("name"))
        bed_path, bed_name = None, ""
        if body.get("bed_file"):
            bed_path = _loom_bed_path(user, body.get("bed_file"))
            if bed_path is None:
                return jsonify({"error": "That music bed isn't in your beds folder."}), 400
            bed_name = str(body.get("bed_name") or "")
            ext = bed_path.suffix.lstrip(".")
            if not LOOM_EDL_BED_NAME_RE.match(bed_name) or not bed_name.endswith("." + ext):
                bed_name = "music_bed." + ext
        _loom_exports_dir.mkdir(parents=True, exist_ok=True)
        zpath = _loom_exports_dir / (uuid.uuid4().hex + ".zip")
        missing = []
        try:
            with zipfile.ZipFile(str(zpath), "w", zipfile.ZIP_STORED) as z:
                z.writestr(stem + ".edl", edl)
                z.writestr(stem + ".csv", csv_text)
                for mid, fname in plan:
                    p = _loom_complete_clip(mid)
                    if p is None:
                        missing.append("%s  %s  (no complete file for this clip in the library)" % (fname, mid))
                    elif p.suffix.lower() != ".mp4":
                        missing.append("%s  %s  (the library file is %s, not .mp4)" % (fname, mid, p.suffix.lower()))
                    else:
                        z.write(str(p), arcname=fname)
                if bed_path is not None:
                    z.write(str(bed_path), arcname=bed_name)
                if missing:
                    z.writestr("MISSING.txt", "These clips are named in the edit decision list but are "
                               "not in this zip:\r\n\r\n" + "\r\n".join(missing) + "\r\n")
        except OSError as e:
            _unlink_quiet(zpath)
            return jsonify({"error": _redact_host_paths(str(e))[:160]}), 500
        # Streamed from the temp file by a plain generator rather than send_file: a send_file
        # response is "direct passthrough", and Werkzeug then never runs call_on_close -- the
        # zip would outlive every download. Here the response's close() (the download ended,
        # or the client went away) deletes it; the start-up sweep takes any a crash left.
        from flask import Response

        def _stream():
            with open(str(zpath), "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    yield chunk
        resp = Response(_stream(), mimetype="application/zip")
        resp.headers["Content-Disposition"] = 'attachment; filename="%s.zip"' % stem
        resp.headers["Content-Length"] = str(zpath.stat().st_size)
        resp.headers["X-Edl-Missing-Count"] = str(len(missing))
        resp.call_on_close(lambda: _unlink_quiet(zpath))
        return resp

    # ==== "AS SHOTS, IN ORDER" (Session P, P5) ===================================================
    @app.route("/api/loom/prompts")
    @tier(LOGIN)
    def api_loom_prompts():
        """?ids=a,b,c -> {pictures: [{media_id, prompt, created_at, is_video}]} in the order
        asked, unknown ids left out. A READ-ONLY lookup of those ids' local catalog rows: the
        Loom titles a collection's shots from it, the gallery orders a plain selection by it.
        Never PixAI."""
        from moonglade.catalog_verbs import rows_for_media_ids
        from moonglade.loom_files import LOOM_MEDIA_ID_RE
        raw = [x.strip() for x in (request.args.get("ids") or "").split(",") if x.strip()]
        if len(raw) > 200:
            return jsonify({"error": "at most 200 ids at once"}), 400
        ids = [x for x in raw if LOOM_MEDIA_ID_RE.match(x)]
        pics = []
        for r in rows_for_media_ids(db_path, ids):
            pics.append({"media_id": str(r.get("media_id") or ""),
                         "prompt": str(r.get("prompt_full") or r.get("prompt_preview") or "")[:2000],
                         "created_at": str(r.get("created_at") or ""),
                         "is_video": str(r.get("is_video") or "") == "1"})
        return jsonify({"pictures": pics})

    @app.route("/api/loom/export", methods=["POST"])
    @tier(LOGIN)
    def api_loom_export():
        """Trim each finished shot to its in/out and concat into one 720p mp4 -- the
        rough cut becomes a real deliverable. Async (ffmpeg in a thread); poll
        /api/loom/export-status, download /api/loom/export-file. Login required (any session, local or LAN).
        Each segment's real audio rides along when the clip has one (ffprobe-detected);
        segments with no audio stream (e.g. rendered without the "Generate audio" toggle)
        get matching-duration silence synthesized (anullsrc) so the concatenated audio
        track never desyncs across a segment boundary. "Matching" is load-bearing, not
        best-effort: a span is only ever a trim's own out point or a real ffprobe
        measurement, never a guess. When neither exists the export does NOT quietly pad --
        it either drops the audio track entirely (when there was no real audio anywhere, so
        nothing is lost) or refuses and names the shot (when real audio would be thrown out
        of sync by it). See the span pre-pass below. body: {clips:[{mid,in,out}], total_seconds}"""
        from moonglade.thumbs import probe_duration, probe_has_audio
        from moonglade.catalog import get_row
        from moonglade.loom_files import loom_bed_audio_graph, loom_bed_windows
        if not _media_tools.ffmpeg_path():
            return jsonify({"error": "ffmpeg is not on PATH -- install it to export."}), 400
        # ffprobe deliberately is NOT gated here alongside ffmpeg -- media_tools resolves the
        # two separately for exactly this reason. It usually ships in the
        # same package, and probe_has_audio()/probe_duration() both fail soft when it is
        # absent -- which means on a machine with ffmpeg but no ffprobe EVERY clip reads as
        # silent and no duration is readable, i.e. the common untrimmed shot would trip an
        # up-front gate and the owner would get no export at all. That machine used to get a
        # file (badly desynced, but a file), and taking the file away is a hard change to a
        # documented feature over a dependency the wiki does not ask for. So a missing
        # ffprobe DEGRADES here (see the span pre-pass: no measurable spans and no real
        # audio anywhere -> the cut is muxed without an audio track, which is the same thing
        # you would have heard, since every segment's audio was going to be synthesized
        # silence). A refusal is kept for the one case where continuing is definitively
        # corrupt: some shot HAS real audio and another cannot be measured, where a guessed
        # span shifts that real audio permanently out of sync.
        with _export_lock:
            if _export_job["status"] == "running":
                return jsonify({"error": "an export is already running"}), 409
        body = request.get_json(silent=True) or {}
        try:
            total_sec = float(body.get("total_seconds") or 0) or 1.0
        except (TypeError, ValueError):
            total_sec = 1.0
        segs = []
        # Session P (P3): per segment, whether the shot has its own audio (the Loom's one
        # definition, loom-bed-core.js hasOwnAudio -- the bed ducks under it) and the span the
        # Loom computed for it (the bed's timing falls back to it when a length can't be read).
        seg_meta = []
        for c in (body.get("clips") or []):
            mid = str(c.get("mid") or "")
            if not mid:
                continue
            # Resolve the shot's video the same way /video-file does: catalog row ->
            # filename (find_files_for_media_id is image-only, so it never sees mp4s).
            row = get_row(db_path, mid)
            if not row or str(row.get("is_video") or "") != "1" or not row.get("filename"):
                continue
            path = str(out_dir / row["filename"])
            if not os.path.exists(path):
                continue
            try:
                ci = max(0.0, float(c.get("in") or 0))
            except (TypeError, ValueError):
                ci = 0.0
            co = c.get("out")
            try:
                co = float(co) if co not in (None, "") else None
            except (TypeError, ValueError):
                co = None
            # Optional spatial crop: {x,y,w,h} fractions of the frame. Sanitized to a valid
            # in-bounds sub-rectangle; anything malformed or effectively full-frame -> no crop.
            crop = None
            cr = c.get("crop")
            if isinstance(cr, dict):
                try:
                    cx, cy = float(cr.get("x") or 0), float(cr.get("y") or 0)
                    cw, ch = float(cr.get("w") or 0), float(cr.get("h") or 0)
                    cx = min(max(cx, 0.0), 1.0); cy = min(max(cy, 0.0), 1.0)
                    cw = min(cw, 1.0 - cx); ch = min(ch, 1.0 - cy)
                    if cw > 0.05 and ch > 0.05 and (cw < 0.99 or ch < 0.99 or cx > 0.01 or cy > 0.01):
                        crop = (cx, cy, cw, ch)
                except (TypeError, ValueError):
                    crop = None
            # mid rides along purely so a per-segment failure below can name the shot the
            # owner has to go fix -- the on-disk path is a host path we don't hand back.
            segs.append((path, ci, co, probe_has_audio(path), crop, mid))
            try:
                cspan = float(c.get("span")) if c.get("span") not in (None, "") else None
            except (TypeError, ValueError):
                cspan = None
            seg_meta.append((bool(c.get("own_audio")), cspan))
        if not segs:
            return jsonify({"error": "no finished shot videos found on disk to export"}), 400
        # THE MUSIC BED (Session P, P3): mixed under the cut by the page's rules, from the
        # caller's own bed folder (never a path the client names). A bed that is not there is
        # left out and the owner is told, rather than failing the whole cut.
        bed_req = body.get("bed") if isinstance(body.get("bed"), dict) else None
        bed_path = _loom_bed_path(str(session.get("user") or ""), bed_req.get("file")) if bed_req else None
        bed_warning = ("The music bed's file isn't in your beds folder, so the cut was rendered "
                       "without it.") if (bed_req and bed_req.get("file") and bed_path is None) else ""
        _export_dir.mkdir(parents=True, exist_ok=True)
        out_path = _export_dir / "loom_cut.mp4"
        W, H = 1280, 720
        parts, labels = [], ""
        # --- silence spans, resolved BEFORE a single filter string is built ----------
        # A silent segment needs an explicit numeric span to synthesize (anullsrc has no
        # natural end), and the number has to be RIGHT: concat lays each segment's audio
        # end-to-end, so silence shorter than its own video does not merely mute that shot's
        # tail -- every LATER segment's audio starts early and stays early for the rest of
        # loom_cut.mp4. Until 2026-07-27 an unreadable duration silently became
        # `max(0.1, (ci + 0.1) - ci)` == 0.1s, which manufactured exactly the desync this
        # whole path exists to prevent, in an export that reports "done" and looks finished
        # until you watch past the first shot.
        #
        # Doing the whole pass up front, instead of deciding shot-by-shot mid-assembly, is
        # what makes the fallback answerable: "can this export have a correct audio track at
        # all" is a question about the WHOLE clip list, and it has two very different
        # answers depending on whether any real audio is in play.
        spans = {}           # segment index -> silence span (silent segments only)
        unmeasurable = []    # media_ids of silent, untrimmed shots with no readable length
        for i, (path, ci, co, has_audio, crop, mid) in enumerate(segs):
            if has_audio:
                continue
            if co is not None:
                spans[i] = co - ci          # the trim's own end: exact, no probe needed
                continue
            dur = probe_duration(path)
            if dur is None:
                unmeasurable.append(mid)
                continue
            # Floor kept for the degenerate case a real measurement can still produce: a
            # trim-in at or past the clip's end leaves nothing, and atrim=duration=0 is not
            # a valid filter argument. This one IS a fudge, and a knowingly small one -- the
            # video side of such a segment is empty too, so the mismatch it can introduce is
            # bounded by 0.1s on a shot the owner has already trimmed into oblivion.
            spans[i] = max(0.1, dur - ci)
        have_real_audio = any(ha for (_p, _ci, _co, ha, _cr, _m) in segs)
        audio_track = True
        export_warning = ""      # set only when the cut comes out different from what was asked
        if unmeasurable and have_real_audio:
            # Some shot carries real recorded audio and another cannot be measured. Padding
            # the unmeasurable one with a guess would push that real audio permanently out
            # of sync, and dropping the track would throw the owner's actual audio away.
            # Both outcomes are worse than not producing a file, so this is the one refusal
            # left -- and since real audio was detected, ffprobe is demonstrably working,
            # which makes the named file itself the suspect.
            return jsonify({"error":
                "Shot %s has no audio track and no out point, so the export needs its real "
                "length to keep the shots that DO have audio in sync -- but ffprobe could "
                "not read its duration (the file may be truncated or still downloading). "
                "Set that shot's out point, or fix the file, then export again."
                % unmeasurable[0]}), 400
        if unmeasurable:
            # No real audio anywhere, so the entire audio track was going to be synthesized
            # silence. Mux without one instead of inventing lengths: the cut sounds exactly
            # the same, nothing can drift, and the owner gets the deliverable. This is the
            # ffmpeg-without-ffprobe machine's normal path -- probe_has_audio() answers
            # False for every clip there, so `have_real_audio` cannot be true.
            audio_track = False
            # Say it on the OWNER'S screen, not only in the log. A missing ffprobe is a
            # prerequisite problem with a one-line cure, and the person who can fix it is the
            # one staring at the export dialog -- handing them a quietly silent cut and filing
            # the reason in a log file they have no reason to open is how this stays a mystery.
            export_warning = (
                "Exported with no audio track. %d shot(s) (%s) have no audio, no out point, "
                "and their real length could not be measured, so there was nothing to keep in "
                "sync against.%s"
                % (len(unmeasurable), ", ".join(unmeasurable[:5]),
                   " ffprobe is not installed -- it ships with the full ffmpeg build, and "
                   "installing it restores measured lengths and audio."
                   if not _media_tools.ffprobe_path() else ""))
            try:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "loom export: %d shot(s) (%s) have no audio stream, no out point and no "
                    "readable duration%s -- exporting with no audio track rather than "
                    "padding with a guessed length.",
                    len(unmeasurable), ", ".join(unmeasurable[:5]),
                    " (ffprobe is not on PATH; it ships with the full ffmpeg build)"
                    if not _media_tools.ffprobe_path() else "")
            except Exception:
                pass
        need_silence = audio_track and any(not ha for (_p, _ci, _co, ha, _cr, _m) in segs)
        silence_idx = len(segs)   # the synthetic-silence input, appended after all real -i's
        bed_idx = len(segs) + (1 if need_silence else 0)   # the bed's input, after the silence
        for i, (path, ci, co, has_audio, crop, _mid) in enumerate(segs):
            tr = "trim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
            # A per-shot crop happens in SOURCE pixels (iw/ih), before the scale-to-canvas, so
            # the kept region fills the 1280x720 frame. No crop -> the chain is unchanged.
            crop_f = ("crop=iw*%.4f:ih*%.4f:iw*%.4f:ih*%.4f," % (crop[2], crop[3], crop[0], crop[1])) if crop else ""
            parts.append("[%d:v]%s,setpts=PTS-STARTPTS,%sscale=%d:%d:force_original_aspect_ratio=decrease,"
                         "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v%d]" % (i, tr, crop_f, W, H, W, H, i))
            if audio_track and has_audio:
                atr = "atrim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
                parts.append("[%d:a]%s,asetpts=PTS-STARTPTS[a%d]" % (i, atr, i))
            elif audio_track:
                # [silence_idx:a] is a raw decoder-input reference (the lavfi anullsrc), not a
                # named filter output -- ffmpeg allows referencing it multiple times (once per
                # silent segment) without an explicit asplit.
                parts.append("[%d:a]atrim=duration=%.3f,asetpts=PTS-STARTPTS[a%d]"
                             % (silence_idx, spans[i], i))
            # concat's input pads are PER-SEGMENT interleaved (v0,a0,v1,a1,...), never grouped
            # by stream type (v0,v1,...,a0,a1,...) -- ffmpeg errors "media type mismatch" if
            # the pad order doesn't match n*(v+a) in that exact per-segment sequence.
            labels += ("[v%d][a%d]" % (i, i)) if audio_track else ("[v%d]" % i)
        fc = ";".join(parts) + ";" + labels + (
            "concat=n=%d:v=1:a=1[vout][%s]" % (len(segs), "acut" if bed_path is not None else "aout")
            if audio_track else "concat=n=%d:v=1:a=0[vout]" % len(segs))
        if bed_path is not None:
            # Each segment's length in the cut: the trim's own out point, else the measured
            # file, else the span the Loom computed -- the same order the silence pass uses.
            bed_spans = []
            for i, (path, ci, co, _ha, _cr, _m) in enumerate(segs):
                if co is not None:
                    sp = co - ci
                else:
                    d = spans.get(i)
                    if d is None:
                        pd = probe_duration(path)
                        d = (pd - ci) if pd is not None else seg_meta[i][1]
                    sp = d
                bed_spans.append(max(0.1, float(sp if sp is not None else 0.1)))
            cut_len = sum(bed_spans)
            try:
                bed_dur = float(bed_req.get("dur")) if bed_req.get("dur") not in (None, "") else None
            except (TypeError, ValueError):
                bed_dur = None
            measured = probe_duration(str(bed_path))
            if measured:
                bed_dur = measured
            bed_len = min(bed_dur, cut_len) if bed_dur else cut_len
            fc += ";" + loom_bed_audio_graph(
                bed_idx, bed_req.get("db", -8), cut_len, bed_dur,
                loom_bed_windows(bed_spans, [m[0] for m in seg_meta], bed_len),
                cut_label="acut" if audio_track else None, out_label="aout")
            audio_track = True           # the bed alone is an audio track when the shots had none
        # The binary comes from media_tools, not a bare name on PATH -- the one
        # resolution, shared with every other ffmpeg call in the app.
        cmd = [_media_tools.ffmpeg_path(), "-y"]
        for (path, _ci, _co, _ha, _cr, _m) in segs:
            cmd += ["-i", path]
        if need_silence:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        if bed_path is not None:
            cmd += ["-i", str(bed_path)]
        cmd += ["-filter_complex", fc, "-map", "[vout]"]
        if audio_track:
            cmd += ["-map", "[aout]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if audio_track:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [str(out_path)]
        export_warning = " ".join(x for x in (export_warning, bed_warning) if x)
        with _export_lock:
            _export_job.update(status="running", progress=0, elapsed=0.0, out="",
                               error="", warning=export_warning, proc=None, cancelled=False)
        threading.Thread(target=_run_export, args=(cmd, out_path, total_sec), daemon=True).start()
        # `audio` is a fact about the file that is about to be written, returned so a caller
        # can tell the owner the cut came out silent-by-necessity. NOT a claim that anything
        # renders it today: the Loom's export dialog reads `error` on the POST and then polls
        # export-status, so as of this change the durable record of a dropped track is the
        # server log warning above. Stated plainly rather than dressed up, because a comment
        # promising a notice that no client draws is how this file rots.
        return jsonify({"ok": True, "shots": len(segs), "audio": audio_track})

    @app.route("/api/loom/export-status")
    @tier(LOGIN)
    def api_loom_export_status():
        with _export_lock:
            return jsonify({k: _export_job[k] for k in
                            ("status", "progress", "elapsed", "out", "error", "warning")})

    @app.route("/api/loom/export-file")
    @tier(LOGIN)
    def api_loom_export_file():
        from moonglade.web_policy import harden_file_response
        name = _export_job.get("out") or "loom_cut.mp4"
        if not (_export_dir / name).exists():
            return "No export available.", 404
        return harden_file_response(
            send_from_directory(str(_export_dir), name, as_attachment=True,
                                download_name="moonglade-loom-cut.mp4"), name)

    @app.route("/api/loom/export-cancel", methods=["POST"])
    @tier(LOGIN)
    def api_loom_export_cancel():
        with _export_lock:
            proc = _export_job.get("proc")
            if _export_job["status"] == "running" and proc is not None:
                _export_job["cancelled"] = True
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        return jsonify({"ok": True})

    # Tier 2 of the two-tier project export: a self-contained zip carrying every media
    # file a project actually references, alongside the same {project, thumbs} JSON tier 1
    # already produces client-side (see exportJSON in master-storyboard.jsx). A real
    # PixAI media_id is globally issued, not locally scoped, so the bundle keeps it as-is
    # end to end -- no path-rewriting inside the project object, ever. On import, a media
    # id already resolvable on the receiving machine is simply skipped (both sides already
    # have it); one that isn't gets copied into imported/ and cataloged fresh. That also
    # makes re-importing the same bundle twice a no-op the second time.
    _BUNDLE_VIDEO_EXTS = _scan._VIDEO_EXTS   # THE video extension set, not a fourth copy of it.
    # It used to be a re-typed literal here, because the set lived in backup.py and
    # backup.py imports this file, so a module-level import back the other way is a
    # cycle. The 2026-08-23 library-scan collapse moved the set into THIS module's
    # LIBRARY SCAN section (it is the `"video"` kind), which is what backup.py now
    # imports -- so the reason for the copy is gone along with the copy.

    _LOOM_PENDING_KEYS = ("pendingTaskId", "pendingSubmitId", "pendingSettings", "pendingAnchor",
                          "pendingBoard", "pendingQuote", "genStartedAt", "supersededTasks")

    def _loom_strip_in_flight(project):
        """Python twin of loom-takes-core.js's stripInFlight: a copied board carries no render
        in flight. A shot that was rendering is settled -- done with a selected take, error
        without one."""
        if not isinstance(project, dict):
            return project
        for act in (project.get("acts") or []):
            for c in ((act or {}).get("cards") or []):
                if not isinstance(c, dict):
                    continue
                busy = any(c.get(k) for k in _LOOM_PENDING_KEYS) or c.get("status") == "wip"
                if not busy:
                    continue
                for k in _LOOM_PENDING_KEYS:
                    c.pop(k, None)
                if c.get("status") == "wip":
                    c["status"] = "done" if c.get("resultMid") else "error"
        return project

    def _loom_collect_media_ids(project):
        """Every real (catalog) media_id a project references -- resultMid, both frame
        slots, and every cast/asset entry -- mapped to WHERE each one was referenced from.
        thumbId references are NOT collected: they're client-only (base64 in `thumbs`) and
        already travel inside project.json as-is.

        Returns an insertion-ordered {media_id: [label, ...]} dict rather than the bare set
        this used to return, for two reasons. The labels are the whole difference between a
        useful missing-media report and the one export-bundle used to produce: "2 files are
        missing" with no way to tell which shot they belonged to left the owner hand-diffing
        every reference in the project against the zip's media/ folder. And insertion order
        makes the zip's media/ entries -- and the missing list -- come out identical twice
        for the same project, instead of following whatever order set hashing happened to
        pick that run. Callers that only want the ids still just iterate the dict.

        The labels mirror the Loom's own `A·01` shot codes (loom-core.js's actLetter +
        1-based card number) on purpose: a code in this report has to be one the owner can
        find on screen without translating it."""
        ids = {}

        def _note(mid, where):
            ids.setdefault(str(mid), []).append(where)

        for ai, act in enumerate(project.get("acts") or []):
            letter = chr(65 + ai) if ai < 26 else "A%d" % ai   # matches actLetter()'s wrap
            for ci, c in enumerate(act.get("cards") or []):
                code = "%s·%02d" % (letter, ci + 1)
                title = (c.get("title") or "").strip()
                code = "%s %s" % (code, title) if title else code
                if c.get("resultMid"):
                    _note(c["resultMid"], "%s (shot result)" % code)
                # Session P (review F17): every take's clip travels, not only the selected
                # one -- a restored board must be able to ★ any of them. Mirrors takesOf():
                # the stored takes; resultMid above covers the derived/legacy take.
                for t in (c.get("takes") if isinstance(c.get("takes"), list) else []):
                    tm = str((t or {}).get("mid") or "")
                    if tm and tm != str(c.get("resultMid") or ""):
                        _note(tm, "%s (take %s)" % (code, (t or {}).get("n")))
                for slot in ("openFrame", "closeFrame"):
                    f = c.get(slot) or {}
                    if f.get("mediaId"):
                        _note(f["mediaId"], "%s (%s)" % (code, slot))
        for a in (project.get("assets") or []):
            if a.get("mediaId"):
                who = (a.get("name") or a.get("tag") or a.get("id") or "?")
                _note(a["mediaId"], "cast/asset %s" % who)
        return ids

    def _loom_resolve_media(mid):
        """A project can reference either an image OR a video by media_id (a shot's
        resultMid is very often a video), but find_files_for_media_id only ever sees
        images by design. Same fallback /api/loom/export already uses for exactly this
        reason: catalog row -> is_video + filename -> out_dir/filename. Returns a Path
        or None."""
        from moonglade.catalog import get_row
        paths = _scan.find_files_for_media_id(out_dir, mid)
        if paths:
            return paths[0]
        row = get_row(db_path, mid)
        if row and str(row.get("is_video") or "") == "1" and row.get("filename"):
            p = out_dir / row["filename"]
            if p.exists():
                return p
        return None

    # Cap on the X-Bundle-Missing value. Nothing in HTTP bounds a header value, but every
    # mainstream server and proxy caps the header BLOCK (nginx/Apache land around 8 KB, and
    # the limit is on the whole block, not this one line), so a header that grows with the
    # project is how you get a bundle that downloads fine on the machine that built it and
    # is rejected by a proxy on the next one. ~900 bytes fits a few dozen ids with the rest
    # of the response's headers left comfortable.
    _BUNDLE_MISSING_HEADER_MAX = 900

    def _bundle_missing_header(missing):
        """The X-Bundle-Missing value: comma-separated, ASCII-only, length-capped media_ids.

        Filtered rather than trusted, because every id here came out of client-supplied
        project JSON: a value carrying CR/LF is header injection, and a non-latin-1 one makes
        Werkzeug raise while serialising the response -- turning a successful export into a
        500 for the owner. Ids that survive the filter but overflow the cap collapse into a
        trailing "+N more"; the complete list, with the act/shot each id came from, is in the
        zip's project.json regardless, which is why truncating here costs nothing."""
        safe = [s for s in (re.sub(r"[^A-Za-z0-9._-]", "", str(m["media_id"]))[:64]
                            for m in missing) if s]
        out, used = [], 0
        for i, mid in enumerate(safe):
            if used + len(mid) + 1 > _BUNDLE_MISSING_HEADER_MAX:
                out.append("+%d more" % (len(safe) - i))
                break
            out.append(mid)
            used += len(mid) + 1
        return ",".join(out)

    @app.route("/api/loom/export-bundle", methods=["POST"])
    @tier(LOGIN)
    def api_loom_export_bundle():
        """Full-bundle export: a zip of project.json (the lightweight Backup .json's
        {project, thumbs}, plus a `missing_media` manifest this tier alone can produce
        because only the server knows what's on disk) and every referenced media file under
        media/<id><ext>. Login required -- reads real files off disk, same trust level as
        /export-zip."""
        import io
        import zipfile
        body = request.get_json(silent=True) or {}
        project = body.get("project") or {}
        thumbs = body.get("thumbs") or {}
        if not project:
            return jsonify({"error": "no project given"}), 400
        mids = _loom_collect_media_ids(project)
        # Resolve everything BEFORE opening the archive so project.json can carry the missing
        # manifest and still be written first (a reader streaming the zip gets the project,
        # and the report about it, before megabytes of media).
        resolved, missing = [], []
        for mid in mids:
            p = _loom_resolve_media(mid)
            if p:
                resolved.append((mid, p))
            else:
                missing.append({"media_id": mid, "referenced_by": mids[mid]})
        # Session P (P3, ruling 8): the board's music bed travels as beds/<sha1>.<ext>, read
        # from the caller's own bed folder only (a name that does not resolve there is simply
        # reported missing -- never a path the client chose).
        bed = project.get("bed") if isinstance(project.get("bed"), dict) else None
        bed_path = None
        if bed and bed.get("file"):
            bed_path = _loom_bed_path(str(session.get("user") or ""), bed.get("file"))
            if bed_path is None:
                missing.append({"media_id": str(bed.get("file"))[:64], "referenced_by": ["music bed"]})
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
            z.writestr("project.json", json.dumps({"project": project, "thumbs": thumbs,
                                                   "missing_media": missing}))
            for mid, p in resolved:
                z.write(p, arcname="media/{}{}".format(mid, p.suffix.lower()))
            if bed_path is not None:
                z.write(str(bed_path), arcname="beds/" + bed_path.name)
        mem.seek(0)
        name = "{}_bundle.zip".format((project.get("name") or "loom_project").replace(" ", "_"))
        resp = send_file(mem, mimetype="application/zip", as_attachment=True, download_name=name)
        # Missing media doesn't fail the export (a partial bundle is still useful), so the
        # report has to reach the owner some other way. It goes to two places on purpose:
        #
        #   project.json's `missing_media` is the durable copy -- id plus the act/shot code
        #   each id was referenced from. It is IN the zip, so it survives the download, it
        #   travels to whoever the bundle is handed to, and it does not depend on a client
        #   noticing a response header at the moment of export. import-bundle ignores the key
        #   (it reads `project`/`thumbs`), so adding it costs the round trip nothing.
        #
        #   X-Bundle-Missing is the live copy, so the client can NAME what didn't travel
        #   instead of only counting it. This route shipped with the count alone under a
        #   comment claiming "the client surfaces this list" -- it could not; `missing` was
        #   discarded the moment len() was taken, and the owner was told "2 files are missing"
        #   with nowhere to look them up. X-Bundle-Missing-Count stays for the client that
        #   already reads it, and stays authoritative: it is the true total, while the header
        #   list may be truncated (see _bundle_missing_header).
        resp.headers["X-Bundle-Missing-Count"] = str(len(missing))
        hdr = _bundle_missing_header(missing)
        if hdr:
            resp.headers["X-Bundle-Missing"] = hdr
        return resp

    @app.route("/api/loom/import-bundle", methods=["POST"])
    @tier(LOGIN)
    def api_loom_import_bundle():
        """Accepts a full-bundle zip (see export-bundle), catalogs any media this machine
        doesn't already have (source='api' -- it's real PixAI media, just synced via the
        bundle instead of --update), and returns {project, thumbs} in the exact shape
        importJSON already expects, so both tiers share one client-side create-project path.
        Login required (any session, local or LAN)."""
        from moonglade.thumbs import make_thumbnail, make_video_thumbnail
        from moonglade.catalog import save_catalog_over_snapshot
        from moonglade.loom_files import (LOOM_BED_FILE_RE, LOOM_BED_MAX_BYTES,
                                          LOOM_BUNDLE_MAX_BEDS, LOOM_BUNDLE_MEDIA_MAX_BYTES,
                                          LOOM_BUNDLE_MEDIA_RE, _unlink_quiet, sniff_audio_ext)
        from moonglade.web_policy import (LOOM_BUNDLE_REQUEST_MAX_BYTES, REQUEST_MAX_BYTES,
                                          ZIP_MAX_MEMBERS, ZIP_MAX_TOTAL_BYTES,
                                          ZIP_TOO_MANY_MEMBERS)
        import io
        import time
        import zipfile

        # Finding 9: the upload is capped (LOOM_BUNDLE_REQUEST_MAX_BYTES) and read as the file
        # Werkzeug already spooled it to, never copied whole into memory; a bundle with more
        # than ZIP_MAX_MEMBERS entries is refused before anything is read out of it.
        request.max_content_length = LOOM_BUNDLE_REQUEST_MAX_BYTES
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        try:
            z = zipfile.ZipFile(f.stream)
        except Exception:
            return jsonify({"error": "not a valid bundle (couldn't read project.json)"}), 400
        if len(z.infolist()) > ZIP_MAX_MEMBERS:
            return jsonify({"error": ZIP_TOO_MANY_MEMBERS}), 413
        try:
            info = z.getinfo("project.json")
            if info.file_size > REQUEST_MAX_BYTES:
                raise ValueError("project.json too large")
            with z.open(info) as pj:
                raw = pj.read(REQUEST_MAX_BYTES + 1)
            if len(raw) > REQUEST_MAX_BYTES:
                raise ValueError("project.json too large")
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return jsonify({"error": "not a valid bundle (couldn't read project.json)"}), 400
        project = data.get("project")
        if not project:
            return jsonify({"error": "bundle's project.json has no project"}), 400
        imported_dir = out_dir / "imported"
        # The carry map for this bundle's media, read ONCE (issue #19). The
        # _loom_resolve_media guard below does NOT establish that a media_id is absent from
        # the catalog -- it only asks whether a FILE resolves (find_files_for_media_id, or
        # a video row whose filename exists on disk). A row whose file is gone is normal,
        # supported state: reconcile_catalog_with_disk leaves it intact by design, so a
        # media_id quarantined by --dedup or deleted by hand still carries its rating,
        # title, collections, artwork_id and published state. Without `known`, importing a
        # bundle that references such a media_id would write the file AND blank every one
        # of those columns through save_catalog's full-row upsert -- exactly the 2026-09-03
        # data loss. The file is still written (the bytes really are missing here); the row
        # keeps what the user owns.
        media_entries = [m for m in (LOOM_BUNDLE_MEDIA_RE.match(n) for n in z.namelist()) if m]
        known = _full_meta.known_catalog_rows(db_path, [m.group(1) for m in media_entries])
        rows = []
        # Session P (P3, review F19): a bundle's music bed is RE-HASHED on arrival and stored
        # under the name its own bytes give it, in the caller's bed folder -- never under the
        # name inside the zip, which could point anywhere or claim another bed's hash. The
        # board is then pointed at the computed name. Not audio, or over the cap: skipped.
        # Spend review S5: ONLY the bed the imported board names is read and stored -- a board
        # has one bed, so a bundle stores at most one file of at most LOOM_BED_MAX_BYTES. Every
        # other beds/ entry is skipped unread: before, each one was stored, so a small bundle
        # of highly compressible "audio" could fill the disk with files nothing referenced.
        import tempfile
        user = str(session.get("user") or "")
        bed_names = {}
        pbed0 = project.get("bed") if isinstance(project, dict) else None
        wanted = str((pbed0 or {}).get("file") or "") if isinstance(pbed0, dict) else ""
        wanted_entries = (["beds/" + wanted] if LOOM_BED_FILE_RE.match(wanted) else [])[:LOOM_BUNDLE_MAX_BEDS]
        present = set(z.namelist())
        for name in wanted_entries:
            if name not in present:
                continue
            try:
                info = z.getinfo(name)
                if info.file_size > LOOM_BED_MAX_BYTES or not user:
                    continue
                d = _loom_beds_dir(user)
                d.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=".import-", suffix=".part", dir=str(d))
                total, head = 0, b""
                with os.fdopen(fd, "wb") as out, z.open(info) as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        total += len(chunk)
                        if total > LOOM_BED_MAX_BYTES:
                            break
                        if len(head) < 64:
                            head = (head + chunk)[:64]
                        out.write(chunk)
                ext = sniff_audio_ext(head)
                if total == 0 or total > LOOM_BED_MAX_BYTES or ext is None:
                    _unlink_quiet(tmp)
                    continue
                bed_names[name[len("beds/"):]] = _loom_store_bed(user, tmp, ext)
            except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
                continue
        pbed = project.get("bed") if isinstance(project, dict) else None
        if isinstance(pbed, dict):
            got = bed_names.get(str(pbed.get("file") or ""))
            if got:
                project["bed"] = dict(pbed, file=got)
            elif not LOOM_BED_FILE_RE.match(str(pbed.get("file") or "")):
                project.pop("bed", None)          # a bed naming no storable file is no bed
        bundle_written = 0                 # bytes this import has unpacked (ZIP_MAX_TOTAL_BYTES)
        for m in media_entries:
            name, mid, ext = m.group(0), m.group(1), "." + m.group(2)
            if _loom_resolve_media(mid):
                continue  # already have it -- both sides share this media, nothing to do
            imported_dir.mkdir(parents=True, exist_ok=True)
            dest = imported_dir / "{}{}".format(mid, ext)
            if not _scan._is_under(dest.resolve(), imported_dir.resolve()):
                continue
            # Streamed under a cap into a temp file, then moved into place: a huge or
            # truncated entry never leaves a partial picture behind (Invariant 3).
            part = dest.with_name(dest.name + ".part")
            try:
                total = 0
                with open(part, "wb") as out, z.open(name) as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        total += len(chunk)
                        if total > LOOM_BUNDLE_MEDIA_MAX_BYTES or \
                                bundle_written + total > ZIP_MAX_TOTAL_BYTES:
                            break
                        out.write(chunk)
                if bundle_written + total > ZIP_MAX_TOTAL_BYTES:
                    _unlink_quiet(part)        # the whole bundle's budget is spent (finding 9):
                    break                      # nothing more is unpacked from it
                if total == 0 or total > LOOM_BUNDLE_MEDIA_MAX_BYTES:
                    _unlink_quiet(part)
                    continue
                bundle_written += total
                os.replace(part, dest)
            except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
                _unlink_quiet(part)
                continue
            is_vid = ext in _BUNDLE_VIDEO_EXTS
            thumb_path = thumb_dir / "{}.jpg".format(mid)
            if is_vid:
                make_video_thumbnail(dest, thumb_path)  # best-effort; --rebuild-thumbs backfills
            else:
                make_thumbnail(dest, thumb_path)
            # Same shared row-builder every capture path uses (issue #19): a bundle
            # import is run_import_local's shape -- a file, no task, so no `fm` and no
            # generation surface, but WITH `known` (see above -- a missing file does not
            # mean a missing row). created_at stays this route's own naive local stamp,
            # NOT _created_at_utc's UTC+Z -- see that helper for why the two sort
            # differently.
            rows.append(_full_meta.build_catalog_row(
                mid, known=known,
                filename=str(dest.relative_to(out_dir)).replace("\\", "/"),
                source="api", status="imported",
                created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                prompt_preview=dest.stem[:100], is_video="1" if is_vid else ""))
        if rows:
            save_catalog_over_snapshot(db_path, rows, known)
        # Session P (review F4/F17): a board exported mid-render never imports with that
        # render's markers -- the render belongs to the original. The client strips too
        # (stripInFlight); this makes the bundle's own answer honest on its way out.
        project = _loom_strip_in_flight(project)
        return jsonify({"project": project, "thumbs": data.get("thumbs") or {},
                        "media_added": len(rows)})

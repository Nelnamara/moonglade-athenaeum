"""moonglade/routes_library.py -- the library's routes: rating, the poster rebuild, prompt edits,
collections (add, detail, manage, order), curation and its restore, prompt replace, thumbnails,
the video file, the full image, the ZIP export, the model search and version, a task's and a video
task's parameters, image meta, the gallery listing, similar, the contact sheet, duplicates (list,
resolve, undo), and the app's three data routes (/api/library, /api/detail, /api/history), with
the app-bound _find_local_video_file and _loom_complete_clip the Loom and the spend routes read.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the first block was, after the delete and recipe routes it reads
(_batch_sibling_count; _recipes, _recipe_user_id, _read_only_flag). Names the block reads from
create_app's setup and the front door come in through ctx (the bound-from-ctx lines below), so
every closure on both sides holds the one same object. gallery's own names are imported inside the
function that reads them, at call time, so a test's patch of moonglade.gallery still reaches the
route.
"""
import json
import os
import re
import time

from flask import jsonify, redirect, request, send_file, send_from_directory, session

from moonglade import dupes as _dupes
from moonglade import jobs as _jobs
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import organize as _organize
from moonglade import pixai_client as _pixai_client
from moonglade import scan as _scan
from moonglade import series as _series
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _batch_sibling_count = ctx._batch_sibling_count
    _check_csrf = ctx._check_csrf
    _csp_nonce = ctx._csp_nonce
    _gen_session = ctx._gen_session
    _is_local_request = ctx._is_local_request
    _read_only_flag = ctx._read_only_flag
    _recipe_user_id = ctx._recipe_user_id
    _recipes = ctx._recipes
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    thumb_dir = ctx.thumb_dir
    # -- end --

    @app.route("/api/rate/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def rate(media_id):
        from moonglade.gallery import update_rating
        data = request.get_json(silent=True) or {}
        try:
            value = max(0, min(5, int(data.get("rating", 0))))
        except (TypeError, ValueError):
            return json.dumps({"ok": False}), 400, {"Content-Type": "application/json"}
        update_rating(db_path, media_id, value)
        # Lamplighter (curation_streak) + The Long Vigil (active_days): rating a piece --
        # including clearing it to 0 -- is curation. Keyed day-lists, idempotent, silent-soft.
        try:
            _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
        except Exception:
            pass
        return json.dumps({"ok": True, "rating": value}), 200, {"Content-Type": "application/json"}

    @app.route("/api/rebuild-poster/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def rebuild_poster(media_id):
        """Regenerate ONE video's poster thumbnail from its file, replacing the cached
        one. For a clip whose cached poster is wrong -- e.g. a fade-in that was
        thumbnailed inside the fade before the representative-frame pick shipped
        (owner, 2026-08-22) -- without a whole --rebuild-thumbs pass. LOGIN tier like
        /api/rate: it only rewrites a regenerable local cache file, touches nothing on
        PixAI and no config. Videos only; an image's thumb is a straight resize and
        never wrong in this way."""
        from moonglade.gallery import Path, get_row, make_video_thumbnail
        if not media_id or "/" in media_id or "\\" in media_id or ".." in media_id:
            return json.dumps({"ok": False, "error": "bad id"}), 400, {"Content-Type": "application/json"}
        row = get_row(db_path, media_id)
        if not row:
            return json.dumps({"ok": False, "error": "not in the catalog"}), 404, {"Content-Type": "application/json"}
        if str(row.get("is_video") or "") != "1":
            return json.dumps({"ok": False, "error": "not a video"}), 400, {"Content-Type": "application/json"}
        # The catalog row's filename is canonical; the matcher is the fallback if the
        # file moved (and it must be told to look for VIDEO extensions -- its default
        # set is images only).
        src = out_dir / str(row.get("filename") or "")
        if not (row.get("filename") and src.is_file()):
            from moonglade import backup as core   # lazy, like every other gallery use of it
            files = _scan.find_files_for_media_id(out_dir, media_id, exts=core._VIDEO_EXTS)
            if not files:
                return json.dumps({"ok": False, "error": "video file not found"}), 404, {"Content-Type": "application/json"}
            src = Path(files[0])
        thumb = out_dir / "gallery" / "thumbs" / (media_id + ".jpg")
        ok = make_video_thumbnail(src, thumb)
        if not ok:
            return json.dumps({"ok": False, "error": "ffmpeg extract failed (is ffmpeg on PATH?)"}), 200, {"Content-Type": "application/json"}
        return json.dumps({"ok": True, "thumb": "/thumbs/" + media_id + ".jpg?v=" + str(int(time.time()))}), 200, {"Content-Type": "application/json"}

    @app.route("/api/edit-prompt/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def edit_prompt(media_id):
        from moonglade.gallery import update_prompt_full
        data = request.get_json(silent=True) or {}
        update_prompt_full(db_path, media_id, data.get("prompt", ""))
        return json.dumps({"ok": True}), 200, {"Content-Type": "application/json"}

    @app.route("/api/collection", methods=["POST"])
    @tier(LOGIN)
    def api_collection():
        """JSON twin of /collection-add + /collection-remove for fetch()-driven
        clients: one route, `action` picks the direction, same add_to_collection /
        remove_from_collection helpers underneath (comma-name scrubbing, the
        read-modify-write lock, no-op-if-already-there counting -- all of it), no
        redirect banner. LOGIN tier, exactly like both page routes it mirrors.
        `count` is rows actually CHANGED, the page banner's own number -- adding to
        a collection an image is already in counts zero, not one."""
        from moonglade.gallery import (CurationError, _is_smart_name, add_to_collection,
                                       remove_from_collection)
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip()
        if action not in ("add", "remove"):
            return jsonify({"error": "action must be 'add' or 'remove'"}), 400
        name = str(body.get("collection") or "").strip()
        if not name:
            return jsonify({"error": "no collection name given"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        if action == "remove" and _is_smart_name(db_path, name):
            return jsonify({"error": "“{}” is a smart collection, a saved search. Pictures "
                                     "leave it by no longer matching.".format(name)}), 400
        fn = add_to_collection if action == "add" else remove_from_collection
        try:
            return jsonify({"ok": True, "count": fn(db_path, media_ids, name)})
        except CurationError as e:        # adding to a smart collection (N1)
            return jsonify({"error": str(e)}), 400

    # ------------------------------------------------------------------------------------
    # CURATION (Session N). Local catalog only: none of these routes touches PixAI, and none
    # can delete a picture or a file. Every POST checks the session's CSRF token (the token
    # rides in the body, as for the Panel's account routes).
    # ------------------------------------------------------------------------------------
    @app.route("/api/collections/detail")
    @tier(LOGIN)
    def api_collections_detail():
        """Every collection, hand-picked and smart, with its count and cover -- what the
        collections list and the manager draw. Read-only; a smart collection's count is its
        saved query run now."""
        from moonglade.gallery import collection_summaries
        return jsonify({"collections": collection_summaries(db_path)})

    @app.route("/api/collections/manage", methods=["POST"])
    @tier(LOGIN)
    def api_collections_manage():
        """The collections manager's writes and Save-as-smart, one route, `action` picks:
        rename {name, new_name} · merge {names: [target, ...others]} · delete {name} ·
        smart {query, name?, replace?}. Labels and saved queries only -- a delete or a merge
        never removes a picture. A refusal is a 400 with the reason in words."""
        from moonglade.gallery import (CurationError, delete_collection, merge_collections,
                                       rename_collection, save_smart_collection)
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        action = str(body.get("action") or "").strip()
        try:
            if action == "rename":
                res = rename_collection(db_path, body.get("name"), body.get("new_name"))
            elif action == "merge":
                names = body.get("names")
                res = merge_collections(db_path, names if isinstance(names, list) else [])
            elif action == "delete":
                res = delete_collection(db_path, body.get("name"))
            elif action == "smart":
                res = save_smart_collection(db_path, body.get("query"),
                                            name=body.get("name") or "",
                                            replace=str(body.get("replace") or "").strip())
            else:
                return jsonify({"error": "action must be rename, merge, delete or smart"}), 400
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    # ---- MANUAL ORDER (Session P, P6) -------------------------------------------------------
    # A hand-picked collection's order: read by the order editor, the collection view's
    # "Manual" sort, the Contact sheet and "as shots, in order". Local catalog only, never
    # PixAI; the write is one transaction and needs the session's CSRF token.
    @app.route("/api/collections/order", methods=["GET"])
    @tier(LOGIN)
    def api_collections_order_get():
        """{name, kind, media_ids, manual} -- the collection's members in its order
        (ordered_members). Read-only: opening the editor writes nothing."""
        from moonglade.gallery import ordered_members
        name = (request.args.get("name") or "").strip()
        res = ordered_members(db_path, name)
        if res["kind"] is None:
            return jsonify(dict(res, error="There is no collection called “{}”.".format(name))), 404
        return jsonify(res)

    @app.route("/api/collections/order", methods=["POST"])
    @tier(LOGIN)
    def api_collections_order_set():
        """{csrf, name, media_ids} -> the saved order (ordered_members after). A smart
        collection, an unknown one and any id that is not a member are refused (400)."""
        from moonglade.gallery import CurationError, set_collection_order
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        ids = body.get("media_ids")
        try:
            res = set_collection_order(db_path, body.get("name"), ids if isinstance(ids, list) else [])
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    @app.route("/api/curate", methods=["POST"])
    @tier(LOGIN)
    def api_curate():
        """Bulk (or single) curation: {media_ids, op} with op one of {rating: 0-5} ·
        {mark: keeper|reject|""} · {add_tag} · {remove_tag} · {note}. Answers what really
        changed -- `changed` counts pictures whose values differ afterwards, `prev` / `after`
        carry each changed picture's full state -- so the client can show an honest count and
        an Undo that restores each picture's OWN previous values (POST /api/curate/restore).
        Tags, marks and notes live in the local catalog and are never sent to PixAI."""
        from moonglade.gallery import CurationError, curate_apply
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        try:
            res = curate_apply(db_path, body.get("media_ids"), body.get("op"))
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        if res["changed"] and isinstance(body.get("op"), dict) and "rating" in body["op"]:
            # Rating is curation whichever door it came through (see /api/rate).
            try:
                _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
            except Exception:
                pass
        return jsonify(dict(res, ok=True))

    @app.route("/api/curate/restore", methods=["POST"])
    @tier(LOGIN)
    def api_curate_restore():
        """Undo for /api/curate: {prev: {media_id: {rating, mark, tags, note}}} -- exactly
        the `prev` map that call returned. Puts each picture back to its own previous
        values; a request with any invalid entry changes nothing."""
        from moonglade.gallery import CurationError, curate_restore
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        try:
            res = curate_restore(db_path, body.get("prev"))
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    @app.route("/api/replace-prompts", methods=["POST"])
    @tier(LOGIN)
    def api_replace_prompts():
        """JSON twin of /bulk-replace-prompt: same bulk_replace_prompt helper (plain
        substring find/replace over prompt_full, counting only rows that actually
        changed), no redirect banner. LOGIN tier, like the page route it mirrors.
        An empty `find` is a 400 here rather than the helper's silent 0: the page
        form can't submit one, so a JSON caller sending one is a bug worth naming."""
        from moonglade.gallery import bulk_replace_prompt
        body = request.get_json(silent=True) or {}
        find = str(body.get("find") or "")
        if not find:
            return jsonify({"error": "no find text given"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        changed = bulk_replace_prompt(db_path, media_ids, find,
                                      str(body.get("replace") or ""))
        return jsonify({"ok": True, "changed": changed})

    # Full images are write-once: /img/ is keyed by on-disk path and /full/ resolves to
    # the downloaded original, so the bytes behind a given URL never change. Cache those
    # forever -- pagination, back-navigation, and re-visits cost zero re-download, the
    # single biggest win on mobile / LAN.
    _IMMUTABLE = "public, max-age=31536000, immutable"

    # Thumbnails are NOT immutable, despite being keyed by media_id: `--rebuild-thumbs`
    # regenerates them IN PLACE at the same key (that is its whole job -- repairing
    # posters that ffmpeg missed). media_id is an identity, not a content hash, so an
    # `immutable` year-long cache pins the broken poster it was meant to fix. Short
    # max-age + the ETag send_from_directory already sets = a 304 on the common path.
    _THUMB_CACHE = "public, max-age=300"

    # The Sibling Strip's 32px tier (issue #30): derived from the EXISTING 768 thumb
    # (never the master), cached beside the badge cache under gallery/cache/_strip/
    # (badge_cache_dir()'s rule: regenerable caches live as siblings there, never in
    # the goods tree). Self-heals when the 768 thumb is newer (mtime) -- a rebuilt
    # poster re-cuts its strip thumb on the next request. Browser cache matches the
    # 768 thumb's own 300s policy (the block above): the strip URL carries NO ?v=, and
    # a rebuilt poster must not show its old tile for a day (adversarial review, 2026-08-22).
    _STRIP_CACHE = _THUMB_CACHE   # same 300s as the 768: media_id is an identity, not a hash
    _STRIP_ID_OK = re.compile(r"[0-9A-Za-z_-]+")

    # The allowlist of derived thumb sizes, ?s=<key> -> (longest side in px, cache folder).
    # 32 is the Sibling Strip's; 256 is the phone's Data saver tier (Session Q, Q7): the
    # same derive-from-the-768, cache-beside-the-badges, self-healing shape, additive and
    # read-only -- an unlisted key still answers the plain 768 thumb.
    _THUMB_TIERS = {"32": (32, "_strip"), "256": (256, "_t256")}

    def _sized_thumb(media_id, key):
        """Path of the cached derived thumb (`key` names a tier in _THUMB_TIERS) for
        media_id, (re)cut from the 768 thumb when missing or stale. None when there is
        no 768 thumb to derive from or the cut fails -- the caller then falls through
        to the normal thumb."""
        side, folder = _THUMB_TIERS[key]
        # ALLOWLIST the id here, inside the helper, so every caller is covered. A
        # denylist of / \ .. missed the Windows drive letter: pathlib's `/` RESETS to
        # a drive-relative path when the right operand carries one, so
        # thumb_dir / "C:x.jpg" == Path("C:x.jpg") == the drive ROOT -- and
        # send_from_directory would then serve C:\x.jpg (adversarial review,
        # 2026-08-22). Catalog ids are numeric (or local_<hex>); nothing else is valid.
        if not _STRIP_ID_OK.fullmatch(media_id or ""):
            return None
        src = thumb_dir / (media_id + ".jpg")
        if not src.is_file():
            return None
        dst = out_dir / "gallery" / "cache" / folder / (media_id + ".jpg")
        try:
            src_mtime = src.stat().st_mtime
            if dst.is_file() and dst.stat().st_mtime >= src_mtime:
                return dst
            from PIL import Image
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Atomic: cut to a temp file and os.replace it in. An in-place save that died
            # mid-write (disk full, kill) left a truncated file carrying a FRESH mtime,
            # which then passed the staleness check and was served for the whole
            # cache window; a concurrent reader (4 siblings render the same URL at once
            # on a threaded server) could also read a half-written file.
            tmp = dst.with_suffix(".tmp")
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    im.thumbnail((side, side))
                    im.save(tmp, "JPEG", quality=80)
                os.replace(tmp, dst)
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            return dst
        except Exception:
            return None

    @app.route("/thumbs/<media_id>.jpg")
    @tier(LOGIN)
    def thumb(media_id):
        # ?s= is an allowlist (_THUMB_TIERS: 32 and 256); anything else is the 768 thumb.
        from moonglade.gallery import Path, find_image_file, get_row, harden_file_response
        size_key = request.args.get("s") or ""
        if size_key in _THUMB_TIERS and "/" not in media_id \
                and "\\" not in media_id and ".." not in media_id:
            p = _sized_thumb(media_id, size_key)
            if p is not None:
                resp = send_from_directory(str(p.parent), p.name, max_age=86400,
                                           mimetype="image/jpeg")
                resp.headers["Cache-Control"] = _STRIP_CACHE
                return harden_file_response(resp, p.name)
        # An SVG has no server thumbnail by design (DESIGN_3.22 5.3): every grid, picker and
        # viewer builds /thumbs/<id>.jpg, so for an SVG row this route points the <img> (or CSS
        # background-image) at the library file route instead, which already serves it under
        # the 5.4 headers. A redirect, never the SVG's text inlined or a different element.
        if "/" not in media_id and "\\" not in media_id and ".." not in media_id \
                and not (Path(str(thumb_dir)) / "{}.jpg".format(media_id)).exists():
            row = get_row(db_path, media_id)
            sp = find_image_file(out_dir, media_id, row.get("filename") if row else "")
            if sp and str(sp).lower().endswith(".svg"):
                return redirect("/full/{}".format(media_id))
        resp = send_from_directory(str(thumb_dir), "{}.jpg".format(media_id),
                                   max_age=300, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = _THUMB_CACHE
        return harden_file_response(resp, "{}.jpg".format(media_id))

    @app.route("/video-file/<media_id>")
    @tier(LOGIN)
    def video_file(media_id):
        from moonglade.gallery import get_row, harden_file_response, media_type_for
        row = get_row(db_path, media_id)
        if not row or row.get("is_video") != "1":
            return "Video not found.", 404
        # Resolved through _find_local_video_file -- the SAME question the detail page asks
        # before it decides to draw a player at all. This route used to answer a narrower
        # one: it served `row["filename"]` and 404'd if that column was blank (an older row,
        # or one written before the download settled on a name) or stale (`--organize` moved
        # the clip, a re-download landed it under a different name). detail() has the
        # media-id fallback and this did not, so the two could disagree -- and when they
        # disagree the page renders <video><source> over a 404, which is a dead black box
        # with no message: M30's exact symptom, surviving on top of M30's own fix. An
        # existence check is only worth having if it is answered by whatever will serve the
        # bytes, so there is one resolver and both callers ask it.
        p = _find_local_video_file(media_id, row=row)
        if p is None:
            return "Video not found.", 404
        try:
            rel = str(p.relative_to(out_dir)).replace("\\", "/")
        except ValueError:
            # Only reachable if a catalog `filename` escaped the backup folder (an absolute
            # path, or one with ..). send_from_directory would refuse it below anyway; doing
            # it here keeps "found" meaning the same thing to the resolver and to the serve.
            return "Video not found.", 404
        # send_from_directory supports HTTP Range, so the <video> can seek
        resp = send_from_directory(str(out_dir), rel, max_age=31536000,
                                   mimetype=media_type_for(p.name))
        resp.headers["Cache-Control"] = _IMMUTABLE
        return harden_file_response(resp, p.name)

    @app.route("/full/<media_id>")
    @tier(LOGIN)
    def full_image(media_id):
        # Resolve a media_id to its full-res file on the fly (used by the
        # lightbox so the index page doesn't precompute 250 image paths).
        from moonglade.gallery import find_image_file, get_row, harden_file_response, media_type_for
        row = get_row(db_path, media_id)
        p = find_image_file(out_dir, media_id, row.get("filename") if row else "")
        if not p or not p.exists():
            return "Not found", 404
        # ?dl=1 -> force a SAVE with the real filename (the detail page's plain Download);
        # without it, inline (the lightbox displays the image). Same file either way.
        # A type that is not a raster picture (an SVG from Edit Pro) is a download either
        # way: harden_file_response never lets it open as a page on this origin.
        dl = bool(request.args.get("dl"))
        resp = send_from_directory(str(p.parent), p.name, max_age=31536000,
                                   mimetype=media_type_for(p.name),
                                   as_attachment=dl, download_name=(p.name if dl else None))
        resp.headers["Cache-Control"] = _IMMUTABLE
        return harden_file_response(resp, p.name)

    @app.route("/export-zip", methods=["POST"])
    @tier(LOGIN)
    def export_zip():
        # Stream a ZIP of the selected files. Default is STORED (no recompression) --
        # they're already compressed. Optional export-time transforms: convert to
        # PNG/JPEG (`fmt`) and/or embed prompt+ids into the file (`embed`). Both run on a
        # COPY in a temp dir and are discarded after zipping -- the catalog and the
        # originals on disk are NEVER touched, and a converted file never re-enters the
        # catalog as a new row (the decided shape; the archive stays exactly as PixAI
        # delivered it). Videos are always passed through as-is (Pillow can't transform mp4).
        from moonglade.gallery import Path, find_image_file, get_row, query_catalog
        import io
        import zipfile
        import shutil
        import tempfile
        from moonglade import backup as core
        # Two entry points: a curated SELECTION (media_ids from the grid) or a whole
        # COLLECTION by name. For a collection we resolve its FULL membership here in SQL
        # (up to the same 2000 cap) rather than trusting the rendered checkboxes -- "download
        # this collection" must mean every item in it, even across pages the grid never
        # loaded. There is no "zip the entire catalog" path: absent both, ids is empty -> 404.
        coll = (request.form.get("collection") or "").strip()
        if coll:
            rows_c, _ = query_catalog(db_path, collection=coll, page=1, page_size=2000)
            ids = [r["media_id"] for r in rows_c]
        else:
            ids = request.form.getlist("media_ids")
        fmt = (request.form.get("fmt") or "original").lower()
        if fmt not in ("original", "png", "jpeg"):
            fmt = "original"
        embed = (request.form.get("embed") or "") in ("1", "true", "on", "yes")
        transforming = (fmt != "original") or embed
        tmp = tempfile.mkdtemp(prefix="mg_export_") if transforming else None
        mem = io.BytesIO()
        n = 0
        # convert_image()/embed_metadata() never raise -- they report failure via a
        # returned/discarded status NOTE and quietly hand back the untouched original. That
        # note used to be thrown away (convert's into `_note`, embed's not even captured),
        # so "export as JPEG + embed prompt" could silently ship untouched originals with
        # zero signal anywhere. This is a plain form POST -> file-download response (see
        # doExportDownload() in the page's own JS): there's no fetch/JSON leg for a status
        # message to ride, so the only channel that survives the download is a small report
        # INSIDE the zip itself, added only when something actually needed reporting.
        warnings = []
        try:
            with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
                seen_names = set()
                for mid in ids[:2000]:  # safety cap
                    row = get_row(db_path, mid)
                    if not row:
                        continue
                    p = find_image_file(out_dir, mid, row.get("filename"))
                    if not p or not p.exists():
                        continue
                    src = p
                    if tmp and not row.get("is_video"):
                        # Transform a COPY only -- never the original file.
                        work = Path(tmp) / p.name
                        try:
                            shutil.copy2(p, work)
                            if fmt != "original":
                                work, note = core.convert_image(work, fmt, keep_original=False)
                                if note not in ("ok", "already"):
                                    warnings.append("{}: convert to {} -> {} (shipped as-is)"
                                                     .format(p.name, fmt, note))
                            if embed:
                                enote = core.embed_metadata(work, {
                                    "prompt": row.get("prompt_full") or row.get("prompt") or "",
                                    "media_id": mid, "task_id": row.get("task_id") or "",
                                    "model": row.get("model_name") or row.get("model_id") or "",
                                    "seed": row.get("seed") or "",
                                    "date": row.get("created_at") or ""})
                                if enote != "ok":
                                    warnings.append("{}: embed prompt -> {} (not embedded)"
                                                     .format(p.name, enote))
                            src = work
                        except Exception as e:
                            src = p        # any transform failure -> ship the original untouched
                            warnings.append("{}: transform failed ({}) -- shipped the original"
                                             .format(p.name, _redact_host_paths(str(e))[:120]))
                    name = src.name
                    if name in seen_names:
                        name = "{}_{}".format(mid, src.name)
                    seen_names.add(name)
                    z.write(src, arcname=name)
                    n += 1
                if warnings:
                    report = ("Some files in this export did not convert and/or embed the prompt "
                               "as requested -- they were shipped as their original file instead:\n\n"
                               + "\n".join(warnings) + "\n")
                    z.writestr("_export_warnings.txt", report)
            if not n:
                return "No matching images found.", 404
            mem.seek(0)
            resp = send_file(mem, mimetype="application/zip", as_attachment=True,
                             download_name="moonglade_selection_{}.zip".format(n))
            if warnings:
                resp.headers["X-Export-Warnings"] = str(len(warnings))
            return resp
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)   # bytes are already in `mem`

    @app.route("/api/model-search")
    @tier(LOGIN)
    def api_model_search():
        """Search PixAI models/LoRAs for the picker grid. Read-only, owner's key. Login required
        (any session, local or LAN).
        ?q=&kind=base|lora&size=N&cursor=&category=&sort=popular|newest&base_type=.

        Three data sources by design: REST /search (base models' default) has RICH rows
        (description / refCount / official badge) but silently ignores market filters AND
        has no per-row architecture field; the GraphQL `generationModels` connection honors
        category + a Newest sort AND (picker-parity-round2, 2026-07-24) carries
        modelType/loraBaseModelType per row too. LoRA search (kind=lora) ALWAYS uses GraphQL
        now, regardless of category/sort -- architecture-aware compat sort/badging
        (base_type=) needs that per-row data on every LoRA search, not just the
        category/Newest subset, and REST's oRPC endpoint has no equivalent field to request
        it from (confirmed by inspecting its full response shape -- see
        the 2026-07-21 audit). Base-model search is UNCHANGED (REST by default, GraphQL
        only for category/Newest) -- architecture filtering is a LoRA-picker concept only,
        base models don't get compat-sorted against anything.

        cursor= (owner report 2026-07-24: the picker "scrolls a few rows and stops -- no
        continuous scroll"): an OPAQUE token from a previous response's `next_cursor` --
        the client just echoes it back with no idea which search path is serving it; THIS
        route decides what it means for the CURRENT request. On the GraphQL path it's the
        real Relay endCursor, passed straight through as `after=`. On the REST path (which
        has no cursor concept, only a raw int offset) it's a base-10 offset string, parsed
        here and passed as `offset=`; the response's own `next_cursor` is then computed as
        offset+size so the next request stays a plain opaque round-trip either way. Always
        '' when the underlying `has_more` is false, regardless of what math would otherwise
        produce -- a client must never be handed a cursor that pages past a real end.
        Absent/malformed cursor == first page, same as no cursor was ever sent.

        base_type=<model_type>: the CALLER's already-resolved selected base model's own
        model_type (the Gallery/Loom already resolve this today for the post-selection
        is_lora_compatible() gate -- this just reuses it). ONE caller-supplied value, three
        layers, coarsest first:
          1. SERVER-SIDE FILTER (added 2026-07-24, the real fix): threaded into
             model_search_market_gql as lora_base_type, which asks PixAI for LoRAs whose
             base family matches -- generationModels(loraBaseModelTypes:[<enum>]). This is
             what stops a DiT.2 user's LoRA browse from being 24-of-24 SD 1.5 rows, which
             was the actual complaint (the standing workaround was keyword-searching "sdxl"
             on PixAI's own site). Approximate, not strict, and only applied for architecture
             values on core's whitelist -- anything else falls through unfiltered.
             BROWSE ONLY since the owner's second walk (2026-09-07), which REFINES the
             2026-07-24 ruling rather than reversing it: see `server_lora_type` below.
          2. per-page soft SORT (compatible-or-unknown first, confirmed-mismatch last).
          3. per-row `compat` tag -- the PRECISE layer, see annotate_lora_compat(). Kept
             deliberately: layer 1 is a coarse browse hint, so only this one can be trusted
             to badge an individual row.
        Absent/kind=base -> results pass through unmodified, exactly as before."""
        from moonglade.gallery import _hunt_by_name
        q = (request.args.get("q") or "").strip()
        usage = "LORA" if (request.args.get("kind") or "base").lower() == "lora" else "MODEL"
        category = (request.args.get("category") or "").strip().lower()
        sort = (request.args.get("sort") or "").strip().lower()
        base_type = (request.args.get("base_type") or "").strip()
        cursor = (request.args.get("cursor") or "").strip()
        # --- picker parity round 3 (2026-07-26).
        # `src` is WHICH LIST to browse (market / bookmark / mine) -- the thing PixAI renders as
        # tabs. `source` is a market FILTER (all / pixai / external), which they express through
        # the connection's `types` argument. Two different concepts with confusingly similar
        # names in their own UI; keeping our query keys distinct so a caller cannot mix them up.
        src = (request.args.get("src") or "market").strip().lower()
        source = (request.args.get("source") or "").strip().lower()
        license_ = (request.args.get("license") or "").strip().upper()
        # Posted-at. The DateRange shape was CAPTURED from the live site 2026-07-26 --
        # {"gt": "<ISO instant>"}, start of day N days back in local time -- so core
        # builds it from a whitelisted token and an unknown token yields None (no filter).
        posted = (request.args.get("posted") or "").strip().lower()
        # Their Model Type filter is multi-select, so this is a repeated param rather
        # than one value. Base-model searches only; a LoRA search narrows by
        # architecture through base_type instead.
        model_types = [t for t in request.args.getlist("model_type") if t.strip()]
        try:
            size = max(1, min(int(request.args.get("size") or 24), 50))
        except ValueError:
            size = 24
        # The base-type filter is a BROWSE hint, not a SEARCH one -- owner's second walk
        # (2026-09-07: "searching for a known LoRA still fails"), REFINING the 2026-07-24
        # ruling that added layer 1, not reversing it. Typing a name is a hunt for a LoRA he
        # already knows, and the server filter answers that hunt by leaving the match OUT of
        # the results entirely: an SDXL LoRA searched for while Tsubaki.3 (MMDIT26B) is the
        # picked base simply is not there, the page fills up with other loosely-relevant
        # LoRAs, and the empty state never fires -- so the search reads as broken. With a
        # keyword we send NO filter and let layer 3 (annotate_lora_compat, the precise one)
        # show the match greyed with its "needs <arch>" badge instead of hiding it. Browsing
        # with no keyword keeps the filter exactly as 2026-07-24 set it: that wall
        # (24-of-24 SD 1.5 rows) is the whole reason layer 1 exists. `base_type` itself is
        # untouched -- it still feeds the sort and the badge on every LoRA search.
        server_lora_type = base_type if (usage == "LORA" and not q) else ""
        try:
            # The market is browsed AS THE WEBSITE (core.present_as_web): PixAI filters what it
            # returns by the client it believes it is talking to, and the API-key session's own
            # identity gets the stricter mobile-app policy -- a search that fills pages on the
            # site came back empty here (owner, 2026-09-07). Same key, same query, website
            # identity: the same rows the site shows.
            core, session = _gen_session()
            if src == "saved":
                # The Saved tab (Session S): one of the account's PixAI model collections --
                # Saved, the reserved default, unless `set` names a set -- 24 a page by cursor,
                # newest saved first. PixAI's own keyword search (cursor mode) and ONE LoRA
                # base (`base`, the chips) filter it; the kind is fixed by the picker. The plain
                # API-key session, as the 2026-10-03 probe read it (no website identity).
                rec = _recipes()
                set_id = (request.args.get("set") or "").strip()
                if not set_id:
                    found = rec.model_default(session, _recipe_user_id(core, session))
                    if found is None:
                        return jsonify({"results": [], "has_more": False, "next_cursor": ""})
                    set_id = found["id"]
                payload = rec.model_page(session, set_id, "lora" if usage == "LORA" else "base",
                                         cursor=cursor, query=q,
                                         lora_base=(request.args.get("base") or "").strip())
                if usage == "LORA" and base_type:
                    payload["results"] = _models.annotate_lora_compat(payload["results"], base_type)
                payload["read_only"] = _read_only_flag(core)
                return jsonify(payload)
            session = _mirror.present_as_web(session)
            if src == "bookmark":
                # Its own operation -- the market connection has no bookmark argument, so this
                # cannot be folded into the call below. Same row shape, so the grid does not care.
                def _bookmark_page(after):
                    return _models.model_bookmarks_gql(
                        session, keyword=q, usage=usage, limit=size, after=after,
                        lora_base_type=server_lora_type)
                payload = _hunt_by_name(_bookmark_page, q, size) if q else _bookmark_page(cursor or None)
            elif src == "mine":
                # "My LoRAs" is NOT a separate operation: it is the ordinary market connection
                # filtered by the signed-in user's own id, exactly as their MY LORA tab does it.
                def _mine_page(after):
                    return _models.model_search_market_gql(
                        session, keyword=q, category=category, sort=sort, usage=usage,
                        limit=size, after=after,
                        lora_base_type=server_lora_type,
                        author_id=_pixai_client._client_of(session).user_id or "")
                payload = _hunt_by_name(_mine_page, q, size) if q else _mine_page(cursor or None)
            # GraphQL whenever ANY market filter or sort is in play. The owner reported that
            # under Popular the Model Type and Posted-at filters did nothing: base+Popular used
            # to fall through to REST, whose own docstring says it "silently ignores market
            # filters". REST survives only for a bare, unfiltered base browse, where its richer
            # rows (description / refCount / official badge) are worth having.
            elif (usage == "LORA" or category in _models.MARKET_CATEGORIES
                  or posted or license_ or model_types
                  or (sort and sort not in ("trending", "popular"))):
                payload = _models.model_search_market_gql(
                    session, keyword=q, category=category, sort=sort, usage=usage,
                    limit=size, after=(cursor or None),
                    # The same caller-supplied value that feeds the compat sort/badge
                    # below, resolved once by the client -- but only on a keywordless BROWSE
                    # (see server_lora_type). core ignores it for a base-model search and for
                    # any architecture off its whitelist.
                    lora_base_type=server_lora_type,
                    source=source, permitted_use=license_,
                    time_range=_models.posted_at_range(posted),
                    model_types=model_types)
            else:
                offset = int(cursor) if cursor.isdigit() else 0
                payload = _models.model_search_rest(session, keyword=q, usage=usage,
                                                  size=size, offset=offset)
                payload["next_cursor"] = str(offset + size) if payload.get("has_more") else ""
            if usage == "LORA" and base_type:
                payload["results"] = _models.annotate_lora_compat(payload["results"], base_type)
            # Session S: every card's ⊕ Save dims under READ_ONLY before any tap (a local check)
            payload["read_only"] = _read_only_flag(core)
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "results": []}), 200

    @app.route("/api/model-version")
    @tier(LOGIN)
    def api_model_version():
        """Resolve a model_id (from the grid) to its generatable version id + the version
        metadata the picker needs: model_type (for LoRA↔base compat), lora_base_model_type,
        trigger_words (to offer inserting into the prompt), and the author's tuned preset.
        Login required; read-only, one API call.

        ?all=1 (picker-parity-round2, 2026-07-24): return EVERY published version instead of
        just the resolved latest -- {versions:[...]}, same per-row shape plus `label`/
        `is_latest` -- so the picker can offer a real choice (see
        core.list_model_versions). Default (no ?all) is UNCHANGED: the single resolved-latest
        shape every existing caller already expects.

        ?version_id=X (2026-08-02, the Runs reel's reuse-prefill): the REVERSE lookup --
        {"model_id": "..."} , "" if unresolvable. The catalog stores a run's model_id as the
        VERSION PixAI actually rendered with, not the base model id this route's other two
        modes take -- reuse-prefill needs this to feed applyModelRow the same real, current
        base id a fresh market pick would use, never the version id verbatim (see
        core.resolve_model_base_id)."""
        version_id = (request.args.get("version_id") or "").strip()
        if version_id:
            try:
                core, session = _gen_session()
                session = _mirror.present_as_web(session)   # same policy as the search that found it
                return jsonify({"model_id": _models.resolve_model_base_id(session, version_id)})
            except Exception as e:
                return jsonify({"error": _redact_host_paths(str(e))[:200], "model_id": ""}), 200
        mid = (request.args.get("model_id") or "").strip()
        if not mid:
            return jsonify({"error": "model_id required", "version_id": ""}), 400
        try:
            core, session = _gen_session()
            session = _mirror.present_as_web(session)   # same policy as the search that found it
            if (request.args.get("all") or "").strip() in ("1", "true"):
                return jsonify({"versions": _models.list_model_versions(session, mid)})
            # with_profiles: this is a BASE-model resolve whose answer feeds the composer's
            # mode bar, so it is one of the two places that pays the second, version-keyed
            # inference-profiles read (the ?all=1 branch's own is_latest row is the other).
            # Every other caller of resolve_version_meta -- the LoRA/remix path below --
            # leaves it off and stays at one read (red team 2026-09-07).
            # The same opt-in carries the version's size rule, the false compatibility
            # entries from /features and whether a reference goes out as a context image
            # (core._attach_features, SCOPE_2026-09-26) -- read from the gate's own cache.
            return jsonify(_models.resolve_version_meta(session, mid, with_profiles=True))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "version_id": ""}), 200

    @app.route("/api/task-params/<task_id>")
    @tier(LOGIN)
    def api_task_params(task_id):
        """A task's submit parameters, reduced to what Remix (issue #4) needs:
        the task's LoRAs -- exact {version_id, weight} pairs straight off
        parameters.lora, each resolved to its base model id for the composer,
        NEVER matched by name -- plus the exact model version id the task
        rendered with. Read-only; nothing here submits or spends, and the
        composer's own gates still stand between a prefill and a paid generate.

        Contract hardened by the 2026-08-13 adversarial review:
        - A task this library has no row for is refused (404) -- the route runs
          under the owner's credentials and must not be a free probe of
          arbitrary task ids for any signed-in LAN session (finding 4.3).
        - Video and chat tasks are refused (400) -- their recipes belong to
          their own pipelines (finding 4.2).
        - task_detail_gql returning None (its NETWORK-failure value -- it does
          not raise) answers {"error": ...}, never a success-shaped empty LoRA
          list: the client's disclosure branch keys on `error`, and without
          this the likeliest failure could structurally never be disclosed
          (finding 2.1).
        - retries=1: this is a prefill, not a lost generation -- the default
          retry ladder would hold the composer's 'restoring' state for minutes
          on a PixAI outage (finding 4.1).
        - An unparseable stored weight SKIPS the LoRA and counts it in
          `unresolved` -- never a silent plausible default (finding 1.5); a
          failed compatibility-meta lookup ships the row flagged `degraded`
          so the client can disclose it (finding 1.4)."""
        from moonglade.gallery import get_row_by_task
        tid = (task_id or "").strip()
        if not tid:
            return jsonify({"error": "task id required"}), 400
        crow = get_row_by_task(db_path, tid)
        if not crow:
            return jsonify({"error": "no such task in this library"}), 404
        if str(crow.get("is_video") or "") == "1":
            return jsonify({"error": "not an image-generation task"}), 400
        try:
            core, session = _gen_session()
            task = _task_reads.task_detail_gql(session, tid, retries=1)
            if not task:
                return jsonify({"error": "couldn't read the task from PixAI"}), 200
            params = task.get("parameters") or {}
            if isinstance(params.get("chat"), dict):
                return jsonify({"error": "not an image-generation task"}), 400
            lora_map = params.get("lora") or {}
            rows, unresolved = [], 0
            meta_cache = {}
            if isinstance(lora_map, dict):
                for vid, weight in lora_map.items():
                    try:
                        w = float(weight)
                    except (TypeError, ValueError):
                        unresolved += 1
                        continue
                    base = _models.resolve_model_base_id(session, str(vid))
                    if not base:
                        unresolved += 1
                        continue
                    if base not in meta_cache:
                        # No with_profiles here on purpose: nothing below reads `profiles`
                        # and a LoRA never renders a mode bar, so asking for it would cost a
                        # second PixAI GET per unique LoRA base for a field this route drops
                        # (red team 2026-09-07).
                        meta_cache[base] = _models.resolve_version_meta(session, base) or {}
                    meta = meta_cache[base]
                    lbt = str(meta.get("lora_base_model_type") or "")
                    rows.append({
                        "model_id": base, "version_id": str(vid), "weight": w,
                        "title": str(_models.model_name_gql(session, str(vid)) or "") or base,
                        "preview_url": "",
                        "lora_base_model_type": lbt,
                        "model_type": str(meta.get("model_type") or ""),
                        "degraded": not lbt,
                    })
            return jsonify({"task_id": tid, "loras": rows, "unresolved": unresolved,
                            "model_version_id": str(params.get("modelId") or "")})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/video-task-params/<task_id>")
    @tier(LOGIN)
    def api_video_task_params(task_id):
        """A VIDEO task's submit parameters, reduced to what "↺ Remix for videos"
        (SCOPE_2026-08-17 §2) needs: the shot kind (i2v / flf / r2v) and every
        recipe field the Video composer can set -- engine, duration, quality,
        camera, audio(+language), prompt-helper, negative, prompt, channel -- plus
        the source/reference media ids, each flagged in_lib against the local
        catalog so the client restores only what it actually holds.

        A deliberate SIBLING of /api/task-params rather than a widening of it: that
        route refuses videos (`not an image-generation task`) and its refusal test
        pins exactly that (dev/tests/test_task_params.py). Widening it would blur the
        two recipes' shapes; a sibling keeps each honest. Same contract otherwise:
        read-only (nothing here submits or spends; the composer's own price-identity
        gate still stands between a prefill and a paid generate), membership-checked
        against the catalog (finding 4.3 -- no free probing of arbitrary task ids),
        retries=1 (a prefill, not a lost generation -- finding 4.1), and
        host-path-redacted errors.

        Refuses (mirroring the image sibling, inverted): an IMAGE row (its recipe
        belongs to /api/task-params) and a CHAT task -- both `not a video task`,
        400. task_detail_gql returning None (its NETWORK-failure value, not a raise)
        answers {"error": ...}, never a success-shaped empty recipe."""
        from moonglade.gallery import get_row_by_task
        tid = (task_id or "").strip()
        if not tid:
            return jsonify({"error": "task id required"}), 400
        crow = get_row_by_task(db_path, tid)
        if not crow:
            return jsonify({"error": "no such task in this library"}), 404
        if str(crow.get("is_video") or "") != "1":
            return jsonify({"error": "not a video task"}), 400
        try:
            core, session = _gen_session()
            task = _task_reads.task_detail_gql(session, tid, retries=1)
            if not task:
                return jsonify({"error": "couldn't read the task from PixAI"}), 200
            params = task.get("parameters") or {}
            if not isinstance(params, dict):
                params = {}
            if isinstance(params.get("chat"), dict):
                return jsonify({"error": "not a video task"}), 400

            def _mref(mid):
                from moonglade.gallery import get_row
                mid = str(mid or "")
                if not mid:
                    return None
                return {"media_id": mid, "in_lib": bool(get_row(db_path, mid))}

            def _mrefs(ids):
                out = []
                for mid in (ids or []):
                    r = _mref(mid)
                    if r:
                        out.append(r)
                return out

            def _dur(v):
                # i2vPro.duration is a string ("5"), referenceVideo.duration an int -- normalize
                # to a clean int (or None) so the client never has to guess the type.
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

            out = {
                "task_id": tid,
                "model_id": str(params.get("modelId") or ""),
                "is_private": bool(params.get("isPrivate")),
            }
            rv = params.get("referenceVideo")
            i2v = params.get("i2vPro") or params.get("i2v")
            if isinstance(rv, dict):
                out.update({
                    "kind": "r2v",
                    "video_model": str(rv.get("model") or ""),
                    "duration": _dur(rv.get("duration")),
                    "quality": str(rv.get("mode") or ""),
                    "camera": "",
                    "audio": bool(rv.get("generateAudio")),
                    "audio_language": str(rv.get("audioLanguage") or ""),
                    "prompt_helper": False,
                    "negative": "",                      # r2v carries no negative (builder omits it)
                    "prompt": str(rv.get("prompt") or ""),
                    # The source's output aspect ratio (Tsubaki engines only). Read so the
                    # Remix can SAY it is not carried -- the drawer has no ratio picker yet,
                    # and a hidden carried ratio would be priced and sent unseen (2026-09-26).
                    "ratio": str(rv.get("ratio") or ""),
                    "start": None, "end": None,
                    "image_refs": _mrefs(rv.get("referenceImageMediaIds")),
                    "video_refs": _mrefs(rv.get("referenceVideoMediaIds")),
                    "audio_refs": _mrefs(rv.get("referenceAudioMediaIds")),
                })
            elif isinstance(i2v, dict):
                tail = str(i2v.get("tailMediaId") or "")
                out.update({
                    "kind": "flf" if tail else "i2v",
                    "video_model": str(i2v.get("model") or ""),
                    "duration": _dur(i2v.get("duration")),
                    "quality": str(i2v.get("mode") or ""),
                    "camera": str(i2v.get("cameraMovement") or ""),
                    "audio": bool(i2v.get("generateAudio")),
                    "audio_language": str(i2v.get("audioLanguage") or ""),
                    "prompt_helper": bool(i2v.get("usePromptsHelper")),
                    "negative": str(i2v.get("negativePrompts") or ""),
                    "prompt": str(i2v.get("prompts") or ""),
                    "start": _mref(i2v.get("mediaId")),
                    "end": _mref(tail),
                    "image_refs": [], "video_refs": [], "audio_refs": [],
                })
            else:
                # A video ROW whose task has neither block: nothing safe to prefill from.
                return jsonify({"error": "not a video task"}), 400
            return jsonify(out)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/image-meta/<media_id>")
    @tier(LOGIN)
    def api_image_meta(media_id):
        """The one catalog row the Upscale panel needs, by media_id. Read-only, no network.

        Scoped deliberately narrow: the fields an i2i upscale submits (real pixel size, the
        model that made it, and the prompt it is re-rendered under) plus what the panel shows
        about them. NOT a general row dump -- `filename` in particular is a HOST PATH
        fragment and stays out, matching the same withholding /panel does for non-local
        callers.

        Not localhost-gated, for the reason /api/gallery-images spells out: it reads only the
        local catalog and returns what the gallery already serves openly, so a gate would add
        no protection while breaking the panel for the owner browsing over his own LAN.
        Spending stays gated on /api/generate, which is where the upscale is actually
        submitted.
        """
        from moonglade.gallery import get_row
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"error": "no such image"}), 404
        # A model id is what makes an upscale submittable without asking. Locally imported
        # files have no PixAI task behind them and so can never carry one -- the panel says
        # so and offers its picker, rather than presenting a blank as though it were a
        # catalog gap the owner could go and fill.
        source = str(row.get("source") or "")
        return jsonify({
            "media_id": str(row.get("media_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "width": str(row.get("width") or ""),
            "height": str(row.get("height") or ""),
            "model_id": str(row.get("model_id") or ""),
            "model_name": str(row.get("model_name") or ""),
            "prompt": str(row.get("prompt_full") or row.get("prompt_preview") or ""),
            "negative": str(row.get("negative_prompt") or ""),
            "steps": str(row.get("steps") or ""),
            "cfg": str(row.get("cfg_scale") or ""),
            "is_video": str(row.get("is_video") or "") == "1",
            "source": source,
            "local_import": source == "local",
        })

    @app.route("/api/gallery-images")
    @tier(LOGIN)
    def api_gallery_images():
        """Pick-from-your-gallery source for the create surfaces + The Loom: recent (or
        keyword-filtered) IMAGE media_ids with thumbnails -> use the media_id full-res, no
        re-upload. Read-only. NOT localhost-gated: it reads ONLY the local catalog and
        returns the same thumbnails/prompts the gallery already serves openly, so the gate
        added no protection while breaking the picker for the owner on a --host 0.0.0.0
        server accessed via a LAN address. Spending still gated on the generate/upload
        routes. ?q=&limit=&page="""
        from moonglade.gallery import query_catalog
        q = (request.args.get("q") or "").strip()
        try:
            limit = max(1, min(int(request.args.get("limit") or 40), 100))
            page = max(1, int(request.args.get("page") or 1))
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            limit, page, rating_min = 40, 1, 0
        sort = "oldest" if (request.args.get("sort") or "") == "oldest" else "newest"
        # type: image (default -> back-compat with the create pickers) | video | all.
        # Filtering happens in SQL (media_type) so pagination + total are correct even
        # for videos (a tiny slice of the catalog); the old post-query skip returned
        # near-empty pages for anything video-heavy.
        gtype = (request.args.get("type") or "image").strip().lower()
        media_type = gtype if gtype in ("image", "video") else ""   # "" = both
        rows, total = query_catalog(
            db_path, q=q, sort=sort, page=page, page_size=limit,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            rating_min=rating_min, media_type=media_type,
            # No SVG on this list (3.22 S5, DESIGN_3.22 5.3): the Apple TV client reads it and
            # tvOS cannot draw one, and no create surface may take one as a source. In SQL, so
            # the page and the total stay true.
            no_svg=True)
        out = []
        for r in rows:
            mid = r.get("media_id")
            if not mid:
                continue
            isv = str(r.get("is_video") or "") == "1"
            # is_nsfw rides along so every consumer of this route (the gallery Picker,
            # <mg-gallery-picker>, and the Generate drawer's reference slots) can set
            # data-nsfw the same way the Jinja template and /api/similar already do.
            # Audit 2026-07-21 S5: this was the one remaining projection gap -- without
            # it, Privacy Blur (body.privacy-blur .card[data-nsfw="1"] img) never saw an
            # NSFW thumbnail on any of these three surfaces.
            isnsfw = str(r.get("is_nsfw") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "is_nsfw": "1" if isnsfw else "",
                        "thumb": "/thumbs/{}.jpg".format(mid),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000],
                        "duration": (r.get("video_duration") or "") if isv else "",
                        # Session H: a context image's size, for the drawer's Auto frame
                        "w": str(r.get("width") or ""), "h": str(r.get("height") or ""),
                        "rating": str(r.get("rating") or "0")})
        return jsonify({"images": out, "total": total, "page": page, "limit": limit})

    @app.route("/api/similar/<media_id>")
    @tier(LOGIN)
    def api_similar(media_id):
        """'More like this': the k catalog images most visually similar to media_id, via the
        moonglade.similar CLIP sidecar index. Mirrors /api/gallery-images's shape so the client
        reuses the same .card rendering. Read-only; fails soft to an empty list if the sidecar
        index or its ML stack isn't available/built yet, so it never 500s the gallery."""
        from moonglade.gallery import find_image_file, get_row
        try:
            k = max(1, min(int(request.args.get("k") or 24), 60))
        except ValueError:
            k = 24
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"images": [], "total": 0, "error": "unknown media_id"}), 404
        img_path = find_image_file(out_dir, media_id, row.get("filename"))
        if not img_path:
            return jsonify({"images": [], "total": 0, "error": "image file not found"}), 200
        try:
            from moonglade import similar as moonglade_similar
            hits = moonglade_similar.similar(str(img_path), k=k, exclude_media_id=media_id)
        except Exception as e:
            return jsonify({"images": [], "total": 0,
                            "error": "similarity index unavailable: " + _redact_host_paths(str(e))[:180]}), 200
        # An EMPTY index is not the same as "no matches", and conflating the two hid a real
        # regression for three days. The 2026-07-25 module rename orphaned the stored index;
        # moonglade.similar._get_table() then CREATED a fresh empty one instead of raising, so this
        # route returned zero hits with no error at all and the client fell back to "the index may
        # still be building" -- a benign transient message covering a permanent broken state.
        # Reporting the size lets the client tell the truth and say what to do about it.
        if not hits:
            try:
                indexed = int(moonglade_similar.count())
            except Exception:
                indexed = None
            if indexed == 0:
                return jsonify({"images": [], "total": 0, "indexed": 0,
                                "error": "The similarity index is empty, so there is nothing to "
                                         "compare against. Rebuild it from the Control Panel "
                                         "(Rebuild similar index)."}), 200
        _telemetry.telem_bump("similar_uses", out_dir=out_dir)       # Kindred Spirits
        out = []
        for mid, score in hits:
            r = get_row(db_path, mid)
            if not r:
                continue        # the sidecar index can drift from later catalog deletes
            isv = str(r.get("is_video") or "") == "1"
            # is_nsfw rides along so the client's hand-cloned .card (Similar.open() below --
            # this modal builds its own DOM instead of reusing the server-rendered template at
            # the top of the page, unlike every other card-producing surface) can set
            # data-nsfw the same way the Jinja template does. Without it, Privacy Blur
            # (body.privacy-blur .card[data-nsfw="1"] img) never sees an NSFW lookalike here
            # at all, and it never gets blurred -- fixed alongside the client half below.
            isnsfw = str(r.get("is_nsfw") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "is_nsfw": "1" if isnsfw else "",
                        "thumb": "/thumbs/{}.jpg".format(mid), "score": round(float(score), 3),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000]})
        return jsonify({"images": out, "total": len(out), "query": str(media_id)})

    @app.route("/api/collections")
    @tier(LOGIN)
    def api_collections():
        """Collection names for the picker/filter dropdowns. Read-only, local catalog."""
        from moonglade.gallery import unique_collections
        return jsonify({"collections": unique_collections(db_path)})

    @app.route("/contact-sheet")
    @tier(LOGIN)
    def contact_sheet():
        """Print-ready views for physical output. ?format=letter (grid, default) |
        photo (single 4x6) | strip (photo-booth: 2x2in strips on a 4x6, for the
        Sinfonia). Sources: ?ids=a,b,c or ?collection=<name>. ?cols / ?captions for
        the grid. Opens the print dialog on load."""
        # This page is assembled with str.format(), NOT render_template_string, so it
        # gets NONE of Jinja's autoescaping -- every catalog/query value interpolated
        # below has to be escaped by hand or ?collection=<script>... is reflected XSS
        # straight into the logged-in session (markupsafe escapes ' and " too, which
        # the single-quoted src=' ' attributes here depend on).
        from moonglade.gallery import ordered_members, query_catalog, rows_for_media_ids
        from markupsafe import escape
        ids_arg = (request.args.get("ids") or "").strip()
        collection = (request.args.get("collection") or "").strip()
        fmt = (request.args.get("format") or "letter").lower()
        if fmt not in ("letter", "photo", "strip"):
            fmt = "letter"
        try:
            cols = max(2, min(int(request.args.get("cols") or 4), 8))
        except ValueError:
            cols = 4
        captions = (request.args.get("captions") or "1") not in ("0", "false", "no")
        if ids_arg:
            ids = [x for x in ids_arg.split(",") if x.strip()]
            rows = rows_for_media_ids(db_path, ids)
            title = "{} selected".format(len(rows))
        elif collection:
            # P6: a collection prints in its own order (a hand-picked one's manual order, then
            # pictures added since, oldest first; a smart one's matches, oldest first).
            rows = rows_for_media_ids(db_path, ordered_members(db_path, collection)["media_ids"][:400])
            title = "Collection: {}".format(escape(collection))
        else:
            rows, _ = query_catalog(db_path, sort="newest", page=1, page_size=60)
            title = "Recent"

        mids = [str(r.get("media_id")) for r in rows if r.get("media_id")]
        # The page's two scripts carry this response's nonce (CSP_PAGE_POLICY runs nothing
        # else), and the Print button is wired from the nonced script, not an onclick.
        _nonce = _csp_nonce()
        _autoprint = ("<script nonce='" + _nonce + "'>"
                      "var _p=document.getElementById('mg-print');"
                      "if(_p)_p.addEventListener('click',function(){window.print();});"
                      "window.addEventListener('load',function(){"
                      "setTimeout(function(){window.print();},350);});</script>")
        _bar = ("<div class='bar'><h1>{t}</h1><button id='mg-print'>"
                "\U0001f5a8 Print</button><a href='/' style='margin-left:auto'>"
                "&larr; gallery</a></div>")

        if fmt == "photo" and mids:
            return ("<!DOCTYPE html><html><head><meta charset='UTF-8'><title>4x6 photo</title>"
                    "<style>@page{size:4in 6in;margin:0}html,body{margin:0;height:100%;"
                    "background:#fff;font-family:system-ui,sans-serif}"
                    ".bar{display:flex;gap:12px;align-items:center;padding:10px}"
                    ".bar h1{font-size:15px;margin:0}"
                    ".photo{width:100%;height:100vh;display:flex;align-items:center;"
                    "justify-content:center;overflow:hidden}"
                    ".photo img{max-width:100%;max-height:100%;object-fit:contain}"
                    "@media print{.bar{display:none}}</style></head><body>"
                    + _bar.format(t="4&times;6 photo")
                    + "<div class='photo'><img src='/full/{}'></div>".format(escape(mids[0]))
                    + _autoprint + "</body></html>")

        if fmt == "strip" and mids:
            frames = [mids[i % len(mids)] for i in range(4)]
            frame_html = "".join(
                "<div class='frame'><img src='/full/{}'></div>".format(escape(m)) for m in frames)
            one = "<div class='strip'>" + frame_html + "</div>"
            return ("<!DOCTYPE html><html><head><meta charset='UTF-8'><title>Photo strip</title>"
                    "<style>@page{size:4in 6in;margin:0}html,body{margin:0;height:100%;"
                    "background:#fff;font-family:system-ui,sans-serif}"
                    ".bar{display:flex;gap:12px;align-items:center;padding:10px}"
                    ".bar h1{font-size:15px;margin:0}"
                    ".strips{display:flex;width:4in;height:6in}"
                    ".strip{width:2in;height:6in;display:flex;flex-direction:column;"
                    "padding:0.05in;box-sizing:border-box}"
                    ".strip:first-child{border-right:1px dashed #bbb}"
                    ".frame{flex:1;margin:0.03in 0;overflow:hidden}"
                    ".frame img{width:100%;height:100%;object-fit:cover;display:block}"
                    "@media print{.bar{display:none}}</style></head><body>"
                    + _bar.format(t="Photo-booth strip (cut in two)")
                    + "<div class='strips'>" + one + one + "</div>"
                    + _autoprint + "</body></html>")

        cells = []
        for r in rows:
            mid = str(r.get("media_id") or "")
            if not mid:
                continue
            cap = ""
            if captions:
                date = (r.get("created_at") or "")[:10]
                try:
                    stars = "★" * int(r.get("rating") or 0)
                except (TypeError, ValueError):
                    stars = ""
                cap = "<div class='cap'>{}{}</div>".format(
                    escape(date), (" " + stars) if stars else "")
            cells.append(
                "<figure><img src='/thumbs/{}.jpg' alt=''>{}</figure>".format(
                    escape(mid), cap))
        html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Contact sheet &middot; {title}</title>
<style>
  @page {{ size: letter; margin: 12mm; }}
  body {{ font-family: system-ui, sans-serif; margin: 18px; color: #111; }}
  .bar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
  .bar h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  .bar button {{ font-size: 13px; padding: 6px 14px; cursor: pointer; }}
  .grid {{ display: grid; grid-template-columns: repeat({cols}, 1fr); gap: 8px; }}
  figure {{ margin: 0; break-inside: avoid; }}
  figure img {{ width: 100%; aspect-ratio: 1; object-fit: cover; border: 1px solid #ddd; border-radius: 4px; display: block; }}
  .cap {{ font-size: 9px; color: #555; margin-top: 2px; text-align: center; }}
  @media print {{ .bar {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<div class="bar"><h1>{title} &middot; {n} images</h1>
  <button id="mg-print">&#128424; Print</button>
  <a href="/" style="margin-left:auto;">&larr; back to gallery</a></div>
<div class="grid">{cells}</div>
{autoprint}
</body></html>""".format(title=title, cols=cols, n=len(cells), cells="".join(cells),
                         autoprint=_autoprint)
        return html

    @app.route("/api/contact-sheet")
    @tier(LOGIN)
    def api_contact_sheet():
        """JSON twin of /contact-sheet -- feeds the React ContactSheetOverlay's on-screen
        preview and its own native (window.print()) output. Same source selection as the
        page route (rows_for_media_ids / query_catalog); the page route stays untouched
        for classic's own use until demolition -- the new front door never calls it."""
        from moonglade.gallery import ordered_members, query_catalog, rows_for_media_ids
        import datetime as _dt
        ids_arg = (request.args.get("ids") or "").strip()
        collection = (request.args.get("collection") or "").strip()
        if ids_arg:
            ids = [x for x in ids_arg.split(",") if x.strip()]
            rows = rows_for_media_ids(db_path, ids)
            collection_name = "{} selected".format(len(rows))
        elif collection:
            # P6: the collection's own order, the same as the print view above.
            rows = rows_for_media_ids(db_path, ordered_members(db_path, collection)["media_ids"][:400])
            collection_name = collection
        else:
            rows, _ = query_catalog(db_path, sort="newest", page=1, page_size=60)
            collection_name = "Recent"

        frames = []
        for r in rows:
            mid = str(r.get("media_id") or "")
            if not mid:
                continue
            try:
                stars = "★" * int(r.get("rating") or 0)
            except (TypeError, ValueError):
                stars = ""
            title = ((r.get("title") or "").strip()
                     or (r.get("prompt_preview") or "").strip()[:60]
                     or "Untitled")
            frames.append({
                "media_id": mid,
                "title": title,
                "model": r.get("model_name") or "",
                "stars": stars,
                "thumb_url": "/thumbs/{}.jpg".format(mid),
            })

        d = _dt.datetime.now()
        printed_date = "{} {}, {}".format(d.strftime("%B"), d.day, d.year)
        return jsonify({
            "collectionName": collection_name,
            "frameCount": len(frames),
            "printedDate": printed_date,
            "frames": frames,
        })

    @app.route("/api/duplicates")
    @tier(LOGIN)
    def api_duplicates():
        """Real, working duplicate-groups listing for the React Duplicate Review overlay
        (the parked affordance in HealthOverlay.jsx's Duplicates/Reclaimable stat tiles).
        Owner-scoped "happy medium" (2026-08-02, moonglade-internal/DECISIONS.md), FOUR tiers --
        3 EXACT-match with no invented data/percentage, plus one perceptual-similarity
        tier that carries a real, derived closeness score (see near_duplicate below) --

          same_media     Class A: the same PixAI media_id reused across >1 folder bucket.
                          duplicate_groups() (this module) -- the classic /duplicates
                          page's own engine, reused as-is (its 300-row cap is lifted here;
                          see the call below).
          identical_file Class B: byte-identical files under DIFFERENT media_ids.
                          moonglade.organize.audit_collection(content=True)'s size-bucketed
                          SHA pass -- reused as-is; not naive O(n^2).
          same_seed       Class C: catalog rows sharing (seed, prompt_full) -- a cheap
                          SQL GROUP BY (same_seed_groups(), this module), not a new
                          detection algorithm.
          near_duplicate  Class D (new): images whose dHash `phash` column (populated by
                          `--backfill-phash`, compute_dhash()) is within a Hamming-
                          distance threshold of another's -- catches an upscaled or
                          recompressed copy of the same image, which byte-hashing (Class
                          B) cannot, because the bytes genuinely differ. The ONE tier
                          that carries a `closeness_pct` per group (near_duplicate_groups(),
                          this module) -- real, Hamming-distance-derived, never invented;
                          the other three tiers stay percentage-free by design. Rows with
                          no phash yet (backfill not run / not yet reached that row)
                          simply don't participate -- they are not reported as "no match",
                          they are just absent from this tier until backfilled.

        Deliberately EXCLUDES the CLIP-embedding "similar composition" tier -- real
        infrastructure exists at /api/similar, but it measures visual resemblance, not
        duplication (see DECISIONS.md).

        Read-only, no filesystem mutation -- LOGIN tier, same trust class as the classic
        /duplicates page and api_health. Members are shaped identically across all four
        tiers (media_id/thumb/dims/rating/date/path/bucket/size/is_keeper) so the client
        never has to special-case by matchType."""
        from moonglade.gallery import find_image_file, rows_for_media_ids
        from moonglade import backup as core

        def _member(mid, row, path, bucket, size, is_keeper):
            from moonglade.gallery import is_archive_only
            row = row or {}
            isv = str(row.get("is_video") or "") == "1"
            return {
                "media_id": str(mid),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "width": row.get("width") or "",
                "height": row.get("height") or "",
                "rating": row.get("rating") or "",
                "created_at": row.get("created_at") or "",
                "is_video": "1" if isv else "",
                "path": str(path).replace("\\", "/"),
                "bucket": bucket,
                "size": size,
                "is_keeper": bool(is_keeper),
                # PixAI no longer has it (#66): in the same_seed / near_duplicate tiers it is
                # the only copy of its picture, and the Resolve confirms name it.
                "archive_only": is_archive_only(row),
            }

        groups = []

        # ---- same_media (Class A) -------------------------------------------
        # No arbitrary cap here -- the classic page's limit=300 exists to keep an HTML
        # render short, not because the underlying scan is expensive (one scan_library
        # pass, no hashing); this route reports the real count instead of truncating.
        class_a = _dupes.duplicate_groups(out_dir, limit=100000)
        rows_a = {r["media_id"]: r for r in rows_for_media_ids(db_path, [g["media_id"] for g in class_a])}
        for g in class_a:
            mid = g["media_id"]
            row = rows_a.get(str(mid))
            members = [_member(mid, row, c["rel"], c["bucket"], c["size"], c["rel"] == g["keeper"])
                       for c in g["copies"]]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "same_media:{}".format(mid), "matchType": "same_media",
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- identical_file (Class B) ----------------------------------------
        audit = _organize.audit_collection(out_dir, content=True)
        class_b = audit["class_b"]
        mids_b = sorted({str(item[4]) for g in class_b for item in g["files"]})
        rows_b = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_b)}
        for g in class_b:
            keeper_path = g["keeper"][0]
            members = [_member(mid, rows_b.get(str(mid)), rel, bucket, size, p == keeper_path)
                       for (p, rel, bucket, size, mid) in g["files"]]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "identical_file:{}".format(g["sha"]), "matchType": "identical_file",
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- same_seed (Class C) ----------------------------------------------
        seed_groups = _dupes.same_seed_groups(db_path)
        mids_c = sorted({mid for g in seed_groups for mid in g["media_ids"]})
        rows_c = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_c)}
        for g in seed_groups:
            candidates = []
            for mid in g["media_ids"]:
                row = rows_c.get(str(mid))
                if not row:
                    continue        # a stale media_id (row deleted since indexed) -- skip, don't fabricate
                fpath = find_image_file(out_dir, mid, row.get("filename"))
                try:
                    size = fpath.stat().st_size if fpath else 0
                except OSError:
                    size = 0
                # Sort key: oldest real created_at first (the original generation is the
                # keeper); a blank date sorts LAST so an unknown-date row is never
                # mistaken for the original over a row with a real timestamp.
                sort_key = row.get("created_at") or "9999-99-99"
                candidates.append((sort_key, mid, row, fpath, size))
            if len(candidates) < 2:
                continue             # every media_id in this seed group turned out stale
            candidates.sort(key=lambda c: c[0])
            keeper_mid = candidates[0][1]
            members = [_member(mid, row, (str(fpath.relative_to(out_dir)) if fpath else ""),
                               "", size, mid == keeper_mid)
                       for (_, mid, row, fpath, size) in candidates]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "same_seed:{}:{}".format(g["seed"], g["prompt_hash"]),
                           "matchType": "same_seed", "seed": g["seed"],
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- near_duplicate (Class D, new) ------------------------------------
        # Same "resolve real rows/files, oldest created_at is the keeper" shape as
        # same_seed above -- the only tier-specific addition is closeness_pct, carried
        # at the group level exactly like same_seed carries `seed`.
        near_groups = _dupes.near_duplicate_groups(db_path)
        mids_d = sorted({mid for g in near_groups for mid in g["media_ids"]})
        rows_d = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_d)}
        for g in near_groups:
            candidates = []
            for mid in g["media_ids"]:
                row = rows_d.get(str(mid))
                if not row:
                    continue        # stale media_id (row deleted since phash was computed)
                fpath = find_image_file(out_dir, mid, row.get("filename"))
                try:
                    size = fpath.stat().st_size if fpath else 0
                except OSError:
                    size = 0
                sort_key = row.get("created_at") or "9999-99-99"
                candidates.append((sort_key, mid, row, fpath, size))
            if len(candidates) < 2:
                continue             # every media_id in this group turned out stale
            candidates.sort(key=lambda c: c[0])
            keeper_mid = candidates[0][1]
            members = [_member(mid, row, (str(fpath.relative_to(out_dir)) if fpath else ""),
                               "", size, mid == keeper_mid)
                       for (_, mid, row, fpath, size) in candidates]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "near_duplicate:{}".format("-".join(g["media_ids"])),
                           "matchType": "near_duplicate", "closeness_pct": g["closeness_pct"],
                           "reclaimable_bytes": reclaim, "members": members})

        groups.sort(key=lambda g: -g["reclaimable_bytes"])
        counts = {"same_media": len(class_a), "identical_file": len(class_b),
                 "same_seed": len(seed_groups), "near_duplicate": len(near_groups)}
        return jsonify({
            "groups": groups,
            "counts": counts,
            "total_groups": len(groups),
            "total_reclaimable_bytes": sum(g["reclaimable_bytes"] for g in groups),
        })

    @app.route("/api/duplicates/resolve", methods=["POST"])
    @tier(LOGIN)
    def api_duplicates_resolve():
        """The destructive half of Duplicate Review: quarantines the LOSING
        copies of one or more duplicate groups into out_dir/_duplicates/, via
        quarantine_duplicate_file() above -- QUARANTINE ONLY, mirroring
        cmd_dedup()'s DEFAULT (--apply without --dedup-delete) behavior.
        --dedup-delete's hard-delete path is not reachable through this route
        under any body field.

        Body: {"csrf": "...", "resolutions": [ {group_id, keep, remove}, ... ]}
        -- OR the single-resolution shortcut, the same three fields at the TOP
        level (group_id/keep/remove), for the per-group "Resolve" button; the
        frontend's "Auto-resolve all" sends the batch shape instead of one
        request per group, so a many-group resolve is one round trip, not N.

        `keep` and each entry of `remove` are {"media_id": "...", "path": "..."}
        -- the exact (media_id, path) pair GET /api/duplicates already returned
        for that member. `path`, not media_id, is what actually disambiguates a
        member: a same_media group's members all share ONE media_id (that
        tier's whole definition -- the same generation saved in more than one
        folder), so media_id alone cannot say which COPY to keep vs remove;
        path can, because GET /api/duplicates already returns a distinct path
        per member in every tier.

        SAFETY -- enforced here, not just a disabled frontend button:
          * keep-count 0 (no valid `keep`, or nothing valid in `remove`) -> that
            resolution is refused with a clear per-group error and nothing is
            touched for it; "remove everything including the keeper" is not a
            resolve.
          * every path is validated to resolve strictly inside out_dir (no ../
            escape) and its own filename's encoded media_id (media_id_of())
            must match the media_id claimed for it.
          * the keep/remove pair is re-verified as a REAL duplicate
            relationship for the group_id's own matchType, against the actual
            files/catalog rows right now -- see _validate_duplicate_pair()'s
            docstring for the exact check run per tier.

        CSRF: explicit-token class (_check_csrf(), the same helper
        /api/users/add, /api/users/remove and /api/users/password use) -- a
        real, hard-to-undo-by-accident file mutation triggered by one web
        click, not the exempt spend-path class /api/generate etc. sit in.

        READ_ONLY in config.json refuses this exactly like submit_generation/
        submit_fixer/delete_task/claim_reward -- see
        quarantine_duplicate_file().

        ARCHIVE-ONLY MEMBERS GO WITH THE REST (#66; the owner's ruling on the 2026-10-03
        walk: warn, don't block). In the same_seed and near_duplicate tiers a member PixAI no
        longer has (is_archive_only) is the only copy of ITS picture; the screens name it
        before Resolve (each member carries `archive_only`), and Undo puts its file and its
        snapshotted catalog row back (restore_quarantined_duplicate).

        Response: {"quarantined": [...], "errors": [...], "reclaimed_bytes": N}.
        Per-item, not all-or-nothing -- one bad group in a batch (a stale
        group_id, a file already gone) does not block the rest, same "one file
        the OS won't release must not strand the rest" shape as
        /api/delete-local."""
        from moonglade.gallery import (_resolve_under, _validate_duplicate_pair,
                                       quarantine_duplicate_file)
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400

        resolutions = body.get("resolutions")
        if not isinstance(resolutions, list):
            single = {k: body.get(k) for k in ("group_id", "keep", "remove")}
            resolutions = [single] if single.get("group_id") else []
        if not resolutions:
            return jsonify({"error": "no resolutions given"}), 400

        quarantined, errors = [], []
        for res in resolutions:
            res = res if isinstance(res, dict) else {}
            group_id = str(res.get("group_id") or "").strip()
            keep = res.get("keep")
            remove_raw = res.get("remove")
            if not group_id:
                errors.append({"group_id": group_id, "error": "missing group_id"})
                continue
            if (not isinstance(keep, dict) or not str(keep.get("media_id") or "").strip()
                    or not str(keep.get("path") or "").strip()):
                errors.append({"group_id": group_id,
                               "error": "no keeper specified -- refusing to resolve "
                                        "(keep-count is 0)"})
                continue

            keep_path_str = str(keep.get("path") or "")
            # The keeper guard compares RESOLVED paths, not the raw client strings --
            # 'images//a.png', 'images\\a.png' and './images/a.png' all name the same
            # file as 'images/a.png', and a raw-string compare would let an aliased
            # spelling of the keeper slip into the remove list (the validator can't
            # catch it either: the keeper is byte-identical and same-media with
            # itself by definition). Found by the 2026-08-07 branch review.
            keep_resolved = _resolve_under(out_dir, keep_path_str)
            seen, remove_items = set(), []
            for item in (remove_raw if isinstance(remove_raw, list) else []):
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("media_id") or "").strip()
                path = str(item.get("path") or "").strip()
                if not mid or not path or path in seen:
                    continue
                item_resolved = _resolve_under(out_dir, path)
                if item_resolved is not None and item_resolved == keep_resolved:
                    continue                      # the keeper itself, however spelled
                if path == keep_path_str:
                    continue                      # raw match still caught if unresolvable
                seen.add(path)
                remove_items.append({"media_id": mid, "path": path})
            if not remove_items:
                errors.append({"group_id": group_id, "error": "nothing valid to remove"})
                continue

            match_type = group_id.split(":", 1)[0]
            ok, why = _validate_duplicate_pair(out_dir, db_path, match_type, keep, remove_items)
            if not ok:
                errors.append({"group_id": group_id, "error": why})
                continue

            keep_mid = str(keep.get("media_id"))
            for item in remove_items:
                result = quarantine_duplicate_file(out_dir, thumb_dir, db_path,
                                                   item["media_id"], item["path"], group_id)
                if result.get("ok"):
                    result["group_id"] = group_id
                    result["kept_media_id"] = keep_mid
                    quarantined.append(result)
                else:
                    errors.append({"group_id": group_id, "media_id": item["media_id"],
                                  "error": result.get("error")})

        if quarantined:
            _telemetry.telem_bump("duplicates_resolved", len(quarantined), out_dir=out_dir)
        return jsonify({"quarantined": quarantined, "errors": errors,
                        "reclaimed_bytes": sum(q.get("size", 0) for q in quarantined)})

    @app.route("/api/duplicates/undo", methods=["POST"])
    @tier(LOGIN)
    def api_duplicates_undo():
        """Reverses ONE quarantine_duplicate_file() call (see its own docstring
        and restore_quarantined_duplicate()): moves a single quarantined
        duplicate back to its exact original recorded location and restores its
        catalog row. Singular by design -- 'Undo' on one just-resolved item, not
        a batch undo; an 'Auto-resolve all' that needs undoing calls this once
        per item, the same acceptable simplification /api/duplicates/resolve's
        own docstring notes for the read side of this feature.

        Body: {"csrf": "...", "quarantine_path": "_duplicates/images/p_t2_333.webp"}
        -- the exact `quarantine_path` /api/duplicates/resolve returned for that
        item.

        Same CSRF class, same tier, same READ_ONLY gate as resolve (see
        restore_quarantined_duplicate()). Fails with a clear error -- never a
        silent no-op or a write to some OTHER location -- when the undo record
        is missing/stale or the original location is now occupied by something
        else."""
        from moonglade.gallery import restore_quarantined_duplicate
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        quarantine_path = str(body.get("quarantine_path") or "").strip()
        if not quarantine_path:
            return jsonify({"error": "quarantine_path required"}), 400
        result = restore_quarantined_duplicate(out_dir, thumb_dir, db_path, quarantine_path)
        if result.get("ok"):
            _telemetry.telem_bump("duplicates_undone", out_dir=out_dir)
        return jsonify(result)

    # The app's three data routes: /api/library, /api/detail/<media_id>, /api/history, each
    # on exactly one path. They used to answer on a second one under /api/next/, the React
    # app's pilot codename, for one release of grace; that is gone, and a page left open
    # from before 3.17.0 needs a reload (dev/tests/test_api_route_aliases.py pins it). The
    # /next/assets/ prefix above is NOT part of this: installed phone apps read their icons
    # from it, so it is never dropped.
    @app.route("/api/library")
    @tier(LOGIN)
    def api_library():
        """The new gallery's own listing surface -- full filter set, clean field
        names, one purpose. Reads the same catalog engine (query_catalog) as
        everything else; nothing here is borrowed from the picker routes.

        Two dial-in-series modes ride on top (#34 direction B), both no-ops unless
        the client opts in, so the default payload is exactly what it was before:
          * ?group=series -- fold the FULL filtered set into series UNITS: a
            multi-task series becomes ONE card (its cover row + a `series` key with
            the sid/counts/title), every other row stays its own card, and paging
            counts units, not rows. Grouping is server-side because a series spans
            many pages (up to 801 images) -- a client can't collapse what it never
            sees on one page.
          * ?series=<sid> -- the complement: the ungrouped listing constrained to
            one series' members (B's 'open a stack' navigation), resolved in SQL by
            query_catalog. Ignored while group=series (grouping supersedes it)."""
        from moonglade.gallery import (list_group_rows, personal_get, query_catalog,
                                       rows_for_media_ids)
        q = (request.args.get("q") or "").strip()
        try:
            page = max(1, int(request.args.get("page") or 1))
            page_size = max(1, min(int(request.args.get("page_size") or 100), 200))
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            page, page_size, rating_min = 1, 100, 0
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        sort = (request.args.get("sort") or "newest").strip()
        group = (request.args.get("group") or "").strip()
        series = (request.args.get("series") or "").strip()
        # One filter set, keyed by query_catalog()/list_group_rows()'s own param
        # names, so the paged row query and the whole-set grouping query see an
        # IDENTICAL WHERE + ORDER.
        filters = dict(
            q=q, sort=sort, rating_min=rating_min, media_type=media,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            # The Advanced flyout's fields -- same engine params the classic
            # gallery's form submits, same names where the URL is user-visible.
            model=(request.args.get("model") or "").strip(),
            lora=(request.args.get("lora") or "").strip(),
            date_from=(request.args.get("from") or "").strip(),
            date_to=(request.args.get("to") or "").strip(),
            art_tag=(request.args.get("tag") or "").strip(),
            # Not a flyout field -- reached only from the Details view's "View batch"
            # link (same engine param the classic gallery's own link sets).
            batch=(request.args.get("batch") or "").strip(),
            published_only=(request.args.get("published") or "") == "1")

        _pers = {}     # media_id -> personal layer, filled once per page (Session N3)

        def _card(r):
            """One grid card dict for a catalog row -- the SINGLE definition both the
            plain row listing and a grouped unit's cover build, so a series cover is
            byte-identical to that same media as an ordinary card (only the extra
            `series` key ever differs)."""
            from moonglade.gallery import is_archive_only
            mid = r.get("media_id")
            pl = _pers.get(str(mid)) or {}
            return {
                # The owner's own layer (N3): the keeper|reject mark the card wears, and the
                # tags. Local catalog only.
                "mark": pl.get("mark", ""),
                "tags": pl.get("tags", []),
                "media_id": str(mid),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "is_video": str(r.get("is_video") or "") == "1",
                "is_nsfw": str(r.get("is_nsfw") or "") == "1",
                "model": str(r.get("model_name") or ""),
                "date": str(r.get("created_at") or "")[:10],   # UTC day -- fallback only; the
                "created_at": str(r.get("created_at") or ""),  # client derives the LOCAL day from this
                "rating": int(str(r.get("rating") or "0") or 0)
                          if str(r.get("rating") or "").isdigit() else 0,
                "w": str(r.get("width") or ""),
                "h": str(r.get("height") or ""),
                "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:1200],
                # The pilot's captions were missing metrics the classic card shows
                # (owner QA, 2026-07-30): where it came from, and the actual file.
                "source": str(r.get("source") or ""),
                "filename": str(r.get("filename") or ""),
                # The placard's Accession Stamp + Sibling Strip (issue #30): the
                # client batches task_ids into one POST /api/siblings per page.
                "task_id": str(r.get("task_id") or ""),
                "title": str(r.get("title") or "").strip(),
                "batch_index": str(r.get("batch_index") or ""),   # #33: PixAI's own output number
                "batch_size": str(r.get("batch_size") or ""),
                # Session H T3a: the Lightbox edit bar is offered on the same pictures as the
                # "Edit with Tsubaki" menu item -- every still, whatever model made it (owner
                # ruling, 2026-09-28). Never on a video.
                "tsubaki_edit": str(r.get("is_video") or "") != "1",
                # #66: PixAI no longer has it, so this is the only copy -- the card's
                # corner pill reads ARCHIVE.
                "archive_only": is_archive_only(r),
            }

        if group == "series":
            by_task, by_sid = _series.series_index(db_path)
            # The whole filtered set, ids + the four grouping columns only, in sort
            # order. Bounded (measured in dev/tests/test_series_grouping.py).
            unit_order, members = _series.fold_series_units(
                list_group_rows(db_path, **filters), by_task)
            total = len(unit_order)
            start = (page - 1) * page_size
            page_keys = unit_order[start:start + page_size]
            # Resolve this page's units to ONE cover media_id each (the newest
            # surviving image of the unit), then fetch just those full rows -- one
            # query, at most page_size rows.
            cover_ids = [str(_series._series_cover_row(members[k]).get("media_id") or "")
                         for k in page_keys]
            full = {str(r.get("media_id")): r
                    for r in rows_for_media_ids(db_path, cover_ids)}
            _pers.update(personal_get(db_path, cover_ids))
            items = []
            for k, mid in zip(page_keys, cover_ids):
                r = full.get(mid)
                if r is None:
                    continue
                card = _card(r)
                if k[0] == "series":
                    s = by_sid.get(k[1]) or {}
                    card["series"] = {
                        "sid": k[1],
                        # count_tasks is the series' FULL task (version) count from
                        # by_sid -- the dial's step count, a property of the series
                        # itself, not of the current filter. count_images is the
                        # SURVIVING member count (cheap -- we already hold them), so a
                        # filtered stack's image tally matches what the filter left
                        # visible rather than overcounting hidden members.
                        "count_tasks": s.get("count_tasks", 0),
                        "count_images": len(members[k]),
                        "title": s.get("title", ""),
                    }
                elif k[0] == "task" and len(members[k]) >= 2:
                    # A folded BATCH -- one task with >=2 surviving images (not a
                    # multi-task series). Mark it so the grid renders a BATCH stack that
                    # opens through the existing View-batch path (?batch=task_id). A lone
                    # image (one survivor) carries no marker and renders as today's plain
                    # singleton, indistinguishable from an ungrouped card.
                    card["batch"] = {"task_id": k[1], "count": len(members[k])}
                items.append(card)
        else:
            rows, total = query_catalog(
                db_path, page=page, page_size=page_size, series=series, **filters)
            _pers.update(personal_get(db_path, [r.get("media_id") for r in rows]))
            items = [_card(r) for r in rows if r.get("media_id")]
        pages = max(1, (total + page_size - 1) // page_size)
        return jsonify({"items": items, "total": total, "page": page, "pages": pages})

    @app.route("/api/detail/<media_id>")
    @tier(LOGIN)
    def api_detail(media_id):
        """The pilot's Details view backing data -- classic's detail() route (~12254),
        JSON instead of a server-rendered page. Full row, plus prev_id/next_id computed
        the SAME way: list_media_ids() under the CURRENT filter/sort (the same param
        names /api/library accepts), index looked up in that ordered id list.

        Deliberately does NOT precompute img_url/video_url/an existence check the way
        classic's route does -- classic needed that because a dead <img src> shows a
        broken-image icon with no explanation. The client already gets that signal for
        free (an <img>/<video> onError), so there is nothing here worth a filesystem
        stat the caller didn't ask for."""
        from moonglade.gallery import get_row, is_archive_only, list_media_ids, personal_get
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        q = (request.args.get("q") or "").strip()
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        sort = (request.args.get("sort") or "newest").strip()
        try:
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            rating_min = 0
        nav_ids = list_media_ids(
            db_path, q=q, sort=sort, rating_min=rating_min, media_type=media,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            model=(request.args.get("model") or "").strip(),
            lora=(request.args.get("lora") or "").strip(),
            date_from=(request.args.get("from") or "").strip(),
            date_to=(request.args.get("to") or "").strip(),
            art_tag=(request.args.get("tag") or "").strip(),
            # The View batch drill-down (#81): the list route filters by it, so the walk
            # this picture sits in -- its "k of N" and Prev/Next -- must stay inside it too.
            batch=(request.args.get("batch") or "").strip(),
            # The opened stack (?series=<sid>), same reason: /api/library honours it, so the
            # walk a picture opened from a stack sits in stays inside that stack.
            series=(request.args.get("series") or "").strip(),
            published_only=(request.args.get("published") or "") == "1")
        try:
            idx = nav_ids.index(media_id)
        except ValueError:
            idx = -1
        prev_id = nav_ids[idx - 1] if idx > 0 else None
        next_id = nav_ids[idx + 1] if 0 <= idx < len(nav_ids) - 1 else None
        # Where this picture sits in the WHOLE filtered walk and how long the walk is --
        # the same list prev/next came from, so no second query (#64). The phone prints
        # them as "14 of 3,240"; a picture the filter does not contain has no position.
        position = idx + 1 if idx >= 0 else None
        pl = personal_get(db_path, [media_id]).get(str(media_id)) or {}
        out = {
            "row": row,
            # The owner's own layer over this picture (N3): tags, keeper|reject, a note.
            "personal": {"tags": pl.get("tags", []), "mark": pl.get("mark", ""),
                         "note": pl.get("note", "")},
            "prev_id": prev_id, "next_id": next_id,
            "position": position, "nav_total": len(nav_ids),
            # Same value the gallery's own "Delete from PixAI" is gated on. A LAN
            # session can browse and spend, but not destroy on the owner's real
            # cloud account.
            "can_delete_cloud": _is_local_request(),
            "siblings": _batch_sibling_count(row.get("task_id")),
            # #66: gone from PixAI as of the last check -- the record says so, and its
            # "Delete locally" names it the last copy before it asks.
            "archive_only": is_archive_only(row),
        }
        # Session M (NOTES 3): the run this picture came from, when the caller's own account
        # sent it through the dock -- History reuse restores the TEMPLATE from it, not the
        # resolved prompt. A read of the Runs store; absent for everything else.
        run = _run_for_task(row.get("task_id"))
        if run is not None:
            out["run"] = run
        return jsonify(out)

    def _run_for_task(task_id):
        try:
            from moonglade import runs
            found = runs.RunsStore(out_dir).find_task(task_id)
        except Exception:                                    # noqa: BLE001
            return None
        if not found:
            return None
        run, job = found
        if run.get("account") != str(session.get("user") or ""):
            return None
        return {"run_id": run.get("run_id"), "mode": run.get("mode"),
                "template": run.get("template") or "", "var_mode": run.get("var_mode") or "",
                "count": run.get("count"), "run_seed": run.get("run_seed"),
                "dock_seed": run.get("dock_seed") or "", "cell": job.get("cell"),
                "vars": job.get("vars") or []}

    def _history_ts(created_at):
        """Epoch seconds for a stored created_at, or None. Tolerant of the three forms
        the catalog holds: PixAI's 24-char `2026-08-17T06:14:10.545Z`, the 20-char
        no-millis `…Z` fallback, and 6 legacy local-import rows that are 19-char naive
        (`2026-07-29T21:47:44`) -- read as UTC, which is what they were written as."""
        from datetime import datetime, timezone
        s = str(created_at or "").strip()
        if s.endswith("Z"):
            s = s[:-1]
        try:
            base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        frac = s[19:]
        ms = 0.0
        if frac.startswith(".") and frac[1:].isdigit():
            ms = float("0" + frac)
        return base.timestamp() + ms

    @app.route("/api/history")
    @tier(LOGIN)
    def api_history():
        """Read-only feed for the Generate dock's History mode: the last `days` LOCAL
        calendar days of finished runs (catalog rows by created_at, newest first, empty
        days included as [] = "No runs"), with the live job log merged on top -- a
        running/stale/failed generate job that has no catalog rows yet becomes one
        synthetic row in its day; a done job is dropped (its media ARE catalog rows,
        saved before the done event ever lands), and a running job whose task already
        has rows in the window is dropped too (catalog wins). One indexed range query
        (`created_at >= ? AND created_at < ?`, no functions on the column) plus one
        seek for the paging cursor; core.read_jobs() DIRECTLY -- never /api/jobs's
        helpers, which reconcile against PixAI and rewrite the log. No network, no
        spend path, no _check_read_only: a local SQLite SELECT and a local file read.

        Params: days (1..31, default 7) · before (YYYY-MM-DD local, EXCLUSIVE cursor;
        absent = today is the newest bucket) · tz (minutes EAST of UTC, JS
        `-new Date().getTimezoneOffset()`; default = this server's local offset) ·
        source (online|api|local) · media (image|video) -- the last two in
        _build_where's own idiom. Day boundaries are computed HERE so the indexed
        window is exactly N local days and the empty days / `next_before` cursor are
        deterministic (and pytest-able) rather than a client-side guess."""
        from moonglade.gallery import history_created_ats, history_page
        from moonglade import backup as core
        from collections import Counter
        from datetime import datetime, timedelta, timezone
        try:
            days = max(1, min(int(request.args.get("days") or 7), 31))
        except ValueError:
            days = 7
        try:
            tz_min = int(request.args.get("tz") or "")
        except ValueError:
            tz_min = int(round((datetime.now().astimezone().utcoffset()
                                or timedelta(0)).total_seconds() / 60))
        tz_min = max(-14 * 60, min(tz_min, 14 * 60))
        tzinfo = timezone(timedelta(minutes=tz_min))
        before = (request.args.get("before") or "").strip()
        if before:
            try:
                end_local = datetime.strptime(before, "%Y-%m-%d").replace(tzinfo=tzinfo)
            except ValueError:
                return jsonify({"error": "before must be YYYY-MM-DD"}), 400
        else:
            today = datetime.now(tzinfo).date()
            end_local = datetime(today.year, today.month, today.day,
                                 tzinfo=tzinfo) + timedelta(days=1)
        start_local = end_local - timedelta(days=days)
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        source = (request.args.get("source") or "").strip().lower()
        source = source if source in ("online", "api", "local") else ""

        def utc_iso(dt):
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        def local_date(ts):
            return datetime.fromtimestamp(ts, tzinfo).date()

        def as_int(s):
            s = str(s or "").strip()
            if not s:
                return None
            try:
                return int(float(s))
            except ValueError:
                return None

        since_utc, until_utc = utc_iso(start_local), utc_iso(end_local)
        page = history_page(db_path, since_utc, until_utc, media=media, source=source)
        rows = page["rows"]
        # Paging cursor: the NEWEST row older than this window, so the next page
        # opens on a day that has runs instead of a run of empty days.
        next_before, older_days = None, 0
        older_ts = _history_ts(page["older_created_at"]) if page["older_created_at"] else None
        if older_ts is not None:
            nb_date = local_date(older_ts) + timedelta(days=1)
            nb_local = datetime(nb_date.year, nb_date.month, nb_date.day, tzinfo=tzinfo)
            next_before = nb_date.isoformat()
            older_days = len({
                local_date(t) for t in (
                    _history_ts(c) for c in history_created_ats(
                        db_path,
                        utc_iso(nb_local - timedelta(days=days)), utc_iso(nb_local),
                        media=media, source=source))
                if t is not None})

        buckets = {}
        for i in range(days):
            d = end_local - timedelta(days=i + 1)
            buckets[d.date().isoformat()] = []
        task_counts = Counter(str(r["task_id"] or "") for r in rows)
        for r in rows:
            ts = _history_ts(r["created_at"])
            if ts is None:
                continue
            key = local_date(ts).isoformat()
            if key not in buckets:
                continue
            mid = str(r["media_id"] or "")
            tid = str(r["task_id"] or "")
            is_video = str(r["is_video"] or "") == "1"
            pc = str(r["paid_credit"] or "").strip()
            duration = None
            if is_video:
                try:
                    duration = float(r["video_duration"]) if str(r["video_duration"] or "").strip() else None
                except ValueError:
                    duration = None
            buckets[key].append({
                "media_id": mid,
                "task_id": tid,
                "kind": "video" if is_video else "image",
                "state": "done",
                "created_at": str(r["created_at"] or ""),
                "ts": ts,
                "w": as_int(r["width"]),
                "h": as_int(r["height"]),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "media_url": ("/video-file/{}" if is_video else "/full/{}").format(mid),
                "model": str(r["model"] or ""),
                "model_id": str(r["model_id"] or ""),
                "prompt": str(r["prompt"] or ""),
                "duration": duration,
                "paid_credit": as_int(pc) if pc else None,
                "source": str(r["source"] or ""),
                "count_in_task": task_counts[tid] if tid else 1,
            })

        # Live jobs on top, deduped against the catalog by task_id (== job_id for a
        # generate job). Jobs are always the dock's own runs (source 'api'), so a
        # feed narrowed to backed-up or imported rows has no live rows to add.
        try:
            jobs = _jobs.read_jobs(out_dir)
        except Exception:
            jobs = []
        tasks_in_window = {str(r["task_id"] or "") for r in rows if r["task_id"]}
        for j in jobs:
            if j.get("type") != "generate":
                continue
            if j.get("status") not in ("running", "stale", "failed"):
                continue
            jid = str(j.get("job_id") or "")
            if not jid or jid in tasks_in_window:
                continue
            is_video = bool(j.get("is_video"))
            if (media == "video" and not is_video) or (media == "image" and is_video):
                continue
            if source in ("online", "local"):
                continue
            try:
                ts = float(j.get("started_at") or j.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            key = local_date(ts).isoformat()
            if key not in buckets:
                continue
            pc = j.get("paid_credit")
            try:
                count = max(1, int(j.get("count") or 1))
            except (TypeError, ValueError):
                count = 1
            buckets[key].append({
                "job_id": jid,
                "task_id": jid,
                "media_id": None,
                "kind": "video" if is_video else "image",
                "state": j.get("status"),
                "ts": ts,
                "created_at": datetime.fromtimestamp(ts, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"),
                "count": count,
                "label": j.get("label"),
                "error": j.get("error"),
                "eta_seconds": j.get("eta_seconds"),
                "started": j.get("started"),
                "paid_credit": (int(pc) if isinstance(pc, (int, float))
                                and not isinstance(pc, bool) else None),
                "w": None, "h": None, "thumb": None, "prompt": None, "model": None,
            })
        for key in buckets:
            buckets[key].sort(key=lambda x: (x["ts"], str(x.get("media_id") or "")),
                              reverse=True)
        return jsonify({
            "tz": tz_min,
            "days": [{"date": d, "label_hint": None, "rows": buckets[d]} for d in buckets],
            "next_before": next_before,
            "has_more": next_before is not None,
            "older_days": older_days,
        })

    def _find_local_video_file(mid, row=None):
        """Resolve a catalog media_id to its local video file on disk -- the app-bound face
        of the module-level find_local_video_file (which holds the whole rule and its
        reasons), supplying this library's out_dir and, when the caller has none, its row.

        Shared by /api/loom/handoff (frame extraction), /api/loom/video-duration
        (footage-import fallback probe), the detail page's does-this-clip-exist check, and
        /video-file itself. That last one is the point rather than a nicety: while
        /video-file resolved `row["filename"]` on its own, the page could decide a clip was
        present (via the fallback here) and then link to a URL that 404s, which draws a dead
        player and says nothing -- the very failure the detail-page check was added to stop.
        One resolver, four callers, one answer. (The fifth, since 2026-09-26, is the
        reference-video length lookup -- core.make_video_duration_lookup -- which calls the
        module-level function so the CLI's --reference-video reads the same answer.)

        `row` is an already-loaded catalog row, passed by callers that just fetched it so
        this doesn't repeat a primary-key SELECT they already paid for. It is a cache, not
        an override: pass a DIFFERENT row and you get a different file, which is why only
        the two callers holding this exact mid's row use it."""
        from moonglade.gallery import get_row
        return _scan.find_local_video_file(out_dir, mid,
                                     row if row is not None else get_row(db_path, mid))

    def _loom_complete_clip(mid):
        """The library file for a clip id, only when it is a COMPLETE file (Invariant 3: a
        .part download and a zero-byte file are not there) inside the library. Or None."""
        p = _find_local_video_file(mid)
        if p is None:
            return None
        try:
            if (p.name.endswith(".part") or not p.is_file() or p.stat().st_size <= 0
                    or not _scan._is_under(p.resolve(), out_dir.resolve())):
                return None
        except OSError:
            return None
        return p

    # -- provided to ctx (split_move) --
    ctx._find_local_video_file = _find_local_video_file
    ctx._loom_complete_clip = _loom_complete_clip
    # -- end --

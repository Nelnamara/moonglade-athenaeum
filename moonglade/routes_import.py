"""moonglade/routes_import.py -- the import and outside routes: Fix them on the outside notice,
the Suggest prompt read, tag autocomplete, the picker's upload to PixAI, and the local import
(files and zips into the catalog), with the zip extractor its caps and zip-slip guard live in.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, after the spend routes and before the Loom's routes (the block sat just
before the Loom store; DESIGN 1.5's order, since the Suggest prompt read takes
_source_format_lookup from routes_generate). Names the block reads from create_app's setup, the
front door (the CSRF check, the PixAI session, the host-path redactor) and the spend routes come
in through ctx (the bound-from-ctx lines below), so every closure on both sides holds the one
same object; _safe_extract_zip stays a closure cell of api_import_local. gallery's own names (the
zip caps, the outside fix lock, the outside scan) are imported inside the function that reads
them, at call time, so a test's patch of moonglade.gallery still reaches the route.
"""

from flask import jsonify, request

from moonglade import gen_params as _gen_params
from moonglade import scan as _scan
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.web_tiers import LOCALHOST, LOGIN, tier
    # -- bound from ctx (split_move) --
    _check_csrf = ctx._check_csrf
    _gen_session = ctx._gen_session
    _redact_host_paths = ctx._redact_host_paths
    _source_format_lookup = ctx._source_format_lookup
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    @app.route("/api/outside/fix", methods=["POST"])
    @tier(LOCALHOST)
    def api_outside_fix():
        """**Fix them** on the notice about things outside the app that still name its old
        files (server_notice; moonglade.outside, DECISIONS 2026-10-07 pick 5): this machine's
        scheduled tasks, Claude tools registrations and shortcuts are looked at again, now,
        and each one found is rewritten to the new names -- a copy of it kept first in
        local\\.snapshot\\ -- and reported fixed or failed, with the reason, in plain words.

        LOCALHOST: it rewrites files and Task Scheduler entries on the machine the server runs
        on, the same trust class as /api/branding/shortcut. The CSRF explicit-token class: a
        real change to the machine off one click. One fix at a time."""
        from moonglade.gallery import _OUTSIDE_FIXING, _outside_scan, _shortcut_icon_bytes
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        if not _OUTSIDE_FIXING.acquire(blocking=False):
            return jsonify({"error": "Already fixing them. Give it a moment."}), 409
        try:
            from moonglade import outside as moonglade_outside
            results = moonglade_outside.fix(provide_icon=_shortcut_icon_bytes)
            _outside_scan()
        finally:
            _OUTSIDE_FIXING.release()
        kind, title, msg = moonglade_outside.result_words(results)
        return jsonify({"ok": True, "kind": kind, "title": title, "msg": msg,
                        "results": [r.as_dict() for r in results]})

    @app.route("/api/suggest-prompt")
    @tier(LOGIN)
    def api_suggest_prompt():
        """Image-to-prompt for the gallery's 'Suggest prompt' button: PixAI's tag list +
        NL description for a media_id. Read-only and free; login required. ?media_id="""
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"suggestions": [], "error": "media_id required"}), 400
        # 3.22 S5: PixAI reads no prompt from an SVG; refused here, before any request.
        why = _gen_params.source_refusal(_source_format_lookup(mid), "prompt")
        if why:
            return jsonify({"suggestions": [], "error": why}), 200
        try:
            core, session = _gen_session()
            return jsonify({"suggestions": core.suggest_prompt(session, mid)})
        except Exception as e:
            return jsonify({"suggestions": [], "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/tag-suggest")
    @tier(LOGIN)
    def api_tag_suggest():
        """Tag autocomplete for the drawer's prompt boxes (the site's Tag Suggestions
        dropdown). Read-only and free; login required. ?q=<prefix>."""
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"tags": []})
        try:
            core, session = _gen_session()
            return jsonify({"tags": core.tag_search_gql(session, q, first=8)})
        except Exception as e:
            return jsonify({"tags": [], "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/upload", methods=["POST"])
    @tier(LOGIN)
    def api_upload():
        """Upload a local file from the picker -> PixAI media_id (the same free
        3-step S3 handshake as the CLI's --upload). Login required,
        spends nothing. At most UPLOAD_MAX_BYTES (a 413 with a plain sentence past it)."""
        from moonglade.gallery import UPLOAD_MAX_BYTES
        request.max_content_length = UPLOAD_MAX_BYTES
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        import os as _os
        import tempfile
        suffix = _os.path.splitext(f.filename)[1][:8] or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            f.save(tmp)
            tmp.close()
            core, session = _gen_session()
            mid = core.upload_media(session, tmp.name)
            _telemetry.telem_bump("uploads", out_dir=out_dir)        # first-upload milestone
            return jsonify({"media_id": str(mid)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

    def _safe_extract_zip(zip_path, dest_dir, max_members=None, max_total=None):
        """Extract a zip into dest_dir, dropping any member whose resolved path would escape
        dest_dir (zip-slip). Localhost-only caller, but a crafted archive still shouldn't be
        able to write outside the temp dir.

        Capped (app security review 2026-11-19, finding 9): a zip with more than
        ZIP_MAX_MEMBERS files is refused before anything is written, and extraction stops
        the moment the bytes WRITTEN pass ZIP_MAX_TOTAL_BYTES -- counted as they are written,
        never taken from the zip's own size fields, which a zip bomb lies in. Either raises
        ZipTooBig with its plain sentence; the caller's temp dir is then thrown away."""
        from moonglade.gallery import (ZIP_MAX_MEMBERS, ZIP_MAX_MEMBER_BYTES, ZIP_MAX_TOTAL_BYTES,
                                       ZIP_MEMBER_TOO_BIG, ZIP_TOO_BIG, ZIP_TOO_MANY_MEMBERS,
                                       ZipTooBig)
        import os as _os
        import zipfile as _zip
        max_members = ZIP_MAX_MEMBERS if max_members is None else max_members
        max_total = ZIP_MAX_TOTAL_BYTES if max_total is None else max_total
        root = _os.path.realpath(dest_dir)
        written = 0
        with _zip.ZipFile(zip_path) as z:
            members = [m for m in z.namelist() if not m.endswith("/")]
            if len(members) > max_members:
                raise ZipTooBig(ZIP_TOO_MANY_MEMBERS)
            for m in members:
                target = _os.path.realpath(_os.path.join(dest_dir, m))
                if target != root and not target.startswith(root + _os.sep):
                    continue                          # zip-slip -> skip
                _os.makedirs(_os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as dst:
                    member = 0
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        written += len(chunk)
                        member += len(chunk)
                        if member > ZIP_MAX_MEMBER_BYTES:
                            raise ZipTooBig(ZIP_MEMBER_TOO_BIG)
                        if written > max_total:
                            raise ZipTooBig(ZIP_TOO_BIG)
                        dst.write(chunk)
        return written

    @app.route("/api/import-local", methods=["POST"])
    @tier(LOCALHOST, message="this imports files onto the server's machine; localhost-only")
    def api_import_local():
        """Import local files into the catalog as source='local' -- the web equivalent of the
        CLI's --import-local. Accepts multipart `files` (images/videos); a `.zip` is expanded.

        Localhost-only: it copies files into the backup (`imported/`) and shells out to build
        thumbnails on the machine the SERVER process runs on -- a host-filesystem write, the
        same trust tier as the destructive Panel jobs and /api/branding/shortcut, NOT the
        broader logged-in-LAN auth. A LAN device must never be able to write files onto the
        owner's machine. Nothing is uploaded to PixAI (that's /api/upload).

        Saves the uploads to a temp dir (expanding any zip), then reuses
        core.run_import_local (copy -> imported/ + catalog source='local' + thumbnail, path
        dedup), tags an optional collection, and returns counts. Synchronous for now."""
        from moonglade.gallery import (IMPORT_REQUEST_MAX_BYTES, ZIP_MAX_TOTAL_BYTES, ZipTooBig,
                                       _is_smart_name, add_to_collection)
        import os as _os
        import tempfile
        import shutil
        from types import SimpleNamespace
        from moonglade import backup as core
        # Finding 9: one request is at most IMPORT_REQUEST_MAX_BYTES (the page's batches stay
        # far under it), and everything its zips unpack shares one ZIP_MAX_TOTAL_BYTES budget.
        request.max_content_length = IMPORT_REQUEST_MAX_BYTES
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "no files"}), 400
        collection = (request.form.get("collection") or "").strip()
        if collection and _is_smart_name(db_path, collection.replace(",", " ").strip()):
            # a smart collection is a saved search: refuse BEFORE any file is imported (N1)
            return jsonify({"error": "“{}” is a smart collection, a saved search; "
                                     "pictures can't be imported into it.".format(collection)}), 400
        tmp = tempfile.mkdtemp(prefix="mg_import_")
        try:
            saved = 0
            unzip_left = ZIP_MAX_TOTAL_BYTES
            # A guard, not the design: the web page sends a big folder in several requests
            # (hooks/useImport.js), so this is only reached by a caller that sends more at
            # once. What it does not take it COUNTS, and says so in the answer (#82) -- it
            # used to drop everything past the cap without a word.
            not_taken = max(0, len(files) - _scan.IMPORT_REQUEST_CAP)
            for i, f in enumerate(files[:_scan.IMPORT_REQUEST_CAP]):
                base = _os.path.basename(f.filename or "")
                if not base:
                    not_taken += 1          # a part with no file name: nothing to import
                    continue
                # Own subdir per upload so two files sharing a basename don't collide in the
                # temp dir; run_import_local then copies each into imported/ by basename, so the
                # final names stay clean (matching the CLI's --import-local behavior).
                sub = _os.path.join(tmp, str(i))
                _os.makedirs(sub, exist_ok=True)
                dest = _os.path.join(sub, base)
                f.save(dest)
                if base.lower().endswith(".zip"):
                    try:
                        unzip_left -= _safe_extract_zip(dest, sub, max_total=unzip_left)
                    except ZipTooBig as e:
                        return jsonify({"error": str(e)}), 413
                    finally:
                        try: _os.unlink(dest)
                        except OSError: pass
                saved += 1
            if not saved:
                return jsonify({"error": "no usable files"}), 400
            res = core.run_import_local(SimpleNamespace(out=str(out_dir), import_local=tmp))
            mids = res.get("media_ids") or []
            if collection and mids:
                add_to_collection(db_path, mids, collection)
            return jsonify({"ok": True, "imported": res["imported"], "skipped": res["skipped"],
                            "not_taken": not_taken, "collection": collection or None})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # -- provided to ctx (split_move) --
    # -- end --

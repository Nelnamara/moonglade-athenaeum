"""moonglade/routes_branding.py -- the branding routes: the public branding art (/branding/<path>,
the one PUBLIC route here), badge thumbnails and feat masks, and the branding panel's API (the
banner mark and its animation, slot uploads, crops and the active pick, role uploads, restores
and defaults, the custom mark, the earned banners and the Desktop launcher shortcut).

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the second and larger block was, after the Mirror's routes (the
first block sat after the library routes; its rules keep their tiers and endpoints). Names the
block reads from create_app's setup and the front door (the CSRF check, the host-path redactor)
come in through ctx (the bound-from-ctx lines below), so every closure on both sides holds the
one same object. gallery's own names are imported inside the function that reads them, at call
time, so a test's patch of moonglade.gallery still reaches the route.
"""
import hmac
import re

from flask import jsonify, request

from moonglade import achievements as _achievements
from moonglade import branding as _branding
from moonglade import scan as _scan
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.gallery import LOCALHOST, LOGIN, PUBLIC, tier
    # -- bound from ctx (split_move) --
    _check_csrf = ctx._check_csrf
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    @app.route("/branding/<path:fname>")
    @tier(PUBLIC)
    def branding(fname):
        """Serve branding art. The URL vocabulary is PUBLIC role names
        (/branding/marks/..., /branding/bridge/emotion/...); the on-disk tree
        and the container keys are CODED -- this route is the ONE place the
        two meet (_public_rel_to_coded, applied exactly once to the incoming
        rel). After translation: seal check, then a loose file under
        branding_root() first, the shipped container second (the loose-then-
        container contract every read path holds). Absent everywhere -> 404 so
        the header's onerror simply removes the <img>. Path-safe.

        The three banner flats take their OWN branch, after the seal check and
        in place of the loose-root lookup (2026-09-10): they are per-install
        RENDERS, not tree assets, so the coded root is never read for them.
        This install's flat wins -- the only copy in banner_keep_dir() when the
        slot wears one, else its render in banner_cache_dir(); failing that the
        container's own copy, if an older pack carries one; failing that the
        slot's SHIPPED sealed default, so a fresh install is dressed before its
        first crop. And the coded ROOT's own top level is inert the same way: a
        bare rel translation did not recognize reads the container only, so a
        file parked at the root is never served.

        This route SERVES and never renders. It is PUBLIC tier -- an anonymous
        GET from anywhere on the LAN reaches it -- so it must not be able to
        schedule a Pillow decode-crop-resize-save, and it must not write into
        the cache. Keeping a render current is create_app's startup ensure pass
        (_ensure_banner_renders) plus the explicit user actions that change a
        pick; see _ensure_banner_flat."""
        from moonglade.gallery import harden_file_response
        from flask import send_from_directory, abort
        import mimetypes
        bdir = _branding.branding_root().resolve()
        try:
            target = (bdir / fname).resolve()
            target.relative_to(bdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        coded = _branding._public_rel_to_coded(target.relative_to(bdir).as_posix())
        # Pictures only (owner, 2026-11-18): any other type -- a hand-dropped .html or
        # .svg above all, on this PUBLIC route -- is a 404 before anything is read,
        # loose or packed. branding_serves_type names the one carve-out (the shipped
        # moments' clips and sounds) and why.
        if not _branding.branding_serves_type(coded):
            abort(404)
        # The unlock split, enforced (see _seal_rule, which judges the CODED
        # rel -- a probe that guesses a coded path passes through translation
        # unchanged, so it faces the same verdict): achievement-bound art only
        # serves once its achievement is earned, whether the bytes would come
        # from a loose file or the container.
        mode, seal_aid = _branding._seal_rule(coded)
        if mode == "deny":
            abort(404)
        if mode == "earned" and seal_aid not in _branding._earned_achievement_ids(
                out_dir, db_path, need=seal_aid):
            abort(404)
        if coded in _branding._BANNER_FLAT.values():
            # The flat branch. bdir is deliberately NOT consulted: the render
            # lives in the cache, and a file parked at the coded root is not a
            # render. Pure lookup -- whatever the startup ensure pass and the
            # explicit write paths left here is what is served.
            slot = next(s for s, n in _branding._BANNER_FLAT.items() if n == coded)
            cdir = _branding._served_flat_dir(out_dir, slot)
            try:
                have_render = (cdir / coded).is_file()
            except OSError:
                have_render = False
            if have_render:
                resp = send_from_directory(str(cdir), coded)
                resp.headers["Cache-Control"] = "no-cache, must-revalidate"
                return harden_file_response(resp, coded)
            # Container-ONLY read (not _branding_bytes, which would try the
            # coded root loose first): an older pack may carry a top-level flat.
            box = _branding._get_container()
            raw = box.get(coded) if box else None
            if raw is None:
                # Rule-8 flat fallback: nothing rendered on this install yet and
                # nothing to render FROM -> the slot's shipped sealed default
                # (translation itself never rewrites the flat names).
                raw = _branding._branding_bytes(_branding._flat_default_rel(slot))
        elif "/" not in coded:
            # A bare rel translation did not recognize (rule 7) addresses the
            # coded ROOT's own top level, and the root is inert (2026-09-10):
            # the app writes nothing there, the discovery walk does not count
            # what sits there, and this route does not serve it. Container only
            # -- loose root is never read.
            box = _branding._get_container()
            raw = box.get(coded) if box else None
        elif (coded.lower() in _branding._role_coded_rels() and (bdir / coded).is_file()
              and not _branding._role_file_decodes(bdir / coded)
              and (_branding._get_container() is not None and _branding._get_container().has(coded))):
            # Fail-soft (Session X): an override of a named role that will not decode is the
            # pack's default, silently. Container-ONLY, like the flat branch above -- the loose
            # bytes are exactly what must not be served. With no pack default to fall back to
            # there is nothing better to say, and the loose file is served as it always was.
            raw = _branding._get_container().get(coded)
        elif (bdir / coded).is_file():
            resp = send_from_directory(str(bdir), coded)
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"   # branding art gets re-cut; never serve a stale copy
            return harden_file_response(resp, coded)
        elif coded in _branding._moment_clip_rels():
            # A moment's clip, container-sourced (no loose copy): verified once,
            # then sliced from memory for every range the <video> asks for.
            raw = _branding._container_clip_bytes(coded)
        else:
            # Container fallback keys on the CODED rel (posix separators -- the
            # container's native addressing; loose path == container key, always).
            raw = _branding._branding_bytes(coded)
        if raw is None:
            abort(404)
        # Every body that reaches here is in memory -- the container's bytes, or a
        # flat's shipped default read through _branding_bytes -- rather than a file
        # send_from_directory streams, so it gets the Range handling that would
        # have given a loose file.
        mime = mimetypes.guess_type(coded)[0] or "application/octet-stream"
        return harden_file_response(
            _branding._ranged_bytes_response(app.response_class, raw, mime), coded)

    @app.route("/badge-thumb/<aid>.png", defaults={"ext": "png"})
    @app.route("/badge-thumb/<aid>.webp", defaults={"ext": "webp"})
    @tier(LOGIN)
    def badge_thumb(aid, ext):
        """Cached ~256px badge for the Folio of Honors tiles (masters stay the source of
        truth). Lazily generated on first hit; path-safe (no slashes via <aid>).

        TWO extensions, ONE gate. `.webp` answers the client's webp-first probe with the
        ANIMATED master passed through untouched (_badge_anim), and 404s when there is no
        animated master -- which is the normal answer for most ids, and the signal the
        chain falls back to `.png` on. Both rules land on this one view function
        deliberately: the roster/hidden-feat gate below is written once and cannot be
        half-applied to one extension, which is exactly how a second route would have
        leaked a sealed feat's art."""
        from moonglade.gallery import Path
        from flask import send_from_directory, abort
        if not aid or "/" in aid or "\\" in aid or ".." in aid:
            abort(404)
        # Achievement ids are canonically lowercase-kebab; the underlying resolve
        # is on a case-insensitive FS, so a case-variant (an upper-cased <ID>.png)
        # would otherwise skip the hidden-feat gate below (a frozenset of
        # lowercase ids) yet still read the real sealed master -- the same
        # fail-open leak _seal_rule casefolds against. Normalise once here so the
        # gate, _earned_achievement_ids, and the cache key all agree.
        aid = aid.lower()
        # Fail CLOSED, matching _seal_rule's badge branch. Only serve a thumb for
        # an id that IS in the roster; an unknown id -- OR ANY id when the roster
        # is unavailable (no/invalid container -> _ach_ids() empty) -- is denied.
        # Without this, _ach_hidden() also goes empty in that state, the hidden
        # gate below silently passes, and an unearned masked feat's master serves
        # by id (the fail-open _seal_rule was written to avoid; the parallel gate
        # here missed it -- adversarial, 2026-08-22). Visible feats' thumbs still
        # serve unearned (the Folio's locked tiles show art by design).
        if aid not in _achievements._ach_ids():
            abort(404)
        # Feats the roster marks hidden are masked in /api/achievements, but
        # their ids sit in this public source -- so an unearned masked feat's
        # badge must not be fishable by id here either.
        if aid in _achievements._ach_hidden() and aid not in _branding._earned_achievement_ids(
                out_dir, db_path, need=aid):
            abort(404)
        if ext == "webp":
            # Past the same gate the stills pass, so an unearned masked feat's
            # animation is no more fishable than its still. Served whole -- see
            # _badge_anim on why an animated master is never re-encoded here.
            raw = _achievements._badge_anim(aid)
            if raw is None:
                abort(404)             # no animated master -> the chain falls back to .png
            resp = app.response_class(raw, mimetype="image/webp")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        # The celebration toast asks for 384px so the enlarged medallion stays crisp
        # on HiDPI, and since 2026-09-07 so does the phone Folio's detail sheet, which
        # now shows the badge whole at the frame's full height; the Folio grid keeps the
        # 256 default. Allowlisted to those two so the cache can't be spammed into
        # unbounded sizes.
        size = 384 if request.args.get("size") == "384" else 256
        p = _achievements._badge_thumb(out_dir, aid, size)
        if isinstance(p, (bytes, bytearray)):
            # cache unwritable -> _badge_thumb handed us the image in memory
            resp = app.response_class(bytes(p), mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        if not p or not Path(p).is_file():
            abort(404)
        p = Path(p)
        resp = send_from_directory(str(p.parent), p.name)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/feat-mask/<token>.png")
    @tier(LOGIN)
    def feat_mask(token):
        """The veil card's silhouette: an alpha-only PNG (white on transparent) cut from the
        badge of the NEXT unfound feat, named in the URL by an opaque HMAC token
        (_feat_mask_token) that says nothing about the feat's id, name or file.

        It serves ONLY the current pick's mask. A token for any other feat, a token that is
        not one, a feat already earned (the pick has moved on) and every request made before
        a first feat is earned all answer the same bare 404, so the route is not an oracle
        for which feats exist or which is next. The pick is recomputed from a fresh earned
        set on every request -- never from the 5-second cache -- so the mask for the feat
        that became the veil a moment ago is never refused off stale state. Read-only; no
        spend and nothing written beyond the regenerable cache file."""
        from flask import abort
        if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
            abort(404)

        def has_art(aid):
            return _branding._branding_exists(_branding._role_rel("badges", aid + ".png"))

        # need="" is in no cached set, so the helper recomputes instead of answering from its
        # 5-second cache -- an earn that landed since the cache was filled is never missed.
        earned = _branding._earned_achievement_ids(out_dir, db_path, need="")
        pick = _branding._pick_masked_feat(earned, has_art=has_art)
        if pick is None:
            abort(404)
        if not hmac.compare_digest(_branding._feat_mask_token(app.secret_key, pick["id"]), token):
            abort(404)
        png = _branding._feat_mask_bytes(out_dir, pick["id"], token)
        if png is None:
            abort(404)
        resp = app.response_class(png, mimetype="image/png")
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp
    @app.route("/api/branding", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_branding():
        """The banner mark (the icon beside the title) + its animation. GET and POST both
        require login (any session, local or LAN) -- cosmetic, so any authorized device may
        read or change it, same as the rest of the LOGIN-tier settings surface.
        Persists to settings.json's branding (save_branding)."""
        if request.method == "GET":
            # Reflects a raw filesystem drop immediately, same as /api/achievements --
            # a caller reading branding state directly (this route, not the achievements
            # one) must never see a stale pre-adoption picture. Cheap; see
            # sweep_branding_drops()'s own docstring.
            try:
                _branding.sweep_branding_drops(out_dir)
            except Exception:
                pass
            cfg = _branding.load_branding(out_dir)
            return jsonify(dict(_branding._branding_tuning(cfg),
                                mark=cfg["mark"], anim=cfg["anim"],
                                anims=_branding.MARK_ANIMS,
                                marks=_branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path)),
                                slots=_branding.branding_slots_payload(out_dir),
                                roles=_branding.branding_roles_payload(out_dir)))
        body = request.get_json(silent=True) or {}
        cfg = _branding.load_branding(out_dir)
        _before = (cfg.get("mark"), cfg.get("anim"))
        _marks = _branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path))
        have = {m["id"] for m in _marks}
        if "anim" in body:
            anim = str(body["anim"])
            # A retired id is refused here rather than silently accepted: the picker
            # no longer offers one, so a POST carrying it is a stale client or a
            # hand-rolled call, and answering 400 is how it finds that out. (An
            # ALREADY-STORED retired pick is a different case -- load_branding wears
            # classic for it, so nobody's install breaks.)
            if anim not in _branding.MARK_ANIMS:
                return jsonify({"error": "unknown animation"}), 400
            cfg["anim"] = anim
        if "mark" in body:
            mark = str(body["mark"])
            if mark != "logo" and mark not in have:
                return jsonify({"error": "unknown mark"}), 400
            # Reward gate (2026-09-08): a mark bound to an achievement may be set
            # only once that achievement is earned -- the same refusal /api/skin
            # gives a locked skin, so a client can't force a locked mark. `logo`
            # and every free (unlock:"") mark pass; earned is computed above in
            # `_marks` off the shared recipe.
            locked = next((m for m in _marks
                           if m["id"] == mark and not m["earned"]), None)
            if locked is not None:
                # unlock_name is already spoiler-masked (empty while the feat is
                # masked -- see list_marks). NEVER fall back to the raw
                # unlock id: that would name the very feat the mask exists to
                # hide (feat/mark-gating spoiler audit 2026-09-08).
                return jsonify({"error": "mark locked",
                                "unlock": locked.get("unlock_name") or "",
                                "mark": cfg["mark"]}), 403
            cfg["mark"] = mark
        # The tuning fields: clamped, never refused. A slider that sends 4.0 gets
        # 3.0 back and the UI settles onto it -- an error toast for dragging too far
        # would be a worse answer than the honest ceiling.
        for k in ("anim_speed", "anim_scale", "glow_angle"):
            if k in body:
                cfg[k] = _branding._brand_num(k, body[k], cfg[k])
        if "glow_color" in body:
            colour = _branding._brand_color(body["glow_color"], None)
            if colour is None:
                return jsonify({"error": "glow_color must be #rrggbb"}), 400
            cfg["glow_color"] = colour
        _branding.save_branding(out_dir, cfg)
        if (cfg.get("mark"), cfg.get("anim")) != _before:   # Interior Decorator: a real change only
            _telemetry.telem_bump("skin_changed_runs", out_dir=out_dir)
        if cfg["anim"] == "eclipse":           # Eclipse: sun and moon in balance
            _telemetry.telem_flag("eclipse_anim_triggered", out_dir=out_dir)
        return jsonify(dict(_branding._branding_tuning(cfg),
                            mark=cfg["mark"], anim=cfg["anim"]))

    @app.route("/api/branding/slot", methods=["POST"])
    @tier(LOGIN)
    def api_branding_slot_upload():
        """Upload a new asset into one Branding slot (the three banner slots --
        Control Panel.dc.html's 'From disk' chip; the named roles have their own
        door, /api/branding/role, with a CSRF check this one predates). LOGIN tier,
        matching /api/branding just above: cosmetic, no host-filesystem risk
        beyond writing into branding/, the same machine-local git-ignored tree
        marks already live in (NOT the shortcut route's stricter local-only gate).
        Re-encodes through Pillow rather than trusting the upload's own bytes/
        extension, the same defense-in-depth this app already applies to real
        library thumbnails (see _thumb_for, above)."""
        slot = request.form.get("slot") or ""
        if slot not in _branding.BANNER_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        f = request.files.get("file")
        media_id = (request.form.get("media_id") or "").strip()
        if (f is None or not f.filename) and not media_id:
            return jsonify({"error": "no file"}), 400
        try:
            import io
            from PIL import Image
            if f is not None and f.filename:
                head = f.stream.read(64)
                f.stream.seek(0)
                _branding.guard_webp_canvas(head, _branding.BANNER_MAX_SIDE)       # before libwebp commits a declared canvas
                im = Image.open(f.stream)
            else:
                # "From the gallery..." (Control Panel.dc.html:342) -- source the asset
                # from the user's own library by media_id, via the same shared resolver
                # every other media_id->file path uses. Images only; a video id simply
                # resolves to no usable frame here.
                hits = _scan.find_files_for_media_id(out_dir, media_id)
                img_hit = next((p for p in hits if p.suffix.lower() in _scan._IMAGE_EXTS), None)
                if img_hit is None:
                    return jsonify({"error": "no local image for that media id"}), 400
                with open(img_hit, "rb") as fh:
                    _branding.guard_webp_canvas(fh.read(64), _branding.BANNER_MAX_SIDE)
                im = Image.open(img_hit)
            im.load()
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
        except _branding.ImageRefused as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        item = _branding.add_slot_asset(out_dir, slot, buf.getvalue())   # neutral transform to start
        return jsonify({"slot": slot, "item": item, "assets": _branding.list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/crop", methods=["POST"])
    @tier(LOGIN)
    def api_branding_slot_crop():
        """Update one uploaded asset's zoom/cropX/cropY transform (Control
        Panel.dc.html's three banner sliders). LOGIN tier, same as the upload
        route. Any of the three fields may be omitted to keep its stored value.
        Legacy `crop` (left/center/right) is still accepted for back-compat and
        mapped to a cropX pan. Widened 2026-08-06 from the old cycleCrop."""
        body = request.get_json(silent=True) or {}
        slot, item_id = body.get("slot"), str(body.get("id") or "")
        zoom, cropx, cropy = body.get("zoom"), body.get("cropX"), body.get("cropY")
        if zoom is None and cropx is None and cropy is None:
            legacy = {"left": 0, "center": 50, "right": 100}
            crop = str(body.get("crop") or "")
            if crop not in legacy:
                return jsonify({"error": "unknown crop value"}), 400
            cropx = legacy[crop]
        if not _branding.set_slot_crop(out_dir, slot, item_id, zoom=zoom, cropx=cropx, cropy=cropy):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"assets": _branding.list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/active", methods=["POST"])
    @tier(LOGIN)
    def api_branding_slot_active():
        """Pick which already-uploaded asset is active for a slot. LOGIN tier,
        same as the upload route. There is no "clear to none" -- see
        set_slot_active()'s own docstring for why."""
        body = request.get_json(silent=True) or {}
        slot, item_id = body.get("slot"), body.get("id")
        if not _branding.set_slot_active(out_dir, slot, str(item_id) if item_id else None):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"slots": _branding.branding_slots_payload(out_dir)})

    @app.route("/api/branding/role", methods=["POST"])
    @tier(LOGIN)
    def api_branding_role_upload():
        """Make one picture the install's override of one image of a named role (the Branding
        tab's Roles section; a hidden, unlock-gated surface). Multipart: csrf, slot (a key of
        ROLE_SLOTS), key (one of that role's images) and either `file` (From disk) or `media_id`
        (From the gallery). LOGIN tier, with the explicit CSRF token this write class carries.
        The spec is checked and the file written in branding_role_upload() -- read that, it is the
        whole path; this handler only reads the request. The cap on the request is set before the
        form is parsed, so a body far past ROLE_MAX_BYTES is a 413 and is never spooled."""
        request.max_content_length = _branding.ROLE_MAX_BYTES + 64 * 1024     # the file, plus its form fields
        if not _check_csrf(request.form):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slot = request.form.get("slot") or ""
        if slot not in _branding.ROLE_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        body, status = _branding.branding_role_upload(
            out_dir, slot, (request.form.get("key") or "").strip(),
            upload=request.files.get("file"), media_id=(request.form.get("media_id") or "").strip(),
            check_only=request.form.get("check") == "1")
        return jsonify(body), status

    @app.route("/api/branding/role/restore", methods=["POST"])
    @tier(LOGIN)
    def api_branding_role_restore():
        """Go back to the pack's default for one role image: removes the install's override
        (the one file under the coded tree) and nothing else. LOGIN tier, CSRF-checked."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slot = str(body.get("slot") or "")          # a list or dict is not hashable: coerce before the lookup
        if slot not in _branding.ROLE_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        out, status = _branding.branding_role_restore(out_dir, slot, str(body.get("key") or ""))
        return jsonify(out), status

    @app.route("/api/branding/role/default/<slot>/<key>")
    @tier(LOGIN)
    def api_branding_role_default(slot, key):
        """The pack's own art for one role image, so the Roles row can show default beside
        yours while an override is in place. Only the nine named role images are reachable
        here; the bytes come from the container alone (never the loose tree), and an image the
        pack does not carry is a plain 404."""
        from flask import abort
        import mimetypes
        img = (_branding.ROLE_SLOTS.get(slot) or {}).get("images", {}).get(key)
        if img is None:
            abort(404)
        box = _branding._get_container()
        raw = box.get(_branding._public_rel_to_coded(img["public"])) if box else None
        if raw is None:
            abort(404)
        resp = app.response_class(raw, mimetype=mimetypes.guess_type(img["public"])[0]
                                  or "application/octet-stream")
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    @app.route("/api/branding/mark/custom", methods=["POST"])
    @tier(LOGIN)
    def api_branding_mark_custom():
        """Upload The Great Library's custom mark (Control Panel.dc.html's 6th
        marks tile). LOGIN tier + a real server-side achievement check -- unlike
        the deferred banner-earned-art masking (still local-UI-only pending the
        SQLite asset-bundling project), this route actually performs a write, so
        it gets the same real gate /api/skin already applies to earned skins."""
        if not _branding._mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "The Great Library hasn't been earned yet"}), 403
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        # An uploaded WEBP is stored verbatim, everything else is re-encoded to PNG.
        # Same reasoning as the filesystem-drop path: re-encoding an animated webp
        # keeps frame one and silently throws the animation away, which would make
        # the one format the owner authors animated marks in the one format this
        # route breaks. The bytes are still validated as an image before they land.
        raw = f.read()
        is_webp = str(f.filename).lower().endswith(".webp")
        try:
            import io
            from PIL import Image
            # The same two questions every user-picture upload asks first: a WebP's declared canvas
            # from its header (libwebp commits it all when Pillow merely opens the file), and only
            # the everyday formats ever opened.
            _branding.guard_webp_canvas(raw[:64], _branding.ROLE_MAX_SIDE)
            im = Image.open(io.BytesIO(raw), formats=_branding.ROLE_OPEN_FORMATS)
            im.load()
            if is_webp:
                art = raw
            else:
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, format="PNG")
                art = buf.getvalue()
        except _branding.ImageRefused as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        mark = _branding.add_custom_mark(out_dir, art, ext=".webp" if is_webp else ".png")
        return jsonify({"mark": mark["id"], "marks": _branding.list_marks(out_dir)})

    @app.route("/api/branding/mark/custom/remove", methods=["POST"])
    @tier(LOGIN)
    def api_branding_mark_custom_remove():
        """Remove an uploaded custom mark (Control Panel.dc.html's Remove chip).
        LOGIN tier, same as the upload route above."""
        body = request.get_json(silent=True) or {}
        mark_id = str(body.get("id") or "")
        if not _branding.remove_custom_mark(out_dir, mark_id):
            return jsonify({"error": "unknown custom mark"}), 400
        cfg = _branding.load_branding(out_dir)
        return jsonify({"mark": cfg["mark"], "marks": _branding.list_marks(out_dir)})

    @app.route("/api/branding/banners/earned")
    @tier(LOGIN)
    def api_branding_banners_earned():
        """The earned-banner picks BannerEditor's locked/earned tile row renders.
        One entry today (great_library, gated on the-great-library); void_banner
        is deliberately NOT listed -- it rewards a future achievement (#57-60)
        and stays invisible until that lands. The png URL is the public role
        form and is itself seal-gated by the /branding/ route, so a locked
        banner's art can't be previewed by fetching the URL directly. LOGIN
        tier, mirroring /api/branding/mark/custom."""
        return jsonify({"banners": [{
            "id": "great_library",
            "label": "The Great Library",
            "earned": _branding._mark_earned(out_dir, db_path, "the-great-library"),
            "png": "/branding/earned_banners/great_library.png",
        }]})

    @app.route("/api/branding/banner/earned", methods=["POST"])
    @tier(LOGIN)
    def api_branding_banner_earned():
        """Apply an earned banner as the banner_main flat. Server gate is
        authoritative (the UI's locked tile is cosmetic): 403 until the
        achievement is really earned, same _mark_earned check the custom-mark
        upload runs. On success the SEALED earned_banners bytes go through the
        exact _render_banner_flat pipeline every other banner write uses
        (banner_main ratio 4:1 -> 1920x480), so the applied banner can't
        differ from an uploaded one in shape or size. The choice is stored in
        settings.json's branding.worn_banner ({"kind": "earned", "banner_id"}),
        the render beside it in the cache is stamped the same, and the ensure
        pass rebuilds it from the pack whenever the cache lacks it (B6). LOGIN
        tier, mirroring /api/branding/mark/custom."""
        body = request.get_json(silent=True)
        body = body if isinstance(body, dict) else {}   # a JSON array/string/number -> 400, not 500
        if str(body.get("id") or "") != "great_library":
            return jsonify({"error": "unknown banner"}), 400
        if not _branding._mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "banner locked"}), 403
        raw = _branding._branding_bytes(_branding._role_rel("earned_banners", "great_library.png"))
        record = {"kind": "earned", "banner_id": "great_library"}
        if raw is None or not _branding._render_banner_flat(out_dir, "banner_main", raw, record=record):
            return jsonify({"error": "banner art unavailable"}), 400
        if not _branding._set_worn_banner("banner_main", record):
            return jsonify({"error": "Couldn't save the banner choice; try again."}), 200
        return jsonify({"ok": True})

    @app.route("/api/branding/shortcut", methods=["POST"])
    @tier(LOCALHOST)
    def api_branding_shortcut():
        """Write/refresh the Desktop launcher shortcut with the chosen mark's
        .ico. A .pyw can't carry an icon; the .lnk can -- this IS the app icon.
        Machine-local action -> owner-only.

        Deliberately gated to _is_local_request(), NOT the broader
        _is_authorized_request(): this calls make_launcher_shortcut(), which
        shells out to PowerShell/WScript.Shell COM to write to the Desktop of the
        machine the SERVER process runs on -- see that function's own docstring
        ("caller must gate to localhost"). A logged-in LAN account is meant to
        unlock spend-the-owner's-credits generation features, not trigger
        PowerShell execution / filesystem writes on the host -- a materially
        different trust boundary, so this one route was NOT broadened along with
        the rest of the branding-writes group during the LAN-auth conversion
        pass (unlike GET/POST /api/branding just above, which only writes
        settings.json's branding picks -- ordinary app data, correctly broadened)."""
        body = request.get_json(silent=True) or {}
        mark = str(body.get("mark") or _branding.load_branding(out_dir)["mark"])
        # Whitelist before anything touches the shell: only a known cut mark id
        # may become an icon path (no traversal, no quoting surprises). Gated on
        # EARNED too (red team 2026-09-08): the Desktop .lnk icon IS the app's
        # real icon, so a locked reward mark's art must not become it any more
        # than it may become the active in-app mark -- the same 403 POST
        # /api/branding gives. Free/logo marks and earned bound marks pass.
        _marks = _branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path))
        if mark not in {m["id"] for m in _marks}:
            return jsonify({"error": "unknown mark (no .ico cut for it)"}), 400
        locked = next((m for m in _marks if m["id"] == mark and not m["earned"]), None)
        if locked is not None:
            # Masked name only, never the raw unlock id -- a masked feat's
            # id must not leak through the shortcut 403 either (spoiler audit).
            return jsonify({"error": "mark locked",
                            "unlock": locked.get("unlock_name") or ""}), 403
        try:
            lnk = _branding.make_launcher_shortcut(out_dir, mark)
        except RuntimeError as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 400
        return jsonify({"ok": True, "lnk": lnk})

    # -- provided to ctx (split_move) --
    # -- end --

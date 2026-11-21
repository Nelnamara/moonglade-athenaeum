"""moonglade/routes_mirror.py -- the Mirror's routes ("Mirror to PixAI website"): its status, the
switch, Disconnect, the one-click Connect (this machine's browser sign-in, then a due renewal),
the Connect from PixAI window and the sign-in it hands over, with the account check both Connect
roads share.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was, after the achievement routes. Names the block reads
from create_app's setup and the front door (the CSRF check, the local-request check, the page
nonce, the host-path redactor and the Connect from PixAI page) come in through ctx (the
bound-from-ctx lines below), so every closure on both sides holds the one same object. The
sign-in, its renewal and the switch stay in moonglade.mirror and moonglade.settings, read through
those modules as before; gallery's own names are imported inside the function that reads them, at
call time, so a test's patch of moonglade.gallery still reaches the route.
"""
import secrets

from flask import jsonify, render_template_string, request, session

from moonglade import mirror as _mirror
from moonglade import settings as _settings


def register(app, ctx):
    from moonglade.web_tiers import LOCALHOST, LOGIN, tier
    # -- bound from ctx (split_move) --
    MIRROR_CONNECT_PAGE = ctx.MIRROR_CONNECT_PAGE
    _check_csrf = ctx._check_csrf
    _is_local_request = ctx._is_local_request
    _noncify = ctx._noncify
    _redact_host_paths = ctx._redact_host_paths
    # -- end --

    @app.route("/api/mirror/status")
    @tier(LOGIN)
    def api_mirror_status():
        """Read-only status of 'Mirror to PixAI website': the toggle flag + the stored
        JWT's days-left, decoded OFFLINE (no network). NEVER returns the token (review
        F13). LOGIN tier.

        #71 adds what the ring is drawn from: `left_s` / `span_s` (core.mirror_token_span --
        the token's own life, never iat to exp) and `renewal` (core.mirror_renewal_status: ok,
        failed, paused, expired, off), so the tile warns only when a renewal actually failed
        or cannot run, not whenever the token sits in its normal renewal window."""
        from moonglade import backup as core
        state = _mirror.load_mirror_state()
        jwt = (state.get("jwt") or "")
        left_s, span_s = _mirror.mirror_token_span(state)
        return jsonify({"enabled": _mirror.mirror_enabled(), "connected": bool(jwt),
                        "days_left": _mirror.jwt_days_left(jwt) if jwt else None,
                        "left_s": int(left_s) if left_s is not None else None,
                        "span_s": int(span_s) if span_s is not None else None,
                        "renewal": _mirror.mirror_renewal_status()})

    @app.route("/api/mirror/enable", methods=["POST"])
    @tier(LOCALHOST)
    def api_mirror_enable():
        """Set the "Mirror to PixAI website" switch (settings.json's mirror_to_pixai).
        LOCALHOST-ONLY: it decides which credential rides the owner's every generation, so it
        is in the same trust class as /api/setup/save-key and /api/branding/shortcut -- a
        logged-in LAN session must not be able to flip the owner's every generation onto the
        browser JWT. settings.json is written whole under its own lock (moonglade.settings)."""
        from moonglade import backup as core
        want = bool((request.get_json(silent=True) or {}).get("enabled"))
        # [MAJOR] Only ARM (true-write) when a usable browser JWT actually exists: arming the
        # mirror with no live session lets every Bridge/enhance submit hit the mirror-ON gate,
        # fail make_mirror_session(), and refuse -- an armed toggle that can run nothing. The
        # DISARM (false-write) is always allowed, so the owner can always turn it back off.
        if want and not _mirror._jwt_usable(_mirror.load_mirror_state().get("jwt") or ""):
            return jsonify({"error": "Connect the mirror first — not armed",
                            "enabled": False}), 200
        try:
            _settings.set_values(**{_settings.MIRROR_TO_PIXAI: want})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
        return jsonify({"enabled": want})

    @app.route("/api/mirror/disconnect", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_disconnect():
        """The Mirror tile's Disconnect (app security review 2026-11-19, finding 7): forget the
        stored PixAI sign-in and stop renewing it (mirror.disconnect_mirror), and turn the
        switch off, since an armed Mirror with no sign-in refuses every create. LOGIN tier, a
        client on this machine or a private home network (mirror.home_network_address), the
        same reach as Connect from PixAI; the session's CSRF token. Body {csrf}. Answers ok, or
        a plain sentence; the sign-in is never read back."""
        if not _mirror.home_network_address(request.remote_addr):
            return jsonify({"ok": False, "error": _mirror.SITE_TOKEN_NOT_HOME}), 403
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        if not _mirror.disconnect_mirror():
            return jsonify({"error": "Moonglade couldn't delete the stored PixAI sign-in. "
                                     "Close anything that has its local folder open, then "
                                     "try again."}), 200
        try:
            if _mirror.mirror_enabled():
                _settings.set_values(**{_settings.MIRROR_TO_PIXAI: False})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"ok": True, "enabled": True,
                            "error": "The sign-in is gone, but the switch couldn't be turned "
                                     "off: " + _redact_host_paths(str(e))[:160]}), 200
        return jsonify({"ok": True, "enabled": False})

    def _connect_api_key_account():
        # The account the API key REALLY is, asked of PixAI every time: a USER_ID pinned
        # in config.json is a legacy override and must not decide whose sign-in is kept.
        from moonglade import backup as core
        s = core._make_session(None, resolve_user=False)
        try:
            return core.resolve_user_id(s)
        except core.PixAIAuthError:
            # PixAI refuses the key and no usable sign-in could answer for it (2026-11-19):
            # the account the STORED sign-in names, expired or not, is one this key was
            # already confirmed to be when that sign-in was connected. None stored: refuse.
            old = _mirror.load_mirror_state().get("jwt") or ""
            return str(_mirror.jwt_claims(old).get("sub") or "") if old else ""

    # One-click Connect (back 2026-11-19): read the pixai.art sign-in from THIS machine's
    # Chrome/Edge/Brave. The one thing the 3.20.7 route lacked is added: the token's `sub`
    # must be the account the API key resolves to (mirror.accept_site_token), so a browser
    # signed in as someone else is refused and nothing is stored.
    @app.route("/api/mirror/connect", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_connect():
        """Connect: read the pixai.art sign-in from this machine's browser, check it is the
        API key's own account, store it, run a due renewal. Answers only ok + days left, or a
        fixed plain sentence -- never the token, a claim or the account id. No credential
        crosses the network: the server reads its own local browser store. LOGIN tier, the
        session's CSRF token (body {csrf})."""
        from moonglade import backup as core
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not _check_csrf(body):
            return jsonify({"ok": False, "error": "Your session expired. Reload the page and "
                            "try again."}), 400
        try:
            core._check_read_only("connect the PixAI mirror")   # the renewal is account-mutating
        except Exception as e:                          # noqa: BLE001
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:160]}), 200
        try:
            bj = _mirror.read_browser_jwt()
        except Exception:                               # noqa: BLE001 -- the reader never raises
            bj = None
        if not bj:
            return jsonify({"ok": False, "error": "Couldn't read a pixai.art session from a "
                            "browser on this machine. Sign in to pixai.art in Chrome/Edge/Brave "
                            "(reload the page once so the token is written), then try again, "
                            "or use the Connect from PixAI bookmark."}), 200
        out = _mirror.accept_site_token(bj, _connect_api_key_account)
        if not out.get("ok"):
            return jsonify({"ok": False, "error": out.get("error") or "Not connected."}), 200
        try:
            _mirror.make_mirror_session(user_initiated=True)   # a due renewal, as before
        except Exception:                               # noqa: BLE001
            pass
        jwt = _mirror.load_mirror_state().get("jwt") or ""
        return jsonify({"ok": bool(jwt),
                        "days_left": _mirror.jwt_days_left(jwt) if jwt else None})

    @app.route("/mirror/connect")
    @tier(LOGIN)
    def mirror_connect_page():
        """The window the Control Panel's "Connect from PixAI" bookmark opens from a pixai.art
        tab. It tells its opener it is ready (to https://pixai.art only), takes the sign-in
        back only from that exact origin and that window, and hands it to
        /api/mirror/connect-token with this session's CSRF token. Login-gated like every page:
        a signed-out visitor goes through /login and lands back here, still the opener's
        window. Dressed in the login card's own classes -- no new design. Holds no credential
        itself; the page is marked no-store all the same."""
        from moonglade.pages import DESIGN_TOKENS_CSS
        session.setdefault("csrf", secrets.token_hex(16))
        resp = app.response_class(render_template_string(
            _noncify(MIRROR_CONNECT_PAGE.replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS)),
            boot={"csrf": session["csrf"]}), mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.route("/api/mirror/connect-token", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_connect_token():
        """Connect from PixAI: store the sign-in the user's own pixai.art tab handed over
        (body {csrf, token}). LOGIN tier, a client on this machine or a private home network
        (mirror.home_network_address) -- over HTTPS unless it is this machine -- the session's
        CSRF token, and a same-origin request
        only (an Origin header naming another site is refused). READ_ONLY refuses,
        as Connect always has. Then mirror.accept_site_token checks the token -- a PixAI JWT,
        unexpired, and for the SAME PixAI account the API key resolves to -- before storing
        it. Answers only ok + days left, or a plain sentence; never the token, a claim or the
        account id, and nothing here logs."""
        # Home network only (2026-11-18): never accept a sign-in from outside a home network.
        # Same client address the localhost-only checks read (request.remote_addr, the real
        # TCP peer; no forwarded header is trusted anywhere in this app).
        from moonglade.web_policy import CONNECT_TOKEN_NEEDS_HTTPS
        if not _mirror.home_network_address(request.remote_addr):
            return jsonify({"ok": False, "error": _mirror.SITE_TOKEN_NOT_HOME}), 403
        # And from another device, only over HTTPS (app security review 2026-11-19, finding
        # 1): a PixAI sign-in posted over plain http:// crosses the network readable by anyone
        # on it, and renews itself for whoever holds it. This PC's own loopback never leaves
        # the PC, so it may stay plain. Checked before the body is read.
        if not request.is_secure and not _is_local_request():
            return jsonify({"ok": False, "error": CONNECT_TOKEN_NEEDS_HTTPS}), 403
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"ok": False, "error": "That request didn't come from this "
                            "Moonglade page, so nothing was saved."}), 403
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not _check_csrf(body):
            return jsonify({"ok": False, "error": "Your session expired. Reload the page and "
                            "try again."}), 400
        from moonglade import backup as core
        try:
            core._check_read_only("connect the PixAI mirror")
        except Exception as e:                          # noqa: BLE001
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:160]}), 200

        out = _mirror.accept_site_token(body.get("token"), _connect_api_key_account)
        if out.get("ok"):
            return jsonify({"ok": True, "days_left": out.get("days_left")})
        return jsonify({"ok": False, "error": out.get("error") or "Not connected."}), 200

    # -- provided to ctx (split_move) --
    # -- end --

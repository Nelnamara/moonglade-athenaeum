"""moonglade/routes_gate.py -- the gallery's front door and its security core: the sign-in
routes (/login, /api/login, /api/logout) with the session they establish and the per-address
lockout, the request hooks (the unknown-host refusal, the default-deny front door, the plain-LAN
redirect to HTTPS, the cross-origin write refusal, the protective headers and CSP, the 413
refusal, gzip, the code-asset no-cache and the server mark), the CSRF check, the local-request and
authorized-request tests, the PixAI session and entitlements helpers, the reference-upload cache,
the beacon identity, and the page shells with the routes that serve them (/ and /next/assets).

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, first, so every hook registers in its original relative order and every
other family reads these names from the one object. Names the block reads from create_app's
setup come in through ctx (the bound-from-ctx lines below), and the names other code reads back go
out through ctx (the provided-to-ctx lines at the end), so every closure on both sides holds the
one same object. gallery's own names are imported inside the function that reads them, at call
time, so a test's patch of moonglade.gallery still reaches the route.
"""
import secrets
import threading
import time

from flask import g as _flask_g
from flask import (jsonify, redirect, render_template_string, request, send_from_directory, session,
                   url_for)

from moonglade import assets as moonglade_assets
from moonglade import branding as _branding
from moonglade import hostcheck as _hostcheck
from moonglade import paths as _paths
from moonglade import settings as _settings
from moonglade import web_sessions as _web_sessions


def register(app, ctx):
    from moonglade.pages import _AUTH_401_GUARD_JS, _PREPAINT_BOOT_JS
    from moonglade.web_tiers import LOGIN, PUBLIC, tier
    # -- bound from ctx (split_move) --
    build_stamp = ctx.build_stamp
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    # Redacts THIS MACHINE's own filesystem paths out of an exception message before
    # it's stored or served to any LOGIN-tier caller (any signed-in LAN account, not
    # just the owner) -- str(e) on a file-not-found, permission, or upstream-API error
    # routinely embeds an absolute path, which routinely embeds the OS username.
    #
    # Literal-PREFIX replacement, NOT a regex. An earlier attempt (2026-07-21, docs/
    # the 2026-07-21 audit's S3) used a regex (`[^\s'"<>\|]*`) that stopped matching at
    # the first whitespace, so a spaced Windows username (`C:\Users\John Smith\...`)
    # still leaked in full -- exactly the harm this exists to close -- and its own
    # tests used space-free paths, so they'd have shipped green. This re-spin is
    # tested against a spaced username specifically because of that history.
    #
    # Longest-candidate-first: home/cwd/tmp/out_dir routinely nest inside one another
    # (out_dir is very often somewhere under the home directory), so matching the
    # LONGEST real path first replaces the whole thing with one tag -- matching a
    # shorter ancestor first would leave the more specific, still-identifying suffix
    # (out_dir's own folder name) sitting right after the placeholder.
    #
    # Bounds CONTENT, not size -- pairs with append_job_event's existing [:200] cap
    # (SIZE only) and every jsonify site's own [:N] slice; this must run BEFORE those
    # slices, not after, or a redaction landing past the cutoff never happens.
    def _redact_host_paths(msg):
        # Delegates to the one module-level copy (see _redact_host_paths_cli:
        # the closure and the module function were maintained as twins until
        # 2026-08-14, when issue #14's fix collapsed them).
        from moonglade.redact import _redact_host_paths_cli
        return _redact_host_paths_cli(out_dir, msg)

    @app.context_processor
    def _inject_branding():
        # mark_url / mark_anim / mark_kind on every page render, so the chosen
        # banner mark + its animation apply to the gallery, panel, health, dupes.
        return _branding.brand_context(out_dir)

    # catalog media_id -> upload-kind media_id, for references sent from the gallery.
    # PixAI refuses a generation-output id as an input (see resolve_img), so each
    # referenced image is uploaded once and reused. Process-lifetime only and
    # deliberately unbounded-but-tiny: one short string pair per image the owner has
    # ever referenced this run. Losing it on restart just re-uploads, which is free.
    _ref_upload_cache = {}
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_next(url):
        """Only ever redirect to a same-site PATH after login -- ?next=https://evil.example
        or ?next=//evil.example (scheme-relative) must never be honored, or /login becomes
        an open redirect. A bare local path ('/loom', '/export-csv', ...) is the only
        shape every caller of this actually needs (redirect(url_for('login', next=request.path))
        is the only producer of a real `next`).

        Also rejects any embedded TAB/CR/LF control characters, not just a leading "//":
        Werkzeug's own Response.get_wsgi_headers() strips those control characters back out
        of a Location header value before writing it to the socket (via iri_to_uri), so a
        value like "/<TAB>/evil.example" sails past the plain "//" prefix check here yet
        gets rewritten by Werkzeug itself into a literal "//evil.example" scheme-relative
        redirect -- confirmed against the installed Flask/Werkzeug via a throwaway
        reproduction. The CR/LF variants don't even get that far: redirect() raises an
        unhandled ValueError ("Header values must not contain newline characters") instead,
        turning a real login into a 500. Regression -- see
        dev/tests/test_web_auth.py's safe-next tests."""
        _UNSAFE_NEXT_CHARS = ("\\", "\t", "\r", "\n")
        if (url and url.startswith("/") and not url.startswith("//")
                and not any(c in url for c in _UNSAFE_NEXT_CHARS)):
            return url
        return None

    def _establish_session(username):
        """Populate a freshly-authenticated session for `username` -- the ONE place
        that decides what "you are now logged in" means, shared by BOTH a normal
        /login credential POST and the local-only first-account bootstrap POST
        below (factored out so the two paths can never drift apart on what a
        session looks like)."""
        from moonglade import backup as core
        session.clear()
        session["user"] = username
        session["sess_epoch"] = core.get_web_user_session_epoch(username)
        session["csrf"] = secrets.token_hex(16)
        # This session's own id, and when it was made (finding 6): Log Out ends exactly this
        # id (moonglade.web_sessions), and the gate refuses it SESSION_ABSOLUTE_LIFETIME_S
        # after `born`, however often it is used.
        session["sid"] = secrets.token_urlsafe(18)
        session["born"] = int(time.time())
        session.permanent = True

    @app.route("/login")
    @tier(PUBLIC)
    def login():
        """The sign-in page: serves the React shell (LoginPage.jsx) for EVERY request,
        including from the server's own machine -- there is no localhost bypass (see
        _is_authorized_request() above). GET-ONLY since the classic cut (2026-08-08):
        the real submit is POST /api/login (JSON; sign-in AND local-only first-run
        account creation, with the lockout/CSRF/bootstrap enforcement + its own test
        suite). The classic FORM POST branch and LOGIN_HTML died with the cut -- a
        stale pre-cut tab replaying a form POST now gets a 405 and a reload lands
        here. LoginPage.jsx renders one of three states off the boot flags below:
        sign-in (an account exists), local bootstrap-create (no_accounts + is_local),
        or the LAN-first-run safety message (no_accounts + NOT is_local)."""
        from moonglade.pages import DESIGN_TOKENS_CSS
        next_url = _safe_next(request.values.get("next", "")) or ""
        from moonglade import backup as core
        no_accounts = not core.list_web_users()
        is_local = _is_local_request()
        # setdefault, NEVER a fresh mint on GET: the front door redirects every
        # unauthenticated request here including the browser's own incidental asset
        # GETs (favicon, apple-touch-icon, ...) -- an unconditional mint orphaned the
        # token the visible page already held ("Your session expired" on every submit,
        # reproduced). Failed POSTs rotate the token in /api/login instead.
        session.setdefault("csrf", secrets.token_hex(16))
        brand = _branding.brand_context(out_dir)
        boot = {
            "authenticated": False,
            "csrf": session["csrf"],
            "no_accounts": no_accounts,
            "is_local": is_local,
            "next": next_url,
            "build_stamp": build_stamp,
            "mark_url": brand.get("mark_url") or "/branding/logo.png",
            "mark_anim": brand.get("mark_anim") or "classic",
            "mark_kind": brand.get("mark_kind") or "",
            # The animation tuning rides with the pick it tunes -- one payload, so
            # the header can never paint the right treatment at the wrong speed.
            "anim_speed": brand.get("anim_speed", 1.0),
            "anim_scale": brand.get("anim_scale", 1.0),
            "glow_color": brand.get("glow_color") or "#94e2d5",
            "glow_angle": brand.get("glow_angle", 0.0),
        }
        return render_template_string(
            _noncify(LOGIN_PAGE.replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS)),
            boot=boot)

    @app.route("/api/login", methods=["POST"])
    @tier(PUBLIC)
    def api_login():
        """JSON sign-in AND first-run account creation for the React Login page
        (2026-08-02) -- moonglade-internal/DECISIONS.md's 2026-07-31 feasibility map called
        this out explicitly: 'A SPA needs real POST /api/login -> JSON... before
        auth can be driven from React at all.' Public (@tier(PUBLIC)) -- an
        unauthenticated caller is exactly who needs to reach this.

        mode="create" (added once design_handoff/request-bootstrap-account-creation.md
        came back with a real spec) mirrors classic login()'s own bootstrap POST
        branch exactly -- same bootstrap_mode gate (no_accounts AND is_local,
        re-checked here independent of what GET rendered, so a hand-crafted
        mode=create POST from a non-local address or after the first account
        already exists is refused server-side regardless of client state), same
        core.username_problem/password_problem/add_or_update_web_user. Every
        other branch (lockout, CSRF, plain sign-in, error strings) is identical
        to before this existed -- shares _login_seconds_locked/_login_try_acquire/
        _login_clear (one IP-keyed counter for both modes), _establish_session,
        _safe_next. Errors are the identical generic strings login() gives, on
        purpose -- never which field was wrong for a sign-in attempt, and this
        and the classic form must never be distinguishable to an attacker by
        their error text."""
        body = request.get_json(silent=True) or {}
        from moonglade import backup as core

        def _fail(error):
            # Every failed POST rotates the session token, exactly like classic
            # login()'s POST branch ("a consumed/known-bad token must never stay
            # silently resubmittable" -- guarded there by test_web_auth.py's
            # rotation test; this route's missing rotation was found by the
            # 2026-08-07 /api/login test port). Unlike the classic form, which
            # re-renders with the fresh token embedded, a SPA holds its token in
            # JS -- so the fresh one rides back in the error payload for the
            # login page to adopt on the next attempt.
            session["csrf"] = secrets.token_hex(16)
            return jsonify({"error": error, "csrf": session["csrf"]})

        next_url = _safe_next(str(body.get("next") or "")) or ""
        no_accounts = not core.list_web_users()
        bootstrap_mode = no_accounts and _is_local_request()
        wants_create = body.get("mode") == "create"
        ip = _client_ip()
        locked_for = _login_seconds_locked(ip)
        if locked_for is not None:
            mins = max(1, (locked_for + 59) // 60)
            return _fail("Too many failed attempts from this address. "
                         "Try again in about {} minute{}.".format(
                             mins, "" if mins == 1 else "s"))
        if not _check_csrf(body):
            return _fail("Your session expired. Reload the page and try again.")
        if wants_create and not bootstrap_mode:
            # Same defense-in-depth as classic login()'s identical check: a
            # mode=create POST is only ever honored while bootstrap_mode is
            # true for THIS request, never inferred from CSRF validity alone.
            error = ("No account has been set up yet. Ask whoever runs this "
                    "server to sign in from the machine itself first.") if no_accounts \
                    else "Invalid username or password."
            return _fail(error)
        relocked_for = _login_try_acquire(ip)
        if relocked_for is not None:
            mins = max(1, (relocked_for + 59) // 60)
            return _fail("Too many failed attempts from this address. "
                         "Try again in about {} minute{}.".format(
                             mins, "" if mins == 1 else "s"))
        if wants_create:
            # bootstrap_mode is guaranteed True here -- the guard above already
            # rejected wants_create whenever it's False.
            username = str(body.get("username") or "").strip()
            password = str(body.get("password") or "")
            confirm = str(body.get("confirm") or "")
            un_problem = core.username_problem(username)
            pw_problem = core.password_problem(password)
            if un_problem:
                return _fail(un_problem)
            if pw_problem:
                return _fail(pw_problem)
            if password != confirm:
                return _fail("Passwords do not match.")
            core.add_or_update_web_user(username, password)
            _login_clear(ip)
            _establish_session(username)
            return jsonify({"ok": True, "next": next_url or "/"})
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if username and core.verify_web_user(username, password):
            _login_clear(ip)
            _establish_session(username)
            return jsonify({"ok": True, "next": next_url or "/"})
        error = "Invalid username or password."
        # Same "just tripped the lockout" report login()'s own POST branch
        # gives -- see that comment for why this can't just be inferred from
        # _login_try_acquire's own return value (it deliberately let THIS
        # attempt through so a correct 5th-try password still works).
        just_locked = _login_seconds_locked(ip)
        if just_locked is not None:
            mins = max(1, (just_locked + 59) // 60)
            error = ("Too many failed attempts from this address. "
                     "Try again in about {} minute{}.".format(mins, "" if mins == 1 else "s"))
        return _fail(error)

    # Served by logout() in place of a redirect -- see its own comment for why a
    # real page (not a 3xx) is required to run the Cache Storage purge. Static, no
    # Jinja/user input involved, so a plain string is safer than round-tripping it
    # through render_template_string for nothing.
    @app.route("/api/logout", methods=["POST"])
    @tier(PUBLIC)
    def api_logout():
        """JSON sign-out for the React app (2026-08-02), POST only -- the one sign-out
        surface since the classic cut removed /logout.

        WHICH DEVICES IT REACHES (#70, owner 2026-10-02: "We should not be logging out
        all sessions. This is a LAN app, not internet."). Log Out signs out the device
        it was pressed on and nothing else: `session.clear()`, no epoch bump. Signing
        out EVERY device -- the move for a lost phone or a session you think was
        captured -- is its own explicit request, `scope: "everywhere"`, which bumps the
        account's session epoch (core.bump_web_user_session_epoch) so every outstanding
        cookie for it stops working. Only that exact word reaches the other devices; a
        missing, older ("this-device") or unknown scope is an ordinary Log Out. The
        Accounts window's "Sign out all devices" sends "everywhere"; changing your password
        in Panel -> Users bumps the same epoch and keeps the device you changed it from.
        Either way the session that asked is recorded as signed out server-side (its `sid`,
        moonglade.web_sessions), so a copied cookie for it stops working at once.

        A sign-out that would revoke checks the session's CSRF token first, and a bad
        token is a loud 400 that leaves the session intact. Public (@tier(PUBLIC)): an
        already-dead cookie must still be able to shed itself locally with no valid
        session to check a CSRF token against -- "fail toward MORE cleanup, never less"
        -- so this skips the CSRF check entirely (not just downgrades it) whenever
        `authorized` is false, and a dead cookie can never revoke anything.

        No HTML page to run the Cache Storage purge from this time -- the
        caller (React) does that purge itself in JS on a successful response,
        then navigates to /login. See LoginPage.jsx / App.jsx's logout
        handler."""
        from moonglade.web_policy import SESSION_ABSOLUTE_LIFETIME_S
        from moonglade import backup as core
        body = request.get_json(silent=True) or {}
        user = session.get("user")
        # ORDER MATTERS, same as logout(): read `user` before any call that
        # might clear the session.
        authorized = bool(user) and _is_authorized_request()
        if authorized:
            if not _check_csrf(body):
                return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
            if body.get("scope") == "everywhere":
                core.bump_web_user_session_epoch(user)
            # Server-side, this session only (finding 6): its id is recorded as signed out,
            # so a copy of this cookie taken before the Log Out stops working too. A dead
            # cookie never gets here (`authorized`), so it can record nothing.
            _web_sessions.sign_out(session.get("sid"), session.get("born"),
                                   SESSION_ABSOLUTE_LIFETIME_S)
        session.clear()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # THE front door: DEFAULT-DENY for every request, enforced in one place.
    # ------------------------------------------------------------------
    # Routes whose contract is JSON, not an HTML page -- these get a JSON 401
    # instead of a login redirect, so a fetch(...).then(r => r.json()) caller
    # still gets parseable JSON instead of choking on the login page's HTML.
    # ONE prefix since the classic cut (2026-08-08): the two legacy non-/api/
    # JSON routes (/rate/<id>, /edit-prompt/<id>) were renamed under /api/.
    # This selects the SHAPE of a refusal, never whether to refuse -- that is
    # the route's own @tier declaration, and this list must never grow into a
    # second, parallel one.
    _JSON_GATE_PREFIXES = ("/api/",)

    @app.before_request
    def _refuse_unknown_host():
        """The DNS-rebinding guard (moonglade/hostcheck.py): a request whose Host header names
        something that is not this machine is refused with 421 before ANY route runs -- the
        public tier included, because the first-account form on /login is exactly what a
        rebinding page would reach. Registered before _enforce_front_door so it runs first.
        IP literals, localhost, this PC's hostname (bare and .local), the advertised Bonjour
        name and settings.json's allowed_hosts all pass; see hostcheck for why that is safe."""
        from moonglade.gallery import _SERVER_CONTROL
        header = request.environ.get("HTTP_HOST", "")
        try:
            extra = list(_settings.allowed_hosts())
            from moonglade.bonjour import hostname_label as _bonjour_label
            extra.append(_bonjour_label(_settings.server()["bonjour_name"]) + ".local")
            adv = _SERVER_CONTROL.get("bonjour")
            if adv is not None and getattr(adv, "hostname", None):
                extra.append(adv.hostname)
        except Exception:                    # noqa: BLE001 -- a settings hiccup narrows, never widens
            extra = []
        if _hostcheck.allowed(header, extra):
            return None
        if request.path.startswith(_JSON_GATE_PREFIXES):
            return jsonify({"error": _hostcheck.REFUSED_WORDS}), _hostcheck.REFUSED_STATUS
        return (_hostcheck.REFUSED_WORDS, _hostcheck.REFUSED_STATUS,
                {"Content-Type": "text/plain; charset=utf-8"})

    @app.before_request
    def _enforce_front_door():
        """THE gate: every request is refused unless its route's own @tier
        declaration lets it through.

        The tier is read off the view function (see tier() / route_tier()), so
        this hook holds NO list of paths. It used to hold two -- _PUBLIC_PATHS
        and _PUBLIC_PREFIXES -- which were the public tier written a second
        time, in a second place, keyed on a string prefix rather than on the
        route. Those are now `@tier(PUBLIC)` on login / api_login / api_logout /
        branding / next_assets, and mean exactly what they meant before:
        /branding/ is public because it is static drop-in art (logo, marks,
        mascots, banners) with traversal already rejected in branding(), and the
        login page every unauthenticated visitor sees has to render it; the
        /next/assets/ bundle is public for the same reason -- LoginPage.jsx's
        own compiled CSS/JS, no user data, no catalog, no credential. /static/ is
        NOT in that set: the login page never loads anything from it, and `static`
        stays LOGIN.

        Three tiers, one place:
          PUBLIC    -> through, no session needed.
          LOGIN     -> _is_authorized_request() (a logged-in session ONLY -- no
                       localhost bypass, see that function's docstring further
                       down).
          LOCALHOST -> that same session check AND _is_local_request().

        The LOCALHOST arm is what changed on 2026-08-23. It used to be absent:
        this hook only ever asked "is the session valid?", so it passed a
        logged-in LAN device straight through, and each localhost-only handler
        opened with its own hand-written `if not _is_local_request(): return
        jsonify({"error": "localhost-only"}), 403`. Nothing structural kept
        those there -- the check was silently deleted from api_panel_cancel and
        api_panel_schedule (commit 0fd8cee) and never written at all in
        api_setup_save_key, while all three docstrings went on claiming
        "localhost-only". The refusal body is unchanged (same status, same JSON,
        same wording, including the three routes that say something more
        specific via `message=`); it is only issued from one place now.

        A route whose localhost requirement depends on its ARGUMENTS keeps its
        own conditional check, because that is not a tier: /api/panel/run
        demands loopback only for a destructive action (14 of the 20
        PANEL_ACTIONS are not, and a LAN account may run every one of them),
        and /api/users/remove and /api/users/password only for an account that
        is not the caller's own. Those declare the floor the gate can enforce.

        This hook replaced 43 individual, easy-to-forget
        `if not _is_authorized_request(): ...` blocks that used to sit
        one-per-route (see CHANGELOG.md for the full list) with one place that
        can't be skipped when a new route is added later -- exactly the gap a
        prior adversarial review flagged: `/`, `/image/<id>`, `/delete/<id>`,
        `/delete-bulk`, `/rate/<id>`, `/edit-prompt/<id>`, `/collection-add`,
        `/collection-remove`, `/bulk-replace-prompt`, `/panel`, `/duplicates`,
        `/health`, the raw asset routes (`/thumbs/`, `/img/`, `/video-file/`,
        `/full/`, `/badge-thumb/`, `/contact-sheet`), `/export-zip`,
        `/manifest.webmanifest`, `/sw.js`, and `/api/gallery-images`,
        `/api/similar`, `/api/collections`, `/api/contests`,
        `/api/achievements`, `/api/skin`, `/api/ach-event`, `/api/your-art`,
        `/api/loom/export-status`, `/api/loom/export-file`, `/api/ping` had NO
        auth check of any kind before this hook existed."""
        from moonglade.web_tiers import LOCALHOST, LOGIN, PUBLIC, route_tier, route_tier_message
        view = app.view_functions.get(request.endpoint or "")
        # No rule matched (a 404 in waiting), so there is no declaration to
        # read. Gate it as LOGIN, exactly as the old path-prefix version did:
        # an anonymous caller gets the login redirect, not a 404 that maps the
        # app for them. A REGISTERED route can never land here -- create_app
        # refuses to return an app with an undeclared rule.
        level = route_tier(view, request.method) if view is not None else LOGIN
        if level is None:
            level = LOGIN
        if level == PUBLIC:
            return None
        if not _is_authorized_request():
            if request.path.startswith(_JSON_GATE_PREFIXES):
                return jsonify({"error": "authentication required"}), 401
            # Keep the query too (?page=, ?image=) so a logged-out hit to a deep link lands
            # THERE after login, not on page 1 (#32). request.path is path-only; full_path
            # keeps the query -- mirrors the client-side guard (location.pathname+search).
            # _safe_next still screens it: a same-site single-'/' path, and the query is
            # percent-encoded so no raw control chars slip through. full_path appends a bare
            # '?' when there's no query, so fall back to path then to avoid the ugly "/?".
            _next = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=_safe_next(_next) or ""))
        if level == LOCALHOST and not _is_local_request():
            return jsonify({"error": route_tier_message(view)}), 403
        return None

    # ------------------------------------------------------------------
    # The request gate's two transport rules (app security review 2026-11-19). Each is its own
    # before_request hook, kept apart from _enforce_front_door (who may reach a route) on
    # purpose: these decide whether a request is ALLOWED TO ARRIVE THE WAY IT DID.
    # ------------------------------------------------------------------
    def _send_plain_lan_visits_to_https():
        """Finding 1: once the server speaks HTTPS (moonglade.tls), a plain-HTTP visit from
        another device is sent to the https:// address -- a GET or HEAD by a temporary
        redirect (never a cached one: a later start without HTTPS must not be redirected by the
        browser's memory), anything else refused with a sentence naming the address. This PC's
        own loopback keeps plain HTTP in the default mode (TLS_LAN); --https (TLS_ALL) sends
        every plain visit over. Runs FIRST, ahead of the front door, so a visitor's very first
        hop is already to https."""
        from moonglade.web_policy import PLAIN_HTTP_REFUSED
        mode = app.config.get("MG_TLS_MODE") or "off"
        if mode not in ("lan", "all") or request.is_secure:
            return None
        if mode == "lan" and _is_local_request():
            return None
        home = "https://" + request.host + "/"
        if request.method in ("GET", "HEAD"):
            target = "https://" + request.host + (
                request.full_path if request.query_string else request.path)
            return redirect(target, code=307)
        msg = PLAIN_HTTP_REFUSED.format(url=home)
        if request.path.startswith(_JSON_GATE_PREFIXES):
            return jsonify({"error": msg}), 403
        return app.response_class(msg, status=403, mimetype="text/plain")

    app.before_request_funcs.setdefault(None, []).insert(0, _send_plain_lan_visits_to_https)

    @app.before_request
    def _refuse_cross_origin_writes():
        """Finding 2: ONE front-door check for every state-changing request. A POST, PUT,
        PATCH or DELETE passes only when it comes from one of this server's own pages: its
        Origin header (else its Referer) names this request's own scheme, host and port, and
        a Sec-Fetch-Site header, when the browser sends one, says same-origin
        (same_origin_write). A page on another port of this PC (the D: install on 5757, a dev
        server, any other local web app) is same-SITE, so the Lax session cookie rides its
        requests -- and is refused here, before any route reads its body. Routes that check
        the explicit CSRF token still do, after this.

        A request carrying none of those three headers is not from a browser (a browser
        sends Origin on every POST and Sec-Fetch-Site on every request), so there is no
        ambient cookie to abuse and it passes to the route's own checks."""
        from moonglade.web_policy import CROSS_ORIGIN_REFUSED, same_origin_write
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        h = request.headers
        if same_origin_write(h.get("Origin"), h.get("Referer"), h.get("Sec-Fetch-Site"),
                             request.scheme, request.host):
            return None
        if request.path.startswith(_JSON_GATE_PREFIXES):
            return jsonify({"error": CROSS_ORIGIN_REFUSED}), 403
        return app.response_class(CROSS_ORIGIN_REFUSED, status=403, mimetype="text/plain")

    def _csp_nonce():
        """This response's script nonce, made on first use (one per request)."""
        n = getattr(_flask_g, "mg_csp_nonce", None)
        if not n:
            n = _flask_g.mg_csp_nonce = secrets.token_urlsafe(18)
        return n

    def _noncify(page_source):
        """A page TEMPLATE with its __CSP_NONCE__ marks filled in. Applied to the template's
        own source, before Jinja or any request value touches it, so nothing a request
        supplies can ever carry the nonce."""
        from moonglade.web_policy import CSP_NONCE_MARK
        return page_source.replace(CSP_NONCE_MARK, _csp_nonce())

    @app.after_request
    def _protective_headers(resp):
        """Finding 4: every response says nosniff, may be framed only by this origin, and sends no Referer
        off this origin; every HTML page carries the Content-Security-Policy its inline
        scripts were written for (CSP_PAGE_POLICY, with this request's nonce). A response
        that set its own policy keeps it (served files carry `sandbox`, harden_file_response),
        and so does one that set its own Referrer-Policy (the connect page's no-referrer)."""
        from moonglade.web_policy import page_csp
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "same-origin")
        if "Content-Security-Policy" not in h and (resp.mimetype or "") == "text/html":
            h["Content-Security-Policy"] = page_csp(getattr(_flask_g, "mg_csp_nonce", None))
        return resp

    @app.errorhandler(413)
    def _too_large(_e):
        """Finding 9's refusal: the body was over the route's cap (REQUEST_MAX_BYTES unless the
        route raised it). A plain sentence, JSON for the API."""
        from moonglade.web_policy import REQUEST_MAX_BYTES, _too_large_sentence
        try:
            limit = request.max_content_length
        except Exception:                                  # noqa: BLE001
            limit = REQUEST_MAX_BYTES
        msg = _too_large_sentence(limit)
        if request.path.startswith(_JSON_GATE_PREFIXES):
            return jsonify({"error": msg}), 413
        return app.response_class(msg, status=413, mimetype="text/plain")

    def _check_csrf(body):
        """Shared CSRF check for this app's state-changing POSTs -- the Panel's
        Users tab (a parsed JSON body) and /logout (request.form) -- using the exact
        same session-based token pattern /login's form uses (see that route's
        docstring), reused rather than reinvented: every state-changing form in this
        app is meant to carry one. `body` only has to be .get()-able, so a dict and a
        request.form MultiDict both work.

        Called _check_panel_csrf until /logout became its second caller (the
        CSRF-able-GET fix) -- the "panel" in the name had stopped being true."""
        submitted_csrf = str((body or {}).get("csrf") or "")
        live_csrf = session.get("csrf", "") or ""
        return bool(live_csrf) and secrets.compare_digest(submitted_csrf, live_csrf)

    # --- Generation surface (owner-only: local, or a logged-in LAN session) --
    # The Generate drawer talks to PixAI with the OWNER's API key and can spend
    # credits. Every generation endpoint (and the rest of the ~44-site LAN-auth
    # conversion -- panel, Loom, snippets/presets, branding writes, jobs,
    # account/claims) is gated to _is_authorized_request(), NOT this narrower
    # _is_local_request() -- exposing the gallery on the LAN (--host 0.0.0.0)
    # must never let an UNAUTHENTICATED device use the key or spend credits, but
    # a logged-in LAN session is deliberately trusted the same as the owner at
    # the keyboard (see CHANGELOG.md's "Real session-based web login" entry).
    # _is_local_request() itself backs the deliberately-narrower LOCALHOST tier
    # on top of that: since 2026-08-23 it is read in ONE place for every route
    # that declares @tier(LOCALHOST) -- _enforce_front_door() -- rather than by
    # a hand-written guard per handler. The only direct callers left are the
    # three routes whose localhost requirement depends on their ARGUMENTS and so
    # is not a tier (/api/panel/run's destructive actions, /api/users/remove and
    # /api/users/password for an account that is not the caller's own) and a
    # handful of purely-informational reads (a boot flag, a withheld host path).
    #
    # FAILS CLOSED on a missing/empty remote_addr: a prior version treated
    # "" as local, which is safe under
    # THIS app's actual deployment (app.run() -> Werkzeug's dev server always
    # populates remote_addr from the real TCP peer, never blank/None -- a plain
    # HTTP client cannot spoof it), but is a fail-OPEN default in a function
    # that now also gates the first-account bootstrap form/POST (above) plus
    # destructive Panel actions and /api/branding/shortcut (below) -- worth
    # being fail-closed on principle given how much rides on it, in case this
    # app is ever run behind a proxy/WSGI shim that doesn't populate the key.
    def _is_local_request():
        ra = (request.remote_addr or "").strip()
        return ra in ("127.0.0.1", "::1", "localhost")

    def _note_power_request(action):
        """Who pressed Stop or Restart, for the line the server writes when it ends (#95): the
        address, whether it is this PC, the signed-in user and the browser string. All of it is
        cleaned to one printable line first -- a client controls the user name and the browser.
        No cookie, token or header dump is read."""
        from moonglade.gallery import _clean_for_log, _note_server_exit
        try:
            _note_server_exit("from %s (%s), user \"%s\", browser \"%s\"" % (
                _clean_for_log(request.remote_addr),
                "this PC" if _is_local_request() else "another device",
                _clean_for_log(session.get("user")),
                _clean_for_log(request.headers.get("User-Agent"), 100)))
        except Exception:                               # noqa: BLE001 -- a log line never gates a Stop
            pass

    def _is_authorized_request():
        """THE canonical authorization gate for every network-originated request:
        true ONLY for a request carrying a valid logged-in session (see /login
        below). Deliberately has NO localhost/loopback bypass -- login is
        required on every path, localhost hostname or IP included; no request
        address is a trusted tier. A fresh install creates its
        first account either via `python -m moonglade --add-web-user`
        or, while no accounts exist yet, through /login's own local-only
        bootstrap_mode form -- see login()'s docstring below for the real,
        shipped web-based bootstrap flow; account creation is NOT CLI-only.
        That bootstrap lives entirely inside login()'s own narrower gate, not
        here: `_is_authorized_request()` itself still has no bypass of any kind,
        so the web app remains unreachable, from any address including
        127.0.0.1, to anything but /login until an account exists and signs in.
        `_is_local_request()` still exists and is still used, but ONLY as an
        independent, stricter, ADDITIONAL requirement on the routes that must
        never run for a remote session even when logged in -- the LOCALHOST tier
        (every route carrying `@tier(LOCALHOST)`, enforced by
        _enforce_front_door() right after this function returns true), plus the
        few argument-dependent cases that are not a tier (destructive Panel
        actions, changing or removing an account that is not the caller's own).
        It is no longer consulted here.

        Every genuine access-control gate that used to read `_is_local_request()`
        was converted to this during the LAN-auth pass; a few purely-informational
        uses (a template flag, an enrichment branch) were also broadened here for
        consistency with the gates they mirror -- see CHANGELOG.md for the
        site-by-site list. It's a plain function closed over this app's
        `session`, so any FUTURE route added inside this same create_app() (e.g. a
        mobile view) can call it directly -- that's the whole point of factoring
        it out instead of inlining the check.

        A session is re-validated against config.json's AUTH_USERS on every call
        (not just trusted because `session.get("user")` is set): the plain Flask
        session is a stateless, client-side signed cookie with nothing server-side
        to revoke, so without this re-check a cookie captured off plain-HTTP LAN
        traffic would keep working forever -- surviving both the real user
        signing out everywhere (/api/logout's scope "everywhere" bumps their
        sess_epoch) and the account being removed
        (get_web_user_session_epoch returns None once it's gone). See that
        function's docstring for the fuller writeup."""
        user = session.get("user")
        if user is None:
            return False
        from moonglade import backup as core
        current_epoch = core.get_web_user_session_epoch(user)
        if current_epoch is None or current_epoch != session.get("sess_epoch"):
            session.clear()   # stale/revoked -- drop it so later requests short-circuit above
            return False
        if not _session_is_current():
            session.clear()   # too old, signed out, or from before sessions had an id
            return False
        return True

    def _session_is_current(now=None):
        """The session's own id is not signed out (Log Out, moonglade.web_sessions) and it is
        younger than SESSION_ABSOLUTE_LIFETIME_S (finding 6). A cookie from before sessions
        carried an id and a birth time has neither and is refused: one sign-in per device
        after this update, so that every live session can be ended on its own."""
        from moonglade.web_policy import SESSION_ABSOLUTE_LIFETIME_S
        sid = session.get("sid")
        born = session.get("born")
        if not sid or not isinstance(born, (int, float)) or isinstance(born, bool):
            return False
        now = time.time() if now is None else now
        if now - born > SESSION_ABSOLUTE_LIFETIME_S or born - now > 300:
            return False
        return not _web_sessions.is_signed_out(sid)

    # ---- Login rate limiting: in-memory per-IP failed-attempt counter ----------
    # Lives in this closure (one dict per running server PROCESS), not config.json
    # or a database -- it exists to blunt casual brute force, not to be a durable
    # security ledger. Known, deliberate limitations (spelled out rather than
    # silently assumed away): (1) resets to empty on every server restart; (2) if
    # this app is ever run under a multi-worker server (gunicorn/uwsgi with >1
    # worker process), each worker process keeps its OWN counter, so the effective
    # lockout threshold becomes (workers x _LOGIN_MAX_FAILS) instead of the real
    # one -- a genuine multi-worker deployment would need a shared store (Redis, a
    # DB table) instead. Fine as-is for this app's normal deployment: one process,
    # `python -m moonglade.gallery`.
    _login_lock = threading.Lock()
    _login_attempts = {}   # ip -> {"fails": int, "first_fail": epoch, "locked_until": epoch|None}
    _LOGIN_MAX_FAILS = 5
    _LOGIN_WINDOW_S = 5 * 60     # failed attempts must land within this window to count together
    _LOGIN_LOCKOUT_S = 15 * 60   # lockout duration once max fails is hit within the window

    def _client_ip():
        return (request.remote_addr or "").strip() or "unknown"

    def _login_seconds_locked(ip):
        """None if `ip` may attempt a login right now; otherwise seconds remaining
        on its current lockout."""
        import time as _time
        with _login_lock:
            rec = _login_attempts.get(ip)
            if not rec or not rec.get("locked_until"):
                return None
            remaining = rec["locked_until"] - _time.time()
            if remaining <= 0:
                _login_attempts.pop(ip, None)   # lockout expired -- clean slate
                return None
            return int(remaining)

    def _login_try_acquire(ip):
        """Atomically re-check `ip`'s lockout status AND reserve/record this
        attempt as a (provisional) failure, in the SAME critical section --
        closes a TOCTOU race in the old check-then-act pattern (a fast, lock-
        protected `locked_for` read, then verify_web_user()'s slow -- and
        UNLOCKED -- scrypt comparison, then a separate fast, lock-protected write
        after). Under that old pattern, many concurrent requests from one IP each
        pass the early read before any of them reaches the write, so a burst of
        arbitrarily many guesses lands "free" before the counter reflects more
        than zero fails -- only the NEXT burst gets locked out, buying N guesses
        per 15-minute cycle instead of the intended 5. Reserving the attempt here,
        before the slow call runs, means the fail count (and therefore the lock)
        is committed atomically at admission time, not completion time. A
        genuinely correct login calls _login_clear() right after, which erases
        this reservation along with the rest of the counter, so a real user's own
        correct password is never penalized by it.

        Also opportunistically sweeps any OTHER address's record whose failure
        window has fully expired without ever reaching a lockout -- otherwise an
        IP that fails 1-4 times and never returns sits in this dict forever (no
        other code path ever removes it), an unbounded-growth vector from many
        distinct real source addresses (no header-spoofing needed: IPv6 privacy
        rotation or any real botnet/proxy pool). Low severity for a genuinely
        LAN-only deployment, real the moment --host 0.0.0.0 sits behind a
        port-forward or other routable path.

        Returns None if the attempt may proceed, else seconds remaining on the
        lockout that was already in effect (or was just now triggered)."""
        import time as _time
        now = _time.time()
        with _login_lock:
            stale = [k for k, r in _login_attempts.items()
                     if k != ip and not r.get("locked_until")
                     and now - r["first_fail"] > _LOGIN_WINDOW_S]
            for k in stale:
                _login_attempts.pop(k, None)

            rec = _login_attempts.get(ip)
            if rec and rec.get("locked_until"):
                remaining = rec["locked_until"] - now
                if remaining > 0:
                    return int(remaining)
                _login_attempts.pop(ip, None)   # lockout expired -- clean slate

            rec = _login_attempts.setdefault(
                ip, {"fails": 0, "first_fail": now, "locked_until": None})
            if now - rec["first_fail"] > _LOGIN_WINDOW_S:   # window expired -- start fresh
                rec["fails"] = 0
                rec["first_fail"] = now
            rec["fails"] += 1
            if rec["fails"] >= _LOGIN_MAX_FAILS:
                rec["locked_until"] = now + _LOGIN_LOCKOUT_S
            return None

    def _login_clear(ip):
        """Called on a successful login -- a real owner/user typing their own
        password correctly should never stay throttled by earlier typos."""
        with _login_lock:
            _login_attempts.pop(ip, None)

    def _gen_session():
        from moonglade import backup as core
        return core, core._make_session(None)

    # Membership is not stored anywhere -- it is a live GraphQL read per call -- and
    # /api/price fires on every keystroke in the drawer, so an uncached check would tax the
    # cost badge with a round trip per character. Five minutes is long enough to cost
    # nothing and short enough that a membership bought (or lapsed) mid-session is picked up
    # without a restart. An UNKNOWN result is deliberately not cached: it means the read
    # failed, and a transient failure must not pin a paying member to non-member behaviour.
    _entitle_cache = {"value": None, "at": 0.0}
    _ENTITLE_TTL = 300.0

    def _entitlements(core, session):
        """{"is_member": True/False/None, "lora_cap": int|None} -- what PixAI says this
        account may ask for. None anywhere means UNKNOWN and every caller fails open."""
        import time as _t
        now = _t.time()
        cached = _entitle_cache["value"]
        if cached is not None and (now - _entitle_cache["at"]) < _ENTITLE_TTL:
            return cached
        try:
            me = core.account_info(session)
            val = {"is_member": core.account_is_member(me),
                   "lora_cap": core.account_lora_cap(me)}
        except Exception:                                    # noqa: BLE001
            return {"is_member": None, "lora_cap": None}
        if val["is_member"] is not None:
            _entitle_cache["value"] = val
            _entitle_cache["at"] = now
        return val

    def _account_is_member(core, session):
        """True / False / None(unknown) -- entitlement for PixAI's members-only options."""
        return _entitlements(core, session)["is_member"]

    def _input_media_id(core, session, val):
        """Turn whatever the client sent into a media_id PixAI will accept as an INPUT.

        A media_id in our catalog identifies a generation OUTPUT. On 2026-07-20 PixAI
        refused one as an input (invalid_media_id / invalid_reference_image_media_id) and
        this helper was built to upload instead. PROBED since: i2vPro (2026-07-26) and
        referenceVideo (2026-08-22, 10 completed tasks) both accept catalog ids, so
        /api/loom/generate passes ids through and calls this only as the retry FALLBACK
        after a real invalid_*_media_id rejection. /api/edit and /api/fix still resolve
        through it on the main path.

        We hold the file on disk (that is what the backup IS), so upload it and hand
        PixAI an upload-kind id. Same free S3 handshake as --upload and /api/upload;
        spends nothing. Cached per media_id for the process lifetime.

        This lives at create_app scope, called by EVERY path that feeds a user-chosen
        image to PixAI -- /api/loom/generate, /api/edit, /api/fix. The first fix for this
        bug only patched the video route, which left the other input routes silently broken
        in exactly the same way; a shared helper is what stops the next input path from
        reintroducing it.

        Falls back to the value unchanged on ANY failure (no local copy, upload error)
        so PixAI's own error surfaces rather than a mystery 'no reference'.
        """
        from moonglade.catalog_verbs import find_image_file
        from moonglade.catalog import get_row
        s = str(val or "").strip()
        if not s or not s.isdigit():
            return s                       # data: URLs and blanks are handled by callers
        if s in _ref_upload_cache:
            return _ref_upload_cache[s]
        try:
            row = get_row(db_path, s)
            fp = find_image_file(out_dir, s, (row or {}).get("filename") or "")
            if not fp or not fp.exists():
                return s
            mid = core.upload_media(session, str(fp))
        except Exception:                  # noqa: BLE001 -- never 500 a generation over this
            return s
        if mid:
            _ref_upload_cache[s] = str(mid)
            return str(mid)
        return s

    def _ach_sid():
        """This session's beacon identity: the LOGIN's own stable identity -- the account
        name plus the `csrf` token _establish_session() mints AT LOGIN -- fingerprinted,
        with the caller's address as a second key. Nonces are bound to it, and the debounce
        and the rate limit are keyed on it.

        REPLACING (2026-09-07, refining the same day's nonce ruling) a lazy
        `session.setdefault("ach_sid", secrets.token_hex(16))`. The Flask session is a
        client-held signed cookie, and _is_authorized_request() re-validates only
        user/sess_epoch -- so the cookie handed out at login is still valid, still
        authorized, and carries NO ach_sid. setdefault therefore minted a fresh one on
        every replay of it, and with it a fresh 30-call budget and a fresh debounce slate:
        the limit this route's own docstring calls the stop for a scripted replay loop did
        not bind at all (60 rounds, 60 sids, no 429). The key had to be something a client
        cannot vary by replaying an OLDER cookie, and both halves of this one are written
        once, at login, by the single _establish_session() that defines what a session is
        -- a replayed cookie carries the same pair, so it draws on the same budget. The
        address is a second key so two devices signed into one account keep budgets of
        their own rather than sharing (and colliding on) one.

        The csrf token is HASHED rather than used raw: it is the same token that guards the
        write routes, and a long-lived process dict is not a place to leave it lying about.
        The lazy random id survives only as the fallback for a session with no login
        identity at all -- nothing behind @tier(LOGIN) can reach that, but the render seams
        call this too, and a no-accounts first render has no `user` to key on."""
        import hashlib
        user = str(session.get("user") or "")
        tok = str(session.get("csrf") or "")
        if user and tok:
            who = hashlib.sha256(("%s\x00%s" % (user, tok)).encode("utf-8")).hexdigest()[:16]
        else:
            who = "anon:" + session.setdefault("ach_sid", secrets.token_hex(16))
        return "%s@%s" % (who, _client_ip())

    # ==== THE GALLERY -- the React front door ================================
    # "/" serves gallery/dist (Vite build: `npm run build` inside gallery/).
    # This is the FIRST-CLASS frontend the gallery UI migrated to -- real
    # component files, its own purpose-built API below, NOT the Loom's delivery
    # and NOT the picker routes. It shipped under the `/next` codename through
    # the pilot; that codename is retired (issue #51) and this page answers on
    # one path. Design lock + suite-shell rationale:
    # moonglade-internal/DECISIONS.md "THE MIX is the pilot's locked direction" (2026-07-29).
    # Auth: covered by the global _enforce_front_door() hook like every route.
    _GALLERY_DIST = _paths.gallery_dist()

    # No vanilla web components ride along anymore: the video Generate drawer and
    # its cost badge became the React <VideoDrawer>/<CostBadge> in the 2026-08-08
    # no-vanilla port (the last of static/mg-*.js), joining the notify system
    # (toasts/tracker/celebrations) already in the React bundle -- so this shell
    # carries no <script src="/static/mg-*.js"> tags and no anchors.
    # __UPSCALE_CONST__ serves MG_LORA / MG_UPSCALE from their one Python source,
    # same idiom as the classic pages.
    # viewport-fit=cover (2026-09-06, the phone audit's foundational finding). Without it a
    # notched phone lays the page out INSIDE the safe area and every
    # env(safe-area-inset-*) resolves to 0 -- so the tab bar's home-indicator gutter, the
    # sheets' footer padding, the hero's notch guard and every other inset the mobile
    # stylesheets carry were quietly doing nothing on exactly the hardware they were
    # written for. It is inert everywhere else: a browser reporting no insets resolves the
    # same env() to 0 with or without it, which is what the desktop shell has always
    # measured. The same line rides LOGIN_PAGE and _LOOM_SHELL, the other two shells a
    # phone reaches, and gallery/index.html, the dev twin of this one.
    APP_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
<link rel="manifest" href="/next/assets/manifest.json">
<meta name="theme-color" content="#0a0818">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Moonglade">
<link rel="apple-touch-icon" href="/next/assets/icon-180.png">
""" + _PREPAINT_BOOT_JS + _AUTH_401_GUARD_JS + """
<link rel="stylesheet" href="/next/assets/app.css">
{# The app's ONE palette + every skin override, AFTER the bundle's stylesheet so
   the tokens win any same-specificity :root collision. Same idiom BASE_HTML and
   the Loom shell use -- deliberately not a /next/assets/tokens.css route, which
   would split the single source of truth. The notify system (in the React bundle
   as of the 2026-08-08 no-vanilla port) does the rest: it reconciles data-skin
   against /api/achievements on load. #}
<style>
__DESIGN_TOKENS__
</style>
</head><body>
<div id="root"></div>
{# The Job Tracker's #jobs-fab/#jobs-tray anchors lived here as body-level divs until the
   2026-08-08 no-vanilla port -- the React <ActivityTray> now renders them (same ids, still
   body-level via a portal), so the shell carries no notify markup, no pre-paint flash guard,
   and no mg-notify.js script tag. #}
{# |tojson, NOT json.dumps|safe: json.dumps does not escape "</script>", and boot
   carries third-party text (PixAI model titles via unique_models, collection
   names from any account). One "</script>" in a model title would break out of
   this inline script and run in a session that can POST the CSRF-exempt
   /api/generate -- i.e. spend without consent. Jinja's tojson escapes < > &. #}
<script nonce="__CSP_NONCE__">window.MG_BOOT = {{ boot|tojson }};</script>
__UPSCALE_CONST__
<script type="module" src="/next/assets/app.js"></script>
</body></html>"""

    # LoginPage.jsx's own shell (2026-08-02) -- deliberately its OWN, smaller
    # template rather than reusing APP_PAGE verbatim. When it was written, APP_PAGE
    # also loaded eight /static/mg-*.js custom-element scripts (pickers, cost badge,
    # generate drawer, upscale panel; since ported into the React bundle and deleted,
    # 2026-08-08). They were not on the public tier, so an unauthenticated visitor's
    # <script> requests for them 302'd back to /login (the front door redoing its own
    # job on itself), the module script's own fetch got HTML back and threw
    # "Unexpected token '<'", and the bundle never ran at all. The shell stays its own:
    # only /next/assets/ (this page's own bundle/stylesheet) is @tier(PUBLIC), and a
    # visitor who has not signed in has no use for __UPSCALE_CONST__. Same app.js bundle
    # either way (main.jsx statically imports both App and LoginPage, so Vite ships one
    # file) -- only the SHELL differs, and the shell is what decides which one actually
    # needs to reach an unauthenticated browser.
    # viewport-fit=cover, same reason as APP_PAGE's own note above: this shell serves
    # LoginPageMobile.jsx on a phone, and login-mobile.css cannot read an inset the
    # viewport never opened.
    LOGIN_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
<link rel="manifest" href="/next/assets/manifest.json">
<meta name="theme-color" content="#0a0818">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Moonglade">
<link rel="apple-touch-icon" href="/next/assets/icon-180.png">
""" + _PREPAINT_BOOT_JS + _AUTH_401_GUARD_JS + """
<link rel="stylesheet" href="/next/assets/app.css">
<style>
__DESIGN_TOKENS__
</style>
</head><body>
<div id="root"></div>
{# |tojson, NOT json.dumps|safe -- same XSS reasoning as APP_PAGE's own boot
   script: Jinja's tojson escapes < > & so a stray "</script>" in, say, a
   redirected `next` path can never break out of this inline script. #}
<script nonce="__CSP_NONCE__">window.MG_BOOT = {{ boot|tojson }};</script>
<script type="module" src="/next/assets/app.js"></script>
</body></html>"""

    # /mirror/connect's page (Connect from PixAI, 2026-11-18): the login card's own markup and
    # classes (gallery/src/styles/login.css, already in app.css), no bundle -- a few lines of
    # inline script do the whole job. PIXAI is the one origin a sign-in is taken from (www.
    # redirects to it), and the ready ping names it as its target, never "*". The token lives
    # in one closure variable for the length of one POST and is never written to the page.
    MIRROR_CONNECT_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Connect from PixAI · Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
""" + _PREPAINT_BOOT_JS + _AUTH_401_GUARD_JS + """
<link rel="stylesheet" href="/next/assets/app.css">
<style>
__DESIGN_TOKENS__
</style>
</head><body>
<div class="lgn-stage">
  <div class="lgn-wash lgn-wash-a"></div>
  <div class="lgn-wash lgn-wash-b"></div>
  <div class="lgn-frame">
    <div class="lgn-card">
      <div class="lgn-titlewrap">
        <div class="lgn-title">Connect from PixAI</div>
        <div class="lgn-framing" id="mc-status" role="status">Waiting for your pixai.art tab…</div>
      </div>
      <div class="lgn-error" id="mc-error" role="alert" hidden></div>
      <button type="button" class="lgn-signbtn" id="mc-close">Close</button>
    </div>
  </div>
</div>
<script nonce="__CSP_NONCE__">window.MG_MIRROR_CONNECT = {{ boot|tojson }};</script>
<script nonce="__CSP_NONCE__">
(function () {
  var PIXAI = "https://pixai.art";
  var boot = window.MG_MIRROR_CONNECT || {};
  var status = document.getElementById("mc-status");
  var error = document.getElementById("mc-error");
  function say(t) { status.textContent = t; }
  function fail(t) { error.textContent = t; error.hidden = false; }
  document.getElementById("mc-close").addEventListener("click", function () { window.close(); });
  var opener = window.opener;
  if (!opener) {
    say("Not connected.");
    fail("Open this from the Connect from PixAI bookmark, clicked on a pixai.art tab.");
    return;
  }
  var got = false, tries = 0;
  function ping() {
    if (got) return;
    try { opener.postMessage({ type: "moonglade-mirror-ready" }, PIXAI); } catch (e) {}
    if (++tries < 360) { setTimeout(ping, 500); return; }
    say("Not connected.");
    fail("Nothing came from pixai.art. Click the bookmark again on a pixai.art tab.");
  }
  function days(n) {
    return n >= 1 ? n + (n === 1 ? " day" : " days") + " left" : "less than a day left";
  }
  window.addEventListener("message", function (e) {
    if (got || e.origin !== PIXAI || e.source !== opener) return;
    var d = e.data;
    if (!d || d.type !== "moonglade-mirror-token" || typeof d.token !== "string") return;
    got = true;
    say("Checking your PixAI sign-in…");
    var token = d.token;
    fetch("/api/mirror/connect-token", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf: boot.csrf || "", token: token })
    }).then(function (r) {
      return r.json().catch(function () { return {}; });
    }).then(function (j) {
      if (j && j.ok) { say("Connected · " + days(j.days_left)); return; }
      say("Not connected.");
      fail((j && j.error) || "Moonglade couldn't save that sign-in.");
    }).catch(function () {
      say("Not connected.");
      fail("Couldn't reach Moonglade. Check that it is still running, then try again.");
    });
    token = null;
  });
  ping();
})();
</script>
</body></html>"""

    # "/" is the FRONT DOOR (the flip, 2026-08-01) and, since issue #51, the
    # ONLY path to it. The pilot-era `/next` alias is gone with the codename --
    # nothing in the app, the launcher, the docs or the wiki linked it (the
    # shell pushes window.location.pathname, and every in-app deep link is
    # already "/?image="), so no redirect stands in for it. A pilot-era
    # bookmark 404s: the owner's call, "default is retire".
    @app.route("/")
    @tier(LOGIN)
    def app_page():
        from moonglade.catalog_verbs import catalog_years, unique_models
        from moonglade.curation import catalog_counts, list_smart_collections
        from moonglade.catalog import unique_collections
        from moonglade.pages import DESIGN_TOKENS_CSS, _upscale_const_js
        from moonglade.ach_beacon import _ach_mint
        session.setdefault("csrf", secrets.token_hex(16))
        brand = _branding.brand_context(out_dir)
        stats = catalog_counts(db_path)
        # First-run wizard gating -- SAME computation as classic's index() (see its own
        # long comment on why this is a fresh config.json read, not the module-cached
        # core._cfg): someone who just pasted a key via the wizard needs this to flip on
        # the very next load, not after a restart. No is_local/is_true_local conjunct here
        # either, matching index() exactly -- the front door's own auth gate is what keeps
        # an anonymous LAN visitor from ever reaching this line at all; a signed-in LAN
        # session sees the same wizard an owner does, and the real write endpoints
        # (/api/setup/save-key) enforce their own localhost-only check independently.
        from moonglade import backup as _core
        _fresh_cfg = _core._load_config()
        needs_key = not bool(_fresh_cfg.get("PIXAI_API_KEY") or _fresh_cfg.get("U3T"))
        catalog_empty = not needs_key and (stats["images"] + stats["videos"]) == 0
        # Asset container check (2026-08-10): cheap (marker-file compare, not a
        # re-hash) so it's safe on every boot, not just first-run. Placement of
        # the resulting UI moment (a Setup Wizard phase vs. standalone) is a
        # frontend decision -- this flag is UI-agnostic on purpose, same as
        # needs_key above, so either caller can drive it.
        needs_assets = moonglade_assets.needs_download(_branding._container_path())
        boot = {
            "stats": stats,
            "needs_key": needs_key,
            "needs_assets": needs_assets,
            "catalog_empty": catalog_empty,
            "collections": unique_collections(db_path),
            # Smart collections (N1): saved searches, listed beside the hand-picked ones.
            "smart_collections": list_smart_collections(db_path),
            "user": session.get("user") or "",
            "is_local": True,
            "is_true_local": _is_local_request(),
            "csrf": session["csrf"],
            # The feat beacon's per-render nonce (2026-09-07 ruling -- see
            # api_ach_event()'s own comment). One event per nonce, 60 seconds,
            # bound to this session; notify/achNonce.js seeds itself from here and
            # rotates on each accepted event.
            "ach_nonce": _ach_mint(_ach_sid()),
            "build_stamp": build_stamp,
            # The locked default; becomes a Branding-panel setting later
            # (moonglade-internal/DECISIONS.md "Banner controls join the Branding panel").
            "band": {"height": 340, "crop": 30},
            # For the Advanced flyout: the model datalist + the From/To year range.
            "models": unique_models(db_path),
            "years": catalog_years(db_path),
            # The chosen branding: which mark, its animation, and whether it is a
            # rounded tile or a transparent floater. _inject_branding() already
            # puts these in every template's Jinja context; the pilot needs them
            # in JS because its mark is a React component, and the glint mask
            # needs the URL as a CSS variable (a built stylesheet cannot
            # Jinja-interpolate one). Without this the mark rendered dead.
            "mark_url": brand.get("mark_url") or "/branding/logo.png",
            "mark_anim": brand.get("mark_anim") or "classic",
            "mark_kind": brand.get("mark_kind") or "",
            # The animation tuning rides with the pick it tunes -- one payload, so
            # the header can never paint the right treatment at the wrong speed.
            "anim_speed": brand.get("anim_speed", 1.0),
            "anim_scale": brand.get("anim_scale", 1.0),
            "glow_color": brand.get("glow_color") or "#94e2d5",
            "glow_angle": brand.get("glow_angle", 0.0),
        }
        return render_template_string(
            _noncify(APP_PAGE.replace("__UPSCALE_CONST__", _upscale_const_js()))
                     .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS),
            boot=boot)

    @app.route("/next/assets/<path:fname>")
    @tier(PUBLIC)
    def next_assets(fname):
        resp = send_from_directory(str(_GALLERY_DIST), fname)
        # The bundle changes on every `npm run build` with NO url change, and this
        # response carried no Cache-Control -- so browsers HEURISTICALLY cached
        # app.css/app.js and kept painting days-old layout. Bit for real (2026-08-08):
        # the Details full-window takeover looked "overridden by the banner" on the
        # owner's everyday tab -- a stale cached app.css from BEFORE the takeover fix,
        # while a fresh session's probe of the same server looked perfect. no-cache
        # forces revalidation; ETag/Last-Modified make that a cheap 304 on localhost/
        # LAN, so repeat loads stay fast but can never be stale again.
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.after_request
    def _gzip_html(resp):
        # Compress only HTML pages (the big card grids). File responses are
        # direct_passthrough streams and are left untouched.
        try:
            if (resp.status_code == 200 and not resp.direct_passthrough
                    and resp.content_type and resp.content_type.startswith("text/html")
                    and "gzip" in request.headers.get("Accept-Encoding", "")):
                data = resp.get_data()
                if len(data) > 1024:
                    import gzip as _gzip
                    packed = _gzip.compress(data, 6)
                    resp.set_data(packed)
                    resp.headers["Content-Encoding"] = "gzip"
                    resp.headers["Content-Length"] = str(len(packed))
                    resp.headers["Vary"] = "Accept-Encoding"
        except Exception:
            pass
        return resp

    @app.after_request
    def _code_assets_no_cache(resp):
        # Same staleness class as /next/assets (see next_assets): files under static/
        # (today the design pages and tokens; once the shared mg-*.js web components)
        # change on edit with no url change, and heuristic caching kept old copies
        # live in real tabs. Scoped to /static/
        # ONLY -- thumbnails and full media stay freely cacheable (huge, and a
        # media file's content never changes under its id).
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.after_request
    def _identify_server(resp):
        # Stamp EVERY response -- including the front door's 401 short-circuit -- with a
        # stable marker the "Moonglade Launcher" uses to tell "our server is already
        # on this port" from "some other service is" (or nothing). It MUST ride the auth
        # gate: the launcher probes /api/ping without a session and now gets a 401, not a
        # 200, so a status-based check can't identify us. A fixed value, not __version__:
        # the launcher only needs identity, and broadcasting the exact build on every
        # response is needless disclosure for a public-repo app. after_request runs on
        # responses returned by before_request (the gate returns, never raises), so the
        # header lands on the 401 too -- pinned by test_web_auth.
        resp.headers["X-Moonglade"] = "1"
        return resp

    # -- provided to ctx (split_move) --
    ctx.MIRROR_CONNECT_PAGE = MIRROR_CONNECT_PAGE
    ctx._account_is_member = _account_is_member
    ctx._ach_sid = _ach_sid
    ctx._check_csrf = _check_csrf
    ctx._csp_nonce = _csp_nonce
    ctx._entitlements = _entitlements
    ctx._gen_session = _gen_session
    ctx._input_media_id = _input_media_id
    ctx._is_local_request = _is_local_request
    ctx._noncify = _noncify
    ctx._note_power_request = _note_power_request
    ctx._redact_host_paths = _redact_host_paths
    # -- end --

"""moonglade/routes_panel.py -- the Control Panel's routes: health and the integrity pass (the
broken list, mark, fix and its status and stop), the panel summary, the users (add, remove,
password), the server's ping, stop, restart and library folder, the updater (check, status,
apply), Bonjour and the CA certificate, the CSV and curation exports, the job runner's run, status,
cancel, schedule and sweep, the website-task import and the watch status.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was. Names the block reads from create_app's setup, the
front door and the background block (the job slot and its lock, the schedule, the job log, the
watch status ...) come in through ctx (the bound-from-ctx lines below), so every closure on both
sides holds the one same object. gallery's own names are imported inside the function that reads
them, at call time, so a test's patch of moonglade.gallery still reaches the route.
"""
import secrets
import threading
import time

from flask import jsonify, request, send_file, session

from moonglade import branding as _branding
from moonglade import health as _health
from moonglade import jobs as _jobs
from moonglade import living as _living
from moonglade import mirror as _mirror
from moonglade import paths as _paths
from moonglade import settings as _settings
from moonglade import updater as _updater
from moonglade import web_accounts as _web_accounts


def register(app, ctx):
    from moonglade.web_tiers import LOCALHOST, LOGIN, PUBLIC, tier
    # -- bound from ctx (split_move) --
    PANEL_ACTIONS = ctx.PANEL_ACTIONS
    _LIVING_STALE_ACTIONS = ctx._LIVING_STALE_ACTIONS
    _artworks_job_busy = ctx._artworks_job_busy
    _artworks_kick = ctx._artworks_kick
    _check_csrf = ctx._check_csrf
    _collect_single_flight = ctx._collect_single_flight
    _gen_session = ctx._gen_session
    _is_local_request = ctx._is_local_request
    _job_busy = ctx._job_busy
    _living_runnable = ctx._living_runnable
    _load_sched = ctx._load_sched
    _log_job = ctx._log_job
    _note_power_request = ctx._note_power_request
    _panel_job = ctx._panel_job
    _panel_lock = ctx._panel_lock
    _panel_run = ctx._panel_run
    _redact_host_paths = ctx._redact_host_paths
    _save_sched = ctx._save_sched
    _sched_lock = ctx._sched_lock
    _standing_action = ctx._standing_action
    _standing_runnable = ctx._standing_runnable
    _update_busy = ctx._update_busy
    _update_busy_refusal = ctx._update_busy_refusal
    _watch_lock = ctx._watch_lock
    _watch_status = ctx._watch_status
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    @app.route("/api/health")
    @tier(LOGIN)
    def api_health():
        """The health dashboard's data as JSON -- gap-audit route #10, consumed by the
        React app's HealthOverlay (the in-app modal that replaces bouncing to the
        /health page). Same computation, same fields, same LOGIN tier as the page it
        un-bakes; the page route stays until demolition.

        THE CACHE IS health_cached() (module level -- see its own block for the reasoning):
        keyed on the CATALOG FILE with no time floor, serve-stale-while-recomputing, and
        primed off-thread at boot. It replaced the 120s TTL this route carried from
        2026-08-06, which was stale in one direction (a change made 5s ago stayed invisible
        for two minutes) and cold in the other (a first open after two idle minutes paid the
        whole walk with the user watching). The cache still lives OUTSIDE
        collection_health(), as it always has, so every direct caller -- the classic /health
        page, the tests -- gets a pure, uncached computation. ?fresh=1 bypasses; the client
        sends it on an explicit user refresh, never on a plain open."""
        return jsonify(_health.health_cached(out_dir, db_path,
                                     fresh=bool(request.args.get("fresh"))))

    # ---- Health's Broken files list (Session W, the Archive Integrity Handoff) ----
    # The list reads the last integrity check's report (moonglade.integrity.broken_list);
    # the owner's Mark lost / Keep as is are a local flag beside it (integrity_marks.json).
    # Neither touches a file, a catalog row or PixAI.

    @app.route("/api/integrity/broken")
    @tier(LOGIN)
    def api_integrity_broken():
        """The Broken files list: the last check's broken rows with each one's pill, the one
        action that applies, its chip and its local mark, plus what Fix all would do.
        `read_only` says whether re-downloads are off (READ_ONLY in config.json)."""
        from moonglade import backup as core
        from moonglade import integrity as moonglade_integrity
        doc = moonglade_integrity.broken_list(out_dir, db_path,
                                              avg_bytes=_health.health_avg_file_bytes())
        doc["read_only"] = bool(core.READ_ONLY or core._read_only_now())
        doc["run"] = _fix_runner.status()
        return jsonify(doc)

    @app.route("/api/integrity/mark", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_mark():
        """Mark lost / Keep as is / Undo: set one broken row's local mark ("lost", "kept",
        or "" to clear it) and answer the mark it had before, which Undo sends back. Only a
        row on the list can take a mark; clearing is allowed for any row that has one.
        Body: {csrf, media_id, mark}."""
        from moonglade import integrity as moonglade_integrity
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        mid = str(body.get("media_id") or "").strip()
        mark = str(body.get("mark") or "")
        if mark not in ("",) + moonglade_integrity.MARKS:
            return jsonify({"error": "That isn't a mark this list keeps."}), 400
        if mark and mid not in moonglade_integrity.listed_ids(out_dir):
            return jsonify({"error": "That file isn't on the Broken files list."}), 400
        if not mark and mid not in moonglade_integrity.read_marks(out_dir):
            return jsonify({"ok": True, "media_id": mid, "mark": "", "prev": ""})
        try:
            prev = moonglade_integrity.set_mark(out_dir, mid, mark)
        except (ValueError, OSError) as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 400
        return jsonify({"ok": True, "media_id": mid, "mark": mark, "prev": prev})

    # The fix run: moonglade.integrity.FixRunner, one per server, on its own thread so closing
    # Health never stops it. It refuses an archive-only row BY ITSELF (redownload_one reads the
    # catalog, whatever the client sent), READ_ONLY blocks its re-downloads but not its local
    # thumbnail rebuilds, and it deletes nothing. Test seam: app.extensions["mg_integrity_fix"].
    from moonglade import integrity as _integ
    _fix_runner = _integ.FixRunner(out_dir, db_path, log_job=_log_job)
    app.extensions["mg_integrity_fix"] = _fix_runner

    @app.route("/api/integrity/fix", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_fix():
        """Start a fix run over the chosen rows: one per-row Re-download / Rebuild, or Fix all
        recoverable. Body: {csrf, items: [{media_id, action}, ...]} -- every row with the action
        the list SHOWED ("redownload" or "rebuild"), which the runner holds it to: a file that
        changed since the check runs nothing (review finding 3). Rows not on the Broken files
        list come back in `refused`; 409 while a run is going. Answers the run's status with
        `started`."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        items = body.get("items")
        if (not isinstance(items, list) or not items
                or not all(isinstance(it, dict) and str(it.get("media_id") or "").strip()
                           and it.get("action") in _integ.FIX_ACTIONS for it in items)):
            return jsonify({"error": "No files were chosen."}), 400
        st = _fix_runner.start(items[:5000])
        if st is None:
            return jsonify({"error": "A fix is already running.", "busy": True}), 409
        st["started"] = bool(st["running"])
        return jsonify(st)

    @app.route("/api/integrity/fix/status")
    @tier(LOGIN)
    def api_integrity_fix_status():
        """The fix run as it stands: n / N, the current row's bytes, every result so far."""
        return jsonify(_fix_runner.status())

    @app.route("/api/integrity/fix/stop", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_fix_stop():
        """Stop: the current file finishes, then the run ends. Nothing is rolled back."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        _fix_runner.stop()
        return jsonify({"ok": True})

    @app.route("/api/panel/summary")
    @tier(LOGIN)
    def api_panel_summary():
        """JSON twin of /panel's own aggregation, for the React Control Panel overlay --
        same data, same local/destructive action-visibility rule (see /panel's own long
        comment on panel_is_local), just packaged for fetch() instead of Jinja. Nothing
        computed here is new: every field is a value /panel already builds every request.
        LOGIN tier, matching /panel itself."""
        from moonglade.gallery import _supervised
        from moonglade.trash import list_quarantined
        from moonglade.curation import catalog_counts
        panel_is_local = _is_local_request()
        all_actions = [{"action": k, "label": v["label"], "destructive": v["destructive"],
                        "advanced": v.get("advanced", False),
                        "int_param": v.get("int_param", False),
                        "int_default": v.get("int_default"),
                        "int_range": v.get("int_range")}
                       for k, v in PANEL_ACTIONS.items()]
        actions = [a for a, (k, v) in zip(all_actions, PANEL_ACTIONS.items())
                  if v.get("panel_visible", True) and (panel_is_local or not v["destructive"])]
        from moonglade import backup as core
        session.setdefault("csrf", secrets.token_hex(16))
        try:
            _branding.sweep_branding_drops(out_dir)   # see api_branding()'s own GET for why
        except Exception:
            pass
        branding = _branding.load_branding(out_dir)
        # Control Panel.dc.html:226's {{ trashCount }} -- the Trash tile's own real
        # count, previously hardcoded to "--" on both platforms (nothing fetched
        # it; the real number only ever resolved once TrashSubOverlay's own
        # /api/trash/list call ran). Reuses list_quarantined()'s own total rather
        # than a second counting pass -- see that function's docstring for why an
        # os.scandir()-based count stays cheap even at a large trash size.
        trash_count = list_quarantined(out_dir, page=1, page_size=1)[1]
        return jsonify({
            "stats": catalog_counts(db_path),
            "trash_count": trash_count,
            "supervised": _supervised(),
            "panel_is_local": panel_is_local,
            # On this PC or a private home network (the reach of Connect from PixAI): the
            # Mirror tile's Disconnect shows for it, not only for the page on 127.0.0.1.
            "home_network": bool(_mirror.home_network_address(request.remote_addr)),
            "actions": actions, "all_actions": all_actions,
            "out_dir": str(out_dir) if panel_is_local else "",
            "web_users": _web_accounts.list_web_users(),
            "current_username": session.get("user"),
            "csrf": session["csrf"],
            "branding": dict(_branding._branding_tuning(branding),
                             mark=branding["mark"], anim=branding["anim"],
                             anims=_branding.MARK_ANIMS,
                             # The Control Panel reads its marks from HERE, not from
                             # GET /api/branding -- so the earned annotation the two
                             # gated mark grids render off (locked/dimmed) has to be
                             # computed here too, or the lock never shows and a bound
                             # mark only fails on click with a raw 403 toast (red team
                             # 2026-09-08). Same gate as the GET route below.
                             marks=_branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path)),
                             slots=_branding.branding_slots_payload(out_dir),
                             roles=_branding.branding_roles_payload(out_dir)),
        })

    @app.route("/api/users/add", methods=["POST"])
    @tier(LOCALHOST)
    def api_users_add():
        """Add a new gallery web-login account from the Panel's Users tab.

        LOCALHOST-ONLY as of 2026-07-22. Previously gated by nothing beyond the
        front door, reasoned as "every account in this app's model already
        carries equal trust, so any logged-in session may manage accounts."
        That principle covers what an ALREADY-EXISTING account can do (generate,
        browse, curate) -- it was never weighed against a LAN guest minting
        itself a brand-new, persistent account. Closed alongside the matching
        fix to /api/users/remove: a LAN session used to be able to evict the
        owner's own account and then register a fresh one for itself, one
        finding with two halves (see the old state doc's Access & accounts section).
        Account creation now sits in the same trust class as
        api_setup_save_key/api_branding_shortcut/destructive Panel jobs -- a
        logged-in LAN account can use the gallery, not decide who else gets to.

        Refuses a duplicate username outright rather than silently resetting a
        stranger's password (that's still what add_or_update_web_user itself
        does, and stays available for the owner via --add-web-user for exactly
        that recovery case).

        The exists-check and the write happen in ONE call to
        core.add_web_user_if_new() (a single _accounts_lock acquisition), not a
        separate list_web_users() read followed by a separate
        add_or_update_web_user() write -- the latter shape was a TOCTOU: two
        concurrent requests claiming the same brand-new username could both pass
        the "doesn't exist yet" check before either write landed, and the second
        write would silently reset the first request's just-created password.
        (Same root-cause family as /api/users/remove's last-account race -- see
        that route's docstring.)"""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        confirm = str(body.get("confirm") or "")
        # Same core.username_problem()/password_problem() the /login bootstrap form
        # and the --add-web-user CLI call use -- one policy, three entry points, no
        # drift. username_problem covers empty, over-length, and control chars.
        un_problem = _web_accounts.username_problem(username)
        if un_problem:
            return jsonify({"error": un_problem}), 400
        pw_problem = _web_accounts.password_problem(password)
        if pw_problem:
            return jsonify({"error": pw_problem}), 400
        if password != confirm:
            return jsonify({"error": "Passwords do not match."}), 400
        if not _web_accounts.add_web_user_if_new(username, password):
            return jsonify({"error": "That username already exists."}), 400
        return jsonify({"ok": True, "username": username})

    @app.route("/api/users/remove", methods=["POST"])
    @tier(LOGIN)
    def api_users_remove():
        """Remove a gallery web-login account from the Panel's Users tab.

        Removing SOMEONE ELSE'S account is LOCALHOST-only, as of 2026-07-22;
        removing YOUR OWN account stays reachable from any logged-in session,
        local or LAN. Self-removal can only harm the caller -- that's a
        different, much smaller trust question than evicting another named
        account, which is the specific gap this closes: a LAN session used to
        be able to remove ANY account by name, including the owner's, with no
        guard beyond "not the last account left." A guest handed a tablet could
        boot the owner and (before the matching api_users_add fix) mint itself
        a durable login in the same motion. See the old state doc's Access &
        accounts section for the full reasoning; api_users_add closes the
        other half (a LAN session can no longer register a new account either).

        Refuses to remove the LAST remaining account: that would leave zero
        accounts, re-triggering the local-only bootstrap state and effectively
        locking out every remote LAN user until someone re-bootstraps from the
        server machine itself -- a real self-lockout risk, guarded against
        explicitly rather than left as a footgun. This applies even to a local
        session removing itself.

        The "how many accounts exist" check and the removal happen in ONE call
        to core.remove_web_user_guarded() (a single _accounts_lock acquisition),
        not a separate list_web_users() read followed by a separate
        remove_web_user() write -- the latter shape was a TOCTOU race,
        reproduced live against this real route (adversarial review,
        2026-07-19): with exactly 2 accounts, two concurrent removes of two
        DIFFERENT usernames could each read "2 accounts, safe to proceed" before
        either write landed, and both writes would go through -- leaving
        AUTH_USERS empty, the exact self-lockout this guard exists to prevent."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        username = str(body.get("username") or "").strip()
        if username != session.get("user") and not _is_local_request():
            return jsonify({"error": "localhost-only to remove another account"}), 403
        from moonglade import backup as core
        result = _web_accounts.remove_web_user_guarded(username)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "last_account":
            return jsonify({"error": "Can't remove the last remaining account -- "
                                     "that would lock every remote device out until "
                                     "someone signs in locally to bootstrap a new one."}), 400
        # S10: a removed login's per-login folder (prefs, state, snippets, presets, saved
        # views) goes with it.
        _web_accounts.remove_login_files(out_dir, username)
        return jsonify({"ok": True, "username": username})

    @app.route("/api/users/password", methods=["POST"])
    @tier(LOGIN)
    def api_users_password():
        """Change an account's password from the Panel's Users tab.

        Closes the last CLI-only account operation: until now a forgotten gallery password could
        only be reset with `--add-web-user` on the server machine (its add-or-update semantics
        doubling as a reset). Owner decision 2026-07-26: a user may change THEIR OWN password from
        anywhere, and changing anyone else's is an owner-machine action.

        Reading the code turned that into a single rule rather than two code paths, because the
        cases differ in exactly one respect -- whether the CURRENT password must be proved:

            LOCALHOST     may set ANY account's password without the current one.
            non-local     may set only its OWN, and must prove the current one.

        Both halves are load-bearing. Without the first, the forgotten-password case is not fixed
        at all, which is the entire point of the item -- and requiring the old password at the
        machine protects nothing, since anyone sitting there can edit config.json directly. Without
        the second, an already-authenticated LAN session -- a tablet left unlocked on the
        network -- could silently change the owner's password and lock him out of his own account,
        needing nothing but an open browser tab.

        The username check mirrors `api_users_remove` deliberately rather than inventing a stricter
        shape: an omitted username means "me", and a supplied one that is not yours demands
        LOCALHOST. That route's trust model has already survived an adversarial review, and
        consistency with it is worth more here than a second convention.

        The write bumps `sess_epoch`, so every session cookie issued under the old password stops
        working immediately -- which is the point on other devices and merely rude on this one. So
        when the caller changed their OWN password, this re-issues the current session's epoch: the
        browser you are standing in front of stays signed in, every other device drops. A local
        reset of SOMEONE ELSE's password deliberately does not do that, because the whole intent
        there is to evict whoever was using it.
        """
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        me = session.get("user")
        local = _is_local_request()
        target = str(body.get("username") or "").strip() or me
        new_pw = str(body.get("new_password") or "")

        if target != me and not local:
            return jsonify({"error": "localhost-only to change another account's password"}), 403
        # Same policy the Users tab already enforces when ADDING an account -- one rule, one
        # place, so a password that could not be registered cannot be set here either.
        problem = _web_accounts.password_problem(new_pw)
        if problem:
            return jsonify({"error": problem}), 400

        # None means "do not check" and is reserved for a caller already proven local.
        current = None if local else str(body.get("current_password") or "")
        if current is not None and not current:
            return jsonify({"error": "Enter your current password."}), 400

        result = _web_accounts.set_web_user_password_guarded(target, new_pw, current_password=current)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "bad_current":
            # Deliberately the same wording whether the account exists or not by this point --
            # the caller has already been established as the owner of `target` or as local, so
            # there is nothing left to leak, but keeping it vague costs nothing.
            return jsonify({"error": "That current password isn't right."}), 403

        if target == me:
            session["sess_epoch"] = _web_accounts.get_web_user_session_epoch(me)
        return jsonify({"ok": True, "username": target,
                        "signed_out_elsewhere": True,
                        "still_signed_in_here": target == me})

    @app.route("/api/ping")
    @tier(LOGIN)
    def api_ping():
        """Cheap liveness probe — the Stop/Restart reconnect overlay polls this. Login required
        (any session, local or LAN)."""
        return jsonify({"ok": True})

    @app.route("/api/server/stop", methods=["POST"])
    @tier(LOGIN)
    def api_server_stop():
        """Shut the server down cleanly from the browser (Homebridge-style) instead of Task
        Manager. Login required (any session, local or LAN). Under the managed launcher this ends the whole app.

        Refused while a maintenance job is running, because os._exit kills only THIS
        process: the job's subprocess would outlive it, still walking the library with
        nothing reading its output and nothing able to cancel it. The Panel already says
        so -- Stop and Restart carry class 'jobbtn', which poll() disables for the life of
        a job -- but that is the browser's copy of the rule, and a tab loaded before the
        job started (or a second tab) still has live buttons. This is the same rule, kept
        where it cannot be bypassed. Cancel the job first; that is what it is for."""
        from moonglade.gallery import _schedule_server_exit
        if _update_busy():
            return _update_busy_refusal()
        busy = _job_busy()
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't shut down while it works).".format(busy)}), 409
        _note_power_request("Stop")
        _schedule_server_exit(0)
        return jsonify({"ok": True, "action": "stop"})

    @app.route("/api/library-path", methods=["GET", "POST"])
    @tier(LOGIN, POST=LOCALHOST)
    def api_library_path():
        """Read or set the library folder (settings.json's library_dir).

        LOCALHOST-ONLY on write: it decides which folder every later start opens (and the
        command line and the MCP server with it), so it sits in the same trust class as
        /api/setup/save-key and /api/branding/shortcut. GET is LOGIN -- the Panel shows the
        current folder to whoever can already see the Panel, and it is the same host path
        /panel already withholds from non-local callers, so it is withheld here too.

        Setting this moves nothing by itself, and the old folder is left exactly as it is: it
        points the app at a different folder on the next start, and there is no "migrate"
        option here to get wrong. That next launcher or server start does tidy the new folder
        when it holds an older Moonglade's layout (moonglade.migrate): its records come into
        its _moonglade folder -- only what is Moonglade's by its content; a folder of someone's
        own that merely shares an old name (logs, loom, branding) is left alone. A folder
        that is the program's own, or holds a Moonglade program, is refused here
        (moonglade.migrate.library_refusal), since every start would refuse it too.
        """
        from moonglade.gallery import DEFAULT_LIBRARY_DIR, Path, _supervised
        from moonglade import backup as _core
        if request.method == "GET":
            local = _is_local_request()
            # BOTH path fields are withheld from a non-local caller, not just the first.
            # POST stores an ABSOLUTE path, so `stored` is the host path too -- blanking
            # `path` while returning `stored` handed it straight back, defeating the
            # withholding that /panel and this route's own docstring promise. `configured`
            # says whether a folder is set without saying where it is, which is all the
            # Panel needs to decide what to show.
            stored = _settings.library_dir()
            return jsonify({
                "path": str(out_dir) if local else "",
                "stored": stored if local else "",
                "configured": bool(stored),
                "default": DEFAULT_LIBRARY_DIR,
                "local": local,
                "supervised": _supervised(),
            })
        body = request.get_json(silent=True) or {}
        want = str(body.get("path") or "").strip().strip('"')
        if not want:
            return jsonify({"error": "Enter a folder path."}), 200
        try:
            target = Path(want).expanduser()
            # Stored absolute: the server's working directory is the launcher's folder, and
            # a relative path stored here would silently mean somewhere else the moment
            # anything started it from elsewhere (a scheduled task, a terminal, a shortcut).
            target = (target.resolve() if target.is_absolute()
                      else (_paths.run_dir() / target).resolve())
        except (OSError, ValueError) as e:
            return jsonify({"error": "That path isn't usable: {}".format(e)[:160]}), 200
        if target.exists() and not target.is_dir():
            return jsonify({"error": "That path is a file, not a folder."}), 200
        from moonglade import migrate as _migrate
        refused = _migrate.library_refusal(target)
        if refused:
            return jsonify({"error": "That folder can't be a library: {}. Choose a folder of "
                                     "its own.".format(refused)}), 200
        if not target.exists():
            if not body.get("create"):
                return jsonify({"needs_create": True, "path": str(target),
                                "error": "That folder doesn't exist yet."}), 200
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return jsonify({"error": "Couldn't create it: {}".format(
                    _redact_host_paths(str(e)))[:160]}), 200
        # Written only AFTER the folder is known good -- never write first and hope, the
        # same order /api/setup/save-key follows for the API key. settings.json is written
        # whole under its own lock (moonglade.settings), never config.json.
        try:
            _settings.set_values(**{_settings.LIBRARY_DIR: str(target)})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": "Couldn't save the setting: {}".format(
                _redact_host_paths(str(e)))[:160]}), 200
        has_catalog = (target / "catalog.db").exists()
        return jsonify({"ok": True, "path": str(target), "has_catalog": has_catalog,
                        "supervised": _supervised(), "restart_needed": str(target) != str(out_dir)})

    @app.route("/api/server/restart", methods=["POST"])
    @tier(LOGIN)
    def api_server_restart():
        """Restart the server from the browser. Needs the managed launcher (Moonglade Launcher),
        which relaunches on exit code 42; otherwise the process would just stop. Login required (any session, local or LAN)."""
        from moonglade.gallery import _schedule_server_exit, _supervised
        if not _supervised():
            return jsonify({"error": "Restart needs the managed launcher — start via "
                                     "'Moonglade Launcher'. (Stop still works.)"}), 409
        # An update restarts the server ITSELF when it is done; a restart in the middle of
        # one would land the process on half-pulled code. (The updater's own restart does
        # not come through here -- see _update_busy.)
        if _update_busy():
            return _update_busy_refusal()
        busy = _job_busy()                       # same rule as Stop -- see api_server_stop
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't restart while it works).".format(busy)}), 409
        _note_power_request("Restart")
        _schedule_server_exit(42)
        return jsonify({"ok": True, "action": "restart"})

    @app.route("/api/update/check")
    @tier(LOGIN)
    def api_update_check():
        """Is a newer release out?

        Two cadences, one answer. In the background the server re-checks roughly hourly
        and announces what it finds (run_update_tick, off the scheduler's existing tick --
        owner ruling 2026-09-04, reversing 2026-09-01's "no background tick anywhere").
        Here, `?fresh=1` is the Control Panel OPENING: it bypasses the 30-minute cache,
        floored at UPDATE_PANEL_FLOOR seconds, so ten opens in a minute still cost GitHub
        one request. Any other caller reads the cache exactly as before.

        Never fails the Panel: an offline machine gets behind:false with the reason
        attached, at 200. See check_for_update for why the failure is not cached.

        This route only ever ANSWERS. Applying an update is /api/update/apply, behind the
        modal's explicit confirm -- nothing here can reach it."""
        from moonglade import backup as core
        if str(request.args.get("fresh") or "").lower() in ("1", "true", "yes"):
            return jsonify(_updater.check_for_update_fresh(core.__version__))
        payload = _updater.check_for_update(core.__version__)
        _updater.note_update_transition(payload)
        return jsonify(payload)

    @app.route("/api/update/status")
    @tier(LOGIN)
    def api_update_status():
        """The phase the apply is in, for the modal to poll:
        idle | backup | pulling | deps | restarting | failed (with the tool's verbatim error).
        `backup` names the catalog copy made before the pull, once it exists.

        The error is redacted on the way OUT, not on the way in: git and pip name real
        paths, and this payload is readable by any logged-in device on the LAN. The
        unredacted copy stays where it belongs -- the server's own console/log."""
        st = _updater.update_state()
        if st.get("error"):
            st["error"] = _redact_host_paths(st["error"])
        return jsonify(st)

    @app.route("/api/update/apply", methods=["POST"])
    @tier(LOGIN)
    def api_update_apply():
        """Pull the new release and restart into it. NEVER SILENT: the modal's explicit
        confirm is required, and this is the CSRF explicit-token class -- a real system
        mutation off one web click, the same class as publish and the user-admin routes.

        Every refusal names its own reason, because "no" without a why is the thing that
        makes a person start deleting files. Each also carries a machine-readable `kind`
        (2026-09-04, Identity Chrome handoff C2) so the modal can PRESENT it correctly
        without guessing from the wording: "busy" means come back in a minute and nothing
        is wrong (a job is running, or an apply already is); "failed" means this install
        will refuse until something is changed. The third presentation the modal has --
        offline -- is not a payload at all: it is the absence of one, decided client-side
        when the request never reached this server. Adding the field rather than
        string-matching the message is deliberate: the reasons below get reworded (three
        of them did in v3.7.2), and a UI keyed to their prose would silently mis-colour
        the next time one does. The gates:
          * confirm + CSRF          -- it was actually asked for, by this session
          * READ_ONLY               -- belt. Not a PixAI spend, but the owner's flag says
                                       "don't change my install", and this changes the
                                       install more than anything else here does
          * supervised              -- without the managed launcher, exit 42 stops the
                                       server instead of relaunching it: an update would
                                       be indistinguishable from "the app vanished"
          * no running panel job    -- same rule Restart uses; a pull under a running job
                                       swaps the code out from under it
          * on master               -- the recovered scope's own out-of-scope rule: a
                                       feature branch is somebody mid-work, not a stale
                                       install
          * no tracked edits        -- the update owns those paths and is about to write
                                       them; --ff-only would refuse anyway, and refusing
                                       here says WHICH files instead of a git error
          * no untracked file at a  -- and ONLY those. A stray folder the release has
            path the update writes     never heard of is not a reason to refuse: real
                                       installs collect them, and blocking on all of them
                                       (as the first live apply did, over a personal
                                       `boop/`) refuses every real machine forever
        The work itself runs off the panel-job slot on its own single-flight thread, so
        the restart it asks for cannot be refused by the job it is itself.

        WHY LOGIN AND NOT LOCALHOST, recorded because this route shells out and is the
        obvious candidate for the stricter tier: it runs FIXED arguments (no part of the
        request reaches a command line) against the owner's own repository over HTTPS,
        and it is deliberately LOGIN per the owner-approved P4 scope -- "every user, one
        click" -- and the Restart precedent it is modelled on, which is LOGIN for the same
        reason: the person who can restart this server should be able to update it."""
        from moonglade.gallery import _supervised
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again.",
                            "kind": "failed"}), 400
        if not body.get("confirm"):
            return jsonify({"error": "confirm required — the update is never applied silently",
                            "kind": "failed"}), 400
        from moonglade import backup as core
        if core.READ_ONLY or core._read_only_now():
            return jsonify({"error": "READ_ONLY is set in config.json — refusing to update "
                                     "this install. Remove it (or set it to false) to allow "
                                     "this.", "kind": "failed"}), 409
        if not _supervised():
            return jsonify({"error": "Updating needs the managed launcher — start via "
                                     "'Moonglade Launcher'. (Without it the server would stop "
                                     "instead of restarting into the new version.)",
                            "kind": "failed"}), 409
        busy = _job_busy()
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the code can't change while it works).".format(busy),
                            "kind": "busy"}), 409
        rc, branch = _updater._git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = (branch or "").strip()
        if rc != 0:
            return jsonify({"error": "couldn't read this checkout's branch: "
                                     + _redact_host_paths(branch)[:200],
                            "kind": "failed"}), 409
        if branch != "master":
            return jsonify({"error": "this checkout is on '%s', not master — updating a "
                                     "feature branch is out of scope. Switch to master "
                                     "first." % branch[:60], "kind": "failed"}), 409
        rc, dirty = _updater._git(["status", "--porcelain"])
        if rc != 0:
            return jsonify({"error": "couldn't read this checkout's state: "
                                     + _redact_host_paths(dirty)[:200],
                            "kind": "failed"}), 409
        tracked, untracked = _updater.split_porcelain(dirty)
        if tracked:
            return jsonify({"error": "this checkout has uncommitted changes — the update "
                                     "would overwrite them. In the way: "
                                     + _redact_host_paths(", ".join(tracked[:6])),
                            "kind": "failed"}), 409
        # The release the modal offered, and only that (app security review 2026-11-19,
        # finding 10): the apply fast-forwards to this tag's commit, never master's head.
        # Read from the last check, never fetched here.
        tag = _updater.announced_release()
        if not tag:
            return jsonify({"error": "no release has been announced to this install yet — "
                                     "open the Control Panel so it checks, then try again.",
                            "kind": "failed"}), 409
        cur_v, tag_v = _updater.version_tuple(core.__version__), _updater.version_tuple(tag)
        if cur_v and tag_v and tag_v <= cur_v:
            return jsonify({"error": "this install is already on %s or newer." % tag,
                            "kind": "failed"}), 409
        # Untracked entries are judged against what the update actually brings, not
        # blocked on sight -- see split_porcelain and untracked_in_the_way. This costs a
        # fetch, but only on a checkout that HAS stray files, and only the fetch the apply
        # was about to do regardless.
        ignored_untracked = 0
        if untracked:
            incoming, why = _updater.incoming_paths(tag)
            if incoming is None:
                return jsonify({"error": "couldn't work out what the update brings, so "
                                         "whether your untracked files are in its way is "
                                         "unknown — and this won't guess. git said: "
                                         + _redact_host_paths(why)[:300],
                                "kind": "failed"}), 409
            clash = _updater.untracked_in_the_way(untracked, incoming)
            if clash:
                return jsonify({"error": "an untracked file is where the update needs to "
                                         "write: "
                                         + _redact_host_paths(", ".join(clash[:6]))
                                         + " — move or delete it, then try again.",
                                "kind": "failed"}), 409
            ignored_untracked = len(untracked)
        with _updater._update_lock:
            if _updater._update_state["phase"] not in ("idle", "failed"):
                return jsonify({"error": "an update is already running", "kind": "busy"}), 409
            _updater._update_state.update(phase="backup", error="", at=time.time(), backup="")

        def _restart():
            # The SAME gates the restart route applies, re-checked at the moment it
            # actually happens rather than trusted from a minute ago -- then the same
            # one call it makes. Not a second restart mechanism.
            from moonglade.gallery import _note_server_exit, _schedule_server_exit, _supervised
            if not _supervised():
                raise RuntimeError("the managed launcher is gone")
            still = _job_busy()
            if still:
                raise RuntimeError('"%s" started while updating' % still)
            _schedule_server_exit(42)
            _note_server_exit("by the update just applied")

        # The activity log is the ONLY part of this that survives the restart a successful
        # update is about to trigger -- and the only record at all of one that failed while
        # nobody was watching the modal. Redacted like every other LAN-visible string.
        job_id = "update-" + secrets.token_hex(6)

        # ...and if the tree had stray files this update deliberately left alone, the log
        # line says how many. The record has to show that the guard chose to proceed --
        # otherwise "it updated over my files" and "it updated beside my files" leave the
        # same trace, and only one of those is a bug worth chasing.
        label = "Updated Moonglade"
        if ignored_untracked:
            label += " (ignored untracked: %d)" % ignored_untracked

        def _log_update(status, error=""):
            _log_job(job_id, status=status, type="update", label=label,
                     error=(_redact_host_paths(error)[:600] or None))

        threading.Thread(target=_updater.run_update, args=(_restart, tag),
                         kwargs={"log_fn": _log_update,
                                 "backup_fn": lambda: _updater.backup_catalog(db_path)},
                         daemon=True).start()
        return jsonify({"ok": True, "phase": "backup"})

    @app.route("/api/bonjour/status")
    @tier(LOGIN)
    def api_bonjour_status():
        """Live Bonjour/mDNS state for the Control Panel chip: is it broadcasting, under what
        name, at which reachable URLs, and is zeroconf even installed. Login required (local or
        LAN) -- reading the broadcast state is safe for a LAN device; only WRITING the settings
        (below) is localhost-only."""
        from moonglade.gallery import DEFAULT_PORT, _SERVER_CONTROL, _supervised
        from moonglade import bonjour as moonglade_bonjour
        cfg = _settings.server()
        serving = _SERVER_CONTROL.get("serving") or {}
        adv = _SERVER_CONTROL.get("bonjour")
        host = str(serving.get("host") or cfg["host"])
        try:
            port = int(serving.get("port") or cfg["port"])
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        scheme = str(serving.get("scheme") or "http")
        enabled = bool(cfg["bonjour_enabled"])
        name = str(cfg["bonjour_name"])
        broadcasting = bool(adv is not None and adv.active)
        hostname = adv.hostname if broadcasting else moonglade_bonjour.hostname_label(name) + ".local"
        lan_bind = moonglade_bonjour.is_lan_bind(host)
        ip = adv.ip if broadcasting else moonglade_bonjour.lan_ip()
        urls = []
        if lan_bind and ip:
            urls = ["{}://{}:{}/".format(scheme, hostname, port),
                    "{}://{}:{}/".format(scheme, ip, port)]
        return jsonify({
            "enabled": enabled, "broadcasting": broadcasting, "name": name,
            "host": host, "port": port, "scheme": scheme, "hostname": hostname,
            "lan_bind": lan_bind, "lan_ip": ip, "reachable_urls": urls,
            "zeroconf_available": moonglade_bonjour.zeroconf_available(),
            "supervised": _supervised(),
            # HTTPS on the home network (moonglade.tls): the mode this start runs in, the
            # certificate's SHA-256 fingerprint for a device to check its warning against
            # (public, like the certificate itself), and why there is none when there isn't.
            "tls": str(app.config.get("MG_TLS_MODE") or "off"),
            "tls_fingerprint": str(app.config.get("MG_TLS_FINGERPRINT") or ""),
            "tls_problem": str(app.config.get("MG_TLS_PROBLEM") or ""),
        })

    @app.route("/moonglade-ca.crt")
    @tier(PUBLIC)
    def moonglade_ca_certificate():
        """This PC's certificate authority (moonglade.tls), for a phone, tablet or Mac to
        install once so its browser stops warning. PUBLIC: a certificate is public by nature --
        the server hands the same one to every client in every handshake -- and a device
        fetches it before it signs in. The person checks its SHA-256 fingerprint against the
        LAN card on the PC before trusting it. 404 when this start has no HTTPS."""
        from moonglade import tls as _tls_mod
        p = _tls_mod.ca_cert_path()
        if not app.config.get("MG_TLS_FINGERPRINT") or not p.is_file():
            return app.response_class("This Moonglade isn't serving HTTPS, so it has no "
                                      "certificate to install.", status=404,
                                      mimetype="text/plain")
        resp = send_file(str(p), mimetype="application/x-x509-ca-cert", as_attachment=True,
                         download_name="Moonglade-this-PC.crt", max_age=0)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.route("/api/bonjour/settings", methods=["POST"])
    @tier(LOGIN, POST=LOCALHOST)
    def api_bonjour_settings():
        """Write the Bonjour/mDNS settings (settings.json) and apply what can change live.
        Broadcast on/off and the name apply immediately (re-register); the bind host/port are
        launch-time, so those return restart_needed. LOCALHOST-only on write: a LAN device may
        SEE the state but only the server box may change how the server is exposed."""
        from moonglade.gallery import _SERVER_CONTROL, _supervised
        from moonglade import bonjour as moonglade_bonjour
        body = request.get_json(silent=True) or {}
        cfg = _settings.server()
        enabled = bool(body["enabled"]) if "enabled" in body else bool(cfg["bonjour_enabled"])
        name = str(body.get("name") if body.get("name") is not None
                   else cfg["bonjour_name"]).strip()
        new_host = str(body.get("host") if body.get("host") is not None
                       else cfg["host"]).strip()
        raw_port = body.get("port", cfg["port"])
        if not name:
            return jsonify({"error": "A name is required."}), 200
        if new_host not in ("127.0.0.1", "0.0.0.0"):
            return jsonify({"error": "Host must be 127.0.0.1 (this machine only) or 0.0.0.0 (LAN)."}), 200
        try:
            new_port = int(raw_port)
            if not (1 <= new_port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Port must be a whole number between 1 and 65535."}), 200
        try:
            _settings.set_values(**{_settings.BONJOUR: {"enabled": enabled, "name": name},
                                    _settings.HOST: new_host, _settings.PORT: new_port})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": "Couldn't save the setting: {}".format(
                _redact_host_paths(str(e)))[:160]}), 200
        # Apply live what needs no rebind: stop, then (re)start if it should be on, using the
        # CURRENTLY-serving host/port -- a host/port CHANGE only takes effect on the next restart.
        serving = _SERVER_CONTROL.get("serving") or {}
        cur_host = str(serving.get("host") or new_host)
        cur_port = int(serving.get("port") or new_port)
        adv = _SERVER_CONTROL.get("bonjour")
        broadcasting = False
        if adv is not None:
            adv.stop()
            if enabled and moonglade_bonjour.is_lan_bind(cur_host):
                broadcasting = adv.start(name, cur_port, str(serving.get("scheme") or "http"))
        restart_needed = (new_host != cur_host) or (new_port != cur_port)
        hostname = adv.hostname if (adv is not None and adv.active) else moonglade_bonjour.hostname_label(name) + ".local"
        return jsonify({"ok": True, "enabled": enabled, "name": name, "host": new_host,
                        "port": new_port, "broadcasting": broadcasting, "hostname": hostname,
                        "restart_needed": restart_needed, "supervised": _supervised()})

    @app.route("/export-csv")
    @tier(LOGIN)
    def export_csv_download():
        """Download the catalog as a CSV -- from the browser you get a real file (Downloads),
        not a copy silently written into the backup folder. Built in memory. Authorized only.

        Honours the gallery grid's OWN filter query string (?q=&model=&collection=&rating_min=
        &media=&from_year=...), so exporting from a filtered view exports that view rather
        than the whole library. With no filter args it stays the full dump it has always
        been -- load_catalog, not query_catalog, because the latter's `filename != ''`
        would quietly drop rows whose file isn't on disk yet."""
        from moonglade.curation import _filters_from_args, query_catalog
        from moonglade.catalog import catalog_csv_text, load_catalog
        import io
        import datetime
        filters = _filters_from_args(request.args)
        if filters:
            # ONE unpaginated query (page_size=None), deliberately. This used to COUNT the
            # matches and then ask a SECOND, later query for exactly that many rows, with no
            # lock or transaction across the pair -- so a catalog write landing in the gap
            # left the second query's LIMIT sized to the OLD count. The everyday case is not
            # exotic: "Sync now" is a Panel job that inserts rows for minutes at a time while
            # the owner keeps browsing, and the export it produced mid-sync shipped fewer
            # rows than matched with nothing in the file saying so. A single SELECT reads one
            # snapshot and cannot disagree with itself. `sort` isn't a filter (it never
            # changes WHICH rows match) so it stays a separate argument -- and an unknown
            # value falls back to the default order inside query_catalog.
            rows, _ = query_catalog(db_path, page=1, page_size=None,
                                    sort=request.args.get("sort", "newest"), **filters)
        else:
            rows = load_catalog(db_path)
        mem = io.BytesIO(catalog_csv_text(rows).encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="text/csv", as_attachment=True,
                         download_name="moonglade-catalog-{}.csv".format(
                             datetime.date.today().isoformat()))

    @app.route("/export-curation")
    @tier(LOGIN)
    def export_curation_download():
        """Download the curation sidecar -- ratings, hand-picked collections and their manual
        order, smart collections, and the personal layer (tags, keeper/reject, notes) -- as
        one JSON file keyed by media id (moonglade/curation_io.py). The same browser
        download as /export-csv beside it, built in memory, never written into the library.
        It goes back in with `--import-curation` (dry run by default)."""
        import io
        import datetime
        from moonglade import curation_io as cio
        mem = io.BytesIO(cio.dumps(cio.export_curation(db_path)).encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="application/json", as_attachment=True,
                         download_name="moonglade-curation-{}.json".format(
                             datetime.date.today().isoformat()))

    @app.route("/api/panel/run", methods=["POST"])
    @tier(LOGIN)
    def api_panel_run():
        """Start a whitelisted maintenance job as a background subprocess. Safe/read-only
        actions are open to any authorized session (local or logged-in LAN); destructive
        actions (file-changing -- organize, dedup --apply, rebuild-thumbnails) additionally
        require the request to be from the local machine itself, same trust tier as
        /api/branding/shortcut -- a logged-in LAN account can generate and browse, but not
        run destructive maintenance on the owner's local files. Destructive actions also
        require confirm=true."""
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip()
        spec = PANEL_ACTIONS.get(action)
        if not spec:
            return jsonify({"error": "unknown action"}), 400
        if spec["destructive"] and not _is_local_request():
            return jsonify({"error": "this action changes files; localhost-only"}), 403
        if spec["destructive"] and not body.get("confirm"):
            return jsonify({"error": "this action changes files; confirm required"}), 400
        # The mirror of the apply route's own job check: code must not change under a
        # running job, and a job must not start under a changing codebase.
        if _update_busy():
            return _update_busy_refusal()
        # The published-artwork sweep writes the same catalog rows these jobs do, and it is
        # in-process rather than in the job slot, so _panel_run refuses one while the other
        # is in flight. The refusal is re-stated here only so the click gets a reason it can
        # read: _panel_run answers False for "the slot is taken" too, and "a job is already
        # running" would be the wrong sentence for a sweep that has no slot.
        if action in _living.ARTWORKS_TOUCHING_ACTIONS and _living.artworks_sweep_in_flight():
            return jsonify({"error": "the published-artwork sweep is reading PixAI into "
                                     "these same rows right now — wait a moment and press "
                                     "Run now again"}), 409
        try:
            # `n` is only consumed by an int_param action (test-pull); _panel_run
            # clamps it into range and ignores it otherwise, so passing it always is safe.
            # The busy check lives INSIDE _panel_run, under the same lock that claims the
            # slot -- checking it here first would just be the race again.
            # THE FOLLOW-ON IS A PROPERTY OF THE ACTION, not of who started it. The wiki
            # states the chain as a plain fact about Sync now -- "the one-shot refresh,
            # then a perceptual-hash backfill straight after it" -- and it was true only
            # when the living library's own tick was the trigger. A click got the sync
            # alone. Looked up from the same table _living_run reads, so there is one
            # answer to "what follows this job".
            if not _panel_run(action, int_arg=body.get("n"),
                              then=_living.LIVING_BY_ACTION.get(action, {}).get("then")):
                return jsonify({"error": "a job is already running"}), 409
            return jsonify({"ok": True, "action": action, "label": spec["label"]})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    def _close_orphan_if_resolved(tid, media_ids, is_video):
        """A task-id recovery (below) just independently confirmed real media for `tid`.
        If `tid` ALSO has its own job entry that's still non-terminal -- the orphan case:
        api_task_status()'s own done/failed write never ran for it (its polling browser
        tab stopped, or a transient exception left it at 'running' per that route's
        deliberate design), so it's been spinning in the Activity card forever even
        though the generation finished -- close THAT original entry too, not just the
        new 'import-<suffix>' job api_import_task logs for the recovery action itself.
        Otherwise the Activity card keeps showing a phantom stuck spinner permanently
        disconnected from reality, even after the real media has landed.

        Writes the EXACT event shape api_task_status()'s own done branch writes
        (status='done', media_ids, is_video) so a reader of jobs.jsonl can't tell "task-
        status resolved it" from "a manual recovery resolved it" -- same file, same
        fields, same convention.

        Reads the RAW reconstructed log (core._reconstruct_jobs), not read_jobs()'s
        filtered view, so a very old orphan -- one read_jobs() would already be hiding
        past JOBS_MAX_AGE -- still gets closed rather than silently left at 'running' in
        the log forever. Skips a job the owner already dismissed (respects that explicit
        action instead of resurrecting it with a new event). Fails soft: the recovery
        itself must succeed even if this bookkeeping doesn't."""
        try:
            from moonglade import backup as _core
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            orig = jobs_by_id.get(tid)
            if orig and not orig.get("dismissed") and orig.get("status") not in _jobs._JOBS_TERMINAL:
                _log_job(tid, status="done", media_ids=media_ids, is_video=is_video)
        except Exception:                          # noqa: BLE001 -- bookkeeping must not break recovery
            pass

    @app.route("/api/import-task", methods=["POST"])
    @tier(LOGIN)
    def api_import_task():
        """Pull ONE generation/edit task's media into the gallery by its task id -- recovers
        edits + anything stuck in Favorites that --update's listing skips (edits aren't in that
        listing). Downloads the owner's OWN finished media; spends nothing.

        LOGIN tier, deliberately -- any signed-in session, local or LAN. This docstring
        used to say "Localhost-only", which was never true of the code and is exactly the
        bait a route-gating audit warned about: a stale claim like this invites someone to
        "restore" a gate that was never there, silently breaking the LAN-recovery case.
        The real tier is pinned by dev/tests/test_route_tiers.py.

        Logs to the Activity card. Returns {saved, media_ids, is_video} or {error}."""
        from moonglade.catalog_verbs import task_media
        tid = str((request.get_json(silent=True) or {}).get("task_id") or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "enter a numeric task id"}), 200
        # "Look behind the milk": if this task is already catalogued, don't re-fetch --
        # just report it's here + hand back its media so the UI can jump straight to it.
        pre_rows = task_media(db_path, tid)
        if pre_rows:
            pre = [r["media_id"] for r in pre_rows]
            _close_orphan_if_resolved(tid, pre, bool(pre_rows[0]["is_video"]))
            return jsonify({"ok": True, "already": True, "saved": 0, "media_ids": pre})
        job_id = "import-" + tid[-8:]
        _log_job(job_id, status="running", type="import", label="Import task " + tid)
        try:
            core, session = _gen_session()
            res = _collect_single_flight(core, session, tid)
            n, mids = int(res.get("saved") or 0), (res.get("media_ids") or [])
            _log_job(job_id, status="done", media_ids=mids,
                     label="Imported {} media from task {}".format(n, tid))
            if mids:
                _close_orphan_if_resolved(tid, mids, bool(res.get("is_video")))
            return jsonify({"ok": True, "saved": n, "media_ids": mids,
                            "is_video": bool(res.get("is_video"))})
        except Exception as e:
            _log_job(job_id, status="failed", error=_redact_host_paths(str(e))[:200])
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/panel/status")
    @tier(LOGIN)
    def api_panel_status():
        """Live state of the running maintenance job, for the Panel's progress UI.

        `lines` is LOOPBACK-ONLY; the rest of the payload is not. The two halves of this
        response are different KINDS of data: status/action/label/rc/progress describe the
        job, but `lines` is the maintenance subprocess's own stdout -- absolute paths out of
        the owner's install, catalog internals, and whatever a CLI traceback happens to
        print. That is host detail, and Moonglade is explicitly not single-user, so a
        logged-in LAN account must not be able to poll it. See the Trust & Safety wiki page.

        Found 2026-07-21 by an adversarial review: STARTING a destructive job was gated
        (api_panel_run's `spec["destructive"] and not _is_local_request()`) and CANCELLING
        one was gated (api_panel_cancel), but READING the output was a bare `@app.route`
        with no tier check at all -- the one door in the set nobody had shut.

        Deliberately NOT a whole-route LOCALHOST gate, which is the obvious-looking fix and
        is wrong here: 14 of the 20 PANEL_ACTIONS are non-destructive, and a LAN account is
        allowed to run every one of them (api_panel_run only requires loopback when
        `spec["destructive"]`). Gating the whole route would let that account start a job
        and then watch a progress UI that never moves, across all three pollers (the Panel,
        the job tray, and the resume-on-load check). Redacting one field closes the leak
        without taking away anything a LAN caller is entitled to. The tier table entry
        therefore correctly stays LOGIN (dev/tests/test_route_tiers.py).

        The replacement line is a real line rather than `[]` so the log area explains itself
        instead of just rendering blank, which reads as a bug -- the consumer at ~7385 does
        `if (d.lines) { log.textContent = d.lines.join('\\n') }`, and `[]` is truthy in JS."""
        from moonglade.gallery import _power_in_progress
        local = _is_local_request()
        with _panel_lock:
            lines = (list(_panel_job["lines"]) if local
                     else ["(job output is shown only on the server's own screen)"])
            return jsonify({"status": _panel_job["status"], "action": _panel_job["action"],
                            "label": _panel_job["label"], "rc": _panel_job["rc"],
                            "progress": _panel_job["progress"],
                            "warn_count": _panel_job.get("warn_count") or 0,
                            # "stop" | "restart" while one is under way, else "" (#84): the
                            # panel resumes its reconnect watch from this on mount.
                            "power": _power_in_progress(),
                            "lines": lines})

    @app.route("/api/watch/status")
    @tier(LOGIN)
    def api_watch_status():
        """Live-mirror watcher health: is the push WebSocket connected right now, when
        did it last see an event, how many gens has it mirrored this server run."""
        with _watch_lock:
            out = dict(_watch_status)
            out["task_stream"] = dict(_watch_status["task_stream"])
            return jsonify(out)

    @app.route("/api/panel/cancel", methods=["POST"])
    @tier(LOCALHOST)
    def api_panel_cancel():
        """Stop the running maintenance job from the browser (no Task Manager). Terminates the
        subprocess; the reader marks it 'cancelled'.

        LOCALHOST-ONLY, and the check below is load-bearing: it was silently deleted in
        commit 0fd8cee -- the very commit that built the two-tier model for the sibling
        route /api/panel/run -- while this docstring's "Localhost-only" claim survived.
        Restored 2026-07-19 after a route-gating audit. This is the paired STOP control
        for jobs whose START requires loopback, so admitting a LAN caller here is the
        same trust violation from the other end: organize flushes its undo manifest per
        row but only writes catalog_updates via save_catalog() AFTER the loop, so a
        mid-run terminate leaves files physically moved on disk while catalog.db still
        points at their old paths. Undo survives; catalog/disk coherence does not."""
        with _panel_lock:
            proc = _panel_job.get("proc")
            running = _panel_job["status"] == "running"
            if running and proc is not None:
                _panel_job["cancelled"] = True
        if not (running and proc is not None):
            return jsonify({"ok": False, "error": "no job is running"}), 200
        try:
            proc.terminate()   # reader sees stdout close -> finalizes status as 'cancelled'
        except Exception as e:
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:140]}), 200
        return jsonify({"ok": True, "action": "cancel"})

    @app.route("/api/panel/schedule", methods=["GET", "POST"])
    @tier(LOGIN, POST=LOCALHOST)
    def api_panel_schedule():
        """Panel settings: the automated-task schedule + the download-workers count. GET
        returns the current settings; POST MERGES only the fields present (so the schedule
        toggle and the workers selector -- two separate controls writing this one file --
        never wipe each other). Only non-destructive actions are schedulable.

        GET is login-only so a LAN session's Panel still renders the current settings.
        WRITING is LOCALHOST-ONLY -- that check was silently dropped in commit 0fd8cee
        while this docstring's claim survived; restored 2026-07-19 after a route-gating
        audit. It matters more than "it's only settings" suggests: `sync-videos` is a
        real PANEL_ACTIONS key with destructive=False AND panel_visible=False, so a LAN
        caller could schedule a full-history feed sync at 16 workers, hourly, forever,
        surviving restarts -- via a background-only job with no Panel button, so the
        owner would never see it configured. And `workers` is not schedule-scoped:
        _panel_run reads it for EVERY run including the owner's own local button
        clicks, so this endpoint also sets the concurrency of local maintenance jobs."""
        with _sched_lock:
            s = _load_sched()
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                if "action" in body and body.get("action"):
                    s["action"] = str(body.get("action"))
                if "enabled" in body:
                    s["enabled"] = bool(body.get("enabled"))
                if "interval_hours" in body:
                    try:
                        s["interval_hours"] = max(1, min(int(body.get("interval_hours") or 6), 168))
                    except (TypeError, ValueError):
                        s["interval_hours"] = 6
                if "workers" in body:
                    try:
                        # no `or 4` -- workers=0 must clamp to 1, not fall through to 4
                        s["workers"] = max(1, min(int(body.get("workers")), 16))
                    except (TypeError, ValueError):
                        s["workers"] = 4
                if "jobs" in body:
                    # THE LIVING LIBRARY'S LIST. A PATCH, exactly like every other field
                    # here: the client sends only the rows it is changing, and only the
                    # two things it may change -- whether a job runs by itself, and how
                    # often. `action` and `last_run` are never taken from the body: an
                    # unknown action is dropped by living_merge (the shipped list is the
                    # only list), and a client that could write last_run could make a
                    # sixty-day staleness job fire on demand.
                    rows = {r["action"]: r for r in s["jobs"]}
                    for patch in (body.get("jobs") or []):
                        if not isinstance(patch, dict):
                            continue
                        row = rows.get(str(patch.get("action") or ""))
                        if not row:
                            continue
                        if "enabled" in patch:
                            row["enabled"] = bool(patch.get("enabled"))
                        if "interval_s" in patch:
                            # THE FLOOR IS ENFORCED HERE, not in the browser. The Panel
                            # renders no cadence selector for a staleness job -- but a
                            # POST is not the Panel, and living_clamp_interval is the one
                            # place that knows sixty days is a floor rather than a
                            # default. A patch asking for a full re-walk every minute
                            # comes back clamped, saved clamped, and answered clamped.
                            row["interval_s"] = _living.living_clamp_interval(
                                row["action"], patch["interval_s"],
                                default=row.get("interval_s"))
                            # the owner's own pick: a later default change never moves it
                            # (living_merge, LIVING_RETIRED_DEFAULTS)
                            row["chosen"] = True
                if not _standing_runnable(s.get("action")):
                    # ADVANCED IS REFUSED HERE TOO, not only at the tick. The tick has
                    # always skipped an advanced action -- a full re-walk on a six-hour
                    # timer is a foot-gun, and test-pull needs an N this path cannot
                    # supply -- but the save route did not, so the pair could be SAVED
                    # and then never run by anyone: _living_tick stood aside for a
                    # standing order that refuses the job, and the Panel said "the
                    # standing order below runs this one" about a job neither path would
                    # ever start. Both halves say the same thing now.
                    return jsonify({"error": "only safe jobs can be scheduled — a full "
                                             "re-walk, an inventory count and a test pull "
                                             "stay in Advanced, by hand"}), 400
                _save_sched(s)
            # `catalog` is what the Panel draws the "runs itself" rows from: the shipped
            # label, note and cadence beside each saved row, so the client never has to
            # keep its own copy of the job list (and never disagrees with the server's).
            #
            # `deferred` is the honest half of a collision the tick has always handled
            # silently: the legacy standing order still owns whatever action it names, so
            # _living_tick skips that action's row -- correctly, since two paths starting
            # one job would just take turns losing the single Panel slot. But the row went
            # on displaying its own cadence and its own "next in 3h", which is a schedule
            # it is NOT running. The skip stays; the row now says why.
            #
            # Read through _standing_action, the same function the tick defers by, so the
            # row and the tick can never disagree: a standing order naming a job that path
            # refuses to start owns nothing, and the row is not marked deferred to it.
            standing = _standing_action(s)
            return jsonify(dict(s, catalog=[
                {"action": j["action"], "label": j["label"], "note": j["note"],
                 "default_interval_s": j["interval_s"],
                 "stale": j["action"] in _LIVING_STALE_ACTIONS,
                 "needs_torch": j.get("needs") == "torch",
                 "deferred": j["action"] == standing,
                 "available": _living_runnable(j["action"])
                              and (j.get("needs") != "torch" or _living._torch_present())}
                for j in _living.LIVING_ALL]))

    @app.route("/api/panel/sweep", methods=["POST"])
    @tier(LOCALHOST)
    def api_panel_sweep():
        """RUN NOW for the published-artwork sweep -- the one living job that is not a
        PANEL_ACTIONS key, because it runs in-process (the CLI's --sync-artworks is the
        full re-walk and has no short-circuiting equivalent to spawn).

        LOCALHOST for the same reason /api/panel/schedule's writes are: this starts real,
        paced PixAI traffic on the owner's own credentials, and a logged-in LAN session
        unlocks browsing, not background work on his account. Forced -- the owner pressing
        Run now is asking past the fifteen-minute guard, exactly as the publish kick does.

        Answers immediately; the sweep runs off-thread and announces itself through the
        Activity ledger if it changed anything. It never touches the page the owner is
        looking at.

        `deferred` names the catalog-writing Panel job that held the sweep off, when one
        did (_artworks_job_busy) -- so an ok:false is never a silent nothing.

        NOT `scheduled`, and it is the only one of the four triggers that is not: this is a
        button the owner pressed, so it still toasts when it finishes, exactly like every
        other job he starts himself (owner's walk, 2026-09-07)."""
        deferred = _artworks_job_busy()
        return jsonify({"ok": bool(_artworks_kick(force=True)),
                        "deferred": deferred,
                        "action": _living.LIVING_SWEEP_ACTION})

    # -- provided to ctx (split_move) --
    # -- end --

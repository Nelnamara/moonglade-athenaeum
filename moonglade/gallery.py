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
from moonglade import dupe_review as _dupe_review
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
from moonglade import thumbs as _thumbs
from moonglade import train_guard as _train_guard
from moonglade import training as _training
from moonglade import trash as _trash
from moonglade import updater as _updater
from moonglade import secure_files as _secure_files
from moonglade import watch_plans as _watch_plans
from moonglade import web_policy as _web_policy
from moonglade import web_sessions as _web_sessions
from moonglade import web_tiers as _web_tiers
from moonglade import web_accounts as _web_accounts

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


def _carries_bearer():
    """Any Authorization header makes a request bearer-only (review R6): it never reads, and is
    never given, a session cookie."""
    try:
        return request.headers.get("Authorization") is not None
    except RuntimeError:                           # no request
        return False


class _RememberingSessions(_PerRequestSecureSessions):
    """The per-request-Secure sessions above (subclassed, so that flag survives: review R2/R11),
    taught about remembered devices (moonglade.web_devices).

    * A cookie's signature is accepted up to REMEMBER_DEVICE_LIFETIME_S old; a session WITHOUT a
      remembered device (`dev`) older than permanent_session_lifetime is still read as empty,
      exactly as Flask's own max_age did. (Flask checks the signature against
      permanent_session_lifetime, so a longer Expires alone would still drop an idle remembered
      cookie at 30 days.)
    * A remembered session's cookie expires when its record does (`dev_exp`); every other one
      keeps permanent_session_lifetime.
    * A request carrying an Authorization header reads no cookie and is sent none."""

    def open_session(self, app, request):
        from itsdangerous import BadSignature
        if request.headers.get("Authorization") is not None:
            return self.session_class()
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(self.get_cookie_name(app))
        if not val:
            return self.session_class()
        try:
            data, signed = s.loads(val, max_age=_web_policy.REMEMBER_DEVICE_LIFETIME_S,
                                   return_timestamp=True)
        except BadSignature:
            return self.session_class()
        signed = signed.timestamp() if hasattr(signed, "timestamp") else float(signed)
        if not (isinstance(data, dict) and data.get("dev")) and (
                time.time() - signed > app.permanent_session_lifetime.total_seconds()):
            return self.session_class()
        return self.session_class(data)

    def get_expiration_time(self, app, session):
        import datetime as _dt
        exp = session.get("dev_exp")
        if session.permanent and session.get("dev") and isinstance(exp, (int, float)) \
                and not isinstance(exp, bool):
            return _dt.datetime.fromtimestamp(exp, _dt.timezone.utc)
        return super().get_expiration_time(app, session)

    def should_set_cookie(self, app, session):
        if _carries_bearer():
            return False
        return super().should_set_cookie(app, session)

    def save_session(self, app, session, response):
        if _carries_bearer():
            return None                            # not even a delete-cookie header
        return super().save_session(app, session, response)


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
    # that never actually ran would look identical to one with nothing to do. There is no
    # module-level logger either; moonglade.logs.setup_logging() configures the root logger.
    import logging as _logging
    try:
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
    app.secret_key = _web_accounts.get_or_create_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS can never read the session cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site POST/nav CSRF vectors
    # Secure PER REQUEST (2026-11-19): the cookie is marked Secure whenever the request that
    # sets it came over HTTPS -- every other device on the home network since moonglade.tls --
    # so a browser never sends it back over plain http://. This PC's own loopback may stay
    # plain HTTP, and a Secure cookie set there would be dropped by the browser and break
    # sign-in, so the flag follows the request rather than one app-wide setting.
    # _RememberingSessions keeps that flag and adds the remembered device's longer cookie
    # (moonglade.web_devices) and the bearer path's no-cookie rule.
    app.session_interface = _RememberingSessions()
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

    # Every route family out of this function is one module with one register(app, ctx).
    # They share this one ctx, in this order: a family reads what the families before it
    # provided and provides what the families after it read, so a name is one object on
    # both sides. register() adds its names to ctx itself.
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import routes_gate as _routes_gate
    from moonglade import web_threads as _web_threads
    from moonglade import routes_panel as _routes_panel
    from moonglade import routes_delete as _routes_delete
    from moonglade import routes_recipes as _routes_recipes
    from moonglade import routes_library as _routes_library
    from moonglade import routes_account as _routes_account
    from moonglade import routes_community as _routes_community
    from moonglade import routes_train as _routes_train
    from moonglade import routes_ach as _routes_ach
    from moonglade import routes_mirror as _routes_mirror
    from moonglade import routes_branding as _routes_branding
    from moonglade import web_loom_store as _web_loom_store
    from moonglade import routes_generate as _routes_generate
    from moonglade import routes_import as _routes_import
    from moonglade import routes_loom as _routes_loom
    ctx = _SimpleNamespace(build_stamp=build_stamp, db_path=db_path, out_dir=out_dir,
                           thumb_dir=thumb_dir)
    for _family in (
            _routes_gate, _web_threads, _routes_panel, _routes_delete, _routes_recipes,
            _routes_library, _routes_account, _routes_community, _routes_train, _routes_ach,
            _routes_mirror, _routes_branding, _web_loom_store, _routes_generate, _routes_import,
            _routes_loom):
        _family.register(app, ctx)

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
        _thumbs.build_thumbnails(rows, out_dir, thumb_dir, force=args.rebuild_thumbs, recheck=False)

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
        _thumbs.start_see_through_recheck(rows, out_dir, thumb_dir)
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

#!/usr/bin/env python3
"""
moonglade_backup.py  (v4 - media resolution)
================================================
Bulk-download YOUR OWN PixAI.art generated images. Replays PixAI's persisted
GraphQL query (listUserTaskSummaries) to page backward through your entire
generation history, turns each task's mediaId / batchMediaIds into full-resolution
image URLs, downloads them (with resume), paces itself, and writes a catalog with
the prompt preview next to each image.

You own the copyright to images you generate on PixAI. Keep the rate modest.

--------------------------------------------------------------------------------
HOW IMAGES ARE FETCHED
--------------------------------------------------------------------------------
Task summaries don't contain image URLs -- they contain media IDs. PixAI serves
media at:   https://api.pixai.art/v1/media/<mediaId>
Fetching that object returns a `urls` list of variants (PUBLIC/ORIGINAL/etc);
resolve_media() picks the best one via URL_VARIANT_PREFERENCE. Run --probe to
see the resolution result before committing.

--------------------------------------------------------------------------------
SECURITY MODEL (unchanged)
--------------------------------------------------------------------------------
* No password handling. Bearer token from PIXAI_TOKEN env var or token.txt only.
* HTTPS verification always ON. On 401, refresh the token and re-run (resumes).

--------------------------------------------------------------------------------
QUICK START
--------------------------------------------------------------------------------
  pip install requests truststore
  set PIXAI_TOKEN ...   (your OS's way)
  python moonglade_backup.py --probe     # resolve full-res media URL, sanity-check
  python moonglade_backup.py             # download everything (backward)
  python moonglade_backup.py --max 40    # small test first
"""

__version__ = "2.5.0"

import argparse
import csv
import datetime
import getpass
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
from collections import defaultdict, Counter
from pathlib import Path

from moonglade_gallery import (CATALOG_FIELDS, _IMAGE_EXTS, init_db, load_catalog,
                            save_catalog, migrate_csv_to_db, export_csv, _db_is_empty,
                            media_id_of, find_files_for_media_id, build_thumbnails,
                            _NO_WINDOW, DELETED_DIRNAME)


def _ensure_db(out):
    """Return db_path after auto-migrating catalog.csv if the db is missing/empty.

    Raises PixAIError if neither db nor csv exists.
    """
    out = Path(out)
    db_path  = out / "catalog.db"
    csv_path = out / "catalog.csv"
    if _db_is_empty(db_path):
        if csv_path.exists():
            print("Migrating catalog.csv → catalog.db ...")
            n = migrate_csv_to_db(csv_path, db_path)
            print("Migrated {:,} rows.".format(n))
        else:
            raise PixAIError(
                "No catalog found in {}. Run a download (or --collect-only) first.".format(out))
    return db_path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

_TRUSTSTORE_ACTIVE = False
try:
    import truststore
    truststore.inject_into_ssl()
    _TRUSTSTORE_ACTIVE = True
except Exception:
    pass


class PixAIError(Exception):
    """Raised instead of sys.exit() so the GUI and tests can catch errors cleanly."""


class EmptyOutputsError(PixAIError):
    """PixAI reported the task TERMINAL -- either 'done' with empty outputs, or a real
    failure (failed/error/cancelled/rejected) -- so it produced nothing and never will.

    This exists to be distinguishable from an ordinary PixAIError at a catch
    site, NOT to carry different information. The web poller's collect step has
    to tell two failures apart that look identical through a bare `except`:

      * a transient 5xx/429/timeout, where the task is probably fine and writing
        a terminal 'failed' would brick the Jobs card with a sticky false
        failure for a generation that actually succeeded; and
      * this, where the task is genuinely over and empty, and NOT writing a
        terminal event leaves the job spinning on 'running' forever.

    Before this split the poller treated both as the first case, so a real
    empty-output task (e.g. one submitted with an unusable input media id) hung
    in the Jobs card indefinitely. Subclasses PixAIError so every existing
    `except PixAIError` keeps catching it unchanged."""


class WatchStaleError(PixAIError):
    """Raised by `_watch_events_async` when the WebSocket has gone silent for too
    long -- see `_WS_STALE_TIMEOUT`. Exists to be distinguishable from an ordinary
    connection failure at `_watch_loop`'s catch site, the same reasoning as
    EmptyOutputsError above: a ConnectionClosed/OSError there means the socket
    itself reported trouble, but this means the socket looked fine (no error, no
    close frame) while nothing arrived on it for longer than PixAI's normal event
    cadence -- a distinct failure mode worth counting separately (see
    `_watch_status["stale_reconnects"]`) so it stays visible instead of blending
    into ordinary reconnect noise. Subclasses PixAIError so every existing
    `except PixAIError` / `except Exception` keeps catching it unchanged."""


# ---------------------------------------------------------------------------
# Verbose diagnostics
# ---------------------------------------------------------------------------
# A single module-level switch shared by the CLI (--verbose) and the GUI
# (Verbose logging checkbox). vlog() is a no-op until set_verbose(True) is
# called, so normal runs and the test suite are completely unaffected.
_VERBOSE = False
_VERBOSE_T0 = None


def set_verbose(on):
    """Enable/disable timestamped diagnostic logging. Resets the elapsed clock
    each time it is enabled so timings read from the start of the operation."""
    global _VERBOSE, _VERBOSE_T0
    _VERBOSE = bool(on)
    if _VERBOSE:
        _VERBOSE_T0 = time.monotonic()


def vlog(msg):
    """Print a diagnostic line prefixed with seconds-since-enabled, but only in
    verbose mode. Writes to stdout so the GUI log pane captures it too. Also
    always forwarded to the persistent file logger (moonglade_logging), regardless
    of verbose state, so a run's diagnostics are on record even if -v wasn't
    passed -- this is the one call site touched to give every existing vlog()
    caller file-logging for free, rather than threading a logger through ~100
    of them individually."""
    import moonglade_logging
    moonglade_logging.get_logger().debug(msg)
    if not _VERBOSE:
        return
    t0 = _VERBOSE_T0 if _VERBOSE_T0 is not None else time.monotonic()
    print("  [v +{:6.1f}s] {}".format(time.monotonic() - t0, msg), flush=True)


API_URL = "https://api.pixai.art/graphql"
# PixAI's newer typed-RPC (oRPC) REST surface, served at /v2 on the same host and
# authenticated with the same Bearer token. The free-card ("kaisuuken") list + match
# live here, NOT on GraphQL -- verified 2026-07-03. Derived from API_URL so a custom
# host in config carries over.
REST_API_BASE = API_URL.rsplit("/graphql", 1)[0] + "/v2"

# ===========================================================================
# CAPTURED FROM YOUR BROWSER -- loaded from config.json (see config.example.json)
# Update config.json when the site changes (see RECAPTURE at the bottom).
# ===========================================================================
OPERATION_NAME = "listUserTaskSummaries"
CLIENT_LIBRARY = {"name": "@apollo/client", "version": "4.1.4"}


def _config_path():
    """Resolve config.json's path: prefer a copy next to the script file, then the
    current working directory (same order _load_config() has always read in). If
    neither exists yet (first run / a fresh write), default to creating it next to
    the script -- the natural "this install's config" location."""
    for cfg_path in (Path(__file__).resolve().parent / "config.json", Path("config.json")):
        if cfg_path.exists():
            return cfg_path
    return Path(__file__).resolve().parent / "config.json"


def _load_config():
    """Read config.json. Returns {} quietly if absent so --help and offline modes
    (--organize, --catalog-stats) work without it; main() validates before API calls.
    Looks next to the script file first, then the current working directory."""
    cfg_path = _config_path()
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print("Warning: could not read config.json: {}".format(e))
        return {}


def _save_config(cfg):
    """Write config.json back to disk (indent=2, matching the file's existing style).
    ATOMIC: serialize fully, write a same-directory temp file, then os.replace() --
    an atomic rename on NTFS and POSIX alike. A reader therefore always sees either
    the complete old file or the complete new one, never a torn hybrid.

    This is load-bearing, not polish, and it is why the old "not atomic-tmp-swapped,
    config.json is small and single-owner" reasoning no longer holds. _load_config()
    catches ValueError on a corrupt file and returns {} -- which reads as an EMPTY
    AUTH_USERS, which drops /login into local-only bootstrap_mode (whoever is at the
    machine mints a fresh admin) and clears every live session. Revocation state
    (AUTH_EPOCH_SEQ) now lives in this file too, and EVERY /logout writes it, so the
    old truncate-then-write was a steadily widening window on an auth wipe."""
    path = _config_path()
    data = json.dumps(cfg, indent=2)          # serialize BEFORE touching disk
    tmp = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # Windows only: an AV scanner or indexer can transiently hold the
                # target open. Retry briefly, then fail LOUD -- a silently dropped
                # write here IS the lost-revocation defect this change exists to fix.
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Web gallery login accounts -- session-based auth for moonglade_gallery.py's Flask
# app (gates EVERY request, local or remote -- there is no localhost bypass; see
# _is_authorized_request() there).
# Stored in config.json (the existing convention for secrets -- it already holds
# PIXAI_API_KEY): AUTH_SECRET_KEY signs the Flask session cookie, AUTH_USERS is a
# list of {"username", "password_hash"} (werkzeug.security -- scrypt as of modern
# werkzeug, timing-safe compare built in; no new pip install, werkzeug already
# ships with Flask). Account lifecycle used to be CLI-only; as of the web-based
# bootstrap + Panel Users tab (2026-07-19) it's also reachable from the browser
# (see moonglade_gallery.py's /login bootstrap POST and /api/users/add|remove) --
# --add-web-user / --remove-web-user / --list-web-users remain a valid recovery
# path. If AUTH_USERS is empty, logging in from the LAN is simply impossible --
# there is no default/backdoor account, ever.
#
# _accounts_lock serializes every read-modify-write of AUTH_USERS (and the
# atomic check-and-mutate helpers below) against every OTHER thread doing the
# same, within this one process. moonglade_gallery.py runs `app.run(...,
# threaded=True)`, so two browser tabs/devices hitting /login's bootstrap POST
# (or the Panel's Add/Remove-user endpoints) concurrently used to run
# add_or_update_web_user()/remove_web_user()'s _load_config -> mutate ->
# _save_config sequence unlocked and interleaved -- a real, reproduced lost-
# update: two concurrent bootstrap creates for DIFFERENT usernames could both
# return a 302 "success" to their own browser while only the second write
# actually landed on disk, silently discarding the first account (adversarial
# review, 2026-07-19). Does NOT protect against a separate CLI invocation
# editing config.json while the server is also running -- that's a distinct,
# pre-existing, cross-PROCESS assumption (_save_config's docstring), not what
# this lock is for.
# ---------------------------------------------------------------------------
_accounts_lock = threading.Lock()

def get_or_create_secret_key():
    """Return config.json's AUTH_SECRET_KEY, generating + persisting a fresh
    secrets.token_hex(32) the first time this ever runs. Persisting it is what lets
    Flask sessions (and therefore logins) survive a server restart -- without this,
    every restart would silently log everyone out, which is a usability bug, not
    just a security nitpick."""
    cfg = _load_config()
    key = (cfg.get("AUTH_SECRET_KEY") or "").strip()
    if key:
        return key
    key = secrets.token_hex(32)
    cfg["AUTH_SECRET_KEY"] = key
    try:
        _save_config(cfg)
    except OSError as e:
        print("Warning: could not persist AUTH_SECRET_KEY to config.json: {}. "
              "Sessions will not survive a restart this run.".format(e))
    return key


def _find_web_user(cfg, username):
    for u in (cfg.get("AUTH_USERS") or []):
        if isinstance(u, dict) and u.get("username") == username:
            return u
    return None


_EPOCH_SEQ_KEY = "AUTH_EPOCH_SEQ"
# Applied ONCE, when config.json has never carried AUTH_EPOCH_SEQ. See below -- this
# constant is the fix, not a tuning knob.
_EPOCH_LEGACY_MARGIN = 1_000_000


def _next_sess_epoch(cfg):
    """Return the next install-wide session-epoch ticket, stamping it into `cfg`.

    MUST be called with `_accounts_lock` ALREADY HELD, and with `cfg` a config dict
    the caller is about to _save_config(). It deliberately takes NO lock and does NO
    I/O of its own -- precisely so its callers, every one of which already holds the
    NON-REENTRANT _accounts_lock, cannot self-deadlock. A new caller must already
    hold the lock.

    WHY THE COUNTER IS INSTALL-WIDE AND NOT PER-ACCOUNT: a counter stored in the
    account record dies with the account. Removing and re-creating a username reset
    sess_epoch to 0 -- the exact value stale cookies already carry -- so
    _is_authorized_request() compared 0 == 0 and ALLOWED. Remove-and-re-add is
    precisely the recovery an owner performs after a suspected cookie theft, which
    made the recovery step itself un-revoke every cookie ever issued to that name.

    WHY THE MARGIN (do NOT "simplify" this away -- removing it silently re-opens the
    defect): on a config written by the previous code there is no AUTH_EPOCH_SEQ, and
    the max-scan below can only see accounts that STILL EXIST. If the owner removed
    the compromised account and THEN upgraded -- the likely ordering, since the
    upgrade is the response to the incident -- that account's epoch history is gone,
    the scan returns only the survivors' small values, and the first tickets walk
    1, 2, 3... straight back through the stale cookies' range. Jumping clear of the
    whole legacy range on first mint closes that without needing to see the deleted
    account. Live legacy cookies carry small ints, so the jump logs nobody out.

    The max-scan is kept too, and is self-healing: if config.json is hand-edited so a
    user's sess_epoch exceeds the counter, the next ticket still clears it."""
    seeded = _EPOCH_SEQ_KEY in cfg
    try:
        highest = int(cfg.get(_EPOCH_SEQ_KEY, 0) or 0)
    except (TypeError, ValueError):
        highest = 0
        seeded = False
    if not seeded:
        highest = max(highest, _EPOCH_LEGACY_MARGIN)
    for u in (cfg.get("AUTH_USERS") or []):
        if isinstance(u, dict):
            try:
                highest = max(highest, int(u.get("sess_epoch", 0)))
            except (TypeError, ValueError):
                pass          # hand-edited garbage -> ignore, never crash a login
    nxt = highest + 1
    cfg[_EPOCH_SEQ_KEY] = nxt
    return nxt


def list_web_users():
    """Return [{"username": ...}, ...] from config.json's AUTH_USERS -- USERNAMES
    ONLY, never password hashes. Used by --list-web-users."""
    with _accounts_lock:
        cfg = _load_config()
        return [{"username": u["username"]} for u in (cfg.get("AUTH_USERS") or [])
                if isinstance(u, dict) and u.get("username")]


# --- Web-login password policy -------------------------------------------
# ONE source of truth, called by every path that can create an account: the
# first-run bootstrap form on /login, the Control Panel's Users tab, and the
# --add-web-user CLI recovery flag. It lives here, next to the account model,
# rather than in the web layer specifically so those three can't drift apart --
# the previous 4-character rule was duplicated across two call sites and would
# have had to be corrected in both.
#
# Deliberately shaped after NIST SP 800-63B: LENGTH is the control that matters,
# and composition rules ("must contain a symbol") are NOT enforced, because they
# measurably push people toward predictable mutations like "P@ssw0rd1" instead
# of toward real entropy. What we DO reject is the small set of passwords that
# stay trivially guessable at any length: one repeated character, a straight run
# off the keyboard, and the perennial favourites.
MIN_WEB_PASSWORD_LEN = 8

# Usernames are bounded so a pathological one can't wreck the account-list layout
# (a 300-char name pushed a live Remove button ~980px outside its card) or bloat
# config.json. 64 is generous for a display name yet safely short; the account row
# also truncates in CSS as a second line of defence for any legacy over-long name.
MAX_WEB_USERNAME_LEN = 64

_COMMON_PASSWORDS = frozenset({
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyui", "qwerty123", "letmein1", "welcome1", "iloveyou", "admin123",
    "administrator", "changeme", "trustno1", "sunshine", "princess", "football",
    "baseball", "superman", "dragon123", "monkey123", "abc12345", "starwars",
})


def _is_single_run(s):
    """True if `s` is one unbroken ascending or descending character run
    ("12345678", "abcdefgh", "87654321") -- a keyboard-walk shape long enough to
    sail past a length check while carrying almost no entropy."""
    if len(s) < 3:
        return False
    deltas = {ord(b) - ord(a) for a, b in zip(s, s[1:])}
    return deltas == {1} or deltas == {-1}


def password_problem(password):
    """Return a human-readable reason `password` is unacceptable for a web-login
    account, or None if it passes. Every caller renders the returned string to
    the user verbatim, so each one names what to do next, not just what's wrong."""
    pw = password or ""
    if len(pw) < MIN_WEB_PASSWORD_LEN:
        return "Password must be at least {} characters.".format(MIN_WEB_PASSWORD_LEN)
    if pw.lower() in _COMMON_PASSWORDS:
        return "That password is too common to be safe. Pick something less guessable."
    if len(set(pw)) == 1:
        return "Password can't be one character repeated. Pick something less guessable."
    if _is_single_run(pw.lower()):
        return ("Password can't be a single run of sequential characters. "
                "Pick something less guessable.")
    return None


def username_problem(username):
    """Return a human-readable reason `username` is unacceptable for a web-login
    account, or None if it passes. Mirrors password_problem(): one policy, rendered
    verbatim at every entry point (the /login bootstrap form, the Panel's
    /api/users/add, and --add-web-user), so the rule can't drift between them.
    Callers strip first; this assumes an already-stripped value but tolerates one."""
    u = (username or "").strip()
    if not u:
        return "Username is required."
    if len(u) > MAX_WEB_USERNAME_LEN:
        return "Username must be at most {} characters.".format(MAX_WEB_USERNAME_LEN)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in u):
        return "Username can't contain control characters."
    return None


def add_or_update_web_user(username, password):
    """Hash `password` (werkzeug, scrypt) and add/update `username` in config.json's
    AUTH_USERS. Only the hash ever touches disk -- the plaintext password passed in
    here is never written anywhere. Returns True if this replaced an existing
    account's password, False if the account is new.

    Also stamps/bumps `sess_epoch` -- see get_web_user_session_epoch()'s docstring
    for why: a password change must invalidate any session cookie issued under the
    old password immediately, not just future ones.

    The whole read-modify-write runs under `_accounts_lock` -- see that lock's
    docstring for the concurrent-bootstrap lost-update it closes."""
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    # Hard backstop for EVERY writer, including the --add-web-user CLI path that
    # doesn't go through username_problem() -- length is enforced at the one place
    # the account actually gets written, so nothing can persist an over-long name.
    if len(username) > MAX_WEB_USERNAME_LEN:
        raise ValueError("username must be at most {} characters".format(MAX_WEB_USERNAME_LEN))
    if not password:
        raise ValueError("password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        existing = _find_web_user(cfg, username)
        replaced = existing is not None
        # Ticket from the install-wide counter, never a per-account increment: see
        # _next_sess_epoch()'s docstring for why a record-local counter was the bug.
        next_epoch = _next_sess_epoch(cfg)
        new_users = [u for u in users if not (isinstance(u, dict) and u.get("username") == username)]
        new_users.append({"username": username, "password_hash": generate_password_hash(password),
                           "sess_epoch": next_epoch})
        cfg["AUTH_USERS"] = new_users
        _save_config(cfg)
        return replaced


def set_web_user_password_guarded(username, new_password, current_password=None):
    """Change an existing account's password. Returns "ok", "not_found" or "bad_current".

    ONE `_accounts_lock` acquisition covers the existence check, the current-password
    verification and the write. That is not stylistic: `remove_web_user_guarded`'s docstring
    records a TOCTOU race reproduced live against a real route when a read and a write were
    split across two acquisitions, and "verify the old password, then write the new one" is
    the same shape. Between a separate verify and write, a concurrent change could land and
    this call would happily overwrite it having validated against a password that no longer
    existed.

    `current_password=None` means DO NOT CHECK -- reserved for the caller that has already
    established the request came from the server machine. Passing a string means the check is
    mandatory and a mismatch returns "bad_current" without writing. There is deliberately no
    third mode: a caller either proves the old password or proves it is local, and the route
    (`/api/users/password`) is the only place that distinction is made.

    Unlike `add_or_update_web_user`, this REFUSES an unknown username instead of creating the
    account. A password reset for someone who does not exist is a mistake to report, not an
    invitation to mint them -- that update-or-add behaviour stays reserved for the CLI's
    deliberate recovery path.

    Bumps `sess_epoch` through the same install-wide counter every other writer uses, so a
    changed password invalidates session cookies issued under the old one immediately. Callers
    that want the CURRENT session to survive must re-issue its cookie afterwards; see
    /api/users/password, which does exactly that so a user changing their own password is not
    logged out of the browser they are standing in front of."""
    from werkzeug.security import generate_password_hash, check_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if not new_password:
        raise ValueError("new password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        existing = _find_web_user(cfg, username)
        if existing is None:
            return "not_found"
        if current_password is not None:
            if not check_password_hash(existing.get("password_hash", ""), current_password or ""):
                return "bad_current"
        users = cfg.get("AUTH_USERS") or []
        next_epoch = _next_sess_epoch(cfg)
        new_users = [u for u in users
                     if not (isinstance(u, dict) and u.get("username") == username)]
        new_users.append({"username": username,
                          "password_hash": generate_password_hash(new_password),
                          "sess_epoch": next_epoch})
        cfg["AUTH_USERS"] = new_users
        _save_config(cfg)
        return "ok"


def add_web_user_if_new(username, password):
    """Atomic check-and-add: like add_or_update_web_user(), but refuses outright
    (returns False, writes nothing) if `username` already exists, instead of
    resetting a stranger's password -- the whole "does it exist" check and the
    write happen under ONE `_accounts_lock` acquisition, so two concurrent
    requests trying to claim the same brand-new username can never both
    succeed. Used by the Panel's /api/users/add (moonglade_gallery.py); the plain
    add_or_update_web_user()'s update-or-add semantics stay reserved for the
    CLI's --add-web-user recovery case. Returns True if added, False if the
    username was already taken (nothing written)."""
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if len(username) > MAX_WEB_USERNAME_LEN:          # same backstop as add_or_update_web_user
        raise ValueError("username must be at most {} characters".format(MAX_WEB_USERNAME_LEN))
    if not password:
        raise ValueError("password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        if _find_web_user(cfg, username) is not None:
            return False
        users = cfg.get("AUTH_USERS") or []
        users.append({"username": username, "password_hash": generate_password_hash(password),
                       # The Panel's /api/users/add path -- the one an owner actually
                       # uses from a browser. Hardcoding 0 here left the resurrection
                       # defect fully live through the UI even with the CLI path fixed.
                       "sess_epoch": _next_sess_epoch(cfg)})
        cfg["AUTH_USERS"] = users
        _save_config(cfg)
        return True


def remove_web_user(username):
    """Remove `username` from config.json's AUTH_USERS. Returns True if an account
    was actually removed, False if no such username existed. Runs under
    `_accounts_lock` -- see that lock's docstring."""
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        new_users = [u for u in users if not (isinstance(u, dict) and u.get("username") == username)]
        removed = len(new_users) != len(users)
        if removed:
            # Advance the install-wide counter while the departing account is STILL
            # in cfg["AUTH_USERS"], so its epoch is folded into the high-water mark
            # before the record -- and therefore the evidence -- is destroyed.
            # Calling this AFTER the reassignment below silently re-opens the
            # resurrection defect, because _next_sess_epoch scans that same list.
            _next_sess_epoch(cfg)
            cfg["AUTH_USERS"] = new_users
            _save_config(cfg)
        return removed


def remove_web_user_guarded(username, min_remaining=1):
    """Atomic check-and-remove: refuses to remove `username` if doing so would
    leave fewer than `min_remaining` accounts, checked under the SAME
    `_accounts_lock` acquisition as the mutation itself -- closes a TOCTOU race
    where the Panel's /api/users/remove used to read list_web_users() (a
    "how many accounts are there" snapshot), THEN separately call
    remove_web_user() to mutate, with nothing stopping two concurrent removals
    of two DIFFERENT accounts from each observing "more than one left" via
    their own stale snapshot before either write landed, and both proceeding --
    reproduced live against the real Flask route (adversarial review,
    2026-07-19): exactly 2 accounts, two concurrent removes of two different
    usernames, both return 200 {"ok": true}, AUTH_USERS ends up empty --
    the self-lockout this guard exists to prevent, achieved anyway.

    Returns one of "removed", "not_found", "last_account"."""
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        if _find_web_user(cfg, username) is None:
            return "not_found"
        if len(users) <= min_remaining:
            return "last_account"
        _next_sess_epoch(cfg)     # BEFORE the filter -- see remove_web_user's comment
        cfg["AUTH_USERS"] = [u for u in users
                              if not (isinstance(u, dict) and u.get("username") == username)]
        _save_config(cfg)
        return "removed"


def get_web_user_session_epoch(username):
    """Current `sess_epoch` for `username`, or None if the account doesn't exist
    (e.g. removed via --remove-web-user). A session's cookie embeds the epoch that
    was current at login time; moonglade_gallery.py's _is_authorized_request()
    re-checks it against this on every request, so:
      - removing the account invalidates any outstanding session for it immediately
        (this returns None -> no epoch can ever match again), and
      - /logout can revoke every outstanding session for that identity (not just
        the browser that clicked it) by calling bump_web_user_session_epoch()
        before clearing its own session.
    Without this, a stolen session cookie (plain-HTTP LAN, packet capture) would
    keep working after the legitimate user signs out or the account is removed,
    since the stock Flask session is a stateless, client-side signed cookie with
    nothing server-side to revoke -- see CHANGELOG.md for the fuller writeup."""
    cfg = _load_config()
    user = _find_web_user(cfg, (username or "").strip())
    if user is None:
        return None
    return int(user.get("sess_epoch", 0))


def bump_web_user_session_epoch(username):
    """Issue `username` a fresh session-epoch ticket, invalidating every outstanding
    session cookie for that identity in one move (used by /logout). No-op (returns
    False) if the account no longer exists.

    Runs the whole read-modify-write under `_accounts_lock`, like every OTHER
    AUTH_USERS writer. It previously did _load_config -> mutate -> _save_config
    entirely UNLOCKED -- the one writer that didn't -- which interleaved with a
    concurrent /api/users/add is a lost update in BOTH directions: either the newly
    created account is erased from disk, or the epoch bump is lost. A lost bump means
    revocation silently no-ops and the stolen cookie this function exists to kill
    stays live. Found by an independent cloud review, not by any test.

    _find_web_user returns the dict living inside cfg["AUTH_USERS"] (not a copy), so
    mutating it mutates cfg -- the previous implementation relied on this too."""
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        user = _find_web_user(cfg, username)
        if user is None:
            return False
        user["sess_epoch"] = _next_sess_epoch(cfg)
        _save_config(cfg)
        return True


_dummy_hash_cache = {}


def _dummy_password_hash():
    """A real (valid-format) werkzeug hash of a password nobody will ever type,
    computed lazily and cached for this process. verify_web_user() runs a check
    against this for an UNKNOWN username so an unknown-username login takes about
    the same time as a known-username-wrong-password one -- no username enumeration
    via response timing. Lazy + cached so a plain CLI run that never touches web
    auth never pays scrypt's cost, and a running server pays it at most once."""
    if "h" not in _dummy_hash_cache:
        from werkzeug.security import generate_password_hash
        _dummy_hash_cache["h"] = generate_password_hash("no-such-account-#dummy-timing-guard")
    return _dummy_hash_cache["h"]


def verify_web_user(username, password):
    """Check username/password against config.json's AUTH_USERS. True only on an
    exact match against a KNOWN username, via werkzeug's timing-safe
    check_password_hash. An unknown username still runs a (dummy) hash check
    instead of returning immediately, so response timing doesn't leak which
    usernames exist."""
    from werkzeug.security import check_password_hash
    cfg = _load_config()
    user = _find_web_user(cfg, (username or "").strip())
    if user is None:
        check_password_hash(_dummy_password_hash(), password or "")
        return False
    return check_password_hash(user.get("password_hash", ""), password or "")


_cfg = _load_config()
# A trust signal for anyone nervous about handing a third-party tool spend/delete access
# to their PixAI account: with READ_ONLY:true in config.json, every account-mutating
# network call refuses itself -- CLI and web alike, and REGARDLESS of --confirm/--apply/
# --yes, since those flags are the very thing a cautious first run wants to be safe to
# pass without reading the source first. This does NOT cover purely local operations
# (--organize, --dedup) -- those already have their own dry-run-by-default + --apply
# gates and never touch the network; conflating "protect my files" with "protect my
# account" would be a different, weaker promise than the one this flag makes.
READ_ONLY = bool(_cfg.get("READ_ONLY", False))


def _check_read_only(action):
    """Called at the top of every branch that actually fires an account-mutating
    network call. Raising here, unconditionally, is what makes READ_ONLY override
    --confirm/--apply/--yes rather than just changing their default.

    Eight call sites, not four: submit_generation, submit_fixer, delete_task_gql and
    claim_reward are the choke points the WEB app's generate/edit/fix/delete/claim
    routes all funnel through -- but the CLI's run_generate, run_generate_video,
    run_reference_video and run_edit_image each build their OWN createGenerationTask
    call instead of calling through a choke point, and until 2026-07-21 none of them
    called this.
    Found by audit: with READ_ONLY=True and --confirm, every one of them reached the
    mutation, and the free-card check fired first -- a live network call before the
    guard even ran. Each of those runners now calls this as the FIRST statement of its
    actual-submit branch, before any upload or card-check, not just before the mutation
    itself.

    run_generate is a partial exception since 2026-07-24: the inferenceProfile retry
    that used to be its own reason for building a separate submit call now lives in
    submit_generation() instead (shared with every other caller), so run_generate calls
    THROUGH that choke point for the mutation itself -- but it still keeps this direct
    call too, because _apply_kaisuuken's free-card check is a real network call that
    happens BEFORE submit_generation() is reached, so a guard living only inside
    submit_generation() would let that call through first under READ_ONLY, same bug as
    the paragraph above. The other four CLI runners are unchanged -- inferenceProfile is
    only ever set by plain image-generation params, so they never needed the retry.

    upload_media() is deliberately NOT gated here -- it costs no credits and is not one
    of the four actions CLAUDE.md's contract lists (submit a generation, submit a fix,
    delete a task, claim a reward). Whether READ_ONLY should also block a free upload
    is an open question, tracked in docs/AUDIT_2026-07-21.md, not resolved by this
    docstring."""
    if READ_ONLY:
        raise PixAIError(
            "READ_ONLY is set in config.json -- refusing to {}. "
            "Remove it (or set it to false) to allow this.".format(action))


# Persisted-query hashes are PUBLIC, non-secret identifiers of PixAI's own frontend
# GraphQL operations (the same for every user, embedded in their JS bundle). The
# history feed / task detail / delete operations are NOT exposed on the public API
# the API key talks to, so these hashes are the only way to reach them. They change
# only when PixAI overhauls their frontend -- captured 2026-06-28. Override any in
# config.json if one rotates (you'll get a clear "recapture" error if it does).
PERSISTED_QUERY_HASH = _cfg.get("PERSISTED_QUERY_HASH", "") or \
    "d30424c72dc7d75d14c09d9fe447e1ac3dea8e767668092e2113efb8c817573e"
U3T = _cfg.get("U3T", "")
USER_ID = _cfg.get("USER_ID", "")  # auto-resolved from the API key (me{id}) if blank
TASK_DETAIL_HASH = _cfg.get("TASK_DETAIL_HASH", "") or \
    "2526f64c73c59fcfeff938b0f4a8b3b610f2294bc6eb6b6b281aa671ac81a08e"
# Default to the captured getGenerationModelByVersionId hash so model-name
# resolution works out of the box (override in config.json if it rotates).
MODEL_DETAIL_HASH = _cfg.get("MODEL_DETAIL_HASH", "") or \
    "0d2ab28b2991e3fd74672ffec0adf8947e599d79e0039348a7d2642e0bf8c9bc"
# Published-artwork ops (for --sync-artworks). These are public persisted-query
# identifiers, not secrets; captured 2026-06-22. Override in config.json if a
# PixAI frontend update rotates them.
ARTWORK_LIST_HASH = _cfg.get("ARTWORK_LIST_HASH", "") or \
    "ce6f4a6e63fe210c7f77b29c7b8bdce8b7ede4d4520c01de1d36e01b224918a5"
CLIENT_LIBRARY_ARTWORK = {"name": "@apollo/client", "version": "4.1.4"}
# Deletion mutation (deleteGenerationTask). Also a public persisted hash. It only
# ever touches YOUR OWN tasks, and the destructive paths are independently gated by
# explicit confirmation (typed "DELETE" in the gallery; --apply plus a typed "delete"
# on the CLI -- NOT --confirm, which gates credit-spending generation), so the default
# is safe; override in config.json if it rotates.
DELETE_TASK_HASH = _cfg.get("DELETE_TASK_HASH", "") or \
    "9f0c8dd3edfe712a4479d700df0b33faebbbc28c7d2310589ea192e1a35d6ee4"
DELETE_OPERATION = "deleteGenerationTask"
# ===========================================================================

# Media URL: https://api.pixai.art/v1/media/<id>
MEDIA_BASE = "https://api.pixai.art/v1/media/{id}"
# ===========================================================================


def load_token(cli_token=None):
    # Priority: explicit --token > PIXAI_API_KEY (config) > PIXAI_TOKEN env > token.txt.
    # The official API key is preferred because it's long-lived (up to ~2 years) and
    # authenticates the same Bearer endpoint -- no expiring browser JWT to recapture.
    if cli_token:
        return cli_token.strip()
    api_key = (_cfg.get("PIXAI_API_KEY", "") or "").strip()
    if not api_key:
        fresh = _load_config()
        api_key = (fresh.get("PIXAI_API_KEY", "") if fresh else "").strip()
    if api_key:
        return api_key
    env = os.environ.get("PIXAI_TOKEN")
    if env:
        return env.strip()
    for f in (Path(__file__).resolve().parent / "token.txt", Path("token.txt")):
        if f.exists():
            return f.read_text(encoding="utf-8").strip()
    raise PixAIError("No credential found. Add PIXAI_API_KEY to config.json (preferred), "
                     "set PIXAI_TOKEN, pass --token, or create token.txt.")


def _ssl_help():
    return ("\nSSL verification failed (antivirus/proxy intercepting HTTPS).\n"
            "Fix safely:  pip install truststore   then re-run.\n"
            "(truststore active this run: {})\n".format(_TRUSTSTORE_ACTIVE))


def _format_size(num_bytes):
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return "{:.1f} {}".format(num_bytes, unit)
        num_bytes /= 1024
    return "{:.1f} PB".format(num_bytes)


def _progress_line(done, total, new=0, width=40):
    """Return a \r-overwriting progress line for terminal output."""
    new_str = "  +{} new".format(new) if new else ""
    if total:
        pct = min(done / total, 1.0)
        filled = int(width * pct)
        bar = ("=" * filled + ">" + " " * (width - filled - 1)
               if filled < width else "=" * width)
        return "\r  [{bar}] {done}/{total} checked ({pct:.1f}%){new}  ".format(
            bar=bar, done=done, total=total, pct=pct * 100, new=new_str)
    return "\r  Checking: {done} images...{new}  ".format(done=done, new=new_str)


# Line prefix the Control Panel greps for to drive its live progress bar. Deliberately a
# non-whitespace ASCII token (a str.strip() anywhere must NOT be able to eat it) that won't
# collide with normal log output. Fields after it are done|total|new.
PANEL_PROGRESS_PREFIX = "~=MGPROG=~"

# Same idea as PANEL_PROGRESS_PREFIX, for a different signal (D-4): a download run that
# finished with some files failed after retries, but exit code 0 by design -- the Panel
# subprocess has no other way to tell "done" from "done, but N files failed" apart from
# this marker line. The field after it is the fail count.
PANEL_WARN_PREFIX = "~=MGWARN=~"


def _make_progress(out_dir=None, job_id=None):
    """Return a progress(done, total, new=0) callback. Under the Control Panel
    (env MOONGLADE_PROGRESS=1) it emits newline-terminated machine markers the panel parses into
    a live bar; in a terminal it draws the \\r-overwriting bar. So long jobs (dedup/audit/sync)
    show real progress in BOTH places instead of just spinning silently.

    When `out_dir` + `job_id` are BOTH given, the terminal-bar callback ALSO appends a
    throttled 'running' progress heartbeat (~once per 1% tick, same throttling as the
    Control Panel's own _panel_reader) to out_dir/jobs.jsonl via append_job_event. This is
    purely additive -- a side-channel log write -- and never changes what gets printed to
    stdout; it's what lets a bare-terminal run build the same jobs.jsonl activity trail a
    panel-spawned subprocess already gets (the panel logs its OWN job by parsing the
    MOONGLADE_PROGRESS markers below, so that branch deliberately does NOT also log here --
    doing so would double the Jobs card entry for one real run)."""
    _last_pct = {"v": -1}

    def _log_tick(done, total):
        if not (out_dir and job_id and total):
            return
        try:
            pct = int(min(done / total, 1.0) * 100)
        except (TypeError, ZeroDivisionError):
            return
        if pct == _last_pct["v"]:
            return
        _last_pct["v"] = pct
        try:
            append_job_event(out_dir, job_id, status="running",
                             done=int(done), total=int(total))
        except Exception:                                  # noqa: BLE001 -- fail-soft logging
            pass

    if os.environ.get("MOONGLADE_PROGRESS") == "1":
        def _cb(done, total, new=0):
            print("{}{}|{}|{}".format(PANEL_PROGRESS_PREFIX,
                                      int(done), int(total or 0), int(new)), flush=True)
        return _cb

    def _cb(done, total, new=0):
        sys.stdout.write(_progress_line(done, total, new))
        sys.stdout.flush()
        _log_tick(done, total)
    return _cb


# ---------------------------------------------------------------------------
# Job log: an APPEND-ONLY activity registry that the web "Jobs" card reads.
# Several processes write it -- the Flask server, panel subprocesses, and the
# CLI run straight from a terminal -- so every writer just opens in "a" mode
# and appends ONE json line recording a job's current state. Readers replay the
# tail and collapse by job_id (last event wins; a terminal done/failed never
# reverts to running). Append-only sidesteps the read-modify-write races a
# single mutated JSON blob would have across processes. It doubles as a plain
# debug dump -- open jobs.jsonl and read it. Consumed by moonglade_gallery.py.
# ---------------------------------------------------------------------------
JOBS_LOG_NAME = "jobs.jsonl"
JOBS_KEEP = 50                 # show at most this many most-recent jobs
JOBS_MAX_AGE = 24 * 3600       # drop FINISHED jobs older than this (seconds)
_JOBS_TERMINAL = ("done", "failed", "done_with_errors")
_JOBS_COMPACT_AT = 2000        # rewrite the raw log once it passes this many lines

# How stale a 'running' job has to be before the ongoing /api/jobs reconciliation
# sweep (resolve_orphan_jobs, called with min_age=this from moonglade_gallery.py's
# api_jobs()) will re-ask PixAI for its real status. This is a *different* clock
# from --poll-timeout: --poll-timeout (300s generate / 600s video, see argparse
# defaults) bounds how long the CLI waits on ONE task it's actively watching --
# it's "the task itself timed out". This bounds something else: "the client
# stopped watching" (a closed tab, a dead Generate card, a crashed browser) while
# the task itself may still be legitimately in flight. Picking --poll-timeout's
# own 300s here would false-flag any real generation slower than 5 minutes --
# ordinary for video -- as an orphan on every single /api/jobs poll (the web
# generate path never re-stamps a running job's `ts` past its initial submit
# event, so nothing else naturally resets that clock). 1800s (30 minutes) is
# comfortably past every known real generation time (routine within minutes;
# --poll-timeout only waits up to 600s even for video) while still surfacing a
# genuine orphan same-day, far short of JOBS_MAX_AGE's 24h silent drop-from-view.
JOBS_ORPHAN_SWEEP_AGE = 30 * 60


def _jobs_path(out_dir):
    return Path(out_dir) / JOBS_LOG_NAME


def append_job_event(out_dir, job_id, status=None, **fields):
    """Append ONE job event to jobs.jsonl (append-only; safe from many processes).
    Each call records a job's CURRENT state; readers collapse by job_id. Known
    fields: type, label, done, total, media_ids, error, source, dismissed. `ts`
    is stamped here. Fails soft -- logging a job must never break the job.

    Every STRING field is capped at 200 chars here, at the one write choke point
    every job event from every source funnels through (web routes' own _log_job
    wrapper, the Panel's subprocess reader, the CLI's own job logging). Found
    2026-07-21: _cli_job_finish wrote a caught exception's str(e) here with NO cap
    at all -- the only error-write in either module missing one -- fed by blanket
    `except Exception` wrappers around whole download/sync runs, so an unbounded
    message (a long traceback, an arbitrarily large error string) could land here
    verbatim and later get served back to any LOGIN caller via /api/jobs. 200
    matches the str(e)[:200] convention already used at every other error-serving
    site in this app, rather than inventing a new limit.

    This bounds SIZE, not CONTENT -- a short message can still contain a host path
    (`C:\\Users\\...` easily fits in 200 chars). Redacting host detail out of error
    text generally is a separate, larger, deliberately deferred piece of work (see
    docs/AUDIT_2026-07-21.md, S3) -- a first attempt at that used a regex that
    stopped redacting at the first space, silently leaving a spaced username
    exposed, which is exactly the kind of narrow-looking fix that is easy to get
    subtly wrong. This closes the "totally unbounded" half safely tonight without
    reopening that harder problem."""
    if not job_id:
        return
    rec = {"ts": time.time(), "job_id": str(job_id)}
    if status is not None:
        rec["status"] = status
    for k, v in fields.items():
        if v is None:
            continue
        rec[k] = v[:200] if isinstance(v, str) else v
    try:
        with _jobs_path(out_dir).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI-side job logging: gives a command run straight from a terminal
# (python moonglade_backup.py --sync / --update / --generate / ...) the SAME
# jobs.jsonl activity trail a panel-spawned subprocess already gets from
# moonglade_gallery.py's _panel_run/_panel_reader (job_id "panel-<uuid>") and
# delete_tasks_bulk (job_id "bulkdel-<uuid>") -- this is the "cli-<uuid>" flavor.
# Deliberately a no-op under the Control Panel itself (MOONGLADE_PROGRESS=1): the
# panel already logs its OWN "panel-<uuid>" job for that exact subprocess, so
# creating a second "cli-<uuid>" job here would just double the Jobs card entry
# for one real run. Every call is fail-soft -- a logging problem must NEVER
# crash, block, or change the outcome of the real command.
# ---------------------------------------------------------------------------

def _cli_job_start(out_dir, label):
    """Start a 'cli-<uuid>' job for a bare-terminal run. Returns the job_id, or None
    when under the panel (see module note above) or if logging itself fails."""
    if os.environ.get("MOONGLADE_PROGRESS") == "1":
        return None
    try:
        import uuid
        job_id = "cli-" + uuid.uuid4().hex[:12]
        append_job_event(out_dir, job_id, status="running", type="cli", label=label)
        return job_id
    except Exception:                                       # noqa: BLE001 -- fail-soft logging
        return None


def _cli_job_finish(out_dir, job_id, error=None, warn=0, warn_detail=None):
    """Terminal event for a _cli_job_start job. No-op if no job was started.

    `warn` (D-4): a partial-failure count from a run that otherwise completed (some
    files failed to download after retries, but the run itself didn't raise). Logged
    as its own terminal status, "done_with_errors", distinct from both "done" (clean)
    and "failed" (the run itself raised) -- so a scheduled/automated caller, or the
    Panel's Jobs tray, can tell "ran but lost files" apart from either extreme instead
    of everything but a hard crash collapsing into a silent "done".

    `warn_detail` (B15): overrides the default "file(s) failed to download" noun
    phrase for a caller whose `warn` count isn't about downloaded files -- e.g.
    run_sync_artworks, where it can mean a page fetch that failed mid-pagination or
    a failed video download. The done_with_errors status/marker mechanism itself is
    unchanged; only the human-readable detail text differs."""
    if not job_id:
        return
    try:
        if error is not None:
            append_job_event(out_dir, job_id, status="failed", error=str(error))
        elif warn:
            detail = warn_detail or "file(s) failed to download"
            append_job_event(out_dir, job_id, status="done_with_errors",
                             error="{} {}".format(warn, detail))
        else:
            append_job_event(out_dir, job_id, status="done")
    except Exception:                                       # noqa: BLE001 -- fail-soft logging
        pass


def _reconstruct_jobs(out_dir):
    """Replay the whole log, collapsing by job_id. Returns (jobs_by_id, first_seen_order,
    raw_line_count). A terminal (done/failed) job is sticky: a later non-terminal event (a
    stale/interleaved heartbeat) can neither revert its status nor inject progress fields
    onto it -- only an explicit dismiss is honored once a job has finished.

    `started_at` (owner field-report 2026-07-23: two stuck generations, no way to recover
    their task id without server access) -- the FIRST event's `ts` is the job's true
    registration time, but every later event's `cur.update(rec)` used to blindly overwrite
    `ts` with its own, so by the time a job reached a terminal state the original start
    time was gone, and "time spent" was not reconstructable client-side. Stamped here, once,
    off the first event seen for a job_id, and never touched again by later merges (later
    events don't carry their own `started_at` key, so `cur.update(rec)` can't clobber it).
    `rec.setdefault` (not a plain assignment) also makes this correct across compaction: a
    compacted log's single surviving line for a job already HAS a real `started_at` baked
    in from a prior reconstruction, and re-deriving it from that line's own `ts` (the last
    known event, not the true start) would be wrong -- setdefault leaves an already-present
    value alone."""
    jobs, order, n = {}, [], 0
    try:
        with _jobs_path(out_dir).open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                n += 1
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                jid = rec.get("job_id")
                if not jid:
                    continue
                cur = jobs.get(jid)
                if cur is None:
                    rec.setdefault("started_at", rec.get("ts"))
                    jobs[jid] = rec
                    order.append(jid)
                elif cur.get("status") in _JOBS_TERMINAL and rec.get("status") not in _JOBS_TERMINAL:
                    # finished job + a stale heartbeat: ignore all of it EXCEPT an explicit
                    # dismiss (which is exactly how a done/failed job gets cleared).
                    if "dismissed" in rec:
                        cur["dismissed"] = rec["dismissed"]
                else:
                    cur.update(rec)
    except OSError:
        return {}, [], 0
    return jobs, order, n


def _job_expired(job, now, max_age):
    """A job is expired once there's been no activity (its last event's ts) for max_age.
    This applies to RUNNING jobs too: a 'running' entry with no heartbeat for a full day is
    a zombie (the tab closed, or a blip hit before the done poll) -- ageing it out keeps the
    card honest and stops orphaned entries leaking into the log forever."""
    return bool(max_age) and (now - float(job.get("ts") or 0)) > max_age


def _select_jobs(jobs, order, now, keep, max_age):
    """The single canonical selection used by BOTH read_jobs and maybe_compact_jobs, so the
    card and the on-disk compaction can never disagree about which jobs survive. Drops
    dismissed + expired; keeps ALL surviving running jobs (never capped away mid-flight);
    caps only the FINISHED history to `keep`. Returns newest-first; ties break by first-seen
    order (stable), which is identical at both call sites."""
    live, done = [], []
    for jid in order:                       # order = first-seen -> a stable, shared tiebreak
        j = jobs[jid]
        if j.get("dismissed") or _job_expired(j, now, max_age):
            continue
        (live if j.get("status") not in _JOBS_TERMINAL else done).append(j)
    live.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    done.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    if keep:
        done = done[:keep]                  # cap the finished history only, never running
    merged = live + done
    merged.sort(key=lambda j: float(j.get("ts") or 0), reverse=True)
    return merged


def read_jobs(out_dir, keep=JOBS_KEEP, max_age=JOBS_MAX_AGE, now=None):
    """Current job list for the web card: newest-first, collapsed by job_id, dismissed
    removed, stale jobs aged out, finished history capped to keep (running never capped).
    Each job carries both `ts` (its most recent event) and `started_at` (its registration
    event -- see `_reconstruct_jobs`), so a caller can compute elapsed time for a running
    job (now - started_at) or a finished one (ts - started_at) without a backend change."""
    jobs, order, _n = _reconstruct_jobs(out_dir)
    if not jobs:
        return []
    return _select_jobs(jobs, order, time.time() if now is None else now, keep, max_age)


def resolve_orphan_jobs(out_dir, status_fn, min_age=0, now=None):
    """Resolve jobs stuck at 'running' by asking `status_fn(task_id)` for their true state
    and appending a terminal event when it has finished. Only PixAI-task-keyed generate
    jobs (job_id is the numeric task id) are checked -- panel/delete jobs are local and
    self-report. `status_fn` returns 'running' | 'done' | 'failed' (a raised exception on
    one job is skipped, not fatal). Fixes jobs orphaned when a Generate card was closed
    before its poll resolved. Returns the number of jobs resolved to a terminal state.

    `min_age` (seconds, default 0): skip jobs whose last event is younger than this --
    don't even call `status_fn`. 0 means "ask about every non-terminal generate job right
    now", which is what the ONE-SHOT call at live-mirror watcher startup wants (catch
    anything left stuck from a prior server session, immediately). A real `min_age`
    (JOBS_ORPHAN_SWEEP_AGE) is for the ONGOING reconciliation sweep api_jobs() runs on
    every poll -- see that constant's comment for why 300s/--poll-timeout is the wrong
    number to reuse here.

    Two behaviors below are gated on `min_age` being truthy, so the min_age=0 (startup)
    call keeps its exact original behavior -- unchanged from before this parameter
    existed, still exactly what every pre-existing test pins:

    - A `status_fn` call that comes back genuinely still 'running' for an aged-in job
      writes a lightweight 'running' heartbeat, refreshing that job's `ts`. This is the
      only RECURRING writer for a web-submitted generate job: api_task_status()'s own
      'running' branch writes at most twice per job (once when it first sees it queued,
      once when a worker starts it -- the queue/render phase the Activity tray renders),
      deliberately de-duped so it can never become a per-poll heartbeat. So without this,
      once a job crosses min_age it would get re-asked on literally every subsequent
      /api/jobs poll for as long as it keeps genuinely running -- a real video generation
      easily outlives 30 minutes. The heartbeat resets the min_age clock, so a
      still-genuinely-running job is only re-checked once per min_age, not once per poll.
    - A `status_fn` call that RAISES for an aged-in job is recorded as 'stale' -- a
      distinct, visible, non-terminal status meaning "still stuck, and we couldn't reach
      PixAI to find out why" -- instead of silently left untouched. Un-gated (min_age=0),
      a single transient blip on a job that's merely SECONDS old would immediately get
      branded 'stale', which is wrong -- that's exactly the "transient blip" case
      api_task_status()'s own except-clause deliberately declines to treat as terminal.
      Gating on min_age means only a job that has ALREADY been stuck a while, and is now
      ALSO unreachable, gets the marker."""
    resolved = 0
    now = time.time() if now is None else now
    for j in read_jobs(out_dir):
        if j.get("status") in _JOBS_TERMINAL:
            continue
        jid = str(j.get("job_id") or "")
        if j.get("type") != "generate" or not jid.isdigit():
            continue
        if min_age and (now - float(j.get("ts") or 0)) < min_age:
            continue
        try:
            phase = status_fn(jid)
        except Exception:                          # noqa: BLE001 -- one bad lookup must not stop the rest
            if min_age:
                append_job_event(out_dir, jid, status="stale",
                                 error="couldn't reach PixAI to verify this job's real status")
            continue
        started = None
        if isinstance(phase, dict):
            # Tolerate a caller handing us generation_status()'s whole
            # {status, phase, paid_credit} dict rather than the phase string. A real
            # caller did exactly that and this loop silently matched nothing for every
            # job, every time. Raising instead would not have helped -- the per-job
            # `except Exception` above swallows errors by design, so a contract
            # violation here is INVISIBLE rather than loud. Accepting both shapes is
            # what actually makes that failure mode impossible.
            started = phase.get("started")
            phase = phase.get("phase")
        if phase in _JOBS_TERMINAL:
            append_job_event(out_dir, jid, status=phase,
                             error=("task " + phase if phase == "failed" else None))
            resolved += 1
        elif started is False:
            # A task PixAI accepted, queued, and never assigned a worker. It stays
            # NON-TERMINAL for ~60 minutes before being reaped, so the branch above never
            # fires and the heartbeat below would keep the card spinning as though work
            # were happening -- which is exactly how five of the owner's generations died
            # unnoticed between 2026-07-21 and 07-24 (all `cancelled`, all
            # outputs.reason="waiting timeout", none ever dispatched).
            #
            # `stale` is reused rather than inventing a state: it already renders a warning
            # glyph + message in the tracker, and it is deliberately NOT in _JOBS_TERMINAL,
            # so if PixAI does eventually start the task a later done/failed still wins.
            # Tested `started is False`, never `not started`: a caller that omits the field
            # reports None, and "unknown" must not brand every in-flight job stale.
            append_job_event(out_dir, jid, status="stale",
                             error="PixAI accepted this job but has not started it -- no "
                                   "worker has picked it up. Unstarted tasks are cancelled "
                                   "and refunded at about 60 minutes.")
        elif min_age:
            append_job_event(out_dir, jid, status="running")   # refresh ts; see docstring
    return resolved


# Job-id prefixes for work the SERVER PROCESS itself owns -- it spawns these and nothing else
# will ever report them finished. Deliberately EXCLUDES "cli-": a CLI job belongs to a separate
# process with its own lifetime that the server knows nothing about, so sweeping one would mark a
# genuinely-running terminal command as dead. Numeric ids are PixAI generate tasks and belong to
# resolve_orphan_jobs() instead.
_JOBS_SERVER_OWNED_PREFIXES = ("panel-", "import-", "bulkdel-")


def resolve_interrupted_local_jobs(out_dir, now=None):
    """Mark server-owned jobs left non-terminal by a previous process as failed. Returns the count.

    Call this ONCE at server startup. The rule needs no age heuristic and no clock comparison,
    which is what makes it reliable: at the moment the server boots it has not yet created any
    job of its own, so every server-owned job still sitting at a non-terminal status necessarily
    belongs to a process that is gone. There is nothing left to ask, and nothing will ever arrive.

    This closes a real gap. resolve_orphan_jobs() reaps only PixAI-task-keyed generate jobs -- its
    docstring notes that panel/delete jobs "are local and self-report", which is true right up
    until the process is killed. Then the terminal event is simply never written, and the Job
    Tracker shows "running" forever. Owner's production case (2026-07-26): `panel-3d49d9bffea2`,
    a Similar-index rebuild killed by a machine-wide memory exhaustion, still displaying as
    running after the reboot. The silent-death detection shipped 2026-07-25 does not cover this
    class at all, because it is built around asking PixAI about a task id that these jobs do not
    have.

    Uses the existing "failed" status and an `error` message rather than inventing an
    "interrupted" state: failed is already terminal, already rendered by the tracker, and already
    carries a message -- and the job did, in fact, fail. A new status would need matching UI in
    mg-notify.js and a new entry in _JOBS_TERMINAL for no gain.

    ONE known imprecision, stated rather than hidden: a panel job runs as a SUBPROCESS, so if the
    server is restarted while one is genuinely still running, this marks it failed early. That
    self-corrects -- _reconstruct_jobs() only blocks a NON-terminal record from overwriting a
    terminal one, so the subprocess's own later "done" still lands (verified at the
    `cur.get("status") in _JOBS_TERMINAL` branch). Recording the owning pid on each event would
    remove the imprecision entirely; it is not worth the extra surface for a case that resolves
    itself."""
    n = 0
    for j in read_jobs(out_dir, now=now):
        if j.get("status") in _JOBS_TERMINAL:
            continue
        jid = str(j.get("job_id") or "")
        if not jid.startswith(_JOBS_SERVER_OWNED_PREFIXES):
            continue
        append_job_event(
            out_dir, jid, status="failed",
            error="Interrupted -- the app stopped before this finished. Nothing was corrupted; "
                  "run it again when you're ready.")
        n += 1
    return n


def maybe_compact_jobs(out_dir, keep=JOBS_KEEP, max_age=JOBS_MAX_AGE):
    """Opportunistically rewrite jobs.jsonl down to exactly the records _select_jobs keeps,
    so the append-only log can't grow without bound. Only fires once the raw file passes
    _JOBS_COMPACT_AT lines. Uses the SAME selection as read_jobs, so compaction can never
    delete a job the card is currently showing, nor drop an in-flight running job. A
    concurrent append from another process during the rewrite could be lost -- acceptable
    for a display/paper-trail log, and rare (compaction only). Called by the web reader."""
    jobs, order, n = _reconstruct_jobs(out_dir)
    if n <= _JOBS_COMPACT_AT:
        return
    kept = _select_jobs(jobs, order, time.time(), keep, max_age)
    kept.reverse()                          # write oldest-first so append order stays chronological
    path = _jobs_path(out_dir)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            for j in kept:
                fh.write(json.dumps(j, separators=(",", ":")) + "\n")
        tmp.replace(path)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _quick_count(session, page_size=500):
    """Paginate through the library to count total images for the progress meter.
    Uses a conservative page size (default 500) to avoid server-side Prisma
    errors that occur at large page sizes. Returns 0 on any API error so the
    download still proceeds — the progress bar degrades to a running total."""
    print("Counting library size for progress meter...")
    try:
        before = None
        total = 0
        while True:
            conn = find_connection(gql(session, page_variables(page_size, before)))
            if not conn:
                break
            for edge in conn.get("edges", []):
                node = edge.get("node", edge)
                total += len(media_ids_for(node))
            pi = conn.get("pageInfo", {})
            if not pi.get("hasPreviousPage"):
                break
            before = pi.get("startCursor")
        print("Library total: {} images\n".format(total))
        return total
    except PixAIError as e:
        print("  (count failed: {}) -- progress bar will show running total only\n".format(e))
        return 0


# ---------------------------------------------------------------------------
# Persisted GraphQL GET (with Apollo CSRF headers)
# ---------------------------------------------------------------------------
def gql(session, variables, retries=4):
    params = {
        "operation": OPERATION_NAME,
        "u3t": U3T,
        "operationName": OPERATION_NAME,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"clientLibrary": CLIENT_LIBRARY,
             "persistedQuery": {"version": 1, "sha256Hash": PERSISTED_QUERY_HASH}},
            separators=(",", ":")),
    }
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            _t = time.monotonic()
            r = session.get(API_URL, params=params, timeout=60)
        except requests.exceptions.SSLError:
            raise PixAIError(_ssl_help())
        except requests.RequestException as e:
            if attempt == retries:
                raise
            print("  network error ({}); retrying in {:.0f}s".format(e, delay))
            time.sleep(delay); delay *= 2; continue

        if r.status_code == 401:
            raise PixAIError("401 Unauthorized -- token missing/expired. Refresh and re-run.")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                r.raise_for_status()
            print("  HTTP {}; backing off {:.0f}s".format(r.status_code, delay))
            time.sleep(delay); delay *= 2; continue

        try:
            data = r.json()
        except ValueError:
            raise PixAIError("HTTP {} non-JSON response:\n{}".format(
                r.status_code, r.text[:800]))
        if data.get("errors"):
            if "PersistedQueryNotFound" in json.dumps(data["errors"]):
                raise PixAIError("Persisted-query hash not recognized. Recapture the hash "
                                 "(see RECAPTURE at the bottom of this file).")
            print("\n=== GraphQL error (HTTP {}) ===".format(r.status_code))
            print(json.dumps(data["errors"], indent=2)[:3000])
            raise PixAIError("GraphQL error (see log above).")
        if r.status_code >= 400:
            print("\nHTTP {}:\n{}".format(r.status_code, json.dumps(data, indent=2)[:1500]))
            raise PixAIError("HTTP {} error (see log above).".format(r.status_code))
        vlog("{} page -> HTTP {} ({:,} bytes) in {:.2f}s".format(
            OPERATION_NAME, r.status_code, len(r.content), time.monotonic() - _t))
        return data["data"]
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def find_connection(data):
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if "edges" in cur and "pageInfo" in cur:
                return cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def slug_from_prompt(prompt, max_len, sep="_"):
    """Make a filesystem-safe slug from a prompt preview.

    Removes characters Windows forbids (\\ / : * ? " < > |), collapses runs of
    punctuation/whitespace (commas etc.) into the separator, trims to max_len, and
    strips trailing dots/spaces/separators (which Windows dislikes).
    """
    if not prompt:
        return ""
    s = prompt.strip()
    # Drop anything that's not a word char, space, or hyphen; this removes the
    # forbidden set plus commas, quotes, parentheses, colons, etc.
    s = re.sub(r"[^\w\s-]", " ", s, flags=re.UNICODE)
    # Collapse whitespace/hyphen runs into the chosen separator.
    s = re.sub(r"[\s-]+", sep, s).strip(sep + ". ")
    if len(s) > max_len:
        s = s[:max_len].rstrip(sep + ". ")
    return s


def build_stem_name(prompt_preview, task_id, media_id, max_len, sep="_"):
    """<clean_prompt>_<task_id>_<media_id>, falling back gracefully if no prompt.

    The media_id is always last so resume can match on `_<media_id>` no matter
    what readable text precedes it. The task_id is the stable per-task anchor.
    """
    slug = slug_from_prompt(prompt_preview, max_len, sep)
    tid = str(task_id or "task")
    mid = str(media_id)
    parts = [p for p in (slug, tid, mid) if p]
    return sep.join(parts)


# The two region kinds POST /v2/task/fixer accepts, in the order a filename spells them out
# (so "hand then face" and "face then hand" produce the same marker).
_FIX_TAGS = ("face", "hand")


def fixer_block(task):
    """`parameters.chat.fixer` when this getTaskById task is a hand/face Fix, else None.

    PixAI turns a POST /v2/task/fixer submit into an ordinary taskKind=chat generation, so a
    Fix comes back looking exactly like an instruct Edit apart from this one sub-block -- it
    is the only thing that identifies the task family after the fact."""
    chat = ((task or {}).get("parameters") or {}).get("chat")
    fx = chat.get("fixer") if isinstance(chat, dict) else None
    return fx if isinstance(fx, dict) else None


def fix_marker(boxes):
    """'fix-face' / 'fix-hand' / 'fix-face-hand' for a Fix output's filename, read off the
    tags its boxes carried. An untagged box degrades to a plain 'fix' rather than guessing
    which region kind it was. Hyphens stay literal so the marker reads as ONE token beside
    the separator-joined parts around it."""
    tags = {str((b or {}).get("tag") or "").lower()
            for b in (boxes or []) if isinstance(b, dict)}
    return "-".join(["fix"] + [t for t in _FIX_TAGS if t in tags])


def build_fix_stem_name(source_label, boxes, task_id, media_id, max_len, sep="_"):
    """`<source-slug>_fix-face_<task_id>_<media_id>` -- the filename stem for a Fix output.

    build_stem_name cannot serve this family: a fixer task's `prompts` is a FIXED template
    PixAI writes itself ("Image 2 shows the areas in Image 1 that need fixing..."), so every
    Fix output it ever named got the same meaningless 60-character slug and a folder of them
    was unbrowsable. The readable half comes from the SOURCE image instead, and the marker
    says which kind of region was repaired.

    Two ordering rules, both load-bearing: the source slug leads, so a Fix sorts directly
    beside the image it repaired (same slug, and the source's own name continues with a
    digit while this one continues with 'f'); and media_id stays LAST, so invariant 7's
    shared `_<media_id>` matcher -- resume, already_downloaded, organize -- still finds it.
    The length cap applies to the slug only, so the marker can never be truncated away."""
    slug = slug_from_prompt(source_label, max_len, sep)
    parts = [p for p in (slug, fix_marker(boxes), str(task_id or "task"), str(media_id)) if p]
    return sep.join(parts)


def already_downloaded(root, media_id):
    """Return an existing image file for this media_id anywhere under root,
    regardless of its prompt prefix, task id, or which subfolder it's in.

    Uses the shared `find_files_for_media_id` matcher so resume recognizes BOTH
    naming layouts — prefixed `*_<mid>.*` AND bare `<mid>.*` (the single-image
    --organize month layout). Before this was aligned, bare month files were
    invisible to resume, so every re-download re-fetched them as flat files and
    organize left the flat copy orphaned -> the images/+month duplication."""
    matches = find_files_for_media_id(root, media_id)
    return matches[0] if matches else None


def already_downloaded_video(root, media_id):
    """Video-aware sibling of already_downloaded() (B16, audit 2026-07-21).

    already_downloaded() alone is a guaranteed-False no-op for videos: its default
    matcher (find_files_for_media_id's _IMAGE_EXTS) never matches .mp4/.webm/etc,
    so --sync-artworks --with-videos' resume check fired a full resolve_media
    network round trip on every single run, even for a video already on disk. Same
    shared matcher, same exact-match + quarantine-exclusion contract -- just
    _VIDEO_EXTS instead of the image-only default."""
    matches = find_files_for_media_id(root, media_id, exts=_VIDEO_EXTS)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Content hashing (shared by --audit content dedup and organize's same-bytes check)
# ---------------------------------------------------------------------------
def _file_sha(path, _chunk=1 << 20):
    """Streamed blake2b digest of a file. Returns hex str, or None on read error."""
    import hashlib
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(_chunk), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _same_bytes(a, b):
    """True if two files are byte-identical. Cheap size check first, then hash."""
    try:
        sa, sb = a.stat().st_size, b.stat().st_size
    except OSError:
        return False
    if sa != sb:
        return False
    ha = _file_sha(a)
    return ha is not None and ha == _file_sha(b)


def _same_pixels(a, b):
    """True if two images have identical pixel content, ignoring container/metadata
    differences (e.g. a PNG with embedded prompt text vs the same image without).
    Returns None if Pillow is unavailable or either file can't be decoded."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    try:
        with Image.open(a) as ia, Image.open(b) as ib:
            if ia.size != ib.size:
                return False
            ra, rb = ia.convert("RGBA"), ib.convert("RGBA")
            return ImageChops.difference(ra, rb).getbbox() is None
    except Exception:
        return None


def media_ids_for(node):
    ids = []
    if node.get("mediaId"):
        ids.append(str(node["mediaId"]))
    for b in (node.get("batchMediaIds") or []):
        if b:
            ids.append(str(b))
    return list(dict.fromkeys(ids))


def _is_video_task_node(node):
    """A listing node is a VIDEO task iff it carries `i2vProModel` (set for BOTH i2v and
    reference-video -- verified across the whole feed: 100% of video tasks have it, no image
    task does). Such a node's `mediaId` is the video's poster STILL, so the image download
    path must SKIP it -- otherwise that still gets catalogued as a standalone image, a
    duplicate of the video's own poster (the "video shown as a phantom image" bug). The real
    video is backed up by run_sync_videos, which keys off this same field."""
    return bool(node.get("i2vProModel"))


def extract_meta(node):
    return {
        "task_id": node.get("id", ""),
        "created_at": node.get("createdAt", ""),
        "prompt_preview": node.get("promptsPreview", "") or "",
        "status": node.get("status", ""),
    }


# ---------------------------------------------------------------------------
# Media URL + variant detection + download
# ---------------------------------------------------------------------------
# Preference order of variant labels inside the media object's "urls" list.
URL_VARIANT_PREFERENCE = ["PUBLIC", "ORIGINAL", "ORIG", "FULL", "THUMBNAIL", "STILL_THUMBNAIL"]


def resolve_media(session, mid):
    """Fetch the media object and return (best_full_res_url, info_dict).

    Reads the object's `urls` list and picks the highest-quality variant
    (PUBLIC = full-resolution original on PixAI). Returns (None, {}) on failure.
    """
    _t = time.monotonic()
    try:
        r = session.get(MEDIA_BASE.format(id=mid), timeout=30)
        r.raise_for_status()
        obj = r.json()
    except (requests.RequestException, ValueError) as e:
        vlog("resolve_media {} FAILED in {:.2f}s ({})".format(
            mid, time.monotonic() - _t, e))
        return None, {}
    urls = obj.get("urls") or []
    by_variant = {}
    for u in urls:
        if isinstance(u, dict) and u.get("url"):
            by_variant[str(u.get("variant", "")).upper()] = u["url"]
    chosen = None
    for pref in URL_VARIANT_PREFERENCE:
        if pref in by_variant:
            chosen = by_variant[pref]
            break
    if not chosen and by_variant:
        chosen = next(iter(by_variant.values()))
    info = {"width": obj.get("width"), "height": obj.get("height"),
            "type": obj.get("type", "")}
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
    """
    try:
        from PIL import Image, PngImagePlugin
    except ImportError:
        return "pillow-missing"
    ext = path.suffix.lower()
    pairs = [(str(k), str(v)) for k, v in fields.items() if v not in (None, "")]
    try:
        if ext == ".png":
            with Image.open(path) as im:
                im.load()
                meta = PngImagePlugin.PngInfo()
                for k, v in pairs:
                    meta.add_text(k, v)
                im.save(path, "PNG", pnginfo=meta, optimize=True)
            return "ok"
        if ext in (".jpg", ".jpeg"):
            with Image.open(path) as im:
                im.load()
                exif = im.getexif()
                desc = "; ".join("{}={}".format(k, v) for k, v in pairs)
                exif[0x010E] = desc[:1500]  # ImageDescription
                im.save(path, "JPEG", quality="keep", exif=exif)
            return "ok"
        return "unsupported"
    except Exception as e:
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


def _atomic_replace(tmp, dest, attempts=6, base_delay=0.15):
    """`os.replace(tmp, dest)` with a short backoff retry on a transient Windows sharing
    violation. On Windows, antivirus / the Search Indexer briefly opens a file the instant
    it's created, so renaming a just-written `.part` file can raise
    PermissionError [WinError 32] for a few hundred ms. A handful of retries clears it; a
    file that's genuinely stuck still raises on the final attempt so the caller sees the real
    error. No-op difference from a bare replace on POSIX (the violation never occurs there).

    This is why a finished video could vanish from the panel: the poster download's rename
    threw here, *before* the video row was cataloged, so the clip was pulled but never saved.
    (Its callers now also treat a poster failure as non-fatal -- see _download_video_task.)"""
    for i in range(attempts):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))


def download(session, url, stem, retries=3, convert=None,
             jpeg_quality=92, jpeg_bg="white", keep_webp=False):
    """stem is a Path WITHOUT extension. Returns (status, final_path_or_None)."""
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
                tmp = dest.with_suffix(dest.suffix + ".part")
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


def page_variables(page_size, before=None):
    v = {"last": page_size, "userId": USER_ID}
    if before:
        v["before"] = before
    return v


# ---------------------------------------------------------------------------
# Full-meta API (task detail + model name)
# ---------------------------------------------------------------------------
_FULL_META_FIELDS = (
    "prompt_full", "natural_prompt", "seed", "steps",
    "sampler", "cfg_scale", "model_id", "model_name", "loras",
    "negative_prompt", "clip_skip", "paid_credit",
)


def _paid_credit_str(task):
    """Catalog-string form of a task dict's server-reported `paidCredit` (the ACTUAL
    credit cost, known once the task ran). '' when the field is absent/null (unknown)
    -- never coerce that to '0', because '0' is a real, meaningful value (a free card
    or daily-free gen). Task-level: callers stamp it on each of the task's media rows."""
    v = (task or {}).get("paidCredit")
    return "" if v is None else str(v)


def task_detail_gql(session, task_id):
    """GET getTaskById for one task. Returns the task dict or None on failure."""
    if not TASK_DETAIL_HASH:
        # Defensive only: TASK_DETAIL_HASH ships with a working built-in default (see
        # its module-level assignment above), so this fires only if that default is
        # stripped or someone blanks it in config.json -- not a real setup gate.
        raise PixAIError(
            "TASK_DETAIL_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current getTaskById "
            "sha256Hash from DevTools if the hash rotated (see RECAPTURE at the bottom of "
            "this file).")
    params = {
        "operation": "getTaskById",
        "u3t": U3T,
        "operationName": "getTaskById",
        "variables": json.dumps({"id": str(task_id)}, separators=(",", ":")),
        "extensions": json.dumps(
            {"clientLibrary": CLIENT_LIBRARY,
             "persistedQuery": {"version": 1, "sha256Hash": TASK_DETAIL_HASH}},
            separators=(",", ":")),
    }
    try:
        r = session.get(API_URL, params=params, timeout=60)
        if r.status_code != 200:
            return None
        data = r.json()
        return (data.get("data") or {}).get("task")
    except (requests.RequestException, ValueError):
        return None


_DELETE_BATCH_MEDIA_MUT = """
mutation($id: ID!, $input: UpdateGenerationTaskInput!) {
  updateGenerationTask(id: $id, input: $input) { id }
}
"""


def delete_batch_media_gql(session, task_id, media_id):
    """Delete ONE image out of a task's batch, leaving the task and its siblings alone.

    The finer-grained counterpart to `delete_task_gql`, which is task-level: deleting any
    one image there takes the whole batch with it. DELETES from your PixAI account and is
    irreversible on their side.

    Signature discovered by validation-error probing (nothing executed): the mutation is
    `updateGenerationTask(id: ID!, input: UpdateGenerationTaskInput!)` and the delete rides
    in as `{deleteBatchMedia: {mediaId}}`. It goes over the ad-hoc POST path (`gql_mutate`),
    so unlike `delete_task_gql` it needs NO persisted hash and cannot break when one rotates.

    Two properties copied deliberately from `delete_task_gql`, because both are safety
    rather than style:
      - `_check_read_only` fires BEFORE the network call. READ_ONLY is a promise the Trust
        & Safety page makes about every account-mutating path; a new destructive path that
        skipped it would be a silent hole in that promise.
      - SINGLE ATTEMPT, no retry/backoff. A flaky network must never be able to fire a
        destructive delete twice."""
    task_id, media_id = str(task_id or "").strip(), str(media_id or "").strip()
    if not task_id or not media_id:
        raise PixAIError(
            "per-image delete needs BOTH a task id and a media id (got task={!r}, media={!r}) "
            "-- a blank media id would be an update with nothing to delete, and a blank task "
            "id has no batch to delete from.".format(task_id, media_id))
    _check_read_only("delete one image from a task on your PixAI account")
    # gql_mutate is the SINGLE-ATTEMPT promise above, made real: it hard-codes retries=0,
    # where a re-POST on a RequestException or a 429/5xx could re-fire a destructive
    # mutation against a batch that has already changed underneath it (a read timeout can
    # arrive AFTER PixAI processed the delete). delete_task_gql avoids this by hand-rolling
    # its own single session.post; this is the same guarantee through the shared helper.
    return gql_mutate(session, _DELETE_BATCH_MEDIA_MUT,
                      {"id": task_id, "input": {"deleteBatchMedia": {"mediaId": media_id}}})


def delete_task_gql(session, task_id):
    """Replay the deleteGenerationTask persisted mutation for ONE task id.

    DELETES the generation from your PixAI account -- irreversible. This is a void
    mutation: on SUCCESS the server returns null (data.deleteGenerationTask == None),
    so the meaningful signal is the ABSENCE of an error, not the payload. Raises
    PixAIError with a clear message on any failure. Deliberately single-attempt (NO
    retry/backoff loop) so a flaky network can never cause a delete to fire twice.
    """
    _check_read_only("delete a task from your PixAI account")
    # Defensive only: DELETE_TASK_HASH ships with a working built-in default, so this
    # can fire solely if that default is stripped or the hash rotates and someone blanks
    # it. It is NOT a setup gate -- --apply plus the typed "delete" confirm are what stand
    # between a caller and a real delete.
    if not DELETE_TASK_HASH:
        raise PixAIError(
            "DELETE_TASK_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current "
            "deleteGenerationTask sha256Hash from DevTools (Network -> graphql -> a delete "
            "request -> Payload -> extensions.persistedQuery.sha256Hash) if the hash rotated.")
    # Mutations are POST (Apollo blocks them over GET). Mirror the site's params.
    params = {"operation": DELETE_OPERATION, "u3t": U3T}
    body = {
        "operationName": DELETE_OPERATION,
        "variables": {"taskId": str(task_id)},
        "extensions": {"clientLibrary": CLIENT_LIBRARY,
                       "persistedQuery": {"version": 1, "sha256Hash": DELETE_TASK_HASH}},
    }
    _t = time.monotonic()
    try:
        r = session.post(API_URL, params=params, json=body, timeout=60)
    except requests.exceptions.SSLError:
        raise PixAIError(_ssl_help())
    except requests.RequestException as e:
        raise PixAIError("network error deleting task {}: {}".format(task_id, e))

    if r.status_code == 401:
        raise PixAIError("401 Unauthorized -- token missing/expired. Refresh and re-run.")
    try:
        data = r.json()
    except ValueError:
        raise PixAIError("HTTP {} non-JSON response deleting task {}:\n{}".format(
            r.status_code, task_id, r.text[:500]))
    if data.get("errors"):
        msg = json.dumps(data["errors"])
        if "PersistedQueryNotFound" in msg:
            raise PixAIError("deleteGenerationTask hash not recognized -- recapture "
                             "DELETE_TASK_HASH into config.json (see RECAPTURE).")
        raise PixAIError("GraphQL error deleting task {}: {}".format(task_id, msg[:600]))
    if r.status_code >= 400:
        raise PixAIError("HTTP {} deleting task {}:\n{}".format(
            r.status_code, task_id, json.dumps(data)[:600]))
    result = (data.get("data") or {}).get(DELETE_OPERATION)
    vlog("deleteGenerationTask {} -> {} in {:.2f}s".format(
        task_id, result, time.monotonic() - _t))
    return result


def _is_mutation_document(query):
    """True when `query` is a GraphQL MUTATION document rather than a query.

    Deliberately a dumb leading-keyword check: every document in this module is a plain
    string literal that starts with its operation type. Anything it cannot classify falls
    back to False (treated as a query), which is the behaviour that existed before it."""
    return str(query or "").lstrip().lower().startswith("mutation")


def gql_adhoc(session, query, variables=None, retries=None):
    """Run an ad-hoc (non-persisted) GraphQL operation by POSTing the full query
    document. PixAI's endpoint accepts these under Bearer auth (the API key has
    read+write scope), so NO persisted sha256Hash capture is needed -- this is the
    generic foundation for every read/write op beyond the reverse-engineered
    listing path. Returns the `data` dict; raises PixAIError on GraphQL/HTTP error.

    Mutations must be POST (Apollo blocks them over GET); this always POSTs, so it
    works for queries and mutations alike.

    RETRIES. `retries=None` (the default) means "the safe default for THIS document":
    **3 for a query, 0 for a mutation**. A retry re-POSTs on a RequestException or a
    429/5xx, and that is only free when the operation is idempotent. It is not free for a
    mutation, because a lost RESPONSE is indistinguishable from a lost REQUEST -- a read
    timeout, a dropped connection, or a 502 from a proxy can all arrive AFTER PixAI has
    already created the task and charged for it, and the retry then submits (and pays for)
    a second one. Spending and account-mutating callers should still go through
    `gql_mutate()`, which cannot be handed a retry count at all; this default is the
    backstop for a future call site that reaches for `gql_adhoc` and forgets. An explicit
    integer always wins, so a caller can still ask for anything on purpose."""
    if retries is None:
        retries = 0 if _is_mutation_document(query) else 3
    body = {"query": query, "variables": variables or {}}
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            r = session.post(API_URL, json=body, timeout=120)
        except requests.exceptions.SSLError:
            raise PixAIError(_ssl_help())
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(delay); delay *= 2; continue
        if r.status_code == 401:
            raise PixAIError("401 Unauthorized -- API key missing/expired.")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                r.raise_for_status()
            time.sleep(delay); delay *= 2; continue
        try:
            data = r.json()
        except ValueError:
            raise PixAIError("HTTP {} non-JSON response:\n{}".format(r.status_code, r.text[:400]))
        if data.get("errors"):
            raise PixAIError("GraphQL error: " + json.dumps(data["errors"])[:500])
        return data.get("data") or {}
    raise RuntimeError("unreachable")


def gql_mutate(session, query, variables=None):
    """`gql_adhoc` for a mutation that MUST NOT fire twice: SINGLE ATTEMPT, always.

    Every credit-spending or account-mutating GraphQL call goes through here instead of
    calling `gql_adhoc` directly -- createGenerationTask (image, edit, video, reference
    video), uploadMedia, and the per-image delete. It takes **no `retries` argument on
    purpose**: there is no correct value above 0 for a spending path, so the knob simply
    is not offered rather than being offered with a safe default that a call site can
    override by accident. That is the whole design -- a new spend path written against
    this helper inherits the safe behaviour, and one written against `gql_adhoc` gets it
    anyway from that function's mutation-aware default.

    Why a retry is not free here: `gql_adhoc`'s retry loop re-POSTs on a RequestException
    or a 429/5xx, and a lost RESPONSE looks exactly like a lost REQUEST. A read timeout, a
    dropped connection, or a proxy's 502 after the backend already succeeded all leave
    PixAI holding a created, CHARGED task while the client believes nothing happened -- so
    the retry submits a second generation and pays for it twice. The same reasoning made
    `delete_batch_media_gql` single-attempt (there the damage is a second irreversible
    delete against a batch that already changed underneath it) and keeps `delete_task_gql`
    hand-rolling its own lone `session.post`.

    A 429 alone WOULD be safe to re-send (rate-limited means the request was refused, not
    processed), but 429 and 5xx share one branch in `gql_adhoc` and a 5xx is genuinely
    ambiguous. The trade is deliberate: not retrying costs an error the caller can see and
    act on; retrying wrongly costs credits they cannot get back."""
    return gql_adhoc(session, query, variables, retries=0)


def resolve_user_id(session):
    """Resolve the authenticated account's user id from the API key, via the public
    `me` query (the one account-scoped query the ad-hoc API surface exposes). Lets
    setup work with just PIXAI_API_KEY -- no manual USER_ID needed."""
    data = gql_adhoc(session, "query{ me{ id } }")
    uid = ((data or {}).get("me") or {}).get("id", "")
    if not uid:
        raise PixAIError("the `me` query returned no id")
    return str(uid)


def media_file_gql(session, media_id):
    """Resolve a VIDEO media's actual file URL. The REST /v1/media endpoint
    returns an empty urls[] for videos; the GraphQL `media` object carries the
    real mp4 in `fileUrl`. Returns {'fileUrl','type','duration'} or {}."""
    query = ("query($id:String!){ media(id:$id){ id type duration fileUrl "
             "hlsUrl size } }")
    try:
        return (gql_adhoc(session, query, {"id": str(media_id)}) or {}).get("media") or {}
    except PixAIError:
        return {}


def video_outputs(task):
    """Extract image-to-video outputs from a getTaskById result. Returns a list of
    {video_media_id, poster_media_id, seed} plus the shared prompt/duration."""
    if not task:
        return [], {}
    params = task.get("parameters") or {}
    rv = params.get("referenceVideo") or {}
    shared = {
        "prompt": rv.get("prompt", ""),
        "duration": rv.get("duration", ""),
        "i2v_model": rv.get("model", ""),
    }
    outs = []
    for v in ((task.get("outputs") or {}).get("videos") or []):
        vmid = v.get("mediaId")
        if vmid:
            outs.append({
                "video_media_id": str(vmid),
                "poster_media_id": str(v.get("thumbnailMediaId") or ""),
                "seed": str(v.get("seed") or ""),
            })
    return outs, shared


def model_search_gql(session, keyword="", limit=15, base_only=False, lora_only=False):
    """Search PixAI generation models by keyword via the `generationModels`
    connection. Returns a list of {title, type, model_id, version_id}.

    IMPORTANT: createGenerationTask's `modelId` wants the *version* id, not the
    model id. The search node's `id` is the MODEL id (which generation rejects);
    `latestVersion.id` is the generatable version id. So we surface version_id as
    the value to feed into --generate.

    base_only=True drops LoRA / video types -- a LoRA can't be the BASE model
    (generation fails), so the base-model picker filters them out. LoRAs belong in
    the separate LoRA picker."""
    q = ("query($k:String,$n:Int){ generationModels(keyword:$k, first:$n){ "
         "edges { node { id title type isNsfw likedCount latestVersion { id } "
         "media { id urls { url } } } } } }")
    data = gql_adhoc(session, q, {"k": keyword, "n": limit})
    out = []
    for e in (data.get("generationModels") or {}).get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        if base_only and ("LORA" in mtype or "VIDEO" in mtype):
            continue
        if lora_only and "LORA" not in mtype:
            continue
        out.append({
            "title": n.get("title") or "",
            "type": n.get("type") or "",
            "is_nsfw": bool(n.get("isNsfw")),
            "liked_count": int(n.get("likedCount") or 0),
            "model_id": str(n.get("id") or ""),
            "version_id": str((n.get("latestVersion") or {}).get("id") or ""),
            "preview_url": _model_preview_url(n.get("media")),
        })
    return out


def _model_preview_url(media):
    """Pick a directly-displayable cover thumbnail from a generationModels node's
    `media.urls`. The CDN list is [orig, thumb, stillThumb]; the `thumb` variant is
    the right size for a picker and needs no auth. Falls back to the first url."""
    urls = [u.get("url") for u in ((media or {}).get("urls") or []) if u.get("url")]
    return next((u for u in urls if "/thumb/" in u), urls[0] if urls else "")


def model_search_rest(session, keyword="", usage="MODEL", size=24, offset=0):
    """Search models/LoRAs via the oRPC GET /v2/generation-model/search endpoint. Unlike
    the GraphQL `generationModels` connection (which conflates base models + LoRAs), this
    cleanly separates them by `usageType` (MODEL vs LORA) and returns cover thumbnails.
    Returns {results:[{title, type, model_id, liked_count, should_blur, preview_url,
    has_version}], has_more}. Read-only (no spend). NOTE: `model_id` is the MODEL id --
    resolve the generatable version id with resolve_latest_version() on selection."""
    params = {"usageType": (usage or "MODEL").upper(),
              "size": max(1, min(int(size), 50)), "offset": max(0, int(offset))}
    kw = (keyword or "").strip()
    if kw:
        params["keyword"] = kw
    data = _rest_get(session, "/generation-model/search", params=params) or {}
    out = []
    for m in data.get("data") or []:
        med = m.get("media") or {}
        flag = m.get("flag") or {}
        # Real field names (probed 2026-07-04): the rich description lives under
        # `modelDescription`, base-model family under `category`, and an official
        # badge under `curations` (e.g. ["inhouse"]). See private/GENERATOR_SURFACE.md.
        cur = m.get("curations") or []
        out.append({
            "title": m.get("title") or "",
            "type": m.get("type") or "",
            "model_id": str(m.get("id") or ""),
            "liked_count": int(m.get("likedCount") or 0),
            "should_blur": bool(flag.get("shouldBlur")),
            # publicUrl preferred (matches cover_url below): PixAI's own thumbnailUrl is a
            # small, often blurry auto-thumb -- fine as a last-resort fallback, poor as the
            # grid card's main image. loading="lazy" on the <img> bounds the cost to what's
            # actually on screen.
            "preview_url": med.get("publicUrl") or med.get("thumbnailUrl") or "",
            "has_version": bool(m.get("hasLatestAvailableVersion")),
            # Rich surface for the preview pop-out card.
            "description": (m.get("modelDescription") or "")[:600],
            "base_model": m.get("category") or "",
            "curations": [c for c in cur if isinstance(c, str)],
            "official": any((c or "").lower() == "inhouse" for c in cur if isinstance(c, str)),
            "comment_count": int(m.get("commentCount") or 0),
            "ref_count": int(m.get("refCount") or 0),
            "author_id": str(m.get("authorId") or ""),
            "cover_url": med.get("publicUrl") or med.get("thumbnailUrl") or "",
            # GraphQL-only per-viewer state absent here -> False, the mirror of
            # model_search_market_gql's "REST-only rich fields absent here -> empty so the
            # card hides them". This endpoint carries no bookmarked/liked equivalent at all,
            # so False means "this path can't tell you", NOT "confirmed not bookmarked" --
            # exactly like `official: False` on a GraphQL row. Present-and-falsy (rather than
            # missing) so a consumer can read the key off either path's rows.
            "bookmarked": False, "liked": False,
        })
    return {"results": out, "has_more": bool(data.get("hasMore"))}


# Model-Market categories the GraphQL `generationModels` connection actually honors (probed
# 2026-07-04). NOTE 'concept' is NOT a real server value (returns empty) -- excluded.
# PixAI's own nine, in their own order. Confirmed 2026-07-26 from the training page, where
# their category dropdown is currently rendering RAW i18n keys
# ("market:lora-categories.animal.label", ...) -- a bug on their side that handed over the
# canonical list. We were short two: **animal** and **realistic**. `detail` is their
# "Detail Enhancement".
MARKET_CATEGORIES = ("character", "animal", "style", "realistic", "pose", "clothing",
                    "background", "detail", "other")

# GenerationModelType enum members this app is willing to put INTO a query document, for
# generationModels(loraBaseModelTypes:[...]) -- see model_search_market_gql's lora_base_type
# argument. Only these five: the architectures confirmed to exist as a LoRA's BASE family.
# (MULTI_LORA is a LoRA's OWN type and VIDEO_MODEL is not an image base, so neither is ever a
# legitimate value here and both are deliberately absent.)
#
# This MUST stay a fixed whitelist. A GraphQL enum is a bare token, not a string -- it cannot
# be bound as a $variable, so the value is interpolated into the query text, exactly like
# MARKET_CATEGORIES above and for exactly the same reason: caller-supplied text must never
# reach a query document. Anything not listed here is silently ignored and the search runs
# UNFILTERED -- fail-open, the same way a non-whitelisted `category` is dropped. An unknown or
# newly-added architecture must degrade to "no server-side filter" (the per-row
# annotate_lora_compat badge still tells the truth), never to a rejected query that would
# break LoRA browsing outright.
LORA_BASE_MODEL_TYPES = ("SDXL_MODEL", "SD_V1_MODEL", "SD3_MEDIUM_MODEL",
                         "DIT7_MODEL", "DIT7A_MODEL", "DIT7B_MODEL", "DIT7C_MODEL",
                         "DIT7D_MODEL", "DIT9_MODEL",
                         "MMDIT26A_MODEL", "MMDIT26B_MODEL", "USER_DIT26A_MODEL",
                         "Z_IMAGE_V1_MODEL")

# Their Model Type filter, as a label -> enum mapping. The first four rows are MEASURED off live
# requests (drove their base-model picker 2026-07-26 and read what it sent); the last two are
# inferred from the naming and are marked as such rather than presented as fact.
#
# Two behaviours of their filter worth copying, both observed rather than assumed:
#   * "All" sends types:["ANY_MODEL"] -- it does not omit the argument.
#   * It is MULTI-SELECT. Choosing DiT.3 then DiT.1 sent types:["MMDIT26B_MODEL","DIT7_MODEL"].
#     A single-value control here would silently be the wrong shape.
# PixAI's four market sorts, every value captured off a live request 2026-07-26. `feed` selects
# the backend ranking and `orderBy` the field within it; Trending needs no orderBy because the
# trending feed IS the ordering.
#
# `markInfo.refCount` is the "uses" figure printed on their cards -- the same field identified
# earlier as the number on a card -- so Most Used is genuinely most-used, not most-liked again.
#
# One difference deliberately NOT copied: their trending and latest feeds page BACKWARD
# (`last`/`before`) while meilisearch pages forward (`first`/`after`). This app pages forward
# everywhere, which the connection accepts for all four, and switching direction per sort would
# mean two cursor conventions in one picker for no user-visible gain.
MARKET_SORTS = {
    "trending":   ("trending", ""),
    "liked":      ("meilisearch", "-markInfo.likedCount"),
    "used":       ("meilisearch", "-markInfo.refCount"),
    "newest":     ("latest", "-createdAt"),
}
# What the old two-button UI sent, kept working so an older client or a bookmarked URL does not
# silently lose its sort.
MARKET_SORT_ALIASES = {"popular": "trending", "latest": "newest", "": "trending"}


def market_sort(name):
    """(feed, orderBy) for a sort name, falling back to Trending for anything unrecognised."""
    key = (name or "").strip().lower()
    key = MARKET_SORT_ALIASES.get(key, key)
    return MARKET_SORTS.get(key, MARKET_SORTS["trending"])


# ALL SEVEN MEASURED off live requests (2026-07-26) -- none is inferred from its name.
MODEL_TYPE_FILTERS = (
    ("All", "ANY_MODEL"),
    ("DiT.3", "MMDIT26B_MODEL"),
    ("DiT.2", "MMDIT26A_MODEL"),
    ("DiT.1", "DIT7_MODEL"),
    ("Community DiT", "USER_DIT26A_MODEL"),
    ("SDXL", "SDXL_MODEL"),
    ("SD 1.5", "SD_V1_MODEL"),
)
# HOW THESE WERE CAPTURED, because the technique is reusable and three attempts failed first.
# Apollo's cache is IN-MEMORY, so a full page reload empties it; selecting a filter as the very
# FIRST action on a fresh load therefore has to hit the network. Earlier tries kept selecting
# other options first, and the cache could always answer.
#
# "Community DiT" was the last unknown and the one worth not guessing: USER_DIT26A_MODEL turned
# out to be right, but DIT9_MODEL was equally plausible, and a wrong enum member here fails
# SILENTLY -- the wrong rows, or none, reading as an empty result rather than an error.
#
# The filter is MULTI-SELECT: successive clicks sent ["USER_DIT26A_MODEL"], then
# [..., "SDXL_MODEL"], then [..., "SD_V1_MODEL"], which is also what settled the last two.
#
# The full 46-member GenerationModelType enum is not copied here on purpose. It is
# recoverable at any time, and stays current, via tools/harvest_api_surface.py -- their
# own contract chunk carries it verbatim. A hand-copied list would just rot.

# Their "Source" filter (All / PixAI / External) is NOT a separate argument -- it is expressed
# through `types`. Read straight out of their ModelFilter chunk, which maps the UI value to an
# enum member and back:
#     .with({type:"lora", source:"pixai"},    () => [AnyUserLora])
#     .with({type:"lora", source:"external"}, () => [AnyNonUserLora])
# and the tokens themselves are in the bundle: ANY_LORA / ANY_USER_LORA / ANY_NON_USER_LORA
# (ANY_SDXL_LORA and ANY_NON_SDXL_LORA also exist, unused here).
#
# A LoRA the OWNER trained carries type USER_MULTI_LORA -- seen on his own rows -- which is why
# "PixAI" means user-trained and "External" means uploaded from elsewhere.
LORA_SOURCE_TYPES = {
    "": "",                          # All -- send no `types` at all, preserving today's behaviour
    "pixai": "ANY_USER_LORA",
    "external": "ANY_NON_USER_LORA",
}

# Their License Type filter has exactly ONE meaningful value. Their handler is literally
#     onChange: r => a("permittedUse", r === "COMMERCIAL" ? "COMMERCIAL" : undefined)
# so it is COMMERCIAL or the argument is omitted. PermittedUse:COMMERCIAL was also observed on a
# real row. The data behind it is extra.permissions{personalUses, commercialUses,
# shareImagesOnline, shouldCreditAuthor}.
PERMITTED_USES = ("COMMERCIAL",)

# Their "Posted at" options, and the offset each one means. Captured from the live request: the
# UI sends a DateRange of {"gt": "<ISO instant>"} and nothing else -- no upper bound, no `lt`.
POSTED_AT_DAYS = {"yesterday": 1, "7d": 7, "30d": 30}


def posted_at_range(token):
    """One of POSTED_AT_DAYS -> the DateRange dict PixAI expects, or None for "All Time".

    Measured, not guessed: selecting Past 7 Days on 2026-07-26 sent
    {"gt": "2026-07-19T07:00:00.000Z"}. Note what that value is NOT -- it is not
    now-minus-168-hours. 07:00:00.000Z is local MIDNIGHT at UTC-7, so the boundary is the start
    of the day N days back, in the viewer's own timezone. Matching that matters for more than
    tidiness: a start-of-day boundary is a stable cache key, whereas a rolling
    now-minus-N-seconds mints a fresh one on every keystroke and would defeat their caching (and
    ours) for no benefit.

    Milliseconds and a literal Z, matching JSON.stringify(new Date()) in their client. An
    unrecognised token returns None, so the filter is simply absent and the search runs
    unfiltered -- the same fail-open contract as every other filter here."""
    days = POSTED_AT_DAYS.get((token or "").strip().lower())
    if not days:
        return None
    local_midnight = (datetime.datetime.now().astimezone()
                      .replace(hour=0, minute=0, second=0, microsecond=0)
                      - datetime.timedelta(days=days))
    utc = local_midnight.astimezone(datetime.timezone.utc)
    return {"gt": utc.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(utc.microsecond // 1000)}

# CORRECTION, 2026-07-26. Comments in this file state that "an enum cannot be a $variable", which
# is why `loraBaseModelTypes` is interpolated behind a whitelist. That claim is WRONG: PixAI's own
# query documents declare `$types: [GenerationModelType]`, `$permittedUse: PermittedUse` and
# `$loraBaseModelTypes: [GenerationModelType!]` and bind them normally. Verified by reading their
# documents (tools/harvest_api_surface.py).
#
# So the filters added below are BOUND VARIABLES, never interpolated -- caller text cannot reach
# the query document at all, which is strictly safer than interpolating it after a whitelist
# check. The whitelists stay, for a different reason worth keeping: an unrecognised value is
# DROPPED so the search runs unfiltered (fail-open), rather than binding a bad enum and having the
# server reject the whole query. That is the behaviour the existing filters promise and the picker
# depends on. The older interpolated path is left alone deliberately -- it works, it is guarded,
# and rewriting it is a separate change with its own risk.


def _market_row(n):
    """One `generationModels`-shaped node -> the picker's row dict.

    Extracted 2026-07-26 so the BOOKMARK tab returns rows that are IDENTICAL to MARKET's, field
    for field. Two near-copies of a 20-field dict is how a picker ends up rendering a card that
    silently loses its architecture badge on one tab only."""
    lv = n.get("latestVersion") or {}
    return {
        "title": n.get("title") or "",
        "type": n.get("type") or "",
        "model_id": str(n.get("id") or ""),
        "liked_count": int(n.get("likedCount") or 0),
        "should_blur": bool(n.get("isNsfw")),
        "preview_url": _model_preview_url(n.get("media")),
        "has_version": bool(lv.get("id")),
        # REST-only rich fields absent here -> empty so the card hides them.
        "description": "", "base_model": "", "curations": [], "official": False,
        "comment_count": 0, "ref_count": 0, "author_id": "",
        "cover_url": _model_preview_url(n.get("media")),
        # GraphQL-only extras.
        "tags": [t.get("name") for t in (n.get("tags") or []) if t.get("name")][:8],
        "author": (n.get("author") or {}).get("displayName") or "",
        "created_at": n.get("createdAt") or "",
        # Architecture, for LoRA compat sort/badging (annotate_lora_compat) -- '' when
        # the connection has no version yet, same empty-string convention as everywhere
        # else in this file (never None, so a naive .strip()/comparison never explodes).
        "model_type": lv.get("modelType") or "",
        "lora_base_model_type": lv.get("loraBaseModelType") or "",
        # Per-viewer state (GraphQL-only). Always a real bool -- a node that omits the
        # field yields False, never None, same never-None rule as the two fields above.
        "bookmarked": bool(n.get("bookmarked")),
        "liked": bool(n.get("liked")),
    }


def model_search_market_gql(session, keyword="", category="", sort="", usage="MODEL", limit=24,
                            after=None, lora_base_type="", author_id="",
                            source="", permitted_use="", time_range=None,
                            model_types=()):
    """Market-style model browse via the GraphQL `generationModels` connection, which -- unlike
    the REST /search -- actually HONORS `category` and a date `orderBy`. Use this for category
    chips + a Newest sort; the REST path (model_search_rest) stays the default for keyword/Popular
    because its rows are richer (description/refCount/official). Returns the SAME row shape as
    model_search_rest so the picker renders both interchangeably (REST-only fields come back
    empty and the card hides them), plus GraphQL-only extras: tags + created_at + author.

    category: one of MARKET_CATEGORIES (ignored if not). sort: 'newest' -> orderBy -createdAt;
    anything else -> the connection's default order. usage MODEL/LORA splits base vs LoRA rows
    (the connection conflates them). Read-only, no spend.

    `latestVersion` also requests modelType/loraBaseModelType (picker-parity-round2,
    2026-07-24) -- confirmed live: real rows come back e.g. modelType:"MULTI_LORA",
    loraBaseModelType:"SD_V1_MODEL". Costs nothing extra (same request, no additional
    round trip) and is what lets api_model_search's LoRA path do architecture-aware
    sort/badging (see annotate_lora_compat) through this GraphQL connection, which -- unlike
    REST's oRPC search -- actually carries this per-row. Surfaced as `model_type` /
    `lora_base_model_type`, the SAME key names model_search_rest's sibling
    resolve_version_meta() already uses, so callers don't care which path produced a row.

    `bookmarked` + `liked` (2026-07-24) are VIEWER-SCOPED booleans GenerationModel carries on
    every connection that returns one -- probed live: bookmarked:true on 50/50 rows of the
    owner's own bookmark connection, false on 3/3 plain market rows. Genuinely free (two more
    leaf fields on a request the picker already makes, no extra round trip). REST's oRPC
    /search has NO equivalent, so model_search_rest defaults both to False and callers must
    read False as "this path can't tell you" rather than "confirmed not bookmarked" -- the
    same convention as `official` in the other direction. Nothing renders them yet; the picker
    tab that consumes them is separate, later work.

    after=<cursor> (owner report 2026-07-24: the picker "scrolls a few rows and stops"):
    forward Relay-cursor paging -- standard `edges`/`pageInfo` connection shape, the same
    spec this app already relies on elsewhere (page_variables' before/last cursor pagination
    for task history, just the other direction). has_more was ALREADY computed correctly
    from pageInfo.hasNextPage; the real gap was that the query never requested endCursor and
    never accepted an after: argument, so a client had no way to actually ask for the next
    page even knowing one existed. Omitted entirely (not sent as an empty string) when
    absent -- a present-but-empty $a may not mean the same thing to PixAI's resolver as no
    $a at all, and this is the first page of a fresh search either way. next_cursor in the
    return is '' whenever has_more is false, even if the server's own endCursor is
    non-empty -- never hand a caller a cursor that would page forever on an exhausted list.

    lora_base_type=<GenerationModelType> (2026-07-24): SERVER-SIDE architecture filtering for
    LoRA search, via an argument this connection has accepted all along and this app never
    used -- generationModels(loraBaseModelTypes:[MMDIT26A_MODEL], ...). Ignored unless
    usage=LORA (nothing to filter a base-model list by) and unless the value is in
    LORA_BASE_MODEL_TYPES; see that tuple for why the whitelist is mandatory rather than
    defensive. Measured live: [MMDIT26A_MODEL] returned 23 of 24 rows compatible with a
    DiT.2 base, against 24-of-24 SD_V1 with no filter at all -- which is the wall that made
    LoRA browsing useless for anything but SD 1.5.

    GOTCHA, and it cost real time once already: the values are UNQUOTED GraphQL ENUM tokens.
    An earlier probe sent them as JSON strings (["MMDIT26A_MODEL"]), got a type error back,
    and the error was misread as "this argument doesn't exist" -- so the whole capability sat
    unused for weeks. Enums also cannot be bound as $variables, which is why this one value
    is interpolated while `keyword` stays a bound variable.

    The filter is APPROXIMATE, not strict: [DIT7B_MODEL] measured back 12 DiT7B rows, 10
    MMDIT26A and 2 SDXL. A search row's `loraBaseModelTypes` is a coarse browse hint (a union
    over the model's releases), not the resolved version's singular `loraBaseModelType`. So
    this narrows the candidate pool cheaply and annotate_lora_compat() remains the precise
    per-row layer on top -- do not treat the filter as a substitute for the badge."""
    cat = (category or "").strip().lower()
    # category/orderBy come from a fixed whitelist -> safe to interpolate; keyword stays a
    # bound $variable (never interpolate user text into a query).
    args = ["keyword:$k", "first:$n"]
    if cat in MARKET_CATEGORIES:
        args.append('category:"%s"' % cat)
    # Sort is a FEED plus an orderBy, both from a fixed table -- safe to interpolate, and an
    # unrecognised name falls back to Trending rather than producing a broken query.
    feed, order_by = market_sort(sort)
    args.append('feed:"%s"' % feed)
    if order_by:
        args.append('orderBy:"%s"' % order_by)
    # Server-side architecture filter -- LoRA searches only (there is nothing to filter a
    # base-model list by). The value is a BARE ENUM TOKEN, unquoted: [MMDIT26A_MODEL], never
    # ["MMDIT26A_MODEL"]. Passing them as strings is a type error the server rejects, and
    # since an enum cannot be a $variable either, this is interpolated -- hence the
    # LORA_BASE_MODEL_TYPES whitelist gate, which also makes an unrecognized architecture
    # fall through to an unfiltered search rather than a rejected query.
    want_lora = (usage or "MODEL").upper() == "LORA"
    lbt = (lora_base_type or "").strip().upper()
    if want_lora and lbt in LORA_BASE_MODEL_TYPES:
        args.append("loraBaseModelTypes:[%s]" % lbt)
    after = (after or "").strip()
    var_decl = "$k:String,$n:Int"
    variables = {"k": keyword or "", "n": int(limit)}
    if after:
        args.append("after:$a")
        var_decl += ",$a:String"
        variables["a"] = after

    # --- picker-parity round 3 (2026-07-26). All BOUND variables, all fail-open: an
    # unrecognised value is dropped and the search runs unfiltered rather than being rejected.
    #
    # authorId is the whole "MY LORA" tab -- their own MY LORA is this same connection filtered
    # by the signed-in user's id, not a separate operation.
    au = str(author_id or "").strip()
    if au:
        args.append("authorId:$au")
        var_decl += ",$au:ID"
        variables["au"] = au

    # `types` is ALWAYS sent, which is what their own pickers do -- LoRA tabs send ANY_LORA even
    # with Source set to All, and the base-model tab sends ANY_MODEL. Both were read off live
    # requests.
    #
    # This is a fix, not just parity. We used to send no `types` at all and filter by row type in
    # Python after the fetch, so asking for 24 could yield a mixed page and hand the grid far
    # fewer once the wrong kind was discarded -- short pages, almost certainly the "scrolls a few
    # rows and stops" report. Filtering server-side means a full page of the kind actually wanted.
    #
    # An explicit Source (PixAI-trained / external) narrows further and replaces ANY_LORA; their
    # own MY LORA request pairs ANY_LORA with authorId exactly as this does.
    src = str(source or "").strip().lower()
    src_enum = LORA_SOURCE_TYPES.get(src, "") if want_lora else ""

    # A base search can also narrow to specific ARCHITECTURES -- their Model Type filter, which is
    # MULTI-SELECT (choosing DiT.3 then DiT.1 sends both tokens, observed on a live request). Only
    # whitelisted members survive, so an unknown value is dropped and the search stays unfiltered
    # rather than being refused: the same fail-open contract as every other filter here.
    chosen = [t for t in (str(x).strip().upper() for x in (model_types or []))
              if t in LORA_BASE_MODEL_TYPES]
    args.append("types:$ty")
    var_decl += ",$ty:[GenerationModelType]"
    if chosen and not want_lora:
        variables["ty"] = chosen
    else:
        variables["ty"] = [src_enum or ("ANY_LORA" if want_lora else "ANY_MODEL")]

    pu = str(permitted_use or "").strip().upper()
    if pu in PERMITTED_USES:
        args.append("permittedUse:$pu")
        var_decl += ",$pu:PermittedUse"
        variables["pu"] = pu

    # timeRange takes a DateRange input object. Its FIELD NAMES are not yet captured -- they are
    # not in any query document (input types never are) and the one promising bundle hit turned
    # out to be an unrelated error payload. So this passes the caller's dict straight through and
    # omits the argument entirely when there is nothing to send. Nothing constructs a DateRange
    # here on a guess: a wrong shape would be a rejected query, and the picker must never break
    # on a filter. Capture the shape from one live request (set Posted at -> Past 7 Days with the
    # network tab open and read `timeRange`), then the only change needed is in the caller.
    if isinstance(time_range, dict) and time_range:
        args.append("timeRange:$tr")
        var_decl += ",$tr:DateRange"
        variables["tr"] = time_range
    q = ("query(" + var_decl + "){ generationModels(" + ", ".join(args) + "){ "
         "pageInfo{ hasNextPage endCursor } edges { node { id title type isNsfw "
         "likedCount bookmarked liked "
         "latestVersion { id modelType loraBaseModelType } media { id urls { url } } "
         "tags { name } author { displayName } createdAt } } } }")
    data = (gql_adhoc(session, q, variables) or {}).get("generationModels") or {}
    out = []
    for e in data.get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        is_lora = "LORA" in mtype
        if want_lora and not is_lora:
            continue
        if not want_lora and (is_lora or "VIDEO" in mtype):
            continue
        out.append(_market_row(n))
    page_info = data.get("pageInfo") or {}
    has_more = bool(page_info.get("hasNextPage"))
    return {"results": out, "has_more": has_more,
            "next_cursor": (page_info.get("endCursor") or "") if has_more else ""}


# Derived offline from PixAI's own bundle and validated against three hashes seen on real
# requests (tools/harvest_api_surface.py). Only the FALLBACK needs it -- the ad-hoc path below
# carries its own document, so a rotated hash cannot break the primary route.
BOOKMARKED_MODELS_OP = "listMyBookmarkedGenerationModels"
BOOKMARKED_MODELS_HASH = "2281653492ff54ef17707104736fd74e7a8d70dc314e024e595f0e71ff2945b9"

_BOOKMARK_NODE_FIELDS = (
    "id title type isNsfw likedCount bookmarked liked "
    "latestVersion { id modelType loraBaseModelType } media { id urls { url } } "
    "tags { name } author { displayName } createdAt")


def model_bookmarks_gql(session, keyword="", usage="MODEL", limit=24, after=None,
                        lora_base_type=""):
    """The owner's BOOKMARKED models/LoRAs, in the SAME row shape as model_search_market_gql.
    Read-only, spends nothing.

    `listMyBookmarkedGenerationModels` is an operation NAME, not a field: its document queries
    `me { bookmarkedGenerationModels(...) }`. An earlier probe asked whether the operation name
    existed on type Query, got "Cannot query field ... on type Query", and that was recorded as
    "reachable ONLY through the persisted-query path". It does not follow -- the name was never a
    field, and `me` is plainly reachable ad-hoc (resolve_user_id uses `query{ me{ id } }`).

    So this tries AD-HOC first with our own projection, and falls back to the persisted GET with
    the derived hash only if that is refused. Two reasons for that order: the ad-hoc document
    cannot rot when PixAI redeploys, and it lets us request exactly the fields a row needs instead
    of their much larger fragment. `_last_path` records which route served, so a caller (or a
    test) can tell without guessing.

    The field accepts the same filters MARKET does -- keyword, modelTypes, loraBaseModelTypes,
    loraBaseModelIds -- plus full before/after/first/last paging, so the bookmark tab is not a
    stripped-down list. Note their own UI hides its Filters button on this tab while keeping the
    architecture filter live, which is consistent with what the arguments allow."""
    want_lora = (usage or "MODEL").upper() == "LORA"
    kw = (keyword or "").strip()
    after = (after or "").strip()
    lbt = (lora_base_type or "").strip().upper()

    args = ["first:$n"]
    var_decl = "$n:Int"
    variables = {"n": int(limit)}
    if kw:
        args.append("keyword:$k")
        var_decl += ",$k:String"
        variables["k"] = kw
    if after:
        args.append("after:$a")
        var_decl += ",$a:String"
        variables["a"] = after
    # Same reasoning as the market path: ask for the kind we want rather than discarding the
    # wrong kind afterwards, so a bookmark page arrives full. ANY_LORA is what their own bookmark
    # request sends for the LoRA tab; ANY_MODEL mirrors their base-model tab.
    args.append("modelTypes:$mt")
    var_decl += ",$mt:[GenerationModelType]"
    variables["mt"] = ["ANY_LORA" if want_lora else "ANY_MODEL"]
    if want_lora and lbt in LORA_BASE_MODEL_TYPES:
        args.append("loraBaseModelTypes:$lb")
        var_decl += ",$lb:[GenerationModelType!]"
        variables["lb"] = [lbt]

    q = ("query(" + var_decl + "){ me { id bookmarkedGenerationModels(" + ", ".join(args)
         + "){ totalCount pageInfo{ hasNextPage endCursor } edges { node { "
         + _BOOKMARK_NODE_FIELDS + " } } } } }")

    conn, path = None, ""
    try:
        data = gql_adhoc(session, q, variables) or {}
        conn = ((data.get("me") or {}).get("bookmarkedGenerationModels")) or {}
        path = "adhoc"
    except PixAIError as e:
        vlog("bookmarks: ad-hoc refused ({}); trying the persisted hash".format(e))
        conn = _bookmarks_persisted(session, variables, want_lora, lbt, kw, after, int(limit))
        path = "persisted"

    out = []
    for e in conn.get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        is_lora = "LORA" in mtype
        # A bookmark list mixes base models and LoRAs exactly as the market connection does, so
        # the same split applies -- otherwise the LoRA tab shows base models and vice versa.
        if want_lora and not is_lora:
            continue
        if not want_lora and (is_lora or "VIDEO" in mtype):
            continue
        out.append(_market_row(n))

    page_info = conn.get("pageInfo") or {}
    has_more = bool(page_info.get("hasNextPage"))
    return {"results": out, "has_more": has_more,
            "next_cursor": (page_info.get("endCursor") or "") if has_more else "",
            "total": conn.get("totalCount"), "_path": path}


def _bookmarks_persisted(session, variables, want_lora, lbt, kw, after, limit):
    """Fallback: the same query over the persisted-GET path, using the derived hash.

    Their document names its variables differently from our ad-hoc one, so the payload is rebuilt
    rather than reusing `variables` -- passing `n`/`mt`/`lb` to a document expecting
    `first`/`modelTypes`/`loraBaseModelTypes` would fail for a reason that looks like a
    permissions problem and would send the next person down the wrong path entirely."""
    v = {"first": limit}
    if kw:
        v["keyword"] = kw
    if after:
        v["after"] = after
    if want_lora:
        v["modelTypes"] = ["ANY_LORA"]
    if want_lora and lbt in LORA_BASE_MODEL_TYPES:
        v["loraBaseModelTypes"] = [lbt]
    params = {
        "operation": BOOKMARKED_MODELS_OP,
        "u3t": U3T or "",
        "operationName": BOOKMARKED_MODELS_OP,
        "variables": json.dumps(v, separators=(",", ":")),
        "extensions": json.dumps(
            {"clientLibrary": CLIENT_LIBRARY,
             "persistedQuery": {"version": 1, "sha256Hash": BOOKMARKED_MODELS_HASH}},
            separators=(",", ":")),
    }
    r = session.get(API_URL, params=params, timeout=60)
    try:
        body = r.json()
    except ValueError:
        raise PixAIError("bookmarks: HTTP {} non-JSON response".format(r.status_code))
    if body.get("errors"):
        blob = json.dumps(body["errors"])[:400]
        if "PersistedQueryNotFound" in blob:
            raise PixAIError(
                "bookmarks: the persisted hash has rotated. Re-run "
                "`python tools/harvest_api_surface.py fetch` then `extract` to re-derive it "
                "-- the hashes are computed from PixAI's own bundle, so this is self-healing.")
        raise PixAIError("bookmarks: " + blob)
    return ((body.get("data") or {}).get("me") or {}).get("bookmarkedGenerationModels") or {}


def _empty_version_meta():
    return {"version_id": "", "model_type": "", "lora_base_model_type": "",
            "trigger_words": "", "negative_prompt": "", "sampling_method": "",
            "sampling_steps": None, "cfg_scale": None, "capabilities": [],
            "compatibility": {}, "restrictions": {}}


def _version_row_to_meta(r):
    """One row of GET /v2/generation-model/{id}/versions -> the picker-facing meta shape.
    Split out of resolve_version_meta (picker-parity-round2, 2026-07-24) so
    list_model_versions can map EVERY row through the IDENTICAL logic instead of a second
    hand-copy -- resolve_version_meta (rows[0] only) and list_model_versions (all rows)
    must never drift apart on what a 'version' means.

    - model_type: this version's architecture enum (SDXL_MODEL / DIT7B_MODEL / MULTI_LORA / ...).
    - lora_base_model_type: for a LoRA, the base-model family it REQUIRES (null for base models).
      A LoRA runs on a base iff lora_base_model_type == the base's model_type (see is_lora_compatible).
    - trigger_words: the LoRA's activation tokens (extra.triggerWords|trainedWords); '' if none.
    - the rest: the author's tuned generation preset (extra.*), for prefilling the drawer.
    - compatibility: which Advanced-panel params this model actually HONORS (e.g.
      {cfgScale:false, samplingSteps:false, negativePrompt:true, ...}, probed live
      2026-07-06 -- memory pixai-model-capability-schema). A control the model ignores
      should be hidden/disabled in the drawer, not just always shown as if it did
      something. Empty dict (not missing) when absent -- callers treat "no entry for this
      key" as "unknown, don't restrict" (fail open), same convention as capabilities above.
    - restrictions: real min/max bounds for the params above (e.g.
      {samplingSteps:{min:16,max:50}}) -- clamp the drawer's own hardcoded bounds to these
      when present instead of a one-size-fits-all guess."""
    extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
    caps = extra.get("capabilities")
    compat = extra.get("compatibility")
    restrictions = extra.get("restrictions")
    return {
        "version_id": str(r.get("id") or ""),
        "model_type": (r.get("modelType") or "").strip(),
        "lora_base_model_type": (r.get("loraBaseModelType") or "").strip() if r.get("loraBaseModelType") else "",
        "trigger_words": (extra.get("triggerWords") or extra.get("trainedWords") or "").strip(),
        "negative_prompt": (extra.get("negativePrompts") or "").strip(),
        "sampling_method": (extra.get("samplingMethod") or "").strip(),
        "sampling_steps": extra.get("samplingSteps"),
        "cfg_scale": extra.get("cfgScale"),
        "capabilities": [c for c in caps if isinstance(c, str)] if isinstance(caps, list) else [],
        "compatibility": compat if isinstance(compat, dict) else {},
        "restrictions": restrictions if isinstance(restrictions, dict) else {},
    }


def resolve_version_meta(session, model_id):
    """Resolve a model's latest generatable version AND the metadata we were throwing away.
    One GET /v2/generation-model/{id}/versions call returns everything below; the earlier
    resolve_latest_version() kept only the id. Read-only.

    Returns {version_id, model_type, lora_base_model_type, trigger_words, negative_prompt,
    sampling_method, sampling_steps, cfg_scale, capabilities, compatibility, restrictions}.
    All keys always present (empty/None when the model has no version or the field is
    absent).

    NOTE: `/generation-model/{id}/versions` returns MULTIPLE rows per model -- confirmed on
    PixAI's own site, which lists them as separate releases/iterations, all on the SAME
    fixed architecture (a LoRA is NOT multi-architecture; loraBaseModelType is consistent
    across a given LoRA's rows -- an earlier draft of this fix assumed otherwise and was
    reverted). This function still always takes rows[0] (presumed latest) -- it's the
    fast path used right after a pick, where "latest" is the right default. To offer a
    real choice among the other rows, see list_model_versions() below (picker-parity-round2,
    2026-07-24), which maps the FULL list through the same per-row shape."""
    try:
        data = _rest_get(session, "/generation-model/" + str(model_id) + "/versions")
    except PixAIError:
        return _empty_version_meta()
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    if not rows:
        return _empty_version_meta()
    return _version_row_to_meta(rows[0])


def list_model_versions(session, model_id):
    """Every published version/release row for a model/LoRA -- not just resolve_version_meta's
    rows[0]. PixAI's own site offers a version selector on model/LoRA cards; this is what
    lets our picker do the same instead of always silently resolving the latest
    (docs/AUDIT_2026-07-21.md's tracked O12/O13 remainder, closed picker-parity-round2,
    2026-07-24). Same ONE GET as resolve_version_meta (no new network surface, no N+1) --
    each row mapped through the identical _version_row_to_meta shape, so a chosen
    version_id carries real model_type/lora_base_model_type/tuned-preset data, not a
    stripped-down id-only listing.

    Adds two UI-facing fields per row: `label` (a human position tag -- 'Latest' for the
    first/presumed-newest row, matching resolve_version_meta's own long-standing rows[0]
    assumption, else 'vN' counting back from it, with the row's own createdAt date appended
    when present) and `is_latest` (True only for that first row) -- so a picker can render
    a real choice without inventing version numbers PixAI doesn't actually provide. Rows
    with no id are skipped (nothing to select). Read-only."""
    try:
        data = _rest_get(session, "/generation-model/" + str(model_id) + "/versions")
    except PixAIError:
        return []
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    out = []
    n = len(rows)
    for i, r in enumerate(rows):
        meta = _version_row_to_meta(r)
        if not meta["version_id"]:
            continue
        created = (r.get("createdAt") or "").strip()
        tag = "Latest" if i == 0 else "v{}".format(n - i)
        meta["label"] = tag + (" · " + created[:10] if created else "")
        meta["is_latest"] = (i == 0)
        out.append(meta)
    return out


def resolve_latest_version(session, model_id):
    """Resolve a model's latest generatable VERSION id (what createGenerationTask's
    `modelId` actually wants) from its MODEL id. Thin wrapper over resolve_version_meta.
    Returns '' when the model has no version. Read-only."""
    return resolve_version_meta(session, model_id)["version_id"]


def is_lora_compatible(base_model_type, lora_base_model_type):
    """True if a LoRA can run on a base model. The rule is EXACT enum equality: the LoRA's
    `loraBaseModelType` must equal the base version's `modelType` (both drawn from the same
    GenerationModelType enum). Mismatched families are rejected server-side -> a wasted
    generation / burned free card, which this gate prevents pre-submit.

    IMPORTANT: this is FAMILY-level only. Pony / Illustrious / NoobAI / vanilla-SDXL all
    collapse into SDXL_MODEL, so passing this check is NOT a quality guarantee -- only a hard
    block on architecture mismatch. Fails OPEN: if either type is unknown/empty we return True
    (never block a submit on missing data)."""
    b = (base_model_type or "").strip().upper()
    lo = (lora_base_model_type or "").strip().upper()
    if not b or not lo:
        return True
    return b == lo


def annotate_lora_compat(results, base_model_type):
    """Soft-sort + tag a LoRA search-results list by architecture compatibility with a
    selected base model (docs/AUDIT_2026-07-21.md's LoRA-arch-filter item; the root-caused
    mechanism confirmed live: a row's real architecture is `lora_base_model_type`, sourced
    from GraphQL's `latestVersion.loraBaseModelType` via model_search_market_gql -- NEVER
    the `base_model` field, which is PixAI's content CATEGORY, not architecture).

    Pure reorder + tag over ALREADY-fetched rows -- makes no network call itself, so it
    behaves identically (and is independently testable) no matter which search path
    produced `results`. `base_model_type`: the caller's already-resolved selected base
    model's `model_type` (the exact value the post-selection is_lora_compatible() gate
    already uses) -- '' / None means "no base picked yet", and `results` is returned
    completely unmodified (browsing before picking a base must not be touched).

    SOFT SORT, deliberately not a hard filter (see CHANGELOG.md for the full reasoning):
    stable-partitions rows into "compatible-or-unknown" first, "confirmed incompatible"
    last -- the SAME fail-open rule as is_lora_compatible() itself, so this can never hide
    a LoRA the picker doesn't have enough data to judge. Each row gains a `compat` tag --
    'yes' | 'no' | 'unknown' -- so the client can badge precisely: an 'unknown' row SORTS
    with the compatible group (fail-open) but is NOT badged as confirmed-compatible, which
    would overclaim data this function doesn't have."""
    bt = (base_model_type or "").strip()
    if not bt:
        return results
    tagged = []
    for row in results:
        lbt = (row.get("lora_base_model_type") or "").strip()
        if not lbt:
            compat = "unknown"
        else:
            compat = "yes" if is_lora_compatible(bt, lbt) else "no"
        row = dict(row)
        row["compat"] = compat
        tagged.append(row)
    head = [r for r in tagged if r["compat"] != "no"]
    tail = [r for r in tagged if r["compat"] == "no"]
    return head + tail


def run_list_models(args):
    """CLI: search PixAI models and print name / type / generatable version id."""
    session = _make_session(getattr(args, "token", None))
    kw = getattr(args, "list_models", "") or ""
    results = model_search_gql(session, kw, limit=getattr(args, "max", 0) or 25)
    if not results:
        print("No models found for '{}'.".format(kw))
        return
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):                       # Windows consoles are often cp1252
        return t.encode(enc, "replace").decode(enc, "replace")
    print("{:<40} {:<14} version id (use as --model)".format("model", "type"))
    for m in results:
        tag = " [NSFW]" if m["is_nsfw"] else ""
        print("{:<40} {:<14} {}{}".format(
            _safe(m["title"][:40]), m["type"][:14], m["version_id"], tag))


def model_name_gql(session, model_version_id, _cache={}):
    """GET getGenerationModelByVersionId; result cached by ID (few unique models)."""
    if not model_version_id:
        return ""
    mid = str(model_version_id)
    if mid in _cache:
        return _cache[mid]
    if not MODEL_DETAIL_HASH:
        _cache[mid] = mid
        return mid
    params = {
        "operation": "getGenerationModelByVersionId",
        "u3t": U3T,
        "operationName": "getGenerationModelByVersionId",
        "variables": json.dumps({"id": mid}, separators=(",", ":")),
        "extensions": json.dumps(
            {"clientLibrary": CLIENT_LIBRARY,
             "persistedQuery": {"version": 1, "sha256Hash": MODEL_DETAIL_HASH}},
            separators=(",", ":")),
    }
    try:
        r = session.get(API_URL, params=params, timeout=60)
        r.raise_for_status()
        mv = (r.json().get("data") or {}).get("generationModelVersion") or {}
        title = (mv.get("model") or {}).get("title", "")
        version = mv.get("name", "")
        name = "{} {}".format(title, version).strip() if title else mid
    except Exception:
        name = mid
    _cache[mid] = name
    return name


def extract_full_meta(task):
    """Pull the extended fields out of a getTaskById task dict."""
    if not task:
        return {}
    params = task.get("parameters") or {}
    outputs = task.get("outputs") or {}
    detail = outputs.get("detailParameters") or {}
    extra = params.get("extra") or {}
    # negativePrompts may live under a few keys depending on PixAI's flow; many
    # newer "structured prompt" tasks have none at all.
    neg = (params.get("negativePrompts") or detail.get("negativePrompts")
           or extra.get("negativePrompts") or params.get("negativePrompt") or "")
    clip = detail.get("clipSkip", params.get("clipSkip", ""))
    # A taskKind=chat task -- an instruct Edit, or a hand/face Fix -- keeps its model inside
    # the `chat` block, and build_chat_edit_parameters sets NO top-level modelId at all, so
    # without this fallback a chat task's Model rendered as an em-dash on the detail page.
    # NOTHING ELSE about a chat task is recoverable here, deliberately: it has no seed, no
    # sampler, no steps and no cfg scale (outputs.detailParameters is absent entirely), and
    # those stay empty rather than borrowing a plausible-looking number the task never had.
    chat = params.get("chat") if isinstance(params.get("chat"), dict) else {}
    model_id = str(params.get("modelId") or chat.get("modelId") or "")
    # PixAI's two CHAT models are the ones this app already names (EDIT_MODELS), so the label
    # resolves locally: a Fix's Model reads "Reference Pro" rather than a 19-digit id, with no
    # extra network round trip. Callers that also run model_name_gql still overwrite it.
    chat_label = (edit_model_by_id(model_id) or {}).get("label", "") if chat else ""
    return {
        "prompt_full":    params.get("prompts", ""),
        "natural_prompt": extra.get("naturalPrompts", ""),
        "seed":           str(outputs.get("seed") or ""),
        "steps":          str(detail.get("steps") or ""),
        "sampler":        detail.get("sampler", ""),
        "cfg_scale":      str(detail.get("cfg_scale") or ""),
        "model_id":       model_id,
        "model_name":     chat_label,  # otherwise filled in by caller after model_name_gql
        "loras":          "",  # filled in by caller via resolve_loras()
        "negative_prompt": neg,
        "clip_skip":      str(clip) if clip != "" else "",
        # getTaskById returns paidCredit top-level even for historical tasks (verified
        # against a real captured task, 2026-07-04) -- so full-meta/backfill passes
        # recover spend history, not just fresh generations.
        "paid_credit":    _paid_credit_str(task),
    }


def resolve_loras(session, task):
    """Read parameters.lora ({loraVersionId: weight}) from a getTaskById task and
    return a readable "Name:0.7, Name2:0.5" string, resolving each LoRA id to a
    name via getGenerationModelByVersionId (cached). Unresolvable ids keep the
    number. Empty string if the task used no LoRAs."""
    params = (task or {}).get("parameters") or {}
    lora = params.get("lora") or {}
    if not isinstance(lora, dict) or not lora:
        return ""
    parts = []
    for vid, weight in lora.items():
        name = model_name_gql(session, vid)
        if not name or str(name) == str(vid) or str(name).isdigit():
            name = "lora {}".format(vid)
        try:
            w = "{:g}".format(float(weight))
        except (TypeError, ValueError):
            w = str(weight)
        parts.append("{}:{}".format(name, w))
    return ", ".join(parts)


def _merge_full(fm, kr):
    """Merge full-meta fields: prefer fresh fm, fall back to known-row kr."""
    return {f: (fm.get(f) or kr.get(f, "")) for f in _FULL_META_FIELDS}


def carry_local_fields(row, known):
    """Merge a freshly-rebuilt download row OVER its existing catalog row so LOCAL
    curation survives a re-pull. A download pass only knows API/file fields
    (task_id, filename, url, prompt, seed, model, ...); WITHOUT this merge, every
    re-processed media_id has its locally-owned fields -- collections, rating,
    art_tags, is_published, title, aes_score, blurhash, and any future local
    column -- silently blanked by the full-row upsert. This was a real data-loss
    bug: a --update/--full-meta pass wiped collection tags.

    `known` maps media_id -> the existing catalog row (a pre-download snapshot).
    An empty fresh value never clobbers an existing one, so a missing download
    keeps the old filename. New media_ids (absent from `known`) pass through
    unchanged. Applied at save time, it covers every row-builder path at once."""
    base = dict(known.get(row.get("media_id", ""), {}))
    for k, v in row.items():
        if v not in ("", None):
            base[k] = v
        else:
            base.setdefault(k, "")
    return base


def cmd_convert_existing(args, out):
    """Convert all .webp files in the backup tree to the target format in-place."""
    target = (args.convert or "png").lower()
    out_ext = ".jpg" if target in ("jpg", "jpeg") else ".png"

    webp_files = sorted(p for p in out.rglob("*.webp")
                        if not p.name.endswith(".part") and p.stat().st_size > 0)
    if not webp_files:
        print("No .webp files found under {}.".format(out))
        return

    print("Found {} .webp file(s); converting to {}.".format(len(webp_files), target))
    if args.keep_webp:
        print("--keep-webp: originals kept alongside converted files.")

    if args.dry_run:
        for p in webp_files[:10]:
            print("  {} -> {}".format(p.name, p.with_suffix(out_ext).name))
        if len(webp_files) > 10:
            print("  ... and {} more".format(len(webp_files) - 10))
        print("\nDry run -- nothing converted. Re-run without --dry-run to apply.")
        return

    ok = failed = 0
    total = len(webp_files)
    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Converting with {} parallel workers.".format(workers))
    _prog = getattr(args, "progress", None)
    pillow_missing = False
    for p, res in _parallel_map(
            webp_files,
            lambda f: convert_image(f, target, args.jpeg_quality, args.jpeg_bg,
                                    keep_original=args.keep_webp),
            workers, _prog):
        note = res[1] if res else "error"
        if note == "pillow-missing":
            pillow_missing = True
            break
        if note == "ok":
            ok += 1
        else:
            print("  FAILED {}: {}".format(p.name, note))
            failed += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  {:,}/{:,}  ok {:,}  failed {:,}  ".format(
                ok + failed, total, ok, failed))
            sys.stdout.flush()
    if pillow_missing:
        raise PixAIError("--convert-existing needs Pillow:  pip install pillow")

    print("\nConverted: {}, failed: {}.".format(ok, failed))
    if failed:
        print("Failed files left as .webp -- re-run to retry.")


# ---------------------------------------------------------------------------
# Duplicate audit + dedup (filesystem-truth; independent of catalog.db)
# ---------------------------------------------------------------------------
# Keeper priority when the same image lives in several buckets: lower wins
# (i.e. we KEEP the most-organized copy and remove the rest). This reinforces
# --organize's layout instead of fighting it. "batches" ranks first as LEGACY
# ONLY -- no reachable code path creates a batches/ folder anymore (the old
# live-organize-into-batches mode lived behind an `organize_adv_live` runtime
# flag that no CLI argument has ever set since; --organize's real, current
# output is month folders only, and its own run tidies up leftover legacy
# batches/ dirs -- see below). A batches/ folder found here is pre-existing
# data from an older run, still worth preferring as a keeper if one exists.
_BUCKET_PRIORITY = {"batches": 0, "month": 1, "images": 2, "other": 3}


def _bucket_of(rel_path):
    """Classify a path (relative to out_dir) into a top-level bucket name."""
    top = str(rel_path).replace("\\", "/").split("/")[0]
    if top == "images":
        return "images"
    if top == "batches":
        return "batches"
    if top == "unknown-date":
        return "month"
    if len(top) == 7 and top[4] == "-" and top[:4].isdigit():
        return "month"
    return "other"


def _scan_media_files(out_dir):
    """One walk of the tree. Yields (path, rel, bucket, media_id) for every image
    file outside gallery/, _duplicates/, and _deleted/. Single source of truth for
    the audit (and, via verify_quarantine, the dedup-verify pass).

    _deleted/ exclusion is B11 (audit 2026-07-21): without it, a locally-purged
    image is a valid audit hit -- reported back as a live Class A duplicate of its
    own quarantined self, and (via verify_quarantine's survivor index) potentially
    treated as the "surviving keeper" a _duplicates/ copy is compared against."""
    gallery_dir = out_dir / "gallery"
    quarantine_dir = out_dir / "_duplicates"
    deleted_dir = out_dir / DELETED_DIRNAME
    for p in out_dir.rglob("*"):
        if p.suffix.lower() not in _IMAGE_EXTS or not p.is_file():
            continue
        if p.name.endswith(".part"):
            continue
        if (_is_under_dir(p, gallery_dir) or _is_under_dir(p, quarantine_dir)
                or _is_under_dir(p, deleted_dir)):
            continue
        rel = p.relative_to(out_dir)
        yield p, rel, _bucket_of(rel), media_id_of(p)


def _is_under_dir(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def audit_collection(out_dir, content=True, progress=None):
    """Filesystem-truth duplicate audit. Returns a dict:
        per_bucket       : {bucket: count}
        class_a          : [ {media_id, files:[(rel,bucket,size)], keeper, losers} ]
        class_b          : [ {sha, files:[(rel,bucket,size,media_id)], keeper, losers} ]
        totals           : counts + reclaimable bytes
    Class A = same media_id in >1 location (no hashing needed).
    Class B = byte-identical content under DIFFERENT media_ids (size-bucketed hash).
    """
    by_mid = defaultdict(list)      # mid -> [(path, rel, bucket, size)]
    by_size = defaultdict(list)     # size -> [(path, rel, bucket, mid)]
    per_bucket = Counter()
    all_files = list(_scan_media_files(out_dir))
    total = len(all_files)
    for i, (p, rel, bucket, mid) in enumerate(all_files):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0:
            # A 0-byte file (an interrupted download, same failure mode as invariant 3's
            # resume-index bug) must never enter by_mid/by_size: with bucket priority as
            # the ONLY keeper-selection signal, an empty file in the "batches" bucket
            # outranks a real image in "images" and gets chosen as the survivor. Under
            # plain --dedup that is recoverable (the auto-verify pass below flags it,
            # "REVIEW NEEDED"); under --dedup --apply --dedup-delete there is no verify
            # step at all, so it silently hard-deletes the only real copy. Excluding it
            # here means it can never become a keeper OR a loser -- it simply isn't part
            # of any duplicate group, which is also correct: an empty file isn't a
            # duplicate of anything.
            continue
        per_bucket[bucket] += 1
        by_mid[mid].append((p, rel, bucket, size))
        by_size[size].append((p, rel, bucket, mid))
        if progress and (i % 500 == 0 or i + 1 == total):
            progress(i + 1, total, 0)

    def _keeper(items, key_bucket):
        # items: list of tuples; key_bucket(item) -> bucket name. Prefer organized,
        # then shortest path (stable), so the canonical copy is deterministic.
        # A zero-byte item (it[3] is size on the by_mid tuple shape) can never win --
        # False < True, so "is empty" sorts before every real bucket/path comparison.
        # Defense in depth: the loop above already excludes zero-byte files from ever
        # reaching `items` at all, so this branch should be unreachable in practice.
        return min(items, key=lambda it: (it[3] == 0,
                                          _BUCKET_PRIORITY.get(key_bucket(it), 9),
                                          len(str(it[1]))))

    # ---- Class A: same media_id across >1 distinct bucket -------------------
    class_a = []
    for mid, items in by_mid.items():
        buckets = {b for (_, _, b, _) in items}
        if len(items) > 1 and len(buckets) > 1:
            keeper = _keeper(items, lambda it: it[2])
            losers = [it for it in items if it[0] != keeper[0]]
            class_a.append({"media_id": mid, "files": items,
                            "keeper": keeper, "losers": losers})

    # ---- Class B: identical bytes, different media_id -----------------------
    class_b = []
    if content:
        # Only hash within same-size groups that span >1 distinct media_id.
        candidates = [(s, grp) for s, grp in by_size.items()
                      if len({m for (_, _, _, m) in grp}) > 1]
        hashed = 0
        n_to_hash = sum(len(grp) for _, grp in candidates)
        by_sha = defaultdict(list)
        for s, grp in candidates:
            for (p, rel, bucket, mid) in grp:
                sha = _file_sha(p)
                hashed += 1
                if sha:
                    by_sha[sha].append((p, rel, bucket, s, mid))
                if progress and (hashed % 200 == 0 or hashed == n_to_hash):
                    progress(hashed, max(n_to_hash, 1), 1)
        for sha, items in by_sha.items():
            mids = {m for (_, _, _, _, m) in items}
            if len(items) > 1 and len(mids) > 1:
                keeper = _keeper(items, lambda it: it[2])
                losers = [it for it in items if it[0] != keeper[0]]
                class_b.append({"sha": sha, "files": items,
                                "keeper": keeper, "losers": losers})

    reclaim_a = sum(sz for g in class_a for (_, _, _, sz) in g["losers"])
    reclaim_b = sum(it[3] for g in class_b for it in g["losers"])
    return {
        "per_bucket": dict(per_bucket),
        "class_a": class_a,
        "class_b": class_b,
        "totals": {
            "files": total,
            "class_a_groups": len(class_a),
            "class_a_redundant": sum(len(g["losers"]) for g in class_a),
            "class_b_groups": len(class_b),
            "class_b_redundant": sum(len(g["losers"]) for g in class_b),
            "reclaimable_bytes": reclaim_a + reclaim_b,
        },
    }


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "{:.1f} {}".format(n, unit)
        n /= 1024


def cmd_audit(args, out):
    """Read-only duplicate audit. Prints a summary and writes audit_report.csv.
    Touches nothing on disk. Independent of catalog.db."""
    content = not getattr(args, "no_content", False)
    print("Auditing {} (content hashing: {})...".format(
        out, "on" if content else "off"))
    _prog = getattr(args, "progress", None)
    rep = audit_collection(out, content=content, progress=_prog)
    t = rep["totals"]

    print("\nFiles per bucket:")
    for b, c in sorted(rep["per_bucket"].items(), key=lambda kv: -kv[1]):
        print("  {:<10} {:,}".format(b, c))

    print("\nClass A  - same media_id in >1 folder : {:,} groups, {:,} redundant files"
          .format(t["class_a_groups"], t["class_a_redundant"]))
    print("Class B  - identical bytes, diff id   : {:,} groups, {:,} redundant files"
          .format(t["class_b_groups"], t["class_b_redundant"]))
    print("Reclaimable if deduped                : {}".format(
        _fmt_bytes(t["reclaimable_bytes"])))

    # Write detailed CSV
    report_path = out / "audit_report.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["class", "group_key", "role", "bucket", "media_id", "size", "path"])
        for g in rep["class_a"]:
            kp, kr, kb, ksz = g["keeper"]
            w.writerow(["A", g["media_id"], "keep", kb, g["media_id"], ksz, str(kr)])
            for (_, rel, b, sz) in g["losers"]:
                w.writerow(["A", g["media_id"], "remove", b, g["media_id"], sz, str(rel)])
        for g in rep["class_b"]:
            kp, kr, kb, ksz, kmid = g["keeper"]
            w.writerow(["B", g["sha"][:12], "keep", kb, kmid, ksz, str(kr)])
            for (_, rel, b, sz, mid) in g["losers"]:
                w.writerow(["B", g["sha"][:12], "remove", b, mid, sz, str(rel)])
    print("\nDetailed report -> {}".format(report_path.relative_to(out.parent)
                                            if out.parent else report_path))
    print("Run --dedup to act on this (quarantine by default; nothing deleted yet).")
    return rep


def cmd_dedup(args, out, db_path):
    """Act on the audit: move redundant copies to _duplicates/ (default) or delete
    them (--dedup-delete). Keeps the most-organized copy. Dry-run by default.
    Reconciles catalog.db with what's left on disk afterward."""
    # Dedup is filesystem-truth: it does not need a catalog to run. Reconcile is
    # a bonus, applied only if a catalog exists.
    try:
        db_path = _ensure_db(out)
        have_catalog = True
    except PixAIError:
        have_catalog = False
    content = not getattr(args, "no_content", False)
    delete = getattr(args, "dedup_delete", False)
    apply = getattr(args, "apply", False)  # default is dry-run unless --apply

    rep = audit_collection(out, content=content, progress=getattr(args, "progress", None))
    losers = []  # (rel_path, abs_path)
    for g in rep["class_a"]:
        for (p, rel, b, sz) in g["losers"]:
            losers.append((rel, p))
    for g in rep["class_b"]:
        for (p, rel, b, sz, mid) in g["losers"]:
            losers.append((rel, p))

    action = "DELETE" if delete else "quarantine to _duplicates/"
    print("\nDedup plan: {:,} redundant files to {} ({})".format(
        len(losers), action, _fmt_bytes(rep["totals"]["reclaimable_bytes"])))
    for rel, _ in losers[:8]:
        print("  {}".format(rel))
    if len(losers) > 8:
        print("  ... and {:,} more".format(len(losers) - 8))

    if not apply:
        print("\nDry run -- nothing changed. Re-run with --apply to perform it.")
        return rep

    quarantine_root = out / "_duplicates"
    moved = removed = failed = 0
    _prog = getattr(args, "progress", None)
    for i, (rel, p) in enumerate(losers):
        try:
            if delete:
                p.unlink()
                removed += 1
            else:
                dest = quarantine_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest = dest.with_name(dest.stem + "_dup" + dest.suffix)
                p.replace(dest)
                moved += 1
        except OSError as e:
            print("  failed {} ({})".format(rel, e))
            failed += 1
        if _prog:
            _prog(i + 1, len(losers), 0)

    if delete:
        print("\nDeleted {:,} files, {:,} failed.".format(removed, failed))
    else:
        print("\nQuarantined {:,} files to {}, {:,} failed.".format(
            moved, quarantine_root.relative_to(out.parent) if out.parent else quarantine_root,
            failed))

    if moved or removed:
        try:      # The Great Sweep: cumulative pieces removed via --dedup
            from moonglade_gallery import telem_bump
            telem_bump("culled", moved + removed, out_dir=out)
        except Exception:
            pass

    if have_catalog:
        n = reconcile_catalog_with_disk(out, db_path)
        print("Reconciled catalog: updated {:,} filename/batch entries to match disk.".format(n))

    # Auto-verify after quarantining. Dedup chose losers by media_id WITHOUT
    # comparing bytes, so this is the only step that confirms each quarantined
    # file truly matches a surviving keeper. Never auto-deletes -- the human does.
    if not delete and moved:
        print("\n--- Verifying the quarantine (confirming every moved file is "
              "redundant) ---")
        vr = verify_quarantine(out, progress=getattr(args, "progress", None))
        ok = vr["safe"] + vr["meta_only"]
        print("Verify: {:,} confirmed safe ({:,} byte-identical + {:,} metadata-only), "
              "{:,} differ, {:,} orphan.".format(
                  ok, vr["safe"], vr["meta_only"], len(vr["differs"]), len(vr["orphan"])))
        if vr["differs"] or vr["orphan"]:
            print("REVIEW NEEDED before deleting _duplicates/ -- run --verify-dupes "
                  "to write verify_report.csv with the flagged items.")
        else:
            print("All quarantined files confirmed redundant -- _duplicates/ is safe "
                  "to delete to reclaim the space.")
    return rep


def verify_quarantine(out_dir, restore_orphans=False, progress=None):
    """Final-pass safety check on _duplicates/ BEFORE you delete it.

    For every quarantined file, find the surviving keeper with the same media_id
    (outside _duplicates/) and compare bytes. Classifies each as:
      * safe    - a keeper exists AND bytes are identical -> truly redundant
      * differs - a keeper exists but bytes DIFFER -> same media_id, different
                  content (a naming collision the sort/backfill missed) -> REVIEW
      * orphan  - no surviving keeper at all -> quarantining it lost the only copy
    Optionally restores orphans back to images/. Returns a result dict.
    """
    quarantine_root = out_dir / "_duplicates"
    if not quarantine_root.exists():
        return {"safe": 0, "differs": [], "orphan": [], "total": 0}

    files = [p for p in quarantine_root.rglob("*")
             if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    # Index surviving keepers (everything outside _duplicates/ and gallery/) once,
    # in a single walk, so we don't rglob the whole tree per quarantined file.
    survivors = defaultdict(list)
    for p, rel, bucket, mid in _scan_media_files(out_dir):
        survivors[mid].append(p)

    safe = 0
    meta_only = 0  # bytes differ but pixels identical (e.g. embedded PNG metadata)
    differs = []   # (quarantined_path, keeper_path) - genuinely different pixels
    orphan = []    # quarantined_path
    total = len(files)
    for i, q in enumerate(files):
        keepers = survivors.get(media_id_of(q), [])
        if not keepers:
            orphan.append(q)
        elif _same_bytes(q, keepers[0]):
            safe += 1
        else:
            # Bytes differ. Fall back to a pixel compare: identical pixels mean the
            # difference is just container/metadata (the keeper has prompt text
            # embedded), so it's still safe to delete the quarantined copy.
            px = _same_pixels(q, keepers[0])
            if px is True:
                meta_only += 1
            else:
                differs.append((q, keepers[0]))
        if progress and (i % 200 == 0 or i + 1 == total):
            progress(i + 1, total, 0)

    restored = 0
    if restore_orphans and orphan:
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for q in orphan:
            dest = images_dir / q.name
            try:
                q.replace(dest)
                restored += 1
            except OSError as e:
                print("  restore failed {} ({})".format(q.name, e))

    return {"safe": safe, "meta_only": meta_only, "differs": differs,
            "orphan": orphan, "total": total, "restored": restored}


def cmd_verify_dupes(args, out):
    """Verify the _duplicates/ quarantine is safe to delete. Read-only unless
    --restore-orphans is passed."""
    restore = getattr(args, "restore_orphans", False)
    print("Verifying quarantine in {}/_duplicates ...".format(out))
    res = verify_quarantine(out, restore_orphans=restore,
                            progress=getattr(args, "progress", None))
    if res["total"] == 0:
        print("No _duplicates/ folder (nothing quarantined yet).")
        return res

    print("\nQuarantined files checked : {:,}".format(res["total"]))
    print("  safe - byte-identical keeper exists       : {:,}".format(res["safe"]))
    print("  safe - pixels identical (metadata-only)   : {:,}".format(res["meta_only"]))
    print("  DIFFERS - same id, DIFFERENT pixels       : {:,}".format(len(res["differs"])))
    print("  ORPHAN  - no surviving keeper             : {:,}".format(len(res["orphan"])))

    if res["differs"] or res["orphan"]:
        report = out / "verify_report.csv"
        with open(report, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["status", "quarantined_file", "surviving_keeper"])
            for q, k in res["differs"]:
                w.writerow(["differs", str(q.relative_to(out)), str(k.relative_to(out))])
            for q in res["orphan"]:
                w.writerow(["orphan", str(q.relative_to(out)), ""])
        print("\nFlagged items written to {}".format(report.relative_to(out.parent)
                                                     if out.parent else report))

    if res.get("restored"):
        print("Restored {:,} orphaned files to images/.".format(res["restored"]))

    if not res["differs"] and not res["orphan"]:
        print("\nAll clear: every quarantined file is byte-identical to a surviving "
              "copy. Safe to delete _duplicates/.")
    else:
        print("\nDo NOT blanket-delete yet -- review the flagged items above first.")
        if res["orphan"] and not restore:
            print("Re-run with --restore-orphans to move orphans back to images/.")
    return res


def reconcile_catalog_with_disk(out_dir, db_path):
    """After files move/disappear, point each catalog row's filename+batch at the
    surviving on-disk file for that media_id. Rows whose file is gone keep their
    last-known filename but are left intact (the image may be re-downloadable)."""
    rows = load_catalog(db_path)
    updated = 0
    for r in rows:
        mid = r.get("media_id")
        if not mid:
            continue
        matches = find_files_for_media_id(out_dir, mid)
        if not matches:
            continue
        survivor = matches[0]
        rel = survivor.relative_to(out_dir)
        bucket = _bucket_of(rel)
        new_batch = rel.parts[1] if bucket == "batches" and len(rel.parts) > 2 else (
            "" if bucket != "batches" else r.get("batch", ""))
        if r.get("filename") != survivor.name or r.get("batch", "") != new_batch:
            r["filename"] = survivor.name
            r["batch"] = new_batch
            updated += 1
    if updated:
        save_catalog(db_path, rows)
    return updated


ORGANIZE_MANIFEST = "organize_manifest.csv"


def cmd_organize(args, out, img_dir, db_path):
    """Normalize PixAI images into YYYY-MM/ month folders with descriptive,
    readable filenames (prompt_taskid_mediaid) -- one flat scheme, NO batch
    subfolders. Scans the WHOLE backup (flat images/, existing month folders, and
    any legacy batches/), so a single run brings everything to the same layout for
    easy Explorer browsing.

    Safety: writes a reversible move-manifest (organize_manifest.csv: old->new) so
    every move can be undone with --undo-organize. Idempotent (files already at
    their target are skipped), byte-safe (never overwrites a differing file), and
    dry-runnable. Metadata embedding (--embed-metadata) and conversion (--convert)
    are opt-in. Imported (source='local') files, videos, and _deleted/ quarantine
    are left untouched (B11, audit 2026-07-21: this is the only one of B11's five
    quarantine-blind walks that actually MOVES files -- a stale _deleted/ remnant
    sharing a media_id with the live catalogued copy collided with it in the move
    plan, either hard-deleting one outright as a spurious "redundant" duplicate or
    resurrecting the quarantined copy into the organized tree in its place)."""
    db_path = _ensure_db(out)
    meta_by_mid = {}
    for row in load_catalog(db_path):
        mid = row.get("media_id")
        if mid:
            meta_by_mid[mid] = row

    skip_dirs = (out / "gallery", out / "_duplicates", out / "videos", out / "imported",
                 out / DELETED_DIRNAME)

    def _target(mid, row, ext):
        month = (row.get("created_at") or "")[:7] or "unknown-date"
        stem = build_stem_name(row.get("prompt_preview", ""), row.get("task_id", ""),
                               mid, args.name_length, args.name_sep)
        return out / month / (stem + ext)

    # Sources: every PixAI image on disk (catalog media), wherever it currently is.
    plan, in_place = [], 0
    for p in out.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS:
            continue
        if p.name.endswith(".part") or p.name.startswith("_"):
            continue
        if any(_under(p, d) for d in skip_dirs):
            continue
        row = meta_by_mid.get(media_id_of(p))
        if not row or (row.get("source") or "") == "local":
            continue                       # unknown file or user import: leave it
        dst = _target(media_id_of(p), row, p.suffix.lower())
        if p.resolve() == dst.resolve():
            in_place += 1
            continue
        plan.append((p, dst, media_id_of(p), row))

    print("Organize plan: {} file(s) -> YYYY-MM/ with descriptive names; "
          "{} already in place.".format(len(plan), in_place))
    for src, dst, mid, row in plan[:6]:
        print("  {}  ->  {}".format(src.relative_to(out), dst.relative_to(out)))
    if len(plan) > 6:
        print("  ... and {} more".format(len(plan) - 6))
    if args.convert:
        print("Will also convert to {}.".format(args.convert))
    if getattr(args, "embed_metadata", False):
        print("Will embed prompt metadata into PNG/JPEG (WebP skipped).")

    if args.dry_run:
        print("\nDry run -- nothing moved. Re-run without --dry-run to apply.")
        return
    if not plan:
        print("Nothing to do -- everything already organized.")
        return

    manifest_path = out / ORGANIZE_MANIFEST
    mf_new = not manifest_path.exists()
    mf = open(manifest_path, "a", newline="", encoding="utf-8")
    mw = csv.writer(mf)
    if mf_new:
        mw.writerow(["old_path", "new_path", "ts"])
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    moved = converted = embedded = skipped = deduped = 0
    catalog_updates = {}                   # media_id -> new basename
    month_index = defaultdict(list)
    _prog = getattr(args, "progress", None)

    for n, (src, dst, mid, row) in enumerate(plan):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.resolve() != src.resolve():
            # Target already holds this media. Byte-identical -> drop the redundant
            # source (this is the INVARIANT-7 protection). Differ -> keep both.
            if _same_bytes(src, dst):
                try:
                    src.unlink(); deduped += 1
                except OSError:
                    pass
            else:
                print("  KEPT both (differ): {} vs {}".format(src.name, dst.relative_to(out)))
            skipped += 1
            final = dst
        else:
            try:
                src.replace(dst)
                mw.writerow([str(src.relative_to(out)).replace("\\", "/"),
                             str(dst.relative_to(out)).replace("\\", "/"), ts])
                mf.flush()
                moved += 1
                final = dst
                catalog_updates[mid] = final.name
            except OSError as e:
                print("  move failed {} ({})".format(src.name, e))
                continue
        if args.convert:
            final, note = convert_image(final, args.convert, args.jpeg_quality,
                                        args.jpeg_bg, keep_original=args.keep_webp)
            if note == "pillow-missing":
                raise PixAIError("--convert needs Pillow:  pip install pillow")
            if note == "ok":
                converted += 1
            catalog_updates[mid] = final.name
        if getattr(args, "embed_metadata", False):
            note = embed_metadata(final, {
                "prompt": row.get("prompt_preview", ""), "task_id": row.get("task_id", ""),
                "media_id": mid, "width": row.get("width", ""), "height": row.get("height", ""),
                "created_at": row.get("created_at", ""), "status": row.get("status", ""),
                "source": "PixAI"})
            if note == "ok":
                embedded += 1
        month_index[final.parent.name].append({
            "filename": final.name, "media_id": mid, "task_id": row.get("task_id", ""),
            "prompt_preview": row.get("prompt_preview", ""), "width": row.get("width", ""),
            "height": row.get("height", ""), "created_at": row.get("created_at", ""),
            "status": row.get("status", "")})

        if _prog:
            _prog(n + 1, len(plan), 0)
        else:
            sys.stdout.write("\r  {:,}/{:,}  moved {:,}  ".format(n + 1, len(plan), moved))
            sys.stdout.flush()
    mf.close()
    if not _prog:
        print()

    for month, entries in month_index.items():
        idx_path = out / month / "_index.csv"
        new = not idx_path.exists()
        with open(idx_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["filename", "media_id", "task_id",
                                              "prompt_preview", "width", "height",
                                              "created_at", "status"])
            if new:
                w.writeheader()
            for e in entries:
                w.writerow(e)

    # Tidy up now-empty legacy batches/ folders (drop their _prompt.txt first).
    batches_root = out / "batches"
    if batches_root.exists():
        for f in batches_root.rglob("_prompt.txt"):
            try:
                f.unlink()
            except OSError:
                pass
        for d in sorted([p for p in batches_root.rglob("*") if p.is_dir()],
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            batches_root.rmdir()
        except OSError:
            pass

    if catalog_updates:
        rows = load_catalog(db_path)
        for r in rows:
            if r["media_id"] in catalog_updates:
                r["filename"] = catalog_updates[r["media_id"]]
                r["batch"] = ""            # batches are gone
        save_catalog(db_path, rows)
        print("Updated {:,} catalog entries.".format(len(catalog_updates)))

    print("\nOrganized: moved {:,}, already-in-place {:,}.".format(moved, in_place))
    if deduped:
        print("Removed {:,} redundant byte-identical copies.".format(deduped))
    if args.convert:
        print("Converted to {}: {:,}.".format(args.convert, converted))
    if embedded:
        print("Embedded metadata into {:,} images.".format(embedded))
    print("Reversible manifest: {}  (run --undo-organize to revert)".format(manifest_path))
    try:      # Keeper of Order: a real (non-dry-run) organize completed
        from moonglade_gallery import telem_bump
        telem_bump("organize_runs", out_dir=out)
    except Exception:
        pass


def cmd_undo_organize(args, out):
    """Reverse the moves recorded in organize_manifest.csv (newest run first):
    each new_path is moved back to its old_path. Safe (skips already-reverted),
    then clears the manifest. Lets a re-normalize be undone if you don't like it."""
    db_path = _ensure_db(out)
    manifest_path = out / ORGANIZE_MANIFEST
    if not manifest_path.exists():
        print("No organize manifest found ({}); nothing to undo.".format(manifest_path))
        return
    with open(manifest_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("new_path")]
    print("Reverting {} recorded move(s)...".format(len(rows)))
    if getattr(args, "dry_run", False):
        for r in rows[:8]:
            print("  {}  ->  {}".format(r["new_path"], r["old_path"]))
        print("\nDry run -- nothing moved.")
        return
    reverted = miss = 0
    for r in reversed(rows):               # undo newest first
        new_p, old_p = out / r["new_path"], out / r["old_path"]
        if old_p.exists() and not new_p.exists():
            continue                       # already reverted
        if not new_p.exists():
            miss += 1
            continue
        old_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            new_p.replace(old_p)
            reverted += 1
        except OSError as e:
            print("  revert failed {} ({})".format(new_p, e))
    # The gallery resolves files by media id (find_files_for_media_id matches both
    # naming layouts), so restored files still resolve without rewriting the
    # catalog. Clear the manifest now that it's been applied.
    manifest_path.unlink()
    print("Reverted {} file(s); {} already gone. Manifest cleared.".format(reverted, miss))


# ---------------------------------------------------------------------------
# Callable API (used by the GUI; also called by main() for the CLI)
# ---------------------------------------------------------------------------
def _make_session(token_val):
    """Validate config, load token, return a configured requests.Session.
    Re-reads config.json at call time so the GUI works even when the module
    was imported before the working directory was set correctly."""
    global PERSISTED_QUERY_HASH, U3T, USER_ID, TASK_DETAIL_HASH, MODEL_DETAIL_HASH
    global DELETE_TASK_HASH
    fresh = _load_config()
    if fresh:
        PERSISTED_QUERY_HASH = fresh.get("PERSISTED_QUERY_HASH", "") or PERSISTED_QUERY_HASH
        U3T = fresh.get("U3T", "") or U3T
        USER_ID = fresh.get("USER_ID", "") or USER_ID
        TASK_DETAIL_HASH = fresh.get("TASK_DETAIL_HASH", "") or TASK_DETAIL_HASH
        MODEL_DETAIL_HASH = fresh.get("MODEL_DETAIL_HASH", "") or MODEL_DETAIL_HASH
        DELETE_TASK_HASH = fresh.get("DELETE_TASK_HASH", "") or DELETE_TASK_HASH
    have_api_key = bool((fresh or {}).get("PIXAI_API_KEY") or _cfg.get("PIXAI_API_KEY"))
    # Persisted hashes now ship with defaults, so the API-key path needs nothing but
    # the key (USER_ID is auto-resolved below). The legacy browser-JWT path still
    # wants a U3T alongside its short-lived token.
    if not have_api_key and not U3T:
        raise PixAIError(
            "No API key found. Add PIXAI_API_KEY to config.json (recommended -- then "
            "nothing else is required), or use the legacy token path (U3T + token.txt).\n"
            "Copy config.example.json to config.json. See the Setup wiki page: "
            "https://github.com/Nelnamara/moonglade-athenaeum/wiki/Setup")
    token = load_token(token_val)
    session = requests.Session()
    session.headers.update({
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/json",
        "User-Agent": "pixai-personal-backup/1.0",
        "apollo-require-preflight": "true",
        "x-apollo-operation-name": OPERATION_NAME,
    })
    # Auto-resolve the user id from the API key when it isn't pinned in config.
    if not USER_ID:
        if have_api_key:
            try:
                USER_ID = resolve_user_id(session)
                vlog("resolved USER_ID from API key: {}".format(USER_ID))
            except Exception as e:
                raise PixAIError(
                    "Could not auto-resolve your user id from the API key "
                    "(me query failed: {}).\nAdd USER_ID to config.json as a fallback."
                    .format(e))
        else:
            raise PixAIError("config.json needs USER_ID (or set PIXAI_API_KEY to "
                             "auto-resolve it).")
    return session


def run_probe(args):
    """Test API connection and resolve full-res media URL for the newest task."""
    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))
    print("Fetching newest page...\n")
    conn = find_connection(gql(session, page_variables(args.page_size)))
    if not conn:
        print("No connection found.")
        return
    edges = conn.get("edges", [])
    pi = conn.get("pageInfo", {})
    print("OK -- {} items. hasPreviousPage={}".format(
        len(edges), pi.get("hasPreviousPage")))
    node = edges[0].get("node", edges[0]) if edges else {}
    meta = extract_meta(node)
    mids = media_ids_for(node)
    print("First task: id={} media_ids={}".format(meta["task_id"], mids))
    print("Prompt preview:", meta["prompt_preview"][:80])
    if mids:
        url, info = resolve_media(session, mids[0])
        print("\nResolved full-res URL:", url or "(none!)")
        print("Dimensions: {}x{}".format(info.get("width"), info.get("height")))
        if url:
            print("\nLooks right? Run a download to back up everything.")
        else:
            print("\nCouldn't find a URL in the media object -- paste this back.")


def run_delete_tasks(args):
    """Delete one or more generation tasks from your PixAI account (IRREVERSIBLE).

    Guards, in order:
      1. Dry-run by default -- prints the target list and stops. Requires --apply.
      2. With --apply, a typed 'delete' confirmation (skippable with --yes, which
         is refused on a non-interactive stdin unless explicitly passed).
      3. Single-attempt per task (delete_task_gql does no retry).
    Local backups (image files + catalog.db) are NOT touched -- this only removes
    the generation from your account on PixAI's servers.
    """
    raw = getattr(args, "delete_task", None) or []
    seen, ids = set(), []
    for t in raw:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            ids.append(t)
    if not ids:
        raise PixAIError("No task ids given. Usage: --delete-task <taskId> [<taskId> ...]")

    print("Tasks targeted for deletion ({}):".format(len(ids)))
    for t in ids:
        print("  {}".format(t))

    if not getattr(args, "apply", False):
        print("\nDRY RUN -- nothing deleted. Re-run with --apply to permanently delete "
              "these from your PixAI account.")
        print("(Deletion is irreversible. Your local backups are NOT affected.)")
        return {"targeted": len(ids), "deleted": 0, "failed": 0, "dry_run": True}

    if not getattr(args, "yes", False):
        if not getattr(sys.stdin, "isatty", lambda: False)():
            raise PixAIError(
                "--apply needs interactive confirmation. Re-run attached to a terminal, "
                "or pass --yes to confirm non-interactively (irreversible -- be careful).")
        ans = input("\nPermanently delete {} task(s) from your PixAI account? "
                    "Type 'delete' to confirm: ".format(len(ids)))
        if ans.strip().lower() != "delete":
            print("Aborted -- nothing deleted.")
            return {"targeted": len(ids), "deleted": 0, "failed": 0, "aborted": True}

    session = _make_session(getattr(args, "token", None))
    delay = getattr(args, "delay", 0.4)
    deleted = failed = 0
    for i, t in enumerate(ids, 1):
        try:
            # deleteGenerationTask is a void mutation: it returns null on a
            # SUCCESSFUL delete and raises (GraphQL errors / 401 / PersistedQuery
            # NotFound) on failure. So a clean return -- whatever the payload --
            # means the task was deleted.
            delete_task_gql(session, t)
            deleted += 1
            print("  [{}/{}] deleted task {}".format(i, len(ids), t))
        except PixAIError as e:
            failed += 1
            print("  [{}/{}] FAILED task {}: {}".format(i, len(ids), t, e))
        if i < len(ids):
            time.sleep(delay)
    print("\nDeletion complete: {} deleted, {} failed.".format(deleted, failed))
    return {"targeted": len(ids), "deleted": deleted, "failed": failed}


def run_count(args):
    """Tally total tasks and images in the library without downloading."""
    session = _make_session(getattr(args, "token", None))
    count_size = getattr(args, "count_page_size", 5000)
    print("Counting your whole library (page size {})...".format(count_size))
    before = None
    tasks = images = page = 0
    batched_tasks = 0
    while True:
        page += 1
        conn = find_connection(gql(session, page_variables(count_size, before)))
        if not conn:
            break
        edges = conn.get("edges", [])
        if not edges:
            break
        for edge in edges:
            node = edge.get("node", edge)
            tasks += 1
            n = len(media_ids_for(node))
            images += n
            if n > 1:
                batched_tasks += 1
        pi = conn.get("pageInfo", {})
        more = pi.get("hasPreviousPage")
        print("  page {}: {} tasks so far, {} images so far{}".format(
            page, tasks, images, "" if more else "  (reached the end)"))
        if not more:
            break
        before = pi.get("startCursor")
        time.sleep(args.delay)
    print("\n================ LIBRARY TOTALS ================")
    print("Total tasks (generations) : {}".format(tasks))
    print("Total images              : {}  (mediaId + batchMediaIds)".format(images))
    print("Tasks that are batches    : {}  (>1 image each)".format(batched_tasks))
    print("Fetched in {} request(s).".format(page))
    out = Path(args.out)
    disk_count, disk_bytes, thumb_count = _count_backup_images(out) if out.exists() else (0, 0, 0)
    print("\n--- On disk ({}) ---".format(args.out))
    print("Image files on disk       : {}".format(disk_count))
    if thumb_count:
        print("  + preview thumbnails    : {}".format(thumb_count))
    print("Total collection size     : {}".format(
        _format_size(disk_bytes) if disk_bytes else "0 B (folder empty or not found)"))
    if images > tasks:
        print("\nNote: image count exceeds task count because some older tasks\n"
              "produced batches of several images -- all of them get downloaded.")


def artwork_list_gql(session, before=None, last=50):
    """GET listArtworks for the owner's own authorId. Returns the Relay
    connection dict (edges + pageInfo) or None on failure."""
    variables = {"authorId": str(USER_ID), "last": last, "tackLanguage": "en"}
    if before:
        variables["before"] = before
    params = {
        "operation": "listArtworks",
        "u3t": U3T,
        "operationName": "listArtworks",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"clientLibrary": CLIENT_LIBRARY_ARTWORK,
             "persistedQuery": {"version": 1, "sha256Hash": ARTWORK_LIST_HASH}},
            separators=(",", ":")),
    }
    try:
        r = session.get(API_URL, params=params, timeout=60,
                        headers={"x-apollo-operation-name": "listArtworks"})
        if r.status_code != 200:
            return None
        return find_connection(r.json().get("data") or {})
    except (requests.RequestException, ValueError):
        return None


def extract_artwork_meta(node):
    """Pull the published-artwork fields we store from a listArtworks node.
    Keyed by media_id so it merges onto the existing catalog row.

    The listArtworks node already carries an `extra` block (no extra request), from which we
    also lift a compact BlurHash (instant gallery placeholders) + PixAI's per-category NSFW
    classifier scores (a finer signal than the binary is_nsfw). Published rows only."""
    tacks = node.get("tacks") or []
    tags = [t.get("displayName") or t.get("codeName") for t in tacks
            if (t.get("displayName") or t.get("codeName"))]
    extra = node.get("extra") if isinstance(node.get("extra"), dict) else {}
    scores = extra.get("nsfwPredict")
    nsfw_scores = ""
    if isinstance(scores, dict):
        # keep it small + deterministic: round each category to 3 decimals
        try:
            nsfw_scores = json.dumps({k: round(float(v), 3) for k, v in scores.items()
                                      if isinstance(v, (int, float))}, separators=(",", ":"))
        except (TypeError, ValueError):
            nsfw_scores = ""
    return {
        "media_id":      str(node.get("mediaId") or ""),
        "artwork_id":    str(node.get("id") or ""),
        "title":         node.get("title") or "",
        "is_published":  "1" if (node.get("visibility") == "PUBLIC") else "0",
        "is_nsfw":       "1" if node.get("isNsfw") else "0",
        "liked_count":   str(node.get("likedCount") or 0),
        "comment_count": str(node.get("commentCount") or 0),
        "aes_score":     str(node.get("aesScore") or ""),
        "art_tags":      ", ".join(tags),
        "blurhash":      str(extra.get("imageBlurHash") or ""),
        "nsfw_scores":   nsfw_scores,
    }


def run_sync_artworks(args):
    """Page the owner's published artworks (listArtworks) and merge their
    metadata (title, published flag, NSFW flag, likes, comments, aes score, tags)
    onto matching catalog rows by media_id. Published artworks are a subset of
    generations, so unmatched/undownloaded ones are simply skipped.

    Returns {"artworks", "matched", "videos", "fail"} (B15) -- "fail" counts a
    pagination fetch that failed mid-run (artwork_list_gql has no retry of its own,
    unlike gql()) plus any video that failed to download after retries; a non-zero
    "fail" means this run is INCOMPLETE even though it didn't raise. Callers should
    thread it into _cli_job_finish(warn=...) the same way run_download's own callers
    thread dl['fail']."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    # Build the session FIRST -- _make_session auto-resolves USER_ID from the API key when it
    # isn't pinned in config.json. (Checking before this was the bug: it hard-failed on a config
    # that never lists USER_ID even though the key can resolve it.)
    session = _make_session(getattr(args, "token", None))
    if not USER_ID:
        raise PixAIError("USER_ID is missing and could not be resolved from your API key. "
                         "Add USER_ID to config.json as a fallback.")

    by_mid = {}                      # media_id -> artwork fields
    videos = []                      # (video_media_id, title) for animated artworks
    with_videos = getattr(args, "with_videos", False)
    artworks = 0
    before = None
    page = 0
    incomplete = False               # B15: True if pagination stopped on a failed
                                      # fetch rather than legitimately running out of pages
    _prog = getattr(args, "progress", None)
    print("Syncing published artworks (listArtworks)...")
    while True:
        page += 1
        conn = artwork_list_gql(session, before=before, last=50)
        if not conn:
            if page == 1:
                raise PixAIError(
                    "listArtworks returned no data. The ARTWORK_LIST_HASH may have "
                    "rotated after a PixAI update -- recapture it into config.json.")
            # B15: unlike gql() (retries 4x, then raises), artwork_list_gql has no
            # retry of its own -- a RequestException/non-200/bad-JSON on any page
            # after the first is swallowed and returns None (see its own docstring).
            # Treat that exactly like the download-retry-exhausted case: whatever was
            # already collected is real and worth keeping, but the run is INCOMPLETE,
            # not a clean finish -- it must not report a total that looks whole.
            incomplete = True
            print("\n  page {} fetch failed (no response) -- stopping pagination early. "
                  "Results below are INCOMPLETE, not a full sync.".format(page))
            break
        edges = conn.get("edges", [])
        if not edges:
            break
        for edge in edges:
            node = edge.get("node", edge)
            meta = extract_artwork_meta(node)
            if meta["media_id"]:
                by_mid[meta["media_id"]] = meta
                artworks += 1
            vmid = node.get("videoMediaId")
            if vmid:
                videos.append((str(vmid), meta.get("title") or node.get("id")))
        print("  page {}: {} artworks (total {})".format(page, len(edges), artworks))
        if _prog:
            _prog(artworks, artworks, 0)
        pi = conn.get("pageInfo", {})
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
        time.sleep(getattr(args, "delay", 0.4))

    # Merge onto existing catalog rows by media_id.
    rows = load_catalog(db_path)
    matched = 0
    for r in rows:
        m = by_mid.get(r.get("media_id"))
        if not m:
            continue
        for k, v in m.items():
            if k != "media_id":
                r[k] = v
        matched += 1
    if matched:
        save_catalog(db_path, rows)
    print("\nArtworks fetched: {}.  Matched to catalog rows: {}.  "
          "(Unmatched artworks have no downloaded image.)".format(artworks, matched))

    # Optionally download animated-artwork video files (videoMediaId) into videos/.
    vids_ok = 0
    vids_failed = 0                  # B15: real failures after retries, not "missing"
    if with_videos and videos:
        vdir = out / "videos"
        vdir.mkdir(parents=True, exist_ok=True)
        workers = max(1, getattr(args, "workers", 1) or 1)
        print("\nDownloading {} animated artwork video(s) -> videos/ {}...".format(
            len(videos), "({} workers) ".format(workers) if workers > 1 else ""))

        def _fetch_video(item):
            vmid, title = item
            if already_downloaded_video(out, vmid):
                return "skip"
            url, info = resolve_media(session, vmid)
            if not url:
                return "missing"
            stem = vdir / build_stem_name(title or "", "", vmid,
                                          getattr(args, "name_length", 60),
                                          getattr(args, "name_sep", "_"))
            status, path = download(session, url, stem)
            return status

        for item, status in _parallel_map(videos, _fetch_video, workers, _prog,
                                          delay=getattr(args, "delay", 0.4)):
            if status in ("ok", "skip"):
                vids_ok += 1
            elif status == "missing":
                print("  no media url for video {} ({})".format(item[0], item[1]))
            elif status == "fail":
                # download() already retried internally before giving up -- same
                # terminal "fail" status run_download's own dl['fail'] counts.
                vids_failed += 1
                print("  FAILED video {} ({})".format(item[0], item[1]))
        print("Videos saved/present: {} of {}.".format(vids_ok, len(videos)))
    elif videos and not with_videos:
        print("({} animated artworks have video; re-run with --with-videos to download them.)"
              .format(len(videos)))

    # B15: same "done_with_errors" visibility run_download's own callers already get --
    # a loud console notice plus the same machine-readable marker for the Panel
    # subprocess reader (this function is run as its own subprocess by the "sync-artworks"
    # Panel action, exactly like a plain download). Exit code is unaffected by design,
    # same rationale as run_download's own end-of-run notice.
    fail = (1 if incomplete else 0) + vids_failed
    if fail:
        detail = []
        if incomplete:
            detail.append("artwork listing stopped early after a page fetch failed")
        if vids_failed:
            detail.append("{} video(s) failed to download after retries".format(vids_failed))
        print("\n*** FINISHED WITH ERRORS: {} -- exit code is still 0 by design. ***"
              .format("; ".join(detail)))
        if os.environ.get("MOONGLADE_PROGRESS") == "1":
            print("{}{}".format(PANEL_WARN_PREFIX, fail), flush=True)

    return {"artworks": artworks, "matched": matched, "videos": vids_ok, "fail": fail}


def run_sync_videos(args):
    """Back up image-to-video generations. The task listing exposes only a video's
    THUMBNAIL media id; the real video media id lives in getTaskById ->
    outputs.videos[].mediaId, and its mp4 URL in the GraphQL media object's
    fileUrl. So: find i2v tasks (i2vProModel set in the summary), fetch each task,
    resolve + download the mp4 into videos/, and catalog it as a video row
    (is_video=1) with the still frame as its poster."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    vdir = out / "videos"
    workers = max(1, getattr(args, "workers", 1) or 1)
    name_length = getattr(args, "name_length", 60)
    name_sep = getattr(args, "name_sep", "_")
    _prog = getattr(args, "progress", None)

    # 1. Page the whole feed; collect the cheap i2v task summaries.
    print("Scanning generation history for image-to-video tasks...")
    i2v_nodes, before, scanned = [], None, 0
    while True:
        conn = find_connection(gql(session, page_variables(
            getattr(args, "page_size", 250) or 250, before)))
        if not conn:
            break
        edges = conn.get("edges") or []
        if not edges:
            break
        for e in edges:
            n = e.get("node") or {}
            scanned += 1
            if n.get("i2vProModel"):
                i2v_nodes.append(n)
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
    print("Found {} image-to-video task(s) across {} generations.".format(
        len(i2v_nodes), scanned))
    if not i2v_nodes:
        return {"i2v_tasks": 0, "videos": 0}
    vdir.mkdir(parents=True, exist_ok=True)

    # Generate a gallery poster thumbnail for a video (keyed by the VIDEO media
    # id) from its still frame, so previews work without a separate image backup.
    from moonglade_gallery import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    poster_tmp = out / "gallery" / "_postertmp"

    def _ensure_video_thumb(video_media_id, poster_media_id, video_path=None):
        thumb_path = thumb_dir / "{}.jpg".format(video_media_id)
        if thumb_path.exists():
            return
        try:
            # Preferred: thumbnail the PixAI still-frame poster.
            if poster_media_id:
                url, _info = resolve_media(session, poster_media_id)
                if url:
                    poster_tmp.mkdir(parents=True, exist_ok=True)
                    status, path = download(session, url, poster_tmp / str(poster_media_id))
                    if status in ("ok", "skip") and path:
                        make_thumbnail(path, thumb_path)
                        try:
                            path.unlink()
                        except OSError:
                            pass
            # Fallback (no poster, e.g. older i2v): first frame of the mp4 via ffmpeg.
            if not thumb_path.exists() and video_path:
                video_poster_thumb(video_path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the sync
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(video_media_id, e))

    # 2. Per task: getTaskById -> video outputs -> fileUrl -> download mp4.
    def _do_task(node):
        task = task_detail_gql(session, node["id"])
        outs, shared = video_outputs(task)
        detail = ((task or {}).get("outputs") or {}).get("detailParameters") or {}
        params = (task or {}).get("parameters") or {}
        rows = []
        for o in outs:
            vmid = o["video_media_id"]
            hit = [p for p in vdir.glob("*_{}.*".format(vmid))
                   if not p.name.endswith(".part") and p.stat().st_size > 0]
            if hit:
                path, status = hit[0], "skip"
            else:
                fm = media_file_gql(session, vmid)
                url = fm.get("fileUrl")
                if not url:
                    rows.append("missing")
                    continue
                stem = vdir / build_stem_name(
                    shared.get("prompt") or node.get("promptsPreview", ""),
                    node["id"], vmid, name_length, name_sep)
                status, path = download(session, url, stem)
            if status in ("ok", "skip") and path:
                full = {f: "" for f in CATALOG_FIELDS}
                full.update({
                    "task_id": str(node["id"]),
                    "media_id": vmid,
                    "filename": str(path.relative_to(out)).replace("\\", "/"),
                    "prompt_full": shared.get("prompt", ""),
                    "prompt_preview": (node.get("promptsPreview") or "")[:100],
                    "seed": str(o.get("seed") or ""),
                    "created_at": node.get("createdAt", ""),
                    "width": str(detail.get("width") or ""),
                    "height": str(detail.get("height") or ""),
                    "model_id": str(params.get("modelId") or ""),
                    "status": "completed",
                    "is_video": "1",
                    "poster_media_id": o.get("poster_media_id", ""),
                    "paid_credit": _paid_credit_str(task),   # actual cost, task-level
                    "video_duration": str(shared.get("duration") or ""),
                })
                _ensure_video_thumb(vmid, o.get("poster_media_id"), path)
                video_faststart(path)                # iOS needs moov at the front to stream
                rows.append(full)
            else:
                rows.append(status)
        return rows

    print("Resolving + downloading videos -> videos/ {}...".format(
        "({} workers) ".format(workers) if workers > 1 else ""))
    new_rows, ok, missing = [], 0, 0
    for node, result in _parallel_map(i2v_nodes, _do_task, workers, _prog,
                                      delay=getattr(args, "delay", 0.4)):
        for item in (result or []):
            if isinstance(item, dict):
                new_rows.append(item); ok += 1
            elif item == "missing":
                missing += 1
    if new_rows:
        save_catalog(db_path, new_rows)
    print("Videos saved/present: {}{}.".format(
        ok, " | {} had no resolvable file url".format(missing) if missing else ""))
    return {"i2v_tasks": len(i2v_nodes), "videos": ok}


_VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".mkv", ".m4v"})


def _under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _ffmpeg_path(_cache=[]):
    """Return the ffmpeg executable path if available, else '' (cached)."""
    if not _cache:
        import shutil
        _cache.append(shutil.which("ffmpeg") or "")
    return _cache[0]


def video_poster_thumb(video_path, thumb_path):
    """Extract a frame of a video via ffmpeg and write it as the gallery thumbnail.
    OPTIONAL: returns False (no-op) if ffmpeg isn't on PATH, so videos just fall
    back to the placeholder + play badge. Used for imported videos and as a
    fallback for i2v videos with no still-frame poster.

    Thin delegate: the ONE ffmpeg-extract implementation lives in
    moonglade_gallery.make_video_thumbnail (which build_thumbnails' poster-less
    fallback also uses) -- two copies of this wheel WILL drift. The `_ffmpeg_path`
    guard stays here because import-local and sync-videos gate on it."""
    if not _ffmpeg_path():
        return False
    from moonglade_gallery import make_video_thumbnail
    return make_video_thumbnail(video_path, thumb_path)


def _mp4_is_faststart(path):
    """True if an mp4's `moov` atom precedes `mdat` — i.e. iOS/Safari can stream it
    progressively over HTTP. Best-effort top-level box scan; returns True on any parse
    trouble so we never remux a file we can't read."""
    import struct
    order = []
    try:
        with open(path, "rb") as f:
            while len(order) < 12:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                size = struct.unpack(">I", hdr[:4])[0]
                order.append(hdr[4:8].decode("latin1", "replace"))
                if size == 1:                       # 64-bit extended size
                    size = struct.unpack(">Q", f.read(8))[0]; f.seek(size - 16, 1)
                elif size == 0:                     # extends to EOF
                    break
                else:
                    f.seek(size - 8, 1)
                if "moov" in order and "mdat" in order:
                    break
    except (OSError, struct.error, ValueError):
        return True
    if "moov" not in order:
        return True
    di = order.index("mdat") if "mdat" in order else 10 ** 9
    return order.index("moov") < di


def video_faststart(path):
    """Losslessly move an mp4's `moov` atom to the front (ffmpeg -c copy -movflags
    +faststart) so iOS/Safari will play it over HTTP -- PixAI serves videos with moov at
    the END, which desktop tolerates but iOS refuses (MediaError 4). No re-encode, no
    quality loss. Returns True only when it rewrote the file; no-op (False) if ffmpeg is
    absent, the file is already faststart, or the remux fails (original left untouched).

    The temp name is UNIQUE per invocation (uuid suffix), never derived from the
    filename alone. Two collectors can legitimately remux the same clip seconds apart
    (the gallery's live-mirror watcher and a /api/task-status done-poll both collect a
    finished task, and the CLI's --watch-backup is a whole separate process), and with
    a deterministic temp name their two concurrent ffmpeg runs interleaved writes into
    the SAME temp file: the survivor was a full-length mp4 carrying the other run's
    stale pre-shift bytes exactly one moov-size offset out of place -- it played fine
    and then stopped mid-way. With unique temps any overlap is safe: each remux is
    complete and self-contained, and whichever os.replace lands last wins with a
    COMPLETE file either way."""
    p = Path(path)
    if p.suffix.lower() not in (".mp4", ".mov", ".m4v"):
        return False
    ff = _ffmpeg_path()
    if not ff or not p.exists() or _mp4_is_faststart(p):
        return False
    import subprocess
    from uuid import uuid4
    # unique per call; the real ext stays LAST so ffmpeg still picks the muxer by extension
    tmp = p.with_name(p.stem + ".__fstmp__" + uuid4().hex[:8] + p.suffix)
    try:
        r = subprocess.run([ff, "-y", "-v", "error", "-i", str(p),
                            "-c", "copy", "-movflags", "+faststart", str(tmp)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
                           creationflags=_NO_WINDOW)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(str(tmp), str(p))            # atomic swap
            return True
    except Exception as e:                          # noqa: BLE001 -- remux must never crash a collect
        # swallowed by design (a failed remux leaves the original playable), but never
        # silently: a lost race or an odd ffmpeg failure must at least show under -v.
        vlog("faststart remux failed for {}: {}".format(p.name, e))
    try:
        if tmp.exists():
            tmp.unlink()   # the temp is unique to THIS call, so this only ever cleans our own leftover
    except OSError:
        pass
    return False


def run_faststart_videos(args):
    """Rewrite every non-faststart mp4 under videos/ so iOS can stream them (lossless
    -c copy +faststart). Idempotent -- skips files already faststart. Touches only the
    video files, never the catalog. Fixes the 'plays on desktop, error 4 on iPhone' bug
    for the existing library; new videos are faststarted at collect time automatically."""
    out = Path(args.out)
    vdir = out / "videos"
    vids = sorted(p for p in vdir.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".m4v")) if vdir.exists() else []
    if not _ffmpeg_path():
        print("ffmpeg not found on PATH; cannot faststart."); return {"fixed": 0, "total": len(vids)}
    print("Faststart pass over {} video(s) in {}...".format(len(vids), vdir), flush=True)
    fixed = skipped = 0
    for i, p in enumerate(vids, 1):
        if _mp4_is_faststart(p):
            skipped += 1
        elif video_faststart(p):
            fixed += 1
            print("  [{}/{}] faststart -> {}".format(i, len(vids), p.name), flush=True)
    print("Done: {} rewritten, {} already OK ({} total).".format(fixed, skipped, len(vids)))
    return {"fixed": fixed, "skipped": skipped, "total": len(vids)}


def run_import_local(args):
    """Catalog non-PixAI media so it shows + plays in the gallery (source='local').

    Two modes:
      * No dir (or a dir already inside the backup): scan the backup folder and
        catalog any image/video NOT already in the catalog -- i.e. files you
        dropped into videos/ or anywhere under the backup.
      * External dir: copy each media file into the backup (videos/ or imported/)
        then catalog it.

    Idempotent: files already cataloged (by relative path) are skipped, so it's
    safe to re-run. Images get a gallery thumbnail; videos play via the catalog
    filename (no still to thumbnail, so they show a placeholder + the video badge)."""
    import hashlib
    import shutil
    from moonglade_gallery import make_thumbnail
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # import can seed a fresh, download-free backup
    thumb_dir = out / "gallery" / "thumbs"
    media_exts = _IMAGE_EXTS | _VIDEO_EXTS

    raw = getattr(args, "import_local", None)
    src = Path(raw) if raw else out
    if not src.exists():
        raise PixAIError("import path not found: {}".format(src))
    try:
        external = not _under(src.resolve(), out.resolve()) and src.resolve() != out.resolve()
    except OSError:
        external = False

    _prog = getattr(args, "progress", None)
    catalog_rows = load_catalog(db_path)
    existing = {(r.get("filename") or "").replace("\\", "/")
                for r in catalog_rows if r.get("filename")}
    # Also key on media_id: an already-backed-up PixAI file is named after its
    # media id, so media_id_of() of an organized file matches an existing row even
    # though its on-disk path no longer equals the stored `filename` string. This
    # is what stops --import-local from re-cataloging the whole backup as 'local'.
    existing_mids = {r.get("media_id") for r in catalog_rows if r.get("media_id")}
    gallery_dir = out / "gallery"
    quarantine = out / "_duplicates"
    # Branding moved to the APP root on 2026-07-26, so this no longer names a live
    # directory -- kept because an install that predates the move still has files here,
    # and --import-local would otherwise catalogue someone's banner and mascots as
    # gallery images. Excluding an absent path costs nothing; dropping the exclusion
    # would silently sweep a legacy folder into the library.
    branding_dir = out / "branding"   # app chrome (banner/logo/marks) -- never gallery content
    # B11 (audit 2026-07-21): purge_media_local() clears a purged image's catalog
    # row when it moves the file to _deleted/, so without this exclusion the scan
    # below sees an orphaned file with no existing row/media_id match and
    # resurrects it as a brand-new source='local' row.
    deleted_dir = out / DELETED_DIRNAME

    print("Scanning {} for media (this can take a moment on a large backup)...".format(src),
          flush=True)
    candidates, scanned = [], 0
    for p in src.rglob("*"):
        scanned += 1
        if scanned % 5000 == 0:
            vlog("scanned {} files, {} media so far...".format(scanned, len(candidates)))
        if p.is_file() and p.suffix.lower() in media_exts and not p.name.endswith(".part"):
            candidates.append(p)
    total = len(candidates)
    print("Found {} media file(s) among {} scanned; cataloging new ones...".format(
        total, scanned), flush=True)

    rows, made, skipped = [], 0, 0
    for idx, p in enumerate(candidates):
        if _prog:
            _prog(idx + 1, total, 0)
        if not external and (_under(p, gallery_dir) or _under(p, quarantine)
                             or _under(p, branding_dir) or _under(p, deleted_dir)):
            continue
        is_vid = p.suffix.lower() in _VIDEO_EXTS
        if external:
            dest_dir = out / ("videos" if is_vid else "imported")
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / p.name
            if not dest.exists():
                shutil.copy2(p, dest)
            stored = dest
        else:
            stored = p
        rel = str(stored.relative_to(out)).replace("\\", "/")
        if rel in existing or media_id_of(stored) in existing_mids:
            skipped += 1                  # already cataloged (by path OR PixAI media id)
            continue
        mid = "local_" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
        try:
            created = time.strftime("%Y-%m-%dT%H:%M:%S",
                                    time.localtime(stored.stat().st_mtime))
        except OSError:
            created = ""
        full = {f: "" for f in CATALOG_FIELDS}
        full.update({
            "media_id": mid, "filename": rel, "source": "local",
            "status": "imported", "created_at": created,
            "prompt_preview": stored.stem[:100],
            "is_video": "1" if is_vid else "",
        })
        rows.append(full)
        if is_vid:
            video_poster_thumb(stored, thumb_dir / "{}.jpg".format(mid))  # ffmpeg, optional
            video_faststart(stored)                  # iOS needs moov at the front to stream
        else:
            make_thumbnail(stored, thumb_dir / "{}.jpg".format(mid))
        made += 1
        vlog("imported {} ({})".format(rel, "video" if is_vid else "image"))

    if rows:
        save_catalog(db_path, rows)
    print("Imported {} new local file(s){}; {} already cataloged.".format(
        made, " (copied into the backup)" if external else "", skipped))
    # media_ids of the rows created THIS run -- the web importer uses them to tag an
    # optional collection; CLI callers that only read imported/skipped are unaffected.
    return {"imported": made, "skipped": skipped,
            "media_ids": [r["media_id"] for r in rows]}


_GEN_MUTATION = ("mutation createGenerationTask($parameters: JSONObject!) {"
                 " createGenerationTask(parameters: $parameters) { id } }")
_GEN_STATUS = ("query($id: ID!) { task(id: $id) "
               "{ id status paidCredit startedAt outputs } }")
# startedAt + outputs are load-bearing, not decoration: `startedAt` is the ONLY way to
# tell a task PixAI queued-but-never-dispatched from one that is genuinely running (both
# sit at a non-terminal status), and `outputs.reason` carries PixAI's own explanation for
# a cancellation (e.g. "waiting timeout"). Without them this poller could only ever see
# `status`, which is how five of the owner's generations died silently across four days.
DEFAULT_GEN_MODEL = "1983308862240288769"  # Tsubaki.2 v1 (override with --model)


# LoRA weight bounds are per BASE ARCHITECTURE. Owner-reported from the live site,
# 2026-07-25, after using the first (flat) slider:
#
#     DiT family (dit1, Tsubaki.2/DiT.2, community DiT) :  0.0 .. 1.2
#     SD1.5, SDXL                                       : -2.0 .. +2.0
#
# There is no single correct range, which is why both earlier attempts were wrong in
# opposite directions: a 0..2 spinner blocked the legal negatives SD allows, and a flat
# -2..2 slider offered DiT weights PixAI rejects. Negative weights subtract a LoRA's
# influence and are legal on the SD architectures only.
LORA_WEIGHT_STEP = 0.1
# The owner's rule, given 2026-07-25: every DiT family is 0..1.2; only SD1.5 and SDXL are
# -2..+2. Extended 2026-07-26 once the full enum was enumerated from PixAI's bundle -- this table
# held five architectures when there are twenty-five members, and the fallback for an unrecognised
# one is the SD range, so a DiT LoRA was being offered -2..+2 against a real ceiling of 1.2.
#
# DIT7_MODEL is the important addition: it is what their picker sends for "DiT.1", and only
# DIT7B_MODEL was listed here, so the commonest DiT case was very likely already falling through.
LORA_WEIGHT_RANGES = {
    # DiT, every variant in the bundle -- 0..1.2.
    "DIT7_MODEL":        (0.0, 1.2),
    "DIT7A_MODEL":       (0.0, 1.2),
    "DIT7B_MODEL":       (0.0, 1.2),
    "DIT7C_MODEL":       (0.0, 1.2),
    "DIT7D_MODEL":       (0.0, 1.2),
    "DIT9_MODEL":        (0.0, 1.2),   # "Community DiT" in their UI
    "MMDIT26A_MODEL":    (0.0, 1.2),   # DiT.2 / Tsubaki.2
    "MMDIT26B_MODEL":    (0.0, 1.2),   # DiT.3 -- had no entry at all before today
    "USER_DIT26A_MODEL": (0.0, 1.2),   # a user-TRAINED DiT.2, which is what the owner's own are
    # Stable Diffusion -- the only two the owner specified as -2..+2.
    "SD_V1_MODEL":       (-2.0, 2.0),
    "SDXL_MODEL":        (-2.0, 2.0),
    # DELIBERATELY ABSENT: SD3_MEDIUM_MODEL and Z_IMAGE_V1_MODEL. Both are real members, but the
    # owner's ranges never covered them, and they fall through to the widest range on purpose --
    # narrowing a slider on a guess would remove a capability the account may really have, while
    # a value the architecture rejects merely surfaces as a refused submit, which costs nothing.
}
# The union, used as the hard sanity bound in _lora_params (which sees a version id and a
# number, never an architecture) and as the fallback for an unknown or not-yet-picked base.
# Deliberately the WIDER of the two rather than the narrower: unknown must not silently
# remove a capability the account actually has, and the same fail-open reasoning as
# LORA_BASE_MODEL_TYPES above. A value the architecture rejects surfaces as a refused
# submit, which costs nothing.
LORA_WEIGHT_MIN, LORA_WEIGHT_MAX = -2.0, 2.0


def lora_weight_range(model_type):
    """(min, max) for a base model's architecture; the widest range when it is unknown."""
    return LORA_WEIGHT_RANGES.get(str(model_type or "").strip().upper(),
                                  (LORA_WEIGHT_MIN, LORA_WEIGHT_MAX))


def _lora_params(raw):
    """Turn LoRA specs into createGenerationTask's two fields. `raw` is a list of
    'versionId:weight' strings or (versionId, weight) tuples. Returns
    ({versionId: weight}, [{weight, versionId}])."""
    lora_map, lora_list = {}, []
    for item in (raw or []):
        if isinstance(item, (tuple, list)):
            vid, w = str(item[0]).strip(), item[1]
        else:
            vid, _sep, ws = str(item).partition(":")
            vid = vid.strip()
            w = ws.strip()
        if not vid:
            continue
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 0.7
        # PixAI's own Advanced panel bounds the weight at -2..2 (step 0.1), negatives
        # included -- read off the live control. Clamped here for the same reason the
        # upscale params are: this is the last place before the submit, and a value outside
        # their range is a rejected generation rather than a stronger effect.
        w = max(LORA_WEIGHT_MIN, min(LORA_WEIGHT_MAX, w))
        lora_map[vid] = w
        lora_list.append({"weight": w, "versionId": vid})
    return lora_map, lora_list


# --- Upscale + boosters (ordinary t2i/i2i generation parameters) --------------
# PixAI's "Confirm Upscale" dialog offers TWO methods as radio buttons, and each radio's
# `value` attribute IS the parameter name the submit carries:
#   enlarge -> `enlarge` (ratio) + `enlargeModel` (which upscaler network runs)
#   upscale -> `upscale` (ratio) + upscaleDenoisingStrength/Steps/Sampler ("Hires": the
#              image is re-diffused at the larger size, which is why it has denoising
#              controls and no upscaler dropdown, and why it costs roughly 3x as much)
# They are the same family of params as width/height -- NOT a separate plugin surface --
# so they ride the generation submit we already make.
ENLARGE_MODELS = ("ESRGAN_4x", "R-ESRGAN 4x+", "R-ESRGAN 4x+ Anime6B", "SwinIR_4x",
                  "Lollypop")
DEFAULT_ENLARGE_MODEL = "R-ESRGAN 4x+ Anime6B"      # PixAI's own default selection
DEFAULT_QUALITY_TAG = "Masterpiece"                 # their "Quality Tag" booster's prefix
# Captured from a completed Hires job; their dialog hints strength works best 0.4-0.6.
DEFAULT_UPSCALE_DENOISING_STRENGTH = 0.6
DEFAULT_UPSCALE_DENOISING_STEPS = 26
UPSCALE_RATIO_STEP = 0.1                            # both sliders step in tenths
# A ratio slider's MAXIMUM is not a constant -- it moves with the source dimensions,
# because what is actually capped is the OUTPUT pixel count. Measured maxima: a 1400x784
# source allowed 1.9 in enlarge mode (-> 2656x1488) and 1.4 in Hires (-> 1952x1096),
# while a 768x1280 source allowed 1.5 in Hires (-> 1152x1920). Each measurement brackets
# the ceiling between "the largest allowed output area" and "the next 0.1 step's area":
#   enlarge  >= 2656*1488 = 3,952,128  and  < 2800*1568 = 4,390,400
#   Hires    >= 1152*1920 = 2,211,840  and  < 2096*1176 = 2,464,896  (both samples merged)
# The values below sit inside those windows and reproduce all three measurements exactly.
# INFERRED FROM TWO SOURCE SIZES, NOT DOCUMENTED: a source whose own bracket falls outside
# these windows could be one 0.1 step off, so treat a PixAI rejection here as new data
# rather than a bug in the arithmetic.
UPSCALE_PIXEL_CEILING = {"enlarge": 2048 * 2048, "upscale": 2048 * 1152}
# Every enlargeModel is a 4x network, and no measurement has ever shown a slider past it,
# so 4.0 is the backstop for a source small enough that the area ceiling never bites.
UPSCALE_RATIO_HARD_MAX = 4.0


def upscale_output_dims(width, height, ratio):
    """Output size an upscale ratio produces: scaled, then floored to the multiple of 8
    every SD pipeline needs (the same snap _gen_parameters applies to width/height).
    This is what their dialog prints under the slider -- 1400x784 at Hires 1.4 reads
    '1952x1096', not 1960x1096, because the floor happens after the float multiply."""
    r = float(ratio or 1)
    return (max(64, int((int(width) * r) // 8) * 8),
            max(64, int((int(height) * r) // 8) * 8))


def max_upscale_ratio(width, height, mode="enlarge"):
    """Largest ratio `mode` allows for a source of this size, in the slider's own 0.1
    steps -- derived from UPSCALE_PIXEL_CEILING, never hardcoded, because the same
    dialog shows different maxima for different source sizes. Walks the steps down from
    the hard backstop so the answer honours the multiple-of-8 snap the real output uses.
    Returns 1.0 (= no upscale possible) for a source already at the ceiling."""
    ceiling = UPSCALE_PIXEL_CEILING.get(str(mode))
    if ceiling is None:
        raise PixAIError("unknown upscale mode {!r} -- expected one of {}".format(
            mode, ", ".join(sorted(UPSCALE_PIXEL_CEILING))))
    steps = int(round((UPSCALE_RATIO_HARD_MAX - 1.0) / UPSCALE_RATIO_STEP))
    for i in range(steps, 0, -1):
        r = round(1.0 + i * UPSCALE_RATIO_STEP, 1)
        w, h = upscale_output_dims(width, height, r)
        if w * h <= ceiling:
            return r
    return 1.0


def _upscale_ratio(raw):
    """Normalize a requested ratio to the slider's 0.1 step, or None when the caller did
    not really ask for an upscale. 1.0 (and anything below) IS "no upscale" -- emitting
    enlarge/upscale at 1.0 would still change the priced shape for no visible gain."""
    try:
        r = round(float(raw), 1)
    except (TypeError, ValueError):
        return None
    return r if r > 1.0 else None


def _gen_parameters(args):
    if getattr(args, "params_json", ""):
        return json.loads(args.params_json)
    def _dim(v):                          # SD models require multiples of 8
        return max(64, (int(v) // 8) * 8)
    params = {
        "prompts": args.prompt,
        # naturalPrompts is the natural-language form the prompt-helper reads; send
        # it alongside prompts (PixAI's generator does the same).
        "naturalPrompts": args.prompt,
        "modelId": args.model or DEFAULT_GEN_MODEL,
        "width": _dim(args.width),
        "height": _dim(args.height),
        "samplingSteps": args.steps,
        "cfgScale": args.cfg,
        # batchSize must be >= 1. `--batch-size` shares dest="count" with the top-level
        # `--count` (store_true) flag, so its default can arrive as False -> coerce.
        "batchSize": max(1, int(getattr(args, "count", 1) or 1)),
        # 1000 = high priority (faster, more credits); 500 = standard (cheaper).
        # We default to standard so a run costs less unless high is requested.
        "priority": getattr(args, "priority", 500) or 500,
    }
    # Quality mode (inferenceProfile) is MODEL-TYPE-SPECIFIC: SD_V1_MODEL accepts
    # lite/standard but rejects pro/ultra (those are for newer model types). So we
    # only send it when explicitly chosen; "auto"/"" omits it and lets PixAI pick
    # the model's default (always safe -- this is the original working behavior).
    mode = (getattr(args, "mode", "") or "").strip().lower()
    if mode and mode != "auto":
        params["inferenceProfile"] = mode
    if getattr(args, "negative", ""):
        params["negativePrompts"] = args.negative
    if getattr(args, "seed", None) is not None:
        params["seed"] = args.seed
    # LoRAs: createGenerationTask wants BOTH a {versionId: weight} map and a
    # [{weight, versionId}] array, keyed by the LoRA's version id.
    lmap, llist = _lora_params(getattr(args, "lora", None))
    if lmap:
        params["lora"] = lmap
        params["loraParameters"] = llist
    # Prompt helper (auto-interprets/enhances the natural prompt). On by default to
    # match the site; turn OFF when it mangles a carefully-built prompt.
    if getattr(args, "prompt_helper", True):
        params["promptHelper"] = {"withStage": True, "userWantToEnable": True,
                                  "forcePromptHelperDetectionSide": "server"}
    else:
        params["promptHelper"] = {"withStage": False, "userWantToEnable": False,
                                  "forcePromptHelperDetectionSide": "server"}
    # Reference image (the site's "use as reference" = plain img2img): a top-level
    # mediaId + strength on an otherwise standard submit. Banked from a real capture
    # 2026-07-04 (task 2030052367400863154): {..., mediaId, strength: 0.55}.
    ref = str(getattr(args, "ref_media_id", "") or "").strip()
    if ref:
        params["mediaId"] = ref
        try:
            stg = float(getattr(args, "ref_strength", 0.55) or 0.55)
        except (TypeError, ValueError):
            stg = 0.55
        params["strength"] = max(0.05, min(1.0, stg))
    # Upscale + boosters. EVERY key here is emitted only when the caller actually asked
    # for it: these are absent from a plain submit, and an always-present default would
    # silently change what every existing call site generates (and what it costs).
    enlarge = _upscale_ratio(getattr(args, "enlarge", None))
    upscale = _upscale_ratio(getattr(args, "upscale", None))
    if enlarge and upscale:
        # Kept short on purpose: the web route clips a builder refusal to 140 characters
        # for the cost badge's note, so the actionable half must come first.
        raise PixAIError("enlarge and upscale are mutually exclusive -- they are PixAI's "
                         "two upscale methods ('Upscale' and 'Hires'), so pick one")
    # Clamping can land on 1.0 for a source already at the output ceiling; that is "no
    # upscale is possible at this size", so the block is dropped rather than submitting a
    # 1.0 ratio that changes the priced shape and produces nothing.
    if enlarge:
        enlarge = min(enlarge, max_upscale_ratio(params["width"], params["height"],
                                                 "enlarge"))
    elif upscale:
        upscale = min(upscale, max_upscale_ratio(params["width"], params["height"],
                                                 "upscale"))
    if enlarge and enlarge > 1.0:
        params["enlarge"] = enlarge
        # An unknown upscaler name would be rejected by PixAI, so fall back to their own
        # default rather than losing the whole submit over a typo.
        model = str(getattr(args, "enlarge_model", "") or "").strip()
        params["enlargeModel"] = model if model in ENLARGE_MODELS else DEFAULT_ENLARGE_MODEL
    elif upscale and upscale > 1.0:
        params["upscale"] = upscale
        dstr = getattr(args, "upscale_denoising_strength", None)
        dstr = DEFAULT_UPSCALE_DENOISING_STRENGTH if dstr is None else dstr
        dsteps = getattr(args, "upscale_denoising_steps", None)
        dsteps = DEFAULT_UPSCALE_DENOISING_STEPS if dsteps is None else dsteps
        try:
            dstr = float(dstr)
        except (TypeError, ValueError):
            dstr = DEFAULT_UPSCALE_DENOISING_STRENGTH
        try:
            dsteps = int(dsteps)
        except (TypeError, ValueError):
            dsteps = DEFAULT_UPSCALE_DENOISING_STEPS
        # Bounds read off the live dialog's own controls: strength 0.01-0.99 step 0.01,
        # steps 1-50 step 1.
        params["upscaleDenoisingStrength"] = round(max(0.01, min(0.99, dstr)), 2)
        params["upscaleDenoisingSteps"] = max(1, min(50, dsteps))
        # Empty string is what a completed Hires job carried -- Hires has no sampler
        # dropdown of its own, so this hands the choice back to the base generation.
        params["upscaleSampler"] = str(getattr(args, "upscale_sampler", "") or "")
    if getattr(args, "face_fix", False):
        params["enableADetailer"] = True             # their "Face Fix" booster
    qtag = str(getattr(args, "quality_tag", "") or "").strip()
    if qtag:
        params["qualityTag"] = {"prefix": qtag}      # their "Quality Tag" booster
    if getattr(args, "kaisuuken_id", ""):
        params["kaisuukenId"] = str(args.kaisuuken_id)   # spend a free card instead of credits
    return params


# --- Video (image-to-video) generation ---------------------------------------
# The i2v generator uses the SAME createGenerationTask mutation as images, but the
# `parameters` JSONObject is a nested {type, version, parameters:{i2vPro:{...}}}
# shape (reverse-engineered from a real payload, 2026-07-01). A source image
# (media_id) becomes the first frame; an optional tail image gives first/last-frame
# interpolation. This is the engine "Generate shot" will call once wired up.
DEFAULT_VIDEO_MODEL = "v4.0.1"


# Video enums banked from the generator i18n (2026-07-02):
VIDEO_CAMERA_MOVES = ("unset", "horizontal", "pan", "roll", "tilt", "vertical-pan", "zoom")
VIDEO_AUDIO_LANGS = ("english", "japanese", "chinese", "korean", "none")  # "none" = SE only
VIDEO_DURATIONS = (5, 6, 10, 15)                                          # 15 is v4.0-only

# Video model registry: the `.model` NAME a submit carries -> its numeric top-level
# `modelId` (+ a UI label). A real (card-covered) submit carries BOTH; WITHOUT the modelId
# PixAI resolves "Unknown or removed model" and no free card can match -- that was the
# "video card won't tap" bug. All five VERIFIED via --dump-params of real gens (2026-07-06).
VIDEO_MODELS = {
    "v4.0.1": {"model_id": "2003969750675682808", "label": "V4.0 Lite Preview"},
    "v4.0":   {"model_id": "2003968021137101826", "label": "V4.0 Preview (full)"},
    "v3.2":   {"model_id": "1961182207978260675", "label": "V3.2"},
    "v3.0.2": {"model_id": "2014412117889628958", "label": "V3.0 Lite"},
    "v3.0":   {"model_id": "1919508300549460046", "label": "V3.0"},
    # No numeric modelId published for these two, and none is needed -- `i2vPro.model`
    # resolves the engine (see build_video_parameters). Listed so the roster is complete
    # and video_model_id() returns '' for them deliberately, not by accident.
    "v3.0.1": {"model_id": "", "label": "V3.0 Flash"},
    "v2.7":   {"model_id": "", "label": "V2.7 (High Dynamics)"},
}


def video_model_id(name):
    """Numeric top-level `modelId` for a video `.model` name ('' if unknown). A submit MUST
    include this or PixAI can't resolve the model and no free card can match."""
    return (VIDEO_MODELS.get((name or "").strip()) or {}).get("model_id", "")
VIDEO_CHANNELS = ("private", "normal")                                     # private = "Enhanced" (Plus/Premium)


def build_video_parameters(prompt, media_id, model=DEFAULT_VIDEO_MODEL, *,
                           tail_media_id="", duration=5, mode="professional",
                           generate_audio=False, audio_language="english",
                           negative="", use_prompt_helper=False, kaisuuken_id="",
                           camera_movement="", model_id="", is_private=False):
    """Build createGenerationTask's `parameters` for an image-to-video (i2vPro) job.

    VERIFIED against a real card-covered submit (2026-07-06 via --dump-params): the shape
    is a top-level `modelId` + the `i2vPro` block + privacy/preview flags. There is NO
    `channel` field. `media_id` = source/first frame; `tail_media_id` (optional) = last
    frame for FLF interpolation.

    `modelId` is NOT what selects the engine -- `i2vPro.model` is. Corrected 2026-07-21
    after two free --dump-params captures + three read-only price probes: two real tasks
    (v2.7 and v3.0.1) both carried modelId 1648918127446573124, an IMAGE checkpoint, and
    rendered fine; the two models then priced DIFFERENTLY (~56,000 vs ~44,800 for 10s) off
    that IDENTICAL modelId, and omitting modelId altogether priced the same as sending it.
    The earlier "REQUIRED" note came from a v4.0 submit where dropping modelId lost the
    free-card match -- that is a CARD-MATCHING requirement, not a model-resolution one, so
    we still send it whenever VIDEO_MODELS knows one. When it doesn't (v2.7, v3.0.1 -- no
    numeric id published and no card covers them anyway) the key is OMITTED rather than
    sent empty: absent is the shape the probe actually exercised; `modelId: ""` is not.

    NOTE: video costs FAR more than images (~27.5k credits for a 5s V4.0 clip), so
    submission stays gated behind explicit --confirm. This builder spends nothing.
    """
    i2v = {
        "model": model,
        "mediaId": str(media_id),
        "usePromptsHelper": bool(use_prompt_helper),
        "prompts": prompt or "",
        "mode": mode,                        # "basic" | "professional"
        "duration": str(duration),           # seconds, as a string ("5"/"10"/"15")
    }
    # Only for models that support it -- see VIDEO_AUDIO_MODELS. Sending these to v3.0.2 got a
    # misleading NSFW refusal on an image the website accepted.
    if str(model).strip() in VIDEO_AUDIO_MODELS:
        i2v["generateAudio"] = bool(generate_audio)
        i2v["audioLanguage"] = audio_language
    if tail_media_id:
        i2v["tailMediaId"] = str(tail_media_id)
    if negative:
        i2v["negativePrompts"] = negative
    # cameraMovement is v2.7-style camera-dropdown; only send when a real move is picked
    # (the verified v4.0 submit omits it entirely -> keep it out by default).
    if camera_movement and camera_movement != "unset":
        i2v["cameraMovement"] = camera_movement
    params = {
        "priority": 1000,
        "i2vPro": i2v,
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
    }
    _mid = str(model_id or video_model_id(model))
    if _mid:                                  # omit rather than send "" -- see docstring
        params["modelId"] = _mid
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)   # spend a free card instead of credits
    return params


# Reference video (multi-image/video/audio reference) -- a SEPARATE top-level
# `referenceVideo` block, VERIFIED from a real submit (2026-07-02). Distinct from i2vPro.
REFVIDEO_MODEL_ID = "2003969750675682808"   # numeric model id for v4.0.1 reference-video


def build_reference_video_parameters(prompt, image_media_ids=(), *, video_media_ids=(),
                                     audio_media_ids=(), model="v4.0.1",
                                     model_id=REFVIDEO_MODEL_ID, duration=5,
                                     mode="professional", generate_audio=False,
                                     audio_language="english", is_private=False,
                                     priority=1000, kaisuuken_id=""):
    """Build createGenerationTask `parameters` for a REFERENCE video (multi-image / video /
    audio reference). VERIFIED shape (2026-07-02) -- a top-level `referenceVideo` block,
    NOT i2vPro. The prompt references inputs by position with @image1/@video1/@audio1
    mentions. `duration` is an int here; channel maps to `isPrivate`. Builder spends nothing."""
    rv = {
        "mode": mode,
        "model": model,
        "prompt": prompt or "",
        "duration": int(duration),
        "audioLanguage": audio_language,
        "generateAudio": bool(generate_audio),
        "inputVideoDurations": [],
        "referenceAudioMediaIds": [str(m) for m in (audio_media_ids or [])],
        "referenceImageMediaIds": [str(m) for m in (image_media_ids or [])],
        "referenceVideoMediaIds": [str(m) for m in (video_media_ids or [])],
    }
    params = {
        "priority": int(priority),
        "referenceVideo": rv,
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
        "modelId": str(model_id),
    }
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)
    return params


# Only the v4.0 family renders a 15-second clip. VIDEO_DURATIONS has carried the note
# "15 is v4.0-only" since it was banked, but nothing enforced it, so a 15s request on any
# other model went straight to PixAI, which refuses the mutation -- no task is created, so
# nothing appears on the account and the client shows an instant unexplained decline. A rule
# that lives only in a comment is not a rule.
VIDEO_15S_MODELS = ("v4.0", "v4.0.1")


# PixAI rejects a video prompt over this with a raw GraphQL validation error
# ("maxLength must NOT have more than 2000 characters") and no task is created. Measured
# 2026-07-26: the owner's working submit on PixAI's own site carried 1986 characters, so the
# limit is real and he was writing right up against it. Checked here rather than letting the
# round trip fail, so the message can say the actual count and how much to cut.
VIDEO_PROMPT_MAXLEN = 2000


# Which video models actually take the audio fields. SURVEYED 2026-07-26 across the owner's own
# successful tasks, one per model, via getTaskById (read-only, free) -- not inferred:
#
#   v3.2     generateAudio=True   audioLanguage=english     <- audio supported
#   v4.0     generateAudio=True   audioLanguage=english     <- audio supported
#   v4.0.1   generateAudio=True   audioLanguage=english     <- audio supported
#   v3.0.2   (both fields ABSENT)                           <- omit
#   v2.7     (both fields ABSENT)                           <- omit
#   v3.0.1   generateAudio=False, audioLanguage absent      <- omit (never seen carrying audio)
#
# Sending them regardless is NOT harmless, and this is the bug that cost an evening. A controlled
# pair on media id 747704233721405654 with model v3.0.2: PixAI's own site submitted it WITHOUT the
# audio fields and the video rendered; this app submitted it WITH them and was refused
# "This image contains sensitive or NSFW content." Same image, same model, audio the differing
# variable -- so an unsupported audio flag surfaces as a CONTENT complaint, which sent the whole
# investigation chasing a moderation problem that did not exist.
#
# An earlier cut of this guessed "v4.0 family only" and a pre-existing test caught it: v3.2 really
# does carry audio. Hence the survey. Do not narrow this list without measuring the model first.
VIDEO_AUDIO_MODELS = ("v3.2", "v4.0", "v4.0.1")


def _snap_video_duration(d, model=""):
    """Snap a requested duration (seconds) to the nearest allowed PixAI video length.

    `model` (optional) additionally enforces the 15s restriction: 15 is v4.0-only, so any other
    model snaps down to 10 rather than being sent a length PixAI will reject. Omitting `model`
    keeps the original model-blind behavior exactly, which is what the CLI's own preview path
    and the pre-existing tests pin."""
    try:
        d = float(d)
    except (TypeError, ValueError):
        return 5
    snapped = min(VIDEO_DURATIONS, key=lambda v: abs(v - d))
    if snapped == 15 and model and str(model).strip() not in VIDEO_15S_MODELS:
        return 10
    return snapped


def build_shot_video_params(mode, prompt, image_ids=(), video_ids=(), audio_ids=(),
                            *, duration=5, generate_audio=False, model="",
                            audio_language="english", camera_movement="",
                            quality="professional", negative="", is_private=False):
    """PixAI video PROVIDER ADAPTER: map a Loom shot (mode + prompt + @-ordered ref
    media_ids) to createGenerationTask video params. This is the SEAM a future Seedance/
    other provider mirrors -- same shot spec in, provider-native params out. I2V/FLF ->
    i2vPro; R2V/V2V/any-with-refs -> referenceVideo. Duration snaps to PixAI's allowed
    lengths. (Card auto-apply happens at the route: a V4.0 card makes it free.)

    `negative` only reaches i2vPro (I2V/FLF) -- the referenceVideo submit shape captured
    2026-07-02 has no negativePrompts field at all. A genuine PixAI API gap, not an
    oversight here -- R2V/V2V shots silently ignore a negative prompt if one is set."""
    m = (mode or "R2V").upper()
    # Both submit shapes cap the prompt, under different field names
    # (i2vPro.prompts / referenceVideo.prompt), so check once here where they converge.
    if prompt and len(prompt) > VIDEO_PROMPT_MAXLEN:
        raise PixAIError(
            "Your video prompt is {:,} characters and PixAI's limit is {:,} -- trim {:,} and "
            "resubmit. (PixAI rejects the whole submit on this, so nothing was created or "
            "charged.)".format(len(prompt), VIDEO_PROMPT_MAXLEN,
                               len(prompt) - VIDEO_PROMPT_MAXLEN))
    imgs = [str(i) for i in (image_ids or []) if str(i).strip()]
    vids = [str(v) for v in (video_ids or []) if str(v).strip()]
    auds = [str(a) for a in (audio_ids or []) if str(a).strip()]
    mdl = (model or "").strip() or DEFAULT_VIDEO_MODEL
    dur = _snap_video_duration(duration, mdl)
    qual = (quality or "professional").strip() or "professional"
    mid_num = video_model_id(mdl)                  # the REQUIRED numeric modelId for this model
    if m == "I2V" and imgs:
        return build_video_parameters(prompt, imgs[0], model=mdl, duration=dur,
                                      mode=qual, generate_audio=generate_audio,
                                      audio_language=audio_language,
                                      camera_movement=camera_movement, model_id=mid_num,
                                      negative=negative, is_private=is_private)
    if m == "FLF" and len(imgs) >= 2:
        return build_video_parameters(prompt, imgs[0], model=mdl, tail_media_id=imgs[1],
                                      duration=dur, mode=qual, generate_audio=generate_audio,
                                      audio_language=audio_language,
                                      camera_movement=camera_movement, model_id=mid_num,
                                      negative=negative, is_private=is_private)
    if imgs or vids or auds:                       # R2V / V2V / any mode carrying references
        return build_reference_video_parameters(prompt, image_media_ids=imgs,
                                                 video_media_ids=vids, audio_media_ids=auds,
                                                 model=mdl, duration=dur, mode=qual,
                                                 is_private=is_private,
                                                 generate_audio=generate_audio,
                                                 audio_language=audio_language,
                                                 model_id=(mid_num or REFVIDEO_MODEL_ID))
    raise PixAIError("PixAI video needs a frame or a reference image/video for this shot "
                     "(mode {}) -- attach a cast image or an open frame.".format(m))


def probe_video_duration(path):
    """Real duration (seconds, float) of a local clip via ffprobe -- powers the Edit
    Bay's reel from the ACTUAL generated lengths, not the planned ones. None on any
    failure (ffprobe missing / unreadable). Pure read."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stderr=subprocess.DEVNULL, timeout=20,
            creationflags=_NO_WINDOW).decode().strip()
        return round(float(out), 2)
    except Exception:                                  # noqa: BLE001
        return None


def extract_last_frame(video_path, out_png, at_seconds=None):
    """Grab a clip's frame to out_png via ffmpeg. This is the frame-handoff primitive:
    one shot's last frame becomes the next shot's opening frame, so a sequence reads as
    one continuous scene.

    `at_seconds` makes the handoff TRIM-AWARE: the previous shot's trimOut is the point
    the cut actually ends on, so the handed-off frame must be the frame AT that out-point,
    not the untrimmed clip's real final frame. When it's None (no trim) -- or past the
    clip's real end -- fall back to seeking ~0.15s before EOF. Returns out_png or None."""
    import os
    import subprocess
    if at_seconds is not None:
        try:
            dur = probe_video_duration(video_path)
        except Exception:                              # noqa: BLE001
            dur = None
        # a trimOut at/after the real end is just "the last frame" -> use the EOF path
        if not (dur and at_seconds < dur - 0.05):
            at_seconds = None
    try:
        if at_seconds is None:
            seek = ["-sseof", "-0.15", "-i", str(video_path)]
        else:
            # -ss before -i (fast, keyframe-accurate enough for a still); back off a hair
            # so we land ON the last kept frame, not the first discarded one.
            seek = ["-ss", "{:.3f}".format(max(0.0, float(at_seconds) - 0.05)), "-i", str(video_path)]
        subprocess.run(
            ["ffmpeg", "-y"] + seek +
            ["-update", "1", "-frames:v", "1", "-q:v", "2", str(out_png)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=True,
            creationflags=_NO_WINDOW)
        return str(out_png) if os.path.exists(out_png) and os.path.getsize(out_png) > 0 else None
    except Exception:                                  # noqa: BLE001
        return None


# The whole --enhance command is gone, both halves of it, and neither is coming back.
#
# The panelplugin half (--workflow-id: upscale / remove-background / line-art / relight, plus
# workflow_catalog and the web routes that drove them): the submit shape was right -- captured
# from a real task -- but PixAI never assigns a worker to a panelplugin task when the client
# authenticated with an API key. It accepts the submit, queues it, charges for it, then cancels
# it at roughly 60 minutes with outputs.reason "waiting timeout" and refunds. Measured
# 2026-07-24 and isolated by elimination: their own official preset workflow ids behave
# identically while their web client runs the same workflow in 1-3 seconds, and a taskKind=chat
# fixer submit from this app dispatched in one second minutes earlier. No workflow id, input key
# or payload change reaches a runner.
#
# The art-filter half (build_filter_parameters, --filter-id): that one worked, and was still
# the wrong thing to do. PixAI's 7 "art filters" are not inference at all -- each is two or
# three linear gradients with a blend mode, an opacity and an optional
# brightness/contrast/saturation trim, served from a PUBLIC unauthenticated config endpoint
# (GET https://api.pixai.art/config/imageArtFilters) that their own web client reads and
# composites in the browser, with no Generate button and no price on the panel. Submitting that
# as an image-filter generation charged credits and waited on a worker queue to perform a
# handful of gradient fills. static/mg-art-filters.js does the identical composite locally,
# offline, for nothing, so the paid path is deleted rather than left as a strictly worse
# second option.
#
# Guarded by tests/test_enhance.py, which drives the parser to prove the flags are unaccepted
# and greps for the two literals a submit could not do without -- the filter model's id and the
# `inputs` key that named a filter. Neither appears above on purpose: as with "panelplugin",
# the CONCEPT is named in prose so the exact strings stay a reliable tripwire.


def _gen_video_parameters(args):
    """Build the i2v `parameters` from CLI/GUI args (thin wrapper over
    build_video_parameters). `--params-json` overrides everything.

    Snaps --duration to PixAI's allowed lengths (5/6/10/15) before it reaches the
    builder -- the same snap build_shot_video_params (the Loom/web adapter) already
    applies, now made a CLI guarantee too rather than a Loom-only one (B9)."""
    if getattr(args, "params_json", ""):
        return json.loads(args.params_json)
    return build_video_parameters(
        getattr(args, "prompt", "") or "",
        getattr(args, "image", "") or "",
        model=(getattr(args, "video_model", "") or getattr(args, "model", "")
               or DEFAULT_VIDEO_MODEL),
        tail_media_id=getattr(args, "tail", "") or "",
        duration=_snap_video_duration(
            getattr(args, "duration", 5) or 5,
            (getattr(args, "video_model", "") or getattr(args, "model", "")
             or DEFAULT_VIDEO_MODEL)),
        mode=getattr(args, "vmode", None) or "professional",
        generate_audio=bool(getattr(args, "audio", False)),
        audio_language=getattr(args, "audio_language", None) or "english",
        negative=getattr(args, "negative", "") or "",
        use_prompt_helper=bool(getattr(args, "video_prompt_helper", False)),
        kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
        camera_movement=getattr(args, "camera_movement", "") or "",
        is_private=((getattr(args, "vchannel", "") or "private") == "private"),
    )


# --- media upload + instruct-editing (the "Edit this image" surface) --------------
# uploadMedia is a 3-step S3 handshake (verified 2026-07-01): request a presigned
# target, PUT the bytes, then register -> media_id. It's a plain GraphQL mutation, so
# gql_mutate drives it with no persisted hash (single attempt -- see upload_media).
# Uploading is FREE.
_UPLOAD_MEDIA_MUT = (
    "mutation uploadMedia($input: UploadMediaInput!) {"
    " uploadMedia(input: $input) { uploadUrl externalId mediaId"
    " media { id type width height } } }")

# PixAI "Edit Pro" (instruct-editing) model. Override with --edit-model.
EDIT_PRO_MODEL_ID = "2006468692917575683"

# The two image models (modelType CHAT) that accept an instruct/reference edit. Caps VERIFIED
# via the model-capability probe 2026-07-06 (extra.chatEditing). Drives the Edit card's model
# picker + its resolution/quality/aspect option lists + reference-image cap. Reference Pro
# exposes NO quality option (qualities empty) and adds 21:9; Edit Pro is 1K/2K, Reference 2K/4K.
EDIT_MODELS = {
    "edit-pro": {
        "model_id": EDIT_PRO_MODEL_ID,
        "label": "Edit Pro", "max_refs": 4,
        "resolutions": ["1K", "2K"],
        "qualities": ["low", "medium", "high"],
        "aspects": ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "1:3", "3:1"],
        "default": {"resolution": "1K", "quality": "medium", "aspect": "3:4"},
    },
    "reference-pro": {
        "model_id": "1948514378441961474",
        "label": "Reference Pro", "max_refs": 10,
        "resolutions": ["2K", "4K"],
        "qualities": [],
        "aspects": ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "21:9"],
        "default": {"resolution": "2K", "quality": "", "aspect": "3:4"},
    },
}
DEFAULT_EDIT_MODEL = "edit-pro"

# The model PixAI runs a hand/face Fix on -- the same CHAT model the Edit card calls
# Reference Pro. A Fix submit (POST /v2/task/fixer, just {mediaId, boxes}) never names a
# model, so this is how the Fix paths that DO need one -- pricing the request, and labelling
# the collected output's Model instead of leaving an em-dash -- get it without a second
# hardcoded copy of the id. Reference Pro is known-flaky; a Fix's intermittent failures are
# that model, not this app.
FIXER_MODEL_ID = EDIT_MODELS["reference-pro"]["model_id"]


def edit_model_id(key):
    """model_id for an Edit-card model key ('edit-pro'/'reference-pro'); '' if unknown."""
    return (EDIT_MODELS.get((key or "").strip()) or {}).get("model_id", "")


def edit_model_by_id(model_id):
    """The EDIT_MODELS spec whose model_id matches `model_id`, else None -- used to clamp a
    submitted edit's resolution/quality/aspect to what that model actually supports."""
    mid = str(model_id or "")
    for spec in EDIT_MODELS.values():
        if spec.get("model_id") == mid:
            return spec
    return None


def clamp_edit_config(model_id, resolution, quality, aspect):
    """Snap an edit's (resolution, quality, aspect) to the resolved model's real capabilities,
    so NO path -- preset, stale UI, old client -- can send an option the model rejects (the
    preset-with-Reference-Pro bug). Unknown models pass through unchanged. Returns the tuple."""
    spec = edit_model_by_id(model_id)
    if not spec:
        return resolution, quality, aspect
    if not spec["qualities"]:
        quality = ""                                   # model exposes no quality knob
    elif quality and quality not in spec["qualities"]:
        quality = spec["default"].get("quality", "")
    if resolution not in spec["resolutions"]:
        resolution = spec["default"]["resolution"]
    if aspect not in spec["aspects"]:
        aspect = spec["default"]["aspect"]
    return resolution, quality, aspect


def upload_media(session, path, media_type="IMAGE"):
    """Upload a LOCAL image file to PixAI and return its media_id.

    Three steps (verified from the live app): (1) uploadMedia({type,provider:"S3"})
    returns a presigned S3 `uploadUrl` + an `externalId`; (2) PUT the file bytes to
    that URL (raw S3, NOT our API session -- so the Bearer never leaks to S3);
    (3) uploadMedia({type,provider,externalId}) registers the object and returns the
    `mediaId`. Lets local images feed edit / i2v / reference flows. Uploading is free.
    """
    p = Path(path)
    if not p.is_file():
        raise PixAIError("upload: file not found: {}".format(p))
    data = p.read_bytes()

    # Both uploadMedia legs go through gql_mutate (single attempt). Step 3 is the one that
    # must never double-apply -- re-registering the same externalId after a lost response
    # can leave a second media object on the account -- and step 1 takes the same treatment
    # so the whole handshake reads one way; a failed upload costs nothing to re-run.
    r1 = gql_mutate(session, _UPLOAD_MEDIA_MUT,
                    {"input": {"type": media_type, "provider": "S3"}})
    u = (r1 or {}).get("uploadMedia") or {}
    upload_url, external_id = u.get("uploadUrl"), u.get("externalId")
    if not upload_url or not external_id:
        raise PixAIError("upload: no presigned url/externalId returned: "
                         + json.dumps(r1)[:300])

    ct = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    try:
        put = requests.put(upload_url, data=data, headers={"Content-Type": ct}, timeout=180)
    except requests.exceptions.SSLError:
        raise PixAIError(_ssl_help())
    if put.status_code not in (200, 201, 204):
        raise PixAIError("upload: S3 PUT failed (HTTP {}): {}".format(
            put.status_code, (put.text or "")[:200]))

    r3 = gql_mutate(session, _UPLOAD_MEDIA_MUT,
                    {"input": {"type": media_type, "provider": "S3",
                               "externalId": external_id}})
    reg = (r3 or {}).get("uploadMedia") or {}
    mid = reg.get("mediaId") or (reg.get("media") or {}).get("id")
    if not mid:
        raise PixAIError("upload: registration returned no mediaId: " + json.dumps(r3)[:300])
    return str(mid)


def _is_local_source(src):
    """A source is a local file to upload (vs an existing catalog media_id) when it
    points at a real file on disk. media_ids are big numeric strings; paths aren't."""
    try:
        return bool(src) and os.path.isfile(src)
    except (OSError, ValueError):
        return False


def build_chat_edit_parameters(prompt, media_ids, model_id=EDIT_PRO_MODEL_ID, *,
                               resolution="1K", aspect_ratio="3:4", quality="medium",
                               kaisuuken_id="", scene_id=""):
    """Build createGenerationTask's `parameters` for an instruct edit (the `chat`
    block), verified against a real Edit-Pro submit (2026-07-01). `media_ids` is one
    or more source media_ids (an array => multi-image reference editing); the first
    is also sent as `mediaId`. `scene_id` marks a Toolbox PRESET (banked 2026-07-04
    from task 2030050946353349700: a preset = this same chat block + a canned prompt
    + top-level sceneId, e.g. "character-card"; Edit cards match it either way).
    NOTE: `kaisuuken_id` defaults to "" and is only attached (below) when the caller
    passes one explicitly -- same opt-in shape as the other build_*_parameters builders.
    Without one the server charges credits, so this still stays behind --confirm like
    all spend paths.
    """
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    if not ids:
        raise PixAIError("edit needs at least one source media_id")
    params = {"chat": {
        "prompts": prompt or "",
        "mediaId": ids[0],
        "mediaIds": ids,
        "modelId": str(model_id or EDIT_PRO_MODEL_ID),
        # quality is omitted when empty -- Reference Pro exposes no quality option, so sending
        # one would be a bogus knob; Edit Pro still sends low/medium/high.
        "modelConfig": dict({"resolution": resolution, "aspectRatio": aspect_ratio},
                            **({"quality": quality} if quality else {})),
    }}
    if scene_id:
        params["sceneId"] = str(scene_id)
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)   # spend a free card instead of credits
    return params


def _edit_config_from_args(args):
    """Pull the modelConfig knobs (with defaults) out of CLI/GUI args."""
    model_id = getattr(args, "edit_model", "") or EDIT_PRO_MODEL_ID
    resolution = getattr(args, "edit_resolution", "") or "1K"
    aspect_ratio = getattr(args, "edit_aspect", "") or "3:4"
    quality = getattr(args, "edit_quality", "") or "medium"
    # Same guard the web /api/edit path already runs (_edit_params_from_payload ->
    # clamp_edit_config) -- without it the CLI can submit a resolution/quality/aspect
    # the resolved model doesn't actually support (e.g. the 1K/medium defaults above,
    # sent to reference-pro, which only exposes 2K/4K and no quality knob at all), an
    # invalid combo on a credit-spend path.
    resolution, quality, aspect_ratio = clamp_edit_config(model_id, resolution, quality, aspect_ratio)
    return dict(
        model_id=model_id,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        quality=quality,
        kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
    )


def _poll_task_status(session, task_id, timeout, *, interval=3, label="task",
                      fail_noun="task"):
    """Poll `_GEN_STATUS` until the task completes, fails, or times out. Returns the
    server-authoritative `paidCredit` (or None) and prints it as the actual cost on
    completion. Raises PixAIError on failure/timeout. Shared by the generate / video /
    edit submit paths so their poll behaviour can't drift."""
    deadline = time.time() + timeout
    paid_credit = None
    started_at, last_status = None, ""
    while time.time() < deadline:
        task = (gql_adhoc(session, _GEN_STATUS, {"id": task_id}) or {}).get("task") or {}
        status = str(task.get("status", "")).lower()
        last_status = status or last_status
        started_at = task.get("startedAt") or started_at
        if task.get("paidCredit") is not None:
            paid_credit = task.get("paidCredit")     # server-authoritative actual cost
        vlog("{} poll: {}{}".format(label, status or "(unknown)",
                                    "" if started_at else " (not started yet)"))
        if status in ("completed", "succeeded", "success", "done"):
            if paid_credit is not None:
                print("  actual cost: {:,} credits".format(int(paid_credit)))
            return paid_credit
        if status in ("failed", "error", "cancelled", "canceled"):
            raise PixAIError("{} ended with status: {}{}".format(
                fail_noun, status, _pixai_reason_suffix(task)))
        time.sleep(interval)
    if _never_dispatched(last_status, started_at):
        raise PixAIError(
            "{} was accepted by PixAI but NEVER started. After {}s it is still queued "
            "with no start time, so no worker ever picked it up -- waiting longer will "
            "not help, and --task-id recovery has nothing to fetch. PixAI reaps an "
            "unstarted task at about 60 minutes and issues a refund then, so the credits "
            "should come back on their own; check your credit history if they don't. "
            "(task {})".format(fail_noun, timeout, task_id))
    raise PixAIError(
        "stopped waiting after {}s, but the task is STILL RUNNING on PixAI (task {}). "
        "Nothing is lost: recover it free once it finishes with --task-id {} "
        "(or it arrives in your next --update).".format(timeout, task_id, task_id))


def _task_failure_reason(outputs):
    """PixAI's own explanation for a failure, from whichever key it used this time.

    It does NOT use one key. A task it cancelled says `{"reason": "waiting timeout"}`, while a
    task its model refused says `{"finish_reason": "ERROR", "modelResponse": [],
    "failureMessage": "Provider refused to answer", "failure_reason":
    "PROVIDER_REFUSE_ANSWER"}`. Reading only `reason` made three real, fully-explained
    content refusals look unexplained, and they were written up as model flakiness -- the
    opposite advice from what the payload actually said.

    Preference order is deliberate: the human sentence first, then the enum (still far better
    than nothing), then the cancelled-task key. `finish_reason` is skipped -- "ERROR" is a
    category, not information.

    NOTE the projection trap: this is the GRAPHQL `outputs`. REST `/v2/task/{id}` returns a
    DIFFERENT `outputs` ({mediaIds, mediaUrls}) with no failure detail at all, so a probe
    against REST will report no reason exists when one does."""
    if not isinstance(outputs, dict):
        return ""
    for key in ("failureMessage", "failure_reason", "reason"):
        val = outputs.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def describe_failure(status, reason="", started=True):
    """A failure message a person can act on, from what PixAI actually tells us.

    Their status string for a failed generation is genuinely just "failed", and `outputs`
    frequently comes back empty, so faithfully forwarding their words leaves the user with
    one useless word -- which is exactly what the owner saw on three consecutive hand-fix
    attempts (2026-07-25): status `failed`, error `failed`, nothing else. Forwarding is
    still right when they DO explain themselves; this only fills the silence.

    Three distinct cases, because they send you to three different places:
      - reason given      -> lead with THEIR words; ours must never bury them.
      - never dispatched  -> it did not "fail to render", no worker ever took it. Saying
                             otherwise sends someone off debugging a prompt that was never
                             read. These are reaped and refunded at ~60 minutes.
      - ran, then failed  -> their model errored. Nothing to fix in the request, and the
                             credits come back on their own (observed: charged and refunded
                             within 2-3 seconds), which is the first thing anyone wants to
                             know.

    Their reason and our explanation are ADDITIVE, not either/or. "waiting timeout" is
    their jargon: accurate, and meaningless to anyone who does not already know it means
    no worker ever picked the task up. Lead with their words, then say what happened."""
    status = str(status or "failed").strip() or "failed"
    reason = str(reason or "").strip()
    parts = [status]
    if reason:
        parts.append("PixAI's reason: {}".format(reason))
        # A provider/content refusal is the moderator declining the content, not a system
        # fault. Saying so turns a dead end into a next step -- the fix is rewording, and
        # without this the message reads like something is broken and needs debugging.
        if "refus" in reason.lower() or "policy" in reason.lower():
            parts.append("That is a content refusal, not a fault: rewording the prompt "
                         "usually clears it. Nothing was charged — refused generations "
                         "are refunded.")
    if not started:
        parts.append("It was queued but never started, so nothing rendered — unstarted "
                     "tasks are cancelled and refunded after about an hour.")
    elif not reason:
        parts.append("PixAI ran this and it failed without giving a reason. Failed "
                     "generations are refunded automatically, so the credits come back.")
    return " — ".join(parts)


def _pixai_reason_suffix(task):
    """PixAI's own explanation for a terminal status, from `outputs.reason` (e.g.
    "waiting timeout"). Surfaced because a bare "cancelled" reads as though the USER
    cancelled something -- the owner saw exactly that five times and had no way to know
    PixAI had timed the task out of its own queue."""
    reason = _task_failure_reason((task or {}).get("outputs"))
    return " (PixAI's reason: {})".format(reason) if reason else ""


def _never_dispatched(status, started_at):
    """True when PixAI accepted a task, queued it, and never assigned it a worker.

    Keys on `startedAt` being absent AND a POSITIVE observation of a pre-run status. Two
    deliberate exclusions, both of which would otherwise produce a confident lie:
      - `running` without a `startedAt` has obviously started, so it stays on the
        reassuring "still running, recover it free" timeout path.
      - an EMPTY status means we never actually observed the task (e.g. a zero/expired
        timeout that never entered the poll loop). "Not observed" is not "not dispatched",
        so that also stays on the reassuring path -- claiming a task is dead because we
        never looked at it is the same class of error as the message this fix removes."""
    return not started_at and str(status or "").lower() in ("waiting", "pending", "queued")


def _maybe_dump_params(args, result):
    """If --dump-params is set, print the task's full submit `parameters` (the exact
    shape PixAI received). Handy for banking a param shape off a recovered --task-id
    without a live browser capture. Read-only; prints nothing otherwise.

    Also prints the task's own status. Found needed 2026-07-21: recovering a task is
    almost always done BECAUSE something looked wrong, and the params alone can't say
    whether PixAI ever actually ran it -- this used to print only what was submitted,
    never what happened to it, so the one moment you most want to know the outcome was
    exactly when this told you nothing about it."""
    if not getattr(args, "dump_params", False):
        return
    params = (result or {}).get("parameters")
    print("=== task parameters (full submit shape) ===")
    print(json.dumps(params if params is not None else result, indent=2, ensure_ascii=False))
    print("=== end parameters ===")
    status = (result or {}).get("status")
    if status:
        print("task status: {}".format(status))


def _outputs_or_raise(result, found, empty_message):
    """Common tail for every 'download a completed task's outputs' function: raise
    EmptyOutputsError when there is nothing to download, with a message that matches
    what actually happened rather than always claiming the task 'completed'.

    Found 2026-07-21 chasing a real report of edit jobs that looked like they'd never
    reached PixAI. They had: a real task id was issued (the spend already happened),
    but PixAI's own status for the task was 'failed' -- and every one of the four call
    sites below said 'task completed but no media ids found' regardless, because none
    of them looked at `result["status"]` before writing the message. For a task PixAI
    itself marked failed, 'completed' is not almost-right, it's the opposite of what
    happened, and it is exactly the kind of thing that reads as a tool bug instead of
    a PixAI-side rejection.

    `empty_message` is the ORIGINAL message, used verbatim for the case it was always
    right about -- a task that is genuinely done with empty outputs (e.g. silently
    content-filtered). Only the newly-distinguished failed/cancelled/rejected case gets
    different text; nothing about the genuinely-empty case changes."""
    if found:
        return
    raw = str((result or {}).get("status") or "").lower()
    if raw in _GEN_FAIL:
        raise EmptyOutputsError(
            "PixAI reported this task as '{}' -- it did not complete, so there is "
            "nothing to recover. Check pixai.art for why, or resubmit.".format(raw))
    raise EmptyOutputsError(empty_message)


def run_generate(args):
    """Create images via PixAI (createGenerationTask), poll to completion, download
    the results into the backup, and catalog them as source='api'. GUARDED: without
    --confirm it only prints a preview (spends no credits). Submits through
    submit_generation() (and so through gql_mutate) + the shared session/download/
    catalog plumbing."""
    out = Path(args.out)
    params = _gen_parameters(args)
    existing_task = (getattr(args, "task_id", "") or "").strip()

    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask (PREVIEW -- no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        _preview_card_note(args, params)
        print("\nThis would SPEND PixAI credits (unless free above). Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # generation can seed a fresh backup
    session = _make_session(getattr(args, "token", None))
    thumb_dir = out / "gallery" / "thumbs"
    from moonglade_gallery import make_thumbnail

    if existing_task:
        # Recover an already-created generation by id (no new credits). Tool/API
        # generations don't enter listUserTaskSummaries, so --update can't fetch
        # them -- this is how you reclaim a stranded paid generation.
        task_id = existing_task
        print("Fetching existing task (no credits):", task_id)
    else:
        # submit_generation() now owns both the actual mutation and the inferenceProfile
        # retry (2026-07-24 -- shared with every other caller, including the web
        # /api/generate route), so this CLI runner just calls through it instead of
        # duplicating that logic. It still needs its OWN _check_read_only call here
        # though, before _apply_kaisuuken's free-card check: that's a real network call
        # that fires BEFORE submit_generation() is even reached below, so relying only on
        # the guard inside submit_generation() would let it through first under
        # READ_ONLY -- the exact bug _check_read_only's own docstring and
        # tests/test_read_only_cli_paths.py describe finding.
        _check_read_only("submit a generation (spends credits)")
        print("Submitting generation task...")
        _apply_kaisuuken(session, params, args)
        task_id = submit_generation(session, params)
        print("  task id:", task_id)

        _poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="generate", fail_noun="generation")

    # The Task type exposes its media under `outputs` (mediaId / batchMediaIds /
    # videos), NOT at the top level. getTaskById returns that whole object and is
    # already proven, so reuse it for the result rather than guessing an ad-hoc
    # selection set.
    result = task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    outputs = result.get("outputs") or {}
    # _task_image_media prefers outputs.batch[] (the real individual images) over
    # outputs.mediaId (the composite grid PixAI returns for any batchSize>1 task) --
    # reading mediaId/batchMediaIds directly here used to save only the grid and
    # silently drop every individual image on a multi-image generation (audit:
    # fail-open/unfiled-workflow-findings, 2026-07-21).
    media = _task_image_media(outputs)
    seeds = dict(media)
    mids = [mid for mid, _ in media]
    for v in outputs.get("videos") or []:
        if v.get("mediaId"):
            mids.append(str(v["mediaId"]))
    mids = list(dict.fromkeys(mids))
    _outputs_or_raise(result, mids, "task completed but no media ids found")

    # Prefer the task's actual metadata (authoritative, and the only source when
    # recovering by --task-id); fall back to the params we submitted.
    fm = extract_full_meta(result)

    def _pick(fm_key, *param_keys):
        if fm.get(fm_key):
            return str(fm[fm_key])
        for pk in param_keys:
            if params.get(pk):
                return str(params[pk])
        return ""

    img_dir = out / "images"
    rows, saved = [], []
    for mid in mids:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        prompt = fm.get("prompt_full") or params.get("prompts", "")
        stem = img_dir / build_stem_name(prompt, task_id, mid,
                                         getattr(args, "name_length", 60),
                                         getattr(args, "name_sep", "_"))
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = {f: "" for f in CATALOG_FIELDS}
        full.update({
            "task_id": str(task_id), "media_id": mid,
            "filename": str(path.relative_to(out)).replace("\\", "/"),
            "url": url, "source": "api", "status": "completed",
            "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_full": prompt,
            "prompt_preview": (prompt or "")[:100],
            "negative_prompt": _pick("negative_prompt", "negativePrompts"),
            "seed": seeds.get(mid) or _pick("seed", "seed"),   # per-image seed on a batch
            "steps": _pick("steps", "samplingSteps"),
            "cfg_scale": _pick("cfg_scale", "cfgScale"),
            "model_id": _pick("model_id", "modelId"),
            # Resolved here, not just in the backfill. extract_full_meta only fills
            # model_name for a CHAT task (from the local EDIT_MODELS table); every ordinary
            # generation left it blank, so every freshly captured image showed a raw
            # 19-digit model id on its detail page until a later --backfill-full-meta
            # happened to come past. model_name_gql is process-cached, so this is one call
            # per distinct model for the whole run, not one per image.
            "model_name": _resolved_model_name(session, fm, _pick("model_id", "modelId")),
            # Four fields extract_full_meta hands over that this row used to drop, so they
            # arrived blank on every live capture and only appeared once a
            # --backfill-full-meta came past -- which is the manual step the whole
            # capture-it-as-it-happens path exists to remove. `loras` in particular is
            # always "" out of extract_full_meta by design: it documents that the CALLER
            # resolves it, the backfill did, and this did not.
            "sampler": fm.get("sampler", ""),
            "natural_prompt": fm.get("natural_prompt", ""),
            "clip_skip": fm.get("clip_skip", ""),
            "loras": _resolved_loras(session, result),
            "paid_credit": _paid_credit_str(result),   # actual cost, task-level
            "width": str((info or {}).get("width") or params.get("width") or ""),
            "height": str((info or {}).get("height") or params.get("height") or ""),
        })
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))

    if rows:
        save_catalog(db_path, rows)
        if existing_task:
            try:      # Against the Void: a stranded task pulled back by id
                from moonglade_gallery import telem_bump
                telem_bump("recover_events", out_dir=out)
            except Exception:
                pass
    print("Generated + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved)}


def _download_video_task(session, result, task_id, out, args, params):
    """Download + catalog the video output(s) of a completed task. Shared by i2v (i2vPro)
    and reference-video (referenceVideo) -- reads outputs.videos + the submitted block
    generically. Returns the list of saved file paths."""
    outs, shared = video_outputs(result)
    _outputs_or_raise(result, outs, "video task completed but no video outputs found")
    detail = ((result or {}).get("outputs") or {}).get("detailParameters") or {}
    sent = (params.get("i2vPro") or params.get("referenceVideo") or {}) if isinstance(params, dict) else {}
    prompt = shared.get("prompt") or sent.get("prompts") or sent.get("prompt") or ""

    from moonglade_gallery import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    vdir = out / "videos"
    vdir.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    rows, saved = [], []
    for o in outs:
        vmid = o["video_media_id"]
        url = media_file_gql(session, vmid).get("fileUrl")
        if not url:
            print("  no file url for video", vmid)
            continue
        stem = vdir / build_stem_name(prompt, task_id, vmid, getattr(args, "name_length", 60), "_")
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = {f: "" for f in CATALOG_FIELDS}
        full.update({
            "task_id": str(task_id), "media_id": vmid,
            "filename": str(path.relative_to(out)).replace("\\", "/"),
            "url": url, "source": "api", "status": "completed", "is_video": "1",
            "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_full": prompt, "prompt_preview": (prompt or "")[:100],
            "negative_prompt": sent.get("negativePrompts", ""),
            "seed": str(o.get("seed") or ""),
            "poster_media_id": o.get("poster_media_id", ""),
            "paid_credit": _paid_credit_str(result),   # actual cost, task-level
            "video_duration": str(shared.get("duration") or sent.get("duration") or ""),
            "model_id": str(sent.get("model") or ""),
            "width": str(detail.get("width") or ""),
            "height": str(detail.get("height") or ""),
        })
        # Poster thumbnail is COSMETIC -- it must never block cataloging the finished video.
        # A transient Windows lock on the poster's temp file (WinError 32) used to raise from
        # download() right here, before rows.append below, so the clip was pulled to videos/
        # but never saved and the panel never showed it. A missing/failed thumb self-heals on
        # the next --rebuild-thumbs / --sync.
        pm = o.get("poster_media_id")
        thumb_path = thumb_dir / "{}.jpg".format(vmid)
        try:
            if pm:
                purl, _pi = resolve_media(session, pm)
                if purl:
                    ptmp = out / "gallery" / "_postertmp"
                    ptmp.mkdir(parents=True, exist_ok=True)
                    st, pp = download(session, purl, ptmp / str(pm))
                    if st in ("ok", "skip") and pp:
                        make_thumbnail(pp, thumb_path)
                        try:
                            pp.unlink()              # don't leave poster temps to accumulate / be re-locked
                        except OSError:
                            pass
            # Poster-less (or poster fetch failed): ffmpeg the mp4's first frame, so the
            # gallery never shows a blank tile waiting on a later sync. Matches _do_task /
            # run_import_local; no-op if ffmpeg isn't on PATH.
            if not thumb_path.exists():
                video_poster_thumb(path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the catalog
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(vmid, e))
        video_faststart(path)                        # iOS needs moov at the front to stream
        rows.append(full)
        saved.append(str(path))
    if rows:
        save_catalog(db_path, rows)
    return saved


def _task_image_media(outputs):
    """The REAL output images of a completed image task as [(media_id, seed)], newest logic:
    a batchSize>1 task stores a 2x2 COMPOSITE GRID under outputs.mediaId and the INDIVIDUAL
    images under outputs.batch[] -- so we take the individuals (the actual generations), never
    the grid. batchSize==1 / legacy tasks fall back to outputs.mediaId (+ legacy batchMediaIds).
    Per-image seed comes from batch[].seed, else the shared outputs.seed. Deduped, order-kept.

    This is why batch generations were previously under-captured: the old path read
    outputs.batchMediaIds (which is null on modern tasks) and saved only the grid."""
    outputs = outputs or {}
    batch = outputs.get("batch") or []
    shared_seed = str(outputs.get("seed") or "")
    pairs = []
    if batch:                                        # modern batch: save the individuals
        for b in batch:
            mid = str((b or {}).get("mediaId") or "")
            if mid:
                pairs.append((mid, str((b or {}).get("seed") or shared_seed)))
    else:                                            # single image (or legacy shape)
        if outputs.get("mediaId"):
            pairs.append((str(outputs["mediaId"]), shared_seed))
        for m in outputs.get("batchMediaIds") or []:
            pairs.append((str(m), shared_seed))
    seen, uniq = set(), []
    for mid, sd in pairs:
        if mid and mid not in seen:
            seen.add(mid)
            uniq.append((mid, sd))
    return uniq


def _task_detail_query(session, task_id):
    """getTaskById via the persisted hash when available, else the ad-hoc `task(id:)` query
    (same parameters+outputs shape -- verified). Despite the name, this ad-hoc-fallback
    resilience is NOT shared by --full-meta / --backfill-full-meta: run_backfill_full_meta
    and run_download's --full-meta branch both call task_detail_gql directly, bypassing
    this function entirely (run_backfill_full_meta even raises PixAIError itself when
    TASK_DETAIL_HASH is empty -- see its own guard, unconditional). The only real caller
    is collect_generation (the --task-id / --dump-params recovery path), which is the one
    place that actually gets this fallback. Rewiring the two CLI callers to use it too
    would be a real behavior change -- not done here."""
    if TASK_DETAIL_HASH:
        return task_detail_gql(session, task_id)
    # paidCredit rides along so the fallback path stores the actual cost too (the
    # field is proven safe ad-hoc -- _GEN_STATUS already selects it on every poll).
    q = "query($id: ID!) { task(id: $id) { id status createdAt parameters outputs paidCredit } }"
    return (gql_adhoc(session, q, {"id": str(task_id)}) or {}).get("task")


def _fix_source_label(task, out):
    """The readable half of a Fix output's filename: the prompt of the SOURCE image the Fix
    ran on, looked up in this backup's own catalog by media_id, falling back to that
    media_id when the source isn't ours (a fresh upload) and to '' when the task names no
    source at all. Naming a Fix after the image it repaired is what makes a folder of them
    browsable, and it lands the two files next to each other in a sorted listing.

    Fails soft: an unreadable catalog costs the name its readable half, never the download."""
    params = (task or {}).get("parameters") or {}
    chat = params.get("chat") if isinstance(params.get("chat"), dict) else {}
    src = str(chat.get("mediaId") or params.get("mediaId") or "")
    if not src:
        return ""
    try:
        row = next((r for r in load_catalog(Path(out) / "catalog.db")
                    if r.get("media_id") == src), None)
    except Exception:                      # noqa: BLE001 -- a naming nicety, never a blocker
        row = None
    label = ((row or {}).get("prompt_preview") or (row or {}).get("prompt_full") or "").strip()
    return label or src


def _download_image_task(session, result, task_id, out, args, prompt="", model_name=""):
    """Download + catalog the image output(s) of a completed task. Saves the individual batch
    images (not the composite grid) via _task_image_media, storing each image's own seed.
    resolve_media -> download -> catalog as source='api'. Returns the saved file paths."""
    outputs = result.get("outputs") or {}
    media = _task_image_media(outputs)
    _outputs_or_raise(result, media, "task completed but no media ids found")
    from moonglade_gallery import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    img_dir = out / "images"
    db_path = out / "catalog.db"
    # A hand/face Fix is the one task family whose `prompts` is PixAI's own fixed template,
    # so build_stem_name would give every Fix ever collected the same unreadable name --
    # build_fix_stem_name names it from the source image + a fix-face/fix-hand marker
    # instead. Detected here rather than at the call sites so recovering a Fix by --task-id
    # names it the same way the web collect does. NEW OUTPUT ONLY: nothing renames a file
    # already on disk.
    fx = fixer_block(result)
    fix_label = _fix_source_label(result, out) if fx is not None else ""
    fm = extract_full_meta(result)
    rows, saved = [], []
    for mid, seed in media:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        name_len = getattr(args, "name_length", 60)
        name_sep = getattr(args, "name_sep", "_")
        if fx is not None:
            stem = img_dir / build_fix_stem_name(fix_label, fx.get("boxes"), task_id, mid,
                                                 name_len, name_sep)
        else:
            stem = img_dir / build_stem_name(prompt, task_id, mid, name_len, name_sep)
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = {f: "" for f in CATALOG_FIELDS}
        full.update({
            "task_id": str(task_id), "media_id": mid, "seed": seed,
            "filename": str(path.relative_to(out)).replace("\\", "/"),
            "url": url, "source": "api", "status": "completed",
            "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_full": prompt, "prompt_preview": (prompt or "")[:100],
            # Everything extract_full_meta resolved from the task. This row used to write
            # only the model id, so a generation captured as it happened landed with an
            # em-dash for Steps, Sampler, CFG, LoRAs and the rest -- not because PixAI never
            # recorded them, but because they were never written down, and only a later
            # --backfill-full-meta filled them in. That backfill is the manual step
            # capturing-as-it-happens exists to remove.
            #
            # An em-dash remains the honest answer where the task genuinely recorded
            # nothing: a CHAT task (Edit/Fix) has no detailParameters at all, so these
            # resolve to "" and render as before. An explicit model_name from the caller
            # still wins over the looked-up one.
            "model_id": fm.get("model_id", ""),
            "model_name": model_name or _resolved_model_name(session, fm,
                                                             fm.get("model_id", "")),
            "steps": fm.get("steps", ""),
            "sampler": fm.get("sampler", ""),
            "cfg_scale": fm.get("cfg_scale", ""),
            "negative_prompt": fm.get("negative_prompt", ""),
            "natural_prompt": fm.get("natural_prompt", ""),
            "clip_skip": fm.get("clip_skip", ""),
            "loras": _resolved_loras(session, result),
            "paid_credit": _paid_credit_str(result),   # actual cost, task-level
            "width": str((info or {}).get("width") or ""),
            "height": str((info or {}).get("height") or ""),
        })
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))
    if rows:
        save_catalog(db_path, rows)
    return saved


def _bump_card_use(params):
    """Thrifty Archivist: count the free card only once its task ACTUALLY submitted
    (a card attached to a rejected submit was never spent). Fail-soft no-op."""
    if isinstance(params, dict) and params.get("kaisuukenId"):
        try:
            from moonglade_gallery import telem_bump
            telem_bump("free_cards_applied")
        except Exception:
            pass


def submit_generation(session, params):
    """Submit a createGenerationTask and return the task id immediately -- no wait, no
    download. The card (if any) must already be attached to `params`. Raises on no id.

    inferenceProfile (the Mode quality setting) is MODEL-TYPE-SPECIFIC on PixAI's side --
    some model types only accept lite/standard, others pro/ultra, and an unsupported value
    gets the whole submit REJECTED with a raw GraphQL error. A rejected submit costs no
    credits, so on that specific rejection this drops inferenceProfile and retries once on
    the model's default instead of failing the call outright. This used to be a one-off
    try/except living only inside the CLI's run_generate; moved here 2026-07-24 so every
    caller gets it for free -- the web /api/generate, /api/edit and /api/loom/generate
    routes, and run_generate itself, which now just calls through here (see its own
    comment). Only params built by _gen_parameters ever carry inferenceProfile, so this
    is a silent no-op for every other caller (edit/enhance/video params never set it).

    The submit goes through `gql_mutate`, NOT `gql_adhoc`: a createGenerationTask that is
    transparently re-POSTed after a lost response is a second generation and a second
    charge. The inferenceProfile re-submit below is a different thing and is safe -- it
    only fires on a PixAIError, which means PixAI answered with a GraphQL error and
    REJECTED the task, so there is nothing created and nothing charged to duplicate."""
    _check_read_only("submit a generation (spends credits)")
    try:
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
    except PixAIError as e:
        if "inferenceProfile" in str(e) and "inferenceProfile" in params:
            dropped = params.pop("inferenceProfile")
            print("  mode '{}' not supported by this model; retrying on the "
                  "model's default...".format(dropped))
            created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
        else:
            raise
    task_id = (created.get("createGenerationTask") or {}).get("id")
    if not task_id:
        raise PixAIError("no task id returned: " + json.dumps(created)[:200])
    _bump_card_use(params)
    return str(task_id)


def clean_fix_boxes(boxes):
    """Filter + normalize hand/face Fix boxes into what POST /v2/task/fixer accepts: tag
    'hand'|'face' (lowercased), non-negative integer origin, positive size, at most 20.
    Anything else is dropped, so a stale or malformed client box can't reach the server.

    Shared by submit_fixer and build_fixer_price_parameters deliberately: the shape that
    gets PRICED has to be the shape that gets SUBMITTED, or the cost badge would quote a
    request PixAI never receives."""
    clean = []
    for b in (boxes or []):
        tag = str((b or {}).get("tag") or "").lower()
        if tag not in ("hand", "face"):
            continue
        try:
            x, y = max(0, int(b["x"])), max(0, int(b["y"]))
            w, h = int(b["width"]), int(b["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            clean.append({"x": x, "y": y, "width": w, "height": h, "tag": tag})
    return clean[:20]


def build_fixer_price_parameters(media_id, boxes, *, model_id=None):
    """createGenerationTask-shaped `parameters` for a hand/face Fix, built ONLY to hand to
    price_task(). NOTHING submits these -- a Fix is submitted by submit_fixer, which never
    sees them.

    A Fix goes out as a REST body of just {mediaId, boxes}, and that body is not priceable.
    What PixAI's server builds from it is a taskKind=chat generation carrying a `chat.fixer`
    block, and GET /v2/task-price DOES price that: measured 2026-07-25 it answers a flat
    8000 for a Fix, invariant to box count (1 / 3 / 10), canvas size and priority. Drop the
    chat block from the same call and it falls back to the 1200 base floor -- the block, not
    the scalars, is what carries the cost, which is why this synthesizes one instead of
    passing the REST body through. Nothing here is invented: no width/height, no priority,
    no prompt, because the measurement showed none of them move the number."""
    clean = clean_fix_boxes(boxes)
    if not clean:
        raise PixAIError("fixer needs at least one hand/face box")
    mid = str(media_id)
    model = str(model_id or FIXER_MODEL_ID)
    return {"mediaId": mid, "modelId": model,
            "chat": {"fixer": {"boxes": clean}, "mediaId": mid, "modelId": model}}


def submit_fixer(session, media_id, boxes):
    """Submit a hand/face fixer task via POST /v2/task/fixer -> task id (poll it like any
    generation). `boxes` = [{x, y, width, height, tag}] in ORIGINAL-image pixel coords, tag
    'hand' | 'face' (<=20). Builds a mask from the boxes and repairs those regions. Raises."""
    _check_read_only("submit a hand/face fix (spends credits)")
    clean = clean_fix_boxes(boxes)
    if not clean:
        raise PixAIError("fixer needs at least one hand/face box")
    data = _rest_post(session, "/task/fixer",
                      {"mediaId": str(media_id), "boxes": clean}) or {}
    tid = data.get("id")
    if not tid:
        raise PixAIError("fixer: no task id returned: " + json.dumps(data)[:200])
    return str(tid)


_GEN_DONE = ("completed", "success", "succeeded", "done", "finished")
_GEN_FAIL = ("failed", "error", "cancelled", "canceled", "rejected")


def generation_status(session, task_id):
    """One status check for a task -> {status, phase, paid_credit, started, reason}.
    `phase` normalizes the raw status into 'running' | 'done' | 'failed' for the async
    poller. Read-only.

    `started` and `reason` exist because 'what' without 'why' is how five of the owner's
    generations died unnoticed over four days (2026-07-21..24):
      - `started` is False until PixAI actually assigns a worker. A task it accepted,
        queued and never dispatched sits at a NON-TERMINAL status for ~60 minutes before
        being reaped, so on status alone it is indistinguishable from real work and shows
        as an indefinite spinner. This is the only field that tells them apart.
      - `reason` is PixAI's own explanation from `outputs.reason` (e.g. "waiting
        timeout"). Without it a caller can only report "cancelled", which reads as though
        the USER cancelled something they never started.
    Callers that only want the original three keys are unaffected -- those are unchanged."""
    d = gql_adhoc(session, _GEN_STATUS, {"id": str(task_id)}) or {}
    t = d.get("task") or {}
    raw = (t.get("status") or "").lower()
    phase = ("done" if raw in _GEN_DONE else
             "failed" if raw in _GEN_FAIL else "running")
    return {"status": t.get("status") or "", "phase": phase, "paid_credit": t.get("paidCredit"),
            "started": bool(t.get("startedAt")),
            "reason": _task_failure_reason(t.get("outputs"))}


def _resolved_loras(session, task):
    """The task's LoRAs as a readable string, for a row being catalogued live.

    extract_full_meta returns `loras: ""` on purpose and documents that the caller fills it;
    --backfill-full-meta does, and the live capture did not, so a generation's LoRAs were
    blank until a backfill happened past. Resolution is name lookups behind model_name_gql's
    process cache, so a batch costs one call per distinct LoRA at most. A failure costs the
    label, never the row.
    """
    try:
        return resolve_loras(session, task) or ""
    except Exception:                                  # noqa: BLE001
        return ""


def _resolved_model_name(session, fm, model_id):
    """The model's human-readable name for a row being catalogued live.

    extract_full_meta sets model_name only for a chat task (Edit/Fix, resolved locally from
    EDIT_MODELS); for an ordinary generation it is blank and the caller is expected to fill
    it -- which the backfill does and the live capture did not. Falls back to whatever
    extract_full_meta had, then to blank, so a lookup failure costs the label and never the
    row.
    """
    have = str((fm or {}).get("model_name") or "").strip()
    if have:
        return have
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    try:
        return model_name_gql(session, mid) or ""
    except Exception:                                  # noqa: BLE001
        return ""


def collect_generation(session, task_id, out_dir, *, name_length=60, name_sep="_"):
    """Download + catalog a COMPLETED task's output(s) into out_dir -> {media_ids, saved,
    is_video}. Auto-detects video (outputs.videos) vs image and uses the matching shared
    downloader. Call only once status is 'done'."""
    from types import SimpleNamespace
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    init_db(out / "catalog.db")
    result = _task_detail_query(session, task_id) or {}
    a = SimpleNamespace(name_length=name_length, name_sep=name_sep)
    vouts, _shared = video_outputs(result)
    if vouts:
        saved = _download_video_task(session, result, task_id, out, a, {})
        mids = [str(o["video_media_id"]) for o in vouts if o.get("video_media_id")]
        dur = probe_video_duration(saved[0]) if saved else None   # real clip length for the reel
        return {"media_ids": mids, "saved": len(saved), "is_video": True, "duration": dur}
    fm = extract_full_meta(result)
    saved = _download_image_task(session, result, task_id, out, a, prompt=fm.get("prompt_full", ""))
    # the real images (batch individuals, not the composite grid)
    mids = [mid for mid, _seed in _task_image_media(result.get("outputs") or {})]
    return {"media_ids": mids, "saved": len(saved), "is_video": False}


def web_generate(session, params, out_dir, *, name_length=60, name_sep="_", poll_timeout=240):
    """Synchronous submit -> wait -> download+catalog (used by tests / any blocking caller).
    The async gallery routes use submit_generation + generation_status + collect_generation
    instead. Returns {task_id, media_ids, saved, paid_credit}."""
    task_id = submit_generation(session, params)
    paid = _poll_task_status(session, task_id, poll_timeout, interval=3,
                             label="generate", fail_noun="generation")
    got = collect_generation(session, task_id, out_dir,
                             name_length=name_length, name_sep=name_sep)
    return {"task_id": task_id, "media_ids": got["media_ids"],
            "saved": got["saved"], "paid_credit": paid}


def run_generate_video(args):
    """Create an image-to-video clip via PixAI (createGenerationTask + i2vPro params),
    poll to completion, download the mp4 into videos/, and catalog it (source='api',
    is_video='1'). GUARDED: without --confirm it only PREVIEWS (spends nothing). Video
    is expensive (~27.5k credits for a 5s V4.0 clip), so the preview shouts the cost.
    Reuses the same submit/poll as images and the same video download as --sync-videos."""
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    if not existing_task and not (getattr(args, "image", "") or "").strip():
        raise PixAIError("--generate-video needs --image <media_id> (a catalog image to animate).")
    params = _gen_video_parameters(args)

    if not existing_task and not getattr(args, "confirm", False):
        i2v = params.get("i2vPro") or {}
        print("=== PixAI createGenerationTask -- VIDEO (PREVIEW, no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        print("\n*** VIDEO GENERATION IS EXPENSIVE ***")
        print("  model={}  mode={}  duration={}s{}{}".format(
            i2v.get("model"), i2v.get("mode"), i2v.get("duration"),
            "  +audio" if i2v.get("generateAudio") else "",
            "  (first/last-frame)" if i2v.get("tailMediaId") else ""))
        print("  A V4.0 5s clip costs ~27,500 credits. Re-run with --confirm to submit.")
        _preview_card_note(args, params)
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))
    vdir = out / "videos"
    vdir.mkdir(parents=True, exist_ok=True)

    if existing_task:
        task_id = existing_task
        print("Fetching existing video task (no credits):", task_id)
    else:
        _check_read_only("submit a video generation (spends credits)")
        print("Submitting VIDEO generation task (this spends credits)...")
        _apply_kaisuuken(session, params, args)
        # gql_mutate, never gql_adhoc: a re-POSTed createGenerationTask is a second
        # (expensive) video and a second charge -- see gql_mutate's docstring.
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
        task_id = (created.get("createGenerationTask") or {}).get("id")
        if not task_id:
            raise PixAIError("no task id returned: " + json.dumps(created)[:300])
        print("  task id:", task_id)
        _bump_card_use(params)
        _poll_task_status(session, task_id, getattr(args, "poll_timeout", 600),
                          interval=5, label="video", fail_noun="video generation")

    # Result: getTaskById -> outputs.videos -> fileUrl -> download mp4 (same as --sync-videos).
    result = task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    saved = _download_video_task(session, result, task_id, out, args, params)
    print("Generated + cataloged {} video(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "videos": len(saved)}


def _resolve_refs(session, items, media_type="IMAGE"):
    """Resolve reference sources (media_id or local file) to media_ids, uploading any
    local files. Used by reference-video on --confirm.

    `media_type` is the PixAI MediaType to register an uploaded local file under.
    Live-probed 2026-07-24: MediaType is a real GraphQL enum with exactly two members,
    IMAGE and VIDEO. Pass media_type=None for a ref kind that has no valid upload type
    (audio) -- a local file is then refused rather than mislabelled as an image.
    Existing media_ids pass through untouched regardless."""
    ids = []
    for s in items:
        if _is_local_source(s):
            if media_type is None:
                raise PixAIError(
                    "--ref-audio only takes a media id that already exists on PixAI, not a "
                    "local file ({}). PixAI's uploader accepts images and videos only, so "
                    "there is no way to upload a bare audio file. Workaround: put the audio "
                    "into a video (even a still image with the audio track) and pass that "
                    "with --ref-video instead.".format(s))
            print("Uploading local reference:", s)
            ids.append(upload_media(session, s, media_type))
        else:
            ids.append(str(s))
    return ids


def run_reference_video(args):
    """Create a REFERENCE video (multi-image/video/audio reference) via createGenerationTask
    + a `referenceVideo` block. Refs (--ref-image/--ref-video/--ref-audio) are catalog
    media_ids OR local files (auto-uploaded on --confirm); reference them in --prompt as
    @image1/@video1/@audio1. Preview-only unless --confirm. Downloads + catalogs the mp4.
    --task-id recovers an existing reference-video task for free."""
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    imgs = [s for s in (getattr(args, "ref_image", None) or []) if s and str(s).strip()]
    vids = [s for s in (getattr(args, "ref_video", None) or []) if s and str(s).strip()]
    auds = [s for s in (getattr(args, "ref_audio", None) or []) if s and str(s).strip()]
    override = getattr(args, "params_json", "") or ""
    prompt = getattr(args, "prompt", "") or ""

    if not existing_task and not (imgs or vids or auds) and not override:
        raise PixAIError("--reference-video needs at least one --ref-image/--ref-video/"
                         "--ref-audio (a media_id or local file), or --task-id to recover.")

    is_private = (getattr(args, "vchannel", "private") == "private")

    def _build(img_ids, vid_ids, aud_ids):
        # Duration: default 5 (matches the argparse flag + the i2v sibling -- was 15 here,
        # a real 3x cost divergence, B10), snapped to PixAI's allowed lengths before use
        # for either preview or submit, same as the i2v CLI path (B9).
        return build_reference_video_parameters(
            prompt, image_media_ids=img_ids, video_media_ids=vid_ids, audio_media_ids=aud_ids,
            model=(getattr(args, "video_model", "") or "v4.0.1"),
            duration=_snap_video_duration(getattr(args, "duration", 5) or 5,
                                          (getattr(args, "video_model", "") or "v4.0.1")),
            mode=getattr(args, "vmode", None) or "professional",
            generate_audio=bool(getattr(args, "audio", False)),
            audio_language=getattr(args, "audio_language", None) or "english",
            is_private=is_private, kaisuuken_id=getattr(args, "kaisuuken_id", "") or "")

    # PREVIEW: no upload, no submit. Local files shown as placeholders.
    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask -- REFERENCE VIDEO (PREVIEW, no credits spent) ===")
        if override:
            print(json.dumps({"parameters": json.loads(override)}, indent=2))
        else:
            ph = lambda lst: [("<upload:{}>".format(s) if _is_local_source(s) else s) for s in lst]
            prev = _build(ph(imgs), ph(vids), ph(auds))
            print(json.dumps({"parameters": prev}, indent=2))
            _preview_card_note(args, prev)
        print("\n*** REFERENCE VIDEO IS EXPENSIVE *** (a 15s clip uses 3 V4.0 cards). "
              "Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))

    params = {}
    if existing_task:
        task_id = existing_task
        print("Fetching existing reference-video task (no credits):", task_id)
    else:
        # Checked before _resolve_refs, not just before the mutation: _resolve_refs
        # uploads any local ref files (upload_media -> a real gql_adhoc mutation) before
        # this function ever reaches the createGenerationTask call.
        _check_read_only("submit a reference video generation (spends credits)")
        if override:
            params = json.loads(override)
        else:
            params = _build(_resolve_refs(session, imgs, "IMAGE"),
                            _resolve_refs(session, vids, "VIDEO"),
                            _resolve_refs(session, auds, None))
        print("Submitting REFERENCE VIDEO task (spends credits unless a free card applies)...")
        _apply_kaisuuken(session, params, args)
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
        task_id = (created.get("createGenerationTask") or {}).get("id")
        if not task_id:
            raise PixAIError("no task id returned: " + json.dumps(created)[:300])
        print("  task id:", task_id)
        _bump_card_use(params)
        _poll_task_status(session, task_id, getattr(args, "poll_timeout", 600), interval=5,
                          label="reference video", fail_noun="reference video generation")

    result = task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    saved = _download_video_task(session, result, task_id, out, args, params)
    print("Generated + cataloged {} video(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "videos": len(saved)}


def run_upload(args):
    """Upload a local image to PixAI and print its media_id (the reusable primitive
    behind --edit-src file support). Free; spends nothing."""
    session = _make_session(getattr(args, "token", None))
    mid = upload_media(session, args.upload_file)
    print("Uploaded media_id:", mid)
    return {"media_id": mid}


def run_edit_image(args):
    """Instruct-edit an image via PixAI (createGenerationTask with a `chat` block):
    describe the change in --prompt and pass source(s) via --edit-src (a catalog
    media_id OR a local file, uploaded automatically; repeatable for multi-image
    reference). Poll -> download the result image(s) -> catalog as source='api'.
    GUARDED: without --confirm it only PREVIEWS (uploads nothing, spends nothing).
    --task-id recovers an already-created edit for free. Mirrors run_generate."""
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    srcs = [s for s in (getattr(args, "edit_src", None) or []) if s and str(s).strip()]
    override = getattr(args, "params_json", "") or ""
    prompt = getattr(args, "prompt", "") or ""
    cfg = _edit_config_from_args(args)

    if not existing_task and not srcs and not override:
        raise PixAIError("--edit-image needs --edit-src <media_id|file> (repeatable), "
                         "or --task-id to recover an existing edit.")

    # PREVIEW: no upload, no submit, no credits. Local files shown as placeholders.
    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask -- EDIT (PREVIEW, no credits spent) ===")
        if override:
            params = json.loads(override)
        else:
            preview_ids = [("<upload:{}>".format(s) if _is_local_source(s) else s)
                           for s in srcs] or ["<source>"]
            params = build_chat_edit_parameters(
                prompt, preview_ids, model_id=cfg["model_id"],
                resolution=cfg["resolution"], aspect_ratio=cfg["aspect_ratio"],
                quality=cfg["quality"], kaisuuken_id=cfg["kaisuuken_id"])
        print(json.dumps({"parameters": params}, indent=2))
        _preview_card_note(args, params)
        print("\nThis would SPEND PixAI credits (unless free above). "
              "Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))
    thumb_dir = out / "gallery" / "thumbs"
    from moonglade_gallery import make_thumbnail

    params = {}
    if existing_task:
        task_id = existing_task
        print("Fetching existing edit task (no credits):", task_id)
    else:
        # Checked before the upload loop, not just before the mutation -- see
        # run_reference_video.
        _check_read_only("submit an edit (spends credits unless a card applies)")
        if override:
            params = json.loads(override)
        else:
            media_ids = []
            for s in srcs:
                if _is_local_source(s):
                    print("Uploading local image:", s)
                    media_ids.append(upload_media(session, s))
                else:
                    media_ids.append(str(s))
            params = build_chat_edit_parameters(
                prompt, media_ids, model_id=cfg["model_id"],
                resolution=cfg["resolution"], aspect_ratio=cfg["aspect_ratio"],
                quality=cfg["quality"], kaisuuken_id=cfg["kaisuuken_id"])
        print("Submitting EDIT task (spends credits unless a free card applies)...")
        _apply_kaisuuken(session, params, args)
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
        task_id = (created.get("createGenerationTask") or {}).get("id")
        if not task_id:
            raise PixAIError("no task id returned: " + json.dumps(created)[:300])
        print("  task id:", task_id)
        _bump_card_use(params)
        _poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="edit", fail_noun="edit")

    result = task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    outputs = result.get("outputs") or {}
    # Same fix as run_generate: outputs.batch[] holds the real individual images on
    # a batchSize>1 edit; outputs.mediaId alone is the composite grid.
    media = _task_image_media(outputs)
    seeds = dict(media)
    mids = [mid for mid, _ in media]
    _outputs_or_raise(result, mids, "edit task completed but no media ids found")

    fm = extract_full_meta(result)
    chat = (params.get("chat") or {}) if isinstance(params, dict) else {}
    prompt_used = fm.get("prompt_full") or prompt or chat.get("prompts", "")
    img_dir = out / "images"
    rows, saved = [], []
    for mid in mids:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        stem = img_dir / build_stem_name(prompt_used, task_id, mid,
                                         getattr(args, "name_length", 60),
                                         getattr(args, "name_sep", "_"))
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = {f: "" for f in CATALOG_FIELDS}
        full.update({
            "task_id": str(task_id), "media_id": mid, "seed": seeds.get(mid, ""),
            "filename": str(path.relative_to(out)).replace("\\", "/"),
            "url": url, "source": "api", "status": "completed",
            "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_full": prompt_used, "prompt_preview": (prompt_used or "")[:100],
            "model_id": str(chat.get("modelId") or fm.get("model_id") or ""),
            "model_name": fm.get("model_name", "") or "Edit",
            "paid_credit": _paid_credit_str(result),   # actual cost, task-level
            "width": str((info or {}).get("width") or ""),
            "height": str((info or {}).get("height") or ""),
        })
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))

    if rows:
        save_catalog(db_path, rows)
    print("Edited + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved)}


def _needs_model_fix(row):
    """Return the model version-id to resolve if this row's model_name is missing
    or still a raw numeric id; else ''. Handles the case where model_name was
    set to the numeric id (MODEL_DETAIL_HASH was absent on an earlier run)."""
    mid = (row.get("model_id") or "").strip()
    name = (row.get("model_name") or "").strip()
    if not mid and name.isdigit():
        mid = name  # model_name itself is the numeric id
    if not mid:
        return ""
    if not name or name == mid or name.isdigit():
        return mid
    return ""


def run_fix_models(args):
    """Re-resolve human-readable model names for catalog rows whose model_name is
    blank or still a numeric version-id (e.g. saved before MODEL_DETAIL_HASH was
    configured). One API call per distinct model id (cached)."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    rows = load_catalog(db_path)

    to_resolve = {}   # version_id -> rows needing it
    for r in rows:
        vid = _needs_model_fix(r)
        if vid:
            to_resolve.setdefault(vid, []).append(r)

    if not to_resolve:
        print("No model names need fixing -- catalog already has readable names.")
        return {"fixed": 0, "models": 0, "unresolved": 0}

    relabel = getattr(args, "relabel_removed", False)
    removed_label = "Unknown or removed model"
    workers = max(1, getattr(args, "workers", 1) or 1)
    print("Resolving {} distinct model id(s) across {} rows{}...".format(
        len(to_resolve), sum(len(v) for v in to_resolve.values()),
        " ({} workers)".format(workers) if workers > 1 else ""))
    _prog = getattr(args, "progress", None)
    fixed = relabeled = unresolved = 0
    for vid, name in _parallel_map(sorted(to_resolve),
                                   lambda v: model_name_gql(session, v),
                                   workers, _prog, delay=getattr(args, "delay", 0.4)):
        if name and name != vid and not str(name).isdigit():
            for r in to_resolve[vid]:
                r["model_name"] = name
                fixed += 1
        else:
            unresolved += 1
            if relabel:
                for r in to_resolve[vid]:
                    r["model_name"] = removed_label  # model_id kept for reference
                    relabeled += 1
                print("  {} unresolved -> '{}'".format(vid, removed_label))
            else:
                print("  could not resolve model {} (left as-is)".format(vid))

    if fixed or relabeled:
        save_catalog(db_path, rows)
    print("\nFixed {} row(s) across {} model(s); {} id(s) unresolved{}.".format(
        fixed, len(to_resolve) - unresolved, unresolved,
        " (relabeled {} rows to '{}')".format(relabeled, removed_label) if relabeled else ""))
    return {"fixed": fixed, "relabeled": relabeled, "models": len(to_resolve) - unresolved,
            "unresolved": unresolved}


# Read-only account dashboard. Ad-hoc query (no persisted hash) -- the selection
# below mirrors what the site's getMyQuota + getMyMembership return. READ ONLY:
# this only reports your credit balance / plan. It never moves money. Buying
# credits or changing your subscription is deliberately NOT implemented -- do that
# in the browser.
# `roles` (2026-07-24) is the account's own role list -- the owner's carries BETA_TO_INVITE,
# the flag behind PixAI's early-access programs (the Tsubaki.3 / DiT.3 invite). One extra leaf
# field on the query the header chip, --account and /api/account already run: no extra call,
# no spend. Only the field NAME was probed, not its exact shape, so every consumer must
# normalize rather than assume a list (see /api/account).
_ACCOUNT_QUERY = """
query {
  me {
    id
    quotaAmount
    tasks { totalCount }
    followerCount
    followingCount
    referralCode { code }
    membership { membershipId tier privilege }
    subscription { planId provider interval status startAt endAt cancelAtPeriodEnd }
  }
}
"""


def artwork_views(session, artwork_id):
    """Live view count for one of the owner's published artworks (ad-hoc `artwork(id){views}`,
    no persisted hash). Views dwarf likes and aren't stored locally -> the 'Your Art' panel's
    headline signal. Read-only; 0 on any failure."""
    if not artwork_id:
        return 0
    try:
        d = gql_adhoc(session, "query($id:ID!){ artwork(id:$id){ views } }",
                      {"id": str(artwork_id)})
        return int(((d or {}).get("artwork") or {}).get("views") or 0)
    except (PixAIError, TypeError, ValueError):
        return 0


def account_info(session, raise_on_error=False):
    """Fetch credits + membership/subscription via ad-hoc GraphQL. Returns the `me` dict.
    Fails soft to {} by default (the web header chip relies on that); pass raise_on_error=True
    to let the real PixAIError propagate so a caller can report WHY (auth vs transient).
    Read-only. Note gql_adhoc already retries network/429/5xx 3x with backoff, so an error
    here means a sustained outage or a real auth/GraphQL problem, not a one-off blip."""
    try:
        return (gql_adhoc(session, _ACCOUNT_QUERY) or {}).get("me") or {}
    except PixAIError:
        if raise_on_error:
            raise
        return {}


def run_account_info(args):
    """Print a read-only account dashboard: credit balance, membership, and
    subscription status. Never initiates payment -- buy credits in the browser."""
    session = _make_session(getattr(args, "token", None))
    try:
        me = account_info(session, raise_on_error=True)
    except PixAIError as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            print("Account read failed: your API key is missing or expired -- check config.json.")
        else:
            # gql_adhoc already retried; this is a sustained network/API hiccup, not your key.
            print("Account read failed (temporary API/connection issue) -- try again in a moment.")
            print("  detail: {}".format(msg[:160]))
        return {}
    if not me:
        print("Account read returned no data -- try again in a moment.")
        return {}
    mem = me.get("membership") or {}
    sub = me.get("subscription") or {}
    priv = mem.get("privilege") or {}
    try:
        credits = "{:,}".format(int(me.get("quotaAmount") or 0))
    except (TypeError, ValueError):
        credits = str(me.get("quotaAmount"))
    print("Account ID       : {}".format(me.get("id") or USER_ID))
    print("Credits (balance): {}".format(credits))
    server_tasks = ((me.get("tasks") or {}).get("totalCount"))
    if server_tasks is not None:
        print("Lifetime tasks   : {:,}  (server's count of every generation you've made)".format(
            int(server_tasks)))
    if me.get("followerCount") is not None:
        print("Followers        : {:,}  (following {:,})".format(
            int(me.get("followerCount") or 0), int(me.get("followingCount") or 0)))
    if me.get("referralCode"):
        print("Referral code    : {}".format((me.get("referralCode") or {}).get("code", "-")))
    if mem:
        print("Membership       : {} (tier {})".format(
            mem.get("membershipId", "-"), mem.get("tier", "-")))
        if priv.get("dailyClaimAdded"):
            print("Daily free claim : {:,}".format(int(priv["dailyClaimAdded"])))
        if priv.get("professionalMode"):
            print("Professional mode: on")
        # The rest of the membership entitlements (were fetched, never shown).
        if priv.get("paidCredit"):
            print("Credit ceiling   : {:,}".format(int(priv["paidCredit"])))
        slots = []
        if priv.get("lora") is not None:
            slots.append("{} LoRA".format(priv["lora"]))
        if priv.get("freeUserLora") is not None:
            slots.append("{} free-user LoRA".format(priv["freeUserLora"]))
        if priv.get("privateModel") is not None:
            slots.append("{} private-model".format(priv["privateModel"]))
        if slots:
            print("Slots            : {}".format(", ".join(slots)))
        if priv.get("extraPackageValue"):
            print("Extra package    : {:,}".format(int(priv["extraPackageValue"])))
    if sub:
        renew = "cancels at period end" if sub.get("cancelAtPeriodEnd") else "renews"
        print("Subscription     : {} {} via {} ({}); {} {}".format(
            sub.get("planId", "-"), (sub.get("interval") or "").lower(),
            sub.get("provider", "-"), sub.get("status", "-"),
            renew, (sub.get("endAt") or "")[:10]))
    print("\n(Read-only. To buy credits or change your plan, use the browser.)")
    return {"quota": me.get("quotaAmount"), "membership": mem.get("membershipId")}


# --- Live event push (WebSocket) ------------------------------------------------
# PixAI pushes personal events over a graphql-transport-ws WebSocket at
# wss://gw.pixai.art/graphql -- a SEPARATE transport from the api.pixai.art HTTP API.
# The `personalEvents` subscription (no args) streams two channels: `taskUpdated`
# (your generations changing state) and `newNotification`. Listening is READ-ONLY and
# far gentler on PixAI than periodic polling. Confirmed reachable with the same Bearer
# token the tool already holds (see private/APP_OPERATIONS_FULL.md).
#
# STATUS: this `--watch` command is the shipped live monitor. With --watch-backup it
# is also the event-driven backup mode -- each task's 'completed' frame (confirmed
# lifecycle below) triggers an immediate download + catalog, instead of waiting on
# the next polling pass.
_WS_URI = "wss://gw.pixai.art/graphql"
_WS_SUBSCRIPTION = (
    "subscription Watch { personalEvents { "
    "taskUpdated { id status updatedAt mediaId media { id urls { url } } priority userId } "
    "newNotification { id title createdAt userId } } }")
# Confirmed lifecycle: waiting -> running -> completed. The
# 'completed' frame is the one carrying a populated mediaId, so that's when we mirror.
_WS_DONE_STATUS = "completed"

# How long the receive loop below will wait for the NEXT frame off the wire --
# a `next` event, a `newNotification`, or even just a server `ping` keepalive --
# before deciding the connection is a zombie and forcing a reconnect. This is
# NOT "no taskUpdated in N seconds" (an account can be legitimately idle for
# hours between generations); it is "nothing at all arrived, including PixAI's
# own keepalive pings", which is what a genuinely dead-but-not-yet-errored
# socket looks like -- exactly the incident this guards against: `connected`
# stayed True and `last_error` stayed None for ~21 minutes while real
# generations finished and produced zero `taskUpdated` frames.
#
# Picking the number: the two things we actually know are (1) real generations
# in the incident finished in under a minute on PixAI's side, so any live
# session doing real work produces frames on a sub-minute cadence, not a
# multi-minute one; and (2) the failure was silent for ~21 minutes, so the
# threshold needs to be decisively shorter than that to matter, while staying
# well clear of ordinary lulls (a slow multi-minute video render between
# frames, a user idling between submissions) so a healthy connection is never
# cycled just for being briefly quiet. 240s (4 minutes) sits in the middle of
# that gap: an order of magnitude past any real per-frame cadence we've
# observed (so no thrash under normal bursty use), but leaves ~5x headroom
# before it would matter compared to tonight's ~20-minute silent gap, and
# lines up with the same magnitude as this app's other liveness clocks
# (--poll-timeout's 300s generate default; JOBS_ORPHAN_SWEEP_AGE's much
# coarser 30-minute sweep is a different, slower-moving safety net, not a
# reason to match it here).
_WS_STALE_TIMEOUT = 240


async def _watch_events_async(auth_header, on_event, seconds):
    """Connect, handshake, subscribe to personalEvents, and dispatch each `next` frame's
    payload to on_event(dict). Replies to server pings. Runs until `seconds` elapses (None =
    until cancelled). Read-only: sends only connection_init / subscribe / pong / complete.

    Every frame off the wire -- a `next`, a `ping`, anything -- resets a
    `_WS_STALE_TIMEOUT`-second clock. If that clock lapses, raises WatchStaleError
    instead of waiting forever on a socket that reports no error but has gone
    silent (see `_WS_STALE_TIMEOUT`'s comment for why that happens and how the
    number was picked). WatchStaleError is just another exception out of this
    coroutine, so any caller that already reconnects on failure -- `_watch_loop`
    in moonglade_gallery.py's outer while-True/backoff, and `run_watch` below's own
    try/except -- handles it for free with no special-casing needed at the call
    site; it exists only so a caller that WANTS to tell "went stale" apart from
    "socket errored" can."""
    import asyncio
    import websockets
    async def _run():
        async with websockets.connect(
                _WS_URI, subprotocols=["graphql-transport-ws"],
                additional_headers={"Origin": "https://pixai.art"}) as ws:
            await ws.send(json.dumps({"type": "connection_init",
                                      "payload": {"Authorization": auth_header}}))
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if ack.get("type") != "connection_ack":
                raise PixAIError("WebSocket handshake failed (no connection_ack): {!r}".format(ack))
            await ws.send(json.dumps({"id": "watch", "type": "subscribe",
                                      "payload": {"query": _WS_SUBSCRIPTION}}))
            on_event({"__meta__": "subscribed"})
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_WS_STALE_TIMEOUT)
                except asyncio.TimeoutError:
                    # Converted to a WatchStaleError HERE, not left as a bare
                    # asyncio.TimeoutError, so it can never be mistaken for (or
                    # accidentally swallowed by) the outer bounded-run timeout
                    # below, which catches that same exception type for a
                    # completely different reason (the `seconds` run budget).
                    raise WatchStaleError(
                        "no frame from PixAI in {}s (not even a keepalive ping) -- "
                        "treating the connection as dead".format(_WS_STALE_TIMEOUT))
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "ping":
                    await ws.send(json.dumps({"type": "pong"})); continue
                if mtype == "error":
                    raise PixAIError("subscription rejected: {}".format(
                        json.dumps(msg.get("payload"))))
                if mtype == "complete":
                    break
                if mtype == "next":
                    ev = (((msg.get("payload") or {}).get("data") or {})
                          .get("personalEvents") or {})
                    on_event(ev)
    if seconds:
        try:
            await asyncio.wait_for(_run(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
    else:
        await _run()


def run_watch(args):
    """CLI: live-monitor your PixAI events over the push WebSocket (read-only). Prints each
    taskUpdated / newNotification as it arrives. With --watch-backup, a task reaching
    'completed' is downloaded + cataloged the instant it finishes -- event-driven backup
    (the polling loop becomes a fallback, not the default). This is the 'live mirror' mode."""
    import asyncio
    import threading
    session = _make_session(getattr(args, "token", None))
    auth = session.headers.get("Authorization")
    if not auth:
        print("No Authorization token on the session -- check your API key.")
        return
    seconds = getattr(args, "watch_seconds", 0) or None
    do_backup = bool(getattr(args, "watch_backup", False))
    out_dir = getattr(args, "out", "pixai_backup") or "pixai_backup"
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):
        return str(t).encode(enc, "replace").decode(enc, "replace")

    seen = {"n": 0, "saved": 0}
    backed = set()   # task ids already mirrored this session (a 'completed' can repeat)

    def _mirror(tid):
        """Download + catalog one finished task off the event loop (own session per thread)."""
        try:
            res = collect_generation(_make_session(getattr(args, "token", None)), tid, out_dir)
            n = res.get("saved") or 0
            seen["saved"] += n
            print("      -> mirrored task {}: {} file(s) {}".format(
                tid, n, "[video]" if res.get("is_video") else ""))
        except Exception as e:
            print("      -> backup of task {} failed: {}".format(tid, _safe(str(e)[:140])))

    def on_event(ev):
        if ev.get("__meta__") == "subscribed":
            mode = "mirroring completed tasks -> {}".format(out_dir) if do_backup else "monitor only"
            print("[*] connected + subscribed to personalEvents ({}). Listening".format(mode)
                  + (" for {}s".format(seconds) if seconds else " (Ctrl-C to stop)") + "...\n")
            return
        seen["n"] += 1
        tu = ev.get("taskUpdated")
        nn = ev.get("newNotification")
        if tu:
            urls = (((tu.get("media") or {}).get("urls")) or [])
            url = (urls[0].get("url") if urls else "") or ""
            status = tu.get("status")
            tid = str(tu.get("id") or "")
            print("  [taskUpdated] status={:<14} task={} media={} {}".format(
                _safe(status), tid or "-", tu.get("mediaId") or "-", _safe(url)[:70]))
            if do_backup and status == _WS_DONE_STATUS and tid and tid not in backed:
                backed.add(tid)
                threading.Thread(target=_mirror, args=(tid,), daemon=True).start()
        if nn:
            print("  [notification] {} — {}".format(
                _safe(nn.get("title")), (nn.get("createdAt") or "")[:19]))
        if not tu and not nn:
            print("  [event] " + _safe(json.dumps(ev))[:200])

    print("Watching PixAI live events at {} (read-only; gentler than polling).".format(_WS_URI))
    try:
        asyncio.run(_watch_events_async(auth, on_event, seconds))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("\nWatch ended: {}".format(_safe(str(e)[:200])))
        return
    msg = "\nStopped. Saw {} event(s)".format(seen["n"])
    if do_backup:
        msg += ", mirrored {} file(s)".format(seen["saved"])
    print(msg + ".")


# --- Contests (community + official) --------------------------------------------
# PixAI's live contest board lives at REST `GET /v2/contest/list?page=N&pageSize=M`
# (NOT the GraphQL `contests` connection, which is a stale official-only archive).
# "Active" is the server-computed `runtimeStatus == "running"` -- no client date math.
# Read-only: browsing contests never spends. See private/APP_OPERATIONS_FULL.md.
_CONTEST_PAGE_SIZE = 50


def _contest_title(t):
    """Contest title/description come as {en, zh, ja, ko, ...} (or occasionally a bare
    string). Prefer English, fall back to the first non-empty value."""
    if isinstance(t, dict):
        return t.get("en") or next((v for v in t.values() if v), "") or ""
    return t or ""


def list_contests(session, active_only=False, max_pages=6):
    """Return the PixAI contest board as normalized dicts, newest-first. `active_only`
    keeps just the currently-running ones (runtimeStatus=='running'). Pages through
    /v2/contest/list up to max_pages (the board is ~2 pages). Read-only, no spend."""
    out = []
    page = 1
    while True:
        d = _rest_get(session, "/contest/list",
                      params={"page": page, "pageSize": _CONTEST_PAGE_SIZE}) or {}
        rows = d.get("data") or []
        for r in rows:
            status = (r.get("runtimeStatus") or "").lower()
            active = status == "running"
            if active_only and not active:
                continue
            mid = str(r.get("mediaId") or "")
            slug = r.get("slug") or ""
            out.append({
                "id": str(r.get("id") or ""),
                "title": _contest_title(r.get("title")),
                "slug": slug,
                "type": (r.get("type") or "").lower(),          # 'official' | 'community'
                "status": status,                                # 'running' | 'ended'
                "active": active,
                "vote_type": r.get("voteType") or "",            # creator_pick | user_vote
                "prize_amount": int(r.get("prizeAmount") or 0),
                "prize_distribution": [p for p in (r.get("prizeDistribution") or [])
                                       if isinstance(p, dict)],
                "cover_url": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
                "start_at": r.get("startAt") or "",
                "end_at": r.get("endAt") or "",
                "result_at": r.get("resultAt") or "",
                "url": ("https://pixai.art/en/contest/%s" % slug) if slug else "",
                "description": _contest_title(r.get("description"))[:600],
            })
        total_page = int(d.get("totalPage") or 1)
        if page >= total_page or page >= max_pages:
            break
        page += 1
    return out


def run_contests(args):
    """CLI: list PixAI contests (default: only the currently-running ones). Read-only.
    --all-contests includes ended ones. Encourages community engagement -- see what's live."""
    session = _make_session(getattr(args, "token", None))
    active_only = not getattr(args, "all_contests", False)
    try:
        contests = list_contests(session, active_only=active_only)
    except PixAIError as e:
        print("Could not fetch contests: {}".format(str(e)[:160]))
        return
    if not contests:
        print("No {}contests found.".format("active " if active_only else ""))
        return
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):
        return str(t).encode(enc, "replace").decode(enc, "replace")
    official = [c for c in contests if c["type"] == "official"]
    community = [c for c in contests if c["type"] != "official"]
    label = "active" if active_only else "all"
    print("PixAI contests ({}): {} official, {} community\n".format(
        label, len(official), len(community)))
    for group, name in ((official, "OFFICIAL"), (community, "COMMUNITY")):
        if not group:
            continue
        print("-- {} --".format(name))
        for c in group:
            flag = "" if c["active"] else " (ended)"
            prize = "  {:,} cr".format(c["prize_amount"]) if c["prize_amount"] else ""
            print("  {}{}{}".format(_safe(c["title"])[:52], prize, flag))
            print("    {} -> {}   {}".format(
                (c["start_at"] or "")[:10], (c["end_at"] or "")[:10], c["url"]))
        print("")
    print("(Read-only. Enter a contest from the PixAI website.)")


# --- Free "cards" (kaisuuken / 回数券) -------------------------------------------
# PixAI grants free-generation tickets ("kaisuuken", model-locked) via membership/events.
# These live on the oRPC /v2 REST API, NOT GraphQL (verified 2026-07-03 from the app's
# own contract). Two ops matter:
#   GET  /v2/kaisuuken/summary  -> {kaisuukens:[{count, expiryCounts, templateId, taskTypes,
#                                    routeToNative, templateName, ...}]}  (one row per template)
#   POST /v2/kaisuuken/check    -> given a generation's params, returns the matching cards +
#                                  individual TICKET ids: {matches:[{templateId,
#                                  kaisuukens:[{id, expiresAt}] (<=3, nearest first), total}]}
# On pixai.art the web client calls `check` and attaches the ticket id for you; we do the
# same via _apply_kaisuuken (attach `kaisuukenId` -> server consumes the card -> 0 credits).
# The `check` call is READ-ONLY: it never consumes a card; consumption happens only when a
# task is actually submitted with the attached id. Both helpers fail soft.


def _rest_get(session, path, params=None, timeout=30):
    """GET a /v2 oRPC REST route. Returns parsed JSON. Raises PixAIError on non-2xx."""
    r = session.get(REST_API_BASE + path, params=params, timeout=timeout)
    if not r.ok:
        raise PixAIError("REST GET {} -> {}: {}".format(path, r.status_code, r.text[:300]))
    return r.json()


def _rest_post(session, path, body, timeout=60):
    """POST JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx."""
    r = session.post(REST_API_BASE + path, json=body, timeout=timeout)
    if not r.ok:
        raise PixAIError("REST POST {} -> {}: {}".format(path, r.status_code, r.text[:300]))
    return r.json()


def _normalize_kaisuuken(raw):
    """Normalize one kaisuuken TEMPLATE row from /v2/kaisuuken/summary. Each row is a
    template with a held `count` (not per-id ids -- those come from `check`). The model
    it's locked to lives in routeToNative (pixai://...?modelVersionId=NNN)."""
    raw = raw or {}
    m = re.search(r"modelVersionId=(\d+)", raw.get("routeToNative") or "")
    return {
        "name": raw.get("templateName") or raw.get("templateCode") or "card",
        "count": raw.get("count"),
        "category": raw.get("categoryName") or raw.get("categoryCode") or "",
        "task_types": raw.get("taskTypes") or [],
        "model_version_id": m.group(1) if m else "",
        "template_code": raw.get("templateCode") or "",
        "template_id": raw.get("templateId") or "",
        "expires": raw.get("soonestExpireAt") or "",
    }


def list_kaisuukens(session):
    """Read the account's free-generation cards via GET /v2/kaisuuken/summary. Read-only;
    fails soft (returns []) on error. One row per template, with the held `count`, the
    model it's locked to, and soonest expiry."""
    try:
        data = _rest_get(session, "/kaisuuken/summary") or {}
    except PixAIError:
        return []
    rows = data.get("kaisuukens")
    if rows is None:
        return []
    return [_normalize_kaisuuken(k) for k in rows]


def _target_model_id(parameters):
    """The model id a generation targets, wherever it lives: top-level `modelId` for
    plain gen + video, or `chat.modelId` for an instruct edit. Empty string if none."""
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("modelId")
               or (parameters.get("chat") or {}).get("modelId") or "").strip()


def match_kaisuuken(session, parameters, enrich=False, raise_on_error=False):
    """POST /v2/kaisuuken/check with a generation's `parameters` and return the single
    nearest-expiry matching TICKET as {id, expiresAt, templateId, total} -- or None when
    no card matches. READ-ONLY: this only *checks*; the card is consumed later, when the
    task is submitted with the returned id attached. Fails soft (returns None) by default
    -- fine for every read-only/preview/display caller, where a glitched check should not
    block the UI.

    `raise_on_error=True` re-raises instead of swallowing the failure into None. The one
    caller that needs this is `_apply_kaisuuken`'s spend-time check: there, a transient
    check failure and "genuinely no card matches" must NOT collapse into the same outcome,
    because that outcome is "proceed and spend real credits."

    `enrich=True` cross-references /kaisuuken/summary to (a) PREFER the card locked to this
    generation's own model when more than one template is eligible -- so an Edit gen spends
    an Edit card, not a same-expiry Reference card that merely also matched -- and (b) attach
    the card's human `name` for honest UI ("Edit Pro Only covers this", not a guess). The
    default (False) keeps the original single-call behavior for every existing caller."""
    if not parameters:
        return None
    try:
        data = _rest_post(session, "/kaisuuken/check",
                          {"type": "generation-task", "parameters": parameters}) or {}
    except (PixAIError, ValueError):
        if raise_on_error:
            raise
        return None
    matches = data.get("matches") or []
    if not matches:
        return None
    by_tid = {c.get("template_id"): c for c in list_kaisuukens(session)} if enrich else {}
    # (A) When several cards are eligible, prefer the one whose model IS this generation's
    # model; fall back to the full set if none match (or we didn't enrich).
    want = _target_model_id(parameters)
    pool = matches
    if enrich and want and len(matches) > 1:
        preferred = [mt for mt in matches
                     if str((by_tid.get(mt.get("templateId")) or {}).get("model_version_id") or "") == want]
        if preferred:
            pool = preferred
    best = None
    for mt in pool:
        for k in (mt.get("kaisuukens") or []):
            kid = k.get("id")
            if not kid:
                continue
            # ISO8601 sorts chronologically; treat never-expire (null) as far future.
            exp = k.get("expiresAt") or "9999-12-31"
            if best is None or exp < best["_exp"]:
                best = {"id": kid, "expiresAt": k.get("expiresAt"),
                        "templateId": mt.get("templateId"), "total": mt.get("total"),
                        "_exp": exp}
    if best:
        best.pop("_exp", None)
        if enrich:                                     # (B) name the card for honest UI
            best["name"] = (by_tid.get(best["templateId"]) or {}).get("name")
    return best


# GET /v2/task-price computes a generation's credit cost WITHOUT creating it (mirrors the
# GraphQL pricingTask). Scalar params go as query params; the nested blocks below go as
# URL-encoded JSON. Field set = the endpoint's input schema (`Ou` in the app contract) --
# anything else (prompts, seed, cfgScale, channel, kaisuukenId, …) is not priced, so skip it.
_PRICE_SCALARS = frozenset((
    "width", "height", "samplingSteps", "inferenceProfile", "upscaleDenoisingSteps",
    "upscaleDenoisingStrength", "upscale", "samplingMethod", "priority", "strength",
    "batchSize", "enableTile", "enlarge", "mediaId", "modelId", "enableADetailer",
    "lightning", "vaeModelId", "workflowName", "sceneId", "watermark"))
_PRICE_NESTED = frozenset((
    "controlNets", "ipAdapter", "animateDiff", "workflow", "i2vPro", "referenceVideo",
    "t2i2v", "inputs", "chat", "inpaint", "loraParameters"))
# The upscale keys above are why the cost badge tracks an upscale at all -- the two methods
# differ by roughly 3x at their maximum ratio. Deliberately NOT listed: enlargeModel,
# upscaleSampler and qualityTag. They are real submit params, but they are not in this
# endpoint's input schema and none of them changes the price (the cost is the same whichever
# upscaler network runs), and an off-schema query param risks a 400 that would make
# price_task fail soft and blank the badge. Add one only with a measurement showing it priced.


def price_task(session, params):
    """Compute a generation's credit cost via GET /v2/task-price WITHOUT creating it.
    Returns actualPrice (int credits) or None. READ-ONLY -- spends nothing, fails soft."""
    if not params:
        return None
    q = {}
    for k, v in params.items():
        if v is None:
            continue
        if k in _PRICE_NESTED:
            q[k] = json.dumps(v)          # requests URL-encodes the JSON string
        elif k in _PRICE_SCALARS:
            q[k] = v
    if not q:
        return None
    try:
        data = _rest_get(session, "/task-price", params=q) or {}
    except (PixAIError, ValueError):
        return None
    ap = data.get("actualPrice")
    return int(ap) if ap is not None else None


def queue_wait_estimate(session, priority, model_version_id):
    """PixAI's own queue-wait estimate for a (priority, model) pair, in whole seconds, or
    None. GET /v2/task/wait-time -- the number their site puts beside Generate ("Est. wait
    ~9 seconds"). READ-ONLY: creates nothing, prices nothing, spends nothing.

    The parameter shape was probed, not guessed, because the route gives up nothing on its
    own: with no parameters it 400s `expected number, received NaN` on path ["priority"];
    with a priority alone it 400s "modelVersionId or generationModelId must be provided";
    `generationModelId` then 404s "Generation model not found" for the very id our submits
    carry in their `modelId` field, while `modelVersionId` with that same id answers 200. So
    as far as this route is concerned, a submit's `modelId` IS a model version id. `priority`
    is a validated enum rather than a free number -- 1 comes back "invalid priority" -- and
    the two values this app ever submits (500 normal, 1000 --high-priority) both answer.

    Response: {waitDurationSeconds, displayBucket, displaySeconds, displayMinutes}.
    Measured 2026-07-25: Tsubaki.2 v1 at priority 500 -> 25.4s and at 1000 -> 4.4s;
    Reference Pro at 500 -> 50.1s; the same pair re-asked minutes later -> 26.7s. So it is
    per-model AND per-priority, and it tracks real queue depth.

    This is a QUEUE-DEPTH estimate for a submission -- NOT a per-task ETA, and emphatically
    not progress. PixAI exposes no progress on a task at all (probed against a live control:
    none of progress/percent/percentage/step/steps/currentStep/eta/estimatedTime/
    queuePosition/position/waitTime exist on the task object). A caller must present this as
    the estimate it is, never as a countdown that ticks down.
    """
    if not model_version_id:
        return None                      # the route 400s without one; don't spend the call
    try:
        pri = int(priority)
    except (TypeError, ValueError):
        pri = 500                        # this app's own submit default (see build params)
    try:
        data = _rest_get(session, "/task/wait-time",
                         params={"priority": pri,
                                 "modelVersionId": str(model_version_id)}) or {}
    except (PixAIError, ValueError):
        return None                      # an estimate is a nicety; never raise for it
    secs = data.get("waitDurationSeconds")
    if secs is None:
        secs = data.get("displaySeconds")
    try:
        return max(0, int(round(float(secs))))
    except (TypeError, ValueError):
        return None


def suggest_prompt(session, media_id):
    """Reverse a prompt out of an image (PixAI's "Image to prompt"): GET
    /v2/tag/suggest-prompt/{mediaId} -> a list of suggested prompt strings (a Danbooru-
    style tag list + a natural-language description variant). FREE, read-only. Raises."""
    data = _rest_get(session, "/tag/suggest-prompt/" + str(media_id)) or {}
    return data.get("output") or []


def tag_search_gql(session, prefix, first=8):
    """Tag autocomplete for the prompt writer -- the site's "Tag Suggestions" dropdown.
    GraphQL `tags(q:$prefix, first:$n)` (field-probed 2026-07-04; node has name/
    category/id/weight, no usage count -- the site's counts are client-side). Returns
    a list of tag names. FREE, read-only. Raises on GraphQL error."""
    q = "query($k:String!,$n:Int){ tags(q:$k, first:$n){ edges{ node{ name } } } }"
    d = gql_adhoc(session, q, {"k": str(prefix), "n": int(first)}) or {}
    out = []
    for e in (d.get("tags") or {}).get("edges") or []:
        name = (e.get("node") or {}).get("name")
        if name:
            out.append(name)
    return out


def run_suggest_prompt(args):
    """--suggest-prompt <media_id|file>: print PixAI's suggested prompt(s) for an image
    (the site's "Image to prompt"). A local file is uploaded first (free); a catalog
    media_id is used directly. FREE and read-only -- spends no credits, no --confirm.

    PixAI's suggest-prompt endpoint is image-only and 500s on a video; the web gallery
    already hides the "Suggest prompt" button for a video row (`row.is_video != '1'`
    in moonglade_gallery.py). Mirror that same gate here (B18 residual) so the CLI refuses
    early with a clear message instead of surfacing that raw 500."""
    src = (getattr(args, "suggest_prompt", "") or "").strip()
    if not src:
        raise PixAIError("--suggest-prompt needs a catalog media_id or a local image file.")
    is_local = _is_local_source(src)
    if is_local:
        if Path(src).suffix.lower() in _VIDEO_EXTS:
            raise PixAIError(
                "--suggest-prompt only works on images, not video -- {} looks like a "
                "video file (PixAI's image-to-prompt endpoint doesn't support "
                "video).".format(src))
    else:
        out = getattr(args, "out", "") or "pixai_backup"
        row = next((r for r in load_catalog(Path(out) / "catalog.db")
                    if r.get("media_id") == src), None)
        if row and row.get("is_video") == "1":
            raise PixAIError(
                "--suggest-prompt only works on images, not video -- media {} is a video "
                "in your catalog (PixAI's image-to-prompt endpoint doesn't support video; "
                "the web gallery hides this button for videos for the same reason).".format(src))
    session = _make_session(getattr(args, "token", None))
    if is_local:
        print("Uploading image (free):", src)
        media_id = upload_media(session, src)
    else:
        media_id = src
    outs = suggest_prompt(session, media_id)
    if not outs:
        print("No prompt suggestion returned for media", media_id)
        return {"suggestions": 0, "media_id": media_id}
    print("=== suggested prompt(s) for media {} ===".format(media_id))
    for i, o in enumerate(outs, 1):
        print("\n[{}] {}".format(i, o))
    return {"suggestions": len(outs), "media_id": media_id}


# --- Claimable rewards (daily credits, agent stamina) -- oRPC /v2/claim ----------
def list_claims(session):
    """Read the account's claimable rewards via GET /v2/claim (daily credits, agent
    stamina). Read-only; fails soft (returns []). Each row: {id, amount, canClaim,
    claimedAt, nextClaimableTime}."""
    try:
        data = _rest_get(session, "/claim")
    except PixAIError:
        return []
    return data if isinstance(data, list) else []


def claim_reward(session, claim_id):
    """Claim a reward by id via POST /v2/claim/{id}. State-changing: grants the reward to
    YOUR OWN account (a routine daily entitlement, no money moves). Returns the updated
    claim record. Raises PixAIError on error."""
    _check_read_only("claim a reward")  # still a real account mutation, even a beneficial one
    return _rest_post(session, "/claim/" + str(claim_id), {})


def _fmt_epoch_ms(ms):
    if not ms:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return str(ms)


def run_claims(args):
    """--claims: list your claimable rewards (read-only). --claim <id|all>: claim one or
    all ready rewards -- GATED behind --confirm (grants free credits/stamina to your own
    account). Never claims anything without --confirm."""
    session = _make_session(getattr(args, "token", None))
    claim_id = (getattr(args, "claim", "") or "").strip()
    rewards = list_claims(session)
    if not rewards:
        print("No claimable rewards found (read-only; nothing changed).")
        return {"rewards": 0}

    if not claim_id:                                   # LIST (read-only)
        print("Claimable rewards (read-only):\n")
        for r in rewards:
            state = "READY now" if r.get("canClaim") else \
                    "next: " + _fmt_epoch_ms(r.get("nextClaimableTime"))
            print("  {:<24} {:>8}   {}".format(r.get("id"), r.get("amount"), state))
        ready = [r["id"] for r in rewards if r.get("canClaim")]
        if ready:
            print("\nReady: {}\nClaim with:  --claim <id>  (or --claim all)  --confirm".format(
                ", ".join(ready)))
        else:
            print("\nNothing ready to claim right now.")
        return {"rewards": len(rewards), "ready": len(ready)}

    # CLAIM (--claim <id|all>) -- guarded by --confirm
    targets = ([r for r in rewards if r.get("canClaim")] if claim_id == "all"
               else [r for r in rewards if r.get("id") == claim_id])
    if not targets:
        print("Nothing to claim for '{}' (unknown id, or not currently claimable).".format(claim_id))
        return {"claimed": 0}
    if not any(t.get("canClaim") for t in targets):
        print("'{}' is not claimable yet (next: {}).".format(
            claim_id, _fmt_epoch_ms(targets[0].get("nextClaimableTime"))))
        return {"claimed": 0}
    if not getattr(args, "confirm", False):
        print("Would claim (re-run with --confirm):")
        for r in targets:
            if r.get("canClaim"):
                print("  {} (+{})".format(r.get("id"), r.get("amount")))
        return {"claimed": 0, "preview": True}
    claimed = 0
    for r in targets:
        if not r.get("canClaim"):
            continue
        try:
            claim_reward(session, r["id"])
            print("Claimed {} (+{}).".format(r["id"], r.get("amount")))
            claimed += 1
        except PixAIError as e:
            print("Failed to claim {}: {}".format(r["id"], str(e)[:150]))
    if claimed:
        try:      # Claimant: the Void pays a small stipend
            from moonglade_gallery import telem_bump
            telem_bump("claims", claimed)
        except Exception:
            pass
    return {"claimed": claimed}


def _apply_kaisuuken(session, params, args):
    """Attach a free-card ticket id (`kaisuukenId`) to `params` in place, mirroring the
    web client. Precedence: explicit --kaisuuken-id > --no-card (skip) > auto-match via
    /v2/kaisuuken/check. Returns the attached id ('' if none). The card is only consumed
    when the task is actually submitted; this just picks the id. Logs what it did.

    The auto-match check retries once on failure, then ABORTS (raises PixAIError) rather
    than falling through to "no card -> pay credits". match_kaisuuken's normal fail-soft
    contract is right for read-only/preview callers, but wrong here: this is the last
    check before real money moves, and a transient glitch is not the same fact as "no
    free card exists" -- treating them the same silently spends credits on a generation
    that may have just been shown as free. Aborting surfaces the problem instead of
    guessing with the user's money (audit: `fail-open`, 2026-07-21)."""
    explicit = (getattr(args, "kaisuuken_id", "") or "").strip()
    if explicit:
        params["kaisuukenId"] = explicit
        print("  attaching your --kaisuuken-id (free card): {}".format(explicit))
        return explicit
    if getattr(args, "no_card", False):
        print("  --no-card: not using a free card (this WILL spend credits).")
        return ""
    best = None
    check_err = None
    for attempt in range(2):
        try:
            best = match_kaisuuken(session, params, enrich=True, raise_on_error=True)
            check_err = None
            break
        except (PixAIError, ValueError) as e:
            check_err = e
            if attempt == 0:
                time.sleep(1.5)
    if check_err is not None:
        # On-theme wording: mirrors the "job lost"
        # message PixAI's own site shows on a similar random failure, rather than a raw
        # technical error -- still refuses to guess and silently spend credits, just
        # says so in the app's own voice instead of engineer-speak.
        raise PixAIError(
            "Lost to the Void -- the free-card check didn't come back before submitting, "
            "so nothing was spent. Wait a moment and try again. ({})".format(check_err))
    if best and best.get("id"):
        params["kaisuukenId"] = best["id"]
        print("  free card matches ({}) -> attaching it; this costs 0 credits "
              "(card expires {}).".format(best.get("name") or "card",
                                          (best.get("expiresAt") or "never")[:10]))
        return best["id"]
    print("  no matching free card -> this will spend credits.")
    return ""


def _preview_card_note(args, params):
    """In a PREVIEW, tell the user the real credit cost and whether a free card covers it --
    read-only /v2/kaisuuken/check + /v2/task-price (no spend, no upload). Fails soft (stays
    silent) if offline or unauthenticated, so previews still work with no network."""
    def _fmt(n):
        return "~{:,} credits".format(n) if n is not None else "credits"
    if getattr(args, "no_card", False):
        try:
            session = _make_session(getattr(args, "token", None))
            price = price_task(session, params)
        except Exception:
            price = None
        print("--no-card set: this WILL spend {} on --confirm even if a card matches.".format(_fmt(price)))
        return
    explicit = (getattr(args, "kaisuuken_id", "") or "").strip()
    if explicit:
        print("A free card (--kaisuuken-id) will be attached on --confirm -> 0 credits.")
        return
    try:
        session = _make_session(getattr(args, "token", None))
        best = match_kaisuuken(session, params)
        price = price_task(session, params)
    except Exception:
        return  # offline / no key -- stay silent, preview is still valid
    if best and best.get("id"):
        saved = " (saves {})".format(_fmt(price)) if price else ""
        print("FREE: a matching card covers this -- with --confirm it costs 0 credits{} "
              "(card expires {}).".format(saved, (best.get("expiresAt") or "never")[:10]))
    else:
        print("NO FREE CARD matches -- with --confirm this will cost {}.".format(_fmt(price)))


def run_cards(args):
    """Print the account's free-generation cards (kaisuuken) via GET /v2/kaisuuken/summary.
    Read-only. Cards ARE auto-applied by this tool now: on --confirm we call
    /v2/kaisuuken/check for the matching ticket id and attach it (0 credits), exactly like
    the website. Pass --no-card to force paying credits, or --kaisuuken-id to force one."""
    session = _make_session(getattr(args, "token", None))
    cards = list_kaisuukens(session)
    if not cards:
        print("No free cards found (read-only; nothing was spent).")
        return {"cards": 0}
    print("Free-generation cards (kaisuuken) -- model-locked. Auto-applied on --confirm; a\n"
          "matching card makes that generation cost 0 credits (use --no-card to opt out):\n")
    total = 0
    for c in cards:
        total += int(c.get("count") or 0)
        model = c["model_version_id"] or ("/".join(c["task_types"]) or "-")
        print("  {:>3}x  {:<22} {:<13} model={:<20} exp {}".format(
            c.get("count") or 0, c.get("name"), "[" + c["category"] + "]",
            model, str(c["expires"])[:10]))
    print("\n{} free generations total. The matching card is attached automatically when you\n"
          "generate on its model (nearest-expiry first):".format(total))
    print("  Tsubaki.2 card  -> --generate         (default model already matches)")
    print("  Edit Pro card   -> --edit-image       (default model already matches)")
    print("  Reference Pro   -> --generate --model 1948514378441961474")
    return {"cards": len(cards), "total": total}


def run_reconcile_deleted(args):
    """Find catalog rows whose PixAI task no longer exists in your live feed -- i.e.
    generations you deleted on the website -- and flag them (deleted_remote='1') so
    the gallery can surface them for a local prune. Closes the cloud->local delete
    drift. Advisory: re-running refreshes the flags. Skips imports (no task) and
    very-recent rows (a fresh generation may not have propagated to the feed yet)."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    _prog = getattr(args, "progress", None)

    print("Scanning your live PixAI feed for existing task ids...")
    live, before, page = set(), None, 0
    while True:
        conn = find_connection(gql(session, page_variables(
            getattr(args, "page_size", 250) or 250, before)))
        if not conn:
            break
        edges = conn.get("edges") or []
        if not edges:
            break
        for e in edges:
            tid = (e.get("node") or {}).get("id")
            if tid:
                live.add(str(tid))
        page += 1
        vlog("reconcile: page {}, {} live tasks so far".format(page, len(live)))
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasPreviousPage"):
            break
        before = pi.get("startCursor")
    print("Live tasks in your feed: {:,}".format(len(live)))
    if not live:
        raise PixAIError("Live feed returned no tasks -- aborting so we don't flag "
                         "your whole catalog by mistake.")

    grace = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 2 * 86400))
    rows = load_catalog(db_path)
    flagged = cleared = 0
    for r in rows:
        tid = (r.get("task_id") or "").strip()
        gone = (tid and tid not in live and (r.get("source") or "") != "local"
                and (r.get("created_at") or "") < grace)
        was = r.get("deleted_remote") == "1"
        if gone and not was:
            r["deleted_remote"] = "1"; flagged += 1
        elif not gone and was:
            r["deleted_remote"] = ""; cleared += 1
        else:
            r["deleted_remote"] = "1" if gone else ""
    save_catalog(db_path, rows)
    print("Flagged {:,} row(s) as deleted-on-PixAI; cleared {:,} stale flag(s).".format(
        flagged, cleared))
    print("Review in the gallery: Source -> 'Deleted on PixAI', then bulk Delete (local).")
    return {"live": len(live), "flagged": flagged, "cleared": cleared}


def _count_backup_images(out):
    """Count the ORIGINAL image files on disk, split from preview thumbnails. The naive
    rglob-for-_IMAGE_EXTS double-counts because gallery/thumbs/<id>.jpg is one .jpg per image --
    which made 'files on disk' look ~2x the catalog. Excludes gallery/ (thumbs) and _duplicates/
    (quarantined). Returns (originals_count, originals_bytes, thumbnail_count)."""
    out = Path(out)
    skip = (out / "gallery", out / "_duplicates")
    n = b = thumbs = 0
    for p in out.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS or p.name.endswith(".part"):
            continue
        if any(s in p.parents for s in skip):
            if (out / "gallery") in p.parents:
                thumbs += 1
            continue
        n += 1
        try:
            b += p.stat().st_size
        except OSError:
            pass
    return n, b, thumbs


def run_rebuild_similar(args):
    """--rebuild-similar: drop + re-embed the visual-similarity ('Similar') index from
    scratch off the on-disk backup. Cures a corrupted/duplicate-index table by building
    ONE clean named index. Uses the shared progress callback (terminal bar + Control Panel
    marker). No network; needs torch/pixeltable. Run it when the gallery is NOT serving
    Similar queries (both touch the same embedded Postgres)."""
    try:
        import moonglade_similar as ps
    except Exception as e:
        sys.exit("Similar index unavailable (pixeltable/torch not installed): {}".format(e))
    if not ps.is_available():
        sys.exit("Similar index needs torch -- install the ML deps (torch/transformers/pixeltable).")
    out = Path(args.out)
    if not out.exists():
        sys.exit("No backup dir at {}.".format(out))
    print("Rebuilding the Similar index from {} -- drops the old table, re-embeds every image.".format(out))
    n = ps.rebuild(ps.scan_dir(out), progress=getattr(args, "progress", None))
    print()  # finish the \r progress line
    print("Similar index rebuilt: embedded {:,} images ({:,} in index, {} skipped).".format(
        n, ps.count(), ps.sync.last_errors))


def run_sync_similar(args):
    """--sync-similar: TOP UP the visual-similarity index -- embed only images it doesn't
    already have. The incremental counterpart to --rebuild-similar.

    This exists because sync() was always incremental (it skips media_ids already in the index)
    while the only way to reach it was rebuild(), which DROPS the table first. So the sole
    available action was also the most destructive one, and after an interrupted build the
    obvious move threw away every row that had survived.

    Measured on the owner's library, 2026-07-26, after a machine-wide memory exhaustion killed a
    rebuild at 75%: topping up the missing 8,706 images took 11.7 min, against ~38 min to
    re-embed all 35,106 from scratch -- and it could not lose the 26,400 rows already there,
    whereas a fresh rebuild dying again would have left strictly less than it started with.

    Prefer this. Reach for --rebuild-similar only to cure an index that is actually broken
    (duplicate/corrupt), not merely incomplete. No network; needs torch/pixeltable. Run it while
    the gallery is NOT serving Similar queries -- both use the same embedded Postgres."""
    try:
        import moonglade_similar as ps
    except Exception as e:
        sys.exit("Similar index unavailable (pixeltable/torch not installed): {}".format(e))
    if not ps.is_available():
        sys.exit("Similar index needs torch -- install the ML deps (torch/transformers/pixeltable).")
    out = Path(args.out)
    if not out.exists():
        sys.exit("No backup dir at {}.".format(out))
    before = ps.count()
    print("Topping up the Similar index from {} -- {:,} already indexed, embedding only what's "
          "missing.".format(out, before))
    n = ps.sync(ps.scan_dir(out), progress=getattr(args, "progress", None))
    print()  # finish the \r progress line
    after = ps.count()
    if not n:
        print("Similar index already complete: {:,} images, nothing to add.".format(after))
    else:
        print("Similar index topped up: embedded {:,} new images ({:,} -> {:,} in index, "
              "{} skipped).".format(n, before, after, ps.sync.last_errors))


def run_catalog_stats(args):
    """Summarize the existing catalog (no network needed)."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    _prog = getattr(args, "progress", None)
    rows = load_catalog(db_path)
    n = len(rows)
    total = downloaded = missing = pending = 0
    for i, row in enumerate(rows):
        total += 1
        if row.get("filename"):
            downloaded += 1
        elif not row.get("url"):
            missing += 1
        else:
            pending += 1
        if _prog and (i % 1000 == 0 or i + 1 == n):
            _prog(i + 1, n)
    # paid_credit is a TASK-level cost stamped on each of the task's media rows --
    # tally once per task_id (a 4-image batch is ONE spend), never per row. Rows
    # with '' never tracked a cost and stay out of the tally entirely.
    task_cost = {}
    for row in rows:
        pc = (row.get("paid_credit") or "").strip()
        tid = row.get("task_id") or row.get("media_id")
        if pc and tid not in task_cost:
            try:
                task_cost[tid] = int(float(pc))
            except ValueError:
                pass
    print("Catalog: {}".format(db_path))
    print("Total image entries : {}".format(total))
    print("  downloaded files  : {}".format(downloaded))
    print("  resolved, pending : {}".format(pending))
    print("  no URL (missing)  : {}".format(missing))
    if task_cost:
        print("Credits tracked     : {:,} spent across {:,} tasks ({:,} free)".format(
            sum(task_cost.values()), len(task_cost),
            sum(1 for v in task_cost.values() if v == 0)))
    _print_meta_coverage(rows, total)
    disk_count, disk_bytes, thumb_count = _count_backup_images(out)
    if disk_count:
        print("Image files on disk : {}  ({})".format(disk_count, _format_size(disk_bytes)))
    if thumb_count:
        print("  + {} preview thumbnails (gallery/thumbs, not originals)".format(thumb_count))


# Columns whose EMPTINESS unambiguously means "never fetched". Deliberately NOT `loras`
# or `negative_prompt`: a generation with no LoRAs and no negative prompt stores those blank
# too, so a blank one cannot be told apart from one that was never filled, and reporting them
# as a coverage gap would send you off to re-fetch tasks that are already complete.
#
# `paid_credit` IS unambiguous despite free generations existing -- a free task stores "0",
# and only a never-tracked one stores "".
_META_COVERAGE = (
    ("full metadata", "prompt_full", "--backfill-full-meta"),
    ("model id", "model_id", "--backfill-full-meta"),
    ("model name", "model_name", "--backfill-full-meta"),
)


def _print_meta_coverage(rows, total):
    """How much of the catalog actually carries its metadata, and what a sweep would cost.

    Without this the stats screen can say "35,133 entries, all downloaded" about a catalog in
    which not one row knows which model made it -- the counters only ever described FILES.
    Coverage is what decides whether a sweep is due, and the unique-task count is what it
    costs: metadata is fetched once per task, so a 4-image batch is one call, not four.
    """
    if not total:
        return
    print("Metadata coverage   :")
    worst_missing_tasks = 0
    for label, col, fix in _META_COVERAGE:
        have = sum(1 for r in rows if (r.get(col) or "").strip())
        gap = [r for r in rows if not (r.get(col) or "").strip()]
        tasks = len({r.get("task_id") for r in gap if r.get("task_id")})
        worst_missing_tasks = max(worst_missing_tasks, tasks)
        line = "  {:<17}: {:,} / {:,} ({:.0f}%)".format(label, have, total,
                                                        100.0 * have / total)
        if gap:
            line += "  -- {:,} missing across {:,} tasks".format(len(gap), tasks)
        print(line)
    # Locally imported files have no PixAI task behind them, so they can NEVER carry a model
    # and are not a gap to chase. Counted separately rather than silently deflating the
    # percentages above, which would make a complete catalog look permanently short.
    local = sum(1 for r in rows if (r.get("source") or "").strip() == "local")
    if local:
        print("  {:<17}: {:,} imported locally -- no PixAI task, so no model to fetch"
              .format("of which", local))
    if worst_missing_tasks:
        print("  Fill them with    : --backfill-full-meta --workers 8"
              "   (resumable; skips rows already filled)")
    costed = sum(1 for r in rows if (r.get("paid_credit") or "").strip())
    if costed < total:
        print("  Cost history      : add --with-credit to recover spend on older tasks")


def _parallel_map(items, work_fn, workers=1, progress=None, delay=0.0, on_error=None):
    """Run work_fn(item) over items, yielding (item, result) as each finishes.

    workers<=1 runs serially, sleeping `delay` between items. Higher uses a bounded thread
    pool for latency-bound network calls -- and STILL honours `delay`, as a global floor on
    the interval between request starts, not a per-thread one. It used to be dropped
    entirely on the parallel path ("concurrency itself paces"), which meant `--workers 8`
    turned a deliberately paced request stream into eight threads firing as fast as they
    completed. Being polite to PixAI's servers is a standing rule of this project, and it
    should not switch itself off because a flag was passed. The pace is global, so raising
    --workers now buys latency hiding up to that ceiling rather than a bigger burst; lower
    --delay if you genuinely want more throughput, and know that you are choosing it.

    A worker's exception yields a None result rather than crashing the run -- but it is
    NEVER swallowed silently: `on_error(item, exc)` is called with it first. It used to be
    discarded, and a real 17,289-task backfill consequently reported "16,044 failed" with no
    reason attached to any of them, which is a number you cannot act on.

    progress(done, total, 0) is called on THIS thread, so the caller may safely mutate
    shared state in the yield body.
    """
    items = list(items)
    total = len(items)
    if workers <= 1:
        for i, it in enumerate(items):
            try:
                res = work_fn(it)
            except Exception as e:                       # noqa: BLE001 -- reported, not hidden
                res = None
                if on_error:
                    on_error(it, e)
            yield it, res
            if progress:
                progress(i + 1, total, 0)
            if delay:
                time.sleep(delay)
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    gate = threading.Lock()
    next_start = [0.0]

    def _paced(it):
        if delay:
            # One global slot at a time: each worker waits for the next free slot and books
            # the one after it, so the whole pool starts at most one request per `delay`
            # seconds no matter how many threads are in it.
            with gate:
                now = time.monotonic()
                wait = max(0.0, next_start[0] - now)
                next_start[0] = max(now, next_start[0]) + delay
            if wait:
                time.sleep(wait)
        return work_fn(it)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_paced, it): it for it in items}
        for fut in as_completed(futs):
            it = futs[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:                       # noqa: BLE001 -- reported, not hidden
                res = None
                if on_error:
                    on_error(it, e)
            yield it, res
            if progress:
                progress(done, total, 0)


def run_backfill_meta(args):
    """Fill in missing url/width/height for catalog rows via resolve_media().
    Safe to re-run -- skips rows that already have all three fields."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    rows = load_catalog(db_path)

    to_fill = [r for r in rows if not (r.get("url") and r.get("width") and r.get("height"))]
    print("Found {:,} rows missing url/width/height (out of {:,} total).".format(
        len(to_fill), len(rows)))
    if not to_fill:
        print("Nothing to backfill.")
        return

    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Resolving with {} parallel workers.".format(workers))
    updated = failed = 0
    _prog = getattr(args, "progress", None)
    for row, res in _parallel_map(to_fill, lambda r: resolve_media(session, r["media_id"]),
                                  workers, _prog, delay=args.delay):
        url, info = res if res else (None, {})
        if url:
            row["url"] = url
            row["width"] = str(info.get("width") or "")
            row["height"] = str(info.get("height") or "")
            updated += 1
        else:
            failed += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  {:,}/{:,}  updated {:,}  failed {:,}  ".format(
                updated + failed, len(to_fill), updated, failed))
            sys.stdout.flush()

    print("\nWriting catalog...")
    save_catalog(db_path, to_fill)
    print("Done. Updated {:,} rows, {:,} still missing.".format(updated, failed))


def run_backfill_full_meta(args):
    """Fill in prompt_full/natural_prompt/seed/steps/sampler/cfg_scale/model_id/model_name
    for catalog rows missing them, using getTaskById + getGenerationModelByVersionId.
    Also fills url/width/height from the task's media object as a free side effect.
    Safe to re-run -- skips rows that already have prompt_full."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))

    if not TASK_DETAIL_HASH:
        # Defensive only: TASK_DETAIL_HASH ships with a working built-in default, so this
        # fires only if that default is stripped or blanked in config.json.
        raise PixAIError(
            "TASK_DETAIL_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current getTaskById "
            "sha256Hash from DevTools if the hash rotated (see RECAPTURE at the bottom of "
            "this file).")

    rows = load_catalog(db_path)
    with_loras = getattr(args, "with_loras", False)
    with_credit = getattr(args, "with_credit", False)

    # Work per unique task_id (one API call covers all media in that task).
    # --with-loras also re-processes rows that have full meta but a blank `loras`
    # column (e.g. backfilled before LoRA tracking existed). It re-fetches their
    # getTaskById to extract parameters.lora.
    # --with-credit is the same pattern for `paid_credit` (added 2026-07-23):
    # getTaskById returns paidCredit for historical tasks, so rows cataloged before
    # cost tracking existed can recover their real spend. Opt-in, like --with-loras,
    # because it re-fetches every not-yet-costed task (long run on a big catalog).
    # These four come ONLY from a getTaskById fetch -- the listing feed carries neither.
    # A row holding none of them has never seen a task detail, whatever else it holds.
    _DETAIL_ONLY = ("model_id", "steps", "sampler", "cfg_scale")

    def _needs(r):
        if not r.get("prompt_full"):
            return True
        # prompt_full alone is NOT proof the detail was fetched. Rows exist carrying a
        # prompt and a seed and nothing else -- no model, no steps, no sampler, no CFG --
        # and while prompt_full was the sole sentinel every one of them was skipped
        # forever: the sweep printed "Nothing to backfill" over a catalog that could not
        # say which model made any of it. Measured on a real catalog before this changed:
        # 788/800 rows had a prompt, 5/800 had a model id, and a backfill was a no-op.
        # A task that genuinely returns none of the four is re-fetched on a later sweep
        # too; that is a bounded, idempotent cost, and far cheaper than the silence.
        if not any((r.get(c) or "").strip() for c in _DETAIL_ONLY):
            return True
        if with_loras and r.get("task_id") and not r.get("loras"):
            return True
        if with_credit and r.get("task_id") and not r.get("paid_credit"):
            return True
        return False
    needs_fill = [r for r in rows if _needs(r)]
    # Named separately in the count below because it is the case that used to be invisible.
    stalled = [r for r in needs_fill
               if r.get("prompt_full")
               and not any((r.get(c) or "").strip() for c in _DETAIL_ONLY)]
    task_ids = list(dict.fromkeys(r["task_id"] for r in needs_fill if r.get("task_id")))
    print("Found {:,} rows to fill across {:,} unique tasks{}{}.".format(
        len(needs_fill), len(task_ids), " (incl. LoRAs)" if with_loras else "",
        " (incl. credit costs)" if with_credit else ""))
    if stalled:
        print("  {:,} of them have a prompt but no model/steps/sampler/CFG -- these were "
              "skipped by every earlier backfill.".format(len(stalled)))
    if not task_ids:
        print("Nothing to backfill.")
        return

    # Fetch and cache full meta per task_id (parallelizable -- each task is an
    # independent getTaskById round-trip).
    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Fetching with {} parallel workers.".format(workers))

    def _fetch_task(tid):
        task_data = task_detail_gql(session, tid)
        fm = extract_full_meta(task_data)
        if fm.get("model_id"):
            fm["model_name"] = model_name_gql(session, fm["model_id"])
        fm["loras"] = resolve_loras(session, task_data)
        media_obj = (task_data or {}).get("media") or {}
        if media_obj:
            by_v = {str(u.get("variant", "")).upper(): u["url"]
                    for u in (media_obj.get("urls") or []) if isinstance(u, dict) and u.get("url")}
            for pref in ("PUBLIC", "ORIGINAL", "ORIG", "FULL", "THUMBNAIL"):
                if pref in by_v:
                    fm["_media_url"] = by_v[pref]
                    break
            fm["_media_width"] = str(media_obj.get("width") or "")
            fm["_media_height"] = str(media_obj.get("height") or "")
        return fm

    task_cache = {}  # task_id -> full meta dict
    fetched = failed = 0
    _prog = getattr(args, "progress", None)
    # Failures are counted BY REASON. A bare total is unactionable: the same "16,044 failed"
    # covers a rotated hash, an expired key, a rate limit and a genuinely deleted task, and
    # those have four different answers.
    err_kinds = {}

    def _note_error(tid, exc):
        key = "{}: {}".format(type(exc).__name__, str(exc).strip().splitlines()[0][:120]
                              if str(exc).strip() else "(no message)")
        err_kinds[key] = err_kinds.get(key, 0) + 1

    errored = 0

    for tid, fm in _parallel_map(task_ids, _fetch_task, workers, _prog, delay=args.delay,
                                 on_error=_note_error):
        fm = fm or {}
        task_cache[tid] = fm
        if fm.get("prompt_full"):
            fetched += 1
        else:
            failed += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  Tasks {:,}/{:,}  fetched {:,}  failed {:,}  ".format(
                fetched + failed, len(task_ids), fetched, failed))
            sys.stdout.flush()

    print("\nApplying to {:,} catalog rows...".format(len(rows)))
    for row in rows:
        fm = task_cache.get(row.get("task_id"), {})
        if not fm:
            continue
        for f in _FULL_META_FIELDS:
            if not row.get(f) and fm.get(f):
                row[f] = fm[f]
        # Backfill url/width/height from task media as bonus
        if not row.get("url") and fm.get("_media_url"):
            row["url"] = fm["_media_url"]
        if not row.get("width") and fm.get("_media_width"):
            row["width"] = fm["_media_width"]
        if not row.get("height") and fm.get("_media_height"):
            row["height"] = fm["_media_height"]

    save_catalog(db_path, rows)
    # "failed" used to mean two unrelated things at once: the fetch threw, or it returned
    # fine and simply carried no prompt (a deleted task, or a kind that records none). Those
    # have completely different answers, and reporting one number for both had us guessing
    # at a 16,044 and then at a 157. Counted apart now.
    errored = sum(err_kinds.values())
    empty = failed - errored
    print("Done. Fetched {:,} tasks, {:,} failed, catalog updated.".format(fetched, failed))
    if empty > 0:
        print("  {:,} of those returned fine but carried no prompt -- a deleted task, or a "
              "kind that records none. Nothing is wrong with them.".format(empty))
    if err_kinds:
        print("Why they failed:")
        for kind, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:5]:
            print("  {:>7,}  {}".format(n, kind))
        worst = max(err_kinds.values())
        if worst >= 20 and failed > fetched:
            # A majority-failure run is not a partial success, and re-running it unchanged
            # just repeats it. Say so, and say the two things that are actually true: it is
            # resumable, so nothing already fetched is refetched, and a slower pace is the
            # first thing to try when a server is pushing back.
            print("  Most of this run failed. Nothing fetched was lost -- the backfill is "
                  "resumable and skips what it already filled -- but re-running it exactly "
                  "as it was will fail the same way.")
            print("  If that reason looks like the server pushing back, try a gentler pace: "
                  "--workers 2 --delay 1")


def _check_time_capsule(created_at, out_dir):
    """Time Capsule feat: a NEWLY-downloaded piece created >2 years ago. Fires
    only on the download event, never on a full-catalog rescan (old rows already
    on disk must not earn it). Fail-soft; never slows the download loop."""
    try:
        from datetime import datetime
        s = str(created_at or "")[:19]
        if not s:
            return
        if (datetime.now() - datetime.fromisoformat(s)).days > 730:
            from moonglade_gallery import telem_flag
            telem_flag("old_piece_backed_up", out_dir=out_dir)
    except Exception:
        pass


def run_download(args, progress=None):
    """Run the full paginated download + catalog loop.

    progress: optional callable(done: int, total: int) invoked after each
    image is processed (downloaded or skipped). Used by the GUI progress bar.
    When stdout is a real terminal and no progress callback is provided, a
    \r-overwriting ASCII progress bar is printed instead.
    """
    out = Path(args.out)
    img_dir = out / "images"
    raw_path = out / "raw_tasks.jsonl"
    db_path  = out / "catalog.db"

    # Ensure db exists and is populated (auto-migrates catalog.csv if needed)
    try:
        db_path = _ensure_db(out)
    except PixAIError:
        # Fresh install with no prior catalog — create empty db
        init_db(db_path)

    # Load existing catalog so prior-session rows are never lost
    known = {r["media_id"]: r for r in load_catalog(db_path) if r.get("media_id")}
    if known:
        print("Loaded {} existing catalog entries.\n".format(len(known)))

    use_full_meta = getattr(args, "full_meta", False)

    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))

    if use_full_meta and not TASK_DETAIL_HASH:
        # Defensive only: TASK_DETAIL_HASH ships with a working built-in default, so this
        # fires only if that default is stripped or blanked in config.json.
        raise PixAIError(
            "TASK_DETAIL_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current getTaskById "
            "sha256Hash from DevTools if the hash rotated (see RECAPTURE at the bottom of "
            "this file).")

    img_dir.mkdir(parents=True, exist_ok=True)

    # ONE fast tree walk at startup (os.scandir, ~free stat() on Windows): seed
    # the progress count AND build the on-disk media_id index. Resume is then an
    # O(1) dict lookup instead of an O(whole-tree) rglob per media_id -- the
    # latter made follow-up runs scale quadratically with collection size.
    # Prunes gallery/ thumbnails, _duplicates/ quarantine, and _deleted/ quarantine
    # (B11, audit 2026-07-21: without this a locally-purged media_id is still
    # indexed as "already done", so resume/--update never re-downloads it).
    already_done = 0
    disk_bytes = 0
    on_disk_by_mid = {}   # media_id -> Path of an existing full-res image

    def _iter_image_entries(root):
        skip_dirs = {"gallery", "_duplicates", DELETED_DIRNAME}
        stack = [str(root)]
        while stack:
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in skip_dirs:
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            yield e
            except OSError:
                continue

    if out.exists():
        _t_scan = time.monotonic()
        for e in _iter_image_entries(out):
            name = e.name
            if name.endswith(".part") or os.path.splitext(name)[1].lower() not in _IMAGE_EXTS:
                continue
            try:
                size = e.stat().st_size
            except OSError:
                size = None
            # A zero-byte file (an interrupted download that got far enough to create
            # the file but not to write it) must NOT count as "already done" here --
            # indexing it means it is skipped FOREVER: no --update/--sync ever
            # re-attempts a media_id already in this index, and
            # reconcile_catalog_with_disk's strict matcher (moonglade_gallery.py) finds
            # nothing wrong either, so the row's filename is left pointing at a dead
            # file with no signal to the user. A stat() race (size is None) is treated
            # as fine, matching prior behaviour -- we can't tell either way, and this
            # index has always erred toward "already done" on an unreadable stat.
            if size == 0:
                continue
            already_done += 1
            if size is not None:
                disk_bytes += size
            on_disk_by_mid.setdefault(media_id_of(name), Path(e.path))
        vlog("startup disk scan: {} image files ({}) indexed in {:.2f}s".format(
            already_done, _format_size(disk_bytes), time.monotonic() - _t_scan))
    # Progress counts items as the walk visits them (skips included), starting at
    # zero -- it must NOT be seeded with already_done, or the on-disk images get
    # counted twice (seed + re-check) and the bar overshoots past 100%.
    processed = 0

    if already_done:
        print("Resuming: {} image files already on disk ({}).\n".format(
            already_done, _format_size(disk_bytes)))

    # Progress denominator: avoid a full-history NETWORK pre-count on every run.
    # For a populated library the catalog size is an instant, good-enough estimate
    # (the progress bar already tolerates over/under). Only walk the API to count
    # on a fresh library (empty catalog) or when the user asks for --accurate-count.
    if getattr(args, "accurate_count", False) or not known:
        total_images = _quick_count(session)
    else:
        total_images = max(already_done, len(known))
        print("Library size (catalog estimate): ~{} images "
              "(use --accurate-count for an exact API count)\n".format(total_images))

    def _tick():
        nonlocal processed
        processed += 1
        if progress:
            progress(processed, total_images, dl["ok"])
        elif sys.stdout.isatty():
            sys.stdout.write(_progress_line(processed, total_images, dl["ok"]))
            sys.stdout.flush()

    if progress:
        progress(processed, total_images, 0)

    print("Walking your generation history (newest -> oldest)...")
    raw_f = open(raw_path, "w", encoding="utf-8")

    _full_meta_cache = {}  # task_id -> full meta dict

    before = None
    seen = 0
    written = set()   # media_ids written this session
    dl = {"ok": 0, "skip": 0, "missing": 0, "fail": 0}
    page = 0
    update_mode = getattr(args, "update", False)
    update_grace = getattr(args, "update_grace", 2)
    consecutive_known_pages = 0

    # Parallel downloads: only for the common flat-download case. collect_only does
    # no downloads, so it falls back to the serial path.
    workers = max(1, getattr(args, "workers", 1) or 1)
    parallel = (workers > 1
                and not getattr(args, "collect_only", False))
    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print("Parallel downloads: {} workers.\n".format(workers))

    def _row_for(meta, mid, full_meta, filename="", url="", w="", h=""):
        return {
            "task_id": meta["task_id"], "media_id": mid,
            "filename": filename, "url": url, "width": w, "height": h,
            "prompt_preview": meta["prompt_preview"],
            "status": meta["status"], "created_at": meta["created_at"],
            **_merge_full(full_meta, known.get(mid, {})),
        }

    try:
        while True:
            page += 1
            conn = find_connection(gql(session, page_variables(args.page_size, before)))
            if not conn:
                print("No connection; stopping.")
                break
            edges = conn.get("edges", [])
            if not edges:
                break
            print("Page {}: {} tasks (total {})".format(page, len(edges), seen + len(edges)))

            page_rows = []  # rows accumulated this page; upserted after each page
            page_new = 0    # media_ids on this page NOT already on disk (for --update)

            if parallel:
                # Pass 1 (serial, local): emit raw json, handle on-disk skips, and
                # build a worklist of media_ids that actually need fetching.
                worklist = []
                for edge in edges:
                    node = edge.get("node", edge)
                    raw_f.write(json.dumps(node, ensure_ascii=False) + "\n")
                    if _is_video_task_node(node):
                        continue   # video task: its poster still is NOT a standalone image
                    meta = extract_meta(node)
                    all_mids = media_ids_for(node)
                    full_meta = {}
                    if use_full_meta:
                        tid = meta["task_id"]
                        if tid not in _full_meta_cache:
                            task_data = task_detail_gql(session, tid)
                            fm = extract_full_meta(task_data)
                            if fm.get("model_id"):
                                fm["model_name"] = model_name_gql(session, fm["model_id"])
                            fm["loras"] = resolve_loras(session, task_data)
                            _full_meta_cache[tid] = fm
                            time.sleep(args.delay)
                        full_meta = _full_meta_cache.get(tid, {})
                    for mid in all_mids:
                        existing = on_disk_by_mid.get(mid)
                        if existing:
                            dl["skip"] += 1
                            k = known.get(mid, {})
                            row = _row_for(meta, mid, full_meta,
                                           filename=existing.name, url=k.get("url", ""),
                                           w=k.get("width", ""), h=k.get("height", ""))
                            row["prompt_preview"] = k.get("prompt_preview") or meta["prompt_preview"]
                            row["status"] = k.get("status") or meta["status"]
                            row["created_at"] = k.get("created_at") or meta["created_at"]
                            page_rows.append(row)
                            written.add(mid)
                            _tick()
                            continue
                        page_new += 1
                        stem = img_dir / build_stem_name(
                            meta["prompt_preview"], meta["task_id"], mid,
                            args.name_length, args.name_sep)
                        worklist.append({"meta": meta, "mid": mid, "stem": stem,
                                         "full_meta": full_meta})

                # Pass 2 (parallel): resolve + download. Only the per-item network
                # and file write run in threads; all shared state is mutated here
                # in the main thread as futures complete.
                def _work(item):
                    url, info = resolve_media(session, item["mid"])
                    if not url:
                        return item, "missing", "", info, None
                    status, path = download(
                        session, url, item["stem"],
                        convert=getattr(args, "convert", None),
                        jpeg_quality=getattr(args, "jpeg_quality", 92),
                        jpeg_bg=getattr(args, "jpeg_bg", "white"),
                        keep_webp=getattr(args, "keep_webp", False))
                    return item, status, url, info, path

                if worklist:
                    with ThreadPoolExecutor(max_workers=workers) as ex:
                        for fut in as_completed([ex.submit(_work, it) for it in worklist]):
                            item, status, url, info, path = fut.result()
                            meta, mid, full_meta = item["meta"], item["mid"], item["full_meta"]
                            w, h = info.get("width", ""), info.get("height", "")
                            if status == "missing":
                                dl["missing"] += 1
                                page_rows.append(_row_for(meta, mid, full_meta, w=w, h=h))
                            else:
                                dl[status] += 1
                                page_rows.append(_row_for(
                                    meta, mid, full_meta,
                                    filename=path.name if path else "", url=url, w=w, h=h))
                                if path and status in ("ok", "skip"):
                                    on_disk_by_mid[mid] = path
                                if status == "ok":
                                    _check_time_capsule(meta.get("created_at"), out)
                            written.add(mid)
                            _tick()

                if page_rows:
                    save_catalog(db_path, [carry_local_fields(r, known) for r in page_rows])
                seen += len(edges)
                if args.max and seen >= args.max:
                    print("Reached --max limit.")
                    break
                if update_mode:
                    if page_new == 0:
                        consecutive_known_pages += 1
                        if consecutive_known_pages >= update_grace:
                            print("\n--update: {} consecutive pages already on disk; "
                                  "stopping (older items are already downloaded)."
                                  .format(consecutive_known_pages))
                            break
                    else:
                        consecutive_known_pages = 0
                raw_f.flush()
                pi = conn.get("pageInfo", {})
                if not pi.get("hasPreviousPage"):
                    break
                before = pi.get("startCursor")
                time.sleep(args.delay)
                continue

            for edge in edges:
                node = edge.get("node", edge)
                raw_f.write(json.dumps(node, ensure_ascii=False) + "\n")
                if _is_video_task_node(node):
                    continue   # video task: its poster still is NOT a standalone image
                meta = extract_meta(node)
                all_mids = media_ids_for(node)

                # Fetch full task detail once per task_id (cached; batches cost 1 call)
                full_meta = {}
                if use_full_meta:
                    tid = meta["task_id"]
                    if tid not in _full_meta_cache:
                        task_data = task_detail_gql(session, tid)
                        fm = extract_full_meta(task_data)
                        if fm.get("model_id"):
                            fm["model_name"] = model_name_gql(session, fm["model_id"])
                        fm["loras"] = resolve_loras(session, task_data)
                        _full_meta_cache[tid] = fm
                        time.sleep(args.delay)
                    full_meta = _full_meta_cache.get(meta["task_id"], {})

                task_folder = img_dir
                for idx, mid in enumerate(all_mids):
                    existing = (None if getattr(args, "collect_only", False)
                                else on_disk_by_mid.get(mid))
                    if existing:
                        dl["skip"] += 1
                        k = known.get(mid, {})
                        page_rows.append({
                            "task_id":        k.get("task_id") or meta["task_id"],
                            "media_id":       mid,
                            "filename":       existing.name,
                            "url":            k.get("url", ""),
                            "width":          k.get("width", ""),
                            "height":         k.get("height", ""),
                            "prompt_preview": k.get("prompt_preview") or meta["prompt_preview"],
                            "status":         k.get("status") or meta["status"],
                            "created_at":     k.get("created_at") or meta["created_at"],
                            **_merge_full(full_meta, k),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    page_new += 1  # this media_id is not yet on disk
                    stem_name = build_stem_name(
                        meta["prompt_preview"], meta["task_id"], mid,
                        args.name_length, args.name_sep)
                    stem = task_folder / stem_name
                    url, info = resolve_media(session, mid)
                    w, h = info.get("width", ""), info.get("height", "")
                    if not url:
                        dl["missing"] += 1
                        page_rows.append({
                            "task_id": meta["task_id"], "media_id": mid,
                            "filename": "", "url": "", "width": w, "height": h,
                            "prompt_preview": meta["prompt_preview"],
                            "status": meta["status"], "created_at": meta["created_at"],
                            **_merge_full(full_meta, known.get(mid, {})),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    if getattr(args, "collect_only", False):
                        page_rows.append({
                            "task_id": meta["task_id"], "media_id": mid,
                            "filename": "", "url": url, "width": w, "height": h,
                            "prompt_preview": meta["prompt_preview"],
                            "status": meta["status"], "created_at": meta["created_at"],
                            **_merge_full(full_meta, known.get(mid, {})),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    status, path = download(
                        session, url, stem,
                        convert=getattr(args, "convert", None),
                        jpeg_quality=getattr(args, "jpeg_quality", 92),
                        jpeg_bg=getattr(args, "jpeg_bg", "white"),
                        keep_webp=getattr(args, "keep_webp", False))
                    dl[status] += 1
                    _tick()
                    page_rows.append({
                        "task_id": meta["task_id"], "media_id": mid,
                        "filename": path.name if path else "",
                        "url": url, "width": w, "height": h,
                        "prompt_preview": meta["prompt_preview"],
                        "status": meta["status"], "created_at": meta["created_at"],
                        **_merge_full(full_meta, known.get(mid, {})),
                    })
                    written.add(mid)
                    if path and status in ("ok", "skip"):
                        on_disk_by_mid[mid] = path  # keep index current within the run
                    if status == "ok":
                        _check_time_capsule(meta.get("created_at"), out)
                        time.sleep(args.delay)

            # Upsert this page's rows so progress is durable even on interrupt.
            # _carry() re-merges each row over its existing catalog row so a
            # re-pull never blanks local curation (collections/rating/tags/...).
            if page_rows:
                save_catalog(db_path, [carry_local_fields(r, known) for r in page_rows])

                seen += 1
                if args.max and seen >= args.max:
                    break

            raw_f.flush()
            if args.max and seen >= args.max:
                print("Reached --max limit.")
                break

            # Incremental --update: pages come newest -> oldest, so once we hit
            # a run of pages where everything is already on disk, the rest of the
            # history is older and already downloaded -> stop early. The grace
            # window tolerates occasional gaps (a few missing/failed items).
            if update_mode:
                if page_new == 0:
                    consecutive_known_pages += 1
                    if consecutive_known_pages >= update_grace:
                        print("\n--update: {} consecutive pages already on disk; "
                              "stopping (older items are already downloaded)."
                              .format(consecutive_known_pages))
                        break
                else:
                    consecutive_known_pages = 0

            pi = conn.get("pageInfo", {})
            if not pi.get("hasPreviousPage"):
                break
            before = pi.get("startCursor")
            time.sleep(args.delay)

    finally:
        raw_f.close()

    if not progress and sys.stdout.isatty() and processed:
        print()  # move past the \r progress bar line

    print("\nDone. Tasks seen: {}".format(seen))
    print("Images -> downloaded {}, skipped {}, missing {}, failed {}".format(
        dl["ok"], dl["skip"], dl["missing"], dl["fail"]))
    print("Catalog: {}\nRaw: {}\nImages: {}".format(db_path, raw_path, img_dir))
    if dl["fail"]:
        # D-4: exit code is UNCHANGED by design (still 0 -- a partial failure must not
        # break a Task Scheduler wrapper over one transient blip). This is purely a
        # louder, harder-to-miss console notice, plus (below) a machine-readable marker
        # for anything watching stdout (the Panel subprocess reader).
        print("\n*** FINISHED WITH ERRORS: {} file(s) failed to download after retries "
              "-- just re-run, finished files are skipped. Exit code is still 0 by "
              "design. ***".format(dl["fail"]))
        if os.environ.get("MOONGLADE_PROGRESS") == "1":
            print("{}{}".format(PANEL_WARN_PREFIX, dl["fail"]), flush=True)
    return dl


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_rebuild_thumbs(args):
    """--rebuild-thumbs: one uniform thumbnail pass over the whole catalog.
    Images are re-rendered from their originals at today's size/quality settings
    (OVERWRITTEN in place, so the gallery never goes blank mid-run -- this is
    what kills years of quality drift), poster-less videos get a local ffmpeg
    frame extract, and thumbs whose media left the catalog are swept."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    from moonglade_gallery import build_thumbnails, load_catalog
    thumb_dir = out / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    rows = load_catalog(db_path)
    known = {r.get("media_id") for r in rows if r.get("media_id")}
    swept = 0
    for f in thumb_dir.glob("*.jpg"):
        if f.stem not in known:
            try:
                f.unlink()
                swept += 1
            except OSError:
                pass
    if swept:
        print("Swept {:,} orphaned thumbnails (media no longer in the catalog).".format(swept))
    print("Rebuilding thumbnails for {:,} catalog rows (images overwritten in place; "
          "poster-less videos get an ffmpeg frame; existing video posters kept)...".format(len(rows)))
    _prog = getattr(args, "progress", None)
    build_thumbnails(rows, out, thumb_dir, force=True,
                     progress_cb=((lambda d, t, _p: _prog(d, t)) if _prog else None),
                     workers=max(1, int(getattr(args, "workers", 4) or 4)))
    print("\nThumbnail rebuild complete.")
    return {"swept": swept, "rows": len(rows)}


# ---------------------------------------------------------------------------
# Web gallery login account management (CLI-only -- see the module note above
# get_or_create_secret_key). Deliberately interactive-only (no --password flag):
# a password never belongs in shell history, a saved script, or a process list.
# ---------------------------------------------------------------------------

def run_add_web_user(args):
    """CLI: add or update one gallery web-login account. Prompts for username
    (plain input -- not secret) and password (getpass.getpass -- never echoed to
    the terminal, never printed, never logged), then hashes and persists it via
    add_or_update_web_user. Refuses to save on a blank entry or a confirmation
    mismatch."""
    username = input("Username: ").strip()
    if not username:
        sys.exit("Username must not be empty. Nothing was saved.")
    password = getpass.getpass("Password: ")
    if not password:
        sys.exit("Password must not be empty. Nothing was saved.")
    problem = password_problem(password)
    if problem:
        # Same policy the web forms enforce -- this is the recovery path, not a
        # back door around the rules the Users tab applies.
        sys.exit("{} Nothing was saved.".format(problem))
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        sys.exit("Passwords did not match. Nothing was saved.")
    replaced = add_or_update_web_user(username, password)
    print("{} web-login account '{}'.".format("Updated" if replaced else "Added", username))


def run_remove_web_user(args):
    """CLI: remove one gallery web-login account by username."""
    username = args.remove_web_user
    if remove_web_user(username):
        print("Removed web-login account '{}'.".format(username))
    else:
        print("No web-login account named '{}'.".format(username))


def run_list_web_users(args):
    """CLI: list gallery web-login USERNAMES only -- never prints password hashes."""
    users = list_web_users()
    if not users:
        print("No web-login accounts yet. Add one with --add-web-user.")
        return
    print("Web-login accounts ({}):".format(len(users)))
    for u in users:
        print("  " + u["username"])


def main():
    ap = argparse.ArgumentParser(description="Back up your own PixAI gallery.")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    ap.add_argument("--rebuild-thumbs", action="store_true",
                    help="regenerate EVERY image thumbnail at the current size/quality "
                         "settings (fixes quality drift across eras), extract posters for "
                         "poster-less videos via ffmpeg, and sweep orphaned thumbs. "
                         "Overwrites in place -- the gallery never goes blank.")
    ap.add_argument("--sync", action="store_true",
                    help="One-shot sync, in five steps: incremental pull WITH full metadata "
                         "(equivalent to --update --full-meta), re-resolve any unlabeled "
                         "model names, fill any catalog rows still missing "
                         "prompts/seeds/models, build any missing preview thumbnails, and "
                         "reconcile rows deleted on PixAI. Every step is idempotent, so "
                         "re-running on a clean catalog costs almost nothing.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print timestamped diagnostics (per-page fetch, per-image "
                         "resolve/download timing, disk-scan time) so you can see what a "
                         "long-running operation is doing")
    ap.add_argument("--token",
                    help="Bearer token for PixAI API auth (overrides PIXAI_TOKEN env var "
                         "and token.txt)")
    ap.add_argument("--delete-task", nargs="+", metavar="TASK_ID", default=None,
                    help="DELETE the given generation task id(s) from your PixAI account "
                         "(irreversible). Dry-run unless --apply is also given; then asks "
                         "for typed confirmation unless --yes. Local backups are untouched. "
                         "(DELETE_TASK_HASH ships with a working default; no config.json setup needed.)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive confirmation for --delete-task --apply "
                         "(use with care; deletion cannot be undone)")
    ap.add_argument("--out", default="pixai_backup",
                    help="output folder for images and catalog (default: pixai_backup)")
    ap.add_argument("--page-size", type=int, default=250,
                    help="tasks per API page (default 250; fewer round-trips. Keep <~8000)")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel download workers (default 4). 1 = serial/polite. "
                         "Higher saturates bandwidth on bulk first-time pulls; ignored for "
                         "--collect-only.")
    ap.add_argument("--max", type=int, default=0, help="stop after N tasks (0=all)")
    ap.add_argument("--update", action="store_true",
                    help="incremental follow-up run: stop paging once a run of pages is "
                         "already fully on disk (newest-first, so older items are already "
                         "downloaded). Much faster than re-walking the whole history.")
    ap.add_argument("--update-grace", type=int, default=2,
                    help="with --update, number of consecutive all-on-disk pages before "
                         "stopping (default 2; raise if your history has gaps)")
    ap.add_argument("--accurate-count", action="store_true",
                    help="walk the whole API to count library size for the progress bar "
                         "(slow). Default uses the catalog size as a fast estimate.")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="seconds to wait between API requests (default: 0.4)")
    ap.add_argument("--probe", action="store_true",
                    help="show first page + auto-detect the full-res variant, then exit")
    ap.add_argument("--count", action="store_true",
                    help="tally total tasks + images via the API (no downloads), then exit")
    ap.add_argument("--count-page-size", type=int, default=5000,
                    help="page size used by --count (bigger = fewer requests; "
                         "server errors above ~10000 so default is 5000)")
    ap.add_argument("--catalog-stats", action="store_true",
                    help="summarize the existing catalog.db (counts only), then exit")
    ap.add_argument("--collect-only", action="store_true",
                    help="scan and catalog images without downloading files")
    ap.add_argument("--name-length", type=int, default=60,
                    help="max characters of the prompt used in filenames (default 60)")
    ap.add_argument("--name-sep", default="_", choices=["_", "-"],
                    help="word separator in filenames (default _)")
    ap.add_argument("--convert", default=None, choices=["png", "jpeg", "jpg"],
                    help="convert each downloaded webp to png or jpeg (needs Pillow). "
                         "Replaces the .webp unless --keep-webp is set.")
    ap.add_argument("--jpeg-quality", type=int, default=92,
                    help="JPEG quality 1-100 when --convert jpeg (default 92)")
    ap.add_argument("--jpeg-bg", default="white", choices=["white", "black"],
                    help="background to flatten transparency onto for JPEG")
    ap.add_argument("--keep-webp", action="store_true",
                    help="keep the original .webp after converting")
    ap.add_argument("--convert-existing", action="store_true",
                    help="convert all already-downloaded .webp files to --convert format "
                         "(default png). No token needed. Supports --dry-run and --keep-webp.")
    ap.add_argument("--organize", action="store_true",
                    help="normalize the WHOLE backup into YYYY-MM/ month folders with "
                         "descriptive filenames (no batch subfolders); writes a reversible "
                         "move-manifest. Idempotent + dry-runnable. Then exit")
    ap.add_argument("--organize-adv", action="store_true",
                    help="alias for --organize (kept for back-compat)")
    ap.add_argument("--undo-organize", action="store_true",
                    help="revert the last --organize-adv run using organize_manifest.csv "
                         "(move files back to their old paths), then exit")
    ap.add_argument("--embed-metadata", action="store_true",
                    help="with --organize-adv, embed prompt/IDs/date into PNG/JPEG files "
                         "(off by default; useful when pulling images into other apps)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --organize / --organize-adv / --undo-organize, show the "
                         "plan without moving anything")
    # ON BY DEFAULT since 2026-07-25. This is a backup tool whose point is the catalog, and
    # full metadata was the one thing you only got by asking: a plain run or --update left
    # rows with no prompt, no seed and no model, and the gap was invisible until something
    # needed it. (Measured on the owner's own library: a stats screen reporting "35,133
    # entries, all downloaded" over rows that could not say which model made them.) --sync
    # has always implied it; now every pull does, and the flag stays accepted so existing
    # scripts, docs and the Panel's whitelisted argv keep working unchanged.
    ap.add_argument("--full-meta", dest="full_meta", action="store_true", default=True,
                    help="(now the DEFAULT) fetch full prompt, seed, steps, sampler, CFG and "
                         "model name for each task via a second API call. One extra call per "
                         "unique task -- a batch's images share one call. Kept as an explicit "
                         "flag so existing commands and scripts still work.")
    ap.add_argument("--no-full-meta", dest="full_meta", action="store_false",
                    help="skip the per-task metadata call: faster pull, but the catalog rows "
                         "it creates carry no prompt, seed or model until a later "
                         "--backfill-full-meta fills them in. On a first backup of a large "
                         "history this is the quicker route -- the pull's metadata fetch is "
                         "serial, while --backfill-full-meta --workers N is parallel.")
    ap.add_argument("--backfill-meta", action="store_true",
                    help="fill in missing url/width/height in catalog.db via resolve_media "
                         "for rows that lack them, then exit")
    ap.add_argument("--backfill-full-meta", action="store_true",
                    help="fill in prompt_full/seed/model/etc in catalog.db via getTaskById "
                         "for rows that lack them; also backfills url/width/height as a bonus, then exit")
    ap.add_argument("--with-loras", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "no LoRA data yet (populates the loras column for older images; long run)")
    ap.add_argument("--with-credit", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "no recorded credit cost yet (recovers the paid_credit column for older "
                         "generations from the task record; long run)")
    ap.add_argument("--export-csv", action="store_true",
                    help="export catalog.db to catalog.csv for interop/backup, then exit")
    ap.add_argument("--sync-artworks", action="store_true",
                    help="fetch your published-artwork metadata (title, NSFW flag, likes, "
                         "comments, aes score, tags) via listArtworks and merge it onto "
                         "matching catalog rows by media_id, then exit")
    ap.add_argument("--with-videos", action="store_true",
                    help="with --sync-artworks, also download animated-artwork video files "
                         "(videoMediaId) into a videos/ folder")
    ap.add_argument("--sync-videos", action="store_true",
                    help="back up your image-to-video generations: find i2v tasks, download "
                         "each mp4 into videos/, and catalog them (is_video), then exit")
    ap.add_argument("--faststart-videos", dest="faststart_videos", action="store_true",
                    help="losslessly move every video's moov atom to the front (ffmpeg "
                         "-c copy +faststart) so iOS/Safari can play them over HTTP, then exit")
    ap.add_argument("--account", action="store_true",
                    help="show a read-only account dashboard (credit balance, membership, "
                         "subscription) and exit. Never moves money")
    ap.add_argument("--cards", action="store_true",
                    help="show your free-generation cards (kaisuuken) + their ids, then exit. "
                         "Read-only; pass an id to a run with --kaisuuken-id")
    ap.add_argument("--contests", action="store_true",
                    help="list PixAI contests currently running (community + official), then "
                         "exit. Read-only. Add --all-contests to include ended ones")
    ap.add_argument("--all-contests", action="store_true",
                    help="with --contests, include ended contests too")
    ap.add_argument("--watch", action="store_true",
                    help="live-monitor your PixAI events over the push WebSocket (read-only; "
                         "gentler than polling). Prints task/notification events as they arrive")
    ap.add_argument("--watch-seconds", type=int, default=0, metavar="N",
                    help="with --watch, auto-stop after N seconds (default: run until Ctrl-C)")
    ap.add_argument("--watch-backup", action="store_true",
                    help="with --watch, mirror each generation into --out the instant it "
                         "reaches 'completed' (event-driven backup; no polling). Read-only")
    ap.add_argument("--claims", action="store_true",
                    help="list your claimable rewards (daily credits, agent stamina), then "
                         "exit. Read-only")
    ap.add_argument("--claim", default="", metavar="ID|all",
                    help="claim a ready reward by id (or 'all') -- requires --confirm. "
                         "Grants free credits/stamina to your own account")
    ap.add_argument("--reconcile-deleted", action="store_true",
                    help="flag catalog rows whose PixAI task is gone from your live feed "
                         "(deleted on the website) so the gallery can surface them for a "
                         "local prune, then exit")
    ap.add_argument("--import-local", nargs="?", const="", default=None, metavar="DIR",
                    help="catalog non-PixAI media (source='local') so it shows in the gallery. "
                         "No DIR = scan the backup folder for files you dropped in; a DIR "
                         "outside the backup is copied in. Then exit")
    # --- Generation (createGenerationTask) -------------------------------------
    gen = ap.add_argument_group("generation (--generate)")
    gen.add_argument("--generate", action="store_true",
                     help="create images via PixAI and catalog them (source='api'). "
                          "Preview-only unless --confirm (spends credits)")
    gen.add_argument("--prompt", default="", help="positive prompt for --generate")
    gen.add_argument("--negative", default="", help="negative prompt for --generate")
    gen.add_argument("--model", default="", help="modelId for --generate (default: Tsubaki.2)")
    gen.add_argument("--width", type=int, default=512)
    gen.add_argument("--height", type=int, default=512)
    gen.add_argument("--steps", type=int, default=25)
    gen.add_argument("--cfg", type=float, default=7.0)
    gen.add_argument("--batch-size", dest="count", type=int, default=1,
                     help="number of images per --generate run (batch size)")
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--priority", type=int, default=500,
                     help="generation priority: 500 = standard (default, cheaper), "
                          "1000 = high (faster, costs more credits)")
    gen.add_argument("--high-priority", dest="priority", action="store_const", const=1000,
                     help="shortcut for --priority 1000 (faster, more credits)")
    gen.add_argument("--mode", default="auto",
                     choices=["auto", "lite", "standard", "pro", "ultra"],
                     help="quality mode (inferenceProfile). auto (default) lets PixAI pick the "
                          "model's default -- always safe. lite/standard suit SD_V1 models; "
                          "pro/ultra are for newer model types (an unsupported mode is rejected)")
    gen.add_argument("--no-prompt-helper", dest="prompt_helper", action="store_false",
                     help="disable PixAI's prompt-helper (use your prompt more literally; "
                          "helps when auto-enhancement mangles a carefully-built prompt)")
    gen.set_defaults(prompt_helper=True)
    gen.add_argument("--lora", action="append", metavar="VERSIONID:WEIGHT",
                     help="add a LoRA by its version id and weight, e.g. "
                          "--lora 1686550608832816741:0.7 (repeatable). Find version ids "
                          "with --list-models")
    # Upscale + boosters. Flags are named after the PARAMETERS (what --dump-params shows),
    # with PixAI's own dialog label quoted in the help -- their two radio buttons read
    # "Upscale" (= the `enlarge` param) and "Hires" (= the `upscale` param), so naming the
    # flags after the labels instead would have made --upscale mean enlarge.
    gen.add_argument("--enlarge", type=float, default=None, metavar="RATIO",
                     help="enlarge the finished image with an upscaler network (PixAI's "
                          "'Upscale' method), in 0.1 steps from 1.1. Clamped to the largest "
                          "ratio the output-size ceiling allows for this --width/--height. "
                          "Mutually exclusive with --upscale")
    gen.add_argument("--enlarge-model", dest="enlarge_model", default="",
                     choices=list(ENLARGE_MODELS),
                     help="which upscaler network --enlarge runs (default: {})".format(
                         DEFAULT_ENLARGE_MODEL))
    gen.add_argument("--upscale", type=float, default=None, metavar="RATIO",
                     help="re-diffuse the image at a larger size (PixAI's 'Hires' method), "
                          "in 0.1 steps from 1.1. Sharper than --enlarge and roughly 3x the "
                          "credits; allows a smaller maximum ratio. Mutually exclusive with "
                          "--enlarge")
    gen.add_argument("--upscale-denoise", dest="upscale_denoising_strength", type=float,
                     default=None, metavar="STRENGTH",
                     help="--upscale denoising strength, 0.01-0.99 (default {}; PixAI's own "
                          "hint is 0.4-0.6 -- higher redraws more)".format(
                              DEFAULT_UPSCALE_DENOISING_STRENGTH))
    gen.add_argument("--upscale-denoise-steps", dest="upscale_denoising_steps", type=int,
                     default=None, metavar="N",
                     help="--upscale denoising steps, 1-50 (default {})".format(
                         DEFAULT_UPSCALE_DENOISING_STEPS))
    gen.add_argument("--face-fix", dest="face_fix", action="store_true",
                     help="run PixAI's face restorer over the result (enableADetailer -- "
                          "the generator's 'Face Fix' booster)")
    gen.add_argument("--quality-tag", dest="quality_tag", nargs="?",
                     const=DEFAULT_QUALITY_TAG, default="", metavar="PREFIX",
                     help="prepend a quality booster to the prompt (the generator's "
                          "'Quality Tag'). Bare flag uses '{}'".format(DEFAULT_QUALITY_TAG))
    gen.add_argument("--task-id", default="",
                     help="with --generate, fetch + catalog an ALREADY-created task by id "
                          "(no new credits). Recovers a stranded generation that --update "
                          "can't see, since generated tasks don't enter the listing feed")
    gen.add_argument("--params-json", default="", help="raw parameters object (overrides the above)")
    gen.add_argument("--poll-timeout", type=int, default=300,
                     help="seconds to wait for a submitted task to finish before giving up (default 300)")
    gen.add_argument("--confirm", action="store_true",
                     help="REQUIRED for --generate/--generate-video to actually submit (spends credits)")
    # --- image-to-video generation (shares --prompt/--negative/--model/--confirm/--task-id) ---
    gen.add_argument("--generate-video", dest="generate_video", action="store_true",
                     help="create an image-to-video clip via PixAI from a source image "
                          "(--image). Preview-only unless --confirm. Video is EXPENSIVE "
                          "(~27,500 credits for a 5s V4.0 clip)")
    gen.add_argument("--image", default="", help="source image media_id to animate (first frame)")
    gen.add_argument("--tail", default="", help="optional last-frame image media_id "
                     "(first/last-frame interpolation)")
    gen.add_argument("--duration", type=int, default=5, help="video length in seconds (e.g. 5/10/15)")
    gen.add_argument("--video-model", dest="video_model", default="",
                     help="video model (default v4.0.1); overrides --model for --generate-video")
    gen.add_argument("--video-mode", dest="vmode", default="professional",
                     choices=["basic", "professional"], help="video quality tier")
    gen.add_argument("--audio", action="store_true", help="generate audio with the video")
    gen.add_argument("--audio-language", dest="audio_language", default="english",
                     help="spoken language for --audio video sound (default english; no effect without --audio)")
    gen.add_argument("--video-prompt-helper", dest="video_prompt_helper", action="store_true",
                     help="enable PixAI's prompt-helper for video (off by default)")
    gen.add_argument("--camera-movement", dest="camera_movement", default="",
                     choices=list(VIDEO_CAMERA_MOVES),
                     help="camera move (v2.7-style): horizontal/pan/roll/tilt/vertical-pan/zoom "
                          "(default unset = omit; camera direction can also go in the prompt)")
    gen.add_argument("--video-channel", dest="vchannel", default="private",
                     choices=list(VIDEO_CHANNELS),
                     help="video channel: private = 'Enhanced' (Plus/Premium) | normal")
    gen.add_argument("--dump-params", action="store_true",
                     help="with --generate/--generate-video/--edit-image (esp. --task-id "
                          "recovery), print the task's full submit parameters -- bank any "
                          "param shape (multiRef, referenceVideo, ...) with no browser capture")
    # --- reference video (multi-image/video/audio reference) ---
    gen.add_argument("--reference-video", dest="reference_video", action="store_true",
                     help="create a multi-reference video (referenceVideo): pass refs with "
                          "--ref-image/--ref-video/--ref-audio and cite them in --prompt as "
                          "@image1/@video1/@audio1. Preview-only unless --confirm")
    gen.add_argument("--ref-image", dest="ref_image", action="append", metavar="MEDIA_ID|FILE",
                     help="reference image (media_id or local file, auto-uploaded). Repeatable: "
                          "@image1=first, @image2=second, ...")
    gen.add_argument("--ref-video", dest="ref_video", action="append", metavar="MEDIA_ID|FILE",
                     help="reference video (repeatable; cite as @video1, @video2, ...)")
    gen.add_argument("--ref-audio", dest="ref_audio", action="append", metavar="MEDIA_ID|FILE",
                     help="reference audio (repeatable; cite as @audio1, ...)")
    # --enhance / --src / --filter-id / --strength are gone -- see build_filter_parameters'
    # former neighbourhood above for both measurements. Art filters run in the browser now
    # (static/mg-art-filters.js, the gallery's Edit > Enhance tab): free, offline, no submit.
    # --- instruct editing + media upload (the "Edit this image" surface) ---
    gen.add_argument("--edit-image", dest="edit_image", action="store_true",
                     help="instruct-edit an image via PixAI: describe the change in --prompt "
                          "and pass source(s) with --edit-src (a catalog media_id OR a local "
                          "file, uploaded automatically). Preview-only unless --confirm")
    gen.add_argument("--edit-src", dest="edit_src", action="append", metavar="MEDIA_ID|FILE",
                     help="source image for --edit-image: a media_id or a local image file "
                          "(local files upload automatically). Repeatable for multi-image reference")
    gen.add_argument("--edit-model", dest="edit_model", default="",
                     help="edit model id (default PixAI Edit Pro {})".format(EDIT_PRO_MODEL_ID))
    gen.add_argument("--edit-resolution", dest="edit_resolution", default="1K",
                     help="edit output resolution (default 1K; e.g. 1K/2K)")
    gen.add_argument("--edit-aspect", dest="edit_aspect", default="3:4",
                     help="edit output aspect ratio (default 3:4)")
    gen.add_argument("--edit-quality", dest="edit_quality", default="medium",
                     help="edit quality tier (default medium)")
    gen.add_argument("--upload", dest="upload_file", default="", metavar="FILE",
                     help="upload a local image to PixAI, print its media_id, then exit "
                          "(the reusable primitive behind --edit-src file support). Free")
    gen.add_argument("--suggest-prompt", dest="suggest_prompt", default="", metavar="MEDIA|FILE",
                     help="reverse a prompt out of an image ('Image to prompt'): print PixAI's "
                          "suggested tags + description for a catalog media_id or local file. Free")
    gen.add_argument("--kaisuuken-id", dest="kaisuuken_id", default="", metavar="ID",
                     help="force a specific free card (kaisuuken) id on this generate/edit/"
                          "video run. Normally not needed -- a matching card is auto-applied "
                          "on --confirm (like the website)")
    gen.add_argument("--no-card", dest="no_card", action="store_true",
                     help="do NOT auto-apply a free card; pay credits even if a card matches")
    gen.add_argument("--list-models", nargs="?", const="", default=None, metavar="KEYWORD",
                     help="search PixAI generation models by keyword and print their "
                          "generatable version ids (use as --model), then exit")
    ap.add_argument("--fix-model-names", action="store_true",
                    help="re-resolve readable model names for catalog rows whose model_name "
                         "is blank or a raw numeric id (one API call per distinct model), then exit")
    ap.add_argument("--relabel-removed", action="store_true",
                    help="with --fix-model-names, relabel ids that no longer resolve (deleted "
                         "models) to 'Unknown or removed model' instead of leaving the raw number")
    ap.add_argument("--audit", action="store_true",
                    help="read-only duplicate audit of the whole backup folder; writes "
                         "audit_report.csv and prints a summary, then exit. Independent of catalog.db.")
    ap.add_argument("--dedup", action="store_true",
                    help="act on the audit: move redundant copies to _duplicates/ (keeping the "
                         "most-organized copy), then reconcile catalog.db. Dry-run unless --apply.")
    ap.add_argument("--apply", action="store_true",
                    help="with --dedup, actually perform the moves/deletes (default is dry-run)")
    ap.add_argument("--dedup-delete", action="store_true",
                    help="with --dedup --apply, delete redundant copies instead of quarantining them")
    ap.add_argument("--no-content", action="store_true",
                    help="with --audit/--dedup, skip content hashing (Class B); only do the fast "
                         "same-media_id location dedup (Class A)")
    ap.add_argument("--verify-dupes", action="store_true",
                    help="final-pass safety check on _duplicates/: confirm every quarantined file "
                         "is byte-identical to a surviving keeper before you delete. Flags orphans "
                         "and same-id-different-bytes mismatches. Read-only unless --restore-orphans.")
    ap.add_argument("--restore-orphans", action="store_true",
                    help="with --verify-dupes, move any orphaned quarantined files (no surviving "
                         "keeper) back to images/")
    ap.add_argument("--rebuild-similar", action="store_true",
                    help="drop + re-embed the visual-similarity ('Similar') index from scratch off "
                         "the on-disk backup. Cures a corrupted/duplicate index; builds ONE clean "
                         "named index. ~decode-bound, no network. Needs torch/pixeltable.")
    ap.add_argument("--sync-similar", action="store_true",
                    help="TOP UP the 'Similar' index: embed only images it doesn't already have. "
                         "The incremental counterpart to --rebuild-similar and the one you "
                         "normally want -- it cannot lose existing rows, and after an interrupted "
                         "build it resumes instead of starting over. Needs torch/pixeltable.")
    webauth = ap.add_argument_group("web gallery login accounts (session-based auth)")
    webauth.add_argument("--add-web-user", action="store_true",
                    help="add or update a gallery web-login account: interactively prompts "
                         "for a username and password (getpass -- never echoed/printed), "
                         "hashes the password, and saves it to config.json's AUTH_USERS. "
                         "Deliberately CLI-only -- no account-creation form is ever reachable "
                         "over the network")
    webauth.add_argument("--remove-web-user", default="", metavar="USERNAME",
                    help="remove a gallery web-login account by username")
    webauth.add_argument("--list-web-users", action="store_true",
                    help="list gallery web-login usernames (never password hashes), then exit")
    args = ap.parse_args()
    set_verbose(getattr(args, "verbose", False))
    import moonglade_logging
    moonglade_logging.setup_logging(args.out, verbose=getattr(args, "verbose", False))
    # Give every command a progress callback (terminal bar, or Control Panel markers under
    # MOONGLADE_PROGRESS=1). Commands that report progress (audit/dedup/sync/...) pick it up;
    # the rest ignore it.
    args.progress = _make_progress()

    if args.probe and args.count:
        print("Note: --probe exits before --count runs. Run them separately:\n"
              "  python moonglade_backup.py --count\n"
              "Continuing with --probe only.\n")

    # Web-login account management: no PixAI token/network/out-dir needed at all,
    # so these run before anything else touches --out.
    if getattr(args, "list_web_users", False):
        run_list_web_users(args)
        return
    if getattr(args, "remove_web_user", ""):
        run_remove_web_user(args)
        return
    if getattr(args, "add_web_user", False):
        run_add_web_user(args)
        return

    out = Path(args.out)
    img_dir = out / "images"
    db_path  = out / "catalog.db"
    csv_path = out / "catalog.csv"
    try:      # achievement telemetry: bare telem_* bumps land in this install's ledger
        from moonglade_gallery import set_telemetry_out
        set_telemetry_out(out)
    except Exception:
        pass

    try:
        if getattr(args, "delete_task", None):
            run_delete_tasks(args)
            return
        if args.catalog_stats:
            run_catalog_stats(args)
            return
        if getattr(args, "rebuild_similar", False):
            run_rebuild_similar(args)
            return
        if getattr(args, "sync_similar", False):
            run_sync_similar(args)
            return
        if args.export_csv:
            if not db_path.exists():
                sys.exit("No catalog.db found at {}.".format(db_path))
            export_csv(db_path, csv_path)
            print("Exported {:,} rows to {}.".format(
                len(load_catalog(db_path)), csv_path))
            return
        if args.sync_artworks:
            # B15: same job-tracking + done_with_errors wiring --sync already has (see
            # above) -- previously this call had NO job logging at all, so a partial
            # failure (mid-pagination break, a failed video download) was invisible
            # everywhere: no Jobs-tray entry, no done_with_errors, nothing.
            _job = _cli_job_start(out, "Artwork sync")
            try:
                res = run_sync_artworks(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _cli_job_finish(out, _job, error=e)
                raise
            _cli_job_finish(out, _job, warn=(res or {}).get("fail", 0),
                            warn_detail="issue(s) during artwork sync")
            return
        if args.sync_videos:
            run_sync_videos(args)
            return
        if getattr(args, "faststart_videos", False):
            run_faststart_videos(args)
            return
        if args.account:
            run_account_info(args)
            return
        if getattr(args, "cards", False):
            run_cards(args)
            return
        if getattr(args, "contests", False):
            run_contests(args)
            return
        if getattr(args, "watch", False):
            run_watch(args)
            return
        if getattr(args, "claims", False) or getattr(args, "claim", ""):
            run_claims(args)
            return
        if args.reconcile_deleted:
            run_reconcile_deleted(args)
            return
        if args.import_local is not None:
            run_import_local(args)
            return
        if args.list_models is not None:
            run_list_models(args)
            return
        if args.generate:
            _job = _cli_job_start(out, "Image generation")
            try:
                run_generate(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _cli_job_finish(out, _job, error=e)
                raise
            _cli_job_finish(out, _job)
            return
        if getattr(args, "generate_video", False):
            _job = _cli_job_start(out, "Video render")
            try:
                run_generate_video(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _cli_job_finish(out, _job, error=e)
                raise
            _cli_job_finish(out, _job)
            return
        if getattr(args, "reference_video", False):
            run_reference_video(args)
            return
        if getattr(args, "upload_file", ""):
            run_upload(args)
            return
        if getattr(args, "suggest_prompt", ""):
            run_suggest_prompt(args)
            return
        if getattr(args, "edit_image", False):
            run_edit_image(args)
            return
        if args.fix_model_names:
            run_fix_models(args)
            return
        if args.audit:
            cmd_audit(args, out)
            return
        if args.dedup:
            cmd_dedup(args, out, db_path)
            return
        if args.verify_dupes:
            cmd_verify_dupes(args, out)
            return
        if getattr(args, "rebuild_thumbs", False):
            run_rebuild_thumbs(args)
            return
        if getattr(args, "sync", False):
            # Sync = the "it should just happen" pipeline: incremental pull that
            # arrives WITH metadata, re-resolve any model ids that came back
            # blank/numeric, fill anything still blank, rebuild any missing preview
            # thumbnails, then reconcile rows deleted on the website. Every step is
            # idempotent/self-limiting (backfill skips rows that already have
            # prompt_full; build_thumbnails skips thumbs already on disk), so
            # re-running --sync on a clean catalog costs almost nothing extra.
            args.update = True
            args.full_meta = True
            # cli-<uuid> job: parity with the Control Panel's own panel-<uuid> logging for
            # a --sync run spawned as a subprocess. Also re-point args.progress at a
            # job-aware callback so the download/thumbnail progress ticks below feed
            # throttled heartbeats into the same job (purely additive -- see _make_progress).
            _job = _cli_job_start(out, "Library sync")
            if _job:
                args.progress = _make_progress(out, _job)
            try:
                # run_download uses its `progress` PARAM (not args.progress), so hand it over
                # explicitly -- otherwise the panel's progress bar is blank during the
                # download step (fix_models/backfill already read args.progress themselves).
                dl = run_download(args, progress=getattr(args, "progress", None))
                print("\nSync: resolving any unlabeled model names...")
                run_fix_models(args)
                print("Sync: filling any rows still missing metadata...")
                run_backfill_full_meta(args)
                print("Sync: building any missing preview thumbnails...")
                thumb_dir = out / "gallery" / "thumbs"
                thumb_dir.mkdir(parents=True, exist_ok=True)
                # build_thumbnails reports progress_cb(done, total, pct); our shared progress
                # callback expects (done, total, new-count), so adapt -- forward only done/total
                # (new defaults to 0) rather than mislabel the percentage as a "new items" count.
                _prog = getattr(args, "progress", None)
                build_thumbnails(load_catalog(db_path), out, thumb_dir,
                                 progress_cb=((lambda d, t, _pct: _prog(d, t)) if _prog else None))
                # Reconcile is advisory (it only FLAGS cloud-deleted rows) and runs its own live
                # feed scan, so a failure here must NOT discard the successful backup above. Catch
                # BROADLY on purpose: that scan goes through gql(), which re-raises bare requests
                # network/HTTP errors that are NOT PixAIError -- a narrow catch would let a
                # transient blip crash the whole sync after everything else already succeeded.
                print("Sync: reconciling rows deleted on PixAI...")
                try:
                    run_reconcile_deleted(args)
                except Exception as e:                   # noqa: BLE001 -- advisory step, never fatal
                    print("  reconcile skipped: {}".format(e))
                print("Sync complete.")
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _cli_job_finish(out, _job, error=e)
                raise
            _cli_job_finish(out, _job, warn=(dl or {}).get("fail", 0))
            return
        if args.backfill_meta:
            run_backfill_meta(args)
            return
        if args.backfill_full_meta:
            run_backfill_full_meta(args)
            return
        if args.convert_existing:
            cmd_convert_existing(args, out)
            return
        if args.undo_organize:
            cmd_undo_organize(args, out)
            return
        if args.organize or args.organize_adv:   # --organize-adv: back-compat alias
            cmd_organize(args, out, img_dir, db_path)
            return
        if args.probe:
            run_probe(args)
            return
        if args.count:
            run_count(args)
            return
        # Plain full download, or --update (an incremental run of the same code path) --
        # cli-<uuid> job, same parity rationale as --sync above. Deliberately does NOT
        # thread a job-aware progress callback through run_download here: that call
        # passes no `progress` kwarg today, so run_download's own `sys.stdout.isatty()`
        # fallback draws the \r bar directly -- wiring progress in would change that
        # existing terminal-output behavior (it would print unconditionally, tty or not).
        _job = _cli_job_start(out, "Incremental update" if getattr(args, "update", False) else "Full backup")
        try:
            dl = run_download(args)
        except Exception as e:                           # noqa: BLE001 -- re-raised below unchanged
            _cli_job_finish(out, _job, error=e)
            raise
        _cli_job_finish(out, _job, warn=(dl or {}).get("fail", 0))
    except PixAIError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

# ===========================================================================
# RECAPTURE (only if the site changes): re-grab the persisted sha256Hash, U3T,
# and USER_ID from Network tab -> graphql row -> Payload, and update config.json.
# Keep your token private.
# ===========================================================================

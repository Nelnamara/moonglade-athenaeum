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

__version__ = "3.7.0"

import argparse
import base64
import csv
import datetime
import getpass
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from pathlib import Path

from moonglade_gallery import (CATALOG_FIELDS, _IMAGE_EXTS, init_db, migrate, load_catalog,
                            save_catalog, _db_is_empty, rows_for_media_ids,
                            media_id_of, find_files_for_media_id, build_thumbnails,
                            _NO_WINDOW, DELETED_DIRNAME, _redact_host_paths_cli,
                            # The one library scan (see moonglade_gallery.py's
                            # "LIBRARY SCAN" section) -- imported the same way the
                            # SQLite catalog helpers above are, because the gallery
                            # is the shared base module and this file imports it.
                            scan_library, bucket_of, _VIDEO_EXTS,
                            GALLERY_DIRNAME, DUPLICATES_DIRNAME,
                            QUARANTINE_EXCLUDE, QUARANTINE_EXCLUDE_ANYWHERE,
                            IMPORT_EXCLUDE)


def _ensure_db(out):
    """Return db_path, schema-migrated. Raises PixAIError if no catalog db exists.

    The legacy catalog.csv auto-seed was retired 2026-08-24 (#19): a stale export
    silently reseeding the catalog was a footgun, and catalog.db is the source of truth.
    """
    out = Path(out)
    db_path = out / "catalog.db"
    if _db_is_empty(db_path):
        raise PixAIError(
            "No catalog found in {}. Run a download (or --collect-only) first.".format(out))
    migrate(db_path)      # the CLI's entry point says the schema upgrade out loud; the
                          # catalog road's per-process memo makes it free from here on
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

# Cached view of what config.json says RIGHT NOW, refreshed only when the file's
# (mtime, size) stamp changes -- see _read_only_now().
_read_only_state = {"stamp": None, "value": None}


def _read_only_now():
    """READ_ONLY as config.json holds it at THIS moment, not as it was at import.

    The module-level READ_ONLY above is an import-time snapshot, and the gallery
    server is a process that stays up for days: flipping the switch on in
    config.json did nothing to a running server, which kept spending credits and
    deleting for its whole lifetime. The Trust & Safety wiki page presents this
    flag as the thing standing between the tool and the account, so a snapshot
    that can't be turned on is a safety promise the code doesn't keep.

    Re-reading is gated on the file's stat stamp because _check_read_only() sits
    on every credit-spending path: an unchanged config costs one stat(), not a
    JSON parse. If the file can't be stat'd (no config.json at all -- --help and
    the offline modes run without one) the import-time snapshot stands."""
    try:
        st = os.stat(_config_path())
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return READ_ONLY
    if _read_only_state["stamp"] != stamp:
        _read_only_state["value"] = bool(_load_config().get("READ_ONLY", False))
        _read_only_state["stamp"] = stamp
    return _read_only_state["value"]


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
    is an open question, tracked in the 2026-07-21 audit, not resolved by this
    docstring.

    Both the import-time snapshot AND the live file are consulted, and EITHER one
    being set refuses the call. Turning the switch ON therefore takes effect on a
    server that is already running; turning it OFF still needs a restart, which is
    the direction it is safe to be slow in."""
    if READ_ONLY or _read_only_now():
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
# Website-mirror JWT (the Control Panel "Mirror to PixAI" toggle). refreshToken is a
# no-arg persisted mutation; the fresh JWT comes back in the `token` RESPONSE header
# (server sends access-control-expose-headers: token,...). Confirmed from a live
# getMyInfo capture 2026-08-14. The mirror helpers live just after _make_session below.
# Public hash; override in config.json if it rotates.
REFRESH_TOKEN_HASH = _cfg.get("REFRESH_TOKEN_HASH", "") or \
    "ad4ac2d62cbc5ab168a212594fb515c58cca1a101c60233a214fd7e037157546"
PIXAI_COOKIE_DOMAIN = "pixai.art"
# Short session cookies the server rolls forward via Set-Cookie on every response
# (_udt IS the u3t value; ~60m / ~30m lifetimes). Read the whole jar so refreshToken
# sees the same cookies the browser sends.
SESSION_COOKIE_NAMES = ("_bsid", "_bsid.sig", "_udt", "_udt.sig")
# Roll the ~27-day JWT once it drops under this many days left (a box that runs even
# weekly never lapses).
MIRROR_REFRESH_WHEN_DAYS_LEFT = 5
# The localStorage key the pixai.art frontend keeps the live JWT under (confirmed on a
# logged-in tab 2026-08-15). localStorage is NOT app-bound(v20)-encrypted the way modern
# Chrome cookies are, so reading THIS is how the mirror bootstraps on a current Chrome
# where the cookie store can't be decrypted. Note the trailing ":token" is exact -- the
# sibling ":intercom-user-jwt" key must never be mistaken for it.
LOCALSTORAGE_JWT_KEY = b"https://api.pixai.art:token"
# The mirror must file generations as the WEB client so PixAI applies the website's content
# policy, not the stricter mobile-app (Apple-compliance) one. Confirmed 2026-08-15: the same
# account + prompt succeeds on pixai.art (task 2045416767743558052) but 403s "against PixAI's
# policy" through the mirror. clientLibrary already matches the web app (@apollo/client); the
# remaining tell is the HTTP identity -- our non-browser User-Agent and missing Origin/Referer.
# So the mirror session presents a desktop-browser identity. A stable modern Chrome UA is
# enough: PixAI classifies the client FAMILY (browser vs app), not the version.
MIRROR_WEB_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
MIRROR_WEB_ORIGIN = "https://pixai.art"
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
        # Under _CONSOLE_LOCK so a bar frame cannot be drawn INSIDE a multi-line message a
        # worker thread is emitting (see _console_block). Uncontended in the normal case --
        # the bar is drawn from the main thread and the blocks are rare.
        with _CONSOLE_LOCK:
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

# Serializes the ONE non-append writer of jobs.jsonl (maybe_compact_jobs' whole-file
# rewrite) against every other thread in this process, exactly like _accounts_lock does
# for AUTH_USERS and for the same reproduced reason: moonglade_gallery.py runs
# threaded=True, so two /api/jobs polls (two tabs, or the gallery plus the Loom) can both
# see the log cross _JOBS_COMPACT_AT and start rewriting it at the same moment. Appends
# don't need this -- they're one "a"-mode line and safe across processes by design.
_jobs_compact_lock = threading.Lock()


def _jobs_path(out_dir):
    return Path(out_dir) / JOBS_LOG_NAME


def append_job_event(out_dir, job_id, status=None, **fields):
    """Append ONE job event to jobs.jsonl (append-only; safe from many processes).
    Each call records a job's CURRENT state; readers collapse by job_id. Known
    fields: type, label, done, total, media_ids, error, source, dismissed, count
    (requested image count, image-gen registrations only). `ts` is stamped here.
    Fails soft -- logging a job must never break the job.

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
    the 2026-07-21 audit, S3) -- a first attempt at that used a regex that
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
            append_job_event(out_dir, job_id, status="failed",
                             error=_redact_host_paths_cli(out_dir, str(error))[:200])
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
    # Whole thing under _jobs_compact_lock: the count check and the rewrite have to be one
    # step, or two concurrent pollers both pass the threshold test and rewrite together. The
    # scratch file is pid-stamped like _save_config's for the cross-PROCESS half of the same
    # race -- a panel subprocess compacting at the same instant would otherwise be writing
    # into the very file this one is about to rename, truncating the log to a hybrid.
    with _jobs_compact_lock:
        jobs, order, n = _reconstruct_jobs(out_dir)
        if n <= _JOBS_COMPACT_AT:
            return
        kept = _select_jobs(jobs, order, time.time(), keep, max_age)
        kept.reverse()                      # write oldest-first so append order stays chronological
        path = _jobs_path(out_dir)
        tmp = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                for j in kept:
                    fh.write(json.dumps(j, separators=(",", ":")) + "\n")
            _atomic_replace(tmp, path)      # transient Windows sharing violation != lost compaction
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
            conn = find_connection(gql(session, page_variables(
                page_size, _client_of(session).user_id, before)))
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


# ===========================================================================
# pixai_client -- the ONE PixAI transport seam
# ===========================================================================
# Every byte this app exchanges with PixAI leaves through a PixAIClient. Before
# this section existed there was no transport MODULE at all: a bare
# requests.Session was threaded through seventy-odd functions as a positional
# argument, and the five primitives that actually spoke to PixAI --
# gql/gql_adhoc/gql_mutate/_rest_get/_rest_post -- were module functions that
# each re-derived the rules from that Session. The rules that matter are not
# stylistic:
#
#   * the retry policy, and the ONE place the spend rule lives. `mutate()` has
#     no `retries` parameter -- not defaulted to 0, ABSENT -- so a spending call
#     site cannot ask for the unsafe value. `query()`'s `retries=None` is
#     document-aware (3 for a query, 0 for a mutation) as the backstop for a
#     call site that reaches past `mutate()`. A lost RESPONSE is
#     indistinguishable from a lost REQUEST, and re-POSTing createGenerationTask
#     after PixAI already created and CHARGED for the task pays twice.
#   * the two roads to PixAI -- the persisted-hash GET (`persisted()`), which is
#     how the personal-history operations are reached, and the ad-hoc POST
#     (`query()`/`mutate()`), which is everything the API key can ask for
#     directly -- plus the oRPC `/v2` REST road (`rest_get()`/`rest_post()`).
#   * WHICH credential a create rides (`for_create()`): the browser-JWT mirror
#     session when the Mirror toggle is on, the API key otherwise, and a refusal
#     rather than a silent fall-back to the key when the mirror is unavailable.
#
# There is a second adapter: `tests/fake_pixai.py`'s FakePixAI answers the same
# interface from registered responses and refuses any operation nobody
# registered, so "the suite never touches the network" is structural instead of
# a habit maintained by 300-odd private monkeypatches.
#
# TRANSITION SURFACE. `get`/`post`/`headers`/`cookies` on the client delegate
# straight to the inner requests.Session, because a handful of call sites still
# reach for the Session themselves rather than through a verb: the persisted
# GETs that have not moved onto `persisted()` (task_detail_gql,
# _bookmarks_persisted, model_name_gql, resolve_model_base_id,
# _resolve_model_preset, artwork_list_gql), delete_task_gql's lone hand-rolled
# POST, refresh_jwt's mirror POST, resolve_media and download (which are not
# GraphQL at all -- a media object and a file body), and run_watch reading the
# Authorization header off to hand to the WebSocket. `.session` is the escape
# hatch those will eventually stop needing; it exists for the transition, not
# forever.
#
# NOT everything gets a client. A pasted API key is validated by hand-building a
# Session with that key as the sole credential (moonglade_gallery's
# /api/setup/save-key) precisely BECAUSE the normal path prefers the cached
# config -- a garbage key once verified because the real cached key answered.
# `_client_of()` therefore wraps whatever Session it is handed without reading
# config, resolving a user id, or touching a credential, so that route keeps its
# guarantee while still reaching account_info through the same verb.
# ===========================================================================


def _is_mutation_document(query):
    """True when `query` is a GraphQL MUTATION document rather than a query.

    Deliberately a dumb leading-keyword check: every document in this module is a plain
    string literal that starts with its operation type. Anything it cannot classify falls
    back to False (treated as a query), which is the behaviour that existed before it."""
    return str(query or "").lstrip().lower().startswith("mutation")


class PixAIClient:
    """The transport seam: everything this app asks PixAI, asked here.

    Five verbs (`query`, `mutate`, `persisted`, `rest_get`, `rest_post`), one credential
    choice (`for_create`), and the underlying requests.Session on `.session` for the call
    sites still mid-transition. `auth_kind` is `"api-key"` or `"web-jwt"`; `user_id` is the
    resolved account id.

    The class holds no PixAI knowledge that the module does not already own -- endpoints,
    hashes and the Apollo headers stay module-level -- so a client can be built around ANY
    session (a hand-built one, a test double) without that session inheriting the config
    cache."""

    #: Marks an object as a PixAI transport adapter, so `_client_of` hands it straight
    #: back instead of wrapping it. Checked with `is True` on purpose: a MagicMock answers
    #: every attribute with a truthy mock, and a mock standing in for a *Session* must
    #: still be wrapped or its `.post` would never be reached. This is what lets
    #: tests/fake_pixai.py's FakePixAI be a real second adapter rather than a subclass --
    #: it satisfies the interface, it does not inherit the implementation.
    _is_pixai_client = True

    def __init__(self, session, auth_kind="api-key", user_id=None):
        self._session = session
        self._auth_kind = auth_kind
        self._user_id = user_id

    # -- identity ----------------------------------------------------------
    @property
    def session(self):
        """The underlying requests.Session. For the transition only -- prefer a verb."""
        return self._session

    @property
    def auth_kind(self):
        """`"api-key"` (the official credential) or `"web-jwt"` (the website mirror)."""
        return self._auth_kind

    @property
    def user_id(self):
        """The authenticated account's PixAI id."""
        return self._user_id or USER_ID

    def __repr__(self):
        return "<PixAIClient {} user={}>".format(self._auth_kind, self.user_id or "?")

    # -- the transition surface: the raw Session, delegated ------------------
    def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._session.post(*args, **kwargs)

    @property
    def headers(self):
        return self._session.headers

    @property
    def cookies(self):
        return self._session.cookies

    # -- ad-hoc GraphQL POST -------------------------------------------------
    def query(self, document, variables=None, retries=None):
        """Run an ad-hoc (non-persisted) GraphQL operation by POSTing the full document.

        `retries=None` (the default) means "the safe default for THIS document": **3 for a
        query, 0 for a mutation**. A retry re-POSTs on a RequestException or a 429/5xx, and
        that is only free when the operation is idempotent. An explicit integer wins, so a
        caller can still ask for anything on purpose. Returns the `data` dict; raises
        PixAIError on GraphQL/HTTP error."""
        if retries is None:
            retries = 0 if _is_mutation_document(document) else 3
        return self._graphql_post(document, variables, retries)

    def mutate(self, document, variables=None):
        """`query()` for a mutation that MUST NOT fire twice: SINGLE ATTEMPT, always.

        It takes **no `retries` argument on purpose** -- there is no correct value above 0
        for a spending path, so the knob is not offered rather than offered with a safe
        default a call site can override by accident. Pinned by
        tests/test_pixai_client.py and tests/test_spend_no_retry.py."""
        return self._graphql_post(document, variables, 0)

    def _graphql_post(self, document, variables, retries):
        """The one ad-hoc POST loop. `retries` is already resolved to an integer by the
        verb that called in -- this function never chooses it, which is what keeps the
        spend rule readable in exactly two places above."""
        body = {"query": document, "variables": variables or {}}
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                r = self._session.post(API_URL, json=body, timeout=120)
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
                raise PixAIError("HTTP {} non-JSON response:\n{}".format(
                    r.status_code, r.text[:400]))
            if data.get("errors"):
                raise PixAIError("GraphQL error: " + json.dumps(data["errors"])[:500])
            return data.get("data") or {}
        raise RuntimeError("unreachable")

    # -- persisted-hash GET --------------------------------------------------
    def persisted(self, op_name, variables=None, sha256=None, retries=4,
                  client_library=None, headers=None):
        """Replay one of PixAI's own persisted operations as a GET, with the Apollo CSRF
        params their frontend sends. `sha256=None` resolves the captured hash for
        `op_name` (the history feed is the operation that rides this road out of the box);
        every other captured op rides here by passing its OWN `sha256=`. `client_library`
        overrides the Apollo `clientLibrary` block for the one op that sends its own
        (`listArtworks`), and `headers` adds request headers for this single call
        (`listArtworks`' `x-apollo-operation-name`). Returns the `data` dict; raises
        PixAIError with a recapture hint if the hash went stale, and PixAIError -- never a
        bare KeyError -- if the reply is a non-GraphQL body carrying no `data` key (a stale
        credential or an edge refusal answered in its own JSON)."""
        sha = sha256 or (PERSISTED_QUERY_HASH if op_name == OPERATION_NAME else "")
        if not sha:
            raise PixAIError(
                "no persisted hash is known for operation {!r} -- pass sha256=... or add "
                "it to config.json (see RECAPTURE at the bottom of moonglade_backup.py)."
                .format(op_name))
        params = {
            "operation": op_name,
            "u3t": U3T,
            "operationName": op_name,
            "variables": json.dumps(variables or {}, separators=(",", ":")),
            "extensions": json.dumps(
                {"clientLibrary": client_library or CLIENT_LIBRARY,
                 "persistedQuery": {"version": 1, "sha256Hash": sha}},
                separators=(",", ":")),
        }
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                _t = time.monotonic()
                r = self._session.get(API_URL, params=params, timeout=60, headers=headers)
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
            if not isinstance(data, dict) or "data" not in data:
                raise PixAIError(
                    "HTTP {} returned a non-GraphQL body (no 'data' key), so the request "
                    "failed rather than answering -- a stale/absent credential or an edge "
                    "refusal is the usual cause:\n{}".format(
                        r.status_code, (r.text or "")[:300]))
            vlog("{} page -> HTTP {} ({:,} bytes) in {:.2f}s".format(
                op_name, r.status_code, len(r.content), time.monotonic() - _t))
            return data["data"]
        raise RuntimeError("unreachable")

    # -- the oRPC /v2 REST road ----------------------------------------------
    def rest_get(self, path, params=None, timeout=30):
        """GET a /v2 oRPC REST route. Returns parsed JSON. Raises PixAIError on non-2xx.

        Single-attempt by construction, like `rest_post` -- see its note."""
        r = self._session.get(REST_API_BASE + path, params=params, timeout=timeout)
        if not r.ok:
            raise PixAIError("REST GET {} -> {}: {}".format(path, r.status_code, r.text[:300]))
        return r.json()

    def rest_post(self, path, body=None, timeout=60):
        """POST JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx.

        NO retry loop, deliberately: `submit_fixer` and `claim_reward` ride this, and the
        session mounts no urllib3 Retry adapter (requests' default HTTPAdapter is
        max_retries=0), so both are single-attempt. Pinned by
        tests/test_spend_no_retry.py::test_rest_post_has_no_retry_loop."""
        r = self._session.post(REST_API_BASE + path, json=body, timeout=timeout)
        if not r.ok:
            raise PixAIError("REST POST {} -> {}: {}".format(path, r.status_code, r.text[:300]))
        return r.json()

    # -- which credential a create rides -------------------------------------
    def for_create(self):
        """The client a CREATE must POST through: the browser-JWT mirror when the 'Mirror
        to PixAI' toggle is on (so the generation lands in the pixai.art web library),
        this same client otherwise. Refuses (raises) rather than falling back to the API
        key when the mirror is armed but unavailable. Callers must have already passed
        `_check_read_only` -- building the mirror session may make a refreshToken call."""
        chosen = _session_for_create(self)
        if chosen is self:
            return self
        return PixAIClient(chosen, auth_kind="web-jwt")


def _client_of(session):
    """The transport adapter for `session`: itself when it already is one, a thin
    PixAIClient wrapper around it otherwise.

    "Already is one" is the `_is_pixai_client is True` marker rather than an isinstance
    check, so a second adapter (tests/fake_pixai.py's FakePixAI) passes through without
    inheriting this class's implementation.

    Wrapping reads NO config and resolves NO credential -- that is what lets the pasted-
    API-key validation route hand its own hand-built Session to account_info and still
    get the guarantee it was built for."""
    if getattr(session, "_is_pixai_client", False) is True:
        return session
    return PixAIClient(session)


# --- end pixai_client ------------------------------------------------------


# ---------------------------------------------------------------------------
# Persisted GraphQL GET (with Apollo CSRF headers)
# ---------------------------------------------------------------------------
def gql(session, variables, retries=4):
    """Replay the history-feed persisted query. Thin delegate onto
    `PixAIClient.persisted` -- the road itself lives in the pixai_client section."""
    return _client_of(session).persisted(OPERATION_NAME, variables, retries=retries)


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


def local_media_id(path):
    """Content-addressed id for an imported (non-PixAI) file: local_<12 hex>.

    Derived from the file's BYTES. The id used to be a hash of the file's PATH, which
    let the name decide the identity -- two different pictures both landing on
    `imported/image.png` collided on the catalog row as well as on disk, and one of
    them was silently never stored. Hashing content makes that collision impossible,
    and makes the same picture imported twice from two folders recognisable as one
    picture instead of two. Returns None when the file can't be read."""
    h = _file_sha(path)
    return ("local_" + h[:12]) if h else None


_LOCAL_SUFFIX_RE = re.compile(r"(?:_local_[0-9a-f]{12})+$")


def build_local_name(path, mid):
    """<readable-stem>_<media_id><ext> -- build_stem_name()'s counterpart for a file
    with no PixAI task behind it, keeping that convention's load-bearing half: the id
    goes LAST, so anything that matches on a trailing _<media_id> treats an imported
    file exactly like a backed-up one.

    Any id already on the stem is stripped first, which is what makes this safe to run
    over its own output: without it a second pass slugs `image_local_ab12` and produces
    `image_local_ab12_local_ab12`, growing the name on every run."""
    slug = slug_from_prompt(_LOCAL_SUFFIX_RE.sub("", path.stem), 60)
    ext = path.suffix.lower()
    return "{}_{}{}".format(slug, mid, ext) if slug else "{}{}".format(mid, ext)


def migrate_local_filenames(out, db_path, thumb_dir):
    """Bring already-imported files onto the content-addressed scheme, so the library
    carries ONE naming convention rather than two. Returns (renamed, skipped).

    Curation rides along: the entire row is carried over and only media_id/filename
    change, so ratings, collections, titles and tags survive. The thumbnail is named
    after the media id, so it is renamed in step -- otherwise every migrated file
    would quietly lose its thumbnail and regenerate as a placeholder.

    Deliberately never deletes: a destination that already exists holds the same
    content (the name contains the content hash), so the row is left exactly as it
    is for a human to look at rather than resolved by removing one of them."""
    from moonglade_gallery import delete_from_catalog
    out = Path(out)
    thumb_dir = Path(thumb_dir)
    renamed = skipped = 0
    for r in load_catalog(db_path):
        if (r.get("source") or "") != "local":
            continue
        rel = (r.get("filename") or "").replace("\\", "/")
        # imported/ ONLY -- that folder holds files the importer itself copied in, so
        # their names are ours to choose. A file the owner dropped into videos/ or
        # anywhere else under the backup was named by him and is merely CATALOGUED in
        # place (run_import_local's in-place mode never moves anything); renaming those
        # would be this tool reaching into files it did not put there.
        if not rel.startswith("imported/"):
            continue
        src = out / rel
        if not src.exists():
            continue
        new_mid = local_media_id(src)
        if not new_mid:
            skipped += 1
            continue
        new_name = build_local_name(src, new_mid)
        old_mid = r.get("media_id") or ""
        if src.name == new_name and old_mid == new_mid:
            continue                                  # already on the new scheme
        dest = src.with_name(new_name)
        if dest != src:
            if dest.exists():
                skipped += 1                          # same content already there
                continue
            try:
                src.replace(dest)
            except OSError:
                skipped += 1                          # locked right now; next run gets it
                continue
        # Row first, old row second: a crash between them leaves a stale extra row
        # (visible, fixable) rather than no row at all for a file that just moved.
        row = dict(r)
        row["media_id"] = new_mid
        row["filename"] = str(dest.relative_to(out)).replace("\\", "/")
        save_catalog(db_path, [row])
        if old_mid and old_mid != new_mid:
            delete_from_catalog(db_path, old_mid)
            old_thumb = thumb_dir / "{}.jpg".format(old_mid)
            if old_thumb.exists():
                try:
                    old_thumb.replace(thumb_dir / "{}.jpg".format(new_mid))
                except OSError:
                    pass                              # regenerable; not worth failing over
        renamed += 1
        vlog("renamed import {} -> {}".format(rel, row["filename"]))
    return renamed, skipped


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

    The re-save goes to a same-directory temp and is then renamed over the original
    through _atomic_replace(), like every other on-disk writer here. Writing back
    over the source directly meant a crash, a power loss or a full disk partway
    through left a truncated image and NO original to fall back on -- this file is
    the backup, so an in-place rewrite is the one copy of the picture. The temp
    name ends in .part so the resume/organize scans that already ignore .part
    leftovers never mistake one for a finished download."""
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


# ---------------------------------------------------------------------------
# Full-meta API (task detail + model name)
# ---------------------------------------------------------------------------
_FULL_META_FIELDS = (
    "prompt_full", "natural_prompt", "seed", "steps",
    "sampler", "cfg_scale", "model_id", "model_name", "loras",
    "negative_prompt", "clip_skip", "paid_credit",
    "source_media_id", "derive_kind",
    # Full generation surface (issue #18) -- so --backfill-full-meta fills these on existing
    # rows too. MUST stay in sync with _GEN_SURFACE_FIELDS (both are static; a mismatch just
    # means a field the row-builders write but the backfill wouldn't, or vice-versa).
    "inference_profile", "quality_tag", "prompt_helper", "control_nets", "lora_parameters",
    "priority", "render_seconds", "backend", "started_at", "ended_at", "updated_at",
    "retry_count", "moderation", "video_mode", "video_model",
    # Batch identity (issue #33): PixAI's own 0-based output number + batch size from
    # getTaskById outputs.batch. Per-ROW, unlike everything else here -- extract_full_meta
    # leaves both blank at task level (fm is cached once per task) and each row resolves
    # its own via _with_batch_position before _merge_full / the backfill apply carry them.
    "batch_index", "batch_size",
)


def _paid_credit_str(task):
    """Catalog-string form of a task dict's server-reported `paidCredit` (the ACTUAL
    credit cost, known once the task ran). '' when the field is absent/null (unknown)
    -- never coerce that to '0', because '0' is a real, meaningful value (a free card
    or daily-free gen). Task-level: callers stamp it on each of the task's media rows."""
    v = (task or {}).get("paidCredit")
    return "" if v is None else str(v)


def task_detail_gql(session, task_id, retries=3):
    """GET getTaskById for one task. Returns the task dict or None on failure.

    RETRIED with backoff -- the same 3-retry shape `gql_adhoc` gives any query -- because a
    single blip here is read downstream as a LOST GENERATION. The moment that matters is the
    tail of a create path: the task has already completed and already been CHARGED, and a
    `None` here reaches `_outputs_or_raise` as "task completed but no media ids found",
    which says "your images are gone" when the task, its images and the credits are all
    exactly where PixAI left them. One timeout should not produce that sentence.

    Retrying is safe HERE specifically because this is a read-only QUERY. The rule that
    forbids a silent retry (see `gql_mutate`) is about a re-POST paying for a second
    generation; a repeated getTaskById cannot spend, delete or change anything.

    A genuine failure now says so, instead of leaving the caller to describe an outage as
    an empty result."""
    if not TASK_DETAIL_HASH:
        # Defensive only: TASK_DETAIL_HASH ships with a working built-in default (see
        # its module-level assignment above), so this fires only if that default is
        # stripped or someone blanks it in config.json -- not a real setup gate.
        raise PixAIError(
            "TASK_DETAIL_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current getTaskById "
            "sha256Hash from DevTools if the hash rotated (see RECAPTURE at the bottom of "
            "this file).")
    # Rides the one transport seam (PixAIClient.persisted) rather than hand-building the
    # persisted-GET params: same operationName, same TASK_DETAIL_HASH, same variables JSON,
    # so the wire PixAI sees is byte-for-byte what it was. The 3-retry count is preserved,
    # passed straight through -- a blip here is read downstream as a LOST GENERATION.
    # `_client_of` accepts either a raw Session or a client. Still fails SOFT: this path must
    # return None and never raise, so a single outage is not reported as "your images are
    # gone" -- the seam's raise is caught here and turned back into None.
    try:
        data = _client_of(session).persisted(
            "getTaskById", {"id": str(task_id)}, sha256=TASK_DETAIL_HASH, retries=retries)
    except (PixAIError, requests.RequestException) as e:
        print("  could not read task {} back from PixAI ({}). Nothing was spent and nothing "
              "is lost -- this call only READS a task, so the generation and its credits are "
              "exactly as PixAI left them. Try again in a moment.".format(task_id, e))
        return None
    return (data or {}).get("task")


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
    integer always wins, so a caller can still ask for anything on purpose.

    THIN DELEGATE onto `PixAIClient.query` -- the POST, the retry loop and the
    document-aware default all live in the pixai_client section, once. The function
    survives under this name because seventy-odd callers still hand it a `session`
    positionally (a raw requests.Session, a PixAIClient, or a test double are all fine)
    and because the suite patches it here."""
    return _client_of(session).query(query, variables, retries=retries)


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

    Why a retry is not free here: the ad-hoc retry loop re-POSTs on a RequestException
    or a 429/5xx, and a lost RESPONSE looks exactly like a lost REQUEST. A read timeout, a
    dropped connection, or a proxy's 502 after the backend already succeeded all leave
    PixAI holding a created, CHARGED task while the client believes nothing happened -- so
    the retry submits a second generation and pays for it twice. The same reasoning made
    `delete_batch_media_gql` single-attempt (there the damage is a second irreversible
    delete against a batch that already changed underneath it) and keeps `delete_task_gql`
    hand-rolling its own lone `session.post`.

    A 429 alone WOULD be safe to re-send (rate-limited means the request was refused, not
    processed), but 429 and 5xx share one branch in the retry loop and a 5xx is genuinely
    ambiguous. The trade is deliberate: not retrying costs an error the caller can see and
    act on; retrying wrongly costs credits they cannot get back.

    THIN DELEGATE onto `PixAIClient.mutate`, which likewise offers no `retries`
    parameter -- the rule now has ONE home rather than being re-argued at each helper."""
    return _client_of(session).mutate(query, variables)


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
    # A video task carries ONE of two blocks: `referenceVideo` for a multi-reference
    # generation, `i2vPro` for an ordinary image-to-video. Reading only the first meant every
    # plain i2v -- the common Video-tab case, and everything --sync-videos backfills -- was
    # cataloged with a blank prompt and duration, with nothing to show it had been dropped.
    # The two blocks do NOT agree on the key: referenceVideo carries `prompt`, i2vPro carries
    # `prompts` (see build_video_parameters), so both spellings are read.
    src = params.get("referenceVideo") or params.get("i2vPro") or {}
    shared = {
        "prompt": src.get("prompt") or src.get("prompts") or "",
        "duration": src.get("duration", ""),
        "i2v_model": src.get("model", ""),
        # A video's negative prompt lives INSIDE this block, never at params top level, so
        # extract_full_meta's neg (which reads params.negativePrompts) always came back blank
        # for video and --sync-videos dropped it. Surfaced here so both video row-builders read
        # one source (audit 2026-08-15); _download_video_task already read the same key directly.
        "negative_prompt": src.get("negativePrompts") or "",
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


def _row_should_blur(node):
    """Whether the picker must blur this model's cover -- ONE rule for BOTH row sources.

    model_search_rest (REST /generation-model/search) and _market_row (the GraphQL
    `generationModels` node, serving Market + Bookmarks) are documented as producing the
    SAME interchangeable row shape, and the picker renders them in one grid -- but they
    disagreed on this field: REST read the API's own `flag.shouldBlur`, GraphQL read the raw
    `isNsfw` content flag. So the same model blurred on one tab and not the other, and a
    keyword search and a Market browse of one grid gave different answers about identical
    content (M02, 2026-07-27).

    The rule, in order:

    1. The API's own `shouldBlur`, wherever the payload carries it (`flag.shouldBlur` on a
       REST row, a node-level `shouldBlur` on a GraphQL one). It is the authoritative answer
       because it is the only one computed against the VIEWER's content settings -- an
       account that has opted into seeing this content gets False here for a model whose
       `isNsfw` is perfectly true.
    2. Failing that, `isNsfw` -- the raw content flag, which knows nothing about the viewer.

    PREFERRING a field is worthless unless a query SELECTS it: the first pass at this bug
    added the preference while both GraphQL documents still asked only for `isNsfw`, so every
    real Market/Bookmarks row took branch 2 and the behaviour was byte-for-byte what the
    finding described (M02 round 2, 2026-07-27). `_model_conn_query` now asks for the field;
    branch 2 is the honest fallback for the row shapes that genuinely cannot carry it -- the
    persisted bookmark document (PixAI's own fragment, ours to send, not to edit) and, if
    their schema turns out not to expose the field at all, the degraded Market/Bookmarks
    projection that helper falls back to.

    Ambiguity resolves toward blurring, never away from it: a row that carries neither key
    reads False, but a row flagged NSFW with no viewer-scoped answer blurs -- including on
    the REST path, where `flag.shouldBlur` used to be read with a bare `.get()` so a row that
    simply omitted it showed an NSFW cover unblurred. That direction has a cost and it is
    chosen, not overlooked: if PixAI ever stops sending the flag on a row, an opted-in viewer
    gets blur they did not ask for and can clear with one click, where the other direction
    puts an NSFW cover on the screen of someone who never opted in at all."""
    node = node or {}
    flag = node.get("flag") if isinstance(node.get("flag"), dict) else {}
    for src in (flag, node):
        v = src.get("shouldBlur")
        if v is not None:
            return bool(v)
    return bool(node.get("isNsfw") or flag.get("isNsfw"))


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
        # Real field names (probed 2026-07-04): the rich description lives under
        # `modelDescription`, base-model family under `category`, and an official
        # badge under `curations` (e.g. ["inhouse"]). See private/GENERATOR_SURFACE.md.
        cur = m.get("curations") or []
        out.append({
            "title": m.get("title") or "",
            "type": m.get("type") or "",
            "model_id": str(m.get("id") or ""),
            "liked_count": int(m.get("likedCount") or 0),
            # Shared with _market_row so both paths blur the same model the same way --
            # this row keeps its authoritative flag.shouldBlur, and a row that somehow
            # arrives without one now falls back to isNsfw instead of silently not blurring.
            "should_blur": _row_should_blur(m),
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
        # Was `bool(n.get("isNsfw"))` -- the REST sibling read the API's own shouldBlur, so
        # one model blurred on Search and not on Market/Bookmarks. Both documents that feed
        # this function now SELECT the viewer-scoped flag (see _MODEL_BLUR_FIELD), and both
        # rows go through the one rule.
        "should_blur": _row_should_blur(n),
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


# The viewer-scoped blur flag, as a GraphQL leaf on a generationModels node. Requested by
# both model-connection documents through _model_conn_query below.
#
# UNPROBED, and treated as such. `flag.shouldBlur` is confirmed on the REST search row
# (2026-07-04); the same name on the GraphQL node is an inference from PixAI's own REST/GQL
# naming, not something read off a live reply. A field the schema does not have is a REJECTED
# QUERY -- the whole page, not just that leaf -- and this file's standing rule (see the
# un-guessed DateRange shape above) is that the picker must never break on a field we guessed.
# Hence: ask once per process, and if the enriched document is refused, re-run the SAME search
# without the field and remember the answer. Cost if the guess is wrong is one extra request
# per process and the pre-existing isNsfw behaviour; cost of not asking at all is that
# _row_should_blur's preference can never fire on a live row, which is the bug itself.
_MODEL_BLUR_FIELD = "shouldBlur"
# None = not asked yet this process, True = PixAI answered it, False = refused, stop asking.
_model_blur_supported = None
# A refusal has to REPEAT before it is believed. `gql_adhoc` raises PixAIError for a 200
# carrying an `errors` array -- which is the shape of PixAI's transient "Internal server
# error" as well as of a rejected field -- so a single refusal is not evidence about the
# schema at all. Latching on one blip permanently demoted Market/Bookmarks back to `isNsfw`
# for the life of a long-running gallery process, silently reopening the very disagreement
# this field was added to close. A genuinely absent field is refused EVERY time; a blip is
# not, so two consecutive refusals separate them without matching on error wording.
_model_blur_refusals = 0
_MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP = 2


def _model_conn_query(session, build, variables):
    """Run a model-connection document that ASKS for `_MODEL_BLUR_FIELD`, degrading once.

    `build(leaf)` returns the query text with `leaf` spliced into the node projection ("" for
    the original, field-less document).

    The degrade is deliberately NOT keyed on the wording of PixAI's error -- an error string
    match is a guess about a guess, and the failure it would miss is a dead Market tab. It is
    keyed on evidence instead: if the enriched document is refused and the identical document
    WITHOUT the field then succeeds, the field is the LIKELY culprit -- but only likely, since
    a transient 200-with-errors looks identical and would pass on the retry by then having
    cleared. So one such observation is not acted on; the latch goes off (and every later call
    in this process skips the field) only once refusals repeat CONSECUTIVELY, which a missing
    field does every time and a blip does not. If the plain document fails
    too, this was a real outage/auth failure -- that exception propagates untouched (one extra
    request on that path, deliberately) and the latch is left alone, so the next process asks
    again.

    No lock, unlike `_warn_media_tls_once`'s latch next door: two gallery threads racing here
    cost one duplicate probe and then agree, whereas two threads racing that one would print
    the same twenty-line TLS paragraph twice."""
    global _model_blur_supported, _model_blur_refusals
    if _model_blur_supported is False:
        return gql_adhoc(session, build(""), variables)
    try:
        data = gql_adhoc(session, build(_MODEL_BLUR_FIELD + " "), variables)
    except PixAIError as e:
        plain = gql_adhoc(session, build(""), variables)
        _model_blur_refusals += 1
        if _model_blur_refusals >= _MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP:
            _model_blur_supported = False
            vlog("model connection refused `{}` {} times ({}); retried without it -- blur "
                 "falls back to isNsfw for the rest of this run".format(
                     _MODEL_BLUR_FIELD, _model_blur_refusals, str(e)[:160]))
        else:
            vlog("model connection refused `{}` ({}); retried without it and will ask again "
                 "-- one refusal is as likely to be a transient error as a missing field"
                 .format(_MODEL_BLUR_FIELD, str(e)[:160]))
        return plain
    _model_blur_supported = True
    _model_blur_refusals = 0        # a success clears the tally: only CONSECUTIVE refusals count
    return data


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
    # `blur` is the viewer-scoped flag, spliced in by _model_conn_query so a schema that does
    # not carry it degrades to this same document without it rather than to a broken tab.
    def _q(blur):
        return ("query(" + var_decl + "){ generationModels(" + ", ".join(args) + "){ "
                "pageInfo{ hasNextPage endCursor } edges { node { id title type isNsfw "
                + blur + "likedCount bookmarked liked "
                "latestVersion { id modelType loraBaseModelType } media { id urls { url } } "
                "tags { name } author { displayName } createdAt } } } }")
    data = (_model_conn_query(session, _q, variables) or {}).get("generationModels") or {}
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

def _bookmark_node_fields(blur=""):
    """The bookmark node projection -- the same leaves the Market document asks for, so both
    tabs produce identical rows. `blur` is the viewer-scoped flag, spliced in (or not) by
    _model_conn_query; see _MODEL_BLUR_FIELD for why it is asked for conditionally."""
    return ("id title type isNsfw " + blur + "likedCount bookmarked liked "
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

    def _q(blur):
        return ("query(" + var_decl + "){ me { id bookmarkedGenerationModels(" + ", ".join(args)
                + "){ totalCount pageInfo{ hasNextPage endCursor } edges { node { "
                + _bookmark_node_fields(blur) + " } } } } }")

    conn, path = None, ""
    try:
        # Through _model_conn_query, not gql_adhoc directly: a refusal of the blur leaf must
        # be answered by re-asking ad-hoc without it, NOT by silently demoting the whole tab
        # to the persisted hash -- that route sends PixAI's own fragment, which cannot be
        # narrowed to the fields a row needs and rots when they redeploy.
        data = _model_conn_query(session, _q, variables) or {}
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
    # Rides the one transport seam (PixAIClient.persisted) instead of hand-building the
    # persisted-GET params: same operationName, same BOOKMARKED_MODELS_HASH, same variables
    # JSON, so the wire is byte-for-byte what it was (U3T is empty by default, where the old
    # `U3T or ""` and the seam's `U3T` encode identically). Single attempt, as before -- no
    # retry.
    #
    # The M03 guarantee now lives in the seam. It used to live here: a refusal answered with
    # perfectly valid but non-GraphQL JSON -- a plain {"statusCode":401,...} from the edge,
    # with no "errors" array -- once fell straight through the `or {}` tail, and the user saw
    # an EMPTY Bookmarks tab for a request that never ran (M03, 2026-07-27). persisted now
    # makes that impossible for EVERY persisted GET: it reads `errors` before status (so a
    # rotated hash still gets its recapture hint), and refuses a body with no "data" key with
    # a PixAIError rather than laundering it into an empty result. So a refusal RAISES here
    # too -- it is simply the seam raising now, not this function.
    data = _client_of(session).persisted(
        BOOKMARKED_MODELS_OP, v, sha256=BOOKMARKED_MODELS_HASH, retries=0)
    return ((data or {}).get("me") or {}).get("bookmarkedGenerationModels") or {}


def workflow_catalog(session, first=80):
    """List PixAI enhance/panelplugin WORKFLOWS via the `workflows` GraphQL connection ->
    [{id, name, type, cover_media_id}]. `id` is the numeric workflowId that
    build_panelplugin_parameters wants. Covers upscale / remove-background / line-art /
    sketch-colorizer / inpaint / outpaint / style converters / etc. Read-only.

    Restored 2026-08-18 for the Bridge tier (drift §44). NOTE: a live probe (2026-08-16/17)
    found this connection returns ZERO entries on our credential, so the six mirror-gated
    Enhance presets do NOT self-populate from it -- they are addressed by hardcoded workflow
    ids/names in the /api/enhance caller. This is kept for /api/workflows parity and so the
    picker self-updates the day PixAI opens the connection to us."""
    q = "query($n:Int){ workflows(first:$n){ edges { node { id name type coverMediaId } } } }"
    d = gql_adhoc(session, q, {"n": int(first)}) or {}
    out = []
    for e in (d.get("workflows") or {}).get("edges") or []:
        n = e.get("node") or {}
        if not n.get("id"):
            continue
        out.append({"id": str(n["id"]), "name": n.get("name") or "",
                    "type": n.get("type") or "", "cover_media_id": str(n.get("coverMediaId") or "")})
    return out


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
    (the 2026-07-21 audit's tracked O12/O13 remainder, closed picker-parity-round2,
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
    selected base model (the 2026-07-21 audit's LoRA-arch-filter item; the root-caused
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


# Sentinel parked in model_name_gql's memo cache when the LOOKUP ITSELF failed -- a network
# error, a timeout, a 5xx, an unparseable body, OR a perfectly-well-formed HTTP 200 whose
# payload is a GraphQL `errors` array rather than an answer. It is not a name and must never
# be written to a catalog row -- see model_name_gql's docstring.
_MODEL_LOOKUP_FAILED = object()


def model_name_gql(session, model_version_id, _cache={}, strict=False):
    """GET getGenerationModelByVersionId; result cached by ID (few unique models).

    Returns the id itself when the name cannot be resolved, which the callers that just want
    a label are written against. That conflated two facts with very different consequences:
    "PixAI answered, and this version has no name / no longer exists" and "the request never
    got an answer". `--fix-models --relabel-removed` acts on the first by permanently writing
    "Unknown or removed model" over the row, and `_needs_model_fix` then considers the row
    resolved -- so a single timeout mid-run mislabelled every row of a still-perfectly-valid
    model, forever, with no re-run able to repair it (M18, 2026-07-27).

    `strict=True` therefore raises PixAIError instead of returning the id when the LOOKUP
    failed. What counts as a failure is decided the way `gql()` decides it, and for the same
    reason: **PixAI answers a refused GraphQL request with HTTP 200 and an `errors` array**.
    `raise_for_status()` is blind to that shape, so an exception-only guard closed the
    network half of this bug and left the half that hurts more -- a rotated persisted hash or
    an auth failure surfaced as a resolver error refuses EVERY id in the run, so one
    `--fix-models --relabel-removed` would stamp "Unknown or removed model" over the model
    provenance of the whole catalog at once (M18 round 2, 2026-07-27). So this mirrors the one
    ordering decision that matters in `gql()` -- the `errors` array is read BEFORE the status
    is trusted at all -- and then rejects, in turn, a bad status, a body that is not a GraphQL
    reply, and a reply that simply never carried the `generationModelVersion` field we asked
    for. None of those is an answer about the model. (It does not copy `gql()`'s 401/429/5xx
    pre-checks: those exist there to drive a backoff-and-retry loop this lookup does not have,
    and every one of them ends up a failure here anyway.)

    Two things it deliberately does NOT treat as a failure, because both are real "PixAI has
    no name for this" answers: an absent MODEL_DETAIL_HASH (nothing was asked, and the
    id-as-name fallback is the documented behaviour of an unconfigured install), and a
    response that carries `generationModelVersion` explicitly NULL or title-less -- that is
    the genuinely-removed model `--relabel-removed` exists for.

    A failure is memoised as `_MODEL_LOOKUP_FAILED`, never as a name. Caching the id would
    make the failure indistinguishable from an answer for the rest of the process -- which
    matters most in `--sync`, where the full-meta pass and `--fix-models` share this cache in
    one run, so a blip during the former would otherwise be laundered into a "resolved to its
    own id" verdict for the latter. Caching the *verdict* still spares the repeat calls."""
    if not model_version_id:
        return ""
    mid = str(model_version_id)
    if mid in _cache:
        hit = _cache[mid]
        if hit is _MODEL_LOOKUP_FAILED:
            if strict:
                raise PixAIError(
                    "model {} lookup failed earlier this run; not retried".format(mid))
            return mid
        return hit
    if not MODEL_DETAIL_HASH:
        _cache[mid] = mid
        return mid
    try:
        # Rides the one transport seam (PixAIClient.persisted): same operationName, same
        # MODEL_DETAIL_HASH, same variables JSON -> byte-identical wire. retries=0 keeps this
        # SINGLE-ATTEMPT (a name lookup drives no backoff loop, exactly as before). The seam
        # already enforces the M18 ordering this function was hardened around: it reads the
        # `errors` array BEFORE trusting the status (a refused PixAI query is a 200 carrying
        # `errors`), rejects a bad status, and refuses a non-GraphQL body that has no `data`
        # key -- raising PixAIError for each, which the `except` below records as a FAILURE,
        # never as a name. What must stay HERE is the one distinction the seam cannot draw for
        # us: a reply whose `data` is missing the `generationModelVersion` field answered
        # NOTHING (fail), whereas that field present but null is the genuine "model is gone"
        # answer that --relabel-removed exists for.
        data = _client_of(session).persisted(
            "getGenerationModelByVersionId", {"id": mid},
            sha256=MODEL_DETAIL_HASH, retries=0)
        if not isinstance(data, dict) or "generationModelVersion" not in data:
            raise PixAIError("reply carried no generationModelVersion field: {}".format(
                str(data)[:200]))
        mv = data["generationModelVersion"] or {}
        title = (mv.get("model") or {}).get("title", "")
        version = mv.get("name", "")
        name = "{} {}".format(title, version).strip() if title else mid
    except Exception as e:                  # noqa: BLE001 -- a name lookup must not end a run
        # The lookup never landed. Record THAT, not the id: the id is what a successful
        # "no such model" answer also looks like, and --relabel-removed acts irreversibly
        # on the difference.
        _cache[mid] = _MODEL_LOOKUP_FAILED
        if strict:
            raise PixAIError("model {} lookup failed: {}".format(mid, str(e)[:200]))
        return mid
    _cache[mid] = name
    return name


def resolve_model_base_id(session, model_version_id):
    """The base MODEL id a generation VERSION id belongs to -- what
    `/generation-model/<id>/versions` (list_model_versions, and so the base-model picker's
    own re-resolve flow) actually wants, distinct from the VERSION id a submitted task uses
    and so the catalog's `model_id` column stores (api_generate resolves `args.model` to a
    VERSION id before submit; every catalog write path follows the same convention -- see
    moonglade_gallery.py's api_generate and this module's own catalog-row builders).

    Needed by the gallery's Runs-reel reuse-prefill (2026-08-02): it only has a run's
    catalog row, so it must ask PixAI 'what model is this a version of' before it can feed
    the picker's normal base-model-id flow -- feeding it the version id directly returns an
    empty version list (a real, verify-flagged bug: 'Model lookup failed' on every reuse
    click, old or new gens alike, since it's a catalog-wide convention).

    Same GraphQL op as model_name_gql (getGenerationModelByVersionId), deliberately its OWN
    request rather than a refactor of that function's cache: model_name_gql's failure
    semantics are hardened against two real production incidents (see its docstring, M18),
    and this is a rare, one-off, user-triggered lookup (a single reuse click), not a hot
    backfill loop -- the extra request is cheap and the isolation is worth it.

    Fails soft: '' on anything short of a clean answer (no hash configured, network error,
    GraphQL error, missing/null model) -- this is a "nice to restore" path, never a reason to
    block or mislead the caller. The caller leaves the composer's model untouched on ''
    rather than repeating today's wrong-id failure toast for a case that isn't the user's
    mistake."""
    if not model_version_id or not MODEL_DETAIL_HASH:
        return ""
    try:
        # Rides the one transport seam (PixAIClient.persisted): same operationName, same
        # MODEL_DETAIL_HASH, same variables JSON -> byte-identical wire. retries=0 (this
        # one-off reuse-click lookup drove no retry before). Fails SOFT to '' on anything
        # short of a clean answer: the seam raises PixAIError on a GraphQL error / bad status
        # / non-GraphQL body, and the `except` below turns every one of those back into ''.
        data = _client_of(session).persisted(
            "getGenerationModelByVersionId", {"id": str(model_version_id)},
            sha256=MODEL_DETAIL_HASH, retries=0)
        mv = (data.get("generationModelVersion") if isinstance(data, dict) else None) or {}
        return str((mv.get("model") or {}).get("id") or "")
    except Exception:                        # noqa: BLE001 -- a soft-fail restore, never fatal
        return ""


# The full-generation-surface columns (issue #18) extract_full_meta resolves and every
# row-builder must persist. One list so a new surface field is wired in exactly one place.
_GEN_SURFACE_FIELDS = (
    "inference_profile", "quality_tag", "prompt_helper", "control_nets", "lora_parameters",
    "priority", "render_seconds", "backend", "started_at", "ended_at", "updated_at",
    "retry_count", "moderation", "video_mode", "video_model",
)
# What EVERY create-time row-builder copies from extract_full_meta: the surface fields PLUS
# lineage (source_media_id/derive_kind). The builders used to spread only _GEN_SURFACE_FIELDS,
# so a freshly captured DERIVED image/video landed with a blank lineage panel until a separate
# --backfill-lineage ran (audit 2026-08-15). extract_full_meta already resolves both.
_TASK_ROW_FIELDS = _GEN_SURFACE_FIELDS + ("source_media_id", "derive_kind")


def _prompt_helper_label(params, task):
    """Fold promptHelper.enable + PixAI's detect verdict into one readable label:
    'on' / 'off' / 'off (reason)'. '' when the task carries neither."""
    ph = params.get("promptHelper") if isinstance(params.get("promptHelper"), dict) else {}
    det = task.get("detectPromptHelperResult") if isinstance(task.get("detectPromptHelperResult"), dict) else {}
    reason = (det.get("enableReasonCode") or "").strip()
    if "enable" not in ph and not reason:
        return ""
    base = "on" if ph.get("enable") else "off"
    return "{} ({})".format(base, reason) if reason else base


def extract_full_meta(task):
    """Pull the extended fields out of a getTaskById task dict."""
    if not task:
        return {}
    params = task.get("parameters") or {}
    outputs = task.get("outputs") or {}
    detail = outputs.get("detailParameters") or {}
    extra = params.get("extra") or {}
    # Full generation surface (issue #18): everything the task record carries that the row used
    # to drop. All pure reads from the task dict; steps/sampler/cfg get a model-preset fallback
    # in the caller (needs the network), the rest resolve here.
    i2v = params.get("i2vPro") if isinstance(params.get("i2vPro"), dict) else {}
    ii = outputs.get("inferenceInfo") if isinstance(outputs.get("inferenceInfo"), dict) else {}
    stages = ii.get("stages") if isinstance(ii.get("stages"), dict) else {}
    qtag = params.get("qualityTag") if isinstance(params.get("qualityTag"), dict) else {}
    cnets = params.get("controlNets") or []
    lparams = params.get("loraParameters") or []
    run_s = stages.get("pipeline_run_s")
    retry = task.get("retryCount")
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
    # LINEAGE: the source image + derivation kind, if this task derived from another image.
    # Filled here so both the forward sync and --backfill-full-meta populate it for free.
    src_mid, derive_kind = source_media_of_task(task)
    return {
        "source_media_id": src_mid or "",
        "derive_kind":     derive_kind or "",
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
        # Full generation surface (issue #18):
        "inference_profile": str(params.get("inferenceProfile") or ""),
        "quality_tag":       str(qtag.get("prefix") or ""),
        "prompt_helper":     _prompt_helper_label(params, task),
        "control_nets":      json.dumps(cnets) if cnets else "",
        "lora_parameters":   json.dumps(lparams) if lparams else "",
        "priority":          str(params.get("priority") or ""),
        "render_seconds":    ("{:.1f}".format(run_s) if isinstance(run_s, (int, float)) else ""),
        "backend":           str(ii.get("backend") or ""),
        "started_at":        str(task.get("startedAt") or ""),
        "ended_at":          str(task.get("endAt") or ""),
        "updated_at":        str(task.get("updatedAt") or ""),
        "retry_count":       ("" if retry is None else str(retry)),
        "moderation":        str((task.get("moderationAction") or {}).get("promptsModerationAction") or ""),
        "video_mode":        str(i2v.get("mode") or ""),
        "video_model":       str(i2v.get("model") or ""),
        # BATCH IDENTITY (issue #33): blank at TASK level on purpose -- outputs.batch is an
        # ordered array with one entry per output, so the index is a per-ROW fact. The raw
        # list is parked under _batch (private, never persisted: _merge_full and the backfill
        # apply iterate _FULL_META_FIELDS only) and each row resolves its own index/size via
        # _with_batch_position. A task with no batch array (edit/upscale/video/chat) parks
        # None and every row of it stays blank -- "not a batch output", never inferred.
        "batch_index": "",
        "batch_size":  "",
        "_batch":      outputs.get("batch") if isinstance(outputs.get("batch"), list) else None,
    }


def batch_position(batch, media_id):
    """PixAI's own output number for one media of a task (issue #33): the position of
    `media_id` in the task's ORDERED outputs.batch array -- the same <n> the site's own
    download names use (from-PixAI-<taskId>-<n>, verified against real downloads).
    Returns ('<index>', '<size>') as 0-based catalog strings, or ('', '') when there is
    no batch array (edits, upscales, videos, imports) or the media id is not in it --
    blank means "not a batch output", NEVER a guess from media_id order (which can swap
    outputs; probe 2026-08-23). The index is PixAI's permanent fact: a sibling deleted
    later keeps its gap, nothing is ever renumbered."""
    if not isinstance(batch, list) or not batch:
        return "", ""
    mid = str(media_id or "")
    if not mid:
        return "", ""
    for i, entry in enumerate(batch):
        if isinstance(entry, dict) and str(entry.get("mediaId") or "") == mid:
            return str(i), str(len(batch))
    return "", ""


def _with_batch_position(fm, media_id):
    """Per-ROW view of a task-level full-meta dict (issue #33): fm is fetched and cached
    once per task, but batch_index/batch_size differ per output, so each row resolves its
    own from the raw outputs.batch list extract_full_meta parked under fm['_batch'].
    Returns fm itself when there is nothing to resolve (no batch array, or the media id
    is not one of its outputs -- both fields stay ''), else a shallow copy with both set,
    leaving the shared cached dict untouched."""
    bi, bs = batch_position((fm or {}).get("_batch"), media_id)
    if not bi:
        return fm
    fm = dict(fm)
    fm["batch_index"], fm["batch_size"] = bi, bs
    return fm


def _resolve_model_preset(session, version_id, _cache={}):
    """The model VERSION's default sampling params from getGenerationModelByVersionId's
    `extra` -> {steps, sampler, cfg_scale}, each '' when the version exposes no default for it.
    VERSION-accurate (keyed on the exact version the gen used, so no latest-version drift), and
    cached per version id. Never raises.

    Crucially self-limiting: a flow/DiT model like Tsubaki.2 (AuraFlow) exposes samplingSteps
    but NO samplingMethod / cfgScale, so those come back '' and an em-dash there stays the
    honest answer (that model genuinely has no sampler or CFG) -- only a value the model really
    defaults to is ever filled (issue #18)."""
    vid = str(version_id or "")
    if not vid:
        return {}
    if vid in _cache:
        return _cache[vid]
    preset = {}
    if MODEL_DETAIL_HASH:
        try:
            # Rides the one transport seam (PixAIClient.persisted): same operationName, same
            # MODEL_DETAIL_HASH, same variables JSON -> byte-identical wire. retries=0 (a
            # single GET, as before). Never raises out: the seam's PixAIError on any refusal
            # is caught here and the preset stays {} -- an em-dash is the honest answer when a
            # model genuinely exposes no default for a field.
            data = _client_of(session).persisted(
                "getGenerationModelByVersionId", {"id": vid},
                sha256=MODEL_DETAIL_HASH, retries=0)
            mv = (data.get("generationModelVersion") if isinstance(data, dict) else None) or {}
            ex = mv.get("extra") or {}
            steps, sampler, cfg = ex.get("samplingSteps"), ex.get("samplingMethod"), ex.get("cfgScale")
            preset = {
                "steps":     ("" if steps is None else str(steps)),
                "sampler":   (str(sampler) if sampler else ""),
                "cfg_scale": ("" if cfg is None else str(cfg)),
            }
        except Exception:
            preset = {}
    _cache[vid] = preset
    return preset


def _fill_preset_defaults(session, fm, task):
    """Backfill fm's steps/sampler/cfg_scale from the model VERSION preset when the task itself
    omitted them (issue #18: Tsubaki.2's detailParameters is absent, so the gen ran on the
    model's baked defaults recorded nowhere in the task). Mutates + returns fm.

    Gated to plain IMAGE diffusion gens: a chat/edit task or an i2v video task carries no image
    sampling params, so it is skipped and its em-dashes stay. Only fills a field that is blank
    AND has a non-null preset value -- never overwrites a task-recorded value, never invents one
    the model has no default for."""
    if not isinstance(fm, dict):
        return fm
    params = (task or {}).get("parameters") or {}
    if params.get("chat") or params.get("i2vPro"):     # not a plain image diffusion gen
        return fm
    if (fm.get("steps") or "").strip() and (fm.get("sampler") or "").strip() and (fm.get("cfg_scale") or "").strip():
        return fm                                        # nothing missing -> no lookup
    preset = _resolve_model_preset(session, fm.get("model_id", ""))
    for k in ("steps", "sampler", "cfg_scale"):
        if not (fm.get(k) or "").strip() and preset.get(k):
            fm[k] = preset[k]
    return fm


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


def known_catalog_rows(db_path, ids):
    """The pre-download snapshot carry_local_fields needs: media_id -> existing row.

    Keyed to just this task's media, so it is a lookup rather than a whole-catalog read.
    A catalog that does not exist yet -- the first collect into a fresh output folder,
    before save_catalog creates the table -- means there is nothing local to carry, which
    is an empty map and not an error.
    """
    try:
        rows = rows_for_media_ids(db_path, ids)
    except sqlite3.OperationalError:
        return {}
    return {r["media_id"]: r for r in rows if r.get("media_id")}


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
    unchanged. Applied at save time, it covers every row-builder path at once.

    APPLIED AT, since issue #19 closed the gap, in TWO places and no others:

      * `build_catalog_row` -- so EVERY create-time capture path gets the carry by
        construction rather than by remembering: run_sync_videos, run_import_local,
        run_generate, _download_video_task, _download_image_task, run_edit_image, and
        the gallery's /api/loom/import-bundle. The two collect writers
        (_download_image_task / _download_video_task) are the per-task path every
        create route funnels through -- run_generate, run_edit_image,
        run_generate_video, collect_generation, the watch mirror, CLI --task-id
        recovery -- and until 2026-09-03 they were missing it, so RE-collecting a task
        wiped exactly the fields listed above; a finished generation polled twice was
        enough to do it. Four of the seven builders still had no carry at all until the
        helper gave them one.
      * run_download's page saves and its backfill pass, which build their rows from
        the feed rather than through build_catalog_row and so still apply it directly.
    """
    base = dict(known.get(row.get("media_id", ""), {}))
    for k, v in row.items():
        if v not in ("", None):
            base[k] = v
        else:
            base.setdefault(k, "")
    return base


def _created_at_utc(value=""):
    """A capture's `created_at`: PixAI's own `createdAt` when the task carries one, else
    NOW as UTC + 'Z'.

    The Z matters. `created_at` is sorted as a plain STRING (`_SORT_SQL` does no
    `datetime()` wrapping), so a naive LOCAL-time stamp reads as hours "older" than a
    same-moment UTC one west of Greenwich -- a local save at 23:0X PDT sorted behind rows
    PixAI timestamped 06:05 UTC the "next" day, an hour earlier in real time. Found via
    run_import_local, which had the same defect; the four task-capture paths each carried
    their own copy of this rule AND of the paragraph explaining it, which is why it now
    lives in exactly one place."""
    return value or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_catalog_row(media_id, *, fm=None, known=None,
                      task_id="", filename="", url="", source="", status="",
                      created_at="", prompt_full="", prompt_preview=None,
                      natural_prompt="", negative_prompt="", seed="",
                      steps="", sampler="", cfg_scale="", clip_skip="",
                      model_id="", model_name="", loras="", paid_credit="",
                      width="", height="",
                      is_video="", poster_media_id="", video_duration=""):
    """THE create-time catalog row. Every capture path -- download, generate, edit, video,
    local import -- builds its row here, so they all write the same surface and none of them
    can clobber what the user owns (issue #19 item 4).

    Three things happen, in this order, for every caller:

      1. Start from the blank `CATALOG_FIELDS` template, so a row always carries every
         column and a newly added column is blank rather than absent.
      2. Set the API/file fields below, then spread `_TASK_ROW_FIELDS` from `fm`
         (`extract_full_meta`'s output) UNIFORMLY -- the 15 generation-surface columns of
         issue #18 plus lineage (`source_media_id`/`derive_kind`). A caller with no task
         (a local import) passes no `fm` and those stay blank.
      3. Merge the result over `known` via `carry_local_fields`, so LOCAL curation --
         artwork_id, is_published, title, rating, collections, art_tags, aes_score,
         blurhash -- survives a re-capture of a media_id already in the catalog.

    Step 3 is the point. Before this helper, six call sites hand-assembled the same row and
    only two of them remembered the carry; re-collecting an already-collected generation
    rebuilt its row from the blank template and erased the user's work (owner, live,
    2026-09-03: a published piece lost its artwork_id when a relaunch re-polled a finished
    task). `known` maps media_id -> the pre-capture catalog row; pass
    `known_catalog_rows(db_path, ids)`. Omitting it is only correct where the caller has
    already established that the media_id is NOT in the catalog.

    They also DRIFT, which is the other half of why this exists: the 2026-08-15 audit found
    lineage missing from every site at once, and the video paths dropping fields the image
    paths kept. A field added here now reaches every capture path in one edit.

    WHO SETS WHAT (7 call sites; blank at any site not listed):

      field              set by                                source
      -----------------  ------------------------------------  --------------------------
      media_id           all                                   the output's media id
      task_id            SV, GEN, VID, IMG, EDIT               the task's id
      filename           all                                   path relative to out/, '/'-joined
      url                GEN, VID, IMG, EDIT                   resolve_media / media_file_gql
      source             IMP='local'; GEN,VID,IMG,EDIT,LOOM='api'  provenance (SV leaves '')
      status             SV,GEN,VID,IMG,EDIT='completed'; IMP,LOOM='imported'
      created_at         all                                   _created_at_utc(task.createdAt)
                                                               at GEN/VID/IMG/EDIT; the node's
                                                               own createdAt at SV (no
                                                               fallback); file mtime as UTC+Z
                                                               at IMP
      prompt_full        SV, GEN, VID, IMG, EDIT               task prompt / submitted prompt
      prompt_preview     defaults to prompt_full[:100]         SV passes promptsPreview,
                                                               IMP/LOOM the file stem
      negative_prompt    SV, GEN, VID, IMG                     video shared block (SV/VID),
                                                               fm->submitted (GEN), fm (IMG)
      natural_prompt     GEN, IMG                              fm
      seed               SV, GEN, VID, IMG, EDIT               the per-output seed
      steps/sampler/     GEN, IMG                              fm ONLY -- task-echoed ->
        cfg_scale                                              model preset -> blank; never
                                                               the submitted value (owner
                                                               ruling 2026-08-15)
      clip_skip          GEN, IMG                              fm
      model_id           SV, GEN, VID, IMG, EDIT               parameters.modelId / the
                                                               submitted block / fm /
                                                               chat.modelId
      model_name         GEN, IMG, EDIT                        _resolved_model_name /
                                                               _edit_model_label
      loras              GEN, IMG                              _resolved_loras (resolved
                                                               names+weights, not fm)
      paid_credit        SV, GEN, VID, IMG, EDIT               _paid_credit_str -- TASK-level,
                                                               repeated on each media row
      width/height       SV, GEN, VID, IMG, EDIT               media info -> detailParameters
                                                               -> submitted dims
      is_video           SV, VID='1'; IMP, LOOM per extension
      poster_media_id    SV, VID                               the still-frame media id
      video_duration     SV, VID                               shared/submitted duration
      _TASK_ROW_FIELDS   every site, uniformly                 fm (blank when there is no task)

    Sites: SV=run_sync_videos, IMP=run_import_local, GEN=run_generate,
    VID=_download_video_task, IMG=_download_image_task, EDIT=run_edit_image,
    LOOM=moonglade_gallery's /api/loom/import-bundle."""
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({
        "task_id": task_id, "media_id": media_id, "filename": filename, "url": url,
        "source": source, "status": status, "created_at": created_at,
        "prompt_full": prompt_full,
        "prompt_preview": (prompt_full or "")[:100] if prompt_preview is None else prompt_preview,
        "natural_prompt": natural_prompt, "negative_prompt": negative_prompt,
        "seed": seed, "steps": steps, "sampler": sampler, "cfg_scale": cfg_scale,
        "clip_skip": clip_skip, "model_id": model_id, "model_name": model_name,
        "loras": loras, "paid_credit": paid_credit, "width": width, "height": height,
        "is_video": is_video, "poster_media_id": poster_media_id,
        "video_duration": video_duration,
    })
    # issue #18 + lineage, spread for EVERY caller instead of once per site.
    row.update({k: (fm or {}).get(k, "") for k in _TASK_ROW_FIELDS})
    return carry_local_fields(row, known or {})


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


# The bucket classifier is `moonglade_gallery.bucket_of` -- the LIBRARY SCAN
# section's one copy. This alias keeps the private name every caller (and
# tests/test_dedup.py's `core._bucket_of` assertions) already uses.
_bucket_of = bucket_of


def _scan_media_files(out_dir):
    """One walk of the tree. Yields (path, rel, bucket, media_id) for every image
    file outside gallery/, _duplicates/, and _deleted/. The audit's view (and, via
    verify_quarantine, the dedup-verify pass) onto the shared scan.

    _deleted/ exclusion is B11 (audit 2026-07-21): without it, a locally-purged
    image is a valid audit hit -- reported back as a live Class A duplicate of its
    own quarantined self, and (via verify_quarantine's survivor index) potentially
    treated as the "surviving keeper" a _duplicates/ copy is compared against.

    Deliberately does NOT drop zero-byte files (named disagreement 3): the audit
    has to SEE one in order to never choose it as a keeper -- tests/test_dedup.py
    pins that, and it is why the scan reports `size` rather than deciding."""
    for e in scan_library(out_dir, kinds=("image",), exclude=QUARANTINE_EXCLUDE):
        yield e.path, e.rel, e.bucket, e.media_id


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

    # This walker's own exclusion (named disagreement 6): the shared quarantine set
    # plus videos/ and imported/, which organize must leave alone because they are
    # not PixAI images to normalize.
    skip_dirs = QUARANTINE_EXCLUDE + ("videos", "imported")

    def _target(mid, row, ext):
        month = (row.get("created_at") or "")[:7] or "unknown-date"
        stem = build_stem_name(row.get("prompt_preview", ""), row.get("task_id", ""),
                               mid, args.name_length, args.name_sep)
        return out / month / (stem + ext)

    # Sources: every PixAI image on disk (catalog media), wherever it currently is.
    plan, in_place = [], 0
    for e in scan_library(out, kinds=("image",), exclude=skip_dirs):
        p = e.path
        if p.name.startswith("_"):
            continue                       # organize's own rule, about files not folders
        row = meta_by_mid.get(e.media_id)
        if not row or (row.get("source") or "") == "local":
            continue                       # unknown file or user import: leave it
        dst = _target(e.media_id, row, p.suffix.lower())
        if p.resolve() == dst.resolve():
            in_place += 1
            continue
        plan.append((p, dst, e.media_id, row))

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
    """Validate config, load token, return a configured PixAIClient.

    The app's ONE entry to PixAI: it re-reads config.json at call time (so the GUI works
    even when the module was imported before the working directory was set correctly),
    refreshes the persisted-hash globals from it, builds the API-key requests.Session, and
    resolves USER_ID over the network when it is not pinned.

    It returns a `PixAIClient`, not the bare Session -- the client IS accepted everywhere a
    `session` is passed today (it delegates `get`/`post`/`headers`/`cookies` to the Session
    it holds, and every primitive resolves whatever it is handed through `_client_of`), so
    the ~70 session-taking functions are unchanged. The name stays `_make_session` because
    thirty-odd call sites and a hundred-odd tests say it."""
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
    # Hand the resolved account id to the client so `client.user_id` carries it directly.
    # The module global stays as the config seed / resolution home and the client's own
    # `or USER_ID` fallback, but business logic now reads the id off the client, not here.
    return PixAIClient(session, auth_kind="api-key", user_id=USER_ID)


# ===========================================================================
# Website-mirror JWT: zero-paste acquisition + self-renewal.
#
# The API key files a generation under the account but does NOT make it appear in
# the pixai.art web LIBRARY -- only a browser-session submission does. The Control
# Panel "Mirror to PixAI" toggle uses the helpers below to hold a live browser
# session with NO manual pastes, the way the site keeps itself logged in.
#
# Mechanism (confirmed from a live getMyInfo capture 2026-08-14):
#   - The session rides short cookies on .pixai.art that the server rolls forward
#     on every response: _bsid (~30m) + _udt (~60m; _udt IS the u3t value) + .sig
#     pairs (cache-control:no-store, vary:Origin,Authorization).
#   - The JWT rides as Authorization: Bearer (~27d); a FRESH jwt is returned in the
#     `token` response header (access-control-expose-headers: token,...).
#   - refreshToken is a no-arg persisted mutation (REFRESH_TOKEN_HASH).
# So: read the .pixai.art session from the local browser ONCE (cookies-from-browser),
# then the cookies self-refresh and refreshToken rolls the JWT -- zero paste. A
# one-time paste field is the break-glass fallback only.
#
# SAFETY: only touched when the mirror toggle is ON (pure API-key mode never calls
# these). The credential never leaves this machine and is never printed, logged, or
# committed (same rule as PIXAI_API_KEY); diagnostics report only non-secret
# derivatives (expiry date, days-left, ok/None). The live "read the real browser +
# first refreshToken" step self-verifies at runtime on the owner's machine.
# ===========================================================================
def _b64url_decode(seg):
    """Decode one base64url JWT segment, tolerant of missing padding."""
    seg = seg + "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg.encode("ascii"))


def jwt_claims(token):
    """The JWT payload claims as a dict, or {} if unparseable. Decodes the payload
    ONLY (never verifies the signature -- we don't hold the key and don't need to;
    PixAI validates it, we just read `exp`). Never raises."""
    try:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            return {}
        claims = json.loads(_b64url_decode(parts[1]))
        return claims if isinstance(claims, dict) else {}   # a non-object payload is not claims
    except Exception:
        return {}


def jwt_expiry(token):
    """Unix `exp` (seconds) or None. Offline."""
    exp = jwt_claims(token).get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def jwt_days_left(token, now=None):
    """Whole days until the JWT expires, or None. Offline -- what the Panel countdown
    ('PixAI mirror: N days left') renders, decoded at startup with no network call."""
    exp = jwt_expiry(token)
    if exp is None:
        return None
    now = time.time() if now is None else now
    return int((exp - now) // 86400)


def mirror_needs_refresh(token, now=None, threshold_days=MIRROR_REFRESH_WHEN_DAYS_LEFT):
    """True when the JWT is missing, unparseable, expired, or within the cushion --
    i.e. the renewal loop should call refreshToken. Pure; the scheduler's decision."""
    left = jwt_days_left(token, now=now)
    return left is None or left <= threshold_days


def read_browser_session(browsers=("chrome", "edge", "brave")):
    """Read the current .pixai.art session cookies from the local browser store, the
    way yt-dlp's --cookies-from-browser does. Returns {name: value} for the cookies
    found, or {} if none could be read. NEVER raises and NEVER logs a value.

    Prefers `browser_cookie3` (handles Chrome/Edge/Brave/Firefox + the Windows DPAPI +
    AES-GCM decrypt across OSes). Falls back to the native Windows reader below. On a
    machine with neither a browser nor the dep, returns {} and the caller degrades to
    the stored session / the break-glass paste."""
    jar = {}
    try:
        import browser_cookie3 as bc3  # optional dep; the robust path
    except Exception:
        bc3 = None
    if bc3 is not None:
        for name in browsers:
            loader = getattr(bc3, name, None)
            if loader is None:
                continue
            try:
                cj = loader(domain_name=PIXAI_COOKIE_DOMAIN)
                for c in cj:
                    if PIXAI_COOKIE_DOMAIN in (c.domain or ""):
                        jar[c.name] = c.value
                if jar:
                    return jar
            except Exception:
                continue  # locked profile, no such browser, decrypt fail -> try next
        if jar:
            return jar
    try:
        return _read_chromium_cookies_windows()
    except Exception:
        return {}


def _read_chromium_cookies_windows():
    """Native Windows Chrome/Edge cookie read: AES-GCM values decrypted with the
    profile key from Local State (DPAPI-unprotected). Read-only; copies the
    share-readable DB to a temp file so an open browser doesn't block it. Returns {}
    on any failure -- a best-effort fallback, never a hard dependency. No value logged."""
    import shutil
    import sqlite3
    import tempfile
    la = os.environ.get("LOCALAPPDATA", "")
    profiles = [
        os.path.join(la, r"Google\Chrome\User Data"),
        os.path.join(la, r"Microsoft\Edge\User Data"),
    ]
    jar = {}
    for udir in profiles:
        ck = os.path.join(udir, "Default", "Network", "Cookies")
        ls = os.path.join(udir, "Local State")
        if not (os.path.isfile(ck) and os.path.isfile(ls)):
            continue
        try:
            key = _chromium_aes_key(ls)
            if not key:
                continue
            tmp = os.path.join(tempfile.gettempdir(), "mg_ck_%d.db" % os.getpid())
            shutil.copy2(ck, tmp)  # native copy succeeds even while the browser holds it
            try:
                con = sqlite3.connect(tmp)
                rows = con.execute(
                    "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                    ("%" + PIXAI_COOKIE_DOMAIN,),
                ).fetchall()
                con.close()
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            for name, enc in rows:
                val = _chromium_decrypt(enc, key)
                if val:
                    jar[name] = val
            if jar:
                return jar
        except Exception:
            continue
    return jar


def _chromium_aes_key(local_state_path):
    """The per-profile AES key from Local State, DPAPI-unprotected. Windows only."""
    try:
        import win32crypt  # from pywin32
    except Exception:
        return None
    with open(local_state_path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    enc_key = base64.b64decode(state["os_crypt"]["encrypted_key"])
    enc_key = enc_key[5:]  # strip the "DPAPI" prefix
    return win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]


def _chromium_decrypt(enc, key):
    """AES-256-GCM decrypt of a Chromium v10/v11 cookie value. '' on failure."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if enc[:3] in (b"v10", b"v11"):
            nonce, ct = enc[3:15], enc[15:]
            return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8", "replace")
    except Exception:
        pass
    return ""


# --- localStorage JWT reader ------------------------------------------------------
# Modern Chrome (>=127) wraps the cookie store in app-bound "v20" encryption a normal
# user process can't decrypt, so the cookie path above returns nothing there. But the
# pixai.art frontend ALSO keeps the live JWT in localStorage, and localStorage's
# on-disk store (Local Storage/leveldb) is NOT app-bound-encrypted -- so we read the JWT
# straight out of it. That's the whole reason "Connect" can work on a current Chrome
# without a paste. The Bearer JWT alone authenticates the mirror (create rides
# Authorization: Bearer; refreshToken renews off the Bearer), so cookies are optional.
#
# We parse leveldb properly (a minimal pure-Python reader -- no C dep, no third-party
# library). A raw byte-scan is NOT enough: an established profile compacts its writes into
# .ldb SSTables whose keys are PREFIX-COMPRESSED (the literal "https://api.pixai.art:token"
# never appears contiguously) and whose data blocks are usually SNAPPY-COMPRESSED (the JWT
# bytes aren't even there in the clear). So we reconstruct real key->value pairs from both
# the .ldb SSTables and the .log write-ahead log, match the exact localStorage key, and
# validate the decoded token's issuer is "pixai" before trusting it. The freshest (max
# `exp`) wins across every file/profile. Read-only; NEVER raises, NEVER logs a value.
def _read_file_shared(path):
    """Read a file Chrome may hold open. Direct read first (Chromium opens leveldb files
    share-read on Windows); on failure, copy to temp and read the copy. b'' on failure,
    never raises."""
    import shutil
    import tempfile
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        pass
    tmp = os.path.join(tempfile.gettempdir(),
                       "mg_ls_%d_%s_%s" % (os.getpid(), secrets.token_hex(4),
                                           os.path.basename(path)))
    try:
        shutil.copy2(path, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    except OSError:
        return b""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _lvarint(buf, pos):
    """Decode a leveldb base-128 varint at buf[pos:]. Returns (value, next_pos). Raises
    IndexError if it runs off the end (callers treat that as a malformed block)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _snappy_decompress(data):
    """Pure-Python Snappy block decompression (the codec leveldb uses for SSTable blocks).
    Returns the decompressed bytes, or None on malformed input. No dependency."""
    try:
        expect, pos = _lvarint(data, 0)
        out = bytearray()
        n = len(data)
        while pos < n:
            tag = data[pos]
            pos += 1
            kind = tag & 0x03
            if kind == 0:                       # literal
                length = tag >> 2
                if length >= 60:
                    nbytes = length - 59        # 60->1 .. 63->4 extra length bytes
                    length = 0
                    for i in range(nbytes):
                        length |= data[pos + i] << (8 * i)
                    pos += nbytes
                length += 1
                out += data[pos:pos + length]
                pos += length
            else:
                if kind == 1:                   # copy, 1-byte offset
                    length = 4 + ((tag >> 2) & 0x07)
                    offset = ((tag >> 5) << 8) | data[pos]
                    pos += 1
                elif kind == 2:                 # copy, 2-byte offset
                    length = 1 + (tag >> 2)
                    offset = data[pos] | (data[pos + 1] << 8)
                    pos += 2
                else:                           # kind == 3, copy, 4-byte offset
                    length = 1 + (tag >> 2)
                    offset = (data[pos] | (data[pos + 1] << 8)
                              | (data[pos + 2] << 16) | (data[pos + 3] << 24))
                    pos += 4
                if offset <= 0 or offset > len(out):
                    return None
                start = len(out) - offset
                for i in range(length):         # byte-by-byte: copies may overlap
                    out.append(out[start + i])
        return bytes(out) if len(out) == expect else None
    except (IndexError, ValueError):
        return None


def _lvldb_decompress_block(data, offset, size):
    """The block at [offset, offset+size), decompressed per its 1-byte compression-type
    trailer (0 none, 1 snappy, 2 zlib, 4 zstd). None if unreadable/unknown."""
    if offset < 0 or offset + size + 1 > len(data):
        return None
    raw = data[offset:offset + size]
    comp = data[offset + size]
    if comp == 0:
        return raw
    if comp == 1:
        return _snappy_decompress(raw)
    if comp == 2:
        try:
            import zlib
            return zlib.decompress(raw)
        except Exception:
            return None
    if comp == 4:
        try:
            from compression import zstd        # Python 3.14+ stdlib
            return zstd.decompress(raw)
        except Exception:
            try:
                import zstandard                 # optional third-party fallback
                return zstandard.ZstdDecompressor().decompress(raw)
            except Exception:
                return None
    return None


def _lvldb_block_pairs(block):
    """Yield (key, value) from one decompressed leveldb block, undoing prefix compression.
    The block ends with a restart array: [restart offsets...][num_restarts as uint32 LE].
    A malformed block yields nothing rather than raising."""
    n = len(block)
    if n < 4:
        return
    try:
        num_restarts = int.from_bytes(block[n - 4:n], "little")
        entries_end = n - 4 - num_restarts * 4
        if entries_end < 0:
            return
        pos = 0
        last_key = b""
        while pos < entries_end:
            shared, pos = _lvarint(block, pos)
            non_shared, pos = _lvarint(block, pos)
            value_len, pos = _lvarint(block, pos)
            key = last_key[:shared] + block[pos:pos + non_shared]
            pos += non_shared
            value = block[pos:pos + value_len]
            pos += value_len
            last_key = key
            yield key, value
    except (IndexError, ValueError):
        return


_LVLDB_SSTABLE_MAGIC = 0xDB4775248B80FB57


def _lvldb_sstable_entries(data):
    """Yield (user_key, value, seq, is_deletion) from a leveldb .ldb SSTable. Reads the footer
    -> index block -> each data block (decompressing as needed) -> prefix-decoded entries. The
    8-byte internal-key trailer encodes (seq<<8 | type) little-endian; type 0 is a deletion
    tombstone. Yields nothing on any structural surprise (never raises)."""
    n = len(data)
    if n < 48:
        return
    try:
        footer = data[n - 48:n]
        if int.from_bytes(footer[40:48], "little") != _LVLDB_SSTABLE_MAGIC:
            return
        p = 0
        _, p = _lvarint(footer, p)                # metaindex handle offset (skip)
        _, p = _lvarint(footer, p)                # metaindex handle size   (skip)
        idx_off, p = _lvarint(footer, p)
        idx_size, p = _lvarint(footer, p)
    except (IndexError, ValueError):
        return
    index_block = _lvldb_decompress_block(data, idx_off, idx_size)
    if index_block is None:
        return
    for _sep, handle in _lvldb_block_pairs(index_block):
        try:
            b_off, hp = _lvarint(handle, 0)
            b_size, _hp = _lvarint(handle, hp)
        except (IndexError, ValueError):
            continue
        blk = _lvldb_decompress_block(data, b_off, b_size)
        if blk is None:
            continue
        for key, value in _lvldb_block_pairs(blk):
            if len(key) >= 8:                    # internal-key trailer = seq<<8 | type
                trailer = int.from_bytes(key[-8:], "little")
                yield key[:-8], value, trailer >> 8, (trailer & 0xFF) == 0


def _lvldb_log_entries(data):
    """Yield (key, value, seq, is_deletion) from a leveldb .log write-ahead log. Each
    WriteBatch header carries the sequence number of its first entry; entry i has seq = base+i.
    Reassembles physical record fragments across 32 KiB blocks. Deletions are yielded as
    tombstones (empty value, is_deletion=True) so a later logout can suppress an earlier PUT.
    Yields nothing on malformed input (never raises)."""
    BLOCK = 32768
    n = len(data)
    pos = 0
    frag = b""
    try:
        while pos + 7 <= n:
            block_left = BLOCK - (pos % BLOCK)
            if block_left < 7:                   # zero-padded block trailer -> next block
                pos += block_left
                continue
            length = data[pos + 4] | (data[pos + 5] << 8)
            rtype = data[pos + 6]
            pos += 7
            chunk = data[pos:pos + length]
            pos += length                        # ALWAYS consume the payload, even for a
            if rtype == 0 or length == 0:        # zero/padding record -- else a kZeroType
                continue                         # record with a payload desyncs every record
            if rtype == 1:                       # FULL
                rec = chunk
            elif rtype == 2:                     # FIRST
                frag = chunk
                continue
            elif rtype == 3:                     # MIDDLE
                frag += chunk
                continue
            elif rtype == 4:                     # LAST
                rec = frag + chunk
                frag = b""
            else:
                frag = b""
                continue
            # WriteBatch: header seq(8)+count(4)=12, then entries; entry i has seq base+i
            if len(rec) < 12:
                continue
            base_seq = int.from_bytes(rec[0:8], "little")
            rp = 12
            rn = len(rec)
            idx = 0
            while rp < rn:
                tag = rec[rp]
                rp += 1
                if tag == 1:                     # kTypeValue: key, value
                    klen, rp = _lvarint(rec, rp)
                    key = rec[rp:rp + klen]
                    rp += klen
                    vlen, rp = _lvarint(rec, rp)
                    value = rec[rp:rp + vlen]
                    rp += vlen
                    yield key, value, base_seq + idx, False
                    idx += 1
                elif tag == 0:                   # kTypeDeletion: key only
                    klen, rp = _lvarint(rec, rp)
                    key = rec[rp:rp + klen]
                    rp += klen
                    yield key, b"", base_seq + idx, True
                    idx += 1
                else:
                    break                        # unknown tag -> stop this batch
    except (IndexError, ValueError):
        return


def _lvldb_value_to_jwt(value):
    """A Chromium localStorage value (encoding byte + payload) -> JWT string, or ''. 0x00 is
    UTF-16LE, 0x01 is Latin-1 (a JWT is ASCII, so ours is 0x01)."""
    if not value:
        return ""
    enc, body = value[0], value[1:]
    try:
        if enc == 0:
            s = body.decode("utf-16-le", "ignore")
        elif enc == 1:
            s = body.decode("latin-1", "ignore")
        else:
            s = value.decode("latin-1", "ignore")
    except Exception:
        return ""
    s = s.strip()
    return s if s.startswith("eyJ") and s.count(".") == 2 else ""


def _pick_pixai_token(entries):
    """THE pixai.art auth token from ONE profile's leveldb entries, honoring leveldb's own
    last-writer-wins-by-sequence semantics. `entries` are (user_key, value, seq, is_deletion)
    tuples from that profile's .ldb + .log (which share one sequence space). Among entries for
    the token key (ends with LOCALSTORAGE_JWT_KEY, contains 'pixai'), the HIGHEST sequence
    number is the live state: if it's a deletion tombstone (logout) -> '' (not a stale token);
    otherwise decode it and require iss=='pixai' (the definitive guard -- the Local Storage
    store is shared across every origin, so unrelated JWTs live beside it). Returns '' if none.
    Sequence numbers are unique per write, so ties are effectively impossible; if two values
    tie (bottom-level seq-zeroing), the later `exp` wins, and any tombstone at the top wins."""
    best_seq = -1
    deleted_at_top = False
    values_at_top = []                           # (exp, jwt) for value entries at best_seq
    for key, value, seq, is_del in entries:
        if b"pixai" not in key or not key.endswith(LOCALSTORAGE_JWT_KEY):
            continue
        if seq > best_seq:
            best_seq = seq
            deleted_at_top = False
            values_at_top = []
        if seq == best_seq:
            if is_del:
                deleted_at_top = True
            else:
                jwt = _lvldb_value_to_jwt(value)
                if jwt and jwt_claims(jwt).get("iss") == "pixai":
                    exp = jwt_expiry(jwt)
                    values_at_top.append((exp if exp is not None else -1, jwt))
    if best_seq < 0 or deleted_at_top or not values_at_top:
        return ""
    values_at_top.sort()
    return values_at_top[-1][1]                   # freshest value at the top sequence


def read_browser_jwt(browsers=("chrome", "edge", "brave")):
    """The live pixai.art JWT read from a local browser's localStorage, across ALL profiles
    (Default, Profile N, ...) of the given Chromium browsers. Each profile is resolved on its
    own sequence space (a logout tombstone there suppresses that profile's older token); the
    freshest LIVE token (max `exp`) across profiles wins. Returns '' if none. This is what lets
    'Connect' bootstrap the mirror on a current Chrome whose cookie store is
    app-bound-encrypted. NEVER raises, NEVER logs the value."""
    la = os.environ.get("LOCALAPPDATA", "")
    roots = {
        "chrome": os.path.join(la, r"Google\Chrome\User Data"),
        "edge": os.path.join(la, r"Microsoft\Edge\User Data"),
        "brave": os.path.join(la, r"BraveSoftware\Brave-Browser\User Data"),
    }

    def _profile_entries(ldb):
        try:
            files = os.listdir(ldb)
        except OSError:
            return
        for fn in files:
            path = os.path.join(ldb, fn)
            if fn.endswith(".ldb"):
                blob = _read_file_shared(path)
                if blob:
                    yield from _lvldb_sstable_entries(blob)
            elif fn.endswith(".log"):
                blob = _read_file_shared(path)
                if blob:
                    yield from _lvldb_log_entries(blob)

    candidates = []
    for name in browsers:
        udir = roots.get(name)
        if not udir or not os.path.isdir(udir):
            continue
        try:
            profiles = os.listdir(udir)
        except OSError:
            continue
        for prof in profiles:
            ldb = os.path.join(udir, prof, "Local Storage", "leveldb")
            if not os.path.isdir(ldb):
                continue
            tok = _pick_pixai_token(_profile_entries(ldb))   # per-profile, tombstone-aware
            if tok:
                candidates.append(tok)

    best, best_exp = "", -1                       # freshest live token across profiles
    for j in candidates:
        e = jwt_expiry(j)
        if e is not None and e > best_exp:
            best, best_exp = j, e
    return best


def refresh_jwt(session, current_jwt=None):
    """Call the no-arg refreshToken mutation and return a genuinely FRESH JWT, or None.

    `session` is a JWT-authed requests.Session (from _mirror_session_from). The new jwt
    arrives in the `token` response header; the mutation's scalar return is the fallback
    shape. Renews our own token only -- it does not spend. Returns None (never raises) on any
    error, so the caller keeps the current jwt until it truly expires.

    Guards against a FALSE "renewed" (review): the gateway rolls the SAME token back in the
    `token` header on ordinary authenticated responses, and a GraphQL error (e.g.
    PersistedQueryNotFound after a hash rotation) still answers HTTP 200 carrying that echo.
    So a renewal requires status 200, NO `errors` array, and a token that DIFFERS from the
    one we sent -- an unchanged token is not a renewal."""
    headers = {
        "Content-Type": "application/json",
        "apollo-require-preflight": "true",
        "x-apollo-operation-name": "refreshToken",
    }
    if current_jwt:
        headers["Authorization"] = "Bearer " + current_jwt
    body = {
        "operationName": "refreshToken",
        "variables": {},
        "extensions": {
            "clientLibrary": CLIENT_LIBRARY,
            "persistedQuery": {"version": 1, "sha256Hash": REFRESH_TOKEN_HASH},
        },
    }
    try:
        r = session.post(API_URL, json=body, headers=headers, timeout=30)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json() or {}
    except Exception:
        payload = {}
    if payload.get("errors"):
        return None                        # error response -> its echoed token is NOT fresh
    cur = current_jwt or ""
    tok = r.headers.get("token")
    if tok and tok != cur and jwt_expiry(tok):
        return tok
    val = (payload.get("data") or {}).get("refreshToken")
    if isinstance(val, str) and val != cur and jwt_expiry(val):
        return val
    return None


# --- Mirror session state: a dedicated git-ignored store (NOT config.json) --------
# Single-flight lock: serializes the refresh->persist critical section so two threads can't
# both fire refreshToken and race their writes. The SLOW work (the leveldb/localStorage
# browser read and the no-network fast path) runs OUTSIDE the lock so a Connect can't block
# every Generate -- an earlier version held the lock across a ~12 s scan plus a 30 s POST
# (adversarial review 2026-08-15). The gallery serves threaded=True.
_mirror_lock = threading.Lock()
# Backoff so a persistently-failing refresh (rotated hash, expired session, PixAI 5xx) is not
# re-fired on EVERY create while the JWT sits inside its refresh cushion (review). time-based.
_mirror_refresh_next_try = 0.0
_MIRROR_REFRESH_COOLDOWN = 600      # seconds to wait after a failed refresh before retrying


def _mirror_state_path():
    """Where the rotating mirror session (JWT + cookie jar) lives: a dedicated
    git-ignored file beside config.json. Deliberately NOT config.json -- the JWT
    rotates on every refresh, and a write there must never risk clobbering the API
    key (a test once overwrote the real PIXAI_API_KEY; a separate file can't)."""
    return _config_path().parent / "mirror_session.json"


def load_mirror_state():
    """The stored mirror session {jwt} or {} if none. (A legacy `cookies` key from older
    builds is ignored -- the mirror is JWT-only now.) Never raises, never logs a value."""
    p = _mirror_state_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def save_mirror_state(state):
    """Atomically persist {jwt} to the git-ignored mirror file. Best-effort: True/False,
    never raises, never logs a value. JWT-only: cookies are no longer stored -- the Bearer
    JWT authenticates both the create and the refresh; the short session cookies died ~1 h
    after issue (so they never survived to a day-22 refresh anyway), and pairing a
    Default-profile cookie jar with an any-profile JWT risked a cross-identity submit (review)."""
    p = _mirror_state_path()
    # Per-WRITE-unique temp (pid + random), not per-process: the gallery is threaded, so a
    # per-pid temp name lets two concurrent savers interleave into one file then both
    # os.replace -> corrupt JSON -> load returns {} -> mirror "lost" (review F5). A unique
    # temp per write + atomic replace makes concurrent saves last-writer-wins, never corrupt.
    tmp = p.with_name(p.name + ".tmp-{}-{}".format(os.getpid(), secrets.token_hex(6)))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"jwt": state.get("jwt", "")}, f, indent=2)
        os.replace(tmp, p)
        return True
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def mirror_enabled():
    """Is the Control Panel 'Mirror to PixAI website' toggle on? Reads config fresh
    (git-ignored MIRROR_TO_PIXAI flag). Default OFF = pure API-key mode. When ON, the create
    POST rides the browser JWT (see _session_for_create) so the generation lands in the
    pixai.art web library."""
    return bool(_load_config().get("MIRROR_TO_PIXAI"))


def _jwt_usable(jwt):
    """True only when the JWT is present, parseable, and not expired (days_left >= 0). This
    is the gate for 'can the mirror actually submit with this' -- distinct from merely
    'a JWT string exists', which is what let an expired stored token block a browser re-read."""
    if not jwt:
        return False
    left = jwt_days_left(jwt)
    return left is not None and left >= 0


def _mirror_session_from(jwt):
    """A requests.Session authed as the browser JWT (Bearer) and presenting the WEB client
    identity -- used for BOTH the refreshToken probe and the mirrored create. Built directly,
    NOT via _make_session, so it never enforces the API-key/U3T precondition the mirror
    doesn't need and never resolves USER_ID over the browser token (review). JWT-only, no
    cookies. The web identity makes PixAI apply the website content policy, not the stricter
    mobile-app one; x-apollo-operation-name is present for Apollo CSRF (value need only be
    present, not correct)."""
    session = requests.Session()
    if jwt:
        session.headers["Authorization"] = "Bearer " + jwt
    session.headers.update({
        "Accept": "application/json",
        "apollo-require-preflight": "true",
        "x-apollo-operation-name": OPERATION_NAME,
        "User-Agent": MIRROR_WEB_USER_AGENT,
        "Origin": MIRROR_WEB_ORIGIN,
        "Referer": MIRROR_WEB_ORIGIN + "/",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    return session


def make_mirror_session(bootstrap_from_browser=False):
    """The mirror submit/refresh session: a requests.Session authed with the browser JWT
    (Bearer) presenting the WEB client identity. Returns None -- NEVER raises -- when there is
    no USABLE (present, parseable, unexpired) JWT even after a browser re-read and a refresh;
    callers must then refuse and spend nothing, never an API-key fallback (review F5).

    JWT-only, and built via _mirror_session_from (NOT _make_session): the API-key path's
    precondition/USER_ID-resolution must not run over the browser token (review).

    Lock scope: the SLOW browser read runs OUTSIDE _mirror_lock; only the refresh->persist
    critical section takes the lock (single-flight), and a failed refresh backs off so it is
    not re-fired on every create (review)."""
    global _mirror_refresh_next_try
    jwt = load_mirror_state().get("jwt") or ""
    # (Re-)bootstrap from the browser whenever the stored JWT is not USABLE -- not merely when
    # it is absent. Gating on `not jwt` meant an expired stored token could never be replaced,
    # which left Connect and --mirror-check permanently dead until the file was hand-deleted
    # (review). The browser read is slow, so it happens before the lock.
    if bootstrap_from_browser and not _jwt_usable(jwt):
        bj = read_browser_jwt()
        if bj:
            jwt = bj
            save_mirror_state({"jwt": jwt})
    # Roll the JWT forward when inside the refresh cushion -- but never under READ_ONLY
    # (refreshToken is account-mutating), and not more often than the cooldown after a failure.
    if jwt and mirror_needs_refresh(jwt) and not (READ_ONLY or _read_only_now()):
        with _mirror_lock:
            cur = load_mirror_state().get("jwt") or jwt      # a peer thread may have refreshed
            if mirror_needs_refresh(cur):
                now = time.time()
                if now >= _mirror_refresh_next_try:
                    fresh = refresh_jwt(_mirror_session_from(cur), current_jwt=cur)
                    if fresh:
                        cur = fresh
                        save_mirror_state({"jwt": cur})
                        _mirror_refresh_next_try = 0.0
                    else:
                        _mirror_refresh_next_try = now + _MIRROR_REFRESH_COOLDOWN
            jwt = cur
    if not _jwt_usable(jwt):
        return None                        # absent/expired -> refuse, never API-key (F5)
    return _mirror_session_from(jwt)


def _session_for_create(api_session):
    """The session the CREATE POST must use: the browser JWT (mirror) when the 'Mirror to
    PixAI' toggle is on, so the generation lands in the pixai.art web library; else the
    API-key api_session, exactly as today. The single choke every create site routes
    through (review F4) -- swap ONLY the create's session, never the poll/collect/media
    calls (F6), and NEVER fall back to the API key when mirroring: if the mirror session
    is unavailable, refuse and spend nothing (F5).

    Callers must have already passed _check_read_only, since make_mirror_session may make a
    refreshToken network call (review F12). free-card (/v2/kaisuuken/check) still runs on the
    API-key session at the call site -- only the create rides the JWT."""
    if not mirror_enabled():
        return api_session
    m = make_mirror_session()
    if m is None:
        raise PixAIError(
            "Mirror to PixAI is ON but its browser session is expired or unavailable -- "
            "run `--mirror-check` (or re-bootstrap from a logged-in browser). Nothing was "
            "submitted and no credits were spent.")
    return m


def run_mirror_check(args):
    """--mirror-check: prove the zero-paste mirror loop WITHOUT ever printing the token.
    Tries the stored session; if none, reads the pixai.art session from a local browser;
    calls refreshToken to confirm renewal; reports only days-left + ok/fail and persists
    the fresh session. This is the owner's step-0 verification -- it renews our own token
    and spends nothing. If it can't read a browser (e.g. run headless/sandboxed), it says
    so plainly rather than guessing. Refused under READ_ONLY (refreshToken is account-mutating)."""
    if READ_ONLY or _read_only_now():
        print("Mirror: READ_ONLY is set in config.json -- refusing to refresh the mirror "
              "token (refreshToken is an account-mutating call). Clear READ_ONLY to run this.")
        return {"ok": False, "source": "read_only"}
    jwt = load_mirror_state().get("jwt") or ""
    src = "stored"
    if not _jwt_usable(jwt):
        bj = read_browser_jwt()          # localStorage: works on a v20-cookie Chrome
        if bj:
            jwt = bj
            src = "browser"
    if not jwt:
        print("Mirror: no session. No usable JWT in mirror_session.json, and none readable "
              "from a local browser's pixai.art localStorage (is a browser installed and "
              "logged in to pixai.art?). Open pixai.art logged-in, then retry.")
        return {"ok": False, "source": "none"}
    before = jwt_days_left(jwt)
    fresh = refresh_jwt(_mirror_session_from(jwt), current_jwt=jwt)
    if not fresh:
        # A still-valid JWT whose refresh merely failed (rotated hash, transient 5xx) is
        # reported distinctly from a truly-dead one, and its jar is NOT wiped.
        if _jwt_usable(jwt):
            save_mirror_state({"jwt": jwt})
            print("Mirror ({}): the stored JWT is still valid ({} days left) but refreshToken "
                  "did NOT return a fresh token -- renewal may be temporarily unavailable "
                  "(a PixAI hash rotation or a transient error). It keeps working until it "
                  "nears expiry; re-run then.".format(src, before))
            return {"ok": True, "source": src, "renewed": False, "days_left": before}
        print("Mirror ({}): the JWT is expired and refreshToken did not renew it. Re-open "
              "pixai.art logged-in, then retry.".format(src))
        return {"ok": False, "source": src, "renewed": False}
    after = jwt_days_left(fresh)
    saved = save_mirror_state({"jwt": fresh})
    print("Mirror OK (source: {}). refreshToken renewed the JWT -> {} days left{}. {}".format(
        src, after, "" if before is None else " (was {})".format(before),
        "Stored." if saved else "WARNING: could not persist mirror_session.json."))
    return {"ok": True, "source": src, "renewed": True, "days_left": after}


# ===========================================================================
# MIRROR-SUBMIT INVARIANTS (upheld by the code above; from the 2026-08-14 adversarial review
# and the 2026-08-15 ultrareview). This is a SPEND + CREDENTIAL path -- keep all of these:
#  1. Single submit: exactly one createGenerationTask per create; the create session is
#     swapped ONLY at the _session_for_create choke, and every credit-spending create routes
#     through it (image/edit/video/reference-video via submit_generation, AND the /v2 fixer).
#  2. No gql_adhoc for spend: createGenerationTask goes through gql_mutate (retries=0).
#  3. READ_ONLY fires before any mirror network call: refreshToken (make_mirror_session,
#     run_mirror_check, /api/mirror/connect) and the create (submit_generation/submit_fixer).
#  4. No credential emission: the JWT is never printed/logged/returned; diagnostics report
#     only days-left + ok/None; the credential travels only in a POST body/Authorization.
#  5. No silent API-key fallback: make_mirror_session decides refuse-vs-allow OFFLINE from a
#     usable-JWT check and returns None on failure; _session_for_create raises rather than
#     using the API key when the mirror is ON.
#  6. Collect stays on the API-key session: only the create POST rides the mirror JWT;
#     poll / collect_generation / GET /v1/media do NOT.
#  7. JWT-only: no cookies are stored or paired (they died ~1 h after issue and pairing them
#     across browser profiles risked a cross-identity submit).
# ===========================================================================


def run_probe(args):
    """Test API connection and resolve full-res media URL for the newest task."""
    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))
    print("Fetching newest page...\n")
    conn = find_connection(gql(session, page_variables(
        args.page_size, _client_of(session).user_id)))
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
        conn = find_connection(gql(session, page_variables(
            count_size, _client_of(session).user_id, before)))
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
    counts = _count_backup_images(out) if out.exists() else DiskCounts(0, 0, 0)
    disk_count, disk_bytes, thumb_count = counts
    print("\n--- On disk ({}) ---".format(args.out))
    print("Image files on disk       : {}".format(disk_count))
    if thumb_count:
        print("  + preview thumbnails    : {}".format(thumb_count))
    if counts.trashed:
        print("  + soft-deleted (trash)  : {}  ({}, in {}/)".format(
            counts.trashed, _format_size(counts.trashed_bytes), DELETED_DIRNAME))
    print("Total collection size     : {}".format(
        _format_size(disk_bytes) if disk_bytes else "0 B (folder empty or not found)"))
    if images > tasks:
        print("\nNote: image count exceeds task count because some older tasks\n"
              "produced batches of several images -- all of them get downloaded.")


def artwork_list_gql(session, before=None, last=50):
    """GET listArtworks for the owner's own authorId. Returns the Relay
    connection dict (edges + pageInfo) or None on failure."""
    variables = {"authorId": str(_client_of(session).user_id), "last": last,
                 "tackLanguage": "en"}
    if before:
        variables["before"] = before
    # Rides the one transport seam (PixAIClient.persisted): same operationName, same
    # ARTWORK_LIST_HASH, same variables JSON -> byte-identical wire. This op is the one that
    # sends its OWN Apollo clientLibrary block (CLIENT_LIBRARY_ARTWORK) and an
    # x-apollo-operation-name CSRF header, both threaded through persisted's `client_library=`
    # / `headers=` so the request PixAI sees is byte-for-byte what it was. retries=0 (a single
    # GET, as before). Fails SOFT to None on any refusal: the seam raises PixAIError on a bad
    # status / GraphQL error / non-GraphQL body, all caught here.
    try:
        data = _client_of(session).persisted(
            "listArtworks", variables, sha256=ARTWORK_LIST_HASH,
            client_library=CLIENT_LIBRARY_ARTWORK, retries=0,
            headers={"x-apollo-operation-name": "listArtworks"})
    except (requests.RequestException, PixAIError, ValueError):
        return None
    return find_connection(data or {})


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
        # PixAI's own moderation flag, distinct from the binary is_nsfw (a work can be
        # sensitive without being nsfw) -- already in the listArtworks response, the app just
        # never read it (#20). Powers the "Sensitive" badge in My Art.
        "is_sensitive":  "1" if node.get("isSensitive") else "0",
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
    if not _client_of(session).user_id:
        raise PixAIError("USER_ID is missing and could not be resolved from your API key. "
                         "Add USER_ID to config.json as a fallback.")

    by_mid = {}                      # media_id -> artwork fields
    by_video_mid = {}                # videoMediaId -> artwork fields. An animation's
                                     # catalog row is keyed by its MP4's media_id (is_video
                                     # '1'), not the poster mediaId that `by_mid` holds, so
                                     # without this map the video row never receives an
                                     # artwork_id and the Animations tab stays empty (#20).
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
                by_video_mid[str(vmid)] = meta      # tag the animation's own row too (#20)
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
        # match a row by its own media_id (still artworks) OR by a videoMediaId
        # (animations, whose row is keyed by the mp4) -- #20.
        m = by_mid.get(r.get("media_id")) or by_video_mid.get(r.get("media_id"))
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
    # Pre-pass snapshot of the existing rows, keyed by media_id: the rows built
    # below start from an all-blank CATALOG_FIELDS template, so upserting them raw
    # blanked every locally-owned column (rating, collections, art_tags, title,
    # is_published, aes_score, blurhash) on EVERY re-run of this sync. Handed to
    # build_catalog_row, which carries those columns forward for every capture path.
    known = {r["media_id"]: r for r in load_catalog(db_path) if r.get("media_id")}
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
            getattr(args, "page_size", 250) or 250,
            _client_of(session).user_id, before)))
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
        full_meta = extract_full_meta(task)   # issue #18: the full generation surface (video row)
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
                full = build_catalog_row(
                    vmid, fm=full_meta, known=known,   # fm: issue #18 (no preset fill: video)
                    task_id=str(node["id"]),
                    filename=str(path.relative_to(out)).replace("\\", "/"),
                    prompt_full=shared.get("prompt", ""),
                    # NOT prompt_full[:100]: the summary node carries its own preview.
                    prompt_preview=(node.get("promptsPreview") or "")[:100],
                    seed=str(o.get("seed") or ""),
                    created_at=node.get("createdAt", ""),   # a listed task always has one
                    width=str(detail.get("width") or ""),
                    height=str(detail.get("height") or ""),
                    model_id=str(params.get("modelId") or ""),
                    negative_prompt=shared.get("negative_prompt", ""),   # video block, not top level
                    status="completed",
                    is_video="1",
                    poster_media_id=o.get("poster_media_id", ""),
                    paid_credit=_paid_credit_str(task),   # actual cost, task-level
                    video_duration=str(shared.get("duration") or ""),
                )
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
        save_catalog(db_path, new_rows)   # the carry already happened in build_catalog_row
    print("Videos saved/present: {}{}.".format(
        ok, " | {} had no resolvable file url".format(missing) if missing else ""))
    return {"i2v_tasks": len(i2v_nodes), "videos": ok}


# _VIDEO_EXTS is the LIBRARY SCAN section's `"video"` kind, imported at the top of
# this file with the rest of the shared base -- one spelling of the video extension
# set instead of the three this file, the gallery's health walk and the loom bundle
# each used to keep.


def _under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


# ===========================================================================
# media_tools -- the ONE ffmpeg / ffprobe seam
# ===========================================================================
# Every ffmpeg and ffprobe invocation in this app enters the OS through this
# section. Before it existed there were seven call sites across
# moonglade_backup.py and moonglade_gallery.py, and each one re-typed the same
# four things: an availability check, `creationflags=_NO_WINDOW`, a timeout, and
# a blanket `except`. They disagreed on all four. Two of them asked ffprobe the
# SAME question -- how long is this clip -- through different `-of` flags and
# answered differently (one rounded to 2dp, one did not), and were called
# crosswise from both modules. Two invoked the binary by bare name where the
# others used a which()-resolved path. One cached its which(), one re-ran it per
# file. video_poster_thumb's own comment had already banked the diagnosis: "two
# copies of this wheel WILL drift."
#
# What lives here, exactly once:
#
#   * availability -- ffmpeg_path() / ffprobe_path(), one cached probe each,
#     asked separately because they are separately installable.
#   * the flags -- NO_WINDOW, on every spawn.
#   * the timeouts -- the *_TIMEOUT constants below ARE the policy; a caller
#     naming its own number is how the old sites drifted 15 apart from 20.
#   * the failure rule -- a media tool NEVER raises at its caller and never
#     blocks the work it serves. run_ffmpeg/run_ffprobe answer with a
#     ToolResult, and every failure they swallow gets a vlog() line so a
#     degraded run is on record instead of silent.
#
# ToolResult.missing is the load-bearing part. "The binary is not installed" used
# to reach every caller as a FileNotFoundError caught by a blanket `except` that
# could not tell it apart from a corrupt file, so the difference between "there
# is no audio" and "I could not look" was lost at the seam. It is now a field.
# That is the mechanism under the standing rule that a missing ffprobe DEGRADES
# the Loom export and never blocks it: the export can ask which kind of nothing
# it got back.
#
# A nonzero returncode is deliberately NOT logged here and NOT a `missing`: it is
# ffmpeg's ordinary way of refusing a file, its meaning is caller-specific (the
# faststart remux reads its stderr and names the clip; a thumbnail just retries
# with different flags), and logging it here would double up on the caller's own,
# better message.
#
# The gallery reaches this section as `core.<name>` through a function-body
# `import moonglade_backup as core` -- module scope would be an import cycle,
# since this module imports moonglade_gallery at the top.

NO_WINDOW = _NO_WINDOW   # re-exported: no caller of this section reaches for the raw constant

# The timeout policy, in one place. Sized by what the invocation actually does,
# not by which module happens to be calling.
PROBE_TIMEOUT = 20         # ffprobe: a metadata read, no decoding
FRAME_TIMEOUT = 45         # one frame out of one clip
THUMB_TIMEOUT = 90         # the thumbnail filter scans a batch of opening frames
THUMB_RETRY_TIMEOUT = 60   # ...and the literal-first-frame retry behind it
REMUX_TIMEOUT = 300        # faststart: -c copy over the whole file


@dataclass(frozen=True)
class ToolResult:
    """What one ffmpeg/ffprobe invocation did. Never an exception.

    `ok`          -- the process ran and exited 0.
    `returncode`  -- its exit code, or None when no process completed at all
                     (binary absent, timed out, failed to spawn).
    `stdout`/`stderr` -- text, always captured. ffmpeg reports WHY it refused
                     something on stderr and nowhere else.
    `missing`     -- the binary is not installed. The degrade-never-block road:
                     a caller answers this differently from a real failure.
    """
    ok: bool
    returncode: object
    stdout: str
    stderr: str
    missing: bool


_TOOL_PATHS = {}


def _tool_path(name):
    """Resolved path to a media binary, or '' -- asked of the OS once per process.

    Cached because it is asked on per-file hot paths (every clip in a thumbnail
    sweep, every shot in an export) and a which() is a directory walk. The price is
    that installing ffmpeg while the app runs needs a restart to be noticed, which
    is the deal the old `_ffmpeg_path` already made; the gallery's uncached copies
    paid a which() per file for a refresh nobody was waiting on."""
    if name not in _TOOL_PATHS:
        import shutil
        _TOOL_PATHS[name] = shutil.which(name) or ""
    return _TOOL_PATHS[name]


def ffmpeg_path():
    """Path to ffmpeg, or '' when it is not installed (cached -- see _tool_path).

    Public because some callers must gate BEFORE building work: the faststart sweep
    prints one honest line instead of walking the library, and the Loom export
    refuses up front rather than assembling a filtergraph nothing can run."""
    return _tool_path("ffmpeg")


def ffprobe_path():
    """Path to ffprobe, or '' when it is not installed (cached -- see _tool_path).

    Asked SEPARATELY from ffmpeg_path() on purpose. They ship together in a full
    build but not in every package, and the machine with ffmpeg and no ffprobe is
    exactly the one the Loom export has to keep serving -- gating the two together
    would take a working feature away over a binary the wiki never asks for."""
    return _tool_path("ffprobe")


def _reset_tool_cache():
    """Forget the resolved binary paths. For tests that exercise the caching itself;
    production has no reason to re-ask."""
    _TOOL_PATHS.clear()


def _as_text(v):
    """Whatever a completed process handed back, as str. The one decode point."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _run_tool(name, path, args, timeout, input=None):
    """Spawn one media binary and answer with a ToolResult. Never raises.

    The single owner of the missing-binary road, `creationflags=NO_WINDOW`, the
    timeout, stream capture, decoding, and the vlog() line for every failure that
    used to disappear into a caller's blanket `except`."""
    import subprocess
    if not path:
        vlog("{} is not installed; skipping: {}".format(
            name, " ".join(str(a) for a in args[:4])))
        return ToolResult(ok=False, returncode=None, stdout="",
                          stderr="{} not found on PATH".format(name), missing=True)
    argv = [path] + [str(a) for a in args]
    try:
        # stdout/stderr are PIPEd explicitly rather than via capture_output=True:
        # ffmpeg's stderr is the entire diagnostic on a refusal, and with `-v error`
        # it prints nothing at all on success, so piping costs nothing on the happy
        # path. Decoding is pinned to utf-8/replace because the alternative -- the
        # platform locale with strict errors -- can raise out of a call whose whole
        # contract is that it does not.
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, input=input, creationflags=NO_WINDOW)
    except FileNotFoundError as e:
        # which() said yes and the exec still failed: the binary moved, or a shim
        # points at nothing. Same road for the caller as never having had it.
        vlog("{} vanished between which() and exec: {}".format(name, e))
        return ToolResult(ok=False, returncode=None, stdout="", stderr=str(e), missing=True)
    except subprocess.TimeoutExpired:
        vlog("{} timed out after {}s: {}".format(name, timeout, " ".join(argv[1:5])))
        return ToolResult(ok=False, returncode=None, stdout="",
                          stderr="timed out after {}s".format(timeout), missing=False)
    except Exception as e:                       # noqa: BLE001 -- a media tool never raises at its caller
        vlog("{} failed to run: {}".format(name, e))
        return ToolResult(ok=False, returncode=None, stdout="", stderr=str(e), missing=False)
    return ToolResult(ok=(r.returncode == 0), returncode=r.returncode,
                      stdout=_as_text(r.stdout), stderr=_as_text(r.stderr), missing=False)


def run_ffmpeg(args, *, timeout, input=None):
    """Run ffmpeg with `args` -- everything AFTER the binary, which this supplies.
    Never raises; see ToolResult. `input` is stdin text for the rare filter that
    wants it (the streams are text-mode, so bytes are not accepted)."""
    return _run_tool("ffmpeg", ffmpeg_path(), args, timeout, input=input)


def run_ffprobe(args, *, timeout):
    """Run ffprobe with `args` -- everything AFTER the binary, which this supplies.
    Never raises; see ToolResult."""
    return _run_tool("ffprobe", ffprobe_path(), args, timeout)


def duration(path, *, timeout=None):
    """Real length of a clip in seconds, or None when it cannot be read.

    THE one answer to "how long is this file". There used to be two, asking ffprobe
    the same question through different flags: this module's `probe_video_duration`
    (`-of default=noprint_wrappers=1:nokey=1`, 20s, rounded to 2dp) and the
    gallery's `probe_duration` (`-of csv=p=0`, 15s, full precision), each called
    from both modules. Full precision wins, because rounding is a display choice and
    a measurement that has already been rounded cannot be un-rounded -- a caller that
    wants 2dp rounds at its own call site, where the reason it wants them is visible.
    """
    r = run_ffprobe(["-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)],
                    timeout=PROBE_TIMEOUT if timeout is None else timeout)
    if not r.ok:
        return None
    try:
        return float(r.stdout.strip())
    except (TypeError, ValueError):
        return None


def has_audio(path, *, timeout=None):
    """True/False for "does this file carry at least one audio stream", and None
    when ffprobe could not answer at all.

    The three-way answer is the whole point. "Definitely silent" and "I could not
    look" are different facts, and collapsing them is how a machine without ffprobe
    came to read every clip as silent with nothing able to notice. A caller that
    only needs the safe reading -- treat unknown as silent -- coerces with bool(),
    in one place, on purpose."""
    r = run_ffprobe(["-v", "error", "-select_streams", "a", "-show_entries",
                     "stream=index", "-of", "csv=p=0", str(path)],
                    timeout=PROBE_TIMEOUT if timeout is None else timeout)
    if not r.ok:
        return None
    return bool(r.stdout.strip())


def extract_last_frame(video_path, out_png, at_seconds=None, *, trim_aware=True):
    """Grab a clip's frame to out_png via ffmpeg. This is the frame-handoff primitive:
    one shot's last frame becomes the next shot's opening frame, so a sequence reads as
    one continuous scene.

    `at_seconds` makes the handoff TRIM-AWARE: the previous shot's trimOut is the point
    the cut actually ends on, so the handed-off frame must be the frame AT that out-point,
    not the untrimmed clip's real final frame. When it's None (no trim) -- or past the
    clip's real end -- fall back to seeking ~0.15s before EOF. Returns out_png or None.

    It is also GENERAL: `at_seconds=0.0` takes the explicit-seek branch and yields the
    FIRST frame. Nothing in this app should write a second frame extractor; `frame_at`
    below is this function under the module's argument order, not another copy of it.

    `trim_aware=False` skips the duration measurement and seeks to `at_seconds` as given
    -- for a caller that already knows its timestamp is inside the clip."""
    import os
    if at_seconds is not None and trim_aware:
        dur = duration(video_path)
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
    except (TypeError, ValueError):
        return None
    r = run_ffmpeg(["-y"] + seek +
                   ["-update", "1", "-frames:v", "1", "-q:v", "2", str(out_png)],
                   timeout=FRAME_TIMEOUT)
    if not r.ok:
        return None
    try:
        return str(out_png) if os.path.exists(out_png) and os.path.getsize(out_png) > 0 else None
    except OSError:
        return None


def frame_at(path, t, out, *, trim_aware=True):
    """Write the frame at `t` seconds of `path` to `out`; `t=None` means the clip's
    last frame, `t=0.0` its first. Returns `out` or None.

    The module-interface face of extract_last_frame, which stays THE frame primitive
    and keeps its name because the rest of the app and the decision record both call
    it that. This is a signature, not a second implementation."""
    return extract_last_frame(path, out, at_seconds=t, trim_aware=trim_aware)


# --- end media_tools -------------------------------------------------------


def video_poster_thumb(video_path, thumb_path):
    """Extract a frame of a video via ffmpeg and write it as the gallery thumbnail.
    OPTIONAL: returns False (no-op) if ffmpeg isn't on PATH, so videos just fall
    back to the placeholder + play badge. Used for imported videos and as a
    fallback for i2v videos with no still-frame poster.

    Thin delegate: the ONE ffmpeg-extract implementation lives in
    moonglade_gallery.make_video_thumbnail (which build_thumbnails' poster-less
    fallback also uses) -- two copies of this wheel WILL drift. The availability
    guard stays here because import-local and sync-videos gate on it."""
    if not ffmpeg_path():
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


# What a faststart attempt actually DID. Three outcomes, because two are not enough: a bool
# collapses "I tried and ffmpeg refused" into the same False as "there was nothing to do",
# and a sweep that treats that union as failure reports a healthy file as broken. The
# concurrency that makes them collide is BLESSED by the docs -- wiki/Backing-Up.md says
# --faststart-videos is safe to run while the gallery or a live watch is collecting, and the
# live mirror remuxes the same clips -- so between one caller's "not faststart" check and the
# next line of code the file can legitimately already be fixed, or gone from Trash entirely
# (M04 round 2, 2026-07-27).
FASTSTART_REWROTE = "rewrote"        # the file was not faststart and now is
FASTSTART_NOT_NEEDED = "not-needed"  # nothing to do: already faststart, vanished, not a video
FASTSTART_REFUSED = "refused"        # ffmpeg (or the swap) tried and failed -- a REAL failure


def _video_faststart_attempt(path):
    """The remux, reporting WHICH of the three FASTSTART_* outcomes happened.

    `video_faststart` below is the bool face of this, kept because almost every caller only
    wants "did the file change" -- see its docstring for the mechanism and the unique-temp
    rationale. Only run_faststart_videos, which has to account for every clip it walked and
    name the ones still broken, needs the third answer."""
    p = Path(path)
    if p.suffix.lower() not in (".mp4", ".mov", ".m4v"):
        return FASTSTART_NOT_NEEDED
    ff = ffmpeg_path()
    if not ff or not p.exists() or _mp4_is_faststart(p):
        # Deliberately NOT a refusal. This is the branch a concurrent collector's remux (or a
        # Trash purge) lands in when it wins the race with a sweep that had already decided
        # this file needed work; calling it a failure prints "still not iOS-playable" about a
        # file that is now perfectly playable.
        return FASTSTART_NOT_NEEDED
    from uuid import uuid4
    # unique per call; the real ext stays LAST so ffmpeg still picks the muxer by extension
    tmp = p.with_name(p.stem + ".__fstmp__" + uuid4().hex[:8] + p.suffix)
    try:
        # Through media_tools: the binary, the no-window flag, the timeout and the "never
        # raises" rule all come from there. stderr arrives CAPTURED because run_ffmpeg pipes
        # it always -- ffmpeg reports why it refused a remux there and nowhere else, and with
        # -v error it prints nothing at all on success.
        r = run_ffmpeg(["-y", "-v", "error", "-i", str(p),
                        "-c", "copy", "-movflags", "+faststart", str(tmp)],
                       timeout=REMUX_TIMEOUT)
        if r.ok and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(str(tmp), str(p))            # atomic swap
            return FASTSTART_REWROTE
        # A non-zero returncode raises NOTHING -- it is ffmpeg's ordinary way of refusing a
        # file (a stream anomaly `-c copy` won't carry, say), which is why media_tools hands
        # it back rather than logging it: the message worth printing is this one, naming the
        # clip. This branch used to fall straight through to the cleanup below, so the one
        # genuinely COMMON failure mode was the one that produced no message even under -v --
        # flatly contradicting the comment in the except clause below (M04, 2026-07-27).
        # Report the code and ffmpeg's own reason, since "it didn't work" without either is
        # not something a user can act on.
        why = " ".join((r.stderr or "").split())[:400] or (
            "no stderr; wrote no usable temp file" if r.ok else "no stderr")
        vlog("faststart remux failed for {}: ffmpeg exit {} -- {}".format(
            p.name, r.returncode, why))
    except Exception as e:                          # noqa: BLE001 -- remux must never crash a collect
        # swallowed by design (a failed remux leaves the original playable), but never
        # silently: a lost race or an odd ffmpeg failure must at least show under -v.
        vlog("faststart remux failed for {}: {}".format(p.name, e))
    try:
        if tmp.exists():
            tmp.unlink()   # the temp is unique to THIS call, so this only ever cleans our own leftover
    except OSError:
        pass
    if not p.exists():
        # The SOURCE went away while ffmpeg was reading it -- a Trash purge from the gallery,
        # or an --organize move, both of which the docs say may run alongside this. ffmpeg
        # failing to open a file that no longer exists is not a refusal, and reporting it as
        # one names a file the user cannot go and look at. Checked here rather than up front
        # because this is the only window the earlier `p.exists()` cannot cover.
        return FASTSTART_NOT_NEEDED
    return FASTSTART_REFUSED


def video_faststart(path):
    """Losslessly move an mp4's `moov` atom to the front (ffmpeg -c copy -movflags
    +faststart) so iOS/Safari will play it over HTTP -- PixAI serves videos with moov at
    the END, which desktop tolerates but iOS refuses (MediaError 4). No re-encode, no
    quality loss. Returns True only when it rewrote the file; no-op (False) if ffmpeg is
    absent, the file is already faststart, or the remux fails (original left untouched).

    A caller that has to tell a refusal apart from a no-op wants `_video_faststart_attempt`,
    which this wraps -- False here is deliberately the union of both, and the collect-time
    callers (which just want the file made streamable if it can be) do not care which.

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
    return _video_faststart_attempt(path) == FASTSTART_REWROTE


def run_faststart_videos(args):
    """Rewrite every non-faststart mp4 under videos/ so iOS can stream them (lossless
    -c copy +faststart). Idempotent -- skips files already faststart. Touches only the
    video files, never the catalog. Fixes the 'plays on desktop, error 4 on iPhone' bug
    for the existing library; new videos are faststarted at collect time automatically.

    Every video lands in exactly ONE of fixed / skipped / failed, and each failure is named.
    A clip video_faststart refused used to land in NONE of them, so the summary quietly read
    fixed+skipped < total -- and the user, who ran this command precisely because a video
    would not play on their phone, had no way to tell which file was still broken, or even
    that any still was (M04, 2026-07-27).

    'failed' means ffmpeg was asked and could not: nothing else. The first version of this
    accounting asked `_mp4_is_faststart` itself and then treated a False from video_faststart
    as a refusal -- but video_faststart re-asks the same question, and wiki/Backing-Up.md
    blesses running this sweep while the gallery or a live watch is collecting, so the live
    mirror remuxing that clip (or a Trash purge removing it) in between the two checks made
    the sweep print 'FAILED <name> -- still not iOS-playable' about a file that had just been
    FIXED. One question, asked once, by `_video_faststart_attempt`: whatever it says the
    outcome is, is the outcome. A clip someone else repaired BEFORE this sweep reached it
    counts as already-OK; one repaired AFTER we looked gets a harmless second remux and
    counts as rewritten. Neither is a failure, and that is the whole point."""
    out = Path(args.out)
    vdir = out / "videos"
    vids = sorted(p for p in vdir.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".m4v")) if vdir.exists() else []
    if not ffmpeg_path():
        print("ffmpeg not found on PATH; cannot faststart.")
        return {"fixed": 0, "skipped": 0, "failed": 0, "total": len(vids)}
    print("Faststart pass over {} video(s) in {}...".format(len(vids), vdir), flush=True)
    fixed = skipped = 0
    failures = []
    for i, p in enumerate(vids, 1):
        outcome = _video_faststart_attempt(p)
        if outcome == FASTSTART_REWROTE:
            fixed += 1
            print("  [{}/{}] faststart -> {}".format(i, len(vids), p.name), flush=True)
        elif outcome == FASTSTART_REFUSED:
            failures.append(p)
            print("  [{}/{}] FAILED {} -- still not iOS-playable (re-run with -v for "
                  "ffmpeg's own reason)".format(i, len(vids), p.name), flush=True)
        else:
            skipped += 1
    print("Done: {} rewritten, {} already OK, {} failed ({} total).".format(
        fixed, skipped, len(failures), len(vids)))
    for p in failures:
        print("  still not faststart: {}".format(p))
    return {"fixed": fixed, "skipped": skipped, "failed": len(failures),
            "total": len(vids)}


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
    import shutil
    from moonglade_gallery import make_thumbnail
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # import can seed a fresh, download-free backup
    thumb_dir = out / "gallery" / "thumbs"

    raw = getattr(args, "import_local", None)
    src = Path(raw) if raw else out
    if not src.exists():
        raise PixAIError("import path not found: {}".format(src))
    try:
        _s, _o = src.resolve(), out.resolve()
        external = not _under(_s, _o) and _s != _o
        scan_root_is_out = (_s == _o)
    except OSError:
        external = False
        scan_root_is_out = (src == out)

    _prog = getattr(args, "progress", None)
    catalog_rows = load_catalog(db_path)
    existing = {(r.get("filename") or "").replace("\\", "/")
                for r in catalog_rows if r.get("filename")}
    # Also key on media_id: an already-backed-up PixAI file is named after its
    # media id, so media_id_of() of an organized file matches an existing row even
    # though its on-disk path no longer equals the stored `filename` string. This
    # is what stops --import-local from re-cataloging the whole backup as 'local'.
    existing_mids = {r.get("media_id") for r in catalog_rows if r.get("media_id")}
    # The same snapshot as a media_id -> row map, for build_catalog_row's carry. Free
    # (catalog_rows is already in hand). Belt-and-braces here rather than load-bearing:
    # the two guards above mean an already-cataloged file is skipped before it ever
    # reaches the builder, so there is nothing to carry -- but the guarantee lives in
    # the builder for every path, not in each caller's memory.
    known = {r["media_id"]: r for r in catalog_rows if r.get("media_id")}

    # IMPORT_EXCLUDE = the shared quarantine set plus legacy branding/ (named
    # disagreement 5) -- app chrome that must never be catalogued as gallery
    # content, and, for _deleted/, B11 (audit 2026-07-21): purge_media_local()
    # clears a purged image's catalog row when it moves the file there, so without
    # the exclusion the scan finds an orphaned file with no existing row/media_id
    # match and resurrects it as a brand-new source='local' row.
    #
    # Those names only mean anything relative to the backup root, so they apply
    # exactly when the scan root IS the backup root. An external source folder --
    # or a subfolder of the backup handed in explicitly -- excludes nothing, which
    # is what the old `if not external and _under(p, out / "gallery")` chain
    # amounted to: it tested paths rooted at `out`, which could not match anything
    # under a different root.
    excl = IMPORT_EXCLUDE if scan_root_is_out else ()

    print("Scanning {} for media (this can take a moment on a large backup)...".format(src),
          flush=True)
    candidates = []
    for e in scan_library(src, kinds=("image", "video"), exclude=excl):
        candidates.append(e.path)
        if len(candidates) % 5000 == 0:
            vlog("scanned {} media files so far...".format(len(candidates)))
    total = len(candidates)
    print("Found {} media file(s); cataloging new ones...".format(total), flush=True)

    rows, made, skipped = [], 0, 0
    for idx, p in enumerate(candidates):
        if _prog:
            _prog(idx + 1, total, 0)
        is_vid = p.suffix.lower() in _VIDEO_EXTS
        if external:
            dest_dir = out / ("videos" if is_vid else "imported")
            dest_dir.mkdir(parents=True, exist_ok=True)
            mid = local_media_id(p)
            if not mid:
                skipped += 1              # unreadable source; nothing to copy or key on
                continue
            # Decided BEFORE the copy, not after: the id comes from the source's own
            # bytes, so content already in the library can be recognised without
            # writing anything. Copying first and skipping later left the file sitting
            # in imported/ with no row pointing at it.
            if mid in existing_mids:
                skipped += 1
                continue
            # The stored name ends in the CONTENT hash, so a destination that already
            # exists holds the same bytes -- there is nothing to overwrite and nothing
            # to lose. Naming by basename alone silently threw away the second of two
            # different files that happened to share a name (image.png / 00001.png out
            # of separate folders is ordinary, not a corner case) while still counting
            # it as imported, so the loss only surfaced once the original was gone.
            dest = dest_dir / build_local_name(p, mid)
            if not dest.exists():
                shutil.copy2(p, dest)
            stored = dest
        else:
            stored = p
            mid = local_media_id(stored)
            if not mid:
                skipped += 1
                continue
        rel = str(stored.relative_to(out)).replace("\\", "/")
        if rel in existing or mid in existing_mids or media_id_of(stored) in existing_mids:
            skipped += 1                  # already cataloged (by path, content, or PixAI id)
            continue
        existing_mids.add(mid)            # two sources, one content: catalog it once
        try:
            # UTC + Z, matching the PixAI-sourced rows' `createdAt` format below --
            # `created_at` is sorted as a plain string (_SORT_SQL has no datetime()
            # wrapping), so a naive LOCAL-time stamp here reads as hours "older" than
            # a same-moment UTC one west of Greenwich, silently outranked by anything
            # PixAI collected since (a local save at 23:0X PDT sorted behind rows
            # timestamped 06:05 UTC the "next" day, an hour earlier in real time).
            created = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(stored.stat().st_mtime))
        except OSError:
            created = ""
        rows.append(build_catalog_row(
            mid, known=known, filename=rel, source="local",
            status="imported", created_at=created,
            prompt_preview=stored.stem[:100],       # no prompt: name the file after itself
            is_video="1" if is_vid else ""))        # no fm: a local file has no task
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
    # Anything imported before content-addressing came in still carries its original
    # basename and a path-derived id. Bring those onto the same scheme here rather
    # than leaving the library split across two conventions.
    migrated, mig_skipped = migrate_local_filenames(out, db_path, thumb_dir)
    if migrated or mig_skipped:
        print("Renamed {} earlier import(s) to the current naming{}.".format(
            migrated,
            "; {} left alone (locked or already present)".format(mig_skipped)
            if mig_skipped else ""))
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
# What an upscale runs on when nothing better is known. PixAI's own upscale dialog has NO
# model control at all: their submit spreads the enlarge/upscale params and then sets a
# FIXED modelId, pulling prompts/width/height off the source's original task. So a model is
# not something the user is meant to choose here, and demanding one turned an image whose
# model the catalog never recorded -- every locally imported file, and anything predating a
# full meta sweep -- into an upscale that could not be started at all.
#
# It is a model VERSION id, not a model id. A submit's `modelId` is a version id throughout
# (see _gen_parameters and queue_wait_estimate), and this value was read straight out of
# their submit builder, so it must be handed to the web routes as `version_id` -- passing it
# as `model_id` sends it into the model->versions lookup, which finds nothing and answers
# "pick a model first".
#
# Used only as the fallback: when the catalog DOES know what made the picture, that model is
# still the better answer, because Hires re-diffuses and the original keeps the style.
UPSCALE_FALLBACK_VERSION_ID = "1861558740588989558"
# Captured from a completed Hires job; their dialog hints strength works best 0.4-0.6.
DEFAULT_UPSCALE_DENOISING_STRENGTH = 0.6
# The live Hires dialog's default Denoising Steps is 20 (was 26 in our code; re-verified
# against the new-gen platform, probe 2026-08-25 / scope 2026-08-26).
DEFAULT_UPSCALE_DENOISING_STEPS = 20
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


# PixAI's generation priority channels, read off their own bundle:
#   {default: 1000, turboMode: 500, low: 0}   (an XHigh 1500 exists; not exposed here)
#
# The names matter and are NOT in speed order. 500 is **TurboMode -- members only, no
# extra cost**, not the cheap standard tier it was taken for; 1000 is High Priority,
# which anyone may use and which costs EXTRA. This app defaulted every submit to 500,
# so every generation asked for a members-only channel. That is invisible while the
# membership is live -- it just runs fast and free -- and the day it lapses PixAI starts
# refusing with "Only member can use turbo mode" (REQUIRE_MEMBERSHIP, 403), on paths
# that had worked for months.
#
# PixAI's own client never hits that, because it normalises before submitting: a member
# asking for Low is upgraded to Turbo, and a NON-member asking for Turbo is downgraded to
# Low. Nothing here can read entitlement without an extra round trip per submit, so
# submit_generation does the same correction from the other end -- see it for why acting
# on the rejection is safe.
PRIORITY_LOW = 0          # standard speed, no extra cost, anyone
PRIORITY_TURBO = 500      # ~7.6x faster, no extra cost -- MEMBERS ONLY
PRIORITY_HIGH = 1000      # ~10x faster, costs extra credits, anyone
PRIORITY_XHIGH = 1500     # in their enum; this app never sends it
PRIORITY_CHOICES = (PRIORITY_LOW, PRIORITY_TURBO, PRIORITY_HIGH, PRIORITY_XHIGH)

# Flipped the first time PixAI refuses Turbo for want of a membership. Process-scoped on
# purpose: it stops the SECOND and every later submit paying a wasted round trip, without
# caching an entitlement across runs that the owner may renew at any moment.
_turbo_refused = {"seen": False}


def _coerce_priority(value):
    """A submitted priority, defaulting to Turbo. Accepts 0 (Low) properly, which a
    truthiness fallback cannot."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return PRIORITY_TURBO
    return v if v in PRIORITY_CHOICES else PRIORITY_TURBO


def priority_for_submit(params):
    """Downgrade a Turbo request to Low once PixAI has told us this account can't use it.

    Mirrors the downgrade half of PixAI's own normaliser. Returns the params unchanged
    when there is nothing to correct."""
    if _turbo_refused["seen"] and params.get("priority") == PRIORITY_TURBO:
        params = dict(params)
        params["priority"] = PRIORITY_LOW
    return params


def _is_turbo_refusal(err):
    """True for PixAI's members-only refusal of the Turbo channel -- matched on the
    stable parts (its REQUIRE_MEMBERSHIP code, its numeric code, or the message) rather
    than on one exact string."""
    s = str(err)
    return ("REQUIRE_MEMBERSHIP" in s or "40300047" in s
            or ("turbo" in s.lower() and "member" in s.lower()))


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
        # See PRIORITY_* -- 500 is TURBO (members only), not "standard". `or` is wrong
        # here: PRIORITY_LOW is 0, and `0 or X` is X, which would quietly re-upgrade a
        # deliberate Low back to Turbo.
        "priority": _coerce_priority(getattr(args, "priority", None)),
    }
    # Quality mode (inferenceProfile) is MODEL-TYPE-SPECIFIC: SD_V1_MODEL accepts
    # lite/standard but rejects pro/ultra (those are for newer model types). So we
    # only send it when explicitly chosen; "auto"/"" omits it and lets PixAI pick
    # the model's default. Safe for VALIDITY (the original working behavior) --
    # NOT a general promise about PRICE: on the video path the omitted default is
    # the ~3x-expensive one (issue #6, build_video_parameters' mode guard). If a
    # price probe ever shows inferenceProfile behaving the same way, stop
    # omitting here too.
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
    # A fired ceiling clamp is RECORDED, not applied in silence -- same contract as the
    # width/height/steps/cfg/count clamps (see _gen_args_from_web_payload's `adjusted`
    # receipt). The web namespace carries that list on `.clamped`; the CLI's argparse
    # Namespace has no such attribute, so the append is guarded by getattr. The clamp
    # VALUE is unchanged -- only the receipt entry is new.
    def _note_upscale_clamp(field, asked, used):
        receipt = getattr(args, "clamped", None)
        if isinstance(receipt, list):
            receipt.append({"field": field, "asked": asked, "used": used})
    if enlarge:
        _ceil = max_upscale_ratio(params["width"], params["height"], "enlarge")
        if _ceil < enlarge:
            _note_upscale_clamp("enlarge", enlarge, _ceil)
        enlarge = min(enlarge, _ceil)
    elif upscale:
        _ceil = max_upscale_ratio(params["width"], params["height"], "upscale")
        if _ceil < upscale:
            _note_upscale_clamp("upscale", upscale, _ceil)
        upscale = min(upscale, _ceil)
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
    # Quality Tag is MEMBERS-ONLY on PixAI -- crowned in their Add Booster menu on every
    # model, and their own guide says "member-only" in writing. This app was never built to
    # get around their systems (owner, 2026-07-28), so an account PixAI reports as
    # non-member does not send the gated parameter. `is_member` is True/False/None from
    # core.account_is_member(); only an explicit False gates, so an unreadable account still
    # submits exactly as before.
    if qtag and getattr(args, "is_member", None) is False:
        qtag = ""
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
VIDEO_CHANNELS = ("private", "normal")   # private = the site's "Private" channel (was "Enhanced" until 2026-08-18)


def build_video_parameters(prompt, media_id, model=DEFAULT_VIDEO_MODEL, *,
                           tail_media_id="", duration=5, mode="professional",
                           generate_audio=False, audio_language="english",
                           negative="", use_prompt_helper=False, kaisuuken_id="",
                           camera_movement="", model_id="", is_private=False):
    """Build createGenerationTask's `parameters` for an image-to-video (i2vPro) job.

    VERIFIED against a real card-covered submit (2026-07-06 via --dump-params): the shape
    is a top-level `modelId` + the `i2vPro` block + privacy/preview flags. Their site
    sends a top-level `channel` (observed value "private", task dump 2026-07-26); we send
    the equivalent as `isPrivate`. Also unsent by us: width/height and a lora object,
    both present in their submit. PROBED 2026-08-22 (17 i2v tasks, 6 models, read-only):
    all three are inert. `width`/`height` is PixAI echoing the SOURCE FRAME's dimensions
    onto the task (3/3 exact match; present on our own tasks though we never send it),
    and cost keys on model + duration, never resolution. `channel` is the same switch as
    `isPrivate`, relabelled. `lora` is always {} for video. Nothing to add.
    (moonglade-internal/probes/PROBE_2026-08-22_r2v-refs-and-video-fields.md)
    `media_id` = source/first frame; `tail_media_id` (optional) =
    last frame for FLF interpolation.

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
    # NEVER let `mode` ride absent/empty on this spend path (issue #6): read-only
    # price probes on one real shot measured professional 18,000 / basic 14,000 /
    # OMITTED 50,000 -- PixAI's own default is the expensive one, so "omit it and
    # let the server pick" is ~3x the money. Every caller today passes a real
    # value; this guard is for the next caller, and it fails LOUDLY at build time
    # (previews run this builder long before any --confirm can spend).
    if mode not in ("basic", "professional"):
        raise ValueError("i2vPro.mode must be 'basic' or 'professional', got %r -- "
                         "omitting it triples the price (issue #6)" % (mode,))
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
        # The new platform (2026-08-25) moved the visibility switch to a top-level string
        # enum `channel: "normal"|"private"`, replacing the old boolean `isPrivate`. Send
        # BOTH: the server honors whichever it reads, so emitting the legacy field too can't
        # regress privacy while the new field carries the switch forward.
        "channel": "private" if is_private else "normal",
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
        "inputVideoDurations": [],
        "referenceAudioMediaIds": [str(m) for m in (audio_media_ids or [])],
        "referenceImageMediaIds": [str(m) for m in (image_media_ids or [])],
        "referenceVideoMediaIds": [str(m) for m in (video_media_ids or [])],
    }
    # Audio only for models that take it -- the SAME table the i2v builder gates on, see
    # VIDEO_AUDIO_MODELS. Sending these to a model without audio support comes back as
    # "This image contains sensitive or NSFW content": a CONTENT complaint for an
    # unsupported flag, which points the investigation at moderation instead of the shape.
    if str(model).strip() in VIDEO_AUDIO_MODELS:
        rv["generateAudio"] = bool(generate_audio)
        rv["audioLanguage"] = audio_language
    params = {
        "priority": int(priority),
        "referenceVideo": rv,
        # New platform: top-level `channel` string replaces the boolean `isPrivate`; send
        # both (server honors whichever) so privacy can't regress. Same switch as i2vPro.
        "channel": "private" if is_private else "normal",
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
                            quality="professional", negative="", is_private=False,
                            use_prompt_helper=False):
    """PixAI video PROVIDER ADAPTER: map a Loom shot (mode + prompt + @-ordered ref
    media_ids) to createGenerationTask video params. This is the SEAM a future Seedance/
    other provider mirrors -- same shot spec in, provider-native params out. I2V/FLF ->
    i2vPro; R2V/V2V/any-with-refs -> referenceVideo. Duration snaps to PixAI's allowed
    lengths. (Card auto-apply happens at the route: a V4.0 card makes it free.)

    `negative` only reaches i2vPro (I2V/FLF) -- the referenceVideo submit shape captured
    2026-07-02 has no negativePrompts field at all. A genuine PixAI API gap, not an
    oversight here -- R2V/V2V shots silently ignore a negative prompt if one is set.
    `use_prompt_helper` (the Generate dock's 'Video prompt helper' switch, off by default)
    likewise only reaches i2vPro.usePromptsHelper -- referenceVideo has no such field."""
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
                                      negative=negative, is_private=is_private,
                                      use_prompt_helper=bool(use_prompt_helper))
    if m == "FLF" and len(imgs) >= 2:
        return build_video_parameters(prompt, imgs[0], model=mdl, tail_media_id=imgs[1],
                                      duration=dur, mode=qual, generate_audio=generate_audio,
                                      audio_language=audio_language,
                                      camera_movement=camera_movement, model_id=mid_num,
                                      negative=negative, is_private=is_private,
                                      use_prompt_helper=bool(use_prompt_helper))
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


def build_panelplugin_parameters(media_id, workflow_id="", *, workflow_name="",
                                 strength=None, extra_inputs=None, priority=1000,
                                 is_private=False, kaisuuken_id=""):
    """Enhance via a PixAI panelplugin WORKFLOW (face-fix / bg-remove / handfix / lineart ...).
    VERIFIED shape (2026-07-02): model 'pixai-panelplugin', `inputs.image = {type:'media',
    media_id}` (+ optional strength / per-plugin args). A workflow is addressed by either a
    numeric `workflowId` (VERIFIED path) OR a `workflowName` like 'mymusise/hand-fix' (mined
    from the app). Produces an image output. Builder spends nothing.

    Restored 2026-08-18 for the Bridge tier (drift §44 / SCOPE §3). The 2026-07-24 deletion
    was correct about the API KEY -- PixAI reaps an API-key panelplugin submit unstarted at
    ~60 min -- but overshot to "impossible". A panelplugin task submitted on the BROWSER JWT
    (the mirror) dispatches in seconds. So the ONLY safe caller is one gated on an armed
    mirror: /api/enhance refuses unless make_mirror_session() is live, and submit_generation
    routes the create through _session_for_create onto that JWT. This builder itself is
    credential-agnostic; the gate lives at the route."""
    inputs = {"image": {"type": "media", "media_id": str(media_id)}}
    if strength is not None:
        inputs["strength"] = float(strength)
    if extra_inputs:
        inputs.update(extra_inputs)
    params = {
        "priority": int(priority),
        "model": "pixai-panelplugin",
        "inputs": inputs,
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
    }
    if workflow_name:
        params["workflowName"] = str(workflow_name)
    elif workflow_id:
        params["workflowId"] = str(workflow_id)
    else:
        raise PixAIError("panelplugin needs a workflow_id or workflow_name")
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)
    return params


# The six mirror-gated Bridge Enhance presets (the DC set, drift §44), each PINNED to its
# addressing. This is the canonical record because Branch C is confirmed: the live `workflows`
# GraphQL connection returns ZERO entries on our credential (probed 2026-08-16/17), so the DC's
# "self-populates from workflow_catalog" cannot happen -- the presets are hardcoded, not
# discovered. Each is addressed by a workflow_name = "<author/workflow>:<version>", passed
# straight to build_panelplugin_parameters via /api/enhance.
#
# ADDRESSES ARE AUTHORITATIVE + DISPATCH-PROVEN (2026-08-18). All six were pulled from PixAI's
# live public config -- GET https://api.pixai.art/config/constants -> imageEnhancementPlugins,
# which gives {workflowName, workflowVersion, args} per plugin -- then each was submitted FOR
# REAL through the mirror JWT and confirmed to DISPATCH and complete (startedAt set, status
# completed). This replaced four rotted guesses that /v2/task-price had falsely blessed:
#   * handfix / face -- the bare names ("mymusise/hand-fix", "kyo/face-detailer") 404'd at
#     createGenerationTask ("No workflow matched by the name"). The real addresses carry the
#     :version suffix the config supplies (:v1, :v4.0).
#   * line_art / sketch_color -- the old numeric workflow_ids (1796.../1793..., recovered from
#     the b93ce1e enh-card onclicks) were ACCEPTED and CHARGED but never dispatched -- no worker
#     picked them up, reaped unstarted at ~60min (the owner hit this live on line_art). The real
#     workflows are name-addressed: pixai-official/image-to-lineart, .../sketch-coloring-workflow.
#   * bg_remove / emotion were already dispatch-proven earlier and kept as-is.
# LESSON (why the earlier "task-price de-risked it" note was wrong): /v2/task-price validates the
# request SHAPE and prices it, NOT that a live worker exists for the workflow -- it quoted all six,
# including the four dead ones. Only a real JWT submit proves dispatch. See memory
# bridge-enhance-presets-rotted. `args` (per-plugin defaults like handfix strength / a face-detailer
# prompt / the emotion radios) are applied server-side when omitted -- a bare name:version submits.
BRIDGE_ENHANCE_PRESETS = (
    {"key": "handfix",     "label": "Handfix",           "workflow_name": "mymusise/hand-fix:v1"},
    {"key": "face",        "label": "Face Enhance",      "workflow_name": "kyo/face-detailer:v4.0"},
    {"key": "emotion",     "label": "Change Emotion",    "workflow_name": "kyo/emotionlab:633acbbb",
     "has_control": True},
    {"key": "bg_remove",   "label": "Background Remover", "workflow_name": "mymusise/39a2c67c:unet-0.1.3.2"},
    {"key": "line_art",    "label": "Convert to Line Art",
     "workflow_name": "pixai-official/image-to-lineart:0a59dd67"},
    {"key": "sketch_color", "label": "Sketch Coloring",
     "workflow_name": "pixai-official/sketch-coloring-workflow:d40e38f8"},
)

# Change Emotion is the one preset with a control (has_control): the user picks a target
# expression. The workflow_name is derived from the preset row so it can't drift.
ENHANCE_EMOTION_WORKFLOW = next(
    p["workflow_name"] for p in BRIDGE_ENHANCE_PRESETS if p["key"] == "emotion")
# The panelplugin input key emotionlab reads the chosen expression from is `prompt`, and the
# value is a danbooru TAG STRING (NOT the option key). DISPATCH-PROVEN 2026-08-20 against three
# completed website submits recovered via getTaskById (--dump-params): the real submit is
#   inputs.prompt = "<tag string>"   e.g. Upset -> "sad, crying", Aroused -> "sexy, steam,
#   half-closed eyes, torogao, heavy breathing"   addressed by workflowName kyo/emotionlab:633acbbb.
# The prior `inputs.emotion = <filename stem>` wiring was wrong on all three axes (arg name, value,
# AND a versionless workflow address) -- which is why every earlier API attempt charged 2000
# credits and never applied an expression (the "dispatch-verify" note it was built on read a FAILED
# job's acceptance as proof). Source of truth for the option->tag map and the workflow version is
# PixAI's PUBLIC config: GET https://api.pixai.art/config/constants -> imageEnhancementPlugins ->
# emotion (workflowName/workflowVersion, and args.prompt.options[].value keyed by the
# options.<key> i18n label path). Re-pull that endpoint to refresh if PixAI edits the set.
ENHANCE_EMOTION_ARG = "prompt"

# option key (the staged branding/bridge/emotion/<key> filename stem, i.e. the value the picker
# sends up) -> the danbooru tag string emotionlab's `prompt` arg expects. Captured verbatim from
# config/constants imageEnhancementPlugins.emotion (2026-08-20). An unknown key falls back to
# itself at the route, so a custom-staged expression still submits *something* rather than erroring.
ENHANCE_EMOTION_PROMPTS = {
    "happy": "smile",
    "upset": "sad, crying",
    "mad": "angry, annoyed, angry symbol",
    "smug": "smug, laughing, smirk, grin",
    "laughing": "closed eyes, laughing, open mouth",
    "playful": ";d, open mouth",
    "sassy": ":q",
    "sympathy": "sad smile",
    "cute": ":3",
    "moved": "smile crying",
    "afraid": "constricted pupils, scared, trembling, open mouth, wavy mouth, tearing up",
    "shocked": "surprised, :o, \U0001f626, constricted pupils",
    "pumped": "excited, happy, :d, sparkling eyes",
    "awkward": "nervous, sweat, v-shaped eyebrows, frown, open mouth, wavy mouth",
    "confused": "@ @, trembling, confused, misunderstanding, puzzle",
    "nervous": "full-face blush, looking to the side, sideways glance, half-closed eyes",
    "sickened": "grimace, gloom (expression), embarrassed, dark persona, jitome",
    "speechless": "depressed, sanpaku, jitome, looking to the side, sideways glance, ",
    "annoyed": "scowl, >:(, v-shaped eyebrows",
    "aroused": "sexy, steam, half-closed eyes, torogao, heavy breathing",
    "shy": "open mouth, wavy mouth, full-face blush, v-shaped eyebrows",
    "affection": "heart-shaped eyes, smile",
    "focused": "v-shaped eyebrows, frown, looking to the side, sideways glance, half-closed eyes",
    "naughty": "fang, tongue out, half-closed eyes",
    "amazed": "+ +, open mouth, mouth drool",
    "stunned": "wide-eyed",
    "aggrieved": ">_<",
    "doubt": ";o",
    "pouting": ":t [ :T ]",
    "glasgow-smile": "glasgow smile",
    "mania": "crazy smile",
    "impatience": "rolling eyes",
    "nosebleed": "nosebleed",
    "scowl": "grimace",
    "blush-stickers": "blush stickers",
}

# The 25 (of 35) emotions PixAI marks membership-gated (config/constants -> ...emotion.args.prompt
# .options[].membership == True); the other 10 are free. A gated pick on a non-member account is
# REJECTED by PixAI -- but a rejected panelplugin job refunds its credits at the ~60-min reap, so
# this is a picker HINT (badge the tile), not a submit block. The owner's account carries a
# membership, so all 35 dispatch for them; the flag exists so the surface stays honest if that lapses.
ENHANCE_EMOTION_MEMBERSHIP = frozenset({
    "afraid", "shocked", "pumped", "awkward",
    "confused", "nervous", "sickened", "speechless",
    "annoyed", "aroused", "shy", "affection",
    "focused", "naughty", "amazed", "stunned",
    "aggrieved", "doubt", "pouting", "glasgow-smile",
    "mania", "impatience", "nosebleed", "scowl",
    "blush-stickers",
})


# The CLI --enhance command stays gone -- both halves of it. Only the WEB /api/enhance route
# is restored (mirror-gated), never the CLI flag or run_enhance; see build_panelplugin_parameters
# above for the reversal, and tests/test_enhance.py for the guards.
#
# The panelplugin half's CLI entry (--workflow-id and run_enhance): NOT restored. The Bridge is
# web-only -- its mirror gate is a route concern, and a bare CLI --workflow-id could submit a
# panelplugin task on the API key (the reaped-at-60-min bug). tests/test_enhance.py keeps the
# flag unparseable.
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
# Guarded by tests/test_enhance.py, which drives the parser to prove the --filter-id flag is
# unaccepted and greps for the two literals a FILTER submit could not do without -- the filter
# model's id and the filter-inputs key. Neither exact string appears above on purpose: the
# CONCEPT is named in prose so the strings themselves stay a reliable tripwire. (The panelplugin
# model literal and its workflow-id key DO appear now, in the restored, mirror-gated builder
# above -- test_enhance.py asserts their PRESENCE, not their absence.)


# The Bridge §4/§5 -- "AI Tools" = PixAI "chat editing scenes". A DIFFERENT surface from the
# panelplugin Enhance presets above: browse via listChatEditingScenes (read-only), generate via
# createChatEditingSceneTask (mutation). Captured + dispatch-proven live 2026-08-18 -- all 28
# scenes run on the mirror JWT. Browse UI: AiToolsModal.jsx; generate UI: the gen drawer's scene
# generator (§5). The submit shape was read from PixAI's own /ai-tools/<slug> page:
#   CreateChatEditingSceneTaskInput = {sceneId, mediaIds[], preset ("random" | <preset key> |
#     "custom"), custom?, selectorValues:[{id, value}]}
# with a client-side guard mediaIds.length >= (refImages.minCount or 1) -- every scene transforms
# at least one source image; dual-character needs exactly two. Like the panelplugin Enhance path,
# this is web-only: a scene task submitted on the API key is accepted, CHARGED, then reaped
# unstarted at ~60min -- it must ride the browser JWT, so the /api/scene route mirror-gates it
# and passes make_mirror_session() straight in (no _session_for_create -- that helper is for the
# createGenerationTask path; scenes always use the JWT session the caller hands them).
_SCENE_LIST_Q = """query listChatEditingScenes {
  chatEditingScenes {
    sceneId modelId title name description tutorial tags
    presets { name key i18nKey }
    custom { label description placeholder }
    images { background demo }
    permission { membershipTier }
    refImages { minCount maxCount slotLabels presetMediaIds }
    selectors { id label options { key label icon } defaultKey }
    overrideParameters
  }
}"""
_SCENE_SUBMIT_M = ("mutation createChatEditingSceneTask($input: CreateChatEditingSceneTaskInput!)"
                   " { createChatEditingSceneTask(input: $input) { id } }")


def chat_editing_scenes(session):
    """List PixAI's AI-Tools 'chat editing scenes' -- the browse half of the Bridge AI-Tools
    tier. Read-only: returns the raw scene configs (each carries sceneId, modelId, presets,
    selectors, custom, refImages, permission.membershipTier). The gen drawer reads each scene's
    control schema from here to render its form. Runs on the mirror JWT (a website surface);
    pass make_mirror_session()."""
    d = gql_adhoc(session, _SCENE_LIST_Q, {}) or {}
    return d.get("chatEditingScenes") or []


def submit_scene(session, scene_id, media_ids, preset="random", custom=None, selector_values=None):
    """Submit a chat-editing scene task (createChatEditingSceneTask) -> task id. The generate
    half of the Bridge AI-Tools tier. SPENDS, so it goes through gql_mutate (SINGLE attempt, no
    retry -- a re-POST after a lost response pays twice) and MUST run on the mirror JWT; the
    caller passes _check_read_only first at the route choke, exactly like /api/enhance ->
    submit_generation. `preset` is a preset key, "random", or "custom" (with `custom` text);
    `selector_values` is [{id, value}] for the scene's selectors (e.g. aspect-ratio)."""
    _check_read_only("submit chat-editing scene")
    inp = {"sceneId": str(scene_id),
           "mediaIds": [str(m) for m in (media_ids or []) if m],
           "preset": str(preset or "random")}
    if custom is not None and str(custom).strip():
        inp["custom"] = str(custom)
    if selector_values:
        inp["selectorValues"] = [{"id": str(s["id"]), "value": s["value"]}
                                 for s in selector_values if s.get("id")]
    d = gql_mutate(session, _SCENE_SUBMIT_M, {"input": inp})
    return ((d or {}).get("createChatEditingSceneTask") or {}).get("id")


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
        # _GEN_DONE / _GEN_FAIL are this module's single source of truth for a terminal
        # status -- generation_status() and _outputs_or_raise() already read them. This loop
        # used to carry its own hand-copied tuples, and they had drifted out of step: they
        # were missing 'finished' (a real success) and 'rejected' (a real failure, and named
        # as terminal in EmptyOutputsError's own docstring). A rejected generation is
        # already refunded, but the poller went on waiting for it until the timeout expired
        # and then reported it as still running on PixAI.
        if status in _GEN_DONE:
            if paid_credit is not None:
                print("  actual cost: {:,} credits".format(int(paid_credit)))
            return paid_credit
        if status in _GEN_FAIL:
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
    different text; nothing about the genuinely-empty case changes.

    Issue #8 (2026-08-13) added the third case the same lesson demanded: a task whose
    status is NON-terminal (queued/running) is not missing anything -- it simply hasn't
    produced output YET, and 'no media found' there reads as a lost paid generation and
    sends real debugging effort at a task that is fine. Wait vs. investigate are
    opposite responses; the message now says which one applies."""
    if found:
        return
    raw = str((result or {}).get("status") or "").lower()
    if raw in _GEN_FAIL:
        raise EmptyOutputsError(
            "PixAI reported this task as '{}' -- it did not complete, so there is "
            "nothing to recover. Check pixai.art for why, or resubmit.".format(raw))
    if raw and raw not in _GEN_DONE:
        raise EmptyOutputsError(
            "this task is still '{}' on PixAI -- nothing to collect YET. It hasn't "
            "finished (or failed); try again once it completes.".format(raw))
    raise EmptyOutputsError(empty_message)


def run_generate(args):
    """Create images via PixAI (createGenerationTask), poll to completion, download
    the results into the backup, and catalog them as source='api'. GUARDED: without
    --confirm it only prints a preview (spends no credits). Submits through
    submit_generation() (and so through gql_mutate) + the shared session/download/
    catalog plumbing.

    A task recovered by --task-id that turns out to have VIDEO outputs is collected as
    video, through the same _download_video_task the video commands use -- never dragged
    through the image path. See the comment at the outputs split below for why."""
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
    mids = list(dict.fromkeys(mid for mid, _ in media))
    # outputs.videos USED TO BE APPENDED TO `mids` and walked by the image loop below, which
    # downloaded the mp4 into images/ and wrote it a catalog row off `{f: "" for f in
    # CATALOG_FIELDS}` -- so is_video stayed blank. The gallery lists images with
    # `COALESCE(is_video,'') != '1'`, so the clip was served as an image: an <img> pointed at
    # an mp4 (broken tile), no poster thumbnail, and no faststart remux, none of which the
    # image path knows how to do (M16, 2026-07-27). Reachable simply by handing
    # `--generate --task-id` an i2v or reference-video id -- a mispaste, or a script looping
    # over a mixed list of ids.
    #
    # So videos go to the code that actually handles videos. Collecting rather than refusing
    # is what collect_generation (the /watch and web routes) already does off the same
    # outputs.videos tell, and refusing would strand the outputs of a task the user has
    # ALREADY paid for behind a second command.
    #
    # What is recovered, honestly: the FILE, its is_video flag, its poster and its faststart
    # remux -- always. The prompt/duration/model on the row are best-effort. `params` here is
    # the image-gen submit block, so _download_video_task's `sent` lookup finds neither
    # i2vPro nor referenceVideo in it and falls back to `video_outputs`' shared block -- and
    # that reads `parameters.referenceVideo` ONLY. A reference-video task therefore recovers
    # its prompt and duration; a pure i2v (i2vPro) task lands with those three columns blank
    # and needs a --backfill-full-meta pass to fill them. Blank-but-filed beats an mp4 served
    # through an <img> tag, which is what this branch replaced, but do not read the comment
    # above as a promise that the metadata always survives -- it does not.
    vouts, _vshared = video_outputs(result)
    _outputs_or_raise(result, mids or vouts, "task completed but no media ids found")

    # Prefer the task's actual metadata (authoritative, and the only source when recovering by
    # --task-id); fall back to the params we submitted -- EXCEPT the sampling fields, see below.
    fm = extract_full_meta(result)
    # steps/sampler/cfg_scale follow the MODEL, not the submit. A task that recorded none ran on
    # the model's baked defaults, so the VERSION preset is their truth -- and where the model
    # genuinely has no sampler/CFG (AuraFlow, e.g. Tsubaki.2) the honest answer is a blank, not
    # the samplingSteps/cfgScale we happened to send and the model ignored. So these three read
    # from `fm` below (task-echoed -> preset -> blank) and NEVER fall back to the submitted value
    # (owner ruling 2026-08-15). _fill_preset_defaults populates fm's blanks from the preset; it
    # used to sit here and let the preset preempt _pick's submitted fallback for `steps` only,
    # while `cfg` still leaked the submitted 7.0 -- an inconsistency this removes. Matches
    # _download_image_task, the sibling downloader, which already reads these straight from fm.
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg

    def _pick(fm_key, *param_keys):
        if fm.get(fm_key):
            return str(fm[fm_key])
        for pk in param_keys:
            if params.get(pk):
                return str(params[pk])
        return ""

    img_dir = out / "images"
    rows, saved = [], []
    # The pre-download snapshot build_catalog_row carries forward -- see its step 3 and
    # _download_image_task's fuller note. Recovering a task by --task-id can perfectly
    # well land on media that is already catalogued, rated and published.
    known = known_catalog_rows(db_path, mids)
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
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
            negative_prompt=_pick("negative_prompt", "negativePrompts"),
            seed=seeds.get(mid) or _pick("seed", "seed"),   # per-image seed on a batch
            # Model's truth, not the submit: fm holds task-echoed -> preset -> blank. No
            # _pick here on purpose -- a submitted samplingSteps/cfgScale the model ignored
            # must not stand in for the model's real behavior (owner ruling; see above).
            steps=fm.get("steps", ""),
            cfg_scale=fm.get("cfg_scale", ""),
            model_id=_pick("model_id", "modelId"),
            # Resolved here, not just in the backfill. extract_full_meta only fills
            # model_name for a CHAT task (from the local EDIT_MODELS table); every ordinary
            # generation left it blank, so every freshly captured image showed a raw
            # 19-digit model id on its detail page until a later --backfill-full-meta
            # happened to come past. model_name_gql is process-cached, so this is one call
            # per distinct model for the whole run, not one per image.
            model_name=_resolved_model_name(session, fm, _pick("model_id", "modelId")),
            # Four fields extract_full_meta hands over that this row used to drop, so they
            # arrived blank on every live capture and only appeared once a
            # --backfill-full-meta came past -- which is the manual step the whole
            # capture-it-as-it-happens path exists to remove. `loras` in particular is
            # always "" out of extract_full_meta by design: it documents that the CALLER
            # resolves it, the backfill did, and this did not.
            sampler=fm.get("sampler", ""),
            natural_prompt=fm.get("natural_prompt", ""),
            clip_skip=fm.get("clip_skip", ""),
            loras=_resolved_loras(session, result),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or params.get("width") or ""),
            height=str((info or {}).get("height") or params.get("height") or ""))
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))

    if rows:
        save_catalog(db_path, rows)

    videos = []
    if vouts:
        print("This task has {} VIDEO output(s) -- collecting them as video (videos/, "
              "is_video=1, poster thumbnail, faststart), not as images.".format(len(vouts)))
        if not mids:
            print("  (a video task: `--generate-video --task-id {}` is the direct route)"
                  .format(task_id))
        try:
            videos = _download_video_task(session, result, task_id, out, args, params)
        except Exception as e:                # noqa: BLE001 -- see below; images are already safe
            # FAIL SOFT, like the image loop above. That loop walks past an image it cannot
            # resolve or download with a `continue`; this block had no equivalent, so one
            # media-CDN TLS failure or a dropped connection inside download() -- which
            # answers an SSLError with `raise PixAIError(_ssl_help())` -- escaped through
            # main's handler. The images were already downloaded AND already in the catalog
            # two lines up, but the user got a traceback-shaped exit instead of the summary
            # listing them, and run_generate's return dict never happened (M16, 2026-07-27).
            #
            # Broad on purpose, and safe to be: everything the image half of this command
            # promised is durable before we get here, the clip is still on PixAI (already
            # paid for, recoverable for free), and the message below names the command that
            # fetches it. KeyboardInterrupt is not an Exception, so Ctrl-C still stops the run.
            print("  video collection FAILED ({}) -- {}".format(
                str(e)[:200],
                "the {} image(s) below are saved and cataloged.".format(len(saved))
                if saved else "this task had no image outputs, so nothing was collected."))
            print("  The clip is still on PixAI and costs nothing to re-fetch: "
                  "`--generate-video --task-id {}`".format(task_id))

    # A hidden recovery feat: a stranded task pulled back by id. Counted once per RECOVERY, whatever
    # kind of output it turned out to hold -- this used to live inside `if rows:`, so a
    # video-only task (rows is empty by construction for one) recovered nothing as far as the
    # ledger was concerned, and the achievement that exists to reward exactly that rescue
    # never moved (M16, 2026-07-27).
    if existing_task and (rows or videos):
        try:
            from moonglade_gallery import telem_bump
            telem_bump("recover_events", out_dir=out)
        except Exception:
            pass

    print("Generated + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    if videos:
        print("Generated + cataloged {} video(s):".format(len(videos)))
        for s in videos:
            print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved),
            "videos": len(videos)}


def _download_video_task(session, result, task_id, out, args, params):
    """Download + catalog the video output(s) of a completed task. Shared by i2v (i2vPro)
    and reference-video (referenceVideo) -- reads outputs.videos + the submitted block
    generically. Returns the list of saved file paths."""
    outs, shared = video_outputs(result)
    _outputs_or_raise(result, outs, "video task completed but no video outputs found")
    detail = ((result or {}).get("outputs") or {}).get("detailParameters") or {}
    fm = extract_full_meta(result)   # issue #18: the full generation surface for the video row
    sent = (params.get("i2vPro") or params.get("referenceVideo") or {}) if isinstance(params, dict) else {}
    prompt = shared.get("prompt") or sent.get("prompts") or sent.get("prompt") or ""

    from moonglade_gallery import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    vdir = out / "videos"
    vdir.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    rows, saved = [], []
    # The same pre-download snapshot the image path takes, and for the same reason: the
    # row is rebuilt from a blank template, so without the carry a re-collect blanks the
    # video's rating, collections, title and published state. build_catalog_row applies it.
    known = known_catalog_rows(db_path, [o.get("video_media_id") for o in outs])
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
        full = build_catalog_row(
            vmid, fm=fm, known=known,   # fm: issue #18 (no preset fill: video)
            task_id=str(task_id),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed", is_video="1",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
            negative_prompt=sent.get("negativePrompts", ""),
            seed=str(o.get("seed") or ""),
            poster_media_id=o.get("poster_media_id", ""),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            video_duration=str(shared.get("duration") or sent.get("duration") or ""),
            model_id=str(sent.get("model") or ""),
            width=str(detail.get("width") or ""),
            height=str(detail.get("height") or ""))
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
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    rows, saved = [], []
    # THE PRE-DOWNLOAD SNAPSHOT. Every row below is rebuilt from a blank CATALOG_FIELDS
    # template, which knows only API/file fields -- so upserting it raw BLANKS everything
    # locally owned: artwork_id, is_published, title, rating, collections, art_tags,
    # aes_score, blurhash. Collecting a task a second time therefore erased the work of
    # having published, rated and filed the picture. (Owner, live, 2026-09-03: a published
    # piece lost its artwork_id after a relaunch re-polled a finished task.) Keyed to this
    # task's media only, so it stays a lookup rather than a whole-catalog read.
    # build_catalog_row applies it -- which is what makes this structural rather than
    # something each of the capture paths has to remember (issue #19).
    known = known_catalog_rows(db_path, [m for m, _ in media])
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
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id), seed=seed,
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
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
            model_id=fm.get("model_id", ""),
            model_name=model_name or _resolved_model_name(session, fm,
                                                          fm.get("model_id", "")),
            steps=fm.get("steps", ""),
            sampler=fm.get("sampler", ""),
            cfg_scale=fm.get("cfg_scale", ""),
            negative_prompt=fm.get("negative_prompt", ""),
            natural_prompt=fm.get("natural_prompt", ""),
            clip_skip=fm.get("clip_skip", ""),
            loras=_resolved_loras(session, result),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or ""),
            height=str((info or {}).get("height") or ""))
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


# Per-VERSION inference-profile cache for the submit/price gate below. Keyed by version_id
# ALONE (not the session): /api/price builds a FRESH session per keystroke (gallery
# _gen_session -> _make_session(None)), so an id(session) memo never hit across price calls and
# every keystroke re-fetched /inference-profiles over the network -- the drawer's "price
# reloading" lag (2026-08-26). The profile set is per-VERSION architecture data, identical
# across accounts/sessions, so version-keyed caching is correct and turns the per-keystroke GET
# into one-per-model-per-TTL. Entries carry a monotonic timestamp; the TTL bounds staleness so a
# model whose profiles PixAI later changes is picked up within the hour (a restart clears it
# too). conftest clears it between tests so no model's profiles leak across them.
_PROFILE_CACHE_TTL = 3600.0                  # seconds; inference profiles change very rarely
_profile_cache = {}                          # version_id -> (fetched_at_monotonic, profiles_list)


def _model_profiles(session, version_id):
    """The inference-profile set for a model VERSION, via the VERSION-keyed endpoint
    GET /v2/generation-model/<version_id>/inference-profiles.

    This is the ONLY endpoint the gate consults, and the ONLY one that answers on a submit's
    `modelId` (which is a VERSION id): the model-keyed /versions route 404s on a version id,
    which is why an earlier resolve_version_meta-based gate was inert (adversarial review /
    live GETs, 2026-08-26). The real body is `{"profiles": [...]}` (NOT `data`).

    Returns the list on HTTP 200 -- which may be `[]` (SDXL answers `{"profiles": []}`). This
    distinguishes 'SDXL, definitively no profiles' from 'could not determine': ANY failure
    (exception / non-2xx / a body that is not a dict with a `profiles` list) returns None so
    the gate can fail soft and leave the submit exactly as it is today. Read-only.

    CACHED per version_id across ALL sessions (see _profile_cache) with a TTL, because
    /api/price runs this on every keystroke on a FRESH session (gallery _gen_session) -- a
    session-keyed memo re-hit the network each time. Only a SUCCESSFUL result is cached (None
    is not, so a transient failure re-attempts rather than sticking)."""
    vid = str(version_id)
    now = time.monotonic()
    hit = _profile_cache.get(vid)
    if hit is not None and (now - hit[0]) < _PROFILE_CACHE_TTL:
        return hit[1]
    try:
        data = _rest_get(session, "/generation-model/" + vid + "/inference-profiles")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        return None
    _profile_cache[vid] = (now, profiles)
    return profiles


def _gate_params_for_model(session, params):
    """Gate a plain-image createGenerationTask's field set on the model's ARCHITECTURE, so
    the shape we PRICE and the shape we SUBMIT agree with what the model actually honors
    (PixAI new-gen platform, 2026-08-25). Called from BOTH submit_generation and price_task
    with the IDENTICAL helper, so the cost badge cannot diverge from the real charge.

    The architecture signal is the VERSION-keyed inference-profile set (_model_profiles):
    - NON-EMPTY -> DiT (MMDIT26A/B). The site sends `inferenceProfile` and omits
      `samplingSteps`/`cfgScale`/`samplingMethod`/`clipSkip`. So: ensure a profile is present
      (fill the model's DEFAULT-flagged profile when the user left it on auto -- and if NO row
      is flagged default, leave it ABSENT so the SERVER picks its own default: omitting keeps
      quote == charge, whereas synthesizing a possibly-invalid profile would reintroduce the
      divergence) and drop the four ignored/rejected fields.
    - EMPTY `[]` -> SDXL (a definitive 200). Keep `samplingSteps`/`cfgScale`; ensure
      `inferenceProfile` is NOT present (SDXL rejects pro/ultra -- the drop-and-retry in
      submit_generation was papering over exactly this).

    BEST-EFFORT + FAIL-SOFT: no `modelId`, a non-image submit (video/edit/enhance flow through
    submit_generation too and must pass untouched), or a profile set that cannot be determined
    (None) all return the params UNCHANGED -- a failed lookup never breaks a submit or changes
    its spend outcome versus today. Non-mutating: returns the ORIGINAL object on every no-op
    path (so submit_generation's own in-place inferenceProfile drop-and-retry still mutates the
    caller's dict), and a shallow COPY only when it actually gates. The profile GET is the only
    new network call, and it is read-only."""
    if not params or not params.get("modelId"):
        return params
    # Video (i2vPro/referenceVideo) is the only non-image submit carrying a TOP-LEVEL
    # modelId; instruct-edit (chat.modelId) and enhance (workflowName) have none, so the
    # modelId guard already skips them. Skip video explicitly.
    if "i2vPro" in params or "referenceVideo" in params:
        return params
    try:
        profiles = _model_profiles(session, params["modelId"])
    except Exception:
        return params
    if profiles is None:
        return params                       # couldn't determine -> today's behavior, unchanged
    if profiles:                            # non-empty -> DiT (profile-driven)
        p = dict(params)
        if not p.get("inferenceProfile"):
            default = ""
            for r in profiles:
                if isinstance(r, dict) and r.get("profileFlag") == "default":
                    default = str(r.get("profileName") or "").strip()
                    break
            # A default was flagged -> send it. NONE flagged -> leave inferenceProfile ABSENT
            # so the server applies its own default (quote == charge); never synthesize one.
            if default:
                p["inferenceProfile"] = default
        for k in ("samplingSteps", "cfgScale", "samplingMethod", "clipSkip"):
            p.pop(k, None)
        return p
    # profiles == [] -> SDXL: steps/cfg drive cost; strip a profile the model would reject.
    p = dict(params)
    p.pop("inferenceProfile", None)
    return p


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
    # Mirror routing (review F4/F5): after the READ_ONLY gate, the create rides the browser
    # JWT session when the toggle is on (else this is a pass-through, unchanged). submit_
    # generation is create-only -- it returns the task id and never polls/collects -- so
    # rebinding the whole session here is safe; the CALLER keeps its API-key session for
    # download (F6).
    session = _session_for_create(session)
    # Gate the field set on the model's architecture (DiT profile vs SDXL steps/cfg) BEFORE
    # the mutation, with the SAME helper price_task uses, so the submitted shape equals the
    # priced shape. Fail-soft: an undetermined profile set returns params unchanged (today's
    # behavior).
    params = _gate_params_for_model(session, params)
    params = priority_for_submit(params)   # already known to be turbo-refused? use Low
    try:
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
    except PixAIError as e:
        if "inferenceProfile" in str(e) and "inferenceProfile" in params:
            dropped = params.pop("inferenceProfile")
            print("  mode '{}' not supported by this model; retrying on the "
                  "model's default...".format(dropped))
            created = gql_mutate(session, _GEN_MUTATION, {"parameters": params})
        elif _is_turbo_refusal(e) and params.get("priority") == PRIORITY_TURBO:
            # Turbo (500) is members-only and this app asked for it on EVERY submit, so
            # the day a membership lapses every generate/edit/video/fix/upscale starts
            # failing at once. Safe to re-submit for the same reason the inferenceProfile
            # case above is: PixAI returned a GraphQL error, so the task was rejected --
            # nothing exists and nothing was charged. Falls back to the tier their own
            # client would have picked for a non-member.
            params = dict(params, priority=PRIORITY_LOW)
            _turbo_refused["seen"] = True
            print("  turbo is members-only on this account; resubmitting at standard "
                  "speed (no extra cost).")
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
    # The fixer IS a credit-spending create, so it rides the mirror JWT session when the
    # toggle is on (review F1: the choke belongs at "a create", not only at gql_mutate sites).
    # Create-only -- the caller polls/collects on its own API-key session (F6); pass-through
    # when the mirror is off; refuses before spend if the mirror is on but unavailable (F5).
    data = _rest_post(_session_for_create(session), "/task/fixer",
                      {"mediaId": str(media_id), "boxes": clean}) or {}
    tid = data.get("id")
    if not tid:
        raise PixAIError("fixer: no task id returned: " + json.dumps(data)[:200])
    return str(tid)

# =============================================================================
# ONE PAYLOAD ROAD -- price and submit build the same dict
# =============================================================================
# Every create surface used to reach a PixAI `parameters` dict by a road of its
# own: /api/price through the gallery's `_params_and_nocard`, and each create
# route through its own builder call, its own `_apply_kaisuuken`, its own
# mutation. Two roads to one number is how a cost badge comes to quote a job
# that is not the one about to be paid for -- the hazard already written down at
# /api/generate ("the badge must quote the shape that will actually submit").
#
# The interface is three names, and they sit here, right behind the builders,
# because that is the only place both a quote and a spend can see the same dict:
#
#   build_request(payload, ...) -> GenerationRequest    the ONLY producer
#   price(session, req)  -> dict                        READ-ONLY, spends nothing
#   submit(session, req) -> dict                        the ONE spend choke
#
# `price` and `submit` both read `req.parameters` and neither ever rebuilds it,
# so a quote and a spend inside one request describe the same job by
# construction, not by two pieces of code agreeing. A caller cannot submit a
# shape that was never quotable, because `build_request` is the only place a
# shape comes from and the mode dispatch lives there exactly once.
#
# It is also the one place READ_ONLY and the free card are decided. Before this,
# each web route called `_apply_kaisuuken` (a real network call) and only THEN
# reached `submit_generation`'s READ_ONLY guard -- the same fail-open ordering
# the four CLI runners were fixed for on 2026-07-21, still live on the web side.
# `submit` checks first and matches nothing else.
#
# The CLI runners (`run_generate`, `run_generate_video`, `run_edit_image`, ...)
# deliberately keep their own flow for now: they carry preview/--confirm/--dump-
# params behaviour that is not a web payload's, and folding them in is its own
# increment.


@dataclass
class GenerationRequest:
    """One create request: the exact dict PixAI will receive, plus the few
    route-level facts the payload carries that a submit needs.

    `parameters` is THE object -- price() reads it, submit() sends it, nothing
    rebuilds it in between. `None` means the payload was not enough to build a
    shape, and `note` says what is missing in the cost badge's own voice.

    mode              "image" | "edit" | "fix" | "video" | "enhance"
    parameters        createGenerationTask `parameters`, or None (see `note`)
    no_card           skip the free-card match (forced True for a Fix)
    note              why `parameters` is None -- rendered by the badge
    price_note        set when the shape is REAL but must not be priced: an
                      enhance/panelplugin task is priced by its workflow id,
                      which is deliberately not in _PRICE_SCALARS, so pricing
                      the workflow-less shape that survives the allowlist
                      returns a confident WRONG number. No number is the honest
                      answer until that is measured live.
    media_id / boxes  the Fix's own submit body: POST /v2/task/fixer takes
                      {mediaId, boxes} and never sees `parameters` (those are
                      the synthesized chat.fixer shape, built for pricing only).
    model_version_id  the RESOLVED model version an image gen will submit --
                      the one fact a route needs to tell "no model picked" from
                      "the builder refused something".
    lora_version_ids  the LoRAs actually going out, for the per-account cap and
                      the LoRA telemetry.
    adjusted          the clamp receipt: [{field, asked, used}] for every clamp
                      that FIRED. Clamping is substitution on a paid path, so
                      the route hands it back in the response rather than
                      charging for a different generation in silence.
    """
    mode: str = "image"
    parameters: dict = None
    no_card: bool = False
    note: str = None
    price_note: str = None
    media_id: str = ""
    boxes: list = field(default_factory=list)
    model_version_id: str = ""
    lora_version_ids: list = field(default_factory=list)
    adjusted: list = field(default_factory=list)


@dataclass
class RequestResolver:
    """The lookups `build_request` cannot do on its own, supplied by the caller.

    model_version(model_id, client_version_id) -> version id   -- needs a session
    preset(user, name) -> banked Toolbox preset dict or None   -- per-account store
    media_id(value)    -> an id PixAI accepts as an INPUT      -- uploads; SUBMIT only

    `media_id` is deliberately absent when pricing. /api/price fires on every
    keystroke in the drawer, and resolving there would upload the same file once
    per character; a quote needs the SHAPE, not an upload-kind id.
    """
    model_version: object = None
    preset: object = None
    media_id: object = None


def model_version_resolver(session):
    """The ONE model_id -> version_id rule, so a quote and a spend can never
    resolve a picked model differently.

    A client version_id is honored IF it names one of model_id's own real
    versions (PixAI's model cards offer a version picker and so does ours);
    otherwise -- absent, stale from a fast model switch, or belonging to a
    DIFFERENT model entirely -- it falls back to the newest. A raw client
    version_id is never trusted blind: that is what once landed generations on
    PixAI as 'Unknown model'. With no model_id at all the client's version_id
    stands unchanged (back-compat), and a model that resolves to nothing leaves
    it untouched rather than inventing one.

    /api/price used to run a DIFFERENT, weaker resolve of its own (rows[0] via
    resolve_version_meta, and only when the payload carried no version_id and no
    mode at all), which is precisely a badge quoting one model while the submit
    sent another.
    """
    def _resolve(model_id, client_version_id=""):
        mid = str(model_id or "").strip()
        vid = str(client_version_id or "").strip()
        if not mid:
            return vid
        versions = list_model_versions(session, mid)
        chosen = next((v for v in versions if v.get("version_id") == vid),
                      None) if vid else None
        if chosen:
            return chosen["version_id"]
        if versions:
            return versions[0]["version_id"]
        return vid
    return _resolve
def _gen_args_from_web_payload(p):
    """Turn the Generate drawer's JSON into the SAME argparse-like namespace the CLI
    feeds to _gen_parameters -- so web + CLI build identical params (one source
    of truth). Clamped to safe ranges, and every clamp that actually fired is listed on
    the returned namespace as `.clamped` = [{field, asked, used}] so the route can tell
    the caller its request was rewritten instead of charging for the difference."""
    from types import SimpleNamespace
    p = p or {}
    def num(k, d, cast=int):
        try:
            return cast(p.get(k, d))
        except (TypeError, ValueError):
            return d
    # "Clamped to safe ranges" was, until this existed, true of `count` alone: width,
    # height, steps and cfg went through num() with no ceiling and straight into a real
    # paid submit, because _gen_parameters only FLOORS width/height to 64 (via
    # _dim) and caps nothing at all. /api/generate is LOGIN-tier on purpose -- any
    # signed-in LAN device may spend -- so the drawer's own HTML min/max attributes are
    # the only bound a well-behaved client honours and a hand-rolled POST honours none:
    # {"width": 999999999, "steps": 999999} reached PixAI, priced at whatever that
    # produces. Clamp here, where the docstring promises it.
    #
    # The ceilings are read off the drawer's OWN controls, not invented:
    #   width/height  64..4096  -- #gen-cw / #gen-ch (min=64 max=4096 step=8), and the
    #                              drawer's d8() already clamps to exactly that before
    #                              it POSTs, so this is the same number twice
    #   steps         1..150    -- #gen-steps, and gateField()'s defMin/defMax
    #   cfg           1..30     -- #gen-cfg, and gateField()'s defMin/defMax
    # Same idiom _gen_parameters uses for the Hires knobs ("bounds read off the
    # live dialog's own controls: strength 0.01-0.99, steps 1-50").
    #
    # These are NOT provably the widest the UI can emit, and an earlier draft of this
    # comment claimed they were ("a model publishing tighter `restrictions` narrows the
    # browser field further"). gateField() REPLACES the field's min/max with whatever
    # `restrictions` carries rather than clipping them, and `restrictions` is live PixAI
    # data -- so a model publishing samplingSteps.max = 200 would widen the drawer's own
    # control and the drawer would legitimately POST 200.
    #
    # Which is exactly why a clamp that FIRES is recorded instead of applied in silence.
    # Clamping is substitution on a paid path: the caller asked for one generation and
    # is charged for a different one, and doing that without a word is a worse failure
    # than the absurd value the clamp exists to refuse -- the money is gone either way,
    # and only the version that says so tells you what it bought. `adjusted` is that
    # receipt; /api/generate hands it back in the response (see api_generate). No
    # price/charge split comes of it either way: /api/price builds its params through
    # this same function, so the badge already quotes the clamped request.
    adjusted = []

    def clamp(field, v, lo, hi):
        c = max(lo, min(hi, v))
        if c != v:
            adjusted.append({"field": field, "asked": v, "used": c})
        return c
    loras = []
    for lo in (p.get("loras") or []):
        vid = str((lo or {}).get("version_id") or "").strip()
        if vid:
            loras.append((vid, (lo or {}).get("weight", 0.7)))
    seed_raw = str(p.get("seed") or "").strip()
    hp = p.get("high_priority") in (True, "1", "true", "on")
    return SimpleNamespace(
        params_json="", prompt=(p.get("prompt") or "").strip(),
        negative=(p.get("negative") or "").strip(),
        model=(p.get("version_id") or "").strip(),
        width=clamp("width", num("width", 512), 64, 4096),
        height=clamp("height", num("height", 512), 64, 4096),
        steps=clamp("steps", num("steps", 25), 1, 150),
        cfg=clamp("cfg", num("cfg", 7, float), 1.0, 30.0),
        count=clamp("count", num("count", 1), 1, 4),
        # Ticked = High (1000, costs extra). Unticked = Turbo (500, free but
        # members-only); core's submit downgrades that to Low on its own if PixAI
        # says this account isn't entitled, so an expired membership no longer
        # breaks every generate/edit/upscale at once.
        priority=(PRIORITY_HIGH if hp else PRIORITY_TURBO),
        mode=(p.get("mode") or "auto"),
        seed=(int(seed_raw) if seed_raw.lstrip("-").isdigit() else None),
        lora=loras,
        # .lower() matters: a JSON `false` arrives as Python False, and
        # str(False) is "False" -- which did NOT match the lowercase tuple, so
        # every explicitly-disabled prompt helper was submitted as ENABLED.
        # Found 2026-07-29 reviewing the pilot's port; it bit the classic
        # drawer's unchecked box identically.
        prompt_helper=(str(p.get("prompt_helper", "1")).lower()
                       not in ("0", "false", "off", "none")),
        ref_media_id=str(p.get("ref_media_id") or "").strip(),
        ref_strength=num("ref_strength", 0.55, float),
        # Upscale + boosters. num() returns its default for a missing/blank value, so
        # None here means "the drawer's Upscale control is Off" and the builder omits
        # every one of these keys -- an absent control must not change the submit.
        enlarge=num("enlarge", None, float),
        enlarge_model=str(p.get("enlarge_model") or "").strip(),
        upscale=num("upscale", None, float),
        upscale_denoising_strength=num("upscale_denoise", None, float),
        upscale_denoising_steps=num("upscale_denoise_steps", None, int),
        face_fix=(p.get("face_fix") in (True, "1", "true", "on")),
        quality_tag=str(p.get("quality_tag") or "").strip(),
        kaisuuken_id="", no_card=bool(p.get("no_card")),
        # _gen_parameters reads named attributes only, so carrying the receipt on
        # the namespace costs the submit shape nothing and keeps it beside the values it
        # describes -- a caller cannot pick up the args and lose the record of what was
        # changed to make them.
        clamped=adjusted)


def _edit_parameters_from_payload(p, user, resolve):
    """Build the instruct-edit `chat` params from the Edit tab's JSON. Source is a
    catalog media_id (the image being edited). A `preset` name swaps in a locally
    banked Toolbox preset (canned prompt + sceneId + its modelId), looked up from
    `user`'s own per-account presets through the caller's `resolve.preset`.
    Returns None if no source (or a preset name that isn't banked).

    `resolve.media_id` is present on a real submit and deliberately absent when
    pricing. With it, every source id is run through the caller's resolver -- a
    catalog id is a generation OUTPUT and PixAI refuses it as an input. Without
    it, ids are left alone: /api/price only needs the SHAPE to compute a cost,
    and uploading on every cost check would upload the same file repeatedly
    while the user types."""
    p = p or {}
    src = str(p.get("source") or "").strip()
    if not src:
        return None
    instruction = (p.get("instruction") or "").strip()
    scene_id, model_id = "", ""
    preset_name = str(p.get("preset") or "").strip()
    if preset_name:
        pre = resolve.preset(user, preset_name) if resolve.preset else None
        if not pre:
            return None
        instruction = pre.get("prompt") or instruction
        scene_id = pre.get("scene_id") or ""
        model_id = pre.get("model_id") or ""
    # A preset pins its own model; otherwise resolve from the Edit-card model picker.
    if not model_id:
        model_id = edit_model_id(p.get("edit_model") or "") or EDIT_PRO_MODEL_ID
    # quality: omitted (passed "") for models with no quality option (Reference Pro);
    # default medium only when the client sent no quality key at all.
    q = p.get("quality")
    if q is None:
        q = "medium"
    res, q, asp = clamp_edit_config(model_id, (p.get("resolution") or "1K"), q,
                                    (p.get("aspect") or "3:4"))   # never send an invalid knob
    kwargs = dict(resolution=res, aspect_ratio=asp, quality=q, scene_id=scene_id,
                  model_id=model_id)
    # multi-image: sources[] (primary + extra refs) if the client sent them, else [source];
    # capped to the model's reference limit (Edit Pro 4 / Reference Pro 10).
    media = p.get("sources")
    media = [str(m).strip() for m in media if str(m).strip()] if isinstance(media, list) else []
    if not media:
        media = [src]
    spec = edit_model_by_id(model_id)
    if spec:
        media = media[:spec["max_refs"]] or [src]
    if resolve.media_id is not None:       # real submit -- see the docstring
        media = [resolve.media_id(m) for m in media]
    return build_chat_edit_parameters(instruction, media, **kwargs)


# An enhance/panelplugin task is priced by its workflow id, which is deliberately NOT in
# _PRICE_SCALARS: pricing the workflow-less shape that survives the allowlist returns a
# confident WRONG number, so no number is the honest answer until it is measured live.
_ENHANCE_PRICE_NOTE = "couldn't verify the cost of an AI preset yet"

# The READ_ONLY refusal wording per road -- the same sentences submit_generation and
# submit_fixer raise, so moving the guard earlier did not change what a user reads.
_SUBMIT_ACTIONS = {"fix": "submit a hand/face fix (spends credits)"}
_SUBMIT_ACTION_DEFAULT = "submit a generation (spends credits)"


def build_request(payload, *, mode=None, user=None, is_member=None, resolve=None):
    """Turn a web payload into the ONE GenerationRequest that both /api/price and the
    create routes ride. The mode dispatch lives here and nowhere else.

    `mode` pins the road when the CALLER knows it -- a create route is single-purpose,
    and /api/generate must build an image gen whatever the payload says. It matters on a
    spend path: `mode` is overloaded in the payload itself (the image road reads it as
    the inferenceProfile quality setting, "auto"/"lite"/"pro"/...), so an unpinned
    {"mode": "I2V"} POSTed at /api/generate would otherwise build and pay for a VIDEO.
    Omit it and the road is read off the payload -- that is /api/price, the one caller
    that legitimately serves every road.

    `is_member` is the same entitlement the submit applies, so a badge cannot quote a
    price for a members-only option that will be stripped before it is sent. `resolve`
    carries the lookups this cannot do itself (see RequestResolver).

    Raises PixAIError when a BUILDER refuses (asking for both upscale methods at once, an
    unknown video mode): that is a real refusal with a real message, and each caller
    already renders one -- the badge as its note, a create route as its logged failure.
    A payload that is merely INCOMPLETE is not an error: it comes back with `note` set and
    `parameters` None."""
    p = payload or {}
    rs = resolve if resolve is not None else RequestResolver()
    road = str(mode or p.get("mode") or "").strip()
    no_card = bool(p.get("no_card"))

    if road == "edit":
        params = _edit_parameters_from_payload(p, user, rs)
        return GenerationRequest(mode="edit", parameters=params, no_card=no_card,
                                 note=None if params else "pick an image to edit")

    if road == "fix":
        # A hand/face Fix is submitted over POST /v2/task/fixer, whose {mediaId, boxes}
        # body /v2/task-price cannot read -- but the taskKind=chat task PixAI builds from
        # it IS priceable, so build_fixer_price_parameters synthesizes that chat.fixer
        # shape (see its docstring for the measurement). `parameters` is therefore the
        # PRICE shape only; `media_id` + `boxes` are what actually go out, which is why
        # submit() reads those, and a shape this could not synthesize never blocks a
        # submit -- submit_fixer runs the same clean_fix_boxes and is the real guard.
        src = str(p.get("source") or "").strip()
        if src and rs.media_id is not None:
            src = str(rs.media_id(src) or src)
        boxes = list(p.get("boxes") or [])
        # no_card is forced True here and is NOT read off the payload: /v2/task/fixer
        # takes only mediaId + boxes, with no kaisuukenId field anywhere on it, so a free
        # card can never be spent on a Fix however well /v2/kaisuuken/check matches the
        # synthesized params. Letting the card check run would paint the badge emerald
        # "FREE -- a card covers this" over an action about to charge full credits.
        if not src:
            return GenerationRequest(mode="fix", no_card=True, boxes=boxes,
                                     note="pick an image to fix")
        try:
            params = build_fixer_price_parameters(src, boxes)
        except PixAIError:
            return GenerationRequest(mode="fix", no_card=True, media_id=src, boxes=boxes,
                                     note="drag a box over a hand or face")
        return GenerationRequest(mode="fix", parameters=params, no_card=True,
                                 media_id=src, boxes=boxes)

    if road == "video" or road in ("I2V", "FLF", "R2V"):
        shot = str(p.get("mode") or "").strip().upper()
        if shot not in ("I2V", "FLF", "R2V"):
            shot = "R2V"                   # the Loom's own default for an unnamed shot
        imgs = [str(i) for i in (p.get("images") or []) if str(i).strip()]
        # .isdigit() on the video/audio refs is the SUBMIT's filter, and pricing uses it
        # too now: a non-numeric ref was priced and then dropped before the mutation,
        # which is a quote for a different job than the spend.
        vids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip().isdigit()]
        auds = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip().isdigit()]
        # I2V/FLF are image-anchored (source frame / start+end frame); R2V accepts
        # ANY reference kind alone (e.g. a video-only Multi-ref) -- gating all three
        # modes on `imgs` alone silently mispriced a video/audio-only R2V request as
        # "pick a source image", found 2026-07-18 while wiring the ref-slot expansion.
        has_ref = imgs or (shot == "R2V" and (vids or auds))
        if not has_ref:
            return GenerationRequest(mode="video", no_card=no_card,
                                     note="pick a source image")
        params = build_shot_video_params(
            shot, (p.get("prompt") or "").strip(), image_ids=imgs,
            video_ids=vids, audio_ids=auds,
            duration=p.get("duration") or 5,
            generate_audio=bool(p.get("generate_audio") or p.get("audio")),
            model=(p.get("video_model") or ""),
            camera_movement=(p.get("camera_movement") or ""),
            quality=(p.get("quality") or "professional"),
            audio_language=(p.get("audio_language") or "english"),
            negative=(p.get("negative") or "").strip(),
            is_private=bool(p.get("is_private")),
            use_prompt_helper=bool(p.get("prompt_helper")))
        return GenerationRequest(mode="video", parameters=params, no_card=no_card)

    if road == "enhance":
        src = str(p.get("source") or "").strip()
        if src and rs.media_id is not None:
            src = str(rs.media_id(src) or src)
        wid = str(p.get("workflow_id") or "").strip()
        wname = str(p.get("workflow_name") or "").strip()
        if not src:
            return GenerationRequest(mode="enhance", no_card=no_card,
                                     note="pick an image first",
                                     price_note=_ENHANCE_PRICE_NOTE)
        if not (wid or wname):
            return GenerationRequest(mode="enhance", no_card=no_card, media_id=src,
                                     note="pick an AI preset",
                                     price_note=_ENHANCE_PRICE_NOTE)
        # workflow_name wins inside the builder when both are set; a preset is pinned to
        # exactly one of the two (numeric id OR author/workflow name) in the caller.
        # Change Emotion carries a control: pass the picked expression, and ONLY for that
        # preset (an unknown input on the others would be a stray arg on a spend submit).
        # The picker sends the option KEY (filename stem); emotionlab's `prompt` arg wants
        # the danbooru TAG STRING, so translate key->tag here (unknown key falls back to
        # itself).
        emotion_key = str(p.get("emotion") or "").strip()
        emotion_tag = ENHANCE_EMOTION_PROMPTS.get(emotion_key, emotion_key)
        extra = ({ENHANCE_EMOTION_ARG: emotion_tag}
                 if emotion_tag and wname == ENHANCE_EMOTION_WORKFLOW else None)
        params = build_panelplugin_parameters(src, wid, workflow_name=wname,
                                              extra_inputs=extra)
        return GenerationRequest(mode="enhance", parameters=params, no_card=no_card,
                                 media_id=src, price_note=_ENHANCE_PRICE_NOTE)

    # --- the image road (the payload's own `mode` is the inferenceProfile here) --------
    args = _gen_args_from_web_payload(p)
    if rs.model_version is not None:
        args.model = rs.model_version(p.get("model_id") or "", args.model)
    lora_ids = [vid for vid, _w in (args.lora or [])]
    if not args.model:
        return GenerationRequest(mode="image", no_card=args.no_card, note="pick a model",
                                 lora_version_ids=lora_ids, adjusted=args.clamped)
    # Same entitlement the submit applies, so the badge cannot quote a price for a
    # members-only option that will be stripped before it is sent.
    args.is_member = is_member
    return GenerationRequest(mode="image", parameters=_gen_parameters(args),
                             no_card=args.no_card, model_version_id=args.model,
                             lora_version_ids=lora_ids, adjusted=args.clamped)


def price(session, req):
    """The live cost + free-card verdict for a request. READ-ONLY -- it creates nothing
    and spends nothing, and the object it prices is the very `req.parameters` a submit
    would send, which is the whole point of this road.

    Fails CLOSED in both directions: an unbuildable payload is `cost: None` with the note,
    never a `free` a caller could act on; and `free` is card_covers(best), NOT bool(best)
    -- a multi-ticket video can MATCH a card the account holds too few tickets of (issue
    #15), and that case is paid at the full price because the site attaches nothing. One
    predicate shared with the CLI preview and _apply_kaisuuken, so this can never say FREE
    while the submit charges.

    `cards` is the HELD count (kept under its old name for the badge's "(N left)"); the
    job's ticket cost is `cards_needed`, and `card_short` is the honest flag the badge
    renders as "not enough -- costs the full price"."""
    if req.parameters is None:
        return {"cost": None, "free": False, "note": req.note}
    if req.price_note:
        return {"cost": None, "free": False, "note": req.price_note}
    cost = price_task(session, req.parameters)
    best = None if req.no_card else match_kaisuuken(session, req.parameters, enrich=True)
    covered = card_covers(best)
    return {"cost": cost, "free": covered,
            "cards": (best or {}).get("total"),
            "cards_held": (best or {}).get("total"),
            "cards_needed": (best or {}).get("consumeAmount"),
            "card_short": bool(best) and not covered,
            "card_name": (best or {}).get("name"),
            # The Loom's batch tally keys its per-template ticket pool on this (falls
            # back to card_name when absent) -- see loom-core.js tallyPricesDetailed.
            "card_template": (best or {}).get("templateId"),
            "card_expires": (best or {}).get("expiresAt")}


def submit(session, req, *, no_card=None):
    """Spend: READ_ONLY guard -> free card -> the one mutation this road's mode uses.
    Returns {"task_id": ...}.

    The READ_ONLY check is FIRST, ahead of the card match, and that ordering is the point
    of putting it here. `_apply_kaisuuken` calls /v2/kaisuuken/check -- a real network
    call on the account -- and every web create route used to make it before reaching
    submit_generation's own guard, so a READ_ONLY install still talked to PixAI before
    refusing. That is the identical fail-open the four CLI runners were fixed for on
    2026-07-21; the web side kept it until this became one choke.

    `no_card` overrides the request's own flag for a caller with a reason to (the
    request's flag is what the payload asked for). A Fix ignores both: POST /v2/task/fixer
    has no kaisuukenId field at all, so no card can ever cover one, and this never runs
    the check that would tell a user otherwise."""
    _check_read_only(_SUBMIT_ACTIONS.get(req.mode, _SUBMIT_ACTION_DEFAULT))
    if req.mode == "fix":
        # A Fix's `parameters` are the PRICE shape and may legitimately be None while the
        # submit is still good (a box clean_fix_boxes would drop is not this function's
        # call to make -- submit_fixer runs the same cleaner and is the real guard). What
        # it cannot do without is the two fields /v2/task/fixer actually takes.
        if not req.media_id or not req.boxes:
            raise PixAIError(req.note or "nothing to submit")
        return {"task_id": submit_fixer(session, req.media_id, req.boxes)}
    if req.parameters is None:
        raise PixAIError(req.note or "nothing to submit")
    from types import SimpleNamespace
    skip = req.no_card if no_card is None else bool(no_card)
    # Passing the flag through rather than branching around the call keeps
    # _apply_kaisuuken's own precedence (explicit id > no_card > auto-match) and its
    # spend log ("--no-card: this WILL spend credits") the single source of both.
    _apply_kaisuuken(session, req.parameters,
                     SimpleNamespace(kaisuuken_id="", no_card=skip))
    return {"task_id": submit_generation(session, req.parameters)}


# =============================================================================
# end of the one payload road
# =============================================================================


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


def _edit_model_label(session, fm, model_id):
    """The model name to store on an EDIT (chat-task) row -- resolvable, never a dead end.

    This used to be `fm.get("model_name", "") or "Edit"`. extract_full_meta fills model_name
    for a chat task only from the local EDIT_MODELS table, so an edit made with any model NOT
    in those two hardcoded entries -- `--edit-image --params-json` with a newer modelId, or
    `--task-id` recovering a chat task made on PixAI's web UI after this table was last
    updated -- landed the literal string "Edit" in the catalog. That string is worse than
    blank: `_needs_model_fix` sees a non-empty, non-digit name that differs from the model_id,
    calls the row resolved, and --fix-models never queues it. The row showed the generic
    "Edit" forever, having also lost WHICH edit model made it, and no re-run could repair it
    (M17, 2026-07-27).

    So an unknown edit model goes through the same _resolved_model_name every ordinary
    generation uses. Whatever that returns is recoverable: a real name is the answer; the id
    (its soft-failure return) and "" both make `_needs_model_fix` hand the row to
    --fix-models on the next run.

    "Edit" survives for the one case it was ever right about -- a chat task carrying NO model
    id at all, where there is nothing to resolve and nothing for --fix-models to queue
    regardless (it returns '' for an id-less row), so a generic label costs nothing and beats
    an empty Model field."""
    mid = str(model_id or "").strip()
    if not mid:
        return str((fm or {}).get("model_name") or "").strip() or "Edit"
    return _resolved_model_name(session, fm, mid)


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
        # Hand the downloader the task's OWN submitted parameters, the way the submit paths
        # hand it theirs. video_outputs reads only the referenceVideo block, so with an empty
        # dict here a plain image-to-video (i2vPro) had nothing to read: every clip collected
        # through this path -- the ordinary Video tab case -- was cataloged with a blank
        # prompt, negative prompt, duration and model.
        saved = _download_video_task(session, result, task_id, out, a,
                                     result.get("parameters") or {})
        mids = [str(o["video_media_id"]) for o in vouts if o.get("video_media_id")]
        # Real clip length for the reel. media_tools.duration answers at full precision;
        # the 2dp are this call site's own display choice (the catalog's video_duration
        # column is read back as a label, not re-measured).
        _dur = duration(saved[0]) if saved else None
        dur = round(_dur, 2) if _dur is not None else None
        return {"media_ids": mids, "saved": len(saved), "is_video": True, "duration": dur}
    fm = extract_full_meta(result)
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
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
        # No hardcoded reference price here: the line below prints THIS clip's real cost from
        # /task-price (and the card verdict for it). A fixed "a 5s clip costs ~27,500" used to
        # sit right above the true "~82,500" for a 15s clip -- two numbers on one screen for
        # one spend (found running the preview live, 2026-08-16).
        print("  Re-run with --confirm to submit.")
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
        _apply_kaisuuken(session, params, args)   # free-card check on the API-key session
        # gql_mutate, never gql_adhoc: a re-POSTed createGenerationTask is a second
        # (expensive) video and a second charge -- see gql_mutate's docstring.
        # _session_for_create: the CREATE rides the mirror JWT when the toggle is on
        # (else pass-through); download below stays on the API-key `session` (F6).
        created = gql_mutate(_session_for_create(session), _GEN_MUTATION, {"parameters": params})
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
        _apply_kaisuuken(session, params, args)   # free-card check on the API-key session
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        # _session_for_create: create rides the mirror JWT when on; download stays API-key (F6).
        created = gql_mutate(_session_for_create(session), _GEN_MUTATION, {"parameters": params})
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
        _apply_kaisuuken(session, params, args)   # free-card check on the API-key session
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        # _session_for_create: create rides the mirror JWT when on; download stays API-key (F6).
        created = gql_mutate(_session_for_create(session), _GEN_MUTATION, {"parameters": params})
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
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    chat = (params.get("chat") or {}) if isinstance(params, dict) else {}
    prompt_used = fm.get("prompt_full") or prompt or chat.get("prompts", "")
    # Resolved ONCE for the task, not per output image: the model is a property of the task,
    # and _resolved_model_name can reach the network for an edit model this app doesn't know
    # locally (model_name_gql is process-cached, so this is at most one call either way).
    edit_model_id_used = str(chat.get("modelId") or fm.get("model_id") or "")
    edit_model_name = _edit_model_label(session, fm, edit_model_id_used)
    img_dir = out / "images"
    rows, saved = [], []
    # See build_catalog_row step 3: an edit recovered by --edit-task-id can land on media
    # the user has already rated, filed or published.
    known = known_catalog_rows(db_path, mids)
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
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id), seed=seeds.get(mid, ""),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt_used,   # prompt_preview derives from it
            model_id=edit_model_id_used,
            model_name=edit_model_name,
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or ""),
            height=str((info or {}).get("height") or ""))
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
    # Ids whose lookup FAILED (network/timeout/5xx), as opposed to answering "no such model".
    # --relabel-removed writes a permanent label that _needs_model_fix then reads as
    # "resolved", so a run must never act on a failure it could simply leave for the next one
    # (M18, 2026-07-27). _parallel_map calls on_error before yielding that item, so the set
    # is always populated by the time the loop body below tests it.
    lookup_failed = set()

    def _note_lookup_failure(vid, exc):
        lookup_failed.add(vid)
        print("  model {} could not be checked ({}) -- left untouched for the next run".format(
            vid, str(exc)[:160]))

    for vid, name in _parallel_map(sorted(to_resolve),
                                   lambda v: model_name_gql(session, v, strict=True),
                                   workers, _prog, delay=getattr(args, "delay", 0.4),
                                   on_error=_note_lookup_failure):
        if name and name != vid and not str(name).isdigit():
            for r in to_resolve[vid]:
                r["model_name"] = name
                fixed += 1
        elif vid in lookup_failed:
            # Not counted as unresolved either: "unresolved" means PixAI answered and had no
            # name, and the summary's model tally is derived from it. This id simply was not
            # examined, and re-running --fix-models will pick the same rows up again because
            # nothing was written over them.
            continue
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
    print("\nFixed {} row(s) across {} model(s); {} id(s) unresolved{}{}.".format(
        fixed, len(to_resolve) - unresolved - len(lookup_failed), unresolved,
        " (relabeled {} rows to '{}')".format(relabeled, removed_label) if relabeled else "",
        "; {} id(s) not checked -- lookup failed, re-run to finish them".format(
            len(lookup_failed)) if lookup_failed else ""))
    return {"fixed": fixed, "relabeled": relabeled,
            "models": len(to_resolve) - unresolved - len(lookup_failed),
            "unresolved": unresolved, "lookup_failed": len(lookup_failed)}


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


_UPSERT_ARTWORK = (
    "mutation upsertArtwork($input: UpsertArtworkInput!, $id: ID) {"
    " upsertArtwork(input: $input, id: $id) { id mediaId title visibility hidePrompts } }")
_PUBLISH_FROM_TASK = (
    "mutation createArtworkFromTaskV2($taskId: ID!, $input: CreateArtworkFromTaskInput!) {"
    " createArtworkFromTaskV2(taskId: $taskId, input: $input)"
    " { id mediaId title visibility hidePrompts } }")
_DELETE_ARTWORK = "mutation deleteArtwork($id: ID!) { deleteArtwork(id: $id) }"
_LIST_TACKS = (
    "query listTacks($q: String, $first: Int) { tacks(q: $q, first: $first) {"
    " edges { node { id codeName defaultName } } } }")


def resolve_tack_ids(session, tags):
    """Map plain tag strings to PixAI 'tack' ids (their tag objects). The publish form
    sends `tackIds`, not free text -- `tags` is always [] in the real payload -- so a tag
    that has no tack simply cannot be attached, and is reported back to the caller rather
    than silently dropped. Read-only. Returns (ids, unmatched)."""
    ids, unmatched = [], []
    for t in tags or []:
        name = str(t).lstrip("#").strip()
        if not name:
            continue
        try:
            d = gql_adhoc(session, _LIST_TACKS, {"q": name, "first": 8}) or {}
            edges = ((d.get("tacks") or {}).get("edges")) or []
        except PixAIError:
            edges = []
        hit = None
        for e in edges:
            n = (e or {}).get("node") or {}
            if str(n.get("codeName") or "").lower() == name.lower() \
                    or str(n.get("defaultName") or "").lower() == name.lower():
                hit = n
                break
        # NO fuzzy fallback to edges[0] here -- that used to silently attach whatever
        # ranked first in PixAI's search (e.g. typing "moon" attaching "moonlight") with
        # no signal in the preview, contradicting this function's own contract below.
        # Found by ultrareview 2026-08-06: a real, unreported substitution onto a public
        # artwork. Only an EXACT codeName/defaultName match counts as resolved now;
        # anything else is reported in `unmatched`, exactly as promised.
        if hit and hit.get("id"):
            ids.append(str(hit["id"]))
        else:
            unmatched.append(name)
    return ids, unmatched


_TRAIN_FREE_CURRENCY = "free::user_lora_training"
_CREATE_TRAINING = ("mutation createTrainingTask($input: CreateTrainingTaskInput!) {"
                    " createTrainingTask(input: $input) { id refId } }")
# PixAI's real LoRA-training categories, probed live off the train-lora page's own
# category select 2026-08-06 (the design mockup's character/style/concept was placeholder
# -- "concept" isn't a real PixAI value). Values are what the mutation takes.
TRAIN_CATEGORIES = ("character", "animal", "style", "realistic", "pose", "clothing",
                    "background", "detail", "other")
TRAIN_MIN_IMAGES = 10
TRAIN_MAX_IMAGES = 100


# The trainable base-model architectures, in the order PixAI's own train page shows them,
# each mapped to its friendly label. The label map is PixAI's own (harvested
# constants-*.js: mmdit26b->DiT.3, mmdit26a->DiT.2, dit7->DiT.1, sdxl->SDXL) plus SD 1.5.
# "Model Type" on the train page IS this architecture -- picking one filters which base
# models ("Model Theme") are offered; the value actually submitted is the chosen model's
# VERSION id, not its model id (the site names the field baseModelId but assigns it the
# versionId -- confirmed in the harvested submit builder).
_TRAIN_ARCHS = (
    ("MMDIT26B_MODEL", "DiT.3"),
    ("MMDIT26A_MODEL", "DiT.2"),
    ("DIT7_MODEL",     "DiT.1"),
    ("SDXL_MODEL",     "SDXL"),
    ("SD_V1_MODEL",    "SD 1.5"),
)

# PixAI's curated training-base list is NOT the public generationModels catalog (the
# owner caught this -- my first build pulled the general model-picker feed). The real
# list is served bundled with the pricing matrix by the train page's own config, which
# is NOT reachable through any documented endpoint or the RE harvest (probed exhaustively
# 2026-08-06: the connection's `feed` arg is ignored, `category:"in-house"` only covers
# SD 1.5, and the SDXL officials aren't in the public catalog at all). So this is a
# CAPTURED SNAPSHOT of that config (owner pasted the real response 2026-08-06). It matches
# the site exactly. To refresh when PixAI adds base models: on the train-lora page, capture
# the config response (models[] + pricing) and replace both constants below.
_TRAIN_BASE_MODELS = [
    # (version_id, model_id, title, modelType, usage, cover)
    ("1983308862240288769", "1982880136609467518", "Tsubaki.2", "MMDIT26A_MODEL", "animation", "https://images-ng.pixai.art/images/stillThumb/b03c47d1-fcfa-4502-af96-7ef049ebaade"),
    ("1894092844569363483", "1884107375027888751", "Tsubaki", "DIT7_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/98cd261b-9a65-42cd-916b-df27b5e61607"),
    ("1844843519625072849", "1844843518698131638", "Illustrious-v1.0", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/2e0591cc-50fa-4e37-89c6-e641cf65c483"),
    ("1830737069924162722", "1800107133055979065", "NoobAI XL", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/bd4ff6a2-b3de-4645-94e8-3ad19ed82f3f"),
    ("1869108561160475178", "1869108554114044295", "Hinata v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/43cf3a51-b7e3-4e8c-8847-38b44471f03b"),
    ("1795876005752987687", "1795876005744599078", "Illustrious-v0.1", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/dc62608f-53f3-426f-a462-ea49578115cd"),
    ("1861558740588989558", "1861558737426484240", "Haruka-v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/1c51e854-da5d-4e38-9a60-5532d1e64d23"),
    ("1856956435031440023", "1856956427276171616", "Otome-v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/908f0958-f377-4cca-93ee-11438fd0752f"),
    ("1805666669332128958", "1805666668619097261", "Haruka", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/8f07e40a-dca1-41fe-a950-cf5c06a59d3f"),
    ("1772043571096449082", "1772043569905266745", "Hikari", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/11ca16f5-a018-4c4f-92e5-4f7d67d8ac84"),
    ("1856964022763541122", "1856964021647856206", "Illustrious-v2.0", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/2f6816a5-82f3-47e4-afa9-58a8415d0f22"),
    ("1788325270093701704", "1788325267627450916", "Waterfront-v0.9", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/52b7f937-5abc-4406-b753-b826115f92a3"),
    ("1728110559428576906", "1728110558497441412", "Animagine XL", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/49c70b8b-82f0-435b-97f9-0887139aa375"),
    ("1722800994358889032", "1722800993478085189", "PhotoPedia XL", "SDXL_MODEL", "realistic", "https://images-ng.pixai.art/images/thumb/1b5538ef-4ffd-4e00-ab27-393104db7b51"),
    ("1954632828118619567", "1954632827019711809", "Hoshino v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/fbc85e5d-6f5e-4b02-a54a-fc679001770f"),
    ("1811528826405408057", "1811528825797233974", "Hoshino", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/d3b638af-7bac-4878-8f3a-1ec4b62998ab"),
    ("1854247165841065427", "1854247164461139322", "Hinata v1", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/060b9c8c-ed2e-4e45-98c1-ac5df005b248"),
    ("1648918127446573124", "1648918125777240131", "Moonbeam", "SD_V1_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/96596124-b2cd-4619-819a-55b425c79307"),
    ("1718827626761711784", "1718827626749128871", "majicMIX realistic", "SD_V1_MODEL", "realistic", "https://images-ng.pixai.art/images/thumb/9bb8d254-ef76-44ef-8a1a-9a64a95df76b"),
    ("1648918115270508582", "1648918113336934437", "Anything V5", "SD_V1_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/e0e7b6a7-baa5-4178-adbe-36610797019f"),
]

# Real training prices per architecture (captured with the model list 2026-08-06). PixAI
# prices training from this matrix, keyed by modelType: `price` for a fresh dataset,
# `reuse` when re-using an existing dataset, `retrain` for a re-run. A free-training quota
# unit overrides all of this to 0. `originalPrice` (when present) is the pre-discount tag.
_TRAIN_PRICING = {
    "SD_V1_MODEL":    {"price": 25000, "retrain": 25000, "reuse": 12500},
    "SDXL_MODEL":     {"price": 25000, "retrain": 25000, "reuse": 12500, "originalPrice": 75000},
    "DIT7_MODEL":     {"price": 50000, "retrain": 50000, "reuse": 25000, "originalPrice": 150000},
    "MMDIT26A_MODEL": {"price": 100000, "retrain": 50000, "reuse": 50000, "originalPrice": 200000},
}


def training_price_for_version(version_id):
    """The base training price (fresh dataset) for the base model behind version_id, from
    the captured pricing matrix -- or None if the version isn't a known base or its type
    isn't priced. None means 'unknown', which the caller must treat as the unsafe case."""
    arch = next((m[3] for m in _TRAIN_BASE_MODELS if m[0] == str(version_id)), None)
    row = _TRAIN_PRICING.get(arch or "")
    return row.get("price") if row else None


def list_trainable_base_models(session=None, per_type=None):
    """The base models a LoRA can be trained on, grouped by architecture -- the train
    page's Model Type -> Model Theme picker. Served from PixAI's own curated config (see
    _TRAIN_BASE_MODELS' note). `session` is accepted but unused: the list is a captured
    snapshot, not a live query, because the real config endpoint isn't reachable. Each
    model dict: {version_id, model_id, title, cover, usage}. version_id is what
    `submit_training(base_model_id=...)` takes."""
    groups = []
    for arch, label in _TRAIN_ARCHS:
        models = [
            {"version_id": v, "model_id": mid, "title": title, "cover": cover, "usage": usage}
            for (v, mid, title, mtype, usage, cover) in _TRAIN_BASE_MODELS if mtype == arch
        ]
        if models:
            price = (_TRAIN_PRICING.get(arch) or {}).get("price")
            groups.append({"arch": arch, "label": label, "models": models, "price": price})
    return groups


def training_free_quota(session):
    """How many FREE LoRA trainings the account has left. PixAI tracks these as a QUOTA
    under the currency `free::user_lora_training` -- NOT as a kaisuuken free card (the
    card pool is generation-only, which is why /v2/kaisuuken/summary never lists one).
    Read-only. Returns an int; 0 on any failure, which is the safe direction: 0 means
    'treat this as paid', never 'assume it's free'."""
    try:
        d = gql_adhoc(session,
                      "query($currency:String!){ me { id quotaAmount(currency:$currency) } }",
                      {"currency": _TRAIN_FREE_CURRENCY}) or {}
        return int(((d.get("me") or {}).get("quotaAmount")) or 0)
    except (PixAIError, TypeError, ValueError):
        return 0


def normalize_trigger_words(text):
    """PixAI's own trigger-word rules, from the train-LoRA form: no leading/trailing
    spaces and no consecutive spaces (the form states both). Returns the cleaned string."""
    return " ".join(str(text or "").split())


def validate_training(base_model_id, media_ids, title, trigger_words, category,
                      training_task_id=""):
    """Mirror the site's OWN pre-submit validation (its Er() builder) so a bad request is
    refused here instead of burning a round trip -- or worse, a free-training quota unit.
    Returns the normalized trigger words. Raises PixAIError with a plain-language reason."""
    # base_model_id is the model VERSION id (list_trainable_base_models' version_id) --
    # PixAI's baseModelId input takes the version, not the model, id.
    if not base_model_id:
        raise PixAIError("pick a base model to train on")
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    if len(ids) < TRAIN_MIN_IMAGES and not training_task_id:
        raise PixAIError("training needs at least %d images -- you have %d"
                         % (TRAIN_MIN_IMAGES, len(ids)))
    if len(ids) > TRAIN_MAX_IMAGES:
        raise PixAIError("training takes at most %d images -- you have %d"
                         % (TRAIN_MAX_IMAGES, len(ids)))
    if not str(title or "").strip():
        raise PixAIError("give the LoRA a name")
    tw = normalize_trigger_words(trigger_words)
    if not tw:
        raise PixAIError("trigger words are required -- they're how you summon the LoRA")
    if len(tw) > 200:
        raise PixAIError("trigger words are too long")
    if str(category or "") not in TRAIN_CATEGORIES:
        raise PixAIError("pick a category (%s)" % "/".join(TRAIN_CATEGORIES))
    return tw


def submit_training(session, base_model_id, media_ids, title, trigger_words, category,
                    training_task_id="", primary_lora_model_id="", kaisuuken_id=""):
    """Submit a real LoRA training task to PixAI (`createTrainingTask`).

    SPENDS unless the account has free-training quota left (see training_free_quota) --
    so it goes through gql_mutate: SINGLE ATTEMPT, no retry, for exactly the reason
    every other spend path does. A lost response after the server accepted the task
    would, on retry, start a SECOND training and consume a second quota unit (or a real
    credit charge, which for training is large). _check_read_only gates it like every
    other account mutation.

    This function does NOT decide whether the user wants to pay: callers preview first
    (quota + validation) and only call this once the user has confirmed. Input shape
    mirrors the site's own form exactly. Returns the created task dict."""
    _check_read_only("submit a LoRA training task")
    tw = validate_training(base_model_id, media_ids, title, trigger_words, category,
                           training_task_id)
    inp = {
        "baseModelId": str(base_model_id),
        "mediaIds": [str(m) for m in (media_ids or []) if str(m).strip()],
        "title": str(title).strip(),
        "type": "USER_MULTI_LORA",
        "triggerWords": tw,
        "category": str(category),
    }
    if training_task_id:
        inp["trainingTaskId"] = str(training_task_id)
    if primary_lora_model_id:
        inp["primaryLoraModelId"] = str(primary_lora_model_id)
    if kaisuuken_id:
        inp["kaisuukenId"] = str(kaisuuken_id)
    d = gql_mutate(session, _CREATE_TRAINING, {"input": inp}) or {}
    return d.get("createTrainingTask") or {}


def source_media_of_task(task):
    """The SOURCE image a derived generation was made FROM, plus what kind of derivation
    it was -- returns (source_media_id, kind) or (None, None) for an original generation.

    This is the data behind Image Details' LINEAGE panel. Every derive path already puts
    its input image's mediaId in the submit parameters, and PixAI persists it on the task,
    so it is readable back from getTaskById for history as well as recordable going
    forward. The four real shapes (see build_video_parameters / build_chat_edit_parameters
    / build_panelplugin_parameters / the upscale block):
      * img2video       -> parameters.i2vPro.mediaId        (kind "video"; legacy tasks: i2v)
      * edit/reference  -> parameters.chat.mediaId          (kind "edit")
      * enhance/plugin  -> parameters.inputs.image.media_id (kind "enhance")
      * upscale/hires   -> parameters.mediaId + upscale|enlarge ratio  (kind "upscale")
    A plain txt2img has no input image and returns (None, None)."""
    params = ((task or {}).get("parameters") or {})
    if not isinstance(params, dict):
        return (None, None)
    # i2vPro is the current image-to-video submit shape; `i2v` is the legacy key older
    # tasks carry. Reading only `i2v` meant EVERY modern i2v task returned (None,None), so
    # video lineage was never captured -- create-time OR --backfill-lineage (audit 2026-08-15).
    i2v = params.get("i2vPro") or params.get("i2v")
    if isinstance(i2v, dict) and i2v.get("mediaId"):
        return (str(i2v["mediaId"]), "video")
    chat = params.get("chat")
    if isinstance(chat, dict) and chat.get("mediaId"):
        return (str(chat["mediaId"]), "edit")
    # Enhance (panelplugin workflow -- handfix / bg-remove / line-art / sketch-coloring / ...):
    # the source image is nested at inputs.image.media_id in the b93ce1e submit shape
    # (build_panelplugin_parameters). This MUST be checked BEFORE the top-level `mediaId`
    # branch below: a Bridge result carries no top-level mediaId, so without this branch it
    # files as an ORIGINAL generation with no source (catalog lineage correctness, not polish).
    # VERIFIED 2026-08-18 against a real completed panelplugin task (bg-remove, task
    # 2046466559401368536): getTaskById reads the source back as inputs.image.media_id in
    # snake_case -- PixAI does NOT camelCase it to mediaId on persist. So `media_id` is the
    # live read-back shape and the `mediaId` fallback below is defensive-only (kept in case a
    # future submit/persist shape change flips it).
    inputs = params.get("inputs")
    if isinstance(inputs, dict):
        img = inputs.get("image")
        if isinstance(img, dict):
            emid = img.get("media_id") or img.get("mediaId")
            if emid:
                return (str(emid), "enhance")
    mid = params.get("mediaId")
    if mid:
        ratio = params.get("upscale") or params.get("enlarge")
        return (str(mid), "upscale" if ratio else "derived")
    return (None, None)


def task_media_index(session, task_id, media_id):
    """Which image of a task a given media_id IS -- the `mediaIndex` the publish mutation
    needs. Derived from the task's own ordered output list (`_task_image_media`, the same
    enumeration the downloader uses), never guessed from a filename: a batchSize>1 task
    stores individuals under outputs.batch[] and their ORDER is the index PixAI means.
    Read-only. Returns the int index, or None if the task/media can't be resolved -- the
    caller decides whether that's fatal (it is, for publishing: publishing the wrong image
    of a batch is not a recoverable mistake)."""
    if not task_id or not media_id:
        return None
    try:
        task = task_detail_gql(session, str(task_id))
    except PixAIError:
        return None
    if not task:
        return None
    pairs = _task_image_media(task.get("outputs") or {})
    for i, (mid, _seed) in enumerate(pairs):
        if str(mid) == str(media_id):
            return i
    return None


def publish_artwork_from_task(session, task_id, media_index=0, title="", description="",
                              tack_ids=None, private=False, hide_prompts=False,
                              challenge=None, extra=None):
    """Publish one image of a generation task as a PixAI ARTWORK
    (`createArtworkFromTaskV2`). Account-mutating (it puts work on your public profile),
    so it goes through gql_mutate -- single attempt, no retry: a lost response after the
    server already created the artwork would otherwise publish a duplicate. Costs no
    credits. Input shape mirrors the site's own publish form exactly (title/description/
    visibility/isPrivate/hidePrompts/tags=[]/tackIds/mediaIndex, challenge inside extra).
    Returns the created artwork dict; raises PixAIError on failure.

    `challenge` DOES NOT ENTER A CONTEST -- verified live 2026-09-01, after a publish made
    with one attached produced no entry. It is artwork METADATA: the contest back-link that
    listArtworks hands back on node.extra (private/API_OPERATIONS.md). Entering is a
    separate REST call, `contest_enter` -> POST /v2/contest/{slug}/artwork, and a caller
    that wants publish-and-enter has to make both (see api_myart_publish, which does)."""
    _check_read_only("publish an artwork to your PixAI account")
    vis = "PRIVATE" if private else "PUBLIC"
    ex = dict(extra or {})
    if challenge:
        ex["challenge"] = challenge
    if description:
        ex["description"] = description
    inp = {
        "title": title or "",
        "description": description or "",
        "tags": [],                       # always empty on the wire; tackIds carries tags
        "tackIds": list(tack_ids or []),
        "visibility": vis,
        "isPrivate": bool(private),
        "hidePrompts": bool(hide_prompts),
        "mediaIndex": int(media_index or 0),
        "extra": ex,
    }
    d = gql_mutate(session, _PUBLISH_FROM_TASK,
                   {"taskId": str(task_id), "input": inp}) or {}
    return d.get("createArtworkFromTaskV2") or {}


def update_artwork(session, artwork_id, media_id=None, title=None, description=None,
                   tack_ids=None, private=None, hide_prompts=None, extra=None):
    """Edit an EXISTING artwork (`upsertArtwork` with an id) -- retitle, re-tag, or flip
    visibility (the My Art publish-toggle / edit-tags actions). Account-mutating ->
    gql_mutate. Only the fields you pass are sent, so a tag edit can't silently reset a
    title. Returns the updated artwork dict; raises PixAIError on failure."""
    _check_read_only("edit an artwork on your PixAI account")
    inp = {}
    if media_id is not None:
        inp["mediaId"] = str(media_id)
    if title is not None:
        inp["title"] = title
    if tack_ids is not None:
        inp["tags"] = []
        inp["tackIds"] = list(tack_ids)
    if private is not None:
        inp["visibility"] = "PRIVATE" if private else "PUBLIC"
        inp["isPrivate"] = bool(private)
    if hide_prompts is not None:
        inp["hidePrompts"] = bool(hide_prompts)
    ex = dict(extra or {})
    if description is not None:
        ex["description"] = description
    if ex:
        inp["extra"] = ex
    if not inp:
        raise PixAIError("update_artwork: nothing to change")
    d = gql_mutate(session, _UPSERT_ARTWORK,
                   {"id": str(artwork_id), "input": inp}) or {}
    return d.get("upsertArtwork") or {}


def delete_artwork(session, artwork_id):
    """Unpublish/delete one artwork from your PixAI account (`deleteArtwork`).
    IRREVERSIBLE on their side; your local files and catalog row are untouched.
    Single attempt (gql_mutate) so a flaky network can never delete twice. Like
    deleteGenerationTask, success is the ABSENCE of an error, not the payload."""
    _check_read_only("delete an artwork from your PixAI account")
    gql_mutate(session, _DELETE_ARTWORK, {"id": str(artwork_id)})
    return True


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


def account_is_member(me):
    """Is there an ACTIVE PixAI membership on this account? True / False / None=unknown.

    MEASURED 2026-07-28 against the owner's deliberately-lapsed account: `membership` comes
    back as **null** the moment it expires, while `subscription` lingers as a historical
    record -- status "inactive", a past endAt, cancelAtPeriodEnd true. So membership's
    PRESENCE is the signal and subscription is not: reading `subscription.planId` would call
    a lapsed account premium forever. An active account carries membership{membershipId,
    tier, privilege} (tier 3 on the 2026-07-06 probe).

    Returns None when `me` is empty -- i.e. the account could not be read at all. Callers
    MUST fail OPEN on None: a network blip or a transient GraphQL error must never silently
    strip a paying member's entitlements mid-session. Only an explicit False gates anything,
    the same convention as the model-capability gate."""
    if not me:
        return None
    return bool(me.get("membership"))


_CREDIT_BALANCE_QUERY = """
query {
  me {
    id
    total: quotaAmount
    free: quotaAmount(currency: "free")
    paid: quotaAmount(currency: "paid")
  }
}
"""


def credit_balance(session):
    """Read the account's credit balance split Paid vs Free -- the same three numbers the
    site's own Membership & Credits page shows, where account_info()'s `quotaAmount` only
    ever surfaces the lump total. Returns {"total", "free", "paid"} (ints, or None on error).

    ** The mechanism, learned the hard way (2026-08-07): the split is `me { quotaAmount,
    quotaAmount(currency: "free"), quotaAmount(currency: "paid") }` -- aliased fields on
    `me`, with the currency codes being the bare strings "free"/"paid". The ORIGINAL query
    `user(id).{total,free,paid}` was invalid (PixAI: "Cannot query field total on type
    User") and always failed; a long probe missed the codes because `freeCredit`/`paidCredit`
    etc. all return null and introspection is disabled. The exact query was finally recovered
    from the site's own bundled operation AST (owner-supplied currency dump). Verified live:
    free 219,951 + paid 3,533,040 = total 3,752,991. ** Read-only; fails soft to all-None."""
    try:
        data = gql_adhoc(session, _CREDIT_BALANCE_QUERY, {}) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"total": None, "free": None, "paid": None}
    me = data.get("me") or {}
    return {"total": me.get("total"), "free": me.get("free"), "paid": me.get("paid")}


# PixAI's free-tier LoRAs-per-generation allowance. Their own generate panel prints it
# verbatim beside the LoRA section as "Free: 0/3   Max: 15 (crowned)", measured 2026-07-28
# on a lapsed account, and the owner independently confirmed 3 is his live cap. It is a
# CONSTANT here because `membership.privilege` -- where the paid cap lives -- is null for a
# non-member, so there is no field to read it from. If PixAI ever moves it, the symptom is a
# refused submit (LORA_NUM_EXCEEDED), not a silent overspend.
FREE_LORA_CAP = 3


def account_lora_cap(me):
    """LoRAs-per-generation this account may use. int, or None when genuinely unknown.

    Three cases, and the middle one is the bug this exists to fix:
      * `me` empty            -> None. The account could not be read; callers fail OPEN.
      * membership present    -> privilege.lora, else privilege.freeUserLora.
      * membership NULL       -> FREE_LORA_CAP. A non-member is not "unknown", it is the
                                 free tier -- and returning None here is what silently
                                 disabled the cap guard the moment the owner's membership
                                 lapsed, letting six LoRAs reach PixAI against a cap of
                                 three (LORA_NUM_EXCEEDED, reproduced 2026-07-28)."""
    if not me:
        return None
    priv = ((me.get("membership") or {}).get("privilege")) or {}
    cap = priv.get("lora")
    if cap is None:
        cap = priv.get("freeUserLora")
    if cap is None:
        return FREE_LORA_CAP if not me.get("membership") else None
    try:
        return int(cap)
    except (TypeError, ValueError):
        return None


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
    print("Account ID       : {}".format(me.get("id") or _client_of(session).user_id))
    print("Credits (balance): {}".format(credits))
    balance = credit_balance(session)
    if balance["free"] is not None or balance["paid"] is not None:
        print("  of which free  : {:,}".format(int(balance["free"] or 0)))
        print("  of which paid  : {:,}".format(int(balance["paid"] or 0)))
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
    return {"quota": me.get("quotaAmount"), "membership": mem.get("membershipId"),
            "free_credits": balance["free"], "paid_credits": balance["paid"]}


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
                # WHOLE, never truncated. It used to be sliced to 600 chars, which was
                # safe only while nothing rendered it. The brief is MARKDOWN upstream, so
                # a mid-token cut can sever a **bold** run or a [link](url) and leave the
                # renderer holding half a construct -- and the detail view now renders it.
                "description": _contest_title(r.get("description")),
                # The entry requirements, straight through (contest detail view):
                #   rules  -- [{type: 'required_model_ids', model_ids: [...]}
                #              | {type: 'required_lora_ids', lora_ids: [...]}]; [] = no restriction
                #   tack_name -- the tag an entry must carry (PixAI calls a tag a "tack")
                #   desc_url / result_url -- the contest's own rules + results documents,
                #     both frequently absent (null upstream -> "" here)
                "rules": [x for x in (r.get("rules") or []) if isinstance(x, dict)],
                "tack_name": r.get("proposedTackName") or "",
                "desc_url": r.get("descUrl") or "",
                "result_url": r.get("resultUrl") or "",
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


def _contest_rows(payload):
    """Flatten one contest-artwork payload into a list of plain dicts.

    Two shapes are accepted on purpose. The sibling `/contest/list` answers with a
    `{data:[...]}` envelope, while the per-user / winners routes are documented as bare
    JSON arrays and only the array form was seen live -- so guessing one shape would put
    an unverified assumption between the caller and the data. A dict payload yields its
    `data` list, a list payload is itself, anything else yields nothing.

    Each row is reduced to its SCALAR fields: the four the app actually uses (`id`,
    `authorId`, `mediaId`, `title`) plus whatever else came flat -- a winner's rank field,
    whose upstream name is unverified, therefore rides along untouched rather than being
    guessed at by name. Nested envelopes (the echoed `contest{}` object) are dropped."""
    if isinstance(payload, dict):
        rows = payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        flat = {str(k): v for k, v in r.items()
                if v is None or isinstance(v, (str, int, float, bool))}
        # ONE exception to the scalars-only rule, and it is an identity question rather
        # than a tidiness one. An entry row can carry its artwork as a nested object
        # (`{"id": <entry id>, "artwork": {"id": <artwork id>}}`), and dropping that
        # leaves only the ENTRY id -- a different value from the artwork id every other
        # path keys on. The dedupe set is grow-only, so one real entry then lands under
        # two keys and counts twice, forever. Lift the artwork id out to the flat name
        # the rest of the app already reads.
        if not flat.get("artworkId"):
            art = r.get("artwork")
            if isinstance(art, dict) and art.get("id"):
                flat["artworkId"] = str(art["id"])
        out.append(flat)
    return out


def contest_my_entries(session, slug, user_id):
    """One account's OWN entries in one contest, as plain dicts.

    `GET /v2/contest/{slug}/artwork/{userId}` -- the "have I entered, and how many times"
    read, without paging the contest's whole entry list. Read-only: browsing entries never
    spends and never changes the account, so no `_check_read_only` here.

    Raises PixAIError upward on a non-2xx (and ValueError on a malformed 200 body); every
    caller of this is a poll that fails soft at its own layer, which keeps the failure
    handling where the "what should a poll do about it" decision actually lives."""
    return _contest_rows(_rest_get(
        session, "/contest/%s/artwork/%s" % (slug, user_id)))


def contest_winners(session, slug):
    """The winners of one contest, as plain dicts. `GET /v2/contest/{slug}/winners`.

    Verified live: a still-running contest answers with an EMPTY JSON array rather than an
    error, and the list populates at the contest's `resultAt` -- so an empty result means
    "not decided yet", never "call failed". `authorId` identifies each winner; any rank
    field upstream sends is preserved as-is (see _contest_rows). Read-only, no spend."""
    return _contest_rows(_rest_get(session, "/contest/%s/winners" % slug))


def contest_artworks(session, slug, page=1):
    """One page of a contest's PUBLIC entries -- everyone's, not just this account's.
    `GET /v2/contest/{slug}/artwork` with `{"page": N, "sort": "newest"}` (page size is
    the server's, ~20). Read-only; feeds the detail view's entries preview, where the
    full browse is a link-out to pixai.art rather than a paging UI here.

    Returns the envelope shape `{data, totalCount, page, totalPage}` with `data`
    normalized by _contest_rows. A bare-array answer is tolerated the same way the
    per-user route's is (only the sibling /contest/list envelope was verified live): the
    rows are the array and the counts fall back to what was actually returned, so a
    caller never reads an invented total. Raises PixAIError upward on a non-2xx."""
    d = _rest_get(session, "/contest/%s/artwork" % slug,
                  params={"page": int(page or 1), "sort": "newest"})
    rows = _contest_rows(d)
    env = d if isinstance(d, dict) else {}

    def _int(key, fallback):
        try:
            return int(env.get(key) or fallback)
        except (TypeError, ValueError):
            return fallback
    return {"data": rows, "totalCount": _int("totalCount", len(rows)),
            "page": _int("page", int(page or 1)), "totalPage": _int("totalPage", 1)}


def contest_enter(session, slug, artwork_id):
    """Enter one ALREADY-PUBLISHED artwork into a contest. **ACCOUNT-MUTATING.**

    This is account-visible in the strongest sense: it puts the artwork into a PUBLIC
    contest under the owner's name, where everyone can see it, and the contract exposes no
    un-enter route. So it is gated by `_check_read_only` before the network call fires,
    exactly like submit_generation / submit_fixer / delete_task_gql / claim_reward, and it
    rides the single-attempt `_rest_post` with NO retry loop of its own -- a re-POST after
    a lost response would submit a second entry.

    `POST /v2/contest/{slug}/artwork` with `{"artworkId": ...}` -> the parsed response
    dict (`{"success": true}` upstream). Upstream refusals arrive as a PixAIError carrying
    the status and body: NOT_ELIGIBLE (e.g. the artwork was published before the contest
    opened), UNAUTHORIZED, INVALID_INPUT.

    THE ENTRY FEE IS UNMEASURED. The contract also declares an INSUFFICIENT_CREDITS error,
    so entering MAY cost credits -- but no entry has ever been submitted from here to find
    out, and the capture scope deliberately stopped short of firing one. Callers must
    present the cost as UNKNOWN; do not tell a user this is free."""
    _check_read_only("enter a PixAI contest")
    return _rest_post(session, "/contest/%s/artwork" % slug,
                      {"artworkId": str(artwork_id)})


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
    """GET a /v2 oRPC REST route. Returns parsed JSON. Raises PixAIError on non-2xx.

    THIN DELEGATE onto `PixAIClient.rest_get` -- the route road lives in the pixai_client
    section. Kept under this name because a dozen call sites hand it a `session`
    positionally and the suite patches it here (tests/conftest.py's `_no_live_card_network`
    is what makes the /v2 API offline by default)."""
    return _client_of(session).rest_get(path, params=params, timeout=timeout)


def _rest_post(session, path, body, timeout=60):
    """POST JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx.

    THIN DELEGATE onto `PixAIClient.rest_post`, which carries the no-retry-loop rule that
    keeps `submit_fixer` and `claim_reward` single-attempt."""
    return _client_of(session).rest_post(path, body, timeout=timeout)


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
    except (PixAIError, requests.RequestException, ValueError):
        # "Fails soft" has to mean every way this call can fail, not just the tidy one.
        # _rest_get only converts a non-2xx into a PixAIError -- a ConnectionError or a
        # read timeout comes straight out of the raw session.get, and a malformed 200 body
        # out of r.json() as a ValueError. Both used to escape, and the caller that felt it
        # is match_kaisuuken(enrich=True): its own try/except covers the /kaisuuken/check
        # POST but not this cross-reference, so an escape there broke the fail-soft /
        # raise_on_error contract every enrich caller relies on -- including the one inside
        # _apply_kaisuuken, mid --confirm, whose except only catches (PixAIError, ValueError).
        # An unreadable summary costs the card's model preference and its display name,
        # exactly as it already did when the failure happened to be a PixAIError.
        return []
    rows = data.get("kaisuukens")
    if rows is None:
        return []
    return [_normalize_kaisuuken(k) for k in rows]


def list_kaisuuken_logs(session, first=50, after=None):
    """Read the account's benefit-card USAGE history via GET /v2/kaisuuken/logs -- the
    per-redemption ledger, distinct from the held-count summary /v2/kaisuukens/summary gives
    (that one only has a live `count`; this one is the paper trail of every time a card was
    actually spent). Verified live 2026-08-02 against the account's own history.

    Each row: {record_id, template_name, category, task_type, task_id, action, credit_cost,
    created_at}. `action` is "consumed" or "refunded" -- PixAI hands a card back (a NEW record,
    same kaisuukenId, action=refunded) when the task it was attached to failed or was refused;
    a single card can cycle consumed->refunded->consumed again across different tasks, so
    record_id is not 1:1 with "one use". `credit_cost` is what the redemption would have cost
    in credits had no card covered it -- useful for a "cards have saved you N credits" total,
    never an actual charge (the whole point of the card is that it wasn't charged).

    Cursor-paginated (Relay style): pass a previous call's `end_cursor` as `after` to page
    forward; `has_next` says whether more exist. Read-only; fails soft on error (matching
    list_kaisuukens()'s contract) since a glitched read should never block a display."""
    try:
        params = {"first": int(first)}
        if after:
            params["after"] = str(after)
        data = _rest_get(session, "/kaisuuken/logs", params=params) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"logs": [], "has_next": False, "end_cursor": None}
    rows = data.get("data")
    if rows is None:
        return {"logs": [], "has_next": False, "end_cursor": None}
    page = data.get("pageInfo") or {}
    logs = [{
        "record_id": r.get("id") or "",
        "template_name": r.get("templateName") or "",
        "category": r.get("categoryCode") or "",
        "task_type": r.get("taskType") or "",
        "task_id": str(r.get("taskId") or ""),
        "action": r.get("action") or "",
        "credit_cost": r.get("creditCost"),
        "created_at": r.get("createdAt") or "",
    } for r in rows]
    return {"logs": logs, "has_next": bool(page.get("hasNextPage")), "end_cursor": page.get("endCursor")}


def kaisuuken_type_catalog(session, max_pages=25):
    """Page ALL the way back through list_kaisuuken_logs() to build a lifetime roster of
    every benefit-card TEMPLATE this account has ever redeemed or been refunded -- the "what
    types have I ever held" answer /v2/kaisuuken/summary can't give once a card type fully
    expires out of current holdings (verified 2026-08-02: Reference Pro Only and Edit Pro
    Only both fully cycled out of live holdings but still show up here going back ~a month).

    Caveat: this only catches types actually USED (consumed or refunded) at least once -- a
    card that expired untouched leaves no trace in this log, so it is a lower bound on
    "every card type ever granted", not an exact one.

    Capped at `max_pages` pages of 100 rows each as a politeness/safety bound -- an old
    account could otherwise page indefinitely. Returns what it found plus whether the cap
    was hit before the log ran out, so a caller can tell "that's everything" from "there's
    more, ask for more pages"."""
    catalog = {}
    cursor, pages, hit_cap = None, 0, False
    while pages < max_pages:
        page = list_kaisuuken_logs(session, first=100, after=cursor)
        for row in page["logs"]:
            name = row["template_name"] or "(unknown)"
            entry = catalog.setdefault(name, {
                "category": row["category"], "task_type": row["task_type"],
                "consumed": 0, "refunded": 0,
                "first_seen": row["created_at"], "last_seen": row["created_at"]})
            if row["action"] == "consumed":
                entry["consumed"] += 1
            elif row["action"] == "refunded":
                entry["refunded"] += 1
            ts = row["created_at"]
            if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
                entry["first_seen"] = ts
            if ts and (not entry["last_seen"] or ts > entry["last_seen"]):
                entry["last_seen"] = ts
        pages += 1
        if not page["has_next"] or not page["logs"]:
            break
        cursor = page["end_cursor"]
    else:
        hit_cap = True
    return {"templates": catalog, "pages_read": pages, "hit_page_cap": hit_cap}


# --- Coupons ("Credit Boost", extra-package-boosts) ---------------------------
# A reward type entirely SEPARATE from kaisuuken benefit cards, verified live 2026-08-02
# (owner: "coupons are for monthly events, one is live now"). A coupon is a percentage
# bonus applied to an "Extra Package" (credit-pack) purchase, not a free generation -- the
# naming of its own endpoint (extra-package-boosts) confirms the mechanic. Lives on the
# same oRPC /v2 REST surface as kaisuuken, but is its own resource, not a kaisuuken variant.

#: The site's own "My Coupons" top list (what you currently HOLD) vs its "View coupon
#: history" accordion (what's past) are the SAME endpoint, told apart only by `statuses` --
#: both CONFIRMED via live network capture 2026-08-02, resolving what the first pass here
#: left as an unconfirmed guess.
COUPON_STATUSES_ON_HAND = ("available", "locked")
COUPON_STATUSES_HISTORY = ("redeemed", "expired")


def list_extra_package_boosts(session, statuses=COUPON_STATUSES_ON_HAND, first=50, after=None):
    """Read the account's "Credit Boost" coupons via GET /v2/extra-package-boosts. Defaults
    to what you currently HOLD (COUPON_STATUSES_ON_HAND) -- the primary ask ("list what we
    have on hand", not just a spend history). Pass `statuses=COUPON_STATUSES_HISTORY` for
    the past (redeemed + expired) view instead; both share this one endpoint.

    Each row: {code, boost_percent, status, issued_by, note, locked_for_order_id,
    available_since, available_until, created_at}. `locked_for_order_id` ties a redeemed
    coupon to the specific purchase order it boosted -- the same link behind the credit log's
    "Extra Package" rows carrying a matching reason tag (see the credit-ledger work).
    Cursor-paginated (Relay style, same shape as list_kaisuuken_logs); read-only, fails soft
    on error."""
    try:
        params = {"first": int(first)}
        for i, s in enumerate(statuses):
            params["status[{}]".format(i)] = s
        if after:
            params["after"] = str(after)
        data = _rest_get(session, "/extra-package-boosts", params=params) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"coupons": [], "has_next": False, "end_cursor": None}
    rows = data.get("data")
    if rows is None:
        return {"coupons": [], "has_next": False, "end_cursor": None}
    page = data.get("pageInfo") or {}
    coupons = [{
        "code": r.get("code") or "",
        "boost_percent": r.get("boostRatePercentage"),
        "status": r.get("status") or "",
        "issued_by": r.get("issuedBy") or "",
        "note": r.get("note") or "",
        "locked_for_order_id": r.get("lockedForOrderId") or "",
        "available_since": r.get("availableSince") or "",
        "available_until": r.get("availableUntil") or "",
        "created_at": r.get("createdAt") or "",
    } for r in rows]
    return {"coupons": coupons, "has_next": bool(page.get("hasNextPage")),
            "end_cursor": page.get("endCursor")}


# --- Credit Ledger (full spend/purchase/gift history) -------------------------
# The REAL "spend history" behind the site's Membership & Credits -> Credit log table --
# a much bigger surface than either kaisuuken_logs or extra_package_boosts, and NOT the
# same endpoint as either: rides ad-hoc GraphQL `me.quotaLogs`, not the /v2 REST surface.
#
# ** 2026-08-07 fix: query `me`, NOT `user(id: $userId)`. ** The original used
# `user(id).quotaLogs` and always came back EMPTY -- quotaLogs is private financial data
# that PixAI exposes ONLY on `me`, never on the public `user(id)` type, even for your own
# id (no error, just an empty connection -- which is why the "verified live 2026-08-02"
# claim slipped through). Confirmed live against the real account 2026-08-07: `me.quotaLogs`
# returns the real ledger (daily claims, event gifts, spend...) with working backward
# pagination; `user(id).quotaLogs` returns nothing. The `reason`/`logReason` server-side
# filter is dropped -- it isn't offered on the `me` connection and nothing in the app sends
# it (the modal has no reason filter); re-add via a probed arg name if a filter UI is built.
_QUOTA_LOG_QUERY = """
query($last: Int!, $before: String) {
  me {
    id
    quotaLogs(last: $last, before: $before) {
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
      edges {
        cursor
        node { refId userId amount type extra createdAt updatedAt }
      }
    }
  }
}
"""

# `type` enum values CONFIRMED against real account data 2026-08-02 (one entry each,
# sampled from a mixed page -- NOT exhaustive). PixAI's own filter dropdown offers ~25
# distinct labels across 5 categories (Credits Spending / Purchased Credits / Earned
# Rewards / Grants & Refunds / Special Rewards); only these four have a confirmed enum so
# far. An unmapped type still comes through list_credit_log() (label falls back to the raw
# enum string) -- this dict is a display nicety, not a gate.
CREDIT_LOG_REASONS = {
    "task_cost": "Generation Task",
    "daily": "Daily Claim",
    "event_gift": "Event Gift",
    "extra_package": "Extra Package",
}


def list_credit_log(session, last=50, before=None, reason=None):
    """Read the account's full credit transaction ledger via ad-hoc GraphQL
    `user(id).quotaLogs` -- every credit gain AND loss (purchases, daily claims, event
    gifts, generation spend, refunds, ...), not just generation cost. Distinct from
    list_kaisuuken_logs()/list_extra_package_boosts(), which are their own narrower REST
    endpoints for card/coupon-specific history.

    Each row: {ref_id, amount, type, label, extra, created_at, updated_at}. `amount` is
    signed (negative = spend, positive = gain). `type` is the raw enum (see
    CREDIT_LOG_REASONS for the ones confirmed so far); `label` is the friendly name when
    known, else the raw enum. `extra` is an opaque per-type payload -- e.g. the coupon-boost
    "🎫 +15%" reason tag seen on an extra_package row in the site's own UI must live in
    here, but no populated sample was captured to confirm its structure, so it is passed
    through raw rather than parsed.

    Backward-paginated (last/before over hasPreviousPage/startCursor), matching this
    codebase's OWN established connection style for history listings (see
    page_variables()) -- the opposite direction from kaisuuken/coupons' forward
    first/after. Pass a previous call's `next_cursor` as `before` to page further into the
    past. Optional `reason` filters server-side to one raw type, mirroring the site's own
    per-category filter dropdown. Read-only; fails soft on error, matching every other
    reader in this module."""
    try:
        variables = {"last": int(last)}
        if before:
            variables["before"] = str(before)
        # `reason` is accepted for API compatibility but no longer sent -- the `me`
        # connection doesn't take it (see _QUOTA_LOG_QUERY's note). Kept as a param so the
        # route/CLI signatures don't change; a filter UI would need a probed arg name.
        _ = reason
        data = gql_adhoc(session, _QUOTA_LOG_QUERY, variables) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"entries": [], "has_more": False, "next_cursor": None}
    quota_logs = (data.get("me") or {}).get("quotaLogs") or {}
    edges = quota_logs.get("edges")
    if edges is None:
        return {"entries": [], "has_more": False, "next_cursor": None}
    page = quota_logs.get("pageInfo") or {}
    entries = []
    for e in edges:
        n = e.get("node") or {}
        t = n.get("type") or ""
        entries.append({
            "ref_id": n.get("refId") or "",
            "amount": n.get("amount"),
            "type": t,
            "label": CREDIT_LOG_REASONS.get(t, t),
            "extra": n.get("extra"),
            "created_at": n.get("createdAt") or "",
            "updated_at": n.get("updatedAt") or "",
        })
    return {"entries": entries, "has_more": bool(page.get("hasPreviousPage")),
            "next_cursor": page.get("startCursor")}


def _target_model_id(parameters):
    """The model id a generation targets, wherever it lives: top-level `modelId` for
    plain gen + video, or `chat.modelId` for an instruct edit. Empty string if none."""
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("modelId")
               or (parameters.get("chat") or {}).get("modelId") or "").strip()


# The /kaisuuken/check protocol version the site sends. 1 (or omitted) = single-ticket-only
# matcher; 2 = multi-ticket, returns consumeAmount. Named so a future bump is one edit.
_KAISUUKEN_CHECK_VERSION = 2


def match_kaisuuken(session, parameters, enrich=False, raise_on_error=False):
    """POST /v2/kaisuuken/check (protocol version 2, see _KAISUUKEN_CHECK_VERSION) with a
    generation's `parameters` and return the best matching TICKET as
      {id, expiresAt, templateId, total, consumeAmount, covered, balance_unknown, name?}
    -- or None when no card matches. `total` = tickets HELD on that template (int, or None
    when the balance could not be read); `consumeAmount` = tickets this job COSTS (>=1);
    `covered` = the ONE coverage verdict every caller reads via card_covers(); `balance_unknown`
    tells a not-covered result apart from a genuinely short one so surfaces word it honestly.
    Selection is coverage-first, then model preference (enrich), then nearest expiry.
    READ-ONLY: this only *checks*; the card is consumed later, when the task is submitted with
    the returned id attached. Fails soft (returns None) by default -- fine for every
    read-only/preview/display caller, where a glitched check should not block the UI.

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
        # `version: 2` is load-bearing (issue #15, live-verified 2026-08-16). Without it PixAI
        # runs its v1 matcher, which knows only single-ticket cards and answers `matches: []`
        # for any i2vPro duration >= 10 -- so every >5s video went out card-less at full price
        # for as long as this app existed. v2 (the site's own useKaisuukenMatch shape) returns
        # the multi-ticket match plus `consumeAmount` = tickets this job COSTS. NOTE the server
        # does NOT filter by balance: a 15s job comes back matched even when held < needed, so
        # coverage is decided HERE (see `covered` below), the one place every caller reads it.
        data = _rest_post(session, "/kaisuuken/check",
                          {"type": "generation-task", "parameters": parameters,
                           "version": _KAISUUKEN_CHECK_VERSION}) or {}
    except (PixAIError, ValueError):
        if raise_on_error:
            raise
        return None
    matches = data.get("matches") or []
    if not matches:
        return None
    by_tid = {c.get("template_id"): c for c in list_kaisuukens(session)} if enrich else {}
    # Per-template need/held/covered, computed ONCE per template (not re-derived per ticket
    # inside the expiry loop) and parsed defensively: a null/0/"2" consumeAmount must never
    # collapse into "costs nothing" (0 -> always covered) or a TypeError inside the spend
    # path. Absent consumeAmount is the v1 semantic: one job, one ticket.
    #
    # `held` comes from the match's OWN `total`, else (when enriched) the summary count for
    # that template, else None = UNKNOWN. It deliberately does NOT fall back to the response's
    # top-level `total`: that scalar is the SUM across all matched templates (the repo's own
    # _TWO_CARDS fixture: 17 + 5 = 22), so using it credited every template with the whole
    # pool, let a 5-held template read as covering a 6-ticket job, and -- because both then
    # landed in covered_pool -- let nearest-expiry pick the SHORT one over the 17-held one,
    # defeating the coverage-first ordering below (review 2026-08-16, reproduced).
    def _facts(mt):
        try:
            need = int(mt.get("consumeAmount") or 1)
        except (TypeError, ValueError):
            need = 1
        need = max(need, 1)
        held = None
        raw_held = mt.get("total")
        if raw_held is None and enrich:               # summary count as a second opinion
            raw_held = (by_tid.get(mt.get("templateId")) or {}).get("count")
        if raw_held is not None:
            try:
                held = int(raw_held)
            except (TypeError, ValueError):
                held = None
        # Unknown balance is a distinct state, not "short": for a 1-ticket job assume covered
        # (not attaching when actually covered loses real credits, and 1 ticket is the v1
        # world that always worked). For ANY multi-ticket job fail CLOSED -- the general rule,
        # not a video special-case, so a future multi-ticket non-video card gets the same
        # protection. Being wrong here costs the full clip price either way; fail-closed is
        # chosen over an unverified under-funded attach, and callers word it as UNKNOWN
        # ("couldn't read your balance"), never as "not enough" (which asserts an unread fact).
        unknown = held is None
        covered = (need <= 1) if unknown else (held >= need)
        return need, held, covered, unknown

    facts = {id(mt): _facts(mt) for mt in matches}
    # (A0) Coverage FIRST, then preference, then nearest expiry: a short template (2 held,
    # needs 3) must never shadow one that covers (9 held) just because it expires sooner --
    # the old order (nearest-expiry across the whole pool) did exactly that. If NO template
    # covers, fall back to the full pool so the honest short message can still name a card.
    covered_pool = [mt for mt in matches if facts[id(mt)][2]]
    pool = covered_pool or matches
    # (A) When several cards are eligible, prefer the one whose model IS this generation's
    # model; fall back to the full set if none match (or we didn't enrich).
    want = _target_model_id(parameters)
    if enrich and want and len(pool) > 1:
        preferred = [mt for mt in pool
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
                need, held, covered, unknown = facts[id(mt)]
                best = {"id": kid, "expiresAt": k.get("expiresAt"),
                        "templateId": mt.get("templateId"), "total": held,
                        "consumeAmount": need, "covered": covered,
                        "balance_unknown": unknown,
                        "_exp": exp}
    if best:
        best.pop("_exp", None)
        if enrich:                                     # (B) name the card for honest UI
            best["name"] = (by_tid.get(best["templateId"]) or {}).get("name")
    return best


def card_covers(best):
    """THE coverage predicate every caller reads -- CLI preview, _apply_kaisuuken, /api/price.
    True iff a card matched AND it covers the whole job (held >= consumeAmount). Defaults to
    covered when the result predates the field (older test stubs / v1 responses), which is the
    v1 one-job-one-ticket semantic. One home so the three surfaces can never disagree -- the
    CLI preview said FREE while the apply path charged full price precisely because each
    derived 'free' on its own (issue #15)."""
    return bool(best) and bool(best.get("covered", True))


def _card_uses_note(best):
    """The ONE 'uses N of H cards; ' phrase for a COVERED multi-ticket job (empty string for a
    1-ticket job, so an ordinary image reads 'covers this' on every surface exactly as before).
    Shared by the CLI preview and the spend log so they can't drift (they did)."""
    b = best or {}
    try:
        need = int(b.get("consumeAmount") or 1)
    except (TypeError, ValueError):
        need = 1
    if need <= 1:
        return ""
    held = b.get("total")
    return "uses {} of {} cards; ".format(need, held if held is not None else "?")


def card_short_note(best, cost=None):
    """The one honest sentence for the NOT-COVERED-but-matched case. Wording is deliberate:
    nothing is attached and the FULL price is charged, so it must never read as partial
    application ('covers 2 of 3, the rest costs N' was rejected in review for exactly that).
    Two sub-cases, told apart honestly (review 2026-08-16):
      SHORT   -- the balance was read and it is < needed: "you hold 2 of the 3 ... not enough".
      UNKNOWN -- the balance could NOT be read (no per-template total, no summary count) and the
                 job needs >1 ticket, so we fail closed. This must NOT say "not enough" -- that
                 asserts a fact nobody read; a user holding 9 tickets would be told they hold
                 too few. It says the balance couldn't be read and no card will be attached.
    `cost` = the full credit price if known."""
    b = best or {}
    need = int(b.get("consumeAmount") or 1)
    held = b.get("total")
    name = b.get("name") or "card"
    tail = (" -- this costs the full ~{:,} credits".format(int(cost)) if cost is not None
            else " -- this costs the full credit price")
    if b.get("balance_unknown") or held is None:
        return ("couldn't read how many {} tickets you hold (this needs {}), so no card will "
                "be attached".format(name, need) + tail)
    return ("you hold {} of the {} {} tickets this needs -- not enough, so no card is used"
            .format(held, need, name) + tail)


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
    # Same architecture gate the submit applies, so the badge prices the shape that will be
    # sent (quote == charge for DiT/SDXL). Local reassignment only -- the caller's params
    # object (which price() also hands to match_kaisuuken) is left untouched.
    params = _gate_params_for_model(session, params)
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
    except (PixAIError, requests.RequestException, ValueError):
        # "Fails soft" has to mean EVERY way this call can fail (list_kaisuukens' own rule):
        # _rest_get only converts a non-2xx into a PixAIError; a ConnectionError / ReadTimeout
        # comes straight out of the raw session.get. This is called from _apply_kaisuuken's
        # SHORT branch, INSIDE the spend path, purely to put a number in a sentence -- a network
        # blip there used to escape and abort a confirmed submit with a raw traceback.
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
class ClaimsResult(list):
    """A claim list that also carries WHY it is empty, when it is empty for a bad reason.

    `list_claims` fails soft to an empty list on purpose and must keep doing so: the
    gallery's account panels call it on every render and must not 500 because PixAI
    hiccuped. But "the fetch failed" and "you have nothing to claim" are different facts,
    and `run_claims` printed "No claimable rewards found" for both -- so a transient 5xx
    left a REAL, ready daily-credit reward unclaimed while telling the user, in so many
    words, that there was nothing there (M05, 2026-07-27).

    A list subclass rather than a (rows, error) tuple because every existing call site --
    `for c in core.list_claims(session)` in two gallery routes, `if not rewards`, and
    `list_claims(...) == []` in the tests -- keeps working byte-for-byte unchanged, and a
    caller that substitutes a plain list (as the run_claims tests do) simply reports no
    error. Read `.error` via getattr with a default for exactly that reason."""

    def __init__(self, rows=(), error=""):
        super().__init__(rows)
        self.error = error


def list_claims(session):
    """Read the account's claimable rewards via GET /v2/claim (daily credits, agent
    stamina). Read-only; fails soft (returns an empty ClaimsResult). Each row: {id, amount,
    canClaim, claimedAt, nextClaimableTime}.

    The empty-on-failure return carries `.error` so a caller reporting to a human can say
    "the fetch failed" instead of "you have nothing to claim" -- see ClaimsResult."""
    try:
        data = _rest_get(session, "/claim")
    except PixAIError as e:
        return ClaimsResult((), str(e))
    return ClaimsResult(data if isinstance(data, list) else ())


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
    # An empty list from a FAILED fetch is not the same fact as an empty list from an
    # account with nothing to claim, and this is the one place a human reads the answer.
    # Reporting both as "No claimable rewards found" is how a ready reward went unclaimed
    # after a transient 5xx, with nothing on screen to suggest retrying (M05, 2026-07-27).
    # getattr with a default: a caller/test may hand back a plain list, which carries none.
    err = getattr(rewards, "error", "") or ""
    if err:
        print("Could NOT read your claimable rewards: {}".format(err[:200]))
        print("This is a failed request, not an empty account -- a ready reward may still "
              "be waiting. Nothing was claimed; re-run --claims in a minute.")
        return {"rewards": 0, "error": err[:200]}
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
    A card is attached ONLY when `card_covers(best)` -- a match that is SHORT (multi-ticket
    video, held < consumeAmount) attaches nothing, prints `card_short_note`, and spends the
    full price, exactly as the site does (owner ruling, issue #15).

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
    # The auto-match /v2/kaisuuken/check must run under the SAME identity that will create.
    # A card reserved on the API-key session does not necessarily apply to a mirror (web-JWT)
    # create, so a generation previewed as FREE could be billed in real credits (review F2/F8).
    # _session_for_create is a pass-through when the mirror is off, and refuses (raises) before
    # any spend when the mirror is on but unavailable (F5).
    session = _session_for_create(session)
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
    if best and best.get("id") and card_covers(best):
        # ONE singular kaisuukenId, even for a multi-ticket job (site-verified): the server
        # debits consumeAmount tickets off that one template itself. Never a list.
        params["kaisuukenId"] = best["id"]
        print("  free card matches ({}) -> attaching it; {}this costs 0 credits "
              "(card expires {}).".format(best.get("name") or "card", _card_uses_note(best),
                                          (best.get("expiresAt") or "never")[:10]))
        return best["id"]
    if best and best.get("id"):
        # SHORT: matched, but held < needed. Owner ruling (issue #15): SPEND, matching the
        # site -- attach nothing, say plainly that the FULL price is charged, then proceed.
        # No refusal here; the honesty is the obligation. The cost lookup is diagnostic only
        # -- it exists to put a number in the sentence -- so it is wrapped so that NOTHING it
        # can raise ever aborts the submit it describes (price_task fails soft too, but this
        # is the one place a cosmetic lookup sits inside the spend path, so it gets its own
        # belt; review 2026-08-16). A missing number just drops from the wording.
        try:
            cost = price_task(session, params)
        except Exception:                                  # noqa: BLE001 -- diagnostic, never fatal
            cost = None
        print("  " + card_short_note(best, cost) + ".")
        return ""
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
        # An explicit id is FORCED: it is attached as given, with no coverage check on its
        # template (review 2026-08-16 -- this used to promise "-> 0 credits" unconditionally,
        # which for a multi-ticket clip on an under-funded template is a paid clip shown as
        # free). Say plainly what is and isn't guaranteed.
        print("A free card (--kaisuuken-id) will be attached on --confirm as given. Coverage "
              "is NOT checked for a forced id: if that card's template holds fewer tickets "
              "than this job needs, PixAI charges the full credit price (or refuses). Drop "
              "--kaisuuken-id to let the auto-match pick a card that covers.")
        return
    try:
        session = _make_session(getattr(args, "token", None))
        # enrich=True, same as _apply_kaisuuken: the preview must name the SAME template
        # the spend will pick (model preference only applies when enriched), or the two
        # could disagree about which card -- and whether it covers.
        best = match_kaisuuken(session, params, enrich=True)
        price = price_task(session, params)
    except Exception:
        # Offline / no key: the preview is still valid, but a spend page must not go SILENT
        # about cost (the web badge's "couldn't verify" rule). This used to just return,
        # which -- once the stale hardcoded reference price above it was removed -- would
        # have left a video preview with no cost line at all.
        print("Couldn't verify the cost or free-card match right now (offline or no key) -- "
              "with --confirm this MAY spend credits.")
        return
    # Three honest branches off the ONE predicate (card_covers). Before issue #15 this said
    # FREE on any match -- with version:2 a short 15s clip now matches, and that would have
    # promised FREE right before --confirm spent the full price.
    if card_covers(best) and best.get("id"):
        saved = " (saves {})".format(_fmt(price)) if price else ""
        # "uses N of H cards" only when the job costs MORE than one ticket -- the same gate the
        # web badge applies, so a 1-ticket image reads the same everywhere ("covers this",
        # not "uses 1 of 16 cards"; review: CLI/badge wording drift).
        uses = _card_uses_note(best)
        print("FREE: {} covers this -- {}with --confirm it costs 0 credits{} "
              "(card expires {}).".format(best.get("name") or "a matching card", uses, saved,
                                          (best.get("expiresAt") or "never")[:10]))
    elif best and best.get("id"):
        print("NOT free -- " + card_short_note(best, price) + " with --confirm.")
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
          "matching card makes that generation cost 0 credits (use --no-card to opt out).\n"
          "Videos can need MORE THAN ONE ticket (a 15s clip needs 3): if you hold fewer than\n"
          "the job needs, no card is used and it costs the FULL credit price.\n")
    total = 0
    for c in cards:
        total += int(c.get("count") or 0)
        model = c["model_version_id"] or ("/".join(c["task_types"]) or "-")
        print("  {:>3}x  {:<22} {:<13} model={:<20} exp {}".format(
            c.get("count") or 0, c.get("name"), "[" + c["category"] + "]",
            model, str(c["expires"])[:10]))
    # "tickets", not "generations": a video ticket is one per 5 seconds, so 16 video tickets
    # is 5 fifteen-second clips, not 16 (the header above says so; this line used to contradict it).
    print("\n{} tickets total (one image or 5s of video each). The matching card is attached\n"
          "automatically when you generate on its model (nearest-expiry first):".format(total))
    print("  Tsubaki.2 card  -> --generate         (default model already matches)")
    print("  Edit Pro card   -> --edit-image       (default model already matches)")
    print("  Reference Pro   -> --generate --model 1948514378441961474")
    return {"cards": len(cards), "total": total}


def run_card_history(args):
    """Print the account's benefit-card usage history (list_kaisuuken_logs) -- the paper
    trail /v2/kaisuuken/summary can't show: every past redemption/refund, the task it was
    attached to, and when. Read-only. Pass --card-history-all to page all the way back and
    print the lifetime card-type catalog instead (kaisuuken_type_catalog) -- slower, several
    requests, but answers "what card types have I ever held" once a type cycles out of
    current holdings."""
    session = _make_session(getattr(args, "token", None))
    if getattr(args, "card_history_all", False):
        result = kaisuuken_type_catalog(session)
        templates = result["templates"]
        if not templates:
            print("No benefit-card history found (read-only; nothing was spent).")
            return {"templates": 0}
        print("Every benefit-card TYPE this account has ever used, across {} page(s){}:\n".format(
            result["pages_read"],
            " (stopped at the page cap -- there may be more)" if result["hit_page_cap"] else ""))
        for name, info in sorted(templates.items(), key=lambda kv: kv[1]["last_seen"], reverse=True):
            print("  {:<22} [{:<11}] consumed={:<3} refunded={:<3} last used {}".format(
                name, info["category"] or "-", info["consumed"], info["refunded"],
                str(info["last_seen"])[:10]))
        return {"templates": len(templates)}
    page = list_kaisuuken_logs(session, first=int(getattr(args, "card_history_count", 0) or 20))
    logs = page["logs"]
    if not logs:
        print("No benefit-card history found (read-only; nothing was spent).")
        return {"logs": 0}
    print("Recent benefit-card usage (most recent first):\n")
    for row in logs:
        print("  {:<22} {:<9} task {:<20} {}".format(
            row["template_name"], row["action"], row["task_id"],
            str(row["created_at"])[:19].replace("T", " ")))
    if page["has_next"]:
        print("\n...more exist -- pass --card-history-all to page through the full history.")
    return {"logs": len(logs)}


def run_coupons(args):
    """Print the account's "Credit Boost" coupons (list_extra_package_boosts) -- a reward
    type separate from benefit cards: a percentage bonus on an Extra Package (credit-pack)
    purchase, tied to promotional events. Defaults to what you currently HOLD (the primary
    ask -- on-hand inventory, not just a spend history); pass --coupons-history for the past
    (redeemed + expired) view instead. Read-only."""
    session = _make_session(getattr(args, "token", None))
    history = getattr(args, "coupons_history", False)
    statuses = COUPON_STATUSES_HISTORY if history else COUPON_STATUSES_ON_HAND
    page = list_extra_package_boosts(session, statuses=statuses)
    coupons = page["coupons"]
    if not coupons:
        print("No {} coupons found (read-only; nothing was spent).".format(
            "past" if history else "currently-held"))
        return {"coupons": 0}
    print("Credit Boost coupons ({}):\n".format(
        "redeemed + expired history" if history else "currently held"))
    for c in coupons:
        print("  +{}%  {:<10} issued by {:<8} available {} -> {}".format(
            c["boost_percent"], c["status"], c["issued_by"],
            str(c["available_since"])[:10], str(c["available_until"])[:10]))
    if page["has_next"]:
        print("\n...more exist than shown here.")
    return {"coupons": len(coupons)}


def run_credit_log(args):
    """Print the account's full credit transaction ledger (list_credit_log) -- the real
    spend/purchase/gift history behind Membership & Credits -> Credit log, not just
    generation cost. Read-only. Pass --credit-log-reason to filter to one raw type (see
    CREDIT_LOG_REASONS for the ones with a confirmed friendly label) or --credit-log-before
    <cursor> to page further into the past."""
    session = _make_session(getattr(args, "token", None))
    page = list_credit_log(session, last=int(getattr(args, "credit_log_count", 0) or 30),
                            before=getattr(args, "credit_log_before", "") or None,
                            reason=getattr(args, "credit_log_reason", "") or None)
    entries = page["entries"]
    if not entries:
        print("No credit log entries found (read-only; nothing was spent).")
        return {"entries": 0}
    print("Credit log (most recent first):\n")
    for e in entries:
        amount = e["amount"] or 0
        sign = "+" if amount >= 0 else ""
        print("  {}{:<10,} {:<20} {}".format(
            sign, amount, e["label"], str(e["created_at"])[:19].replace("T", " ")))
    if page["has_more"]:
        print("\n...more exist further back -- pass --credit-log-before {} to page.".format(
            page["next_cursor"]))
    return {"entries": len(entries)}


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
            getattr(args, "page_size", 250) or 250,
            _client_of(session).user_id, before)))
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


class DiskCounts(tuple):
    """(originals_count, originals_bytes, thumbnail_count), with the TRASH carried alongside.

    A real 3-tuple, so every `n, b, thumbs = _count_backup_images(out)` call site keeps
    unpacking exactly as it always did; the `_deleted/` totals ride as attributes because a
    fourth slot would have broken that contract. Same trick, and the same reason, as
    ClaimsResult above: the caller that wants the extra fact can ask for it, and the ones
    that don't are untouched.

    Why the extra fact exists at all: quarantined files were simply DROPPED from the scan
    (M06's fix), and dropping them silently would trade one wrong number for another --
    'Image files on disk' would stop matching what `du` says about the folder, with nothing
    on screen explaining the gap. --catalog-stats is the command the wiki points at for
    deciding what to clean up, and 'N files are already in the trash, purge to reclaim X' is
    the single most actionable line that scan can produce."""

    def __new__(cls, originals, originals_bytes, thumbs, trashed=0, trashed_bytes=0):
        self = super().__new__(cls, (originals, originals_bytes, thumbs))
        self.trashed = trashed
        self.trashed_bytes = trashed_bytes
        return self


def _count_backup_images(out):
    """Count the ORIGINAL image files on disk, split from preview thumbnails. The naive
    rglob-for-_IMAGE_EXTS double-counts because gallery/thumbs/<id>.jpg is one .jpg per image --
    which made 'files on disk' look ~2x the catalog. Excludes gallery/ (thumbs), _duplicates/
    (quarantined) and _deleted/ (the soft-delete quarantine). Returns a DiskCounts:
    (originals_count, originals_bytes, thumbnail_count) plus .trashed / .trashed_bytes.

    `_deleted/` was NOT excluded until M06 (2026-07-27), while run_download's own disk
    scanner in this file has excluded all three for longer (B11, audit 2026-07-21). Soft-
    deleted images are still real files pending a purge, so counting them as part of the
    active library inflated exactly the number a user reads before deciding what to delete --
    on the screen the wiki's 'Reclaiming disk space' section sends them to. They are now
    reported SEPARATELY rather than dropped, so the total still accounts for the whole
    folder."""
    out = Path(out)
    # The one walker that does NOT want the quarantine trees pruned -- it counts
    # them into separate columns instead of dropping them, so it asks for
    # `exclude=()` and splits on the entry's own top-level folder against the
    # shared dirnames. Case-normalized because the old `dir in p.parents` test was
    # (Path comparison is case-insensitive on Windows).
    _norm = os.path.normcase
    _gallery, _deleted, _dupes = (_norm(GALLERY_DIRNAME), _norm(DELETED_DIRNAME),
                                  _norm(DUPLICATES_DIRNAME))
    n = b = thumbs = trashed = trashed_bytes = 0
    for e in scan_library(out, kinds=("image",), exclude=()):
        top = _norm(e.rel.parts[0]) if len(e.rel.parts) > 1 else ""
        if top == _gallery:
            thumbs += 1
        elif top == _deleted:
            trashed += 1
            trashed_bytes += e.size or 0
        elif top == _dupes:
            pass                       # quarantined duplicates: neither live nor trash
        else:
            n += 1
            b += e.size or 0
    return DiskCounts(n, b, thumbs, trashed, trashed_bytes)


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
    counts = _count_backup_images(out)
    disk_count, disk_bytes, thumb_count = counts
    if disk_count:
        print("Image files on disk : {}  ({})".format(disk_count, _format_size(disk_bytes)))
    if thumb_count:
        print("  + {} preview thumbnails (gallery/thumbs, not originals)".format(thumb_count))
    # The trash is real disk space that is NOT part of the library, and this screen is where
    # a user decides what to reclaim -- so it is named and costed rather than folded into the
    # library total (which is what it used to be) or dropped without a word (M06).
    if counts.trashed:
        print("  + {} soft-deleted in {}/ ({}) -- purge in the gallery's Trash to reclaim"
              .format(counts.trashed, DELETED_DIRNAME, _format_size(counts.trashed_bytes)))


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


class _DefaultDelay(float):
    """The argparse DEFAULT for `--delay`, tagged so "nobody said anything" can be told from
    "the user asked for this".

    A plain float cannot answer that question. `args.delay == 0.4` is true both when the flag
    was never typed and when it was typed as `--delay 0.4`, and `parser.get_default("delay")`
    only re-derives the same 0.4 -- so any comparison-based test silently overrides a
    deliberate choice that happens to match the shipped default. argparse runs `type=float`
    over a value it took from the COMMAND LINE and leaves the `default=` object untouched
    otherwise, so the tag survives exactly when the user was silent, which is the fact we
    need. A float subclass rather than a None-and-fill-in-later default because `args.delay`
    is read as a number in a dozen places (`time.sleep(args.delay)`, the `{:g}` banner, every
    `_parallel_map(delay=...)` call); every one of them keeps working unchanged.

    Only the parallel download stage asks -- see run_download. Everything else honours
    --delay's default exactly as it always has."""
    __slots__ = ()


DEFAULT_DELAY = _DefaultDelay(0.4)


def _delay_was_chosen(args):
    """True when `--delay` was actually typed (or a caller deliberately set one).

    A synthesized args namespace -- the tests, and any in-process caller that builds one --
    carries a plain float, which reads as a deliberate choice. That is the right default for
    a caller that went to the trouble of naming a delay; the one caller that must NOT be
    re-paced, the Control Panel's Sync job, reaches run_download by spawning the CLI with
    `--workers N` and no `--delay` at all, so it comes through argparse and lands on the
    sentinel. A namespace with no `delay` at all named nothing either, so it reads as not
    chosen -- answering True there would send the caller straight into an AttributeError
    reaching for the value it just claimed existed."""
    d = getattr(args, "delay", None)
    return d is not None and not isinstance(d, _DefaultDelay)


def _pace_gate(delay, *, clock=None, sleep=None):
    """Return a zero-arg callable that blocks until the caller owns the next request slot.

    One global slot at a time: each caller reads the next free slot, waits for it, and books
    the one after it, so a WHOLE thread pool starts at most one request per `delay` seconds
    no matter how many threads are in it. The obvious alternative -- sleeping `delay` inside
    each worker -- is not the same thing and is not enough: it still bursts at
    workers x rate, which is exactly the impoliteness the flag was passed to prevent.

    A falsy `delay` returns a no-op, so a caller can install the gate unconditionally and pay
    nothing (not even a lock acquisition) when the user asked for no pacing.

    Lifted out of _parallel_map's inner closure on 2026-07-27, when run_download's own inline
    pool -- the DEFAULT `--workers 4` path, and the highest-traffic code in the whole tool --
    turned out to apply no pacing at all to its per-image resolve/download calls. The fix for
    that must not be a second, subtly different copy of this clock: two pacing
    implementations drift, and the one that drifts is the one nobody is looking at.

    NOTE that run_download installs this gate only when the user EXPLICITLY passed --delay;
    a defaulted --delay gets `_pace_gate(0)`, i.e. the no-op. _parallel_map's own callers are
    unaffected and pace as they always did. Read run_download's comment before assuming a
    default backup is throttled by this -- it is not.

    `clock`/`sleep` are injectable for deterministic tests only: the pacing unit tests drive
    the gate with a frozen clock and a recording sleep so they assert on the slots BOOKED,
    not on real wall-clock gaps (which measured scheduling jitter and flaked under load).
    Production passes neither and resolves `time.monotonic`/`time.sleep` at call time, so the
    behaviour -- including anything that monkeypatches `core.time` -- is exactly as before.
    """
    if not delay:
        return lambda: None
    gate = threading.Lock()
    next_start = [0.0]

    def _wait():
        with gate:
            now = (clock or time.monotonic)()
            wait = max(0.0, next_start[0] - now)
            next_start[0] = max(now, next_start[0]) + delay
        if wait:
            (sleep or time.sleep)(wait)

    return _wait


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
    pace = _pace_gate(delay)   # one global slot per item -- see _pace_gate

    def _paced(it):
        pace()
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


# How many completed tasks between catalog flushes in run_backfill_full_meta. Small enough that
# an interrupted 36k-image run loses at most this many tasks of work (~1-2 min at normal pace),
# large enough that the flush I/O stays a rounding error next to the getTaskById fetch time.
_BACKFILL_CHECKPOINT_TASKS = 500


def run_backfill_full_meta(args):
    """Fill catalog rows from getTaskById + getGenerationModelByVersionId: the core
    prompt_full/natural_prompt/seed/steps/sampler/cfg_scale/model_id/model_name, plus
    url/width/height from the task's media object as a free side effect. steps/sampler/cfg
    also fall back to the model VERSION preset when the task recorded none (issue #18).

    Re-fetch is gated by _needs() (see below), which is why the extra surfaces are opt-in --
    each widens the set of already-detailed rows that get re-fetched:
      --with-loras    rows missing the `loras` column (predate LoRA tracking)
      --with-credit   rows missing `paid_credit` (predate cost tracking)
      --with-surface  rows missing the 15 issue-#18 surface columns (inference_profile,
                      quality_tag, render_seconds, backend, retry_count, moderation, ...) --
                      the ONLY way a pre-#18 row that already has prompt + model ever gains
                      them, since it otherwise passes every _needs() gate and is skipped.
    Safe to re-run -- each pass skips rows already carrying what it targets."""
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
    with_surface = getattr(args, "with_surface", False)

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
        # --with-surface is the same opt-in pattern for the 15 issue-#18 surface columns
        # (inference_profile, quality_tag, render_seconds, backend, retry_count, moderation,
        # ...). A pre-#18 row that DID reach detail (it has prompt_full + a model id) passes
        # every gate above and so was skipped forever, never gaining a single surface column
        # -- exactly the rows the whole surface capture exists to enrich. `updated_at` is the
        # sentinel: it is one of the 15, every real getTaskById carries it, and nothing wrote
        # it before #18, so a blank updated_at on a row that has a task_id means "this row
        # predates surface capture." A row already enriched has it set and is skipped; a task
        # that genuinely returns no updatedAt re-fetches each run (bounded, idempotent -- the
        # same deal the _DETAIL_ONLY sweep already makes). Opt-in because on a big historical
        # catalog it re-fetches nearly every task once.
        if with_surface and r.get("task_id") and not (r.get("updated_at") or "").strip():
            return True
        return False
    needs_fill = [r for r in rows if _needs(r)]
    # Named separately in the count below because it is the case that used to be invisible.
    stalled = [r for r in needs_fill
               if r.get("prompt_full")
               and not any((r.get(c) or "").strip() for c in _DETAIL_ONLY)]
    # The surface-only re-admits: rows that already reached detail (prompt + model) yet carry
    # no surface columns. Called out for the same reason `stalled` is -- it is the population
    # --with-surface exists to reach, and staying silent about its size hid whether the flag did
    # anything on a given catalog.
    surface_only = [r for r in needs_fill
                    if with_surface and r.get("task_id") and r.get("prompt_full")
                    and any((r.get(c) or "").strip() for c in _DETAIL_ONLY)
                    and not (r.get("updated_at") or "").strip()]
    task_ids = list(dict.fromkeys(r["task_id"] for r in needs_fill if r.get("task_id")))
    print("Found {:,} rows to fill across {:,} unique tasks{}{}{}.".format(
        len(needs_fill), len(task_ids), " (incl. LoRAs)" if with_loras else "",
        " (incl. credit costs)" if with_credit else "",
        " (incl. #18 surface)" if with_surface else ""))
    if stalled:
        print("  {:,} of them have a prompt but no model/steps/sampler/CFG -- these were "
              "skipped by every earlier backfill.".format(len(stalled)))
    if surface_only:
        print("  {:,} of them already had prompt + model but no #18 surface data (profile, "
              "quality tag, render time, backend, moderation...) -- re-fetched for it.".format(
                  len(surface_only)))
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
        _fill_preset_defaults(session, fm, task_data)   # issue #18: model-preset steps/sampler/cfg
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

    # Index the catalog by task id ONCE so each task's meta applies straight to its own rows as
    # it streams back -- no whole-catalog task_cache held across the run. The rows already carry
    # their load-time local columns (they came from load_catalog), so re-saving one preserves
    # its rating/collections/art_tags/etc.
    rows_by_task = {}
    for row in rows:
        rows_by_task.setdefault(str(row.get("task_id") or ""), []).append(row)

    def _apply(tid, fm):
        """Fill one task's catalog rows from its full meta; return the rows it actually changed
        (so only those get written at the next checkpoint)."""
        changed = []
        for row in rows_by_task.get(str(tid), ()):
            hit = False
            # fm is per-TASK; batch_index/batch_size are per-ROW (issue #33) -- resolve
            # this row's own from the outputs.batch list fm parked under _batch.
            fmr = _with_batch_position(fm, row.get("media_id"))
            for f in _FULL_META_FIELDS:
                if not row.get(f) and fmr.get(f):
                    row[f] = fmr[f]; hit = True
            # Backfill url/width/height from task media as bonus
            if not row.get("url") and fm.get("_media_url"):
                row["url"] = fm["_media_url"]; hit = True
            if not row.get("width") and fm.get("_media_width"):
                row["width"] = fm["_media_width"]; hit = True
            if not row.get("height") and fm.get("_media_height"):
                row["height"] = fm["_media_height"]; hit = True
            if hit:
                changed.append(row)
        return changed

    # Persist AS WE GO, not once at the very end. A 36k-image catalog is tens of thousands of
    # getTaskById calls -- an hour-plus run -- and the old single end-save meant a Ctrl-C or a
    # dropped connection at minute 50 wrote NOTHING, so the whole run was lost. Now every
    # _BACKFILL_CHECKPOINT_TASKS completed tasks the rows filled so far are flushed, so an
    # interrupted run keeps its progress and a rerun resumes where it stopped (the rows already
    # filled now fail _needs() and are skipped). Only backfill-CHANGED rows are written, never
    # the untouched majority -- so an image the owner just rated in the gallery mid-run is not
    # re-saved from a stale snapshot, which NARROWS the concurrent-edit window the end-save had.
    pending = []

    def _checkpoint():
        if pending:
            save_catalog(db_path, pending)
            pending.clear()

    for tid, fm in _parallel_map(task_ids, _fetch_task, workers, _prog, delay=args.delay,
                                 on_error=_note_error):
        fm = fm or {}
        if fm.get("prompt_full"):
            fetched += 1
        else:
            failed += 1
        pending.extend(_apply(tid, fm))
        if (fetched + failed) % _BACKFILL_CHECKPOINT_TASKS == 0:
            _checkpoint()
        if not _prog and workers <= 1:
            sys.stdout.write("\r  Tasks {:,}/{:,}  fetched {:,}  failed {:,}  ".format(
                fetched + failed, len(task_ids), fetched, failed))
            sys.stdout.flush()

    _checkpoint()   # flush the final partial batch
    print()         # end the \r progress line before the summary below
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


def run_backfill_lineage(args):
    """--backfill-lineage: fill source_media_id/derive_kind for rows that already have full
    meta (so --backfill-full-meta's own _needs() gate would never revisit them) but predate
    lineage tracking. Same per-task getTaskById + source_media_of_task as the forward path
    (extract_full_meta), just re-scoped to target ONLY the two lineage columns so a catalog
    that's already fully backfilled doesn't need a second full re-fetch to gain lineage.
    Safe to re-run -- skips rows that already have EITHER column set (an original txt2img
    legitimately has both blank forever, so "blank" alone can't be the skip signal; a task_id
    already visited is tracked instead so an original is never re-fetched every run)."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))

    if not TASK_DETAIL_HASH:
        raise PixAIError(
            "TASK_DETAIL_HASH is empty -- the built-in default is missing or was overridden "
            "with a blank value in config.json. Restore it, or capture a current getTaskById "
            "sha256Hash from DevTools if the hash rotated.")

    rows = load_catalog(db_path)
    # A task is "done" once ANY of its rows carries a real source_media_id OR the persisted
    # lineage_checked marker (a confirmed original -- "blank" alone is ambiguous with "never
    # checked", which is exactly what lineage_checked exists to disambiguate).
    done_tasks = {r["task_id"] for r in rows
                  if r.get("task_id") and (r.get("source_media_id") or r.get("lineage_checked"))}
    task_ids = list(dict.fromkeys(
        r["task_id"] for r in rows if r.get("task_id") and r["task_id"] not in done_tasks))
    print("Found {:,} unfiled tasks to check for lineage.".format(len(task_ids)))
    if not task_ids:
        print("Nothing to backfill.")
        return

    workers = max(1, getattr(args, "workers", 1) or 1)

    def _fetch(tid):
        task_data = task_detail_gql(session, tid)
        src, kind = source_media_of_task(task_data)
        return (src or "", kind or "")

    task_lineage = {}
    found = checked = 0
    _prog = getattr(args, "progress", None)
    err_kinds = {}

    def _note_error(tid, exc):
        key = "{}: {}".format(type(exc).__name__, str(exc).strip().splitlines()[0][:120]
                              if str(exc).strip() else "(no message)")
        err_kinds[key] = err_kinds.get(key, 0) + 1

    for tid, res in _parallel_map(task_ids, _fetch, workers, _prog, delay=args.delay,
                                  on_error=_note_error):
        if res is None:
            # The fetch RAISED (network blip, rate limit, PixAI 500) -- _parallel_map
            # calls on_error and then still yields the item with res=None. Leaving the
            # task OUT of task_lineage keeps lineage_checked unstamped so the next run
            # retries it; folding it in as ("", "") would stamp the error as a confirmed
            # original and permanently exclude the task from every future run.
            continue
        src, kind = res
        task_lineage[tid] = (src, kind)
        checked += 1
        if src:
            found += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  Tasks {:,}/{:,}  derived {:,}  ".format(
                checked, len(task_ids), found))
            sys.stdout.flush()

    print("\nApplying to catalog rows...")
    for row in rows:
        tid = row.get("task_id")
        if tid not in task_lineage:
            continue
        src, kind = task_lineage[tid]
        if src:
            row["source_media_id"] = src
            row["derive_kind"] = kind
        # No source image -- a confirmed original, not "not yet checked". Persisted (a real
        # catalog column) so this task is skipped on every future run instead of re-fetched
        # forever -- see this command's docstring.
        row["lineage_checked"] = "1"

    save_catalog(db_path, rows)
    errored = sum(err_kinds.values())
    print("Done. Checked {:,} tasks, {:,} carried a derivation source, {:,} errored. "
          "Catalog updated.".format(checked, found, errored))
    if err_kinds:
        print("Why they failed:")
        for kind, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:5]:
            print("  {:>7,}  {}".format(n, kind))


def run_backfill_phash(args):
    """--backfill-phash: compute a perceptual difference-hash (compute_dhash(), a 64-bit
    dHash -- see its docstring in moonglade_gallery.py) for every catalog row missing
    one. IMAGE ROWS ONLY: is_video='1' rows are skipped by design -- the near-duplicate
    tier this feeds (near_duplicate_groups(), moonglade_gallery.py) is scoped to images,
    matching the same image-only scope every other duplicate tier already has.

    Purely local, CPU-bound Pillow work -- no network call, so --delay/politeness pacing
    (that flag exists to be polite to PixAI's servers) does not apply here. --workers
    still parallelizes it via a thread pool (Pillow releases the GIL during decode, same
    reasoning build_thumbnails() already uses). --max caps how many rows THIS RUN
    processes (0 = all) -- useful for scoping a first pass on a large library, or a small
    disposable verification run, before committing to hashing the whole thing.

    Safe to re-run -- skips rows that already have a phash. A row whose image file can't
    be found on disk and a row whose file exists but Pillow can't decode are counted
    SEPARATELY from each other (and from the video rows skipped by design), so the
    summary can say WHY a row wasn't filled rather than just how many weren't -- the
    same "don't collapse different failure reasons into one number" lesson
    run_backfill_full_meta's docstring already explains."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    from moonglade_gallery import load_catalog, save_catalog, compute_dhash, find_image_file

    rows = load_catalog(db_path)
    videos = [r for r in rows if str(r.get("is_video") or "") == "1"]
    to_fill = [r for r in rows
              if not r.get("phash") and str(r.get("is_video") or "") != "1"]
    found_n = len(to_fill)
    max_n = int(getattr(args, "max", 0) or 0)
    capped = bool(max_n and found_n > max_n)
    if capped:
        to_fill = to_fill[:max_n]
    print("Found {:,} image rows missing a perceptual hash (out of {:,} total catalog "
          "rows, {:,} video rows skipped by design).".format(found_n, len(rows), len(videos)))
    if capped:
        print("  Capped to the first {:,} by --max.".format(max_n))
    if not to_fill:
        print("Nothing to backfill.")
        return {"filled": 0, "unresolved": 0, "unreadable": 0, "total": len(rows)}

    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Hashing with {} parallel workers.".format(workers))

    def _one(row):
        path = find_image_file(out, row["media_id"], row.get("filename"))
        if not path:
            return None, "unresolved"
        h = compute_dhash(path)
        return (h, "ok") if h else (None, "unreadable")

    filled = unresolved = unreadable = 0
    _prog = getattr(args, "progress", None)
    for row, res in _parallel_map(to_fill, _one, workers, _prog, delay=0):
        h, status = res if res else (None, "unreadable")
        if h:
            row["phash"] = h
            filled += 1
        elif status == "unresolved":
            unresolved += 1
        else:
            unreadable += 1
        if not _prog and workers <= 1:
            sys.stdout.write(
                "\r  {:,}/{:,}  hashed {:,}  unresolved {:,}  unreadable {:,}  ".format(
                    filled + unresolved + unreadable, len(to_fill), filled, unresolved, unreadable))
            sys.stdout.flush()

    print("\nWriting catalog...")
    save_catalog(db_path, to_fill)
    print("Done. Hashed {:,} rows. {:,} had no resolvable file on disk, {:,} couldn't be "
          "decoded.".format(filled, unresolved, unreadable))
    return {"filled": filled, "unresolved": unresolved, "unreadable": unreadable, "total": len(rows)}


def _check_time_capsule(created_at, out_dir):
    """A hidden anniversary feat: fires when a NEWLY-downloaded piece is old enough,
    only on the download event, never on a full-catalog rescan (old rows already
    on disk must not earn it). Fail-soft; never slows the download loop.

    The feat's NAME, roast, criteria label and points are sealed in the container. The
    trigger's comparison constant (below) and its flag name are NOT -- they run in the
    public download loop with no container, so they are an accepted, un-sealable residual
    plaintext leak (recorded as such in the sealing definition-of-done). Do not describe
    them as sealed; the spoiler-leak guard can't catch a bare integer either."""
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

    # Ensure the catalog db exists + is schema-migrated (raises if none; no CSV auto-seed, #19)
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

    # ONE fast tree walk at startup (the shared scan_library: os.scandir, ~free
    # stat() on Windows, excluded subtrees pruned before descending): seed the
    # progress count AND build the on-disk media_id index. Resume is then an
    # O(1) dict lookup instead of an O(whole-tree) rglob per media_id -- the
    # latter made follow-up runs scale quadratically with collection size. This
    # walk happens BEFORE any network call and is the whole of INVARIANT 2's base
    # case, so it stays one walk and one dict.
    # QUARANTINE_EXCLUDE_ANYWHERE prunes gallery/ thumbnails, _duplicates/ and
    # _deleted/ by NAME at any depth -- this walker's own reading of the exclusion
    # set (named disagreement 2), not the top-level-subtree one the rglob walkers
    # use. B11 (audit 2026-07-21): without the _deleted/ prune a locally-purged
    # media_id is still indexed as "already done", so resume/--update never
    # re-downloads it.
    already_done = 0
    disk_bytes = 0
    on_disk_by_mid = {}   # media_id -> Path of an existing full-res image

    if out.exists():
        _t_scan = time.monotonic()
        for e in scan_library(out, kinds=("image",),
                              exclude=QUARANTINE_EXCLUDE_ANYWHERE):
            # A zero-byte file (an interrupted download that got far enough to create
            # the file but not to write it) must NOT count as "already done" here --
            # indexing it means it is skipped FOREVER: no --update/--sync ever
            # re-attempts a media_id already in this index, and
            # reconcile_catalog_with_disk's strict matcher (moonglade_gallery.py) finds
            # nothing wrong either, so the row's filename is left pointing at a dead
            # file with no signal to the user. A stat() race (size is None) is treated
            # as fine, matching prior behaviour -- we can't tell either way, and this
            # index has always erred toward "already done" on an unreadable stat.
            # This is INVARIANT 3 living at the caller, which is why scan_library
            # reports `size` instead of applying a zero-byte rule of its own.
            if e.size == 0:
                continue
            already_done += 1
            if e.size is not None:
                disk_bytes += e.size
            on_disk_by_mid.setdefault(e.media_id, e.path)
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
            # _CONSOLE_LOCK: this is THE writer a pool thread's TLS paragraph races with --
            # _tick runs on the main thread as futures complete, resolve_media runs on the
            # workers. See _console_block.
            with _CONSOLE_LOCK:
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
    # --delay is documented as a politeness throttle that applies to most commands, not just
    # to the serial download loop -- but the parallel branch below paced only the page listing
    # and the per-task full-meta fetch, and fired every resolve_media + download back-to-back
    # with nothing in between, so a user who asked for pacing did not get it on the one stage
    # that makes the most requests (M07, 2026-07-27).
    #
    # It is honoured here only when the user actually TYPED --delay. The first repair paced
    # the pool off the argparse default and so re-paced every existing install that had never
    # asked for anything: at the shipped 0.4s that is a hard global ceiling of 2.5 images/sec
    # regardless of --workers, which turns this file's own documented `--workers 8
    # --page-size 500  # fast full backfill` into a ~2-hour download stage for a 17k library
    # where it used to be ~35 minutes, and quietly makes the Control Panel's Download-workers
    # selector decorative (the panel spawns the CLI with --workers N and no --delay). A
    # throttle nobody asked for is not politeness, it is a silent 3-6x regression -- so the
    # DEFAULT keeps today's full-speed behaviour and `--delay <n>` (including `--delay 0.4`,
    # typed) buys the documented contract. See _DefaultDelay for how the two are told apart.
    #
    # When it IS on: same global-slot semantics as _parallel_map -- one request start per
    # delay across the whole pool, NOT per thread -- so --workers still buys latency hiding
    # rather than a bigger burst, and the gate is built ONCE for the run so the pace survives
    # page boundaries. Each image books ONE slot, covering its resolve_media and its download
    # together; that is a deliberate choice and it is NOT the same rate as the serial branch,
    # which sleeps once per SUCCESSFULLY downloaded image and not at all for a missing one.
    _paced_downloads = _delay_was_chosen(args)
    _pace_image = _pace_gate(args.delay if _paced_downloads else 0)
    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print("Parallel downloads: {} workers{}.\n".format(
            workers,
            (", paced to one image per {:g}s across the pool (--delay)".format(args.delay)
             if _paced_downloads and args.delay else "")))

    def _row_for(meta, mid, full_meta, filename="", url="", w="", h=""):
        return {
            "task_id": meta["task_id"], "media_id": mid,
            "filename": filename, "url": url, "width": w, "height": h,
            "prompt_preview": meta["prompt_preview"],
            "status": meta["status"], "created_at": meta["created_at"],
            # full_meta is per-TASK; batch_index/batch_size are per-ROW (issue #33)
            **_merge_full(_with_batch_position(full_meta, mid), known.get(mid, {})),
        }

    try:
        while True:
            page += 1
            conn = find_connection(gql(session, page_variables(
                args.page_size, _client_of(session).user_id, before)))
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
                            _fill_preset_defaults(session, fm, task_data)   # issue #18
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
                    # Blocks on a pool thread until this image's slot comes up -- but only
                    # when the user typed --delay. Left at its default (and with --delay 0)
                    # this is a no-op call on a `lambda: None`, so the pool runs exactly as
                    # fast as it did before the gate existed.
                    _pace_image()
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
                        _fill_preset_defaults(session, fm, task_data)   # issue #18
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
                            **_merge_full(_with_batch_position(full_meta, mid), k),
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
                            **_merge_full(_with_batch_position(full_meta, mid), known.get(mid, {})),
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
                            **_merge_full(_with_batch_position(full_meta, mid), known.get(mid, {})),
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
                        **_merge_full(_with_batch_position(full_meta, mid), known.get(mid, {})),
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

            # Count TASKS, not pages -- exactly as the parallel branch above does. Counting
            # one per page made every single-worker run (which is what --collect-only always
            # is) overshoot --max by a whole page size and print a "Tasks seen" total that
            # was really a page count.
            seen += len(edges)

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
                         "(equivalent to --update --full-meta), fill any catalog rows still "
                         "missing prompts/seeds/models, re-resolve any unlabeled model names, "
                         "build any missing preview thumbnails, and reconcile rows deleted on "
                         "PixAI. Every step is idempotent, so re-running on a clean catalog "
                         "costs almost nothing. (Video tasks are not part of --sync -- run "
                         "--sync-videos for those.)")
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
    ap.add_argument("--max", type=int, default=0,
                    help="stop after N tasks (0=all); with --backfill-phash, caps the number "
                         "of rows that run processes instead")
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
    # default is the _DefaultDelay sentinel, not a bare 0.4, so run_download can tell a typed
    # `--delay 0.4` from an untouched default. See _DefaultDelay for why a comparison cannot.
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help="seconds to wait between API requests (default: 0.4). Passing it "
                         "EXPLICITLY also paces the parallel download stage, at one image "
                         "per --delay across the whole pool; left at its default, downloads "
                         "run at full --workers speed as they always have")
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
    ap.add_argument("--undo-organize", action="store_true",
                    help="revert the last --organize run using organize_manifest.csv "
                         "(move files back to their old paths), then exit")
    ap.add_argument("--embed-metadata", action="store_true",
                    help="with --organize, embed prompt/IDs/date into PNG/JPEG files "
                         "(off by default; useful when pulling images into other apps)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --organize / --undo-organize, show the "
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
    ap.add_argument("--with-surface", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "none of the issue-#18 surface columns yet (inference profile, quality "
                         "tag, render time, backend, moderation, retry count...); the only way a "
                         "pre-#18 generation gains them. Long run on a big historical catalog.")
    ap.add_argument("--backfill-lineage", action="store_true",
                    help="fill in source_media_id/derive_kind (which image an edit/upscale/"
                         "video was made FROM) for rows that predate lineage tracking, via "
                         "getTaskById; powers Image Details' LINEAGE panel. Idempotent -- a "
                         "confirmed original is remembered and never re-fetched. Then exit.")
    ap.add_argument("--backfill-phash", action="store_true",
                    help="compute a perceptual difference-hash (dHash) for every image catalog "
                         "row that lacks one, powering the near-duplicate ('upscaled or "
                         "recompressed copy') tier of GET /api/duplicates. Local Pillow work, no "
                         "network call -- --workers parallelizes it, --max caps how many rows "
                         "this run processes. Videos are skipped. Then exit.")
    ap.add_argument("--sync-artworks", action="store_true",
                    help="fetch your published-artwork metadata (title, NSFW flag, likes, "
                         "comments, aes score, tags) via listArtworks and merge it onto "
                         "matching catalog rows by media_id, then exit")
    ap.add_argument("--with-videos", action="store_true",
                    help="with --sync-artworks, also download animated-artwork video files "
                         "(videoMediaId) into a videos/ folder")
    ap.add_argument("--sync-videos", action="store_true",
                    help="back up your image-to-video generations: find i2v tasks, download "
                         "each mp4 into videos/, and catalog them (is_video), then exit. This is "
                         "the video-side complement of --sync, which skips video tasks: run it to "
                         "capture videos made on the PixAI website (app-made videos are already "
                         "caught when generated). Full-history scan, so it's a separate pass.")
    ap.add_argument("--faststart-videos", dest="faststart_videos", action="store_true",
                    help="losslessly move every video's moov atom to the front (ffmpeg "
                         "-c copy +faststart) so iOS/Safari can play them over HTTP, then exit")
    ap.add_argument("--account", action="store_true",
                    help="show a read-only account dashboard (credit balance, membership, "
                         "subscription) and exit. Never moves money")
    ap.add_argument("--cards", action="store_true",
                    help="show your free-generation cards (kaisuuken) + their ids, then exit. "
                         "Read-only; pass an id to a run with --kaisuuken-id")
    ap.add_argument("--mirror-check", action="store_true",
                    help="check/bootstrap the 'Mirror to PixAI website' session (reads the "
                         "pixai.art session from a local browser, refreshes the JWT) and "
                         "report days-left, then exit. Never prints the token; spends nothing")
    ap.add_argument("--card-history", action="store_true",
                    help="show recent benefit-card usage (redemptions + refunds), then exit. "
                         "Read-only. Pass --card-history-all for the full lifetime card-type "
                         "catalog instead of a recent list")
    ap.add_argument("--card-history-all", action="store_true",
                    help="with --card-history, page all the way back and print every card "
                         "TYPE ever used (several requests; read-only)")
    ap.add_argument("--card-history-count", type=int, default=0, metavar="N",
                    help="with --card-history, how many recent records to show (default 20)")
    ap.add_argument("--coupons", action="store_true",
                    help="show your currently-held Credit Boost coupons, then exit. "
                         "Read-only -- a reward type separate from benefit cards. Pass "
                         "--coupons-history for the redeemed + expired view instead")
    ap.add_argument("--coupons-history", action="store_true",
                    help="with --coupons, show the past (redeemed + expired) view instead "
                         "of what you currently hold")
    ap.add_argument("--credit-log", action="store_true",
                    help="show your full credit transaction ledger (purchases, claims, "
                         "gifts, generation spend, refunds), then exit. Read-only")
    ap.add_argument("--credit-log-count", type=int, default=0, metavar="N",
                    help="with --credit-log, how many recent entries to show (default 30)")
    ap.add_argument("--credit-log-reason", default="", metavar="TYPE",
                    help="with --credit-log, filter to one raw type (e.g. task_cost, daily, "
                         "event_gift, extra_package -- see CREDIT_LOG_REASONS)")
    ap.add_argument("--credit-log-before", default="", metavar="CURSOR",
                    help="with --credit-log, page further into the past using a cursor "
                         "printed by a previous --credit-log run")
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
    gen.add_argument("--priority", type=int, default=PRIORITY_TURBO,
                     choices=list(PRIORITY_CHOICES),
                     help="speed channel: 0 = standard, no extra cost; 500 = turbo, "
                          "~7.6x faster and free but MEMBERS ONLY (default -- falls back "
                          "to 0 on its own if the account isn't a member); 1000 = high, "
                          "~10x faster and costs EXTRA credits; 1500 = extra high")
    gen.add_argument("--high-priority", dest="priority", action="store_const",
                     const=PRIORITY_HIGH,
                     help="shortcut for --priority 1000 (faster, costs extra credits)")
    gen.add_argument("--low-priority", dest="priority", action="store_const",
                     const=PRIORITY_LOW,
                     help="shortcut for --priority 0 (standard speed, never members-only)")
    gen.add_argument("--mode", default="auto",
                     choices=["auto", "lite", "standard", "pro", "ultra"],
                     help="quality mode (inferenceProfile). auto (default) lets PixAI pick the "
                          "model's default -- always VALID (price depends on the model's own "
                          "default). lite/standard suit SD_V1 models; "
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
                     help="video channel: private = the site's 'Private' channel (works "
                          "can't be published) | normal")
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
        if getattr(args, "mirror_check", False):
            run_mirror_check(args)
            return
        if getattr(args, "card_history", False) or getattr(args, "card_history_all", False):
            run_card_history(args)
            return
        if getattr(args, "coupons", False) or getattr(args, "coupons_history", False):
            run_coupons(args)
            return
        if getattr(args, "credit_log", False):
            run_credit_log(args)
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
            # arrives WITH metadata, fill anything still blank (which is what fills a
            # model_id for a row that never reached detail), THEN re-resolve any model
            # ids that came back blank/numeric into clean names, rebuild any missing
            # preview thumbnails, then reconcile rows deleted on the website. Every step
            # is idempotent/self-limiting (backfill skips rows that already have
            # prompt_full; build_thumbnails skips thumbs already on disk), so
            # re-running --sync on a clean catalog costs almost nothing extra.
            #
            # Order note (2026-08-15): backfill runs BEFORE fix-models on purpose.
            # fix-models can only relabel a row that already HAS a model_id; backfill is
            # what fills model_id for a row that never saw task detail. Running backfill
            # first hands those freshly-filled ids to fix-models in the SAME sync, instead
            # of leaving a numeric/blank name (backfill's own model_name_gql soft-fail) to
            # be cleaned only on the next run. Both steps are independent and idempotent, so
            # the swap is safe -- it just closes the loop one sync sooner.
            #
            # VIDEO scope (2026-08-15): --sync intentionally does NOT run the video
            # backfill. run_download skips video task nodes by design (a video's poster is
            # not a standalone image), and app-path videos are already captured the moment
            # they are made (run_generate_video / --task-id recovery / _download_video_task).
            # The only videos --sync can't reach are ones generated on the PixAI WEBSITE.
            # Capturing those means a FULL-history feed walk plus a getTaskById per i2v task
            # every run -- the opposite of --sync's cheap-idempotent-rerun contract -- so it
            # stays the separate, deliberate `--sync-videos` pass rather than being folded in.
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
                print("\nSync: filling any rows still missing metadata...")
                run_backfill_full_meta(args)
                print("Sync: resolving any unlabeled model names...")
                run_fix_models(args)
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
                # Mark the first full sync done so the gallery stops withholding achievement
                # unlock toasts (first-light etc. fire on completion, not seconds into the
                # very first sync). Idempotent; covers the wizard too (its "Sync now" job
                # runs this same --sync). Fail-soft: a telemetry hiccup must not fail the sync.
                try:
                    import moonglade_gallery as _mg
                    _mg.telem_flag("first_sync_done", out_dir=out)
                except Exception:
                    pass
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
        if getattr(args, "backfill_lineage", False):
            run_backfill_lineage(args)
            return
        if getattr(args, "backfill_phash", False):
            run_backfill_phash(args)
            return
        if args.convert_existing:
            cmd_convert_existing(args, out)
            return
        if args.undo_organize:
            cmd_undo_organize(args, out)
            return
        if args.organize:
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
        # Build any missing preview thumbnails so a plain --update (or full backup) leaves
        # batch tiles renderable immediately. run_download writes image files + catalog rows
        # but NO thumbs, and the /thumbs/<mid>.jpg route serves straight from the cache with
        # no on-the-fly fallback -- so without this, freshly pulled images (esp. multi-image
        # batches) have no thumbnail until the next --sync or a gallery-server start. Mirrors
        # --sync's thumbnail tail; this is ONLY on the plain-download path (the --sync branch
        # above runs its own build and returns, so it never double-runs). build_thumbnails
        # skips thumbs already on disk, so a no-op update costs almost nothing -- and NOT
        # force=True, which would rebuild every thumbnail. Fail-soft on purpose: a thumbnail
        # hiccup must never crash a backup that already succeeded (the gallery server also
        # rebuilds missing thumbs on its next start).
        try:
            thumb_dir = out / "gallery" / "thumbs"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            print("Building any missing preview thumbnails...")
            _prog = getattr(args, "progress", None)
            build_thumbnails(load_catalog(db_path), out, thumb_dir,
                             progress_cb=((lambda d, t, _pct: _prog(d, t)) if _prog else None))
        except Exception as e:                           # noqa: BLE001 -- additive, never fatal
            vlog("thumbnail backfill after update skipped: {}".format(e))
    except PixAIError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

# ===========================================================================
# RECAPTURE (only if the site changes): re-grab the persisted sha256Hash, U3T,
# and USER_ID from Network tab -> graphql row -> Payload, and update config.json.
# Keep your token private.
# ===========================================================================

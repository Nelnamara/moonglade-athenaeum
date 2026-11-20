#!/usr/bin/env python3
"""
moonglade/backup.py  (v4 - media resolution)
================================================
Bulk-download YOUR OWN PixAI.art generated images. Reads PixAI's history-feed
GraphQL query (taskSummaries, as a full document) to page backward through your entire
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
  python -m moonglade --probe            # resolve full-res media URL, sanity-check
  python -m moonglade                    # download everything (backward)
  python -m moonglade --max 40           # small test first
"""

__version__ = "3.21.3"

import argparse
import base64
import copy
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
from collections import defaultdict, namedtuple, Counter
from dataclasses import dataclass, field
from pathlib import Path

from moonglade import cloud_delete as _cloud_delete
from moonglade import jobs as _jobs
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import organize as _organize
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import pricing as _pricing
from moonglade import secure_files as _secure_files
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade.gallery import (CATALOG_FIELDS, init_db, migrate, load_catalog,
                            query_catalog, catalog_csv_text,
                            save_catalog, _db_is_empty, rows_for_media_ids,
                            # A save of rows built from an earlier read: re-reads the
                            # current rows in the write transaction so an edit made
                            # meanwhile is never undone (2026-11-19).
                            save_catalog_over_snapshot,
                            # The row-level artwork write (see run_sync_artworks): one
                            # narrow UPDATE of the eleven PixAI-owned columns, keyed by
                            # media_id -- imported the same way its whole-table siblings
                            # above are.
                            apply_artwork_meta,
                            # ...and its twin for the four view columns, which are folded
                            # by their own narrow UPDATE because they are read once per
                            # deliberate sync, not on the fifteen-minute sweep's cadence.
                            apply_artwork_views,
                            build_thumbnails,
                            _NO_WINDOW, _redact_host_paths_cli)
# The one library scan (moonglade/scan.py, out of the gallery since 3.21.0).
from moonglade.scan import (_IMAGE_EXTS, media_id_of, find_files_for_media_id, DELETED_DIRNAME,
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


class HistoryPageRefused(PixAIError):
    """PixAI answered a page of the history feed with a GraphQL error: any refusal of the full
    document, or its passing "Internal server error" that a wait and a smaller page did not
    get past. The message is HISTORY_REFUSED, the plain sentence a user sees; PixAI's own
    error is the chained cause. Raised by `gql` only; a network failure, a 401 or a 5xx is
    NOT this (those stay what they were), so a caller that names this one knows PixAI itself
    answered "no"."""


class ArtworkListRefused(PixAIError):
    """The owner's published-artwork list could not be read. The message is the reason in
    plain words (the kind of failure and PixAI's own message). Raised by `artwork_list_gql`
    only, so a caller that names this one knows it was the artwork read that failed."""


class LocalRefusal(PixAIError):
    """Refused HERE, before any network call: READ_ONLY, or the request's own validation.
    Nothing reached PixAI, so a spend guard treats it as a definite refusal
    (definite_refusal) and never tells the user a run "may have started" (waves 2+3 review,
    F4). Still a PixAIError, so every existing catch site is unchanged."""


class PixAIAuthError(PixAIError):
    """PixAI answered 401 on the GraphQL road (or a write that names it): the credential was
    refused before anything ran. Typed so a spend guard reads it by type, never by its
    message's "401 " prefix (DESIGN_3.22 2.6). Still a PixAIError with the same message."""


def graphql_error(errors, data=None, code=None):
    """The exception the GraphQL transport raises for an answer carrying `errors`: a PixAIError
    whose message is "GraphQL error: <errors>" (500 characters), with the whole list on
    `graphql_errors` and the answer's `data` on `graphql_data`. `errors` may be a list of
    error dicts, or text -- a JSON list, else one error of that message -- for a caller (or a
    test) that only has words; `code` puts PixAI's code where its site reads one
    (`extensions.exception.name`) on a text error. The spend classifier reads the
    attributes, never the message."""
    if isinstance(errors, str):
        try:
            parsed = json.loads(errors)
        except ValueError:
            parsed = None
        errors = parsed if isinstance(parsed, list) else [{"message": errors}]
    elif not isinstance(errors, list):
        errors = [{"message": str(errors)}]
    if code:
        errors = [dict(e, extensions={"exception": {"name": code}}) if isinstance(e, dict)
                  and "extensions" not in e else e for e in errors]
    err = PixAIError("GraphQL error: " + json.dumps(errors)[:500])
    err.graphql_errors = errors
    err.graphql_data = data
    return err


class PixAIRestError(PixAIError):
    """A /v2 REST route answered non-2xx. Still a PixAIError with the same message as before
    (every existing catch site is unchanged); it also carries the HTTP `status` and PixAI's
    parsed error body (`code`, `data`, the oRPC error shape) so a caller can say which images
    PixAI refused, or that a task was not in the state a route needs, in PixAI's own terms
    instead of a truncated string.

    `body` is PixAI's parsed answer exactly as sent -- None when it was not JSON -- and
    `http_status` is the same number as `status` (the recipe code reads that name, the
    training code this one); `fields` is the body as a dict, empty when it was not one."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def http_status(self):
        return self.status

    @property
    def fields(self):
        return self.body if isinstance(self.body, dict) else {}

    @property
    def code(self):
        return str(self.fields.get("code") or "")

    @property
    def data(self):
        d = self.fields.get("data")
        return d if isinstance(d, dict) else {}


def _rest_error(verb, path, r):
    try:
        body = r.json()
    except ValueError:
        body = None
    return PixAIRestError("REST {} {} -> {}: {}".format(verb, path, r.status_code, r.text[:300]),
                          status=r.status_code, body=body)


def _is_redirect_status(r):
    """True for a 3xx answer. `r.ok` is True for a 3xx, so a write verb asks this first.
    Guarded on an int status, so a stand-in response without one is not mistaken for it."""
    status = getattr(r, "status_code", None)
    return isinstance(status, int) and not isinstance(status, bool) and 300 <= status < 400


def _refuse_redirect(verb, path, r):
    """A write verb's answer to a 3xx (redirects are never followed on a write, #92 review
    F1): raise a PixAIRestError carrying the status, before anything reads the body -- the
    write is not re-sent anywhere, and a 3xx never counts as success."""
    if _is_redirect_status(r):
        raise PixAIRestError("REST {} {} -> {}: PixAI redirected this request; nothing was "
                             "re-sent.".format(verb, path, r.status_code),
                             status=r.status_code, body=None)


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
    always forwarded to the persistent file logger (moonglade.logs), regardless
    of verbose state, so a run's diagnostics are on record even if -v wasn't
    passed -- this is the one call site touched to give every existing vlog()
    caller file-logging for free, rather than threading a logger through ~100
    of them individually."""
    from moonglade import logs as moonglade_logging
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
# Site identifiers and the optional legacy overrides loaded from config.json (see
# config.example.json). When PixAI changes their site, the fix is in code, not in config.json.
# ===========================================================================
# The history feed's operation name. Its saved request retired (#89: the feed is read as a
# full document, _HISTORY_PAGE_DOC); the name survives as the x-apollo-operation-name value
# the sessions send for Apollo's CSRF check, which needs one present, not a matching one.
OPERATION_NAME = "listUserTaskSummaries"


def _config_path():
    """config.json's path -- THE call every reader and writer of it makes. The rule lives in
    moonglade.paths.config_path(): the copy beside the app first, then the current working
    directory (same order _load_config() has always read in); if neither exists yet (first
    run / a fresh write), the one beside the app. Kept as this module's function because
    the test suite pins it per test (dev/tests/conftest.py's _isolated_auth_config), so no test
    can reach the real file."""
    return _paths.config_path()


def _load_config():
    """Read config.json. Returns {} quietly if absent so --help and offline modes
    (--organize, --catalog-stats) work without it; main() validates before API calls.
    Looks next to the script file first, then the current working directory."""
    cfg_path = _config_path()
    if not cfg_path.exists():
        return {}
    try:
        # Read the way the move reads it (paths.decode_text): a byte order mark or a UTF-16
        # file (PowerShell 5.1's `>`) is the same config, not an empty one -- an empty one
        # would drop /login into bootstrap mode.
        return json.loads(_paths.decode_text(cfg_path.read_bytes()))
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
    (AUTH_EPOCH_SEQ) now lives in this file too, and every sign-out everywhere writes it, so the
    old truncate-then-write was a steadily widening window on an auth wipe."""
    path = _config_path()
    data = json.dumps(cfg, indent=2)          # serialize BEFORE touching disk
    tmp = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
    try:
        # Secrets at rest (app security review 2026-11-19, finding 5): the API key, the
        # session signing key and the account hashes are this user's alone. The temp file is
        # made owner-only while still EMPTY, before the secrets are written into it, so no copy
        # of them ever sits readable; the result is restricted again after the replace.
        _secure_files.write_private(tmp, data)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                _secure_files.restrict_to_owner(path)
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
# Web gallery login accounts -- session-based auth for moonglade/gallery.py's Flask
# app (gates EVERY request, local or remote -- there is no localhost bypass; see
# _is_authorized_request() there).
# Stored in config.json (the existing convention for secrets -- it already holds
# PIXAI_API_KEY): AUTH_SECRET_KEY signs the Flask session cookie, AUTH_USERS is a
# list of {"username", "password_hash"} (werkzeug.security -- scrypt as of modern
# werkzeug, timing-safe compare built in; no new pip install, werkzeug already
# ships with Flask). Account lifecycle used to be CLI-only; as of the web-based
# bootstrap + Panel Users tab (2026-07-19) it's also reachable from the browser
# (see moonglade/gallery.py's /login bootstrap POST and /api/users/add|remove) --
# --add-web-user / --remove-web-user / --list-web-users remain a valid recovery
# path. If AUTH_USERS is empty, logging in from the LAN is simply impossible --
# there is no default/backdoor account, ever.
#
# _accounts_lock serializes every read-modify-write of AUTH_USERS (and the
# atomic check-and-mutate helpers below) against every OTHER thread doing the
# same, within this one process. moonglade/gallery.py runs `app.run(...,
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

# How every NEW web-login password hash is made (werkzeug's generate_password_hash method):
# scrypt at werkzeug's own default cost. A module-level name for one reason: the test suite
# swaps it for a token scrypt cost on its throwaway accounts (dev/tests/conftest.py), since a
# real hash takes about a tenth of a second per account made and per sign-in checked, and most
# of the suite signs in. check_password_hash reads the cost back out of each stored hash, so
# this decides only how new hashes are made. Never lower it here:
# dev/tests/test_web_auth.py holds the shipped value to full strength.
WEB_PASSWORD_HASH_METHOD = "scrypt"

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
        new_users.append({"username": username,
                          "password_hash": generate_password_hash(
                              password, method=WEB_PASSWORD_HASH_METHOD),
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
                          "password_hash": generate_password_hash(
                              new_password, method=WEB_PASSWORD_HASH_METHOD),
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
    succeed. Used by the Panel's /api/users/add (moonglade/gallery.py); the plain
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
        users.append({"username": username,
                      "password_hash": generate_password_hash(
                          password, method=WEB_PASSWORD_HASH_METHOD),
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
    was current at login time; moonglade/gallery.py's _is_authorized_request()
    re-checks it against this on every request, so:
      - removing the account invalidates any outstanding session for it immediately
        (this returns None -> no epoch can ever match again), and
      - a sign-out everywhere (/api/logout with scope "everywhere") revokes every
        outstanding session for that identity (not just the browser that clicked it)
        by calling bump_web_user_session_epoch() before clearing its own session.
        A plain Log Out signs out only its own browser (#70).
    Without this, a stolen session cookie (plain-HTTP LAN, packet capture) would
    keep working after the legitimate user signs out everywhere or the account is removed,
    since the stock Flask session is a stateless, client-side signed cookie with
    nothing server-side to revoke -- see CHANGELOG.md for the fuller writeup."""
    cfg = _load_config()
    user = _find_web_user(cfg, (username or "").strip())
    if user is None:
        return None
    return int(user.get("sess_epoch", 0))


def bump_web_user_session_epoch(username):
    """Issue `username` a fresh session-epoch ticket, invalidating every outstanding
    session cookie for that identity in one move (used by /api/logout's sign-out
    everywhere). No-op (returns
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
    auth never pays scrypt's cost, and a running server pays it at most once. Made with
    WEB_PASSWORD_HASH_METHOD and cached per method, so it always costs what a real account's
    check costs."""
    method = WEB_PASSWORD_HASH_METHOD
    if method not in _dummy_hash_cache:
        from werkzeug.security import generate_password_hash
        _dummy_hash_cache[method] = generate_password_hash(
            "no-such-account-#dummy-timing-guard", method=method)
    return _dummy_hash_cache[method]


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
# network call refuses itself -- CLI and web alike, and REGARDLESS of --confirm/--apply,
# since those flags are the very thing a cautious first run wants to be safe to
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
    --confirm/--apply rather than just changing their default.

    Eight call sites, not four: submit_generation, submit_fixer, delete_task and
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


# No operation rides a saved (hash-only) request any more: the history feed (#89), task
# detail and model detail (#91) are read as full documents (_HISTORY_PAGE_DOC,
# _TASK_DETAIL_DOC, _MODEL_VERSION_DOC), and the whole-generation delete and the Mirror's
# session renewal go to PixAI's /v2 REST routes, exactly as pixai.art sends them (#92). A
# DELETE_TASK_HASH or REFRESH_TOKEN_HASH left in an old config.json is simply not read.
U3T = _cfg.get("U3T", "")
USER_ID = _cfg.get("USER_ID", "")  # auto-resolved from the API key (me{id}) if blank
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
    for f in _paths.token_paths():
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
    Control Panel's own _panel_reader) to the library's jobs.jsonl (_moonglade/records/) via append_job_event. This is
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
            _jobs.append_job_event(out_dir, job_id, status="running",
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
                page_size, _pixai_client._client_of(session).user_id, before)))
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
# The history feed: one road, the full document over the ad-hoc POST
# ---------------------------------------------------------------------------
# The history feed as a full document, selecting the task summary fields every reader uses.
# It needs no saved copy on PixAI's side. The saved request it replaced (a hash of the site's
# old document) was answered from a cache part of the time and refused the rest -- about one
# read in five on the owner's install on 2026-10-25 -- and the site itself no longer sends it
# (#89). Same ids, same order, same result shape, so `find_connection` reads it.
_HISTORY_PAGE_DOC = (
    "query($userId: ID!, $last: Int, $before: String) { user(id: $userId) { id "
    "taskSummaries(last: $last, before: $before) { "
    "pageInfo { hasNextPage hasPreviousPage endCursor startCursor } "
    "edges { node { id userId status priority runnerId startedAt endAt createdAt paidCredit "
    "mediaId batchMediaIds i2vProModel characteristics artworkCount promptsPreview "
    "enrolledExperiment } } } } }")

# What a user is told when PixAI refuses a page of the feed, in plain words: the read
# changed nothing, and asking again later is all there is to do.
HISTORY_REFUSED = ("PixAI refused the history feed; nothing was changed -- try again in a "
                   "minute.")
# PixAI's passing failure on a big page: a GraphQL "Internal server error" (its database
# layer) after about 5 s, seen only at 5000 rows, 2 reads of 4, the same read answering 5 s
# later (PROBE_2026-10-25). `gql` waits this long and asks once more, then once more at
# HISTORY_FALLBACK_LAST rows, a size that answered every time it was measured.
HISTORY_RETRY_WAIT_S = 5.0
HISTORY_FALLBACK_LAST = 2000
# --count's page size (--count-page-size). 2000, not the 5000 it was: the count asks 2.5x as
# many pages, and never the size PixAI fails now and then.
COUNT_PAGE_SIZE = 2000


def _history_wait(seconds):
    """The wait before `gql` asks again after an internal-server failure. Its own name, so a
    test records the wait instead of taking it."""
    time.sleep(seconds)


def _feed_refusal(exc):
    """`(refused, internal)` for an error the feed's document read raised. `refused` is True
    when PixAI answered with GraphQL errors (`_graphql_post` hangs the list on the error; a
    bare "GraphQL error: ..." message counts too); `internal` is True when one of them is the
    passing "Internal server error". A network error, a 401, a 5xx or a non-JSON body is
    neither."""
    errors = getattr(exc, "graphql_errors", None)
    if isinstance(errors, list):
        return True, any(isinstance(err, dict) and "internal server error"
                         in str(err.get("message") or "").lower() for err in errors)
    text = str(exc)
    if text.startswith("GraphQL error"):
        return True, "internal server error" in text.lower()
    return False, False


def gql(session, variables, retries=4):
    """One page of the history feed: `_HISTORY_PAGE_DOC` POSTed through `gql_adhoc` with the
    page variables (`page_variables`), a query. Returns the `data` dict; `find_connection`
    reads the page out of it. `retries` is `gql_adhoc`'s, covering network errors and 5xx as
    it always has.

    PixAI answering with a GraphQL error is `HistoryPageRefused` (message HISTORY_REFUSED,
    chained from PixAI's own error), at once -- with one exception. Its "Internal server error"
    on a big page passes: wait HISTORY_RETRY_WAIT_S (`_history_wait`) and ask once more, and if
    that fails the same way and the page asked for more than HISTORY_FALLBACK_LAST rows, ask
    once more for HISTORY_FALLBACK_LAST rows with the same `before`. A page that comes back
    smaller than asked is still a page: every caller walks on from the returned page's own
    `pageInfo.startCursor`, never from the size it asked for. Network errors, a 401 and a 5xx
    raise as they do from `gql_adhoc`. Read-only, so asking again costs nothing but a request.

    An answer with no page in it is `HistoryPageRefused` too (`_history_answer`), never an
    empty history: a body that is not GraphQL at all -- `{"message": "Forbidden"}` at a 200,
    400 or 403, an edge's or a stale credential's own JSON -- comes back from the ad-hoc POST
    as {}, and every caller would read the missing connection as the end of the feed."""
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC, variables, retries=retries)
    except PixAIError as e:
        refused, internal = _feed_refusal(e)
        if not refused:
            raise
        if not internal:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
    else:
        return _history_answer(data)
    _history_wait(HISTORY_RETRY_WAIT_S)
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC, variables, retries=retries)
    except PixAIError as e:
        refused, internal = _feed_refusal(e)
        if not refused:
            raise
        last = (variables or {}).get("last")
        if not internal or not isinstance(last, int) or last <= HISTORY_FALLBACK_LAST:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
    else:
        return _history_answer(data)
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC,
                         dict(variables, last=HISTORY_FALLBACK_LAST), retries=retries)
    except PixAIError as e:
        if _feed_refusal(e)[0]:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
        raise
    return _history_answer(data)


def _history_answer(data):
    """`data` when it holds a page of the feed (a connection: `edges` and `pageInfo`); else
    `HistoryPageRefused`, chained from a PixAIError that says what came back. A user with no
    generations still gets a connection, with no edges, so no real answer is refused. The
    same check the artworks list makes (`artwork_list_gql`, #88)."""
    if find_connection(data or {}) is None:
        raise HistoryPageRefused(HISTORY_REFUSED) from PixAIError(
            "PixAI answered, but with no history page in it")
    return data


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
    from moonglade.gallery import delete_from_catalog
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
            # Every band's extremes, not getbbox(): on an RGBA image getbbox() looks at
            # the alpha band only (Pillow 10+), so any two opaque pictures "matched" and a
            # different picture under the same id passed as a metadata-only copy.
            return all(hi == 0 for _lo, hi in ImageChops.difference(ra, rb).getextrema())
    except Exception:
        return None


def media_ids_for(node):
    """Every media id a task summary NAMES: `mediaId` plus `batchMediaIds`, deduped.

    NOT the ids the catalog is keyed by -- on a batch task `mediaId` is the composite
    preview grid and on a video task it is the poster still, and no row is keyed by
    either. Anything asking "is this already collected?" wants `cataloged_media_ids`
    below; asking it here answers "no" forever for both shapes (2026-09-07)."""
    ids = []
    if node.get("mediaId"):
        ids.append(str(node["mediaId"]))
    for b in (node.get("batchMediaIds") or []):
        if b:
            ids.append(str(b))
    return list(dict.fromkeys(ids))


def cataloged_media_ids(node):
    """The media ids this task's catalog rows are actually keyed by.

    `media_ids_for` answers a DIFFERENT question -- every media id a task names -- and the
    two sets are not the same. On a batch task `mediaId` is the composite preview grid,
    which is never one of the batch members and is never cataloged (probe 2026-09-06); on a
    video task `mediaId` is the poster STILL, while the catalog's row is keyed by the mp4's
    own media id. Anything asking "has this task already been collected?" off
    media_ids_for therefore answered "no" forever for both shapes -- which is what made the
    live mirror's catch-up relist the same tasks every five minutes and claim in the log
    they had never been mirrored (fixed 2026-09-07; the ruling that catch-up skips a task
    only when the catalog is actually missing its media is unchanged, this is the id set
    that ruling always meant).

    Reads whichever shape it is handed:

    * A full `getTaskById` result (it has `outputs`): videos via `video_outputs`, images via
      `_task_image_media` -- the same two helpers `collect_generation` catalogs from, so the
      answer is by construction the ids the rows carry.
    * A `listUserTaskSummaries` node (a `TaskSummary`: no `outputs` at all, only
      `mediaId` / `batchMediaIds` / `i2vProModel`): `batchMediaIds` when the task HAS a
      batch, else `mediaId`. That is PixAI's own frontend rule for a summary, and it lands
      on the same ids `_task_image_media` reaches from the detail. A member PixAI has
      deleted comes through as a hole in `batchMediaIds` and is dropped here, matching
      `_task_image_media` skipping a `deletedAt` member -- so a batch whose members are ALL
      deleted yields nothing and deliberately does NOT fall back to `mediaId`, exactly as
      that helper refuses to.

    A VIDEO summary returns [] -- honestly nothing, because a summary names none of the ids
    the catalog holds (only getTaskById carries the video's own media id). [] therefore
    means "this node cannot tell you", not "there is nothing to collect", and a caller that
    must decide about a video task from a summary has to ask by task id instead:
    `_watch_catchup` checks `_is_video_task_node` first and uses `get_row_by_task`."""
    node = node or {}
    outputs = node.get("outputs")
    if outputs is not None:                          # full task detail
        vouts, _shared = video_outputs(node)
        if vouts:
            return list(dict.fromkeys(
                str(o["video_media_id"]) for o in vouts if o.get("video_media_id")))
        return [mid for mid, _seed in _task_image_media(outputs)]
    if _is_video_task_node(node):                    # summary: only the poster still
        return []
    batch = node.get("batchMediaIds")
    if isinstance(batch, (list, tuple)) and len(batch) > 0:
        return list(dict.fromkeys(str(b) for b in batch if b))
    return [str(node["mediaId"])] if node.get("mediaId") else []


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
    chosen, variant = None, ""
    for pref in URL_VARIANT_PREFERENCE:
        if pref in by_variant:
            chosen, variant = by_variant[pref], pref
            break
    if not chosen and by_variant:
        variant, chosen = next(iter(by_variant.items()))
    # `variant` says which copy `chosen` is: the Broken files re-download (moonglade.integrity)
    # must never take a THUMBNAIL fallback for an original. Every other caller ignores it.
    info = {"width": obj.get("width"), "height": obj.get("height"),
            "type": obj.get("type", ""), "variant": variant}
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
    if "svg" in ct:
        return ".svg"
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
             jpeg_quality=92, jpeg_bg="white", keep_webp=False, progress=None):
    """stem is a Path WITHOUT extension. Returns (status, final_path_or_None).

    `progress`, when given, is called as progress(bytes_so_far, content_length) after each
    chunk is written (content_length 0 when the response sends none): the Broken files list's
    byte bar (Session W) rides it. It only watches; it changes nothing about the download."""
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
                        if progress:
                            progress(nbytes, expect if enc == "identity" else 0)
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
    # Per-ROW too (2026-09-06): the deletedAt stamp on this image's own outputs.batch entry,
    # so a backfill marks the row of an image deleted from PixAI's website rather than
    # leaving it looking live. Blank for every live output and every non-batch task.
    "cloud_deleted_at",
)


def _paid_credit_str(task):
    """Catalog-string form of a task dict's server-reported `paidCredit` (the ACTUAL
    credit cost, known once the task ran). '' when the field is absent/null (unknown)
    -- never coerce that to '0', because '0' is a real, meaningful value (a free card
    or daily-free gen). Task-level: callers stamp it on each of the task's media rows."""
    v = (task or {}).get("paidCredit")
    return "" if v is None else str(v)


def gql_adhoc(session, query, variables=None, retries=None, timeout=120):
    """Run an ad-hoc (non-persisted) GraphQL operation by POSTing the full query
    document. PixAI's endpoint accepts these under Bearer auth (the API key has
    read+write scope), so NO persisted sha256Hash capture is needed -- this is the
    generic foundation for every read/write op, the history feed's page read (`gql`),
    task detail (`task_detail_gql`) and model detail (`_model_version_gql`) included.
    Returns the `data` dict; raises PixAIError on GraphQL/HTTP error.

    `timeout` is the per-attempt socket timeout in seconds (120 unless a caller says
    otherwise): `task_detail_gql` hands down the delete preview's remaining budget.

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
    return _pixai_client._client_of(session).query(query, variables, retries=retries, timeout=timeout)


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
    delete against a batch that already changed underneath it) and keeps `delete_task` on
    `rest_post`'s one POST, which has no retry loop.

    A 429 alone WOULD be safe to re-send (rate-limited means the request was refused, not
    processed), but 429 and 5xx share one branch in the retry loop and a 5xx is genuinely
    ambiguous. The trade is deliberate: not retrying costs an error the caller can see and
    act on; retrying wrongly costs credits they cannot get back.

    THIN DELEGATE onto `PixAIClient.mutate`, which likewise offers no `retries`
    parameter -- the rule now has ONE home rather than being re-argued at each helper."""
    return _pixai_client._client_of(session).mutate(query, variables)


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


def run_list_models(args):
    """CLI: search PixAI models and print name / type / generatable version id."""
    session = _make_session(getattr(args, "token", None))
    kw = getattr(args, "list_models", "") or ""
    results = _models.model_search_gql(session, kw, limit=getattr(args, "max", 0) or 25)
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
    # A video task carries ONE of two blocks, and both name the engine and the quality
    # tier the same way (`model`, `mode`). Reading only i2vPro left every reference-video
    # row's video_model / video_mode blank on every capture road (PROBE_2026-09-26 V09).
    vblock = i2v or (params.get("referenceVideo")
                     if isinstance(params.get("referenceVideo"), dict) else {})
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
        "video_mode":        str(vblock.get("mode") or ""),
        "video_model":       str(vblock.get("model") or ""),
        # BATCH IDENTITY (issue #33): blank at TASK level on purpose -- outputs.batch is an
        # ordered array with one entry per output, so the index is a per-ROW fact. The raw
        # list is parked under _batch (private, never persisted: _merge_full and the backfill
        # apply iterate _FULL_META_FIELDS only) and each row resolves its own index/size via
        # _with_batch_position. A task with no batch array (edit/upscale/video/chat) parks
        # None and every row of it stays blank -- "not a batch output", never inferred.
        "batch_index": "",
        "batch_size":  "",
        # Per-ROW for the same reason (2026-09-06): PixAI deletes one output at a time, so
        # "does PixAI still have this one" cannot be a task-level answer.
        "cloud_deleted_at": "",
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
    later keeps its gap, nothing is ever renumbered.

    A member PixAI has deleted (its entry carries `deletedAt`) reports blank: it is no
    longer one of the task's outputs, so it has no live output number. Its SURVIVING
    siblings are untouched -- they keep the numbers and the batch size PixAI gave them,
    because the deleted entry stays in the array and the site's own
    from-PixAI-<taskId>-<n> download names never shift either."""
    if not isinstance(batch, list) or not batch:
        return "", ""
    mid = str(media_id or "")
    if not mid:
        return "", ""
    for i, entry in enumerate(batch):
        if isinstance(entry, dict) and str(entry.get("mediaId") or "") == mid:
            if entry.get("deletedAt"):
                return "", ""
            return str(i), str(len(batch))
    return "", ""


def _with_batch_position(fm, media_id):
    """Per-ROW view of a task-level full-meta dict (issue #33): fm is fetched and cached
    once per task, but batch_index/batch_size differ per output, so each row resolves its
    own from the raw outputs.batch list extract_full_meta parked under fm['_batch'].
    Returns fm itself when there is nothing to resolve (no batch array, or the media id
    is not one of its outputs -- both fields stay ''), else a shallow copy with both set,
    leaving the shared cached dict untouched.

    `cloud_deleted_at` is the third per-row field and rides here for the same reason
    (2026-09-06): whether PixAI still has THIS image is a per-output fact the task-level
    meta cannot hold.

    WHEN THE MARKER IS ACTUALLY SET -- this path is the quieter of its two writers, and on
    a settled catalog it never fires at all. --backfill-full-meta re-fetches a row only when
    that row is missing its prompt or all of model/steps/sampler/CFG (or when --with-loras /
    --with-credit / --with-surface widen the net), so a row that already carries its detail
    is never revisited and never reaches this line. The writer that does the work in the
    ordinary case is the DELETE path: whenever the app reads a task back from PixAI for a
    delete -- the confirm dialog's question, the delete itself, and the Actions dropdown's
    bulk delete -- it stamps the row of every batch member that answer reports deleted
    (moonglade.gallery's /api/delete-image, and _rows_the_bulk_purge_must_keep).

    IT IS NOT ONLY HAND-RUN ANY MORE (2026-09-06, the living library). --backfill-full-meta
    is a STEP OF --sync (see the CLI's --sync handler: run_download, then this backfill,
    then fix-models), and --sync is one of LIVING_JOBS -- every six hours, enabled by
    default -- so this line is reachable unattended, on whatever rows that run was
    re-fetching anyway. The gate is unchanged and is what keeps it quiet: a row already
    carrying its detail is never revisited. --reconcile-deleted still writes only the
    task-level `deleted_remote` advisory and never looks inside a batch, and the
    fifteen-minute artworks_sweep and the weekly view-count job never touch this column."""
    batch = (fm or {}).get("_batch")
    bi, bs = batch_position(batch, media_id)
    gone = str((_cloud_delete.batch_entry(batch, media_id) or {}).get("deletedAt") or "")
    if not bi and not gone:
        return fm
    fm = dict(fm)
    if bi:
        fm["batch_index"], fm["batch_size"] = bi, bs
    if gone:
        fm["cloud_deleted_at"] = gone
    return fm


def _resolve_model_preset(session, version_id, _cache={}):
    """The model VERSION's default sampling params from its `extra` (`_model_version_gql`)
    -> {steps, sampler, cfg_scale}, each '' when the version exposes no default for it.
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
    try:
        # retries=0 (`_model_version_gql`: a single read, as before). Never raises out: a
        # refusal is caught here and the preset stays {} -- an em-dash is the honest answer
        # when a model genuinely exposes no default for a field.
        data = _models._model_version_gql(session, vid)
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
    name via model_name_gql (cached). Unresolvable ids keep the number. Empty string
    if the task used no LoRAs."""
    params = (task or {}).get("parameters") or {}
    lora = params.get("lora") or {}
    if not isinstance(lora, dict) or not lora:
        return ""
    parts = []
    for vid, weight in lora.items():
        name = _models.model_name_gql(session, vid)
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

      * `build_catalog_row` -- so EVERY create-time capture path builds its row in one
        place: run_sync_videos, run_import_local, run_generate, _download_video_task,
        _download_image_task, run_edit_image, and the gallery's /api/loom/import-bundle.
        The builder applies the merge, but only over the `known` map its CALLER hands it,
        so a site that omits `known` still writes a blanking row -- the shared builder
        removes the drift, not the need to pass the snapshot. (The Loom bundle import
        shipped omitting it, on a comment claiming its file-resolution guard proved the
        media_id was uncataloged; a catalog row outlives its file by design, so it did
        not.) The two collect writers
        (_download_image_task / _download_video_task) are the per-task path every
        create route funnels through -- run_generate, run_edit_image,
        run_generate_video, collect_generation, the watch mirror, CLI --task-id
        recovery -- and until 2026-09-03 they were missing it, so RE-collecting a task
        wiped exactly the fields listed above; a finished generation polled twice was
        enough to do it. Four of the seven builders still had no carry at all until the
        helper gave them one.
      * run_download's page saves, which build their rows from the feed rather than
        through build_catalog_row; `save_catalog_over_snapshot` applies the same rule.

    `known` is a snapshot, so it goes stale while a writer works: every writer that
    carries saves through `save_catalog_over_snapshot`, which merges over the rows as they
    are at write time and never writes back a row deleted meanwhile (2026-11-19: a Sync
    undid ratings, collections and deletes made in the gallery while it ran).
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
                                                               task's numeric modelId, else
                                                               the engine name (VID,
                                                               _video_row_model) / fm /
                                                               chat.modelId
      model_name         GEN, IMG, EDIT, VID                   _resolved_model_name /
                                                               _edit_model_label /
                                                               _video_row_model
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
    LOOM=moonglade.gallery's /api/loom/import-bundle."""
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
# Callable API (used by the GUI; also called by main() for the CLI)
# ---------------------------------------------------------------------------
def _make_session(token_val, resolve_user=True):
    """Validate config, load token, return a configured PixAIClient.

    `resolve_user=False` skips the USER_ID lookup (the `me` query, which retries three times)
    for a caller whose requests never use the user id -- the Broken files list's media
    re-downloads read /v1/media and the media object only.

    The app's ONE entry to PixAI: it re-reads config.json at call time (so the GUI works
    even when the module was imported before the working directory was set correctly),
    refreshes the legacy U3T/USER_ID overrides from it, builds the API-key requests.Session, and
    resolves USER_ID over the network when it is not pinned.

    It returns a `PixAIClient`, not the bare Session -- the client IS accepted everywhere a
    `session` is passed today (it delegates `get`/`post`/`headers`/`cookies` to the Session
    it holds, and every primitive resolves whatever it is handed through `_client_of`), so
    the ~70 session-taking functions are unchanged. The name stays `_make_session` because
    thirty-odd call sites and a hundred-odd tests say it."""
    global U3T, USER_ID
    fresh = _load_config()
    if fresh:
        U3T = fresh.get("U3T", "") or U3T
        USER_ID = fresh.get("USER_ID", "") or USER_ID
    have_api_key = bool((fresh or {}).get("PIXAI_API_KEY") or _cfg.get("PIXAI_API_KEY"))
    # No saved request needs a hash any more (#92), so the API-key path needs nothing but
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
    # Auto-resolve the user id from the API key when it isn't pinned in config. Asked through
    # the client, so a key PixAI refuses still resolves on the Mirror sign-in (a read).
    if not USER_ID and resolve_user:
        if have_api_key:
            try:
                USER_ID = resolve_user_id(
                    _pixai_client.PixAIClient(session, auth_kind="api-key", read_fallback=True))
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
    return _pixai_client.PixAIClient(session, auth_kind="api-key", user_id=USER_ID,
                                     read_fallback=True)


def run_probe(args):
    """Test API connection and resolve full-res media URL for the newest task."""
    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))
    print("Fetching newest page...\n")
    conn = find_connection(gql(session, page_variables(
        args.page_size, _pixai_client._client_of(session).user_id)))
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


def run_count(args):
    """Tally total tasks and images in the library without downloading."""
    session = _make_session(getattr(args, "token", None))
    count_size = getattr(args, "count_page_size", COUNT_PAGE_SIZE)
    print("Counting your whole library (page size {})...".format(count_size))
    before = None
    tasks = images = page = 0
    batched_tasks = 0
    while True:
        page += 1
        conn = find_connection(gql(session, page_variables(
            count_size, _pixai_client._client_of(session).user_id, before)))
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


# The owner's published artworks as a full query document. The selection is exactly what
# the two readers use (extract_artwork_meta, the sweep's page test and run_sync_artworks'
# video pass) and nothing else. It NEVER selects `views`: reading a view count counts as a
# view on every work the query returns (see artwork_views_bulk), and this read runs every
# fifteen minutes. Pages walk BACKWARD from the newest end (last / before), so the first
# page holds the newest works and `hasPreviousPage` / `startCursor` lead to the older ones.
_ARTWORK_LIST_DOC = (
    "query($a: ID!, $n: Int, $before: String, $lang: String) {"
    " artworks(authorId: $a, last: $n, before: $before) {"
    " edges { node { id mediaId videoMediaId title visibility isNsfw isSensitive"
    " likedCount commentCount aesScore tacks { codeName displayName(language: $lang) }"
    " extra } }"
    " pageInfo { hasPreviousPage startCursor } } }")


def _artwork_list_reason(exc):
    """Why an artwork-list read failed, in plain words: the kind of failure and PixAI's own
    message. A GraphQL refusal gives PixAI's error code and message; anything else gives the
    exception's class and text. Capped, and left unredacted: the caller that logs it knows
    which folders to hide."""
    errors = getattr(exc, "graphql_errors", None)
    said = []
    if isinstance(errors, list):
        for err in errors[:3]:
            if not isinstance(err, dict):
                continue
            ext = err.get("extensions") if isinstance(err.get("extensions"), dict) else {}
            kind = str(ext.get("code") or "").strip()
            msg = str(err.get("message") or "").strip()
            if kind or msg:
                said.append("{}: {}".format(kind, msg) if kind and msg else (kind or msg))
    if said:
        return "PixAI refused the request ({})".format("; ".join(said))[:300]
    text = str(exc).strip()
    return "{}{}".format(type(exc).__name__, ": " + text if text else "")[:300]


def artwork_list_gql(session, before=None, last=50, retries=None):
    """One page of the owner's own published artworks, read as a full query document
    (`_ARTWORK_LIST_DOC`) over the ad-hoc road. Returns the Relay connection dict (`edges`
    of `node`s, and `pageInfo` with `hasPreviousPage` / `startCursor`); `before` is the
    previous page's `startCursor`, and None starts at the newest end.

    A read that cannot be completed RAISES `ArtworkListRefused` carrying the reason in plain
    words (`_artwork_list_reason`): PixAI's refusal, a network failure, or an answer with no
    artwork list in it. It used to hand back None and swallow the reason, which left a
    failing fifteen-minute sweep logging a bare "page 1 fetch failed" with nothing to go on.
    Read-only (a query, never a mutation) and costs nothing; re-reading a page changes no
    number on PixAI's side. `retries` is gql_adhoc's: None keeps the default query retries
    (--sync-artworks, run by hand), and the fifteen-minute sweep passes 0 so a stalled PixAI
    costs it one attempt, not minutes -- the next sweep is the retry."""
    author = str(_pixai_client._client_of(session).user_id or "")
    if not author:
        raise ArtworkListRefused("the app has no PixAI account id to read artworks for")
    variables = {"a": author, "n": last, "lang": "en"}
    if before:
        variables["before"] = before
    try:
        data = gql_adhoc(session, _ARTWORK_LIST_DOC, variables, retries=retries)
    except (requests.RequestException, PixAIError, ValueError, TypeError) as e:
        raise ArtworkListRefused(_artwork_list_reason(e)) from e
    conn = find_connection(data or {})
    if conn is None:
        raise ArtworkListRefused("PixAI answered, but with no list of artworks in it")
    return conn


def artwork_views_bulk(session, page_size=40, delay=0.4, max_pages=60):
    """{artwork_id: views} for the owner's whole published library, in paced bulk pages.
    Returns (views, complete) -- `complete` False means a page failed and the map is a
    partial answer, never a total to present as whole.

    WHY THIS EXISTS AT ALL. Views are the one engagement number the artwork listing
    (artwork_list_gql) deliberately does not select, because reading one counts as a view and
    the listing is read every fifteen minutes. Fetching them one-artwork-at-a-time, live,
    is what made the My Art panel slow and its totals a subtotal. PROBE_2026-09-06 settled
    the open question: the AD-HOC bulk form `artworks(authorId, first:N)` -- already proven
    for field-probing by PROBE_2026-08-24 -- accepts `views`. A hundred works cost three
    calls here instead of a hundred, and they are paid once per sync rather than once per
    open.

    READING A VIEW COUNT COSTS A VIEW. The same probe measured it directly: a page that
    selects `views` increments the counter for EVERY artwork it returns (40 rows read, all
    40 up by one, repeatedly); a page that does not select `views` costs nothing. There is
    no way to observe this number without perturbing it, so the design goal is to observe
    it RARELY AND PREDICTABLY -- once per deliberate --sync-artworks -- rather than on
    every idle glance at a panel. views_spike() subtracts the sweep's own read before
    calling anything a spike; do not remove that subtraction on the theory that it is a
    rounding error, it is the difference between "nobody looked" and "+1 forever".

    SINGLE ATTEMPT, and that is not a style choice. Because the read PERTURBS the thing it
    reads, this is the same class of call `gql_mutate` exists for even though it is
    technically a query: a lost RESPONSE looks exactly like a lost REQUEST (a read timeout,
    a proxy's 502 arriving after PixAI already answered and already bumped the counters),
    so a retry re-reads -- and re-increments -- the same forty artworks inside one sweep.
    Those rows then carry +2 of the sweep's own making while views_spike subtracts exactly
    SPIKE_SELF_READ = 1, which permanently inflates their stored count and can push a
    borderline work over the floor into a false "is taking off" note. `retries=0` is
    therefore passed by hand here, the same way delete_batch_media_gql does for its own
    non-idempotent call; a page that fails falls into the except below and reports the
    sweep incomplete, which is the honest answer.

    Read-only in the sense that matters for the account: a query, never a mutation, and
    nothing here spends credits."""
    try:
        author = str(_pixai_client._client_of(session).user_id or "")
    except AttributeError:
        return {}, False
    if not author:
        return {}, False
    doc = ('query($a: ID!, $n: Int, $after: String) {'
           ' artworks(authorId: $a, first: $n, after: $after) {'
           ' edges { node { id views } } pageInfo { hasNextPage endCursor } } }')
    views, cursor, pages = {}, None, 0
    while pages < max_pages:
        pages += 1
        try:
            data = gql_adhoc(session, doc,
                             {"a": author, "n": int(page_size), "after": cursor}, retries=0)
        except (requests.RequestException, PixAIError, ValueError, TypeError):
            return views, False
        conn = ((data or {}).get("artworks")) or {}
        edges = conn.get("edges") or []
        for e in edges:
            n = (e or {}).get("node") or {}
            aid = str(n.get("id") or "")
            if aid and n.get("views") is not None:
                try:
                    views[aid] = int(n["views"])
                except (TypeError, ValueError):
                    pass
        pi = conn.get("pageInfo") or {}
        if not edges or not pi.get("hasNextPage"):
            return views, True
        cursor = pi.get("endCursor")
        if not cursor:
            return views, True
        time.sleep(delay)
    return views, False               # ran out of pages: partial, and says so


def extract_artwork_meta(node):
    """Pull the published-artwork fields we store from a node of the artwork list.
    Keyed by media_id so it merges onto the existing catalog row.

    The list's node already carries an `extra` block (no extra request), from which we
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
        # sensitive without being nsfw) -- already in the artwork list's answer, the app just
        # never read it (#20). Powers the "Sensitive" badge in My Art.
        "is_sensitive":  "1" if node.get("isSensitive") else "0",
    }


def run_sync_artworks(args):
    """Page the owner's published artworks (artwork_list_gql) and merge their
    metadata (title, published flag, NSFW flag, likes, comments, aes score, tags)
    onto matching catalog rows by media_id. Published artworks are a subset of
    generations, so unmatched/undownloaded ones are simply skipped.

    The merge is a set of NARROW per-row UPDATEs (apply_artwork_meta) of the eleven
    PixAI-owned columns, not a read-modify-write of the whole table -- see the long note
    at the merge itself for why that distinction is the difference between a refresh and
    a silent revert of everything another writer did while this walk was running.

    Returns {"artworks", "matched", "videos", "fail"} (B15) -- "fail" counts a
    pagination fetch that failed mid-run (artwork_list_gql raises ArtworkListRefused with
    the reason, and the first page's refusal ends the run) plus any video that failed to
    download after retries; a non-zero
    "fail" means this run is INCOMPLETE even though it didn't raise. Callers should
    thread it into _cli_job_finish(warn=...) the same way run_download's own callers
    thread dl['fail']."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    # Build the session FIRST -- _make_session auto-resolves USER_ID from the API key when it
    # isn't pinned in config.json. (Checking before this was the bug: it hard-failed on a config
    # that never lists USER_ID even though the key can resolve it.)
    session = _make_session(getattr(args, "token", None))
    if not _pixai_client._client_of(session).user_id:
        raise PixAIError("USER_ID is missing and could not be resolved from your API key. "
                         "Add USER_ID to config.json as a fallback.")

    # VIEWS-ONLY: the narrow run behind the Panel's own "View counts" job (owner's call,
    # 2026-09-06). The view read is the one part of this command that COSTS something --
    # one view on every published work -- so it gets its own cadence rather than riding
    # whatever cadence the metadata refresh happens to be on. In this mode the listing is
    # not walked at all: the counts join the catalog by artwork_id, which apply_artwork_meta
    # wrote on some earlier run, so nothing here needs the listing to have just happened.
    # It beats --no-views on purpose: a run whose whole purpose is the counts must not be
    # talked out of them by a flag the Panel adds for the OTHER job.
    views_only = bool(getattr(args, "views_only", False))

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
    if views_only:
        print("Reading view counts only -- the artwork listing is not walked this run.")
    else:
        print("Syncing published artworks...")
    while not views_only:
        page += 1
        try:
            conn = artwork_list_gql(session, before=before, last=50)
        except ArtworkListRefused as e:
            if page == 1:
                raise PixAIError(
                    "Could not read your published artworks, so nothing was synced. "
                    "{}.".format(e)) from e
            # B15: a page after the first that cannot be read is not "no more pages". Treat
            # it exactly like the download-retry-exhausted case: whatever was already
            # collected is real and worth keeping, but the run is INCOMPLETE, not a clean
            # finish -- it must not report a total that looks whole. The reason is printed
            # with it, so the run says why it stopped.
            incomplete = True
            print("\n  page {} could not be read ({}) -- stopping pagination early. "
                  "Results below are INCOMPLETE, not a full sync.".format(page, e))
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

    # VIEWS SWEEP (2026-09-06). A SECOND, ad-hoc pass over the same library, because the
    # listing above never selects `views` (reading one counts as a view) -- see
    # artwork_views_bulk.
    # Runs only when the listing itself found something (no point pricing a sweep against a
    # library we failed to enumerate).
    #
    # A SUPPLEMENTARY READ IN ITS OWN GUARD, exactly like /api/account's credit-split call:
    # it must never turn a successful metadata sync into a failed run. `incomplete` above
    # means one specific thing -- the ARTWORK LISTING is partial, so the counts printed
    # below are not the whole library -- and a views sweep that could not reach PixAI says
    # nothing about that. It reports itself separately (`views_complete` in the return) and
    # merges whatever it did get; the rows it missed keep their previous reading.
    views_map, views_ok = {}, False
    want_views = views_only or (artworks and not getattr(args, "no_views", False))
    if want_views and (READ_ONLY or _read_only_now()):
        # READ_ONLY IS A PROMISE ABOUT THE ACCOUNT, and this read changes it. Asking PixAI
        # how many views a work has ADDS ONE to that number, for every work the query
        # returns -- there is no way to look without it counting -- so the sweep is an
        # account-touching call and belongs on the same side of the switch as publishing
        # and deleting. Refused out loud rather than silently, and the metadata half below
        # keeps working: READ_ONLY has never stopped browsing, backing up or searching.
        # Skipped rather than raised, because the rest of this run is a plain read and
        # taking it down with the sweep would be its own bug.
        print("READ_ONLY is set in config.json -- skipping the view-count sweep. "
              "Reading a view count adds one to it on PixAI, so it is a change to your "
              "own numbers there, not just a look.")
        want_views = False
    if want_views:
        print("Sweeping view counts (bulk artworks query)...")
        views_map, views_ok = artwork_views_bulk(
            session, delay=getattr(args, "delay", 0.4))
        print("  views for {} artwork(s){}".format(
            len(views_map), "" if views_ok else "  -- INCOMPLETE, a page failed"))

    # THE MERGE -- narrow per-row UPDATEs, never a whole-catalog round trip.
    #
    # This used to be `load_catalog -> edit the matched rows in memory -> save_catalog`:
    # read all ~36k rows, then upsert EVERY column of EVERY row back from a snapshot taken
    # after a walk that can run for minutes. That is correct only while this process is the
    # library's ONLY writer -- and since the living library (2026-09-06) it plainly is not.
    # The artworks sweep writes these same rows every fifteen minutes, on every publish and
    # at boot; the owner's ratings and collections land from the browser at any moment. Any
    # write that landed between this run's read and its save was silently reverted, across
    # EVERY column of EVERY row -- ratings and collections included, which this sync has no
    # business touching at all. It is the same lost-update class the September carry fixes
    # closed for the download writers, still open here because this function predates them.
    #
    # apply_artwork_meta (moonglade.gallery) is the row-level twin the sweep already uses:
    # one UPDATE per artwork actually seen, of exactly the eleven PixAI-owned columns
    # extract_artwork_meta fills, keyed by media_id. Rows this sync never saw are not
    # written at all, so they cannot be reverted; a locally-authored column is not in the
    # statement, so it cannot be reached. It also never invents a row, so "unmatched
    # artworks have no downloaded image" still holds by construction rather than by the
    # merge loop happening not to add any.
    #
    # `matched` means exactly what it always did: SQLite's rowcount for an UPDATE is the
    # number of rows whose WHERE matched, which is the number of catalog rows this artwork
    # listing reached.
    metas = {}
    for vmid, m in by_video_mid.items():
        # An animation's catalog row is keyed by its MP4's media_id, not the poster
        # `mediaId` the node carries (#20) -- so it wants the same metadata under THAT key.
        metas[vmid] = dict(m, media_id=vmid)
    for mid, m in by_mid.items():
        # A still's own row wins any collision between the two maps, exactly as the old
        # `by_mid.get(...) or by_video_mid.get(...)` did.
        metas[mid] = m
    matched = apply_artwork_meta(db_path, list(metas.values())) if metas else 0

    # The views half of the same merge, in its own narrow statement (apply_artwork_views).
    # It runs AFTER the meta write on purpose: the sweep is keyed by ARTWORK id and the
    # catalog row is keyed by media_id, so the artwork_id apply_artwork_meta has just
    # written is the join -- including for an animation, whose mp4 row learns its
    # artwork_id from the re-keying above (#20). Rows the sweep missed are not in the map
    # and are not written, so a partial sweep leaves the last reading anyone took.
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    viewed = apply_artwork_views(db_path, views_map, now_iso) if views_map else 0
    if not views_only:
        print("\nArtworks fetched: {}.  Matched to catalog rows: {}.  "
              "(Unmatched artworks have no downloaded image.)".format(artworks, matched))
    if viewed:
        print("View counts written to {} row(s).  Note: reading a view count registers "
              "a view, so this sweep added 1 to each.".format(viewed))

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

    return {"artworks": artworks, "matched": matched, "videos": vids_ok, "fail": fail,
            "views": viewed, "views_complete": views_ok}


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
            _pixai_client._client_of(session).user_id, before)))
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
    from moonglade.gallery import make_thumbnail
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
                _media_tools.video_poster_thumb(video_path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the sync
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(video_media_id, e))

    # 2. Per task: getTaskById -> video outputs -> fileUrl -> download mp4.
    def _do_task(node):
        task = _task_reads.task_detail_gql(session, node["id"])
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
                _media_tools.video_faststart(path)                # iOS needs moov at the front to stream
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
        save_catalog_over_snapshot(db_path, new_rows, known)   # carried in build_catalog_row; merged over the rows as they are NOW
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
    if not _media_tools.ffmpeg_path():
        print("ffmpeg not found on PATH; cannot faststart.")
        return {"fixed": 0, "skipped": 0, "failed": 0, "total": len(vids)}
    print("Faststart pass over {} video(s) in {}...".format(len(vids), vdir), flush=True)
    fixed = skipped = 0
    failures = []
    for i, p in enumerate(vids, 1):
        outcome = _media_tools._video_faststart_attempt(p)
        if outcome == _media_tools.FASTSTART_REWROTE:
            fixed += 1
            print("  [{}/{}] faststart -> {}".format(i, len(vids), p.name), flush=True)
        elif outcome == _media_tools.FASTSTART_REFUSED:
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
    from moonglade.gallery import make_thumbnail
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
            _media_tools.video_poster_thumb(stored, thumb_dir / "{}.jpg".format(mid))  # ffmpeg, optional
            _media_tools.video_faststart(stored)                  # iOS needs moov at the front to stream
        else:
            make_thumbnail(stored, thumb_dir / "{}.jpg".format(mid))
        made += 1
        vlog("imported {} ({})".format(rel, "video" if is_vid else "image"))

    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
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
    # A user-trained DiT.3. PixAI's stepUp table (`Ua`) puts it in the same 0..1.2 range as
    # every other DiT family (bundle, 2026-09-26; SCOPE_2026-09-26 G8).
    "USER_DIT26B_MODEL": (0.0, 1.2),
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


# ---- Colour palettes (Session H decision 4, 2026-09-28) ------------------------------------
# PixAI's shape, from its own contract: a palette is {overall?, background?, character?}, each
# group {colors: [{hex: "#RRGGBB", ratio: 0-100}]} with 1-12 colours, and overall or background
# must be present. A generation carries colorPalette: {name, palette} (the task-parameter
# schema), which the Generate drawer builds (gallery/src/gen/colorPaletteCore.js). The official
# palettes are one read-only GET; a user's own palettes live in the app's per-account store,
# never on PixAI (saving there is a write this app does not make).
PALETTE_GROUPS = ("overall", "background", "character")
PALETTE_MAX_COLORS = 12
PALETTE_NAME_MAX = 50
PALETTE_NAME_DEFAULT = "Custom palette"
_PALETTE_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _palette_ratio(raw):
    """A colour's share as PixAI takes it: a number 0-100, sent as a whole percent. None when
    it is not a number in range."""
    if isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0 or v > 100:                    # NaN or out of range
        return None
    return int(round(v))


def _palette_group_colors(raw):
    """[{hex, ratio}] from one palette group, or None when it is not a valid group: a list of
    1-12 colours, each a #RRGGBB hex (upper-cased) and a 0-100 ratio (a whole percent)."""
    colors = raw.get("colors") if isinstance(raw, dict) else None
    if not isinstance(colors, list) or not 1 <= len(colors) <= PALETTE_MAX_COLORS:
        return None
    out = []
    for c in colors:
        hx = c.get("hex") if isinstance(c, dict) else None
        ratio = _palette_ratio(c.get("ratio")) if isinstance(c, dict) else None
        if not isinstance(hx, str) or not _PALETTE_HEX_RE.match(hx.strip()) or ratio is None:
            return None
        out.append({"hex": hx.strip().upper(), "ratio": ratio})
    return out


def clean_color_palette(raw):
    """The web payload's `color_palette` -> the task parameter `colorPalette`
    ({name, palette}), or None when the payload carries none (absent, null, or an empty
    object -- the drawer leaves the key out when no palette applies).

    Anything PixAI's own schema would refuse is refused HERE, before any network call, as a
    builder refusal (PixAIError): the badge shows it as its note, the create route returns
    it, and nothing is created or charged. Groups other than overall/background/character
    are refused rather than dropped (a dropped group would change the picture asked for)."""
    if raw is None or (isinstance(raw, dict) and not raw):
        return None
    bad = "The colour palette isn't valid: "
    if not isinstance(raw, dict) or not isinstance(raw.get("palette"), dict):
        raise PixAIError(bad + "it has no colour groups (nothing was sent or charged)")
    pal = raw["palette"]
    extra = [k for k in pal if k not in PALETTE_GROUPS]
    if extra:
        raise PixAIError(bad + "unknown group {} (nothing was sent or charged)".format(
            ", ".join(sorted(str(k) for k in extra))[:40]))
    out = {}
    for k in PALETTE_GROUPS:
        if pal.get(k) is None:
            continue
        colors = _palette_group_colors(pal[k])
        if colors is None:
            raise PixAIError(bad + "{} needs 1 to 12 #RRGGBB colours with 0-100 shares "
                                   "(nothing was sent or charged)".format(k))
        out[k] = {"colors": colors}
    if "overall" not in out and "background" not in out:
        raise PixAIError(bad + "it needs overall or background colours "
                               "(nothing was sent or charged)")
    name = raw.get("name")
    name = name.strip() if isinstance(name, str) else ""
    return {"name": (name or PALETTE_NAME_DEFAULT)[:PALETTE_NAME_MAX], "palette": out}


def color_palette_presets(session):
    """PixAI's official colour palettes -- GET /v2/color-palettes/presets, READ-ONLY -- as
    [{id, name, cover_url, palette}], each palette holding only its valid groups (a group that
    fails _palette_group_colors is left out; a preset left with neither overall nor background
    is skipped). `cover_url` is PixAI's CDN thumbnail as given, or "". Raises on a failed read;
    the caller decides how to fail soft."""
    data = _rest_get(session, "/color-palettes/presets")
    rows = (data or {}).get("palettes") if isinstance(data, dict) else None
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        raw = r.get("palette") if isinstance(r.get("palette"), dict) else {}
        pal = {}
        for k in PALETTE_GROUPS:
            colors = _palette_group_colors(raw.get(k))
            if colors:
                pal[k] = {"colors": colors}
        if "overall" not in pal and "background" not in pal:
            continue
        cover = r.get("coverUrl")
        out.append({"id": str(r.get("id") or ""),
                    "name": str(r.get("name") or "")[:PALETTE_NAME_MAX] or "Palette",
                    "cover_url": cover if isinstance(cover, str) else "",
                    "palette": pal})
    return out


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
    # Session H: the drawer's context images go out as they are (catalog / upload ids, never
    # through an input resolver -- the quote and the spend build the identical list). Only the
    # web namespace carries the attribute, so the CLI's shape is unchanged.
    ctx_ids = list(getattr(args, "context_images", None) or [])
    if ctx_ids:
        params["contextImages"] = ctx_ids
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
    # Colour palette: {name, palette}, already cleaned by clean_color_palette. Emitted only
    # when asked for, so every other submit is byte-identical; the gate strips it where the
    # model cannot take it (and says so).
    cpal = getattr(args, "color_palette", None)
    if cpal:
        params["colorPalette"] = cpal
    qtag = str(getattr(args, "quality_tag", "") or "").strip()
    # Quality Tag is MEMBERS-ONLY on PixAI -- crowned in their Add Booster menu on every
    # model, and their own guide says "member-only" in writing. This app was never built to
    # get around their systems (owner, 2026-07-28), so an account PixAI reports as
    # non-member does not send the gated parameter. `is_member` is True/False/None from
    # core.account_is_member(); only an explicit False gates, so an unreadable account still
    # submits exactly as before.
    if qtag and getattr(args, "is_member", None) is False:
        qtag = ""
    # SCOPE_2026-09-26 G4: the web road resolves the booster to the chosen VERSION's own tag
    # ({prefix, suffix}, extra.qualityTags[0]) at build time and hands it over here; the CLI
    # never sets it, so `--quality-tag` still sends {"prefix": <text>} exactly as before.
    qobj = getattr(args, "quality_tag_obj", None)
    if qtag and isinstance(qobj, dict):
        params["qualityTag"] = {"prefix": str(qobj.get("prefix") or ""),
                                "suffix": str(qobj.get("suffix") or "")}
    elif qtag:
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
VIDEO_DURATIONS = (5, 6, 10, 15)                  # 15: VIDEO_15S_MODELS only; per engine: VIDEO_MODEL_DURATIONS

# Video model registry: the `.model` NAME a submit carries -> its numeric top-level
# `modelId` (+ a UI label). A real (card-covered) submit carries BOTH; WITHOUT the modelId
# PixAI resolves "Unknown or removed model" and no free card can match -- that was the
# "video card won't tap" bug. All five VERIFIED via --dump-params of real gens (2026-07-06).
VIDEO_MODELS = {
    "v4.0.1": {"model_id": "2003969750675682808", "label": "V4.0 Lite Preview"},
    "v4.0":   {"model_id": "2003968021137101826", "label": "V4.0 Preview (full)"},
    # The two Tsubaki video engines (PROBE_2026-09-26 V01/V13). The ids are the ones PixAI
    # stamped on the owner's own tbkv tasks (2060014126868040808 -> tbkv1.0,
    # 2060390260986220957 -> tbkv1.0.1), and the labels are the version titles a read-only
    # getGenerationModelByVersionId returns for those ids. The site itself never sends a
    # numeric modelId for video -- the server maps the name. This app sends these ids on the
    # REFERENCE path only (SCOPE_2026-09-26 V2: its own id, never v4.0.1's; the probe priced a
    # tbkv1.0.1 reference video the same with its own id, v4.0.1's and none). A tbkv i2vPro
    # carries NO top-level modelId, as on the site -- see VIDEO_I2V_NO_MODELID_MODELS.
    "tbkv1.0.1": {"model_id": "2054378086834851904", "label": "Tsubaki Video"},
    "tbkv1.0":   {"model_id": "2042030623542642408", "label": "Tsubaki Video Flash"},
    "v3.2":   {"model_id": "1961182207978260675", "label": "V3.2"},
    "v3.0.2": {"model_id": "2014412117889628958", "label": "V3.0 Lite"},
    "v3.0":   {"model_id": "1919508300549460046", "label": "V3.0"},
    # No numeric modelId published for these two, and none is needed -- `i2vPro.model`
    # resolves the engine (see build_video_parameters). Listed so the roster is complete
    # and video_model_id() returns '' for them deliberately, not by accident.
    "v3.0.1": {"model_id": "", "label": "V3.0 Flash"},
    "v2.7":   {"model_id": "", "label": "V2.7 (High Dynamics)"},
}


# PixAI retires V3.2 video on 2026-11-23 03:00 UTC (their announcement, 10 Nov 2026). From that
# instant this app stops offering it and refuses a submit that names it, before any network call.
# The front end keeps a mirror of this table (gallery/src/gen/videoDrawerCore.js
# VIDEO_MODEL_RETIRED) because its engine list is static JS; a parity test holds the two together.
# VIDEO_MODELS keeps the entry so old V3.2 videos in the library keep their "V3.2" label.
VIDEO_MODEL_RETIRED = {"v3.2": "2026-11-23T03:00:00Z"}


def _video_clock():
    """Now, in UTC. A seam so a test can stand either side of the retirement instant."""
    return datetime.datetime.now(datetime.timezone.utc)


def video_model_retired(model, now=None):
    """True from the instant PixAI retires this video engine (VIDEO_MODEL_RETIRED)."""
    when = VIDEO_MODEL_RETIRED.get(str(model or "").strip())
    if not when:
        return False
    cut = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
    now = now or _video_clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now >= cut


def check_video_model_retired(model, now=None):
    """Refuse a retired engine in plain words (PixAIError, raised before any network call, so
    nothing is created or charged)."""
    if video_model_retired(model, now):
        name = str(model).strip()
        label = (VIDEO_MODELS.get(name) or {}).get("label") or name
        when = datetime.datetime.strptime(VIDEO_MODEL_RETIRED[name], "%Y-%m-%dT%H:%M:%SZ")
        raise PixAIError("{} was retired by PixAI on {} {} -- pick another video engine "
                         "(nothing was created or charged).".format(
                             label, when.day, when.strftime("%b")))


def _params_video_models(params):
    """The video engine names a createGenerationTask `parameters` carries (i2vPro.model /
    referenceVideo.model); empty for anything that is not a video submit."""
    out = []
    if isinstance(params, dict):
        for key in ("i2vPro", "referenceVideo"):
            blk = params.get(key)
            if isinstance(blk, dict) and blk.get("model"):
                out.append(blk["model"])
    return out


def check_params_retired(params, now=None):
    """Refuse a `parameters` object that names a retired video engine, whoever built it.

    The builders check the engine they are handed, but a raw `--params-json` never passes
    through a builder, and the three CLI create roads (--generate-video, --reference-video,
    --edit-image) send their mutation directly rather than through submit_generation. Each
    calls this as soon as it has its parameters, before any network call (2026-11-19)."""
    for _vm in _params_video_models(params):
        check_video_model_retired(_vm, now)


def video_model_id(name):
    """Numeric top-level `modelId` for a video `.model` name ('' if unknown). A submit MUST
    include this or PixAI can't resolve the model and no free card can match."""
    return (VIDEO_MODELS.get((name or "").strip()) or {}).get("model_id", "")


def _video_model_id_fits(engine, model_id):
    """Is `model_id` a version id this video engine's row may carry (and be titled from)?
    An engine VIDEO_MODELS knows takes only its own id, so v2.7 / v3.0.1 (no id) take none:
    their real tasks carry 1648918127446573124, an IMAGE checkpoint. An engine the roster
    does not know (or a row with no engine recorded) takes any id, as before."""
    engine = str(engine or "").strip()
    if engine not in VIDEO_MODELS:
        return True
    return str(model_id or "").strip() == video_model_id(engine) != ""


VIDEO_CHANNELS = ("private", "normal")   # private = the site's "Private" channel (was "Enhanced" until 2026-08-18)


# --- Per-engine capability tables (Tsubaki video, PROBE_2026-09-26 V03-V06) ---------------
# Video models have no /features, /inference-profiles or /size-config data (both tbkv ids
# answer empty lists there), so these are hand-kept tables checked against the site's own
# panel matrix (helper--EEE6Q9r.js `I()`, the i2vPro field picker `X`) and tools.json. An
# engine ABSENT from a table keeps today's behaviour exactly -- every table here only ever
# narrows what a listed engine is sent.
TSUBAKI_VIDEO_MODELS = ("tbkv1.0", "tbkv1.0.1")

# Allowed durations per engine. The tbkv panel offers 5/10/15 (default 5) with or without a
# tail frame, and the stored i2vPro schema has only ever allowed "5"/"10"/"15". Absent =>
# VIDEO_DURATIONS (the existing engines keep their 6 s stop, unchanged by this table).
VIDEO_MODEL_DURATIONS = {m: (5, 10, 15) for m in TSUBAKI_VIDEO_MODELS}

# Engines whose panel has no negative prompt / no camera movement. The site's picker `X`
# adds negativePrompts / cameraMovement only when the panel enables them, and the tbkv panel
# enables neither. Other engines are unchanged on purpose: a v4.0.1 i2vPro with a negative
# is on the wire (task 2058947728431110088) and rendered.
VIDEO_NO_NEGATIVE_MODELS = TSUBAKI_VIDEO_MODELS
VIDEO_NO_CAMERA_MODELS = TSUBAKI_VIDEO_MODELS

# Multi-Reference caps per engine (the tbkv panel's multiReference `D`: images 6, videos 0,
# audio 3). Only the VIDEO cap is enforced at build time (a video reference sent to an
# engine that takes none); absent => no cap here, as today.
VIDEO_REF_CAPS = {m: {"images": 6, "videos": 0, "audios": 3} for m in TSUBAKI_VIDEO_MODELS}

# referenceVideo.ratio: tbkv-only, reference-path only, the 9 values of the site's `Qe`.
# Omitted (or "adaptive") lets PixAI infer the ratio from the references.
VIDEO_RATIO_MODELS = TSUBAKI_VIDEO_MODELS
VIDEO_RATIOS = ("adaptive", "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")

# i2vPro engines that go out with NO top-level modelId, whatever VIDEO_MODELS knows. No tbkv
# i2vPro task exists yet, from the site or from this app (PROBE_2026-09-26 V02 and its open
# capture: "the modelId it stamps" is unobserved). The site's i2vPro submit sends the name only,
# and the probe's tbkv i2vPro price quotes (21,000 for 5 s, 63,000 for 15 s) were taken on that
# shape. So the unobserved field stays at today's behaviour -- omitted, as it was before tbkv
# joined VIDEO_MODELS -- and the owner's first First Frame run tests one new thing, not two.
# Remove an engine from here once a real tbkv i2vPro task shows what the server stamps.
VIDEO_I2V_NO_MODELID_MODELS = TSUBAKI_VIDEO_MODELS


def video_model_durations(model):
    """The durations (seconds) this engine accepts -- its own set when VIDEO_MODEL_DURATIONS
    lists it, else the shared VIDEO_DURATIONS."""
    return VIDEO_MODEL_DURATIONS.get(str(model or "").strip(), VIDEO_DURATIONS)


def _check_video_ref_caps(model, video_media_ids):
    """Refuse video references an engine cannot take (PixAIError at BUILD time: the badge
    shows it as its note and nothing is created or charged). Only engines listed in
    VIDEO_REF_CAPS are capped; the drawer holds such refs back and never sends them, so this
    is the backstop for the CLI and a hand-rolled payload."""
    cap = (VIDEO_REF_CAPS.get(str(model or "").strip()) or {}).get("videos")
    n = len([v for v in (video_media_ids or []) if str(v).strip()])
    if cap is not None and n > cap:
        label = (VIDEO_MODELS.get(str(model).strip()) or {}).get("label") or model
        if cap == 0:
            raise PixAIError("{} takes no video references -- remove the {} video "
                             "reference{} (nothing was created or charged).".format(
                                 label, n, "" if n == 1 else "s"))
        raise PixAIError("{} takes at most {} video references, not {} -- remove {} "
                         "(nothing was created or charged).".format(label, cap, n, n - cap))


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
    we still send it whenever VIDEO_MODELS knows one -- except on the Tsubaki engines, whose
    i2vPro goes out in the site's name-only shape until a real task shows what the server
    stamps (VIDEO_I2V_NO_MODELID_MODELS). When it doesn't (v2.7, v3.0.1 -- no
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
    check_video_model_retired(model)
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
    # Neither field on an engine whose panel has none (VIDEO_NO_NEGATIVE_MODELS /
    # VIDEO_NO_CAMERA_MODELS): the tbkv i2vPro block carries only the site's picker `X`
    # fields. The tbkv i2vPro half is bundle-grounded and price-quoted, not yet on the wire;
    # an unsupported field is how v3.0.2's audio flag came back as a false NSFW refusal.
    if negative and str(model).strip() not in VIDEO_NO_NEGATIVE_MODELS:
        i2v["negativePrompts"] = negative
    # cameraMovement is v2.7-style camera-dropdown; only send when a real move is picked
    # (the verified v4.0 submit omits it entirely -> keep it out by default).
    if (camera_movement and camera_movement != "unset"
            and str(model).strip() not in VIDEO_NO_CAMERA_MODELS):
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
    # A Tsubaki i2vPro sends no modelId at all, even one passed in (VIDEO_I2V_NO_MODELID_MODELS).
    _mid = ("" if str(model).strip() in VIDEO_I2V_NO_MODELID_MODELS
            else str(model_id or video_model_id(model)))
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
                                     model_id=None, duration=5,
                                     mode="professional", generate_audio=False,
                                     audio_language="english", is_private=False,
                                     priority=1000, kaisuuken_id="", ratio="",
                                     input_video_durations=None):
    """Build createGenerationTask `parameters` for a REFERENCE video (multi-image / video /
    audio reference). VERIFIED shape (2026-07-02) -- a top-level `referenceVideo` block,
    NOT i2vPro. The prompt references inputs by position with @image1/@video1/@audio1
    mentions. `duration` is an int here; channel maps to `isPrivate`. Builder spends nothing.

    `model_id` defaults to THIS model's own numeric id (video_model_id), and the key is
    omitted when there is none -- the i2v builder's rule. It used to default to v4.0.1's id,
    so a reference video on any other engine went out paired with a different model's id
    (PROBE_2026-09-26 V02); a quote does not move with it (the three modelId variants of a
    tbkv1.0.1 reference video all priced 63,000), but the free-card match keys on it.

    `ratio` is sent only for the Tsubaki engines (VIDEO_RATIO_MODELS), one of VIDEO_RATIOS,
    and omitted when empty or "adaptive" (PixAI's contract: omitted = adaptive = inferred
    from the references). It is PROVEN only on the site's REST reference-video route; this
    app submits `referenceVideo` over GraphQL, where acceptance is unobserved (probe capture
    item). A refusal is not retried -- the spend path's single attempt stands.

    `input_video_durations` is each reference video's length in seconds, in
    `referenceVideoMediaIds` order, or None/[] for the old empty list. The caller decides
    all-or-nothing (see input_video_durations()); this only sends what it is given, as
    positive floats. PixAI floors each entry and bills the output seconds PLUS the input
    seconds; an empty list is priced as a flat 15 s of input in total."""
    check_video_model_retired(model)
    _check_video_ref_caps(model, video_media_ids)
    rv = {
        "mode": mode,
        "model": model,
        "prompt": prompt or "",
        "duration": int(duration),
        "inputVideoDurations": [float(d) for d in (input_video_durations or [])],
        "referenceAudioMediaIds": [str(m) for m in (audio_media_ids or [])],
        "referenceImageMediaIds": [str(m) for m in (image_media_ids or [])],
        "referenceVideoMediaIds": [str(m) for m in (video_media_ids or [])],
    }
    r = str(ratio or "").strip()
    if r and str(model).strip() in VIDEO_RATIO_MODELS:
        if r not in VIDEO_RATIOS:
            raise PixAIError("aspect ratio {!r} is not one PixAI takes -- use one of {} "
                             "(nothing was created or charged).".format(r, ", ".join(VIDEO_RATIOS)))
        if r != "adaptive":
            rv["ratio"] = r
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
    }
    _mid = str(video_model_id(model) if model_id is None else (model_id or ""))
    if _mid:                                  # omit rather than send "" -- see docstring
        params["modelId"] = _mid
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)
    return params


def input_video_durations(video_media_ids, lookup):
    """referenceVideo.inputVideoDurations for these reference videos, ALL OR NOTHING.

    Returns (durations, unknown): each video's length from `lookup(media_id)` (seconds or
    None) in the given order when every one is known and positive, else ([], True) -- the
    exact list the app always sent before, never a partial one (a short list is priced as a
    flat 15 s of input in total, and which positions it would cover is unobserved). `unknown`
    is False when there are no video references at all, or when every length resolved.
    A `lookup` of None (a caller with no library to read) is the old behaviour."""
    vids = [str(v) for v in (video_media_ids or []) if str(v).strip()]
    if not vids:
        return [], False
    if lookup is None:
        return [], True
    out = []
    for v in vids:
        try:
            secs = lookup(v)
            secs = float(secs) if secs is not None else None
        except (TypeError, ValueError, OSError, PixAIError):
            secs = None
        if secs is None or not secs > 0:                     # None, <= 0 (or NaN)
            return [], True
        out.append(secs)
    return out, False


# The receipt line a reference video carries when a length could not be read. Worded to the
# probe's finding, not to a direction: PixAI prices a missing list as a flat 15 s of input in
# TOTAL, which is more than one short clip and less than two long ones.
INPUT_VIDEO_UNKNOWN_WHY = ("input video length unknown — PixAI prices a flat 15 s of input "
                           "in total")


def make_video_duration_lookup(out_dir, db_path=None):
    """A reference video's real length in seconds, or None -> RequestResolver.video_duration.

    Order (SCOPE_2026-09-26 V5): the local file's measured length (media_tools.duration on
    the file the gallery's one video resolver finds -- the catalog filename, else the
    media-id matcher); else the catalog's `video_duration` (the clip's REQUESTED length --
    acceptable because PixAI floors each entry, and a 10 s output measures ~10.04 s); else
    None. No network read, ever: /api/price runs this on every keystroke.

    The answer is cached per media id for the life of the returned callable (one per gallery
    app, one per CLI run), so a quote and the spend that follows it read the same number even
    if a file lands in between, and a miss does not re-walk the library per keystroke."""
    from moonglade.gallery import get_row
    from moonglade.scan import find_local_video_file
    out = Path(out_dir)
    dbp = Path(db_path) if db_path else out / "catalog.db"
    cache = {}
    lock = threading.Lock()

    def _lookup(media_id):
        mid = str(media_id or "").strip()
        if not mid:
            return None
        with lock:
            if mid in cache:
                return cache[mid]
        row = {}
        try:
            if dbp.is_file():
                row = get_row(dbp, mid) or {}
        except Exception:                            # noqa: BLE001 -- a lookup never breaks a quote
            row = {}
        secs = None
        try:
            f = find_local_video_file(out, mid, row)
            if f is not None:
                secs = _media_tools.duration(str(f))
        except Exception:                            # noqa: BLE001
            secs = None
        if secs is None or not secs > 0:
            try:
                secs = float(row.get("video_duration") or 0) or None
            except (TypeError, ValueError):
                secs = None
            if secs is not None and not secs > 0:
                secs = None
        with lock:
            cache[mid] = secs
        return secs
    return _lookup


# Only the v4.0 family renders a 15-second clip. VIDEO_DURATIONS has carried the note
# "15 is v4.0-only" since it was banked, but nothing enforced it, so a 15s request on any
# other model went straight to PixAI, which refuses the mutation -- no task is created, so
# nothing appears on the account and the client shows an instant unexplained decline. A rule
# that lives only in a comment is not a rule.
# The Tsubaki engines render 15 s too: both of the owner's tbkv tasks (2060014126868040808,
# 2060390260986220957) are 15 s reference videos, and the tbkv panel offers 5/10/15
# (PROBE_2026-09-26 V04 -- before this they silently snapped a 15 s request down to 10).
VIDEO_15S_MODELS = ("v4.0", "v4.0.1", "tbkv1.0", "tbkv1.0.1")


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
#   tbkv1.0    generateAudio=True audioLanguage=english     <- audio supported (2026-09-26:
#   tbkv1.0.1  generateAudio=True audioLanguage=english        both on the wire; the tbkv
#                                                              panel has audioLanguage)
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
VIDEO_AUDIO_MODELS = ("v3.2", "v4.0", "v4.0.1", "tbkv1.0", "tbkv1.0.1")


def _snap_video_duration(d, model=""):
    """Snap a requested duration (seconds) to the nearest allowed PixAI video length.

    `model` (optional) additionally enforces the engine's own rules: an engine listed in
    VIDEO_MODEL_DURATIONS snaps to ITS set (6 -> 5 on a Tsubaki engine, whose panel and stored
    schema have no 6), and 15 is VIDEO_15S_MODELS-only, so any other model snaps down to 10
    rather than being sent a length PixAI will reject. Omitting `model` keeps the original
    model-blind behavior exactly, which is what the CLI's own preview path and the pre-existing
    tests pin."""
    try:
        d = float(d)
    except (TypeError, ValueError):
        return 5
    allowed = video_model_durations(model) if model else VIDEO_DURATIONS
    snapped = min(allowed, key=lambda v: abs(v - d))
    if snapped == 15 and model and str(model).strip() not in VIDEO_15S_MODELS:
        return 10
    return snapped


def build_shot_video_params(mode, prompt, image_ids=(), video_ids=(), audio_ids=(),
                            *, duration=5, generate_audio=False, model="",
                            audio_language="english", camera_movement="",
                            quality="professional", negative="", is_private=False,
                            use_prompt_helper=False, input_video_durations=None, ratio=""):
    """PixAI video PROVIDER ADAPTER: map a Loom shot (mode + prompt + @-ordered ref
    media_ids) to createGenerationTask video params. This is the SEAM a future Seedance/
    other provider mirrors -- same shot spec in, provider-native params out. I2V/FLF ->
    i2vPro; R2V/V2V/any-with-refs -> referenceVideo. Duration snaps to PixAI's allowed
    lengths. (Card auto-apply happens at the route: a V4.0 card makes it free.)

    `negative` only reaches i2vPro (I2V/FLF) -- the referenceVideo submit shape captured
    2026-07-02 has no negativePrompts field at all. A genuine PixAI API gap, not an
    oversight here -- R2V/V2V shots silently ignore a negative prompt if one is set.
    `use_prompt_helper` (the Generate dock's 'Video prompt helper' switch, off by default)
    likewise only reaches i2vPro.usePromptsHelper -- referenceVideo has no such field.

    Every engine sends its OWN modelId or none (PROBE_2026-09-26 V02): the reference path
    used to fall back to v4.0.1's id for an engine VIDEO_MODELS did not know, pairing
    `model: "tbkv1.0.1"` with another model's id. `input_video_durations` (the caller's
    all-or-nothing list, see input_video_durations()) reaches only referenceVideo, and an
    engine that takes no video references refuses them here (build_reference_video_parameters)
    rather than sending them.

    `ratio` (the Generate drawer's Tsubaki aspect-ratio picker, 2026-09-28) reaches only the
    referenceVideo road, where build_reference_video_parameters sends it for a Tsubaki engine
    and never as "adaptive"; an i2vPro shot has no such field and never carries it. The web
    road writes the receipt when it cannot go out (build_request)."""
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
                                                 model_id=mid_num,
                                                 input_video_durations=input_video_durations,
                                                 ratio=ratio)
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
# above for the reversal, and dev/tests/test_enhance.py for the guards.
#
# The panelplugin half's CLI entry (--workflow-id and run_enhance): NOT restored. The Bridge is
# web-only -- its mirror gate is a route concern, and a bare CLI --workflow-id could submit a
# panelplugin task on the API key (the reaped-at-60-min bug). The parser defines no such flag.
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
# Guarded by dev/tests/test_enhance.py, which greps for the two literals a FILTER submit could not do without -- the filter
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
    control schema from here to render its form.

    Which credential: the scene LIST answers on the API key too (all 34 scenes, 2026-09-26
    probe). The app still browses only behind the armed Bridge, by decision (DECISIONS
    2026-08-18, "the AI-Tools tier splits by FUNCTION") -- /api/scenes passes
    make_mirror_session() -- and the SUBMIT (submit_scene) stays JWT-only: a scene submitted
    on the API key reaped unstarted when that was tried (DECISIONS 2026-08-18; not
    re-tested by the 2026-09-26 probe)."""
    d = gql_adhoc(session, _SCENE_LIST_Q, {}) or {}
    return d.get("chatEditingScenes") or []


def submit_scene(session, scene_id, media_ids, preset="random", custom=None, selector_values=None,
                 on_send=None):
    """Submit a chat-editing scene task (createChatEditingSceneTask) -> task id. The generate
    half of the Bridge AI-Tools tier. SPENDS, so it goes through gql_mutate (SINGLE attempt, no
    retry -- a re-POST after a lost response pays twice) and MUST run on the mirror JWT; the
    caller passes _check_read_only first at the route choke, exactly like /api/enhance ->
    submit_generation. `preset` is a preset key, "random", or "custom" (with `custom` text);
    `selector_values` is [{id, value}] for the scene's selectors (e.g. aspect-ratio).
    `on_send(input)` is called immediately before the mutation (observation only)."""
    _check_read_only("submit chat-editing scene")
    inp = {"sceneId": str(scene_id),
           "mediaIds": [str(m) for m in (media_ids or []) if m],
           "preset": str(preset or "random")}
    if custom is not None and str(custom).strip():
        inp["custom"] = str(custom)
    if selector_values:
        inp["selectorValues"] = [{"id": str(s["id"]), "value": s["value"]}
                                 for s in selector_values if s.get("id")]
    _observe_send(on_send, inp)
    d = gql_mutate(session, _SCENE_SUBMIT_M, {"input": inp})
    tid = ((d or {}).get("createChatEditingSceneTask") or {}).get("id")
    if not tid:
        # An answer with no task id is not a success and not a refusal: the task may exist
        # (3.21.2). Raised AFTER the send, so every caller reads it "may have started".
        raise PixAIError("scene: no task id returned: " + json.dumps(d)[:200])
    return str(tid)


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
#
# Re-read 2026-09-26 (the preset roster's extra.chatEditing, SCOPE_2026-09-26 E1/E2):
#   * Edit Pro publishes defaultAspectRatio "3:5" and offers 3:5 and 5:3 on top of the eleven
#     below, so its default moved from 3:4 to 3:5.
#   * Reference Pro publishes NO defaultAspectRatio. For a model like that PixAI's own aspect
#     control shows an "Auto" tile, selected by default, and sends no aspectRatio at all -- the
#     owner's two Reference Pro edits on the wire carry modelConfig {resolution} only. "auto"
#     is therefore an aspect VALUE here, first in Reference Pro's list and its default, and
#     build_chat_edit_parameters omits aspectRatio for it. Auto leaves the frame to PixAI; it
#     does NOT promise to keep the source's frame (the probe's verifier saw a 0.595 source
#     come back 2:3), so no copy anywhere may say it does.
# editCore.js EDIT_CAPS mirrors this table by hand; dev/tests/test_edit_upload.py's parity test
# reads both and fails if their aspects, defaults, reference caps, resolutions or qualities
# drift apart.
#
# PixAI Edit v4.0 (Session L decision 6, lane w2-small 2026-09-28), copied from its own model
# record -- the preset roster's version row 1983993578828959744, extra.chatEditing, read
# 2026-09-28: maxInputImageCount 10; supportedResolutionOptions 1K/2K/4K, defaultResolution
# 1K; no quality options; no defaultAspectRatio; fourteen aspects down to 1:8 / 8:1, in the
# record's own order. No published default aspect means PixAI's own client sends no
# aspectRatio (modelParams `ge`), so "auto" is its first aspect and its default, exactly as for
# Reference Pro. Listed first; the card's default model stays Edit Pro.
# Labelled as PixAI labels it, "PixAI Edit (v4.0)": the latest version of PixAI's general Edit
# model, not Edit Pro and not Tsubaki.3 (the owner's walk, 2026-10-03).
#
# PixAI Edit Pro V2.0 (#67, PROBE_2026-10-02_site): a new VERSION of the Edit Pro model
# (2026-09-29), not a new model, copied from its own version row 2061589941358465024,
# extra.chatEditing: maxInputImageCount 10; 1K/2K; low/medium/high; eleven aspects (v1.0's
# thirteen minus 1:3 and 3:1) in the record's order; defaults 1K/medium/3:5. Labelled as PixAI
# labels it ("PixAI Edit Pro (v2.0)") and listed right after v1.0. v1.0 stays -- PixAI still
# offers it, the Edit Pro AI Tools scenes run on it, and it stays the card's default
# (EDIT_PRO_MODEL_ID). Same submit shape and price table as v1.0; only chat.modelId differs.
EDIT_ASPECT_AUTO = "auto"
EDIT_MODELS = {
    "edit-v4": {
        "model_id": "1983993578828959744",
        "label": "PixAI Edit (v4.0)", "max_refs": 10,
        "resolutions": ["1K", "2K", "4K"],
        "qualities": [],
        "aspects": [EDIT_ASPECT_AUTO, "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "21:9", "1:4", "4:1", "1:8", "8:1"],
        "default": {"resolution": "1K", "quality": "", "aspect": EDIT_ASPECT_AUTO},
    },
    "edit-pro": {
        "model_id": EDIT_PRO_MODEL_ID,
        "label": "Edit Pro", "max_refs": 4,
        "resolutions": ["1K", "2K"],
        "qualities": ["low", "medium", "high"],
        "aspects": ["3:5", "5:3", "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "1:3", "3:1"],
        "default": {"resolution": "1K", "quality": "medium", "aspect": "3:5"},
    },
    "edit-pro-v2": {
        "model_id": "2061589941358465024",
        "label": "Edit Pro (v2.0)", "max_refs": 10,
        "resolutions": ["1K", "2K"],
        "qualities": ["low", "medium", "high"],
        "aspects": ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "3:5",
                    "5:3"],
        "default": {"resolution": "1K", "quality": "medium", "aspect": "3:5"},
    },
    "reference-pro": {
        "model_id": "1948514378441961474",
        "label": "Reference Pro", "max_refs": 10,
        "resolutions": ["2K", "4K"],
        "qualities": [],
        "aspects": [EDIT_ASPECT_AUTO, "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "21:9"],
        "default": {"resolution": "2K", "quality": "", "aspect": EDIT_ASPECT_AUTO},
    },
}
DEFAULT_EDIT_MODEL = "edit-pro"
# The aspect an edit on a model OUTSIDE the table gets when nobody picked one. What such a
# model does with no aspectRatio is unobserved, so this fails open to the value every edit sent
# before the table defaults existed (SCOPE_2026-09-26's rule for unobserved behaviour).
_EDIT_ASPECT_UNKNOWN_MODEL = "3:4"

# The model PixAI ran a hand/face Fix on BEFORE October 2026 -- the same CHAT model the Edit
# card calls Reference Pro. Kept only because it labels the Fixes collected before then (a
# Fix submit, POST /v2/task/fixer with just {mediaId, boxes}, never names a model).
# PixAI now runs a Fix on PixAI Edit v4.1 (2066624583022309376): measured 2026-10-28 through
# POST /v2/task/fixer/price, whose answer equals the v4.1 quote and not this model's. The app
# no longer prices with this constant -- a Fix is priced by PixAI's own Fix price route off
# the exact submit body (price_fixer).
FIXER_MODEL_ID = EDIT_MODELS["reference-pro"]["model_id"]


def edit_model_id(key):
    """model_id for an Edit-card model key ('edit-v4'/'edit-pro'/'edit-pro-v2'/
    'reference-pro'); '' if unknown."""
    return (EDIT_MODELS.get((key or "").strip()) or {}).get("model_id", "")


def edit_model_by_id(model_id):
    """The EDIT_MODELS spec whose model_id matches `model_id`, else None -- used to clamp a
    submitted edit's resolution/quality/aspect to what that model actually supports."""
    mid = str(model_id or "")
    for spec in EDIT_MODELS.values():
        if spec.get("model_id") == mid:
            return spec
    return None


def edit_default_aspect(model_id):
    """The aspect an edit on `model_id` gets when the caller picked none: the model's own table
    default ("auto" for Reference Pro, which publishes none; "3:5" for Edit Pro), or the
    pre-table 3:4 for a model the table does not know (see _EDIT_ASPECT_UNKNOWN_MODEL)."""
    spec = edit_model_by_id(model_id)
    return spec["default"]["aspect"] if spec else _EDIT_ASPECT_UNKNOWN_MODEL


def clamp_edit_config(model_id, resolution, quality, aspect):
    """Snap an edit's (resolution, quality, aspect) to the resolved model's real capabilities,
    so NO path -- preset, stale UI, old client -- can send an option the model rejects (the
    preset-with-Reference-Pro bug). Unknown models pass through unchanged. Returns the tuple.

    "auto" passes only for a model whose table lists it -- one that publishes no default
    aspect (Reference Pro). On Edit Pro it is not a legal value and snaps to the model's
    default (3:5), exactly like any other aspect the model does not offer. On a model OUTSIDE
    the table (a banked Toolbox preset pins one, e.g. PixAI Edit v3.0) "auto" -- or no aspect
    at all -- becomes the pre-table 3:4 (_EDIT_ASPECT_UNKNOWN_MODEL): what such a model does
    with no aspectRatio is unobserved, so it fails open to what every edit sent before "auto"
    existed. Any other aspect still passes through unchanged there."""
    spec = edit_model_by_id(model_id)
    if not spec:
        if not aspect or aspect == EDIT_ASPECT_AUTO:
            aspect = _EDIT_ASPECT_UNKNOWN_MODEL
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
                               resolution="1K", aspect_ratio=None, quality="medium",
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

    `aspect_ratio` left unset (or blank) takes the model's own table default
    (edit_default_aspect). "auto" sends NO aspectRatio at all -- PixAI's own shape for a
    model with no published default (the owner's Reference Pro edits on the wire) -- which
    leaves the frame to PixAI. Only for a model whose table lists "auto": on any other model
    (Edit Pro, or one outside the table) "auto" is not a value it takes, so it gets that
    model's default instead (3:5 on Edit Pro, the pre-table 3:4 off the table).
    """
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    if not ids:
        raise PixAIError("edit needs at least one source media_id")
    mid = str(model_id or EDIT_PRO_MODEL_ID)
    if not aspect_ratio or (aspect_ratio == EDIT_ASPECT_AUTO and EDIT_ASPECT_AUTO not in
                            ((edit_model_by_id(mid) or {}).get("aspects") or ())):
        aspect_ratio = edit_default_aspect(mid)
    model_config = {"resolution": resolution}
    if aspect_ratio != EDIT_ASPECT_AUTO:
        model_config["aspectRatio"] = aspect_ratio
    # quality is omitted when empty -- Reference Pro exposes no quality option, so sending
    # one would be a bogus knob; Edit Pro still sends low/medium/high.
    if quality:
        model_config["quality"] = quality
    params = {"chat": {
        "prompts": prompt or "",
        "mediaId": ids[0],
        "mediaIds": ids,
        "modelId": mid,
        "modelConfig": model_config,
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
    # No --edit-aspect -> the model's own default (Edit Pro 3:5, Reference Pro auto), not a
    # fixed 3:4 that clamp would then keep on every model offering it (SCOPE_2026-09-26 E1).
    aspect_ratio = getattr(args, "edit_aspect", "") or edit_default_aspect(model_id)
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
    if raw in _task_reads._GEN_FAIL:
        raise EmptyOutputsError(
            "PixAI reported this task as '{}' -- it did not complete, so there is "
            "nothing to recover. Check pixai.art for why, or resubmit.".format(raw))
    if raw and raw not in _task_reads._GEN_DONE:
        raise EmptyOutputsError(
            "this task is still '{}' on PixAI -- nothing to collect YET. It hasn't "
            "finished (or failed); try again once it completes.".format(raw))
    raise EmptyOutputsError(empty_message)


def _print_gate_receipt(adjusted, gated=True):
    """The CLI's half of the SCOPE_2026-09-26 receipt: what the per-model gate changed,
    printed under the parameters (used None = not sent, printed "off"). A long value -- a
    negative prompt the model does not take -- is shortened to its first characters.
    `gated=False` is a preview that could not reach the model's rules (offline / no key)."""
    if not gated:
        print("(Not checked against this model's own rules -- offline or no key. A --confirm "
              "run checks them before it submits.)")
        return

    def _short(v):
        s = "off" if v is None else str(v)
        return s if len(s) <= 40 else s[:39] + "…"
    for a in adjusted or []:
        why = a.get("why")
        print("  adjusted: {} {} -> {}{}".format(
            a.get("field"), _short(a.get("asked")), _short(a.get("used")),
            " ({})".format(why) if why else ""))


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

    # SCOPE_2026-09-26 G7: gate ONCE, right after the build, and use that one dict for the
    # preview print, _preview_card_note, _apply_kaisuuken and submit_generation -- so the card
    # is matched against the shape that is sent (the backstop gates inside price_task and
    # submit_generation return this same object). The gate needs a session for its
    # read-only lookups; a PREVIEW that cannot make one (offline, no key) prints the ungated
    # build and says so, exactly as its card note already fails soft. A --confirm run makes
    # its session here and fails as it always did when it cannot. A --task-id recovery
    # submits nothing, so it is not gated.
    session = None
    adjusted = []
    if not existing_task:
        if getattr(args, "confirm", False):
            # READ_ONLY refuses a --confirm run BEFORE the gate's read-only PixAI lookups
            # (/inference-profiles, /features, /size-config) and before any gate refusal, so
            # a READ_ONLY install never calls PixAI on a spend path and always reads the
            # READ_ONLY message (review R8). An EXTRA, earlier call: the existing guard below,
            # ahead of _apply_kaisuuken, stays exactly where it is.
            _check_read_only("submit a generation (spends credits)")
        try:
            session = _make_session(getattr(args, "token", None))
        except Exception:
            if getattr(args, "confirm", False):
                raise
            session = None
        if session is not None:
            params, adjusted = _models._gate_image_params(session, params)
            _models._refuse_lost_upscale(args, params)

    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask (PREVIEW -- no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        _print_gate_receipt(adjusted, gated=session is not None)
        _preview_card_note(args, params)
        print("\nThis would SPEND PixAI credits (unless free above). Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # generation can seed a fresh backup
    if session is None:
        session = _make_session(getattr(args, "token", None))
    _print_gate_receipt(adjusted, gated=True)
    thumb_dir = out / "gallery" / "thumbs"
    from moonglade.gallery import make_thumbnail

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
        # dev/tests/test_read_only_cli_paths.py describe finding.
        _check_read_only("submit a generation (spends credits)")
        print("Submitting generation task...")
        _apply_kaisuuken(session, params, args)
        # 3.21.2 (L1): an answer that cannot show whether the task was made says so in plain
        # words and exits non-zero -- never a raw transport error that reads like "nothing
        # happened, try again". `reached` is submit_generation's own mark just before the send.
        reached = spend_watch()
        task_id = _cli_send_once(lambda: submit_generation(session, params),
                                 reached=lambda: reached.v)
        print("  task id:", task_id)

        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="generate", fail_noun="generation")

    # The Task type exposes its media under `outputs` (mediaId / batchMediaIds /
    # videos), NOT at the top level. getTaskById returns that whole object and is
    # already proven, so reuse it for the result rather than guessing an ad-hoc
    # selection set.
    result = _task_reads.task_detail_gql(session, task_id) or {}
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
        save_catalog_over_snapshot(db_path, rows, known)

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
            from moonglade.telemetry import telem_bump
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


def _video_row_model(session, result, params, sent, fm):
    """(model_id, model_name) for a video row being catalogued live (PROBE_2026-09-26 V09,
    owner ruling 3 of 2026-09-26).

    THE STORED TASK WINS. The engine is the task's own video block (fm.video_model), and the
    submitted block (`sent`) only fills in when the task has none. model_id is the TASK's
    numeric top-level `modelId` (what PixAI stamped on the stored task, from getTaskById);
    the submitted params' modelId counts only when it is this engine's own id. On the
    `--generate-video --task-id` recovery road `params` is rebuilt from the CLI args, not
    read from the task (engine defaulting to v4.0.1), so trusting it filed a recovered
    Tsubaki or V3.0 Flash clip under V4.0 Lite's id and title (review f-V-F1).

    An engine VIDEO_MODELS knows takes only ITS OWN id (video_model_id). Real v2.7 and
    v3.0.1 tasks carry modelId 1648918127446573124, an IMAGE checkpoint (see
    build_video_parameters' docstring); titling that id would file an image model's name on
    a video row, so such a row keeps the engine name, as the repair migration leaves v2.7 /
    v3.0.1 rows (review f-V-F2 / V-R2; the owner can widen this). An engine the roster does
    not know yet takes any numeric id. Otherwise the engine NAME, so a row is never left
    with '' when the engine is known. It used to be the engine name unconditionally, which
    split one model across two ids (--sync-videos writes the number) and handed "tbkv1.0.1"
    to the version lookup as if it were a version id.

    model_name is the version's own title from model_name_gql for a numeric id ("Tsubaki
    Video v1.0"), falling back to the VIDEO_MODELS label for the engine. Video model names
    are dynamic now (ruling 3, reversing 2026-08-15's "a video row's model_name stays
    blank"): the Tsubaki engines are the first to carry a name rather than a version string.
    A lookup failure costs the label, never the row."""
    engine = str((fm or {}).get("video_model") or (sent or {}).get("model") or "").strip()
    task_params = (result or {}).get("parameters")
    task_params = task_params if isinstance(task_params, dict) else {}
    mid = ""
    for cand in ((fm or {}).get("model_id"), task_params.get("modelId")):
        c = str(cand or "").strip()
        if c.isdigit():
            mid = c
            break
    if not mid and isinstance(params, dict):
        c = str(params.get("modelId") or "").strip()
        if c and c == video_model_id(engine):
            mid = c
    if mid and not _video_model_id_fits(engine, mid):
        mid = ""
    name = ""
    if mid:
        got = _resolved_model_name(session, {}, mid)
        if got and got != mid and not str(got).isdigit():
            name = str(got)
    if not name:
        name = (VIDEO_MODELS.get(engine) or {}).get("label", "")
    return (mid or engine), name


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
    model_id, model_name = _video_row_model(session, result, params, sent, fm)

    from moonglade.gallery import make_thumbnail
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
            model_id=model_id, model_name=model_name,
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
                _media_tools.video_poster_thumb(path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the catalog
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(vmid, e))
        _media_tools.video_faststart(path)                        # iOS needs moov at the front to stream
        rows.append(full)
        saved.append(str(path))
    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
    return saved


def _task_image_media(outputs):
    """The REAL output images of a completed image task as [(media_id, seed)], newest logic:
    a batchSize>1 task stores a 2x2 COMPOSITE GRID under outputs.mediaId and the INDIVIDUAL
    images under outputs.batch[] -- so we take the individuals (the actual generations), never
    the grid. batchSize==1 / legacy tasks fall back to outputs.mediaId (+ legacy batchMediaIds).
    Per-image seed comes from batch[].seed, else the shared outputs.seed. Deduped, order-kept.

    This is why batch generations were previously under-captured: the old path read
    outputs.batchMediaIds (which is null on modern tasks) and saved only the grid.

    A member PixAI has DELETED keeps its place in the array and gains a `deletedAt`
    (2026-09-06). It is not one of the task's images any more, so it is skipped here --
    otherwise every re-sync would list it and download the deleted image straight back in.
    A batch whose members are ALL deleted therefore yields nothing, and deliberately does
    not fall back to outputs.mediaId: on a batch task that is the combined preview picture,
    never one of the images."""
    outputs = outputs or {}
    batch = outputs.get("batch") or []
    shared_seed = str(outputs.get("seed") or "")
    pairs = []
    if batch:                                        # modern batch: save the individuals
        for b in batch:
            mid = str((b or {}).get("mediaId") or "")
            if mid and not (b or {}).get("deletedAt"):
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
    """The task read collect_generation (the --task-id / --dump-params recovery path) and the
    gallery's queue estimate make: `task_detail_gql`, the full document (#91). Its narrower
    ad-hoc fallback went with the saved request it stood in for."""
    return _task_reads.task_detail_gql(session, task_id)


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
    from moonglade.gallery import make_thumbnail
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
            # A Fix made since PixAI's Hand/Face Fix launch may carry `passes` (each with
            # its own tag) instead of, or beside, `boxes`; fix_marker reads `tag` off both.
            fix_parts = list(fx.get("boxes") or []) + list(fx.get("passes") or [])
            stem = img_dir / build_fix_stem_name(fix_label, fix_parts, task_id, mid,
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
        save_catalog_over_snapshot(db_path, rows, known)
    return saved


def _bump_card_use(params):
    """Thrifty Archivist: count the free card only once its task ACTUALLY submitted
    (a card attached to a rejected submit was never spent). Fail-soft no-op."""
    if isinstance(params, dict) and params.get("kaisuukenId"):
        try:
            from moonglade.telemetry import telem_bump
            telem_bump("free_cards_applied")
        except Exception:
            pass


# =============================================================================
# Tsubaki.3 Unlimited Mode (SCOPE_2026-09-26_unlimited-mode, §8 amendments binding)
# =============================================================================
# A lane request is an ordinary Tsubaki.3 image submit carrying `parameters.lane =
# "infinite"`; PixAI runs it free while the account holds the entitlement, and stamps its own
# priority (300) on it. The app never claims the entitlement -- that is an account action the
# owner takes on PixAI's site -- and only ever READS its status.
#
# Four rules hold on every road (§2, §8.2-3):
#   - refuse, never silently drop: a lane request that breaks a rule is refused at build with
#     one plain sentence, before any spend;
#   - a lane request never touches a card (no /v2/kaisuuken/check, no kaisuukenId), keyed on
#     the params' own `lane`, whatever road built them;
#   - a lane request is never resubmitted as anything else (neither of submit_generation's
#     automatic resubmits fires on it);
#   - the entitlement is read live (cached briefly), never assumed.

UNLIMITED_LANE = "infinite"
# The versions the lane is offered on: PixAI's own site asks the status for Tsubaki.3's id and
# no other (§8.4). Not "any MMDIT26B" -- Flash is MMDIT26B too and has no lane.
UNLIMITED_VERSIONS = frozenset(("2024383379556065549",))
# Session H (decision 2 / T3a): a Tsubaki edit runs on Tsubaki.3. It is offered on every still
# picture -- the "Edit with Tsubaki" menu item and the Lightbox edit bar alike (owner ruling,
# 2026-09-28), whatever model made it. gallery/src/gen/tsubakiCore.js carries the same ids
# (dev/tests/test_tsubaki3_generate.py pins the copies together).
TSUBAKI3_MODEL_ID = "2024383378759147749"
TSUBAKI3_VERSION_ID = "2024383379556065549"
# The status is cached RAW, keyed by (version, the identity that creates), and the expiry is
# compared with the clock at every check (§8.8): an hour's success TTL is too long for a grant
# that ends on a fixed date, so success keeps 5 minutes and a failure the gate's own minute.
_UNLIMITED_CACHE_TTL = 300.0
_UNLIMITED_FAIL_TTL = 60.0
_unlimited_cache = {}                       # (version_id, identity) -> (fetched_at, raw|None)

UNLIMITED_BUSY = "An Unlimited Mode picture is still being made"
_UNLIMITED_REFUSED = "PixAI refused this as an Unlimited Mode task, so nothing was spent"
_UNLIMITED_NO_CARD = "Unlimited Mode never uses a free card — remove the card from this request"
_UNLIMITED_UNWIRED = "Unlimited Mode can't be checked on this road, so nothing was sent"
_UNLIMITED_T3_ONLY = "Unlimited Mode runs on Tsubaki.3 only"
_UNLIMITED_IMAGE_ONLY = "Unlimited Mode is for Tsubaki.3 image generation only"
_UNLIMITED_UNREAD = ("Couldn't read this model's settings from PixAI, so Unlimited Mode can't "
                     "be checked — try again in a minute")
_UNLIMITED_UNCONFIRMED = ("Couldn't confirm your Unlimited Mode with PixAI, so nothing was "
                          "sent — try again in a minute")
_UNLIMITED_ENDED = "Your Unlimited Mode has ended"
_UNLIMITED_NOT_HELD = "Unlimited Mode isn't active on this account"


def asks_unlimited(payload):
    """True when a web payload asks for the lane (the drawer's `unlimited: true`)."""
    return isinstance(payload, dict) and payload.get("unlimited") in (True, "1", "true", "on")


def is_lane_request(params):
    """True for ANY createGenerationTask params carrying a `lane` -- the web road's, a CLI
    --params-json, a banked --dump-params shape. The spend choke keys on this (§8.3)."""
    return isinstance(params, dict) and bool(params.get("lane"))


def _unlimited_identity():
    """The identity that will CREATE: the browser JWT when Mirror to PixAI is on, else the
    API key. The entitlement is read, and cached, under that identity (§8.8)."""
    return "mirror" if _mirror.mirror_enabled() else "key"


def _unlimited_session(session, identity):
    """The session the status is read on: the caller's for the API key; for the mirror, the
    stored browser JWT when it is usable, else None (the read then fails soft). Built
    directly, never through make_mirror_session: a read must not roll the token forward."""
    if identity != "mirror":
        return session
    jwt = _mirror.load_mirror_state().get("jwt") or ""
    return _mirror._mirror_session_from(jwt) if _mirror._jwt_usable(jwt) else None


def _unlimited_raw(session, version_id):
    """GET /v2/generation-model-version/<version>/infinite-mode, RAW, cached (see
    _unlimited_cache). A body is kept only when it carries a boolean `owned`; anything else
    -- an exception, a non-2xx, a strange body, an unusable mirror session -- is a failure,
    cached for _UNLIMITED_FAIL_TTL, and returns None. Read-only."""
    vid = str(version_id or "").strip()
    if not vid:
        return None
    identity = _unlimited_identity()
    key = (vid, identity)
    now = time.monotonic()
    hit = _unlimited_cache.get(key)
    if hit is not None:
        ttl = _UNLIMITED_CACHE_TTL if hit[1] is not None else _UNLIMITED_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    raw = None
    try:
        s = _unlimited_session(session, identity)
        if s is not None:
            data = _rest_get(s, "/generation-model-version/" + vid + "/infinite-mode",
                             timeout=_models._GATE_READ_TIMEOUT)
            if isinstance(data, dict) and isinstance(data.get("owned"), bool):
                raw = data
    except Exception:
        raw = None
    _unlimited_cache[key] = (now, raw)
    return raw


def _expiry_epoch(value):
    """PixAI's expiresAt as epoch seconds, or None. ISO 8601 is what the route answers (the
    site reads it with `new Date(...)`); epoch seconds or milliseconds are tolerated."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e12 else float(value)
    try:
        d = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def infinite_mode_status(session, version_id, now=None):
    """The account's Unlimited Mode on a version -> {owned, expires_at, days_left}, or None
    when the status could not be read. S1, as amended (§8.8).

    `owned` is True only when PixAI says owned AND expiresAt is still in the future, compared
    with the clock on EVERY call (the raw answer is cached, the verdict never is), so nothing
    goes out as a lane request after the grant ends. `days_left` is whole days remaining,
    rounded up -- the site's own count (29 on 2026-09-26 for a 2026-10-25 grant); 0 when not
    owned. Read-only: never the claim route."""
    import math
    raw = _unlimited_raw(session, version_id)
    if raw is None:
        return None
    exp = _expiry_epoch(raw.get("expiresAt"))
    t = time.time() if now is None else now
    owned = raw.get("owned") is True and exp is not None and exp > t
    return {"owned": owned,
            "expires_at": raw.get("expiresAt") if exp is not None else None,
            "days_left": int(math.ceil((exp - t) / 86400.0)) if owned else 0}


def _lane_size_rule(ranges, step):
    """The lane's size limit off a version's /size-config ranges, or None without them: the
    site's own rule -- the area fits the SMALLEST range's max area and the size lies inside a
    range. `max_side` is the largest square on the model's step inside that area (Tsubaki.3:
    1800 x 1800 is the area, and 1800 is off the 16 px grid, so 1792 x 1792 -- §8.5)."""
    import math
    if not ranges:
        return None
    step = max(1, int(step or 1))
    max_area = min(r[1] * r[3] for r in ranges)
    return {"max_area": max_area, "max_side": math.isqrt(max_area) // step * step,
            "ranges": [list(r) for r in ranges]}


def _lane_size_ok(width, height, rule):
    """True when (width, height) passes _lane_size_rule's limit."""
    return (width * height <= rule["max_area"]
            and any(r[0] <= width <= r[1] and r[2] <= height <= r[3] for r in rule["ranges"]))


def _unlimited_check(session, params, version_id):
    """The lane's eligibility, on the GATED dict (S3, §8.4-5): refuse with one sentence, or
    return a COPY carrying `lane` with `priority` removed (PixAI stamps its own 300 on a lane
    task; the site's build sends none -- §8.2). The caller's dict is never mutated.

    Order: the version pin (no read) -> the gated shape (the gate's three cached reads must all
    have answered, or the gate passed an unsnapped, unconverted dict) -> the entitlement ->
    the site's own rules: Pro mode, batch 1, no reference, no workflow or recipe, no card, no
    High priority, and the size actually sent (after the 16 px snap)."""
    vid = str(version_id or "").strip()
    if vid not in UNLIMITED_VERSIONS:
        raise PixAIError(_UNLIMITED_T3_ONLY)
    feats = _models._model_features(session, vid)
    profiles = _models._model_profiles(session, vid)
    ranges = _models._model_size_config(session, vid)
    if not feats or not profiles or not ranges:
        raise PixAIError(_UNLIMITED_UNREAD)
    if feats["model_type"] != "MMDIT26B_MODEL":
        raise PixAIError(_UNLIMITED_T3_ONLY)
    status = infinite_mode_status(session, vid)
    if status is None:
        raise PixAIError(_UNLIMITED_UNCONFIRMED)
    if not status["owned"]:
        raise PixAIError(_UNLIMITED_ENDED if status["expires_at"] else _UNLIMITED_NOT_HELD)
    p = params
    if str(p.get("inferenceProfile") or "").strip().lower() != "pro":
        raise PixAIError("Unlimited Mode runs on Pro mode — pick Pro")
    try:
        batch = int(p.get("batchSize") or 1)
    except (TypeError, ValueError):
        batch = 0
    if batch != 1:
        raise PixAIError("Unlimited Mode makes one picture at a time — set the count to 1")
    if p.get("mediaId") or p.get("contextImages"):
        raise PixAIError("Unlimited Mode can't use a reference picture — remove it")
    if p.get("workflowId") or p.get("recipeIds"):
        raise PixAIError("Unlimited Mode can't use a workflow or a recipe")
    if p.get("kaisuukenId"):
        raise PixAIError(_UNLIMITED_NO_CARD)
    if p.get("priority") in (PRIORITY_HIGH, PRIORITY_XHIGH):
        raise PixAIError("Unlimited Mode can't use High priority — turn it off")
    rule = _lane_size_rule(ranges, _models._size_rule(feats["model_type"], ranges)["step"])
    try:
        w, h = int(p.get("width")), int(p.get("height"))
    except (TypeError, ValueError):
        w = h = 0
    if not (w > 0 and h > 0 and _lane_size_ok(w, h, rule)):
        raise PixAIError("Unlimited Mode: this size is too large — up to {0} × {0}".format(
            rule["max_side"]))
    out = dict(p)
    out["lane"] = UNLIMITED_LANE
    out.pop("priority", None)
    return out


def unlimited_resolver(session):
    """The build-time lane check for RequestResolver.unlimited: (params, version_id) -> the
    lane params, or a PixAIError. The SAME function for a quote and a spend (the gallery's
    _price_resolver and _submit_resolver), like gate_resolver. A resolver WITHOUT it refuses a
    lane request (§8.10) -- a road that cannot read the entitlement never sends one."""
    def _check(params, version_id):
        return _unlimited_check(session, params, version_id)
    return _check


def _graphql_reason(err):
    """PixAI's own words out of a gql_mutate refusal ("GraphQL error: [{message, extensions:
    {code}}]"): the messages, each with its code when it has one. The raw text otherwise."""
    s = str(err)
    head = "GraphQL error: "
    if s.startswith(head):
        try:
            errs = json.loads(s[len(head):])
            bits = []
            for e in errs if isinstance(errs, list) else []:
                if isinstance(e, dict):
                    code = (e.get("extensions") or {}).get("code") \
                        if isinstance(e.get("extensions"), dict) else None
                    msg = str(e.get("message") or "").strip()
                    bits.append(msg + (" ({})".format(code) if code else ""))
            if any(bits):
                return "; ".join(b for b in bits if b)
        except ValueError:
            pass
    return s


def submit_generation(session, params, *, on_send=None, exact=False):
    """Submit a createGenerationTask and return the task id immediately -- no wait, no
    download. The card (if any) must already be attached to `params`. Raises on no id.

    Session M (BUILD-w5-m s3.4): `on_send(variables)` is called immediately before each
    mutation with a deep COPY of what is about to go out -- observation only: its return is
    ignored and an exception inside it is swallowed, so a recorder can never block or alter a
    spend. It is how the Inspector learns the exact request PixAI got and how a run knows the
    mutation was reached. `exact=True` (a run's jobs, review F6) turns off BOTH refusal-only
    resubmits below: a job goes out once, exactly as it was quoted and confirmed, and PixAI's
    refusal comes back as it came. Both default to today's behaviour, byte for byte.

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
    REJECTED the task, so there is nothing created and nothing charged to duplicate.

    An Unlimited Mode request (ANY params carrying `lane`, whatever road built them --
    SCOPE_2026-09-26_unlimited-mode §8.2-3) is exempt from BOTH resubmits: dropping its
    profile or its Turbo would send a different task than the lane request that was asked
    for, and the Turbo fallback would also flip the process-wide _turbo_refused. It goes out
    once; PixAI's refusal comes back in plain words. It never carries a card."""
    _check_read_only("submit a generation (spends credits)")
    check_params_retired(params)             # before any network call: no spend, no round-trip
    lane = is_lane_request(params)
    if lane and params.get("kaisuukenId"):
        raise PixAIError(_UNLIMITED_NO_CARD)
    # Mirror routing (review F4/F5): after the READ_ONLY gate, the create rides the browser
    # JWT session when the toggle is on (else this is a pass-through, unchanged). submit_
    # generation is create-only -- it returns the task id and never polls/collects -- so
    # rebinding the whole session here is safe; the CALLER keeps its API-key session for
    # download (F6).
    session = _mirror._session_for_create(session)
    # Gate the field set on the model's architecture (DiT profile vs SDXL steps/cfg) BEFORE
    # the mutation, with the SAME helper price_task uses, so the submitted shape equals the
    # priced shape. Fail-soft: an undetermined profile set returns params unchanged (today's
    # behavior).
    params = _models._gate_params_for_model(session, params)
    # Lane w2-recipes: the dict about to go out may not carry recipes beside context images
    # (a reference the backstop gate just converted), a lane or an upscale. No network.
    from moonglade import recipes as _recipes
    _recipes.check_params(params)
    if not exact:
        # Already known to be turbo-refused? use Low. A run job (exact) never: the run applied
        # this at build, so it was quoted and digested, and what is sent must equal what was
        # quoted (review N1) -- a flag flipped since then would send an unquoted priority.
        params = priority_for_submit(params)
    # Session H (BUILD-w2-gen §8, review S1): decided BEFORE the mutation, off the gate's own
    # cached profile read -- is the profile asked for one this version LISTS? A listed profile
    # PixAI refuses is an entitlement refusal (a non-member's Ultra), not "unsupported", so the
    # drop-and-resubmit below must not turn it into a Pro job the quote never described; and
    # a REQUIRE_MEMBERSHIP answer on a listed members-only profile is ambiguous between Ultra
    # and Turbo, so the Turbo fallback stands down too. An unreadable list keeps today's
    # self-heal (pinned since 2026-07-24).
    listed, members_only = _models._profile_listing(session, params)

    def _send(p):
        _mark_spend_reached()                                # 3.21.2: this thread's spend mark
        if on_send is not None:
            try:
                on_send(copy.deepcopy(p))
            except Exception:                                # noqa: BLE001
                pass                                         # a recorder never blocks a spend
        return gql_mutate(session, _GEN_MUTATION, {"parameters": p})
    try:
        created = _send(params)
    except PixAIError as e:
        if _recipes.refusal_from(e):
            # PixAI refused a recipe: nothing was created. Re-raised BEFORE the two resubmits
            # below can read its words -- a recipe refusal is never retried as anything else.
            raise
        if lane:
            # Never retried as anything else (§8.2). A GraphQL error whose data resolved
            # nothing is PixAI refusing the task, so nothing exists and nothing was spent;
            # anything else -- a partial success (the mutation's data came back beside the
            # errors, review N2), a timeout -- is passed on as it came, because it does not
            # prove that and must read may_have_started, never refused.
            # Keyed on the type and the transport's structured `errors` (classify_outcome's
            # rule), never on the message text (DESIGN_3.22 2.6, L2).
            if definite_refusal(e) and getattr(e, "graphql_errors", None):
                refused = PixAIError(_UNLIMITED_REFUSED + ": " + _graphql_reason(e))
                refused.graphql_data = getattr(e, "graphql_data", None)
                refused.refused = True       # a definite refusal, for a run's job state
                raise refused
            raise
        if exact:
            # A run job (review F6): never resubmitted on another profile or priority -- that
            # would be a request nobody quoted, sent after the run's budget check. PixAI's
            # answer comes back as it came; definite_refusal() reads it.
            raise
        if not definite_refusal(e):
            # Both resubmits below are safe ONLY because a refusal means nothing was made. A
            # GraphQL error whose mutation data came back non-null is a partial success: the
            # task exists and may be charged, so sending again would pay twice. The same rule
            # the lane, run jobs, training and the Loom fallback already follow (red team
            # 2026-10-01). A timeout or dropped connection is passed on unchanged as well.
            raise
        if "inferenceProfile" in str(e) and "inferenceProfile" in params and listed:
            refused = PixAIError("PixAI refused the {} profile for this account, so nothing "
                                 "was made: {}".format(params.get("inferenceProfile"),
                                                       _graphql_reason(e)))
            refused.refused = True
            raise refused
        if "inferenceProfile" in str(e) and "inferenceProfile" in params:
            dropped = params.pop("inferenceProfile")
            print("  mode '{}' not supported by this model; retrying on the "
                  "model's default...".format(dropped))
            created = _send(params)
        elif _is_turbo_refusal(e) and params.get("priority") == PRIORITY_TURBO \
                and not members_only:
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
            created = _send(params)
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
    Anything else is dropped, so a stale or malformed client box can't reach the server --
    a non-finite coordinate (Infinity, NaN: Python's json reads both) included.

    A box that starts above or left of the picture is CLIPPED, not shifted (#93 review F3):
    x -40 width 100 becomes x 0 width 60, the part that is on the picture -- shifting it to
    x 0 width 100 would repair 40 px the box never covered. The far edges are the picture's
    to know, not this function's; the clients clip those.

    Called only through build_fixer_body, which both the price and the submit use: the body
    that gets PRICED has to be the body that gets SUBMITTED, or the cost badge would quote a
    request PixAI never receives."""
    clean = []
    for b in (boxes or []):
        tag = str((b or {}).get("tag") or "").lower()
        if tag not in ("hand", "face"):
            continue
        try:
            x, y = int(b["x"]), int(b["y"])
            w, h = int(b["width"]), int(b["height"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue                     # OverflowError: int(inf); ValueError: int(nan)
        if x < 0:
            w, x = w + x, 0
        if y < 0:
            h, y = h + y, 0
        if w > 0 and h > 0:
            clean.append({"x": x, "y": y, "width": w, "height": h, "tag": tag})
    return clean[:20]


FIX_ONE_KIND = ("A Fix repairs one kind at a time — clear the face boxes or the hand "
                "boxes first.")

def build_fixer_body(media_id, boxes):
    """THE body of a hand/face Fix: {mediaId, boxes}, boxes cleaned by clean_fix_boxes. The
    price (price_fixer, on POST /v2/task/fixer/price) and the spend (submit_fixer, on POST
    /v2/task/fixer) both send what this returns for their own inputs: the SAME boxes (the
    same cleaner, so the same kind, count and coordinates) on the same picture. What differs
    is the media id, deliberately: the gallery's quote names the picture by its CATALOG id
    (/api/price runs no media resolver -- it would upload once per keystroke), while its spend
    names it by the upload-kind id the submit's resolver gets by uploading the local file
    first (PixAI refuses a generation OUTPUT id as an input on this path). PixAI's price does
    not move with the picture (measured 2026-10-28: 4,800 for every source size), so the
    number quoted is the number charged.

    Raises PixAIError when no box survives the cleaner, and FIX_ONE_KIND when the boxes carry
    more than one tag: since PixAI's Hand Fix / Face Fix launch (2026-10-21) its server
    refuses a face box and a hand box in one Fix ("all boxes must share one tag", measured
    2026-10-28 on the price route, which shares the submit route's input schema). A Fix is
    one pass of one kind."""
    clean = clean_fix_boxes(boxes)
    if not clean:
        raise PixAIError("drag a box over a hand or face")
    if len({b["tag"] for b in clean}) > 1:
        raise PixAIError(FIX_ONE_KIND)
    return {"mediaId": str(media_id), "boxes": clean}


# THE SPEND MARK (3.21.2, L1). A caller that must tell "never reached the send" from "sent,
# answer unclear" -- a web single send, a CLI runner -- takes a fresh mark for its thread with
# spend_watch(); each create marks it immediately before its one spend request
# (_mark_spend_reached: submit_generation's send, submit_fixer, submit_scene). Thread-local,
# because a request's send runs on the request's own thread; observation only, it changes
# nothing that is sent.
_SPEND_WATCH = threading.local()


class _SpendMark:
    __slots__ = ("v",)

    def __init__(self):
        self.v = False


def spend_watch():
    """A fresh spend mark for this thread: `.v` turns True once a create in this thread
    reaches its spend request. Replaces any earlier mark of the thread."""
    mark = _SpendMark()
    _SPEND_WATCH.mark = mark
    return mark


def _mark_spend_reached():
    mark = getattr(_SPEND_WATCH, "mark", None)
    if mark is not None:
        mark.v = True


def _observe_send(on_send, payload):
    """Mark this thread's spend as reached, and tell an `on_send` observer what is about to go
    out (a deep copy). Observation only: an exception inside the observer is swallowed, so a
    recorder can never block or alter a spend."""
    _mark_spend_reached()
    if on_send is None:
        return
    try:
        on_send(copy.deepcopy(payload))
    except Exception:                                        # noqa: BLE001
        pass


def submit_fixer(session, media_id, boxes, on_send=None):
    """Submit a hand/face fixer task via POST /v2/task/fixer -> task id (poll it like any
    generation). `boxes` = [{x, y, width, height, tag}] in ORIGINAL-image pixel coords, tag
    'hand' | 'face' (<=20), all ONE kind. Builds a mask from the boxes and repairs those
    regions. Raises.

    READ_ONLY first, then build_fixer_body -- so a body with no usable box, or with two kinds
    PixAI would refuse, is refused here before any network call. Never sends cusPrompts.
    `on_send(body)` is called immediately before the one POST (observation only)."""
    _check_read_only("submit a hand/face fix (spends credits)")
    body = build_fixer_body(media_id, boxes)
    # The fixer IS a credit-spending create, so it rides the mirror JWT session when the
    # toggle is on (review F1: the choke belongs at "a create", not only at gql_mutate sites).
    # Create-only -- the caller polls/collects on its own API-key session (F6); pass-through
    # when the mirror is off; refuses before spend if the mirror is on but unavailable (F5).
    create_session = _mirror._session_for_create(session)
    _observe_send(on_send, body)
    data = _rest_post(create_session, "/task/fixer", body) or {}
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
    media_id / boxes  the Fix's inputs: submit_fixer rebuilds its POST
                      /v2/task/fixer body from these with build_fixer_body, the
                      builder that made `parameters` (which, for a Fix, IS that
                      {mediaId, boxes} body, priced on /v2/task/fixer/price).
    model_version_id  the RESOLVED model version an image gen will submit --
                      the one fact a route needs to tell "no model picked" from
                      "the builder refused something".
    lora_version_ids  the LoRAs actually going out, for the per-account cap and
                      the LoRA telemetry.
    adjusted          the clamp receipt: [{field, asked, used}] for every clamp
                      that FIRED. Clamping is substitution on a paid path, so
                      the route hands it back in the response rather than
                      charging for a different generation in silence.
    unlimited         an Unlimited Mode request that passed _unlimited_check
                      (`parameters` carries lane "infinite"). price() answers it
                      free without a card check and submit() never runs one --
                      and no `no_card` a caller passes can put the card back.
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
    unlimited: bool = False


@dataclass
class RequestResolver:
    """The lookups `build_request` cannot do on its own, supplied by the caller.

    model_version(model_id, client_version_id) -> the chosen version ROW (the
                          list_model_versions meta dict: version_id, quality_tag, ...)
                          or a bare version id                  -- needs a session
    preset(user, name) -> banked Toolbox preset dict or None   -- per-account store
    media_id(value)    -> an id PixAI accepts as an INPUT      -- uploads; SUBMIT only
    gate(params)       -> (params, adjusted)                   -- the per-model gate,
                          applied ONCE at build so the quoted, card-matched and
                          submitted dict is one object; `adjusted` is receipt entries
                          [{field, asked, used, why}] (see gate_resolver)
    video_duration(media_id) -> seconds or None                -- a reference video's
                          real length, for referenceVideo.inputVideoDurations
    unlimited(params, version_id) -> lane params               -- the Unlimited Mode
                          check (see unlimited_resolver); absent = a lane request
                          is refused on this road
    features(version_id) -> parsed /features or None           -- Session H: the
                          architecture the creativity shape is decided on, the gate's
                          own cached read (features_resolver); absent = the web
                          payload's `creativity` is not honoured (legacy helper only)

    `media_id` is deliberately absent when pricing. /api/price fires on every
    keystroke in the drawer, and resolving there would upload the same file once
    per character; a quote needs the SHAPE, not an upload-kind id. `gate` and
    `video_duration` are supplied IDENTICALLY to a quote and a spend -- they change
    the shape, so a quote without them would price something the submit never sends.
    """
    model_version: object = None
    preset: object = None
    media_id: object = None
    gate: object = None
    video_duration: object = None
    unlimited: object = None
    features: object = None


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

    Returns the chosen version ROW (the list_model_versions meta dict, with `version_id`)
    whenever it read the rows, and the plain version-id string otherwise (no model_id, or a
    model that listed nothing). SCOPE_2026-09-26 G4: build_request reads the version's own
    quality tag off that row, so the rule costs no new GET. build_request accepts either
    form, so a resolver that returns a bare id (older callers, test stubs) still works.
    """
    def _resolve(model_id, client_version_id=""):
        mid = str(model_id or "").strip()
        vid = str(client_version_id or "").strip()
        if not mid:
            return vid
        versions = _models.list_model_versions(session, mid)
        chosen = next((v for v in versions if v.get("version_id") == vid),
                      None) if vid else None
        if chosen:
            return chosen
        if versions:
            return versions[0]
        return vid
    return _resolve


def gate_resolver(session):
    """The build-time gate for RequestResolver.gate: params -> (params, adjusted).

    SCOPE_2026-09-26_tsubaki3-parity-fixes: the per-model image gate (_gate_image_params --
    the size grid, the feature strips, a reference as a context image, the MMDIT26B prompt
    helper, the LoRA weight range), bound to `session`, returning the gated dict and one
    receipt entry per change. The SAME function for a quote and a spend: the gallery's
    _price_resolver and _submit_resolver both hand it their session, so the dict /api/price
    prices and card-matches is the dict the submit sends. A refusal raises PixAIError, which
    build_request's callers already render (the badge as its note)."""
    def _gate(params):
        return _models._gate_image_params(session, params)
    return _gate


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
    # Session H (BUILD-w2-gen §1): the drawer's context images, in slot order (slot N is the
    # prompt's @imageN), and its creativity stop. Refused, never repaired: a malformed list or
    # a repeated picture would change the count and the price.
    ctx_raw = p.get("context_images")
    context_images = []
    if ctx_raw not in (None, "", []):
        if not isinstance(ctx_raw, list):
            raise PixAIError("context images must be a list of picture ids")
        for x in ctx_raw:
            v = str(x if x is not None else "").strip()
            if not v.isdigit():
                raise PixAIError("context images must be a list of picture ids")
            context_images.append(v)
        if len(set(context_images)) != len(context_images):
            raise PixAIError("The same picture is in two context slots — remove one")
    creativity = p.get("creativity")
    if creativity in (None, ""):
        creativity = None
    elif creativity not in _models._CREATIVITY_LEVELS:
        raise PixAIError("creativity must be off, low or medium")
    return SimpleNamespace(
        context_images=context_images, creativity=creativity,
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
        # The Generate drawer's colour palette (Session H 4): cleaned or REFUSED here, before
        # any network call -- a refusal is the badge's note and costs nothing. The gate
        # decides whether it may go out (see _gate_image_params' palette rule).
        color_palette=clean_color_palette(p.get("color_palette")),
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
    # never send an invalid knob; a payload with no aspect takes the model's own default
    # (Edit Pro 3:5, Reference Pro auto) -- SCOPE_2026-09-26 E1.
    res, q, asp = clamp_edit_config(model_id, (p.get("resolution") or "1K"), q,
                                    (p.get("aspect") or edit_default_aspect(model_id)))
    kwargs = dict(resolution=res, aspect_ratio=asp, quality=q, scene_id=scene_id,
                  model_id=model_id)
    # multi-image: sources[] (primary + extra refs) if the client sent them, else [source];
    # capped to the resolved row's OWN reference limit (Edit Pro v1.0 4; Edit Pro V2.0, Edit
    # v4.0 and Reference Pro 10) -- two versions of one model can differ, so never a fixed cap.
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
    # Unlimited Mode is a Tsubaki.3 IMAGE lane. Asked for on any other road it is refused,
    # never quietly ignored into a paid job (SCOPE_2026-09-26_unlimited-mode §2).
    lane = asks_unlimited(p)
    if lane and road in ("edit", "fix", "video", "I2V", "FLF", "R2V", "enhance"):
        raise PixAIError(_UNLIMITED_IMAGE_ONLY)

    if road == "edit":
        params = _edit_parameters_from_payload(p, user, rs)
        return GenerationRequest(mode="edit", parameters=params, no_card=no_card,
                                 note=None if params else "pick an image to edit")

    if road == "fix":
        # A hand/face Fix is submitted over POST /v2/task/fixer with a body of {mediaId,
        # boxes}, and PixAI prices that very body on POST /v2/task/fixer/price (#93). So
        # `parameters` IS the submit body, from build_fixer_body: price() hands it to
        # price_fixer, and submit() -> submit_fixer rebuilds the same dict from `media_id` +
        # `boxes` with the same builder. A body the builder refuses (no usable box, or face
        # and hand together, which PixAI's server refuses) is a note with no parameters --
        # nothing to price -- and submit_fixer refuses it again, before any network call.
        # (Within ONE request the quote and the spend share the body. The gallery builds two
        # -- /api/price with no media resolver, /api/fix with the uploading one -- so there
        # the boxes are identical and the media id is not: see build_fixer_body.)
        src = str(p.get("source") or "").strip()
        if src and rs.media_id is not None:
            src = str(rs.media_id(src) or src)
        boxes = list(p.get("boxes") or [])
        # no_card is forced True here and is NOT read off the payload: /v2/task/fixer
        # takes only mediaId + boxes, with no kaisuukenId field anywhere on it, so a free
        # card can never be spent on a Fix, and price() never runs the card check for one.
        # Letting it run would paint the badge emerald "FREE -- a card covers this" over an
        # action about to charge full credits.
        if not src:
            return GenerationRequest(mode="fix", no_card=True, boxes=boxes,
                                     note="pick an image to fix")
        try:
            params = build_fixer_body(src, boxes)
        except PixAIError as e:
            note = FIX_ONE_KIND if str(e) == FIX_ONE_KIND else "drag a box over a hand or face"
            return GenerationRequest(mode="fix", parameters=None, no_card=True, media_id=src,
                                     boxes=boxes, note=note)
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
        vmodel = (p.get("video_model") or "").strip() or DEFAULT_VIDEO_MODEL
        negative = (p.get("negative") or "").strip()
        camera = (p.get("camera_movement") or "")
        adjusted = []
        # Which submit shape build_shot_video_params will take: i2vPro for a framed I2V/FLF,
        # referenceVideo for everything else carrying refs. Only the latter reads the input
        # video lengths, and only the former could have carried a negative or a camera move.
        i2v_road = (shot == "I2V" and imgs) or (shot == "FLF" and len(imgs) >= 2)
        # A length this engine does not take is snapped by build_shot_video_params (6 -> 5 on
        # a Tsubaki engine, 15 -> 10 on a 10 s engine); say so rather than change it silently.
        # The drawer snaps on the client first (applyModelGating), so this is the receipt for
        # a Remix-built or hand-rolled payload (review f-V-F5).
        asked_dur = p.get("duration") or 5
        used_dur = _snap_video_duration(asked_dur, vmodel)
        try:
            dur_moved = float(asked_dur) != used_dur
        except (TypeError, ValueError):
            dur_moved = True
        if dur_moved:
            takes = [d for d in video_model_durations(vmodel)
                     if d != 15 or vmodel in VIDEO_15S_MODELS]
            adjusted.append({"field": "duration", "asked": asked_dur, "used": used_dur,
                             "why": "this engine takes {} s".format(
                                 "/".join(str(d) for d in takes))})
        durations = []
        if not i2v_road and vids:
            # V5: each reference video's real length, through the SAME lookup the quote and
            # the spend both carry (RequestResolver.video_duration) -- all or nothing.
            durations, unknown = input_video_durations(vids, rs.video_duration)
            if unknown:
                adjusted.append({"field": "inputVideoDurations", "asked": "measured lengths",
                                 "used": [], "why": INPUT_VIDEO_UNKNOWN_WHY})
        # The Tsubaki Multi-Reference aspect ratio (lane w2-small, 2026-09-28). It rides only the
        # referenceVideo road of a Tsubaki engine (VIDEO_RATIO_MODELS) -- keyed on the ROAD, not
        # the shot mode, since an FLF with one frame goes out as a reference video (spend review
        # N6). Asked for anywhere else it is dropped with a receipt; the drawer never asks there.
        # "adaptive" is PixAI's default and is never sent, so it needs no receipt.
        ratio = str(p.get("ratio") or "").strip()
        if ratio and ratio != "adaptive" and (i2v_road or vmodel not in VIDEO_RATIO_MODELS):
            adjusted.append({"field": "ratio", "asked": ratio, "used": None,
                             "why": "only Tsubaki Video's Multi-Reference takes an aspect ratio"})
            ratio = ""
        if i2v_road:
            # V6: the builder drops both on an engine whose panel has neither; say so.
            if negative and vmodel in VIDEO_NO_NEGATIVE_MODELS:
                adjusted.append({"field": "negativePrompts", "asked": negative, "used": None,
                                 "why": "negative prompt not used by this engine"})
            if camera and camera != "unset" and vmodel in VIDEO_NO_CAMERA_MODELS:
                adjusted.append({"field": "cameraMovement", "asked": camera, "used": None,
                                 "why": "camera not used by this engine"})
        params = build_shot_video_params(
            shot, (p.get("prompt") or "").strip(), image_ids=imgs,
            video_ids=vids, audio_ids=auds,
            duration=p.get("duration") or 5,
            generate_audio=bool(p.get("generate_audio") or p.get("audio")),
            model=(p.get("video_model") or ""),
            camera_movement=camera,
            quality=(p.get("quality") or "professional"),
            audio_language=(p.get("audio_language") or "english"),
            negative=negative,
            is_private=bool(p.get("is_private")),
            use_prompt_helper=bool(p.get("prompt_helper")),
            input_video_durations=durations,
            ratio=ratio)
        return GenerationRequest(mode="video", parameters=params, no_card=no_card,
                                 adjusted=adjusted)

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
    # Session H (BUILD-w2-gen §2): what a context-image request may not carry, refused at build.
    if args.context_images:
        if args.ref_media_id:
            raise PixAIError("Send context images or a reference picture, not both")
        if _upscale_ratio(args.enlarge) or _upscale_ratio(args.upscale):
            raise PixAIError("An upscale can't carry context images")
        bad = [n for n in _image_refs(args.prompt)
               if n < 1 or n > len(args.context_images)]
        if bad:
            raise PixAIError("The prompt names @image{}, but only {} context image{} {} set"
                             .format(bad[0], len(args.context_images),
                                     "" if len(args.context_images) == 1 else "s",
                                     "is" if len(args.context_images) == 1 else "are"))
    row = None
    if rs.model_version is not None:
        got = rs.model_version(p.get("model_id") or "", args.model)
        if isinstance(got, dict):          # the chosen version ROW (model_version_resolver)
            row = got
            args.model = str(got.get("version_id") or "")
        else:
            args.model = got
    lora_ids = [vid for vid, _w in (args.lora or [])]
    if not args.model:
        return GenerationRequest(mode="image", no_card=args.no_card, note="pick a model",
                                 lora_version_ids=lora_ids, adjusted=args.clamped)
    # Same entitlement the submit applies, so the badge cannot quote a price for a
    # members-only option that will be stripped before it is sent.
    args.is_member = is_member
    # SCOPE_2026-09-26 G4 -- the Quality Tag booster sends the chosen VERSION's own tag, at
    # build time and never in the gate (the gate's version-keyed routes carry no `extra`).
    # Row read with a non-empty half -> that {prefix, suffix}. Row read with none (Tsubaki.3,
    # Flash, Tsubaki.2, some SDXL) -> no qualityTag, as PixAI's own site sends, with a receipt
    # entry because the booster was asked for. No row (no model_id, nothing listed) -> today's
    # literal prefix. The drawer reads the chip disabled for the no-tag case.
    if args.quality_tag and row is not None and "quality_tag" in row:
        qt = row.get("quality_tag")
        if isinstance(qt, dict):
            args.quality_tag_obj = qt
        else:
            args.clamped.append({"field": "qualityTag", "asked": args.quality_tag,
                                 "used": None,
                                 "why": "this model version publishes no quality tag"})
            args.quality_tag = ""
    params = _gen_parameters(args)
    adjusted = args.clamped
    # Recipes, step 1 (lanes w2-recipes x w2-gen): the payload's `recipeIds`, validated by
    # moonglade.recipes.recipe_ids_from, onto the BUILT params HERE -- before the creativity
    # step-down below reads them (w2-gen review S3) and before the gate. Refuses a malformed
    # list, a gateless road, and recipes beside context images or on the Upscale road.
    # Returns `params` itself when the payload names none. Design:
    # design/notes/recipes/BUILD-w2-recipes.md.
    from moonglade import recipes as _recipes
    params = _recipes.attach_to_built(params, p, gated=rs.gate is not None)
    # Session H decision 5 -- the creativity stop, shaped at BUILD on the architecture the
    # gate itself reads (rs.features, the same cached /features; review B3). The gate's G6 then
    # relocates naturalPrompts and forces medium beside context images, idempotently.
    if args.creativity is not None:
        _shape_creativity(params, args.creativity, rs, args.model, adjusted)
    # G7 -- ONE gate, applied ONCE, here. The gated dict IS req.parameters: price() prices and
    # card-matches it, submit() attaches the card to it and sends it, and the backstop gates
    # inside price_task/submit_generation return this same object. A gate refusal raises
    # PixAIError like any builder refusal (the badge's note; nothing is spent).
    if rs.gate is not None:
        try:
            params, gate_adjusted = rs.gate(params)
        except PixAIError:
            # A lane request on another version is told so in the lane's own words, not in a
            # gate refusal about its profile (Session H added the gate's unlisted-profile
            # refusal, which a lane request on Flash -- "pro" is not Flash's -- reaches first).
            if lane and rs.unlimited is not None \
                    and str(args.model or "").strip() not in UNLIMITED_VERSIONS:
                raise PixAIError(_UNLIMITED_T3_ONLY)
            raise
        adjusted = list(adjusted) + list(gate_adjusted or [])
        _models._refuse_lost_upscale(args, params)   # an Upscale is never billed as a new generation
    # Recipes, step 2: every forbidden combination checked AGAIN on the dict the gate returned
    # (it can turn a reference into a context image), before the lane check so Unlimited Mode
    # still refuses a recipe. Returns `params` itself when the payload names none, or when
    # step 1's ids rode through the gate as sent.
    params = _recipes.apply_to_params(params, p, gated=rs.gate is not None)
    # Unlimited Mode (SCOPE_2026-09-26_unlimited-mode S3): checked AFTER the one gate and its
    # profile fill, on the dict that will be quoted and sent. A road without the entitlement
    # lookup, or without the gate, cannot vouch for the lane and refuses it (§8.4, §8.10).
    if lane:
        if rs.unlimited is None or rs.gate is None:
            raise PixAIError(_UNLIMITED_UNWIRED)
        params = rs.unlimited(params, args.model)
    # THE SMART REFERENCE SUBMIT, AS PIXAI'S OWN SITE SENDS IT (captured live 2026-10-03, the
    # owner's walk): a context-image edit carries `controlNets: []` and, for one picture, no
    # batchSize. The quote prices this same dict (req.parameters), so the two cannot differ.
    # The source picture's own size is the drawer's (genCore.tsubakiEditState); the gate above
    # already put it on the model's size rule.
    if params.get("contextImages"):
        params.setdefault("controlNets", [])
        if params.get("batchSize") == 1:
            params.pop("batchSize")
    return GenerationRequest(mode="image", parameters=params,
                             no_card=args.no_card or lane, model_version_id=args.model,
                             lora_version_ids=lora_ids, adjusted=adjusted, unlimited=lane)


_IMAGE_REF_RE = re.compile(r"@image(\d+)")


def _image_refs(prompt):
    """The @imageN numbers a prompt names, in order (Session H decision 2). The same rule as
    the drawer's tsubakiCore.AT_REF_RE -- dev/tests/test_tsubaki3_generate.py pins the two."""
    return [int(m.group(1)) for m in _IMAGE_REF_RE.finditer(str(prompt or ""))]


def _recipes_in(params):
    """True when the built params carry recipes, read by the recipe lane's one parser."""
    from moonglade import recipes as _recipes
    return bool(_recipes.recipe_ids_from(params))


def _shape_creativity(params, level, rs, version_id, adjusted):
    """Session H decision 5: the web payload's creativity stop onto the params, in place.

    Only on MMDIT26B, decided by the gate's own /features read (review B3). /features
    unreadable -> refuse (a creativity shape PixAI's site would never send beside an unchecked
    architecture). Another architecture -> the legacy on/off shape the builder already made
    stays, with a receipt entry. On MMDIT26B the level is the one asked, EXCEPT: context images
    run it at medium, and recipes run it one step lower (medium -> low, low -> off), as PixAI's
    own builder does (task-*.js). Both are receipt entries. The recipe step lives HERE, at
    build, because the gate must stay idempotent; it reads the BUILT params' recipeIds, so it
    fires only when recipes are really sent (review S3). build_request attaches them before
    this runs (moonglade.recipes.attach_to_built), and they are read here through the same
    parser, moonglade.recipes.recipe_ids_from (recipes review finding 6)."""
    if rs.features is None:
        return
    feats = rs.features(version_id)
    if feats is None:
        raise PixAIError("Couldn't read this model's settings from PixAI, so its creativity "
                         "can't be set — try again in a minute")
    if feats.get("model_type") != "MMDIT26B_MODEL":
        adjusted.append({"field": "creativity", "asked": level, "used": None,
                         "why": "this model's prompt helper is on or off"})
        return
    used = level
    if params.get("contextImages"):
        used = "medium"
        if level != "medium":
            adjusted.append({"field": "promptHelper", "asked": level, "used": "medium",
                             "why": "a context image runs the prompt helper at medium, as "
                                    "PixAI's own site does"})
    elif level in ("medium", "low") and _recipes_in(params):
        used = "low" if level == "medium" else "off"
        adjusted.append({"field": "promptHelper", "asked": level, "used": used,
                         "why": "recipes run the prompt helper one step lower, as PixAI's "
                                "own site does"})
    params["promptHelper"] = {"creativity": used, "forcePromptHelperDetectionSide": "server"}


def price(session, req, *, card_session=None):
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
    renders as "not enough -- costs the full price".

    `adjusted` (SCOPE_2026-09-26 receipts) rides beside the cost whenever the build rewrote
    anything -- a clamp, or the per-model gate's snap/strip/conversion -- so the drawer's and
    the Loom's badges can say so BEFORE a spend. Absent when nothing was changed, the same
    rule /api/generate's response follows (a key on every answer is a key clients ignore).
    The object priced and card-matched here is req.parameters, already gated at build.

    `card_session` (2026-11-18) is the identity the free-card check reads under -- the one the
    send will create on (_apply_kaisuuken checks there, through _session_for_create), so the
    quote and the send cannot disagree about a card. Defaults to `session`, as before."""
    out = _price_answer(session, req, card_session=card_session)
    if req.adjusted:
        out["adjusted"] = list(req.adjusted)
    # The breakdown notes ride a PAID quote only: on a card-covered one "+X" would read as a
    # charge (review N1), and the extra reads would buy nothing.
    if req.mode == "image" and req.parameters is not None and not req.unlimited \
            and out.get("cost") is not None and not out.get("free"):
        out.update(_price_breakdown(session, req.parameters, out["cost"]))
    return out


def _price_breakdown(session, params, cost):
    """Session H: what the badge's one note line says (BUILD-w2-gen "Price"): the context
    images' charge ("N context images +X") and a non-default profile's ("profile Ultra +X"),
    each the difference between this request's price and the same request without it. The
    variant dicts are PRICED only -- never card-checked, never submitted, never cached where a
    submit reads. A read that fails leaves its figure out; nothing here can fail the quote."""
    out = {}
    ctx = params.get("contextImages")
    if isinstance(ctx, list) and ctx:
        out["context_images"] = len(ctx)
        base = _pricing.price_task(session, {k: v for k, v in params.items() if k != "contextImages"})
        if base is not None and cost - base >= 0:
            out["context_charge"] = cost - base
    prof = str(params.get("inferenceProfile") or "").strip()
    if prof:
        try:
            rows = _models._model_profiles(session, params.get("modelId")) or []
        except Exception:
            rows = []
        default = next((str(r.get("profileName") or "").strip() for r in rows
                        if isinstance(r, dict) and r.get("profileFlag") == "default"), "")
        mine = next((r for r in rows if isinstance(r, dict)
                     and str(r.get("profileName") or "").strip() == prof), None)
        if default and mine is not None and prof != default:
            out["profile"] = str(mine.get("title") or prof)[:40]
            alt = _pricing.price_task(session, dict(params, inferenceProfile=default))
            if alt is not None and cost - alt >= 0:
                out["profile_extra"] = cost - alt
    return out


def _price_answer(session, req, card_session=None):
    """price()'s verdict, minus the receipt (see price)."""
    if req.parameters is None:
        return {"cost": None, "free": False, "note": req.note}
    if req.price_note:
        return {"cost": None, "free": False, "note": req.price_note}
    if req.mode == "fix":
        # #93: a Fix is priced by PixAI's own Fix price route off the exact submit body
        # (req.parameters IS that body). Never a card check -- no card can cover a Fix --
        # and a failed quote is cost None with no number from anywhere else.
        q = _pricing.price_fixer(session, req.parameters)
        boxes = req.parameters.get("boxes") or []
        out = {"cost": q["cost"] if q else None, "free": False,
               "cards": None, "cards_held": None, "cards_needed": None, "card_short": False,
               "card_name": None, "card_template": None, "card_expires": None,
               "fix_pass": boxes[0]["tag"] if boxes else None, "fix_boxes": len(boxes)}
        if q and q.get("original") is not None and q["original"] > q["cost"]:
            out["original_cost"] = q["original"]
        return out
    if req.unlimited:
        # S4: free by the entitlement, never by a card -- no /v2/kaisuuken/check at all. The
        # list price rides along as `list_cost` when /v2/task-price answers (what PixAI's
        # price route says of a lane request is unobserved; the verdict does not depend on it).
        out = {"cost": 0, "free": True, "unlimited": True}
        listed = _pricing.price_task(session, req.parameters)
        if listed is not None:
            out["list_cost"] = listed
        return out
    cost = _pricing.price_task(session, req.parameters)
    recipes = bool(req.parameters.get("recipeIds"))
    if recipes:
        # Lane w2-recipes: a failed quote with recipes is PixAI's refusal (RECIPE_*) or
        # "couldn't verify" -- and the card check is skipped, so FREE needs a read price.
        from moonglade import recipes as _recipes
        verdict = _recipes.price_verdict(session, req.parameters, cost)
        if verdict is not None:
            return verdict
    best = None if req.no_card else match_kaisuuken(card_session or session, req.parameters,
                                                    enrich=True)
    covered = card_covers(best)
    out = {"cost": cost, "free": covered,
           "cards": (best or {}).get("total"),
           "cards_held": (best or {}).get("total"),
           "cards_needed": (best or {}).get("consumeAmount"),
           "card_short": bool(best) and not covered,
           "card_name": (best or {}).get("name"),
           # The Loom's batch tally keys its per-template ticket pool on this (falls
           # back to card_name when absent) -- see loom-core.js tallyPricesDetailed.
           "card_template": (best or {}).get("templateId"),
           "card_expires": (best or {}).get("expiresAt")}
    if recipes and covered:
        out["card_note"] = _recipes.CARD_NOTE    # a card over a recipe's LoRAs: unobserved
    return out


def submit(session, req, *, no_card=None, before_send=None, on_send=None, exact=False):
    """Spend: READ_ONLY guard -> free card -> the one mutation this road's mode uses.
    Returns {"task_id": ...}.

    Session M (BUILD-w5-m s3.4): `before_send(params)` runs after the card step and before
    submit_generation on EVERY branch that reaches it (the lane branch too, review F13b); it
    may raise to stop, and nothing has been sent when it does -- a run's budget check lives
    there. `on_send` and `exact` are handed to submit_generation (see it). All three default
    to today's behaviour, byte for byte.

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
        # A Fix's `parameters` are the submit body build_fixer_body made for the price.
        # submit_fixer rebuilds the same body from `media_id` + `boxes` with that same
        # builder, after its own READ_ONLY check, and is the real guard: a body the builder
        # refuses (no usable box, two kinds) raises there before any network call. What
        # this cannot do without is the two inputs that body is built from.
        if not req.media_id or not req.boxes:
            raise PixAIError(req.note or "nothing to submit")
        # `on_send` (a run's) is told just before the one POST, as on the generation road, so
        # a caller knows whether the spend was reached (3.21.2, L1). Observation only; passed
        # only when asked for, so a default Fix calls submit_fixer exactly as before.
        return {"task_id": submit_fixer(session, req.media_id, req.boxes,
                                        **({"on_send": on_send} if on_send is not None else {}))}
    if req.parameters is None:
        raise PixAIError(req.note or "nothing to submit")
    if req.unlimited:
        # S5: the card step is skipped outright for a lane request -- keyed on req.unlimited,
        # which the `no_card` argument cannot override (§8.10). submit_generation guards the
        # params' own `lane` too, for every road that reaches it (§8.3).
        if before_send is not None:
            before_send(req.parameters)
        return {"task_id": submit_generation(session, req.parameters,
                                             **_send_kwargs(on_send, exact))}
    from types import SimpleNamespace
    skip = req.no_card if no_card is None else bool(no_card)
    # Passing the flag through rather than branching around the call keeps
    # _apply_kaisuuken's own precedence (explicit id > no_card > auto-match) and its
    # spend log ("--no-card: this WILL spend credits") the single source of both.
    _apply_kaisuuken(session, req.parameters,
                     SimpleNamespace(kaisuuken_id="", no_card=skip))
    if before_send is not None:
        before_send(req.parameters)
    return {"task_id": submit_generation(session, req.parameters,
                                         **_send_kwargs(on_send, exact))}


def _send_kwargs(on_send, exact):
    """submit_generation's Session M keywords, passed only when asked for: a default submit
    calls it exactly as it always did."""
    kw = {}
    if on_send is not None:
        kw["on_send"] = on_send
    if exact:
        kw["exact"] = True
    return kw


# Session M: the pause between one answered mutation and the next in a run ("be polite to
# their servers"; the Loom's batch staggers 2.2 s). Nothing waits for a task to FINISH.
RUN_SEND_GAP_S = 1.5


def _run_budget_note(sent):
    return ("The free card expected for image {} was used elsewhere, so it would cost more "
            "than you confirmed. {} {} sent; the rest were not.".format(
                sent + 1, sent, "was" if sent == 1 else "were"))


def send_run(session, jobs, *, hooks, budget=None, gap_s=None, sleep=None):
    """THE run sender (Session M, BUILD-w5-m s4): a run's jobs, strictly one after another,
    each through submit() -- READ_ONLY first, the card step, the budget check, then
    submit_generation(exact=True), whose one gql_mutate is the only mutation a job can make.
    The FIRST failure stops the rest; nothing is retried or resent.

    `jobs`   [{"cell": int, "req": GenerationRequest, "no_card": True | None}] -- the very
             objects the run quoted; nothing is rebuilt here.
    `budget` {"each": credits per job, "total": the confirmed total} or None. Before each
             job without a card: charged-so-far + each > total stops the run before that
             job (a card spent in another tab, a card that expired). None = a single send,
             which has no confirmed total (review F11): no check, the card auto-applies.
    `hooks`  the Runs store's side, each call guarded here:
               sending(cell)                        committed BEFORE the job's submit; if it
                                                    raises, the run stops, nothing more sent
               sent(cell, task_id, request, card)   after the mutation; a raise is swallowed
                                                    (the task exists; the answer carries it)
               failed(cell, state, error, request)  a job that did not go out cleanly
    Returns {"status": "sent"|"stopped", "reason"?, "jobs": [{cell, state, task_id?, card,
             error?, recipe_error?}]} with state sent | refused | may_have_started | not_sent.

    State after a failure (s4.4): an exception before on_send fired means the mutation was
    never reached -> not_sent; after it, a definite refusal (a GraphQL error, a 401, a local
    refusal) -> refused; anything else (a timeout, a dropped connection, a 5xx, no task id)
    -> may_have_started, never resent and never counted as refused."""
    from moonglade import recipes as _recipes
    gap = RUN_SEND_GAP_S if gap_s is None else gap_s
    pause = sleep if sleep is not None else time.sleep
    out = []
    state = {"charged": 0, "sent": 0, "stop": None}

    for idx, job in enumerate(jobs):
        cell = job["cell"]
        if state["stop"] is not None:
            out.append({"cell": cell, "state": "not_sent", "card": False})
            continue
        if idx and gap:
            pause(gap)
        try:
            hooks.sending(cell)
        except Exception:                                    # noqa: BLE001
            state["stop"] = ("Couldn't record cell {} before sending it, so it and the rest "
                             "were not sent.".format(cell + 1))
            out.append({"cell": cell, "state": "not_sent", "card": False})
            continue
        seen = {"request": None}

        def _on_send(variables):
            seen["request"] = variables

        def _before(params):
            if budget is None or params.get("kaisuukenId"):
                return
            if state["charged"] + int(budget["each"]) > int(budget["total"]):
                raise LocalRefusal(budget.get("note") or _run_budget_note(state["sent"]))

        try:
            task_id = submit(session, job["req"], no_card=job.get("no_card"),
                             before_send=_before, on_send=_on_send, exact=True)["task_id"]
        except Exception as e:                               # noqa: BLE001
            reached = seen["request"] is not None
            if not reached:
                st = "not_sent"
            elif getattr(e, "refused", False) or definite_refusal(e):
                st = "refused"
            else:
                st = "may_have_started"
            refusal = _recipes.refusal_from(e) if reached else None
            msg = refusal["copy"] if refusal else _graphql_reason(e)
            rec = {"cell": cell, "state": st, "card": False, "error": str(msg)[:300]}
            if refusal:
                rec["recipe_error"] = refusal
            out.append(rec)
            try:
                hooks.failed(cell, st, rec["error"], seen["request"])
            except Exception:                                # noqa: BLE001
                pass
            state["stop"] = rec["error"]
            continue
        card = bool((seen["request"] or {}).get("kaisuukenId"))
        if not card and budget is not None:
            state["charged"] += int(budget["each"])
        state["sent"] += 1
        out.append({"cell": cell, "state": "sent", "task_id": str(task_id), "card": card})
        try:
            hooks.sent(cell, str(task_id), seen["request"], card)
        except Exception:                                    # noqa: BLE001
            pass
    res = {"status": "stopped" if state["stop"] is not None else "sent", "jobs": out}
    if state["stop"] is not None:
        res["reason"] = state["stop"]
    return res


# =============================================================================
# end of the one payload road
# =============================================================================


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
        return _models.model_name_gql(session, mid) or ""
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
        _dur = _media_tools.duration(saved[0]) if saved else None
        dur = round(_dur, 2) if _dur is not None else None
        return {"media_ids": mids, "saved": len(saved), "is_video": True, "duration": dur}
    fm = extract_full_meta(result)
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    saved = _download_image_task(session, result, task_id, out, a, prompt=fm.get("prompt_full", ""))
    # the real images (batch individuals, not the composite grid)
    mids = [mid for mid, _seed in _task_image_media(result.get("outputs") or {})]
    return {"media_ids": mids, "saved": len(saved), "is_video": False}


def _i2v_cli_unsent_notes(args):
    """The receipts for what --generate-video was asked for and does not send (the CLI's half
    of the receipts rule; build_request records the web road's). A Tsubaki engine has no
    negative prompt and no camera move (VIDEO_NO_NEGATIVE_MODELS / VIDEO_NO_CAMERA_MODELS --
    build_video_parameters drops both), and --video-ratio belongs to --reference-video.
    --params-json is sent exactly as given, so only the ratio note applies to it."""
    notes = []
    if (getattr(args, "video_ratio", "") or "").strip():
        notes.append("--video-ratio applies to --reference-video only (not sent).")
    if getattr(args, "params_json", ""):
        return notes
    model = str(getattr(args, "video_model", "") or getattr(args, "model", "")
                or DEFAULT_VIDEO_MODEL).strip()
    label = (VIDEO_MODELS.get(model) or {}).get("label") or model
    if (getattr(args, "negative", "") or "").strip() and model in VIDEO_NO_NEGATIVE_MODELS:
        notes.append("negative prompt not used by {} (not sent).".format(label))
    cam = (getattr(args, "camera_movement", "") or "").strip()
    if cam and cam != "unset" and model in VIDEO_NO_CAMERA_MODELS:
        notes.append("camera not used by {} (not sent).".format(label))
    return notes


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
    if not existing_task:
        check_params_retired(params)      # a raw --params-json skips the builder's check

    if not existing_task and not getattr(args, "confirm", False):
        i2v = params.get("i2vPro") or {}
        print("=== PixAI createGenerationTask -- VIDEO (PREVIEW, no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        print("\n*** VIDEO GENERATION IS EXPENSIVE ***")
        print("  model={}  mode={}  duration={}s{}{}".format(
            i2v.get("model"), i2v.get("mode"), i2v.get("duration"),
            "  +audio" if i2v.get("generateAudio") else "",
            "  (first/last-frame)" if i2v.get("tailMediaId") else ""))
        for n in _i2v_cli_unsent_notes(args):
            print("  note: " + n)
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
        for n in _i2v_cli_unsent_notes(args):
            print("  note: " + n)
        print("Submitting VIDEO generation task (this spends credits)...")
        _apply_kaisuuken(session, params, args)   # free-card check on the API-key session
        # gql_mutate, never gql_adhoc: a re-POSTed createGenerationTask is a second
        # (expensive) video and a second charge -- see gql_mutate's docstring.
        # _session_for_create: the CREATE rides the mirror JWT when the toggle is on
        # (else pass-through); download below stays on the API-key `session` (F6).
        task_id = _cli_create_once(_mirror._session_for_create(session), params)
        print("  task id:", task_id)
        _bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 600),
                          interval=5, label="video", fail_noun="video generation")

    # Result: getTaskById -> outputs.videos -> fileUrl -> download mp4 (same as --sync-videos).
    result = _task_reads.task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    # A recovered task is filed from ITS OWN parameters, as collect_generation does. `params`
    # here was rebuilt from this run's CLI args (engine defaulting to v4.0.1), not read from
    # the task, so handing it over filed a recovered clip under another engine's model, and
    # its prompt / negative / duration fallbacks read the args too (review f-V-F1).
    saved = _download_video_task(session, result, task_id, out, args,
                                 (result.get("parameters") or {}) if existing_task else params)
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
    if not existing_task and override:
        check_params_retired(json.loads(override))   # sent as given: no builder checks it

    is_private = (getattr(args, "vchannel", "private") == "private")
    vmodel = (getattr(args, "video_model", "") or "v4.0.1")
    ratio = (getattr(args, "video_ratio", "") or "").strip()
    if not existing_task and not override:
        # Before any upload: an engine that takes no video references refuses them here,
        # not after _resolve_refs has already uploaded the local files.
        _check_video_ref_caps(vmodel, vids)

    # Each --ref-video's real length (SCOPE_2026-09-26 V5), read ONCE from the SOURCES --
    # a local file is measured directly, a media id through the same lookup the gallery's
    # quote and spend carry, against --out -- so the preview and the submit (whose ids are
    # upload ids by then) send the identical list. All or nothing, as on the web road.
    _lookup = [None]

    def _vid_len(src):
        if _is_local_source(src):
            return _media_tools.duration(str(src))
        if _lookup[0] is None:
            _lookup[0] = make_video_duration_lookup(out)
        return _lookup[0](src)
    in_durs, in_unknown = input_video_durations(vids, _vid_len) if not override else ([], False)

    def _build(img_ids, vid_ids, aud_ids):
        # Duration: default 5 (matches the argparse flag + the i2v sibling -- was 15 here,
        # a real 3x cost divergence, B10), snapped to PixAI's allowed lengths before use
        # for either preview or submit, same as the i2v CLI path (B9). No model_id: the
        # builder sends THIS engine's own id (it used to send v4.0.1's for every engine).
        return build_reference_video_parameters(
            prompt, image_media_ids=img_ids, video_media_ids=vid_ids, audio_media_ids=aud_ids,
            model=vmodel,
            duration=_snap_video_duration(getattr(args, "duration", 5) or 5, vmodel),
            mode=getattr(args, "vmode", None) or "professional",
            generate_audio=bool(getattr(args, "audio", False)),
            audio_language=getattr(args, "audio_language", None) or "english",
            is_private=is_private, kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
            ratio=ratio, input_video_durations=in_durs)

    def _notes():
        if in_unknown:
            print("  note: " + INPUT_VIDEO_UNKNOWN_WHY + " (inputVideoDurations sent as []).")
        if ratio and vmodel not in VIDEO_RATIO_MODELS:
            print("  note: --video-ratio is only sent to the Tsubaki video engines ({}); "
                  "not sent for {}.".format(", ".join(VIDEO_RATIO_MODELS), vmodel))

    # PREVIEW: no upload, no submit. Local files shown as placeholders.
    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask -- REFERENCE VIDEO (PREVIEW, no credits spent) ===")
        if override:
            print(json.dumps({"parameters": json.loads(override)}, indent=2))
        else:
            ph = lambda lst: [("<upload:{}>".format(s) if _is_local_source(s) else s) for s in lst]
            prev = _build(ph(imgs), ph(vids), ph(auds))
            print(json.dumps({"parameters": prev}, indent=2))
            _notes()
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
            _notes()
        print("Submitting REFERENCE VIDEO task (spends credits unless a free card applies)...")
        _apply_kaisuuken(session, params, args)   # free-card check on the API-key session
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        # _session_for_create: create rides the mirror JWT when on; download stays API-key (F6).
        task_id = _cli_create_once(_mirror._session_for_create(session), params)
        print("  task id:", task_id)
        _bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 600), interval=5,
                          label="reference video", fail_noun="reference video generation")

    result = _task_reads.task_detail_gql(session, task_id) or {}
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
    if not existing_task and override:
        check_params_retired(json.loads(override))   # sent as given: no builder checks it

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
    from moonglade.gallery import make_thumbnail

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
        task_id = _cli_create_once(_mirror._session_for_create(session), params)
        print("  task id:", task_id)
        _bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="edit", fail_noun="edit")

    result = _task_reads.task_detail_gql(session, task_id) or {}
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
        save_catalog_over_snapshot(db_path, rows, known)
    print("Edited + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved)}


def _needs_model_fix(row):
    """Return the model version-id to resolve if this row's model_name is missing
    or still a raw numeric id; else ''. Handles the case where model_name was
    set to the numeric id (the model lookup failed on an earlier run).

    Only a NUMERIC id is ever handed to the version lookup. A video row collected before
    2026-09-26 stored the engine NAME ("tbkv1.0.1", "v4.0.1") in model_id, and this passed it
    to getGenerationModelByVersionId as if it were a version id -- a lookup that can only
    fail (retried and printed every --sync) or answer "unresolved", which --relabel-removed
    then stamps permanently (PROBE_2026-09-26 V09). Those rows are repaired offline by the
    gallery's catalog migration instead. A video row WITH a numeric id and a blank name is
    filled like any other row: video model names are dynamic (owner ruling 3, 2026-09-26) --
    unless the id is not its engine's own (_video_model_id_fits): --sync-videos files a v2.7 /
    v3.0.1 clip under the IMAGE checkpoint its task carried, and titling that would put an
    image model's name on a video row (review V-R2)."""
    mid = (row.get("model_id") or "").strip()
    name = (row.get("model_name") or "").strip()
    if not mid and name.isdigit():
        mid = name  # model_name itself is the numeric id
    if not mid or not mid.isdigit():
        return ""
    if (str(row.get("is_video") or "").strip() == "1"
            and not _video_model_id_fits(row.get("video_model"), mid)):
        return ""
    if not name or name == mid or name.isdigit():
        return mid
    return ""


def run_fix_models(args):
    """Re-resolve human-readable model names for catalog rows whose model_name is
    blank or still a numeric version-id (e.g. saved while the model lookup was failing).
    One API call per distinct model id (cached)."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    session = _make_session(getattr(args, "token", None))
    rows = load_catalog(db_path)
    # As loaded: the save at the end merges over the rows as they are THEN (a Sync step).
    snapshot = {r["media_id"]: dict(r) for r in rows if r.get("media_id")}

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
                                   lambda v: _models.model_name_gql(session, v, strict=True),
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
        save_catalog_over_snapshot(db_path, rows, snapshot, blank_keeps=False)
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

# PixAI's curated training-base list is NOT the public generationModels catalog (the owner
# caught this -- the first build pulled the general model-picker feed). Both of PixAI's train
# pages read it, bundled with the pricing matrix and the dataset's image rule, from the public
# dynamic-config key `trainLoraModels`: GET <api>/config/trainLoraModels, no credential needed.
# The 2026-08-06 note here called that config "NOT reachable through any documented endpoint";
# it was wrong -- the key sat in the bundle all along, and the 2026-09-26 probe read it with a
# plain GET (SCOPE_2026-09-26 E7, probe findings SURF-13 / T07). training_config() now reads it
# live through _config_get, cached, and falls back to the snapshot below on any failure, so a
# failed read still offers and prices every base the site offered on 2026-09-26 -- Tsubaki.3
# (DiT.3, 100,000 credits) included. To refresh the snapshot, capture that GET and replace the
# three constants below.
_TRAIN_BASE_MODELS = [
    # (version_id, model_id, title, modelType, usage, cover)
    ("2024383379556065549", "2024383378759147749", "Tsubaki.3", "MMDIT26B_MODEL", "animation", "https://images-ng.pixai.art/images/stillThumb/87954a09-c834-48eb-ae0b-698cd9c7f471"),
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

# Training prices per architecture (the same config's pricing.pricesByModelType, 2026-09-26
# capture). PixAI's basic trainer prices a run from this matrix, keyed by modelType: `price` for
# a fresh dataset -- the only tier this app quotes, since it never reuses a dataset or retrains
# -- `reuse` when re-using an existing dataset, `retrain` for a re-run. `originalPrice` (when
# present) is the pre-discount tag and is never what a run costs. A usable free-training quota
# overrides all of it to 0, and so does a matching training free card.
_TRAIN_PRICING = {
    "SD_V1_MODEL":    {"price": 25000, "retrain": 25000, "reuse": 12500},
    "SDXL_MODEL":     {"price": 25000, "retrain": 25000, "reuse": 12500, "originalPrice": 75000},
    "DIT7_MODEL":     {"price": 50000, "retrain": 50000, "reuse": 25000, "originalPrice": 150000},
    "MMDIT26A_MODEL": {"price": 100000, "retrain": 50000, "reuse": 50000, "originalPrice": 200000},
    "MMDIT26B_MODEL": {"price": 100000, "retrain": 70000, "reuse": 70000},
}

# The dataset's image rule (the same config's imageConstraints, 2026-09-26 capture): every
# image at least minWidth wide AND minHeight high, its long side over its short side at most
# maxAspectRatio. This is the SERVER's rule shape -- the contract's TRAINING_IMAGE_REJECTED
# error carries exactly these fields -- and it is stricter than the basic wizard's own client
# check (a 262,144-pixel count and a 1:3..3:1 ratio: an 800x400 image passes that and fails
# this), so this per-side rule is the safe superset (probe T04, verifier correction).
_TRAIN_IMAGE_CONSTRAINTS = {"minWidth": 512, "minHeight": 512, "maxAspectRatio": 3}

# The architectures whose trigger words must be at least 30 characters (PixAI's own
# TrainLoraFlowHeader rule, unchanged since August: DiT.2 and DiT.3).
_TRAIN_LONG_TRIGGER_TYPES = ("MMDIT26A_MODEL", "MMDIT26B_MODEL")
TRAIN_TRIGGER_MAX = 256
TRAIN_TRIGGER_MIN_DIT = 30


# --- PixAI's public dynamic config (GET <api>/config/<key>) --------------------------------
# The site reads a handful of keys off this road (trainLoraModels, trainLoraStatus, constants,
# ...). It sits OUTSIDE the /v2 REST routes, so dev/tests/conftest.py's _rest_get/_rest_post block
# never covered it: _config_get is the ONE reader, and an autouse conftest fixture blocks it, so
# no test can reach PixAI through it. Anonymous (no credential is sent -- the 2026-09-26 probe
# read both training keys with a plain GET), short timeout, single attempt, read-only.
CONFIG_API_BASE = API_URL.rsplit("/graphql", 1)[0] + "/config"
# Cached per key, the _model_profiles discipline: an hour for an answer, a minute for a failure
# (so an unreachable key is retried once a minute, not on every call). conftest clears it.
_CONFIG_TTL = 3600.0
_CONFIG_FAIL_TTL = 60.0
_config_cache = {}                           # key -> (fetched_at_monotonic, dict|None)


def _config_get(key, timeout=10):
    """GET one public dynamic-config key. Returns the parsed JSON; raises PixAIError on a
    non-2xx or a transport failure. Callers go through _cached_config, which fails soft."""
    try:
        r = requests.get(CONFIG_API_BASE + "/" + str(key), timeout=timeout)
    except requests.exceptions.SSLError:
        raise PixAIError(_ssl_help())
    except requests.RequestException as e:
        raise PixAIError("config {} unreachable: {}".format(key, e))
    if not r.ok:
        raise PixAIError("config {} -> HTTP {}".format(key, r.status_code))
    return r.json()


def _cached_config(key, ttl=_CONFIG_TTL):
    """The config dict for `key`, or None when it could not be read (cached for
    _CONFIG_FAIL_TTL) or did not answer with a JSON object. Never raises."""
    now = time.monotonic()
    hit = _config_cache.get(key)
    if hit is not None and (now - hit[0]) < (ttl if hit[1] is not None else _CONFIG_FAIL_TTL):
        return hit[1]
    try:
        data = _config_get(key)
    except Exception:                                   # noqa: BLE001 -- fail soft to today
        data = None
    if not isinstance(data, dict):
        data = None
    _config_cache[key] = (now, data)
    return data


def _train_models_from(raw):
    """The live config's models[] as the app's row dicts, or None when it has none usable."""
    rows = (raw or {}).get("models") if isinstance(raw, dict) else None
    out = []
    for m in rows if isinstance(rows, list) else []:
        if not isinstance(m, dict):
            continue
        vid, mtype = str(m.get("versionId") or "").strip(), str(m.get("modelType") or "").strip()
        if not vid or not mtype:
            continue
        out.append({"version_id": vid, "model_id": str(m.get("modelId") or ""),
                    "title": str(m.get("modelName") or vid), "model_type": mtype,
                    "usage": str(m.get("usage") or ""), "cover": str(m.get("coverUrl") or "")})
    return out or None


def _train_pricing_from(raw):
    """The live config's pricing.pricesByModelType, integers only, or None when absent."""
    table = (((raw or {}).get("pricing") or {}).get("pricesByModelType")
             if isinstance(raw, dict) else None)
    if not isinstance(table, dict):
        return None
    out = {}
    for mtype, row in table.items():
        if not isinstance(row, dict):
            continue
        clean = {}
        for k in ("price", "retrain", "reuse", "originalPrice"):
            try:
                if row.get(k) is not None:
                    clean[k] = int(row[k])
            except (TypeError, ValueError):
                pass
        if "price" in clean:
            out[str(mtype)] = clean
    return out or None


def _train_constraints_from(raw):
    """imageConstraints off the live config, each field falling back on its own to the
    snapshot's when absent or not a positive number."""
    live = (raw or {}).get("imageConstraints") if isinstance(raw, dict) else None
    out = dict(_TRAIN_IMAGE_CONSTRAINTS)
    for k in out:
        try:
            v = float((live or {}).get(k))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = v
    return out


def training_config():
    """PixAI's basic-training config: {models, pricing, image_constraints, live}.

    Read live from /config/trainLoraModels (cached, see _cached_config) and falling back,
    piece by piece, to the 2026-09-26 snapshot above: a failed read, or a body missing a
    piece, never leaves the panel with nothing to offer or price. `live` says whether the
    model list itself came off the wire. Read-only; never raises."""
    raw = _cached_config("trainLoraModels")
    live_models = _train_models_from(raw)
    models = live_models or [
        {"version_id": v, "model_id": mid, "title": title, "model_type": mtype,
         "usage": usage, "cover": cover}
        for (v, mid, title, mtype, usage, cover) in _TRAIN_BASE_MODELS]
    pricing = _train_pricing_from(raw) or {k: dict(v) for k, v in _TRAIN_PRICING.items()}
    return {"models": models, "pricing": pricing,
            "image_constraints": _train_constraints_from(raw), "live": bool(live_models)}


def training_model_type(version_id, config=None):
    """The architecture (modelType) of a training base, by VERSION id; None if unknown."""
    cfg = config or training_config()
    return next((m["model_type"] for m in cfg["models"]
                 if m["version_id"] == str(version_id)), None)


def training_price_for_version(version_id, config=None):
    """The training price (fresh dataset: `price`, never originalPrice) for the base behind
    version_id, from the live config (snapshot fallback) -- or None if the version isn't a
    known base or its type isn't priced. None means 'unknown', which the caller must treat as
    the unsafe case. The quote and the confirm both read it through the same cache, so they
    cannot disagree within the cache's hour."""
    cfg = config or training_config()
    row = cfg["pricing"].get(training_model_type(version_id, cfg) or "")
    return row.get("price") if row else None


# The architecture PixAI marks "Recommended" on both train pages since 2026-09-27 (DiT.3), and
# the one the Session J handoff pre-selects (decision 6a, DECISIONS 2026-09-28).
TRAIN_RECOMMENDED_TYPE = "MMDIT26B_MODEL"


def default_training_base(config=None):
    """The base the panel pre-selects: the Recommended architecture's first row (Tsubaki.3 --
    the handoff's 6a and PixAI's own basic page since 2026-09-27, whose DiT.3 tab opens
    selected), else the first SDXL row (PixAI's older default, `e.find(SdxlModel) ?? e[0]`),
    else the first row. This replaces the SCOPE_2026-09-26 E7 rule that avoided Tsubaki.3 for
    its price: the price now sits on the review footer before Start, and a paid start still
    needs the amount ticked."""
    cfg = config or training_config()
    offered = [m for m in cfg["models"] if m["model_type"] in dict(_TRAIN_ARCHS)]
    pick = (next((m for m in offered if m["model_type"] == TRAIN_RECOMMENDED_TYPE), None)
            or next((m for m in offered if m["model_type"] == "SDXL_MODEL"), None)
            or (offered[0] if offered else None))
    return pick["version_id"] if pick else ""


def list_trainable_base_models(session=None, per_type=None, config=None):
    """The base models a LoRA can be trained on, grouped by architecture -- the train
    page's Model Type -> Model Theme picker, in _TRAIN_ARCHS order. Served from PixAI's own
    config (training_config: live, snapshot fallback); `session` is accepted but unused, as
    the config read is anonymous. Each model dict: {version_id, model_id, title, cover, usage}.
    version_id is what `submit_training(base_model_id=...)` takes. An architecture this app has
    no label for is left out, as the site's own chip list does."""
    cfg = config or training_config()
    groups = []
    for arch, label in _TRAIN_ARCHS:
        models = [{"version_id": m["version_id"], "model_id": m["model_id"], "title": m["title"],
                   "cover": m["cover"], "usage": m["usage"]}
                  for m in cfg["models"] if m["model_type"] == arch]
        if models:
            row = cfg["pricing"].get(arch) or {}
            groups.append({"arch": arch, "label": label, "models": models,
                           "price": row.get("price"), "reuse": row.get("reuse"),
                           "list_price": row.get("originalPrice"),
                           "recommended": arch == TRAIN_RECOMMENDED_TYPE})
    return groups


def training_free_quota(session):
    """How many FREE LoRA trainings this account can use right now -- the membership quota
    under the currency `free::user_lora_training`, counted ONLY for a member. Read-only.

    PixAI's own trainer counts the quota only when `me.membership.tier != null` (tier 0
    counts), and prices the run in full otherwise (probe T09): so this returns quotaAmount when
    the membership tier -- read in the SAME query as the quota -- is present, and 0 when it is
    absent, null, or the read failed. 0 is the safe direction: it means 'treat this as paid',
    never 'assume it's free', so the paid confirm's accept_credit_cost applies.

    The quota is ONE of the two ways a training runs free. The other is a training free card
    (kaisuuken type `training-task`): PixAI's site checks for one too and attaches it --
    match_training_kaisuuken. (Owner ruling 4, 2026-09-26: the 2026-07-26 note "the free
    trainings ARE cards" and the old docstring here, "the quota, NOT a card", were each half
    right.)"""
    try:
        d = gql_adhoc(session,
                      "query($currency:String!){ me { id membership { tier }"
                      " quotaAmount(currency:$currency) } }",
                      {"currency": _TRAIN_FREE_CURRENCY}) or {}
        me = d.get("me") or {}
        membership = me.get("membership")
        tier = membership.get("tier") if isinstance(membership, dict) else None
        if tier is None:
            return 0
        return max(0, int(me.get("quotaAmount") or 0))
    except (PixAIError, requests.RequestException, TypeError, ValueError, AttributeError):
        return 0


def match_training_kaisuuken(session, base_version_id, raise_on_error=False):
    """The read-only training free-card check: /v2/kaisuuken/check with PixAI's own training
    shape {type: "training-task", baseModelId: <base VERSION id>, version: 2} (the site's
    useKaisuukenMatch). Same result and coverage rules as match_kaisuuken; nothing is
    consumed until createTrainingTask carries the returned id."""
    return match_kaisuuken(session, None, enrich=True, raise_on_error=raise_on_error,
                           training_base_model_id=base_version_id)


# The training pause switch's cache clock: PixAI's own pages poll it once a minute.
_TRAIN_STATUS_TTL = 60.0


def training_pause():
    """None when LoRA training is open -- or when the pause switch could not be read, which
    proceeds exactly as before this check existed -- else {"resumes_at": iso-or-""}.

    PixAI's public /config/trainLoraStatus: paused when `state == "PAUSED"` or
    `disabled == true` (its trainLoraStatus module); `resumesAt` is named only when it parses
    to a time still in the future. While paused the site redirects both train pages to a
    notice; this app refuses the submit instead. Read-only, cached for a minute."""
    raw = _cached_config("trainLoraStatus", ttl=_TRAIN_STATUS_TTL)
    if not isinstance(raw, dict):
        return None
    if not (raw.get("state") == "PAUSED" or raw.get("disabled") is True):
        return None
    resumes = ""
    ra = raw.get("resumesAt")
    if isinstance(ra, str) and ra.strip():
        try:
            when = datetime.datetime.fromisoformat(ra.strip().replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            if when > datetime.datetime.now(datetime.timezone.utc):
                resumes = when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
    return {"resumes_at": resumes}


def normalize_trigger_words(text):
    """PixAI's own trigger-word normalizer, in its order (the train page's he()): runs of
    CR/LF become ", "; any whitespace run becomes one space; a run of commas with spaces
    between them becomes one ", "; lowercase; then leading and trailing commas and whitespace
    are stripped. The string validate_training checks -- and the one submitted -- is this."""
    s = str(text or "")
    s = re.sub(r"[\r\n]+", ", ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r",\s*(?:,\s*)+", ", ", s)
    s = s.lower()
    return re.sub(r"^[,\s]+|[,\s]+$", "", s)


def trigger_word_length(text):
    """A trigger-word string's length as PixAI's page measures it: JavaScript's
    `String.length`, i.e. UTF-16 code units -- a character outside the Basic Multilingual
    Plane, such as an emoji, counts 2. Python's len() would count it once, and so let through a
    256-emoji string PixAI refuses as too long while refusing a 15-emoji DiT.3 trigger it
    accepts. The train panel's counter shows the same number (normalizeTrigger in
    gallery/src/gen/trainCore.js)."""
    return len(str(text or "").encode("utf-16-le")) // 2


def validate_training(base_model_id, media_ids, title, trigger_words, category,
                      training_task_id="", config=None):
    """Mirror the site's OWN pre-submit validation (its Er() builder) so a bad request is
    refused here instead of burning a round trip -- or worse, a free-training quota unit.
    Returns the normalized trigger words. Raises PixAIError with a plain-language reason.

    Trigger words follow PixAI's rule on the NORMALIZED string: empty refused, over 256
    characters refused, and under 30 refused on a DiT.2 / DiT.3 base (MMDIT26A / MMDIT26B).
    The image rule needs each image's size, which this has no way to know -- the caller runs
    check_training_images over its own catalog."""
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
    # Counted the way the site counts them (trigger_word_length: JavaScript's `length`, UTF-16
    # code units), so an emoji is 2 here as it is there.
    units = trigger_word_length(tw)
    if units > TRAIN_TRIGGER_MAX:
        raise PixAIError("trigger words are too long -- %d characters at most, yours are %d"
                         % (TRAIN_TRIGGER_MAX, units))
    if training_model_type(base_model_id, config) in _TRAIN_LONG_TRIGGER_TYPES \
            and units < TRAIN_TRIGGER_MIN_DIT:
        raise PixAIError("trigger words must be at least %d characters on a DiT.2 or DiT.3 "
                         "base -- yours are %d" % (TRAIN_TRIGGER_MIN_DIT, units))
    if str(category or "") not in TRAIN_CATEGORIES:
        raise PixAIError("pick a category (%s)" % "/".join(TRAIN_CATEGORIES))
    return tw


def check_training_images(media_ids, dims, constraints=None):
    """Hold each dataset image to PixAI's training image rule (training_config's
    image_constraints: each side at least minWidth / minHeight, long side over short side at
    most maxAspectRatio). `dims` is {media_id: (width, height)} from the caller's catalog.

    Returns (rejected, unchecked): `rejected` is [{media_id, width, height, why}] for images
    the rule refuses; `unchecked` lists the ids whose size is unknown (not in `dims`, or not
    positive numbers) -- those are NOT passed as checked, the caller says they were not.

    This app REFUSES a run holding a rejected image, naming each one. PixAI's own basic
    wizard silently drops them and trains on the rest; refusing is deliberate here, so a paid
    run never trains on a different dataset than the one picked."""
    c = dict(_TRAIN_IMAGE_CONSTRAINTS)
    c.update(constraints or training_config()["image_constraints"])
    min_w, min_h, max_ar = float(c["minWidth"]), float(c["minHeight"]), float(c["maxAspectRatio"])
    rejected, unchecked = [], []
    for mid in [str(m) for m in (media_ids or []) if str(m).strip()]:
        wh = (dims or {}).get(mid)
        try:
            w, h = float(wh[0]), float(wh[1])
        except (TypeError, ValueError, IndexError, KeyError):
            w = h = 0.0
        if not (w > 0 and h > 0):
            unchecked.append(mid)
            continue
        if w < min_w or h < min_h:
            why = "smaller than %dx%d" % (min_w, min_h)
        elif max(w, h) / min(w, h) > max_ar:
            why = "longer than %g:1" % max_ar
        else:
            continue
        rejected.append({"media_id": mid, "width": int(w), "height": int(h), "why": why})
    return rejected, unchecked


def describe_rejected_training_images(rejected):
    """The refusal's own words for check_training_images' `rejected` list."""
    shown = ", ".join("%s (%dx%d, %s)" % (r["media_id"], r["width"], r["height"], r["why"])
                      for r in rejected[:8])
    more = " and %d more" % (len(rejected) - 8) if len(rejected) > 8 else ""
    return ("PixAI won't train on %d of these images — remove %s and try again: %s%s."
            % (len(rejected), "it" if len(rejected) == 1 else "them", shown, more))


def submit_training(session, base_model_id, media_ids, title, trigger_words, category,
                    training_task_id="", primary_lora_model_id="", kaisuuken_id="",
                    config=None):
    """Submit a real LoRA training task to PixAI (`createTrainingTask`).

    SPENDS unless the account has usable free-training quota left (training_free_quota) or
    the caller attaches a matching training free card (`kaisuuken_id`, from
    match_training_kaisuuken) -- so it goes through gql_mutate: SINGLE ATTEMPT, no retry, for
    exactly the reason
    every other spend path does. A lost response after the server accepted the task
    would, on retry, start a SECOND training and consume a second quota unit (or a real
    credit charge, which for training is large). _check_read_only gates it like every
    other account mutation.

    This function does NOT decide whether the user wants to pay: callers preview first
    (quota + validation) and only call this once the user has confirmed. Input shape
    mirrors the site's own form exactly. Returns the created task dict.

    `config` is the caller's training_config() -- the one it previewed and priced against --
    so this validates against the SAME config instead of a fresh re-read that could differ.
    A refusal before the network call (READ_ONLY, validation) is raised as LocalRefusal:
    nothing was sent, and the caller's spend guard must not say a run may have started."""
    try:
        _check_read_only("submit a LoRA training task")
        tw = validate_training(base_model_id, media_ids, title, trigger_words, category,
                               training_task_id, config=config)
    except LocalRefusal:
        raise
    except PixAIError as e:
        raise LocalRefusal(str(e)) from e
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


# --- LoRA training: the advanced flow, runs, publish (Session J, 2026-09-28) ------------------
# PixAI's advanced trainer is a draft (GraphQL createTrainingTask, trainingMode "advanced", no
# images, free) worked on through REST under /v2/training-task/{id}: the dataset (PUT media,
# free), a PAID describe round (POST caption, priced per task by GET caption-price), the owner's
# own edits of those descriptions (PUT captions/{mediaId}, free, only once a machine description
# exists), a PAID start (POST submit, priced by GET price), a PAID retry of a failed run (a NEW
# run), and an irreversible publish. Every writer below calls _check_read_only first and rides a
# single-attempt transport (gql_mutate, rest_post, rest_put, rest_patch). Callers preview and
# acknowledge; nothing here decides that the user wants to pay. The wire facts and the guard
# order are in ../moonglade-internal/design/notes/training/BUILD-w3-train.md.

# Basic's four goals (and Advanced's categories), PixAI's own values: its "Something else"
# sub-kind is never sent.
TRAIN_GOALS = (("character", "Character"), ("style", "Art style"), ("clothing", "Outfit"),
               ("other", "Something else"))
# The architectures Advanced offers (Tsubaki.3 Recommended, then Tsubaki.2).
TRAIN_ADVANCED_TYPES = ("MMDIT26B_MODEL", "MMDIT26A_MODEL")
# What PixAI's own advanced page submits: its parameter controls are inert ("coming soon") and
# it sends these defaults. Sent verbatim -- the quote route takes no length, and PixAI's own
# fallback price scales with it, so an unquoted length is never sent (spend review, finding 3).
TRAIN_DEFAULT_OPTIONS = {"trainingSteps": 325, "learningRate": 0.0006, "rank": 64,
                         "gradAccum": 2}
# A description, as PixAI's editor caps it (its contract would take 20,000; the editor is the
# rule users meet).
TRAIN_CAPTION_MAX = 1000

_TRAINING_TASK_FIELDS = ("id userId status trainingMode type refId retryCount createdAt "
                         "updatedAt startedAt endAt parameters { title mediaIds category "
                         "baseModelId triggerWords } extra { progress estimatedTotalTime } "
                         "outputs { message }")
_TRAINING_TASK_Q = "query($id: ID!) { trainingTask(id: $id) { " + _TRAINING_TASK_FIELDS + " } }"
_MY_LORAS_Q = ("query($au: ID, $ty: GenerationModelType, $n: Int, $b: String) { "
               "generationModels(authorId: $au, type: $ty, last: $n, before: $b) { "
               "pageInfo { hasPreviousPage startCursor } edges { node { id title isPrivate "
               "visibilityType createdAt mediaId latestAvailableVersion { id } trainingTask { "
               + _TRAINING_TASK_FIELDS + " } } } } }")
_GEN_MODEL_Q = ("query($id: ID!) { generationModel(id: $id) { id authorId title type isPrivate "
                "visibilityType } }")
_UPSERT_MODEL = ("mutation upsertGenerationModel($id: ID, $input: UpsertGenerationModelInput!) "
                 "{ upsertGenerationModel(id: $id, input: $input) { id isPrivate "
                 "visibilityType } }")


def training_eta(steps=325):
    """PixAI's own estimate (its advanced page's Br()): t = max(1, round(steps * 27 / 325))
    minutes, shown as "about t to round(t * 1.3) minutes" -- 27-35 at the default, the same
    number its basic page prints."""
    t = max(1, int(round(float(steps) * 27.0 / 325.0)))
    return {"min": t, "max": int(round(t * 1.3))}


def advanced_training_bases(config=None):
    """The two bases Advanced offers: one row per advanced architecture (an "animation" row
    preferred, as the site picks), Recommended first. [{version_id, title, cover, model_type,
    recommended}]."""
    cfg = config or training_config()
    out = []
    for mtype in TRAIN_ADVANCED_TYPES:
        rows = [m for m in cfg["models"] if m["model_type"] == mtype]
        pick = next((m for m in rows if m.get("usage") == "animation"), None) or \
            (rows[0] if rows else None)
        if pick:
            out.append({"version_id": pick["version_id"], "title": pick["title"],
                        "cover": pick["cover"], "model_type": mtype,
                        "recommended": mtype == TRAIN_RECOMMENDED_TYPE})
    return out


def training_price_tier(version_id, tier="price", config=None):
    """A base's price at one tier of PixAI's matrix (`price` fresh, `reuse` a reused dataset),
    or None when unknown. Never `originalPrice`."""
    cfg = config or training_config()
    row = cfg["pricing"].get(training_model_type(version_id, cfg) or "") or {}
    v = row.get(tier)
    return v if isinstance(v, int) else None


# PixAI's own "rejected" list: the 20 codes its site's create flow (useHeldTaskPrice `ye`)
# treats as "no task was made" (DESIGN_3.22 1.3). Every other code it may answer is, to the
# site as to this app, an UNKNOWN outcome.
PIXAI_REJECTED_CODES = frozenset({
    "FORBIDDEN", "BAD_REQUEST", "INVALID_INPUT", "MODEL_DEPRECATED", "TOO_MANY_REQUESTS",
    "INVALID_PARAMETERS_COMPATIBILITY", "NO_PERMISSION_FOR_GENERATION", "REQUIRE_T_2_MEMBERSHIP",
    "INSUFFICIENT_BALANCE", "WAITING_NUM_EXCEEDED", "WATERMARK_NOT_AVAILABLE",
    "NSFW_PROMPTS_DETECTED", "NSFW_PROMPTS_DETECTED_ADULT_NOT_SET", "NO_PERMISSION_FOR_PREVIEW",
    "NO_PERMISSION_FOR_EARLY_ACCESS", "KAISUUKEN_NOT_AVAILABLE", "KAISUUKEN_NOT_ALLOWED",
    "RECIPE_UNAVAILABLE", "RECIPE_INCOMPATIBLE", "REQUIRE_MEMBERSHIP",
})
# The codes a spend reads as "refused, nothing made" (DESIGN_3.22 2.6): PixAI's list above, and
# three the create route answers before any task exists -- the credential is checked before the
# handler runs (UNAUTHORIZED), the schema before it (VALIDATION_ERROR), and the site's own form
# checks the lane entitlement before it submits (INFINITE_MODE_NOT_ELIGIBLE). Promoting another
# code needs evidence and a design note: "unknown" costs a held button, never money.
DEFINITE_CODES = PIXAI_REJECTED_CODES | {"UNAUTHORIZED", "VALIDATION_ERROR",
                                         "INFINITE_MODE_NOT_ELIGIBLE"}
# The training routes' family (DESIGN_3.22 2.6, V5): PixAI's list plus every code the training
# routes declare in their error maps (harvest 938fb68efeea `trainingTask-DTATiVlJ.js`). Each
# refuses the request against the task's current state, so no new run exists after it -- a clear
# training refusal never holds Start, Describe or Retry. Never used for a create.
TRAINING_CODES = PIXAI_REJECTED_CODES | {
    "BAD_REQUEST", "INVALID_INPUT", "UNAUTHORIZED",                 # request and auth
    "NOT_FOUND", "FORBIDDEN", "CONFLICT",                           # the task
    "TRAINING_IMAGE_REJECTED", "TRAINING_DATASET_TOO_SMALL",         # the dataset
    "MODEL_PUBLISH_CONFLICT", "LORA_REBATE_REQUIRES_PUBLIC",         # publishing
    "INSUFFICIENT_BALANCE",                                          # credits
}
# `codes=ANY_PIXAI_CODE`: any code in PixAI's oRPC error body is a refusal -- for a non-spend
# write whose route answers its own codes before it acts and whose caller reads the outcome
# back (the inbox: mark read, reply, delete a reply, claim a gift). A spend never uses it.
ANY_PIXAI_CODE = None
# A REST timeout (408) or a closed-request (499) answer is never a refusal, whatever its body
# says: PixAI, or an edge in front of it, may have accepted the request before it said so.
_UNKNOWN_OUTCOME_STATUSES = frozenset({408, 499})


def classify_outcome(exc, codes=DEFINITE_CODES):
    """What a failed send's exception proves: "local" (refused HERE, nothing sent), "refused"
    (PixAI answered no, so nothing was created or charged) or "unknown" (it may exist and may be
    charged: a spend guard reads it as "may have started").

    It reads the exception's TYPE and structured fields only, never its message text
    (DESIGN_3.22 2.6; the 3.21.2 fix L2):
      - LocalRefusal: local.
      - PixAIRestError: refused only when the status is a 4xx other than 408 and 499 AND the
        body is PixAI's oRPC error (a JSON object with a string `code`) whose code is in
        `codes`. A bare 4xx (an edge's page, no PixAI body), a 3xx, a 5xx and any other code:
        unknown. `codes=None` accepts any PixAI code -- for a route whose own codes are all
        answered before it acts and whose outcome the caller reads back (the inbox's).
      - PixAIAuthError (the GraphQL road's 401): refused.
      - a GraphQL error (the transport hangs the `errors` list on it as `graphql_errors`):
        refused only when its `data` resolved nothing. A root field that came back non-null
        beside `errors` is a PARTIAL SUCCESS -- the task exists and may be charged (waves 2+3
        review, F2) -- so it is unknown.
      - anything else (a timeout, a dropped connection, a non-JSON or id-less answer): unknown."""
    if isinstance(exc, LocalRefusal):
        return "local"
    if isinstance(exc, PixAIRestError):
        try:
            status = int(exc.status)
        except (TypeError, ValueError):
            return "unknown"
        if not 400 <= status < 500 or status in _UNKNOWN_OUTCOME_STATUSES:
            return "unknown"
        body = exc.body
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not code:
            return "unknown"
        return "refused" if (codes is None or code in codes) else "unknown"
    if isinstance(exc, PixAIAuthError):
        return "refused"
    if isinstance(exc, PixAIError):
        errors = getattr(exc, "graphql_errors", None)
        if isinstance(errors, list) and errors:
            partial = getattr(exc, "graphql_data", None)
            if isinstance(partial, dict) and any(v is not None for v in partial.values()):
                return "unknown"
            # 3.21.2 review: an `errors` answer with no data is a refusal ONLY when every error
            # names a definite code. An INTERNAL_SERVER_ERROR, an "upstream request timeout"
            # with no code, or any code outside the table may sit in front of a task PixAI made.
            for err in errors:
                code = graphql_error_code(err)
                if code is None or (codes is not None and code not in codes):
                    return "unknown"
            return "refused"
    return "unknown"


# A numeric GraphQL code with a known name. Evidence: 40300047 is PixAI's members-only refusal
# (private/CLASS4_PROBE_2026-07-28.md section 6, live 403s; the Turbo resubmit has keyed on it
# since 2026-07, DESIGN_3.22 2.7). Other numbers seen (40300027 LORA_NUM_EXCEEDED, 40300032
# NSFW_DETECTED) name codes outside the definite tables, so they are left unknown.
_GRAPHQL_NUMERIC_CODES = {40300047: "REQUIRE_MEMBERSHIP"}


def graphql_error_code(err):
    """One GraphQL error's code name, or None. Read where PixAI's own site reads it
    (errorUtil `c`: `errors[i].extensions.exception.name`), then `extensions.code`, then a
    top-level `code`; a known numeric code is mapped to its name. Never the message."""
    if not isinstance(err, dict):
        return None
    ext = err.get("extensions") if isinstance(err.get("extensions"), dict) else {}
    exc = ext.get("exception") if isinstance(ext.get("exception"), dict) else {}
    for raw in (exc.get("name"), exc.get("code"), ext.get("code"), err.get("code")):
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, int) and not isinstance(raw, bool) and raw in _GRAPHQL_NUMERIC_CODES:
            return _GRAPHQL_NUMERIC_CODES[raw]
    return None


def outcome_reason(exc):
    """PixAI's own reason for a failed send, in a short line for the user beside "may have
    started" (an NSFW_DETECTED or INPUT_IMAGE_TOO_LARGE that is not a definite refusal, an
    expired sign-in's 401): the oRPC code and message, the GraphQL errors' messages and codes,
    else the exception's text. Display only -- never an input to classify_outcome."""
    if isinstance(exc, PixAIRestError):
        f = exc.fields
        code = f.get("code") if isinstance(f.get("code"), str) else ""
        text = f.get("message") if isinstance(f.get("message"), str) else ""
        head = "HTTP {}".format(exc.status) if exc.status is not None else "PixAI"
        if code or text:
            return "{}: {}".format(head, " -- ".join(x for x in (code, text.strip()) if x))
        return "{}: {}".format(head, str(exc).split(": ", 1)[-1][:200])
    errors = getattr(exc, "graphql_errors", None)
    if isinstance(errors, list) and errors:
        bits = []
        for e in errors:
            if isinstance(e, dict):
                code = graphql_error_code(e)
                msg = str(e.get("message") or "").strip()
                bits.append(msg + (" ({})".format(code) if code else ""))
        if any(bits):
            return "; ".join(b for b in bits if b)
    return "{}: {}".format(type(exc).__name__, str(exc)) if not isinstance(exc, PixAIError) \
        else str(exc)


def definite_refusal(exc, codes=DEFINITE_CODES):
    """True when nothing was created or charged: refused here before the network call
    (LocalRefusal: READ_ONLY, the request's own validation) or refused by PixAI in a way that
    proves no task exists. False for anything that may have reached PixAI and succeeded,
    which a spend guard must treat as "may have started". The rule is classify_outcome's."""
    return classify_outcome(exc, codes) in ("local", "refused")


def send_outcome(exc, reached):
    """A single send's state after `exc`: "not_sent" when the one spend request was never
    reached (`reached` False: everything before it is local or a read), else "refused" when
    the answer proves nothing was made (definite_refusal, or a refusal this app re-raised with
    `refused = True` after that same check), else "may_have_started"."""
    if not reached:
        return "not_sent"
    if getattr(exc, "refused", False) is True or definite_refusal(exc):
        return "refused"
    return "may_have_started"


# What a command-line single send prints when its answer cannot show whether a task was made
# (DESIGN_3.22 2.12). No catch-up runs for a CLI user, so it never promises one.
CLI_UNCLEAR = ("PixAI may have started this (task not confirmed). Check pixai.art or run "
               "--sync before running this again.")


class SendOutcomeUnclear(Exception):
    """A command-line single send that reached PixAI and got no answer that proves either
    way: the task may exist and may be charged. The message is CLI_UNCLEAR and the cause is
    chained. Deliberately NOT a PixAIError (DESIGN_3.22 2.2), so no guard that reads "a plain
    PixAIError was raised before the send" can ever mistake it for nothing-sent; main() exits
    non-zero on it."""


def _cli_send_once(send, reached=lambda: True):
    """Run a CLI runner's ONE send. A refusal comes back as it came (PixAI's words); an
    unknown outcome after the send was reached raises SendOutcomeUnclear. Never re-sends."""
    try:
        return send()
    except Exception as e:                                   # noqa: BLE001 -- re-raised below
        if send_outcome(e, reached()) != "may_have_started":
            raise
        detail = "{}: {}".format(type(e).__name__, str(e)[:200]).strip()
        raise SendOutcomeUnclear(CLI_UNCLEAR + "\n  PixAI's answer: " + detail) from e


def _cli_create_once(create_session, params):
    """The video, reference-video and edit runners' ONE createGenerationTask, through
    gql_mutate (single attempt, never a redirect). Returns the task id. An answer with no id
    is as unclear as a lost one, so it is raised inside the send and reads unclear too."""
    def _send():
        created = gql_mutate(create_session, _GEN_MUTATION, {"parameters": params})
        task_id = (created.get("createGenerationTask") or {}).get("id")
        if not task_id:
            raise PixAIError("no task id returned: " + json.dumps(created)[:300])
        return task_id
    return _cli_send_once(_send)


_TRAIN_ERROR_WORDS = {
    "TRAINING_IMAGE_REJECTED": "PixAI won't train on some of these images (smaller than its "
                               "minimum size, or too long and thin)",
    "TRAINING_DATASET_TOO_SMALL": "PixAI needs more images in this set before it can go on",
    "INSUFFICIENT_BALANCE": "there aren't enough credits on the account; nothing was charged",
    "MODEL_PUBLISH_CONFLICT": "another public LoRA already uses these weights",
    "LORA_REBATE_REQUIRES_PUBLIC": "only a public LoRA can join rebates",
}


def training_error_words(exc):
    """A PixAI training refusal in plain words: its defined code where it sent one, its own
    message otherwise."""
    if isinstance(exc, PixAIRestError):
        if exc.code in _TRAIN_ERROR_WORDS:
            return _TRAIN_ERROR_WORDS[exc.code]
        msg = str(exc.fields.get("message") or "").strip()
        if msg:
            return msg
    return str(exc)


def _task_path(task_id, suffix=""):
    tid = str(task_id or "").strip()
    if not tid.isdigit():
        raise PixAIError("not a training task id: %r" % (task_id,))
    return "/training-task/" + tid + suffix


def training_task(session, task_id):
    """One training task by id (GraphQL trainingTask) -- basic or advanced -- or raises.
    Read-only. `extra.progress` is PixAI's percentage (0-100) and `estimatedTotalTime` its
    whole-run estimate in milliseconds, both only while it runs."""
    d = gql_adhoc(session, _TRAINING_TASK_Q, {"id": str(task_id)}) or {}
    t = d.get("trainingTask")
    if not isinstance(t, dict):
        raise PixAIError("training task %s not found" % task_id)
    return t


def list_training_in_progress(session, limit=100):
    """Every advanced task still in the owner's hands (drafts through failed), newest activity
    first: [{id, status, title, baseModelId, mediaCount, updatedAt}]. Read-only."""
    d = _rest_get(session, "/training-task/in-progress",
                  params={"limit": max(1, min(int(limit), 100))}) or {}
    return [t for t in (d.get("tasks") or []) if isinstance(t, dict)]


def list_training_completed(session, limit=100):
    """Every finished advanced task, newest first, published or not (`modelId` null until
    published): [{id, title, baseModelId, mediaCount, modelId, completedAt}]. Read-only."""
    d = _rest_get(session, "/training-task/completed",
                  params={"limit": max(1, min(int(limit), 100))}) or {}
    return [t for t in (d.get("tasks") or []) if isinstance(t, dict)]


def list_my_trained_loras(session, pages=3, per_page=20):
    """The account's own trained LoRAs with the run behind each (GraphQL generationModels
    authorId + ANY_USER_LORA, the list PixAI's "Import from previous datasets" reads), newest
    first, up to `pages` pages. Each row: {model_id, title, is_private, visibility, created_at,
    cover_media_id, version_id, task} where task is the TrainingTask dict or None. Read-only."""
    uid = str(_pixai_client._client_of(session).user_id or "")
    out, before = [], None
    for _ in range(max(1, int(pages))):
        v = {"au": uid, "ty": "ANY_USER_LORA", "n": int(per_page)}
        if before:
            v["b"] = before
        d = (gql_adhoc(session, _MY_LORAS_Q, v) or {}).get("generationModels") or {}
        rows = []
        for e in d.get("edges") or []:
            n = (e or {}).get("node") or {}
            if not n.get("id"):
                continue
            ver = n.get("latestAvailableVersion") or {}
            rows.append({"model_id": str(n["id"]), "title": str(n.get("title") or ""),
                         "is_private": bool(n.get("isPrivate")),
                         "visibility": str(n.get("visibilityType") or ""),
                         "created_at": str(n.get("createdAt") or ""),
                         "cover_media_id": str(n.get("mediaId") or ""),
                         "version_id": str(ver.get("id") or ""),
                         "task": n.get("trainingTask") if isinstance(n.get("trainingTask"), dict)
                         else None})
        out.extend(reversed(rows))                 # `last` pages come oldest-first
        info = d.get("pageInfo") or {}
        if not info.get("hasPreviousPage") or not info.get("startCursor"):
            break
        before = info["startCursor"]
    return out


def training_caption_quote(session, task_id):
    """What the next describe round would charge: {image_count, total_price} -- PixAI's own
    per-task quote (the images with no machine description yet, times the unit price). The
    config's captionPricing is stale (100 there; 150 on the owner's capture draft), so this,
    never the config, is the number shown and acknowledged. Read-only."""
    d = _rest_get(session, _task_path(task_id, "/caption-price")) or {}
    if not isinstance(d.get("totalPrice"), (int, float)):
        raise PixAIError("PixAI returned no describe price for training task %s" % task_id)
    return {"image_count": int(d.get("imageCount") or 0),
            "total_price": int(d.get("totalPrice") or 0)}


def training_quote(session, task_id):
    """What starting (or retrying) this advanced task would charge today, by its base model --
    PixAI's own free quote (GET price). Read-only. Returns an int."""
    d = _rest_get(session, _task_path(task_id, "/price")) or {}
    if not isinstance(d.get("price"), (int, float)):
        raise PixAIError("PixAI returned no price for training task %s" % task_id)
    return int(d["price"])


def training_captions(session, task_id):
    """The task's descriptions: [{media_id, source (machine|user), caption_url, machine_url,
    user_url}]. The links are short-lived; fetch_caption_text reads each. Read-only."""
    d = _rest_get(session, _task_path(task_id, "/captions")) or {}
    out = []
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("mediaId"):
            out.append({"media_id": str(it["mediaId"]), "source": str(it.get("source") or ""),
                        "caption_url": str(it.get("captionUrl") or ""),
                        "machine_url": str(it.get("machineCaptionUrl") or ""),
                        "user_url": str(it.get("userCaptionUrl") or "")})
    return out


def fetch_caption_text(url, limit=64 * 1024):
    """One description's text from its time-limited link (PixAI's own page fetches it the same
    way, without credentials). HTTPS only; NO PixAI credential rides this request -- a plain
    requests.get, never the account session; capped at `limit` bytes. Returns None on any
    failure (the caller shows the description as unreadable, never as empty-and-editable)."""
    u = str(url or "")
    if not u.startswith("https://"):
        return None
    try:
        r = requests.get(u, timeout=15, stream=True)
        if not r.ok:
            return None
        raw = r.raw.read(limit + 1, decode_content=True) or b""
        return raw[:limit].decode("utf-8", "replace").strip()
    except (requests.RequestException, OSError, ValueError):
        return None


def create_advanced_training_draft(session, base_model_id, title, trigger_words, category,
                                   config=None):
    """Create an ADVANCED training draft -- PixAI's own step-1 call (createTrainingTask with
    {type: LORA, trainingMode: advanced, title, category, baseModelId, triggerWords}, no
    images). FREE, but it writes to the account, so it runs only on the user's deliberate
    "Next · creates a draft" (DECISIONS 2026-09-28, nothing writes on open). Name, category,
    base and trigger words are fixed from here. Single attempt. Returns {id}."""
    _check_read_only("create a LoRA training draft")
    cfg = config or training_config()
    bases = {b["version_id"] for b in advanced_training_bases(cfg)}
    if str(base_model_id) not in bases:
        raise PixAIError("Advanced training runs on Tsubaki.3 or Tsubaki.2 only")
    if str(category or "") not in dict(TRAIN_GOALS):
        raise PixAIError("pick what you are training (%s)" % ", ".join(
            lab for _, lab in TRAIN_GOALS))
    # the dataset floor is checked when describing and starting, not here: a draft has none
    tw = validate_training(base_model_id, [], title, trigger_words, category,
                           training_task_id="draft", config=cfg)
    inp = {"type": "LORA", "trainingMode": "advanced", "title": str(title).strip(),
           "category": str(category), "baseModelId": str(base_model_id), "triggerWords": tw}
    d = gql_mutate(session, _CREATE_TRAINING, {"input": inp}) or {}
    task = d.get("createTrainingTask") or {}
    if not task.get("id"):
        raise PixAIError("PixAI created no draft")
    return {"id": str(task["id"])}


def replace_training_media(session, task_id, media_ids):
    """Replace an advanced task's whole image list (PUT media, <=100, free). Single attempt."""
    _check_read_only("change a LoRA training set")
    ids = []
    for m in media_ids or []:
        m = str(m).strip()
        if m and m not in ids:
            ids.append(m)
    if len(ids) > TRAIN_MAX_IMAGES:
        raise PixAIError("training takes at most %d images -- you have %d"
                         % (TRAIN_MAX_IMAGES, len(ids)))
    d = _rest_put(session, _task_path(task_id, "/media"), {"mediaIds": ids}) or {}
    return [str(m) for m in (d.get("mediaIds") or ids)]


def start_training_captions(session, task_id):
    """PAID: send the set's undescribed images to PixAI's describe round (POST caption). The
    caller has quoted it (training_caption_quote) and had the amount acknowledged. Single
    attempt. Returns PixAI's new status."""
    _check_read_only("describe LoRA training images (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/caption"), {}) or {}
    return str(d.get("status") or "")


def save_training_caption(session, task_id, media_id, text):
    """Save the owner's own description for one image (PUT captions/{mediaId}; free; PixAI
    keeps it as a new version, the machine's stays on file). Only for an image PixAI has
    described already. 1 to TRAIN_CAPTION_MAX characters. Single attempt."""
    _check_read_only("edit a LoRA training description")
    t = str(text or "").strip()
    if not t:
        raise PixAIError("a description can't be empty")
    if len(t) > TRAIN_CAPTION_MAX:
        raise PixAIError("a description is %d characters at most -- this one is %d"
                         % (TRAIN_CAPTION_MAX, len(t)))
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        raise PixAIError("which image?")
    _rest_put(session, _task_path(task_id, "/captions/" + mid), {"text": t})
    return t


def submit_advanced_training(session, task_id):
    """PAID: start an advanced run (POST submit) with PixAI's own default options, exactly as
    its page sends them (TRAIN_DEFAULT_OPTIONS). No free card rides it -- PixAI's page attaches
    none. The caller has quoted it (training_quote) and had the amount acknowledged. Single
    attempt. Returns PixAI's new status."""
    _check_read_only("start a LoRA training run (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/submit"),
                   {"trainingOptions": dict(TRAIN_DEFAULT_OPTIONS)}) or {}
    return str(d.get("status") or "")


def retry_training(session, task_id):
    """PAID: a NEW run from a failed advanced one (POST retry: same set, same descriptions,
    charged again at today's price). The failed task stays as it is, so a second call would
    start and charge a second run -- the caller guards against that. Single attempt. Returns
    {id (the new run), origin_id, status}."""
    _check_read_only("retry a LoRA training run (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/retry"), {}) or {}
    return {"id": str(d.get("trainingTaskId") or ""),
            "origin_id": str(d.get("originTaskId") or task_id),
            "status": str(d.get("status") or "")}


def publish_training(session, task_id, visibility, rebate):
    """IRREVERSIBLE: turn a finished advanced run into a LoRA (POST publish, once per run).
    visibility private|public; rebate join|decline, and join only when public (refused here
    before PixAI would). Single attempt. Returns {model_id, version_id}."""
    _check_read_only("publish a trained LoRA")
    if visibility not in ("private", "public"):
        raise PixAIError("publish it private or public")
    if rebate not in ("join", "decline"):
        raise PixAIError("join or decline rebates")
    if rebate == "join" and visibility != "public":
        raise PixAIError(_TRAIN_ERROR_WORDS["LORA_REBATE_REQUIRES_PUBLIC"])
    d = _rest_post(session, _task_path(task_id, "/publish"),
                   {"visibility": visibility, "loraRebate": rebate}) or {}
    return {"model_id": str(d.get("modelId") or ""), "version_id": str(d.get("versionId") or "")}


def make_model_public(session, model_id):
    """IRREVERSIBLE: a private LoRA of yours goes public (upsertGenerationModel with just
    {isPrivate: false}, exactly the site's call). Single attempt."""
    _check_read_only("make a LoRA public")
    d = gql_mutate(session, _UPSERT_MODEL, {"id": str(model_id),
                                            "input": {"isPrivate": False}}) or {}
    return d.get("upsertGenerationModel") or {}


def lora_rebate_eligibility(session, model_id):
    """PixAI's rebate check for one of your LoRAs: {offered, joined, can_join}. Read-only;
    a failed read answers not offered."""
    try:
        d = _rest_get(session, "/generation-model/%s/lora-rebate-eligibility"
                      % str(model_id).strip()) or {}
    except (PixAIError, requests.RequestException):
        return {"offered": False, "joined": False, "can_join": False}
    offered = d.get("featureStatus") == "enabled"
    joined = offered and d.get("eligibility") == "accept"
    allowed = d.get("allowedTargetEligibilities") or []
    return {"offered": offered, "joined": joined,
            "can_join": offered and not joined and "accept" in allowed}


_THUMB_VARIANTS = ("STILL_THUMBNAIL", "THUMBNAIL", "PUBLIC", "ORIGINAL")


def media_thumbnail_url(session, media_id):
    """A small picture URL for one PixAI media id -- for training-set images this library has
    no thumbnail of (an upload, or an image imported from an earlier set). Reads the media
    object (GET /v1/media/<id>, read-only) and prefers a thumbnail variant. None on failure."""
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        return None
    try:
        r = session.get(MEDIA_BASE.format(id=mid), timeout=20)
        r.raise_for_status()
        obj = r.json()
    except (requests.RequestException, ValueError):
        return None
    by = {str(u.get("variant", "")).upper(): u.get("url") for u in (obj.get("urls") or [])
          if isinstance(u, dict) and u.get("url")}
    for v in _THUMB_VARIANTS:
        if by.get(v):
            return by[v]
    return next(iter(by.values()), None)


def join_lora_rebates(session, model_id):
    """IRREVERSIBLE: join one of your public LoRAs to the rebate programme (PATCH
    lora-rebate-eligibility {eligibility: accept}, the site's call). Single attempt."""
    _check_read_only("join a LoRA to rebates")
    return _rest_patch(session, "/generation-model/%s/lora-rebate-eligibility"
                       % str(model_id).strip(), {"eligibility": "accept"}) or {}


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
      * context image   -> parameters.contextImages[0]      (kind "derived")
    A plain txt2img has no input image and returns (None, None).

    Context images (SCOPE_2026-09-26 E3): a Tsubaki.3 / Flash generation made from a
    reference carries its source ONLY in `contextImages` -- no top-level mediaId, no chat
    block (the owner's seven 2026-09-23 runs) -- and a site Edit-dialog instruction edit of
    a Tsubaki picture has the same shape, so the two cannot be told apart from parameters
    and both file as "derived", the img2img kind. With two or more context images the FIRST
    is the source; which one "counts" beyond that is a design call not made here."""
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
    ctx = params.get("contextImages")
    if isinstance(ctx, list) and ctx and ctx[0] and str(ctx[0]).strip():
        return (str(ctx[0]).strip(), "derived")
    return (None, None)


def task_media_index(session, task_id, media_id):
    """Which image of a task a given media_id IS -- the `mediaIndex` the publish mutation
    needs. Never guessed from a filename: a batchSize>1 task stores its individuals under
    outputs.batch[] and their ORDER is the index PixAI means.

    It is PixAI's OWN output number -- the RAW position in that array, counted with deleted
    members still occupying their slots, the same number `batch_position` reports and the
    same <n> the site's own from-PixAI-<taskId>-<n> download names use. Counting only the
    members PixAI still has (`_task_image_media`, which skips them, is the right enumeration
    for DOWNLOADING and the wrong one here) shifts every image after a deletion down one
    slot: on a batch whose first picture was deleted, publishing the third would send index
    1, which is the second picture's slot, and the wrong picture would go to the owner's
    public profile with nothing saying so.

    Read-only. Returns the int index, or None -- publish nothing -- when the task can't be
    read, when the batch does not list this image at all (a stale row, or the batch's
    combined preview picture), or when PixAI has already deleted this image: a member with a
    `deletedAt` is no longer one of the task's outputs, so it has no number to publish at.
    A task with no batch array (a single-image generation, an edit, an upscale) resolves
    from its own ordered outputs instead, where the lone image is index 0. The caller decides
    whether None is fatal (it is, for publishing: publishing the wrong image of a batch is
    not a recoverable mistake)."""
    if not task_id or not media_id:
        return None
    try:
        task = _task_reads.task_detail_gql(session, str(task_id))
    except PixAIError:
        return None
    if not task:
        return None
    outputs = task.get("outputs") or {}
    batch = outputs.get("batch")
    if isinstance(batch, list) and batch:
        # batch_position answers blank for BOTH "not one of this task's outputs" and "PixAI
        # deleted this one", and neither may be published -- so both land on None here.
        bi, _size = batch_position(batch, media_id)
        return int(bi) if bi != "" else None
    for i, (mid, _seed) in enumerate(_task_image_media(outputs)):
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
    listArtworks hands back on node.extra (../moonglade-internal/private/API_OPERATIONS.md). Entering is a
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
    Single attempt (gql_mutate) so a flaky network can never delete twice. A void
    mutation: success is the ABSENCE of an error, not the payload."""
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
    print("Account ID       : {}".format(me.get("id") or _pixai_client._client_of(session).user_id))
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
# token the tool already holds (see ../moonglade-internal/private/APP_OPERATIONS_FULL.md).
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

# OUR OWN KEEPALIVE (2026-09-29). The clock above assumed PixAI pings an idle
# subscription. It does not: every idle stretch in the logs since 2026-09-04 reads
# "connected and subscribed" followed, exactly 240s later, by "socket went silent",
# with the catch-up sweep then finding nothing missed -- a healthy, quiet account
# declared dead every four minutes, and the Control Panel read "Reconnecting ...
# treating the connection as dead" for the minute of backoff after each one. The
# protocol lets EITHER side ping, and the receiver must answer with a pong, so after
# this many seconds of quiet the client sends its own graphql-transport-ws `ping`;
# the server's `pong` is a frame like any other and resets the stale clock. A
# connection that answers nothing -- not even our ping -- still goes stale at
# _WS_STALE_TIMEOUT exactly as before. (The websockets library's own RFC 6455 pings
# are control frames recv() never returns, so they cannot reset this clock.)
_WS_HEARTBEAT = 60


async def _watch_events_async(auth_header, on_event, seconds):
    """Connect, handshake, subscribe to personalEvents, and dispatch each `next` frame's
    payload to on_event(dict). Replies to server pings, and after `_WS_HEARTBEAT` seconds
    of quiet sends a ping of its own (see that constant). Runs until `seconds` elapses
    (None = until cancelled). Read-only: sends only connection_init / subscribe / ping /
    pong / complete.

    Every frame off the wire -- a `next`, a `ping`, the `pong` to our ping, anything --
    resets a `_WS_STALE_TIMEOUT`-second clock. If that clock lapses, raises WatchStaleError
    instead of waiting forever on a socket that reports no error but has gone
    silent (see `_WS_STALE_TIMEOUT`'s comment for why that happens and how the
    number was picked). WatchStaleError is just another exception out of this
    coroutine, so any caller that already reconnects on failure -- `_watch_loop`
    in moonglade/gallery.py's outer while-True/backoff, and `run_watch` below's own
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
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _WS_STALE_TIMEOUT
            while True:
                # Wait for the next frame, but never past the staleness deadline, and never
                # longer than one heartbeat: a quiet heartbeat sends our ping and waits on.
                left = deadline - loop.time()
                wait = min(_WS_HEARTBEAT, max(left, 0))
                try:
                    # recv() is cancellation-safe in websockets' asyncio client: a timed-out
                    # wait loses no frame, the next recv() returns it.
                    raw = await asyncio.wait_for(ws.recv(), timeout=wait)
                except asyncio.TimeoutError:
                    if wait >= left:
                        # Converted to a WatchStaleError HERE, not left as a bare
                        # asyncio.TimeoutError, so it can never be mistaken for (or
                        # accidentally swallowed by) the outer bounded-run timeout
                        # below, which catches that same exception type for a
                        # completely different reason (the `seconds` run budget).
                        raise WatchStaleError(
                            "no frame from PixAI in {}s (not even a reply to our keepalive "
                            "ping) -- treating the connection as dead".format(_WS_STALE_TIMEOUT))
                    await ws.send(json.dumps({"type": "ping"}))
                    continue
                deadline = loop.time() + _WS_STALE_TIMEOUT
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
    out_dir = getattr(args, "out", _paths.DEFAULT_LIBRARY_DIR) or _paths.DEFAULT_LIBRARY_DIR
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
# Read-only: browsing contests never spends. See ../moonglade-internal/private/APP_OPERATIONS_FULL.md.
_CONTEST_PAGE_SIZE = 50
# The contest board's page CEILING and pace (SCOPE_2026-09-26 E4). list_contests stops at the
# board's own `totalPage`; this ceiling only bounds a board that keeps growing -- it was a bare
# 6, and the 2026-09-26 board already answered totalPage 7 at 50 a page (330 contests), so the
# oldest page silently fell off. Pages are read 0.35 s apart, the contest sweep's own pace
# (moonglade.contest_sync._CONTEST_SYNC_PAUSE): the board is a public read and CLAUDE.md asks for
# paced requests.
_CONTEST_MAX_PAGES = 20
_CONTEST_PAGE_PAUSE = 0.35


def _contest_title(t):
    """Contest title/description come as {en, zh, ja, ko, ...} (or occasionally a bare
    string). Prefer English, fall back to the first non-empty value."""
    if isinstance(t, dict):
        return t.get("en") or next((v for v in t.values() if v), "") or ""
    return t or ""


def _contest_rule(rule):
    """One contest rule, with every `*_ids` list turned into strings. A 19-digit id that
    arrives as a bare JSON number would be ROUNDED by the browser's JSON.parse above 2^53
    and link the wrong recipe or model; str() here keeps every digit (null entries dropped)."""
    out = dict(rule)
    for k, v in rule.items():
        if isinstance(k, str) and k.endswith("_ids") and isinstance(v, list):
            out[k] = [str(i) for i in v if i is not None]
    return out


def list_contests(session, active_only=False, max_pages=_CONTEST_MAX_PAGES, meta=None):
    """Return the PixAI contest board as normalized dicts, newest-first. `active_only`
    keeps just the currently-running ones (runtimeStatus=='running'). Pages through
    /v2/contest/list until the board's own `totalPage`, never past `max_pages`
    (_CONTEST_MAX_PAGES), pausing _CONTEST_PAGE_PAUSE between pages; when the ceiling rather
    than `totalPage` ends the walk, the log says so. Read-only, no spend.

    `meta`, when given, is an out-dict the caller reads afterwards (the return value stays a
    plain list): pages_read, total_page, total_count, limit (rows the walk could read) and
    `truncated` -- True only when the ceiling, not the board's own `totalPage`, ended it."""
    out = []
    page = 1
    while True:
        if page > 1:
            time.sleep(_CONTEST_PAGE_PAUSE)
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
                #   rules  -- [{type: 'required_model_ids', model_ids: [...]} | {type: 'required_lora_ids', lora_ids: [...]} | {type: 'required_recipe_ids', recipe_ids: [...]}]; [] = no restriction
                #   tack_name -- the tag an entry must carry (PixAI calls a tag a "tack")
                #   desc_url / result_url -- the contest's own rules + results documents,
                #     both frequently absent (null upstream -> "" here)
                "rules": [_contest_rule(x) for x in (r.get("rules") or [])
                          if isinstance(x, dict)],
                "tack_name": r.get("proposedTackName") or "",
                "desc_url": r.get("descUrl") or "",
                "result_url": r.get("resultUrl") or "",
                # Settlement (L3, PROBE 2026-09-29): `rewardStatus` reads "distributed" once
                # the prizes have been paid out, which is the signal the win check uses to stop
                # re-reading a contest early. Absent upstream -> "" (unknown, never a guess).
                "reward_status": str(r.get("rewardStatus") or "").lower(),
                "reward_distributed_at": r.get("rewardDistributedAt") or "",
            })
        total_page = int(d.get("totalPage") or 1)
        total_count = int(d.get("totalCount") or 0)
        if page >= total_page:
            if meta is not None:
                meta.update(pages_read=page, total_page=total_page, total_count=total_count,
                            limit=page * _CONTEST_PAGE_SIZE, truncated=False)
            break
        if page >= max_pages:
            if meta is not None:
                meta.update(pages_read=page, total_page=total_page, total_count=total_count,
                            limit=page * _CONTEST_PAGE_SIZE, truncated=True)
            from moonglade import logs as moonglade_logging
            moonglade_logging.get_logger().warning(
                "contest board: stopped at the %d-page ceiling; the board reports %d pages, "
                "so its oldest %d page(s) were not read", max_pages, total_page,
                total_page - page)
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
    guessed at by name. Nested envelopes (the echoed `contest{}` object) are dropped, except
    its `entry`: the placement (kept as one small dict, see below)."""
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
        # L3 (PROBE 2026-09-29): the echoed `contest{}` block is NOT noise on these rows -- its
        # nested `entry` carries the placement. `contest.entry = {rank, prizeAmount, source,
        # submittedAt}`: `rank` is the PRIZE TIER (1/2/3, shared by every winner in that tier,
        # null on a non-winner's entry), `prizeAmount` what that tier paid, `source` "manual"
        # for a hand-picked winner and "tack" for an ordinary entry. Dropping it (the old
        # scalars-only rule) is what made the app show list positions 1..65 and a prize of 0.
        # Kept ADDITIVELY, and only when upstream sent it, so a row without the block maps
        # exactly as it always did. `rank` stays an int or None -- a numeric string is NOT
        # coerced, because "is this an integer rank" is the win check's whole question.
        blk = r.get("contest")
        ent = blk.get("entry") if isinstance(blk, dict) else None
        if not isinstance(ent, dict):
            ent = r.get("entry") if isinstance(r.get("entry"), dict) else None
        if isinstance(ent, dict):
            rank = ent.get("rank")
            prize = ent.get("prizeAmount")
            flat["entry"] = {
                "rank": rank if (isinstance(rank, int) and not isinstance(rank, bool)) else None,
                "prizeAmount": prize if (isinstance(prize, (int, float))
                                         and not isinstance(prize, bool)) else 0,
                "source": ent.get("source") if isinstance(ent.get("source"), str) else "",
                "submittedAt": (ent.get("submittedAt")
                                if isinstance(ent.get("submittedAt"), str) else ""),
            }
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
    "not decided yet", never "call failed". ONE unpaged list; each row is a winning artwork
    (`id` is the artwork id, `authorId` its author) and its `entry` is the placement:
    `entry.rank` is the prize TIER (1/2/3, shared by every winner in that tier) and
    `entry.prizeAmount` what the tier paid (PROBE 2026-09-29; see _contest_rows). Read-only,
    a GET and nothing else, no spend."""
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
    exactly like submit_generation / submit_fixer / delete_task / claim_reward, and it
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
    positionally and the suite patches it here (dev/tests/conftest.py's `_no_live_card_network`
    is what makes the /v2 API offline by default)."""
    return _pixai_client._client_of(session).rest_get(path, params=params, timeout=timeout)


def _rest_post(session, path, body, timeout=60):
    """POST JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx.

    THIN DELEGATE onto `PixAIClient.rest_post`, which carries the no-retry-loop rule that
    keeps `submit_fixer` and `claim_reward` single-attempt."""
    return _pixai_client._client_of(session).rest_post(path, body, timeout=timeout)


def _rest_patch(session, path, body, timeout=60):
    """PATCH JSON to a /v2 oRPC REST route. THIN DELEGATE onto `PixAIClient.rest_patch`
    (single attempt). Blocked in tests by conftest."""
    return _pixai_client._client_of(session).rest_patch(path, body, timeout=timeout)


def _rest_put(session, path, body, timeout=60):
    """PUT JSON to a /v2 oRPC REST route. THIN DELEGATE onto `PixAIClient.rest_put`
    (single attempt). Blocked in tests by conftest, like _rest_get / _rest_post."""
    return _pixai_client._client_of(session).rest_put(path, body, timeout=timeout)


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
        # Every expiry date the type holds, with how many expire then (Session Y, #69): the
        # credits chip's "N <kind> expire <date>" lines. A dateless or unreadable entry is
        # dropped -- it can never expire soon.
        "expiry_counts": _expiry_counts(raw.get("expiryCounts")),
    }


def _expiry_counts(rows):
    out = []
    for e in rows or []:
        if not isinstance(e, dict) or not e.get("expiresAt"):
            continue
        try:
            n = int(e.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append({"expires_at": str(e["expiresAt"]), "count": n})
    return out


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
    created_at}. `action` is one of the four actions PixAI's contract allows: "consumed",
    "refunded", "expired" or "revoked". PixAI hands a card back (a NEW record, same
    kaisuukenId, action=refunded) when the task it was attached to failed or was refused; a
    single card can cycle consumed->refunded->consumed again across different tasks, so
    record_id is not 1:1 with "one use". "expired" is a card that ran out unused and "revoked"
    one PixAI took back: neither was attached to a task, so those rows come with no task id
    (task_id "") and no credit cost (None). The first expiry row on the owner's log is dated
    2026-09-18 (PROBE_2026-10-02_site, #68); cards that ran out before then left no row.
    `credit_cost` is what the redemption would have cost in credits had no card covered it --
    useful for a "cards have saved you N credits" total, never an actual charge (the whole
    point of the card is that it wasn't charged).

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

    Each template counts all four actions the log carries -- consumed, refunded, expired and
    revoked (#68) -- so a card type that only ever ran out still has its row, with its expiries
    counted rather than dropped.

    Caveat: the log's first expiry row is dated 2026-09-18, so a card type that expired
    untouched before then left no trace here (verified 2026-08-02); the roster is a lower
    bound on "every card type ever granted", not an exact one.

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
                "consumed": 0, "refunded": 0, "expired": 0, "revoked": 0,
                "first_seen": row["created_at"], "last_seen": row["created_at"]})
            if row["action"] in ("consumed", "refunded", "expired", "revoked"):
                entry[row["action"]] += 1
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


def list_credit_log(session, last=50, before=None):
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
    past. There is no type filter: the `me` connection takes no such argument. Read-only;
    fails soft on error, matching every other reader in this module."""
    try:
        variables = {"last": int(last)}
        if before:
            variables["before"] = str(before)
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


def match_kaisuuken(session, parameters, enrich=False, raise_on_error=False, *,
                    training_base_model_id=""):
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
    default (False) keeps the original single-call behavior for every existing caller.

    `training_base_model_id` switches the body to PixAI's TRAINING check (the site's
    useKaisuukenMatch, owner ruling 4, 2026-09-26): {type: "training-task", baseModelId:
    <the base VERSION id>, version: 2}, with no `parameters` at all. The answer is read with
    exactly the same rules. match_training_kaisuuken is the named way in."""
    training_base = str(training_base_model_id or "").strip()
    if not parameters and not training_base:
        return None
    if training_base:
        body = {"type": "training-task", "baseModelId": training_base,
                "version": _KAISUUKEN_CHECK_VERSION}
    else:
        body = {"type": "generation-task", "parameters": parameters,
                "version": _KAISUUKEN_CHECK_VERSION}
    try:
        # `version: 2` is load-bearing (issue #15, live-verified 2026-08-16). Without it PixAI
        # runs its v1 matcher, which knows only single-ticket cards and answers `matches: []`
        # for any i2vPro duration >= 10 -- so every >5s video went out card-less at full price
        # for as long as this app existed. v2 (the site's own useKaisuukenMatch shape) returns
        # the multi-ticket match plus `consumeAmount` = tickets this job COSTS. NOTE the server
        # does NOT filter by balance: a 15s job comes back matched even when held < needed, so
        # coverage is decided HERE (see `covered` below), the one place every caller reads it.
        data = _rest_post(session, "/kaisuuken/check", body) or {}
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
    want = training_base or _target_model_id(parameters)
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
    in moonglade/gallery.py). Mirror that same gate here (B18 residual) so the CLI refuses
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
        out = getattr(args, "out", "") or _paths.DEFAULT_LIBRARY_DIR
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
            from moonglade.telemetry import telem_bump
            telem_bump("claims", claimed)
        except Exception:
            pass
    return {"claimed": claimed}


# The spend-time free-card check came back 401: PixAI no longer accepts the sign-in this
# create rides, so the words depend on WHICH sign-in that was (_session_for_create: the
# website session when Mirror to PixAI is on, the API key otherwise). Both end with the raw
# error in parentheses, like the "Lost to the Void" message beside them.
_SIGNIN_REFUSED_MIRROR = (
    "PixAI no longer accepts this app's website sign-in, so nothing was submitted and "
    "nothing was spent. Sign in to pixai.art, click your Connect from PixAI bookmark on "
    "that tab (it is on the Mirror to PixAI tile in the Control Panel), and try again. "
    "({})")
_SIGNIN_REFUSED_API_KEY = (
    "PixAI no longer accepts this app's API key, so nothing was submitted and nothing was "
    "spent. Make a new key on PixAI and put it in config.json as PIXAI_API_KEY (the Setup "
    "page in the wiki shows where), then try again. ({})")


def _is_signin_refusal(err):
    """True when `err` is a REST answer of HTTP 401 (PixAIRestError.status). Read off the
    status the transport already carries, never by matching the message text."""
    return isinstance(err, PixAIRestError) and err.status == 401


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
    guessing with the user's money (audit: `fail-open`, 2026-07-21).

    An Unlimited Mode request (params carrying `lane`, from ANY road -- a CLI --params-json
    or a banked --dump-params shape included) never touches a card: no check runs and no id
    is attached, and a card asked for beside the lane is refused rather than dropped
    (SCOPE_2026-09-26_unlimited-mode §8.3)."""
    explicit = (getattr(args, "kaisuuken_id", "") or "").strip()
    if is_lane_request(params):
        if explicit or params.get("kaisuukenId"):
            raise PixAIError(_UNLIMITED_NO_CARD)
        print("  Unlimited Mode: no free card is checked or attached.")
        return ""
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
    session = _mirror._session_for_create(session)
    best = None
    check_err = None
    for attempt in range(2):
        try:
            best = match_kaisuuken(session, params, enrich=True, raise_on_error=True)
            check_err = None
            break
        except (PixAIError, ValueError) as e:
            check_err = e
            # A 401 is PixAI refusing the sign-in itself: waiting and asking again cannot
            # change that answer, so it is not retried (no second call, no sleep). The status
            # rides on the PixAIRestError that _rest_error built, through match_kaisuuken's
            # re-raise, so it is read from there and never from the message text.
            if _is_signin_refusal(e):
                break
            if attempt == 0:
                time.sleep(1.5)
    if check_err is not None:
        if _is_signin_refusal(check_err):
            raise PixAIError((_SIGNIN_REFUSED_MIRROR if _mirror.mirror_enabled()
                              else _SIGNIN_REFUSED_API_KEY).format(check_err))
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
            cost = _pricing.price_task(session, params)
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
    if is_lane_request(params):
        # A lane request never touches a card, at quote or at submit (SCOPE_2026-09-26_
        # unlimited-mode §2) -- so no /v2/kaisuuken/check here either.
        print("Unlimited Mode request: no free card is checked or attached. PixAI runs it "
              "free on an active Unlimited Mode, or refuses it.")
        return
    if getattr(args, "no_card", False):
        try:
            session = _make_session(getattr(args, "token", None))
            price = _pricing.price_task(session, params)
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
        price = _pricing.price_task(session, params)
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
    generation cost. Read-only. Pass --credit-log-before <cursor> to page further into the
    past."""
    session = _make_session(getattr(args, "token", None))
    page = list_credit_log(session, last=int(getattr(args, "credit_log_count", 0) or 30),
                            before=getattr(args, "credit_log_before", "") or None)
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


# When the archive-only flags were last rewritten: the Broken files list's LOST line says "gone
# from your PixAI history as of <date>", and this is that date (Session W, W5a).
RECONCILE_STAMP = "reconcile_stamp.json"


# The task statuses that end with no picture at all: nothing to back up, ever.
_NO_PICTURE_STATUSES = frozenset({"failed", "cancelled", "canceled", "rejected", "error"})


def feed_counts(nodes, have_task_ids):
    """What a full walk of the live feed says about backing it up (the header's Backed up pill,
    moonglade.gallery.backup_coverage). `nodes` are the feed's task summaries, `have_task_ids`
    the catalog's task ids. Returns {live, no_picture, in_progress, missing}:
      no_picture   a failed or cancelled generation -- PixAI made no picture, so there is
                   nothing to fetch and nothing will ever fix it; the pill does not count it
      in_progress  still queued or running (counted once it finishes)
      missing      finished with a picture, and not in the catalog: what Sync now fetches."""
    have = set(have_task_ids or ())
    live = no_picture = in_progress = missing = 0
    for node in nodes or ():
        tid = str(node.get("id") or "")
        if not tid:
            continue
        live += 1
        st = str(node.get("status") or "").strip().lower()
        if st in _NO_PICTURE_STATUSES:
            no_picture += 1
        elif st and st != "completed":
            in_progress += 1
        elif not media_ids_for(node):
            no_picture += 1                  # finished, but PixAI lists no picture for it
        elif tid not in have:
            missing += 1
    return {"live": live, "no_picture": no_picture, "in_progress": in_progress,
            "missing": missing}


def read_reconcile_stamp(out):
    """reconcile_stamp.json as a dict, or {} when there is none or it will not read."""
    try:
        doc = json.loads(_paths.records_path(out, RECONCILE_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _stamp_reconcile(out, flagged, cleared, counts=None):
    """Write reconcile_stamp.json among the library's records, atomically. Advisory, like the
    reconcile itself: a disk that refuses it costs the date on a LOST line, nothing more.
    `counts` (feed_counts) rides along for the Backed up pill."""
    doc = {"reconciled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "flagged": flagged, "cleared": cleared}
    for k, v in (counts or {}).items():
        doc[k] = int(v)
    dest = _paths.records_path(out, RECONCILE_STAMP)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        _atomic_replace(tmp, dest)
    except OSError:
        pass


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
    # `complete` is set ONLY by a page saying there is nothing older. Every row missing from
    # `live` is flagged below, so a walk that stopped anywhere else (no page in the answer, an
    # empty page while PixAI says older ones exist) must flag nothing: a partial `live` would
    # mark tasks that still exist on PixAI as deleted, and the gallery offers those for a
    # bulk local Delete.
    live, before, page, complete = set(), None, 0, False
    nodes = []                         # every summary, for feed_counts (the Backed up pill)
    while True:
        conn = find_connection(gql(session, page_variables(
            getattr(args, "page_size", 250) or 250,
            _pixai_client._client_of(session).user_id, before)))
        if not conn:
            break
        edges = conn.get("edges") or []
        pi = conn.get("pageInfo") or {}
        if not edges:
            complete = not pi.get("hasPreviousPage")
            break
        for e in edges:
            node = e.get("node") or {}
            tid = node.get("id")
            if tid:
                live.add(str(tid))
                nodes.append(node)
        page += 1
        vlog("reconcile: page {}, {} live tasks so far".format(page, len(live)))
        if not pi.get("hasPreviousPage"):
            complete = True
            break
        before = pi.get("startCursor")
    if not complete:
        raise PixAIError("Live feed ended early -- nothing was flagged.")
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
    counts = feed_counts(nodes, {(r.get("task_id") or "").strip() for r in rows})
    _stamp_reconcile(out, flagged, cleared, counts)
    print("Flagged {:,} row(s) as deleted-on-PixAI; cleared {:,} stale flag(s).".format(
        flagged, cleared))
    print("Review in the gallery: Source -> 'Deleted on PixAI', then bulk Delete (local).")
    return dict(counts, live=len(live), flagged=flagged, cleared=cleared)


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
    _records = _norm(_paths.LIBRARY_APP_DIRNAME)
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
        elif top == _records:
            pass                       # the app's own folder (_moonglade/), never pictures
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
        from moonglade import similar as ps
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
        from moonglade import similar as ps
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


def _one_line(text, width):
    t = " ".join(str(text or "").split())
    return t if len(t) <= width else t[:width - 1].rstrip() + "\u2026"


def run_search(args):
    """--search / --export-csv: the gallery's own search, from the command line. Reads
    catalog.db only -- no network, nothing written except the CSV a caller names. The query
    goes through the SAME parser the search box uses (moonglade.gallery.query_catalog)."""
    try:     # a prompt with characters the console cannot show must not stop the listing
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    out = Path(args.out)
    db_path = _ensure_db(out)
    q = (getattr(args, "search", None) or "").strip()
    if q:
        rows, _ = query_catalog(db_path, q=q, page=1, page_size=None, sort="newest")
    else:
        rows = load_catalog(db_path)
    csv_path = getattr(args, "export_csv", "")
    if csv_path:
        # newline="" so the file's line endings are the CSV writer's own, as the download's are
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(catalog_csv_text(rows))
        print("Wrote {} row(s) to {}".format(len(rows), csv_path))
        if not q:
            return
    limit = int(getattr(args, "limit", 50) or 0)
    shown = rows[:limit] if limit > 0 else rows
    if getattr(args, "search_json", False):
        print(json.dumps([{"media_id": r.get("media_id", ""), "created_at": r.get("created_at", ""),
                           "model": r.get("model_name", ""), "rating": r.get("rating", ""),
                           "prompt": r.get("prompt_full") or r.get("prompt_preview") or ""}
                          for r in shown], ensure_ascii=False, indent=2))
        return
    for r in shown:
        print("{}  {}  {}  {}  {}".format(
            r.get("media_id", ""), str(r.get("created_at", ""))[:10],
            _one_line(r.get("model_name", ""), 24) or "-",
            ("%s*" % r["rating"]) if r.get("rating") else "-",
            _one_line(r.get("prompt_full") or r.get("prompt_preview"), 70)))
    if len(shown) < len(rows):
        print("... {} of {} match(es) shown; --limit 0 for all, --export-csv PATH for a file".format(
            len(shown), len(rows)))
    else:
        print("{} match(es)".format(len(rows)))


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
    """Fill catalog rows from the task detail read + the model version read: the core
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

    rows = load_catalog(db_path)
    # As loaded, so a checkpoint save keeps a rating or collection set while this runs.
    snapshot = {r["media_id"]: dict(r) for r in rows if r.get("media_id")}
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
        task_data = _task_reads.task_detail_gql(session, tid)
        fm = extract_full_meta(task_data)
        if fm.get("model_id"):
            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
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
            save_catalog_over_snapshot(db_path, pending, snapshot, blank_keeps=False)
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
        task_data = _task_reads.task_detail_gql(session, tid)
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
    dHash -- see its docstring in moonglade/gallery.py) for every catalog row missing
    one. IMAGE ROWS ONLY: is_video='1' rows are skipped by design -- the near-duplicate
    tier this feeds (near_duplicate_groups(), moonglade/gallery.py) is scoped to images,
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
    from moonglade.gallery import load_catalog, save_catalog, compute_dhash, find_image_file

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
            from moonglade.telemetry import telem_flag
            telem_flag("old_piece_backed_up", out_dir=out_dir)
    except Exception:
        pass


# THE WALK-END MARKER (owner report, 2026-09-07). "This should have picked up where it
# left off and continued pulling 37k images." One fact, per library: has any pass over
# this history ever reached the oldest page? Everything --update's early stop assumes
# rests on it, and until 2026-09-07 nothing recorded it, so a first backup stopped
# part-way left two known pages at the newest end and every later Sync read those two as
# "the whole library is already here".
#
# It lives in the library's own telemetry.json -- the same store `first_sync_done` uses --
# and NOT in config.json: it is a fact about this backup folder, not a setting of the app,
# and two out_dirs must never share it. Fail-soft both ways, and the READ fails to False on
# purpose: an unreadable marker means "keep walking", which costs pages, where the opposite
# default means silently declaring an unfinished library finished.
WALK_END_FLAG = "walk_reached_end"


def walk_end_reached(out_dir):
    """True once some pass over this library has seen pageInfo.hasPreviousPage == False."""
    try:
        from moonglade import gallery as _mg
        return bool(_telemetry.load_telemetry(out_dir)["flags"].get(WALK_END_FLAG))
    except Exception:
        return False


def mark_walk_end_reached(out_dir):
    """Record that a pass walked all the way to the oldest page. Idempotent."""
    try:
        from moonglade import gallery as _mg
        _telemetry.telem_flag(WALK_END_FLAG, out_dir=out_dir)
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
    raw_path = _paths.records_path(out, "raw_tasks.jsonl")
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
            # reconcile_catalog_with_disk's strict matcher (moonglade/gallery.py) finds
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
    # THE RESUME GATE (owner report, 2026-09-07). This REFINES the incremental-stop ruling
    # rather than reversing it: a run of already-on-disk pages still ends the walk, but only
    # once this library has PROVEN where the end of history is (walk_end_reached above).
    # Without that proof the walk pages to the true end exactly as a full re-walk does --
    # still skipping every file already on disk, so it costs page listings, not downloads --
    # which is what makes a first backup that was stopped part-way finish on the next Sync
    # instead of stopping after the two pages it happened to have.
    end_known = walk_end_reached(out)
    reached_end = False      # this run saw pageInfo.hasPreviousPage == False
    stopped_early = False    # this run took the consecutive-known-pages stop

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
                args.page_size, _pixai_client._client_of(session).user_id, before)))
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
                            task_data = _task_reads.task_detail_gql(session, tid)
                            fm = extract_full_meta(task_data)
                            if fm.get("model_id"):
                                fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
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
                    save_catalog_over_snapshot(db_path, page_rows, known)
                seen += len(edges)
                if args.max and seen >= args.max:
                    print("Reached --max limit.")
                    break
                if update_mode:
                    if page_new == 0:
                        consecutive_known_pages += 1
                        # `end_known`: the resume gate. See where it is set, above.
                        if end_known and consecutive_known_pages >= update_grace:
                            print("\n--update: {} consecutive pages already on disk; "
                                  "stopping (older items are already downloaded)."
                                  .format(consecutive_known_pages))
                            stopped_early = True
                            break
                    else:
                        consecutive_known_pages = 0
                raw_f.flush()
                pi = conn.get("pageInfo", {})
                if not pi.get("hasPreviousPage"):
                    reached_end = True
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
                        task_data = _task_reads.task_detail_gql(session, tid)
                        fm = extract_full_meta(task_data)
                        if fm.get("model_id"):
                            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
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

            # Upsert this page's rows so progress is durable even on interrupt. Each row
            # is merged over the row the catalog holds NOW, not over `known` (read when
            # the run started): a re-pull never blanks local curation, and a rating,
            # collection or delete made in the gallery during the run is not undone.
            if page_rows:
                save_catalog_over_snapshot(db_path, page_rows, known)

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
            # Gated on `end_known` since 2026-09-07 -- "already on disk" only implies
            # "already downloaded" for a library whose tail was reached at least once.
            if update_mode:
                if page_new == 0:
                    consecutive_known_pages += 1
                    if end_known and consecutive_known_pages >= update_grace:
                        print("\n--update: {} consecutive pages already on disk; "
                              "stopping (older items are already downloaded)."
                              .format(consecutive_known_pages))
                        stopped_early = True
                        break
                else:
                    consecutive_known_pages = 0

            pi = conn.get("pageInfo", {})
            if not pi.get("hasPreviousPage"):
                reached_end = True
                break
            before = pi.get("startCursor")
            time.sleep(args.delay)

    finally:
        raw_f.close()

    if reached_end:
        # ONLY a page that actually reported "no previous page" arms the marker. A --max
        # cut-off, a --update early stop, an empty/absent connection and a run killed
        # mid-page all leave it exactly as it was -- which is the whole point: the marker
        # is proof the tail was seen, not a record that a walk happened.
        mark_walk_end_reached(out)
        end_known = True

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
    # How the walk ENDED, alongside what it moved -- the counters were already the return
    # value (D-4), and --sync's closing line is the one caller that has to tell "walked to
    # the end" from "caught up" apart (2026-09-07). Extra keys only; dl["ok"]/["skip"]/
    # ["missing"]/["fail"] mean exactly what they meant.
    dl["pages"] = page
    dl["reached_end"] = reached_end
    dl["stopped_early"] = stopped_early
    dl["end_known"] = end_known
    return dl


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_rebuild_thumbs(args):
    """--rebuild-thumbs: one uniform thumbnail pass over the whole catalog.
    Images are re-rendered from their originals at today's size/quality settings and
    REPLACED IN PLACE -- each one rendered to a temp file beside its destination and
    os.replace()d over the old one (make_thumbnail), so the gallery never goes blank
    mid-run and an interruption can never leave a truncated .jpg sitting at a real
    thumbnail's name for the exists-check to mistake for a finished one. This is what
    kills years of quality drift. Poster-less videos get a local ffmpeg frame extract,
    and thumbs whose media left the catalog are swept."""
    out = Path(args.out)
    db_path = _ensure_db(out)
    from moonglade.gallery import build_thumbnails, load_catalog
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
    """CLI: remove one gallery web-login account by username, and its per-login folder in the
    library (S10: a removed login's preferences, presets and snippets go with it)."""
    username = args.remove_web_user
    if remove_web_user(username):
        remove_login_files(getattr(args, "out", None), username)
        print("Removed web-login account '{}'.".format(username))
    else:
        print("No web-login account named '{}'.".format(username))


def remove_login_files(out_dir, username):
    """Delete `username`'s per-login folder (moonglade.paths.account_dir) in the library
    `out_dir`, once the login itself is gone. Best effort: True when it was removed."""
    if not out_dir or not str(username or "").strip():
        return False
    import shutil
    folder = _paths.account_dir(out_dir, username)
    try:
        if folder.is_dir():
            shutil.rmtree(folder)
            return True
    except OSError:
        pass
    return False


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
    # prog: the usage line names the command as it is typed (3.20), whether it came in by
    # `python -m moonglade` or as the code folder, `python "<app folder>\moonglade"`.
    ap = argparse.ArgumentParser(prog="python -m moonglade",
                                 description="Back up your own PixAI gallery.")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    # --help is grouped by what a command is for. The grouping is presentation only: every flag
    # keeps its name, its default and its meaning.
    g_backup = ap.add_argument_group("Backup", "pull your PixAI history down and keep it current")
    g_library = ap.add_argument_group("Library", "work on the local library and its catalog")
    g_create = ap.add_argument_group("Create", "make a picture, a video or an edit (a preview "
                                     "until --confirm); the generation options live here too")
    g_account = ap.add_argument_group("Account", "read-only looks at your PixAI account, "
                                      "rewards, and the gallery's web logins")
    g_maint = ap.add_argument_group("Maintenance", "repair and refill what the catalog holds")
    g_search = ap.add_argument_group("Search", "search the local catalog (no network)")
    g_maint.add_argument("--rebuild-thumbs", action="store_true",
                    help="regenerate EVERY image thumbnail at the current size/quality "
                         "settings (fixes quality drift across eras), extract posters for "
                         "poster-less videos via ffmpeg, and sweep orphaned thumbs. "
                         "Overwrites in place -- the gallery never goes blank.")
    g_backup.add_argument("--sync", action="store_true",
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
    # default=None: the library comes from settings.json (the Control Panel's library folder)
    # unless this run names one -- moonglade.setup.prepare() resolves it (S8).
    ap.add_argument("--out", default=None,
                    help="library folder for this run (default: the library folder set in "
                         "the Control Panel, or pixai_backup beside the app)")
    g_backup.add_argument("--page-size", type=int, default=250,
                    help="tasks per API page (default 250; fewer round-trips. Keep it at 2,000 or below)")
    g_backup.add_argument("--workers", type=int, default=4,
                    help="parallel download workers (default 4). 1 = serial/polite. "
                         "Higher saturates bandwidth on bulk first-time pulls; ignored for "
                         "--collect-only.")
    g_backup.add_argument("--max", type=int, default=0,
                    help="stop after N tasks (0=all); with --backfill-phash, caps the number "
                         "of rows that run processes instead")
    g_backup.add_argument("--update", action="store_true",
                    help="incremental follow-up run: stop paging once a run of pages is "
                         "already fully on disk (newest-first, so older items are already "
                         "downloaded). Much faster than re-walking the whole history. The "
                         "early stop waits until one pass has reached the end of your "
                         "history, so an interrupted first backup resumes to the end.")
    g_backup.add_argument("--update-grace", type=int, default=2,
                    help="with --update, number of consecutive all-on-disk pages before "
                         "stopping (default 2; raise if your history has gaps). Ignored "
                         "until this library's walk has reached the end of history once.")
    g_backup.add_argument("--accurate-count", action="store_true",
                    help="walk the whole API to count library size for the progress bar "
                         "(slow). Default uses the catalog size as a fast estimate.")
    # default is the _DefaultDelay sentinel, not a bare 0.4, so run_download can tell a typed
    # `--delay 0.4` from an untouched default. See _DefaultDelay for why a comparison cannot.
    g_backup.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help="seconds to wait between API requests (default: 0.4). Passing it "
                         "EXPLICITLY also paces the parallel download stage, at one image "
                         "per --delay across the whole pool; left at its default, downloads "
                         "run at full --workers speed as they always have")
    g_backup.add_argument("--probe", action="store_true",
                    help="show first page + auto-detect the full-res variant, then exit")
    g_backup.add_argument("--count", action="store_true",
                    help="tally total tasks + images via the API (no downloads), then exit")
    g_backup.add_argument("--count-page-size", type=int, default=COUNT_PAGE_SIZE,
                    help="page size used by --count (bigger = fewer requests; default "
                         "2000, because PixAI fails a 5000-row page now and then)")
    g_library.add_argument("--catalog-stats", action="store_true",
                    help="summarize the existing catalog.db (counts only), then exit")
    g_backup.add_argument("--collect-only", action="store_true",
                    help="scan and catalog images without downloading files")
    g_backup.add_argument("--name-length", type=int, default=60,
                    help="max characters of the prompt used in filenames (default 60)")
    g_backup.add_argument("--name-sep", default="_", choices=["_", "-"],
                    help="word separator in filenames (default _)")
    g_backup.add_argument("--convert", default=None, choices=["png", "jpeg", "jpg"],
                    help="convert each downloaded webp to png or jpeg (needs Pillow). "
                         "Replaces the .webp unless --keep-webp is set.")
    g_backup.add_argument("--jpeg-quality", type=int, default=92,
                    help="JPEG quality 1-100 when --convert jpeg (default 92)")
    g_backup.add_argument("--jpeg-bg", default="white", choices=["white", "black"],
                    help="background to flatten transparency onto for JPEG")
    g_backup.add_argument("--keep-webp", action="store_true",
                    help="keep the original .webp after converting")
    g_backup.add_argument("--convert-existing", action="store_true",
                    help="convert all already-downloaded .webp files to --convert format "
                         "(default png). No token needed. Supports --dry-run and --keep-webp.")
    g_library.add_argument("--organize", action="store_true",
                    help="normalize the WHOLE backup into YYYY-MM/ month folders with "
                         "descriptive filenames (no batch subfolders); writes a reversible "
                         "move-manifest. Idempotent + dry-runnable. Then exit")
    g_library.add_argument("--undo-organize", action="store_true",
                    help="revert the last --organize run using organize_manifest.csv "
                         "(move files back to their old paths), then exit")
    g_library.add_argument("--embed-metadata", action="store_true",
                    help="with --organize, embed prompt/IDs/date into PNG/JPEG files "
                         "(off by default; useful when pulling images into other apps)")
    g_library.add_argument("--dry-run", action="store_true",
                    help="with --organize / --undo-organize, show the "
                         "plan without moving anything")
    # ON BY DEFAULT since 2026-07-25. This is a backup tool whose point is the catalog, and
    # full metadata was the one thing you only got by asking: a plain run or --update left
    # rows with no prompt, no seed and no model, and the gap was invisible until something
    # needed it. (Measured on the owner's own library: a stats screen reporting "35,133
    # entries, all downloaded" over rows that could not say which model made them.) --sync
    # has always implied it; now every pull does, and the flag stays accepted so existing
    # scripts, docs and the Panel's whitelisted argv keep working unchanged.
    g_backup.add_argument("--full-meta", dest="full_meta", action="store_true", default=True,
                    help="(now the DEFAULT) fetch full prompt, seed, steps, sampler, CFG and "
                         "model name for each task via a second API call. One extra call per "
                         "unique task -- a batch's images share one call. Kept as an explicit "
                         "flag so existing commands and scripts still work.")
    g_backup.add_argument("--no-full-meta", dest="full_meta", action="store_false",
                    help="skip the per-task metadata call: faster pull, but the catalog rows "
                         "it creates carry no prompt, seed or model until a later "
                         "--backfill-full-meta fills them in. On a first backup of a large "
                         "history this is the quicker route -- the pull's metadata fetch is "
                         "serial, while --backfill-full-meta --workers N is parallel.")
    g_maint.add_argument("--backfill-meta", action="store_true",
                    help="fill in missing url/width/height in catalog.db via resolve_media "
                         "for rows that lack them, then exit")
    g_maint.add_argument("--backfill-full-meta", action="store_true",
                    help="fill in prompt_full/seed/model/etc in catalog.db via getTaskById "
                         "for rows that lack them; also backfills url/width/height as a bonus, then exit")
    g_backup.add_argument("--with-loras", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "no LoRA data yet (populates the loras column for older images; long run)")
    g_backup.add_argument("--with-credit", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "no recorded credit cost yet (recovers the paid_credit column for older "
                         "generations from the task record; long run)")
    g_backup.add_argument("--with-surface", action="store_true",
                    help="with --backfill-full-meta, ALSO re-fetch rows that have full meta but "
                         "none of the issue-#18 surface columns yet (inference profile, quality "
                         "tag, render time, backend, moderation, retry count...); the only way a "
                         "pre-#18 generation gains them. Long run on a big historical catalog.")
    g_maint.add_argument("--backfill-lineage", action="store_true",
                    help="fill in source_media_id/derive_kind (which image an edit/upscale/"
                         "video was made FROM) for rows that predate lineage tracking, via "
                         "getTaskById; powers Image Details' LINEAGE panel. Idempotent -- a "
                         "confirmed original is remembered and never re-fetched. Then exit.")
    g_maint.add_argument("--backfill-phash", action="store_true",
                    help="compute a perceptual difference-hash (dHash) for every image catalog "
                         "row that lacks one, powering the near-duplicate ('upscaled or "
                         "recompressed copy') tier of GET /api/duplicates. Local Pillow work, no "
                         "network call -- --workers parallelizes it, --max caps how many rows "
                         "this run processes. Videos are skipped. Then exit.")
    g_backup.add_argument("--sync-artworks", action="store_true",
                    help="fetch your published-artwork metadata (title, NSFW flag, likes, "
                         "comments, views, aes score, tags) and merge it "
                         "onto matching catalog rows by media_id, then exit")
    g_backup.add_argument("--with-videos", action="store_true",
                    help="with --sync-artworks, also download animated-artwork video files "
                         "(videoMediaId) into a videos/ folder")
    g_backup.add_argument("--no-views", action="store_true",
                    help="with --sync-artworks, skip the view-count sweep. Reading a view "
                         "count registers a view on PixAI's side (one per work, per sweep), "
                         "so this is the opt-out for a run where you want the metadata "
                         "refreshed without touching your own view numbers")
    g_backup.add_argument("--views-only", dest="views_only", action="store_true",
                    help="with --sync-artworks, read ONLY the view counts and skip the "
                         "artwork listing. The counts join your catalog by artwork id, so "
                         "they do not need the listing walked again. This is what the "
                         "Control Panel's weekly \"View counts\" job runs")
    g_backup.add_argument("--sync-videos", action="store_true",
                    help="back up your image-to-video generations: find i2v tasks, download "
                         "each mp4 into videos/, and catalog them (is_video), then exit. This is "
                         "the video-side complement of --sync, which skips video tasks: run it to "
                         "capture videos made on the PixAI website (app-made videos are already "
                         "caught when generated). Full-history scan, so it's a separate pass.")
    g_backup.add_argument("--faststart-videos", dest="faststart_videos", action="store_true",
                    help="losslessly move every video's moov atom to the front (ffmpeg "
                         "-c copy +faststart) so iOS/Safari can play them over HTTP, then exit")
    g_account.add_argument("--account", action="store_true",
                    help="show a read-only account dashboard (credit balance, membership, "
                         "subscription) and exit. Never moves money")
    g_account.add_argument("--cards", action="store_true",
                    help="show your free-generation cards (kaisuuken) + their ids, then exit. "
                         "Read-only; pass an id to a run with --kaisuuken-id")
    g_account.add_argument("--mirror-check", action="store_true",
                    help="check the 'Mirror to PixAI website' session: renew the saved "
                         "sign-in once and report days-left, then exit. Never reads a browser "
                         "(connect with the Connect from PixAI bookmark), never prints the "
                         "token; spends nothing")
    g_account.add_argument("--card-history", action="store_true",
                    help="show recent benefit-card usage (redemptions + refunds), then exit. "
                         "Read-only. Pass --card-history-all for the full lifetime card-type "
                         "catalog instead of a recent list")
    g_account.add_argument("--card-history-all", action="store_true",
                    help="with --card-history, page all the way back and print every card "
                         "TYPE ever used (several requests; read-only)")
    g_account.add_argument("--card-history-count", type=int, default=0, metavar="N",
                    help="with --card-history, how many recent records to show (default 20)")
    g_account.add_argument("--coupons", action="store_true",
                    help="show your currently-held Credit Boost coupons, then exit. "
                         "Read-only -- a reward type separate from benefit cards. Pass "
                         "--coupons-history for the redeemed + expired view instead")
    g_account.add_argument("--coupons-history", action="store_true",
                    help="with --coupons, show the past (redeemed + expired) view instead "
                         "of what you currently hold")
    g_account.add_argument("--credit-log", action="store_true",
                    help="show your full credit transaction ledger (purchases, claims, "
                         "gifts, generation spend, refunds), then exit. Read-only")
    g_account.add_argument("--credit-log-count", type=int, default=0, metavar="N",
                    help="with --credit-log, how many recent entries to show (default 30)")
    g_account.add_argument("--credit-log-before", default="", metavar="CURSOR",
                    help="with --credit-log, page further into the past using a cursor "
                         "printed by a previous --credit-log run")
    g_account.add_argument("--contests", action="store_true",
                    help="list PixAI contests currently running (community + official), then "
                         "exit. Read-only. Add --all-contests to include ended ones")
    g_account.add_argument("--all-contests", action="store_true",
                    help="with --contests, include ended contests too")
    g_backup.add_argument("--watch", action="store_true",
                    help="live-monitor your PixAI events over the push WebSocket (read-only; "
                         "gentler than polling). Prints task/notification events as they arrive")
    g_backup.add_argument("--watch-seconds", type=int, default=0, metavar="N",
                    help="with --watch, auto-stop after N seconds (default: run until Ctrl-C)")
    g_backup.add_argument("--watch-backup", action="store_true",
                    help="with --watch, mirror each generation into --out the instant it "
                         "reaches 'completed' (event-driven backup; no polling). Read-only")
    g_account.add_argument("--claims", action="store_true",
                    help="list your claimable rewards (daily credits, agent stamina), then "
                         "exit. Read-only")
    g_account.add_argument("--claim", default="", metavar="ID|all",
                    help="claim a ready reward by id (or 'all') -- requires --confirm. "
                         "Grants free credits/stamina to your own account")
    g_maint.add_argument("--reconcile-deleted", action="store_true",
                    help="flag catalog rows whose PixAI task is gone from your live feed "
                         "(deleted on the website) so the gallery can surface them for a "
                         "local prune, then exit")
    g_backup.add_argument("--import-local", nargs="?", const="", default=None, metavar="DIR",
                    help="catalog non-PixAI media (source='local') so it shows in the gallery. "
                         "No DIR = scan the backup folder for files you dropped in; a DIR "
                         "outside the backup is copied in. Then exit")
    # --- Generation (createGenerationTask) -------------------------------------
    g_create.add_argument("--generate", action="store_true",
                     help="create images via PixAI and catalog them (source='api'). "
                          "Preview-only unless --confirm (spends credits)")
    g_create.add_argument("--prompt", default="", help="positive prompt for --generate")
    g_create.add_argument("--negative", default="", help="negative prompt for --generate")
    g_create.add_argument("--model", default="", help="modelId for --generate (default: Tsubaki.2)")
    g_create.add_argument("--width", type=int, default=512,
                     help="image width in pixels (default 512; rounded down to a multiple of 8 "
                          "and moved onto the model's own size grid if it does not fit -- the "
                          "preview names any change)")
    g_create.add_argument("--height", type=int, default=512,
                     help="image height in pixels (default 512; rounded and moved onto the "
                          "model's size grid the same way as --width)")
    g_create.add_argument("--steps", type=int, default=25,
                     help="sampling steps (default 25; not sent to a model that publishes its "
                          "own quality profiles, which set their own)")
    g_create.add_argument("--cfg", type=float, default=7.0,
                     help="CFG scale (default 7; not sent to a model that publishes its own "
                          "quality profiles, which set their own)")
    g_create.add_argument("--batch-size", dest="count", type=int, default=1,
                     help="number of images per --generate run (batch size)")
    g_create.add_argument("--seed", type=int, default=None,
                     help="seed for a repeatable picture (default: random -- none is sent)")
    g_create.add_argument("--priority", type=int, default=PRIORITY_TURBO,
                     choices=list(PRIORITY_CHOICES),
                     help="speed channel: 0 = standard, no extra cost; 500 = turbo, "
                          "~7.6x faster and free but MEMBERS ONLY (default -- falls back "
                          "to 0 on its own if the account isn't a member); 1000 = high, "
                          "~10x faster and costs EXTRA credits; 1500 = extra high")
    g_create.add_argument("--high-priority", dest="priority", action="store_const",
                     const=PRIORITY_HIGH,
                     help="shortcut for --priority 1000 (faster, costs extra credits)")
    g_create.add_argument("--low-priority", dest="priority", action="store_const",
                     const=PRIORITY_LOW,
                     help="shortcut for --priority 0 (standard speed, never members-only)")
    g_create.add_argument("--mode", default="auto",
                     choices=["auto", "lite", "standard", "pro", "ultra"],
                     help="quality mode (inferenceProfile). auto (default) lets PixAI pick the "
                          "model's default -- always VALID (price depends on the model's own "
                          "default). lite/standard suit SD_V1 models; "
                          "pro/ultra are for newer model types. A mode the model does not list "
                          "is refused before anything is sent; if the list cannot be read and "
                          "PixAI rejects the mode, it is dropped and the run goes once on the "
                          "model's default")
    g_create.add_argument("--no-prompt-helper", dest="prompt_helper", action="store_false",
                     help="disable PixAI's prompt-helper (use your prompt more literally; "
                          "helps when auto-enhancement mangles a carefully-built prompt)")
    g_create.set_defaults(prompt_helper=True)
    g_create.add_argument("--lora", action="append", metavar="VERSIONID:WEIGHT",
                     help="add a LoRA by its version id and weight, e.g. "
                          "--lora 1686550608832816741:0.7 (repeatable). Find version ids "
                          "with --list-models")
    # Upscale + boosters. Flags are named after the PARAMETERS (what --dump-params shows),
    # with PixAI's own dialog label quoted in the help -- their two radio buttons read
    # "Upscale" (= the `enlarge` param) and "Hires" (= the `upscale` param), so naming the
    # flags after the labels instead would have made --upscale mean enlarge.
    g_create.add_argument("--enlarge", type=float, default=None, metavar="RATIO",
                     help="enlarge the finished image with an upscaler network (PixAI's "
                          "'Upscale' method), in 0.1 steps from 1.1. Clamped to the largest "
                          "ratio the output-size ceiling allows for this --width/--height. "
                          "Mutually exclusive with --upscale")
    g_create.add_argument("--enlarge-model", dest="enlarge_model", default="",
                     choices=list(ENLARGE_MODELS),
                     help="which upscaler network --enlarge runs (default: {})".format(
                         DEFAULT_ENLARGE_MODEL))
    g_create.add_argument("--upscale", type=float, default=None, metavar="RATIO",
                     help="re-diffuse the image at a larger size (PixAI's 'Hires' method), "
                          "in 0.1 steps from 1.1. Sharper than --enlarge and roughly 3x the "
                          "credits; allows a smaller maximum ratio. Mutually exclusive with "
                          "--enlarge")
    g_create.add_argument("--upscale-denoise", dest="upscale_denoising_strength", type=float,
                     default=None, metavar="STRENGTH",
                     help="--upscale denoising strength, 0.01-0.99 (default {}; PixAI's own "
                          "hint is 0.4-0.6 -- higher redraws more)".format(
                              DEFAULT_UPSCALE_DENOISING_STRENGTH))
    g_create.add_argument("--upscale-denoise-steps", dest="upscale_denoising_steps", type=int,
                     default=None, metavar="N",
                     help="--upscale denoising steps, 1-50 (default {})".format(
                         DEFAULT_UPSCALE_DENOISING_STEPS))
    g_create.add_argument("--face-fix", dest="face_fix", action="store_true",
                     help="run PixAI's face restorer over the result (enableADetailer -- "
                          "the generator's 'Face Fix' booster)")
    g_create.add_argument("--quality-tag", dest="quality_tag", nargs="?",
                     const=DEFAULT_QUALITY_TAG, default="", metavar="PREFIX",
                     help="prepend a quality booster to the prompt (the generator's "
                          "'Quality Tag'). Bare flag uses '{}'".format(DEFAULT_QUALITY_TAG))
    g_create.add_argument("--task-id", default="",
                     help="with --generate, fetch + catalog an ALREADY-created task by id "
                          "(no new credits). Recovers a stranded generation that --update "
                          "can't see, since generated tasks don't enter the listing feed")
    g_create.add_argument("--params-json", default="", help="raw parameters object (overrides the above)")
    g_create.add_argument("--poll-timeout", type=int, default=300,
                     help="seconds to wait for a submitted task to finish before giving up (default 300)")
    g_create.add_argument("--confirm", action="store_true",
                     help="REQUIRED for --generate, --generate-video, --reference-video and "
                          "--edit-image to actually submit (spends credits), and for --claim "
                          "(grants free credits/stamina to your own account)")
    # --- image-to-video generation (shares --prompt/--negative/--model/--confirm/--task-id) ---
    g_create.add_argument("--generate-video", dest="generate_video", action="store_true",
                     help="create an image-to-video clip via PixAI from a source image "
                          "(--image). Preview-only unless --confirm. Video is EXPENSIVE "
                          "(~27,500 credits for a 5s V4.0 clip)")
    g_create.add_argument("--image", default="", help="source image media_id to animate (first frame)")
    g_create.add_argument("--tail", default="", help="optional last-frame image media_id "
                     "(first/last-frame interpolation)")
    g_create.add_argument("--duration", type=int, default=5,
                     help="video length in seconds: 5, 6, 10 or 15 (default 5). Snapped to the "
                          "nearest length the chosen --video-model takes: 15 is V4.0 and Tsubaki "
                          "only (other engines stop at 10), and the Tsubaki engines have no 6")
    g_create.add_argument("--video-model", dest="video_model", default="",
                     help="video model (default v4.0.1); overrides --model for --generate-video")
    g_create.add_argument("--video-mode", dest="vmode", default="professional",
                     choices=["basic", "professional"], help="video quality tier")
    g_create.add_argument("--audio", action="store_true", help="generate audio with the video")
    g_create.add_argument("--audio-language", dest="audio_language", default="english",
                     help="spoken language for --audio video sound (default english; no effect without --audio)")
    g_create.add_argument("--video-prompt-helper", dest="video_prompt_helper", action="store_true",
                     help="enable PixAI's prompt-helper for video (off by default)")
    g_create.add_argument("--camera-movement", dest="camera_movement", default="",
                     choices=list(VIDEO_CAMERA_MOVES),
                     help="camera move (v2.7-style): horizontal/pan/roll/tilt/vertical-pan/zoom "
                          "(default unset = omit; camera direction can also go in the prompt)")
    g_create.add_argument("--video-channel", dest="vchannel", default="private",
                     choices=list(VIDEO_CHANNELS),
                     help="video channel: private = the site's 'Private' channel (works "
                          "can't be published) | normal")
    g_create.add_argument("--dump-params", action="store_true",
                     help="with --generate/--generate-video/--edit-image (esp. --task-id "
                          "recovery), print the task's full submit parameters -- bank any "
                          "param shape (multiRef, referenceVideo, ...) with no browser capture")
    # --- reference video (multi-image/video/audio reference) ---
    g_create.add_argument("--reference-video", dest="reference_video", action="store_true",
                     help="create a multi-reference video (referenceVideo): pass refs with "
                          "--ref-image/--ref-video/--ref-audio and cite them in --prompt as "
                          "@image1/@video1/@audio1. Preview-only unless --confirm")
    g_create.add_argument("--ref-image", dest="ref_image", action="append", metavar="MEDIA_ID|FILE",
                     help="reference image (media_id or local file, auto-uploaded). Repeatable: "
                          "@image1=first, @image2=second, ...")
    g_create.add_argument("--ref-video", dest="ref_video", action="append", metavar="MEDIA_ID|FILE",
                     help="reference video (repeatable; cite as @video1, @video2, ...)")
    g_create.add_argument("--ref-audio", dest="ref_audio", action="append", metavar="MEDIA_ID",
                     help="reference audio, as a media_id only -- a local audio file cannot be "
                          "uploaded (put it in a video and pass that with --ref-video). "
                          "Repeatable; cite as @audio1, ...")
    g_create.add_argument("--video-ratio", dest="video_ratio", default="",
                     choices=[""] + list(VIDEO_RATIOS), metavar="RATIO",
                     help="--reference-video output aspect ratio, Tsubaki video engines only "
                          "(tbkv1.0 / tbkv1.0.1): one of " + ", ".join(VIDEO_RATIOS)
                          + ". Default/adaptive = omitted, PixAI infers it from the references")
    # --enhance / --src / --filter-id / --strength are gone -- see build_filter_parameters'
    # former neighbourhood above for both measurements. Art filters run in the browser now
    # (static/mg-art-filters.js, the gallery's Edit > Enhance tab): free, offline, no submit.
    # --- instruct editing + media upload (the "Edit this image" surface) ---
    g_create.add_argument("--edit-image", dest="edit_image", action="store_true",
                     help="instruct-edit an image via PixAI: describe the change in --prompt "
                          "and pass source(s) with --edit-src (a catalog media_id OR a local "
                          "file, uploaded automatically). Preview-only unless --confirm")
    g_create.add_argument("--edit-src", dest="edit_src", action="append", metavar="MEDIA_ID|FILE",
                     help="source image for --edit-image: a media_id or a local image file "
                          "(local files upload automatically). Repeatable for multi-image reference")
    g_create.add_argument("--edit-model", dest="edit_model", default="",
                     help="edit model id (default PixAI Edit Pro {})".format(EDIT_PRO_MODEL_ID))
    g_create.add_argument("--edit-resolution", dest="edit_resolution", default="1K",
                     help="edit output resolution (default 1K; e.g. 1K/2K)")
    g_create.add_argument("--edit-aspect", dest="edit_aspect", default="",
                     help="edit output aspect ratio (default: the edit model's own -- Edit Pro "
                          "3:5; Reference Pro 'auto', which sends no aspect ratio and leaves "
                          "the frame to PixAI)")
    g_create.add_argument("--edit-quality", dest="edit_quality", default="medium",
                     help="edit quality tier (default medium)")
    g_create.add_argument("--upload", dest="upload_file", default="", metavar="FILE",
                     help="upload a local image to PixAI, print its media_id, then exit "
                          "(the reusable primitive behind --edit-src file support). Free")
    g_create.add_argument("--suggest-prompt", dest="suggest_prompt", default="", metavar="MEDIA|FILE",
                     help="reverse a prompt out of an image ('Image to prompt'): print PixAI's "
                          "suggested tags + description for a catalog media_id or local file. Free")
    g_create.add_argument("--kaisuuken-id", dest="kaisuuken_id", default="", metavar="ID",
                     help="force a specific free card (kaisuuken) id on this generate/edit/"
                          "video run. Normally not needed -- a matching card is auto-applied "
                          "on --confirm (like the website)")
    g_create.add_argument("--no-card", dest="no_card", action="store_true",
                     help="do NOT auto-apply a free card; pay credits even if a card matches")
    g_create.add_argument("--list-models", nargs="?", const="", default=None, metavar="KEYWORD",
                     help="search PixAI generation models by keyword and print their "
                          "generatable version ids (use as --model), then exit")
    g_maint.add_argument("--fix-model-names", action="store_true",
                    help="re-resolve readable model names for catalog rows whose model_name "
                         "is blank or a raw numeric id (one API call per distinct model), then exit")
    g_maint.add_argument("--relabel-removed", action="store_true",
                    help="with --fix-model-names, relabel ids that no longer resolve (deleted "
                         "models) to 'Unknown or removed model' instead of leaving the raw number")
    g_library.add_argument("--audit", action="store_true",
                    help="read-only duplicate audit of the whole backup folder; writes "
                         "audit_report.csv and prints a summary, then exit. Independent of catalog.db.")
    g_library.add_argument("--verify-library", dest="verify_library", action="store_true",
                    help="read-only integrity pass over every catalogued file: missing, zero-byte, "
                         "missing or empty thumbnails, uncataloged files. Writes "
                         "integrity_report.csv/.json to the library's _moonglade/records folder and prints a summary, "
                         "then exit. Changes nothing else.")
    g_library.add_argument("--verify-deep", dest="verify_deep", action="store_true",
                    help="with --verify-library, also check each file's end structurally "
                         "(PNG/JPEG/WebP/GIF end markers, MP4 moov); a torn file is reported as "
                         "suspect. Reads two small ranges per file, decodes nothing.")
    g_library.add_argument("--dedup", action="store_true",
                    help="act on the audit: move redundant copies to _duplicates/ (keeping the "
                         "most-organized copy), then reconcile catalog.db. Dry-run unless --apply.")
    g_library.add_argument("--apply", action="store_true",
                    help="with --dedup, actually perform the moves/deletes (default is dry-run); "
                         "with --import-curation, actually write the curation")
    g_library.add_argument("--export-curation", dest="export_curation", nargs="?", const="",
                    default=None, metavar="FILE",
                    help="write your curation (ratings, collections and their order, smart "
                         "collections, tags, keeper/reject marks, notes) to a JSON file keyed by "
                         "media id, then exit. Default file: curation_<stamp>.json in the library")
    g_library.add_argument("--import-curation", dest="import_curation", default="", metavar="FILE",
                    help="read a curation file back into this catalog. Dry run unless --apply; "
                         "fill-only (keeps any rating, mark or note already there) unless "
                         "--curation-overwrite. Saves the current state first.")
    g_library.add_argument("--curation-overwrite", dest="curation_overwrite", action="store_true",
                    help="with --import-curation, the file wins for the pictures it lists: "
                         "rating, mark, note, tags, collections and manual orders")
    g_library.add_argument("--dedup-delete", action="store_true",
                    help="with --dedup --apply, delete redundant copies instead of quarantining them")
    g_library.add_argument("--no-content", action="store_true",
                    help="with --audit/--dedup, skip content hashing (Class B); only do the fast "
                         "same-media_id location dedup (Class A)")
    g_library.add_argument("--verify-dupes", action="store_true",
                    help="final-pass safety check on _duplicates/: confirm every quarantined file "
                         "is byte-identical to a surviving keeper before you delete. Flags orphans "
                         "and same-id-different-bytes mismatches. Read-only unless --restore-orphans.")
    g_library.add_argument("--restore-orphans", action="store_true",
                    help="with --verify-dupes, move any orphaned quarantined files (no surviving "
                         "keeper) back to images/")
    g_library.add_argument("--empty-duplicates", dest="empty_duplicates", action="store_true",
                    help="send the files in _duplicates/ to the Recycle Bin, only after a "
                         "--verify-dupes that found every one safe and only if nothing in "
                         "_duplicates/ changed since; checks again first. Preview unless --apply. "
                         "Needs send2trash; refused under READ_ONLY.")
    g_library.add_argument("--rebuild-similar", action="store_true",
                    help="drop + re-embed the visual-similarity ('Similar') index from scratch off "
                         "the on-disk backup. Cures a corrupted/duplicate index; builds ONE clean "
                         "named index. ~decode-bound, no network. Needs torch/pixeltable. "
                         "Heavy: don't run it beside GPU- or RAM-heavy programs.")
    g_library.add_argument("--sync-similar", action="store_true",
                    help="TOP UP the 'Similar' index: embed only images it doesn't already have. "
                         "The incremental counterpart to --rebuild-similar and the one you "
                         "normally want -- it cannot lose existing rows, and after an interrupted "
                         "build it resumes instead of starting over. Needs torch/pixeltable. "
                         "Heavy: don't run it beside GPU- or RAM-heavy programs.")
    g_account.add_argument("--add-web-user", action="store_true",
                    help="add or update a gallery web-login account: interactively prompts "
                         "for a username and password (getpass -- never echoed/printed), "
                         "hashes the password, and saves it to config.json's AUTH_USERS. "
                         "Deliberately CLI-only -- no account-creation form is ever reachable "
                         "over the network")
    g_account.add_argument("--remove-web-user", default="", metavar="USERNAME",
                    help="remove a gallery web-login account by username")
    g_account.add_argument("--list-web-users", action="store_true",
                    help="list gallery web-login usernames (never password hashes), then exit")
    
    g_search.add_argument("--search", default=None, metavar="QUERY",
                    help="search the local catalog with the same query language as the gallery's "
                         "search box (words, key:value operators like model: lora:Name>0.7 "
                         "created:2026Q3 rating:>=4, -negation, quotes) and print one line per "
                         "match: media id, date, model, rating, start of the prompt. Read-only, "
                         "no network")
    g_search.add_argument("--limit", type=int, default=50, metavar="N",
                    help="with --search: print at most N matches (default 50; 0 = all)")
    g_search.add_argument("--json", dest="search_json", action="store_true",
                    help="with --search: print the matches as a JSON list instead of lines")
    g_search.add_argument("--export-csv", dest="export_csv", default="", metavar="PATH",
                    help="write the --search matches (every match, ignoring --limit) to PATH as "
                         "a CSV with the same columns as the gallery's Export view; without "
                         "--search it exports the whole catalog")
    args = ap.parse_args()
    # B2: before anything reads a setting, the install half of the move runs and the library
    # is resolved: --out for this one run, else settings.json's, else the default. The command
    # line never moves a library's files (X1): one still in an older Moonglade's layout stops
    # the command with a plain sentence, as does a move that cannot finish.
    from moonglade import setup as moonglade_setup
    # --list-web-users and --add-web-user read and write config.json alone, so the library is
    # not checked for them (an older layout, or an older Moonglade still writing it, must not
    # block them). --remove-web-user does touch the library (it deletes the login's folder
    # there), so it keeps every check. The dispatch below runs list, then remove, then add.
    accounts_only = bool(args.list_web_users or
                         (args.add_web_user and not args.remove_web_user))
    try:
        prepared = moonglade_setup.prepare("cli", explicit_out=args.out,
                                           library_half=not accounts_only)
    except moonglade_setup.MoveStopped as e:
        sys.exit(str(e))
    args.out = str(prepared.library)
    set_verbose(getattr(args, "verbose", False))
    from moonglade import logs as moonglade_logging
    moonglade_logging.setup_logging(verbose=getattr(args, "verbose", False))
    prepared.log()
    # Give every command a progress callback (terminal bar, or Control Panel markers under
    # MOONGLADE_PROGRESS=1). Commands that report progress (audit/dedup/sync/...) pick it up;
    # the rest ignore it.
    args.progress = _make_progress()

    if args.probe and args.count:
        print("Note: --probe exits before --count runs. Run them separately:\n"
              "  python -m moonglade --count\n"
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
        from moonglade.telemetry import set_telemetry_out
        set_telemetry_out(out)
    except Exception:
        pass

    try:
        if getattr(args, "search", None) is not None or getattr(args, "export_csv", ""):
            run_search(args)
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
            _job = _jobs._cli_job_start(out, "Artwork sync")
            try:
                res = run_sync_artworks(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job, warn=(res or {}).get("fail", 0),
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
            _mirror.run_mirror_check(args)
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
            _job = _jobs._cli_job_start(out, "Image generation")
            try:
                run_generate(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job)
            return
        if getattr(args, "generate_video", False):
            _job = _jobs._cli_job_start(out, "Video render")
            try:
                run_generate_video(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job)
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
            _organize.cmd_audit(args, out)
            return
        if getattr(args, "verify_library", False):
            # Read-only (moonglade/integrity.py): no _check_read_only, nothing to gate.
            from moonglade import integrity as moonglade_integrity
            _job = _jobs._cli_job_start(out, "Verify library integrity")
            try:
                moonglade_integrity.run_cli(out, db_path, deep=getattr(args, "verify_deep", False),
                                            progress=args.progress)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job)
            return
        if getattr(args, "export_curation", None) is not None:
            # Local catalog only (moonglade/curation_io.py); no PixAI call.
            from moonglade import curation_io as moonglade_curation_io
            moonglade_curation_io.run_export_cli(out, db_path, args.export_curation)
            return
        if getattr(args, "import_curation", ""):
            from moonglade import curation_io as moonglade_curation_io
            try:
                moonglade_curation_io.run_import_cli(
                    out, db_path, args.import_curation, apply=args.apply,
                    overwrite=getattr(args, "curation_overwrite", False))
            except moonglade_curation_io.CurationIOError as e:
                print("Nothing imported: {}".format(e))
                sys.exit(1)
            return
        if args.dedup:
            _organize.cmd_dedup(args, out, db_path)
            return
        if args.verify_dupes:
            _organize.cmd_verify_dupes(args, out)
            return
        if getattr(args, "empty_duplicates", False):
            _organize.cmd_empty_duplicates(args, out, db_path)
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
            _job = _jobs._cli_job_start(out, "Library sync")
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
                # WHICH ENDING (owner report, 2026-09-07). Both endings used to print the
                # same "Sync complete." -- so a Sync that stopped two pages into an
                # unfinished library announced itself exactly like one that had walked the
                # whole 37k. Say which happened, in the owner's own terms.
                if (dl or {}).get("reached_end"):
                    print("Sync complete — walked to the end of your history ({} pages)."
                          .format((dl or {}).get("pages") or 0))
                else:
                    print("Sync complete — caught up (nothing new in the last {} pages)."
                          .format(getattr(args, "update_grace", 2)))
                # Mark the first full sync done so the gallery stops withholding achievement
                # unlock toasts (first-light etc. fire on completion, not seconds into the
                # very first sync). Idempotent; covers the wizard too (its "Sync now" job
                # runs this same --sync). Fail-soft: a telemetry hiccup must not fail the sync.
                #
                # Gated on the walk-end marker since 2026-09-07: it used to be set on EVERY
                # --sync exit, so an interrupted first backup followed by a two-page Sync
                # told first_sync_complete() the first sync was done when most of the library
                # was still missing. Now the flag means what its name says.
                try:
                    from moonglade import gallery as _mg
                    if walk_end_reached(out):
                        _telemetry.telem_flag("first_sync_done", out_dir=out)
                except Exception:
                    pass
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job, warn=(dl or {}).get("fail", 0))
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
            _organize.cmd_undo_organize(args, out)
            return
        if args.organize:
            _organize.cmd_organize(args, out, img_dir, db_path)
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
        _job = _jobs._cli_job_start(out, "Incremental update" if getattr(args, "update", False) else "Full backup")
        try:
            dl = run_download(args)
        except Exception as e:                           # noqa: BLE001 -- re-raised below unchanged
            _jobs._cli_job_finish(out, _job, error=e)
            raise
        _jobs._cli_job_finish(out, _job, warn=(dl or {}).get("fail", 0))
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
    except (PixAIError, SendOutcomeUnclear) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

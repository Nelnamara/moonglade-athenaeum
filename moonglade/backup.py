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

__version__ = "3.22.0"

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

from moonglade import account_api as _account_api
from moonglade import cards as _cards
from moonglade import cloud_delete as _cloud_delete
from moonglade import contests as _contests
from moonglade import full_meta as _full_meta
from moonglade import gen_cli as _gen_cli
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import history as _history
from moonglade import jobs as _jobs
from moonglade import library_runs as _library_runs
from moonglade import media_fetch as _media_fetch
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import organize as _organize
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import pricing as _pricing
from moonglade import secure_files as _secure_files
from moonglade import task_feed as _task_feed
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import training as _training
from moonglade import web_accounts as _web_accounts
from moonglade.gallery import _NO_WINDOW
from moonglade.thumbs import build_thumbnails
from moonglade.catalog_verbs import (rows_for_media_ids,
                                     # The row-level artwork write (see run_sync_artworks): one
                                     # narrow UPDATE of the eleven PixAI-owned columns, keyed by
                                     # media_id -- imported the same way its whole-table
                                     # siblings below are.
                                     apply_artwork_meta,
                                     # ...and its twin for the four view columns, which are
                                     # folded by their own narrow UPDATE because they are read
                                     # once per deliberate sync, not on the fifteen-minute
                                     # sweep's cadence.
                                     apply_artwork_views)
from moonglade.curation import query_catalog
from moonglade.catalog import (CATALOG_FIELDS, init_db, migrate, load_catalog,
                               catalog_csv_text, save_catalog, _db_is_empty,
                               # A save of rows built from an earlier read: re-reads the
                               # current rows in the write transaction so an edit made
                               # meanwhile is never undone (2026-11-19).
                               save_catalog_over_snapshot)
from moonglade.redact import _redact_host_paths_cli
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


class PixAIOutcomeError(Exception):
    """A send reached PixAI and its answer proves neither that a task was made nor that it was
    not (DESIGN_3.22 2.2). Deliberately NOT a PixAIError: no `except PixAIError` written before
    the create door existed, and no message test, can read it as a refusal. Every caller names
    it, or reads it through gen_road.classify_outcome, which answers "unknown"."""


class CreateOutcomeUnknown(PixAIOutcomeError):
    """The create door (PixAIClient.create) sent its one POST and got no answer that proves
    either way: a timeout, a dropped connection, a 3xx, or a 2xx its kind's success extractor
    rejects (not JSON, no non-empty string `id`). The task may exist and may be charged, so a
    spend guard reads it as "may have started" and nothing is ever sent again after it.
    `kind` is the door's kind and `status` the HTTP status when there was one."""

    def __init__(self, message, kind=None, status=None):
        super().__init__(message)
        self.kind = kind
        self.status = status


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
        with _media_fetch._CONSOLE_LOCK:
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
            conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
                page_size, _pixai_client._client_of(session).user_id, before)))
            if not conn:
                break
            for edge in conn.get("edges", []):
                node = edge.get("node", edge)
                total += len(_history.media_ids_for(node))
            pi = conn.get("pageInfo", {})
            if not pi.get("hasPreviousPage"):
                break
            before = pi.get("startCursor")
        print("Library total: {} images\n".format(total))
        return total
    except PixAIError as e:
        print("  (count failed: {}) -- progress bar will show running total only\n".format(e))
        return 0


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


# Flipped the first time PixAI refuses Turbo for want of a membership. Process-scoped on
# purpose: it stops the SECOND and every later submit paying a wasted round trip, without
# caching an entitlement across runs that the owner may renew at any moment.
_turbo_refused = {"seen": False}


# --- media upload + instruct-editing (the "Edit this image" surface) --------------
# uploadMedia is a 3-step S3 handshake (verified 2026-07-01): request a presigned
# target, PUT the bytes, then register -> media_id. It's a plain GraphQL mutation, so
# gql_mutate drives it with no persisted hash (single attempt -- see upload_media).
# Uploading is FREE.
_UPLOAD_MEDIA_MUT = (
    "mutation uploadMedia($input: UploadMediaInput!) {"
    " uploadMedia(input: $input) { uploadUrl externalId mediaId"
    " media { id type width height } } }")

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


_GEN_MODEL_Q = ("query($id: ID!) { generationModel(id: $id) { id authorId title type isPrivate "
                "visibilityType } }")
_UPSERT_MODEL = ("mutation upsertGenerationModel($id: ID, $input: UpsertGenerationModelInput!) "
                 "{ upsertGenerationModel(id: $id, input: $input) { id isPrivate "
                 "visibilityType } }")


def make_model_public(session, model_id):
    """IRREVERSIBLE: a private LoRA of yours goes public (upsertGenerationModel with just
    {isPrivate: false}, exactly the site's call). Single attempt."""
    _check_read_only("make a LoRA public")
    d = gql_mutate(session, _UPSERT_MODEL, {"id": str(model_id),
                                            "input": {"isPrivate": False}}) or {}
    return d.get("upsertGenerationModel") or {}


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


def _create(session, kind, body):
    """THE create door (DESIGN_3.22 2.2): one POST of `body` to the route `kind` names in
    PixAIClient's closed path table, checked on its final bytes, never retried, never
    redirected. Returns PixAI's answer (a dict with a non-empty string `id`).

    THIN DELEGATE onto `PixAIClient.create`, kept under this name so the suite can block it the
    way it blocks `_rest_post` (dev/tests/conftest.py's `_no_live_card_network`). `session` is
    the client `for_create()` chose for this one send."""
    return _pixai_client._client_of(session).create(kind, body)


def _rest_patch(session, path, body, timeout=60):
    """PATCH JSON to a /v2 oRPC REST route. THIN DELEGATE onto `PixAIClient.rest_patch`
    (single attempt). Blocked in tests by conftest."""
    return _pixai_client._client_of(session).rest_patch(path, body, timeout=timeout)


def _rest_put(session, path, body, timeout=60):
    """PUT JSON to a /v2 oRPC REST route. THIN DELEGATE onto `PixAIClient.rest_put`
    (single attempt). Blocked in tests by conftest, like _rest_get / _rest_post."""
    return _pixai_client._client_of(session).rest_put(path, body, timeout=timeout)


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
    for row, res in _parallel_map(to_fill, lambda r: _media_fetch.resolve_media(session, r["media_id"]),
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
        task_data = _full_meta._task_for_full_meta(session, tid)
        fm = _full_meta.extract_full_meta(task_data)
        if fm.get("model_id"):
            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
        fm["loras"] = _full_meta.resolve_loras(session, task_data)
        _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18: model-preset steps/sampler/cfg
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
            fmr = _full_meta._with_batch_position(fm, row.get("media_id"))
            for f in _full_meta._FULL_META_FIELDS:
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
        src, kind = _account_api.source_media_of_task(task_data)
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
    from moonglade.thumbs import compute_dhash
    from moonglade.catalog_verbs import find_image_file
    from moonglade.catalog import load_catalog, save_catalog

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
            with _media_fetch._CONSOLE_LOCK:
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
            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
        }

    try:
        while True:
            page += 1
            conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
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
                    if _history._is_video_task_node(node):
                        continue   # video task: its poster still is NOT a standalone image
                    meta = _history.extract_meta(node)
                    all_mids = _history.media_ids_for(node)
                    full_meta = {}
                    if use_full_meta:
                        tid = meta["task_id"]
                        if tid not in _full_meta_cache:
                            task_data = _full_meta._task_for_full_meta(session, tid)
                            fm = _full_meta.extract_full_meta(task_data)
                            if fm.get("model_id"):
                                fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
                            fm["loras"] = _full_meta.resolve_loras(session, task_data)
                            _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18
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
                        stem = img_dir / _history.build_stem_name(
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
                    url, info = _media_fetch.resolve_media(session, item["mid"])
                    if not url:
                        return item, "missing", "", info, None
                    status, path = _media_fetch.download(
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
                if _history._is_video_task_node(node):
                    continue   # video task: its poster still is NOT a standalone image
                meta = _history.extract_meta(node)
                all_mids = _history.media_ids_for(node)

                # Fetch full task detail once per task_id (cached; batches cost 1 call)
                full_meta = {}
                if use_full_meta:
                    tid = meta["task_id"]
                    if tid not in _full_meta_cache:
                        task_data = _full_meta._task_for_full_meta(session, tid)
                        fm = _full_meta.extract_full_meta(task_data)
                        if fm.get("model_id"):
                            fm["model_name"] = _models.model_name_gql(session, fm["model_id"])
                        fm["loras"] = _full_meta.resolve_loras(session, task_data)
                        _full_meta._fill_preset_defaults(session, fm, task_data)   # issue #18
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
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), k),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    page_new += 1  # this media_id is not yet on disk
                    stem_name = _history.build_stem_name(
                        meta["prompt_preview"], meta["task_id"], mid,
                        args.name_length, args.name_sep)
                    stem = task_folder / stem_name
                    url, info = _media_fetch.resolve_media(session, mid)
                    w, h = info.get("width", ""), info.get("height", "")
                    if not url:
                        dl["missing"] += 1
                        page_rows.append({
                            "task_id": meta["task_id"], "media_id": mid,
                            "filename": "", "url": "", "width": w, "height": h,
                            "prompt_preview": meta["prompt_preview"],
                            "status": meta["status"], "created_at": meta["created_at"],
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
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
                            **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
                        })
                        written.add(mid)
                        _tick()
                        continue
                    status, path = _media_fetch.download(
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
                        **_full_meta._merge_full(_full_meta._with_batch_position(full_meta, mid), known.get(mid, {})),
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
    from moonglade.thumbs import build_thumbnails
    from moonglade.catalog import load_catalog
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
    g_backup.add_argument("--count-page-size", type=int, default=_history.COUNT_PAGE_SIZE,
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
    g_create.add_argument("--priority", type=int, default=_gen_params.PRIORITY_TURBO,
                     choices=list(_gen_params.PRIORITY_CHOICES),
                     help="speed channel: 0 = standard, no extra cost; 500 = turbo, "
                          "~7.6x faster and free but MEMBERS ONLY (default -- falls back "
                          "to 0 on its own if the account isn't a member); 1000 = high, "
                          "~10x faster and costs EXTRA credits; 1500 = extra high")
    g_create.add_argument("--high-priority", dest="priority", action="store_const",
                     const=_gen_params.PRIORITY_HIGH,
                     help="shortcut for --priority 1000 (faster, costs extra credits)")
    g_create.add_argument("--low-priority", dest="priority", action="store_const",
                     const=_gen_params.PRIORITY_LOW,
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
                     choices=list(_gen_params.ENLARGE_MODELS),
                     help="which upscaler network --enlarge runs (default: {})".format(
                         _gen_params.DEFAULT_ENLARGE_MODEL))
    g_create.add_argument("--upscale", type=float, default=None, metavar="RATIO",
                     help="re-diffuse the image at a larger size (PixAI's 'Hires' method), "
                          "in 0.1 steps from 1.1. Sharper than --enlarge and roughly 3x the "
                          "credits; allows a smaller maximum ratio. Mutually exclusive with "
                          "--enlarge")
    g_create.add_argument("--upscale-denoise", dest="upscale_denoising_strength", type=float,
                     default=None, metavar="STRENGTH",
                     help="--upscale denoising strength, 0.01-0.99 (default {}; PixAI's own "
                          "hint is 0.4-0.6 -- higher redraws more)".format(
                              _gen_params.DEFAULT_UPSCALE_DENOISING_STRENGTH))
    g_create.add_argument("--upscale-denoise-steps", dest="upscale_denoising_steps", type=int,
                     default=None, metavar="N",
                     help="--upscale denoising steps, 1-50 (default {})".format(
                         _gen_params.DEFAULT_UPSCALE_DENOISING_STEPS))
    g_create.add_argument("--face-fix", dest="face_fix", action="store_true",
                     help="run PixAI's face restorer over the result (enableADetailer -- "
                          "the generator's 'Face Fix' booster)")
    g_create.add_argument("--quality-tag", dest="quality_tag", nargs="?",
                     const=_gen_params.DEFAULT_QUALITY_TAG, default="", metavar="PREFIX",
                     help="prepend a quality booster to the prompt (the generator's "
                          "'Quality Tag'). Bare flag uses '{}'".format(_gen_params.DEFAULT_QUALITY_TAG))
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
                     choices=list(_gen_params.VIDEO_CAMERA_MOVES),
                     help="camera move (v2.7-style): horizontal/pan/roll/tilt/vertical-pan/zoom "
                          "(default unset = omit; camera direction can also go in the prompt)")
    g_create.add_argument("--video-channel", dest="vchannel", default="private",
                     choices=list(_gen_params.VIDEO_CHANNELS),
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
                     choices=[""] + list(_gen_params.VIDEO_RATIOS), metavar="RATIO",
                     help="--reference-video output aspect ratio, Tsubaki video engines only "
                          "(tbkv1.0 / tbkv1.0.1): one of " + ", ".join(_gen_params.VIDEO_RATIOS)
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
                     help="edit model id (default PixAI Edit Pro {})".format(_gen_params.EDIT_PRO_MODEL_ID))
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
        _web_accounts.run_list_web_users(args)
        return
    if getattr(args, "remove_web_user", ""):
        _web_accounts.run_remove_web_user(args)
        return
    if getattr(args, "add_web_user", False):
        _web_accounts.run_add_web_user(args)
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
            _library_runs.run_search(args)
            return
        if args.catalog_stats:
            _library_runs.run_catalog_stats(args)
            return
        if getattr(args, "rebuild_similar", False):
            _library_runs.run_rebuild_similar(args)
            return
        if getattr(args, "sync_similar", False):
            _library_runs.run_sync_similar(args)
            return
        if args.sync_artworks:
            # B15: same job-tracking + done_with_errors wiring --sync already has (see
            # above) -- previously this call had NO job logging at all, so a partial
            # failure (mid-pagination break, a failed video download) was invisible
            # everywhere: no Jobs-tray entry, no done_with_errors, nothing.
            _job = _jobs._cli_job_start(out, "Artwork sync")
            try:
                res = _library_runs.run_sync_artworks(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job, warn=(res or {}).get("fail", 0),
                            warn_detail="issue(s) during artwork sync")
            return
        if args.sync_videos:
            _library_runs.run_sync_videos(args)
            return
        if getattr(args, "faststart_videos", False):
            _library_runs.run_faststart_videos(args)
            return
        if args.account:
            _account_api.run_account_info(args)
            return
        if getattr(args, "cards", False):
            _account_api.run_cards(args)
            return
        if getattr(args, "mirror_check", False):
            _mirror.run_mirror_check(args)
            return
        if getattr(args, "card_history", False) or getattr(args, "card_history_all", False):
            _account_api.run_card_history(args)
            return
        if getattr(args, "coupons", False) or getattr(args, "coupons_history", False):
            _account_api.run_coupons(args)
            return
        if getattr(args, "credit_log", False):
            _account_api.run_credit_log(args)
            return
        if getattr(args, "contests", False):
            _contests.run_contests(args)
            return
        if getattr(args, "watch", False):
            _task_feed.run_watch(args)
            return
        if getattr(args, "claims", False) or getattr(args, "claim", ""):
            _account_api.run_claims(args)
            return
        if args.reconcile_deleted:
            _library_runs.run_reconcile_deleted(args)
            return
        if args.import_local is not None:
            _library_runs.run_import_local(args)
            return
        if args.list_models is not None:
            _full_meta.run_list_models(args)
            return
        if args.generate:
            _job = _jobs._cli_job_start(out, "Image generation")
            try:
                _gen_cli.run_generate(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job)
            return
        if getattr(args, "generate_video", False):
            _job = _jobs._cli_job_start(out, "Video render")
            try:
                _gen_cli.run_generate_video(args)
            except Exception as e:                       # noqa: BLE001 -- re-raised below unchanged
                _jobs._cli_job_finish(out, _job, error=e)
                raise
            _jobs._cli_job_finish(out, _job)
            return
        if getattr(args, "reference_video", False):
            _gen_cli.run_reference_video(args)
            return
        if getattr(args, "upload_file", ""):
            _gen_cli.run_upload(args)
            return
        if getattr(args, "suggest_prompt", ""):
            _account_api.run_suggest_prompt(args)
            return
        if getattr(args, "edit_image", False):
            _gen_cli.run_edit_image(args)
            return
        if args.fix_model_names:
            _library_runs.run_fix_models(args)
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
                _library_runs.run_fix_models(args)
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
                    _library_runs.run_reconcile_deleted(args)
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
            _full_meta.cmd_convert_existing(args, out)
            return
        if args.undo_organize:
            _organize.cmd_undo_organize(args, out)
            return
        if args.organize:
            _organize.cmd_organize(args, out, img_dir, db_path)
            return
        if args.probe:
            _account_api.run_probe(args)
            return
        if args.count:
            _account_api.run_count(args)
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
    except (PixAIError, _gen_road.SendOutcomeUnclear) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

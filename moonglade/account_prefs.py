"""
moonglade/account_prefs.py
==========================
Per-account preferences and state: the case-collision-safe account key every per-account store
uses, the account prefs document (/api/account/prefs) and the account state file beside it.
Moved verbatim out of moonglade/gallery.py in the 3.21.0 split (phase 2). Named account_prefs,
not accounts: moonglade/backup.py already owns the web-login accounts.

The one name it needs from the gallery (the exclusive lock file it shares with the telemetry)
is imported from moonglade.gallery inside each function that uses it, never at the top, so
importing this module never imports the gallery.
"""
import json
import os
import re
import threading
import time
from contextlib import contextmanager

from moonglade import paths as _paths


def _account_key(username):
    """Filesystem-safe, case-COLLISION-safe key for `username` -- the ONE shared
    helper every per-account store (saved views, prompt snippets, Loom storyboards,
    toolbox presets) keys its own file/directory with (B14 residual). The rule itself is
    moonglade.paths.account_key, which names each login's folder
    (<library>/_moonglade/accounts/<key>/).

    Account identity in this app is case-SENSITIVE: moonglade/backup.py's
    _find_web_user compares the raw username with `==`, and username_problem()
    rejects only empty/too-long/control-char names -- nothing about case. So "Nel"
    and "nel" are two distinct AUTH_USERS rows. But every one of these stores
    originally keyed its per-account file with quote(username, safe=""), which is
    itself case-PRESERVING: quote("Nel") == "Nel" and quote("nel") == "nel" are two
    different STRINGS naming the SAME file on NTFS, which is case-insensitive but
    case-preserving. That silently merged two distinct accounts onto one shared
    file/directory -- reproduced end to end (a save from one account was visible
    to, and overwritable by, the other) for saved views originally, then inherited
    by every store that copied the same quote() keying pattern since.

    A short hex digest of the exact (case-sensitive) username sidesteps NTFS's
    case-folding entirely: "Nel" and "nel" hash to two different digests, so they
    always land on two different files -- on every filesystem, not just Windows.
    Deliberately not reversible from the key alone -- nothing on disk needs a
    human-readable username back; the account already owns its display name in
    config.json's AUTH_USERS."""
    return _paths.account_key(username)


# ---------------------------------------------------------------------------
# Per-account preferences -- one small JSON document per app login account
# ---------------------------------------------------------------------------
# The home for state that belongs to ONE signed-in account rather than to the library:
# which first-run guides it has dismissed, the "what's new" it has seen, per-base-family
# generate defaults, a pinned goal. Deliberately generic -- a flat {key: JSON value}
# document validated at the write boundary -- so each later consumer is a key name
# (`guide.<surface>`, `seen.whatsnew`, `unleash`, ...), never another store.
#
# ON DISK: <library>/_moonglade/accounts/<key>/prefs.json, where <key> is
# _account_key(username) -- the same case-safe digest every per-account store uses, never
# the raw name -- beside the login's other stores (moonglade.paths.account_dir).
#
# WHICH ACCOUNT: the route passes session["user"] and nothing else; the body can never
# name one. There is no web "no accounts" mode to key: the gallery has no localhost
# bypass, and with zero accounts nothing past /login is reachable (DECISIONS: "The
# gallery is default-deny, with no localhost bypass"), so every request that reaches
# the route carries a real username. ACCOUNT_LOCAL is for a SERVER-SIDE caller that has
# no web session at all (the CLI, the MCP server): it lands on accounts/_local/prefs.json.
# It cannot collide with an account: a digest is 16 hex characters and never "_local",
# and the sentinel is an object, not a string, so no session cookie can carry it. An
# empty or missing username is refused outright -- it never falls back to _local.
#
# CORRUPT FILES: a read of a missing, unparsable or non-object file answers {} (fail
# soft: a torn preference must never break a page). A WRITE never silently replaces a
# corrupt file with that empty reading: the bad file is moved aside to
# <key>.corrupt-<UTC stamp>.json (kept, logged) before the new document lands. A file
# that exists but cannot be READ (a sharing violation, a permission error) refuses the
# write instead -- what could not be read is not overwritten.
#
# LOCKING: one thread lock around every read-modify-write, plus a per-account O_EXCL
# lockfile (_excl_lockfile, telemetry's) so a second process writing the same document
# cannot interleave. A lockfile that cannot be taken in time refuses the write
# (AccountPrefsBusy) rather than risk a lost update. Writes are atomic: temp file in
# the same directory + core._atomic_replace.
ACCOUNT_PREFS_NAME = "prefs.json"
ACCOUNT_PREF_KEY_MAX = 64
ACCOUNT_PREF_VALUE_MAX = 64 * 1024        # one value's compact JSON, UTF-8 bytes
ACCOUNT_PREFS_DOC_MAX = 1024 * 1024       # the whole document as written, UTF-8 bytes
# Lowercase dotted names: segments of [a-z0-9_-], the first starting with a letter, the
# rest with a letter or digit (so `seen.feat.12` works), no empty segment.
ACCOUNT_PREF_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)*$")
_ACCOUNT_PREFS_LOCK = threading.Lock()


class _AccountLocal(object):
    """The type of ACCOUNT_LOCAL. A distinct object, not a string, on purpose."""
    __slots__ = ()

    def __repr__(self):
        return "ACCOUNT_LOCAL"


ACCOUNT_LOCAL = _AccountLocal()


class AccountPrefsError(ValueError):
    """A change the store refuses (bad key, value not JSON, over a size cap, bad
    shape). str(e) is a plain sentence the route returns verbatim with a 400."""


class AccountPrefsBusy(RuntimeError):
    """Another process held this account's document lock past the wait."""


def account_prefs_path(out_dir, account):
    """The one file `account`'s preferences live in. `account` is a username (the
    session's own) or ACCOUNT_LOCAL; anything else -- None, "", whitespace, a
    non-string -- raises ValueError rather than landing on some shared file."""
    if account is ACCOUNT_LOCAL:
        return _paths.local_account_dir(out_dir) / ACCOUNT_PREFS_NAME
    if isinstance(account, str) and account.strip():
        return _paths.account_dir(out_dir, account) / ACCOUNT_PREFS_NAME
    raise ValueError("account prefs need a signed-in account (or ACCOUNT_LOCAL)")


def _account_prefs_read(p):
    """(document, state) for one prefs file. state: "ok", "missing", "corrupt" (not
    UTF-8 JSON, or not an object) or "unreadable" (it exists, the OS would not hand it
    over). The document is {} for every state but "ok"."""
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return {}, "missing"
    except OSError:
        return {}, "unreadable"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):      # UnicodeDecodeError is a ValueError
        return {}, "corrupt"
    if not isinstance(doc, dict):
        return {}, "corrupt"
    return doc, "ok"


def account_pref_key_problem(key):
    """A plain sentence saying why `key` is not a valid preference key, or None."""
    if not isinstance(key, str) or not key:
        return "Preference keys must be non-empty strings."
    if len(key) > ACCOUNT_PREF_KEY_MAX:
        return "Preference key '{}...' is longer than {} characters.".format(
            key[:24], ACCOUNT_PREF_KEY_MAX)
    if not ACCOUNT_PREF_KEY_RE.match(key):
        return ("'{}' is not a valid preference key: use lowercase dotted names "
                "like guide.library or seen.whatsnew.".format(key))
    return None


def _account_pref_normalise(key, value):
    """`value` round-tripped through JSON exactly as it will be stored, or
    AccountPrefsError. allow_nan=False: NaN/Infinity are not JSON, and the browser's
    JSON.parse would choke on the file forever after."""
    try:
        enc = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        raise AccountPrefsError("The value for '{}' is not plain JSON.".format(key))
    size = len(enc.encode("utf-8"))
    if size > ACCOUNT_PREF_VALUE_MAX:
        raise AccountPrefsError(
            "The value for '{}' is too large ({:,} bytes; the limit is {:,}).".format(
                key, size, ACCOUNT_PREF_VALUE_MAX))
    return json.loads(enc)


def account_prefs_get(out_dir, account):
    """`account`'s preferences document ({} when it has none, or its file is
    corrupt or unreadable). Returns a fresh dict the caller may keep."""
    p = account_prefs_path(out_dir, account)
    with _ACCOUNT_PREFS_LOCK:
        doc, _state = _account_prefs_read(p)
    return doc


def account_prefs_update(out_dir, account, set_=None, unset=None):
    """Apply {key: value} sets and a list of key removals to `account`'s document, in
    one locked, atomic read-modify-write. Returns the updated document.

    Every key and value is validated before anything is written; one bad entry
    refuses the whole change (AccountPrefsError, nothing written). The document cap is
    checked on the result, except for a change that only REMOVES keys -- that is
    always accepted, so an over-cap document (a hand-edited file) can still shrink.
    Unsetting a key that is not there is a no-op, not an error. A change that alters
    nothing writes nothing -- except over a corrupt file, which any change sets aside
    and replaces.

    Raises AccountPrefsError (refused change), AccountPrefsBusy (another process held
    the lock), OSError (the file could not be read, preserved or written)."""
    from moonglade.telemetry import _excl_lockfile
    set_ = {} if set_ is None else set_
    unset = [] if unset is None else unset
    if not isinstance(set_, dict):
        raise AccountPrefsError("'set' must be an object of {key: value}.")
    if not isinstance(unset, (list, tuple)):
        raise AccountPrefsError("'unset' must be a list of keys.")
    clean = {}
    for k, v in set_.items():
        problem = account_pref_key_problem(k)
        if problem:
            raise AccountPrefsError(problem)
        clean[k] = _account_pref_normalise(k, v)
    drop = []
    for k in unset:
        problem = account_pref_key_problem(k)
        if problem:
            raise AccountPrefsError(problem)
        if k in clean:
            raise AccountPrefsError("'{}' is in both 'set' and 'unset'.".format(k))
        drop.append(k)

    p = account_prefs_path(out_dir, account)
    with _ACCOUNT_PREFS_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _excl_lockfile(p.with_suffix(".lock"))
        if lock is None:
            raise AccountPrefsBusy("Preferences are being saved elsewhere; try again.")
        try:
            doc, state = _account_prefs_read(p)
            if state == "unreadable":
                raise OSError("could not read the saved preferences to update them")
            new = dict(doc)
            new.update(clean)
            for k in drop:
                new.pop(k, None)
            if new == doc and state != "corrupt":
                return new      # nothing changed (a missing file stays missing)
            data = json.dumps(new, indent=1, sort_keys=True, ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
            if clean and len(data) > ACCOUNT_PREFS_DOC_MAX:
                raise AccountPrefsError(
                    "Saved preferences would be too large ({:,} bytes; the limit "
                    "is {:,}).".format(len(data), ACCOUNT_PREFS_DOC_MAX))
            if state == "corrupt":
                _account_prefs_set_aside(p)
            from moonglade import backup as core
            tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
            try:
                tmp.write_bytes(data)
                core._atomic_replace(tmp, p)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            return new
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Per-account narrator state -- SERVER-ONLY, deliberately not the prefs store
# ---------------------------------------------------------------------------
# The narrator's ladder (moonglade/narrator.py) is progress an account earns slowly, so it
# cannot live where the account itself can write: /api/account/prefs takes any key from the
# browser, which would make "the count" one console line away. This is a sibling store with
# the same key rule (_account_key), the same locking (a thread lock plus a per-account
# lockfile) and the same atomic write, and NO route that takes a state from a client: the
# poke route below is the only writer, and it writes what moonglade.narrator.poke() returned.
#
# ON DISK: <library>/_moonglade/accounts/<key>/state.json. A missing, torn or non-object file reads as a
# fresh state (fail soft: a torn file must not break a click); a write never fails a poke
# silently -- the route answers what it could not save.
ACCOUNT_STATE_NAME = "state.json"
_ACCOUNT_STATE_LOCK = threading.Lock()


def account_state_path(out_dir, account):
    """The file `account`'s server-only state lives in. A username (the session's own);
    anything else -- None, "", whitespace, a non-string -- raises ValueError rather than
    landing on some shared file."""
    if not (isinstance(account, str) and account.strip()):
        raise ValueError("account state needs a signed-in account")
    return _paths.account_dir(out_dir, account) / ACCOUNT_STATE_NAME


@contextmanager
def account_state_locked(out_dir, account):
    """Hold this account's state lock (thread + process) for a read-modify-write.
    Yields the path. Raises AccountPrefsBusy when another process held the lockfile past the
    wait -- the caller refuses the request rather than risk a lost update."""
    from moonglade.telemetry import _excl_lockfile
    p = account_state_path(out_dir, account)
    with _ACCOUNT_STATE_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _excl_lockfile(p.with_suffix(".lock"))
        if lock is None:
            raise AccountPrefsBusy("Busy; try again.")
        try:
            yield p
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def _narrator_clock():
    """(epoch seconds, local calendar day) -- the two readings the ladder is given. The day
    is the SERVER's local date, the same convention the Vigil's day ledger uses
    (telem_mark_day). One seam so a test can drive a fortnight without sleeping."""
    import datetime as _dt
    return time.time(), _dt.date.today().isoformat()


def account_state_read(p):
    """The stored document ({} when missing, unreadable, torn or not an object)."""
    doc, _state = _account_prefs_read(p)
    return doc


def account_state_write(p, doc):
    """Atomically replace `p` with `doc`. Raises OSError."""
    from moonglade import backup as core
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
    try:
        tmp.write_bytes(data)
        core._atomic_replace(tmp, p)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _account_prefs_set_aside(p):
    """Move a corrupt prefs file out of the way (kept, never deleted) so the write
    about to land does not silently destroy it. Raises OSError if it cannot be moved:
    a file that could not be preserved is not overwritten."""
    import logging as _logging
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    aside = p.with_name("{}.corrupt-{}.json".format(p.stem, stamp))
    n = 1
    while aside.exists():
        n += 1
        aside = p.with_name("{}.corrupt-{}-{}.json".format(p.stem, stamp, n))
    os.replace(p, aside)
    _logging.getLogger(__name__).warning(
        "account prefs: %s was not a JSON object; kept it as %s and started a fresh "
        "document", p.name, aside.name)

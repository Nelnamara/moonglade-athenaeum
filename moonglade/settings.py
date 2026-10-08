"""moonglade.settings -- local\\settings.json: everything the app writes for this install.

config.json keeps only what a person edits by hand (the PixAI key, the logins, the session key
and its revocation counter, READ_ONLY, USER_ID and the hash overrides). Everything the app
itself sets lives here instead, one key each (DECISIONS 2026-10-07; SPEC_3.20_REBUILD.md, S17):

  library_dir      the library folder, as stored (absolute when the Control Panel set it; a
                   relative one is anchored to the app folder). Absent: the default library.
  host, port       the bind address and port.
  bonjour          {"enabled": bool, "name": str}: LAN discovery.
  mirror_to_pixai  the Control Panel's "Mirror to PixAI website" switch.
  launch_args      the server's launch switches that outlive one start (LAUNCH_FLAGS).
  branding         {"mark": id, "animation": {anim, anim_speed, anim_scale, glow_color,
                   glow_angle}, "slots": {slot: asset id}, "worn_banner": {slot: {...}}}.

One file, one lock, written whole and atomically (a temp beside it, flushed to disk, then
os.replace). A reader parses it once per change of the file: the document is cached against
the file's (inode, mtime, size), so the per-request readers (the mark on every page, the
Mirror switch on every generation) cost one stat. It is read as UTF-8 with or without a byte
order mark (Notepad and PowerShell write one).

A file that is there but cannot be read (another program holds it) or will not parse is never
written over: update() refuses (SettingsUnreadable), and every start stops with a sentence
(moonglade.setup.prepare checks state() first) rather than open the default library. A
moment's failure to read is never cached as an empty document.

Nothing here reads an old place. The values that used to live in config.json, serve.txt,
branding.json and branding_slots.json are brought here once by the move (moonglade.migrate),
which runs before anything reads a setting (moonglade.setup.prepare).
"""
import copy
import json
import os
import threading
import time
from pathlib import Path

from moonglade import paths as _paths

LIBRARY_DIR = "library_dir"
HOST = "host"
PORT = "port"
BONJOUR = "bonjour"
MIRROR_TO_PIXAI = "mirror_to_pixai"
LAUNCH_ARGS = "launch_args"
BRANDING = "branding"
KEYS = (LIBRARY_DIR, HOST, PORT, BONJOUR, MIRROR_TO_PIXAI, LAUNCH_ARGS, BRANDING)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_BONJOUR_NAME = "Moonglade"

# The server's launch switches that may be stored (launch_args): each one is a plain switch the
# server takes, and each means the same thing at every start. Anything else a hand-written
# serve.txt held is dropped by the move, with a log line: the library, host and port become
# their own keys; the one-shot switches below would repeat their one-off job at every start.
LAUNCH_FLAGS = ("--https", "--skip-thumbs", "--allow-port-reuse", "-v", "--verbose")
ONE_SHOT_FLAGS = ("--rebuild-thumbs", "--open-browser")

# The addresses the server can bind from a stored host (an explicit --host is trusted as typed).
_BINDABLE_HOSTS = ("127.0.0.1", "0.0.0.0", "localhost", "::", "::1")

_LOCK = threading.RLock()
_cache = {"key": None, "doc": None}
LOCK_WAIT_S = 5.0
LOCK_STALE_S = 30.0


class SettingsBusy(RuntimeError):
    """Another process held settings.json's lock past the wait: the change was not saved."""


class SettingsUnreadable(OSError):
    """settings.json is there but cannot be read, or is not a settings document. Nothing is
    written over it: a fresh file would throw away the library pin, the port and every pick."""


def _stamp(p):
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _parse(p):
    """(document, state, why): state "ok", "missing", "unreadable" (the file is there but
    could not be read: another program holds it, access was refused) or "corrupt" (not JSON,
    or not an object); `why` says it in plain words. The document is {} unless "ok"."""
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return {}, "missing", ""
    except OSError as e:
        why = ("access was refused, or another program has it open"
               if isinstance(e, PermissionError) else (e.strerror or e.__class__.__name__))
        return {}, "unreadable", why
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return {}, "corrupt", "it isn't valid JSON"
    if not isinstance(doc, dict):
        return {}, "corrupt", "it doesn't hold a settings object"
    return doc, "ok", ""


def state():
    """(state, why) of settings.json, read now: see _parse."""
    _doc, st, why = _parse(_paths.settings_path())
    return st, why


def read():
    """The whole document, a copy the caller may change freely. A missing, unreadable or
    damaged file reads as {} (fail soft: a torn settings file must never stop a page); a file
    that could not be read at all is not cached, so the next read tries again."""
    p = _paths.settings_path()
    key = (str(p), _stamp(p))
    with _LOCK:
        if _cache["key"] != key or _cache["doc"] is None:
            doc, st, _why = _parse(p)
            if st == "unreadable":
                return {}
            _cache["key"], _cache["doc"] = key, doc
        return copy.deepcopy(_cache["doc"])


def get(key, default=None):
    return read().get(key, default)


def _file_lock(p):
    """settings.json's cross-process lock: an O_EXCL lockfile beside it, taken within
    LOCK_WAIT_S; one older than LOCK_STALE_S was left by a process that died. Returns its
    path, or raises SettingsBusy."""
    lock = p.with_name(p.name + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                pass
        except PermissionError:
            pass                                 # Windows: a holder's lock being deleted
        if time.monotonic() > deadline:
            raise SettingsBusy("settings.json is busy; try again.")
        time.sleep(0.02)


def _write(p, doc):
    """Write `doc` whole: a temp beside the file, flushed to disk, then os.replace."""
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp = p.with_name("%s.tmp-%d" % (p.name, os.getpid()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                # Windows: an indexer or scanner can hold the target for a moment.
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def update(fn):
    """Change the settings: `fn(doc)` edits a fresh read of the document in place, and the
    result is written whole. Holds the one lock (this process's, and the lockfile every
    process honours) across the read and the write, so two writers never lose each other's
    change. A file that exists but cannot be read, or will not parse, is never written over:
    the change is refused (SettingsUnreadable), and the file kept as it is. Returns a copy of
    the new document. Raises SettingsBusy or OSError (SettingsUnreadable included)."""
    p = _paths.settings_path()
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _file_lock(p)
        try:
            doc, st, why = _parse(p)
            if st in ("unreadable", "corrupt"):
                raise SettingsUnreadable("settings.json can't be read (%s), so the change was "
                                         "not saved." % why)
            fn(doc)
            _write(p, doc)
            _cache["key"], _cache["doc"] = (str(p), _stamp(p)), copy.deepcopy(doc)
            return copy.deepcopy(doc)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def set_values(**values):
    """Store each key=value (a value of None removes the key)."""
    def _apply(doc):
        for k, v in values.items():
            if v is None:
                doc.pop(k, None)
            else:
                doc[k] = v
    return update(_apply)


# ---- the library ----------------------------------------------------------------------------
def library_dir():
    """The library folder as stored, or "" when none is (the default library is in use)."""
    v = read().get(LIBRARY_DIR)
    return v.strip() if isinstance(v, str) else ""


def library_path(explicit=None):
    """THE library resolver, used by the server, the command line and the MCP server (S8): an
    explicit choice for this one run (--out, MOONGLADE_OUT), then settings.json's library_dir,
    then the default. An explicit one is taken as typed (a relative one is relative to where it
    was typed); a stored or default one that is relative is anchored to the app folder, so every
    entry point -- whatever its working directory -- opens the same library."""
    if explicit:
        return Path(str(explicit))
    stored = library_dir() or _paths.DEFAULT_LIBRARY_DIR
    p = Path(stored).expanduser()
    return p if p.is_absolute() else _paths.library_anchor() / p


# ---- the server -----------------------------------------------------------------------------
def _host(value):
    host = str(value or "").strip() or DEFAULT_HOST
    if host in _BINDABLE_HOSTS:
        return host
    # A hand-edited or junk host must not crash the bind at startup: only a real IP literal.
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return DEFAULT_HOST


def _port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    if isinstance(value, bool) or not 1 <= port <= 65535:
        return DEFAULT_PORT
    return port


def server(host_arg=None, port_arg=None, doc=None):
    """{host, port, bonjour_enabled, bonjour_name}. An explicit --host/--port for this one
    start wins; else the stored values (from `doc` when given: the settings as the move will
    leave them, moonglade.migrate.planned_settings); else the defaults. Bonjour is off unless
    switched on."""
    doc = read() if doc is None else doc
    bonjour = doc.get(BONJOUR) if isinstance(doc.get(BONJOUR), dict) else {}
    host = host_arg if host_arg is not None else _host(doc.get(HOST))
    try:
        port = int(port_arg) if port_arg is not None else _port(doc.get(PORT, DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    name = str(bonjour.get("name") or "").strip() or DEFAULT_BONJOUR_NAME
    return {"host": host, "port": port, "bonjour_enabled": bool(bonjour.get("enabled", False)),
            "bonjour_name": name}


def launch_args(doc=None):
    """The stored launch switches, in order, each one of LAUNCH_FLAGS."""
    v = (read() if doc is None else doc).get(LAUNCH_ARGS)
    if not isinstance(v, list):
        return []
    return [str(a) for a in v if str(a) in LAUNCH_FLAGS]


def mirror_to_pixai():
    """Is the Control Panel's "Mirror to PixAI website" switch on? Off unless stored on."""
    return read().get(MIRROR_TO_PIXAI) is True


# ---- branding ---------------------------------------------------------------------------------
def branding():
    """The branding picks: {"mark", "animation", "slots", "worn_banner"}, each present only
    when stored (moonglade.gallery validates them against what exists)."""
    v = read().get(BRANDING)
    return v if isinstance(v, dict) else {}


def update_branding(fn):
    """Change the branding picks: `fn(branding)` edits the "branding" object in place."""
    def _apply(doc):
        b = doc.get(BRANDING)
        if not isinstance(b, dict):
            b = {}
        fn(b)
        doc[BRANDING] = b
    return update(_apply)

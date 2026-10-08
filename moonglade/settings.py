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
Mirror switch on every generation) cost one stat.

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


def _stamp(p):
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _parse(p):
    """(document, state): state "ok", "missing" or "corrupt" (unreadable, not JSON, or not an
    object). The document is {} unless "ok"."""
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return {}, "missing"
    except OSError:
        return {}, "corrupt"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}, "corrupt"
    if not isinstance(doc, dict):
        return {}, "corrupt"
    return doc, "ok"


def read():
    """The whole document, a copy the caller may change freely. A missing or unreadable file
    reads as {} (fail soft: a torn settings file must never stop a page)."""
    p = _paths.settings_path()
    key = (str(p), _stamp(p))
    with _LOCK:
        if _cache["key"] != key or _cache["doc"] is None:
            doc, _state = _parse(p)
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
    change. A file that exists but will not parse is set aside (settings.json.corrupt-<time>,
    kept) rather than silently replaced. Returns a copy of the new document. Raises
    SettingsBusy or OSError."""
    p = _paths.settings_path()
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _file_lock(p)
        try:
            doc, state = _parse(p)
            if state == "corrupt":
                aside = p.with_name("%s.corrupt-%s" % (
                    p.name, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())))
                os.replace(p, aside)
                import logging
                logging.getLogger("moonglade.settings").warning(
                    "settings.json could not be read; set aside as %s and started fresh.",
                    aside.name)
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


def server(host_arg=None, port_arg=None):
    """{host, port, bonjour_enabled, bonjour_name}. An explicit --host/--port for this one
    start wins; else the stored values; else the defaults. Bonjour is off unless switched on."""
    doc = read()
    bonjour = doc.get(BONJOUR) if isinstance(doc.get(BONJOUR), dict) else {}
    host = host_arg if host_arg is not None else _host(doc.get(HOST))
    try:
        port = int(port_arg) if port_arg is not None else _port(doc.get(PORT, DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    name = str(bonjour.get("name") or "").strip() or DEFAULT_BONJOUR_NAME
    return {"host": host, "port": port, "bonjour_enabled": bool(bonjour.get("enabled", False)),
            "bonjour_name": name}


def launch_args():
    """The stored launch switches, in order, each one of LAUNCH_FLAGS."""
    v = read().get(LAUNCH_ARGS)
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

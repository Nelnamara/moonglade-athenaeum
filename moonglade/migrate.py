"""moonglade.migrate -- the move into the layout moonglade.paths describes.

Two halves, each with its own journal and its own lock (SPEC_3.20_REBUILD.md; DECISIONS
2026-10-07, "The full reorganize: the owner's picks"):

  * THE INSTALL HALF (migrate_install), in local\\ under local\\.lock, journal local\\.journal.json:
    the settings merge (serve.txt, the app-written keys of config.json, branding.json and
    branding_slots.json fold into local\\settings.json), then the art pack and its marker, the
    Mirror's sign-in, the launcher's serve.log*, and the shortcut icons.
  * THE LIBRARY HALF (migrate_library), in <library>\\_moonglade\\ under its .lock, journal
    _moonglade\\.journal.json: the records, the owner's decisions, every per-login store, the
    Loom, the logs, the banner renders, the dead branding copies.

moonglade.setup.prepare() runs both, in that order, before anything reads a setting. The
install half runs for every kind of start; the library half moves files only for a launcher or
server start, and only in the library this install serves (prepare_library): a command-line or
MCP run, or any run that names its own library, never moves one, and refuses a library still in
an older layout rather than read empty new homes.

The rules (each one is a test in dev/tests/test_move_*.py):

  * ONE HOME PER ITEM. After the move nothing reads an old place; only this module knows where
    an older version kept things.
  * THE SAFE MOVE, per file: copy into a temp beside the destination (SQLite through its backup
    API), flush it to disk, verify it (sha256 for a file; PRAGMA integrity_check and every
    table's row count for a database), write the journal entry, swap the temp in with
    os.replace (only ever within one folder), mark the entry made, then delete the source.
    Nothing is ever renamed across folders or volumes. An interrupted move is finished by the
    next start: a leftover temp is this module's own and is discarded, and a destination the
    journal says the move made is trusted.
  * CONFLICTS. A copy in the new place wins only when the journal says the move made it (and
    the old copy is still the very bytes it copied). Any other two-copy case: JSONL and other
    append-only line files are merged (lines the other lacks are appended); the counters and
    sets of telemetry.json, achievements.json and the spend guard are merged where the format
    allows; anything else keeps the newer copy and parks the other in .snapshot\\parked\\, with
    a log line. Nothing is deleted on a guess. (Two copies with the same bytes are one.)
  * THE SNAPSHOT (the owner's pick 4). Before a run moves, removes or parks anything, the small
    records it is about to touch are zipped into its half's .snapshot\\ (one zip per run that has
    work, so every later sweep is covered too) -- never pictures, catalog.db, the art pack, the
    logs, a cache, or the Mirror's sign-in (a stale token is a credential lying around). Parked
    copies go beside the zip. Once the move has finished, the journal counts clean server
    starts -- a server that served for a while, or was stopped cleanly (count_clean_start,
    called by the server, never by prepare) -- and the first one after a run that moved
    anything does not count. At CLEAN_STARTS the app deletes .snapshot\\.
  * AN OLDER INSTALL STILL LIVE. Once a library's move has finished, an old-layout file written
    after it means an older Moonglade is still using that library: the start stops and says
    so, rather than sweep its records out from under it. Started again with nothing more
    written there (the person closed it), the move brings in what it wrote.
  * PER-LOGIN DATA. Every login key's files move into accounts\\<key>\\, whether or not this
    install's config.json lists the login (another install may share the library). A file
    named by a login's plain name (before the hashed keys) goes to that login's folder when
    the login is known; otherwise it stays where it is, said in the log. Nothing per-login is
    deleted here: only removing a login (the Users tab, --remove-web-user) does that.
  * CACHES ARE REBUILT, not copied: the badge thumbnails, feat masks and slot/earned banner
    renders are deleted, and made again in local\\cache\\ when next needed. The shortcut icons are
    not a cache: they go to local\\icons\\ before the old icon cache folders are deleted.
  * UPGRADES from 3.17 onward, plus the copy-first 3.20 layout: 3.20's MOVED.json records
    (`source_print`) tell its copies from files written since, then are deleted. The pre-v7
    pack rename (moonglade.assets.migrate_legacy_name) and the shared-presets fold run here;
    the legacy branding-root move and the Loom store.json split stay where they were
    (moonglade.gallery), now acting on the new homes.
  * THE SPEND RECORDS (train_guard.json, the Loom's _submits\\) move as files, through the same
    safe move, while nothing runs: no server has started yet. No spend logic is here.
  * A FAILURE STOPS THE START (MoveStopped, with a plain sentence that says why and what to
    do): a lock held past its wait, a file that cannot be copied or removed, an unreadable
    config.json while the settings are still to merge. Carrying on would read empty new homes.
    A source the move has copied and verified is made writable before it is deleted, and a
    refusal is tried again a few times, so a read-only file or a scanner's moment never stops
    every start.
"""
import calendar
import errno
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote as _quote

from moonglade import paths as _paths

LOGGER_NAME = "moonglade.migrate"
JOURNAL_FORMAT = 1
LOCK_WAIT_S = 60.0           # how long a start waits for another start's move
LOCK_STALE_S = 300.0         # another PC's lock untouched this long was left by a start that died
HEARTBEAT_S = 5.0            # a held lock is touched at least this often, even mid-file
CLEAN_STARTS = 5             # clean server starts after which .snapshot\ is deleted (pick 4)
MOVING_SUFFIX = ".moving"    # the temp a copy is made into, beside its destination
PARKED_DIRNAME = "parked"
REMOVE_TRIES = 5             # a delete Windows refuses is tried this many times...
REMOVE_BACKOFF_S = 0.1       # ...pausing 0.1, 0.2, 0.4 and 0.8 s between tries
WRITTEN_SINCE_SLACK_S = 2.0  # a file's time this close to the move's own end is the move's
# The kinds of start that may move a library's files (X1): the launcher and the web server, in
# the library this install serves. The command line and the MCP server never do.
MOVING_KINDS = ("launcher", "server")

# ---- what older versions kept, and where (only this module may name these) -----------------
OLD_RECORD = "MOVED.json"                # 3.20's copy-first record, in local\ and _moonglade\
OLD_LOCK = ".migrating"                  # 3.20's lock name
OLD_ICON_CACHE = "_container_cache"      # 3.19's icon cache at the app root
OLD_REPORTS = "reports"                  # 3.20's _moonglade\reports\
SETTINGS_FILES = ("serve.txt", "branding.json", "branding_slots.json")
LAUNCHER_LOGS = ("serve.log", "serve.log.1", "serve.log.2", "serve.log.3")
# The config.json keys the app wrote, which now live in settings.json.
CONFIG_MOVED_KEYS = ("LIBRARY_DIR", "HOST", "PORT", "BONJOUR_ENABLED", "BONJOUR_NAME",
                     "MIRROR_TO_PIXAI")
# The app's own dead files at the install root (S9): the desktop GUI's settings (the GUI went
# in v2.1.0). A 0-byte catalog.db there is dead too (_install_half), never a real catalog.
DEAD_ROOT_FILES = ("pixai_gui_settings.json",)
# The library's dead files: the legacy catalog export nothing has read since 2026-08-24 (the
# gallery's "Download catalog (CSV)" makes a fresh one on demand).
DEAD_LIBRARY_FILES = ("catalog.csv",)
PACK_NAME = _paths.PACK_NAME
PACK_MARKER = PACK_NAME + ".version"

# The library's records: name -> how two copies are reconciled.
RECORDS = {
    "achievements.json": "json:achievements",
    "telemetry.json": "json:telemetry",
    "schedule.json": "file",
    "train_guard.json": "json:guard",
    "reconcile_stamp.json": "file",
    "jobs.jsonl": "lines",
    "raw_tasks.jsonl": "lines",
    "runs.db": "db",
    # the integrity reports are records (S6), regenerable but read by Health
    "integrity_report.csv": "file",
    "integrity_report.json": "file",
    "audit_report.csv": "file",
    "verify_report.csv": "file",
}
# Reports, which 3.20 kept in _moonglade\reports\ rather than _moonglade\ itself.
_REPORT_NAMES = ("integrity_report.csv", "integrity_report.json", "audit_report.csv",
                 "verify_report.csv")
# The owner's decisions: name -> how two copies are reconciled. Plus the curation undo files.
DECISIONS = {
    "integrity_marks.json": "file",
    "organize_manifest.csv": "lines",       # append-only, header first
}
CURATION_SNAPSHOT_PREFIX = "curation_pre_import_"
# The per-login stores: old folder -> the file's name in accounts\<key>\.
PER_LOGIN = {
    "account_prefs": "prefs",
    "account_state": "state",
    "prompt_snippets": "snippets",
    "toolbox_presets": "presets",
    "view_presets": "views",
}
# The install-wide files three of those replaced: folded into each login with none of its own.
SHARED_PRESETS = {
    "prompt_snippets.json": "snippets.json",
    "toolbox_presets.json": "presets.json",
    "view_presets.json": "views.json",
}
# The rendered banner flats (moonglade.gallery._BANNER_FLAT), by slot.
BANNER_FLATS = {"banner_main": "banner.png", "banner_login": "login-banner.png",
                "banner_loom": "banner-loom.png"}
# Rebuildable caches a library used to hold under gallery\cache\.
LIBRARY_CACHES = ("_badges", "_masks", "_banners")
# The Loom's caches and scratch: never in the snapshot (they are rebuilt or re-exported).
_LOOM_UNSNAPPED = ("_beds", "_frames", "_uploads", "exports", "_exports")
# Transient files nothing needs: a lock, a half-written temp.
_TRANSIENT_RE = re.compile(r"(\.lock$|\.part$|\.tmp$|\.tmp-|\.copying-|\.rotating-)")

_KEY_RE = re.compile(r"^(?:[0-9a-f]{16}|_local)$")


def old_app_root():
    """Where an install before this layout kept its machine files: the app folder itself.
    The tests pin this to a folder of their own (dev/tests/conftest.py)."""
    return _paths.APP_ROOT


class MoveStopped(RuntimeError):
    """The move could not go on, and the start must stop. str(e) is a plain sentence."""


class _Failed(Exception):
    """One step of the move failed. `cause` is the OSError behind it, when there is one, so
    the sentence the person sees can say what to do about it (_advice)."""

    def __init__(self, msg, cause=None):
        super().__init__(msg)
        self.cause = cause


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log():
    return logging.getLogger(LOGGER_NAME)


# ---- what one run did -------------------------------------------------------------------------
class Report:
    """What a prepare() run did, as plain log lines, and whether each half found anything to
    do (worked) or parked anything. Two kinds of line: the overview (info, warn) and one line
    per item the move handled (item: what, from where, to where, and how -- moved, merged,
    set aside, removed). log() writes both to the app's log once logging is up; a start that
    never sets logging up (the launcher) appends them to local\\logs\\moonglade.log itself
    (write_log). summary() is the overview alone, for serve.log's one line."""

    def __init__(self):
        self.lines = []
        self.items = []
        self.worked = {"install": False, "library": False}
        self.parked = 0

    def info(self, msg, *args):
        self.lines.append((logging.INFO, msg % args if args else msg))

    def warn(self, msg, *args):
        self.lines.append((logging.WARNING, msg % args if args else msg))

    def item(self, msg, *args):
        self.items.append((logging.INFO, msg % args if args else msg))

    def all_lines(self):
        return self.items + self.lines

    def log(self):
        for level, line in self.all_lines():
            _log().log(level, line)

    def write_log(self, path=None):
        """Append every line to the app's log file (moonglade.log, in the format
        moonglade.logs writes) from a process that has not set logging up. Never raises."""
        if not self.items and not self.lines:
            return
        path = Path(path) if path is not None else _paths.logs_dir() / "moonglade.log"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for level, line in self.all_lines():
                    f.write("%s %-8s [%s] %s\n" % (stamp, logging.getLevelName(level),
                                                   LOGGER_NAME, line))
        except OSError:
            pass

    def summary(self):
        return " ".join(line for _level, line in self.lines)


# ---- the journal and the lock -------------------------------------------------------------------
class Journal:
    """One half's journal: {format, started, finished, settings_merged, snapshot,
    clean_starts, items: {destination: {src, src_sha256, sha256, state, time}}}. Written
    whole, through a temp flushed to disk."""

    def __init__(self, folder):
        self.path = Path(folder) / _paths.JOURNAL_NAME
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
                raise ValueError
        except (OSError, ValueError):
            doc = {"format": JOURNAL_FORMAT, "started": None, "finished": None, "items": {}}
        self.doc = doc

    @property
    def items(self):
        return self.doc["items"]

    def save(self):
        _write_bytes(self.path, (json.dumps(self.doc, indent=1, sort_keys=True) + "\n")
                     .encode("utf-8"))

    def finish(self):
        """Stamp the half finished, and remember the journal file's own time as the disk
        wrote it (finished_mtime_ns): an old-layout file written later than that was written
        after the move (written_since), and the disk's clock -- a NAS's own included -- is
        the one both times come from."""
        self.doc["finished"] = _now()
        self.save()
        try:
            self.doc["finished_mtime_ns"] = self.path.stat().st_mtime_ns
            self.save()
        except OSError:
            pass

    def finished_at(self):
        """When the half last finished, in seconds on the disk's clock, or None."""
        ns = self.doc.get("finished_mtime_ns")
        if isinstance(ns, int) and ns > 0:
            return ns / 1e9
        stamp = self.doc.get("finished")
        if isinstance(stamp, str):
            try:
                return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
            except ValueError:
                return None
        return None

    def worked(self):
        """This run moved, merged, parked or removed something: the clean-start count starts
        again, and the next served start does not count (count_clean_start)."""
        self.doc["clean_starts"] = 0
        self.doc["skip_next"] = True


def _host():
    """This PC's name, as a lock records it."""
    try:
        return socket.gethostname() or "?"
    except OSError:
        return "?"


def _process_started(pid):
    """When process `pid` started (seconds since the epoch), or None when that cannot be
    known. A lock is only ever taken over from a dead holder: a pid that is running but
    started after the lock was made is a reused number, not the holder."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            h = k32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            try:
                created, exited, kernel, user = (wintypes.FILETIME(), wintypes.FILETIME(),
                                                 wintypes.FILETIME(), wintypes.FILETIME())
                if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                           ctypes.byref(kernel), ctypes.byref(user)):
                    return None
                ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
                return ticks / 1e7 - 11644473600.0
            finally:
                k32.CloseHandle(h)
        except (OSError, AttributeError, ValueError):
            return None
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            fields = f.read().rsplit(b")", 1)[1].split()
        start_ticks = int(fields[19])
        with open("/proc/stat", "rb") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith(b"btime"))
        return btime + start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


def _pid_alive(pid):
    """Is process `pid` running? Unknown answers True (never break a live holder's lock).
    Never signals anything: on Windows os.kill would TERMINATE the process, so the process is
    only opened for a query."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return False         # this process holds no lock across prepare() calls: a dead run's
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            h = k32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return ctypes.get_last_error() != 87     # ERROR_INVALID_PARAMETER: no such pid
            try:
                code = wintypes.DWORD()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return True
                return code.value == 259                 # STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except (OSError, AttributeError, ValueError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


# The locks this process holds now, touched by _heartbeat() from inside long steps.
_HELD = []
_BEAT = {"at": 0.0}


def _heartbeat(force=False):
    """Touch every lock this process holds -- the install lock too while the library half
    runs -- at most every HEARTBEAT_S (always when `force`): a long copy (a Loom export, a
    slow network drive) is never taken for a start that died."""
    now = time.monotonic()
    if not force and now - _BEAT["at"] < HEARTBEAT_S:
        return
    _BEAT["at"] = now
    for lock in list(_HELD):
        lock.touch()


def _folder_writable(folder):
    """Can this user make a file in `folder`? Tried with a real file, removed at once (the
    only reliable answer on Windows, where the read-only attribute on a folder means nothing
    and its access list is what refuses)."""
    try:
        fd, probe = tempfile.mkstemp(prefix=".moonglade-probe-", dir=str(folder))
    except OSError:
        return False
    os.close(fd)
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


class FolderLock:
    """A folder's move lock: `.lock` made with O_EXCL, holding "<pid> <PC name> <made at>",
    touched after every step and from inside long ones (so a long move is never mistaken for
    a dead one). acquire() waits up to LOCK_WAIT_S for another holder, then raises
    MoveStopped. A lock is taken over only from a holder that is gone: on this PC, its process
    is not running (or the number now belongs to a process started after the lock was made);
    a lock another PC made (a library on a network drive) counts as alive until it has gone
    LOCK_STALE_S untouched. release() removes only a lock that still holds this one's own
    line. A folder this user cannot write in stops the start and says so."""

    def __init__(self, folder, what):
        self.path = Path(folder) / _paths.LOCK_NAME
        self.what = what
        self.held = False
        self.token = ""

    def acquire(self, wait=None):
        wait = LOCK_WAIT_S if wait is None else wait
        deadline = time.monotonic() + wait
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if self._stale():
                        os.remove(self.path)
                        continue
                except OSError:
                    continue                     # it went while we looked: try again
            except PermissionError as e:
                # Windows answers the same for a holder's lock being deleted (a moment) and a
                # folder this user cannot write in (for good): only a real file tells them apart.
                if not self.path.exists() and not _folder_writable(self.path.parent):
                    raise MoveStopped(
                        "Moonglade can't write in %s (%s), so it can't start. Make the folder "
                        "writable for you, then start Moonglade again." % (
                            self.path.parent, _reason(e)))
            except OSError as e:
                raise MoveStopped("Moonglade can't write in %s (%s), so it can't start. %s" % (
                    self.path.parent, _reason(e), _advice(e)))
            else:
                self.token = "%d %s %.3f" % (os.getpid(), _host(), time.time())
                try:
                    os.write(fd, self.token.encode("utf-8"))
                finally:
                    os.close(fd)
                self.held = True
                _HELD.append(self)
                return self
            if time.monotonic() > deadline:
                raise MoveStopped(
                    "Another Moonglade start is still tidying %s. Wait a minute, then start "
                    "Moonglade again." % self.what)
            time.sleep(0.1)

    def _stale(self):
        """True only when the holder is gone (see the class). Raises OSError when the lock
        went while we looked."""
        age = time.time() - self.path.stat().st_mtime
        try:
            parts = self.path.read_text(encoding="utf-8").split()
            pid = int(parts[0]) if parts else None
        except (ValueError, UnicodeDecodeError):
            pid = None
        if pid is None:
            return age > 2.0                     # being written: give it a moment
        host = parts[1] if len(parts) > 1 else _host()
        if host.lower() != _host().lower():
            return age > LOCK_STALE_S            # another PC's start: alive until untouched
        if not _pid_alive(pid):
            return True
        try:
            made = float(parts[2]) if len(parts) > 2 else None
        except ValueError:
            made = None
        started = _process_started(pid) if made is not None else None
        return started is not None and started > made + 2.0     # the number was reused

    def touch(self):
        if self.held:
            try:
                os.utime(self.path, None)
            except OSError:
                pass

    def release(self):
        if self.held:
            self.held = False
            if self in _HELD:
                _HELD.remove(self)
            try:
                if self.path.read_text(encoding="utf-8") == self.token:
                    os.remove(self.path)
            except (OSError, UnicodeDecodeError):
                pass

    def __enter__(self):
        return self if self.held else self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


# ---- files ------------------------------------------------------------------------------------
def _kind_of_failure(e):
    """"open" (another program has it), "full" (no space), "readonly" (the drive or the folder
    refuses this user), "refused" (Windows refused: read-only or open elsewhere), or ""."""
    if not isinstance(e, OSError):
        return ""
    win = getattr(e, "winerror", None)
    if win in (32, 33):                          # sharing / lock violation
        return "open"
    if e.errno == errno.ENOSPC or win in (39, 112):
        return "full"
    if e.errno == errno.EROFS or win == 19:      # a write-protected drive
        return "readonly"
    if isinstance(e, PermissionError):
        return "refused"
    return ""


def _reason(e):
    """Why a file step failed, in plain words."""
    return {"open": "another program has it open",
            "full": "the disk is full",
            "readonly": "the drive is read-only",
            "refused": "access was refused: it is read-only, or another program has it open",
            }.get(_kind_of_failure(e)) or getattr(e, "strerror", None) or e.__class__.__name__


def _advice(e):
    """What the person can do about it."""
    return {"open": "Close the program that has it open (an editor, OneDrive or another sync "
                    "tool, a virus scan), then start Moonglade again.",
            "full": "Free some space on that drive, then start Moonglade again.",
            "readonly": "Make the drive writable, then start Moonglade again.",
            "refused": "Check that the file and its folder aren't read-only for you and that no "
                       "other program has the file open, then start Moonglade again.",
            }.get(_kind_of_failure(e)) or "Start Moonglade again."


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            _heartbeat()
    return h.hexdigest()


def _fsync_path(p):
    try:
        with open(p, "r+b") as f:
            os.fsync(f.fileno())
    except OSError:
        pass


def _fsync_dir(d):
    """Flush a folder's entries (POSIX; Windows has no directory handle to flush)."""
    if sys.platform == "win32":
        return
    try:
        fd = os.open(str(d), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _write_bytes(p, data):
    """Write `data` to `p` whole: a temp beside it, flushed, then os.replace."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + MOVING_SUFFIX)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        _fsync_dir(p.parent)
    finally:
        _discard(tmp)


def _discard(p):
    try:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            os.remove(p)
    except OSError:
        pass


def _make_writable(p):
    """Clear a read-only attribute (Windows refuses to delete a read-only file)."""
    try:
        mode = os.stat(p).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(p, mode | stat.S_IWRITE)
    except OSError:
        pass


def _rmtree_whole(folder):
    """Delete `folder` and everything in it. A file that kept a read-only attribute when it was
    copied in (the outside-references fixer copies a shortcut with shutil.copy2, a library
    restored from read-only media) is made writable first: Windows refuses to delete a
    read-only file, and the folder would otherwise outlive every attempt. Raises OSError."""
    for dirpath, _dirs, files in os.walk(folder):
        for fn in files:
            _make_writable(os.path.join(dirpath, fn))
    shutil.rmtree(folder)


def _remove(p):
    """Delete a file or folder this module has accounted for: a source already copied and
    verified, a cache, a leftover of the app's own. A read-only attribute is cleared first,
    and a refusal is tried again REMOVE_TRIES times with a growing pause (a scanner, an
    indexer or a sync tool can hold a file for a moment). Raises _Failed, carrying the cause."""
    p = Path(p)
    last = None
    for attempt in range(REMOVE_TRIES):
        try:
            if p.is_dir() and not p.is_symlink():
                _rmtree_whole(p)
            elif p.exists() or p.is_symlink():
                _make_writable(p)
                os.remove(p)
            return
        except FileNotFoundError:
            return
        except PermissionError as e:
            last = e
            if attempt + 1 < REMOVE_TRIES:
                time.sleep(REMOVE_BACKOFF_S * (2 ** attempt))
        except OSError as e:
            raise _Failed("couldn't remove %s (%s)" % (p, _reason(e)), e)
    raise _Failed("couldn't remove %s (%s)" % (p, _reason(last)), last)


def _same(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def _db_counts(p):
    """{table: rows} for a SQLite file that passes PRAGMA integrity_check, else None."""
    con = None
    try:
        con = sqlite3.connect(str(p))
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return None
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
                for t in tables}
    except sqlite3.Error:
        return None
    finally:
        if con is not None:
            con.close()


def _copy_into(src, tmp, kind):
    """Copy `src` into the temp `tmp` (SQLite through its backup API), flushed to disk.
    Returns the kind actually used: a database that fails its own integrity check is copied
    byte for byte instead, so exactly what is there is kept."""
    _discard(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if kind == "db" and _db_counts(src) is not None:
        s = sqlite3.connect(str(src))
        try:
            d = sqlite3.connect(str(tmp))
            try:
                s.backup(d)
            finally:
                d.close()
        finally:
            s.close()
        _fsync_path(tmp)
        _keep_times(src, tmp)
        return "db"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        for chunk in iter(lambda: fi.read(1 << 20), b""):
            fo.write(chunk)
            _heartbeat()
        fo.flush()
        os.fsync(fo.fileno())
    _keep_times(src, tmp)
    return "file"


def _keep_times(src, dest):
    """Give a copy its source's modified time. "Keep the newer copy" compares the two copies'
    real times; a copy stamped with the moment it was made would always look newer."""
    try:
        st = os.stat(src)
        os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass


def _same_volume(src, dest_folder):
    """Are `src` and the folder `dest_folder` on one volume? Then a move is one rename."""
    try:
        a, b = os.stat(src).st_dev, os.stat(dest_folder).st_dev
    except OSError:
        return False
    return a == b and a != 0


def _verified(src, src_hash, tmp, kind):
    """Re-read the flushed copy: the same sha256 as the source, or for a database a clean
    integrity check and the same row count in every table."""
    if kind == "db":
        a, b = _db_counts(src), _db_counts(tmp)
        return a is not None and a == b
    return _sha256(tmp) == src_hash


# 3.20's fingerprint of a file or folder (its MOVED.json `source_print`), recomputed to tell a
# copy 3.20 made from a file written since.
def _transient_320(name):
    return name.endswith((".lock", ".part")) or ".tmp" in name or ".copying-" in name


def _fingerprint_320(p):
    p = Path(p)
    if p.is_dir():
        files = newest = size = 0
        for dirpath, _dirs, filenames in os.walk(p):
            for fn in filenames:
                if _transient_320(fn):
                    continue
                st = (Path(dirpath) / fn).stat()
                files += 1
                size += st.st_size
                newest = max(newest, st.st_mtime_ns)
        return {"files": files, "newest_mtime_ns": newest, "size": size}
    st = p.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


class CopyFirst:
    """3.20's copy-first record (MOVED.json), read once. unchanged(name, old) is True when the
    old copy at `old` is still exactly what 3.20 recorded copying -- a leftover, safe to delete
    -- and False for a file written since (or one 3.20 never recorded)."""

    def __init__(self, record):
        self.path = Path(record)
        self.entries = {}
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            for e in doc.get("entries", []):
                if isinstance(e, dict) and isinstance(e.get("name"), str):
                    self.entries[e["name"]] = e
        except (OSError, ValueError, AttributeError, TypeError):
            self.entries = {}

    def unchanged(self, name, old):
        e = self.entries.get(name)
        if not e or e.get("action") not in ("copied", "kept"):
            return False
        want = e.get("source_print")
        same_then = e.get("action") != "kept" or e.get("dest_print") == want
        try:
            return want is not None and same_then and _fingerprint_320(old) == want
        except OSError:
            return False


# ---- one half's context -------------------------------------------------------------------------
class _Half:
    def __init__(self, name, folder, roots, report, lock=None):
        self.name = name
        self.folder = Path(folder)               # where the journal, lock and .snapshot live
        self.roots = roots                       # [(prefix, root)] for naming paths
        self.report = report
        self.lock = lock
        self.journal = Journal(self.folder)
        self.parked = 0
        self.snapshotted = False                 # this run's zip is made (_make_snapshot)

    def rel(self, p):
        p = Path(p)
        for prefix, root in self.roots:
            try:
                r = p.relative_to(root).as_posix()
            except ValueError:
                continue
            return prefix + r
        return str(p)

    def path_of(self, rel):
        """The path a journal key (rel()) names."""
        for prefix, root in sorted(self.roots, key=lambda t: -len(t[0])):
            if rel.startswith(prefix):
                return Path(root) / rel[len(prefix):]
        return Path(rel)

    def settle_renames(self):
        """A rename journalled as under way ("renaming") and cut short: made, when the file is
        at its new place and gone from its old one; forgotten, when it never left (the next
        move tries again). Returns True when the journal changed."""
        changed = False
        for key, entry in list(self.journal.items.items()):
            if not isinstance(entry, dict) or entry.get("state") != "renaming":
                continue
            dest, src = self.path_of(key), self.path_of(entry.get("src") or "")
            if dest.is_file() and not src.exists():
                entry.update(state="made", how="renamed")
                changed = True
            elif src.is_file() and not dest.exists():
                del self.journal.items[key]
                changed = True
        return changed

    @property
    def snapshot_dir(self):
        return self.folder / _paths.SNAPSHOT_DIRNAME

    def tick(self):
        """After each item: touch every lock this process holds (this half's, and the
        install's while the library half runs)."""
        if self.lock is not None:
            self.lock.touch()
        _heartbeat(force=True)


# ---- merges ----------------------------------------------------------------------------------
def _merge_generic(a, b):
    """`a` kept, `b` folded in: dicts by key, lists as a union in order, numbers the larger,
    booleans either; anything else stays `a`'s (telemetry's counters, maxima, sets, flags and
    day ledgers are all grow-only, so this loses nothing either side counted)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge_generic(a[k], v) if k in a else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        return list(a) + [x for x in b if x not in a]
    if isinstance(a, bool) and isinstance(b, bool):
        return a or b
    if (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and not isinstance(a, bool) and not isinstance(b, bool)):
        return max(a, b)
    return a


def _merge_achievements(a, b, b_newer):
    """seen: the union; earned_at: each feat's EARLIEST pinned date (pin-once: the first time
    it was earned); skin: the newer file's."""
    out = dict(a)
    seen = [s for s in (a.get("seen") or []) if isinstance(s, str)]
    seen += [s for s in (b.get("seen") or []) if isinstance(s, str) and s not in seen]
    out["seen"] = seen
    ea = dict(a.get("earned_at") or {})
    for k, v in (b.get("earned_at") or {}).items():
        if k not in ea or (isinstance(v, str) and isinstance(ea[k], str) and v < ea[k]):
            ea[k] = v
    out["earned_at"] = ea
    if b_newer and b.get("skin"):
        out["skin"] = b["skin"]
    return out


def _merge_guard(a, b, b_newer):
    """The training spend guard: each section's entries from both copies; where both hold one
    key, the later-armed entry. More guarding, never less."""
    out = dict(a)
    for section in set(a) | set(b):
        sa, sb = a.get(section), b.get(section)
        if not isinstance(sa, dict) or not isinstance(sb, dict):
            out[section] = sa if section in a else sb
            continue
        merged = dict(sa)
        for k, v in sb.items():
            if k not in merged:
                merged[k] = v
                continue
            try:
                at_a = float((merged[k] or {}).get("at") or 0)
                at_b = float((v or {}).get("at") or 0)
            except (AttributeError, TypeError, ValueError):
                continue
            if at_b > at_a:
                merged[k] = v
        out[section] = merged
    return out


def _merged_bytes(src, dest, kind):
    """The merged content for `dest` (bytes), or None when the two cannot be merged."""
    if kind == "lines":
        a = dest.read_text(encoding="utf-8").splitlines()
        b = src.read_text(encoding="utf-8").splitlines()
        have = set(a)
        extra = [ln for ln in b if ln not in have]
        text = "\n".join(a + extra)
        return (text + "\n" if text else "").encode("utf-8")
    if kind.startswith("json:"):
        a = json.loads(dest.read_text(encoding="utf-8"))
        b = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(a, dict) or not isinstance(b, dict):
            return None
        b_newer = src.stat().st_mtime > dest.stat().st_mtime
        if kind == "json:achievements":
            doc = _merge_achievements(a, b, b_newer)
        elif kind == "json:guard":
            doc = _merge_guard(a, b, b_newer)
        else:
            doc = _merge_generic(a, b)
        return (json.dumps(doc, indent=1) + "\n").encode("utf-8")
    return None


# ---- the safe move ------------------------------------------------------------------------------
def _park(path, half, said=True):
    """Move `path` aside into the half's .snapshot\\parked\\ (copied, verified, then removed:
    the park may be on another volume). Kept until the snapshot goes. `said`: log the
    two-copies line (a caller with its own words passes False)."""
    path = Path(path)
    base = half.snapshot_dir / PARKED_DIRNAME / half.rel(path).replace(":", "_")
    target, n = base, 1
    while target.exists():
        n += 1
        target = base.with_name("%s.%d" % (base.name, n))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + MOVING_SUFFIX)
    src_hash = _sha256(path)
    _copy_into(path, tmp, "file")
    if _sha256(tmp) != src_hash:
        _discard(tmp)
        raise _Failed("couldn't set %s aside (the copy did not match)" % path)
    os.replace(tmp, target)
    _remove(path)
    half.parked += 1
    half.report.parked += 1
    half.journal.worked()
    if said:
        half.report.warn("Two different copies of %s: kept the newer one and set the other "
                         "aside in %s.", half.rel(path), half.rel(target))
    else:
        half.report.item("Set aside %s in %s.", half.rel(path), half.rel(target))
    return target


def _replace_with(dest, data, half, key, src_hash):
    """Write merged bytes over `dest` safely and record the move made it."""
    tmp = dest.with_name(dest.name + MOVING_SUFFIX)
    _discard(tmp)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if tmp.read_bytes() != data:
        _discard(tmp)
        raise _Failed("couldn't write the merged %s" % dest)
    half.journal.items[key] = {"src": None, "src_sha256": src_hash,
                               "sha256": hashlib.sha256(data).hexdigest(),
                               "state": "verified", "time": _now(), "merged": True}
    half.journal.save()
    os.replace(tmp, dest)
    _fsync_dir(dest.parent)
    half.journal.items[key]["state"] = "made"
    half.journal.save()


def _merged_log(src, dest):
    """Two copies of one log: one file, the older copy's lines first. A copy that the other
    simply continues is the other; nothing either holds is lost to the snapshot."""
    s_st, d_st = src.stat(), dest.stat()
    older, newer = (src, dest) if s_st.st_mtime <= d_st.st_mtime else (dest, src)
    a, b = older.read_bytes(), newer.read_bytes()
    if b.startswith(a):
        return b
    if a.startswith(b):
        return a
    return a + (b"\n" if a and not a.endswith(b"\n") else b"") + b


def _two_copies(src, dest, kind, half, vouched):
    """Both the old place and the new hold the item. Returns what was done. "Newer" is each
    copy's own modified time: the move keeps a copy's time (_keep_times), so a copy it made
    is as old as what it copied."""
    key = half.rel(dest)
    entry = half.journal.items.get(key) or {}
    item = half.report.item
    src_hash = _sha256(src)
    if vouched:
        _remove(src)
        item("Removed %s: 3.20 had already copied it to %s.", half.rel(src), half.rel(dest))
        return "removed"
    dest_hash = _sha256(dest)
    made = entry.get("state") == "made" or (entry.get("state") == "verified"
                                            and entry.get("sha256") == dest_hash)
    if made and entry.get("src_sha256") == src_hash:
        if entry.get("state") != "made":     # it died between the swap and the journal
            half.journal.items[key]["state"] = "made"
            half.journal.save()
        _remove(src)                         # the move's own source, not yet deleted
        item("Removed %s: it was already moved to %s.", half.rel(src), half.rel(dest))
        return "removed"
    if src_hash == dest_hash:
        _remove(src)                         # the same bytes: nothing to lose
        item("Removed %s: %s holds the same.", half.rel(src), half.rel(dest))
        return "removed"
    if kind == "cache":
        _remove(src)                         # rebuildable either way
        item("Removed %s: a cache, made again when it is needed.", half.rel(src))
        return "removed"
    if kind == "token":
        # Two Mirror sign-ins: the newer is the live one; a stale token is never parked.
        if src.stat().st_mtime > dest.stat().st_mtime:
            _remove(dest)
            return _bring(src, dest, kind, half)
        _remove(src)
        item("Removed an older Mirror sign-in at %s.", half.rel(src))
        return "removed"
    data = None
    try:
        if kind == "log":
            data = _merged_log(src, dest)
        elif kind == "lines" or kind.startswith("json:"):
            data = _merged_bytes(src, dest, kind)
    except (OSError, ValueError, UnicodeDecodeError):
        data = None
    if data is not None:
        _replace_with(dest, data, half, key, src_hash)
        _remove(src)
        item("Merged %s into %s.", half.rel(src), half.rel(dest))
        return "merged"
    # Anything else: keep the newer, park the other.
    if src.stat().st_mtime > dest.stat().st_mtime:
        _park(dest, half)
        return _bring(src, dest, kind, half)
    _park(src, half)
    return "parked"


def _rename_into(src, dest):
    """Move `src` to a `dest` that does not exist yet with one rename, never over a file that
    appeared meanwhile. Raises OSError when it cannot (another volume, a file system without
    the call): the caller copies instead."""
    if sys.platform == "win32":
        os.rename(src, dest)                 # Windows refuses an existing destination
        return
    os.link(src, dest)                       # refuses an existing destination
    try:
        os.remove(src)
    except OSError:
        pass                                 # the same file twice: the next start removes it


def _bring(src, dest, kind, half, vouched=False):
    """Bring the file `src` to `dest` (see the module's rules). On one volume that is one
    rename (the art pack, a Loom export: nothing is copied); across volumes, or for a
    database, the safe copy: temp, verify, swap, then delete the source. Either way the
    journal says so first. Returns "moved", "removed", "merged", "parked", or None when there
    was nothing at `src`. Raises _Failed."""
    src, dest = Path(src), Path(dest)
    tmp = dest.with_name(dest.name + MOVING_SUFFIX)
    _discard(tmp)                            # a crashed run's own temp
    try:
        key = half.rel(dest)
        if not src.is_file() or _same(src, dest):
            return None
        half.report.worked[half.name] = True
        if dest.exists():
            return _two_copies(src, dest, kind, half, vouched)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if kind != "db" and _same_volume(src, dest.parent):
            half.journal.items[key] = {"src": half.rel(src), "state": "renaming",
                                       "time": _now()}
            half.journal.save()
            try:
                _rename_into(src, dest)
            except OSError:
                half.journal.items.pop(key, None)        # copy it instead, below
            else:
                _fsync_dir(dest.parent)
                half.journal.items[key].update(state="made", how="renamed")
                half.journal.save()
                half.tick()
                half.report.item("Moved %s to %s.", half.rel(src), half.rel(dest))
                return "moved"
        src_hash = _sha256(src)
        used = _copy_into(src, tmp, kind)
        if not _verified(src, src_hash, tmp, used):
            _discard(tmp)
            raise _Failed("the copy of %s did not match it" % src)
        half.journal.items[key] = {"src": half.rel(src), "src_sha256": src_hash,
                                   "sha256": _sha256(tmp), "state": "verified",
                                   "time": _now()}
        half.journal.save()
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
        half.journal.items[key]["state"] = "made"
        half.journal.save()
        _remove(src)
        half.tick()
        half.report.item("Moved %s to %s (copied, checked, then removed from the old place).",
                         half.rel(src), half.rel(dest))
        return "moved"
    except _Failed:
        raise
    except (OSError, sqlite3.Error) as e:
        _discard(tmp)
        raise _Failed("couldn't move %s (%s)" % (src, _reason(e)),
                      e if isinstance(e, OSError) else None)


def _bring_or_say(src, dest, kind, half, vouched=False):
    """_bring(), except that an old log that cannot be moved (a process still holding it open)
    never stops a start: nothing reads a log's old place, the new log starts in local/logs/,
    and the next start tries again. Every other item that cannot be moved stops the start."""
    try:
        return _bring(src, dest, kind, half, vouched=vouched)
    except _Failed as e:
        if kind != "log":
            raise
        half.report.warn("An old log could not be moved yet (%s); it is tried again at the "
                         "next start.", e)
        return None


def _copy_new(src, dest):
    """Copy `src` to a `dest` that does not exist yet, safely (temp, verify, swap); the source
    stays. Raises _Failed."""
    tmp = dest.with_name(dest.name + MOVING_SUFFIX)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        h = _sha256(src)
        _copy_into(src, tmp, "file")
        if _sha256(tmp) != h:
            raise _Failed("the copy of %s did not match it" % src)
        os.replace(tmp, dest)
    except OSError as e:
        raise _Failed("couldn't copy %s (%s)" % (src, _reason(e)), e)
    finally:
        _discard(tmp)


def _files_under(folder):
    """Every file under `folder`, sorted, transients included (the caller decides)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for fn in files:
            out.append(Path(dirpath) / fn)
    return sorted(out)


def _prune_empty(folder):
    """Remove `folder` and the folders under it that hold nothing at all."""
    folder = Path(folder)
    if not folder.is_dir():
        return
    for dirpath, _dirs, _files in sorted(os.walk(folder), key=lambda t: -len(t[0])):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


# ---- the snapshot -------------------------------------------------------------------------------
def _make_snapshot(half, members, extra=None):
    """Zip `members` [(path, name in the zip)] (and `extra` {name: bytes}) into the half's
    .snapshot\\ before this run moves, removes or parks anything: once per run that has work,
    not once per journal, so a sweep made long after the first move (a file written back by an
    older install, one restored from an old backup) is in a zip too. A database goes in
    through SQLite's backup API."""
    if half.snapshotted or (not members and not extra):
        return
    half.snapshotted = True
    snap = half.snapshot_dir
    snap.mkdir(parents=True, exist_ok=True)
    stem = "before-the-move-%s" % time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    name, n = stem + ".zip", 1
    while (snap / name).exists():            # two runs in one second: never over a zip
        n += 1
        name = "%s-%d.zip" % (stem, n)
    target = snap / name
    tmp = target.with_name(target.name + MOVING_SUFFIX)
    count = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, arc in members:
                path = Path(path)
                if not path.is_file():
                    continue
                if path.suffix == ".db":
                    dbtmp = snap / (path.name + ".snapshot-copy")
                    try:
                        _copy_into(path, dbtmp, "db")
                        zf.write(dbtmp, arc)
                    finally:
                        _discard(dbtmp)
                else:
                    zf.write(path, arc)
                count += 1
            for arc, data in (extra or {}).items():
                zf.writestr(arc, data)
                count += 1
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as e:
        _discard(tmp)
        raise _Failed("couldn't make the safety snapshot in %s (%s)" % (snap, _reason(e)),
                      e if isinstance(e, OSError) else None)
    half.journal.doc["snapshot"] = {"made": _now(), "zip": name, "files": count}
    half.journal.worked()
    half.journal.save()
    half.report.info("Saved a safety copy of %d small file(s) in %s before moving them.",
                     count, half.rel(target))


def count_clean_start(folder, report):
    """One clean server start for the half whose folder is `folder`. The server calls this
    once it has served for a while, or when it is stopped cleanly -- never prepare(): a
    server that refused its port, or crashed as it started, has proved nothing. The first
    such start after a run that moved anything is not counted (that run set skip_next).
    At CLEAN_STARTS the app deletes the half's WHOLE .snapshot\\ -- the zip, anything parked
    beside it, and the copies the outside-references fixer saved in local\\.snapshot\\outside\\
    (moonglade.outside). A fix made later resets the count (reset_clean_starts), so its copies
    go CLEAN_STARTS clean starts on. The caller holds the folder's lock. Never raises."""
    try:
        journal = Journal(folder)
        snap = Path(folder) / _paths.SNAPSHOT_DIRNAME
        if not journal.doc.get("finished"):
            return
        if journal.doc.get("skip_next"):
            journal.doc["skip_next"] = False
            journal.save()
            return
        if not snap.exists():
            return
        n = int(journal.doc.get("clean_starts") or 0) + 1
        if n >= CLEAN_STARTS:
            _rmtree_whole(snap)
            journal.doc["clean_starts"] = 0
            if isinstance(journal.doc.get("snapshot"), dict):
                journal.doc["snapshot"]["removed"] = _now()
            report.info("Deleted the safety copy in %s after %d clean starts.", snap,
                        CLEAN_STARTS)
        else:
            journal.doc["clean_starts"] = n
        journal.save()
    except (OSError, ValueError, TypeError):
        pass


def reset_clean_starts(folder, wait=2.0):
    """Something new went into `folder`'s .snapshot\\ (the outside-references fixer's copy of
    a shortcut or a task): count CLEAN_STARTS clean starts again from here, so the copy is
    not deleted at the very next one. Takes the folder's lock briefly; a busy lock skips it.
    Never raises."""
    try:
        with FolderLock(folder, "the app folder").acquire(wait=wait):
            journal = Journal(folder)
            if journal.doc.get("clean_starts"):
                journal.doc["clean_starts"] = 0
                journal.save()
    except (MoveStopped, OSError, ValueError, TypeError):
        pass


# ---- config.json and serve.txt ------------------------------------------------------------------
def _read_config_strict():
    """(document, state) of config.json: state "ok", "missing" or "corrupt"."""
    p = _paths.config_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, "missing"
    except OSError:
        return {}, "corrupt"
    try:
        doc = json.loads(raw)
    except ValueError:
        return {}, "corrupt"
    return (doc, "ok") if isinstance(doc, dict) else ({}, "corrupt")


def logins_from_config():
    """The login names in config.json's AUTH_USERS, or None when they cannot be known (no
    readable config.json). The per-login moves use this to fold and to drop orphans."""
    doc, state = _read_config_strict()
    if state != "ok":
        return None
    users = doc.get("AUTH_USERS")
    if not isinstance(users, list):
        return []
    return [str(u["username"]) for u in users
            if isinstance(u, dict) and isinstance(u.get("username"), str) and u["username"]]


def parse_serve_txt(text):
    """What a serve.txt said, the way the old launcher read it (split on whitespace):
    {"out", "host", "port", "launch_args", "dropped"}. The library, host and port become their
    own settings; the switches in moonglade.settings.LAUNCH_FLAGS become launch_args; one-shot
    and unknown flags (with any value after them) are dropped and named in "dropped"."""
    from moonglade import settings as _settings
    toks = str(text or "").split()
    got = {"out": None, "host": None, "port": None, "launch_args": [], "dropped": []}
    i = 0
    while i < len(toks):
        t = toks[i]
        flag, eq, val = t.partition("=")
        if flag in ("--out", "--host", "--port"):
            if not eq:
                val = toks[i + 1] if i + 1 < len(toks) else ""
                i += 1
            got[flag[2:]] = val
        elif t in _settings.LAUNCH_FLAGS:
            if t not in got["launch_args"]:
                got["launch_args"].append(t)
        else:
            dropped = [t]
            if t.startswith("-") and not eq and i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                dropped.append(toks[i + 1])
                i += 1
            got["dropped"].append(" ".join(dropped))
        i += 1
    return got


def _first(paths):
    for p in paths:
        if Path(p).is_file():
            return Path(p)
    return None


def _plan_merge(sources, cfg, current, resume=None):
    """What the settings merge stores, without storing it: (merged {key: value}, lines
    [(level, line)]).

    A NEW merge folds serve.txt, config.json's app-written keys, branding.json and
    branding_slots.json together. For the library, host and port the value the old version
    actually used wins: the serve.txt flag (the old launcher passed it, and an explicit flag
    always won), then the config.json key, then what settings.json already held. The losing
    values go to the log only.

    A RESUME (`resume`: the values a merge journalled before it was cut short) reads nothing
    from those old places as a choice: settings.json already holds what the merge decided, and
    it wins over whatever config.json or serve.txt still says (X2: a LIBRARY_DIR left behind
    by a cut-short merge must never beat the library serve.txt pinned). A value the journal
    holds and settings.json has lost is put back."""
    from moonglade import settings as _settings
    serve = _first(sources["serve.txt"])
    flags = parse_serve_txt(serve.read_text(encoding="utf-8", errors="replace")) if serve \
        else parse_serve_txt("")
    merged, lines = {}, []

    def note(msg, *args):
        lines.append((logging.INFO, msg % args if args else msg))

    def _port_ok(v):
        try:
            return 1 <= int(v) <= 65535
        except (TypeError, ValueError):
            return False

    contests = (
        (_settings.LIBRARY_DIR, "library folder",
         [("serve.txt --out", flags["out"]),
          ("config.json LIBRARY_DIR", str(cfg.get("LIBRARY_DIR") or "").strip() or None)],
         lambda v: True),
        (_settings.HOST, "host", [("serve.txt --host", flags["host"]),
                                  ("config.json HOST", cfg.get("HOST"))], lambda v: True),
        (_settings.PORT, "port", [("serve.txt --port", flags["port"]),
                                  ("config.json PORT", cfg.get("PORT"))], _port_ok),
    )

    if resume is not None:
        for k, v in resume.items():
            if k not in current:
                merged[k] = v
        for key, label, candidates, _valid in contests:
            have = current.get(key, resume.get(key))
            for where, v in candidates:
                if v not in (None, "") and have not in (None, "") and str(v) != str(have):
                    note("The %s from %s (%s) was not used: settings.json holds %s.",
                         label, where, v, have)
        return merged, lines

    for key, label, candidates, valid in contests:
        live = [(where, v) for where, v in candidates if v not in (None, "") and valid(v)]
        if not live:
            continue
        where, v = live[0]
        for w2, v2 in live[1:] + [("settings.json", current.get(key))]:
            if v2 not in (None, "") and str(v2) != str(v):
                note("The %s from %s (%s) was not used: %s wins (%s).", label, w2, v2, where, v)
        merged[key] = int(v) if key == _settings.PORT else v
    if serve is not None:
        merged[_settings.LAUNCH_ARGS] = list(flags["launch_args"])
        for d in flags["dropped"]:
            note("serve.txt's \"%s\" was dropped: it is not a setting that lasts.", d)
    if "BONJOUR_ENABLED" in cfg or "BONJOUR_NAME" in cfg:
        b = dict(current.get(_settings.BONJOUR) or {})
        if "BONJOUR_ENABLED" in cfg:
            b["enabled"] = bool(cfg["BONJOUR_ENABLED"])
        if cfg.get("BONJOUR_NAME"):
            b["name"] = str(cfg["BONJOUR_NAME"])
        merged[_settings.BONJOUR] = b
    if "MIRROR_TO_PIXAI" in cfg:
        merged[_settings.MIRROR_TO_PIXAI] = bool(cfg["MIRROR_TO_PIXAI"])
    branding = dict(current.get(_settings.BRANDING) or {})
    bj = _first(sources["branding.json"])
    if bj is not None:
        try:
            raw = json.loads(bj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            if raw.get("mark"):
                branding["mark"] = str(raw["mark"])
            anim = {k: raw[k] for k in ("anim", "anim_speed", "anim_scale", "glow_color",
                                        "glow_angle") if k in raw}
            if anim:
                branding["animation"] = anim
    bs = _first(sources["branding_slots.json"])
    if bs is not None:
        try:
            raw = json.loads(bs.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            branding["slots"] = {str(k): str(v) for k, v in raw.items() if v}
    if bj is not None or bs is not None:
        merged[_settings.BRANDING] = branding
    return merged, lines


def _store_merge(half, merged, lines, report):
    """Write `merged` into settings.json and check it held. Raises _Failed."""
    from moonglade import settings as _settings
    for level, line in lines:
        report.lines.append((level, line))
    if merged:
        def _apply(doc):
            doc.update(merged)
        _settings.update(_apply)
        check = _settings.read()
        for k, v in merged.items():
            if check.get(k) != v:
                raise _Failed("settings.json did not keep %s" % k)
        report.info("Settings brought into %s: %s.", half.rel(_paths.settings_path()),
                    ", ".join(sorted(merged)))


def _merge_inputs(local, old):
    """The old places' settings files ({name: [paths, the live one first]}) and config.json
    ((document, state))."""
    sources = {name: [p for p in (local / name, old / name) if p.is_file()]
               for name in SETTINGS_FILES}
    return sources, _read_config_strict()


def _merge_state(journal, sources, cfg_keys):
    """The journalled settings merge ({"state", "values"}), or {} when none is under way. A
    merge is under way while its state is "merged" (settings.json written) or "keys_dropped"
    (config.json's keys gone, the old files not yet); "done" means the last one finished. An
    earlier build's bare `settings_merged` stamp, with old settings still about, counts as a
    merge under way: what settings.json holds wins."""
    merge = journal.doc.get("merge")
    if isinstance(merge, dict) and merge.get("state") in ("merged", "keys_dropped", "done"):
        return merge
    if journal.doc.get("settings_merged") and (any(sources.values()) or cfg_keys):
        return {"state": "merged", "values": {}}
    return {}


def planned_settings():
    """settings.json as it will be once this install's settings merge has run, without
    running it: what is stored, plus what serve.txt and config.json's app-written keys will
    bring (or, for a merge cut short, what it journalled). The launcher's and the server's
    port check reads this before prepare() (S1), so a second start never moves anything under
    a live one. Never raises and never writes; {} when nothing can be read."""
    from moonglade import settings as _settings
    try:
        current = _settings.read()
        local, old = _paths.local_dir(), old_app_root()
        sources, (cfg, cfg_state) = _merge_inputs(local, old)
        cfg_keys = [k for k in CONFIG_MOVED_KEYS if k in cfg]
        merge = _merge_state(Journal(local), sources, cfg_keys)
        resuming = merge.get("state") in ("merged", "keys_dropped")
        if not (resuming or any(sources.values()) or cfg_keys):
            return current
        merged, _lines = _plan_merge(sources, cfg if cfg_state == "ok" else {}, current,
                                     resume=(merge.get("values") or {}) if resuming else None)
        out = dict(current)
        out.update(merged)
        return out
    except Exception:                                   # noqa: BLE001 -- a guess at a port
        return {}


def _drop_config_keys(report):
    """Remove the moved keys from config.json with its own atomic writer, under the lock every
    config.json writer holds. Returns False when config.json will not parse (it is then left
    alone). Raises _Failed."""
    from moonglade import backup as _core
    with _core._accounts_lock:
        doc, state = _read_config_strict()
        if state == "missing":
            return True
        if state != "ok":
            return False
        gone = [k for k in CONFIG_MOVED_KEYS if k in doc]
        if not gone:
            return True
        for k in gone:
            doc.pop(k, None)
        try:
            _core._save_config(doc)
        except OSError as e:
            raise _Failed("couldn't update config.json (%s)" % _reason(e), e)
    if len(gone) == 1:
        report.info("Removed %s from config.json: it lives in settings.json now.", gone[0])
    else:
        report.info("Removed %s from config.json: they live in settings.json now.",
                    ", ".join(gone))
    return True


def _save_quietly(journal):
    try:
        journal.save()
    except OSError:
        pass


def _stopped(where, e):
    """The sentence for a move that could not finish: what failed, then what to do."""
    cause = e.cause if isinstance(e, _Failed) else (e if isinstance(e, OSError) else None)
    return "Moonglade couldn't finish tidying %s: %s. Nothing was lost. %s" % (
        where, e, _advice(cause))


# ---- the install half -------------------------------------------------------------------------
def migrate_install(report, lock=None):
    """The install half. The caller holds local\\'s lock. Raises MoveStopped."""
    local = _paths.local_dir()
    old = old_app_root()
    half = _Half("install", local, [("local/", local), ("", old)], report, lock)
    copyfirst = CopyFirst(local / OLD_RECORD)
    try:
        _install_half(half, local, old, copyfirst, report)
    except (_Failed, OSError, sqlite3.Error, RuntimeError) as e:
        if isinstance(e, MoveStopped):
            raise
        _save_quietly(half.journal)
        raise MoveStopped(_stopped("its folder", e))
    return half


def _install_half(half, local, old, copyfirst, report):
    j = half.journal
    if not j.doc.get("started"):
        j.doc["started"] = _now()
    if half.settle_renames():
        j.save()
    sources, (cfg, cfg_state) = _merge_inputs(local, old)
    cfg_keys = [k for k in CONFIG_MOVED_KEYS if k in cfg]
    merge = _merge_state(j, sources, cfg_keys)
    resuming = merge.get("state") in ("merged", "keys_dropped")
    pending_merge = resuming or any(sources.values()) or bool(cfg_keys)
    if cfg_state == "corrupt" and (resuming or not (merge or j.doc.get("settings_merged"))):
        raise MoveStopped("config.json can't be read, so Moonglade can't bring its settings "
                          "across. Fix or restore config.json, then start Moonglade again.")

    # The pre-v7 pack rename, at the old place, so the move below carries the renamed pack.
    from moonglade import assets as _assets
    if not _same(old, local) and (old / _assets.LEGACY_NAME).is_file():
        _assets.migrate_legacy_name(old / PACK_NAME)

    # What else is there: (source, destination, kind).
    moves = []
    if not _same(old, local):
        moves.append((old / PACK_NAME, local / PACK_NAME, "pack"))
    mirror_srcs = [_paths.config_path().parent / _paths.MIRROR_SESSION_NAME,
                   old / _paths.MIRROR_SESSION_NAME]
    for src in mirror_srcs:
        moves.append((src, local / _paths.MIRROR_SESSION_NAME, "token"))
    for name in LAUNCHER_LOGS:
        for src in (local / name, old / name):
            moves.append((src, _paths.logs_dir() / name, "log"))
    old_icon_dirs = [old / OLD_ICON_CACHE / "marks", local / "cache" / "marks"]
    for d in old_icon_dirs:
        for ico in _files_under(d):
            if ico.suffix.lower() == ".ico":
                moves.append((ico, _paths.icons_dir() / ico.name, "cache"))
    leftovers = [p for p in (local / OLD_RECORD, local / OLD_LOCK, old / OLD_ICON_CACHE,
                             local / "cache" / "marks")
                 if p.exists() and not _same(p, local)]
    # The app's own dead files at the install root (S9): never left for the person to delete.
    dead = [old / n for n in DEAD_ROOT_FILES if (old / n).is_file()]
    stray_db = old / "catalog.db"
    try:
        if stray_db.is_file() and stray_db.stat().st_size == 0:
            dead.append(stray_db)                # an empty stray, never a real catalog
    except OSError:
        pass
    same_folder = _same(old, local)
    stray_marker = old / PACK_MARKER
    has_work = (pending_merge or leftovers or dead
                or (not same_folder and stray_marker.is_file())
                or any(Path(s).is_file() and not _same(s, d) for s, d, _k in moves))
    if not has_work:
        if not j.doc.get("finished"):
            j.finish()
        return
    report.worked["install"] = True
    j.worked()

    # The safety snapshot: the small settings files about to go, and the config keys.
    members = []
    for name, paths in sources.items():
        for p in paths:
            members.append((p, half.rel(p)))
    if (local / OLD_RECORD).is_file():
        members.append((local / OLD_RECORD, "local/" + OLD_RECORD))
    for p in dead:
        if p.stat().st_size:
            members.append((p, half.rel(p)))
    extra = {}
    if cfg_keys:
        extra["config.json (the keys moved to settings.json).json"] = json.dumps(
            {k: cfg[k] for k in cfg_keys}, indent=2).encode("utf-8")
    _make_snapshot(half, members, extra)

    # 1. The settings merge, journalled step by step (X2): settings.json written, then
    # config.json's moved keys dropped, then the old files deleted. A start cut short between
    # two steps resumes from the next one, and what settings.json holds wins from then on.
    if pending_merge:
        from moonglade import settings as _settings
        if not resuming:
            merged, lines = _plan_merge(sources, cfg if cfg_state == "ok" else {},
                                        _settings.read())
            _store_merge(half, merged, lines, report)
            merge = {"state": "merged", "values": merged, "at": _now()}
            j.doc["merge"] = merge
            j.save()
        else:
            merged, lines = _plan_merge(sources, cfg if cfg_state == "ok" else {},
                                        _settings.read(), resume=merge.get("values") or {})
            _store_merge(half, merged, lines, report)
            j.doc["merge"] = merge
        if merge["state"] == "merged":
            if not _drop_config_keys(report):
                raise MoveStopped("config.json can't be read, so Moonglade can't finish "
                                  "bringing its settings across. Fix or restore config.json, "
                                  "then start Moonglade again.")
            merge["state"] = "keys_dropped"
            j.save()
        for name, paths in sources.items():
            if not paths:
                continue
            primary = paths[0]
            for p in paths[1:]:
                if copyfirst.unchanged(name, p) or _sha256(p) == _sha256(primary):
                    _remove(p)
                    report.item("Removed %s: the same as %s.", half.rel(p), half.rel(primary))
                else:
                    _park(p, half)
            _remove(primary)
            report.item("Removed %s: what it held is in local/settings.json now.",
                        half.rel(primary))
        merge["state"] = "done"
        j.doc["settings_merged"] = _now()
        j.save()
        half.tick()

    # 2. The art pack and its marker: the marker describes one pack's bytes, so it moves only
    # with its own pack.
    if not same_folder:
        old_pack, new_pack = old / PACK_NAME, local / PACK_NAME
        if old_pack.is_file() and new_pack.is_file():
            _remove(old_pack)
            if stray_marker.is_file():
                _remove(stray_marker)
            report.info("Removed an older copy of the art pack from the app folder; the one in "
                        "local/ is used.")
        elif old_pack.is_file():
            if (local / PACK_MARKER).is_file():
                _remove(local / PACK_MARKER)     # a marker whose pack is not there
            moved = _bring(old_pack, new_pack, "file", half)
            if moved == "moved":
                report.info("Moved the art pack into local/.")
                if stray_marker.is_file():
                    _bring(stray_marker, local / PACK_MARKER, "file", half)
        elif stray_marker.is_file():
            pack_made = (j.items.get(half.rel(new_pack)) or {}).get("state") == "made"
            if pack_made and new_pack.is_file() and not (local / PACK_MARKER).exists():
                # The pack came across and the start was cut short before its marker did:
                # the marker still describes it, so it follows (no re-download).
                _bring(stray_marker, local / PACK_MARKER, "file", half)
            else:
                _remove(stray_marker)            # a few bytes about a pack that is not there

    # 3. The Mirror's sign-in, the launcher's logs, the shortcut icons.
    for src, dest, kind in moves:
        if kind == "pack":
            continue
        _bring_or_say(src, dest, kind, half)
    for p in leftovers:
        if p.exists():
            _remove(p)
            report.item("Removed %s: an older version's bookkeeping or icon cache.", half.rel(p))
    for p in dead:
        if p.exists():
            _remove(p)
            report.info("Removed %s from the app folder: nothing uses it any more.", p.name)
    j.finish()
    report.info("The app folder is tidy: settings in local/settings.json, logs in "
                "local/logs/, shortcut icons in local/icons/.")


# ---- the library half -------------------------------------------------------------------------
def _library_roots(out):
    return [("", Path(out)), ("local/", _paths.local_dir())]


def migrate_library(out_dir, logins, report, lock=None):
    """The library half for `out_dir`. The caller holds the library's lock, and has made sure
    this start may move this library's files (prepare_library). `logins`: the login names
    (logins_from_config()), or None when unknown. Raises MoveStopped."""
    out = Path(out_dir)
    app = _paths.library_app_dir(out)
    half = _Half("library", app, _library_roots(out), report, lock)
    copyfirst = CopyFirst(app / OLD_RECORD)
    try:
        _library_half(half, out, app, copyfirst, logins, report)
    except (_Failed, OSError, sqlite3.Error, RuntimeError) as e:
        if isinstance(e, MoveStopped):
            raise
        _save_quietly(half.journal)
        raise MoveStopped(_stopped("the library folder %s" % out, e))
    return half


class _Plan:
    def __init__(self):
        self.moves = []          # (src, dest, kind, vouched)
        self.removals = []       # files and (pruned once empty) folders
        self.parks = []          # stray logs, set aside beside the snapshot
        self.dead = []           # the library's dead branding\ files, set aside, then gone
        self.kept = []           # per-login files no login can be found for: left, and said
        self.snap = []           # (path, name in the zip)


def _plain_name_login(name, logins):
    """(login, rest) for a per-login file named by the login's own name, the way the stores
    named them before the hashed keys (quote(login, safe="") + "." + rest), or None. The
    longest matching name wins ("Nel.Smith.json" is Nel.Smith's, not Nel's). A name that
    matches one login only when case is ignored is that login's (on NTFS the file was that
    login's whichever way it was spelled); two such logins ("Nel", "nel") are a guess, and
    nothing is decided on a guess."""
    if not logins:
        return None
    named = sorted(((_quote(u, safe=""), u) for u in logins), key=lambda t: -len(t[0]))
    for q, u in named:
        if name.startswith(q + ".") and len(name) > len(q) + 1:
            return u, name[len(q) + 1:]
    loose = [(q, u) for q, u in named
             if name.lower().startswith(q.lower() + ".") and len(name) > len(q) + 1]
    if len({u for _q, u in loose}) == 1:
        q, u = loose[0]
        return u, name[len(q) + 1:]
    return None


def _plan_library(out, app, copyfirst, logins, half):
    plan = _Plan()
    reports = app / OLD_REPORTS

    def two(name, primary, secondary, dest, kind, vouch_name=None):
        if primary.is_file():
            plan.moves.append((primary, dest, kind, False))
            plan.snap.append((primary, half.rel(primary)))
        if secondary.is_file():
            vouched = copyfirst.unchanged(vouch_name or name, secondary)
            plan.moves.append((secondary, dest, kind, vouched))
            if not vouched:
                plan.snap.append((secondary, half.rel(secondary)))

    # Records and the reports that are records (S6).
    for name, kind in RECORDS.items():
        primary = (reports if name in _REPORT_NAMES else app) / name
        two(name, primary, out / name, _paths.records_path(out, name, make=False), kind)
    # The owner's decisions.
    for name, kind in DECISIONS.items():
        two(name, reports / name, out / name, _paths.decisions_path(out, name, make=False), kind)
    for folder in (reports, out):
        try:
            snaps = sorted(folder.glob(CURATION_SNAPSHOT_PREFIX + "*.json"))
        except OSError:
            snaps = []
        for p in snaps:
            vouched = folder == out and copyfirst.unchanged(p.name, p)
            plan.moves.append((p, _paths.decisions_path(out, p.name, make=False), "file",
                               vouched))
            plan.snap.append((p, half.rel(p)))
    # Per-login stores. Every login key's files move into accounts\<key>\ -- this install's
    # logins or not: another install may share the library, and nothing per-login is deleted
    # on a guess (X3; only removing a login deletes its folder). A file named by a login's
    # plain name (before the hashed keys) goes to that login's folder when the login is known
    # (S8); one no login can be found for stays where it is, and the log says so.
    for old_name, new_stem in PER_LOGIN.items():
        for base, from_320 in ((app, True), (out, False)):
            folder = base / old_name
            vouched_folder = not from_320 and copyfirst.unchanged(old_name, folder)
            for p in _files_under(folder):
                if _TRANSIENT_RE.search(p.name):
                    plan.removals.append(p)
                    continue
                key, _dot, rest = p.name.partition(".")
                if p.parent == folder and _KEY_RE.match(key) and rest:
                    dest = _paths.accounts_dir(out) / key / (new_stem + "." + rest)
                elif p.parent == folder and _plain_name_login(p.name, logins):
                    login, rest = _plain_name_login(p.name, logins)
                    dest = _paths.account_dir(out, login) / (new_stem + "." + rest)
                else:
                    plan.kept.append(p)
                    continue
                plan.snap.append((p, half.rel(p)))
                plan.moves.append((p, dest, "file", vouched_folder))
            plan.removals.append(folder)              # pruned once empty
    # The library's logs, into local\logs\.
    for base, from_320 in ((app / "logs", True), (out / "logs", False)):
        vouched_folder = not from_320 and copyfirst.unchanged("logs", base)
        for p in _files_under(base):
            if _TRANSIENT_RE.search(p.name):
                plan.removals.append(p)
            elif p.parent != base:
                plan.parks.append(p)
            else:
                plan.moves.append((p, _paths.logs_dir() / p.name, "log", vouched_folder))
        plan.removals.append(base)
    # The Loom's whole folder, into _moonglade\loom\.
    loom_old = out / "loom"
    for p in _files_under(loom_old):
        rel = p.relative_to(loom_old)
        if _TRANSIENT_RE.search(p.name):
            plan.removals.append(p)
            continue
        kind = "lines" if rel.parts[0] == "_submits" and p.suffix == ".jsonl" else "file"
        plan.moves.append((p, _paths.loom_root(out) / rel, kind, False))
        if rel.parts[0] not in _LOOM_UNSNAPPED:
            plan.snap.append((p, half.rel(p)))
    if loom_old.is_dir():
        plan.removals.append(loom_old)
    # Dead copies nothing reads: the library's old branding.json and the legacy catalog.csv
    # (in the zip, then removed), and its old branding\ folder (every file in it set aside in
    # the snapshot, so it goes with the snapshot rather than stay forever).
    for p in [out / "branding.json"] + [out / n for n in DEAD_LIBRARY_FILES]:
        if p.is_file():
            plan.snap.append((p, half.rel(p)))
            plan.removals.append(p)
    plan.dead = [p for p in _files_under(out / "branding")]
    if (out / "branding").is_dir():
        plan.removals.append(out / "branding")
    # 3.20's bookkeeping.
    for p in (app / OLD_RECORD, app / OLD_LOCK, out / "telemetry.lock", app / "telemetry.lock",
              out / "integrity_report.lock", reports / "integrity_report.lock",
              out / "jobs.jsonl.tmp", app / "jobs.jsonl.tmp"):
        if p.is_file():
            if p.name == OLD_RECORD:
                plan.snap.append((p, half.rel(p)))
            plan.removals.append(p)
    plan.removals.append(reports)
    return plan


def _shared_presets(half, out, app, copyfirst, logins, report):
    """The three install-wide preset files: copied into each login with no file of its own,
    then deleted. Left alone, with a log line, while the logins cannot be known."""
    for name, new_name in SHARED_PRESETS.items():
        paths = [p for p in (app / name, out / name) if p.is_file()]
        if not paths:
            continue
        half.report.worked["library"] = True
        if not logins:
            report.warn("%s was left where it is: there are no logins in config.json to give "
                        "it to yet.", half.rel(paths[0]))
            continue
        primary = paths[0]
        for user in logins:
            dest = _paths.account_dir(out, user) / new_name
            if not dest.exists():
                _copy_new(primary, dest)
                report.item("Copied %s to %s.", half.rel(primary), half.rel(dest))
        for p in paths[1:]:
            if copyfirst.unchanged(name, p) or _sha256(p) == _sha256(primary):
                _remove(p)
                report.item("Removed %s: the same as %s.", half.rel(p), half.rel(primary))
            else:
                _park(p, half)
        _remove(primary)
        report.info("Gave the shared %s to each login that had none of its own.", name)


def _banners(half, out, report):
    """The banner renders a library held in gallery\\cache\\_banners\\ (B6). A slot render is
    rebuilt from the pick, and an earned one from the pack (its banner id goes into
    settings.json's worn_banner): both are deleted. A migrated render, or one with no record,
    is the only copy of what the install wears: it moves whole into local\\banners\\, and
    worn_banner says so. A choice settings.json already holds is never overwritten."""
    from moonglade import settings as _settings
    folder = out / "gallery" / "cache" / "_banners"
    if not folder.is_dir():
        return
    half.report.worked["library"] = True
    worn = dict((_settings.branding().get("worn_banner") or {}))
    changed = False
    for slot, name in BANNER_FLATS.items():
        png, rec_path = folder / name, folder / (name + ".json")
        rec = None
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        kind = rec.get("kind") if isinstance(rec, dict) else None
        if not png.is_file():
            continue
        if kind == "slot":
            continue                                     # rebuilt from the pick
        if kind == "earned":
            if slot not in worn and rec.get("banner_id"):
                worn[slot] = {"kind": "earned", "banner_id": str(rec["banner_id"])}
                changed = True
            continue                                     # rebuilt from the pack
        # migrated, unrecorded, or a kind this build does not know: the only copy.
        if slot in worn:
            _park(png, half)
            continue
        _bring(png, _paths.banners_dir() / name, "file", half)
        worn[slot] = {"kind": "migrated"}
        changed = True
        report.info("Kept the banner this install wears (%s) in local/banners/.", name)
    if changed:
        _settings.update_branding(lambda b: b.__setitem__("worn_banner", worn))


def _caches(out):
    return [out / "gallery" / "cache" / c for c in LIBRARY_CACHES]


def _shared_files(out, app):
    return [p for n in SHARED_PRESETS for p in (app / n, out / n) if p.is_file()]


def _has_work(plan, shared, caches):
    """Is there anything to move, merge, set aside or remove? A folder still holding only
    what the plan leaves (a file no login can be found for, something unexpected) is not work:
    it is said once, by the start that emptied the rest, or every start would count as one
    that moved something."""
    return (any(Path(s).is_file() for s, _d, _k, _v in plan.moves)
            or any(Path(p).is_file() for p in plan.removals)
            or any(Path(p).is_dir() and not _files_under(p) for p in plan.removals)
            or bool(plan.parks) or bool(plan.dead) or bool(shared)
            or any(c.exists() for c in caches))


def _written_since(journal, plan, shared):
    """[(path, mtime_ns)] of old-layout files written after this library's move last
    finished: an older Moonglade still using the library writes its old homes (the logs and
    the records), and nothing of this version ever does."""
    since = journal.finished_at()
    if since is None:
        return []
    out = []
    for p in [s for s, _d, _k, _v in plan.moves] + list(shared):
        try:
            st = Path(p).stat()
        except OSError:
            continue
        if st.st_mtime > since + WRITTEN_SINCE_SLACK_S:
            out.append((Path(p), st.st_mtime_ns))
    return out


def _old_layout_records(plan, shared):
    """The files at old places that this version would read in a new home: every record,
    decision, per-login store and the Loom (not the logs, which nothing reads back)."""
    return [Path(s) for s, _d, k, _v in plan.moves if k != "log" and Path(s).is_file()] + \
        list(shared)


def _names(paths, half, most=3):
    rels = [half.rel(p) for p in paths]
    more = len(rels) - most
    return ", ".join(rels[:most]) + (" and %d more" % more if more > 0 else "")


def _older_live_words(out, written, half, moving):
    head = ("An older Moonglade is still using the library %s: it wrote %s after this version "
            "moved the library's files into _moonglade. " % (out, _names(written, half)))
    if moving:
        return head + ("Moving them now, while it runs, would hide its records from it. Close "
                       "that Moonglade (its window, its scheduled tasks and its Claude tools), "
                       "then start this one again: it brings in what that one wrote.")
    return head + ("This command never moves a library's files. Close that Moonglade, then "
                   "start this one with its launcher (Moonglade Launcher) to bring in what it "
                   "wrote.")


def _refusal_words(out, named):
    if named:
        return ("The library %s is still in an older Moonglade's layout, and a run that names "
                "its own library (--out or MOONGLADE_OUT) never moves one. Open it once with "
                "the launcher of the Moonglade it belongs to, updated to this version, then "
                "run this again." % out)
    return ("The library %s is still in an older Moonglade's layout. Open it once with this "
            "install's launcher (Moonglade Launcher), then run this again." % out)


def prepare_library(out_dir, report, moves, named=False, wait=None):
    """The library half as prepare() runs it (X1). `moves`: this start may move this
    library's files (a launcher or server start, in the library this install serves).

      * A library whose move finished and whose old homes were written since is in use by an
        older Moonglade: every kind of start stops and says so.
      * A start that may not move (the command line, the MCP server, a run naming its own
        library) refuses a library still in an older layout -- it would read empty new
        homes -- and otherwise changes nothing in it.
      * With nothing to do, nothing is locked: a read-only library still opens. A start that
        may move stamps the library's journal finished, when it can.
      * Otherwise the move runs under the library's lock (migrate_library).
    Raises MoveStopped."""
    out = Path(out_dir)
    app = _paths.library_app_dir(out)
    logins = logins_from_config()
    look = _Half("library", app, _library_roots(out), Report())
    plan = _plan_library(out, app, CopyFirst(app / OLD_RECORD), logins, look)
    shared = _shared_files(out, app)
    if not moves:
        written = _written_since(look.journal, plan, shared)
        if written:
            raise MoveStopped(_older_live_words(out, [p for p, _ns in written], look, False))
        if _old_layout_records(plan, shared):
            raise MoveStopped(_refusal_words(out, named))
        return None
    if not _has_work(plan, shared, _caches(out)):
        renaming = any(isinstance(e, dict) and e.get("state") == "renaming"
                       for e in look.journal.items.values())
        if not look.journal.doc.get("finished") or renaming:
            try:
                if app.is_dir() or (app.parent.is_dir() and _folder_writable(app.parent)):
                    app.mkdir(exist_ok=True)
                    lock = FolderLock(app, "the library folder %s" % out)
                    with lock.acquire(wait=2.0):
                        half = _Half("library", app, _library_roots(out), report, lock)
                        j = half.journal
                        if not j.doc.get("started"):
                            j.doc["started"] = _now()
                        half.settle_renames()
                        if not j.doc.get("finished"):
                            j.finish()
                        else:
                            j.save()
            except (MoveStopped, OSError):
                pass                             # read-only, or busy: nothing was to move
        return None
    try:
        app.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MoveStopped("Moonglade can't write in the library folder %s (%s), so it can't "
                          "bring the library's files into their new homes. %s" % (
                              out, _reason(e), _advice(e)))
    lock = FolderLock(app, "the library folder %s" % out)
    with lock.acquire(wait=wait):
        return migrate_library(out, logins, report, lock=lock)


def _library_half(half, out, app, copyfirst, logins, report):
    j = half.journal
    plan = _plan_library(out, app, copyfirst, logins, half)
    shared = _shared_files(out, app)
    caches = _caches(out)
    if not j.doc.get("started"):
        j.doc["started"] = _now()
    if half.settle_renames():
        j.save()
    if not _has_work(plan, shared, caches):
        if not j.doc.get("finished"):
            j.finish()
        return
    # An older Moonglade still on this library: stop, unless the person was told and nothing
    # more has been written there since (they closed it and started this one again).
    written = _written_since(j, plan, shared)
    if written:
        files = {half.rel(p): ns for p, ns in written}
        held = j.doc.get("held_back")
        if not isinstance(held, dict) or held.get("files") != files:
            j.doc["held_back"] = {"at": _now(), "files": files}
            j.save()
            raise MoveStopped(_older_live_words(out, [p for p, _ns in written], half, True))
        report.info("Bringing in what an older Moonglade wrote to %s after the move: %s.",
                    out, _names([p for p, _ns in written], half))
    j.doc.pop("held_back", None)
    report.worked["library"] = True
    j.worked()
    app.mkdir(parents=True, exist_ok=True)
    # The safety snapshot: the small records about to move, the shared preset files, the
    # banner renders that may be the only copy, and 3.20's record.
    snap = list(plan.snap) + [(p, half.rel(p)) for p in shared]
    bfolder = out / "gallery" / "cache" / "_banners"
    for name in BANNER_FLATS.values():
        for p in (bfolder / name, bfolder / (name + ".json")):
            if p.is_file():
                snap.append((p, half.rel(p)))
    _make_snapshot(half, snap)
    moved = 0
    for src, dest, kind, vouched in plan.moves:
        if _bring_or_say(src, dest, kind, half, vouched=vouched) == "moved":
            moved += 1
    for p in plan.parks:
        if p.is_file():
            _park(p, half)
    if plan.dead:
        parked = [p for p in plan.dead if p.is_file()]
        for p in parked:
            _park(p, half, said=False)
        if parked:
            report.info("Set aside the library's old branding folder (%s) with the safety copy: "
                        "nothing uses it any more, and it goes when the safety copy does.",
                        _names(parked, half, most=10))
    for p in plan.kept:
        if p.is_file():
            report.warn("Left %s where it is: no login in config.json goes by that name.",
                        half.rel(p))
    _shared_presets(half, out, app, copyfirst, logins, report)
    _banners(half, out, report)
    # Caches: deleted once the new home exists (they are rebuilt in local\cache\).
    _paths.cache_dir().mkdir(parents=True, exist_ok=True)
    for c in caches:
        if c.exists():
            _remove(c)
            report.item("Removed %s: a cache, made again when it is needed.", half.rel(c))
    for p in plan.removals:
        if not p.exists():
            continue
        if p.is_dir():
            _prune_empty(p)
            left = [x for x in _files_under(p) if x not in plan.kept]
            if left:
                # Only what the plan accounted for is ever removed: a folder still holding
                # something unexpected is left where it is, and said.
                report.warn("%s still holds %s; left where it is.", half.rel(p),
                            ", ".join(half.rel(x) for x in left[:10]))
            continue
        _remove(p)
        report.item("Removed %s: nothing uses it any more.", half.rel(p))
    if moved:
        report.info("Moved %d file(s) in the library %s into %s.", moved, out, half.rel(app))
    j.finish()

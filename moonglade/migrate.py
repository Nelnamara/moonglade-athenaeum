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
    journal says the move made is trusted. Every swap (_replace) waits out a refusal Windows
    gives for a moment (a scan, the indexer, OneDrive), as every delete does.
  * CONFLICTS, AT THE FIRST MOVE. A copy in the new place wins only when the journal says the
    move made it: the old copy is still the very bytes it copied (and is simply removed), or
    was written after the move made the new home -- it sits at the very old place the move
    took the home from, or its time is later than the journal's -- as when a first move cut
    short is followed by an older install writing the old homes it emptied. Such a copy is
    folded in by the rules for after the move (below), and a home the move made is never set
    aside for it. Any other two-copy case:
    JSONL and other append-only line files are merged (lines the other lacks are appended); the
    counters and sets of telemetry.json, achievements.json and the spend guard are merged where
    the format allows; anything else keeps the newer copy and parks the other in
    .snapshot\\parked\\, with a log line. Nothing is deleted on a guess. (Two copies with the
    same bytes are one.)
  * AFTER THE MOVE HAS FINISHED, THE NEW HOME ALWAYS WINS (_fold_in). An old-layout file
    written later -- by an older install still on the library, or by a version gone back to --
    holds only that install's additions (the move had emptied its homes), so it never replaces
    the new home. What it adds is folded in where the format allows: lines it lacks; JSON
    records by union, telemetry's counters at their max per key (never added: a restored
    backup of any age, or a sync tool's copy, holds counts the new home already has, and a max
    can't count them twice -- so the counts an older install makes after the move aren't
    added), the spend guard entry by entry, whichever blocks longer; runs.db (the Runs and
    their spend reservations) run by run, inside the new home itself under SQLite's write
    lock, after both files pass their integrity check -- a run both hold keeps the new home's
    rows whole, and the older copy's is named in the log; integrity_marks.json mark by mark, a
    login's stores key by key, and the Loom's cast library and boards inside the JSON text the
    Loom keeps in each file -- on a clash the new home's value stays and the older one is
    logged, except a board: one both copies changed is kept whole beside its new home under a
    key of its own, so no card or render record of either is lost. What can't be merged is set
    aside and named in the log; a Loom value that can't is kept beside its new home under a key
    of its own, outside the snapshot. When the NEW home is the side that won't read, the start
    stops and names it: the healthy older copy is never set aside.
  * THE SNAPSHOT (the owner's pick 4). Before a run moves, removes or parks anything, the small
    records it is about to touch are zipped into its half's .snapshot\\ (one zip per run that has
    work, so every later sweep is covered too) -- never pictures, catalog.db, the art pack, the
    logs, a cache, or the Mirror's sign-in (a stale token is a credential lying around). Parked
    copies go beside the zip. Once the move has finished, the journal counts clean server
    starts -- a server that served for a while, or was stopped cleanly (count_clean_start,
    called by the server, never by prepare) -- and the first one after a run that moved
    anything does not count. At CLEAN_STARTS the app deletes .snapshot\\.
  * AN OLDER INSTALL STILL LIVE. An older Moonglade still serving a library (on this PC or
    another Windows PC) holds its old log open: Windows refuses to rename it, even after a
    moment's wait, and the start stops before any record moves (_old_log_in_use) -- at the
    first move, and at every later bring-in. Once a library's move has finished, an old-layout
    file written after it also means an older Moonglade is still using that library: the start
    stops and says so, rather than sweep its records out from under it. Started again with
    nothing more written there and no old log held (the person stopped it: Stop server in its
    Control Panel, since closing its browser tab leaves it serving), the move brings in what it
    wrote, and the new homes keep everything they hold. Before the first move has finished (one
    cut short), an old-layout file written after the move made its own new home counts the
    same way. A held log is seen only when both
    installs run on Windows and open the same folder (a shared folder or a NAS share). If
    either runs on Linux or macOS, nothing is held; and a library that OneDrive, Dropbox or
    another sync tool keeps in step is a separate copy on each PC, whose log the other PC's
    install never holds. In both cases the person closes every older install first.
  * ONLY WHAT IS MOONGLADE'S, BY ITS CONTENT. An old home's name is not enough: a folder that
    isn't a Moonglade library is left exactly as it is (_is_moonglade_library), and in one that
    is, each old home passes its own check -- the logs only moonglade.log*, the Loom only its
    own entries, the old branding only Moonglade's art -- and anything else is left where it
    is, and named in the log. A library is never the program's own folder, nor one holding a
    program (library_refusal): every start refuses one, and the settings merge and the
    Control Panel never store one.
  * LINKS. A junction or a symbolic link is never walked into, copied or deleted through, and
    no tree removal follows one. A link found in an old home is moved as a link -- the link
    entry itself renamed on the same drive (_bring_link); a symbolic link whose target is
    written relative to its own folder is made again at its deeper new home with its target
    rewritten, so it still points at the same place (off Windows) -- and one that can't be
    (its new home taken or on another drive, a relative one on Windows that would have to
    change, one pointing by its full path -- every junction -- into something the same move
    takes or empties) is left where it is while the start stops with a plain sentence, before
    anything moves. Links move before any file, so a start cut short never leaves a link
    whose target's files have already gone. A cache that is a link goes as the link alone; a
    logs\\ or branding\\ that is one is left, and so is a banner cache holding a linked
    render, and anything inside a link.
  * PER-LOGIN DATA. Every login key's files move into accounts\\<key>\\, whether or not this
    install's config.json lists the login (another install may share the library). A file
    named by a login's plain name (before the hashed keys) goes to that login's folder when
    the login is known; otherwise it stays where it is, said in the log. Nothing per-login is
    deleted here: only removing a login (the Users tab, --remove-web-user) does that. The
    three install-wide preset files go the same way: into every login with no file of its own,
    this install's and every one the library already holds, then deleted; with no login to give
    them to, they stay where they are, and are no work for any start.
  * CACHES ARE REBUILT, not copied: the badge thumbnails, feat masks and slot/earned banner
    renders are deleted, and made again in local\\cache\\ when next needed. The shortcut icons are
    not a cache: they go to local\\icons\\ before the old icon cache folders are deleted.
  * THE APP'S OWN DEAD FILES GO: the old GUI's settings, an empty stray catalog.db, and the
    Python leftovers git keeps at the root after an update (3.19's __pycache__\\, pytest's
    .pytest_cache\\, tests\\ and tools\\ holding only bytecode, empty docs\\ and screenshots\\) --
    never a folder holding a real file.
  * UPGRADES from 3.10 onward, plus the copy-first 3.20 layout. 3.10 to 3.16 keep every file
    where 3.17 does (read off the v3.10.0-v3.16.0 tags) and only lack what came later, so one
    move serves them all. 3.20's MOVED.json records (`source_print`) tell its copies from files
    written since, then are deleted. The pre-v7 pack rename (moonglade.assets.
    migrate_legacy_name) and the shared-presets fold run here; the legacy branding-root move,
    the banner renders 3.10 and 3.11 left in the art tree, and the Loom store.json split stay
    where they were (moonglade.gallery), now acting on the new homes.
  * THE SPEND RECORDS (train_guard.json, the Loom's _submits\\, runs.db's reservations) move as
    files, through the same safe move, while nothing runs: no server has started yet. No spend
    logic is here.
  * A FAILURE STOPS THE START (MoveStopped, with a plain sentence that says why and what to
    do): a lock held past its wait, a dead start's lock that can't be removed, a file that
    cannot be copied or removed, a link that can't move as a link, an unreadable config.json
    while the settings are still to merge. Carrying on would read empty new homes. A source the
    move has copied and verified is made writable before it is deleted, and a refusal is tried
    again a few times, so a read-only file or a scanner's moment never stops every start.
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
REMOVE_TRIES = 5             # a delete (or a swap) Windows refuses is tried this many times...
REMOVE_BACKOFF_S = 0.1       # ...pausing 0.1, 0.2, 0.4 and 0.8 s between tries
# The Windows refusals a swap is tried again for: access denied (a scanner or a sync tool
# opening the file just written), a sharing violation, a lock violation.
_REPLACE_RETRY_WINERRORS = (5, 32, 33)
WRITTEN_SINCE_SLACK_S = 2.0  # a file's time this close to the move's own end is the move's
# A file at most this big is hashed even when it moves by one rename, so the journal knows the
# very bytes the move took, as the copy path's does (a record put back later with exactly those
# bytes is then the move's own source, and is only removed: _two_copies).
SMALL_RECORD_BYTES = 4 << 20
# The reparse tags of an entry that points somewhere else: a symbolic link (to a file or a
# folder) and a junction (a mount point). os.path.islink() misses a junction, and os.walk()
# and Path.is_dir() go into one; the move never does (_is_link).
_LINK_TAGS = (0xA000000C, 0xA0000003)
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
# The install root's dead Python leftovers. An update is a git pull, and git keeps an ignored
# file when it deletes the tracked ones beside it: 3.19's root modules leave their bytecode in
# __pycache__\, pytest its .pytest_cache\, and the suite and tools (in dev\ since 3.20) leave
# tests\ and tools\ holding only __pycache__\; docs\ and screenshots\ are older shells. Each
# goes only while it holds nothing but bytecode, pytest's cache, or nothing (_only_dead_python):
# a folder holding a real file, or a link, is never removed.
DEAD_ROOT_FOLDERS = ("__pycache__", ".pytest_cache", "tests", "tools", "docs", "screenshots")
# The first bytes of the CACHEDIR.TAG pytest writes into its cache folder (the cache-directory
# tagging standard's own signature).
_CACHEDIR_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"
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
            # backslashreplace: a line carrying a lone UTF-16 surrogate (a Loom value with a
            # cut-off emoji) is written as \udXXX, never raises, and never loses the lines after.
            with open(path, "a", encoding="utf-8", errors="backslashreplace") as f:
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
    clean_starts, items: {destination: {src, src_sha256, sha256, state, time, made_ns}}}.
    Written whole, through a temp flushed to disk."""

    def __init__(self, folder):
        self.path = Path(folder) / _paths.JOURNAL_NAME
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
                raise ValueError
        except (OSError, ValueError):
            doc = {"format": JOURNAL_FORMAT, "started": None, "finished": None, "items": {}}
        self.doc = doc
        self.saved_ns = self._disk_ns()

    def _disk_ns(self):
        """The journal file's own time as the disk wrote it, or None."""
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    @property
    def items(self):
        return self.doc["items"]

    def save(self):
        _write_bytes(self.path, (json.dumps(self.doc, indent=1, sort_keys=True) + "\n")
                     .encode("utf-8"))
        self.saved_ns = self._disk_ns()

    def made(self, key, **extra):
        """Journal the item at `key` made, and save. made_ns is the disk's time of the save
        that journalled it under way: the move had the item by then, so an old-layout copy at
        its old place written later was written after the move took it (_written_since)."""
        entry = self.items[key]
        entry.update(state="made", **extra)
        if self.saved_ns:
            entry["made_ns"] = self.saved_ns
        self.save()

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


def _boot_time():
    """When this PC last started, in seconds since the epoch on its own clock, or None when
    that can't be known."""
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32")
            k32.GetTickCount64.restype = ctypes.c_ulonglong
            return time.time() - k32.GetTickCount64() / 1000.0
        except (OSError, AttributeError, ValueError):
            return None
    try:
        with open("/proc/stat", "rb") as f:
            for line in f:
                if line.startswith(b"btime"):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


BOOT_SLACK_S = 60.0          # a lock made this long before this PC last started was a dead run's
TAKEOVER_STALE_S = 30.0      # a take-over marker this old was left by a start that died taking over
TAKEOVER_TRIES = 20          # marker numbers tried before waiting like any other start


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
    a dead one) -- by writing it, so the disk stamps its time. acquire() waits up to
    LOCK_WAIT_S for another holder, then raises MoveStopped. A lock is taken over only from a
    holder that is gone (_stale). On this PC its process is checked first: not running, or
    the number now belongs to a process started after the lock was made, is gone; running and
    started before it, it is the holder, whatever the clock says. Only a process that can't be
    opened (another user's: a service, winlogon) is judged otherwise: gone when the lock was
    made before the PC last started, else alive only until LOCK_STALE_S untouched -- a live
    holder touches its lock every HEARTBEAT_S. A lock another PC made (a library on a network
    drive) counts as alive until it has gone LOCK_STALE_S untouched. Every age is read on the
    disk's own clock (never this PC's against another's), from the same open file as the
    bytes judged. A stale lock is taken over under a short-lived marker made with O_EXCL
    (_take_over): only the start holding it re-reads the lock, and removes it only when it is
    still byte for byte the lock judged dead. The lock is never moved aside, so a live one
    made meanwhile is never touched. release() removes only a lock that still holds this
    one's own line. A folder this user cannot write in stops the start and says so, and so
    does a dead start's lock this user can't remove -- after the same wait, pausing between
    tries, never spinning on it."""

    def __init__(self, folder, what):
        self.path = Path(folder) / _paths.LOCK_NAME
        self.what = what
        self.held = False
        self.token = ""
        self._disk_offset = None                 # the disk's clock less this PC's (_disk_now)

    def acquire(self, wait=None):
        wait = LOCK_WAIT_S if wait is None else wait
        deadline = time.monotonic() + wait
        stuck = None                             # why a dead holder's lock can't be removed
        self._disk_offset = None
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stale, seen = self._stale()
                except OSError:
                    stale, seen = False, None    # it went while we looked: try again
                if stale:
                    taken = self._take_over(seen)
                    if taken is True:
                        stuck = None
                        continue
                    if isinstance(taken, OSError):
                        # A dead start's lock this user can't remove (another account's file,
                        # a share without delete rights): wait like any other holder, then say
                        # so -- never spin on it.
                        stuck = taken
                else:
                    stuck = None                 # a live holder's: "still tidying", not stuck
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
                self._clear_markers()
                return self
            if time.monotonic() > deadline:
                if stuck is not None:
                    raise MoveStopped(
                        "Moonglade can't remove the old lock %s (%s). A start that stopped "
                        "part-way left it, and it only marks that start, which is no longer "
                        "running: delete it, then start Moonglade again." % (
                            self.path, _reason(stuck)))
                raise MoveStopped(
                    "Another Moonglade start is still tidying %s. Wait a minute, then start "
                    "Moonglade again." % self.what)
            time.sleep(0.1)

    def _disk_now(self):
        """Now, on the clock of the disk the lock is on: a file made in the lock's folder takes
        its time from the disk (a share's server, a NAS), as the lock's own time does. The
        difference from this PC's clock is read once per acquire()."""
        if self._disk_offset is None:
            self._disk_offset = 0.0
            try:
                fd, probe = tempfile.mkstemp(prefix=".moonglade-clock-",
                                             dir=str(self.path.parent))
            except OSError:
                return time.time()
            try:
                os.write(fd, b"0")
                self._disk_offset = os.fstat(fd).st_mtime - time.time()
            except OSError:
                pass
            finally:
                os.close(fd)
                try:
                    os.remove(probe)
                except OSError:
                    pass
        return time.time() + self._disk_offset

    def _stale(self):
        """(True only when the holder is gone (see the class), the lock's bytes as judged).
        The bytes and their time come from one open file: a lock replaced while we look is
        never judged by another's age. Raises OSError when the lock went while we looked."""
        with open(self.path, "rb") as f:
            seen = f.read()
            mtime = os.fstat(f.fileno()).st_mtime
        age = self._disk_now() - mtime
        try:
            parts = seen.decode("utf-8").split()
            pid = int(parts[0]) if parts else None
        except (ValueError, UnicodeDecodeError):
            pid = None
        if pid is None:
            return age > 2.0, seen               # being written: give it a moment
        host = parts[1] if len(parts) > 1 else _host()
        if host.lower() != _host().lower():
            return age > LOCK_STALE_S, seen      # another PC's start: alive until untouched
        try:
            made = float(parts[2]) if len(parts) > 2 else None
        except ValueError:
            made = None
        # The process first (#6): the boot time follows this PC's clock, so a clock stepped
        # forward after a live start made its lock would read it as made before the last boot.
        if not _pid_alive(pid):
            return True, seen                    # its process is gone
        started = _process_started(pid)
        if started is not None and made is not None:
            return started > made + 2.0, seen    # running: the holder, unless reused since
        # Running, as far as can be told, but it can't be opened to say when it started (a
        # service or winlogon holding a dead start's reused number): dead when the lock was
        # made before this PC last started, and otherwise alive only until it has gone
        # LOCK_STALE_S untouched (#8) -- a live holder touches it every HEARTBEAT_S.
        boot = _boot_time() if made is not None else None
        if boot is not None and made < boot - BOOT_SLACK_S:
            return True, seen
        return age > LOCK_STALE_S, seen

    def _marker(self, seen, n):
        """The take-over marker for the lock judged as `seen` (bytes), number `n`."""
        return self.path.with_name("%s.takeover-%s-%d" % (
            self.path.name, hashlib.sha256(seen).hexdigest()[:16], n))

    def _take_over(self, seen):
        """Take over the stale lock judged as `seen` (#7), under a marker made with O_EXCL and
        named for that very lock: only the start holding it re-reads the lock, and removes it
        only when it is still byte for byte `seen`. Nothing else removes a lock that isn't its
        own, and a lock's bytes never repeat, so once the dead one is gone no taker can touch
        the live one made after it. The lock is never moved aside. A marker TAKEOVER_STALE_S
        old was left by a start that died taking over: the next number is tried, and the old
        marker is never removed under another taker. The marker goes when the take-over is
        done (and any left over goes when the folder is next locked: _clear_markers). True when
        the dead lock was removed (the folder is free to lock), False when it went first, was
        replaced, or another start is taking it over, the OSError when it can't be removed."""
        marker = None
        for n in range(1, TAKEOVER_TRIES + 1):
            cand = self._marker(seen, n)
            try:
                fd = os.open(str(cand), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = self._disk_now() - os.stat(cand).st_mtime
                except OSError:
                    return False                 # it went while we looked: try again
                if age > TAKEOVER_STALE_S:
                    continue                     # a start that died taking over: the next one
                return False                     # another start is taking it over now
            except PermissionError as e:
                if os.path.lexists(cand):
                    return False                 # another start's marker, going: try again
                return e
            except OSError as e:
                return e
            os.close(fd)
            marker = cand
            break
        if marker is None:
            return False
        try:
            try:
                got = self.path.read_bytes()
            except FileNotFoundError:
                return False                     # it went first
            except OSError as e:
                return e
            if got != seen:
                return False                     # a live lock made meanwhile: never touched
            try:
                _make_writable(self.path)        # a dead start's read-only lock
                os.remove(self.path)
            except FileNotFoundError:
                return False
            except OSError as e:
                return e
            return True
        finally:
            try:
                os.remove(marker)
            except OSError:
                pass

    def _clear_markers(self):
        """Remove the take-over markers beside a lock this start now holds. Each names a lock
        that is gone (this one was made with O_EXCL, and a lock's bytes never repeat), so none
        guards anything any more; a slow taker holding one finds the lock isn't its own."""
        prefix = self.path.name + ".takeover-"
        try:
            names = os.listdir(self.path.parent)
        except OSError:
            return
        for n in names:
            if n.startswith(prefix):
                try:
                    os.remove(self.path.parent / n)
                except OSError:
                    pass

    def touch(self):
        """Keep a held lock fresh by writing its own line again, so the disk stamps the time
        (another PC ages it on the disk's clock). Never writes over a lock that isn't this
        one's own."""
        if self.held:
            mine = self.token.encode("utf-8")
            try:
                with open(self.path, "r+b") as f:
                    if f.read() == mine:
                        f.seek(0)
                        f.write(mine)
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
    if isinstance(e, sqlite3.OperationalError) and \
            any(w in str(e).lower() for w in ("locked", "busy")):
        return "open"                            # a database another program is writing
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
            }.get(_kind_of_failure(e)) or getattr(e, "strerror", None) \
        or (str(e) if isinstance(e, sqlite3.Error) else None) or e.__class__.__name__


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


def _replace(src, dst):
    """os.replace(src, dst) -- every swap the move makes goes through here (the journal, a
    moved, merged or parked file, the snapshot's zip). A refusal Windows gives for a moment
    (winerror 5, 32 or 33: a virus scan, the search indexer or OneDrive opening the file just
    written) is tried again REMOVE_TRIES times with a growing pause. Raises the last OSError."""
    for attempt in range(REMOVE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            if getattr(e, "winerror", None) not in _REPLACE_RETRY_WINERRORS \
                    or attempt + 1 >= REMOVE_TRIES:
                raise
            time.sleep(REMOVE_BACKOFF_S * (2 ** attempt))


def _write_bytes(p, data):
    """Write `data` to `p` whole: a temp beside it, flushed, then swapped in (_replace)."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + MOVING_SUFFIX)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, p)
        _fsync_dir(p.parent)
    finally:
        _discard(tmp)


# ---- links: a junction or a symbolic link is never walked into, copied or deleted through ----
def _is_link(p):
    """Is `p` an entry that points somewhere else -- a symbolic link (to a file or a folder)
    or a Windows junction? os.path.islink() misses a junction, and os.walk(), Path.is_dir()
    and a plain copy all go through one. The move never does: a link is moved as a link
    (renamed, _bring_link), and a delete removes only the link itself (_unlink_link)."""
    try:
        st = os.lstat(p)
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def _link_target(p):
    """Where the link `p` points, for a sentence ("" when it can't be read): a junction's
    target without Windows' \\\\?\\ prefix, and a \\\\?\\UNC\\ one as the \\\\server path it is."""
    try:
        t = os.readlink(p)
    except (OSError, ValueError, AttributeError):
        return ""
    if t.startswith("\\\\?\\UNC\\"):
        return "\\\\" + t[len("\\\\?\\UNC\\"):]
    if t.startswith("\\\\?\\"):
        return t[len("\\\\?\\"):]
    return t


def _symlink_text(p):
    """The target the symbolic link `p` holds, as it is written (relative or a full path);
    None for a junction (always a full path) or anything that isn't a symbolic link."""
    try:
        if not stat.S_ISLNK(os.lstat(p).st_mode):
            return None
        return os.readlink(p)
    except (OSError, ValueError, AttributeError):
        return None


def _relinked(link_dir, target, new_dir):
    """A symbolic link in the real folder `link_dir` holds `target`: the target to write
    instead when the link moves to the real folder `new_dir`, so it still points at the same
    place -- relative, as it was -- or None when it needs no change (a full path, or one that
    points at the same place from either folder). Path arithmetic only."""
    if not target or os.path.isabs(target):
        return None
    old = os.path.normpath(os.path.join(link_dir, target))
    new = os.path.normpath(os.path.join(new_dir, target))
    if os.path.normcase(old) == os.path.normcase(new):
        return None
    return os.path.relpath(old, new_dir)


def _retarget(src, dest):
    """The target a symbolic link at `src` must hold at `dest` to point where it does now
    (_relinked, on the real folders), or None when a plain rename keeps it right."""
    text = _symlink_text(src)
    if text is None:
        return None
    return _relinked(os.path.realpath(Path(src).parent), text,
                     os.path.realpath(Path(dest).parent))


_UNPLANNED = object()


def _real_entry(p):
    """`p` with the folders above it resolved (links followed), the entry itself as it is."""
    p = Path(p)
    return os.path.normpath(os.path.join(os.path.realpath(p.parent), p.name))


def _under_path(p, root):
    """`p` relative to `root` (both plain path strings), or None when it isn't under it."""
    a, b = os.path.normcase(p), os.path.normcase(root)
    if a == b:
        return ""
    if a.startswith(b.rstrip("\\/") + os.sep):
        return p[len(root.rstrip("\\/")) + 1:]
    return None


def _through_the_plan(aim, homes, removed):
    """Where the place `aim` will be once the plan has moved (a full path), None when the plan
    leaves it where it is, or False when the move empties it and it has no one new place.
    `homes` maps every planned source (by _real_entry, normcased) to its new home; `removed`
    holds what the plan deletes, files and the folders it prunes once empty: only a folder at
    or under one of those can be emptied (the library's own folder never is)."""
    key = os.path.normcase(aim)
    if key in homes:
        return homes[key]
    for src, dest in homes.items():             # inside a link the plan moves whole
        rest = _under_path(key, src)
        if rest and _is_link(src):
            return os.path.join(dest, aim[len(aim) - len(rest):])
    if not os.path.isdir(aim) or _is_link(aim):
        return None
    if not any(_under_path(aim, r) is not None for r in removed):
        return None                              # a folder the move never removes stays
    if not any(_under_path(h, aim) for h in homes):
        return None                              # no planned source inside: never walked
    files, links = _scan(aim)
    inside = [(str(f), os.path.normcase(_real_entry(f))) for f in files + links]
    if not inside or not all(k in homes or k in removed for _f, k in inside):
        return None                              # it keeps something: it stays
    places = {}
    for f, k in inside:
        dest = homes.get(k)
        if dest is None:
            continue                             # a transient the move deletes
        rel = _under_path(f, aim)
        if not rel or not os.path.normcase(dest).endswith(os.sep + os.path.normcase(rel)):
            return False                         # its files go to homes of other names
        place = dest[:len(dest) - len(rel) - 1]
        places[os.path.normcase(place)] = place
    if not places:
        return None                              # only transients: nothing of it moves
    if len(places) != 1:
        return False                             # its files split between new homes
    return next(iter(places.values()))


def _plan_link_targets(moves, removals):
    """For each link the plan moves: ({old path: the target a relative symbolic link must
    hold at its new home, or None when its text already points right from there}, {old path:
    (why it can't, what to do)}).

    A relative target the same plan moves is followed to its new place (#9: the Loom's
    exports\\latest -> 2026-10 keeps its text, its inner layout unchanged); one the move empties
    with no one new place can't be pointed at, and stops the start. A full-path target -- every
    junction, and a symbolic link written with one -- is renamed as it is, so it keeps naming
    the very place it names: right while the plan leaves that place alone, and pointing at an
    emptied, pruned old folder when the plan takes it (round 3 #9). That one stops the start,
    before anything moves."""
    homes = {os.path.normcase(_real_entry(s)): _real_entry(d)
             for s, d, _k, _v in moves if _movable(s)}
    removed = {os.path.normcase(_real_entry(p)) for p in removals}
    targets, why = {}, {}
    for src, dest, kind, _v in moves:
        if not (kind == "link" or _is_link(src)):
            continue
        k = os.path.normcase(str(src))
        text = _symlink_text(src)
        if text is None or os.path.isabs(text):
            full = _link_target(src)             # a junction's, without Windows' \\?\ prefix
            if not full or not os.path.isabs(full):
                continue                         # can't be read: renamed as it is
            # Where it points, its folders resolved -- and as written, for a path that goes
            # through a link the plan moves whole (the link's own old place goes).
            there = None
            for aim in dict.fromkeys((_real_entry(full), os.path.normpath(full))):
                there = _through_the_plan(aim, homes, removed)
                if there is not None:
                    break
            if there is None:
                continue                         # the plan leaves it where it is
            if there is False:
                why[k] = ("it points by its full path at %s, which the move empties" % aim,
                          _FULL_LINK_ADVICE)
            else:
                why[k] = ("it points by its full path at %s, which the move takes to %s, so "
                          "from its new home it would point at the emptied old place" % (
                              aim, there), _FULL_LINK_ADVICE)
            continue
        if not text:
            continue
        aim = os.path.normpath(os.path.join(os.path.realpath(Path(src).parent), text))
        new_dir = os.path.realpath(Path(dest).parent)
        there = _through_the_plan(aim, homes, removed)
        if there is False:
            why[k] = ("it points at %s, which the move empties" % aim, _RELATIVE_LINK_ADVICE)
            continue
        there = aim if there is None else there
        if os.path.normcase(os.path.normpath(os.path.join(new_dir, text))) == \
                os.path.normcase(there):
            targets[k] = None                    # its text already points there
            continue
        try:
            targets[k] = os.path.relpath(there, new_dir)
        except ValueError:                       # another drive: no relative path reaches it
            why[k] = ("it points at %s, which no relative path reaches from there" % there,
                      _RELATIVE_LINK_ADVICE)
    return targets, why


def _link_stuck(src, dest, taken=True, link_target=_UNPLANNED):
    """Why the link `src` can't move as a link to `dest` (_link_stop's arguments), or None:
    its new home is taken (when `taken`), on another drive, or (on Windows) it points by a
    path relative to where it sits that would point elsewhere from there."""
    if taken and os.path.lexists(dest):
        return (src, dest, "that place is already taken")
    if not _same_device(src, dest):
        return (src, dest, "its new home is on another drive")
    target = _retarget(src, dest) if link_target is _UNPLANNED else link_target
    if sys.platform == "win32" and target is not None:
        return (src, dest, _RELATIVE_LINK_WHY % _symlink_text(src), _RELATIVE_LINK_ADVICE)
    return None


def _nearest_existing(p):
    p = Path(p)
    while not os.path.lexists(p) and p != p.parent:
        p = p.parent
    return p


def _same_device(src, dest):
    """Is the entry `src` on the drive `dest` would be made on (its nearest existing folder,
    links in the way followed)? Unknown counts as yes: the rename itself then says."""
    try:
        a = os.lstat(src).st_dev
        b = os.stat(_nearest_existing(Path(dest).parent)).st_dev
    except OSError:
        return True
    return a == b or not a or not b


_RELATIVE_LINK_WHY = ("it points by a path written from where it sits (%s), so from its new "
                      "home it would point somewhere else")
_RELATIVE_LINK_ADVICE = ("Make the link point by its full path, or put the real folder or file "
                         "in its place, then start Moonglade again.")
_FULL_LINK_ADVICE = ("Delete the link itself, not what is in it (deleting a link in File "
                     "Explorer leaves what it points at, which then moves with the rest), start "
                     "Moonglade again, then make the link again pointing at the new place.")


def _unlink_link(p):
    """Remove the link entry `p` itself -- never what it points at. Raises OSError."""
    try:
        os.unlink(p)                             # a file link; POSIX: any link
    except (IsADirectoryError, PermissionError):
        os.rmdir(p)                              # Windows: a folder link or a junction


def _scan(folder):
    """(files, links) under `folder`, each sorted: every file, and every link found (_is_link),
    which is never walked into. A `folder` that is itself a link gives ([], [folder])."""
    folder = Path(folder)
    if _is_link(folder):
        return [], [folder]
    if not folder.is_dir():
        return [], []
    files, links, stack = [], [], [folder]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            p = Path(e.path)
            if _is_link(p):
                links.append(p)
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                stack.append(p)
            else:
                files.append(p)
    return sorted(files), sorted(links)


def _via_link(path, root):
    """Is any folder from `root` (not included) down to `path` (included) a link? A path
    that goes through one leads into what the link points at, which the move never touches."""
    path, root = Path(path), Path(root)
    try:
        rel = path.relative_to(root)
    except ValueError:
        return _is_link(path)
    p = root
    for part in rel.parts:
        p = p / part
        if _is_link(p):
            return True
    return False


def _empty_tree(folder):
    """True when `folder` holds no file and no link at any depth (only empty folders)."""
    files, links = _scan(folder)
    return not files and not links


def _discard(p):
    """Remove one of the move's own temps (or a folder of them). Never raises; a link is
    removed as a link."""
    try:
        if _is_link(p):
            _unlink_link(p)
        elif p.is_dir():
            _rmtree_whole(p)
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
    """Delete `folder` and everything in it, never following a link: a junction or symbolic
    link inside (or `folder` itself, when it is one) is removed as the link entry alone, and
    what it points at is never touched. A file that kept a read-only attribute when it was
    copied in (the outside-references fixer copies a shortcut with shutil.copy2, a library
    restored from read-only media) is made writable first: Windows refuses to delete a
    read-only file, and the folder would otherwise outlive every attempt. Raises OSError."""
    files, links = _scan(folder)
    for link in links:
        _unlink_link(link)
    if _is_link(folder) or not Path(folder).exists():
        return
    for p in files:
        _make_writable(p)
    shutil.rmtree(folder)


def _remove(p):
    """Delete a file or folder this module has accounted for: a source already copied and
    verified, a cache, a leftover of the app's own. A link is removed as the link entry alone,
    never what it points at. A read-only attribute is cleared first, and a refusal is tried
    again REMOVE_TRIES times with a growing pause (a scanner, an indexer or a sync tool can
    hold a file for a moment). Raises _Failed, carrying the cause."""
    p = Path(p)
    last = None
    for attempt in range(REMOVE_TRIES):
        try:
            if _is_link(p):
                _unlink_link(p)
            elif p.is_dir():
                _rmtree_whole(p)
            elif p.exists():
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
    """{table: rows} for a SQLite file that passes PRAGMA integrity_check, else None. A file
    that is busy or can't be opened (sqlite3.OperationalError: locked by another program, no
    access) is not a damaged one: that raises, and the start stops to try again."""
    con = None
    try:
        con = sqlite3.connect(str(p))
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return None
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
                for t in tables}
    except sqlite3.OperationalError:
        raise
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
    if p.is_dir() and not _is_link(p):
        files = newest = size = 0
        for f in _scan(p)[0]:                    # never through a link
            if _transient_320(f.name):
                continue
            st = f.stat()
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
        # The library's move had finished before this run began: an old-layout copy now is
        # one written since, and the new home always wins (_fold_in). The first move (and the
        # install half) keep their own rules.
        self.settled = False
        # The Loom's key->value folder in the new home (the library half only): its files are
        # merged by what the Loom stores in them (_loom_kv_merged).
        self.loom_kv = None
        # The target each relative symbolic link the plan moves must hold at its new home
        # (_plan_link_targets: None for one renamed as it is), by its old path.
        self.link_targets = {}

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
        # The last save before the cut is the one that journalled the rename under way.
        stamp = {"made_ns": self.journal.saved_ns} if self.journal.saved_ns else {}
        for key, entry in list(self.journal.items.items()):
            if not isinstance(entry, dict) or entry.get("state") != "renaming":
                continue
            dest, src = self.path_of(key), self.path_of(entry.get("src") or "")
            if entry.get("how") == "link":       # a link renamed as itself (_bring_link)
                if os.path.lexists(dest) and not os.path.lexists(src):
                    entry.update(state="made", **stamp)
                    changed = True
                elif os.path.lexists(src) and not os.path.lexists(dest):
                    del self.journal.items[key]
                    changed = True
                elif (entry.get("target") and os.path.lexists(src)
                      and _symlink_text(dest) == entry["target"]
                      and _symlink_text(src) is not None
                      and _symlink_text(src) == entry.get("was", _symlink_text(src))):
                    # Made again at its new home with its target rewritten, and cut short
                    # before the old entry went: it goes now -- only while it is still the
                    # link it was (a real file an older install wrote there since is kept,
                    # and the entry stays under way).
                    try:
                        _unlink_link(src)
                    except OSError:
                        continue
                    entry.update(state="made", **stamp)
                    changed = True
                continue
            if dest.is_file() and not src.exists():
                entry.update(state="made", how="renamed", **stamp)
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


# How long each entry of the training spend guard blocks (moonglade.gallery.TrainGuard): a Basic
# start that may have gone through ("ambiguous", or "armed" and never resolved) for 15 minutes,
# one PixAI started for a minute; a retry PixAI took ("done") for good, one that may have gone
# through for a day; an Advanced confirm that may have gone through for 15 minutes.
_GUARD_AMBIGUOUS_S = 15 * 60.0
_GUARD_STARTED_S = 60.0
_GUARD_RETRY_AMBIGUOUS_S = 24 * 3600.0


def _guard_block_end(section, entry):
    """When `entry`, one key of the spend guard's `section`, stops blocking (seconds since the
    epoch): inf for a retry PixAI took, -inf for an entry that never blocks, None for one that
    can't be read. A section this build doesn't know blocks until its entry's own time."""
    if not isinstance(entry, dict):
        return None
    try:
        at = float(entry.get("at") or 0)
    except (TypeError, ValueError):
        return None
    state = entry.get("state")
    if section == "retried":
        state = state or "armed"
        if state == "done":
            return float("inf")
        if state in ("ambiguous", "armed"):
            return at + _GUARD_RETRY_AMBIGUOUS_S
        return float("-inf")
    if section == "basic":
        if state in ("ambiguous", "armed"):
            return at + _GUARD_AMBIGUOUS_S
        if state == "started":
            return at + _GUARD_STARTED_S
        return float("-inf")
    if section == "paid":
        return at + _GUARD_AMBIGUOUS_S       # any confirm on record blocks while it is fresh
    return at


def _merge_guard(a, b, b_newer):
    """The training spend guard, `a` (the new home's) with `b` folded in: each section's
    entries from both copies; where both hold one key, the entry whose block ends later
    (_guard_block_end) -- a retry PixAI took always wins, and on a tie (both "done") `a`'s
    stays. More guarding, never less: a later but shorter block never replaces a longer one."""
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
            end_a, end_b = _guard_block_end(section, merged[k]), _guard_block_end(section, v)
            if end_b is not None and (end_a is None or end_b > end_a):
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


# ---- after the library's move has finished: the new home always wins ----------------------------
def _under(p, folder):
    try:
        Path(p).relative_to(folder)
        return True
    except ValueError:
        return False


def _settled_kind(kind, dest, loom_kv=None):
    """How an old-layout copy written after the library's move finished (by an older install
    still on the library, or a version gone back to) is folded into the new home. The kinds
    the first move already merges keep their merge (lines, logs, the JSON records, the spend
    guard); a database is merged row by row; integrity_marks.json mark by mark; a file of the
    Loom's key->value store (under `loom_kv`) by what the Loom keeps in it (_loom_kv_merged);
    any other JSON store (a login's prefs, state, snippets, presets or views, the schedule) key
    by key. A report, a curation undo file or anything else is "park": it can't be merged, so
    it is set aside and named."""
    if kind != "file":
        return kind
    name = Path(dest).name
    if loom_kv is not None and Path(dest).suffix.lower() == ".json" and _under(dest, loom_kv):
        return "json:loom"
    if name == "integrity_marks.json":
        return "json:marks"
    if name in _REPORT_NAMES or name.startswith(CURATION_SNAPSHOT_PREFIX):
        return "park"
    if Path(dest).suffix.lower() == ".json":
        return "json:keys"
    return "park"


def _union_new_wins(a, b):
    """`a` (the new home's) kept whole, with what only `b` (the older copy) holds added: a
    dict by key, a list as a union in order. Returns (merged, clashes) -- clashes is
    [(key, b's value)] for each key both hold with different values, where `a`'s value is
    kept -- or (None, []) when the two can't be merged (not the same kind of thing)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out, clashes = dict(a), []
        for k, v in b.items():
            if k not in a:
                out[k] = v
            elif a[k] != v:
                clashes.append((k, v))
        return out, clashes
    if isinstance(a, list) and isinstance(b, list):
        return list(a) + [x for x in b if x not in a], []
    return None, []


def _union_marks(a, b):
    """integrity_marks.json ({"format", "marks": {media id: {mark, at}}}): every media id's
    mark from both copies, the new home's where both hold one (a clash)."""
    if not isinstance(a, dict) or not isinstance(b, dict) \
            or not isinstance(a.get("marks"), dict) or not isinstance(b.get("marks"), dict):
        return None, []
    marks, clashes = _union_new_wins(a["marks"], b["marks"])
    out = dict(a)
    out["marks"] = marks
    for k, v in b.items():
        out.setdefault(k, v)
    return out, clashes


def _merge_telemetry(a, b):
    """telemetry.json written after the move, `b`, folded into the new home's, `a`: each
    counter at its max, never added. A copy written at an old place after the move may be a
    restored backup of any age, a sync tool's copy, or an older install's own counts since;
    nothing in the file tells which, and adding the first two counted achievements twice. A
    max can never count anything twice, and folding the same copy again changes nothing. The
    cost: the counts an older install makes after the move aren't added (the docs say not to
    run one on the library). The maxima stay at their max, the sets, days and day lists are
    unions, a flag is set if either set it (all as _merge_generic does), and the new home's
    baselines stay (a snapshot only `b` holds, for an app folder the new home never looked at,
    is added)."""
    out = _merge_generic(a, b)
    ba, bb = a.get("baselines"), b.get("baselines")
    if isinstance(ba, dict):
        baselines = dict(bb) if isinstance(bb, dict) else {}
        baselines.update(ba)
        out["baselines"] = baselines
    return out


# ---- the Loom's key->value store, after the move ----------------------------------------------
# The Loom keeps every board and its cast library as JSON text (window.storage.set(k,
# JSON.stringify(...)), loom/master-storyboard.jsx), which /api/loom/set writes as a JSON string
# (moonglade.gallery's _loom_kv_write: json.dumps(value)): the file is JSON text inside a JSON
# string, one file per key, named quote(key) + ".json".
LOOM_CASTLIB_KEY = "storyboard:v2:castlib"    # the cast library: {v, members: [{libId, ...}]}
LOOM_ACTIVE_KEY = "storyboard:v2:active"      # which board is open: a pointer, not a record


def _loom_inner(outer):
    """(the document, True) for a Loom value holding JSON text, else (outer, False)."""
    if isinstance(outer, str):
        try:
            return json.loads(outer), True
        except ValueError:
            return outer, False
    return outer, False


def _union_cast(a, b):
    """The cast library, the new home's `a` with the older copy's `b` folded in: every member
    of both by its libId -- the new home's where both hold one (a clash) -- and every other
    key by union (the new home's on a clash). Returns (merged, clashes)."""
    members = list(a["members"])
    mine = {str(m.get("libId")): m for m in members if isinstance(m, dict) and m.get("libId")}
    clashes = []
    for m in b["members"]:
        lid = str(m.get("libId")) if isinstance(m, dict) and m.get("libId") else None
        if lid is None:
            if m not in members:
                members.append(m)
            continue
        if lid in mine:
            if mine[lid] != m:
                clashes.append(("member " + lid, m))
            continue
        members.append(m)
        mine[lid] = m
    rest, more = _union_new_wins({k: v for k, v in a.items() if k != "members"},
                                 {k: v for k, v in b.items() if k != "members"})
    rest["members"] = members
    return rest, more + clashes


def _loom_kv_merged(src, dest):
    """A Loom key->value file both homes hold, after the move: (the new home's value with the
    older copy's folded in, as the file's bytes; clashes), or (None, clashes) when the two
    can't be merged. The JSON text inside each is merged, not the string around it: the cast
    library member by member (_union_cast); a board (any other key) gains the keys only the
    older copy holds -- but a board both copies changed can't be merged: key by key, the new
    home's "acts" would replace the older copy's whole, and every card and render record only
    the older install made would go. That one comes back as (None, its clashes), and _fold_in
    keeps it whole beside the new home. What is merged is written back the way the Loom's own
    write leaves it. The open-board pointer keeps the new home's (the older one is logged).
    Raises ValueError or UnicodeDecodeError for a copy that won't parse, OSError for one that
    won't read."""
    from urllib.parse import unquote
    key = unquote(Path(dest).stem)
    a_outer = json.loads(dest.read_text(encoding="utf-8"))
    b_outer = json.loads(src.read_text(encoding="utf-8"))
    if a_outer == b_outer:
        return dest.read_bytes(), []
    if key == LOOM_ACTIVE_KEY:
        return dest.read_bytes(), [("the open board", b_outer)]
    a, a_text = _loom_inner(a_outer)
    b, b_text = _loom_inner(b_outer)
    if a_text != b_text:
        return None, []
    if (key == LOOM_CASTLIB_KEY and isinstance(a, dict) and isinstance(b, dict)
            and isinstance(a.get("members"), list) and isinstance(b.get("members"), list)):
        doc, clashes = _union_cast(a, b)
    else:
        doc, clashes = _union_new_wins(a, b)
        if clashes:
            return None, clashes                 # a board both changed: kept whole beside
    if doc is None:
        return None, []
    if doc == a:
        return dest.read_bytes(), clashes
    if a_text:
        value = json.dumps(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    else:
        value = json.dumps(doc)
    return value.encode("utf-8"), clashes


def _loom_aside(dest):
    """Where a Loom file that can't be merged is kept, beside the new home under a key of its
    own (`<key>-older-<UTC time>`): outside the safety snapshot, so no clean-start sweep ever
    deletes it, and still the Loom's -- a board kept this way is listed as a board."""
    from urllib.parse import quote, unquote
    base = "%s-older-%s" % (unquote(Path(dest).stem),
                            time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
    key, n = base, 1
    while os.path.lexists(dest.with_name(quote(key, safe="") + ".json")):
        n += 1
        key = "%s-%d" % (base, n)
    return dest.with_name(quote(key, safe="") + ".json"), key


def _loom_kept_beside(dest, sha):
    """A value already kept beside the new home `dest` (_loom_aside: `<key>-older-*`) whose
    bytes have the sha256 `sha`, or None."""
    from urllib.parse import unquote
    prefix = unquote(Path(dest).stem) + "-older-"
    try:
        names = sorted(os.listdir(Path(dest).parent))
    except OSError:
        return None
    for n in names:
        p = Path(dest).parent / n
        if n.endswith(".json") and unquote(n[:-5]).startswith(prefix) and not _is_link(p):
            try:
                if p.is_file() and _sha256(p) == sha:
                    return p
            except OSError:
                continue
    return None


def _settled_bytes(src, dest, how):
    """(the new home's content with the older copy folded in, as bytes; clashes), or
    (None, []) when the two can't be merged. Raises ValueError or UnicodeDecodeError for a
    copy that won't parse, OSError for one that won't read."""
    if how == "log":
        return _merged_log(src, dest), []
    if how != "lines" and not how.startswith("json:"):
        return None, []
    try:                                                 # the new home first: is it the failing side?
        a = dest.read_text(encoding="utf-8")
        if how != "lines":
            a = json.loads(a)
    except (ValueError, UnicodeDecodeError):
        raise _NewHomeBroken(dest)
    if how == "lines":
        return _merged_bytes(src, dest, "lines"), []
    if how == "json:loom":
        return _loom_kv_merged(src, dest)
    b = json.loads(src.read_text(encoding="utf-8"))
    clashes = []
    if how == "json:keys":
        doc, clashes = _union_new_wins(a, b)
    elif how == "json:marks":
        doc, clashes = _union_marks(a, b)
    elif not isinstance(a, dict) or not isinstance(b, dict):
        doc = None
    elif how == "json:achievements":
        doc = _merge_achievements(a, b, b_newer=False)       # the new home's skin
    elif how == "json:guard":
        doc = _merge_guard(a, b, False)                      # more guarding, never less
    elif how == "json:telemetry":
        doc = _merge_telemetry(a, b)                         # each counter at its max
    else:
        doc = _merge_generic(a, b)
    if doc is None:
        return None, []
    if doc == a:
        return dest.read_bytes(), clashes                    # nothing new: the bytes stay
    return (json.dumps(doc, indent=1) + "\n").encode("utf-8"), clashes


def _runs_kept_words(runs_kept, most=20):
    """The older copy's runs the new home's won over, for the log: run id (status, task ids)."""
    parts = ["%s (status %s; task ids: %s)" % (rid, status or "unknown",
                                               ", ".join(tasks) or "none")
             for rid, status, tasks in runs_kept[:most]]
    more = len(runs_kept) - most
    return "; ".join(parts) + (" and %d more" % more if more > 0 else "")


def _clash_words(clashes, most=20, width=300):
    """The older copy's values the new home's won over, for the log: key=value, ... In plain
    ASCII: a lone surrogate in a Loom value is written as its JSON escape, never carried into
    the log."""
    def short(v):
        s = json.dumps(v, ensure_ascii=True, sort_keys=True)
        return s if len(s) <= width else s[:width] + "..."
    parts = ["%s=%s" % (k, short(v)) for k, v in clashes[:most]]
    more = len(clashes) - most
    return ", ".join(parts) + (" and %d more" % more if more > 0 else "")


def _db_tables(con, schema):
    return [r[0] for r in con.execute(
        "SELECT name FROM %s.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' "
        "ORDER BY name" % schema)]


def _qi(name):
    return '"%s"' % str(name).replace('"', '""')


RUN_KEY = "run_id"       # the column every Runs table keys its rows on (moonglade.runs)


def _insert_missing(con, q, cols, pk, old_cols, where="", params=()):
    """Insert into main.`q` the rows of old.`q` (those `where` picks) it doesn't hold yet: by
    primary key (the new home's row wins), or -- with no primary key -- the very same row."""
    names = ", ".join(_qi(c) for c in cols)
    if pk and all(c in old_cols for c in pk):
        same = " AND ".join("m.%s IS o.%s" % (_qi(c), _qi(c)) for c in pk)
        con.execute("INSERT INTO main.%s (%s) SELECT %s FROM old.%s AS o WHERE %sNOT EXISTS "
                    "(SELECT 1 FROM main.%s AS m WHERE %s)" % (
                        q, names, ", ".join("o." + _qi(c) for c in cols), q,
                        ("%s AND " % where) if where else "", q, same), params)
    else:
        con.execute("INSERT INTO main.%s (%s) SELECT %s FROM old.%s AS o%s EXCEPT SELECT %s "
                    "FROM main.%s" % (q, names, names, q, (" WHERE " + where) if where else "",
                                      names, q), params)


def _fold_rows(con):
    """The fold itself, inside _fold_db_rows' transaction. Returns (added, clashes)."""
    added, clashes, shapes = {}, [], {}
    mine = set(_db_tables(con, "main"))
    for name in _db_tables(con, "old"):
        q = _qi(name)
        if name not in mine:
            sql = con.execute("SELECT sql FROM old.sqlite_master WHERE type='table' AND name=?",
                              (name,)).fetchone()[0]
            con.execute(sql)
        info = con.execute("PRAGMA main.table_info(%s)" % q).fetchall()
        old_cols = {r[1] for r in con.execute("PRAGMA old.table_info(%s)" % q)}
        cols = [r[1] for r in info if r[1] in old_cols]
        if cols:
            pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5] > 0]
            shapes[name] = (q, cols, pk, old_cols)
    by_run = [n for n, shape in shapes.items() if RUN_KEY in shape[1]]
    have, theirs = set(), set()
    for name in by_run:
        q = shapes[name][0]
        have |= {r[0] for r in con.execute("SELECT DISTINCT %s FROM main.%s" % (RUN_KEY, q))}
        theirs |= {r[0] for r in con.execute("SELECT DISTINCT %s FROM old.%s" % (RUN_KEY, q))}
    for rid in sorted(theirs & have, key=str):
        if any(_run_rows_differ(con, shapes[n], rid) for n in by_run):
            clashes.append(_run_said(con, shapes, rid))
    only_theirs = sorted(theirs - have, key=str)
    for name, (q, cols, pk, old_cols) in shapes.items():
        before = con.execute("SELECT COUNT(*) FROM main.%s" % q).fetchone()[0]
        if name in by_run:
            for rid in only_theirs:                      # a run only the older copy holds
                _insert_missing(con, q, cols, pk, old_cols, "o.%s IS ?" % RUN_KEY, (rid,))
        else:
            _insert_missing(con, q, cols, pk, old_cols)
        added[name] = con.execute("SELECT COUNT(*) FROM main.%s" % q).fetchone()[0] - before
    return added, clashes


def _run_rows_differ(con, shape, rid):
    """Does the older copy hold a row for run `rid` in this table that the new home doesn't?"""
    q, cols = shape[0], shape[1]
    names = ", ".join(_qi(c) for c in cols)
    return con.execute(
        "SELECT COUNT(*) FROM (SELECT %s FROM old.%s WHERE %s IS ? EXCEPT SELECT %s FROM "
        "main.%s WHERE %s IS ?)" % (names, q, RUN_KEY, names, q, RUN_KEY),
        (rid, rid)).fetchone()[0] > 0


def _run_said(con, shapes, rid):
    """(run id, its status in the older copy, its task ids there): what the log names for a
    run both copies hold whose older rows were not brought in."""
    status, tasks = None, []
    runs, jobs = shapes.get("runs"), shapes.get("run_jobs")
    if runs and "status" in runs[1]:
        row = con.execute("SELECT status FROM old.%s WHERE %s IS ?" % (runs[0], RUN_KEY),
                          (rid,)).fetchone()
        status = row[0] if row else None
    if jobs and "task_id" in jobs[1]:
        order = " ORDER BY cell" if "cell" in jobs[1] else ""
        tasks = [str(r[0]) for r in con.execute(
            "SELECT task_id FROM old.%s WHERE %s IS ? AND task_id IS NOT NULL AND "
            "task_id != ''%s" % (jobs[0], RUN_KEY, order), (rid,))]
    return rid, status, tasks


def _fold_db_rows(target, src):
    """Bring into the SQLite file `target` -- the new home itself, in place -- every row of
    `src` it doesn't hold, in one BEGIN IMMEDIATE transaction: SQLite's own write lock, so a
    server writing `target` at the same moment waits for the fold (or the fold for it), and
    no row either writes is lost. (SQLite refuses an ATTACH inside a transaction, so `src` is
    attached just before it begins; every read, compare and insert is inside it.)

    The Runs tables (those keyed on run_id: the runs and their jobs, the spend reservations)
    fold run by run: a run only `src` holds comes across whole; a run both hold keeps the new
    home's rows whole, and nothing of the older copy's is grafted onto it -- where the older
    copy's rows for it differ, that run is a clash, named for the log. Any other table folds
    row by row by primary key (the new home's row wins), or with none, by the very same row.
    A table only `src` has is made first. The new home's integrity is checked again before
    the COMMIT.

    Returns ({table: rows added}, [(run id, its status there, its task ids there)]). Raises
    sqlite3.Error (rolled back: `target` is unchanged)."""
    con = sqlite3.connect(str(target), isolation_level=None, timeout=10.0)
    try:
        con.execute("ATTACH DATABASE ? AS old", (str(src),))
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                added, clashes = _fold_rows(con)
                check = con.execute("PRAGMA main.integrity_check").fetchone()[0]
                if check != "ok":
                    raise _Failed("the merged %s did not check out (%s)" % (target, check))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.execute("DETACH DATABASE old")
    finally:
        con.close()
    return added, clashes


# ---- the safe move ------------------------------------------------------------------------------
def _link_stop(src, dest, why, advice=None):
    """The sentence for a link the move can't bring as a link (MoveStopped)."""
    target = _link_target(src)
    where = (" into its new home %s" % dest) if dest is not None else ""
    return MoveStopped(
        "%s is a link (a junction or a symbolic link)%s. Moonglade moves a link only as a "
        "link, by renaming it%s on the same drive, and %s. Nothing it points at was touched. "
        "%s" % (src, (" to " + target) if target else "", where, why,
                advice or "Move the link yourself, or put the real folder or file in its place, "
                          "then start Moonglade again."))


def _park(path, half, said=True):
    """Move `path` aside into the half's .snapshot\\parked\\ (copied, verified, then removed:
    the park may be on another volume). Kept until the snapshot goes. A link is parked as a
    link: renamed there, never copied (what it points at is never touched). `said`: log the
    two-copies line (a caller with its own words passes False)."""
    path = Path(path)
    base = half.snapshot_dir / PARKED_DIRNAME / half.rel(path).replace(":", "_")
    target, n = base, 1
    while os.path.lexists(target):
        n += 1
        target = base.with_name("%s.%d" % (base.name, n))
    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_link(path):
        try:
            os.rename(path, target)
        except OSError as e:
            raise _link_stop(path, None, "it couldn't be set aside (%s)" % _reason(e))
        half.parked += 1
        half.report.parked += 1
        half.journal.worked()
        half.report.item("Set aside the link %s in %s (what it points at was not touched).",
                         half.rel(path), half.rel(target))
        return target
    tmp = target.with_name(target.name + MOVING_SUFFIX)
    src_hash = _sha256(path)
    _copy_into(path, tmp, "file")
    if _sha256(tmp) != src_hash:
        _discard(tmp)
        raise _Failed("couldn't set %s aside (the copy did not match)" % path)
    _replace(tmp, target)
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


def _swap_in(tmp, dest, half, key, src_hash, merged_sha):
    """Swap the verified temp `tmp` in over `dest`, journalled first (verified, then made)."""
    half.journal.items[key] = {"src": None, "src_sha256": src_hash, "sha256": merged_sha,
                               "state": "verified", "time": _now(), "merged": True}
    half.journal.save()
    _replace(tmp, dest)
    _fsync_dir(dest.parent)
    half.journal.made(key)


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
    _swap_in(tmp, dest, half, key, src_hash, hashlib.sha256(data).hexdigest())


class _NewHomeBroken(Exception):
    """The new home's own file fails its check (won't parse, fails PRAGMA integrity_check)."""

    def __init__(self, path):
        super().__init__(str(path))
        self.path = Path(path)


def _new_home_broken_words(dest, src):
    return ("%s won't read as what it should be: it fails its own check. Moonglade can't bring "
            "in %s, which an older Moonglade wrote after the move, without reading it, so "
            "nothing was moved or set aside. Restore %s from a backup, then start Moonglade "
            "again." % (dest, src, dest.name))


def _fold_db(src, dest, half, key, src_hash):
    """runs.db written after the move (the Runs and their spend reservations): both files pass
    PRAGMA integrity_check first, then the new home itself takes, in place, every run of the
    older copy it doesn't hold (_fold_db_rows: one BEGIN IMMEDIATE transaction, so a server
    writing the new home meanwhile loses nothing), and the journal says so. Returns (added,
    clashes), or None when the OLDER copy fails its check (it can't be merged). Raises
    _NewHomeBroken when the new home fails its own, sqlite3.Error (busy: the start stops and
    tries again) or OSError."""
    if _db_counts(dest) is None:
        raise _NewHomeBroken(dest)
    if _db_counts(src) is None:
        return None
    added, clashes = _fold_db_rows(dest, src)
    half.journal.items[key] = {"src": None, "src_sha256": src_hash, "sha256": None,
                               "time": _now(), "merged": True}
    half.journal.made(key)
    return added, clashes


def _fold_in(src, dest, kind, half, key, src_hash):
    """The library's move had finished, and `src` -- an old home -- was written since: by an
    older install still on the library, or by a version gone back to. The new home always
    wins: it is never replaced, and what the older copy adds is folded into it where the
    format allows (_settled_kind): lines it lacks, JSON keys and marks it lacks (on a clash
    the new home's value stays, and the older value is logged), telemetry's counters and
    maxima at their max (_merge_telemetry), guards from both, database rows by primary key.
    What can't be merged is set aside and named in the log -- except a file of the Loom's
    key->value store (a board both copies changed among them), which is kept beside the new
    home under a key of its own (_loom_aside), outside the safety snapshot: a board or a cast
    list the older install made is never lost to the clean-start sweep. Returns "merged",
    "parked" or "kept"."""
    how = _settled_kind(kind, dest, half.loom_kv)
    item, rel = half.report.item, half.rel
    why = "it is not a kind of file that can be merged"
    try:
        if how == "db":
            folded = _fold_db(src, dest, half, key, src_hash)
            if folded is not None:
                added, runs_kept = folded
                _remove(src)
                if runs_kept:
                    half.report.warn(
                        "In %s the new home's run was kept whole for %d run(s) both copies "
                        "hold, and the older copy's rows for it were not brought in; the older "
                        "copy at %s said: %s.", rel(dest), len(runs_kept), rel(src),
                        _runs_kept_words(runs_kept))
                item("Merged %s into %s: the new home kept every row it had, and the older "
                     "copy added %s.", rel(src), rel(dest),
                     ", ".join("%d to %s" % (n, t) for t, n in sorted(added.items()))
                     or "nothing")
                return "merged"
            why = "the older copy fails its own integrity check"
        elif how != "park":
            data, clashes = _settled_bytes(src, dest, how)
            if data is not None:
                _replace_with(dest, data, half, key, src_hash)
                _remove(src)
                if clashes:
                    item("In %s the new home's value was kept for %d key(s); the older copy "
                         "at %s said: %s.", rel(dest), len(clashes), rel(src),
                         _clash_words(clashes))
                item("Merged %s into %s (the new home kept what it had).", rel(src), rel(dest))
                return "merged"
            if how == "json:loom" and clashes:
                why = "both copies changed the same board (%s)" % ", ".join(
                    str(k) for k, _v in clashes[:10])
            else:
                why = "the two copies hold different kinds of things"
    except sqlite3.OperationalError:
        raise                                            # busy or unreadable: stop, try again
    except _NewHomeBroken as e:
        # The new home is the side that fails: the healthy older copy is never set aside for
        # the damaged one to stay. Stop, and name the file.
        raise MoveStopped(_new_home_broken_words(e.path, src))
    except (ValueError, UnicodeDecodeError, sqlite3.DatabaseError):
        why = "the older copy can't be read as what it should be"
    if how == "json:loom":
        kept = _loom_kept_beside(dest, src_hash)
        if kept is not None:
            # A start cut short after keeping it beside, before the old file went.
            _remove(src)
            item("Removed %s: the Loom already keeps the same beside %s as %s.", rel(src),
                 rel(dest), rel(kept))
            return "kept"
        aside, key_aside = _loom_aside(dest)
        half.report.warn("Kept %s (written there after the move) beside %s as %s, the Loom "
                         "key \"%s\": %s, so both are kept.", rel(src), rel(dest), rel(aside),
                         key_aside, why)
        _bring(src, aside, "file", half)
        return "kept"
    target = _park(src, half, said=False)
    half.report.warn("Kept %s, the new home, and set aside %s (written there after the move) "
                     "in %s: %s.", rel(dest), rel(src), rel(target), why)
    return "parked"


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
    is as old as what it copied. A new home the journal says this move made is never set
    aside for an old-layout copy written after it (_written_after_made): that copy is folded
    in, the new home winning, as after a finished move."""
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
            half.journal.made(key)
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
    if half.settled or (made and _written_after_made(src, entry, half)):
        # Written after the library's move finished, or after this move made the new home (a
        # first move cut short, then an older install wrote its emptied old home): the new home
        # always wins (A). A home the move made is never set aside for such a copy.
        return _fold_in(src, dest, kind, half, key, src_hash)
    # The first move.
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


def _bring_link(src, dest, half):
    """Bring the link `src` (a junction, or a symbolic link to a file or a folder) to `dest`
    as a link: the link entry itself is renamed, on the same drive, journalled first. What it
    points at is never copied, walked or deleted. A symbolic link whose target is written
    relative to its own folder would point somewhere else from its deeper new home
    (_retarget): off Windows it is made again at `dest` with its target rewritten (still
    relative) and the old entry removed; on Windows, where making one needs a privilege, the
    start stops. A link that can't be brought there (that place is taken, it is on another
    drive, it points by a relative path on Windows) is left where it is, and the start stops
    with a plain sentence (MoveStopped; _plan_library stops for these before anything
    moves). Returns "moved", or None when nothing is at `src`."""
    src, dest = Path(src), Path(dest)
    if not os.path.lexists(src) or _same(src, dest):
        return None
    half.report.worked[half.name] = True
    if os.path.lexists(dest):
        raise _link_stop(src, dest, "that place is already taken")
    key = half.rel(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    planned = half.link_targets.get(os.path.normcase(str(src)), _UNPLANNED)
    target = _retarget(src, dest) if planned is _UNPLANNED else planned
    if target is not None and sys.platform == "win32":
        raise _link_stop(src, dest, _RELATIVE_LINK_WHY % _symlink_text(src),
                         _RELATIVE_LINK_ADVICE)
    entry = {"src": half.rel(src), "state": "renaming", "how": "link", "time": _now()}
    if target is not None:
        entry["target"] = target
        entry["was"] = _symlink_text(src)        # what the old entry held (settle_renames)
    half.journal.items[key] = entry
    half.journal.save()
    try:
        if target is None:
            os.rename(src, dest)
        else:
            os.symlink(target, dest, target_is_directory=os.path.isdir(src))
    except OSError as e:
        half.journal.items.pop(key, None)
        half.journal.save()
        raise _link_stop(src, dest, "it couldn't be renamed there (%s)" % _reason(e))
    if target is not None:
        try:
            _unlink_link(src)
        except OSError as e:
            # Made at its new home; the old entry stays journalled "renaming", and the next
            # start removes it (settle_renames).
            raise _Failed("couldn't remove the old link %s (%s)" % (src, _reason(e)), e)
    _fsync_dir(dest.parent)
    half.journal.made(key)
    half.tick()
    if target is None:
        half.report.item("Moved the link %s to %s (what it points at was not touched).",
                         half.rel(src), half.rel(dest))
    else:
        half.report.item("Moved the link %s to %s, its target written as %s from there so it "
                         "still points at the same place (what it points at was not "
                         "touched).", half.rel(src), half.rel(dest), target)
    return "moved"


def _bring(src, dest, kind, half, vouched=False):
    """Bring the file `src` to `dest` (see the module's rules). On one volume that is one
    rename (the art pack, a Loom export: nothing is copied); across volumes, or for a
    database, the safe copy: temp, verify, swap, then delete the source. Either way the
    journal says so first. A link is brought as a link (_bring_link). Returns "moved",
    "removed", "merged", "parked", or None when there was nothing at `src`. Raises _Failed
    (MoveStopped for a link that can't be moved)."""
    src, dest = Path(src), Path(dest)
    if kind == "link" or _is_link(src):
        return _bring_link(src, dest, half)
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
            entry = {"src": half.rel(src), "state": "renaming", "time": _now()}
            if kind != "log" and src.stat().st_size <= SMALL_RECORD_BYTES:
                # A small record's very bytes are journalled here too, as the copy below
                # journals them: a copy of it put back later is known.
                entry["src_sha256"] = _sha256(src)
            half.journal.items[key] = entry
            half.journal.save()
            try:
                _rename_into(src, dest)
            except OSError:
                half.journal.items.pop(key, None)        # copy it instead, below
            else:
                _fsync_dir(dest.parent)
                half.journal.made(key, how="renamed")
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
        _replace(tmp, dest)
        _fsync_dir(dest.parent)
        half.journal.made(key)
        _remove(src)
        half.tick()
        half.report.item("Moved %s to %s (copied, checked, then removed from the old place).",
                         half.rel(src), half.rel(dest))
        return "moved"
    except _Failed:
        raise
    except (OSError, sqlite3.Error) as e:
        _discard(tmp)
        raise _Failed("couldn't move %s (%s)" % (src, _reason(e)), e)


def _bring_or_say(src, dest, kind, half, vouched=False):
    """_bring(), except that an old log that still can't be moved (a refusal, a scanner's
    hold that outlasts the retries) is left for the next start: nothing reads a log's old
    place, and the new log starts in local/logs/. A library's old moonglade.log that another
    program holds open does stop the start, before anything moves (_old_log_in_use): an older
    Moonglade may still be serving that library. Every other item that can't be moved stops
    the start."""
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
        _replace(tmp, dest)
    except OSError as e:
        raise _Failed("couldn't copy %s (%s)" % (src, _reason(e)), e)
    finally:
        _discard(tmp)


def _files_under(folder):
    """Every file under `folder`, sorted, transients included (the caller decides). A link is
    never walked into, and is not a file here (_scan gives the links)."""
    return _scan(folder)[0]


def _prune_empty(folder):
    """Remove `folder` and the folders under it that hold nothing at all. A link is never
    walked into or removed, so a folder holding one stays."""
    folder = Path(folder)
    if _is_link(folder) or not folder.is_dir():
        return
    dirs, stack = [], [folder]
    while stack:
        d = stack.pop()
        dirs.append(d)
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            p = Path(e.path)
            try:
                if not _is_link(p) and e.is_dir(follow_symlinks=False):
                    stack.append(p)
            except OSError:
                continue
    for d in sorted(dirs, key=lambda p: -len(str(p))):
        try:
            os.rmdir(d)
        except OSError:
            pass


def _is_pytest_cache(folder):
    """A folder pytest made for its cache: it carries pytest's CACHEDIR.TAG."""
    try:
        with open(Path(folder) / "CACHEDIR.TAG", "rb") as f:
            return f.read(len(_CACHEDIR_SIGNATURE)) == _CACHEDIR_SIGNATURE
    except OSError:
        return False


def _only_dead_python(folder):
    """True when `folder` is a real folder (not a link) holding nothing but what Python and
    pytest made -- compiled bytecode (.pyc) in __pycache__ folders, and pytest's own cache
    folders -- or nothing at all. False the moment it holds a link or any other file: a folder
    holding a real file is never the app's to remove."""
    folder = Path(folder)
    if _is_link(folder) or not folder.is_dir():
        return False
    files, links = _scan(folder)
    if links:
        return False
    for f in files:
        if f.parent.name == "__pycache__" and f.suffix.lower() in (".pyc", ".pyo"):
            continue
        p, ok = f.parent, False
        while True:
            if p.name == ".pytest_cache" and _is_pytest_cache(p):
                ok = True
                break
            if p == folder or p == p.parent:
                break
            p = p.parent
        if not ok:
            return False
    return True


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
                if _is_link(path) or not path.is_file():
                    continue                     # never what a link points at
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
        _replace(tmp, target)
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as e:
        _discard(tmp)
        raise _Failed("couldn't make the safety snapshot in %s (%s)" % (snap, _reason(e)),
                      e if isinstance(e, (OSError, sqlite3.Error)) else None)
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

    def _port_bad(v):
        """Why `v` can't be the port, or None."""
        try:
            return None if 1 <= int(v) <= 65535 else "it isn't a port number"
        except (TypeError, ValueError):
            return "it isn't a port number"

    def _library_bad(v):
        """Why `v` can't be the library, or None: never the program's own folder (#11)."""
        p = Path(str(v)).expanduser()
        if not p.is_absolute():
            p = _paths.library_anchor() / p
        return library_refusal(p)

    contests = (
        (_settings.LIBRARY_DIR, "library folder",
         [("serve.txt --out", flags["out"]),
          ("config.json LIBRARY_DIR", str(cfg.get("LIBRARY_DIR") or "").strip() or None)],
         _library_bad),
        (_settings.HOST, "host", [("serve.txt --host", flags["host"]),
                                  ("config.json HOST", cfg.get("HOST"))], lambda v: None),
        (_settings.PORT, "port", [("serve.txt --port", flags["port"]),
                                  ("config.json PORT", cfg.get("PORT"))], _port_bad),
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

    for key, label, candidates, bad in contests:
        live = []
        for where, v in candidates:
            if v in (None, ""):
                continue
            why = bad(v)
            if why:
                # Kept out of settings.json (what it held stays), and said in the log.
                note("The %s from %s (%s) was not used: %s.", label, where, v, why)
            else:
                live.append((where, v))
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
    cause = e.cause if isinstance(e, _Failed) else \
        (e if isinstance(e, (OSError, sqlite3.Error)) else None)
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
    linked_logs = []
    for name in LAUNCHER_LOGS:
        for src in (local / name, old / name):
            if _is_link(src):
                linked_logs.append(src)          # left where it is: nothing reads an old log
                continue
            moves.append((src, _paths.logs_dir() / name, "log"))
    # (An icon cache that is a junction or a link -- or sits in one -- is never walked: its
    # .ico files stay where the link points, and the leftover below removes the link alone.)
    old_icon_dirs = [(old / OLD_ICON_CACHE / "marks", old), (local / "cache" / "marks", local)]
    for d, root in old_icon_dirs:
        if _via_link(d, root):
            continue
        for ico in _files_under(d):
            if ico.suffix.lower() == ".ico":
                moves.append((ico, _paths.icons_dir() / ico.name, "cache"))
    # A leftover inside a link (local\cache a junction, say) is never removed: that would
    # delete inside what the link points at. One that is itself a link goes as the link alone.
    leftovers, in_links = [], []
    for p, root in ((local / OLD_RECORD, local), (local / OLD_LOCK, local),
                    (old / OLD_ICON_CACHE, old), (local / "cache" / "marks", local)):
        if not (p.exists() or _is_link(p)) or _same(p, local):
            continue
        if not _is_link(p) and _via_link(p.parent, root):
            in_links.append(p)
            continue
        leftovers.append(p)
    # The app's own dead files at the install root (S9): never left for the person to delete.
    dead = [old / n for n in DEAD_ROOT_FILES if (old / n).is_file()]
    stray_db = old / "catalog.db"
    try:
        if stray_db.is_file() and stray_db.stat().st_size == 0:
            dead.append(stray_db)                # an empty stray, never a real catalog
    except OSError:
        pass
    # The dead Python leftovers at the root (bytecode, pytest's cache, the emptied tests\ and
    # tools\): rebuildable or dead, so never in the snapshot. One holding a real file stays.
    dead_python = [old / n for n in DEAD_ROOT_FOLDERS
                   if not _same(old / n, local) and _only_dead_python(old / n)]
    same_folder = _same(old, local)
    stray_marker = old / PACK_MARKER
    has_work = (pending_merge or leftovers or dead or dead_python
                or (not same_folder and stray_marker.is_file())
                or any(Path(s).is_file() and not _same(s, d) for s, d, _k in moves))
    if not has_work:
        if not j.doc.get("finished"):
            j.finish()
        return
    # A link that can't move as a link stops the start here, before the settings merge
    # removes serve.txt and branding.json (the next start finds the state as it was).
    stuck = _install_links_stuck(moves, old, local, same_folder)
    if stuck:
        raise _link_stop(*stuck[0])
    report.worked["install"] = True
    j.worked()
    for p in linked_logs:
        report.item("Left %s where it is: it is a link, and nothing reads an old log.",
                    half.rel(p))

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
        if p.exists() or _is_link(p):
            _remove(p)
            report.item("Removed %s: an older version's bookkeeping or icon cache.", half.rel(p))
    for p in in_links:
        report.item("Left %s where it is: it is inside a link, and what a link points at is "
                    "never touched.", half.rel(p))
    for p in dead:
        if p.exists():
            _remove(p)
            report.info("Removed %s from the app folder: nothing uses it any more.", p.name)
    for p in dead_python:
        if _only_dead_python(p):                 # still nothing of anyone's own in it
            _remove(p)
            report.info("Removed %s\\ from the app folder: it held only what Python or pytest "
                        "made for the old layout.", p.name)
    for n in DEAD_ROOT_FOLDERS:
        p = old / n
        if p.exists() and p not in dead_python and not _same(p, local):
            report.item("Left %s\\ in the app folder: it holds files of its own.", n)
    j.finish()
    report.info("The app folder is tidy: settings in local/settings.json, logs in "
                "local/logs/, shortcut icons in local/icons/.")


def _install_links_stuck(moves, old, local, same_folder):
    """The install half's links that can't move as links (_link_stuck), checked before
    anything moves: the Mirror's sign-in, and the art pack and its marker when they would be
    brought (a pack already in local\\ means the old one, link or not, is only removed; the
    marker's new home is cleared before it comes). A sign-in that is a link, with another of
    its old places holding something for the same home (#11: config.json found in the working
    directory gives it two), could only arrive after that one took the home: it stops the
    start here too, before the settings merge."""
    stuck, seen, tokens = [], set(), []
    for src, dest, kind in moves:
        if kind != "token" or not _movable(src) or _same(src, dest):
            continue
        k = os.path.normcase(os.path.abspath(src))
        if k in seen:
            continue
        seen.add(k)
        tokens.append((src, dest))
    for src, dest in tokens:
        if not _is_link(src):
            continue
        home = os.path.normcase(os.path.abspath(dest))
        others = [s for s, d in tokens
                  if s is not src and os.path.normcase(os.path.abspath(d)) == home]
        why = _link_stuck(src, dest)
        if why is not None and why[2] == "that place is already taken":
            stuck.append(why)
        elif others:
            stuck.append((src, dest, "another copy of it (%s) goes to that place too"
                          % others[0]))
        elif why:
            stuck.append(why)
    if not same_folder:
        old_pack, new_pack = old / PACK_NAME, local / PACK_NAME
        if old_pack.is_file() and not new_pack.is_file():
            if _is_link(old_pack):
                why = _link_stuck(old_pack, new_pack)
                if why:
                    stuck.append(why)
            marker = old / PACK_MARKER
            if _is_link(marker):
                why = _link_stuck(marker, local / PACK_MARKER, taken=False)
                if why:
                    stuck.append(why)
    return stuck


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
    half.loom_kv = _paths.loom_root(out) / "kv"
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
        self.moves = []          # (src, dest, kind, vouched); kind "link" moves a link as one
        self.removals = []       # files and (pruned once empty) folders
        self.dead = []           # the library's dead branding\ files, set aside, then gone
        self.kept = []           # per-login files no login can be found for: left, and said
        self.left = []           # old-home names that aren't Moonglade's by their content: left
        self.stuck = []          # (link, dest or None, why[, advice]): a link that can't
        #                          move as a link (_link_stop's arguments)
        self.snap = []           # (path, name in the zip)
        self.ours = False        # the folder is a Moonglade library (_is_moonglade_library)
        self.log_links = []      # a logs\ that is a link, or a moonglade.log* that is one: never
        #                          moved, still probed for an older install (_old_log_in_use)
        self.dead_unlink = []    # links in the dead branding\ that can't be set aside by a
        #                          rename (another drive): removed where they are, as links
        self.link_targets = {}   # {old path: the target a relative link holds at its new home}


# The Loom's own entries in its folder (3.10-3.19's <library>\loom\): the boards (kv\, and the
# store.json they were split from), the render journal, the music beds, frames, uploads and
# exports. A loom\ holding none of these is not the Loom's, and is left where it is.
LOOM_ENTRIES = ("kv", "_submits", "_beds", "_frames", "_uploads", "exports", "_exports",
                "store.json", "store.json.migrated")
# What a library's old branding\ held (before the art moved beside the launcher, 2026-07-26):
# a branding\ with none of it is someone else's.
OLD_BRANDING_ENTRIES = ("marks", "mascots", "badges", "_thumbs", "rewards", "logo.png",
                        "favicon.png", "banner.png")
# The keys a library's old branding.json held.
BRANDING_JSON_KEYS = ("mark", "anim", "anim_speed", "anim_scale", "glow_color", "glow_angle")
# The app's own logs in a library's old logs\: moonglade.log and its dated rotations.
_APP_LOG_RE = re.compile(r"^moonglade\.log(\..+)?$")
# Every version's catalog.csv began with these columns.
_CATALOG_CSV_HEAD = "task_id,media_id,filename"


def _json_doc(p):
    """The JSON document in the file `p`, or None (missing, unreadable, not JSON, a link)."""
    try:
        if _is_link(p):
            return None
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None


def _first_line(p, size=4096):
    """The first line of the file `p` ("" when it can't be read)."""
    try:
        with open(p, "rb") as f:
            return f.read(size).decode("utf-8-sig", "replace").splitlines()[0]
    except (OSError, IndexError):
        return ""


def _db_has_table(p, table):
    """Does the SQLite file `p` hold `table`? Opened read-only; a busy or broken file is "no"."""
    p = Path(p)
    if _is_link(p) or not p.is_file():
        return False
    con = None
    try:
        con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                           (table,)).fetchone() is not None
    except (sqlite3.Error, OSError, ValueError):
        return False
    finally:
        if con is not None:
            con.close()


def _child_names(folder):
    """The names directly inside `folder` -- a link's too: only its own entry list is read;
    nothing in it is opened, walked into or changed."""
    try:
        return set(os.listdir(folder))
    except OSError:
        return set()


def _is_moonglade_library(out, logins=None):
    """Is `out` a Moonglade library, rather than a folder of someone's own that only shares
    one of Moonglade's old names (logs\\, loom\\, branding\\, catalog.csv)? Yes when it holds
    something only Moonglade writes: a catalog.db with the catalog table; a record at its top
    readable as one (the achievements, telemetry, schedule, spend guard or reconcile stamp as
    a JSON object, runs.db with its runs table, a job list whose first line is a JSON object,
    the owner's integrity marks); a per-login file named by a login key (or by the plain name
    of a login config.json lists); a loom\\ holding the Loom's own entries; the gallery's
    badge, mask or banner cache; or the app's own files already in _moonglade\\. Only then do
    its old homes count as Moonglade's, and each still passes its own content check
    (_plan_library)."""
    out = Path(out)
    app = _paths.library_app_dir(out)
    if app.is_dir() and not _is_link(app):
        if _child_names(app) - {_paths.JOURNAL_NAME, _paths.LOCK_NAME, _paths.SNAPSHOT_DIRNAME}:
            return True
    if _db_has_table(out / "catalog.db", "catalog") or _db_has_table(out / "runs.db", "runs"):
        return True
    for name in ("achievements.json", "telemetry.json", "schedule.json", "train_guard.json",
                 "reconcile_stamp.json"):
        if isinstance(_json_doc(out / name), dict):
            return True
    marks = _json_doc(out / "integrity_marks.json")
    if isinstance(marks, dict) and isinstance(marks.get("marks"), dict):
        return True
    for name in ("jobs.jsonl", "raw_tasks.jsonl"):
        p = out / name
        if p.is_file() and not _is_link(p):
            try:
                if isinstance(json.loads(_first_line(p) or "null"), dict):
                    return True
            except ValueError:
                pass
    for old_name in PER_LOGIN:
        for n in _child_names(out / old_name):
            if _KEY_RE.match(n.partition(".")[0]) or _plain_name_login(n, logins):
                return True
    if _child_names(out / "gallery" / "cache") & set(LIBRARY_CACHES):
        return True                              # the gallery's own badge/mask/banner caches
    return bool(_child_names(out / "loom") & set(LOOM_ENTRIES))


def _branding_json_ours(p):
    """A library's old branding.json: a JSON object of Moonglade's branding keys only."""
    doc = _json_doc(p)
    return (isinstance(doc, dict) and bool(doc) and ("mark" in doc or "anim" in doc)
            and all(k in BRANDING_JSON_KEYS for k in doc))


def _catalog_csv_ours(p):
    """The legacy catalog export: its header begins with the catalog's first columns."""
    return not _is_link(p) and _first_line(p).replace('"', "").startswith(_CATALOG_CSV_HEAD)


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
    """What the library half would do in `out`, without doing it (a _Plan). Nothing is planned
    on a name alone (#10): a folder that isn't a Moonglade library (_is_moonglade_library)
    gets an empty plan, and in one that is, each old home passes its own content check -- in
    logs\\ only the moonglade.log files, in loom\\ only the Loom's own entries, a branding\\
    only with Moonglade's old art in it, branding.json only with Moonglade's keys, catalog.csv
    only with the catalog's header. Anything else is left where it is (plan.left) and the log
    says so. A junction or a symbolic link is never walked into (B): one found in an old home
    is moved as a link, and one that can't be (its new home is taken, or it would have to
    split) is plan.stuck: the start stops, before anything moves, with a plain sentence."""
    plan = _Plan()
    reports = app / OLD_REPORTS
    plan.ours = _is_moonglade_library(out, logins)
    if not plan.ours:
        for n in ("logs", "loom", "branding", "branding.json") + DEAD_LIBRARY_FILES:
            if os.path.lexists(out / n):
                plan.left.append(out / n)
        return plan
    # 3.20's reports\ that is itself a link: its files split between records\ and decisions\,
    # so it can't move as one link, and nothing is ever moved out through one.
    if _is_link(reports):
        plan.stuck.append((reports, None, "its files go one by one into _moonglade\\records "
                                          "and _moonglade\\decisions, so it can't move as one "
                                          "link"))
        reports = None

    def two(name, primary, secondary, dest, kind, vouch_name=None):
        if primary is not None and _movable(primary):
            plan.moves.append((primary, dest, kind, False))
            plan.snap.append((primary, half.rel(primary)))
        if _movable(secondary):
            vouched = copyfirst.unchanged(vouch_name or name, secondary)
            plan.moves.append((secondary, dest, kind, vouched))
            if not vouched:
                plan.snap.append((secondary, half.rel(secondary)))

    # Records and the reports that are records (S6).
    for name, kind in RECORDS.items():
        if name in _REPORT_NAMES:
            primary = reports / name if reports is not None else None
        else:
            primary = app / name
        two(name, primary, out / name, _paths.records_path(out, name, make=False), kind)
    # The owner's decisions.
    for name, kind in DECISIONS.items():
        two(name, reports / name if reports is not None else None, out / name,
            _paths.decisions_path(out, name, make=False), kind)
    for folder in [f for f in (reports, out) if f is not None]:
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
    # (S8); one no login can be found for stays where it is, and the log says so. A store's
    # folder that is itself a link can't move as one (its files go one by one into the logins'
    # folders): the start stops and says so.
    for old_name, new_stem in PER_LOGIN.items():
        for base, from_320 in ((app, True), (out, False)):
            folder = base / old_name
            if _is_link(folder):
                plan.stuck.append((folder, None, "its files go one by one into each login's own "
                                                 "folder in _moonglade\\accounts, so it can't "
                                                 "move as one link"))
                continue
            vouched_folder = not from_320 and copyfirst.unchanged(old_name, folder)
            files, links = _scan(folder)
            for p in files + links:
                link = p in links
                if not link and _TRANSIENT_RE.search(p.name):
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
                if link:
                    plan.moves.append((p, dest, "link", False))
                else:
                    plan.snap.append((p, half.rel(p)))
                    plan.moves.append((p, dest, "file", vouched_folder))
            plan.removals.append(folder)              # pruned once empty
    # The library's logs, into local\logs\: only Moonglade's own (moonglade.log and its
    # rotations). Nothing reads a log back, so a link here -- or a logs\ that is one -- is
    # simply left where it is, like anything else in the folder that isn't the app's.
    for base, from_320 in ((app / "logs", True), (out / "logs", False)):
        if _is_link(base):
            plan.left.append(base)
            plan.log_links.append(base)
            continue
        vouched_folder = not from_320 and copyfirst.unchanged("logs", base)
        files, links = _scan(base)
        for p in files:
            if p.parent == base and _APP_LOG_RE.match(p.name):
                plan.moves.append((p, _paths.logs_dir() / p.name, "log", vouched_folder))
        plan.log_links += [p for p in links if p.parent == base and _APP_LOG_RE.match(p.name)]
        if base.is_dir():
            plan.removals.append(base)                # pruned once empty; the rest is said
    # The Loom's own entries, into _moonglade\loom\. A loom\ that is a link (the Loom kept on
    # another drive) moves as the link, when its entries are the Loom's.
    loom_old, loom_new = out / "loom", _paths.loom_root(out)
    if _is_link(loom_old):
        if _child_names(loom_old) & set(LOOM_ENTRIES):
            plan.moves.append((loom_old, loom_new, "link", False))
        else:
            plan.left.append(loom_old)
    elif loom_old.is_dir():
        names = _child_names(loom_old)
        if names & set(LOOM_ENTRIES):
            for n in sorted(names):
                e = loom_old / n
                if n not in LOOM_ENTRIES:
                    if not _is_link(e) and e.is_file() and _TRANSIENT_RE.search(n):
                        plan.removals.append(e)
                    else:
                        plan.left.append(e)
                    continue
                if _is_link(e):
                    files, links = [], [e]
                elif e.is_file():
                    files, links = [e], []
                else:
                    files, links = _scan(e)
                for p in files:
                    rel = p.relative_to(loom_old)
                    if _TRANSIENT_RE.search(p.name):
                        plan.removals.append(p)
                        continue
                    kind = "lines" if rel.parts[0] == "_submits" and p.suffix == ".jsonl" \
                        else "file"
                    plan.moves.append((p, loom_new / rel, kind, False))
                    if rel.parts[0] not in _LOOM_UNSNAPPED:
                        plan.snap.append((p, half.rel(p)))
                for p in links:
                    plan.moves.append((p, loom_new / p.relative_to(loom_old), "link", False))
            plan.removals.append(loom_old)
        else:
            plan.left.append(loom_old)
    # Dead copies nothing reads: the library's old branding.json and the legacy catalog.csv
    # (in the zip, then removed), and its old branding\ folder (every file in it set aside in
    # the snapshot, so it goes with the snapshot rather than stay forever; a link in it is set
    # aside as a link). Each only when its content is Moonglade's.
    for p, ours in [(out / "branding.json", _branding_json_ours)] + \
            [(out / n, _catalog_csv_ours) for n in DEAD_LIBRARY_FILES]:
        if os.path.lexists(p):
            if p.is_file() and not _is_link(p) and ours(p):
                plan.snap.append((p, half.rel(p)))
                plan.removals.append(p)
            else:
                plan.left.append(p)
    branding = out / "branding"
    if _is_link(branding):
        plan.left.append(branding)
    elif branding.is_dir():
        if _child_names(branding) & set(OLD_BRANDING_ENTRIES):
            files, links = _scan(branding)
            plan.dead = files + links
            plan.removals.append(branding)
            # A link is set aside by renaming it beside the safety copy; where that is on
            # another drive it can't be, so the link entry alone is removed where it is (what
            # it points at is never touched) -- decided now, never a stop after the records.
            plan.dead_unlink = [
                p for p in links if not _same_device(
                    p, half.snapshot_dir / PARKED_DIRNAME / half.rel(p).replace(":", "_"))]
        else:
            plan.left.append(branding)
    # 3.20's bookkeeping.
    bookkeeping = [app / OLD_RECORD, app / OLD_LOCK, out / "telemetry.lock",
                   app / "telemetry.lock", out / "integrity_report.lock",
                   out / "jobs.jsonl.tmp", app / "jobs.jsonl.tmp"]
    if reports is not None:
        bookkeeping.append(reports / "integrity_report.lock")
    for p in bookkeeping:
        if p.is_file() and not _is_link(p):
            if p.name == OLD_RECORD:
                plan.snap.append((p, half.rel(p)))
            plan.removals.append(p)
    if reports is not None:
        plan.removals.append(reports)
    # A cache inside a linked folder, and a _banners\ that is a link or holds a linked render
    # (_banners_linked), are left and said (_caches).
    for c in LIBRARY_CACHES:
        p = out / "gallery" / "cache" / c
        if (_via_link(p.parent, out) and c in _child_names(p.parent)) or \
                (c == "_banners" and _banners_linked(p)):
            plan.left.append(p)
    # A link that can't move as a link stops the start before anything moves: its new home is
    # taken, or another planned source goes there too (it could only arrive after that one
    # took it), or it is on another drive, or it points by a relative path the move can't
    # keep right (the target it would need is worked out through the plan itself, #9), or by
    # a full path into something the plan takes or empties (a junction included), or on
    # Windows a relative path that would have to change. Any source that is a link counts,
    # whatever kind the plan gave it (a record, a decision or a curation file can be one).
    plan.link_targets, cant = _plan_link_targets(plan.moves, plan.removals)
    going = {}
    for src, dest, _k, vouched in plan.moves:
        # (A file 3.20 already copied, unchanged since, is only removed once its home is
        # there: it never lands on a link.)
        if _movable(src) and not (vouched and not _is_link(src)):
            going.setdefault(os.path.normcase(str(dest)), []).append(src)
    for src, dest, kind, _v in plan.moves:
        if not (kind == "link" or _is_link(src)) or _same(src, dest):
            continue
        k = os.path.normcase(str(src))
        others = [s for s in going.get(os.path.normcase(str(dest)), []) if s is not src]
        stuck = _link_stuck(src, dest, link_target=plan.link_targets.get(k, _UNPLANNED))
        if stuck is not None and stuck[2] == "that place is already taken":
            plan.stuck.append(stuck)
        elif others:
            plan.stuck.append((src, dest, "another copy of it (%s) goes to that place too"
                               % others[0]))
        elif k in cant:
            plan.stuck.append((src, dest) + tuple(cant[k]))
        elif stuck is not None:
            plan.stuck.append(stuck)
    return plan


def _movable(p):
    """Is there something at `p` to move: a file, or a link (moved as a link)?"""
    return _is_link(p) or Path(p).is_file()


# A login's key in the library: the first 16 hex digits of its name's sha256 (never the
# command line's own _local folder, which is not a login).
_LOGIN_KEY_RE = re.compile(r"^[0-9a-f]{16}$")


def _preset_keys(out, logins, plan):
    """The login keys the shared preset files go to: this install's logins (config.json), and
    every login key the library already holds -- a folder in accounts\\, a folder of Loom
    boards, a render journal in the Loom's _submits\\, or one the plan is moving there. In
    3.10-3.19 every login with no file of its own saw the shared files, another install's on
    the same library too. An empty set when there is no login to give them to; None while this
    install's logins can't be known (no readable config.json): nothing is given out on a
    guess."""
    if logins is None:
        return None
    keys = {_paths.account_key(u) for u in logins}
    loom = _paths.loom_root(out)
    homes = [Path(d) for _s, d, _k, _v in plan.moves]
    for folder in (_paths.accounts_dir(out), loom / "kv", loom / "_submits"):
        names = set(_child_names(folder))
        names.update(d.relative_to(folder).parts[0] for d in homes if _under(d, folder))
        for n in names:
            key = n[:-len(".jsonl")] if folder.name == "_submits" and n.endswith(".jsonl") else n
            if _LOGIN_KEY_RE.match(key):
                keys.add(key)
    return keys


def _shared_presets(half, out, app, copyfirst, keys, report):
    """The three install-wide preset files: copied into each login with no file of its own --
    this install's, and every one the library already holds (_preset_keys) -- then deleted.
    Left alone, with a log line, while there is no login to give them to."""
    for name, new_name in SHARED_PRESETS.items():
        paths = [p for p in (app / name, out / name) if p.is_file() and not _is_link(p)]
        if not paths:
            continue
        if not keys:
            report.warn("%s was left where it is: there is no login to give it to yet.",
                        half.rel(paths[0]))
            continue
        half.report.worked["library"] = True
        primary = paths[0]
        for key in sorted(keys):
            dest = _paths.accounts_dir(out) / key / new_name
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
    if _via_link(folder, out) or _banners_linked(folder) or not folder.is_dir():
        return             # through a link, or holding a linked render: left, never read from
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
    """The library's rebuildable caches that are there to delete: one that is a link goes as
    the link alone -- except a _banners\\ that is a link or holds a linked render
    (_banners_linked), which may hold the only copy of a banner the install wears and can't be
    read out of the link -- and one inside a linked folder is never touched (both are left,
    and said: _plan_library)."""
    out = Path(out)
    found = []
    for c in LIBRARY_CACHES:
        p = out / "gallery" / "cache" / c
        if _via_link(p.parent, out) or (c == "_banners" and _banners_linked(p)):
            continue
        if os.path.lexists(p):
            found.append(p)
    return found


def _banners_linked(folder):
    """Is the library's banner render cache a link, or does it hold a render a library may
    wear (BANNER_FLATS) that is a link? Such a render may be the only copy of the banner the
    install wears, and could only move into local\\banners\\ -- on another drive, for a
    library away from the program -- by being read through the link: the folder is left where
    it is, and said, like a _banners\\ that is itself a link."""
    folder = Path(folder)
    return _is_link(folder) or any(_is_link(folder / n) for n in BANNER_FLATS.values())


def _shared_files(out, app, keys):
    """The shared preset files there are to give out: none while no login can take them
    (_preset_keys), so that they are not work for every start."""
    if not keys:
        return []
    return [p for n in SHARED_PRESETS for p in (app / n, out / n)
            if p.is_file() and not _is_link(p)]


def _has_work(plan, shared, caches):
    """Is there anything to move, merge, set aside or remove -- or a link that stops the start?
    A folder still holding only what the plan leaves (a file no login can be found for,
    something that isn't Moonglade's) is not work: it is said once, by the start that emptied
    the rest, or every start would count as one that moved something."""
    return (any(_movable(s) for s, _d, _k, _v in plan.moves)
            or any(Path(p).is_file() and not _is_link(p) for p in plan.removals)
            or any(Path(p).is_dir() and not _is_link(p) and _empty_tree(p)
                   for p in plan.removals)
            or bool(plan.dead) or bool(plan.stuck) or bool(shared)
            or any(os.path.lexists(c) for c in caches))


def _mtime_ns(p):
    """`p`'s own modified time (a link's own, never what it points at), or None."""
    try:
        return os.lstat(p).st_mtime_ns
    except OSError:
        return None


def _made_at(entry):
    """When the move made the new home a journal entry names, in seconds on the disk's clock
    (made_ns), else by the entry's own stamp; None for an entry the move hasn't made."""
    if not isinstance(entry, dict) or entry.get("state") not in ("made", "verified"):
        return None
    ns = entry.get("made_ns")
    if isinstance(ns, int) and ns > 0:
        return ns / 1e9
    try:
        return float(calendar.timegm(time.strptime(entry.get("time"), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _written_after_made(src, entry, half):
    """Was the old-layout copy `src` written after the move made its new home (`entry`)? It was
    when it sits at the very old place the move took that home from (the move emptied it), or
    when its own time is later than the home's (_made_at)."""
    if entry.get("src") is not None and entry.get("src") == half.rel(src):
        return True
    t, ns = _made_at(entry), _mtime_ns(src)
    return t is not None and ns is not None and ns / 1e9 > t + WRITTEN_SINCE_SLACK_S


def _written_since(half, plan, shared):
    """[(path, mtime_ns)] of old-layout files written after this library's move last
    finished: an older Moonglade still using the library writes its old homes (its
    moonglade.log and its records), and nothing of this version ever does. Before the first
    move has finished (one cut short), an old-layout file written after the move made its own
    new home counts the same way."""
    since = half.journal.finished_at()
    if since is not None:
        times = [(s, since) for s, _d, _k, _v in plan.moves] + [(p, since) for p in shared]
    else:
        times = [(s, _made_at(half.journal.items.get(half.rel(d))))
                 for s, d, _k, _v in plan.moves]
    out = []
    for p, t in times:
        ns = _mtime_ns(p)
        if t is not None and ns is not None and ns / 1e9 > t + WRITTEN_SINCE_SLACK_S:
            out.append((Path(p), ns))
    return out


def _old_layout_records(plan):
    """The files at old places that this version would read in a new home: every record,
    decision, per-login store and the Loom (not the logs, which nothing reads back), and any
    link the move would carry. Not the shared preset files: only the gallery reads presets,
    snippets and views, never the command line or the MCP server."""
    return [Path(s) for s, _d, k, _v in plan.moves if k != "log" and _movable(s)] + \
        [Path(stuck[0]) for stuck in plan.stuck]


def _names(paths, half, most=3):
    rels = [half.rel(p) for p in paths]
    more = len(rels) - most
    return ", ".join(rels[:most]) + (" and %d more" % more if more > 0 else "")


# How to stop an older Moonglade that is still using a library. Its server (3.10-3.19, started
# from that version's launcher) runs under pythonw with no window of its own: closing its
# browser tab leaves it serving. Control Panel -> Server -> Stop server is what stops it.
STOP_OLDER_WORDS = (
    "Stop that Moonglade with Stop server in its Control Panel, or end its python or pythonw "
    "process (closing its browser tab doesn't stop it). Turn off its scheduled tasks, and any "
    "service that starts it on Linux or macOS, and close its Claude tools.")


def _older_live_words(out, written, half, moving):
    head = ("An older Moonglade is still using the library %s: it wrote %s after this version "
            "moved the library's files into _moonglade. " % (out, _names(written, half)))
    if moving:
        return head + ("Moving them now, while it runs, would hide its records from it. " +
                       STOP_OLDER_WORDS + " Then start this one again: it brings in what that "
                       "one wrote, and keeps everything already here.")
    return head + ("This command never moves a library's files. " + STOP_OLDER_WORDS +
                   " Then start this one with its launcher (Moonglade Launcher) to bring in "
                   "what it wrote.")


def _refusal_words(out, named):
    if named:
        return ("The library %s is still in an older Moonglade's layout, and a run that names "
                "its own library (--out or MOONGLADE_OUT) never moves one. Open it once with "
                "the launcher of the Moonglade it belongs to, updated to this version, then "
                "run this again." % out)
    return ("The library %s is still in an older Moonglade's layout. Open it once with this "
            "install's launcher (Moonglade Launcher), then run this again." % out)


# The sentence when something still holds a library's old log open (#12): at the first move,
# and before bringing in what an older Moonglade wrote after it -- before anything moves, so
# an older install's records are never taken from under it. Filled with the log, then the
# library. Moonglade can tell only when both installs run on Windows and open the same folder
# (a shared folder or a NAS share), never a sync tool's separate copy on another PC.
OLDER_RUNNING_WORDS = (
    "Another program has %s open, so Moonglade can't tidy the library %s yet. It may be an "
    "older Moonglade still running on that library, on this PC or another Windows PC: stop it "
    "with Stop server in its Control Panel, or end its python or pythonw process (closing its "
    "browser tab doesn't stop it), and stop its scheduled tasks and any service that starts "
    "it. Otherwise close the program that has the file open. Then start Moonglade again.")


def _held_open(p):
    """Does another program hold the file `p` open? Windows refuses to rename a file another
    program has open without sharing its delete (a sharing or lock violation), so `p` is
    renamed onto itself, and held only when every one of REMOVE_TRIES tries is refused, with
    the same growing pause as a swap: a moment's hold (a sync tool or a virus scan reading the
    last lines) is waited out. Off Windows nothing is refused, and nothing is held."""
    for attempt in range(REMOVE_TRIES):
        try:
            os.rename(p, p)
            return False
        except PermissionError as e:
            if getattr(e, "winerror", None) not in (32, 33):
                return False
        except OSError:
            return False
        if attempt + 1 < REMOVE_TRIES:
            time.sleep(REMOVE_BACKOFF_S * (2 ** attempt))
    return True


def _same_file(a, b):
    """Are `a` and `b` one file (one path, or two names for the same file)?"""
    if _same(a, b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _link_file(p):
    """The file the link `p` points at, by its full path, or None (not a file, or unreadable)."""
    try:
        real = Path(os.path.realpath(p))
    except (OSError, ValueError):
        return None
    return real if real.is_file() and not _is_link(real) else None


def _old_logs(plan):
    """[(the file to probe, the path to name)]: every old moonglade.log* the plan moves, and
    those it leaves because they sit in a linked logs\\ (probed through the link) or are
    links themselves (probed by the file each points at)."""
    out = []
    for src, dest, kind, _v in plan.moves:
        if kind == "log" and not _is_link(src) and Path(src).is_file() \
                and not _same_file(src, dest):
            out.append((Path(src), Path(src)))
    for p in plan.log_links:
        p = Path(p)
        if _APP_LOG_RE.match(p.name):            # a moonglade.log that is a link
            entries = [p]
        else:                                     # a logs\ that is a link
            entries = [p / n for n in sorted(_child_names(p)) if _APP_LOG_RE.match(n)]
        for e in entries:
            real = _link_file(e) if _is_link(e) else (e if e.is_file() else None)
            if real is not None and not _same_file(real, _paths.logs_dir() / e.name):
                out.append((real, e))
    return out


def _old_log_in_use(plan):
    """The first old-layout log another program still holds open (_held_open), or None. A
    server before 3.20 kept its log in the library's logs\\ open while it ran, on this PC or
    another Windows PC, so a held old log means one may still be serving the library -- in a
    linked logs\\ too, and through a log that is a link (renaming a file onto itself, through
    the link or at the file it points at, changes nothing). A log that is the same file as its
    new home (a library inside this install's own local\\) is this install's own, and is
    skipped."""
    for probe, named in _old_logs(plan):
        if _held_open(probe):
            return named
    return None


def library_refusal(path):
    """Why `path` can never be a library, in plain words ("it is Moonglade's own program
    folder"), or None. A library is a folder of its own: never the install folder, nor a folder
    holding an install -- its code (moonglade\\ with the package in it), its machine folder
    (local\\ with its settings or journal), its launcher, or an older install's server file
    (moonglade_gallery.py, at the root through 3.19). The move would otherwise take the
    Loom's code for the Loom's data (#11). The Control Panel, the settings merge and every
    start ask this."""
    p = Path(path)
    try:
        if _same(p, old_app_root()):
            return "it is Moonglade's own program folder"
        if ((p / "moonglade" / "__init__.py").is_file()
                or (p / _paths.LAUNCHER_NAME).is_file()
                or (p / "moonglade_gallery.py").is_file()       # an install before 3.20
                or (p / _paths.LOCAL_DIRNAME / _paths.SETTINGS_NAME).is_file()
                or (p / _paths.LOCAL_DIRNAME / _paths.JOURNAL_NAME).is_file()):
            return "it holds a Moonglade program (its code, its local folder or its launcher)"
    except (OSError, ValueError):
        return None
    return None


def _install_folder_words(out, why, named):
    if named:
        return ("The library %s that this run names can't be used: %s, and a library has to "
                "be a folder of its own. Name your library's own folder, then run this again."
                % (out, why))
    return ("Moonglade's library folder is set to %s, which can't be a library: %s, and a "
            "library has to be a folder of its own. Set library_dir in %s to your library's "
            "own folder (or remove that line to use %s), then start Moonglade again." % (
                out, why, _paths.settings_path(), _paths.DEFAULT_LIBRARY_DIR))


def prepare_library(out_dir, report, moves, named=False, wait=None):
    """The library half as prepare() runs it (X1). `moves`: this start may move this
    library's files (a launcher or server start, in the library this install serves).

      * A library that is the program's own folder, or holds a program (library_refusal), is
        refused by every kind of start, with a plain sentence (#11).
      * A library whose move finished and whose old homes were written since is in use by an
        older Moonglade: every kind of start stops and says so.
      * A start that may not move (the command line, the MCP server, a run naming its own
        library) refuses a library still in an older layout -- it would read empty new
        homes -- and otherwise changes nothing in it.
      * With nothing to do, nothing is locked: a read-only library still opens. A start that
        may move stamps the library's journal finished, when it can (and says once what it
        left in a folder that isn't a Moonglade library).
      * Otherwise the move runs under the library's lock (migrate_library).
    Raises MoveStopped."""
    out = Path(out_dir)
    why = library_refusal(out)
    if why:
        raise MoveStopped(_install_folder_words(out, why, named))
    app = _paths.library_app_dir(out)
    logins = logins_from_config()
    look = _Half("library", app, _library_roots(out), Report())
    plan = _plan_library(out, app, CopyFirst(app / OLD_RECORD), logins, look)
    shared = _shared_files(out, app, _preset_keys(out, logins, plan)) if plan.ours else []
    if not moves:
        written = _written_since(look, plan, shared)
        if written:
            raise MoveStopped(_older_live_words(out, [p for p, _ns in written], look, False))
        if _old_layout_records(plan):
            raise MoveStopped(_refusal_words(out, named))
        return None
    if not _has_work(plan, shared, _caches(out) if plan.ours else []):
        renaming = any(isinstance(e, dict) and e.get("state") == "renaming"
                       for e in look.journal.items.values())
        if not look.journal.doc.get("finished") or renaming:
            if plan.left and not look.journal.doc.get("finished"):
                _say_left(plan, look, report)
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


def _say_left(plan, half, report):
    """One line naming what the move left because it isn't Moonglade's by its content."""
    one = len(plan.left) == 1
    report.info("Left %s where %s: %s Moonglade's by %s content, so the move doesn't touch %s.",
                _names(plan.left, half, most=10), "it is" if one else "they are",
                "it isn't" if one else "they aren't", "its" if one else "their",
                "it" if one else "them")


def _library_half(half, out, app, copyfirst, logins, report):
    j = half.journal
    if not j.doc.get("started"):
        j.doc["started"] = _now()
    # A rename cut short is settled first: it can finish one (a link made again at its new
    # home whose old entry is still there), which the plan must not take for a taken home.
    if half.settle_renames():
        j.save()
    plan = _plan_library(out, app, copyfirst, logins, half)
    keys = _preset_keys(out, logins, plan)
    shared = _shared_files(out, app, keys) if plan.ours else []
    caches = _caches(out) if plan.ours else []
    if not _has_work(plan, shared, caches):
        if not j.doc.get("finished"):
            j.finish()
        elif j.doc.pop("held_back", None) is not None:
            j.save()
        return
    # An older Moonglade still on this library: stop, unless the person was told and nothing
    # more has been written there since (they closed it and started this one again). "Nothing
    # more" is every file written since being one the stop named, with the same time: a
    # bring-in cut short has already folded some of them in. held_back stays until this run
    # finishes, so a start after one cut short carries on rather than blame an older install.
    written = _written_since(half, plan, shared)
    if written:
        files = {half.rel(p): ns for p, ns in written}
        held = j.doc.get("held_back")
        known = held.get("files") if isinstance(held, dict) else None
        if not isinstance(known, dict) or any(known.get(k) != ns for k, ns in files.items()):
            j.doc["held_back"] = {"at": _now(), "files": files}
            j.save()
            raise MoveStopped(_older_live_words(out, [p for p, _ns in written], half, True))
    # Something still holds an old log open -- an older Moonglade serving this library (on
    # this PC or another Windows PC), idle or not: stop before any of its records move (#12),
    # at the first move and at every bring-in alike (an idle one writes nothing between two
    # starts, so the rule above alone would let the second through). held_back is kept.
    held_log = _old_log_in_use(plan)
    if held_log is not None:
        raise MoveStopped(OLDER_RUNNING_WORDS % (held_log, out))
    if written:
        report.info("Bringing in what an older Moonglade wrote to %s after the move: %s. The "
                    "new homes keep everything they hold; what it added is merged in.",
                    out, _names([p for p, _ns in written], half))
    # A link that can't move as a link stops the start before anything moves (B).
    if plan.stuck:
        raise _link_stop(*plan.stuck[0])
    # The library's move had finished before this run: an old-layout copy now was written
    # since, and the new home always wins (A). Before that, the first move's rules hold.
    half.settled = bool(j.doc.get("finished"))
    half.link_targets = plan.link_targets
    report.worked["library"] = True
    j.worked()
    app.mkdir(parents=True, exist_ok=True)
    # The safety snapshot: the small records about to move, the shared preset files, the
    # banner renders that may be the only copy, and 3.20's record.
    snap = list(plan.snap) + [(p, half.rel(p)) for p in shared]
    # A fold writes telemetry.json's new home in place: its own copy goes into this run's zip
    # first, beside the older copy (after the move, or where this move already made it).
    homes = {Path(d) for s, d, k, _v in plan.moves
             if k == "json:telemetry" and _movable(s) and Path(d).is_file()
             and (half.settled or _made_at(j.items.get(half.rel(d))) is not None)}
    snap += [(d, half.rel(d)) for d in sorted(homes)]
    bfolder = out / "gallery" / "cache" / "_banners"
    for name in BANNER_FLATS.values():
        for p in (bfolder / name, bfolder / (name + ".json")):
            if p.is_file():
                snap.append((p, half.rel(p)))
    _make_snapshot(half, snap)
    # Links first (#10): each was planned against its target's files where they are now, so
    # it moves before any of them do. A start cut short between the two then never finds a
    # link whose target's files have already left (it would see an emptied folder, and stop
    # or point the link at the old place the move then prunes).
    links_first = sorted(plan.moves, key=lambda m: 0 if (m[2] == "link" or _is_link(m[0]))
                         else 1)
    moved = 0
    for src, dest, kind, vouched in links_first:
        if _bring_or_say(src, dest, kind, half, vouched=vouched) == "moved":
            moved += 1
    if plan.dead:
        set_aside = []
        for p in [p for p in plan.dead if _movable(p)]:
            if p in plan.dead_unlink and _is_link(p):
                _remove(p)
                report.item("Removed the link %s: the safety copy is on another drive, so it "
                            "couldn't be set aside there (what it points at was not touched).",
                            half.rel(p))
                continue
            _park(p, half, said=False)
            set_aside.append(p)
        if set_aside:
            report.info("Set aside the library's old branding folder (%s) with the safety copy: "
                        "nothing uses it any more, and it goes when the safety copy does.",
                        _names(set_aside, half, most=10))
    for p in plan.kept:
        if _movable(p):
            report.warn("Left %s where it is: no login in config.json goes by that name.",
                        half.rel(p))
    if plan.left:
        _say_left(plan, half, report)
    _shared_presets(half, out, app, copyfirst, keys, report)
    _banners(half, out, report)
    # Caches: deleted once the new home exists (they are rebuilt in local\cache\). A cache
    # folder that is a link goes as the link alone: what it points at is never touched.
    _paths.cache_dir().mkdir(parents=True, exist_ok=True)
    for c in caches:
        if os.path.lexists(c):
            link = _is_link(c)
            _remove(c)
            if link:
                report.item("Removed the link %s: a cache, made again when it is needed (what "
                            "it pointed at was not touched).", half.rel(c))
            else:
                report.item("Removed %s: a cache, made again when it is needed.", half.rel(c))
    for p in plan.removals:
        if _is_link(p) or not p.exists():
            continue
        if p.is_dir():
            _prune_empty(p)
            files, links = _scan(p)
            left = [x for x in files + links if x not in plan.kept]
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
    j.doc.pop("held_back", None)
    j.finish()

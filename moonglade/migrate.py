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

moonglade.setup.prepare() runs both, in that order, before anything reads a setting.

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
  * THE SNAPSHOT (the owner's pick 4). Before a half's first move, the small records it is
    about to move are zipped into its .snapshot\\ -- never pictures, catalog.db, the art pack,
    the logs, a cache, or the Mirror's sign-in (a stale token is a credential lying around).
    Parked copies go beside the zip. The journal counts clean server starts once the move has
    finished (count_clean_start); at CLEAN_STARTS the app deletes .snapshot\\.
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
  * A FAILURE STOPS THE START (MoveStopped, with a plain sentence): a lock held past its wait,
    a file that cannot be copied or removed, an unreadable config.json while the settings are
    still to merge. Carrying on would read empty new homes.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import sys
import time
import zipfile
from pathlib import Path

from moonglade import paths as _paths

LOGGER_NAME = "moonglade.migrate"
JOURNAL_FORMAT = 1
LOCK_WAIT_S = 60.0           # how long a start waits for another start's move
LOCK_STALE_S = 300.0         # a lock untouched this long was left by a process that died
CLEAN_STARTS = 5             # clean server starts after which .snapshot\ is deleted (pick 4)
MOVING_SUFFIX = ".moving"    # the temp a copy is made into, beside its destination
PARKED_DIRNAME = "parked"

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
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log():
    return logging.getLogger(LOGGER_NAME)


# ---- what one run did -------------------------------------------------------------------------
class Report:
    """What a prepare() run did, as plain log lines (written once logging is up: log()), and
    whether each half found anything to do (worked) or parked anything."""

    def __init__(self):
        self.lines = []
        self.worked = {"install": False, "library": False}
        self.parked = 0

    def info(self, msg, *args):
        self.lines.append((logging.INFO, msg % args if args else msg))

    def warn(self, msg, *args):
        self.lines.append((logging.WARNING, msg % args if args else msg))

    def log(self):
        for level, line in self.lines:
            _log().log(level, line)

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


class FolderLock:
    """A folder's move lock: `.lock` made with O_EXCL, holding the pid, touched after every
    step (so a long move is never mistaken for a dead one). acquire() waits up to LOCK_WAIT_S
    for another holder, then raises MoveStopped. A lock whose process is gone (a start that
    crashed or lost power), or one untouched for LOCK_STALE_S, is taken over."""

    def __init__(self, folder, what):
        self.path = Path(folder) / _paths.LOCK_NAME
        self.what = what
        self.held = False

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
            except PermissionError:
                pass                             # Windows: a holder's lock being deleted
            except OSError as e:
                raise MoveStopped("Moonglade can't write in %s (%s), so it can't start. "
                                  "Check that the folder isn't read-only." % (
                                      self.path.parent, _reason(e)))
            else:
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                self.held = True
                return self
            if time.monotonic() > deadline:
                raise MoveStopped(
                    "Another Moonglade start is still tidying %s. Wait a minute, then start "
                    "Moonglade again." % self.what)
            time.sleep(0.1)

    def _stale(self):
        """True when the holder is gone: its pid is not running, or the lock has not been
        touched for LOCK_STALE_S. Raises OSError when the lock went while we looked."""
        age = time.time() - self.path.stat().st_mtime
        if age > LOCK_STALE_S:
            return True
        try:
            pid = int(self.path.read_text(encoding="ascii").strip() or "0")
        except (ValueError, UnicodeDecodeError):
            return age > 2.0                     # being written: give it a moment
        return not _pid_alive(pid)

    def touch(self):
        if self.held:
            try:
                os.utime(self.path, None)
            except OSError:
                pass

    def release(self):
        if self.held:
            self.held = False
            try:
                os.remove(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


# ---- files ------------------------------------------------------------------------------------
def _reason(e):
    if isinstance(e, PermissionError):
        return "in use or read-only"
    return getattr(e, "strerror", None) or e.__class__.__name__


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
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


def _rmtree_whole(folder):
    """Delete `folder` and everything in it. A file that kept a read-only attribute when it was
    copied in (the outside-references fixer copies a shortcut or a config with shutil.copy2)
    is made writable first: Windows refuses to delete a read-only file, and the folder would
    otherwise outlive every attempt. Raises OSError."""
    for dirpath, _dirs, files in os.walk(folder):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                mode = os.stat(p).st_mode
                if not mode & stat.S_IWRITE:
                    os.chmod(p, mode | stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(folder)


def _remove(p):
    """Delete a file or folder this module has accounted for. Raises _Failed."""
    try:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            os.remove(p)
    except OSError as e:
        raise _Failed("couldn't remove %s (%s)" % (p, _reason(e)))


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
        return "db"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
        fo.flush()
        os.fsync(fo.fileno())
    return "file"


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

    def rel(self, p):
        p = Path(p)
        for prefix, root in self.roots:
            try:
                r = p.relative_to(root).as_posix()
            except ValueError:
                continue
            return prefix + r
        return str(p)

    @property
    def snapshot_dir(self):
        return self.folder / _paths.SNAPSHOT_DIRNAME

    def tick(self):
        if self.lock is not None:
            self.lock.touch()


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
def _park(path, half):
    """Move `path` aside into the half's .snapshot\\parked\\ (copied, verified, then removed:
    the park may be on another volume). Kept until the snapshot goes."""
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
    half.journal.doc["clean_starts"] = 0
    half.report.warn("Two different copies of %s: kept the newer one and set the other aside "
                     "in %s.", half.rel(path), half.rel(target))
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


def _two_copies(src, dest, kind, half, vouched):
    """Both the old place and the new hold the item. Returns what was done."""
    key = half.rel(dest)
    entry = half.journal.items.get(key) or {}
    src_hash = _sha256(src)
    if vouched:
        _remove(src)
        half.report.info("Removed %s: 3.20 had already copied it to %s.",
                         half.rel(src), half.rel(dest))
        return "removed"
    dest_hash = _sha256(dest)
    made = entry.get("state") == "made" or (entry.get("state") == "verified"
                                            and entry.get("sha256") == dest_hash)
    if made and entry.get("src_sha256") == src_hash:
        if entry.get("state") != "made":     # it died between the swap and the journal
            half.journal.items[key]["state"] = "made"
            half.journal.save()
        _remove(src)                         # the move's own source, not yet deleted
        return "removed"
    if src_hash == dest_hash:
        _remove(src)                         # the same bytes: nothing to lose
        return "removed"
    if kind == "cache":
        _remove(src)                         # rebuildable either way
        return "removed"
    if kind == "token":
        # Two Mirror sign-ins: the newer is the live one; a stale token is never parked.
        if src.stat().st_mtime > dest.stat().st_mtime:
            _remove(dest)
            return _bring(src, dest, kind, half)
        _remove(src)
        half.report.info("Removed an older Mirror sign-in at %s.", half.rel(src))
        return "removed"
    if kind == "lines" or kind.startswith("json:"):
        try:
            data = _merged_bytes(src, dest, kind)
        except (OSError, ValueError, UnicodeDecodeError):
            data = None
        if data is not None:
            _replace_with(dest, data, half, key, src_hash)
            _remove(src)
            half.report.info("Merged the copy of %s at %s into %s.", dest.name,
                             half.rel(src), half.rel(dest))
            return "merged"
    # Anything else: keep the newer, park the other.
    if src.stat().st_mtime > dest.stat().st_mtime:
        _park(dest, half)
        return _bring(src, dest, kind, half)
    _park(src, half)
    return "parked"


def _bring(src, dest, kind, half, vouched=False):
    """Bring the file `src` to `dest` by the safe move (see the module's rules). Returns
    "moved", "removed", "merged", "parked", or None when there was nothing at `src`.
    Raises _Failed."""
    src, dest = Path(src), Path(dest)
    tmp = dest.with_name(dest.name + MOVING_SUFFIX)
    _discard(tmp)                            # a crashed run's own temp
    try:
        if not src.is_file() or _same(src, dest):
            return None
        half.report.worked[half.name] = True
        if dest.exists():
            return _two_copies(src, dest, kind, half, vouched)
        key = half.rel(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
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
        return "moved"
    except _Failed:
        raise
    except (OSError, sqlite3.Error) as e:
        _discard(tmp)
        raise _Failed("couldn't move %s (%s)" % (src, _reason(e)))


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
        raise _Failed("couldn't copy %s (%s)" % (src, _reason(e)))
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
    .snapshot\\ once, before its first move. A database goes in through SQLite's backup API."""
    if half.journal.doc.get("snapshot") or (not members and not extra):
        return
    snap = half.snapshot_dir
    snap.mkdir(parents=True, exist_ok=True)
    name = "before-the-move-%s.zip" % time.strftime("%Y%m%d-%H%M%S", time.gmtime())
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
        raise _Failed("couldn't make the safety snapshot in %s (%s)" % (snap, _reason(e)))
    half.journal.doc["snapshot"] = {"made": _now(), "zip": name, "files": count}
    half.journal.doc["clean_starts"] = 0
    half.journal.save()
    half.report.info("Saved a safety copy of %d small file(s) in %s before moving them.",
                     count, half.rel(target))


def count_clean_start(folder, report, half_name):
    """One clean server start for the half whose folder is `folder`: its move has finished
    and this start found nothing to move, merge or park. At CLEAN_STARTS the app deletes the
    half's WHOLE .snapshot\\ -- the zip, anything parked beside it, and the copies the
    outside-references fixer saved in local\\.snapshot\\outside\\ (moonglade.outside). A fix
    made later that makes the folder again is counted again from there, so its copies go too,
    CLEAN_STARTS clean starts on. Never raises."""
    try:
        journal = Journal(folder)
        snap = Path(folder) / _paths.SNAPSHOT_DIRNAME
        if not snap.exists() or not journal.doc.get("finished"):
            return
        if report.worked.get(half_name) or report.parked:
            journal.doc["clean_starts"] = 0
            journal.save()
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


def _merge_settings(half, sources, cfg, report):
    """Fold serve.txt, config.json's app-written keys, branding.json and branding_slots.json
    into settings.json. For the library, host and port the value the old version actually used
    wins: the serve.txt flag (the old launcher passed it, and an explicit flag always won),
    then the config.json key, then what settings.json already held. The losing values go to the
    log only. Returns the merged keys (for the check that follows)."""
    from moonglade import settings as _settings
    serve = _first(sources["serve.txt"])
    flags = parse_serve_txt(serve.read_text(encoding="utf-8", errors="replace")) if serve \
        else parse_serve_txt("")
    current = _settings.read()
    merged = {}

    def pick(key, label, candidates, valid=lambda v: True):
        live = [(where, v) for where, v in candidates if v not in (None, "") and valid(v)]
        if not live:
            return
        where, v = live[0]
        for w2, v2 in live[1:] + [("settings.json", current.get(key))]:
            if v2 not in (None, "") and str(v2) != str(v):
                report.info("The %s from %s (%s) was not used: %s wins (%s).",
                            label, w2, v2, where, v)
        merged[key] = v

    def _port_ok(v):
        try:
            return 1 <= int(v) <= 65535
        except (TypeError, ValueError):
            return False

    pick(_settings.LIBRARY_DIR, "library folder",
         [("serve.txt --out", flags["out"]),
          ("config.json LIBRARY_DIR", str(cfg.get("LIBRARY_DIR") or "").strip() or None)])
    pick(_settings.HOST, "host", [("serve.txt --host", flags["host"]),
                                  ("config.json HOST", cfg.get("HOST"))])
    pick(_settings.PORT, "port", [("serve.txt --port", flags["port"]),
                                  ("config.json PORT", cfg.get("PORT"))], valid=_port_ok)
    if _settings.PORT in merged:
        merged[_settings.PORT] = int(merged[_settings.PORT])
    if serve is not None:
        merged[_settings.LAUNCH_ARGS] = list(flags["launch_args"])
        for d in flags["dropped"]:
            report.info("serve.txt's \"%s\" was dropped: it is not a setting that lasts.", d)
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

    def _apply(doc):
        doc.update(merged)
    _settings.update(_apply)
    check = _settings.read()
    for k, v in merged.items():
        if check.get(k) != v:
            raise _Failed("settings.json did not keep %s" % k)
    if merged:
        report.info("Settings brought into %s: %s.", half.rel(_paths.settings_path()),
                    ", ".join(sorted(merged)))
    return merged


def _drop_config_keys(report):
    """Remove the moved keys from config.json with its own atomic writer, under the lock every
    config.json writer holds. A file that will not parse is left alone."""
    from moonglade import backup as _core
    with _core._accounts_lock:
        doc, state = _read_config_strict()
        if state != "ok":
            return
        gone = [k for k in CONFIG_MOVED_KEYS if k in doc]
        if not gone:
            return
        for k in gone:
            doc.pop(k, None)
        try:
            _core._save_config(doc)
        except OSError as e:
            raise _Failed("couldn't update config.json (%s)" % _reason(e))
    report.info("Removed %s from config.json: they live in settings.json now.", ", ".join(gone))


def _save_quietly(journal):
    try:
        journal.save()
    except OSError:
        pass


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
        raise MoveStopped("Moonglade couldn't finish tidying its folder: %s. Nothing was "
                          "lost; close anything using that file and start Moonglade again."
                          % e)
    return half


def _install_half(half, local, old, copyfirst, report):
    j = half.journal
    if not j.doc.get("started"):
        j.doc["started"] = _now()
    sources = {name: [p for p in (local / name, old / name) if p.is_file()]
               for name in SETTINGS_FILES}
    cfg, cfg_state = _read_config_strict()
    cfg_keys = [k for k in CONFIG_MOVED_KEYS if k in cfg]
    pending_merge = any(sources.values()) or bool(cfg_keys)
    if cfg_state == "corrupt" and not j.doc.get("settings_merged"):
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
    same_folder = _same(old, local)
    stray_marker = old / PACK_MARKER
    has_work = (pending_merge or leftovers or (not same_folder and stray_marker.is_file())
                or any(Path(s).is_file() and not _same(s, d) for s, d, _k in moves))
    if not has_work:
        if not j.doc.get("finished"):
            j.doc["finished"] = _now()
            j.save()
        return
    report.worked["install"] = True

    # The safety snapshot: the small settings files about to go, and the config keys.
    members = []
    for name, paths in sources.items():
        for p in paths:
            members.append((p, half.rel(p)))
    if (local / OLD_RECORD).is_file():
        members.append((local / OLD_RECORD, "local/" + OLD_RECORD))
    extra = {}
    if cfg_keys:
        extra["config.json (the keys moved to settings.json).json"] = json.dumps(
            {k: cfg[k] for k in cfg_keys}, indent=2).encode("utf-8")
    _make_snapshot(half, members, extra)

    # 1. The settings merge.
    if pending_merge:
        _merge_settings(half, sources, cfg if cfg_state == "ok" else {}, report)
        j.doc["settings_merged"] = _now()
        j.save()
        for name, paths in sources.items():
            if not paths:
                continue
            primary = paths[0]
            for p in paths[1:]:
                if copyfirst.unchanged(name, p) or _sha256(p) == _sha256(primary):
                    _remove(p)
                else:
                    _park(p, half)
            _remove(primary)
        _drop_config_keys(report)
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
            _remove(stray_marker)                # a few bytes about a pack that is not there

    # 3. The Mirror's sign-in, the launcher's logs, the shortcut icons.
    for src, dest, kind in moves:
        if kind == "pack":
            continue
        _bring_or_say(src, dest, kind, half)
    for p in leftovers:
        if p.exists():
            _remove(p)
    j.doc["finished"] = _now()
    j.save()
    report.info("The app folder is tidy: settings in local/settings.json, logs in "
                "local/logs/, shortcut icons in local/icons/.")


# ---- the library half -------------------------------------------------------------------------
def migrate_library(out_dir, logins, report, lock=None):
    """The library half for `out_dir`. The caller holds the library's lock. `logins`: the
    login names (logins_from_config()), or None when unknown. Raises MoveStopped."""
    out = Path(out_dir)
    app = _paths.library_app_dir(out)
    half = _Half("library", app, [("", out), ("local/", _paths.local_dir())], report, lock)
    copyfirst = CopyFirst(app / OLD_RECORD)
    try:
        _library_half(half, out, app, copyfirst, logins, report)
    except (_Failed, OSError, sqlite3.Error, RuntimeError) as e:
        if isinstance(e, MoveStopped):
            raise
        _save_quietly(half.journal)
        raise MoveStopped("Moonglade couldn't finish tidying the library folder %s: %s. "
                          "Nothing was lost; close anything using that file and start "
                          "Moonglade again." % (out, e))
    return half


class _Plan:
    def __init__(self):
        self.moves = []          # (src, dest, kind, vouched)
        self.removals = []       # files and (pruned once empty) folders
        self.parks = []          # ambiguous files, set aside beside the snapshot
        self.snap = []           # (path, name in the zip)
        self.orphans = 0         # per-login files of logins no longer in config.json


def _plan_library(out, app, copyfirst, logins, half):
    plan = _Plan()
    reports = app / OLD_REPORTS
    keys = None if not logins else {_paths.account_key(u) for u in logins}

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
    # Per-login stores, keyed by the login hash. A file of a login no longer in AUTH_USERS goes
    # (S10; it is in the safety copy). A name that is not a login key at all is ambiguous, and
    # is parked beside the safety copy.
    for old_name, new_stem in PER_LOGIN.items():
        for base, from_320 in ((app, True), (out, False)):
            folder = base / old_name
            vouched_folder = not from_320 and copyfirst.unchanged(old_name, folder)
            for p in _files_under(folder):
                if _TRANSIENT_RE.search(p.name):
                    plan.removals.append(p)
                    continue
                plan.snap.append((p, half.rel(p)))
                key, _dot, rest = p.name.partition(".")
                if p.parent != folder or not _KEY_RE.match(key) or not rest:
                    plan.parks.append(p)
                    continue
                if keys is not None and key != _paths.LOCAL_ACCOUNT_KEY and key not in keys:
                    plan.removals.append(p)
                    plan.orphans += 1
                    continue
                dest = _paths.accounts_dir(out) / key / (new_stem + "." + rest)
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
    # Dead copies nothing reads: the library's old branding\ and branding.json (in the zip).
    for p in (out / "branding.json",):
        if p.is_file():
            plan.snap.append((p, half.rel(p)))
            plan.removals.append(p)
    for p in _files_under(out / "branding"):
        plan.snap.append((p, half.rel(p)))
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
        for p in paths[1:]:
            if copyfirst.unchanged(name, p) or _sha256(p) == _sha256(primary):
                _remove(p)
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


def _library_half(half, out, app, copyfirst, logins, report):
    j = half.journal
    plan = _plan_library(out, app, copyfirst, logins, half)
    shared = [p for n in SHARED_PRESETS for p in (app / n, out / n) if p.is_file()]
    caches = [out / "gallery" / "cache" / c for c in LIBRARY_CACHES]
    # A folder still holding something the plan does not know is left (and said once, by the
    # start that emptied the rest): it is not work, or every start would count as unclean.
    has_work = (any(Path(s).is_file() for s, _d, _k, _v in plan.moves)
                or any(Path(p).is_file() for p in plan.removals)
                or any(Path(p).is_dir() and not _files_under(p) for p in plan.removals)
                or plan.parks or shared or any(c.exists() for c in caches))
    if not j.doc.get("started"):
        j.doc["started"] = _now()
    if not has_work:
        if not j.doc.get("finished"):
            j.doc["finished"] = _now()
            j.save()
        return
    report.worked["library"] = True
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
    _shared_presets(half, out, app, copyfirst, logins, report)
    _banners(half, out, report)
    # Caches: deleted once the new home exists (they are rebuilt in local\cache\).
    _paths.cache_dir().mkdir(parents=True, exist_ok=True)
    for c in caches:
        if c.exists():
            _remove(c)
    for p in plan.removals:
        if not p.exists():
            continue
        if p.is_dir():
            _prune_empty(p)
            left = [half.rel(x) for x in _files_under(p)]
            if left:
                # Only what the plan accounted for is ever removed: a folder still holding
                # something unexpected is left where it is, and said.
                report.warn("%s still holds %s; left where it is.", half.rel(p),
                            ", ".join(left[:10]))
            continue
        _remove(p)
    if plan.orphans:
        report.info("Removed %d per-login file(s) of logins no longer in config.json (kept in "
                    "the safety copy).", plan.orphans)
    if moved:
        report.info("Moved %d file(s) in the library %s into %s.", moved, out, half.rel(app))
    j.doc["finished"] = _now()
    j.save()

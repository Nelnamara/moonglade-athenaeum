"""moonglade.migrate -- 3.20's move: the machine files into APP_ROOT/local/, and each
library's own records into <library>/_moonglade/ (its reports into _moonglade/reports/).

Where everything goes is moonglade.paths' to say; this module only brings an install's old
layout across, once, when a real start runs it (moonglade.gallery's main(), the launcher for
its own two files, and the command line, `python -m moonglade`, for the library it is pointed
at). The rules:

  * NOTHING OF THE OWNER'S IS EVER DELETED. What is left in an old place is named on the About
    card as safe to delete (leftovers()); the app never removes it.
  * Small files are COPIED (folders included) and the old copy left for one release, so going
    back to 3.19 still works. Two are MOVED instead, because two copies would diverge:
    mirror_session.json (a rotating login token) and train_guard.json (a spend guard: a stale
    copy could let a training spend slip it). A SQLite file is copied with SQLite's own
    backup API, never byte for byte.
  * The library itself is never touched: catalog.db, the pictures, YYYY-MM/, images/,
    videos/, imported/, loom/, gallery/, _deleted/, _duplicates/, and the library-side
    branding.json nothing reads.
  * The art pack is MOVED with os.replace (same volume: no copy of a file of several hundred
    MB), its .version marker with it. A pack still under its pre-v7 name goes through 3.18's
    rename first (moonglade.assets.migrate_legacy_name).
  * The icon cache (_container_cache/) is COPIED to local/cache/ and the old one is kept:
    a Desktop shortcut made before 3.20 takes its icon from _container_cache/marks/, and
    would turn plain if it went. New shortcuts and the code use local/cache/. It is never
    named on About as a leftover, since an old shortcut may still be using it.
  * serve.log is not copied: a fresh one starts in local/ and the old ones stay.
  * config.json stays at the app root and is never touched.
  * EVERY STEP IS SAFE TO RUN AGAIN. A name already recorded is skipped; a name present in
    both places is left alone (the new copy wins, the old one is a leftover).
  * A FAILURE NEVER STOPS THE APP STARTING. It is logged once, on the app's own logger (which
    moonglade.logs lets through to the file at every level), and tried again at the next
    start; meanwhile moonglade.paths keeps reading anything not brought across where it is.
  * What was brought across is written down beside it in MOVED.json (local/MOVED.json,
    <library>/_moonglade/MOVED.json): one entry per name with its source, its destination,
    copied/moved/fresh, the time and the size -- the reversible pattern of
    organize_manifest.csv.
"""
import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from moonglade import paths as _paths

# A child of the app's own logger: moonglade.logs lets it through to the file log at every
# level (a logger outside it stops at WARNING, and the line saying what moved would be lost).
LOGGER_NAME = "moonglade.migrate"

MANIFEST_FORMAT = 1

PACK_NAME = "moonglade.mgpack"
PACK_MARKER_NAME = PACK_NAME + ".version"

# The machine files, in the order a start brings them across, and how. The pack goes first
# so its marker can follow it.
LOCAL_PLAN = (
    (PACK_NAME, "moved"),
    (PACK_MARKER_NAME, "moved"),
    (_paths.MIRROR_SESSION_NAME, "moved"),
    ("branding.json", "copied"),
    ("branding_slots.json", "copied"),
    ("serve.txt", "copied"),
    ("serve.log", "fresh"),
    (_paths.ICON_CACHE_NAME, "copied"),       # kept: old Desktop shortcuts use it
)
# The launcher's own two files: it brings these across itself, before it reads serve.txt.
LAUNCHER_NAMES = ("serve.txt", "serve.log")


class Outcome:
    """What one run did: the manifest entries it wrote, what it could not bring across (name,
    plain reason), and any plain sentence worth saying on the console."""

    def __init__(self, where):
        self.where = where
        self.done = []
        self.failed = []
        self.notes = []

    def summary(self):
        """One plain line, or "" when there is nothing to say."""
        parts = []
        for action, verb in (("moved", "moved"), ("copied", "copied"),
                             ("fresh", "started fresh")):
            names = [e["name"] for e in self.done if e["action"] == action]
            if names:
                parts.append("%s %s" % (verb, ", ".join(names)))
        line = ""
        if parts:
            line = "Tidied %s: %s." % (self.where, "; ".join(parts))
        if self.failed:
            line += (" " if line else "") + (
                "Could not bring across %s: left where %s, still used there, and tried again "
                "at the next start." % (
                    ", ".join("%s (%s)" % f for f in self.failed),
                    "it is" if len(self.failed) == 1 else "they are"))
        return line

    def log(self):
        """Write the summary to the log, once: a warning when something failed."""
        line = self.summary()
        if line:
            logging.getLogger(LOGGER_NAME).log(
                logging.WARNING if self.failed else logging.INFO, line)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _reason(e):
    if isinstance(e, PermissionError):
        return "in use or read-only"
    return getattr(e, "strerror", None) or e.__class__.__name__


def _rel(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _transient(name):
    """A file never worth bringing across: a lock, or a half-written temp."""
    return name.endswith((".lock", ".part")) or ".tmp" in name or ".copying-" in name


def _temp_beside(dest):
    return dest.with_name("%s.copying-%d-%s" % (dest.name, os.getpid(), uuid.uuid4().hex[:8]))


def _copy_file(src, dest):
    """Copy through a temp of this run's own, then rename it into place: a copy is whole or
    not there at all."""
    tmp = _temp_beside(dest)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _copy_sqlite(src, dest):
    """A SQLite file is copied with SQLite's own backup API, never byte for byte: that is
    right even while another process has it open."""
    tmp = _temp_beside(dest)
    try:
        s = sqlite3.connect(str(src))
        try:
            d = sqlite3.connect(str(tmp))
            try:
                s.backup(d)
            finally:
                d.close()
        finally:
            s.close()
        os.replace(tmp, dest)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _merge_tree(src, dest):
    """Copy every file of the folder `src` that `dest` does not have yet (the new one wins
    per file), keeping its shape; locks and temps are left behind. Returns the bytes copied
    or already there."""
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for dirpath, dirnames, filenames in os.walk(src):
        here = Path(dirpath)
        rel = here.relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for fn in filenames:
            if _transient(fn):
                continue
            target = dest / rel / fn
            if not target.exists():
                if fn.endswith(".db"):
                    _copy_sqlite(here / fn, target)
                else:
                    _copy_file(here / fn, target)
            total += (here / fn).stat().st_size
    return total


def _size(p):
    p = Path(p)
    if p.is_dir():
        return sum((Path(d) / f).stat().st_size
                   for d, _, fs in os.walk(p) for f in fs)
    return p.stat().st_size


def _bring(name, src, dest, how, root, outcome, recorded):
    """Bring one name across `how` ("moved", "copied" or "fresh"). Returns the manifest entry
    it wrote down, or None when there was nothing to do (already recorded, nothing in the old
    place, or both places already hold it) or it failed (noted in `outcome`)."""
    if name in recorded:
        return None
    try:
        if not src.exists():
            return None
        if how == "fresh":
            size = _size(src)                       # left where it is; a new one starts
        elif src.is_dir() and how == "copied":
            size = _merge_tree(src, dest)            # a partial earlier try is finished
        elif dest.exists():
            return None                              # both: the new one wins
        elif how == "moved":
            os.replace(src, dest)
            size = _size(dest)
        elif src.suffix == ".db":
            _copy_sqlite(src, dest)
            size = _size(dest)
        else:
            _copy_file(src, dest)
            size = _size(dest)
    except (OSError, sqlite3.Error) as e:
        outcome.failed.append((name, _reason(e)))
        return None
    entry = {"name": name, "source": _rel(src, root), "dest": _rel(dest, root),
             "action": how, "time": _now(), "size": size}
    outcome.done.append(entry)
    return entry


def _write_manifest(manifest, outcome):
    """Add this run's entries to the manifest (created on a first run even when there was
    nothing to bring, so the folder says when it was set up). Written whole, through a temp."""
    if not outcome.done and manifest.exists():
        return
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
            raise ValueError
    except (OSError, ValueError):
        doc = {"format": MANIFEST_FORMAT, "created": _now(), "entries": []}
    doc["entries"].extend(outcome.done)
    tmp = _temp_beside(manifest)
    try:
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, manifest)
    except OSError as e:
        outcome.failed.append((_paths.MOVED_NAME, _reason(e)))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _legacy_pack_rename(old_pack, new_pack, recorded, outcome):
    """3.18's one-time rename, at the OLD place, for an install whose pack still has its
    pre-v7 name: then the move below carries the renamed pack across like any other."""
    if PACK_NAME in recorded or new_pack.exists():
        return
    from moonglade import assets as _assets
    if _assets.migrate_legacy_name(old_pack) == "both":
        outcome.notes.append("An old %s is still in the app folder. It's safe to delete."
                             % _assets.LEGACY_NAME)


def migrate_local(only=None):
    """Bring the machine files across into local_dir(). `only`: a subset of names (the
    launcher's own). Returns an Outcome; never raises for a file it could not bring."""
    outcome = Outcome("the app folder")
    local = _paths.local_dir()
    try:
        local.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        outcome.failed.append((_paths.LOCAL_DIRNAME, _reason(e)))
        return outcome
    manifest = local / _paths.MOVED_NAME
    recorded = _paths.moved_names(manifest)
    root = _paths.APP_ROOT
    for name, how in LOCAL_PLAN:
        if only is not None and name not in only:
            continue
        src, dest = _paths.old_local_path(name), local / name
        if name == PACK_NAME:
            _legacy_pack_rename(src, dest, recorded, outcome)
        if name == PACK_MARKER_NAME and not (local / PACK_NAME).exists():
            continue                                 # the marker stays with its pack
        _bring(name, src, dest, how, root, outcome, recorded)
    _write_manifest(manifest, outcome)
    return outcome


# The library's records that are MOVED rather than copied (see the module's rules).
MOVED_RECORDS = ("train_guard.json",)
# A report never worth bringing across: the integrity writers' lock, held for seconds.
TRANSIENT_REPORTS = ("integrity_report.lock",)


def _library_plan(out):
    """(name, source, destination, how) for every record and report the library holds,
    state first, then reports, then the curation import's undo files."""
    records = out / _paths.RECORDS_DIRNAME
    reports = records / _paths.REPORTS_DIRNAME
    for name in _paths.STATE_NAMES:
        how = "moved" if name in MOVED_RECORDS else "copied"
        yield name, _paths.old_state_path(out, name), records / name, how
    for name in _paths.REPORT_NAMES:
        if name not in TRANSIENT_REPORTS:
            yield name, _paths.old_state_path(out, name), reports / name, "copied"
    try:
        snapshots = sorted(p.name for p in out.glob(_paths.CURATION_SNAPSHOT_PREFIX + "*.json"))
    except OSError:
        snapshots = []
    for name in snapshots:
        yield name, _paths.old_state_path(out, name), reports / name, "copied"


def migrate_library(out_dir):
    """Bring the library `out_dir`'s records across into its _moonglade/ folder. A folder
    that is not there yet (a first run's library) is left alone. Returns an Outcome; never
    raises for a record it could not bring."""
    out = Path(out_dir)
    outcome = Outcome("the library " + str(out))
    if not out.is_dir():
        return outcome
    reports = out / _paths.RECORDS_DIRNAME / _paths.REPORTS_DIRNAME
    try:
        reports.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        outcome.failed.append((_paths.RECORDS_DIRNAME, _reason(e)))
        return outcome
    manifest = _paths.records_manifest(out)
    recorded = _paths.moved_names(manifest)
    for name, src, dest, how in _library_plan(out):
        _bring(name, src, dest, how, out, outcome, recorded)
    _write_manifest(manifest, outcome)
    return outcome


def open_library(out_dir):
    """Every entry point's one call for its library, once logging is set up and before
    anything reads a record: bring the records across, re-point the file log at the new
    logs/ (moonglade.logs.reopen), then log what happened, once -- in the new log. Never
    raises."""
    try:
        outcome = migrate_library(out_dir)
    except Exception as e:                       # noqa: BLE001 -- a start must go on
        outcome = Outcome("the library " + str(out_dir))
        outcome.failed.append(("the library's records", _reason(e)))
    try:
        from moonglade import logs as moonglade_logging
        moonglade_logging.reopen(out_dir)
    except Exception:                            # noqa: BLE001 -- the old log still works
        pass
    outcome.log()
    return outcome


# ---- what is left in the old places: About's list ----------------------------------------

# How many rotated serve logs the launcher keeps (moonglade_logging.SERVE_LOG_KEEP).
_OLD_SERVE_LOGS = ("serve.log.1", "serve.log.2", "serve.log.3")
# The library-side branding.json: the old home of the branding choice, read by nothing since
# branding moved to the app folder (2026-07). Named on About, never brought across.
_UNUSED_LIBRARY_FILES = ("branding.json",)


def _shown(p):
    """A leftover by the name it has on disk; a folder's ends in a separator."""
    return p.name + os.sep if p.is_dir() else p.name


def leftovers(out_dir=None):
    """Every old copy the app no longer reads, as (where, name) -- where is "app" (the app
    folder) or "library" (the top of `out_dir`); a folder's name ends in a separator. Read
    from the disk on each ask, so a name leaves the moment its file is deleted.

    A copy is left over when it is still in its old place but the resolver now answers
    somewhere else: an install not yet brought across has nothing left over (everything is
    still read where it is). Never raises."""
    found = []
    try:
        from moonglade import assets as _assets
        pack_in_use = _paths.local_path(PACK_NAME)
        app_names = [_assets.LEGACY_NAME, _assets.LEGACY_NAME + ".version"]
        app_names += [n for n, _ in LOCAL_PLAN] + list(_OLD_SERVE_LOGS)
        for name in app_names:
            if name == _paths.ICON_CACHE_NAME:
                continue        # still in use: an old Desktop shortcut takes its icon from it
            old = _paths.old_local_path(name)
            if not old.exists():
                continue
            if name.startswith(_assets.LEGACY_NAME):
                gone = pack_in_use.exists()          # the pack in use has the new name
            elif name in _OLD_SERVE_LOGS:
                gone = _paths.local_path("serve.log") != _paths.old_local_path("serve.log")
            else:
                gone = _paths.local_path(name) != old
            if gone:
                found.append(("app", _shown(old)))
    except OSError:
        pass
    if out_dir is None:
        return found
    out = Path(out_dir)
    try:
        for name, src, _dest, _how in _library_plan(out):
            if not src.exists():
                continue
            ask = _paths.state_path if name in _paths.STATE_NAMES else _paths.reports_path
            if ask(out, name) != src:
                found.append(("library", _shown(src)))
        for name in _UNUSED_LIBRARY_FILES:
            p = _paths.old_state_path(out, name)
            if p.is_file() and p != _paths.local_path(name):     # never the one in use
                found.append(("library", name + " (unused)"))
    except OSError:
        pass
    return found


def _and(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


_WHERE = (("app", "in the app folder"), ("library", "in the library folder"),
          ("pack", "beside the pack"))


def leftovers_note(items):
    """About's one line for `items` ((where, name) pairs, leftovers()'s shape), or "" when
    there are none: what is safe to delete, and where."""
    parts = []
    for where, label in _WHERE:
        names = [n for w, n in items if w == where]
        if names:
            parts.append("%s %s" % (_and(names), label))
    if not parts:
        return ""
    return "Safe to delete once you've checked this version works: %s." % "; ".join(parts)


def tidy_app_folder():
    """main()'s one call, once logging is set up and the port is known to be free: bring the
    machine files across, say anything worth saying on the console, and log what happened,
    once. Never raises."""
    try:
        outcome = migrate_local()
    except Exception as e:                       # noqa: BLE001 -- a start must go on
        outcome = Outcome("the app folder")
        outcome.failed.append(("the machine files", _reason(e)))
    for note in outcome.notes:
        print(note)
    outcome.log()
    return outcome


def tidy_launcher_files():
    """The launcher's call, before it reads serve.txt: bring serve.txt across and start
    serve.log fresh in local/. It has no log of its own yet, so it writes the outcome's
    summary into the serve.log it opens. Never raises."""
    try:
        return migrate_local(only=LAUNCHER_NAMES)
    except Exception as e:                       # noqa: BLE001 -- the launcher must go on
        outcome = Outcome("the app folder")
        outcome.failed.append(("serve.txt", _reason(e)))
        return outcome

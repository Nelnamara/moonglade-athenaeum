"""moonglade_paths.py -- where Moonglade Athenaeum's own files are. The ONE place an app-root
path is derived.

Every module used to find "the app's folder" from its own `__file__`, in more than a dozen
places, and none of them shared a helper (moonglade-internal/scopes/wave4/COUPLING.md section
2). That only works while every module sits flat beside the launcher. Each location now has a
named helper here, so moving a group of files is a change to one line in this module:

  APP_ROOT          the folder holding the launcher and config.json.
  config_path()     config.json: beside the app first, then the working directory.
  local_path(name)  the machine files, in APP_ROOT/local/ since 3.20: the art pack and its
                    .version marker, branding.json, branding_slots.json, mirror_session.json,
                    serve.txt, serve.log and the icon cache (local/cache/). They belong to
                    this machine, not to the code, the art tree or the library. Until an
                    install's own files have been brought across (moonglade.migrate), a file
                    found only in its old place (old_local_path()) is read there.
  art_root()        the coded art tree branding_root() returns. Deliberately NOT derived
                    from local_path(): the art tree and the machine files move separately.
  state_path(out_dir, name)    one of the app's own records inside a library: its state
  reports_path(out_dir, name)  files, jobs, logs and per-account folders, and its reports.
                    catalog.db, the pictures, loom/, gallery/, _deleted/ and _duplicates/
                    are the library itself, not records, and never go through these.
  the rest          the shipped files the app reads: the pack manifest, wiki/, the
                    CHANGELOG, gallery/dist, loom/, static/, requirements.txt, the launcher
                    and the two entry scripts.

Nothing here imports another app module, so every module (and the launcher, before it has
anything else) can import it first.

The test suite pins `config_path`, `local_path`, `local_dir` and `old_local_path` to each
test's own folder (tests/conftest.py), and tests/test_app_paths.py holds every helper against
the exact path it resolves to.
"""
import json
from pathlib import Path

# The folder holding the launcher (Serve Gallery.pyw) and config.json: the parent of the
# moonglade/ code folder this module sits in. The code moved down a folder in 3.20, and every
# app-root path still follows from this one line.
APP_ROOT = Path(__file__).resolve().parent.parent

# The coded art tree's folder name ("goods" in hex). The tree sits beside the launcher, not
# in the library or the code (DECISIONS 2026-07-26).
GOODS_ROOT_NAME = "0x676F6F6473"

# The library used when neither --out nor config.json's LIBRARY_DIR names one. RELATIVE on
# purpose: it resolves against run_dir(), and it is shown, stored and logged as typed.
DEFAULT_LIBRARY_DIR = "pixai_backup"


def config_path():
    """config.json: the copy beside the app first, then one in the working directory. If
    neither exists yet (a first run, a fresh write) it is the one beside the app."""
    for candidate in (APP_ROOT / "config.json", Path("config.json")):
        if candidate.exists():
            return candidate
    return APP_ROOT / "config.json"


def token_paths():
    """Where the legacy token.txt credential is looked for, in order: beside the app, then
    the working directory (the same rule config.json keeps)."""
    return (APP_ROOT / "token.txt", Path("token.txt"))


# ---- 3.20: the machine files' folder, and the library's records folder -------------------
# The machine files' folder under APP_ROOT.
LOCAL_DIRNAME = "local"
# The app's own records inside a library, and its reports inside that.
RECORDS_DIRNAME = "_moonglade"
REPORTS_DIRNAME = "reports"
# What a migration brought across, written beside what it brought (moonglade.migrate): one
# entry per name, with where it came from, where it went, copied or moved, when and how big.
# A name it records is never looked for in its old place again.
MOVED_NAME = "MOVED.json"
# The icon cache: local/cache/ now, the app root's _container_cache/ before 3.20.
ICON_CACHE_NAME = "cache"
OLD_ICON_CACHE_NAME = "_container_cache"
# The file the mirror's login lives in (a rotating token): beside config.json before 3.20.
MIRROR_SESSION_NAME = "mirror_session.json"


def local_dir():
    """The machine files' folder: APP_ROOT/local."""
    return APP_ROOT / LOCAL_DIRNAME


def old_local_path(name):
    """Where 3.19 kept the machine file `name`: the app folder itself, except the icon cache
    (`_container_cache/`) and mirror_session.json (beside wherever config.json was found).
    The migration's source, and a reader's fallback until the file has been brought across."""
    if name == ICON_CACHE_NAME:
        return APP_ROOT / OLD_ICON_CACHE_NAME
    if name == MIRROR_SESSION_NAME:
        return config_path().parent / name
    return APP_ROOT / name


def local_path(name):
    """A machine file by name: `moonglade.mgpack` (+ `.version`), `branding.json`,
    `branding_slots.json`, `mirror_session.json`, `serve.txt`, `serve.log`, the icon cache
    (`cache`). It is local_dir() / name, except while the file is still only in its old
    place and the migration has not recorded it (an install not yet started on 3.20, or a
    move that was refused): then it is read, and written, where it is."""
    return _settled(local_dir(), name, old_local_path(name), local_dir() / MOVED_NAME)


def icon_cache_dir():
    """The regenerable cache of pack-shipped .ico files that Windows must read off disk (the
    Desktop shortcut's icon). A machine file, so it goes through local_path()."""
    return local_path(ICON_CACHE_NAME) / "marks"


# The manifest's recorded names, read once per change of the file (path -> (stamp, names)).
_moved_names_cache = {}


def moved_names(manifest):
    """The names a migration manifest records as brought across (copied, moved or started
    fresh). An absent or unreadable manifest records nothing."""
    manifest = Path(manifest)
    try:
        st = manifest.stat()
    except OSError:
        return frozenset()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _moved_names_cache.get(str(manifest))
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        names = frozenset(e["name"] for e in doc.get("entries", [])
                          if isinstance(e, dict) and isinstance(e.get("name"), str))
    except (OSError, ValueError, AttributeError, TypeError):
        names = frozenset()
    _moved_names_cache[str(manifest)] = (stamp, names)
    return names


def _settled(new_dir, name, old, manifest):
    """The new place for `name`, unless it is missing there, present in its old place `old`,
    and not recorded in `manifest`: then the old place. A recorded name is never looked for
    in its old place again, so deleting the new copy can never bring back a stale old one."""
    new = Path(new_dir) / name
    try:
        if new.exists() or not old.exists():
            return new
        if name in moved_names(manifest):
            return new
    except OSError:
        return new
    return old


def art_root():
    """The coded art tree, beside the launcher. branding_root() returns this."""
    return APP_ROOT / GOODS_ROOT_NAME


def manifest_path():
    """The pack manifest, committed with the code: which pack this build wants and where to
    fetch it."""
    return APP_ROOT / "moonglade" / "manifest.json"


def wiki_dir():
    """The wiki/ folder shipped with this install: the in-app Help guide."""
    return APP_ROOT / "wiki"


def changelog_path():
    """This install's own CHANGELOG.md: About's what's new."""
    return APP_ROOT / "CHANGELOG.md"


def gallery_dist():
    """The built React front end, served at /."""
    return APP_ROOT / "gallery" / "dist"


def loom_dir():
    """The Loom's folder."""
    return APP_ROOT / "loom"


def loom_dist():
    """The Loom's built bundle, served at /loom/dist/."""
    return loom_dir() / "dist"


def loom_vendor():
    """The Loom's vendored libraries, served at /loom/vendor/."""
    return loom_dir() / "vendor"


def static_dir():
    """Flask's /static/ folder (the design-kit files)."""
    return APP_ROOT / "static"


def requirements_path():
    """requirements.txt, which the one-click update installs when it changed."""
    return APP_ROOT / "requirements.txt"


def launcher_path():
    """Serve Gallery.pyw, the launcher the Desktop shortcut points at."""
    return APP_ROOT / "Serve Gallery.pyw"


# The web server's entry script, by its path under APP_ROOT. The launcher joins it onto its
# own os.path.abspath folder, so the path it runs is byte-for-byte what 3.18 ran.
GALLERY_SCRIPT = "moonglade_gallery.py"


def gallery_script_path():
    """The web server's entry script, which the launcher runs."""
    return APP_ROOT / GALLERY_SCRIPT


def backup_script_path():
    """The command-line tool's entry script, which the Control Panel runs for its jobs."""
    return APP_ROOT / "moonglade_backup.py"


def default_library_path():
    """The default library as an absolute path, for a process whose working directory is not
    the app's (the MCP server, started by an MCP client from anywhere)."""
    return APP_ROOT / DEFAULT_LIBRARY_DIR


def state_path(out_dir, name):
    """One of the app's own records inside the library `out_dir`, by name:
    `achievements.json`, `telemetry.json`, `schedule.json`, `train_guard.json`,
    `reconcile_stamp.json`, `jobs.jsonl`, `raw_tasks.jsonl`, `runs.db`, the per-account
    folders (`account_prefs/`, `account_state/`, `prompt_snippets/`, `toolbox_presets/`,
    `view_presets/`), the install-wide files they replaced and still fall back to
    (`prompt_snippets.json`, `toolbox_presets.json`, `view_presets.json`) and `logs/`.
    Today it is out_dir / name."""
    return Path(out_dir) / name


def reports_path(out_dir, name):
    """One of the app's reports inside the library `out_dir`, by name:
    `integrity_report.csv`/`.json`/`.lock`, `integrity_marks.json`, `audit_report.csv`,
    `verify_report.csv`, `organize_manifest.csv` and the curation import's undo files
    (`curation_pre_import_<time>.json`). Today it is out_dir / name."""
    return Path(out_dir) / name


def run_dir():
    """The working directory, which relative paths (the default library, a relative folder
    typed into the Control Panel) resolve against. Every entry point makes it APP_ROOT: the
    launcher changes into it, the Control Panel starts its jobs in it, and the documented
    command lines run from it. Named so that code which depends on it says so."""
    return Path.cwd()

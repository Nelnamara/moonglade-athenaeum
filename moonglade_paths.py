"""moonglade_paths.py -- where Moonglade Athenaeum's own files are. The ONE place an app-root
path is derived.

Every module used to find "the app's folder" from its own `__file__`, in more than a dozen
places, and none of them shared a helper (moonglade-internal/scopes/wave4/COUPLING.md section
2). That only works while every module sits flat beside the launcher. Each location now has a
named helper here, so moving a group of files is a change to one line in this module:

  APP_ROOT          the folder holding the launcher and config.json.
  config_path()     config.json: beside the app first, then the working directory.
  local_path(name)  the machine files: the art pack and its .version marker, branding.json,
                    branding_slots.json, mirror_session.json, serve.txt, serve.log and the
                    icon cache. They belong to this machine, not to the code, the art tree
                    or the library.
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

The test suite pins `config_path` and `local_path` to each test's own folder
(tests/conftest.py), and tests/test_app_paths.py holds every helper against the exact path
it resolved to before this module existed.
"""
from pathlib import Path

# The folder holding the launcher (Serve Gallery.pyw) and config.json. Today that is this
# module's own folder. When the code moves into a package folder this becomes that
# folder's parent -- the only line that changes.
APP_ROOT = Path(__file__).resolve().parent

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


def local_path(name):
    """A machine file by name: `moonglade.mgpack` (+ `.version`), `branding.json`,
    `branding_slots.json`, `mirror_session.json`, `serve.txt`, `serve.log`, the icon cache.
    Today it is APP_ROOT / name."""
    return APP_ROOT / name


def icon_cache_dir():
    """The regenerable cache of pack-shipped .ico files that Windows must read off disk (the
    Desktop shortcut's icon). A machine file, so it goes through local_path()."""
    return local_path("_container_cache") / "marks"


def art_root():
    """The coded art tree, beside the launcher. branding_root() returns this."""
    return APP_ROOT / GOODS_ROOT_NAME


def manifest_path():
    """The pack manifest, committed with the code: which pack this build wants and where to
    fetch it."""
    return APP_ROOT / "moonglade_manifest.json"


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


def gallery_script_path():
    """The web server's entry script, which the launcher runs."""
    return APP_ROOT / "moonglade_gallery.py"


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

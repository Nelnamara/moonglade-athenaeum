"""moonglade.paths -- where Moonglade Athenaeum's own files are. The ONE place an app-root or
library-records path is derived.

Every module used to find "the app's folder" from its own `__file__`, in more than a dozen
places, and none of them shared a helper (moonglade-internal/scopes/wave4/COUPLING.md section
2). Each location now has a named helper here, so moving a group of files is a change to one
line in this module.

The layout (moonglade-internal/scopes/wave4-rescope/SPEC_3.20_REBUILD.md; DECISIONS 2026-10-07,
"The full reorganize: the owner's picks"). There is ONE home for each item, and nothing here
ever answers an old place: only the move itself (moonglade.migrate) knows where an older
version kept things.

  <install>\\                 APP_ROOT: the launcher, config.json (hand-edited values only),
                             the code (moonglade\\), the art tree and the shipped folders.
    local\\                   local_dir(): this PC's machinery.
      settings.json          settings_path(): everything the app writes (moonglade.settings).
      mirror_session.json    local_path(MIRROR_SESSION_NAME): the Mirror's rotating sign-in.
      moonglade.mgpack       local_path(PACK_NAME), and its .version marker.
      icons\\                 icons_dir(): the shortcut .ico files. NOT a cache: a shortcut
                             points here, so clearing a cache never blanks its icon.
      banners\\               banners_dir(): banner renders that are the only copy.
      cache\\                 cache_dir(): rebuildable things (badges, masks, banner renders).
      logs\\                  logs_dir(): serve.log* (the launcher's) and moonglade.log*.
      .journal.json, .lock   the install half of the move.
  <library>\\
    _moonglade\\              library_app_dir(out): everything of the app's in a library.
      accounts\\<key>\\        account_dir(out, login): every per-login store.
      loom\\                  loom_root(out): the Loom's whole folder.
      records\\               records_path(out, name): achievements, runs, jobs, the schedule,
                             the spend guard, telemetry, the integrity reports...
      decisions\\             decisions_path(out, name): what the owner decided and must never
                             lose (Mark-lost choices, the --organize undo list, curation undo).
      .journal.json, .lock   the library half of the move.

Nothing here imports another app module, so every module (and the launcher, before it has
anything else) can import it first.

The test suite pins `config_path`, `local_dir`, `local_path` and `library_anchor` to each
test's own folder (tests/conftest.py), and tests/test_app_paths.py holds every helper against
the exact path it resolves to.
"""
import hashlib
from pathlib import Path

# The folder holding the launcher and config.json: the parent of the moonglade/ code folder
# this module sits in. Every app-root path follows from this one line.
APP_ROOT = Path(__file__).resolve().parent.parent

# The coded art tree's folder name ("goods" in hex). The tree sits beside the launcher, not
# in the library or the code (DECISIONS 2026-07-26).
GOODS_ROOT_NAME = "0x676F6F6473"

# The library used when neither an explicit --out nor settings.json names one. RELATIVE on
# purpose: it is anchored to APP_ROOT (moonglade.settings.library_path), and it is shown and
# logged as typed.
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


# ---- the install: local\ ------------------------------------------------------------------
LOCAL_DIRNAME = "local"
SETTINGS_NAME = "settings.json"
MIRROR_SESSION_NAME = "mirror_session.json"
PACK_NAME = "moonglade.mgpack"
ICONS_DIRNAME = "icons"
BANNERS_DIRNAME = "banners"
CACHE_DIRNAME = "cache"
LOGS_DIRNAME = "logs"
# The move's bookkeeping, one of each in local\ and in a library's _moonglade\.
JOURNAL_NAME = ".journal.json"
LOCK_NAME = ".lock"
# The safety snapshot (the owner's pick 4), beside each journal; parked copies go in it.
SNAPSHOT_DIRNAME = ".snapshot"


def local_dir():
    """This PC's machinery: APP_ROOT/local."""
    return APP_ROOT / LOCAL_DIRNAME


def local_path(name):
    """A flat file in local\\ by name: the pack (`moonglade.mgpack`) and its `.version`
    marker, `mirror_session.json`. Always local_dir() / name."""
    return local_dir() / name


def settings_path():
    """settings.json: everything the app writes for this install (moonglade.settings)."""
    return local_dir() / SETTINGS_NAME


def icons_dir():
    """The shortcut .ico files Windows reads off disk (the Desktop/Start-menu shortcuts and
    the pack's Explorer type). Not a cache: a shortcut points at a file here."""
    return local_dir() / ICONS_DIRNAME


def banners_dir():
    """Banner renders that are the only copy of what this install wears (moved in from an
    early version's art-tree root, or a render with no record): never regenerated, never in
    a cache."""
    return local_dir() / BANNERS_DIRNAME


def cache_dir():
    """Rebuildable things: badge thumbnails, feat masks, slot and earned banner renders.
    Anything here may be deleted; it is made again when it is next needed."""
    return local_dir() / CACHE_DIRNAME


def logs_dir():
    """Both logs: the launcher's serve.log* and the app's moonglade.log*."""
    return local_dir() / LOGS_DIRNAME


# ---- the library: <library>\_moonglade\ ----------------------------------------------------
# The app's own folder inside a library. Every library walker prunes it (moonglade.gallery's
# QUARANTINE_EXCLUDE), so nothing in it is ever catalogued, counted, organized or quarantined
# -- the Loom's frames and cuts included, which is why the Loom lives in it.
LIBRARY_APP_DIRNAME = "_moonglade"
ACCOUNTS_DIRNAME = "accounts"
LOOM_DIRNAME = "loom"
RECORDS_DIRNAME = "records"
DECISIONS_DIRNAME = "decisions"
# The per-login account folder of a caller with no web session (the CLI, the MCP server):
# moonglade.gallery's ACCOUNT_LOCAL. A login's key is 16 hex characters, so it never collides.
LOCAL_ACCOUNT_KEY = "_local"


def library_app_dir(out_dir):
    """The app's folder inside the library `out_dir`: out_dir/_moonglade."""
    return Path(out_dir) / LIBRARY_APP_DIRNAME


def account_key(login):
    """Filesystem-safe, case-COLLISION-safe key for the login name `login`: the first 16 hex
    digits of sha256 of the exact (case-sensitive) name. "Nel" and "nel" are two logins, and
    on NTFS two plain-name folders would be one; two digests never are. Not reversible on
    purpose: the login owns its display name in config.json's AUTH_USERS."""
    return hashlib.sha256(str(login).encode("utf-8")).hexdigest()[:16]


def accounts_dir(out_dir):
    """Where every per-login folder of the library `out_dir` lives."""
    return library_app_dir(out_dir) / ACCOUNTS_DIRNAME


def account_dir(out_dir, login):
    """The one folder holding every per-login store of `login` (prefs, state, snippets,
    toolbox presets, saved views) in the library `out_dir`: accounts/<account_key(login)>."""
    return accounts_dir(out_dir) / account_key(login)


def local_account_dir(out_dir):
    """The per-login folder of a caller with no web session (LOCAL_ACCOUNT_KEY)."""
    return accounts_dir(out_dir) / LOCAL_ACCOUNT_KEY


def loom_root(out_dir):
    """The Loom's whole folder in the library `out_dir`: boards (kv/), music beds (_beds/),
    the render journal (_submits/), frames and exports."""
    return library_app_dir(out_dir) / LOOM_DIRNAME


def _in_library(folder, out_dir, make):
    """`folder`, made first when `make` and the library itself exists -- so a first write can
    land, and asking about a folder that is not a library never creates one."""
    if make:
        try:
            if not folder.is_dir() and Path(out_dir).is_dir():
                folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return folder


def records_path(out_dir, name, make=True):
    """One of the app's records in the library `out_dir`, by name: achievements.json (with
    the skin), telemetry.json, schedule.json, train_guard.json, reconcile_stamp.json,
    jobs.jsonl, raw_tasks.jsonl, runs.db, the integrity reports and their lock,
    audit_report.csv, verify_report.csv. out_dir/_moonglade/records/name. `make=False` only
    looks: it never makes the folder."""
    return _in_library(library_app_dir(out_dir) / RECORDS_DIRNAME, out_dir, make) / name


def decisions_path(out_dir, name, make=True):
    """One of the owner's decisions in the library `out_dir`, by name: integrity_marks.json
    (Mark lost / Keep as is), organize_manifest.csv (the --organize undo list), the curation
    import's undo snapshots (curation_pre_import_<time>.json). Kept apart from the records
    because none of it can be made again. out_dir/_moonglade/decisions/name."""
    return _in_library(library_app_dir(out_dir) / DECISIONS_DIRNAME, out_dir, make) / name


# ---- shipped files ----------------------------------------------------------------------
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
    """The Loom's code folder (the front end), not its library data (loom_root)."""
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


# The web server's OLD entry script, by its path under APP_ROOT: since 3.20 the root stand-in
# a launcher from before the move still runs (moonglade_gallery.py; it stays for good). No app
# code runs it any more -- the launcher runs `-m moonglade.gallery` -- and only the tests that
# hold every path where it was (tests/test_app_paths.py) ask for it.
GALLERY_SCRIPT = "moonglade_gallery.py"


def gallery_script_path():
    """The root moonglade_gallery.py stand-in an old launcher runs. Test-only: the app itself
    starts the server as `python -m moonglade.gallery`."""
    return APP_ROOT / GALLERY_SCRIPT


def backup_script_path():
    """The root moonglade_backup.py stand-in for old command lines (goes in 3.21). Test-only:
    the Control Panel runs its jobs as `python -m moonglade`."""
    return APP_ROOT / "moonglade_backup.py"


def library_anchor():
    """The folder a relative library path (the default, or a relative one stored in
    settings.json) is anchored to: the app folder, whatever the working directory of the
    entry point. The test suite pins it to each test's own folder."""
    return APP_ROOT


def default_library_path():
    """The default library as an absolute path: DEFAULT_LIBRARY_DIR anchored to the app
    folder (library_anchor())."""
    return library_anchor() / DEFAULT_LIBRARY_DIR


def run_dir():
    """The working directory, which a relative path typed into the Control Panel resolves
    against. Every entry point makes it APP_ROOT: the launcher changes into it, the Control
    Panel starts its jobs in it, and the documented command lines run from it. Named so that
    code which depends on it says so."""
    return Path.cwd()

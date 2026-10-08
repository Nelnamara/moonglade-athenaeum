"""moonglade.setup -- prepare(kind): the first thing every entry point runs (B2).

Before anything reads a setting, every way Moonglade starts -- the launcher, the web server,
the command line, the MCP server -- calls prepare(kind) once:

  1. Under the install lock (local\\.lock): merge the settings into local\\settings.json and run
     the install half of the move (moonglade.migrate.migrate_install).
  2. Resolve the library from settings.json (moonglade.settings.library_path), unless this run
     names one itself (--out, MOONGLADE_OUT).
  3. Under the library lock (<library>\\_moonglade\\.lock): run the library half
     (moonglade.migrate.migrate_library). A library folder that is not there yet is left
     alone: the server makes it, and the next start finds nothing to move.

The install lock is held through step 3 (locks are always taken install first, so two starts
can never wait on each other): the library half also writes into local\\ (the library's logs,
the only-copy banners, the worn banner).

A lock held past its wait, or a move that cannot finish, stops the start with a plain sentence
(moonglade.migrate.MoveStopped): never carry on, since the new homes would read empty.

Nothing is logged while this runs -- logging opens its file in local\\logs\\, which the move
itself fills -- so prepare() returns a Prepared whose log() writes what happened once the
entry point has set logging up.
"""
from pathlib import Path

from moonglade import migrate as _migrate
from moonglade import paths as _paths
from moonglade import settings as _settings

KINDS = ("launcher", "server", "cli", "mcp")

MoveStopped = _migrate.MoveStopped


class Prepared:
    """What prepare() found: the library this run uses (`library`, a Path), and what the move
    did (`report`). log() writes the move's lines to the app's log."""

    def __init__(self, kind, library, report):
        self.kind = kind
        self.library = library
        self.report = report

    def log(self):
        self.report.log()

    def summary(self):
        return self.report.summary()


def prepare(kind, explicit_out=None):
    """Run the move (install half, then the library's) and resolve the library. `kind` is
    one of KINDS; `explicit_out` is this run's own library choice (--out / MOONGLADE_OUT), if
    any. Returns a Prepared. Raises MoveStopped (str(e) is the sentence to show).

    Only a server start counts toward deleting the safety snapshots (pick 4): the launcher
    always starts a server straight after, and the command line and the MCP server can run
    many times an hour."""
    if kind not in KINDS:
        raise ValueError("prepare(kind): kind is one of %s" % (KINDS,))
    report = _migrate.Report()
    local = _paths.local_dir()
    try:
        local.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MoveStopped("Moonglade can't make its folder %s (%s), so it can't start."
                          % (local, _migrate._reason(e)))
    with _migrate.FolderLock(local, "the app folder") as install_lock:
        _migrate.migrate_install(report, lock=install_lock)
        library = _settings.library_path(explicit_out)
        if Path(library).is_dir():
            app = _paths.library_app_dir(library)
            try:
                app.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise MoveStopped("Moonglade can't write in the library folder %s (%s)."
                                  % (library, _migrate._reason(e)))
            with _migrate.FolderLock(app, "the library folder %s" % library) as lib_lock:
                _migrate.migrate_library(library, _migrate.logins_from_config(), report,
                                         lock=lib_lock)
                if kind == "server":
                    _migrate.count_clean_start(app, report, "library")
        if kind == "server":
            _migrate.count_clean_start(local, report, "install")
    return Prepared(kind, library, report)

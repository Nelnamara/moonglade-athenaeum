"""moonglade.setup -- prepare(kind): the first thing every entry point runs (B2).

Before anything reads a setting, every way Moonglade starts -- the launcher, the web server,
the command line, the MCP server -- calls prepare(kind) once:

  1. Under the install lock (local\\.lock): check settings.json can be read (a file that is
     there but unreadable or damaged stops the start: guessing would open the default
     library), then merge the settings into it and run the install half of the move
     (moonglade.migrate.migrate_install). Every kind runs this half.
  2. Resolve the library from settings.json (moonglade.settings.library_path), unless this run
     names one itself (--out, MOONGLADE_OUT).
  3. The library half (moonglade.migrate.prepare_library). Only a launcher or server start
     moves a library's files, and only in the library this install serves: the command line,
     the MCP server and any run naming its own library never move anything, and refuse a
     library still in an older layout with a plain sentence. Every kind stops when an older
     Moonglade is still writing the library's old homes, and every kind refuses a library that
     is the program's own folder (or holds a Moonglade program). A library folder that is not
     there yet is left alone: the server makes it, and the next start finds nothing to move.

The install lock is held through step 3 (locks are always taken install first, so two starts
can never wait on each other): the library half also writes into local\\ (the library's logs,
the only-copy banners, the worn banner).

A lock held past its wait, or a move that cannot finish, stops the start with a plain sentence
(moonglade.migrate.MoveStopped): never carry on, since the new homes would read empty.

Nothing is logged while this runs -- logging opens its file in local\\logs\\, which the move
itself fills -- so prepare() returns a Prepared whose log() writes what happened once the
entry point has set logging up (the launcher, which never sets logging up, appends it to
local\\logs\\moonglade.log with write_log()).

The safety snapshots' clean-start count is the server's to keep (Prepared.count_clean_start):
a start counts once the server has served for a while or was stopped cleanly, never at
prepare(), which a server that then refuses its port or crashes has also run.

peek_server() is what the launcher and the server read BEFORE prepare(): the port this start
will bind, without changing anything, so a second start bows out before it could move files
under a running one.
"""
from pathlib import Path

from moonglade import migrate as _migrate
from moonglade import paths as _paths
from moonglade import settings as _settings

KINDS = ("launcher", "server", "cli", "mcp")
MOVING_KINDS = _migrate.MOVING_KINDS
COUNT_WAIT_S = 5.0          # how long the clean-start count waits for a lock before skipping

MoveStopped = _migrate.MoveStopped


class Prepared:
    """What prepare() found: the library this run uses (`library`, a Path), and what the move
    did (`report`). log() writes the move's lines to the app's log."""

    def __init__(self, kind, library, report, library_moves=False, library_ran=False,
                 named=False):
        self.kind = kind
        self.library = library
        self.report = report
        self.library_moves = library_moves       # the library half ran here (it may move)
        self.library_ran = library_ran           # the library half was looked at (the folder was there)
        self.named = named                       # this run named its own library
        self.counted = False

    def late_library(self):
        """The library folder was not there when prepare() looked, and is now (a NAS waking up,
        a removable drive put back, a folder made between the look and the server's own
        mkdir): the library half runs now, before anything reads the library -- otherwise this
        session would serve an un-moved library with empty spend guards in the new homes. A
        no-op when prepare() already looked, and when there is still no folder. Takes the
        install lock first, as prepare() does. Raises MoveStopped."""
        if self.library_ran or not Path(self.library).is_dir():
            return
        moves = self.kind in MOVING_KINDS and not self.named
        late = _migrate.Report()
        with _migrate.FolderLock(_paths.local_dir(), "the app folder"):
            _migrate.prepare_library(self.library, late, moves=moves, named=self.named)
        self.library_ran = True
        self.library_moves = moves
        # Logging is up by now (the server sets it up after prepare()): what the late look did
        # is written at once, and kept with the rest of the report.
        self.report.items += late.items
        self.report.lines += late.lines
        self.report.parked += late.parked
        for half, worked in late.worked.items():
            self.report.worked[half] = self.report.worked.get(half, False) or worked
        late.log()

    def log(self):
        self.report.log()

    def write_log(self):
        self.report.write_log()

    def summary(self):
        return self.report.summary()

    def count_clean_start(self):
        """One clean start of the server this prepare() was for (S1): call it once the server
        has served for a while, or when it stops cleanly. Counts toward deleting each half's
        safety snapshot (moonglade.migrate.count_clean_start), at most once per start, under
        the locks (a busy lock skips the count rather than wait). Returns the Report of what
        it did. Never raises."""
        rep = _migrate.Report()
        if self.counted:
            return rep
        self.counted = True
        local = _paths.local_dir()
        try:
            with _migrate.FolderLock(local, "the app folder").acquire(wait=COUNT_WAIT_S):
                _migrate.count_clean_start(local, rep)
                app = _paths.library_app_dir(self.library)
                if self.library_moves and app.is_dir():
                    with _migrate.FolderLock(app, "the library folder %s" % self.library) \
                            .acquire(wait=COUNT_WAIT_S):
                        _migrate.count_clean_start(app, rep)
        except (MoveStopped, OSError):
            pass
        return rep


def _check_settings():
    """S4: settings.json there but unreadable, or damaged, stops the start: guessing would open
    the default library, and the first write would throw the real settings away."""
    state, why = _settings.state()
    where = _paths.settings_path()
    if state == "unreadable":
        raise MoveStopped(
            "Moonglade can't read its settings file %s (%s), so it can't tell which library to "
            "open. Close any program that has the file open, then start Moonglade again."
            % (where, why))
    if state == "corrupt":
        raise MoveStopped(
            "Moonglade's settings file %s is damaged (%s), so it can't tell which library to "
            "open, and it won't write over it. Fix the file (it is plain JSON), then start "
            "Moonglade again." % (where, why))


def peek_server(host_arg=None, port_arg=None):
    """{host, port, bonjour_enabled, bonjour_name, launch_args}: what this install's next
    start will bind, read before prepare() and without changing anything (an older version's
    settings still waiting to be merged are read the way the merge will read them). Never
    raises: at worst it answers the defaults, and only decides which port is probed."""
    planned = _migrate.planned_settings()
    out = _settings.server(host_arg, port_arg, doc=planned)
    out["launch_args"] = _settings.launch_args(doc=planned)
    return out


def prepare(kind, explicit_out=None, library_half=True):
    """Run the move (install half, then the library's) and resolve the library. `kind` is
    one of KINDS; `explicit_out` is this run's own library choice (--out / MOONGLADE_OUT), if
    any. `library_half=False` is for a command that never touches the library (the command
    line's --list-web-users and --add-web-user, which read and write config.json alone): the
    install half still runs, but the library is not checked, so a library still in an older
    layout, or an older Moonglade still writing it, does not block a command that never reads
    it. Returns a Prepared. Raises MoveStopped (str(e) is the sentence to show)."""
    if kind not in KINDS:
        raise ValueError("prepare(kind): kind is one of %s" % (KINDS,))
    report = _migrate.Report()
    local = _paths.local_dir()
    try:
        local.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MoveStopped("Moonglade can't make its folder %s (%s), so it can't start. %s"
                          % (local, _migrate._reason(e), _migrate._advice(e)))
    library_moves = False
    library_ran = False
    with _migrate.FolderLock(local, "the app folder") as install_lock:
        _check_settings()
        _migrate.migrate_install(report, lock=install_lock)
        library = _settings.library_path(explicit_out)
        moves = kind in MOVING_KINDS and not explicit_out
        if library_half and Path(library).is_dir():
            _migrate.prepare_library(library, report, moves=moves, named=bool(explicit_out))
            library_moves = moves
            library_ran = True
    # A command that never touches the library (library_half=False) is done with it: it never
    # asks for the late look either.
    return Prepared(kind, library, report, library_moves=library_moves,
                    library_ran=library_ran or not library_half, named=bool(explicit_out))

"""Shared logging baseline for both surfaces (moonglade_backup.py's CLI and
moonglade_gallery.py's web server): a persistent, rotating file under
out_dir/logs/moonglade.log, always on regardless of -v/--verbose -- so a crash
or failure is on record even if nobody remembered the flag, or the terminal
window that would have shown it is already gone.

Design, and why: Python's own logging module, not a new dependency or an OS-log
integration (Windows Event Log via pywin32, syslog) -- this is a public,
cross-platform tool with real external users, and a rotating file is the
portable "robust and standard" choice every platform can read the same way.
Root's own level is left at WARNING so third-party libraries (requests,
urllib3, PIL, ...) that never set their own logger level stay quiet; this
app's own logger, the web server module's own logger (both names it can have --
see GALLERY_LOGGER_NAMES) and werkzeug's request-line logger explicitly override
that ceiling, so their messages reach the handlers regardless. Flask's own internal
`app.logger.error(..., exc_info=...)` call on an unhandled request exception
already logs at ERROR -- above the WARNING ceiling -- so it reaches the file
with no bespoke @app.errorhandler needed. `app.logger`'s own name is the app's: the main
file's stem when the server runs as the main module (`gallery` since 3.20, `moonglade_gallery`
before) and the module name when imported (`moonglade.gallery`). GALLERY_LOGGER_NAMES levels
those too, so the app logger's INFO lines reach the file as they did before the move.
"""
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from moonglade import paths as _paths

LOGGER_NAME = "moonglade"

# The web server's OWN module logger, under both names it can have. moonglade/gallery.py's
# background workers do not use get_logger() -- they use logging.getLogger(__name__), which
# resolves to "__main__" when the server runs as the main module (which is how it always runs
# in production: "Serve Gallery.pyw" launches `python -m moonglade.gallery` as a child) and to
# "moonglade.gallery" when it is imported. Before 3.20 the imported name was the flat
# "moonglade_gallery", and neither name was under LOGGER_NAME, so until 2026-09-07
# every one of those lines inherited root's WARNING ceiling and reached the file only if it
# happened to be a warning. The live mirror is the case that made it matter: its whole
# lifecycle -- "connected and subscribed", "task N reported completed -- mirroring",
# "disconnected cleanly; reconnecting" -- is logged at INFO and was therefore absent from
# moonglade.log entirely, which is the one record that could answer "was the socket up when
# that generation finished?" after the fact. Both names are levelled because both are real:
# the script name in production, the module name under the test suite and anything that
# imports the app.
#
# "gallery" is Flask's own app.logger in production: Flask names it after the main FILE's stem
# when the app's import name is "__main__" (moonglade/gallery.py since 3.20; it was
# "moonglade_gallery" before the move, which this tuple already levelled). Without it the move
# would have put the app logger back under root's WARNING ceiling.
GALLERY_LOGGER_NAMES = ("moonglade.gallery", "__main__", "gallery")

_configured = False
_file_handler = None
_console_handler = None
_prev_excepthook = None
_prev_threading_excepthook = None


def setup_logging(out_dir, verbose=False):
    """Idempotent -- safe to call more than once (tests, a CLI command that
    internally drives another). Only the first call attaches handlers; later
    calls just adjust the verbosity level.

    out_dir: the same output folder everything else in this app already
    lives under (catalog.db, images/, branding/, jobs.jsonl) -- git-ignored
    already, so logs/ needs no new .gitignore entry.
    """
    global _configured, _file_handler, _console_handler
    app_logger = logging.getLogger(LOGGER_NAME)

    if _configured:
        _console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
        return app_logger

    file_handler = _file_handler_for(out_dir)
    fmt = file_handler.formatter

    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setFormatter(fmt)
    _console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)   # sane ceiling for third-party libs that set no level
    root.addHandler(file_handler)
    root.addHandler(_console_handler)

    # The app logger's OWN level stays at the most permissive setting always --
    # it is the HANDLERS (file always DEBUG, console DEBUG-only-if-verbose)
    # that decide what's actually written where. Gating app_logger itself on
    # verbose would suppress DEBUG-level app messages (vlog()'s own calls,
    # among others) from ever reaching the file even when not verbose --
    # exactly the "forgot -v, nothing on record" problem this exists to fix.
    app_logger.setLevel(logging.DEBUG)
    for _name in GALLERY_LOGGER_NAMES:                     # the web server's own module logger
        logging.getLogger(_name).setLevel(logging.DEBUG)
    logging.getLogger("werkzeug").setLevel(logging.INFO)   # request lines, always

    _install_crash_hook(app_logger)
    _file_handler = file_handler
    _configured = True
    return app_logger


def _file_handler_for(out_dir):
    """The rotating file handler for out_dir's log (log_path()), its folder made."""
    log_file = log_path(out_dir)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        str(log_file), when="midnight", backupCount=14, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    handler.setLevel(logging.DEBUG)   # the file always captures everything
    return handler


def reopen(out_dir):
    """Point the file log at log_path(out_dir) when that has moved since setup_logging()
    opened it -- 3.20: logging opens before a library is brought across (in its old logs/,
    where an unmigrated library still keeps it), and moonglade.migrate.open_library() calls
    this once the copy into _moonglade/logs/ is made. Returns True when it re-pointed; a no-op
    (False) when logging is not set up or is already writing there. Never raises."""
    global _file_handler
    if not _configured or _file_handler is None:
        return False
    try:
        new = os.path.normcase(os.path.abspath(str(log_path(out_dir))))
        if os.path.normcase(_file_handler.baseFilename) == new:
            return False
        handler = _file_handler_for(out_dir)
    except Exception:
        return False
    root = logging.getLogger()
    root.addHandler(handler)
    old, _file_handler = _file_handler, handler
    root.removeHandler(old)
    try:
        old.close()
    except Exception:
        pass
    return True


def _install_crash_hook(logger):
    """Log any uncaught exception at CRITICAL, then hand off to whatever
    excepthook was already installed (Python's default, printing the
    traceback to stderr) so the user-visible behavior is unchanged -- this
    only ADDS a permanent record of the crash, it doesn't alter how it's
    reported to the terminal.

    BOTH of Python's hooks are installed, because there are two and they do not
    overlap. `sys.excepthook` fires ONLY for the main thread. An uncaught exception
    in any background worker -- the web app's sync/build/thumbnail jobs, the
    live-mirror watcher thread -- goes to `threading.excepthook` instead, which was
    left at its default until 2026-07-27: it printed a traceback to a stderr nobody
    was watching and returned, leaving zero trace in out_dir/logs/moonglade.log. That
    is exactly the "terminal window that would have shown it is already gone" case in
    this module's own docstring, and it meant a background job that died looked
    identical to a background job that quietly stopped.

    The threading hook takes ONE args object (exc_type/exc_value/exc_traceback/thread),
    not sys.excepthook's three positionals, so it cannot simply reuse _hook.

    NOT covered, deliberately: a function raising inside a
    concurrent.futures.ThreadPoolExecutor worker (run_download's parallel branch, the
    gallery's job runners). The executor catches BaseException itself and parks it on
    the Future, so NEITHER hook ever fires -- the traceback exists only if somebody
    calls future.result(). There is no hook to install for that; making those visible
    means logging where the futures are collected, at the call sites."""
    global _prev_excepthook, _prev_threading_excepthook
    previous_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        if exc_type is not KeyboardInterrupt:      # Ctrl+C is not a crash
            logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        previous_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        # Same Ctrl+C exclusion as the main hook, plus SystemExit -- CPython's own
        # default threading hook silently ignores SystemExit, because sys.exit() inside
        # a worker is an ordinary way to end that thread; filing it at CRITICAL would
        # record an orderly shutdown as a crash.
        if args.exc_type not in (KeyboardInterrupt, SystemExit):
            logger.critical(
                "Uncaught exception in thread %s",
                getattr(args.thread, "name", None) or "<unknown>",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        previous_thread_hook(args)

    _prev_excepthook = previous_hook
    _prev_threading_excepthook = previous_thread_hook
    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def log_path(out_dir):
    """The current log file's path, for a future --show-logs/Panel affordance."""
    return _paths.state_path(out_dir, "logs") / "moonglade.log"


# serve.log, the launcher's capture of the server's console (Serve Gallery.pyw), is appended
# to on every start. It is trimmed at start instead of by a logging handler: the server's
# stdout and stderr are written straight into the file by the OS, so nothing in Python sees
# the lines go by.
SERVE_LOG_MAX_BYTES = 1024 * 1024
SERVE_LOG_KEEP = 3


def rotate_by_size(path, max_bytes=SERVE_LOG_MAX_BYTES, keep=SERVE_LOG_KEEP):
    """Run before the file is opened for appending: when `path` is over `max_bytes`, it
    becomes `<name>.1`, the older ones shift up to `<name>.<keep>` and the oldest is dropped.
    Returns True when it rotated; never raises -- a log must never stop the app starting.

    The order is what keeps a refused rotation from losing anything. The usual refusal is the
    log itself being held open by another process (Windows will not rename an open file), so
    the log is moved aside to a temporary name FIRST: if that is refused, nothing has been
    touched. Only then do the old logs shift up, and the moved-aside log becomes `.1`. If a
    shift is refused half-way, the log is put back where the launcher appends and the
    rotation is abandoned, the old logs still there."""
    p = Path(path)
    try:
        if p.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False
    aside = p.with_name("%s.rotating-%d" % (p.name, os.getpid()))
    try:
        os.replace(p, aside)
    except OSError:
        return False                       # held open elsewhere: nothing was touched
    try:
        for n in range(max(1, int(keep)) - 1, 0, -1):
            older = p.with_name("%s.%d" % (p.name, n))
            if older.exists():
                os.replace(older, p.with_name("%s.%d" % (p.name, n + 1)))
        os.replace(aside, p.with_name(p.name + ".1"))
    except OSError:
        try:
            os.replace(aside, p)           # back where the launcher appends
        except OSError:
            pass
        return False
    return True


def get_logger():
    return logging.getLogger(LOGGER_NAME)


def _reset_for_tests():
    """Test-only: undo setup_logging() so each test starts clean. Not called
    by any production code path.

    The crash hooks are restored too, not just the handlers: each _install_crash_hook()
    call closes over whatever hook it found and chains to it, so a reset that left them
    installed would have the NEXT setup_logging() chain onto the old pair, and one crash
    would be written to the log once per surviving link. Harmless in production (the hook
    is installed once per process) but it compounds across a test session -- and there
    are two hooks to leak now, not one."""
    global _configured, _file_handler, _console_handler
    global _prev_excepthook, _prev_threading_excepthook
    if _prev_excepthook is not None:
        sys.excepthook = _prev_excepthook
    if _prev_threading_excepthook is not None:
        threading.excepthook = _prev_threading_excepthook
    _prev_excepthook = None
    _prev_threading_excepthook = None
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(logging.WARNING)
    logging.getLogger(LOGGER_NAME).setLevel(logging.NOTSET)
    for name in GALLERY_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.NOTSET)
    logging.getLogger("werkzeug").setLevel(logging.NOTSET)
    _configured = False
    _file_handler = None
    _console_handler = None

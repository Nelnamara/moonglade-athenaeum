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
app's own logger and werkzeug's request-line logger explicitly override that
ceiling, so their messages reach the handlers regardless. Flask's own internal
`app.logger.error(..., exc_info=...)` call on an unhandled request exception
already logs at ERROR -- above the WARNING ceiling -- so it reaches the file
with no bespoke @app.errorhandler needed, and it works under whatever name
`app.logger` resolves to (`__main__` when run as a script, `moonglade_gallery`
when imported) without this module needing to know or care which.
"""
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOGGER_NAME = "moonglade"

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

    log_dir = Path(out_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.TimedRotatingFileHandler(
        str(log_dir / "moonglade.log"), when="midnight", backupCount=14,
        encoding="utf-8", delay=True)
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)   # the file always captures everything

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
    logging.getLogger("werkzeug").setLevel(logging.INFO)   # request lines, always

    _install_crash_hook(app_logger)
    _file_handler = file_handler
    _configured = True
    return app_logger


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
    return Path(out_dir) / "logs" / "moonglade.log"


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
    logging.getLogger("werkzeug").setLevel(logging.NOTSET)
    _configured = False
    _file_handler = None
    _console_handler = None

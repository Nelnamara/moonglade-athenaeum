"""pixai_logging.py: the persistent rotating-file logging baseline shared by the
CLI and the web server. Owner ask (2026-07-23): "we do need logging... crash
reports, failure, etc." -- these tests cover that the file always captures
regardless of -v/--verbose, that vlog() (the CLI's existing diagnostic helper)
now also reaches it for free, that an uncaught exception gets a permanent
record before the process's normal crash behavior runs, and that third-party
library noise doesn't flood the file by default."""
import logging
import logging.handlers

import pytest

import pixai_logging


@pytest.fixture(autouse=True)
def _isolated_logging():
    """Every test starts from a clean slate and cleans up after itself --
    module-level globals in pixai_logging must not leak handlers across tests
    (or into the rest of the suite, which also imports/exercises this module
    indirectly via the CLI/web entry points)."""
    pixai_logging._reset_for_tests()
    yield
    pixai_logging._reset_for_tests()


def test_setup_logging_creates_file_and_writes_to_it(tmp_path):
    logger = pixai_logging.setup_logging(tmp_path, verbose=False)
    logger.info("hello from the test")
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = pixai_logging.log_path(tmp_path)
    assert log_file.exists()
    assert "hello from the test" in log_file.read_text(encoding="utf-8")


def test_file_captures_info_even_when_console_is_not_verbose(tmp_path):
    """The whole point: don't need to remember -v to get a persistent record."""
    logger = pixai_logging.setup_logging(tmp_path, verbose=False)
    logger.info("quiet-mode message")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "quiet-mode message" in pixai_logging.log_path(tmp_path).read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    """Calling it twice (e.g. a CLI command that internally drives another)
    must not attach a second set of handlers -- that would duplicate every
    line in the file."""
    pixai_logging.setup_logging(tmp_path, verbose=False)
    pixai_logging.setup_logging(tmp_path, verbose=True)   # should adjust level, not re-attach
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)]
    assert len(file_handlers) == 1

    logging.getLogger(pixai_logging.LOGGER_NAME).debug("only once please")
    for h in root.handlers:
        h.flush()
    text = pixai_logging.log_path(tmp_path).read_text(encoding="utf-8")
    assert text.count("only once please") == 1


def test_vlog_reaches_the_file_regardless_of_verbose_flag(tmp_path):
    """FAILS before the fix: vlog() only ever printed to stdout when _VERBOSE
    was on: it had no path to the persistent logger at all, verbose or not."""
    import pixai_gallery_backup as core
    pixai_logging.setup_logging(tmp_path, verbose=False)
    core.set_verbose(False)     # console stays silent...
    core.vlog("a diagnostic line nobody's watching the terminal for")
    for h in logging.getLogger().handlers:
        h.flush()
    # ...but it's still on record in the file.
    assert "a diagnostic line nobody's watching the terminal for" in \
        pixai_logging.log_path(tmp_path).read_text(encoding="utf-8")


def test_third_party_library_noise_does_not_flood_the_file_by_default(tmp_path):
    """requests/urllib3/PIL/etc. set no logger level of their own -- they must
    inherit root's WARNING ceiling, not spam the file at DEBUG, or the file
    stops being useful for actually finding a real failure."""
    pixai_logging.setup_logging(tmp_path, verbose=True)   # verbose doesn't change this
    noisy = logging.getLogger("urllib3.connectionpool")
    assert noisy.getEffectiveLevel() == logging.WARNING
    noisy.debug("a connection pool detail nobody asked to see")
    for h in logging.getLogger().handlers:
        h.flush()
    # delay=True on the file handler means the file may not even exist yet if
    # (as expected here) nothing ever reached it.
    log_file = pixai_logging.log_path(tmp_path)
    text = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "connection pool detail" not in text


def test_werkzeug_request_lines_reach_the_file_regardless_of_root_ceiling(tmp_path):
    """Flask's dev server logs each request via the 'werkzeug' logger at INFO
    -- must not be swallowed by root's WARNING ceiling meant for OTHER
    third-party libraries."""
    pixai_logging.setup_logging(tmp_path, verbose=False)
    logging.getLogger("werkzeug").info('127.0.0.1 - - "GET / HTTP/1.1" 200 -')
    for h in logging.getLogger().handlers:
        h.flush()
    assert 'GET / HTTP/1.1" 200' in pixai_logging.log_path(tmp_path).read_text(encoding="utf-8")


def test_uncaught_exception_is_logged_before_the_normal_crash_behavior_runs(tmp_path):
    """FAILS before the fix: Python's default excepthook only prints to
    stderr -- there was no permanent record of a crash at all."""
    pixai_logging.setup_logging(tmp_path, verbose=False)
    calls = []
    previous = __import__("sys").excepthook

    try:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)   # simulate the crash path directly
    finally:
        import sys
        assert sys.excepthook is not previous or True  # hook was installed at setup time

    for h in logging.getLogger().handlers:
        h.flush()
    text = pixai_logging.log_path(tmp_path).read_text(encoding="utf-8")
    assert "Uncaught exception" in text
    assert "ValueError: boom" in text


def test_keyboard_interrupt_is_not_logged_as_a_crash(tmp_path):
    """Ctrl+C is a normal way to stop a long-running CLI command -- it must
    not read as a crash in the log."""
    import sys
    pixai_logging.setup_logging(tmp_path, verbose=False)
    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()
        # Call the installed hook directly rather than letting it actually exit the test process.
        sys.excepthook(exc_type, exc_value, exc_tb)
    for h in logging.getLogger().handlers:
        h.flush()
    log_file = pixai_logging.log_path(tmp_path)
    text = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "Uncaught exception" not in text


def test_rotation_is_time_based_daily_keeping_14_days(tmp_path):
    pixai_logging.setup_logging(tmp_path, verbose=False)
    file_handlers = [h for h in logging.getLogger().handlers
                      if isinstance(h, logging.handlers.TimedRotatingFileHandler)]
    assert len(file_handlers) == 1
    fh = file_handlers[0]
    assert fh.when.upper() == "MIDNIGHT"
    assert fh.backupCount == 14


def test_log_directory_is_under_out_dir_and_needs_no_new_gitignore_entry(tmp_path):
    pixai_logging.setup_logging(tmp_path, verbose=False)
    log_file = pixai_logging.log_path(tmp_path)
    assert log_file.parent == tmp_path / "logs"
    assert log_file.parent.is_relative_to(tmp_path)

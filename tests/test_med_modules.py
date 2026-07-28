"""Regression tests for the three small modules the CLI/gallery lean on but almost
nothing else in the suite reaches: moonglade_logging.py's crash hooks,
moonglade_similar.py's index maintenance, and moonglade_mcp.py's write/report
contracts. All three defects here shared one shape -- a failure that produced no
signal at all: a worker thread that crashed with nothing in the log, a similarity
result silently short of what was asked for, and a rating write that reported
success without writing.

moonglade_mcp imports fastmcp, which is an OPTIONAL dep (requirements-mcp.txt, not
requirements.txt) and is installed neither on a normal dev machine nor in CI. Skipping
the whole file on that basis would mean the set_rating fix below is verified nowhere,
which is the same "green suite that cannot see the bug it was written for" failure the
tests.yml Playwright comment argues against -- so a minimal stub stands in when the real
package is absent. It fakes only what this module touches at import time; the tool
bodies under test are the real ones.
"""
import logging
import sys
import threading
import types

import pytest

import moonglade_gallery as g
import moonglade_logging


# --- moonglade_mcp import shim --------------------------------------------------

def _install_fastmcp_stub():
    fastmcp = types.ModuleType("fastmcp")

    class _StubFastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self, fn):
            # The real @mcp.tool returns a FunctionTool wrapper around fn; _fn() below
            # unwraps either shape, so tests read the same against stub and real package.
            return fn

        def run(self, *a, **k):
            raise AssertionError("the fastmcp stub must never start a server")

    class _StubImage:
        def __init__(self, data=None, format=None):
            self.data, self.format = data, format

    utilities = types.ModuleType("fastmcp.utilities")
    utility_types = types.ModuleType("fastmcp.utilities.types")
    utility_types.Image = _StubImage
    utilities.types = utility_types
    fastmcp.FastMCP = _StubFastMCP
    fastmcp.utilities = utilities
    sys.modules.setdefault("fastmcp", fastmcp)
    sys.modules.setdefault("fastmcp.utilities", utilities)
    sys.modules.setdefault("fastmcp.utilities.types", utility_types)


try:                       # prefer the real package wherever it IS installed
    import fastmcp         # noqa: F401
except ImportError:
    _install_fastmcp_stub()

import moonglade_mcp as M   # noqa: E402  (must follow the stub install)


def _fn(tool):
    """The plain function behind an @mcp.tool -- FunctionTool.fn under real fastmcp,
    the function itself under the stub."""
    return getattr(tool, "fn", tool)


def _seed(tmp_path, media_ids):
    """A catalog holding exactly `media_ids`, plus a file on disk for each so
    find_image_file resolves. Returns the db path."""
    db = tmp_path / "catalog.db"
    rows = []
    for mid in media_ids:
        row = {f: "" for f in g.CATALOG_FIELDS}
        row.update(media_id=mid, filename="{}.png".format(mid),
                   created_at="2025-01-01T00:00:00")
        rows.append(row)
        (tmp_path / "{}.png".format(mid)).write_bytes(b"not-really-a-png")
    g.save_catalog(db, rows)
    return db


@pytest.fixture()
def mcp_out(tmp_path, monkeypatch):
    """Point the module-level OUT/DB (resolved from env at import) at this test's dir."""
    def _point(media_ids):
        db = _seed(tmp_path, media_ids)
        monkeypatch.setattr(M, "OUT", tmp_path)
        monkeypatch.setattr(M, "DB", str(db))
        return db
    return _point


# --- M11: the crash hook covers background threads, not just the main one -------

@pytest.fixture(autouse=True)
def _isolated_logging():
    """Snapshot BOTH hooks around every test and hard-restore them afterwards.
    _reset_for_tests() already puts back what it recorded, but a test that installs
    its own sentinel before setup_logging() would otherwise leave that sentinel
    behind as the restored "previous" hook for the rest of the session."""
    saved = (sys.excepthook, threading.excepthook)
    moonglade_logging._reset_for_tests()
    yield
    moonglade_logging._reset_for_tests()
    sys.excepthook, threading.excepthook = saved


def _flush():
    for h in logging.getLogger().handlers:
        h.flush()


def _log_text(tmp_path):
    p = moonglade_logging.log_path(tmp_path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_uncaught_exception_in_a_background_thread_reaches_the_file(tmp_path):
    """FAILS before the fix: only sys.excepthook was overridden, and Python routes a
    worker thread's uncaught exception through threading.excepthook instead -- the
    default one, which prints to stderr and returns. The web app's sync/build jobs and
    the watcher all run on such threads, so their crashes left no record at all."""
    # Chain into a no-op instead of pytest's own threadexception hook: this test raises
    # an unhandled thread exception on purpose, and that plugin would turn it into a
    # PytestUnhandledThreadExceptionWarning every run. Chaining itself is asserted by
    # the next test. Installed BEFORE setup_logging, which captures what it chains to.
    threading.excepthook = lambda args: None
    moonglade_logging.setup_logging(tmp_path, verbose=False)

    def boom():
        raise ValueError("worker exploded")

    t = threading.Thread(target=boom, name="mg-worker-under-test")
    t.start()
    t.join()
    _flush()

    text = _log_text(tmp_path)
    assert "Uncaught exception in thread mg-worker-under-test" in text
    assert "ValueError: worker exploded" in text


def test_thread_crash_hook_still_chains_to_whatever_was_installed(tmp_path):
    """The hook only ADDS a record; it must not swallow the traceback Python would
    otherwise have printed, exactly like the main-thread hook."""
    seen = []
    threading.excepthook = lambda args: seen.append(args.exc_type)
    moonglade_logging.setup_logging(tmp_path, verbose=False)

    t = threading.Thread(target=lambda: 1 / 0, name="mg-chain-test")
    t.start()
    t.join()
    _flush()

    assert seen == [ZeroDivisionError]
    assert "Uncaught exception in thread mg-chain-test" in _log_text(tmp_path)


def test_keyboard_interrupt_in_a_thread_is_not_logged_as_a_crash(tmp_path):
    """Ctrl+C stopping a long job is not a crash on the main thread and is not one in
    a worker either -- same exclusion, or every interrupted run files a false crash."""
    threading.excepthook = lambda args: None      # chained into; keeps pytest's warning out
    moonglade_logging.setup_logging(tmp_path, verbose=False)

    def interrupted():
        raise KeyboardInterrupt()

    t = threading.Thread(target=interrupted, name="mg-ctrl-c")
    t.start()
    t.join()
    _flush()

    assert "Uncaught exception" not in _log_text(tmp_path)


def test_system_exit_in_a_thread_is_not_logged_as_a_crash(tmp_path):
    """sys.exit() inside a worker is an ordinary way to end that thread -- CPython's own
    default threading hook ignores it, so recording it at CRITICAL would file an orderly
    shutdown as a crash."""
    threading.excepthook = lambda args: None      # chained into; keeps pytest's warning out
    moonglade_logging.setup_logging(tmp_path, verbose=False)

    t = threading.Thread(target=sys.exit, name="mg-orderly-exit")
    t.start()
    t.join()
    _flush()

    assert "Uncaught exception" not in _log_text(tmp_path)


def test_main_thread_crash_hook_is_unchanged(tmp_path):
    """Installing the second hook must not disturb the first one."""
    moonglade_logging.setup_logging(tmp_path, verbose=False)
    try:
        raise RuntimeError("main-thread boom")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    _flush()

    text = _log_text(tmp_path)
    assert "Uncaught exception" in text
    assert "RuntimeError: main-thread boom" in text


# --- M12a: the MCP `similar` tool names its own truncation ----------------------

def _fake_similar_module(hits):
    return types.SimpleNamespace(
        similar=lambda path, k=48, exclude_media_id=None: list(hits))


def test_similar_reports_stale_index_entries_instead_of_a_short_count(mcp_out, monkeypatch):
    """FAILS before the fix: neighbours whose catalog row is gone were dropped in
    silence, so a limit:24 request answered count:1 with nothing to distinguish
    "the index is stale" from "there is only one similar image in the library"."""
    mcp_out(["q", "n1"])
    monkeypatch.setitem(sys.modules, "moonglade_similar",
                        _fake_similar_module([("n1", 0.9), ("gone1", 0.8), ("gone2", 0.7)]))

    d = _fn(M.similar)("q", limit=24)

    assert [n["media_id"] for n in d["neighbors"]] == ["n1"]
    assert d["count"] == 1
    assert d["requested"] == 24
    assert d["stale_index_entries"] == 2
    assert d["stale_media_ids"] == ["gone1", "gone2"]
    assert "rebuild-similar" in d["note"]


def test_similar_says_zero_stale_when_the_index_is_clean(mcp_out, monkeypatch):
    """A healthy index must not grow an explanatory note -- the note is the signal that
    something needs maintenance, so it has to mean something when it appears."""
    mcp_out(["q", "n1", "n2"])
    monkeypatch.setitem(sys.modules, "moonglade_similar",
                        _fake_similar_module([("n1", 0.9), ("n2", 0.8)]))

    d = _fn(M.similar)("q", limit=24)

    assert d["count"] == 2
    assert d["stale_index_entries"] == 0
    assert "note" not in d
    assert "stale_media_ids" not in d


def test_similar_requested_reflects_the_clamped_limit(mcp_out, monkeypatch):
    """`requested` has to be the k actually asked of the index (limit is clamped to
    1..96), or comparing it against `count` misleads at the boundaries."""
    mcp_out(["q"])
    monkeypatch.setitem(sys.modules, "moonglade_similar", _fake_similar_module([]))

    assert _fn(M.similar)("q", limit=500)["requested"] == 96
    assert _fn(M.similar)("q", limit=0)["requested"] == 1


# --- M13: set_rating tells the truth about whether it wrote ---------------------

def test_set_rating_reports_failure_for_an_unknown_media_id(mcp_out):
    """FAILS before the fix: g.update_rating is a bare UPDATE that matches zero rows for
    an unknown id, and the tool returned ok:True regardless -- a typo or a stale id read
    as a successful write and the image stayed unrated."""
    db = mcp_out(["real1"])

    res = _fn(M.set_rating)("typo-not-in-catalog", 5)

    assert res["ok"] is False
    assert res["error"] == "no such media_id"
    assert res["media_id"] == "typo-not-in-catalog"
    assert g.get_row(str(db), "real1")["rating"] in ("", None)   # nothing else touched


def test_set_rating_still_writes_for_a_real_media_id(mcp_out):
    db = mcp_out(["real1"])

    res = _fn(M.set_rating)("real1", 4)

    assert res == {"ok": True, "media_id": "real1", "rating": 4}
    assert g.get_row(str(db), "real1")["rating"] == "4"


def test_set_rating_clamps_and_still_persists(mcp_out):
    """The 0-5 clamp predates this change and must survive it -- the existence check
    runs before the write, not instead of it."""
    db = mcp_out(["real1"])

    assert _fn(M.set_rating)("real1", 99)["rating"] == 5
    assert g.get_row(str(db), "real1")["rating"] == "5"

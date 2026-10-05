"""serve.log trims itself (Wave 4 groundwork, 3.19.0).

The launcher appends the server's console output to serve.log and never trimmed it (2.5 MB
on a long-running install). At start, before it opens the file, a log over 1 MB now becomes
serve.log.1, the older ones shift to .2 and .3, and the oldest is dropped. Everything else
the launcher does is unchanged.

The rotation is moonglade_logging.rotate_by_size, tested here on a temp folder; the launcher
runs on import (it is a script), so its use of it is read off its source.
"""
import ast

import pytest

import moonglade_logging as mlog
from tests.conftest import REPO_ROOT

MB = 1024 * 1024


def _write(p, text, size=None):
    data = text.encode("utf-8")
    if size is not None:
        data = data + b"x" * (size - len(data))
    p.write_bytes(data)


def _head(p, n=None):
    """The text a fixture log starts with (its padding to a size is all "x")."""
    return p.read_bytes()[:n].decode("utf-8").rstrip("x")


@pytest.fixture
def app(tmp_path):
    """A folder of its own: conftest seeds a pack into tmp_path itself."""
    d = tmp_path / "app"
    d.mkdir()
    return d


def test_the_limits_are_one_megabyte_and_three_old_logs():
    assert mlog.SERVE_LOG_MAX_BYTES == MB
    assert mlog.SERVE_LOG_KEEP == 3


def test_a_small_log_is_left_alone(app):
    log = app / "serve.log"
    _write(log, "current", MB)                     # exactly the limit: not over it
    assert mlog.rotate_by_size(log) is False
    assert log.stat().st_size == MB
    assert not (app / "serve.log.1").exists()


def test_no_log_yet_is_not_an_error(app):
    assert mlog.rotate_by_size(app / "serve.log") is False
    assert list(app.iterdir()) == []


def test_a_big_log_becomes_dot_one_and_the_older_ones_shift(app):
    log = app / "serve.log"
    _write(log, "newest", MB + 1)
    _write(app / "serve.log.1", "one")
    _write(app / "serve.log.2", "two")
    _write(app / "serve.log.3", "three")
    assert mlog.rotate_by_size(log) is True
    assert not log.exists()                        # the launcher opens a fresh one
    assert _head(app / "serve.log.1") == "newest"
    assert _head(app / "serve.log.2") == "one"
    assert _head(app / "serve.log.3") == "two"
    assert sorted(p.name for p in app.iterdir()) == [
        "serve.log.1", "serve.log.2", "serve.log.3"]  # the oldest ("three") is gone


def test_it_keeps_three_across_many_starts(app):
    log = app / "serve.log"
    for n in range(6):
        _write(log, "run%d" % n, MB + 10)
        mlog.rotate_by_size(log)
    assert sorted(p.name for p in app.iterdir()) == [
        "serve.log.1", "serve.log.2", "serve.log.3"]
    assert [_head(app / ("serve.log.%d" % i)) for i in (1, 2, 3)] == [
        "run5", "run4", "run3"]


def test_a_gap_in_the_old_logs_is_fine(app):
    log = app / "serve.log"
    _write(log, "newest", MB + 1)
    _write(app / "serve.log.2", "two")             # no .1
    assert mlog.rotate_by_size(log) is True
    assert _head(app / "serve.log.1") == "newest"
    assert _head(app / "serve.log.3") == "two"


def test_a_refused_rename_never_stops_the_start(app, monkeypatch):
    """A file Windows will not let go of (another process holding it): nothing raises, and
    the log is left as it was to be appended to."""
    import os
    log = app / "serve.log"
    _write(log, "held", MB + 1)

    def refuse(*a, **k):
        raise PermissionError("in use")
    monkeypatch.setattr(os, "replace", refuse)
    assert mlog.rotate_by_size(log) is False
    assert _head(log) == "held"


# ---- the launcher uses it, at start, on the machine file -------------------------------

def _launcher():
    src = (REPO_ROOT / "Serve Gallery.pyw").read_text(encoding="utf-8")
    return src, ast.parse(src)


def _top_index(tree, pred):
    for i, node in enumerate(tree.body):
        if any(pred(n) for n in ast.walk(node)):
            return i
    return None


def _calls(name):
    return lambda n: isinstance(n, ast.Call) and (
        getattr(n.func, "attr", None) == name or getattr(n.func, "id", None) == name)


def test_the_launcher_rotates_serve_log_before_it_opens_it():
    src, tree = _launcher()
    guard = _top_index(tree, lambda n: isinstance(n, ast.If) and any(
        _calls("_moonglade_on_port")(c) for c in ast.walk(n.test)))
    rotate = _top_index(tree, _calls("rotate_by_size"))
    opened = _top_index(tree, lambda n: _calls("open")(n) and (
        "serve.log" in ast.unparse(n) or "_serve_log" in ast.unparse(n)))
    loop = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.While))
    assert None not in (guard, rotate, opened, loop), (guard, rotate, opened, loop)
    # after the single-instance check (a second launcher must not touch the running one's
    # log), before the log is opened, and once -- not on every exit-42 relaunch
    assert guard < rotate < opened < loop
    assert 'local_path("serve.log")' in src


def test_the_launcher_still_supervises_and_relaunches_on_42():
    src, _ = _launcher()
    assert "RESTART_CODE = 42" in src
    assert 'MOONGLADE_SUPERVISED="1"' in src
    assert "if rc == RESTART_CODE:" in src and "continue" in src

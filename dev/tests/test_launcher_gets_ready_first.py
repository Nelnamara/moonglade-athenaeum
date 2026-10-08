"""The launcher gets the install ready before it reads a setting (3.20 rebuild, B2).

`Moonglade Launcher.pyw` calls moonglade.setup.prepare("launcher") first: the settings merge
and the move, under their locks, before settings.json or the port is read. Claims:
  * it looks for a server already on its port FIRST (S1), from the settings as the move will
    leave them (moonglade.setup.peek_server), so a second double-click never moves anything
    under a running server;
  * prepare runs once, with "launcher", before the first setting is read -- what it puts in
    place (settings.json's port) is what the launcher then probes and opens;
  * what getting ready did goes into local/logs/moonglade.log, one line per file;
  * a server that stops as it starts is said in a message box, with the reason serve.log
    holds (S10);
  * a start that cannot get ready says why, plainly, and stops: no server, no browser. On
    Windows that is a message box (pythonw has no console) and a line in local/logs/serve.log.
    MoveStopped's text is the sentence shown;
  * moonglade.setup is part of every build now: one that is missing, or fails to import, stops
    the start like any other failure.

The .pyw runs on import, so it is run with runpy and every outside effect stood in for, the
same way dev/tests/test_launcher_runs_the_package.py runs it.
"""
import importlib.abc
import importlib.util
import runpy
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
import webbrowser

import pytest

from moonglade import paths
from tests.conftest import REPO_ROOT, stub_code_module

LAUNCHER = REPO_ROOT / "Moonglade Launcher.pyw"


class _NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


@pytest.fixture
def launch(monkeypatch, tmp_path):
    import ctypes

    def _launch(codes=(0,), windows=False, child_says="", ours_on_port=False):
        codes = list(codes)
        run = types.SimpleNamespace(started=[], boxes=[], probed=[], opened=[], exit=None)

        def popen(cmd, **kw):
            run.started.append(types.SimpleNamespace(cmd=list(cmd), **kw))
            if child_says:
                kw["stderr"].write(child_says)
            rc = codes.pop(0)
            return types.SimpleNamespace(wait=lambda: rc)

        def urlopen(url, timeout=None):
            run.probed.append(url)
            if ours_on_port:            # the gated /api/ping answers 401 with our header
                raise urllib.error.HTTPError(url, 401, "login", {"X-Moonglade": "1"}, None)
            raise urllib.error.URLError("refused")

        def box(hwnd, text, title, flags):
            run.boxes.append((text, title))
            return 1

        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(webbrowser, "open", lambda url: run.opened.append(url))
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(threading, "Thread", _NoThread)
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(
            user32=types.SimpleNamespace(MessageBoxW=box)), raising=False)
        if windows:
            monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.chdir(tmp_path)              # it changes directory; this puts it back
        try:
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        except SystemExit as e:
            run.exit = e.code
        return run
    return _launch


def _setup(prepare, port=5000):
    return types.SimpleNamespace(prepare=prepare, peek_server=lambda: {"port": port})


def test_it_gets_ready_once_before_it_reads_a_setting(launch, monkeypatch):
    calls = []

    def prepare(kind):
        calls.append(kind)
        # what the merge puts in place is what the launcher must then read
        paths.settings_path().write_text('{"port": 5959}', encoding="utf-8")

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[42, 0])
    assert calls == ["launcher"]                      # once, not again on a relaunch
    assert len(run.started) == 2
    assert run.started[0].cmd == [sys.executable, "-m", "moonglade.gallery"]
    # the port as it will be (read before the move), then the one the move put in place
    assert run.probed == ["http://localhost:5000/api/ping", "http://localhost:5959/api/ping"]


def test_the_real_prepare_runs_and_its_move_happens_first(launch):
    """Not stubbed: the real moonglade.setup.prepare("launcher") runs in this test's own
    local/ (conftest pins it), so an install's journal is there before the server starts."""
    run = launch(codes=[0])
    assert len(run.started) == 1
    assert (paths.local_dir() / ".journal.json").is_file()


def test_a_move_that_stops_shows_its_own_sentence(launch, monkeypatch):
    from moonglade import migrate

    def prepare(kind):
        raise migrate.MoveStopped("Another start is getting Moonglade ready. Try again in a "
                                  "minute.")

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[0], windows=True)
    assert run.exit == 1 and run.started == []
    assert "Another start is getting Moonglade ready." in run.boxes[0][0]


def test_what_getting_ready_did_goes_in_serve_log(launch, monkeypatch):
    said = types.SimpleNamespace(summary=lambda: "Moved serve.txt into local.")
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: said))
    launch(codes=[0])
    log = (paths.logs_dir() / "serve.log").read_text(encoding="utf-8")
    assert "[launcher] Moved serve.txt into local." in log


@pytest.mark.parametrize("failure", [
    RuntimeError("Another start is getting this install ready. Try again in a minute."),
    SystemExit("Another start is getting this install ready. Try again in a minute."),
], ids=["raises", "exits-with-a-message"])
def test_a_start_that_cannot_get_ready_says_why_and_stops(launch, monkeypatch, failure):
    def prepare(kind):
        raise failure

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[0], windows=True)
    assert run.exit == 1
    assert run.started == [], "a start that could not get ready must never carry on"
    assert len(run.boxes) == 1
    text, title = run.boxes[0]
    assert title == "Moonglade Athenaeum"
    assert "Another start is getting this install ready. Try again in a minute." in text
    assert "Try again in a minute." in (paths.logs_dir() / "serve.log").read_text(
        encoding="utf-8")


def test_off_windows_it_says_so_on_stderr(launch, monkeypatch, capsys):
    def prepare(kind):
        raise RuntimeError("The library's folder is busy.")

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[0], windows=False)
    assert run.exit == 1 and run.started == []
    if sys.platform != "win32":
        assert run.boxes == []
    assert "The library's folder is busy." in capsys.readouterr().err


def test_a_build_without_moonglade_setup_stops(launch, monkeypatch):
    """The data layer is part of the build: without it nothing would bring an older install's
    settings across, so the launcher says so and stops rather than start on empty homes."""
    import moonglade
    monkeypatch.delattr(moonglade, "setup", raising=False)
    monkeypatch.setitem(sys.modules, "moonglade.setup", None)    # "no such module"
    run = launch(codes=[0], windows=True)
    assert run.exit == 1 and run.started == []
    assert len(run.boxes) == 1


class _BrokenSetupFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """moonglade.setup exists, but importing it fails on a module IT needs."""

    def find_spec(self, name, path=None, target=None):
        if name == "moonglade.setup":
            return importlib.util.spec_from_loader(name, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ModuleNotFoundError("No module named 'somedependency'", name="somedependency")


def test_a_setup_module_that_fails_to_import_stops_the_start(launch, monkeypatch):
    import moonglade
    monkeypatch.delattr(moonglade, "setup", raising=False)
    monkeypatch.delitem(sys.modules, "moonglade.setup", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BrokenSetupFinder()] + sys.meta_path)
    run = launch(codes=[0], windows=True)
    assert run.exit == 1 and run.started == []
    assert "somedependency" in run.boxes[0][0]


def test_a_server_already_running_means_nothing_is_moved(launch, monkeypatch):
    """S1: the single-instance check comes before prepare(), so a second double-click never
    moves files under a running server."""
    calls = []
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: calls.append(kind), port=5757))
    run = launch(codes=[0], ours_on_port=True)
    assert calls == [] and run.started == [] and run.exit == 0
    assert run.opened == ["http://localhost:5757/"]


def _ready():
    return types.SimpleNamespace(summary=lambda: "", write_log=lambda: None)


def test_a_server_that_stops_as_it_starts_says_why(launch, monkeypatch):
    """S10: the server's move stopped (a busy lock): it printed its sentence behind the mark
    into serve.log and exited 3. The launcher shows that sentence, not a dead browser."""
    from moonglade import gallery as g
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: _ready()))
    run = launch(codes=[3], windows=True, child_says=(
        "\n" + g.PREPARE_MARK + "Another Moonglade start is still tidying the library. Wait "
        "a minute, then start Moonglade again.\n"))
    assert run.exit == 1
    assert run.boxes[0][0].endswith("Another Moonglade start is still tidying the library. "
                                    "Wait a minute, then start Moonglade again.")


def test_a_crash_as_it_starts_shows_the_end_of_serve_log(launch, monkeypatch):
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: _ready()))
    run = launch(codes=[1], windows=True,
                 child_says="Traceback (most recent call last):\nImportError: no flask\n")
    assert run.exit == 1
    text = run.boxes[0][0]
    assert "stopped as it started (code 1)" in text and "ImportError: no flask" in text


def test_a_clean_stop_says_nothing(launch, monkeypatch):
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: _ready()))
    run = launch(codes=[0], windows=True)
    assert run.boxes == [] and run.exit is None


def test_what_getting_ready_did_goes_in_moonglade_log_one_line_per_file(launch):
    """Rehearsal 5: the real prepare, on an older install's settings: its lines land in
    local/logs/moonglade.log, where the docs send people to look."""
    paths.local_dir().mkdir(parents=True, exist_ok=True)
    paths.local_path("serve.txt").write_text("--port 6124\n", encoding="utf-8")
    launch(codes=[0])
    log = (paths.logs_dir() / "moonglade.log").read_text(encoding="utf-8")
    assert "Removed local/serve.txt: what it held is in local/settings.json now." in log

"""The launcher gets the install ready before it reads a setting (3.20 rebuild, B2).

`Moonglade Launcher.pyw` calls moonglade.setup.prepare("launcher") first: the settings merge
and the move, under their locks, before serve.txt, config.json or the port is read. Claims:
  * prepare runs once, with "launcher", before the first setting is read -- what it puts in
    place is what the launcher then starts the server with;
  * a start that cannot get ready says why, plainly, and stops: no server, no browser. On
    Windows that is a message box (pythonw has no console) and a line in serve.log;
  * a build with no moonglade.setup at all carries on as before -- only the module's own
    absence is forgiven: an import failing INSIDE it stops the start like any other failure.

The .pyw runs on import, so it is run with runpy and every outside effect stood in for, the
same way tests/test_launcher_runs_the_package.py runs it.
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

    def _launch(codes=(0,), windows=False):
        codes = list(codes)
        run = types.SimpleNamespace(started=[], boxes=[], exit=None)

        def popen(cmd, **kw):
            run.started.append(types.SimpleNamespace(cmd=list(cmd), **kw))
            rc = codes.pop(0)
            return types.SimpleNamespace(wait=lambda: rc)

        def urlopen(url, timeout=None):
            raise urllib.error.URLError("refused")

        def box(hwnd, text, title, flags):
            run.boxes.append((text, title))
            return 1

        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(webbrowser, "open", lambda url: None)
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


def _setup(prepare):
    return types.SimpleNamespace(prepare=prepare)


def test_it_gets_ready_once_before_it_reads_a_setting(launch, monkeypatch):
    calls = []

    def prepare(kind):
        calls.append(kind)
        # what the merge puts in place is what the launcher must then read
        paths.local_path("serve.txt").write_text("--port 5959", encoding="utf-8")

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[42, 0])
    assert calls == ["launcher"]                      # once, not again on a relaunch
    assert len(run.started) == 2
    assert run.started[0].cmd == [sys.executable, "-m", "moonglade.gallery", "--port", "5959"]


def test_what_getting_ready_did_goes_in_serve_log(launch, monkeypatch):
    said = types.SimpleNamespace(summary=lambda: "Moved serve.txt into local.")
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: said))
    launch(codes=[0])
    log = paths.local_path("serve.log").read_text(encoding="utf-8")
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
    assert "Try again in a minute." in paths.local_path("serve.log").read_text(encoding="utf-8")


def test_off_windows_it_says_so_on_stderr(launch, monkeypatch, capsys):
    def prepare(kind):
        raise RuntimeError("The library's folder is busy.")

    stub_code_module(monkeypatch, "setup", _setup(prepare))
    run = launch(codes=[0], windows=False)
    assert run.exit == 1 and run.started == []
    if sys.platform != "win32":
        assert run.boxes == []
    assert "The library's folder is busy." in capsys.readouterr().err


def test_a_build_without_moonglade_setup_carries_on(launch, monkeypatch):
    """Until the data layer's setup module is part of the build, the launcher starts as it did."""
    import moonglade
    monkeypatch.delattr(moonglade, "setup", raising=False)
    monkeypatch.setitem(sys.modules, "moonglade.setup", None)    # "no such module"
    run = launch(codes=[0])
    assert run.exit is None or run.exit == 0
    assert len(run.started) == 1


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

"""The launcher runs the package (3.20, "the move").

`Moonglade Launcher.pyw` starts the web server as `python -m moonglade.gallery` from the app's
folder, with no arguments: the server reads the library, host, port and launch switches from
local/settings.json itself. An exit code of 42 relaunches the same command, anything else ends
it, a server already answering on the port means it only opens the browser and bows out, and
the port it probes and opens is settings.json's (the Control Panel's Bonjour chip writes it).
Nothing reads serve.txt or config.json's PORT any more: the move folds both into settings.json
before the launcher reads a setting (moonglade.setup.prepare).

The .pyw is a script that runs on import, so it is run here with runpy and every outside
effect stood in for: subprocess.Popen records the child it would start and hands back the
exit codes the test chose, the single-instance probe and the browser are stubbed, time.sleep
returns at once and the browser-opening thread never starts. conftest pins local_dir() and
config_path() to this test's own folder, so settings.json, serve.log and config.json are the
test's, never the checkout's.
"""
import json
import os
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
from tests.conftest import REPO_ROOT

LAUNCHER = REPO_ROOT / "Moonglade Launcher.pyw"


class _NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


@pytest.fixture
def launch(monkeypatch, tmp_path):
    import ctypes

    def _launch(codes=(0,), settings=None, config=None, ours_on_port=False):
        if settings is not None:
            paths.settings_path().write_text(json.dumps(settings), encoding="utf-8")
        if config is not None:
            paths.config_path().write_text(json.dumps(config), encoding="utf-8")
        codes = list(codes)
        run = types.SimpleNamespace(started=[], probed=[], opened=[], boxes=[], exit=None)

        def popen(cmd, **kw):
            run.started.append(types.SimpleNamespace(cmd=list(cmd), **kw))
            rc = codes.pop(0)
            return types.SimpleNamespace(wait=lambda: rc)

        def urlopen(url, timeout=None):
            run.probed.append(url)
            if ours_on_port:            # the gated /api/ping answers 401 with our header
                raise urllib.error.HTTPError(url, 401, "login", {"X-Moonglade": "1"}, None)
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(webbrowser, "open", lambda url: run.opened.append(url))
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(threading, "Thread", _NoThread)
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(
            user32=types.SimpleNamespace(
                MessageBoxW=lambda hwnd, text, title, flags: run.boxes.append(text) or 1)),
            raising=False)
        monkeypatch.chdir(tmp_path)              # it changes directory; this puts it back
        try:
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        except SystemExit as e:
            run.exit = e.code
        return run
    return _launch


def test_it_starts_the_server_as_the_package_from_the_app_folder(launch):
    run = launch(codes=[0], settings={"host": "0.0.0.0", "port": 5757,
                                      "launch_args": ["--skip-thumbs"]})
    assert len(run.started) == 1
    child = run.started[0]
    # no flags: the server reads host, port and launch switches from settings.json itself
    assert child.cmd == [sys.executable, "-m", "moonglade.gallery"]
    assert os.path.samefile(child.cwd, paths.APP_ROOT)
    assert child.env["MOONGLADE_SUPERVISED"] == "1"
    assert child.stdin is subprocess.DEVNULL
    assert getattr(child.stdout, "name", None) == str(paths.logs_dir() / "serve.log")
    assert run.probed == ["http://localhost:5757/api/ping"]


def test_exit_42_relaunches_the_same_command_and_0_ends_it(launch):
    run = launch(codes=[42, 42, 0])
    assert len(run.started) == 3
    assert run.started[0].cmd == run.started[1].cmd == run.started[2].cmd \
        == [sys.executable, "-m", "moonglade.gallery"]


def test_a_crash_ends_the_launcher_without_a_relaunch(launch):
    """A server that falls over as it starts is said (S10), and never relaunched."""
    run = launch(codes=[1])
    assert len(run.started) == 1
    assert run.exit == 1
    if sys.platform == "win32":
        assert "stopped as it started (code 1)" in run.boxes[0]


def test_a_running_server_on_the_port_means_open_the_browser_and_bow_out(launch):
    run = launch(settings={"port": 5858}, ours_on_port=True)
    assert run.started == []
    assert run.opened == ["http://localhost:5858/"]
    assert run.exit == 0


def test_with_no_port_stored_it_probes_the_default(launch):
    run = launch(codes=[0])
    assert run.probed == ["http://localhost:5000/api/ping"]


def test_an_older_installs_serve_txt_and_config_port_reach_it_through_the_move(launch):
    """An update from 3.19 or older: serve.txt and config.json's PORT are folded into
    settings.json by the move the launcher runs first (serve.txt's flag wins, as it did),
    serve.txt is deleted, and the launcher probes and opens the port that won."""
    paths.local_dir().mkdir(parents=True, exist_ok=True)
    paths.local_path("serve.txt").write_text("--port 6123\n", encoding="utf-8")
    run = launch(codes=[0], config={"PORT": 6200})
    assert run.probed == ["http://localhost:6123/api/ping"]
    assert run.started[0].cmd == [sys.executable, "-m", "moonglade.gallery"]
    assert not paths.local_path("serve.txt").exists()
    assert json.loads(paths.settings_path().read_text(encoding="utf-8"))["port"] == 6123
    assert "PORT" not in json.loads(paths.config_path().read_text(encoding="utf-8"))


def test_the_launcher_reads_no_old_setting():
    """No serve.txt, no config.json PORT/HOST, no extra arguments: the settings merge deleted
    them, and settings.json is read through moonglade.settings."""
    src = LAUNCHER.read_text(encoding="utf-8")
    for gone in ("serve.txt", "SERVE_ARGS", "_load_config", '"PORT"', '"HOST"',
                 'local_path("serve.log")'):
        assert gone not in src, gone
    assert '_settings.server()["port"]' in src

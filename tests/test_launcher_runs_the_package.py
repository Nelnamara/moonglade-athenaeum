"""The launcher runs the package (3.20, "the move").

`Moonglade Launcher.pyw` starts the web server as `python -m moonglade.gallery` from the app's
folder. Everything else it does is exactly as before: the serve.txt flags ride along, an exit
code of 42 relaunches the same command, anything else ends it, a server already answering on
the port means it only opens the browser and bows out, and the port comes from config.json
when serve.txt names none.

The .pyw is a script that runs on import, so it is run here with runpy and every outside
effect stood in for: subprocess.Popen records the child it would start and hands back the
exit codes the test chose, the single-instance probe and the browser are stubbed, time.sleep
returns at once and the browser-opening thread never starts. conftest pins local_path() and
config_path() to this test's own folder, so serve.txt, serve.log and config.json are the
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
    def _launch(codes=(0,), serve_txt=None, config=None, ours_on_port=False):
        if serve_txt is not None:
            paths.local_path("serve.txt").write_text(serve_txt, encoding="utf-8")
        if config is not None:
            paths.config_path().write_text(json.dumps(config), encoding="utf-8")
        codes = list(codes)
        run = types.SimpleNamespace(started=[], probed=[], opened=[], exit=None)

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
        monkeypatch.chdir(tmp_path)              # it changes directory; this puts it back
        try:
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        except SystemExit as e:
            run.exit = e.code
        return run
    return _launch


def test_it_starts_the_server_as_the_package_from_the_app_folder(launch):
    run = launch(codes=[0], serve_txt="--host 0.0.0.0 --port 5757\n")
    assert len(run.started) == 1
    child = run.started[0]
    assert child.cmd == [sys.executable, "-m", "moonglade.gallery",
                         "--host", "0.0.0.0", "--port", "5757"]
    assert os.path.samefile(child.cwd, paths.APP_ROOT)
    assert child.env["MOONGLADE_SUPERVISED"] == "1"
    assert child.stdin is subprocess.DEVNULL
    assert getattr(child.stdout, "name", None) == str(paths.local_path("serve.log"))
    assert run.probed == ["http://localhost:5757/api/ping"]


def test_exit_42_relaunches_the_same_command_and_0_ends_it(launch):
    run = launch(codes=[42, 42, 0])
    assert len(run.started) == 3
    assert run.started[0].cmd == run.started[1].cmd == run.started[2].cmd \
        == [sys.executable, "-m", "moonglade.gallery"]


def test_a_crash_ends_the_launcher_without_a_relaunch(launch):
    run = launch(codes=[1])
    assert len(run.started) == 1


def test_a_running_server_on_the_port_means_open_the_browser_and_bow_out(launch):
    run = launch(serve_txt="--port 5858", ours_on_port=True)
    assert run.started == []
    assert run.opened == ["http://localhost:5858/"]
    assert run.exit == 0


def test_with_no_port_in_serve_txt_it_takes_config_jsons(launch):
    """It reads config.json by importing the command-line module in its own process. Were
    that import to fail after the move it would be swallowed, and the launcher would probe
    and open :5000 whatever the config said."""
    run = launch(codes=[0], config={"PORT": 6123})
    assert run.probed == ["http://localhost:6123/api/ping"]
    assert run.started[0].cmd == [sys.executable, "-m", "moonglade.gallery"]

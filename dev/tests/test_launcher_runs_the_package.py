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
import itertools
import json
import os
import re
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

from moonglade import deps, paths
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

    def _launch(codes=(0,), settings=None, config=None, ours_on_port=False, pid=None):
        if settings is not None:
            paths.settings_path().write_text(json.dumps(settings), encoding="utf-8")
        if config is not None:
            paths.config_path().write_text(json.dumps(config), encoding="utf-8")
        codes = list(codes)
        run = types.SimpleNamespace(started=[], probed=[], opened=[], boxes=[], exit=None,
                                    sleeps=[], ns=None)

        def popen(cmd, **kw):
            run.started.append(types.SimpleNamespace(cmd=list(cmd), **kw))
            rc = codes.pop(0)
            if isinstance(rc, BaseException):       # a start that fails (no memory, ...)
                raise rc
            # the stand-in child: only `wait` (and a pid when the test asks), like the real one
            extra = {} if pid is None else {"pid": pid}
            return types.SimpleNamespace(wait=lambda: rc, **extra)

        def urlopen(url, timeout=None):
            run.probed.append(url)
            if ours_on_port:            # the gated /api/ping answers 401 with our header
                raise urllib.error.HTTPError(url, 401, "login", {"X-Moonglade": "1"}, None)
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(webbrowser, "open", lambda url: run.opened.append(url))
        monkeypatch.setattr(time, "sleep", lambda s: run.sleeps.append(s))
        monkeypatch.setattr(threading, "Thread", _NoThread)
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(deps, "missing", lambda path: [])   # see test_first_run_deps.py
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(
            user32=types.SimpleNamespace(
                MessageBoxW=lambda hwnd, text, title, flags: run.boxes.append(text) or 1)),
            raising=False)
        monkeypatch.chdir(tmp_path)              # it changes directory; this puts it back
        try:
            run.ns = runpy.run_path(str(LAUNCHER), run_name="__main__")
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
    assert child.env["PYTHONFAULTHANDLER"] == "1"      # a native crash leaves its stacks in serve.log
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


# --- #95: every server start and exit says so in serve.log -------------------------------------
STAMP = r"^\[launcher\] \d{4}-\d\d-\d\d \d\d:\d\d:\d\d "


def _serve_log_text():
    return (paths.logs_dir() / "serve.log").read_text(encoding="utf-8")


def _timed_lines(text):
    """The launcher's timed lines (what _record writes), one per element; a traceback's own
    lines under the last one are not counted."""
    return [ln for ln in text.splitlines() if re.match(STAMP, ln)]


def _slow_clock(monkeypatch, step=31.0):
    """time.monotonic that moves `step` seconds on every call: a server that ran a while."""
    counter = itertools.count(1)
    monkeypatch.setattr(time, "monotonic", lambda: next(counter) * step)


def test_every_server_start_and_exit_is_recorded(launch):
    run = launch(codes=[42, 0])
    lines = _timed_lines(_serve_log_text())
    assert len(run.started) == 2
    started = [ln for ln in lines if " server pid ? started " in ln]
    assert len(started) == 2
    assert "(start 1, launcher pid %d)" % os.getpid() in started[0]
    assert "(start 2, launcher pid %d)" % os.getpid() in started[1]
    restart = [ln for ln in lines if "ended: exit code 42 (restart)" in ln]
    assert len(restart) == 1 and restart[0].endswith("; starting it again")
    stop = [ln for ln in lines if "ended: exit code 0 (a normal stop)" in ln]
    assert len(stop) == 1 and "starting it again" not in stop[0]
    assert lines[-1].endswith("launcher closing: the server has ended and was not asked to restart")
    assert all(re.match(STAMP, ln) for ln in lines)


def test_a_started_line_names_the_servers_pid_when_it_has_one(launch):
    launch(codes=[0], pid=4321)
    text = _serve_log_text()
    assert "server pid 4321 started" in text and "server pid 4321 ended" in text


def test_a_crash_after_the_first_half_minute_is_recorded_not_silent(launch, monkeypatch):
    """The case that left nothing before: any exit but 42 after BOOT_S ended the launcher and
    threw the exit code away."""
    _slow_clock(monkeypatch)
    run = launch(codes=[1])
    assert run.boxes == [] and run.exit is None          # no box, ended as it always did
    text = _serve_log_text()
    assert "ended: exit code 1 after" in text
    assert "launcher closing" in text


def test_an_nt_status_exit_code_is_shown_in_hex(launch, monkeypatch):
    _slow_clock(monkeypatch)
    launch(codes=[3221225477])
    assert "exit code 3221225477 (0xC0000005)" in _serve_log_text()


def test_the_exit_words_and_the_span_words(launch):
    ns = launch(codes=[0]).ns
    assert ns["_exit_words"](0) == "exit code 0 (a normal stop)"
    assert ns["_exit_words"](42) == "exit code 42 (restart)"
    assert ns["_exit_words"](1) == "exit code 1"
    assert ns["_exit_words"](255) == "exit code 255"
    assert ns["_exit_words"](3221225477) == "exit code 3221225477 (0xC0000005)"
    assert ns["_exit_words"](None) == "no exit code"
    assert [ns["_span"](s) for s in (0, 45, 60, 185, 3600, 11525)] == [
        "0s", "45s", "1m00s", "3m05s", "1h00m00s", "3h12m05s"]


def test_an_error_that_ends_the_launcher_is_logged_and_still_raised(launch):
    """A relaunch that fails (no memory, say) has no console under pythonw: it is written to
    serve.log, then raised as before."""
    with pytest.raises(OSError, match="no memory"):
        launch(codes=[42, OSError("no memory")])
    text = _serve_log_text()
    assert "launcher stopped by an error:" in text
    assert "OSError" in text and "no memory" in text
    assert "launcher closing" not in text


def test_the_child_gets_the_crash_dump_switch(launch):
    run = launch(codes=[0])
    assert run.started[0].env["PYTHONFAULTHANDLER"] == "1"
    assert run.started[0].env["MOONGLADE_SUPERVISED"] == "1"


# --- the supervise loop behaves exactly as before the lines were added -------------------------
def test_exit_42_still_waits_point_six_seconds_each_time_then_zero_ends(launch):
    run = launch(codes=[42, 42, 0])
    assert len(run.started) == 3 and run.exit is None
    assert run.sleeps.count(0.6) == 2
    assert run.boxes == []


def test_a_crash_inside_the_first_half_minute_still_shows_the_box_and_exits_1(launch):
    run = launch(codes=[1])                              # the real clock: well under BOOT_S
    assert run.exit == 1 and len(run.started) == 1
    text = _serve_log_text()
    assert "ended: exit code 1 after" in text            # recorded, as well as said in the box
    assert "launcher closing" not in text                # _stop raised before the closing line
    if sys.platform == "win32":
        assert len(run.boxes) == 1 and "stopped as it started (code 1)" in run.boxes[0]
        assert "[launcher] " not in run.boxes[0]         # the box shows the server's output only


def test_a_start_crash_after_a_restart_is_not_relaunched(launch):
    run = launch(codes=[42, 1])
    assert len(run.started) == 2 and run.exit == 1


def test_a_log_that_cannot_be_written_never_stops_a_restart(launch, monkeypatch):
    """serve.log locked or full: _record falls back to _log_line and swallows whatever fails."""
    import builtins
    real_open = builtins.open

    def refuse_serve_log(file, *a, **k):
        if str(file).endswith("serve.log"):
            raise PermissionError("locked")
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", refuse_serve_log)
    run = launch(codes=[42, 0])
    assert len(run.started) == 2 and run.exit is None

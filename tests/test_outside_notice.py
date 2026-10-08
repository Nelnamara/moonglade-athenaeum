"""The app's side of the outside-references fixer (DECISIONS 2026-10-07, pick 5): one notice,
with a Fix them button, for things outside the app that still name its old files.

  * A real start looks once, off the request path (main() -> _outside_prime()); an app a test
    builds never looks, so it never says anything.
  * The notice rides the /api/jobs poll, and only a tab on THIS machine gets it: the fix
    rewrites this machine's tasks, configs and shortcuts. Its button carries the session's
    CSRF token.
  * POST /api/outside/fix is LOCALHOST tier, checks the explicit token before anything runs,
    runs one fix at a time, looks again afterwards, and answers in the fixer's plain words.
  * The launcher re-points broken shortcuts by itself, off its start's path, on Windows only.

moonglade.outside itself is held in tests/test_outside.py; here it is stood in for, so no
test can reach the real machine (conftest refuses it regardless).
"""
import ast
import inspect
import runpy
import subprocess
import sys
import textwrap
import threading
import time
import types
import urllib.error
import urllib.request
import webbrowser

import pytest

from moonglade import gallery as g
from moonglade import outside
from moonglade import paths
from tests.conftest import REPO_ROOT, login_client, session_csrf, stub_code_module, with_csrf

LAN = {"REMOTE_ADDR": "192.168.1.9"}
_ITEMS = [outside.Item("task", "\\Moonglade sync", "the scheduled task “Moonglade sync”", {}),
          outside.Item("shortcut", "x.lnk", "the shortcut “Moonglade” on your Desktop", {})]


@pytest.fixture
def found(monkeypatch):
    monkeypatch.setitem(g._OUTSIDE, "items", list(_ITEMS))
    return _ITEMS


def test_nothing_is_said_before_the_start_has_looked(monkeypatch):
    monkeypatch.setitem(g._OUTSIDE, "items", None)
    assert g.server_notice(local=True) is None
    monkeypatch.setitem(g._OUTSIDE, "items", [])
    assert g.server_notice(local=True) is None


def test_only_this_machine_hears_about_it(found):
    assert g.server_notice(local=False) is None
    n = g.server_notice(local=True)
    assert n["key"] == g._SERVER_START
    assert n["title"] == "Some things outside Moonglade still use its old file names."
    assert n["msg"] == ("The scheduled task “Moonglade sync” and the shortcut “Moonglade” on "
                        "your Desktop. Fix them points them at the new names.")
    assert n["fix"] == {"label": "Fix them"}


def test_the_jobs_poll_carries_it_with_the_sessions_token(tmp_path, found):
    cli = login_client(tmp_path)
    d = cli.get("/api/jobs").get_json()
    assert d["notice"]["title"].startswith("Some things outside Moonglade")
    assert d["notice"]["fix"] == {"label": "Fix them", "csrf": session_csrf(cli)}
    assert session_csrf(cli)
    lan = cli.get("/api/jobs", environ_overrides=LAN).get_json()
    assert lan["notice"] is None


def test_an_app_a_test_builds_never_looks(tmp_path, monkeypatch):
    monkeypatch.setitem(g._OUTSIDE, "items", None)
    looked = []
    monkeypatch.setattr(outside, "find", lambda *a, **k: looked.append(1) or [])
    cli = login_client(tmp_path)
    assert cli.get("/api/jobs").get_json()["notice"] is None
    assert looked == []


@pytest.fixture
def fixer(monkeypatch, found):
    calls = types.SimpleNamespace(fix=[], find=0)

    def fake_fix(items=None, **kw):
        calls.fix.append(kw)
        return [outside.Result("the scheduled task “Moonglade sync”", True),
                outside.Result("the shortcut “Moonglade” on your Desktop", False,
                               "Windows refused: changing it needs administrator rights")]

    def fake_find(*a, **k):
        calls.find += 1
        return [_ITEMS[1]]

    monkeypatch.setattr(outside, "fix", fake_fix)
    monkeypatch.setattr(outside, "find", fake_find)
    return calls


def test_fix_them_fixes_looks_again_and_says_what_happened(tmp_path, fixer):
    cli = login_client(tmp_path)
    r = cli.post("/api/outside/fix", json=with_csrf(cli))
    assert r.status_code == 200
    d = r.get_json()
    assert d["kind"] == "err" and d["title"] == "Some couldn't be fixed."
    assert d["msg"] == ("Fixed the scheduled task “Moonglade sync”. Couldn't fix the shortcut "
                        "“Moonglade” on your Desktop: Windows refused: changing it needs "
                        "administrator rights.")
    assert [x["fixed"] for x in d["results"]] == [True, False]
    assert len(fixer.fix) == 1 and fixer.fix[0]["provide_icon"] is g._shortcut_icon_bytes
    assert fixer.find == 1 and g._OUTSIDE["items"] == [_ITEMS[1]]


def test_fix_them_needs_the_sessions_token_before_anything_runs(tmp_path, fixer):
    cli = login_client(tmp_path)
    r = cli.post("/api/outside/fix", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "Your session expired. Reload the page and try again."
    r = cli.post("/api/outside/fix", json={"csrf": "not-the-token"})
    assert r.status_code == 400
    assert fixer.fix == [] and fixer.find == 0


def test_fix_them_is_this_machine_only(tmp_path, fixer):
    cli = login_client(tmp_path)
    r = cli.post("/api/outside/fix", json=with_csrf(cli), environ_overrides=LAN)
    assert r.status_code == 403
    assert fixer.fix == []
    view = cli.application.view_functions["api_outside_fix"]
    assert g.route_tier(view, "POST") == g.LOCALHOST


def test_one_fix_at_a_time(tmp_path, fixer):
    cli = login_client(tmp_path)
    assert g._OUTSIDE_FIXING.acquire(blocking=False)
    try:
        r = cli.post("/api/outside/fix", json=with_csrf(cli))
    finally:
        g._OUTSIDE_FIXING.release()
    assert r.status_code == 409 and fixer.fix == []


def test_a_shortcuts_icon_is_only_ever_a_plain_mark_name(monkeypatch):
    asked = []
    monkeypatch.setattr(g, "_branding_bytes", lambda rel: asked.append(rel) or b"ICO")
    assert g._shortcut_icon_bytes("mark_4") == b"ICO"
    for bad in ("..\\..\\secret", "a/b", "", None, "mark 4"):
        assert g._shortcut_icon_bytes(bad) is None
    assert len(asked) == 1


def test_the_look_is_a_real_starts_and_off_the_request_path():
    """main() starts it once the server is bound, on its own thread; create_app() never."""
    src = textwrap.dedent(inspect.getsource(g.main))
    assert "_outside_prime()" in src
    assert src.index("_outside_prime()") > src.index("_make_server(args.host")
    assert "_outside_prime" not in inspect.getsource(g.create_app)
    started = []

    class T:
        def __init__(self, target=None, daemon=None, name=None):
            started.append((target, daemon, name))

        def start(self):
            pass
    import moonglade.gallery as mg
    old = mg.threading.Thread
    mg.threading.Thread = T
    try:
        g._outside_prime()
    finally:
        mg.threading.Thread = old
    assert started == [(g._outside_scan, True, "moonglade-outside-scan")]


def test_a_look_that_fails_finds_nothing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("schtasks went away")
    monkeypatch.setattr(outside, "find", boom)
    monkeypatch.setitem(g._OUTSIDE, "items", None)
    assert g._outside_scan() == [] and g._OUTSIDE["items"] == []


# ---- the launcher's own pass ------------------------------------------------------------------

class _Thread:
    started = []

    def __init__(self, target=None, daemon=None, name=None, **k):
        self.target, self.name = target, name

    def start(self):
        _Thread.started.append(self)


def _launch(monkeypatch, platform):
    import ctypes
    _Thread.started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: types.SimpleNamespace(
        wait=lambda: 0))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError("refused")))
    monkeypatch.setattr(webbrowser, "open", lambda url: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(threading, "Thread", _Thread)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(
        user32=types.SimpleNamespace(MessageBoxW=lambda *a: 1)), raising=False)
    ready = types.SimpleNamespace(summary=lambda: "")
    stub_code_module(monkeypatch, "setup", types.SimpleNamespace(prepare=lambda kind: ready))
    monkeypatch.chdir(paths.local_dir())
    try:
        runpy.run_path(str(REPO_ROOT / "Moonglade Launcher.pyw"), run_name="__main__")
    except SystemExit:
        pass
    return {t.name: t for t in _Thread.started}


def test_the_launcher_re_points_shortcuts_on_windows_and_says_so(monkeypatch):
    threads = _launch(monkeypatch, "win32")
    t = threads["moonglade-shortcuts"]
    ran = []
    monkeypatch.setattr(outside, "repoint_shortcuts", lambda: ran.append(1) or [
        outside.Result("the shortcut “Moonglade Athenaeum” on your Desktop", True)])
    t.target()
    assert ran == [1]
    log = (paths.logs_dir() / "serve.log").read_text(encoding="utf-8")
    assert "[launcher] Fixed the shortcut “Moonglade Athenaeum” on your Desktop." in log


def test_the_launchers_pass_never_stops_a_start(monkeypatch):
    threads = _launch(monkeypatch, "win32")

    def boom():
        raise RuntimeError("no shell")
    monkeypatch.setattr(outside, "repoint_shortcuts", boom)
    threads["moonglade-shortcuts"].target()                # says nothing, raises nothing


def test_off_windows_the_launcher_has_no_shortcuts_to_look_at(monkeypatch):
    assert "moonglade-shortcuts" not in _launch(monkeypatch, "linux")


def test_the_launchers_pass_is_after_getting_ready_and_before_the_server_loop():
    src = (REPO_ROOT / "Moonglade Launcher.pyw").read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = [n for n in tree.body if not isinstance(n, ast.FunctionDef)]

    def first(pred):
        return next(i for i, n in enumerate(body) if any(pred(x) for x in ast.walk(n)))
    ready = first(lambda x: isinstance(x, ast.Call) and getattr(x.func, "attr", "") == "prepare")
    shortcuts = first(lambda x: isinstance(x, ast.Constant) and x.value == "moonglade-shortcuts")
    loop = next(i for i, n in enumerate(body) if isinstance(n, ast.While))
    assert ready < shortcuts < loop

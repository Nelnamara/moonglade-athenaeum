"""config.json's account lock holds across PROCESSES, not only threads (security review intake,
2026-11-21). A command-line --add-web-user runs in its own process; before this, it could lose
an update against a running server's write, because `_accounts_lock` was a threading.Lock.

The test starts real second Python processes from a small script written under its tmp_path.
The script points moonglade.paths.config_path() at the test's own config.json BEFORE it imports
the engine, so no child ever reads or writes the checkout's real file; the lock's sidecar lands
beside that tmp config.json. Both children start at once, so the engine import (the slow part)
is paid once.
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from moonglade import backup as core
from moonglade import web_accounts
from tests.conftest import REPO_ROOT, TEST_PASSWORD_HASH_METHOD

_CHILD = r'''
import sys, time
from pathlib import Path

cfg_path, role, work, hash_method = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
from moonglade import paths
paths.config_path = lambda: cfg_path            # never the checkout's real config.json
from moonglade import backup, web_accounts
web_accounts.WEB_PASSWORD_HASH_METHOD = hash_method     # the suite's token cost


def wait_for(p, limit=20.0):
    end = time.monotonic() + limit
    while not p.exists():
        if time.monotonic() > end:
            sys.exit("timed out waiting for " + p.name)
        time.sleep(0.01)


if role == "hold":
    with backup._accounts_lock:
        (work / "held").write_text("1")
        wait_for(work / "go")
        (work / "released").write_text("1")     # written while still holding the lock
elif role.startswith("add:"):
    name = role[4:]
    real_save = backup._save_config

    def slow_save(cfg):                         # widen the read->write window on purpose
        time.sleep(0.3)
        real_save(cfg)
    backup._save_config = slow_save
    (work / ("ready-" + name)).write_text("1")
    wait_for(work / "start")
    web_accounts.add_or_update_web_user(name, "a-test-password-" + name)
'''


def _start(tmp_path, role):
    script = tmp_path / "lock_child.py"
    if not script.exists():
        script.write_text(_CHILD, encoding="utf-8")
    env = dict(os.environ)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + old if old else "")
    return subprocess.Popen(
        [sys.executable, "-B", str(script), str(core._config_path()), role, str(tmp_path),
         TEST_PASSWORD_HASH_METHOD],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _wait_for(path, proc, limit=20.0):
    end = time.monotonic() + limit
    while not path.exists():
        if proc.poll() is not None:
            out, err = proc.communicate()
            pytest.fail("the child exited before %s: %s %s" % (path.name, out, err))
        assert time.monotonic() < end, "timed out waiting for " + path.name
        time.sleep(0.01)


def _finish(proc):
    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0, out + err


def test_the_sidecar_sits_beside_config_json():
    assert core._accounts_lock_path() == core._config_path().with_name("config.json.lock")


def test_the_lock_holds_across_processes(tmp_path, monkeypatch):
    """1. Another process holds the lock: a short wait here times out with an error naming the
    lock file, and leaves nothing held. 2. With the full wait, this process reads config.json
    only after the holder has let go. 3. This process and a third one each add a different
    user, each taking 0.3 s between reading config.json and writing it back: without a lock
    that holds across processes, the later write puts back a file missing the other account."""
    core._save_config({"AUTH_USERS": []})
    holder, adder = _start(tmp_path, "hold"), _start(tmp_path, "add:alice")
    try:
        _wait_for(tmp_path / "held", holder)
        _wait_for(tmp_path / "ready-alice", adder)

        monkeypatch.setattr(core, "ACCOUNTS_LOCK_WAIT_S", 0.2)
        with pytest.raises(core.AccountsLockTimeout) as info:
            with core._accounts_lock:
                pass
        assert str(core._accounts_lock_path()) in str(info.value)
        assert isinstance(info.value, OSError)
        assert not core._accounts_lock.locked()
        monkeypatch.setattr(core, "ACCOUNTS_LOCK_WAIT_S", 10.0)

        reads, real_load, real_save = [], core._load_config, core._save_config

        def load_and_note():
            reads.append((tmp_path / "released").exists())
            return real_load()

        def slow_save(cfg):
            time.sleep(0.3)
            real_save(cfg)
        monkeypatch.setattr(core, "_load_config", load_and_note)
        monkeypatch.setattr(core, "_save_config", slow_save)
        (tmp_path / "start").write_text("1")          # alice queues behind the holder too
        threading.Timer(0.3, (tmp_path / "go").write_text, args=("1",)).start()
        t0 = time.monotonic()
        web_accounts.add_or_update_web_user("bob", "a-test-password-bob")
        assert time.monotonic() - t0 >= 0.25
        assert reads == [True], "read config.json while another process held the lock"
    finally:
        for name in ("go", "start"):
            (tmp_path / name).write_text("1")
        _finish(holder)
        _finish(adder)
    assert not core._accounts_lock.locked()
    users = json.loads(core._config_path().read_text(encoding="utf-8"))["AUTH_USERS"]
    assert sorted(u["username"] for u in users) == ["alice", "bob"]


# ---------------------------------------------------------------------------
# When the lock cannot be had: the server still starts, the sign-in page still answers, a
# writing route says so in JSON, and the command line stops with a sentence. A busy lock is
# simulated in-process (the OS lock never comes free, a short wait), so these stay fast.
# ---------------------------------------------------------------------------

def _lock_never_free(monkeypatch):
    monkeypatch.setattr(core, "ACCOUNTS_LOCK_WAIT_S", 0.05)
    monkeypatch.setattr(core, "_lock_fd", lambda fd: False)


def _sidecar_unopenable(monkeypatch):
    def _refuse():
        raise PermissionError("the lock file is there but cannot be opened")
    monkeypatch.setattr(core._AccountsLock, "_take_file_lock", staticmethod(_refuse))


@pytest.mark.parametrize("trouble", [_lock_never_free, _sidecar_unopenable])
def test_a_lock_it_cannot_take_never_stops_the_server_starting(tmp_path, monkeypatch, capsys,
                                                                trouble):
    from moonglade.gallery import create_app
    trouble(monkeypatch)
    app = create_app(tmp_path)                    # raised out of create_app before the fix
    assert app.secret_key
    saved = json.loads(core._config_path().read_text(encoding="utf-8"))
    assert saved["AUTH_SECRET_KEY"] == app.secret_key      # the unlocked read-or-create ran
    assert "could not take config.json's account lock" in capsys.readouterr().out
    assert not core._accounts_lock.locked()


def test_a_writing_route_answers_503_json_when_the_lock_times_out(tmp_path, monkeypatch):
    from tests.conftest import login_client
    cli = login_client(tmp_path)
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    _lock_never_free(monkeypatch)
    r = cli.post("/api/users/add", json={"username": "newperson", "password": "hunter2222",
                                         "confirm": "hunter2222", "csrf": csrf})
    assert r.status_code == 503 and r.is_json
    err = r.get_json()["error"]
    assert "try again" in err
    assert str(tmp_path) not in err and ".lock" not in err          # names no path
    assert not core._accounts_lock.locked()
    assert "newperson" not in {u["username"] for u in web_accounts.list_web_users()}


def test_the_sign_in_page_answers_while_another_thread_holds_the_lock(tmp_path):
    """GET /login and the POST /api/login sign-in read the account list without the lock, so
    a holder (here a thread that keeps it for seconds) never stalls the public front door."""
    from moonglade.gallery import create_app
    from tests.conftest import _do_login
    app = create_app(tmp_path)
    web_accounts.add_or_update_web_user("tester", "a-real-test-password-1")
    held, done = threading.Event(), threading.Event()

    def hold():
        with core._accounts_lock:
            held.set()
            done.wait(10)
    t = threading.Thread(target=hold, daemon=True)
    t.start()
    try:
        assert held.wait(5)
        _do_login(app.test_client(), "tester", "a-real-test-password-1")
        # Answered while the holder still has it, not after it let go.
        assert core._accounts_lock.locked() and t.is_alive()
    finally:
        done.set()
        t.join(10)
    assert not core._accounts_lock.locked()


def test_the_command_line_stops_with_the_plain_sentence(tmp_path, monkeypatch):
    import argparse
    web_accounts.add_or_update_web_user("carol", "a-test-password-carol")
    _lock_never_free(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt="": "dave")
    monkeypatch.setattr(web_accounts.getpass, "getpass", lambda prompt="": "a-test-password-dave")
    with pytest.raises(SystemExit) as info:
        web_accounts.run_add_web_user(argparse.Namespace())
    assert isinstance(info.value.code, str) and "Another Moonglade process" in info.value.code
    with pytest.raises(SystemExit) as info:
        web_accounts.run_remove_web_user(argparse.Namespace(remove_web_user="carol", out=None))
    assert isinstance(info.value.code, str) and "Another Moonglade process" in info.value.code
    assert not core._accounts_lock.locked()
    assert [u["username"] for u in web_accounts.list_web_users()] == ["carol"]

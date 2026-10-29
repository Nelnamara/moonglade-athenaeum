"""#95: when the gallery stops, serve.log and moonglade.log say what ended it and who asked.

The launcher's half (a line per start and per exit) is pinned in
test_launcher_runs_the_package.py. This file is the server's half: the sentence for each way it
can end (server_exit_reason), the first-wins record of who pressed Stop or Restart
(_note_server_exit, _note_power_request on the two routes), the line main()'s `finally` writes,
and the off-Windows signal note. Stdlib only; no sealed content.

Not here, on purpose: the real signal.signal and faulthandler.enable. pytest owns faulthandler
for the whole session, and a real handler would outlive the test.
"""
import inspect
import logging
import signal
import sys

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _client(tmp_path, user="tester"):
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "1", "filename": "a_1.png",
                                           "created_at": "2025-01-01T00:00:00"}])
    return login_test_client(create_app(tmp_path), username=user)


@pytest.fixture
def fresh_exit_record(monkeypatch):
    """No reason recorded and no exit scheduled, as at the start of a process."""
    monkeypatch.delitem(g._SERVER_CONTROL, "exit_why", raising=False)
    monkeypatch.setitem(g._SERVER_CONTROL, "exit_scheduled", False)


def test_server_exit_reason_words():
    why = 'from ::1 (this PC), user "tester", browser "x"'
    stop = g.server_exit_reason(True, 0, why, False)
    assert stop == "Stop requested " + why
    assert g.server_exit_reason(True, 42, why, False).startswith("Restart requested from ::1")
    assert g.server_exit_reason(True, 42, "by the update just applied", False) == \
        "Restart requested by the update just applied"
    assert g.server_exit_reason(True, 0, "", False) == "Stop requested (no details recorded)"
    assert g.server_exit_reason(False, 0, "", True) == "Ctrl+C in a terminal"
    err = g.server_exit_reason(False, 0, "", False)
    assert "unhandled error" in err and "CRITICAL" in err
    # the serve loop returned with nobody asking: not called an error
    assert "ended on its own" in g.server_exit_reason(False, 0, "", False, errored=False)
    # a Stop that was asked wins over everything else
    assert g.server_exit_reason(True, 0, why, True).startswith("Stop requested")


def test_span_words():
    assert [g._span_words(s) for s in (0, 45, 60, 185, 3600, 11525)] == [
        "0s", "45s", "1m00s", "3m05s", "1h00m00s", "3h12m05s"]
    assert g._span_words(-5) == "0s" and g._span_words(None) == "0s"


def test_clean_for_log_cannot_forge_a_line():
    assert g._clean_for_log("a\r\n[server] 2026 stopping: fake") == "a??[server] 2026 stopping: fake"
    assert g._clean_for_log("café ☃") == "caf? ?"
    assert len(g._clean_for_log("x" * 10000)) == 100
    assert len(g._clean_for_log("x" * 10000, 40)) == 40
    assert g._clean_for_log(None) == ""
    # a quote cannot close the value it sits in
    assert g._clean_for_log('x", browser "y') == "x', browser 'y"
    assert "\n" not in g._clean_for_log("one\ntwo\x00three\x1b[0m")


def test_note_server_exit_first_wins(fresh_exit_record, caplog):
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        g._note_server_exit("first reason")
        g._note_server_exit("second reason")
    assert g._SERVER_CONTROL["exit_why"] == "first reason"
    asked = [r.getMessage() for r in caplog.records if "server exit requested" in r.getMessage()]
    assert asked == ["server exit requested: first reason"]


def _requests_logged(caplog):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("server exit requested")]


def test_stop_and_restart_routes_log_who_asked(tmp_path, monkeypatch, caplog, fresh_exit_record):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    monkeypatch.setattr(g, "_supervised", lambda: True)
    cli = _client(tmp_path)
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    cookies = [c.value for c in cli._cookies.values()] if hasattr(cli, "_cookies") else []
    agent = "Bad\nAgent " + "x" * 300            # newline: only an environ can carry one
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        d = cli.post("/api/server/stop", environ_overrides={
            "REMOTE_ADDR": "192.168.1.9", "HTTP_USER_AGENT": agent}).get_json()
    assert d == {"ok": True, "action": "stop"} and codes == [0]
    said = _requests_logged(caplog)
    assert len(said) == 1
    line = said[0]
    assert "192.168.1.9" in line and "another device" in line
    assert 'user "tester"' in line
    assert "\n" not in line and "\r" not in line
    browser = line.split('browser "', 1)[1].rsplit('"', 1)[0]
    assert browser.startswith("Bad?Agent x") and len(browser) == 100
    # nothing a session holds is in the line
    assert csrf and csrf not in caplog.text
    assert cookies and all(c not in caplog.text for c in cookies)

    # a Restart from this PC, after the first reason is cleared (a fresh process in real life)
    g._SERVER_CONTROL.pop("exit_why", None)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        cli.post("/api/server/restart", environ_overrides={"HTTP_USER_AGENT": "Mozilla/5.0"})
    assert codes == [0, 42]
    line = _requests_logged(caplog)[0]
    assert "from 127.0.0.1 (this PC)" in line and 'browser "Mozilla/5.0"' in line


def test_a_user_name_with_a_fake_marker_stays_inside_its_quotes(tmp_path, monkeypatch, caplog,
                                                                 fresh_exit_record):
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: None)
    cli = _client(tmp_path, user='[server]\r\n2026-01-01 00:00:00 stopping: fake')
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        cli.post("/api/server/stop")
    line = _requests_logged(caplog)[0]
    assert "\n" not in line and "\r" not in line
    assert 'user "[server]??2026-01-01 00:00:00 stopping: fake"' in line


def test_a_refused_click_is_not_a_stop(tmp_path, monkeypatch, caplog, fresh_exit_record):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    monkeypatch.setattr(g, "_supervised", lambda: True)
    cli = _client(tmp_path)
    monkeypatch.setattr(g, "_update_state", {"phase": "deps", "error": "", "at": 0.0})
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        assert cli.post("/api/server/stop").status_code == 409        # an update is running
        assert cli.post("/api/server/restart").status_code == 409
        monkeypatch.setattr(g, "_supervised", lambda: False)
        monkeypatch.setattr(g, "_update_state", {"phase": "idle", "error": "", "at": 0.0})
        assert cli.post("/api/server/restart").status_code == 409     # not supervised
    assert codes == [] and _requests_logged(caplog) == []
    assert "exit_why" not in g._SERVER_CONTROL


def test_the_update_restart_records_its_own_reason():
    """The updater's closure runs on a thread with no request: it names the update, after the
    one call test_updater.py pins to the front of that closure."""
    src = inspect.getsource(g.create_app)
    body = src[src.index("def _restart():"):]
    assert body.index("_schedule_server_exit(42)") < body.index(
        '_note_server_exit("by the update just applied")') < 1200
    assert "_note_power_request" not in body[:1200]


def test_main_stop_path_calls_the_reason_builder_first():
    """main() is too heavy to run: its `finally` is read. The reason line is the first thing in
    it, ahead of every cleanup, and wrapped so a failure cannot skip them."""
    src = inspect.getsource(g.main)
    finally_at = src.index("    finally:\n        # First, and wrapped")
    reason_at = src.index("server_exit_reason(", finally_at)
    assert reason_at < src.index("_count_timer.cancel()", finally_at)
    block = src[finally_at:src.index("_count_timer.cancel()", finally_at)]
    assert "try:" in block and "except Exception" in block
    assert "interrupted = True" in src[:finally_at]
    assert src.index("_install_signal_note()") < src.index("prepared.log()")


def test_main_writes_the_line_to_both_files():
    block = inspect.getsource(g.main)
    block = block[block.index("server_exit_reason("):block.index("_count_timer.cancel()")]
    assert '"server stopping: %s (pid %d, up %s, exit code %d)"' in block
    assert 'print("[server] %s stopping: %s (pid %d, up %s, exit code %d)"' in block
    assert "flush=True" in block


# --- the signal note (off Windows only) ---------------------------------------------------------
def test_signal_note_logs_then_restores_default(monkeypatch, caplog):
    """Registered through a recorder, so no real handler is installed in the test process."""
    registered = {}
    sent = []

    def fake_signal(signum, handler):
        registered[signum] = handler

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(signal, "getsignal", lambda s: signal.SIG_DFL)
    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr(g.os, "kill", lambda pid, signum: sent.append((pid, signum)))
    g._install_signal_note()
    assert signal.SIGTERM in registered
    handler = registered[signal.SIGTERM]
    with caplog.at_level(logging.INFO, logger="moonglade.gallery"):
        handler(signal.SIGTERM, None)
    assert any(r.getMessage() == "server received SIGTERM" for r in caplog.records)
    assert registered[signal.SIGTERM] == signal.SIG_DFL          # the default is back ...
    assert sent == [(g.os.getpid(), signal.SIGTERM)]              # ... and the signal re-sent once


def test_signal_note_must_not_replace_an_ignored_signal(monkeypatch):
    """nohup, or a parent that set SIG_IGN: a handler that ends with the default action would
    turn 'ignored' into 'dies'."""
    registered = {}
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(signal, "getsignal", lambda s: signal.SIG_IGN)
    monkeypatch.setattr(signal, "signal", lambda s, h: registered.__setitem__(s, h))
    g._install_signal_note()
    assert registered == {}


def test_a_raise_in_the_note_never_blocks_a_stop(tmp_path, monkeypatch, fresh_exit_record):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))

    def boom(why):
        raise RuntimeError("log broke")

    monkeypatch.setattr(g, "_note_server_exit", boom)
    r = _client(tmp_path).post("/api/server/stop")
    assert r.status_code == 200 and codes == [0]


def test_signal_note_installs_nothing_on_windows(monkeypatch):
    """A pythonw process is never delivered a signal, so there is nothing to note."""
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(signal, "signal", lambda *a: calls.append(a))
    g._install_signal_note()
    assert calls == []


def test_signal_note_off_the_main_thread_is_quiet(monkeypatch):
    def refuses(signum, handler):
        raise ValueError("signal only works in main thread of the main interpreter")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(signal, "signal", refuses)
    g._install_signal_note()                                      # must not raise

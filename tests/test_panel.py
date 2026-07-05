"""Control Panel: maintenance-job runner. Whitelist-only actions, destructive ones
gated behind confirm, one at a time. The subprocess spawn is monkeypatched so no CLI
actually runs."""
import pixai_gallery as g
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def test_panel_page_renders_with_actions(tmp_path):
    html = _client(tmp_path).test_client().get("/panel").get_data(as_text=True)
    assert "Control Panel" in html
    assert '"action": "update"' in html or '"action":"update"' in html   # actions_json
    assert "Incremental backup" in html


def test_run_rejects_unknown_action(tmp_path):
    cli = _client(tmp_path).test_client()
    assert cli.post("/api/panel/run", json={"action": "rm -rf"}).status_code == 400


def test_run_destructive_needs_confirm(tmp_path, monkeypatch):
    import subprocess
    spawned = {"n": 0}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: spawned.update(n=spawned["n"] + 1))
    cli = _client(tmp_path).test_client()      # create_app's build-stamp may spawn git
    base = spawned["n"]
    r = cli.post("/api/panel/run", json={"action": "dedup-apply"})   # no confirm
    assert r.status_code == 400 and "confirm" in r.get_json()["error"]
    assert spawned["n"] == base                # the panel run itself spawned nothing


def test_run_safe_action_spawns_and_status(tmp_path, monkeypatch):
    import subprocess

    class FakeProc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("line one\nline two\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    app = _client(tmp_path)
    cli = app.test_client()
    r = cli.post("/api/panel/run", json={"action": "update"})
    assert r.get_json()["ok"] is True
    # reader thread is a daemon; poll status until it finishes
    import time
    for _ in range(50):
        d = cli.get("/api/panel/status").get_json()
        if d["status"] != "running":
            break
        time.sleep(0.02)
    assert d["status"] == "done" and d["rc"] == 0
    assert "line two" in d["lines"]


def test_schedule_roundtrip_and_safe_only(tmp_path):
    cli = _client(tmp_path).test_client()
    # default: disabled
    assert cli.get("/api/panel/schedule").get_json()["enabled"] is False
    # save a valid safe schedule
    s = cli.post("/api/panel/schedule",
                 json={"enabled": True, "action": "update", "interval_hours": 12}).get_json()
    assert s["enabled"] is True and s["action"] == "update" and s["interval_hours"] == 12
    assert (tmp_path / "schedule.json").exists()
    assert cli.get("/api/panel/schedule").get_json()["interval_hours"] == 12
    # destructive actions cannot be scheduled
    r = cli.post("/api/panel/schedule", json={"enabled": True, "action": "dedup-apply"})
    assert r.status_code == 400
    # interval is clamped to [1, 168]
    assert cli.post("/api/panel/schedule",
                    json={"action": "stats", "interval_hours": 9999}).get_json()["interval_hours"] == 168


def test_run_argv_is_whitelisted_flags_only(tmp_path, monkeypatch):
    """The spawned argv must be python + the CLI + --out + our fixed flags -- never a
    shell string, never user input."""
    import subprocess
    captured = {}

    class FakeProc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("")
        def wait(self):
            return 0
    def fake_popen(argv, **k):
        captured["argv"] = argv
        return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    cli = _client(tmp_path).test_client()
    cli.post("/api/panel/run", json={"action": "audit"})
    import time
    time.sleep(0.05)
    argv = captured["argv"]
    assert argv[1].endswith("pixai_gallery_backup.py")
    assert "--audit" in argv and "--no-content" in argv and "--out" in argv
    assert all(isinstance(a, str) for a in argv)


# --- Server control: stop / restart from the browser (Homebridge-style) ---

def test_ping_is_open(tmp_path):
    cli = _client(tmp_path).test_client()
    assert cli.get("/api/ping").get_json() == {"ok": True}


def test_server_stop_schedules_exit_0(tmp_path, monkeypatch):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _client(tmp_path).test_client()
    d = cli.post("/api/server/stop").get_json()
    assert d == {"ok": True, "action": "stop"} and codes == [0]      # stop -> exit 0
    # LAN device can't stop the owner's server
    r = cli.post("/api/server/stop", environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403 and codes == [0]                     # unchanged


def test_server_restart_needs_supervisor(tmp_path, monkeypatch):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _client(tmp_path).test_client()
    # not supervised -> refused (409), no exit scheduled
    monkeypatch.setattr(g, "_supervised", lambda: False)
    r = cli.post("/api/server/restart")
    assert r.status_code == 409 and codes == []
    # supervised -> exit 42 (the relaunch signal)
    monkeypatch.setattr(g, "_supervised", lambda: True)
    d = cli.post("/api/server/restart").get_json()
    assert d["action"] == "restart" and codes == [42]


def test_panel_shows_restart_state(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_supervised", lambda: True)
    html = _client(tmp_path).test_client().get("/panel").get_data(as_text=True)
    assert "Restart server" in html and "Stop server" in html

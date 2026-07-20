"""Control Panel: maintenance-job runner. Whitelist-only actions, destructive ones
gated behind confirm, one at a time. The subprocess spawn is monkeypatched so no CLI
actually runs."""
import re
import pixai_gallery as g
import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client, login_existing_client


def _csrf(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    return m.group(1)


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def _authed_client(tmp_path):
    """Like _client(tmp_path).test_client(), but logged in for real -- for every test
    below EXCEPT test_destructive_action_refuses_authenticated_lan_session (which does
    its own explicit login inline) and test_cancel_is_localhost_only (which deliberately
    stays anonymous to prove the gate itself)."""
    return login_test_client(_client(tmp_path))


def test_panel_page_renders_with_actions(tmp_path):
    html = _authed_client(tmp_path).get("/panel").get_data(as_text=True)
    assert "Control Panel" in html
    assert "Sync now" in html
    # ACTIONS drives the Maintenance BUTTONS (panel_visible only); ALL_ACTIONS drives the
    # scheduler dropdown and must still include the background-only jobs.
    buttons_json = html.split("var ACTIONS = ", 1)[1].split(";", 1)[0]
    dropdown_json = html.split("var ALL_ACTIONS = ", 1)[1].split(";", 1)[0]
    assert '"action": "sync"' in buttons_json
    # update/backfill-meta/fix-models folded into --sync -- no longer standalone actions
    for gone in ("update", "backfill-meta", "fix-models"):
        assert gone not in buttons_json and gone not in dropdown_json
    # sync-videos / sync-artworks GAINED buttons in the web-parity pass: nothing should
    # need the CLI. They are full-history re-walks, so their labels say so out loud
    # rather than hiding them.
    for shown in ("sync-videos", "sync-artworks"):
        assert '"action": "{}"'.format(shown) in buttons_json
        assert "full re-walk" in buttons_json
    # reconcile-deleted deliberately stays button-less -- NOT an oversight. --sync already
    # runs it as its final step (run_sync's pipeline), so a button would be a second path
    # to work that just happened, inviting someone to run it and wonder why nothing
    # changed. It stays schedulable for anyone wanting it on its own cadence.
    assert "reconcile-deleted" not in buttons_json
    assert '"action": "reconcile-deleted"' in dropdown_json


def test_run_rejects_unknown_action(tmp_path):
    cli = _authed_client(tmp_path)
    assert cli.post("/api/panel/run", json={"action": "rm -rf"}).status_code == 400


def test_run_destructive_needs_confirm(tmp_path, monkeypatch):
    import subprocess
    spawned = {"n": 0}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: spawned.update(n=spawned["n"] + 1))
    cli = _authed_client(tmp_path)      # create_app's build-stamp may spawn git
    base = spawned["n"]
    r = cli.post("/api/panel/run", json={"action": "dedup-apply"})   # no confirm
    assert r.status_code == 400 and "confirm" in r.get_json()["error"]
    assert spawned["n"] == base                # the panel run itself spawned nothing


def test_destructive_action_refuses_authenticated_lan_session(tmp_path, monkeypatch):
    """A logged-in LAN account must NOT be able to trigger a destructive maintenance
    job (organize / dedup --apply / rebuild-thumbnails) -- unlike safe read-only panel
    actions, these change local files on the SERVER's own machine, same trust tier as
    /api/branding/shortcut. A LAN login unlocks spend-the-owner's-credits generation
    features, not host-filesystem mutation."""
    import subprocess, io
    spawned = {"n": 0}

    class FakeProc:
        """A real Popen-alike: the final call in this test succeeds (localhost),
        so _panel_run really does spawn the reader thread on whatever Popen
        returns -- it needs .stdout (iterable) and .wait(), unlike a plain
        counter callback that returns None and crashes that thread."""
        def __init__(self):
            self.stdout = io.StringIO("")
        def wait(self):
            return 0

    def fake_popen(*a, **k):
        spawned["n"] += 1
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    LAN = "203.0.113.5"
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    # Prove the session really is authenticated (it can reach an ordinary
    # authorized-LAN route) before proving it still can't reach this one.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    base = spawned["n"]
    r = cli.post("/api/panel/run", json={"action": "dedup-apply", "confirm": True},
                 environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403 and "localhost-only" in r.get_json()["error"]
    assert spawned["n"] == base   # nothing was spawned

    # The same account, from the actual local machine, still works (destructive
    # actions aren't broken for the owner -- just not exposed to remote sessions).
    r2 = cli.post("/api/panel/run", json={"action": "dedup-apply", "confirm": True})
    assert r2.status_code == 200
    assert spawned["n"] == base + 1


def test_run_safe_action_spawns_and_status(tmp_path, monkeypatch):
    import subprocess

    class FakeProc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("line one\nline two\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    cli = _authed_client(tmp_path)
    r = cli.post("/api/panel/run", json={"action": "sync"})
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
    cli = _authed_client(tmp_path)
    # default: disabled
    assert cli.get("/api/panel/schedule").get_json()["enabled"] is False
    # save a valid safe schedule -- sync-videos has NO panel button anymore (it's
    # panel_visible=False, a full-feed scan meant for the scheduler), but must still be
    # schedulable: that's its only home now that the button is gone.
    s = cli.post("/api/panel/schedule",
                 json={"enabled": True, "action": "sync-videos", "interval_hours": 12}).get_json()
    assert s["enabled"] is True and s["action"] == "sync-videos" and s["interval_hours"] == 12
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

    cli = _authed_client(tmp_path)
    cli.post("/api/panel/run", json={"action": "audit"})
    import time
    time.sleep(0.05)
    argv = captured["argv"]
    assert argv[1].endswith("pixai_gallery_backup.py")
    assert "--audit" in argv and "--no-content" in argv and "--out" in argv
    assert all(isinstance(a, str) for a in argv)


def test_workers_setting_persists_merges_and_reaches_argv(tmp_path, monkeypatch):
    """The Download-workers selector persists to schedule.json so BOTH manual runs and
    the scheduled run use it, is injected as --workers N into the spawned argv, and its
    partial POST merges (doesn't wipe the schedule fields the other control wrote)."""
    import subprocess
    cli = _authed_client(tmp_path)

    # seed a schedule, then a workers-ONLY post must not wipe it (merge, not replace)
    cli.post("/api/panel/schedule", json={"enabled": True, "action": "sync", "interval_hours": 12})
    cli.post("/api/panel/schedule", json={"workers": 8})
    s = cli.get("/api/panel/schedule").get_json()
    assert s["workers"] == 8 and s["enabled"] is True
    assert s["action"] == "sync" and s["interval_hours"] == 12
    # out-of-range clamps to [1, 16]
    assert cli.post("/api/panel/schedule", json={"workers": 999}).get_json()["workers"] == 16
    assert cli.post("/api/panel/schedule", json={"workers": 0}).get_json()["workers"] == 1

    # set a real value; a spawned job must carry --workers N reflecting it
    cli.post("/api/panel/schedule", json={"workers": 6})
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

    cli.post("/api/panel/run", json={"action": "sync"})
    import time
    time.sleep(0.05)
    argv = captured["argv"]
    assert "--workers" in argv and argv[argv.index("--workers") + 1] == "6"


def test_watch_status_default_shape(tmp_path):
    """conftest sets MOONGLADE_DISABLE_WATCH=1 for every test (see its docstring --
    without it, create_app() would open a real WebSocket to PixAI using whatever real
    credentials happen to be on this machine, on every single test in the suite).
    /api/watch/status must still answer safely with the never-started default shape.
    It's NOT actually localhost-only (api_watch_status() has no _is_local_request()
    check of its own, just ordinary read data) -- an authenticated LAN session can
    read it too, same as most routes here. The anonymous check below proves an
    UNauthenticated request is still refused outright, using a still-anonymous
    client off the same app rather than claiming address alone gates this route."""
    app = _client(tmp_path)
    anon = app.test_client()
    r = anon.get("/api/watch/status", environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 401
    cli = login_test_client(app)
    d = cli.get("/api/watch/status").get_json()
    assert d["connected"] is False and d["mirrored"] == 0 and d["events_seen"] == 0


def test_watch_autostarts_unless_disabled(tmp_path, monkeypatch):
    """The live-mirror watcher auto-starts (a background thread targeting _watch_loop)
    unless MOONGLADE_DISABLE_WATCH=1. This test explicitly clears the flag conftest sets
    globally to prove the auto-start WIRING is correct -- but replaces threading.Thread
    with a recorder that never calls .start() for real, so nothing actually attempts a
    live connection even with the flag cleared."""
    import threading
    monkeypatch.delenv("MOONGLADE_DISABLE_WATCH", raising=False)
    targets = []

    class _RecordingThread:
        def __init__(self, target=None, args=(), daemon=None):
            targets.append(target)
        def start(self):
            pass   # deliberately a no-op -- see docstring
    monkeypatch.setattr(threading, "Thread", _RecordingThread)

    create_app(tmp_path)

    assert any(t and t.__name__ == "_watch_loop" for t in targets)


def test_run_sync_action_spawns_sync_flag(tmp_path, monkeypatch):
    """'Sync now' is the panel's primary job: one argv, --sync (pull + metadata)."""
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

    cli = _authed_client(tmp_path)
    r = cli.post("/api/panel/run", json={"action": "sync"})
    assert r.get_json()["ok"] is True
    import time
    time.sleep(0.05)
    assert "--sync" in captured["argv"]


# --- Server control: stop / restart from the browser (Homebridge-style) ---

def test_ping_is_open(tmp_path):
    """Despite api_ping()'s own "Open" docstring, the global front door (added after
    that comment was written) now gates it like every other /api/ route -- it's listed
    among the previously-fully-ungated routes in _enforce_front_door()'s docstring and
    covered by tests/test_web_auth.py's parametrized denial tests. This just needs a
    logged-in session like everything else here."""
    cli = _authed_client(tmp_path)
    assert cli.get("/api/ping").get_json() == {"ok": True}


def test_server_stop_schedules_exit_0(tmp_path, monkeypatch):
    """Per the LAN-auth pass's commit message ("/api/server/stop ... stay open to any
    logged-in LAN session" -- owner decision), this is trusted for ANY authenticated
    session, not localhost-only -- api_server_stop() has no _is_local_request() check
    of its own. The anonymous check below proves an unauthenticated request is
    refused regardless of address; the authenticated checks after prove a logged-in
    session can stop it from either address."""
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _client(tmp_path).test_client()
    r0 = cli.post("/api/server/stop", environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r0.status_code == 401 and codes == []
    cli = login_existing_client(cli)
    d = cli.post("/api/server/stop").get_json()
    assert d == {"ok": True, "action": "stop"} and codes == [0]      # stop -> exit 0
    d2 = cli.post("/api/server/stop", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).get_json()
    assert d2 == {"ok": True, "action": "stop"} and codes == [0, 0]  # LAN session: also trusted


def test_server_restart_needs_supervisor(tmp_path, monkeypatch):
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _authed_client(tmp_path)
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
    html = _authed_client(tmp_path).get("/panel").get_data(as_text=True)
    assert "Restart server" in html and "Stop server" in html


# --- Cancel a running maintenance job from the browser (no Task Manager) ---

def test_cancel_with_no_job_is_a_noop(tmp_path):
    cli = _authed_client(tmp_path)
    r = cli.post("/api/panel/cancel")
    assert r.get_json() == {"ok": False, "error": "no job is running"}


def test_cancel_terminates_running_job(tmp_path, monkeypatch):
    """A running job's subprocess is .terminate()'d and the status becomes
    'cancelled' -- not 'failed' -- so the UI can say the user stopped it."""
    import subprocess, threading, time

    class CancelableProc:
        """stdout blocks until terminate() is called, so the job stays 'running'
        until we cancel it -- mirroring a long dedup that hasn't finished."""
        def __init__(self):
            self._stop = threading.Event()
            self.terminated = False
            self._sent = False
            self.stdout = self

        def readline(self):
            if not self._sent:
                self._sent = True
                return "hashing...\n"
            self._stop.wait()          # block here until terminate()
            return ""                  # EOF -> reader loop ends

        def close(self):
            pass

        def wait(self):
            self._stop.wait()
            return 1                    # terminated processes exit non-zero

        def terminate(self):
            self.terminated = True
            self._stop.set()

    proc = CancelableProc()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

    cli = _authed_client(tmp_path)
    assert cli.post("/api/panel/run", json={"action": "dedup-dry"}).get_json()["ok"] is True

    # wait for the job to actually be 'running' (reader thread picked up the proc)
    for _ in range(50):
        if cli.get("/api/panel/status").get_json()["status"] == "running":
            break
        time.sleep(0.02)
    assert cli.get("/api/panel/status").get_json()["status"] == "running"

    d = cli.post("/api/panel/cancel").get_json()
    assert d == {"ok": True, "action": "cancel"}
    assert proc.terminated is True

    # the reader thread should now settle to 'cancelled' (not 'failed')
    for _ in range(50):
        if cli.get("/api/panel/status").get_json()["status"] != "running":
            break
        time.sleep(0.02)
    assert cli.get("/api/panel/status").get_json()["status"] == "cancelled"


def test_cancel_is_localhost_only(tmp_path):
    """AUTHENTICATED but non-local, so a 403 can only come from the handler's own
    _is_local_request() check. This previously drove an anonymous client asserting 401 --
    the front door's answer, returned before the handler runs -- so it passed whether or
    not the check existed. It did not: commit 0fd8cee deleted it (in the very commit that
    built the two-tier model for the sibling route /api/panel/run) while leaving the
    'Localhost-only' docstring in place. Restored 2026-07-19."""
    cli = _authed_client(tmp_path)
    r = cli.post("/api/panel/cancel", environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403
    assert "localhost" in r.get_json()["error"]


def test_schedule_write_is_localhost_only_but_read_is_not(tmp_path):
    """The schedule endpoint is deliberately SPLIT: GET stays login-only so a LAN
    session's Panel can still render current settings, while POST is localhost-only.
    Its check was dropped in the same commit as cancel's. Writing matters more than
    'it's only settings' suggests -- sync-videos is a real PANEL_ACTIONS key with
    destructive=False and panel_visible=False, so a LAN caller could schedule a
    full-history sync at 16 workers hourly, forever, via a job with no Panel button;
    and `workers` is read by _panel_run for EVERY run, including the owner's own local
    ones."""
    cli = _authed_client(tmp_path)
    lan = {"REMOTE_ADDR": "192.168.1.9"}
    assert cli.get("/api/panel/schedule", environ_overrides=lan).status_code == 200
    r = cli.post("/api/panel/schedule", json={"action": "sync-videos", "enabled": True,
                                              "interval_hours": 1, "workers": 16},
                 environ_overrides=lan)
    assert r.status_code == 403
    assert "localhost" in r.get_json()["error"]
    # and the write really did not land
    assert cli.get("/api/panel/schedule").get_json().get("enabled") is not True


# --- The Loom: ffmpeg export of the rough cut (mocked -- no real ffmpeg) ---

def test_loom_export_runs_and_downloads(tmp_path, monkeypatch):
    import subprocess, shutil, io, time
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "shot_v1.mp4").write_bytes(b"fakemp4")   # media_id 'v1'
    # the export resolves the clip via the catalog row (is_video + filename)
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="v1", filename="videos/shot_v1.mp4", is_video="1",
             created_at="2025-01-01T00:00:00")])
    monkeypatch.setattr(shutil, "which", lambda n: "ffmpeg" if n == "ffmpeg" else None)

    class FakeProc:
        def __init__(self, argv):
            open(argv[-1], "wb").write(b"OUTPUT")          # argv[-1] = out path
            self.stderr = io.StringIO("frame=1 time=00:00:01.00 bitrate=x\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: FakeProc(argv))

    cli = create_app(tmp_path).test_client()
    # An unauthenticated LAN request can't kick off exports -- checked FIRST, while
    # `cli` is still anonymous (api_loom_export() has no extra _is_local_request()
    # check of its own; once logged in, a LAN session is trusted the same as the owner).
    r = cli.post("/api/loom/export", json={"clips": []},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 401
    cli = login_existing_client(cli)
    r = cli.post("/api/loom/export",
                 json={"clips": [{"mid": "v1", "in": 0, "out": 2}], "total_seconds": 2})
    assert r.get_json().get("ok") is True
    for _ in range(60):
        d = cli.get("/api/loom/export-status").get_json()
        if d["status"] != "running":
            break
        time.sleep(0.02)
    assert d["status"] == "done" and d["progress"] == 100
    assert cli.get("/api/loom/export-file").status_code == 200


def test_loom_export_needs_a_video(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: "ffmpeg")
    cli = _authed_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [{"mid": "nope", "in": 0}]})
    assert r.status_code == 400 and "no finished shot" in r.get_json()["error"]


# --- probe_has_audio / probe_duration: pure ffprobe wrappers, fail-soft ---------

def test_probe_has_audio(monkeypatch):
    import subprocess, shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/bin/ffprobe" if n == "ffprobe" else None)

    class R:
        def __init__(self, out):
            self.stdout = out
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R("0\n"))
    assert g.probe_has_audio("clip.mp4") is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R(""))
    assert g.probe_has_audio("silent.mp4") is False          # no stream index -> no audio
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert g.probe_has_audio("clip.mp4") is False            # ffprobe missing -> fail soft

    def _boom(*a, **k):
        raise OSError("gone")
    monkeypatch.setattr(shutil, "which", lambda n: "/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert g.probe_has_audio("clip.mp4") is False             # never raises


def test_probe_duration(monkeypatch):
    import subprocess, shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/bin/ffprobe")

    class R:
        def __init__(self, out):
            self.stdout = out
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R("5.234\n"))
    assert g.probe_duration("clip.mp4") == 5.234
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R("not-a-number\n"))
    assert g.probe_duration("clip.mp4") is None                # never raises on garbage
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert g.probe_duration("clip.mp4") is None                # ffprobe missing -> None


# --- /api/loom/export: real audio rides along, silence fills the gap -----------

def _mock_export_ffmpeg(monkeypatch):
    """Same FakeProc convention as test_loom_export_runs_and_downloads, but captures
    every argv so the constructed ffmpeg command is inspectable."""
    import subprocess, shutil, io
    monkeypatch.setattr(shutil, "which", lambda n: "ffmpeg" if n == "ffmpeg" else None)
    captured = []

    class FakeProc:
        def __init__(self, argv):
            captured.append(argv)
            open(argv[-1], "wb").write(b"OUTPUT")
            self.stderr = io.StringIO("frame=1 time=00:00:01.00 bitrate=x\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: FakeProc(argv))
    return captured


def _two_video_client(tmp_path):
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "shot_v1.mp4").write_bytes(b"fakemp4")
    (tmp_path / "videos" / "shot_v2.mp4").write_bytes(b"fakemp4")
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="v1", filename="videos/shot_v1.mp4", is_video="1",
             created_at="2025-01-01T00:00:00"),
        _row(media_id="v2", filename="videos/shot_v2.mp4", is_video="1",
             created_at="2025-01-01T00:00:00")])
    return login_test_client(create_app(tmp_path))


def _ffmpeg_call(captured):
    """create_app() shells out to git rev-parse for its build stamp -- pick out the
    actual ffmpeg invocation from everything Popen captured, not just captured[0]."""
    return next(argv for argv in captured if argv and argv[0] == "ffmpeg")


def _filter_complex_of(argv):
    return argv[argv.index("-filter_complex") + 1]


def test_export_real_audio_maps_both_streams_no_a0(tmp_path, monkeypatch):
    """The original bug: audio was hard-dropped (concat=...a=0, no -c:a, no [aout] map)
    even when every clip has real audio. Two clips, both WITH audio."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: True)
    cli = _two_video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0, "out": 2}, {"mid": "v2", "in": 0, "out": 3}],
        "total_seconds": 5})
    assert r.get_json()["ok"] is True
    argv = _ffmpeg_call(captured)
    fc = _filter_complex_of(argv)
    assert "a=0" not in fc and "a=1" in fc
    assert "-map" in argv and "[aout]" in argv
    assert "-c:a" in argv and "aac" in argv
    assert "anullsrc" not in fc                    # no silence needed, no synthetic input
    # concat's input pads must be PER-SEGMENT interleaved (v0,a0,v1,a1,...) -- grouping by
    # stream type instead ([v0][v1][a0][a1]) is a real ffmpeg error ("media type mismatch
    # between ... audio and ... video"), caught only by actually running ffmpeg, not by any
    # assertion on individual substrings above. Pin the exact adjacent ordering.
    assert "[v0][a0][v1][a1]concat=" in fc
    assert argv.count("-i") == 2                   # exactly the two real clips, no lavfi extra


def test_export_silent_clip_gets_matching_duration_silence(tmp_path, monkeypatch):
    """One real-audio clip + one silent clip (e.g. rendered without 'Generate audio') --
    the silent one must get a synthetic track sized to its OWN trim span, not skipped."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio",
                        lambda path: "v1" in str(path))   # v1 has audio, v2 doesn't
    cli = _two_video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0, "out": 2}, {"mid": "v2", "in": 1, "out": 4}],
        "total_seconds": 5})
    assert r.get_json()["ok"] is True
    argv = _ffmpeg_call(captured)
    fc = _filter_complex_of(argv)
    assert "a=1" in fc and "a=0" not in fc
    assert "anullsrc" in " ".join(argv)             # synthetic-silence input WAS added
    assert argv.count("-i") == 3                    # 2 real clips + 1 lavfi anullsrc
    # the silent segment (v2, span 4-1=3.0s) draws from input index 2 (after the 2 real -i's)
    assert "[2:a]atrim=duration=3.000" in fc
    assert "atrim=start=0.000:end=2.000" in fc      # v1's real audio trimmed to its own span


def test_export_all_silent_reuses_one_anullsrc_input(tmp_path, monkeypatch):
    """Neither clip has audio -- exactly ONE synthetic-silence input is added and referenced
    twice (not duplicated per segment); each segment still gets its own correctly-sized span."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    cli = _two_video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0, "out": 2}, {"mid": "v2", "in": 0, "out": 3}],
        "total_seconds": 5})
    assert r.get_json()["ok"] is True
    argv = _ffmpeg_call(captured)
    fc = _filter_complex_of(argv)
    assert argv.count("-i") == 3                    # 2 real clips + exactly 1 lavfi input
    assert "[2:a]atrim=duration=2.000" in fc and "[2:a]atrim=duration=3.000" in fc


def test_export_silent_clip_with_no_trim_out_probes_real_duration(tmp_path, monkeypatch):
    """When 'out' isn't set (trim to the clip's real end) AND the clip has no audio, the
    synthetic silence can't infer a length from anullsrc -- probe_duration must be consulted."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    monkeypatch.setattr(g, "probe_duration", lambda path: 6.0)
    cli = _two_video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 1.0}], "total_seconds": 5})   # no 'out' -> co is None
    assert r.get_json()["ok"] is True
    fc = _filter_complex_of(_ffmpeg_call(captured))
    assert "[1:a]atrim=duration=5.000" in fc         # probed 6.0 - in(1.0) = 5.0


def test_new_parity_actions_spawn_the_right_whitelisted_argv(tmp_path, monkeypatch):
    """Web-parity pass: five actions gained a web entry point so nothing needs the CLI.

    The two OPTION toggles (full audit, delete-instead-of-quarantine) are separate
    whitelisted action KEYS, not flags the client contributes. That distinction is the
    security property the runner is built on -- _panel_run assembles "a WHITELISTED argv,
    never an arbitrary command" -- so a checkbox that appended argv would erode it.

    Asserts the argv actually SPAWNED rather than reading the server-side table, because
    the table is closed over inside create_app() and its argv is deliberately never sent
    to the browser. Spawning is also the thing that matters."""
    import subprocess, io
    captured = []

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")
        def wait(self):
            return 0

    def fake_popen(argv, **k):
        captured.append(argv)
        return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    cli = _authed_client(tmp_path)
    cases = [
        ("audit-full",      ["--audit"],                              False),
        ("verify-dupes",    ["--verify-dupes"],                       False),
        ("rebuild-similar", ["--rebuild-similar"],                    False),
        ("sync-videos",     ["--sync-videos"],                        False),
        ("sync-artworks",   ["--sync-artworks"],                      False),
        ("dedup-delete",    ["--dedup", "--apply", "--dedup-delete"], True),
    ]
    import time
    for action, expected, destructive in cases:
        captured.clear()
        body = {"action": action}
        if destructive:
            body["confirm"] = True
        r = cli.post("/api/panel/run", json=body)
        assert r.status_code == 200, "{} -> {}".format(action, r.get_data(as_text=True))
        for _ in range(50):                       # one job at a time; let it finish
            if cli.get("/api/panel/status").get_json()["status"] != "running":
                break
            time.sleep(0.02)
        assert captured, "{} spawned nothing".format(action)
        argv = captured[0]
        for flag in expected:
            assert flag in argv, "{} argv missing {}: {}".format(action, flag, argv)
        # The full audit must NOT carry --no-content -- that flag is what makes the
        # default audit the fast pass, so keeping it would make "full" a no-op.
        if action == "audit-full":
            assert "--no-content" not in argv


def test_dedup_delete_refuses_without_confirm(tmp_path, monkeypatch):
    """It deletes outright with no _duplicates/ safety net, so it must be gated at
    least as hard as dedup-apply -- confirm required, and (covered by
    test_destructive_action_refuses_authenticated_lan_session) localhost-only."""
    import subprocess
    spawned = {"n": 0}
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.update(n=spawned["n"] + 1))
    cli = _authed_client(tmp_path)
    base = spawned["n"]
    r = cli.post("/api/panel/run", json={"action": "dedup-delete"})   # no confirm
    assert r.status_code == 400 and "confirm" in r.get_json()["error"]
    assert spawned["n"] == base

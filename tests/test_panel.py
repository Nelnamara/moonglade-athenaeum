"""Control Panel: maintenance-job runner. Whitelist-only actions, destructive ones
gated behind confirm, one at a time. The subprocess spawn is monkeypatched so no CLI
actually runs."""
import re
import moonglade_gallery as g
import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client, login_existing_client


def _csrf(html):
    # Either the classic hidden input (bootstrap_mode) or the React shell's
    # window.MG_BOOT JSON blob (the common case: a real account already
    # exists, so GET /login now serves LoginPage.jsx -- 2026-08-02).
    m = re.search(r'name="csrf" value="([^"]+)"|"csrf":\s*"([^"]+)"', html)
    assert m, "login page did not render a csrf token (classic hidden field or MG_BOOT)"
    return m.group(1) or m.group(2)


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
    # undo-organize / restore-orphans were the last two CLI-only maintenance actions;
    # they must RENDER a button (not merely be runnable), which is the point of adding
    # them -- and render among the DESTRUCTIVE ones, since both move files on disk.
    import json
    by_action = {a["action"]: a for a in json.loads(buttons_json)}
    for shown in ("undo-organize", "restore-orphans"):
        assert shown in by_action, "{} has no Maintenance button".format(shown)
        assert by_action[shown]["destructive"] is True
    # reconcile-deleted deliberately stays button-less -- NOT an oversight. --sync already
    # runs it as its final step (run_sync's pipeline), so a button would be a second path
    # to work that just happened, inviting someone to run it and wonder why nothing
    # changed. It stays schedulable for anyone wanting it on its own cadence.
    assert "reconcile-deleted" not in buttons_json
    assert '"action": "reconcile-deleted"' in dropdown_json


def test_panel_summary_matches_the_page_route(tmp_path):
    """/api/panel/summary (2026-08-02, for the React Control Panel overlay) is a JSON
    twin of /panel's own aggregation -- same data, same local/destructive visibility
    rule. Asserted against the SAME two properties test_panel_page_renders_with_actions
    checks on the HTML route, so a future change to either can't silently diverge."""
    cli = _authed_client(tmp_path)
    d = cli.get("/api/panel/summary").get_json()
    assert d["stats"]["images"] == 1  # the one seeded row
    by_action = {a["action"]: a for a in d["actions"]}
    assert "sync" in by_action
    assert "reconcile-deleted" not in by_action          # panel_visible: False
    all_by_action = {a["action"]: a for a in d["all_actions"]}
    assert "reconcile-deleted" in all_by_action            # still in the full list
    for shown in ("undo-organize", "restore-orphans"):
        assert by_action[shown]["destructive"] is True
    assert d["panel_is_local"] is True                     # test client is loopback
    assert d["out_dir"], "a local session must see the real out_dir"
    assert "csrf" in d and d["csrf"]
    assert d["branding"]["mark"] == "logo"                 # load_branding()'s own default
    assert "anims" in d["branding"] and "classic" in d["branding"]["anims"]
    assert set(d["branding"]["slots"].keys()) == {"banner_main", "banner_login", "mascots", "rewards", "banner_loom"}
    assert d["trash_count"] == 0                            # nothing quarantined yet


def test_panel_summary_trash_count_is_real(tmp_path):
    """Control Panel.dc.html:226's {{ trashCount }} -- the Trash tile's own real
    count. Previously hardcoded to "--" on both platforms (2026-08-05 fix):
    nothing fetched it until now, the real number only ever resolved once
    TrashSubOverlay's own /api/trash/list call ran."""
    import moonglade_gallery as g
    qdir = tmp_path / g.DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "a.webp").write_bytes(b"x")
    (qdir / "b.webp").write_bytes(b"x")
    cli = _authed_client(tmp_path)
    assert cli.get("/api/panel/summary").get_json()["trash_count"] == 2


def test_panel_summary_withholds_out_dir_from_lan(tmp_path):
    """The host filesystem path is the same host-detail /panel's own docstring withholds
    from a LAN caller (S2, 2026-07-21 audit) -- this JSON twin must match, not leak it."""
    cli = _authed_client(tmp_path)
    LAN = "203.0.113.5"
    d = cli.get("/api/panel/summary", environ_overrides={"REMOTE_ADDR": LAN}).get_json()
    assert d["out_dir"] == ""
    assert d["panel_is_local"] is False
    by_action = {a["action"]: a for a in d["actions"]}
    assert "undo-organize" not in by_action, (
        "a LAN session must not receive destructive actions in the visible list")


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


def test_panel_job_events_carry_action_and_rc(tmp_path, monkeypatch):
    """The run-history ledger (2026-08-06) reads jobs.jsonl's panel events: the start
    event must carry the machine `action` key (per-action last-run lookups + "run
    again"), and the terminal event must carry `rc` (the design's own "… · rc 0"
    result format). Reconstructed via the same read_jobs() the /api/jobs feed uses,
    so this asserts what the ledger actually receives, not raw log lines."""
    import subprocess

    class FakeProc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("line one\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    cli = _authed_client(tmp_path)
    cli.post("/api/panel/run", json={"action": "sync"})
    import time
    for _ in range(50):
        d = cli.get("/api/panel/status").get_json()
        if d["status"] != "running":
            break
        time.sleep(0.02)
    assert d["status"] == "done"

    import moonglade_backup as core
    jobs = [j for j in core.read_jobs(tmp_path) if j.get("type") == "panel"]
    assert jobs, "the panel run never reached jobs.jsonl"
    job = jobs[0]
    assert job.get("action") == "sync", "start event lost the machine action key"
    assert job.get("rc") == 0, "terminal event lost the exit code"
    assert job.get("status") == "done"


def test_run_reports_done_with_errors_from_the_warn_marker(tmp_path, monkeypatch):
    """D-4: the CLI subprocess prints a ~=MGWARN=~N marker line when some files failed
    but the run itself completed (exit 0). Before the fix, _panel_reader had no idea
    this marker existed -- it fell into the generic log-lines branch, and status was
    computed purely from rc==0, so this looked identical to a clean 'done'."""
    import subprocess

    class FakeProc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("line one\n~=MGWARN=~3\nline two\n")
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    cli = _authed_client(tmp_path)
    cli.post("/api/panel/run", json={"action": "sync"})
    import time
    d = {}
    for _ in range(50):
        d = cli.get("/api/panel/status").get_json()
        if d["status"] != "running":
            break
        time.sleep(0.02)
    assert d["status"] == "done_with_errors" and d["rc"] == 0
    assert d["warn_count"] == 3
    # the marker line itself must not pollute the visible log
    assert "~=MGWARN=~3" not in d["lines"]
    assert "line one" in d["lines"] and "line two" in d["lines"]


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
    assert argv[1].endswith("moonglade_backup.py")
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
            # Guard on argv[0] -- subprocess.Popen is patched globally, and
            # create_app() (called right below) also shells out to
            # `git rev-parse --short HEAD` (_build_stamp). For THAT call
            # argv[-1] is the literal string "HEAD", so writing to it
            # unconditionally dropped a stray 6-byte file named HEAD into the
            # repo root on every run of this test (docs/AUDIT_2026-07-21.md O10).
            if argv and argv[0] == "ffmpeg":
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
            # Same guard as the other FakeProc in this file -- see its comment.
            # Any create_app() call after this monkeypatch shells `git rev-parse
            # --short HEAD` through the same patched Popen; without the guard
            # argv[-1] == "HEAD" gets a stray file written to it in the repo root.
            if argv and argv[0] == "ffmpeg":
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
        # The incremental counterpart. Both are non-destructive by the Panel's definition
        # (nothing leaves the disk), but only this one is safe to reach for after an
        # interrupted build -- rebuild-similar drops the table first.
        ("sync-similar",    ["--sync-similar"],                       False),
        ("sync-videos",     ["--sync-videos"],                        False),
        ("sync-artworks",   ["--sync-artworks"],                      False),
        ("dedup-delete",    ["--dedup", "--apply", "--dedup-delete"], True),
        # The last two CLI-only maintenance actions. Both MOVE files on the server's
        # own disk, so both are destructive (confirm + localhost). --restore-orphans
        # is a no-op on its own: it only takes effect alongside --verify-dupes, so the
        # whitelisted argv must carry both flags.
        ("undo-organize",   ["--undo-organize"],                      True),
        ("restore-orphans", ["--verify-dupes", "--restore-orphans"],  True),
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


def _run_and_capture_argv(cli, monkeypatch, body):
    """POST an action, capture the spawned argv, wait for the one-at-a-time job to
    finish. Returns the argv list. Shared by the advanced-action tests below."""
    import subprocess, io, time
    captured = []

    class FakeProc:
        def __init__(self): self.stdout = io.StringIO("")
        def wait(self): return 0

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: captured.append(argv) or FakeProc())
    r = cli.post("/api/panel/run", json=body)
    assert r.status_code == 200, "{} -> {}".format(body, r.get_data(as_text=True))
    for _ in range(50):
        if cli.get("/api/panel/status").get_json()["status"] != "running":
            break
        time.sleep(0.02)
    assert captured, "{} spawned nothing".format(body)
    return captured[0]


def test_advanced_sync_actions_spawn_correct_argv(tmp_path, monkeypatch):
    """Web parity step 2: the Advanced section's three sync variants each map to a fixed
    whitelisted flag set -- a full re-walk (--full-meta, non-incremental), a read-only
    inventory (--count), and the test pull (--max, covered below)."""
    cli = _authed_client(tmp_path)
    assert "--full-meta" in _run_and_capture_argv(cli, monkeypatch, {"action": "resync-full"})
    assert "--count" in _run_and_capture_argv(cli, monkeypatch, {"action": "inventory"})


def test_test_pull_clamps_n_and_never_passes_a_raw_string(tmp_path, monkeypatch):
    """THE security-critical part of the parameterised action. test-pull is the one panel
    action that carries a value, so the value must be proven to reach argv only as a
    bounded integer -- clamped into [1,200], defaulted on garbage/absence -- never a raw
    client string. This is what keeps _panel_run's "a WHITELISTED argv, never an arbitrary
    command" true even with a parameter in play."""
    cli = _authed_client(tmp_path)

    def n_after_max(body):
        argv = _run_and_capture_argv(cli, monkeypatch, dict(body, action="test-pull"))
        assert "--max" in argv, argv
        val = argv[argv.index("--max") + 1]
        assert val.lstrip("-").isdigit(), "N reached argv as a non-integer: {!r}".format(val)
        return int(val)

    assert n_after_max({"n": 5}) == 5                 # in range -> passed through
    assert n_after_max({"n": 999999}) == 200          # over max -> clamped to hi
    assert n_after_max({"n": 0}) == 1                 # under min -> clamped to lo
    assert n_after_max({"n": -50}) == 1               # negative -> clamped to lo
    assert n_after_max({"n": "20; rm -rf /"}) == 20   # injection attempt -> default, never in argv
    assert n_after_max({"n": "abc"}) == 20            # garbage -> default
    assert n_after_max({}) == 20                       # absent -> default


def test_advanced_actions_are_flagged_and_kept_off_the_scheduler(tmp_path):
    """The panel hands the client an `advanced` flag per action (so they render in the
    Advanced section, not the main button rows) and the scheduler dropdown filters on it.
    Server-side backstop: the scheduler LOOP also skips advanced actions, so even a
    hand-edited schedule naming one never fires. Here we pin the flag the client keys on."""
    import json
    cli = _authed_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    m = re.search(r"var ALL_ACTIONS = (\[.*?\]);", html)
    assert m, "ALL_ACTIONS not found on the panel page"
    by_action = {a["action"]: a for a in json.loads(m.group(1))}
    for adv in ("resync-full", "inventory", "test-pull"):
        assert by_action[adv]["advanced"] is True
    assert by_action["test-pull"]["int_param"] is True
    assert by_action["sync"]["advanced"] is False      # an ordinary action is not advanced


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

def test_myart_items_returns_card_ready_artwork_rows(tmp_path):
    """GET /api/myart/items (the My Art tabbed gallery, 2026-08-06): every catalog
    row with an artwork_id -- public AND private -- card-ready: thumb URL, title
    with prompt fallback, is_video split, parsed tags, visibility flag. Rows with
    no artwork_id (never published/synced) are excluded."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="m1", artwork_id="a1", title="Titled One", prompt_preview="p1",
             is_video="0", is_published="1", liked_count="12", art_tags="elf, moon",
             created_at="2026-07-01T10:00:00", filename="x_m1.png"),
        _row(media_id="m2", artwork_id="a2", title="", prompt_preview="fallback prompt here",
             is_video="0", is_published="0", created_at="2026-07-02T10:00:00",
             filename="x_m2.png"),
        _row(media_id="m3", artwork_id="a3", title="Vid", is_video="1", is_published="1",
             liked_count="3", art_tags="loop", created_at="2026-07-03T10:00:00",
             filename="x_m3.mp4"),
        _row(media_id="m4", title="No artwork", created_at="2026-07-04T10:00:00",
             filename="x_m4.png"),
    ])
    cli = login_test_client(create_app(tmp_path))
    d = cli.get("/api/myart/items").get_json()
    items = {it["media_id"]: it for it in d["items"]}
    assert set(items) == {"m1", "m2", "m3"}          # m4 has no artwork_id
    assert items["m1"]["public"] is True and items["m1"]["likes"] == 12
    assert items["m1"]["tags"] == ["elf", "moon"]
    assert items["m1"]["thumb"] == "/thumbs/m1.jpg"
    assert items["m2"]["public"] is False
    assert items["m2"]["title"].startswith("fallback prompt")   # title falls back
    assert items["m3"]["is_video"] is True
    assert [it["media_id"] for it in d["items"]] == ["m3", "m2", "m1"]   # newest first

def _publish_setup(tmp_path, monkeypatch):
    """Logged-in client with every PixAI call stubbed AT THE CORE MODULE -- these tests
    must never touch the real account. (The route's own _gen_session is a closure inside
    create_app, so patching a module attribute of moonglade_gallery would silently do
    nothing and let a real session through; patching moonglade_backup itself is what
    actually intercepts. Found the hard way while writing these.) Returns (client, calls)."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="mUn", task_id="t99", title="Unpublished one", filename="x_mUn.png",
             created_at="2026-07-01T00:00:00"),
        _row(media_id="mPub", task_id="t1", artwork_id="a1", title="Published one",
             is_published="1", art_tags="elf", filename="x_mPub.png",
             created_at="2026-07-02T00:00:00"),
    ])
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def _tacks(session, tags):
        calls.append(("resolve_tack_ids", list(tags)))
        return ([("tack-" + str(t).lstrip("#")) for t in tags if t != "nosuchtag"],
                [t for t in tags if t == "nosuchtag"])

    def _publish(session, task_id, **kw):
        calls.append(("publish", task_id, kw)); return {"id": "newart1"}

    def _update(session, artwork_id, **kw):
        calls.append(("update", artwork_id, kw)); return {"id": artwork_id}

    def _delete(session, artwork_id):
        calls.append(("delete", artwork_id)); return True

    def _media_index(session, task_id, media_id):
        calls.append(("task_media_index", task_id, media_id))
        return None if media_id == "mNoIdx" else 1

    monkeypatch.setattr(core, "task_media_index", _media_index)
    monkeypatch.setattr(core, "resolve_tack_ids", _tacks)
    monkeypatch.setattr(core, "publish_artwork_from_task", _publish)
    monkeypatch.setattr(core, "update_artwork", _update)
    monkeypatch.setattr(core, "delete_artwork", _delete)
    return login_test_client(create_app(tmp_path)), calls


def _post_publish(cli, body):
    # the live session token, the same source the React panel reads it from
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    return cli.post("/api/myart/publish", json=dict(body, csrf=csrf))


def test_myart_publish_previews_without_touching_the_account(tmp_path, monkeypatch):
    """No confirm -> NO mutation fires. The route reports what it WOULD do, including
    resolved tag ids and any tag it could not resolve."""
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    d = _post_publish(cli, {"action": "publish", "media_id": "mUn",
                            "tags": ["elf", "nosuchtag"]}).get_json()
    assert d["preview"] is True and d["action"] == "publish" and d["task_id"] == "t99"
    assert d["tack_ids"] == ["tack-elf"] and d["unmatched_tags"] == ["nosuchtag"]
    assert d["spends_credits"] is False
    assert d["media_index"] == 1        # resolved from the task, shown in the preview
    # both lookups are read-only; NO publish/update/delete reached the account
    assert sorted(c[0] for c in calls) == ["resolve_tack_ids", "task_media_index"]


def test_myart_publish_confirmed_mutates_and_mirrors_the_catalog(tmp_path, monkeypatch):
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    d = _post_publish(cli, {"action": "publish", "media_id": "mUn", "confirm": True,
                            "title": "New title", "media_index": 2}).get_json()
    assert d["published"] is True and d["artwork_id"] == "newart1"
    _, task_id, kw = next(c for c in calls if c[0] == "publish")
    # media_index comes from the TASK's own ordered outputs, not the client's body --
    # the request said 2, the server resolved 1, and the server wins.
    assert task_id == "t99" and kw["media_index"] == 1 and kw["title"] == "New title"
    items = cli.get("/api/myart/items").get_json()["items"]
    assert any(i["media_id"] == "mUn" and i["public"] for i in items)


def test_myart_publish_confirm_honors_a_deliberately_cleared_title(tmp_path, monkeypatch):
    """Regression, ultrareview 2026-08-06 bug_003: the confirm branch used to `title or
    row["title"] or ""`, so an intentionally-cleared title (empty string, not omitted)
    silently fell back to the catalog's stale title -- while the preview/confirm sheet had
    already shown the user an empty title. `mUn`'s catalog row starts with a real title
    ("Unpublished one"); sending title="" must publish EMPTY, not that stale title."""
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    d = _post_publish(cli, {"action": "publish", "media_id": "mUn", "confirm": True,
                            "title": ""}).get_json()
    assert d["published"] is True
    _, _, kw = next(c for c in calls if c[0] == "publish")
    assert kw["title"] == "", "an explicitly empty title must not fall back to the catalog row's stale title"


def test_myart_publish_confirm_falls_back_only_when_title_is_omitted(tmp_path, monkeypatch):
    """The counterpart to the test above: when the client never sends `title` at all
    (field genuinely absent, not cleared), falling back to the catalog's own title is
    correct -- that's the "publish with no explicit title" case, unaffected by this fix."""
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    d = _post_publish(cli, {"action": "publish", "media_id": "mUn", "confirm": True}).get_json()
    assert d["published"] is True
    _, _, kw = next(c for c in calls if c[0] == "publish")
    assert kw["title"] == "Unpublished one"


def test_myart_actions_guard_their_preconditions(tmp_path, monkeypatch):
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    # an unpublished image has no artwork to toggle
    assert _post_publish(cli, {"action": "visibility", "media_id": "mUn",
                               "private": True, "confirm": True}).status_code == 400
    # an already-published one cannot be published again
    assert _post_publish(cli, {"action": "publish", "media_id": "mPub",
                               "confirm": True}).status_code == 400
    assert _post_publish(cli, {"action": "nope", "media_id": "mPub"}).status_code == 400
    assert _post_publish(cli, {"action": "delete", "media_id": "ghost"}).status_code == 400
    assert not [c for c in calls if c[0] in ("publish", "update", "delete")]
    # the real flip works and mirrors into the catalog
    d = _post_publish(cli, {"action": "visibility", "media_id": "mPub",
                            "private": True, "confirm": True}).get_json()
    assert d["updated"] is True
    assert next(c for c in calls if c[0] == "update")[2]["private"] is True
    items = {i["media_id"]: i for i in cli.get("/api/myart/items").get_json()["items"]}
    assert items["mPub"]["public"] is False


def test_myart_publish_requires_csrf(tmp_path, monkeypatch):
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    r = cli.post("/api/myart/publish", json={"action": "delete", "media_id": "mPub",
                                             "confirm": True})
    assert r.status_code == 400
    assert not calls          # nothing reached the account

def test_myart_publish_refuses_when_the_batch_position_is_unresolvable(tmp_path, monkeypatch):
    """If the server can't tell WHICH image of a task a media_id is, it refuses rather
    than defaulting to index 0 -- publishing the wrong picture of a batch to a public
    profile is not a recoverable mistake."""
    cli, calls = _publish_setup(tmp_path, monkeypatch)
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="mNoIdx", task_id="t77", title="Ambiguous", filename="x_mNoIdx.png",
             created_at="2026-07-05T00:00:00"),
    ])
    r = _post_publish(cli, {"action": "publish", "media_id": "mNoIdx", "confirm": True})
    assert r.status_code == 400
    assert "refusing to publish" in r.get_json()["error"]
    assert not [c for c in calls if c[0] == "publish"]

# --- LoRA training: the spend path. Every test here stubs the account at the core
# module (see _publish_setup's comment for why a moonglade_gallery attribute patch
# would silently let a real session through). ---

def _train_setup(tmp_path, monkeypatch, free_quota=9):
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "training_free_quota", lambda s: free_quota)

    def _submit(session, *a, **kw):
        calls.append(("submit", a, kw))
        return {"id": "trn1", "refId": "model9"}

    monkeypatch.setattr(core, "submit_training", _submit)
    return login_test_client(create_app(tmp_path)), calls


def _post_train(cli, body):
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    return cli.post("/api/train/submit", json=dict(body, csrf=csrf))


_GOOD_TRAIN = {"base_model_id": "bm1", "media_ids": [str(i) for i in range(12)],
               "title": "Nel test", "trigger_words": "nelnamara druid",
               "category": "character"}


def test_train_preview_reports_free_quota_and_fires_nothing(tmp_path, monkeypatch):
    cli, calls = _train_setup(tmp_path, monkeypatch, free_quota=9)
    d = _post_train(cli, _GOOD_TRAIN).get_json()
    assert d["preview"] is True and d["is_free"] is True
    assert d["free_trainings_left"] == 9 and d["image_count"] == 12
    assert "Free" in d["cost_note"]
    assert not calls                       # nothing submitted


def test_train_confirmed_submits_when_free(tmp_path, monkeypatch):
    cli, calls = _train_setup(tmp_path, monkeypatch, free_quota=9)
    d = _post_train(cli, dict(_GOOD_TRAIN, confirm=True)).get_json()
    assert d["submitted"] is True and d["was_free"] is True
    assert d["task"]["refId"] == "model9"
    assert d["free_trainings_left"] == 8
    assert len(calls) == 1


def test_train_refuses_to_spend_credits_without_explicit_acceptance(tmp_path, monkeypatch):
    """With no free quota the cost is real AND unquotable (PixAI prices client-side),
    so the same click that was free must NOT silently spend. 402 until the caller
    explicitly accepts."""
    cli, calls = _train_setup(tmp_path, monkeypatch, free_quota=0)
    # a REAL base model version -> the preview quotes its real price (Illustrious = SDXL = 25k)
    body = dict(_GOOD_TRAIN, base_model_id="1844843519625072849")
    prev = _post_train(cli, body).get_json()
    assert prev["is_free"] is False and prev["price"] == 25000
    assert "25,000" in prev["cost_note"]
    r = _post_train(cli, dict(body, confirm=True))
    assert r.status_code == 402
    assert not calls
    # explicit acceptance lets it through
    d = _post_train(cli, dict(body, confirm=True, accept_credit_cost=True)).get_json()
    assert d["submitted"] is True and d["was_free"] is False
    assert len(calls) == 1


def test_train_validates_with_pixais_own_rules_before_any_network(tmp_path, monkeypatch):
    cli, calls = _train_setup(tmp_path, monkeypatch)
    bad = [
        (dict(_GOOD_TRAIN, media_ids=["1", "2"]), "at least 10"),
        (dict(_GOOD_TRAIN, title=""), "name"),
        (dict(_GOOD_TRAIN, trigger_words="   "), "trigger words"),
        (dict(_GOOD_TRAIN, category="wrong"), "category"),
        (dict(_GOOD_TRAIN, base_model_id=""), "base model"),
    ]
    for body, needle in bad:
        r = _post_train(cli, dict(body, confirm=True))
        assert r.status_code == 400, needle
        assert needle in r.get_json()["error"], (needle, r.get_json())
    assert not calls


def test_train_submit_requires_csrf(tmp_path, monkeypatch):
    cli, calls = _train_setup(tmp_path, monkeypatch)
    r = cli.post("/api/train/submit", json=dict(_GOOD_TRAIN, confirm=True))
    assert r.status_code == 400
    assert not calls


def test_trigger_words_normalize_to_pixais_rules():
    assert core.normalize_trigger_words("  nel   druid  ") == "nel druid"
    assert core.normalize_trigger_words(None) == ""

def test_list_trainable_base_models_is_the_curated_snapshot_grouped_by_arch():
    """The picker's data contract: PixAI's curated base list (captured snapshot, NOT the
    public model catalog -- the owner caught the first build pulling the general feed),
    grouped by architecture with the friendly labels and each model's VERSION id."""
    groups = core.list_trainable_base_models()
    labels = [g["label"] for g in groups]
    assert labels == ["DiT.2", "DiT.1", "SDXL", "SD 1.5"]     # DiT.3 has no models -> dropped
    sdxl = next(g for g in groups if g["label"] == "SDXL")
    titles = [m["title"] for m in sdxl["models"]]
    assert "Illustrious-v1.0" in titles and "NoobAI XL" in titles   # the real curated set
    assert "xl aaa" not in titles                                   # not the community feed
    assert sdxl["price"] == 25000
    il = next(m for m in sdxl["models"] if m["title"] == "Illustrious-v1.0")
    assert il["version_id"] == "1844843519625072849"     # the VERSION id, submit-ready
    assert il["cover"].startswith("https://images-ng.pixai.art/")
    # DiT.2 is the priciest; SD 1.5 the cheapest -- real captured pricing
    assert core.training_price_for_version("1983308862240288769") == 100000   # Tsubaki.2 (DiT.2)
    assert core.training_price_for_version("1648918127446573124") == 25000    # Moonbeam (SD 1.5)
    assert core.training_price_for_version("not-a-real-version") is None

# --- Lineage (2026-08-06): batch siblings (task_id) + derivation chain (source_media_id).

def test_source_media_of_task_reads_all_three_derive_shapes():
    edit = core.source_media_of_task({"parameters": {"chat": {"mediaId": "111", "modelId": "x"}}})
    assert edit == ("111", "edit")
    video = core.source_media_of_task({"parameters": {"i2v": {"mediaId": "222"}}})
    assert video == ("222", "video")
    upscale = core.source_media_of_task({"parameters": {"mediaId": "333", "upscale": 2}})
    assert upscale == ("333", "upscale")
    enlarge = core.source_media_of_task({"parameters": {"mediaId": "444", "enlarge": 2}})
    assert enlarge == ("444", "upscale")
    original = core.source_media_of_task({"parameters": {"prompts": "a cat"}})
    assert original == (None, None)
    assert core.source_media_of_task(None) == (None, None)
    assert core.source_media_of_task({}) == (None, None)


def test_api_lineage_returns_siblings_parent_and_children(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        # a 2-image batch: mBatch1/mBatch2 share task_id "tBatch"
        _row(media_id="mBatch1", task_id="tBatch", title="Batch one", filename="x_1.png"),
        _row(media_id="mBatch2", task_id="tBatch", title="Batch two", filename="x_2.png"),
        # mUp was upscaled FROM mBatch1
        _row(media_id="mUp", task_id="tUp", source_media_id="mBatch1", derive_kind="upscale",
             title="Upscaled", filename="x_3.png"),
        # an edit made from mUp too, so mUp has both a parent (mBatch1) and a child (mEdit)
        _row(media_id="mEdit", task_id="tEdit", source_media_id="mUp", derive_kind="edit",
             title="Edited", filename="x_4.png"),
        # an unrelated original, no lineage at all
        _row(media_id="mLoner", task_id="tLoner", title="Alone", filename="x_5.png"),
    ])
    cli = login_test_client(create_app(tmp_path))

    d = cli.get("/api/lineage/mBatch1").get_json()
    assert [s["media_id"] for s in d["siblings"]] == ["mBatch2"]
    assert d["parent"] is None
    assert [c["media_id"] for c in d["children"]] == ["mUp"]   # mUp was made FROM mBatch1
    assert d["children"][0]["kind"] == "upscale"

    d = cli.get("/api/lineage/mUp").get_json()
    assert d["siblings"] == []                              # tUp has only mUp
    assert d["parent"]["media_id"] == "mBatch1" and d["parent"]["kind"] == "upscale"
    assert [c["media_id"] for c in d["children"]] == ["mEdit"]
    assert d["children"][0]["kind"] == "edit"

    d = cli.get("/api/lineage/mLoner").get_json()
    assert d["siblings"] == [] and d["parent"] is None and d["children"] == []

    assert cli.get("/api/lineage/does-not-exist").status_code == 404


def test_extract_full_meta_includes_lineage_fields():
    fm = core.extract_full_meta({"parameters": {"chat": {"mediaId": "999", "modelId": "x"}},
                                 "outputs": {}})
    assert fm["source_media_id"] == "999" and fm["derive_kind"] == "edit"
    fm2 = core.extract_full_meta({"parameters": {"prompts": "a cat"}, "outputs": {}})
    assert fm2["source_media_id"] == "" and fm2["derive_kind"] == ""


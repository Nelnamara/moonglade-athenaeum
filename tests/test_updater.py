"""The auto-updater: the release check, the refusal matrix, and the apply sequence.

NOTHING here touches the network or runs a subprocess. `_git`, pip and the release fetch
are each substituted at their own seam, which is also the point of those seams existing:
this feature shells out and restarts a server, so every test drives it with the real code
paths and fake tools rather than the other way round.
"""
import json

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return login_test_client(create_app(tmp_path))


def _csrf(cli):
    return cli.get("/api/panel/summary").get_json()["csrf"]


def _rel(tag, name="A release", url="https://example.invalid/r", draft=False):
    return {"tag_name": tag, "name": name, "html_url": url, "draft": draft}


def _fake_opener(payload):
    """Stand in for urllib.request.urlopen: a context manager whose read() is the body."""
    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def read(self_inner):
            return json.dumps(payload).encode("utf-8")
    return lambda req, timeout=None: _Resp()


def _fresh_cache(monkeypatch):
    """The check cache is a module singleton -- reset it per test, the same isolation the
    suite gives every other module-level cache."""
    monkeypatch.setattr(g, "_update_cache", {"at": 0.0, "payload": None})


def _idle_state(monkeypatch):
    monkeypatch.setattr(g, "_update_state", {"phase": "idle", "error": "", "at": 0.0})
    # The real 2s handover pause exists for the browser poll; a test does not need it.
    monkeypatch.setattr(g, "UPDATE_RESTART_DELAY", 0)


# ---- version arithmetic ----------------------------------------------------

def test_versions_compare_numerically_not_as_text():
    """The bug this exists to prevent: "3.10.0" sorts BEFORE "3.9.0" as text, which would
    tell a 3.9 install it is current forever and a 3.10 install it is behind forever."""
    assert g.version_tuple("v3.10.0") > g.version_tuple("v3.9.0")
    assert g.version_tuple("3.6.0") == (3, 6, 0)          # a bare version parses too
    assert g.version_tuple("v3.6.0") == (3, 6, 0)         # ...identically to its tag
    for junk in ("assets-2026-08-21", "v3.6", "v3.6.0-rc1", "", None, "latest"):
        assert g.version_tuple(junk) is None, junk


def test_the_release_picker_takes_the_highest_version_not_the_first_listed():
    """GitHub orders by creation date. A hotfix cut on an old line AFTER a newer release
    lists FIRST -- and first-listed would then offer a 3.6.0 install a "newer" 3.5.1."""
    picked = g.pick_latest_release([_rel("v3.5.1"), _rel("v3.6.0"), _rel("v3.4.9")])
    assert picked["tag_name"] == "v3.6.0"
    # ...and the comparison is numeric there too
    assert g.pick_latest_release([_rel("v3.9.0"), _rel("v3.10.0")])["tag_name"] == "v3.10.0"


def test_the_release_picker_skips_prereleases():
    """"Update me" does not mean "put me on a release candidate"."""
    picked = g.pick_latest_release([
        {"tag_name": "v4.0.0", "prerelease": True, "html_url": "", "name": ""},
        _rel("v3.6.0")])
    assert picked["tag_name"] == "v3.6.0"


def test_the_release_picker_skips_asset_packs():
    """The whole correctness of the check. Asset packs are FULL releases and can be the
    newest thing in the repo -- /releases/latest would happily offer one as an app
    update."""
    picked = g.pick_latest_release([
        _rel("assets-2026-08-30"), _rel("assets-2026-08-21"), _rel("v3.6.0"), _rel("v3.5.0")])
    assert picked["tag_name"] == "v3.6.0"
    assert g.pick_latest_release([_rel("assets-2026-08-30")]) is None
    assert g.pick_latest_release([]) is None
    # a draft is not a release anyone can pull
    assert g.pick_latest_release([_rel("v9.9.9", draft=True), _rel("v3.6.0")])["tag_name"] == "v3.6.0"


# ---- the check route -------------------------------------------------------

def test_check_reports_behind_with_the_release_details(tmp_path, monkeypatch):
    _fresh_cache(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [
        _rel("assets-2026-08-30"), _rel("v3.10.0", "The Tenth", "https://example.invalid/v3100")])
    cli = _client(tmp_path)
    d = cli.get("/api/update/check").get_json()
    assert d["latest"] == "v3.10.0" and d["behind"] is True
    assert d["title"] == "The Tenth" and d["notes_url"] == "https://example.invalid/v3100"
    assert d["current"] and d["checked_at"] > 0
    assert "error" not in d


def test_check_reports_up_to_date_on_its_own_version(tmp_path, monkeypatch):
    import moonglade_backup as core
    _fresh_cache(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v" + core.__version__)])
    d = _client(tmp_path).get("/api/update/check").get_json()
    assert d["behind"] is False and d["latest"] == "v" + core.__version__


def test_check_is_cached_for_the_ttl(tmp_path, monkeypatch):
    """GitHub allows 60 unauthenticated requests an hour and the Panel fires this on every
    open -- ten opens must cost one request."""
    _fresh_cache(monkeypatch)
    calls = {"n": 0}

    def _fetch(**k):
        calls["n"] += 1
        return [_rel("v9.9.9")]
    monkeypatch.setattr(g, "fetch_releases", _fetch)
    cli = _client(tmp_path)
    for _ in range(5):
        assert cli.get("/api/update/check").get_json()["latest"] == "v9.9.9"
    assert calls["n"] == 1
    # ...and the cache genuinely expires rather than being permanent
    g._update_cache["at"] -= (g.UPDATE_CHECK_TTL + 1)
    cli.get("/api/update/check")
    assert calls["n"] == 2


def test_check_fails_soft_and_memoizes_the_failure_briefly(tmp_path, monkeypatch):
    """An offline machine opening the Panel gets a Panel -- and doesn't pay a full connect
    timeout on every open. The failure IS cached, but only for UPDATE_FAILURE_TTL, so one
    blip cannot hide a real update for the long TTL's half hour."""
    _fresh_cache(monkeypatch)
    calls = {"n": 0}

    def _boom(**k):
        calls["n"] += 1
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(g, "fetch_releases", _boom)
    cli = _client(tmp_path)
    r = cli.get("/api/update/check")
    assert r.status_code == 200
    d = r.get_json()
    assert d["behind"] is False and "getaddrinfo failed" in d["error"]
    cli.get("/api/update/check")                      # a second open costs nothing
    assert calls["n"] == 1
    assert g._update_cache["ttl"] == g.UPDATE_FAILURE_TTL
    assert g.UPDATE_FAILURE_TTL < g.UPDATE_CHECK_TTL  # ...and it is the SHORT one
    # once that short window passes, it really does try again
    g._update_cache["at"] -= (g.UPDATE_FAILURE_TTL + 1)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9")])
    assert cli.get("/api/update/check").get_json()["behind"] is True
    assert g._update_cache["ttl"] == g.UPDATE_CHECK_TTL   # a success caches the long way


def test_check_handles_a_release_list_with_no_versions(tmp_path, monkeypatch):
    _fresh_cache(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("assets-2026-08-30")])
    d = _client(tmp_path).get("/api/update/check").get_json()
    assert d["behind"] is False and d["error"] == "no versioned release found"


def test_fetch_releases_asks_github_for_the_list_not_latest(monkeypatch):
    """Pinned because /releases/latest is the obvious-looking call and the wrong one."""
    seen = {}

    def _opener(req, timeout=None):
        seen["url"] = req.full_url
        seen["ua"] = req.get_header("User-agent")
        return _fake_opener([_rel("v3.6.0")])(req, timeout)
    assert g.fetch_releases(opener=_opener)[0]["tag_name"] == "v3.6.0"
    assert "/releases?per_page=" in seen["url"] and "/releases/latest" not in seen["url"]
    assert "moonglade" in (seen["ua"] or "").lower()


# ---- the apply refusal matrix ----------------------------------------------

def _apply_ready(monkeypatch, branch="master", dirty="", supervised=True):
    """A machine where an update WOULD be allowed: supervised, on a clean master."""
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_supervised", lambda: supervised)

    def _git(args, **k):
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, branch
        if args[:1] == ["status"]:
            return 0, dirty
        if args[:1] == ["rev-parse"]:
            return 0, "abc123"
        return 0, ""
    monkeypatch.setattr(g, "_git", _git)
    return _git


def _apply(cli, **body):
    return cli.post("/api/update/apply", json=dict({"confirm": True, "csrf": _csrf(cli)}, **body))


def test_apply_refuses_without_csrf(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)
    r = cli.post("/api/update/apply", json={"confirm": True})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]


def test_apply_refuses_without_confirm(tmp_path, monkeypatch):
    """Never silent: the modal's explicit yes is the whole gate."""
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)
    r = cli.post("/api/update/apply", json={"csrf": _csrf(cli)})
    assert r.status_code == 400 and "confirm" in r.get_json()["error"]


def test_apply_refuses_under_read_only(tmp_path, monkeypatch):
    """Not a PixAI spend, but the owner's flag says don't change this install -- and this
    changes it more than anything else in the app."""
    import moonglade_backup as core
    monkeypatch.setattr(core, "READ_ONLY", True)
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409 and "READ_ONLY" in r.get_json()["error"]


def test_apply_refuses_unsupervised(tmp_path, monkeypatch):
    """Without the launcher, exit 42 stops the server instead of relaunching it -- the
    update would look like the app vanishing."""
    _apply_ready(monkeypatch, supervised=False)
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409 and "managed launcher" in r.get_json()["error"]


def test_apply_refuses_while_a_job_runs(tmp_path, monkeypatch):
    """Same rule Restart uses: a pull that swaps the code out from under a running job is
    how you get a half-old, half-new process. The refusal names the job in the way."""
    _apply_ready(monkeypatch)
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    app = create_app(tmp_path)
    app.extensions["mg_panel_job"].update(status="running", label="Sync now")
    cli = login_test_client(app)
    r = _apply(cli)
    assert r.status_code == 409
    assert "Sync now" in r.get_json()["error"]
    # and once the slot frees, the same call is allowed
    app.extensions["mg_panel_job"].update(status="idle", label="")
    monkeypatch.setattr(g.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None: type(
                            "T", (), {"start": lambda self_: None})())
    assert _apply(cli).status_code == 200


def test_apply_refuses_off_master(tmp_path, monkeypatch):
    _apply_ready(monkeypatch, branch="feat/something")
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409
    assert "feat/something" in r.get_json()["error"] and "master" in r.get_json()["error"]


def test_apply_refuses_a_dirty_tree_and_names_the_files(tmp_path, monkeypatch):
    """--ff-only would refuse anyway; refusing here says WHICH files are in the way."""
    _apply_ready(monkeypatch, dirty=" M moonglade_gallery.py\n?? notes.txt\n")
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert "uncommitted" in err and "moonglade_gallery.py" in err and "notes.txt" in err


def test_apply_starts_the_update_when_every_gate_passes(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)                 # built BEFORE the Thread patch: create_app
    started = {"n": 0}                      # starts threads of its own
    monkeypatch.setattr(g.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None: type(
                            "T", (), {"start": lambda self_: started.update(n=started["n"] + 1)})())
    r = _apply(cli)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert started["n"] == 1
    assert g.update_state()["phase"] == "pulling"
    # single-flight: a second click while one runs is refused, not queued
    r2 = _apply(cli)
    assert r2.status_code == 409 and "already running" in r2.get_json()["error"]


# ---- the apply sequence ----------------------------------------------------

def test_run_update_skips_pip_when_requirements_did_not_move(monkeypatch):
    """The common case. A dependency install is slow, and running one on every code
    update would make "nothing changed" the expensive path."""
    _idle_state(monkeypatch)
    seen = []

    def _git(args, **k):
        seen.append(args)
        if args[:1] == ["rev-parse"]:
            return 0, "OLD" if len(seen) == 1 else "NEW"
        if args[:1] == ["diff"]:
            return 0, "moonglade_gallery.py\ngallery/dist/app.js"
        return 0, "Updating abc..def"
    monkeypatch.setattr(g, "_git", _git)
    pip = {"n": 0}
    restarted = {"n": 0}
    assert g.run_update(lambda: restarted.update(n=1),
                        pip_fn=lambda: pip.update(n=pip["n"] + 1) or (0, "")) is True
    assert pip["n"] == 0 and restarted["n"] == 1
    assert g.update_state()["phase"] == "restarting"


def test_run_update_installs_deps_when_requirements_moved(monkeypatch):
    _idle_state(monkeypatch)
    calls = []

    def _git(args, **k):
        calls.append(args)
        if args[:1] == ["rev-parse"]:
            return 0, "OLD" if len([c for c in calls if c[:1] == ["rev-parse"]]) == 1 else "NEW"
        if args[:1] == ["diff"]:
            return 0, "requirements.txt\nmoonglade_backup.py"
        return 0, ""
    monkeypatch.setattr(g, "_git", _git)
    pip = {"n": 0}
    assert g.run_update(lambda: None, pip_fn=lambda: pip.update(n=1) or (0, "ok")) is True
    assert pip["n"] == 1


def test_an_unreadable_diff_installs_rather_than_guessing(monkeypatch):
    """Can't tell whether deps moved -> install. Guessing "no" can leave the app running
    new code against old dependencies; guessing "yes" only costs time."""
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_git", lambda args, **k: (0, "HEAD") if args[:1] == ["rev-parse"]
                        else (1, "fatal: bad object") if args[:1] == ["diff"] else (0, ""))
    assert g._requirements_changed("OLD", "NEW") is True


def test_a_failed_pull_stops_and_keeps_the_error_verbatim(monkeypatch):
    """--ff-only either fast-forwards or refuses, so a failed pull changed nothing -- and
    git's own words are what the person watching needs."""
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_git", lambda args, **k:
                        (0, "HEAD") if args[:1] == ["rev-parse"]
                        else (1, "fatal: Not possible to fast-forward, aborting."))
    pip = {"n": 0}
    restarted = {"n": 0}
    assert g.run_update(lambda: restarted.update(n=1),
                        pip_fn=lambda: pip.update(n=1) or (0, "")) is False
    st = g.update_state()
    assert st["phase"] == "failed" and "fast-forward" in st["error"]
    assert pip["n"] == 0 and restarted["n"] == 0        # nothing after the failure ran


def test_a_failed_pip_stops_before_restarting(monkeypatch):
    _idle_state(monkeypatch)
    heads = iter(["OLD", "NEW"])

    def _git(args, **k):
        if args[:1] == ["rev-parse"]:
            return 0, next(heads, "NEW")
        if args[:1] == ["diff"]:
            return 0, "requirements.txt"
        return 0, ""
    monkeypatch.setattr(g, "_git", _git)
    restarted = {"n": 0}
    assert g.run_update(lambda: restarted.update(n=1),
                        pip_fn=lambda: (1, "ERROR: could not install")) is False
    st = g.update_state()
    assert st["phase"] == "failed" and "could not install" in st["error"]
    assert restarted["n"] == 0


def test_a_refused_restart_is_reported_not_swallowed(monkeypatch):
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_git", lambda args, **k: (0, "SAME"))

    def _restart():
        raise RuntimeError("the managed launcher is gone")
    assert g.run_update(_restart, pip_fn=lambda: (0, "")) is False
    assert "launcher is gone" in g.update_state()["error"]


def test_status_route_reports_the_phase(tmp_path, monkeypatch):
    _idle_state(monkeypatch)
    cli = _client(tmp_path)
    assert cli.get("/api/update/status").get_json()["phase"] == "idle"
    g._set_update_state("failed", "git pull failed:\nfatal: whatever")
    d = cli.get("/api/update/status").get_json()
    assert d["phase"] == "failed" and "fatal: whatever" in d["error"]


# ---- rollback, retry, and the record that survives the restart ---------------

def test_a_failed_pip_rolls_the_pull_back(monkeypatch):
    """The dangerous failure. The tree was verified clean before the pull, so resetting to
    the recorded HEAD loses nothing -- and it is what stops the install sitting on new code
    with old dependencies."""
    _idle_state(monkeypatch)
    seen = []
    heads = iter(["OLD", "NEW"])

    def _git(args, **k):
        seen.append(list(args))
        if args[:1] == ["rev-parse"]:
            return 0, next(heads, "NEW")
        if args[:1] == ["diff"]:
            return 0, "requirements.txt"
        return 0, ""
    monkeypatch.setattr(g, "_git", _git)
    assert g.run_update(lambda: None,
                        pip_fn=lambda: (1, "ERROR: no matching distribution")) is False
    assert ["reset", "--hard", "OLD"] in seen, seen
    st = g.update_state()
    assert "no matching distribution" in st["error"]     # pip's own words, kept
    assert "Rolled back to OLD" in st["error"]           # ...and what was done about it


def test_a_failed_rollback_says_so_loudly(monkeypatch):
    """If the reset ALSO fails the install is genuinely in a bad state, and the error has
    to say which -- with the command to fix it by hand."""
    _idle_state(monkeypatch)
    heads = iter(["OLD", "NEW"])
    monkeypatch.setattr(g, "_git", lambda args, **k:
                        (0, next(heads, "NEW")) if args[:1] == ["rev-parse"]
                        else (0, "requirements.txt") if args[:1] == ["diff"]
                        else (1, "fatal: cannot reset") if args[:1] == ["reset"]
                        else (0, ""))
    assert g.run_update(lambda: None, pip_fn=lambda: (1, "boom")) is False
    err = g.update_state()["error"]
    assert "ROLLBACK ALSO FAILED" in err and "git reset --hard OLD" in err


def test_retrying_after_a_pip_failure_really_re_runs_pip(monkeypatch):
    """The retry trap the rollback closes. Without it the second attempt found the pull
    already applied, saw no requirements diff against the new HEAD, skipped pip entirely
    and declared success on an install whose dependencies were never installed."""
    _idle_state(monkeypatch)
    repo = {"head": "OLD"}                    # the checkout's real state across attempts
    pip = {"n": 0, "ok": False}

    def _git(args, **k):
        if args[:1] == ["rev-parse"]:
            return 0, repo["head"]
        if args[:1] == ["pull"]:
            repo["head"] = "NEW"
            return 0, "Updating OLD..NEW"
        if args[:1] == ["diff"]:
            moved = args[1:] == ["--name-only", "OLD", "NEW"]
            return 0, "requirements.txt" if moved else ""
        if args[:1] == ["reset"]:
            repo["head"] = args[2]
            return 0, ""
        return 0, ""

    def _pip():
        pip["n"] += 1
        return (0, "ok") if pip["ok"] else (1, "ERROR: transient")
    monkeypatch.setattr(g, "_git", _git)

    assert g.run_update(lambda: None, pip_fn=_pip) is False
    assert pip["n"] == 1 and repo["head"] == "OLD"        # rolled back, so...
    pip["ok"] = True
    assert g.run_update(lambda: None, pip_fn=_pip) is True
    assert pip["n"] == 2, "the retry must actually re-run pip"


def test_both_outcomes_are_written_to_the_activity_log(monkeypatch):
    """The only part of an update that survives the restart it triggers -- and the only
    record at all of one that failed while nobody was watching the modal."""
    _idle_state(monkeypatch)
    logged = []
    monkeypatch.setattr(g, "_git", lambda args, **k: (0, "SAME"))
    assert g.run_update(lambda: None, pip_fn=lambda: (0, ""),
                        log_fn=lambda status, error="": logged.append((status, error))) is True
    assert logged == [("done", "")]

    logged.clear()
    monkeypatch.setattr(g, "_git", lambda args, **k:
                        (0, "HEAD") if args[:1] == ["rev-parse"] else (1, "fatal: refusing"))
    assert g.run_update(lambda: None,
                        log_fn=lambda status, error="": logged.append((status, error))) is False
    assert logged[0][0] == "failed" and "fatal: refusing" in logged[0][1]


def test_a_logging_failure_never_breaks_the_update(monkeypatch):
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_git", lambda args, **k: (0, "SAME"))

    def _boom(status, error=""):
        raise OSError("disk full")
    assert g.run_update(lambda: None, pip_fn=lambda: (0, ""), log_fn=_boom) is True


def test_the_update_records_a_line_in_the_real_activity_log(tmp_path, monkeypatch):
    """End to end through the route: the jobs.jsonl line the activity tracker serves."""
    import moonglade_backup as core
    _apply_ready(monkeypatch)
    monkeypatch.setattr(g, "_git", lambda args, **k:
                        (0, "master") if args[:2] == ["rev-parse", "--abbrev-ref"]
                        else (0, "") if args[:1] == ["status"]
                        else (0, "SAME"))
    cli = _client(tmp_path)
    monkeypatch.setattr(g, "_schedule_server_exit", lambda code: None)
    real_thread = g.threading.Thread

    def _inline(target=None, args=(), kwargs=None, daemon=None):
        return type("T", (), {"start": lambda self_: target(*args, **(kwargs or {}))})()
    monkeypatch.setattr(g.threading, "Thread", _inline)
    assert _apply(cli).status_code == 200
    monkeypatch.setattr(g.threading, "Thread", real_thread)
    rows = [j for j in core.read_jobs(tmp_path) if j.get("type") == "update"]
    assert len(rows) == 1 and rows[0]["status"] == "done"
    assert rows[0]["label"] == "Updated Moonglade"


# ---- mutual exclusion, both directions ---------------------------------------

def _mid_update(monkeypatch, phase="pulling"):
    monkeypatch.setattr(g, "_update_state", {"phase": phase, "error": "", "at": 0.0})


def test_restart_and_stop_refuse_while_an_update_runs(tmp_path, monkeypatch):
    """The reverse of test_apply_refuses_while_a_job_runs: restarting mid-pull would land
    the process on half-pulled code."""
    monkeypatch.setattr(g, "_supervised", lambda: True)
    codes = []
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _client(tmp_path)
    _mid_update(monkeypatch, "deps")
    for path in ("/api/server/restart", "/api/server/stop"):
        r = cli.post(path)
        assert r.status_code == 409, path
        assert "update is in progress" in r.get_json()["error"], path
    assert codes == []                              # nothing was scheduled
    # ...and once the update is done, both work again
    _mid_update(monkeypatch, "idle")
    assert cli.post("/api/server/restart").get_json()["action"] == "restart"
    assert codes == [42]


def test_a_panel_job_refuses_to_start_while_an_update_runs(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    _mid_update(monkeypatch, "restarting")
    r = cli.post("/api/panel/run", json={"action": "sync"})
    assert r.status_code == 409 and "update is in progress" in r.get_json()["error"]


def test_the_scheduler_skips_a_tick_while_an_update_runs():
    """The one exclusion with no route to drive: a timer that fires mid-update would start
    a job against changing code with nobody watching."""
    import inspect
    src = inspect.getsource(g.create_app)
    loop = src[src.index("def _scheduler_loop():"):]
    loop = loop[:loop.index("def ", 40)]
    assert "_update_busy()" in loop, "the scheduler tick must skip while an update runs"


def test_the_updates_own_restart_is_not_blocked_by_its_own_phase():
    """The exemption that keeps the whole thing from deadlocking on itself: the updater
    calls the exit scheduler directly, never through the route it just locked out."""
    import inspect
    src = inspect.getsource(g.create_app)
    body = src[src.index("def _restart():"):]
    assert "_schedule_server_exit(42)" in body[:900]
    assert "_update_busy" not in body[:900]


# ---- redaction ---------------------------------------------------------------

def test_the_status_route_redacts_host_paths(tmp_path, monkeypatch):
    """git and pip name real paths, and this payload is readable by any logged-in device
    on the LAN. The unredacted copy stays in the server's own log."""
    _idle_state(monkeypatch)
    cli = _client(tmp_path)
    g._set_update_state("failed", "error: cannot open %s/thing" % str(tmp_path))
    d = cli.get("/api/update/status").get_json()
    assert str(tmp_path) not in d["error"] and "cannot open" in d["error"]

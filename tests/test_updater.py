"""The auto-updater: the release check, the refusal matrix, and the apply sequence.

NOTHING here touches the network or runs a subprocess. `_git`, pip and the release fetch
are each substituted at their own seam, which is also the point of those seams existing:
this feature shells out and restarts a server, so every test drives it with the real code
paths and fake tools rather than the other way round.
"""
import json

import pytest

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

def _apply_ready(monkeypatch, branch="master", dirty="", supervised=True,
                 incoming=(), fetch_rc=0, fetch_out=""):
    """A machine where an update WOULD be allowed: supervised, on a clean master.

    `incoming` is what the pending release touches -- the paths `git diff HEAD..@{u}`
    would list -- which is what the untracked half of the dirty check is measured
    against. `fetch_rc`/`fetch_out` stand in for a fetch that can't reach the remote."""
    _idle_state(monkeypatch)
    monkeypatch.setattr(g, "_supervised", lambda: supervised)

    def _git(args, **k):
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, branch
        if args[:1] == ["status"]:
            return 0, dirty
        if args[:1] == ["fetch"]:
            return fetch_rc, fetch_out
        if args[:2] == ["diff", "--name-only"]:
            return 0, "\n".join(incoming)
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


def test_apply_refuses_a_tracked_edit_and_names_the_file(tmp_path, monkeypatch):
    """--ff-only would refuse anyway; refusing here says WHICH files are in the way.

    The untracked `notes.txt` alongside it is NOT named and NOT a reason: the update
    doesn't write that path, so it was never endangered."""
    _apply_ready(monkeypatch, dirty=" M moonglade_gallery.py\n?? notes.txt\n",
                 incoming=["moonglade_gallery.py"])
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert "uncommitted" in err and "moonglade_gallery.py" in err
    assert "notes.txt" not in err


def _started(monkeypatch):
    """Count the apply thread instead of running it -- 'it got as far as the pull' is
    what every proceed-case below is actually asserting."""
    seen = {"n": 0}
    monkeypatch.setattr(g.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None: type(
                            "T", (), {"start": lambda self_: seen.update(n=seen["n"] + 1)})())
    return seen


def test_an_untracked_file_the_update_never_touches_does_not_stop_it(tmp_path, monkeypatch):
    """A stray file is not an endangered file. Real installs collect them, so blocking on
    sight refuses every real machine forever."""
    _apply_ready(monkeypatch, dirty="?? notes.txt\n", incoming=["moonglade_gallery.py"])
    cli = _client(tmp_path)
    started = _started(monkeypatch)
    r = _apply(cli)
    assert r.status_code == 200 and started["n"] == 1


def test_the_live_case_an_untracked_boop_folder_does_not_stop_the_update(tmp_path, monkeypatch):
    """The FIRST live apply (v3.7.0 -> v3.7.1) was refused over a personal `boop/` the
    release had never heard of, with the untrue claim that the update would overwrite it.
    Nothing in the release lives under that path; the update proceeds."""
    _apply_ready(monkeypatch, dirty="?? boop/\n",
                 incoming=["moonglade_gallery.py", "static/app.js"])
    cli = _client(tmp_path)
    started = _started(monkeypatch)
    r = _apply(cli)
    assert r.status_code == 200 and started["n"] == 1


def test_an_untracked_file_at_an_incoming_path_refuses_and_names_it(tmp_path, monkeypatch):
    """The case the guard is FOR: git would refuse this pull too, so this says why in
    words, and honestly -- 'where the update needs to write', not 'your changes'."""
    _apply_ready(monkeypatch, dirty="?? new_module.py\n?? notes.txt\n",
                 incoming=["new_module.py", "moonglade_gallery.py"])
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert "untracked" in err and "new_module.py" in err
    assert "notes.txt" not in err            # the innocent one is not dragged in


def test_an_untracked_directory_containing_an_incoming_file_refuses(tmp_path, monkeypatch):
    """porcelain prints an untracked DIRECTORY as one line, `d/`, standing for everything
    beneath it -- so a plain equality check would miss the collision git itself refuses
    on. Prefix matching is what keeps this guard from being LOOSER than git's own rule."""
    _apply_ready(monkeypatch, dirty="?? d/\n", incoming=["d/x.py"])
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409 and "d/" in r.get_json()["error"]
    # ...and the mirror shape: an untracked FILE where the update needs a DIRECTORY
    _apply_ready(monkeypatch, dirty="?? d\n", incoming=["d/x.py"])
    r = _apply(_client(tmp_path))
    assert r.status_code == 409 and "untracked" in r.get_json()["error"]


def test_an_unreadable_upstream_refuses_rather_than_guessing(tmp_path, monkeypatch):
    """If the fetch can't say what is coming, whether the stray files are in the way is
    unknown -- and the safe unknown is 'no', in git's own words."""
    _apply_ready(monkeypatch, dirty="?? notes.txt\n", fetch_rc=1,
                 fetch_out="fatal: unable to access origin")
    cli = _client(tmp_path)
    r = _apply(cli)
    assert r.status_code == 409
    assert "unable to access origin" in r.get_json()["error"]


def test_a_clean_tree_never_pays_for_the_fetch(tmp_path, monkeypatch):
    """The common case is unchanged: with nothing stray there is nothing to compare, so
    the pre-check asks the network nothing and the pull does its own fetch as before."""
    calls = []
    _apply_ready(monkeypatch, dirty="")
    real = g._git
    monkeypatch.setattr(g, "_git", lambda args, **k: (calls.append(args[0]), real(args, **k))[1])
    cli = _client(tmp_path)
    _started(monkeypatch)
    assert _apply(cli).status_code == 200
    assert "fetch" not in calls


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


# ---- the refusal CONTRACT --------------------------------------------------
#
# Every test above pins one refusal's PROSE. This pins the machine-readable half the
# 2026-09-04 update modal actually dispatches on: `kind`, which decides whether the
# refusal is drawn gold ("busy" -- come back in a moment, nothing is wrong) or ruby
# ("failed" -- this install keeps refusing until something changes). Before `kind` the
# client string-matched those messages apart; a branch that forgets the field, or ships a
# third value, now silently falls through to the client's own default instead of the
# presentation the handoff drew. The prose is free to change; this contract is not.

def _refuse_no_csrf(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    return _client(tmp_path).post("/api/update/apply", json={"confirm": True})


def _refuse_no_confirm(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)
    return cli.post("/api/update/apply", json={"csrf": _csrf(cli)})


def _refuse_read_only(tmp_path, monkeypatch):
    import moonglade_backup as core
    monkeypatch.setattr(core, "READ_ONLY", True)
    _apply_ready(monkeypatch)
    return _apply(_client(tmp_path))


def _refuse_unsupervised(tmp_path, monkeypatch):
    _apply_ready(monkeypatch, supervised=False)
    return _apply(_client(tmp_path))


def _refuse_busy_job(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    app = create_app(tmp_path)
    app.extensions["mg_panel_job"].update(status="running", label="Sync now")
    return _apply(login_test_client(app))


def _refuse_off_master(tmp_path, monkeypatch):
    _apply_ready(monkeypatch, branch="feat/something")
    return _apply(_client(tmp_path))


def _refuse_dirty_tracked(tmp_path, monkeypatch):
    _apply_ready(monkeypatch, dirty=" M moonglade_gallery.py\n",
                 incoming=["moonglade_gallery.py"])
    return _apply(_client(tmp_path))


def _refuse_untracked_collision(tmp_path, monkeypatch):
    _apply_ready(monkeypatch, dirty="?? new_module.py\n",
                 incoming=["new_module.py", "moonglade_gallery.py"])
    return _apply(_client(tmp_path))


def _refuse_already_running(tmp_path, monkeypatch):
    _apply_ready(monkeypatch)
    cli = _client(tmp_path)                 # built BEFORE the Thread patch, as above
    _started(monkeypatch)
    assert _apply(cli).status_code == 200   # the first click takes the single-flight slot
    return _apply(cli)


@pytest.mark.parametrize("setup, expected", [
    (_refuse_no_csrf, "failed"),
    (_refuse_no_confirm, "failed"),
    (_refuse_read_only, "failed"),
    (_refuse_unsupervised, "failed"),
    (_refuse_busy_job, "busy"),
    (_refuse_off_master, "failed"),
    (_refuse_dirty_tracked, "failed"),
    (_refuse_untracked_collision, "failed"),
    (_refuse_already_running, "busy"),
], ids=["no-csrf", "no-confirm", "read-only", "unsupervised", "busy-job",
        "off-master", "dirty-tracked", "untracked-collision", "already-running"])
def test_every_refusal_carries_a_kind_the_modal_can_dispatch_on(
        tmp_path, monkeypatch, setup, expected):
    """Each refusal /api/update/apply can reach names itself as "busy" or "failed".

    COVERED, one case per refusal the route can be driven into with the fixtures this
    file already has: no CSRF, no confirm, READ_ONLY, unsupervised, a panel job in the
    way, off master, a tracked edit, an untracked file at an incoming path, and a second
    apply while one is already running.

    NOT COVERED here, because each needs a git seam that fails rather than answers and
    the fixtures above have no shape for one: the three "couldn't read this checkout"
    branches (rev-parse, status) and the unreadable-upstream branch, which
    test_an_unreadable_upstream_refuses_rather_than_guessing drives for its prose. All
    four are written "failed" alongside the ones below.

    "offline" is deliberately absent: it is not a server refusal at all. The client owns
    it (hooks/useControlPanel.js's classifyRefusal), for the case where no answer arrived."""
    r = setup(tmp_path, monkeypatch)
    assert r.status_code in (400, 409), "a refusal, not a start"
    d = r.get_json()
    assert d.get("error"), "a refusal always says why in words too"
    assert d.get("kind") in ("busy", "failed"), (
        "the modal dispatches on `kind` alone -- a missing or unknown value falls through "
        "to the client's default presentation. Got: %r" % (d.get("kind"),))
    assert d["kind"] == expected


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


def test_the_log_line_records_the_untracked_files_the_update_stepped_around(
        tmp_path, monkeypatch):
    """The guard's decision has to leave a trace. Without it, "it updated OVER my files"
    and "it updated BESIDE my files" look identical afterwards, and only one is a bug."""
    import moonglade_backup as core
    _apply_ready(monkeypatch, dirty="?? boop/\n?? notes.txt\n",
                 incoming=["moonglade_gallery.py"])
    cli = _client(tmp_path)
    monkeypatch.setattr(g, "_schedule_server_exit", lambda code: None)
    real_thread = g.threading.Thread

    def _inline(target=None, args=(), kwargs=None, daemon=None):
        return type("T", (), {"start": lambda self_: target(*args, **(kwargs or {}))})()
    monkeypatch.setattr(g.threading, "Thread", _inline)
    assert _apply(cli).status_code == 200
    monkeypatch.setattr(g.threading, "Thread", real_thread)
    rows = [j for j in core.read_jobs(tmp_path) if j.get("type") == "update"]
    assert len(rows) == 1 and rows[0]["label"] == "Updated Moonglade (ignored untracked: 2)"


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


# ---- the background cadence, and the guard that keeps it announce-only ---------
#
# Owner ruling 2026-09-04 (../moonglade-internal/DECISIONS.md, "The updater checks in the
# background"): the app re-checks roughly hourly and ANNOUNCES what it finds, reversing his
# own 2026-09-01 "no background tick anywhere". Clarified the same night, and the reason the
# guard below exists: he first read "full background" as the app updating itself -- "I don't
# want that". The chosen behaviour is check-and-announce ONLY. Applying is the Panel's Update
# button and its confirm, always.
#
# T0 is a REAL-looking epoch on purpose: the tick and the floor both measure `now` against a
# zero-initialized "last run", so a toy clock of 0/1/2 would read as "never due" and these
# tests would pass while measuring nothing.
T0 = 1800000000.0


def _fresh_tick(monkeypatch, at=0.0, floor_at=0.0):
    """Reset the background cadence's module singletons -- the same per-test isolation
    _fresh_cache gives the check cache."""
    monkeypatch.setattr(g, "_update_tick", {"at": at})
    monkeypatch.setattr(g, "_update_floor", {"at": floor_at})
    monkeypatch.setattr(g, "_update_notice",
                        {"version": "", "seq": 0, "at": 0.0, "payload": None})


def _counting_fetch(monkeypatch, releases):
    """fetch_releases, counted."""
    calls = {"n": 0}

    def _fetch(**k):
        calls["n"] += 1
        return list(releases)
    monkeypatch.setattr(g, "fetch_releases", _fetch)
    return calls


def test_the_background_tick_asks_about_once_an_hour(monkeypatch):
    """The whole budget this feature is allowed to spend: 24 GitHub requests a day against
    an unauthenticated allowance of 60 an HOUR. The clock is mocked -- nothing sleeps."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9")])
    assert g.run_update_tick("3.0.0", now=T0)["latest"] == "v9.9.9"
    assert calls["n"] == 1
    # ...and no tick in the next hour is due at all
    for minute in (1, 5, 30, 59):
        assert g.run_update_tick("3.0.0", now=T0 + minute * 60) is None
    assert calls["n"] == 1
    # An hour on it runs again -- and the 30-minute TTL has long expired by then, so that
    # run is a real request. One an hour, which is the number the budget was written for.
    assert g.run_update_tick("3.0.0", now=T0 + g.UPDATE_TICK_SECONDS)["latest"] == "v9.9.9"
    assert calls["n"] == 2
    assert g.UPDATE_TICK_SECONDS >= 2 * g.UPDATE_CHECK_TTL   # the cache can never outlive a tick


def test_the_tick_reuses_a_recent_panel_answer_rather_than_re_asking(monkeypatch):
    """The tick is deliberately NOT forced: a Panel open five minutes ago already has the
    answer, and asking again for it is a request spent on nothing."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9")])
    g._update_cache.update(at=T0 - 60, ttl=g.UPDATE_CHECK_TTL,
                           payload={"current": "3.0.0", "latest": "v9.9.9",
                                    "behind": True, "checked_at": T0 - 60})
    assert g.run_update_tick("3.0.0", now=T0)["latest"] == "v9.9.9"
    assert calls["n"] == 0                       # the cache answered


def test_a_new_release_is_announced_once_not_on_every_tick(monkeypatch):
    """A transition, not a heartbeat. The hourly check finds the same release every hour
    once one is out; announcing that every hour is how you teach someone to ignore it."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9", "The Ninth")])
    assert g.run_update_tick("3.0.0", now=T0) is not None
    first = g.update_notice()
    assert first["latest"] == "v9.9.9" and first["behind"] is True
    assert first["title"] == "The Ninth"
    seq = first["seq"]
    for hour in (1, 2, 3):                       # three more hours of finding the same thing
        _fresh_cache(monkeypatch)                # ...each one really asking
        g.run_update_tick("3.0.0", now=T0 + hour * g.UPDATE_TICK_SECONDS)
    assert g.update_notice()["seq"] == seq, "the same release must not re-announce"
    _fresh_cache(monkeypatch)                    # a HIGHER release IS a new event
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.10.0")])
    g.run_update_tick("3.0.0", now=T0 + 4 * g.UPDATE_TICK_SECONDS)
    assert g.update_notice()["latest"] == "v9.10.0"
    assert g.update_notice()["seq"] == seq + 1


def test_the_announcement_clears_once_the_release_is_no_longer_newer(monkeypatch):
    """After the update lands, the stamp must stop offering it."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9")])
    g.run_update_tick("3.0.0", now=T0)
    assert g.update_notice()["latest"] == "v9.9.9"
    _fresh_cache(monkeypatch)
    assert g.run_update_tick("9.9.9", now=T0 + g.UPDATE_TICK_SECONDS)["behind"] is False
    assert g.update_notice() is None


def test_a_failed_background_check_announces_nothing(monkeypatch):
    """Offline is not news. check_for_update answers behind:false with a reason attached,
    and the announcement stays empty rather than carrying an error to a corner toast."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)

    def _boom(**k):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(g, "fetch_releases", _boom)
    assert "getaddrinfo failed" in g.run_update_tick("3.0.0", now=T0)["error"]
    assert g.update_notice() is None


def test_a_blip_does_not_take_a_standing_announcement_off_every_tab(monkeypatch):
    """The other half of "offline is not news", and the one that bites once a release IS
    out: a failed check is the ABSENCE of an answer, not the answer "you are current".

    It arrives as behind:false with a reason attached, so clearing on `behind` alone meant
    one GitHub blip pulled the banner off every open tab and bumped the seq -- and the next
    good tick an hour later announced the SAME version as if it were new. Two toasts for
    one release, against a ruling that says one."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9", "The Ninth")])
    g.run_update_tick("3.0.0", now=T0)
    seq = g.update_notice()["seq"]

    def _boom(**k):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(g, "fetch_releases", _boom)
    _fresh_cache(monkeypatch)                    # the blip really goes out and really fails
    blip = g.run_update_tick("3.0.0", now=T0 + g.UPDATE_TICK_SECONDS)
    assert "getaddrinfo failed" in blip["error"] and blip["behind"] is False
    after = g.update_notice()
    assert after is not None, "a blip must not take the standing announcement down"
    assert after["latest"] == "v9.9.9" and after["title"] == "The Ninth"
    assert after["seq"] == seq, "and must not move the counter the client dedupes on"

    # ...so the good tick behind it is not a second announcement of the same release.
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9", "The Ninth")])
    _fresh_cache(monkeypatch)
    assert g.run_update_tick("3.0.0", now=T0 + 2 * g.UPDATE_TICK_SECONDS)["behind"] is True
    assert g.update_notice()["seq"] == seq, "the same release must not re-announce"

    # A GENUINE up-to-date answer -- no error, the update was applied -- still clears.
    assert g.note_update_transition({"current": "9.9.9", "latest": "v9.9.9", "behind": False},
                                    now=T0 + 3 * g.UPDATE_TICK_SECONDS) is False
    assert g.update_notice() is None


def test_a_panel_open_gets_a_fresh_answer_past_the_cache(monkeypatch):
    """The Panel is where a person goes to ASK, so it bypasses the 30-minute TTL the rest
    of the app reads -- otherwise "it checks when you open it" can be half an hour stale."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9")])
    assert g.check_for_update_fresh("3.0.0", now=T0)["latest"] == "v9.9.9"
    assert calls["n"] == 1
    # the cache is minutes old and answers a normal caller...
    assert g.check_for_update("3.0.0", now=T0 + 300)["latest"] == "v9.9.9"
    assert calls["n"] == 1
    # ...but a Panel open past the floor asks again
    assert g.check_for_update_fresh("3.0.0", now=T0 + 300)["latest"] == "v9.9.9"
    assert calls["n"] == 2


def test_rapid_panel_opens_cost_github_nothing(monkeypatch):
    """The floor. Opening and closing the Panel is free -- it must not become a way to
    spend the hourly allowance a keystroke at a time."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9")])
    g.check_for_update_fresh("3.0.0", now=T0)
    for second in (1, 5, 20, 59):
        assert g.check_for_update_fresh("3.0.0", now=T0 + second)["latest"] == "v9.9.9"
    assert calls["n"] == 1, "inside the floor a Panel open reads the cache"
    g.check_for_update_fresh("3.0.0", now=T0 + g.UPDATE_PANEL_FLOOR)
    assert calls["n"] == 2
    assert g.UPDATE_PANEL_FLOOR < g.UPDATE_CHECK_TTL          # ...and it IS the short one


def test_the_check_route_asks_fresh_only_when_the_panel_says_so(tmp_path, monkeypatch):
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9")])
    cli = _client(tmp_path)
    assert cli.get("/api/update/check").get_json()["latest"] == "v9.9.9"
    assert calls["n"] == 1
    assert cli.get("/api/update/check").get_json()["latest"] == "v9.9.9"
    assert calls["n"] == 1                       # a plain re-read inside the TTL, as before
    g._update_floor["at"] -= (g.UPDATE_PANEL_FLOOR + 1)
    assert cli.get("/api/update/check?fresh=1").get_json()["latest"] == "v9.9.9"
    assert calls["n"] == 2                       # the Panel open is the one that goes back


def test_the_jobs_poll_carries_the_announcement_and_never_fetches(tmp_path, monkeypatch):
    """How the news reaches a person who is nowhere near the Control Panel: it rides the
    one server-truth poll every open tab already runs. That poll must never ask GitHub
    itself -- it reports what the hourly tick found."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    calls = _counting_fetch(monkeypatch, [_rel("v9.9.9", "The Ninth")])
    cli = _client(tmp_path)
    assert cli.get("/api/jobs").get_json()["update"] is None      # nothing found yet
    assert calls["n"] == 0
    g.run_update_tick("3.0.0", now=T0)
    assert calls["n"] == 1
    for _ in range(5):
        d = cli.get("/api/jobs").get_json()
        assert d["update"]["latest"] == "v9.9.9"
        assert d["update"]["title"] == "The Ninth"
        assert "jobs" in d                        # the card's own payload is untouched
    assert calls["n"] == 1, "the jobs poll must never reach GitHub"


# ONE set, read by both guards below. They were written with different ones -- the wired
# closure's omitted _git, subprocess and api_update_apply -- which meant the function the
# scheduler ACTUALLY calls every minute was held to a looser rule than the functions it
# calls. A guard with a hole in it is worse than no guard, because it reads as cover.
FORBIDDEN_APPLY_NAMES = {"run_update", "_panel_run", "_schedule_server_exit",
                         "api_update_apply", "_git", "subprocess", "_set_update_state"}


def test_the_background_path_has_no_route_into_applying_an_update():
    """THE GUARD. The owner rejected auto-apply in the same conversation that asked for the
    background check -- "I don't want that". So the tick, the announcement and the fresh
    Panel check are walked for anything that could start one. NAMES, not text: a docstring
    in these functions legitimately says the words run_update and /api/update/apply.

    STRING CONSTANTS COUNT TOO, and this is why: a walk that collects only Name and
    Attribute nodes sees `run_update()` but not `getattr(g, "run_update")()` or
    `globals()["run_update"]()` -- the name arrives as a string and the guard waves it
    through. So any string literal EQUAL to a forbidden name is flagged as well. Equality,
    not substring, is the whole trick: the docstrings above say "run_update" inside a
    sentence (saying it is how the rule is stated), and a sentence is never equal to it."""
    import ast
    import inspect
    import textwrap
    forbidden = FORBIDDEN_APPLY_NAMES
    for name in ("run_update_tick", "note_update_transition", "update_notice",
                 "check_for_update_fresh", "check_for_update"):
        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(g, name))))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in forbidden:
                    used.add(node.value)          # a name reached by string is still reached
        assert not (used & forbidden), \
            "%s can reach %s -- the background path must only ANNOUNCE" % (
                name, sorted(used & forbidden))


def test_the_scheduler_tick_only_announces():
    """The same guard where the cadence actually fires: the closure the scheduler loop
    calls every minute. Walked as source because it is a closure inside create_app.

    THE SAME forbidden set as its sibling above (FORBIDDEN_APPLY_NAMES) -- this one used to
    carry a shorter one, so the function the scheduler really runs was allowed _git,
    subprocess and api_update_apply that the functions it calls were not.

    String constants are flagged as well as names, for the reason the sibling's docstring
    gives: `getattr(g, "run_update")()` puts the name in a Constant, where a Name/Attribute
    walk cannot see it."""
    import ast
    import inspect
    import textwrap
    src = inspect.getsource(g.create_app)
    fn = src[src.index("def _update_check_tick():"):]
    fn = fn[:fn.index("def ", 40)]
    assert "run_update_tick" in fn, "the hourly check must actually be wired to the loop"
    # NAMES and real strings, never the raw text: this function's own docstring says the
    # words /api/update/apply and run_update, because saying them is how the rule is stated.
    tree = ast.parse(textwrap.dedent(fn))
    body = tree.body[0]
    if (body.body and isinstance(body.body[0], ast.Expr)
            and isinstance(body.body[0].value, ast.Constant)):
        del body.body[0]                          # the docstring is prose, not a call
    forbidden = FORBIDDEN_APPLY_NAMES
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "update/apply" not in node.value, "the scheduler tick must not call apply"
            if node.value in forbidden:
                used.add(node.value)              # reached by string is still reached
    assert not (used & forbidden), \
        "the scheduler tick can reach %s -- it must only ANNOUNCE" % sorted(used & forbidden)

    # ...and it rides the suite's own network gate, so create_app() in a test never asks
    # GitHub anything (the same reason the live-mirror watcher and contest sweep ride it).
    # Sampled ONCE at create_app time, not re-read every minute: this tick lives in a daemon
    # thread that outlives the test that made it, and conftest sets the flag per test -- a
    # re-reading gate could fire in the gap between two of them and hit the real API.
    assert "if not _bg_release_check" in fn
    assert '_bg_release_check = os.environ.get("MOONGLADE_DISABLE_WATCH") != "1"' in src


def test_a_tick_that_finds_a_release_does_not_touch_the_updater(monkeypatch):
    """Behaviour, not just shape: the real tick against a release it has never seen, with
    every apply-side entry point booby-trapped."""
    _fresh_cache(monkeypatch)
    _fresh_tick(monkeypatch)
    _idle_state(monkeypatch)

    def _never(*a, **k):
        raise AssertionError("the background check applied an update")
    monkeypatch.setattr(g, "run_update", _never)
    monkeypatch.setattr(g, "_git", _never)
    monkeypatch.setattr(g, "_schedule_server_exit", _never)
    monkeypatch.setattr(g, "fetch_releases", lambda **k: [_rel("v9.9.9")])
    assert g.run_update_tick("3.0.0", now=T0)["behind"] is True
    assert g.update_notice()["latest"] == "v9.9.9"
    assert g.update_state()["phase"] == "idle"        # nothing ever started

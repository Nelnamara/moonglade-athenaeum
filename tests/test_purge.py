"""The destructive local-purge path — previously untested, and the scariest code in
the app (it deletes files). Covers purge_media_local (quarantine vs hard-delete) and
the gallery /delete-tasks-bulk route (cloud delete is mocked; we assert local side
effects + that the cloud call fires task-level)."""
import pixai_gallery as g
from pixai_gallery import (CATALOG_FIELDS, save_catalog, load_catalog,
                           purge_media_local, create_app)

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows, files):
    save_catalog(tmp_path / "catalog.db", rows)
    img = tmp_path / "images"
    img.mkdir(exist_ok=True)
    for name, data in files.items():
        (img / name).write_bytes(data)
    return tmp_path / "catalog.db"


def test_purge_quarantines_file_and_clears_row(tmp_path):
    db = _seed(tmp_path, [_row(media_id="55", filename="55.png")], {"55.png": b"DATA"})
    thumb = tmp_path / "gallery" / "thumbs"
    thumb.mkdir(parents=True)
    (thumb / "55.jpg").write_bytes(b"t")

    moved = purge_media_local(tmp_path, thumb, db, "55", "55.png")

    assert moved == tmp_path / g.DELETED_DIRNAME / "55.png"
    assert moved.exists() and moved.read_bytes() == b"DATA"     # file preserved, just moved
    assert not (tmp_path / "images" / "55.png").exists()        # gone from its old spot
    assert not (thumb / "55.jpg").exists()                      # thumb (regenerable) removed
    assert load_catalog(db) == []                               # catalog row cleared


def test_purge_hard_delete_mode(tmp_path):
    db = _seed(tmp_path, [_row(media_id="9", filename="9.png")], {"9.png": b"x"})
    moved = purge_media_local(tmp_path, tmp_path / "t", db, "9", "9.png", quarantine=False)
    assert moved is None
    assert not (tmp_path / "images" / "9.png").exists()
    assert not (tmp_path / g.DELETED_DIRNAME).exists()          # nothing quarantined
    assert load_catalog(db) == []


def test_purge_missing_file_is_safe(tmp_path):
    db = _seed(tmp_path, [_row(media_id="404", filename="404.png")], {})  # no file on disk
    moved = purge_media_local(tmp_path, tmp_path / "t", db, "404", "404.png")
    assert moved is None
    assert load_catalog(db) == []                              # row still cleared, no crash


def test_quarantined_file_is_invisible_to_resolution(tmp_path):
    # A file already sitting in _deleted/ must not be found as a live media file.
    db = _seed(tmp_path, [], {})
    qdir = tmp_path / g.DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "77.png").write_bytes(b"old")
    assert g.find_image_file(tmp_path, "77", "77.png") is None
    assert g.find_files_for_media_id(tmp_path, "77") == []


def test_delete_tasks_bulk_route_quarantines_and_calls_cloud(tmp_path, monkeypatch):
    import pixai_gallery_backup as core
    db = _seed(tmp_path, [
        _row(media_id="100", task_id="T1", filename="100.png"),
        _row(media_id="101", task_id="T1", filename="101.png"),   # same task, NOT selected
        _row(media_id="200", task_id="", filename="200.png", source="local"),
    ], {"100.png": b"a", "101.png": b"b", "200.png": b"c"})

    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: calls.append(tid))

    client = login_client(tmp_path)
    r = client.post("/delete-tasks-bulk", data={"media_ids": ["100", "200"], "back": "/"})
    assert "bulkdel=started" in r.headers["Location"]            # async now: kicks off + reports to the card

    import time
    for _ in range(200):                                         # wait for the background delete thread
        if not load_catalog(db):
            break
        time.sleep(0.02)

    assert calls == ["T1"]                                       # cloud delete fired once, task-level
    deleted = tmp_path / g.DELETED_DIRNAME
    # selecting 100 purges its WHOLE task (100 + 101); 200 is a local-only import
    for name in ("100.png", "101.png", "200.png"):
        assert (deleted / name).exists()
    assert {r["media_id"] for r in load_catalog(db)} == set()    # all three rows cleared


def test_bulk_delete_async_logs_a_job_that_completes(tmp_path, monkeypatch):
    """The async delete registers a 'delete' job that shows in /api/jobs and reaches 'done'."""
    import time
    import pixai_gallery_backup as core
    _seed(tmp_path, [_row(media_id="a1", task_id="TA", filename="a1.png")], {"a1.png": b"x"})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: None)

    client = login_client(tmp_path)
    client.post("/delete-tasks-bulk", data={"media_ids": ["a1"], "back": "/"})

    job = None
    for _ in range(200):
        jobs = client.get("/api/jobs").get_json()["jobs"]
        job = next((j for j in jobs if j.get("type") == "delete"), None)
        if job and job["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert job is not None and job["status"] == "done" and job["total"] == 1


def test_bulk_delete_cloud_is_localhost_only(tmp_path, monkeypatch):
    """A LAN request must NOT be able to delete from the owner's PixAI account.

    Before the global front-door hook existed, this route's own defense-in-depth
    check redirected back to the gallery with a `delerr` banner; now the global
    hook (_enforce_front_door(), see pixai_gallery.py) denies the request before
    this route's body ever runs, redirecting to /login instead -- the
    security-relevant invariants below (nothing fired, nothing deleted) are
    unchanged."""
    import time
    import pixai_gallery_backup as core
    db = _seed(tmp_path, [_row(media_id="z1", task_id="TZ", filename="z1.png")], {"z1.png": b"x"})
    fired = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.append(tid))

    client = create_app(tmp_path).test_client()
    r = client.post("/delete-tasks-bulk", data={"media_ids": ["z1"], "back": "/"},
                    environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "/login" in r.headers["Location"]        # refused before the handler ran, not a delete
    time.sleep(0.1)                                  # give any wrongly-spawned thread a beat
    assert fired == []                               # nothing deleted from the cloud
    assert {x["media_id"] for x in load_catalog(db)} == {"z1"}   # row intact


def test_bulk_delete_cloud_refuses_authenticated_lan_session(tmp_path, monkeypatch):
    """A logged-in LAN account must NOT be able to trigger /delete-tasks-bulk --
    same trust tier as /api/branding/shortcut and destructive Panel actions: this
    destroys on the owner's real PixAI account, irreversibly. A LAN login unlocks
    browsing and spending the owner's credits, not deleting the owner's cloud
    generations. Regression test: this route's own _is_local_request() re-check
    was dropped during the LAN-auth conversion pass (0fd8cee) and never replaced
    -- the global front-door hook alone let ANY logged-in LAN session through,
    unlike its siblings test_panel.py::test_destructive_action_refuses_authenticated_lan_session
    and test_branding.py::test_shortcut_refuses_authenticated_lan_session, which
    already covered this shape. Flagged by adversarial review and fixed 2026-07-19."""
    import time
    import pixai_gallery_backup as core
    db = _seed(tmp_path, [_row(media_id="z2", task_id="TZ2", filename="z2.png")], {"z2.png": b"x"})
    fired = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.append(tid))

    client = login_client(tmp_path)
    LAN = "203.0.113.5"
    # Prove the session really is authenticated (it can reach an ordinary
    # authorized-LAN route) before proving it still can't reach this one.
    assert client.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = client.post("/delete-tasks-bulk", data={"media_ids": ["z2"], "back": "/"},
                    environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "delerr=" in r.headers["Location"]        # refused by the route itself (delerr banner),
    assert "/login" not in r.headers["Location"]     # NOT the front door (would be a /login redirect)
    time.sleep(0.1)                                   # give any wrongly-spawned thread a beat
    assert fired == []                                # nothing deleted from the cloud
    assert {x["media_id"] for x in load_catalog(db)} == {"z2"}   # row intact

    # The same account, from the actual local machine, still works (this isn't
    # broken for the owner -- just not exposed to remote LAN sessions).
    r2 = client.post("/delete-tasks-bulk", data={"media_ids": ["z2"], "back": "/"})
    assert "bulkdel=started" in r2.headers["Location"]

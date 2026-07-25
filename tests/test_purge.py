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


# ---------------------------------------------------------------------------
# /api/delete-preview -- the blast radius of "Delete from PixAI", BEFORE it fires.
# The dialog said "this deletes the whole TASK" in prose but never showed which
# images that meant, so the one irreversible action in the app was also the only one
# whose real scope the user could not see. These tests pin the two properties that
# make the preview worth having: it must resolve the selection exactly the way
# delete_tasks_bulk does (a preview that disagrees with the action is worse than
# none), and its counts must stay exact even when the thumbnail strip is capped.
# ---------------------------------------------------------------------------

def test_delete_preview_lists_the_siblings_the_delete_would_take(tmp_path):
    """One selected image of a four-image batch: the preview has to come back with all
    four, flagging which one was actually picked, plus the local-only import that has
    no task to delete. Mirrors test_delete_tasks_bulk_route_quarantines_and_calls_cloud
    above -- same seed shape, same resolution, no cloud call."""
    _seed(tmp_path, [
        _row(media_id="100", task_id="T1", filename="100.png"),
        _row(media_id="101", task_id="T1", filename="101.png"),   # same task, NOT selected
        _row(media_id="102", task_id="T1", filename="102.png"),   # same task, NOT selected
        _row(media_id="103", task_id="T1", filename="103.png", is_video="1"),
        _row(media_id="200", task_id="", filename="200.png", source="local"),
    ], {})

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview",
                       json={"media_ids": ["100", "200"]}).get_json()

    assert body["totals"] == {"selected": 2, "tasks": 1, "media": 5,
                              "unselected": 3, "local_only": 1}, (
        "the preview's totals do not describe what /delete-tasks-bulk would actually "
        "take: one task's four images plus one local-only purge")
    assert len(body["tasks"]) == 1 and body["tasks"][0]["task_id"] == "T1"
    shown = body["tasks"][0]["media"]
    assert [m["media_id"] for m in shown] == ["100", "101", "102", "103"], (
        "the three unselected batch siblings are missing from the preview -- they are "
        "exactly the images the user cannot otherwise see they are about to lose")
    assert [m["selected"] for m in shown] == [True, False, False, False]
    assert shown[3]["is_video"] is True
    assert [m["media_id"] for m in body["local_only"]] == ["200"]


def test_delete_preview_counts_stay_exact_when_the_strip_is_capped(tmp_path):
    """A selection spanning more tasks than the modal can reasonably render is
    truncated for DISPLAY only. The counts are what the user reads to decide, so they
    must describe the whole selection, not the visible slice -- a preview that
    undercounts an irreversible delete is worse than no preview at all."""
    cap = g.DELETE_PREVIEW_TASK_CAP
    rows = []
    for i in range(cap + 3):
        rows.append(_row(media_id="s{}".format(i), task_id="T{}".format(i),
                         filename="s{}.png".format(i)))
        rows.append(_row(media_id="x{}".format(i), task_id="T{}".format(i),
                         filename="x{}.png".format(i)))   # unselected sibling
    _seed(tmp_path, rows, {})

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={
        "media_ids": ["s{}".format(i) for i in range(cap + 3)]}).get_json()

    assert body["truncated"] is True
    assert len(body["tasks"]) == cap                      # display slice, capped
    assert body["totals"]["tasks"] == cap + 3             # counts, exact
    assert body["totals"]["media"] == (cap + 3) * 2
    assert body["totals"]["unselected"] == cap + 3


def test_delete_preview_does_not_scan_the_catalog_once_per_selected_task(tmp_path, monkeypatch):
    """`catalog` indexes media_id (PRIMARY KEY), created_at, model_name, rating and
    batch -- but NOT task_id, so every `WHERE task_id=?` is a full table scan, and the
    preview needs each selected task's whole membership. Measured on a 36,000-row
    catalog: one query per task costs 216ms for 24 tasks and 8.6s for 800, all of it
    inside the request the dialog is waiting on; the same 800 tasks batched into chunked
    `IN` passes cost 38ms. Counting statements rather than milliseconds so a fast disk
    can't make this vacuous and a slow one can't make it flaky."""
    rows = []
    for i in range(30):                      # deliberately > DELETE_PREVIEW_TASK_CAP
        rows.append(_row(media_id="q{}".format(i), task_id="Q{}".format(i),
                         filename="q{}.png".format(i)))
        rows.append(_row(media_id="r{}".format(i), task_id="Q{}".format(i),
                         filename="r{}.png".format(i)))
    _seed(tmp_path, rows, {})
    client = login_client(tmp_path)

    seen = []
    real_connect = g._connect

    class _Spy:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *a):
            seen.append(sql)
            return self._con.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._con, name)

    monkeypatch.setattr(g, "_connect", lambda *a, **k: _Spy(real_connect(*a, **k)))
    del seen[:]                              # ignore anything the login/render did
    body = client.post("/api/delete-preview", json={
        "media_ids": ["q{}".format(i) for i in range(30)]}).get_json()

    assert body["totals"]["media"] == 60      # the work really was done
    scans = [s for s in seen if "task_id=?" in s or "task_id IN" in s]
    assert len(scans) <= 3, (
        "the preview issued {} task_id lookups for 30 selected tasks -- task_id is "
        "unindexed, so that is one full table scan each".format(len(scans)))


def test_delete_preview_refuses_an_authenticated_lan_session(tmp_path):
    """LOCALHOST, mirroring the action it previews: the preview of an irreversible
    cloud delete is not a lower trust tier than the delete. Same shape as
    test_bulk_delete_cloud_refuses_authenticated_lan_session below -- prove the
    session really is authorized first, then prove this route still refuses it."""
    _seed(tmp_path, [_row(media_id="p1", task_id="TP", filename="p1.png")], {})
    client = login_client(tmp_path)
    LAN = "203.0.113.5"
    assert client.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = client.post("/api/delete-preview", json={"media_ids": ["p1"]},
                    environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403


def test_cloud_delete_confirm_renders_the_preview_and_keeps_the_typed_gate(tmp_path):
    """The dialog is the whole point of the endpoint above, so pin the wiring: the
    gallery must actually fetch the preview, and the typed DELETE gate must survive
    the change -- making a consequence visible is not a reason to loosen the guard in
    front of it."""
    _seed(tmp_path, [_row(media_id="1", task_id="T", filename="1.png")], {})
    html = login_client(tmp_path).get("/").get_data(as_text=True)
    assert "/api/delete-preview" in html, (
        "the gallery never asks for the blast radius, so the confirm cannot show it")
    assert "cd-modal" in html
    assert "Type DELETE to confirm" in html, (
        "the typed DELETE gate vanished from the cloud-delete flow")


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

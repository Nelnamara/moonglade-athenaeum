"""The destructive local-purge path — previously untested, and the scariest code in
the app (it deletes files). Covers purge_media_local (quarantine vs hard-delete) and
the gallery /api/delete-tasks route (cloud delete is mocked; we assert local side
effects + that the cloud call fires task-level). The classic /delete-tasks-bulk form
route died in the 2026-08-08 classic cut; the JSON twin runs the same
_start_bulk_delete engine, so the behavior pinned here is unchanged."""
import contextlib

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import (CATALOG_FIELDS, save_catalog, load_catalog,
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


def test_purge_keeps_the_row_when_the_quarantine_move_fails(tmp_path, monkeypatch):
    """The data-loss case. The move can genuinely fail -- an antivirus or sync client
    holding the file open for a moment, or a library on a different volume from
    out_dir, which makes img.replace(dest) a cross-device rename (OSError on Windows).
    The file then stays exactly where it was, so dropping its catalog row anyway
    strands it: invisible in the gallery AND absent from _deleted/, which is the only
    place the trash panel looks. wiki/Deleting.md promises local deletes are
    recoverable; an orphan is the one shape that cannot be recovered."""
    db = _seed(tmp_path, [_row(media_id="66", filename="66.png")], {"66.png": b"KEEP"})
    thumb = tmp_path / "gallery" / "thumbs"
    thumb.mkdir(parents=True)
    (thumb / "66.jpg").write_bytes(b"t")

    def _cross_device(self, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(g.Path, "replace", _cross_device)

    with pytest.raises(OSError):
        purge_media_local(tmp_path, thumb, db, "66", "66.png")

    assert (tmp_path / "images" / "66.png").read_bytes() == b"KEEP", "the file moved anyway"
    assert [r["media_id"] for r in load_catalog(db)] == ["66"], (
        "the catalog row was destroyed for a file that never left its original path -- "
        "it is now an orphan no restore path can find")


def test_purge_keeps_the_row_when_the_hard_delete_fails(tmp_path, monkeypatch):
    """Same contract on the hard-delete branch: a file the OS refused to unlink is
    still there, so the row that points at it has to stay too."""
    db = _seed(tmp_path, [_row(media_id="67", filename="67.png")], {"67.png": b"KEEP"})

    def _denied(self, **kw):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(g.Path, "unlink", _denied)

    with pytest.raises(OSError):
        purge_media_local(tmp_path, tmp_path / "t", db, "67", "67.png", quarantine=False)

    assert (tmp_path / "images" / "67.png").exists()
    assert [r["media_id"] for r in load_catalog(db)] == ["67"]


def test_quarantined_file_is_invisible_to_resolution(tmp_path):
    # A file already sitting in _deleted/ must not be found as a live media file.
    db = _seed(tmp_path, [], {})
    qdir = tmp_path / g.DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "77.png").write_bytes(b"old")
    assert g.find_image_file(tmp_path, "77", "77.png") is None
    assert g.find_files_for_media_id(tmp_path, "77") == []


def test_delete_tasks_bulk_route_quarantines_and_calls_cloud(tmp_path, monkeypatch, pixai):
    import moonglade_backup as core
    db = _seed(tmp_path, [
        _row(media_id="100", task_id="T1", filename="100.png"),
        _row(media_id="101", task_id="T1", filename="101.png"),   # same task, NOT selected
        _row(media_id="200", task_id="", filename="200.png", source="local"),
    ], {"100.png": b"a", "101.png": b"b", "200.png": b"c"})

    calls = []
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: calls.append(tid))

    client = login_client(tmp_path)
    r = client.post("/api/delete-tasks", json={"media_ids": ["100", "200"]})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True and body["job_id"]  # async: kicks off + reports to the card
    assert body["tasks"] == 1 and body["local_only"] == 1        # one task + one local-only import

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
    assert {row["media_id"] for row in load_catalog(db)} == set()    # all three rows cleared


def test_bulk_delete_keeps_going_when_one_local_purge_fails(tmp_path, monkeypatch, pixai):
    """One unmovable file must not abandon every task queued behind it. The cloud
    deletes have already fired and cannot be taken back by the time the local purge
    runs, so a loop that dies on the first OSError leaves the remaining tasks gone
    from PixAI but still in the local catalog -- the exact cloud/catalog drift this
    route exists to prevent, and silent, because the job card is the only place it
    would ever show."""
    import time
    import moonglade_backup as core
    db = _seed(tmp_path, [
        _row(media_id="300", task_id="TA", filename="300.png"),
        _row(media_id="400", task_id="TB", filename="400.png"),
    ], {"300.png": b"a", "400.png": b"b"})

    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: None)

    real_replace = g.Path.replace

    def _one_bad_file(self, target):
        if self.name == "300.png":                 # TA is processed first (task ids sort)
            raise OSError(18, "Invalid cross-device link")
        return real_replace(self, target)

    monkeypatch.setattr(g.Path, "replace", _one_bad_file)

    client = login_client(tmp_path)
    client.post("/api/delete-tasks", json={"media_ids": ["300", "400"]})

    job = None
    for _ in range(200):
        jobs = client.get("/api/jobs").get_json()["jobs"]
        job = next((j for j in jobs if j.get("type") == "delete"), None)
        if job and job["status"] in ("done", "failed"):
            break
        time.sleep(0.02)

    assert job is not None and job["status"] == "failed", (
        "a purge that failed was reported as a clean run")
    assert (tmp_path / g.DELETED_DIRNAME / "400.png").exists(), (
        "the second task was abandoned after the first one's file would not move")
    assert {r["media_id"] for r in load_catalog(db)} == {"300"}, (
        "the row for the file still on disk should survive, and only that one")


def test_bulk_delete_async_logs_a_job_that_completes(tmp_path, monkeypatch, pixai):
    """The async delete registers a 'delete' job that shows in /api/jobs and reaches 'done'."""
    import time
    import moonglade_backup as core
    _seed(tmp_path, [_row(media_id="a1", task_id="TA", filename="a1.png")], {"a1.png": b"x"})
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: None)

    client = login_client(tmp_path)
    client.post("/api/delete-tasks", json={"media_ids": ["a1"]})

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
    real_catalog = g.catalog

    class _Spy:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *a):
            seen.append(sql)
            return self._con.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._con, name)

    # Re-pinned 2026-08-23: the preview's SQL moved out of the route into the
    # delete_preview_rows catalog verb, which opens the catalog through catalog(),
    # so that is where the spy goes now. Spying on the old _connect would still
    # PASS -- seeing zero statements and counting zero scans -- which is the one
    # outcome this test must never be able to report as a success.
    @contextlib.contextmanager
    def _spy_catalog(*a, **k):
        with real_catalog(*a, **k) as con:
            yield _Spy(con)

    monkeypatch.setattr(g, "catalog", _spy_catalog)
    del seen[:]                              # ignore anything the login/render did
    body = client.post("/api/delete-preview", json={
        "media_ids": ["q{}".format(i) for i in range(30)]}).get_json()

    assert body["totals"]["media"] == 60      # the work really was done
    assert seen, "the spy saw no SQL at all -- it is watching the wrong seam"
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


def test_bulk_delete_cloud_is_localhost_only(tmp_path, monkeypatch, pixai):
    """A LAN request must NOT be able to delete from the owner's PixAI account.

    An unauthenticated request never reaches the route body at all: the global
    front-door hook (_enforce_front_door(), see moonglade_gallery.py) denies it
    first, answering 401 on the /api/ JSON tier -- the security-relevant
    invariants below (nothing fired, nothing deleted) are unchanged from when
    this covered the classic /delete-tasks-bulk form route."""
    import time
    import moonglade_backup as core
    db = _seed(tmp_path, [_row(media_id="z1", task_id="TZ", filename="z1.png")], {"z1.png": b"x"})
    fired = []
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.append(tid))

    client = create_app(tmp_path).test_client()
    r = client.post("/api/delete-tasks", json={"media_ids": ["z1"]},
                    environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 401                     # refused before the handler ran, not a delete
    time.sleep(0.1)                                  # give any wrongly-spawned thread a beat
    assert fired == []                               # nothing deleted from the cloud
    assert {x["media_id"] for x in load_catalog(db)} == {"z1"}   # row intact


def test_bulk_delete_cloud_refuses_authenticated_lan_session(tmp_path, monkeypatch, pixai):
    """A logged-in LAN account must NOT be able to trigger /api/delete-tasks --
    same trust tier as /api/branding/shortcut and destructive Panel actions: this
    destroys on the owner's real PixAI account, irreversibly. A LAN login unlocks
    browsing and spending the owner's credits, not deleting the owner's cloud
    generations. Regression test: the classic route's own _is_local_request()
    re-check was dropped during the LAN-auth conversion pass (0fd8cee) and never
    replaced -- the global front-door hook alone let ANY logged-in LAN session
    through, unlike its siblings test_panel.py::test_destructive_action_refuses_authenticated_lan_session
    and test_branding.py::test_shortcut_refuses_authenticated_lan_session, which
    already covered this shape. Flagged by adversarial review and fixed 2026-07-19;
    ported to the surviving JSON route when the classic form route died 2026-08-08."""
    import time
    import moonglade_backup as core
    db = _seed(tmp_path, [_row(media_id="z2", task_id="TZ2", filename="z2.png")], {"z2.png": b"x"})
    fired = []
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.append(tid))

    client = login_client(tmp_path)
    LAN = "203.0.113.5"
    # Prove the session really is authenticated (it can reach an ordinary
    # authorized-LAN route) before proving it still can't reach this one.
    assert client.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = client.post("/api/delete-tasks", json={"media_ids": ["z2"]},
                    environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403                       # refused by the route itself (its own
    assert "localhost" in (r.get_json() or {}).get("error", "")  # _is_local_request re-check),
    # NOT the front door (that would be a 401 "authentication required")
    time.sleep(0.1)                                   # give any wrongly-spawned thread a beat
    assert fired == []                                # nothing deleted from the cloud
    assert {x["media_id"] for x in load_catalog(db)} == {"z2"}   # row intact

    # The same account, from the actual local machine, still works (this isn't
    # broken for the owner -- just not exposed to remote LAN sessions).
    r2 = client.post("/api/delete-tasks", json={"media_ids": ["z2"]})
    body2 = r2.get_json()
    assert r2.status_code == 200 and body2["ok"] is True and body2["job_id"]


# ---------------------------------------------------------------------------
# /api/delete-preview -- THE LIVE CHECK (owner, 2026-09-07): "one live read per
# selected task, capped at 40; above that the preview says it is an estimate, and the
# delete still keeps back what the live read finds."
#
# The preview was 100% local until now, and the local catalog cannot know about an
# image the owner deleted on PixAI's own website. The DELETE has always known -- it
# reads every task before it acts (_rows_the_bulk_purge_must_keep) and keeps those rows
# back -- so the preview over-reported the blast radius of the one action it exists to
# describe exactly. These pin the read, the cap, and the fail-soft direction.
# ---------------------------------------------------------------------------

_LIVE_GONE = "2026-09-07T09:00:00.000Z"


def _live_task(tid, members, gone=()):
    """A getTaskById answer: a batch whose deleted members carry `deletedAt` and keep
    their place, which is what a read-only probe of the owner's own tasks found on
    2026-09-06 (moonglade_backup.py, DELETING ONE IMAGE)."""
    return {"id": tid, "status": "completed", "outputs": {
        "mediaId": "GRID-" + tid,
        "batch": [({"mediaId": m, "deletedAt": _LIVE_GONE} if m in gone
                   else {"mediaId": m}) for m in members]}}


def _fake_session(monkeypatch):
    """A session object the preview can hold but never actually use: every read below is
    monkeypatched at core.task_detail_gql, so nothing reaches the network."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())


def test_delete_preview_reads_each_selected_task_back_from_pixai_once(tmp_path, monkeypatch):
    """One read per task, no more, and the answer changes the numbers: the member PixAI
    already dropped moves out of "will be deleted" and into its own count."""
    _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png"),
        _row(media_id="a2", task_id="T1", filename="a2.png"),
        _row(media_id="a3", task_id="T1", filename="a3.png"),
        _row(media_id="b1", task_id="T2", filename="b1.png"),
        _row(media_id="b2", task_id="T2", filename="b2.png"),
    ], {})
    _fake_session(monkeypatch)

    reads = []
    live = {"T1": _live_task("T1", ["a1", "a2", "a3"], gone=("a3",)),
            "T2": _live_task("T2", ["b1", "b2"])}

    def _read(sess, tid, **k):
        reads.append(str(tid))
        return live[str(tid)]

    monkeypatch.setattr(core, "task_detail_gql", _read)

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview",
                       json={"media_ids": ["a1", "b1"]}).get_json()

    assert sorted(reads) == ["T1", "T2"], (
        "expected exactly one live read per selected task, got {}".format(reads))
    assert body["estimate"] is False
    assert body["live_checked"] == 2 and body["unverified"] == 0
    assert body["already_gone"] == 1, (
        "the member carrying deletedAt is not reported as already gone on PixAI")
    # `totals` keeps its old meaning -- the whole membership -- so nothing that reads it
    # today is surprised; the modal subtracts already_gone for "will be deleted".
    assert body["totals"]["media"] == 5
    marks = {m["media_id"]: m["already_gone"]
             for tk in body["tasks"] for m in tk["media"]}
    assert marks == {"a1": False, "a2": False, "a3": True, "b1": False, "b2": False}
    assert [tk["unverified"] for tk in body["tasks"]] == [False, False]


def test_delete_preview_counts_a_row_the_catalog_already_marked_gone(tmp_path, monkeypatch):
    """The delete keeps rows back from TWO sources -- the live read AND the
    cloud_deleted_at the catalog was stamped with the last time anything read this task.
    A preview that used only the first would still disagree with the delete."""
    _seed(tmp_path, [
        _row(media_id="c1", task_id="T9", filename="c1.png"),
        _row(media_id="c2", task_id="T9", filename="c2.png",
             cloud_deleted_at=_LIVE_GONE),
    ], {})
    _fake_session(monkeypatch)
    # The live read no longer lists c2 as deleted; the catalog's own marker still stands
    # on its own, exactly as it does at delete time.
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda sess, tid, **k: _live_task("T9", ["c1", "c2"]))

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={"media_ids": ["c1"]}).get_json()

    assert body["already_gone"] == 1
    marks = {m["media_id"]: m["already_gone"] for m in body["tasks"][0]["media"]}
    assert marks == {"c1": False, "c2": True}


def test_delete_preview_over_the_cap_reads_nothing_and_says_it_is_an_estimate(
        tmp_path, monkeypatch):
    """Above DELETE_PREVIEW_LIVE_CAP the preview does not call PixAI at all. The counts
    are the library's, the response says so, and the delete still checks every task
    before it acts."""
    n = g.DELETE_PREVIEW_LIVE_CAP + 1
    rows = [_row(media_id="e{}".format(i), task_id="E{}".format(i),
                 filename="e{}.png".format(i)) for i in range(n)]
    _seed(tmp_path, rows, {})
    _fake_session(monkeypatch)

    reads = []
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda sess, tid, **k: reads.append(tid))

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={
        "media_ids": ["e{}".format(i) for i in range(n)]}).get_json()

    assert reads == [], (
        "{} tasks is over the cap of {} -- the preview must not call PixAI at all, and "
        "it made {} reads".format(n, g.DELETE_PREVIEW_LIVE_CAP, len(reads)))
    assert body["estimate"] is True
    assert body["live_checked"] == 0 and body["unverified"] == 0
    assert body["already_gone"] == 0
    assert body["totals"]["tasks"] == n and body["totals"]["media"] == n


def test_delete_preview_at_exactly_the_cap_still_reads(tmp_path, monkeypatch):
    """The cap is inclusive: 40 tasks is checked, 41 is an estimate. Pinned so the
    boundary cannot drift by one without somebody noticing."""
    n = g.DELETE_PREVIEW_LIVE_CAP
    rows = [_row(media_id="f{}".format(i), task_id="F{}".format(i),
                 filename="f{}.png".format(i)) for i in range(n)]
    _seed(tmp_path, rows, {})
    _fake_session(monkeypatch)

    reads = []

    def _read(sess, tid, **k):
        reads.append(str(tid))
        return _live_task(str(tid), [str(tid).replace("F", "f")])

    monkeypatch.setattr(core, "task_detail_gql", _read)

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={
        "media_ids": ["f{}".format(i) for i in range(n)]}).get_json()

    assert len(reads) == n and body["estimate"] is False
    assert body["live_checked"] == n and body["unverified"] == 0


def test_delete_preview_counts_a_task_whose_read_failed_from_the_catalog(
        tmp_path, monkeypatch):
    """FAIL SOFT, in the safe direction. A read that could not be made leaves the task on
    its local rows -- so the preview can only ever over-report an irreversible delete,
    never quietly shrink it -- and says out loud that it could not be checked."""
    _seed(tmp_path, [
        _row(media_id="g1", task_id="G1", filename="g1.png"),
        _row(media_id="g2", task_id="G1", filename="g2.png"),
        _row(media_id="h1", task_id="H1", filename="h1.png"),
        _row(media_id="h2", task_id="H1", filename="h2.png"),
    ], {})
    _fake_session(monkeypatch)

    def _read(sess, tid, **k):
        if str(tid) == "G1":
            raise core.PixAIError("network error reading task")
        return _live_task("H1", ["h1", "h2"], gone=("h2",))

    monkeypatch.setattr(core, "task_detail_gql", _read)

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview",
                       json={"media_ids": ["g1", "h1"]}).get_json()

    assert body["unverified"] == 1 and body["live_checked"] == 1
    assert body["already_gone"] == 1, (
        "the task that DID answer must still be counted exactly -- one blip does not "
        "throw the whole preview back to guessing")
    assert body["totals"]["media"] == 4          # the failed task keeps all its rows
    by_task = {tk["task_id"]: tk for tk in body["tasks"]}
    assert by_task["G1"]["unverified"] is True
    assert by_task["H1"]["unverified"] is False
    assert all(m["already_gone"] is False for m in by_task["G1"]["media"]), (
        "a task nobody could read must not have any of its images written off as gone")


def test_delete_preview_reads_nothing_when_there_is_no_session_to_read_with(
        tmp_path, monkeypatch):
    """No credentials, bad config, PixAI unreachable at the session seam: every task is
    unverified and the preview answers from the catalog exactly as it did before the live
    check existed. It must not 500 the confirm dialog."""
    _seed(tmp_path, [
        _row(media_id="i1", task_id="I1", filename="i1.png"),
        _row(media_id="i2", task_id="I1", filename="i2.png"),
    ], {})

    def _no_session(*a, **k):
        raise core.PixAIError("No API key found.")

    monkeypatch.setattr(core, "_make_session", _no_session)

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={"media_ids": ["i1"]}).get_json()

    assert body["live_checked"] == 0 and body["unverified"] == 1
    assert body["already_gone"] == 0 and body["estimate"] is False
    assert body["totals"]["media"] == 2


def test_delete_preview_writes_down_what_pixai_said_so_the_delete_keeps_it(
        tmp_path, monkeypatch):
    """The preview's answer is PERSISTED, not just displayed (2026-09-07, refining the
    same day's "the preview mutates nothing" note).

    The dialog promises, by name, that an image PixAI has already deleted stays in the
    backup because this copy is the last one anywhere. The delete makes its OWN read a
    moment later, and that read can fail where this one worked -- a blip, a 401, a 5xx
    past its retries. When it does, _rows_the_bulk_purge_must_keep falls back to the
    catalog alone; if nothing wrote the preview's answer there, the fallback finds no
    marker and purges exactly the row the dialog named. So the preview stamps
    cloud_deleted_at when it sees deletedAt, and the promise survives the second read."""
    import time
    db = _seed(tmp_path, [
        _row(media_id="k1", task_id="K1", filename="k1.png"),
        _row(media_id="k2", task_id="K1", filename="k2.png"),
        _row(media_id="k3", task_id="K1", filename="k3.png"),
    ], {"k1.png": b"a", "k2.png": b"b", "k3.png": b"c"})
    _fake_session(monkeypatch)
    monkeypatch.setattr(core, "task_detail_gql", lambda sess, tid, **k: _live_task(
        "K1", ["k1", "k2", "k3"], gone=("k3",)))

    client = login_client(tmp_path)
    body = client.post("/api/delete-preview", json={"media_ids": ["k1"]}).get_json()
    assert body["already_gone"] == 1

    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["k3"]["cloud_deleted_at"] == _LIVE_GONE, (
        "the preview saw PixAI's deletedAt and threw it away -- the delete's own read is "
        "now the only thing standing between that promise and the purge")
    assert not rows["k1"]["cloud_deleted_at"] and not rows["k2"]["cloud_deleted_at"], (
        "only the member PixAI really dropped may be stamped")

    # The delete, with its own live read failing where the preview's succeeded.
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: None)

    def _blip(sess, tid, **k):
        raise core.PixAIError("network error reading task")

    monkeypatch.setattr(core, "task_detail_gql", _blip)

    assert client.post("/api/delete-tasks",
                       json={"media_ids": ["k1"]}).get_json()["ok"] is True
    job = None
    for _ in range(300):
        jobs = client.get("/api/jobs").get_json()["jobs"]
        job = next((j for j in jobs if j.get("type") == "delete"), None)
        if job and job["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert job is not None and job["status"] == "done", job

    assert (tmp_path / "images" / "k3.png").exists(), (
        "the file the modal promised would stay was quarantined by the delete")
    assert {r["media_id"] for r in load_catalog(db)} == {"k3"}, (
        "the row the modal promised would stay was purged with the task")
    assert job.get("kept_media") == ["k3"]

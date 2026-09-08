"""Per-image cloud delete: the finer-grained partner to the task-level "Delete from PixAI".

The two delete paths were separated as a safety net and stay separated: LOCAL moves the file
to `_deleted/` and drops the catalog row, and PixAI still has the image, so a later sync
brings it back. CLOUD is irreversible on their side and asks for DELETE to be typed. Every
test here is about a property of that split rather than about the happy path, because the
happy path is one mutation call and the dangerous parts are everything around it.
"""
import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import moonglade_backup as core  # noqa: E402
from moonglade_gallery import CATALOG_FIELDS, save_catalog  # noqa: E402

from tests.conftest import login_client  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _cli(tmp_path, rows, monkeypatch=None):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path)


def _session_stub(token_val):
    """Exact arity, deliberately: `lambda *a, **k` here masked a real bug for a whole build.

    core._make_session takes a REQUIRED positional, and the route omitted it -- so every
    click raised TypeError, the route's broad `except Exception` turned that into an HTTP
    200 error body, and the feature never once fired. Seven green tests said otherwise
    because their stub swallowed the missing argument. A stub that accepts anything cannot
    catch a caller that passes the wrong thing.
    """
    return object()


def _batch(tmp_path):
    """One task with three images, plus an unrelated local import."""
    return [
        _row(media_id="a", task_id="T1", filename="a.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="b", task_id="T1", filename="b.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="c", task_id="T1", filename="c.png", created_at="2025-01-01T00:00:00"),
        _row(media_id="z", task_id="", filename="z.png", source="local",
             created_at="2025-01-02T00:00:00"),
    ]


GONE = "2026-09-06T11:22:33.000Z"


def _live_task(*members):
    """What PixAI answers about the batch above. `members` are (media_id, deleted?) pairs.

    The route has to READ this before it deletes anything: which mutation PixAI accepts
    depends on how many of a task's images PixAI still has, and the local catalog cannot
    know that -- a sibling deleted from PixAI's own website leaves the local row untouched.
    """
    batch = []
    for mid, deleted in members:
        entry = {"extra": {}, "mediaId": mid, "seed": "1"}
        if deleted:
            entry["deletedAt"] = GONE
        batch.append(entry)
    return {"id": "T1", "status": "completed",
            "outputs": {"mediaId": "GRID-COMBINED", "seed": "1", "batch": batch}}


def _lone_task(media_id):
    """A task that made ONE image: no batch array at all, the picture IS outputs.mediaId."""
    return {"id": "T1", "status": "completed", "outputs": {"mediaId": media_id, "seed": "1"}}


def _reads(monkeypatch, task):
    """Answer the live read with `task` and count how often it was asked."""
    seen = []
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, tid, **k: seen.append(str(tid)) or task)
    return seen


def _all_live():
    return _live_task(("a", False), ("b", False), ("c", False))


def test_it_deletes_only_the_named_image_and_leaves_its_siblings(tmp_path, monkeypatch):
    """The whole point. The task-level delete takes every image of a batch; this must take
    exactly one and leave the rest of the task alone, on PixAI and in the catalog.

    PixAI still has all three images here, so this is the one case `deleteBatchMedia` was
    ever right for -- the live read is what establishes that."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())
    monkeypatch.setattr(core, "delete_batch_media_gql",
                        lambda s, tid, mid: seen.update(task=tid, media=mid))
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert d.get("ok") is True
    assert seen == {"task": "T1", "media": "b"}, "the wrong image (or task) was deleted"

    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        left = sorted(r[0] for r in con.execute("SELECT media_id FROM catalog"))
    assert left == ["a", "c", "z"], "a sibling was taken with it"
    # Local file quarantined, not destroyed -- the same recoverable path the local delete uses.
    assert not (tmp_path / "b.png").exists()
    assert (tmp_path / "_deleted" / "b.png").exists()


def test_a_failed_cloud_delete_leaves_the_local_copy_alone(tmp_path, monkeypatch):
    """Order is load-bearing: cloud first, local second. If the cloud call fails there must
    be nothing to clean up locally and the image is still there to try again. The reverse
    order leaves a hole in the catalog for an image PixAI still has."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())

    def boom(s, tid, mid):
        raise core.PixAIError("HTTP 500 from PixAI")

    monkeypatch.setattr(core, "delete_batch_media_gql", boom)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert "500" in (d.get("error") or "")
    assert (tmp_path / "b.png").exists(), "the local file was purged despite the cloud failing"
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        assert con.execute("SELECT COUNT(*) FROM catalog WHERE media_id='b'").fetchone()[0] == 1


def test_a_failed_local_purge_comes_back_as_an_error_body(tmp_path, monkeypatch):
    """The mirror of the test above, on the other side of the cloud call. By the time the
    local purge runs the delete on PixAI is already done and irreversible, so a purge that
    fails (the file locked, or _deleted/ on a different volume than the library) has to be
    reported through this route's own JSON contract -- the client reads `error` and says so.
    An unhandled 500 tells the user nothing while a row for an image PixAI no longer has
    quietly stays in the catalog."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())
    monkeypatch.setattr(core, "delete_batch_media_gql", lambda s, tid, mid: None)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    def _cross_device(self, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(pathlib.Path, "replace", _cross_device)

    r = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True})
    assert r.status_code == 200, "a local-purge failure escaped as a raw server error"
    d = r.get_json()
    assert d.get("ok") is not True and d.get("error"), (
        "the route claimed success for a purge that never happened")
    assert (tmp_path / "b.png").exists()
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM catalog WHERE media_id='b'").fetchone()[0] == 1, (
            "the row was cleared for a file still sitting in the library")


# ---------------------------------------------------------------------------
# Two phases: say what will happen, then do exactly that (2026-09-06)
# ---------------------------------------------------------------------------

def _nothing_deletes(monkeypatch):
    """Both delete mutations wired to fail the test if either one is reached."""
    monkeypatch.setattr(core, "delete_batch_media_gql", lambda *a, **k: pytest.fail(
        "the per-image mutation fired"))
    monkeypatch.setattr(core, "delete_task_gql", lambda *a, **k: pytest.fail(
        "the whole-task mutation fired"))


def test_the_preview_says_what_will_happen_and_deletes_nothing(tmp_path, monkeypatch):
    """The dialog's words have to come from PixAI's own answer about this task, not from a
    count of local rows -- the local catalog cannot see a sibling deleted from the website.
    So the button asks first, with confirm false, and gets a plan back with nothing done."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    reads = _reads(monkeypatch, _live_task(("a", True), ("b", False), ("c", False)))
    _nothing_deletes(monkeypatch)
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image",
                 json={"media_id": "b", "confirm": False}).get_json()
    assert d["plan"] == "per-image"
    assert d["live_siblings"] == 1, "it counted the sibling PixAI already deleted"
    assert d["local_rows"] == ["b"], "the preview named the wrong local rows"
    assert "1 other image" in d["message"], d["message"]
    assert reads == ["T1"], "the preview did not read the live task"
    assert d.get("ok") is not True
    assert (tmp_path / "b.png").exists() and not (tmp_path / "_deleted").exists()


def test_the_preview_names_every_local_row_a_whole_task_delete_takes(tmp_path, monkeypatch):
    """The honest half of the whole-task branch: it removes the generation record on PixAI,
    so every local row of that task goes with it -- and the dialog has to say so BEFORE the
    user types DELETE, not discover it afterwards."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _live_task(("a", True), ("b", False), ("c", True)))
    _nothing_deletes(monkeypatch)
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": False}).get_json()
    assert d["plan"] == "whole-task"
    assert d["local_rows"] == ["b"], (
        "rows for images PixAI already deleted were listed for quarantine: {}".format(
            d["local_rows"]))
    assert "whole generation" in d["message"], d["message"]


def test_a_confirm_carrying_a_stale_plan_is_refused(tmp_path, monkeypatch):
    """The dialog said "one image, two siblings stay". Between reading that and typing
    DELETE, the siblings were deleted from PixAI's website -- so the same click would now
    take the whole generation. Refuse: the user agreed to the other thing."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _live_task(("a", True), ("b", False), ("c", True)))
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image",
                 json={"media_id": "b", "confirm": True, "plan": "per-image"}).get_json()
    assert d.get("ok") is not True
    assert "changed" in (d.get("error") or "").lower(), d
    assert (tmp_path / "b.png").exists(), "it purged locally on a delete that never fired"


def test_the_whole_task_branch_keeps_what_pixai_already_deleted(tmp_path, monkeypatch):
    """The rule that decides which local files survive. PixAI removes the generation record,
    so every image of it that PixAI still had is gone there -- those rows are quarantined
    here too, so the two sides do not drift. But the images PixAI had ALREADY deleted are
    only still anywhere because THIS library holds them, and nothing about this delete
    changes that. Those rows and their files stay."""
    fired = {}
    monkeypatch.setattr(core, "_make_session", _session_stub)
    # PixAI's copy of this task: `a` was deleted earlier, `c` is the one image still there,
    # and `b` is a local row PixAI's copy no longer lists at all.
    _reads(monkeypatch, _live_task(("a", True), ("c", False)))
    monkeypatch.setattr(core, "delete_task_gql",
                        lambda s, tid: fired.update(task=tid))
    monkeypatch.setattr(core, "delete_batch_media_gql", lambda *a, **k: pytest.fail(
        "the per-image mutation fired on the last live image of a batch"))
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image",
                 json={"media_id": "c", "confirm": True, "plan": "whole-task"}).get_json()
    assert d.get("ok") is True, d
    assert fired == {"task": "T1"}
    assert sorted(d["local_rows"]) == ["b", "c"]

    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        left = sorted(r[0] for r in con.execute("SELECT media_id FROM catalog"))
    assert left == ["a", "z"], "the row PixAI had already deleted was taken too"
    assert (tmp_path / "a.png").exists(), (
        "the only surviving copy of an image PixAI already deleted was quarantined")
    assert (tmp_path / "_deleted" / "b.png").exists()
    assert (tmp_path / "_deleted" / "c.png").exists()


def test_every_image_pixai_already_deleted_is_kept_back_not_just_one(tmp_path, monkeypatch):
    """How MANY files a whole-generation delete keeps back is however many the owner had
    already deleted on PixAI -- there is nothing in the rule that stops at one, and a
    four-picture batch you culled down to one on PixAI's website keeps three.

    Pinned because the docs said "one local file is deliberately kept back" and the number
    is not one: a promise about your own files has to match what the code does."""
    fired = {}
    monkeypatch.setattr(core, "_make_session", _session_stub)
    # PixAI kept `c` only; `a` and `b` were both deleted from its website earlier.
    _reads(monkeypatch, _live_task(("a", True), ("b", True), ("c", False)))
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.update(task=tid))
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image",
                 json={"media_id": "c", "confirm": False}).get_json()
    assert d["plan"] == "whole-task"
    assert d["local_rows"] == ["c"], d["local_rows"]
    assert "2 images of this generation you already deleted" in d["message"], d["message"]

    d = cli.post("/api/delete-image",
                 json={"media_id": "c", "confirm": True, "plan": "whole-task"}).get_json()
    assert d.get("ok") is True and fired == {"task": "T1"}
    assert (tmp_path / "a.png").exists() and (tmp_path / "b.png").exists(), (
        "only one of the two last-copies-anywhere was kept back")
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        left = sorted(r[0] for r in con.execute("SELECT media_id FROM catalog"))
    assert left == ["a", "b", "z"]


# ---------------------------------------------------------------------------
# It shows in the Activity window, like a bulk delete does (owner's walk 2026-09-07)
# ---------------------------------------------------------------------------

def _delete_jobs(tmp_path):
    """Every `delete` row in the job log, newest first."""
    return [j for j in core.read_jobs(tmp_path) if j.get("type") == "delete"]


def test_a_confirmed_delete_writes_one_activity_row(tmp_path, monkeypatch):
    """Owner's walk 2026-09-07: "single delete did NOT show in the Activity tracker".

    A bulk delete has written a job row since it existed (_start_bulk_delete's
    "bulkdel-<hex>"); this one wrote nothing at all, so an image deleted from PixAI left no
    trace anywhere in the app -- the one window that says what happened to this library was
    blind to the most destructive thing in it, depending only on which button was used.

    ONE row, and it says what actually happened in the plan's own words. It carries the media
    id so the row can show the thumbnail, and it is NOT marked scheduled, because the owner
    pressed a button -- which is what makes it toast like every other job he starts.
    """
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())
    monkeypatch.setattr(core, "delete_batch_media_gql", lambda s, tid, mid: None)
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    assert cli.post("/api/delete-image",
                    json={"media_id": "b", "confirm": True}).get_json().get("ok") is True

    rows = _delete_jobs(tmp_path)
    assert len(rows) == 1, "the tracker got {} rows for one delete".format(len(rows))
    j = rows[0]
    assert j["job_id"].startswith("del-"), j["job_id"]
    assert j["status"] == "done"
    assert j["label"] == "Deleted 1 image from PixAI", j["label"]
    assert j["media_ids"] == ["b"], "the row cannot show which image went"
    assert not j.get("scheduled"), "a delete he pressed was logged as an automatic job"


def test_a_whole_task_delete_says_so_on_its_row(tmp_path, monkeypatch):
    """The other branch, and the row must not claim the smaller one. Deleting the last image
    of a generation removes the whole generation record on PixAI -- the same fact the dialog
    warns about before the click has to be the fact the tracker records after it."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _lone_task("b"))
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: None)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    assert cli.post("/api/delete-image",
                    json={"media_id": "b", "confirm": True}).get_json().get("ok") is True
    j = _delete_jobs(tmp_path)[0]
    assert j["status"] == "done"
    assert j["label"] == "Deleted the whole generation from PixAI (last image)", j["label"]


def test_the_preview_writes_no_activity_row(tmp_path, monkeypatch):
    """Opening the dialog is not an event. The preview deletes nothing, so a row for it would
    be an entry in the tracker for something that did not happen -- and one per dialog-open,
    since the dialog can be opened and closed all day."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": False}).get_json()
    assert d["plan"] == "per-image"
    assert _delete_jobs(tmp_path) == [], "the tracker logged a delete that never happened"


def test_a_refused_delete_is_logged_as_a_failure_that_names_the_refusal(tmp_path, monkeypatch):
    """A refusal is an outcome, not a non-event: he pressed the button, the image is still on
    PixAI, and the window has to say why rather than showing nothing at all. `failed`, not
    `done` -- a green row would read as "deleted"."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _live_task(("a", False), ("b", True), ("c", False)))
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert "already deleted" in (d.get("error") or "").lower(), d

    j = _delete_jobs(tmp_path)[0]
    assert j["status"] == "failed"
    assert "already deleted on PixAI" in j["label"], j["label"]
    assert "already deleted on PixAI" in (j.get("error") or ""), j


def test_a_cloud_delete_that_errors_is_logged_as_a_failure(tmp_path, monkeypatch):
    """The delete PixAI refused mid-flight -- a 500, an expired token, READ_ONLY. The image is
    still there and the local copy was never touched, and the tracker says so with the error
    line rather than staying silent about the click."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _all_live())

    def boom(s, tid, mid):
        raise core.PixAIError("HTTP 500 from PixAI")

    monkeypatch.setattr(core, "delete_batch_media_gql", boom)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    cli.post("/api/delete-image", json={"media_id": "b", "confirm": True})
    j = _delete_jobs(tmp_path)[0]
    assert j["status"] == "failed" and "500" in (j.get("error") or ""), j
    assert j["label"] == "Delete from PixAI failed", j["label"]


def test_a_lone_image_uses_the_whole_task_mutation(tmp_path, monkeypatch):
    """The bug this whole change exists for. A task that made ONE image has no batch for
    `deleteBatchMedia` to delete from, and PixAI answers 403 -- so the button had never once
    worked on a single-image generation. PixAI's own site sends the whole-task mutation."""
    fired = {}
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _lone_task("b"))
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: fired.update(task=tid))
    monkeypatch.setattr(core, "delete_batch_media_gql", lambda *a, **k: pytest.fail(
        "the per-image mutation fired on a task with no batch -- PixAI answers 403"))
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert d.get("ok") is True, d
    assert fired == {"task": "T1"}
    assert (tmp_path / "_deleted" / "b.png").exists()


def test_a_read_that_fails_deletes_nothing(tmp_path, monkeypatch):
    """Fail-safe direction. The read fails soft to None on a network blip, and the answer to
    "I could not see this task" must never be a delete -- least of all the whole-task one,
    which would take a whole generation off a dropped packet."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, None)
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert d.get("ok") is not True
    assert "nothing was deleted" in (d.get("error") or "").lower(), d
    assert (tmp_path / "b.png").exists()
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        assert con.execute("SELECT COUNT(*) FROM catalog WHERE media_id='b'").fetchone()[0] == 1


def test_an_image_pixai_already_deleted_says_so_and_marks_the_row(tmp_path, monkeypatch):
    """Nothing to delete, so nothing is sent. The row is marked instead, so the library
    stops presenting the image as one PixAI still holds -- and the local file stays, because
    it is now the only copy anywhere."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _live_task(("a", False), ("b", True), ("c", False)))
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert "already deleted" in (d.get("error") or "").lower(), d
    assert (tmp_path / "b.png").exists(), "it quarantined the only copy left"
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        stamp = con.execute(
            "SELECT cloud_deleted_at FROM catalog WHERE media_id='b'").fetchone()[0]
    assert stamp == GONE, "the row still claims PixAI has this image"


def test_a_preview_read_marks_every_sibling_pixai_has_already_deleted(tmp_path, monkeypatch):
    """The marker is written by a read the app was ALREADY making. Asking what deleting `b`
    would do reads the whole task back, and PixAI's answer says it dropped `a` -- so `a`'s
    row records that here, on the preview, with no second network call.

    It cannot wait for `--backfill-full-meta`: that pass only re-fetches a row missing its
    prompt or model detail, so a row that already has both is never revisited and the marker
    would never be set at all in the ordinary case.

    Nothing else moves: no mutation fires, no file is touched, and the rows of the images
    PixAI still has keep their blank marker rather than being swept along with it."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, _live_task(("a", True), ("b", False), ("c", False)))
    _nothing_deletes(monkeypatch)
    for f in ("a.png", "b.png", "c.png"):
        (tmp_path / f).write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": False}).get_json()
    assert d["plan"] == "per-image", d

    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        marks = dict(con.execute("SELECT media_id, cloud_deleted_at FROM catalog"))
    assert marks["a"] == GONE, (
        "a sibling PixAI has deleted still looks live in the catalog after the app read it")
    assert marks["b"] == "" and marks["c"] == "" and marks["z"] == "", (
        "a row PixAI still has was marked as deleted: {}".format(marks))
    for f in ("a.png", "b.png", "c.png"):
        assert (tmp_path / f).exists(), "the preview touched a file"
    assert not (tmp_path / "_deleted").exists()


def test_a_video_clip_is_refused_rather_than_guessed_at(tmp_path, monkeypatch):
    """Video outputs hang off outputs.videos and neither mutation is known to be the right
    one for them. Say where to do it instead of firing a destructive guess."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    _reads(monkeypatch, {"id": "T1", "outputs": {"mediaId": "poster", "videos": [
        {"mediaId": "b", "seed": "1"}]}})
    _nothing_deletes(monkeypatch)
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))

    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    assert "video" in (d.get("error") or "").lower(), d
    assert (tmp_path / "b.png").exists()


def test_it_refuses_without_the_confirm_flag(tmp_path, monkeypatch):
    """The typed-DELETE prompt is the client's half of the gate. A route that acted without
    the flag would make that prompt decorative -- anything that could reach the endpoint
    could delete."""
    called = []
    monkeypatch.setattr(core, "_make_session", _session_stub)
    monkeypatch.setattr(core, "delete_batch_media_gql",
                        lambda s, t, m: called.append((t, m)))
    cli = _cli(tmp_path, _batch(tmp_path))
    r = cli.post("/api/delete-image", json={"media_id": "b"})
    assert r.status_code == 400
    assert called == [], "it deleted without confirmation"


def test_an_imported_file_says_so_instead_of_erroring(tmp_path, monkeypatch):
    """A local import has no PixAI task behind it, so there is nothing on their side to
    delete. Naming the control that DOES apply beats surfacing a mutation error about a
    blank task id."""
    called = []
    monkeypatch.setattr(core, "_make_session", _session_stub)
    monkeypatch.setattr(core, "delete_batch_media_gql",
                        lambda s, t, m: called.append((t, m)))
    cli = _cli(tmp_path, _batch(tmp_path))
    d = cli.post("/api/delete-image", json={"media_id": "z", "confirm": True}).get_json()
    assert "imported" in (d.get("error") or "").lower()
    assert called == [], "it tried to delete an image PixAI never had"


def test_read_only_still_blocks_it(tmp_path, monkeypatch):
    """READ_ONLY is a promise the Trust & Safety page makes about every account-mutating
    path. The primitive checks it before the network call; this proves the route inherits
    that rather than reaching PixAI some other way."""
    monkeypatch.setattr(core, "_make_session", _session_stub)
    # READ_ONLY is a module-level global resolved at import, not read from _cfg
    # per call -- patching the config dict would leave the guard switched off.
    monkeypatch.setattr(core, "READ_ONLY", True)
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: pytest.fail("READ_ONLY did not stop the mutation"))
    (tmp_path / "b.png").write_bytes(b"x")
    cli = _cli(tmp_path, _batch(tmp_path))
    d = cli.post("/api/delete-image", json={"media_id": "b", "confirm": True}).get_json()
    # The READ_ONLY message specifically -- "an error came back" would also pass if the
    # route had failed for some unrelated reason and the guard were switched off entirely.
    assert "READ_ONLY" in (d.get("error") or ""), (
        "blocked, but not by the read-only guard: {!r}".format(d.get("error")))
    assert (tmp_path / "b.png").exists(), "it purged locally on a blocked cloud delete"


def test_the_cloud_delete_is_single_attempt(monkeypatch):
    """A destructive mutation must never be retried, and this one nearly was.

    delete_batch_media_gql routes through gql_adhoc, which defaults to retries=3 and re-POSTs
    on a RequestException or a 429/5xx. Its own docstring promised SINGLE ATTEMPT the whole
    time -- the promise was real, the implementation was not. The danger is specific: a read
    timeout can arrive AFTER PixAI has already processed the delete, so a retry re-fires a
    destructive mutation against a batch that has already changed underneath it.

    delete_task_gql gets this right by hand-rolling its own single session.post; this proves
    the finer-grained one gets it right through the shared helper instead of by accident.
    """
    import requests

    attempts = []

    class _Session:
        def post(self, *a, **k):
            attempts.append(1)
            raise requests.exceptions.ConnectionError("network blip")

    monkeypatch.setattr(core, "READ_ONLY", False)
    with pytest.raises(Exception):
        core.delete_batch_media_gql(_Session(), "T1", "m1")
    assert len(attempts) == 1, (
        "the delete was POSTed {} times -- a destructive mutation must fire once"
        .format(len(attempts)))


def test_the_batch_size_reaches_the_delete_dialog(tmp_path):
    """Ported from the classic detail page (cut 2026-08-08): the server-rendered dialog
    carried `data-siblings="3"` so "the other 2 images stay" was a real number rather than
    a claim the page could not back up. The dialog markup is React's now and out of a Flask
    client's reach, but the NUMBER still has to come from the server -- /api/next/detail is
    the surviving route that feeds the Details view, and its `siblings` field is what the
    dialog words the batch warning from. An import (blank task_id) reports 0, which is how
    the client knows there is no batch to warn about at all."""
    cli = _cli(tmp_path, _batch(tmp_path))
    d = cli.get("/api/next/detail/b").get_json()
    assert d.get("siblings") == 3, "the batch size never reached the client"
    assert cli.get("/api/next/detail/z").get_json().get("siblings") == 0, (
        "an imported file claimed batch siblings it does not have")


def test_the_cloud_delete_is_withheld_from_a_lan_session(tmp_path):
    """Ported from the classic detail page (cut 2026-08-08), which hid #del-cloud-btn for a
    LAN request: a logged-in LAN session unlocks browsing and spending, not irreversible
    destruction on the owner's real account. The button is React's now; the server's half of
    that rule is /api/next/detail's `can_delete_cloud` flag, computed from
    _is_local_request() -- the SAME check /api/delete-image itself enforces (the 403 for an
    authenticated LAN POST is proven in test_route_tiers.py, where api_delete_image is
    declared LOCALHOST). This proves the client is TOLD not to offer the control, so the
    gate is a hidden button rather than a dead-end click into a 403."""
    cli = _cli(tmp_path, _batch(tmp_path))
    assert cli.get("/api/next/detail/b").get_json().get("can_delete_cloud") is True, (
        "the owner's own localhost session was denied the cloud-delete control")

    lan = cli.get("/api/next/detail/b",
                  environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert lan.status_code == 200, "a logged-in LAN session should still browse details"
    assert lan.get_json().get("can_delete_cloud") is False, (
        "a LAN session was offered cloud deletion")

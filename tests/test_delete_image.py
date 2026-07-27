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


def test_it_deletes_only_the_named_image_and_leaves_its_siblings(tmp_path, monkeypatch):
    """The whole point. The task-level delete takes every image of a batch; this must take
    exactly one and leave the rest of the task alone, on PixAI and in the catalog."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", _session_stub)
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


def test_the_two_delete_paths_are_worded_apart_on_the_page(tmp_path):
    """A dialog that words the recoverable and the irreversible identically is how the wrong
    one gets clicked. Local must say it is recoverable and that a sync brings it back; cloud
    must say it cannot be undone and must carry the typed-DELETE prompt."""
    cli = _cli(tmp_path, _batch(tmp_path))
    html = cli.get("/image/b").get_data(as_text=True)
    assert "Delete locally" in html and "Delete from PixAI" in html
    assert "recoverable" in html and "sync brings it back" in html
    assert "Type DELETE to confirm" in html
    assert "cannot be undone" in html
    # The batch size reaches the dialog, so "the other 2 images stay" is a real number rather
    # than a claim the page cannot back up.
    assert 'data-siblings="3"' in html


def test_the_cloud_button_is_absent_for_an_import_and_over_lan(tmp_path):
    """An import has nothing on PixAI to delete, and a LAN session is not allowed to destroy
    on the owner's account. Both cases hide the control rather than offering a dead-end
    click -- the same rule the LAN chip exists to enforce."""
    cli = _cli(tmp_path, _batch(tmp_path))
    # By the button's id, not its label: the markup's own explanatory comment names the
    # gallery's task-level "Delete from PixAI", so a label substring matches even when no
    # button is rendered at all.
    assert 'id="del-cloud-btn"' not in cli.get("/image/z").get_data(as_text=True)
    assert 'id="del-cloud-btn"' in cli.get("/image/b").get_data(as_text=True)

    lan = cli.get("/image/b", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    if lan.status_code == 200:
        assert 'id="del-cloud-btn"' not in lan.get_data(as_text=True), (
            "a LAN session was offered cloud deletion")

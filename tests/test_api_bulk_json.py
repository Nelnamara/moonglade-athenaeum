"""The JSON twins of the redirect-page bulk flows (plus /api/stats).

/api/delete-local, /api/collection, /api/replace-prompts and /api/delete-tasks are
format conversions of /delete-bulk, /collection-add + /collection-remove,
/bulk-replace-prompt and /delete-tasks-bulk for fetch()-driven clients -- same
helpers underneath, JSON contract instead of redirect-with-banner. The page routes
stay until classic's demolition, so every test here is about the JSON routes doing
the SAME thing the page routes do: the same trash mechanism (restorable via
/api/trash/restore), the same collection helpers, the same task-level cloud delete
through core.delete_task_gql. Tier enforcement (401/403 shapes) is owned by
tests/test_route_tiers.py; here only the contracts that go beyond a bare tier are
re-proven (the LAN refusal wording, READ_ONLY).
"""
import time

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, save_catalog, load_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows, files=None):
    save_catalog(tmp_path / "catalog.db", rows)
    img = tmp_path / "images"
    img.mkdir(exist_ok=True)
    for name, data in (files or {}).items():
        (img / name).write_bytes(data)
    return tmp_path / "catalog.db"


def _wait_for_delete_job(client, timeout_ticks=200):
    """Poll /api/jobs until the async delete worker reports done/failed."""
    job = None
    for _ in range(timeout_ticks):
        jobs = client.get("/api/jobs").get_json()["jobs"]
        job = next((j for j in jobs if j.get("type") == "delete"), None)
        if job and job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    return job


# ---------------------------------------------------------------------------
# /api/delete-local -- the JSON twin of /delete-bulk
# ---------------------------------------------------------------------------

def test_delete_local_quarantines_through_the_same_trash_path(tmp_path):
    """The point of reusing purge_media_local rather than reimplementing: the file
    lands in _deleted/ where /api/trash/restore can bring it back."""
    db = _seed(tmp_path, [
        _row(media_id="a", filename="a.png"),
        _row(media_id="b", filename="b.png"),
        _row(media_id="keep", filename="keep.png"),
    ], {"a.png": b"A", "b.png": b"B", "keep.png": b"K"})

    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["a", "b"]}).get_json()
    assert d == {"ok": True, "count": 2, "failed": 0}

    deleted = tmp_path / g.DELETED_DIRNAME
    assert (deleted / "a.png").exists() and (deleted / "b.png").exists()
    assert (tmp_path / "images" / "keep.png").exists(), "an unselected file was taken"
    assert {r["media_id"] for r in load_catalog(db)} == {"keep"}

    # The same trash mechanism the page delete uses: restore undoes it.
    r = cli.post("/api/trash/restore", json={"media_ids": ["a"]}).get_json()
    assert r["restored"] == ["a"] and not r["errors"]
    assert "a" in {row["media_id"] for row in load_catalog(db)}


def test_delete_local_requires_media_ids(tmp_path):
    cli = login_client(tmp_path)
    assert cli.post("/api/delete-local", json={}).status_code == 400
    assert cli.post("/api/delete-local", json={"media_ids": []}).status_code == 400


def test_delete_local_skips_unknown_ids_and_dedupes(tmp_path):
    """`count` describes FILES quarantined: a repeated id must not inflate it and an
    id the catalog has never heard of is skipped, not an error -- the page route's
    exact behavior."""
    db = _seed(tmp_path, [_row(media_id="x", filename="x.png")], {"x.png": b"X"})
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local",
                 json={"media_ids": ["x", "x", "ghost"]}).get_json()
    assert d == {"ok": True, "count": 1, "failed": 0}
    assert load_catalog(db) == []


def test_delete_local_reports_a_failed_move_without_stranding_the_rest(tmp_path,
                                                                       monkeypatch):
    """Same contract as /delete-bulk's delerr banner, in JSON: one file the OS won't
    release must not abandon the rest, and the caller is told how many failed."""
    db = _seed(tmp_path, [
        _row(media_id="bad", filename="bad.png"),
        _row(media_id="good", filename="good.png"),
    ], {"bad.png": b"x", "good.png": b"y"})

    real_replace = g.Path.replace

    def _one_bad_file(self, target):
        if self.name == "bad.png":
            raise OSError(18, "Invalid cross-device link")
        return real_replace(self, target)

    monkeypatch.setattr(g.Path, "replace", _one_bad_file)

    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["bad", "good"]}).get_json()
    assert d == {"ok": False, "count": 1, "failed": 1}
    assert (tmp_path / g.DELETED_DIRNAME / "good.png").exists()
    # The failed file keeps BOTH its file and its row (purge_media_local's contract).
    assert (tmp_path / "images" / "bad.png").exists()
    assert {r["media_id"] for r in load_catalog(db)} == {"bad"}


# ---------------------------------------------------------------------------
# /api/collection -- the JSON twin of /collection-add + /collection-remove
# ---------------------------------------------------------------------------

def test_collection_add_then_remove_round_trips(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="1", filename="1.png"),
        _row(media_id="2", filename="2.png"),
    ])
    cli = login_client(tmp_path)

    d = cli.post("/api/collection", json={
        "action": "add", "collection": "Faves", "media_ids": ["1", "2"]}).get_json()
    assert d == {"ok": True, "count": 2}
    assert all(r["collections"] == "Faves" for r in load_catalog(db))

    # Adding again changes nothing -- count is rows CHANGED, the page banner's number.
    d = cli.post("/api/collection", json={
        "action": "add", "collection": "Faves", "media_ids": ["1", "2"]}).get_json()
    assert d == {"ok": True, "count": 0}

    d = cli.post("/api/collection", json={
        "action": "remove", "collection": "Faves", "media_ids": ["1"]}).get_json()
    assert d == {"ok": True, "count": 1}
    by_id = {r["media_id"]: r["collections"] for r in load_catalog(db)}
    assert by_id == {"1": "", "2": "Faves"}


def test_collection_validates_its_inputs(tmp_path):
    _seed(tmp_path, [_row(media_id="1", filename="1.png")])
    cli = login_client(tmp_path)
    assert cli.post("/api/collection", json={
        "action": "toggle", "collection": "X", "media_ids": ["1"]}).status_code == 400
    assert cli.post("/api/collection", json={
        "action": "add", "collection": "", "media_ids": ["1"]}).status_code == 400
    assert cli.post("/api/collection", json={
        "action": "add", "collection": "X", "media_ids": []}).status_code == 400


# ---------------------------------------------------------------------------
# /api/replace-prompts -- the JSON twin of /bulk-replace-prompt
# ---------------------------------------------------------------------------

def test_replace_prompts_changes_only_matching_rows(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="1", filename="1.png", prompt_full="a red fox"),
        _row(media_id="2", filename="2.png", prompt_full="a blue bird"),
        _row(media_id="3", filename="3.png", prompt_full="red sky at night"),
    ])
    cli = login_client(tmp_path)
    d = cli.post("/api/replace-prompts", json={
        "find": "red", "replace": "green", "media_ids": ["1", "2", "3"]}).get_json()
    # `changed` counts rows that actually changed -- "2" has no 'red' to replace.
    assert d == {"ok": True, "changed": 2}
    by_id = {r["media_id"]: r["prompt_full"] for r in load_catalog(db)}
    assert by_id["1"] == "a green fox"
    assert by_id["2"] == "a blue bird"
    assert by_id["3"] == "green sky at night"


def test_replace_prompts_scopes_to_the_given_ids(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="1", filename="1.png", prompt_full="red"),
        _row(media_id="2", filename="2.png", prompt_full="red"),
    ])
    cli = login_client(tmp_path)
    d = cli.post("/api/replace-prompts", json={
        "find": "red", "replace": "blue", "media_ids": ["1"]}).get_json()
    assert d == {"ok": True, "changed": 1}
    by_id = {r["media_id"]: r["prompt_full"] for r in load_catalog(db)}
    assert by_id == {"1": "blue", "2": "red"}


def test_replace_prompts_requires_find_and_ids(tmp_path):
    _seed(tmp_path, [_row(media_id="1", filename="1.png", prompt_full="x")])
    cli = login_client(tmp_path)
    assert cli.post("/api/replace-prompts", json={
        "find": "", "replace": "y", "media_ids": ["1"]}).status_code == 400
    assert cli.post("/api/replace-prompts", json={
        "find": "x", "replace": "y", "media_ids": []}).status_code == 400


# ---------------------------------------------------------------------------
# /api/delete-tasks -- the JSON twin of /delete-tasks-bulk (MUTATES THE CLOUD)
# ---------------------------------------------------------------------------

def _cloud_batch(tmp_path):
    """One task with two images (only one ever selected), plus a local import."""
    return _seed(tmp_path, [
        _row(media_id="m1", task_id="T1", filename="m1.png"),
        _row(media_id="m2", task_id="T1", filename="m2.png"),   # sibling, NOT selected
        _row(media_id="loc", task_id="", filename="loc.png", source="local"),
    ], {"m1.png": b"a", "m2.png": b"b", "loc.png": b"c"})


def test_delete_tasks_by_media_ids_matches_the_page_route(tmp_path, monkeypatch):
    """Selecting one image takes its WHOLE task (cloud + local) and the import is
    purged locally only -- byte-for-byte the /delete-tasks-bulk behavior, because
    both routes run the same _resolve_delete_targets + _start_bulk_delete."""
    db = _cloud_batch(tmp_path)
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: calls.append(tid))

    cli = login_client(tmp_path)
    d = cli.post("/api/delete-tasks", json={"media_ids": ["m1", "loc"]}).get_json()
    assert d["ok"] is True and d["job_id"]
    assert d["tasks"] == 1 and d["local_only"] == 1 and d["count"] == 2

    job = _wait_for_delete_job(cli)
    assert job is not None and job["status"] == "done"
    assert calls == ["T1"], "cloud delete must fire once, task-level"
    deleted = tmp_path / g.DELETED_DIRNAME
    for name in ("m1.png", "m2.png", "loc.png"):
        assert (deleted / name).exists()
    assert load_catalog(db) == []


def test_delete_tasks_by_task_ids_directly(tmp_path, monkeypatch):
    db = _cloud_batch(tmp_path)
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: calls.append(tid))

    cli = login_client(tmp_path)
    d = cli.post("/api/delete-tasks", json={"task_ids": ["T1", "T1"]}).get_json()
    assert d["ok"] is True and d["tasks"] == 1 and d["local_only"] == 0

    job = _wait_for_delete_job(cli)
    assert job is not None and job["status"] == "done"
    assert calls == ["T1"]
    # Both task members purged; the import was never part of the selection.
    assert {r["media_id"] for r in load_catalog(db)} == {"loc"}
    assert (tmp_path / "images" / "loc.png").exists()


def test_delete_tasks_purge_local_false_leaves_the_library_alone(tmp_path, monkeypatch):
    """Cloud-only mode (the CLI --delete-task behavior): the task is deleted on
    PixAI, local files and catalog rows stay, and imports -- which have no cloud
    side at all -- are dropped from the job entirely."""
    db = _cloud_batch(tmp_path)
    calls = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "delete_task_gql", lambda sess, tid: calls.append(tid))

    cli = login_client(tmp_path)
    d = cli.post("/api/delete-tasks", json={
        "media_ids": ["m1", "loc"], "purge_local": False}).get_json()
    assert d["ok"] is True
    assert d["local_only"] == 0, "an import slipped into a cloud-only run"
    assert d["count"] == 1

    job = _wait_for_delete_job(cli)
    assert job is not None and job["status"] == "done"
    assert calls == ["T1"]
    assert {r["media_id"] for r in load_catalog(db)} == {"m1", "m2", "loc"}
    for name in ("m1.png", "m2.png", "loc.png"):
        assert (tmp_path / "images" / name).exists()
    assert not (tmp_path / g.DELETED_DIRNAME).exists()


def test_delete_tasks_read_only_refuses_before_the_job_starts(tmp_path, monkeypatch):
    """READ_ONLY is the Trust & Safety promise: one clean 403 up front, no job on
    the Activity card, and the cloud mutation is never reached."""
    _cloud_batch(tmp_path)
    monkeypatch.setattr(core, "READ_ONLY", True)
    monkeypatch.setattr(core, "delete_task_gql",
                        lambda *a, **k: pytest.fail("READ_ONLY did not stop the delete"))

    cli = login_client(tmp_path)
    r = cli.post("/api/delete-tasks", json={"media_ids": ["m1"]})
    assert r.status_code == 403
    assert "READ_ONLY" in (r.get_json().get("error") or "")
    assert not [j for j in cli.get("/api/jobs").get_json()["jobs"]
                if j.get("type") == "delete"], "a job was logged for a refused delete"


def test_delete_tasks_refuses_an_authenticated_lan_session(tmp_path, monkeypatch):
    """Same LOCALHOST tier as the page route, JSON refusal shape. The generic tier
    sweep in test_route_tiers.py also covers this; asserted here too because the
    wording is part of this route's contract."""
    _cloud_batch(tmp_path)
    monkeypatch.setattr(core, "delete_task_gql",
                        lambda *a, **k: pytest.fail("a LAN session reached the cloud delete"))
    cli = login_client(tmp_path)
    r = cli.post("/api/delete-tasks", json={"media_ids": ["m1"]},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403
    assert "localhost-only" in (r.get_json().get("error") or "")


def test_delete_tasks_requires_ids(tmp_path):
    _cloud_batch(tmp_path)
    cli = login_client(tmp_path)
    assert cli.post("/api/delete-tasks", json={}).status_code == 400


def test_delete_tasks_unknown_media_ids_is_a_clean_noop(tmp_path):
    """A selection that resolves to nothing (all ids unknown) answers ok/count=0
    instead of spawning an empty job -- the page route's silent redirect, in JSON."""
    _cloud_batch(tmp_path)
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-tasks", json={"media_ids": ["ghost"]}).get_json()
    assert d["ok"] is True and d["count"] == 0 and d["job_id"] is None


# ---------------------------------------------------------------------------
# /api/stats -- the classic banner's numbers, as JSON
# ---------------------------------------------------------------------------

def _stats_catalog(tmp_path):
    return _seed(tmp_path, [
        _row(media_id="i1", task_id="T1", filename="i1.png"),
        _row(media_id="i2", task_id="T1", filename="i2.png"),
        _row(media_id="i3", task_id="T2", filename="i3.png",
             collections="Faves,Wall"),
        _row(media_id="v1", task_id="T2", filename="v1.mp4", is_video="1"),
        _row(media_id="loc", task_id="", filename="loc.png", source="local",
             collections="Faves"),
    ])


def test_stats_serves_the_banner_counts(tmp_path):
    """images/videos/collections are catalog_counts -- the exact numbers the classic
    template bakes into its header banner. Offline (no API key in tests), the
    coverage half fails soft to nulls, matching the classic page hiding its badge."""
    _stats_catalog(tmp_path)
    cli = login_client(tmp_path)
    d = cli.get("/api/stats").get_json()
    assert d["images"] == 4 and d["videos"] == 1
    assert d["collections"] == 2                      # Faves + Wall, deduped
    assert d["local_tasks"] == 2                      # T1 + T2; the import has no task
    assert d["server_tasks"] is None and d["coverage_pct"] is None


def test_stats_coverage_matches_the_account_badge_computation(tmp_path, monkeypatch):
    """Same formula the cover-badge gets from /api/account: distinct local tasks over
    the server's lifetime task count, one decimal, capped at 100."""
    _stats_catalog(tmp_path)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info",
                        lambda session: {"tasks": {"totalCount": 3}})
    cli = login_client(tmp_path)
    d = cli.get("/api/stats").get_json()
    assert d["server_tasks"] == 3 and d["local_tasks"] == 2
    assert d["coverage_pct"] == round(2 / 3 * 100, 1)


def test_stats_coverage_never_exceeds_100(tmp_path, monkeypatch):
    """A server count lagging behind local (sync raced a deletion) must clamp, not
    report 200% backed up -- same min() the account route applies."""
    _stats_catalog(tmp_path)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "account_info",
                        lambda session: {"tasks": {"totalCount": 1}})
    cli = login_client(tmp_path)
    assert cli.get("/api/stats").get_json()["coverage_pct"] == 100.0

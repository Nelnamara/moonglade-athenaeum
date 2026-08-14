"""/api/task-params/<task_id> -- Remix's recipe-recovery route (issue #4).

Pins the contract the 2026-08-13 adversarial review demanded:
- a task_detail_gql None (its NETWORK-failure return -- it does not raise) must
  answer {"error": ...}, never a success-shaped empty LoRA list (finding 2.1);
- membership: only task ids present in the local catalog resolve (finding 4.3),
  and video/chat tasks are refused (finding 4.2);
- an unparseable weight is counted + skipped, never a silent 0.7 (finding 1.5);
- a failed compatibility-meta lookup ships the row flagged `degraded` (1.4);
- two versions of one LoRA model both come back as distinct rows (1.1 -- the
  client is the layer that must then refuse to merge them);
- retries=1 (finding 4.1).

Patch seam (see tests/test_loom_import_frames.py's header): _gen_session is a
closure handing back the moonglade_backup module itself, so the functions are
patched on `core`, with _make_session stubbed."""
import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog
from tests.conftest import login_client

TID = "9000000000000007041"


def _row(**kw):
    r = {f: "" for f in CATALOG_FIELDS}
    r.update(kw)
    return r


def _cli(tmp_path, monkeypatch, rows=None):
    save_catalog(tmp_path / "catalog.db", rows if rows is not None else [
        _row(media_id="1", filename="a_1.png", task_id=TID,
             created_at="2025-01-01T00:00:00")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    return login_client(tmp_path)


def _wire_task(monkeypatch, task, *, bases=None, names=None, metas=None):
    """Stub the four core helpers the route chains."""
    calls = {"retries": None}

    def detail(session, tid, retries=3):
        calls["retries"] = retries
        return task
    monkeypatch.setattr(core, "task_detail_gql", detail)
    monkeypatch.setattr(core, "resolve_model_base_id",
                        lambda s, vid: (bases or {}).get(str(vid), ""))
    monkeypatch.setattr(core, "model_name_gql",
                        lambda s, vid, **k: (names or {}).get(str(vid), ""))
    monkeypatch.setattr(core, "resolve_version_meta",
                        lambda s, mid: (metas or {}).get(str(mid), {}))
    return calls


def test_happy_path_exact_rows_and_model_version(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch,
               {"parameters": {"modelId": "vER1", "lora": {"L1v": 0.9}}},
               bases={"L1v": "baseA"}, names={"L1v": "Nice LoRA"},
               metas={"baseA": {"lora_base_model_type": "SDXL", "model_type": "SDXL"}})
    d = cli.get("/api/task-params/" + TID).get_json()
    assert "error" not in d
    assert d["model_version_id"] == "vER1"
    assert d["unresolved"] == 0
    assert d["loras"] == [{
        "model_id": "baseA", "version_id": "L1v", "weight": 0.9,
        "title": "Nice LoRA", "preview_url": "",
        "lora_base_model_type": "SDXL", "model_type": "SDXL",
        "degraded": False,
    }]
    # NB: getTaskById resolves cloud-DELETED tasks too (CLAUDE.md, delete
    # section) -- remixing a deleted row working is a feature; a future
    # "validate the task still exists" change must not break it.


def test_unreadable_task_is_an_error_not_empty(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch, None)
    d = cli.get("/api/task-params/" + TID).get_json()
    assert d.get("error")            # NEVER a success-shaped {"loras": []}
    assert "loras" not in d


def test_retries_is_one_not_the_default_ladder(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    calls = _wire_task(monkeypatch, {"parameters": {}})
    cli.get("/api/task-params/" + TID)
    assert calls["retries"] == 1


def test_unknown_task_refused(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch, {"parameters": {"lora": {"x": 1}}})
    r = cli.get("/api/task-params/12345")
    assert r.status_code == 404 and r.get_json()["error"]


def test_video_and_chat_tasks_refused(tmp_path, monkeypatch):
    vid_tid = "8000000000000000001"
    cli = _cli(tmp_path, monkeypatch, rows=[
        _row(media_id="1", filename="a_1.png", task_id=TID,
             created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.mp4", task_id=vid_tid, is_video="1",
             created_at="2025-01-01T00:00:00")])
    _wire_task(monkeypatch, {"parameters": {"chat": {"modelId": "m"}}})
    r = cli.get("/api/task-params/" + vid_tid)
    assert r.status_code == 400 and "image" in r.get_json()["error"]
    r = cli.get("/api/task-params/" + TID)        # image row, but a chat task
    assert r.status_code == 400 and "image" in r.get_json()["error"]


def test_unparseable_weight_skipped_and_counted(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch,
               {"parameters": {"lora": {"L1v": "abc", "L2v": 0.5}}},
               bases={"L2v": "baseB"},
               metas={"baseB": {"lora_base_model_type": "DiT.2", "model_type": "DiT.2"}})
    d = cli.get("/api/task-params/" + TID).get_json()
    assert d["unresolved"] == 1
    assert [l["version_id"] for l in d["loras"]] == ["L2v"]
    assert all(l["weight"] != 0.7 for l in d["loras"])   # no silent default anywhere


def test_unresolvable_base_counts_unresolved(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch, {"parameters": {"lora": {"gone": 1.0}}})  # bases={} -> ""
    d = cli.get("/api/task-params/" + TID).get_json()
    assert d["unresolved"] == 1 and d["loras"] == []


def test_meta_failure_ships_row_flagged_degraded(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch, {"parameters": {"lora": {"L1v": 0.8}}},
               bases={"L1v": "baseA"}, metas={})     # meta lookup -> {}
    d = cli.get("/api/task-params/" + TID).get_json()
    assert d["loras"][0]["degraded"] is True
    assert d["loras"][0]["weight"] == 0.8            # weight still exact


def test_two_versions_of_one_lora_model_both_returned(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    _wire_task(monkeypatch,
               {"parameters": {"lora": {"v1": 0.9, "v2": 0.3}}},
               bases={"v1": "baseA", "v2": "baseA"},
               metas={"baseA": {"lora_base_model_type": "SDXL", "model_type": "SDXL"}})
    d = cli.get("/api/task-params/" + TID).get_json()
    assert [(l["model_id"], l["version_id"], l["weight"]) for l in d["loras"]] == \
        [("baseA", "v1", 0.9), ("baseA", "v2", 0.3)]
    # the CLIENT refuses the second same-model row and counts it into the
    # disclosed note -- the server's job is only to never hide the collision


def test_exception_answers_redacted_error(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)

    def boom(session, tid, retries=3):
        raise RuntimeError(r"C:\Users\gwilkins\secret\place blew up")
    monkeypatch.setattr(core, "task_detail_gql", boom)
    r = cli.get("/api/task-params/" + TID)
    d = r.get_json()
    assert r.status_code == 200 and d["error"]
    assert "gwilkins" not in d["error"]

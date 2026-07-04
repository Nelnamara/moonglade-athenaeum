"""Model/LoRA grid backend: /v2 search (MODEL vs LORA) + version resolution. Mocked --
conftest blocks live /v2; no network, no spend."""
import pixai_gallery_backup as core

_SEARCH = {"data": [
    {"id": "1982880136609467518", "title": "Tsubaki.2", "type": "MMDIT26A_MODEL",
     "likedCount": 10151, "flag": {"shouldBlur": False},
     "media": {"thumbnailUrl": "https://cdn/thumb/x", "publicUrl": "https://cdn/pub/x"},
     "hasLatestAvailableVersion": True},
    {"id": "999", "title": "Spicy LoRA", "type": "MULTI_LORA", "likedCount": 7,
     "flag": {"shouldBlur": True}, "media": {"thumbnailUrl": None, "publicUrl": "https://cdn/pub/y"},
     "hasLatestAvailableVersion": True},
], "hasMore": True}


def test_model_search_rest_shapes_rows(monkeypatch):
    seen = {}
    def fake_get(s, path, params=None, **k):
        seen["path"] = path
        seen["params"] = params
        return _SEARCH
    monkeypatch.setattr(core, "_rest_get", fake_get)
    out = core.model_search_rest(object(), keyword="tsu", usage="MODEL", size=10, offset=0)
    assert seen["path"] == "/generation-model/search"
    assert seen["params"]["usageType"] == "MODEL" and seen["params"]["keyword"] == "tsu"
    assert out["has_more"] is True and len(out["results"]) == 2
    a, b = out["results"]
    assert a["title"] == "Tsubaki.2" and a["model_id"] == "1982880136609467518"
    assert a["liked_count"] == 10151 and a["preview_url"] == "https://cdn/thumb/x"
    assert b["should_blur"] is True and b["preview_url"] == "https://cdn/pub/y"   # falls back to publicUrl


def test_model_search_rest_omits_empty_keyword(monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: seen.update(params=params) or {"data": []})
    core.model_search_rest(object(), keyword="", usage="lora", size=5)
    assert "keyword" not in seen["params"] and seen["params"]["usageType"] == "LORA"


def test_resolve_latest_version_picks_first(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, **k: [{"id": "1983308862240288769", "modelId": "1982880136609467518"}])
    assert core.resolve_latest_version(object(), "1982880136609467518") == "1983308862240288769"


def test_resolve_latest_version_empty(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: [])
    assert core.resolve_latest_version(object(), "x") == ""


def test_web_generate_pipeline(monkeypatch, tmp_path):
    # web_generate = submit -> poll -> task detail -> download/catalog; all reused parts
    # mocked so no network / no spend. Verifies it threads the pieces + returns media_ids.
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {"id": "T1"}})
    monkeypatch.setattr(core, "_poll_task_status", lambda *a, **k: 0)
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t: {"outputs": {"mediaId": "M1", "batchMediaIds": ["M2"]}})
    monkeypatch.setattr(core, "_download_image_task", lambda *a, **k: ["/p/M1.webp", "/p/M2.webp"])
    res = core.web_generate(object(), {"prompts": "x", "modelId": "v"}, str(tmp_path))
    assert res["task_id"] == "T1" and res["media_ids"] == ["M1", "M2"]
    assert res["saved"] == 2 and res["paid_credit"] == 0


def test_web_generate_raises_without_task_id(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {}})
    with pytest.raises(core.PixAIError):
        core.web_generate(object(), {"prompts": "x", "modelId": "v"}, str(tmp_path))


def test_workflow_catalog(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"workflows": {"edges": [
        {"node": {"id": "1794855217667308480", "name": "Image Upscale",
                  "type": "UPSCALE", "coverMediaId": "9"}},
        {"node": {"id": "", "name": "no-id skipped"}},
    ]}})
    out = core.workflow_catalog(object())
    assert len(out) == 1 and out[0]["id"] == "1794855217667308480"
    assert out[0]["name"] == "Image Upscale" and out[0]["cover_media_id"] == "9"


def test_submit_generation(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {"id": "T9"}})
    assert core.submit_generation(object(), {"x": 1}) == "T9"


def test_submit_generation_raises(monkeypatch):
    import pytest
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {}})
    with pytest.raises(core.PixAIError):
        core.submit_generation(object(), {})


def test_generation_status_phases(monkeypatch):
    for raw, phase in [("completed", "done"), ("succeeded", "done"), ("failed", "failed"),
                       ("cancelled", "failed"), ("running", "running"), ("pending", "running")]:
        monkeypatch.setattr(core, "gql_adhoc",
                            lambda s, q, v=None, _r=raw: {"task": {"status": _r, "paidCredit": 7}})
        st = core.generation_status(object(), "T")
        assert st["phase"] == phase and st["paid_credit"] == 7


def test_collect_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: {"outputs": {"mediaId": "M1"}})
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {"prompt_full": "p"})
    monkeypatch.setattr(core, "_download_image_task", lambda *a, **k: ["/M1.webp"])
    got = core.collect_generation(object(), "T", str(tmp_path))
    assert got["media_ids"] == ["M1"] and got["saved"] == 1

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

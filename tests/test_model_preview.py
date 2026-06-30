"""Model/LoRA search surfaces a directly-displayable cover thumbnail for the picker
(so you don't need the PixAI website open to browse LoRAs)."""
import pixai_gallery_backup as core


def test_model_preview_url_picks_thumb_variant():
    media = {"id": "1", "urls": [
        {"url": "https://images-ng.pixai.art/images/orig/abc"},
        {"url": "https://images-ng.pixai.art/images/thumb/abc"},
        {"url": "https://images-ng.pixai.art/images/stillThumb/abc"},
    ]}
    assert core._model_preview_url(media) == "https://images-ng.pixai.art/images/thumb/abc"


def test_model_preview_url_falls_back_and_handles_empty():
    assert core._model_preview_url({"urls": [{"url": "x/orig/y"}]}) == "x/orig/y"
    assert core._model_preview_url(None) == ""
    assert core._model_preview_url({"urls": []}) == ""


def test_model_search_surfaces_preview(monkeypatch):
    fake = {"generationModels": {"edges": [
        {"node": {"id": "m1", "title": "Cool LoRA", "type": "LORA", "isNsfw": False,
                  "likedCount": 42, "latestVersion": {"id": "v1"},
                  "media": {"urls": [{"url": "cdn/thumb/p"}]}}},
    ]}}
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: fake)
    res = core.model_search_gql(object(), "cool", lora_only=True)
    assert res[0]["preview_url"] == "cdn/thumb/p"
    assert res[0]["liked_count"] == 42
    assert res[0]["version_id"] == "v1"

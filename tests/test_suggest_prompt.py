"""Image-to-prompt: GET /v2/tag/suggest-prompt/{mediaId} (free, read-only). Mocked --
conftest blocks live /v2; no network, no spend."""
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core


def test_suggest_prompt_returns_output(monkeypatch):
    seen = {}
    def fake_get(s, path, **k):
        seen["path"] = path
        return {"output": ["a, b, c", "A picture of a, b, c"]}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    assert core.suggest_prompt(object(), "999") == ["a, b, c", "A picture of a, b, c"]
    assert seen["path"] == "/tag/suggest-prompt/999"


def test_suggest_prompt_empty(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: {})
    assert core.suggest_prompt(object(), "999") == []


def _args(**kw):
    base = dict(suggest_prompt="", token=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_run_suggest_prompt_media_id(monkeypatch, capsys):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "suggest_prompt", lambda s, mid: ["tag1, tag2"])
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload for media_id")))
    res = core.run_suggest_prompt(_args(suggest_prompt="999"))
    assert res == {"suggestions": 1, "media_id": "999"}
    assert "tag1, tag2" in capsys.readouterr().out


def test_run_suggest_prompt_requires_arg():
    with pytest.raises(core.PixAIError):
        core.run_suggest_prompt(_args(suggest_prompt=""))


def test_run_suggest_prompt_local_file_uploads_first(monkeypatch, tmp_path):
    f = tmp_path / "pic.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media", lambda s, p: "up-1")
    grabbed = {}
    def fake_suggest(s, mid):
        grabbed["mid"] = mid
        return ["x"]
    monkeypatch.setattr(core, "suggest_prompt", fake_suggest)
    core.run_suggest_prompt(_args(suggest_prompt=str(f)))
    assert grabbed["mid"] == "up-1"   # the local file was uploaded, then that id used


# ---- B18 residual: --suggest-prompt needs the same video gate the web template has ----
# (`{% if row.is_video != '1' %}` around the Suggest Prompt button in pixai_gallery.py).
# PixAI's suggest-prompt endpoint is image-only and 500s on a video; the CLI must refuse
# early with a clear message instead of surfacing that raw 500.

def test_run_suggest_prompt_refuses_a_known_video_media_id(tmp_path, monkeypatch):
    from pixai_gallery import CATALOG_FIELDS, save_catalog
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "9001", "is_video": "1", "filename": "2025-01/v_9001.mp4"}])
    # Proves the gate fires BEFORE any session/network setup -- not just before the
    # REST call -- by making _make_session itself explode if it's ever reached.
    monkeypatch.setattr(core, "_make_session",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not touch the network for a known video")))
    with pytest.raises(core.PixAIError, match="video"):
        core.run_suggest_prompt(_args(suggest_prompt="9001", out=str(tmp_path)))


def test_run_suggest_prompt_refuses_a_local_video_file(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setattr(core, "_make_session",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not touch the network for a video file")))
    with pytest.raises(core.PixAIError, match="video"):
        core.run_suggest_prompt(_args(suggest_prompt=str(f), out=str(tmp_path)))


def test_run_suggest_prompt_still_allows_an_image_media_id_not_in_the_catalog(monkeypatch, tmp_path):
    """The gate must only fire when the LOCAL catalog affirmatively says is_video='1' --
    an id the catalog doesn't know about (someone else's, or not yet synced) must still
    reach the network exactly as before."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "suggest_prompt", lambda s, mid: ["tag1, tag2"])
    res = core.run_suggest_prompt(_args(suggest_prompt="424242", out=str(tmp_path)))
    assert res == {"suggestions": 1, "media_id": "424242"}

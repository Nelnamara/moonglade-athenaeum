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

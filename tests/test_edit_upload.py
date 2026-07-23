"""Media upload (uploadMedia 3-step S3 handshake) + instruct editing
(createGenerationTask `chat` block). Pinned to the REAL captured shapes (2026-07-01).
Pure/mocked -- no live network, no credits."""
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core


# ---- build_chat_edit_parameters (pinned to the captured Edit-Pro submit) ----

def test_build_chat_edit_parameters_matches_real_submit():
    p = core.build_chat_edit_parameters(
        "Change it to nighttime moonlight", ["738939216332293270"],
        model_id="2006468692917575683",
        resolution="1K", aspect_ratio="3:4", quality="medium")
    assert p == {"chat": {
        "prompts": "Change it to nighttime moonlight",
        "mediaId": "738939216332293270",
        "mediaIds": ["738939216332293270"],
        "modelId": "2006468692917575683",
        "modelConfig": {"resolution": "1K", "aspectRatio": "3:4", "quality": "medium"},
    }}
    # NEVER attach a free-card id by default (spend stays credit-gated + explicit)
    assert "kaisuukenId" not in p


def test_build_chat_edit_multi_reference():
    p = core.build_chat_edit_parameters("blend", ["10", "20", "30"])
    chat = p["chat"]
    assert chat["mediaId"] == "10"                 # first is the primary
    assert chat["mediaIds"] == ["10", "20", "30"]  # array => multi-image reference
    assert chat["modelId"] == core.EDIT_PRO_MODEL_ID


def test_build_chat_edit_requires_a_source():
    with pytest.raises(core.PixAIError):
        core.build_chat_edit_parameters("x", [])


# ---- _is_local_source: file => upload; numeric media_id => passthrough ----

def test_is_local_source_distinguishes_file_from_media_id(tmp_path):
    f = tmp_path / "pic.png"
    f.write_bytes(b"\x89PNG\r\n")
    assert core._is_local_source(str(f)) is True
    assert core._is_local_source("738939216332293270") is False
    assert core._is_local_source("") is False


# ---- upload_media: the 3-step S3 handshake ----

def test_upload_media_three_step_flow(tmp_path, monkeypatch):
    f = tmp_path / "pic.png"
    f.write_bytes(b"PNGDATA")

    calls = []

    def fake_gql(session, query, variables=None, retries=3):
        calls.append(variables["input"])
        if "externalId" not in variables["input"]:
            # phase 1: hand back a presigned target
            return {"uploadMedia": {"uploadUrl": "https://s3.example/put",
                                    "externalId": "uuid-1"}}
        # phase 3: register -> media id
        return {"uploadMedia": {"mediaId": "999", "media": {"id": "999"}}}

    put_calls = []

    def fake_put(url, data=None, headers=None, timeout=None):
        put_calls.append((url, data, headers))
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    monkeypatch.setattr(core.requests, "put", fake_put)

    mid = core.upload_media(object(), str(f))

    assert mid == "999"
    # phase 1 has no externalId; phase 3 carries the one from phase 1
    assert calls[0] == {"type": "IMAGE", "provider": "S3"}
    assert calls[1] == {"type": "IMAGE", "provider": "S3", "externalId": "uuid-1"}
    # the raw bytes were PUT to the presigned url (not through our API session)
    assert put_calls and put_calls[0][0] == "https://s3.example/put"
    assert put_calls[0][1] == b"PNGDATA"


def test_upload_media_missing_file(tmp_path):
    with pytest.raises(core.PixAIError):
        core.upload_media(object(), str(tmp_path / "nope.png"))


# ---- run_edit_image guards ----

def _edit_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, edit_src=["100"], params_json="",
                prompt="make it night", edit_model="", edit_resolution="1K",
                edit_aspect="3:4", edit_quality="medium", confirm=False, task_id="",
                poll_timeout=300, name_length=60, name_sep="_")
    base.update(kw)
    return SimpleNamespace(**base)


def test_edit_previews_without_confirm(tmp_path, monkeypatch):
    # No --confirm => preview only: no upload, no network, spends nothing.
    def boom(*a, **k):
        raise AssertionError("network/upload must not run in preview")
    monkeypatch.setattr(core, "gql_adhoc", boom)
    monkeypatch.setattr(core, "upload_media", boom)
    res = core.run_edit_image(_edit_args(tmp_path))
    assert res == {"submitted": False}


def test_edit_preview_shows_local_files_without_uploading(tmp_path, monkeypatch, capsys):
    f = tmp_path / "pic.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload in preview")))
    core.run_edit_image(_edit_args(tmp_path, edit_src=[str(f)]))
    out = capsys.readouterr().out
    assert "<upload:" in out and "PREVIEW" in out


def test_edit_requires_a_source(tmp_path):
    with pytest.raises(core.PixAIError):
        core.run_edit_image(_edit_args(tmp_path, edit_src=[], params_json="", task_id=""))


def test_edit_config_from_args_clamps_to_model_caps(tmp_path):
    """The CLI's own --edit-resolution/--edit-quality DEFAULTS (1K/medium) are exactly
    what used to reach the server unclamped -- a real model like reference-pro (no
    quality knob at all, 2K/4K only) rejects that combo. The web /api/edit path has
    run this same guard (clamp_edit_config) since the preset-mismatch bug; the CLI
    never did. Same expected values as test_clamp_edit_config_snaps_to_model_caps.

    Bite: remove the clamp_edit_config call from _edit_config_from_args and this
    fails -- cfg comes back with the raw, unclamped 1K/medium instead."""
    args = _edit_args(tmp_path, edit_model="1948514378441961474",
                      edit_resolution="1K", edit_aspect="21:9", edit_quality="medium")
    cfg = core._edit_config_from_args(args)
    assert cfg["resolution"] == "2K"
    assert cfg["quality"] == ""
    assert cfg["aspect_ratio"] == "21:9"


def test_edit_preview_shows_the_clamped_config_not_the_raw_defaults(tmp_path, capsys):
    """End-to-end: --edit-image's own preview output (what a real --confirm run would
    actually submit) reflects the clamped values, not the CLI's raw defaults."""
    args = _edit_args(tmp_path, edit_model="1948514378441961474",
                      edit_resolution="1K", edit_aspect="21:9", edit_quality="medium")
    core.run_edit_image(args)
    out = capsys.readouterr().out
    assert '"resolution": "2K"' in out
    assert '"quality"' not in out   # reference-pro exposes no quality knob at all

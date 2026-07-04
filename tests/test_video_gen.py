"""Video (image-to-video) parameter builder — the first brick of storyboard-driven
video gen. Pinned to the REAL captured i2vPro payload (2026-07-01) so we know the
builder produces exactly what PixAI's generator sends. Pure functions; no network,
no credits."""
from types import SimpleNamespace

import pixai_gallery_backup as core


def test_build_video_parameters_matches_real_submit():
    # EXACT structure of a real captured createGenerationTask submit (2026-07-01):
    # variables.parameters = {channel, i2vPro:{...}} -- no {type,version} wrapper.
    p = core.build_video_parameters(
        "", media_id="738340964113285867", model="v4.0.1",
        tail_media_id="738340489931639723", duration=5, mode="professional",
        generate_audio=True,
    )
    assert p == {
        "channel": "private",
        "i2vPro": {
            "model": "v4.0.1",
            "mediaId": "738340964113285867",
            "usePromptsHelper": False,
            "prompts": "",
            "mode": "professional",
            "duration": "5",
            "generateAudio": True,
            "audioLanguage": "english",
            "tailMediaId": "738340489931639723",
        },
    }


def test_single_source_image_omits_tail():
    p = core.build_video_parameters("motion", media_id="100")
    i2v = p["i2vPro"]
    assert p["channel"] == "private"
    assert i2v["mediaId"] == "100"
    assert "tailMediaId" not in i2v                 # no tail => single-source i2v
    assert i2v["model"] == core.DEFAULT_VIDEO_MODEL


def test_gen_video_parameters_from_args():
    a = SimpleNamespace(prompt="p", image="55", tail="56", duration=10,
                        model="", video_model="", vmode="basic", audio=False,
                        audio_language="english", negative="",
                        video_prompt_helper=False, params_json="")
    p = core._gen_video_parameters(a)
    i2v = p["i2vPro"]
    assert i2v["mediaId"] == "55" and i2v["tailMediaId"] == "56"
    assert i2v["duration"] == "10" and i2v["mode"] == "basic"
    assert i2v["model"] == core.DEFAULT_VIDEO_MODEL   # empty model -> default


def test_params_json_override():
    a = SimpleNamespace(params_json='{"type":"x"}')
    assert core._gen_video_parameters(a) == {"type": "x"}


def _video_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), image="55", tail="", prompt="p", negative="",
                model="", video_model="", duration=5, vmode="professional",
                audio=False, audio_language="english", video_prompt_helper=False,
                params_json="", task_id="", confirm=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_generate_video_previews_without_confirm(tmp_path):
    # No --confirm => preview only, no network, spends nothing.
    res = core.run_generate_video(_video_args(tmp_path))
    assert res == {"submitted": False}


def test_generate_video_requires_a_source_image(tmp_path):
    import pytest
    with pytest.raises(core.PixAIError):
        core.run_generate_video(_video_args(tmp_path, image=""))


# ---- banked enums: camera movement + channel (2026-07-02) ----

def test_camera_movement_included_when_set():
    p = core.build_video_parameters("p", media_id="1", camera_movement="zoom")
    assert p["i2vPro"]["cameraMovement"] == "zoom"


def test_camera_movement_omitted_by_default_and_on_unset():
    assert "cameraMovement" not in core.build_video_parameters("p", media_id="1")["i2vPro"]
    assert "cameraMovement" not in core.build_video_parameters(
        "p", media_id="1", camera_movement="unset")["i2vPro"]


def test_channel_default_private_and_override_normal():
    assert core.build_video_parameters("p", media_id="1")["channel"] == "private"
    assert core.build_video_parameters("p", media_id="1", channel="normal")["channel"] == "normal"


# ---- --dump-params: bank any submit shape off a recovered task ----

def test_dump_params_prints_full_shape_when_flagged(capsys):
    core._maybe_dump_params(SimpleNamespace(dump_params=True),
                            {"parameters": {"i2vPro": {"model": "v4.0.1"},
                                            "multiRefResource": {"imageMediaIds": ["1"]}}})
    out = capsys.readouterr().out
    assert "full submit shape" in out and "v4.0.1" in out and "multiRefResource" in out


def test_dump_params_silent_by_default(capsys):
    core._maybe_dump_params(SimpleNamespace(dump_params=False), {"parameters": {"x": 1}})
    assert capsys.readouterr().out == ""


# ---- referenceVideo (multi-image/video/audio) -- pinned to the real submit (2026-07-02) ----

def test_build_reference_video_matches_real_submit():
    p = core.build_reference_video_parameters(
        "make @image1 dance", image_media_ids=["10", "20"],
        model="v4.0.1", duration=15, mode="professional",
        generate_audio=True, audio_language="english")
    rv = p["referenceVideo"]
    assert rv["referenceImageMediaIds"] == ["10", "20"]
    assert rv["duration"] == 15                       # INT, not "15"
    assert rv["referenceVideoMediaIds"] == [] and rv["referenceAudioMediaIds"] == []
    assert p["isPrivate"] is False and p["enablePreview"] is True
    assert p["modelId"] == core.REFVIDEO_MODEL_ID
    assert "referenceVideo" in p and "i2vPro" not in p   # distinct from i2v


def test_reference_video_refs_private_and_card():
    p = core.build_reference_video_parameters(
        "x", image_media_ids=["1"], video_media_ids=["v1"], audio_media_ids=["a1"],
        is_private=True, kaisuuken_id="card9")
    rv = p["referenceVideo"]
    assert rv["referenceVideoMediaIds"] == ["v1"] and rv["referenceAudioMediaIds"] == ["a1"]
    assert p["isPrivate"] is True and p["kaisuukenId"] == "card9"


def _refvid_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, reference_video=True, ref_image=["10"],
                ref_video=None, ref_audio=None, params_json="", prompt="@image1 dances",
                video_model="", duration=15, vmode="professional", audio=False,
                audio_language="english", vchannel="private", kaisuuken_id="",
                confirm=False, task_id="", poll_timeout=600, name_length=60, dump_params=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_reference_video_previews_without_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network in preview")))
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload in preview")))
    assert core.run_reference_video(_refvid_args(tmp_path)) == {"submitted": False}


def test_reference_video_requires_a_ref(tmp_path):
    import pytest
    with pytest.raises(core.PixAIError):
        core.run_reference_video(_refvid_args(tmp_path, ref_image=None))


# ---- shot -> video params (the PixAI provider adapter for the Edit Bay) ----

def test_snap_video_duration():
    assert core._snap_video_duration(4) == 5
    assert core._snap_video_duration(12) == 10
    assert core._snap_video_duration(15) == 15
    assert core._snap_video_duration("bad") == 5


def test_build_shot_video_params_i2v():
    assert "i2vPro" in core.build_shot_video_params("I2V", "turn", image_ids=["100"], duration=5)


def test_build_shot_video_params_flf():
    assert "i2vPro" in core.build_shot_video_params("FLF", "morph", image_ids=["1", "2"], duration=6)


def test_build_shot_video_params_r2v():
    p = core.build_shot_video_params("R2V", "@image1 @image2", image_ids=["1", "2"], duration=15)
    assert "referenceVideo" in p and p["referenceVideo"]["referenceImageMediaIds"] == ["1", "2"]


def test_build_shot_video_params_needs_refs():
    import pytest
    with pytest.raises(core.PixAIError):
        core.build_shot_video_params("R2V", "x")


def test_build_shot_video_params_model_and_audio_passthrough():
    p = core.build_shot_video_params("I2V", "sing", image_ids=["1"], duration=5,
                                     model="v3.2", generate_audio=True,
                                     audio_language="japanese", camera_movement="zoom",
                                     quality="basic")
    i2v = p["i2vPro"]
    assert i2v["model"] == "v3.2" and i2v["generateAudio"] is True
    assert i2v["audioLanguage"] == "japanese"
    assert i2v["cameraMovement"] == "zoom" and i2v["mode"] == "basic"
    r = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model="v4.0")
    assert r["referenceVideo"]["model"] == "v4.0"
    # empty model falls back to the default on every path
    d = core.build_shot_video_params("I2V", "x", image_ids=["1"], model="")
    assert d["i2vPro"]["model"] == core.DEFAULT_VIDEO_MODEL


def test_collect_generation_detects_video(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: {"outputs": {"videos": [{"mediaId": "V9"}]}})
    monkeypatch.setattr(core, "video_outputs", lambda r: ([{"video_media_id": "V9"}], {"prompt": "p"}))
    monkeypatch.setattr(core, "_download_video_task", lambda *a, **k: ["/V9.mp4"])
    got = core.collect_generation(object(), "T", str(tmp_path))
    assert got["is_video"] is True and got["media_ids"] == ["V9"] and got["saved"] == 1

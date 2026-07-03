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

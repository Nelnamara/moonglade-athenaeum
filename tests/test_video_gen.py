"""Video (image-to-video) parameter builder — the first brick of storyboard-driven
video gen. Pinned to the REAL captured i2vPro payload (2026-07-01) so we know the
builder produces exactly what PixAI's generator sends. Pure functions; no network,
no credits."""
from types import SimpleNamespace

import pixai_gallery_backup as core


def test_build_video_parameters_matches_real_submit():
    # EXACT structure of a real CARD-COVERED submit (verified 2026-07-06 via --dump-params):
    # top-level modelId (REQUIRED -- resolved from the .model name) + i2vPro block + privacy
    # flags. No `channel`. Omitting modelId was the "video card won't tap" bug.
    p = core.build_video_parameters(
        "", media_id="738340964113285867", model="v4.0.1",
        tail_media_id="738340489931639723", duration=5, mode="professional",
        generate_audio=True,
    )
    assert p == {
        "priority": 1000,
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
        "isPrivate": False,
        "enablePreview": True,
        "hidePrompts": False,
        "modelId": "2003969750675682808",   # v4.0.1 (Lite) -> its numeric id
    }


def test_single_source_image_omits_tail():
    p = core.build_video_parameters("motion", media_id="100")
    i2v = p["i2vPro"]
    assert "channel" not in p and p["isPrivate"] is False
    assert i2v["mediaId"] == "100"
    assert "tailMediaId" not in i2v                 # no tail => single-source i2v
    assert i2v["model"] == core.DEFAULT_VIDEO_MODEL
    assert p["modelId"] == "2003969750675682808"    # DEFAULT (v4.0.1) resolved to its numeric id


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


def test_isprivate_default_and_modelid_required():
    p = core.build_video_parameters("p", media_id="1")
    assert "channel" not in p and p["isPrivate"] is False   # channel retired; isPrivate now
    assert p["enablePreview"] is True and p["hidePrompts"] is False
    # the REQUIRED top-level modelId resolves from the .model name (the video-card fix)
    assert p["modelId"] == core.video_model_id(core.DEFAULT_VIDEO_MODEL) == "2003969750675682808"
    assert core.build_video_parameters("p", media_id="1", is_private=True)["isPrivate"] is True


def test_shot_params_carry_correct_modelid():
    # i2v: the numeric modelId must ride along, resolved per model (was missing entirely --
    # PixAI logged "Unknown or removed model" and no card matched without it).
    assert core.build_shot_video_params(
        "I2V", "x", image_ids=["1"], model="v4.0.1")["modelId"] == "2003969750675682808"
    assert core.build_shot_video_params(
        "I2V", "x", image_ids=["1"], model="v4.0")["modelId"] == "2003968021137101826"
    # R2V: the reference path no longer hardcodes the Lite id -- full V4.0 gets the full id.
    assert core.build_shot_video_params(
        "R2V", "@image1", image_ids=["1"], model="v4.0")["modelId"] == "2003968021137101826"


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


# ---- shot -> video params (the PixAI provider adapter for the Loom) ----

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


def test_build_shot_video_params_negative_and_channel():
    # negative + is_private reach i2vPro (I2V/FLF) -- both fields exist on that submit shape.
    p = core.build_shot_video_params("I2V", "x", image_ids=["1"], negative="blurry, watermark",
                                     is_private=True)
    assert p["i2vPro"]["negativePrompts"] == "blurry, watermark"
    assert p["isPrivate"] is True
    f = core.build_shot_video_params("FLF", "x", image_ids=["1", "2"], negative="extra fingers")
    assert f["i2vPro"]["negativePrompts"] == "extra fingers"
    # default is_private stays False (today's de-facto Normal-channel behavior, unchanged)
    default = core.build_shot_video_params("I2V", "x", image_ids=["1"])
    assert default["isPrivate"] is False


def test_build_shot_video_params_r2v_channel_but_no_negative_field():
    # referenceVideo DOES carry isPrivate...
    r = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], is_private=True)
    assert r["isPrivate"] is True
    # ...but has no negativePrompts field at all -- a genuine PixAI API gap (the captured
    # referenceVideo submit shape has never had one), not a bug: negative is silently
    # dropped for R2V rather than invented into a field PixAI doesn't accept.
    r2 = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], negative="blurry")
    assert "negativePrompts" not in r2["referenceVideo"]


def test_build_shot_video_params_r2v_video_and_audio_ids_flow_through():
    p = core.build_shot_video_params("R2V", "@video1 @audio1", video_ids=["9"], audio_ids=["7"])
    rv = p["referenceVideo"]
    assert rv["referenceVideoMediaIds"] == ["9"] and rv["referenceAudioMediaIds"] == ["7"]
    assert rv["referenceImageMediaIds"] == []


def test_collect_generation_detects_video(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: {"outputs": {"videos": [{"mediaId": "V9"}]}})
    monkeypatch.setattr(core, "video_outputs", lambda r: ([{"video_media_id": "V9"}], {"prompt": "p"}))
    monkeypatch.setattr(core, "_download_video_task", lambda *a, **k: ["/V9.mp4"])
    got = core.collect_generation(object(), "T", str(tmp_path))
    assert got["is_video"] is True and got["media_ids"] == ["V9"] and got["saved"] == 1


def test_download_video_task_posterless_makes_ffmpeg_thumb(monkeypatch, tmp_path):
    """A poster-less API-generated video (no still-frame) must get its thumbnail from
    the mp4's first frame AT COLLECT TIME (via video_poster_thumb) -- not wait for a
    later --sync-videos pass. This is the fix for the blank-video-tile bug."""
    from pathlib import Path
    # No poster on the output -> the ffmpeg fallback branch must fire.
    monkeypatch.setattr(core, "video_outputs",
                        lambda r: ([{"video_media_id": "V1", "poster_media_id": "", "seed": 1}],
                                   {"prompt": "p", "duration": 5}))
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "http://x/v.mp4"})

    def _fake_download(session, url, stem, **kw):
        p = Path(str(stem) + ".mp4"); p.write_bytes(b"\x00\x00\x00\x18ftypmp42"); return "ok", p
    monkeypatch.setattr(core, "download", _fake_download)

    calls = []
    def _fake_vpt(video_path, thumb_path):
        calls.append((str(video_path), str(thumb_path))); Path(thumb_path).write_bytes(b"jpg"); return True
    monkeypatch.setattr(core, "video_poster_thumb", _fake_vpt)

    core._download_video_task(object(), {}, "T1", tmp_path, SimpleNamespace(name_length=60), {})

    assert len(calls) == 1, "ffmpeg first-frame fallback should fire exactly once for a poster-less video"
    assert calls[0][1].endswith("V1.jpg")
    assert (tmp_path / "gallery" / "thumbs" / "V1.jpg").exists()


def test_download_video_task_with_poster_skips_ffmpeg(monkeypatch, tmp_path):
    """When PixAI DID return a still-frame poster, we thumbnail that -- ffmpeg fallback
    must NOT run (no redundant decode)."""
    from pathlib import Path
    monkeypatch.setattr(core, "video_outputs",
                        lambda r: ([{"video_media_id": "V2", "poster_media_id": "P2", "seed": 1}],
                                   {"prompt": "p", "duration": 5}))
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "http://x/v.mp4"})
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("http://x/p.png", {}))

    def _fake_download(session, url, stem, **kw):
        p = Path(str(stem)); p.parent.mkdir(parents=True, exist_ok=True)
        p = p.with_suffix(p.suffix or ".bin"); p.write_bytes(b"data"); return "ok", p
    monkeypatch.setattr(core, "download", _fake_download)
    monkeypatch.setattr("pixai_gallery.make_thumbnail",
                        lambda src, dst: (Path(dst).write_bytes(b"jpg"), True)[1])

    called = []
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: called.append(1))
    core._download_video_task(object(), {}, "T2", tmp_path, SimpleNamespace(name_length=60), {})
    assert called == [], "poster present -> ffmpeg fallback should be skipped"
    assert (tmp_path / "gallery" / "thumbs" / "V2.jpg").exists()

"""Video (image-to-video) parameter builder — the first brick of storyboard-driven
video gen. Pinned to the REAL captured i2vPro payload (2026-07-01) so we know the
builder produces exactly what PixAI's generator sends. Pure functions; no network,
no credits."""
from types import SimpleNamespace

import pytest

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


def test_dump_params_also_prints_the_task_status(capsys):
    """Found 2026-07-21 debugging a real report of edit jobs that 'never hit PixAI':
    --dump-params printed only what was SUBMITTED, never what happened to it -- so the
    one moment someone recovers a task specifically because something looked wrong, this
    told them nothing about the outcome. A real task carries status alongside parameters
    in the same getTaskById response; this must not require a second round trip."""
    core._maybe_dump_params(SimpleNamespace(dump_params=True),
                            {"parameters": {"x": 1}, "status": "Failed"})
    out = capsys.readouterr().out
    assert "task status: Failed" in out


def test_dump_params_omits_the_status_line_when_absent(capsys):
    """Must not print 'task status: None' or similar -- silence is correct when the
    response genuinely carries no status field."""
    core._maybe_dump_params(SimpleNamespace(dump_params=True), {"parameters": {"x": 1}})
    out = capsys.readouterr().out
    assert "task status" not in out


# ---- _outputs_or_raise: an accurate message when PixAI itself failed the task ----

class TestOutputsOrRaise:
    def test_does_not_raise_when_something_was_found(self):
        core._outputs_or_raise({"status": "done"}, found=["media1"], empty_message="unused")

    def test_genuinely_empty_completed_task_keeps_the_original_message(self):
        """The case this message was always right about -- e.g. a silently
        content-filtered task that PixAI still reports as 'done'. Must not change."""
        with pytest.raises(core.EmptyOutputsError, match="task completed but no media"):
            core._outputs_or_raise({"status": "done"}, found=[],
                                   empty_message="task completed but no media ids found")

    def test_missing_status_keeps_the_original_message(self):
        """A --task-id recovery whose getTaskById response has no status field at all
        (or the field is empty) must fall back to the original wording, not silently
        claim a failure that was never reported."""
        with pytest.raises(core.EmptyOutputsError, match="task completed but no media"):
            core._outputs_or_raise({}, found=[],
                                   empty_message="task completed but no media ids found")

    @pytest.mark.parametrize("raw_status", ["failed", "Failed", "ERROR", "cancelled",
                                            "Canceled", "rejected"])
    def test_a_real_pixai_failure_gets_an_accurate_message_instead(self, raw_status):
        """The actual bug: all four call sites said 'task completed' unconditionally,
        even when PixAI's own status said the task never completed at all -- which read
        as a Moonglade bug reporting a PixAI-side rejection. Case-insensitive, since
        pixai_gallery_backup.py's own generation_status() lowercases before comparing
        against this same _GEN_FAIL tuple."""
        with pytest.raises(core.EmptyOutputsError) as exc:
            core._outputs_or_raise({"status": raw_status}, found=[],
                                   empty_message="task completed but no media ids found")
        msg = str(exc.value)
        assert "completed" not in msg, "still claims the task completed"
        assert raw_status.lower() in msg.lower()
        assert "pixai.art" in msg, "no pointer to where the real reason might be found"


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


# ---- gallery references must be uploaded, not passed through (regression) ----

def test_gallery_catalog_ref_is_uploaded_not_passed_through(tmp_path, monkeypatch):
    """PRODUCTION BUG, 2026-07-20: every generation started from the gallery failed with
    PixAI's invalid_media_id / invalid_reference_image_media_id and a full refund, while
    the same thing from the Loom worked.

    A media_id in our catalog identifies a generation OUTPUT, and PixAI will not accept
    one as a generation INPUT. It is NOT expiry -- both a month-old and a same-day id
    resolve fine through GET /v1/media -- it is media kind: readable is not usable-as-input.

    The Loom escaped it by accident: it sends data: thumbnails, which the route already
    uploaded, yielding an upload-kind id. The gallery sends bare catalog ids, so it could
    never reach that branch.

    Pins the fix: a catalog id whose file we hold on disk must be uploaded, and the
    UPLOADED id is what reaches PixAI."""
    from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client

    (tmp_path / "2025-01").mkdir(parents=True, exist_ok=True)
    img = tmp_path / "2025-01" / "shot_733917871331404290.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "733917871331404290", "filename": "2025-01/shot_733917871331404290.png",
        "created_at": "2026-06-18T05:24:56Z"}])

    uploaded, submitted = [], {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media",
                        lambda session, path, **k: uploaded.append(str(path)) or "999000111222")
    monkeypatch.setattr(core, "submit_generation",
                        lambda session, params: submitted.update(params) or "task-1")
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)

    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/loom/generate", json={
        "mode": "I2V", "prompt": "test", "images": ["733917871331404290"], "duration": 5})
    assert r.status_code == 200, r.get_data(as_text=True)

    assert uploaded, "the catalog reference was passed through instead of uploaded"
    assert img.name in uploaded[0]
    # The UPLOADED id must be what PixAI receives -- not the catalog id that it rejects.
    assert submitted["i2vPro"]["mediaId"] == "999000111222"


def test_gallery_ref_upload_is_cached_per_media_id(tmp_path, monkeypatch):
    """Referencing the same image twice in one R2V must upload it once, not per slot."""
    from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client

    (tmp_path / "2025-01").mkdir(parents=True, exist_ok=True)
    img = tmp_path / "2025-01" / "a_555.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "555", "filename": "2025-01/a_555.png", "created_at": "2026-06-18T05:24:56Z"}])

    calls, submitted = [], {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media",
                        lambda session, path, **k: calls.append(1) or "777")
    monkeypatch.setattr(core, "submit_generation",
                        lambda session, params: submitted.update(params) or "t")
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)

    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/loom/generate", json={
        "mode": "R2V", "prompt": "x", "images": ["555", "555"], "duration": 5})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert len(calls) == 1, "same media_id uploaded {} times".format(len(calls))
    assert submitted["referenceVideo"]["referenceImageMediaIds"] == ["777", "777"]


def _seed_one(tmp_path, mid="733917871331404290"):
    from pixai_gallery import CATALOG_FIELDS, save_catalog
    (tmp_path / "2025-01").mkdir(parents=True, exist_ok=True)
    (tmp_path / "2025-01" / ("s_%s.png" % mid)).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": mid, "filename": "2025-01/s_%s.png" % mid,
        "created_at": "2026-06-18T05:24:56Z"}])
    return mid


def test_every_input_path_uploads_the_catalog_reference(tmp_path, monkeypatch):
    """The first fix for the invalid_media_id bug patched ONLY the video route, leaving
    /api/enhance, /api/edit and /api/fix silently broken the same way -- the owner's next
    enhance died on it. PixAI refuses a generation-OUTPUT id as an INPUT on every one of
    these paths, so all four must resolve through _input_media_id.

    Parametrised deliberately: a new input endpoint that forgets to resolve is the exact
    way this returns, and this fails by name when it does."""
    from pixai_gallery import create_app
    from tests.conftest import login_test_client
    mid = _seed_one(tmp_path)
    seen = {}

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media", lambda s, path, **k: "999000111222")
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: seen.update(params=params) or "t1")
    monkeypatch.setattr(core, "submit_fixer",
                        lambda s, src, boxes: seen.update(fix_src=src) or "t2")
    monkeypatch.setattr(core, "build_panelplugin_parameters",
                        lambda src, wid: seen.update(enh_src=src) or {"p": 1})

    cli = login_test_client(create_app(tmp_path))

    # 1. video
    assert cli.post("/api/loom/generate", json={"mode": "I2V", "prompt": "x",
                    "images": [mid], "duration": 5}).status_code == 200
    assert seen["params"]["i2vPro"]["mediaId"] == "999000111222"

    # 2. enhance -- the path the owner's stuck job died on
    cli.post("/api/enhance", json={"source": mid, "workflow_id": "wf1"})
    assert seen.get("enh_src") == "999000111222", "enhance passed the raw catalog id"

    # 3. fix
    cli.post("/api/fix", json={"source": mid, "boxes": [{"x": 1, "y": 1, "w": 2, "h": 2}]})
    assert seen.get("fix_src") == "999000111222", "fix passed the raw catalog id"

    # 4. edit
    seen.pop("params", None)
    cli.post("/api/edit", json={"source": mid, "instruction": "make it night"})
    chat = (seen.get("params") or {}).get("chat") or {}
    ids = str(chat)
    assert "999000111222" in ids and mid not in ids, "edit passed the raw catalog id"


def test_pricing_never_uploads(tmp_path, monkeypatch):
    """/api/price only needs the SHAPE to compute a cost. Resolving there would upload
    the same file over and over while the user types, so _edit_params_from_payload
    takes `session` only on the real submit path."""
    from pixai_gallery import create_app
    from tests.conftest import login_test_client
    mid = _seed_one(tmp_path, "555111222333")
    uploads = []
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: uploads.append(1) or "nope")
    cli = login_test_client(create_app(tmp_path))
    cli.post("/api/price", json={"mode": "edit", "source": mid, "instruction": "x"})
    cli.post("/api/price", json={"mode": "I2V", "images": [mid], "duration": 5})
    assert not uploads, "pricing uploaded {} time(s) -- it must not".format(len(uploads))


def test_atomic_replace_retries_a_transient_windows_lock(monkeypatch, tmp_path):
    """os.replace on a just-written .part file can raise PermissionError [WinError 32] for a
    few hundred ms while antivirus / the Search Indexer holds it. _atomic_replace retries past
    the transient lock and succeeds -- and still re-raises if a file is genuinely stuck, so it
    never silently loses data. This is the root of the vanishing-video bug: the poster's rename
    threw here, before the clip was cataloged."""
    import pytest
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)   # don't actually wait
    real = core.os.replace

    src = tmp_path / "poster.jpg.part"; src.write_text("x")
    dst = tmp_path / "poster.jpg"
    n = {"c": 0}
    def flaky(s, d):
        n["c"] += 1
        if n["c"] < 3:                               # locked for the first two attempts
            raise PermissionError(32, "The process cannot access the file")
        return real(s, d)
    monkeypatch.setattr(core.os, "replace", flaky)
    core._atomic_replace(src, dst)
    assert dst.exists() and n["c"] == 3, "should retry past the transient lock, then succeed"

    # A permanently-stuck file still surfaces the real error rather than losing the write.
    stuck = tmp_path / "b.part"; stuck.write_text("y")
    monkeypatch.setattr(core.os, "replace",
                        lambda s, d: (_ for _ in ()).throw(PermissionError(32, "stuck")))
    with pytest.raises(PermissionError):
        core._atomic_replace(stuck, tmp_path / "b.jpg", attempts=3)


def test_download_video_task_catalogs_video_even_if_poster_fails(monkeypatch, tmp_path):
    """A WinError 32 on the poster's temp-file rename used to raise from download() BEFORE the
    video row was appended, so a finished clip was pulled to videos/ but never cataloged -- and
    the panel never showed the result. The poster is cosmetic; the video must still catalog.
    Bites: without the try/except around the poster block, _download_video_task raises here and
    save_catalog is never reached."""
    from pathlib import Path
    monkeypatch.setattr(core, "video_outputs",
                        lambda r: ([{"video_media_id": "V7", "poster_media_id": "P7", "seed": 1}],
                                   {"prompt": "p", "duration": 5}))
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "http://x/v.mp4"})
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("http://x/poster.png", {}))

    def _dl(session, url, stem, **kw):
        if "poster" in url:                          # the poster download hits the Windows lock
            raise PermissionError(32, "The process cannot access the file ... .jpg.part")
        p = Path(str(stem) + ".mp4"); p.write_bytes(b"\x00\x00\x00\x18ftypmp42"); return "ok", p
    monkeypatch.setattr(core, "download", _dl)
    monkeypatch.setattr(core, "video_poster_thumb", lambda v, t: False)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)

    saved = []
    monkeypatch.setattr(core, "save_catalog", lambda db, rows: saved.extend(rows))

    core._download_video_task(object(), {}, "T7", tmp_path, SimpleNamespace(name_length=60), {})
    assert any(r.get("media_id") == "V7" and r.get("is_video") == "1" for r in saved), \
        "the finished video must be cataloged even when the poster thumbnail fails"

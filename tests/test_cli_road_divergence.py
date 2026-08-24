"""Why the four CLI create runners are NOT folded onto the one payload road.

`core.build_request()` is the single producer of a PixAI `parameters` dict for the WEB
(/api/price + every create route), and the "one payload road" entry in DECISIONS.md
deliberately left the CLI create runners -- `run_generate`, `run_generate_video`,
`run_reference_video`, `run_edit_image` -- off it, because they "carry
preview/--confirm/--dump-params behaviour that is not a web payload's, and folding them in
blind on a spend path is how a refactor becomes an incident."

This file turns that prose into an executable boundary. It pins, per runner:

  * the PLAIN case where build_request DOES reproduce the runner's own params byte-for-byte
    (so a future fold knows exactly the subset that is safe), AND
  * the concrete inputs where it does NOT -- the reasons the fold was refused:
      - `--kaisuuken-id`  : the CLI builders EMBED `kaisuukenId` in the submitted params;
                            build_request's adapters force it to "" and `submit()` hard-codes
                            it to "" as well, so the one road cannot express a forced card.
      - `--params-json`   : every runner treats it as a RAW passthrough (the exact submit
                            shape, used for --task-id recovery banking); a web payload has no
                            such field.
      - clamps / defaults : the image road clamps width/height/steps/cfg/count and refuses an
                            empty model, and can only emit TURBO/HIGH priority; the CLI floors
                            dims but caps nothing, defaults an empty model to DEFAULT_GEN_MODEL,
                            and honours LOW/EXTRA-HIGH.
      - prompt max-length : the video web wrapper (build_shot_video_params) RAISES on a
                            >2000-char prompt at build time (a preview would abort); the CLI
                            i2v builder does not.
      - edit model resolve: `--edit-model` is a RAW model id on the CLI; the web edit road
                            reads it as a KEY ('edit-pro'/'reference-pro').

Every submitted-wire divergence a test locks here is a byte the deferral protects. If a
later increment folds a runner, the plain-case tests keep passing and the divergence tests
FAIL with a message that says which behaviour would have changed on a spend path -- which is
the signal to change the payload road or the flag, not to route it through blind.

No network: only the pure build functions are called (`_gen_parameters`,
`_gen_video_parameters`, `build_chat_edit_parameters`, `build_reference_video_parameters`,
`build_request` with resolve=None). `submit()` is exercised with its network legs stubbed.
"""
from types import SimpleNamespace as NS

import pytest

import moonglade_backup as core

P_TURBO, P_HIGH, P_LOW = core.PRIORITY_TURBO, core.PRIORITY_HIGH, core.PRIORITY_LOW


# =============================================================================
# image road -- run_generate builds via _gen_parameters(args)
# =============================================================================
def _img_args(**over):
    base = dict(params_json="", prompt="a moonwell", negative="", model="123456",
                width=512, height=512, steps=25, cfg=7.0, count=1, seed=None,
                priority=P_TURBO, mode="auto", prompt_helper=True, lora=None,
                ref_media_id="", ref_strength=0.55, enlarge=None, upscale=None,
                upscale_denoising_strength=None, upscale_denoising_steps=None,
                face_fix=False, quality_tag="", kaisuuken_id="", no_card=False)
    base.update(over)
    return NS(**base)


def _img_payload(a):
    """The best-faith args -> web-payload adapter for the image road. It maps every field
    build_request's image road reads; the divergences below are inherent to the two roads,
    not to a lossy adapter."""
    return {"prompt": a.prompt, "negative": a.negative, "version_id": a.model,
            "width": a.width, "height": a.height, "steps": a.steps, "cfg": a.cfg,
            "count": a.count, "seed": ("" if a.seed is None else str(a.seed)),
            "high_priority": (a.priority == P_HIGH), "mode": a.mode,
            "prompt_helper": a.prompt_helper,
            "loras": [{"version_id": v, "weight": w} for v, w in (a.lora or [])],
            "ref_media_id": a.ref_media_id, "no_card": a.no_card}


def _img_web(a):
    return core.build_request(_img_payload(a), mode="image", resolve=None, is_member=None).parameters


def test_image_plain_case_is_byte_identical():
    """The fold boundary: a plain, in-range, no-special-flag generate DOES round-trip
    through build_request unchanged. This is the subset a fold could ever be safe on."""
    a = _img_args()
    assert _img_web(a) == core._gen_parameters(a)


def test_image_diverges_on_kaisuuken_id():
    a = _img_args(kaisuuken_id="CARD-42")
    old = core._gen_parameters(a)
    assert old.get("kaisuukenId") == "CARD-42"          # the CLI embeds the forced card
    assert "kaisuukenId" not in _img_web(a)             # the web road cannot
    assert _img_web(a) != old


def test_image_diverges_on_params_json_passthrough():
    raw = '{"prompts": "verbatim", "modelId": "9", "batchSize": 1}'
    a = _img_args(params_json=raw)
    assert core._gen_parameters(a) == {"prompts": "verbatim", "modelId": "9", "batchSize": 1}
    assert _img_web(a) != core._gen_parameters(a)        # web has no raw-params field


def test_image_diverges_on_out_of_range_dimensions():
    a = _img_args(width=8000, steps=400, count=8)
    old = core._gen_parameters(a)
    web = _img_web(a)
    assert old["width"] == 8000 and web["width"] == 4096       # CLI floors only; web clamps
    assert old["samplingSteps"] == 400 and web["samplingSteps"] == 150
    assert old["batchSize"] == 8 and web["batchSize"] == 4


def test_image_diverges_on_empty_model():
    """CLI defaults an empty model to DEFAULT_GEN_MODEL and submits; the web road refuses
    ('pick a model', parameters None). Folding would turn a working default into a refusal."""
    a = _img_args(model="")
    assert core._gen_parameters(a)["modelId"] == core.DEFAULT_GEN_MODEL
    assert core.build_request(_img_payload(a), mode="image", resolve=None).parameters is None


def test_image_diverges_on_low_priority():
    """--low-priority / --priority 0 is a real CLI channel; the web adapter can only emit
    TURBO or HIGH, so it would silently re-price a deliberate standard-speed submit."""
    a = _img_args(priority=P_LOW)
    assert core._gen_parameters(a)["priority"] == P_LOW
    assert _img_web(a)["priority"] == P_TURBO


# =============================================================================
# i2v road -- run_generate_video builds via _gen_video_parameters(args)
# =============================================================================
def _vid_args(**over):
    base = dict(params_json="", prompt="a slow pan", image="7770", tail="", duration=5,
                video_model="v4.0.1", model="", vmode="professional", audio=False,
                audio_language="english", video_prompt_helper=False, camera_movement="",
                vchannel="private", negative="", kaisuuken_id="")
    base.update(over)
    return NS(**base)


def _vid_payload(a):
    return {"mode": "I2V", "images": [a.image] + ([a.tail] if a.tail else []),
            "prompt": a.prompt, "duration": a.duration,
            "video_model": a.video_model or "v4.0.1", "camera_movement": a.camera_movement,
            "quality": a.vmode, "generate_audio": a.audio, "audio_language": a.audio_language,
            "negative": a.negative, "is_private": (a.vchannel == "private"),
            "prompt_helper": a.video_prompt_helper}


def test_i2v_plain_case_is_byte_identical():
    a = _vid_args()
    web = core.build_request(_vid_payload(a), mode="video", resolve=None).parameters
    assert web == core._gen_video_parameters(a)


def test_i2v_diverges_on_kaisuuken_id():
    a = _vid_args(kaisuuken_id="CARD-9")
    old = core._gen_video_parameters(a)
    web = core.build_request(_vid_payload(a), mode="video", resolve=None).parameters
    assert old.get("kaisuukenId") == "CARD-9"
    assert "kaisuukenId" not in web


def test_i2v_diverges_on_prompt_over_maxlen():
    """A >2000-char prompt builds fine on the CLI (PixAI rejects it at submit) but the web
    video wrapper RAISES at build time -- so a fold would make a preview abort where it
    prints today."""
    a = _vid_args(prompt="x" * (core.VIDEO_PROMPT_MAXLEN + 100))
    core._gen_video_parameters(a)                       # no raise
    with pytest.raises(core.PixAIError):
        core.build_request(_vid_payload(a), mode="video", resolve=None)


# =============================================================================
# reference-video road -- run_reference_video builds via build_reference_video_parameters
# =============================================================================
def test_refvideo_diverges_on_nondefault_model_id():
    """run_reference_video passes NO model_id, so a non-default --video-model still submits
    the v4.0.1 numeric id (the builder default); the web R2V road recomputes the id for the
    chosen model. Different modelId on a spend path."""
    model = "v4.0"
    # exactly what run_reference_video._build() does with these args:
    cli = core.build_reference_video_parameters(
        "a pan @image1", image_media_ids=["55"], video_media_ids=[], audio_media_ids=[],
        model=model, duration=core._snap_video_duration(5, model), mode="professional",
        generate_audio=False, audio_language="english", is_private=True, kaisuuken_id="")
    web = core.build_request(
        {"mode": "R2V", "images": ["55"], "prompt": "a pan @image1", "duration": 5,
         "video_model": model, "quality": "professional", "is_private": True},
        mode="video", resolve=None).parameters
    assert cli["modelId"] == core.REFVIDEO_MODEL_ID              # v4.0.1's id, unconditionally
    assert web["modelId"] == core.video_model_id(model)         # the chosen model's id
    assert cli["modelId"] != web["modelId"]


# =============================================================================
# edit road -- run_edit_image builds via build_chat_edit_parameters + _edit_config_from_args
# =============================================================================
def _edit_args(**over):
    base = dict(params_json="", prompt="make it night", edit_model="", edit_resolution="1K",
                edit_aspect="3:4", edit_quality="medium", kaisuuken_id="")
    base.update(over)
    return NS(**base)


def _edit_old(a, src="5550"):
    cfg = core._edit_config_from_args(a)
    return core.build_chat_edit_parameters(
        a.prompt, [src], model_id=cfg["model_id"], resolution=cfg["resolution"],
        aspect_ratio=cfg["aspect_ratio"], quality=cfg["quality"], kaisuuken_id=cfg["kaisuuken_id"])


def _edit_web(a, src="5550"):
    return core.build_request(
        {"source": src, "sources": [src], "instruction": a.prompt,
         "edit_model": (a.edit_model or "edit-pro"), "resolution": a.edit_resolution,
         "aspect": a.edit_aspect, "quality": a.edit_quality},
        mode="edit", resolve=None).parameters


def test_edit_plain_case_is_byte_identical():
    a = _edit_args()
    assert _edit_web(a) == _edit_old(a)


def test_edit_diverges_on_kaisuuken_id():
    a = _edit_args(kaisuuken_id="CARD-7")
    old = _edit_old(a)
    assert old["chat"].get("kaisuukenId") is None       # kaisuukenId is top-level, not in chat
    assert old.get("kaisuukenId") == "CARD-7"
    assert "kaisuukenId" not in _edit_web(a)


def test_edit_diverges_on_raw_model_id():
    """`--edit-model` is a RAW model id on the CLI; the web edit road reads it as a KEY, so a
    raw Reference-Pro id lands as Reference-Pro (2K, no quality knob) on the CLI and falls
    back to Edit-Pro (1K/medium) on the web road -- a different model AND config."""
    ref_id = core.EDIT_MODELS["reference-pro"]["model_id"]
    a = _edit_args(edit_model=ref_id)
    old, web = _edit_old(a), _edit_web(a)
    assert old["chat"]["modelId"] == ref_id
    assert web["chat"]["modelId"] == core.EDIT_PRO_MODEL_ID
    assert old["chat"]["modelConfig"] != web["chat"]["modelConfig"]


# =============================================================================
# submit() cannot express a forced card either -- the other half of --kaisuuken-id
# =============================================================================
def test_submit_road_cannot_force_a_kaisuuken_id(monkeypatch):
    """`submit()` builds the free-card check with a hard-coded kaisuuken_id="" (only its
    no_card flag is threaded), so even if a runner shared build_request it could not carry
    `--kaisuuken-id` through the shared submit. Proven by capturing the namespace submit()
    hands _apply_kaisuuken, with every network leg stubbed."""
    seen = {}
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation", lambda s, p: "TASK-1")
    monkeypatch.setattr(core, "_apply_kaisuuken",
                        lambda s, p, args: seen.setdefault("args", args))
    req = core.GenerationRequest(mode="image", parameters={"prompts": "x"}, no_card=False)
    out = core.submit(None, req)
    assert out == {"task_id": "TASK-1"}
    assert seen["args"].kaisuuken_id == ""              # no seam to force a specific card

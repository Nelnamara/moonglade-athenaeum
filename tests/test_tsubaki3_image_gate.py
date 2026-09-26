"""The Tsubaki.3 / Flash / DiT image gate (SCOPE_2026-09-26_tsubaki3-parity-fixes, lane G).

One gate, applied ONCE at build (`build_request`'s image road through RequestResolver.gate,
and the CLI's run_generate right after _gen_parameters), so the dict that is quoted,
card-matched and submitted is one object. What it does, per the probe of 2026-09-26:

  G1  sizes onto the model's grid and range (16 on every DiT family, /size-config's union)
  G2  strips what the model does not take (/features "off", and the MMDiT / user-DiT rule)
  G3  sends a reference as a context image on MMDIT26B -- and refuses it beside a LoRA
  G4  the Quality Tag booster sends the version's own tag (build time, never the gate)
  G5  Tsubaki.3's default negative comes from routedNegativePrompts
  G6  the MMDIT26B prompt helper is a creativity level
  G7  quote, card and submit read the one gated dict
  G8  USER_DIT26B_MODEL joins the DiT tables
  G9  a hidden profile is filtered from the drawer's list only
  G10 LoRA weights are held to the architecture's range

Every PixAI read is faked at `_rest_get` with bodies shaped like the 2026-09-26 captures
(features, size-config, inference profiles). No prompt text from any real task appears here:
the twelve wire shapes are rebuilt with placeholders.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import moonglade_backup as core

from tests.conftest import login_client

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

T3 = "2024383379556065549"          # Tsubaki.3 (MMDIT26B)
FLASH = "2050048243034896798"       # Tsubaki.3 Flash (MMDIT26B)
T2 = "V-T2"                         # an MMDIT26A version (Tsubaki.2's architecture)
UD3 = "V-UD3"                       # a user-trained DiT.3 (USER_DIT26B)
SDXL = "V-SDXL"
BLIND = "V-BLIND"                   # a version whose /features never answers

# auth/T3v_features.json, statuses only (source/mutuallyExclusiveWith do not drive the gate).
T3_STATUS = {
    "lora": "on", "styleMix": "off", "controlnet": "off", "lowPriority": "on",
    "lightning": "off", "shift": "off", "rescaleCfg": "off", "upscale": "off",
    "enableADetailer": "off", "vae": "off", "clipSkip": "off", "ipAdapter": "off",
    "refImage": "off", "negativePrompt": "on", "cfgScale": "off", "styleKey": "on",
    "watermark": "off", "inferenceProfile": "on", "samplingMethod": "off",
    "samplingSteps": "off", "contextImages": "on", "colorPalette": "on"}
# auth/Flashv_features.json differs only in negativePrompt (off, source "version").
FLASH_STATUS = dict(T3_STATUS, negativePrompt="off")


def features(model_type, status):
    return {"modelType": model_type,
            "features": [{"featureName": k, "status": v, "source": "modelType",
                          "mutuallyExclusiveWith": []} for k, v in status.items()]}


# auth/T3v_size-config.json == Flashv_size-config.json (presets omitted -- the gate reads the
# ranges only).
SIZE_CONFIG = {"ranges": [
    {"name": "XL", "minWidth": 512, "maxWidth": 2496, "minHeight": 512, "maxHeight": 2496,
     "step": 16, "accessStatus": "available"},
    {"name": "L", "minWidth": 512, "maxWidth": 2200, "minHeight": 512, "maxHeight": 2200,
     "step": 16, "accessStatus": "available"},
    {"name": "M", "minWidth": 512, "maxWidth": 1800, "minHeight": 512, "maxHeight": 1800,
     "step": 16, "accessStatus": "available"}]}
T3_RULE = {"step": 16, "lo": 512, "hi": 2496}

T3_PROFILES = {"profiles": [{"profileName": "pro", "profileFlag": "default"},
                            {"profileName": "ultra", "profileFlag": "membershipOnly"}]}
FLASH_PROFILES = {"profiles": [{"profileName": "flash", "profileFlag": "default"}]}

MODELS = {
    T3: {"features": features("MMDIT26B_MODEL", T3_STATUS), "size-config": SIZE_CONFIG,
         "inference-profiles": T3_PROFILES},
    FLASH: {"features": features("MMDIT26B_MODEL", FLASH_STATUS), "size-config": SIZE_CONFIG,
            "inference-profiles": FLASH_PROFILES},
    T2: {"features": features("MMDIT26A_MODEL", {"upscale": "on", "enableADetailer": "on",
                                                 "negativePrompt": "on"}),
         "size-config": SIZE_CONFIG, "inference-profiles": T3_PROFILES},
    UD3: {"features": features("USER_DIT26B_MODEL", {}), "size-config": None,
          "inference-profiles": {"profiles": []}},
    SDXL: {"features": features("SDXL_MODEL", {}), "size-config": {"ranges": []},
           "inference-profiles": {"profiles": []}},
    BLIND: {"features": core.PixAIError("503"), "size-config": core.PixAIError("503"),
            "inference-profiles": core.PixAIError("503")},
}


class FakeRest:
    """_rest_get, answering the version-keyed reads and /task-price; refusing anything else
    by path so an unexpected read fails loudly instead of reaching a network."""

    def __init__(self, models=None, price=4000):
        self.models = dict(MODELS if models is None else models)
        self.price = price
        self.calls = []
        self.priced = []

    def __call__(self, session, path, params=None, **k):
        self.calls.append(path)
        if path == "/task-price":
            self.priced.append(dict(params or {}))
            return {"actualPrice": self.price}
        m = re.match(r"^/generation-model/([^/]+)/(features|size-config|inference-profiles)$",
                     path)
        if m and m.group(1) in self.models:
            body = self.models[m.group(1)].get(m.group(2))
            if isinstance(body, Exception):
                raise body
            if body is None:
                raise core.PixAIError("404 " + path)
            return body
        raise core.PixAIError("unexpected GET " + path)


@pytest.fixture
def rest(monkeypatch):
    fake = FakeRest()
    monkeypatch.setattr(core, "_rest_get", fake)
    return fake


def gate(params):
    return core._gate_image_params(object(), params)


def img(vid, **kw):
    """A plain app-built image submit, as _gen_parameters shapes it."""
    p = {"prompts": "<prompt>", "naturalPrompts": "<prompt>", "modelId": vid,
         "width": 1024, "height": 1024, "samplingSteps": 25, "cfgScale": 7.0,
         "batchSize": 1, "priority": core.PRIORITY_TURBO,
         "promptHelper": {"withStage": True, "userWantToEnable": True,
                          "forcePromptHelperDetectionSide": "server"}}
    p.update(kw)
    return p


# --- the drawer's own aspect x size grid, computed the way genCore.dims() does -------------

ASPECTS = [("1:1", 1), ("3:4", 3 / 4), ("4:3", 4 / 3), ("2:3", 2 / 3), ("3:2", 3 / 2),
           ("9:16", 9 / 16), ("16:9", 16 / 9), ("3:1", 3)]
SIZES = [768, 1024, 1536, 2048]


def _d8(n):
    """genCore.js d8: Math.round(n / 8) * 8 clamped to 64..4096 (Math.round is half-up)."""
    import math
    return max(64, min(4096, int(math.floor(n / 8 + 0.5)) * 8))


def drawer_raw(r, size):
    return (_d8(size), _d8(size / r)) if r >= 1 else (_d8(size * r), _d8(size))


# =============================================================================
# G1 -- the size grid and range
# =============================================================================

NINE_FAILING = {
    ("2:3", 1024): (688, 1024), ("3:2", 1024): (1024, 688),
    ("2:3", 2048): (1376, 2048), ("3:2", 2048): (2048, 1376),
    ("9:16", 768): (512, 912), ("16:9", 768): (912, 512),
    ("3:1", 768): (1536, 512), ("3:1", 1024): (1520, 512), ("3:1", 2048): (2048, 688),
}


def test_the_nine_failing_drawer_presets_snap_and_the_rest_do_not_move(rest):
    """PROBE T3-02: nine of the drawer's 32 aspect x size presets fail Tsubaki.3's rule
    (off the /16 grid, or a side under 512). Exactly those nine move, to the app's own snap;
    the other 23 pass through untouched -- the same object, no receipt."""
    moved = {}
    for label, r in ASPECTS:
        for size in SIZES:
            w, h = drawer_raw(r, size)
            p = img(T3, width=w, height=h, inferenceProfile="pro")
            p.pop("samplingSteps"), p.pop("cfgScale")
            p["promptHelper"] = {"creativity": "medium",
                                 "forcePromptHelperDetectionSide": "server"}
            p.pop("naturalPrompts")
            out, adjusted = gate(p)
            if (out["width"], out["height"]) != (w, h):
                moved[(label, size)] = (out["width"], out["height"])
                assert {a["field"] for a in adjusted} <= {"width", "height"}
            else:
                assert out is p and adjusted == [], (label, size)
    assert moved == NINE_FAILING


def test_on_grid_sizes_never_move_and_768x432_becomes_912x512_with_a_receipt(rest):
    """2048x1152 (the owner's own accepted size), 816x2448 (PixAI's own XL 1:3 preset, above
    model-config's 2048) and 1088x1824 (a site auto-size) pass untouched. 768x432 is on the
    16 grid but under 512 -- the short side goes up to 512 and the long side follows."""
    for w, h in ((2048, 1152), (816, 2448), (1088, 1824)):
        p = img(T3, width=w, height=h)
        out, adjusted = gate(p)
        assert (out["width"], out["height"]) == (w, h)
        assert not [a for a in adjusted if a["field"] in ("width", "height")]
    out, adjusted = gate(img(T3, width=768, height=432))
    assert (out["width"], out["height"]) == (912, 512)
    by = {a["field"]: a for a in adjusted}
    assert by["width"]["asked"] == 768 and by["width"]["used"] == 912
    assert by["height"]["asked"] == 432 and by["height"]["used"] == 512
    assert "16 px grid from 512 to 2496" in by["width"]["why"]


def test_the_dit_step_table_and_step_aligned_bounds():
    for t in ("DIT7_MODEL", "DIT7B_MODEL", "MMDIT26A_MODEL", "MMDIT26B_MODEL",
              "USER_DIT26A_MODEL", "USER_DIT26B_MODEL"):
        assert core._size_rule(t)["step"] == 16, t
    for t in ("SDXL_MODEL", "SD_V1_MODEL", "DIT9_MODEL", ""):
        assert core._size_rule(t)["step"] == 8, t
    # the UNION of the ranges, aligned inward to the step
    assert core._size_rule("MMDIT26B_MODEL", [(500, 2500, 510, 2490), (512, 1800, 512, 1800)]) \
        == {"step": 16, "lo": 512, "hi": 2496}
    assert core._size_rule("MMDIT26B_MODEL", [(512, 2496, 512, 2496)]) == T3_RULE
    # no ranges -> today's 64..4096, on the step
    assert core._size_rule("MMDIT26A_MODEL", None) == {"step": 16, "lo": 64, "hi": 4096}
    assert core._size_rule("SDXL_MODEL", []) == {"step": 8, "lo": 64, "hi": 4096}
    # a published restrictions step wins (the drawer's rule; none is published today)
    assert core._size_rule("SDXL_MODEL", None, {"width": {"step": 32}})["step"] == 32
    # rounding is half-UP, never Python's half-to-even: 680 -> 688, 1016 -> 1024
    assert core._snap_size(1024, 680, T3_RULE) == (1024, 688)
    assert core._snap_size(1016, 1016, {"step": 16, "lo": 64, "hi": 4096}) == (1024, 1024)
    # the long side wins when both bounds cannot hold (a 6:1 frame)
    assert core._snap_size(3072, 512, T3_RULE) == (2496, 512)


def test_a_dit_version_without_a_size_config_answer_snaps_to_the_step_only(rest):
    """No /size-config answer -> step only, with today's 64..4096 clamp: 1020 -> 1024 on a
    user-trained DiT.3, and a sub-512 side is left alone (there is no range to enforce)."""
    out, adjusted = gate(img(UD3, width=1020, height=400))
    assert (out["width"], out["height"]) == (1024, 400)
    assert [a["field"] for a in adjusted if a["field"] in ("width", "height")] == ["width"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_and_python_give_identical_results_for_all_32_presets(rest, tmp_path):
    """The drawer's '-> W x H px' line is what is sent: genCore.dims() with the model's
    size_rule, and the server's gate on the drawer's own /8 output, agree on every preset --
    plus a few custom W x H entries. Runs the real genCore.js under node."""
    gen = (ROOT / "gallery" / "src" / "gen" / "genCore.js").as_uri()
    customs = [(1000, 3000), (4000, 300), (700, 700), (2500, 2500)]
    script = tmp_path / "parity.mjs"
    script.write_text(
        "import { ASPECTS, SIZES, dims, snapSize } from " + json.dumps(gen) + ";\n"
        "const rule = " + json.dumps(T3_RULE) + ";\n"
        "const customs = " + json.dumps(customs) + ";\n"
        "const out = [];\n"
        "for (const [label, r] of ASPECTS) for (const size of SIZES) {\n"
        "  const s = { aspect: r, size, customW: '', customH: '' };\n"
        "  const raw = dims(s);\n"
        "  const snapped = dims({ ...s, model: { size_rule: rule } });\n"
        "  out.push({ label, size, raw: [raw.width, raw.height],\n"
        "             snapped: [snapped.width, snapped.height] });\n"
        "}\n"
        "for (const [w, h] of customs) {\n"
        "  const s = { aspect: 1, size: 1024, customW: String(w), customH: String(h) };\n"
        "  const raw = dims(s);\n"
        "  const snapped = dims({ ...s, model: { size_rule: rule } });\n"
        "  out.push({ label: 'custom', size: 0, raw: [raw.width, raw.height],\n"
        "             snapped: [snapped.width, snapped.height] });\n"
        "}\n"
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    # stdin from devnull and output to a file, as tests/test_js_syntax.py does: a pipe-less
    # spawn is what works under every runner here (Windows hands some a dead stdin handle).
    out_file, err_file = tmp_path / "parity.out", tmp_path / "parity.err"
    try:
        with open(os.devnull, "rb") as nul, open(out_file, "wb") as fo, \
                open(err_file, "wb") as fe:
            rc = subprocess.call([NODE, str(script)], stdin=nul, stdout=fo, stderr=fe,
                                 timeout=60)
    except OSError as e:
        pytest.skip("cannot spawn node in this environment: {}".format(e))
    assert rc == 0, err_file.read_text(encoding="utf-8", errors="replace")
    rows = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(rows) == 32 + len(customs)
    for row in rows:
        if row["label"] != "custom":
            r = dict(ASPECTS)[row["label"]]
            assert tuple(row["raw"]) == drawer_raw(r, row["size"]), row
        assert tuple(row["snapped"]) == core._snap_size(*row["raw"], T3_RULE), row
        # ...and the gate, handed the drawer's own /8 output, sends exactly that
        out, _adj = gate(img(T3, width=row["raw"][0], height=row["raw"][1]))
        assert [out["width"], out["height"]] == row["snapped"], row
    assert sum(1 for x in rows[:32] if x["raw"] != x["snapped"]) == 9


# =============================================================================
# G2 -- strip what the model does not take
# =============================================================================

HIRES = {"upscale": 1.5, "upscaleDenoisingStrength": 0.6, "upscaleDenoisingSteps": 25,
         "upscaleSampler": ""}


def test_each_feature_that_is_off_strips_its_fields_with_a_receipt(rest):
    out, adjusted = gate(img(FLASH, negativePrompts="<negative>", enableADetailer=True,
                             **HIRES))
    for k in ("negativePrompts", "enableADetailer", *HIRES):
        assert k not in out, k
    by = {a["field"]: a for a in adjusted}
    assert by["negativePrompts"] == {"field": "negativePrompts", "asked": "<negative>",
                                     "used": None,
                                     "why": "this model takes no negative prompt"}
    assert set(HIRES) <= set(by) and by["enableADetailer"]["used"] is None
    # Tsubaki.3 takes a negative prompt: kept
    out3, _ = gate(img(T3, negativePrompts="<negative>"))
    assert out3["negativePrompts"] == "<negative>"


def test_a_feature_absent_from_the_list_is_on_and_only_literal_off_strips(rest):
    rest.models["V-SPARSE"] = {"features": features("MMDIT26B_MODEL", {"negativePrompt": "Off"}),
                               "size-config": SIZE_CONFIG, "inference-profiles": None}
    out, adjusted = gate(img("V-SPARSE", negativePrompts="<negative>"))
    assert out["negativePrompts"] == "<negative>"     # "Off" is not the literal "off"
    assert not [a for a in adjusted if a["field"] == "negativePrompts"]


def test_enlarge_is_never_stripped_and_features_never_own_steps_or_cfg(rest):
    """enlarge/enlargeModel ride every model (the site keeps them). samplingSteps/cfgScale
    belong to the profile branch alone: /features saying them 'off' strips nothing when the
    profile set is unknown -- they drive the SDXL price."""
    rest.models[T3] = dict(MODELS[T3], **{"inference-profiles": core.PixAIError("503")})
    out, _ = gate(img(T3, enlarge=1.5, enlargeModel="R-ESRGAN 4x+ Anime6B"))
    assert out["enlarge"] == 1.5 and out["enlargeModel"] == "R-ESRGAN 4x+ Anime6B"
    assert out["samplingSteps"] == 25 and out["cfgScale"] == 7.0


def test_the_model_type_rule_strips_hires_and_face_fix_on_mmdit_and_user_dit(rest):
    """PixAI never sends Hires or Face Fix to MMDIT26A/B or USER_DIT26A/B, whatever the
    feature list says -- here T2's features say both are ON and they still go."""
    for vid in (T2, UD3):
        out, adjusted = gate(img(vid, enableADetailer=True, **HIRES))
        for k in ("enableADetailer", *HIRES):
            assert k not in out, (vid, k)
        assert all(a["used"] is None for a in adjusted
                   if a["field"] in ("enableADetailer", *HIRES))
    # SDXL keeps both
    out, _ = gate(img(SDXL, enableADetailer=True, **HIRES))
    assert out["enableADetailer"] is True and out["upscale"] == 1.5


def test_an_unanswered_features_read_changes_nothing(rest):
    p = img(BLIND, enableADetailer=True, negativePrompts="<negative>", width=777, height=333,
            mediaId="M1", strength=0.5, **HIRES)
    out, adjusted = gate(p)
    assert out is p and adjusted == []


# =============================================================================
# The Upscale road is exempt
# =============================================================================

@pytest.mark.parametrize("vid", [T2, T3])
@pytest.mark.parametrize("method", ["enlarge", "upscale"])
def test_the_upscale_road_passes_untouched_on_mmdit26a_and_b(vid, method, rest):
    """An Upscale-panel request (a top-level mediaId with enlarge or upscale) is never
    snapped, stripped or turned into a context image -- G3 there would bill a new Tsubaki.3
    generation for an Upscale click. The 2026-08-25 profile branch still applies."""
    p = {"modelId": vid, "prompts": "", "mediaId": "M1", "strength": 0.55,
         "width": 1000, "height": 1000, "batchSize": 1, "priority": core.PRIORITY_TURBO,
         method: 1.5}
    if method == "upscale":
        p.update(upscaleDenoisingStrength=0.6, upscaleDenoisingSteps=25, upscaleSampler="")
    out, adjusted = gate(p)
    assert adjusted == []
    assert out["mediaId"] == "M1" and out["strength"] == 0.55 and out[method] == 1.5
    assert "contextImages" not in out
    assert (out["width"], out["height"]) == (1000, 1000)
    if method == "upscale":
        assert out["upscaleDenoisingStrength"] == 0.6
    assert out["inferenceProfile"] == "pro"          # the profile branch, as before


def test_the_upscale_panel_payload_rides_the_road_untouched(rest):
    req = core.build_request({"version_id": T3, "prompt": "", "ref_media_id": "M1",
                              "ref_strength": 0.55, "enlarge": 2, "width": 1000,
                              "height": 1000},
                             mode="image", resolve=core.RequestResolver(
                                 gate=core.gate_resolver(object())))
    p = req.parameters
    assert p["mediaId"] == "M1" and p["enlarge"] == 2.0 and "contextImages" not in p
    assert req.adjusted == []


# =============================================================================
# G3 -- a reference on MMDIT26B becomes a context image
# =============================================================================

def _road(payload, **kw):
    return core.build_request(payload, mode="image", resolve=core.RequestResolver(
        gate=core.gate_resolver(object())), **kw)


@pytest.mark.parametrize("vid", [T3, FLASH])
def test_a_reference_on_mmdit26b_goes_out_as_a_context_image(vid, rest):
    req = _road({"version_id": vid, "prompt": "<prompt>", "negative": "<negative>",
                 "ref_media_id": "M1", "ref_strength": 0.7, "prompt_helper": False,
                 "width": 1632, "height": 912})
    p = req.parameters
    assert p["contextImages"] == ["M1"]
    assert "mediaId" not in p and "strength" not in p and "negativePrompts" not in p
    # effective context images force the helper to medium -- a receipt, because the user
    # had it off
    assert p["promptHelper"] == {"creativity": "medium",
                                 "forcePromptHelperDetectionSide": "server"}
    by = {a["field"]: a for a in req.adjusted}
    assert by["negativePrompts"]["used"] is None
    assert by["promptHelper"] == {"field": "promptHelper", "asked": "off", "used": "medium",
                                  "why": by["promptHelper"]["why"]}


def test_a_reference_keeps_todays_shape_where_context_images_do_not_apply(rest):
    rest.models["V-NOCTX"] = {"features": features("MMDIT26B_MODEL",
                                                   dict(T3_STATUS, contextImages="off")),
                              "size-config": SIZE_CONFIG, "inference-profiles": None}
    rest.models["V-ABSENT"] = {"features": features("MMDIT26B_MODEL", {"lora": "on"}),
                               "size-config": SIZE_CONFIG, "inference-profiles": None}
    for vid in (T2, "V-NOCTX", "V-ABSENT", BLIND):
        out, _ = gate(img(vid, mediaId="M1", strength=0.5))
        assert out["mediaId"] == "M1" and out["strength"] == 0.5, vid
        assert "contextImages" not in out, vid


def test_a_reference_plus_a_lora_on_tsubaki3_is_refused_never_trimmed(rest):
    """The site silently drops the context image when a LoRA is present; this refuses at
    build time instead (the LoRA-cap precedent) -- the badge shows it, nothing is spent."""
    payload = {"version_id": T3, "prompt": "<prompt>", "ref_media_id": "M1",
               "loras": [{"version_id": "L1", "weight": 0.7}]}
    with pytest.raises(core.PixAIError) as err:
        _road(payload)
    assert str(err.value) == "Tsubaki.3 can't combine a reference image with LoRAs — remove one"
    # the backstop inside price_task fails soft (no price), never raises
    args = core._gen_args_from_web_payload(payload)
    args.model = T3
    raw = core._gen_parameters(args)
    assert raw["mediaId"] == "M1" and raw["lora"] == {"L1": 0.7}
    assert core.price_task(object(), raw) is None


def test_context_images_are_priced(rest):
    """_PRICE_NESTED carries contextImages (live quote: 5,100 for one, 6,000 for two)."""
    assert "contextImages" in core._PRICE_NESTED
    core.price_task(object(), {"modelId": T3, "contextImages": ["A", "B"],
                               "inferenceProfile": "pro", "width": 1632, "height": 912,
                               "promptHelper": {"creativity": "medium",
                                                "forcePromptHelperDetectionSide": "server"}})
    assert rest.priced[-1]["contextImages"] == json.dumps(["A", "B"])


# =============================================================================
# G6 -- the MMDIT26B prompt helper is a creativity level
# =============================================================================

def test_prompt_helper_on_and_off_become_creativity_levels(rest):
    on, _ = gate(img(T3))
    assert on["promptHelper"] == {"forcePromptHelperDetectionSide": "server",
                                  "creativity": "medium"}
    assert on["extra"] == {"naturalPrompts": "<prompt>"} and "naturalPrompts" not in on
    off_in = img(T3, promptHelper={"withStage": False, "userWantToEnable": False,
                                   "forcePromptHelperDetectionSide": "server"})
    off, adjusted = gate(off_in)
    assert off["promptHelper"] == {"forcePromptHelperDetectionSide": "server",
                                   "creativity": "off"}
    assert "extra" not in off and "naturalPrompts" not in off
    assert not [a for a in adjusted if a["field"] == "promptHelper"]


def test_prompt_helper_merges_into_extra_and_never_mutates_the_caller(rest):
    ph = {"withStage": True, "userWantToEnable": True, "forcePromptHelperDetectionSide": "server"}
    extra = {"keep": 1}
    p = img(T3, promptHelper=ph, extra=extra)
    out, _ = gate(p)
    assert out["extra"] == {"keep": 1, "naturalPrompts": "<prompt>"}
    assert ph == {"withStage": True, "userWantToEnable": True,
                  "forcePromptHelperDetectionSide": "server"} and extra == {"keep": 1}
    assert p["naturalPrompts"] == "<prompt>" and "creativity" not in p["promptHelper"]


def test_prompt_helper_is_idempotent_and_other_architectures_keep_the_legacy_shape(rest):
    site = img(T3, promptHelper={"enable": True, "creativity": "low",
                                 "forcePromptHelperDetectionSide": "server"})
    site.pop("naturalPrompts")
    site.pop("samplingSteps"), site.pop("cfgScale")
    site["inferenceProfile"] = "pro"
    out, adjusted = gate(site)
    assert out is site and adjusted == []
    legacy, _ = gate(img(T2))
    assert legacy["promptHelper"]["userWantToEnable"] is True
    assert "creativity" not in legacy["promptHelper"]


# =============================================================================
# G7 -- gate(gate(p)) is gate(p) on the twelve Tsubaki.3 wire shapes
# =============================================================================

def _wire_shapes():
    """The five app-built and seven site-built Tsubaki.3 tasks of 2026-09-17/18
    (probe/tasks), rebuilt field for field with every text and id replaced by a
    placeholder. Server-normalised records, as the probe notes: string seeds, a filled-in
    promptHelper.enable, extra.naturalPrompts."""
    flags = {"isPrivate": False, "enablePreview": False, "hidePrompts": False}
    legacy = {"enable": True, "withStage": True, "userWantToEnable": True,
              "forcePromptHelperDetectionSide": "server"}
    loras3 = ["L1", "L2", "L3"]
    loras5 = loras3 + ["L4", "L5"]

    def lora(ids):
        return {"lora": {i: 0.7 for i in ids},
                "loraParameters": [{"weight": 0.7, "versionId": i} for i in ids]}

    def app(priority, batch, profile, **kw):
        p = {"priority": priority, "width": 2048, "height": 1152, "prompts": "<prompt>",
             "negativePrompts": "<negative>", "batchSize": batch,
             "inferenceProfile": profile, "promptHelper": dict(legacy), "modelId": T3,
             "extra": {"naturalPrompts": "<natural>"}, **flags}
        p.update(kw)
        return p
    apps = [
        app(500, 4, "ultra"),
        app(500, 1, "pro", seed="1", kaisuukenId="card-a", **lora(loras3)),
        app(1000, 1, "pro", seed="1", kaisuukenId="card-b", **lora(loras3)),
        app(1000, 1, "ultra", seed="1", **lora(loras3)),
        app(1000, 2, "ultra", seed="2", qualityTag={"prefix": "<tag>"},
            enableADetailer=True, **lora(loras5)),
    ]

    def site(w, h, ctx):
        return {"priority": 1000, "width": w, "height": h, "prompts": "<prompt>",
                "inferenceProfile": "pro", "qualityTag": {"prefix": "", "suffix": ""},
                "promptHelper": {"enable": True, "creativity": "medium",
                                 "forcePromptHelperDetectionSide": "server"},
                "controlNets": [], "contextImages": list(ctx), "modelId": T3,
                "extra": {"naturalPrompts": "<natural>"}, **flags}
    sites = [site(1088, 1824, ["C1"]), site(1632, 912, ["C1"]), site(1632, 912, ["C1"]),
             site(1632, 912, ["C1"]), site(1632, 912, ["C1"]), site(1632, 912, ["C1", "C2"]),
             site(1088, 1792, ["C2"])]
    return apps, sites


def test_the_gate_is_idempotent_on_the_twelve_tsubaki3_wire_shapes(rest):
    apps, sites = _wire_shapes()
    assert len(apps) == 5 and len(sites) == 7
    for p in apps + sites:
        g1, _a1 = gate(p)
        g2, a2 = gate(g1)
        assert g2 is g1 and a2 == []
        # the backstop form hands the already-gated dict straight back too
        assert core._gate_params_for_model(object(), g1) is g1
    # the site's own shapes are already in the site's form: untouched, same object
    for p in sites:
        out, adjusted = gate(p)
        assert out is p and adjusted == []
    # the app-built legacy helper converts, and Face Fix leaves Tsubaki.3 with a receipt
    out, adjusted = gate(apps[4])
    assert out["promptHelper"] == {"forcePromptHelperDetectionSide": "server",
                                   "creativity": "medium"}
    assert "enableADetailer" not in out
    assert [a["field"] for a in adjusted] == ["enableADetailer"]


# =============================================================================
# G7 -- price(), submit() and run_generate card-match the gated dict
# =============================================================================

CARD = {"id": "card-1", "name": "Tsubaki.3", "total": 3, "consumeAmount": 1,
        "covered": True, "templateId": "tpl-1", "expiresAt": "2026-12-31T00:00:00Z"}


def test_price_and_submit_card_match_and_send_the_gated_dict(rest, monkeypatch):
    matched, sent = [], []
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: matched.append(params) or dict(CARD))
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "gql_mutate",
                        lambda s, q, v=None: sent.append(v["parameters"])
                        or {"createGenerationTask": {"id": "T1"}})
    req = _road({"version_id": T3, "prompt": "<prompt>", "ref_media_id": "M1",
                 "width": 768, "height": 432})
    gated = req.parameters
    assert gated["contextImages"] == ["M1"] and (gated["width"], gated["height"]) == (912, 512)

    quoted = core.price(object(), req)
    assert matched[0] is gated                       # the badge's card verdict: gated dict
    assert quoted["free"] is True and quoted["cost"] == 4000
    assert rest.priced[-1]["contextImages"] == json.dumps(["M1"])
    assert rest.priced[-1]["width"] == 912
    assert {a["field"] for a in quoted["adjusted"]} >= {"width", "height"}

    assert core.submit(object(), req) == {"task_id": "T1"}
    assert matched[1] is gated                       # the spend's card check: same object
    assert sent[0] is gated                          # ...and the backstop sent it as-is
    assert gated["kaisuukenId"] == "card-1"


def _cli_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), params_json="", prompt="<prompt>", negative="",
                model=T3, width=768, height=432, steps=25, cfg=7.0, count=1, seed=None,
                priority=core.PRIORITY_TURBO, mode="auto", prompt_helper=True, lora=None,
                ref_media_id="", ref_strength=0.55, enlarge=None, upscale=None,
                upscale_denoising_strength=None, upscale_denoising_steps=None,
                face_fix=True, quality_tag="", kaisuuken_id="", no_card=False,
                confirm=True, task_id="", token=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _Stop(Exception):
    pass


def test_run_generate_card_matches_and_submits_the_gated_dict(rest, monkeypatch, tmp_path):
    matched, sent = [], []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: matched.append(params) or dict(CARD))
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: sent.append(params) or "T1")

    def stop(*a, **k):
        raise _Stop()
    monkeypatch.setattr(core, "_poll_task_status", stop)
    with pytest.raises(_Stop):
        core.run_generate(_cli_args(tmp_path))
    assert sent[0] is matched[0]
    assert (sent[0]["width"], sent[0]["height"]) == (912, 512)
    assert "enableADetailer" not in sent[0]
    assert sent[0]["promptHelper"]["creativity"] == "medium"


def test_run_generate_preview_prints_and_card_checks_the_gated_dict(rest, monkeypatch,
                                                                     tmp_path, capsys):
    matched = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, params, **k: matched.append(params) or None)
    assert core.run_generate(_cli_args(tmp_path, confirm=False)) == {"submitted": False}
    out = capsys.readouterr().out
    shown = json.loads(out.split("===\n", 1)[1].split("\n  adjusted:", 1)[0])["parameters"]
    assert (shown["width"], shown["height"]) == (912, 512)
    assert "adjusted: width 768 -> 912" in out
    assert "adjusted: enableADetailer True -> off" in out
    assert matched and (matched[0]["width"], matched[0]["height"]) == (912, 512)


def test_read_only_still_refuses_before_any_tripwire_with_the_real_gate(rest, monkeypatch):
    req = _road({"version_id": T3, "prompt": "<prompt>", "ref_media_id": "M1"})
    assert req.parameters["contextImages"] == ["M1"]      # the gate really ran

    def tripwire(name):
        def _boom(*a, **k):
            raise AssertionError("READ_ONLY did not stop the call before " + name)
        return _boom
    monkeypatch.setattr(core, "READ_ONLY", True)
    for fn in ("match_kaisuuken", "_apply_kaisuuken", "price_task", "submit_generation",
               "_session_for_create", "gql_mutate"):
        monkeypatch.setattr(core, fn, tripwire(fn))
    with pytest.raises(core.PixAIError) as err:
        core.submit(object(), req)
    assert "READ_ONLY" in str(err.value)


# =============================================================================
# G4 / G5 / G9 -- the version row
# =============================================================================

def test_quality_tag_cases_on_the_version_row():
    row = lambda extra: core._version_row_to_meta({"id": "V", "modelType": "SDXL_MODEL",
                                                   "extra": extra})
    assert row({"qualityTags": [{"prefix": "", "suffix": "<suffix>"}]})["quality_tag"] == \
        {"prefix": "", "suffix": "<suffix>"}
    assert row({"qualityTags": [{"prefix": "<pre>", "suffix": ""}]})["quality_tag"] == \
        {"prefix": "<pre>", "suffix": ""}
    assert row({"qualityTags": [{"prefix": "", "suffix": ""}]})["quality_tag"] is None
    assert row({"qualityTags": []})["quality_tag"] is None
    assert row({})["quality_tag"] is None
    assert row({"qualityTags": "junk"})["quality_tag"] is None
    assert core._empty_version_meta()["quality_tag"] is None


def _with_row(row):
    return core.RequestResolver(model_version=lambda mid, vid: row)


def test_the_quality_tag_booster_sends_the_versions_own_tag():
    base = {"model_id": "M1", "version_id": "V", "prompt": "<prompt>",
            "quality_tag": "Masterpiece"}
    tagged = {"version_id": "V", "quality_tag": {"prefix": "", "suffix": "<suffix>"}}
    req = core.build_request(base, mode="image", resolve=_with_row(tagged))
    assert req.parameters["qualityTag"] == {"prefix": "", "suffix": "<suffix>"}
    assert req.adjusted == []
    # a row that answered with no tag (Tsubaki.3, Flash): nothing sent, and said so
    untagged = {"version_id": "V", "quality_tag": None}
    req = core.build_request(base, mode="image", resolve=_with_row(untagged))
    assert "qualityTag" not in req.parameters
    assert req.adjusted == [{"field": "qualityTag", "asked": "Masterpiece", "used": None,
                             "why": "this model version publishes no quality tag"}]
    # no row (the resolver answered a bare id): today's literal prefix
    req = core.build_request(base, mode="image", resolve=_with_row("V"))
    assert req.parameters["qualityTag"] == {"prefix": "Masterpiece"}
    # the members-only rule is unchanged
    req = core.build_request(base, mode="image", resolve=_with_row(tagged), is_member=False)
    assert "qualityTag" not in req.parameters


def test_routed_negative_prompts_prefill_on_mmdit26b_only():
    routed = {"default": "<routed-default>", "contextImage": "<routed-context>"}
    extra = {"negativePrompts": "<legacy>", "routedNegativePrompts": routed}
    meta = lambda mt, ex: core._version_row_to_meta({"id": "V", "modelType": mt, "extra": ex})
    assert meta("MMDIT26B_MODEL", extra)["negative_prompt"] == "<routed-default>"
    assert meta("MMDIT26A_MODEL", extra)["negative_prompt"] == "<legacy>"
    # both keys, both strings <= 4096, or the legacy field stands
    for bad in ({"default": "<d>"}, {"default": "<d>", "contextImage": 3},
                {"default": "x" * 4097, "contextImage": ""}, "junk"):
        ex = {"negativePrompts": "<legacy>", "routedNegativePrompts": bad}
        assert meta("MMDIT26B_MODEL", ex)["negative_prompt"] == "<legacy>", bad


def test_a_hidden_profile_is_filtered_only_from_the_drawers_list(monkeypatch):
    rows = [{"profileName": "secret", "profileFlag": "hidden"},
            {"profileName": "pro", "profileFlag": "default"},
            {"profileName": "ultra", "profileFlag": "membershipOnly"}]
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: rows)
    meta = core._attach_profiles(object(), {"version_id": "V"})
    assert meta["profiles"] == ["pro", "ultra"]
    # the gate keeps the full list: its default fill is unchanged, and a hidden profile a
    # CLI or Remix sends is not refused
    out, _ = gate({"modelId": "V", "prompts": "x"})
    assert out["inferenceProfile"] == "pro"
    out, _ = gate({"modelId": "V", "prompts": "x", "inferenceProfile": "secret"})
    assert out["inferenceProfile"] == "secret"


# =============================================================================
# The drawer's version meta (_attach_features)
# =============================================================================

def test_attach_features_merges_only_false_and_never_overwrites(rest):
    meta = core._version_row_to_meta({"id": FLASH, "modelType": "MMDIT26B_MODEL", "extra": {
        "compatibility": {"styleKey": True, "negativePrompt": False, "upscale": True}}})
    core._attach_features(object(), meta)
    c = meta["compatibility"]
    assert c["negativePrompt"] is False and c["enableADetailer"] is False
    assert c["upscale"] is True                  # an explicit extra value is never overwritten
    assert c["styleKey"] is True
    assert "lora" not in c                       # never adds a true
    assert meta["context_images"] is True
    assert meta["size_rule"] == T3_RULE


def test_attach_features_model_type_rule_and_unknowns(rest):
    meta = core._version_row_to_meta({"id": T2, "modelType": "MMDIT26A_MODEL", "extra": {}})
    core._attach_features(object(), meta)
    assert meta["compatibility"] == {"enableADetailer": False, "upscale": False}
    assert meta["context_images"] is False
    blind = core._version_row_to_meta({"id": BLIND, "modelType": "SDXL_MODEL", "extra": {}})
    core._attach_features(object(), blind)
    assert blind["compatibility"] == {} and blind["context_images"] is None
    assert blind["size_rule"] == {"step": 8, "lo": 64, "hi": 4096}


# =============================================================================
# G8 / G10 -- the DiT tables and the LoRA weight bound
# =============================================================================

def test_user_dit26b_joins_the_dit_tables():
    assert core.lora_weight_range("USER_DIT26B_MODEL") == (0.0, 1.2)
    assert "USER_DIT26B_MODEL" in core.LORA_BASE_MODEL_TYPES
    assert "USER_DIT26B_MODEL" in core.DIT_SIZE_STEP_TYPES
    assert "USER_DIT26B_MODEL" in core.NO_HIRES_FACEFIX_TYPES


def test_lora_weights_are_clamped_to_the_architectures_range(rest):
    lora = {"lora": {"L1": 1.5, "L2": -0.5, "L3": 0.7},
            "loraParameters": [{"weight": 1.5, "versionId": "L1"},
                               {"weight": -0.5, "versionId": "L2"},
                               {"weight": 0.7, "versionId": "L3"}]}
    p = img(T3, **lora)
    out, adjusted = gate(p)
    assert out["lora"] == {"L1": 1.2, "L2": 0.0, "L3": 0.7}
    assert [e["weight"] for e in out["loraParameters"]] == [1.2, 0.0, 0.7]
    by = {a["field"]: a for a in adjusted}
    assert by["lora L1"]["asked"] == 1.5 and by["lora L1"]["used"] == 1.2
    assert by["lora L2"]["asked"] == -0.5 and by["lora L2"]["used"] == 0.0
    assert "lora L3" not in by
    assert p["lora"]["L1"] == 1.5                # the caller's map is never mutated
    # SDXL runs -2..2: untouched; an unknown architecture: untouched
    for vid in (SDXL, BLIND):
        o, a = gate(img(vid, **lora))
        assert o["lora"]["L1"] == 1.5 and not [x for x in a if x["field"].startswith("lora")]


# =============================================================================
# /api/price returns the receipt before a spend
# =============================================================================

def test_api_price_returns_adjusted_for_a_flash_negative(tmp_path, monkeypatch):
    fake = FakeRest(price=950)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_rest_get", fake)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    cli = login_client(tmp_path)
    d = cli.post("/api/price", json={"version_id": FLASH, "prompt": "<prompt>",
                                     "negative": "<negative>", "width": 1024,
                                     "height": 1024}).get_json()
    assert d["cost"] == 950
    neg = [a for a in d["adjusted"] if a["field"] == "negativePrompts"]
    assert neg == [{"field": "negativePrompts", "asked": "<negative>", "used": None,
                    "why": "this model takes no negative prompt"}]
    assert "negativePrompts" not in fake.priced[-1]
    # ...and a reference beside a LoRA on Tsubaki.3 is the badge's note, not a number
    d = cli.post("/api/price", json={"version_id": T3, "prompt": "<prompt>",
                                     "ref_media_id": "M1",
                                     "loras": [{"version_id": "L1", "weight": 0.7}]}).get_json()
    assert d["cost"] is None and "can't combine a reference image with LoRAs" in d["note"]


# =============================================================================
# conftest isolation for the new caches
# =============================================================================

_seen = {}


def test_gate_caches_fill_during_a_test(rest):
    gate(img(T3))
    assert T3 in core._features_cache and T3 in core._size_config_cache
    _seen["filled"] = True


def test_gate_caches_start_empty_in_the_next_test():
    assert _seen.get("filled"), "runs after the test above"
    assert core._features_cache == {} and core._size_config_cache == {}

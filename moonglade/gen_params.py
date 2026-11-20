"""
moonglade/gen_params.py
=======================
The pure generation builders and their tables: the image parameters (`_gen_parameters`, the
LoRA weight ranges, the upscale and enlarge tables, the priority channels, colour palettes), the
video engines and their builders (`build_video_parameters`, `build_reference_video_parameters`,
`build_shot_video_params`, `_gen_video_parameters`, the duration lookups and retirement checks),
the Enhance presets and `build_panelplugin_parameters`, the edit models and
`build_chat_edit_parameters`, and the Fix body (`clean_fix_boxes`, `build_fixer_body`). Moved
verbatim out of moonglade/backup.py in the 3.22 split (phase 5).

They send nothing. The two engine names they read (PixAIError, and _rest_get for the official
colour palettes) are imported from moonglade.backup inside the functions that use them, at call
time, so importing this module never imports the engine.
"""
import datetime
import json
import os
import re
import threading
from pathlib import Path

from moonglade import media_tools as _media_tools


DEFAULT_GEN_MODEL = "1983308862240288769"  # Tsubaki.2 v1 (override with --model)


# LoRA weight bounds are per BASE ARCHITECTURE. Owner-reported from the live site,
# 2026-07-25, after using the first (flat) slider:
#
#     DiT family (dit1, Tsubaki.2/DiT.2, community DiT) :  0.0 .. 1.2
#     SD1.5, SDXL                                       : -2.0 .. +2.0
#
# There is no single correct range, which is why both earlier attempts were wrong in
# opposite directions: a 0..2 spinner blocked the legal negatives SD allows, and a flat
# -2..2 slider offered DiT weights PixAI rejects. Negative weights subtract a LoRA's
# influence and are legal on the SD architectures only.
LORA_WEIGHT_STEP = 0.1
# The owner's rule, given 2026-07-25: every DiT family is 0..1.2; only SD1.5 and SDXL are
# -2..+2. Extended 2026-07-26 once the full enum was enumerated from PixAI's bundle -- this table
# held five architectures when there are twenty-five members, and the fallback for an unrecognised
# one is the SD range, so a DiT LoRA was being offered -2..+2 against a real ceiling of 1.2.
#
# DIT7_MODEL is the important addition: it is what their picker sends for "DiT.1", and only
# DIT7B_MODEL was listed here, so the commonest DiT case was very likely already falling through.
LORA_WEIGHT_RANGES = {
    # DiT, every variant in the bundle -- 0..1.2.
    "DIT7_MODEL":        (0.0, 1.2),
    "DIT7A_MODEL":       (0.0, 1.2),
    "DIT7B_MODEL":       (0.0, 1.2),
    "DIT7C_MODEL":       (0.0, 1.2),
    "DIT7D_MODEL":       (0.0, 1.2),
    "DIT9_MODEL":        (0.0, 1.2),   # "Community DiT" in their UI
    "MMDIT26A_MODEL":    (0.0, 1.2),   # DiT.2 / Tsubaki.2
    "MMDIT26B_MODEL":    (0.0, 1.2),   # DiT.3 -- had no entry at all before today
    "USER_DIT26A_MODEL": (0.0, 1.2),   # a user-TRAINED DiT.2, which is what the owner's own are
    # A user-trained DiT.3. PixAI's stepUp table (`Ua`) puts it in the same 0..1.2 range as
    # every other DiT family (bundle, 2026-09-26; SCOPE_2026-09-26 G8).
    "USER_DIT26B_MODEL": (0.0, 1.2),
    # Stable Diffusion -- the only two the owner specified as -2..+2.
    "SD_V1_MODEL":       (-2.0, 2.0),
    "SDXL_MODEL":        (-2.0, 2.0),
    # DELIBERATELY ABSENT: SD3_MEDIUM_MODEL and Z_IMAGE_V1_MODEL. Both are real members, but the
    # owner's ranges never covered them, and they fall through to the widest range on purpose --
    # narrowing a slider on a guess would remove a capability the account may really have, while
    # a value the architecture rejects merely surfaces as a refused submit, which costs nothing.
}
# The union, used as the hard sanity bound in _lora_params (which sees a version id and a
# number, never an architecture) and as the fallback for an unknown or not-yet-picked base.
# Deliberately the WIDER of the two rather than the narrower: unknown must not silently
# remove a capability the account actually has, and the same fail-open reasoning as
# LORA_BASE_MODEL_TYPES above. A value the architecture rejects surfaces as a refused
# submit, which costs nothing.
LORA_WEIGHT_MIN, LORA_WEIGHT_MAX = -2.0, 2.0


def lora_weight_range(model_type):
    """(min, max) for a base model's architecture; the widest range when it is unknown."""
    return LORA_WEIGHT_RANGES.get(str(model_type or "").strip().upper(),
                                  (LORA_WEIGHT_MIN, LORA_WEIGHT_MAX))


def _lora_params(raw):
    """Turn LoRA specs into createGenerationTask's two fields. `raw` is a list of
    'versionId:weight' strings or (versionId, weight) tuples. Returns
    ({versionId: weight}, [{weight, versionId}])."""
    lora_map, lora_list = {}, []
    for item in (raw or []):
        if isinstance(item, (tuple, list)):
            vid, w = str(item[0]).strip(), item[1]
        else:
            vid, _sep, ws = str(item).partition(":")
            vid = vid.strip()
            w = ws.strip()
        if not vid:
            continue
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 0.7
        # PixAI's own Advanced panel bounds the weight at -2..2 (step 0.1), negatives
        # included -- read off the live control. Clamped here for the same reason the
        # upscale params are: this is the last place before the submit, and a value outside
        # their range is a rejected generation rather than a stronger effect.
        w = max(LORA_WEIGHT_MIN, min(LORA_WEIGHT_MAX, w))
        lora_map[vid] = w
        lora_list.append({"weight": w, "versionId": vid})
    return lora_map, lora_list


# --- Upscale + boosters (ordinary t2i/i2i generation parameters) --------------
# PixAI's "Confirm Upscale" dialog offers TWO methods as radio buttons, and each radio's
# `value` attribute IS the parameter name the submit carries:
#   enlarge -> `enlarge` (ratio) + `enlargeModel` (which upscaler network runs)
#   upscale -> `upscale` (ratio) + upscaleDenoisingStrength/Steps/Sampler ("Hires": the
#              image is re-diffused at the larger size, which is why it has denoising
#              controls and no upscaler dropdown, and why it costs roughly 3x as much)
# They are the same family of params as width/height -- NOT a separate plugin surface --
# so they ride the generation submit we already make.
ENLARGE_MODELS = ("ESRGAN_4x", "R-ESRGAN 4x+", "R-ESRGAN 4x+ Anime6B", "SwinIR_4x",
                  "Lollypop")
DEFAULT_ENLARGE_MODEL = "R-ESRGAN 4x+ Anime6B"      # PixAI's own default selection
DEFAULT_QUALITY_TAG = "Masterpiece"                 # their "Quality Tag" booster's prefix
# What an upscale runs on when nothing better is known. PixAI's own upscale dialog has NO
# model control at all: their submit spreads the enlarge/upscale params and then sets a
# FIXED modelId, pulling prompts/width/height off the source's original task. So a model is
# not something the user is meant to choose here, and demanding one turned an image whose
# model the catalog never recorded -- every locally imported file, and anything predating a
# full meta sweep -- into an upscale that could not be started at all.
#
# It is a model VERSION id, not a model id. A submit's `modelId` is a version id throughout
# (see _gen_parameters and queue_wait_estimate), and this value was read straight out of
# their submit builder, so it must be handed to the web routes as `version_id` -- passing it
# as `model_id` sends it into the model->versions lookup, which finds nothing and answers
# "pick a model first".
#
# Used only as the fallback: when the catalog DOES know what made the picture, that model is
# still the better answer, because Hires re-diffuses and the original keeps the style.
UPSCALE_FALLBACK_VERSION_ID = "1861558740588989558"
# Captured from a completed Hires job; their dialog hints strength works best 0.4-0.6.
DEFAULT_UPSCALE_DENOISING_STRENGTH = 0.6
# The live Hires dialog's default Denoising Steps is 20 (was 26 in our code; re-verified
# against the new-gen platform, probe 2026-08-25 / scope 2026-08-26).
DEFAULT_UPSCALE_DENOISING_STEPS = 20
UPSCALE_RATIO_STEP = 0.1                            # both sliders step in tenths
# A ratio slider's MAXIMUM is not a constant -- it moves with the source dimensions,
# because what is actually capped is the OUTPUT pixel count. Measured maxima: a 1400x784
# source allowed 1.9 in enlarge mode (-> 2656x1488) and 1.4 in Hires (-> 1952x1096),
# while a 768x1280 source allowed 1.5 in Hires (-> 1152x1920). Each measurement brackets
# the ceiling between "the largest allowed output area" and "the next 0.1 step's area":
#   enlarge  >= 2656*1488 = 3,952,128  and  < 2800*1568 = 4,390,400
#   Hires    >= 1152*1920 = 2,211,840  and  < 2096*1176 = 2,464,896  (both samples merged)
# The values below sit inside those windows and reproduce all three measurements exactly.
# INFERRED FROM TWO SOURCE SIZES, NOT DOCUMENTED: a source whose own bracket falls outside
# these windows could be one 0.1 step off, so treat a PixAI rejection here as new data
# rather than a bug in the arithmetic.
UPSCALE_PIXEL_CEILING = {"enlarge": 2048 * 2048, "upscale": 2048 * 1152}
# Every enlargeModel is a 4x network, and no measurement has ever shown a slider past it,
# so 4.0 is the backstop for a source small enough that the area ceiling never bites.
UPSCALE_RATIO_HARD_MAX = 4.0


def upscale_output_dims(width, height, ratio):
    """Output size an upscale ratio produces: scaled, then floored to the multiple of 8
    every SD pipeline needs (the same snap _gen_parameters applies to width/height).
    This is what their dialog prints under the slider -- 1400x784 at Hires 1.4 reads
    '1952x1096', not 1960x1096, because the floor happens after the float multiply."""
    r = float(ratio or 1)
    return (max(64, int((int(width) * r) // 8) * 8),
            max(64, int((int(height) * r) // 8) * 8))


def max_upscale_ratio(width, height, mode="enlarge"):
    """Largest ratio `mode` allows for a source of this size, in the slider's own 0.1
    steps -- derived from UPSCALE_PIXEL_CEILING, never hardcoded, because the same
    dialog shows different maxima for different source sizes. Walks the steps down from
    the hard backstop so the answer honours the multiple-of-8 snap the real output uses.
    Returns 1.0 (= no upscale possible) for a source already at the ceiling."""
    from moonglade.backup import PixAIError
    ceiling = UPSCALE_PIXEL_CEILING.get(str(mode))
    if ceiling is None:
        raise PixAIError("unknown upscale mode {!r} -- expected one of {}".format(
            mode, ", ".join(sorted(UPSCALE_PIXEL_CEILING))))
    steps = int(round((UPSCALE_RATIO_HARD_MAX - 1.0) / UPSCALE_RATIO_STEP))
    for i in range(steps, 0, -1):
        r = round(1.0 + i * UPSCALE_RATIO_STEP, 1)
        w, h = upscale_output_dims(width, height, r)
        if w * h <= ceiling:
            return r
    return 1.0


def _upscale_ratio(raw):
    """Normalize a requested ratio to the slider's 0.1 step, or None when the caller did
    not really ask for an upscale. 1.0 (and anything below) IS "no upscale" -- emitting
    enlarge/upscale at 1.0 would still change the priced shape for no visible gain."""
    try:
        r = round(float(raw), 1)
    except (TypeError, ValueError):
        return None
    return r if r > 1.0 else None


# PixAI's generation priority channels, read off their own bundle:
#   {default: 1000, turboMode: 500, low: 0}   (an XHigh 1500 exists; not exposed here)
#
# The names matter and are NOT in speed order. 500 is **TurboMode -- members only, no
# extra cost**, not the cheap standard tier it was taken for; 1000 is High Priority,
# which anyone may use and which costs EXTRA. This app defaulted every submit to 500,
# so every generation asked for a members-only channel. That is invisible while the
# membership is live -- it just runs fast and free -- and the day it lapses PixAI starts
# refusing with "Only member can use turbo mode" (REQUIRE_MEMBERSHIP, 403), on paths
# that had worked for months.
#
# PixAI's own client never hits that, because it normalises before submitting: a member
# asking for Low is upgraded to Turbo, and a NON-member asking for Turbo is downgraded to
# Low. Nothing here can read entitlement without an extra round trip per submit, so
# submit_generation does the same correction from the other end -- see it for why acting
# on the rejection is safe.
PRIORITY_LOW = 0          # standard speed, no extra cost, anyone
PRIORITY_TURBO = 500      # ~7.6x faster, no extra cost -- MEMBERS ONLY
PRIORITY_HIGH = 1000      # ~10x faster, costs extra credits, anyone
PRIORITY_XHIGH = 1500     # in their enum; this app never sends it
PRIORITY_CHOICES = (PRIORITY_LOW, PRIORITY_TURBO, PRIORITY_HIGH, PRIORITY_XHIGH)

def _coerce_priority(value):
    """A submitted priority, defaulting to Turbo. Accepts 0 (Low) properly, which a
    truthiness fallback cannot."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return PRIORITY_TURBO
    return v if v in PRIORITY_CHOICES else PRIORITY_TURBO


# ---- Colour palettes (Session H decision 4, 2026-09-28) ------------------------------------
# PixAI's shape, from its own contract: a palette is {overall?, background?, character?}, each
# group {colors: [{hex: "#RRGGBB", ratio: 0-100}]} with 1-12 colours, and overall or background
# must be present. A generation carries colorPalette: {name, palette} (the task-parameter
# schema), which the Generate drawer builds (gallery/src/gen/colorPaletteCore.js). The official
# palettes are one read-only GET; a user's own palettes live in the app's per-account store,
# never on PixAI (saving there is a write this app does not make).
PALETTE_GROUPS = ("overall", "background", "character")
PALETTE_MAX_COLORS = 12
PALETTE_NAME_MAX = 50
PALETTE_NAME_DEFAULT = "Custom palette"
_PALETTE_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _palette_ratio(raw):
    """A colour's share as PixAI takes it: a number 0-100, sent as a whole percent. None when
    it is not a number in range."""
    if isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0 or v > 100:                    # NaN or out of range
        return None
    return int(round(v))


def _palette_group_colors(raw):
    """[{hex, ratio}] from one palette group, or None when it is not a valid group: a list of
    1-12 colours, each a #RRGGBB hex (upper-cased) and a 0-100 ratio (a whole percent)."""
    colors = raw.get("colors") if isinstance(raw, dict) else None
    if not isinstance(colors, list) or not 1 <= len(colors) <= PALETTE_MAX_COLORS:
        return None
    out = []
    for c in colors:
        hx = c.get("hex") if isinstance(c, dict) else None
        ratio = _palette_ratio(c.get("ratio")) if isinstance(c, dict) else None
        if not isinstance(hx, str) or not _PALETTE_HEX_RE.match(hx.strip()) or ratio is None:
            return None
        out.append({"hex": hx.strip().upper(), "ratio": ratio})
    return out


def clean_color_palette(raw):
    """The web payload's `color_palette` -> the task parameter `colorPalette`
    ({name, palette}), or None when the payload carries none (absent, null, or an empty
    object -- the drawer leaves the key out when no palette applies).

    Anything PixAI's own schema would refuse is refused HERE, before any network call, as a
    builder refusal (PixAIError): the badge shows it as its note, the create route returns
    it, and nothing is created or charged. Groups other than overall/background/character
    are refused rather than dropped (a dropped group would change the picture asked for)."""
    from moonglade.backup import PixAIError
    if raw is None or (isinstance(raw, dict) and not raw):
        return None
    bad = "The colour palette isn't valid: "
    if not isinstance(raw, dict) or not isinstance(raw.get("palette"), dict):
        raise PixAIError(bad + "it has no colour groups (nothing was sent or charged)")
    pal = raw["palette"]
    extra = [k for k in pal if k not in PALETTE_GROUPS]
    if extra:
        raise PixAIError(bad + "unknown group {} (nothing was sent or charged)".format(
            ", ".join(sorted(str(k) for k in extra))[:40]))
    out = {}
    for k in PALETTE_GROUPS:
        if pal.get(k) is None:
            continue
        colors = _palette_group_colors(pal[k])
        if colors is None:
            raise PixAIError(bad + "{} needs 1 to 12 #RRGGBB colours with 0-100 shares "
                                   "(nothing was sent or charged)".format(k))
        out[k] = {"colors": colors}
    if "overall" not in out and "background" not in out:
        raise PixAIError(bad + "it needs overall or background colours "
                               "(nothing was sent or charged)")
    name = raw.get("name")
    name = name.strip() if isinstance(name, str) else ""
    return {"name": (name or PALETTE_NAME_DEFAULT)[:PALETTE_NAME_MAX], "palette": out}


def color_palette_presets(session):
    """PixAI's official colour palettes -- GET /v2/color-palettes/presets, READ-ONLY -- as
    [{id, name, cover_url, palette}], each palette holding only its valid groups (a group that
    fails _palette_group_colors is left out; a preset left with neither overall nor background
    is skipped). `cover_url` is PixAI's CDN thumbnail as given, or "". Raises on a failed read;
    the caller decides how to fail soft."""
    from moonglade.backup import _rest_get
    data = _rest_get(session, "/color-palettes/presets")
    rows = (data or {}).get("palettes") if isinstance(data, dict) else None
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        raw = r.get("palette") if isinstance(r.get("palette"), dict) else {}
        pal = {}
        for k in PALETTE_GROUPS:
            colors = _palette_group_colors(raw.get(k))
            if colors:
                pal[k] = {"colors": colors}
        if "overall" not in pal and "background" not in pal:
            continue
        cover = r.get("coverUrl")
        out.append({"id": str(r.get("id") or ""),
                    "name": str(r.get("name") or "")[:PALETTE_NAME_MAX] or "Palette",
                    "cover_url": cover if isinstance(cover, str) else "",
                    "palette": pal})
    return out


def _gen_parameters(args):
    from moonglade.backup import PixAIError
    if getattr(args, "params_json", ""):
        return json.loads(args.params_json)
    def _dim(v):                          # SD models require multiples of 8
        return max(64, (int(v) // 8) * 8)
    params = {
        "prompts": args.prompt,
        "modelId": args.model or DEFAULT_GEN_MODEL,
        "width": _dim(args.width),
        "height": _dim(args.height),
        "samplingSteps": args.steps,
        "cfgScale": args.cfg,
        # batchSize must be >= 1. `--batch-size` shares dest="count" with the top-level
        # `--count` (store_true) flag, so its default can arrive as False -> coerce.
        "batchSize": max(1, int(getattr(args, "count", 1) or 1)),
        # See PRIORITY_* -- 500 is TURBO (members only), not "standard". `or` is wrong
        # here: PRIORITY_LOW is 0, and `0 or X` is X, which would quietly re-upgrade a
        # deliberate Low back to Turbo.
        "priority": _coerce_priority(getattr(args, "priority", None)),
    }
    # Quality mode (inferenceProfile) is MODEL-TYPE-SPECIFIC: SD_V1_MODEL accepts
    # lite/standard but rejects pro/ultra (those are for newer model types). So we
    # only send it when explicitly chosen; "auto"/"" omits it and lets PixAI pick
    # the model's default. Safe for VALIDITY (the original working behavior) --
    # NOT a general promise about PRICE: on the video path the omitted default is
    # the ~3x-expensive one (issue #6, build_video_parameters' mode guard). If a
    # price probe ever shows inferenceProfile behaving the same way, stop
    # omitting here too.
    mode = (getattr(args, "mode", "") or "").strip().lower()
    if mode and mode != "auto":
        params["inferenceProfile"] = mode
    if getattr(args, "negative", ""):
        params["negativePrompts"] = args.negative
    if getattr(args, "seed", None) is not None:
        params["seed"] = args.seed
    # LoRAs: createGenerationTask wants BOTH a {versionId: weight} map and a
    # [{weight, versionId}] array, keyed by the LoRA's version id.
    lmap, llist = _lora_params(getattr(args, "lora", None))
    if lmap:
        params["lora"] = lmap
        params["loraParameters"] = llist
    # Prompt helper (auto-interprets/enhances the natural prompt). On by default to
    # match the site; turn OFF when it mangles a carefully-built prompt.
    if getattr(args, "prompt_helper", True):
        params["promptHelper"] = {"withStage": True, "userWantToEnable": True,
                                  "forcePromptHelperDetectionSide": "server"}
    else:
        params["promptHelper"] = {"withStage": False, "userWantToEnable": False,
                                  "forcePromptHelperDetectionSide": "server"}
    # Session H: the drawer's context images go out as they are (catalog / upload ids, never
    # through an input resolver -- the quote and the spend build the identical list). Only the
    # web namespace carries the attribute, so the CLI's shape is unchanged.
    ctx_ids = list(getattr(args, "context_images", None) or [])
    if ctx_ids:
        params["contextImages"] = ctx_ids
    # Reference image (the site's "use as reference" = plain img2img): a top-level
    # mediaId + strength on an otherwise standard submit. Banked from a real capture
    # 2026-07-04 (task 2030052367400863154): {..., mediaId, strength: 0.55}.
    ref = str(getattr(args, "ref_media_id", "") or "").strip()
    if ref:
        params["mediaId"] = ref
        try:
            stg = float(getattr(args, "ref_strength", 0.55) or 0.55)
        except (TypeError, ValueError):
            stg = 0.55
        params["strength"] = max(0.05, min(1.0, stg))
    # Upscale + boosters. EVERY key here is emitted only when the caller actually asked
    # for it: these are absent from a plain submit, and an always-present default would
    # silently change what every existing call site generates (and what it costs).
    enlarge = _upscale_ratio(getattr(args, "enlarge", None))
    upscale = _upscale_ratio(getattr(args, "upscale", None))
    if enlarge and upscale:
        # Kept short on purpose: the web route clips a builder refusal to 140 characters
        # for the cost badge's note, so the actionable half must come first.
        raise PixAIError("enlarge and upscale are mutually exclusive -- they are PixAI's "
                         "two upscale methods ('Upscale' and 'Hires'), so pick one")
    # Clamping can land on 1.0 for a source already at the output ceiling; that is "no
    # upscale is possible at this size", so the block is dropped rather than submitting a
    # 1.0 ratio that changes the priced shape and produces nothing.
    # A fired ceiling clamp is RECORDED, not applied in silence -- same contract as the
    # width/height/steps/cfg/count clamps (see _gen_args_from_web_payload's `adjusted`
    # receipt). The web namespace carries that list on `.clamped`; the CLI's argparse
    # Namespace has no such attribute, so the append is guarded by getattr. The clamp
    # VALUE is unchanged -- only the receipt entry is new.
    def _note_upscale_clamp(field, asked, used):
        receipt = getattr(args, "clamped", None)
        if isinstance(receipt, list):
            receipt.append({"field": field, "asked": asked, "used": used})
    if enlarge:
        _ceil = max_upscale_ratio(params["width"], params["height"], "enlarge")
        if _ceil < enlarge:
            _note_upscale_clamp("enlarge", enlarge, _ceil)
        enlarge = min(enlarge, _ceil)
    elif upscale:
        _ceil = max_upscale_ratio(params["width"], params["height"], "upscale")
        if _ceil < upscale:
            _note_upscale_clamp("upscale", upscale, _ceil)
        upscale = min(upscale, _ceil)
    if enlarge and enlarge > 1.0:
        params["enlarge"] = enlarge
        # An unknown upscaler name would be rejected by PixAI, so fall back to their own
        # default rather than losing the whole submit over a typo.
        model = str(getattr(args, "enlarge_model", "") or "").strip()
        params["enlargeModel"] = model if model in ENLARGE_MODELS else DEFAULT_ENLARGE_MODEL
    elif upscale and upscale > 1.0:
        params["upscale"] = upscale
        dstr = getattr(args, "upscale_denoising_strength", None)
        dstr = DEFAULT_UPSCALE_DENOISING_STRENGTH if dstr is None else dstr
        dsteps = getattr(args, "upscale_denoising_steps", None)
        dsteps = DEFAULT_UPSCALE_DENOISING_STEPS if dsteps is None else dsteps
        try:
            dstr = float(dstr)
        except (TypeError, ValueError):
            dstr = DEFAULT_UPSCALE_DENOISING_STRENGTH
        try:
            dsteps = int(dsteps)
        except (TypeError, ValueError):
            dsteps = DEFAULT_UPSCALE_DENOISING_STEPS
        # Bounds read off the live dialog's own controls: strength 0.01-0.99 step 0.01,
        # steps 1-50 step 1.
        params["upscaleDenoisingStrength"] = round(max(0.01, min(0.99, dstr)), 2)
        params["upscaleDenoisingSteps"] = max(1, min(50, dsteps))
        # Empty string is what a completed Hires job carried -- Hires has no sampler
        # dropdown of its own, so this hands the choice back to the base generation.
        params["upscaleSampler"] = str(getattr(args, "upscale_sampler", "") or "")
    if getattr(args, "face_fix", False):
        params["enableADetailer"] = True             # their "Face Fix" booster
    # Colour palette: {name, palette}, already cleaned by clean_color_palette. Emitted only
    # when asked for, so every other submit is byte-identical; the gate strips it where the
    # model cannot take it (and says so).
    cpal = getattr(args, "color_palette", None)
    if cpal:
        params["colorPalette"] = cpal
    qtag = str(getattr(args, "quality_tag", "") or "").strip()
    # Quality Tag is MEMBERS-ONLY on PixAI -- crowned in their Add Booster menu on every
    # model, and their own guide says "member-only" in writing. This app was never built to
    # get around their systems (owner, 2026-07-28), so an account PixAI reports as
    # non-member does not send the gated parameter. `is_member` is True/False/None from
    # core.account_is_member(); only an explicit False gates, so an unreadable account still
    # submits exactly as before.
    if qtag and getattr(args, "is_member", None) is False:
        qtag = ""
    # SCOPE_2026-09-26 G4: the web road resolves the booster to the chosen VERSION's own tag
    # ({prefix, suffix}, extra.qualityTags[0]) at build time and hands it over here; the CLI
    # never sets it, so `--quality-tag` still sends {"prefix": <text>} exactly as before.
    qobj = getattr(args, "quality_tag_obj", None)
    if qtag and isinstance(qobj, dict):
        params["qualityTag"] = {"prefix": str(qobj.get("prefix") or ""),
                                "suffix": str(qobj.get("suffix") or "")}
    elif qtag:
        params["qualityTag"] = {"prefix": qtag}      # their "Quality Tag" booster
    if getattr(args, "kaisuuken_id", ""):
        params["kaisuukenId"] = str(args.kaisuuken_id)   # spend a free card instead of credits
    # naturalPrompts is the natural-language form the prompt helper reads; it goes beside
    # prompts on every image, as PixAI's generator does -- and where PixAI's site puts it:
    # under `extra` (PROBE_2026-09-23_site: "still nests naturalPrompts in extra";
    # PROBE_2026-10-02_site's captured submit {extra:{naturalPrompts}, ...}). The REST create
    # schema (`yt`) has no top-level key by that name, so the wire guard refuses one there.
    # Merged into any extra already built; the MMDIT26B gate (G6) reads it here and stays
    # idempotent.
    extra = dict(params["extra"]) if isinstance(params.get("extra"), dict) else {}
    extra["naturalPrompts"] = args.prompt
    params["extra"] = extra
    return params


# --- Video (image-to-video) generation ---------------------------------------
# The i2v generator uses the SAME createGenerationTask mutation as images, but the
# `parameters` JSONObject is a nested {type, version, parameters:{i2vPro:{...}}}
# shape (reverse-engineered from a real payload, 2026-07-01). A source image
# (media_id) becomes the first frame; an optional tail image gives first/last-frame
# interpolation. This is the engine "Generate shot" will call once wired up.
DEFAULT_VIDEO_MODEL = "v4.0.1"


# Video enums banked from the generator i18n (2026-07-02):
VIDEO_CAMERA_MOVES = ("unset", "horizontal", "pan", "roll", "tilt", "vertical-pan", "zoom")
VIDEO_AUDIO_LANGS = ("english", "japanese", "chinese", "korean", "none")  # "none" = SE only
VIDEO_DURATIONS = (5, 6, 10, 15)                  # 15: VIDEO_15S_MODELS only; per engine: VIDEO_MODEL_DURATIONS

# Video model registry: the `.model` NAME a submit carries -> its numeric top-level
# `modelId` (+ a UI label). A real (card-covered) submit carries BOTH; WITHOUT the modelId
# PixAI resolves "Unknown or removed model" and no free card can match -- that was the
# "video card won't tap" bug. All five VERIFIED via --dump-params of real gens (2026-07-06).
VIDEO_MODELS = {
    "v4.0.1": {"model_id": "2003969750675682808", "label": "V4.0 Lite Preview"},
    "v4.0":   {"model_id": "2003968021137101826", "label": "V4.0 Preview (full)"},
    # The two Tsubaki video engines (PROBE_2026-09-26 V01/V13). The ids are the ones PixAI
    # stamped on the owner's own tbkv tasks (2060014126868040808 -> tbkv1.0,
    # 2060390260986220957 -> tbkv1.0.1), and the labels are the version titles a read-only
    # getGenerationModelByVersionId returns for those ids. The site itself never sends a
    # numeric modelId for video -- the server maps the name. This app sends these ids on the
    # REFERENCE path only (SCOPE_2026-09-26 V2: its own id, never v4.0.1's; the probe priced a
    # tbkv1.0.1 reference video the same with its own id, v4.0.1's and none). A tbkv i2vPro
    # carries NO top-level modelId, as on the site -- see VIDEO_I2V_NO_MODELID_MODELS.
    "tbkv1.0.1": {"model_id": "2054378086834851904", "label": "Tsubaki Video"},
    "tbkv1.0":   {"model_id": "2042030623542642408", "label": "Tsubaki Video Flash"},
    "v3.2":   {"model_id": "1961182207978260675", "label": "V3.2"},
    "v3.0.2": {"model_id": "2014412117889628958", "label": "V3.0 Lite"},
    "v3.0":   {"model_id": "1919508300549460046", "label": "V3.0"},
    # No numeric modelId published for these two, and none is needed -- `i2vPro.model`
    # resolves the engine (see build_video_parameters). Listed so the roster is complete
    # and video_model_id() returns '' for them deliberately, not by accident.
    "v3.0.1": {"model_id": "", "label": "V3.0 Flash"},
    "v2.7":   {"model_id": "", "label": "V2.7 (High Dynamics)"},
}


# PixAI retires V3.2 video on 2026-11-23 03:00 UTC (their announcement, 10 Nov 2026). From that
# instant this app stops offering it and refuses a submit that names it, before any network call.
# The front end keeps a mirror of this table (gallery/src/gen/videoDrawerCore.js
# VIDEO_MODEL_RETIRED) because its engine list is static JS; a parity test holds the two together.
# VIDEO_MODELS keeps the entry so old V3.2 videos in the library keep their "V3.2" label.
VIDEO_MODEL_RETIRED = {"v3.2": "2026-11-23T03:00:00Z"}


def _video_clock():
    """Now, in UTC. A seam so a test can stand either side of the retirement instant."""
    return datetime.datetime.now(datetime.timezone.utc)


def video_model_retired(model, now=None):
    """True from the instant PixAI retires this video engine (VIDEO_MODEL_RETIRED)."""
    when = VIDEO_MODEL_RETIRED.get(str(model or "").strip())
    if not when:
        return False
    cut = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
    now = now or _video_clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now >= cut


def check_video_model_retired(model, now=None):
    """Refuse a retired engine in plain words (PixAIError, raised before any network call, so
    nothing is created or charged)."""
    from moonglade.backup import PixAIError
    if video_model_retired(model, now):
        name = str(model).strip()
        label = (VIDEO_MODELS.get(name) or {}).get("label") or name
        when = datetime.datetime.strptime(VIDEO_MODEL_RETIRED[name], "%Y-%m-%dT%H:%M:%SZ")
        raise PixAIError("{} was retired by PixAI on {} {} -- pick another video engine "
                         "(nothing was created or charged).".format(
                             label, when.day, when.strftime("%b")))


def _params_video_models(params):
    """The video engine names a createGenerationTask `parameters` carries (i2vPro.model /
    referenceVideo.model); empty for anything that is not a video submit."""
    out = []
    if isinstance(params, dict):
        for key in ("i2vPro", "referenceVideo"):
            blk = params.get(key)
            if isinstance(blk, dict) and blk.get("model"):
                out.append(blk["model"])
    return out


def check_params_retired(params, now=None):
    """Refuse a `parameters` object that names a retired video engine, whoever built it.

    The builders check the engine they are handed, but a raw `--params-json` never passes
    through a builder, and the three CLI create roads (--generate-video, --reference-video,
    --edit-image) send their mutation directly rather than through submit_generation. Each
    calls this as soon as it has its parameters, before any network call (2026-11-19)."""
    for _vm in _params_video_models(params):
        check_video_model_retired(_vm, now)


def video_model_id(name):
    """Numeric top-level `modelId` for a video `.model` name ('' if unknown). A submit MUST
    include this or PixAI can't resolve the model and no free card can match."""
    return (VIDEO_MODELS.get((name or "").strip()) or {}).get("model_id", "")


def _video_model_id_fits(engine, model_id):
    """Is `model_id` a version id this video engine's row may carry (and be titled from)?
    An engine VIDEO_MODELS knows takes only its own id, so v2.7 / v3.0.1 (no id) take none:
    their real tasks carry 1648918127446573124, an IMAGE checkpoint. An engine the roster
    does not know (or a row with no engine recorded) takes any id, as before."""
    engine = str(engine or "").strip()
    if engine not in VIDEO_MODELS:
        return True
    return str(model_id or "").strip() == video_model_id(engine) != ""


VIDEO_CHANNELS = ("private", "normal")   # private = the site's "Private" channel (was "Enhanced" until 2026-08-18)


# --- Per-engine capability tables (Tsubaki video, PROBE_2026-09-26 V03-V06) ---------------
# Video models have no /features, /inference-profiles or /size-config data (both tbkv ids
# answer empty lists there), so these are hand-kept tables checked against the site's own
# panel matrix (helper--EEE6Q9r.js `I()`, the i2vPro field picker `X`) and tools.json. An
# engine ABSENT from a table keeps today's behaviour exactly -- every table here only ever
# narrows what a listed engine is sent.
TSUBAKI_VIDEO_MODELS = ("tbkv1.0", "tbkv1.0.1")

# Allowed durations per engine. The tbkv panel offers 5/10/15 (default 5) with or without a
# tail frame, and the stored i2vPro schema has only ever allowed "5"/"10"/"15". Absent =>
# VIDEO_DURATIONS (the existing engines keep their 6 s stop, unchanged by this table).
VIDEO_MODEL_DURATIONS = {m: (5, 10, 15) for m in TSUBAKI_VIDEO_MODELS}

# Engines whose panel has no negative prompt / no camera movement. The site's picker `X`
# adds negativePrompts / cameraMovement only when the panel enables them, and the tbkv panel
# enables neither. Other engines are unchanged on purpose: a v4.0.1 i2vPro with a negative
# is on the wire (task 2058947728431110088) and rendered.
VIDEO_NO_NEGATIVE_MODELS = TSUBAKI_VIDEO_MODELS
VIDEO_NO_CAMERA_MODELS = TSUBAKI_VIDEO_MODELS

# Multi-Reference caps per engine (the tbkv panel's multiReference `D`: images 6, videos 0,
# audio 3). Only the VIDEO cap is enforced at build time (a video reference sent to an
# engine that takes none); absent => no cap here, as today.
VIDEO_REF_CAPS = {m: {"images": 6, "videos": 0, "audios": 3} for m in TSUBAKI_VIDEO_MODELS}

# referenceVideo.ratio: tbkv-only, reference-path only, the 9 values of the site's `Qe`.
# Omitted (or "adaptive") lets PixAI infer the ratio from the references.
VIDEO_RATIO_MODELS = TSUBAKI_VIDEO_MODELS
VIDEO_RATIOS = ("adaptive", "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")

# i2vPro engines that go out with NO top-level modelId, whatever VIDEO_MODELS knows. No tbkv
# i2vPro task exists yet, from the site or from this app (PROBE_2026-09-26 V02 and its open
# capture: "the modelId it stamps" is unobserved). The site's i2vPro submit sends the name only,
# and the probe's tbkv i2vPro price quotes (21,000 for 5 s, 63,000 for 15 s) were taken on that
# shape. So the unobserved field stays at today's behaviour -- omitted, as it was before tbkv
# joined VIDEO_MODELS -- and the owner's first First Frame run tests one new thing, not two.
# Remove an engine from here once a real tbkv i2vPro task shows what the server stamps.
VIDEO_I2V_NO_MODELID_MODELS = TSUBAKI_VIDEO_MODELS


def video_model_durations(model):
    """The durations (seconds) this engine accepts -- its own set when VIDEO_MODEL_DURATIONS
    lists it, else the shared VIDEO_DURATIONS."""
    return VIDEO_MODEL_DURATIONS.get(str(model or "").strip(), VIDEO_DURATIONS)


def _check_video_ref_caps(model, video_media_ids):
    """Refuse video references an engine cannot take (PixAIError at BUILD time: the badge
    shows it as its note and nothing is created or charged). Only engines listed in
    VIDEO_REF_CAPS are capped; the drawer holds such refs back and never sends them, so this
    is the backstop for the CLI and a hand-rolled payload."""
    from moonglade.backup import PixAIError
    cap = (VIDEO_REF_CAPS.get(str(model or "").strip()) or {}).get("videos")
    n = len([v for v in (video_media_ids or []) if str(v).strip()])
    if cap is not None and n > cap:
        label = (VIDEO_MODELS.get(str(model).strip()) or {}).get("label") or model
        if cap == 0:
            raise PixAIError("{} takes no video references -- remove the {} video "
                             "reference{} (nothing was created or charged).".format(
                                 label, n, "" if n == 1 else "s"))
        raise PixAIError("{} takes at most {} video references, not {} -- remove {} "
                         "(nothing was created or charged).".format(label, cap, n, n - cap))


def build_video_parameters(prompt, media_id, model=DEFAULT_VIDEO_MODEL, *,
                           tail_media_id="", duration=5, mode="professional",
                           generate_audio=False, audio_language="english",
                           negative="", use_prompt_helper=False, kaisuuken_id="",
                           camera_movement="", model_id="", is_private=False):
    """Build createGenerationTask's `parameters` for an image-to-video (i2vPro) job.

    VERIFIED against a real card-covered submit (2026-07-06 via --dump-params): the shape
    is a top-level `modelId` + the `i2vPro` block + privacy/preview flags. Their site
    sends a top-level `channel` (observed value "private", task dump 2026-07-26); we send
    the equivalent as `isPrivate`. Also unsent by us: width/height and a lora object,
    both present in their submit. PROBED 2026-08-22 (17 i2v tasks, 6 models, read-only):
    all three are inert. `width`/`height` is PixAI echoing the SOURCE FRAME's dimensions
    onto the task (3/3 exact match; present on our own tasks though we never send it),
    and cost keys on model + duration, never resolution. `channel` is the same switch as
    `isPrivate`, relabelled. `lora` is always {} for video. Nothing to add.
    (moonglade-internal/probes/PROBE_2026-08-22_r2v-refs-and-video-fields.md)
    `media_id` = source/first frame; `tail_media_id` (optional) =
    last frame for FLF interpolation.

    `modelId` is NOT what selects the engine -- `i2vPro.model` is. Corrected 2026-07-21
    after two free --dump-params captures + three read-only price probes: two real tasks
    (v2.7 and v3.0.1) both carried modelId 1648918127446573124, an IMAGE checkpoint, and
    rendered fine; the two models then priced DIFFERENTLY (~56,000 vs ~44,800 for 10s) off
    that IDENTICAL modelId, and omitting modelId altogether priced the same as sending it.
    The earlier "REQUIRED" note came from a v4.0 submit where dropping modelId lost the
    free-card match -- that is a CARD-MATCHING requirement, not a model-resolution one, so
    we still send it whenever VIDEO_MODELS knows one -- except on the Tsubaki engines, whose
    i2vPro goes out in the site's name-only shape until a real task shows what the server
    stamps (VIDEO_I2V_NO_MODELID_MODELS). When it doesn't (v2.7, v3.0.1 -- no
    numeric id published and no card covers them anyway) the key is OMITTED rather than
    sent empty: absent is the shape the probe actually exercised; `modelId: ""` is not.

    NOTE: video costs FAR more than images (~27.5k credits for a 5s V4.0 clip), so
    submission stays gated behind explicit --confirm. This builder spends nothing.
    """
    # NEVER let `mode` ride absent/empty on this spend path (issue #6): read-only
    # price probes on one real shot measured professional 18,000 / basic 14,000 /
    # OMITTED 50,000 -- PixAI's own default is the expensive one, so "omit it and
    # let the server pick" is ~3x the money. Every caller today passes a real
    # value; this guard is for the next caller, and it fails LOUDLY at build time
    # (previews run this builder long before any --confirm can spend).
    check_video_model_retired(model)
    if mode not in ("basic", "professional"):
        raise ValueError("i2vPro.mode must be 'basic' or 'professional', got %r -- "
                         "omitting it triples the price (issue #6)" % (mode,))
    i2v = {
        "model": model,
        "mediaId": str(media_id),
        "usePromptsHelper": bool(use_prompt_helper),
        "prompts": prompt or "",
        "mode": mode,                        # "basic" | "professional"
        "duration": str(duration),           # seconds, as a string ("5"/"10"/"15")
    }
    # Only for models that support it -- see VIDEO_AUDIO_MODELS. Sending these to v3.0.2 got a
    # misleading NSFW refusal on an image the website accepted.
    if str(model).strip() in VIDEO_AUDIO_MODELS:
        i2v["generateAudio"] = bool(generate_audio)
        i2v["audioLanguage"] = audio_language
    if tail_media_id:
        i2v["tailMediaId"] = str(tail_media_id)
    # Neither field on an engine whose panel has none (VIDEO_NO_NEGATIVE_MODELS /
    # VIDEO_NO_CAMERA_MODELS): the tbkv i2vPro block carries only the site's picker `X`
    # fields. The tbkv i2vPro half is bundle-grounded and price-quoted, not yet on the wire;
    # an unsupported field is how v3.0.2's audio flag came back as a false NSFW refusal.
    if negative and str(model).strip() not in VIDEO_NO_NEGATIVE_MODELS:
        i2v["negativePrompts"] = negative
    # cameraMovement is v2.7-style camera-dropdown; only send when a real move is picked
    # (the verified v4.0 submit omits it entirely -> keep it out by default).
    if (camera_movement and camera_movement != "unset"
            and str(model).strip() not in VIDEO_NO_CAMERA_MODELS):
        i2v["cameraMovement"] = camera_movement
    params = {
        "priority": 1000,
        "i2vPro": i2v,
        # The new platform (2026-08-25) moved the visibility switch to a top-level string
        # enum `channel: "normal"|"private"`, replacing the old boolean `isPrivate`. Send
        # BOTH: the server honors whichever it reads, so emitting the legacy field too can't
        # regress privacy while the new field carries the switch forward.
        "channel": "private" if is_private else "normal",
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
    }
    # A Tsubaki i2vPro sends no modelId at all, even one passed in (VIDEO_I2V_NO_MODELID_MODELS).
    _mid = ("" if str(model).strip() in VIDEO_I2V_NO_MODELID_MODELS
            else str(model_id or video_model_id(model)))
    if _mid:                                  # omit rather than send "" -- see docstring
        params["modelId"] = _mid
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)   # spend a free card instead of credits
    return params


# Reference video (multi-image/video/audio reference) -- a SEPARATE top-level
# `referenceVideo` block, VERIFIED from a real submit (2026-07-02). Distinct from i2vPro.
REFVIDEO_MODEL_ID = "2003969750675682808"   # numeric model id for v4.0.1 reference-video


def build_reference_video_parameters(prompt, image_media_ids=(), *, video_media_ids=(),
                                     audio_media_ids=(), model="v4.0.1",
                                     model_id=None, duration=5,
                                     mode="professional", generate_audio=False,
                                     audio_language="english", is_private=False,
                                     priority=1000, kaisuuken_id="", ratio="",
                                     input_video_durations=None):
    """Build createGenerationTask `parameters` for a REFERENCE video (multi-image / video /
    audio reference). VERIFIED shape (2026-07-02) -- a top-level `referenceVideo` block,
    NOT i2vPro. The prompt references inputs by position with @image1/@video1/@audio1
    mentions. `duration` is an int here; channel maps to `isPrivate`. Builder spends nothing.

    `model_id` defaults to THIS model's own numeric id (video_model_id), and the key is
    omitted when there is none -- the i2v builder's rule. It used to default to v4.0.1's id,
    so a reference video on any other engine went out paired with a different model's id
    (PROBE_2026-09-26 V02); a quote does not move with it (the three modelId variants of a
    tbkv1.0.1 reference video all priced 63,000), but the free-card match keys on it.

    `ratio` is sent only for the Tsubaki engines (VIDEO_RATIO_MODELS), one of VIDEO_RATIOS,
    and omitted when empty or "adaptive" (PixAI's contract: omitted = adaptive = inferred
    from the references). It is PROVEN only on the site's REST reference-video route; this
    app submits `referenceVideo` over GraphQL, where acceptance is unobserved (probe capture
    item). A refusal is not retried -- the spend path's single attempt stands.

    `input_video_durations` is each reference video's length in seconds, in
    `referenceVideoMediaIds` order, or None/[] for the old empty list. The caller decides
    all-or-nothing (see input_video_durations()); this only sends what it is given, as
    positive floats. PixAI floors each entry and bills the output seconds PLUS the input
    seconds; an empty list is priced as a flat 15 s of input in total."""
    from moonglade.backup import PixAIError
    check_video_model_retired(model)
    _check_video_ref_caps(model, video_media_ids)
    rv = {
        "mode": mode,
        "model": model,
        "prompt": prompt or "",
        "duration": int(duration),
        "inputVideoDurations": [float(d) for d in (input_video_durations or [])],
        "referenceAudioMediaIds": [str(m) for m in (audio_media_ids or [])],
        "referenceImageMediaIds": [str(m) for m in (image_media_ids or [])],
        "referenceVideoMediaIds": [str(m) for m in (video_media_ids or [])],
    }
    r = str(ratio or "").strip()
    if r and str(model).strip() in VIDEO_RATIO_MODELS:
        if r not in VIDEO_RATIOS:
            raise PixAIError("aspect ratio {!r} is not one PixAI takes -- use one of {} "
                             "(nothing was created or charged).".format(r, ", ".join(VIDEO_RATIOS)))
        if r != "adaptive":
            rv["ratio"] = r
    # Audio only for models that take it -- the SAME table the i2v builder gates on, see
    # VIDEO_AUDIO_MODELS. Sending these to a model without audio support comes back as
    # "This image contains sensitive or NSFW content": a CONTENT complaint for an
    # unsupported flag, which points the investigation at moderation instead of the shape.
    if str(model).strip() in VIDEO_AUDIO_MODELS:
        rv["generateAudio"] = bool(generate_audio)
        rv["audioLanguage"] = audio_language
    params = {
        "priority": int(priority),
        "referenceVideo": rv,
        # New platform: top-level `channel` string replaces the boolean `isPrivate`; send
        # both (server honors whichever) so privacy can't regress. Same switch as i2vPro.
        "channel": "private" if is_private else "normal",
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
    }
    _mid = str(video_model_id(model) if model_id is None else (model_id or ""))
    if _mid:                                  # omit rather than send "" -- see docstring
        params["modelId"] = _mid
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)
    return params


def input_video_durations(video_media_ids, lookup):
    """referenceVideo.inputVideoDurations for these reference videos, ALL OR NOTHING.

    Returns (durations, unknown): each video's length from `lookup(media_id)` (seconds or
    None) in the given order when every one is known and positive, else ([], True) -- the
    exact list the app always sent before, never a partial one (a short list is priced as a
    flat 15 s of input in total, and which positions it would cover is unobserved). `unknown`
    is False when there are no video references at all, or when every length resolved.
    A `lookup` of None (a caller with no library to read) is the old behaviour."""
    from moonglade.backup import PixAIError
    vids = [str(v) for v in (video_media_ids or []) if str(v).strip()]
    if not vids:
        return [], False
    if lookup is None:
        return [], True
    out = []
    for v in vids:
        try:
            secs = lookup(v)
            secs = float(secs) if secs is not None else None
        except (TypeError, ValueError, OSError, PixAIError):
            secs = None
        if secs is None or not secs > 0:                     # None, <= 0 (or NaN)
            return [], True
        out.append(secs)
    return out, False


# The receipt line a reference video carries when a length could not be read. Worded to the
# probe's finding, not to a direction: PixAI prices a missing list as a flat 15 s of input in
# TOTAL, which is more than one short clip and less than two long ones.
INPUT_VIDEO_UNKNOWN_WHY = ("input video length unknown — PixAI prices a flat 15 s of input "
                           "in total")


def make_video_duration_lookup(out_dir, db_path=None):
    """A reference video's real length in seconds, or None -> RequestResolver.video_duration.

    Order (SCOPE_2026-09-26 V5): the local file's measured length (media_tools.duration on
    the file the gallery's one video resolver finds -- the catalog filename, else the
    media-id matcher); else the catalog's `video_duration` (the clip's REQUESTED length --
    acceptable because PixAI floors each entry, and a 10 s output measures ~10.04 s); else
    None. No network read, ever: /api/price runs this on every keystroke.

    The answer is cached per media id for the life of the returned callable (one per gallery
    app, one per CLI run), so a quote and the spend that follows it read the same number even
    if a file lands in between, and a miss does not re-walk the library per keystroke."""
    from moonglade.gallery import get_row
    from moonglade.scan import find_local_video_file
    out = Path(out_dir)
    dbp = Path(db_path) if db_path else out / "catalog.db"
    cache = {}
    lock = threading.Lock()

    def _lookup(media_id):
        mid = str(media_id or "").strip()
        if not mid:
            return None
        with lock:
            if mid in cache:
                return cache[mid]
        row = {}
        try:
            if dbp.is_file():
                row = get_row(dbp, mid) or {}
        except Exception:                            # noqa: BLE001 -- a lookup never breaks a quote
            row = {}
        secs = None
        try:
            f = find_local_video_file(out, mid, row)
            if f is not None:
                secs = _media_tools.duration(str(f))
        except Exception:                            # noqa: BLE001
            secs = None
        if secs is None or not secs > 0:
            try:
                secs = float(row.get("video_duration") or 0) or None
            except (TypeError, ValueError):
                secs = None
            if secs is not None and not secs > 0:
                secs = None
        with lock:
            cache[mid] = secs
        return secs
    return _lookup


# Only the v4.0 family renders a 15-second clip. VIDEO_DURATIONS has carried the note
# "15 is v4.0-only" since it was banked, but nothing enforced it, so a 15s request on any
# other model went straight to PixAI, which refuses the mutation -- no task is created, so
# nothing appears on the account and the client shows an instant unexplained decline. A rule
# that lives only in a comment is not a rule.
# The Tsubaki engines render 15 s too: both of the owner's tbkv tasks (2060014126868040808,
# 2060390260986220957) are 15 s reference videos, and the tbkv panel offers 5/10/15
# (PROBE_2026-09-26 V04 -- before this they silently snapped a 15 s request down to 10).
VIDEO_15S_MODELS = ("v4.0", "v4.0.1", "tbkv1.0", "tbkv1.0.1")


# PixAI rejects a video prompt over this with a raw GraphQL validation error
# ("maxLength must NOT have more than 2000 characters") and no task is created. Measured
# 2026-07-26: the owner's working submit on PixAI's own site carried 1986 characters, so the
# limit is real and he was writing right up against it. Checked here rather than letting the
# round trip fail, so the message can say the actual count and how much to cut.
VIDEO_PROMPT_MAXLEN = 2000


# Which video models actually take the audio fields. SURVEYED 2026-07-26 across the owner's own
# successful tasks, one per model, via getTaskById (read-only, free) -- not inferred:
#
#   v3.2     generateAudio=True   audioLanguage=english     <- audio supported
#   v4.0     generateAudio=True   audioLanguage=english     <- audio supported
#   v4.0.1   generateAudio=True   audioLanguage=english     <- audio supported
#   v3.0.2   (both fields ABSENT)                           <- omit
#   v2.7     (both fields ABSENT)                           <- omit
#   v3.0.1   generateAudio=False, audioLanguage absent      <- omit (never seen carrying audio)
#   tbkv1.0    generateAudio=True audioLanguage=english     <- audio supported (2026-09-26:
#   tbkv1.0.1  generateAudio=True audioLanguage=english        both on the wire; the tbkv
#                                                              panel has audioLanguage)
#
# Sending them regardless is NOT harmless, and this is the bug that cost an evening. A controlled
# pair on media id 747704233721405654 with model v3.0.2: PixAI's own site submitted it WITHOUT the
# audio fields and the video rendered; this app submitted it WITH them and was refused
# "This image contains sensitive or NSFW content." Same image, same model, audio the differing
# variable -- so an unsupported audio flag surfaces as a CONTENT complaint, which sent the whole
# investigation chasing a moderation problem that did not exist.
#
# An earlier cut of this guessed "v4.0 family only" and a pre-existing test caught it: v3.2 really
# does carry audio. Hence the survey. Do not narrow this list without measuring the model first.
VIDEO_AUDIO_MODELS = ("v3.2", "v4.0", "v4.0.1", "tbkv1.0", "tbkv1.0.1")


def _snap_video_duration(d, model=""):
    """Snap a requested duration (seconds) to the nearest allowed PixAI video length.

    `model` (optional) additionally enforces the engine's own rules: an engine listed in
    VIDEO_MODEL_DURATIONS snaps to ITS set (6 -> 5 on a Tsubaki engine, whose panel and stored
    schema have no 6), and 15 is VIDEO_15S_MODELS-only, so any other model snaps down to 10
    rather than being sent a length PixAI will reject. Omitting `model` keeps the original
    model-blind behavior exactly, which is what the CLI's own preview path and the pre-existing
    tests pin."""
    try:
        d = float(d)
    except (TypeError, ValueError):
        return 5
    allowed = video_model_durations(model) if model else VIDEO_DURATIONS
    snapped = min(allowed, key=lambda v: abs(v - d))
    if snapped == 15 and model and str(model).strip() not in VIDEO_15S_MODELS:
        return 10
    return snapped


def build_shot_video_params(mode, prompt, image_ids=(), video_ids=(), audio_ids=(),
                            *, duration=5, generate_audio=False, model="",
                            audio_language="english", camera_movement="",
                            quality="professional", negative="", is_private=False,
                            use_prompt_helper=False, input_video_durations=None, ratio=""):
    """PixAI video PROVIDER ADAPTER: map a Loom shot (mode + prompt + @-ordered ref
    media_ids) to createGenerationTask video params. This is the SEAM a future Seedance/
    other provider mirrors -- same shot spec in, provider-native params out. I2V/FLF ->
    i2vPro; R2V/V2V/any-with-refs -> referenceVideo. Duration snaps to PixAI's allowed
    lengths. (Card auto-apply happens at the route: a V4.0 card makes it free.)

    `negative` only reaches i2vPro (I2V/FLF) -- the referenceVideo submit shape captured
    2026-07-02 has no negativePrompts field at all. A genuine PixAI API gap, not an
    oversight here -- R2V/V2V shots silently ignore a negative prompt if one is set.
    `use_prompt_helper` (the Generate dock's 'Video prompt helper' switch, off by default)
    likewise only reaches i2vPro.usePromptsHelper -- referenceVideo has no such field.

    Every engine sends its OWN modelId or none (PROBE_2026-09-26 V02): the reference path
    used to fall back to v4.0.1's id for an engine VIDEO_MODELS did not know, pairing
    `model: "tbkv1.0.1"` with another model's id. `input_video_durations` (the caller's
    all-or-nothing list, see input_video_durations()) reaches only referenceVideo, and an
    engine that takes no video references refuses them here (build_reference_video_parameters)
    rather than sending them.

    `ratio` (the Generate drawer's Tsubaki aspect-ratio picker, 2026-09-28) reaches only the
    referenceVideo road, where build_reference_video_parameters sends it for a Tsubaki engine
    and never as "adaptive"; an i2vPro shot has no such field and never carries it. The web
    road writes the receipt when it cannot go out (build_request)."""
    from moonglade.backup import PixAIError
    m = (mode or "R2V").upper()
    # Both submit shapes cap the prompt, under different field names
    # (i2vPro.prompts / referenceVideo.prompt), so check once here where they converge.
    if prompt and len(prompt) > VIDEO_PROMPT_MAXLEN:
        raise PixAIError(
            "Your video prompt is {:,} characters and PixAI's limit is {:,} -- trim {:,} and "
            "resubmit. (PixAI rejects the whole submit on this, so nothing was created or "
            "charged.)".format(len(prompt), VIDEO_PROMPT_MAXLEN,
                               len(prompt) - VIDEO_PROMPT_MAXLEN))
    imgs = [str(i) for i in (image_ids or []) if str(i).strip()]
    vids = [str(v) for v in (video_ids or []) if str(v).strip()]
    auds = [str(a) for a in (audio_ids or []) if str(a).strip()]
    mdl = (model or "").strip() or DEFAULT_VIDEO_MODEL
    dur = _snap_video_duration(duration, mdl)
    qual = (quality or "professional").strip() or "professional"
    mid_num = video_model_id(mdl)                  # the REQUIRED numeric modelId for this model
    if m == "I2V" and imgs:
        return build_video_parameters(prompt, imgs[0], model=mdl, duration=dur,
                                      mode=qual, generate_audio=generate_audio,
                                      audio_language=audio_language,
                                      camera_movement=camera_movement, model_id=mid_num,
                                      negative=negative, is_private=is_private,
                                      use_prompt_helper=bool(use_prompt_helper))
    if m == "FLF" and len(imgs) >= 2:
        return build_video_parameters(prompt, imgs[0], model=mdl, tail_media_id=imgs[1],
                                      duration=dur, mode=qual, generate_audio=generate_audio,
                                      audio_language=audio_language,
                                      camera_movement=camera_movement, model_id=mid_num,
                                      negative=negative, is_private=is_private,
                                      use_prompt_helper=bool(use_prompt_helper))
    if imgs or vids or auds:                       # R2V / V2V / any mode carrying references
        return build_reference_video_parameters(prompt, image_media_ids=imgs,
                                                 video_media_ids=vids, audio_media_ids=auds,
                                                 model=mdl, duration=dur, mode=qual,
                                                 is_private=is_private,
                                                 generate_audio=generate_audio,
                                                 audio_language=audio_language,
                                                 model_id=mid_num,
                                                 input_video_durations=input_video_durations,
                                                 ratio=ratio)
    raise PixAIError("PixAI video needs a frame or a reference image/video for this shot "
                     "(mode {}) -- attach a cast image or an open frame.".format(m))


def build_panelplugin_parameters(media_id, workflow_id="", *, workflow_name="",
                                 strength=None, extra_inputs=None, priority=1000,
                                 is_private=False, kaisuuken_id=""):
    """Enhance via a PixAI panelplugin WORKFLOW (face-fix / bg-remove / handfix / lineart ...).
    VERIFIED shape (2026-07-02): model 'pixai-panelplugin', `inputs.image = {type:'media',
    media_id}` (+ optional strength / per-plugin args). A workflow is addressed by either a
    numeric `workflowId` (VERIFIED path) OR a `workflowName` like 'mymusise/hand-fix' (mined
    from the app). Produces an image output. Builder spends nothing.

    Restored 2026-08-18 for the Bridge tier (drift §44 / SCOPE §3). The 2026-07-24 deletion
    was correct about the API KEY -- PixAI reaps an API-key panelplugin submit unstarted at
    ~60 min -- but overshot to "impossible". A panelplugin task submitted on the BROWSER JWT
    (the mirror) dispatches in seconds. So the ONLY safe caller is one gated on an armed
    mirror: /api/enhance refuses unless make_mirror_session() is live, and submit_generation
    routes the create through _session_for_create onto that JWT. This builder itself is
    credential-agnostic; the gate lives at the route."""
    from moonglade.backup import PixAIError
    inputs = {"image": {"type": "media", "media_id": str(media_id)}}
    if strength is not None:
        inputs["strength"] = float(strength)
    if extra_inputs:
        inputs.update(extra_inputs)
    params = {
        "priority": int(priority),
        "model": "pixai-panelplugin",
        "inputs": inputs,
        "isPrivate": bool(is_private),
        "enablePreview": True,
        "hidePrompts": False,
    }
    if workflow_name:
        params["workflowName"] = str(workflow_name)
    elif workflow_id:
        params["workflowId"] = str(workflow_id)
    else:
        raise PixAIError("panelplugin needs a workflow_id or workflow_name")
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)
    return params


# The six mirror-gated Bridge Enhance presets (the DC set, drift §44), each PINNED to its
# addressing. This is the canonical record because Branch C is confirmed: the live `workflows`
# GraphQL connection returns ZERO entries on our credential (probed 2026-08-16/17), so the DC's
# "self-populates from workflow_catalog" cannot happen -- the presets are hardcoded, not
# discovered. Each is addressed by a workflow_name = "<author/workflow>:<version>", passed
# straight to build_panelplugin_parameters via /api/enhance.
#
# ADDRESSES ARE AUTHORITATIVE + DISPATCH-PROVEN (2026-08-18). All six were pulled from PixAI's
# live public config -- GET https://api.pixai.art/config/constants -> imageEnhancementPlugins,
# which gives {workflowName, workflowVersion, args} per plugin -- then each was submitted FOR
# REAL through the mirror JWT and confirmed to DISPATCH and complete (startedAt set, status
# completed). This replaced four rotted guesses that /v2/task-price had falsely blessed:
#   * handfix / face -- the bare names ("mymusise/hand-fix", "kyo/face-detailer") 404'd at
#     createGenerationTask ("No workflow matched by the name"). The real addresses carry the
#     :version suffix the config supplies (:v1, :v4.0).
#   * line_art / sketch_color -- the old numeric workflow_ids (1796.../1793..., recovered from
#     the b93ce1e enh-card onclicks) were ACCEPTED and CHARGED but never dispatched -- no worker
#     picked them up, reaped unstarted at ~60min (the owner hit this live on line_art). The real
#     workflows are name-addressed: pixai-official/image-to-lineart, .../sketch-coloring-workflow.
#   * bg_remove / emotion were already dispatch-proven earlier and kept as-is.
# LESSON (why the earlier "task-price de-risked it" note was wrong): /v2/task-price validates the
# request SHAPE and prices it, NOT that a live worker exists for the workflow -- it quoted all six,
# including the four dead ones. Only a real JWT submit proves dispatch. See memory
# bridge-enhance-presets-rotted. `args` (per-plugin defaults like handfix strength / a face-detailer
# prompt / the emotion radios) are applied server-side when omitted -- a bare name:version submits.
BRIDGE_ENHANCE_PRESETS = (
    {"key": "handfix",     "label": "Handfix",           "workflow_name": "mymusise/hand-fix:v1"},
    {"key": "face",        "label": "Face Enhance",      "workflow_name": "kyo/face-detailer:v4.0"},
    {"key": "emotion",     "label": "Change Emotion",    "workflow_name": "kyo/emotionlab:633acbbb",
     "has_control": True},
    {"key": "bg_remove",   "label": "Background Remover", "workflow_name": "mymusise/39a2c67c:unet-0.1.3.2"},
    {"key": "line_art",    "label": "Convert to Line Art",
     "workflow_name": "pixai-official/image-to-lineart:0a59dd67"},
    {"key": "sketch_color", "label": "Sketch Coloring",
     "workflow_name": "pixai-official/sketch-coloring-workflow:d40e38f8"},
)

# Change Emotion is the one preset with a control (has_control): the user picks a target
# expression. The workflow_name is derived from the preset row so it can't drift.
ENHANCE_EMOTION_WORKFLOW = next(
    p["workflow_name"] for p in BRIDGE_ENHANCE_PRESETS if p["key"] == "emotion")
# The panelplugin input key emotionlab reads the chosen expression from is `prompt`, and the
# value is a danbooru TAG STRING (NOT the option key). DISPATCH-PROVEN 2026-08-20 against three
# completed website submits recovered via getTaskById (--dump-params): the real submit is
#   inputs.prompt = "<tag string>"   e.g. Upset -> "sad, crying", Aroused -> "sexy, steam,
#   half-closed eyes, torogao, heavy breathing"   addressed by workflowName kyo/emotionlab:633acbbb.
# The prior `inputs.emotion = <filename stem>` wiring was wrong on all three axes (arg name, value,
# AND a versionless workflow address) -- which is why every earlier API attempt charged 2000
# credits and never applied an expression (the "dispatch-verify" note it was built on read a FAILED
# job's acceptance as proof). Source of truth for the option->tag map and the workflow version is
# PixAI's PUBLIC config: GET https://api.pixai.art/config/constants -> imageEnhancementPlugins ->
# emotion (workflowName/workflowVersion, and args.prompt.options[].value keyed by the
# options.<key> i18n label path). Re-pull that endpoint to refresh if PixAI edits the set.
ENHANCE_EMOTION_ARG = "prompt"

# option key (the staged branding/bridge/emotion/<key> filename stem, i.e. the value the picker
# sends up) -> the danbooru tag string emotionlab's `prompt` arg expects. Captured verbatim from
# config/constants imageEnhancementPlugins.emotion (2026-08-20). An unknown key falls back to
# itself at the route, so a custom-staged expression still submits *something* rather than erroring.
ENHANCE_EMOTION_PROMPTS = {
    "happy": "smile",
    "upset": "sad, crying",
    "mad": "angry, annoyed, angry symbol",
    "smug": "smug, laughing, smirk, grin",
    "laughing": "closed eyes, laughing, open mouth",
    "playful": ";d, open mouth",
    "sassy": ":q",
    "sympathy": "sad smile",
    "cute": ":3",
    "moved": "smile crying",
    "afraid": "constricted pupils, scared, trembling, open mouth, wavy mouth, tearing up",
    "shocked": "surprised, :o, \U0001f626, constricted pupils",
    "pumped": "excited, happy, :d, sparkling eyes",
    "awkward": "nervous, sweat, v-shaped eyebrows, frown, open mouth, wavy mouth",
    "confused": "@ @, trembling, confused, misunderstanding, puzzle",
    "nervous": "full-face blush, looking to the side, sideways glance, half-closed eyes",
    "sickened": "grimace, gloom (expression), embarrassed, dark persona, jitome",
    "speechless": "depressed, sanpaku, jitome, looking to the side, sideways glance, ",
    "annoyed": "scowl, >:(, v-shaped eyebrows",
    "aroused": "sexy, steam, half-closed eyes, torogao, heavy breathing",
    "shy": "open mouth, wavy mouth, full-face blush, v-shaped eyebrows",
    "affection": "heart-shaped eyes, smile",
    "focused": "v-shaped eyebrows, frown, looking to the side, sideways glance, half-closed eyes",
    "naughty": "fang, tongue out, half-closed eyes",
    "amazed": "+ +, open mouth, mouth drool",
    "stunned": "wide-eyed",
    "aggrieved": ">_<",
    "doubt": ";o",
    "pouting": ":t [ :T ]",
    "glasgow-smile": "glasgow smile",
    "mania": "crazy smile",
    "impatience": "rolling eyes",
    "nosebleed": "nosebleed",
    "scowl": "grimace",
    "blush-stickers": "blush stickers",
}

# The 25 (of 35) emotions PixAI marks membership-gated (config/constants -> ...emotion.args.prompt
# .options[].membership == True); the other 10 are free. A gated pick on a non-member account is
# REJECTED by PixAI -- but a rejected panelplugin job refunds its credits at the ~60-min reap, so
# this is a picker HINT (badge the tile), not a submit block. The owner's account carries a
# membership, so all 35 dispatch for them; the flag exists so the surface stays honest if that lapses.
ENHANCE_EMOTION_MEMBERSHIP = frozenset({
    "afraid", "shocked", "pumped", "awkward",
    "confused", "nervous", "sickened", "speechless",
    "annoyed", "aroused", "shy", "affection",
    "focused", "naughty", "amazed", "stunned",
    "aggrieved", "doubt", "pouting", "glasgow-smile",
    "mania", "impatience", "nosebleed", "scowl",
    "blush-stickers",
})


# The CLI --enhance command stays gone -- both halves of it. Only the WEB /api/enhance route
# is restored (mirror-gated), never the CLI flag or run_enhance; see build_panelplugin_parameters
# above for the reversal, and dev/tests/test_enhance.py for the guards.
#
# The panelplugin half's CLI entry (--workflow-id and run_enhance): NOT restored. The Bridge is
# web-only -- its mirror gate is a route concern, and a bare CLI --workflow-id could submit a
# panelplugin task on the API key (the reaped-at-60-min bug). The parser defines no such flag.
#
# The art-filter half (build_filter_parameters, --filter-id): that one worked, and was still
# the wrong thing to do. PixAI's 7 "art filters" are not inference at all -- each is two or
# three linear gradients with a blend mode, an opacity and an optional
# brightness/contrast/saturation trim, served from a PUBLIC unauthenticated config endpoint
# (GET https://api.pixai.art/config/imageArtFilters) that their own web client reads and
# composites in the browser, with no Generate button and no price on the panel. Submitting that
# as an image-filter generation charged credits and waited on a worker queue to perform a
# handful of gradient fills. static/mg-art-filters.js does the identical composite locally,
# offline, for nothing, so the paid path is deleted rather than left as a strictly worse
# second option.
#
# Guarded by dev/tests/test_enhance.py, which greps for the two literals a FILTER submit could not do without -- the filter
# model's id and the filter-inputs key. Neither exact string appears above on purpose: the
# CONCEPT is named in prose so the strings themselves stay a reliable tripwire. (The panelplugin
# model literal and its workflow-id key DO appear now, in the restored, mirror-gated builder
# above -- test_enhance.py asserts their PRESENCE, not their absence.)


def _gen_video_parameters(args):
    """Build the i2v `parameters` from CLI/GUI args (thin wrapper over
    build_video_parameters). `--params-json` overrides everything.

    Snaps --duration to PixAI's allowed lengths (5/6/10/15) before it reaches the
    builder -- the same snap build_shot_video_params (the Loom/web adapter) already
    applies, now made a CLI guarantee too rather than a Loom-only one (B9)."""
    if getattr(args, "params_json", ""):
        return json.loads(args.params_json)
    return build_video_parameters(
        getattr(args, "prompt", "") or "",
        getattr(args, "image", "") or "",
        model=(getattr(args, "video_model", "") or getattr(args, "model", "")
               or DEFAULT_VIDEO_MODEL),
        tail_media_id=getattr(args, "tail", "") or "",
        duration=_snap_video_duration(
            getattr(args, "duration", 5) or 5,
            (getattr(args, "video_model", "") or getattr(args, "model", "")
             or DEFAULT_VIDEO_MODEL)),
        mode=getattr(args, "vmode", None) or "professional",
        generate_audio=bool(getattr(args, "audio", False)),
        audio_language=getattr(args, "audio_language", None) or "english",
        negative=getattr(args, "negative", "") or "",
        use_prompt_helper=bool(getattr(args, "video_prompt_helper", False)),
        kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
        camera_movement=getattr(args, "camera_movement", "") or "",
        is_private=((getattr(args, "vchannel", "") or "private") == "private"),
    )


# PixAI "Edit Pro" (instruct-editing) model. Override with --edit-model.
EDIT_PRO_MODEL_ID = "2006468692917575683"

# The two image models (modelType CHAT) that accept an instruct/reference edit. Caps VERIFIED
# via the model-capability probe 2026-07-06 (extra.chatEditing). Drives the Edit card's model
# picker + its resolution/quality/aspect option lists + reference-image cap. Reference Pro
# exposes NO quality option (qualities empty) and adds 21:9; Edit Pro is 1K/2K, Reference 2K/4K.
#
# Re-read 2026-09-26 (the preset roster's extra.chatEditing, SCOPE_2026-09-26 E1/E2):
#   * Edit Pro publishes defaultAspectRatio "3:5" and offers 3:5 and 5:3 on top of the eleven
#     below, so its default moved from 3:4 to 3:5.
#   * Reference Pro publishes NO defaultAspectRatio. For a model like that PixAI's own aspect
#     control shows an "Auto" tile, selected by default, and sends no aspectRatio at all -- the
#     owner's two Reference Pro edits on the wire carry modelConfig {resolution} only. "auto"
#     is therefore an aspect VALUE here, first in Reference Pro's list and its default, and
#     build_chat_edit_parameters omits aspectRatio for it. Auto leaves the frame to PixAI; it
#     does NOT promise to keep the source's frame (the probe's verifier saw a 0.595 source
#     come back 2:3), so no copy anywhere may say it does.
# editCore.js EDIT_CAPS mirrors this table by hand; dev/tests/test_edit_upload.py's parity test
# reads both and fails if their aspects, defaults, reference caps, resolutions or qualities
# drift apart.
#
# PixAI Edit v4.0 (Session L decision 6, lane w2-small 2026-09-28), copied from its own model
# record -- the preset roster's version row 1983993578828959744, extra.chatEditing, read
# 2026-09-28: maxInputImageCount 10; supportedResolutionOptions 1K/2K/4K, defaultResolution
# 1K; no quality options; no defaultAspectRatio; fourteen aspects down to 1:8 / 8:1, in the
# record's own order. No published default aspect means PixAI's own client sends no
# aspectRatio (modelParams `ge`), so "auto" is its first aspect and its default, exactly as for
# Reference Pro. Listed first; the card's default model stays Edit Pro.
# Labelled as PixAI labels it, "PixAI Edit (v4.0)": the latest version of PixAI's general Edit
# model, not Edit Pro and not Tsubaki.3 (the owner's walk, 2026-10-03).
#
# The two output capability lists (DESIGN_3.22 5.1), baked from the version records'
# extra.chatEditing (PROBE_2026-11-18_site): `output_formats` is supportedOutputFormatOptions
# (only Edit Pro V2.0 lists png/svg/gif), `backgrounds` is supportedBackgroundOptions
# (transparent on Edit Pro v1.0 and V2.0). The live /versions record wins when it can be read
# (models.edit_output_caps_live, by `base_model_id`, the MODEL id that route takes:
# PROBE_2026-10-26_site and 11-18 read Edit Pro 2006468692900798466, Reference Pro
# 1948514378379046913, PixAI Edit 1882220606138613945); this table is the fallback.
#
# PixAI Edit Pro V2.0 (#67, PROBE_2026-10-02_site): a new VERSION of the Edit Pro model
# (2026-09-29), not a new model, copied from its own version row 2061589941358465024,
# extra.chatEditing: maxInputImageCount 10; 1K/2K; low/medium/high; eleven aspects (v1.0's
# thirteen minus 1:3 and 3:1) in the record's order; defaults 1K/medium/3:5. Labelled as PixAI
# labels it ("PixAI Edit Pro (v2.0)") and listed right after v1.0. v1.0 stays -- PixAI still
# offers it, the Edit Pro AI Tools scenes run on it, and it stays the card's default
# (EDIT_PRO_MODEL_ID). Same submit shape and price table as v1.0; only chat.modelId differs.
EDIT_ASPECT_AUTO = "auto"
EDIT_MODELS = {
    "edit-v4": {
        "model_id": "1983993578828959744",
        "label": "PixAI Edit (v4.0)", "max_refs": 10,
        "resolutions": ["1K", "2K", "4K"],
        "qualities": [],
        "aspects": [EDIT_ASPECT_AUTO, "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "21:9", "1:4", "4:1", "1:8", "8:1"],
        "default": {"resolution": "1K", "quality": "", "aspect": EDIT_ASPECT_AUTO},
        "base_model_id": "1882220606138613945", "output_formats": [], "backgrounds": [],
    },
    "edit-pro": {
        "model_id": EDIT_PRO_MODEL_ID,
        "label": "Edit Pro", "max_refs": 4,
        "resolutions": ["1K", "2K"],
        "qualities": ["low", "medium", "high"],
        "aspects": ["3:5", "5:3", "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "1:3", "3:1"],
        "default": {"resolution": "1K", "quality": "medium", "aspect": "3:5"},
        "base_model_id": "2006468692900798466", "output_formats": [],
        "backgrounds": ["transparent"],
    },
    "edit-pro-v2": {
        "model_id": "2061589941358465024",
        "label": "Edit Pro (v2.0)", "max_refs": 10,
        "resolutions": ["1K", "2K"],
        "qualities": ["low", "medium", "high"],
        "aspects": ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "3:5",
                    "5:3"],
        "default": {"resolution": "1K", "quality": "medium", "aspect": "3:5"},
        "base_model_id": "2006468692900798466", "output_formats": ["png", "svg", "gif"],
        "backgrounds": ["transparent"],
    },
    "reference-pro": {
        "model_id": "1948514378441961474",
        "label": "Reference Pro", "max_refs": 10,
        "resolutions": ["2K", "4K"],
        "qualities": [],
        "aspects": [EDIT_ASPECT_AUTO, "16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
                    "5:4", "21:9"],
        "default": {"resolution": "2K", "quality": "", "aspect": EDIT_ASPECT_AUTO},
        "base_model_id": "1948514378379046913", "output_formats": [], "backgrounds": [],
    },
}
DEFAULT_EDIT_MODEL = "edit-pro"
# The aspect an edit on a model OUTSIDE the table gets when nobody picked one. What such a
# model does with no aspectRatio is unobserved, so this fails open to the value every edit sent
# before the table defaults existed (SCOPE_2026-09-26's rule for unobserved behaviour).
_EDIT_ASPECT_UNKNOWN_MODEL = "3:4"

# The model PixAI ran a hand/face Fix on BEFORE October 2026 -- the same CHAT model the Edit
# card calls Reference Pro. Kept only because it labels the Fixes collected before then (a
# Fix submit, POST /v2/task/fixer with just {mediaId, boxes}, never names a model).
# PixAI now runs a Fix on PixAI Edit v4.1 (2066624583022309376): measured 2026-10-28 through
# POST /v2/task/fixer/price, whose answer equals the v4.1 quote and not this model's. The app
# no longer prices with this constant -- a Fix is priced by PixAI's own Fix price route off
# the exact submit body (price_fixer).
FIXER_MODEL_ID = EDIT_MODELS["reference-pro"]["model_id"]


def edit_model_id(key):
    """model_id for an Edit-card model key ('edit-v4'/'edit-pro'/'edit-pro-v2'/
    'reference-pro'); '' if unknown."""
    return (EDIT_MODELS.get((key or "").strip()) or {}).get("model_id", "")


def edit_model_by_id(model_id):
    """The EDIT_MODELS spec whose model_id matches `model_id`, else None -- used to clamp a
    submitted edit's resolution/quality/aspect to what that model actually supports."""
    mid = str(model_id or "")
    for spec in EDIT_MODELS.values():
        if spec.get("model_id") == mid:
            return spec
    return None


def edit_default_aspect(model_id):
    """The aspect an edit on `model_id` gets when the caller picked none: the model's own table
    default ("auto" for Reference Pro, which publishes none; "3:5" for Edit Pro), or the
    pre-table 3:4 for a model the table does not know (see _EDIT_ASPECT_UNKNOWN_MODEL)."""
    spec = edit_model_by_id(model_id)
    return spec["default"]["aspect"] if spec else _EDIT_ASPECT_UNKNOWN_MODEL


def clamp_edit_config(model_id, resolution, quality, aspect):
    """Snap an edit's (resolution, quality, aspect) to the resolved model's real capabilities,
    so NO path -- preset, stale UI, old client -- can send an option the model rejects (the
    preset-with-Reference-Pro bug). Unknown models pass through unchanged. Returns the tuple.

    "auto" passes only for a model whose table lists it -- one that publishes no default
    aspect (Reference Pro). On Edit Pro it is not a legal value and snaps to the model's
    default (3:5), exactly like any other aspect the model does not offer. On a model OUTSIDE
    the table (a banked Toolbox preset pins one, e.g. PixAI Edit v3.0) "auto" -- or no aspect
    at all -- becomes the pre-table 3:4 (_EDIT_ASPECT_UNKNOWN_MODEL): what such a model does
    with no aspectRatio is unobserved, so it fails open to what every edit sent before "auto"
    existed. Any other aspect still passes through unchanged there."""
    spec = edit_model_by_id(model_id)
    if not spec:
        if not aspect or aspect == EDIT_ASPECT_AUTO:
            aspect = _EDIT_ASPECT_UNKNOWN_MODEL
        return resolution, quality, aspect
    if not spec["qualities"]:
        quality = ""                                   # model exposes no quality knob
    elif quality and quality not in spec["qualities"]:
        quality = spec["default"].get("quality", "")
    if resolution not in spec["resolutions"]:
        resolution = spec["default"]["resolution"]
    if aspect not in spec["aspects"]:
        aspect = spec["default"]["aspect"]
    return resolution, quality, aspect


def _is_local_source(src):
    """A source is a local file to upload (vs an existing catalog media_id) when it
    points at a real file on disk. media_ids are big numeric strings; paths aren't."""
    try:
        return bool(src) and os.path.isfile(src)
    except (OSError, ValueError):
        return False


# Edit Pro's new outputs (DESIGN_3.22 5.1; chatEditing-DtzDRo8B.js's enums): the formats, and the
# GIF frame count and frame length PixAI takes, as whole numbers.
EDIT_OUTPUT_FORMATS = ("png", "svg", "gif")
EDIT_FRAME_COUNT_RANGE = (2, 16)          # PixAI's default 9, sent only when asked for
EDIT_FRAME_MS_RANGE = (20, 2000)          # PixAI's default 200, sent only when asked for


def edit_output_caps(model_id, live=None):
    """{"output_formats": [...], "backgrounds": [...]} for an edit model: `live` (the version
    record's extra.chatEditing as models.edit_output_caps_live reads it) when it is a dict,
    else the baked EDIT_MODELS lists. A model outside the table offers neither. Pure."""
    if isinstance(live, dict):
        return {"output_formats": [str(f) for f in live.get("output_formats") or []],
                "backgrounds": [str(b) for b in live.get("backgrounds") or []]}
    spec = edit_model_by_id(model_id) or {}
    return {"output_formats": list(spec.get("output_formats") or []),
            "backgrounds": list(spec.get("backgrounds") or [])}


def edit_output_config(model_id, *, output_format=None, frame_count=None,
                       frame_duration_ms=None, transparent=False, auto_tone=True, caps=None):
    """The chat.modelConfig keys Edit Pro's new outputs add (DESIGN_3.22 5.1), or LocalRefusal
    with a sentence. Never clamps: a value outside the rules is refused and nothing is sent.

      output_format      png (the default, sent as nothing), svg or gif -- svg and gif only
                         when the model's record lists them (supportedOutputFormatOptions)
      frame_count        a whole number 2-16, gif only (PixAI's default 9 when unset)
      frame_duration_ms  a whole number 20-2000, gif only (PixAI's default 200 when unset)
      transparent        background "transparent", only when the model lists it
                         (supportedBackgroundOptions) and the format is png
      auto_tone          on (the default) sends nothing; off sends colorTone "original",
                         only with transparent

    `caps` is the live capability read (edit_output_caps' `live`); None uses the baked table."""
    from moonglade.backup import LocalRefusal
    fmt = None if output_format in (None, "") else output_format
    if fmt is not None and (not isinstance(fmt, str) or fmt not in EDIT_OUTPUT_FORMATS):
        raise LocalRefusal("The output format must be PNG, SVG or GIF, so nothing was sent.")
    have = edit_output_caps(model_id, caps)
    if fmt in ("svg", "gif") and fmt not in have["output_formats"]:
        raise LocalRefusal("This edit model can't make {} pictures, so nothing was sent."
                           .format(fmt.upper()))
    out = {}
    if fmt in ("svg", "gif"):
        out["outputFormat"] = fmt
    for value, key, (lo, hi), label in (
            (frame_count, "frameCount", EDIT_FRAME_COUNT_RANGE, "The frame count"),
            (frame_duration_ms, "frameDurationMs", EDIT_FRAME_MS_RANGE, "The frame length")):
        if value is None:
            continue
        if fmt != "gif":
            raise LocalRefusal("{} goes only with a GIF, so nothing was sent.".format(label))
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise LocalRefusal("{} must be a whole number from {} to {}, so nothing was sent."
                               .format(label, lo, hi))
        out[key] = value
    if not isinstance(transparent, bool) or not isinstance(auto_tone, bool):
        raise LocalRefusal("The background setting must be on or off, so nothing was sent.")
    if transparent:
        if "transparent" not in have["backgrounds"]:
            raise LocalRefusal("This edit model can't make a see-through background, so "
                               "nothing was sent.")
        if fmt not in (None, "png"):
            raise LocalRefusal("A see-through background goes only with a PNG, so nothing "
                               "was sent.")
        out["background"] = "transparent"
        if not auto_tone:
            out["colorTone"] = "original"
    elif not auto_tone:
        raise LocalRefusal("Auto tone goes only with a see-through background, so nothing "
                           "was sent.")
    return out


def check_edit_outputs(params, caps=None):
    """edit_output_config's rules over an edit's BUILT chat.modelConfig (a --params-json, a
    banked shape): LocalRefusal when its new-output keys break them. Pure; returns None."""
    from moonglade.backup import LocalRefusal
    chat = params.get("chat") if isinstance(params, dict) else None
    mc = chat.get("modelConfig") if isinstance(chat, dict) else None
    if not isinstance(mc, dict):
        return None
    bg, tone = mc.get("background"), mc.get("colorTone")
    if bg is not None and bg != "transparent":
        raise LocalRefusal("The background must be see-through or left out, so nothing was "
                           "sent.")
    if tone is not None and tone != "original":
        raise LocalRefusal("The colour tone must be original or left out, so nothing was sent.")
    fmt = mc.get("outputFormat")
    if fmt == "png":
        fmt = None              # png is the default the app sends as nothing; PixAI takes it
    edit_output_config(chat.get("modelId"), output_format=fmt,
                       frame_count=mc.get("frameCount"),
                       frame_duration_ms=mc.get("frameDurationMs"),
                       transparent=bg == "transparent", auto_tone=tone is None, caps=caps)
    return None


# =============================================================================
# WHAT AN SVG OR A GIF MAY BE A SOURCE FOR (DESIGN_3.22 1.6 and 5.3; 3.22 S5)
# =============================================================================
# PixAI's own rules for a result (`task-Bjykk1Ur.js`): an SVG allows no image tools, no
# use-as-base and no edit; a GIF allows upscale, variations and image-to-text, but not
# use-as-base or edit; neither can become video. The app refuses the same, HERE, before any
# upload or network call. The uses the app's roads name:
#   edit    an edit's source or reference (Edit, Edit Pro)
#   video   a video frame or a reference-video picture (I2V, FLF, R2V)
#   base    a reference or context image on the image road -- the Upscale road included: it
#           sends the picture as the same use-as-base mediaId, so a GIF is refused there too
#           (the refuse reading; PixAI's own GIF upscale is not this request)
#   tool    an AI tool's source: a hand/face Fix, an enhance preset, an AI Tools scene
#   prompt  image-to-prompt (suggest-prompt)
SOURCE_USES = ("edit", "video", "base", "tool", "prompt")
_SOURCE_TAKES = {"svg": frozenset(), "gif": frozenset({"prompt"})}
_SOURCE_WORDS = {"edit": "edited", "video": "a video frame",
                 "base": "used as a base or reference picture", "tool": "used with an AI tool",
                 "prompt": "read for a prompt"}
_SOURCE_EXTS = {".svg": "svg", ".gif": "gif"}
_SOURCE_DATA_TYPES = {"image/svg+xml": "svg", "image/gif": "gif"}


def source_format(value, row=None):
    """"svg" / "gif" / "" for a source: the catalog row's recorded output_format first, then
    its file's extension; with no row, a local path's extension or a data: URL's type. Pure."""
    if isinstance(row, dict):
        rec = str(row.get("output_format") or "").strip().lower()
        if rec in _SOURCE_TAKES:
            return rec
        return _SOURCE_EXTS.get(os.path.splitext(str(row.get("filename") or ""))[1].lower(), "")
    s = str(value or "").strip()
    if s.lower().startswith("data:"):
        return _SOURCE_DATA_TYPES.get(s[5:].split(";", 1)[0].split(",", 1)[0].strip().lower(), "")
    return _SOURCE_EXTS.get(os.path.splitext(s)[1].lower(), "")


def source_refusal(fmt, use):
    """The sentence refusing a `fmt` picture as a `use` source, or None when it is allowed."""
    takes = _SOURCE_TAKES.get(str(fmt or "").lower())
    if takes is None or use in takes:
        return None
    return "{} can't be {} on PixAI, so nothing was sent.".format(
        "An SVG" if fmt == "svg" else "A GIF", _SOURCE_WORDS.get(use, "used here"))


def refuse_unusable_source(fmt, use):
    """LocalRefusal when a `fmt` picture is not a `use` source (source_refusal); else None."""
    why = source_refusal(fmt, use)
    if why:
        from moonglade.backup import LocalRefusal
        raise LocalRefusal(why)


def refuse_unusable_sources(values, use, fmt_of):
    """refuse_unusable_source for each of `values`, its format read by `fmt_of(value)`."""
    for v in values or ():
        if str(v or "").strip():
            refuse_unusable_source(fmt_of(str(v).strip()), use)


def catalog_source_format(out_dir):
    """value -> source_format against the library at `out_dir` (the CLI runners' lookup): a
    local file by its extension, a media id by its catalog row (recorded format, then
    extension), anything else by its own text. A catalog that cannot be read reads as no row."""
    from pathlib import Path
    db = Path(out_dir or ".") / "catalog.db"

    def _fmt(value):
        s = str(value or "").strip()
        if not s.isdigit() or _is_local_source(s):
            return source_format(s)
        from moonglade.backup import known_catalog_rows
        try:
            row = known_catalog_rows(db, [s]).get(s) if db.is_file() else None
        except Exception:                                    # noqa: BLE001 -- no row
            row = None
        return source_format(s, row)
    return _fmt


def build_chat_edit_parameters(prompt, media_ids, model_id=EDIT_PRO_MODEL_ID, *,
                               resolution="1K", aspect_ratio=None, quality="medium",
                               kaisuuken_id="", scene_id="", output_format=None,
                               frame_count=None, frame_duration_ms=None, transparent=False,
                               auto_tone=True, caps=None):
    """Build createGenerationTask's `parameters` for an instruct edit (the `chat`
    block), verified against a real Edit-Pro submit (2026-07-01). `media_ids` is one
    or more source media_ids (an array => multi-image reference editing); the first
    is also sent as `mediaId`. `scene_id` marks a Toolbox PRESET (banked 2026-07-04
    from task 2030050946353349700: a preset = this same chat block + a canned prompt
    + top-level sceneId, e.g. "character-card"; Edit cards match it either way).
    NOTE: `kaisuuken_id` defaults to "" and is only attached (below) when the caller
    passes one explicitly -- same opt-in shape as the other build_*_parameters builders.
    Without one the server charges credits, so this still stays behind --confirm like
    all spend paths.

    `aspect_ratio` left unset (or blank) takes the model's own table default
    (edit_default_aspect). "auto" sends NO aspectRatio at all -- PixAI's own shape for a
    model with no published default (the owner's Reference Pro edits on the wire) -- which
    leaves the frame to PixAI. Only for a model whose table lists "auto": on any other model
    (Edit Pro, or one outside the table) "auto" is not a value it takes, so it gets that
    model's default instead (3:5 on Edit Pro, the pre-table 3:4 off the table).

    Edit Pro's new outputs (DESIGN_3.22 5.1) -- `output_format`, `frame_count`,
    `frame_duration_ms`, `transparent`, `auto_tone` -- go into chat.modelConfig only when set,
    under edit_output_config's rules (`caps`: the live capability read, None = the baked
    table); a combination outside them is LocalRefusal, never clamped.
    """
    from moonglade.backup import PixAIError
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    if not ids:
        raise PixAIError("edit needs at least one source media_id")
    mid = str(model_id or EDIT_PRO_MODEL_ID)
    if not aspect_ratio or (aspect_ratio == EDIT_ASPECT_AUTO and EDIT_ASPECT_AUTO not in
                            ((edit_model_by_id(mid) or {}).get("aspects") or ())):
        aspect_ratio = edit_default_aspect(mid)
    model_config = {"resolution": resolution}
    if aspect_ratio != EDIT_ASPECT_AUTO:
        model_config["aspectRatio"] = aspect_ratio
    # quality is omitted when empty -- Reference Pro exposes no quality option, so sending
    # one would be a bogus knob; Edit Pro still sends low/medium/high.
    if quality:
        model_config["quality"] = quality
    model_config.update(edit_output_config(
        mid, output_format=output_format, frame_count=frame_count,
        frame_duration_ms=frame_duration_ms, transparent=transparent, auto_tone=auto_tone,
        caps=caps))
    params = {"chat": {
        "prompts": prompt or "",
        "mediaId": ids[0],
        "mediaIds": ids,
        "modelId": mid,
        "modelConfig": model_config,
    }}
    if scene_id:
        params["sceneId"] = str(scene_id)
    if kaisuuken_id:
        params["kaisuukenId"] = str(kaisuuken_id)   # spend a free card instead of credits
    return params


def _edit_config_from_args(args):
    """Pull the modelConfig knobs (with defaults) out of CLI/GUI args."""
    model_id = getattr(args, "edit_model", "") or EDIT_PRO_MODEL_ID
    resolution = getattr(args, "edit_resolution", "") or "1K"
    # No --edit-aspect -> the model's own default (Edit Pro 3:5, Reference Pro auto), not a
    # fixed 3:4 that clamp would then keep on every model offering it (SCOPE_2026-09-26 E1).
    aspect_ratio = getattr(args, "edit_aspect", "") or edit_default_aspect(model_id)
    quality = getattr(args, "edit_quality", "") or "medium"
    # Same guard the web /api/edit path already runs (_edit_params_from_payload ->
    # clamp_edit_config) -- without it the CLI can submit a resolution/quality/aspect
    # the resolved model doesn't actually support (e.g. the 1K/medium defaults above,
    # sent to reference-pro, which only exposes 2K/4K and no quality knob at all), an
    # invalid combo on a credit-spend path.
    resolution, quality, aspect_ratio = clamp_edit_config(model_id, resolution, quality, aspect_ratio)
    return dict(
        model_id=model_id,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        quality=quality,
        kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
    )




def clean_fix_boxes(boxes):
    """Filter + normalize hand/face Fix boxes into what POST /v2/task/fixer accepts: tag
    'hand'|'face' (lowercased), non-negative integer origin, positive size, at most 20.
    Anything else is dropped, so a stale or malformed client box can't reach the server --
    a non-finite coordinate (Infinity, NaN: Python's json reads both) included.

    A box that starts above or left of the picture is CLIPPED, not shifted (#93 review F3):
    x -40 width 100 becomes x 0 width 60, the part that is on the picture -- shifting it to
    x 0 width 100 would repair 40 px the box never covered. The far edges are the picture's
    to know, not this function's; the clients clip those.

    Called only through build_fixer_body, which both the price and the submit use: the body
    that gets PRICED has to be the body that gets SUBMITTED, or the cost badge would quote a
    request PixAI never receives."""
    clean = []
    for b in (boxes or []):
        tag = str((b or {}).get("tag") or "").lower()
        if tag not in ("hand", "face"):
            continue
        try:
            x, y = int(b["x"]), int(b["y"])
            w, h = int(b["width"]), int(b["height"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue                     # OverflowError: int(inf); ValueError: int(nan)
        if x < 0:
            w, x = w + x, 0
        if y < 0:
            h, y = h + y, 0
        if w > 0 and h > 0:
            clean.append({"x": x, "y": y, "width": w, "height": h, "tag": tag})
    return clean[:20]


FIX_ONE_KIND = ("A Fix repairs one kind at a time — clear the face boxes or the hand "
                "boxes first.")

def build_fixer_body(media_id, boxes):
    """THE body of a hand/face Fix: {mediaId, boxes}, boxes cleaned by clean_fix_boxes. The
    price (price_fixer, on POST /v2/task/fixer/price) and the spend (submit_fixer, on POST
    /v2/task/fixer) both send what this returns for their own inputs: the SAME boxes (the
    same cleaner, so the same kind, count and coordinates) on the same picture. What differs
    is the media id, deliberately: the gallery's quote names the picture by its CATALOG id
    (/api/price runs no media resolver -- it would upload once per keystroke), while its spend
    names it by the upload-kind id the submit's resolver gets by uploading the local file
    first (PixAI refuses a generation OUTPUT id as an input on this path). PixAI's price does
    not move with the picture (measured 2026-10-28: 4,800 for every source size), so the
    number quoted is the number charged.

    Raises PixAIError when no box survives the cleaner, and FIX_ONE_KIND when the boxes carry
    more than one tag: since PixAI's Hand Fix / Face Fix launch (2026-10-21) its server
    refuses a face box and a hand box in one Fix ("all boxes must share one tag", measured
    2026-10-28 on the price route, which shares the submit route's input schema). A Fix is
    one pass of one kind."""
    from moonglade.backup import PixAIError
    clean = clean_fix_boxes(boxes)
    if not clean:
        raise PixAIError("drag a box over a hand or face")
    if len({b["tag"] for b in clean}) > 1:
        raise PixAIError(FIX_ONE_KIND)
    return {"mediaId": str(media_id), "boxes": clean}


# =============================================================================
# ENHANCE ON PIXAI'S REST ROUTE (DESIGN_3.22 2.3; 3.22 S3-enhance)
# =============================================================================
# POST /v2/task/enhance takes {enhanceType, mediaId, prompt?}, not a panelplugin workflow
# (task.createTask refuses workflow keys). The site maps a workflow to its enhanceType as
# `task-CtewRxby.js` ke() does: the workflow name's part before ":" matched against PixAI's live
# config constants.imageEnhancementPlugins[<enhanceType>].workflowName. G and Q below are that
# file's own lists.
ENHANCE_TYPES = ("handfix", "face-detailer", "emotion", "background-remover",
                 "image-to-lineart", "sketch-coloring")                 # task-CtewRxby.js G
ENHANCE_PROMPT_TYPES = ("face-detailer", "emotion", "sketch-coloring")   # task-CtewRxby.js Q
ENHANCE_UNMAPPED = ("Couldn't match this AI preset to PixAI's enhance route, so nothing was "
                    "sent -- try again in a minute")


def enhance_type_for(workflow_name, plugins=None):
    """The enhanceType PixAI's site would send for `workflow_name` (an "author/workflow:ver"
    preset address), or None. `plugins` is constants.imageEnhancementPlugins; None reads it
    from PixAI's live public config (cached, fail-soft). Only the six known types are ever
    answered. Pure when `plugins` is given."""
    name = str(workflow_name or "").split(":", 1)[0].strip()
    if not name:
        return None
    if plugins is None:
        from moonglade.backup import _cached_config
        plugins = (_cached_config("constants") or {}).get("imageEnhancementPlugins")
    if not isinstance(plugins, dict):
        return None
    for key, row in plugins.items():
        if key in ENHANCE_TYPES and isinstance(row, dict) and row.get("workflowName") == name:
            return key
    return None


def build_enhance_body(media_id, enhance_type, prompt=None):
    """THE body of an enhance on the REST route: {enhanceType, mediaId, prompt?}, the site's
    q(): a prompt rides only the three types that take one, and an emotion needs one (its ye()).
    Raises LocalRefusal for an unknown type, no source, or an emotion with no prompt."""
    from moonglade.backup import LocalRefusal
    t = str(enhance_type or "")
    mid = str(media_id or "").strip()
    if t not in ENHANCE_TYPES:
        raise LocalRefusal(ENHANCE_UNMAPPED)
    if not mid:
        raise LocalRefusal("pick an image first")
    body = {"enhanceType": t, "mediaId": mid}
    if t in ENHANCE_PROMPT_TYPES and isinstance(prompt, str) and prompt.strip():
        body["prompt"] = prompt
    if t == "emotion" and "prompt" not in body:
        raise LocalRefusal("pick an expression first")
    return body


# =============================================================================
# THE WIRE GUARD (DESIGN_3.22 2.4): priced = sent, checked on the final bytes
# =============================================================================
# PixAI's REST create routes strip every key their schema does not name, at every depth,
# silently (zod `object`, harvest 938fb68efeea `vendor-validation-D9eDNToB.js`). A key the app
# priced and card-checked but PixAI then dropped is a job nobody quoted. So the create door
# checks the exact object it is about to send against the schema below and REFUSES on any key
# outside it -- never strips. Each object cites the harvest symbol it mirrors
# (`BaseTaskSubmitForm-BYhygXK9.js` unless named; re-diffed by the monthly P9).
#
# A spec is: _SCALAR (a str, number, bool or null -- never an object or a list, so nothing can
# hide under it), a dict (an object with exactly these keys allowed), a one-item list (an
# array whose every element is that spec), or _RECORD (an object with free keys and scalar
# values: `lora`'s versionId -> weight map, `It`).
_SCALAR = "scalar"
_RECORD = "record"
_PALETTE_GROUP = {"colors": [{"hex": _SCALAR, "ratio": _SCALAR}]}        # paletteData-qnWMp3nI m, n
_WIRE_IMAGE = {                                                        # `yt`, the plain image keys
    # prompt and model
    "prompts": _SCALAR, "negativePrompts": _SCALAR, "modelId": _SCALAR, "model": _SCALAR,
    "modelStyle": {"type": _SCALAR, "keyId": _SCALAR, "custom": _SCALAR,   # `Wa` (a union)
                   "refId": _SCALAR},
    "vaeModelId": _SCALAR, "characterId": _SCALAR, "sceneId": _SCALAR,
    # size and sampling
    "width": _SCALAR, "height": _SCALAR, "seed": _SCALAR, "samplingSteps": _SCALAR,
    "samplingMethod": _SCALAR, "cfgScale": _SCALAR, "clipSkip": _SCALAR, "batchSize": _SCALAR,
    "priority": _SCALAR,
    # inputs
    "mediaId": _SCALAR, "contextImages": [_SCALAR],                     # `Fn`
    "controlNets": [{"type": _SCALAR, "mediaId": _SCALAR, "weight": _SCALAR,   # `Un` of `Vn`
                     "thresholdA": _SCALAR, "maskMediaId": _SCALAR}],
    "lora": _RECORD,                                                    # `It`
    "loraParameters": [{"versionId": _SCALAR, "triggerWords": _SCALAR,  # `Gn` of `Bn`
                        "weight": _SCALAR,
                        "positionInfo": {"startIndex": _SCALAR, "endIndex": _SCALAR}}],  # `jn`
    "recipeIds": [_SCALAR],                                             # `es`
    "colorPalette": {"source": _SCALAR, "id": _SCALAR, "name": _SCALAR,  # `xi` = paletteData g
                     "createdAt": _SCALAR, "updatedAt": _SCALAR,
                     "palette": {"overall": _PALETTE_GROUP, "background": _PALETTE_GROUP,
                                 "character": _PALETTE_GROUP}},          # paletteData b
    "maskMediaId": _SCALAR, "strength": _SCALAR,
    "sdedit": {"spectralScale": _SCALAR, "hfsBlurSigma": _SCALAR,       # `va` = inpaint-CusgHKxP S
               "hfsEnd": _SCALAR, "colorCorrection": _SCALAR},
    "latentCouple": {"type": _SCALAR, "divisions": [_SCALAR],           # `Jn`
                     "positions": [_SCALAR], "weights": [_SCALAR]},
    # boosters and upscale
    "qualityTag": {"prefix": _SCALAR, "suffix": _SCALAR},               # `Ya`
    "styleMix": {"enabled": _SCALAR, "seed": _SCALAR, "weight": _SCALAR},   # `as`
    "enableADetailer": _SCALAR, "upscale": _SCALAR, "upscaleDenoisingSteps": _SCALAR,
    "upscaleDenoisingStrength": _SCALAR, "upscaleSampler": _SCALAR, "enlarge": _SCALAR,
    "enlargeModel": _SCALAR, "enableTile": _SCALAR,
    # profile and helper
    "inferenceProfile": _SCALAR,
    "inferenceConfig": {"rescaleCFG": _SCALAR,                          # `Ka`
                        "modelSampling": {"inputs": {"shift": _SCALAR}}},
    "promptHelper": {k: _SCALAR for k in (                              # `Et`
        "withStage", "userWantToEnable", "enable", "creativity",
        "forcePromptHelperDetectionSide", "creativeMode", "agentic", "agenticCompare")},
    # lanes and cards (`kaisuukenExtraCredits` is in PixAI's schema and never in this one: D2)
    "lane": _SCALAR, "channel": _SCALAR, "kaisuukenId": _SCALAR,
    # other
    "extra": {"naturalPrompts": _SCALAR, "referenceImagePrompts": _SCALAR,   # `Hn` = he.extend
              "triggerWords": _SCALAR, "source": _SCALAR},
    "watermark": _SCALAR,
}
_WIRE_CHAT = {                                                         # `rs`
    "prompts": _SCALAR, "mediaId": _SCALAR, "mediaIds": [_SCALAR], "modelId": _SCALAR,
    "workspaceId": _SCALAR,
    # `Ln`, cut to the keys this app builds (DESIGN_3.22 5.1): the three it always sent and Edit
    # Pro's five new outputs. `layerDecomposition` is PixAI's and never built here, so it is
    # refused like a misspelling (the refuse reading).
    "modelConfig": {k: _SCALAR for k in (
        "resolution", "aspectRatio", "quality",
        "outputFormat", "frameCount", "frameDurationMs", "background", "colorTone")},
}
#: The final body per door kind -- the wrapper included for /task/create (`ys` takes
#: `parameters` and `thread`; the app never sends a thread, so only `parameters` is allowed).
#: The edit shape is `ns`: the image keys and `chat`. The video, t2i2v, inpaint and remix
#: blocks the union also knows are not this app's to send on these kinds, so they are refused.
WIRE_SCHEMA = {
    "image": {"parameters": _WIRE_IMAGE},
    "edit": {"parameters": dict(_WIRE_IMAGE, chat=_WIRE_CHAT)},
    # POST /v2/task/chat-editing-scene, `ChatEditingPresetWrapper-BSt4gUa4.js` via create-*.js
    "scene": {"sceneId": _SCALAR, "mediaIds": [_SCALAR], "preset": _SCALAR, "custom": _SCALAR,
              "selectorValues": [{"id": _SCALAR, "value": _SCALAR}]},
    # POST /v2/task/enhance, `task-CtewRxby.js`
    "enhance": {"enhanceType": _SCALAR, "mediaId": _SCALAR, "prompt": _SCALAR},
    # POST /v2/task/fixer: build_fixer_body's {mediaId, boxes} (the route the app sends today)
    "fix": {"mediaId": _SCALAR,
            "boxes": [{"x": _SCALAR, "y": _SCALAR, "width": _SCALAR, "height": _SCALAR,
                       "tag": _SCALAR}]},
}
#: PixAI's `Es` guard: workflow and art-filter tasks are created through GraphQL, never here.
WIRE_WORKFLOW_KEYS = ("workflow", "workflowId", "workflowName", "workflowVersionId", "inputs")
#: What the REST create routes drop and the app may still build (the video and panelplugin
#: builders): dropped by rest_wire, by name, never silently (DESIGN_3.22 2.4 rule 4).
WIRE_KNOWN_DROPS = ("enablePreview", "hidePrompts", "isPrivate")
_WIRE_ENUMS = {"channel": ("normal", "private"),                     # `Ne`
               "lane": ("normal", "infinite"),                       # `Xn`
               "watermark": ("pixai",)}
_WIRE_OUTPUT_FORMATS = ("png", "svg", "gif")                          # chatEditing-DtzDRo8B.js


def _wire_refusal(why):
    from moonglade.backup import LocalRefusal
    return LocalRefusal("PixAI's create route would not take this request as built ({}), so "
                        "nothing was sent.".format(why))


def rest_wire(kind, params):
    """The REST half of to_wire, for one door kind: a COPY of `params` with the known-drop
    list applied (pure). `isPrivate` follows one rule: with no `channel` it becomes the channel
    ("private" when true, else "normal"); when both are present and disagree the request is
    refused; then it is dropped. `enablePreview` and `hidePrompts` are dropped. A kind whose
    body is not a generation's parameters (scene, enhance, fix) comes back as a plain copy."""
    import copy
    p = copy.deepcopy(params)
    if kind not in ("image", "edit") or not isinstance(p, dict):
        return p
    if "isPrivate" in p:
        if not isinstance(p.get("isPrivate"), bool):
            raise _wire_refusal("isPrivate must be true or false")
        want = "private" if p["isPrivate"] else "normal"
        if "channel" not in p:
            p["channel"] = want
        elif p.get("channel") != want:
            raise _wire_refusal("isPrivate and channel disagree")
        p.pop("isPrivate")
    for k in ("enablePreview", "hidePrompts"):
        p.pop(k, None)
    return p


def wire_drops(kind, params):
    """The keys rest_wire drops from `params` for `kind`, by name -- for the Inspector's
    request record. [] for a GraphQL kind, or when nothing is dropped. Pure."""
    from moonglade.gen_road import CREATE_ROAD
    if CREATE_ROAD.get(kind) != "rest" or kind not in ("image", "edit") \
            or not isinstance(params, dict):
        return []
    return [k for k in WIRE_KNOWN_DROPS if k in params]


def to_wire(kind, params):
    """THE road-aware wire step (DESIGN_3.22 2.4 rule 2), pure. On a kind gen_road.CREATE_ROAD
    sends over GraphQL it returns `params` itself, unchanged (the video and reference-video
    bodies stay byte for byte what they were); on a REST kind it returns rest_wire's copy. It is
    the last step of build_request, so the badge, the card check and the preview see the shape
    the door will send; the door runs rest_wire again on the final object, and that is the run
    that counts."""
    from moonglade.gen_road import CREATE_ROAD
    if CREATE_ROAD.get(kind) != "rest":
        return params
    return rest_wire(kind, params)


def _wire_walk(spec, value, path, misses):
    if spec == _SCALAR:
        if isinstance(value, (dict, list)):
            misses.append("{} must be a single value".format(path))
        return
    if spec == _RECORD:
        if not isinstance(value, dict):
            misses.append("{} must be an object".format(path))
            return
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                misses.append("{}.{} must be a single value".format(path, k))
        return
    if isinstance(spec, list):
        if not isinstance(value, list):
            misses.append("{} must be a list".format(path))
            return
        for i, item in enumerate(value):
            _wire_walk(spec[0], item, "{}[{}]".format(path, i), misses)
        return
    if not isinstance(value, dict):
        misses.append("{} must be an object".format(path))
        return
    for k, v in value.items():
        sub = "{}.{}".format(path, k) if path else str(k)
        if k not in spec:
            misses.append("{} is not a field it takes".format(sub))
            continue
        _wire_walk(spec[k], v, sub, misses)


def check_wire(kind, body):
    """THE recursive allowlist (DESIGN_3.22 2.4 rule 3, 5): refuse (LocalRefusal, nothing sent)
    unless every key of `body` -- the FINAL object the door is about to send, wrapper included
    -- is in WIRE_SCHEMA[kind] at its depth, and the cheap load-bearing value rules hold.
    Never strips. Returns None."""
    if kind not in WIRE_SCHEMA or not isinstance(body, dict):
        raise _wire_refusal("no wire schema for {!r}".format(str(kind)[:40]))
    inner = body.get("parameters") if kind in ("image", "edit") else body
    if not isinstance(inner, dict):
        raise _wire_refusal("no parameters")
    # The named refusals first, so the sentence says what is wrong, not only where.
    if _wire_has_key(body, "kaisuukenExtraCredits"):
        raise _wire_refusal("a free card never carries extra credits")
    if kind in ("scene", "enhance", "fix") and _wire_has_key(body, "kaisuukenId"):
        raise _wire_refusal("a free card never rides this kind")
    if kind in ("image", "edit"):
        hit = [k for k in WIRE_WORKFLOW_KEYS if k in inner]
        if hit:
            raise _wire_refusal("workflow tasks are not created on this route: " + hit[0])
    misses = []
    _wire_walk(WIRE_SCHEMA[kind], body, "", misses)
    if misses:
        raise _wire_refusal(misses[0])
    for k, allowed in _WIRE_ENUMS.items():
        if k in inner and inner[k] not in allowed:
            raise _wire_refusal("{} must be one of {}".format(k, "/".join(allowed)))
    mc = (inner.get("chat") or {}).get("modelConfig") if kind == "edit" else None
    if isinstance(mc, dict):
        fmt = mc.get("outputFormat")
        if fmt is not None and fmt not in _WIRE_OUTPUT_FORMATS:
            raise _wire_refusal("outputFormat must be png, svg or gif")
        for key, lo, hi in (("frameCount", 2, 16), ("frameDurationMs", 20, 2000)):
            if key not in mc:
                continue
            v = mc[key]
            if fmt != "gif":
                raise _wire_refusal("{} goes only with a gif".format(key))
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise _wire_refusal("{} must be a whole number {}-{}".format(key, lo, hi))


def _wire_has_key(value, key):
    """True when `key` is an object key anywhere inside `value`."""
    if isinstance(value, dict):
        return key in value or any(_wire_has_key(v, key) for v in value.values())
    if isinstance(value, list):
        return any(_wire_has_key(v, key) for v in value)
    return False

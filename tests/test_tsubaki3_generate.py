"""Session H -- Tsubaki.3 in the Generate drawer, the server half (lane w2-gen).

Design and its adversarial review: moonglade-internal/design/notes/tsubaki3-generate/
BUILD-w2-gen.md. What is pinned here:

  - the web payload's `context_images` and `creativity` (refused, never repaired);
  - a context-image request: the ids go out as they are, what the feature excludes is not
    sent, and every combination PixAI's own site would never send is refused at build --
    a reference beside them, an upscale, LoRAs, recipes, a style, the lane, an @imageN with
    no slot, a model that does not take them, an unreadable /features, more than the live max;
  - the creativity stop: shaped on the gate's own /features read, forced to medium beside
    context images, one step lower beside recipes, the legacy shape on another architecture;
  - the gate stays idempotent (the backstops in price_task / submit_generation re-gate);
  - profiles: an unlisted one is refused at build; a LISTED one PixAI refuses is never
    resubmitted on the default, and a members-only one stands the Turbo fallback down;
  - the price breakdown (context images' charge, a non-default profile's), priced only;
  - the drawer's meta (size tiers, the live context max, creativity, the profile rows);
  - the Tsubaki edit ids, mirrored in gallery/src/gen/tsubakiCore.js.

Every PixAI read is faked at `_rest_get`; nothing here reaches a network.
"""
import json
import re
from pathlib import Path

import pytest

import moonglade_backup as core
from tests.test_tsubaki3_image_gate import (
    FLASH, MODELS, SDXL, SIZE_CONFIG, T3, T3_PROFILES, FakeRest, features, T3_STATUS,
)

ROOT = Path(__file__).resolve().parent.parent

# auth/T3v_size-config.json's shape: the ranges WITH their presets (the gate reads the ranges,
# the drawer's tier row the presets).
SIZE_CONFIG_PRESETS = {"ranges": [
    {"name": "XL", "minWidth": 512, "maxWidth": 2496, "minHeight": 512, "maxHeight": 2496,
     "step": 16, "requiredMembershipTier": 0, "accessStatus": "available",
     "defaultPresetId": "xl-a",
     "presets": [{"id": "xl-a", "width": 1104, "height": 1824, "ratioLabel": "3:5"},
                 {"id": "xl-b", "width": 1408, "height": 1408, "ratioLabel": "1:1"}]},
    {"name": "L", "minWidth": 512, "maxWidth": 2200, "minHeight": 512, "maxHeight": 2200,
     "step": 16, "requiredMembershipTier": 1, "accessStatus": "available",
     "defaultPresetId": "l-a",
     "presets": [{"id": "l-a", "width": 944, "height": 1584, "ratioLabel": "3:5"}]},
]}
PROFILES_FULL = {"profiles": [
    {"profileName": "pro", "profileFlag": "default", "title": "Pro",
     "desc": "Higher detail.", "basePrice": 3000, "requiredMembershipTier": 0},
    {"profileName": "ultra", "profileFlag": "membershipOnly", "title": "Ultra",
     "desc": "Maximum detail.", "basePrice": 3500, "requiredMembershipTier": 1},
]}
MODEL_CONFIG = {"configs": {"pixai-app": {"params": {"contextImages": {
    "visibility": "enabled", "kind": "media", "media": {"types": ["image"], "maxCount": 3}}}}}}


class Rest(FakeRest):
    """FakeRest plus /model-config and a price that knows context images and profiles:
    4000 base, +900 per context image, +500 on Ultra."""

    def __init__(self, model_config=MODEL_CONFIG, **kw):
        super().__init__(**kw)
        self.model_config = model_config
        self.models[T3] = dict(self.models[T3], **{"inference-profiles": PROFILES_FULL})

    def __call__(self, session, path, params=None, **k):
        m = re.match(r"^/model-config/([^/]+)$", path)
        if m:
            self.calls.append(path)
            if isinstance(self.model_config, Exception):
                raise self.model_config
            if (params or {}).get("source") != "pixai-app":
                raise core.PixAIError("400 source")
            return self.model_config
        if path == "/task-price":
            self.priced.append(dict(params or {}))
            q = params or {}
            n = len(json.loads(q["contextImages"])) if "contextImages" in q else 0
            return {"actualPrice": 4000 + 900 * n + (500 if q.get("inferenceProfile") == "ultra" else 0)}
        return super().__call__(session, path, params, **k)


@pytest.fixture
def rest(monkeypatch):
    fake = Rest()
    monkeypatch.setattr(core, "_rest_get", fake)
    return fake


def road(payload, **kw):
    s = object()
    return core.build_request(payload, mode="image", resolve=core.RequestResolver(
        gate=core.gate_resolver(s), features=core.features_resolver(s),
        unlimited=core.unlimited_resolver(s)), **kw)


def ctx_payload(**kw):
    p = {"version_id": T3, "prompt": "Use @image1 as the face, the pose from @image2",
         "negative": "", "mode": "pro", "width": 1632, "height": 912, "count": 1,
         "prompt_helper": True, "creativity": "medium", "context_images": ["701", "702"],
         "loras": []}
    p.update(kw)
    return p


# =============================================================================
# the web payload
# =============================================================================

@pytest.mark.parametrize("bad", ["701", [701.5], ["7a1"], [""], ["701", "701"]])
def test_context_images_must_be_a_list_of_distinct_ids(bad, rest):
    with pytest.raises(core.PixAIError):
        road(ctx_payload(context_images=bad))


def test_creativity_must_be_a_level(rest):
    with pytest.raises(core.PixAIError, match="off, low or medium"):
        road(ctx_payload(creativity="high"))


# =============================================================================
# a context-image request
# =============================================================================

def test_the_ids_go_out_as_they_are_and_what_the_feature_excludes_is_not_sent(rest):
    req = road(ctx_payload(negative="<negative>", ref_strength=0.7))
    p = req.parameters
    assert p["contextImages"] == ["701", "702"]
    assert "mediaId" not in p and "strength" not in p and "negativePrompts" not in p
    assert "lora" not in p and "loraParameters" not in p
    assert p["promptHelper"] == {"creativity": "medium", "forcePromptHelperDetectionSide": "server"}
    assert p["extra"] == {"naturalPrompts": p["prompts"]} and "naturalPrompts" not in p
    assert {a["field"] for a in req.adjusted} >= {"negativePrompts"}


def test_context_images_run_creativity_at_medium_with_a_receipt(rest):
    req = road(ctx_payload(creativity="off"))
    assert req.parameters["promptHelper"]["creativity"] == "medium"
    rec = [a for a in req.adjusted if a["field"] == "promptHelper"]
    assert rec and rec[0]["asked"] == "off" and rec[0]["used"] == "medium"


@pytest.mark.parametrize("change,words", [
    ({"ref_media_id": "M1"}, "not both"),
    ({"enlarge": 2}, "upscale"),
    ({"upscale": 1.5}, "upscale"),
    ({"prompt": "Use @image3"}, "names @image3, but only 2 context images are set"),
    ({"prompt": "Use @image0"}, "names @image0"),
    ({"loras": [{"version_id": "L1", "weight": 0.7}]}, "can't combine context images with LoRAs"),
    ({"context_images": ["701", "702", "703", "704"], "prompt": "p"}, "up to 3 context images — remove 1"),
    ({"version_id": SDXL}, "doesn't take context images"),
])
def test_what_a_context_image_request_may_not_carry_is_refused(change, words, rest):
    with pytest.raises(core.PixAIError) as err:
        road(ctx_payload(**change))
    assert words in str(err.value)
    assert rest.priced == [], "a refusal is decided before any price read"


def test_an_unreadable_features_read_refuses_context_images(rest):
    rest.models[T3] = dict(rest.models[T3], features=core.PixAIError("503"))
    with pytest.raises(core.PixAIError, match="context images can't be checked|creativity can't be set"):
        road(ctx_payload())


def test_the_live_max_comes_from_model_config_and_falls_back_to_three(rest):
    rest.model_config = {"configs": {"pixai-app": {"params": {"contextImages": {
        "media": {"maxCount": 2}}}}}}
    with pytest.raises(core.PixAIError, match="up to 2 context images — remove 1"):
        road(ctx_payload(context_images=["701", "702", "703"], prompt="p"))
    core._model_config_cache.clear()
    rest.model_config = core.PixAIError("503")
    assert road(ctx_payload(context_images=["701", "702", "703"], prompt="p")).parameters[
        "contextImages"] == ["701", "702", "703"]
    with pytest.raises(core.PixAIError, match="up to 3"):
        road(ctx_payload(context_images=["701", "702", "703", "704"], prompt="p"))


@pytest.mark.parametrize("extra,words", [
    ({"recipeIds": ["2046394714775712134"]}, "Recipes are held"),
    ({"modelStyle": {"type": "key", "keyId": "k"}}, "style"),
    ({"lane": "infinite"}, "Unlimited Mode can't use a reference picture"),
    ({"mediaId": "M1"}, "not both"),
    ({"lora": {"L1": 0.7}}, "LoRAs"),
    ({"chat": {"modelId": "x"}}, "edit or an upscale"),
])
def test_the_gate_refuses_a_hand_built_context_image_dict(extra, words, rest):
    p = {"prompts": "p", "modelId": T3, "width": 1024, "height": 1024, "batchSize": 1,
         "contextImages": ["701"]}
    p.update(extra)
    with pytest.raises(core.PixAIError) as err:
        core._gate_image_params(object(), p)
    assert words in str(err.value)


def test_a_lane_request_never_carries_context_images(rest, monkeypatch):
    monkeypatch.setattr(core, "infinite_mode_status",
                        lambda s, v: {"owned": True, "expires_at": "2099-01-01", "days_left": 9})
    with pytest.raises(core.PixAIError):
        road(ctx_payload(unlimited=True, mode="pro"))


# =============================================================================
# creativity
# =============================================================================

@pytest.mark.parametrize("level", ["off", "low", "medium"])
def test_the_stop_goes_out_as_asked_without_context_images(level, rest):
    req = road({"version_id": T3, "prompt": "<p>", "creativity": level, "mode": "pro",
                "prompt_helper": level != "off", "width": 1024, "height": 1024})
    p = req.parameters
    assert p["promptHelper"] == {"creativity": level, "forcePromptHelperDetectionSide": "server"}
    if level == "off":
        assert "extra" not in p and "naturalPrompts" not in p
    else:
        assert p["extra"] == {"naturalPrompts": "<p>"}
    assert not [a for a in req.adjusted if a["field"] == "promptHelper"]


def test_another_architecture_keeps_the_legacy_helper_with_a_receipt(rest):
    req = road({"version_id": SDXL, "prompt": "<p>", "creativity": "off",
                "prompt_helper": False, "width": 1024, "height": 1024})
    assert req.parameters["promptHelper"] == {"withStage": False, "userWantToEnable": False,
                                              "forcePromptHelperDetectionSide": "server"}
    assert any(a["field"] == "creativity" and a["used"] is None for a in req.adjusted)


def test_recipes_run_the_helper_one_step_lower_at_build(rest):
    """The site's own rule (task-*.js): hasRecipes ? (medium -> low, else off). Keyed on the
    BUILT params' recipeIds (the passthrough is lane w2-recipes'), so it fires only when the
    recipes are really sent."""
    rs = core.RequestResolver(features=core.features_resolver(object()))
    for asked, used in (("medium", "low"), ("low", "off"), ("off", "off")):
        params, adjusted = {"recipeIds": ["1"], "modelId": T3}, []
        core._shape_creativity(params, asked, rs, T3, adjusted)
        assert params["promptHelper"]["creativity"] == used
        assert bool(adjusted) == (asked != "off")
    params, adjusted = {"modelId": T3}, []
    core._shape_creativity(params, "medium", rs, T3, adjusted)
    assert params["promptHelper"]["creativity"] == "medium" and adjusted == []


def test_a_road_without_the_features_resolver_ignores_creativity(rest):
    req = core.build_request({"version_id": T3, "prompt": "<p>", "creativity": "off",
                              "prompt_helper": False, "width": 1024, "height": 1024},
                             mode="image", resolve=core.RequestResolver(
                                 gate=core.gate_resolver(object())))
    assert req.parameters["promptHelper"]["creativity"] == "off"      # the legacy off, via G6


@pytest.mark.parametrize("ctx", [False, True])
@pytest.mark.parametrize("level", ["off", "low", "medium"])
@pytest.mark.parametrize("with_extra", [False, True])
def test_the_gate_is_idempotent_on_every_creativity_shape(ctx, level, with_extra, rest):
    p = {"prompts": "p", "naturalPrompts": "p", "modelId": T3, "width": 1024, "height": 1024,
         "batchSize": 1, "inferenceProfile": "pro",
         "promptHelper": {"creativity": level, "forcePromptHelperDetectionSide": "server"}}
    if ctx:
        p["contextImages"] = ["701"]
    if with_extra:
        p["extra"] = {"other": 1}
    once, _ = core._gate_image_params(object(), p)
    twice, adjusted = core._gate_image_params(object(), once)
    assert twice is once and adjusted == []


# =============================================================================
# profiles
# =============================================================================

def test_an_unlisted_profile_is_refused_at_build(rest):
    with pytest.raises(core.PixAIError, match="doesn't offer the lite profile"):
        road({"version_id": T3, "prompt": "<p>", "mode": "lite", "width": 1024, "height": 1024})


def test_a_listed_profile_pixai_refuses_is_never_resubmitted_on_the_default(rest, monkeypatch):
    sent = []

    def fake(s, q, v=None):
        sent.append(dict(v["parameters"]))
        raise core.PixAIError('GraphQL error: [{"message": "inferenceProfile ultra requires membership"}]')
    monkeypatch.setattr(core, "gql_mutate", fake)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    params = {"prompts": "p", "modelId": T3, "width": 1024, "height": 1024, "batchSize": 1,
              "inferenceProfile": "ultra", "priority": core.PRIORITY_TURBO}
    with pytest.raises(core.PixAIError, match="refused the ultra profile"):
        core.submit_generation(object(), params)
    assert len(sent) == 1


def test_a_members_only_profile_stands_the_turbo_fallback_down(rest, monkeypatch):
    sent = []

    def fake(s, q, v=None):
        sent.append(dict(v["parameters"]))
        raise core.PixAIError('GraphQL error: [{"message": "REQUIRE_MEMBERSHIP"}]')
    monkeypatch.setattr(core, "gql_mutate", fake)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    params = {"prompts": "p", "modelId": T3, "width": 1024, "height": 1024, "batchSize": 1,
              "inferenceProfile": "ultra", "priority": core.PRIORITY_TURBO}
    with pytest.raises(core.PixAIError):
        core.submit_generation(object(), params)
    assert len(sent) == 1
    # ...while Pro (listed, not members-only) keeps the Turbo self-heal
    sent.clear()
    calls = []

    def fake2(s, q, v=None):
        calls.append(dict(v["parameters"]))
        if v["parameters"].get("priority") == core.PRIORITY_TURBO:
            raise core.PixAIError('GraphQL error: [{"message": "REQUIRE_MEMBERSHIP"}]')
        return {"createGenerationTask": {"id": "T1"}}
    monkeypatch.setattr(core, "gql_mutate", fake2)
    monkeypatch.setattr(core, "_turbo_refused", {"seen": False})
    assert core.submit_generation(object(), dict(params, inferenceProfile="pro")) == "T1"
    assert len(calls) == 2 and calls[1]["priority"] == core.PRIORITY_LOW


@pytest.mark.parametrize("message,profile", [
    ("inferenceProfile lite is not supported by this model", "lite"),
    ("REQUIRE_MEMBERSHIP", "pro"),
])
def test_a_partial_success_is_never_resubmitted(rest, monkeypatch, message, profile):
    """PixAI answered with errors AND a created task (`data.createGenerationTask` non-null):
    the task exists and may be charged. Neither the profile drop nor the Turbo-to-standard
    resubmit may send it again -- that would be a second paid generation (red team
    2026-10-01). The error goes back to the caller exactly as it came."""
    sent = []

    def fake(s, q, v=None):
        sent.append(dict(v["parameters"]))
        e = core.PixAIError('GraphQL error: [{"message": "%s"}]' % message)
        e.graphql_data = {"createGenerationTask": {"id": "T-made"}}
        raise e
    monkeypatch.setattr(core, "gql_mutate", fake)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "_turbo_refused", {"seen": False})
    # Reach the two resubmit branches: the profile is not one the version lists (so the
    # inferenceProfile drop is the road taken) and not members-only (so Turbo may step down).
    monkeypatch.setattr(core, "_profile_listing", lambda s, p: (False, False))
    monkeypatch.setattr(core, "_gate_image_params", lambda s, p: (p, []))
    params = {"prompts": "p", "modelId": T3, "width": 1024, "height": 1024, "batchSize": 1,
              "inferenceProfile": profile, "priority": core.PRIORITY_TURBO}
    with pytest.raises(core.PixAIError) as ei:
        core.submit_generation(object(), params)
    assert len(sent) == 1, "a partial success was sent a second time"
    assert core.definite_refusal(ei.value) is False


# =============================================================================
# the price breakdown
# =============================================================================

def test_the_breakdown_names_the_context_charge_and_a_non_default_profile(rest, monkeypatch):
    matched = []
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: matched.append(params))
    req = road(ctx_payload(mode="ultra"))
    out = core.price(object(), req)
    assert out["cost"] == 4000 + 1800 + 500
    assert out["context_images"] == 2 and out["context_charge"] == 1800
    assert out["profile"] == "Ultra" and out["profile_extra"] == 500
    assert matched == [req.parameters], "only the real dict is card-checked"
    assert req.parameters["contextImages"] == ["701", "702"]      # the variants never touch it
    assert req.parameters["inferenceProfile"] == "ultra"


def test_no_breakdown_on_the_default_profile_or_a_card_covered_quote(rest, monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: None)
    out = core.price(object(), road({"version_id": T3, "prompt": "p", "mode": "pro",
                                     "width": 1024, "height": 1024}))
    assert "profile" not in out and "context_images" not in out
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: {
        "total": 3, "consumeAmount": 1, "covered": True, "name": "card"})
    monkeypatch.setattr(core, "card_covers", lambda best: True)
    out = core.price(object(), road(ctx_payload()))
    assert out["free"] is True and "context_charge" not in out


# =============================================================================
# the drawer's meta
# =============================================================================

def test_the_meta_carries_tiers_the_live_max_creativity_and_the_profile_rows(rest):
    rest.models[T3] = dict(rest.models[T3], **{"size-config": SIZE_CONFIG_PRESETS})
    meta = core._attach_features(object(), core._attach_profiles(
        object(), dict(core._empty_version_meta(), version_id=T3)))
    assert meta["context_images"] is True and meta["context_max"] == 3
    assert meta["creativity"] is True
    xl, l = meta["size_tiers"]
    assert xl == {"name": "XL", "min": 512, "max": 2496, "step": 16, "required_tier": 0,
                  "access": "available", "default": [1104, 1824],
                  "presets": [{"ratio": "3:5", "width": 1104, "height": 1824},
                              {"ratio": "1:1", "width": 1408, "height": 1408}]}
    assert l["required_tier"] == 1 and l["default"] == [944, 1584]
    rows = meta["profile_rows"]
    assert [r["name"] for r in rows] == ["pro", "ultra"]
    assert rows[1] == {"name": "ultra", "title": "Ultra", "desc": "Maximum detail.",
                       "base_price": 3500, "flag": "membershipOnly", "required_tier": 1}
    # the gate still reads plain ranges off the same cached body
    assert list(core._model_size_config(object(), T3)) == [(512, 2496, 512, 2496),
                                                           (512, 2200, 512, 2200)]


def test_an_sdxl_version_has_no_tiers_no_max_and_no_creativity(rest):
    meta = core._attach_features(object(), dict(core._empty_version_meta(), version_id=SDXL))
    assert meta["size_tiers"] is None and meta["context_max"] is None
    assert meta["creativity"] is False


# =============================================================================
# the JS mirrors
# =============================================================================

def test_the_tsubaki3_ids_match_the_drawer_copy():
    js = (ROOT / "gallery/src/gen/tsubakiCore.js").read_text(encoding="utf-8")
    m = re.search(r'TSUBAKI3 = \{ model_id: "(\d+)", version_id: "(\d+)"', js)
    assert m and m.group(1) == core.TSUBAKI3_MODEL_ID and m.group(2) == core.TSUBAKI3_VERSION_ID
    assert core.TSUBAKI3_VERSION_ID in core.UNLIMITED_VERSIONS


def test_the_image_ref_rule_matches_the_drawer_copy():
    js = (ROOT / "gallery/src/gen/tsubakiCore.js").read_text(encoding="utf-8")
    assert "export const AT_REF_RE = /@image(\\d+)/g;" in js
    assert core._IMAGE_REF_RE.pattern == r"@image(\d+)"
    assert core._image_refs("a @image1 b @image12 @image0 @imagex") == [1, 12, 0]


# =============================================================================
# the Lightbox edit bar's request is the site's Smart Reference submit (2026-10-03)
# =============================================================================

def bar_payload(**kw):
    """What the Lightbox edit bar's buildPayload sends for a 1280 x 768 source (pinned on the JS side
    by loom/test/tsubaki-core.test.js, 'a 1280 x 768 source: these keys, these values')."""
    p = {"version_id": T3, "model_id": "", "prompt": "make it night", "negative": "",
         "width": 1280, "height": 768, "mode": "pro", "steps": 25, "cfg": None, "count": 1,
         "seed": None, "high_priority": False, "prompt_helper": True, "creativity": "medium",
         "ref_media_id": None, "ref_strength": None, "upscale": None, "upscale_denoise": None,
         "upscale_denoise_steps": None, "face_fix": False, "quality_tag": None, "loras": [],
         "context_images": ["701"], "image_refs": []}
    p.update(kw)
    return p


def test_the_edit_bar_request_is_the_sites_smart_reference_shape(rest):
    """PixAI's own site, captured live on 2026-10-03, sends a Smart Reference edit as
    {extra: {naturalPrompts}, priority, width, height, prompts, modelId, seed, inferenceProfile,
    controlNets: [], contextImages, promptHelper: {forcePromptHelperDetectionSide, creativity}}:
    the source's own size, an empty controlNets, and no batchSize for one picture. The bar's request
    now has exactly those keys (seed is left out when none is set, as before), and the quote prices
    the very same dict."""
    req = road(bar_payload())
    assert req.parameters == {
        "extra": {"naturalPrompts": "make it night"}, "priority": core.PRIORITY_TURBO,
        "width": 1280, "height": 768, "prompts": "make it night", "modelId": T3,
        "inferenceProfile": "pro", "controlNets": [], "contextImages": ["701"],
        "promptHelper": {"forcePromptHelperDetectionSide": "server", "creativity": "medium"}}
    rest.priced.clear()
    core.price_task(object(), req.parameters)
    assert rest.priced and all("batchSize" not in q for q in rest.priced)
    assert rest.priced[-1]["width"] in (1280, "1280") and rest.priced[-1]["height"] in (768, "768")


def test_a_run_of_several_still_says_how_many(rest):
    """batchSize is left out only at one -- the site's own shape; a count above one (the dock's
    confirm road) still says how many."""
    assert road(bar_payload(count=2)).parameters["batchSize"] == 2


# =============================================================================
# the Lightbox edit bar runs at High Priority (the owner's call, 2026-10-03)
# =============================================================================

def test_the_edit_bar_is_sent_at_high_priority_and_quoted_at_it(rest, monkeypatch):
    """PixAI's free Turbo lane was not starting context-image edits; the site edits that worked ran at
    High Priority. The bar's payload asks for it (genCore.tsubakiEditState), so its request carries
    priority 1000 -- and the quote prices and card-checks that very dict, so the cost line shows what
    is spent: free when a card covers it, the quoted credits when none does."""
    req = road(bar_payload(high_priority=True))
    assert req.parameters["priority"] == core.PRIORITY_HIGH == 1000
    assert not req.unlimited and not core.asks_unlimited(bar_payload(high_priority=True))
    # no card: the quoted credits, priced on the dict that carries priority 1000
    matched = []
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: matched.append(params))
    rest.priced.clear()
    out = core.price(object(), req)
    assert out["free"] is False and out["cost"] == 4000 + 900
    assert str(rest.priced[0]["priority"]) == "1000"
    assert matched == [req.parameters] and matched[0]["priority"] == 1000
    # a card that covers it: free, checked against the same dict
    seen = []
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: seen.append(params) or {
        "total": 2, "consumeAmount": 1, "covered": True, "name": "card"})
    out = core.price(object(), req)
    assert out["free"] is True and seen[0]["priority"] == 1000


def test_nothing_else_changes_priority():
    """Only the bar asks: the web payload without high_priority (the dock's default, the Loom's
    unticked box) is still Turbo, and with it ticked is still High."""
    assert core._gen_args_from_web_payload({"prompt": "p"}).priority == core.PRIORITY_TURBO
    assert core._gen_args_from_web_payload({"prompt": "p", "high_priority": False}).priority == core.PRIORITY_TURBO
    assert core._gen_args_from_web_payload({"prompt": "p", "high_priority": True}).priority == core.PRIORITY_HIGH


def test_the_price_query_of_a_context_image_request_carries_control_nets(rest):
    """The /v2/task-price query for the bar's request carries `controlNets` as the JSON string "[]"
    beside its contextImages. A live read-only check (2026-10-03 review) found the quote identical
    with and without it (3,900), and +1,000 at priority 1000 -- so the empty list is safe to quote,
    and this pins the shape."""
    req = road(bar_payload())
    q = core._task_price_query(object(), req.parameters)
    assert q["controlNets"] == "[]"
    assert json.loads(q["contextImages"]) == ["701"]
    assert "batchSize" not in q

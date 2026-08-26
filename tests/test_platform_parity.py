"""Model-type-conditional image submit + price gate (PixAI new-gen platform, 2026-08-25).

The centerpiece is `_gate_params_for_model`: it gates a plain-image createGenerationTask's
field set on the model's ARCHITECTURE and MUST be applied IDENTICALLY to the submitted shape
and the priced shape, or the cost badge quotes a price the wallet doesn't pay.

The architecture signal is the VERSION-keyed inference-profile set, read via `_model_profiles`
from GET /v2/generation-model/<versionId>/inference-profiles -- body `{"profiles": [...]}`.
That endpoint is the ONLY one that answers on a submit's `modelId` (a VERSION id); the
model-keyed /versions route 404s on it, which is why an earlier resolve_version_meta-based
gate was inert in production (adversarial review + live GETs, 2026-08-26). These tests pin the
REAL `{"profiles": [...]}` shape and the real parse. All network is mocked at `_rest_get` /
`gql_mutate` -- no live calls, no optional-dep imports (CI curated-deps rule)."""
import pytest

import moonglade_backup as core


def _dit_profiles(default="lite"):
    """A DiT model's inference-profile rows; the `default` one carries profileFlag=='default'.
    Mirrors the live body: `{"profiles": [{profileName, profileFlag}, ...]}` (this returns just
    the list, which is what _model_profiles hands back)."""
    return [{"profileName": name, "profileFlag": ("default" if name == default else None)}
            for name in ("lite", "standard", "pro", "ultra")]


# --- (a) DiT (non-empty profiles): profile present, no steps/cfg ---------------

def test_gate_dit_auto_fills_the_flagged_default_and_drops_steps_cfg(monkeypatch):
    # default row is "pro" (a DiT.3-like model) -> proves the gate READS the model's default,
    # it does not synthesize "lite".
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: _dit_profiles(default="pro"))
    params = {"modelId": "DIT1", "prompts": "a cat", "samplingSteps": 28, "cfgScale": 5,
              "samplingMethod": "Euler a", "clipSkip": 2, "width": 768, "height": 1280}
    gated = core._gate_params_for_model(object(), params)
    assert gated["inferenceProfile"] == "pro"          # the model's REAL flagged default
    for k in ("samplingSteps", "cfgScale", "samplingMethod", "clipSkip"):
        assert k not in gated
    # non-mutating: the caller's original dict is untouched
    assert params["samplingSteps"] == 28 and "inferenceProfile" not in params


def test_gate_dit_auto_with_no_default_row_leaves_profile_absent(monkeypatch):
    # No row flagged default -> DO NOT synthesize one. Omitting inferenceProfile defers to the
    # server's own default, which keeps quote == charge (review finding 3).
    rows = [{"profileName": "lite", "profileFlag": None},
            {"profileName": "pro", "profileFlag": None}]
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: rows)
    params = {"modelId": "DIT1", "samplingSteps": 28, "cfgScale": 5}
    gated = core._gate_params_for_model(object(), params)
    assert "inferenceProfile" not in gated             # absent -> server picks its default
    assert "samplingSteps" not in gated and "cfgScale" not in gated


def test_gate_dit_keeps_an_explicitly_chosen_profile(monkeypatch):
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: _dit_profiles(default="lite"))
    params = {"modelId": "DIT1", "inferenceProfile": "ultra", "samplingSteps": 28, "cfgScale": 5}
    gated = core._gate_params_for_model(object(), params)
    assert gated["inferenceProfile"] == "ultra"        # user's choice preserved
    assert "samplingSteps" not in gated and "cfgScale" not in gated


# --- (b) SDXL (profiles == [], a definitive 200): steps/cfg kept, no profile ---

def test_gate_sdxl_empty_profiles_keeps_steps_cfg_and_strips_profile(monkeypatch):
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: [])
    params = {"modelId": "SDXL1", "inferenceProfile": "ultra", "samplingSteps": 28, "cfgScale": 5}
    gated = core._gate_params_for_model(object(), params)
    assert gated["samplingSteps"] == 28 and gated["cfgScale"] == 5
    # SDXL rejects pro/ultra -- the non-auto profile is stripped before it can be rejected
    assert "inferenceProfile" not in gated


# --- (c) THE KEY ONE: price path and submit path gate IDENTICALLY (quote==charge)

def test_price_and_submit_apply_identical_gating(monkeypatch):
    """The badge must price the exact shape the submit sends. Both call the SAME gate, which
    hits the REAL _model_profiles parse of `{"profiles": [...]}`. For a DiT model the priced
    query and the submitted params agree: the model's real default profile present, the
    steps/cfg/method the server ignores gone from BOTH. The default row here is "pro" (not
    "lite"), so this also proves the gate reads the model's true default."""
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "priority_for_submit", lambda p: p)

    priced = {}

    def fake_rest_get(session, path, params=None, **k):
        if path.endswith("/inference-profiles"):
            return {"profiles": [{"profileName": "lite", "profileFlag": None},
                                 {"profileName": "pro", "profileFlag": "default"},
                                 {"profileName": "ultra", "profileFlag": "membershipOnly"}]}
        if path == "/task-price":
            priced.update(params or {})
            return {"actualPrice": 4200}
        raise core.PixAIError("unexpected GET " + path)
    monkeypatch.setattr(core, "_rest_get", fake_rest_get)

    submitted = {}
    monkeypatch.setattr(core, "gql_mutate",
                        lambda s, q, v=None: (submitted.update(v["parameters"]),
                                              {"createGenerationTask": {"id": "T1"}})[1])

    base = {"modelId": "DIT3VER", "prompts": "a cat", "samplingSteps": 28, "cfgScale": 5,
            "samplingMethod": "Euler a", "width": 768, "height": 1280, "priority": 1000}
    assert core.submit_generation(object(), dict(base)) == "T1"
    core.price_task(object(), dict(base))

    # DiT-auto now carries the model's REAL default profile ("pro"), on BOTH paths
    assert submitted.get("inferenceProfile") == "pro"
    assert priced.get("inferenceProfile") == "pro"
    # the server-ignored fields are gone from BOTH the submit and the /task-price query
    for shape in (submitted, priced):
        assert "samplingSteps" not in shape and "samplingMethod" not in shape
    assert "cfgScale" not in submitted     # cfgScale isn't a priced scalar; assert it on submit


def test_gate_is_deterministic_for_the_same_inputs(monkeypatch):
    """Same params + same profile set -> byte-identical gated shape, whichever path calls it."""
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: _dit_profiles(default="standard"))
    base = {"modelId": "DIT1", "prompts": "x", "samplingSteps": 20, "cfgScale": 6}
    a = core._gate_params_for_model(object(), dict(base))
    b = core._gate_params_for_model(object(), dict(base))
    assert a == b and a["inferenceProfile"] == "standard"


# --- (d) fail-soft: an undetermined profile set never breaks / changes a submit -

def test_gate_fail_soft_when_profiles_unknown(monkeypatch):
    # _model_profiles returns None on any lookup failure -> gate must leave params UNCHANGED.
    monkeypatch.setattr(core, "_model_profiles", lambda s, vid: None)
    params = {"modelId": "M", "inferenceProfile": "ultra", "samplingSteps": 28, "cfgScale": 5}
    gated = core._gate_params_for_model(object(), params)
    assert gated is params                             # unchanged, SAME object
    assert gated["samplingSteps"] == 28 and gated["inferenceProfile"] == "ultra"


def test_gate_fail_soft_when_lookup_raises(monkeypatch):
    def boom(s, vid):
        raise core.PixAIError("profiles blew up")
    monkeypatch.setattr(core, "_model_profiles", boom)
    params = {"modelId": "M", "inferenceProfile": "ultra", "samplingSteps": 28}
    assert core._gate_params_for_model(object(), params) is params


def test_gate_noop_without_a_model_id():
    params = {"prompts": "x", "samplingSteps": 28}
    assert core._gate_params_for_model(object(), params) is params


def test_gate_leaves_a_video_submit_untouched(monkeypatch):
    """Video/edit/enhance also flow through submit_generation. A video submit carries a
    TOP-LEVEL modelId (a video model), so the gate must skip it -- never look up profiles for
    it, never add an image inferenceProfile to it."""
    monkeypatch.setattr(core, "_model_profiles",
                        lambda s, vid: pytest.fail("gate must not look up profiles for video"))
    vparams = core.build_video_parameters("motion", media_id="1", mode="professional")
    assert core._gate_params_for_model(object(), vparams) is vparams


# --- _model_profiles: reads the `profiles` key, [] for SDXL, None on failure, memoized ---

def test_model_profiles_reads_the_profiles_key(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: {"profiles": [
        {"profileName": "lite", "profileFlag": "default"},
        {"profileName": "pro", "profileFlag": None}]})
    prof = core._model_profiles(object(), "V1")
    assert [r["profileName"] for r in prof] == ["lite", "pro"]


def test_model_profiles_sdxl_returns_empty_list(monkeypatch):
    # SDXL answers 200 with an empty profiles array -- a DEFINITIVE "no profiles", not a miss.
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: {"profiles": []})
    assert core._model_profiles(object(), "SDXL") == []


def test_model_profiles_none_on_failure(monkeypatch):
    def boom(s, path, **k):
        raise core.PixAIError("404 -- version-keyed /versions would 404 here too")
    monkeypatch.setattr(core, "_rest_get", boom)
    assert core._model_profiles(object(), "V1") is None
    # a 200 whose body is not a dict-with-a-profiles-list is also "couldn't determine" -> None
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: {"unexpected": True})
    assert core._model_profiles(object(), "V2") is None


def test_model_profiles_memoizes_per_session_and_version(monkeypatch):
    n = {"gets": 0}

    def fake_rest_get(session, path, params=None, **k):
        n["gets"] += 1
        return {"profiles": [{"profileName": "lite", "profileFlag": "default"}]}
    monkeypatch.setattr(core, "_rest_get", fake_rest_get)
    s = object()
    a = core._model_profiles(s, "V1")
    b = core._model_profiles(s, "V1")
    assert a == b and n["gets"] == 1                   # second call served from the memo

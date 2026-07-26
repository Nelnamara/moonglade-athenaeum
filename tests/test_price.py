"""Credit-cost estimation via GET /v2/task-price (read-only -- computes cost without
creating a task). Mocked _rest_get; conftest blocks live /v2. No network, no spend."""
import json

import moonglade_backup as core


def test_price_scalars_and_nested_split(monkeypatch):
    seen = {}
    def fake_get(s, path, params=None, **k):
        seen["path"] = path
        seen["params"] = params
        return {"originalPrice": 2600, "actualPrice": 2600, "type": "prepaid"}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    p = core.price_task(object(), {
        "modelId": "123", "width": 512, "priority": 500,
        "prompts": "skip me", "cfgScale": 7, "seed": 9,       # not priced -> dropped
        "i2vPro": {"model": "v4.0.1", "duration": "5"},        # nested -> JSON string
    })
    assert p == 2600
    assert seen["path"] == "/task-price"
    q = seen["params"]
    assert q["modelId"] == "123" and q["width"] == 512 and q["priority"] == 500
    assert "prompts" not in q and "cfgScale" not in q and "seed" not in q
    assert q["i2vPro"] == json.dumps({"model": "v4.0.1", "duration": "5"})


def test_price_returns_actual_not_original(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: {"originalPrice": 5000, "actualPrice": 3000})
    assert core.price_task(object(), {"modelId": "x"}) == 3000


def test_price_fails_soft(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("400")))
    assert core.price_task(object(), {"modelId": "x"}) is None


def test_price_empty_params_returns_none():
    assert core.price_task(object(), {}) is None


def test_price_no_priceable_fields_skips_call(monkeypatch):
    # only non-priced fields => empty query => None WITHOUT hitting the endpoint
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    assert core.price_task(object(), {"prompts": "x", "seed": 1}) is None


def test_price_missing_actualprice_returns_none(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: {"type": "prepaid"})
    assert core.price_task(object(), {"modelId": "x"}) is None


# ---- GET /v2/task/wait-time: PixAI's own queue-wait estimate (also read-only) ----
# The parameter shape was probed live rather than guessed -- see queue_wait_estimate's
# docstring for the exact 400/404 sequence that pinned it down.

def test_wait_time_asks_for_priority_and_modelVersionId(monkeypatch):
    """The two parameters the route validates. `modelVersionId`, NOT `generationModelId`:
    the id our submits carry as `modelId` 404s "Generation model not found" under the
    latter and answers 200 under the former."""
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen["path"], seen["params"] = path, params
        return {"waitDurationSeconds": 25.42, "displayBucket": "seconds",
                "displaySeconds": 25, "displayMinutes": None}

    monkeypatch.setattr(core, "_rest_get", fake_get)
    assert core.queue_wait_estimate(object(), 500, "1983308862240288769") == 25
    assert seen["path"] == "/task/wait-time"
    assert seen["params"] == {"priority": 500, "modelVersionId": "1983308862240288769"}


def test_wait_time_rounds_the_float_pixai_returns(monkeypatch):
    """waitDurationSeconds is fractional (26.7 measured). Rounded, not truncated."""
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: {"waitDurationSeconds": 26.7})
    assert core.queue_wait_estimate(object(), 500, "x") == 27


def test_wait_time_without_a_model_skips_the_call(monkeypatch):
    """The route 400s outright without a model id ("modelVersionId or generationModelId
    must be provided"), so there is nothing to gain by asking."""
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    assert core.queue_wait_estimate(object(), 500, "") is None
    assert core.queue_wait_estimate(object(), 500, None) is None


def test_wait_time_defaults_a_missing_priority_to_the_normal_tier(monkeypatch):
    """`priority` is a validated enum, not a free number (1 is rejected as "invalid
    priority"), so a task whose stored parameters lack one still has to be asked about at
    a real tier -- 500 is this app's own submit default."""
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen.update(params or {})
        return {"waitDurationSeconds": 30}

    monkeypatch.setattr(core, "_rest_get", fake_get)
    assert core.queue_wait_estimate(object(), None, "x") == 30
    assert seen["priority"] == 500


def test_wait_time_fails_soft(monkeypatch):
    """An estimate is a nicety. A 400/429/blip must return None, never propagate -- the
    caller is a status poll whose real job is reporting the task's phase."""
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("400")))
    assert core.queue_wait_estimate(object(), 500, "x") is None


def test_wait_time_missing_or_unusable_number_returns_none(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: {"displayBucket": "seconds"})
    assert core.queue_wait_estimate(object(), 500, "x") is None
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: {"waitDurationSeconds": "soon"})
    assert core.queue_wait_estimate(object(), 500, "x") is None

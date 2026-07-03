"""Credit-cost estimation via GET /v2/task-price (read-only -- computes cost without
creating a task). Mocked _rest_get; conftest blocks live /v2. No network, no spend."""
import json

import pixai_gallery_backup as core


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

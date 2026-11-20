"""Edit Pro's new outputs, engine and API only (DESIGN_3.22 section 5, step S5).

The request (5.1): build_chat_edit_parameters' keyword arguments written into chat.modelConfig
with exactly the allowed values and gates, the capability lists from the live /versions record
with the baked EDIT_MODELS fallback, a refusal (never a clamp) for anything outside the rules,
the new keys in the price identity, and the wire schema naming exactly these keys. Prices are
P3's (PROBE_2026-11-18_site's `chatPriceList` row for Edit Pro V2.0) as quote fixtures. Nothing
here touches the network.
"""
import json
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import gen_cli
from moonglade import gen_params
from moonglade import gen_road
from moonglade import models as models_mod
from moonglade import pixai_client as pc
from moonglade import pricing
from moonglade import runs

from tests.conftest import _REAL_CREATE

V1 = gen_params.EDIT_PRO_MODEL_ID                       # Edit Pro v1.0
V2 = gen_params.edit_model_id("edit-pro-v2")            # Edit Pro V2.0
REF = gen_params.edit_model_id("reference-pro")
EDIT_PRO_BASE = "2006468692900798466"


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)


def _mc(model_id=V2, **kw):
    return gen_params.build_chat_edit_parameters("make it night", ["111"], model_id,
                                                 **kw)["chat"]["modelConfig"]


# ---------------------------------------------------------------------------
# 5.1: each argument writes exactly its key, and only when set
# ---------------------------------------------------------------------------

def test_nothing_new_is_sent_by_default_and_png_is_sent_as_nothing():
    plain = _mc()
    assert set(plain) == {"resolution", "aspectRatio", "quality"}
    assert _mc(output_format="png") == plain
    assert _mc(output_format="") == plain


@pytest.mark.parametrize("kw, want", [
    (dict(output_format="svg"), {"outputFormat": "svg"}),
    (dict(output_format="gif"), {"outputFormat": "gif"}),
    (dict(output_format="gif", frame_count=2, frame_duration_ms=20),
     {"outputFormat": "gif", "frameCount": 2, "frameDurationMs": 20}),
    (dict(output_format="gif", frame_count=16, frame_duration_ms=2000),
     {"outputFormat": "gif", "frameCount": 16, "frameDurationMs": 2000}),
    (dict(transparent=True), {"background": "transparent"}),
    (dict(transparent=True, output_format="png"), {"background": "transparent"}),
    (dict(transparent=True, auto_tone=False),
     {"background": "transparent", "colorTone": "original"}),
])
def test_each_argument_writes_its_wire_key(kw, want):
    mc = _mc(**kw)
    assert {k: v for k, v in mc.items() if k not in ("resolution", "aspectRatio",
                                                      "quality")} == want


def test_transparent_rides_edit_pro_v1_too():
    assert _mc(V1, transparent=True)["background"] == "transparent"


@pytest.mark.parametrize("model, kw, words", [
    (V2, dict(output_format="webp"), "PNG, SVG or GIF"),
    (V2, dict(output_format="SVG"), "PNG, SVG or GIF"),
    (V1, dict(output_format="svg"), "can't make SVG"),
    (V1, dict(output_format="gif"), "can't make GIF"),
    (REF, dict(output_format="gif"), "can't make GIF"),
    ("999", dict(output_format="svg"), "can't make SVG"),             # off the table
    (V2, dict(frame_count=9), "goes only with a GIF"),
    (V2, dict(output_format="svg", frame_duration_ms=200), "goes only with a GIF"),
    (V2, dict(output_format="gif", frame_count=1), "2 to 16"),
    (V2, dict(output_format="gif", frame_count=17), "2 to 16"),
    (V2, dict(output_format="gif", frame_count=9.0), "2 to 16"),
    (V2, dict(output_format="gif", frame_count=True), "2 to 16"),
    (V2, dict(output_format="gif", frame_count="9"), "2 to 16"),
    (V2, dict(output_format="gif", frame_duration_ms=19), "20 to 2000"),
    (V2, dict(output_format="gif", frame_duration_ms=2001), "20 to 2000"),
    (REF, dict(transparent=True), "see-through"),
    (V2, dict(transparent=True, output_format="svg"), "only with a PNG"),
    (V2, dict(transparent=True, output_format="gif"), "only with a PNG"),
    (V2, dict(auto_tone=False), "Auto tone goes only"),
    (V2, dict(transparent="yes"), "on or off"),
])
def test_a_combination_outside_the_rules_is_refused_never_clamped(model, kw, words):
    with pytest.raises(core.LocalRefusal, match=words) as ei:
        _mc(model, **kw)
    assert "nothing was sent" in str(ei.value)


# ---------------------------------------------------------------------------
# 5.1: the capability lists -- the live record wins, the baked table is the fallback
# ---------------------------------------------------------------------------

def test_the_baked_lists_match_the_probe():
    caps = {k: gen_params.edit_output_caps(gen_params.edit_model_id(k))
            for k in gen_params.EDIT_MODELS}
    assert caps["edit-pro-v2"] == {"output_formats": ["png", "svg", "gif"],
                                   "backgrounds": ["transparent"]}
    assert caps["edit-pro"] == {"output_formats": [], "backgrounds": ["transparent"]}
    assert caps["reference-pro"] == caps["edit-v4"] == {"output_formats": [], "backgrounds": []}
    assert gen_params.edit_output_caps("999") == {"output_formats": [], "backgrounds": []}


def test_the_live_record_wins_over_the_baked_table():
    none_listed = {"output_formats": [], "backgrounds": []}
    with pytest.raises(core.LocalRefusal, match="can't make SVG"):
        _mc(V2, output_format="svg", caps=none_listed)
    with pytest.raises(core.LocalRefusal, match="see-through"):
        _mc(V2, transparent=True, caps=none_listed)
    assert _mc(V1, output_format="gif", caps={"output_formats": ["gif"]})["outputFormat"] == "gif"


def _versions_rows(chat_editing_v2, chat_editing_v1=None):
    return [{"id": V2, "extra": {"chatEditing": chat_editing_v2}},
            {"id": V1, "extra": {"chatEditing": chat_editing_v1 or {}}}]


def test_the_live_read_takes_the_lists_off_the_versions_record(monkeypatch):
    calls = []

    def _get(session, path, **kw):
        calls.append(path)
        return {"data": _versions_rows(
            {"maxInputImageCount": 10, "supportedOutputFormatOptions": ["png", "svg", "gif"],
             "supportedBackgroundOptions": ["transparent"]},
            {"supportedBackgroundOptions": ["transparent"]})}
    monkeypatch.setattr(core, "_rest_get", _get)
    assert models_mod.edit_output_caps_live(object(), V2) == {
        "output_formats": ["png", "svg", "gif"], "backgrounds": ["transparent"]}
    assert models_mod.edit_output_caps_live(object(), V1) == {
        "output_formats": [], "backgrounds": ["transparent"]}
    assert calls == ["/generation-model/" + EDIT_PRO_BASE + "/versions"] * 2
    models_mod.edit_output_caps_live(object(), V2)                 # cached
    assert len(calls) == 2


@pytest.mark.parametrize("answer", [
    RuntimeError("down"), {"data": []}, {"data": [{"id": V2, "extra": {}}]},
    {"data": [{"id": V2, "extra": {"chatEditing": "x"}}]}, "not json",
])
def test_an_unreadable_record_is_none_and_the_baked_table_answers(monkeypatch, answer):
    def _get(session, path, **kw):
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(core, "_rest_get", _get)
    assert models_mod.edit_output_caps_live(object(), V2) is None
    assert _mc(V2, output_format="svg", caps=None)["outputFormat"] == "svg"


def test_a_model_the_table_does_not_know_is_never_read(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: pytest.fail("read an unknown model"))
    assert models_mod.edit_output_caps_live(object(), "999") is None


# ---------------------------------------------------------------------------
# The web road: the payload keys, the resolver, one rule for the quote and the spend
# ---------------------------------------------------------------------------

def _edit_req(resolve=None, **payload):
    p = dict({"source": "111", "edit_model": "edit-pro-v2", "instruction": "night"}, **payload)
    return gen_road.build_request(p, mode="edit", resolve=resolve)


def test_the_edit_payload_reaches_the_builder():
    req = _edit_req(output_format="gif", frame_count="12", frame_duration_ms=170)
    mc = req.parameters["chat"]["modelConfig"]
    assert (mc["outputFormat"], mc["frameCount"], mc["frameDurationMs"]) == ("gif", 12, 170)
    req = _edit_req(transparent=True, auto_tone="0")
    mc = req.parameters["chat"]["modelConfig"]
    assert (mc["background"], mc["colorTone"]) == ("transparent", "original")
    assert "outputFormat" not in _edit_req(output_format="png").parameters["chat"]["modelConfig"]


@pytest.mark.parametrize("payload", [
    dict(frame_count="nine", output_format="gif"), dict(frame_count=8.5, output_format="gif"),
    dict(output_format="gif", frame_count=40), dict(transparent="maybe"),
    dict(output_format="svg", edit_model="edit-pro"),
])
def test_a_bad_payload_is_refused_at_build(payload):
    with pytest.raises(core.LocalRefusal):
        _edit_req(**payload)


def test_the_resolvers_live_lists_are_what_the_build_reads():
    asked = []

    def _caps(model_id):
        asked.append(model_id)
        return {"output_formats": [], "backgrounds": []}
    rs = gen_road.RequestResolver(edit_caps=_caps)
    with pytest.raises(core.LocalRefusal, match="can't make SVG"):
        _edit_req(rs, output_format="svg")
    assert asked == [V2]


def test_the_gallery_quote_and_spend_carry_the_same_capability_read(monkeypatch, tmp_path):
    """/api/price and /api/edit both read the model's live lists, and both refuse what they
    say no to: the badge never quotes an output the send would refuse."""
    from moonglade import cards as cards_mod
    from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client
    save_catalog(tmp_path / "catalog.db", [dict({f: "" for f in CATALOG_FIELDS},
                                                media_id="55", filename="a_55.png")])
    asked, seen = [], {}

    def _resolver(session):
        def _caps(model_id):
            asked.append(model_id)
            return {"output_formats": ["png", "gif"], "backgrounds": []}
        return _caps
    monkeypatch.setattr(models_mod, "edit_caps_resolver", _resolver)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(pricing, "price_task", lambda s, params: seen.update(priced=params) or 14000)
    monkeypatch.setattr(cards_mod, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(gen_road, "submit",
                        lambda s, req, **k: seen.update(sent=req.parameters) or {"task_id": "t1"})
    cli = login_test_client(create_app(tmp_path))
    body = {"mode": "edit", "edit_model": "edit-pro-v2", "source": "55", "instruction": "night",
            "output_format": "gif", "frame_count": 4}
    cli.post("/api/price", json=body)
    assert cli.post("/api/edit", json=body).get_json().get("task_id") == "t1"
    assert seen["priced"]["chat"] == seen["sent"]["chat"]
    assert seen["sent"]["chat"]["modelConfig"]["frameCount"] == 4
    assert asked == [V2, V2]
    seen.clear()
    svg = dict(body, output_format="svg", frame_count=None)       # live record: no SVG
    priced = cli.post("/api/price", json=svg).get_json()
    assert priced.get("cost") is None and "can't make SVG" in str(priced)
    cli.post("/api/edit", json=svg)
    assert "sent" not in seen and "priced" not in seen


# ---------------------------------------------------------------------------
# The wire schema names exactly these keys under chat.modelConfig
# ---------------------------------------------------------------------------

def test_the_wire_schema_lists_exactly_the_built_keys():
    mc = gen_params.WIRE_SCHEMA["edit"]["parameters"]["chat"]["modelConfig"]
    assert set(mc) == {"resolution", "aspectRatio", "quality", "outputFormat", "frameCount",
                       "frameDurationMs", "background", "colorTone"}


class _Answer:
    status_code, headers = 200, {}
    text = '{"id": "T1"}'
    ok = True

    def json(self):
        return {"id": "T1"}


class _Wire:
    def __init__(self):
        self.posts, self.headers = [], {}

    def post(self, url, **kw):
        self.posts.append(json.loads(kw["data"].decode("utf-8")))
        return _Answer()


@pytest.mark.parametrize("key, value", [
    ("outputFormatt", "svg"), ("layerDecomposition", True), ("frame_count", 9),
    ("backgroundColor", "transparent"),
])
def test_a_misspelt_or_unbuilt_model_config_key_is_refused_never_dropped(key, value):
    params = gen_params.build_chat_edit_parameters("x", ["111"], V2)
    params["chat"]["modelConfig"][key] = value
    wire = _Wire()
    with pytest.raises(core.LocalRefusal, match="chat.modelConfig." + key):
        pc.PixAIClient(wire).create("edit", params)
    assert wire.posts == []


def test_every_new_key_goes_out_on_the_final_body(monkeypatch):
    monkeypatch.setattr(core, "_create", _REAL_CREATE)
    wire = _Wire()
    params = gen_params.build_chat_edit_parameters(
        "x", ["111"], V2, output_format="gif", frame_count=9, frame_duration_ms=200)
    pc.PixAIClient(wire).create("edit", params)
    gif = wire.posts[0]["parameters"]["chat"]["modelConfig"]
    params = gen_params.build_chat_edit_parameters("x", ["111"], V2, transparent=True,
                                                   auto_tone=False)
    pc.PixAIClient(wire).create("edit", params)
    clear = wire.posts[1]["parameters"]["chat"]["modelConfig"]
    assert (gif["outputFormat"], gif["frameCount"], gif["frameDurationMs"]) == ("gif", 9, 200)
    assert (clear["background"], clear["colorTone"]) == ("transparent", "original")


def test_kaisuuken_extra_credits_is_never_built_and_never_sent():
    params = gen_params.build_chat_edit_parameters("x", ["111"], V2, output_format="gif",
                                                   kaisuuken_id="K1")
    assert "kaisuukenExtraCredits" not in json.dumps(params)
    params["kaisuukenExtraCredits"] = 3000
    wire = _Wire()
    with pytest.raises(core.LocalRefusal, match="extra credits"):
        pc.PixAIClient(wire).create("edit", params)
    assert wire.posts == []


# ---------------------------------------------------------------------------
# 5.2: the price identity -- P3's prices, read off the very keys that are sent
# ---------------------------------------------------------------------------

def _p3_price(q):
    """PixAI's /v2/task-price for Edit Pro V2.0 as P3 measured it (the chatPriceList row
    2061589941358465024, axes outputFormat x quality x resolution x frameCount)."""
    mc = json.loads(q["chat"])["modelConfig"]
    fmt, quality = mc.get("outputFormat", "png"), mc.get("quality", "medium")
    if fmt == "svg":
        return {"low": 11000, "medium": 13500, "high": 18000}[quality]
    if fmt == "gif":
        frames = mc.get("frameCount", 9)
        bucket = "2-8" if frames <= 8 else "9-16"
        return {("2-8", "low"): 7000, ("2-8", "medium"): 11500, ("2-8", "high"): 14500,
                ("9-16", "low"): 8500, ("9-16", "medium"): 14000,
                ("9-16", "high"): 18000}[(bucket, quality)]
    return {("low", "1K"): 4500, ("medium", "1K"): 8000, ("high", "1K"): 18000}[
        (quality, mc.get("resolution", "1K"))]


@pytest.fixture
def task_price(monkeypatch):
    seen = []

    def _get(session, path, params=None, **kw):
        assert path == "/task-price"
        seen.append(params)
        return {"actualPrice": _p3_price(params)}
    monkeypatch.setattr(core, "_rest_get", _get)
    return seen


@pytest.mark.parametrize("kw, want", [
    ({}, 8000),
    (dict(transparent=True), 8000),
    (dict(transparent=True, auto_tone=False), 8000),
    (dict(output_format="svg", quality="low"), 11000),
    (dict(output_format="svg"), 13500),
    (dict(output_format="svg", quality="high"), 18000),
    (dict(output_format="gif", frame_count=2), 11500),
    (dict(output_format="gif", frame_count=9), 14000),
    (dict(output_format="gif", frame_count=16), 14000),
])
def test_the_quote_prices_the_new_keys_as_p3_did(task_price, kw, want):
    params = gen_params.build_chat_edit_parameters("x", ["111"], V2, **kw)
    assert pricing.price_task(object(), params) == want
    sent = json.loads(task_price[-1]["chat"])["modelConfig"]
    assert sent == params["chat"]["modelConfig"]


def test_the_new_keys_are_in_the_price_identity():
    assert "chat" in pricing._PRICE_NESTED
    nine = gen_params.build_chat_edit_parameters("x", ["111"], V2, output_format="gif",
                                                 frame_count=9)
    two = gen_params.build_chat_edit_parameters("x", ["111"], V2, output_format="gif",
                                                frame_count=2)
    q9, q2 = (pricing._task_price_query(object(), p) for p in (nine, two))
    assert json.loads(q9["chat"])["modelConfig"]["frameCount"] == 9
    assert q9 != q2
    assert runs.run_digest([(nine, False)], q9) != runs.run_digest([(two, False)], q2)


# ---------------------------------------------------------------------------
# A hand-written edit shape on the command line meets the same rules
# ---------------------------------------------------------------------------

def _cli_args(tmp_path, params, confirm):
    return SimpleNamespace(out=str(tmp_path), params_json=json.dumps(params), confirm=confirm,
                           task_id="", token=None, prompt="", edit_src=["111"], edit_model="",
                           edit_resolution="", edit_aspect="", edit_quality="",
                           kaisuuken_id="", no_card=True)


@pytest.mark.parametrize("confirm", [False, True])
def test_a_params_json_edit_outside_the_rules_is_refused_before_anything_moves(
        monkeypatch, tmp_path, confirm):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: pytest.fail("made a session"))
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: pytest.fail("uploaded"))
    shape = gen_params.build_chat_edit_parameters("x", ["111"], V1)
    shape["chat"]["modelConfig"]["outputFormat"] = "svg"            # v1.0 lists no SVG
    with pytest.raises(core.LocalRefusal, match="can't make SVG"):
        gen_cli.run_edit_image(_cli_args(tmp_path, shape, confirm))


def test_check_edit_outputs_reads_a_built_shape():
    ok = gen_params.build_chat_edit_parameters("x", ["111"], V2, output_format="gif",
                                               frame_count=4)
    assert gen_params.check_edit_outputs(ok) is None
    png = gen_params.build_chat_edit_parameters("x", ["111"], V1)
    png["chat"]["modelConfig"]["outputFormat"] = "png"
    assert gen_params.check_edit_outputs(png) is None
    for key, value in (("background", "opaque"), ("colorTone", "warm"),
                       ("frameCount", 4)):
        bad = gen_params.build_chat_edit_parameters("x", ["111"], V2)
        bad["chat"]["modelConfig"][key] = value
        with pytest.raises(core.LocalRefusal):
            gen_params.check_edit_outputs(bad)


# ---------------------------------------------------------------------------
# 5.2: cards are all or nothing (D2) -- "the card doesn't cover this", held as unclear
# ---------------------------------------------------------------------------

def _extra_credits_refusal():
    return core.PixAIRestError("REST POST /task/create -> 400", 400,
                               {"code": "KAISUUKEN_EXTRA_CREDITS_REQUIRED",
                                "message": "extra credits required"})


def test_extra_credits_required_reads_the_card_does_not_cover_this_and_holds():
    e = _extra_credits_refusal()
    assert "KAISUUKEN_EXTRA_CREDITS_REQUIRED" not in gen_road.DEFINITE_CODES
    assert gen_road.classify_outcome(e, "create") == "unknown"
    assert gen_road.send_outcome(e, True) == "may_have_started"
    assert "the free card doesn't cover this" in gen_road.outcome_reason(e)


def test_the_cli_says_the_card_does_not_cover_this_beside_may_have_started():
    def _send():
        raise _extra_credits_refusal()
    with pytest.raises(gen_road.SendOutcomeUnclear) as ei:
        gen_road._cli_send_once(_send)
    assert str(ei.value).startswith(gen_road.CLI_UNCLEAR)
    assert "the free card doesn't cover this" in str(ei.value)


class _RefusingAnswer(_Answer):
    status_code, ok = 400, False
    text = '{"code": "KAISUUKEN_EXTRA_CREDITS_REQUIRED"}'

    def json(self):
        return {"code": "KAISUUKEN_EXTRA_CREDITS_REQUIRED"}


class _RefusingWire(_Wire):
    def post(self, url, **kw):
        self.posts.append(json.loads(kw["data"].decode("utf-8")))
        return _RefusingAnswer()


def test_a_card_answered_with_extra_credits_required_is_never_resent(monkeypatch):
    """No send after an unknown outcome: one POST, the card never re-sent without itself, and
    never re-sent with kaisuukenExtraCredits."""
    from moonglade import cards as cards_mod
    monkeypatch.setattr(core, "_create", _REAL_CREATE)
    monkeypatch.setattr(models_mod, "_gate_params_for_model", lambda s, p: p)

    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
        return "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    wire = _RefusingWire()
    req = gen_road.GenerationRequest(mode="edit", parameters=gen_params.build_chat_edit_parameters(
        "x", ["111"], V2, output_format="gif", frame_count=9))
    with pytest.raises(core.PixAIRestError):
        gen_road.submit(pc.PixAIClient(wire), req)
    assert len(wire.posts) == 1
    assert wire.posts[0]["parameters"]["kaisuukenId"] == "K1"
    assert "kaisuukenExtraCredits" not in json.dumps(wire.posts)

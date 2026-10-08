"""The Generate drawer's colour palette on the server (Session H decision 4; the Library tab to
PixAI's own pattern). Lane w2-small, 2026-09-28; the design and its spend review are in
moonglade-internal/design/notes/small-calls/BUILD-w2-small.md.

  - GET /api/palettes/presets: PixAI's official palettes, one read, cached, covers through the
    app's own CDN proxy, fail-soft.
  - clean_color_palette: the web payload's color_palette -> the task's colorPalette, or a
    builder refusal for anything PixAI's schema would refuse (nothing is sent or charged).
  - the image road: colorPalette rides the built dict only when the model's /features lists
    colorPalette "on" and no context image is in play; the quote leaves it out (task-price has
    no such field); the gate strips it with a receipt otherwise.

Every PixAI read is faked at _rest_get; nothing leaves the machine."""
import re

import pytest

from moonglade import backup as core
from tests.conftest import login_client

T3 = "2024383379556065549"
SDXL = "V-SDXL"
FLASH_OFF = "V-NOPAL"                # an MMDIT26B version whose /features says colorPalette off

WISTERIA = {
    "id": "2035840489783758862", "name": "Wisteria Whisper",
    "palette": {
        "overall": {"colors": [{"hex": "#B0C7E8", "ratio": 30}, {"hex": "#DCF0F9", "ratio": 20},
                               {"hex": "#5564A5", "ratio": 15}, {"hex": "#DAD1D8", "ratio": 15},
                               {"hex": "#4F70F1", "ratio": 10}, {"hex": "#E4B3C6", "ratio": 10}]},
        "background": {"colors": [{"hex": "#FEF9F7", "ratio": 60}, {"hex": "#ADC2DF", "ratio": 40}]},
    },
    "coverUrl": "https://images-ng.pixai.art/images/thumb/b0c6394e-2db4-43f0-adfd-738181eb3c6c",
    "createdAt": "2026-07-20T07:13:33.852Z", "updatedAt": "2026-08-18T09:17:22.987Z",
}
PALETTE = {"name": "My Rime", "palette": {
    "overall": {"colors": [{"hex": "#8a8fb8", "ratio": 40}, {"hex": "#5A5A9A", "ratio": 25},
                           {"hex": "#7AE8E8", "ratio": 20}, {"hex": "#E070B0", "ratio": 15}]},
    "background": {"colors": [{"hex": "#2A3A5A", "ratio": 60}, {"hex": "#9AB8D8", "ratio": 40}]}}}
SENT = {"name": "My Rime", "palette": {
    "overall": {"colors": [{"hex": "#8A8FB8", "ratio": 40}, {"hex": "#5A5A9A", "ratio": 25},
                           {"hex": "#7AE8E8", "ratio": 20}, {"hex": "#E070B0", "ratio": 15}]},
    "background": {"colors": [{"hex": "#2A3A5A", "ratio": 60}, {"hex": "#9AB8D8", "ratio": 40}]}}}


def _features(model_type, status):
    return {"modelType": model_type, "features": [
        {"featureName": k, "status": v} for k, v in status.items()]}


T3_STATUS = {"negativePrompt": "on", "contextImages": "on", "colorPalette": "on",
             "inferenceProfile": "on", "upscale": "off", "enableADetailer": "off"}
BODIES = {
    "/generation-model/%s/features" % T3: _features("MMDIT26B_MODEL", T3_STATUS),
    "/generation-model/%s/features" % FLASH_OFF: _features(
        "MMDIT26B_MODEL", dict(T3_STATUS, colorPalette="off")),
    "/generation-model/%s/features" % SDXL: _features("SDXL_MODEL", {}),
    "/generation-model/%s/inference-profiles" % T3: {"profiles": [
        {"profileName": "pro", "profileFlag": "default"}]},
    "/generation-model/%s/inference-profiles" % FLASH_OFF: {"profiles": [
        {"profileName": "pro", "profileFlag": "default"}]},
    "/generation-model/%s/inference-profiles" % SDXL: {"profiles": []},
    "/generation-model/%s/size-config" % T3: {"ranges": [
        {"minWidth": 512, "maxWidth": 2496, "minHeight": 512, "maxHeight": 2496}]},
    "/generation-model/%s/size-config" % FLASH_OFF: {"ranges": [
        {"minWidth": 512, "maxWidth": 2496, "minHeight": 512, "maxHeight": 2496}]},
    "/color-palettes/presets": {"palettes": [WISTERIA, {"id": "x", "name": "broken",
                                                        "palette": {"character": {"colors": [
                                                            {"hex": "#000000", "ratio": 100}]}},
                                                        "coverUrl": None}]},
}


class FakeRest:
    def __init__(self):
        self.calls, self.priced = [], []

    def __call__(self, session, path, params=None, **k):
        self.calls.append(path)
        if path == "/task-price":
            self.priced.append(dict(params or {}))
            return {"actualPrice": 5100}
        if path in BODIES:
            return BODIES[path]
        raise core.PixAIError("unexpected GET " + path)


@pytest.fixture
def rest(monkeypatch):
    fake = FakeRest()
    monkeypatch.setattr(core, "_rest_get", fake)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    return fake


# ---- the Library read ------------------------------------------------------------------

def test_presets_route_returns_the_clean_library_with_proxied_covers(tmp_path, rest):
    cli = login_client(tmp_path)
    d = cli.get("/api/palettes/presets").get_json()
    assert [p["name"] for p in d["palettes"]] == ["Wisteria Whisper"]   # character-only dropped
    p = d["palettes"][0]
    assert p["id"] == "2035840489783758862"
    assert p["cover_url"].startswith("/api/pixai-cdn/thumb?u=https%3A%2F%2Fimages-ng.pixai.art%2F")
    assert p["palette"]["background"]["colors"][0] == {"hex": "#FEF9F7", "ratio": 60}
    assert "character" not in p["palette"]
    # cached: a second open is not a second read
    cli.get("/api/palettes/presets")
    assert rest.calls.count("/color-palettes/presets") == 1


def test_presets_route_fails_soft_and_does_not_cache_a_failure(tmp_path, monkeypatch):
    calls = []

    def boom(session, path, params=None, **k):
        calls.append(path)
        raise core.PixAIError("503 upstream")
    monkeypatch.setattr(core, "_rest_get", boom)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = login_client(tmp_path)
    d = cli.get("/api/palettes/presets").get_json()
    assert d["palettes"] == [] and "503" in d["error"]
    cli.get("/api/palettes/presets")
    assert calls == ["/color-palettes/presets"] * 2


def test_a_cover_off_pixais_cdn_is_not_proxied(monkeypatch, tmp_path):
    body = {"palettes": [dict(WISTERIA, coverUrl="https://evil.example/x.png")]}
    monkeypatch.setattr(core, "_rest_get", lambda s, path, params=None, **k: body)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    d = login_client(tmp_path).get("/api/palettes/presets").get_json()
    assert d["palettes"][0]["cover_url"] == ""


# ---- the request cleaner ---------------------------------------------------------------

def test_clean_palette_upper_cases_and_keeps_only_the_groups_given():
    assert core.clean_color_palette(PALETTE) == SENT
    assert core.clean_color_palette(None) is None
    assert core.clean_color_palette({}) is None
    out = core.clean_color_palette({"name": "  ", "palette": {
        "background": {"colors": [{"hex": "#000000", "ratio": 99.6}]}}})
    assert out == {"name": core.PALETTE_NAME_DEFAULT,
                   "palette": {"background": {"colors": [{"hex": "#000000", "ratio": 100}]}}}
    assert len(core.clean_color_palette({"name": "x" * 90, "palette": SENT["palette"]})["name"]) == 50


@pytest.mark.parametrize("bad", [
    "not a dict",
    {"name": "x"},                                                         # no palette
    {"name": "x", "palette": {"character": {"colors": [{"hex": "#000000", "ratio": 100}]}}},
    {"name": "x", "palette": {"overall": {"colors": []}}},                 # 0 colours
    {"name": "x", "palette": {"overall": {"colors": [{"hex": "#000000", "ratio": 1}] * 13}}},
    {"name": "x", "palette": {"overall": {"colors": [{"hex": "red", "ratio": 100}]}}},
    {"name": "x", "palette": {"overall": {"colors": [{"hex": "#000000", "ratio": 101}]}}},
    {"name": "x", "palette": {"overall": {"colors": [{"hex": "#000000", "ratio": True}]}}},
    {"name": "x", "palette": {"overall": {"colors": [{"hex": "#000000", "ratio": "nan"}]}}},
    {"name": "x", "palette": {"overall": SENT["palette"]["overall"], "hair": {"colors": []}}},
])
def test_clean_palette_refuses_what_pixai_would(bad):
    with pytest.raises(core.PixAIError) as e:
        core.clean_color_palette(bad)
    assert "nothing was sent or charged" in str(e.value)


# ---- the image road: built, gated, quoted, submitted ---------------------------------------

def _road(payload, **kw):
    return core.build_request(payload, mode="image", resolve=core.RequestResolver(
        gate=core.gate_resolver(object())), **kw)


def _img(vid, **kw):
    body = {"version_id": vid, "prompt": "<prompt>", "width": 1024, "height": 1024,
            "color_palette": PALETTE}
    body.update(kw)
    return body


def _palette_receipts(req):
    return [a for a in req.adjusted if a["field"] == "colorPalette"]


def test_the_palette_rides_the_built_dict_on_a_model_that_takes_one(rest):
    req = _road(_img(T3))
    assert req.parameters["colorPalette"] == SENT
    assert _palette_receipts(req) == []


def test_no_palette_key_means_a_byte_identical_build(rest):
    with_none = _road(_img(T3, color_palette=None)).parameters
    without = _road({k: v for k, v in _img(T3).items() if k != "color_palette"}).parameters
    assert with_none == without and "colorPalette" not in without


@pytest.mark.parametrize("vid,why", [
    (FLASH_OFF, "this model takes no colour palette"),
    (SDXL, "this model takes no colour palette"),
    ("V-UNREAD", "couldn't confirm this model takes a colour palette"),
])
def test_the_gate_fails_closed_on_a_model_that_does_not_take_one(vid, why, rest):
    """Spend review B1: the rule runs before the gate's features-unread exit, so an unread
    /features strips it too (PixAI's own client reads an unread list as off)."""
    req = _road(_img(vid))
    assert "colorPalette" not in req.parameters
    assert _palette_receipts(req) == [{"field": "colorPalette", "asked": "My Rime",
                                       "used": None, "why": why}]


def test_a_context_image_takes_no_palette_one_receipt(rest):
    req = _road(_img(T3, ref_media_id="M1"))
    assert req.parameters["contextImages"] == ["M1"]
    assert "colorPalette" not in req.parameters
    assert _palette_receipts(req) == [{"field": "colorPalette", "asked": "My Rime", "used": None,
                                       "why": "a context image takes no colour palette"}]


def test_a_dict_carrying_context_images_or_an_upscale_loses_the_palette_at_the_gate(rest):
    base = {"prompts": "<p>", "modelId": T3, "width": 1024, "height": 1024, "batchSize": 1,
            "colorPalette": SENT}
    out, adj = core._gate_image_params(object(), dict(base, contextImages=["M1"]))
    assert "colorPalette" not in out and adj[0]["why"] == "a context image takes no colour palette"
    out, adj = core._gate_image_params(object(), dict(base, mediaId="M1", enlarge=2.0))
    assert "colorPalette" not in out
    assert [a["why"] for a in adj if a["field"] == "colorPalette"] == ["an upscale takes no colour palette"]
    # and the backstop form is idempotent on an already-gated dict
    gated = _road(_img(T3)).parameters
    assert core._gate_params_for_model(object(), gated) is gated


def test_the_meta_says_which_versions_take_a_palette(rest):
    assert core._attach_features(object(), {"version_id": T3})["color_palette"] is True
    assert core._attach_features(object(), {"version_id": FLASH_OFF})["color_palette"] is False
    assert core._attach_features(object(), {"version_id": "V-UNREAD"})["color_palette"] is None


def test_api_price_quotes_without_it_and_refuses_a_bad_one(tmp_path, rest, monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    cli = login_client(tmp_path)
    d = cli.post("/api/price", json=_img(T3)).get_json()
    assert d["cost"] == 5100 and not d.get("adjusted")
    assert "colorPalette" not in rest.priced[-1]          # task-price takes no colorPalette
    bad = dict(_img(T3), color_palette={"name": "x", "palette": {"character": {"colors": [
        {"hex": "#000000", "ratio": 100}]}}})
    d = cli.post("/api/price", json=bad).get_json()
    assert d["cost"] is None and "isn't valid" in d["note"]


def _web(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "account_info",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("offline")))
    return login_client(tmp_path)


def test_api_generate_sends_the_palette_it_quoted(tmp_path, rest, monkeypatch):
    cli = _web(monkeypatch, tmp_path)
    cards = []
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, params, **k: cards.append(dict(params)))
    sent = []
    monkeypatch.setattr(core, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "gql_mutate",
                        lambda s, q, v=None: sent.append(v["parameters"])
                        or {"createGenerationTask": {"id": "4242"}})
    d = cli.post("/api/generate", json=_img(T3)).get_json()
    assert d.get("task_id") == "4242", d
    assert len(sent) == 1 and sent[0]["colorPalette"] == SENT
    assert cards and cards[-1]["colorPalette"] == SENT     # the card check sees the same dict


def test_read_only_refuses_a_palette_generate_before_anything_is_sent(tmp_path, rest, monkeypatch):
    cli = _web(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(core, "gql_mutate", lambda *a, **k: sent.append(a) or {})
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "READ_ONLY", True)
    d = cli.post("/api/generate", json=_img(T3)).get_json()
    assert "READ_ONLY" in d["error"] and sent == []

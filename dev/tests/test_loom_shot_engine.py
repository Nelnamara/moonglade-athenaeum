"""A Loom shot's engine, channel and prompt helper reach PixAI exactly as they were priced
(issue #90).

The Loom used to leave `video_model` out of every shot body, so the server read a blank engine as
"the default" (V4.0 Lite) on /api/price and on /api/loom/generate alike: the standing estimate,
Generate all and a card's Render all priced and sent V4.0 Lite whatever the drawer showed. The
shot now carries `video_model` (always explicit), `is_private` and `prompt_helper`. The Loom's
side is pinned in loom/test/loom-shot-settings.test.js; this file pins the server half, the half
that spends: a body naming an engine is priced and submitted on THAT engine, byte for byte, and a
body naming none gets the default, pinned so a changed default is a decision and not a drift.

The pattern is test_video_tsubaki.py's byte-identical-blocks test, one seam lower: PixAI is the
FakePixAI transport, so what is compared is what would have gone on the wire -- the card check's
`parameters` and the price query (what /api/price asked PixAI about) against the
createGenerationTask variables (what /api/loom/generate sent). Nothing reaches the network.
"""
import json
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import gallery as g

TBKV_ID = "2054378086834851904"          # tbkv1.0.1's own numeric id (test_video_tsubaki.TBKV_IDS)
PRICE = 21000

# The Loom's own keys on a journalled render (a fresh shot and submit id for each render, so one
# test can render twice); /api/price is never sent them.
_LOOM_KEYS = ("loom_target", "submit_id", "expect_free")


def _loom_keys(n):
    return {"loom_target": {"board_id": "b1", "card_id": "c%d" % n}, "submit_id": "s%d" % n,
            "expect_free": False}

# mode -> (the block the server builds, the pictures the shot carries)
_ROADS = {"I2V": ("i2vPro", ["111"]),
          "FLF": ("i2vPro", ["111", "222"]),
          "R2V": ("referenceVideo", ["111"])}


def _shot(mode="I2V", **kw):
    """The body loom-core.js shotPayload() builds (plus the origin the Loom stamps), with the
    settings a test is about overridden. No V2V: a V2V body takes the image road on /api/price,
    so the Loom's shot modes here are the three it actually sends."""
    block, images = _ROADS[mode]
    body = {"mode": mode, "prompt": "Shot text @image1" if mode == "R2V" else "Shot text",
            "images": images, "video_refs": [], "duration": 5, "quality": "professional",
            "generate_audio": False, "audio_language": "english", "is_private": False,
            "prompt_helper": False, "hasInput": True, "origin": "loom-shot"}
    body.update(kw)
    return body


@pytest.fixture
def rig(tmp_path, pixai):
    """A signed-in client over the fake PixAI: a quote that always answers PRICE, no free card,
    and one registered create. Anything else the road reaches for fails by name."""
    from tests.conftest import login_test_client
    pixai.on("/task-price", {"actualPrice": PRICE})
    pixai.on("/kaisuuken/check", {"matches": []})
    pixai.on("createGenerationTask", {"createGenerationTask": {"id": "task-1"}})
    cli = login_test_client(g.create_app(tmp_path))
    return SimpleNamespace(cli=cli, fake=pixai, n=0)


def _price_then_render(rig, body):
    """What the Loom does for one shot: the badge's /api/price, then the render's
    /api/loom/generate with the Loom's own keys beside the same body. Returns the three views
    of the request: the card check's parameters, the price query, and the create's parameters."""
    rig.n += 1
    rig.fake.calls.clear()
    d = rig.cli.post("/api/price", json=body).get_json()
    assert d["cost"] == PRICE, d
    assert rig.fake.mutations() == 0, "a quote creates nothing"
    check = rig.fake.calls_for("/kaisuuken/check")[0]
    quote = rig.fake.calls_for("/task-price")[0]
    r = rig.cli.post("/api/loom/generate", json={**body, **_loom_keys(rig.n)}).get_json()
    assert r.get("task_id") == "task-1", r
    (create,) = rig.fake.calls_for("createGenerationTask")
    return SimpleNamespace(priced=check.body["parameters"], query=quote.params,
                           sent=create.variables["parameters"])


def _block(params):
    return params["i2vPro"] if "i2vPro" in params else params["referenceVideo"]


def _same_request(got):
    """The quote and the render are one request: every parameter the card check saw is what the
    mutation sent, and the price query's video block is that same block."""
    assert got.sent == got.priced
    road = "i2vPro" if "i2vPro" in got.sent else "referenceVideo"
    assert json.loads(got.query[road]) == got.sent[road]


# =============================================================================
# the engine rides
# =============================================================================
@pytest.mark.parametrize("mode", ["I2V", "FLF", "R2V"])
def test_a_tsubaki_shot_is_priced_and_submitted_on_tsubaki_byte_for_byte(rig, mode):
    got = _price_then_render(rig, _shot(mode, video_model="tbkv1.0.1"))
    _same_request(got)
    assert _block(got.sent)["model"] == "tbkv1.0.1"
    assert _block(got.priced)["model"] == "tbkv1.0.1"
    if mode == "R2V":
        assert got.sent["modelId"] == TBKV_ID, "the reference road sends the engine's own id"
    else:
        assert "modelId" not in got.sent, "a Tsubaki i2vPro goes out in the site's name-only shape"


@pytest.mark.parametrize("model", ["v4.0.1", "v4.0", "v3.2", "v3.0.2", "v3.0", "v3.0.1", "v2.7",
                                   "tbkv1.0", "tbkv1.0.1"])
def test_every_engine_in_the_roster_is_the_one_priced_and_sent(rig, model):
    got = _price_then_render(rig, _shot("I2V", video_model=model))
    _same_request(got)
    assert _block(got.sent)["model"] == model
    assert json.loads(got.query["i2vPro"])["model"] == model


@pytest.mark.parametrize("model", ["v4.0.1", "v4.0", "tbkv1.0", "tbkv1.0.1"])
def test_a_multi_reference_shot_carries_its_engine_on_the_reference_road(rig, model):
    got = _price_then_render(rig, _shot("R2V", video_model=model))
    _same_request(got)
    assert got.sent["referenceVideo"]["model"] == model
    assert got.sent["modelId"] == core.video_model_id(model)


def test_two_engines_do_not_collapse_into_one_request(rig):
    """The Loom's old failure in one picture: the same shot on two engines is two requests.
    A route that ignored video_model would send the default for both and this would be equal."""
    a = _price_then_render(rig, _shot("I2V", video_model="v4.0.1"))
    b = _price_then_render(rig, _shot("I2V", video_model="tbkv1.0.1"))
    assert _block(a.sent)["model"] == "v4.0.1" and _block(b.sent)["model"] == "tbkv1.0.1"
    assert a.sent != b.sent and a.priced != b.priced and a.query != b.query


# =============================================================================
# a shot with no engine: the default, pinned
# =============================================================================
def test_the_default_engine_is_pinned():
    """A changed default engine is a decision with a price attached, never a drift. The Loom's
    engineOf() reads the same constant (loom/test/video-roster-parity.test.js)."""
    assert core.DEFAULT_VIDEO_MODEL == "v4.0.1"


@pytest.mark.parametrize("named", [None, "", "   "], ids=["absent", "blank", "spaces"])
@pytest.mark.parametrize("mode", ["I2V", "R2V"])
def test_a_body_naming_no_engine_is_priced_and_sent_on_the_default(rig, mode, named):
    body = _shot(mode)
    if named is not None:
        body["video_model"] = named
    got = _price_then_render(rig, body)
    _same_request(got)
    assert _block(got.sent)["model"] == "v4.0.1"
    assert got.sent["modelId"] == core.REFVIDEO_MODEL_ID == "2003969750675682808"


def test_naming_the_default_is_the_same_request_as_naming_nothing(rig):
    """What lets an old board (no engine saved) and a shot set to V4.0 Lite price alike: the
    Loom's fingerprint treats them as equal, and so does the wire."""
    bare = _price_then_render(rig, _shot("FLF"))
    named = _price_then_render(rig, _shot("FLF", video_model="v4.0.1"))
    assert named.sent == bare.sent and named.priced == bare.priced and named.query == bare.query


# =============================================================================
# the channel and the helper ride with it
# =============================================================================
def test_the_channel_and_the_helper_reach_both_the_quote_and_the_render(rig):
    got = _price_then_render(rig, _shot("I2V", video_model="v4.0.1", is_private=True,
                                        prompt_helper=True))
    _same_request(got)
    for params in (got.priced, got.sent):
        assert params["isPrivate"] is True and params["channel"] == "private"
        assert params["i2vPro"]["usePromptsHelper"] is True


def test_a_normal_channel_and_no_helper_are_what_an_unset_shot_sends(rig):
    got = _price_then_render(rig, _shot("I2V", video_model="v4.0.1"))
    for params in (got.priced, got.sent):
        assert params["isPrivate"] is False and params["channel"] == "normal"
        assert params["i2vPro"]["usePromptsHelper"] is False


def test_the_helper_is_a_first_frame_and_first_last_field_only(rig):
    """referenceVideo has no helper field (build_shot_video_params): asking for one on a
    Multi-Reference shot changes nothing on the wire, quote or render, so the two still agree."""
    got = _price_then_render(rig, _shot("R2V", video_model="v4.0.1", prompt_helper=True))
    _same_request(got)
    assert "usePromptsHelper" not in got.sent["referenceVideo"]


def test_tsubaki_audio_and_language_ride_with_the_engine(rig):
    got = _price_then_render(rig, _shot("I2V", video_model="tbkv1.0.1", generate_audio=True,
                                        audio_language="japanese"))
    _same_request(got)
    assert got.sent["i2vPro"]["generateAudio"] is True
    assert got.sent["i2vPro"]["audioLanguage"] == "japanese"


# =============================================================================
# the Loom's own keys stay out of the request
# =============================================================================
def test_the_loom_keys_never_reach_what_was_priced_or_sent(rig):
    got = _price_then_render(rig, _shot("I2V", video_model="tbkv1.0.1"))
    for params in (got.priced, got.sent):
        assert not (set(_LOOM_KEYS) | {"video_model", "prompt_helper", "is_private"}) & set(params)
    assert not set(_LOOM_KEYS) & set(got.query)

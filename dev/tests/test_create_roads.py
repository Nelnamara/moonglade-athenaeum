"""THE ROADS ABOVE THE DOOR (DESIGN_3.22 2.4-2.7, 2.11; S3).

One reachable sender per kind (the road table, T-V6), the guard on the final card-attached body
(T-F2), one identity per send (T-V8), the observation step (T-F11), the card proof in a run
(T-V3), and no outcome decided by message text (T-F1, T-F3). The door's own tests are in
test_create_door.py; here the real door runs over a recording session where the bytes matter,
and core._create / core.gql_mutate are recorded where only the road matters. Nothing here
touches the network.
"""
import json
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gen_cli
from moonglade import gen_params
from moonglade import gen_road
from moonglade import mirror as mirror_mod
from moonglade import models as models_mod
from moonglade import pixai_client as pc
from moonglade import task_reads as task_reads_mod

from tests.conftest import _REAL_CREATE


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: False)
    monkeypatch.setattr(models_mod, "_gate_params_for_model", lambda s, p: p)
    monkeypatch.setattr(models_mod, "_profile_listing", lambda s, p: (False, False))
    monkeypatch.setattr(cards_mod, "match_kaisuuken", lambda *a, **k: None)


class _Answer:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body
        self.text, self.headers = json.dumps(body) if body is not None else "", {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class Wire:
    """A requests.Session stand-in under the REAL door: records each POST's decoded body."""

    def __init__(self, *answers):
        self.answers = list(answers) or [_Answer(200, {"id": "T1"})]
        self.posts = []
        self.headers = {}

    def post(self, url, **kw):
        body = json.loads(kw["data"].decode("utf-8")) if kw.get("data") else kw.get("json")
        self.posts.append((url, body))
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, BaseException):
            raise a
        return a

    def get(self, *a, **k):
        raise requests.ConnectionError("no reads here")


@pytest.fixture
def door(monkeypatch):
    """The real core._create (conftest blocks it)."""
    monkeypatch.setattr(core, "_create", _REAL_CREATE)


IMAGE_P = {"prompts": "a cat", "modelId": "1", "width": 512, "height": 512, "priority": 500,
           "inferenceProfile": "ultra"}


EDIT_CHAT = {"prompts": "make it night", "mediaId": "111", "mediaIds": ["111"],
             "modelId": gen_params.EDIT_PRO_MODEL_ID, "modelConfig": {"resolution": "1K"}}


FIX_BOX = {"x": 1, "y": 2, "width": 30, "height": 40, "tag": "hand"}

# Recorded from today's builders before S3-video-wire (build_shot_video_params, 2026-11-20),
# byte for byte: the GraphQL video bodies must never move (DESIGN_3.22 2.11, T-F7).
I2V_FIXTURE = json.loads(
    '{"channel": "normal", "enablePreview": true, "hidePrompts": false, "i2vPro": '
    '{"audioLanguage": "english", "duration": "5", "generateAudio": false, "mediaId": '
    '"733917871331404290", "mode": "professional", "model": "v4.0.1", "prompts": "a fox runs", '
    '"usePromptsHelper": false}, "isPrivate": false, "modelId": "2003969750675682808", '
    '"priority": 1000}')
R2V_FIXTURE = json.loads(
    '{"channel": "private", "enablePreview": true, "hidePrompts": false, "isPrivate": true, '
    '"modelId": "2003969750675682808", "priority": 1000, "referenceVideo": {"audioLanguage": '
    '"english", "duration": 5, "generateAudio": true, "inputVideoDurations": [], "mode": '
    '"professional", "model": "v4.0.1", "prompt": "@image1 waves", "referenceAudioMediaIds": [], '
    '"referenceImageMediaIds": ["733917871331404290", "733917871331404291"], '
    '"referenceVideoMediaIds": []}}')


def _shots():
    i2v = gen_params.build_shot_video_params(
        "I2V", "a fox runs", image_ids=["733917871331404290"], video_ids=[], audio_ids=[],
        duration=5, generate_audio=False, model="", camera_movement="", quality="professional",
        audio_language="english", negative="", is_private=False, use_prompt_helper=False,
        input_video_durations=[], ratio="")
    r2v = gen_params.build_shot_video_params(
        "R2V", "@image1 waves", image_ids=["733917871331404290", "733917871331404291"],
        video_ids=[], audio_ids=[], duration=5, generate_audio=True, model="",
        camera_movement="", quality="professional", audio_language="english", negative="",
        is_private=True, use_prompt_helper=False, input_video_durations=[], ratio="")
    return i2v, r2v


def test_the_graphql_video_bodies_are_byte_identical_and_to_wire_leaves_them_alone():
    i2v, r2v = _shots()
    for built, fixture, kind in ((i2v, I2V_FIXTURE, "video"), (r2v, R2V_FIXTURE, "refvideo")):
        assert json.dumps(built, sort_keys=True) == json.dumps(fixture, sort_keys=True)
        wired = gen_params.to_wire(kind, built)
        assert wired is built, "to_wire touched a GraphQL body"
        assert json.dumps(wired, sort_keys=True) == json.dumps(fixture, sort_keys=True)
        assert {"isPrivate", "enablePreview", "hidePrompts"} <= set(wired)   # nothing dropped


def test_the_video_road_sends_the_fixture_through_gql_mutate_unchanged(monkeypatch):
    sent = []
    monkeypatch.setattr(core, "gql_mutate", lambda s, q, v=None: sent.append(v["parameters"])
                        or {"createGenerationTask": {"id": "V1"}})
    monkeypatch.setattr(core, "_create", lambda *a, **k: pytest.fail("video rode the door"))
    i2v, _r2v = _shots()
    req = gen_road.build_request({"mode": "I2V", "images": ["733917871331404290"],
                                  "prompt": "a fox runs", "duration": 5}, mode="video")
    assert gen_road.submit(object(), req, no_card=True) == {"task_id": "V1"}
    assert json.dumps(sent[0], sort_keys=True) == json.dumps(i2v, sort_keys=True)
ENHANCE_BODY = {"enhanceType": "background-remover", "mediaId": "111"}
# PixAI's constants.imageEnhancementPlugins, as its live config answers it (DECISIONS: the
# per-plugin {workflowName, workflowVersion, args}); the names are the presets' pinned ones.
PLUGINS = {"handfix": {"workflowName": "mymusise/hand-fix", "workflowVersion": "v1"},
           "face-detailer": {"workflowName": "kyo/face-detailer", "workflowVersion": "v4.0"},
           "emotion": {"workflowName": "kyo/emotionlab", "workflowVersion": "633acbbb"},
           "background-remover": {"workflowName": "mymusise/39a2c67c",
                                  "workflowVersion": "unet-0.1.3.2"},
           "image-to-lineart": {"workflowName": "pixai-official/image-to-lineart"},
           "sketch-coloring": {"workflowName": "pixai-official/sketch-coloring-workflow"}}


def _web_jwt(session):
    """The Mirror armed for the test: a marked web-jwt client over `session`."""
    c = pc.PixAIClient(session, auth_kind="web-jwt")
    c._create_chosen = True
    return c


# ---------------------------------------------------------------------------
# Enhance on the REST route (T-F4, T-V9, mutations 12, 13, 28)
# ---------------------------------------------------------------------------

@pytest.fixture
def plugins(monkeypatch):
    monkeypatch.setattr(core, "_cached_config",
                        lambda key, **k: {"imageEnhancementPlugins": PLUGINS}
                        if key == "constants" else None)


def test_every_pinned_preset_maps_to_the_type_pixais_site_would_send(plugins):
    want = {"handfix": "handfix", "face": "face-detailer", "emotion": "emotion",
            "bg_remove": "background-remover", "line_art": "image-to-lineart",
            "sketch_color": "sketch-coloring"}
    for pr in gen_params.BRIDGE_ENHANCE_PRESETS:
        assert gen_params.enhance_type_for(pr["workflow_name"]) == want[pr["key"]], pr["key"]


def test_an_unmapped_preset_is_a_note_and_never_sent(monkeypatch):
    monkeypatch.setattr(core, "_cached_config", lambda key, **k: None)   # config unreadable
    req = gen_road.build_request({"source": "111", "workflow_name": "mymusise/hand-fix:v1"},
                                 mode="enhance")
    assert req.parameters is None and req.note == gen_params.ENHANCE_UNMAPPED
    req = gen_road.build_request({"source": "111", "workflow_id": "1793447160259872021"},
                                 mode="enhance")
    assert req.parameters is None                    # a numeric id can never be mapped


def test_the_enhance_body_and_the_emotion_prompt(plugins):
    req = gen_road.build_request({"source": "111", "workflow_name": "mymusise/39a2c67c:unet"},
                                 mode="enhance")
    assert req.parameters == ENHANCE_BODY and req.no_card is True
    emo = gen_road.build_request({"source": "111", "emotion": "smile",
                                  "workflow_name": gen_params.ENHANCE_EMOTION_WORKFLOW},
                                 mode="enhance")
    assert emo.parameters["enhanceType"] == "emotion" and emo.parameters["prompt"]
    # an emotion without its expression cannot be sent (the site's own rule)
    bare = gen_road.build_request({"source": "111",
                                   "workflow_name": gen_params.ENHANCE_EMOTION_WORKFLOW},
                                  mode="enhance")
    assert bare.parameters is None


def test_an_enhance_send_makes_no_card_call_and_rides_the_web_sign_in(door, monkeypatch):
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken",
                        lambda *a, **k: pytest.fail("an enhance reached the card step"))
    monkeypatch.setattr(cards_mod, "match_kaisuuken",
                        lambda *a, **k: pytest.fail("an enhance reached the card check"))
    wire = Wire(_Answer(200, {"id": "E1"}))
    req = gen_road.GenerationRequest(mode="enhance", parameters=dict(ENHANCE_BODY),
                                     no_card=False, media_id="111")
    assert gen_road.submit(_web_jwt(wire), req, no_card=False) == {"task_id": "E1"}
    (url, body), = wire.posts
    assert url.endswith("/task/enhance") and body == ENHANCE_BODY
    # on the API key it is refused with nothing sent (mutation 14)
    wire2 = Wire()
    with pytest.raises(core.LocalRefusal):
        gen_road.submit(pc.PixAIClient(wire2), req)
    assert wire2.posts == []


def test_the_badge_quotes_the_enhance_price_route_on_the_mirror_session(monkeypatch):
    asked = []
    mirror_session = object()
    monkeypatch.setattr(cards_mod, "match_kaisuuken",
                        lambda *a, **k: pytest.fail("an enhance quote ran a card check"))
    monkeypatch.setattr(core, "_rest_post", lambda s, path, body, **k: (
        asked.append((s, path, body)), {"actualPrice": 1000})[1])
    from moonglade import pricing
    monkeypatch.setattr(pricing, "enhance_quote_session", lambda: mirror_session)
    req = gen_road.GenerationRequest(mode="enhance", parameters=dict(ENHANCE_BODY),
                                     media_id="111", no_card=True)
    out = gen_road.price(object(), req)
    assert out["cost"] == 1000 and out["free"] is False
    assert asked == [(mirror_session, "/task/enhance/price", ENHANCE_BODY)]
    # an answer that is not {actualPrice: int} is no number
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: {"actualPrice": "1000"})
    assert gen_road.price(object(), req)["cost"] is None
    # no armed Mirror: no call at all, and "couldn't verify"
    monkeypatch.setattr(pricing, "enhance_quote_session", lambda: None)
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: pytest.fail("quoted with no Mirror"))
    out = gen_road.price(object(), req)
    assert out["cost"] is None and out["note"] == gen_road._ENHANCE_PRICE_NOTE


def test_the_quote_and_spend_paths_are_never_swapped():
    from moonglade import pricing
    assert pricing._ENHANCE_PRICE_PATH == "/task/enhance/price"
    assert pc.CREATE_PATHS["enhance"] == "/task/enhance"
    assert pricing._FIXER_PRICE_PATH == "/task/fixer/price"
    assert pc.CREATE_PATHS["fix"] == "/task/fixer"


@pytest.mark.parametrize("mode", ["enhance", "scene", "fix"])
def test_a_cardless_send_claiming_a_free_quote_is_refused(mode):
    req = gen_road.GenerationRequest(mode=mode, parameters={"x": 1})
    with pytest.raises(core.LocalRefusal):
        gen_road.quoted_free_hooks(req, True)
    assert gen_road.quoted_free_hooks(req, False) == {}


def test_a_fix_over_the_real_door_is_one_post_of_the_cleaned_body(door):
    wire = Wire(_Answer(200, {"id": "F1"}))
    assert gen_road.submit_fixer(pc.PixAIClient(wire), "111", [dict(FIX_BOX, tag="HAND")]) \
        == "F1"
    (url, body), = wire.posts
    assert url.endswith("/task/fixer") and body == {"mediaId": "111", "boxes": [FIX_BOX]}


@pytest.mark.parametrize("answer", [_Answer(200, {}), requests.ReadTimeout("slow"),
                                    _Answer(307, {"id": "F1"})])
def test_a_fix_without_a_proven_id_is_unknown_and_sent_once(door, answer):
    wire = Wire(answer)
    with pytest.raises(core.CreateOutcomeUnknown):
        gen_road.submit_fixer(pc.PixAIClient(wire), "111", [dict(FIX_BOX)])
    assert len(wire.posts) == 1


def test_a_scene_rides_the_door_on_the_web_sign_in_only(door, monkeypatch):
    """T-F5 through the road: submit_scene on the API key is refused with nothing sent; on the
    Mirror's marked client it is one POST of the scene input."""
    wire = Wire(_Answer(200, {"id": "S1"}))
    with pytest.raises(core.LocalRefusal):
        gen_road.submit_scene(pc.PixAIClient(wire), "character-card", ["111"])
    assert wire.posts == []
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda *a, **k: wire)
    client = pc.PixAIClient(Wire()).for_create(require="web-jwt")
    assert gen_road.submit_scene(client, "character-card", ["111"], preset="random") == "S1"
    (url, body), = wire.posts
    assert url.endswith("/task/chat-editing-scene")
    assert body == {"sceneId": "character-card", "mediaIds": ["111"], "preset": "random"}


def test_a_scene_answer_without_an_id_is_unknown(door):
    wire = Wire(_Answer(200, {}))
    with pytest.raises(core.CreateOutcomeUnknown):
        gen_road.submit_scene(pc.PixAIClient(wire, auth_kind="web-jwt"), "s", ["1"])
    assert len(wire.posts) == 1


def _image_req(params=None):
    return gen_road.GenerationRequest(mode="image", parameters=dict(params or IMAGE_P),
                                      no_card=True)


# ---------------------------------------------------------------------------
# One reachable sender per kind (T-V6, mutation 4 and 26)
# ---------------------------------------------------------------------------

@pytest.fixture
def roads(monkeypatch):
    """Record which road a sender reached: the door, or gql_mutate."""
    hit = []

    def _door(session, kind, body):
        hit.append(("rest", kind))
        return {"id": "T1"}

    def _gql(session, document, variables=None):
        hit.append(("graphql", document.split("(")[0].split()[-1]))
        return {"createGenerationTask": {"id": "T1"},
                "createChatEditingSceneTask": {"id": "T1"}}
    monkeypatch.setattr(core, "_create", _door)
    monkeypatch.setattr(core, "gql_mutate", _gql)
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: (hit.append(("rest_post", a[1])),
                                                              {"id": "T1"})[1])
    return hit


def _cli_args(tmp_path, **extra):
    base = dict(out=str(tmp_path), params_json='{"prompts": "test"}', confirm=True,
                task_id="", token=None, prompt="")
    base.update(extra)
    return SimpleNamespace(**base)


@pytest.fixture
def cli(monkeypatch, mock_session):
    monkeypatch.setattr(core, "_make_session", lambda token=None, **k: mock_session)
    monkeypatch.setattr(task_reads_mod, "_poll_task_status", lambda *a, **k: None)
    monkeypatch.setattr(task_reads_mod, "task_detail_gql", lambda *a, **k: {})
    monkeypatch.setattr(gen_cli, "_maybe_dump_params", lambda *a, **k: None)
    return mock_session


def _drive(fn, args):
    try:
        fn(args)
    except Exception:                                        # noqa: BLE001 -- after the send
        pass


# Each kind's senders, web and CLI (V6): the one-sender test lists the CLI runners too.
SENDERS = {
    "image": [
        ("web submit", lambda s, tmp: gen_road.submit(s, _image_req())),
        ("run_generate", lambda s, tmp: _drive(gen_cli.run_generate, _cli_args(tmp))),
    ],
    "edit": [
        ("web submit", lambda s, tmp: gen_road.submit(s, gen_road.GenerationRequest(
            mode="edit", parameters={"chat": dict(EDIT_CHAT)}, no_card=True))),
        ("run_edit_image", lambda s, tmp: _drive(gen_cli.run_edit_image, _cli_args(
            tmp, edit_src=["111"], params_json=json.dumps({"chat": EDIT_CHAT})))),
    ],
    # AI Tools scenes have no CLI runner: the one sender is submit_scene (the /api/scene road).
    "scene": [
        ("submit_scene", lambda s, tmp: gen_road.submit_scene(s, "character-card", ["111"])),
    ],
    # Enhance has no CLI runner: its one sender is the web road (submit -> submit_enhance).
    "enhance": [
        ("web submit", lambda s, tmp: gen_road.submit(_web_jwt(s), gen_road.GenerationRequest(
            mode="enhance", parameters=dict(ENHANCE_BODY), no_card=True, media_id="111"))),
    ],
    # Video and reference video stay on GraphQL (owner, 2026-11-19): web and both CLI runners.
    "video": [
        ("web submit", lambda s, tmp: gen_road.submit(s, gen_road.GenerationRequest(
            mode="video", parameters=dict(I2V_FIXTURE), no_card=True))),
        ("run_generate_video", lambda s, tmp: _drive(gen_cli.run_generate_video, _cli_args(
            tmp, image="733917871331404290", params_json=json.dumps(I2V_FIXTURE)))),
    ],
    "refvideo": [
        ("run_reference_video", lambda s, tmp: _drive(gen_cli.run_reference_video, _cli_args(
            tmp, ref_image=["733917871331404290"], params_json=json.dumps(R2V_FIXTURE)))),
    ],
    # The Fix has no CLI runner: its one sender is the web road (submit -> submit_fixer).
    "fix": [
        ("web submit", lambda s, tmp: gen_road.submit(s, gen_road.GenerationRequest(
            mode="fix", media_id="111", boxes=[dict(FIX_BOX)], no_card=True,
            parameters={"mediaId": "111", "boxes": [dict(FIX_BOX)]}))),
    ],
}


@pytest.mark.parametrize("kind, name, send",
                         [(k, n, f) for k, rows in SENDERS.items() for n, f in rows],
                         ids=lambda v: v if isinstance(v, str) else "")
def test_each_kind_has_one_road_and_every_sender_rides_it(kind, name, send, roads, cli,
                                                          tmp_path):
    send(cli, tmp_path)
    want = gen_road.CREATE_ROAD[kind]
    assert roads, "{} sent nothing".format(name)
    assert {r for r, _k in roads} == {want}, "{} rode {} while CREATE_ROAD says {}".format(
        name, roads, want)
    if want == "rest":
        assert all(k == kind for _r, k in roads)


def test_the_road_table_is_closed_and_video_stays_on_graphql():
    assert set(gen_road.CREATE_ROAD) == {"image", "edit", "scene", "enhance", "fix", "video",
                                         "refvideo"}
    assert set(gen_road.CREATE_ROAD.values()) <= {"rest", "graphql", "rest_post"}
    assert gen_road.CREATE_ROAD["video"] == gen_road.CREATE_ROAD["refvideo"] == "graphql"


# ---------------------------------------------------------------------------
# The guard sees the final, card-attached body (T-F2, mutation 15)
# ---------------------------------------------------------------------------

def test_the_card_rides_inside_parameters_on_the_final_body(door, monkeypatch):
    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
        return "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    wire = Wire()
    req = gen_road.GenerationRequest(mode="image", parameters=dict(IMAGE_P))
    assert gen_road.submit(pc.PixAIClient(wire), req)["task_id"] == "T1"
    (url, body), = wire.posts
    assert url.endswith("/task/create")
    assert body["parameters"]["kaisuukenId"] == "K1" and set(body) == {"parameters"}


def test_a_tsubaki2_image_from_the_builder_passes_the_wire_guard(door):
    """The default model's image, built by the web road's own builder, goes out through the
    real door: naturalPrompts sits under `extra` (as PixAI's site nests it), never at the top
    level, where REST's `yt` has no such key and the guard would refuse every image."""
    req = gen_road.build_request({"prompt": "a cat", "version_id": gen_params.DEFAULT_GEN_MODEL},
                                 mode="image")
    assert req.parameters["modelId"] == gen_params.DEFAULT_GEN_MODEL
    wire = Wire()
    assert gen_road.submit(pc.PixAIClient(wire), req)["task_id"] == "T1"
    (url, body), = wire.posts
    assert url.endswith("/task/create")
    assert body["parameters"]["extra"] == {"naturalPrompts": "a cat"}
    assert "naturalPrompts" not in body["parameters"]


def test_a_stray_top_level_naturalprompts_is_still_refused_unsent(door):
    """A hand-built or --params-json body with the old top-level key is refused, never
    stripped -- the builder moving it is not a licence for the guard to."""
    wire = Wire()
    req = _image_req(dict(IMAGE_P, naturalPrompts="a cat"))
    with pytest.raises(core.LocalRefusal, match="naturalPrompts"):
        gen_road.submit(pc.PixAIClient(wire), req)
    assert wire.posts == []


def test_the_video_builders_never_carry_the_image_extra():
    """The naturalPrompts move is the image builder's alone: the GraphQL video and
    reference-video bodies keep their recorded bytes (the fixture test above) and carry
    neither key."""
    for built in _shots():
        assert "extra" not in built and "naturalPrompts" not in built


def test_a_nested_unknown_key_added_after_the_card_step_is_refused_unsent(door, monkeypatch):
    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
        return "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    monkeypatch.setattr(models_mod, "_gate_params_for_model",
                        lambda s, p: dict(p, promptHelper={"enable": True, "sneaky": 1}))
    wire = Wire()
    req = gen_road.GenerationRequest(mode="image", parameters=dict(IMAGE_P))
    with pytest.raises(core.LocalRefusal, match="promptHelper.sneaky"):
        gen_road.submit(pc.PixAIClient(wire), req)
    assert wire.posts == []


# ---------------------------------------------------------------------------
# One identity per send (T-V8, mutation 27)
# ---------------------------------------------------------------------------

def test_the_card_check_and_the_door_get_the_same_client_and_a_toggle_changes_nothing(
        monkeypatch):
    seen = {}

    def _card(session, params, args):
        seen["card"] = session
        # the Mirror is switched on between the card check and the send
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
        monkeypatch.setattr(mirror_mod, "make_mirror_session",
                            lambda *a, **k: pytest.fail("the identity was chosen twice"))
        return ""

    def _door(session, kind, body):
        seen["door"] = session
        return {"id": "T1"}
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    monkeypatch.setattr(core, "_create", _door)
    before = {}
    req = gen_road.GenerationRequest(mode="image", parameters=dict(IMAGE_P))
    gen_road.submit(pc.PixAIClient(Wire()), req,
                    before_send=lambda p: before.setdefault("params", p))
    assert seen["card"] is seen["door"]
    assert seen["door"].auth_kind == "api-key" and seen["door"]._create_chosen is True
    assert before["params"] is req.parameters


# ---------------------------------------------------------------------------
# The observation step (T-F11) and the card proof in a run (T-V3)
# ---------------------------------------------------------------------------

def test_a_card_send_answered_with_a_charge_is_a_loud_warning_and_nothing_else(door, caplog):
    import logging
    wire = Wire(_Answer(200, {"id": "T1", "paidQuota": 3000,
                              "parameters": dict(IMAGE_P, kaisuukenId="K1")}))
    with caplog.at_level(logging.WARNING, logger="moonglade.create"):
        tid = gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P, kaisuukenId="K1"))
    assert tid == "T1" and len(wire.posts) == 1
    assert any("paidQuota 3000" in r.getMessage() for r in caplog.records)


def test_a_stored_request_that_differs_is_a_warning(door, caplog):
    import logging
    wire = Wire(_Answer(200, {"id": "T1", "parameters": dict(IMAGE_P, priority=0)}))
    with caplog.at_level(logging.WARNING, logger="moonglade.create"):
        gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P))
    assert any("priority sent 500, stored 0" in r.getMessage() for r in caplog.records)


def test_the_observation_step_never_turns_a_created_task_into_an_error(door, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("an observer bug")
    wire = Wire(_Answer(200, {"id": "T1", "parameters": "not a dict", "paidQuota": "x"}))
    assert gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P),
                                      on_created=_boom) == "T1"


def _run(monkeypatch, answers, budget, status=None, reads=None, slept=None):
    """Three card-covered image jobs through send_run, the door answering `answers`. `status`
    answers each task's read (a callable is called with the task id); `reads` and `slept`
    record the reads and the run's pauses."""
    monkeypatch.setattr(core, "_create", lambda s, k, b: answers.pop(0))

    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
        return "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)

    def _status(s, t):
        if reads is not None:
            reads.append(t)
        if callable(status):
            return status(t)
        return status.get(t, {}) if status else {}
    monkeypatch.setattr(task_reads_mod, "generation_status", _status)
    hooks = SimpleNamespace(sending=lambda c: None, sent=lambda *a, **k: None,
                            failed=lambda *a: None)
    jobs = [{"cell": i, "req": _image_req(), "no_card": None} for i in range(3)]
    return gen_road.send_run(pc.PixAIClient(Wire()), jobs, hooks=hooks, budget=budget,
                             gap_s=0, sleep=(slept.append if slept is not None
                                             else (lambda s: None)))


DONE_FREE = {"phase": "done", "paid_credit": 0}


def test_a_run_counts_an_ignored_card_as_charged_and_never_pays_past_its_total(monkeypatch):
    assert gen_road.CARD_PROOF_ON_REST is False
    res = _run(monkeypatch, [{"id": "A", "paidQuota": 100}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 100})
    assert [j["state"] for j in res["jobs"]] == ["sent", "not_sent", "not_sent"]
    assert res["status"] == "stopped"


def test_a_charge_seen_on_the_read_before_the_next_job_counts_too(monkeypatch):
    res = _run(monkeypatch, [{"id": "A"}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 100}, status={"A": {"paid_credit": 100}})
    assert [j["state"] for j in res["jobs"]] == ["sent", "not_sent", "not_sent"]


def test_cards_that_apply_leave_the_run_alone(monkeypatch):
    res = _run(monkeypatch, [{"id": "A", "paidQuota": 0}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 0}, status={"A": DONE_FREE, "B": DONE_FREE})
    assert [j["state"] for j in res["jobs"]] == ["sent", "sent", "sent"]


# 3.22 review F3: the read before the next job fails CLOSED.

def test_a_card_read_that_fails_counts_the_job_as_charged(monkeypatch):
    """Card job A's read fails: A counts as charged, so B (a card job too) is held to the
    confirmed total and is not sent. Before F3 a failed read counted nothing, and B skipped
    the budget check."""
    def _down(t):
        raise core.PixAIError("REST GET /task/A -> 502")
    res = _run(monkeypatch, [{"id": "A"}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 100}, status=_down)
    assert [j["state"] for j in res["jobs"]] == ["sent", "not_sent", "not_sent"]
    assert "hasn't shown whether the free card on image 1 was used" in res["reason"]


def test_a_card_job_still_running_is_read_until_it_ends(monkeypatch):
    """A read 1.5 s after the create finds the task still running with paidQuota 0, which
    proves nothing: the run reads again (its own pause between) until the task ends."""
    seq = {"A": [{"phase": "running", "paid_credit": 0}, {"phase": "running"}, DONE_FREE],
           "B": [DONE_FREE]}
    reads, slept = [], []
    res = _run(monkeypatch, [{"id": "A"}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 0},
               status=lambda t: seq[t].pop(0) if len(seq[t]) > 1 else seq[t][0],
               reads=reads, slept=slept)
    assert [j["state"] for j in res["jobs"]] == ["sent", "sent", "sent"]
    assert reads == ["A", "A", "A", "B"]
    assert slept == [gen_road.RUN_CARD_PROOF_POLL_S] * 2


def test_a_card_charged_at_its_terminal_read_is_marked_unused(monkeypatch):
    """3.22 review F2 (T-V3): the terminal read shows a charge on card job A -- its record and
    the run's hook both say the card was not used, and the run is held to its total."""
    marked, sent = [], []
    monkeypatch.setattr(core, "_create", lambda s, k, b: {"id": "A"} if not sent else {"id": "B"})

    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    monkeypatch.setattr(task_reads_mod, "generation_status",
                        lambda s, t: {"phase": "done", "paid_credit": 100})
    hooks = SimpleNamespace(sending=lambda c: None,
                            sent=lambda *a, **k: sent.append((a[0], k)),
                            failed=lambda *a: None,
                            card_unused=lambda cell, tid: marked.append((cell, tid)))
    jobs = [{"cell": i, "req": _image_req(), "no_card": None} for i in range(2)]
    res = gen_road.send_run(pc.PixAIClient(Wire()), jobs, hooks=hooks,
                            budget={"each": 100, "total": 100}, gap_s=0, sleep=lambda s: None)
    assert res["jobs"][0]["card_unused"] is True and marked == [(0, "A")]
    assert [j["state"] for j in res["jobs"]] == ["sent", "not_sent"]
    assert sent == [(0, {})]


def test_a_card_charged_at_create_reaches_the_sent_hook(monkeypatch):
    sent = []
    monkeypatch.setattr(core, "_create", lambda s, k, b: {"id": "A", "paidQuota": 100})

    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    hooks = SimpleNamespace(sending=lambda c: None,
                            sent=lambda *a, **k: sent.append((a[0], a[3], k)),
                            failed=lambda *a: None)
    res = gen_road.send_run(pc.PixAIClient(Wire()),
                            [{"cell": 0, "req": _image_req(), "no_card": None}], hooks=hooks,
                            budget={"each": 100, "total": 100}, gap_s=0, sleep=lambda s: None)
    assert res["jobs"][0]["card_unused"] is True
    assert sent == [(0, True, {"card_unused": True})]


def test_a_card_job_that_never_ends_in_time_holds_the_run(monkeypatch):
    slept = []
    res = _run(monkeypatch, [{"id": "A"}, {"id": "B"}, {"id": "C"}],
               {"each": 100, "total": 100},
               status=lambda t: {"phase": "running", "paid_credit": 0}, slept=slept)
    assert [j["state"] for j in res["jobs"]] == ["sent", "not_sent", "not_sent"]
    assert sum(slept) >= gen_road.RUN_CARD_PROOF_WAIT_S


# ---------------------------------------------------------------------------
# No outcome decided by message text (T-F1), no resend on an unknown code (T-F3)
# ---------------------------------------------------------------------------

LIES = "GraphQL error: REQUIRE_MEMBERSHIP 40300047 turbo is members-only inferenceProfile"


def _rest_refusal(code, issues=None, message=LIES):
    body = {"code": code, "message": message}
    if issues is not None:
        body["data"] = {"issues": issues}
    return _Answer(400, body)


@pytest.mark.parametrize("answer", [
    requests.ReadTimeout(LIES),
    _Answer(200, {"no": "id", "message": LIES}),
    _Answer(503, {"code": "REQUIRE_MEMBERSHIP", "message": LIES}),
    _Answer(408, {"code": "REQUIRE_MEMBERSHIP", "message": LIES}),
    _rest_refusal("FILE_NOT_FOUND"),
    _rest_refusal("BAD_REQUEST", issues=[{"path": ["parameters", "width"], "message": LIES}]),
    _Answer(403, None),
], ids=["timeout", "no-id", "503", "408", "file-not-found", "bad-request-other-path",
        "bare-403"])
def test_a_crafted_message_never_buys_a_second_send(door, answer):
    wire = Wire(answer, _Answer(200, {"id": "T2"}))
    with pytest.raises((core.PixAIError, core.CreateOutcomeUnknown)):
        gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P))
    assert len(wire.posts) == 1


def test_the_profile_drop_fires_on_the_structured_path_only(door, monkeypatch):
    monkeypatch.setattr(gen_road, "print", lambda *a, **k: None, raising=False)
    wire = Wire(_rest_refusal("BAD_REQUEST", issues=[
        {"path": ["parameters", "inferenceProfile"], "message": "no"}]),
        _Answer(200, {"id": "T2"}))
    assert gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P)) == "T2"
    assert len(wire.posts) == 2
    assert "inferenceProfile" in wire.posts[0][1]["parameters"]
    assert "inferenceProfile" not in wire.posts[1][1]["parameters"]


def test_the_turbo_downgrade_fires_on_the_code_only(door, monkeypatch):
    monkeypatch.setattr(core, "_turbo_refused", {"seen": False})
    p = dict(IMAGE_P)
    p.pop("inferenceProfile")
    wire = Wire(_rest_refusal("REQUIRE_MEMBERSHIP", message="nothing about speed"),
                _Answer(200, {"id": "T2"}))
    assert gen_road.submit_generation(pc.PixAIClient(wire), p) == "T2"
    assert [b["parameters"]["priority"] for _u, b in wire.posts] == [500, 0]


def test_a_run_job_is_never_resubmitted(door):
    wire = Wire(_rest_refusal("REQUIRE_MEMBERSHIP"), _Answer(200, {"id": "T2"}))
    with pytest.raises(core.PixAIRestError):
        gen_road.submit_generation(pc.PixAIClient(wire), dict(IMAGE_P), exact=True)
    assert len(wire.posts) == 1


def test_the_text_keyed_helpers_read_codes_only():
    plain = core.PixAIError(LIES)
    assert gen_road._is_turbo_refusal(plain) is False
    assert gen_road._names_inference_profile(plain) is False
    coded = core.graphql_error([{"message": "x", "extensions": {"code": 40300047}}])
    assert gen_road._is_turbo_refusal(coded) is True
    rest = core.PixAIRestError(LIES, status=400, body={"code": "BAD_REQUEST"})
    assert gen_road._names_inference_profile(rest) is False


# ---------------------------------------------------------------------------
# READ_ONLY first on the image road (mutation 9)
# ---------------------------------------------------------------------------

def test_read_only_refuses_the_image_road_before_the_card_or_the_mirror(monkeypatch, cli,
                                                                        tmp_path, roads):
    monkeypatch.setattr(core, "READ_ONLY", True)
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken",
                        lambda *a: pytest.fail("the card check ran under READ_ONLY"))
    monkeypatch.setattr(mirror_mod, "_session_for_create",
                        lambda s: pytest.fail("the identity was chosen under READ_ONLY"))
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        gen_road.submit(cli, _image_req())
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        gen_cli.run_generate(_cli_args(tmp_path))
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        gen_road.submit(cli, gen_road.GenerationRequest(mode="edit",
                                                        parameters={"chat": dict(EDIT_CHAT)}))
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        gen_cli.run_edit_image(_cli_args(tmp_path, edit_src=["111"],
                                         params_json=json.dumps({"chat": EDIT_CHAT})))
    assert roads == []


def test_the_edit_runner_says_may_have_started_after_one_lost_send(door, cli, monkeypatch,
                                                                   tmp_path):
    """run_edit_image over the real door: a lost answer is one POST and the honest sentence."""
    wire = Wire(requests.ReadTimeout("slow"))
    monkeypatch.setattr(core, "_make_session", lambda token=None, **k: pc.PixAIClient(wire))
    with pytest.raises(gen_road.SendOutcomeUnclear):
        gen_cli.run_edit_image(_cli_args(tmp_path, edit_src=["111"],
                                         params_json=json.dumps({"chat": EDIT_CHAT})))
    assert len(wire.posts) == 1 and wire.posts[0][0].endswith("/task/create")
    assert wire.posts[0][1] == {"parameters": {"chat": EDIT_CHAT}}

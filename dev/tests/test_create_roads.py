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


def _run(monkeypatch, answers, budget, status=None):
    """Two card-covered image jobs through send_run, the door answering `answers`."""
    monkeypatch.setattr(core, "_create", lambda s, k, b: answers.pop(0))

    def _card(session, params, args):
        params["kaisuukenId"] = "K1"
        return "K1"
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _card)
    monkeypatch.setattr(task_reads_mod, "generation_status",
                        lambda s, t: status.get(t, {}) if status else {})
    hooks = SimpleNamespace(sending=lambda c: None, sent=lambda *a: None,
                            failed=lambda *a: None)
    jobs = [{"cell": i, "req": _image_req(), "no_card": None} for i in range(3)]
    return gen_road.send_run(pc.PixAIClient(Wire()), jobs, hooks=hooks, budget=budget,
                             gap_s=0)


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
               {"each": 100, "total": 0}, status={})
    assert [j["state"] for j in res["jobs"]] == ["sent", "sent", "sent"]


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

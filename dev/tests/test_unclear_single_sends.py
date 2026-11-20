"""3.21.2, L1 (DESIGN_3.22 "Live in master today"): a single send whose answer cannot show
whether PixAI made the task says "may have started" and holds the same send.

Every web single send -- /api/generate, /api/edit, /api/enhance, /api/scene, /api/fix and the
gallery's own Video tab on /api/loom/generate -- used to answer a lost or unreadable answer with
a plain {"error"} and re-arm, inviting a second paid tap. Now:
  - an unknown outcome (a timeout, a dropped connection, a 5xx, an answer with no task id)
    answers {error: the may-have-started sentence, state: "may_have_started", unclear: true};
  - the repeat record is claimed BEFORE the send and KEPT on success (the double-tap window)
    and on an unknown outcome (the 60 s window), and an identical send while it stands is
    refused (409) with nothing sent;
  - it is DROPPED only when the send is known to have cost nothing: a definite refusal, or a
    failure before the send was reached.
And the CLI runners print the honest sentence and exit non-zero.

The transport is the REAL one: core._make_session hands out a PixAIClient over a mocked
requests.Session whose post() records every call and answers (or raises) what the test says,
so "nothing was sent" is read off the wire itself. build_request is stubbed (above the door)
so each route reaches its one send without the read-only lookups a real build makes."""
import json

import pytest
import requests

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gallery as g
from moonglade import gen_params as gen_params_mod
from moonglade import mirror as mirror_mod
from moonglade import models as models_mod
from moonglade import pixai_client as pc
from tests.conftest import _REAL_REST_GET, _REAL_REST_POST, login_client

V = "1983308862240288769"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = {}

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%d Server Error" % self.status_code, response=self)


class Wire:
    """A requests.Session stand-in: post() records (url, json) and answers `answer` -- a
    _Resp, an exception to raise, or a callable(url, body) returning either. Reads are not
    part of these tests and fail loudly as a dropped connection (every read on these roads
    is fail-soft)."""

    def __init__(self):
        self.posts = []
        self.answer = None
        self.headers = {}

    def post(self, url, json=None, **k):
        assert k.get("allow_redirects") is False, "a create never follows a redirect"
        self.posts.append((url, json))
        a = self.answer(url, json) if callable(self.answer) else self.answer
        if isinstance(a, BaseException):
            raise a
        return a

    def get(self, *a, **k):
        raise requests.ConnectionError("no reads in this test")

    put = patch = get

    def creates(self):
        return [p for p in self.posts if "kaisuuken" not in p[0]]


def _created(task_id="task-1"):
    return _Resp(200, {"data": {"createGenerationTask": {"id": task_id}}})


def _scene_created(task_id="scene-1"):
    return _Resp(200, {"data": {"createChatEditingSceneTask": {"id": task_id}}})


# The unknown outcomes, as the real transport meets them.
UNKNOWN = {
    "read-timeout": lambda: requests.ReadTimeout("read timed out"),
    "dropped": lambda: requests.ConnectionError("connection reset"),
    "502": lambda: _Resp(502, "<html>Bad Gateway</html>"),
    "non-json-200": lambda: _Resp(200, "<html>hello</html>"),
    "no-id": lambda: _Resp(200, {"data": {"createGenerationTask": None}}),
}
REFUSED = lambda: _Resp(200, {"errors": [{"message": "Not enough credits", "extensions": {
    "code": "FORBIDDEN", "exception": {"name": "INSUFFICIENT_BALANCE"}}}], "data": None})


class _Req:
    def __init__(self, mode):
        self.mode, self.unlimited, self.no_card = mode, False, True
        self.parameters = {"modelId": V, "prompts": "a cat"}
        self.adjusted, self.note, self.media_id, self.boxes = [], "", None, None
        self.lora_version_ids, self.model_version_id = [], V


@pytest.fixture
def rig(tmp_path, monkeypatch):
    wire = Wire()
    client = pc.PixAIClient(wire)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: client)
    # the real /v2 delegates (conftest blocks them by default): they reach `wire` through
    # PixAIClient, which is the transport under test
    monkeypatch.setattr(core, "_rest_post", _REAL_REST_POST)
    monkeypatch.setattr(core, "_rest_get", _REAL_REST_GET)
    monkeypatch.setattr(mirror_mod, "_session_for_create", lambda s: s)
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda *a, **k: client)
    monkeypatch.setattr(core, "build_request", lambda payload, *a, mode=None, **k: _req_for(mode, payload))
    monkeypatch.setattr(models_mod, "_gate_params_for_model", lambda s, p: p)
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: pytest.fail("no upload here"))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    clock = [1000.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])
    return {"cli": login_client(tmp_path), "wire": wire, "clock": clock}


def _req_for(mode, payload):
    r = _Req(mode or "image")
    if mode == "fix":
        r.parameters = {"mediaId": "700", "boxes": payload.get("boxes")}
        r.media_id, r.boxes = "700", payload.get("boxes")
    return r


FACE = {"x": 1, "y": 2, "width": 30, "height": 40, "tag": "face"}

# route, body, the success answer, how many creates one send makes
ROUTES = {
    "generate": ("/api/generate", {"model_id": "M1", "version_id": V, "prompt": "a cat"}, _created),
    "edit": ("/api/edit", {"source": "1", "instruction": "make it night"}, _created),
    "enhance": ("/api/enhance", {"source": "1", "workflow_id": "42"}, _created),
    "scene": ("/api/scene", {"scene_id": "s1", "media_ids": ["1"], "preset": "random"},
              _scene_created),
    "fix": ("/api/fix", {"source": "700", "boxes": [FACE]},
            lambda: _Resp(200, {"id": "fix-1"})),
    "video": ("/api/loom/generate", {"mode": "I2V", "images": ["555"], "prompt": "a cat"},
              _created),
}


def _answer_for(kind, outcome):
    if kind == "scene" and outcome == "no-id":
        return _Resp(200, {"data": {"createChatEditingSceneTask": None}})
    if kind == "fix":
        if outcome == "no-id":
            return _Resp(200, {})
        if outcome == "refused":
            return _Resp(403, {"code": "INSUFFICIENT_BALANCE"})
    if outcome == "refused":
        return REFUSED()
    return UNKNOWN[outcome]()


@pytest.mark.parametrize("kind", sorted(ROUTES))
@pytest.mark.parametrize("outcome", sorted(UNKNOWN))
def test_an_unknown_outcome_says_may_have_started_and_holds_the_same_send(rig, kind, outcome):
    route, body, _ok = ROUTES[kind]
    rig["wire"].answer = _answer_for(kind, outcome)
    r = rig["cli"].post(route, json=body)
    d = r.get_json()
    assert not d.get("task_id"), d
    assert d["state"] == "may_have_started" and d["unclear"] is True, d
    assert "may have started" in d["error"] and "not sent again" in d["error"]
    sent = len(rig["wire"].creates())
    assert sent == 1, "exactly one create went out"
    # inside the unclear window -- past the success window -- the same send is held
    rig["clock"][0] += 30
    again = rig["cli"].post(route, json=body)
    a = again.get_json()
    assert again.status_code == 409 and a["unclear"] is True and a["held"] is True
    assert "may still be starting" in a["error"]
    assert len(rig["wire"].creates()) == sent, "the held send sent nothing"
    # a different send is not held
    rig["wire"].answer = ROUTES[kind][2]()
    other = dict(body, prompt="a dog") if kind != "fix" else {"source": "700",
                                                                "boxes": [dict(FACE, x=9)]}
    assert rig["cli"].post(route, json=other).get_json().get("task_id")
    # once the window is over the same send may go again
    rig["clock"][0] += 31
    assert rig["cli"].post(route, json=body).get_json().get("task_id")


@pytest.mark.parametrize("kind", sorted(ROUTES))
def test_a_definite_refusal_drops_the_record(rig, kind):
    route, body, ok = ROUTES[kind]
    rig["wire"].answer = _answer_for(kind, "refused")
    d = rig["cli"].post(route, json=body).get_json()
    assert d["state"] == "refused" and not d.get("unclear"), d
    rig["wire"].answer = ok()
    assert rig["cli"].post(route, json=body).get_json().get("task_id"), "a refusal frees it"
    assert len(rig["wire"].creates()) == 2


@pytest.mark.parametrize("kind", sorted(ROUTES))
def test_a_success_keeps_the_record_for_the_double_tap_window(rig, kind):
    route, body, ok = ROUTES[kind]
    rig["wire"].answer = ok()
    assert rig["cli"].post(route, json=body).get_json().get("task_id")
    again = rig["cli"].post(route, json=body)
    assert again.status_code == 409 and again.get_json()["held"] is True
    assert not again.get_json().get("unclear")
    assert len(rig["wire"].creates()) == 1
    rig["clock"][0] += 11                                 # past the 10 s double-tap window
    assert rig["cli"].post(route, json=body).get_json().get("task_id")
    assert len(rig["wire"].creates()) == 2


@pytest.mark.parametrize("kind", sorted(ROUTES))
def test_the_record_is_claimed_before_the_send(rig, kind):
    """A second identical send that arrives WHILE the first is still out (another tab, a
    retry the browser made) is refused, and only one create goes."""
    route, body, ok = ROUTES[kind]
    inner = {}

    def answer(url, sent):
        if "inner" not in inner:
            inner["inner"] = rig["cli"].post(route, json=body)
        return ok()
    rig["wire"].answer = answer
    assert rig["cli"].post(route, json=body).get_json().get("task_id")
    assert inner["inner"].status_code == 409
    assert len(rig["wire"].creates()) == 1


@pytest.mark.parametrize("kind", ["generate", "edit", "enhance", "video"])
def test_a_failure_before_the_send_is_not_sent_and_drops_the_record(rig, monkeypatch, kind):
    route, body, ok = ROUTES[kind]
    calls = []

    def mirror(s):
        calls.append(1)
        if len(calls) == 1:
            raise core.PixAIError("Mirror mode is on but no mirror session is available")
        return s
    monkeypatch.setattr(mirror_mod, "_session_for_create", mirror)
    d = rig["cli"].post(route, json=body).get_json()
    assert d["state"] == "not_sent" and not d.get("unclear"), d
    assert rig["wire"].creates() == []
    rig["wire"].answer = ok()
    assert rig["cli"].post(route, json=body).get_json().get("task_id")


def test_submit_scene_never_returns_a_missing_task_id(monkeypatch):
    """The coordinator's finding: submit_scene answered None for an id-less answer, so
    /api/scene said task_id null and AI Tools re-armed. It raises now, after the send."""
    wire = Wire()
    wire.answer = _Resp(200, {"data": {"createChatEditingSceneTask": None}})
    seen = []
    with pytest.raises(core.PixAIError) as ei:
        core.submit_scene(pc.PixAIClient(wire), "s1", ["1"], on_send=seen.append)
    assert seen, "the send was reached"
    assert core.send_outcome(ei.value, True) == "may_have_started"
    assert len(wire.posts) == 1


def test_the_journalled_loom_render_keeps_its_own_journal(rig):
    """A Loom render (submit_id) is not held by the single-send record: its journal answers
    it, as before."""
    rig["wire"].answer = requests.ReadTimeout("slow")
    body = dict(ROUTES["video"][1], submit_id="a" * 32,
                loom_target={"board_id": "b" * 32, "card_id": "c" * 32})
    d = rig["cli"].post("/api/loom/generate", json=body).get_json()
    assert d["state"] == "may_have_started" and d["unclear"] is True
    assert "held" not in d
    replay = rig["cli"].post("/api/loom/generate", json=body).get_json()
    assert replay["state"] == "may_have_started" and "held" not in replay   # the journal's answer


# ---------------------------------------------------------------------------
# The CLI runners
# ---------------------------------------------------------------------------

def test_cli_send_once_says_may_have_started_for_an_unknown_outcome():
    for exc in (requests.ReadTimeout("slow"), requests.HTTPError("502"),
                core.PixAIError("no task id returned: {}"),
                core.PixAIRestError("x", 408, {"code": "BAD_REQUEST"})):
        with pytest.raises(core.SendOutcomeUnclear) as ei:
            core._cli_send_once(lambda: (_ for _ in ()).throw(exc))
        assert str(ei.value).startswith(core.CLI_UNCLEAR)
        assert ei.value.__cause__ is exc
        assert not isinstance(ei.value, core.PixAIError)


def test_cli_send_once_passes_a_refusal_and_an_unreached_failure_through():
    refusal = core.graphql_error("not enough credits", code="INSUFFICIENT_BALANCE")
    with pytest.raises(core.PixAIError) as ei:
        core._cli_send_once(lambda: (_ for _ in ()).throw(refusal))
    assert ei.value is refusal
    with pytest.raises(requests.ReadTimeout):
        core._cli_send_once(lambda: (_ for _ in ()).throw(requests.ReadTimeout("x")),
                            reached=lambda: False)


def test_cli_create_once_reads_a_lost_answer_as_unclear_over_the_real_transport():
    wire = Wire()
    wire.answer = requests.ReadTimeout("read timed out")
    with pytest.raises(core.SendOutcomeUnclear):
        core._cli_create_once(pc.PixAIClient(wire), {"modelId": V})
    assert len(wire.posts) == 1, "single attempt"
    wire.answer = _Resp(200, {"data": {"createGenerationTask": None}})
    with pytest.raises(core.SendOutcomeUnclear):
        core._cli_create_once(pc.PixAIClient(wire), {"modelId": V})
    wire.answer = _created("t9")
    assert core._cli_create_once(pc.PixAIClient(wire), {"modelId": V}) == "t9"


@pytest.mark.parametrize("runner", ["run_generate_video", "run_reference_video", "run_edit_image"])
def test_each_cli_runner_sends_through_the_unclear_wrapper(runner):
    """Each of the three gql_mutate runners sends its one create through _cli_create_once,
    and run_generate through _cli_send_once (source pin: the wrapper is what turns a lost
    answer into the honest sentence)."""
    import inspect
    src = inspect.getsource(getattr(core, runner))
    assert "_cli_create_once(" in src and "gql_mutate(" not in src
    assert "_cli_send_once(" in inspect.getsource(core.run_generate)


def test_run_generate_exits_with_the_honest_sentence(tmp_path, monkeypatch, capsys):
    """End to end: --generate --confirm over a mocked Session whose create times out prints
    the may-have-started sentence and exits non-zero, after exactly one create."""
    wire = Wire()
    wire.answer = requests.ReadTimeout("read timed out")
    client = pc.PixAIClient(wire)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: client)
    monkeypatch.setattr(mirror_mod, "_session_for_create", lambda s: s)
    monkeypatch.setattr(models_mod, "_gate_image_params", lambda s, p: (p, []))
    monkeypatch.setattr(models_mod, "_gate_params_for_model", lambda s, p: p)
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(gen_params_mod, "_gen_parameters", lambda args: {"modelId": V, "prompts": "x"})
    import argparse
    args = argparse.Namespace(out=str(tmp_path), confirm=True, task_id="", token=None,
                              poll_timeout=1)
    with pytest.raises(core.SendOutcomeUnclear) as ei:
        core.run_generate(args)
    assert core.CLI_UNCLEAR in str(ei.value)
    assert len(wire.creates()) == 1


def test_main_exits_non_zero_with_the_sentence():
    """main()'s outer handler turns SendOutcomeUnclear into sys.exit(message), like a
    PixAIError (source pin: running main() needs a whole library)."""
    import inspect
    src = inspect.getsource(core.main)
    assert "except (PixAIError, SendOutcomeUnclear) as e:\n        sys.exit(str(e))" in src

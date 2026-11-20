"""3.21.2 adversarial review of the L1/L2/L3 fixes: the regressions it found, pinned.

  1. A GraphQL `errors` answer with no data was read "refused" whatever its code, so an
     INTERNAL_SERVER_ERROR or an "upstream request timeout" dropped the repeat hold and a second
     identical send went out. It is a refusal only when every error names a definite code.
  3. An unclear answer carries PixAI's own reason (`detail`); a refusal that IS definite never
     says "may have started".
  4. A send that succeeded and then failed in its bookkeeping answers its task id.
  5. An SVG counts as whole only when it ends with </svg>.
The reviewer's probes (scratchpad review_live/test_probe_live.py, P1-P5) are the first block,
turned round to assert the fixed behaviour. The transport is the real PixAIClient over the
mocked Session of test_unclear_single_sends."""
import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import integrity as integ
from moonglade import models as models_mod
from tests.test_unclear_single_sends import ROUTES, _Resp, rig  # noqa: F401  (rig is a fixture)

INTERNAL = lambda: _Resp(200, {"errors": [{"message": "Internal server error",
                                           "extensions": {"code": "INTERNAL_SERVER_ERROR"}}],
                               "data": None})
TIMEOUT_GQL = lambda: _Resp(200, {"errors": [{"message": "upstream request timeout"}], "data": None})
PRISMA = lambda: _Resp(200, {"errors": [{"message": "Internal server error", "extensions": {
    "code": "INTERNAL_SERVER_ERROR", "exception": {"name": "PrismaClientUnknownRequestError"}}}],
    "data": None})


# ---- the reviewer's probes, fixed --------------------------------------------------------

@pytest.mark.parametrize("ans", [INTERNAL, TIMEOUT_GQL, PRISMA],
                         ids=["internal", "upstream-timeout", "prisma"])
@pytest.mark.parametrize("kind", ["generate", "edit", "enhance", "scene", "video"])
def test_P1_a_graphql_server_error_is_unclear_and_holds_the_same_send(rig, kind, ans):
    route, body, ok = ROUTES[kind]
    rig["wire"].answer = lambda u, j: ans()
    r1 = rig["cli"].post(route, json=body).get_json()
    assert r1["state"] == "may_have_started" and r1["unclear"] is True, r1
    rig["wire"].answer = lambda u, j: ok()
    r2 = rig["cli"].post(route, json=body)
    assert r2.status_code == 409 and r2.get_json()["unclear"] is True
    assert len(rig["wire"].creates()) == 1, "the second identical send went nowhere"


def test_P2_a_blank_seed_repeat_after_a_success_is_held(rig):
    route, body, ok = ROUTES["generate"]
    rig["wire"].answer = lambda u, j: ok()
    rig["cli"].post(route, json=dict(body, seed=None))
    rig["clock"][0] += 3
    b = rig["cli"].post(route, json=dict(body, seed=None))
    assert b.status_code == 409 and len(rig["wire"].creates()) == 1


@pytest.mark.parametrize("code,status", [("NSFW_DETECTED", 403), ("INPUT_IMAGE_TOO_LARGE", 400)])
def test_P3_a_fix_nsfw_or_size_answer_is_unclear_with_pixais_reason(rig, code, status):
    """Neither code is in PixAI's rejected list, so the Fix may exist: it holds, and the answer
    says why in PixAI's words."""
    route, body, ok = ROUTES["fix"]
    rig["wire"].answer = lambda u, j: _Resp(status, {"code": code, "message": "nope"})
    a = rig["cli"].post(route, json=body).get_json()
    assert a["state"] == "may_have_started" and code in a["detail"]
    rig["clock"][0] += 30
    assert rig["cli"].post(route, json=body).status_code == 409


def test_P5_a_bare_401_on_fix_is_unclear_and_names_the_401(rig):
    route, body, ok = ROUTES["fix"]
    rig["wire"].answer = lambda u, j: _Resp(401, "Unauthorized")
    a = rig["cli"].post(route, json=body).get_json()
    assert a["state"] == "may_have_started" and "401" in a["detail"]


# ---- 1: the GraphQL rule ------------------------------------------------------------------

@pytest.mark.parametrize("err,want", [
    ({"message": "x", "extensions": {"exception": {"name": "INSUFFICIENT_BALANCE"}}}, "refused"),
    ({"message": "x", "extensions": {"code": "REQUIRE_MEMBERSHIP"}}, "refused"),
    ({"message": "Only member can use turbo mode", "code": 40300047}, "refused"),
    ({"message": "x", "extensions": {"code": "BAD_REQUEST"}}, "refused"),
    ({"message": "x", "extensions": {"code": "INVALID_PARAMETERS_COMPATIBILITY"}}, "refused"),
    ({"message": "INSUFFICIENT_BALANCE"}, "unknown"),                      # words are not a code
    ({"message": "x", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}, "unknown"),
    ({"message": "x", "extensions": {"code": "NSFW_DETECTED"}}, "unknown"),
    ({"message": "x", "code": 40300032}, "unknown"),                         # NSFW_DETECTED's number
    ({"message": "x", "extensions": {"code": "BAD_REQUEST",
                                     "exception": {"name": "PrismaClientKnownRequestError"}}},
     "unknown"),                                                             # the site reads the name
])
def test_a_graphql_error_is_a_refusal_only_by_a_definite_code(err, want):
    assert core.classify_outcome(core.graphql_error([err])) == want


def test_every_error_must_carry_a_definite_code():
    ok = {"message": "a", "extensions": {"code": "BAD_REQUEST"}}
    bad = {"message": "b", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}
    assert core.classify_outcome(core.graphql_error([ok, ok])) == "refused"
    assert core.classify_outcome(core.graphql_error([ok, bad])) == "unknown"
    assert core.classify_outcome(core.graphql_error([ok, {"message": "c"}])) == "unknown"


def test_the_two_resubmits_still_fire_on_their_coded_refusals(monkeypatch):
    """The inferenceProfile drop (BAD_REQUEST / INVALID_PARAMETERS_COMPATIBILITY) and the Turbo
    fallback (REQUIRE_MEMBERSHIP / 40300047) keep working on a coded refusal, and neither
    fires on an uncoded one."""
    monkeypatch.setattr(core, "_check_read_only", lambda *a: None)
    monkeypatch.setattr(core._mirror, "_session_for_create", lambda s: s)
    monkeypatch.setattr(models_mod, "_gate_params_for_model", lambda s, p: p)
    monkeypatch.setattr(models_mod, "_profile_listing", lambda s, p: (False, False))
    monkeypatch.setitem(core._turbo_refused, "seen", False)
    cases = [({"prompts": "a", "modelId": "1", "inferenceProfile": "pro"},
              {"message": "unknown inferenceProfile", "extensions": {"code": "BAD_REQUEST"}}),
             ({"prompts": "a", "modelId": "1", "priority": core.PRIORITY_TURBO},
              {"message": "Only member can use turbo mode", "code": 40300047})]
    for params, err in cases:
        sent = []

        def mutate(s, q, v=None, _err=err):
            sent.append(dict(v["parameters"]))
            if len(sent) == 1:
                raise core.graphql_error([_err])
            return {"createGenerationTask": {"id": "T2"}}
        monkeypatch.setattr(core, "gql_mutate", mutate)
        assert core.submit_generation(object(), dict(params)) == "T2"
        assert len(sent) == 2
        uncoded = dict(err)
        uncoded.pop("extensions", None)
        uncoded.pop("code", None)
        sent.clear()
        monkeypatch.setattr(core, "gql_mutate",
                            lambda s, q, v=None, _e=uncoded: sent.append(1) or
                            (_ for _ in ()).throw(core.graphql_error([_e])))
        with pytest.raises(core.PixAIError):
            core.submit_generation(object(), dict(params))
        assert len(sent) == 1, "no resubmit after an uncoded (unknown) answer"


# ---- 3: a definite refusal never says "may have started" ---------------------------------

@pytest.mark.parametrize("code,status", [("INSUFFICIENT_BALANCE", 403), ("BAD_REQUEST", 400),
                                         ("TOO_MANY_REQUESTS", 429)])
def test_a_definite_fix_refusal_is_a_refusal_not_may_have_started(rig, code, status):
    route, body, ok = ROUTES["fix"]
    rig["wire"].answer = lambda u, j: _Resp(status, {"code": code})
    a = rig["cli"].post(route, json=body).get_json()
    assert a["state"] == "refused" and not a.get("unclear")
    assert "may have started" not in a["error"].lower()


def test_outcome_reason_words():
    assert core.outcome_reason(core.PixAIRestError("x", 403, {"code": "NSFW_DETECTED",
                                                              "message": "flagged"})) == \
        "HTTP 403: NSFW_DETECTED -- flagged"
    assert "401" in core.outcome_reason(core.PixAIRestError("REST POST /x -> 401: no", 401, None))
    assert core.outcome_reason(core.graphql_error(
        [{"message": "Internal server error", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}])) \
        == "Internal server error (INTERNAL_SERVER_ERROR)"


# ---- 4: bookkeeping after a success never turns it into "may have started" ----------------

def _boom(*a, **k):
    raise OSError("disk full")


@pytest.mark.parametrize("kind", ["generate", "edit", "fix"])
def test_a_bookkeeping_failure_after_a_success_answers_the_task_id(rig, monkeypatch, kind):
    """The task exists: the answer is its id (so the job is registered), the failure is
    logged, and the record stays "sent" -- never "may have started"."""
    route, body, ok = ROUTES[kind]
    rig["wire"].answer = lambda u, j: ok()
    if kind == "generate":
        # generate's first step after the send that reads the request: the clamp receipt
        from tests.test_unclear_single_sends import _Req

        class _Raising(_Req):
            @property
            def adjusted(self):
                raise OSError("disk full")

            @adjusted.setter
            def adjusted(self, v):
                pass
        monkeypatch.setattr(core, "build_request", lambda payload, *a, mode=None, **k: _Raising("image"))
    else:
        from moonglade import telemetry as telemetry_mod
        monkeypatch.setattr(telemetry_mod, "telem_set_add", _boom)
    d = rig["cli"].post(route, json=body).get_json()
    assert d.get("task_id"), d
    assert not d.get("unclear") and "error" not in d
    again = rig["cli"].post(route, json=body)
    assert again.status_code == 409 and not again.get_json().get("unclear"), "kept as sent"
    assert len(rig["wire"].creates()) == 1


# ---- 5: an SVG is whole only when closed ---------------------------------------------------

@pytest.mark.parametrize("data,whole", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', True),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n\n  ', True),
    (b'<?xml version="1.0"?>\n<svg><rect/></SVG>\r\n', True),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="64" hei', False),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', False),
])
def test_an_svg_must_end_with_its_closing_tag(tmp_path, data, whole):
    f = tmp_path / "x_1.svg"
    f.write_bytes(data)
    assert (integ.structural_problem(f) is None) is whole
    assert integ.verified_whole(f) is whole

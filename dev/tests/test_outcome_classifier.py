"""3.21.2, L2 (DESIGN_3.22 "Live in master today", 2.6): the outcome classifier reads the
exception's TYPE and structured fields, never its message text.

definite_refusal counted every REST 4xx as "nothing was created" -- 408 and 499 included, and
an edge's 4xx with no PixAI body -- so a 408 on an advanced training submit released the paid
guard and invited a second paid run. Now a REST answer is a refusal only when its status is a
4xx other than 408/499 AND its body is PixAI's oRPC error with a code in DEFINITE_CODES
(PixAI's own rejected list plus three pre-submit codes); everything else is unknown."""
import pytest
import requests

from moonglade import backup as core
from moonglade import pixai_client as pc

DECLARED_OUTSIDE = ["FILE_NOT_FOUND", "NOT_FOUND", "LORA_NUM_EXCEEDED", "MODEL_LORA_INCOMPATIBLE",
                    "IMAGE_SIZE_NOT_ALLOWED", "INPUT_IMAGE_TOO_LARGE", "NSFW_DETECTED",
                    "KAISUUKEN_MATCH_PARAMS_INVALID", "KAISUUKEN_INSUFFICIENT",
                    "KAISUUKEN_SETTINGS_NOT_COVERED", "KAISUUKEN_EXTRA_CREDITS_REQUIRED",
                    "REMIX_UNAVAILABLE", "CREATION_FAILED", "INVALID_ARGUMENT"]


def _rest(status, body):
    return core.PixAIRestError("REST POST /x -> %s" % status, status=status, body=body)


def test_definite_codes_are_pixais_twenty_and_three_pre_submit_codes():
    assert len(core.PIXAI_REJECTED_CODES) == 20
    assert core.DEFINITE_CODES - core.PIXAI_REJECTED_CODES == {
        "UNAUTHORIZED", "VALIDATION_ERROR", "INFINITE_MODE_NOT_ELIGIBLE"}


@pytest.mark.parametrize("code", sorted(core.DEFINITE_CODES))
def test_each_definite_code_reads_refused(code):
    assert core.classify_outcome(_rest(403, {"code": code})) == "refused"
    assert core.definite_refusal(_rest(400, {"code": code, "data": {}}))


@pytest.mark.parametrize("code", DECLARED_OUTSIDE)
def test_each_declared_code_outside_the_list_reads_unknown(code):
    assert core.classify_outcome(_rest(400, {"code": code})) == "unknown"
    assert not core.definite_refusal(_rest(404, {"code": code}))


@pytest.mark.parametrize("status", [408, 499])
@pytest.mark.parametrize("code", ["INSUFFICIENT_BALANCE", "BAD_REQUEST", "UNAUTHORIZED"])
def test_408_and_499_are_unknown_even_with_a_well_formed_body(status, code):
    assert core.classify_outcome(_rest(status, {"code": code})) == "unknown"


@pytest.mark.parametrize("body", [None, "<html>Forbidden</html>", {}, {"code": ""},
                                  {"code": 40300010}, {"message": "INSUFFICIENT_BALANCE"},
                                  ["INSUFFICIENT_BALANCE"]])
def test_a_bare_or_unrecognised_4xx_body_is_unknown(body):
    assert core.classify_outcome(_rest(403, body)) == "unknown"


@pytest.mark.parametrize("status", [301, 307, 500, 502, 503, None, "x"])
def test_redirects_server_errors_and_no_status_are_unknown(status):
    assert core.classify_outcome(_rest(status, {"code": "INSUFFICIENT_BALANCE"})) == "unknown"


def test_any_code_is_only_for_the_inbox_and_still_excludes_408_499_and_bare():
    assert core.definite_refusal(_rest(409, {"code": "ALREADY_CLAIMED"}), codes=core.ANY_PIXAI_CODE)
    assert not core.definite_refusal(_rest(409, {"code": "ALREADY_CLAIMED"}))
    assert not core.definite_refusal(_rest(408, {"code": "X"}), codes=core.ANY_PIXAI_CODE)
    assert not core.definite_refusal(_rest(403, None), codes=core.ANY_PIXAI_CODE)


def test_local_auth_and_graphql_are_read_by_type():
    assert core.classify_outcome(core.LocalRefusal("READ_ONLY")) == "local"
    assert core.classify_outcome(core.PixAIAuthError("401 Unauthorized")) == "refused"
    assert core.classify_outcome(core.graphql_error([{"message": "no"}])) == "refused"
    partial = core.graphql_error([{"message": "late"}], {"createGenerationTask": {"id": "1"}})
    assert core.classify_outcome(partial) == "unknown"
    for exc in (requests.ReadTimeout("x"), requests.ConnectionError("x"),
                requests.HTTPError("502"), core.PixAIError("no task id returned: {}"),
                ValueError("x")):
        assert core.classify_outcome(exc) == "unknown"


@pytest.mark.parametrize("text", [
    "GraphQL error: [{\"message\": \"INSUFFICIENT_BALANCE\"}]",   # the old GraphQL prefix
    "401 Unauthorized -- API key missing/expired.",                 # the old 401 prefix
    "REST POST /task/fixer -> 403: refused INSUFFICIENT_BALANCE",
])
def test_message_text_never_decides(text):
    """A plain PixAIError whose words match the old prefixes is not a refusal: only the
    structured fields the transport sets are read."""
    assert core.classify_outcome(core.PixAIError(text)) == "unknown"
    assert core.send_outcome(core.PixAIError(text), True) == "may_have_started"


def test_the_real_transport_raises_the_typed_errors():
    class _R:
        def __init__(self, status, body):
            self.status_code, self._b, self.ok = status, body, 200 <= status < 300
            self.text = str(body)

        def json(self):
            return self._b

    class _S:
        def __init__(self, r):
            self.r = r

        def post(self, *a, **k):
            return self.r

    with pytest.raises(core.PixAIAuthError):
        pc.PixAIClient(_S(_R(401, {}))).mutate("mutation { x }", {})
    with pytest.raises(core.PixAIError) as ei:
        pc.PixAIClient(_S(_R(200, {"errors": [{"message": "no"}], "data": None}))).mutate(
            "mutation { x }", {})
    assert ei.value.graphql_errors == [{"message": "no"}]
    assert core.definite_refusal(ei.value)
    with pytest.raises(core.PixAIRestError) as ei:
        pc.PixAIClient(_S(_R(408, {"code": "BAD_REQUEST"}))).rest_post("/x", {})
    assert not core.definite_refusal(ei.value)


def test_send_outcome():
    assert core.send_outcome(requests.ReadTimeout("x"), False) == "not_sent"
    assert core.send_outcome(requests.ReadTimeout("x"), True) == "may_have_started"
    assert core.send_outcome(_rest(403, {"code": "INSUFFICIENT_BALANCE"}), True) == "refused"
    e = core.PixAIError("PixAI refused the ultra profile")
    e.refused = True
    assert core.send_outcome(e, True) == "refused"


# ---------------------------------------------------------------------------
# The callers: the paid training guards, the run sender, the lane branch
# ---------------------------------------------------------------------------

def test_the_lane_branch_reads_the_graphql_attributes_not_the_prefix(monkeypatch):
    """submit_generation's lane branch turns a definite GraphQL refusal into the lane's
    words; a plain PixAIError shaped like one is passed on as it came (unknown)."""
    monkeypatch.setattr(core, "_check_read_only", lambda *a: None)
    monkeypatch.setattr(core._mirror, "_session_for_create", lambda s: s)
    monkeypatch.setattr(core, "_gate_params_for_model", lambda s, p: p)
    lane = {"modelId": "1", "prompts": "x", "lane": "infinite"}
    fake_text = core.PixAIError('GraphQL error: [{"message": "no"}]')
    monkeypatch.setattr(core, "gql_mutate", lambda *a, **k: (_ for _ in ()).throw(fake_text))
    with pytest.raises(core.PixAIError) as ei:
        core.submit_generation(object(), dict(lane))
    assert ei.value is fake_text and not getattr(ei.value, "refused", False)
    real = core.graphql_error([{"message": "no"}])
    monkeypatch.setattr(core, "gql_mutate", lambda *a, **k: (_ for _ in ()).throw(real))
    with pytest.raises(core.PixAIError) as ei:
        core.submit_generation(object(), dict(lane))
    assert ei.value.refused is True

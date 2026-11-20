"""The gallery's spend rules as plain gen_road functions (DESIGN_3.22 3.4, step S2b).

The routes' own behaviour is pinned by test_single_send_quoted_free.py,
test_quoted_free_more_roads.py and test_unclear_single_sends.py; this file pins the functions
the routes now call, with no Flask app in the way. Nothing here touches the network.
"""
import pytest

from moonglade import backup as core
from moonglade import gen_road


# --- the FREE-quote rule --------------------------------------------------------------------

def test_pop_expect_free_pops_the_flag_and_never_raises():
    body = {"prompt": "a cat", "expect_free": True}
    assert gen_road.pop_expect_free(body) is True
    assert body == {"prompt": "a cat"}
    assert gen_road.pop_expect_free({"prompt": "x"}) is False
    assert gen_road.pop_expect_free(None) is False
    assert gen_road.pop_expect_free(["not", "a", "dict"]) is False


def test_a_send_quoted_free_goes_out_only_with_a_card():
    with pytest.raises(core.LocalRefusal) as ei:
        gen_road.refuse_if_quoted_free_gone({"prompts": "a cat"})
    assert str(ei.value) == gen_road.QUOTED_FREE_GONE
    gen_road.refuse_if_quoted_free_gone({"kaisuukenId": "K1"})          # passes
    with pytest.raises(core.LocalRefusal, match="the Loom's words"):
        gen_road.refuse_if_quoted_free_gone({}, "the Loom's words")


def test_quoted_free_hooks():
    req = gen_road.GenerationRequest(mode="image", parameters={"prompts": "a cat"})
    assert gen_road.quoted_free_hooks(req, False) == {}
    hooks = gen_road.quoted_free_hooks(req, True)
    with pytest.raises(core.LocalRefusal):
        hooks["before_send"]({"prompts": "a cat"})
    hooks["before_send"]({"prompts": "a cat", "kaisuukenId": "K1"})
    lane = gen_road.GenerationRequest(mode="image", parameters={"lane": "infinite"},
                                      unlimited=True)
    assert gen_road.quoted_free_hooks(lane, True) == {}      # free by the entitlement

# --- the repeat hold (V1) ---------------------------------------------------------------------

@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(gen_road.time, "monotonic", lambda: now[0])
    return now


def test_the_record_is_claimed_before_the_send_and_holds_while_it_is_out(clock):
    key = gen_road.repeat_key("u", "image", {"prompt": "a cat"})
    assert gen_road.repeat_claim(key, claim=False) is None      # a check claims nothing
    assert gen_road.repeat_claim(key) is None                   # claimed
    assert gen_road.repeat_claim(key) == "sending"              # an overlapping send is held
    clock[0] += gen_road.REPEAT_UNCLEAR_S - 1
    assert gen_road.repeat_claim(key) == "sending"              # never settled: held 60 s


def test_a_success_holds_ten_seconds_and_an_unknown_sixty(clock):
    a = gen_road.repeat_key("u", "image", {"prompt": "a cat"})
    b = gen_road.repeat_key("u", "image", {"prompt": "a dog"})
    for k in (a, b):
        gen_road.repeat_claim(k)
    gen_road.repeat_settle(a, "sent")
    gen_road.repeat_settle(b, "may_have_started")
    clock[0] += 2
    assert gen_road.repeat_claim(a) == "sent"                   # a tap 2 s after a success
    clock[0] += 9
    assert gen_road.repeat_claim(a, claim=False) is None        # past the 10 s window
    assert gen_road.repeat_claim(b) == "unclear"
    clock[0] += 50
    assert gen_road.repeat_claim(b, claim=False) is None        # past the 60 s window


@pytest.mark.parametrize("state", ["not_sent", "refused"])
def test_only_a_proven_no_cost_outcome_drops_the_record(clock, state):
    k = gen_road.repeat_key("u", "fix", {"mediaId": "1"})
    gen_road.repeat_claim(k)
    gen_road.repeat_settle(k, state)
    assert gen_road.repeat_claim(k, claim=False) is None


def test_any_other_state_keeps_the_record_as_unclear(clock):
    k = gen_road.repeat_key("u", "fix", {"mediaId": "1"})
    gen_road.repeat_claim(k)
    gen_road.repeat_settle(k, "something new")
    assert gen_road.repeat_claim(k) == "unclear"


def test_the_failure_settle_reads_the_classifier_never_the_text(clock):
    import requests
    k = gen_road.repeat_key("u", "image", {"prompt": "x"})
    gen_road.repeat_claim(k)
    # an unknown outcome whose MESSAGE says it was refused still holds
    e = requests.ReadTimeout("REQUIRE_MEMBERSHIP refused: nothing was charged")
    assert gen_road.repeat_settle_failure(k, e, True) == "may_have_started"
    assert gen_road.repeat_claim(k) == "unclear"
    k2 = gen_road.repeat_key("u", "image", {"prompt": "y"})
    gen_road.repeat_claim(k2)
    refused = core.PixAIRestError("x", status=400, body={"code": "INSUFFICIENT_BALANCE"})
    assert gen_road.repeat_settle_failure(k2, refused, True) == "refused"
    assert gen_road.repeat_claim(k2, claim=False) is None
    k3 = gen_road.repeat_key("u", "image", {"prompt": "z"})
    gen_road.repeat_claim(k3)
    assert gen_road.repeat_settle_failure(k3, refused, False) == "not_sent"


def test_the_key_is_per_user_kind_and_payload():
    base = gen_road.repeat_key("u", "image", {"a": 1, "b": 2})
    assert base == gen_road.repeat_key("u", "image", {"b": 2, "a": 1})
    assert base != gen_road.repeat_key("v", "image", {"a": 1, "b": 2})
    assert base != gen_road.repeat_key("u", "edit", {"a": 1, "b": 2})
    assert gen_road.repeat_key("u", "image", {"x": object()})      # never raises

# --- the Inspector's request record -----------------------------------------------------------

def test_the_request_record_names_the_road_the_kind_rides(monkeypatch):
    p = {"prompts": "a cat", "isPrivate": True}
    monkeypatch.setitem(gen_road.CREATE_ROAD, "image", "graphql")
    assert gen_road.request_record("image", p) == {
        "operation": "createGenerationTask", "variables": {"parameters": p}}
    monkeypatch.setitem(gen_road.CREATE_ROAD, "image", "rest")
    rec = gen_road.request_record("image", p)
    assert rec["operation"] == "task.createTask"
    assert rec["route"] == "POST /v2/task/create"
    assert rec["dropped"] == ["isPrivate"]
    assert rec["variables"] == {"parameters": p}                # the Inspector's reader key
    assert gen_road.request_record("video", {"i2vPro": {}})["operation"] == \
        "createGenerationTask"

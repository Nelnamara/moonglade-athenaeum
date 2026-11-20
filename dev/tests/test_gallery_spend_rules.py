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

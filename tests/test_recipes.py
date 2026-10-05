"""Recipes (lane w2-recipes, Session K + H3/H8/H10): the one build step that adds
`recipeIds` to a generation, the price and send guards around it, PixAI's RECIPE_* refusals
read into a structured answer, the read routes' shapes, and every write's guards (CSRF,
READ_ONLY, single attempt, never a write on open).

Design and its adversarial review: moonglade-internal/design/notes/recipes/BUILD-w2-recipes.md.
No network: `_rest_get` / `_rest_post` are the conftest's blockers unless a test swaps in a
fake, and `moonglade_recipes._rest_delete` is blocked the same way. Tier enforcement for the
new routes is asserted by tests/test_route_tiers.py's snapshot.
"""
import json

import pytest

from moonglade import backup as core
from moonglade import recipes as rec
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import login_client, login_test_client
from tests.fake_pixai import FakePixAI

RID = "2046394714775712134"
RID2 = "2046394714775712135"
# PixAI's collection ids and collection-item ids are UUID strings (probe 2026-10-03, #78), not
# the numeric ids every other recipe route takes. Made-up values in the live shape.
SET_ID = "01a0c2f4-6e88-7b10-9c3d-5e7f8a9b0c1d"
ITEM_ID = "01a0c2f4-7a21-7c44-8d55-6e7f8091a2b3"


def _refused(code, reason, ids):
    e = core.PixAIError("GraphQL error: [...]")
    e.graphql_errors = [{"message": "Recipe is incompatible with this task",
                         "extensions": {"code": "UNPROCESSABLE",
                                        "exception": {"name": code, "recipeIds": ids,
                                                      "reason": reason}}}]
    return e


# ---------------------------------------------------------------------------
# The payload's recipeIds: parsed, never trimmed, dropped or deduplicated
# ---------------------------------------------------------------------------

def test_no_recipes_leaves_the_params_object_untouched():
    params = {"modelId": "1", "prompts": "x"}
    for payload in ({}, {"recipeIds": None}, {"recipeIds": []}):
        assert rec.apply_to_params(params, payload) is params


def test_recipes_ride_as_a_copy_in_the_order_sent():
    params = {"modelId": "1"}
    out = rec.apply_to_params(params, {"recipeIds": [RID2, RID]})
    assert out == {"modelId": "1", "recipeIds": [RID2, RID]}
    assert "recipeIds" not in params


@pytest.mark.parametrize("bad", [
    [int(RID)],            # a number: an 18-19 digit JS number arrives rounded
    [True], [1.5], ["0123"], ["abc"], [""], ["12 34"], "2046394714775712134", {"a": 1},
])
def test_anything_but_digit_strings_refuses(bad):
    with pytest.raises(core.PixAIError):
        rec.recipe_ids_from({"recipeIds": bad})


def test_a_duplicate_refuses_rather_than_deduplicating():
    with pytest.raises(core.PixAIError, match="twice"):
        rec.recipe_ids_from({"recipeIds": [RID, RID]})


def test_more_than_ten_refuses_and_names_how_many_to_remove():
    ids = [str(2046394714775712100 + i) for i in range(12)]
    with pytest.raises(core.PixAIError, match="remove 2"):
        rec.recipe_ids_from({"recipeIds": ids})
    assert len(rec.recipe_ids_from({"recipeIds": ids[:10]})) == 10


@pytest.mark.parametrize("params,match", [
    ({"modelId": "1", "contextImages": ["9"]}, "held while context images"),
    ({"modelId": "1", "lane": "infinite"}, "Unlimited Mode"),
    ({"modelId": "1", "mediaId": "9", "enlarge": 2}, "upscale"),
    ({"modelId": "1", "mediaId": "9", "upscale": 1.5}, "upscale"),
])
def test_forbidden_combinations_refuse_at_build(params, match):
    with pytest.raises(core.PixAIError, match=match):
        rec.apply_to_params(params, {"recipeIds": [RID]})


def test_a_road_without_the_gate_cannot_vouch_for_recipes():
    with pytest.raises(core.PixAIError, match="can't check a recipe"):
        rec.apply_to_params({"modelId": "1"}, {"recipeIds": [RID]}, gated=False)
    # ...and a payload with none still builds on it, untouched
    p = {"modelId": "1"}
    assert rec.apply_to_params(p, {}, gated=False) is p


# ---------------------------------------------------------------------------
# build_request: one dict for the quote and the spend
# ---------------------------------------------------------------------------

def _resolver(gate=True):
    return core.RequestResolver(
        model_version=lambda mid, vid="": "1983308862240288769",
        gate=(lambda params: (params, [])) if gate else None)


def test_build_request_carries_the_recipes_through_the_gate():
    req = core.build_request({"version_id": "1983308862240288769", "prompt": "a moon",
                              "recipeIds": [RID]}, mode="image", resolve=_resolver())
    assert req.parameters["recipeIds"] == [RID]
    assert req.parameters["modelId"] == "1983308862240288769"


def test_build_request_without_recipes_is_byte_identical():
    base = {"version_id": "1983308862240288769", "prompt": "a moon"}
    a = core.build_request(dict(base), mode="image", resolve=_resolver())
    b = core.build_request(dict(base, recipeIds=[]), mode="image", resolve=_resolver())
    assert a.parameters == b.parameters and "recipeIds" not in a.parameters


def test_build_request_refuses_recipes_on_a_gateless_road():
    with pytest.raises(core.PixAIError, match="can't check a recipe"):
        core.build_request({"version_id": "1983308862240288769", "prompt": "x",
                            "recipeIds": [RID]}, mode="image", resolve=_resolver(gate=False))


def test_unlimited_mode_still_refuses_a_recipe(monkeypatch):
    """The recipe step runs BEFORE the lane check, so _unlimited_check sees recipeIds."""
    seen = {}

    def lane_check(params, vid):
        seen["params"] = params
        raise core.PixAIError("Unlimited Mode can't use a workflow or a recipe")
    rs = core.RequestResolver(model_version=lambda m, v="": "1983308862240288769",
                              gate=lambda p: (p, []), unlimited=lane_check)
    with pytest.raises(core.PixAIError, match="recipe"):
        core.build_request({"version_id": "1983308862240288769", "prompt": "x",
                            "unlimited": True, "recipeIds": [RID]}, mode="image", resolve=rs)
    assert seen["params"]["recipeIds"] == [RID]


# ---------------------------------------------------------------------------
# Price: recipeIds in the query; a failed recipe quote is refused or unverified, never FREE
# ---------------------------------------------------------------------------

def test_task_price_query_carries_recipe_ids_as_json(monkeypatch):
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen["params"] = params
        return {"actualPrice": 3100}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    assert core.price_task(object(), {"modelId": "1", "recipeIds": [RID, RID2]}) == 3100
    assert seen["params"]["recipeIds"] == json.dumps([RID, RID2])


def _req(params):
    return core.GenerationRequest(mode="image", parameters=params, model_version_id="1")


def _no_card(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the card check must not run for this quote")
    monkeypatch.setattr(core, "match_kaisuuken", boom)


def test_a_recipe_422_on_the_quote_becomes_the_structured_refusal(monkeypatch):
    err = core.PixAIError('REST GET /task-price -> 422: {"code":"RECIPE_INCOMPATIBLE"}')
    err.body = {"defined": True, "code": "RECIPE_INCOMPATIBLE", "status": 422,
                "data": {"recipeIds": [RID], "reason": "model_mismatch"}}

    def fake_get(*a, **k):
        raise err
    monkeypatch.setattr(core, "_rest_get", fake_get)
    _no_card(monkeypatch)
    out = core.price(object(), _req({"modelId": "1", "recipeIds": [RID]}))
    assert out["cost"] is None and out["free"] is False
    r = out["recipe_error"]
    assert r["code"] == "RECIPE_INCOMPATIBLE" and r["reason"] == "model_mismatch"
    assert r["recipe_ids"] == [RID] and r["group"] == "model"
    assert out["note"] == r["copy"]


def test_a_recipe_quote_that_fails_otherwise_is_unverified_and_never_free(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("timeout")))
    _no_card(monkeypatch)
    out = core.price(object(), _req({"modelId": "1", "recipeIds": [RID]}))
    assert out == {"cost": None, "free": False,
                   "note": "couldn't verify the price with these recipes"}


def test_a_quote_without_recipes_keeps_todays_card_behaviour(monkeypatch):
    monkeypatch.setattr(core, "price_task", lambda s, p: None)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda *a, **k: {"id": "k1", "total": 3, "consumeAmount": 1,
                                         "covered": True, "name": "Tsubaki"})
    out = core.price(object(), _req({"modelId": "1"}))
    assert out["free"] is True and "card_note" not in out


def test_a_card_over_a_priced_recipe_quote_carries_the_note(monkeypatch):
    monkeypatch.setattr(core, "price_task", lambda s, p: 3000)
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda *a, **k: {"id": "k1", "total": 3, "consumeAmount": 1,
                                         "covered": True, "name": "Tsubaki"})
    out = core.price(object(), _req({"modelId": "1", "recipeIds": [RID]}))
    assert out["free"] is True and out["cost"] == 3000
    assert out["card_note"] == rec.CARD_NOTE


# ---------------------------------------------------------------------------
# The send: the backstop, and a recipe refusal is never resubmitted
# ---------------------------------------------------------------------------

def test_the_send_refuses_recipes_beside_context_images(monkeypatch):
    """The build saw a plain reference; the backstop gate converted it late. Nothing is
    sent (review finding 1)."""
    fake = FakePixAI()
    monkeypatch.setattr(core, "_gate_params_for_model",
                        lambda s, p: dict({k: v for k, v in p.items() if k != "mediaId"},
                                          contextImages=[p["mediaId"]]))
    with pytest.raises(core.PixAIError, match="held while context images"):
        core.submit_generation(fake, {"modelId": "1", "mediaId": "9", "recipeIds": [RID]})
    assert not [c for c in fake.calls if c.verb == "mutate"]


def test_the_send_refuses_a_malformed_recipe_list():
    fake = FakePixAI()
    with pytest.raises(core.PixAIError):
        core.submit_generation(fake, {"modelId": "1", "recipeIds": [int(RID)]})
    assert not [c for c in fake.calls if c.verb == "mutate"]


def test_a_recipe_refusal_is_never_resubmitted_whatever_its_words(monkeypatch):
    """Even a refusal whose text says inferenceProfile goes out ONCE (review finding 4)."""
    fake = FakePixAI()
    err = _refused("RECIPE_INCOMPATIBLE", "mutually_exclusive_feature", [RID])
    err.args = ("GraphQL error: inferenceProfile clashes with a recipe",)
    fake.fail("createGenerationTask", err)
    monkeypatch.setattr(core, "_gate_params_for_model", lambda s, p: p)
    with pytest.raises(core.PixAIError):
        core.submit_generation(fake, {"modelId": "1", "inferenceProfile": "pro",
                                      "recipeIds": [RID]})
    assert len([c for c in fake.calls if c.verb == "mutate"]) == 1


def test_read_only_refuses_before_the_recipe_backstop_or_any_call(monkeypatch):
    fake = FakePixAI()
    monkeypatch.setattr(core, "READ_ONLY", True)
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        core.submit_generation(fake, {"modelId": "1", "recipeIds": [RID]})
    assert fake.calls == []


# ---------------------------------------------------------------------------
# PixAI's refusal, read wherever it arrives
# ---------------------------------------------------------------------------

def test_refusal_from_the_graphql_exception_record():
    r = rec.refusal_from(_refused("RECIPE_UNAVAILABLE", "follow_required", [RID]))
    assert r["group"] == "follow" and r["copy"] == "Follow the author to use it"
    r = rec.refusal_from(_refused("RECIPE_UNAVAILABLE", "not_found", [RID]))
    assert r["copy"] == "This recipe isn't available any more" and r["fix"] == "Remove"


def test_refusal_from_a_rest_body_and_from_bare_text():
    e = core.PixAIError("x")
    e.body = {"code": "RECIPE_INCOMPATIBLE", "data": {"recipeIds": [RID, RID2],
                                                      "reason": "lora_budget"}}
    r = rec.refusal_from(e)
    assert r["group"] == "loras" and r["recipe_ids"] == [RID, RID2]
    assert r["copy"].startswith("2 recipes bring")
    text = core.PixAIError('GraphQL error: [{"extensions": {"exception": {"name": '
                           '"RECIPE_INCOMPATIBLE", "recipeIds": ["%s"], "reason": '
                           '"prompt_length_budget"}}}]' % RID)
    r = rec.refusal_from(text)
    assert r["group"] == "prompt" and r["tag"] == "Prompt too long" and r["recipe_ids"] == [RID]


def test_other_failures_are_not_recipe_refusals():
    assert rec.refusal_from(core.PixAIError("GraphQL error: LORA_NUM_EXCEEDED")) is None
    assert rec.refusal_from(None) is None


@pytest.mark.parametrize("group,reasons", sorted(rec.REASON_GROUPS.items()))
def test_every_one_of_the_22_reasons_lands_in_its_group(group, reasons):
    for reason in reasons:
        r = rec.refusal_dict("RECIPE_INCOMPATIBLE", reason, [RID])
        assert r["group"] == group and r["copy"] and r["tag"] and r["fix"]
    assert sum(len(v) for v in rec.REASON_GROUPS.values()) == 22


# ---------------------------------------------------------------------------
# The transport keeps what a structured refusal needs
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _Sess:
    def __init__(self, resp):
        self.resp = resp

    def get(self, *a, **k):
        return self.resp

    def post(self, *a, **k):
        return self.resp


def test_rest_errors_carry_status_and_body_and_keep_their_message():
    body = {"code": "RECIPE_INCOMPATIBLE", "data": {"recipeIds": [RID], "reason": "x"}}
    client = core.PixAIClient(_Sess(_Resp(422, body)))
    with pytest.raises(core.PixAIError) as ei:
        client.rest_get("/task-price")
    assert ei.value.http_status == 422 and ei.value.body == body
    assert str(ei.value).startswith("REST GET /task-price -> 422: ")


def test_a_non_json_error_body_is_still_a_pixai_error():
    client = core.PixAIClient(_Sess(_Resp(502, "<html>bad gateway</html>")))
    with pytest.raises(core.PixAIError) as ei:
        client.rest_post("/kaisuuken/check", {})
    assert ei.value.body is None and ei.value.http_status == 502


def test_graphql_errors_ride_whole_on_the_error():
    errs = [{"message": "m" * 700, "extensions": {"exception": {"name": "RECIPE_UNAVAILABLE",
                                                               "recipeIds": [RID],
                                                               "reason": "not_found"}}}]
    client = core.PixAIClient(_Sess(_Resp(200, {"errors": errs})))
    with pytest.raises(core.PixAIError) as ei:
        client.mutate("mutation { x }")
    assert ei.value.graphql_errors == errs
    assert rec.refusal_from(ei.value)["reason"] == "not_found"


# ---------------------------------------------------------------------------
# Reads: shapes the client draws
# ---------------------------------------------------------------------------

MARKET_CARD = {
    "id": RID, "categories": ["style"], "title": "Classic Japanese", "description": None,
    "coverMediaId": "777", "modelType": "MMDIT26B_MODEL", "modelId": "1850",
    "slotTypes": ["promptFragment", "lora"], "source": "official",
    "slotSpecs": [{"slotIndex": 0, "kind": "text", "length": 86},
                  {"slotIndex": 1, "kind": "lora"}],
    "publishedAt": "2026-09-27T00:00:00Z", "presetType": "public", "status": "published",
    "visibility": "public", "usability": "usable",
    "coverMedia": {"id": "777", "type": "IMAGE", "urls": [
        {"variant": "PUBLIC", "url": "https://img/pub.webp"},
        {"variant": "THUMBNAIL", "url": "https://img/thumb.webp"}]},
    "author": {"id": "5", "username": "pixai", "displayName": "PixAI"},
    "stats": {"likedCount": 186, "taskCount": 66900, "artworkCount": 1200},
    "likeDirection": "removed",
    "model": {"id": "1850", "title": "Tsubaki.3", "type": "MMDIT26B_MODEL",
              "latestAvailableVersion": {"id": "1983308862240288769"}},
}


def test_a_market_card_reads_what_the_design_draws():
    c = rec.card(MARKET_CARD)
    assert c["cover"] == "https://img/thumb.webp"
    assert c["author"]["name"] == "PixAI Official" and c["official"]
    assert (c["uses"], c["likes"], c["artworks"]) == (66900, 186, 1200)
    assert c["kinds"] == [{"type": "promptFragment", "label": "Prompt", "count": 1},
                          {"type": "lora", "label": "LoRA", "count": 1}]
    assert c["prompt_len"] == 86 and c["model_title"] == "Tsubaki.3"
    assert c["model_version_id"] == "1983308862240288769"
    assert "slots" not in c           # a public view never carries its content


def test_the_market_asks_the_sort_route_with_the_contracts_params(monkeypatch):
    rec.clear_cache()
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen[path] = params
        return {"data": [MARKET_CARD], "page": 1, "pageSize": 24, "totalPage": 3,
                "totalCount": 70}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    out = rec.market(object(), sort="most-liked", page=2, category="style",
                     model_type="MMDIT26B_MODEL")
    assert seen["/recipes/most-liked"] == {"page": 2, "pageSize": 24,
                                           "categories[0]": "style",
                                           "modelType": "MMDIT26B_MODEL"}
    assert out["total"] == 70 and out["items"][0]["id"] == RID
    rec.market(object(), sort="latest", query="  moon  ")
    assert seen["/recipes/search"]["q"] == "moon"


def test_style_code_asks_by_ref_and_version_and_reads_null(monkeypatch):
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen[path] = params
        return {"recipeId": None}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    assert rec.by_style_code(object(), "SC-7Q2M-KX", "1983308862240288769") is None
    assert seen["/recipes/by-style-code"] == {"refId": "SC-7Q2M-KX",
                                              "modelVersionId": "1983308862240288769"}


def test_the_draft_route_is_never_called(monkeypatch):
    """GET /v2/recipes/draft CREATES a draft. No function in the module may name it."""
    import inspect
    src = inspect.getsource(rec)
    assert '"/recipes/draft"' not in src and "'/recipes/draft'" not in src


# ---------------------------------------------------------------------------
# Writes: CSRF, READ_ONLY, single attempt, resume never backwards
# ---------------------------------------------------------------------------

DRAFT = {"categories": ["character"], "modelType": "MMDIT26B_MODEL", "modelId": "1850",
         "title": "Priestess of Elune", "description": "", "coverMediaId": "",
         "showcaseMediaIds": ["11", "12", "13"], "presetType": "public",
         "slots": [{"type": "promptFragment", "text": "night elf"},
                   {"type": "lora", "loras": [{"versionId": "88", "weight": 0.7}]}]}


class _Writes:
    """A fake /v2 recipe backend: records every POST, answers each with a recipe in the
    status the step implies."""

    def __init__(self, start_status=None):
        self.posts = []
        self.status = start_status

    def get(self, s, path, params=None, **k):
        return {"id": RID, "status": self.status, "version": 3}

    def post(self, s, path, body, **k):
        self.posts.append((path, body))
        if path == "/recipes/":
            self.status = "draft"
            return {"id": RID, "status": "draft"}
        if path.endswith("/transition"):
            self.status = body["to"]
        return {"id": RID, "status": self.status, "title": "Priestess of Elune"}


def test_publish_creates_saves_and_moves_draft_to_test_to_published(monkeypatch):
    w = _Writes()
    monkeypatch.setattr(core, "_rest_post", w.post)
    out = rec.publish(object(), DRAFT)
    assert [p for p, _ in w.posts] == ["/recipes/", "/recipes/" + RID,
                                       "/recipes/%s/transition" % RID,
                                       "/recipes/%s/transition" % RID]
    assert w.posts[2][1] == {"to": "test"}
    assert w.posts[3][1] == {"to": "published", "showcaseMediaIds": ["11", "12", "13"]}
    body = w.posts[1][1]
    assert "id" not in body and body["presetType"] == "public"
    assert body["coverMediaId"] == "11" and body["description"] is None
    assert out["status"] == "published"


def test_publish_resumes_from_the_live_status_never_backwards(monkeypatch):
    w = _Writes(start_status="test")
    monkeypatch.setattr(core, "_rest_get", w.get)
    monkeypatch.setattr(core, "_rest_post", w.post)
    rec.publish(object(), DRAFT, recipe_id=RID)
    assert [p for p, _ in w.posts] == ["/recipes/" + RID, "/recipes/%s/transition" % RID]
    assert w.posts[1][1]["to"] == "published"
    w = _Writes(start_status="published")
    monkeypatch.setattr(core, "_rest_get", w.get)
    monkeypatch.setattr(core, "_rest_post", w.post)
    assert rec.publish(object(), DRAFT, recipe_id=RID)["status"] == "published"
    assert w.posts == []                               # nothing re-sent


def test_publish_checks_everything_locally_before_any_write(monkeypatch):
    w = _Writes()
    monkeypatch.setattr(core, "_rest_post", w.post)
    for bad in (dict(DRAFT, categories=[]), dict(DRAFT, title=" "),
                dict(DRAFT, showcaseMediaIds=["11"]), dict(DRAFT, slots=[]),
                dict(DRAFT, slots=[{"type": "contextImages", "images": [{"mediaId": "1"}]},
                                   {"type": "lora", "loras": [{"versionId": "8"}]}])):
        with pytest.raises(core.PixAIError):
            rec.publish(object(), bad)
    assert w.posts == []


def test_a_failed_step_after_the_create_reports_the_new_id(monkeypatch):
    def post(s, path, body, **k):
        if path == "/recipes/":
            return {"id": RID, "status": "draft"}
        e = core.PixAIError("REST POST -> 422")
        e.body = {"code": "RECIPE_SHOWCASE_INELIGIBLE"}
        raise e
    monkeypatch.setattr(core, "_rest_post", post)
    with pytest.raises(rec.RecipeWriteError) as ei:
        rec.publish(object(), DRAFT)
    assert ei.value.recipe_id == RID and ei.value.code == "RECIPE_SHOWCASE_INELIGIBLE"
    assert "showcase" in str(ei.value)


def test_every_write_refuses_under_read_only_before_any_call(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)

    def boom(*a, **k):
        raise AssertionError("no call under READ_ONLY")
    monkeypatch.setattr(core, "_rest_post", boom)
    monkeypatch.setattr(core, "_rest_get", boom)
    monkeypatch.setattr(rec, "_rest_delete", boom)
    for call in (lambda: rec.publish(object(), DRAFT),
                 lambda: rec.update(object(), RID, DRAFT, version=3),
                 lambda: rec.transition(object(), RID, "archived"),
                 lambda: rec.set_create(object(), "Portrait looks"),
                 lambda: rec.set_toggle(object(), SET_ID, RID, True),
                 lambda: rec.set_toggle(object(), SET_ID, RID, False, ITEM_ID)):
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            call()


def test_edit_refuses_when_the_recipe_moved_on_pixai(monkeypatch):
    w = _Writes(start_status="published")
    monkeypatch.setattr(core, "_rest_get", w.get)
    monkeypatch.setattr(core, "_rest_post", w.post)
    with pytest.raises(rec.RecipeWriteError, match="changed on PixAI"):
        rec.update(object(), RID, DRAFT, version=2)
    assert w.posts == []
    out = rec.update(object(), RID, DRAFT, version=3)
    assert [p for p, _ in w.posts] == ["/recipes/" + RID] and out["id"] == RID


def test_only_archive_and_unarchive_are_offered():
    with pytest.raises(core.PixAIError):
        rec.transition(object(), RID, "draft")


def test_sets_add_and_remove_ride_the_collections_contract(monkeypatch):
    posts, deletes = [], []
    monkeypatch.setattr(core, "_rest_post",
                        lambda s, path, body, **k: posts.append((path, body)) or
                        {"collectionId": SET_ID, "itemId": ITEM_ID, "saved": True})
    monkeypatch.setattr(rec, "_rest_delete",
                        lambda s, path, **k: deletes.append(path) or
                        {"collectionId": SET_ID, "itemId": None, "saved": False})
    assert rec.set_toggle(object(), SET_ID, RID, True) == {"contains": True, "item_id": ITEM_ID}
    assert posts == [("/collection/%s/items" % SET_ID, {"refType": "recipe", "refId": RID})]
    assert rec.set_toggle(object(), SET_ID, RID, False, ITEM_ID) == {"contains": False,
                                                                     "item_id": ""}
    assert deletes == ["/collection/%s/items/%s" % (SET_ID, ITEM_ID)]
    rec.set_create(object(), "Portrait looks")
    assert posts[-1] == ("/collection/", {"title": "Portrait looks", "description": "",
                                          "contentType": "recipe", "visibility": "private",
                                          "coverMode": "single"})


def test_a_real_set_opens_with_pixais_uuid_ids(monkeypatch):
    """#78: every live collection id and item id is a UUID string, and the Sets code checked
    them with the numeric recipe-id rule, so opening a set or ticking one refused with "That
    isn't a valid id" before anything was sent."""
    gets = []

    def fake_get(s, path, params=None, **k):
        gets.append(path)
        return {"data": [{"id": ITEM_ID, "refId": RID, "refType": "recipe",
                          "recipe": dict(MARKET_CARD, id=RID)}], "nextCursor": None}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    out = rec.set_items(object(), SET_ID)
    assert gets == ["/collection/%s/items" % SET_ID]
    assert [(c["id"], c["item_id"]) for c in out["items"]] == [(RID, ITEM_ID)]


@pytest.mark.parametrize("bad", ["31", "", "../31", SET_ID + "/x", SET_ID.replace("-", ""),
                                 "zzzzzzzz-e558-73a8-94a5-a66e390f8443"])
def test_set_and_item_ids_must_be_uuid_shaped(monkeypatch, bad):
    def boom(*a, **k):
        raise AssertionError("a refused id must reach nothing")
    monkeypatch.setattr(core, "_rest_get", boom)
    monkeypatch.setattr(core, "_rest_post", boom)
    monkeypatch.setattr(rec, "_rest_delete", boom)
    for call in (lambda: rec.set_items(object(), bad),
                 lambda: rec.set_toggle(object(), bad, RID, True),
                 lambda: rec.set_toggle(object(), SET_ID, RID, False, bad)):
        with pytest.raises(core.PixAIError, match="valid id"):
            call()
    # the recipe id keeps its numeric rule: a UUID is not a recipe id
    with pytest.raises(core.PixAIError, match="valid id"):
        rec.set_toggle(object(), SET_ID, ITEM_ID, True)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

POSTS = ["/api/recipes/publish", "/api/recipes/update", "/api/recipes/transition",
         "/api/recipes/sets/create", "/api/recipes/sets/toggle"]


@pytest.mark.parametrize("path", POSTS)
def test_every_recipe_write_needs_the_session_token(tmp_path, monkeypatch, path):
    def boom(*a, **k):
        raise AssertionError("a refused request must reach nothing")
    monkeypatch.setattr(core, "_make_session", boom)
    cli = login_client(tmp_path)
    for body in ({}, {"csrf": "wrong"}):
        r = cli.post(path, json=body)
        assert r.status_code == 400 and "session expired" in r.get_json()["error"]


def _logged_in(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "USER_ID", "4242")
    cli = login_client(tmp_path)
    meta = cli.get("/api/recipes/meta").get_json()
    return cli, meta["csrf"]


def test_meta_hands_out_the_token_and_the_account_id(tmp_path, monkeypatch):
    rec.clear_cache()
    cli, csrf = _logged_in(tmp_path, monkeypatch)
    meta = cli.get("/api/recipes/meta").get_json()
    assert csrf and meta["user_id"] == "4242" and meta["max_recipes"] == 10
    assert "character" in meta["categories"]      # the fallback when the read fails


def test_publish_route_answers_the_recipe_or_the_id_it_made(tmp_path, monkeypatch):
    cli, csrf = _logged_in(tmp_path, monkeypatch)
    w = _Writes()
    monkeypatch.setattr(core, "_rest_post", w.post)
    d = cli.post("/api/recipes/publish", json={"csrf": csrf, "draft": DRAFT}).get_json()
    assert d["recipe"]["status"] == "published"

    def post(s, path, body, **k):
        if path == "/recipes/":
            return {"id": RID, "status": "draft"}
        raise core.PixAIError("REST POST -> 422")
    monkeypatch.setattr(core, "_rest_post", post)
    d = cli.post("/api/recipes/publish", json={"csrf": csrf, "draft": DRAFT}).get_json()
    assert d["recipe_id"] == RID and d["error"]


def test_mine_reads_the_accounts_own_list(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen[path] = params
        return {"data": [MARKET_CARD], "nextCursor": "c2"}
    monkeypatch.setattr(core, "_rest_get", fake_get)
    d = cli.get("/api/recipes/mine?sort=latest").get_json()
    assert "/user/4242/recipes/latest" in seen and d["next_cursor"] == "c2"


def _seed(tmp_path, rows):
    base = {f: "" for f in CATALOG_FIELDS}
    save_catalog(tmp_path / "catalog.db", [dict(base, **r) for r in rows])


def test_make_a_recipe_checks_the_pictures_model_and_refuses_a_stranger(tmp_path,
                                                                           monkeypatch):
    rec.clear_cache()
    _seed(tmp_path, [{"media_id": "501", "task_id": "9001", "model_id": "1983308862240288769",
                      "model_name": "Tsubaki.3", "prompt_full": "a moon"}])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_model_features",
                        lambda s, v: {"model_type": "MMDIT26B_MODEL", "status": {}})
    cli = login_test_client(create_app(tmp_path))
    d = cli.get("/api/recipes/from-image?media_id=501&check=1").get_json()
    assert d["capable"] is True and d["model_type"] == "MMDIT26B_MODEL"
    r = cli.get("/api/recipes/from-image?media_id=999&check=1")
    assert r.status_code == 404 and r.get_json()["capable"] is False
    monkeypatch.setattr(core, "_model_features",
                        lambda s, v: {"model_type": "VIDEO_MODEL", "status": {}})
    assert cli.get("/api/recipes/from-image?media_id=501&check=1").get_json()["capable"] \
        is False


def test_generate_answers_a_recipe_refusal_structured(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def refuse(session, req, **k):
        raise _refused("RECIPE_INCOMPATIBLE", "model_mismatch", [RID])
    monkeypatch.setattr(core, "submit", refuse)
    monkeypatch.setattr(core, "account_info", lambda s: {})
    monkeypatch.setattr(core, "model_version_resolver",
                        lambda s: (lambda m, v="": "1983308862240288769"))
    monkeypatch.setattr(core, "gate_resolver", lambda s: (lambda p: (p, [])))
    cli = login_client(tmp_path)
    d = cli.post("/api/generate", json={"version_id": "1983308862240288769",
                                        "prompt": "a moon", "recipeIds": [RID]}).get_json()
    assert d["recipe_error"]["reason"] == "model_mismatch"
    assert d["error"] == d["recipe_error"]["copy"]


# ---------------------------------------------------------------------------
# Integration with the Tsubaki.3 dock (lanes w2-gen x w2-recipes). The recipe ids are
# attached right after _gen_parameters, so w2-gen's creativity step-down (built params'
# recipeIds, review S3) sees them; every forbidden combination is checked again after the
# gate. The client half of this seam is loom/test/recipes-dock.test.js.
# ---------------------------------------------------------------------------

from tests.test_tsubaki3_generate import T3, Rest, ctx_payload, road  # noqa: E402


@pytest.fixture
def t3rest(monkeypatch):
    fake = Rest()
    monkeypatch.setattr(core, "_rest_get", fake)
    return fake


def _t3(**kw):
    p = {"version_id": T3, "prompt": "<p>", "mode": "pro", "width": 1024, "height": 1024,
         "prompt_helper": True, "creativity": "medium"}
    p.update(kw)
    return p


@pytest.mark.parametrize("asked,used", [("medium", "low"), ("low", "off"), ("off", "off")])
def test_a_recipe_request_steps_creativity_down_in_the_built_params(asked, used, t3rest):
    req = road(_t3(creativity=asked, prompt_helper=asked != "off", recipeIds=[RID]))
    assert req.parameters["recipeIds"] == [RID]
    assert req.parameters["promptHelper"] == {"creativity": used,
                                              "forcePromptHelperDetectionSide": "server"}
    receipts = [a for a in req.adjusted if a["field"] == "promptHelper"]
    assert bool(receipts) == (asked != "off")
    if receipts:
        assert receipts[0]["asked"] == asked and receipts[0]["used"] == used


@pytest.mark.parametrize("asked", ["off", "low", "medium"])
def test_without_recipes_creativity_goes_out_as_asked(asked, t3rest):
    for extra in ({}, {"recipeIds": []}, {"recipeIds": None}):
        req = road(_t3(creativity=asked, prompt_helper=asked != "off", **extra))
        assert req.parameters["promptHelper"]["creativity"] == asked
        assert "recipeIds" not in req.parameters
        assert not [a for a in req.adjusted if a["field"] == "promptHelper"]


def test_both_recipe_steps_hand_back_the_same_object_without_recipes():
    params = {"modelId": "1", "prompts": "x"}
    for payload in ({}, {"recipeIds": None}, {"recipeIds": []}):
        assert rec.attach_to_built(params, payload) is params
        assert rec.attach_to_built(params, payload, gated=False) is params
        assert rec.apply_to_params(params, payload) is params


def test_ids_that_rode_through_the_gate_are_not_copied_again():
    built = rec.attach_to_built({"modelId": "1"}, {"recipeIds": [RID2, RID]})
    assert built["recipeIds"] == [RID2, RID]
    assert rec.apply_to_params(built, {"recipeIds": [RID2, RID]}) is built


def test_a_no_recipe_payload_builds_the_bytes_it_did_before_the_recipe_steps(t3rest, monkeypatch):
    """The Tsubaki.3 road with the two recipe steps in place, against the same road with both
    replaced by a pass-through (the road as it was before recipes existed): same JSON."""
    payloads = [_t3(), _t3(creativity="low"), ctx_payload(),
                _t3(loras=[{"version_id": "L1", "weight": 0.7}])]
    real = [json.dumps(road(dict(p)).parameters) for p in payloads]
    monkeypatch.setattr(rec, "attach_to_built", lambda params, payload, gated=True: params)
    monkeypatch.setattr(rec, "apply_to_params", lambda params, payload, gated=True: params)
    before = [json.dumps(road(dict(p)).parameters) for p in payloads]
    assert real == before


def test_recipes_beside_context_images_refuse_in_one_wording_and_nothing_is_priced(t3rest):
    # the drawer's own context images (refused at build, before the gate)
    with pytest.raises(core.PixAIError) as err:
        road(ctx_payload(recipeIds=[RID]))
    assert str(err.value) == rec.HELD_WITH_CONTEXT
    # a reference the gate turns into a context image (refused after the gate)
    with pytest.raises(core.PixAIError) as err:
        road(_t3(ref_media_id="701", ref_strength=0.5, recipeIds=[RID]))
    assert str(err.value) == rec.HELD_WITH_CONTEXT
    # the gate's own check on a hand-built dict (w2-gen review S4) says the same words
    with pytest.raises(core.PixAIError) as err:
        core._gate_image_params(object(), {"prompts": "p", "modelId": T3, "width": 1024,
                                           "height": 1024, "batchSize": 1,
                                           "contextImages": ["701"], "recipeIds": [RID]})
    assert str(err.value) == rec.HELD_WITH_CONTEXT
    assert t3rest.priced == [], "a refusal is decided before any price read"


def test_the_send_backstop_uses_the_same_wording(monkeypatch):
    fake = FakePixAI()
    monkeypatch.setattr(core, "_gate_params_for_model", lambda s, p: p)
    with pytest.raises(core.PixAIError) as err:
        core.submit_generation(fake, {"modelId": "1", "contextImages": ["9"],
                                      "recipeIds": [RID]})
    assert str(err.value) == rec.HELD_WITH_CONTEXT
    assert not [c for c in fake.calls if c.verb == "mutate"]


def test_the_task_price_query_of_a_built_recipe_request_carries_its_recipe_ids(t3rest,
                                                                             monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    req = road(_t3(recipeIds=[RID2, RID]))
    out = core.price(object(), req)
    assert out["cost"] == 4000
    assert t3rest.priced, "the quote was read"
    for q in t3rest.priced:
        assert q["recipeIds"] == json.dumps([RID2, RID])
    # and the quote's query names the very list that would be sent
    assert json.loads(t3rest.priced[0]["recipeIds"]) == req.parameters["recipeIds"]

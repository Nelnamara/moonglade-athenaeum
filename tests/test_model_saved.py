"""The model and LoRA pickers' Saved tab (Session S): PixAI's model collections read into the
picker, and the two writes the tab makes -- ⊕ Save (one POST to the reserved default) and a tick
in the "Keep this model" menu (one POST or one DELETE) -- each followed by a read-back that
decides what the user is told.

Contract facts: moonglade-internal/probes/PROBE_2026-10-03_collections-markread.md, sections 1-5.
Every fixture below is in the probe's recorded shapes with made-up ids and titles. No network:
`_rest_get` / `_rest_post` / `moonglade_recipes._rest_delete` are the conftest's blockers unless
a test swaps in a fake.
"""
import pytest
import requests

import moonglade_backup as core
import moonglade_recipes as rec
from tests.conftest import login_client

OWNER = "4242"
DEFAULT_ID = "01a0d7dd-e558-73a8-94a5-a66e390f8443"
NAMED_A = "01a0d7de-0001-7a00-8000-000000000001"
NAMED_Z = "01a0d7de-0002-7a00-8000-000000000002"
NAMED_EMPTY = "01a0d7de-0003-7a00-8000-000000000003"
ITEM_1 = "01a0d7df-1111-7b00-8000-000000000011"
ITEM_GONE = "01a0d7df-9999-7b00-8000-000000000099"
LORA_ID = "1873306400000000001"
MODEL_ID = "1873306400000000002"


def _collection(cid, title, count, reserved=None):
    return {"id": cid, "ownerId": OWNER, "title": title, "description": "", "contentType": "model",
            "sortOrder": 0, "visibility": "private", "source": "user", "reservedType": reserved,
            "status": "available", "unavailableReason": None, "moderationStatus": "approved",
            "coverMode": "single", "coverMediaId": None, "coverMediaIds": [],
            "resolvedCoverMediaIds": [], "featuredPinnedAt": None, "featuredPosition": None,
            "itemCount": count, "likeCount": 0, "likeDirection": None, "isOwnOnly": False,
            "isOwner": True, "createdAt": "2026-08-14T02:49:00.000Z",
            "updatedAt": "2026-09-11T00:00:00.000Z"}


def _model(mid, title, mtype="MULTI_LORA", base="SDXL_MODEL", category="sdxl", blur=False):
    version = {"id": "9" + mid[1:], "modelId": mid, "modelTitle": title, "mediaId": "5" + mid[1:],
               "media": None, "name": "v1", "fileUploadId": None,
               "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-01T00:00:00.000Z",
               "extra": {}, "loraBaseModelType": base if "LORA" in mtype else None,
               "loraBaseModelId": None, "modelType": mtype, "status": "PUBLISHED"}
    return {"id": mid, "authorId": "77", "title": title, "type": mtype, "category": category,
            "mediaId": "5" + mid[1:],
            "media": {"width": 512, "height": 512,
                      "thumbnailUrl": "https://images.example.invalid/t/" + mid,
                      "publicUrl": "https://images.example.invalid/p/" + mid},
            "visibilityType": "PUBLIC", "accessType": "PUBLIC", "flag": {"shouldBlur": blur},
            "loraBaseModelTypes": [base] if "LORA" in mtype else [],
            "modelDescription": "a description", "likedCount": 12, "liked": False, "refCount": 34,
            "commentCount": 2, "curations": [], "latestAvailableVersionId": version["id"],
            "hasLatestAvailableVersion": True, "latestAvailableVersion": version,
            "userPermission": None, "weightOffset": 0, "permittedUse": None}


def _item(iid, model, saved_at="2026-09-11T00:00:00.000Z", set_id=DEFAULT_ID):
    return {"id": iid, "collectionId": set_id, "refId": model["id"], "authorId": "77",
            "effectiveStatus": "available", "effectiveUnavailableReason": None,
            "createdAt": saved_at, "updatedAt": saved_at, "refType": "model", "model": model}


def _gone(iid, saved_at="2024-03-05T00:00:00.000Z"):
    """A saved model PixAI has since deleted: the item and its save date survive, nothing else."""
    return {"id": iid, "collectionId": DEFAULT_ID, "refId": "-1", "authorId": "77",
            "effectiveStatus": "unavailable", "effectiveUnavailableReason": "deleted",
            "createdAt": saved_at, "updatedAt": saved_at, "refType": "model", "model": None}


def _selector(contains, item_id=None, extra=()):
    default = dict(_collection(DEFAULT_ID, "default-collection", 481, "default"),
                   containsItem=contains, itemId=item_id)
    data = [default] + [dict(c, containsItem=False, itemId=None) for c in extra]
    return {"recent": [default], "data": data, "nextCursor": None}


def _boom(*a, **k):
    raise AssertionError("no PixAI call expected here")


# ---------------------------------------------------------------------------
# Reads: the row, the rail, a page, the removed models
# ---------------------------------------------------------------------------

def test_a_saved_item_maps_to_the_pickers_row_and_a_removed_one_to_none():
    row = rec.model_item(_item(ITEM_1, _model(LORA_ID, "Glasswing", blur=True)))
    assert row["model_id"] == LORA_ID and row["title"] == "Glasswing"
    assert row["preview_url"] == "https://images.example.invalid/p/" + LORA_ID
    assert row["should_blur"] is True and row["base_model"] == "sdxl"
    assert (row["liked_count"], row["ref_count"], row["comment_count"]) == (12, 34, 2)
    assert row["description"] == "a description" and row["type"] == "MULTI_LORA"
    # the arch label the card shows comes from the latest available version
    assert row["lora_base_model_type"] == "SDXL_MODEL" and row["model_type"] == "MULTI_LORA"
    assert row["item_id"] == ITEM_1 and row["saved_at"] == "2026-09-11T00:00:00.000Z"
    assert rec.model_item(_gone(ITEM_GONE)) is None


class _Reads:
    """A fake /v2 for the model collection reads, keyed the way the probe recorded them."""

    def __init__(self, sets=None, totals=None, pages=None, selector=None):
        self.sets = sets if sets is not None else [_collection(DEFAULT_ID, "default-collection",
                                                               481, "default")]
        self.totals = totals or {}           # (set_id, modelTypes) -> totalItems
        self.pages = pages or {}             # (set_id, cursor or "") -> (data, nextCursor)
        self.selector = selector
        self.gets = []

    def get(self, s, path, params=None, **k):
        params = dict(params or {})
        self.gets.append((path, params))
        if path == "/collection/list/" + OWNER:
            return {"data": self.sets, "nextCursor": None}
        if path == "/collection/selector":
            return self.selector
        sid = path.split("/")[2]
        if params.get("page") == 1:
            return {"data": [], "nextCursor": None, "page": 1, "outOfRange": False,
                    "totalItems": self.totals.get((sid, params.get("modelTypes", ""))),
                    "totalPages": 1}
        data, nxt = self.pages.get((sid, params.get("cursor", "")), ([], None))
        return {"data": data, "nextCursor": nxt, "page": None, "totalItems": None,
                "totalPages": None, "outOfRange": None}


def test_the_rail_is_saved_first_then_named_sets_a_to_z_counting_this_pickers_type(monkeypatch):
    f = _Reads(sets=[_collection(NAMED_Z, "zodiac", 3), _collection(DEFAULT_ID, "default-collection",
                                                                      481, "default"),
                     _collection(NAMED_A, "Anime bases", 8), _collection(NAMED_EMPTY, "Faces", 2)],
               totals={(DEFAULT_ID, "ANY_LORA"): 340, (DEFAULT_ID, "ANY_MODEL"): 132,
                       (NAMED_A, "ANY_LORA"): 6, (NAMED_Z, "ANY_LORA"): 3,
                       (NAMED_EMPTY, "ANY_LORA"): 0})
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_sets(object(), OWNER, "lora")
    assert [(s["id"], s["title"], s["count"]) for s in out["sets"]] == [
        (DEFAULT_ID, "Saved", 340), (NAMED_A, "Anime bases", 6), (NAMED_Z, "zodiac", 3)]
    assert out["default_id"] == DEFAULT_ID
    # 481 saved in all, 132 models and 340 LoRAs live: 9 are models PixAI no longer has
    assert out["unavailable"] == 9
    assert f.gets[0] == ("/collection/list/" + OWNER, {"contentType": "model", "limit": 50})
    counts = [p for path, p in f.gets if p.get("page") == 1]
    assert counts and all(set(p) == {"page", "modelTypes"} for p in counts)


def test_an_account_with_no_saved_list_yet_reads_as_empty(monkeypatch):
    f = _Reads(sets=[])
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_sets(object(), OWNER, "base")
    assert out == {"sets": [], "default_id": "", "unavailable": 0}


def test_a_page_is_cursor_mode_24_at_a_time_and_leaves_removed_models_out(monkeypatch):
    f = _Reads(pages={(DEFAULT_ID, "c2"): ([_item(ITEM_1, _model(LORA_ID, "Glasswing")),
                                             _gone(ITEM_GONE)], "c3")})
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_page(object(), DEFAULT_ID, "lora", cursor="c2", query="glass",
                         lora_base="SDXL_MODEL")
    assert [r["model_id"] for r in out["results"]] == [LORA_ID]
    assert out["has_more"] is True and out["next_cursor"] == "c3"
    path, params = f.gets[-1]
    assert path == "/collection/%s/items" % DEFAULT_ID
    assert params == {"limit": 24, "cursor": "c2", "modelTypes": "ANY_LORA",
                      "loraBaseModelTypes": "SDXL_MODEL", "query": "glass"}


def test_the_model_picker_drops_chat_and_video_models_and_ignores_an_unknown_base(monkeypatch):
    rows = [_item(ITEM_1, _model(MODEL_ID, "Moonwell v3", mtype="SDXL_MODEL")),
            _item(ITEM_1.replace("1111", "2222"), _model("1873306400000000003", "Chatty",
                                                         mtype="CHAT")),
            _item(ITEM_1.replace("1111", "3333"), _model("1873306400000000004", "Reel",
                                                         mtype="VIDEO_MODEL"))]
    f = _Reads(pages={(DEFAULT_ID, ""): (rows, None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_page(object(), DEFAULT_ID, "base", lora_base="NOT_A_BASE")
    assert [r["title"] for r in out["results"]] == ["Moonwell v3"]
    assert out["has_more"] is False and out["next_cursor"] == ""
    assert f.gets[-1][1] == {"limit": 24, "modelTypes": "ANY_MODEL"}


def test_removed_models_are_found_by_walking_saved_and_carry_their_item_id(monkeypatch):
    f = _Reads(pages={(DEFAULT_ID, ""): ([_item(ITEM_1, _model(LORA_ID, "Glasswing"))], "c2"),
                      (DEFAULT_ID, "c2"): ([_gone(ITEM_GONE)], None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_unavailable(object(), OWNER)
    assert out["items"] == [{"item_id": ITEM_GONE, "saved_at": "2024-03-05T00:00:00.000Z",
                             "reason": "deleted"}]
    assert all("modelTypes" not in p for _, p in f.gets if _.endswith("/items"))


def test_the_selector_answers_saved_and_the_unsave_item_id(monkeypatch):
    f = _Reads(selector=_selector(True, ITEM_1, extra=[_collection(NAMED_A, "Anime bases", 6)]))
    monkeypatch.setattr(core, "_rest_get", f.get)
    out = rec.model_state(object(), LORA_ID)
    assert out["saved"] is True and out["item_id"] == ITEM_1 and out["default_id"] == DEFAULT_ID
    assert [(s["title"], s["contains"]) for s in out["sets"]] == [("Saved", True),
                                                                  ("Anime bases", False)]
    assert f.gets == [("/collection/selector", {"refType": "model", "refId": LORA_ID,
                                                "limit": 50})]


# ---------------------------------------------------------------------------
# Writes: ⊕ Save, a menu tick, removing a removed model's row
# ---------------------------------------------------------------------------

class _Writes(_Reads):
    def __init__(self, after, post=None, delete=None, **kw):
        super().__init__(selector=after, **kw)
        self.posts, self.deletes = [], []
        self._post, self._delete = post, delete

    def post(self, s, path, body, **k):
        self.posts.append((path, body))
        if isinstance(self._post, BaseException):
            raise self._post
        return self._post if self._post is not None else {
            "collectionId": DEFAULT_ID, "itemId": ITEM_1, "saved": True}

    def delete(self, s, path, **k):
        self.deletes.append(path)
        if isinstance(self._delete, BaseException):
            raise self._delete
        return self._delete if self._delete is not None else {
            "collectionId": DEFAULT_ID, "itemId": None, "saved": False}


def _wire(monkeypatch, w):
    monkeypatch.setattr(core, "_rest_get", w.get)
    monkeypatch.setattr(core, "_rest_post", w.post)
    monkeypatch.setattr(rec, "_rest_delete", w.delete)


def test_save_is_one_post_to_saved_then_a_selector_read_back(monkeypatch):
    w = _Writes(_selector(True, ITEM_1))
    _wire(monkeypatch, w)
    out = rec.model_save(object(), OWNER, LORA_ID)
    # the site's own path: POST /collection/{defaultId}/items with the MODEL id -- never the PUT
    assert w.posts == [("/collection/%s/items" % DEFAULT_ID, {"refType": "model",
                                                               "refId": LORA_ID})]
    assert out["contains"] is True and out["item_id"] == ITEM_1 and "error" not in out
    assert w.gets[-1][0] == "/collection/selector"


def test_every_model_write_refuses_under_read_only_before_any_call(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    monkeypatch.setattr(core, "_rest_get", _boom)
    monkeypatch.setattr(core, "_rest_post", _boom)
    monkeypatch.setattr(rec, "_rest_delete", _boom)
    for call in (lambda: rec.model_save(object(), OWNER, LORA_ID),
                 lambda: rec.model_tick(object(), NAMED_A, LORA_ID, True),
                 lambda: rec.model_tick(object(), NAMED_A, LORA_ID, False, ITEM_1),
                 lambda: rec.model_remove_gone(object(), OWNER, ITEM_GONE),
                 lambda: rec.set_create(object(), "Faces", content_type="model")):
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            call()


@pytest.mark.parametrize("failure", [
    requests.exceptions.ReadTimeout("read timed out"),
    requests.exceptions.ConnectionError("connection dropped"),
    core.PixAIRestError("REST POST -> 502: bad gateway", status=502, body=None),
])
def test_an_unclear_save_answer_is_read_back_and_never_sent_twice(monkeypatch, failure):
    w = _Writes(_selector(True, ITEM_1), post=failure)
    _wire(monkeypatch, w)
    out = rec.model_save(object(), OWNER, LORA_ID)
    assert len(w.posts) == 1
    assert out["contains"] is True and out["item_id"] == ITEM_1 and "error" not in out
    # ...and when the check shows it did not land, the user is told so, never "Saved"
    w2 = _Writes(_selector(False), post=failure)
    _wire(monkeypatch, w2)
    out = rec.model_save(object(), OWNER, LORA_ID)
    assert len(w2.posts) == 1 and out["contains"] is False and out["error"]


def test_when_the_read_back_fails_too_nothing_is_claimed(monkeypatch):
    w = _Writes(None, post=requests.exceptions.ReadTimeout("read timed out"))

    def get(s, path, params=None, **k):
        if path == "/collection/selector":
            raise requests.exceptions.ConnectionError("still down")
        return w.get(s, path, params, **k)
    _wire(monkeypatch, w)
    monkeypatch.setattr(core, "_rest_get", get)
    out = rec.model_save(object(), OWNER, LORA_ID)
    assert out["contains"] is None and "look on pixai" in out["error"].lower()
    assert len(w.posts) == 1


@pytest.mark.parametrize("code,status,words", [
    ("SOURCE_PRIVATE", 403, "private"),
    ("SOURCE_UNAVAILABLE", 403, "isn't available"),
    ("SOURCE_CANNOT_BE_COLLECTED", 403, "doesn't allow"),
    ("SOURCE_CREATOR_BLOCKED_OWNER", 403, "blocked"),
    ("SOURCE_NOT_FOUND", 404, "couldn't find this model"),
    ("COLLECTION_NOT_FOUND", 404, "couldn't find that set"),
    ("UNAUTHORIZED", 401, "key"),
])
def test_a_refused_save_says_why_in_plain_words(monkeypatch, code, status, words):
    refusal = core.PixAIRestError("REST POST -> %d" % status, status=status,
                                  body={"code": code, "status": status, "message": code})
    w = _Writes(_selector(False), post=refusal)
    _wire(monkeypatch, w)
    out = rec.model_save(object(), OWNER, LORA_ID)
    assert out["contains"] is False and words in out["error"]
    assert code not in out["error"]                      # plain words, not PixAI's code


def test_already_saved_is_not_a_refusal_when_the_read_back_agrees(monkeypatch):
    conflict = core.PixAIRestError("REST POST -> 409", status=409,
                                   body={"code": "COLLECTION_MEMBERSHIP_CONFLICT"})
    w = _Writes(_selector(True, ITEM_1), post=conflict)
    _wire(monkeypatch, w)
    out = rec.model_save(object(), OWNER, LORA_ID)
    assert out["contains"] is True and out["item_id"] == ITEM_1 and "error" not in out


def test_a_tick_adds_with_one_post_and_removes_with_one_delete_by_item_id(monkeypatch):
    named = _collection(NAMED_A, "Anime bases", 6)
    after_add = _selector(True, ITEM_1)
    after_add["data"].append(dict(named, containsItem=True, itemId=ITEM_1))
    w = _Writes(after_add)
    _wire(monkeypatch, w)
    out = rec.model_tick(object(), NAMED_A, LORA_ID, True)
    assert w.posts == [("/collection/%s/items" % NAMED_A, {"refType": "model", "refId": LORA_ID})]
    assert out["contains"] is True and out["item_id"] == ITEM_1

    w = _Writes(_selector(True, ITEM_1, extra=[named]))
    _wire(monkeypatch, w)
    out = rec.model_tick(object(), NAMED_A, LORA_ID, False, ITEM_1)
    assert w.deletes == ["/collection/%s/items/%s" % (NAMED_A, ITEM_1)] and w.posts == []
    assert out["contains"] is False and "error" not in out


def test_a_failed_tick_reports_the_state_the_read_back_found(monkeypatch):
    w = _Writes(_selector(True, ITEM_1), delete=core.PixAIRestError(
        "REST DELETE -> 404", status=404, body={"code": "COLLECTION_NOT_FOUND"}))
    _wire(monkeypatch, w)
    out = rec.model_tick(object(), DEFAULT_ID, LORA_ID, False, ITEM_1)
    assert out["contains"] is True and "couldn't find that set" in out["error"]


@pytest.mark.parametrize("call", [
    lambda: rec.model_save(object(), OWNER, "abc"),
    lambda: rec.model_save(object(), OWNER, "-1"),
    lambda: rec.model_tick(object(), "31", LORA_ID, True),
    lambda: rec.model_tick(object(), NAMED_A, LORA_ID, False, "41"),
    lambda: rec.model_remove_gone(object(), OWNER, "-1"),
])
def test_ids_are_checked_before_anything_is_sent(monkeypatch, call):
    monkeypatch.setattr(core, "_rest_get", _boom)
    monkeypatch.setattr(core, "_rest_post", _boom)
    monkeypatch.setattr(rec, "_rest_delete", _boom)
    with pytest.raises(core.PixAIError, match="valid id"):
        call()


def test_a_removed_models_row_leaves_saved_by_one_delete_of_its_item(monkeypatch):
    w = _Writes(None)
    _wire(monkeypatch, w)
    out = rec.model_remove_gone(object(), OWNER, ITEM_GONE)
    assert w.deletes == ["/collection/%s/items/%s" % (DEFAULT_ID, ITEM_GONE)]
    assert out == {"removed": True}


def test_an_unclear_removal_is_read_back_from_saveds_count(monkeypatch):
    w = _Writes(None, delete=requests.exceptions.ReadTimeout("read timed out"))
    counts = iter([481, 480])

    def get(s, path, params=None, **k):
        w.gets.append((path, params))
        return {"data": [_collection(DEFAULT_ID, "default-collection", next(counts), "default")],
                "nextCursor": None}
    _wire(monkeypatch, w)
    monkeypatch.setattr(core, "_rest_get", get)
    assert rec.model_remove_gone(object(), OWNER, ITEM_GONE) == {"removed": True}
    assert len(w.deletes) == 1


def test_a_new_model_set_is_a_private_model_collection(monkeypatch):
    w = _Writes(None, post=_collection(NAMED_A, "Faces", 0))
    _wire(monkeypatch, w)
    made = rec.set_create(object(), "Faces", content_type="model")
    assert w.posts == [("/collection/", {"title": "Faces", "description": "",
                                         "contentType": "model", "visibility": "private",
                                         "coverMode": "single"})]
    assert made["id"] == NAMED_A


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def _logged_in(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "USER_ID", OWNER)
    cli = login_client(tmp_path)
    csrf = cli.get("/api/account/prefs").get_json()["csrf"]
    return cli, csrf


WRITES = ["/api/model-saved/save", "/api/model-saved/tick", "/api/model-saved/remove",
          "/api/model-saved/sets/create"]


@pytest.mark.parametrize("path", WRITES)
def test_every_model_saved_write_needs_the_session_token(tmp_path, monkeypatch, path):
    def boom(*a, **k):
        raise AssertionError("a refused request must reach nothing")
    monkeypatch.setattr(core, "_make_session", boom)
    cli = login_client(tmp_path)
    for body in ({}, {"csrf": "wrong"}):
        r = cli.post(path, json=body)
        assert r.status_code == 400 and "session expired" in r.get_json()["error"]


def test_the_saved_tab_reads_through_the_picker_search(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)
    f = _Reads(pages={(DEFAULT_ID, ""): ([_item(ITEM_1, _model(LORA_ID, "Glasswing"))], "c2")})
    monkeypatch.setattr(core, "_rest_get", f.get)
    d = cli.get("/api/model-search?kind=lora&size=24&q=&src=saved").get_json()
    assert [r["model_id"] for r in d["results"]] == [LORA_ID]
    assert d["has_more"] is True and d["next_cursor"] == "c2"
    # no set named: the reserved default, found from the list
    assert f.gets[0][0] == "/collection/list/" + OWNER
    d = cli.get("/api/model-search?kind=lora&size=24&q=&src=saved&set=%s&cursor=c2&base=SDXL_MODEL"
                % NAMED_A).get_json()
    assert f.gets[-1] == ("/collection/%s/items" % NAMED_A,
                          {"limit": 24, "cursor": "c2", "modelTypes": "ANY_LORA",
                           "loraBaseModelTypes": "SDXL_MODEL"})


def test_a_saved_tab_read_that_fails_answers_an_error_never_an_empty_list(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)

    def down(*a, **k):
        raise core.PixAIRestError("REST GET -> 503", status=503)
    monkeypatch.setattr(core, "_rest_get", down)
    d = cli.get("/api/model-search?kind=base&size=24&q=&src=saved&set=%s" % DEFAULT_ID).get_json()
    assert d["error"] and d["results"] == []
    d = cli.get("/api/model-saved/sets?kind=base").get_json()
    assert d["error"] and d["sets"] == []


def test_the_rail_route_says_whether_read_only_is_on(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)
    f = _Reads(totals={(DEFAULT_ID, "ANY_LORA"): 340, (DEFAULT_ID, "ANY_MODEL"): 132})
    monkeypatch.setattr(core, "_rest_get", f.get)
    d = cli.get("/api/model-saved/sets?kind=lora").get_json()
    assert d["sets"][0]["title"] == "Saved" and d["unavailable"] == 9 and d["read_only"] is False
    monkeypatch.setattr(core, "READ_ONLY", True)
    assert cli.get("/api/model-saved/sets?kind=lora").get_json()["read_only"] is True


def test_the_save_route_answers_the_read_back(tmp_path, monkeypatch):
    cli, csrf = _logged_in(tmp_path, monkeypatch)
    w = _Writes(_selector(True, ITEM_1))
    _wire(monkeypatch, w)
    d = cli.post("/api/model-saved/save", json={"csrf": csrf, "model_id": LORA_ID}).get_json()
    assert d["contains"] is True and d["item_id"] == ITEM_1 and len(w.posts) == 1
    d = cli.post("/api/model-saved/tick", json={"csrf": csrf, "set_id": DEFAULT_ID,
                                                "model_id": LORA_ID, "on": False,
                                                "item_id": ITEM_1}).get_json()
    assert w.deletes == ["/collection/%s/items/%s" % (DEFAULT_ID, ITEM_1)]


def test_the_save_route_refuses_under_read_only_with_the_reason(tmp_path, monkeypatch):
    cli, csrf = _logged_in(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "READ_ONLY", True)
    monkeypatch.setattr(core, "_rest_get", _boom)
    monkeypatch.setattr(core, "_rest_post", _boom)
    d = cli.post("/api/model-saved/save", json={"csrf": csrf, "model_id": LORA_ID}).get_json()
    assert "READ_ONLY" in d["error"]


def test_opening_the_menu_only_reads(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)
    f = _Reads(selector=_selector(False))
    monkeypatch.setattr(core, "_rest_get", f.get)
    monkeypatch.setattr(core, "_rest_post", _boom)
    monkeypatch.setattr(rec, "_rest_delete", _boom)
    d = cli.get("/api/model-saved/state?model_id=" + LORA_ID).get_json()
    assert d["saved"] is False and d["sets"][0]["title"] == "Saved" and d["read_only"] is False


# ---------------------------------------------------------------------------
# S2c: the old bookmarks merged into Saved
# ---------------------------------------------------------------------------

def _old_row(mid, title, base="SDXL_MODEL"):
    """A row of the frozen old bookmarks list as core.model_bookmarks_gql answers it."""
    return {"model_id": mid, "title": title, "type": "MULTI_LORA", "preview_url": "",
            "lora_base_model_type": base, "liked_count": 1, "description": ""}


class _OldList:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, session, keyword="", usage="MODEL", limit=24, after=None, lora_base_type=""):
        self.calls.append((usage, limit, after))
        rows, nxt = self.pages[after or ""]
        return {"results": rows, "has_more": bool(nxt), "next_cursor": nxt or "", "total": None}


def test_old_bookmarks_merge_only_what_saved_does_not_hold(monkeypatch):
    saved = _model(LORA_ID, "Glasswing")
    f = _Reads(pages={(DEFAULT_ID, ""): ([_item(ITEM_1, saved)], "c2"),
                      (DEFAULT_ID, "c2"): ([_gone(ITEM_GONE)], None)})
    old = _OldList({"": ([_old_row(LORA_ID, "Glasswing"), _old_row("1873306400000000009", "Moth")],
                         "o2"),
                    "o2": ([_old_row("1873306400000000010", "Kurone Ink", "MMDIT26B_MODEL")], None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    monkeypatch.setattr(core, "model_bookmarks_gql", old)
    out = rec.model_old_bookmarks(object(), object(), OWNER, "lora")
    assert [r["title"] for r in out["rows"]] == ["Moth", "Kurone Ink"]
    assert all(r["old"] is True for r in out["rows"]) and out["partial"] is False
    # the live list is walked for this kind only; the old list a page of 50 at a time
    assert all(p.get("modelTypes") == "ANY_LORA" for path, p in f.gets if path.endswith("/items"))
    assert [c[0] for c in old.calls] == ["LORA", "LORA"] and old.calls[0][1] == 50
    # read once: a second open within the hour costs nothing
    monkeypatch.setattr(core, "_rest_get", _boom)
    monkeypatch.setattr(core, "model_bookmarks_gql", _boom)
    assert rec.model_old_bookmarks(object(), object(), OWNER, "lora")["rows"] == out["rows"]


def test_saving_an_old_row_takes_it_out_of_the_merge(monkeypatch):
    f = _Reads(pages={(DEFAULT_ID, ""): ([], None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    monkeypatch.setattr(core, "model_bookmarks_gql",
                        _OldList({"": ([_old_row(LORA_ID, "Glasswing")], None)}))
    assert [r["model_id"] for r in rec.model_old_bookmarks(object(), object(), OWNER, "lora")["rows"]] \
        == [LORA_ID]
    w = _Writes(_selector(True, ITEM_1))
    _wire(monkeypatch, w)
    assert rec.model_save(object(), OWNER, LORA_ID)["contains"] is True
    monkeypatch.setattr(core, "_rest_get", _boom)
    assert rec.model_old_bookmarks(object(), object(), OWNER, "lora")["rows"] == []


def test_an_unfinished_walk_merges_nothing_rather_than_guess(monkeypatch):
    """If Saved cannot be read to its end, an old row may be saved after all: tag none."""
    monkeypatch.setattr(rec, "_OLD_WALK_PAGES", 2)
    f = _Reads(pages={(DEFAULT_ID, ""): ([], "c2"), (DEFAULT_ID, "c2"): ([], "c3")})
    monkeypatch.setattr(core, "_rest_get", f.get)
    monkeypatch.setattr(core, "model_bookmarks_gql",
                        _OldList({"": ([_old_row("1873306400000000009", "Moth")], None)}))
    assert rec.model_old_bookmarks(object(), object(), OWNER, "lora") == {"rows": [],
                                                                         "partial": True}


def test_the_model_picker_merges_no_chat_or_video_rows(monkeypatch):
    f = _Reads(pages={(DEFAULT_ID, ""): ([], None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    rows = [dict(_old_row("1873306400000000011", "Chatty"), type="CHAT"),
            dict(_old_row("1873306400000000012", "Haze Mix"), type="SDXL_MODEL")]
    monkeypatch.setattr(core, "model_bookmarks_gql", _OldList({"": (rows, None)}))
    out = rec.model_old_bookmarks(object(), object(), OWNER, "base")
    assert [r["title"] for r in out["rows"]] == ["Haze Mix"]


def test_the_old_route_reads_the_merge(tmp_path, monkeypatch):
    cli, _ = _logged_in(tmp_path, monkeypatch)
    f = _Reads(pages={(DEFAULT_ID, ""): ([], None)})
    monkeypatch.setattr(core, "_rest_get", f.get)
    monkeypatch.setattr(core, "model_bookmarks_gql",
                        _OldList({"": ([_old_row(LORA_ID, "Glasswing")], None)}))
    d = cli.get("/api/model-saved/old?kind=lora").get_json()
    assert [r["model_id"] for r in d["rows"]] == [LORA_ID] and d["partial"] is False

"""Free "cards" (kaisuuken) support. Pinned to the REAL oRPC /v2 REST surface
(verified 2026-07-03): GET /v2/kaisuuken/summary lists template rows; POST
/v2/kaisuuken/check returns matching ticket ids for a generation's params; the tool
attaches that id (kaisuukenId) so the card is spent instead of credits. Pure/mocked --
no live network (conftest blocks _rest_get/_rest_post), no spend."""
from types import SimpleNamespace

import pytest

import moonglade_backup as core


# ---- _normalize_kaisuuken: the real summary template-row shape ----

def test_normalize_real_shape_model_card():
    n = core._normalize_kaisuuken({
        "count": 16, "categoryName": "Model Card", "templateName": "Tsubaki.2 Only",
        "templateCode": "common-tsubaki-2", "taskTypes": ["image-gen"],
        "templateId": "019cd6f2-f5f3-7616-9c42-2c3fa1c2336a",
        "routeToNative": "pixai://generator/image?modelVersionId=1983308862240288769",
        "soonestExpireAt": "2026-07-06T17:56:10.548Z"})
    assert n["name"] == "Tsubaki.2 Only" and n["count"] == 16
    assert n["category"] == "Model Card" and n["task_types"] == ["image-gen"]
    assert n["model_version_id"] == "1983308862240288769"   # pulled from routeToNative
    assert n["template_id"] == "019cd6f2-f5f3-7616-9c42-2c3fa1c2336a"
    assert n["expires"].startswith("2026-07-06")


def test_normalize_video_card_has_no_model_route():
    n = core._normalize_kaisuuken({
        "count": 10, "categoryName": "Video Card", "templateName": "V4.0 Preview Lite Only",
        "taskTypes": ["i2vpro", "reference-video"], "routeToNative": None,
        "soonestExpireAt": "2026-08-01T23:41:39.186Z"})
    assert n["count"] == 10 and n["model_version_id"] == ""
    assert n["task_types"] == ["i2vpro", "reference-video"]


# ---- list_kaisuukens: GET /v2/kaisuuken/summary, soft-fail ----

def test_list_kaisuukens_from_summary(pixai):
    pixai.on("/kaisuuken/summary", {
        "kaisuukens": [{"count": 16, "templateName": "Tsubaki.2 Only", "categoryName": "Model Card",
                        "routeToNative": "pixai://x?modelVersionId=123"}]})
    cards = core.list_kaisuukens(pixai)
    assert len(cards) == 1 and cards[0]["count"] == 16 and cards[0]["model_version_id"] == "123"


def test_list_kaisuukens_fails_soft(pixai):
    pixai.fail("/kaisuuken/summary", core.PixAIError("network down"))
    assert core.list_kaisuukens(pixai) == []   # error => [] not a crash


# ---- match_kaisuuken: POST /v2/kaisuuken/check -> nearest-expiry ticket id ----

_MATCH_RESP = {"matches": [{"templateId": "tpl-1", "total": 16, "kaisuukens": [
    {"id": "id-late", "expiresAt": "2026-07-09T16:19:36.362Z"},
    {"id": "id-soon", "expiresAt": "2026-07-06T17:56:10.548Z"},   # nearest expiry
    {"id": "id-mid", "expiresAt": "2026-07-07T18:45:34.760Z"},
]}], "total": 16}


def test_match_picks_nearest_expiry(pixai):
    pixai.on("/kaisuuken/check", _MATCH_RESP)
    best = core.match_kaisuuken(pixai, {"modelId": "1983308862240288769"})
    assert best["id"] == "id-soon"                    # soonest expiry wins
    assert best["templateId"] == "tpl-1" and best["total"] == 16
    sent, = pixai.calls
    assert sent.path == "/kaisuuken/check" and sent.verb == "rest_post"
    assert sent.body["type"] == "generation-task"
    assert sent.body["parameters"] == {"modelId": "1983308862240288769"}


def test_match_no_matches_returns_none(pixai):
    pixai.on("/kaisuuken/check", {"matches": [], "total": 0})
    assert core.match_kaisuuken(pixai, {"modelId": "x"}) is None


def test_target_model_id_reads_top_level_and_chat():
    assert core._target_model_id({"modelId": "111"}) == "111"
    assert core._target_model_id({"chat": {"modelId": "222"}}) == "222"   # instruct edit
    assert core._target_model_id({}) == "" and core._target_model_id(None) == ""


# When several cards are eligible, enrich=True must PREFER the one locked to the gen's model.
_TWO_CARDS = {"matches": [
    {"templateId": "tpl-edit", "total": 17, "kaisuukens": [
        {"id": "edit-tkt", "expiresAt": "2026-07-17T20:00:00Z"}]},          # later expiry
    {"templateId": "tpl-ref", "total": 5, "kaisuukens": [
        {"id": "ref-tkt", "expiresAt": "2026-07-16T20:00:00Z"}]},           # SOONER expiry
], "total": 22}

_SUMMARY = [
    {"template_id": "tpl-edit", "name": "Edit Pro Only", "model_version_id": "2006468692917575683"},
    {"template_id": "tpl-ref", "name": "Reference Pro Only", "model_version_id": "1948514378441961474"},
]


def test_match_enrich_prefers_model_matching_card(monkeypatch, pixai):
    """Both cards match + the Reference one expires SOONER. Old behavior grabbed nearest-
    expiry (Reference). enrich=True must instead pick the EDIT card because the generation
    targets the Edit Pro model -- so an edit spends an Edit card, not a Reference one."""
    pixai.on("/kaisuuken/check", _TWO_CARDS)
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: _SUMMARY)
    edit_params = core.build_chat_edit_parameters("x", ["10"])   # chat.modelId = Edit Pro
    best = core.match_kaisuuken(pixai, edit_params, enrich=True)
    assert best["id"] == "edit-tkt" and best["templateId"] == "tpl-edit"
    assert best["name"] == "Edit Pro Only"                       # honest label data


def test_match_without_enrich_keeps_nearest_expiry(monkeypatch, pixai):
    """Default (enrich=False) is unchanged: nearest-expiry across all matches, no summary
    call, no name -- so existing callers behave exactly as before."""
    pixai.on("/kaisuuken/check", _TWO_CARDS)
    monkeypatch.setattr(core, "list_kaisuukens",
                        lambda s: (_ for _ in ()).throw(AssertionError("must not fetch summary")))
    best = core.match_kaisuuken(pixai, core.build_chat_edit_parameters("x", ["10"]))
    assert best["id"] == "ref-tkt"                               # sooner expiry wins, model-blind
    assert "name" not in best


def test_match_enrich_falls_back_when_no_model_match(monkeypatch, pixai):
    """enrich=True but the gen's model matches NO eligible card's model -> don't drop the
    free card; fall back to nearest-expiry across all (still names it)."""
    pixai.on("/kaisuuken/check", _TWO_CARDS)
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: _SUMMARY)
    best = core.match_kaisuuken(pixai, {"modelId": "9999-unknown"}, enrich=True)
    assert best["id"] == "ref-tkt"                               # nearest-expiry fallback
    assert best["name"] == "Reference Pro Only"


def test_match_fails_soft(pixai):
    pixai.fail("/kaisuuken/check", core.PixAIError("400"))
    assert core.match_kaisuuken(pixai, {"modelId": "x"}) is None


def test_match_empty_params_returns_none():
    assert core.match_kaisuuken(object(), {}) is None


# ---- _apply_kaisuuken: precedence (explicit > --no-card > auto-match) ----

def _args(**kw):
    base = dict(kaisuuken_id="", no_card=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_apply_explicit_id_wins(monkeypatch):
    # explicit id skips the match call entirely
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not match")))
    params = {"modelId": "m"}
    assert core._apply_kaisuuken(object(), params, _args(kaisuuken_id="forced")) == "forced"
    assert params["kaisuukenId"] == "forced"


def test_apply_no_card_pays_credits(monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not match")))
    params = {"modelId": "m"}
    assert core._apply_kaisuuken(object(), params, _args(no_card=True)) == ""
    assert "kaisuukenId" not in params


def test_apply_auto_match_attaches(monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken",
                        lambda s, p, enrich=False, **k: {"id": "id-soon", "expiresAt": "2026-07-06T00:00:00Z"})
    params = {"modelId": "1983308862240288769"}
    assert core._apply_kaisuuken(object(), params, _args()) == "id-soon"
    assert params["kaisuukenId"] == "id-soon"


def test_apply_no_match_pays_credits(monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p, enrich=False, **k: None)
    params = {"modelId": "m"}
    assert core._apply_kaisuuken(object(), params, _args()) == ""
    assert "kaisuukenId" not in params


def test_apply_kaisuuken_check_failure_aborts_instead_of_silently_paying(pixai):
    """A transient failure of the free-card check must NOT be treated as 'no card
    exists' at spend time -- match_kaisuuken's normal fail-soft contract collapses
    'genuinely no match' and 'the check itself errored' into the same None, and until
    now _apply_kaisuuken couldn't tell them apart, so a network hiccup silently spent
    real credits on a generation that may have been promised as free moments earlier.
    The fix retries once, then ABORTS the submission with a clear error instead of
    falling through to "no matching free card -> this will spend credits."."""
    pixai.fail("/kaisuuken/check", core.PixAIError("503 upstream hiccup"))
    params = {"modelId": "m"}
    with pytest.raises(core.PixAIError, match="Lost to the Void"):
        core._apply_kaisuuken(pixai, params, _args())
    assert "kaisuukenId" not in params
    # retried at least once before giving up rather than guessing
    assert len(pixai.calls_for("/kaisuuken/check")) >= 2


# ---- run_cards display (list_kaisuukens stubbed) ----

def test_run_cards_empty(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [])
    assert core.run_cards(SimpleNamespace(token=None)) == {"cards": 0}
    assert "No free cards" in capsys.readouterr().out


def test_run_cards_lists_with_total(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [
        {"name": "Tsubaki.2 Only", "count": 16, "category": "Model Card",
         "task_types": ["image-gen"], "model_version_id": "1983308862240288769",
         "template_code": "common-tsubaki-2", "template_id": "t1",
         "expires": "2026-07-06T17:56:10.548Z"},
        {"name": "Edit Pro Only", "count": 20, "category": "Model Card",
         "task_types": ["image-gen"], "model_version_id": "2006468692917575683",
         "template_code": "common-edit-pro", "template_id": "t2",
         "expires": "2026-07-17T20:11:09.504Z"}])
    res = core.run_cards(SimpleNamespace(token=None))
    out = capsys.readouterr().out
    assert res == {"cards": 2, "total": 36}                 # 16 + 20
    assert "Tsubaki.2 Only" in out and "16x" in out and "1983308862240288769" in out


# ---- kaisuukenId injection stays as an optional explicit override in the builders ----

def test_video_params_inject_kaisuuken():
    p = core.build_video_parameters("m", media_id="1", kaisuuken_id="card-9")
    assert p["kaisuukenId"] == "card-9" and "i2vPro" in p


def test_edit_params_inject_kaisuuken():
    p = core.build_chat_edit_parameters("x", ["10"], kaisuuken_id="card-7")
    assert p["kaisuukenId"] == "card-7" and "chat" in p


def test_params_no_kaisuuken_by_default():
    assert "kaisuukenId" not in core.build_video_parameters("m", media_id="1")


# ---- list_kaisuuken_logs: GET /v2/kaisuuken/logs -- the per-redemption "paper trail",
# distinct from /v2/kaisuuken/summary's live held-count. Verified live 2026-08-02. ----

def test_list_kaisuuken_logs_normalizes_real_shape(pixai):
    pixai.on("/kaisuuken/logs", {"data": [
            {"id": "rec-1", "kaisuukenId": "k-1", "templateCode": "common-tsubaki-2",
             "categoryCode": "Model Card", "templateName": "Tsubaki.2 Only",
             "taskType": "image-gen", "taskId": "2040084122530788759", "action": "consumed",
             "creditCost": 3200, "createdAt": "2026-07-31T17:16:00.000Z"},
    ], "pageInfo": {"hasNextPage": True, "endCursor": "cursor-abc"}})
    result = core.list_kaisuuken_logs(pixai, first=20)
    sent, = pixai.calls
    assert sent.path == "/kaisuuken/logs" and sent.params == {"first": 20}
    assert result["has_next"] is True and result["end_cursor"] == "cursor-abc"
    row = result["logs"][0]
    assert row["template_name"] == "Tsubaki.2 Only" and row["category"] == "Model Card"
    assert row["action"] == "consumed" and row["credit_cost"] == 3200
    assert row["task_id"] == "2040084122530788759"


def test_list_kaisuuken_logs_passes_cursor_when_given(pixai):
    pixai.on("/kaisuuken/logs", {"data": [], "pageInfo": {}})
    core.list_kaisuuken_logs(pixai, first=50, after="cursor-xyz")
    assert pixai.calls[0].params == {"first": 50, "after": "cursor-xyz"}


def test_list_kaisuuken_logs_fails_soft(pixai):
    pixai.fail("/kaisuuken/logs", core.PixAIError("network down"))
    assert core.list_kaisuuken_logs(pixai) == {
        "logs": [], "has_next": False, "end_cursor": None}


# ---- kaisuuken_type_catalog: page all the way back for the lifetime card-type roster --
# ("dig the entire crop" -- current holdings alone can't show a type that's fully cycled
# out, e.g. Reference Pro Only / Edit Pro Only both did exactly that between 2026-07-06
# and 2026-08-02.) ----

def test_kaisuuken_type_catalog_pages_until_exhausted(pixai):
    pages = [
        {"data": [
            {"templateName": "Tsubaki.2 Only", "categoryCode": "Model Card",
             "taskType": "image-gen", "action": "consumed",
             "createdAt": "2026-07-31T00:00:00Z"},
            {"templateName": "Edit Pro Only", "categoryCode": "Model Card",
             "taskType": "chat-edit", "action": "refunded",
             "createdAt": "2026-07-10T00:00:00Z"},
        ], "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"}},
        {"data": [
            {"templateName": "Edit Pro Only", "categoryCode": "Model Card",
             "taskType": "chat-edit", "action": "consumed",
             "createdAt": "2026-07-06T00:00:00Z"},
        ], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    ]
    calls = {"n": 0}

    def next_page(call):
        i = calls["n"]
        calls["n"] += 1
        return pages[i]

    pixai.on("/kaisuuken/logs", next_page)
    result = core.kaisuuken_type_catalog(pixai)
    assert result["pages_read"] == 2 and result["hit_page_cap"] is False
    assert set(result["templates"].keys()) == {"Tsubaki.2 Only", "Edit Pro Only"}
    edit_pro = result["templates"]["Edit Pro Only"]
    assert edit_pro["consumed"] == 1 and edit_pro["refunded"] == 1     # both events counted
    assert edit_pro["last_seen"] == "2026-07-10T00:00:00Z"             # newer of its 2 rows
    assert edit_pro["first_seen"] == "2026-07-06T00:00:00Z"            # older of its 2 rows


def test_kaisuuken_type_catalog_respects_page_cap(pixai):
    """A log that NEVER runs out (hasNextPage always True) must stop at max_pages, not hang
    -- an old account paging forever would otherwise hammer PixAI's API indefinitely."""
    pixai.on("/kaisuuken/logs",
             {"data": [{"templateName": "X", "categoryCode": "", "taskType": "",
                        "action": "consumed", "createdAt": "2026-01-01T00:00:00Z"}],
              "pageInfo": {"hasNextPage": True, "endCursor": "always-more"}})
    result = core.kaisuuken_type_catalog(pixai, max_pages=3)
    assert result["pages_read"] == 3 and result["hit_page_cap"] is True


def test_kaisuuken_type_catalog_empty_history(pixai):
    pixai.on("/kaisuuken/logs", {"data": [], "pageInfo": {"hasNextPage": False}})
    result = core.kaisuuken_type_catalog(pixai)
    assert result == {"templates": {}, "pages_read": 1, "hit_page_cap": False}


# ---- run_card_history display (list_kaisuuken_logs / kaisuuken_type_catalog stubbed) ----

def test_run_card_history_empty(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_kaisuuken_logs", lambda s, **k: {
        "logs": [], "has_next": False, "end_cursor": None})
    res = core.run_card_history(SimpleNamespace(token=None, card_history_all=False,
                                                 card_history_count=0))
    assert res == {"logs": 0}
    assert "No benefit-card history" in capsys.readouterr().out


def test_run_card_history_lists_recent(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_kaisuuken_logs", lambda s, **k: {
        "logs": [{"template_name": "Tsubaki.2 Only", "action": "consumed",
                  "task_id": "2040084122530788759", "created_at": "2026-07-31T17:16:00Z",
                  "category": "Model Card", "task_type": "image-gen", "credit_cost": 3200,
                  "record_id": "rec-1"}],
        "has_next": True, "end_cursor": "cursor-abc"})
    res = core.run_card_history(SimpleNamespace(token=None, card_history_all=False,
                                                 card_history_count=0))
    out = capsys.readouterr().out
    assert res == {"logs": 1}
    assert "Tsubaki.2 Only" in out and "consumed" in out and "2040084122530788759" in out
    assert "--card-history-all" in out            # points at how to see more


def test_run_card_history_all_prints_type_catalog(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "kaisuuken_type_catalog", lambda s, **k: {
        "templates": {
            "Tsubaki.2 Only": {"category": "Model Card", "task_type": "image-gen",
                                "consumed": 16, "refunded": 0,
                                "first_seen": "2026-07-29T00:00:00Z",
                                "last_seen": "2026-07-31T17:16:00Z"},
            "Edit Pro Only": {"category": "Model Card", "task_type": "chat-edit",
                               "consumed": 16, "refunded": 1,
                               "first_seen": "2026-07-06T00:00:00Z",
                               "last_seen": "2026-07-10T19:44:00Z"},
        }, "pages_read": 3, "hit_page_cap": False})
    res = core.run_card_history(SimpleNamespace(token=None, card_history_all=True,
                                                 card_history_count=0))
    out = capsys.readouterr().out
    assert res == {"templates": 2}
    assert "Tsubaki.2 Only" in out and "Edit Pro Only" in out
    assert "consumed=16" in out and "refunded=1" in out
    assert "kaisuukenId" not in core.build_chat_edit_parameters("x", ["10"])


# ---- issue #15: multi-ticket cards. /v2/kaisuuken/check `version: 2` is the site's own
# matcher (v1 answers `matches: []` for any i2vPro duration >= 10, so >5s videos went out
# card-less at full price). v2 returns `consumeAmount` = tickets the job COSTS; the server does
# NOT filter by balance, so coverage (held >= need) is decided in match_kaisuuken and read
# everywhere through the ONE predicate, card_covers. ----

_ABSENT = object()   # sentinel: leave consumeAmount out of the template entirely


def _v2_match(consume=_ABSENT, total=16, tid="tpl-1", kid="tkt-1", exp="2026-09-01T00:00:00Z"):
    mt = {"templateId": tid, "total": total,
          "kaisuukens": [{"id": kid, "expiresAt": exp}]}
    if consume is not _ABSENT:
        mt["consumeAmount"] = consume
    return mt


def _video_params(duration=15):
    return {"modelId": "vid-model", "i2vPro": {"duration": duration}}


def test_match_sends_version_2_generation_task(pixai):
    pixai.on("/kaisuuken/check", {"matches": [_v2_match()], "total": 16})
    core.match_kaisuuken(pixai, {"modelId": "m"})
    body = pixai.calls[0].body
    assert body["type"] == "generation-task"
    assert body["version"] == 2 and isinstance(body["version"], int)


@pytest.mark.parametrize("raw,need", [
    (_ABSENT, 1),   # absent -> v1 semantic: one job, one ticket
    (None, 1),      # explicit null
    (0, 1),         # 0 must never mean "costs nothing"
    ("2", 2),       # string from a loose serializer
    (2, 2),
])
def test_match_parses_consume_amount_defensively(pixai, raw, need):
    pixai.on("/kaisuuken/check", {"matches": [_v2_match(consume=raw)], "total": 16})
    best = core.match_kaisuuken(pixai, {"modelId": "m"})
    assert best["consumeAmount"] == need


@pytest.mark.parametrize("raw,held", [("5", 5), (None, None), (5, 5)])
def test_match_parses_total_defensively(pixai, raw, held):
    mt = _v2_match(consume=1, total=raw)
    pixai.on("/kaisuuken/check", {"matches": [mt]})              # no top-level total
    best = core.match_kaisuuken(pixai, {"modelId": "m"})
    assert best["total"] == held


def test_match_covered_when_held_at_least_need(pixai):
    pixai.on("/kaisuuken/check", {"matches": [_v2_match(consume=3, total=3)], "total": 3})
    best = core.match_kaisuuken(pixai, _video_params(15))
    assert best["covered"] is True and core.card_covers(best)


def test_match_not_covered_when_short(pixai):
    pixai.on("/kaisuuken/check", {"matches": [_v2_match(consume=3, total=2)], "total": 2})
    best = core.match_kaisuuken(pixai, _video_params(15))
    assert best is not None and best["id"] == "tkt-1"      # still named, for the honest note
    assert best["covered"] is False and not core.card_covers(best)
    assert best["consumeAmount"] == 3 and best["total"] == 2


def test_match_unknown_balance_covers_single_ticket_only(pixai):
    """Balance unknown: a 1-ticket job stays covered (today's behaviour -- not attaching when
    covered loses real credits); a multi-ticket VIDEO fails CLOSED (not covered)."""
    pixai.on("/kaisuuken/check", {"matches": [_v2_match(consume=1, total=None)]})
    assert core.card_covers(core.match_kaisuuken(pixai, {"modelId": "m"}))
    pixai.on("/kaisuuken/check", {"matches": [_v2_match(consume=3, total=None)]})
    best = core.match_kaisuuken(pixai, _video_params(15))
    assert best is not None and not core.card_covers(best)


def test_match_prefers_covering_template_over_nearer_expiry(pixai):
    """A: 2 held, expires SOONER. B: 5 held, expires later. Need 3 -> B, because coverage
    is decided before nearest-expiry (a short card must never shadow one that covers)."""
    pixai.on("/kaisuuken/check", {"matches": [
        _v2_match(consume=3, total=2, tid="tpl-A", kid="tkt-A", exp="2026-08-20T00:00:00Z"),
        _v2_match(consume=3, total=5, tid="tpl-B", kid="tkt-B", exp="2026-09-20T00:00:00Z"),
    ]})
    best = core.match_kaisuuken(pixai, _video_params(15))
    assert best["id"] == "tkt-B" and best["templateId"] == "tpl-B"
    assert core.card_covers(best)


def test_card_covers_predicate():
    assert core.card_covers(None) is False
    assert core.card_covers({"id": "x"}) is True                     # v1 stub: field absent
    assert core.card_covers({"id": "x", "covered": True}) is True
    assert core.card_covers({"id": "x", "covered": False}) is False


def test_card_short_note_wording():
    note = core.card_short_note({"consumeAmount": 3, "total": 2, "name": "V4.0 Lite"}, cost=1200)
    assert "you hold 2 of the 3 V4.0 Lite tickets this needs" in note
    assert "no card is used" in note and "full ~1,200 credits" in note
    assert "full credit price" in core.card_short_note({"consumeAmount": 3, "total": 2})


# ---- _apply_kaisuuken reads card_covers: attach ONE id when covered, nothing when short ----

def test_apply_covered_multi_ticket_attaches_single_id(monkeypatch, capsys):
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p, enrich=False, **k: {
        "id": "tkt-1", "expiresAt": "2026-09-01T00:00:00Z", "templateId": "tpl-1",
        "total": 5, "consumeAmount": 3, "covered": True, "name": "V4.0 Lite"})
    params = _video_params(15)
    assert core._apply_kaisuuken(object(), params, _args()) == "tkt-1"
    assert params["kaisuukenId"] == "tkt-1" and isinstance(params["kaisuukenId"], str)
    assert "kaisuukenIds" not in params                       # ONE singular id, never a list
    out = capsys.readouterr().out
    assert "uses 3 of 5 cards" in out and "0 credits" in out


def test_apply_short_attaches_nothing_and_prints_short_note(monkeypatch, capsys):
    """Owner ruling: short = SPEND (like the site), attach nothing, say so honestly."""
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p, enrich=False, **k: {
        "id": "tkt-1", "expiresAt": "2026-09-01T00:00:00Z", "templateId": "tpl-1",
        "total": 2, "consumeAmount": 3, "covered": False, "name": "V4.0 Lite"})
    monkeypatch.setattr(core, "price_task", lambda s, p: 1200)
    params = _video_params(15)
    assert core._apply_kaisuuken(object(), params, _args()) == ""
    assert "kaisuukenId" not in params and "kaisuukenIds" not in params
    out = capsys.readouterr().out
    assert "you hold 2 of the 3 V4.0 Lite tickets" in out
    assert "no card is used" in out and "full ~1,200 credits" in out
    assert "costs 0 credits" not in out and "free card matches" not in out   # never shown as free


# ---- _preview_card_note: the CLI preview must agree with the spend path ----

def test_preview_free_when_covered_names_n_of_h(monkeypatch, capsys, pixai):
    seen = {}
    def fake_match(s, p, enrich=False, **k):
        seen["enrich"] = enrich
        return {"id": "tkt-1", "expiresAt": "2026-09-01T00:00:00Z", "templateId": "tpl-1",
                "total": 5, "consumeAmount": 3, "covered": True, "name": "V4.0 Lite"}
    monkeypatch.setattr(core, "match_kaisuuken", fake_match)
    monkeypatch.setattr(core, "price_task", lambda s, p: 1200)
    core._preview_card_note(_args(token=None), _video_params(15))
    out = capsys.readouterr().out
    assert seen["enrich"] is True                              # same template as the spend path
    assert out.startswith("FREE: V4.0 Lite covers this")
    assert "uses 3 of 5 cards" in out and "0 credits" in out and "saves ~1,200 credits" in out


def test_preview_not_free_when_short(monkeypatch, capsys, pixai):
    """BLOCKER before #15: any match printed FREE, so a short 15s clip was promised free
    right before --confirm spent the full price."""
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p, enrich=False, **k: {
        "id": "tkt-1", "expiresAt": "2026-09-01T00:00:00Z", "templateId": "tpl-1",
        "total": 2, "consumeAmount": 3, "covered": False, "name": "V4.0 Lite"})
    monkeypatch.setattr(core, "price_task", lambda s, p: 1200)
    core._preview_card_note(_args(token=None), _video_params(15))
    out = capsys.readouterr().out
    assert out.startswith("NOT free -- ")
    assert "you hold 2 of the 3 V4.0 Lite tickets" in out and "no card is used" in out
    assert "full ~1,200 credits" in out and "--confirm" in out
    assert "FREE:" not in out


def test_run_cards_explains_multi_ticket_videos(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [
        {"name": "V4.0 Preview Lite Only", "count": 2, "category": "Video Card",
         "task_types": ["i2vpro"], "model_version_id": "", "template_code": "v4-lite",
         "template_id": "t3", "expires": "2026-09-01T00:00:00Z"}])
    core.run_cards(SimpleNamespace(token=None))
    out = capsys.readouterr().out
    assert "15s clip needs 3" in out and "FULL credit price" in out


# ---- 2026-08-16 xhigh review of the #15 branch: the four Python spend-path fixes ----

def test_price_task_fails_soft_on_a_network_error_not_just_pixai_errors(pixai):
    """price_task caught only (PixAIError, ValueError); a requests.RequestException from the
    raw session.get escaped -- and it is called from _apply_kaisuuken's SHORT branch, INSIDE
    the spend path, so a transient timeout there aborted a confirmed submit with a traceback."""
    import requests
    pixai.fail("/task-price", requests.exceptions.ConnectionError("reset"))
    assert core.price_task(pixai, {"modelId": "m", "width": 512}) is None


def test_apply_short_branch_never_aborts_the_submit_when_the_cost_lookup_raises(monkeypatch, capsys):
    """Belt on top of price_task's own fail-soft: the SHORT branch's cost lookup is diagnostic
    only, so NOTHING it raises may abort the spend it describes -- the number just drops out."""
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p, enrich=False, **k: {
        "id": "tkt-1", "expiresAt": "2026-09-01T00:00:00Z", "templateId": "tpl-1",
        "total": 2, "consumeAmount": 3, "covered": False, "name": "V4.0 Lite"})
    def boom(s, p):
        raise RuntimeError("anything at all")
    monkeypatch.setattr(core, "price_task", boom)
    params = _video_params(15)
    assert core._apply_kaisuuken(object(), params, _args()) == ""     # proceeds, does not raise
    assert "kaisuukenId" not in params
    out = capsys.readouterr().out
    assert "you hold 2 of the 3 V4.0 Lite tickets" in out and "full credit price" in out


def test_match_never_credits_a_template_with_the_top_level_pool_sum(pixai):
    """The response's top-level `total` is the SUM across matched templates (_TWO_CARDS: 17+5=22).
    Falling back to it when a match lacks its own `total` credited every template with the whole
    pool: a 5-held template read as covering a 6-ticket job, both landed in covered_pool, and
    nearest-expiry then picked the SHORT one -- manufactured coverage + defeated the
    coverage-first ordering (review, reproduced). Now: per-match total, else summary count, else
    None (the unknown-balance policy) -- never the pool sum."""
    a = _v2_match(consume=6, total=None, tid="tpl-a", kid="a-tkt", exp="2026-09-01T00:00:00Z")
    a.pop("total")                                            # per-match total ABSENT
    b = _v2_match(consume=6, total=None, tid="tpl-b", kid="b-tkt", exp="2026-09-09T00:00:00Z")
    b.pop("total")
    pixai.on("/kaisuuken/check", {"matches": [a, b], "total": 22})
    best = core.match_kaisuuken(pixai, _video_params(30))      # no enrich -> no summary count
    assert best["total"] is None, "the pool sum must NOT become a per-template balance"
    assert best["balance_unknown"] is True
    assert best["covered"] is False, "multi-ticket + unknown balance fails CLOSED, never 'covered by the pool sum'"


def test_match_per_match_total_null_does_not_fall_to_the_pool_sum_either(pixai):
    """dict.get's default only fires when the key is ABSENT; an explicit null must behave the
    same as absent (unknown), and in neither case borrow the top-level sum."""
    mt = _v2_match(consume=3, total=None)                     # key present, value None
    pixai.on("/kaisuuken/check", {"matches": [mt], "total": 22})
    best = core.match_kaisuuken(pixai, _video_params(15))
    assert best["total"] is None and best["balance_unknown"] is True and best["covered"] is False


def test_unknown_balance_is_the_general_rule_not_a_video_special_case(pixai):
    """A multi-ticket NON-video job with an unread balance must fail closed the same way -- the
    old code special-cased video (`is_video and need > 1`), so a future multi-ticket edit/batch
    card would have been marked covered on an unknown balance."""
    mt = _v2_match(consume=2)
    mt.pop("total")
    pixai.on("/kaisuuken/check", {"matches": [mt]})
    best = core.match_kaisuuken(pixai, {"modelId": "m", "chat": {"modelId": "m"}})   # not video
    assert best["covered"] is False and best["balance_unknown"] is True
    # ...and a 1-ticket job on an unknown balance is still covered (the v1 world that always worked).
    mt1 = _v2_match(consume=1)
    mt1.pop("total")
    pixai.on("/kaisuuken/check", {"matches": [mt1]})
    assert core.match_kaisuuken(pixai, {"modelId": "m"})["covered"] is True


def test_short_note_says_unknown_when_the_balance_was_not_read():
    """'you hold ? ... not enough' asserted a fact nobody read. Unknown is worded as unknown."""
    note = core.card_short_note({"consumeAmount": 3, "total": None, "balance_unknown": True,
                                 "name": "V4.0 Lite"}, 82500)
    assert "couldn't read how many V4.0 Lite tickets you hold" in note
    assert "not enough" not in note and "?" not in note
    assert "no card will be attached" in note and "full ~82,500 credits" in note
    # A genuinely short one still says short.
    short = core.card_short_note({"consumeAmount": 3, "total": 2, "name": "V4.0 Lite"}, 82500)
    assert "you hold 2 of the 3 V4.0 Lite tickets" in short and "not enough" in short


def test_preview_explicit_kaisuuken_id_does_not_promise_zero_credits(capsys):
    """--kaisuuken-id is FORCED: attached as given, coverage unchecked. It used to print
    '-> 0 credits' unconditionally -- a multi-ticket clip on an under-funded template shown as
    free (review gap sweep). It must say what is and isn't guaranteed."""
    core._preview_card_note(_args(token=None, kaisuuken_id="tkt-forced"), _video_params(15))
    out = capsys.readouterr().out
    assert "-> 0 credits" not in out and "0 credits" not in out
    assert "Coverage is NOT checked" in out and "full credit price" in out


def test_uses_note_only_for_multi_ticket_jobs():
    """'uses N of H cards' is gated on need > 1 everywhere (matches the web badge), so a
    1-ticket image reads 'covers this' on the CLI too -- not 'uses 1 of 16 cards'."""
    assert core._card_uses_note({"consumeAmount": 1, "total": 16}) == ""
    assert core._card_uses_note({"consumeAmount": 3, "total": 5}) == "uses 3 of 5 cards; "
    assert core._card_uses_note({"consumeAmount": 3, "total": None}) == "uses 3 of ? cards; "

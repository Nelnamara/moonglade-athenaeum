"""Free "cards" (kaisuuken) support. Pinned to the REAL oRPC /v2 REST surface
(verified 2026-07-03): GET /v2/kaisuuken/summary lists template rows; POST
/v2/kaisuuken/check returns matching ticket ids for a generation's params; the tool
attaches that id (kaisuukenId) so the card is spent instead of credits. Pure/mocked --
no live network (conftest blocks _rest_get/_rest_post), no spend."""
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core


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

def test_list_kaisuukens_from_summary(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: {
        "kaisuukens": [{"count": 16, "templateName": "Tsubaki.2 Only", "categoryName": "Model Card",
                        "routeToNative": "pixai://x?modelVersionId=123"}]})
    cards = core.list_kaisuukens(object())
    assert len(cards) == 1 and cards[0]["count"] == 16 and cards[0]["model_version_id"] == "123"


def test_list_kaisuukens_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise core.PixAIError("network down")
    monkeypatch.setattr(core, "_rest_get", boom)
    assert core.list_kaisuukens(object()) == []   # error => [] not a crash


# ---- match_kaisuuken: POST /v2/kaisuuken/check -> nearest-expiry ticket id ----

_MATCH_RESP = {"matches": [{"templateId": "tpl-1", "total": 16, "kaisuukens": [
    {"id": "id-late", "expiresAt": "2026-07-09T16:19:36.362Z"},
    {"id": "id-soon", "expiresAt": "2026-07-06T17:56:10.548Z"},   # nearest expiry
    {"id": "id-mid", "expiresAt": "2026-07-07T18:45:34.760Z"},
]}], "total": 16}


def test_match_picks_nearest_expiry(monkeypatch):
    seen = {}
    def fake_post(s, path, body, **k):
        seen["path"] = path
        seen["body"] = body
        return _MATCH_RESP
    monkeypatch.setattr(core, "_rest_post", fake_post)
    best = core.match_kaisuuken(object(), {"modelId": "1983308862240288769"})
    assert best["id"] == "id-soon"                    # soonest expiry wins
    assert best["templateId"] == "tpl-1" and best["total"] == 16
    assert seen["path"] == "/kaisuuken/check"
    assert seen["body"]["type"] == "generation-task"
    assert seen["body"]["parameters"] == {"modelId": "1983308862240288769"}


def test_match_no_matches_returns_none(monkeypatch):
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: {"matches": [], "total": 0})
    assert core.match_kaisuuken(object(), {"modelId": "x"}) is None


def test_match_fails_soft(monkeypatch):
    monkeypatch.setattr(core, "_rest_post",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("400")))
    assert core.match_kaisuuken(object(), {"modelId": "x"}) is None


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
                        lambda s, p: {"id": "id-soon", "expiresAt": "2026-07-06T00:00:00Z"})
    params = {"modelId": "1983308862240288769"}
    assert core._apply_kaisuuken(object(), params, _args()) == "id-soon"
    assert params["kaisuukenId"] == "id-soon"


def test_apply_no_match_pays_credits(monkeypatch):
    monkeypatch.setattr(core, "match_kaisuuken", lambda s, p: None)
    params = {"modelId": "m"}
    assert core._apply_kaisuuken(object(), params, _args()) == ""
    assert "kaisuukenId" not in params


# ---- run_cards display (list_kaisuukens stubbed) ----

def test_run_cards_empty(monkeypatch, capsys):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_kaisuukens", lambda s: [])
    assert core.run_cards(SimpleNamespace(token=None)) == {"cards": 0}
    assert "No free cards" in capsys.readouterr().out


def test_run_cards_lists_with_total(monkeypatch, capsys):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
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
    assert "kaisuukenId" not in core.build_chat_edit_parameters("x", ["10"])

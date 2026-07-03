"""Free "cards" (kaisuuken) support. Pinned to the REAL verified response shape
(2026-07-02): one row per TEMPLATE with a held `count`, model-locked via routeToNative,
applied AUTOMATICALLY on the matching model. Pure/mocked -- no live network, no spend."""
from types import SimpleNamespace

import pixai_gallery_backup as core


# ---- _normalize_kaisuuken: the real template-row shape ----

def test_normalize_real_shape_model_card():
    n = core._normalize_kaisuuken({
        "count": 16, "categoryName": "Model Card", "templateName": "Tsubaki.2 Only",
        "templateCode": "common-tsubaki-2", "taskTypes": ["image-gen"],
        "routeToNative": "pixai://generator/image?modelVersionId=1983308862240288769",
        "soonestExpireAt": "2026-07-06T17:56:10.548Z"})
    assert n["name"] == "Tsubaki.2 Only" and n["count"] == 16
    assert n["category"] == "Model Card" and n["task_types"] == ["image-gen"]
    assert n["model_version_id"] == "1983308862240288769"   # pulled from routeToNative
    assert n["expires"].startswith("2026-07-06")


def test_normalize_video_card_has_no_model_route():
    n = core._normalize_kaisuuken({
        "count": 10, "categoryName": "Video Card", "templateName": "V4.0 Preview Lite Only",
        "taskTypes": ["i2vpro", "reference-video"], "routeToNative": None,
        "soonestExpireAt": "2026-08-01T23:41:39.186Z"})
    assert n["count"] == 10 and n["model_version_id"] == ""
    assert n["task_types"] == ["i2vpro", "reference-video"]


# ---- list_kaisuukens: top-level query, me{} fallback, soft-fail ----

def test_list_kaisuukens_top_level(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {
        "kaisuukens": [{"count": 16, "templateName": "Tsubaki.2 Only", "categoryName": "Model Card",
                        "routeToNative": "pixai://x?modelVersionId=123"}]})
    cards = core.list_kaisuukens(object())
    assert len(cards) == 1 and cards[0]["count"] == 16 and cards[0]["model_version_id"] == "123"


def test_list_kaisuukens_me_fallback(monkeypatch):
    def fake(session, q, variables=None, retries=3):
        if "me {" in q:
            return {"me": {"kaisuukens": [{"count": 5, "templateName": "X"}]}}
        raise core.PixAIError("Cannot query field 'kaisuukens' on type 'Query'")
    monkeypatch.setattr(core, "gql_adhoc", fake)
    cards = core.list_kaisuukens(object())
    assert len(cards) == 1 and cards[0]["count"] == 5


def test_list_kaisuukens_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise core.PixAIError("schema drift")
    monkeypatch.setattr(core, "gql_adhoc", boom)
    assert core.list_kaisuukens(object()) == []   # both forms fail => [] not a crash


# ---- run_cards display ----

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
         "template_code": "common-tsubaki-2", "expires": "2026-07-06T17:56:10.548Z"},
        {"name": "V4.0 Preview Lite Only", "count": 10, "category": "Video Card",
         "task_types": ["i2vpro"], "model_version_id": "", "template_code": "common-video-4-lite",
         "expires": "2026-08-01T23:41:39.186Z"}])
    res = core.run_cards(SimpleNamespace(token=None))
    out = capsys.readouterr().out
    assert res == {"cards": 2, "total": 26}                 # 16 + 10
    assert "Tsubaki.2 Only" in out and "16x" in out and "1983308862240288769" in out


# ---- kaisuukenId injection stays as an optional explicit override ----

def test_video_params_inject_kaisuuken():
    p = core.build_video_parameters("m", media_id="1", kaisuuken_id="card-9")
    assert p["kaisuukenId"] == "card-9" and "i2vPro" in p


def test_edit_params_inject_kaisuuken():
    p = core.build_chat_edit_parameters("x", ["10"], kaisuuken_id="card-7")
    assert p["kaisuukenId"] == "card-7" and "chat" in p


def test_params_no_kaisuuken_by_default():
    assert "kaisuukenId" not in core.build_video_parameters("m", media_id="1")
    assert "kaisuukenId" not in core.build_chat_edit_parameters("x", ["10"])

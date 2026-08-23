"""Coupons ("Credit Boost", extra-package-boosts). A reward type SEPARATE from kaisuuken
benefit cards -- verified live 2026-08-02: GET /v2/extra-package-boosts is its own resource,
a percentage bonus tied to an Extra Package (credit-pack) purchase, not a free generation.
Pure/mocked -- no live network (conftest blocks _rest_get/_rest_post), no spend."""
from types import SimpleNamespace

import moonglade_backup as core


# ---- list_extra_package_boosts: GET /v2/extra-package-boosts, soft-fail ----

def test_list_extra_package_boosts_normalizes_real_shape(monkeypatch):
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen["path"] = path
        seen["params"] = params
        return {"data": [
            {"id": "b-1", "templateId": "t-1", "userId": "u-1", "code": "SUMMER50",
             "boostRatePercentage": 50, "grantSourceType": "event", "grantSourceId": "ev-1",
             "issuedBy": "event", "note": "Summer promotion credit boost",
             "status": "redeemed", "lockedAt": "2026-08-01T22:37:00Z",
             "redeemedAt": "2026-08-01T22:38:00Z", "lockedForOrderId": "order-1",
             "availableSince": "2026-08-01T00:00:00Z",
             "availableUntil": "2026-08-02T00:00:00Z",
             "createdAt": "2026-08-01T00:00:00Z", "updatedAt": "2026-08-01T22:38:00Z"},
        ], "pageInfo": {"hasNextPage": False, "endCursor": None}}

    monkeypatch.setattr(core, "_rest_get", fake_get)
    result = core.list_extra_package_boosts(object())
    assert seen["path"] == "/extra-package-boosts"
    assert result["has_next"] is False
    row = result["coupons"][0]
    assert row["boost_percent"] == 50 and row["status"] == "redeemed"
    assert row["issued_by"] == "event" and row["locked_for_order_id"] == "order-1"


def test_list_extra_package_boosts_uses_bracket_status_params(monkeypatch):
    """PixAI's own web client sends status[0]=redeemed&status[1]=expired (verified via
    live network capture) -- plain repeated `status=` params (requests' normal list
    serialization) is NOT the shape their server was observed accepting."""
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen["params"] = params
        return {"data": [], "pageInfo": {}}

    monkeypatch.setattr(core, "_rest_get", fake_get)
    core.list_extra_package_boosts(object(), statuses=("redeemed", "expired"), first=50)
    assert seen["params"] == {"first": 50, "status[0]": "redeemed", "status[1]": "expired"}


def test_list_extra_package_boosts_defaults_to_on_hand(monkeypatch):
    """The primary ask is "what do I have on hand", not a spend history -- default statuses
    must be the ON-HAND pair (available/locked), not the history pair (redeemed/expired).
    Both confirmed via live network capture: the site's own "My Coupons" top list (current
    holdings) sends available/locked; its "View coupon history" accordion sends
    redeemed/expired."""
    seen = {}

    def fake_get(s, path, params=None, **k):
        seen["params"] = params
        return {"data": [], "pageInfo": {}}

    monkeypatch.setattr(core, "_rest_get", fake_get)
    core.list_extra_package_boosts(object())
    assert seen["params"] == {"first": 50, "status[0]": "available", "status[1]": "locked"}
    assert core.COUPON_STATUSES_ON_HAND == ("available", "locked")
    assert core.COUPON_STATUSES_HISTORY == ("redeemed", "expired")


def test_list_extra_package_boosts_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise core.PixAIError("network down")
    monkeypatch.setattr(core, "_rest_get", boom)
    assert core.list_extra_package_boosts(object()) == {
        "coupons": [], "has_next": False, "end_cursor": None}


# ---- run_coupons display (list_extra_package_boosts stubbed) ----

def test_run_coupons_empty(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_extra_package_boosts", lambda s, **k: {
        "coupons": [], "has_next": False, "end_cursor": None})
    assert core.run_coupons(SimpleNamespace(token=None, coupons_history=False)) == {
        "coupons": 0}
    assert "No currently-held coupons found" in capsys.readouterr().out


def test_run_coupons_history_flag_switches_statuses(monkeypatch, capsys, pixai):
    seen = {}

    def fake_list(s, statuses=None, **k):
        seen["statuses"] = statuses
        return {"coupons": [], "has_next": False, "end_cursor": None}

    monkeypatch.setattr(core, "list_extra_package_boosts", fake_list)
    core.run_coupons(SimpleNamespace(token=None, coupons_history=True))
    assert seen["statuses"] == core.COUPON_STATUSES_HISTORY
    assert "No past coupons found" in capsys.readouterr().out


def test_run_coupons_lists(monkeypatch, capsys, pixai):
    monkeypatch.setattr(core, "list_extra_package_boosts", lambda s, **k: {
        "coupons": [
            {"code": "SUMMER50", "boost_percent": 50, "status": "redeemed",
             "issued_by": "event", "note": "", "locked_for_order_id": "order-1",
             "available_since": "2026-08-01T00:00:00Z",
             "available_until": "2026-08-02T00:00:00Z", "created_at": "2026-08-01T00:00:00Z"},
            {"code": "EARLY15", "boost_percent": 15, "status": "expired",
             "issued_by": "event", "note": "", "locked_for_order_id": "",
             "available_since": "2026-07-30T00:00:00Z",
             "available_until": "2026-07-31T00:00:00Z", "created_at": "2026-07-30T00:00:00Z"},
        ], "has_next": False, "end_cursor": None})
    res = core.run_coupons(SimpleNamespace(token=None))
    out = capsys.readouterr().out
    assert res == {"coupons": 2}
    assert "+50%" in out and "redeemed" in out
    assert "+15%" in out and "expired" in out

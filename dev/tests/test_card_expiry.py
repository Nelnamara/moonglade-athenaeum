"""Session Y (lane R, #69): free cards about to expire (Y1c + Y2a, drift 130).

The card summary PixAI already answers (/v2/kaisuuken/summary) carries each held card type's
expiry dates, `expiryCounts: [{expiresAt, count}]`; the app used to keep only the soonest date.
These pin that the dates now reach /api/account's per-type breakdown, which the credits chip's
peach underline and its tooltip lines (and the phone's Gift box row) are drawn from. Nothing new
is read: the summary is the same call the chip already makes. No network: the `pixai` fixture."""
from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade.gallery import create_app
from moonglade.catalog import CATALOG_FIELDS, save_catalog
from tests.conftest import login_test_client
from moonglade import account_api as account_api_mod


def test_the_summary_keeps_every_expiry_date_per_card_type():
    n = cards_mod._normalize_kaisuuken({
        "count": 13, "templateName": "Tsubaki.3", "templateId": "t1",
        "soonestExpireAt": "2026-10-06T00:00:00Z",
        "expiryCounts": [{"expiresAt": "2026-10-06T00:00:00Z", "count": 5},
                         {"expiresAt": "2026-10-09T00:00:00Z", "count": 3},
                         {"expiresAt": None, "count": 5}, {"count": "x"}]})
    assert n["expiry_counts"] == [{"expires_at": "2026-10-06T00:00:00Z", "count": 5},
                                  {"expires_at": "2026-10-09T00:00:00Z", "count": 3}]


def test_a_summary_row_without_dates_has_none():
    assert cards_mod._normalize_kaisuuken({"count": 1, "templateName": "x"})["expiry_counts"] == []


def test_the_account_breakdown_carries_the_dates(tmp_path, monkeypatch, pixai):
    monkeypatch.setattr(account_api_mod, "account_info", lambda s: {"quotaAmount": 1})
    monkeypatch.setattr(cards_mod, "list_kaisuukens", lambda s: [
        {"name": "Tsubaki.3", "count": 5, "expires": "2026-10-06T00:00:00Z",
         "category": "Model Card",
         "expiry_counts": [{"expires_at": "2026-10-06T00:00:00Z", "count": 5}]},
        {"name": "Legacy", "count": 1, "expires": ""}])
    monkeypatch.setattr(account_api_mod, "list_claims", lambda s: [])
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {"media_id": "1"}])
    cli = login_test_client(create_app(tmp_path))
    d = cli.get("/api/account").get_json()
    assert d["cards_by"][0]["expiry_counts"] == [{"expires_at": "2026-10-06T00:00:00Z", "count": 5}]
    assert d["cards_by"][1]["expiry_counts"] == []

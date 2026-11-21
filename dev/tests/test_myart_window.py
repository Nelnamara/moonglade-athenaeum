"""My Art's 30-day window (owner pick 2026-11-19, look board round 2 topic 6 option A).

PixAI gives only a lifetime views/likes count and the catalog keeps only the latest reading, so a
30-day figure needs history the app did not keep. record_artwork_snapshots() keeps one row per
artwork per local day; myart_window() turns that into the gain over the window. What is pinned:

  * a sweep (apply_artwork_meta / apply_artwork_views) records today's reading, and a second
    write the same day replaces it rather than adding a row;
  * with no history the window says so (`seen` false), and the first read of the route takes a
    baseline, so the gain starts at zero from that day and `since` is that day, `full` false;
  * with fewer than 30 days the gain is "since the oldest reading" and `full` stays false (the
    surface says "since <date>", never a made-up 30); once a reading at least 30 days old exists
    the baseline is the newest one on or before the edge and `full` is true;
  * a never-swept view count is None, not 0, and a gain is never negative;
  * old rows are pruned past SNAPSHOT_KEEP_DAYS;
  * /api/myart/items carries views_30 / likes_30 and the window.
"""
import datetime as dt

import pytest

from moonglade import gallery as g
from moonglade.catalog import CATALOG_FIELDS, save_catalog
from moonglade import catalog as catalog_mod
from moonglade import catalog_verbs as catalog_verbs_mod

T0 = dt.date(2026, 12, 20)


def _row(mid, aid, **kw):
    return {f: "" for f in CATALOG_FIELDS} | {
        "media_id": mid, "artwork_id": aid, "is_published": "1", "liked_count": "0",
        "comment_count": "0"} | kw


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [_row("m1", "a1", views="1000", liked_count="10"),
                     _row("m2", "a2", liked_count="4")])           # a2: views never swept
    return p


def _set(db, aid, **cols):
    with catalog_mod.catalog(db) as con:
        for k, v in cols.items():
            con.execute("UPDATE catalog SET %s=? WHERE artwork_id=?" % k, (str(v), aid))
        con.commit()


def _days(db):
    with catalog_mod.catalog(db) as con:
        return [tuple(r) for r in con.execute(
            "SELECT artwork_id, day, views, likes FROM artwork_snapshots ORDER BY artwork_id, day")]


def test_a_snapshot_is_one_row_per_artwork_per_day_and_never_invents_views(db):
    assert catalog_verbs_mod.record_artwork_snapshots(db, today=T0) == 2
    assert _days(db) == [("a1", "2026-12-20", 1000, 10), ("a2", "2026-12-20", None, 4)]
    _set(db, "a1", views=1100)
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0)                      # same day: replaced
    assert _days(db)[0] == ("a1", "2026-12-20", 1100, 10)
    assert len(_days(db)) == 2


def test_with_no_history_there_is_no_window_yet(db):
    win, w = catalog_verbs_mod.myart_window(db, today=T0)
    assert w["seen"] is False and w["full"] is False and w["since"] == "2026-12-20"
    assert win["a1"] == {"views": 0, "likes": 0}
    assert win["a2"] == {"views": None, "likes": 0}


def test_under_thirty_days_the_gain_is_since_the_oldest_reading_and_not_full(db):
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=9))
    _set(db, "a1", views=1250, liked_count=13)
    _set(db, "a2", views=40)                                       # first swept 3 days ago
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=3))
    _set(db, "a1", views=1400, liked_count=15)
    _set(db, "a2", views=90)
    win, w = catalog_verbs_mod.myart_window(db, today=T0)
    assert w == {"days": 30, "since": "2026-12-11", "full": False, "seen": True}
    assert win["a1"] == {"views": 400, "likes": 5}
    # a2's baseline reading had no views: the first swept reading (40) is its baseline
    assert win["a2"] == {"views": 50, "likes": 0}


def test_with_thirty_days_of_history_the_window_is_full_and_uses_the_edge_reading(db):
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=45))     # views 1000
    _set(db, "a1", views=1300, liked_count=12)
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=31))     # the newest one on/before the edge
    _set(db, "a1", views=1500, liked_count=20)
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=10))
    _set(db, "a1", views=1800, liked_count=25)
    win, w = catalog_verbs_mod.myart_window(db, today=T0)
    assert w["full"] is True and w["since"] == "2026-11-05"
    assert win["a1"] == {"views": 500, "likes": 13}                       # 1800-1300, 25-12


def test_a_gain_never_goes_negative(db):
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=5))
    _set(db, "a1", views=900, liked_count=2)                              # PixAI took some away
    win, _w = catalog_verbs_mod.myart_window(db, today=T0)
    assert win["a1"] == {"views": 0, "likes": 0}


def test_old_readings_are_pruned(db):
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0 - dt.timedelta(days=catalog_verbs_mod.SNAPSHOT_KEEP_DAYS + 5))
    catalog_verbs_mod.record_artwork_snapshots(db, today=T0)
    assert {d for (_a, d, _v, _l) in _days(db)} == {"2026-12-20"}


def test_a_sweep_records_the_reading(db):
    catalog_verbs_mod.apply_artwork_views(db, {"a1": 1234}, "2026-12-20T00:00:00Z")
    assert any(r[0] == "a1" and r[2] == 1234 for r in _days(db))
    n = len(_days(db))
    catalog_verbs_mod.apply_artwork_meta(db, [{"media_id": "m1", "artwork_id": "a1", "title": "t", "liked_count": "11"}])
    assert len(_days(db)) == n                                            # same day: a rewrite, not a row
    assert [r for r in _days(db) if r[0] == "a1"][0][3] == 11


def test_the_route_carries_the_window_and_takes_a_first_baseline(tmp_path):
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [_row(
        "m1", "a1", views="1000", liked_count="10", created_at="2026-10-01T00:00:00Z")])
    c = login_client(tmp_path)
    j = c.get("/api/myart/items").get_json()
    # the very first read had no history: it took a baseline, so the gain starts at zero today
    assert j["window"] == {"days": 30, "since": dt.date.today().isoformat(), "full": False, "seen": True}
    it = j["items"][0]
    assert it["views"] == 1000 and it["views_30"] == 0 and it["likes_30"] == 0
    # a never-swept work stays None, not 0
    save_catalog(tmp_path / "catalog.db", [_row("m2", "a2", liked_count="3", created_at="2026-10-02T00:00:00Z")])
    j2 = c.get("/api/myart/items").get_json()
    assert [i for i in j2["items"] if i["artwork_id"] == "a2"][0]["views_30"] is None

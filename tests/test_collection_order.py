"""Session P, P6: manual order in a hand-picked collection (Loom Handoff section B's P6 prose;
BUILD-w5-p §5.4; ruling 9) -- and the readers that use it.

What these pin, in the order the lane's data-safety rules gave them:

  * ADDITIVE, IN PLACE. One new table (collection_order) arrives through _MIGRATIONS on an
    existing catalog; every catalog row is byte-for-byte what it was, and re-running is harmless.
    Membership stays the comma-joined `collections` label; adding to a collection writes nothing
    to the order table.
  * THE ORDER. Saved positions first; pictures added since go after them, OLDEST first (ruling
    9); a position whose picture has left the collection is ignored. Unordered hand-picked and
    smart collections read oldest first.
  * REFUSALS. A smart collection cannot be ordered (its membership is live); an id that is not a
    member, a repeat, an unknown collection: refused, nothing written. CSRF 403, LOGIN tier.
  * N's MANAGER CARRIES IT. Rename moves the order, delete drops it, merge keeps the target's.
  * READERS. The Contact sheet (both) and the collection view's "Manual" sort use it.
  * LOCAL ONLY: nothing here reaches the network or PixAI.
"""
import socket
import sqlite3

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import (
    CATALOG_FIELDS, CurationError, add_to_collection, delete_collection, load_catalog,
    merge_collections, ordered_members, query_catalog, remove_from_collection, rename_collection,
    save_catalog, save_smart_collection, set_collection_order, list_media_ids,
)
from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("the manual order reached for the network")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    for name in ("gql", "gql_adhoc", "gql_mutate", "_make_session", "submit", "submit_generation"):
        if hasattr(core, name):
            monkeypatch.setattr(core, name, _boom)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="1", filename="1.png", created_at="2026-07-01T12:00:00", collections="Stills,Other"),
        _row(media_id="2", filename="2.png", created_at="2026-07-02T12:00:00", collections="Stills"),
        _row(media_id="3", filename="3.png", created_at="2026-07-03T12:00:00", collections="Stills"),
        _row(media_id="4", filename="4.png", created_at="2026-07-04T12:00:00", collections="Stills", rating="5"),
        _row(media_id="5", filename="5.png", created_at="2026-07-05T12:00:00", collections="Other", rating="5"),
        _row(media_id="6", filename="6.png", created_at="2026-07-06T12:00:00"),
    ])
    return p


def _order_rows(db):
    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT name, media_id, position FROM collection_order ORDER BY name, position").fetchall()
    finally:
        con.close()


def _catalog_bytes(db):
    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT * FROM catalog ORDER BY media_id").fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------- data safety: migration

def test_an_existing_library_gains_the_table_and_every_row_stays_byte_for_byte(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE catalog ({})".format(", ".join(
        ("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f)) for f in CATALOG_FIELDS)))
    for i in range(1, 8):
        con.execute("INSERT INTO catalog (media_id, filename, collections, created_at, prompt_full, rating) "
                    "VALUES (?,?,?,?,?,?)", (str(i), "{}.png".format(i), "Stills,Keep", "2026-07-0%d" % i,
                                             "a prompt, with ☾ and \"quotes\"", str(i % 6)))
    con.commit()
    before = con.execute("SELECT * FROM catalog ORDER BY media_id").fetchall()
    count = con.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "collection_order" not in tables
    rows = load_catalog(p)                          # the first open runs _MIGRATIONS
    con = sqlite3.connect(str(p))
    try:
        assert "collection_order" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert con.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == count == len(rows)
        assert con.execute("SELECT * FROM catalog ORDER BY media_id").fetchall() == before
        assert con.execute("SELECT COUNT(*) FROM collection_order").fetchone()[0] == 0, "an empty table, nothing seeded"
    finally:
        con.close()
    g.migrate(p, force=True)
    assert _catalog_bytes(p) == before


def test_adding_to_a_collection_writes_no_order_and_reading_writes_nothing(db):
    before = _catalog_bytes(db)
    ordered_members(db, "Stills")
    ordered_members(db, "Other")
    query_catalog(db, collection="Stills", sort="manual")
    assert _order_rows(db) == [] and _catalog_bytes(db) == before, "nothing writes on open"
    add_to_collection(db, ["6"], "Stills")
    assert _order_rows(db) == []


# ---------------------------------------------------------------- the order

def test_unordered_collections_read_oldest_first(db):
    d = ordered_members(db, "Stills")
    assert d == {"name": "Stills", "kind": "hand", "media_ids": ["1", "2", "3", "4"], "manual": False}


def test_write_then_read_and_new_members_append_oldest_first(db):
    set_collection_order(db, "Stills", ["3", "1", "4", "2"])
    assert ordered_members(db, "Stills")["media_ids"] == ["3", "1", "4", "2"]
    assert ordered_members(db, "Stills")["manual"] is True
    add_to_collection(db, ["6"], "Stills")
    add_to_collection(db, ["5"], "Stills")
    assert ordered_members(db, "Stills")["media_ids"] == ["3", "1", "4", "2", "5", "6"], \
        "pictures added after the order go to the end, oldest first (ruling 9)"


def test_a_position_whose_picture_left_is_ignored_then_pruned(db):
    set_collection_order(db, "Stills", ["4", "3", "2", "1"])
    remove_from_collection(db, ["3"], "Stills")
    assert ordered_members(db, "Stills")["media_ids"] == ["4", "2", "1"]
    assert ("Stills", "3", 1) in _order_rows(db), "left in place until the next write"
    set_collection_order(db, "Stills", ["1", "2", "4"])
    assert [r[1] for r in _order_rows(db)] == ["1", "2", "4"], "the next write prunes it"


def test_the_write_is_whole_and_positions_run_0_to_n(db):
    set_collection_order(db, "Stills", ["2", "4"])
    assert _order_rows(db) == [("Stills", "2", 0), ("Stills", "4", 1)]
    assert ordered_members(db, "Stills")["media_ids"] == ["2", "4", "1", "3"]


def test_smart_collections_are_refused_and_read_oldest_first(db):
    save_smart_collection(db, "★5", name="Best")
    assert ordered_members(db, "Best") == {"name": "Best", "kind": "smart", "media_ids": ["4", "5"], "manual": False}
    with pytest.raises(CurationError, match="smart collection"):
        set_collection_order(db, "Best", ["5", "4"])
    assert _order_rows(db) == []


@pytest.mark.parametrize("ids,why", [(["1", "5"], "not in"), (["1", "1"], "once"), (["1", ""], "once")])
def test_non_members_and_repeats_are_refused(db, ids, why):
    with pytest.raises(CurationError, match=why):
        set_collection_order(db, "Stills", ids)
    assert _order_rows(db) == []


def test_an_unknown_collection_is_refused(db):
    with pytest.raises(CurationError, match="no hand-picked collection"):
        set_collection_order(db, "Nope", [])
    assert ordered_members(db, "Nope")["kind"] is None


# ---------------------------------------------------------------- N's manager carries it

def test_rename_moves_the_order(db):
    set_collection_order(db, "Stills", ["4", "2", "3", "1"])
    rename_collection(db, "Stills", "Loom stills")
    assert ordered_members(db, "Loom stills")["media_ids"] == ["4", "2", "3", "1"]
    assert {r[0] for r in _order_rows(db)} == {"Loom stills"}


def test_a_case_only_rename_keeps_it_too(db):
    set_collection_order(db, "Stills", ["4", "2", "3", "1"])
    rename_collection(db, "Stills", "stills")
    assert ordered_members(db, "stills")["media_ids"] == ["4", "2", "3", "1"]


def test_delete_drops_the_order(db):
    set_collection_order(db, "Stills", ["4", "2", "3", "1"])
    delete_collection(db, "Stills")
    assert _order_rows(db) == []
    add_to_collection(db, ["2", "1"], "Stills")         # a new collection of the same name starts fresh
    assert ordered_members(db, "Stills") == {"name": "Stills", "kind": "hand", "media_ids": ["1", "2"], "manual": False}


def test_merge_keeps_the_targets_order_and_merged_in_pictures_append(db):
    set_collection_order(db, "Stills", ["4", "3", "2", "1"])
    set_collection_order(db, "Other", ["5", "1"])
    merge_collections(db, ["Stills", "Other"])
    assert ordered_members(db, "Stills")["media_ids"] == ["4", "3", "2", "1", "5"]
    assert {r[0] for r in _order_rows(db)} == {"Stills"}, "the merged collection's order went with it"


# ---------------------------------------------------------------- the readers

def test_the_manual_sort_is_the_collections_order(db):
    set_collection_order(db, "Stills", ["3", "1"])
    rows, total = query_catalog(db, collection="Stills", sort="manual", page=1, page_size=2)
    assert [r["media_id"] for r in rows] == ["3", "1"] and total == 4
    rows, _ = query_catalog(db, collection="Stills", sort="manual", page=2, page_size=2)
    assert [r["media_id"] for r in rows] == ["2", "4"]
    assert list_media_ids(db, collection="Stills", sort="manual") == ["3", "1", "2", "4"]
    # no collection, or a smart one: the manual sort falls back to the default
    save_smart_collection(db, "★5", name="Best")
    assert [r["media_id"] for r in query_catalog(db, sort="manual", page_size=None)[0]][:2] == ["6", "5"]
    assert [r["media_id"] for r in query_catalog(db, collection="Best", sort="manual", page_size=None)[0]] == ["5", "4"]


@pytest.fixture
def client(tmp_path, db):
    cli = login_client(tmp_path)
    cli.csrf = cli.get("/api/account/prefs").get_json()["csrf"]
    return cli


def test_both_contact_sheets_follow_the_order(client, db):
    set_collection_order(db, "Stills", ["4", "2"])
    d = client.get("/api/contact-sheet?collection=Stills").get_json()
    assert [f["media_id"] for f in d["frames"]] == ["4", "2", "1", "3"]
    html = client.get("/contact-sheet?collection=Stills").get_data(as_text=True)
    at = [html.index("/thumbs/%s.jpg" % m) for m in ("4", "2", "1", "3")]
    assert at == sorted(at)
    assert "/thumbs/5.jpg" not in html


# ---------------------------------------------------------------- the routes

def test_order_routes_round_trip(client, db):
    g0 = client.get("/api/collections/order?name=Stills").get_json()
    assert g0 == {"name": "Stills", "kind": "hand", "media_ids": ["1", "2", "3", "4"], "manual": False}
    r = client.post("/api/collections/order", json={"csrf": client.csrf, "name": "Stills", "media_ids": ["2", "1", "4", "3"]})
    assert r.status_code == 200 and r.get_json()["media_ids"] == ["2", "1", "4", "3"] and r.get_json()["ok"]
    assert client.get("/api/collections/order?name=Stills").get_json()["manual"] is True
    assert client.get("/api/collections/order?name=Nope").status_code == 404


def test_order_route_refusals_write_nothing(client, db):
    save_smart_collection(db, "★5", name="Best")
    for body in ({"name": "Best", "media_ids": ["4", "5"]}, {"name": "Stills", "media_ids": ["1", "6"]},
                 {"name": "Stills", "media_ids": ["1", "1"]}, {"name": "Nope", "media_ids": []}):
        r = client.post("/api/collections/order", json=dict(body, csrf=client.csrf))
        assert r.status_code == 400 and r.get_json()["error"]
    assert _order_rows(db) == []


def test_order_post_needs_the_csrf_token(client, db):
    assert client.post("/api/collections/order", json={"name": "Stills", "media_ids": ["2", "1"]}).status_code == 403
    assert client.post("/api/collections/order", json={"csrf": "no", "name": "Stills", "media_ids": ["2"]}).status_code == 403
    assert _order_rows(db) == []


def test_order_routes_are_login_tier(tmp_path, db):
    anon = g.create_app(tmp_path).test_client()
    assert anon.get("/api/collections/order?name=Stills").status_code == 401
    assert anon.post("/api/collections/order", json={}).status_code == 401


def test_the_manage_route_carries_the_order(client, db):
    client.post("/api/collections/order", json={"csrf": client.csrf, "name": "Stills", "media_ids": ["4", "3", "2", "1"]})
    r = client.post("/api/collections/manage", json={"csrf": client.csrf, "action": "rename", "name": "Stills",
                                                      "new_name": "Loom stills"})
    assert r.get_json()["ok"]
    assert client.get("/api/collections/order?name=Loom%20stills").get_json()["media_ids"] == ["4", "3", "2", "1"]


def test_the_library_view_offers_it_through_its_sort(client, db):
    set_collection_order(db, "Stills", ["3", "1"])
    d = client.get("/api/next/library?collection=Stills&sort=manual").get_json()
    assert [it["media_id"] for it in d["items"]] == ["3", "1", "2", "4"]

"""Session N, Curation: smart collections, the collections manager, the personal layer
(tags / keeper|reject mark / note), the search operators that read it, and bulk curation
with an undo that restores each picture's OWN previous values.

What these tests pin, in the order the lane's data-safety rules gave them:

  * ADDITIVE, IN PLACE. Two new tables (personal_meta, smart_collections) arrive through
    _MIGRATIONS on an existing catalog; every row that was there is still there, unchanged,
    and re-running the migration is harmless.
  * LOCAL ONLY. Nothing on this surface reaches PixAI: the whole file runs with the network
    layer booby-trapped.
  * A SMART COLLECTION STORES A QUERY, NEVER MEMBERSHIP. Rate a picture and it is in; unrate
    it and it is out; nothing was written to the collection in between.
  * NOTHING DELETES A PICTURE. Deleting or merging a collection rewrites labels, and the
    catalog rows and files are counted before and after.
  * NOTHING WRITES ON OPEN. Listing collections, reading cards, opening a smart collection
    and searching leave every table byte-for-byte as it was.
"""
import socket
import sqlite3

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import (
    CATALOG_FIELDS, CurationError, curate_apply, curate_restore, delete_collection,
    list_media_ids, list_group_rows, load_catalog, merge_collections, normalize_tag,
    personal_get, query_catalog, rename_collection, save_smart_collection, save_catalog,
)
from tests.conftest import extract_login_csrf, login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _ids(db, **kw):
    return sorted(r["media_id"] for r in query_catalog(db, page_size=None, **kw)[0])


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="1", filename="1.png", prompt_full="night elf druid", rating="4",
             created_at="2026-07-04T12:00:00", art_tags="elf, moon", collections="Druid,Faves",
             width="1024", height="1536"),
        _row(media_id="2", filename="2.png", prompt_full="city at dawn", rating="",
             created_at="2026-07-03T12:00:00", collections="Druid"),
        _row(media_id="3", filename="3.png", prompt_full="owl in the moonwell", rating="5",
             created_at="2026-07-02T12:00:00", collections="Faves"),
        _row(media_id="4", filename="4.png", prompt_full="a blurry owl", rating="2",
             created_at="2026-07-01T12:00:00"),
    ])
    return p


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Curation is local. Any attempt to open a connection, or to call one of the PixAI
    helpers, fails the test that made it."""
    def _boom(*a, **k):
        raise AssertionError("curation reached for the network")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    for name in ("gql", "gql_adhoc", "gql_mutate", "_make_session"):
        if hasattr(core, name):
            monkeypatch.setattr(core, name, _boom)


def _tables(db):
    con = sqlite3.connect(str(db))
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _dump(db):
    con = sqlite3.connect(str(db))
    try:
        return {t: con.execute("SELECT * FROM {} ORDER BY 1".format(t)).fetchall()
                for t in ("catalog", "personal_meta", "smart_collections")}
    finally:
        con.close()


# ---------------------------------------------------------------- data safety: migration

def test_an_existing_library_gains_the_tables_and_loses_nothing(tmp_path):
    """A library built before this session: catalog only. One plain open brings the two new
    tables; every existing row -- rating, collections, prompt -- is exactly what it was."""
    p = tmp_path / "old.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE catalog ({})".format(", ".join(
        ("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f))
        for f in CATALOG_FIELDS)))
    for i in range(1, 6):
        con.execute("INSERT INTO catalog (media_id, filename, rating, collections, prompt_full) "
                    "VALUES (?,?,?,?,?)", (str(i), "{}.png".format(i), str(i % 6), "Keep,Me", "p{}".format(i)))
    con.commit()
    before = con.execute("SELECT * FROM catalog ORDER BY media_id").fetchall()
    con.close()
    assert "personal_meta" not in _tables(p) and "smart_collections" not in _tables(p)

    rows = load_catalog(p)                      # the first open runs _MIGRATIONS
    assert {"personal_meta", "smart_collections"} <= _tables(p)
    after = sqlite3.connect(str(p)).execute("SELECT * FROM catalog ORDER BY media_id").fetchall()
    assert after == before, "the migration touched an existing catalog row"
    assert len(rows) == 5
    g.migrate(p, force=True)                    # re-running the DDL stays harmless
    assert sqlite3.connect(str(p)).execute("SELECT * FROM catalog ORDER BY media_id").fetchall() == before


def test_opening_and_reading_writes_nothing(db):
    """Nothing writes on open: collection lists, smart evaluation, search and card reads
    leave every table exactly as it was."""
    save_smart_collection(db, "keeper")
    before = _dump(db)
    g.unique_collections(db)
    g.list_smart_collections(db)
    g.collection_summaries(db)
    query_catalog(db, q="keeper -reject tag:x note:y")
    query_catalog(db, collection="keeper")
    personal_get(db, ["1", "2"])
    assert _dump(db) == before


# ------------------------------------------------------------------ the personal layer

def test_normalize_tag_is_lowercase_and_hyphenated():
    assert normalize_tag("Pose Study") == "pose-study"
    assert normalize_tag("  Pose__Study!! ") == "pose-study"
    assert normalize_tag("a--b") == "a-b"
    assert normalize_tag("--x--") == "x"
    assert normalize_tag("!!!") == ""
    assert normalize_tag("ポーズ") == "ポーズ"       # any script survives


def test_a_mark_is_exclusive_and_none_clears_it(db):
    curate_apply(db, ["1"], {"mark": "keeper"})
    assert personal_get(db, ["1"])["1"]["mark"] == "keeper"
    curate_apply(db, ["1"], {"mark": "reject"})           # choosing one clears the other
    assert personal_get(db, ["1"])["1"]["mark"] == "reject"
    curate_apply(db, ["1"], {"mark": ""})
    assert "1" not in personal_get(db, ["1"]), "an empty personal row must not be stored"


def test_tags_notes_and_limits(db):
    r = curate_apply(db, ["1", "2"], {"add_tag": "Pose Study"})
    assert r["changed"] == 2
    assert personal_get(db, ["1"])["1"]["tags"] == ["pose-study"]
    assert curate_apply(db, ["1", "2"], {"add_tag": "pose-study"})["changed"] == 0   # already there
    assert curate_apply(db, ["1"], {"remove_tag": "pose-study"})["changed"] == 1
    with pytest.raises(CurationError):
        curate_apply(db, ["1"], {"add_tag": "x" * 33})
    assert curate_apply(db, ["1"], {"add_tag": "x" * 32})["changed"] == 1
    with pytest.raises(CurationError):
        curate_apply(db, ["1"], {"add_tag": "!!"})
    with pytest.raises(CurationError):
        curate_apply(db, ["1"], {"note": "n" * 501})
    assert curate_apply(db, ["1"], {"note": "n" * 500})["changed"] == 1


def test_a_picture_holds_at_most_32_tags(db):
    for i in range(32):
        curate_apply(db, ["3"], {"add_tag": "t{}".format(i)})
    r = curate_apply(db, ["3"], {"add_tag": "one-too-many"})
    assert r["changed"] == 0 and r["refused"] == 1
    assert len(personal_get(db, ["3"])["3"]["tags"]) == 32


def test_setting_a_rating_a_picture_already_has_is_a_no_op(db):
    """N4: the toast counts only real changes, so the server does."""
    r = curate_apply(db, ["1", "2", "3", "4"], {"rating": 4})
    assert r["changed"] == 3, "picture 1 already had 4 stars"
    assert sorted(r["prev"]) == ["2", "3", "4"]
    assert r["prev"]["3"]["rating"] == 5 and r["after"]["3"]["rating"] == 4
    assert curate_apply(db, ["1", "2", "3", "4"], {"rating": 4})["changed"] == 0
    curate_apply(db, ["1"], {"rating": 0})
    assert {x["media_id"]: x["rating"] for x in load_catalog(db)}["1"] == ""    # cleared, not "0"


def test_undo_restores_each_pictures_own_previous_values(db):
    """N4: not a blanket reset. Four pictures with four different starting states go back to
    four different states."""
    curate_apply(db, ["2"], {"mark": "reject"})
    curate_apply(db, ["3"], {"add_tag": "old"})
    ratings = {r["media_id"]: r["rating"] for r in load_catalog(db)}
    assert set(ratings.values()) == {"4", "", "5", "2"}      # four different starting ratings

    res = curate_apply(db, ["1", "2", "3", "4"], {"rating": 3})
    assert res["changed"] == 4
    curate_apply(db, ["1", "2", "3", "4"], {"mark": "keeper"})   # a LATER change, on the same pictures
    back = curate_restore(db, res["prev"])
    assert back["restored"] == 4
    assert {r["media_id"]: r["rating"] for r in load_catalog(db)} == ratings
    # a restore writes the whole previous state: 2 was a reject, 3 carried a tag, 1 and 4 nothing
    assert personal_get(db, ["1", "2", "3", "4"]) == {
        "2": {"tags": [], "mark": "reject", "note": ""},
        "3": {"tags": ["old"], "mark": "", "note": ""},
    }


def test_restore_validates_everything_before_writing_anything(db):
    with pytest.raises(CurationError):
        curate_restore(db, {"1": {"rating": 5, "mark": "keeper", "tags": [], "note": ""},
                            "2": {"rating": 9, "mark": "", "tags": [], "note": ""}})
    assert {r["media_id"]: r["rating"] for r in load_catalog(db)}["1"] == "4", \
        "an invalid entry must change nothing, valid neighbours included"
    assert personal_get(db, ["1"]) == {}


def test_unknown_ids_are_skipped_not_created(db):
    r = curate_apply(db, ["1", "nope"], {"mark": "keeper"})
    assert r["changed"] == 1 and r["skipped"] == 1
    assert "nope" not in personal_get(db, ["nope"])


def test_a_purge_leaves_the_personal_layer_waiting_for_a_restore(db):
    curate_apply(db, ["3"], {"mark": "keeper", "note": "hands"})
    g.delete_from_catalog(db, "3")                        # what a trash purge does to the row
    assert personal_get(db, ["3"])["3"]["note"] == "hands"


# --------------------------------------------------------------- the search operators

def test_the_personal_operators(db):
    curate_apply(db, ["1", "3"], {"mark": "keeper"})
    curate_apply(db, ["4"], {"mark": "reject"})
    curate_apply(db, ["1"], {"add_tag": "pose-study"})
    curate_apply(db, ["2"], {"note": "Good hands, reuse for the opener"})
    assert _ids(db, q="keeper") == ["1", "3"]
    assert _ids(db, q="reject") == ["4"]
    assert _ids(db, q="-reject") == ["1", "2", "3"], "rejects stay visible until -reject"
    assert _ids(db, q="keeper -tag:pose-study") == ["3"]
    assert _ids(db, q="tag:pose-study") == ["1"]
    assert _ids(db, q="tag:Pose*") == ["1"]
    assert _ids(db, q='tag:"pose study"') == ["1"]
    assert _ids(db, q='note:"good hands"') == ["2"]
    assert _ids(db, q="note:opener") == ["2"]
    assert _ids(db, q="-note:opener") == ["1", "3", "4"]
    assert _ids(db, q="keeper ★4+") == ["1", "3"]
    assert _ids(db, q="★5") == ["3"]
    assert _ids(db, q="★4") == ["1", "3"], "star-N without the plus reads as N and up"


def test_tag_still_finds_art_tags_and_art_tags_stays_pixai_only(db):
    curate_apply(db, ["2"], {"add_tag": "elf-adjacent"})
    assert _ids(db, q="tag:moon") == ["1"], "tag: keeps reading PixAI's published tags"
    assert _ids(db, q="art_tags:elf") == ["1"], "art_tags: is PixAI-only and never sees personal tags"
    assert _ids(db, q="tag:elf-adjacent") == ["2"]
    assert _ids(db, q="art_tags:elf-adjacent") == []


def test_negation_covers_free_text_and_operators_and_spares_bare_numbers(db):
    assert _ids(db, q="owl -blurry") == ["3"]
    assert _ids(db, q="-owl") == ["1", "2"]
    assert _ids(db, q="-rating:>=4") == ["2", "4"]
    assert _ids(db, q='-"night elf"') == ["2", "3", "4"]
    assert _ids(db, q="-collection:Faves") == ["2", "4"]
    # a leading hyphen on a bare number is what it always was: literal text, not a negation
    where, params = g._build_where("-5", "", "", "")
    assert "NOT" not in where and params == ["%-5%", "%-5%"]
    where, _ = g._build_where("-", "", "", "")
    assert "NOT" not in where


def test_a_quoted_keeper_is_a_phrase_not_the_operator(db):
    curate_apply(db, ["1"], {"mark": "keeper"})
    where, params = g._build_where('"keeper"', "", "", "")
    assert "personal_meta" not in where and params == ["%keeper%", "%keeper%"]


def test_operator_values_are_bound_never_interpolated(db):
    q = "tag:\"x'); DROP TABLE personal_meta;--\" note:\"'; DELETE FROM catalog;--\""
    assert query_catalog(db, q=q)[1] == 0
    assert "personal_meta" in _tables(db) and len(load_catalog(db)) == 4


# ------------------------------------------------------------------ smart collections

def test_a_smart_collection_stores_the_query_and_never_the_membership(db):
    saved = save_smart_collection(db, "★4+ keeper")
    assert saved == {"name": "4+ keeper", "query": "★4+ keeper", "created": True}
    assert _ids(db, collection="4+ keeper") == [], "nothing is a keeper yet"
    curate_apply(db, ["1"], {"mark": "keeper"})               # it moves in live
    curate_apply(db, ["2"], {"mark": "keeper", "rating": 5})
    assert _ids(db, collection="4+ keeper") == ["1", "2"]
    curate_apply(db, ["1"], {"rating": 1})                    # and out again
    assert _ids(db, collection="4+ keeper") == ["2"]
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM catalog WHERE collections LIKE '%4+ keeper%'").fetchone()[0] == 0
    assert con.execute("SELECT query FROM smart_collections").fetchall() == [("★4+ keeper",)]


def test_opening_a_smart_collection_ands_the_search_field_onto_its_query(db):
    curate_apply(db, ["1", "3"], {"mark": "keeper"})
    save_smart_collection(db, "keeper", name="Keepers")
    assert _ids(db, collection="Keepers") == ["1", "3"]
    assert _ids(db, collection="Keepers", q="owl") == ["3"]
    assert list_media_ids(db, collection="Keepers") == [r["media_id"] for r in
                                                        query_catalog(db, collection="Keepers", page_size=None)[0]]
    assert sorted(r["media_id"] for r in list_group_rows(db, collection="Keepers")) == ["1", "3"]


def test_smart_collection_names_are_unique_across_both_kinds(db):
    save_smart_collection(db, "keeper", name="Keepers")
    with pytest.raises(CurationError):
        save_smart_collection(db, "reject", name="keepers")   # case-insensitive
    with pytest.raises(CurationError):
        save_smart_collection(db, "reject", name="Druid")     # a hand-picked name
    a = save_smart_collection(db, "owl")
    b = save_smart_collection(db, "owl")                      # unnamed: the next free name
    assert (a["name"], b["name"]) == ("owl", "owl 2")
    with pytest.raises(CurationError):
        save_smart_collection(db, "   ")


def test_save_over_replaces_only_the_query(db):
    save_smart_collection(db, "keeper", name="Keepers")
    r = save_smart_collection(db, "reject", replace="Keepers")
    assert r["created"] is False and r["name"] == "Keepers"
    assert [s["query"] for s in g.list_smart_collections(db)] == ["reject"]
    with pytest.raises(CurationError):
        save_smart_collection(db, "x", replace="No such")


def test_pictures_cannot_be_added_to_a_smart_collection(db):
    save_smart_collection(db, "keeper", name="Keepers")
    with pytest.raises(CurationError):
        g.add_to_collection(db, ["1"], "Keepers")
    with pytest.raises(CurationError):
        g.add_to_collection(db, ["1"], "keepers")
    assert g.unique_collections(db) == ["Druid", "Faves"]


def test_the_summaries_list_both_kinds_with_counts_and_covers(db):
    curate_apply(db, ["3"], {"mark": "keeper"})
    save_smart_collection(db, "keeper", name="Keepers")
    s = {c["name"]: c for c in g.collection_summaries(db)}
    assert [c["name"] for c in g.collection_summaries(db)] == ["Druid", "Faves", "Keepers"]
    assert (s["Druid"]["kind"], s["Druid"]["count"], s["Druid"]["cover"]) == ("hand", 2, "1")
    assert (s["Faves"]["count"], s["Faves"]["cover"]) == (2, "1")
    assert s["Keepers"] == {"name": "Keepers", "kind": "smart", "count": 1, "query": "keeper", "cover": "3"}


# ------------------------------------------------------------ the collections manager

def test_rename_is_trimmed_unique_and_keeps_every_member(db):
    r = rename_collection(db, "Druid", "  Druids of   Azeroth ")
    assert r["name"] == "Druids of Azeroth" and r["changed"] == 2
    assert _ids(db, collection="Druids of Azeroth") == ["1", "2"]
    assert _ids(db, collection="Druid") == []
    with pytest.raises(CurationError):
        rename_collection(db, "Faves", "druids of azeroth")     # taken, case-insensitively
    with pytest.raises(CurationError):
        rename_collection(db, "Faves", "   ")
    with pytest.raises(CurationError):
        rename_collection(db, "Nope", "Whatever")
    assert rename_collection(db, "Faves", "faves")["name"] == "faves"   # its own case is its own
    assert rename_collection(db, "faves", "faves")["changed"] == 0


def test_rename_scrubs_commas_which_are_the_stores_separator(db):
    assert rename_collection(db, "Faves", "a,b")["name"] == "a b"
    assert _ids(db, collection="a b") == ["1", "3"]


def test_rename_a_smart_collection(db):
    save_smart_collection(db, "keeper", name="Keepers")
    assert rename_collection(db, "Keepers", "Best")["kind"] == "smart"
    assert [s["name"] for s in g.list_smart_collections(db)] == ["Best"]
    with pytest.raises(CurationError):
        rename_collection(db, "Best", "Druid")


def test_merge_dedupes_into_the_first_and_removes_the_others(db):
    before = len(load_catalog(db))
    r = merge_collections(db, ["Faves", "Druid"])
    assert r["target"] == "Faves" and r["merged"] == ["Druid"] and r["pictures"] == 3
    assert _ids(db, collection="Faves") == ["1", "2", "3"]
    assert g.unique_collections(db) == ["Faves"], "the others are gone"
    row1 = next(x for x in load_catalog(db) if x["media_id"] == "1")
    assert row1["collections"] == "Faves", "picture 1 was in both and holds the label once"
    assert len(load_catalog(db)) == before


def test_merge_needs_two_and_refuses_smart_and_unknown(db):
    save_smart_collection(db, "keeper", name="Keepers")
    with pytest.raises(CurationError):
        merge_collections(db, ["Druid"])
    with pytest.raises(CurationError):
        merge_collections(db, ["Druid", "Druid"])
    with pytest.raises(CurationError) as e:
        merge_collections(db, ["Druid", "Keepers"])
    assert "smart" in str(e.value)
    with pytest.raises(CurationError):
        merge_collections(db, ["Druid", "Nope"])
    assert g.unique_collections(db) == ["Druid", "Faves"], "a refused merge changes nothing"


def test_delete_never_deletes_pictures(db):
    before = [dict(r) for r in load_catalog(db)]
    r = delete_collection(db, "Druid")
    assert r == {"name": "Druid", "kind": "hand", "kept": 2}
    after = load_catalog(db)
    assert len(after) == len(before)
    assert [x["media_id"] for x in after] == [x["media_id"] for x in before]
    assert g.unique_collections(db) == ["Faves"]
    row1 = next(x for x in after if x["media_id"] == "1")
    assert row1["collections"] == "Faves"

    curate_apply(db, ["1"], {"mark": "keeper"})
    save_smart_collection(db, "keeper", name="Keepers")
    assert delete_collection(db, "Keepers") == {"name": "Keepers", "kind": "smart", "kept": 1}
    assert len(load_catalog(db)) == len(before)
    assert personal_get(db, ["1"])["1"]["mark"] == "keeper", "the saved search went, the mark stayed"
    with pytest.raises(CurationError):
        delete_collection(db, "Keepers")


# ---------------------------------------------------------------------------- routes

@pytest.fixture
def client(tmp_path, db):
    cli = login_client(tmp_path)
    cli.csrf = extract_login_csrf(cli.get("/").get_data(as_text=True))
    assert cli.csrf
    return cli


def _post(cli, path, **body):
    return cli.post(path, json=dict(body, csrf=cli.csrf))


@pytest.mark.parametrize("path,body", [
    ("/api/curate", {"media_ids": ["1"], "op": {"rating": 3}}),
    ("/api/curate/restore", {"prev": {"1": {"rating": 3, "mark": "", "tags": [], "note": ""}}}),
    ("/api/collections/manage", {"action": "rename", "name": "Druid", "new_name": "X"}),
    ("/api/collections/manage", {"action": "merge", "names": ["Druid", "Faves"]}),
    ("/api/collections/manage", {"action": "delete", "name": "Druid"}),
    ("/api/collections/manage", {"action": "smart", "query": "keeper"}),
])
def test_every_curation_post_checks_csrf(client, db, path, body):
    before = _dump(db)
    assert client.post(path, json=body).status_code == 400                       # no token
    assert client.post(path, json=dict(body, csrf="not-the-token")).status_code == 400
    assert _dump(db) == before, "a refused request must not have written"


def test_curate_route_round_trip_with_undo(client, db):
    r = _post(client, "/api/curate", media_ids=["1", "2", "3"], op={"rating": 4}).get_json()
    assert r["ok"] and r["changed"] == 2 and sorted(r["prev"]) == ["2", "3"]
    undo = _post(client, "/api/curate/restore", prev=r["prev"]).get_json()
    assert undo["ok"] and undo["restored"] == 2
    assert {x["media_id"]: x["rating"] for x in load_catalog(db)} == {"1": "4", "2": "", "3": "5", "4": "2"}


def test_curate_route_answers_a_refusal_in_words(client):
    r = _post(client, "/api/curate", media_ids=["1"], op={"add_tag": "x" * 40})
    assert r.status_code == 400 and "32" in r.get_json()["error"]
    assert _post(client, "/api/curate", media_ids=[], op={"rating": 1}).status_code == 400
    assert _post(client, "/api/curate", media_ids=["1"], op={"rating": 9}).status_code == 400
    assert _post(client, "/api/curate", media_ids=["1"], op={"mark": "maybe"}).status_code == 400
    assert _post(client, "/api/curate", media_ids=["1"], op={}).status_code == 400
    assert _post(client, "/api/curate", media_ids="1", op={"rating": 1}).status_code == 400


def test_manage_route_actions(client, db):
    smart = _post(client, "/api/collections/manage", action="smart", query="keeper").get_json()
    assert smart["ok"] and smart["name"] == "keeper" and smart["created"] is True
    assert _post(client, "/api/collections/manage", action="rename", name="Druid",
                 new_name="Druids").get_json()["name"] == "Druids"
    assert _post(client, "/api/collections/manage", action="merge",
                 names=["Druids", "Faves"]).get_json()["pictures"] == 3
    dele = _post(client, "/api/collections/manage", action="delete", name="Druids").get_json()
    assert dele["kept"] == 3 and len(load_catalog(db)) == 4
    bad = _post(client, "/api/collections/manage", action="explode")
    assert bad.status_code == 400
    taken = _post(client, "/api/collections/manage", action="rename", name="keeper", new_name="keeper")
    assert taken.status_code == 200          # its own name: nothing to do
    dup = _post(client, "/api/collections/manage", action="smart", query="reject", name="KEEPER")
    assert dup.status_code == 400


def test_collections_detail_route(client):
    d = client.get("/api/collections/detail").get_json()
    assert [c["name"] for c in d["collections"]] == ["Druid", "Faves"]


def test_the_old_collection_route_refuses_a_smart_name(client):
    _post(client, "/api/collections/manage", action="smart", query="keeper", name="Keepers")
    r = client.post("/api/collection", json={"action": "add", "collection": "Keepers", "media_ids": ["1"]})
    assert r.status_code == 400 and "smart collection" in r.get_json()["error"]
    r = client.post("/api/collection", json={"action": "remove", "collection": "Keepers", "media_ids": ["1"]})
    assert r.status_code == 400


def test_cards_carry_the_mark_and_tags_and_details_carries_the_layer(client, db):
    _post(client, "/api/curate", media_ids=["1"], op={"mark": "keeper"})
    _post(client, "/api/curate", media_ids=["1"], op={"add_tag": "pose-study"})
    _post(client, "/api/curate", media_ids=["1"], op={"note": "hands"})
    items = {i["media_id"]: i for i in client.get("/api/library").get_json()["items"]}
    assert items["1"]["mark"] == "keeper" and items["1"]["tags"] == ["pose-study"]
    assert items["2"]["mark"] == "" and items["2"]["tags"] == []
    detail = client.get("/api/detail/1").get_json()
    assert detail["personal"] == {"tags": ["pose-study"], "mark": "keeper", "note": "hands"}
    assert client.get("/api/detail/2").get_json()["personal"] == {"tags": [], "mark": "", "note": ""}


def test_the_library_lists_a_smart_collection_live(client):
    _post(client, "/api/collections/manage", action="smart", query="keeper", name="Keepers")
    lib = lambda: client.get("/api/library?collection=Keepers").get_json()   # noqa: E731
    assert lib()["total"] == 0
    _post(client, "/api/curate", media_ids=["3"], op={"mark": "keeper"})
    d = lib()
    assert d["total"] == 1 and d["items"][0]["media_id"] == "3"


def test_the_boot_lists_smart_collections(client):
    _post(client, "/api/collections/manage", action="smart", query="keeper", name="Keepers")
    html = client.get("/").get_data(as_text=True)
    assert '"smart_collections"' in html and "Keepers" in html


def test_a_curated_picture_survives_a_repull_of_its_catalog_row(db):
    """The layer is not a catalog column: re-saving the row (what --update and every re-pull do
    through the upsert) cannot blank it."""
    curate_apply(db, ["1"], {"mark": "keeper", "add_tag": "kept"})
    row = next(r for r in load_catalog(db) if r["media_id"] == "1")
    row["prompt_full"] = "re-pulled"
    save_catalog(db, [row])
    assert personal_get(db, ["1"])["1"] == {"tags": ["kept"], "mark": "keeper", "note": ""}


# ------------------------------------------- a saved view's operators read what its chips read

def test_the_operators_a_smart_collection_saves_match_the_controls_they_stand_for(tmp_path):
    """gallery/src/curation/curationCore.js composeSmartQuery writes each chip and flyout filter
    as a search operator. Each one has to select exactly the rows the control does, or a smart
    collection would open on different pictures than the view it was saved from."""
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="1", filename="a.png", model_name="Tsubaki.3", source="api", rating="5",
             created_at="2026-01-15T00:00:00Z", is_published="1", art_tags="elf, moon", loras="Moon Light:0.7"),
        _row(media_id="2", filename="b.png", model_name="Lucent Mix", source="local", rating="2",
             created_at="2026-05-02T00:00:00Z", art_tags="owl"),
        _row(media_id="3", filename="c.mp4", model_name="Tsubaki.3", source="online", rating="",
             created_at="2026-08-20T00:00:00Z", is_video="1"),
        _row(media_id="4", filename="d.png", model_name="Lucent Mix", source="deleted", rating="4",
             created_at="2025-12-31T00:00:00Z", deleted_remote="1"),
    ])
    same = [
        (dict(q="video:0"), dict(media_type="image")),
        (dict(q="video:1"), dict(media_type="video")),
        (dict(q="★4+"), dict(rating_min=4)),
        (dict(q="source:api"), dict(source="api")),
        (dict(q="source:local"), dict(source="local")),
        (dict(q="source:deleted"), dict(source="deleted")),
        (dict(q="art_tags:elf"), dict(art_tag="elf")),
        (dict(q="published:1"), dict(published_only=True)),
        (dict(q="created:>=2026-05"), dict(date_from="2026-05")),
        (dict(q="created:<=2026-05"), dict(date_to="2026-05")),
        (dict(q="created:>=2026-01 created:<=2026-05"), dict(date_from="2026-01", date_to="2026-05")),
        (dict(q='collection:"A B"'), dict(collection="A B")),
        (dict(q="lora:moon"), dict(lora="moon")),
    ]
    for op, chip in same:
        assert _ids(p, **op) == _ids(p, **chip), (op, chip)
    # model: and lora: are substring searches where their chips match the whole name
    assert set(_ids(p, model="Tsubaki.3")) <= set(_ids(p, q="model:Tsubaki.3"))


# ------------------------------------ the other doors into a collection refuse a smart one

def test_an_import_into_a_smart_collection_is_refused_before_any_file_lands(client, tmp_path, db):
    """The importer names a collection to tag what it brings in. A smart collection is a saved
    search, so the request is refused BEFORE anything is copied or catalogued."""
    import io
    pytest.importorskip("PIL")
    from PIL import Image
    _post(client, "/api/collections/manage", action="smart", query="keeper", name="Keepers")
    png = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 40, 60)).save(png, "PNG")
    png.seek(0)
    before = len(load_catalog(db))
    r = client.post("/api/import-local", data={"files": (png, "x.png"), "collection": "keepers"},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and "smart collection" in r.get_json()["error"]
    assert not (tmp_path / "imported").exists(), "a file was copied in before the refusal"
    assert len(load_catalog(db)) == before


def test_the_mcp_add_tool_refuses_a_smart_collection(db, monkeypatch):
    pytest.importorskip("fastmcp")
    from moonglade import mcp_server as m
    monkeypatch.setattr(m, "DB", str(db))
    save_smart_collection(db, "keeper", name="Keepers")
    out = m.add_to_collection(["1"], "Keepers")
    assert out["ok"] is False and "smart collection" in out["error"]
    assert m.add_to_collection(["1"], "Faves")["ok"] is True

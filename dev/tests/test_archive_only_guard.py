"""Archive-only pictures (#66): a row PixAI no longer has -- `deleted_remote='1'` (its task left
your feed as of the last --reconcile-deleted) or a `cloud_deleted_at` stamp (PixAI dropped this
one image) -- holds the only copy of that picture anywhere.

The owner's ruling (walk, 2026-10-03): warn, don't block. Keeping them back was tedious.

  * the bulk "Delete locally" removes them with the rest; its confirm first asks the route how
    many of the selection are the only copy (`preview`) and names them;
  * the Trash's Restore brings back the picture AND its catalog row, ARCHIVE flags included,
    which is what lets the confirm say so;
  * Duplicate Review removes them with the rest too, and its Undo puts the row back;
  * the grid card, the duplicate members and the detail read carry `archive_only` so the gallery
    can badge them and the confirms can count them.
"""
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, load_catalog, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows, files):
    save_catalog(tmp_path / "catalog.db", rows)
    img = tmp_path / "images"
    img.mkdir(exist_ok=True)
    for name, data in files.items():
        (img / name).write_bytes(data)
    return tmp_path / "catalog.db"


def _csrf(cli):
    d = cli.get("/api/panel/summary").get_json()
    assert d and d.get("csrf")
    return d["csrf"]


def _three(tmp_path):
    """One ordinary picture and one of each kind of archive-only picture."""
    return _seed(tmp_path, [
        _row(media_id="100", filename="p_100.png"),
        _row(media_id="200", filename="p_200.png", deleted_remote="1"),
        _row(media_id="300", filename="p_300.png", cloud_deleted_at="2026-09-20T10:00:00Z"),
    ], {"p_100.png": b"A", "p_200.png": b"B", "p_300.png": b"C"})


def test_the_rule(tmp_path):
    assert g.is_archive_only({"deleted_remote": "1"}) is True
    assert g.is_archive_only({"cloud_deleted_at": "2026-09-20T10:00:00Z"}) is True
    assert g.is_archive_only({"deleted_remote": "", "cloud_deleted_at": "  "}) is False
    assert g.is_archive_only({"deleted_remote": "0"}) is False
    assert g.is_archive_only({}) is False
    assert g.is_archive_only(None) is False


# ---------------------------------------------------------------------------
# /api/delete-local
# ---------------------------------------------------------------------------

def test_bulk_delete_locally_removes_archive_only_pictures_with_the_rest(tmp_path):
    db = _three(tmp_path)
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["100", "200", "300"]}).get_json()
    assert d == {"ok": True, "count": 3, "failed": 0}
    for name in ("p_100.png", "p_200.png", "p_300.png"):
        assert (tmp_path / g.DELETED_DIRNAME / name).exists(), name
        assert not (tmp_path / "images" / name).exists(), name
    assert load_catalog(db) == []


def test_the_preview_counts_the_only_copies_and_touches_nothing(tmp_path):
    """The bulk confirm asks first: how many of the selection are the only copy. Unknown and
    repeated ids are not counted, the same way the delete itself skips them."""
    db = _three(tmp_path)
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["100", "200", "300", "200", "ghost"],
                                            "preview": True}).get_json()
    assert d == {"preview": True, "count": 3, "archive_only": 2}
    assert {r["media_id"] for r in load_catalog(db)} == {"100", "200", "300"}
    assert not (tmp_path / g.DELETED_DIRNAME).exists()
    assert cli.post("/api/delete-local", json={"media_ids": ["100"], "preview": True}
                    ).get_json() == {"preview": True, "count": 1, "archive_only": 0}


def test_the_trash_restores_an_only_copy_with_its_row(tmp_path):
    """What lets the confirm say the Trash can restore them: Restore puts the file back AND
    reinserts the whole catalog row from the snapshot taken at delete time -- the ARCHIVE flags,
    the rating and the collections included -- so the picture comes back badged as it left."""
    db = _seed(tmp_path, [
        _row(media_id="200", filename="p_200.png", deleted_remote="1", rating="4",
             collections="keepers", prompt_full="a lantern"),
        _row(media_id="300", filename="p_300.png", cloud_deleted_at="2026-09-20T10:00:00Z"),
    ], {"p_200.png": b"B", "p_300.png": b"C"})
    cli = login_client(tmp_path)
    assert cli.post("/api/delete-local", json={"media_ids": ["200", "300"]}).get_json()["count"] == 2
    assert load_catalog(db) == []

    r = cli.post("/api/trash/restore", json={"media_ids": ["200", "300"]}).get_json()
    assert sorted(r["restored"]) == ["200", "300"] and not r["errors"]
    rows = {row["media_id"]: row for row in load_catalog(db)}
    assert rows["200"]["deleted_remote"] == "1" and rows["200"]["rating"] == "4"
    assert rows["200"]["collections"] == "keepers" and rows["200"]["prompt_full"] == "a lantern"
    assert rows["300"]["cloud_deleted_at"] == "2026-09-20T10:00:00Z"
    assert (tmp_path / "images" / "p_200.png").read_bytes() == b"B"
    assert (tmp_path / "images" / "p_300.png").read_bytes() == b"C"
    assert cli.get("/api/detail/200").get_json()["archive_only"] is True


# ---------------------------------------------------------------------------
# Payloads: the card, the detail read, the duplicate members
# ---------------------------------------------------------------------------

def test_the_grid_card_carries_archive_only(tmp_path):
    _three(tmp_path)
    items = login_client(tmp_path).get("/api/library").get_json()["items"]
    flags = {it["media_id"]: it["archive_only"] for it in items}
    assert flags == {"100": False, "200": True, "300": True}


def test_the_grouped_grid_card_carries_archive_only(tmp_path):
    _three(tmp_path)
    items = login_client(tmp_path).get("/api/library?group=series").get_json()["items"]
    flags = {it["media_id"]: it["archive_only"] for it in items}
    assert flags == {"100": False, "200": True, "300": True}


def test_the_detail_read_carries_archive_only(tmp_path):
    _three(tmp_path)
    cli = login_client(tmp_path)
    assert cli.get("/api/detail/100").get_json()["archive_only"] is False
    assert cli.get("/api/detail/200").get_json()["archive_only"] is True
    assert cli.get("/api/detail/300").get_json()["archive_only"] is True


def _same_seed(tmp_path, newer_flags):
    """Two different pictures from one seed and prompt; the newer one (the default loser)
    carries `newer_flags`."""
    return _seed(tmp_path, [
        _row(media_id="444", filename="a_444.webp", seed="12345", prompt_full="a cat",
             created_at="2024-01-01"),
        _row(media_id="555", filename="b_555.webp", seed="12345", prompt_full="a cat",
             created_at="2024-01-02", **newer_flags),
    ], {"a_444.webp": b"XX", "b_555.webp": b"YYY"})


def test_duplicate_members_carry_archive_only(tmp_path):
    _same_seed(tmp_path, {"deleted_remote": "1"})
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    group = next(x for x in d["groups"] if x["matchType"] == "same_seed")
    flags = {m["media_id"]: m["archive_only"] for m in group["members"]}
    assert flags == {"444": False, "555": True}


# ---------------------------------------------------------------------------
# /api/duplicates/resolve
# ---------------------------------------------------------------------------

def _resolve(cli, group_id, keep, remove):
    return cli.post("/api/duplicates/resolve", json={
        "csrf": _csrf(cli), "group_id": group_id, "keep": keep, "remove": remove}).get_json()


def test_resolve_removes_an_archive_only_same_seed_loser_and_undo_brings_it_back(tmp_path):
    db = _same_seed(tmp_path, {"cloud_deleted_at": "2026-09-20T10:00:00Z", "rating": "3"})
    cli = login_client(tmp_path)
    d = _resolve(cli, "same_seed:12345:x",
                 {"media_id": "444", "path": "images/a_444.webp"},
                 [{"media_id": "555", "path": "images/b_555.webp"}])
    assert [q["media_id"] for q in d["quarantined"]] == ["555"]
    assert d["errors"] == [] and "kept_archive_only" not in d
    assert not (tmp_path / "images" / "b_555.webp").exists()
    assert "555" not in {r["media_id"] for r in load_catalog(db)}

    u = cli.post("/api/duplicates/undo", json={
        "csrf": _csrf(cli), "quarantine_path": d["quarantined"][0]["quarantine_path"]}).get_json()
    assert u.get("ok") is True, u
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["555"]["cloud_deleted_at"] == "2026-09-20T10:00:00Z" and rows["555"]["rating"] == "3"
    assert (tmp_path / "images" / "b_555.webp").read_bytes() == b"YYY"


def test_resolve_removes_an_archive_only_near_duplicate_loser(tmp_path):
    _seed(tmp_path, [
        _row(media_id="888", filename="a_888.webp", phash="0000000000000000",
             created_at="2024-01-01"),
        _row(media_id="999", filename="b_999.webp", phash="0000000000000007",
             created_at="2024-01-02", deleted_remote="1"),
    ], {"a_888.webp": b"AAAAAAAAAA", "b_999.webp": b"BB"})
    cli = login_client(tmp_path)
    d = _resolve(cli, "near_duplicate:888-999",
                 {"media_id": "888", "path": "images/a_888.webp"},
                 [{"media_id": "999", "path": "images/b_999.webp"}])
    assert [q["media_id"] for q in d["quarantined"]] == ["999"] and d["errors"] == []
    assert not (tmp_path / "images" / "b_999.webp").exists()


def test_resolve_removes_every_member_but_the_keeper(tmp_path):
    _seed(tmp_path, [
        _row(media_id="1", filename="a_1.webp", seed="7", prompt_full="p", created_at="2024-01-01"),
        _row(media_id="2", filename="b_2.webp", seed="7", prompt_full="p", created_at="2024-01-02",
             deleted_remote="1"),
        _row(media_id="3", filename="c_3.webp", seed="7", prompt_full="p", created_at="2024-01-03"),
    ], {"a_1.webp": b"1", "b_2.webp": b"22", "c_3.webp": b"333"})
    cli = login_client(tmp_path)
    d = _resolve(cli, "same_seed:7:x",
                 {"media_id": "1", "path": "images/a_1.webp"},
                 [{"media_id": "2", "path": "images/b_2.webp"},
                  {"media_id": "3", "path": "images/c_3.webp"}])
    assert sorted(q["media_id"] for q in d["quarantined"]) == ["2", "3"]
    assert (tmp_path / "images" / "a_1.webp").exists()
    assert not (tmp_path / "images" / "b_2.webp").exists()
    assert not (tmp_path / "images" / "c_3.webp").exists()


def test_resolve_leaves_the_byte_identical_tiers_alone(tmp_path):
    """Same generation saved twice: the keeper copy has the same bytes and the same media id,
    so quarantining the extra copy loses nothing -- archive-only or not."""
    (tmp_path / "2024-03").mkdir()
    db = _seed(tmp_path, [_row(media_id="111", filename="p_t1_111.webp", deleted_remote="1")],
               {"p_t1_111.webp": b"DUPE"})
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"DUPE")
    cli = login_client(tmp_path)
    d = _resolve(cli, "same_media:111",
                 {"media_id": "111", "path": "2024-03/111.webp"},
                 [{"media_id": "111", "path": "images/p_t1_111.webp"}])
    assert d["errors"] == [] and len(d["quarantined"]) == 1
    assert (tmp_path / "2024-03" / "111.webp").exists()
    assert [r["media_id"] for r in load_catalog(db)] == ["111"]

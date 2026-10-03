"""Archive-only pictures (#66): a row PixAI no longer has -- `deleted_remote='1'` (its task left
your feed as of the last --reconcile-deleted) or a `cloud_deleted_at` stamp (PixAI dropped this
one image) -- holds the only copy of that picture anywhere.

  * the bulk "Delete locally" keeps them back and says how many it kept;
  * only the single-image path can remove one, and only when it says so (`include_archive_only`);
  * Duplicate Review never removes one in the same-seed or near-duplicate tiers, where the members
    are different pictures with their own pixels; the byte-identical tiers are unaffected;
  * the grid card, the duplicate members and the detail read carry `archive_only` so the gallery
    can badge them.
"""
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, load_catalog, save_catalog

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

def test_bulk_delete_locally_keeps_archive_only_pictures_and_says_how_many(tmp_path):
    db = _three(tmp_path)
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["100", "200", "300"]}).get_json()
    assert d == {"ok": True, "count": 1, "failed": 0, "kept_archive_only": 2}
    assert (tmp_path / g.DELETED_DIRNAME / "p_100.png").exists()
    assert (tmp_path / "images" / "p_200.png").read_bytes() == b"B"
    assert (tmp_path / "images" / "p_300.png").read_bytes() == b"C"
    assert {r["media_id"] for r in load_catalog(db)} == {"200", "300"}


def test_the_bulk_path_has_no_override(tmp_path):
    """`include_archive_only` is honoured for ONE picture only -- the image's own page, after
    its own confirm. Sent with a selection, it changes nothing."""
    db = _three(tmp_path)
    cli = login_client(tmp_path)
    d = cli.post("/api/delete-local", json={"media_ids": ["100", "200"],
                                            "include_archive_only": True}).get_json()
    assert d["count"] == 1 and d["kept_archive_only"] == 1
    assert (tmp_path / "images" / "p_200.png").exists()
    assert "200" in {r["media_id"] for r in load_catalog(db)}


def test_the_single_image_path_removes_one_when_it_says_so(tmp_path):
    db = _three(tmp_path)
    cli = login_client(tmp_path)
    kept = cli.post("/api/delete-local", json={"media_ids": ["200"]}).get_json()
    assert kept == {"ok": True, "count": 0, "failed": 0, "kept_archive_only": 1}
    assert (tmp_path / "images" / "p_200.png").exists()

    d = cli.post("/api/delete-local", json={"media_ids": ["200"],
                                            "include_archive_only": True}).get_json()
    assert d == {"ok": True, "count": 1, "failed": 0, "kept_archive_only": 0}
    assert (tmp_path / g.DELETED_DIRNAME / "p_200.png").exists()   # recoverable from Trash
    assert "200" not in {r["media_id"] for r in load_catalog(db)}


# ---------------------------------------------------------------------------
# Payloads: the card, the detail read, the duplicate members
# ---------------------------------------------------------------------------

def test_the_grid_card_carries_archive_only(tmp_path):
    _three(tmp_path)
    items = login_client(tmp_path).get("/api/next/library").get_json()["items"]
    flags = {it["media_id"]: it["archive_only"] for it in items}
    assert flags == {"100": False, "200": True, "300": True}


def test_the_grouped_grid_card_carries_archive_only(tmp_path):
    _three(tmp_path)
    items = login_client(tmp_path).get("/api/next/library?group=series").get_json()["items"]
    flags = {it["media_id"]: it["archive_only"] for it in items}
    assert flags == {"100": False, "200": True, "300": True}


def test_the_detail_read_carries_archive_only(tmp_path):
    _three(tmp_path)
    cli = login_client(tmp_path)
    assert cli.get("/api/next/detail/100").get_json()["archive_only"] is False
    assert cli.get("/api/next/detail/200").get_json()["archive_only"] is True
    assert cli.get("/api/next/detail/300").get_json()["archive_only"] is True


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


def test_resolve_refuses_an_archive_only_same_seed_loser(tmp_path):
    db = _same_seed(tmp_path, {"cloud_deleted_at": "2026-09-20T10:00:00Z"})
    cli = login_client(tmp_path)
    d = _resolve(cli, "same_seed:12345:x",
                 {"media_id": "444", "path": "images/a_444.webp"},
                 [{"media_id": "555", "path": "images/b_555.webp"}])
    assert d["quarantined"] == []
    assert d["kept_archive_only"] == 1
    assert len(d["errors"]) == 1
    err = d["errors"][0]
    assert err["media_id"] == "555"
    assert "only copy" in err["error"] and "PixAI" in err["error"]
    assert (tmp_path / "images" / "b_555.webp").read_bytes() == b"YYY"
    assert "555" in {r["media_id"] for r in load_catalog(db)}


def test_resolve_refuses_an_archive_only_near_duplicate_loser(tmp_path):
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
    assert d["quarantined"] == [] and d["kept_archive_only"] == 1
    assert (tmp_path / "images" / "b_999.webp").exists()


def test_resolve_still_removes_the_ordinary_members_beside_an_archive_only_one(tmp_path):
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
    assert [q["media_id"] for q in d["quarantined"]] == ["3"]
    assert d["kept_archive_only"] == 1
    assert (tmp_path / "images" / "b_2.webp").exists()
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
    assert d["kept_archive_only"] == 0
    assert (tmp_path / "2024-03" / "111.webp").exists()
    assert [r["media_id"] for r in load_catalog(db)] == ["111"]

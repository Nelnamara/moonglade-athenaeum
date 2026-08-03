"""GET /api/duplicates -- the React Duplicate Review overlay's real, working
duplicate-groups listing (scoped 2026-08-02, docs/DECISIONS.md). Covers the three
exact-match tiers (same_media / identical_file / same_seed), the perceptual-hash
near_duplicate tier (Class D -- see tests/test_phash.py for near_duplicate_groups()
and compute_dhash() in isolation), and the same_seed_groups() SQL helper in
isolation. Route-tier declaration itself (LOGIN, anonymous refusal) is covered
structurally by tests/test_route_tiers.py -- this file proves the handler's actual
output shape and detection logic."""
from moonglade_gallery import CATALOG_FIELDS, save_catalog, same_seed_groups

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---------------------------------------------------------------------------
# same_seed_groups() -- pure SQL helper, no filesystem/Flask involved
# ---------------------------------------------------------------------------

def test_same_seed_groups_finds_shared_seed_and_prompt(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", seed="99", prompt_full="a cat"),
        _row(media_id="2", seed="99", prompt_full="a cat"),
        _row(media_id="3", seed="99", prompt_full="a different prompt"),
    ])
    groups = same_seed_groups(db)
    assert len(groups) == 1
    assert set(groups[0]["media_ids"]) == {"1", "2"}
    assert groups[0]["seed"] == "99"


def test_same_seed_groups_ignores_blank_seed_or_prompt(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", seed="", prompt_full=""),
        _row(media_id="2", seed="", prompt_full=""),
        _row(media_id="3", seed="5", prompt_full=""),
        _row(media_id="4", seed="", prompt_full="x"),
    ])
    assert same_seed_groups(db) == []


# ---------------------------------------------------------------------------
# GET /api/duplicates -- full route, all three tiers
# ---------------------------------------------------------------------------

def test_same_media_tier(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "2024-03").mkdir()
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"AAAA")
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"AAAA")
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="111", width="800", height="600", rating="4", created_at="2024-03-01"),
    ])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    sm = [g for g in d["groups"] if g["matchType"] == "same_media"]
    assert len(sm) == 1
    g = sm[0]
    assert g["id"] == "same_media:111"
    assert len(g["members"]) == 2
    keepers = [m for m in g["members"] if m["is_keeper"]]
    assert len(keepers) == 1
    assert keepers[0]["bucket"] == "month"          # organized copy wins, matches duplicate_groups()
    assert keepers[0]["width"] == "800" and keepers[0]["rating"] == "4"
    assert g["reclaimable_bytes"] == 4               # the one redundant "images/" copy, 4 real bytes
    assert d["counts"]["same_media"] == 1


def test_identical_file_tier(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p_t1_222.webp").write_bytes(b"IDENTICAL-BYTES")
    (tmp_path / "images" / "p_t2_333.webp").write_bytes(b"IDENTICAL-BYTES")
    save_catalog(tmp_path / "catalog.db", [_row(media_id="222"), _row(media_id="333")])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    ib = [g for g in d["groups"] if g["matchType"] == "identical_file"]
    assert len(ib) == 1
    g = ib[0]
    assert len(g["members"]) == 2
    assert {m["media_id"] for m in g["members"]} == {"222", "333"}
    assert sum(1 for m in g["members"] if m["is_keeper"]) == 1
    assert g["reclaimable_bytes"] == len(b"IDENTICAL-BYTES")
    assert d["counts"]["identical_file"] == 1


def test_same_seed_tier(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_444.webp").write_bytes(b"XX")
    (tmp_path / "images" / "b_555.webp").write_bytes(b"YYY")
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="444", filename="a_444.webp", seed="12345", prompt_full="a cat",
             created_at="2024-01-01"),
        _row(media_id="555", filename="b_555.webp", seed="12345", prompt_full="a cat",
             created_at="2024-01-02"),
    ])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    ss = [g for g in d["groups"] if g["matchType"] == "same_seed"]
    assert len(ss) == 1
    g = ss[0]
    assert g["seed"] == "12345"
    assert len(g["members"]) == 2
    keeper = next(m for m in g["members"] if m["is_keeper"])
    assert keeper["media_id"] == "444"                # earlier created_at is the keeper
    assert g["reclaimable_bytes"] == 3                # the "555" loser, real 3-byte file
    assert d["counts"]["same_seed"] == 1


def test_near_duplicate_tier(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_888.webp").write_bytes(b"AAAAAAAAAA")   # 10 bytes, older -> keeper
    (tmp_path / "images" / "b_999.webp").write_bytes(b"BB")           # 2 bytes, newer -> loser
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="888", filename="a_888.webp", phash="0000000000000000",
             created_at="2024-01-01"),
        # Hamming distance 3 from "888"'s hash (only the low 3 bits differ) -- well under
        # the default threshold (10), so this is a real near-duplicate pair.
        _row(media_id="999", filename="b_999.webp", phash="0000000000000007",
             created_at="2024-01-02"),
    ])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    nd = [g for g in d["groups"] if g["matchType"] == "near_duplicate"]
    assert len(nd) == 1
    g = nd[0]
    assert {m["media_id"] for m in g["members"]} == {"888", "999"}
    keeper = next(m for m in g["members"] if m["is_keeper"])
    assert keeper["media_id"] == "888"                # earlier created_at is the keeper
    assert g["reclaimable_bytes"] == 2                 # the "999" loser, real 2-byte file
    assert g["closeness_pct"] == round(100 * (1 - 3 / 64), 1)
    assert d["counts"]["near_duplicate"] == 1


def test_near_duplicate_tier_skips_video_and_blank_phash_rows(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_111.webp").write_bytes(b"A")
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="111", filename="a_111.webp", phash="0000000000000000"),
        # Identical hash, but it's a video row -- this tier is image-only by scope.
        _row(media_id="222", filename="v_222.mp4", phash="0000000000000000", is_video="1"),
        # No phash computed yet -- absent from this tier, not a "no match" result.
        _row(media_id="333", filename="c_333.webp", phash=""),
    ])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    assert [g for g in d["groups"] if g["matchType"] == "near_duplicate"] == []
    assert d["counts"]["near_duplicate"] == 0


def test_no_duplicates_returns_empty_groups(tmp_path):
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    assert d["groups"] == []
    assert d["total_groups"] == 0
    assert d["total_reclaimable_bytes"] == 0
    assert d["counts"] == {"same_media": 0, "identical_file": 0, "same_seed": 0,
                           "near_duplicate": 0}


def test_members_shape_is_uniform_across_tiers(tmp_path):
    """Every member, regardless of matchType, exposes the same key set -- the
    client should never have to special-case by tier."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p_t1_666.webp").write_bytes(b"Z")
    (tmp_path / "images" / "p_t2_777.webp").write_bytes(b"Z")
    save_catalog(tmp_path / "catalog.db", [_row(media_id="666"), _row(media_id="777")])
    d = login_client(tmp_path).get("/api/duplicates").get_json()
    assert d["groups"], "expected at least the identical_file group"
    expected_keys = {"media_id", "thumb", "width", "height", "rating", "created_at",
                     "is_video", "path", "bucket", "size", "is_keeper"}
    for g in d["groups"]:
        assert "id" in g and "matchType" in g and "reclaimable_bytes" in g
        for m in g["members"]:
            assert set(m.keys()) == expected_keys

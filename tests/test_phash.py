"""Perceptual-hash near-duplicate detection (Class D, the follow-up named in
api_duplicates()'s original docstring / docs/DECISIONS.md): compute_dhash() (the
Pillow-only dHash), near_duplicate_groups() (the banded Hamming-distance clustering
SQL/pure-Python helper) and run_backfill_phash() (the `--backfill-phash` CLI), each
in isolation. The route-level near_duplicate tier itself (real files, real catalog
rows, is_keeper/reclaimable_bytes) is covered in tests/test_duplicates_api.py."""
from types import SimpleNamespace

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, compute_dhash, near_duplicate_groups, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _gradient(w=64, h=64, reverse=False):
    """A real, non-uniform test image -- NOT a solid color. dHash only encodes
    RELATIVE brightness between HORIZONTALLY adjacent pixels, so a solid-color image
    (or a purely vertical gradient, where every row is internally flat) collapses to
    hash 0 regardless of content; a horizontal gradient is the simplest image whose
    hash actually reflects its content, which is what these tests need to mean
    anything. `reverse` mirrors it left-right -- every "brighter to the right" bit
    flips to "brighter to the left", the maximally-different image dHash can express."""
    from PIL import Image
    im = Image.new("L", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            frac = (x / w) if not reverse else (1 - x / w)
            px[x, y] = int(255 * frac)
    return im.convert("RGB")


# ---------------------------------------------------------------------------
# compute_dhash() -- pure Pillow, no filesystem/DB involved beyond a temp image
# ---------------------------------------------------------------------------

def test_compute_dhash_identical_images_match_exactly(tmp_path):
    p = tmp_path / "a.png"
    _gradient().save(p)
    h1 = compute_dhash(p)
    h2 = compute_dhash(p)
    assert h1 == h2
    assert len(h1) == 16                        # 64 bits, 16 hex chars
    int(h1, 16)                                  # real hex, doesn't raise


def test_compute_dhash_resized_recompressed_copy_is_close(tmp_path):
    """The actual use case: an upscaled/recompressed copy of the same image should
    hash CLOSE (small Hamming distance), even though its bytes are completely
    different from the original."""
    orig = tmp_path / "orig.png"
    _gradient(64, 64).save(orig)
    # Simulate "upscaled or recompressed": resize up, then save through JPEG (lossy,
    # different format/bytes entirely) at low quality.
    upscaled = tmp_path / "upscaled.jpg"
    from PIL import Image
    with Image.open(orig) as im:
        im.resize((256, 256), Image.LANCZOS).save(upscaled, "JPEG", quality=40)

    h1, h2 = compute_dhash(orig), compute_dhash(upscaled)
    dist = bin(int(h1, 16) ^ int(h2, 16)).count("1")
    assert dist <= 10, "resized/recompressed copy should stay under the near-dup threshold"


def test_compute_dhash_unrelated_images_are_far(tmp_path):
    a = tmp_path / "ascending.png"
    b = tmp_path / "mirrored.png"
    _gradient(64, 64, reverse=False).save(a)
    _gradient(64, 64, reverse=True).save(b)
    dist = bin(int(compute_dhash(a), 16) ^ int(compute_dhash(b), 16)).count("1")
    assert dist > 10, "a genuinely different (mirrored) image should exceed the near-dup threshold"


def test_compute_dhash_unreadable_file_returns_none(tmp_path):
    junk = tmp_path / "not_an_image.png"
    junk.write_bytes(b"this is not image data")
    assert compute_dhash(junk) is None


def test_compute_dhash_missing_file_returns_none(tmp_path):
    assert compute_dhash(tmp_path / "nope.png") is None


# ---------------------------------------------------------------------------
# near_duplicate_groups() -- pure SQL + Hamming-distance clustering, hand-built
# hashes so the exact bit distances (and therefore the expected grouping /
# closeness_pct math) are known rather than incidental to real image content.
# ---------------------------------------------------------------------------

def test_near_duplicate_groups_clusters_close_hashes(tmp_path):
    db = tmp_path / "catalog.db"
    base = 0
    close = base ^ 0b111                 # distance 3 -- a real near-duplicate pair
    far = base ^ ((1 << 40) - 1)         # distance 40 -- nowhere near the threshold
    save_catalog(db, [
        _row(media_id="1", phash="{:016x}".format(base)),
        _row(media_id="2", phash="{:016x}".format(close)),
        _row(media_id="3", phash="{:016x}".format(far)),
    ])
    groups = near_duplicate_groups(db)
    assert len(groups) == 1
    assert set(groups[0]["media_ids"]) == {"1", "2"}
    assert groups[0]["closeness_pct"] == round(100 * (1 - 3 / 64), 1)


def test_near_duplicate_groups_merges_transitive_chain(tmp_path):
    """A ~ B (distance 1) and B ~ C (distance 10, right at the threshold) merge into
    ONE group via union-find even though A ~ C individually (distance 11) exceeds the
    threshold -- the chain-merge behavior the near_duplicate_groups() docstring
    claims. closeness_pct is the WORST (largest) pairwise distance actually found
    inside the final group (11, the A-C pair), not the tightest."""
    db = tmp_path / "catalog.db"
    a = 0
    b = a ^ 1                            # distance(a, b) == 1
    c = b ^ 2046                         # distance(b, c) == 10; distance(a, c) == 11
    save_catalog(db, [
        _row(media_id="a", phash="{:016x}".format(a)),
        _row(media_id="b", phash="{:016x}".format(b)),
        _row(media_id="c", phash="{:016x}".format(c)),
    ])
    groups = near_duplicate_groups(db)
    assert len(groups) == 1
    assert set(groups[0]["media_ids"]) == {"a", "b", "c"}
    assert groups[0]["closeness_pct"] == round(100 * (1 - 11 / 64), 1)


def test_near_duplicate_groups_skips_video_and_blank_phash(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", phash="0000000000000000"),
        _row(media_id="2", phash="0000000000000000", is_video="1"),
        _row(media_id="3", phash=""),
    ])
    assert near_duplicate_groups(db) == []


def test_near_duplicate_groups_no_rows_returns_empty(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", phash="")])
    assert near_duplicate_groups(db) == []


# ---------------------------------------------------------------------------
# run_backfill_phash() -- the CLI flag, run directly (SimpleNamespace args, the
# same pattern tests/test_thumbs.py uses for run_rebuild_thumbs) against a small
# disposable tmp_path fixture. NEVER run against the real pixai_backup/ out_dir.
# ---------------------------------------------------------------------------

def _png(path, color=(100, 50, 150)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def test_backfill_phash_fills_missing_rows_image_only(tmp_path):
    _png(tmp_path / "a_1.png", (200, 30, 30))
    _png(tmp_path / "b_2.png", (30, 200, 30))
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "v_3.mp4").write_bytes(b"not a real video, never opened")
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png"),
        _row(media_id="2", filename="b_2.png", phash="deadbeefdeadbeef"),  # already filled
        _row(media_id="3", filename="videos/v_3.mp4", is_video="1"),       # video: skipped
    ])
    out = core.run_backfill_phash(SimpleNamespace(out=str(tmp_path), workers=1, max=0,
                                                  progress=None))
    assert out["filled"] == 1                  # only row "1" needed filling
    assert out["unresolved"] == 0 and out["unreadable"] == 0

    from moonglade_gallery import load_catalog
    rows = {r["media_id"]: r for r in load_catalog(tmp_path / "catalog.db")}
    assert rows["1"]["phash"] and len(rows["1"]["phash"]) == 16
    assert rows["2"]["phash"] == "deadbeefdeadbeef"     # untouched, already had one
    assert rows["3"]["phash"] == ""                     # video: never touched


def test_backfill_phash_respects_max_cap(tmp_path):
    for i in range(1, 4):
        _png(tmp_path / "img_{}.png".format(i))
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id=str(i), filename="img_{}.png".format(i)) for i in range(1, 4)
    ])
    out = core.run_backfill_phash(SimpleNamespace(out=str(tmp_path), workers=1, max=1,
                                                  progress=None))
    assert out["filled"] == 1                  # capped to 1 of the 3 rows needing it

    from moonglade_gallery import load_catalog
    rows = load_catalog(tmp_path / "catalog.db")
    filled = [r for r in rows if r["phash"]]
    assert len(filled) == 1


def test_backfill_phash_counts_unresolved_file_separately(tmp_path):
    """A catalog row whose file isn't on disk (e.g. a purged/missing image) must be
    counted as 'unresolved', not silently dropped or conflated with a real failure."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="missing.png"),
    ])
    out = core.run_backfill_phash(SimpleNamespace(out=str(tmp_path), workers=1, max=0,
                                                  progress=None))
    assert out["filled"] == 0
    assert out["unresolved"] == 1


def test_backfill_phash_nothing_to_do_is_safe(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a.png", phash="0000000000000000"),
    ])
    out = core.run_backfill_phash(SimpleNamespace(out=str(tmp_path), workers=1, max=0,
                                                  progress=None))
    assert out == {"filled": 0, "unresolved": 0, "unreadable": 0, "total": 1}


# ---------------------------------------------------------------------------
# Schema migration -- the three-place contract (CATALOG_FIELDS/_CREATE_TABLE/
# _MIGRATIONS) for the new `phash` column, same pattern as
# tests/test_filesystem.py::test_migration_adds_paid_credit_to_existing_db_without_data_loss.
# The generic test_migrations_backfill_every_field_added_after_the_original_schema
# already covers this column too; this test additionally locks the no-data-loss
# round-trip specifically for phash.
# ---------------------------------------------------------------------------

def test_migration_adds_phash_to_existing_db_without_data_loss(tmp_path):
    import sqlite3
    from moonglade_gallery import migrate, load_catalog

    assert "phash" in CATALOG_FIELDS
    pre_fields = [f for f in CATALOG_FIELDS if f != "phash"]
    db = tmp_path / "pre_phash.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE catalog ({})".format(
        ", ".join(("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f))
                  for f in pre_fields)))
    con.execute("INSERT INTO catalog (media_id, task_id, filename, rating) VALUES (?,?,?,?)",
                ("m1", "t1", "keep.png", "5"))
    con.commit()
    con.close()

    rows = load_catalog(db)          # first open of this path -> migrate() runs _MIGRATIONS
    assert rows[0]["media_id"] == "m1" and rows[0]["filename"] == "keep.png"
    assert rows[0]["rating"] == "5"                 # no data loss
    assert rows[0]["phash"] in ("", None)           # migrated in, blank default

    row = dict(rows[0])
    row["phash"] = "abcdef0123456789"
    save_catalog(db, [row])
    got = load_catalog(db)[0]
    assert got["phash"] == "abcdef0123456789" and got["filename"] == "keep.png"
    migrate(db, force=True)          # re-running the DDL stays harmless (idempotent) --
                                     # force, or the per-process memo would skip it and
                                     # this line would prove nothing

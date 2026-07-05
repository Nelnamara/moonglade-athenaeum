"""Regression guard for the data-loss bug where a download/--update/--sync pass
rebuilt catalog rows and silently blanked local curation (collections, ratings,
tags, published state). carry_local_fields() must merge fresh download fields
OVER the existing row so curated data always survives a re-pull."""
import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, save_catalog, load_catalog


def test_carry_preserves_local_fields_over_download():
    known = {"m1": {
        "media_id": "m1", "task_id": "t1", "filename": "old_m1.png",
        "prompt_preview": "an elf", "prompt_full": "an elf, masterpiece",
        "collections": "Moonglade Banners,Favorites", "rating": "5",
        "art_tags": "elf,night", "is_published": "1", "title": "My Banner",
    }}
    # what a download pass rebuilds for the SAME media_id: only API/file fields,
    # no collections/rating/tags/etc.
    fresh = {
        "media_id": "m1", "task_id": "t1", "filename": "2026-07/m1.png",
        "url": "https://x/m1", "width": "1920", "height": "480",
        "prompt_preview": "an elf", "status": "completed", "created_at": "2026-07-01",
        "prompt_full": "an elf, masterpiece", "seed": "42", "model_name": "Tsubaki",
    }
    out = core.carry_local_fields(fresh, known)
    # local curation survived
    assert out["collections"] == "Moonglade Banners,Favorites"
    assert out["rating"] == "5" and out["art_tags"] == "elf,night"
    assert out["is_published"] == "1" and out["title"] == "My Banner"
    # fresh download fields still applied
    assert out["filename"] == "2026-07/m1.png" and out["seed"] == "42"
    assert out["model_name"] == "Tsubaki"


def test_carry_empty_fresh_never_clobbers():
    known = {"m1": {"media_id": "m1", "filename": "keep.png", "rating": "4"}}
    # a "missing download" row carries empty filename -- must NOT wipe the old one
    out = core.carry_local_fields(
        {"media_id": "m1", "filename": "", "url": "", "rating": ""}, known)
    assert out["filename"] == "keep.png" and out["rating"] == "4"


def test_carry_new_media_id_passes_through():
    out = core.carry_local_fields(
        {"media_id": "new", "filename": "new.png", "collections": ""}, {})
    assert out["media_id"] == "new" and out["filename"] == "new.png"


def test_round_trip_through_catalog(tmp_path):
    """End-to-end: a curated row, then a download-shaped re-save via carry, keeps
    its collection through an actual save_catalog + reload."""
    db = tmp_path / "catalog.db"
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({"media_id": "m9", "task_id": "t9", "filename": "a.png",
                "collections": "Moonglade Icons", "rating": "5"})
    save_catalog(db, [row])
    known = {r["media_id"]: r for r in load_catalog(db)}
    rebuilt = core.carry_local_fields(
        {"media_id": "m9", "task_id": "t9", "filename": "2026-07/a.png",
         "prompt_full": "fresh"}, known)
    save_catalog(db, [rebuilt])
    back = {r["media_id"]: r for r in load_catalog(db)}["m9"]
    assert back["collections"] == "Moonglade Icons" and back["rating"] == "5"
    assert back["filename"] == "2026-07/a.png" and back["prompt_full"] == "fresh"

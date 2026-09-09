"""Tier-1 curation tools on the MCP server (moonglade_mcp.py).

The tools are thin wrappers over already-tested gallery helpers, so this pins the
WRAPPER contract: the right helper is called, the filters reach query_catalog, and the
return shapes are what an agent consumes. `fastmcp` is an OPTIONAL dep (not in the CI
curated list), so the whole module skips cleanly where it isn't installed -- same
discipline as any other optional-dep test here.
"""
import pytest

pytest.importorskip("fastmcp")   # CI installs no fastmcp -> skip, never fail

import moonglade_gallery as g
import moonglade_mcp as m


def _row(**kw):
    return {f: "" for f in g.CATALOG_FIELDS} | kw


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A small catalog wired into the MCP module's DB/OUT globals the tools read."""
    # query_catalog's base WHERE is `filename != ''`, so every row needs one.
    rows = [
        _row(media_id="m1", filename="m1.webp", rating=0, collections="", source="api", is_video="",
             created_at="2026-01-01", prompt_full="a night elf archdruid", model_name="Tsubaki"),
        _row(media_id="m2", filename="m2.webp", rating=5, collections="Favorites", source="api", is_video="",
             created_at="2026-02-01", prompt_full="moonwell at dusk", model_name="Tsubaki"),
        _row(media_id="m3", filename="m3.webp", rating=3, collections="Favorites,Drafts", source="local", is_video="",
             created_at="2026-03-01", prompt_full="a druid's study", model_name="Anything"),
        _row(media_id="m4", filename="m4.mp4", rating=0, collections="", source="api", is_video="1",
             created_at="2026-04-01", prompt_full="a short clip", model_name="Wan"),
    ]
    db = tmp_path / "catalog.db"
    g.save_catalog(db, rows)
    monkeypatch.setattr(m, "DB", str(db))
    monkeypatch.setattr(m, "OUT", tmp_path)
    return db


def test_list_collections_reports_names_and_counts(catalog):
    out = m.list_collections()
    assert out["count"] == 2
    by_name = {c["name"]: c["count"] for c in out["collections"]}
    assert by_name == {"Favorites": 2, "Drafts": 1}
    # sorted case-insensitive: Drafts before Favorites
    assert [c["name"] for c in out["collections"]] == ["Drafts", "Favorites"]


def test_remove_from_collection_changes_only_matching_rows(catalog):
    assert m.remove_from_collection(["m3"], "Drafts") == {"ok": True, "collection": "Drafts", "removed": 1}
    # Drafts is now empty -> gone from the list; Favorites still has both
    names = {c["name"]: c["count"] for c in m.list_collections()["collections"]}
    assert "Drafts" not in names and names["Favorites"] == 2
    # a media_id not in the collection is a no-op, not an error
    assert m.remove_from_collection(["m1"], "Favorites")["removed"] == 0
    assert m.remove_from_collection(["m2"], "")["ok"] is False


def test_get_images_batches_metadata_and_reports_missing(catalog):
    out = m.get_images(["m1", "m2", "nope"])
    assert out["count"] == 2
    assert {r["media_id"] for r in out["rows"]} == {"m1", "m2"}
    assert out["missing"] == ["nope"]
    # no `missing` key when all resolve
    assert "missing" not in m.get_images(["m1"])


def test_catalog_stats_describes_the_library(catalog):
    st = m.catalog_stats()
    assert st["total"] == 4
    assert st["images"] == 3 and st["videos"] == 1
    assert st["by_source"] == {"api": 3, "local": 1}
    # exact-rating buckets: two unrated (m1, m4), one @3, one @5
    assert st["by_rating"]["0"] == 2
    assert st["by_rating"]["3"] == 1 and st["by_rating"]["5"] == 1
    assert st["by_rating"]["1"] == 0 and st["by_rating"]["4"] == 0
    assert {c["name"]: c["count"] for c in st["collections"]} == {"Favorites": 2, "Drafts": 1}
    assert st["newest"] == "2026-04-01" and st["oldest"] == "2026-01-01"


def test_pull_for_review_uncollected_only(catalog):
    out = m.pull_for_review(uncollected_only=True, unrated_only=False)
    # only m1 and m4 are in no collection
    assert {r["media_id"] for r in out["rows"]} == {"m1", "m4"}


def test_search_catalog_new_filters(catalog):
    assert {r["media_id"] for r in m.search_catalog(media_type="video")["rows"]} == {"m4"}
    assert {r["media_id"] for r in m.search_catalog(source="local")["rows"]} == {"m3"}
    # the created-at range reaches query_catalog
    hits = m.search_catalog(date_from="2026-02-15", date_to="2026-03-15")["rows"]
    assert {r["media_id"] for r in hits} == {"m3"}

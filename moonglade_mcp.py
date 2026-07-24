"""moonglade_mcp.py -- MCP server exposing the Moonglade Athenaeum catalog for
AI-assisted curation of the local PixAI backup. LOCAL stdio, owner-only.

Reuses pixai_gallery.py's catalog helpers + pixai_similar.similar() -- no SQL is
reimplemented here. Read-mostly; set_rating / add_to_collection are the only writes.

Config: env MOONGLADE_OUT = the backup dir that holds catalog.db (e.g.
"D:\\Moonglade Athenaeum\\pixai_backup"). Falls back to ./pixai_backup next to this file.

Register in Claude Code:
    claude mcp add moonglade -e MOONGLADE_OUT="D:\\Moonglade Athenaeum\\pixai_backup" \\
        -- python "C:\\Users\\gwilkins\\source\\repos\\pixai-gallery-backup\\moonglade_mcp.py"
Then restart Claude Code; tools appear as moonglade:search_catalog, moonglade:similar, ...

NOTE: the Similar tool loads the Pixeltable index (embedded Postgres). Don't run a
Similar-heavy MCP session at the same time as `--rebuild-similar` -- both touch the
same DB.
"""
import io
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

import pixai_gallery as g   # catalog helpers -- the single source of truth for SQL

OUT = Path(os.environ.get("MOONGLADE_OUT") or (Path(__file__).resolve().parent / "pixai_backup"))
DB = str(OUT / "catalog.db")

mcp = FastMCP("moonglade-athenaeum")

def _slim(row):
    """Curation-relevant fields from a full catalog row, with friendly names
    (the real columns are prompt_full/prompt_preview and model_name/model_id)."""
    return {
        "media_id": row.get("media_id"),
        "prompt": row.get("prompt_full") or row.get("prompt_preview") or "",
        "model": row.get("model_name") or row.get("model_id") or "",
        "rating": row.get("rating") or 0,
        "collections": row.get("collections") or "",
        "is_nsfw": row.get("is_nsfw"),
        "title": row.get("title") or "",
        "seed": row.get("seed"),
        "art_tags": row.get("art_tags") or "",
        "created_at": row.get("created_at"),
        "is_video": row.get("is_video"),
        "source": row.get("source"),
        "liked_count": row.get("liked_count"),
        # Actual credit cost of the row's task ('0' = free via card/daily, '' = never
        # captured). Task-level: batch siblings repeat the same value.
        "paid_credit": row.get("paid_credit") or "",
        "dimensions": "{}x{}".format(row.get("width") or "?", row.get("height") or "?"),
        "filename": row.get("filename"),
    }


@mcp.tool
def search_catalog(query: str = "", model: str = "", collection: str = "",
                   rating_min: int = 0, source: str = "", media_type: str = "",
                   sort: str = "newest", limit: int = 30) -> dict:
    """Search the image catalog. `query` matches prompt text; filter by model,
    collection, minimum star rating (0-5), source (api/local), or media_type
    (image/video). sort: newest|oldest|rating. Returns {total, count, rows}."""
    rows, total = g.query_catalog(
        DB, q=query, model=model, collection=collection,
        rating_min=max(0, min(rating_min, 5)), source=source, media_type=media_type,
        sort=sort, page=1, page_size=max(1, min(limit, 100)))
    return {"total": total, "count": len(rows), "rows": [_slim(r) for r in rows]}


@mcp.tool
def get_image(media_id: str, include_image: bool = True):
    """Full metadata for ONE image and, by default, a downscaled view so you can
    actually see it. Returns metadata; when include_image, also an image block."""
    row = g.get_row(DB, media_id)
    if not row:
        return {"error": "no such media_id", "media_id": media_id}
    meta = _slim(row)
    if not include_image:
        return meta
    path = g.find_image_file(OUT, media_id, row.get("filename") or "")
    if not path:
        return {**meta, "note": "image file not found on disk"}
    try:
        import PIL.Image
        im = PIL.Image.open(path)
        im.thumbnail((640, 640))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=85)
        return [meta, Image(data=buf.getvalue(), format="jpeg")]
    except Exception as e:
        return {**meta, "note": "could not render image: {}".format(e)}


@mcp.tool
def similar(media_id: str, limit: int = 24) -> dict:
    """Visually-similar images (CLIP) to `media_id`, via the local Similar index.
    Returns neighbors with similarity scores + metadata (self-match excluded)."""
    row = g.get_row(DB, media_id)
    if not row:
        return {"error": "no such media_id", "neighbors": []}
    path = g.find_image_file(OUT, media_id, row.get("filename") or "")
    if not path:
        return {"error": "image file not on disk", "neighbors": []}
    try:
        import pixai_similar as ps
        hits = ps.similar(str(path), k=max(1, min(limit, 96)), exclude_media_id=media_id)
    except Exception as e:
        return {"error": "similar index unavailable: {}".format(e), "neighbors": []}
    neighbors = []
    for mid, score in hits:
        r = g.get_row(DB, mid)
        if r:
            neighbors.append({**_slim(r), "score": round(float(score), 4)})
    return {"query": media_id, "count": len(neighbors), "neighbors": neighbors}


@mcp.tool
def set_rating(media_id: str, rating: int) -> dict:
    """WRITE: set an image's star rating, 0-5 (0 = unrated). Persists to catalog.db."""
    value = max(0, min(5, int(rating)))
    g.update_rating(DB, media_id, value)
    return {"ok": True, "media_id": media_id, "rating": value}


@mcp.tool
def add_to_collection(media_ids: list[str], collection: str) -> dict:
    """WRITE: add one or more images to a named collection (created if new).
    Returns how many rows were added."""
    name = (collection or "").strip()
    if not name:
        return {"ok": False, "error": "collection name required"}
    n = g.add_to_collection(DB, [str(m) for m in media_ids], name)
    return {"ok": True, "collection": name, "added": n}


@mcp.tool
def pull_for_review(limit: int = 20, unrated_only: bool = True, source: str = "") -> dict:
    """Fetch a set of images that likely need curation -- newest first, unrated by
    default. Review, then set_rating / add_to_collection. Returns {count, rows}."""
    rows, _ = g.query_catalog(DB, source=source, sort="newest", page=1,
                              page_size=max(1, min(limit * 5, 300)))
    picked = []
    for r in rows:
        if unrated_only and int(r.get("rating") or 0) != 0:
            continue
        picked.append(_slim(r))
        if len(picked) >= limit:
            break
    return {"count": len(picked), "rows": picked}


if __name__ == "__main__":
    mcp.run(transport="stdio")

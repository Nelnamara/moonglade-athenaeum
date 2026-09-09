"""moonglade_mcp.py -- MCP server exposing the Moonglade Athenaeum catalog for
AI-assisted curation of the local PixAI backup. LOCAL stdio, owner-only.

Reuses moonglade_gallery.py's catalog helpers + moonglade_similar.similar() -- no SQL is
reimplemented here. Catalog writes are set_rating / add_to_collection / remove_from_collection; tag_suggest is the first tool to reach the PixAI account (free, read-only).

Config: env MOONGLADE_OUT = the backup dir that holds catalog.db (e.g.
"D:\\path\\to\\pixai_backup"). Falls back to ./pixai_backup next to this file.

Register in Claude Code:
    claude mcp add moonglade -e MOONGLADE_OUT="D:\\path\\to\\pixai_backup" \\
        -- python "C:\\Users\\<you>\\source\\repos\\pixai-gallery-backup\\moonglade_mcp.py"
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

import moonglade_gallery as g   # catalog helpers -- the single source of truth for SQL

OUT = Path(os.environ.get("MOONGLADE_OUT") or (Path(__file__).resolve().parent / "pixai_backup"))
DB = str(OUT / "catalog.db")

mcp = FastMCP("moonglade-athenaeum")

# ---------------------------------------------------------------------------
# PixAI session. The ACCOUNT-acting tools (tag_suggest today; generate / delete /
# claim on the roadmap) need a live PixAI session, unlike the catalog-only tools.
# Built exactly as the CLI/web do -- moonglade_backup._make_session(None) resolves
# PIXAI_API_KEY from config.json -- lazily and once, so a session that only ever
# touches the local catalog never imports the backup module or holds a credential.
# READ_ONLY in config.json still overrides every mutating path (via _check_read_only
# inside the backup helpers), exactly as for the CLI and the web app.
# ---------------------------------------------------------------------------
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        import moonglade_backup as mb
        _SESSION = mb._make_session(None)
    return _SESSION

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
                   art_tag: str = "", lora: str = "", date_from: str = "", date_to: str = "",
                   published_only: bool = False, sort: str = "newest", limit: int = 30) -> dict:
    """Search the image catalog. `query` matches prompt text; filter by model,
    collection, minimum star rating (0-5), source (api/local), media_type
    (image/video), art_tag, lora, a created-at range (date_from/date_to as YYYY-MM-DD),
    or published_only. sort: newest|oldest|rating. Returns {total, count, rows}."""
    rows, total = g.query_catalog(
        DB, q=query, model=model, collection=collection,
        rating_min=max(0, min(rating_min, 5)), source=source, media_type=media_type,
        art_tag=art_tag, lora=lora, date_from=date_from, date_to=date_to,
        published_only=published_only,
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
    Returns neighbors with similarity scores + metadata (self-match excluded).
    `stale_index_entries` counts neighbours the index still holds but the catalog no
    longer does -- when it is non-zero, `count` is short of `requested` for that
    reason and not because the library ran out of similar images."""
    row = g.get_row(DB, media_id)
    if not row:
        return {"error": "no such media_id", "neighbors": []}
    path = g.find_image_file(OUT, media_id, row.get("filename") or "")
    if not path:
        return {"error": "image file not on disk", "neighbors": []}
    k = max(1, min(limit, 96))
    try:
        import moonglade_similar as ps
        hits = ps.similar(str(path), k=k, exclude_media_id=media_id)
    except Exception as e:
        return {"error": "similar index unavailable: {}".format(e), "neighbors": []}
    neighbors = []
    stale = []
    for mid, score in hits:
        r = g.get_row(DB, mid)
        if r:
            neighbors.append({**_slim(r), "score": round(float(score), 4)})
        else:
            # In the index, absent from the catalog: the image was deleted/purged after it
            # was embedded and nothing pruned the sidecar. Dropping these silently is what
            # made `count: 15` on a `limit: 24` request read as "there are only 15 similar
            # images" -- an agent curating off that number draws the wrong conclusion about
            # the library. Report the shortfall and name its cause instead.
            #
            # This tool does NOT clear them itself: it is interactive and expected to answer
            # fast, and the index has no per-id removal path -- `sync()` only ever adds. The
            # cure is --rebuild-similar, which drops and re-embeds; that is minutes of GPU
            # time, so it is the owner's call to make, not a side effect of a lookup.
            stale.append(mid)
    out = {"query": media_id, "requested": k, "count": len(neighbors),
           "stale_index_entries": len(stale), "neighbors": neighbors}
    if stale:
        out["stale_media_ids"] = stale
        out["note"] = (
            "{} of the {} nearest neighbours are stale similarity-index entries whose "
            "catalog row is gone (deleted or purged), so fewer than the requested {} came "
            "back -- this is index drift, not a shortage of similar images. Rebuilding the "
            "index (--rebuild-similar, or the Control Panel's Rebuild job) clears it."
            .format(len(stale), len(hits), k))
    return out


@mcp.tool
def set_rating(media_id: str, rating: int) -> dict:
    """WRITE: set an image's star rating, 0-5 (0 = unrated). Persists to catalog.db.
    Returns ok:False for a media_id that isn't in the catalog -- nothing was written."""
    value = max(0, min(5, int(rating)))
    # g.update_rating is a bare `UPDATE ... WHERE media_id=?` and returns nothing, so a
    # mistyped or stale id matches zero rows and the write vanishes without a whisper.
    # Reporting ok:True for that told the caller the rating had been set: an agent working
    # through a review queue marks the image done, and it stays unrated forever. The check
    # lives here rather than in update_rating because the gallery helper has other callers
    # whose contract (silent no-op on a missing row) this tool has no business changing.
    if not g.get_row(DB, media_id):
        return {"ok": False, "error": "no such media_id", "media_id": media_id}
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
def pull_for_review(limit: int = 20, unrated_only: bool = True,
                    uncollected_only: bool = False, source: str = "") -> dict:
    """Fetch images that likely need curation -- newest first, unrated by default.
    Set uncollected_only to surface images in NO collection instead (a common curation
    target). Review, then set_rating / add_to_collection. Returns {count, rows}."""
    rows, _ = g.query_catalog(DB, source=source, sort="newest", page=1,
                              page_size=max(1, min(limit * 5, 300)))
    picked = []
    for r in rows:
        if unrated_only and int(r.get("rating") or 0) != 0:
            continue
        if uncollected_only and (r.get("collections") or "").strip():
            continue
        picked.append(_slim(r))
        if len(picked) >= limit:
            break
    return {"count": len(picked), "rows": picked}


@mcp.tool
def list_collections() -> dict:
    """List every named collection and how many images each holds -- the view
    add_to_collection / remove_from_collection are blind to on their own. Returns
    {count, collections:[{name, count}]}."""
    out = []
    for name in g.unique_collections(DB):
        _, total = g.query_catalog(DB, collection=name, page=1, page_size=1)
        out.append({"name": name, "count": total})
    return {"count": len(out), "collections": out}


@mcp.tool
def remove_from_collection(media_ids: list[str], collection: str) -> dict:
    """WRITE: remove one or more images from a named collection. Returns how many rows
    changed; a media_id that wasn't in that collection is skipped, not an error."""
    name = (collection or "").strip()
    if not name:
        return {"ok": False, "error": "collection name required"}
    n = g.remove_from_collection(DB, [str(m) for m in media_ids], name)
    return {"ok": True, "collection": name, "removed": n}


@mcp.tool
def get_images(media_ids: list[str]) -> dict:
    """Metadata for SEVERAL images at once -- the batch form of get_image, for
    cross-referencing a set of ids (search hits, similar neighbours) without a call
    each. Metadata only; for a visual, call get_image on the one you want. Unknown ids
    come back under `missing`."""
    rows, missing = [], []
    for mid in [str(m) for m in media_ids][:100]:
        row = g.get_row(DB, mid)
        if row:
            rows.append(_slim(row))
        else:
            missing.append(mid)
    out = {"count": len(rows), "rows": rows}
    if missing:
        out["missing"] = missing
    return out


@mcp.tool
def catalog_stats() -> dict:
    """At-a-glance shape of the library, so an agent can decide what to curate without
    paging search: totals, media-type / source / exact-rating breakdowns, the created-at
    span, and every collection with its size. Read-only, built from query_catalog totals
    (no reimplemented SQL)."""
    def total(**kw):
        _, t = g.query_catalog(DB, page=1, page_size=1, **kw)
        return t
    # exact-rating buckets from the cumulative rating_min filter: rating r is
    # (>= r) minus (>= r+1); rating 0 is "unrated" (all minus rated-1-or-more).
    by_rating = {}
    for r in range(0, 6):
        hi = total(rating_min=r + 1) if r < 5 else 0
        by_rating[str(r)] = total(rating_min=r) - hi
    newest, _ = g.query_catalog(DB, sort="newest", page=1, page_size=1)
    oldest, _ = g.query_catalog(DB, sort="oldest", page=1, page_size=1)
    return {
        "total": total(),
        "images": total(media_type="image"),
        "videos": total(media_type="video"),
        "by_source": {src: total(source=src) for src in ("api", "local")},
        "by_rating": by_rating,
        "collections": [{"name": n, "count": total(collection=n)}
                        for n in g.unique_collections(DB)],
        "newest": (newest[0].get("created_at") if newest else None),
        "oldest": (oldest[0].get("created_at") if oldest else None),
    }


@mcp.tool
def find_duplicates(limit: int = 100) -> dict:
    """Class-A duplicate groups in the LOCAL library -- a media_id whose file sits in
    more than one folder bucket -- so you can thin or quarantine them. Cheap (no hashing),
    read-only, local (no session). Returns {count, groups:[{media_id, keeper, copies}]}."""
    groups = g.duplicate_groups(OUT, limit=max(1, min(limit, 500)))
    return {"count": len(groups), "groups": groups}


@mcp.tool
def tag_suggest(media_id: str) -> dict:
    """PixAI's own image->tags/description suggestion for ONE image (its "Image to
    prompt"): a Danbooru-style tag list plus a natural-language variant, to auto-tag or
    seed a search. FREE and read-only -- no credits, no mutation -- but it is the first
    tool that reaches the PixAI ACCOUNT, so it needs the session (config.json's
    PIXAI_API_KEY). Returns {media_id, suggestions:[...]} or {..., error} on failure."""
    import moonglade_backup as mb
    try:
        out = mb.suggest_prompt(_session(), str(media_id))
    except Exception as e:
        return {"media_id": media_id, "suggestions": [], "error": str(e)}
    return {"media_id": media_id, "suggestions": list(out or [])}


if __name__ == "__main__":
    mcp.run(transport="stdio")

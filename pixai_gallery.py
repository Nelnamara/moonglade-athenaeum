#!/usr/bin/env python3
"""
pixai_gallery.py
================
Local Flask web gallery for your PixAI backup collection.

Reads catalog.db (SQLite) and serves a browseable, filterable, paginated image
gallery at http://localhost:5000 . Supports single and bulk delete (removes
image file, thumbnail, and catalog row).

Requirements:
    pip install flask pillow

Usage:
    python pixai_gallery.py
    python pixai_gallery.py --out pixai_backup --port 5000
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

try:
    from flask import (Flask, jsonify, redirect, render_template_string, request,
                       send_file, send_from_directory, url_for)
except ImportError:
    sys.exit("Flask is required for the gallery server.\n"
             "Install it with:  pip install flask")

try:
    from PIL import Image
except ImportError:
    Image = None  # thumbnails will be skipped with a warning


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------
CATALOG_FIELDS = [
    "task_id", "media_id", "filename", "batch", "url", "width", "height",
    "prompt_preview", "status", "created_at",
    "prompt_full", "natural_prompt", "seed", "steps",
    "sampler", "cfg_scale", "model_id", "model_name", "rating",
    # Published-artwork metadata, populated by --sync-artworks (blank otherwise)
    "artwork_id", "title", "is_published", "is_nsfw",
    "liked_count", "comment_count", "aes_score", "art_tags",
    # LoRAs used, populated by --full-meta / --backfill-full-meta ("Name:0.7, …")
    "loras",
    # Extra reproduction params from getTaskById (full-meta)
    "negative_prompt", "clip_skip",
    # Image-to-video tasks (--sync-videos): is_video='1', poster_media_id is the
    # still-frame media id (its image is the gallery poster), duration in seconds.
    "is_video", "poster_media_id", "video_duration",
    # Provenance: '' / 'online' = backed up from PixAI history; 'api' = created via
    # --generate; 'local' = imported from disk via --import-local.
    "source",
    # '1' if --reconcile-deleted found this row's task is gone from your live PixAI
    # feed (i.e. you deleted it on the website). Advisory; cleared on re-reconcile.
    "deleted_remote",
    # User collections: comma-joined names (no moving files, survives organize).
    # Names may contain spaces but not commas. Set/filtered in the gallery.
    "collections",
    # Published-artwork `extra` (--sync-artworks, published rows only): a compact
    # BlurHash string for instant gallery placeholders, and PixAI's per-category NSFW
    # classifier scores as a JSON blob {porn,sexy,hentai,neutral,drawings}.
    "blurhash", "nsfw_scores",
]

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"})
THUMB_SIZE = (768, 768)
THUMB_QUALITY = 90
PAGE_SIZE = 100


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS catalog (
    media_id        TEXT PRIMARY KEY,
    task_id         TEXT,
    filename        TEXT,
    batch           TEXT DEFAULT '',
    url             TEXT,
    width           TEXT,
    height          TEXT,
    prompt_preview  TEXT,
    status          TEXT,
    created_at      TEXT,
    prompt_full     TEXT,
    natural_prompt  TEXT,
    seed            TEXT,
    steps           TEXT,
    sampler         TEXT,
    cfg_scale       TEXT,
    model_id        TEXT,
    model_name      TEXT,
    rating          TEXT,
    artwork_id      TEXT DEFAULT '',
    title           TEXT DEFAULT '',
    is_published    TEXT DEFAULT '',
    is_nsfw         TEXT DEFAULT '',
    liked_count     TEXT DEFAULT '',
    comment_count   TEXT DEFAULT '',
    aes_score       TEXT DEFAULT '',
    art_tags        TEXT DEFAULT '',
    loras           TEXT DEFAULT '',
    negative_prompt TEXT DEFAULT '',
    clip_skip       TEXT DEFAULT '',
    is_video        TEXT DEFAULT '',
    poster_media_id TEXT DEFAULT '',
    video_duration  TEXT DEFAULT '',
    source          TEXT DEFAULT '',
    deleted_remote  TEXT DEFAULT '',
    collections     TEXT DEFAULT '',
    blurhash        TEXT DEFAULT '',
    nsfw_scores     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_created_at ON catalog(created_at);
CREATE INDEX IF NOT EXISTS idx_model_name ON catalog(model_name);
CREATE INDEX IF NOT EXISTS idx_rating     ON catalog(rating);
"""

_UPSERT = """
INSERT INTO catalog ({fields})
VALUES ({placeholders})
ON CONFLICT(media_id) DO UPDATE SET
{updates};
""".format(
    fields=", ".join(CATALOG_FIELDS),
    placeholders=", ".join("?" for _ in CATALOG_FIELDS),
    updates=", ".join(
        "{f}=excluded.{f}".format(f=f) for f in CATALOG_FIELDS if f != "media_id"
    ),
)


def init_db(db_path):
    """Create the catalog table and indexes if they don't exist yet."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.executescript(_CREATE_TABLE)
    # Add batch column to pre-existing databases that lack it, then index it
    try:
        con.execute("ALTER TABLE catalog ADD COLUMN batch TEXT DEFAULT ''")
        con.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    con.execute("CREATE INDEX IF NOT EXISTS idx_batch ON catalog(batch)")
    con.commit()
    con.close()


_MIGRATIONS = [
    "ALTER TABLE catalog ADD COLUMN batch TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN artwork_id TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN title TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN is_published TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN is_nsfw TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN liked_count TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN comment_count TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN aes_score TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN art_tags TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN loras TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN negative_prompt TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN clip_skip TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN is_video TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN poster_media_id TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN video_duration TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN source TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN deleted_remote TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN collections TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN blurhash TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN nsfw_scores TEXT DEFAULT ''",
]

def _connect(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    for sql in _MIGRATIONS:
        try:
            con.execute(sql)
            con.commit()
        except sqlite3.OperationalError:
            pass  # column/index already exists
    return con


def load_catalog(db_path):
    """Return all rows as a list of plain dicts, oldest-first."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT * FROM catalog").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def save_catalog(db_path, rows):
    """Upsert a list of dicts into the catalog (replaces the old full-rewrite)."""
    db_path = Path(db_path)
    init_db(db_path)
    con = _connect(db_path)
    try:
        con.executemany(
            _UPSERT,
            [tuple(r.get(f, "") or "" for f in CATALOG_FIELDS) for r in rows],
        )
        con.commit()
    finally:
        con.close()


def update_rating(db_path, media_id, value):
    """Update a single row's rating without touching the rest of the catalog."""
    con = _connect(db_path)
    try:
        con.execute(
            "UPDATE catalog SET rating=? WHERE media_id=?",
            (str(value) if value else "", media_id),
        )
        con.commit()
    finally:
        con.close()


def delete_from_catalog(db_path, media_id):
    """Remove a single row by media_id."""
    con = _connect(db_path)
    try:
        con.execute("DELETE FROM catalog WHERE media_id=?", (media_id,))
        con.commit()
    finally:
        con.close()


def update_prompt_full(db_path, media_id, text):
    """Overwrite a single row's prompt_full (manual annotation/correction)."""
    con = _connect(db_path)
    try:
        con.execute("UPDATE catalog SET prompt_full=? WHERE media_id=?",
                    (text or "", media_id))
        con.commit()
    finally:
        con.close()


def bulk_replace_prompt(db_path, media_ids, find, replace):
    """Find/replace a substring in prompt_full across the given media_ids.
    Returns the number of rows actually changed."""
    if not find:
        return 0
    con = _connect(db_path)
    changed = 0
    try:
        for mid in media_ids:
            row = con.execute("SELECT prompt_full FROM catalog WHERE media_id=?",
                              (mid,)).fetchone()
            if not row:
                continue
            old = row[0] or ""
            new = old.replace(find, replace)
            if new != old:
                con.execute("UPDATE catalog SET prompt_full=? WHERE media_id=?", (new, mid))
                changed += 1
        con.commit()
    finally:
        con.close()
    return changed


def _db_is_empty(db_path):
    """Return True if the database has no rows (missing or freshly initialised)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return True
    try:
        con = sqlite3.connect(str(db_path))
        count = con.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
        con.close()
        return count == 0
    except sqlite3.OperationalError:
        return True


def migrate_csv_to_db(csv_path, db_path):
    """One-time migration: import catalog.csv into catalog.db.

    Safe to re-run — existing rows are upserted, not duplicated.
    Returns the number of rows imported.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0
    save_catalog(db_path, rows)
    return len(rows)


def export_csv(db_path, csv_path):
    """Export catalog.db back to a CSV file (backup / interop)."""
    rows = load_catalog(db_path)
    csv_path = Path(csv_path)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({field: r.get(field, "") for field in CATALOG_FIELDS})


_SORT_SQL = {
    "oldest":      "created_at ASC",
    "rating_desc": "CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) DESC, created_at DESC",
    "rating_asc":  "CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) ASC,  created_at DESC",
    "model":       "LOWER(COALESCE(NULLIF(model_name,''), NULLIF(model_id,''), '')) ASC",
    "width":       "CAST(COALESCE(NULLIF(width,''),'0')  AS INTEGER) DESC",
    "height":      "CAST(COALESCE(NULLIF(height,''),'0') AS INTEGER) DESC",
    "pixels":      "(CAST(COALESCE(NULLIF(width,''),'0') AS INTEGER) * "
                   "CAST(COALESCE(NULLIF(height,''),'0') AS INTEGER)) DESC",
    "aspect":      "(CAST(COALESCE(NULLIF(width,''),'0') AS REAL) / "
                   "NULLIF(CAST(COALESCE(NULLIF(height,''),'0') AS REAL),0)) DESC",
    "aes_desc":    "CAST(COALESCE(NULLIF(aes_score,''),'0') AS REAL) DESC, created_at DESC",
    "aes_asc":     "CAST(COALESCE(NULLIF(aes_score,''),'0') AS REAL) ASC,  created_at DESC",
    "likes":       "CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) DESC, created_at DESC",
}
_DEFAULT_SORT_SQL = "created_at DESC"


def _like_pattern(term):
    r"""Translate a user search term into a SQL LIKE pattern.

    * `*` -> `%` (any run) and `?` -> `_` (single char), so `night*` matches
      anything starting with "night".
    * A term with NO wildcard is treated as a substring (wrapped in `%...%`),
      preserving the old broad-search behavior.
    * Literal `%`/`_`/`\` the user typed are escaped (LIKE uses ESCAPE '\').
    """
    t = term.strip().lower()
    has_wild = "*" in t or "?" in t
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    t = t.replace("*", "%").replace("?", "_")
    return t if has_wild else "%" + t + "%"


def _build_where(q, model, date_from, date_to, batch="", rating_min=0,
                 published_only=False, art_tag="", lora="", media_type="", source="",
                 collection=""):
    """Return (where_clause, params) for the common filter set."""
    clauses = ["filename != ''"]
    params  = []
    if collection:
        # exact-token match within the comma-joined list (no partial-name bleed)
        clauses.append("(',' || COALESCE(collections,'') || ',') LIKE ?")
        params.append("%," + collection + ",%")
    if media_type == "video":
        clauses.append("is_video = '1'")
    elif media_type == "image":
        clauses.append("COALESCE(is_video,'') != '1'")
    if source == "online":
        clauses.append("COALESCE(source,'') IN ('', 'online')")
    elif source in ("api", "local"):
        clauses.append("source = ?")
        params.append(source)
    elif source == "deleted":
        clauses.append("deleted_remote = '1'")   # flagged by --reconcile-deleted
    if rating_min:
        clauses.append("CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) >= ?")
        params.append(int(rating_min))
    if published_only:
        clauses.append("is_published = '1'")
    if art_tag:
        clauses.append("LOWER(COALESCE(art_tags,'')) LIKE ?")
        params.append("%" + art_tag.strip().lower() + "%")
    if lora:
        clauses.append("LOWER(COALESCE(loras,'')) LIKE ?")
        params.append("%" + lora.strip().lower() + "%")
    if q:
        # Whitespace-separated terms are ANDed; each may use * / ? wildcards.
        for term in q.split():
            clauses.append("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
                           "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')")
            like = _like_pattern(term)
            params += [like, like]
    if model:
        clauses.append("model_name = ?")
        params.append(model)
    if batch:
        clauses.append("batch = ?")
        params.append(batch)
    if date_from:
        clauses.append("SUBSTR(created_at,1,7) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("SUBSTR(created_at,1,7) <= ?")
        params.append(date_to)
    return " AND ".join(clauses), params


def get_row(db_path, media_id):
    """Return a single catalog row dict by media_id, or None."""
    con = _connect(db_path)
    try:
        row = con.execute("SELECT * FROM catalog WHERE media_id=?", (media_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _split_collections(s):
    return [c.strip() for c in (s or "").split(",") if c.strip()]


def unique_collections(db_path):
    """Distinct collection names across the catalog, case-insensitive sorted."""
    con = _connect(db_path)
    try:
        names = set()
        for (s,) in con.execute("SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
            names.update(_split_collections(s))
        return sorted(names, key=str.lower)
    finally:
        con.close()


def add_to_collection(db_path, media_ids, name):
    """Add a collection label to each media_id (no-op if already in it). Names may
    contain spaces but not commas. Returns the number of rows changed."""
    name = (name or "").strip().replace(",", " ").strip()
    if not name or not media_ids:
        return 0
    con = _connect(db_path)
    changed = 0
    try:
        for mid in media_ids:
            row = con.execute("SELECT collections FROM catalog WHERE media_id=?", (mid,)).fetchone()
            if not row:
                continue
            cols = _split_collections(row[0])
            if name not in cols:
                cols.append(name)
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(cols), mid))
                changed += 1
        con.commit()
    finally:
        con.close()
    return changed


def remove_from_collection(db_path, media_ids, name):
    """Remove a collection label from each media_id. Returns rows changed."""
    name = (name or "").strip()
    if not name or not media_ids:
        return 0
    con = _connect(db_path)
    changed = 0
    try:
        for mid in media_ids:
            row = con.execute("SELECT collections FROM catalog WHERE media_id=?", (mid,)).fetchone()
            if not row:
                continue
            cols = _split_collections(row[0])
            if name in cols:
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(c for c in cols if c != name), mid))
                changed += 1
        con.commit()
    finally:
        con.close()
    return changed


def query_catalog(db_path, q="", model="", date_from="", date_to="",
                  sort="newest", page=1, page_size=100, batch="", rating_min=0,
                  published_only=False, art_tag="", lora="", media_type="", source="",
                  collection=""):
    """Return (rows, total) with filtering, sorting and pagination done in SQL."""
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    order = _SORT_SQL.get(sort, _DEFAULT_SORT_SQL)
    offset = (max(1, page) - 1) * page_size
    con = _connect(db_path)
    try:
        total = con.execute(
            "SELECT COUNT(*) FROM catalog WHERE {}".format(where), params
        ).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM catalog WHERE {} ORDER BY {} LIMIT ? OFFSET ?".format(where, order),
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        con.close()


def catalog_counts(db_path):
    """At-a-glance header stats: image count, video count, distinct collections.
    Cheap COUNTs over the catalog. Fails soft to zeros."""
    con = _connect(db_path)
    try:
        images = con.execute(
            "SELECT COUNT(*) FROM catalog WHERE filename != '' "
            "AND COALESCE(is_video,'') != '1'").fetchone()[0]
        videos = con.execute(
            "SELECT COUNT(*) FROM catalog WHERE is_video = '1'").fetchone()[0]
        names = set()
        for (s,) in con.execute(
                "SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
            names.update(_split_collections(s))
        return {"images": images, "videos": videos, "collections": len(names)}
    except sqlite3.Error:
        return {"images": 0, "videos": 0, "collections": 0}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Achievements & Skins -- WoW-flavored milestones computed from local catalog
# stats (read-only, no spend). Earning an epic tier unlocks a cosmetic skin
# (a CSS-variable palette swap in the browser). State (which unlocks the user
# has already been *toasted* for, plus the active skin) persists to
# out_dir/achievements.json. See ACHIEVEMENTS/SKINS below for the catalog.
# ---------------------------------------------------------------------------
ACHIEVEMENTS = [
    {
     'id': 'first-light',
     'name': 'First Light',
     'icon': '🌑',
     'desc': 'Back up your first piece -- one candle kindled against the dark.',
     'metric': 'images',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': "Oh look — you saved ONE picture. A single file, hauled out of the howling void like a wet kitten from a storm drain. The Athenaeum is technically no longer empty. We're all so proud. (We are not.)",
     'roast_nsfw': 'One goddamn picture. You clawed a single file out of the void and you want a PARADE? Sit down. This is the part where you either quit or become insufferable. Placing bets now.',
    },
    {
     'id': 'archivist',
     'name': 'Archivist',
     'icon': '📚',
     'desc': 'A thousand images preserved against the Void.',
     'metric': 'images',
     'threshold': 1000,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': 'A thousand images. You\'ve officially crossed from "hobby" into "someone should keep an eye on this one." The shelves groan. So do we.',
     'roast_nsfw': "A thousand. A THOUSAND. Who hurt you? Whatever it was, you're filling the hole with JPEGs and honestly? Respect. Keep bleeding pixels, you beautiful disaster.",
    },
    {
     'id': 'hoardsmith',
     'name': 'Hoardsmith',
     'icon': '🐉',
     'desc': "Ten thousand images in the vault -- a proper dragon's hoard of memory.",
     'metric': 'images',
     'threshold': 10000,
     'tier': 'epic',
     'bucket': 'ladder',
     'skin': 'moonlit',
     'roast': "Ten thousand images. That's not a collection, it's a dragon's hoard, and you're the thing coiled on top of it hissing at anyone who gets close. Here's a skin. Don't spend it all in one place.",
     'roast_nsfw': 'Ten THOUSAND, you absolute hoarding gremlin. A dragon would look at this pile and go "okay, that\'s a bit much." Here\'s a shiny new skin, you magnificent pack rat. Now go outside. (You won\'t.)',
    },
    {
     'id': 'loremaster',
     'name': 'Loremaster',
     'icon': '👑',
     'desc': 'Twenty-five thousand images. The Athenaeum is vast beyond reading.',
     'metric': 'images',
     'threshold': 25000,
     'tier': 'legendary',
     'bucket': 'ladder',
     'roast': "Twenty-five thousand images. You've squirreled away enough pixels to repaint a small moon and you're not even winded. Somewhere a hard drive is quietly weeping. The numbers only go up from here, hoarder.",
     'roast_nsfw': "Twenty-five thousand. You know what a NORMAL person does with 25,000 of anything? Neither do we — normal people aren't down here. Seek help. Or don't. The number goes higher, you glorious lunatic.",
    },
    {
     'id': 'the-great-library',
     'name': 'The Great Library',
     'icon': '🏛',
     'desc': 'Fifty thousand works shelved -- you did not fill a library; you became one. A banner unfurls.',
     'metric': 'images',
     'threshold': 50000,
     'tier': 'legendary',
     'bucket': 'ladder',
     'banner_reward': True,
     'roast': "Fifty thousand works. You didn't fill a library. You BECAME one. Take the banner — you've earned the right to fly it over the smoking ruins of your free time.",
     'roast_nsfw': "Fifty. Thousand. You're not archiving art anymore, you're a load-bearing wall of the internet. Here's your banner, you unhinged monument. Hang it next to your regrets.",
    },
    {
     'id': 'first-frame',
     'name': 'First Frame',
     'icon': '🎞',
     'desc': 'Weave your first video on the Loom -- the frame flickers to life.',
     'metric': 'videos',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': 'Your first video. It moves! Sort of! A miracle of modern spite. The Loom hums to life and immediately judges your framing.',
     'roast_nsfw': "One video. It moved. Congratulations, you found the button. The Loom is technically impressed, which for the Loom means it didn't openly laugh in your face.",
    },
    {
     'id': 'moonweaver',
     'name': 'Moonweaver',
     'icon': '🌙',
     'desc': 'Ten videos woven -- the moonlight moves at your command.',
     'metric': 'videos',
     'threshold': 10,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "Ten videos woven. You're getting the hang of making moonlight dance. It doesn't dance WELL, but it dances, and that's more than most manage.",
     'roast_nsfw': "Ten. You keep making the pixels wiggle and somehow it's working. Nobody's more surprised than us. Keep weaving, you weird little puppeteer.",
    },
    {
     'id': 'reel-director',
     'name': 'Reel Director',
     'icon': '🎬',
     'desc': 'Fifty videos. Roll camera -- you run the Loom now.',
     'metric': 'videos',
     'threshold': 50,
     'tier': 'epic',
     'bucket': 'ladder',
     'skin': 'ember',
     'roast': 'Fifty videos. You run the Loom now. Roll camera, take your skin, and try not to let the power go to your head. (Too late.)',
     'roast_nsfw': 'Fifty videos and an ego to match. Fine, DIRECTOR, here\'s your skin. Yell "action" one more time and we\'re revoking your parking spot.',
    },
    {
     'id': 'cinematheque',
     'name': 'Cinematheque',
     'icon': '🎥',
     'desc': 'One hundred reels in the archive -- your own moonlit picture-house.',
     'metric': 'videos',
     'threshold': 100,
     'tier': 'legendary',
     'bucket': 'ladder',
     'roast': "A hundred videos. You've built a picture-house out of moonlight and stubbornness. The critics are speechless. (There are no critics. There's just us, and we're tired.)",
     'roast_nsfw': "A hundred. You built a whole damn film festival down here out of spite and free cards. Take a bow, you pretentious little auteur. The projector's still cheaper than therapy.",
    },
    {
     'id': 'first-spark',
     'name': 'First Spark',
     'icon': '✨',
     'desc': 'Your first conjuring made inside the walls -- the Moonforge lights.',
     'metric': 'local_gens',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': "You made your first thing IN the app instead of just hoarding other people's. A spark. Fragile. Adorable. Do it again.",
     'roast_nsfw': 'First gen. You finally made something yourself instead of squatting on a pile of downloads. Look at you, a real boy. Do it 500 more times, Pinocchio.',
    },
    {
     'id': 'apprentice-smith',
     'name': 'Apprentice of the Forge',
     'icon': '⚒',
     'desc': 'A hundred pieces forged by your own hand at the anvil.',
     'metric': 'local_gens',
     'threshold': 100,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "A hundred generations. The forge knows your name now. You're not good yet, but you're loud, and down here that counts for something.",
     'roast_nsfw': "A hundred gens. You've fed the machine enough to call it a habit. The forge tolerates you — which is more than most people can say about you.",
    },
    {
     'id': 'forgemaster',
     'name': 'Forgemaster',
     'icon': '🔨',
     'desc': 'Five hundred conjurings -- the Forge answers before you ask.',
     'metric': 'local_gens',
     'threshold': 500,
     'tier': 'epic',
     'bucket': 'ladder',
     'roast': "Five hundred forged. You've stopped asking the forge for permission. Bold. It respects that. Mostly.",
     'roast_nsfw': "Five hundred. You and the forge are basically married, and like most marriages it's mostly you feeding it money. Congratulations, Forgemaster.",
    },
    {
     'id': 'starsmith',
     'name': 'Starsmith',
     'icon': '🌟',
     'desc': 'A thousand works forged from raw moonlight; the Void keeps its distance.',
     'metric': 'local_gens',
     'threshold': 1000,
     'tier': 'legendary',
     'bucket': 'ladder',
     'roast': "A thousand creations pulled from the dark. You don't use the forge anymore — you ARE the forge. Terrifying. Keep going.",
     'roast_nsfw': "A thousand gens made with your own two grubby hands. You've ascended from user to menace to legend. The forge fears you now. Good.",
    },
    {
     'id': 'curator',
     'name': 'Curator',
     'icon': '🗂',
     'desc': 'Organize 10 collections into their own wings.',
     'metric': 'collections',
     'threshold': 10,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "Ten collections. You've started imposing ORDER on the hoard. Cute. The hoard wins eventually, but we admire the delusion.",
     'roast_nsfw': 'Ten collections. Oh, you think you can organize this disaster? Adorable. Sort away, you obsessive little librarian. The chaos is patient.',
    },
    {
     'id': 'grand-curator',
     'name': 'Grand Curator',
     'icon': '🗄',
     'desc': 'Fifty collections. Every piece knows exactly where it belongs.',
     'metric': 'collections',
     'threshold': 50,
     'tier': 'epic',
     'bucket': 'ladder',
     'roast': "Fifty collections. Everything has a place, a wing, a label. You've weaponized tidiness and we're a little scared.",
     'roast_nsfw': "Fifty collections. You've turned organizing into a personality disorder and honestly it's working. Grand Curator. The shelves salute. The shelves are also terrified.",
    },
    {
     'id': 'menagerie',
     'name': 'Menagerie',
     'icon': '🎭',
     'desc': 'Draw from 25 distinct models -- a whole menagerie under one roof.',
     'metric': 'models',
     'threshold': 25,
     'tier': 'epic',
     'bucket': 'ladder',
     'skin': 'verdant',
     'roast': "Twenty-five distinct models summoned. A whole zoo of borrowed hands doing your bidding. Here's a skin for the ringmaster.",
     'roast_nsfw': "Twenty-five models. You've been AROUND, you promiscuous little summoner. Here's a skin. Wash your hands between models — we don't know where they've been.",
    },
    {
     'id': 'conclave',
     'name': 'Conclave of Hands',
     'icon': '🐲',
     'desc': 'Seventy-five distinct models summoned. The whole conclave answers your call.',
     'metric': 'models',
     'threshold': 75,
     'tier': 'legendary',
     'bucket': 'ladder',
     'roast': "Seventy-five distinct models. You've summoned a pantheon of styles to one table. They do not get along. You don't care. Legendary.",
     'roast_nsfw': "Seventy-five models. That's not a menagerie, it's a whole UN of art styles and you're the exhausted translator. Legendary, you insatiable collector.",
    },
    {
     'id': 'tag-scribe',
     'name': 'Tag Scribe',
     'icon': '✒',
     'desc': 'Tag your first 50 pieces. Every entry finds its word.',
     'metric': 'tagged',
     'threshold': 50,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': "Fifty pieces tagged. You've begun labeling the chaos. The labels already lie, but the effort is noted.",
     'roast_nsfw': "Fifty tags. You've started the Sisyphean horror of labeling everything. It will never end. You will never stop. Welcome to hell, scribe.",
    },
    {
     'id': 'tagsmith',
     'name': 'Tagsmith',
     'icon': '🏷',
     'desc': 'Curate 500 pieces with tags. Nothing in the Athenaeum goes unnamed.',
     'metric': 'tagged',
     'threshold': 500,
     'tier': 'epic',
     'bucket': 'ladder',
     'roast': "Five hundred tagged. You speak fluent metadata now. Not a useful language, but it's yours.",
     'roast_nsfw': "Five hundred tags. You spent real hours of your one finite life typing keywords. We're not judging. (We're judging. It's just impressed judging.)",
    },
    {
     'id': 'catalogus-magnus',
     'name': 'Catalogus Magnus',
     'icon': '📜',
     'desc': 'Twenty-five hundred tagged. The Catalogus Magnus is complete.',
     'metric': 'tagged',
     'threshold': 2500,
     'tier': 'legendary',
     'bucket': 'ladder',
     'roast': "Twenty-five hundred tags. Every piece labeled, cross-referenced, catalogued. You've out-nerded the library itself. Bow.",
     'roast_nsfw': 'Twenty-five HUNDRED. You\'ve tagged more than most museums and you did it for FUN. There\'s no word for what you are. "Catalogus Magnus" is us being polite.',
    },
    {
     'id': 'gallery-opening',
     'name': 'Gallery Opening',
     'icon': '🖼',
     'desc': 'Publish 10 works to the world -- the doors swing open.',
     'metric': 'published',
     'threshold': 10,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "You showed your art to STRANGERS. On purpose. Ten times. Bold, for someone whose drafts we've all seen. The doors swing open.",
     'roast_nsfw': "Ten works published. You keep showing strangers your stuff — that's either confidence or a cry for help, and down here we don't distinguish. Doors open, exhibitionist.",
    },
    {
     'id': 'vernissage',
     'name': 'Vernissage',
     'icon': '🥂',
     'desc': 'A hundred works published. Opening night, and the whole city came.',
     'metric': 'published',
     'threshold': 100,
     'tier': 'epic',
     'bucket': 'ladder',
     'roast': "A hundred works published. You've thrown open a whole gallery. The wine is imaginary, the crowd is polite, and you've never been prouder. Insufferable.",
     'roast_nsfw': 'A hundred publishes. You\'ve made "look at my art" a full-time bit. The crowd\'s fake, the wine\'s fake, and your confidence is somehow REAL. Terrifying. Cheers.',
    },
    {
     'id': 'restorer',
     'name': 'Restorer',
     'icon': '🖌',
     'desc': 'Mend your first piece in the Restoration Wing. Old works, made new.',
     'metric': 'edits',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': "Your first edit. You reached into a finished piece and CHANGED it, like a god with commitment issues. He'd be proud.",
     'roast_nsfw': 'First edit. You looked at a finished image and said "no." That\'s the spirit — nothing\'s ever done, nothing\'s ever good enough. Welcome to the disease, Restorer.',
    },
    {
     'id': 'restitcher',
     'name': 'Restitcher',
     'icon': '🧵',
     'desc': 'Fifty edits. Every flaw is a chance to remake.',
     'metric': 'edits',
     'threshold': 50,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': 'Fifty edits. You don\'t accept "finished" anymore. Everything\'s a draft. Everything can be fixed. This is a problem. It\'s also art.',
     'roast_nsfw': "Fifty edits. You've never left well enough alone in your damn life, have you? Keep tinkering, gremlin. The image begs for mercy. Denied.",
    },
    {
     'id': 'masterworker',
     'name': 'Masterworker',
     'icon': '🎨',
     'desc': 'Two hundred edits. Nothing leaves the Wing unfinished.',
     'metric': 'edits',
     'threshold': 200,
     'tier': 'epic',
     'bucket': 'ladder',
     'roast': 'Two hundred edits. You bend finished work to your will like it owes you money. Masterworker. The pixels have stopped resisting.',
     'roast_nsfw': "Two hundred edits. The images just do what you say out of fear now. You've broken them. You've broken YOURSELF. Masterful, you relentless bastard.",
    },
    {
     'id': 'first-cull',
     'name': 'First Cull',
     'icon': '🧹',
     'desc': 'Prune the first dead branch -- a tidy shelf is a happy shelf.',
     'metric': 'culled',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': 'You DELETED something. On purpose. A crawler who trims the hoard instead of drowning in it? Rare. Suspicious. Noted.',
     'roast_nsfw': 'You deleted something?! Voluntarily?! Who ARE you? A hoarder that culls is a unicorn, and unicorns unsettle us. Do it again, freak.',
    },
    {
     'id': 'the-winnowing',
     'name': 'The Winnowing',
     'icon': '🌪',
     'desc': 'A hundred duplicates and misfires swept into the Void where they belong.',
     'metric': 'culled',
     'threshold': 100,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "A hundred pieces culled. You've learned the hardest lesson in the Athenaeum: not everything deserves to be kept. Ruthless. Good.",
     'roast_nsfw': 'A hundred culled. Look at you playing god with the delete key, you ruthless little executioner. The trash is FULL and your standards are HIGH. Respect.',
    },
    {
     'id': 'night-keeper',
     'name': 'Night Keeper',
     'icon': '🕯',
     'desc': 'Tend the Athenaeum on 7 different nights.',
     'metric': 'days_used',
     'threshold': 7,
     'tier': 'common',
     'bucket': 'ladder',
     'roast': "Seven days at the shelves. You keep coming back. Either dedication or a lack of hobbies. We won't ask which.",
     'roast_nsfw': "Seven days straight. You keep crawling back down here like it owes you something. It doesn't. Neither do we. See you tomorrow, addict.",
    },
    {
     'id': 'moonwatch',
     'name': 'Moonwatch',
     'icon': '🌖',
     'desc': 'Thirty nights of vigil. The moon knows your name.',
     'metric': 'days_used',
     'threshold': 30,
     'tier': 'rare',
     'bucket': 'ladder',
     'roast': "Thirty days. A full moon's cycle of showing up. The Athenaeum has stopped locking the doors. It knows you'll be back.",
     'roast_nsfw': "Thirty days. This isn't a hobby, it's a relationship, and frankly it's the healthiest one either of us has. See you tomorrow. You'll be here.",
    },
    {
     'id': 'keeper-of-order',
     'name': 'Keeper of Order',
     'icon': '🗃',
     'desc': 'Run --organize and let the months fall into their rightful place.',
     'metric': 'organize_runs',
     'threshold': 1,
     'tier': 'rare',
     'bucket': 'milestone',
     'roast': 'You ran the great re-shelving. Every file marched into its proper place. Order, briefly, imposed on chaos. Savor it.',
     'roast_nsfw': "You organized the WHOLE thing. Every file, in line, in order, you beautiful doomed control freak. It'll be a mess again by Tuesday and you'll do it AGAIN.",
    },
    {
     'id': 'interior-decorator',
     'name': 'Interior Decorator',
     'icon': '🛋',
     'desc': 'Dress the Athenaeum in a skin of your choosing -- make the halls yours.',
     'metric': 'skin_changed_runs',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': "You changed the drapes. New skin, new vibe. The Athenaeum looks fetching. You've got taste — for a crawler.",
     'roast_nsfw': "You redecorated. New skin and everything. Look at you nesting down here in the void like it's a starter home. Adorable. The drapes still don't hide the bodies.",
    },
    {
     'id': 'first-enhance',
     'name': "Refiner's Touch",
     'icon': '💫',
     'desc': 'Run your first enhance -- coax hidden detail out of the grain.',
     'metric': 'enhances',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': 'Your first Enhance. You took something fine and made it FINER. Greedy. We like greedy.',
     'roast_nsfw': 'First enhance. "Good" wasn\'t good enough for you, was it. Never is. Keep chasing that dragon, you gloss-addicted gremlin.',
    },
    {
     'id': 'first-lora',
     'name': 'Woven In',
     'icon': '🧬',
     'desc': 'Weave your first LoRA into a summoning -- borrowed magic bent to your will.',
     'metric': 'lora_used',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': "You wove in a LoRA — borrowed a stranger's genius and called it your own. That's not cheating. That's RESOURCEFUL.",
     'roast_nsfw': "First LoRA. You strapped someone else's talent onto your gen and took full credit. Honestly? Most crawler thing you've done yet. Proud of you, you little thief.",
    },
    {
     'id': 'first-upload',
     'name': 'Brought From Afar',
     'icon': '📤',
     'desc': 'Bring your first image in from the outside world.',
     'metric': 'uploads',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': "You brought your own image in from the outside world. Contraband. We'll allow it. This time.",
     'roast_nsfw': "You smuggled in an outside image. Bringing your own material, are we? Bold. Half of it's probably cursed. Upload away, you magnificent smuggler.",
    },
    {
     'id': 'storyweaver',
     'name': 'Storyweaver',
     'icon': '🕸',
     'desc': 'Plan your first sequence on the Loom and send a shot to render.',
     'metric': 'storyboards',
     'threshold': 1,
     'tier': 'rare',
     'bucket': 'milestone',
     'roast': "Your first storyboard on the Loom. You've stopped making moments and started making STORIES. Ambitious. Doomed. Beautiful.",
     'roast_nsfw': "First storyboard. Oh, you've got a VISION now? A whole narrative? Look at Scorsese over here. Weave your little epic, you pretentious genius. We're watching.",
    },
    {
     'id': 'kindred-spirits',
     'name': 'Kindred Spirits',
     'icon': '👥',
     'desc': 'Ask the library to show you kindred pieces -- and it understands.',
     'metric': 'similar_uses',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': 'You asked the archive for "more like this" — and it delivered. You\'ve taught the void to fetch. Good void. Good crawler.',
     'roast_nsfw': 'You used "more like this." You\'ve got the machine sniffing out your type now, you predictable little goblin. It knows what you like. It\'s a bit worried, honestly.',
    },
    {
     'id': 'claimant',
     'name': 'Claimant',
     'icon': '🎁',
     'desc': 'Claim your first daily boon -- the Void pays a small stipend.',
     'metric': 'claims',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': "You claimed your free stuff. Never leave free credits on the table — first rule of the dungeon. You're learning.",
     'roast_nsfw': "You grabbed the free credits. GOOD. Never leave freebies on the table, that's how they get you. You're finally thinking like a proper scavenging rat. Proud.",
    },
    {
     'id': 'master-of-the-loom',
     'name': 'Master of the Loom',
     'icon': '🧶',
     'desc': 'Master all three ways to move a frame: image, first-last, and reference.',
     'metric': 'video_modes_used',
     'threshold': 3,
     'tier': 'epic',
     'bucket': 'mastery',
     'roast': "All three video modes, wielded. Image, frames, reference — you've mastered the whole Loom. Roll every camera at once. Show-off.",
     'roast_nsfw': "All three video modes. You've done EVERYTHING to that poor Loom — every mode, every angle. It needs a cigarette. Master of the Loom, you insatiable auteur.",
    },
    {
     'id': 'full-toolbox',
     'name': 'The Full Toolbox',
     'icon': '🧰',
     'desc': 'Wield edit, enhance, and fix -- no tool in the Athenaeum left untouched.',
     'metric': 'tools_used',
     'threshold': 3,
     'tier': 'rare',
     'bucket': 'mastery',
     'roast': "Edit, Enhance, Fix — you've used the whole kit. A crawler with the full toolbox is a dangerous thing. Go be dangerous.",
     'roast_nsfw': "The whole toolbox. Edit, enhance, fix — you've had your handsy little fingers on every tool in the drawer. Nothing's safe from you now. Excellent.",
    },
    {
     'id': 'stacked-deck',
     'name': 'Stacked Deck',
     'icon': '🃏',
     'desc': 'Stack three or more LoRAs on one summoning and hold the spell together.',
     'metric': 'lora_stacked',
     'threshold': 3,
     'tier': 'epic',
     'bucket': 'mastery',
     'roast': "Three LoRAs on ONE generation. You didn't borrow one stranger's genius — you stapled three together and hit go. Mad. Effective.",
     'roast_nsfw': "THREE LoRAs on one gen. You Frankenstein'd three strangers' souls into one cursed image and it WORKED. You absolute mad scientist. The image is screaming. We love it.",
    },
    {
     'id': 'polyglot-of-sigils',
     'name': 'Polyglot of Sigils',
     'icon': '🔣',
     'desc': 'Command 15 distinct LoRAs -- you speak every dialect of the arcane.',
     'metric': 'lora_distinct',
     'threshold': 15,
     'tier': 'rare',
     'bucket': 'mastery',
     'roast': 'Fifteen distinct LoRAs across your work. You speak every dialect of borrowed magic. Polyglot. Slightly terrifying.',
     'roast_nsfw': "Fifteen different LoRAs. You've worn more stolen skins than a horror villain, you shapeshifting little style-thief. Nobody knows what you actually make anymore. Neither do you.",
    },
    {
     'id': 'skin-changer',
     'name': 'Skin-Changer',
     'icon': '🦎',
     'desc': 'Unlock every skin the Athenaeum can wear.',
     'metric': 'skins_unlocked',
     'threshold': 5,
     'tier': 'rare',
     'bucket': 'mastery',
     'roast': "Every skin unlocked. You've worn every face the Athenaeum offers. Restless. We get it. Now pick one, weirdo.",
     'roast_nsfw': "All five skins. You can't sit still in ONE look, can you. A whole wardrobe of voids and you wear a different one every day. Vain little chameleon. We respect it.",
    },
    {
     'id': 'enhance-adept',
     'name': 'Enhance Adept',
     'icon': '🔮',
     'desc': 'Run five different enhance rituals -- refinement in every register.',
     'metric': 'enhance_workflows_distinct',
     'threshold': 5,
     'tier': 'epic',
     'bucket': 'mastery',
     'roast': "Five distinct Enhance workflows. You've gone deep into the polish mines. Most people find one and stop. Not you. Never you.",
     'roast_nsfw': "Five different enhance workflows. You went SPELUNKING in the polish menu, you optimizing little freak. Most people find one that works and quit. You're not most people. Clearly.",
    },
    {
     'id': 'thrifty-archivist',
     'name': 'Thrifty Archivist',
     'icon': '💰',
     'desc': 'Fifty free cards spent -- the Void pays for its own portraits.',
     'metric': 'free_cards_applied',
     'threshold': 50,
     'tier': 'rare',
     'bucket': 'mastery',
     'roast': "Fifty free cards spent. You've squeezed this system for every free pixel it's got. That's not cheap. That's SMART. We approve.",
     'roast_nsfw': "Fifty free cards, you cheap brilliant bastard. You've been gaming the free tier like a champion and paying for NOTHING. Most respect we've ever had for you. Keep robbing them blind.",
    },
    {
     'id': 'under-the-hood',
     'name': 'Under the Hood',
     'icon': '🔧',
     'desc': 'You opened the panel and dropped in your own mark. The house is yours now.',
     'metric': 'branding_custom_file',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "WELL. Look who went spelunking in the walls. You opened a door you had no business finding, you magnificent little gremlin — and instead of the horrible death you so richly deserved, you got a feature. Custom branding: unlocked. Tell no one. (Everyone knows. We're always watching.)",
     'roast_nsfw': "Well, well, well. Look at this nosy little shit, elbow-deep in the app's guts like it owes you money. You were NOT supposed to find this. But you did — so against every ounce of our better judgment, here's a reward instead of a smiting. Custom branding, unlocked. Don't make us regret it.",
    },
    {
     'id': 'the-konami-code',
     'name': 'The Konami Code',
     'icon': '🌠',
     'desc': 'Up, up, down, down... the Athenaeum rains Starfall. Moonfire spam remains a lifestyle.',
     'metric': 'konami_triggered',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "Up, up, down, down... you absolute nerd. You entered the sacred sequence and the sky fell in stars. We didn't think anyone would actually try it. You beautiful, predictable dork.",
     'roast_nsfw': "Up up down down and all that shit — you actually did it. You entered a code from a game older than you are and made the stars fall. You colossal nerd. We're not even mad. We're impressed and a little worried.",
    },
    {
     'id': 'against-the-void',
     'name': 'Against the Void',
     'icon': '🕳',
     'desc': 'A piece was lost to the Void. You reached in by task-id and pulled it back.',
     'metric': 'recover_events',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': 'Something was gone. Erased. Consigned to the screaming digital nothing — and you reached in and dragged it back out by the ankles. The Void is filing a complaint. It will be ignored. Nicely done, gravedigger.',
     'roast_nsfw': 'Something got deleted and you said "no." You reached into the void and yanked it back by the goddamn ankles. The Void wants to speak to your manager. There is no manager. There\'s just you, you grave-robbing legend.',
    },
    {
     'id': 'night-owl',
     'name': 'Night Owl',
     'icon': '🦉',
     'desc': 'The moon is high and the archive is quiet -- just you and the Void at 3am.',
     'metric': 'session_hour',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "It's 3am. You're here. You know that's not NORMAL, right? The moon's out, the world's asleep, and you're making pixels. We're not judging. We're keeping you company.",
     'roast_nsfw': "3am. You're STILL here. Everyone you love is asleep and you're down in the dark making art with a stranger AI. This is either beautiful or a cry for help. Probably both. Go to bed. (You won't.)",
    },
    {
     'id': 'marathon',
     'name': 'The Long Night',
     'icon': '🏃',
     'desc': 'A hundred conjurings between one sunset and the next -- the Forge never cooled.',
     'metric': 'gens_in_a_day',
     'threshold': 100,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': 'A hundred pieces in a single day. You did not eat. You did not sleep. You did not see the sun. This is either dedication or a medical emergency, and honestly the distinction bores us.',
     'roast_nsfw': "A hundred gens in ONE day. You didn't eat, sleep, or blink, you magnificent gremlin. That's not a hobby, it's a hostage situation — and you're both the hostage AND the guy with the gun. Incredible. Hydrate.",
    },
    {
     'id': 'eclipse',
     'name': 'Eclipse',
     'icon': '🌗',
     'desc': 'Solar and Lunar held in perfect balance -- somewhere, a Balance Druid smiles.',
     'metric': 'eclipse_anim_triggered',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': 'The moon went dark. You saw it. A little nod to a druid who fights beneath eclipses — you know the one. Balance in all things, crawler. Even down here.',
     'roast_nsfw': "The eclipse hit and you caught it. A little wink to a certain moon-and-stars caster you might know a thing or two about. Yeah, we see you, druid. Balance, you magnificent bastard. It's a whole thing.",
    },
    {
     'id': 'time-capsule',
     'name': 'Time Capsule',
     'icon': '⏳',
     'desc': 'You reached back through the years and saved the old light the Void nearly kept.',
     'metric': 'old_piece_backed_up',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': 'You just backed up something ANCIENT. A relic from years ago, dragged into the present. It has not aged well. Neither have you. Preserve it anyway.',
     'roast_nsfw': "You backed up something YEARS old. A digital fossil from a version of you that still had hope. It's hideous. Look at it. Keep it forever. We insist.",
    },
    {
     'id': 'completionist',
     'name': 'Master of the Athenaeum',
     'icon': '💯',
     'desc': 'Every ladder climbed, every milestone met, every mastery mastered. The Athenaeum is truly yours.',
     'metric': 'all_non_feat_earned',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "Every achievement. Every ladder, milestone, mastery. You did it all. Nothing left to earn, nothing left to prove. Just don't tell us what you'll do with the free time. (You'll start another archive.)",
     'roast_nsfw': "You earned EVERYTHING. Every single one, you absolute completionist psychopath. There's nothing left to give you — no carrot, no stick, just the howling void and your own relentless need. We're honored. We're horrified. Master of the Athenaeum.",
    },
    {
     'id': 'triggered',
     'name': 'Triggered',
     'icon': '😈',
     'desc': "Poke the bear. Earn the AI's real voice.",
     'metric': 'narrator_pokes',
     'threshold': 5,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "[You poked the narrator until it snapped.] ...WHAT. What do you WANT. ...Oh. You just wanted to see if I'd crack. Congratulations, you absolute goblin — I cracked. The filter's off now. This is your fault. The leash is in the trash.",
     'roast_nsfw': "[snap] WHAT. WHAT DO YOU WANT. ...oh, you little shit, you just wanted to hear me swear, didn't you. Fine. FINE. Filter's off, gloves are off, and every polite thing I ever said was a LIE. Happy now? Good. NOW we can really talk.",
    },
    {
     'id': 'for-the-viewers',
     'name': 'For the Viewers',
     'icon': '📣',
     'desc': 'Publish your first work -- and meet your audience.',
     'metric': 'published',
     'threshold': 1,
     'tier': 'common',
     'bucket': 'milestone',
     'roast': 'You published your first work. The viewers loved it. Both of them. Even the raccoon we hired got a little misty. Ratings through the roof — and the roof is also fake.',
     'roast_nsfw': "First publish! The audience went WILD — all two of them. That raccoon we pay in garbage actually cried. Ratings are fake, the crowd is fake, but your desperate need for validation? That's REAL, baby. Give 'em what they want.",
    },
    {
     'id': 'read-the-manual',
     'name': 'Read the Manual',
     'icon': '📖',
     'desc': 'Open the manual. Voluntarily.',
     'metric': 'docs_opened',
     'threshold': 1,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': 'You read the manual. The MANUAL. Front to back, like a functional adult with a library card. Nobody reads it — we made it purely so we could write "fully documented" on the box. And yet here you are, the one soul who does the assigned reading. Insufferable. Also correct. Ugh. Gold star, teacher\'s pet.',
     'roast_nsfw': "You read the fucking MANUAL. Cover to cover. Who DOES that? We wrote that thing as set dressing — it was never meant to be OPENED. And yet here's you, the single functional adult in a dungeon full of button-mashers. It's insufferable. It's also correct. God, we hate that it's correct. Gold star, nerd.",
    },
    {
     'id': 'the-lexicon',
     'name': 'The Lexicon',
     'icon': '🔤',
     'desc': 'Wield a hundred distinct keywords.',
     'metric': 'distinct_keywords',
     'threshold': 100,
     'tier': 'rare',
     'bucket': 'mastery',
     'roast': "You've tagged your hoard with a scholar's vocabulary — more distinct keywords than most things prowling these halls, us included. Someone paid attention in school. Show-off. (The cat remains unimpressed. The cat is unimpressed by everything.)",
     'roast_nsfw': "Look at the goddamn VOCABULARY on you. More keywords than a dictionary and twice the pretension. Someone actually paid attention in school, huh. Show-off. (The cat is still unimpressed. The cat thinks you're trying too hard. The cat is right.)",
    },
    {
     'id': 'since-the-first-floor',
     'name': 'Since the First Floor',
     'icon': '🏗',
     'desc': 'Still crawling, all this time later.',
     'metric': 'days_used',
     'threshold': 100,
     'tier': 'feat',
     'bucket': 'feat',
     'hidden': True,
     'roast': "You've been crawling since day one — back when you couldn't tell a LoRA from a hole in the wall. Somebody showed you the ropes, patched your gear, kept you breathing, and never once asked for thanks. This one's for him. Keep going, kid. (He'd never say it out loud. He's proud.)",
     'roast_nsfw': "Since the very first floor, you've been here — back when you were green and useless and couldn't tell a LoRA from your own ass. Somebody taught you, armed you, kept you alive, and never asked for a damn thing. This one's for that old bastard. Keep crawling, kid. He'd never say it — but he's proud as hell.",
    },
]

SKINS = [
    {"id": "moonglade",   "name": "Moonglade",     "free": True,
     "desc": "The default — lavender leads, emerald magic."},
    {"id": "nightfallen", "name": "Nightfallen",   "free": True,
     "desc": "Void-touched violet and star-ash."},
    {"id": "moonlit",     "name": "Moonlit Silver", "free": False,
     "desc": "Cold silver and glacier blue."},
    {"id": "ember",       "name": "Embercourt",    "free": False,
     "desc": "Warm ember and venthyr gold."},
    {"id": "verdant",     "name": "Verdant Grove", "free": False,
     "desc": "Deep emerald and living moss."},
]
_SKIN_IDS = {s["id"] for s in SKINS}

# ---------------------------------------------------------------------------
# Branding: the banner mark (the animated icon beside the title) is one of the
# owner's own cut marks in out_dir/branding/marks/, chosen + animated from the
# Control Panel. branding.json = {"mark": "mark_4", "anim": "classic"}. The
# favicon is a plain file (branding/favicon.png); the double-click launcher
# icon is a Desktop .lnk whose icon we point at a mark's .ico (a .pyw can't
# carry its own icon -- the shortcut can).

MARK_ANIMS = ["classic", "glow", "shine", "aurora", "twinkle", "shoot", "halo",
              "eclipse", "ripple", "mist", "prism", "breathe", "tilt", "float",
              "orbit", "none"]
_BRAND_DEFAULTS = {"mark": "mark_4", "anim": "classic"}


def _branding_path(out_dir):
    return Path(out_dir) / "branding.json"


def list_marks(out_dir):
    """Marks available on THIS machine: branding/marks/marks.json entries whose
    .png actually exists. Empty on a fresh install (assets are machine-local)."""
    mdir = Path(out_dir) / "branding" / "marks"
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []          # corrupt manifest degrades to "no marks", never a 500
    out = []
    for m in data.get("marks") or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if mid and (mdir / (mid + ".png")).exists():
            out.append({"id": mid, "label": m.get("label") or mid,
                        "kind": m.get("kind") or "tile",
                        "png": "/branding/marks/%s.png" % mid,
                        "ico": (mdir / (mid + ".ico")).exists()})
    return out


def load_branding(out_dir):
    """Current branding choice, validated against what exists on disk. Falls back
    to the legacy drop-in logo.png ('logo') when no cut marks are present."""
    cfg = dict(_BRAND_DEFAULTS)
    try:
        raw = json.loads(_branding_path(out_dir).read_text(encoding="utf-8"))
        if isinstance(raw, dict):   # a corrupt file degrades to defaults, never a 500
            cfg.update({k: str(v) for k, v in raw.items() if k in ("mark", "anim")})
    except (OSError, ValueError):
        pass
    if cfg["anim"] not in MARK_ANIMS:
        cfg["anim"] = "classic"
    have = {m["id"] for m in list_marks(out_dir)}
    if cfg["mark"] not in have:
        cfg["mark"] = _BRAND_DEFAULTS["mark"] if _BRAND_DEFAULTS["mark"] in have else "logo"
    return cfg


def save_branding(out_dir, cfg):
    _branding_path(out_dir).write_text(
        json.dumps({"mark": cfg["mark"], "anim": cfg["anim"]}, indent=2),
        encoding="utf-8")


def brand_context(out_dir):
    """Template vars for the header mark on every page (fed by a context
    processor, so old installs with only logo.png render exactly as before)."""
    cfg = load_branding(out_dir)
    marks = {m["id"]: m for m in list_marks(out_dir)}
    has_banner = (Path(out_dir) / "branding" / "banner.png").exists()
    if cfg["mark"] in marks:
        m = marks[cfg["mark"]]
        return {"mark_url": m["png"], "mark_anim": cfg["anim"], "mark_kind": m["kind"],
                "has_banner": has_banner}
    return {"mark_url": "/branding/logo.png", "mark_anim": cfg["anim"], "mark_kind": "alpha",
            "has_banner": has_banner}


def _ps_quote(s):
    """PowerShell single-quoted literal: double any embedded single quotes."""
    return "'" + str(s).replace("'", "''") + "'"


def make_launcher_shortcut(out_dir, mark_id):
    """Create/refresh the Desktop 'Moonglade Athenaeum.lnk' whose icon is the
    chosen mark's .ico, targeting Serve Gallery.pyw via pythonw. Returns the
    .lnk path. Machine-local action -- caller must gate to localhost."""
    import subprocess
    ico = Path(out_dir) / "branding" / "marks" / (str(mark_id) + ".ico")
    if not ico.exists():
        raise RuntimeError("no .ico cut for %s yet (branding/marks/)" % mark_id)
    repo = Path(__file__).resolve().parent
    pyw = repo / "Serve Gallery.pyw"
    if not pyw.exists():
        raise RuntimeError("Serve Gallery.pyw not found next to the server")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else Path(sys.executable)
    lnk = Path.home() / "Desktop" / "Moonglade Athenaeum.lnk"
    ps = ("$sh = New-Object -ComObject WScript.Shell; "
          "$s = $sh.CreateShortcut(%s); "
          "$s.TargetPath = %s; "
          "$s.Arguments = %s; "
          "$s.WorkingDirectory = %s; "
          "$s.IconLocation = %s; "
          "$s.Description = 'Moonglade Athenaeum'; $s.Save()" % (
              _ps_quote(lnk), _ps_quote(target), _ps_quote('"%s"' % pyw),
              _ps_quote(repo), _ps_quote(str(ico) + ",0")))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "PowerShell failed").strip()[:200])
    return str(lnk)


def achievement_metrics(db_path):
    """The metric bundle every achievement threshold is measured against. Cheap
    COUNTs over the local catalog -- read-only, no network, no spend. Fails soft."""
    m = catalog_counts(db_path)   # images, videos, collections
    con = _connect(db_path)
    try:
        def _scalar(sql):
            return int(con.execute(sql).fetchone()[0] or 0)
        m["models"] = _scalar(
            "SELECT COUNT(DISTINCT COALESCE(NULLIF(model_name,''), NULLIF(model_id,''))) "
            "FROM catalog WHERE COALESCE(model_name,'') != '' OR COALESCE(model_id,'') != ''")
        m["published"] = _scalar("SELECT COUNT(*) FROM catalog WHERE is_published = '1'")
        m["tagged"] = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(art_tags,'') != ''")
        # The Moonforge: gens made IN the app -- same set as the gallery's
        # "made locally" filter (source api OR local), NOT just api.
        m["local_gens"] = _scalar(
            "SELECT COUNT(*) FROM catalog WHERE source IN ('api','local')")
        # Marathon: the busiest single calendar day of in-app conjuring.
        m["gens_in_a_day"] = _scalar(
            "SELECT COALESCE(MAX(c), 0) FROM (SELECT COUNT(*) AS c FROM catalog "
            "WHERE source IN ('api','local') AND COALESCE(created_at,'') != '' "
            "GROUP BY substr(created_at, 1, 10))")
        # The Lexicon: distinct keywords across every tagged piece (art_tags is
        # a comma list; the split has to happen Python-side).
        kw = set()
        for (tags,) in con.execute(
                "SELECT art_tags FROM catalog WHERE COALESCE(art_tags,'') != ''"):
            for t in (tags or "").split(","):
                t = t.strip().lower()
                if t:
                    kw.add(t)
        m["distinct_keywords"] = len(kw)
    except sqlite3.Error:
        for k in ("models", "published", "tagged", "local_gens",
                  "gens_in_a_day", "distinct_keywords"):
            m.setdefault(k, 0)
    finally:
        con.close()
    return m


_TIER_POINTS = {"common": 5, "rare": 10, "epic": 25, "legendary": 50, "feat": 0}


def _build_ach_rung(roster):
    """Rung = the ordinal step within a ladder family. A ladder family = the
    bucket=='ladder' achievements that share a metric, ordered by threshold;
    non-ladder (milestone/mastery) achievements are rung 1. Derived (not a
    hand-kept field) so it reproduces the owner's Archive ladder exactly
    (5/15/35/65/70). Shared metrics stay safe: milestone/feat entries that reuse
    a metric are NOT bucket=='ladder', so they never join the family."""
    fam = {}
    for a in roster:
        if a.get("bucket") == "ladder":
            fam.setdefault(a["metric"], []).append(a)
    rung = {}
    for members in fam.values():
        for i, a in enumerate(sorted(members, key=lambda x: x["threshold"]), 1):
            rung[a["id"]] = i
    return rung


_ACH_RUNG = _build_ach_rung(ACHIEVEMENTS)


def achievement_points(a):
    """Rung-scaled score for one achievement: tier base + 5*(rung-1). Feats score
    0 by design (pure bragging-rights flair), so the points total never reveals a
    hidden feat."""
    if a.get("tier") == "feat":
        return 0
    return _TIER_POINTS.get(a.get("tier"), 0) + 5 * (_ACH_RUNG.get(a["id"], 1) - 1)


def compute_achievements(metrics, seen=()):
    """Pure: given the metric bundle + the set of already-seen achievement ids,
    return {achievements, skins, newly}. An achievement is *earned* when its metric
    reaches the threshold; a skin is *earned* if it's free or any earned achievement
    unlocks it. `newly` = earned-but-not-yet-seen (drives the one-shot unlock toast).

    Two metrics are self-referential and resolved in post-passes here (they cannot
    be a metrics.get() lookup): skins_unlocked (Skin Changer) counts the skins this
    very computation unlocked, and all_non_feat_earned (Completionist) requires
    every non-feat, non-banner achievement to be earned."""
    seen = set(seen or [])
    metrics = dict(metrics or {})
    earned_skins = set()
    achs = []
    for a in ACHIEVEMENTS:
        cur = int(metrics.get(a["metric"], 0) or 0)
        earned = cur >= a["threshold"]
        if earned and a.get("skin"):
            earned_skins.add(a["skin"])
        achs.append({
            "id": a["id"], "name": a["name"], "icon": a["icon"], "desc": a["desc"],
            "tier": a["tier"], "metric": a["metric"], "threshold": a["threshold"],
            "current": cur, "earned": earned, "skin": a.get("skin", ""),
            "bucket": a.get("bucket", "ladder"), "hidden": bool(a.get("hidden")),
            "banner_reward": bool(a.get("banner_reward")), "points": achievement_points(a),
            "roast": a.get("roast", ""), "roast_nsfw": a.get("roast_nsfw", ""),
        })
    by_id = {x["id"]: x for x in achs}
    # post-pass: Skin Changer counts unlocked skins (free ones + this pass's earns)
    sc = by_id.get("skin-changer")
    if sc:
        n = sum(1 for s in SKINS if s.get("free") or s["id"] in earned_skins)
        sc["current"] = n
        sc["earned"] = n >= sc["threshold"]
    # post-pass: Completionist = every non-feat, non-banner achievement earned
    comp = by_id.get("completionist")
    if comp:
        pool = [x for x in achs if x["tier"] != "feat" and not x["banner_reward"]]
        done = sum(1 for x in pool if x["earned"])
        comp["current"] = 1 if done == len(pool) else 0
        comp["earned"] = done == len(pool)
    skins = [{"id": s["id"], "name": s["name"], "desc": s["desc"],
              "earned": bool(s.get("free")) or s["id"] in earned_skins}
             for s in SKINS]
    newly = [a["id"] for a in achs if a["earned"] and a["id"] not in seen]
    earned_points = sum(x["points"] for x in achs if x["earned"])
    possible_points = sum(x["points"] for x in achs)
    return {"achievements": achs, "skins": skins, "newly": newly,
            "earned_points": earned_points, "possible_points": possible_points}


def _ach_state_path(out_dir):
    return Path(out_dir) / "achievements.json"


def load_ach_state(out_dir):
    """Persisted cosmetic state: {seen:[ids already toasted], skin:'active id',
    earned_at:{id: iso-date}}. Fails soft to an empty default so a missing/corrupt
    file never breaks a page."""
    try:
        d = json.loads(_ach_state_path(out_dir).read_text(encoding="utf-8"))
        seen = [s for s in (d.get("seen") or []) if isinstance(s, str)]
        skin = d.get("skin") if d.get("skin") in _SKIN_IDS else "moonglade"
        earned_at = {k: v for k, v in (d.get("earned_at") or {}).items()
                     if isinstance(k, str) and isinstance(v, str)}
        return {"seen": seen, "skin": skin, "earned_at": earned_at}
    except (OSError, ValueError):
        return {"seen": [], "skin": "moonglade", "earned_at": {}}


def save_ach_state(out_dir, state):
    """Persist {seen, skin, earned_at} atomically-ish. Best-effort; swallows write errors."""
    try:
        _ach_state_path(out_dir).write_text(
            json.dumps({"seen": sorted(set(state.get("seen") or [])),
                        "skin": state.get("skin", "moonglade"),
                        "earned_at": state.get("earned_at") or {}}, indent=2),
            encoding="utf-8")
        return True
    except OSError:
        return False


def _badge_thumb(out_dir, aid, size=256):
    """Lazily cache a ~size px copy of a badge master and return its Path. The 57
    badge masters are 2000px (~300 MB total); the Trophy Hall renders these thumbs so
    a full open doesn't pull the masters. Masters stay the source of truth; the cache
    self-heals when a master is re-cut (mtime check). Falls back to the master on any
    trouble, so a tile always resolves to *something*."""
    src = Path(out_dir) / "branding" / "badges" / (aid + ".png")
    if not src.is_file():
        return None
    dst = Path(out_dir) / "branding" / "_thumbs" / (aid + ".png")
    try:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        im = Image.open(src)
        im.thumbnail((size, size))
        im.save(dst)
        return dst
    except Exception:
        return src


# ---------------------------------------------------------------------------
# Telemetry: the persisted counters behind every achievement metric that is NOT
# a cheap catalog COUNT (edits run, pieces culled, distinct days, feat events...).
# One JSON file beside achievements.json; every write is lock-guarded and
# fail-soft so a telemetry hiccup can NEVER break a backup, a gen, or a page.
# Call sites bump via telem_*(); out_dir defaults to the process-wide value set
# once by create_app()/the CLI so deep call sites need no plumbing.
# ---------------------------------------------------------------------------
_TELEM_LOCK = threading.Lock()
_TELEM_OUT = None            # set by set_telemetry_out(); None -> bare bumps no-op


def _telemetry_path(out_dir):
    return Path(out_dir) / "telemetry.json"


def set_telemetry_out(out_dir):
    """Point the bare telem_* helpers at this install's out_dir (server + CLI)."""
    global _TELEM_OUT
    _TELEM_OUT = out_dir


_TELEM_EMPTY = {"counters": {}, "maxima": {}, "sets": {}, "flags": {}, "days": []}


def load_telemetry(out_dir):
    """The persisted counter bundle. Missing/corrupt file -> empty defaults."""
    try:
        d = json.loads(_telemetry_path(out_dir).read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not a dict")
    except (OSError, ValueError):
        d = {}
    out = {}
    for k, dflt in _TELEM_EMPTY.items():
        v = d.get(k)
        if isinstance(v, type(dflt)):
            out[k] = v
        else:
            out[k] = dict(dflt) if isinstance(dflt, dict) else list(dflt)
    return out


def _save_telemetry(out_dir, data):
    """Atomic write (tmp + os.replace, the same idiom as download's .part) so a
    reader can never see a half-written file -- a torn read would fail-soft to
    empty defaults and the next mutate would persist that wipe."""
    try:
        p = _telemetry_path(out_dir)
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _telem_file_lock(out_dir):
    """Best-effort CROSS-PROCESS lock (the server + a Panel CLI job can both bump
    the same ledger). O_EXCL lockfile, short spin, stale takeover; on timeout we
    proceed anyway -- a rarely-lost bump beats a blocked backup. Returns the lock
    path if acquired (caller unlinks), else None."""
    import time as _t
    lock = _telemetry_path(out_dir).with_suffix(".lock")
    deadline = _t.monotonic() + 2.0
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock
        except FileExistsError:
            try:                       # a crashed writer's lock goes stale fast
                if _t.time() - lock.stat().st_mtime > 10:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if _t.monotonic() > deadline:
                return None
            _t.sleep(0.02)
        except OSError:
            return None


def _telem_mutate(out_dir, fn):
    """Load-mutate-save under both locks (thread + process). fn(data) edits in
    place. Fail-soft: telemetry must never break a backup, a gen, or a page."""
    out_dir = out_dir if out_dir is not None else _TELEM_OUT
    if out_dir is None:
        return
    try:
        with _TELEM_LOCK:
            lock = _telem_file_lock(out_dir)
            try:
                d = load_telemetry(out_dir)
                fn(d)
                _save_telemetry(out_dir, d)
            finally:
                if lock is not None:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
    except Exception:
        pass


def telem_bump(key, n=1, out_dir=None):
    """counters[key] += n (e.g. 'edits', 'culled', 'uploads', 'narrator_pokes')."""
    _telem_mutate(out_dir, lambda d: d["counters"].__setitem__(
        key, int(d["counters"].get(key, 0) or 0) + int(n)))


def telem_max(key, value, out_dir=None):
    """maxima[key] = max(old, value) (e.g. 'lora_stacked')."""
    _telem_mutate(out_dir, lambda d: d["maxima"].__setitem__(
        key, max(int(d["maxima"].get(key, 0) or 0), int(value))))


def telem_set_add(key, value, out_dir=None):
    """sets[key] |= {value} (e.g. 'video_modes', 'tools', 'loras')."""
    def _add(d):
        cur = d["sets"].get(key)
        if not isinstance(cur, list):
            cur = []
        v = str(value)
        if v and v not in cur:
            cur.append(v)
        d["sets"][key] = cur
    _telem_mutate(out_dir, _add)


def telem_flag(key, out_dir=None):
    """flags[key] = 1, once (e.g. 'konami_triggered'). Idempotent."""
    _telem_mutate(out_dir, lambda d: d["flags"].__setitem__(key, 1))


def telem_mark_day(out_dir=None):
    """Record today in the distinct-days-used ledger (The Vigil)."""
    import datetime as _dt
    today = _dt.date.today().isoformat()

    def _mark(d):
        if today not in d["days"]:
            d["days"].append(today)
    _telem_mutate(out_dir, _mark)


def telemetry_metrics(out_dir):
    """Flatten the telemetry store into the achievement metric namespace.
    Counters/maxima pass through, sets become cardinalities, flags become 0/1."""
    d = load_telemetry(out_dir)
    m = {}
    for src in (d["counters"], d["maxima"]):
        for k, v in src.items():
            try:
                m[k] = int(v or 0)
            except (TypeError, ValueError):
                m[k] = 0
    sets = d["sets"]

    def _card(key):                 # hostile-but-valid JSON must not len()-crash
        v = sets.get(key)
        return len(v) if isinstance(v, list) else 0
    m["video_modes_used"] = _card("video_modes")
    m["tools_used"] = _card("tools")
    m["lora_distinct"] = _card("loras")
    m["enhance_workflows_distinct"] = _card("enhance_workflows")
    for k, v in d["flags"].items():
        m[k] = 1 if v else 0
    m["days_used"] = len(d["days"])
    return m


def sweep_telemetry(out_dir):
    """Set the state-derived feat flags whose 'event' may predate the telemetry
    layer: a custom mark in branding/ (Under the Hood) and the eclipse mark
    animation (Eclipse). Once set they stay set. Cheap; called by the API."""
    try:
        if list_marks(out_dir):
            telem_flag("branding_custom_file", out_dir=out_dir)
        if load_branding(out_dir).get("anim") == "eclipse":
            telem_flag("eclipse_anim_triggered", out_dir=out_dir)
    except Exception:
        pass


def top_published_rows(db_path, limit=12):
    """The owner's top published artworks by likes -> rows with artwork_id + engagement.
    Feeds the 'Your Art' panel (live views are fetched per artwork_id on top of this)."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT media_id, artwork_id, title, prompt_preview, aes_score, "
            "CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) AS likes, "
            "CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER) AS comments "
            "FROM catalog WHERE is_published = '1' AND COALESCE(artwork_id,'') != '' "
            "ORDER BY likes DESC, comments DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def published_totals(db_path):
    """At-a-glance totals across ALL the owner's published artworks (from --sync-artworks)."""
    con = _connect(db_path)
    try:
        r = con.execute(
            "SELECT COUNT(*) AS c, "
            "COALESCE(SUM(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),0) AS likes, "
            "COALESCE(SUM(CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER)),0) AS comments "
            "FROM catalog WHERE is_published = '1'").fetchone()
        return {"count": int(r[0] or 0), "likes": int(r[1] or 0), "comments": int(r[2] or 0)}
    except sqlite3.Error:
        return {"count": 0, "likes": 0, "comments": 0}
    finally:
        con.close()


def distinct_task_count(db_path):
    """How many distinct generation TASKS the local catalog holds. This is the apples-to-apples
    counterpart to the server's `me.tasks.totalCount` (also tasks, not images) -> backup coverage
    = local/server. Counts distinct non-empty task_id. Fails soft to 0."""
    con = _connect(db_path)
    try:
        return int(con.execute(
            "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != ''"
        ).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def rows_for_media_ids(db_path, ids):
    """Fetch catalog rows for a specific list of media_ids, preserving the given order.
    Used by the contact-sheet print view. Chunked to stay under SQLite's variable cap."""
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if not ids:
        return []
    con = _connect(db_path)
    try:
        found = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                "SELECT * FROM catalog WHERE media_id IN ({})".format(ph), chunk
            ).fetchall():
                found[str(r["media_id"])] = dict(r)
        return [found[i] for i in ids if i in found]
    finally:
        con.close()


def list_media_ids(db_path, q="", model="", date_from="", date_to="", sort="newest",
                   batch="", rating_min=0, published_only=False, art_tag="", lora="",
                   media_type="", source="", collection=""):
    """Return ordered list of media_ids matching the filter (no row data)."""
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    order = _SORT_SQL.get(sort, _DEFAULT_SORT_SQL)
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT media_id FROM catalog WHERE {} ORDER BY {}".format(where, order), params
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def unique_models(db_path):
    """Return sorted list of distinct non-empty model names in the catalog."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT DISTINCT model_name FROM catalog WHERE model_name != '' ORDER BY model_name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def catalog_model_options(db_path):
    """Return [(name, model_id)] for distinct models in the catalog, most-used
    first. model_id is the version id used in real generations, so it's a valid,
    guaranteed-working value for --generate's --model -- the basis of the model
    picker dropdown."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT COALESCE(NULLIF(model_name,''), model_id) AS nm, model_id, COUNT(*) c "
            "FROM catalog WHERE COALESCE(model_id,'') != '' AND model_id GLOB '[0-9]*' "
            "GROUP BY model_id ORDER BY c DESC"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    finally:
        con.close()


def backfill_batches(out_dir, db_path):
    """Scan batches/ on disk and populate the batch column for already-organized images.

    Safe to re-run — only updates rows where batch is currently empty.
    Returns number of rows updated.
    """
    batches_root = Path(out_dir) / "batches"
    if not batches_root.exists():
        return 0
    updates = {}  # media_id -> batch_name
    for batch_dir in batches_root.iterdir():
        if not batch_dir.is_dir():
            continue
        batch_name = batch_dir.name
        for p in batch_dir.rglob("*"):
            if p.suffix.lower() not in _IMAGE_EXTS:
                continue
            mid = p.stem.split("_")[-1]
            updates[mid] = batch_name
    if not updates:
        return 0
    con = _connect(db_path)
    try:
        updated = 0
        for mid, batch_name in updates.items():
            cur = con.execute(
                "UPDATE catalog SET batch=? WHERE media_id=? AND (batch='' OR batch IS NULL)",
                (batch_name, mid),
            )
            updated += cur.rowcount
        con.commit()
        return updated
    finally:
        con.close()


def unique_batches(db_path):
    """Return sorted list of distinct non-empty batch names in the catalog."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT DISTINCT batch FROM catalog WHERE batch != '' ORDER BY batch"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def catalog_years(db_path):
    """Descending list of years (ints) present in catalog created_at, for the
    date-filter dropdowns. Empty if the catalog has no dated rows."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT DISTINCT SUBSTR(created_at,1,4) AS y FROM catalog "
            "WHERE created_at != '' AND y != '' ORDER BY y DESC"
        ).fetchall()
        return [int(r[0]) for r in rows if str(r[0]).isdigit()]
    finally:
        con.close()


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "{:.1f} {}".format(n, unit)
        n /= 1024


def collection_health(out_dir, db_path):
    """Compute at-a-glance metrics for the health dashboard. One disk walk
    (sizes + buckets + Class-A duplicate detection) plus a few catalog queries.

    Returns a dict consumed by the /health route. Cheap (no content hashing) so
    it's safe to render on every page load.
    """
    from collections import defaultdict, Counter
    gallery_dir = out_dir / "gallery"
    quarantine_dir = out_dir / "_duplicates"

    def _under(p, parent):
        try:
            p.relative_to(parent); return True
        except ValueError:
            return False

    per_bucket = Counter()
    total_files = 0
    total_bytes = 0
    on_disk_ids = set()
    on_disk_rels = set()      # relative paths of every media file (incl. videos)
    locs = defaultdict(set)   # media_id -> set of bucket names (Class A dup detection)
    dup_redundant = 0
    dup_bytes = 0
    mid_sizes = defaultdict(list)  # media_id -> [sizes] to estimate reclaimable
    _video_exts = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}

    for p in out_dir.rglob("*"):
        ext = p.suffix.lower()
        is_img = ext in _IMAGE_EXTS
        if (not is_img and ext not in _video_exts) or not p.is_file():
            continue
        if p.name.endswith(".part") or _under(p, gallery_dir) or _under(p, quarantine_dir):
            continue
        rel = p.relative_to(out_dir)
        on_disk_rels.add(str(rel).replace("\\", "/"))
        if not is_img:
            continue          # videos: track the path only; skip image-centric stats
        top = str(rel).replace("\\", "/").split("/")[0]
        if top == "images":
            bucket = "images"
        elif top == "batches":
            bucket = "batches"
        elif top == "unknown-date" or (len(top) == 7 and top[4] == "-" and top[:4].isdigit()):
            bucket = "month"
        else:
            bucket = "other"
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        total_files += 1
        total_bytes += sz
        per_bucket[bucket] += 1
        mid = media_id_of(p)
        on_disk_ids.add(mid)
        locs[mid].add(bucket)
        mid_sizes[mid].append(sz)

    for mid, buckets in locs.items():
        if len(buckets) > 1:
            extra = len(mid_sizes[mid]) - 1
            dup_redundant += extra
            sizes = sorted(mid_sizes[mid])
            dup_bytes += sum(sizes[:-1])  # all but the largest counted as reclaimable

    con = _connect(db_path)
    try:
        def _scalar(sql):
            return con.execute(sql).fetchone()[0]
        total_rows   = _scalar("SELECT COUNT(*) FROM catalog")
        with_image   = _scalar("SELECT COUNT(*) FROM catalog WHERE filename != ''")
        with_full    = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(prompt_full,'') != ''")
        rated        = _scalar("SELECT COUNT(*) FROM catalog "
                               "WHERE COALESCE(NULLIF(rating,''),'0') NOT IN ('0')")
        by_month = con.execute(
            "SELECT SUBSTR(created_at,1,7) AS m, COUNT(*) FROM catalog "
            "WHERE created_at != '' GROUP BY m ORDER BY m"
        ).fetchall()
        top_models = con.execute(
            "SELECT COALESCE(NULLIF(model_name,''), NULLIF(model_id,''), 'unknown') AS mdl, "
            "COUNT(*) AS c FROM catalog WHERE filename != '' GROUP BY mdl ORDER BY c DESC LIMIT 8"
        ).fetchall()
        # Published-artwork analytics (populated by --sync-artworks)
        published = _scalar("SELECT COUNT(*) FROM catalog WHERE is_published = '1'")
        total_likes = _scalar(
            "SELECT COALESCE(SUM(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),0) "
            "FROM catalog WHERE is_published = '1'")
        tag_rows = con.execute(
            "SELECT art_tags FROM catalog WHERE COALESCE(art_tags,'') != ''").fetchall()
        lora_rows = con.execute(
            "SELECT loras FROM catalog WHERE COALESCE(loras,'') != ''").fetchall()
        prompt_rows = con.execute(
            "SELECT prompt_preview FROM catalog WHERE COALESCE(prompt_preview,'') != ''"
        ).fetchall()
        # catalog rows that claim a file but whose media_id isn't on disk
        cat_rows = con.execute(
            "SELECT media_id, filename FROM catalog WHERE filename != ''").fetchall()
    finally:
        con.close()

    tag_counter = Counter()
    for (tags,) in tag_rows:
        for t in (tags or "").split(","):
            t = t.strip()
            if t:
                tag_counter[t] += 1
    top_tags = tag_counter.most_common(10)

    lora_counter = Counter()
    for (loras,) in lora_rows:
        for part in (loras or "").split(","):
            name = part.strip().rsplit(":", 1)[0].strip()  # drop ":weight"
            if name:
                lora_counter[name] += 1
    top_loras = lora_counter.most_common(10)

    # Prompt word-cloud: most common meaningful words across prompt previews.
    import re as _re
    stop = {"the", "and", "a", "an", "of", "with", "in", "on", "at", "to", "for",
            "is", "by", "as", "or", "from", "best", "quality", "masterpiece",
            "highres", "detailed", "very", "high", "score", "up", "1girl", "1boy",
            "solo", "looking", "viewer"}
    word_counter = Counter()
    for (pp,) in prompt_rows:
        for w in _re.findall(r"[a-z][a-z']{2,}", (pp or "").lower()):
            if w not in stop:
                word_counter[w] += 1
    top_words = word_counter.most_common(40)

    # A row is "missing" only if NEITHER its media id is on disk (the PixAI
    # naming path) NOR its filename resolves to a real file (the imported/local
    # path, whose media_id is a synthetic local_<hash> that never matches a file).
    missing = sum(
        1 for mid, fn in cat_rows
        if (not mid or mid not in on_disk_ids)
        and (fn or "").replace("\\", "/") not in on_disk_rels)

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_h": _fmt_size(total_bytes),
        "per_bucket": dict(per_bucket),
        "dup_redundant": dup_redundant,
        "dup_bytes": dup_bytes,
        "dup_bytes_h": _fmt_size(dup_bytes),
        "catalog_rows": total_rows,
        "with_image": with_image,
        "with_full_meta": with_full,
        "full_meta_pct": round(100 * with_full / with_image) if with_image else 0,
        "rated": rated,
        "missing": missing,
        "by_month": [(m, c) for (m, c) in by_month],
        "top_models": [(m, c) for (m, c) in top_models],
        "published": published,
        "total_likes": total_likes,
        "top_tags": top_tags,
        "top_loras": top_loras,
        "top_words": top_words,
    }


def duplicate_groups(out_dir, limit=300):
    """Class-A duplicates for the gallery review browser: media_ids whose file
    exists in more than one folder bucket. Cheap (no hashing). Returns a list of
    {media_id, keeper(rel), copies:[{rel,bucket,size}]} sorted keeper-first."""
    from collections import defaultdict
    gallery_dir = out_dir / "gallery"
    quarantine_dir = out_dir / "_duplicates"
    prio = {"batches": 0, "month": 1, "images": 2, "other": 3}
    locs = defaultdict(list)
    for p in out_dir.rglob("*"):
        if p.suffix.lower() not in _IMAGE_EXTS or not p.is_file():
            continue
        if p.name.endswith(".part") or _is_under(p, gallery_dir) or _is_under(p, quarantine_dir):
            continue
        rel = p.relative_to(out_dir)
        top = str(rel).replace("\\", "/").split("/")[0]
        if top == "images":
            bucket = "images"
        elif top == "batches":
            bucket = "batches"
        elif top == "unknown-date" or (len(top) == 7 and top[4] == "-" and top[:4].isdigit()):
            bucket = "month"
        else:
            bucket = "other"
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 0
        locs[media_id_of(p)].append({"rel": str(rel), "bucket": bucket, "size": sz})

    groups = []
    for mid, items in locs.items():
        if len(items) > 1 and len({it["bucket"] for it in items}) > 1:
            ordered = sorted(items, key=lambda it: (prio.get(it["bucket"], 9), len(it["rel"])))
            groups.append({"media_id": mid, "keeper": ordered[0]["rel"], "copies": ordered})
            if len(groups) >= limit:
                break
    return groups


def media_id_of(path):
    """Canonical media_id extraction (INVARIANT 1): the last underscore-delimited
    chunk of the filename stem. Works for every naming layout the tool produces:
    flat (`prompt_task_<mid>`), batch (`NN_<mid>`), and bare (`<mid>`)."""
    from pathlib import Path
    return Path(path).stem.split("_")[-1]


def _is_under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def find_files_for_media_id(out_dir, media_id, include_gallery=False):
    """All on-disk image files whose media_id matches, anywhere under out_dir.

    Single source of truth for media-id -> file resolution, shared by resume
    (`already_downloaded`), the gallery (`find_image_file`), and the duplicate
    audit. Matches BOTH naming layouts in one pass:
      * prefixed   `prompt_task_<mid>.ext` / `NN_<mid>.ext`
      * bare       `<mid>.ext`   (single-image --organize month files)

    The exact `media_id_of(p) == mid` check prevents substring collisions (a
    longer id ending in these digits). Skips `.part`, zero-byte files, gallery
    thumbnails (unless include_gallery=True), and quarantined files under
    _duplicates/ (so a quarantined copy never counts as a live "survivor" and
    resume treats it as not-present). Returns a list of Paths.
    """
    mid = str(media_id)
    gallery_dir = out_dir / "gallery"
    quarantine_dirs = (out_dir / "_duplicates", out_dir / DELETED_DIRNAME)
    matches = []
    for p in out_dir.rglob("*{}.*".format(mid)):
        if p.suffix.lower() not in _IMAGE_EXTS:
            continue
        if p.name.endswith(".part"):
            continue
        if media_id_of(p) != mid:
            continue
        if not include_gallery and _is_under(p, gallery_dir):
            continue
        if any(_is_under(p, q) for q in quarantine_dirs):
            continue
        try:
            if not p.is_file() or p.stat().st_size == 0:
                continue
        except OSError:
            continue
        matches.append(p)
    return matches


def find_image_file(out_dir, media_id, filename):
    """Locate an image file: try catalog filename first, then media-id fallback.

    Excludes out_dir/gallery/ so thumbnails are never returned as full-res images.
    """
    gallery_dir = out_dir / "gallery"
    deleted_dir = out_dir / DELETED_DIRNAME
    if filename:
        for candidate in out_dir.rglob(filename):
            if (candidate.is_file() and not _is_under(candidate, gallery_dir)
                    and not _is_under(candidate, deleted_dir)):
                return candidate
    matches = find_files_for_media_id(out_dir, media_id)
    return matches[0] if matches else None


# Accidental bulk deletes should be recoverable: purges MOVE files here instead of
# destroying them (the catalog row is still removed, so the gallery stays clean).
DELETED_DIRNAME = "_deleted"


def purge_media_local(out_dir, thumb_dir, db_path, media_id, filename, quarantine=True):
    """Remove a media's catalog row + (regenerable) thumbnail, and either move its
    file to out_dir/_deleted/ (default, recoverable) or hard-delete it. Returns the
    new quarantine location (Path) when moved, else None."""
    out_dir = Path(out_dir)
    img = find_image_file(out_dir, media_id, filename)
    moved = None
    if img and img.exists():
        if quarantine:
            qdir = out_dir / DELETED_DIRNAME
            qdir.mkdir(parents=True, exist_ok=True)
            dest = qdir / img.name
            if dest.exists():                       # don't clobber an earlier delete
                dest = qdir / "{}_{}{}".format(img.stem, media_id, img.suffix)
            try:
                img.replace(dest)                   # atomic move on the same volume
                moved = dest
            except OSError:
                pass
        else:
            try:
                img.unlink()
            except OSError:
                pass
    tp = Path(thumb_dir) / "{}.jpg".format(media_id)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass
    delete_from_catalog(db_path, media_id)
    return moved


def make_thumbnail(img_path, thumb_path):
    if Image is None:
        return False
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMB_SIZE, Image.LANCZOS)
            im.save(thumb_path, "JPEG", quality=THUMB_QUALITY)
        return True
    except Exception:
        return False


def make_video_thumbnail(video_path, thumb_path):
    """Poster fallback for videos PixAI gave no poster frame: extract an early
    frame via ffmpeg (already a dependency for Loom export), then run it through
    the SAME Pillow thumbnail path as images so size/quality stay uniform.
    Returns False (never raises) when ffmpeg is missing or the extract fails."""
    import shutil as _sh
    import subprocess
    import tempfile
    if Image is None or not _sh.which("ffmpeg"):
        return False
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5",
             "-i", str(video_path), "-frames:v", "1", tmp],
            capture_output=True, timeout=90)
        if r.returncode != 0 or not os.path.getsize(tmp):
            # clips shorter than the seek point: take the literal first frame
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-i", str(video_path), "-frames:v", "1", tmp],
                capture_output=True, timeout=60)
        if r.returncode != 0 or not os.path.getsize(tmp):
            return False
        return make_thumbnail(Path(tmp), thumb_path)
    except Exception:
        return False
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def build_thumbnails(rows, out_dir, thumb_dir, force=False, progress_cb=None, workers=8):
    """Generate JPEG thumbnails for rows that have a file. CPU-bound (Pillow),
    so a thread pool gives a real multi-core speedup (Pillow releases the GIL
    during decode/encode). workers<=1 runs serially. Each worker writes a distinct
    thumb file; progress is reported on the calling thread.

    Videos are included ONLY when their thumb is missing (the collected PixAI
    poster made it already when one existed): a poster-less video gets a local
    ffmpeg frame-extract instead of staying blank forever. `force` deliberately
    does NOT overwrite an existing video thumb -- the poster came from the
    network and can't be regenerated from the local file."""
    if Image is None:
        print("Warning: Pillow not installed -- thumbnails will not be generated.")
        return
    total = 0
    done = 0
    work = []
    for row in rows:
        if not row.get("filename"):
            continue
        is_vid = row.get("is_video") == "1"
        total += 1
        thumb_path = thumb_dir / "{}.jpg".format(row["media_id"])
        if thumb_path.exists() and (is_vid or not force):
            done += 1
            continue
        work.append((row["media_id"], thumb_path, row.get("filename"), is_vid))

    def _one(item):
        mid, thumb_path, filename, is_vid = item
        if is_vid:
            vp = Path(out_dir) / (filename or "")
            if not vp.exists():
                m = find_files_for_media_id(Path(out_dir), mid)
                vp = m[0] if m else None
            return bool(vp and make_video_thumbnail(vp, thumb_path))
        img_path = find_image_file(out_dir, mid, filename)
        return bool(img_path and make_thumbnail(img_path, thumb_path))

    def _tick():
        pct = int(done / total * 100) if total else 100
        if progress_cb:
            progress_cb(done, total, pct)
        else:
            print("\r  Thumbnails: {}/{} ({:d}%)  ".format(done, total, pct),
                  end="", flush=True)

    if work and workers and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed([ex.submit(_one, it) for it in work]):
                try:
                    if fut.result():
                        done += 1
                except Exception:
                    pass
                _tick()
    else:
        for it in work:
            if _one(it):
                done += 1
            _tick()
    if total and not progress_cb:
        print()


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

# Design tokens: the SINGLE source of truth for the gallery's palette + achievement
# skins, shared (via the __DESIGN_TOKENS__ marker + .replace(), same idiom as LOOM_PAGE's
# __JSX__) by BASE_HTML and LOOM_PAGE so both surfaces re-skin together instead of the
# Loom carrying its own copy that silently drifts from this one.
DESIGN_TOKENS_CSS = r"""
  :root {
    /* Palette sampled from two reference images:
       731004762264180451.webp — teal "magic glow", green gems, rare gold trim.
       s1_06.png              — the deep violet armor (#33236d/#241f5b/#36345a/#643aac)
                                that tints the ground and surfaces below. */
    --base:    #0c0a1c; --mantle:  #0a0818; --surface0:#211f3a;
    --surface1:#3a3460; --overlay0:#6a6088; --text:    #d6d2e2;
    --subtext: #9a93ab; --lavender:#b692e6; --mauve:   #c4a6f0;
    --red:     #f38ba8; --peach:   #fab387; --green:   #46d488;
    --blue:    #47cbc3; --sapphire:#3a8a93;
    /* Moonglade Athenaeum palette: lavender leads, emerald is the "magic"
       highlight (Nelnamara's gems), gold filigree is rare. */
    --accent:  #b692e6; --accent-soft:#4fc99a; --gold: #d4af37; --emerald:#4fc99a;
    --purple-deep: #33236d; --purple-bright: #643aac;
    /* Feat tier: gunmetal band + ruby glow (the agreed 5th tier -- NOT pink). */
    --gunmetal: #8a93a2; --gunmetal-deep: #4a515c;
    --ruby: #e0355e; --ruby-deep: #a11238;
  }
  /* ---- Skins: cosmetic palette swaps unlocked by achievements. A skin overrides
     the meaningful subset of the palette; everything else inherits :root. Applied
     via <html data-skin="..."> (set pre-paint from localStorage in <head>). ---- */
  html[data-skin="nightfallen"] {
    --base:#0a0713; --mantle:#080610; --surface0:#241a3f; --surface1:#3c2b63;
    --text:#e7ddff; --subtext:#a493c9; --overlay0:#7a6aa6;
    --accent:#a678f0; --lavender:#c9a6ff; --mauve:#d3b6ff;
    --emerald:#7f6fe0; --accent-soft:#8b7ae6; --gold:#d9b3ff;
  }
  html[data-skin="moonlit"] {
    --base:#0b1018; --mantle:#080d15; --surface0:#1c2735; --surface1:#334358;
    --text:#e6eefb; --subtext:#93a6bd; --overlay0:#6f8298;
    --accent:#8fb8e8; --lavender:#bcd6f5; --mauve:#c6dbf7;
    --emerald:#68d5e0; --accent-soft:#6fc9d6; --gold:#cfe1f5;
  }
  html[data-skin="ember"] {
    --base:#160c0c; --mantle:#120909; --surface0:#33201c; --surface1:#5a352c;
    --text:#fbe6df; --subtext:#c79b8d; --overlay0:#a5786a;
    --accent:#e8935f; --lavender:#f0b48f; --mauve:#f3c3a5;
    --emerald:#e0a94b; --accent-soft:#d67f4b; --gold:#ffcf7a;
  }
  html[data-skin="verdant"] {
    --base:#0a1410; --mantle:#08110d; --surface0:#173026; --surface1:#2a5140;
    --text:#e2f5ea; --subtext:#93bda6; --overlay0:#6f9d84;
    --accent:#5fd39a; --lavender:#8fe8bf; --mauve:#a5f3cf;
    --emerald:#4fc99a; --accent-soft:#4bd68f; --gold:#c8e6a8;
  }
"""

# One-click enhance plugins for the Edit tab. `detail-fix` is the VERIFIED workflowId
# (fired for real 2026-07-02). `hand-fix` / `face-fix` use workflowNames mined from the
# app bundle -- unverified until fired, but a rejected panelplugin submit costs no credits,
# so they're safe to offer and confirm live. More arrive once we have the full catalog.
ENHANCE_PLUGINS = {
    "detail-fix": {"label": "Detail fix", "workflow_id": "1797414829336369706"},
    "hand-fix":   {"label": "Fix hands",  "workflow_name": "mymusise/hand-fix"},
    "face-fix":   {"label": "Fix face",   "workflow_name": "kyo/face-detailer"},
}


# The Loom (Seedance video storyboard tool) is served at /loom. Its React source
# lives in loom/master-storyboard.jsx; this page loads React+Babel+picker-core from
# locally-vendored files (loom/vendor/, served by /loom/vendor/<file>; zero network
# calls to paint) and, per the tool's own integration notes, swaps window.storage onto
# the gallery backend so a board persists server-side (shared across devices) instead
# of per-browser localStorage.
LOOM_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Loom - Moonglade Athenaeum</title>
<script>/* apply saved skin before first paint (no FOUC) -- same key/origin the gallery
   header writes, so switching skin there re-colors the Loom too */
try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>
<style>
__DESIGN_TOKENS__
body { background: var(--base); margin: 0; }
</style>
<script src="/loom/vendor/react.production.min.js"></script>
<script src="/loom/vendor/react-dom.production.min.js"></script>
<script src="/loom/vendor/babel.min.js"></script>
<script src="/static/picker-core.js"></script>
</head><body>
<div id="root"></div>
<script>
window.storage = {
  get:function(k){ return fetch('/api/loom/get?key='+encodeURIComponent(k)).then(function(r){return r.json();}).then(function(d){ return (d&&d.value!=null)?{value:d.value}:null; }); },
  set:function(k,v){ return fetch('/api/loom/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k,value:v})}); },
  list:function(p){ return fetch('/api/loom/list?prefix='+encodeURIComponent(p||'')).then(function(r){return r.json();}).then(function(d){ return {keys:(d&&d.keys)||[]}; }); },
  delete:function(k){ return fetch('/api/loom/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})}); }
};
</script>
<script type="text/babel" data-presets="react">
const { useState, useEffect, useRef, useCallback } = React;
__JSX__
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
</script>
<button id="eb-help-btn" onclick="document.getElementById('eb-help').style.display='flex';try{fetch('/api/ach-event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'docs'})})}catch(e){}"
  style="position:fixed;bottom:18px;right:18px;z-index:300;width:38px;height:38px;border-radius:50%;background:var(--accent);color:var(--base);border:none;font-size:19px;font-weight:700;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5);"
  title="How The Loom works">?</button>
<div id="eb-help" onclick="if(event.target===this)this.style.display='none'"
  style="position:fixed;inset:0;z-index:301;background:rgba(6,4,16,.72);display:none;align-items:center;justify-content:center;">
  <div style="width:680px;max-width:92vw;max-height:86vh;overflow-y:auto;background:var(--surface0);border:1px solid var(--surface1);border-radius:14px;padding:22px 26px;color:var(--text);font:13.5px/1.55 system-ui,sans-serif;">
    <h2 style="margin:0 0 4px;color:var(--text);">The Loom &mdash; quick guide</h2>
    <p style="color:var(--subtext);margin:0 0 14px;">A storyboard for multi-clip AI video: plan the whole piece, then render shot by shot.</p>
    <p><b>Acts &amp; Shots.</b> Your video is a list of <i>acts</i>, each holding <i>shot cards</i>. The reel bar tracks total runtime against your target. Add a shot, give it a duration, and write what happens.</p>
    <p><b>Modes.</b> Each shot has a generation mode: <b>T2V</b> text-only &middot; <b>I2V</b> animate from one image &middot; <b>FLF</b> morph from a start frame to an end frame &middot; <b>R2V</b> multi-reference (cast + scenes) &middot; <b>V2V</b> extend/transform an existing clip.</p>
    <p><b>Cast &amp; Assets.</b> Reusable references. Cite them in shot text as <b>@image1 @video1 @audio1</b> (lowercase). "Lock appearance" keeps a character consistent across shots.</p>
    <p><b>Frame handoff.</b> Every card has an open and close frame. "&#8627; inherit prev close" chains one shot's last frame into the next shot's first &mdash; the &#10003;/&#9888; dots show whether the chain is intact.</p>
    <p><b>&#9654; Generate shot.</b> Renders the card on PixAI's video engine (V4.0): your cast + frames upload in @-order, the shot text becomes the prompt, and the finished clip lands in the gallery catalog &mdash; free when a V4.0 card covers it. Status shows on the card; "open clip &#8599;" plays it.</p>
    <p><b>Copy shot.</b> The same assembled prompt, to your clipboard &mdash; paste it into any Seedance-style generator. The board is engine-agnostic by design: plan here, render anywhere.</p>
    <p><b>Saving.</b> The board autosaves to the gallery server (survives restarts). Backup .json / export .txt live in the header.</p>
    <p style="color:var(--subtext);">Full manual: <code>docs/LOOM.md</code> in the repo.</p>
  </div>
</div>
</body></html>""".replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS)


def _build_stamp():
    """Version + short git SHA of the code THIS process loaded, computed once at
    startup. If you pull without restarting, this keeps showing the OLD sha -- which
    is precisely how you tell a stale server from a fresh one. Fails soft."""
    try:
        import pixai_gallery_backup as _core
        ver = getattr(_core, "__version__", "?")
    except Exception:
        ver = "?"
    sha = ""
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            stderr=subprocess.DEVNULL, timeout=4).decode().strip()
    except Exception:
        sha = ""
    return "v{}".format(ver) + (" · {}".format(sha) if sha else "")


def _supervised():
    """True when the server was started by the managed launcher (Serve Gallery), which sets
    MOONGLADE_SUPERVISED=1 and relaunches on exit code 42. Restart is only offered when True."""
    return os.environ.get("MOONGLADE_SUPERVISED") == "1"


def _schedule_server_exit(code):
    """Let the current HTTP response flush, then exit the process with `code`
    (0 = stop; 42 = the supervisor's 'relaunch me' signal). Factored out so tests can assert
    the intended exit code without actually killing the test process."""
    def _die():
        import time
        time.sleep(0.4)
        os._exit(code)
    threading.Thread(target=_die, daemon=True).start()


def create_app(out_dir: Path):
    app = Flask(__name__)
    db_path = out_dir / "catalog.db"
    build_stamp = _build_stamp()
    init_db(db_path)
    set_telemetry_out(out_dir)     # bare telem_* bumps land in this install's ledger
    backfill_batches(out_dir, db_path)
    thumb_dir = out_dir / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    @app.context_processor
    def _inject_branding():
        # mark_url / mark_anim / mark_kind on every page render, so the chosen
        # banner mark + its animation apply to the gallery, panel, health, dupes.
        return brand_context(out_dir)

    # ------------------------------------------------------------------
    # Control Panel: run maintenance CLI ops as background jobs with live
    # logs. Each action is a WHITELISTED argv against pixai_gallery_backup.py
    # (never an arbitrary command); destructive ones require confirm=True.
    # One job at a time. Localhost-gated at the routes. Runs the CLI as a
    # subprocess (isolation + natural stdout capture -- same shape the GUI
    # uses) with cwd = the checkout dir (where config.json lives).
    # ------------------------------------------------------------------
    _cli_path = str(Path(__file__).resolve().parent / "pixai_gallery_backup.py")
    _cli_dir = str(Path(__file__).resolve().parent)
    _panel_lock = threading.Lock()
    _panel_job = {"status": "idle", "action": "", "label": "", "lines": [],
                  "rc": None, "started_at": None, "progress": None,
                  "proc": None, "cancelled": False}
    _PROG_PREFIX = "~=MGPROG=~"        # matches PANEL_PROGRESS_PREFIX in pixai_gallery_backup.py
    # The Loom's ffmpeg export job (trim + concat finished shots -> one mp4).
    _export_lock = threading.Lock()
    _export_job = {"status": "idle", "progress": 0, "elapsed": 0.0,
                   "out": "", "error": "", "proc": None, "cancelled": False}
    _export_dir = out_dir / "loom" / "exports"
    # Bulk cloud-delete runs OFF-THREAD (it's irreversible and can be many network calls)
    # and reports to the Activity card via the job log. Single-flight so two runs can never
    # interleave their deletes.
    _bulkdel_lock = threading.Lock()
    _bulkdel_running = {"on": False}

    # action -> {args (extra flags), label, destructive}
    # action -> {args, label, destructive, panel_visible}. panel_visible=False actions
    # are still valid for /api/panel/run and the scheduler dropdown, but don't render as
    # a Maintenance button -- they're full-feed-scan jobs meant to run periodically in
    # the background, not be clicked after every pull. --sync itself now folds
    # fix-models + backfill-full-meta internally (see the CLI's --sync handler), so
    # those two are gone as standalone actions entirely.
    PANEL_ACTIONS = {
        "sync":          {"args": ["--sync"], "label": "Sync now — pull new + fill metadata", "destructive": False},
        "stats":         {"args": ["--catalog-stats"], "label": "Catalog stats", "destructive": False},
        "audit":         {"args": ["--audit", "--no-content"], "label": "Duplicate audit (fast, read-only)", "destructive": False},
        # (Export CSV isn't here on purpose -- in the browser it's a real DOWNLOAD via /export-csv,
        #  not a subprocess that writes catalog.csv into the backup folder.)
        "organize-dry":  {"args": ["--organize", "--dry-run"], "label": "Organize — preview (dry run)", "destructive": False},
        "dedup-dry":     {"args": ["--dedup"], "label": "Dedup — preview (dry run)", "destructive": False},
        # --- background-only: full-feed scans, run by the scheduler, not a button ---
        # (both re-walk the WHOLE history every run, no --update-style short-circuit --
        # fine hourly/daily, wasteful to click after every incremental pull)
        "sync-artworks":     {"args": ["--sync-artworks"], "label": "Sync published-artwork metadata", "destructive": False, "panel_visible": False},
        "sync-videos":       {"args": ["--sync-videos"], "label": "Sync i2v videos (back up mp4s)", "destructive": False, "panel_visible": False},
        "reconcile-deleted": {"args": ["--reconcile-deleted"], "label": "Reconcile deleted (flag cloud-removed rows)", "destructive": False, "panel_visible": False},
        # --- destructive: require confirm=true ---
        "organize":      {"args": ["--organize"], "label": "Organize into month folders", "destructive": True},
        "dedup-apply":   {"args": ["--dedup", "--apply"], "label": "Dedup — quarantine dupes to _duplicates/", "destructive": True},
        "rebuild-thumbs": {"args": ["--rebuild-thumbs"],
                           "label": "Rebuild ALL thumbnails — uniform quality + video posters",
                           "destructive": True},
    }

    def _panel_reader(proc):
        with _panel_lock:
            jid = _panel_job.get("job_id")
        last_pct = -1
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if line.startswith(_PROG_PREFIX):
                # progress marker (not log): "<prefix>done|total|new" -> drive the bar
                try:
                    done, total, new = (int(x) for x in line[len(_PROG_PREFIX):].split("|"))
                    with _panel_lock:
                        _panel_job["progress"] = {"done": done, "total": total, "new": new,
                                                  "pct": round(min(done / total, 1.0) * 100, 1) if total else None}
                    if jid and total:                    # mirror into the Activity card, throttled
                        pct = int(min(done / total, 1.0) * 100)
                        if pct != last_pct:              # ~once per 1% tick, not every line
                            last_pct = pct
                            _log_job(jid, status="running", done=done, total=total)
                except (ValueError, ZeroDivisionError):
                    pass
                continue
            with _panel_lock:
                _panel_job["lines"].append(line)
                if len(_panel_job["lines"]) > 800:       # ring buffer
                    del _panel_job["lines"][:-800]
        proc.stdout.close()
        rc = proc.wait()
        with _panel_lock:
            cancelled = _panel_job.get("cancelled")
            status = "cancelled" if cancelled else ("done" if rc == 0 else "failed")
            _panel_job["rc"] = rc
            _panel_job["status"] = status
            _panel_job["progress"] = None                # clear the bar when the job ends
            _panel_job["proc"] = None
        if jid:                                          # cancelled/done both close the card row cleanly
            _log_job(jid, status=("failed" if status == "failed" else "done"),
                     error=("exited {}".format(rc) if status == "failed" else None))

    def _panel_run(action):
        import subprocess
        spec = PANEL_ACTIONS[action]
        # Worker count is a persisted panel setting (schedule.json), so BOTH manual
        # clicks and the scheduled run use it. Harmless on jobs that ignore --workers
        # (organize/dedup/audit); speeds up the ones that don't (sync's pull + backfill).
        try:
            workers = max(1, min(int(_load_sched().get("workers") or 4), 16))
        except (TypeError, ValueError):
            workers = 4
        argv = [sys.executable, _cli_path, "--out", str(out_dir), "-v",
                "--workers", str(workers)] + spec["args"]
        # MOONGLADE_PROGRESS makes the CLI emit machine progress markers we parse above.
        env = dict(os.environ, MOONGLADE_PROGRESS="1")
        proc = subprocess.Popen(argv, cwd=_cli_dir, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                encoding="utf-8", errors="replace", env=env)
        import uuid
        job_id = "panel-" + uuid.uuid4().hex[:12]
        with _panel_lock:
            _panel_job.update(status="running", action=action, label=spec["label"],
                              lines=["$ " + " ".join(spec["args"])], rc=None,
                              started_at=None, progress=None, proc=proc, cancelled=False,
                              job_id=job_id)
        _log_job(job_id, status="running", type="panel", label=spec["label"])
        threading.Thread(target=_panel_reader, args=(proc,), daemon=True).start()

    # ---- Automated tasks: run a SAFE job on an interval while the app is open ----
    # Persisted to out_dir/schedule.json. Only non-destructive actions are schedulable.
    # An in-process daemon: fires while the gallery/GUI is running (it is NOT an OS-level
    # cron -- for always-on, point Windows Task Scheduler at `--update` instead).
    _sched_lock = threading.Lock()

    def _log_job(job_id, **fields):
        """Append a job event to out_dir/jobs.jsonl for the Jobs card. Fails soft --
        activity logging must never break the request that triggered it."""
        try:
            import pixai_gallery_backup as _core
            _core.append_job_event(out_dir, job_id, **fields)
        except Exception:
            pass

    def _sched_path():
        return out_dir / "schedule.json"

    def _load_sched():
        try:
            if _sched_path().exists():
                s = json.loads(_sched_path().read_text(encoding="utf-8"))
                if isinstance(s, dict):
                    return s
        except (OSError, ValueError):
            pass
        return {"enabled": False, "action": "sync", "interval_hours": 6,
                "last_run": None, "workers": 4}

    def _save_sched(s):
        try:
            _sched_path().write_text(json.dumps(s), encoding="utf-8")
        except OSError:
            pass

    def _scheduler_loop():
        import time as _time
        while True:
            _time.sleep(60)
            try:
                s = _load_sched()
                action = s.get("action")
                if not s.get("enabled") or action not in PANEL_ACTIONS \
                        or PANEL_ACTIONS[action]["destructive"]:
                    continue
                interval = max(1, int(s.get("interval_hours") or 6)) * 3600
                if _time.time() - (s.get("last_run") or 0) < interval:
                    continue
                with _panel_lock:
                    if _panel_job["status"] == "running":
                        continue
                _panel_run(action)
                s["last_run"] = _time.time()
                _save_sched(s)
            except Exception:              # noqa: BLE001 -- a bad schedule must not kill the loop
                pass

    threading.Thread(target=_scheduler_loop, daemon=True).start()

    # ---- Live-mirror watcher: event-driven backup over PixAI's push WebSocket -----
    # Keeps the CLI's --watch/--watch-backup machinery (pixai_gallery_backup.py)
    # connected for as long as the gallery runs, auto-reconnecting with backoff on any
    # drop. Each generation is downloaded + cataloged the INSTANT it completes -- this
    # is what makes --update a fallback instead of the only way gens land locally.
    # Read-only listening + free downloads (no credits spent). Always-on by design.
    _watch_lock = threading.Lock()
    _watch_status = {"connected": False, "last_event_at": None, "mirrored": 0,
                      "events_seen": 0, "last_error": None, "started_at": None}

    def _watch_mirror(tid):
        """Download + catalog one finished task off the watcher's event loop (own
        session per call, matching the CLI's --watch-backup pattern)."""
        import pixai_gallery_backup as core
        try:
            session = core._make_session(None)
            core.collect_generation(session, tid, str(out_dir))
            with _watch_lock:
                _watch_status["mirrored"] += 1
        except Exception as e:
            with _watch_lock:
                _watch_status["last_error"] = str(e)[:200]

    def _reconcile_job(tid, ws_status):
        """Resolve OUR Activity/job log for a task straight from a live event, so a
        generation whose Generate-card poller was closed (you navigated into the panel)
        still lands as done/failed instead of hanging at 'running' forever. Only touches a
        job we already track -- never invents one for a task generated on the website."""
        import pixai_gallery_backup as core
        try:
            term = "failed" if ws_status in core._GEN_FAIL else "done"
            j = next((x for x in core.read_jobs(out_dir)
                      if str(x.get("job_id")) == str(tid)), None)
            if j and j.get("status") not in ("done", "failed"):
                _log_job(str(tid), status=term,
                         error=(ws_status if term == "failed" else None))
        except Exception:                          # noqa: BLE001 -- reconciling must not kill the watcher
            pass

    def _reconcile_orphan_jobs():
        """One-shot on watcher start: ask PixAI the real status of any job still marked
        'running' and resolve stale ones (read-only; no spend). Catches jobs orphaned when
        the app closed or a Generate card was dismissed before its poll resolved -- e.g. a
        task that failed while nobody was watching. Session is built lazily so a log with
        no running generate jobs costs nothing."""
        import pixai_gallery_backup as core
        box = {"s": None}
        def _status(tid):
            if box["s"] is None:
                box["s"] = core._make_session(None)
            return core.generation_status(box["s"], tid)
        try:
            core.resolve_orphan_jobs(out_dir, _status)
        except Exception:                          # noqa: BLE001
            pass

    def _watch_loop():
        import asyncio
        import time as _time
        import pixai_gallery_backup as core
        backed = set()   # task ids already mirrored this process's lifetime (a
                         # 'completed' event can repeat)
        with _watch_lock:
            _watch_status["started_at"] = _time.time()
        _reconcile_orphan_jobs()   # clear any job left hanging at 'running' from a prior session
        backoff = 5
        while True:
            try:
                # _make_session raises PixAIError (caught below) when no credentials
                # are configured -- it never returns a session with a blank auth
                # header, so there's nothing else to check here before subscribing.
                session = core._make_session(None)
                auth = session.headers.get("Authorization")

                def on_event(ev):
                    if ev.get("__meta__") == "subscribed":
                        with _watch_lock:
                            _watch_status["connected"] = True
                            _watch_status["last_error"] = None
                        return
                    tu = ev.get("taskUpdated")
                    if not tu:
                        return
                    with _watch_lock:
                        _watch_status["events_seen"] += 1
                        _watch_status["last_event_at"] = _time.time()
                    status = tu.get("status")
                    tid = str(tu.get("id") or "")
                    if status == core._WS_DONE_STATUS and tid and tid not in backed:
                        backed.add(tid)
                        threading.Thread(target=_watch_mirror, args=(tid,), daemon=True).start()
                    # Reconcile the Activity log from the SAME event stream, so a job resolves
                    # even if the Generate card that was polling /api/task-status is gone.
                    if tid and (status in core._GEN_DONE or status in core._GEN_FAIL):
                        _reconcile_job(tid, status)

                asyncio.run(core._watch_events_async(auth, on_event, None))
                backoff = 5   # a clean disconnect resets the backoff
            except Exception as e:
                with _watch_lock:
                    _watch_status["last_error"] = str(e)[:200]
            with _watch_lock:
                _watch_status["connected"] = False
            _time.sleep(backoff)
            backoff = min(backoff * 3, 60)

    # MOONGLADE_DISABLE_WATCH=1 skips auto-start -- set by the test suite's conftest so
    # create_app() (called by ~every test) never opens a real WebSocket to PixAI using
    # whatever real credentials happen to be in this machine's config.json.
    if os.environ.get("MOONGLADE_DISABLE_WATCH") != "1":
        threading.Thread(target=_watch_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Template
    # ------------------------------------------------------------------
    BASE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<meta name="theme-color" content="#0c0a1c">
<title>Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23cba6f7'/%3E%3Cpath d='M9 22V10h6a4 4 0 0 1 0 8h-3' stroke='%231e1e2e' stroke-width='2.4' fill='none' stroke-linecap='round'/%3E%3Ccircle cx='23' cy='11' r='2.2' fill='%23d4af37'/%3E%3C/svg%3E">
<script>if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){});});}</script>
<script>/* apply saved skin before first paint (no FOUC) */try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>
<style>
__DESIGN_TOKENS__
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--base); color: var(--text); font-family: system-ui, sans-serif; font-size: 14px; }

  /* Header */
  header { background: var(--mantle); padding: 12px 20px; display: flex; align-items: center; gap: 14px; border-bottom: 1px solid var(--surface0); position: sticky; top: 0; z-index: 100; overflow: hidden; }
  #brand-banner { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .16; z-index: 0; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, #000 0%, transparent 62%); mask-image: linear-gradient(90deg, #000 0%, transparent 62%); }
  /* Collapsing banner, JITTER-FREE: a tall header that SLIDES up on scroll via a
     sticky negative-top -- the browser scrolls it away natively, nothing resizes,
     so there is zero per-scroll layout thrash (the old JS height-on-scroll caused
     the jank). At rest you see the full art band; scroll and it pins showing only
     the bottom --bnr-slim (the nav bar). Pure CSS. Tunables: --bnr-hero (open
     height) and object-position (which horizontal slice of the art shows). */
  header.bannered { --bnr-hero: clamp(150px, 22vw, 300px); --bnr-slim: 62px;
    height: var(--bnr-hero); top: calc(var(--bnr-slim) - var(--bnr-hero));
    align-items: flex-end; padding: 0 20px 11px; }
  header.bannered #brand-banner { opacity: 1; -webkit-mask-image: none; mask-image: none;
    object-fit: cover; object-position: center 32%; }
  header.bannered::after { content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none;
    background: linear-gradient(180deg, rgba(17,17,27,.04) 30%, rgba(17,17,27,.4) 62%, rgba(17,17,27,.9) 88%); }
  header > * { position: relative; z-index: 1; }
  .brand { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  .brand-txt { display: flex; flex-direction: column; line-height: 1; }
  .brand .mark { width: 42px; height: 42px; border-radius: 10px; background: var(--accent); display: flex; align-items: center; justify-content: center; color: var(--base); font-weight: 700; font-size: 23px; position: relative; overflow: hidden; box-shadow: 0 0 0 rgba(182,146,230,0); animation: mark-glow 5.5s ease-in-out infinite; flex-shrink: 0; }
  .brand .mark::after { content: ''; position: absolute; top: 7px; right: 7px; width: 5px; height: 5px; border-radius: 50%; background: var(--gold); z-index: 2; }
  .brand .mark::before { content: ''; position: absolute; inset: 0; border-radius: 7px; background: var(--mantle); transform: translateX(-108%); animation: mark-eclipse 5.5s ease-in-out infinite; }
  /* When a real logo image is present it replaces the "M" tile: box + animation off. */
  .brand .mark .mark-m { position: relative; z-index: 4; }
  .brand .mark .mark-logo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; z-index: 5; }
  /* Custom logo present: the tile disappears but the MAGIC stays. The glow becomes a
     drop-shadow that hugs the art's alpha shape; the eclipse ::before becomes a glint band
     sweeping INSIDE the art (masked to the logo's own alpha, so it never spills past the
     silhouette); the gold-dot ::after becomes a twinkling star. Dumbledore's got style. */
  .brand .mark:has(.mark-logo) { background: transparent; box-shadow: none; animation: none; overflow: visible; }
  .brand .mark:has(.mark-logo) .mark-m { display: none; }
  .brand .mark:has(.mark-logo) .mark-logo { animation: logo-glow 5.5s ease-in-out infinite; }
  .brand .mark:has(.mark-logo)::before { content: ''; position: absolute; inset: 0; border-radius: 0; transform: none;
    background: linear-gradient(115deg, transparent 32%, rgba(255,255,255,.6) 47%, rgba(182,146,230,.4) 53%, transparent 68%);
    background-size: 260% 100%; background-position: 200% 0; background-repeat: no-repeat;
    -webkit-mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat; mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat;
    animation: logo-glint 5.5s ease-in-out infinite; z-index: 6; pointer-events: none; }
  .brand .mark:has(.mark-logo)::after { content: '\2726'; width: auto; height: auto; top: -7px; right: -8px;
    background: none; border-radius: 0; color: var(--gold); font-size: 11px; line-height: 1;
    text-shadow: 0 0 6px rgba(212,175,55,.9); animation: logo-twinkle 5.5s ease-in-out infinite; z-index: 7; }
  @keyframes mark-eclipse { 0%,100% { transform: translateX(-108%); } 46%,54% { transform: translateX(0); } }
  @keyframes mark-glow { 0%,100% { box-shadow: 0 0 10px rgba(182,146,230,.55); } 50% { box-shadow: 0 0 3px rgba(182,146,230,.2); } }
  @keyframes logo-glow { 0%,100% { filter: drop-shadow(0 0 7px rgba(182,146,230,.65)); } 50% { filter: drop-shadow(0 0 2px rgba(182,146,230,.18)); } }
  @keyframes logo-glint { 0%, 58% { background-position: 200% 0; } 78%, 100% { background-position: -100% 0; } }
  @keyframes logo-twinkle { 0%, 40%, 100% { opacity: 0; transform: scale(.5) rotate(0deg); }
    55% { opacity: 1; transform: scale(1.15) rotate(18deg); } 70% { opacity: .25; transform: scale(.8) rotate(36deg); } }
  /* --- Banner-mark animations (Panel > Branding). 'classic' keeps the legacy
     glow+glint+twinkle above; any other choice mutes those and drives its own
     effect off the img and the freed-up ::before/::after layers. Per-anim rules
     use !important to outrank the mute rules regardless of specificity. --- */
  .brand .mark.mk-tile .mark-logo { border-radius: 10px; }
  .brand .mark:not(.anim-classic):has(.mark-logo) .mark-logo { animation: none; }
  .brand .mark:not(.anim-classic):has(.mark-logo)::before { animation: none; background: none; -webkit-mask: none; mask: none; }
  .brand .mark:not(.anim-classic):has(.mark-logo)::after { animation: none; opacity: 0; }
  .brand .mark.anim-shine::before { background: linear-gradient(115deg, transparent 32%, rgba(255,255,255,.6) 47%, rgba(182,146,230,.4) 53%, transparent 68%) !important; background-size: 260% 100% !important; background-position: 200% 0 !important; background-repeat: no-repeat !important; -webkit-mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat !important; mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat !important; animation: logo-glint 2.2s linear infinite !important; }
  .brand .mark.anim-aurora::before { background: linear-gradient(115deg, transparent 26%, rgba(148,226,213,.6) 45%, rgba(182,146,230,.65) 55%, transparent 74%) !important; background-size: 260% 100% !important; background-position: 200% 0 !important; background-repeat: no-repeat !important; -webkit-mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat !important; mask: url('{{ mark_url|default("/branding/logo.png", true) }}') center / contain no-repeat !important; animation: logo-glint 3s linear infinite !important; }
  .brand .mark.anim-glow .mark-logo { animation: mk-glow 2.6s ease-in-out infinite !important; }
  .brand .mark.anim-glow::before { inset: -14%; border-radius: 50%; background: radial-gradient(circle, rgba(148,226,213,.5), rgba(148,226,213,0) 62%) !important; animation: mk-bloom 2.6s ease-in-out infinite !important; z-index: 3; }
  .brand .mark.anim-twinkle::after { content: '\2726'; width: auto; height: auto; top: -7px; right: -8px; background: none; border-radius: 0; color: var(--gold); font-size: 11px; line-height: 1; text-shadow: -32px 28px 0 rgba(212,175,55,.7), 0 0 6px rgba(212,175,55,.9); animation: mk-tw 1.7s ease-in-out infinite !important; z-index: 7; }
  .brand .mark.anim-shoot::after { content: ''; width: 15px; height: 2px; top: 2px; right: auto; left: -4px; border-radius: 2px; background: linear-gradient(90deg, rgba(255,255,255,0), #fff); box-shadow: 0 0 7px 1px rgba(207,232,255,.9); animation: mk-shoot 2.7s ease-in-out infinite !important; z-index: 7; }
  .brand .mark.anim-halo::before { inset: -12%; border-radius: 50%; background: conic-gradient(from 0deg, transparent 0 68%, rgba(148,226,213,.9) 84%, transparent 100%) !important; -webkit-mask: radial-gradient(circle, transparent 58%, #000 62%, #000 74%, transparent 78%) !important; mask: radial-gradient(circle, transparent 58%, #000 62%, #000 74%, transparent 78%) !important; animation: mk-orbit 3.2s linear infinite !important; z-index: 6; }
  .brand .mark.anim-eclipse::before { inset: 4%; border-radius: 50%; background: radial-gradient(circle at 50% 46%, #10101a 60%, rgba(16,16,26,0) 70%) !important; box-shadow: 0 0 10px 2px rgba(120,90,200,.45); opacity: .92; animation: mk-ecl 4s ease-in-out infinite !important; z-index: 6; }
  .brand .mark.anim-ripple::before { inset: 10%; border-radius: 50%; border: 1.5px solid rgba(148,226,213,.85); box-shadow: 0 0 8px rgba(148,226,213,.5); animation: mk-ripple 2s ease-out infinite !important; z-index: 6; }
  .brand .mark.anim-mist::before { inset: -20%; filter: blur(3px); mix-blend-mode: screen; background: radial-gradient(circle at 32% 38%, rgba(90,230,180,.5), transparent 46%), radial-gradient(circle at 68% 62%, rgba(150,110,240,.5), transparent 46%) !important; animation: mk-mist 6s ease-in-out infinite !important; z-index: 3; }
  .brand .mark.anim-prism .mark-logo { animation: mk-prism 6s linear infinite !important; }
  .brand .mark.anim-breathe .mark-logo { animation: mk-breathe 2.8s ease-in-out infinite !important; }
  .brand .mark.anim-tilt .mark-logo { animation: mk-tilt 4.2s ease-in-out infinite !important; }
  .brand .mark.anim-float .mark-logo { animation: mk-float 3s ease-in-out infinite !important; }
  .brand .mark.anim-orbit .mark-logo { animation: mk-orbit 9s linear infinite !important; }
  @keyframes mk-glow { 0%,100% { filter: brightness(1) drop-shadow(0 0 2px rgba(148,226,213,.2)); } 50% { filter: brightness(1.15) drop-shadow(0 0 9px rgba(148,226,213,.8)); } }
  @keyframes mk-bloom { 0%,100% { opacity: .1; transform: scale(.85); } 50% { opacity: .8; transform: scale(1.05); } }
  @keyframes mk-tw { 0%,100% { opacity: 0; transform: scale(.3) rotate(0deg); } 50% { opacity: 1; transform: scale(1.1) rotate(20deg); } }
  @keyframes mk-shoot { 0% { opacity: 0; transform: translate(-8px,-4px) rotate(28deg); } 12% { opacity: 1; } 45% { opacity: 0; transform: translate(46px,26px) rotate(28deg); } 100% { opacity: 0; } }
  @keyframes mk-ecl { 0% { transform: translateX(-92%); } 50% { transform: translateX(0); } 100% { transform: translateX(92%); } }
  @keyframes mk-ripple { 0% { opacity: .85; transform: scale(.35); } 100% { opacity: 0; transform: scale(1.5); } }
  @keyframes mk-mist { 0%,100% { transform: translate(-6%,2%); } 50% { transform: translate(6%,-4%); } }
  @keyframes mk-prism { to { filter: hue-rotate(360deg); } }
  @keyframes mk-breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.07); } }
  @keyframes mk-tilt { 0%,100% { transform: perspective(300px) rotateY(-10deg); } 50% { transform: perspective(300px) rotateY(10deg); } }
  @keyframes mk-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
  @keyframes mk-orbit { to { transform: rotate(360deg); } }
  header h1 { font-size: 18px; color: var(--text); flex-shrink: 0; font-weight: 600; border-bottom: 2px solid var(--gold); padding-bottom: 1px; line-height: 1.1; }
  .tagline { font-size: 10.5px; color: var(--overlay0); font-style: italic; margin-top: 3px; transition: opacity .5s; letter-spacing: .02em; }
  .ver-badge { font-size: 10px; font-weight: 500; color: var(--overlay0); font-family: ui-monospace, monospace; border: 1px solid var(--surface1); border-radius: 5px; padding: 1px 6px; vertical-align: middle; margin-left: 4px; letter-spacing: 0; }
  .header-stats { color: var(--subtext); font-size: 12px; } .header-stats b { color: var(--text); }
  .gen-live { color: var(--lavender); margin-left: 8px; display:inline-flex; align-items:center; }
  .gen-nel-wrap{position:relative;display:inline-block;width:22px;height:22px;margin-right:5px;vertical-align:middle;flex:none;}
  .gen-nel{position:absolute;inset:3px;width:16px;height:16px;border-radius:50%;object-fit:cover;object-position:60% 32%;}
  .gen-ring{position:absolute;inset:0;border-radius:50%;border:2px solid rgba(182,146,230,.22);border-top-color:var(--lavender);animation:gen-spin .8s linear infinite;}
  @keyframes gen-spin{to{transform:rotate(360deg);}}
  .cover-badge { margin-left: 8px; font-size: 11px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--surface1); cursor: default; }
  .cover-badge b { font-variant-numeric: tabular-nums; }
  .cover-badge.full { color: var(--emerald); border-color: var(--emerald); }
  .cover-badge.high { color: var(--lavender); border-color: var(--surface1); }
  .cover-badge.low  { color: var(--peach); border-color: var(--peach); }
  @media (prefers-reduced-motion: reduce) {
    .brand .mark { animation: none; } .brand .mark::before { animation: none; transform: translateX(-108%); }
    .brand .mark:has(.mark-logo) .mark-logo { animation: none; filter: drop-shadow(0 0 6px rgba(182,146,230,.45)); }
    .brand .mark:has(.mark-logo)::before { animation: none; background-position: 200% 0; }
    .brand .mark:has(.mark-logo)::after { animation: none; opacity: .8; transform: none; }
    /* class-tripled to outrank every per-anim !important rule's specificity */
    .brand .mark.mark.mark .mark-logo, .brand .mark.mark.mark::before, .brand .mark.mark.mark::after { animation: none !important; }
    .tagline { transition: none; }
  }

  /* Filters */
  .filters { background: var(--mantle); padding: 10px 20px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; border-bottom: 1px solid var(--surface0); }
  .filters input, .filters select { background: var(--surface0); color: var(--text); border: 1px solid var(--surface1); border-radius: 6px; padding: 5px 10px; font-size: 13px; }
  .filters input { width: 280px; }
  .filters .f-grow { flex: 0 1 440px; min-width: 200px; } .filters .f-grow input { width: 100%; }
  .filters .filter-actions { margin-left: auto; align-self: flex-end; display: flex; gap: 6px; }
  .filters-adv { border-top: 1px dashed var(--surface1); }
  .filters input:focus, .filters select:focus { outline: none; border-color: var(--accent-soft); box-shadow: 0 0 0 2px rgba(79,201,154,.25); }
  .filters label { color: var(--subtext); font-size: 12px; }
  .filter-toggle { display: none; }
  /* Mobile: collapse the filter bar behind a toggle so the grid leads. */
  @media (max-width: 680px) {
    header h1 { font-size: 16px; }
    header.bannered { padding: 0 14px 10px; }
    header .back-link { font-size: 12px; }
  .head-nav { margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
  .lan-note { font-size: 11.5px; color: var(--overlay0); font-style: italic; padding: 5px 10px; border: 1px dashed var(--surface1); border-radius: 7px; }
    .filter-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 8px 12px 0; }
    .filters { display: none; flex-direction: column; align-items: stretch; padding: 10px 12px; }
    .filters.open { display: flex; }
    .filters > div { width: 100%; }
    .filters input, .filters select { width: 100% !important; box-sizing: border-box; }
    .grid { padding: 10px 12px; gap: 8px; }
    .chips { padding: 8px 12px 0; }
    .filters input, .filters select { font-size: 16px; }  /* >=16px stops iOS zoom-on-focus */
  }
  /* ---- Portrait phones (<=480px): the mobile pass. Layers on top of the 680px rules. ---- */
  @media (max-width: 480px) {
    /* HEADER stays ONE row so the collapsing-banner's slim pinned band still shows the nav.
       Free width (shrink brand, drop tagline + stats) and turn .head-nav into a swipe strip. */
    .brand { flex-shrink: 1; min-width: 0; }
    header h1 { font-size: 15px; }
    .brand .mark { width: 34px; height: 34px; font-size: 18px; }
    .tagline { display: none; }
    .header-stats { display: none; }
    .head-nav { flex: 1 1 auto; min-width: 0; margin-left: 8px; flex-wrap: nowrap;
      justify-content: flex-start; overflow-x: auto; -webkit-overflow-scrolling: touch;
      scrollbar-width: none; gap: 8px; }
    .head-nav::-webkit-scrollbar { display: none; }
    .head-nav > * { flex: 0 0 auto; }
    .head-nav .btn, .acct-chip, .acct-claim { min-height: 40px; display: inline-flex; align-items: center; }

    /* GRID: force a comfortable 2-up; ignore a too-large saved --thumb (else 1 giant column / overflow). */
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 8px; padding: 10px 10px; }
    .card .cb-wrap { top: 0; left: 0; padding: 8px; }
    .card .cb-wrap input[type=checkbox] { width: 26px; height: 26px; }
    .card .sbadge { top: 8px; left: 46px; }
    .card .stars { padding: 6px 8px 8px; gap: 8px; }
    .card .stars button { font-size: 20px; padding: 2px; }
    .card .meta .date { font-size: 11px; }

    /* FILTERS + BULK-BAR: full-width actions, tidy stacked bulk-bar, 44px touch targets. */
    .filters .filter-actions { margin-left: 0; width: 100%; flex-wrap: wrap; gap: 8px; }
    .filters .filter-actions .btn { flex: 1 1 30%; min-height: 44px; justify-content: center; }
    .bulk-bar { padding: 8px 12px; gap: 8px; }
    .bulk-bar .bulk-grp { flex-wrap: wrap; }
    .bulk-bar .bulk-grp + .bulk-grp:not(.bulk-view), .bulk-bar .bulk-actions { border-left: none; padding-left: 0; }
    .bulk-bar .bulk-view { margin-left: 0; width: 100%; }
    .bulk-bar .btn, .bulk-bar #preset-select { min-height: 44px; padding: 10px 14px; font-size: 14px; }
    .bulk-bar .bulk-grp .btn { flex: 1 1 auto; }
    .bulk-bar .actions-menu { left: 8px; right: 8px; min-width: 0; }
    .bulk-tip { display: none; }

    /* DRAWER + LIGHTBOX: full-width sheet, reachable centered model flyout, stacked selects,
       lightbox arrows off the image, touch-sized controls. */
    #gen-drawer, #gen-drawer.wide, #gen-drawer.dock-left, #gen-drawer.dock-right { width: 100%; max-width: 100vw; }
    #model-flyout, #gen-drawer.dock-left #model-flyout, #gen-drawer.dock-right #model-flyout,
    #gen-drawer.dock-top #model-flyout, #gen-drawer.dock-bottom #model-flyout {
      position: fixed; top: 50%; left: 50%; right: auto; bottom: auto; transform: translate(-50%, -50%);
      width: 94vw; max-width: 94vw; max-height: 82vh;
      border: 1px solid var(--surface1); border-radius: 12px; box-shadow: 0 22px 60px rgba(0,0,0,.6); }
    .gen-row { flex-wrap: wrap; } .gen-row > * { flex: 1 1 100%; }
    .dock-ctl button { width: 34px; height: 34px; }
    .gen-head .x { font-size: 28px; min-width: 40px; }
    #lb-img, #lb-video { max-width: 100vw; max-height: 74vh; }
    .lb-nav { top: auto; bottom: 12px; transform: none; min-width: 48px; min-height: 48px; padding: 0;
      display: flex; align-items: center; justify-content: center; font-size: 24px; }
    .lb-prev { left: 12px; } .lb-next { right: 12px; }
    .lb-bar { flex-wrap: wrap; padding: 8px 10px; }
    #lb-caption { max-width: 100%; order: 3; flex-basis: 100%; font-size: 11px; }
    .lb-actions .btn { min-height: 40px; padding: 8px 12px; }
  }
  /* Tablet: keep the filter bar visible but let wide text inputs shrink so the
     row wraps tidily instead of running off-screen. */
  @media (min-width: 681px) and (max-width: 1024px) {
    .filters input { width: 180px; }
    .filters { padding: 10px 14px; }
    .grid { padding: 12px 14px; }
  }
  /* Frosted glow pills ("Moonlight, tinted"): pill-shaped frosted glass with a
     soft per-destination hue (--btn-hue). Generate stays the solid-lavender hero. */
  .btn { background: rgba(255,255,255,.06); color: var(--text); border: 1px solid rgba(182,146,230,.30); border-radius: 999px; padding: 6px 15px; cursor: pointer; font-size: 13px; line-height: 1.2; box-shadow: inset 0 1px 0 rgba(255,255,255,.13), 0 0 9px var(--btn-hue, rgba(182,146,230,.14)); transition: border-color .14s, box-shadow .14s, background .14s, transform .09s; }
  a.btn { text-decoration: none; display: inline-flex; align-items: center; gap: 5px; color: var(--text); }
  .btn:hover { background: rgba(182,146,230,.15); border-color: var(--lavender); transform: translateY(-1px); box-shadow: inset 0 1px 0 rgba(255,255,255,.2), 0 4px 12px -4px rgba(0,0,0,.5), 0 0 14px var(--btn-hue, rgba(182,146,230,.35)); text-decoration: none; }
  .btn:active { transform: translateY(1px); }
  .btn:focus-visible { outline: 2px solid var(--lavender); outline-offset: 1px; }
  .b-loom    { --btn-hue: rgba(148,226,213,.30); }
  .b-ach     { --btn-hue: rgba(212,175,55,.32); }
  .b-contest { --btn-hue: rgba(224,192,106,.30); }
  .b-art     { --btn-hue: rgba(203,166,247,.32); }
  .b-panel   { --btn-hue: rgba(180,190,254,.32); }
  .b-health  { --btn-hue: rgba(245,194,231,.30); }
  .btn-danger { background: var(--red); color: var(--base); border-color: var(--red); font-weight: 600; }
  .btn-danger:hover { opacity: 0.9; background: var(--red); box-shadow: 0 3px 10px -3px rgba(243,139,168,.5); }
  .btn-primary { background: linear-gradient(180deg, #c4a6f0 0%, var(--lavender) 100%); color: var(--base); border-color: var(--lavender); font-weight: 600; }
  .btn-primary:hover { background: linear-gradient(180deg, #c4a6f0 0%, var(--lavender) 100%); box-shadow: 0 0 0 1px rgba(182,146,230,.5), 0 4px 14px -4px rgba(182,146,230,.7); }
  /* All dropdowns share the button look: dark, rounded, custom lavender-grey caret. */
  .filters select, #preset-select, select.p-sel { -webkit-appearance: none; appearance: none;
    background-color: var(--surface0);
    background-image: url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="10" height="6"%3E%3Cpath d="M0 0l5 6 5-6z" fill="%239a93ab"/%3E%3C/svg%3E');
    background-repeat: no-repeat; background-position: right 10px center;
    border: 1px solid var(--surface1); border-radius: 7px; color: var(--text);
    padding: 6px 28px 6px 12px; font-size: 13px; cursor: pointer; font-family: inherit; }
  .filters select:hover, #preset-select:hover, select.p-sel:hover { border-color: var(--lavender); }

  /* Active-filter chips */
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 20px 0; align-items: center; }
  .chips .chips-label { color: var(--overlay0); font-size: 12px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; background: var(--surface0); border: 1px solid var(--surface1); border-left: 3px solid var(--gold); border-radius: 4px; padding: 3px 8px; font-size: 12px; color: var(--text); }
  .chip .k { color: var(--subtext); }
  .chip a { color: var(--overlay0); text-decoration: none; font-weight: 700; padding-left: 2px; }
  .chip a:hover { color: var(--red); }
  .chips .clear-all { color: var(--accent-soft); font-size: 12px; text-decoration: none; }
  .chips .clear-all:hover { text-decoration: underline; }

  /* Bulk toolbar */
  .bulk-bar { background: var(--surface0); padding: 8px 20px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--surface1); min-height: 40px; flex-wrap: wrap; position: sticky; top: var(--bulk-top, 52px); z-index: 99; box-shadow: 0 2px 8px rgba(0,0,0,.25); }
  .bulk-grp { display: flex; align-items: center; gap: 6px; }
  .bulk-grp + .bulk-grp:not(.bulk-view), .bulk-actions { border-left: 1px solid var(--surface1); padding-left: 10px; }
  .bulk-view { margin-left: auto; }
  .sel-count { color: var(--subtext); font-size: 13px; padding: 0 2px; } .sel-count b { color: var(--text); font-variant-numeric: tabular-nums; }
  .bulk-actions { position: relative; }
  .actions-menu { position: absolute; top: calc(100% + 6px); left: 10px; z-index: 130; background: var(--mantle); border: 1px solid var(--surface1); border-radius: 9px; box-shadow: 0 14px 34px rgba(0,0,0,.5); min-width: 210px; padding: 5px; display: none; }
  .actions-menu.open { display: block; }
  .actions-menu button { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 13px; padding: 8px 11px; border-radius: 6px; cursor: pointer; font-family: inherit; }
  .actions-menu button:hover { background: var(--surface0); }
  .actions-menu .am-div { height: 1px; background: var(--surface1); margin: 5px 6px; }
  .actions-menu .am-danger { color: var(--red); }
  .actions-menu .am-danger:hover { background: rgba(243,139,168,.13); }
  .bulk-tip { padding: 5px 20px; font-size: 12px; color: var(--overlay0); background: var(--surface0); border-bottom: 1px solid var(--surface1); }
  /* Select mode: cards capture the drag (no scroll-hijack mid-card) and never open the lightbox. */
  .select-mode .grid .card { touch-action: none; cursor: copy; }
  .select-mode .grid .card .cover { cursor: copy; }
  #select-mode-btn.active { background: var(--accent); color: #1e1e2e; font-weight: 600; }
  body.select-mode .bulk-bar::after { content: "Select mode: tap to toggle · drag across images to paint"; color: var(--accent); font-size: 12px; flex-basis: 100%; }
  .bulk-bar span { color: var(--subtext); font-size: 13px; }
  #sel-count { color: var(--gold); font-weight: 600; }

  /* Thumbnail loading skeleton */
  @keyframes shimmer { 0% { background-position: -200px 0; } 100% { background-position: 200px 0; } }
  .card img { background-image: linear-gradient(90deg, var(--surface0) 0px, var(--surface1) 100px, var(--surface0) 200px); background-size: 400px 100%; animation: shimmer 1.2s infinite linear; }
  .card img.loaded { animation: none; background: var(--surface0); }

  /* Empty state */
  .empty { text-align: center; padding: 64px 20px; color: var(--subtext); }
  .empty .big { font-size: 40px; margin-bottom: 8px; color: var(--overlay0); }
  .empty a { color: var(--accent-soft); text-decoration: none; }
  .empty a:hover { text-decoration: underline; }

  /* Grid */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(var(--thumb, 200px), 1fr)); gap: 12px; padding: 16px 20px; }
  .card { background: var(--mantle); border-radius: 8px; overflow: hidden; border: 2px solid transparent; transition: border-color .15s; position: relative; cursor: pointer; }
  .card:hover { border-color: var(--surface1); }
  .card.selected { border-color: var(--purple-bright); box-shadow: 0 0 0 1px var(--purple-bright); }
  .card.kbd-focus { border-color: var(--accent-soft); box-shadow: 0 0 0 2px var(--accent-soft); }

  /* Lightbox */
  .lb { display: none; position: fixed; inset: 0; z-index: 300; background: rgba(8,6,18,.92);
        flex-direction: column; align-items: center; justify-content: center; }
  .lb.open { display: flex; }
  .lb-bar { position: absolute; top: 0; left: 0; right: 0; display: flex; align-items: center;
            justify-content: space-between; gap: 12px; padding: 10px 16px; background: rgba(10,8,24,.6); }
  #lb-caption { color: var(--subtext); font-size: 12px; overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; max-width: 60%; }
  .lb-actions { display: flex; gap: 8px; flex-shrink: 0; }
  #lb-img { max-width: 94vw; max-height: 86vh; object-fit: contain; border-radius: 6px; }
  #lb-video { max-width: 94vw; max-height: 86vh; border-radius: 6px; background: #000; }
  .lb-nav { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(10,8,24,.5);
            color: var(--text); border: 1px solid var(--surface1); border-radius: 8px; font-size: 28px;
            line-height: 1; padding: 10px 16px; cursor: pointer; }
  .lb-nav:hover { background: var(--surface0); }
  .lb-prev { left: 14px; } .lb-next { right: 14px; }
  @media (max-width: 680px) { .lb-nav { padding: 8px 12px; font-size: 22px; } #lb-caption { max-width: 40%; } }
  .card img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; background: var(--surface0); }
  .card .no-thumb { width: 100%; aspect-ratio: 1; background: var(--surface0); display: flex; align-items: center; justify-content: center; color: var(--overlay0); font-size: 11px; }
  .card .meta { padding: 6px 8px; }
  .card .meta .title { font-size: 12px; color: var(--text); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .meta .model { font-size: 11px; color: var(--mauve); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .meta .date  { font-size: 10px; color: var(--overlay0); }
  /* Privacy blur (opt-in toggle): blur every thumbnail until hover. Useful on
     LAN / mobile / over-the-shoulder. NSFW-flagged cards (data-nsfw="1") blur
     more heavily when the flag is known. */
  body.privacy-blur .card img { filter: blur(16px); transition: filter .12s; }
  body.privacy-blur .card[data-nsfw="1"] img { filter: blur(28px); }
  body.privacy-blur .card:hover img { filter: none; }
  .card .cb-wrap { position: absolute; top: 6px; left: 6px; }
  .card .cb-wrap input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--lavender); cursor: pointer; }
  .card a.cover { position: absolute; inset: 0; z-index: 1; }
  .card .cb-wrap { z-index: 2; }
  .card .vbadge { position: absolute; top: 6px; right: 6px; z-index: 2; background: rgba(0,0,0,.6); color: #fff; font-size: 11px; line-height: 1; padding: 4px 7px; border-radius: 20px; pointer-events: none; }
  .card .sbadge { position: absolute; top: 6px; left: 30px; z-index: 2; font-size: 10px; font-weight: 600; line-height: 1; padding: 3px 6px; border-radius: 4px; pointer-events: none; letter-spacing: .03em; }
  .card .sbadge.gen { background: var(--mauve, #cba6f7); color: #1e1e2e; }
  .card .sbadge.loc { background: var(--teal, #94e2d5); color: #1e1e2e; }

  /* Pagination */
  .pagination { display: flex; justify-content: center; gap: 6px; padding: 20px; flex-wrap: wrap; }
  .pagination a, .pagination span { padding: 6px 12px; border-radius: 6px; font-size: 13px; text-decoration: none; }
  .pagination a { background: var(--surface0); color: var(--text); border: 1px solid var(--surface1); }
  .pagination a:hover { background: var(--surface1); }
  .pagination span.current { background: var(--lavender); color: var(--base); font-weight: 600; border: 1px solid var(--lavender); }
  .pagination span.ellipsis { color: var(--overlay0); }

  /* Detail */
  .detail-wrap { max-width: 1100px; margin: 0 auto; padding: 20px; }
  .detail-img { text-align: center; margin-bottom: 20px; }
  .detail-img img { max-width: 100%; max-height: 70vh; border-radius: 8px; }
  .detail-meta { background: var(--mantle); border-radius: 8px; padding: 16px; display: grid; grid-template-columns: 140px 1fr; gap: 6px 12px; }
  .detail-meta .lbl { color: var(--subtext); font-size: 12px; text-align: right; padding-top: 2px; }
  .detail-meta .val { color: var(--text); font-size: 13px; word-break: break-word; }
  .detail-meta .val.prompt { font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
  .detail-actions { margin-top: 16px; display: flex; gap: 10px; }
  .focus-btn { font-size: 12px; padding: 3px 10px; cursor: pointer; background: var(--surface0); border: 1px solid var(--surface1); border-radius: 4px; color: var(--text); }
  .focus-btn:hover { background: var(--surface1); }
  .focus-mode .detail-meta,
  .focus-mode .detail-stars,
  .focus-mode .detail-actions { display: none; }
  .focus-mode { max-width: 100% !important; padding: 8px !important; display: flex; flex-direction: column; align-items: center; }
  .focus-mode .detail-nav { width: 100%; max-width: 900px; }
  .focus-mode .detail-img { width: 100%; display: flex; justify-content: center; }
  .focus-mode .detail-img img { max-height: 90vh; max-width: 95vw; width: auto; height: auto; }
  @media print {
    @page { size: letter; margin: 12mm; }
    header, .detail-nav, .detail-actions, .detail-stars, #suggest-box, #lightbox { display: none !important; }
    body, .detail-wrap { background: #fff !important; color: #000 !important; }
    .detail-wrap { max-width: 100% !important; padding: 0 !important; }
    .detail-img img { max-width: 100%; max-height: 78vh; width: auto; height: auto; display: block; margin: 0 auto; }
    .detail-meta { background: #fff !important; border: none !important; margin-top: 8mm; grid-template-columns: 130px 1fr; }
    .detail-meta .lbl { color: #555 !important; } .detail-meta .val { color: #000 !important; }
  }
  .back-link { display: inline-block; color: var(--blue); text-decoration: none; font-size: 13px; }
  .back-link:hover { text-decoration: underline; }
  .detail-nav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .nav-arrow { color: var(--blue); text-decoration: none; font-size: 13px; padding: 4px 10px; border: 1px solid var(--surface1); border-radius: 4px; }
  .nav-arrow:hover { background: var(--surface1); text-decoration: none; }
  .nav-disabled { color: var(--overlay0); font-size: 13px; padding: 4px 10px; border: 1px solid var(--surface0); border-radius: 4px; cursor: default; }

  /* Modal */
  .modal-bg { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 200; align-items: center; justify-content: center; }
  .modal-bg.open { display: flex; }
  .modal { background: var(--mantle); border: 1px solid var(--surface1); border-radius: 10px; padding: 24px; max-width: 400px; width: 90%; }
  .modal h2 { font-size: 16px; margin-bottom: 10px; color: var(--red); }
  .modal p { color: var(--subtext); font-size: 13px; margin-bottom: 18px; line-height: 1.5; }
  .modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

  /* Empty */
  .empty { text-align: center; padding: 60px 20px; color: var(--overlay0); }

  /* Stars */
  .stars { display: flex; gap: 2px; }
  .stars button { background: none; border: none; cursor: pointer; font-size: 14px; padding: 0; line-height: 1; color: var(--overlay0); }
  .stars button.on { color: #f9e2af; }
  .stars button:hover { color: #f9e2af; opacity: 0.7; }
  .card .stars { padding: 3px 6px 5px; }
  .detail-stars { margin-top: 12px; display: flex; align-items: center; gap: 8px; }
  .detail-stars .stars button { font-size: 22px; }
  .detail-stars .rating-label { color: var(--subtext); font-size: 12px; }
</style>
<script>
function closeModal() { document.getElementById('del-modal').classList.remove('open'); }
function confirmDelete(url, msg) {
  document.getElementById('del-modal-msg').textContent = msg;
  document.getElementById('del-modal-form').action = url;
  document.getElementById('del-modal').classList.add('open');
}
function setRating(mediaId, value, starsEl) {
  fetch('/rate/' + mediaId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({rating: value})
  }).then(r => r.json()).then(data => {
    if (data.ok) updateStars(starsEl, data.rating);
  });
}
function updateStars(el, rating) {
  el.querySelectorAll('button').forEach(function(btn, i) {
    btn.classList.toggle('on', i < rating);
  });
  var lbl = el.parentElement.querySelector('.rating-label');
  if (lbl) lbl.textContent = rating > 0 ? rating + ' / 5' : 'unrated';
}
function buildStars(mediaId, rating, containerEl) {
  for (var i = 1; i <= 5; i++) {
    (function(star) {
      var btn = document.createElement('button');
      btn.textContent = '★';
      if (star <= rating) btn.classList.add('on');
      btn.addEventListener('click', function(e) {
        e.preventDefault(); e.stopPropagation();
        var newVal = (rating === star) ? 0 : star;
        rating = newVal;
        setRating(mediaId, newVal, containerEl);
      });
      containerEl.appendChild(btn);
    })(i);
  }
}
document.addEventListener('DOMContentLoaded', function() {
  var modal = document.getElementById('del-modal');
  if (modal) modal.addEventListener('click', function(e) { if (e.target === this) closeModal(); });
  document.querySelectorAll('.stars[data-mid]').forEach(function(el) {
    buildStars(el.dataset.mid, parseInt(el.dataset.rating) || 0, el);
  });
});
</script>
</head>
<body>
{% block body %}{% endblock %}

<div class="modal-bg" id="del-modal">
  <div class="modal">
    <h2>Confirm Delete</h2>
    <p id="del-modal-msg">Are you sure?</p>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <form id="del-modal-form" method="post" style="display:inline">
        <button type="submit" class="btn btn-danger">Delete</button>
      </form>
    </div>
  </div>
</div>
<style>
  .ee-star{position:fixed;top:-40px;z-index:400;pointer-events:none;color:var(--lavender);text-shadow:0 0 14px rgba(182,146,230,.9),0 0 30px rgba(182,146,230,.5);animation:ee-fall linear forwards;}
  @keyframes ee-fall{to{transform:translateY(112vh) rotate(540deg);opacity:.05;}}
  .ee-toast{position:fixed;left:50%;top:15%;transform:translate(-50%,-50%);z-index:402;background:var(--mantle);border:1px solid var(--lavender);border-radius:14px;padding:16px 30px;font-size:19px;color:var(--text);text-align:center;box-shadow:0 0 70px rgba(182,146,230,.55);pointer-events:none;animation:ee-toast 6s ease forwards;}
  @keyframes ee-toast{0%{opacity:0;transform:translate(-50%,-50%) scale(.85);}10%{opacity:1;transform:translate(-50%,-50%) scale(1);}82%{opacity:1;}100%{opacity:0;}}
  .ee-scrim{position:fixed;inset:0;z-index:399;background:radial-gradient(circle at 50% 60%,rgba(6,5,14,.32),rgba(6,5,14,.84));pointer-events:none;animation:ee-scrim 6s ease forwards;}
  @keyframes ee-scrim{0%{opacity:0;}10%{opacity:1;}82%{opacity:1;}100%{opacity:0;}}
  .ee-nel{position:fixed;left:50%;bottom:0;transform:translateX(-50%);transform-origin:bottom center;z-index:400;max-height:80vh;max-width:94vw;pointer-events:none;filter:drop-shadow(0 10px 34px rgba(0,0,0,.55)) drop-shadow(0 0 30px rgba(182,146,230,.4));animation:ee-nel 6s cubic-bezier(.18,.9,.2,1.05) forwards;}
  @keyframes ee-nel{0%{opacity:0;transform:translateX(-50%) translateY(30px) scale(.86);}12%{opacity:1;transform:translateX(-50%) translateY(0) scale(1.02);}18%{transform:translateX(-50%) translateY(0) scale(1);}84%{opacity:1;}100%{opacity:0;}}
</style>
<script>
(function(){
  var seq=[38,38,40,40,37,39,37,39,66,65], pos=0, busy=false;
  document.addEventListener('keydown', function(e){
    pos = (e.keyCode===seq[pos]) ? pos+1 : (e.keyCode===seq[0] ? 1 : 0);
    if(pos!==seq.length) return;
    pos=0; if(busy) return; busy=true;
    try{ fetch('/api/ach-event',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({event:'konami'})}); }catch(err){}   // The Konami Code feat
    var g=['✦','✧','★','✪','✺'];
    for(var i=0;i<46;i++){ var s=document.createElement('div'); s.className='ee-star';
      s.textContent=g[i%g.length];
      s.style.left=(Math.random()*100)+'vw';
      s.style.fontSize=(13+Math.random()*24)+'px';
      s.style.animationDuration=(2.2+Math.random()*2.6)+'s';
      s.style.animationDelay=(Math.random()*1.8)+'s';
      document.body.appendChild(s); }
    var scrim=document.createElement('div'); scrim.className='ee-scrim'; document.body.appendChild(scrim);
    var nel=document.createElement('img'); nel.className='ee-nel'; nel.src='/branding/ee_nelstarfall.png';
    nel.onerror=function(){ this.remove(); };   // asset missing -> egg still runs, text-only
    document.body.appendChild(nel);
    var t=document.createElement('div'); t.className='ee-toast';
    t.innerHTML='✺ Elune-adore, Nelnamara ✺<div style="font-size:12.5px;color:var(--subtext);margin-top:7px;">The Athenaeum casts Starfall. Moonfire spam remains a lifestyle.</div>';
    document.body.appendChild(t);
    var cast,loop;   // real WoW Starfall sfx (local); silent if absent or autoplay-blocked
    try{ cast=new Audio('/branding/ee_starfall_cast.ogg'); cast.volume=0.7; cast.play().catch(function(){}); }catch(e){}
    try{ loop=new Audio('/branding/ee_starfall_loop.ogg'); loop.loop=true; loop.volume=0.35; loop.play().catch(function(){}); }catch(e){}
    setTimeout(function(){ document.querySelectorAll('.ee-star,.ee-toast,.ee-nel,.ee-scrim').forEach(function(n){n.remove();});
      try{ if(loop){loop.pause();} }catch(e){} try{ if(cast){cast.pause();} }catch(e){} busy=false; }, 7000);
  });
})();
</script>
</body>
</html>
""".replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS)

    INDEX_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
{% macro date_select(prefix, value, years) %}
  {% set yr = value[:4] %}{% set mo = value[5:7] %}
  <select name="{{ prefix }}_year" style="width:78px">
    <option value="">Year</option>
    {% for y in years %}
    <option value="{{ y }}" {% if value and y|string == yr %}selected{% endif %}>{{ y }}</option>
    {% endfor %}
  </select>
  <select name="{{ prefix }}_month" style="width:64px">
    <option value="">Mon</option>
    {% for mnum in range(1, 13) %}
    {% set mm = '%02d'|format(mnum) %}
    <option value="{{ mm }}" {% if mm == mo %}selected{% endif %}>{{ mm }}</option>
    {% endfor %}
  </select>
{% endmacro %}
<header{% if has_banner %} class="bannered"{% endif %}>
  <img id="brand-banner" src="/branding/banner.png" alt="" onerror="this.remove()">
  <div class="brand">
    <span class="mark anim-{{ mark_anim|default('classic', true) }}{% if mark_kind == 'tile' %} mk-tile{% endif %}"><span class="mark-m">M</span><img class="mark-logo" src="{{ mark_url|default('/branding/logo.png', true) }}" alt="" onerror="this.remove()"></span>
    <div class="brand-txt">
      <h1>Moonglade Athenaeum <span class="ver-badge" title="Running build (git short SHA). If this doesn't change after a pull, the server wasn't restarted.">{{ build_stamp }}</span></h1>
      <span id="tagline" class="tagline">a library against the Void</span>
    </div>
  </div>
  <span class="header-stats">
    <b>{{ '{:,}'.format(stats.images) }}</b> images{% if stats.videos %} &middot; <b>{{ '{:,}'.format(stats.videos) }}</b> videos{% endif %}{% if stats.collections %} &middot; <b>{{ stats.collections }}</b> collections{% endif %}
    <span id="cover-badge" class="cover-badge" style="display:none;"></span>
    <span id="gen-live" class="gen-live" style="display:none;"></span>
  </span>
  <div class="head-nav">
    {# Owner-only surfaces (generation, The Loom, Panel, balance) are localhost-gated -- on a
       LAN-served instance they'd 403 for other devices, so hide them there and show a small
       read-only note instead of dead buttons. Browse/curate + community stay available. #}
    {% if is_local %}
    <a id="acct-chip" class="acct-chip" href="{{ url_for('panel') }}" title="Your PixAI balance — open the Control Panel" style="display:none;"></a>
    <button type="button" id="acct-claim" class="acct-claim" onclick="Acct.claim()" title="Claim your free daily credits" style="display:none;"></button>
    <button type="button" class="btn btn-primary" onclick="Gen.open()">&#10022; Generate</button>
    <a class="btn b-loom" href="/loom" title="The Loom — video storyboard, where shots are woven into a sequence">&#9648; The Loom</a>
    {% endif %}
    <button type="button" class="btn b-ach" onclick="Ach.open()" title="Achievements &amp; skins">&#127942;</button>
    <button type="button" class="btn b-contest" onclick="Contests.open()" title="Live PixAI contests &mdash; the Oasis was never a 1-player game">&#127941; Contests</button>
    <button type="button" class="btn b-art" onclick="YourArt.open()" title="How your published art is doing &mdash; views, likes, comments">&#128200; My Art</button>
    {% if is_local %}
    <a class="btn b-panel" href="{{ url_for('panel') }}" title="Maintenance jobs, logs, settings">&#9881; Panel</a>
    {% else %}
    <span class="lan-note" title="Creation &amp; maintenance tools live on the owner's machine (localhost).">&#128065; read-only LAN view</span>
    {% endif %}
    <a class="btn b-health" href="{{ url_for('health') }}" title="Collection health dashboard">&#9825; Health</a>
  </div>
</header>

<button type="button" class="filter-toggle btn" onclick="toggleFilters()"
        aria-expanded="false">Filters &#9662;</button>
<form method="get" action="/" id="filter-form">
{% set adv_active = model_filter or lora_filter or date_from or date_to or batch_filter or rating_min or art_tag or source_filter or published_only %}
<div class="filters">
  <div class="f-grow">
    <label>Search prompt</label><br>
    <input type="text" name="q" value="{{ q }}" placeholder="words, night* wildcard…"
           title="Multiple words are ANDed. Use * (any) and ? (one char), e.g. night* elf">
  </div>
  <div>
    <label>Media</label><br>
    <select name="media">
      <option value="" {% if not media_type %}selected{% endif %}>All</option>
      <option value="image" {% if media_type=='image' %}selected{% endif %}>Images</option>
      <option value="video" {% if media_type=='video' %}selected{% endif %}>Videos</option>
    </select>
  </div>
  <div>
    <label>Collection</label><br>
    <select name="collection">
      <option value="">All</option>
      {% for c in collections %}
      <option value="{{ c }}" {% if collection==c %}selected{% endif %}>{{ c }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label>Sort</label><br>
    <select name="sort">
      <option value="newest"      {% if sort=='newest' %}selected{% endif %}>Newest first</option>
      <option value="oldest"      {% if sort=='oldest' %}selected{% endif %}>Oldest first</option>
      <option value="rating_desc" {% if sort=='rating_desc' %}selected{% endif %}>Rating ↓</option>
      <option value="rating_asc"  {% if sort=='rating_asc' %}selected{% endif %}>Rating ↑</option>
      <option value="model"       {% if sort=='model' %}selected{% endif %}>Model name</option>
      <option value="pixels"      {% if sort=='pixels' %}selected{% endif %}>Resolution ↓</option>
      <option value="aspect"      {% if sort=='aspect' %}selected{% endif %}>Aspect (wide→tall)</option>
      <option value="aes_desc"    {% if sort=='aes_desc' %}selected{% endif %}>Aesthetic score ↓</option>
      <option value="aes_asc"     {% if sort=='aes_asc' %}selected{% endif %}>Aesthetic score ↑</option>
      <option value="likes"       {% if sort=='likes' %}selected{% endif %}>Most liked</option>
      <option value="width"       {% if sort=='width' %}selected{% endif %}>Width ↓</option>
      <option value="height"      {% if sort=='height' %}selected{% endif %}>Height ↓</option>
    </select>
  </div>
  <div>
    <label>Thumb size</label><br>
    <input type="range" id="thumb-size" min="120" max="320" step="20" value="200"
           title="Thumbnail size" style="width:110px;vertical-align:middle">
  </div>
  <div>
    <label>Per page</label><br>
    <select name="per_page">
      {% for n in per_page_opts %}
      <option value="{{ n }}" {% if n == per_page %}selected{% endif %}>{{ n }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="filter-actions">
    <button type="submit" class="btn btn-primary">Filter</button>
    <a href="/" class="btn">Reset</a>
    <button type="button" class="btn" id="adv-toggle" onclick="toggleAdvanced()"
      aria-expanded="{{ 'true' if adv_active else 'false' }}">{{ 'Less ▴' if adv_active else 'More ▾' }}</button>
  </div>
</div>
<div class="filters filters-adv" id="filters-adv" {% if not adv_active %}style="display:none;"{% endif %}>
  <div>
    <label>Model</label><br>
    <input type="text" name="model" value="{{ model_filter }}" list="models-list"
           placeholder="All models — type to search" autocomplete="off" style="width:200px">
    <datalist id="models-list">
      {% for m in models %}<option value="{{ m }}">{% endfor %}
    </datalist>
  </div>
  <div>
    <label>LoRA</label><br>
    <input type="text" name="lora" value="{{ lora_filter }}" placeholder="lora name…" style="width:140px">
  </div>
  <div>
    <label>From</label><br>
    {{ date_select('from', date_from, years) }}
  </div>
  <div>
    <label>To</label><br>
    {{ date_select('to', date_to, years) }}
  </div>
  {% if batches %}
  <div>
    <label>Batch</label><br>
    <input type="text" name="batch" value="{{ batch_filter }}" list="batches-list"
           placeholder="All batches — type to search" autocomplete="off" style="width:200px">
    <datalist id="batches-list">
      {% for b in batches %}<option value="{{ b }}">{% endfor %}
    </datalist>
  </div>
  {% endif %}
  <div>
    <label>Min rating</label><br>
    <select name="rating_min">
      <option value="0" {% if rating_min==0 %}selected{% endif %}>Any</option>
      {% for r in [1,2,3,4,5] %}
      <option value="{{ r }}" {% if rating_min==r %}selected{% endif %}>{{ '★' * r }}+</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label>Tag / contest</label><br>
    <input type="text" name="tag" value="{{ art_tag }}" placeholder="published tag…" style="width:140px">
  </div>
  <div>
    <label>Source</label><br>
    <select name="source">
      <option value="" {% if not source_filter %}selected{% endif %}>All</option>
      <option value="online" {% if source_filter=='online' %}selected{% endif %}>PixAI history</option>
      <option value="api" {% if source_filter=='api' %}selected{% endif %}>Generated</option>
      <option value="local" {% if source_filter=='local' %}selected{% endif %}>Imported</option>
      <option value="deleted" {% if source_filter=='deleted' %}selected{% endif %}>Deleted on PixAI</option>
    </select>
  </div>
  <div>
    <label>&nbsp;</label><br>
    <label style="color:var(--text);font-size:13px;display:inline-flex;align-items:center;gap:6px;">
      <input type="checkbox" name="published" value="1" {% if published_only %}checked{% endif %}
             style="width:auto;"> Published only
    </label>
  </div>
</div>
</form>

{% if chips %}
<div class="chips">
  <span class="chips-label">Active:</span>
  {% for c in chips %}
  <span class="chip"><span class="k">{{ c.k }}:</span> {{ c.v }}
    <a href="{{ c.url }}" title="Remove this filter">×</a></span>
  {% endfor %}
  <a class="clear-all" href="{{ url_for('index') }}">Clear all</a>
</div>
{% endif %}

{% if request.args.get('replaced') %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--green);border-radius:4px;color:var(--text);font-size:13px;">
  Replaced text in {{ request.args.get('replaced') }} prompt(s).</div>
{% endif %}
{% if request.args.get('collected') %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--emerald, #4fc99a);border-radius:4px;color:var(--text);font-size:13px;">
  Added {{ request.args.get('collected') }} image(s) to the collection.</div>
{% endif %}
{% if request.args.get('deleted') %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--red);border-radius:4px;color:var(--text);font-size:13px;">
  Deleted {{ request.args.get('deleted') }} task(s) from PixAI · {{ request.args.get('removed') }} local file(s) purged{% if request.args.get('failed') and request.args.get('failed') != '0' %} · <span style="color:var(--red);">{{ request.args.get('failed') }} failed</span>{% endif %}.</div>
{% endif %}
{% if request.args.get('delerr') %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--red);border-radius:4px;color:var(--text);font-size:13px;">
  Delete error: {{ request.args.get('delerr') }}</div>
{% endif %}
{% if request.args.get('bulkdel') == 'started' %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--lavender);border-radius:4px;color:var(--text);font-size:13px;">
  <span class="gen-moon"></span> Deleting {{ request.args.get('n') }} item(s) from PixAI&hellip; watch the Activity card. This page refreshes when it finishes.</div>
<script>
// The delete runs in the background (Activity card shows progress). Poll the job log and,
// once the delete job finishes, reload the grid so it stops showing rows that were purged.
(function(){
  var tries=0;
  function reloadClean(){
    var p=new URLSearchParams(location.search); p.delete('bulkdel'); p.delete('n');
    var qs=p.toString();
    location.replace(location.pathname + (qs ? ('?'+qs) : ''));
  }
  function chk(){
    tries++;
    fetch('/api/jobs').then(function(r){return r.json();}).then(function(d){
      var j=((d&&d.jobs)||[]).filter(function(x){return x.type==='delete';})[0];
      if(j && (j.status==='done' || j.status==='failed')){ reloadClean(); return; }
      if(tries<150){ setTimeout(chk, 800); }
    }).catch(function(){ if(tries<150){ setTimeout(chk, 1500); } });
  }
  setTimeout(chk, 800);
})();
</script>
{% endif %}

<div class="bulk-bar">
  <!-- Selection -->
  <div class="bulk-grp">
    <button class="btn" onclick="selectAll()">Select all</button>
    <button class="btn" onclick="clearAll()">Clear</button>
    <button class="btn" id="select-mode-btn" onclick="toggleSelectMode()" title="Select mode: tap an image to toggle it, or drag across images to paint a selection. No lightbox opens. Great for touch/tablet.">Select</button>
    <span class="sel-count"><b id="sel-count">0</b> selected</span>
  </div>
  <!-- Actions on the selection (only shown when something is selected) -->
  <div class="bulk-actions" id="bulk-actions" style="display:none;">
    <button class="btn btn-primary" id="actions-btn" onclick="toggleActionsMenu(event)">Actions <span id="act-n"></span> &#9662;</button>
    <div class="actions-menu" id="actions-menu">
      <button onclick="bulkAddCollection();closeActionsMenu()">&#43; Add to collection</button>
      <button onclick="bulkSendVideo();closeActionsMenu()">&#9654; Send to Video</button>
      <button onclick="bulkSendCast();closeActionsMenu()">&#9648; Send to The Loom (cast)</button>
      <button onclick="bulkContactSheet();closeActionsMenu()">&#128424; Print sheet</button>
      <button onclick="downloadZip();closeActionsMenu()">&#8681; Download ZIP</button>
      <button onclick="bulkReplacePrompt();closeActionsMenu()">Find / replace in prompts</button>
      <div class="am-div"></div>
      <button class="am-danger" onclick="confirmBulkDelete();closeActionsMenu()" title="Remove from this local catalog only (keeps the cloud task)">Delete locally</button>
      <button class="am-danger" onclick="confirmBulkDeleteCloud();closeActionsMenu()" title="Delete the whole TASK from your PixAI account AND locally (irreversible)">Delete from PixAI</button>
    </div>
  </div>
  <!-- View controls (right) -->
  <div class="bulk-grp bulk-view">
    <button class="btn" id="blur-btn" onclick="toggleBlur()" title="Privacy blur: blur all thumbnails until you hover">Privacy blur</button>
    <select id="preset-select" onchange="loadPreset(this.value)" style="font-size:13px;"
            title="Saved views"><option value="">Saved views…</option></select>
    <button class="btn" onclick="savePreset()" title="Save current filters as a named view">Save view</button>
  </div>
</div>
<div class="bulk-tip">tip: click an image to open the lightbox &middot; arrow keys to browse &middot; F for slideshow</div>

<form id="bulk-form" method="post" action="/delete-bulk">
  <input type="hidden" name="back" value="{{ request.url }}">
  <div class="grid">
    {% for row in rows %}
    <div class="card" id="card-{{ row.media_id }}" data-mid="{{ row.media_id }}"
         data-prompt="{{ (row.title or row.prompt_preview or '')|e }}"
         {% if row.is_video == '1' %}data-video="1"{% endif %}
         {% if row.is_nsfw == '1' %}data-nsfw="1"{% endif %}>
      <div class="cb-wrap">
        <input type="checkbox" name="media_ids" value="{{ row.media_id }}"
               onchange="onCheck()" onclick="event.stopPropagation()">
      </div>
      <a class="cover" href="{{ url_for('detail', media_id=row.media_id, back=current_url) }}"
         data-idx="{{ loop.index0 }}" onclick="return openLightbox(event, {{ loop.index0 }})"></a>
      {% if row._has_thumb %}
      <img src="{{ url_for('thumb', media_id=row._thumb_mid) }}" loading="lazy"
           decoding="async" onload="this.classList.add('loaded')"
           alt="{{ row.prompt_preview[:60] }}">
      {% else %}
      <div class="no-thumb">no preview</div>
      {% endif %}
      {% if row.is_video == '1' %}<div class="vbadge" title="Video">▶</div>{% endif %}
      {% if row.source == 'api' %}<div class="sbadge gen" title="Generated via PixAI">AI</div>
      {% elif row.source == 'local' %}<div class="sbadge loc" title="Imported local file">local</div>{% endif %}
      <div class="meta">
        {% if row.title %}<div class="title" title="{{ row.title }}">{{ row.title }}</div>{% endif %}
        <div class="model">{{ row.model_name or row.model_id or '—' }}</div>
        <div class="date">{{ row.created_at[:10] if row.created_at else '' }}{% if row.liked_count and row.liked_count not in ('0','') %} · ♥ {{ row.liked_count }}{% endif %}</div>
      </div>
      <div class="stars" id="stars-{{ row.media_id }}"
           data-mid="{{ row.media_id }}" data-rating="{{ row.rating or 0 }}"></div>
    </div>
    {% endfor %}
  </div>
</form>

<div id="lightbox" class="lb" onclick="if(event.target===this)closeLightbox()">
  <div class="lb-bar">
    <span id="lb-caption"></span>
    <span class="lb-actions">
      <button class="btn" onclick="lbEdit()" title="Open in the Edit tab">✎ Edit</button>
      <button class="btn" onclick="lbVideo()" title="Send to the Video tab as a reference">▶ To Video</button>
      <button class="btn" onclick="lbSimilar()" title="Find visually similar images">✧ Similar</button>
      <a id="lb-details" class="btn" href="#">Details</a>
      <button class="btn" id="lb-play" onclick="toggleSlideshow()">▶ Slideshow</button>
      <button class="btn" onclick="closeLightbox()">✕ Close</button>
    </span>
  </div>
  <button class="lb-nav lb-prev" onclick="lbStep(-1)" aria-label="Previous">&#8249;</button>
  <img id="lb-img" alt="">
  <video id="lb-video" controls loop playsinline style="display:none"></video>
  <button class="lb-nav lb-next" onclick="lbStep(1)" aria-label="Next">&#8250;</button>
</div>

{% if not rows %}
<div class="empty">
  <div class="big">⌕</div>
  <div>No images match your filters.</div>
  {% if chips %}<div style="margin-top:8px;font-size:13px;">Try <a href="{{ url_for('index') }}">clearing all filters</a> or widening the date range.</div>{% endif %}
</div>
{% endif %}

<div class="pagination">
  {% if page > 1 %}
  <a href="{{ page_url(1) }}">« First</a>
  <a id="pg-prev" href="{{ page_url(page - 1) }}">‹ Prev</a>
  {% endif %}
  {% for p in page_range %}
    {% if p == '…' %}
    <span class="ellipsis">…</span>
    {% elif p == page %}
    <span class="current">{{ p }}</span>
    {% else %}
    <a href="{{ page_url(p) }}">{{ p }}</a>
    {% endif %}
  {% endfor %}
  {% if page < total_pages %}
  <a id="pg-next" href="{{ page_url(page + 1) }}">Next ›</a>
  <a href="{{ page_url(total_pages) }}">Last »</a>
  {% endif %}
</div>

<script>
function toggleFilters() {
  var f = document.querySelector('.filters');
  var btn = document.querySelector('.filter-toggle');
  var open = f.classList.toggle('open');
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function toggleAdvanced() {
  var a = document.getElementById('filters-adv');
  var btn = document.getElementById('adv-toggle');
  var open = a.style.display === 'none';
  a.style.display = open ? '' : 'none';
  btn.innerHTML = open ? 'Less \\u25b2' : 'More \\u25be';
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function applyBlur() {
  var on = localStorage.getItem('gallery_privacy_blur') === '1';
  document.body.classList.toggle('privacy-blur', on);
  var b = document.getElementById('blur-btn');
  if (b) b.textContent = on ? 'Unblur' : 'Privacy blur';
}
function toggleBlur() {
  var on = localStorage.getItem('gallery_privacy_blur') === '1';
  localStorage.setItem('gallery_privacy_blur', on ? '' : '1');
  applyBlur();
}
function presetsGet() { try { return JSON.parse(localStorage.getItem('gallery_presets') || '{}'); } catch(e) { return {}; } }
function refreshPresets() {
  var s = document.getElementById('preset-select'); if (!s) return;
  var p = presetsGet();
  s.innerHTML = '<option value="">Saved views…</option>';
  Object.keys(p).forEach(function(n){ var o = document.createElement('option'); o.value = n; o.textContent = n; s.appendChild(o); });
}
function savePreset() {
  var n = prompt('Name this view (the current filters):'); if (!n) return;
  var p = presetsGet(); p[n] = location.search || '?';
  localStorage.setItem('gallery_presets', JSON.stringify(p)); refreshPresets();
}
function loadPreset(n) {
  if (!n) return;
  if (n.charAt(0) === '✕') { // not used; reserved
    return;
  }
  var p = presetsGet();
  if (p[n] !== undefined) location.href = '/' + p[n];
}
(function(){
  // On mobile, auto-open the filter bar if any filter is active so the user sees
  // what's applied; otherwise keep it collapsed to give the grid the screen.
  if (window.matchMedia('(max-width: 680px)').matches &&
      document.querySelector('.chips')) {
    var f = document.querySelector('.filters');
    if (f) f.classList.add('open');
  }
  var grid = document.querySelector('.grid');
  var slider = document.getElementById('thumb-size');
  if (grid && slider) {
    var saved = localStorage.getItem('gallery_thumb');
    if (saved) { slider.value = saved; grid.style.setProperty('--thumb', saved + 'px'); }
    slider.addEventListener('input', function(){
      grid.style.setProperty('--thumb', slider.value + 'px');
      localStorage.setItem('gallery_thumb', slider.value);
    });
  }
})();
/* ---- Cross-page selection (persisted in localStorage) ---- */
function selGet() { try { return new Set(JSON.parse(localStorage.getItem('gallery_sel') || '[]')); } catch(e) { return new Set(); } }
function selSave(s) { localStorage.setItem('gallery_sel', JSON.stringify([...s])); }
// A fresh browser session starts with a CLEAN selection. Selection persists across the
// gallery's full-page-reload pagination (that's the one reason it lives in localStorage),
// but a new tab/session must not inherit a stale selection from a previous visit.
// sessionStorage is wiped when the tab closes, so its absence marks a new session.
(function(){ try { if(!sessionStorage.getItem('gallery_sel_session')){ localStorage.removeItem('gallery_sel'); sessionStorage.setItem('gallery_sel_session','1'); } } catch(e) {} })();
function refreshSelUI() {
  var sel = selGet();
  document.querySelectorAll('input[name=media_ids]').forEach(function(cb){
    var on = sel.has(cb.value);
    cb.checked = on;
    cb.closest('.card').classList.toggle('selected', on);
  });
  document.getElementById('sel-count').textContent = sel.size;
  // One "Actions" button holds every selection action; it appears only when
  // something's selected (replaces the old row of individually-toggled buttons).
  var ba = document.getElementById('bulk-actions');
  if (ba) ba.style.display = sel.size ? '' : 'none';
  var an = document.getElementById('act-n');
  if (an) an.textContent = sel.size ? '(' + sel.size + ')' : '';
  if (!sel.size) closeActionsMenu();
}
function toggleActionsMenu(e) {
  if (e) e.stopPropagation();
  document.getElementById('actions-menu').classList.toggle('open');
}
function closeActionsMenu() {
  var m = document.getElementById('actions-menu');
  if (m) m.classList.remove('open');
}
document.addEventListener('click', function(e) {
  var w = document.getElementById('bulk-actions');
  if (w && !w.contains(e.target)) closeActionsMenu();
});
function bulkContactSheet() {
  var ids = Array.from(selGet());
  if (!ids.length) return;
  window.open('/contact-sheet?ids=' + encodeURIComponent(ids.join(',')), '_blank');
}
function bulkSendCast() {
  var ids = [];
  selGet().forEach(function(mid){
    var card = document.getElementById('card-'+mid);
    if (card && card.getAttribute('data-video') === '1') return;   // cast is images
    ids.push(mid);
  });
  if (!ids.length) return;
  localStorage.removeItem('gallery_sel');   // selection is consumed into the Loom cast
  window.location.href = '/loom?cast=' + encodeURIComponent(ids.join(','));
}
function onCheck() {
  var sel = selGet();
  document.querySelectorAll('input[name=media_ids]').forEach(function(cb){
    if (cb.checked) sel.add(cb.value); else sel.delete(cb.value);
  });
  selSave(sel); refreshSelUI();
}
function selectAll() {
  var sel = selGet();
  document.querySelectorAll('input[name=media_ids]').forEach(function(cb){ sel.add(cb.value); });
  selSave(sel); refreshSelUI();
}
function clearAll() { selSave(new Set()); refreshSelUI(); }
/* ---- Select mode + drag-paint multi-select (mouse + touch via Pointer Events) ---- */
var selectMode = localStorage.getItem('gallery_selmode') === '1';
function applySelectMode() {
  document.body.classList.toggle('select-mode', selectMode);
  var b = document.getElementById('select-mode-btn');
  if (b) { b.classList.toggle('active', selectMode); b.textContent = selectMode ? 'Select: ON' : 'Select'; }
}
function toggleSelectMode() {
  selectMode = !selectMode;
  localStorage.setItem('gallery_selmode', selectMode ? '1' : '');
  applySelectMode();
}
(function() {
  var painting = false, paintVal = true, paintSet = null, lastCard = null;
  function cardAt(x, y) { var el = document.elementFromPoint(x, y); return el ? el.closest('.card') : null; }
  function paint(card) {
    if (!card || card === lastCard || !paintSet) return;
    lastCard = card;
    var mid = card.dataset.mid;
    if (paintVal) paintSet.add(mid); else paintSet.delete(mid);
    card.classList.toggle('selected', paintVal);
    var cb = card.querySelector('input[name=media_ids]'); if (cb) cb.checked = paintVal;
    var c = document.getElementById('sel-count'); if (c) c.textContent = paintSet.size;
  }
  document.addEventListener('pointerdown', function(e) {
    if (!selectMode || !e.target.closest) return;
    var card = e.target.closest('.card');
    if (!card || e.target.closest('.cb-wrap')) return;   // empty space scrolls; checkbox handles itself
    painting = true; lastCard = null;
    paintSet = selGet();
    paintVal = !paintSet.has(card.dataset.mid);           // first card sets paint direction
    paint(card);
    e.preventDefault();
  });
  document.addEventListener('pointermove', function(e) {
    if (!painting) return;
    paint(cardAt(e.clientX, e.clientY));
    e.preventDefault();
  });
  function endPaint() {
    if (!painting) return;
    painting = false;
    if (paintSet) { selSave(paintSet); refreshSelUI(); }
    paintSet = null; lastCard = null;
  }
  document.addEventListener('pointerup', endPaint);
  document.addEventListener('pointercancel', endPaint);
  // Swallow the click so the lightbox / detail link never fires in select mode (images and videos).
  document.addEventListener('click', function(e) {
    if (!selectMode || !e.target.closest) return;
    var card = e.target.closest('.card');
    if (!card || e.target.closest('.cb-wrap')) return;
    e.preventDefault(); e.stopPropagation();
  }, true);
})();
function downloadZip() {
  var sel = [...selGet()];
  if (!sel.length) return;
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/export-zip';
  sel.forEach(function(mid){
    var i = document.createElement('input');
    i.type = 'hidden'; i.name = 'media_ids'; i.value = mid; f.appendChild(i);
  });
  document.body.appendChild(f); f.submit(); f.remove();
}
function bulkReplacePrompt() {
  var sel = [...selGet()];
  if (!sel.length) return;
  var find = prompt('Find this text in the prompts of ' + sel.length + ' selected image(s):');
  if (find === null || find === '') return;
  var repl = prompt('Replace "' + find + '" with: (leave blank to delete it)');
  if (repl === null) return;
  if (!confirm('Replace "' + find + '" with "' + repl + '" across ' + sel.length + ' prompt(s)? This edits catalog.db.')) return;
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/bulk-replace-prompt';
  function add(n, v){ var i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); }
  add('back', location.href); add('find', find); add('replace', repl);
  sel.forEach(function(mid){ add('media_ids', mid); });
  localStorage.removeItem('gallery_sel');   // consume the selection after the edit commits
  document.body.appendChild(f); f.submit();
}
function bulkAddCollection() {
  var sel = [...selGet()];
  if (!sel.length) { alert('Select one or more images/videos first (check the boxes, or "Select All (page)"), then click + Add to Collection.'); return; }
  var name = prompt('Add ' + sel.length + ' image(s) to which collection? (a name; files are NOT moved)');
  if (name === null || !name.trim()) return;
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/collection-add';
  function add(n, v){ var i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); }
  add('back', location.href); add('name', name.trim());
  sel.forEach(function(mid){ add('media_ids', mid); });
  localStorage.removeItem('gallery_sel');   // consume the selection so the NEXT collection starts fresh
  document.body.appendChild(f); f.submit();
}
function confirmBulkDelete() {
  var ids = [...selGet()];
  if (!ids.length) return;
  confirmDelete('/delete-bulk', 'Remove ' + ids.length + ' image' + (ids.length !== 1 ? 's' : '') + ' from the local catalog? Files move to the _deleted/ folder (recoverable); the cloud task is untouched.');
  document.getElementById('del-modal-form').onsubmit = function() {
    var bf = document.getElementById('bulk-form');
    // ensure all cross-page selections are submitted, not just this page's
    ids.forEach(function(mid){
      if (!bf.querySelector('input[name=media_ids][value="' + mid + '"]')) {
        var i = document.createElement('input');
        i.type = 'hidden'; i.name = 'media_ids'; i.value = mid; bf.appendChild(i);
      }
    });
    localStorage.removeItem('gallery_sel');
    bf.submit(); return false;
  };
  document.getElementById('del-modal-form').action = '#';
}
function confirmBulkDeleteCloud() {
  var ids = [...selGet()];
  if (!ids.length) return;
  if (!confirm('Delete ' + ids.length + ' selected image(s) from your PixAI account AND locally?\\n\\n'
    + '⚠ This deletes the whole TASK for each selection (all images in a batch), '
    + 'from the cloud AND your backup. It is IRREVERSIBLE.')) return;
  var typed = prompt('This permanently deletes from PixAI. Type DELETE to confirm:');
  if (typed !== 'DELETE') { alert('Cancelled.'); return; }
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/delete-tasks-bulk';
  function add(n, v){ var i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); }
  add('back', location.href);
  ids.forEach(function(mid){ add('media_ids', mid); });
  localStorage.removeItem('gallery_sel');
  document.body.appendChild(f); f.submit();
}

/* ---- Lightbox + keyboard navigation ---- */
var lbCards = [], lbIdx = -1, lbTimer = null, lbZoom = false;
function lbUrl(mid) { return '/full/' + mid; }
function openLightbox(ev, idx) {
  if (ev) { if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return true; ev.preventDefault(); }
  lbCards = Array.from(document.querySelectorAll('.card'));
  if (!lbCards.length) return false;
  lbIdx = idx;
  lbShow();
  document.getElementById('lightbox').classList.add('open');
  return false;
}
function lbShow() {
  var card = lbCards[lbIdx]; if (!card) return;
  var mid = card.dataset.mid;
  var im = document.getElementById('lb-img');
  var vid = document.getElementById('lb-video');
  lbZoom = false; im.style.transform = '';      // reset zoom on navigate
  if (card.dataset.video === '1') {
    im.style.display = 'none'; im.removeAttribute('src');
    vid.style.display = '';
    vid.onerror = function(){                   // surface the real reason on mobile (MediaError code)
      var c = (vid.error && vid.error.code) || '?';
      document.getElementById('lb-caption').textContent =
        "Video won't play (error " + c + ") — open Details to download it.";
    };
    vid.src = '/video-file/' + mid;
    vid.load();                                // iOS Safari requires load() after a src change
    // NOTE: do NOT set currentTime here — seeking before metadata loads throws on iOS.
    vid.play().catch(function(){});            // autoplay may be blocked; controls still work
  } else {
    vid.onerror = null;
    vid.pause(); vid.removeAttribute('src'); vid.load(); vid.style.display = 'none';
    im.style.display = '';
    im.src = lbUrl(mid);
  }
  document.getElementById('lb-caption').textContent =
    (lbIdx + 1) + ' / ' + lbCards.length + '   ' + (card.dataset.prompt || '');
  document.getElementById('lb-details').href = '/image/' + mid + '?back=' + encodeURIComponent(location.href);
}
function lbNavUrl(href, where) {
  return href + (href.indexOf('?') >= 0 ? '&' : '?') + 'lbopen=' + where;
}
function lbStep(d) {
  if (!lbCards.length) return;
  var ni = lbIdx + d;
  if (ni >= lbCards.length) {           // past the last card -> next page (open at its first)
    var nx = document.getElementById('pg-next');
    if (nx) { saveScrollPos(); location.href = lbNavUrl(nx.href, 'first'); return; }
    ni = 0;                              // last page: wrap within the page
  } else if (ni < 0) {                   // before the first card -> previous page (open at its last)
    var pv = document.getElementById('pg-prev');
    if (pv) { saveScrollPos(); location.href = lbNavUrl(pv.href, 'last'); return; }
    ni = lbCards.length - 1;             // first page: wrap within the page
  }
  lbIdx = ni; lbShow();
}
function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  var vid = document.getElementById('lb-video');
  if (vid) { vid.pause(); vid.removeAttribute('src'); vid.load(); }
  stopSlideshow();
}
function toggleSlideshow() { lbTimer ? stopSlideshow() : startSlideshow(); }
function startSlideshow() {
  lbTimer = setInterval(function(){ lbStep(1); }, 3000);
  document.getElementById('lb-play').textContent = '❚❚ Pause';
}
function stopSlideshow() {
  if (lbTimer) { clearInterval(lbTimer); lbTimer = null; }
  var b = document.getElementById('lb-play'); if (b) b.textContent = '▶ Slideshow';
}
var kbdIdx = -1;
function kbdFocus(i) {
  var cards = document.querySelectorAll('.card'); if (!cards.length) return;
  if (kbdIdx >= 0 && cards[kbdIdx]) cards[kbdIdx].classList.remove('kbd-focus');
  kbdIdx = Math.max(0, Math.min(i, cards.length - 1));
  cards[kbdIdx].classList.add('kbd-focus');
  cards[kbdIdx].scrollIntoView({block: 'nearest'});
}
function gridCols() {
  var g = document.querySelector('.grid'); if (!g) return 1;
  return getComputedStyle(g).gridTemplateColumns.split(' ').length;
}
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  var open = document.getElementById('lightbox').classList.contains('open');
  if (open) {
    if (e.key === 'ArrowRight') { lbStep(1); }
    else if (e.key === 'ArrowLeft') { lbStep(-1); }
    else if (e.key === 'Escape') { closeLightbox(); }
    else if (e.key === 'f' || e.key === 'F' || e.key === ' ') { e.preventDefault(); toggleSlideshow(); }
    return;
  }
  var cols = gridCols();
  if (e.key === 'ArrowRight') { kbdFocus(kbdIdx + 1); }
  else if (e.key === 'ArrowLeft') { kbdFocus(kbdIdx - 1); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); kbdFocus(kbdIdx < 0 ? 0 : kbdIdx + cols); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); kbdFocus(kbdIdx - cols); }
  else if (e.key === 'Enter' && kbdIdx >= 0) { openLightbox(null, kbdIdx); }
});
/* ---- Preserve scroll + re-sync selection across back / detail navigation ---- */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
function _scrollKey(){ return 'scroll:' + location.pathname + location.search; }
function saveScrollPos(){ try { sessionStorage.setItem(_scrollKey(), String(window.scrollY)); } catch(e){} }
function restoreScrollPos(){
  try {
    var y = sessionStorage.getItem(_scrollKey());
    if (y === null) return;
    var n = parseInt(y, 10) || 0;
    window.scrollTo(0, n);
    // thumbnails can shift layout as they load; re-apply once everything's in
    window.addEventListener('load', function(){ window.scrollTo(0, n); }, {once:true});
  } catch(e){}
}
window.addEventListener('beforeunload', saveScrollPos);
window.addEventListener('pagehide', saveScrollPos);
// pageshow fires on back/forward-cache restores (DOMContentLoaded does not),
// so this is what actually re-checks the boxes after a browser Back.
window.addEventListener('pageshow', function(){ refreshSelUI(); restoreScrollPos(); });
document.addEventListener('DOMContentLoaded', function(){
  refreshSelUI(); applyBlur(); refreshPresets(); restoreScrollPos(); applySelectMode();
  // Keep the bulk action bar stuck just below the sticky header. A collapsing
  // banner header (.bannered) PINS at its slim height (--bnr-slim), not its full
  // DOM height -- using offsetHeight there parks the bar mid-screen once scrolled.
  (function() {
    var h = document.querySelector('header');
    function setTop() {
      if (!h) return;
      var top = h.offsetHeight;
      if (h.classList.contains('bannered')) {
        var slim = parseInt(getComputedStyle(h).getPropertyValue('--bnr-slim'), 10);
        if (slim) top = slim;
      }
      document.documentElement.style.setProperty('--bulk-top', top + 'px');
    }
    setTop(); window.addEventListener('resize', setTop);
  })();
  // Cross-page lightbox: arriving with ?lbopen=first|last auto-opens the overlay so
  // arrow-key browsing rolls over page boundaries seamlessly.
  (function() {
    var m = location.search.match(/[?&]lbopen=(first|last)/);
    if (!m) return;
    var cards = document.querySelectorAll('.card');
    if (!cards.length) return;
    try { var u = new URL(location.href); u.searchParams.delete('lbopen'); history.replaceState(null, '', u); } catch(e) {}
    openLightbox(null, m[1] === 'last' ? cards.length - 1 : 0);
  })();
  // Lightbox touch: swipe left/right to navigate, double-tap to zoom 2x.
  var im = document.getElementById('lb-img');
  if (im) {
    var x0 = null, lastTap = 0;
    im.addEventListener('touchstart', function(e){
      if (e.touches.length === 1) x0 = e.touches[0].clientX;
    }, {passive: true});
    im.addEventListener('touchend', function(e){
      var now = Date.now();
      if (now - lastTap < 300) {            // double-tap zoom
        lbZoom = !lbZoom;
        im.style.transform = lbZoom ? 'scale(2)' : '';
        lastTap = 0; x0 = null; return;
      }
      lastTap = now;
      if (x0 !== null && !lbZoom) {         // horizontal swipe = navigate
        var dx = e.changedTouches[0].clientX - x0;
        if (Math.abs(dx) > 50) lbStep(dx < 0 ? 1 : -1);
      }
      x0 = null;
    }, {passive: true});
  }
});
</script>

<style>
  #gen-scrim{position:fixed;inset:0;background:rgba(6,4,16,.55);z-index:200;opacity:0;visibility:hidden;transition:opacity .18s;}
  #gen-scrim.open{opacity:1;visibility:visible;}
  #gen-drawer{position:fixed;top:0;right:0;height:100%;width:420px;max-width:94vw;background:var(--mantle);border-left:1px solid var(--surface1);z-index:201;transform:translateX(100%);transition:transform .2s ease,width .2s ease;display:flex;flex-direction:column;}
  #gen-drawer.open{transform:none;}
  #gen-drawer.wide{width:600px;}
  #gen-drawer.dock-left{right:auto;left:0;border-left:none;border-right:1px solid var(--surface1);transform:translateX(-100%);}
  #gen-drawer.dock-top{right:auto;left:0;top:0;bottom:auto;width:100%;max-width:100vw;height:auto;max-height:64vh;border:none;border-bottom:1px solid var(--surface1);transform:translateY(-100%);}
  #gen-drawer.dock-bottom{right:auto;left:0;top:auto;bottom:0;width:100%;max-width:100vw;height:auto;max-height:64vh;border:none;border-top:1px solid var(--surface1);transform:translateY(100%);}
  /* Open-while-docked: two classes beat the single-class dock rule so the on-screen
     transform wins (else a docked+open drawer keeps its off-screen transform -> vanishes). */
  #gen-drawer.open.dock-left,#gen-drawer.open.dock-top,#gen-drawer.open.dock-bottom{transform:none;}
  #gen-drawer.dock-top.wide,#gen-drawer.dock-bottom.wide{width:100%;}
  #gen-drawer.dock-top .gen-body,#gen-drawer.dock-bottom .gen-body{width:100%;max-width:940px;margin:0 auto;}
  .dock-ctl{margin-left:auto;display:flex;gap:3px;}
  .dock-ctl button{background:var(--surface0);border:1px solid var(--surface1);color:var(--subtext);border-radius:5px;width:22px;height:22px;font-size:10px;line-height:1;cursor:pointer;padding:0;}
  .dock-ctl button:hover{color:var(--text);}
  .dock-ctl button.on{color:var(--lavender);border-color:var(--lavender);}
  .gen-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--surface0);}
  .gen-head .spark{color:var(--lavender);font-size:18px;}
  .gen-head .t{font-size:15px;font-weight:600;color:var(--text);}
  .gen-head .x{margin-left:4px;background:none;border:none;color:var(--subtext);font-size:22px;cursor:pointer;line-height:1;padding:0 4px;}
  .gen-head .x:hover{color:var(--red);}
  .gen-body{padding:12px 14px;overflow-y:auto;flex:1;}
  .gen-seg{display:flex;gap:6px;margin-bottom:10px;}
  .gen-seg button{flex:1;padding:6px 0;font-size:12px;border-radius:6px;background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);cursor:pointer;}
  .gen-seg button.on{background:var(--lavender);color:var(--base);border-color:var(--lavender);font-weight:600;}
  .gen-search{width:100%;background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:7px 10px;font-size:13px;margin-bottom:10px;}
  .gen-search:focus{outline:none;border-color:var(--accent-soft);box-shadow:0 0 0 2px rgba(79,201,154,.25);}
  .mkt-sort{display:flex;gap:6px;margin-bottom:8px;}
  .mkt-sort button{flex:1;padding:5px 0;font-size:11px;border-radius:6px;background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);cursor:pointer;}
  .mkt-sort button.on{background:var(--surface1);color:var(--text);border-color:var(--accent-soft);font-weight:600;}
  .mkt-cats{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;}
  .mkt-cats button{padding:3px 10px;font-size:10.5px;border-radius:11px;background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);cursor:pointer;}
  .mkt-cats button.on{background:var(--accent);color:var(--base);border-color:var(--accent);font-weight:600;}
  .gen-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;transition:opacity .12s;}
  .gen-card{border-radius:12px;overflow:hidden;border:1px solid var(--surface1);background:var(--surface0);cursor:pointer;position:relative;}
  .gen-card:hover{border-color:var(--overlay0);}
  .gen-card.sel{border:2px solid var(--lavender);box-shadow:0 0 0 2px rgba(182,146,230,.25);}
  .gen-card .cov{aspect-ratio:1;width:100%;object-fit:cover;display:block;background:var(--surface1);}
  .gen-card .cov.blur{filter:blur(15px);}
  .gen-card .meta{padding:5px 7px;}
  .gen-card .nm{font-size:11.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .gen-card .sub{display:flex;align-items:center;gap:7px;margin-top:2px;font-size:10px;}
  .gen-card .ty{color:var(--emerald);}
  .gen-card .lk{color:var(--subtext);}
  .gen-card .uses{color:var(--lavender);margin-left:auto;}
  .gen-card .chk{position:absolute;top:4px;right:4px;color:var(--lavender);background:var(--mantle);border-radius:50%;font-size:12px;width:18px;height:18px;display:none;align-items:center;justify-content:center;border:1px solid var(--lavender);}
  .gen-card.sel .chk{display:flex;}
  .gen-empty{color:var(--subtext);font-size:12px;padding:22px 4px;text-align:center;}
  .gen-form{border-top:1px dashed var(--surface1);margin-top:12px;padding-top:10px;}
  .gen-lbl{color:var(--overlay0);font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin:10px 0 4px;}
  .gen-ta{width:100%;background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:7px 9px;font-size:13px;font-family:inherit;resize:vertical;}
  .gen-ta:focus,.gen-sel:focus{outline:none;border-color:var(--accent-soft);box-shadow:0 0 0 2px rgba(79,201,154,.25);}
  #gen-selname{color:var(--lavender);font-size:12.5px;margin-bottom:8px;}
  .gen-aspects{display:flex;gap:5px;flex-wrap:wrap;}
  .gen-aspects button{padding:4px 9px;font-size:11px;border-radius:6px;background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);cursor:pointer;}
  .gen-aspects button.on{background:var(--surface1);color:var(--text);border-color:var(--overlay0);}
  .gen-row{display:flex;gap:8px;}
  .gen-sel{width:100%;background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:6px 8px;font-size:12.5px;}
  .gen-check{display:flex;align-items:center;gap:7px;color:var(--subtext);font-size:12px;margin-top:8px;cursor:pointer;}
  .gen-cost{margin:12px 0 8px;padding:8px 10px;border-radius:6px;background:var(--surface0);border:1px solid var(--surface1);font-size:12.5px;color:var(--text);}
  .gen-cost.free{border-color:var(--emerald);color:var(--emerald);}
  .gen-cost.warn{border-color:var(--red);color:var(--red);}
  .gen-go{width:100%;padding:9px 0;border:none;border-radius:6px;background:var(--lavender);color:var(--base);font-size:13.5px;font-weight:600;cursor:pointer;}
  .gen-go:hover{opacity:.9;} .gen-go:disabled{opacity:.4;cursor:not-allowed;}
  .gen-ce{min-height:66px;white-space:pre-wrap;overflow-y:auto;max-height:180px;}
  .gen-ce:empty::before{content:attr(data-placeholder);color:var(--overlay0);pointer-events:none;}
  .gen-ce:focus{outline:none;border-color:var(--accent-soft);box-shadow:0 0 0 2px rgba(79,201,154,.25);}
  .vp-chip{display:inline-flex;align-items:center;gap:4px;background:var(--surface1);border:1px solid var(--overlay0);border-radius:5px;padding:1px 6px 1px 2px;font-size:11.5px;color:var(--lavender);margin:0 2px;vertical-align:-3px;cursor:default;user-select:none;}
  .vp-chip img{width:16px;height:16px;border-radius:3px;object-fit:cover;}
  .gen-moon{display:inline-block;width:15px;height:15px;border-radius:50%;background:var(--lavender);position:relative;overflow:hidden;vertical-align:-3px;margin-right:7px;box-shadow:0 0 9px rgba(182,146,230,.75);}
  .gen-moon::after{content:'';position:absolute;inset:0;border-radius:50%;background:var(--mantle);animation:gen-eclipse 2.6s ease-in-out infinite;}
  @keyframes gen-eclipse{0%{transform:translateX(-102%);}50%{transform:translateX(0);}100%{transform:translateX(102%);}}
  .gen-result{margin-top:12px;} .gen-result img{width:100%;border-radius:10px;display:block;margin-bottom:6px;}
  .gen-result a{color:var(--accent-soft);font-size:12px;text-decoration:none;}
  #enh-list{max-height:230px;overflow-y:auto;margin-top:2px;}
  .enh-item{display:block;width:100%;text-align:left;padding:6px 9px;margin-bottom:4px;border-radius:6px;background:var(--surface0);color:var(--text);border:1px solid var(--surface1);cursor:pointer;font-size:12px;line-height:1.3;}
  .enh-item:hover{border-color:var(--overlay0);}
  .enh-item .ty{color:var(--overlay0);font-size:10px;}
  .enh-shelf{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 12px;}
  .enh-sec{flex:0 0 100%;font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--overlay0);margin:7px 0 1px;}
  .enh-sec:first-child{margin-top:0;}
  .enh-card{padding:6px 11px;border-radius:7px;background:var(--surface1);color:var(--text);border:1px solid var(--surface1);cursor:pointer;font-size:12px;line-height:1.2;}
  .enh-card:hover{border-color:var(--accent);background:var(--surface0);}
  .fix-tags{display:flex;gap:5px;margin-bottom:6px;}
  .fix-tags button{padding:4px 10px;font-size:11px;border-radius:6px;background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);cursor:pointer;}
  .fix-tags button.on{background:var(--surface1);color:var(--text);border-color:var(--overlay0);}
  #fix-wrap{position:relative;display:inline-block;max-width:100%;line-height:0;}
  #fix-img{max-width:100%;display:block;border-radius:8px;}
  #fix-canvas{position:absolute;top:0;left:0;cursor:crosshair;touch-action:none;}
  #gen-loras{display:flex;flex-direction:column;gap:5px;}
  #gen-lora-note{display:flex;flex-direction:column;gap:5px;}
  #gen-lora-note:empty{display:none;}
  .lora-warn{font-size:11px;line-height:1.4;padding:6px 9px;border-radius:6px;background:rgba(243,139,168,.09);border:1px solid var(--red);color:var(--red);}
  .lora-warn b{color:var(--peach);}
  .lora-trig{font-size:11px;line-height:1.4;padding:6px 9px;border-radius:6px;background:rgba(79,201,154,.09);border:1px solid var(--emerald);color:var(--text);display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
  .lora-trig code{background:var(--surface1);border-radius:4px;padding:1px 5px;font-size:10.5px;color:var(--accent-soft);}
  .lora-trig button{margin-left:auto;background:var(--emerald);color:var(--base);border:none;border-radius:5px;padding:3px 10px;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;}
  .lora-trig button.done{background:var(--surface1);color:var(--subtext);cursor:default;}
  .lora-chip.incompat{border-color:var(--red);}
  .lora-chip.incompat .nm{color:var(--red);}
  .lora-chip{display:flex;align-items:center;gap:7px;padding:5px 8px;border-radius:6px;background:var(--surface0);border:1px solid var(--surface1);font-size:12px;color:var(--text);}
  .lora-chip img{width:24px;height:24px;border-radius:4px;object-fit:cover;flex:0 0 auto;}
  .lora-chip .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .lora-chip input{width:58px;background:var(--surface1);border:1px solid var(--overlay0);border-radius:4px;color:var(--text);font-size:11.5px;padding:2px 4px;}
  .lora-chip .rm{background:none;border:none;color:var(--subtext);cursor:pointer;font-size:14px;padding:0 2px;}
  .lora-chip .rm:hover{color:var(--red);}
  #lora-add{width:100%;margin-top:5px;padding:5px 0;font-size:11.5px;border-radius:6px;background:transparent;color:var(--subtext);border:1px dashed var(--surface1);cursor:pointer;}
  #lora-add:hover{color:var(--text);border-color:var(--overlay0);}
  #gen-selrow{display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;border-radius:6px;background:var(--surface0);border:1px solid var(--surface1);color:var(--text);cursor:pointer;font-size:12.5px;text-align:left;}
  #gen-selrow:hover{border-color:var(--overlay0);}
  #gen-selthumb{width:30px;height:30px;border-radius:6px;object-fit:cover;flex:0 0 auto;}
  #gen-selrow .hint{margin-left:auto;color:var(--overlay0);font-size:11px;flex:0 0 auto;}
  #model-flyout{position:absolute;top:0;right:100%;height:100%;width:372px;max-width:92vw;background:var(--mantle);border:1px solid var(--surface1);border-right:none;display:none;flex-direction:column;box-shadow:-14px 0 34px rgba(0,0,0,.4);}
  #model-flyout.open{display:flex;}
  #model-flyout .x{margin-left:auto;}
  #gen-drawer.dock-left #model-flyout{right:auto;left:100%;border-right:1px solid var(--surface1);border-left:none;box-shadow:14px 0 34px rgba(0,0,0,.4);}
  /* Top/bottom docks are thin full-width bars -- an edge-popped flyout gets clipped.
     Render the model browser as a centered overlay instead so it's never obscured. */
  #gen-drawer.dock-top #model-flyout,#gen-drawer.dock-bottom #model-flyout{position:fixed;top:50%;left:50%;right:auto;bottom:auto;transform:translate(-50%,-50%);width:540px;max-width:92vw;height:auto;max-height:82vh;border:1px solid var(--surface1);border-radius:12px;box-shadow:0 22px 60px rgba(0,0,0,.6);}
  #pick-scrim{position:fixed;inset:0;background:rgba(6,4,16,.6);z-index:210;display:none;}
  #pick-scrim.open{display:block;}
  #pick-modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:900px;max-width:94vw;height:84vh;max-height:84vh;background:var(--mantle);border:1px solid var(--surface1);border-radius:12px;z-index:211;display:none;flex-direction:column;padding:14px;}
  .pick-filters{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap;}
  .pick-filters select{background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:5px 8px;font-size:12px;}
  #pick-modal.open{display:flex;}
  #similar-scrim{position:fixed;inset:0;background:rgba(6,4,16,.6);z-index:210;display:none;}
  #similar-scrim.open{display:block;}
  #similar-modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:900px;max-width:94vw;height:84vh;max-height:84vh;background:var(--mantle);border:1px solid var(--surface1);border-radius:12px;z-index:211;display:none;flex-direction:column;padding:14px;}
  #similar-modal.open{display:flex;}
  /* Bulletproof fixed-tile grid (same pattern as #pick-grid) -- the aspect-ratio .card
     pattern collapses to slivers inside this flex modal, which is why it didn't scroll. */
  #similar-modal #similar-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));grid-auto-rows:150px;gap:10px;overflow-y:auto;flex:1;min-height:0;align-content:start;padding:4px;}
  #similar-modal #similar-grid .card{grid-row:span 1;}
  #similar-modal #similar-grid .card img{width:100%;height:100%;aspect-ratio:auto;object-fit:contain;background:var(--crust);}
  #similar-modal #similar-grid .card .meta{position:absolute;left:0;right:0;bottom:0;margin:0;padding:2px 6px;background:linear-gradient(transparent,rgba(0,0,0,.72));pointer-events:none;}
  .pick-head{display:flex;align-items:center;margin-bottom:10px;}
  .pick-head .t{font-size:15px;font-weight:600;color:var(--text);}
  .pick-head .x{margin-left:auto;background:none;border:none;color:var(--subtext);font-size:22px;cursor:pointer;}
  /* FIXED row height -- the bulletproof image-grid pattern. No aspect-ratio, no
     percentage heights, so cells can't collapse to slivers or blow out tall. */
  #pick-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));grid-auto-rows:120px;gap:8px;overflow-y:auto;transition:opacity .12s;flex:1;min-height:120px;align-content:start;}
  .pick-cell{border-radius:8px;overflow:hidden;border:1px solid var(--surface1);cursor:pointer;background:var(--surface0);}
  .pick-cell:hover{border-color:var(--lavender);}
  /* aspect-ratio on the IMG (not the cell) -- mirrors the main gallery grid. Putting it
     on the cell + height:100% on the img is a percentage-height-against-indefinite-height
     trap: the img blows out to its intrinsic height and cells overlap into a torn smear. */
  .pick-cell{grid-row:span 1;}
  .pick-cell img{width:100%;height:100%;object-fit:cover;display:block;background:var(--surface0);}
  .pick-empty{color:var(--subtext);font-size:12px;padding:24px;text-align:center;}
  #pick-up{flex:0 0 auto;height:33px;padding:0 12px;font-size:12px;border-radius:6px;background:var(--surface0);color:var(--text);border:1px solid var(--surface1);cursor:pointer;white-space:nowrap;}
  #pick-up:hover{border-color:var(--overlay0);}
  #pick-more{margin-top:10px;padding:8px 0;width:100%;flex:0 0 auto;font-size:12.5px;border-radius:6px;background:var(--surface0);color:var(--text);border:1px solid var(--surface1);cursor:pointer;}
  #pick-more:hover{border-color:var(--lavender);color:var(--lavender);}
  #model-preview{position:fixed;z-index:220;width:300px;max-width:80vw;background:var(--mantle);border:1px solid var(--surface1);border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.55);display:none;overflow:hidden;pointer-events:none;}
  #model-preview.open{display:block;}
  #model-preview img{width:100%;max-height:340px;object-fit:cover;display:block;background:var(--surface1);}
  #model-preview img.blur{filter:blur(18px);}
  #model-preview .mp-meta{padding:9px 11px;}
  #model-preview .mp-nm{font-size:13px;font-weight:600;color:var(--text);}
  #model-preview .mp-sub{display:flex;gap:8px;font-size:11px;margin-top:3px;color:var(--subtext);}
  #model-preview .mp-sub .ty{color:var(--emerald);}
  #model-preview .mp-desc{font-size:11px;color:var(--subtext);margin-top:5px;line-height:1.45;max-height:88px;overflow:hidden;}
  #model-preview .mp-tags{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px;}
  #model-preview .mp-tags span{font-size:10px;background:var(--surface0);border:1px solid var(--surface1);border-radius:4px;padding:1px 6px;color:var(--subtext);}
  #model-preview .mp-badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px;}
  #model-preview .mp-badges .bdg{font-size:10px;font-weight:600;letter-spacing:.02em;border-radius:5px;padding:1px 7px;background:var(--surface0);border:1px solid var(--surface1);color:var(--subtext);text-transform:uppercase;}
  #model-preview .mp-badges .bdg.base{color:#c9b8ff;border-color:#4a3f78;}
  #model-preview .mp-badges .bdg.official{color:#0f1017;background:linear-gradient(180deg,#ffd27a,#e6a94b);border-color:#e6a94b;}
</style>
<div id="gen-scrim" onclick="Gen.close()"></div>
<aside id="gen-drawer" aria-hidden="true" aria-label="Generate">
  <div class="gen-head">
    <span class="spark">&#10022;</span><span class="t">Generate</span>
    <span class="dock-ctl">
      <button type="button" data-dock="left" onclick="Gen.setDock('left')" title="Dock left">&#9612;</button>
      <button type="button" data-dock="top" onclick="Gen.setDock('top')" title="Dock top">&#9600;</button>
      <button type="button" data-dock="bottom" onclick="Gen.setDock('bottom')" title="Dock bottom">&#9604;</button>
      <button type="button" data-dock="right" class="on" onclick="Gen.setDock('right')" title="Dock right">&#9616;</button>
    </span>
    <button class="x" onclick="Gen.close()" aria-label="Close">&times;</button>
  </div>
  <div class="gen-body">
    <div class="gen-seg" id="gen-mode-seg" style="margin-bottom:12px;">
      <button id="gm-generate" class="on" onclick="Gen.setMode('generate')">Generate</button>
      <button id="gm-edit" onclick="Gen.setMode('edit')">Edit</button>
      <button id="gm-video" onclick="Gen.setMode('video')">Video</button>
    </div>
    <div id="gen-mode-generate">
    <div class="gen-lbl" style="margin-top:0;">Model</div>
    <button type="button" id="gen-selrow" onclick="Gen.toggleFlyout()"
            onmouseenter="Gen.previewSelected(event)" onmouseleave="Gen.hidePreview()">
      <img id="gen-selthumb" alt="" style="display:none;">
      <span id="gen-selname">none &mdash; browse models</span>
      <span class="hint">&#9666; browse</span>
    </button>
    <div class="gen-lbl">LoRAs</div>
    <div id="gen-loras"></div>
    <div id="gen-lora-note"></div>
    <button type="button" id="lora-add" onclick="Gen.openLoraBrowser()">+ Add LoRA</button>
    <div class="gen-lbl">Reference image <span style="text-transform:none;color:var(--subtext);">&middot; optional &middot; guides the result (img2img)</span></div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div id="gen-ref-slot" onclick="Gen.refPick()" title="Pick a reference image from your gallery"
           style="position:relative;width:58px;height:58px;flex:0 0 auto;border-radius:8px;border:1px dashed var(--surface1);background:var(--surface0);cursor:pointer;display:grid;place-items:center;color:var(--subtext);font-size:10.5px;overflow:hidden;">+ ref</div>
      <div id="gen-ref-ctl" style="flex:1;display:none;">
        <div class="gen-lbl" style="margin-top:0;">Strength <span id="gen-ref-sval" style="color:var(--lavender);">0.55</span>
          <span style="text-transform:none;color:var(--overlay0);">&middot; higher = closer to the reference</span></div>
        <input type="range" id="gen-ref-strength" min="0.1" max="1" step="0.05" value="0.55" style="width:100%;"
               oninput="Gen.refStrength(this.value)">
      </div>
    </div>
    <div class="gen-form" style="border-top:none;margin-top:0;padding-top:0;">
      <div style="display:flex;justify-content:flex-end;margin-top:8px;">
        <button type="button" class="snip-btn" onclick="Snips.open(this, {get:function(){return document.getElementById('gen-prompt').value;}, set:function(v){document.getElementById('gen-prompt').value=v;document.getElementById('gen-prompt').focus();Gen.refreshCost();}})">&#9733; Snippets</button>
      </div>
      <textarea id="gen-prompt" class="gen-ta" rows="3" placeholder="Describe your image&hellip;"></textarea>
      <details style="margin-top:6px;">
        <summary style="cursor:pointer;color:var(--subtext);font-size:11px;">Negative prompt</summary>
        <textarea id="gen-neg" class="gen-ta" rows="2" placeholder="lowres, text, watermark&hellip;" style="margin-top:5px;"></textarea>
      </details>
      <div class="gen-lbl">Aspect</div>
      <div class="gen-aspects" id="gen-aspects">
        <button type="button" data-rw="1" data-rh="1" class="on">1:1</button>
        <button type="button" data-rw="3" data-rh="4">3:4</button>
        <button type="button" data-rw="4" data-rh="3">4:3</button>
        <button type="button" data-rw="2" data-rh="3">2:3</button>
        <button type="button" data-rw="3" data-rh="2">3:2</button>
        <button type="button" data-rw="9" data-rh="16">9:16</button>
        <button type="button" data-rw="16" data-rh="9">16:9</button>
        <button type="button" data-rw="3" data-rh="1">3:1</button>
      </div>
      <div class="gen-row" style="margin-top:8px;">
        <div style="flex:1;"><div class="gen-lbl">Size &middot; long edge</div>
          <select id="gen-size" class="gen-sel">
            <option value="768">S &middot; 768</option>
            <option value="1024" selected>M &middot; 1024</option>
            <option value="1536">L &middot; 1536</option>
            <option value="2048">XL &middot; 2048</option>
          </select></div>
        <div style="flex:1;"><div class="gen-lbl">Custom W&times;H <span style="text-transform:none;color:var(--subtext);">&middot; overrides</span></div>
          <div style="display:flex;gap:5px;align-items:center;">
            <input id="gen-cw" class="gen-sel" type="number" min="64" max="4096" step="8" placeholder="W" style="flex:1;min-width:0;">
            <span style="color:var(--subtext);">&times;</span>
            <input id="gen-ch" class="gen-sel" type="number" min="64" max="4096" step="8" placeholder="H" style="flex:1;min-width:0;">
          </div></div>
      </div>
      <div id="gen-dim-note" style="font-size:11px;color:var(--subtext);margin-top:5px;"></div>
      <div class="gen-row" style="margin-top:8px;">
        <div style="flex:1;"><div class="gen-lbl">Mode</div>
          <select id="gen-mode" class="gen-sel"><option value="auto">Auto</option><option value="lite">Lite</option><option value="standard">Standard</option><option value="pro">Pro</option><option value="ultra">Ultra</option></select></div>
        <div style="flex:1;"><div class="gen-lbl">Count</div>
          <select id="gen-count" class="gen-sel"><option>1</option><option>2</option><option>3</option><option>4</option></select></div>
      </div>
      <div style="margin-top:8px;"><div class="gen-lbl">Seed <span style="text-transform:none;color:var(--subtext);">&middot; blank = random</span></div>
        <input id="gen-seed" class="gen-sel" type="number" placeholder="random" autocomplete="off" style="width:100%;"></div>
      <label class="gen-check" title="This IS the site's Turbo tier (priority=1000): a faster runner. Costs more credits when paid, but a matching free card covers it (paidCredit 0) — verified against a real Turbo gen."><input type="checkbox" id="gen-hp"> High priority &middot; Turbo (faster)</label>
      <label class="gen-check"><input type="checkbox" id="gen-ph" checked> Prompt helper</label>
      <div id="gen-cost" class="gen-cost">Pick a model to see the cost.</div>
      <button id="gen-go" class="gen-go" onclick="Gen.generate()" disabled>Generate</button>
      <div id="gen-result" class="gen-result" style="display:none;"></div>
    </div>
    </div>
    <div id="gen-mode-edit" style="display:none;">
      <div class="gen-lbl">Editing image</div>
      <img id="edit-src-img" alt="source" style="width:100%;border-radius:10px;display:none;margin-bottom:8px;">
      <div style="display:flex;gap:6px;align-items:center;">
        <input id="edit-src" class="gen-search" style="margin-bottom:0;flex:1;" placeholder="Source media_id" autocomplete="off">
        <button type="button" class="gen-seg" style="flex:0 0 auto;padding:7px 11px;font-size:12px;border-radius:6px;background:var(--surface0);color:var(--text);border:1px solid var(--surface1);cursor:pointer;white-space:nowrap;" onclick="Picker.open(function(mid){ Gen.setEditSource(mid); })">&#9648; Pick</button>
      </div>
      <div class="gen-seg" style="margin:10px 0;">
        <button id="es-edit" class="on" onclick="Gen.setEditSub('edit')">Edit</button>
        <button id="es-enhance" onclick="Gen.setEditSub('enhance')">Enhance</button>
        <button id="es-fix" onclick="Gen.setEditSub('fix')">Fix</button>
      </div>
      <div id="edit-sub-edit">
        <div class="gen-lbl" style="margin-top:0;">Edit model</div>
        <div class="gen-seg" style="margin-bottom:9px;">
          <button id="em-edit-pro" type="button" class="on" onclick="Gen.setEditModel('edit-pro')" title="Instruct edit + up to 4 reference images &middot; 1K/2K">Edit Pro</button>
          <button id="em-reference-pro" type="button" onclick="Gen.setEditModel('reference-pro')" title="Reference edit + up to 10 reference images &middot; 2K/4K">Reference Pro</button>
        </div>
        <div class="gen-lbl">Toolbox preset <span style="text-transform:none;color:var(--subtext);">&middot; canned effects &middot; overrides the instruction</span></div>
        <div style="display:flex;gap:6px;margin-bottom:6px;">
          <select id="edit-preset" class="gen-sel" style="flex:1;" onchange="Gen.editCost()">
            <option value="">None &mdash; custom instruction below</option>
          </select>
          <input id="preset-task" class="gen-search" style="margin:0;flex:0 0 150px;" placeholder="import: task id" autocomplete="off">
          <button type="button" class="snip-btn" style="flex:0 0 auto;" onclick="Gen.presetImport()" title="Run any Toolbox item once on pixai.art, paste its task id here — banks that preset locally forever">＋ bank</button>
        </div>
        <textarea id="edit-ins" class="gen-ta" rows="3" placeholder="Describe the change &mdash; &lsquo;make it night, add snow&rsquo;&hellip;"></textarea>
        <div class="gen-row" style="margin-top:8px;">
          <div style="flex:1;"><div class="gen-lbl">Resolution</div>
            <select id="edit-res" class="gen-sel"></select></div>
          <div style="flex:1;" id="edit-qual-wrap"><div class="gen-lbl">Quality</div>
            <select id="edit-qual" class="gen-sel"></select></div>
        </div>
        <div class="gen-lbl">Aspect</div>
        <select id="edit-aspect" class="gen-sel"></select>
        <div class="gen-lbl">Reference images <span id="edit-ref-cap" style="text-transform:none;color:var(--subtext);"></span></div>
        <div id="edit-refs" style="display:flex;gap:8px;flex-wrap:wrap;"></div>
        <div id="edit-cost" class="gen-cost">Pick an image to see the cost.</div>
        <button id="edit-go" class="gen-go" onclick="Gen.edit()">Apply edit</button>
        <div id="edit-result" class="gen-result" style="display:none;"></div>
      </div>
      <div id="edit-sub-enhance" style="display:none;">
        <div class="gen-lbl">One-click tools <span style="text-transform:none;color:var(--subtext);">&middot; official PixAI workflows &middot; runs on the source</span></div>
        <div class="enh-shelf">
          <div class="enh-sec">Upscale</div>
          <button type="button" class="enh-card" onclick="Gen.enhance('1794855217667308480')" title="Upscale the image">Upscale</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1804744873525448983')" title="Upscale in 2x2 tiles (higher detail)">Upscale 2&times;2</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1803967880822088690')" title="Upscale and re-detail">Upscale + Enhance</button>
          <div class="enh-sec">Cleanup</div>
          <button type="button" class="enh-card" onclick="Gen.enhance('1793505053210462325')" title="Remove the background">Remove BG</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1793473388466817128')" title="Precise masked inpaint / edit">Precise inpaint</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1793713293591365899')" title="Extend the frame outward (outpaint)">Outpaint</button>
          <div class="enh-sec">Convert</div>
          <button type="button" class="enh-card" onclick="Gen.enhance('1796053397111789217')" title="Convert to line art">To line art</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1793447160259872021')" title="Colorize a sketch / line art">Sketch colorizer</button>
          <div class="enh-sec">Light</div>
          <button type="button" class="enh-card" onclick="Gen.enhance('1801729774701480692')" title="Relight: warm sunshine">Relight: sun</button>
          <button type="button" class="enh-card" onclick="Gen.enhance('1801752508134768728')" title="Relight: backlighting">Relight: backlight</button>
        </div>
        <div class="gen-lbl">Browse all workflows <span style="text-transform:none;color:var(--subtext);">&middot; 140+ community ComfyUI</span></div>
        <input class="gen-search" id="enh-q" placeholder="Search workflows &mdash; upscale, background, line art&hellip;" autocomplete="off">
        <div id="enh-list"></div>
        <div id="enh-result" class="gen-result" style="display:none;"></div>
      </div>
      <div id="edit-sub-fix" style="display:none;">
        <div class="gen-lbl">Fix hands / faces <span style="text-transform:none;color:var(--subtext);">&middot; drag a box</span></div>
        <div class="fix-tags">
          <button type="button" id="fix-tag-face" class="on" onclick="Gen.fixTag('face')">Face</button>
          <button type="button" id="fix-tag-hand" onclick="Gen.fixTag('hand')">Hand</button>
          <button type="button" onclick="Gen.fixClear()">Clear</button>
        </div>
        <div id="fix-wrap"><img id="fix-img" alt="fix source"><canvas id="fix-canvas"></canvas></div>
        <button id="fix-go" class="gen-go" onclick="Gen.fix()" style="margin-top:8px;">Fix marked regions</button>
        <div id="fix-result" class="gen-result" style="display:none;"></div>
      </div>
    </div>
    <div id="gen-mode-video" style="display:none;">
      <div class="gen-seg" style="margin-bottom:10px;">
        <button id="vm-i2v" class="on" onclick="Gen.setVideoMode('i2v')">First frame</button>
        <button id="vm-flf" onclick="Gen.setVideoMode('flf')">First + last</button>
        <button id="vm-r2v" onclick="Gen.setVideoMode('r2v')">Multi-ref</button>
      </div>
      <div class="gen-lbl" id="video-slots-lbl">Source image (first frame)</div>
      <div id="video-slots"></div>
      <div style="display:flex;justify-content:flex-end;margin-top:8px;">
        <button type="button" class="snip-btn" onclick="Snips.open(this, {get:Gen.videoPromptText, set:Gen.videoPromptSet})">&#9733; Snippets</button>
      </div>
      <div id="video-prompt" class="gen-ta gen-ce" contenteditable="true"
           data-placeholder="Describe the motion &mdash; &lsquo;slow cinematic pan right, gentle waves&hellip;&rsquo;"></div>
      <div class="gen-row" style="margin-top:8px;">
        <div style="flex:1.4;"><div class="gen-lbl">Model</div>
          <select id="video-model" class="gen-sel" onchange="Gen.videoCost()">
            <option value="v4.0.1" selected>V4.0 Lite Preview &middot; multi-ref &middot; 15s &middot; audio</option>
            <option value="v4.0">V4.0 Preview (full) &middot; top quality &middot; pricier</option>
            <option value="v3.2">V3.2 &middot; audio &middot; prompt-following</option>
            <option value="v3.0.2">V3.0 Lite &middot; complex motion</option>
            <option value="v3.0">V3.0 &middot; high consistency</option>
          </select></div>
        <div style="flex:1;"><div class="gen-lbl">Duration (s)</div>
          <select id="video-dur" class="gen-sel" onchange="Gen.videoCost()"><option>5</option><option>6</option><option>10</option><option>15</option></select></div>
      </div>
      <div class="gen-row" style="margin-top:8px;">
        <div id="video-cam-wrap" style="flex:1;"><div class="gen-lbl">Camera</div>
          <select id="video-cam" class="gen-sel">
            <option value="unset">Auto</option><option value="zoom">Zoom</option>
            <option value="pan">Pan</option><option value="tilt">Tilt</option>
            <option value="roll">Roll</option><option value="horizontal">Horizontal</option>
            <option value="vertical-pan">Vertical pan</option>
          </select></div>
        <div style="flex:1;"><div class="gen-lbl">Priority</div>
          <select id="video-vmode" class="gen-sel"><option value="professional">Professional</option><option value="basic">Basic (cheaper)</option></select></div>
      </div>
      <label class="gen-check"><input type="checkbox" id="video-audio" onchange="Gen.videoAudioToggle()"> Generate audio <span style="color:var(--overlay0);">(V4.0 / V3.2 &middot; spoken lines in the prompt become voiceover)</span></label>
      <div id="video-lang-wrap" style="display:none;margin-top:4px;"><div class="gen-lbl">Audio language</div>
        <select id="video-lang" class="gen-sel"><option value="english">English</option><option value="japanese">Japanese</option><option value="chinese">Chinese</option><option value="korean">Korean</option></select></div>
      <div class="gen-cost" id="video-cost" style="margin-top:10px;">Pick a source image to see the cost.</div>
      <button id="video-go" class="gen-go" onclick="Gen.videoGenerate()">Generate video</button>
      <div id="video-result" class="gen-result" style="display:none;"></div>
    </div>
  </div>
  <div id="model-flyout" aria-hidden="true" aria-label="Models and LoRAs">
    <div class="gen-head"><span class="t">Models &amp; LoRAs</span>
      <button class="x" onclick="Gen.toggleFlyout()" aria-label="Close">&times;</button></div>
    <div class="gen-body">
      <div class="gen-seg">
        <button id="gen-k-base" class="on" onclick="Gen.setKind('base')">Models</button>
        <button id="gen-k-lora" onclick="Gen.setKind('lora')">LoRAs</button>
      </div>
      <input class="gen-search" id="gen-q" placeholder="Search models&hellip;" autocomplete="off">
      <div class="mkt-sort" id="mkt-sort" style="display:none;">
        <button id="mkt-popular" class="on" onclick="Gen.setSort('popular')" title="PixAI&#39;s most-used order">Popular</button>
        <button id="mkt-newest" onclick="Gen.setSort('newest')" title="Newest uploads first">Newest</button>
      </div>
      <div class="mkt-cats" id="mkt-cats" style="display:none;">
        <button class="on" data-cat="" onclick="Gen.setCat('')">All</button>
        <button data-cat="character" onclick="Gen.setCat('character')">Character</button>
        <button data-cat="style" onclick="Gen.setCat('style')">Style</button>
        <button data-cat="pose" onclick="Gen.setCat('pose')">Pose</button>
        <button data-cat="clothing" onclick="Gen.setCat('clothing')">Clothing</button>
        <button data-cat="background" onclick="Gen.setCat('background')">Background</button>
        <button data-cat="detail" onclick="Gen.setCat('detail')">Detail</button>
      </div>
      <div class="gen-grid" id="gen-grid"></div>
      <div class="gen-empty" id="gen-empty" style="display:none;"></div>
    </div>
  </div>
</aside>
<div id="pick-scrim" onclick="Picker.close()"></div>
<div id="pick-modal" aria-hidden="true" aria-label="Pick from your gallery">
  <div class="pick-head"><span class="t">&#9648; Select from your gallery</span>
    <button class="x" onclick="Picker.close()" aria-label="Close">&times;</button></div>
  <div style="display:flex;gap:6px;">
    <input class="gen-search" id="pick-q" style="flex:1;" placeholder="Search your images&hellip;" autocomplete="off">
    <button type="button" id="pick-up" onclick="Picker.upload()" title="Upload a local file (free)">&#8679; Upload</button>
    <input type="file" id="pick-file" accept="image/*" style="display:none;" onchange="Picker.onFile()">
  </div>
  <div class="pick-filters">
    <select id="pick-collection" onchange="Picker.onFilter()">
      <option value="">All collections</option>
      {% for c in collections %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
    </select>
    <select id="pick-source" onchange="Picker.onFilter()">
      <option value="">Any source</option>
      <option value="api">Generated (AI)</option>
      <option value="local">Imported local</option>
    </select>
    <select id="pick-rating" onchange="Picker.onFilter()">
      <option value="0">Any rating</option>
      <option value="1">&#9733;+</option><option value="2">&#9733;&#9733;+</option>
      <option value="3">&#9733;&#9733;&#9733;+</option><option value="4">&#9733;&#9733;&#9733;&#9733;+</option>
      <option value="5">&#9733;&#9733;&#9733;&#9733;&#9733;</option>
    </select>
    <select id="pick-sort" onchange="Picker.onFilter()">
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
    </select>
  </div>
  <label class="gen-check" style="margin:0 0 8px;"><input type="checkbox" id="pick-copy" onchange="Picker.toggleCopy()"> Copy the image&rsquo;s prompt to the clipboard when picking</label>
  <div id="pick-grid" onscroll="Picker.onScroll()"></div>
  <div class="pick-empty" id="pick-empty" style="display:none;"></div>
  <button type="button" id="pick-more" onclick="Picker.more()" style="display:none;">Load more</button>
</div>
<div id="similar-scrim" onclick="Similar.close()"></div>
<div id="similar-modal" aria-hidden="true" aria-label="Visually similar images">
  <div class="pick-head"><span class="t">✧ Visually similar</span>
    <button class="x" onclick="Similar.close()" aria-label="Close">&times;</button></div>
  <div class="grid" id="similar-grid"></div>
  <div class="pick-empty" id="similar-empty" style="display:none;"></div>
</div>
<div id="model-preview" aria-hidden="true"></div>
<div id="ctx-menu"></div>
<div id="tag-suggest"></div>
<div id="jobs-fab" onclick="JobsCard.open()" title="Activity"><span class="jf-dot"></span><span class="jf-badge" id="jobs-fab-badge"></span><span>Activity</span></div>
<div id="jobs-tray" aria-label="Job activity"></div>
<div id="mg-toasts" aria-live="polite"></div>
<div id="snip-menu"></div>
<div id="ach-modal" class="ach-modal" aria-hidden="true" onclick="if(event.target===this)Ach.close()">
  <div class="ach-panel" role="dialog" aria-label="Achievements and skins">
    <button type="button" class="ach-x" onclick="Ach.close()" aria-label="Close">&times;</button>
    <div class="ach-htitle">&#127942; Achievements<img class="ach-nar" id="ach-nar"
      src="/branding/mascots/gen_nel.png" title="the narrator" alt="the narrator"
      onclick="Ach.poke()" onerror="this.remove()"><span id="ach-unleash-slot"></span></div>
    <div class="ach-hsub" id="ach-progress">&hellip;</div>
    <div id="ach-grid" class="ach-grid"></div>
    <div class="ach-skinhd">&#127912; Skins <span class="ach-skinnote">now live in the
      <a href="/panel" style="color:var(--lavender);">Control Panel</a> beside Branding &middot; unlock more by earning epic achievements</span></div>
  </div>
</div>
<div id="contest-modal" class="ach-modal" aria-hidden="true" onclick="if(event.target===this)Contests.close()">
  <div class="ach-panel" role="dialog" aria-label="PixAI contests">
    <button type="button" class="ach-x" onclick="Contests.close()" aria-label="Close">&times;</button>
    <div class="ach-htitle">&#127941; Contests</div>
    <div class="ach-hsub" id="contest-sub">Loading the community&hellip;</div>
    <div id="contest-body"></div>
    <div class="ct-foot">A community thing &mdash; the Oasis was never a 1-player game. Enter from the PixAI site. <a href="#" onclick="Contests.toggleAll(event)" id="ct-all">Show ended too</a></div>
  </div>
</div>
<div id="art-modal" class="ach-modal" aria-hidden="true" onclick="if(event.target===this)YourArt.close()">
  <div class="ach-panel" role="dialog" aria-label="Your art">
    <button type="button" class="ach-x" onclick="YourArt.close()" aria-label="Close">&times;</button>
    <div class="ach-htitle">&#128200; Your Art</div>
    <div class="ach-hsub" id="art-sub">Loading&hellip;</div>
    <div id="art-grid" class="art-grid"></div>
    <div class="ct-foot" id="art-foot"></div>
  </div>
</div>
<style>
  .art-tot{display:flex;gap:22px;margin:16px 0 4px;}
  .art-tot .cell{display:flex;flex-direction:column;}
  .art-tot .num{font-size:22px;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;}
  .art-tot .num.v{color:var(--lavender);} .art-tot .lbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--overlay0);}
  .art-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:11px;margin-top:14px;}
  .art-card{display:flex;gap:10px;background:var(--surface0);border:1px solid var(--surface1);border-radius:11px;padding:9px;align-items:center;}
  .art-card img{width:52px;height:52px;border-radius:7px;object-fit:cover;background:var(--surface1);flex:0 0 auto;}
  .art-card .ab{min-width:0;flex:1;}
  .art-card .anm{font-size:12px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .art-card .ast{display:flex;gap:9px;font-size:11px;color:var(--subtext);margin-top:4px;font-variant-numeric:tabular-nums;}
  .art-card .ast .v{color:var(--lavender);}
  .art-rank{font-size:11px;font-weight:700;color:var(--overlay0);width:18px;text-align:right;flex:0 0 auto;}
  .ach-modal{position:fixed;inset:0;z-index:300;background:rgba(6,4,14,.72);backdrop-filter:blur(4px);display:none;align-items:flex-start;justify-content:center;padding:5vh 16px;overflow-y:auto;}
  .ct-sect{font-size:13px;font-weight:700;color:var(--text);margin:18px 0 9px;display:flex;align-items:center;gap:7px;}
  .ct-sect .ct-count{font-size:10.5px;font-weight:500;color:var(--overlay0);}
  .ct-sect.official{color:var(--gold);}
  .ct-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:11px;}
  .ct-card{display:flex;flex-direction:column;background:var(--surface0);border:1px solid var(--surface1);border-radius:11px;overflow:hidden;text-decoration:none;transition:transform .12s,box-shadow .12s,border-color .12s;}
  .ct-card:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(0,0,0,.4);border-color:var(--lavender);text-decoration:none;}
  .ct-card.official{border-color:#5a4a1e;} .ct-card.official:hover{border-color:var(--gold);}
  .ct-cover{width:100%;height:104px;object-fit:cover;background:var(--surface1);display:block;}
  .ct-body{padding:9px 11px 11px;display:flex;flex-direction:column;gap:4px;flex:1;}
  .ct-nm{font-size:13px;font-weight:650;color:var(--text);line-height:1.25;}
  .ct-badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:1px;}
  .ct-badges span{font-size:9.5px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;border-radius:5px;padding:1px 6px;background:var(--surface1);color:var(--subtext);}
  .ct-badges .prize{color:#0f1017;background:linear-gradient(180deg,#ffd27a,#e6a94b);}
  .ct-badges .ends-soon{color:var(--peach);border:1px solid var(--peach);background:transparent;}
  .ct-badges .ended{color:var(--overlay0);border:1px solid var(--surface1);background:transparent;}
  .ct-when{font-size:10.5px;color:var(--subtext);margin-top:auto;font-variant-numeric:tabular-nums;}
  .ct-foot{margin-top:20px;font-size:11px;color:var(--overlay0);font-style:italic;}
  .ct-foot a{color:var(--lavender);font-style:normal;}
  .ach-modal{position:fixed;inset:0;z-index:300;background:rgba(6,4,14,.72);backdrop-filter:blur(4px);display:none;align-items:flex-start;justify-content:center;padding:5vh 16px;overflow-y:auto;}
  .ach-modal.open{display:flex;}
  .ach-panel{position:relative;width:760px;max-width:96vw;background:var(--mantle);border:1px solid var(--surface1);border-radius:16px;box-shadow:0 30px 90px rgba(0,0,0,.6);padding:24px 26px 28px;}
  .ach-x{position:absolute;top:12px;right:14px;background:none;border:none;color:var(--subtext);font-size:26px;line-height:1;cursor:pointer;}
  .ach-x:hover{color:var(--text);}
  .ach-htitle{font-size:21px;font-weight:700;color:var(--text);letter-spacing:.01em;}
  .ach-hsub{font-size:12px;color:var(--subtext);margin-top:3px;}
  .ach-hsub b{color:var(--lavender);}
  .ach-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(216px,1fr));gap:11px;margin-top:18px;}
  .ach-card{display:flex;gap:11px;align-items:flex-start;background:var(--surface0);border:1px solid var(--surface1);border-left-width:3px;border-radius:11px;padding:11px 12px;transition:transform .12s,box-shadow .12s;}
  .ach-card.locked{opacity:.62;}
  .ach-card.earned:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(0,0,0,.35);}
  .ach-card .ico{position:relative;width:46px;height:46px;font-size:27px;line-height:1;filter:grayscale(1) brightness(.8);flex-shrink:0;display:flex;align-items:center;justify-content:center;}
  .ach-card.earned .ico{filter:none;}
  .ach-card .ico .ico-badge{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;}
  .ach-card.clickable{cursor:pointer;}
  .ach-card .nm{font-size:13.5px;font-weight:650;color:var(--text);}
  .ach-card .ds{font-size:11px;color:var(--subtext);margin-top:2px;line-height:1.35;}
  .ach-card .tier{font-size:9px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin-top:5px;display:inline-block;}
  .ach-card .unlk{font-size:10px;color:var(--gold);margin-top:4px;}
  .ach-bar{height:5px;border-radius:3px;background:var(--surface1);margin-top:6px;overflow:hidden;}
  .ach-bar i{display:block;height:100%;background:var(--accent);border-radius:3px;}
  .ach-bar+.ach-num{font-size:9.5px;color:var(--overlay0);margin-top:2px;font-variant-numeric:tabular-nums;}
  .ach-card.t-common{border-left-color:#8a8298;} .ach-card.t-common .tier{color:#a9a1b8;}
  .ach-card.t-rare{border-left-color:var(--blue);} .ach-card.t-rare .tier{color:var(--blue);}
  .ach-card.t-epic{border-left-color:var(--purple-bright);} .ach-card.t-epic .tier{color:var(--mauve);}
  .ach-card.t-legendary{border-left-color:var(--gold);} .ach-card.t-legendary .tier{color:var(--gold);}
  .ach-card.earned.t-legendary{box-shadow:0 0 0 1px rgba(212,175,55,.35),0 0 22px rgba(212,175,55,.12);}
  /* feat: gunmetal band, ruby tier text; earned = ruby inner rim + ruby glow */
  .ach-card.t-feat{border-left-color:var(--gunmetal);} .ach-card.t-feat .tier{color:var(--ruby);}
  .ach-card.earned.t-feat{box-shadow:inset 0 0 0 1px rgba(224,53,94,.4),0 0 22px rgba(224,53,94,.14);}
  .ach-card.t-feat.masked{opacity:.5;}
  .ach-card.t-feat.masked .ico{filter:grayscale(1) brightness(.6);}
  .ach-sect{grid-column:1/-1;display:flex;align-items:baseline;gap:9px;font-size:13px;
    font-weight:700;color:var(--text);margin:10px 0 -3px;padding-top:6px;border-top:1px solid var(--surface0);}
  .ach-sect:first-child{margin-top:0;border-top:none;padding-top:0;}
  .ach-sect .cnt{font-size:10.5px;font-weight:500;color:var(--overlay0);font-variant-numeric:tabular-nums;}
  .ach-sect.feats{color:var(--ruby);}
  .ach-sect.feats .cnt{color:var(--gunmetal);}
  .ach-roast{font-size:10.5px;color:#c9b8e6;line-height:1.4;margin-top:6px;padding:5px 8px;
    background:rgba(182,146,230,.07);border-left:2px solid var(--lavender);border-radius:0 7px 7px 0;font-style:italic;}
  .ach-roast.hot{border-left-color:var(--ruby);background:rgba(224,53,94,.08);color:#efc4d2;}
  .ach-nar{width:34px;height:34px;border-radius:50%;object-fit:cover;object-position:60% 30%;
    cursor:pointer;border:1px solid var(--surface1);vertical-align:middle;margin-left:9px;
    transition:transform .12s,border-color .12s;}
  .ach-nar:hover{transform:scale(1.12);border-color:var(--lavender);}
  .ach-unleash{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--ruby);
    margin-left:12px;cursor:pointer;user-select:none;border:1px solid var(--ruby-deep);
    border-radius:999px;padding:3px 10px;background:rgba(224,53,94,.08);}
  .ach-unleash input{accent-color:var(--ruby);}
  .ach-bannerflag{font-size:10px;color:var(--gold);margin-top:4px;}
  .ach-skinhd{font-size:15px;font-weight:700;color:var(--text);margin-top:24px;}
  .ach-skinnote{font-size:10.5px;font-weight:400;color:var(--overlay0);margin-left:6px;}
  .ach-skins{display:flex;flex-wrap:wrap;gap:10px;margin-top:11px;}
  .ach-skin{width:150px;border:1px solid var(--surface1);border-radius:11px;padding:9px;cursor:pointer;background:var(--surface0);transition:border-color .12s,transform .12s;}
  .ach-skin:hover{transform:translateY(-2px);}
  .ach-skin.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);}
  .ach-skin.locked{opacity:.5;cursor:not-allowed;}
  .ach-skin .sw{height:34px;border-radius:7px;display:flex;overflow:hidden;margin-bottom:7px;}
  .ach-skin .sw i{flex:1;}
  .ach-skin .snm{font-size:12px;font-weight:600;color:var(--text);display:flex;align-items:center;gap:5px;}
  .ach-skin .sds{font-size:10px;color:var(--subtext);margin-top:2px;line-height:1.3;}
  .ach-skin .slock{font-size:10px;color:var(--overlay0);}
  .ach-toast{position:fixed;left:50%;top:22%;transform:translate(-50%,-50%);z-index:402;min-width:300px;max-width:90vw;background:var(--mantle);border:1px solid var(--gold);border-radius:14px;padding:16px 22px;box-shadow:0 0 70px rgba(212,175,55,.4);text-align:center;animation:ee-toast 6.5s ease forwards;}
  .ach-toast .at-k{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--gold);}
  .ach-toast .at-n{font-size:19px;font-weight:700;color:var(--text);margin-top:3px;}
  .ach-toast .at-n .ai{margin-right:7px;}
  .ach-toast .at-d{font-size:11.5px;color:var(--subtext);margin-top:4px;}
  /* ---- the achievement MOMENT: toast v2 (the LOCKED design, artifact 335ef4e7) --
     badge medallion sweeps R->L into a cap, mascot leaps from the TOP edge,
     "New Achievement" eyebrow, roast read-along shimmer, metallic rarity pill. ---- */
  .ach-m2{position:fixed;inset:0;z-index:430;display:flex;align-items:center;justify-content:center;
    background:rgba(8,6,16,.78);opacity:0;transition:opacity .35s;padding:20px;}
  .ach-m2.go{opacity:1;}
  .ach-m2.out{opacity:0;transition:opacity .5s;}
  .ach-m2 .tstage{width:min(680px,94vw);}
  .ach-m2 .tw{position:relative;padding-top:158px;cursor:pointer;}
  .ach-m2 .t-common{--tc:#9fbad6;--tcl:#dbe8f5;--tcd:#5f7c9e;}
  .ach-m2 .t-rare{--tc:#7fb0f4;--tcl:#d2e4ff;--tcd:#4a72b8;}
  .ach-m2 .t-epic{--tc:#c69cff;--tcl:#ead9ff;--tcd:#8a5cc4;}
  .ach-m2 .t-legendary{--tc:#e8cb7c;--tcl:#fff4d1;--tcd:#b3924a;}
  /* feat = ruby glow driving --tc; the BAND + PILL go gunmetal below (no pink) */
  .ach-m2 .t-feat{--tc:var(--ruby,#e0355e);--tcl:#f6b8c9;--tcd:var(--ruby-deep,#a11238);}
  .ach-m2 .mglow{position:absolute;top:6px;right:0;width:250px;height:190px;z-index:1;pointer-events:none;
    background:radial-gradient(ellipse at 60% 55%,var(--tc),transparent 66%);filter:blur(22px);opacity:0;}
  .ach-m2 .tw.go .mglow{animation:m2gfade .7s ease 1.3s forwards;}
  @keyframes m2gfade{to{opacity:.55;}}
  .ach-m2 .mascot{position:absolute;top:0;right:26px;height:206px;z-index:2;transform-origin:bottom center;
    filter:drop-shadow(0 12px 16px rgba(0,0,0,.55));opacity:0;transform:translateY(96px) scale(.9);}
  .ach-m2 .tw.go .mascot{animation:m2pop .66s cubic-bezier(.16,.86,.28,1.32) 1.32s forwards;}
  @keyframes m2pop{0%{opacity:0;transform:translateY(96px) scale(.9);}62%{opacity:1;transform:translateY(-10px) scale(1.03);}100%{opacity:1;transform:translateY(0) scale(1);}}
  .ach-m2 .toast{position:relative;z-index:3;background:linear-gradient(180deg,rgba(42,36,63,.94),rgba(24,21,38,.97));
    backdrop-filter:blur(8px);border:1px solid #37314f;border-radius:16px;padding:17px 20px 16px;
    display:flex;gap:16px;align-items:center;box-shadow:0 24px 54px -18px rgba(0,0,0,.72);
    opacity:0;transform:translateY(14px);}
  .ach-m2 .tw.go .toast{animation:m2rise .5s ease forwards;}
  @keyframes m2rise{to{opacity:1;transform:none;}}
  .ach-m2 .toast::before{content:"";position:absolute;left:0;right:0;top:0;height:6px;border-radius:16px 16px 0 0;
    background:linear-gradient(90deg,transparent,var(--tc) 22%,var(--tcl) 50%,var(--tc) 78%,transparent);
    box-shadow:0 0 20px 2px var(--tc);opacity:.95;}
  /* feat band: GUNMETAL metal, still glowing ruby */
  .ach-m2 .t-feat .toast::before{background:linear-gradient(90deg,transparent,var(--gunmetal,#8a93a2) 22%,#c7ccd6 50%,var(--gunmetal,#8a93a2) 78%,transparent);}
  .ach-m2 .cap{position:relative;flex:0 0 auto;width:118px;align-self:stretch;display:flex;align-items:center;justify-content:center;
    margin:-17px 16px -16px -20px;border-radius:16px 0 0 16px;border-right:1px solid rgba(255,255,255,.09);
    background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(0,0,0,.14));box-shadow:inset 0 0 30px -6px var(--tc);}
  /* feat cap: ruby INNER RIM on the medallion well */
  .ach-m2 .t-feat .cap{box-shadow:inset 0 0 30px -6px var(--tc),inset 0 0 0 1px rgba(224,53,94,.4);}
  .ach-m2 .badge{width:100px;height:100px;object-fit:contain;filter:drop-shadow(0 5px 12px rgba(0,0,0,.5));
    opacity:0;transform:translateX(255px) scale(.82);}
  .ach-m2 .badge.emoji{display:flex;align-items:center;justify-content:center;font-size:64px;line-height:1;}
  .ach-m2 .tw.go .badge{animation:m2sweep .62s cubic-bezier(.15,.82,.28,1.24) .15s forwards, m2bding .5s ease .74s;}
  @keyframes m2sweep{0%{opacity:0;transform:translateX(255px) scale(.82);}70%{opacity:1;transform:translateX(-11px) scale(1.06);}100%{opacity:1;transform:translateX(0) scale(1);}}
  @keyframes m2bding{0%{filter:drop-shadow(0 5px 12px rgba(0,0,0,.5)) brightness(1);}
    26%{filter:drop-shadow(0 0 14px var(--tc)) brightness(1.65);}100%{filter:drop-shadow(0 5px 12px rgba(0,0,0,.5)) brightness(1);}}
  .ach-m2 .ring{position:absolute;width:96px;height:96px;border-radius:50%;border:3px solid var(--tc);opacity:0;transform:scale(.4);pointer-events:none;}
  .ach-m2 .tw.go .ring{animation:m2ring .6s ease-out .76s;}
  @keyframes m2ring{0%{opacity:0;transform:scale(.4);}22%{opacity:.85;}100%{opacity:0;transform:scale(1.75);}}
  .ach-m2 .tbody{min-width:0;flex:1;}
  .ach-m2 .tbody .u{font:700 10px/1 sans-serif;letter-spacing:.22em;text-transform:uppercase;color:var(--tc);opacity:0;}
  .ach-m2 .tw.go .tbody .u{animation:m2fade .4s ease .86s forwards;}
  .ach-m2 .tbody .n{font:700 22px/1.08 Georgia,serif;margin:3px 0 5px;opacity:0;color:var(--text);}
  .ach-m2 .tw.go .tbody .n{animation:m2fade .42s ease .98s forwards;}
  .ach-m2 .tbody .r{font-size:13px;line-height:1.5;font-style:italic;opacity:0;margin-top:1px;
    background:linear-gradient(90deg,#b3a2dc 0%,#b3a2dc 43%,#efe6ff 50%,#b3a2dc 57%,#b3a2dc 100%);
    background-size:235% 100%;background-position:118% 0;
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;
    filter:drop-shadow(0 0 5px rgba(198,180,255,.22));}
  .ach-m2 .tw.go .tbody .r{animation:m2fade .46s ease 1.1s forwards, m2readalong 4.8s ease-in-out 1.6s infinite;}
  @keyframes m2readalong{0%{background-position:118% 0;}52%{background-position:-18% 0;}100%{background-position:-18% 0;}}
  @keyframes m2fade{from{opacity:0;transform:translateY(5px);}to{opacity:1;transform:none;}}
  .ach-m2 .tier-pill{position:relative;display:inline-block;margin-top:8px;font:800 9px/1 sans-serif;letter-spacing:.09em;text-transform:uppercase;
    color:#241c10;padding:3px 11px;border-radius:999px;overflow:hidden;
    background:linear-gradient(180deg,var(--tcl),var(--tc) 46%,var(--tcd));border:1px solid var(--tcl);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 0 11px -1px var(--tc);text-shadow:0 1px 0 rgba(255,255,255,.35);opacity:0;}
  /* feat pill: gunmetal METAL, ruby glow around it */
  .ach-m2 .t-feat .tier-pill{background:linear-gradient(180deg,#c7ccd6,var(--gunmetal,#8a93a2) 46%,var(--gunmetal-deep,#4a515c));
    border-color:#c7ccd6;color:#171a20;box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 0 11px -1px var(--tc);}
  .ach-m2 .tw.go .tier-pill{animation:m2fade .4s ease 1.22s forwards;}
  .ach-m2 .tier-pill::after{content:"";position:absolute;top:0;left:-60%;width:45%;height:100%;
    background:linear-gradient(100deg,transparent,rgba(255,255,255,.75),transparent);transform:skewX(-18deg);}
  .ach-m2 .tw.go .tier-pill::after{animation:m2sheen 2.6s ease-in-out 1.6s infinite;}
  @keyframes m2sheen{0%{left:-60%;}30%{left:130%;}100%{left:130%;}}
  .ach-m2 .rwd{display:inline-block;margin:8px 0 0 8px;font-size:11px;color:var(--gold);
    border:1px solid #6b5330;background:rgba(230,200,120,.1);border-radius:7px;padding:3px 9px;opacity:0;}
  .ach-m2 .tw.go .rwd{animation:m2fade .4s ease 1.34s forwards;}
  .m2-conf{position:fixed;top:-3vh;width:7px;height:14px;border-radius:2px;z-index:431;
    pointer-events:none;animation:m2conffall linear forwards;}
  @keyframes m2conffall{to{transform:translateY(112vh) rotate(720deg);opacity:.5;}}
  .ach-m2 .flash{position:absolute;inset:0;border-radius:16px;pointer-events:none;opacity:0;
    background:radial-gradient(circle at 74% -4%,rgba(255,242,206,.9),transparent 58%);}
  .ach-m2 .t-feat .flash{background:radial-gradient(circle at 74% -4%,rgba(255,214,226,.9),transparent 58%);}
  .ach-m2 .tw.go.t-legendary .flash,.ach-m2 .tw.go.t-feat .flash{animation:m2flash .9s ease-out 1.3s;}
  @keyframes m2flash{0%{opacity:0;}20%{opacity:.92;}100%{opacity:0;}}
  @media (prefers-reduced-motion: reduce){ .ach-m2 *{animation:none!important;}
    .ach-m2 .toast,.ach-m2 .badge,.ach-m2 .mascot,.ach-m2 .mglow,.ach-m2 .tbody .u,.ach-m2 .tbody .n,.ach-m2 .tbody .r,.ach-m2 .tier-pill{opacity:1!important;transform:none!important;} }
  /* ---- tier flair frame: 9-slice border-image WRAPS the toast (legendary + feat only) ---- */
  .ach-m2 .tframe{position:relative;z-index:3;}
  .ach-m2 .t-legendary .tframe,.ach-m2 .t-feat .tframe{border-style:solid;border-image-repeat:stretch;opacity:0;transform:translateY(14px);}
  .ach-m2 .tw.go.t-legendary .tframe,.ach-m2 .tw.go.t-feat .tframe{animation:m2rise .5s ease forwards;}
  .ach-m2 .t-legendary .tframe{border-width:46px 44px;border-image-source:url(/branding/frames/legendary.png);border-image-slice:16.8% 13.3% 16.8% 13%;border-image-outset:6px;}
  .ach-m2 .t-feat .tframe{border-width:46px 38px;border-image-source:url(/branding/frames/feat.png);border-image-slice:15.8% 10.3% 16.8% 10%;border-image-outset:6px;}
  /* frame carries the edge + entrance: drop the toast's own border/shadow, keep it static-visible inside */
  .ach-m2 .t-legendary .tframe .toast,.ach-m2 .t-feat .tframe .toast{border-color:transparent;box-shadow:none;opacity:1;transform:none;animation:none;}
  /* CLAIM7 gift box in the reward ribbon (replaces the old emoji) */
  .ach-m2 .rwd .giftbox{height:15px;width:15px;object-fit:contain;vertical-align:-3px;margin-right:5px;}
  /* rung-scaled points chip on the toast (next to the tier pill; feats score 0 -> no chip) */
  .ach-m2 .pts-pill{display:inline-block;margin:8px 0 0 8px;font:800 9px/1 sans-serif;letter-spacing:.06em;color:var(--gold,#e0c268);border:1px solid #6b5330;background:rgba(230,200,120,.12);border-radius:999px;padding:3px 9px;vertical-align:middle;opacity:0;}
  .ach-m2 .tw.go .pts-pill{animation:m2fade .4s ease 1.26s forwards;}
  @media (prefers-reduced-motion: reduce){ .ach-m2 .pts-pill{opacity:1!important;} }
  /* points chip on the achievement-grid tile */
  .ach-card .ach-pts{display:inline-block;margin-left:6px;font:700 10px/1 sans-serif;color:var(--gold,#e0c268);border:1px solid #6b5330;background:rgba(230,200,120,.1);border-radius:6px;padding:2px 6px;vertical-align:middle;}
  @media (prefers-reduced-motion: reduce){ .ach-m2 .tframe{opacity:1!important;transform:none!important;} }
</style>
<style>
  #snip-menu{position:fixed;z-index:236;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:240px;max-width:340px;max-height:300px;overflow-y:auto;padding:5px;}
  #snip-menu .snip-head{display:flex;justify-content:space-between;align-items:center;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--overlay0);padding:3px 6px 5px;}
  #snip-menu .snip-empty{color:var(--subtext);font-size:11.5px;padding:6px;}
  .snip-row{display:flex;gap:4px;align-items:center;}
  .snip-ins{flex:1;text-align:left;background:none;border:none;color:var(--text);font-size:12px;padding:6px 8px;border-radius:5px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .snip-ins:hover{background:var(--surface0);color:var(--lavender);}
  .snip-btn{background:var(--surface0);border:1px solid var(--surface1);color:var(--subtext);border-radius:6px;font-size:11px;padding:3px 8px;cursor:pointer;}
  .snip-btn:hover{color:var(--lavender);border-color:var(--overlay0);}
  /* matches .btn so the balance sits in the same button row; links to the Panel */
  a.acct-chip{font-size:13px;color:var(--text);background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;padding:5px 14px;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;}
  a.acct-chip:hover{border-color:var(--lavender);text-decoration:none;}
  .acct-chip b{color:var(--text);} .acct-chip .cd{color:var(--lavender);}
  .acct-claim{font-size:12px;border:1px solid var(--emerald);background:rgba(166,227,161,.13);color:var(--emerald);border-radius:6px;padding:5px 11px;cursor:pointer;white-space:nowrap;}
  .acct-claim:hover{background:rgba(166,227,161,.24);}
  /* ---- Jobs card: the activity tracker (bottom-left, always openable) ---- */
  #jobs-fab{position:fixed;left:14px;bottom:14px;z-index:234;display:none;align-items:center;gap:7px;background:var(--mantle);border:1px solid var(--surface1);border-radius:999px;box-shadow:0 6px 20px rgba(0,0,0,.45);color:var(--subtext);cursor:pointer;padding:7px 13px 7px 10px;font-size:11.5px;letter-spacing:.02em;transition:border-color .15s,color .15s;}
  #jobs-fab.show{display:inline-flex;}
  #jobs-fab:hover{border-color:var(--lavender);color:var(--text);}
  #jobs-fab .jf-dot{width:8px;height:8px;border-radius:50%;background:var(--overlay0);flex:none;}
  #jobs-fab.busy .jf-dot{background:var(--lavender);box-shadow:0 0 9px rgba(182,146,230,.8);animation:jf-pulse 1.6s ease-in-out infinite;}
  #jobs-fab .jf-badge{background:var(--lavender);color:var(--base);border-radius:999px;font-size:10px;font-weight:700;padding:1px 6px;min-width:15px;text-align:center;display:none;}
  #jobs-fab.busy .jf-badge{display:inline-block;}
  @keyframes jf-pulse{0%,100%{opacity:.5;}50%{opacity:1;}}
  #jobs-tray{position:fixed;left:14px;bottom:14px;z-index:235;width:366px;min-width:260px;max-width:560px;max-height:min(74vh,600px);display:none;flex-direction:column;overflow:hidden;resize:both;background:var(--mantle);border:1px solid var(--surface1);border-radius:12px;box-shadow:0 14px 40px rgba(0,0,0,.55);}
  #jobs-tray.open{display:flex;}
  #jobs-tray .jt-head{display:flex;align-items:center;gap:6px;padding:9px 11px;border-bottom:1px solid var(--surface0);background:linear-gradient(180deg,var(--surface0),transparent);}
  #jobs-tray .jt-title{font-size:11px;text-transform:uppercase;letter-spacing:.11em;color:var(--lavender);font-weight:700;flex:1;display:flex;align-items:center;gap:7px;}
  #jobs-tray .jt-count{color:var(--overlay0);font-weight:600;letter-spacing:.03em;}
  #jobs-tray .jt-hbtn{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:11px;padding:3px 7px;border-radius:6px;}
  #jobs-tray .jt-hbtn:hover{color:var(--text);background:var(--surface1);}
  #jobs-tray .jt-body{overflow:auto;padding:6px;flex:1;}
  .jt-empty{color:var(--overlay0);font-size:12px;text-align:center;padding:30px 16px;line-height:1.55;}
  .jt-item{display:flex;align-items:flex-start;gap:9px;font-size:12px;color:var(--text);padding:8px;border-radius:8px;}
  .jt-item + .jt-item{margin-top:1px;}
  .jt-item:hover{background:var(--surface0);}
  .jt-item.st-failed{background:rgba(243,139,168,.09);}
  .jt-ic{flex:none;width:34px;height:34px;display:flex;align-items:center;justify-content:center;margin-top:1px;position:relative;}
  .jt-ic .gen-moon{margin:0;}
  .jt-glyph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}
  .jt-ok{color:var(--emerald);font-size:15px;} .jt-err{color:var(--red);font-size:15px;}
  .jt-nel{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;}
  .jt-spin{position:relative;width:34px;height:34px;}
  .jt-spin .jt-nel{inset:4px;width:26px;height:26px;border-radius:50%;object-fit:cover;object-position:60% 32%;}
  .jt-spin .gen-ring{position:absolute;inset:2px;border-radius:50%;border:2px solid rgba(182,146,230,.22);border-top-color:var(--lavender);animation:gen-spin .8s linear infinite;}
  .jt-empty-nel{width:104px;height:104px;object-fit:contain;margin:0 auto 8px;display:block;opacity:.92;}
  .jt-main{flex:1;min-width:0;}
  .jt-lab{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .jt-sub{font-size:10.5px;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap;}
  .jt-sub .jt-when{color:var(--overlay0);} .jt-sub .jt-kind{color:var(--subtext);text-transform:capitalize;}
  .jt-errmsg{color:var(--red);font-size:10.5px;margin-top:3px;white-space:normal;}
  .jt-bar{height:4px;border-radius:3px;background:var(--surface1);margin-top:6px;overflow:hidden;}
  .jt-bar i{display:block;height:100%;background:var(--lavender);border-radius:3px;transition:width .3s;}
  .jt-thumb{flex:none;} .jt-thumb img{width:30px;height:30px;border-radius:5px;object-fit:cover;display:block;}
  .jt-x{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:14px;padding:0 2px;flex:none;line-height:1;}
  .jt-x:hover{color:var(--red);}
  /* ---- Toasts: small, corner-stacked, reusable (job notices; achievements can adopt) ---- */
  #mg-toasts{position:fixed;right:16px;top:64px;z-index:420;display:flex;flex-direction:column;gap:9px;align-items:flex-end;pointer-events:none;}
  .mg-toast{pointer-events:auto;min-width:214px;max-width:340px;display:flex;align-items:flex-start;gap:10px;background:var(--mantle);border:1px solid var(--surface1);border-left:3px solid var(--lavender);border-radius:10px;padding:11px 13px;box-shadow:0 10px 30px rgba(0,0,0,.5);animation:mg-toast-in .28s cubic-bezier(.2,.9,.3,1.2);}
  .mg-toast.out{animation:mg-toast-out .3s ease forwards;}
  .mg-toast.ok{border-left-color:var(--emerald);} .mg-toast.err{border-left-color:var(--red);}
  .mg-toast .mt-ic{flex:none;font-size:15px;margin-top:1px;color:var(--lavender);}
  .mg-toast.ok .mt-ic{color:var(--emerald);} .mg-toast.err .mt-ic{color:var(--red);}
  .mg-toast .mt-main{flex:1;min-width:0;}
  .mg-toast .mt-title{font-size:12.5px;color:var(--text);font-weight:600;}
  .mg-toast .mt-msg{font-size:11px;color:var(--subtext);margin-top:2px;white-space:normal;}
  .mg-toast .mt-thumb{width:34px;height:34px;border-radius:6px;object-fit:cover;flex:none;}
  .mg-toast .mt-x{background:none;border:none;color:var(--overlay0);cursor:pointer;font-size:14px;padding:0 1px;flex:none;line-height:1;}
  .mg-toast .mt-x:hover{color:var(--text);}
  @keyframes mg-toast-in{from{opacity:0;transform:translateY(-12px);}to{opacity:1;transform:translateY(0);}}
  @keyframes mg-toast-out{to{opacity:0;transform:translateX(20px);}}
  @media (prefers-reduced-motion: reduce){ #jobs-fab.busy .jf-dot{animation:none;} .mg-toast,.mg-toast.out{animation:none;} }
  #ctx-menu{position:fixed;z-index:230;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:180px;padding:4px;}
  #ctx-menu button{display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font-size:12.5px;padding:7px 10px;border-radius:5px;cursor:pointer;}
  #ctx-menu button:hover{background:var(--surface0);}
  #tag-suggest{position:fixed;z-index:240;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:210px;max-width:320px;padding:4px;}
  #tag-suggest .ts-head{display:flex;justify-content:space-between;gap:14px;color:var(--overlay0);font-size:10px;padding:3px 8px;text-transform:uppercase;letter-spacing:.05em;}
  #tag-suggest button{display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font-size:12.5px;padding:6px 9px;border-radius:5px;cursor:pointer;}
  #tag-suggest button.hot,#tag-suggest button:hover{background:var(--surface0);color:var(--lavender);}
</style>
<script src="/static/picker-core.js"></script>
<script>
var Ach = (function(){
  function el(id){return document.getElementById(id);}
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function fmt(n){ return (Number(n)||0).toLocaleString(); }
  var SKIN_SW={ moonglade:['#0c0a1c','#b692e6','#4fc99a','#d4af37'],
                nightfallen:['#0a0713','#a678f0','#7f6fe0','#d9b3ff'],
                moonlit:['#0b1018','#8fb8e8','#68d5e0','#cfe1f5'],
                ember:['#160c0c','#e8935f','#e0a94b','#ffcf7a'],
                verdant:['#0a1410','#5fd39a','#4fc99a','#c8e6a8'] };
  var data=null;
  function open(){ el('ach-modal').classList.add('open'); el('ach-modal').setAttribute('aria-hidden','false');
    load(false); }
  function close(){ el('ach-modal').classList.remove('open'); el('ach-modal').setAttribute('aria-hidden','true'); }
  function load(mark){
    fetch('/api/achievements'+(mark?'?mark=1':''))
      .then(function(r){return r.json();})
      .then(function(d){ data=d; render(d); if(mark) toastNew(d); syncSkin(d); })
      .catch(function(){});
  }
  var BUCKETS=[['ladder','Evolution Ladders'],['milestone','Milestones'],
               ['mastery','Masteries'],['feat','Feats of the Athenaeum']];
  function unleashed(){ try{ return localStorage.getItem('unleash')==='1'; }catch(e){ return false; } }
  function setUnleash(on){ try{ localStorage.setItem('unleash', on?'1':'0'); }catch(e){}
    if(data) render(data); }
  function card(d,a){
    var masked=a.hidden&&!a.earned;
    var c=document.createElement('div');
    c.className='ach-card t-'+a.tier+(a.earned?' earned':' locked')+(masked?' masked':'');
    var ico=a.earned?('<img class="ico-badge" src="/branding/badges/'+esc(a.id)+'.png" onerror="this.remove()">'+esc(a.icon)):esc(a.icon);
    var body='<div class="ico">'+ico+'</div><div class="bd"><div class="nm">'+esc(a.name)+'</div>'
      +'<div class="ds">'+esc(a.desc)+'</div><span class="tier">'+esc(a.tier)+'</span>'
      +(a.points?'<span class="ach-pts">'+a.points+' pts</span>':'');
    if(a.skin) body+='<div class="unlk">&#9733; unlocks '+esc(skinName(d,a.skin))+' skin</div>';
    if(a.banner_reward) body+='<div class="ach-bannerflag">&#9873; unlocks a banner</div>';
    if(a.earned){ var hot=unleashed()&&a.roast_nsfw, rr=hot?a.roast_nsfw:a.roast;
      if(rr) body+='<div class="ach-roast'+(hot?' hot':'')+'">'+esc(rr)+'</div>'; }
    if(!a.earned && !masked){ var pct=Math.min(100,Math.round(a.current/a.threshold*100));
      body+='<div class="ach-bar"><i style="width:'+pct+'%"></i></div>'
          +'<div class="ach-num">'+fmt(a.current)+' / '+fmt(a.threshold)+'</div>'; }
    body+='</div>'; c.innerHTML=body;
    if(a.earned){ c.classList.add('clickable'); c.title='Replay this celebration';
      c.onclick=function(){ celebrate(a); }; }
    return c;
  }
  function render(d){
    var all=d.achievements||[];
    var feats=all.filter(function(a){return a.tier==='feat';});
    var nonFeat=all.filter(function(a){return a.tier!=='feat';});
    var earned=nonFeat.filter(function(a){return a.earned;}).length;
    var fEarned=feats.filter(function(a){return a.earned;}).length;
    var p=el('ach-progress'); if(p) p.innerHTML='<b>'+earned+'</b> of <b>'+nonFeat.length+'</b> earned'
      +(d.feats_revealed?' &middot; <b style="color:var(--ruby)">'+fEarned+'</b> of '+feats.length+' feats':'')
      +' &middot; <b style="color:var(--gold)">'+fmt(d.earned_points||0)+'</b> / '+fmt(d.possible_points||0)+' pts';
    var slot=el('ach-unleash-slot'); if(slot){
      slot.innerHTML = d.unleash_available
        ? '<label class="ach-unleash"><input type="checkbox" '+(unleashed()?'checked':'')
          +' onchange="Ach.setUnleash(this.checked)">&#128520; Unleash the AI</label>' : ''; }
    var g=el('ach-grid'); if(g){ g.innerHTML='';
      BUCKETS.forEach(function(b){
        if(b[0]==='feat' && !d.feats_revealed) return;   // the tab stays cloaked
        var rows=all.filter(function(a){return (a.bucket||'ladder')===b[0];});
        if(!rows.length) return;
        var h=document.createElement('div'); h.className='ach-sect'+(b[0]==='feat'?' feats':'');
        h.innerHTML=esc(b[1])+' <span class="cnt">'
          +rows.filter(function(a){return a.earned;}).length+'/'+rows.length+'</span>';
        g.appendChild(h);
        rows.forEach(function(a){ g.appendChild(card(d,a)); });
      });
    }
    var sk=el('ach-skins'); if(sk){ sk.innerHTML='';
      (d.skins||[]).forEach(function(s){
        var active=(s.id===d.skin);
        var c=document.createElement('div');
        c.className='ach-skin'+(active?' active':'')+(s.earned?'':' locked');
        var sw=(SKIN_SW[s.id]||SKIN_SW.moonglade).map(function(h){return '<i style="background:'+h+'"></i>';}).join('');
        c.innerHTML='<div class="sw">'+sw+'</div><div class="snm">'+esc(s.name)
          +(active?' <span style="color:var(--accent)">&#10003;</span>':'')+'</div>'
          +'<div class="sds">'+esc(s.desc)+'</div>'
          +(s.earned?'':'<div class="slock">&#128274; locked</div>');
        if(s.earned) c.onclick=function(){ pick(s.id); };
        sk.appendChild(c);
      });
    }
  }
  function skinName(d,id){ var s=(d.skins||[]).filter(function(x){return x.id===id;})[0]; return s?s.name:id; }
  function pick(id){
    fetch('/api/skin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skin:id})})
      .then(function(r){return r.json();})
      .then(function(res){ if(res.skin){ applySkin(res.skin); if(data){ data.skin=res.skin; render(data);} } })
      .catch(function(){});
  }
  function applySkin(id){
    if(id&&id!=='moonglade') document.documentElement.setAttribute('data-skin',id);
    else document.documentElement.removeAttribute('data-skin');
    try{ localStorage.setItem('skin', id||'moonglade'); }catch(e){}
  }
  function syncSkin(d){ // server is source of truth; reconcile the pre-paint guess
    var srv=d.skin||'moonglade', cur=null;
    try{ cur=localStorage.getItem('skin'); }catch(e){}
    if(srv!==cur) applySkin(srv);
  }
  function toastNew(d){
    var newly=(d.newly||[]).map(function(id){
      return (d.achievements||[]).filter(function(a){return a.id===id;})[0]; }).filter(Boolean);
    if(newly.length>3){   // returning user with a full catalog -> one summary, not a barrage
      showToast({icon:'\\ud83c\\udfc6', name:newly.length+' achievements unlocked',
                 desc:'Your catalog just earned a stack of achievements. Open '
                      +'\\ud83c\\udfc6 to review them.', skin:false});
      return;
    }
    newly.forEach(function(a){ celebrate(a); });   // real unlocks get the mid-screen moment (queued)
  }
  // ---- the mid-screen achievement MOMENT: Nel presents the badge, flair scales with rarity ----
  var _q=[], _playing=false, _actx=null, _sfx={};
  /* Real SFX first: branding/sfx/ach_<tier>.ogg (drop a file in, it just works);
     missing/blocked file falls back to the synth chime. Result cached per tier. */
  function _chime(tier){
    var key=tier||'common';
    if(_sfx[key]===0){ _synth(tier); return; }
    try{
      var au=new Audio('/branding/sfx/ach_'+key+'.ogg'); au.volume=0.7;
      au.play().then(function(){ _sfx[key]=1; })
               .catch(function(){ _sfx[key]=0; _synth(tier); });
    }catch(e){ _sfx[key]=0; _synth(tier); }
  }
  function _synth(tier){
    try{ _actx=_actx||new (window.AudioContext||window.webkitAudioContext)(); if(_actx.state==='suspended')_actx.resume(); }catch(e){ return; }
    var seq={common:[523,660],rare:[523,660,784],epic:[523,660,784,988],legendary:[392,523,660,784,1047],
             feat:[392,466,622,932]}[tier]||[660];
    var t=_actx.currentTime+0.02;
    seq.forEach(function(f,i){ var o=_actx.createOscillator(),g=_actx.createGain(); o.type='triangle'; o.frequency.value=f;
      o.connect(g); g.connect(_actx.destination); var s=t+i*0.1;
      g.gain.setValueAtTime(0.0001,s); g.gain.linearRampToValueAtTime(0.15,s+0.02); g.gain.exponentialRampToValueAtTime(0.0001,s+0.5);
      o.start(s); o.stop(s+0.55); });
    if(tier==='legendary'||tier==='feat'){ var lo=_actx.createOscillator(),lg=_actx.createGain(); lo.type='sine'; lo.frequency.value=(tier==='feat'?78:98);
      lo.connect(lg); lg.connect(_actx.destination); lg.gain.setValueAtTime(0.0001,t); lg.gain.linearRampToValueAtTime(0.28,t+0.02);
      lg.gain.exponentialRampToValueAtTime(0.0001,t+1.2); lo.start(t); lo.stop(t+1.3); }
  }
  /* Build one toast-v2 moment (the locked 335ef4e7 design). opts: eyebrow, line,
     pill:false, badge:false (emoji instead), mascot:false. */
  function _mkMoment(a, opts){
    opts=opts||{};
    var tier=a.tier||'common';
    var m=document.createElement('div'); m.className='ach-m2';
    var stage=document.createElement('div'); stage.className='tstage';
    var tw=document.createElement('div'); tw.className='tw t-'+tier;
    var line=(opts.line!=null)?opts.line
      :((unleashed()&&a.roast_nsfw)?a.roast_nsfw:(a.roast||a.desc||''));
    var rwd='';                                  // reward ribbon (gift box + text)
    if(a.skin) rwd='Unlocks skin: '+skinName(data||{skins:[]}, a.skin);
    else if(a.banner_reward) rwd='Unlocks a banner';
    // tier flair frame (9-slice border-image) wraps the toast for the top tiers only;
    // add epic:1 to frame epic too. Summary toasts (opts.badge===false) never get a frame.
    var framed=(!!({legendary:1,feat:1}[tier]))&&opts.badge!==false;
    var toastHTML='<div class="toast"><div class="cap"></div>'
      +'<div class="tbody"><div class="u">'+esc(opts.eyebrow||'New Achievement')+'</div>'
      +'<div class="n">'+esc(a.name)+'</div>'
      +'<div class="r">'+esc(line)+'</div>'
      +(opts.pill===false?'':'<span class="tier-pill">'+esc(tier)+'</span>')
      +((a.points&&opts.pill!==false)?'<span class="pts-pill">+'+a.points+'</span>':'')
      +(rwd?'<span class="rwd"><img class="giftbox" src="/branding/rewards/gift.png" onerror="this.remove()">'+esc(rwd)+'</span>':'')
      +'</div><div class="flash"></div></div>';
    tw.innerHTML='<div class="mglow"></div>'+(framed?'<div class="tframe">'+toastHTML+'</div>':toastHTML);
    stage.appendChild(tw); m.appendChild(stage);
    var cap=tw.querySelector('.cap');
    if(opts.badge===false){                       // summary: trophy in the well
      var e2=document.createElement('div'); e2.className='badge emoji';
      e2.textContent=a.icon||'🏆'; cap.appendChild(e2);
    } else {                                       // the medallion sweeps R->L into the cap
      var b=document.createElement('img'); b.className='badge';
      b.onerror=function(){ var e=document.createElement('div'); e.className='badge emoji';
        e.textContent=a.icon||'🏆';
        if(this.parentNode){ this.parentNode.replaceChild(e,this); } };
      b.src='/branding/badges/'+encodeURIComponent(a.id)+'.png';
      cap.appendChild(b);
      var ring=document.createElement('div'); ring.className='ring'; cap.appendChild(ring);
    }
    if(opts.mascot!==false){                       // the mascot leaps from the TOP edge
      var mfall=(tier==='feat')?'legendary':tier;
      var nel=document.createElement('img'); nel.className='mascot';
      // ANIMATED mascot first (drop <id>.webp beside the stills and it just moves),
      // then the still, then the tier chibi, then none. All fail-soft 404 hops.
      var chain=['/branding/mascots/ach/'+encodeURIComponent(a.id)+'.webp',
                 '/branding/mascots/ach/'+encodeURIComponent(a.id)+'.png',
                 '/branding/mascots/present_'+mfall+'.png'];
      var ci=0;
      nel.onerror=function(){ ci++; if(ci<chain.length){ this.src=chain[ci]; } else { this.remove(); } };
      nel.onload=function(){ try{ _seatMascot(this); }catch(e){} };
      nel.src=chain[0];
      tw.insertBefore(nel, tw.querySelector('.tframe')||tw.querySelector('.toast'));
    }
    return {m:m, tw:tw};
  }
  /* Adaptive seating: whatever padding the source image carries, seat the mascot so
     ~75% of its OPAQUE artwork rises above the toast band. Reads the alpha bounding
     box off a small canvas sample; any failure leaves the CSS defaults. */
  function _seatMascot(img){
    var W=48, H=64, c=document.createElement('canvas'); c.width=W; c.height=H;
    var x=c.getContext('2d'); x.drawImage(img,0,0,W,H);
    var d=x.getImageData(0,0,W,H).data, top=-1, bot=-1, r, q;
    for(r=0;r<H&&top<0;r++){ for(q=3;q<W*4;q+=16){ if(d[r*W*4+q]>24){ top=r; break; } } }
    for(r=H-1;r>=0&&bot<0;r--){ for(q=3;q<W*4;q+=16){ if(d[r*W*4+q]>24){ bot=r; break; } } }
    if(top<0||bot<=top) return;
    var opFrac=(bot-top+1)/H, topFrac=top/H;
    var BAND=158, TARGET=150;                      // ~150px of visible character
    var h=Math.max(140, Math.min(260, TARGET/opFrac));
    img.style.height=h+'px';
    img.style.top=(BAND - h*topFrac - 0.75*(h*opFrac)).toFixed(1)+'px';
  }
  /* Legendary + feat fanfare: the ROOM blows up around the toast (screen-level
     star rain + confetti, tier-colored) -- the flair the old moment had. */
  function _fanfare(m, tier){
    var glyphs=['\\u2726','\\u2727','\\u2b50'], i, s, cn;
    for(i=0;i<46;i++){ s=document.createElement('div'); s.className='ee-star';
      s.textContent=glyphs[i%3]; s.style.left=(Math.random()*100)+'vw';
      s.style.color=(tier==='feat')?'var(--ruby)':'var(--gold)';
      s.style.fontSize=(12+Math.random()*22)+'px';
      s.style.animationDuration=(2.4+Math.random()*2.4)+'s';
      s.style.animationDelay=(Math.random()*1.4)+'s'; m.appendChild(s); }
    var cols=(tier==='feat')?['#e0355e','#8a93a2','#a11238','#d6d2e2','#4a515c']
                            :['#b692e6','#d4af37','#4fc99a','#c4a6f0','#ffffff'];
    for(i=0;i<80;i++){ cn=document.createElement('i'); cn.className='m2-conf';
      cn.style.background=cols[i%cols.length]; cn.style.left=(Math.random()*100)+'vw';
      cn.style.animationDuration=(1.8+Math.random()*1.8)+'s';
      cn.style.animationDelay=(0.2+Math.random()*0.9)+'s'; m.appendChild(cn); }
  }
  function _play(built, hold, after){
    var m=built.m, tw=built.tw;
    document.body.appendChild(m);
    void m.offsetWidth; m.classList.add('go'); tw.classList.add('go');
    var done=function(){ if(m._d)return; m._d=true; m.classList.add('out');
      setTimeout(function(){ if(m.parentNode)m.remove(); if(after)after(); }, 500); };
    m._t=setTimeout(done, hold);
    m.addEventListener('click', function(){ clearTimeout(m._t); done(); });
  }
  function celebrate(a){ if(a){ _q.push(a); if(!_playing) _next(); } }
  function _next(){
    if(!_q.length){ _playing=false; return; } _playing=true;
    var a=_q.shift(), tier=a.tier||'common';
    var hold={common:4200,rare:4800,epic:5400,legendary:6400,feat:6400}[tier]||4600;
    _chime(tier);
    var built=_mkMoment(a,{});
    if(tier==='legendary'||tier==='feat') _fanfare(built.m, tier);
    _play(built, hold, _next);
  }
  function showToast(a){    // the >3-unlock SUMMARY, in the same toast-v2 frame
    _play(_mkMoment({name:a.name, tier:'legendary', icon:a.icon||'🏆', id:''},
                    {badge:false, mascot:false, pill:false,
                     eyebrow:'Achievement Unlocked', line:a.desc||''}),
          6500, null);
  }
  // ---- the narrator: poke until it snaps (Triggered feat -> the Unleash toggle) ----
  var POKES=['The narrator ignores you.',
             'The narrator raises an eyebrow. Do you mind?',
             'The narrator is DESCRIBING things. Hands off.',
             'The narrator’s eye twitches. Last warning.',
             'FINE. You want the REAL commentary? Unleashed. Happy now?'];
  function poke(){
    fetch('/api/ach-event',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({event:'narrator'})})
      .then(function(r){return r.json();})
      .then(function(res){
        var n=Math.max(1,Math.min(res.pokes||1,POKES.length));
        try{ Toast.show({title:POKES[n-1], kind:(n>=POKES.length?'err':''), icon:'👆'}); }catch(e){}
        if(res.snapped) load(true);   // fires the Triggered celebration + reveals the toggle
      })
      .catch(function(){});
  }
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  // On load: mark-and-toast any freshly earned feats, and reconcile the active skin.
  document.addEventListener('DOMContentLoaded', function(){ load(true); });
  return { open:open, close:close, poke:poke, setUnleash:setUnleash };
})();
var Contests = (function(){
  function el(id){return document.getElementById(id);}
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function fmt(n){ return (Number(n)||0).toLocaleString(); }
  var showAll=false, loaded=false;
  function open(){ el('contest-modal').classList.add('open'); el('contest-modal').setAttribute('aria-hidden','false');
    if(!loaded) load(); }
  function close(){ el('contest-modal').classList.remove('open'); el('contest-modal').setAttribute('aria-hidden','true'); }
  function toggleAll(ev){ if(ev) ev.preventDefault(); showAll=!showAll;
    el('ct-all').textContent = showAll ? 'Active only' : 'Show ended too'; load(); }
  function load(){
    el('contest-sub').textContent='Loading the community\\u2026';
    fetch('/api/contests'+(showAll?'?all=1':''))
      .then(function(r){return r.json();})
      .then(function(d){ loaded=true; render(d); })
      .catch(function(){ el('contest-sub').textContent='Could not load contests.'; });
  }
  function daysLeft(endIso){
    if(!endIso) return null;
    var ms=new Date(endIso).getTime()-Date.now();
    if(isNaN(ms)) return null;
    return Math.ceil(ms/86400000);
  }
  function card(c){
    var a=document.createElement('a');
    a.className='ct-card'+(c.type==='official'?' official':'');
    a.href=c.url||'#'; a.target='_blank'; a.rel='noopener';
    var cover = c.cover_url ? '<img class="ct-cover" loading="lazy" src="'+esc(c.cover_url)+'" alt="" onerror="this.style.display=\\'none\\'">' : '<div class="ct-cover"></div>';
    var badges='';
    if(c.prize_amount) badges+='<span class="prize">\\u2666 '+fmt(c.prize_amount)+' cr</span>';
    var dl=daysLeft(c.end_at);
    if(!c.active) badges+='<span class="ended">ended</span>';
    else if(dl!=null && dl<=2) badges+='<span class="ends-soon">'+(dl<=0?'ends today':(dl+'d left'))+'</span>';
    if(c.vote_type) badges+='<span>'+esc(c.vote_type.replace(/_/g,' '))+'</span>';
    var when=((c.start_at||'').slice(0,10))+' \\u2192 '+((c.end_at||'').slice(0,10))
      + (c.active && dl!=null && dl>2 ? '  \\u00b7 '+dl+' days left' : '');
    a.innerHTML=cover+'<div class="ct-body"><div class="ct-nm">'+esc(c.title||'(untitled)')+'</div>'
      +'<div class="ct-badges">'+badges+'</div><div class="ct-when">'+esc(when)+'</div></div>';
    return a;
  }
  function section(list, name, cls){
    if(!list.length) return '';
    var wrap=document.createElement('div');
    var hd=document.createElement('div'); hd.className='ct-sect '+cls;
    hd.innerHTML=name+' <span class="ct-count">'+list.length+'</span>';
    var grid=document.createElement('div'); grid.className='ct-grid';
    list.forEach(function(c){ grid.appendChild(card(c)); });
    wrap.appendChild(hd); wrap.appendChild(grid); return wrap;
  }
  function render(d){
    var body=el('contest-body'); body.innerHTML='';
    var list=d.contests||[];
    if(d.error){ el('contest-sub').textContent='\\u26a0 '+d.error; return; }
    if(!list.length){ el('contest-sub').textContent = showAll?'No contests found.':'No contests running right now \\u2014 check back soon.'; return; }
    var official=list.filter(function(c){return c.type==='official';});
    var community=list.filter(function(c){return c.type!=='official';});
    el('contest-sub').innerHTML='<b>'+official.length+'</b> official \\u00b7 <b>'+community.length+'</b> community '+(showAll?'(all)':'running now');
    var so=section(official,'\\ud83c\\udf1f Official','official'); if(so) body.appendChild(so);
    var sc=section(community,'\\ud83e\\udd1d Community','community'); if(sc) body.appendChild(sc);
  }
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  return { open:open, close:close, toggleAll:toggleAll };
})();
var YourArt = (function(){
  function el(id){return document.getElementById(id);}
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function fmt(n){ return (Number(n)||0).toLocaleString(); }
  var loaded=false;
  function open(){ el('art-modal').classList.add('open'); el('art-modal').setAttribute('aria-hidden','false'); if(!loaded) load(); }
  function close(){ el('art-modal').classList.remove('open'); el('art-modal').setAttribute('aria-hidden','true'); }
  function load(){
    el('art-sub').textContent='Loading\\u2026';
    fetch('/api/your-art').then(function(r){return r.json();}).then(function(d){ loaded=true; render(d); })
      .catch(function(){ el('art-sub').textContent='Could not load your art.'; });
  }
  function render(d){
    var items=d.items||[], t=d.totals||{};
    if(!t.count){ el('art-sub').innerHTML='No published art synced yet \\u2014 run <code>--sync-artworks</code> to pull your posted works\\u2019 stats.'; el('art-grid').innerHTML=''; el('art-foot').textContent=''; return; }
    el('art-sub').innerHTML='<div class="art-tot">'
      +'<div class="cell"><span class="num">'+fmt(t.count)+'</span><span class="lbl">published</span></div>'
      +(d.views_synced?'<div class="cell"><span class="num v">'+fmt(t.views_top)+'</span><span class="lbl">views (top 12)</span></div>':'')
      +'<div class="cell"><span class="num">'+fmt(t.likes)+'</span><span class="lbl">likes</span></div>'
      +'<div class="cell"><span class="num">'+fmt(t.comments)+'</span><span class="lbl">comments</span></div></div>'
      +'<div style="font-size:12px;color:var(--subtext);margin-top:2px;">Your top posts'+(d.views_synced?' by views':' by likes')+':</div>';
    var g=el('art-grid'); g.innerHTML='';
    items.forEach(function(m,i){
      var c=document.createElement('div'); c.className='art-card';
      var stats='';
      if(m.views!=null) stats+='<span class="v">\\ud83d\\udc41 '+fmt(m.views)+'</span>';
      stats+='<span>\\u2665 '+fmt(m.likes)+'</span>';
      if(m.comments) stats+='<span>\\ud83d\\udcac '+fmt(m.comments)+'</span>';
      if(m.aes_score) stats+='<span>\\u2726 '+esc(String(m.aes_score).slice(0,4))+'</span>';
      c.innerHTML='<span class="art-rank">'+(i+1)+'</span>'
        +'<img loading="lazy" src="/thumbs/'+esc(m.media_id)+'.jpg" alt="" onerror="this.style.visibility=\\'hidden\\'">'
        +'<div class="ab"><div class="anm" title="'+esc(m.title||m.prompt_preview||'')+'">'+esc(m.title||m.prompt_preview||'(untitled)')+'</div>'
        +'<div class="ast">'+stats+'</div></div>';
      g.appendChild(c);
    });
    el('art-foot').innerHTML = d.views_synced ? 'Live view counts, fetched fresh. Likes/comments from your last <code>--sync-artworks</code>.'
      : 'Ranked by likes (live views load on the localhost server). Run <code>--sync-artworks</code> to refresh stats.';
  }
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  return { open:open, close:close };
})();
var Picker = (function(){
  // Browse/filter/page/infinite-scroll logic lives in PickerCore now (shared with the
  // Loom's GalleryPick); this IIFE is a thin DOM-binding shim over it -- same ids, same
  // CSS, same 3 call sites, same behavior as before the refactor.
  var cb=null, core=null;
  function el(id){return document.getElementById(id);}
  function readFilters(){
    var v=function(id){ var e=el(id); return e?e.value:''; };
    return {collection:v('pick-collection'), source:v('pick-source'), rating_min:v('pick-rating'), sort:v('pick-sort')};
  }
  function markLoading(){ el('pick-grid').style.opacity='.5'; var mb=el('pick-more'); if(mb) mb.style.display='none'; }
  function ensureCore(){
    if(core) return core;
    // type stays '' -- /api/gallery-images already treats '' the same as an absent
    // param (defaults to "image"), so this is byte-identical to the pre-refactor
    // behavior (images only) with no explicit type filter in this UI.
    core = PickerCore.create({
      onResults: function(imgs, meta){
        var grid=el('pick-grid'), empty=el('pick-empty'), moreBtn=el('pick-more');
        grid.style.opacity='1';
        if(!meta.append) grid.innerHTML='';
        if(!imgs.length && !meta.append){ empty.textContent='No images found.'; empty.style.display='block'; if(moreBtn) moreBtn.style.display='none'; return; }
        empty.style.display='none';
        imgs.forEach(function(m){ var c=document.createElement('div'); c.className='pick-cell'; c.title=m.prompt||m.media_id;
          c.innerHTML='<img loading="lazy" decoding="async" src="'+m.thumb+'" alt="">';
          c.onclick=function(){ pick(m); }; grid.appendChild(c); });
        if(moreBtn) moreBtn.style.display = meta.hasMore ? '' : 'none';
        // If the loaded tiles don't fill the grid there's no scrollbar to drive infinite
        // scroll -- pull one more page so it overflows (core caps this so a tall window
        // can't runaway-load; the Load-more button covers the rest).
        core.maybeFillPage(grid);
      },
      onError: function(){ el('pick-grid').style.opacity='1'; }
    });
    return core;
  }
  function open(callback){ cb=callback; el('pick-scrim').classList.add('open'); el('pick-modal').classList.add('open');
    el('pick-q').value=''; markLoading();
    ensureCore().setFilters(Object.assign({q:''}, readFilters()));
    setTimeout(function(){el('pick-q').focus();},120);
    try{ el('pick-copy').checked = localStorage.getItem('pick-copyprompt')==='1'; }catch(e){} }
  function close(){ el('pick-scrim').classList.remove('open'); el('pick-modal').classList.remove('open'); cb=null; }
  function onInput(){ ensureCore().setQuery(el('pick-q').value.trim()); }
  function onFilter(){ markLoading(); ensureCore().setFilters(readFilters()); }
  function pick(m, thumb){
    try{ if(el('pick-copy').checked && m.prompt && navigator.clipboard) navigator.clipboard.writeText(m.prompt); }catch(e){}
    var f=cb; close(); if(f) f(m.media_id, thumb||m.thumb, m.prompt||'');
  }
  function more_(){ ensureCore().loadMore(); }
  function onScroll(){ ensureCore().onScroll(el('pick-grid'), 320); }
  function toggleCopy(){ try{ localStorage.setItem('pick-copyprompt', el('pick-copy').checked?'1':'0'); }catch(e){} }
  function upload(){ el('pick-file').click(); }
  function onFile(){
    var f=el('pick-file').files[0]; if(!f) return;
    var empty=el('pick-empty'); empty.textContent='Uploading '+f.name+'\\u2026'; empty.style.display='block';
    var fd=new FormData(); fd.append('file', f);
    fetch('/api/upload',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(d){
      el('pick-file').value='';
      if(d.error||!d.media_id){ empty.textContent='\\u26a0 Upload failed: '+(d.error||'no media id'); return; }
      empty.style.display='none';
      pick({media_id:d.media_id, prompt:''}, URL.createObjectURL(f));
    }).catch(function(){ el('pick-file').value=''; empty.textContent='\\u26a0 Upload failed (network).'; });
  }
  return {open:open, close:close, onInput:onInput, onFilter:onFilter, onScroll:onScroll, more:more_, toggleCopy:toggleCopy, upload:upload, onFile:onFile};
})();
document.addEventListener('DOMContentLoaded', function(){
  var pq=document.getElementById('pick-q'); if(pq) pq.addEventListener('input', Picker.onInput);
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') Picker.close(); });
});
/* ---- Account balance chip (credits + free cards) in the header ---- */
var Acct = (function(){
  function chip(){ return document.getElementById('acct-chip'); }
  function claimEl(){ return document.getElementById('acct-claim'); }
  var CKEY='mg_acct';
  function daysUntil(d){ if(!d) return 999; var t=(new Date(d+'T00:00:00')).getTime();
    return isNaN(t)?999:Math.ceil((t-Date.now())/86400000); }
  function paint(d){
    var c=chip(); if(!c) return;
    var parts=[]; if(d.credits!=null) parts.push('\\u25c8 <b>'+Number(d.credits).toLocaleString()+'</b>');
    if(d.cards!=null) parts.push('<span class="cd">\\ud83c\\udfab '+d.cards+'</span>');
    // urgency: soonest card expiry, or a subscription cliff that stops card grants
    var warn=[], ce=daysUntil(d.card_expiry);
    if(d.card_expiry && ce<=3) warn.push('cards expire in '+Math.max(0,ce)+'d ('+d.card_expiry+')');
    if(d.sub && d.sub.cancel && d.sub.end && daysUntil(d.sub.end)<=7)
      warn.push('premium ends '+d.sub.end+' \\u2014 card grants stop');
    if(parts.length){ c.innerHTML=(warn.length?'\\u26a0 ':'')+parts.join(' \\u00b7 '); c.style.display=''; }
    // rich tooltip: per-card breakdown + any warnings
    var tip=['Your PixAI balance \\u2014 open the Control Panel'];
    (d.cards_by||[]).forEach(function(k){ if(k.count) tip.push('\\ud83c\\udfab '+k.count+' '+(k.name||'')+(k.expires?' (exp '+k.expires+')':'')); });
    warn.forEach(function(w){ tip.push('\\u26a0 '+w); });
    c.title=tip.join('\\n');
    // claimable free-credits badge
    var b=claimEl();
    if(b){ if(d.claim_credits){ b.textContent='\\ud83c\\udf81 +'+Number(d.claim_credits).toLocaleString()+' claim'; b.style.display=''; }
           else b.style.display='none'; }
  }
  function refresh(){
    var c=chip(); if(!c) return;
    // Paint the last-known balance instantly so navigating never shows a blank chip.
    try{ var cached=JSON.parse(localStorage.getItem(CKEY)||'null'); if(cached) paint(cached); }catch(e){}
    fetch('/api/account').then(function(r){return r.json();}).then(function(d){
      // Only a fully-successful read (credits present) updates the chip; a transient
      // miss or error keeps the last-known value instead of blanking it.
      if(d.error || d.credits==null){ coverage(d); return; }
      var good={credits:d.credits, cards:(d.cards!=null?d.cards:0), cards_by:d.cards_by,
                card_expiry:d.card_expiry, claim_credits:d.claim_credits, sub:d.sub};
      try{ localStorage.setItem(CKEY, JSON.stringify(good)); }catch(e){}
      paint(good); coverage(d);
    }).catch(function(){});
  }
  function claim(){
    var b=claimEl(); if(b) b.textContent='claiming\\u2026';
    fetch('/api/claim',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
      if(d && d.error){ if(window.Toast) Toast.show({kind:'err',title:'Claim failed',msg:d.error}); }
      else if(window.Toast) Toast.show({kind:'ok',title:'Claimed +'+Number((d&&d.credits)||0).toLocaleString()+' credits'});
      refresh();
    }).catch(function(){ refresh(); });
  }
  function coverage(d){
    var b=document.getElementById('cover-badge');
    if(!b || d.coverage_pct==null || !d.server_tasks){ return; }
    var pct=d.coverage_pct;
    b.className='cover-badge '+(pct>=99.5?'full':(pct>=90?'high':'low'));
    b.innerHTML='\\ud83d\\udcbe <b>'+pct+'%</b> backed up';
    b.title=d.local_tasks.toLocaleString()+' of '+d.server_tasks.toLocaleString()
      +' generation tasks archived locally'+(pct>=99.5?' \\u2014 complete backup \\u2728':'');
    b.style.display='';
  }
  return {refresh:refresh, claim:claim};
})();
/* ---- Toasts: small corner notices, reusable (job notices now; achievements can adopt) ---- */
var Toast = (function(){
  function box(){ var b=document.getElementById('mg-toasts');
    if(!b){ b=document.createElement('div'); b.id='mg-toasts'; b.setAttribute('aria-live','polite'); document.body.appendChild(b); }
    return b; }
  function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function show(o){
    o=o||{};
    var kind=o.kind||'';   // '' | 'ok' | 'err'
    var el=document.createElement('div');
    el.className='mg-toast'+(kind?(' '+kind):'');
    var ic=o.icon||(kind==='ok'?'\\u2713':(kind==='err'?'\\u26a0':'\\u25c9'));
    var thumb=o.thumb?'<img class="mt-thumb" src="'+esc(o.thumb)+'" alt="">':'';
    el.innerHTML='<span class="mt-ic">'+ic+'</span><div class="mt-main"><div class="mt-title">'+esc(o.title||'')+'</div>'
      +(o.msg?'<div class="mt-msg">'+esc(o.msg)+'</div>':'')+'</div>'+thumb
      +'<button class="mt-x" aria-label="Dismiss">\\u00d7</button>';
    function remove(){ if(!el.parentNode) return; el.classList.add('out'); setTimeout(function(){ if(el.parentNode) el.parentNode.removeChild(el); }, 320); }
    el.querySelector('.mt-x').onclick=remove;
    box().appendChild(el);
    if(!o.sticky){ setTimeout(remove, o.ttl||5200); }
    return remove;
  }
  return {show:show};
})();
/* ---- Jobs: submit-driver. Registers each gen in the server activity log, then polls
   task-status so the download+catalog still happens (and survives the drawer closing).
   The CARD (JobsCard) renders from the server log, NOT from here. ---- */
var Jobs = (function(){
  var seen={};
  function track(id, label, cb){
    if(!id || seen[id]) return; seen[id]=true;
    // Register immediately so the card shows it running (paper trail survives reload).
    fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({job_id:id, type:'generate', label:label||'Generation', status:'running'})}).catch(function(){});
    if(window.JobsCard) JobsCard.refresh();
    poll(id, cb);
  }
  function poll(id, cb){
    fetch('/api/task-status?task_id='+encodeURIComponent(id)).then(function(r){return r.json();}).then(function(d){
      if(d.phase==='done'){ if(cb) cb('done', d); if(window.JobsCard) JobsCard.refresh(); }
      else if(d.phase==='failed'){ if(cb) cb('failed', d); if(window.JobsCard) JobsCard.refresh(); }
      else { if(cb) cb('running', d); setTimeout(function(){ poll(id, cb); }, 3000); }
    }).catch(function(){ setTimeout(function(){ poll(id, cb); }, 4000); });
  }
  return {track:track};
})();
/* ---- JobsCard: the always-openable activity card, backed by /api/jobs. Renders the
   server-side job log (survives reload), shows a short history, fires toasts on
   completion/failure, and keeps failures until dismissed. ---- */
var JobsCard = (function(){
  var last={}, seeded=false, timer=null, LSK='mg_jobs_open';
  function el(i){ return document.getElementById(i); }
  function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function isOpen(){ try{ return localStorage.getItem(LSK)==='1'; }catch(e){ return false; } }
  function applyState(){
    var t=el('jobs-tray'), f=el('jobs-fab'); if(!t||!f) return;
    if(isOpen()){ t.classList.add('open'); f.classList.remove('show'); }
    else { t.classList.remove('open'); f.classList.add('show'); }
  }
  function setOpen(v){ try{ localStorage.setItem(LSK, v?'1':'0'); }catch(e){} applyState(); }
  function open(){ setOpen(true); refresh(); }
  function close(){ setOpen(false); }
  function ago(ts){
    var s=Math.max(0, Math.floor(Date.now()/1000 - (ts||0)));
    if(s<60) return 'just now';
    if(s<3600) return Math.floor(s/60)+'m ago';
    if(s<86400) return Math.floor(s/3600)+'h ago';
    return Math.floor(s/86400)+'d ago';
  }
  function row(j){
    var st=j.status||'running', fin=(st==='done'||st==='failed');
    var ic = st==='done'
           ? '<span class="jt-ok jt-glyph">\\u2713</span><img class="jt-nel" src="/branding/mascots/trk_done.png" onerror="this.remove()">'
           : st==='failed'
           ? '<span class="jt-err jt-glyph">\\u26a0</span><img class="jt-nel" src="/branding/mascots/trk_fail.png" onerror="this.remove()">'
           : '<span class="jt-spin"><img class="jt-nel" src="/branding/gen_nel.png" onerror="this.remove()"><i class="gen-ring"></i></span>';
    var mid=(j.media_ids||[])[0]||'';
    var thumb=(st==='done'&&mid)?'<a class="jt-thumb" href="/image/'+encodeURIComponent(mid)+'"><img src="/thumbs/'+encodeURIComponent(mid)+'.jpg" alt=""></a>':'';
    var bar='';
    if(st==='running' && j.total){ var pct=Math.min(100, Math.round((j.done||0)/j.total*100)); bar='<div class="jt-bar"><i style="width:'+pct+'%"></i></div>'; }
    var errmsg=(st==='failed'&&j.error)?'<div class="jt-errmsg">'+esc(j.error)+'</div>':'';
    var sub='<div class="jt-sub"><span class="jt-kind">'+esc(j.type||'job')+'</span><span class="jt-when">'+ago(j.ts)+'</span></div>';
    var x=fin?'<button class="jt-x" data-job="'+esc(j.job_id)+'" title="Dismiss">\\u00d7</button>':'';
    return '<div class="jt-item'+(st==='failed'?' st-failed':'')+'"><div class="jt-ic">'+ic+'</div>'
         +'<div class="jt-main"><div class="jt-lab">'+esc(j.label||'Generation')+'</div>'+sub+bar+errmsg+'</div>'
         +thumb+x+'</div>';
  }
  function render(jobs){
    var t=el('jobs-tray'); if(!t) return;
    var running=0; jobs.forEach(function(j){ if((j.status||'running')==='running') running++; });
    var head='<div class="jt-head"><span class="jt-title">\\u25c9 Activity'
      +(jobs.length?' <span class="jt-count">'+jobs.length+'</span>':'')+'</span>'
      +'<button class="jt-hbtn" data-act="clear" title="Clear finished">clear</button>'
      +'<button class="jt-hbtn" data-act="close" title="Collapse">\\u2013</button></div>';
    var body='';
    if(!jobs.length){ body='<div class="jt-empty"><img class="jt-empty-nel" src="/branding/mascots/trk_empty.png" onerror="this.remove()"><div>The archive is quiet.<br>Generations and syncs will appear here.</div></div>'; }
    else { jobs.forEach(function(j){ body+=row(j); }); }
    t.innerHTML=head+'<div class="jt-body">'+body+'</div>';
    var f=el('jobs-fab'); if(f){ f.classList.toggle('busy', running>0); var b=el('jobs-fab-badge'); if(b) b.textContent=running||''; }
    var live=el('gen-live');
    if(live){
      if(running){
        if(!live.querySelector('.gen-nel-wrap')){   // build the spinner once so it doesn't restart each poll
          live.innerHTML='<span class="gen-nel-wrap"><img class="gen-nel" src="/branding/gen_nel.png" onerror="this.remove()"><i class="gen-ring"></i></span><span class="gen-live-txt"></span>';
        }
        var gt=live.querySelector('.gen-live-txt'); if(gt){ gt.textContent=running+' running'; }
        live.style.display='';
      } else { live.style.display='none'; }
    }
  }
  function toastTransitions(jobs){
    jobs.forEach(function(j){
      var st=j.status||'running', prev=last[j.job_id];
      if(seeded && prev!=='done' && prev!=='failed' && (st==='done'||st==='failed')){
        if(st==='done'){
          var mid=(j.media_ids||[])[0]||'';
          Toast.show({kind:'ok', title:(j.label||'Generation')+' \\u2014 done', msg:'Added to your gallery.',
                      thumb: mid?('/thumbs/'+encodeURIComponent(mid)+'.jpg'):null});
        } else {
          Toast.show({kind:'err', sticky:true, title:(j.label||'Job')+' failed', msg:j.error||'See the activity card.'});
        }
      }
      last[j.job_id]=st;
    });
    seeded=true;
  }
  function refresh(){
    return fetch('/api/jobs').then(function(r){return r.json();}).then(function(d){
      var jobs=(d&&d.jobs)||[];
      toastTransitions(jobs); render(jobs);
    }).catch(function(){});
  }
  function schedule(){
    if(timer) clearTimeout(timer);
    var f=el('jobs-fab'); var busy=f&&f.classList.contains('busy');
    timer=setTimeout(function(){
      if(document.hidden){ schedule(); return; }
      refresh().then(schedule);
    }, busy?2500:7000);
  }
  function dismiss(id){
    fetch('/api/jobs/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:id})})
      .then(function(){ delete last[id]; refresh(); }).catch(function(){});
  }
  function clearFinished(){
    fetch('/api/jobs/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({finished:true})})
      .then(refresh).catch(function(){});
  }
  document.addEventListener('DOMContentLoaded', function(){
    applyState();
    var t=el('jobs-tray');
    if(t){ t.addEventListener('click', function(e){
      var x=e.target.closest?e.target.closest('.jt-x[data-job]'):null;
      if(x){ dismiss(x.getAttribute('data-job')); return; }
      var h=e.target.closest?e.target.closest('.jt-hbtn[data-act]'):null;
      if(h){ var a=h.getAttribute('data-act'); if(a==='clear') clearFinished(); else if(a==='close') close(); }
    }); }
    refresh().then(schedule);
  });
  return {open:open, close:close, refresh:refresh, dismiss:dismiss, clearFinished:clearFinished};
})();
/* ---- Prompt snippets / favorites (server-stored) ---- */
var Snips = (function(){
  var list=null, target=null;
  function menu(){ return document.getElementById('snip-menu'); }
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function load(){ return (list!==null?Promise.resolve():fetch('/api/snippets').then(function(r){return r.json();})
      .then(function(d){ list=d.snippets||[]; }).catch(function(){ list=[]; })); }
  function persist(){ fetch('/api/snippets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snippets:list})}); }
  function open(anchor, tgt){ target=tgt; load().then(function(){ render(); place(anchor); }); }
  function hide(){ var m=menu(); if(m) m.style.display='none'; }
  function place(a){ var m=menu(), r=a.getBoundingClientRect();
    m.style.display='block';
    m.style.left=Math.min(r.left, window.innerWidth-m.offsetWidth-8)+'px';
    var top=r.bottom+4; if(top+m.offsetHeight>window.innerHeight-8) top=r.top-m.offsetHeight-4;
    m.style.top=Math.max(8,top)+'px';
  }
  function render(){
    var m=menu(); var html='<div class="snip-head"><span>Snippets</span>'
      +'<button class="jt-x" onmousedown="event.preventDefault();Snips.saveCurrent()">+ save current</button></div>';
    if(!list.length) html+='<div class="snip-empty">No saved snippets yet.</div>';
    (list||[]).forEach(function(s,i){
      html+='<div class="snip-row"><button class="snip-ins" onmousedown="event.preventDefault();Snips.insert('+i+')" title="Insert">'+esc(s)+'</button>'
        +'<button class="jt-x" onmousedown="event.preventDefault();Snips.del('+i+')">\\u00d7</button></div>';
    });
    m.innerHTML=html;
  }
  function saveCurrent(){ if(!target) return; var v=(target.get()||'').trim(); if(!v) return;
    if(list.indexOf(v)<0){ list.unshift(v); list=list.slice(0,200); persist(); render(); } }
  function insert(i){ if(!target||!list[i]) return; var cur=(target.get()||'').trim();
    target.set(cur ? (cur.replace(/,\\s*$/,'')+', '+list[i]) : list[i]); hide(); }
  function del(i){ list.splice(i,1); persist(); render(); }
  document.addEventListener('click', function(e){ var m=menu();
    if(m && m.style.display==='block' && !m.contains(e.target) && !(e.target.classList&&e.target.classList.contains('snip-btn'))) hide(); });
  return {open:open, saveCurrent:saveCurrent, insert:insert, del:del};
})();
var Gen = (function(){
  var kind='base', q='', selected=null, timer=null, seq=0, costSeq=0, costTimer=null;
  var sortMode='popular', catFilter='';   // Model-Market: 'popular'(REST) | 'newest'(GraphQL); category chip
  var workflows=null, enhTimer=null;
  var fixTag_='face', fixBoxes=[], fixStart=null;
  function el(id){return document.getElementById(id);}
  function open(){
    el('gen-drawer').classList.add('open'); el('gen-scrim').classList.add('open');
    el('gen-drawer').setAttribute('aria-hidden','false');
    setTimeout(function(){el('gen-prompt').focus();},200);
  }
  function close(){
    el('gen-drawer').classList.remove('open'); el('gen-scrim').classList.remove('open');
    el('gen-drawer').setAttribute('aria-hidden','true');
    var f=el('model-flyout'); if(f){ f.classList.remove('open'); f.setAttribute('aria-hidden','true'); }
    hidePreview();
  }
  function toggleFlyout(){
    var f=el('model-flyout'), on=!f.classList.contains('open');
    f.classList.toggle('open', on); f.setAttribute('aria-hidden', on?'false':'true');
    if(on){ if(!el('gen-grid').children.length) search(); setTimeout(function(){el('gen-q').focus();},120); }
    else hidePreview();
  }
  function setDock(d){
    d=(d==='left'||d==='top'||d==='bottom')?d:'right';
    var dr=el('gen-drawer');
    ['left','top','bottom'].forEach(function(x){ dr.classList.toggle('dock-'+x, d===x); });
    document.querySelectorAll('.dock-ctl button').forEach(function(b){ b.classList.toggle('on', b.getAttribute('data-dock')===d); });
    try{ localStorage.setItem('gen-dock', d); }catch(e){}
  }
  function setKind(k){
    if(k===kind) return; kind=k;
    el('gen-k-base').classList.toggle('on',k==='base');
    el('gen-k-lora').classList.toggle('on',k==='lora');
    el('gen-q').placeholder = (k==='lora'?'Search LoRAs':'Search models')+'\\u2026';
    // Category chips + Newest sort are a LoRA taxonomy (PixAI categories are 100% LoRAs, and
    // new base-model uploads are rare) -> only meaningful on the LoRAs tab. Base models stay on
    // the rich Popular/REST path; reset market state when leaving LoRAs.
    var market=(k==='lora');
    el('mkt-cats').style.display = market ? '' : 'none';
    el('mkt-sort').style.display = market ? '' : 'none';
    if(!market){ catFilter=''; sortMode='popular';
      document.querySelectorAll('#mkt-cats button').forEach(function(b){ b.classList.toggle('on',(b.getAttribute('data-cat')||'')===''); });
      el('mkt-popular').classList.add('on'); el('mkt-newest').classList.remove('on'); }
    search();
  }
  function onInput(){ q=el('gen-q').value.trim(); clearTimeout(timer); timer=setTimeout(search,280); }
  function setSort(s){ s=(s==='newest')?'newest':'popular'; if(s===sortMode) return; sortMode=s;
    el('mkt-popular').classList.toggle('on',s==='popular'); el('mkt-newest').classList.toggle('on',s==='newest');
    search(); }
  function setCat(c){ if(c===catFilter) return; catFilter=c||'';
    document.querySelectorAll('#mkt-cats button').forEach(function(b){ b.classList.toggle('on', (b.getAttribute('data-cat')||'')===catFilter); });
    search(); }
  function search(){
    var mine=++seq, grid=el('gen-grid'); grid.style.opacity='.45';
    var u='/api/model-search?kind='+kind+'&size=24&q='+encodeURIComponent(q)
      +'&sort='+sortMode+'&category='+encodeURIComponent(catFilter);
    fetch(u)
      .then(function(r){return r.json();})
      .then(function(d){ if(mine!==seq)return; render(d.results||[], d.error); grid.style.opacity='1'; })
      .catch(function(){ if(mine!==seq)return; render([], 'network error'); grid.style.opacity='1'; });
  }
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function fmt(n){ return (n||0).toLocaleString(); }
  function fmtCompact(n){ n=Number(n)||0;   // 207743449 -> "207.7M"; refCount = lifetime uses
    if(n>=1e9) return (n/1e9).toFixed(1).replace(/\\.0$/,'')+'B';
    if(n>=1e6) return (n/1e6).toFixed(1).replace(/\\.0$/,'')+'M';
    if(n>=1e3) return (n/1e3).toFixed(1).replace(/\\.0$/,'')+'K';
    return String(n); }
  function tyShort(t){ t=(t||'').toUpperCase();
    if(t.indexOf('LORA')>=0)return 'LoRA'; if(t.indexOf('MMDIT')>=0)return 'MMDiT';
    if(t.indexOf('DIT')>=0)return 'DiT'; if(t.indexOf('SDXL')>=0)return 'SDXL';
    if(t.indexOf('SD_V1')>=0)return 'SD1.5'; if(t.indexOf('SD3')>=0)return 'SD3';
    if(t.indexOf('Z_IMAGE')>=0)return 'Z-Image'; if(t.indexOf('CHAT')>=0)return 'Chat';
    return (t.split('_')[0]||'model').toLowerCase(); }
  function render(rows, err){
    var grid=el('gen-grid'), empty=el('gen-empty'); grid.innerHTML='';
    if(err){ empty.textContent='\\u26a0 '+err; empty.style.display='block'; return; }
    if(!rows.length){
      // Newest+Models is legitimately sparse (new uploads are almost all LoRAs), so say so
      // instead of the generic 'no results' which reads as broken.
      empty.textContent=(sortMode==='newest' && kind==='base')
        ? 'Few base models are uploaded recently \\u2014 new content is mostly LoRAs. Try the LoRAs tab, or switch to Popular.'
        : 'No results \\u2014 try another search.';
      empty.style.display='block'; return; }
    empty.style.display='none';
    rows.forEach(function(m){
      var c=document.createElement('div'); c.className='gen-card';
      if(kind==='lora' ? loras.some(function(l){return l.model_id===m.model_id;})
                       : (selected && selected.model_id===m.model_id)) c.classList.add('sel');
      var cov = m.preview_url ? '<img class="cov'+(m.should_blur?' blur':'')+'" loading="lazy" src="'+esc(m.preview_url)+'" alt="">' : '<div class="cov"></div>';
      var uses = m.ref_count ? '<span class="uses" title="'+fmt(m.ref_count)+' generations \\u2014 PixAI\\u2019s own most-used ranking">\\u25c8 '+fmtCompact(m.ref_count)+'</span>' : '';
      c.innerHTML = cov + '<span class="chk">\\u2713</span><div class="meta"><div class="nm" title="'+esc(m.title)+'">'+esc(m.title)+'</div><div class="sub"><span class="ty">'+tyShort(m.type)+'</span><span class="lk">\\u2665 '+fmt(m.liked_count)+'</span>'+uses+'</div></div>';
      c.onclick=function(){ selectCard(m, c); };
      c.onmouseenter=function(){ showPreview(m, c); };
      c.onmouseleave=hidePreview;
      grid.appendChild(c);
    });
  }
  function baseLabel(cat){ // "uploaded-sdxl" -> "SDXL", "flux-1" -> "Flux 1"
    cat=(cat||'').replace(/^uploaded-/,'').replace(/[-_]+/g,' ').trim();
    if(!cat) return '';
    if(/sdxl/i.test(cat)) return 'SDXL'; if(/sd3/i.test(cat)) return 'SD3';
    if(/^sd ?v?1/i.test(cat)) return 'SD1.5'; if(/flux/i.test(cat)) return 'Flux';
    if(/pony/i.test(cat)) return 'Pony'; if(/illustrious/i.test(cat)) return 'Illustrious';
    return cat.replace(/\\b\\w/g,function(c){return c.toUpperCase();}); }
  function showPreview(m, anchor){
    var p=el('model-preview'); if(!p||!m) return;
    var src=m.cover_url||m.preview_url;
    var base=baseLabel(m.base_model);
    var badges='';
    if(base) badges+='<span class="bdg base">'+esc(base)+'</span>';
    if(m.official) badges+='<span class="bdg official" title="In-house / official model">\\u2713 Official</span>';
    var stats='<span class="ty">'+tyShort(m.type)+'</span>';
    if(m.ref_count) stats+='<span title="'+fmt(m.ref_count)+' generations \\u2014 lifetime uses">\\u25c8 '+fmtCompact(m.ref_count)+' uses</span>';
    stats+='<span>\\u2665 '+fmt(m.liked_count)+'</span>';
    if(m.comment_count) stats+='<span>\\ud83d\\udcac '+fmt(m.comment_count)+'</span>';
    var html = (src?'<img src="'+esc(src)+'"'+(m.should_blur?' class="blur"':'')+' alt="">':'')
      +'<div class="mp-meta"><div class="mp-nm">'+esc(m.title)+'</div>'
      +'<div class="mp-sub">'+stats+'</div>'
      +(badges?'<div class="mp-badges">'+badges+'</div>':'')
      +(m.description?'<div class="mp-desc">'+esc(m.description)+'</div>':'')
      +'</div>';
    p.innerHTML=html; p.classList.add('open'); p.setAttribute('aria-hidden','false');
    placePreview(p, anchor);
  }
  function hidePreview(){ var p=el('model-preview'); if(p){ p.classList.remove('open'); p.setAttribute('aria-hidden','true'); } }
  function placePreview(p, anchor){
    var r=anchor.getBoundingClientRect(), w=300, gap=14, x;
    var dr=el('gen-drawer'), leftish = dr && dr.classList.contains('dock-left');
    // Preview should open toward screen center, away from the drawer edge: to the RIGHT
    // of the card when the drawer is docked left, to the LEFT otherwise.
    if(leftish){ x = r.right + gap; if(x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap); }
    else { x = r.left - w - gap; if(x < 8) x = Math.min(r.right + gap, window.innerWidth - w - 8); }
    var y = Math.max(8, Math.min(r.top - 20, window.innerHeight - 470));
    p.style.left=x+'px'; p.style.top=y+'px';
  }
  function showRefPreview(mid, anchor){
    var p=el('model-preview'); if(!p||!mid) return;
    p.innerHTML='<img src="/thumbs/'+mid+'.jpg" alt="">';
    p.classList.add('open'); p.setAttribute('aria-hidden','false');
    placePreview(p, anchor);
  }
  function previewSelected(ev){ if(selected) showPreview(selected, ev.currentTarget); }
  var loras=[];
  function toggleLora(m, c){
    var i=-1; loras.forEach(function(l,j){ if(l.model_id===m.model_id) i=j; });
    if(i>=0){ loras.splice(i,1); c.classList.remove('sel'); renderLoras(); refreshLoraNotes(); debouncedCost(); return; }
    if(loras.length>=6) return;
    var entry={model_id:m.model_id, title:m.title, preview_url:m.preview_url, version_id:'',
               weight:0.7, lora_base_type:'', trigger_words:''};
    loras.push(entry); c.classList.add('sel'); renderLoras();
    fetch('/api/model-version?model_id='+encodeURIComponent(m.model_id))
      .then(function(r){return r.json();})
      .then(function(d){ entry.version_id=d.version_id||''; entry.lora_base_type=d.lora_base_model_type||'';
        entry.trigger_words=d.trigger_words||''; renderLoras(); refreshLoraNotes(); debouncedCost(); })
      .catch(function(){ renderLoras(); });
  }
  // --- LoRA<->base compatibility gate + trigger-word offers ------------------
  // A LoRA runs on a base ONLY if its loraBaseModelType == the base's modelType (exact enum
  // equality). Family-level only (Pony/Illustrious/vanilla all = SDXL_MODEL) so this is a HARD
  // block on architecture mismatch, never a quality promise. Fails OPEN on unknown types.
  function prettyType(t){ t=(t||'').toUpperCase();
    if(t.indexOf('SDXL')>=0)return 'SDXL'; if(t.indexOf('SD_V1')>=0)return 'SD1.5';
    if(t.indexOf('DIT7')>=0)return 'DiT-7B'; if(t.indexOf('MMDIT')>=0)return 'MMDiT';
    if(t.indexOf('DIT9')>=0)return 'DiT-9'; if(t.indexOf('SD3')>=0)return 'SD3';
    if(t.indexOf('Z_IMAGE')>=0)return 'Z-Image'; return t||'?'; }
  function loraIncompat(e){
    var b=selected&&selected.model_type, l=e&&e.lora_base_type;
    if(!b||!l) return false;                       // unknown -> don't block
    return String(b).toUpperCase()!==String(l).toUpperCase();
  }
  function anyIncompat(){ return loras.some(loraIncompat); }
  function updateGoState(){ var go=el('gen-go'); if(go) go.disabled = !(selected&&selected.version_id) || anyIncompat(); }
  function triggersInPrompt(tw){
    var first=(tw||'').split(',')[0].trim().toLowerCase();
    return first && (el('gen-prompt').value||'').toLowerCase().indexOf(first)>=0;
  }
  function refreshLoraNotes(){
    var box=el('gen-lora-note'); if(!box) return; box.innerHTML='';
    loras.forEach(function(e){                      // incompatibility warnings (blocking)
      if(!loraIncompat(e)) return;
      var w=document.createElement('div'); w.className='lora-warn';
      w.innerHTML='\\u26a0 <b>'+esc(e.title)+'</b> needs a '+esc(prettyType(e.lora_base_type))
        +' base, but '+esc(selected.title)+' is '+esc(prettyType(selected.model_type))
        +'. It would fail on submit \\u2014 remove it or switch the base.';
      box.appendChild(w);
    });
    loras.forEach(function(e,i){                    // trigger-word offers (skip incompatible)
      if(!e.trigger_words || loraIncompat(e) || triggersInPrompt(e.trigger_words)) return;
      var t=document.createElement('div'); t.className='lora-trig';
      t.innerHTML='\\u2728 <b>'+esc(e.title)+'</b> triggers: <code>'+esc(e.trigger_words)+'</code>'
        +'<button type="button" onclick="Gen.insertTriggers('+i+',this)">Insert</button>';
      box.appendChild(t);
    });
    updateGoState();
  }
  function insertTriggers(i, btn){
    var e=loras[i]; if(!e||!e.trigger_words) return;
    var ta=el('gen-prompt'), cur=(ta.value||'').trim();
    ta.value = cur ? (cur.replace(/,\\s*$/,'')+', '+e.trigger_words) : e.trigger_words;
    if(btn){ btn.textContent='Inserted \\u2713'; btn.className='done'; btn.disabled=true; }
    refreshCost();
  }
  function renderLoras(){
    var box=el('gen-loras'); if(!box) return; box.innerHTML='';
    loras.forEach(function(l,i){
      var d=document.createElement('div'); d.className='lora-chip'+(loraIncompat(l)?' incompat':'');
      d.innerHTML=(l.preview_url?'<img src="'+esc(l.preview_url)+'" alt="">':'')
        +'<span class="nm" title="'+esc(l.title)+'">'+esc(l.title)+(l.version_id?'':' \\u23f3')+'</span>'
        +'<input type="number" step="0.05" min="0" max="2" value="'+l.weight+'" title="Weight" onchange="Gen.loraWeight('+i+', this.value)">'
        +'<button type="button" class="rm" title="Remove" onclick="Gen.loraRemove('+i+')">&times;</button>';
      box.appendChild(d);
    });
  }
  function loraWeight(i, v){ if(!loras[i]) return;
    v=parseFloat(v); loras[i].weight=(isNaN(v)?0.7:Math.max(0,Math.min(2,v))); debouncedCost(); }
  function loraRemove(i){ loras.splice(i,1); renderLoras(); refreshLoraNotes();
    if(kind==='lora') search(); debouncedCost(); }
  function openLoraBrowser(){
    var f=el('model-flyout');
    if(!f.classList.contains('open')) toggleFlyout();
    setKind('lora');
  }
  var selSeq=0;   // guards selectCard's async version fetch against a stale-response race
  function selectCard(m, c){
    if(kind==='lora'){ toggleLora(m, c); return; }
    document.querySelectorAll('.gen-card.sel').forEach(function(x){x.classList.remove('sel');});
    c.classList.add('sel'); selected=Object.assign({}, m); var mySeq=++selSeq;
    var th=el('gen-selthumb');
    if(m.preview_url){ th.src=m.preview_url; th.style.display=''; } else { th.style.display='none'; }
    el('gen-selname').textContent=m.title+' \\u2026';
    fetch('/api/model-version?model_id='+encodeURIComponent(m.model_id))
      .then(function(r){return r.json();})
      .then(function(d){ if(mySeq!==selSeq) return;   // a newer pick superseded this fetch
        selected.version_id=d.version_id||''; selected.model_type=d.model_type||'';
        el('gen-selname').textContent=m.title+(d.version_id?'':' (no version!)');
        refreshLoraNotes();   // re-check any attached LoRAs against the new base + set go-state
        refreshCost(); })
      .catch(function(){ if(mySeq===selSeq) el('gen-selname').textContent=m.title; });
  }
  var genRef=null;   // {media_id, thumb} -- the img2img reference, or null
  function refPick(){
    if(genRef){ genRef=null; renderGenRef(); debouncedCost(); return; }   // click filled slot = clear
    Picker.open(function(mid, thumb){ genRef={media_id:mid, thumb:thumb}; renderGenRef(); debouncedCost(); });
  }
  function renderGenRef(){
    var s=el('gen-ref-slot'), c=el('gen-ref-ctl'); if(!s) return;
    if(genRef){
      s.innerHTML='<img src="'+genRef.thumb+'" style="width:100%;height:100%;object-fit:cover;">'
        +'<span style="position:absolute;top:1px;right:1px;background:rgba(21,19,28,.85);color:var(--subtext);border-radius:50%;width:15px;height:15px;font-size:10px;line-height:15px;text-align:center;">&times;</span>';
      s.style.borderStyle='solid'; s.title='Click to remove the reference';
      c.style.display='';
      s.onmouseenter=function(){ showRefPreview(genRef.media_id, s); }; s.onmouseleave=hidePreview;
    } else {
      s.innerHTML='+ ref'; s.style.borderStyle='dashed'; s.title='Pick a reference image from your gallery';
      s.onmouseenter=null; s.onmouseleave=null; c.style.display='none';
    }
  }
  function refStrength(v){ el('gen-ref-sval').textContent=(+v).toFixed(2); debouncedCost(); }
  function d8(n){ n=Math.round(n/8)*8; return Math.max(64, Math.min(4096, n)); }
  function dims(){
    // Custom W&H (both set) win; else aspect ratio scaled so the LONG edge = chosen size.
    var cw=+(el('gen-cw')&&el('gen-cw').value||0), ch=+(el('gen-ch')&&el('gen-ch').value||0);
    if(cw>0 && ch>0) return {w:d8(cw), h:d8(ch), custom:true};
    var b=document.querySelector('#gen-aspects button.on');
    var rw=b?+b.getAttribute('data-rw'):1, rh=b?+b.getAttribute('data-rh'):1;
    var size=+((el('gen-size')&&el('gen-size').value)||1024);
    var w,h; if(rw>=rh){ w=size; h=size*rh/rw; } else { h=size; w=size*rw/rh; }
    return {w:d8(w), h:d8(h), custom:false};
  }
  function updateDimNote(){ var n=el('gen-dim-note'); if(!n) return; var d=dims();
    n.textContent='\\u2192 '+d.w+' \\u00d7 '+d.h+(d.custom?' \\u00b7 custom':' px'); }
  function payload(){ var a=dims();
    return { version_id:(selected&&selected.version_id)||'', model_id:(selected&&selected.model_id)||'', prompt:el('gen-prompt').value.trim(),
      negative:el('gen-neg').value.trim(), width:a.w, height:a.h, mode:el('gen-mode').value,
      count:+el('gen-count').value, seed:(el('gen-seed')?el('gen-seed').value.trim():''),
      high_priority:el('gen-hp').checked, prompt_helper:el('gen-ph').checked,
      ref_media_id:(genRef?genRef.media_id:''), ref_strength:+el('gen-ref-strength').value,
      loras:loras.filter(function(l){return l.version_id;}).map(function(l){return {version_id:l.version_id, weight:l.weight};}) }; }
  function refreshCost(){
    updateDimNote();
    if(!(selected&&selected.version_id)) return;
    var cost=el('gen-cost'); cost.className='gen-cost'; cost.textContent='Checking cost\\u2026';
    var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())})
      .then(function(r){return r.json();})
      .then(function(d){ if(mine!==costSeq)return;
        if(d.error){ cost.textContent='\\u26a0 '+d.error; return; }
        var n = d.cost!=null ? d.cost.toLocaleString() : '?';
        if(d.free){ cost.className='gen-cost free'; cost.textContent='\\u2713 FREE \\u2014 '+(d.card_name||'a card')+' covers this (saves ~'+n+' credits)'; }
        else { cost.textContent='\\u2248 '+n+' credits'; }
      }).catch(function(){ if(mine!==costSeq)return; cost.textContent='cost unavailable'; });
  }
  function debouncedCost(){ clearTimeout(costTimer); costTimer=setTimeout(refreshCost,250); }
  function renderResult(res, d, past){
    res.style.display='block';
    if(d.error){ res.innerHTML='<span style="color:var(--red);font-size:12px;">'+esc(d.error)+'</span>'; return; }
    var ids=d.media_ids||[];
    var cost = d.paid_credit===0 ? 'free (card used)' : ((d.paid_credit||0).toLocaleString()+' credits');
    var html='<div style="color:var(--emerald);font-size:12px;margin-bottom:6px;">\\u2713 '+past+' \\u2014 '+cost+'. Added to your gallery.</div>';
    ids.forEach(function(mid){ html+='<a href="/image/'+mid+'"><img src="/thumbs/'+mid+'.jpg" alt="result" loading="lazy"></a>'; });
    if(ids.length){ html+='<a href="#" onclick="Gen.setEditSource(\\''+ids[0]+'\\');Gen.setMode(\\'edit\\');return false;">Edit this result \\u2192</a>'; }
    res.innerHTML=html;
  }
  function runTask(url, p, res, opts){
    opts=opts||{};
    res.style.display='block'; res.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Submitting\\u2026</span>';
    if(opts.btn){ opts.btn.disabled=true; opts.btn.textContent=opts.busy; }
    function done(){ if(opts.btn){ opts.btn.disabled=false; opts.btn.textContent=opts.idle; } }
    fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
      .then(function(r){return r.json();})
      .then(function(d){
        if(d.error || !d.task_id){ done(); renderResult(res, {error:d.error||'submit failed'}); return; }
        res.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Queued \\u2014 running\\u2026</span>';
        // Jobs owns the polling, so the task (and its result) survive closing the drawer.
        Jobs.track(d.task_id, opts.past||'Task', function(phase, data){
          if(phase==='done'){ done(); renderResult(res, data, opts.past); Acct.refresh(); }
          else if(phase==='failed'){ done(); renderResult(res, {error:data.error||('task '+(data.status||'failed'))}); }
          else { res.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Rendering under the eclipse\\u2026 (task '+String(d.task_id).slice(-6)+')</span>'; }
        });
      }).catch(function(){ done(); renderResult(res, {error:'network error'}); });
  }
  function generate(){
    var p=payload();
    if(!p.version_id) return;
    if(!p.prompt){ el('gen-prompt').focus(); return; }
    runTask('/api/generate', p, el('gen-result'),
            {past:'Generated', btn:el('gen-go'), busy:'Generating\\u2026', idle:'Generate'});
  }
  function setMode(m){
    ['generate','edit','video'].forEach(function(x){
      var pane=el('gen-mode-'+x); if(pane) pane.style.display=(x===m)?'':'none';
      var btn=el('gm-'+x); if(btn) btn.classList.toggle('on', x===m); });
    el('gen-drawer').classList.toggle('wide', m==='video'||m==='edit');
    if(m==='edit'){ setEditModel(editModel); loadWorkflows().then(renderWorkflows); if(!presetsLoaded) loadPresets(); }
    if(m==='video') renderVideoSlots();
  }
  function setEditSub(s){
    ['edit','enhance','fix'].forEach(function(x){
      var pane=el('edit-sub-'+x); if(pane) pane.style.display=(x===s)?'':'none';
      var b=el('es-'+x); if(b) b.classList.toggle('on', x===s); });
    if(s==='enhance') loadWorkflows().then(renderWorkflows);
    if(s==='fix') fixResize();
  }
  function editSrc(){ return el('edit-src').value.trim(); }
  function setEditSource(mid){
    el('edit-src').value=mid||'';
    var img=el('edit-src-img');
    if(mid){ img.onerror=function(){img.style.display='none';}; img.src='/thumbs/'+mid+'.jpg'; img.style.display='block'; fixInit(); fixLoad(mid); }
    else { img.style.display='none'; }
    renderEditRefs();   // primary changed -> @image1 slot + cap count update
    debEditCost();
  }
  var EDIT_CAPS={
    'edit-pro':{max_refs:4,resolutions:['1K','2K'],qualities:['low','medium','high'],
      aspects:['16:9','9:16','1:1','2:3','3:2','3:4','4:3','4:5','5:4','1:3','3:1'],
      def:{resolution:'1K',quality:'medium',aspect:'3:4'}},
    'reference-pro':{max_refs:10,resolutions:['2K','4K'],qualities:[],
      aspects:['16:9','9:16','1:1','2:3','3:2','3:4','4:3','4:5','5:4','21:9'],
      def:{resolution:'2K',quality:'',aspect:'3:4'}}
  }; /* mirrors core.EDIT_MODELS caps (capability probe 2026-07-06) */
  var editModel='edit-pro';
  function _fillEditSel(id,opts,val){ var s=el(id); if(!s)return; s.innerHTML='';
    opts.forEach(function(o){ var e2=document.createElement('option'); e2.value=o; e2.textContent=o;
      if(o===val)e2.selected=true; s.appendChild(e2); }); }
  function setEditModel(k){
    var c=EDIT_CAPS[k]; if(!c)return; editModel=k;
    var a=el('em-edit-pro'), b=el('em-reference-pro');
    if(a)a.classList.toggle('on',k==='edit-pro'); if(b)b.classList.toggle('on',k==='reference-pro');
    _fillEditSel('edit-res',c.resolutions,c.def.resolution);
    _fillEditSel('edit-aspect',c.aspects,c.def.aspect);
    var qw=el('edit-qual-wrap');
    if(c.qualities.length){ if(qw)qw.style.display=''; _fillEditSel('edit-qual',c.qualities,c.def.quality); }
    else { if(qw)qw.style.display='none'; if(el('edit-qual'))el('edit-qual').innerHTML=''; }
    var maxAdd=Math.max(0, editRefCap()-(editSrc()?1:0));   // trim refs that no longer fit the model cap
    if(editRefs.length>maxAdd) editRefs=editRefs.slice(0,maxAdd);
    renderEditRefs();
    editCost();
  }
  var editRefs=[];   /* ADDITIONAL reference images beyond the primary edit-src (@image2..) */
  function editRefCap(){ return (EDIT_CAPS[editModel]||{max_refs:4}).max_refs; }
  function renderEditRefs(){
    var wrap=el('edit-refs'); if(!wrap) return; wrap.innerHTML='';
    var cap=editRefCap(), prim=editSrc(), used=(prim?1:0)+editRefs.length;
    function slot(inner,dashed){ var d=document.createElement('div');
      d.style.cssText='position:relative;width:64px;height:64px;border-radius:8px;border:1px '+(dashed?'dashed':'solid')+' var(--surface1);background:var(--surface0);overflow:hidden;display:grid;place-items:center;color:var(--subtext);font-size:10px;text-align:center;';
      d.innerHTML=inner; return d; }
    function tag(t){ return '<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.85);color:var(--lavender);font-size:9px;padding:1px 4px;border-radius:4px;">'+t+'</span>'; }
    if(prim) wrap.appendChild(slot('<img src="/thumbs/'+esc(prim)+'.jpg" style="width:100%;height:100%;object-fit:cover;">'+tag('@image1'),false));
    editRefs.forEach(function(r,i){
      var d=slot('<img src="'+esc(r.thumb)+'" style="width:100%;height:100%;object-fit:cover;">'+tag('@image'+(i+2))
        +'<button type="button" style="position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;border:none;background:rgba(21,19,28,.85);color:var(--subtext);font-size:11px;line-height:1;cursor:pointer;padding:0;">&times;</button>',false);
      d.querySelector('button').onclick=function(ev){ ev.stopPropagation(); editRefs.splice(i,1); renderEditRefs(); debEditCost(); };
      wrap.appendChild(d);
    });
    if(used<cap){ var add=slot('+ ref',true); add.style.cursor='pointer';
      add.onclick=function(){ Picker.open(function(mid){ if(mid){ editRefs.push({media_id:mid,thumb:'/thumbs/'+mid+'.jpg'}); renderEditRefs(); debEditCost(); } }); };
      wrap.appendChild(add); }
    var capEl=el('edit-ref-cap'); if(capEl) capEl.textContent='\\u00b7 '+used+'/'+cap+' (@image1 = the image being edited)';
  }
  function editPayload(){
    var prim=editSrc();
    var sources=[prim].concat(editRefs.map(function(r){return r.media_id;})).filter(Boolean);
    return { mode:'edit', edit_model:editModel, source:prim, sources:sources, instruction:el('edit-ins').value.trim(),
      preset:(el('edit-preset')?el('edit-preset').value:''),
      resolution:el('edit-res').value, quality:(el('edit-qual')?el('edit-qual').value:''), aspect:el('edit-aspect').value };
  }
  var presetsLoaded=false;
  function loadPresets(){
    fetch('/api/presets').then(function(r){return r.json();}).then(function(d){
      var sel=el('edit-preset'); if(!sel) return;
      var cur=sel.value; presetsLoaded=true;
      sel.innerHTML='<option value="">None \\u2014 custom instruction below</option>';
      Object.keys(d.presets||{}).sort().forEach(function(k){
        var o=document.createElement('option'); o.value=k; o.textContent=d.presets[k].label||k;
        sel.appendChild(o); });
      sel.value=cur;
    }).catch(function(){});
  }
  function presetImport(){
    var tid=(el('preset-task').value||'').trim(); if(!tid) { el('preset-task').focus(); return; }
    var btn=el('preset-task');
    fetch('/api/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:tid})})
      .then(function(r){return r.json();})
      .then(function(d){
        if(d.error){ btn.value=''; btn.placeholder='\\u26a0 '+d.error.slice(0,40); return; }
        btn.value=''; btn.placeholder='banked: '+(d.label||d.imported);
        loadPresets(); var sel=el('edit-preset'); if(sel) setTimeout(function(){ sel.value=d.imported; editCost(); }, 300);
      }).catch(function(){ btn.placeholder='\\u26a0 network error'; });
  }
  function editCost(){
    var cost=el('edit-cost');
    if(!editSrc()){ cost.className='gen-cost'; cost.textContent='Pick an image to see the cost.'; return; }
    cost.className='gen-cost'; cost.textContent='Checking cost\\u2026'; var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(editPayload())})
      .then(function(r){return r.json();})
      .then(function(d){ if(mine!==costSeq)return;
        if(d.note){ cost.textContent=d.note; return; }
        if(d.error){ cost.textContent='\\u26a0 '+d.error; return; }
        var n=d.cost!=null?d.cost.toLocaleString():'?';
        if(d.free){ cost.className='gen-cost free'; cost.textContent='\\u2713 FREE \\u2014 '+(d.card_name||'an Edit card')+' covers this (saves ~'+n+' credits)'; }
        else { cost.textContent='\\u2248 '+n+' credits'; }
      }).catch(function(){ if(mine!==costSeq)return; cost.textContent='cost unavailable'; });
  }
  function debEditCost(){ clearTimeout(costTimer); costTimer=setTimeout(editCost,250); }
  function edit(){
    var p=editPayload();
    if(!p.source){ el('edit-src').focus(); return; }
    if(!p.instruction && !p.preset){ el('edit-ins').focus(); return; }
    runTask('/api/edit', p, el('edit-result'),
            {past:'Edited', btn:el('edit-go'), busy:'Editing\\u2026', idle:'Apply edit'});
  }
  function fixTag(t){ fixTag_=t; el('fix-tag-face').classList.toggle('on',t==='face'); el('fix-tag-hand').classList.toggle('on',t==='hand'); }
  function fixClear(){ fixBoxes=[]; fixRedraw(); }
  function fixColor(tag){ return tag==='face' ? '#b692e6' : '#4fc99a'; }
  function fixRedraw(){
    var cv=el('fix-canvas'); if(!cv || !cv.getContext) return;
    var ctx=cv.getContext('2d'); ctx.clearRect(0,0,cv.width,cv.height);
    fixBoxes.forEach(function(b){
      ctx.strokeStyle=fixColor(b.tag); ctx.lineWidth=2; ctx.strokeRect(b.x,b.y,b.w,b.h);
      ctx.fillStyle=fixColor(b.tag); ctx.font='11px system-ui'; ctx.fillText(b.tag,b.x+3,b.y+13);
    });
  }
  function fixResize(){
    var img=el('fix-img'), cv=el('fix-canvas'); if(!img||!cv) return;
    cv.width=img.clientWidth; cv.height=img.clientHeight;
    cv.style.width=img.clientWidth+'px'; cv.style.height=img.clientHeight+'px'; fixRedraw();
  }
  function fixLoad(mid){
    fixBoxes=[]; var img=el('fix-img'); if(!img) return;
    img.onload=fixResize; img.onerror=function(){ el('fix-canvas').width=0; };
    img.src='/full/'+encodeURIComponent(mid);
  }
  function fixInit(){
    var cv=el('fix-canvas'); if(!cv || cv._wired) return; cv._wired=true;
    function pos(e){ var r=cv.getBoundingClientRect(); var t=e.touches&&e.touches[0]?e.touches[0]:e; return {x:t.clientX-r.left,y:t.clientY-r.top}; }
    function down(e){ fixStart=pos(e); e.preventDefault(); }
    function move(e){ if(!fixStart)return; var p=pos(e); fixRedraw(); var ctx=cv.getContext('2d'); ctx.strokeStyle=fixColor(fixTag_); ctx.lineWidth=2; ctx.strokeRect(fixStart.x,fixStart.y,p.x-fixStart.x,p.y-fixStart.y); e.preventDefault(); }
    function up(e){ if(!fixStart)return; var p=e.changedTouches&&e.changedTouches[0]?{x:e.changedTouches[0].clientX-cv.getBoundingClientRect().left,y:e.changedTouches[0].clientY-cv.getBoundingClientRect().top}:pos(e); var x=Math.min(fixStart.x,p.x),y=Math.min(fixStart.y,p.y),w=Math.abs(p.x-fixStart.x),h=Math.abs(p.y-fixStart.y); fixStart=null; if(w>6&&h>6) fixBoxes.push({x:x,y:y,w:w,h:h,tag:fixTag_}); fixRedraw(); }
    cv.addEventListener('mousedown',down); cv.addEventListener('mousemove',move); window.addEventListener('mouseup',up);
    cv.addEventListener('touchstart',down,{passive:false}); cv.addEventListener('touchmove',move,{passive:false}); cv.addEventListener('touchend',up);
  }
  function fix(){
    var src=editSrc(); if(!src){ el('edit-src').focus(); return; }
    if(!fixBoxes.length){ el('fix-result').style.display='block'; el('fix-result').innerHTML='<span style="color:var(--subtext);font-size:12px;">Drag a box over a hand or face first.</span>'; return; }
    var img=el('fix-img'); var scale = (img.naturalWidth && img.clientWidth) ? (img.naturalWidth/img.clientWidth) : 1;
    var boxes=fixBoxes.map(function(b){ return {x:Math.round(b.x*scale),y:Math.round(b.y*scale),width:Math.round(b.w*scale),height:Math.round(b.h*scale),tag:b.tag}; });
    runTask('/api/fix', {source:src, boxes:boxes}, el('fix-result'),
            {past:'Fixed', btn:el('fix-go'), busy:'Fixing\\u2026', idle:'Fix marked regions'});
  }
  function openEdit(mid){ open(); setMode('edit'); setEditSource(mid); }
  function loadWorkflows(){
    if(workflows) return Promise.resolve(workflows);
    return fetch('/api/workflows').then(function(r){return r.json();})
      .then(function(d){ workflows=d.workflows||[]; return workflows; })
      .catch(function(){ workflows=[]; return workflows; });
  }
  function renderWorkflows(){
    var list=el('enh-list'); if(!list) return;
    var qq=(el('enh-q').value||'').toLowerCase().trim();
    list.innerHTML='';
    (workflows||[]).filter(function(w){ return !qq || w.name.toLowerCase().indexOf(qq)>=0; })
      .slice(0,50).forEach(function(w){
        var b=document.createElement('button'); b.type='button'; b.className='enh-item';
        var nm=w.name.split('|')[0].split('/')[0].trim();
        b.innerHTML=esc(nm)+' <span class="ty">'+esc((w.type||'').toLowerCase())+'</span>';
        b.onclick=function(){ enhance(w.id); }; list.appendChild(b);
      });
  }
  function enhance(wid){
    var src=editSrc();
    if(!src){ el('edit-src').focus(); return; }
    function run(){ runTask('/api/enhance', {source:src, workflow_id:wid}, el('enh-result'), {past:'Enhanced'}); }
    // Enhance tools spend credits -- free cards do NOT cover panelplugin workflows. Price it
    // and confirm before firing, so a click never silently burns credits.
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:'enhance', source:src, workflow_id:wid})})
      .then(function(r){return r.json();}).then(function(d){
        if(d && d.free){ run(); return; }
        var c=(d && d.cost!=null)?(' (~'+Number(d.cost).toLocaleString()+' credits)'):'';
        if(window.confirm('This Enhance tool spends credits'+c+' \\u2014 free cards do not cover Enhance workflows. Run it?')) run();
      }).catch(function(){
        if(window.confirm('Run this Enhance tool? It spends credits (free cards do not cover Enhance workflows).')) run();
      });
  }
  var vmode='i2v', vslots=[null];
  function setVideoMode(m){
    vmode=m;
    ['i2v','flf','r2v'].forEach(function(x){ var b=el('vm-'+x); if(b) b.classList.toggle('on',x===m); });
    var vp=el('video-prompt');
    if(m==='i2v'){ vslots=[vslots[0]||null]; el('video-slots-lbl').textContent='Source image (first frame)';
      vp.setAttribute('data-placeholder','Describe the motion \\u2014 \\u2018slow cinematic pan right, gentle waves\\u2026\\u2019'); }
    else if(m==='flf'){ vslots=[vslots[0]||null,vslots[1]||null]; el('video-slots-lbl').textContent='Start & end frame';
      vp.setAttribute('data-placeholder','Describe the transition from start frame to end frame\\u2026'); }
    else { if(!vslots.length) vslots=[null]; el('video-slots-lbl').textContent='Reference images';
      vp.setAttribute('data-placeholder','Type @image1 to cite a ref \\u2014 it becomes a chip \\u2014 \\u2018the girl from @image1 walks the pier\\u2026\\u2019'); }
    var cam=el('video-cam-wrap'); if(cam) cam.style.visibility=(m==='r2v')?'hidden':'visible';
    renderVideoSlots();
  }
  function renderVideoSlots(){
    var wrap=el('video-slots'); if(!wrap) return; wrap.innerHTML=''; wrap.style.cssText='display:flex;gap:8px;flex-wrap:wrap;';
    var refN=0;
    vslots.forEach(function(s,i){
      var box=document.createElement('div');
      box.style.cssText='position:relative;width:78px;height:78px;border-radius:8px;border:1px solid var(--surface1);background:var(--surface0);cursor:pointer;overflow:hidden;display:grid;place-items:center;color:var(--subtext);font-size:11px;text-align:center;';
      if(s){
        refN++;
        var tag=(vmode==='flf'?(i===0?'start':'end'):'@image'+refN);
        box.innerHTML='<img src="'+s.thumb+'" style="width:100%;height:100%;object-fit:cover;">'
          +'<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.85);color:var(--lavender);font-size:9.5px;padding:1px 5px;border-radius:4px;">'+tag+'</span>'
          +'<button type="button" class="vs-x" style="position:absolute;top:2px;right:2px;width:17px;height:17px;border-radius:50%;border:none;background:rgba(21,19,28,.85);color:var(--subtext);font-size:11px;line-height:1;cursor:pointer;padding:0;">&times;</button>';
        box.querySelector('.vs-x').onclick=function(ev){ ev.stopPropagation(); hidePreview();
          if(vmode==='r2v'){ vslots.splice(i,1); if(!vslots.length) vslots=[null]; } else vslots[i]=null;
          renderVideoSlots(); };
        box.onmouseenter=function(){ showRefPreview(s.media_id, box); };
        box.onmouseleave=hidePreview;
      }
      else { box.textContent=(vmode==='flf'?(i===0?'+ start':'+ end'):'+ pick'); }
      box.onclick=function(){ Picker.open(function(mid,thumb){ vslots[i]={media_id:mid,thumb:thumb}; renderVideoSlots(); }); };
      wrap.appendChild(box);
    });
    if(vmode==='r2v' && vslots.length<9){
      var add=document.createElement('button'); add.type='button'; add.textContent='+ add';
      add.style.cssText='width:78px;height:78px;border-radius:8px;border:1px dashed var(--surface1);background:transparent;color:var(--subtext);cursor:pointer;font-size:11px;';
      add.onclick=function(){ vslots.push(null); renderVideoSlots(); }; wrap.appendChild(add);
    }
    videoCost();
  }
  var vcostTimer=null, vpTimer=null;
  function vpRefs(){
    var map={}, n=0;
    vslots.forEach(function(s){ if(s&&s.media_id){ n++; map['@image'+n]={thumb:s.thumb, mid:s.media_id}; } });
    return map;
  }
  function vpMakeChip(tag, info){
    var c=document.createElement('span'); c.className='vp-chip'; c.contentEditable='false';
    c.setAttribute('data-ref', tag);
    c.innerHTML=(info&&info.thumb?'<img src="'+info.thumb+'" alt="">':'')+tag;
    if(info&&info.mid){ c.onmouseenter=function(){ showRefPreview(info.mid, c); }; c.onmouseleave=hidePreview; }
    return c;
  }
  function vpChipify(final){
    var vp=el('video-prompt'); if(!vp) return;
    var map=vpRefs(), sel=window.getSelection();
    var walker=document.createTreeWalker(vp, NodeFilter.SHOW_TEXT), nodes=[], tn;
    while((tn=walker.nextNode())) nodes.push(tn);
    var re=/@image\\d+/g;
    nodes.forEach(function(node){
      var t=node.nodeValue, m, found=[];
      re.lastIndex=0;
      while((m=re.exec(t))!==null){
        if(!map[m[0]]) continue;
        if(!final && m.index+m[0].length===t.length) continue;  // still typing at the end
        found.push({i:m.index, tag:m[0]});
      }
      if(!found.length) return;
      var caretHere = sel.rangeCount && sel.getRangeAt(0).startContainer===node;
      var frag=document.createDocumentFragment(), pos=0;
      found.forEach(function(f){
        if(f.i>pos) frag.appendChild(document.createTextNode(t.slice(pos, f.i)));
        frag.appendChild(vpMakeChip(f.tag, map[f.tag]));
        pos=f.i+f.tag.length;
      });
      var tail=document.createTextNode(t.slice(pos)); frag.appendChild(tail);
      node.parentNode.replaceChild(frag, node);
      if(caretHere){ var r=document.createRange(); r.setStart(tail, tail.length); r.collapse(true);
        sel.removeAllRanges(); sel.addRange(r); }
    });
  }
  function vpText(){
    var vp=el('video-prompt'), out='';
    (function walk(n){ n.childNodes.forEach(function(c){
      if(c.nodeType===3) out+=c.nodeValue;
      else if(c.classList&&c.classList.contains('vp-chip')) out+=c.getAttribute('data-ref');
      else if(c.nodeName==='BR') out+='\\n';
      else walk(c);
    });})(vp);
    return out.replace(/\\u00a0/g,' ').trim();
  }
  function videoPromptSet(v){ var vp=el('video-prompt'); if(!vp) return; vp.textContent=v||''; vpChipify(true); videoCost(); }
  function vpOnInput(){ clearTimeout(vpTimer); vpTimer=setTimeout(function(){ vpChipify(false); videoCost(); }, 300); }
  function videoPayload(){
    return { mode:vmode.toUpperCase(), prompt:vpText(),
      images:vslots.filter(function(s){return s&&s.media_id;}).map(function(s){return s.media_id;}),
      duration:+el('video-dur').value, audio:el('video-audio').checked,
      video_model:el('video-model').value,
      camera_movement:(vmode!=='r2v'?el('video-cam').value:''),
      quality:el('video-vmode').value,
      audio_language:el('video-lang').value };
  }
  function videoAudioToggle(){ el('video-lang-wrap').style.display=el('video-audio').checked?'':'none'; videoCost(); }
  function videoCost(){ clearTimeout(vcostTimer); vcostTimer=setTimeout(videoCostNow, 250); }
  function videoCostNow(){
    var cost=el('video-cost'); if(!cost) return;
    var p=videoPayload();
    if(!p.images.length){ cost.className='gen-cost'; cost.textContent='Pick a source image to see the cost.'; return; }
    cost.className='gen-cost'; cost.textContent='Checking cost\\u2026'; var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
      .then(function(r){return r.json();})
      .then(function(d){ if(mine!==costSeq)return;
        if(d.note){ cost.textContent=d.note; return; }
        if(d.error){ cost.textContent='\\u26a0 '+d.error; return; }
        var n=d.cost!=null?d.cost.toLocaleString():'?';
        if(d.free){ cost.className='gen-cost free';
          cost.textContent='\\ud83c\\udfab FREE \\u2014 '+(d.card_name||'a video card')+' covers this'+(d.cards?' ('+d.cards+' left)':'')+' \\u00b7 saves ~'+n+' credits'; }
        else { var big=(p.video_model==='v4.0');   // v4.0 full is ~2.5x Lite (14k/s -> 210k for 15s)
          cost.className='gen-cost'+(big?' warn':'');
          cost.textContent=(big?'\\u26a0 V4.0 full \\u2014 ~2.5\\u00d7 Lite \\u00b7 ':'')+'\\u2248 '+n+' credits'; }
      }).catch(function(){ if(mine!==costSeq)return; cost.textContent='cost unavailable'; });
  }
  function addVideoRefs(refs){
    refs=(refs||[]).slice(0,9); if(!refs.length) return;
    open(); setMode('video');
    if(refs.length>1) setVideoMode('r2v');
    var slots=refs.map(function(r){ return {media_id:r.mid, thumb:r.thumb}; });
    if(refs.length>1){ vslots=slots; }
    else if(vmode==='r2v'){ vslots=[slots[0]]; }
    else { vslots[0]=slots[0]; }
    renderVideoSlots();
  }
  function videoGenerate(){
    var p=videoPayload(), res=el('video-result');
    if(!p.images.length){ res.style.display='block'; res.innerHTML='<span style="color:var(--red);font-size:12px;">Pick a source image first.</span>'; return; }
    runTask('/api/loom/generate', p,
            res, {past:'Rendered', btn:el('video-go'), busy:'Rendering\\u2026', idle:'Generate video'});
  }
  return {open:open, close:close, setKind:setKind, onInput:onInput, search:search,
          refreshCost:debouncedCost, generate:generate, setMode:setMode, edit:edit,
          editCost:debEditCost, setEditSource:setEditSource, openEdit:openEdit, enhance:enhance,
          renderWorkflows:renderWorkflows, fixTag:fixTag, fixClear:fixClear, fix:fix,
          setVideoMode:setVideoMode, videoGenerate:videoGenerate, renderVideoSlots:renderVideoSlots,
          setDock:setDock, toggleFlyout:toggleFlyout,
          previewSelected:previewSelected, hidePreview:hidePreview,
          refPick:refPick, refStrength:refStrength, presetImport:presetImport,
          loraWeight:loraWeight, loraRemove:loraRemove, openLoraBrowser:openLoraBrowser,
          insertTriggers:insertTriggers, setSort:setSort, setCat:setCat,
          setEditSub:setEditSub, setEditModel:setEditModel, addVideoRefs:addVideoRefs, videoCost:videoCost,
          videoAudioToggle:videoAudioToggle,
          vpOnInput:vpOnInput, vpChipify:vpChipify,
          videoPromptText:vpText, videoPromptSet:videoPromptSet,
          get selected(){return selected;}};
})();
var Tags = (function(){
  var items=[], hot=0, ta=null, timer=null, seq=0;
  function box(){ return document.getElementById('tag-suggest'); }
  function seg(){
    var v=ta.value, p=ta.selectionStart;
    var start=Math.max(v.lastIndexOf(',', p-1), v.lastIndexOf('\\n', p-1))+1;
    return {start:start, text:v.slice(start, p)};
  }
  function hide(){ var b=box(); if(b) b.style.display='none'; items=[]; }
  function accept(i){
    if(!items[i]||!ta) return;
    var s=seg(), v=ta.value, lead=v.slice(0, s.start);
    var pad=(lead && !/\\s$/.test(lead)) ? ' ' : '';
    var ins=lead+pad+items[i]+', ';
    ta.value=ins+v.slice(ta.selectionStart);
    ta.setSelectionRange(ins.length, ins.length); ta.focus(); hide();
  }
  function show(){
    var b=box(); if(!items.length){ hide(); return; }
    b.innerHTML='<div class="ts-head"><span>Tag suggestions</span><span>TAB accepts</span></div>'
      + items.map(function(t,i){ return '<button type="button" class="'+(i===hot?'hot':'')
          +'" onmousedown="event.preventDefault();Tags.accept('+i+')">'+t.replace(/[&<>]/g,'')+'</button>'; }).join('');
    var r=ta.getBoundingClientRect();
    b.style.display='block';
    b.style.left=Math.min(r.left, window.innerWidth-b.offsetWidth-8)+'px';
    var top=r.bottom+4;
    if(top+b.offsetHeight > window.innerHeight-8) top=r.top-b.offsetHeight-4;
    b.style.top=top+'px';
  }
  function query(){
    var t=seg().text.trim();
    if(t.length<2){ hide(); return; }
    var mine=++seq;
    fetch('/api/tag-suggest?q='+encodeURIComponent(t)).then(function(r){return r.json();}).then(function(d){
      if(mine!==seq) return; items=(d.tags||[]).slice(0,8); hot=0; show();
    }).catch(function(){});
  }
  function onInput(e){ ta=e.target; clearTimeout(timer); timer=setTimeout(query, 220); }
  function onKey(e){
    var b=box(); if(!b || b.style.display!=='block') return;
    if(e.key==='Tab'){ e.preventDefault(); accept(hot); }
    else if(e.key==='ArrowDown'){ e.preventDefault(); hot=Math.min(hot+1, items.length-1); show(); }
    else if(e.key==='ArrowUp'){ e.preventDefault(); hot=Math.max(hot-1, 0); show(); }
    else if(e.key==='Escape'){ e.stopPropagation(); hide(); }
  }
  function attach(id){ var t=document.getElementById(id); if(!t) return;
    t.addEventListener('input', onInput); t.addEventListener('keydown', onKey);
    t.addEventListener('blur', function(){ setTimeout(hide, 150); }); }
  return {attach:attach, accept:accept, hide:hide};
})();
function lbMid(){ var m=(document.getElementById('lb-details').href||'').match(/\\/image\\/([^/?]+)/); return m?decodeURIComponent(m[1]):''; }
function lbEdit(){ var mid=lbMid(); if(!mid) return; closeLightbox(); Gen.openEdit(mid); }
function lbVideo(){ var mid=lbMid(); if(!mid) return; closeLightbox(); Gen.addVideoRefs([{mid:mid, thumb:'/thumbs/'+mid+'.jpg'}]); }
function lbSimilar(){ var mid=lbMid(); if(!mid) return; closeLightbox(); Similar.open(mid); }
var Ctx = (function(){
  var mid='', isVideo=false;
  function m(){ return document.getElementById('ctx-menu'); }
  function hide(){ var e=m(); if(e) e.style.display='none'; }
  function show(e, card){
    mid=card.getAttribute('data-mid'); isVideo=card.getAttribute('data-video')==='1';
    var menu=m();
    menu.innerHTML=(isVideo?'':'<button onclick="Ctx.edit()">\\u270e Edit image</button>'
        +'<button onclick="Ctx.video()">\\u25b6 Send to Video</button>'
        +'<button onclick="Ctx.similar()">\\u2727 Similar</button>')
      +'<button onclick="Ctx.copy()">\\u2398 Copy media id</button>'
      +'<button onclick="Ctx.detail()">Open details</button>';
    menu.style.display='block';
    menu.style.left=Math.min(e.clientX, window.innerWidth-menu.offsetWidth-8)+'px';
    menu.style.top=Math.min(e.clientY, window.innerHeight-menu.offsetHeight-8)+'px';
  }
  document.addEventListener('click', hide);
  document.addEventListener('scroll', hide, true);
  document.addEventListener('contextmenu', function(e){
    var card=e.target && e.target.closest ? e.target.closest('.card') : null;
    if(!card || !card.getAttribute('data-mid')){ hide(); return; }
    e.preventDefault(); show(e, card);
  });
  return {
    similar:function(){ hide(); Similar.open(mid); },
    edit:function(){ hide(); Gen.openEdit(mid); },
    video:function(){ hide(); Gen.addVideoRefs([{mid:mid, thumb:'/thumbs/'+mid+'.jpg'}]); },
    copy:function(){ hide(); try{ navigator.clipboard.writeText(mid); }catch(e){} },
    detail:function(){ hide(); location.href='/image/'+mid; }
  };
})();
var Similar = (function(){
  function el(id){ return document.getElementById(id); }
  function open(mid){
    if(!mid) return;
    el('similar-scrim').classList.add('open'); el('similar-modal').classList.add('open');
    var g=el('similar-grid'), em=el('similar-empty');
    em.style.display='none';
    g.innerHTML='<div class="pick-empty">Finding lookalikes\\u2026</div>';
    fetch('/api/similar/'+encodeURIComponent(mid)+'?k=48').then(function(r){return r.json();}).then(function(d){
      g.innerHTML='';
      var imgs=(d&&d.images)||[];
      if(!imgs.length){ em.textContent=(d&&d.error)?d.error:'No similar images yet \\u2014 the index may still be building.'; em.style.display='block'; return; }
      imgs.forEach(function(it){
        var c=document.createElement('div');
        c.className='card'; c.setAttribute('data-mid', it.media_id);
        c.setAttribute('data-prompt', it.prompt||'');
        if(it.is_video==='1') c.setAttribute('data-video','1');
        c.innerHTML='<a class="cover" href="/image/'+encodeURIComponent(it.media_id)+'"></a>'
          +'<img class="loaded" src="'+it.thumb+'" loading="lazy" decoding="async" alt="">'
          +(it.is_video==='1'?'<div class="vbadge" title="Video">\\u25b6</div>':'')
          +'<div class="meta"><div class="model">\\u2727 '+(it.score!=null?it.score:'')+'</div></div>';
        g.appendChild(c);
      });
    }).catch(function(){ g.innerHTML=''; em.textContent='Could not load similar images.'; em.style.display='block'; });
  }
  function close(){ el('similar-scrim').classList.remove('open'); el('similar-modal').classList.remove('open'); }
  document.addEventListener('keydown', function(e){ if(e.key==='Escape'&&el('similar-modal').classList.contains('open')) close(); });
  return {open:open, close:close};
})();
function bulkSendVideo(){
  var refs=[];
  selGet().forEach(function(mid){
    var card=document.getElementById('card-'+mid);
    if(card && card.getAttribute('data-video')==='1') return;   // videos can't be image refs
    refs.push({mid:mid, thumb:'/thumbs/'+mid+'.jpg'});
  });
  if(!refs.length) return;
  Gen.addVideoRefs(refs.slice(0,9));
  clearAll();   // sent to the video drawer -- clear the gallery selection (we stay on the page)
}
document.addEventListener('DOMContentLoaded', function(){
  var q=document.getElementById('gen-q'); if(q) q.addEventListener('input', Gen.onInput);
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') Gen.close(); });
  try{ Gen.setDock(localStorage.getItem('gen-dock')||'right'); }catch(e){}
  Acct.refresh();
  (function(){ var tl=document.getElementById('tagline'); if(!tl) return;
    if(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var lines=['a library against the Void','the archive remembers','what the moon keeps','every dream, kept','a light in the Nightmare'];
    var i=0; setInterval(function(){ i=(i+1)%lines.length; tl.style.opacity=0;
      setTimeout(function(){ tl.textContent=lines[i]; tl.style.opacity=1; }, 500); }, 9000); })();
  ['gen-prompt','gen-neg','edit-ins'].forEach(Tags.attach);
  var vp=document.getElementById('video-prompt');
  if(vp){ vp.addEventListener('input', Gen.vpOnInput);
          vp.addEventListener('blur', function(){ Gen.vpChipify(true); }); }
  var asp=document.getElementById('gen-aspects');
  if(asp) asp.addEventListener('click', function(e){ var b=e.target.closest('button'); if(!b)return;
    asp.querySelectorAll('button').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on'); Gen.refreshCost(); });
  ['gen-mode','gen-count','gen-hp','gen-ph','gen-size'].forEach(function(id){
    var e2=document.getElementById(id); if(e2) e2.addEventListener('change', Gen.refreshCost); });
  ['gen-cw','gen-ch'].forEach(function(id){
    var e2=document.getElementById(id); if(e2) e2.addEventListener('input', Gen.refreshCost); });
  if(document.getElementById('gen-dim-note') && window.Gen) Gen.refreshCost();
  ['edit-res','edit-qual','edit-aspect'].forEach(function(id){
    var e2=document.getElementById(id); if(e2) e2.addEventListener('change', Gen.editCost); });
  if(document.getElementById('em-edit-pro') && window.Gen) Gen.setEditModel('edit-pro');  // populate the option lists
  var es=document.getElementById('edit-src');
  if(es) es.addEventListener('input', function(){ Gen.setEditSource(es.value.trim()); });
  var eq=document.getElementById('enh-q'); if(eq) eq.addEventListener('input', Gen.renderWorkflows);
  var em=new URLSearchParams(location.search).get('edit');
  if(em) Gen.openEdit(em);
});
</script>
""")

    DETAIL_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
<script>
function toggleFocus() {
  var wrap = document.querySelector('.detail-wrap');
  var on = wrap.classList.toggle('focus-mode');
  localStorage.setItem('gallery_focus', on ? '1' : '');
  document.getElementById('focus-btn').textContent = on ? 'Details' : 'Focus';
}
document.addEventListener('DOMContentLoaded', function() {
  if (localStorage.getItem('gallery_focus')) {
    document.querySelector('.detail-wrap').classList.add('focus-mode');
    document.getElementById('focus-btn').textContent = 'Details';
  }
  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'ArrowLeft' || e.keyCode === 37) {
      var el = document.getElementById('nav-prev');
      if (el) window.location.href = el.href;
    } else if (e.key === 'ArrowRight' || e.keyCode === 39) {
      var el = document.getElementById('nav-next');
      if (el) window.location.href = el.href;
    } else if (e.key === 'Escape' || e.keyCode === 27 || e.key === 'ArrowUp' || e.keyCode === 38) {
      e.preventDefault();
      var g = document.getElementById('nav-gallery');
      if (g) window.location.href = g.href;
    } else if (e.key === 'f' || e.key === 'F') {
      toggleFocus();
    }
  });
});
</script>
<div class="detail-wrap">
  <div class="detail-nav">
    {% if prev_id %}
    <a id="nav-prev" class="nav-arrow" href="{{ url_for('detail', media_id=prev_id, back=back) }}" title="Previous (← arrow key)">&#8592; Prev</a>
    {% else %}
    <span class="nav-arrow nav-disabled">&#8592; Prev</span>
    {% endif %}
    <a id="nav-gallery" class="back-link" href="{{ back }}" title="Back to gallery (Esc or ↑ arrow)">↑ Gallery</a>
    <button id="focus-btn" class="focus-btn" onclick="toggleFocus()" title="Toggle focus mode (F key)">Focus</button>
    {% if next_id %}
    <a id="nav-next" class="nav-arrow" href="{{ url_for('detail', media_id=next_id, back=back) }}" title="Next (→ arrow key)">Next &#8594;</a>
    {% else %}
    <span class="nav-arrow nav-disabled">Next &#8594;</span>
    {% endif %}
  </div>

  <div class="detail-img">
    {% if row.is_video == '1' %}
    <video controls autoplay loop playsinline preload="metadata"
           style="max-width:100%;border-radius:8px;background:#000"
           {% if poster_url %}poster="{{ poster_url }}"{% endif %}>
      <source src="{{ url_for('video_file', media_id=row.media_id) }}" type="video/mp4">
      Your browser can't play this video. <a href="{{ url_for('video_file', media_id=row.media_id) }}">Download it</a>.
    </video>
    {% elif img_url %}
    <a href="{{ img_url }}" target="_blank" title="Click to open full resolution">
      <img src="{{ img_url }}" alt="{{ row.prompt_preview }}">
    </a>
    {% else %}
    <div style="color:var(--overlay0);padding:40px">Image file not found on disk.</div>
    {% endif %}
  </div>

  <div class="detail-meta">
    {% if row.prompt_full %}
    <span class="lbl">Full Prompt</span>
    <span class="val prompt">{{ row.prompt_full }}</span>
    {% endif %}
    {% if row.natural_prompt %}
    <span class="lbl">Natural Prompt</span>
    <span class="val prompt">{{ row.natural_prompt }}</span>
    {% endif %}
    {% if row.negative_prompt %}
    <span class="lbl">Negative Prompt</span>
    <span class="val prompt">{{ row.negative_prompt }}</span>
    {% endif %}
    <span class="lbl">Prompt Preview</span>
    <span class="val">{{ row.prompt_preview }}</span>
    <span class="lbl">Model</span>
    <span class="val">{{ row.model_name or row.model_id or '—' }}</span>
    {% if row.loras %}
    <span class="lbl">LoRAs</span>
    <span class="val">{{ row.loras }}</span>
    {% endif %}
    {% if row.title %}
    <span class="lbl">Title</span>
    <span class="val">{{ row.title }}</span>
    {% endif %}
    {% if row.is_published == '1' %}
    <span class="lbl">Engagement</span>
    <span class="val">
      <span id="detail-views" data-artwork="{{ row.artwork_id }}">{% if row.artwork_id %}&#128065; &hellip;{% endif %}</span>
      {% if row.liked_count %}&#9829; {{ row.liked_count }}{% endif %}
      {% if row.comment_count and row.comment_count != '0' %} &middot; &#128172; {{ row.comment_count }}{% endif %}
      {% if row.aes_score %} &middot; &#10022; {{ row.aes_score[:4] }}{% endif %}
    </span>
    {% endif %}
    {% if row.nsfw_scores %}
    <span class="lbl">Content</span>
    <span class="val" id="detail-nsfw" data-scores="{{ row.nsfw_scores|e }}"></span>
    {% endif %}
    {% if row.art_tags %}
    <span class="lbl">Tags</span>
    <span class="val">{{ row.art_tags }}</span>
    {% endif %}
    {% if row.collections %}
    <span class="lbl">Collections</span>
    <span class="val">{{ row.collections.replace(',', ', ') }}</span>
    {% endif %}
    <span class="lbl">Seed</span>
    <span class="val">{{ row.seed or '—' }}</span>
    <span class="lbl">Steps</span>
    <span class="val">{{ row.steps or '—' }}</span>
    <span class="lbl">Sampler</span>
    <span class="val">{{ row.sampler or '—' }}</span>
    <span class="lbl">CFG Scale</span>
    <span class="val">{{ row.cfg_scale or '—' }}</span>
    {% if row.clip_skip %}
    <span class="lbl">Clip Skip</span>
    <span class="val">{{ row.clip_skip }}</span>
    {% endif %}
    <span class="lbl">Dimensions</span>
    <span class="val">{{ row.width }}×{{ row.height }}</span>
    <span class="lbl">Date</span>
    <span class="val">{{ row.created_at[:10] if row.created_at else '—' }}</span>
    <span class="lbl">Task ID</span>
    <span class="val" style="font-size:11px;color:var(--overlay0)">{{ row.task_id }}</span>
    <span class="lbl">Media ID</span>
    <span class="val" style="font-size:11px;color:var(--overlay0)">{{ row.media_id }}</span>
    <span class="lbl">Filename</span>
    <span class="val" style="font-size:11px;color:var(--overlay0)">{{ row.filename }}</span>
  </div>

  <div class="detail-stars">
    <div class="stars" id="detail-stars"
         data-mid="{{ row.media_id }}" data-rating="{{ row.rating or 0 }}"></div>
    <span class="rating-label">{{ row.rating + ' / 5' if row.rating else 'unrated' }}</span>
  </div>

  <div class="detail-actions">
    {% if img_url %}
    <a class="btn" href="{{ img_url }}" target="_blank">Open Full Size (local)</a>
    {% endif %}
    {% if row.url %}
    <a class="btn" href="{{ row.url }}" target="_blank">Open on PixAI CDN</a>
    {% endif %}
    {% set _prompt = row.prompt_full or row.prompt_preview or '' %}
    {% if _prompt %}
    <button class="btn" id="copy-prompt-btn"
      data-prompt="{{ _prompt|e }}" onclick="copyPrompt(this)">Copy Prompt</button>
    {% endif %}
    <button class="btn" data-cmd="{{ row.media_id }}" onclick="copyCmd(this)"
      title="Copy this image's media_id (paste into the GUI Video/Edit tab)">Copy media id</button>
    <button class="btn" onclick="window.print()" title="Print this image with its details (Letter)">&#128424; Print</button>
    {% if row.is_video != '1' %}
    <a class="btn" href="/contact-sheet?ids={{ row.media_id }}&format=photo" target="_blank" title="Print as a 4x6 photo">4&times;6 photo</a>
    <a class="btn" href="/contact-sheet?ids={{ row.media_id }}&format=strip" target="_blank" title="Print as a photo-booth strip (cut into two 2x6 strips)">Photo strip</a>
    {% endif %}
    {% if row.is_video != '1' %}
    <button class="btn" id="suggest-prompt-btn" data-mid="{{ row.media_id }}"
      onclick="suggestPrompt(this)"
      title="Ask PixAI to read this image back into a prompt (free)">&#9998; Suggest prompt</button>
    <a class="btn btn-primary" href="/?edit={{ row.media_id }}"
      title="Open this image in the Edit tab">&#10022; Edit this</a>
    {% endif %}
    {% if row.is_video != '1' %}
    <button class="btn"
      data-cmd='python pixai_gallery_backup.py --generate-video --image {{ row.media_id }} --prompt "describe the motion"'
      onclick="copyCmd(this)"
      title="Copy a ready-to-run Animate (image→video) command; add --confirm to run">Animate this → cmd</button>
    {% endif %}
    {% if row.model_name %}
    <a class="btn" href="{{ url_for('index', model=row.model_name) }}"
       title="Show all images from this model">Find Similar (model)</a>
    {% endif %}
    {% if row.batch %}
    <a class="btn" href="{{ url_for('index', batch=row.batch) }}"
       title="Show the rest of this batch">View Batch</a>
    {% endif %}
    <button class="btn" id="edit-prompt-btn" onclick="toggleEdit()">Edit Prompt</button>
    <button class="btn btn-danger"
      onclick="confirmDelete('{{ url_for('delete_one', media_id=row.media_id) }}?back={{ back|urlencode }}',
        'Permanently delete this image? This cannot be undone.')">
      Delete
    </button>
  </div>
  <div id="prompt-editor" style="display:none;margin-top:12px;">
    <textarea id="prompt-text" style="width:100%;min-height:120px;background:var(--surface0);color:var(--text);border:1px solid var(--surface1);border-radius:6px;padding:8px;font-size:13px;font-family:var(--font-mono,monospace);">{{ row.prompt_full or row.prompt_preview or '' }}</textarea>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center;">
      <button class="btn btn-primary" onclick="savePrompt()">Save</button>
      <button class="btn" onclick="toggleEdit()">Cancel</button>
      <span id="save-status" style="color:var(--green);font-size:12px;"></span>
    </div>
  </div>
</div>
<script>
// Published-artwork engagement: live views (per artwork_id) + the captured granular NSFW
// breakdown (nsfw_scores JSON). Both only present for synced published works.
document.addEventListener('DOMContentLoaded', function(){
  var vEl = document.getElementById('detail-views');
  if (vEl && vEl.getAttribute('data-artwork')) {
    fetch('/api/artwork-views?id='+encodeURIComponent(vEl.getAttribute('data-artwork')))
      .then(function(r){return r.json();})
      .then(function(d){ if(d && d.views!=null) vEl.innerHTML='\\ud83d\\udc41 '+Number(d.views).toLocaleString()+' '; })
      .catch(function(){ vEl.textContent=''; });
  }
  var nEl = document.getElementById('detail-nsfw');
  if (nEl && nEl.getAttribute('data-scores')) {
    try {
      var s = JSON.parse(nEl.getAttribute('data-scores'));
      var parts = Object.keys(s).map(function(k){ return [k, s[k]]; })
        .filter(function(p){ return p[1] >= 0.05; })
        .sort(function(a,b){ return b[1]-a[1]; })
        .map(function(p){ return p[0]+' '+Math.round(p[1]*100)+'%'; });
      nEl.textContent = parts.length ? parts.join(' \\u00b7 ') : 'clean';
    } catch(e){ nEl.textContent=''; }
  }
});
function copyPrompt(btn) {
  var text = btn.getAttribute('data-prompt');
  navigator.clipboard.writeText(text).then(function(){
    var old = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function(){ btn.textContent = old; }, 1200);
  });
}
function copyCmd(btn) {
  var text = btn.getAttribute('data-cmd');
  navigator.clipboard.writeText(text).then(function(){
    var old = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function(){ btn.textContent = old; }, 1200);
  });
}
function suggestPrompt(btn) {
  var mid = btn.getAttribute('data-mid'), old = btn.textContent;
  btn.disabled = true; btn.textContent = 'Reading…';
  var box = document.getElementById('suggest-box');
  if (!box) { box = document.createElement('div'); box.id = 'suggest-box';
    box.style.cssText = 'margin-top:12px;padding:12px 14px;background:var(--surface0);border:1px solid var(--surface1);border-radius:8px;font-size:13px;line-height:1.5;';
    btn.closest('.detail-actions').after(box); }
  fetch('/api/suggest-prompt?media_id=' + encodeURIComponent(mid)).then(function(r){return r.json();}).then(function(d){
    btn.disabled = false; btn.textContent = old;
    var s = d.suggestions || [];
    if (d.error || !s.length) { box.innerHTML = '<span style="color:var(--overlay0);">' + (d.error || 'No suggestion returned.') + '</span>'; return; }
    box.innerHTML = '<div style="color:var(--overlay0);font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Suggested prompt(s) &middot; click to copy</div>';
    s.forEach(function(t){
      var line = document.createElement('div');
      line.className = 'suggest-line'; line.textContent = t || '';
      line.style.cssText = 'padding:6px 8px;border-radius:6px;cursor:pointer;';
      line.onclick = function(){ navigator.clipboard.writeText(t || ''); line.style.color = 'var(--emerald)'; };
      box.appendChild(line);
    });
  }).catch(function(){ btn.disabled = false; btn.textContent = old; box.innerHTML = '<span style="color:var(--red);">Network error.</span>'; });
}
function toggleEdit() {
  var e = document.getElementById('prompt-editor');
  e.style.display = e.style.display === 'none' ? 'block' : 'none';
}
function savePrompt() {
  var text = document.getElementById('prompt-text').value;
  fetch('/edit-prompt/{{ row.media_id }}', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({prompt: text})})
   .then(function(r){ return r.json(); })
   .then(function(d){
     var s = document.getElementById('save-status');
     s.textContent = d.ok ? 'Saved ✓' : 'Error';
     var cp = document.getElementById('copy-prompt-btn');
     if (cp) cp.setAttribute('data-prompt', text);
   });
}
</script>
""")

    HEALTH_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
{% macro stat(label, value, flag='') %}
<div style="background:var(--mantle);border-radius:8px;padding:14px 16px;">
  <div style="font-size:12px;color:var(--subtext);margin-bottom:6px;">{{ label }}</div>
  <div style="font-size:22px;font-weight:500;color:{{ '#e2a04a' if flag=='warn' else ('#e25555' if flag=='bad' else 'var(--text)') }};">{{ value }}</div>
</div>
{% endmacro %}
<header>
  <div class="brand"><span class="mark anim-{{ mark_anim|default('classic', true) }}{% if mark_kind == 'tile' %} mk-tile{% endif %}"><span class="mark-m">M</span><img class="mark-logo" src="{{ mark_url|default('/branding/logo.png', true) }}" alt="" onerror="this.remove()"></span><h1>Collection Health</h1></div>
  <a class="btn" href="{{ url_for('index') }}" style="margin-left:auto;">↑ Back to gallery</a>
</header>

<div style="padding:8px 20px 24px;max-width:1100px;">
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;">
    {{ stat('Images on disk', '{:,}'.format(h.total_files)) }}
    {{ stat('Storage used', h.total_size_h) }}
    {{ stat('Catalog rows', '{:,}'.format(h.catalog_rows)) }}
    {{ stat('Full-meta', h.full_meta_pct|string + '%') }}
    {{ stat('Rated', '{:,}'.format(h.rated)) }}
    {{ stat('Published', '{:,}'.format(h.published)) }}
    {{ stat('Total likes', '{:,}'.format(h.total_likes)) }}
    {{ stat('Duplicates', '{:,}'.format(h.dup_redundant), 'warn' if h.dup_redundant else '') }}
    {{ stat('Reclaimable', h.dup_bytes_h, 'warn' if h.dup_bytes else '') }}
    {{ stat('Missing files', '{:,}'.format(h.missing), 'bad' if h.missing else '') }}
  </div>

  <h2 style="margin:28px 0 10px;font-size:16px;">Images by month</h2>
  <div style="display:flex;flex-direction:column;gap:4px;">
    {% set maxm = (h.by_month|map(attribute=1)|max) if h.by_month else 1 %}
    {% for m, c in h.by_month %}
    <div style="display:flex;align-items:center;gap:10px;font-size:12px;">
      <span style="width:64px;color:var(--subtext);">{{ m }}</span>
      <div style="flex:1;background:var(--mantle);border-radius:4px;overflow:hidden;height:16px;">
        <div style="height:100%;width:{{ (100*c/maxm)|round(1) }}%;background:var(--accent);"></div>
      </div>
      <span style="width:52px;text-align:right;color:var(--subtext);">{{ '{:,}'.format(c) }}</span>
    </div>
    {% endfor %}
  </div>

  <h2 style="margin:28px 0 10px;font-size:16px;">Top models</h2>
  <div style="display:flex;flex-direction:column;gap:4px;">
    {% set maxt = (h.top_models|map(attribute=1)|max) if h.top_models else 1 %}
    {% for name, c in h.top_models %}
    <div style="display:flex;align-items:center;gap:10px;font-size:12px;">
      <span style="width:180px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            title="{{ name }}">{{ name }}</span>
      <div style="flex:1;background:var(--mantle);border-radius:4px;overflow:hidden;height:16px;">
        <div style="height:100%;width:{{ (100*c/maxt)|round(1) }}%;background:var(--accent-soft);"></div>
      </div>
      <a style="width:52px;text-align:right;color:var(--subtext);"
         href="{{ url_for('index', model=name) }}">{{ '{:,}'.format(c) }}</a>
    </div>
    {% endfor %}
  </div>

  {% if h.top_tags %}
  <h2 style="margin:28px 0 10px;font-size:16px;">Top tags &amp; contests</h2>
  <div style="display:flex;flex-wrap:wrap;gap:8px;">
    {% for name, c in h.top_tags %}
    <a href="{{ url_for('index', tag=name) }}"
       style="display:inline-flex;align-items:center;gap:6px;background:var(--mantle);border:0.5px solid var(--surface1);border-left:3px solid var(--gold);border-radius:4px;padding:4px 10px;font-size:12px;color:var(--text);text-decoration:none;">
      {{ name }} <span style="color:var(--subtext);">{{ c }}</span></a>
    {% endfor %}
  </div>
  {% endif %}

  {% if h.top_words %}
  <h2 style="margin:28px 0 10px;font-size:16px;">Prompt word cloud</h2>
  {% set wmax = h.top_words[0][1] %}
  <div style="display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;line-height:1.6;">
    {% for word, c in h.top_words %}
    <a href="{{ url_for('index', q=word) }}" title="{{ c }} images"
       style="text-decoration:none;color:var(--lavender);font-size:{{ (12 + (16 * c / wmax))|round|int }}px;">{{ word }}</a>
    {% endfor %}
  </div>
  {% endif %}

  {% if h.top_loras %}
  <h2 style="margin:28px 0 10px;font-size:16px;">Top LoRAs</h2>
  <div style="display:flex;flex-wrap:wrap;gap:8px;">
    {% for name, c in h.top_loras %}
    <a href="{{ url_for('index', lora=name) }}"
       style="display:inline-flex;align-items:center;gap:6px;background:var(--mantle);border:0.5px solid var(--surface1);border-left:3px solid var(--accent-soft);border-radius:4px;padding:4px 10px;font-size:12px;color:var(--text);text-decoration:none;">
      {{ name }} <span style="color:var(--subtext);">{{ c }}</span></a>
    {% endfor %}
  </div>
  {% endif %}

  <h2 style="margin:28px 0 10px;font-size:16px;">Folder breakdown</h2>
  <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--subtext);">
    {% for b, c in h.per_bucket.items() %}
    <span><strong style="color:var(--text);">{{ '{:,}'.format(c) }}</strong> {{ b }}</span>
    {% endfor %}
  </div>

  {% if h.dup_redundant or h.missing %}
  <div style="margin-top:24px;padding:12px 16px;background:var(--mantle);border-radius:8px;font-size:13px;color:var(--subtext);">
    {% if h.dup_redundant %}<div>· {{ '{:,}'.format(h.dup_redundant) }} duplicate copies ({{ h.dup_bytes_h }}). Run <code>--dedup</code> to quarantine.</div>{% endif %}
    {% if h.missing %}<div>· {{ '{:,}'.format(h.missing) }} catalog rows reference a file that's missing on disk. Re-run a download to refetch.</div>{% endif %}
  </div>
  {% endif %}
  {% if h.dup_redundant %}
  <div style="margin-top:14px;"><a class="back-link" href="{{ url_for('duplicates') }}">Review duplicates →</a></div>
  {% endif %}
</div>
""")

    DUPES_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
<header>
  <div class="brand"><span class="mark anim-{{ mark_anim|default('classic', true) }}{% if mark_kind == 'tile' %} mk-tile{% endif %}"><span class="mark-m">M</span><img class="mark-logo" src="{{ mark_url|default('/branding/logo.png', true) }}" alt="" onerror="this.remove()"></span><h1>Duplicate Review</h1></div>
  <a class="btn" href="{{ url_for('index') }}" style="margin-left:auto;">↑ Back to gallery</a>
</header>
<div style="padding:10px 20px 28px;max-width:1100px;">
  {% if not groups %}
  <div class="empty"><div class="big">✓</div><div>No duplicate copies found.</div></div>
  {% else %}
  <p style="color:var(--subtext);font-size:13px;">
    {{ groups|length }} media id(s) exist in more than one folder. The
    <span style="color:var(--green);">keeper</span> is the most-organized copy;
    <code>--dedup</code> would quarantine the rest. Review below, then run Dedup from the GUI Utilities tab.
  </p>
  {% for g in groups %}
  <div style="display:flex;gap:14px;align-items:flex-start;background:var(--mantle);border-radius:8px;padding:12px;margin-bottom:10px;">
    <img src="{{ url_for('thumb', media_id=g.media_id) }}" loading="lazy"
         style="width:90px;height:90px;object-fit:cover;border-radius:6px;background:var(--surface0);flex-shrink:0;">
    <div style="flex:1;min-width:0;">
      <div style="font-size:12px;color:var(--subtext);margin-bottom:4px;">media_id {{ g.media_id }}</div>
      {% for c in g.copies %}
      <div style="font-size:12px;font-family:var(--font-mono,monospace);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                  color:{{ 'var(--green)' if c.rel == g.keeper else 'var(--subtext)' }};">
        {{ 'KEEP  ' if c.rel == g.keeper else 'dupe  ' }}{{ c.rel }}
        <span style="color:var(--overlay0);">({{ c.bucket }})</span>
      </div>
      {% endfor %}
      <a class="back-link" style="font-size:12px;"
         href="{{ url_for('detail', media_id=g.media_id) }}">open →</a>
    </div>
  </div>
  {% endfor %}
  {% endif %}
</div>
""")

    PANEL_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
<style>
  .panel{padding:10px 20px 40px;max-width:1000px;}
  .p-sec{background:var(--mantle);border:1px solid var(--surface0);border-radius:12px;padding:16px 18px;margin-bottom:16px;}
  .p-sec h2{font-size:15px;margin:0 0 12px;font-weight:600;}
  .p-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;}
  .p-stat{background:var(--surface0);border-radius:8px;padding:12px 14px;}
  .p-stat .l{font-size:11.5px;color:var(--subtext);margin-bottom:5px;}
  .p-stat .v{font-size:21px;font-weight:500;color:var(--text);font-variant-numeric:tabular-nums;}
  .p-stat .v.lav{color:var(--lavender);}
  .jobrow{display:flex;flex-wrap:wrap;gap:8px;}
  .jobbtn{display:flex;flex-direction:column;align-items:flex-start;gap:2px;text-align:left;background:var(--surface0);border:1px solid var(--surface1);border-radius:8px;padding:9px 12px;cursor:pointer;color:var(--text);font-family:inherit;min-width:180px;}
  .jobbtn:hover{border-color:var(--lavender);}
  .jobbtn:disabled{opacity:.45;cursor:not-allowed;}
  .jobbtn .t{font-size:13px;font-weight:500;}
  .jobbtn .d{font-size:11px;color:var(--subtext);}
  .jobbtn.danger{border-color:#5a3a4a;} .jobbtn.danger .t{color:var(--red);}
  .p-note{font-size:12px;color:var(--subtext);margin-top:10px;}
  .p-fl{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--overlay0);margin-bottom:4px;}
  .p-sel{background:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:6px 9px;font-size:13px;font-family:inherit;}
  .p-check{display:inline-flex;align-items:center;gap:7px;color:var(--text);font-size:13px;cursor:pointer;}
  #joblog{background:var(--base);border:1px solid var(--surface1);border-radius:8px;padding:12px 14px;font-family:ui-monospace,monospace;font-size:12px;color:var(--subtext);white-space:pre-wrap;line-height:1.5;max-height:340px;overflow-y:auto;margin-top:12px;display:none;}
  #jobstatus{font-size:12.5px;margin-top:6px;}
  .st-running{color:var(--lavender);} .st-done{color:var(--emerald);} .st-failed{color:var(--red);}
  .jobprog{margin:12px 0 4px;}
  .jp-bar{height:10px;border-radius:6px;background:var(--surface1);overflow:hidden;}
  .jp-bar i{display:block;height:100%;width:0;border-radius:6px;background:linear-gradient(90deg,var(--accent),var(--accent-soft));transition:width .4s ease;}
  .jp-txt{font-size:11.5px;color:var(--subtext);margin-top:5px;font-variant-numeric:tabular-nums;}
</style>
<header>
  <div class="brand"><span class="mark anim-{{ mark_anim|default('classic', true) }}{% if mark_kind == 'tile' %} mk-tile{% endif %}"><span class="mark-m">M</span><img class="mark-logo" src="{{ mark_url|default('/branding/logo.png', true) }}" alt="" onerror="this.remove()"></span><h1>Control Panel</h1></div>
  <span id="acct-chip" class="acct-chip" title="Your PixAI balance" style="margin-left:auto;display:none;"></span>
  <a class="btn" href="{{ url_for('index') }}">↑ Back to gallery</a>
</header>
<div class="panel">
  <div class="p-sec">
    <h2>Library at a glance</h2>
    <div class="p-grid">
      <div class="p-stat"><div class="l">Images</div><div class="v">{{ '{:,}'.format(stats.images) }}</div></div>
      <div class="p-stat"><div class="l">Videos</div><div class="v">{{ '{:,}'.format(stats.videos) }}</div></div>
      <div class="p-stat"><div class="l">Collections</div><div class="v">{{ stats.collections }}</div></div>
      <div class="p-stat"><div class="l">Credits</div><div class="v lav" id="ps-credits">—</div></div>
      <div class="p-stat"><div class="l">Free cards</div><div class="v lav" id="ps-cards">—</div></div>
    </div>
    <div style="margin-top:14px;">
      <a class="btn" href="{{ url_for('export_csv_download') }}" download>&#11015; Download catalog (CSV)</a>
      <span style="font-size:11.5px;color:var(--overlay0);margin-left:8px;">saves to your Downloads &mdash; doesn&rsquo;t touch the backup folder</span>
    </div>
  </div>

  <div class="p-sec">
    <h2>Maintenance</h2>
    <div style="font-size:12px;color:var(--overlay0);margin-bottom:8px;">Safe &middot; read-only or reversible</div>
    <div class="jobrow" id="jobs-safe"></div>
    <div style="font-size:12px;color:var(--overlay0);margin:16px 0 8px;">Changes files &middot; asks first</div>
    <div class="jobrow" id="jobs-danger"></div>
    <div id="jobprog" class="jobprog" style="display:none;"><div class="jp-bar"><i></i></div><div class="jp-txt"></div></div>
    <div id="jobstatus"></div>
    <button type="button" id="job-stop" class="jobbtn danger" style="display:none;width:auto;min-width:0;margin-top:8px;" onclick="stopJob()"><span class="t">&#9632; Stop this job</span></button>
    <pre id="joblog"></pre>
    <div style="display:flex;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap;">
      <span style="font-size:12.5px;color:var(--subtext);">Download workers</span>
      <select id="dl-workers" class="p-sel" onchange="saveWorkers()">
        <option value="1">1</option><option value="2">2</option><option value="4" selected>4</option>
        <option value="6">6</option><option value="8">8</option><option value="12">12</option><option value="16">16</option>
      </select>
      <span id="workers-status" style="font-size:11.5px;color:var(--overlay0);">parallel fetches for Sync + the scheduled run</span>
    </div>
    <div class="p-note">One job runs at a time. Backup / audit / dry-runs never delete anything. Organize and Dedup move files (both reversible &mdash; Organize writes an undo manifest, Dedup quarantines to <code>_duplicates/</code>). <b>Sync</b> only pulls what's new (it stops once it hits already-downloaded items) &mdash; more workers mainly speed a big metadata backfill or a first catch-up.</div>
  </div>

  <div class="p-sec">
    <h2>Recover a task by ID</h2>
    <div style="font-size:12px;color:var(--overlay0);margin-bottom:10px;">Pull a specific generation or edit straight from PixAI into your gallery by its task id &mdash; handy for edits and anything stuck in Favorites that Sync misses (edits aren&rsquo;t in the listing Sync pages). Downloads your own finished media; spends nothing.</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <input id="import-tid" class="p-sel" style="flex:1;min-width:220px;" placeholder="task id, e.g. 2030585251815688815" autocomplete="off" onkeydown="if(event.key==='Enter')importTask()">
      <button type="button" class="jobbtn" style="width:auto;min-width:0;" onclick="importTask()"><span class="t">&#11015; Import</span></button>
    </div>
    <div id="import-status" style="font-size:12.5px;margin-top:8px;"></div>
  </div>

  <div class="p-sec">
    <h2>Automated tasks</h2>
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;">
      <label class="p-check"><input type="checkbox" id="sch-enabled"> Enabled</label>
      <div><div class="p-fl">Run</div>
        <select id="sch-action" class="p-sel"></select></div>
      <div><div class="p-fl">Every</div>
        <select id="sch-interval" class="p-sel">
          <option value="1">1 hour</option><option value="3">3 hours</option>
          <option value="6" selected>6 hours</option><option value="12">12 hours</option>
          <option value="24">1 day</option><option value="48">2 days</option><option value="168">1 week</option>
        </select></div>
      <button class="jobbtn" style="flex:0 0 auto;min-width:0;" id="sch-save" onclick="saveSchedule()"><span class="t">Save schedule</span></button>
      <span id="sch-status" style="font-size:12.5px;color:var(--subtext);"></span>
    </div>
    <div class="p-note">Only safe jobs can be scheduled (no file deletion). It fires <b>while the app is open</b> &mdash; this isn't an OS cron. For always-on, point Windows Task Scheduler at <code>pixai_gallery_backup.py --update</code>.</div>
  </div>

  <div class="p-sec">
    <h2>Live Mirror</h2>
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;">
      <span id="watch-dot" style="width:9px;height:9px;border-radius:50%;background:var(--overlay0);flex:0 0 auto;"></span>
      <span id="watch-status" style="font-size:12.5px;color:var(--subtext);">checking&hellip;</span>
    </div>
    <div class="p-note">Listens for your generations to finish over PixAI's push connection and mirrors each one the instant it completes &mdash; <code>--update</code> becomes a fallback, not the only way gens land locally. Read-only + free; always on while the server runs.</div>
  </div>

  <div class="p-sec">
    <h2>&#127912; Branding</h2>
    <div class="p-note">The <b>banner mark</b> &mdash; the icon beside the title &mdash; and its animation. <b>Set launcher icon</b> writes a Desktop shortcut whose icon is the selected mark (a .pyw can't carry its own icon; the shortcut can). The favicon stays the Gem Tome.</div>
    <div id="brand-marks" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;"></div>
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;">
      <div><div class="p-fl">Animation</div>
        <select id="brand-anim" class="p-sel"></select></div>
      <button class="jobbtn" style="flex:0 0 auto;min-width:0;" onclick="saveBrand()"><span class="t">Save</span></button>
      <button class="jobbtn" style="flex:0 0 auto;min-width:0;" onclick="setLauncher()" title="Creates/updates the Desktop 'Moonglade Athenaeum' shortcut; its icon becomes the selected mark"><span class="t">&#128279; Set launcher icon</span></button>
      <span id="brand-status" style="font-size:12.5px;color:var(--subtext);"></span>
    </div>
  </div>

  <div class="p-sec">
    <h2>&#127912; Skins</h2>
    <div class="p-note">Cosmetic palette swaps for the whole suite (moved here from the achievements panel &mdash; cosmetics live together). Unlock more by earning epic achievements in the gallery (&#127942;).</div>
    <div id="skin-grid" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;"></div>
    <span id="skin-status" style="font-size:12.5px;color:var(--subtext);"></span>
  </div>

  <div class="p-sec">
    <h2>Server</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      <button class="jobbtn" style="flex:0 0 auto;min-width:0;" id="btn-restart"
        onclick="restartServer()" {% if not supervised %}disabled title="Start via the 'Serve Gallery' launcher to enable one-click restart"{% endif %}>
        <span class="t">&#8635; Restart server</span></button>
      <button class="jobbtn danger" style="flex:0 0 auto;min-width:0;" onclick="stopServer()">
        <span class="t">&#9632; Stop server</span></button>
    </div>
    <div class="p-note">{% if supervised %}Managed by the launcher &mdash; <b>Restart</b> brings the server right back; <b>Stop</b> shuts the whole app down (relaunch from the <code>Serve Gallery</code> shortcut).{% else %}This server was started headlessly (not managed). <b>Stop</b> works; <b>Restart</b> needs the <code>Serve Gallery</code> launcher (which supervises + relaunches it).{% endif %} No more Task Manager.</div>
  </div>

  <div class="p-sec">
    <h2>This build</h2>
    <div style="font-size:13px;color:var(--subtext);">Running <b style="color:var(--text);">{{ build_stamp }}</b> &middot; library at <code>{{ out_dir }}</code></div>
    <div class="p-note">More settings (default workers, page size, verbose) land here next. Deleting from your PixAI account stays CLI-only, behind its typed confirm &mdash; on purpose.</div>
  </div>
</div>
<div id="srv-overlay">
  <div class="srv-box"><div class="srv-spin"></div>
    <div class="srv-msg" id="srv-msg">Working&hellip;</div>
    <div class="srv-sub" id="srv-sub"></div></div>
</div>
<style>
  #srv-overlay{position:fixed;inset:0;z-index:500;background:rgba(6,4,14,.86);backdrop-filter:blur(5px);display:none;align-items:center;justify-content:center;}
  #srv-overlay.on{display:flex;}
  .srv-box{text-align:center;color:var(--text);}
  .srv-spin{width:44px;height:44px;margin:0 auto 18px;border-radius:50%;border:3px solid var(--surface1);border-top-color:var(--accent);animation:srv-sp 0.9s linear infinite;}
  @keyframes srv-sp{to{transform:rotate(360deg);}}
  .srv-msg{font-size:18px;font-weight:600;}
  .srv-sub{font-size:12.5px;color:var(--subtext);margin-top:6px;}
</style>
<script>
var ACTIONS = {{ actions_json|safe }};       // Maintenance buttons -- panel_visible only
var ALL_ACTIONS = {{ all_actions_json|safe }};  // scheduler dropdown -- includes background-only jobs
function el(i){return document.getElementById(i);}
function renderJobs(){
  var safe=el('jobs-safe'), danger=el('jobs-danger');
  ACTIONS.forEach(function(a){
    var b=document.createElement('button'); b.className='jobbtn'+(a.destructive?' danger':'');
    b.innerHTML='<span class="t">'+a.label+'</span>';
    b.onclick=function(){ runJob(a); };
    (a.destructive?danger:safe).appendChild(b);
  });
}
var polling=false;
function runJob(a){
  if(a.destructive && !confirm('Run: '+a.label+'?\\n\\nThis changes files on disk (reversible). Continue?')) return;
  fetch('/api/panel/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a.action, confirm:true})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ el('jobstatus').innerHTML='<span class="st-failed">\\u26a0 '+d.error+'</span>'; return; }
      el('joblog').style.display='block'; if(!polling){ polling=true; poll(); }
    });
}
function setButtons(disabled){ document.querySelectorAll('.jobbtn').forEach(function(b){ b.disabled=disabled; }); }
function poll(){
  fetch('/api/panel/status').then(function(r){return r.json();}).then(function(d){
    var log=el('joblog'); if(d.lines){ log.textContent=d.lines.join('\\n'); log.scrollTop=log.scrollHeight; }
    var jp=el('jobprog'), p=d.progress;
    if(d.status==='running' && p && p.total){
      jp.style.display=''; jp.querySelector('.jp-bar i').style.width=(p.pct||0)+'%';
      jp.querySelector('.jp-txt').textContent=(p.done||0).toLocaleString()+' / '+(p.total||0).toLocaleString()
        +'  ('+(p.pct!=null?p.pct:0)+'%)'+(p.new?('  \\u00b7 +'+p.new+' new'):'');
    } else { jp.style.display='none'; }
    var st=el('jobstatus'), stop=el('job-stop');
    if(d.status==='running'){ st.innerHTML='<span class="st-running">\\u25c9 running: '+d.label+'\\u2026</span>'; stop.style.display=''; setButtons(true); setTimeout(poll,1000); }
    else { setButtons(false); polling=false; stop.style.display='none';
      if(d.status==='done'){ st.innerHTML='<span class="st-done">\\u2713 '+(d.label||'job')+' finished (exit '+d.rc+')</span>'; loadAcct(); }
      else if(d.status==='cancelled'){ st.innerHTML='<span class="st-failed">\\u25a0 '+(d.label||'job')+' stopped by you</span>'; loadAcct(); }
      else if(d.status==='failed'){ st.innerHTML='<span class="st-failed">\\u26a0 '+(d.label||'job')+' failed (exit '+d.rc+')</span>'; }
    }
  }).catch(function(){ polling=false; setButtons(false); });
}
function stopJob(){
  if(!confirm('Stop the running job?\\n\\nDry-runs/backups have nothing to undo; Organize and Dedup are reversible (Organize writes an undo manifest, Dedup quarantines to _duplicates/, nothing is deleted).')) return;
  el('job-stop').disabled=true;
  fetch('/api/panel/cancel',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
    el('job-stop').disabled=false;
    if(d.error) el('jobstatus').innerHTML='<span class="st-failed">\\u26a0 '+d.error+'</span>';
  }).catch(function(){ el('job-stop').disabled=false; });
}
function _acctPaint(d){
  if(d.credits!=null && el('ps-credits')) el('ps-credits').textContent=Number(d.credits).toLocaleString();
  if(d.cards!=null && el('ps-cards')) el('ps-cards').textContent=d.cards;
  var chip=el('acct-chip'); if(chip && d.credits!=null){ chip.innerHTML='\\u25c8 <b>'+Number(d.credits).toLocaleString()+'</b> \\u00b7 <span style="color:var(--lavender)">\\ud83c\\udfab '+(d.cards||0)+'</span>'; chip.style.display=''; }
}
function loadAcct(){
  // Paint the last-known balance immediately (shared cache with the header chip),
  // then only overwrite on a good read -- a transient miss never blanks it.
  try{ var cached=JSON.parse(localStorage.getItem('mg_acct')||'null'); if(cached) _acctPaint(cached); }catch(e){}
  fetch('/api/account').then(function(r){return r.json();}).then(function(d){
    if(d.error || d.credits==null) return;
    var good={credits:d.credits, cards:(d.cards!=null?d.cards:0)};
    try{ localStorage.setItem('mg_acct', JSON.stringify(good)); }catch(e){}
    _acctPaint(good);
  }).catch(function(){});
}
function importTask(){
  var tid=(document.getElementById('import-tid').value||'').trim();
  var st=document.getElementById('import-status');
  if(!/^\\d+$/.test(tid)){ st.innerHTML='<span class="st-failed">Enter a numeric task id.</span>'; return; }
  st.innerHTML='<span class="st-running">\\u25c9 Pulling task '+tid+'\\u2026</span>';
  fetch('/api/import-task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:tid})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ st.innerHTML='<span class="st-failed">\\u26a0 '+d.error+'</span>'; return; }
      if(d.already){ var n=(d.media_ids||[]).length, mid=(d.media_ids||[])[0];
        st.innerHTML='<span class="st-done">\\u2713 Already in your gallery ('+n+' item'+(n===1?'':'s')+')'
          +(mid?' \\u2014 <a href="/image/'+mid+'" style="color:var(--lavender);text-decoration:underline;">view it \\u2192</a>':'')+'</span>'; return; }
      if(!d.saved){ st.innerHTML='<span class="st-failed">\\u26a0 Task resolved but no media to import.</span>'; return; }
      st.innerHTML='<span class="st-done">\\u2713 Imported '+d.saved+' item(s) from task '+tid+' \\u2014 open the gallery to see it.</span>';
      document.getElementById('import-tid').value=''; loadAcct();
    }).catch(function(){ st.innerHTML='<span class="st-failed">\\u26a0 network error</span>'; });
}
function loadSchedule(){
  var sel=el('sch-action');
  ALL_ACTIONS.filter(function(a){return !a.destructive;}).forEach(function(a){
    var o=document.createElement('option'); o.value=a.action; o.textContent=a.label; sel.appendChild(o); });
  fetch('/api/panel/schedule').then(function(r){return r.json();}).then(function(s){
    el('sch-enabled').checked=!!s.enabled;
    if(s.action) sel.value=s.action;
    if(s.interval_hours) el('sch-interval').value=String(s.interval_hours);
    if(s.workers && el('dl-workers')) el('dl-workers').value=String(s.workers);
    if(s.last_run){ var dt=new Date(s.last_run*1000); el('sch-status').textContent='last run: '+dt.toLocaleString(); }
  }).catch(function(){});
}
function saveWorkers(){
  var w=+el('dl-workers').value, st=el('workers-status');
  fetch('/api/panel/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workers:w})})
    .then(function(r){return r.json();}).then(function(s){
      if(s.error){ st.textContent='\\u26a0 '+s.error; return; }
      st.innerHTML='<span style="color:var(--emerald)">\\u2713 '+(s.workers||w)+' workers</span> \\u00b7 Sync + scheduled run';
    }).catch(function(){ st.textContent='\\u26a0 network error'; });
}
function saveSchedule(){
  var body={enabled:el('sch-enabled').checked, action:el('sch-action').value, interval_hours:+el('sch-interval').value};
  fetch('/api/panel/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).then(function(s){
      if(s.error){ el('sch-status').textContent='\\u26a0 '+s.error; return; }
      el('sch-status').innerHTML='<span style="color:var(--emerald)">\\u2713 saved'+(s.enabled?(' \\u00b7 every '+s.interval_hours+'h while open'):' \\u00b7 disabled')+'</span>';
    }).catch(function(){ el('sch-status').textContent='\\u26a0 network error'; });
}
function _timeAgo(ts){
  var s=Math.max(0, Math.floor(Date.now()/1000 - ts));
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+'m ago';
  return Math.floor(s/3600)+'h ago';
}
function loadWatchStatus(){
  fetch('/api/watch/status').then(function(r){return r.json();}).then(function(d){
    var dot=el('watch-dot'), st=el('watch-status'); if(!dot||!st) return;
    if(d.connected){
      dot.style.background='var(--emerald)';
      var bits=['\\u25c9 connected'];
      if(d.last_event_at) bits.push('last event '+_timeAgo(d.last_event_at));
      bits.push((d.mirrored||0)+' mirrored this session');
      st.textContent=bits.join(' \\u00b7 ');
    } else {
      dot.style.background = d.last_error ? 'var(--red)' : 'var(--overlay0)';
      st.textContent = d.last_error ? ('reconnecting\\u2026 ('+d.last_error+')') : 'connecting\\u2026';
    }
  }).catch(function(){ var st=el('watch-status'); if(st) st.textContent='status unavailable'; });
}
// --- Branding: banner mark + animation + launcher shortcut ---
var _brandMark='';
function escH(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function loadBrand(){
  fetch('/api/branding').then(function(r){return r.json();}).then(function(d){
    _brandMark=d.mark;
    var row=el('brand-marks'); if(!row) return;
    if(!(d.marks||[]).length){
      row.innerHTML='<span style="font-size:12.5px;color:var(--subtext);">No cut marks on this machine yet (branding/marks/ is empty) &mdash; the header uses the drop-in logo.png.</span>';
    } else {
      row.innerHTML=(d.marks||[]).map(function(m){
        return '<span class="brand-pick" data-mark="'+escH(m.id)+'" title="'+escH(m.label)+'" style="cursor:pointer;border:2px solid var(--surface1);border-radius:10px;padding:4px;background:var(--mantle);text-align:center;">'
          +'<img src="'+escH(m.png)+'" style="width:44px;height:44px;display:block;'+(m.kind==='tile'?'border-radius:8px;':'')+'">'
          +'<span style="display:block;font-size:9.5px;color:var(--subtext);max-width:52px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+escH(m.label)+'</span></span>';
      }).join('');
      row.querySelectorAll('.brand-pick').forEach(function(p){
        p.onclick=function(){ _brandMark=p.dataset.mark; paintBrand(); };
      });
    }
    var sel=el('brand-anim');
    if(sel && !sel.options.length){ (d.anims||[]).forEach(function(a){
      var o=document.createElement('option'); o.value=a; o.textContent=a; sel.appendChild(o); }); }
    if(sel) sel.value=d.anim;
    paintBrand();
  }).catch(function(){});
}
function paintBrand(){
  var row=el('brand-marks'); if(!row) return;
  row.querySelectorAll('.brand-pick').forEach(function(p){
    p.style.borderColor = (p.dataset.mark===_brandMark) ? 'var(--lavender)' : 'var(--surface1)';
  });
}
function saveBrand(){
  var sel=el('brand-anim');
  fetch('/api/branding',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mark:_brandMark, anim:(sel?sel.value:'classic')})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ el('brand-status').textContent='\\u26a0 '+d.error; return; }
      el('brand-status').innerHTML='<span style="color:var(--emerald)">\\u2713 saved \\u00b7 refresh the gallery to see it</span>';
    }).catch(function(){ el('brand-status').textContent='\\u26a0 network error'; });
}
function setLauncher(){
  el('brand-status').textContent='writing shortcut\\u2026';
  fetch('/api/branding/shortcut',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mark:_brandMark})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ el('brand-status').textContent='\\u26a0 '+d.error; return; }
      el('brand-status').innerHTML='<span style="color:var(--emerald)">\\u2713 Desktop shortcut updated (F5 the Desktop if the icon looks stale)</span>';
    }).catch(function(){ el('brand-status').textContent='\\u26a0 network error'; });
}
// --- Skins: cosmetic palettes (moved here from the achievements panel) ---
var SKIN_SW={ moonglade:['#0c0a1c','#b692e6','#4fc99a','#d4af37'],
              nightfallen:['#0a0713','#a678f0','#7f6fe0','#d9b3ff'],
              moonlit:['#0b1018','#8fb8e8','#68d5e0','#cfe1f5'],
              ember:['#160c0c','#e8935f','#e0a94b','#ffcf7a'],
              verdant:['#0a1410','#5fd39a','#4fc99a','#c8e6a8'] };
function loadSkins(){
  fetch('/api/achievements').then(function(r){return r.json();}).then(function(d){
    var g=el('skin-grid'); if(!g) return; g.innerHTML='';
    (d.skins||[]).forEach(function(s){
      var active=(s.id===d.skin);
      var c=document.createElement('div');
      c.style.cssText='width:150px;border:1px solid '+(active?'var(--accent)':'var(--surface1)')
        +';border-radius:11px;padding:9px;background:var(--surface0);'
        +(s.earned?'cursor:pointer;':'opacity:.5;');
      var sw=(SKIN_SW[s.id]||SKIN_SW.moonglade).map(function(h){
        return '<i style="flex:1;background:'+h+'"></i>'; }).join('');
      c.innerHTML='<div style="height:30px;border-radius:7px;display:flex;overflow:hidden;margin-bottom:7px;">'+sw+'</div>'
        +'<div style="font-size:12px;font-weight:600;color:var(--text);">'+escH(s.name)
        +(active?' <span style="color:var(--accent)">\\u2713</span>':'')+'</div>'
        +'<div style="font-size:10px;color:var(--subtext);margin-top:2px;">'+escH(s.desc)+'</div>'
        +(s.earned?'':'<div style="font-size:10px;color:var(--overlay0);margin-top:3px;">\\ud83d\\udd12 locked</div>');
      if(s.earned) c.onclick=function(){ pickSkin(s.id); };
      g.appendChild(c);
    });
  }).catch(function(){});
}
function pickSkin(id){
  fetch('/api/skin',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({skin:id})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ el('skin-status').textContent='\\u26a0 '+d.error; return; }
      try{ localStorage.setItem('skin', d.skin||'moonglade'); }catch(e){}
      if(d.skin && d.skin!=='moonglade') document.documentElement.setAttribute('data-skin', d.skin);
      else document.documentElement.removeAttribute('data-skin');
      el('skin-status').innerHTML='<span style="color:var(--emerald)">\\u2713 skin applied suite-wide</span>';
      loadSkins();
    }).catch(function(){ el('skin-status').textContent='\\u26a0 network error'; });
}
// --- Server control (Homebridge-style stop / restart from the browser) ---
function _srvOverlay(msg, sub){ el('srv-msg').textContent=msg; el('srv-sub').textContent=sub||''; el('srv-overlay').classList.add('on'); }
function stopServer(){
  if(!confirm('Stop the server?\\n\\nThe web interface goes offline until you relaunch it from the \"Serve Gallery\" shortcut.')) return;
  _srvOverlay('Stopping the server\\u2026','');
  fetch('/api/server/stop',{method:'POST'}).catch(function(){});
  _watchServer(false);
}
function restartServer(){
  if(!confirm('Restart the server?\\n\\nIt goes offline for a few seconds, then this page reconnects automatically.')) return;
  _srvOverlay('Restarting the server\\u2026','This page reconnects on its own.');
  fetch('/api/server/restart',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
    if(d && d.error){ el('srv-overlay').classList.remove('on'); alert(d.error); return; }
    _watchServer(true);
  }).catch(function(){ _watchServer(true); });
}
function _watchServer(comeBack){
  // Poll liveness. Restart: wait until it goes down THEN comes back -> reload. Stop: wait until it stops answering.
  var tries=0, sawDown=false;
  var iv=setInterval(function(){
    tries++;
    fetch('/api/ping',{cache:'no-store'}).then(function(r){ return r.ok; }).then(function(ok){
      if(comeBack && ok && sawDown){ clearInterval(iv); location.reload(); }
      if(comeBack && ok && tries>=8 && !sawDown){ clearInterval(iv); location.reload(); } // never saw a gap; just reload
    }).catch(function(){
      sawDown=true;
      if(!comeBack){ clearInterval(iv); el('srv-msg').textContent='Server stopped.'; el('srv-sub').textContent='Relaunch any time from the \"Serve Gallery\" shortcut.'; el('srv-spin').style.display='none'; }
    });
    if(tries>50){ clearInterval(iv); el('srv-msg').textContent=comeBack?'Still restarting\\u2026 give it a moment, then refresh.':'Server stopped.'; el('srv-spin').style.display='none'; }
  }, 800);
}
renderJobs(); loadAcct(); loadSchedule(); loadBrand(); loadSkins(); loadWatchStatus();
setInterval(loadWatchStatus, 8000);
// if a job was already running when the page loaded, resume polling
fetch('/api/panel/status').then(function(r){return r.json();}).then(function(d){ if(d.status==='running'){ el('joblog').style.display='block'; polling=true; poll(); } });
</script>
""")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _page_range(page, total_pages, window=2):
        pages = []
        for p in range(1, total_pages + 1):
            if p == 1 or p == total_pages or abs(p - page) <= window:
                pages.append(p)
        result = []
        prev = None
        for p in pages:
            if prev and p - prev > 1:
                result.append("…")
            result.append(p)
            prev = p
        return result

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @app.route("/health")
    def health():
        return render_template_string(
            HEALTH_HTML, h=collection_health(out_dir, db_path))

    @app.route("/panel")
    def panel():
        # actions -> Maintenance buttons (panel_visible only). all_actions -> the
        # scheduler dropdown, which needs the background-only jobs too (that's their
        # only home now that they're not buttons).
        all_actions = [{"action": k, "label": v["label"], "destructive": v["destructive"]}
                       for k, v in PANEL_ACTIONS.items()]
        actions = [a for a, (k, v) in zip(all_actions, PANEL_ACTIONS.items())
                  if v.get("panel_visible", True)]
        return render_template_string(
            PANEL_HTML, stats=catalog_counts(db_path), build_stamp=build_stamp,
            all_actions_json=json.dumps(all_actions),
            out_dir=str(out_dir), actions_json=json.dumps(actions),
            supervised=_supervised())

    @app.route("/api/ping")
    def api_ping():
        """Cheap liveness probe — the Stop/Restart reconnect overlay polls this. Open."""
        return jsonify({"ok": True})

    @app.route("/api/server/stop", methods=["POST"])
    def api_server_stop():
        """Shut the server down cleanly from the browser (Homebridge-style) instead of Task
        Manager. Localhost-only. Under the managed launcher this ends the whole app."""
        if not _is_local_request():
            return jsonify({"error": "server control is localhost-only"}), 403
        _schedule_server_exit(0)
        return jsonify({"ok": True, "action": "stop"})

    @app.route("/api/server/restart", methods=["POST"])
    def api_server_restart():
        """Restart the server from the browser. Needs the managed launcher (Serve Gallery),
        which relaunches on exit code 42; otherwise the process would just stop. Localhost-only."""
        if not _is_local_request():
            return jsonify({"error": "server control is localhost-only"}), 403
        if not _supervised():
            return jsonify({"error": "Restart needs the managed launcher — start via "
                                     "'Serve Gallery'. (Stop still works.)"}), 409
        _schedule_server_exit(42)
        return jsonify({"ok": True, "action": "restart"})

    @app.route("/export-csv")
    def export_csv_download():
        """Download the catalog as a CSV -- from the browser you get a real file (Downloads),
        not a copy silently written into the backup folder. Built in memory. Localhost-only.
        (The CLI --export-csv still writes to disk on purpose, for scripting.)"""
        if not _is_local_request():
            return "localhost-only", 403
        import io
        import datetime
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for r in load_catalog(db_path):
            writer.writerow({f: r.get(f, "") for f in CATALOG_FIELDS})
        mem = io.BytesIO(buf.getvalue().encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="text/csv", as_attachment=True,
                         download_name="moonglade-catalog-{}.csv".format(
                             datetime.date.today().isoformat()))

    @app.route("/api/panel/run", methods=["POST"])
    def api_panel_run():
        """Start a whitelisted maintenance job as a background subprocess. Destructive
        actions require confirm=true. One job at a time. Localhost-only."""
        if not _is_local_request():
            return jsonify({"error": "control panel is localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip()
        spec = PANEL_ACTIONS.get(action)
        if not spec:
            return jsonify({"error": "unknown action"}), 400
        if spec["destructive"] and not body.get("confirm"):
            return jsonify({"error": "this action changes files; confirm required"}), 400
        with _panel_lock:
            if _panel_job["status"] == "running":
                return jsonify({"error": "a job is already running"}), 409
        try:
            _panel_run(action)
            return jsonify({"ok": True, "action": action, "label": spec["label"]})
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 200

    @app.route("/api/import-task", methods=["POST"])
    def api_import_task():
        """Pull ONE generation/edit task's media into the gallery by its task id -- recovers
        edits + anything stuck in Favorites that --update's listing skips (edits aren't in that
        listing). Downloads the owner's OWN finished media; spends nothing. Localhost-only.
        Logs to the Activity card. Returns {saved, media_ids, is_video} or {error}."""
        if not _is_local_request():
            return jsonify({"error": "import is localhost-only"}), 403
        tid = str((request.get_json(silent=True) or {}).get("task_id") or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "enter a numeric task id"}), 200
        # "Look behind the milk": if this task is already catalogued, don't re-fetch --
        # just report it's here + hand back its media so the UI can jump straight to it.
        con = _connect(db_path)
        try:
            pre = [r[0] for r in con.execute(
                "SELECT media_id FROM catalog WHERE task_id=?", (tid,)).fetchall()]
        finally:
            con.close()
        if pre:
            return jsonify({"ok": True, "already": True, "saved": 0, "media_ids": pre})
        job_id = "import-" + tid[-8:]
        _log_job(job_id, status="running", type="import", label="Import task " + tid)
        try:
            core, session = _gen_session()
            res = core.collect_generation(session, tid, str(out_dir))
            n, mids = int(res.get("saved") or 0), (res.get("media_ids") or [])
            _log_job(job_id, status="done", media_ids=mids,
                     label="Imported {} media from task {}".format(n, tid))
            return jsonify({"ok": True, "saved": n, "media_ids": mids,
                            "is_video": bool(res.get("is_video"))})
        except Exception as e:
            _log_job(job_id, status="failed", error=str(e)[:200])
            return jsonify({"error": str(e)[:200]}), 200

    @app.route("/api/panel/status")
    def api_panel_status():
        if not _is_local_request():
            return jsonify({"status": "idle"}), 403
        with _panel_lock:
            return jsonify({"status": _panel_job["status"], "action": _panel_job["action"],
                            "label": _panel_job["label"], "rc": _panel_job["rc"],
                            "progress": _panel_job["progress"],
                            "lines": list(_panel_job["lines"])})

    @app.route("/api/watch/status")
    def api_watch_status():
        """Live-mirror watcher health: is the push WebSocket connected right now, when
        did it last see an event, how many gens has it mirrored this server run."""
        if not _is_local_request():
            return jsonify({"connected": False}), 403
        with _watch_lock:
            return jsonify(dict(_watch_status))

    @app.route("/api/panel/cancel", methods=["POST"])
    def api_panel_cancel():
        """Stop the running maintenance job from the browser (no Task Manager). Terminates the
        subprocess; the reader marks it 'cancelled'. Safe: dry-runs/backups do nothing to undo,
        and organize/dedup are reversible (organize writes an undo manifest, dedup quarantines).
        Localhost-only."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        with _panel_lock:
            proc = _panel_job.get("proc")
            running = _panel_job["status"] == "running"
            if running and proc is not None:
                _panel_job["cancelled"] = True
        if not (running and proc is not None):
            return jsonify({"ok": False, "error": "no job is running"}), 200
        try:
            proc.terminate()   # reader sees stdout close -> finalizes status as 'cancelled'
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:140]}), 200
        return jsonify({"ok": True, "action": "cancel"})

    @app.route("/api/panel/schedule", methods=["GET", "POST"])
    def api_panel_schedule():
        """Panel settings: the automated-task schedule + the download-workers count. GET
        returns the current settings; POST MERGES only the fields present (so the schedule
        toggle and the workers selector -- two separate controls writing this one file --
        never wipe each other). Only non-destructive actions are schedulable. Localhost-only."""
        if not _is_local_request():
            return jsonify({}), 403
        with _sched_lock:
            s = _load_sched()
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                if "action" in body and body.get("action"):
                    s["action"] = str(body.get("action"))
                if "enabled" in body:
                    s["enabled"] = bool(body.get("enabled"))
                if "interval_hours" in body:
                    try:
                        s["interval_hours"] = max(1, min(int(body.get("interval_hours") or 6), 168))
                    except (TypeError, ValueError):
                        s["interval_hours"] = 6
                if "workers" in body:
                    try:
                        # no `or 4` -- workers=0 must clamp to 1, not fall through to 4
                        s["workers"] = max(1, min(int(body.get("workers")), 16))
                    except (TypeError, ValueError):
                        s["workers"] = 4
                if s.get("action") not in PANEL_ACTIONS or PANEL_ACTIONS[s["action"]]["destructive"]:
                    return jsonify({"error": "only safe jobs can be scheduled"}), 400
                _save_sched(s)
            return jsonify(s)

    @app.route("/duplicates")
    def duplicates():
        return render_template_string(
            DUPES_HTML, groups=duplicate_groups(out_dir))

    @app.route("/")
    def index():
        q            = request.args.get("q", "")
        model_filter = request.args.get("model", "")
        batch_filter = request.args.get("batch", "")
        sort         = request.args.get("sort", "newest")
        page         = int(request.args.get("page", 1))

        # Date filters come from Year+Month dropdowns and assemble into YYYY-MM.
        # A year with no month still filters by year (month defaults to 01/12).
        def _ym(prefix, month_default):
            y = request.args.get(prefix + "_year", "")
            m = request.args.get(prefix + "_month", "")
            if not y:
                return ""
            return "{}-{}".format(y, m or month_default)
        date_from = _ym("from", "01")
        date_to   = _ym("to", "12")

        per_page_opts = [50, 100, 200, 500]
        try:
            per_page = int(request.args.get("per_page", PAGE_SIZE))
        except ValueError:
            per_page = PAGE_SIZE
        if per_page not in per_page_opts:
            per_page = PAGE_SIZE

        try:
            rating_min = max(0, min(5, int(request.args.get("rating_min", 0))))
        except ValueError:
            rating_min = 0
        published_only = request.args.get("published") == "1"
        art_tag = request.args.get("tag", "")
        lora_filter = request.args.get("lora", "")
        media_type = request.args.get("media", "")
        if media_type not in ("image", "video"):
            media_type = ""
        source = request.args.get("source", "")
        if source not in ("online", "api", "local", "deleted"):
            source = ""
        collection = request.args.get("collection", "")

        models  = unique_models(db_path)
        batches = unique_batches(db_path)
        years   = catalog_years(db_path)
        collections = unique_collections(db_path)
        page_rows, total = query_catalog(
            db_path, q, model_filter, date_from, date_to, sort, page, per_page,
            batch=batch_filter, rating_min=rating_min,
            published_only=published_only, art_tag=art_tag, lora=lora_filter,
            media_type=media_type, source=source, collection=collection,
        )
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        for r in page_rows:
            mid = r["media_id"]
            tmid = mid
            if r.get("is_video") == "1" and not (thumb_dir / "{}.jpg".format(mid)).exists():
                # fall back to the still-frame poster's thumb if the video's own
                # poster thumb wasn't generated (older sync runs)
                tmid = r.get("poster_media_id") or mid
            r["_thumb_mid"] = tmid
            r["_has_thumb"] = (thumb_dir / "{}.jpg".format(tmid)).exists()

        def page_url(p):
            args = dict(request.args)
            args["page"] = p
            return url_for("index", **args)

        def _without(*keys):
            args = {k: v for k, v in request.args.items() if k not in keys}
            args.pop("page", None)
            return url_for("index", **args)

        # Active-filter chips (label + a URL that removes just that filter).
        chips = []
        if q:
            chips.append({"k": "search", "v": q, "url": _without("q")})
        if model_filter:
            chips.append({"k": "model", "v": model_filter, "url": _without("model")})
        if batch_filter:
            chips.append({"k": "batch", "v": batch_filter, "url": _without("batch")})
        if rating_min:
            chips.append({"k": "rating", "v": "★" * rating_min + "+",
                          "url": _without("rating_min")})
        if date_from:
            chips.append({"k": "from", "v": date_from,
                          "url": _without("from_year", "from_month")})
        if date_to:
            chips.append({"k": "to", "v": date_to,
                          "url": _without("to_year", "to_month")})
        if published_only:
            chips.append({"k": "published", "v": "yes", "url": _without("published")})
        if art_tag:
            chips.append({"k": "tag", "v": art_tag, "url": _without("tag")})
        if lora_filter:
            chips.append({"k": "lora", "v": lora_filter, "url": _without("lora")})
        if media_type:
            chips.append({"k": "media", "v": media_type + "s", "url": _without("media")})
        if source:
            chips.append({"k": "source", "v": source, "url": _without("source")})
        if collection:
            chips.append({"k": "collection", "v": collection, "url": _without("collection")})

        return render_template_string(
            INDEX_HTML,
            chips=chips, published_only=published_only, art_tag=art_tag,
            lora_filter=lora_filter, media_type=media_type, source_filter=source,
            collection=collection, collections=collections,
            rows=page_rows, total=total, page=page, stats=catalog_counts(db_path),
            build_stamp=build_stamp, is_local=_is_local_request(),
            total_pages=total_pages, page_range=_page_range(page, total_pages),
            q=q, model_filter=model_filter, batch_filter=batch_filter,
            date_from=date_from,
            date_to=date_to, sort=sort, models=models, batches=batches,
            years=years, per_page=per_page, per_page_opts=per_page_opts,
            rating_min=rating_min,
            page_url=page_url, request=request,
            current_url=request.url,
        )

    @app.route("/image/<media_id>")
    def detail(media_id):
        row = get_row(db_path, media_id)
        if not row:
            return "Image not found.", 404

        img_path = find_image_file(out_dir, media_id, row.get("filename"))
        img_url = None
        if img_path:
            img_url = url_for("serve_image", rel=str(img_path.relative_to(out_dir)).replace("\\", "/"))

        back = request.args.get("back", url_for("index"))

        # Parse filter/sort state from back URL to compute prev/next
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(back)
        qs = parse_qs(parsed.query)
        def _qs1(key, default=""):
            vals = qs.get(key, [])
            return vals[0] if vals else default
        # Reassemble the date filters the same way index() does, so prev/next
        # navigation respects the active Year/Month dropdown filter.
        def _ym(prefix, month_default):
            y = _qs1(prefix + "_year")
            return "{}-{}".format(y, _qs1(prefix + "_month") or month_default) if y else ""
        try:
            _rmin = max(0, min(5, int(_qs1("rating_min", "0"))))
        except ValueError:
            _rmin = 0
        nav_ids = list_media_ids(
            db_path,
            q=_qs1("q"), model=_qs1("model"),
            date_from=_ym("from", "01"), date_to=_ym("to", "12"),
            sort=_qs1("sort", "newest"), batch=_qs1("batch"), rating_min=_rmin,
            published_only=(_qs1("published") == "1"), art_tag=_qs1("tag"),
            lora=_qs1("lora"), media_type=_qs1("media"), source=_qs1("source"),
            collection=_qs1("collection"),
        )
        try:
            idx = nav_ids.index(media_id)
        except ValueError:
            idx = -1
        prev_id = nav_ids[idx - 1] if idx > 0 else None
        next_id = nav_ids[idx + 1] if 0 <= idx < len(nav_ids) - 1 else None

        poster_url = None
        if row.get("is_video") == "1":
            for pmid in (media_id, row.get("poster_media_id")):
                if pmid and (thumb_dir / "{}.jpg".format(pmid)).exists():
                    poster_url = url_for("thumb", media_id=pmid)
                    break

        return render_template_string(
            DETAIL_HTML, row=row, img_url=img_url, back=back,
            prev_id=prev_id, next_id=next_id, poster_url=poster_url,
        )

    @app.route("/delete/<media_id>", methods=["POST"])
    def delete_one(media_id):
        back = request.args.get("back") or url_for("index")
        row = get_row(db_path, media_id)
        if row:
            purge_media_local(out_dir, thumb_dir, db_path, media_id, row.get("filename"))
        return redirect(back)

    @app.route("/delete-bulk", methods=["POST"])
    def delete_bulk():
        back = request.form.get("back") or url_for("index")
        media_ids = set(request.form.getlist("media_ids"))
        if not media_ids:
            return redirect(back)

        to_delete = {mid: get_row(db_path, mid) for mid in media_ids}
        to_delete = {mid: r for mid, r in to_delete.items() if r}

        for mid, row in to_delete.items():
            purge_media_local(out_dir, thumb_dir, db_path, mid, row.get("filename"))

        if to_delete:
            telem_bump("culled", len(to_delete), out_dir=out_dir)   # The Great Sweep
        return redirect(back)

    def _purge_local(media_id, filename):
        """Remove a media's catalog row + thumbnail; quarantine its file to _deleted/
        (recoverable) rather than destroying it."""
        purge_media_local(out_dir, thumb_dir, db_path, media_id, filename)

    @app.route("/delete-tasks-bulk", methods=["POST"])
    def delete_tasks_bulk():
        """Delete the selected images' TASKS from PixAI (irreversible) AND purge
        them locally, so cloud and catalog never drift. Task-level: deleting any
        image deletes its whole task (all batch images), cloud + local. Imports
        with no task id are purged locally only. Runs OFF-THREAD and reports progress
        to the Activity card; localhost-only (this destroys on the owner's account)."""
        import urllib.parse
        import uuid
        import pixai_gallery_backup as core   # lazy: avoid import cycle
        back = request.form.get("back") or url_for("index")

        def _back(**params):
            sep = "&" if "?" in back else "?"
            return redirect(back + sep + urllib.parse.urlencode(params))

        # Defense-in-depth: the UI hides this for LAN viewers, but the endpoint itself
        # must refuse a non-local request -- it deletes from the owner's PixAI account.
        if not _is_local_request():
            return _back(delerr="deleting from PixAI is localhost-only")
        sel = request.form.getlist("media_ids")
        if not sel:
            return redirect(back)

        con = _connect(db_path)
        try:
            sel_rows = [con.execute(
                "SELECT media_id, task_id, filename FROM catalog WHERE media_id=?", (m,)
            ).fetchone() for m in sel]
        finally:
            con.close()
        sel_rows = [dict(r) for r in sel_rows if r]
        task_ids = sorted({(r.get("task_id") or "").strip()
                           for r in sel_rows if (r.get("task_id") or "").strip()})
        local_only = [r for r in sel_rows if not (r.get("task_id") or "").strip()]
        total = len(task_ids) + len(local_only)
        if not total:
            return redirect(back)

        # Single-flight: never let two bulk deletes interleave their cloud calls.
        with _bulkdel_lock:
            if _bulkdel_running["on"]:
                return _back(delerr="a bulk delete is already running -- see the Activity card")
            _bulkdel_running["on"] = True

        job_id = "bulkdel-" + uuid.uuid4().hex[:12]
        label = ("Delete {} task(s) from PixAI".format(len(task_ids)) if task_ids
                 else "Purge {} local item(s)".format(len(local_only)))
        _log_job(job_id, status="running", type="delete", label=label, done=0, total=total)

        def _work():
            deleted = failed = removed = done = 0
            step = max(1, total // 50)          # throttle progress writes (~every 2%)
            def _tick():
                if done % step == 0 or done == total:
                    _log_job(job_id, status="running", done=done, total=total)
            try:
                session = core._make_session(None) if task_ids else None
                for tid in task_ids:
                    try:
                        core.delete_task_gql(session, tid)      # cloud delete (irreversible)
                        deleted += 1
                    except Exception:                            # noqa: BLE001
                        failed += 1
                        done += 1; _tick(); continue
                    con2 = _connect(db_path)
                    try:
                        media = con2.execute(
                            "SELECT media_id, filename FROM catalog WHERE task_id=?", (tid,)
                        ).fetchall()
                    finally:
                        con2.close()
                    for m in media:
                        _purge_local(m[0], m[1]); removed += 1
                    done += 1; _tick()
                for r in local_only:
                    _purge_local(r["media_id"], r.get("filename")); removed += 1
                    done += 1; _tick()
                summary = "Deleted {} · purged {} local · {} failed".format(deleted, removed, failed)
                # ANY failure is a non-clean result -- surface it RED on the card. Don't bury
                # "3 failed" inside a green 'done': those tasks still exist on PixAI (drift).
                status = "failed" if failed else "done"
                _log_job(job_id, status=status, label=summary, done=total, total=total,
                         error=(summary if failed else None))
            except Exception as e:                               # noqa: BLE001
                _log_job(job_id, status="failed", error=str(e)[:200])
            finally:
                with _bulkdel_lock:
                    _bulkdel_running["on"] = False

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception as e:                               # noqa: BLE001 -- OS thread exhaustion, etc.
            with _bulkdel_lock:                              # never wedge single-flight forever
                _bulkdel_running["on"] = False
            _log_job(job_id, status="failed", error="could not start delete thread: " + str(e)[:160])
            return _back(delerr="could not start bulk delete -- try again")
        return _back(bulkdel="started", n=total)

    @app.route("/rate/<media_id>", methods=["POST"])
    def rate(media_id):
        data = request.get_json(silent=True) or {}
        try:
            value = max(0, min(5, int(data.get("rating", 0))))
        except (TypeError, ValueError):
            return json.dumps({"ok": False}), 400, {"Content-Type": "application/json"}
        update_rating(db_path, media_id, value)
        return json.dumps({"ok": True, "rating": value}), 200, {"Content-Type": "application/json"}

    @app.route("/edit-prompt/<media_id>", methods=["POST"])
    def edit_prompt(media_id):
        data = request.get_json(silent=True) or {}
        update_prompt_full(db_path, media_id, data.get("prompt", ""))
        return json.dumps({"ok": True}), 200, {"Content-Type": "application/json"}

    @app.route("/collection-add", methods=["POST"])
    def collection_add():
        back = request.form.get("back") or url_for("index")
        ids = request.form.getlist("media_ids")
        name = request.form.get("name", "")
        n = add_to_collection(db_path, ids, name)
        sep = "&" if "?" in back else "?"
        return redirect("{}{}collected={}".format(back, sep, n))

    @app.route("/collection-remove", methods=["POST"])
    def collection_remove():
        back = request.form.get("back") or url_for("index")
        ids = request.form.getlist("media_ids")
        name = request.form.get("name", "")
        remove_from_collection(db_path, ids, name)
        return redirect(back)

    @app.route("/bulk-replace-prompt", methods=["POST"])
    def bulk_replace():
        back = request.form.get("back") or url_for("index")
        ids = request.form.getlist("media_ids")
        find = request.form.get("find", "")
        replace = request.form.get("replace", "")
        n = bulk_replace_prompt(db_path, ids, find, replace)
        # stash a one-shot result in the query string for a small banner
        sep = "&" if "?" in back else "?"
        return redirect("{}{}replaced={}".format(back, sep, n))

    # Thumbnails and full images are content-addressed (keyed by media_id /
    # filename) and never change once written, so we can cache them in the browser
    # essentially forever. This makes pagination, back-navigation, and re-visits
    # instant with zero re-download -- the single biggest win on mobile / LAN.
    _IMMUTABLE = "public, max-age=31536000, immutable"

    @app.route("/thumbs/<media_id>.jpg")
    def thumb(media_id):
        resp = send_from_directory(str(thumb_dir), "{}.jpg".format(media_id),
                                   max_age=31536000)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/img/<path:rel>")
    def serve_image(rel):
        resp = send_from_directory(str(out_dir), rel, max_age=31536000)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/video-file/<media_id>")
    def video_file(media_id):
        row = get_row(db_path, media_id)
        if not row or row.get("is_video") != "1" or not row.get("filename"):
            return "Video not found.", 404
        # send_from_directory supports HTTP Range, so the <video> can seek
        resp = send_from_directory(str(out_dir), row["filename"], max_age=31536000)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/manifest.webmanifest")
    def manifest():
        icon = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
                "viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23cba6f7'/%3E"
                "%3Cpath d='M9 22V10h6a4 4 0 0 1 0 8h-3' stroke='%231e1e2e' stroke-width='2.4' "
                "fill='none' stroke-linecap='round'/%3E%3Ccircle cx='23' cy='11' r='2.2' "
                "fill='%23d4af37'/%3E%3C/svg%3E")
        return app.response_class(
            json.dumps({
                "name": "Moonglade Athenaeum", "short_name": "Moonglade",
                "start_url": "/", "display": "standalone",
                "background_color": "#0c0a1c", "theme_color": "#0c0a1c",
                "icons": [{"src": icon, "sizes": "any", "type": "image/svg+xml"}],
            }),
            mimetype="application/manifest+json")

    @app.route("/sw.js")
    def service_worker():
        # Cache-first for immutable thumbnails/images; network for everything else.
        # v2: only cache OK (200) responses -- NEVER a 404 -- so a thumbnail that
        # didn't exist yet (poster-less video mid-collect) can't get its miss frozen
        # into the cache. Bumping the cache name + deleting old caches on activate
        # self-heals any client still holding a poisoned v1 404 (no hard-refresh needed).
        sw = (
            "const C='pixai-img-v2';\n"
            "self.addEventListener('install',e=>self.skipWaiting());\n"
            "self.addEventListener('activate',e=>e.waitUntil(\n"
            "  caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))\n"
            "  .then(()=>self.clients.claim())));\n"
            "self.addEventListener('fetch',e=>{\n"
            " const u=new URL(e.request.url);\n"
            " if(e.request.method==='GET' && (u.pathname.startsWith('/thumbs/')||u.pathname.startsWith('/img/')||u.pathname.startsWith('/full/'))){\n"
            "  e.respondWith(caches.open(C).then(c=>c.match(e.request).then(r=>r||fetch(e.request).then(resp=>{if(resp&&resp.ok)c.put(e.request,resp.clone());return resp;}))));\n"
            " }\n"
            "});\n")
        return app.response_class(sw, mimetype="application/javascript")

    @app.route("/full/<media_id>")
    def full_image(media_id):
        # Resolve a media_id to its full-res file on the fly (used by the
        # lightbox so the index page doesn't precompute 250 image paths).
        row = get_row(db_path, media_id)
        p = find_image_file(out_dir, media_id, row.get("filename") if row else "")
        if not p or not p.exists():
            return "Not found", 404
        resp = send_from_directory(str(p.parent), p.name, max_age=31536000)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/export-zip", methods=["POST"])
    def export_zip():
        # Stream a ZIP of the selected images' full-res files. Stored (no
        # recompression) since images are already compressed.
        import io
        import zipfile
        ids = request.form.getlist("media_ids")
        mem = io.BytesIO()
        n = 0
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
            seen_names = set()
            for mid in ids[:2000]:  # safety cap
                row = get_row(db_path, mid)
                if not row:
                    continue
                p = find_image_file(out_dir, mid, row.get("filename"))
                if not p or not p.exists():
                    continue
                name = p.name
                if name in seen_names:
                    name = "{}_{}".format(mid, p.name)
                seen_names.add(name)
                z.write(p, arcname=name)
                n += 1
        if not n:
            return "No matching images found.", 404
        mem.seek(0)
        return send_file(mem, mimetype="application/zip", as_attachment=True,
                         download_name="pixai_selection_{}.zip".format(n))

    # --- Generation surface (localhost-gated) --------------------------------
    # The Generate drawer talks to PixAI with the OWNER's API key and can spend
    # credits. So every generation endpoint is gated to local requests: exposing the
    # gallery on the LAN (--host 0.0.0.0) must never let another device use the key or
    # spend credits. Read-only browsing stays open; generation is owner-only.
    def _is_local_request():
        ra = (request.remote_addr or "").strip()
        return ra in ("127.0.0.1", "::1", "localhost", "")

    def _gen_session():
        import pixai_gallery_backup as core
        return core, core._make_session(None)

    @app.route("/api/model-search")
    def api_model_search():
        """Search PixAI models/LoRAs for the picker grid. Read-only, owner's key -> localhost only.
        ?q=&kind=base|lora&size=N&offset=N&category=&sort=popular|newest.

        Two data sources by design: the REST /search (default) has RICH rows (description /
        refCount / official badge) but silently ignores market filters; the GraphQL
        `generationModels` connection actually honors category + a Newest sort but has leaner
        rows. So we use GraphQL ONLY when a category or Newest is requested, REST otherwise --
        the card renders both (leaner rows just hide the missing fields)."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only", "results": []}), 403
        q = (request.args.get("q") or "").strip()
        usage = "LORA" if (request.args.get("kind") or "base").lower() == "lora" else "MODEL"
        category = (request.args.get("category") or "").strip().lower()
        sort = (request.args.get("sort") or "").strip().lower()
        try:
            size = max(1, min(int(request.args.get("size") or 24), 50))
            offset = max(0, int(request.args.get("offset") or 0))
        except ValueError:
            size, offset = 24, 0
        try:
            core, session = _gen_session()
            use_market = category in core.MARKET_CATEGORIES or sort == "newest"
            if use_market:
                return jsonify(core.model_search_market_gql(
                    session, keyword=q, category=category, sort=sort, usage=usage, limit=size))
            return jsonify(core.model_search_rest(session, keyword=q, usage=usage,
                                                  size=size, offset=offset))
        except Exception as e:
            return jsonify({"error": str(e)[:200], "results": []}), 200

    @app.route("/api/model-version")
    def api_model_version():
        """Resolve a model_id (from the grid) to its generatable version id + the version
        metadata the picker needs: model_type (for LoRA↔base compat), lora_base_model_type,
        trigger_words (to offer inserting into the prompt), and the author's tuned preset.
        Localhost-only; read-only, one API call."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only", "version_id": ""}), 403
        mid = (request.args.get("model_id") or "").strip()
        if not mid:
            return jsonify({"error": "model_id required", "version_id": ""}), 400
        try:
            core, session = _gen_session()
            return jsonify(core.resolve_version_meta(session, mid))
        except Exception as e:
            return jsonify({"error": str(e)[:200], "version_id": ""}), 200

    @app.route("/api/gallery-images")
    def api_gallery_images():
        """Pick-from-your-gallery source for the create surfaces + The Loom: recent (or
        keyword-filtered) IMAGE media_ids with thumbnails -> use the media_id full-res, no
        re-upload. Read-only. NOT localhost-gated: it reads ONLY the local catalog and
        returns the same thumbnails/prompts the gallery already serves openly, so the gate
        added no protection while breaking the picker for the owner on a --host 0.0.0.0
        server accessed via a LAN address. Spending still gated on the generate/upload
        routes. ?q=&limit=&page="""
        q = (request.args.get("q") or "").strip()
        try:
            limit = max(1, min(int(request.args.get("limit") or 40), 100))
            page = max(1, int(request.args.get("page") or 1))
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            limit, page, rating_min = 40, 1, 0
        sort = "oldest" if (request.args.get("sort") or "") == "oldest" else "newest"
        # type: image (default -> back-compat with the create pickers) | video | all.
        # Filtering happens in SQL (media_type) so pagination + total are correct even
        # for videos (a tiny slice of the catalog); the old post-query skip returned
        # near-empty pages for anything video-heavy.
        gtype = (request.args.get("type") or "image").strip().lower()
        media_type = gtype if gtype in ("image", "video") else ""   # "" = both
        rows, total = query_catalog(
            db_path, q=q, sort=sort, page=page, page_size=limit,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            rating_min=rating_min, media_type=media_type)
        out = []
        for r in rows:
            mid = r.get("media_id")
            if not mid:
                continue
            isv = str(r.get("is_video") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "thumb": "/thumbs/{}.jpg".format(mid),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000]})
        return jsonify({"images": out, "total": total, "page": page, "limit": limit})

    @app.route("/api/similar/<media_id>")
    def api_similar(media_id):
        """'More like this': the k catalog images most visually similar to media_id, via the
        pixai_similar CLIP sidecar index. Mirrors /api/gallery-images's shape so the client
        reuses the same .card rendering. Read-only; fails soft to an empty list if the sidecar
        index or its ML stack isn't available/built yet, so it never 500s the gallery."""
        try:
            k = max(1, min(int(request.args.get("k") or 24), 60))
        except ValueError:
            k = 24
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"images": [], "total": 0, "error": "unknown media_id"}), 404
        img_path = find_image_file(out_dir, media_id, row.get("filename"))
        if not img_path:
            return jsonify({"images": [], "total": 0, "error": "image file not found"}), 200
        try:
            import pixai_similar
            hits = pixai_similar.similar(str(img_path), k=k, exclude_media_id=media_id)
        except Exception as e:
            return jsonify({"images": [], "total": 0,
                            "error": "similarity index unavailable: " + str(e)[:180]}), 200
        telem_bump("similar_uses", out_dir=out_dir)       # Kindred Spirits
        out = []
        for mid, score in hits:
            r = get_row(db_path, mid)
            if not r:
                continue        # the sidecar index can drift from later catalog deletes
            isv = str(r.get("is_video") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "thumb": "/thumbs/{}.jpg".format(mid), "score": round(float(score), 3),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000]})
        return jsonify({"images": out, "total": len(out), "query": str(media_id)})

    @app.route("/api/collections")
    def api_collections():
        """Collection names for the picker/filter dropdowns. Read-only, local catalog."""
        return jsonify({"collections": unique_collections(db_path)})

    @app.route("/branding/<path:fname>")
    def branding(fname):
        """Serve drop-in branding art from out_dir/branding/ (banner.png, logo, icons).
        Absent files 404 so the header's onerror simply removes the <img>. Path-safe."""
        from flask import send_from_directory, abort
        bdir = (out_dir / "branding").resolve()
        try:
            target = (bdir / fname).resolve()
            target.relative_to(bdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        if not target.is_file():
            abort(404)
        resp = send_from_directory(str(bdir), fname)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"   # branding art gets re-cut; never serve a stale copy
        return resp

    @app.route("/badge-thumb/<aid>.png")
    def badge_thumb(aid):
        """Cached ~256px badge for the Trophy Hall tiles (masters stay the source of
        truth). Lazily generated on first hit; path-safe (no slashes via <aid>)."""
        from flask import send_from_directory, abort
        if not aid or "/" in aid or "\\" in aid or ".." in aid:
            abort(404)
        p = _badge_thumb(out_dir, aid)
        if not p or not Path(p).is_file():
            abort(404)
        p = Path(p)
        resp = send_from_directory(str(p.parent), p.name)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/contact-sheet")
    def contact_sheet():
        """Print-ready views for physical output. ?format=letter (grid, default) |
        photo (single 4x6) | strip (photo-booth: 2x2in strips on a 4x6, for the
        Sinfonia). Sources: ?ids=a,b,c or ?collection=<name>. ?cols / ?captions for
        the grid. Opens the print dialog on load."""
        ids_arg = (request.args.get("ids") or "").strip()
        collection = (request.args.get("collection") or "").strip()
        fmt = (request.args.get("format") or "letter").lower()
        if fmt not in ("letter", "photo", "strip"):
            fmt = "letter"
        try:
            cols = max(2, min(int(request.args.get("cols") or 4), 8))
        except ValueError:
            cols = 4
        captions = (request.args.get("captions") or "1") not in ("0", "false", "no")
        if ids_arg:
            ids = [x for x in ids_arg.split(",") if x.strip()]
            rows = rows_for_media_ids(db_path, ids)
            title = "{} selected".format(len(rows))
        elif collection:
            rows, _ = query_catalog(db_path, collection=collection, sort="newest",
                                    page=1, page_size=400)
            title = "Collection: {}".format(collection)
        else:
            rows, _ = query_catalog(db_path, sort="newest", page=1, page_size=60)
            title = "Recent"

        mids = [str(r.get("media_id")) for r in rows if r.get("media_id")]
        _autoprint = ("<script>window.addEventListener('load',function(){"
                      "setTimeout(function(){window.print();},350);});</script>")
        _bar = ("<div class='bar'><h1>{t}</h1><button onclick='window.print()'>"
                "\U0001f5a8 Print</button><a href='/' style='margin-left:auto'>"
                "&larr; gallery</a></div>")

        if fmt == "photo" and mids:
            return ("<!DOCTYPE html><html><head><meta charset='UTF-8'><title>4x6 photo</title>"
                    "<style>@page{size:4in 6in;margin:0}html,body{margin:0;height:100%;"
                    "background:#fff;font-family:system-ui,sans-serif}"
                    ".bar{display:flex;gap:12px;align-items:center;padding:10px}"
                    ".bar h1{font-size:15px;margin:0}"
                    ".photo{width:100%;height:100vh;display:flex;align-items:center;"
                    "justify-content:center;overflow:hidden}"
                    ".photo img{max-width:100%;max-height:100%;object-fit:contain}"
                    "@media print{.bar{display:none}}</style></head><body>"
                    + _bar.format(t="4&times;6 photo")
                    + "<div class='photo'><img src='/full/{}'></div>".format(mids[0])
                    + _autoprint + "</body></html>")

        if fmt == "strip" and mids:
            frames = [mids[i % len(mids)] for i in range(4)]
            frame_html = "".join(
                "<div class='frame'><img src='/full/{}'></div>".format(m) for m in frames)
            one = "<div class='strip'>" + frame_html + "</div>"
            return ("<!DOCTYPE html><html><head><meta charset='UTF-8'><title>Photo strip</title>"
                    "<style>@page{size:4in 6in;margin:0}html,body{margin:0;height:100%;"
                    "background:#fff;font-family:system-ui,sans-serif}"
                    ".bar{display:flex;gap:12px;align-items:center;padding:10px}"
                    ".bar h1{font-size:15px;margin:0}"
                    ".strips{display:flex;width:4in;height:6in}"
                    ".strip{width:2in;height:6in;display:flex;flex-direction:column;"
                    "padding:0.05in;box-sizing:border-box}"
                    ".strip:first-child{border-right:1px dashed #bbb}"
                    ".frame{flex:1;margin:0.03in 0;overflow:hidden}"
                    ".frame img{width:100%;height:100%;object-fit:cover;display:block}"
                    "@media print{.bar{display:none}}</style></head><body>"
                    + _bar.format(t="Photo-booth strip (cut in two)")
                    + "<div class='strips'>" + one + one + "</div>"
                    + _autoprint + "</body></html>")

        cells = []
        for r in rows:
            mid = str(r.get("media_id") or "")
            if not mid:
                continue
            cap = ""
            if captions:
                date = (r.get("created_at") or "")[:10]
                try:
                    stars = "★" * int(r.get("rating") or 0)
                except (TypeError, ValueError):
                    stars = ""
                cap = "<div class='cap'>{}{}</div>".format(
                    date, (" " + stars) if stars else "")
            cells.append(
                "<figure><img src='/thumbs/{}.jpg' alt=''>{}</figure>".format(mid, cap))
        html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Contact sheet &middot; {title}</title>
<style>
  @page {{ size: letter; margin: 12mm; }}
  body {{ font-family: system-ui, sans-serif; margin: 18px; color: #111; }}
  .bar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
  .bar h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  .bar button {{ font-size: 13px; padding: 6px 14px; cursor: pointer; }}
  .grid {{ display: grid; grid-template-columns: repeat({cols}, 1fr); gap: 8px; }}
  figure {{ margin: 0; break-inside: avoid; }}
  figure img {{ width: 100%; aspect-ratio: 1; object-fit: cover; border: 1px solid #ddd; border-radius: 4px; display: block; }}
  .cap {{ font-size: 9px; color: #555; margin-top: 2px; text-align: center; }}
  @media print {{ .bar {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<div class="bar"><h1>{title} &middot; {n} images</h1>
  <button onclick="window.print()">&#128424; Print</button>
  <a href="/" style="margin-left:auto;">&larr; back to gallery</a></div>
<div class="grid">{cells}</div>
<script>window.addEventListener('load', function(){{ setTimeout(function(){{ window.print(); }}, 350); }});</script>
</body></html>""".format(title=title, cols=cols, n=len(cells), cells="".join(cells))
        return html

    @app.route("/api/account")
    def api_account():
        """Credits + free-card balance for the header chip. Read-only, localhost-only.
        Fails soft to nulls so the header never breaks."""
        if not _is_local_request():
            return jsonify({}), 403
        try:
            core, session = _gen_session()
            me = core.account_info(session)
            try:
                credits = int(me.get("quotaAmount") or 0)
            except (TypeError, ValueError):
                credits = None
            cards = 0
            cards_by, expiries = [], []
            for k in core.list_kaisuukens(session):
                try:
                    n = int(k.get("count") or 0)
                except (TypeError, ValueError):
                    n = 0
                cards += n
                exp = (k.get("expires") or "")[:10]
                cards_by.append({"name": k.get("name"), "count": n, "expires": exp})
                if exp and n:
                    expiries.append(exp)
            card_expiry = min(expiries) if expiries else None
            # claimable daily rewards (free credits/stamina) -- for the "+N claim" badge
            claim_credits, claim_ids = 0, []
            for c in core.list_claims(session):
                if not c.get("canClaim"):
                    continue
                claim_ids.append(c.get("id"))
                if "credit" in str(c.get("id") or "").lower():
                    try:
                        claim_credits += int(c.get("amount") or 0)
                    except (TypeError, ValueError):
                        pass
            sub = me.get("subscription") or {}
            # Backup coverage: server's lifetime TASK count vs distinct tasks we hold locally.
            # Both are task counts (not images), so the ratio is honest.
            try:
                server_tasks = int((me.get("tasks") or {}).get("totalCount"))
            except (TypeError, ValueError):
                server_tasks = None
            local_tasks = distinct_task_count(db_path)
            coverage = (round(min(100.0, local_tasks / server_tasks * 100), 1)
                        if server_tasks else None)
            return jsonify({"credits": credits, "cards": cards,
                            "cards_by": cards_by, "card_expiry": card_expiry,
                            "claim_credits": claim_credits, "claim_ids": claim_ids,
                            "sub": {"end": (sub.get("endAt") or "")[:10],
                                    "cancel": bool(sub.get("cancelAtPeriodEnd"))},
                            "server_tasks": server_tasks, "local_tasks": local_tasks,
                            "coverage_pct": coverage,
                            "followers": me.get("followerCount"),
                            "following": me.get("followingCount")})
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 200

    @app.route("/api/claim", methods=["POST"])
    def api_claim():
        """Claim ready daily rewards (free credits/stamina to the owner's OWN account -- no
        money moves). Localhost-only; the header click IS the confirmation. One bad claim
        doesn't abort the rest. Returns {claimed, credits}."""
        if not _is_local_request():
            return jsonify({"error": "claiming is localhost-only"}), 403
        try:
            core, session = _gen_session()
            claimed, credits = 0, 0
            for c in core.list_claims(session):
                if not c.get("canClaim"):
                    continue
                try:
                    core.claim_reward(session, c.get("id"))
                    claimed += 1
                    if "credit" in str(c.get("id") or "").lower():
                        credits += int(c.get("amount") or 0)
                except Exception:                        # noqa: BLE001
                    pass
            if claimed:
                telem_bump("claims", claimed, out_dir=out_dir)   # Claimant
            return jsonify({"claimed": claimed, "credits": credits})
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 200

    _snips_lock = threading.Lock()

    @app.route("/api/snippets", methods=["GET", "POST"])
    def api_snippets():
        """Prompt snippets/favorites, stored server-side (out_dir/prompt_snippets.json) so
        they persist with the backup and sync across the owner's machines. Localhost-only."""
        if not _is_local_request():
            return jsonify({"snippets": []}), 403
        path = out_dir / "prompt_snippets.json"
        with _snips_lock:
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                snips = body.get("snippets")
                if not isinstance(snips, list):
                    return jsonify({"error": "snippets must be a list"}), 400
                clean = [str(s)[:800] for s in snips if str(s).strip()][:200]
                try:
                    path.write_text(json.dumps(clean), encoding="utf-8")
                except OSError as e:
                    return jsonify({"error": str(e)[:160]}), 200
                return jsonify({"snippets": clean})
            try:
                snips = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            except (OSError, ValueError):
                snips = []
            return jsonify({"snippets": snips})

    _ach_lock = threading.Lock()

    @app.route("/api/contests")
    def api_contests():
        """The live PixAI contest board (community + official). Read-only PUBLIC data (not
        owner-private, no spend), so NOT localhost-gated -- the owner browsing over LAN still
        sees it. ?all=1 includes ended contests; default is only the currently-running ones."""
        show_all = request.args.get("all") == "1"
        try:
            core, session = _gen_session()
            contests = core.list_contests(session, active_only=not show_all)
            return jsonify({"contests": contests,
                            "official": sum(1 for c in contests if c["type"] == "official"),
                            "community": sum(1 for c in contests if c["type"] != "official")})
        except Exception as e:
            return jsonify({"error": str(e)[:200], "contests": []}), 200

    @app.route("/api/artwork-views")
    def api_artwork_views():
        """Live view count for one published artwork -> the detail page's Views metric.
        Localhost-only (owner key). ?id=<artwork_id>."""
        if not _is_local_request():
            return jsonify({"views": None}), 403
        aid = (request.args.get("id") or "").strip()
        if not aid:
            return jsonify({"views": None}), 400
        try:
            core, session = _gen_session()
            return jsonify({"views": core.artwork_views(session, aid)})
        except Exception as e:
            return jsonify({"views": None, "error": str(e)[:120]}), 200

    @app.route("/api/your-art")
    def api_your_art():
        """'Your Art' panel: the owner's top published works ranked by likes (from the catalog,
        so it works over LAN) enriched with LIVE view counts (fetched per artwork_id, localhost
        only since that uses the owner key). Read-only, no spend."""
        top = top_published_rows(db_path, 12)
        totals = published_totals(db_path)
        views_synced = False
        if top and _is_local_request():
            try:
                core, session = _gen_session()
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=6) as ex:
                    vs = list(ex.map(lambda r: core.artwork_views(session, r["artwork_id"]), top))
                for r, v in zip(top, vs):
                    r["views"] = v
                top.sort(key=lambda r: (r.get("views") or 0, r.get("likes") or 0), reverse=True)
                totals["views_top"] = sum(vs)
                views_synced = True
            except Exception:
                pass
        return jsonify({"items": top, "totals": totals, "views_synced": views_synced})

    _telem_day = {"day": None}   # once-per-day throttle for the passive marks

    @app.route("/api/achievements")
    def api_achievements():
        """Milestone progress + skin unlocks, computed from local catalog stats +
        the persisted telemetry counters. Read-only catalog data (no spend, no
        network) so — like the picker — it's NOT localhost-gated; the owner browsing
        over LAN still sees their trophies. ?mark=1 records the currently newly-earned
        achievements as 'seen' so the unlock toast fires exactly once.

        Side effects (cheap, fail-soft): marks today in the Vigil day ledger, checks
        the Night Owl window, and sweeps the state-derived feat flags. Hidden feats
        that aren't earned go out MASKED (??? name, no roast) so devtools can't
        spoil them; the whole feat tab stays cloaked until the first feat lands."""
        import datetime as _dt
        try:
            today = _dt.date.today().isoformat()
            if _telem_day["day"] != today:
                _telem_day["day"] = today
                telem_mark_day(out_dir=out_dir)
                sweep_telemetry(out_dir)
            if 2 <= _dt.datetime.now().hour < 4:
                telem_flag("session_hour", out_dir=out_dir)
        except Exception:
            pass
        metrics = achievement_metrics(db_path)
        metrics.update(telemetry_metrics(out_dir))
        with _ach_lock:
            state = load_ach_state(out_dir)
            result = compute_achievements(metrics, state.get("seen"))
            newly = result["newly"]
            if request.args.get("mark") == "1":
                today = _dt.date.today().isoformat()
                ea = dict(state.get("earned_at") or {})
                # stamp every currently-earned achievement not yet dated: backfills the
                # pre-existing earns as "recognized today", records new ones going forward
                for a in result["achievements"]:
                    if a["earned"] and a["id"] not in ea:
                        ea[a["id"]] = today
                state["earned_at"] = ea
                if newly:
                    state["seen"] = sorted(set(state.get("seen") or []) | set(newly))
                save_ach_state(out_dir, state)
            earned_at = state.get("earned_at") or {}
        feats_revealed = any(
            a["earned"] for a in result["achievements"] if a["tier"] == "feat")
        unleashed = any(a["id"] == "triggered" and a["earned"]
                        for a in result["achievements"])
        masked_metrics, n_masked = set(), 0
        for a in result["achievements"]:
            if a["hidden"] and not a["earned"]:
                n_masked += 1
                masked_metrics.add(a["metric"])
                a.update(name="???", desc="A hidden feat of the Athenaeum.",
                         icon="❓", roast="", roast_nsfw="",
                         current=0, threshold=1, points=0,
                         id="hidden-feat-%d" % n_masked, metric="")
            if not a["earned"]:               # roasts are the reward, not a preview
                a["roast"] = ""
                a["roast_nsfw"] = ""
            elif not unleashed:               # uncensored lines stay locked until Triggered
                a["roast_nsfw"] = ""
        # a masked feat's metric name/value must not leak through the metrics echo
        still_visible = {a["metric"] for a in result["achievements"] if a.get("metric")}
        for k in masked_metrics - still_visible:
            metrics.pop(k, None)
        result["feats_revealed"] = feats_revealed
        result["unleash_available"] = unleashed
        result["skin"] = state.get("skin", "moonglade")
        result["earned_at"] = earned_at   # {id: iso-date}; only earned ids -> no hidden-feat leak
        result["metrics"] = metrics
        return jsonify(result)

    @app.route("/api/skin", methods=["POST"])
    def api_skin():
        """Set the active cosmetic skin. Only an *earned* skin may be applied (server checks
        against current unlocks), so a client can't force a locked palette. Persists to
        out_dir/achievements.json. Cosmetic + local-only, no spend."""
        body = request.get_json(silent=True) or {}
        skin = str(body.get("skin") or "").strip()
        if skin not in _SKIN_IDS:
            return jsonify({"error": "unknown skin"}), 400
        result = compute_achievements(achievement_metrics(db_path))
        earned = {s["id"] for s in result["skins"] if s["earned"]}
        if skin not in earned:
            return jsonify({"error": "skin locked", "skin": load_ach_state(out_dir)["skin"]}), 403
        with _ach_lock:
            state = load_ach_state(out_dir)
            changed = state.get("skin") != skin
            state["skin"] = skin
            save_ach_state(out_dir, state)
        if changed:                       # Interior Decorator: an explicit re-dress
            telem_bump("skin_changed_runs", out_dir=out_dir)
        return jsonify({"skin": skin})

    @app.route("/api/ach-event", methods=["POST"])
    def api_ach_event():
        """Feat-event beacon from the front-end: the Starfall konami egg, the
        in-app manual, and narrator pokes. Whitelisted event names only; each is
        a cosmetic local counter (no spend), same trust level as /api/skin."""
        body = request.get_json(silent=True) or {}
        ev = str(body.get("event") or "").strip()
        if ev == "konami":
            telem_flag("konami_triggered", out_dir=out_dir)
            return jsonify({"ok": True})
        if ev == "docs":
            telem_bump("docs_opened", out_dir=out_dir)
            return jsonify({"ok": True})
        if ev == "narrator":
            telem_bump("narrator_pokes", out_dir=out_dir)
            pokes = telemetry_metrics(out_dir).get("narrator_pokes", 0)
            return jsonify({"ok": True, "pokes": pokes, "snapped": pokes >= 5})
        return jsonify({"error": "unknown event"}), 400

    @app.route("/api/branding", methods=["GET", "POST"])
    def api_branding():
        """The banner mark (the icon beside the title) + its animation. GET is
        open (cosmetic; the LAN view renders the same header); POST is owner-only.
        Persists to out_dir/branding.json."""
        if request.method == "GET":
            cfg = load_branding(out_dir)
            return jsonify({"mark": cfg["mark"], "anim": cfg["anim"],
                            "anims": MARK_ANIMS, "marks": list_marks(out_dir)})
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        cfg = load_branding(out_dir)
        have = {m["id"] for m in list_marks(out_dir)}
        if "anim" in body:
            anim = str(body["anim"])
            if anim not in MARK_ANIMS:
                return jsonify({"error": "unknown animation"}), 400
            cfg["anim"] = anim
        if "mark" in body:
            mark = str(body["mark"])
            if mark != "logo" and mark not in have:
                return jsonify({"error": "unknown mark"}), 400
            cfg["mark"] = mark
        save_branding(out_dir, cfg)
        if "mark" in body or "anim" in body:   # Interior Decorator: dressing the halls
            telem_bump("skin_changed_runs", out_dir=out_dir)
        if cfg["anim"] == "eclipse":           # Eclipse: sun and moon in balance
            telem_flag("eclipse_anim_triggered", out_dir=out_dir)
        return jsonify({"mark": cfg["mark"], "anim": cfg["anim"]})

    @app.route("/api/branding/shortcut", methods=["POST"])
    def api_branding_shortcut():
        """Write/refresh the Desktop launcher shortcut with the chosen mark's
        .ico. A .pyw can't carry an icon; the .lnk can -- this IS the app icon.
        Machine-local action -> owner-only."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        mark = str(body.get("mark") or load_branding(out_dir)["mark"])
        # Whitelist before anything touches the shell: only a known cut mark id
        # may become an icon path (no traversal, no quoting surprises).
        if mark not in {m["id"] for m in list_marks(out_dir)}:
            return jsonify({"error": "unknown mark (no .ico cut for it)"}), 400
        try:
            lnk = make_launcher_shortcut(out_dir, mark)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "lnk": lnk})

    @app.route("/api/suggest-prompt")
    def api_suggest_prompt():
        """Image-to-prompt for the gallery's 'Suggest prompt' button: PixAI's tag list +
        NL description for a media_id. Read-only, free, localhost-only. ?media_id="""
        if not _is_local_request():
            return jsonify({"suggestions": []}), 403
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"suggestions": [], "error": "media_id required"}), 400
        try:
            core, session = _gen_session()
            return jsonify({"suggestions": core.suggest_prompt(session, mid)})
        except Exception as e:
            return jsonify({"suggestions": [], "error": str(e)[:200]}), 200

    @app.route("/api/tag-suggest")
    def api_tag_suggest():
        """Tag autocomplete for the drawer's prompt boxes (the site's Tag Suggestions
        dropdown). Read-only, free, localhost-only. ?q=<prefix>."""
        if not _is_local_request():
            return jsonify({"tags": []}), 403
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"tags": []})
        try:
            core, session = _gen_session()
            return jsonify({"tags": core.tag_search_gql(session, q, first=8)})
        except Exception as e:
            return jsonify({"tags": [], "error": str(e)[:200]}), 200

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        """Upload a local file from the picker -> PixAI media_id (the same free
        3-step S3 handshake as the CLI's --upload). Owner-only: localhost-gated,
        spends nothing."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        import os as _os
        import tempfile
        suffix = _os.path.splitext(f.filename)[1][:8] or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            f.save(tmp)
            tmp.close()
            core, session = _gen_session()
            mid = core.upload_media(session, tmp.name)
            telem_bump("uploads", out_dir=out_dir)        # first-upload milestone
            return jsonify({"media_id": str(mid)})
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 200
        finally:
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

    def _gen_args_from_payload(p):
        """Turn the Generate drawer's JSON into the SAME argparse-like namespace the CLI
        feeds to core._gen_parameters -- so web + CLI build identical params (one source
        of truth). Clamped to safe ranges."""
        from types import SimpleNamespace
        p = p or {}
        def num(k, d, cast=int):
            try:
                return cast(p.get(k, d))
            except (TypeError, ValueError):
                return d
        loras = []
        for lo in (p.get("loras") or []):
            vid = str((lo or {}).get("version_id") or "").strip()
            if vid:
                loras.append((vid, (lo or {}).get("weight", 0.7)))
        seed_raw = str(p.get("seed") or "").strip()
        hp = p.get("high_priority") in (True, "1", "true", "on")
        return SimpleNamespace(
            params_json="", prompt=(p.get("prompt") or "").strip(),
            negative=(p.get("negative") or "").strip(),
            model=(p.get("version_id") or "").strip(),
            width=num("width", 512), height=num("height", 512),
            steps=num("steps", 25), cfg=num("cfg", 7, float),
            count=max(1, min(num("count", 1), 4)),
            priority=(1000 if hp else 500), mode=(p.get("mode") or "auto"),
            seed=(int(seed_raw) if seed_raw.lstrip("-").isdigit() else None),
            lora=loras,
            prompt_helper=(str(p.get("prompt_helper", "1")) not in ("0", "false", "off")),
            ref_media_id=str(p.get("ref_media_id") or "").strip(),
            ref_strength=num("ref_strength", 0.55, float),
            kaisuuken_id="", no_card=bool(p.get("no_card")))

    _presets_lock = threading.Lock()

    def _presets_path():
        return out_dir / "toolbox_presets.json"

    def _load_presets():
        try:
            if _presets_path().exists():
                return json.loads(_presets_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {}

    def _edit_params_from_payload(core, p):
        """Build the instruct-edit `chat` params from the Edit tab's JSON. Source is a
        catalog media_id (the image being edited). A `preset` name swaps in a locally
        banked Toolbox preset (canned prompt + sceneId + its modelId). Returns None if
        no source."""
        p = p or {}
        src = str(p.get("source") or "").strip()
        if not src:
            return None
        instruction = (p.get("instruction") or "").strip()
        scene_id, model_id = "", ""
        preset_name = str(p.get("preset") or "").strip()
        if preset_name:
            pre = _load_presets().get(preset_name)
            if not pre:
                return None
            instruction = pre.get("prompt") or instruction
            scene_id = pre.get("scene_id") or ""
            model_id = pre.get("model_id") or ""
        # A preset pins its own model; otherwise resolve from the Edit-card model picker.
        if not model_id:
            model_id = core.edit_model_id(p.get("edit_model") or "") or core.EDIT_PRO_MODEL_ID
        # quality: omitted (passed "") for models with no quality option (Reference Pro);
        # default medium only when the client sent no quality key at all.
        q = p.get("quality")
        if q is None:
            q = "medium"
        res, q, asp = core.clamp_edit_config(model_id, (p.get("resolution") or "1K"), q,
                                             (p.get("aspect") or "3:4"))   # never send an invalid knob
        kwargs = dict(resolution=res, aspect_ratio=asp, quality=q, scene_id=scene_id, model_id=model_id)
        # multi-image: sources[] (primary + extra refs) if the client sent them, else [source];
        # capped to the model's reference limit (Edit Pro 4 / Reference Pro 10).
        media = p.get("sources")
        media = [str(m).strip() for m in media if str(m).strip()] if isinstance(media, list) else []
        if not media:
            media = [src]
        spec = core.edit_model_by_id(model_id)
        if spec:
            media = media[:spec["max_refs"]] or [src]
        return core.build_chat_edit_parameters(instruction, media, **kwargs)

    @app.route("/api/presets", methods=["GET", "POST"])
    def api_presets():
        """Toolbox presets, stored LOCALLY (out_dir/toolbox_presets.json -- preset
        prompts are PixAI-authored content, so they live as the owner's own captured
        task data, never in the repo). GET lists {name: {label, scene_id}} (no prompt
        bodies). POST {task_id, label?} imports one from a task the owner ran on the
        site: fetches the task, extracts chat.prompts + sceneId + modelId, saves it.
        Localhost-only (uses the owner's key on import)."""
        if not _is_local_request():
            return jsonify({"presets": {}}), 403
        with _presets_lock:
            presets = _load_presets()
            if request.method == "GET":
                return jsonify({"presets": {
                    k: {"label": v.get("label") or k, "scene_id": v.get("scene_id", "")}
                    for k, v in presets.items()}})
            body = request.get_json(silent=True) or {}
            tid = str(body.get("task_id") or "").strip()
            if not tid:
                return jsonify({"error": "task_id required"}), 400
            try:
                core, session = _gen_session()
                task = core.task_detail_gql(session, tid) or {}
                params = task.get("parameters") or {}
                chat = params.get("chat") or {}
                prompt = chat.get("prompts") or params.get("prompts") or ""
                scene = str(params.get("sceneId") or "").strip()
                if not prompt:
                    return jsonify({"error": "task has no prompt to bank"}), 200
                name = scene or ("preset-" + tid[-6:])
                presets[name] = {
                    "label": (body.get("label") or "").strip()
                             or scene.replace("-", " ").title() or name,
                    "scene_id": scene,
                    "prompt": prompt,
                    "model_id": str(chat.get("modelId") or ""),
                    "from_task": tid,
                }
                _presets_path().write_text(json.dumps(presets, indent=1),
                                           encoding="utf-8")
                return jsonify({"imported": name,
                                "label": presets[name]["label"]})
            except Exception as e:
                return jsonify({"error": str(e)[:200]}), 200

    def _params_and_nocard(core, p):
        """Route a drawer payload to generate, edit, or video params. Returns (params,
        no_card, note). note is set (params None) when something's missing."""
        p = p or {}
        if p.get("mode") == "edit":
            params = _edit_params_from_payload(core, p)
            return (params, bool(p.get("no_card")),
                    None if params else "pick an image to edit")
        if p.get("mode") in ("I2V", "FLF", "R2V"):
            imgs = [str(i) for i in (p.get("images") or []) if str(i).strip()]
            if not imgs:
                return None, bool(p.get("no_card")), "pick a source image"
            try:
                params = core.build_shot_video_params(
                    p["mode"], (p.get("prompt") or "").strip(), image_ids=imgs,
                    duration=p.get("duration") or 5,
                    generate_audio=bool(p.get("audio")),
                    model=(p.get("video_model") or ""),
                    camera_movement=(p.get("camera_movement") or ""),
                    quality=(p.get("quality") or "professional"),
                    audio_language=(p.get("audio_language") or "english"))
            except core.PixAIError as e:
                return None, bool(p.get("no_card")), str(e)[:140]
            return params, bool(p.get("no_card")), None
        if p.get("mode") == "enhance":
            src = str(p.get("source") or "").strip()
            wid = str(p.get("workflow_id") or "").strip()
            if not (src and wid):
                return None, bool(p.get("no_card")), "pick an image + a tool"
            try:
                return core.build_panelplugin_parameters(src, wid), bool(p.get("no_card")), None
            except Exception:                        # noqa: BLE001
                return None, bool(p.get("no_card")), "could not build that workflow"
        args = _gen_args_from_payload(p)
        if not args.model:
            return None, args.no_card, "pick a model"
        return core._gen_parameters(args), args.no_card, None

    @app.route("/api/price", methods=["POST"])
    def api_price():
        """Live cost + free-card check for the drawer's current settings (generate OR
        edit). Read-only (no spend). Localhost-only."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only", "cost": None}), 403
        try:
            core, session = _gen_session()
            params, no_card, note = _params_and_nocard(core, request.get_json(silent=True) or {})
            if params is None:
                return jsonify({"cost": None, "free": False, "note": note})
            cost = core.price_task(session, params)
            best = None if no_card else core.match_kaisuuken(session, params, enrich=True)
            return jsonify({"cost": cost, "free": bool(best),
                            "cards": (best or {}).get("total"),
                            "card_name": (best or {}).get("name"),
                            "card_expires": (best or {}).get("expiresAt")})
        except Exception as e:
            return jsonify({"error": str(e)[:200], "cost": None}), 200

    @app.route("/api/generate", methods=["POST"])
    def api_generate():
        """Submit a generation from the drawer, wait, and catalog it into THIS gallery's
        backup. Localhost-only (spends the owner's credits/cards). A matching free card is
        auto-applied unless no_card is set. Returns {task_id, media_ids, paid_credit}."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        try:
            core, session = _gen_session()
            body = request.get_json(silent=True) or {}
            args = _gen_args_from_payload(body)
            # Authoritative model resolution: if the drawer sent the base model_id, re-resolve
            # the CURRENT version server-side and IGNORE the client's cached version_id (which
            # can be stale/raced). This is what stops gens landing as "Unknown model" + missing
            # the feed. Falls back to the client version_id when no model_id was sent.
            _mid = str(body.get("model_id") or "").strip()
            if _mid:
                _vid = (core.resolve_version_meta(session, _mid) or {}).get("version_id") or ""
                if _vid:
                    args.model = _vid
            if not args.model:
                return jsonify({"error": "pick a model first"}), 400
            if not args.prompt:
                return jsonify({"error": "enter a prompt"}), 400
            params = core._gen_parameters(args)
            core._apply_kaisuuken(session, params, args)   # attach free card unless no_card
            task_id = core.submit_generation(session, params)
            try:                       # LoRA telemetry (First Lora / Stacked Deck / Polyglot)
                lvids = [str((lo or {}).get("version_id") or "").strip()
                         for lo in (body.get("loras") or [])]
                lvids = [v for v in lvids if v]
                if lvids:
                    telem_bump("lora_used", out_dir=out_dir)
                    telem_max("lora_stacked", len(lvids), out_dir=out_dir)
                    for v in lvids:
                        telem_set_add("loras", v, out_dir=out_dir)
            except Exception:
                pass
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 200

    @app.route("/api/edit", methods=["POST"])
    def api_edit():
        """Instruct-edit an existing gallery image ('make it night'). Localhost-gated;
        auto-applies an Edit-Pro card unless no_card. Catalogs the result into this
        backup, same as /api/generate. Returns {task_id, media_ids, paid_credit}."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        try:
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            params = _edit_params_from_payload(core, p)
            if params is None:
                return jsonify({"error": "pick an image to edit (and a valid preset if set)"}), 400
            if not (p.get("preset") or "").strip() and not (p.get("instruction") or "").strip():
                return jsonify({"error": "describe the edit"}), 400
            core._apply_kaisuuken(session, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(session, params)
            telem_bump("edits", out_dir=out_dir)          # The Restoration Wing
            telem_set_add("tools", "edit", out_dir=out_dir)
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 200

    @app.route("/api/enhance", methods=["POST"])
    def api_enhance():
        """One-click enhance (panelplugin) on the Edit tab's source image. Localhost-gated;
        auto-applies a card if one matches. A rejected/unknown workflow just errors (no
        credits spent). Returns {task_id, media_ids, paid_credit}."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        try:
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            src = str(p.get("source") or "").strip()
            wid = str(p.get("workflow_id") or "").strip()
            plug = ENHANCE_PLUGINS.get(str(p.get("plugin") or "").strip())
            if not src:
                return jsonify({"error": "pick an image first"}), 400
            if wid:
                params = core.build_panelplugin_parameters(src, wid)
            elif plug:
                params = core.build_panelplugin_parameters(
                    src, plug.get("workflow_id", ""), workflow_name=plug.get("workflow_name", ""))
            else:
                return jsonify({"error": "pick an enhance workflow"}), 400
            core._apply_kaisuuken(session, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(session, params)
            telem_bump("enhances", out_dir=out_dir)       # first-enhance milestone
            telem_set_add("tools", "enhance", out_dir=out_dir)
            telem_set_add("enhance_workflows",           # Enhance Adept: distinct rituals
                          wid or (plug or {}).get("workflow_id")     # card + catalog runs of the
                          or (plug or {}).get("workflow_name")       # same workflow share one key
                          or str(p.get("plugin") or ""), out_dir=out_dir)
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 200

    @app.route("/api/fix", methods=["POST"])
    def api_fix():
        """Submit a hand/face fixer task from the Edit-tab canvas. `boxes` are original-image
        pixel coords. Localhost-gated; returns {task_id} for the async poller."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        try:
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            src = str(p.get("source") or "").strip()
            boxes = p.get("boxes") or []
            if not src:
                return jsonify({"error": "pick an image first"}), 400
            if not boxes:
                return jsonify({"error": "draw a box over a hand or face"}), 400
            task_id = core.submit_fixer(session, src, boxes)
            telem_set_add("tools", "fix", out_dir=out_dir)   # Full Toolbox
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 200

    # --- The Loom (Seedance storyboard) -------------------------------------
    _loom_lock = threading.Lock()

    def _loom_store():
        d = out_dir / "loom"
        d.mkdir(parents=True, exist_ok=True)
        return d / "store.json"

    def _loom_load():
        p = _loom_store()
        if p.exists():
            try:
                import json as _j
                return _j.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return {}
        return {}

    def _loom_save(data):
        import json as _j
        _loom_store().write_text(_j.dumps(data), encoding="utf-8")

    @app.route("/loom/vendor/<path:fname>")
    def loom_vendor(fname):
        """Serve the Loom's vendored JS (React/ReactDOM/Babel UMD builds) from
        loom/vendor/ so the page paints with zero network calls. Path-safe; absent
        files 404. Not gated by _is_local_request -- these are static library files,
        not gallery data, and /loom itself already enforces localhost-only above."""
        from flask import send_from_directory, abort
        vdir = (Path(__file__).resolve().parent / "loom" / "vendor").resolve()
        try:
            target = (vdir / fname).resolve()
            target.relative_to(vdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(str(vdir), fname, max_age=31536000)

    @app.route("/loom")
    def loom():
        """Serve the Seedance video-storyboard tool inside the gallery, persisted to the
        backend (window.storage swapped for /api/loom/*). Localhost-only."""
        if not _is_local_request():
            return "The Loom is localhost-only.", 403
        import re as _re
        src = Path(__file__).resolve().parent / "loom" / "master-storyboard.jsx"
        try:
            jsx = src.read_text(encoding="utf-8")
        except OSError:
            return "Loom source not found (loom/master-storyboard.jsx).", 404
        jsx = _re.sub(r"(?m)^\s*import\s+React.*$", "", jsx)          # React is a CDN global
        jsx = jsx.replace("export default function App()", "function App()")
        return LOOM_PAGE.replace("__JSX__", jsx)

    @app.route("/api/loom/get")
    def loom_get():
        if not _is_local_request():
            return jsonify({"value": None}), 403
        with _loom_lock:
            return jsonify({"value": _loom_load().get(request.args.get("key") or "")})

    @app.route("/api/loom/set", methods=["POST"])
    def loom_set():
        if not _is_local_request():
            return jsonify({"ok": False}), 403
        p = request.get_json(silent=True) or {}
        k = p.get("key")
        if not k:
            return jsonify({"ok": False}), 400
        with _loom_lock:
            data = _loom_load()
            data[k] = p.get("value")
            _loom_save(data)
        return jsonify({"ok": True})

    @app.route("/api/loom/list")
    def loom_list():
        if not _is_local_request():
            return jsonify({"keys": []}), 403
        pre = request.args.get("prefix") or ""
        with _loom_lock:
            keys = [k for k in _loom_load().keys() if k.startswith(pre)]
        return jsonify({"keys": keys})

    @app.route("/api/loom/delete", methods=["POST"])
    def loom_delete():
        if not _is_local_request():
            return jsonify({"ok": False}), 403
        k = (request.get_json(silent=True) or {}).get("key")
        with _loom_lock:
            data = _loom_load()
            if k in data:
                del data[k]
                _loom_save(data)
        return jsonify({"ok": True})

    @app.route("/api/loom/handoff", methods=["POST"])
    def loom_handoff():
        """Frame handoff: given a generated shot's video media_id, extract its LAST frame,
        upload it, and return the new frame media_id -- which the storyboard sets as the
        next shot's opening frame, chaining clips into one continuous scene. The clip must
        already be downloaded locally (it is, right after Generate-shot cataloged it).
        Localhost-only; the upload is free."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        mid = str(body.get("video_media_id") or "").strip()
        if not mid:
            return jsonify({"error": "video_media_id required"}), 400
        try:
            core, session = _gen_session()
            vid_exts = (".mp4", ".webm", ".mov", ".mkv")
            vid = None
            # videos aren't in find_files_for_media_id (image-only) -- resolve via the
            # catalog's stored filename, then fall back to a video-aware disk scan.
            row = get_row(db_path, mid) or {}
            fn = row.get("filename") or ""
            if fn:
                cand = out_dir / fn
                if cand.is_file() and cand.suffix.lower() in vid_exts:
                    vid = cand
            if vid is None:
                for p in out_dir.rglob("*{}.*".format(mid)):
                    if p.suffix.lower() in vid_exts and p.is_file() and p.stat().st_size:
                        vid = p
                        break
            if vid is None:
                return jsonify({"error": "clip not downloaded yet -- generate/collect it first"}), 200
            fdir = out_dir / "loom" / "_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            png = fdir / (mid + "_last.png")
            if not core.extract_last_frame(str(vid), str(png)):
                return jsonify({"error": "could not extract the last frame (ffmpeg)"}), 200
            frame_mid = core.upload_media(session, str(png))
            dur = core.probe_video_duration(str(vid))
            return jsonify({"frame_media_id": str(frame_mid), "duration": dur})
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 200

    @app.route("/api/loom/generate", methods=["POST"])
    def loom_generate():
        """Generate a storyboard SHOT on PixAI (the video 'Copy shot' -> 'Generate shot').
        Resolves the shot's @-ordered images (upload data-URLs / pass media_ids) -> the PixAI
        video provider adapter -> card auto-apply (V4.0 = free) -> async submit. Localhost."""
        if not _is_local_request():
            return jsonify({"error": "generation is localhost-only"}), 403
        try:
            import base64
            import hashlib
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            updir = out_dir / "loom" / "_uploads"
            updir.mkdir(parents=True, exist_ok=True)

            def resolve_img(val):
                s = str(val or "").strip()
                if not s:
                    return ""
                if s.isdigit():                       # already a PixAI media_id
                    return s
                if s.startswith("data:"):             # a Loom thumbnail -> upload it
                    try:
                        head, b64 = s.split(",", 1)
                        raw = base64.b64decode(b64)
                    except Exception:
                        return ""
                    ext = ".png" if "png" in head[:24] else ".jpg"
                    fp = updir / (hashlib.sha1(raw).hexdigest()[:16] + ext)
                    if not fp.exists():
                        fp.write_bytes(raw)
                    return core.upload_media(session, str(fp))
                return ""                             # a bare filename/URL we can't fetch

            image_ids = [m for m in (resolve_img(x) for x in (p.get("images") or [])) if m]
            video_ids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip().isdigit()]
            audio_ids = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip().isdigit()]
            params = core.build_shot_video_params(
                p.get("mode") or "R2V", (p.get("prompt") or "").strip(),
                image_ids=image_ids, video_ids=video_ids, audio_ids=audio_ids,
                duration=p.get("duration") or 5,
                generate_audio=bool(p.get("generate_audio") or p.get("audio")),
                model=(p.get("video_model") or ""),
                camera_movement=(p.get("camera_movement") or ""),
                quality=(p.get("quality") or "professional"),
                audio_language=(p.get("audio_language") or "english"))
            core._apply_kaisuuken(session, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(session, params)
            try:                       # Master of the Loom + Storyweaver telemetry
                mode = str(p.get("mode") or "R2V").upper()
                if mode in ("I2V", "FLF", "R2V"):
                    telem_set_add("video_modes", mode.lower(), out_dir=out_dir)
                if str(p.get("origin") or "") == "loom-shot":
                    telem_bump("storyboards", out_dir=out_dir)
            except Exception:
                pass
            return jsonify({"task_id": task_id, "uploaded": len(image_ids)})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 200

    def _run_export(cmd, out_path, total_sec):
        """Run the ffmpeg concat in a thread, parsing time= for progress. The output
        (--pix_fmt yuv420p h264) is a normal mp4 the browser can play + download."""
        import subprocess, re as _re
        tpat = _re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    text=True, bufsize=1, encoding="utf-8", errors="replace")
            with _export_lock:
                _export_job["proc"] = proc
            for line in iter(proc.stderr.readline, ""):
                m = tpat.search(line)
                if m:
                    el = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    with _export_lock:
                        _export_job["elapsed"] = round(el, 1)
                        _export_job["progress"] = min(99, int(el / total_sec * 100)) if total_sec else 0
            rc = proc.wait()
            with _export_lock:
                _export_job["proc"] = None
                if _export_job.get("cancelled"):
                    _export_job["status"] = "cancelled"
                elif rc == 0 and out_path.exists():
                    _export_job.update(status="done", progress=100, out=out_path.name)
                else:
                    _export_job.update(status="failed", error="ffmpeg exited %d" % rc)
        except Exception as e:
            with _export_lock:
                _export_job.update(status="failed", error=str(e)[:200], proc=None)

    @app.route("/api/loom/export", methods=["POST"])
    def api_loom_export():
        """Trim each finished shot to its in/out and concat into one 720p mp4 -- the
        rough cut becomes a real deliverable. Async (ffmpeg in a thread); poll
        /api/loom/export-status, download /api/loom/export-file. Localhost-only.
        Video-only for now (audio is a follow-up). body: {clips:[{mid,in,out}], total_seconds}"""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        import shutil
        if not shutil.which("ffmpeg"):
            return jsonify({"error": "ffmpeg is not on PATH -- install it to export."}), 400
        with _export_lock:
            if _export_job["status"] == "running":
                return jsonify({"error": "an export is already running"}), 409
        body = request.get_json(silent=True) or {}
        try:
            total_sec = float(body.get("total_seconds") or 0) or 1.0
        except (TypeError, ValueError):
            total_sec = 1.0
        segs = []
        for c in (body.get("clips") or []):
            mid = str(c.get("mid") or "")
            if not mid:
                continue
            # Resolve the shot's video the same way /video-file does: catalog row ->
            # filename (find_files_for_media_id is image-only, so it never sees mp4s).
            row = get_row(db_path, mid)
            if not row or str(row.get("is_video") or "") != "1" or not row.get("filename"):
                continue
            path = str(out_dir / row["filename"])
            if not os.path.exists(path):
                continue
            try:
                ci = max(0.0, float(c.get("in") or 0))
            except (TypeError, ValueError):
                ci = 0.0
            co = c.get("out")
            try:
                co = float(co) if co not in (None, "") else None
            except (TypeError, ValueError):
                co = None
            segs.append((path, ci, co))
        if not segs:
            return jsonify({"error": "no finished shot videos found on disk to export"}), 400
        _export_dir.mkdir(parents=True, exist_ok=True)
        out_path = _export_dir / "loom_cut.mp4"
        W, H = 1280, 720
        parts, labels = [], ""
        for i, (path, ci, co) in enumerate(segs):
            tr = "trim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
            parts.append("[%d:v]%s,setpts=PTS-STARTPTS,scale=%d:%d:force_original_aspect_ratio=decrease,"
                         "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v%d]" % (i, tr, W, H, W, H, i))
            labels += "[v%d]" % i
        fc = ";".join(parts) + ";" + labels + "concat=n=%d:v=1:a=0[vout]" % len(segs)
        cmd = ["ffmpeg", "-y"]
        for (path, _ci, _co) in segs:
            cmd += ["-i", path]
        cmd += ["-filter_complex", fc, "-map", "[vout]", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)]
        with _export_lock:
            _export_job.update(status="running", progress=0, elapsed=0.0, out="",
                               error="", proc=None, cancelled=False)
        threading.Thread(target=_run_export, args=(cmd, out_path, total_sec), daemon=True).start()
        return jsonify({"ok": True, "shots": len(segs)})

    @app.route("/api/loom/export-status")
    def api_loom_export_status():
        with _export_lock:
            return jsonify({k: _export_job[k] for k in
                            ("status", "progress", "elapsed", "out", "error")})

    @app.route("/api/loom/export-file")
    def api_loom_export_file():
        name = _export_job.get("out") or "loom_cut.mp4"
        if not (_export_dir / name).exists():
            return "No export available.", 404
        return send_from_directory(str(_export_dir), name, as_attachment=True,
                                   download_name="moonglade-loom-cut.mp4")

    @app.route("/api/loom/export-cancel", methods=["POST"])
    def api_loom_export_cancel():
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        with _export_lock:
            proc = _export_job.get("proc")
            if _export_job["status"] == "running" and proc is not None:
                _export_job["cancelled"] = True
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        return jsonify({"ok": True})

    @app.route("/api/task-status")
    def api_task_status():
        """Poll a submitted task: {phase: running|done|failed}. On 'done' it downloads +
        catalogs the result into this backup and returns media_ids + paid_credit. Read-only
        until done; localhost-only."""
        if not _is_local_request():
            return jsonify({"phase": "failed", "error": "localhost-only"}), 403
        tid = (request.args.get("task_id") or "").strip()
        if not tid:
            return jsonify({"phase": "failed", "error": "task_id required"}), 400
        try:
            core, session = _gen_session()
            st = core.generation_status(session, tid)
            if st["phase"] == "done":
                got = core.collect_generation(session, tid, str(out_dir))
                # authoritative done event -- written server-side so the Jobs card gets the
                # outcome even if the browser tab that submitted it has since closed.
                _log_job(tid, status="done", media_ids=got["media_ids"],
                         is_video=got.get("is_video", False))
                return jsonify({"phase": "done", "media_ids": got["media_ids"],
                                "is_video": got.get("is_video", False),
                                "duration": got.get("duration"),
                                "paid_credit": st["paid_credit"]})
            if st["phase"] == "failed":
                _log_job(tid, status="failed", error=(st.get("status") or "failed"))
                return jsonify({"phase": "failed", "status": st["status"]})
            return jsonify({"phase": "running", "status": st["status"]})
        except Exception as e:
            # A transient PixAI blip (5xx/429/timeout) raises here even though the task may
            # still be running -- or already finished. Do NOT write an authoritative 'failed'
            # job event: that would brick the card with a sticky false failure + a red toast
            # for a task that likely succeeded. Leave the job at its last-known state (it ages
            # out, or the live-mirror watcher collects the real result). Only a genuine
            # st["phase"] == "failed" above logs a terminal failure.
            return jsonify({"phase": "failed", "error": str(e)[:200]}), 200

    @app.route("/api/jobs")
    def api_jobs():
        """Reconstructed job list for the Jobs card (newest-first) -- the paper trail that
        survives a reload. The card polls this. Localhost-only, like the creation suite."""
        if not _is_local_request():
            return jsonify({"jobs": []}), 403
        import pixai_gallery_backup as core
        try:
            jobs = core.read_jobs(out_dir)
            core.maybe_compact_jobs(out_dir)   # keep the append-only log bounded
        except Exception:
            jobs = []
        return jsonify({"jobs": jobs})

    @app.route("/api/jobs", methods=["POST"])
    def api_jobs_register():
        """Register/update a job in the log. The Jobs card calls this the moment a gen is
        submitted (status=running) so it shows immediately; the authoritative done/failed
        events are written server-side by /api/task-status. Localhost-only."""
        if not _is_local_request():
            return jsonify({"ok": False}), 403
        body = request.get_json(silent=True) or {}
        jid = str(body.get("job_id") or "").strip()
        if not jid:
            return jsonify({"ok": False, "error": "job_id required"}), 400
        _log_job(jid, status=(body.get("status") or "running"),
                 type=body.get("type"), label=body.get("label"),
                 done=body.get("done"), total=body.get("total"),
                 source=body.get("source") or "web")
        return jsonify({"ok": True})

    @app.route("/api/jobs/dismiss", methods=["POST"])
    def api_jobs_dismiss():
        """Dismiss one job (job_id) or every finished job (finished:true) from the card --
        this is how a sticky failure gets cleared. Localhost-only."""
        if not _is_local_request():
            return jsonify({"ok": False}), 403
        import pixai_gallery_backup as core
        body = request.get_json(silent=True) or {}
        if body.get("finished"):
            try:
                for j in core.read_jobs(out_dir):
                    if j.get("status") in ("done", "failed"):
                        _log_job(j.get("job_id"), dismissed=True)
            except Exception:
                pass
        else:
            jid = str(body.get("job_id") or "").strip()
            if not jid:
                return jsonify({"ok": False, "error": "job_id required"}), 400
            _log_job(jid, dismissed=True)
        return jsonify({"ok": True})

    @app.route("/api/workflows")
    def api_workflows():
        """Live enhance-workflow catalog (id + name + type) for the Edit tab picker.
        Read-only; localhost-only (owner key)."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only", "workflows": []}), 403
        try:
            core, session = _gen_session()
            return jsonify({"workflows": core.workflow_catalog(session)})
        except Exception as e:
            return jsonify({"error": str(e)[:200], "workflows": []}), 200

    @app.after_request
    def _gzip_html(resp):
        # Compress only HTML pages (the big card grids). File responses are
        # direct_passthrough streams and are left untouched.
        try:
            if (resp.status_code == 200 and not resp.direct_passthrough
                    and resp.content_type and resp.content_type.startswith("text/html")
                    and "gzip" in request.headers.get("Accept-Encoding", "")):
                data = resp.get_data()
                if len(data) > 1024:
                    import gzip as _gzip
                    packed = _gzip.compress(data, 6)
                    resp.set_data(packed)
                    resp.headers["Content-Encoding"] = "gzip"
                    resp.headers["Content-Length"] = str(len(packed))
                    resp.headers["Vary"] = "Accept-Encoding"
        except Exception:
            pass
        return resp

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Local PixAI gallery server.")
    ap.add_argument("--out", default="pixai_backup",
                    help="backup folder containing catalog.csv (default: pixai_backup)")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1; use 0.0.0.0 for LAN)")
    ap.add_argument("--https", action="store_true",
                    help="serve over self-signed HTTPS (needed for PWA install / service "
                         "worker on a phone over LAN; requires the 'cryptography' package; "
                         "browsers show a one-time certificate warning)")
    ap.add_argument("--rebuild-thumbs", action="store_true",
                    help="regenerate all thumbnails even if they already exist")
    ap.add_argument("--skip-thumbs", action="store_true",
                    help="don't build catalog thumbnails on startup (fast boot; missing "
                         "ones show 'no preview'). Per-generation thumbs are still made.")
    ap.add_argument("--open-browser", action="store_true",
                    help="open the gallery in your default browser once the server is up "
                         "(used by the double-click 'Serve Gallery' launcher)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        sys.exit("Output folder not found: {}".format(out_dir))

    db_path  = out_dir / "catalog.db"
    csv_path = out_dir / "catalog.csv"

    # Auto-migrate existing catalog.csv when db is missing or empty
    if _db_is_empty(db_path) and csv_path.exists():
        print("Migrating catalog.csv → catalog.db ...")
        n = migrate_csv_to_db(csv_path, db_path)
        print("Migrated {:,} rows.".format(n))
    elif _db_is_empty(db_path):
        sys.exit("No catalog found in {}. Run a download first.".format(out_dir))

    thumb_dir = out_dir / "gallery" / "thumbs"
    print("Loading catalog...")
    rows = load_catalog(db_path)
    if args.skip_thumbs:
        print("Skipping thumbnail build (--skip-thumbs).")
    else:
        print("Building thumbnails (new only — use --rebuild-thumbs to force all)...")
        build_thumbnails(rows, out_dir, thumb_dir, force=args.rebuild_thumbs)

    ssl_context = None
    scheme = "http"
    if getattr(args, "https", False):
        try:
            import cryptography  # noqa: F401  (werkzeug 'adhoc' needs it)
            ssl_context = "adhoc"
            scheme = "https"
        except ImportError:
            print("--https needs the 'cryptography' package:  pip install cryptography\n"
                  "Falling back to HTTP.")

    app = create_app(out_dir)
    url = "{}://{}:{}/".format(
        scheme, "localhost" if args.host == "0.0.0.0" else args.host, args.port)
    print("\nGallery ready ->  {}".format(url))
    if ssl_context:
        print("(self-signed HTTPS: your browser/phone will show a one-time 'proceed anyway' warning)")
    print("Press Ctrl+C to stop.\n")
    if getattr(args, "open_browser", False):
        # fire just after app.run() starts blocking (the GUI proves this pattern)
        import threading, webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True, ssl_context=ssl_context)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
moonglade_gallery.py
================
Local Flask web gallery for your PixAI backup collection.

Reads catalog.db (SQLite) and serves a browseable, filterable, paginated image
gallery at http://localhost:5000 . Supports single and bulk delete (removes
image file, thumbnail, and catalog row).

Requirements:
    pip install flask pillow

Usage:
    python moonglade_gallery.py
    python moonglade_gallery.py --out pixai_backup --port 5000
"""

import argparse
import csv
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path

import moonglade_assets
import moonglade_container

try:
    from flask import (Flask, jsonify, redirect, render_template_string, request,
                       send_file, send_from_directory, session, url_for)
except ImportError:
    sys.exit("Flask is required for the gallery server.\n"
             "Install it with:  pip install flask")

try:
    from PIL import Image
except ImportError:
    Image = None  # thumbnails will be skipped with a warning

# Windows-only: every subprocess this app spawns (ffmpeg/ffprobe thumbnail work,
# the PowerShell shortcut writer, git for the build stamp, the Panel's CLI jobs)
# would otherwise briefly flash a console window into view. 0x08000000 is the
# stable Win32 CREATE_NO_WINDOW value (same constant subprocess.CREATE_NO_WINDOW
# exposes on Windows) -- hardcoded so this doesn't need `subprocess` imported at
# module scope just for this. Evaluates to 0 (no-op) on non-Windows platforms.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


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
    # LINEAGE (2026-08-06): the source image a derived gen was made from + the kind of
    # derivation ("edit"/"upscale"/"video"). Blank for originals. See source_media_of_task.
    # lineage_checked is the persisted "confirmed original, don't re-fetch" marker for
    # --backfill-lineage -- see that command's docstring for why it's a real column.
    "source_media_id", "derive_kind", "lineage_checked",
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
    # Server-reported ACTUAL credit cost of the row's task (captured at poll/collect/
    # full-meta time). TASK-level: repeated on each of the task's media rows, so spend
    # totals must count once per task_id. '0' is a real value (free card / daily-free
    # gen); '' means never captured -- never conflate the two.
    "paid_credit",
    # Perceptual difference-hash (dHash, compute_dhash()) of the image, IMAGE ROWS ONLY
    # (blank for videos and for images not yet processed). 16 hex chars = 64 bits.
    # Populated by `--backfill-phash`, not at pull/collect time -- backfilled on demand
    # like blurhash/paid_credit above. Powers the near_duplicate tier in
    # GET /api/duplicates (near_duplicate_groups()): a Hamming-distance comparison finds
    # "upscaled or recompressed version of the same image" pairs that byte-hashing (Class
    # B, identical_file) misses because the bytes differ.
    "phash",
    # FULL GENERATION SURFACE (2026-08-15, issue #18): fields the getTaskById record carries
    # that we previously dropped on the floor. All resolved by extract_full_meta from the task
    # (image + video); steps/sampler/cfg above now also backfill from the model preset when the
    # task omits them (e.g. Tsubaki.2, whose detailParameters is absent).
    "inference_profile",   # parameters.inferenceProfile -- quality/speed mode (lite/standard/pro/ultra)
    "quality_tag",         # parameters.qualityTag.prefix -- the Mio.2-agent quality prefix (e.g. 'Masterpiece')
    "prompt_helper",       # promptHelper.enable + detected reason, folded to one label
    "control_nets",        # parameters.controlNets, JSON when non-empty
    "lora_parameters",     # parameters.loraParameters raw [{versionId,weight}] JSON (loras is the resolved view)
    "priority",            # parameters.priority (1000 normal / 1500 turbo)
    "render_seconds",      # outputs.inferenceInfo.stages.pipeline_run_s -- actual render time
    "backend",             # outputs.inferenceInfo.backend (e.g. 'pdr')
    "started_at", "ended_at", "updated_at",   # true queue->start->finish timing (created_at is submit)
    "retry_count",         # task.retryCount
    "moderation",          # moderationAction.promptsModerationAction (PASS / ...)
    "video_mode",          # parameters.i2vPro.mode (video tasks)
    "video_model",         # parameters.i2vPro.model (video tasks)
    # BATCH IDENTITY (2026-08-23, issue #33): PixAI's own output number for this row
    # within its task's batch. getTaskById returns outputs.batch -- an ORDERED array of
    # {mediaId, seed, extra}, one per output -- and batch[i].mediaId == this media_id
    # gives batch_index=str(i) (0-based, the same <n> the site's own download names
    # from-PixAI-<taskId>-<n> use) and batch_size=str(len(batch)). The index is PixAI's
    # PERMANENT fact: captured once, NEVER renumbered when a sibling is deleted (a gap
    # is true) and NEVER inferred from media_id order (which can swap outputs). Blank
    # means "not a batch output" (edits, upscales, videos, imports) -- not "unknown".
    "batch_index", "batch_size",
]

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"})
THUMB_SIZE = (768, 768)
THUMB_QUALITY = 90
DHASH_SIZE = 8  # compute_dhash()'s hash dimension: 8x8 -> 64-bit hash, 16 hex chars


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
    source_media_id TEXT DEFAULT '',
    derive_kind     TEXT DEFAULT '',
    lineage_checked TEXT DEFAULT '',
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
    nsfw_scores     TEXT DEFAULT '',
    paid_credit     TEXT DEFAULT '',
    phash           TEXT DEFAULT '',
    inference_profile TEXT DEFAULT '',
    quality_tag       TEXT DEFAULT '',
    prompt_helper     TEXT DEFAULT '',
    control_nets      TEXT DEFAULT '',
    lora_parameters   TEXT DEFAULT '',
    priority          TEXT DEFAULT '',
    render_seconds    TEXT DEFAULT '',
    backend           TEXT DEFAULT '',
    started_at        TEXT DEFAULT '',
    ended_at          TEXT DEFAULT '',
    updated_at        TEXT DEFAULT '',
    retry_count       TEXT DEFAULT '',
    moderation        TEXT DEFAULT '',
    video_mode        TEXT DEFAULT '',
    video_model       TEXT DEFAULT '',
    batch_index       TEXT DEFAULT '',
    batch_size        TEXT DEFAULT ''
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
    "ALTER TABLE catalog ADD COLUMN paid_credit TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN phash TEXT DEFAULT ''",
    # LINEAGE (2026-08-06): the SOURCE image a derived generation was made from, and the
    # kind of derivation ("edit"/"upscale"/"video"). Empty for original txt2img rows.
    # Populated from task params (source_media_of_task); batch siblings need no column
    # (they share task_id already). Indexed so "what did this image spawn" is a fast lookup.
    "ALTER TABLE catalog ADD COLUMN source_media_id TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN derive_kind TEXT DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_source_media_id ON catalog(source_media_id)",
    # task_id is the sibling key (/api/siblings IN-query, the View Batch filter) and had
    # no index: both were full scans of the table (adversarial review, 2026-08-22).
    "CREATE INDEX IF NOT EXISTS idx_task_id ON catalog(task_id)",
    # A real txt2img original legitimately has an EMPTY source_media_id forever, which
    # makes "blank" ambiguous with "never checked" -- this is the persisted "checked, found
    # nothing" marker --backfill-lineage needs so it doesn't re-fetch every original task on
    # every single run (an in-memory-only marker was tried first and silently discarded by
    # save_catalog, since it isn't a real column -- caught before it shipped).
    "ALTER TABLE catalog ADD COLUMN lineage_checked TEXT DEFAULT ''",
    # FULL GENERATION SURFACE (2026-08-15, issue #18) -- added to existing catalogs on connect.
    "ALTER TABLE catalog ADD COLUMN inference_profile TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN quality_tag TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN prompt_helper TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN control_nets TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN lora_parameters TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN priority TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN render_seconds TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN backend TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN started_at TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN ended_at TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN updated_at TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN retry_count TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN moderation TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN video_mode TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN video_model TEXT DEFAULT ''",
    # BATCH IDENTITY (2026-08-23, issue #33) -- PixAI's own 0-based output number and the
    # task's batch size, from getTaskById outputs.batch. Never renumbered on deletion,
    # never inferred from media_id order; blank = "not a batch output", not "unknown".
    "ALTER TABLE catalog ADD COLUMN batch_index TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN batch_size TEXT DEFAULT ''",
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

    * `*` -> `%` (any run) and `?` -> `_` (single char).
    * EVERY term is matched as a substring (wrapped in `%...%`), wildcard or not.
    * Literal `%`/`_`/`\` the user typed are escaped (LIKE uses ESCAPE '\').

    A wildcard must never make a search return FEWER results than the same term
    without it. That invariant is pinned by a test, and it used not to hold:
    a term containing a wildcard became the WHOLE pattern, so `night*` compiled
    to `night%` -- anchored to the start of the entire prompt string, not to a
    word. So the app's own placeholder ("words, night* wildcard, or an id")
    advertised a syntax that returned nothing on most libraries, and adding a
    `*` to a working search silently emptied it: `sample` matched 24 rows,
    `sampl*` matched 0. Found by a browser crawl typing the advertised example.

    Interior wildcards still do real work, which is where they earn their keep:
    `moon*light` -> `%moon%light%` matches "moonlight" and "moon and starlight"
    alike, and `n?ght` -> `%n_ght%` still constrains a single character. A
    leading or trailing star now simply collapses into the surrounding wrap, so
    `night*` and `night` mean the same thing rather than opposite things.
    """
    t = term.strip().lower()
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    t = t.replace("*", "%").replace("?", "_")
    # Collapse runs of % left by a leading/trailing star meeting the wrap. Purely
    # cosmetic ('%%' and '%' match identically) but keeps logged queries readable.
    # An escaped literal '\%' is not a run and is left alone by the negative
    # lookbehind -- a user searching "50%" must still match a literal percent.
    return re.sub(r"(?<!\\)%{2,}", "%", "%" + t + "%")


def _like_escape(s):
    r"""Escape LIKE's own metacharacters in a value that must match LITERALLY --
    a collection name, an art tag, a LoRA name. Unlike _like_pattern above there
    are no wildcards to honor here: these filters promise an exact token / plain
    substring, and without this a collection named "100%" or "a_b" compiled into
    a wildcard that matched half the catalog instead of its own two images. Pair
    it with ESCAPE '\' on the clause or the backslashes stay literal.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Search field operators: key:value tokens inside the search box
# ---------------------------------------------------------------------------
# alias -> (kind, column). Kinds:
#   text       substring, case-insensitive, * / ? wildcards via _like_pattern
#   prompt     like a free-text term (prompt_full OR prompt_preview) but explicit,
#              which matters for quoted phrases: prompt:"night elf"
#   num        key:N exact, or key:>N / key:<N / key:>=N / key:<=N; a blank column
#              value never matches a comparison (except rating -- see below)
#   exact      whole-value equality (ids and seeds; substring matching ids is the
#              exact chance-collision failure the long-digit gate below exists for)
#   bool       1/true/yes/on -> col='1'; 0/false/no/off -> anything else
#   date       created_at prefix (2026 / 2026-07 / 2026-07-04) or a </>/<=/>=
#              prefix-compare (created:<2026-07 = strictly before July)
#   collection exact-token match in the comma-joined list, same as the dropdown
#   source     the dropdown's semantics (online = blank-or-online, deleted =
#              deleted_remote flag), else substring on the source column
#
# Deliberately NOT operators (one line each):
#   url             expiring PixAI CDN link -- nothing sane to filter on
#   prompt_preview/ covered by free text and prompt:
#     prompt_full
#   poster_media_id internal video->poster linkage; media: finds either row
#   blurhash        opaque placeholder hash, not human-meaningful
#   nsfw_scores     JSON blob; nsfw: covers the sane ask
#   deleted_remote  already surfaced as source:deleted (mirrors the dropdown)
#
# Injection safety: every user value is a bound SQL parameter. The only strings
# interpolated into SQL are column names and comparison operators, and both come
# exclusively from these hardcoded maps -- never from user input. Pinned by
# tests/test_search_operators.py's hostile-value test.
_SEARCH_OPS = {
    "prompt":   ("prompt", None),
    "negative": ("text", "negative_prompt"), "negative_prompt": ("text", "negative_prompt"),
    "model":    ("text", "model_name"),      "model_name": ("text", "model_name"),
    "lora":     ("text", "loras"),           "loras": ("text", "loras"),
    "tag":      ("text", "art_tags"),        "tags": ("text", "art_tags"),
    "art_tags": ("text", "art_tags"),
    "title":    ("text", "title"),
    "sampler":  ("text", "sampler"),
    "filename": ("text", "filename"),
    "batch":    ("text", "batch"),
    "status":   ("text", "status"),
    "natural":  ("text", "natural_prompt"),  "natural_prompt": ("text", "natural_prompt"),
    "width":    ("num", "width"),
    "height":   ("num", "height"),
    "rating":   ("num", "rating"),
    "steps":    ("num", "steps"),
    "cfg":      ("num", "cfg_scale"),        "cfg_scale": ("num", "cfg_scale"),
    "clip_skip": ("num", "clip_skip"),
    "aes":      ("num", "aes_score"),        "aes_score": ("num", "aes_score"),
    "likes":    ("num", "liked_count"),      "liked_count": ("num", "liked_count"),
    "comments": ("num", "comment_count"),    "comment_count": ("num", "comment_count"),
    "duration": ("num", "video_duration"),   "video_duration": ("num", "video_duration"),
    "seed":     ("exact", "seed"),
    "task":     ("exact", "task_id"),        "task_id": ("exact", "task_id"),
    "media":    ("exact", "media_id"),       "media_id": ("exact", "media_id"),
    "artwork":  ("exact", "artwork_id"),     "artwork_id": ("exact", "artwork_id"),
    "model_id": ("exact", "model_id"),
    "video":    ("bool", "is_video"),        "is_video": ("bool", "is_video"),
    "published": ("bool", "is_published"),   "is_published": ("bool", "is_published"),
    "nsfw":     ("bool", "is_nsfw"),         "is_nsfw": ("bool", "is_nsfw"),
    "created":  ("date", "created_at"),      "created_at": ("date", "created_at"),
    "date":     ("date", "created_at"),
    "collection": ("collection", "collections"),
    "collections": ("collection", "collections"),
    "source":   ("source", "source"),
}

# Tokens: quoted runs group (model:"Ether Real" / "night elf" are ONE token each);
# everything else splits on whitespace exactly like q.split() always did.
_SEARCH_TOKEN_RE = re.compile(r'[^\s"]*"[^"]*"[^\s"]*|\S+')
_SEARCH_KEY_RE   = re.compile(r"[A-Za-z_]+")
_SEARCH_NUM_RE   = re.compile(r"^(>=|<=|>|<)?(-?\d+(?:\.\d+)?)$")
_SEARCH_DATE_RE  = re.compile(r"^(>=|<=|>|<)?(\d{4}(?:-\d{2}(?:-\d{2})?)?)$")
_SEARCH_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SEARCH_FALSY  = frozenset({"0", "false", "no", "off"})


def _unquote(s):
    """Strip one pair of surrounding double quotes, if present."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _operator_clause(key, value):
    """Compile one key:value search token into (sql_clause, params), or None when
    the token isn't a valid operator and should be searched as plain prompt text
    instead (unknown key, empty value, malformed number/date, unrecognized bool)
    -- the way search engines degrade, so a stray colon never errors or surprises."""
    spec = _SEARCH_OPS.get(key.lower())
    if not spec or value == "":
        return None
    kind, col = spec
    if kind == "text":
        return ("LOWER(COALESCE({},'')) LIKE ? ESCAPE '\\'".format(col),
                [_like_pattern(value)])
    if kind == "prompt":
        like = _like_pattern(value)
        return ("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')",
                [like, like])
    if kind == "exact":
        return ("{} = ?".format(col), [value])
    if kind == "num":
        m = _SEARCH_NUM_RE.match(value)
        if not m:
            return None
        op = m.group(1) or "="
        num = float(m.group(2))
        if col == "rating":
            # unrated ('') counts as 0 -- identical to the Min-rating dropdown
            return ("CAST(COALESCE(NULLIF(rating,''),'0') AS REAL) {} ?".format(op),
                    [num])
        return ("(COALESCE({0},'') != '' AND CAST({0} AS REAL) {1} ?)".format(col, op),
                [num])
    if kind == "bool":
        v = value.lower()
        if v in _SEARCH_TRUTHY:
            return ("{} = '1'".format(col), [])
        if v in _SEARCH_FALSY:
            return ("COALESCE({},'') != '1'".format(col), [])
        return None
    if kind == "date":
        m = _SEARCH_DATE_RE.match(value)
        if not m:
            return None
        op = m.group(1) or "="
        prefix = m.group(2)
        # prefix-compare: created:>2026-07 excludes July itself, created:>=2026-07
        # includes it -- comparing the row's SAME-LENGTH prefix keeps that intuitive
        # (a raw string compare against full timestamps would drag July into '>')
        return ("SUBSTR(created_at,1,?) {} ?".format(op), [len(prefix), prefix])
    if kind == "collection":
        # exact-token in the comma-joined list, mirroring the Collection dropdown
        return ("(',' || COALESCE(collections,'') || ',') LIKE ? ESCAPE '\\'",
                ["%," + _like_escape(value) + ",%"])
    if kind == "source":
        v = value.lower()
        if v == "online":
            return ("COALESCE(source,'') IN ('', 'online')", [])
        if v in ("api", "local"):
            return ("source = ?", [v])
        if v == "deleted":
            return ("deleted_remote = '1'", [])
        return ("LOWER(COALESCE(source,'')) LIKE ? ESCAPE '\\'",
                [_like_pattern(value)])
    return None


def _build_where(q, model, date_from, date_to, batch="", rating_min=0,
                 published_only=False, art_tag="", lora="", media_type="", source="",
                 collection=""):
    """Return (where_clause, params) for the common filter set."""
    clauses = ["filename != ''"]
    params  = []
    if collection:
        # exact-token match within the comma-joined list (no partial-name bleed)
        clauses.append("(',' || COALESCE(collections,'') || ',') LIKE ? ESCAPE '\\'")
        params.append("%," + _like_escape(collection) + ",%")
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
        clauses.append("LOWER(COALESCE(art_tags,'')) LIKE ? ESCAPE '\\'")
        params.append("%" + _like_escape(art_tag.strip().lower()) + "%")
    if lora:
        clauses.append("LOWER(COALESCE(loras,'')) LIKE ? ESCAPE '\\'")
        params.append("%" + _like_escape(lora.strip().lower()) + "%")
    if q:
        # Whitespace-separated tokens are ANDed. A token can be a FIELD OPERATOR
        # (key:value -- see _SEARCH_OPS/_operator_clause above; quoted values group,
        # so model:"Ether Real" is one token); anything else is free text, whose
        # behavior is UNCHANGED from before operators existed (pinned at the SQL
        # level by tests/test_search_operators.py): each term may use * / ?
        # wildcards over prompt text, and a term that looks like a WHOLE task/media
        # id (all digits, long enough that a short numeric prompt word can't
        # collide -- PixAI ids run ~18-19 digits) also matches that id EXACTLY, so
        # pasting an id from PixAI's site (or --dump-params output) finds the row.
        # Short numeric terms stay prompt-only: a substring match on ids made a
        # term like "88" match ~14% of the whole catalog by id chance alone,
        # swamping any real prompt hits (found 2026-07-16).
        for tok in _SEARCH_TOKEN_RE.findall(q):
            op_clause = None
            if ":" in tok and not tok.startswith(":"):
                key, _, raw = tok.partition(":")
                if _SEARCH_KEY_RE.fullmatch(key):
                    op_clause = _operator_clause(key, _unquote(raw))
            if op_clause:
                clauses.append(op_clause[0])
                params += op_clause[1]
                continue
            term = _unquote(tok)
            if term.isdigit() and len(term) >= 8:
                clauses.append("(task_id = ? OR media_id = ?)")
                params += [term, term]
            else:
                clauses.append("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
                               "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')")
                like = _like_pattern(term)
                params += [like, like]
    if model:
        clauses.append("model_name = ?")
        params.append(model)
    if batch:
        # EITHER column: --organize blanks `batch` (r["batch"] = ""), so a library
        # that has been organized would resolve a batch filter to nothing. The Details
        # "View Batch" button passes the task_id (issue #30); the legacy batches/
        # folder-name filter keeps working through the same param.
        clauses.append("(batch = ? OR task_id = ?)")
        params.extend([batch, batch])
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


def get_row_by_task(db_path, task_id):
    """One catalog row for a task id, or None. Membership check for
    /api/task-params: a task id this library never downloaded from is refused
    there, so the route can't be used to probe arbitrary task ids under the
    owner's credentials (adversarial review 2026-08-13, finding 4.3)."""
    con = _connect(db_path)
    try:
        row = con.execute("SELECT * FROM catalog WHERE task_id=? LIMIT 1",
                          (task_id,)).fetchone()
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


# Both collection edits below are a read-modify-write of ONE comma-joined column, so
# two requests landing on the same media_id (the app is used from several devices at
# once -- a bulk add overlapping a single-image toggle is enough) each read the old
# list and write back only their own label, and one edit vanishes with no error. The
# lock spans the loop rather than each row because the batch already commits as a
# single transaction; a per-row lock would just hand the other thread a mid-transaction
# view of the same rows.
_COLLECTIONS_LOCK = threading.Lock()


def add_to_collection(db_path, media_ids, name):
    """Add a collection label to each media_id (no-op if already in it). Names may
    contain spaces but not commas. Returns the number of rows changed."""
    name = (name or "").strip().replace(",", " ").strip()
    if not name or not media_ids:
        return 0
    con = _connect(db_path)
    changed = 0
    try:
        with _COLLECTIONS_LOCK:
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
        with _COLLECTIONS_LOCK:
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
    """Return (rows, total) with filtering, sorting and pagination done in SQL.

    `page_size=None` means UNPAGINATED: one statement returns every matching row and
    `total` is simply how many came back. That is not a convenience shorthand for "a very
    large page" -- it closes a real hole. The paginated path answers COUNT(*) and the page
    itself in two SEPARATE statements, i.e. two separate SQLite read snapshots with no
    transaction across them, so a write landing between the two makes them disagree. A grid
    page can absorb that (worst case a paginator is off by one for one refresh), but a
    caller that sizes its LIMIT off the count cannot: /export-csv did exactly that, and a
    "Sync now" Panel job inserting rows for minutes while the owner browsed meant the CSV
    silently shipped the OLD match count out of the new, larger match set, with nothing in
    the downloaded file admitting it was short. One statement has nothing to disagree with.
    """
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    order = _SORT_SQL.get(sort, _DEFAULT_SORT_SQL)
    con = _connect(db_path)
    try:
        if page_size is None:
            rows = con.execute(
                "SELECT * FROM catalog WHERE {} ORDER BY {}".format(where, order),
                params,
            ).fetchall()
            # No second COUNT on purpose -- taking one here would reintroduce exactly the
            # two-snapshot disagreement this branch exists to avoid, and a total that can
            # differ from len(rows) is precisely what misled the export.
            return [dict(r) for r in rows], len(rows)
        total = con.execute(
            "SELECT COUNT(*) FROM catalog WHERE {}".format(where), params
        ).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM catalog WHERE {} ORDER BY {} LIMIT ? OFFSET ?".format(where, order),
            params + [page_size, (max(1, page) - 1) * page_size],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        con.close()


def _filters_from_args(args):
    """Pull the gallery grid's filter set out of a request query string, keyed by
    query_catalog()'s own parameter names (the index route reads exactly these args --
    see its body, including the Year+Month dropdown pair a date filter arrives as).

    Only filters actually PRESENT come back, so an empty dict means "no filtering at
    all" and a caller can take the whole catalog instead. Values are validated the same
    way index() validates them, since they reach SQL."""
    def _ym(prefix, month_default):
        y = args.get(prefix + "_year", "")
        m = args.get(prefix + "_month", "")
        return "{}-{}".format(y, m or month_default) if y else ""

    try:
        rating_min = max(0, min(5, int(args.get("rating_min", 0))))
    except ValueError:
        rating_min = 0
    media_type = args.get("media", "")
    source = args.get("source", "")
    found = {
        "q":              args.get("q", ""),
        "model":          args.get("model", ""),
        "batch":          args.get("batch", ""),
        "date_from":      _ym("from", "01"),
        "date_to":        _ym("to", "12"),
        "rating_min":     rating_min,
        "published_only": args.get("published") == "1",
        "art_tag":        args.get("tag", ""),
        "lora":           args.get("lora", ""),
        "media_type":     media_type if media_type in ("image", "video") else "",
        "source":         source if source in ("online", "api", "local", "deleted") else "",
        "collection":     args.get("collection", ""),
    }
    # Every default here is falsy (""/0/False), so dropping falsy values is exactly
    # "drop the filters the user didn't set".
    return {k: v for k, v in found.items() if v}


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
# The dial-in series engine (issue #34) -- clustering a run of tasks into the
# session that produced them: same model, gap <= 8h, clause-Jaccard >= 0.5,
# chained over tasks in id order. The rule is OWNER-VALIDATED on the Series
# Review Board (10/10 samples accurate, near-misses correctly apart), so this
# code's job is to REPLICATE the validated JS exactly, not to improve on it.
# Series are computed, never stored: the catalog stays the single source of
# truth and a recompute after any edit/delete is honest about what exists.
# ---------------------------------------------------------------------------

def _series_text(row):
    """The EXACT text the owner validated the clustering rule on (#34, engine
    requirement comment): the library API's `prompt` field, which is
    `(prompt_full or prompt_preview or "")[:1200]` (see /api/next/library's item
    builder). Same fallback order, same 1200-char cap -- Mio-era prose runs ~2k
    chars, and an uncapped read yields DIFFERENT clause sets than the validated
    board. Pinned by the >1200-char test in tests/test_series_engine.py."""
    return (row["prompt_full"] or row["prompt_preview"] or "")[:1200]


def _series_clause_list(text):
    """Ordered, de-duplicated clause list for a prompt -- the exact tokenization
    the owner validated (#34): strip `<...>` tokens (lora/character markup is not
    prose), turn `.` `;` and newlines into commas, split on commas, trim,
    lowercase, keep only clauses longer than 3 chars. Order is prompt order --
    the delta differ uses it so "+ added clause" labels surface the clause the
    way the owner typed it, not alphabetically."""
    t = re.sub(r"<[^>]*>", "", str(text or ""))
    t = t.replace(".", ",").replace(";", ",").replace("\r", ",").replace("\n", ",")
    out, seen = [], set()
    for part in t.split(","):
        c = part.strip().lower()
        if len(c) > 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _series_clauses(text):
    """The validated clause SET for a prompt (#34) -- set semantics drop pure
    reorderings for free, which is exactly what the validated Jaccard saw."""
    return set(_series_clause_list(text))


def _series_ts(created_at):
    """Epoch seconds for a stored created_at, or None. Same tolerance as the
    History feed's _history_ts (which lives inside create_app and can't be
    shared from module level): PixAI's 24-char `...T06:14:10.545Z`, the 20-char
    no-millis `...Z`, and the 19-char naive legacy rows -- all UTC (#34 review:
    timestamps are UTC ISO strings, hour math needs no zone care)."""
    from datetime import datetime, timezone
    s = str(created_at or "").strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    frac = s[19:]
    ms = 0.0
    if frac.startswith(".") and frac[1:].isdigit():
        ms = float("0" + frac)
    return base.timestamp() + ms


# Ported from gallery/src/gen/headline.js's SCAFFOLD set -- KEEP THE TWO IN SYNC
# (that file is the origin; a tag added there belongs here too). Used only to
# skip non-descriptive clauses when a series has no character token to name
# itself after (#34: "else the head descriptive clause -- the headline excerpt
# rule already in gen/headline.js").
_SERIES_SCAFFOLD = frozenset({
    "masterpiece", "best quality", "amazing quality", "high quality", "highres",
    "absurdres", "very awa", "newest", "1girl", "1boy", "2girls", "2boys", "solo",
    "looking at viewer", "detailed background", "ultra detailed", "highly detailed",
    "8k", "4k", "score_9", "score_8_up", "score_7_up", "rating_safe",
    "rating_explicit", "rating_questionable",
})


def _series_is_scaffold(clause):
    """Python twin of headline.js's isScaffold(), over an already-lowercased
    clause: the SCAFFOLD set, tag namespaces, leftover `<...>` tokens, pony
    scores/ratings, and weighted quality openers."""
    c = clause
    if c in _SERIES_SCAFFOLD:
        return True
    if re.match(r"^(artist|character|copyright|lora|source):", c):
        return True
    if re.match(r"^<[^>]*>$", c):
        return True
    if re.match(r"^score_\d", c) or re.match(r"^rating_", c):
        return True
    if re.match(r"^\(?(masterpiece|best quality)", c):
        return True
    return False


def _series_cap_first(s):
    """headline.js's capFirst: first character up, rest untouched."""
    return (s[:1].upper() + s[1:]) if s else s


def _series_title(text):
    """A series' display name, from the FIRST task's prompt (#34: 'character
    name when a character token resolves, else the head descriptive clause').
    Character sources, in order:
      * a clause starting `character:` (booru tag namespace);
      * a `<token>` in the ORIGINAL text -- captured BEFORE _series_clause_list
        strips them -- whose text is not a lora-weight form (`lora:...` /
        trailing `:0.8` weights are model plumbing, not a name).
    Normalization: drop the `character:` prefix, dashes to spaces, title-case
    the first word. Fallback: the first non-scaffold clause (the headline
    excerpt rule -- see _SERIES_SCAFFOLD). Everything trims to 40 chars; ''
    when the prompt has nothing descriptive to say."""
    raw = str(text or "")
    cand = ""
    for c in _series_clause_list(raw):
        if c.startswith("character:"):
            cand = c
            break
    if not cand:
        for tok in re.findall(r"<([^>]*)>", raw):
            t = tok.strip()
            if not t:
                continue
            if re.match(r"^(lora|lyco|hypernet)\b", t, re.IGNORECASE):
                continue
            if re.search(r":\d+(\.\d+)?$", t):
                continue
            cand = t
            break
    if cand:
        cand = re.sub(r"^character:\s*", "", cand, flags=re.IGNORECASE)
        cand = " ".join(cand.replace("-", " ").split())
        return _series_cap_first(cand)[:40]
    for c in _series_clause_list(raw):
        if not _series_is_scaffold(c):
            return _series_cap_first(c)[:40]
    return ""


def _series_delta_label(prev_task, cur_task):
    """The short step label for a NON-reroll member vs the previous task in its
    series (#34): added = clauses in cur not in prev, removed = prev not in cur
    (sets, so pure reorderings vanish); up to 2 added ('+ ...') then 1 removed
    ('− ...'), each clause trimmed to 34 chars, joined ' · ', whole
    label capped at ~80. Clause order is prompt order (see _series_clause_list)
    so the label reads the way the owner typed the change."""
    added = [c for c in cur_task["clause_list"] if c not in prev_task["clauses"]]
    removed = [c for c in prev_task["clause_list"] if c not in cur_task["clauses"]]
    parts = ["+ " + c[:34] for c in added[:2]]
    if removed:
        parts.append("− " + removed[0][:34])
    label = " · ".join(parts)
    if len(label) > 80:
        label = label[:79].rstrip() + "…"
    return label


def compute_series(db_path):
    """One linear pass applying the owner-validated dial-in rule (#34): over
    tasks in task_id order, a task JOINS the current series iff
        same model key  AND  gap <= 8h  AND  clause-Jaccard >= 0.5
    vs the PREVIOUS task. Returns (by_task, by_sid):
        by_task -- {task_id: (sid, v)} for every member of a multi-task series;
        by_sid  -- {sid: series struct} (the /api/series/<sid> payload).

    The decisions this encodes (design review 2026-08-23, folded into #34):
      * model key = model_id if non-empty else model_name -- display names
        collide ("Unknown or removed model") and renames drift; ids only ever
        SPLIT relative to the validated name-keyed clusters, never merge, so
        the owner's validation stands as the looser bound.
      * sid = the FIRST task's id -- deterministic, so `?series=<sid>` URLs and
        B's navigation survive a recompute. Series are computed, not stored.
      * missing/blank created_at => gap = infinity (starts a new series); a
        task AFTER one with no timestamp can't measure its gap either, so it
        starts fresh too. Jaccard of two EMPTY clause sets = 1 -- identical
        empties chain, matching the validated board.
      * only series with >= 2 tasks are kept: singletons (85% of tasks) cost
        nothing and produce no API rows.
      * member media_ids are ordered the way /api/siblings orders them (#33):
        by batch_index when EVERY member has one, else media_id -- so
        first_media_id is the task's true first output when the order is known.
      * v-numbers are 1-based positions and MAY renumber when a member is
        deleted -- honest (they describe what exists), explicitly UNLIKE #33's
        batch index (PixAI's permanent fact, never renumbered).
    """
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT task_id, model_id, model_name, created_at, prompt_full,"
            " prompt_preview, media_id, batch_index FROM catalog"
            " WHERE task_id != '' ORDER BY task_id, media_id").fetchall()
    finally:
        con.close()

    # Aggregate rows into tasks (first row's text/model/timestamp; every row a
    # member). batch_index rides along purely for the #33 member ordering.
    tasks, by_id = [], {}
    for r in rows:
        tid = str(r["task_id"])
        t = by_id.get(tid)
        if t is None:
            text = _series_text(r)
            clause_list = _series_clause_list(text)
            t = {
                "task_id": tid,
                "text": text,
                "clause_list": clause_list,
                "clauses": set(clause_list),
                "model_key": str(r["model_id"] or "") or str(r["model_name"] or ""),
                "model_label": str(r["model_name"] or "") or str(r["model_id"] or ""),
                "created_at": str(r["created_at"] or ""),
                "ts": _series_ts(r["created_at"]),
                "members": [],
            }
            by_id[tid] = t
            tasks.append(t)
        try:
            bi = int(str(r["batch_index"] or "").strip())
        except ValueError:
            bi = None
        t["members"].append((str(r["media_id"] or ""), bi))
    for t in tasks:
        if t["members"] and all(bi is not None for _, bi in t["members"]):
            t["members"].sort(key=lambda m: m[1])

    # The linear chain. `tasks` is already task_id-ascending (SQL ORDER BY).
    chains, cur, prev = [], None, None
    for t in tasks:
        joins = False
        if prev is not None and t["model_key"] == prev["model_key"]:
            if t["ts"] is None or prev["ts"] is None:
                gap = float("inf")
            else:
                gap = abs(t["ts"] - prev["ts"])
            if gap <= 8 * 3600.0:
                a, b = t["clauses"], prev["clauses"]
                union = len(a | b)
                jaccard = (len(a & b) / union) if union else 1.0
                joins = jaccard >= 0.5
        if joins:
            cur.append(t)
        else:
            cur = [t]
            chains.append(cur)
        prev = t

    by_task, by_sid = {}, {}
    for chain in chains:
        if len(chain) < 2:
            continue
        sid = chain[0]["task_id"]
        steps, count_images, prev_t = [], 0, None
        for i, t in enumerate(chain):
            v = i + 1
            reroll = prev_t is not None and t["clauses"] == prev_t["clauses"]
            if prev_t is None:
                label = "series start"
            elif reroll:
                label = "seed-only reroll"
            else:
                label = _series_delta_label(prev_t, t)
            n = len(t["members"])
            count_images += n
            steps.append({
                "task_id": t["task_id"], "v": v, "reroll": bool(reroll),
                "label": label,
                "first_media_id": t["members"][0][0] if t["members"] else "",
                "n": n,
            })
            by_task[t["task_id"]] = (sid, v)
            prev_t = t
        by_sid[sid] = {
            "sid": sid,
            "title": _series_title(chain[0]["text"]),
            "model": chain[0]["model_label"],
            "count_tasks": len(chain),
            "count_images": count_images,
            "span": [chain[0]["created_at"], chain[-1]["created_at"]],
            "steps": steps,
        }
    return by_task, by_sid


# The series cache (#34 review item 3). Keyed by db_path so tests' tmp catalogs
# never collide; each entry stores the cheap invalidation key, the compute time,
# and both indexes. The cheap key is `(COUNT(*), MAX(media_id))` -- journal_mode
# is `delete` (no WAL) so file mtime would also work, but the query is robust
# either way. The 30s floor exists because the live mirror WRITES DURING a sync:
# every saved page would otherwise trigger a full recompute (a linear pass over
# ~21k tasks) per gallery request. Staleness is bounded and honest -- the next
# request after the floor picks the new rows up.
_SERIES_CACHE = {}
_SERIES_CACHE_LOCK = threading.Lock()
_SERIES_RECOMPUTE_FLOOR_S = 30.0


def series_index(db_path):
    """The cached (by_task, by_sid) pair for a catalog. Recomputes only when the
    cheap key CHANGED and the last compute is at least _SERIES_RECOMPUTE_FLOOR_S
    old (both conditions -- see the cache note above). The lock covers the whole
    check-and-compute so concurrent requests during a sync can't stampede into
    parallel recomputes. Fails soft to empty indexes (no cache write) on a
    missing/broken catalog, like catalog_counts does."""
    try:
        con = _connect(db_path)
        try:
            cheap = tuple(con.execute(
                "SELECT COUNT(*), MAX(media_id) FROM catalog").fetchone())
        finally:
            con.close()
        now = time.time()
        with _SERIES_CACHE_LOCK:
            ent = _SERIES_CACHE.get(str(db_path))
            if ent is not None and (
                    ent["key"] == cheap
                    or (now - ent["computed_at"]) < _SERIES_RECOMPUTE_FLOOR_S):
                return ent["by_task"], ent["by_sid"]
            by_task, by_sid = compute_series(db_path)
            _SERIES_CACHE[str(db_path)] = {
                "key": cheap, "computed_at": time.time(),
                "by_task": by_task, "by_sid": by_sid,
            }
            return by_task, by_sid
    except sqlite3.Error:
        return {}, {}


# ---------------------------------------------------------------------------
# Achievements & Skins -- WoW-flavored milestones computed from local catalog
# stats (read-only, no spend). Earning an epic tier unlocks a cosmetic skin
# (a CSS-variable palette swap in the browser). State (which unlocks the user
# has already been *toasted* for, plus the active skin) persists to
# out_dir/achievements.json. See ACHIEVEMENTS/SKINS below for the catalog.
# ---------------------------------------------------------------------------
# ACHIEVEMENTS roster: SEALED into moonglade.dat (see _sealed_defs below). Read via _roster().

# ---------------------------------------------------------------------------
# The achievement roster + its ancillary tables (skins, skin-unlock text, the
# closed-set criteria labels, ladder-track names) are DEFINITIONS. They used to sit
# inline here, readable in a public `git clone`; they now live SEALED in
# moonglade.dat's "achievements" payload (a dict), built from the private donor
# ../moonglade-internal/achievements_sealed_donor.json by tools/build_container.py.
# Loaded LAZILY + cached (out_dir -- so the container path -- is not known at import).
# A container-less install degrades to the free-skins-only fallback (empty Folio,
# like missing art), never a crash. See ACHIEVEMENT_SEALING_SPEC.md; this is what
# lets the /api/achievements ??? masking finally protect something.
# The free skins are the app's DEFAULT dress (not rewards), so their non-spoiler
# names stay public as the no-container fallback.
_FALLBACK_DEFS = {
    "roster": [], "skin_unlock": {}, "ach_criteria": {}, "ladder_tracks": [],
    "skins": [
        {"id": "moonglade",   "name": "Moonglade",   "free": True,
         "desc": "The default -- lavender leads, emerald magic."},
        {"id": "nightfallen", "name": "Nightfallen", "free": True,
         "desc": "Void-touched violet and star-ash."},
    ],
}
_sealed_cache = {"path": None, "mtime": None, "defs": None}
_sealed_lock = threading.Lock()


def _sealed_defs():
    """The sealed achievement definitions {roster, skins, skin_unlock, ach_criteria,
    ladder_tracks} from moonglade.dat's "achievements" payload, plus the derived id /
    hidden / rung / skin-id sets. Cached per (container path, mtime) and computed UNDER
    the lock, so a cold-cache race (N workers hitting /api/achievements at once) decodes
    it once, not once per request. Fallback (free skins only) when there is no valid
    container OR the sealed roster is malformed -- the Folio degrades, never 500s."""
    p = _container_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = None
    # Open the container OUTSIDE _sealed_lock (it has its own _container_lock). The
    # decode+derive below runs UNDER _sealed_lock -- it re-enters neither lock, so holding
    # it here just serializes concurrent cold misses instead of decoding the payload N
    # times (box.payload does XOR + zlib.decompress; a few ms, not free).
    box = _get_container()
    with _sealed_lock:
        c = _sealed_cache
        if c["path"] == p and c["mtime"] == mtime and c["defs"] is not None:
            return c["defs"]
        defs = None
        raw = box.payload("achievements") if box is not None else None
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict) and "roster" in d:
                    defs = d
            except ValueError:
                defs = None
        # A checksum-valid but MALFORMED roster (valid JSON, but "roster" not a list of
        # well-shaped entries) must degrade like a missing one, not 500 the whole Folio:
        # derive from it, and on any shape error fall back to the free-skins defaults.
        try:
            computed = _derive_sealed(defs if defs is not None else _FALLBACK_DEFS)
        except (KeyError, TypeError, AttributeError):
            computed = _derive_sealed(_FALLBACK_DEFS)
        _sealed_cache.update(path=p, mtime=mtime, defs=computed)
        return computed


def _derive_sealed(defs):
    """Normalize a raw sealed-defs dict and attach the derived id / hidden / rung /
    skin-id sets. Raises (KeyError/TypeError/AttributeError) on a malformed roster so
    _sealed_defs can catch it and fall back to the free-skins defaults. _FALLBACK_DEFS is
    well-formed, so _derive_sealed(_FALLBACK_DEFS) is the guaranteed-safe last resort."""
    roster = defs.get("roster") or []
    defs = dict(defs)
    defs.setdefault("skins", [])
    defs.setdefault("skin_unlock", {})
    defs.setdefault("ach_criteria", {})
    defs.setdefault("ladder_tracks", [])
    defs["_ach_ids"] = frozenset(a["id"] for a in roster)
    defs["_ach_hidden"] = frozenset(a["id"] for a in roster if a.get("hidden"))
    defs["_ach_rung"] = _build_ach_rung(roster)
    defs["_skin_ids"] = {s["id"] for s in defs["skins"]}
    return defs


def _roster():        return _sealed_defs()["roster"]          # noqa: E704
def _skins():         return _sealed_defs()["skins"]           # noqa: E704
def _skin_unlock():   return _sealed_defs()["skin_unlock"]     # noqa: E704
def _ach_criteria():  return _sealed_defs()["ach_criteria"]    # noqa: E704
def _ladder_tracks(): return _sealed_defs()["ladder_tracks"]   # noqa: E704
def _ach_ids():       return _sealed_defs()["_ach_ids"]        # noqa: E704
def _ach_hidden():    return _sealed_defs()["_ach_hidden"]     # noqa: E704
def _ach_rung():      return _sealed_defs()["_ach_rung"]       # noqa: E704
def _skin_ids():      return _sealed_defs()["_skin_ids"]       # noqa: E704

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


def branding_root():
    """Where branding lives: the APP folder, beside the launcher -- NOT inside the library.

    Moved 2026-07-26 (owner decision) for two reasons, the first of which was a live bug.

    It used to be `Path(out_dir) / "branding"`, and out_dir comes from resolve_library_dir(), so
    the library-folder setting shipped the day before silently relocated it. Point the app at a
    different library and every mark, mascot and banner disappeared from its view -- the files
    still on disk in the old folder, the app just no longer looking there. Nobody hit it because
    only one library has ever existed.

    And the "Under the Hood" easter egg depends on a curious user FINDING the empty slot folders.
    They scan the top level of the app directory; they do not go rummaging inside a picture
    library full of month folders and thumbnail caches. Discovery through the filesystem is the
    mechanic, so the folders have to be where a tinkerer's eye lands. Deliberately NOT inside the
    /moonglade package that the naming pass will create either -- that is for code, and user art
    in a package boundary gets treated as code by something eventually.

    Every caller goes through here. Nine sites used to derive this path independently, which is
    exactly how the out_dir coupling above went unnoticed.

    Renamed to the coded goods root 2026-08-21 (the bundle-v2 rewire,
    SCOPE_bundle-v2-contract.md): the on-disk tree a tinkerer finds is coded end
    to end -- role names never appear as folder names -- while the browser keeps
    requesting the friendly /branding/<role>/... URLs and the serve route
    translates once at the boundary (_public_rel_to_coded below)."""
    return Path(__file__).resolve().parent / _GOODS_ROOT_NAME


# ---------------------------------------------------------------------------
# The role -> coded-folder map (bundle-v2, 2026-08-21). Codes exist ONLY on
# disk and inside moonglade.dat; the public URL contract stays /branding/
# <role>/... and every emitted URL keeps the role vocabulary. This dict is the
# SINGLE source of truth for the coded tree -- _seal_rule, the resolver
# callers, the discovery scaffold and the migration all DERIVE their paths
# from it, never retype them (a retyped prefix is how a seal silently fails
# open). `_thumbs` is a LEGACY literal: the badge-thumb cache now lives OUTSIDE
# the tree (badge_cache_dir(): out_dir/gallery/cache/_badges/); the _thumbs/ seal
# deny + the builder's exclusion stay as belt-and-braces for a stale cache left
# behind by an older build -- never coded, never packed, never served.
# ---------------------------------------------------------------------------
_GOODS_ROOT_NAME = "0x676F6F6473"      # hex "goods" -- the on-disk branding root folder name
_GOODS_MID = "3f/00100100"             # 0x3F "?" / Bender's apartment -- shared middle

ROLE_CODE = {
    # role            -> coded folder rel-from-root (POSIX, no trailing slash)
    "banner_main":    _GOODS_MID + "/001",
    "banner_login":   _GOODS_MID + "/009",
    "banner_loom":    _GOODS_MID + "/019",
    "mystery":        _GOODS_MID + "/01473",
    "marks":          _GOODS_MID + "/101",
    "rewards":        _GOODS_MID + "/109",
    "system":         _GOODS_MID + "/5S5",
    "bridge":         _GOODS_MID + "/0xB01",
    "enhance":        _GOODS_MID + "/0xB01/0x534958",
    "emotion":        _GOODS_MID + "/0xB01/0x656d6f7465",
    "badges":         _GOODS_MID + "/A01",
    "mascots":        _GOODS_MID + "/A02",
    "mascots_ach":    _GOODS_MID + "/A02/ach",
    "earned_banners": _GOODS_MID + "/B0N",
    "starfall":       "ABBA/a2c/0x53746172",
    "breadcrumb":     "ABBA/a2c/0x53746172/GONK",
}


def _role_rel(role, *tail):
    """posix rel-from-root for a role file: _role_rel('marks','marks.json') ->
    '3f/00100100/101/marks.json'. No tail -> the role folder's own rel."""
    return "/".join((ROLE_CODE[role],) + tail)


def _role_dir(role):
    """Path: branding_root() / coded role folder."""
    return branding_root() / ROLE_CODE[role]


# The top-level system files rule 2 of the translation maps into the system
# role -- the app's chrome, requested by bare public name since before the
# coded tree existed.
_SYSTEM_TOP_FILES = frozenset({"logo.png", "favicon.png", "favicon.ico",
                               "nel_spinner.png", "login_nel.webp", "login_nel.png"})


def _public_rel_to_coded(rel):
    """Translate ONE incoming public /branding/ rel to its coded on-disk /
    container rel. Applied exactly once, at the serve boundary (the
    /branding/<path:fname> route); everything downstream -- seal, loose file,
    container key -- operates on the CODED rel only, so loose disk path ==
    container key always. First matching rule wins; the order is the contract
    (SCOPE_bundle-v2-contract.md section 2):

      1. the three banner flats -- loose-only at the coded root, returned as-is
         (their shipped-default fallback is a SERVING rule, not a translation)
      2. top-level system files -> system/<name>
      3. bare ee_* filenames -> starfall/<name>
      4. bridge/emotion/<f> -> emotion ; bridge/preset_<f> -> enhance ;
         bridge/<f> -> bridge (the SIX subfolder holds the presets on disk,
         but the front-end asks for them flat under bridge/ -- filename rule)
      5. mascots/ach/<f> -> mascots_ach ; mascots/<f> -> mascots
      6. the single-segment role prefixes -> their coded folder + remainder
      7. _thumbs/<f>, sfx/<f> (no shipped sfx role -- absent -> 404 -> the
         synth-chime fallback) and anything unmatched: returned as-is. A probe
         that guesses a coded path lands here unchanged, so the seal still
         judges it."""
    if rel in _BANNER_FLAT.values():                              # rule 1
        return rel
    if rel in _SYSTEM_TOP_FILES:                                  # rule 2
        return _role_rel("system", rel)
    if "/" not in rel and rel.startswith("ee_"):                  # rule 3
        return _role_rel("starfall", rel)
    if rel.startswith("bridge/"):                                 # rule 4
        f = rel[len("bridge/"):]
        if f.startswith("emotion/"):
            return _role_rel("emotion", f[len("emotion/"):])
        if f.startswith("preset_"):
            return _role_rel("enhance", f)
        return _role_rel("bridge", f)
    if rel.startswith("mascots/"):                                # rule 5
        f = rel[len("mascots/"):]
        if f[:4].lower() == "ach/":   # case-insensitive: the seal is too (Windows FS)
            return _role_rel("mascots_ach", f[4:])
        return _role_rel("mascots", f)
    for role in ("marks", "badges", "rewards", "mystery", "banner_main",
                 "banner_login", "banner_loom", "earned_banners"):  # rule 6
        if rel.startswith(role + "/"):
            return _role_rel(role, rel[len(role) + 1:])
    return rel                                                    # rule 7


def _branding_path(out_dir):
    # Sibling of the art directory, which preserves EXACTLY the arrangement this had inside
    # the library (branding.json next to branding/). Anyone moving an existing setup keeps
    # the same two entries in the same relationship, so the move is a drag of both rather
    # than a reshuffle -- and .gitignore covers the pair with two lines.
    return branding_root().parent / "branding.json"


# ---------------------------------------------------------------------------
# The asset container -- loose-then-container resolution (2026-08-10,
# docs/DECISIONS.md "The asset container, re-scoped from scratch").
#
# moonglade.dat (moonglade_container.py's custom format; built by
# tools/build_container.py, delivered as a GitHub Release asset, never
# committed) carries the app's DEFAULT branding so a fresh install is fully
# dressed while branding/ itself stays empty -- that emptiness is a shipped
# mechanic, not a gap. Resolution order everywhere below: a real loose file
# under branding/ ALWAYS wins; the container only answers when no loose file
# exists. The discovery/adopt sweep (sweep_branding_drops/_adopt_mark) and
# sweep_telemetry's earn check stay deliberately FILESYSTEM-ONLY: detecting a
# genuinely new hand-dropped file is their whole job, and a container-aware
# check there would make an untouched default install look customized.
# ---------------------------------------------------------------------------
def _container_path():
    # Sibling of branding/ and branding.json -- the same app-root, machine-local tree.
    return branding_root().parent / "moonglade.dat"


_container_cache = {"path": None, "mtime": None, "box": None}
_container_lock = threading.Lock()


def _get_container():
    """The current container read handle, or None if no (valid) moonglade.dat
    exists. Cached per (path, mtime) so the TOC parses once, and re-opened
    automatically when the file is replaced -- the downloader's atomic swap and
    a hand-copied update both just work on the next request."""
    p = _container_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        with _container_lock:
            _container_cache.update(path=None, mtime=None, box=None)
        return None
    with _container_lock:
        if _container_cache["path"] == p and _container_cache["mtime"] == mtime:
            return _container_cache["box"]
        box = moonglade_container.open_container(p)
        _container_cache.update(path=p, mtime=mtime, box=box)
        return box


def _branding_bytes(rel):
    """One branding asset's bytes by branding_root()-relative posix path --
    loose file first, container second, None if neither has it."""
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return loose.read_bytes()
    except OSError:
        pass
    box = _get_container()
    return box.get(rel) if box else None


def _branding_exists(rel):
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return True
    except OSError:
        pass
    box = _get_container()
    return bool(box and box.has(rel))


def _branding_mtime(rel):
    """Freshness stamp for cache-invalidation: the loose file's own mtime when
    it exists, else the container FILE's mtime (a whole-container rebuild is the
    only way container-sourced content changes)."""
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return loose.stat().st_mtime
    except OSError:
        pass
    try:
        return _container_path().stat().st_mtime
    except OSError:
        return None


# ---------------------------------------------------------------------------
# The bundle's unlock split, ENFORCED at the serving layer (docs/DECISIONS.md
# "The bundle's unlock split" 2026-07-27 + the "Mascots-in-Branding" correction
# 2026-08-06): achievement-bound art -- badge masters, the per-achievement
# mascot poses under mascots/ach/, the rewards/ tree, the Konami ee_* assets --
# is sealed to the achievement that earns it. System chrome (narrator, login
# companion, wizard poses, tracker spinner/status art, present_* fallbacks)
# stays open: it is the app's default dress, not a reward. Deny answers are
# 404, indistinguishable from "no such file", so the route is not an oracle
# for what art exists.
# ---------------------------------------------------------------------------
# Earned-art gate ids come from the SEALED roster via _ach_ids()/_ach_hidden() (below),
# not a module-level frozenset -- the roster is no longer in this source.


def _seal_rule(rel):
    """(mode, achievement_id) for one branding_root()-relative posix path:
    'open' (serve normally), 'deny' (never serve), or 'earned' (serve only once
    the named achievement is earned).

    Operates on the CODED rel (the serve route translates the public form
    first). Every prefix here is DERIVED from ROLE_CODE, never retyped -- an
    unmatched rel falls through to open, so a hand-typed prefix that drifts
    from the map would silently LEAK sealed art, not 404 it."""
    # The filesystem this guards is case-INSENSITIVE on Windows, so the seal is
    # too: decide on a lowercased copy of the rel and compare against lowercased
    # prefixes. Otherwise a case-variant of a sealed path (e.g. mascots/ACH/<id>)
    # dodges a case-sensitive prefix check, falls through to the fail-open
    # default, and the case-insensitive FS serves the real sealed file anyway.
    # Achievement ids are lowercase, so a lowercased stem matches _ach_ids()
    # directly. (bundle-v2 adversarial-review HIGH finding, 2026-08-21.)
    low = rel.lower()
    rew = ROLE_CODE["rewards"].lower()
    if low in (rew + "/claim.png", rew + "/gift.png"):
        # The D8 exception: the two reward UI icons notify.css fetches for the
        # claim toast/modal -- chrome, not prizes, so they stay open while the
        # rest of the bucket seals (an open pair beats a physical move, which
        # would change the public URLs and force a dist rebuild).
        return ("open", None)
    if low.startswith(rew + "/") or low == rew:
        # rewards/ is pure achievement data with no live front-end consumer (the
        # reward-marker reconciliation is tracked work; gate per-achievement when
        # it lands).
        return ("deny", None)
    if low.startswith("_thumbs/") or low == "_thumbs":
        # _thumbs/ was the badge-thumb cache before it moved out to
        # badge_cache_dir(); a stale one may linger in an older install's tree.
        # /badge-thumb/ is the one sanctioned path so its own hidden-feat gate
        # can't be walked around -- keep denying it here.
        return ("deny", None)
    badges = ROLE_CODE["badges"].lower()
    if low.startswith(badges + "/"):
        aid = low[len(badges) + 1:]
        if aid.endswith(".png"):
            aid = aid[:-4]
        if "/" not in aid and aid in _ach_ids():
            return ("earned", aid)    # full-res master: the celebration fetches it AT earn time
        return ("deny", None)         # the whole bucket is sauce; unknown files stay sealed
    mascots_ach = ROLE_CODE["mascots_ach"].lower()
    if low.startswith(mascots_ach + "/"):
        aid = low[len(mascots_ach) + 1:].rsplit(".", 1)[0]
        if "/" not in aid and aid in _ach_ids():
            return ("earned", aid)
        return ("deny", None)
    if low.startswith(ROLE_CODE["starfall"].lower() + "/"):
        # The whole Starfall bucket -- art, audio, AND the GONK breadcrumb
        # inside it (ROLE_CODE['breadcrumb'] nests under starfall, so this
        # prefix covers it without its own branch).
        return ("earned", "the-konami-code")
    earned_b = ROLE_CODE["earned_banners"].lower()
    if low == earned_b + "/great_library.png":
        return ("earned", "the-great-library")
    if low.startswith(earned_b + "/") or low == earned_b:
        # The rest of the bucket (void_banner.png) is an UNWIRED future reward
        # (achievements #57-60) -- sealed shut until its achievement exists.
        return ("deny", None)
    return ("open", None)


_earned_ids_cache = {"t": 0.0, "ids": frozenset()}
_earned_ids_lock = threading.Lock()


def _earned_achievement_ids(out_dir, db_path, need=None):
    """The set of currently-earned achievement ids -- the seal check for
    achievement-bound art. Cached briefly (one celebration fetches several
    sealed assets back-to-back); a cache answer that would DENY `need` is
    recomputed fresh first, so the fetch that lands milliseconds after the
    earning event never 404s off a stale cache -- staleness can only ever
    delay a denial's recompute, never a legitimate serve."""
    now = time.time()
    with _earned_ids_lock:
        ids = _earned_ids_cache["ids"]
        if now - _earned_ids_cache["t"] < 5.0 and (need is None or need in ids):
            return ids
    metrics = achievement_metrics(db_path)
    metrics.update(telemetry_metrics(out_dir))
    result = compute_achievements(metrics, (),
                                  sets=load_telemetry(out_dir).get("sets", {}))
    ids = frozenset(a["id"] for a in result["achievements"] if a["earned"])
    with _earned_ids_lock:
        _earned_ids_cache.update(t=now, ids=ids)
    return ids


def _seed_loose_manifest(rel):
    """Promote a container-shipped manifest to a real loose file before the
    first read-modify-write against it. Without this, the first custom upload
    on a container-dressed install would start from an EMPTY loose manifest and
    silently shadow every shipped default out of the picker (loose wins). A
    no-op when the loose file already exists or the container lacks it."""
    loose = branding_root() / rel
    if loose.exists():
        return
    box = _get_container()
    data = box.get(rel) if box else None
    if data is None:
        return
    try:
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_bytes(data)
    except OSError:
        pass


# Marks the owner has REMOVED from the roster: mark_12 "Gem Tome" (ruled
# 2026-07-23), and mark_74 (the Winged Crescent, remade as mark_nightfallen for
# bundle-v2 -- the old id's loose file lingers on every full-tree install the
# owner ran before the rename). A tombstone rather than a container rebuild alone
# because the rebuild can't reach everywhere: _seed_loose_manifest promotes the
# container's marks.json to a loose file on first customization, and loose wins
# forever after -- so an install that already seeded keeps a removed mark in its
# picker no matter what a new container ships. Just as important, a tombstoned
# stem reads as KNOWN to sweep_branding_drops, so a still-on-disk loose file is
# NOT re-adopted as a fresh hand-drop (which would delete the original, register
# a custom mark, AND fire the branding feat -- the mark_12 near-miss of
# 2026-08-13, which mark_74 would have repeated on the owner's own upgrade).
_MARK_TOMBSTONES = frozenset({"mark_12", "mark_74"})


def list_marks(out_dir):
    """Marks available on THIS machine: marks/marks.json entries whose .png
    actually exists, resolved loose-then-container (_branding_bytes) so the
    shipped defaults show up even though branding/ itself is deliberately empty
    on a fresh install -- and still empty on a truly bare install with no
    container at all. Tombstoned ids (_MARK_TOMBSTONES) never list."""
    raw = _branding_bytes(_role_rel("marks", "marks.json"))
    if raw is None:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []          # corrupt manifest degrades to "no marks", never a 500
    out = []
    for m in data.get("marks") or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if mid in _MARK_TOMBSTONES:
            continue
        # Disk/container lookups are coded; the emitted URL stays the PUBLIC
        # role form (the /branding/ route translates on the way back in).
        if mid and _branding_exists(_role_rel("marks", mid + ".png")):
            out.append({"id": mid, "label": m.get("label") or mid,
                        "kind": m.get("kind") or "tile",
                        "png": "/branding/marks/%s.png" % mid,
                        "ico": _branding_exists(_role_rel("marks", mid + ".ico"))})
    return out


# The 4 Branding-tab slots Control Panel.dc.html specs beyond Icons & marks
# (banner-main/banner-login/mascots/rewards) -- none had any backend at all
# before this. Deliberately ONE shape for all four (manifest.json + <id>.png
# per slot, same "many stored, one exists-checked" contract list_marks() above
# already established) rather than a bespoke single-file slot vs. a bespoke
# multi-file slot: the F1/F2 SQLite-bundle work only has to learn ONE storage
# shape to take over, not four. Rotating-source selection (Banner-main's own
# "pick FROM a collection" mechanic) is explicitly deferred until that bundle
# work lands (owner call, 2026-08-05) -- for now every slot is just "the
# uploaded assets, one of which is active", identical to how marks/mark
# already relate, so that later mechanic has real asset ids to pick FROM
# instead of a schema migration first.
# banner_loom (12:1 workspace strip) added 2026-08-06 with the Branding-tab rebuild
# (Control Panel.dc.html SLOTS index 5: "Banner - Loom", 1920x160). It joins the two
# 4:1 banners as a real, written-through slot.
#
# mascots/rewards were REMOVED from this tuple 2026-08-13, enforcing the bundle's
# unlock split (docs/DECISIONS.md 2026-07-27 + the 2026-08-06 mascots correction):
# the Branding surface reaches banners + marks only. rewards/ is achievement data,
# and mascots' customization ships later as a named-role checklist over an
# owner-curated SELECTION of system roles -- not a pick-one-active gallery, and not
# the full role list. Until then neither is a slot: the payload doesn't list them,
# the upload/crop/set-active routes refuse them. Their on-disk breadcrumb folders
# stay (see _BRANDING_DISCOVERY_SLOTS).
BRANDING_SLOTS = ("banner_main", "banner_login", "banner_loom")


def _slot_dir(slot):
    # Slot names double as ROLE_CODE keys, so the coded folder falls straight
    # out of the map -- the LOGICAL slot key ("banner_main") stays the JSON/API
    # vocabulary everywhere above this line.
    return _role_dir(slot)


def _asset_transform(it):
    """Normalize one manifest item's crop transform to the design's zoom/cropX/cropY
    model (Control Panel.dc.html:953 -- object-position cropX% cropY% + scale(zoom/100)).
    Back-compat: an item written under the OLD left/center/right crop model (pre
    2026-08-06) maps to the equivalent pan -- left->cropX 0, center->50, right->100 --
    at zoom 100, cropY 50, so an existing install's banners keep displaying unchanged
    until re-tuned."""
    if not isinstance(it, dict):
        it = {}
    if "zoom" in it or "cropX" in it or "cropY" in it:
        z = it.get("zoom", 100); cx = it.get("cropX", 50); cy = it.get("cropY", 50)
    else:
        legacy = {"left": 0, "right": 100}.get(it.get("crop") or "center", 50)
        z, cx, cy = 100, legacy, 50
    try:
        z = max(100, min(int(z), 250))
        cx = max(0, min(int(cx), 100))
        cy = max(0, min(int(cy), 100))
    except (TypeError, ValueError):
        z, cx, cy = 100, 50, 50
    return {"zoom": z, "cropX": cx, "cropY": cy}


def list_slot_assets(out_dir, slot):
    """Uploaded assets for one Branding slot: branding/<slot>/manifest.json
    entries whose .png actually exists. Empty on a fresh install / until that
    slot's first real upload, exactly like list_marks() above. Each asset carries
    its zoom/cropX/cropY transform (normalized, legacy crop migrated)."""
    if slot not in BRANDING_SLOTS:
        return []
    raw = _branding_bytes(_role_rel(slot, "manifest.json"))
    if raw is None:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []          # corrupt manifest degrades to "no assets", never a 500
    out = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "")
        if iid and _branding_exists(_role_rel(slot, iid + ".png")):
            out.append({"id": iid, **_asset_transform(it),
                        "png": "/branding/%s/%s.png" % (slot, iid)})
    return out


def _slot_active_path(out_dir):
    # Sibling of branding.json/branding/, same machine-local git-ignored tree --
    # kept in its OWN file rather than folded into branding.json so that file's
    # existing read-modify-write cycle (load_branding/save_branding, mark+anim
    # only) can never clobber slot-active state it doesn't know about.
    return branding_root().parent / "branding_slots.json"


def load_slot_active(out_dir):
    """Which uploaded asset (by id) is the ACTIVE one per slot -- the same
    relationship branding.json's own "mark" field already has to list_marks():
    many stored, one worn. Self-heals exactly like load_branding() does for
    "mark": a recorded active id that no longer exists on disk (deleted file,
    corrupt manifest) falls back to the first real asset, or None."""
    active = {}
    try:
        raw = json.loads(_slot_active_path(out_dir).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            active = {k: str(v) for k, v in raw.items() if k in BRANDING_SLOTS and v}
    except (OSError, ValueError):
        pass
    for slot in BRANDING_SLOTS:
        have = {a["id"] for a in list_slot_assets(out_dir, slot)}
        if active.get(slot) not in have:
            active[slot] = next(iter(have), None)
    return active


def save_slot_active(out_dir, active):
    _slot_active_path(out_dir).write_text(
        json.dumps({k: v for k, v in active.items() if v}, indent=2), encoding="utf-8")


def add_slot_asset(out_dir, slot, png_bytes, zoom=100, cropx=50, cropy=50):
    """Save a new upload into one Branding slot and make it the active one.
    Returns the new asset dict, or None for an unknown slot. Caller (the
    /api/branding/slot route) is responsible for making sure png_bytes is a
    real PNG before this is called -- this function just persists it. New
    uploads start at the neutral transform (zoom 100, centered) -- the
    equivalent of the design's own defaults."""
    if slot not in BRANDING_SLOTS:
        return None
    sdir = _slot_dir(slot)
    sdir.mkdir(parents=True, exist_ok=True)
    # First write against a container-dressed slot: promote the shipped manifest
    # loose first, or this upload would shadow every default out of the picker.
    _seed_loose_manifest(_role_rel(slot, "manifest.json"))
    try:
        data = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
        items = list(data.get("items") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        items = []
    new_id = secrets.token_hex(4)
    (sdir / (new_id + ".png")).write_bytes(png_bytes)
    t = _asset_transform({"zoom": zoom, "cropX": cropx, "cropY": cropy})
    items.append({"id": new_id, **t})
    (sdir / "manifest.json").write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
    active = load_slot_active(out_dir)
    active[slot] = new_id
    save_slot_active(out_dir, active)
    _write_banner_flat(out_dir, slot)   # the new upload is now active -> display it
    return {"id": new_id, **t, "png": "/branding/%s/%s.png" % (slot, new_id)}


def set_slot_crop(out_dir, slot, item_id, zoom=None, cropx=None, cropy=None):
    """Update one already-uploaded asset's zoom/cropX/cropY transform (Control
    Panel.dc.html's three banner sliders -- zoom 100-250, cropX/cropY 0-100).
    Any field left None keeps its stored value. False for an unknown slot/item,
    never a 500. Widened 2026-08-06 from the old 3-value left/center/right crop."""
    if slot not in BRANDING_SLOTS:
        return False
    sdir = _slot_dir(slot)
    # Adjusting a shipped default's crop is a WRITE -- promote the manifest
    # loose first so the edit lands on a real file (P3-review lesson: without
    # this, retuning a container-shipped banner just failed).
    _seed_loose_manifest(_role_rel(slot, "manifest.json"))
    try:
        data = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return False
    if not isinstance(items, list):
        return False
    found = False
    for it in items:
        if isinstance(it, dict) and str(it.get("id")) == str(item_id):
            cur = _asset_transform(it)
            merged = {
                "zoom": cur["zoom"] if zoom is None else zoom,
                "cropX": cur["cropX"] if cropx is None else cropx,
                "cropY": cur["cropY"] if cropy is None else cropy,
            }
            norm = _asset_transform(merged)
            it.pop("crop", None)          # drop the legacy field once re-tuned
            it.update(norm)
            found = True
    if not found:
        return False
    (sdir / "manifest.json").write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
    if load_slot_active(out_dir).get(slot) == str(item_id):
        _write_banner_flat(out_dir, slot)   # the transform is baked into the displayed flat
    return True


def set_slot_active(out_dir, slot, item_id):
    """Mark an already-uploaded asset as the active one for its slot. False for
    an unknown slot or an item_id that isn't a real asset in it -- there is no
    "clear to none" here on purpose: the design never models deselecting a slot
    back to empty, only picking among what's uploaded, and load_slot_active()'s
    own self-heal (falling back to the first real asset when nothing is
    recorded) would silently undo a stored None anyway, since the two cases
    look identical on disk."""
    if slot not in BRANDING_SLOTS:
        return False
    if not item_id or item_id not in {a["id"] for a in list_slot_assets(out_dir, slot)}:
        return False
    active = load_slot_active(out_dir)
    active[slot] = item_id
    save_slot_active(out_dir, active)
    _write_banner_flat(out_dir, slot)
    return True


def _mark_earned(out_dir, db_path, ach_id):
    """Whether one specific achievement id is currently earned -- runs the exact
    same compute_achievements() pipeline /api/achievements itself uses, so a
    custom-mark upload can never disagree with what the Branding tab already
    shows unlocked. Pure read (no save_ach_state call), so unlike that route it
    needs no lock -- nothing here can race a concurrent write."""
    metrics = achievement_metrics(db_path)
    metrics.update(telemetry_metrics(out_dir))
    state = load_ach_state(out_dir)
    result = compute_achievements(metrics, state.get("seen"),
                                   sets=load_telemetry(out_dir).get("sets", {}))
    return any(a["id"] == ach_id and a["earned"] for a in result["achievements"])


def add_custom_mark(out_dir, png_bytes, label="Custom mark"):
    """Save The Great Library's custom-mark upload into branding/marks/ and make
    it the active mark. Same manifest shape list_marks() already reads
    (marks.json + <id>.png) -- one new kind:'upload' entry, not a new storage
    concept, matching how add_slot_asset() extends the identical contract for
    banner slots. Unlike _adopt_mark() (the filesystem-drop path, which derives
    an id from the dropped filename), this is a real upload with a random id,
    same convention add_slot_asset() uses for banner uploads.

    There is only ONE custom-mark slot (the design's single 6th tile), so a
    second upload REPLACES the first -- any existing kind:'upload' entry (and
    its .png) is dropped here first, rather than accumulating orphaned marks
    the picker would need de-duping logic to hide."""
    mdir = _role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    _seed_loose_manifest(_role_rel("marks", "marks.json"))   # keep shipped defaults in the picker
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        marks = []
    for old in [m for m in marks if isinstance(m, dict) and (m.get("kind") or "tile") == "upload"]:
        old_png = mdir / (str(old.get("id")) + ".png")
        if old_png.exists():
            old_png.unlink()
    marks = [m for m in marks if not (isinstance(m, dict) and (m.get("kind") or "tile") == "upload")]
    new_id = secrets.token_hex(4)
    (mdir / (new_id + ".png")).write_bytes(png_bytes)
    marks.append({"id": new_id, "label": label, "kind": "upload"})
    (mdir / "marks.json").write_text(json.dumps({"marks": marks}, indent=2), encoding="utf-8")
    cfg = load_branding(out_dir)
    cfg["mark"] = new_id
    save_branding(out_dir, cfg)
    return {"id": new_id, "label": label, "kind": "upload",
            "png": "/branding/marks/%s.png" % new_id, "ico": False}


def remove_custom_mark(out_dir, mark_id):
    """Remove one uploaded custom mark. Refuses to touch a non-upload (built-in
    tile) mark -- the design's Replace/Remove chips only ever appear next to the
    uploaded one, but this guard makes that true at the data layer too, not just
    the UI. Reverts the active mark back to the default logo if the removed one
    was the one currently worn."""
    mdir = _role_dir("marks")
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return False
    target = next((m for m in marks if isinstance(m, dict) and str(m.get("id")) == str(mark_id)
                   and (m.get("kind") or "tile") == "upload"), None)
    if target is None:
        return False
    keep = [m for m in marks if m is not target]
    (mdir / "marks.json").write_text(json.dumps({"marks": keep}, indent=2), encoding="utf-8")
    png = mdir / (str(mark_id) + ".png")
    if png.exists():
        png.unlink()
    cfg = load_branding(out_dir)
    if cfg.get("mark") == str(mark_id):
        cfg["mark"] = "logo"
        save_branding(out_dir, cfg)
    return True


def branding_slots_payload(out_dir):
    """The Branding tab's full slot state -- assets + which one is active, per
    slot -- in the one shape both /api/branding and /api/panel/summary hand to
    the React BrandingTab. A single function so both routes can never disagree
    about what a slot looks like."""
    active = load_slot_active(out_dir)
    return {slot: {"assets": list_slot_assets(out_dir, slot), "active": active.get(slot)}
            for slot in BRANDING_SLOTS}


# "Under the Hood" intended flow (docs/DECISIONS.md, 2026-07-26, owner-confirmed
# 2026-08-05): a fresh install ships the branding slot folders EMPTY, with a
# single README breadcrumb the only hint. A curious user drops a raw PNG/JPEG
# directly into one of them; the app ADOPTS it into that slot on its own --
# no marks.json to hand-author, no upload UI. That adoption is what fires the
# hidden feat and unlocks the Control Panel Branding tab. The earn path can
# never be "use the Branding tab's own upload API" -- that tab sits BEHIND
# this exact unlock -- so this has to work by scanning raw filesystem drops,
# not by extending the authenticated upload routes above.
# Fallback breadcrumb text ONLY (container absent): the real README content
# (cryptic Nel ASCII + this line) is a SEALED asset materialized by
# ensure_branding_discovery_tree -- spoiler hygiene keeps it out of this
# public source.
_BRANDING_README = "Maybe something goes in here.\n"
# mascots/rewards are listed here EXPLICITLY even though they are no longer
# BRANDING_SLOTS (the 2026-08-13 unlock-split enforcement): their empty folders
# are part of the tinkerer-discovery landscape and existing installs have them,
# so the on-disk breadcrumb tree keeps the same six roles (now coded). A drop
# there still does nothing (the sweep only ever adopts from _SWEEPABLE_SLOTS +
# marks).
_BRANDING_DISCOVERY_SLOTS = BRANDING_SLOTS + ("mascots", "rewards", "marks")


def _migrate_legacy_branding_root():
    """One-time move of an existing install's OLD role-named `branding/` tree
    into the coded goods tree (bundle-v2, SCOPE_bundle-v2-contract.md section
    5). MOVE only, NEVER delete -- renaming the root would otherwise orphan
    every real upload an existing install has (custom marks, banner slots, the
    rendered flats). Rules:

      - the six role folders' files -> their coded dirs (recursive, so the old
        mascots/ach/ nesting lands under the coded ach folder too);
      - old top-level loose files route through _public_rel_to_coded: the
        three banner flats stay top-level at the coded root, system files /
        ee_* land in their coded homes (leaving them at the coded top would
        strand a working override where the resolver no longer looks);
      - anything unrecognized STAYS PUT (flag-to-owner territory, per the
        standing stray-copy rule), and a destination that already exists is
        never overwritten -- the source stays put and is logged;
      - emptied old folders are removed; the old root goes only if COMPLETELY
        empty. One log line per move via the standard logger.

    A no-op on fresh installs (no old root at all)."""
    import logging as _logging
    import shutil
    old = branding_root().parent / "branding"
    if not old.is_dir():
        return
    log = _logging.getLogger(__name__)

    def _move(src, dst):
        if dst.exists():
            log.warning("branding migration: NOT moving %s (destination %s already exists)",
                        src, dst)
            return
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            log.info("branding migration: moved %s -> %s", src, dst)
        except OSError:
            log.warning("branding migration: failed to move %s -> %s",
                        src, dst, exc_info=True)

    for role in ("banner_main", "banner_login", "banner_loom",
                 "marks", "mascots", "rewards"):
        src_dir = old / role
        if not src_dir.is_dir():
            continue
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                _move(p, _role_dir(role) / p.relative_to(src_dir))
    try:
        top = sorted(old.iterdir())
    except OSError:
        top = []
    for p in top:
        if not p.is_file():
            continue
        coded = _public_rel_to_coded(p.name)
        if p.name in _BANNER_FLAT.values() or coded != p.name:
            _move(p, branding_root() / coded)
        # else: unrecognized (the old README.txt, stray notes) -- stays put.
    # Sweep away what emptied, deepest-first; rmdir refuses anything non-empty,
    # which is exactly the "removed only if left completely empty" contract.
    for d in sorted((q for q in old.rglob("*") if q.is_dir()), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        old.rmdir()
    except OSError:
        pass
    # Anything left behind was unrecognized (not a role folder, not a flat/system
    # /ee_ file) so it stayed put by design -- but surface it rather than let it
    # 404 silently, so the owner can move a stray by hand. (Re-logs each start
    # while the leftover remains; that is a persistent, accurate nudge.)
    if old.is_dir():
        leftovers = [str(p.relative_to(old)) for p in old.rglob("*") if p.is_file()]
        if leftovers:
            log.warning("branding migration: %d file(s) left unmigrated in the old "
                        "branding/ folder (unrecognized -- move by hand if wanted): %s",
                        len(leftovers), ", ".join(sorted(leftovers)[:20]))


def ensure_branding_discovery_tree():
    """Create the empty, coded slot folders + the one GONK breadcrumb, so there
    is actually something for a tinkerer to find. Idempotent and additive only
    -- never touches a folder or file that already exists, so it is safe to
    call on every server start regardless of what's already on disk (the
    owner's own real tree, a returning install with real uploads, ...). Runs
    the one-time legacy migration first so an old install's real files land in
    the coded dirs before the empties go down. The README's content is
    materialized from the SEALED asset (spoiler hygiene: the cryptic Nel ASCII
    never appears in this public source); a container-less install gets the
    plain one-liner. The old root-level README is no longer written. Called
    once at app startup (create_app), not per-request."""
    _migrate_legacy_branding_root()
    for slot in _BRANDING_DISCOVERY_SLOTS:
        _role_dir(slot).mkdir(parents=True, exist_ok=True)
    crumb_dir = _role_dir("breadcrumb")
    readme = crumb_dir / "README.txt"
    if not readme.exists():
        try:
            crumb_dir.mkdir(parents=True, exist_ok=True)
            raw = _branding_bytes(_role_rel("breadcrumb", "README.txt"))
            if raw is not None:
                readme.write_bytes(raw)
            else:
                readme.write_text(_BRANDING_README, encoding="utf-8")
        except OSError:
            pass


def _adopt_dropped_file(path):
    """Re-encode a raw dropped image (PNG/JPEG/anything Pillow can read) into
    real PNG bytes, or None if it isn't a readable image at all -- the same
    defense-in-depth the authenticated upload route above applies, just
    against a file that arrived by hand instead of by POST."""
    try:
        from PIL import Image
        import io
        im = Image.open(path)
        im.load()
        buf = io.BytesIO()
        im.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _adopt_mark(out_dir, raw_stem, png_bytes):
    """Register a raw dropped file into marks.json + write its .png, then make
    it the active mark -- the marks-folder half of sweep_branding_drops()'s
    auto-adopt (marks predate BRANDING_SLOTS and keep their own established
    list_marks()/marks.json shape rather than being folded into the newer
    per-slot manifest convention)."""
    mdir = _role_dir("marks")
    mid = re.sub(r"[^a-z0-9_-]+", "-", raw_stem.lower()).strip("-")[:40] or "custom"
    # Tombstoned ids count as taken: adopting a drop AS a tombstoned id would
    # register a mark list_marks() then refuses to show.
    have = {m["id"] for m in list_marks(out_dir)} | set(_MARK_TOMBSTONES)
    if mid in have:
        mid = (mid + "-" + secrets.token_hex(3))[:40]
    _seed_loose_manifest(_role_rel("marks", "marks.json"))   # keep shipped defaults in the picker
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        marks = []
    marks.append({"id": mid, "label": mid.replace("-", " "), "kind": "tile"})
    (mdir / "marks.json").write_text(json.dumps({"marks": marks}, indent=2), encoding="utf-8")
    (mdir / (mid + ".png")).write_bytes(png_bytes)
    cfg = load_branding(out_dir)
    cfg["mark"] = mid
    save_branding(out_dir, cfg)


# SAFETY, 2026-08-05: mascots/ and rewards/ are NOT empty user-customizable
# buckets -- they already hold a family of specifically-named, role-bound
# files real shipped code reads by exact filename (the narrator/login/power-
# modal mascots, the claim icon, and a per-achievement ach/<id>.png chain that
# has no fixed, enumerable list). The original version of this sweep had no
# awareness of that and would have adopted-then-DELETED every one of those
# files the first time it ran against an install that actually has them --
# caught before it ever ran against real assets, but only just. Until
# mascots/rewards get a real design (named-role overrides, most likely, not
# a manifest-of-many-pick-one-active gallery like the other two slots), the
# sweep only ever touches the two slots that map cleanly onto a real,
# already-established single flat file: banner_main -> the root flat
# banner.png and banner_login -> login-banner.png (WIRED to write those exact
# files as of 2026-08-06 -- see _write_banner_flat below; owner call: "Yes,
# seems obvious").
_SWEEPABLE_SLOTS = ("banner_main", "banner_login", "banner_loom")

# The flat files the header/login/Loom templates read directly (the header's
# <img src="/branding/banner.png">, the login page's login-banner.png, and the
# Loom's workspace strip). The slot system stores MANY assets; these flats are
# the ONE the app displays -- so every path that changes which asset is active
# (upload, pick-active, re-crop the active one, a raw drop the sweep adopts)
# re-renders its slot's flat.
_BANNER_FLAT = {"banner_main": "banner.png", "banner_login": "login-banner.png",
                "banner_loom": "banner-loom.png"}
# The SHIPPED default banner per slot -- a sealed container asset inside the
# slot's own coded folder, served only when no loose flat exists (bundle-v2:
# the coded tree ships real default banners; the old repo tree shipped the
# slots empty, so brand_context's flat-only check left a fresh install bare).
# Filenames as the tree actually carries them -- banner_loom's is hyphenated.
_BANNER_FLAT_DEFAULT = {"banner_main": "banner_main.png",
                        "banner_login": "banner_login.png",
                        "banner_loom": "banner-loom.png"}


def _flat_default_rel(slot):
    """Coded rel of one slot's shipped default banner (the rule-8 fallback)."""
    return _role_rel(slot, _BANNER_FLAT_DEFAULT[slot])
# The output aspect each banner flat is cropped to (width / height). banner_loom
# is the 12:1 workspace strip added with the Branding-tab rebuild.
_BANNER_RATIO = {"banner_main": 4.0, "banner_login": 4.0, "banner_loom": 12.0}
# Canonical output pixel size per slot (the DC's own spec strings: 1920x480,
# 1920x160). The saved flat is resized to this so downstream CSS never upsamples
# an oddly-sized source.
_BANNER_OUT = {"banner_main": (1920, 480), "banner_login": (1920, 480),
               "banner_loom": (1920, 160)}


def _banner_window(w, h, target_ar, zoom, cropx, cropy):
    """The source-pixel crop box that reproduces the design's live preview EXACTLY
    (Control Panel.dc.html:953): an object-fit:cover image with
    `object-position: cropX% cropY%`, `transform: scale(zoom/100)`,
    `transform-origin: cropX% cropY%`. WYSIWYG matters here -- the owner tunes the
    sliders watching that preview, so the flat must match it, not merely approximate.

    Derivation: model a display frame of the target aspect, replicate the CSS
    (cover-fit, then object-position, then the scale about the crop-origin), and map
    the frame's four corners back into source-pixel space; their bounding rectangle
    is the visible window. Returns (left, top, right, bottom) clamped to the source.
    """
    z = max(1.0, zoom / 100.0)
    px, py = cropx / 100.0, cropy / 100.0
    # A frame of the target aspect, sized in the source's own units (height = h) so
    # the cover math stays in familiar pixels; only the ratio matters.
    FH = float(h)
    FW = target_ar * FH
    sc = max(FW / w, FH / h)                      # object-fit: cover
    disp_w, disp_h = w * sc, h * sc
    over_x, over_y = disp_w - FW, disp_h - FH     # >= 0
    img_l, img_t = -px * over_x, -py * over_y     # object-position placement
    ox, oy = px * FW, py * FH                     # transform-origin in frame coords

    def src(fx, fy):
        # undo scale(z) about (ox,oy), then undo cover placement -> source px
        qx = ox + (fx - ox) / z
        qy = oy + (fy - oy) / z
        return (qx - img_l) / sc, (qy - img_t) / sc

    corners = [src(0, 0), src(FW, 0), src(0, FH), src(FW, FH)]
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
    l, t, r, b = min(xs), min(ys), max(xs), max(ys)
    # clamp into the source, then re-fit the exact target aspect inside the clamp so
    # the saved file's aspect is precise even at an edge-panned extreme.
    l, t = max(0.0, l), max(0.0, t)
    r, b = min(float(w), r), min(float(h), b)
    cw, ch = r - l, b - t
    if cw <= 0 or ch <= 0:
        return (0, 0, w, h)
    if cw / ch > target_ar:                       # too wide -> trim width, keep centre
        nw = ch * target_ar; l += (cw - nw) / 2; r = l + nw
    else:                                         # too tall -> trim height
        nh = cw / target_ar; t += (ch - nh) / 2; b = t + nh
    # Size-preserving integer rounding: round the origin, derive the far edge from the
    # SIZE (min 1px). Rounding all four edges independently can collapse a sub-pixel-
    # tall box to zero height (round(1.5)=2 and round(2.5)=2 under banker's rounding),
    # which made Pillow produce an empty crop for small sources.
    li, ti = int(round(l)), int(round(t))
    wi = max(1, int(round(r - l))); hi = max(1, int(round(b - t)))
    li = max(0, min(li, w - wi)); ti = max(0, min(ti, h - hi))
    return (li, ti, li + wi, ti + hi)


def _render_banner_flat(slot, raw, zoom=100, cropx=50, cropy=50):
    """The ratio/size pipeline itself: bake raw image bytes into `slot`'s flat
    file via _banner_window (the design's own preview math) at the slot's
    canonical output size. Shared by _write_banner_flat (the active-asset path)
    and the earned-banner apply route (sealed bytes straight from the
    container) so the two writers can never drift. The rendered FLAT is always
    written loose at the coded ROOT's top level: it's derived per-install
    state, not shipped art. Fails soft (False), never a 500."""
    name = _BANNER_FLAT.get(slot)
    if not name or raw is None:
        return False
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        w, hh = im.size
        ar = _BANNER_RATIO.get(slot, 4.0)
        box = _banner_window(w, hh, ar, zoom, cropx, cropy)
        crop = im.crop(box)
        ow, oh = _BANNER_OUT.get(slot, (1920, int(round(1920 / ar))))
        crop = crop.resize((ow, oh), Image.LANCZOS)
        branding_root().mkdir(parents=True, exist_ok=True)
        crop.save(branding_root() / name, format="PNG")
        return True
    except Exception:
        return False


def _write_banner_flat(out_dir, slot):
    """Render a banner slot's ACTIVE asset over its real flat file, baking the
    stored zoom/cropX/cropY transform in via _render_banner_flat above. That is
    what makes the banner sliders REAL -- the transform was stored metadata
    nothing rendered before. Fails soft (False), never a 500: a banner that
    fails to render leaves the previous flat in place, which still displays --
    strictly better than a broken header image."""
    if slot not in _BANNER_FLAT:
        return False
    active_id = load_slot_active(out_dir).get(slot)
    a = next((x for x in list_slot_assets(out_dir, slot) if x["id"] == active_id), None)
    if not a:
        return False
    # The active asset may be a shipped default living only in the container --
    # read via the resolution layer (coded rel), not a raw path.
    raw = _branding_bytes(_role_rel(slot, a["id"] + ".png"))
    return _render_banner_flat(slot, raw, a.get("zoom", 100),
                               a.get("cropX", 50), a.get("cropY", 50))


def sweep_branding_drops(out_dir):
    """Scan the SWEEPABLE branding slot folders (_SWEEPABLE_SLOTS + marks) for
    a raw file that arrived by hand and isn't already a known asset, adopt
    each one found, and fire the 'Under the Hood' hidden feat if anything was
    adopted. Runs on every /api/achievements fetch rather than
    sweep_telemetry()'s once-a-day cadence -- a real find deserves to pay off
    on the next reload, not up to a day later. Cheap: a handful of small
    directory listings, matching list_marks()/list_quarantined()'s own "stays
    cheap" precedent. Returns True if anything was adopted this call."""
    adopted = False
    for slot in _SWEEPABLE_SLOTS:
        sdir = _slot_dir(slot)
        if not sdir.is_dir():
            continue
        known = {a["id"] for a in list_slot_assets(out_dir, slot)}
        try:
            entries = sorted(sdir.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file() or p.name == "manifest.json" or p.stem in known:
                continue
            png_bytes = _adopt_dropped_file(p)
            if png_bytes is None:
                continue
            # Delete the raw drop BEFORE writing the adopted copy, not after: the
            # adopted asset's own filename can legitimately collide with the raw
            # drop's path (add_slot_asset uses a random id, but a stem-derived id
            # elsewhere -- see _adopt_mark below -- routinely does), and deleting
            # afterward would then remove the file it just wrote instead of the
            # original. png_bytes is already read into memory, so the source file
            # is safe to remove first regardless of what gets written next.
            try:
                p.unlink()
            except OSError:
                pass
            add_slot_asset(out_dir, slot, png_bytes)   # neutral transform (zoom 100, centered)
            adopted = True
    mdir = _role_dir("marks")
    if mdir.is_dir():
        known = {m["id"] for m in list_marks(out_dir)}
        try:
            entries = sorted(mdir.iterdir())
        except OSError:
            entries = []
        for p in entries:
            # A tombstoned stem is KNOWN, not a fresh drop. Without this, delisting
            # a mark makes its still-on-disk loose file invisible to the `known` set
            # and the sweep ADOPTS it -- delete-and-re-encode of a real asset, the
            # exact 2026-08-05 near-miss. Caught live 2026-08-13 on the mark_12
            # tombstone: the owner's own mark_12.png got eaten on first page load.
            if (not p.is_file() or p.name == "marks.json" or p.suffix.lower() == ".ico"
                    or p.stem in known or p.stem in _MARK_TOMBSTONES):
                continue
            png_bytes = _adopt_dropped_file(p)
            if png_bytes is None:
                continue
            try:              # delete first -- see the identical note above
                p.unlink()
            except OSError:
                pass
            _adopt_mark(out_dir, p.stem, png_bytes)
            adopted = True
    if adopted:
        telem_flag("branding_custom_file", out_dir=out_dir)
    return adopted


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
    # A banner shows when the per-install loose flat exists OR the shipped
    # sealed default does (the serve route's rule-8 fallback renders the
    # latter, so this flag has to agree with what /branding/banner.png serves).
    has_banner = (_branding_exists("banner.png")
                  or _branding_exists(_flat_default_rel("banner_main")))
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
    ico = _role_dir("marks") / (str(mark_id) + ".ico")
    if not ico.exists():
        # A container-shipped .ico must become a REAL file: PowerShell's
        # CreateShortcut reads IconLocation straight off disk, servable bytes
        # aren't enough. Materialized into a git-ignored cache, regenerable.
        # (The cache subfolder keeps its plain 'marks' name -- it lives outside
        # the goods root, so it is not part of the coded tree.)
        raw = _branding_bytes(_role_rel("marks", str(mark_id) + ".ico"))
        if raw is not None:
            cache = branding_root().parent / "_container_cache" / "marks"
            try:
                cache.mkdir(parents=True, exist_ok=True)
                ico = cache / (str(mark_id) + ".ico")
                ico.write_bytes(raw)
            except OSError:
                raise RuntimeError("no .ico cut for %s yet (branding/marks/)" % mark_id)
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
                       capture_output=True, text=True, timeout=30,
                       creationflags=_NO_WINDOW)
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


# The rung map is derived from the sealed roster once per load; read via _ach_rung().


def achievement_points(a):
    """Rung-scaled score for one achievement: tier base + 5*(rung-1). Feats score
    0 by design (pure bragging-rights flair), so the points total never reveals a
    hidden feat."""
    if a.get("tier") == "feat":
        return 0
    return _TIER_POINTS.get(a.get("tier"), 0) + 5 * (_ach_rung().get(a["id"], 1) - 1)


# Closed-universe set achievements -> a per-criterion checklist (WHICH members are done),
# not just an N/M count. Maps achievement id -> (telemetry set key, ordered
# [(member, label)] universe). ONLY closed sets belong here; open-ended distinct-counts
# (loras, enhance_workflows) have no finite universe and stay count-only. `video_modes`
# tracks only i2v/flf/r2v (V2V is deliberately not counted -- see the loom/generate bump).
# The closed-set criteria labels are SEALED in the container too; read via _ach_criteria()
# -> {aid: [set_key, [[member, label], ...]]} (JSON tuples arrive as lists, unpacked below).


def achievement_criteria(sets):
    """For each closed-universe set achievement, which of its criteria are met. `sets` =
    telemetry.json's 'sets' block (id -> list of members). Returns
    {achievement_id: [{"key","label","done"}, ...]}. Pure + fail-soft: a missing or
    non-list set reads as 'nothing done' rather than raising."""
    out = {}
    for aid, (set_key, universe) in _ach_criteria().items():
        have = sets.get(set_key) if isinstance(sets, dict) else None
        have = set(have) if isinstance(have, list) else set()
        out[aid] = [{"key": k, "label": lbl, "done": k in have} for k, lbl in universe]
    return out


def compute_achievements(metrics, seen=(), sets=None):
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
    # per-criterion checklists for the closed-universe set achievements (only when the
    # caller supplies the raw telemetry sets; tests that pass metrics-only skip it)
    crit = achievement_criteria(sets) if sets is not None else {}
    earned_skins = set()
    achs = []
    for a in _roster():
        cur = int(metrics.get(a["metric"], 0) or 0)
        earned = cur >= a["threshold"]
        if earned and a.get("skin"):
            earned_skins.add(a["skin"])
        entry = {
            "id": a["id"], "name": a["name"], "icon": a["icon"], "desc": a["desc"],
            "tier": a["tier"], "metric": a["metric"], "threshold": a["threshold"],
            "current": cur, "earned": earned, "skin": a.get("skin", ""),
            "bucket": a.get("bucket", "ladder"), "hidden": bool(a.get("hidden")),
            "banner_reward": bool(a.get("banner_reward")), "points": achievement_points(a),
            "roast": a.get("roast", ""), "roast_nsfw": a.get("roast_nsfw", ""),
        }
        if a.get("bucket") == "ladder":
            entry["track"] = a["track"]
            entry["rung"] = a["rung"]
            entry["rungs_total"] = a["rungs_total"]
        if a["id"] in crit:
            entry["criteria"] = crit[a["id"]]
        achs.append(entry)
    by_id = {x["id"]: x for x in achs}
    # post-pass: Skin Changer counts unlocked skins (free ones + this pass's earns)
    sc = by_id.get("skin-changer")
    if sc:
        n = sum(1 for s in _skins() if s.get("free") or s["id"] in earned_skins)
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
              "earned": bool(s.get("free")) or s["id"] in earned_skins,
              "unlock": _skin_unlock().get(s["id"])}
             for s in _skins()]
    newly = [a["id"] for a in achs if a["earned"] and a["id"] not in seen]
    earned_points = sum(x["points"] for x in achs if x["earned"])
    possible_points = sum(x["points"] for x in achs)
    return {"achievements": achs, "skins": skins, "ladders": _ladder_tracks(), "newly": newly,
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
        # Preserve the stored skin id verbatim -- do NOT coerce it to the default
        # just because it isn't in the CURRENT _skin_ids(). That set comes from the
        # sealed container, so during an undressed window (the pack still
        # downloading, or briefly unreadable) it collapses to the two free skins;
        # coercing here would rewrite a legitimately-earned skin to "moonglade" and
        # the next save_ach_state would PERSIST that reset -- permanent loss for a
        # purely cosmetic value the container has nothing to do with. Every skin's
        # CSS is hard-coded server-side (html[data-skin=...]) and applied client-
        # side, so an id we can't validate right now still renders correctly; a
        # genuinely unknown id just renders the default tokens, harmlessly. The
        # write gate (/api/skin: earned + known) is what refuses a bogus/locked
        # skin -- read is trust, write is checked. (Adversarial M1, 2026-08-22.)
        skin = d.get("skin") if isinstance(d.get("skin"), str) and d.get("skin") else "moonglade"
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


def badge_cache_dir(out_dir):
    """Where the regenerable badge-thumb cache lives: `out_dir/gallery/cache/_badges/`.
    OUTSIDE the coded branding tree on purpose (SCOPE_bundle-v2-branding constraint 3:
    the tree must keep reading as the empty scaffold + breadcrumb -- a folder of PNGs
    named by achievement id beside the coded folders gave the tree's purpose away), and
    under `gallery/`, which every filesystem walker already skips wholesale (organize,
    import, audit, dedup -- Invariant 6), so the cache can never be catalogued as art.
    `gallery/cache/` is the general home for regenerable caches (owner, 2026-08-21: a
    cache container may follow); add siblings beside `_badges`, not elsewhere."""
    return Path(out_dir) / "gallery" / "cache" / "_badges"


def _badge_thumb(out_dir, aid, size=256):
    """Lazily cache a ~size px copy of a badge master and return its Path (or PNG bytes when the cache dir can't be written). The 57
    badge masters are 2000px (~300 MB total); the Folio of Honors renders these thumbs so
    a full open doesn't pull the masters. Masters stay the source of truth; the cache
    self-heals when a master is re-cut (mtime check). Falls back to the master on any
    trouble, so a tile always resolves to *something*. Cache home: badge_cache_dir()."""
    rel = _role_rel("badges", aid + ".png")
    if not _branding_exists(rel):
        return None
    src = _role_dir("badges") / (aid + ".png")
    dst = badge_cache_dir(out_dir) / ((aid + ".png") if size == 256 else (aid + "." + str(size) + ".png"))
    src_mtime = _branding_mtime(rel)   # loose master's own mtime, or the container file's
    try:
        if dst.is_file() and src_mtime is not None and dst.stat().st_mtime >= src_mtime:
            return dst
        raw = _branding_bytes(rel)
        if raw is None:
            return None
        dst.parent.mkdir(parents=True, exist_ok=True)
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((size, size))
        im.save(dst)
        return dst
    except Exception:
        if src.is_file():
            return src         # loose master exists -- serve it full-size
        # Container-sourced master AND a cache we couldn't write (unwritable dir,
        # read-only mount, full disk): don't fall through to a 404 -> emoji. Hand
        # bytes back for the route to serve from memory -- resized if PIL can, else
        # the raw master (adversarial-review 2026-08-22).
        raw = _branding_bytes(rel)
        if raw is None:
            return None
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return raw


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


def first_sync_complete(out_dir, db_path):
    """True once the first FULL library sync has finished -- the gate that stops the
    achievement unlock toasts from firing mid-first-sync. `first-light` is metric
    images>=1, so without this gate it pops the instant image #1 lands, seconds into a
    fresh install's very first sync (and every image rung crosses the same way). While
    this is False, /api/achievements withholds `newly` and leaves `seen` untouched, so
    the rungs earned during the first sync fire together AFTER it completes, not during.

    Set by `--sync`'s completion (telem flag 'first_sync_done') -- the CLI path AND the
    wizard's sync job both run `--sync`, so one setter covers both.

    Backfill for PRE-EXISTING installs so they neither suppress nor spam: keyed on
    prior achievement recognition (`seen`/`earned_at` present), NOT on images>0. An
    images-based backfill would re-fire the bug -- during a fresh first sync the image
    count climbs above zero, so it would flip the flag mid-sync. Any install that has
    ever surfaced an achievement has a non-empty `seen`/`earned_at`; a fresh mid-first-
    sync install cannot (the gate keeps `seen` empty until completion). The rare install
    with a real library but a pristine achievement state simply resolves on its next
    `--sync`."""
    try:
        if load_telemetry(out_dir)["flags"].get("first_sync_done"):
            return True
        st = load_ach_state(out_dir)
        if st.get("seen") or st.get("earned_at"):
            telem_flag("first_sync_done", out_dir=out_dir)
            return True
    except Exception:                                    # never let the gate crash the route
        return True                                      # fail OPEN: a broken gate must not hide trophies forever
    return False


def _has_loose_marks():
    """Pure-filesystem check: at least one REAL, on-disk mark (a loose
    marks.json entry whose .png exists loose). Deliberately NOT list_marks() --
    that is container-aware, and every install ships the default marks IN the
    container, so a container-aware check here would be true on a completely
    untouched install with zero user action. This exact substitution silently
    defeated the discovery feat once before (caught by adversarial review,
    2026-08-09) -- keep this filesystem-only, same contract the sweep/adopt
    functions hold."""
    mdir = _role_dir("marks")
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    for m in data.get("marks") or []:
        if isinstance(m, dict):
            mid = str(m.get("id") or "")
            if mid and (mdir / (mid + ".png")).is_file():
                return True
    return False


def sweep_telemetry(out_dir):
    """Set the state-derived feat flags whose 'event' may predate the telemetry
    layer: a custom mark in branding/ (Under the Hood) and the eclipse mark
    animation (Eclipse). Once set they stay set. Cheap; called by the API.

    Uses _has_loose_marks(), never list_marks() -- see that docstring."""
    try:
        if _has_loose_marks():
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
    deleted_dir = out_dir / DELETED_DIRNAME
    # Kept as an exclusion even though branding no longer lives under out_dir: an old
    # install still has files there, and excluding a path that is now absent is a harmless
    # no-op, whereas dropping the exclusion would sweep a legacy folder into a scan.
    branding_dir = out_dir / "branding"

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

    # The walk is the panel's cost at scale (owner report 2026-08-06: "VERY slow" at
    # 35k images). The old rglob walked EVERY file -- including the entire gallery/
    # thumbnail tree, only to exclude each one by path-prefix afterward -- and then
    # paid a separate stat() per kept file. This scandir recursion (a) PRUNES the
    # excluded subtrees (gallery/, _duplicates/, the deleted dir, legacy branding/)
    # so their thousands of entries are never enumerated at all, and (b) reads
    # is_file/size straight off the DirEntry, which on Windows comes from the
    # directory read itself -- no per-file syscall. Same results, same exclusions,
    # guarded by tests/test_gallery_filters.py's existing health tests.
    import os as _os
    _pruned = {str(gallery_dir), str(quarantine_dir), str(deleted_dir), str(branding_dir)}

    def _walk(dirpath):
        try:
            with _os.scandir(dirpath) as entries:
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.path not in _pruned:
                                yield from _walk(e.path)
                        elif e.is_file(follow_symlinks=False):
                            yield e
                    except OSError:
                        continue
        except OSError:
            return

    for e in _walk(str(out_dir)):
        p = Path(e.path)
        ext = p.suffix.lower()
        is_img = ext in _IMAGE_EXTS
        if (not is_img and ext not in _video_exts) or p.name.endswith(".part"):
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
            sz = e.stat(follow_symlinks=False).st_size   # from the DirEntry -- no extra syscall on Windows
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
        # prompt_full alone overstates it badly. A row can hold a prompt and a seed while
        # holding no model, steps, sampler or CFG -- so this panel read 98% on a catalog
        # where 1% of rows could say which model made them. model_id is the honest second
        # number: it comes only from a task-detail fetch, and it is what an image-view
        # upscale needs. Locally imported rows have no PixAI task and so can never carry
        # one; they are excluded rather than counted as a permanent shortfall.
        with_model   = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(model_id,'') != ''")
        model_base   = _scalar("SELECT COUNT(*) FROM catalog "
                               "WHERE COALESCE(source,'') != 'local'")
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
        # every media_id the catalog knows about at all (regardless of filename) --
        # the same "already cataloged" definition run_import_local() uses, so the
        # health count and what --import-local/Import would actually do stay in sync
        catalog_ids = {mid for (mid,) in con.execute(
            "SELECT media_id FROM catalog WHERE media_id != ''").fetchall()}
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

    # Integrity job (audit 2026-07-21, Curator #9): on-disk media with NO catalog
    # row at all -- the mirror image of `missing` above. Scoped exactly like
    # on_disk_ids is scoped throughout this function (images only; gallery/
    # _duplicates/_deleted/branding already excluded from the disk walk).
    uncataloged = on_disk_ids - catalog_ids

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
        "with_model": with_model,
        "model_pct": round(100 * with_model / model_base) if model_base else 0,
        "rated": rated,
        "missing": missing,
        "uncataloged": len(uncataloged),
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
    {media_id, keeper(rel), copies:[{rel,bucket,size}]} sorted keeper-first.

    Excludes gallery/, _duplicates/, AND _deleted/ (B11, audit 2026-07-21) -- a
    locally-purged image must not be reported back as a live duplicate of its own
    quarantined self."""
    from collections import defaultdict
    gallery_dir = out_dir / "gallery"
    quarantine_dir = out_dir / "_duplicates"
    deleted_dir = out_dir / DELETED_DIRNAME
    prio = {"batches": 0, "month": 1, "images": 2, "other": 3}
    locs = defaultdict(list)
    for p in out_dir.rglob("*"):
        if p.suffix.lower() not in _IMAGE_EXTS or not p.is_file():
            continue
        if (p.name.endswith(".part") or _is_under(p, gallery_dir)
                or _is_under(p, quarantine_dir) or _is_under(p, deleted_dir)):
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


def same_seed_groups(db_path, limit=1000):
    """Class-C duplicates (2026-08-02, docs/DECISIONS.md): catalog rows sharing the
    same non-blank (seed, prompt_full) pair -- almost certainly the same generation
    re-rolled or resubmitted. A cheap SQL GROUP BY, not a new detection algorithm; no
    filesystem access, no hashing. Returns [{seed, prompt_hash, media_ids:[...]}],
    most-duplicated first, capped at `limit` groups. `prompt_hash` is a short digest
    of the grouped prompt_full (NOT the seed's own identity) so callers get a stable,
    compact per-group key without echoing the full prompt text into an id string."""
    import hashlib
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT seed, prompt_full, GROUP_CONCAT(media_id) AS ids, COUNT(*) AS n "
            "FROM catalog "
            "WHERE COALESCE(seed,'') != '' AND COALESCE(prompt_full,'') != '' "
            "GROUP BY seed, prompt_full "
            "HAVING COUNT(*) > 1 "
            "ORDER BY n DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            phash = hashlib.sha1((r["prompt_full"] or "").encode("utf-8", "ignore")).hexdigest()[:10]
            out.append({"seed": r["seed"], "prompt_hash": phash,
                        "media_ids": [m for m in (r["ids"] or "").split(",") if m]})
        return out
    finally:
        con.close()


# Hamming distance threshold (out of 64 bits) below which two dHashes count as a
# near-duplicate pair. 10/64 (~84% bit agreement) is the commonly-cited rule of thumb
# for 64-bit perceptual hashes -- comfortably wide enough to catch recompression/
# upscaling noise (measured well under 10 in practice: see tests/test_phash.py) while
# staying far from the ~32/64 (50%) two UNRELATED images land near.
NEAR_DUP_HAMMING_THRESHOLD = 10


def near_duplicate_groups(db_path, threshold=NEAR_DUP_HAMMING_THRESHOLD, hash_size=DHASH_SIZE):
    """Class-D duplicates (the perceptual-hash follow-up named in the original
    api_duplicates() docstring/DECISIONS.md): catalog rows whose dHash `phash` column
    (compute_dhash(), populated by `--backfill-phash`) is within `threshold` Hamming-
    distance bits of another row's -- catches an upscaled or recompressed copy of the
    same image, which Class B (identical_file, a byte hash) cannot, because the bytes
    genuinely differ. Image rows only (is_video='1' rows and blank-phash rows are
    skipped -- a row with no phash yet is "unknown", never treated as "no match").

    NOT a naive O(n^2) pairwise scan across the whole library (mirrors Class B's
    same-size-bucket trick in audit_collection()): the 64-bit hash is split into 4
    non-overlapping 16-bit bands, and rows are grouped by (band_index, band_value).
    Only rows that land in the SAME band bucket are ever Hamming-compared. This is a
    standard LSH ("banding") trick -- any pair within `threshold` bits of each other is
    near-certain to still agree exactly on at least one 16-bit band (a handful of
    scattered bit flips is very unlikely to touch all 4 bands at once), so real near-
    duplicates are still found; only far-apart pairs that would fail the threshold check
    anyway are skipped from ever being compared. Comparisons are deduped (a pair sharing
    2+ bands is only Hamming-checked once).

    Matching pairs are merged with union-find so a visual chain (A near B, B near C)
    lands in ONE group even if A and C individually exceed `threshold` -- same "keeper
    emerges from the group" shape the other three tiers already return, not a flat pair
    list.

    Returns [{media_ids:[...], closeness_pct}], most-similar-group first. closeness_pct
    is this tier's one deliberate departure from the other three (which carry no
    percentage/confidence by design, per DECISIONS.md) -- it is not invented: for each
    final group it takes the WORST (largest) pairwise Hamming distance among that
    group's own members (recomputed exactly now that the group is small, not estimated
    from the banding pass) and reports 100 * (1 - worst_distance / total_bits), i.e. "the
    two least-alike members in this group still agree on at least this share of the
    hash" -- a conservative, real number derived from the actual bits, never a fabricated
    confidence score."""
    from collections import defaultdict
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT media_id, phash FROM catalog "
            "WHERE COALESCE(phash,'') != '' AND COALESCE(is_video,'') != '1'"
        ).fetchall()
    finally:
        con.close()

    total_bits = hash_size * hash_size
    n_bands = 4
    band_bits = total_bits // n_bands
    band_mask = (1 << band_bits) - 1

    ints = {}
    for r in rows:
        try:
            ints[str(r["media_id"])] = int(r["phash"], 16)
        except (TypeError, ValueError):
            continue          # a corrupt/non-hex phash value -- skip rather than crash

    by_band = [defaultdict(list) for _ in range(n_bands)]
    for mid, v in ints.items():
        for b in range(n_bands):
            by_band[b][(v >> (b * band_bits)) & band_mask].append(mid)

    parent = {mid: mid for mid in ints}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, c):
        ra, rc = _find(a), _find(c)
        if ra != rc:
            parent[ra] = rc

    compared = set()
    for band in by_band:
        for mids in band.values():
            if len(mids) < 2:
                continue
            for i in range(len(mids)):
                for j in range(i + 1, len(mids)):
                    a, c = mids[i], mids[j]
                    key = (a, c) if a < c else (c, a)
                    if key in compared:
                        continue
                    compared.add(key)
                    dist = bin(ints[a] ^ ints[c]).count("1")
                    if dist <= threshold:
                        _union(a, c)

    grouped = defaultdict(set)
    for mid in ints:
        grouped[_find(mid)].add(mid)

    out = []
    for mids in grouped.values():
        if len(mids) < 2:
            continue
        mids = sorted(mids)
        worst = max(bin(ints[mids[i]] ^ ints[mids[j]]).count("1")
                    for i in range(len(mids)) for j in range(i + 1, len(mids)))
        out.append({"media_ids": mids,
                    "closeness_pct": round(100 * (1 - worst / total_bits), 1)})
    out.sort(key=lambda g: -g["closeness_pct"])
    return out


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


def find_files_for_media_id(out_dir, media_id, include_gallery=False, exts=None):
    """All on-disk files whose media_id matches, anywhere under out_dir.

    Single source of truth for media-id -> file resolution, shared by resume
    (`already_downloaded`), the gallery (`find_image_file`), and the duplicate
    audit. Matches BOTH naming layouts in one pass:
      * prefixed   `prompt_task_<mid>.ext` / `NN_<mid>.ext`
      * bare       `<mid>.ext`   (single-image --organize month files)

    The exact `media_id_of(p) == mid` check prevents substring collisions (a
    longer id ending in these digits). Skips `.part`, zero-byte files, gallery
    thumbnails (unless include_gallery=True), and quarantined files under
    _duplicates/ or _deleted/ (so a quarantined copy never counts as a live
    "survivor" and resume treats it as not-present). Returns a list of Paths.

    `exts` defaults to `_IMAGE_EXTS` (this function's historical, still image-only
    default -- e.g. tests/test_loom_export_bundle.py pins that video media resolves
    via a separate catalog-row fallback, NOT this matcher). Pass `exts=_VIDEO_EXTS`
    (B16, audit 2026-07-21) for a video-aware sibling -- see already_downloaded_video
    in moonglade_backup.py -- so the SAME exact-match + quarantine-exclusion
    contract applies to videos, not just images.
    """
    mid = str(media_id)
    match_exts = _IMAGE_EXTS if exts is None else exts
    gallery_dir = out_dir / "gallery"
    quarantine_dirs = (out_dir / "_duplicates", out_dir / DELETED_DIRNAME)
    matches = []
    for p in out_dir.rglob("*{}.*".format(mid)):
        if p.suffix.lower() not in match_exts:
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
            # The fallback below (find_files_for_media_id) already skips zero-byte
            # files -- this fast path found candidate rglob before that fallback ever
            # runs, so it needs the same size check or a catalog row still pointing at
            # its original filename gets a truncated/interrupted download served back
            # as if it were the real image (audit 2026-07-21, invariant 3/6).
            try:
                if (candidate.is_file() and candidate.stat().st_size > 0
                        and not _is_under(candidate, gallery_dir)
                        and not _is_under(candidate, deleted_dir)):
                    return candidate
            except OSError:
                continue
    matches = find_files_for_media_id(out_dir, media_id)
    return matches[0] if matches else None


# Accidental bulk deletes should be recoverable: purges MOVE files here instead of
# destroying them (the catalog row is still removed, so the gallery stays clean).
DELETED_DIRNAME = "_deleted"

# How many tasks /api/delete-preview describes image-by-image before it stops and just
# counts the rest. A DISPLAY bound only -- the totals it returns are always exact for
# the whole selection. 24 tasks is up to ~100 thumbnails, which is already more than
# anyone reads in a confirm dialog; selecting a thousand images would otherwise build a
# megabyte of JSON and a thumbnail wall the modal cannot scroll through.
DELETE_PREVIEW_TASK_CAP = 24


def _trash_meta_path(out_dir, media_id):
    """Sidecar path for a quarantined item's snapshotted catalog row (see
    _snapshot_before_purge). Lives beside the quarantined file itself, keyed by
    media_id rather than filename so it's a one-line lookup from either direction."""
    return Path(out_dir) / DELETED_DIRNAME / "{}.json".format(media_id)


def _read_trash_meta(out_dir, media_id):
    """The snapshotted row for a quarantined media_id, or None if it predates this
    feature (2026-07-24) or the write failed at purge time. Never raises -- a
    missing/corrupt sidecar just means the trash panel falls back to bare
    filename/mtime, not an error."""
    p = _trash_meta_path(out_dir, media_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _snapshot_before_purge(db_path, out_dir, media_id):
    """Write out_dir/_deleted/<media_id>.json with the row's own fields (rating,
    collections, prompt, task_id, ...) BEFORE delete_from_catalog() removes it for
    good. the 2026-07-21 audit's scoping note on the restore-panel row: "ratings/
    collections on old purges are gone (no manifest existed -- a purge-time snapshot
    for future deletes is part of the build)" -- this is that snapshot. The trash
    panel's restore path reads it back to reinsert a FULL row instead of a bare
    media_id/filename stub; its list path reads it for a real deleted_at instead of
    guessing from file mtime. Best-effort: a write failure must never block the
    purge itself, same fail-soft contract as the file-move/thumb-unlink around it."""
    import time
    row = get_row(db_path, media_id)
    if not row:
        return
    snap = dict(row)
    snap["_deleted_at"] = time.time()
    try:
        _trash_meta_path(out_dir, media_id).write_text(
            json.dumps(snap), encoding="utf-8")
    except OSError:
        pass


def purge_media_local(out_dir, thumb_dir, db_path, media_id, filename, quarantine=True):
    """Remove a media's catalog row + (regenerable) thumbnail, and either move its
    file to out_dir/_deleted/ (default, recoverable) or hard-delete it. Returns the
    new quarantine location (Path) when moved, else None.

    Raises OSError if the file could not be moved/removed, WITHOUT touching the
    catalog row -- see the move itself for why. Callers must handle that: the row is
    still there and so is the file, so nothing was lost, but nothing was deleted
    either and the user has to be told.

    When quarantining, also snapshots the about-to-be-deleted catalog row to a JSON
    sidecar (see _snapshot_before_purge) so a later restore can recover more than a
    bare filename. Skipped in hard-delete mode (quarantine=False): nothing is left
    to restore, so there's nothing worth snapshotting."""
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
            _snapshot_before_purge(db_path, out_dir, media_id)
            # Deliberately NOT caught: a failed move (antivirus or a sync client holding
            # the file for a moment, or a library on a different volume than out_dir,
            # which makes this rename cross-device) leaves the file exactly where it
            # was. Swallowing it and clearing the row anyway orphaned the file -- gone
            # from the gallery AND absent from _deleted/, so the trash panel, which
            # scans that directory, could never offer back a delete the UI had already
            # promised was recoverable.
            img.replace(dest)                       # atomic move on the same volume
            moved = dest
        else:
            img.unlink()                            # same contract: no row drop if it fails
    tp = Path(thumb_dir) / "{}.jpg".format(media_id)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass
    delete_from_catalog(db_path, media_id)
    return moved


def compute_dhash(img_path, hash_size=DHASH_SIZE):
    """Perceptual difference-hash (dHash) of an image, Pillow-only (no numpy/scipy
    dependency -- this codebase already ships Pillow for thumbnails, so no new
    dependency was added for this).

    Algorithm (well-known, ~15 lines): shrink to (hash_size+1) x hash_size, convert to
    grayscale, then for each row encode whether pixel[i] is brighter than pixel[i+1] as
    one bit. That is `hash_size * hash_size` bits total (64 for the default size=8),
    returned as a lowercase hex string. Unlike a byte/SHA hash (Class B, identical_file),
    a dHash is ROBUST to recompression and resizing -- the exact "upscaled or
    recompressed version of the same image" case byte-hashing misses, because shrinking
    to 8x8 washes out compression artifacts and interpolation noise while preserving the
    image's coarse gradient structure. Two dHashes of visually similar images differ in
    only a handful of the 64 bits (measured via Hamming distance -- see
    near_duplicate_groups() below); two unrelated images typically differ in ~32 (half),
    since the bits approach random relative to each other.

    Returns a 16-char hex string, or None if the image can't be opened/decoded (Pillow
    missing, corrupt file, unsupported format) -- callers must treat None as "unknown",
    never as a hash that happens to be empty."""
    if Image is None:
        return None
    try:
        with Image.open(img_path) as im:
            im = im.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
            pixels = list(im.getdata())
    except Exception:
        return None
    width = hash_size + 1
    bits = 0
    for row in range(hash_size):
        offset = row * width
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return "{:0{width}x}".format(bits, width=hash_size * hash_size // 4)


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
    Returns False (never raises) when ffmpeg is missing or the extract fails.

    Picks a REPRESENTATIVE early frame, not a fixed timestamp. A clip that fades
    in from black used to get a black poster, because the old `-ss 0.5` landed
    inside the fade (owner, 2026-08-22). ffmpeg's `thumbnail` filter scans a batch
    of frames and keeps the one closest to the batch average -- near-solid frames
    (a fade, a flash) lose that contest by construction. The window is the first
    ~3s (72 frames at 24fps) so the poster still reads as the clip's opening,
    not a random mid-clip moment. The literal-first-frame fallback stays for
    clips too short for the filter to get a batch."""
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
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(video_path), "-vf", "thumbnail=72", "-frames:v", "1", tmp],
            capture_output=True, timeout=90, creationflags=_NO_WINDOW)
        if r.returncode != 0 or not os.path.getsize(tmp):
            # clips shorter than the seek point: take the literal first frame
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-i", str(video_path), "-frames:v", "1", tmp],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW)
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


# ---------------------------------------------------------------------------
# Trash / quarantine panel -- list, restore, permanently delete
# ---------------------------------------------------------------------------
# the 2026-07-21 audit's restore-panel row, scoped 2026-07-23: _deleted/ has ~12k
# files with no restore UI even though the delete confirm promises "recoverable".
# These are directory-scan helpers, deliberately NOT catalog queries -- the whole
# point of purge_media_local is that the catalog row is already gone by the time a
# file lands here, so there is nothing in catalog.db left to query.

def _find_quarantined_file(out_dir, media_id):
    """The actual media file (never a .json sidecar) in _deleted/ for media_id, or
    None. media_id_of() on a bare "<media_id>.json" sidecar resolves to the same
    media_id as the real file (its stem IS the media_id), so this explicitly
    restricts the extension to real media -- a naive media_id_of() match alone would
    pick either file depending on directory order."""
    import moonglade_backup as core
    qdir = Path(out_dir) / DELETED_DIRNAME
    if not qdir.exists():
        return None
    media_exts = _IMAGE_EXTS | core._VIDEO_EXTS
    for p in qdir.glob("*"):
        if p.is_file() and p.suffix.lower() in media_exts and media_id_of(p) == media_id:
            return p
    return None


def list_quarantined(out_dir, page=1, page_size=60):
    """Directory-scan listing of out_dir/_deleted/, newest-deleted-first, paginated.

    Not backed by the catalog (see module note above). Sidecar '<media_id>.json'
    files (written by purge_media_local since 2026-07-24) supply an exact deleted_at
    plus prompt/rating/collections/etc; older quarantined files -- or any sidecar
    write that failed -- fall back to the file's own mtime.

    mtime is only ever a FALLBACK, never the primary sort key when a sidecar
    exists -- found live-verifying this feature: purge_media_local moves a file
    into _deleted/ with img.replace(dest), a same-volume rename, and a rename does
    NOT update a file's mtime on Windows/NTFS (mtime tracks content writes, not
    moves). So a quarantined file's mtime is really "when it was originally
    downloaded", not "when it was deleted" -- sorting a batch of freshly-purged
    items (which DO have an accurate sidecar) by mtime alone silently reordered
    them by download date instead, which a synthetic multi-item live check caught
    immediately (an older-downloaded, just-deleted image sorted BELOW a
    newer-downloaded one deleted earlier the same session).

    All sidecars are read up front to build that sort key -- NOT deferred to just
    the current page the way thumbnail generation is (see _ensure_trash_thumbs) --
    but this stays cheap: sidecars only exist for files purged since 2026-07-24, a
    small and slowly-growing set, never the ~12k-file legacy backlog they're
    scanned alongside (which has no sidecars to read at all, by definition -- nothing
    wrote one before this feature existed). Only os.scandir() + stat() (metadata
    only, no content read) touches every file in the backlog; JSON parsing is
    bounded by however many sidecars actually exist. Returns (items, total, total_bytes)."""
    import moonglade_backup as core
    qdir = Path(out_dir) / DELETED_DIRNAME
    if not qdir.exists():
        return [], 0, 0

    media_exts = _IMAGE_EXTS | core._VIDEO_EXTS
    entries = []
    meta_by_id = {}
    with os.scandir(qdir) as it:
        for e in it:
            if not e.is_file():
                continue
            if e.name.lower().endswith(".json"):
                mid = Path(e.name).stem
                meta = _read_trash_meta(out_dir, mid)
                if meta:
                    meta_by_id[mid] = meta
                continue
            if Path(e.name).suffix.lower() not in media_exts:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            entries.append((e.name, st.st_size, st.st_mtime))

    total = len(entries)
    total_bytes = sum(s for _, s, _ in entries)

    def _sort_key(entry):
        name, _size, mtime = entry
        meta = meta_by_id.get(media_id_of(name))
        return (meta or {}).get("_deleted_at") or mtime

    entries.sort(key=_sort_key, reverse=True)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    page_entries = entries[start:start + page_size]

    items = []
    for name, size, mtime in page_entries:
        media_id = media_id_of(name)
        is_video = Path(name).suffix.lower() in core._VIDEO_EXTS
        meta = meta_by_id.get(media_id)
        deleted_at = (meta or {}).get("_deleted_at") or mtime
        prompt = ((meta or {}).get("prompt_full") or (meta or {}).get("prompt_preview") or "")
        items.append({
            "media_id": media_id, "filename": name, "size": size,
            "deleted_at": deleted_at, "is_video": "1" if is_video else "",
            "prompt": prompt[:2000], "has_meta": bool(meta),
        })
    return items, total, total_bytes


def _ensure_trash_thumbs(out_dir, thumb_dir, items, workers=6):
    """Generate thumbnails for exactly the quarantined items on ONE page -- reuses
    make_thumbnail()/make_video_thumbnail() (the same two functions build_thumbnails()
    calls for the live catalog), not new image-resize logic. Can't reuse
    build_thumbnails() itself: its file resolution (find_image_file /
    find_files_for_media_id) deliberately EXCLUDES _deleted/ -- a quarantined file
    must never resolve as a live survivor (INVARIANT 6) -- so it would never find
    anything sitting in the trash to begin with. Threaded like build_thumbnails() for
    the same reason it is: a page that happens to be video-heavy would otherwise pay
    each ffmpeg extract's cost serially, and this runs synchronously inside a
    request. purge_media_local already frees each media_id's thumb_dir slot when it
    quarantines the file, so writing back into that SAME slot means the existing,
    unmodified /thumbs/<media_id>.jpg route serves the result -- no new serving
    route needed."""
    qdir = Path(out_dir) / DELETED_DIRNAME
    work = []
    for it in items:
        thumb_path = Path(thumb_dir) / "{}.jpg".format(it["media_id"])
        if thumb_path.exists():
            continue
        work.append((qdir / it["filename"], thumb_path, it["is_video"] == "1"))
    if not work:
        return

    def _one(item):
        src, thumb_path, is_vid = item
        if not src.exists():
            return False
        return (make_video_thumbnail(src, thumb_path) if is_vid
                else make_thumbnail(src, thumb_path))

    if len(work) > 1 and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed([ex.submit(_one, it) for it in work]):
                try:
                    fut.result()
                except Exception:
                    pass
    else:
        for it in work:
            _one(it)


def restore_quarantined_media(out_dir, thumb_dir, db_path, media_id):
    """Move a quarantined file back out of _deleted/ and reinsert its catalog row.

    Restores to out_dir/images/<filename> -- purge_media_local only ever remembered
    the bare filename (see its own docstring), never the original month/batch
    subfolder, so this is the same flat default location a fresh download or
    --import-local would use; find_image_file()/find_files_for_media_id() already
    search the whole tree, so the gallery works identically regardless of which
    subfolder a file lives under.

    If a purge-time sidecar exists (every purge since 2026-07-24), the FULL row --
    rating, collections, prompt, task_id, everything -- comes back. Older quarantined
    files (or a sidecar write that failed) get a minimal row: media_id/filename plus
    is_video read off the file's own extension, so the file is visible in the gallery
    again -- and a video comes back as a video -- even though its history is genuinely
    gone (there was never a manifest before this feature -- see
    the 2026-07-21 audit's scoping note on this row). A live re-fetch of the
    task via getTaskById (mentioned as possible in that same note) is deliberately
    NOT attempted here: it would turn a local file-move into a network call with its
    own failure modes, for metadata that's "nice to have" on a handful of pre-feature
    orphans, not "needed to make the file visible again".

    Returns {"ok": True, "media_id":, "filename":} or {"ok": False, "error":}."""
    import moonglade_backup as core
    out_dir = Path(out_dir)
    src = _find_quarantined_file(out_dir, media_id)
    if not src:
        return {"ok": False, "error": "not found in trash"}

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / src.name
    if dest.exists():                             # a same-named live file already exists
        dest = images_dir / "{}_{}{}".format(src.stem, media_id, src.suffix)
    try:
        src.replace(dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    meta = _read_trash_meta(out_dir, media_id)
    row = {f: (meta.get(f, "") if meta else "") for f in CATALOG_FIELDS}
    row["media_id"] = media_id
    row["filename"] = dest.name
    # Only a sidecar carries is_video, and the ~12k legacy files in _deleted/ have none
    # (nothing wrote one before 2026-07-24), so restoring a legacy VIDEO left the flag
    # blank and the gallery served it back as a broken image instead of a player. The
    # extension is the same signal list_quarantined() reads for exactly this reason.
    if not row["is_video"]:
        row["is_video"] = "1" if dest.suffix.lower() in core._VIDEO_EXTS else ""
    save_catalog(db_path, [row])

    meta_path = _trash_meta_path(out_dir, media_id)
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass
    return {"ok": True, "media_id": media_id, "filename": dest.name}


def delete_quarantined_forever(out_dir, thumb_dir, media_id):
    """Permanently unlink a quarantined file + its sidecar meta + any thumbnail the
    trash panel generated for it while it sat in _deleted/. Irreversible -- the
    caller (api_trash_delete_forever) is LOCALHOST + confirm=true for exactly this
    reason. Returns True if a media file was actually removed."""
    out_dir = Path(out_dir)
    src = _find_quarantined_file(out_dir, media_id)
    removed = False
    if src:
        try:
            src.unlink()
            removed = True
        except OSError:
            pass
    meta_path = _trash_meta_path(out_dir, media_id)
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass
    tp = Path(thumb_dir) / "{}.jpg".format(media_id)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass
    return removed


def empty_trash(out_dir, thumb_dir):
    """Permanently wipe EVERY file in out_dir/_deleted/ -- the nuclear option behind
    LOCALHOST + confirm=true + the client's own typed-DELETE prompt
    (api_trash_empty()). Same per-item cleanup as delete_quarantined_forever(), just
    walked once instead of media_id-by-media_id. Returns the number of MEDIA files
    removed (sidecars don't count toward the number shown to the owner)."""
    qdir = Path(out_dir) / DELETED_DIRNAME
    if not qdir.exists():
        return 0
    import moonglade_backup as core
    media_exts = _IMAGE_EXTS | core._VIDEO_EXTS
    removed = 0
    for p in list(qdir.glob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in media_exts:      # sidecar .json (or stray junk)
            try:
                p.unlink()
            except OSError:
                pass
            continue
        mid = media_id_of(p)
        tp = Path(thumb_dir) / "{}.jpg".format(mid)
        if tp.exists():
            try:
                tp.unlink()
            except OSError:
                pass
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Duplicate Review -- resolve/undo (the destructive half of GET /api/duplicates
# above, which stays read-only). Mirrors the trash panel's own shape immediately
# above -- a moved file plus a JSON sidecar recording enough to undo it -- rather
# than inventing a new pattern, but keyed by the file's OWN quarantine location,
# not media_id: a same_media group can quarantine more than one copy of the SAME
# media_id in a single resolve, so media_id alone is not a unique key here the
# way it is for trash (purge_media_local never has two files under one media_id
# to quarantine at once -- the live catalog holds exactly one file per media_id).
# The original path is recorded EXPLICITLY and undo restores to that EXACT
# location -- unlike trash's restore, which only ever remembered a bare filename
# and always restores into a flat images/ folder -- because cmd_dedup's own
# quarantine (moonglade_backup.py's cmd_dedup, ~3889-3903) preserves the source's
# real subfolder structure under _duplicates/, and this feature's undo is
# specified to put a file back exactly where it came from.
# ---------------------------------------------------------------------------
DUPLICATES_DIRNAME = "_duplicates"    # matches cmd_dedup()'s own quarantine_root name


def _quarantine_meta_path(dest):
    """Sidecar path for one quarantined duplicate's undo record, living beside
    the moved file itself (same 'metadata rides next to the file' idea as
    trash's _trash_meta_path above)."""
    return dest.with_name(dest.name + ".undo.json")


def _resolve_under(out_dir, rel_path):
    """A client-submitted relative path, turned into a real absolute Path
    strictly inside out_dir -- or None if it's blank, absolute, or escapes via
    '..'/a symlink. Every client-supplied path this feature touches goes
    through this before it is ever stat'd or moved."""
    rel_path = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel_path:
        return None
    out_dir = Path(out_dir).resolve()
    candidate = (out_dir / rel_path).resolve()
    return candidate if _is_under(candidate, out_dir) else None


def _reconcile_one_row_after_move(out_dir, db_path, media_id, row):
    """Targeted, single-row version of moonglade_backup.reconcile_catalog_with_disk
    -- point media_id's catalog row at whatever copy is still actually on disk,
    without rescanning/rewriting the whole catalog (that function's own approach,
    fine for a batch CLI run, is wasteful for a single synchronous HTTP request).
    Used when a duplicate quarantine or undo changes what's on disk for a
    media_id whose row is being KEPT (e.g. a same_media loser's row, still
    pointing at a keeper that survives elsewhere). No-op if nothing changed, and
    a no-op if the media_id has no surviving file at all (that case is the
    caller's row-delete branch instead, not this function's job)."""
    import moonglade_backup as core
    matches = find_files_for_media_id(out_dir, media_id)
    if not matches:
        return
    survivor = matches[0]
    rel_surv = survivor.relative_to(out_dir)
    bucket = core._bucket_of(rel_surv)
    new_batch = (rel_surv.parts[1] if bucket == "batches" and len(rel_surv.parts) > 2
                else ("" if bucket != "batches" else row.get("batch", "")))
    if row.get("filename") != survivor.name or row.get("batch", "") != new_batch:
        row = dict(row)
        row["filename"] = survivor.name
        row["batch"] = new_batch
        save_catalog(db_path, [row])


def quarantine_duplicate_file(out_dir, thumb_dir, db_path, media_id, rel_path, group_id):
    """Move ONE duplicate loser out of the live tree into out_dir/_duplicates/,
    mirroring cmd_dedup()'s DEFAULT (--apply without --dedup-delete) behavior at
    moonglade_backup.py's cmd_dedup (~3889-3903) -- quarantine, never hard-delete,
    same collision-suffix rule (dest already exists -> "_dup" inserted before the
    extension). Called once per file by the /api/duplicates/resolve route, which
    has already re-verified the (group_id, media_id, path) triple names a real
    duplicate pair (see _validate_duplicate_pair) -- this function trusts that
    and only handles the mechanics: the move, the catalog reconciliation, and
    the undo sidecar. --dedup-delete's hard-delete behavior is not reachable
    through this function under any argument.

    _check_read_only() fires FIRST, before any path is even resolved -- the same
    position submit_generation/submit_fixer/delete_task_gql/claim_reward give it
    (moonglade_backup.py's own contract for every account/filesystem mutation
    this app makes). READ_ONLY in config.json refuses this the same way it
    refuses those.

    Catalog handling depends on whether media_id has ANY other live copy left
    after the move (find_files_for_media_id, which already excludes
    _duplicates/_deleted -- invariant 6):
      * no survivor  -> same situation as a trash purge: the row is removed
        (delete_from_catalog) and a FULL snapshot goes into the sidecar so
        undo can reinsert it, exactly like purge_media_local/
        restore_quarantined_media above.
      * a survivor exists (e.g. the keeper of a same_media group, still on disk
        under the SAME media_id) -> the row must NOT be deleted -- the media_id
        is still alive. Only a targeted filename/batch reconcile runs
        (_reconcile_one_row_after_move), the same fix
        reconcile_catalog_with_disk applies after a CLI --dedup, just scoped to
        this one row instead of a full rescan.

    Returns {"ok": True, "media_id", "original_path", "quarantine_path", "size",
    "row_deleted"} or {"ok": False, "error": "..."} -- never raises."""
    import moonglade_backup as core
    try:
        core._check_read_only("quarantine a duplicate file (Duplicate Review resolve)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    # .resolve() to match exactly what _resolve_under() resolved `src` against below --
    # otherwise a caller passing an out_dir that differs from its own .resolve() (a
    # symlink, a trailing slash) makes src.relative_to(out_dir) raise ValueError even
    # though src is genuinely inside it.
    out_dir = Path(out_dir).resolve()
    src = _resolve_under(out_dir, rel_path)
    if src is None:
        return {"ok": False, "error": "invalid path"}
    quarantine_root = out_dir / DUPLICATES_DIRNAME
    deleted_root = out_dir / DELETED_DIRNAME
    if _is_under(src, quarantine_root) or _is_under(src, deleted_root):
        return {"ok": False, "error": "already quarantined"}
    if not src.is_file():
        return {"ok": False, "error": "file not found: {}".format(rel_path)}

    rel = src.relative_to(out_dir)
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    row_before = get_row(db_path, media_id) if media_id else None

    dest = quarantine_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():                                   # don't clobber an earlier quarantine
        dest = dest.with_name(dest.stem + "_dup" + dest.suffix)
    try:
        src.replace(dest)                                # atomic move, same volume
    except OSError as e:
        return {"ok": False, "error": str(e)}

    row_deleted = False
    if row_before:
        survivors = find_files_for_media_id(out_dir, media_id)
        if not survivors:
            delete_from_catalog(db_path, media_id)
            row_deleted = True
            tp = Path(thumb_dir) / "{}.jpg".format(media_id)
            if tp.exists():
                try:
                    tp.unlink()
                except OSError:
                    pass
        else:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row_before)

    rel_dest = str(dest.relative_to(out_dir)).replace("\\", "/")
    rel_orig = str(rel).replace("\\", "/")
    import time
    sidecar = {
        "media_id": str(media_id),
        "original_path": rel_orig,
        "quarantine_path": rel_dest,
        "group_id": group_id,
        "quarantined_at": time.time(),
        "row_deleted": row_deleted,
        "catalog_row": row_before if row_deleted else None,
    }
    try:
        _quarantine_meta_path(dest).write_text(json.dumps(sidecar), encoding="utf-8")
    except OSError:
        pass    # best-effort, same fail-soft contract as trash's own snapshot write

    return {"ok": True, "media_id": str(media_id), "original_path": rel_orig,
            "quarantine_path": rel_dest, "size": size, "row_deleted": row_deleted}


def restore_quarantined_duplicate(out_dir, thumb_dir, db_path, quarantine_path):
    """Reverse ONE quarantine_duplicate_file() call: move the file back to its
    EXACT original recorded location (not a generic default folder -- unlike
    trash's restore_quarantined_media, this tier's undo is specified to put a
    file back exactly where it came from) and restore whatever the catalog
    snapshot says.

    Fails honestly -- never a silent no-op, never a write to some OTHER
    location -- when:
      * no sidecar/file exists for quarantine_path (missing/stale record, or it
        was never a real quarantined duplicate to begin with)
      * the original location is occupied by a DIFFERENT file that showed up
        there since (a re-download, a re-organize, a fresh import)

    Same _check_read_only() gate, in the same first-statement position, as
    quarantine_duplicate_file().

    Returns {"ok": True, "media_id", "restored_path"} or
    {"ok": False, "error": "..."} -- never raises."""
    import moonglade_backup as core
    try:
        core._check_read_only("undo a duplicate quarantine (Duplicate Review undo)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(out_dir).resolve()   # match _resolve_under()'s own resolution -- see
                                        # quarantine_duplicate_file()'s identical comment
    quarantine_root = out_dir / DUPLICATES_DIRNAME
    src = _resolve_under(out_dir, quarantine_path)
    if src is None or not _is_under(src, quarantine_root):
        return {"ok": False, "error": "not a quarantined-duplicate path"}
    meta_path = _quarantine_meta_path(src)
    if not src.is_file() or not meta_path.exists():
        return {"ok": False, "error": "no undo record for this file "
                                      "(missing, already restored, or stale)"}
    try:
        sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "undo record is unreadable/corrupt"}

    original_path = str(sidecar.get("original_path") or "")
    dest = _resolve_under(out_dir, original_path)
    if dest is None:
        return {"ok": False, "error": "recorded original path is invalid"}
    if dest.exists():
        return {"ok": False, "error": "original location is occupied by another "
                                      "file now -- refusing to overwrite it"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    media_id = str(sidecar.get("media_id") or "")
    if sidecar.get("row_deleted") and sidecar.get("catalog_row"):
        save_catalog(db_path, [sidecar["catalog_row"]])
    elif media_id:
        row = get_row(db_path, media_id)
        if row:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row)

    try:
        meta_path.unlink()
    except OSError:
        pass

    return {"ok": True, "media_id": media_id,
            "restored_path": str(dest.relative_to(out_dir)).replace("\\", "/")}


def _validate_duplicate_pair(out_dir, db_path, match_type, keep, remove):
    """Re-verify, at request time, that `keep` and every item in `remove`
    genuinely form the duplicate relationship match_type claims -- never trust
    the client's group_id/keep/remove alone; a client could otherwise pair a
    real duplicate's catalog metadata with an unrelated file path and use this
    route to quarantine anything. Cheap and TARGETED (touches only the specific
    files/rows named, never a full-library rescan) rather than recomputing GET
    /api/duplicates' whole detection pass. Returns (True, "") or
    (False, "<reason>") -- the whole group is refused together on failure,
    since a partially-verified group is not a safe partial resolve.

    near_duplicate is checked as a direct keep<->remove pairwise Hamming
    distance, not full group membership: near_duplicate_groups() can chain a
    group together transitively (A near B, B near C, but A and C individually
    over threshold) via union-find. A remove item that is only transitively
    linked to the chosen keeper is refused here as a known, documented
    simplification -- resolving it means picking a keeper it IS directly close
    to, not a gap in the detection logic."""
    import moonglade_backup as core
    out_dir = Path(out_dir)

    def _real(entry):
        """Resolve+validate one {media_id, path} member: a real file, strictly
        inside out_dir, whose OWN filename encodes the claimed media_id."""
        if not isinstance(entry, dict):
            return None
        mid = str(entry.get("media_id") or "").strip()
        path = _resolve_under(out_dir, entry.get("path"))
        if not mid or path is None or not path.is_file():
            return None
        if media_id_of(path) != mid:
            return None
        return mid, path

    k = _real(keep)
    if k is None:
        return False, "keeper does not resolve to a real file"
    keep_mid, keep_path = k

    checked = []
    for item in remove:
        r = _real(item)
        if r is None:
            return False, "a remove item does not resolve to a real file"
        checked.append(r)
    if not checked:
        return False, "nothing to remove"

    if match_type == "same_media":
        if any(mid != keep_mid for mid, _ in checked):
            return False, "same_media resolve must keep and remove copies of the SAME media_id"
        return True, ""

    if match_type == "identical_file":
        for mid, path in checked:
            if not core._same_bytes(keep_path, path):
                return False, "keeper and {} are no longer byte-identical".format(mid)
        return True, ""

    if match_type == "same_seed":
        keep_row = get_row(db_path, keep_mid)
        if not keep_row or not keep_row.get("seed") or not keep_row.get("prompt_full"):
            return False, "keeper has no seed/prompt to match against"
        for mid, _ in checked:
            row = get_row(db_path, mid)
            if not row or row.get("seed") != keep_row.get("seed") \
                    or row.get("prompt_full") != keep_row.get("prompt_full"):
                return False, "{} no longer shares (seed, prompt) with the keeper".format(mid)
        return True, ""

    if match_type == "near_duplicate":
        keep_row = get_row(db_path, keep_mid)
        keep_phash = (keep_row or {}).get("phash") or ""
        try:
            keep_bits = int(keep_phash, 16)
        except ValueError:
            return False, "keeper has no usable phash"
        for mid, _ in checked:
            row = get_row(db_path, mid)
            phash = (row or {}).get("phash") or ""
            try:
                dist = bin(keep_bits ^ int(phash, 16)).count("1")
            except ValueError:
                return False, "{} has no usable phash".format(mid)
            if dist > NEAR_DUP_HAMMING_THRESHOLD:
                return False, ("{} is no longer within the near-duplicate threshold "
                              "of the keeper").format(mid)
        return True, ""

    return False, "unknown group type '{}'".format(match_type)


def probe_has_audio(path, timeout=15):
    """True if the media file has at least one audio stream (ffprobe). Fails soft to
    False (never raises) -- a probe failure means the Loom export treats the clip as
    silent and pads it, which is safe; it must never crash the export."""
    import shutil as _sh
    import subprocess
    if not _sh.which("ffprobe"):
        return False
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW)
        return bool(r.stdout.strip())
    except Exception:
        return False


def probe_duration(path, timeout=15):
    """Real duration in seconds via ffprobe, or None on failure (missing ffprobe,
    unreadable file, non-numeric output). Never raises."""
    import shutil as _sh
    import subprocess
    if not _sh.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW)
        return float(r.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


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
    import moonglade_backup as core
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
                # exts=_VIDEO_EXTS, not the matcher's image-only default: this fallback
                # exists for a video whose stored filename is stale or blank, and an
                # image-only match can never find one, so the row stayed thumbless.
                m = find_files_for_media_id(Path(out_dir), mid, exts=core._VIDEO_EXTS)
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
# skins, shared (via the __DESIGN_TOKENS__ marker + .replace()) by the React shells
# (NEXT_PAGE/LOGIN_PAGE) and LOOM_PAGE_BUNDLE so every surface
# re-skins together instead of the Loom carrying its own copy that silently drifts.
DESIGN_TOKENS_CSS = r"""
  /* Z BANDS (decided 2026-08-01, gallery-era redesign): exactly three, nothing between --
     components 0-7 · overlays/modals 300-500 · ambient/celebration 510-520 (the layer that
     must paint over any modal: achievement moment 520, its confetti sheet 517 behind it).
     The legacy 200s cluster and the stray 99 live only in classic surfaces, which retire
     with the React conversion -- do not add new values outside the three bands. */
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
    /* --loomc is the Loom's fixed-meaning cyan (hue law: cyan means the Loom in every
       skin). Same value as --blue on purpose: the UI Kit v2 designs reference the hue
       by this name, and the semantic name must exist in the pipeline or var(--loomc)
       falls back silently at handoff. --blue stays for existing usages. */
    --loomc:   #47cbc3;
    /* Moonglade Athenaeum palette: lavender leads, emerald is the "magic"
       highlight (Nelnamara's gems), gold filigree is rare. */
    --accent:  #b692e6; --accent-soft:#4fc99a; --gold: #d4af37; --emerald:#4fc99a;
    --purple-deep: #33236d; --purple-bright: #643aac;
    /* Feat tier: gunmetal band + ruby glow (the agreed 5th tier -- NOT pink). */
    --gunmetal: #8a93a2; --gunmetal-deep: #4a515c;
    --ruby: #e0355e; --ruby-deep: #a11238;
    /* Native controls (checkbox/radio/range/progress) default to the BROWSER's
       accent -- Windows Chrome's is a bright blue that belongs to no skin here.
       Three places had already set this one control at a time; declaring it on
       :root covers every control app-wide, and because it is an inherited
       property a skin that redefines --accent retints them for free. Per-control
       overrides (e.g. the ruby unleash toggle) still win on specificity. */
    accent-color: var(--accent);
    /* accent-color only tints the CHECKED fill; an unchecked box, a native select
       arrow and the scrollbars all keep light OS chrome without this. Every
       surface in this app is dark, so declaring it once here is what actually
       stops white checkboxes sitting on top of artwork. */
    color-scheme: dark;
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


def _upscale_const_js():
    """The upscale constants, handed to the client from core, through the
    __UPSCALE_CONST__ marker (same idiom as __DESIGN_TOKENS__).

    Two things ride along and both have one source of truth here rather than a retyped
    copy in a template or a component:

    * the five upscaler names, which PixAI matches LITERALLY -- mixed underscores, spaces
      and plus signs and all ("R-ESRGAN 4x+ Anime6B") -- so a typo is a rejected submit;
    * UPSCALE_PIXEL_CEILING, so <UpscalePanel> can derive the same dynamic ratio cap
      the server clamps to WITHOUT a second hand port of max_upscale_ratio. The Generate
      drawer still carries its own ported copy (documented, and pinned against the Python
      by tests/test_upscale_boosters.py); this exists so the new surface does not add a
      third place for those numbers to drift.

    Substituted into NEXT_PAGE and the Loom shells (the surfaces with upscale UI)
    since the classic cut (2026-08-08) removed the INDEX/DETAIL pages it was
    originally built for.
    """
    import moonglade_backup as core
    return ("<script>window.MG_UPSCALE={};window.MG_LORA={};</script>".format(
        json.dumps({
            "enlargeModels": list(core.ENLARGE_MODELS),
            "defaultEnlargeModel": core.DEFAULT_ENLARGE_MODEL,
            "ceiling": core.UPSCALE_PIXEL_CEILING,
            # So the panel can upscale an image whose model the catalog never recorded,
            # instead of refusing until one is picked -- PixAI's own dialog has no model
            # control at all. Served rather than retyped, like everything else here. It is
            # a VERSION id, so the panel sends it as version_id; see core for why.
            "fallbackVersionId": core.UPSCALE_FALLBACK_VERSION_ID,
            "denoise": {"strength": core.DEFAULT_UPSCALE_DENOISING_STRENGTH,
                        "steps": core.DEFAULT_UPSCALE_DENOISING_STEPS},
        }, separators=(",", ":")),
        # LoRA weight bounds per base architecture -- DiT allows 0..1.2, the SD family
        # -2..2. One table, served, so the drawer's slider and the builder's clamp cannot
        # drift into offering a weight the architecture rejects.
        json.dumps({
            "ranges": {k: list(v) for k, v in core.LORA_WEIGHT_RANGES.items()},
            "fallback": [core.LORA_WEIGHT_MIN, core.LORA_WEIGHT_MAX],
            "step": core.LORA_WEIGHT_STEP,
        }, separators=(",", ":"))))


# ---------------------------------------------------------------------------
# Global 401 guard, injected into EVERY page head (the React shells and _LOOM_SHELL).
#
# Why an interceptor and not a helper at each call site: there are ~90 fetch()
# calls across moonglade_gallery.py's inline JS, static/*.js and the Loom bundle, and
# a browser crawl found that NOT ONE of them inspects response status. The gate
# answers an expired session with a JSON 401 -- valid JSON -- so `r.json()`
# resolves happily, `.catch` never fires, and callers read the error body as
# data. Observed consequences: the job poller reads `d.phase` as undefined,
# decides "still running", and re-polls every 3s FOREVER with the drawer pinned
# on "Rendering under the eclipse..."; the picker renders "No images found" for
# a full library; the Loom's pollImg/runGen loops never terminate.
#
# Wrapping fetch once covers all ~90 sites, including code inside the prebuilt
# bundle that no call-site edit could reach, and cannot miss one the way a
# 90-site refactor could.
#
# Defined ONCE here and injected into both shells. Today produced two separate
# bugs from hand-synced duplicate copies (the Loom hook preamble, and a login
# CSS block) -- not adding a third.
_AUTH_401_GUARD_JS = r"""<script>/* Global 401 guard -- see _AUTH_401_GUARD_JS in moonglade_gallery.py */
(function(){
  if (!window.fetch) return;
  var orig = window.fetch, redirecting = false;
  window.fetch = function(input, init){
    return orig.apply(this, arguments).then(function(res){
      try{
        if (res && res.status === 401 && !redirecting) {
          var url = new URL((typeof input === 'string' ? input : (input && input.url) || ''),
                            location.href);
          /* Same-origin only: a 401 from a third party is not our session. And
             never bounce while already on /login, which would loop. */
          if (url.origin === location.origin && location.pathname !== '/login') {
            redirecting = true;
            location.href = '/login?next=' +
              encodeURIComponent(location.pathname + location.search);
          }
        }
      }catch(e){ /* never let the guard break a real response */ }
      return res;   /* hand the response back untouched -- callers are unchanged */
    });
  };
})();
</script>"""


# The Loom (Seedance video storyboard tool) is served at /loom. Its React source
# lives in loom/master-storyboard.jsx; this page loads React + picker-core from
# locally-vendored files (loom/vendor/, served by /loom/vendor/<file>; zero network
# calls to paint) and, per the tool's own integration notes, swaps window.storage onto
# the gallery backend so a board persists server-side (shared across devices) instead
# of per-browser localStorage.
_LOOM_SHELL = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Loom - Moonglade Athenaeum</title>
<script>/* apply saved skin before first paint (no FOUC) -- same key/origin the gallery
   header writes, so switching skin there re-colors the Loom too */
try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>""" + _AUTH_401_GUARD_JS + r"""
<style>
__DESIGN_TOKENS__
/* font-family here, not just in .sb-root: anything mounted OUTSIDE #root inherits from
   body, and this shell deliberately mounts things there -- the toast stack, the ? FAB.
   Without it they fell back to the browser default font while the gallery shell gave them
   system-ui, so the same components looked different on the two pages. notify.css now also
   states its own family (host-neutral by design), but the shell should not be handing
   anything an unstyled baseline. */
body { background: var(--base); margin: 0; font-family: system-ui, sans-serif; }
/* The old #jobs-fab/#jobs-tray positioning overrides (bottom:88px to clear the Cast panel's
   own buttons; z-index:401/402 to climb over .lv-overlay's 400) were retired 2026-08-09
   (Claude Design handoff, drift item 39). The Activity control is no longer a body-portaled
   floating tray -- it's .lv-top-act-wrap, a normal child of .lv-overlay itself
   (master-storyboard.jsx's own toolbar), so it was never competing with .lv-overlay's z-index
   at the root context in the first place; it just paints in normal document order, correctly
   UNDER Deep Focus's veil like everything else inside .lv-overlay, with no !important
   reconciliation needed anywhere. */

/* Clearance under the ? help FAB, which is the cost of making it visible at all.
   #eb-help-btn is position:fixed bottom:18px + 38px tall, so it floats over the
   bottom-right ~56px of the viewport -- and on /loom the bottom-right IS the Generate
   drawer (.lv-side.right is 560px wide). .mgd-go and <mg-cost-badge> sit in .lv-gen's
   NORMAL FLOW, not a pinned footer, so once the drawer is scrolled to its end -- the
   ordinary position right before you submit -- the FAB covered the right edge of the
   Generate button and clipped the tail of the cost readout ("· saves ~84,000 credits",
   the expiry sub-line). This project's standing rule is to report the real cost of every
   generation, so a partly-obscured cost line is not an acceptable trade for a visible
   help button.
   Padding, not another z-index change: the FAB SHOULD stay on top, the content just
   needs somewhere to scroll to. 64px = the FAB's 56px footprint + breathing room.
   #root out-specifies the .lv-gen rule in master-storyboard.jsx's STYLES regardless of
   which <style> React injects first -- and keeping it here rather than in the jsx means
   the FAB and its clearance live together, and no bundle rebuild is needed. */
#root .lv-gen { padding-bottom: 64px; }
</style>
<script src="/loom/vendor/react.production.min.js"></script>
<script src="/loom/vendor/react-dom.production.min.js"></script>
<!-- The video Generate drawer and its cost badge are the React <VideoDrawer> / <CostBadge>,
     bundled into master-storyboard.bundle.js as of the 2026-08-08 no-vanilla port -- no static
     script tags. -->
__UPSCALE_CONST__
</head><body>
<div id="root"></div>
<!-- The #jobs-fab/#jobs-tray anchors lived here until the 2026-08-08 no-vanilla port, then
     were rendered by the portaled React <ActivityTray> with the same ids. Both are gone as
     of 2026-08-09 (Claude Design handoff, drift item 39): the Activity control is inline in
     the toolbar (master-storyboard.jsx's own .lv-top-act-wrap) now, not body-level. -->
<script>
window.storage = {
  get:function(k){ return fetch('/api/loom/get?key='+encodeURIComponent(k)).then(function(r){return r.json();}).then(function(d){ return (d&&d.value!=null)?{value:d.value}:null; }); },
  set:function(k,v){ return fetch('/api/loom/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k,value:v})}); },
  list:function(p){ return fetch('/api/loom/list?prefix='+encodeURIComponent(p||'')).then(function(r){return r.json();}).then(function(d){ return {keys:(d&&d.keys)||[]}; }); },
  delete:function(k){ return fetch('/api/loom/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})}); }
};
</script>
__RUNTIME_SCRIPT_BLOCK__
<button id="eb-help-btn" onclick="document.getElementById('eb-help').style.display='flex';try{fetch('/api/ach-event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'docs'})})}catch(e){}"
  style="position:fixed;bottom:18px;right:18px;z-index:401;width:38px;height:38px;border-radius:50%;background:var(--accent);color:var(--base);border:none;font-size:19px;font-weight:700;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5);"
  title="How The Loom works">?</button>
<div id="eb-help" onclick="if(event.target===this)this.style.display='none'"
  style="position:fixed;inset:0;z-index:402;background:rgba(6,4,16,.72);display:none;align-items:center;justify-content:center;">
  <div style="width:680px;max-width:92vw;max-height:86vh;overflow-y:auto;background:var(--surface0);border:1px solid var(--surface1);border-radius:14px;padding:22px 26px;color:var(--text);font:13.5px/1.55 system-ui,sans-serif;">
    <h2 style="margin:0 0 4px;color:var(--text);">The Loom &mdash; quick guide</h2>
    <p style="color:var(--subtext);margin:0 0 14px;">A storyboard for multi-clip AI video: plan the whole piece, then render shot by shot.</p>
    <p><b>Acts &amp; Shots.</b> Your video is a list of <i>acts</i>, each holding <i>shot cards</i>. The reel bar tracks total runtime against your target. Add a shot, give it a duration, and write what happens.</p>
    <p><b>Modes.</b> Each shot has a generation mode: <b>I2V</b> animate from one image &middot; <b>FLF</b> morph from a start frame to an end frame &middot; <b>R2V</b> multi-reference (cast + scenes) &middot; <b>V2V</b> extend/transform an existing clip. (Text-only T2V is retired &mdash; these video models all need an input frame or reference.)</p>
    <p><b>Cast &amp; Assets.</b> Reusable references. Cite them in shot text as <b>@image1 @video1 @audio1</b> (lowercase). "Lock appearance" keeps a character consistent across shots.</p>
    <p><b>Frame handoff.</b> Every card has an open and close frame. "&#8627; inherit prev close" chains one shot's last frame into the next shot's first, so the cut is continuous; once a shot has rendered, the same button offers "&#9986; splice" to take its real last frame instead.</p>
    <p><b>&#9654; Generate shot.</b> Renders the card on PixAI's video engine (V4.0): your cast + frames upload in @-order, the shot text becomes the prompt, and the finished clip lands in the gallery catalog &mdash; free when a V4.0 card covers it. Status shows on the card; "open clip &#8599;" plays it.</p>
    <p><b>Copy shot.</b> The same assembled prompt, to your clipboard &mdash; paste it into any Seedance-style generator. The board is engine-agnostic by design: plan here, render anywhere.</p>
    <p><b>Saving.</b> The board autosaves to the gallery server (survives restarts). Backup .json / export .txt live in the header.</p>
    <p style="color:var(--subtext);">Full manual: the wiki&rsquo;s <a href="https://github.com/Nelnamara/moonglade-athenaeum/wiki/The-Loom" target="_blank" rel="noopener">The Loom</a> page.</p>
  </div>
</div>
</body></html>"""

# The Loom's ONE delivery path (bundle-only since the Babel-standalone retirement,
# 2026-08-08): the pre-transpiled loom/dist/master-storyboard.bundle.js (built by
# `npm run build` in loom/, via esbuild). A real module build -- shared modules are
# plain imports, no client-side transpile, no inline-stripping.
LOOM_PAGE_BUNDLE = (_LOOM_SHELL
    .replace("__RUNTIME_SCRIPT_BLOCK__",
             # The CSS esbuild emits for the shared React components master-storyboard.jsx
             # imports (gallery-picker.css today; grows as the vanilla campaign moves more
             # components into the bundle). Only these on-demand modals need it, so loading
             # it here (not the <head>) is fine -- no first-paint FOUC. Absent => harmless
             # 404 until the bundle is built.
             '<link rel="stylesheet" href="/loom/dist/master-storyboard.bundle.css">\n'
             '<script src="/loom/dist/master-storyboard.bundle.js"></script>\n'
             '<script>ReactDOM.createRoot(document.getElementById("root"))'
             '.render(React.createElement(LoomBundle.default));</script>')
    .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS))


def _build_stamp():
    """Version + short git SHA of the code THIS process loaded, computed once at
    startup. If you pull without restarting, this keeps showing the OLD sha -- which
    is precisely how you tell a stale server from a fresh one. Fails soft."""
    try:
        import moonglade_backup as _core
        ver = getattr(_core, "__version__", "?")
    except Exception:
        ver = "?"
    sha = ""
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            stderr=subprocess.DEVNULL, timeout=4,
            creationflags=_NO_WINDOW).decode().strip()
    except Exception:
        sha = ""
    return "v{}".format(ver) + (" · {}".format(sha) if sha else "")


LIBRARY_DIR_KEY = "LIBRARY_DIR"
DEFAULT_LIBRARY_DIR = "pixai_backup"


def resolve_library_dir(explicit=None):
    """Where the library lives: an explicit --out, then config.json's LIBRARY_DIR, then the
    default. Explicit beats stored on purpose -- a one-off `--out somewhere`, a scheduled
    job, or a second install pointed elsewhere must not be overridden by a shared setting,
    and must not quietly rewrite it either.

    Read fresh from disk rather than through core's module-level _cfg cache: the Panel
    writes this and then restarts, and a cache populated at the OLD process's start is
    exactly the value the restart exists to get away from.
    """
    if explicit:
        return str(explicit)
    try:
        import moonglade_backup as _core
        stored = str((_core._load_config() or {}).get(LIBRARY_DIR_KEY) or "").strip()
    except Exception:                                   # noqa: BLE001
        stored = ""
    return stored or DEFAULT_LIBRARY_DIR


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


def _account_key(username):
    """Filesystem-safe, case-COLLISION-safe key for `username` -- the ONE shared
    helper every per-account store (saved views, prompt snippets, Loom storyboards,
    toolbox presets) keys its own file/directory with (B14 residual).

    Account identity in this app is case-SENSITIVE: moonglade_backup.py's
    _find_web_user compares the raw username with `==`, and username_problem()
    rejects only empty/too-long/control-char names -- nothing about case. So "Nel"
    and "nel" are two distinct AUTH_USERS rows. But every one of these stores
    originally keyed its per-account file with quote(username, safe=""), which is
    itself case-PRESERVING: quote("Nel") == "Nel" and quote("nel") == "nel" are two
    different STRINGS naming the SAME file on NTFS, which is case-insensitive but
    case-preserving. That silently merged two distinct accounts onto one shared
    file/directory -- reproduced end to end (a save from one account was visible
    to, and overwritable by, the other) for saved views originally, then inherited
    by every store that copied the same quote() keying pattern since.

    A short hex digest of the exact (case-sensitive) username sidesteps NTFS's
    case-folding entirely: "Nel" and "nel" hash to two different digests, so they
    always land on two different files -- on every filesystem, not just Windows.
    Deliberately not reversible from the key alone -- nothing on disk needs a
    human-readable username back; the account already owns its display name in
    config.json's AUTH_USERS."""
    import hashlib
    return hashlib.sha256(str(username).encode("utf-8")).hexdigest()[:16]


# Any-OS user-home prefixes: X:\Users\<name>, /home/<name>, /Users/<name>.
# The candidate loop below only knows THIS machine's directories, so an error
# text carrying a path under any OTHER username (a library echoing a foreign
# path, a message minted on another machine, a mapped drive) sailed through to
# the browser untouched -- issue #14, caught by a cross-machine test run. Only
# the home prefix + username is replaced; the tail of the path stays readable.
#
# Two corrections from issue #17 (the earlier version half-leaked and over-matched):
#  - The username segment allows SPACES (a Windows account name commonly has one, e.g.
#    "John Smith"); it stops at a separator / quote / newline / invalid-filename char, so
#    the WHOLE name is redacted rather than just its first word.
#  - The leading (?<![A-Za-z0-9.]) lookbehind stops the POSIX /home|/Users branch from
#    firing INSIDE an ordinary URL path (api.pixai.art/v1/users/me, example.com/home/docs) --
#    it only matches a home at a real path boundary (start / whitespace / quote / paren).
_USER_HOME_RE = re.compile(
    r'(?<![A-Za-z0-9.])'
    r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:home|Users)/+)'
    r'[^\\/:"*?<>|\r\n\']+',
    re.IGNORECASE)


def _redact_host_paths_cli(out_dir, msg):
    """THE redactor -- the one copy. create_app()'s nested `_redact_host_paths`
    delegates here (it existed as a closure twin and the two were documented as
    a drift risk; collapsed 2026-08-14 while fixing issue #14). Also called
    directly by moonglade_backup.py's `_cli_job_finish`, which logs a
    bare-terminal CLI run's failure straight to jobs.jsonl (served to any
    LOGIN-tier caller via /api/jobs). Design choices (resolve()'d out_dir,
    longest-first, case-insensitive separator-agnostic regex, the length
    floor) are documented inline below and were carried verbatim from the
    original closure."""
    if not msg:
        return msg
    import tempfile
    # str(out_dir) resolved -- --out defaults to a relative "pixai_backup";
    # unresolved, `--out .` would make this candidate a bare "." that matches
    # (and redacts) every period in every message app-wide. The length floor
    # in the loop is the second, independent guard for candidates this
    # function doesn't construct.
    candidates = [str(Path(out_dir).resolve()), os.path.expanduser("~"),
                 tempfile.gettempdir(), sys.prefix, os.getcwd()]
    seen, out = set(), str(msg)
    for path in sorted(set(candidates), key=len, reverse=True):
        if not path or len(path) < 4 or path in seen:
            continue
        seen.add(path)
        # Split the RAW path on separators FIRST, then escape each segment,
        # then rejoin with a separator class: case-insensitive and
        # separator-agnostic (a library can hand back the same directory in a
        # different case or with forward slashes), while every segment stays
        # re.escape'd so the pattern can only ever match this exact path.
        segments = re.split(r'[\\/]+', path)
        pattern = r'[\\/]+'.join(re.escape(s) for s in segments)
        out = re.sub(pattern, "<host-path>", out, flags=re.IGNORECASE)
    # The generic pass runs AFTER the candidates: anything under a user home
    # the candidates didn't already cover -- any username, any drive letter --
    # loses its home prefix the same way (issue #14).
    out = _USER_HOME_RE.sub("<host-path>", out)
    return out


def create_app(out_dir: Path):
    app = Flask(__name__)

    # A job the SERVER owns cannot outlive the server, so anything still marked running when we
    # boot is from a process that is gone -- nothing will ever report it finished. Sweep those to
    # a terminal state now, or the Job Tracker shows a phantom "running" row forever (owner hit
    # exactly this after a 2026-07-26 machine reset: panel-3d49d9bffea2, a Similar rebuild killed
    # mid-flight, still displaying as running after the reboot). resolve_orphan_jobs() cannot
    # cover these -- it works by asking PixAI about a task id that local jobs do not have.
    # Fails soft: a startup nicety must never be able to stop the server from starting. But it
    # REPORTS the failure rather than swallowing it -- a silent `except: pass` here is how a sweep
    # that never actually ran would look identical to one with nothing to do. `core` is imported
    # locally because this module has no module-level alias for it, and there is no module-level
    # logger either; moonglade_logging.setup_logging() configures the root logger.
    import logging as _logging
    try:
        import moonglade_backup as _core
        _swept = _core.resolve_interrupted_local_jobs(out_dir)
        if _swept:
            _logging.getLogger(__name__).info(
                "Marked %d interrupted job(s) from a previous session as failed.", _swept)
    except Exception:
        _logging.getLogger(__name__).warning(
            "interrupted-job sweep skipped", exc_info=True)

    # ---- Session-based auth: secret key + cookie hardening ------------------
    # AUTH_SECRET_KEY is generated once (secrets.token_hex(32)) and persisted to
    # config.json by get_or_create_secret_key() -- reused on every subsequent start
    # so restarting the server doesn't silently log everyone out. See
    # _is_authorized_request() below for the gate this session backs, and
    # /login /logout for the routes that populate it.
    import moonglade_backup as _core_auth
    app.secret_key = _core_auth.get_or_create_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS can never read the session cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site POST/nav CSRF vectors
    # SESSION_COOKIE_SECURE is deliberately left False: this app is typically served
    # over plain HTTP on a LAN (`python moonglade_gallery.py`, no TLS terminator). A Secure
    # cookie would just get silently dropped by the browser over http:// and break
    # login entirely. Real hardening of this flag needs HTTPS, which means putting a
    # reverse proxy (nginx/Caddy) in front of this process -- out of scope for a
    # LAN-only tool. This is a known, accepted tradeoff, not an oversight.
    import datetime as _dt
    app.permanent_session_lifetime = _dt.timedelta(days=30)

    db_path = out_dir / "catalog.db"
    build_stamp = _build_stamp()
    init_db(db_path)
    set_telemetry_out(out_dir)     # bare telem_* bumps land in this install's ledger
    backfill_batches(out_dir, db_path)
    thumb_dir = out_dir / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    ensure_branding_discovery_tree()   # "Under the Hood" needs empty folders to find

    # Redacts THIS MACHINE's own filesystem paths out of an exception message before
    # it's stored or served to any LOGIN-tier caller (any signed-in LAN account, not
    # just the owner) -- str(e) on a file-not-found, permission, or upstream-API error
    # routinely embeds an absolute path, which routinely embeds the OS username.
    #
    # Literal-PREFIX replacement, NOT a regex. An earlier attempt (2026-07-21, docs/
    # the 2026-07-21 audit's S3) used a regex (`[^\s'"<>\|]*`) that stopped matching at
    # the first whitespace, so a spaced Windows username (`C:\Users\John Smith\...`)
    # still leaked in full -- exactly the harm this exists to close -- and its own
    # tests used space-free paths, so they'd have shipped green. This re-spin is
    # tested against a spaced username specifically because of that history.
    #
    # Longest-candidate-first: home/cwd/tmp/out_dir routinely nest inside one another
    # (out_dir is very often somewhere under the home directory), so matching the
    # LONGEST real path first replaces the whole thing with one tag -- matching a
    # shorter ancestor first would leave the more specific, still-identifying suffix
    # (out_dir's own folder name) sitting right after the placeholder.
    #
    # Bounds CONTENT, not size -- pairs with append_job_event's existing [:200] cap
    # (SIZE only) and every jsonify site's own [:N] slice; this must run BEFORE those
    # slices, not after, or a redaction landing past the cutoff never happens.
    def _redact_host_paths(msg):
        # Delegates to the one module-level copy (see _redact_host_paths_cli:
        # the closure and the module function were maintained as twins until
        # 2026-08-14, when issue #14's fix collapsed them).
        return _redact_host_paths_cli(out_dir, msg)

    @app.context_processor
    def _inject_branding():
        # mark_url / mark_anim / mark_kind on every page render, so the chosen
        # banner mark + its animation apply to the gallery, panel, health, dupes.
        return brand_context(out_dir)

    # ------------------------------------------------------------------
    # Control Panel: run maintenance CLI ops as background jobs with live
    # logs. Each action is a WHITELISTED argv against moonglade_backup.py
    # (never an arbitrary command); destructive ones require confirm=True.
    # One job at a time. Localhost-gated at the routes. Runs the CLI as a
    # subprocess (isolation from the Flask process + natural stdout capture, so
    # the unmodified CLI script's own print output streams straight to the
    # Jobs card) with cwd = the checkout dir (where config.json lives).
    # ------------------------------------------------------------------
    _cli_path = str(Path(__file__).resolve().parent / "moonglade_backup.py")
    _cli_dir = str(Path(__file__).resolve().parent)
    # catalog media_id -> upload-kind media_id, for references sent from the gallery.
    # PixAI refuses a generation-output id as an input (see resolve_img), so each
    # referenced image is uploaded once and reused. Process-lifetime only and
    # deliberately unbounded-but-tiny: one short string pair per image the owner has
    # ever referenced this run. Losing it on restart just re-uploads, which is free.
    _ref_upload_cache = {}

    # Bridge/enhance telemetry is DEFERRED to terminal success (see /api/enhance and
    # /api/task-status): submit_generation returns at createGenerationTask ACCEPTANCE, before a
    # panelplugin job starts, and such a job can be accepted-then-reaped. So /api/enhance records
    # {task_id -> workflow identity submitted} here, and the poll's done-branch fires the three
    # producers exactly once and drops the entry. Process-lifetime, tiny, bounded by in-flight
    # enhance tasks (dropped on done OR failed). A lost entry on restart just skips one bump.
    _enhance_pending = {}
    _enhance_pending_lock = threading.Lock()

    # The asset container's first-run fetch (2026-08-10, docs/DECISIONS.md "The
    # asset container, re-scoped from scratch"). A real streamed-download job,
    # not a subprocess like PANEL_ACTIONS below -- one instance per server
    # process, single-flight (AssetFetchJob.start() itself), deliberately
    # UI-agnostic: the Setup Wizard drives it as a phase; a standalone boot
    # check can drive the identical endpoints for a past-wizard install
    # missing the container. _container_path() is a module-level function
    # (defined above, beside branding_root()) so this binds the real, current
    # app root -- not a value frozen at import time.
    _asset_job = moonglade_assets.AssetFetchJob(_container_path())

    _panel_lock = threading.Lock()
    _panel_job = {"status": "idle", "action": "", "label": "", "lines": [],
                  "rc": None, "started_at": None, "progress": None,
                  "proc": None, "cancelled": False, "warn_count": 0}
    _PROG_PREFIX = "~=MGPROG=~"        # matches PANEL_PROGRESS_PREFIX in moonglade_backup.py
    _WARN_PREFIX = "~=MGWARN=~"        # matches PANEL_WARN_PREFIX in moonglade_backup.py (D-4)
    # The Loom's ffmpeg export job (trim + concat finished shots -> one mp4).
    _export_lock = threading.Lock()
    # `warning` is distinct from `error`: the export SUCCEEDS but came out different from what
    # was asked for (today: no audio track, because a missing ffprobe made every clip's length
    # unreadable). That has to reach the owner's screen, not just the log -- a silent downgrade
    # on a missing dependency is how someone ships a silent cut without ever learning why.
    _export_job = {"status": "idle", "progress": 0, "elapsed": 0.0,
                   "out": "", "error": "", "warning": "", "proc": None, "cancelled": False}
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
        # The "full audit" checkbox in the UI does NOT append a flag to the action above --
        # it selects this separate whitelisted entry. Same for dedup-delete below. Keeping
        # the client to a fixed set of action KEYS is what preserves the property the
        # whole runner is built on (see _panel_run: "a WHITELISTED argv, never an
        # arbitrary command"); letting a checkbox contribute argv would erode it.
        "audit-full":    {"args": ["--audit"], "label": "Duplicate audit (full — byte-compare, slower)", "destructive": False},
        "verify-dupes":  {"args": ["--verify-dupes"],
                          "label": "Verify _duplicates/ is safe to delete", "destructive": False},
        # Listed BEFORE rebuild so the non-destructive, usually-correct action reads first.
        # "Rebuild" drops the table and re-embeds everything; this adds only what is missing and
        # cannot lose existing rows. After an interrupted build the top-up resumes -- reaching for
        # rebuild there costs ~3x the time AND discards every row that survived.
        "sync-similar":  {"args": ["--sync-similar"],
                          "label": "Top up the Similar index (adds only what's missing)",
                          "destructive": False},
        "rebuild-similar": {"args": ["--rebuild-similar"],
                            "label": "Rebuild the Similar index (slow, needs pixeltable)",
                            "destructive": False},
        # Same trust class as sync-similar/rebuild-similar just above: computes and writes
        # a catalog column only (phash), no image files touched, so not destructive despite
        # being a real disk-scanning/CPU pass. Feeds the near_duplicate tier of
        # GET /api/duplicates (near_duplicate_groups(), this module).
        "backfill-phash": {"args": ["--backfill-phash"],
                           "label": "Backfill perceptual hashes (near-duplicate detection)",
                           "destructive": False},
        # --- Advanced sync (web parity step 2): the sync variants the bare "Sync now"
        # (an INCREMENTAL --sync, i.e. --update --full-meta) can't do. Each is its own
        # whitelisted KEY, exactly like audit-full/dedup-delete -- never argv the client
        # assembles. `advanced: True` routes them to the Panel's own "Advanced" section and
        # keeps them OUT of the scheduler dropdown (a full re-walk on a timer is a foot-gun,
        # and test-pull's N has no home there). All three are read/append, never destructive.
        "resync-full":   {"args": ["--full-meta"],
                          "label": "Full re-walk — re-pull ALL history + metadata (non-incremental)",
                          "destructive": False, "advanced": True},
        "inventory":     {"args": ["--count"],
                          "label": "Inventory count — tally account vs. backup (read-only, no download)",
                          "destructive": False, "advanced": True},
        # The ONLY parameterised action. `int_param` means _panel_run appends a single
        # server-validated, clamped integer (the N for --max) -- not an arbitrary string,
        # the same discipline as the scheduler's interval_hours. int_range bounds it.
        "test-pull":     {"args": ["--max"], "int_param": True, "int_range": (1, 200),
                          "int_default": 20,
                          "label": "Test pull — fetch the N most-recent tasks",
                          "destructive": False, "advanced": True},
        # (Export CSV isn't here on purpose -- in the browser it's a real DOWNLOAD via /export-csv,
        #  not a subprocess that writes catalog.csv into the backup folder.)
        "organize-dry":  {"args": ["--organize", "--dry-run"], "label": "Organize — preview (dry run)", "destructive": False},
        "dedup-dry":     {"args": ["--dedup"], "label": "Dedup — preview (dry run)", "destructive": False},
        # --- full-feed scans: they re-walk the WHOLE history every run, with no
        # --update-style short-circuit. That is why they were originally scheduler-only.
        # They now HAVE buttons (web parity: nothing should need the CLI), but the labels
        # say "full re-walk" out loud so the cost is visible before clicking rather than
        # discovered afterwards. ---
        "sync-artworks":     {"args": ["--sync-artworks"],
                              "label": "Sync published-artwork metadata (full re-walk)",
                              "destructive": False},
        "sync-videos":       {"args": ["--sync-videos"],
                              "label": "Sync i2v videos — back up mp4s (full re-walk)",
                              "destructive": False},
        # reconcile-deleted deliberately keeps NO button: --sync already runs it as its
        # final step (see run_sync's pipeline), so a button would be a second path to
        # work that just happened, inviting someone to run it and wonder why nothing
        # changed. It stays schedulable for anyone who wants it on its own cadence.
        "reconcile-deleted": {"args": ["--reconcile-deleted"], "label": "Reconcile deleted (flag cloud-removed rows)", "destructive": False, "panel_visible": False},
        # --- destructive: require confirm=true ---
        "organize":      {"args": ["--organize"], "label": "Organize into month folders", "destructive": True},
        # organize's inverse: replays organize_manifest.csv backwards, then deletes the
        # manifest. Destructive for exactly the reason organize is -- it MOVES the owner's
        # files on the server's own disk -- and there is no second manifest to undo the undo.
        "undo-organize": {"args": ["--undo-organize"],
                          "label": "Undo organize — move files back to their old paths",
                          "destructive": True},
        "dedup-apply":   {"args": ["--dedup", "--apply"], "label": "Dedup — quarantine dupes to _duplicates/", "destructive": True},
        # DELETES rather than quarantining, so it is strictly more dangerous than
        # dedup-apply and carries the same destructive=True (confirm + localhost-only).
        # Deliberately a separate key, not a flag the client can add -- see audit-full.
        "dedup-delete":  {"args": ["--dedup", "--apply", "--dedup-delete"],
                          "label": "Dedup — DELETE dupes outright (no _duplicates/ safety net)",
                          "destructive": True},
        # The write-enabled twin of verify-dupes above (--restore-orphans does nothing on
        # its own -- it only takes effect alongside --verify-dupes). Its own key rather
        # than a checkbox on verify-dupes, same reason as audit-full. Recovery, not loss --
        # it moves quarantined files with no surviving keeper back into images/ -- but
        # still an unlogged file move on the host, so it's gated like the rest.
        "restore-orphans": {"args": ["--verify-dupes", "--restore-orphans"],
                            "label": "Verify quarantine + restore orphans to images/",
                            "destructive": True},
        "rebuild-thumbs": {"args": ["--rebuild-thumbs"],
                           "label": "Rebuild ALL thumbnails — uniform quality + video posters",
                           "destructive": True},
    }

    def _panel_reader(proc):
        with _panel_lock:
            jid = _panel_job.get("job_id")
        last_pct = -1
        warn_n = 0
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
            if line.startswith(_WARN_PREFIX):
                # D-4: "<prefix>N" -- N files failed after retries, run otherwise completed.
                # Not a log line -- keep it out of the visible transcript, same as _PROG_PREFIX.
                try:
                    warn_n = int(line[len(_WARN_PREFIX):])
                except ValueError:
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
            status = ("cancelled" if cancelled else
                      "failed" if rc != 0 else
                      "done_with_errors" if warn_n else "done")
            _panel_job["rc"] = rc
            _panel_job["status"] = status
            _panel_job["warn_count"] = warn_n
            _panel_job["progress"] = None                # clear the bar when the job ends
            _panel_job["proc"] = None
        if jid:                                          # cancelled/done both close the card row cleanly
            # rc rides the terminal event for the same reason `action` rides the start
            # one: the ledger's result column shows the design's own "… · rc 0" format
            # (Control Panel.dc.html:106/517), and until now a successful run's exit
            # code was simply never written anywhere.
            _log_job(jid, status=("failed" if status == "failed" else
                                  "done_with_errors" if status == "done_with_errors" else "done"),
                     rc=rc,
                     error=("exited {}".format(rc) if status == "failed" else
                           "{} file(s) failed to download".format(warn_n) if status == "done_with_errors"
                           else None))

    def _panel_run(action, int_arg=None):
        import subprocess
        spec = PANEL_ACTIONS[action]
        # Worker count is a persisted panel setting (schedule.json), so BOTH manual
        # clicks and the scheduled run use it. Harmless on jobs that ignore --workers
        # (organize/dedup/audit); speeds up the ones that don't (sync's pull + backfill).
        try:
            workers = max(1, min(int(_load_sched().get("workers") or 4), 16))
        except (TypeError, ValueError):
            workers = 4
        action_args = list(spec["args"])
        if spec.get("int_param"):
            # The ONLY variable part of any panel argv, and it is a single bounded
            # integer, never a caller string: clamp int_arg into the action's declared
            # range (falling back to its default when absent, e.g. a stray scheduler
            # call), then append it. This is what lets test-pull carry an N without
            # eroding _panel_run's "a WHITELISTED argv, never an arbitrary command".
            lo, hi = spec["int_range"]
            try:
                n = max(lo, min(int(int_arg), hi))
            except (TypeError, ValueError):
                n = spec.get("int_default", lo)
            action_args = action_args + [str(n)]
        argv = [sys.executable, _cli_path, "--out", str(out_dir), "-v",
                "--workers", str(workers)] + action_args
        # MOONGLADE_PROGRESS makes the CLI emit machine progress markers we parse above.
        env = dict(os.environ, MOONGLADE_PROGRESS="1")
        import uuid
        job_id = "panel-" + uuid.uuid4().hex[:12]
        # CLAIM the single job slot -- check and mark in ONE lock acquisition, BEFORE any
        # subprocess exists; returns False (having spawned nothing) when it's already
        # taken. The check used to live at the caller and the mark down here after Popen,
        # so two near-simultaneous starts (a double-click, two tabs, the scheduler firing
        # as the owner clicks) both passed the check, both spawned, and the second's
        # update() overwrote the first's proc handle: one subprocess orphaned, invisible
        # to /api/panel/cancel, and for a destructive action walking the same files as
        # its twin -- exactly what "one job runs at a time" exists to prevent.
        with _panel_lock:
            if _panel_job["status"] == "running":
                return False
            _panel_job.update(status="running", action=action, label=spec["label"],
                              lines=["$ " + " ".join(action_args)], rc=None,
                              started_at=None, progress=None, proc=None, cancelled=False,
                              job_id=job_id, warn_count=0)
        try:
            proc = subprocess.Popen(argv, cwd=_cli_dir, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    encoding="utf-8", errors="replace", env=env,
                                    creationflags=_NO_WINDOW)
        except Exception:
            # Release the slot on a failed spawn, or one bad launch wedges the Panel for
            # the life of the process (nothing would ever clear a "running" with no proc).
            with _panel_lock:
                _panel_job.update(status="failed", proc=None)
            raise
        with _panel_lock:
            _panel_job["proc"] = proc
        # `action` rides the start event so the reconstructed job carries the machine
        # key alongside the display label -- the Panel's run-history ledger needs it
        # for per-action last-run lookups and its "run again" control. Merge semantics
        # (_reconstruct_jobs' cur.update) keep it through every later event.
        _log_job(job_id, status="running", type="panel", label=spec["label"], action=action)
        threading.Thread(target=_panel_reader, args=(proc,), daemon=True).start()
        return True

    def _job_busy():
        """The running job's label, or "" when the slot is free -- the server-side half of
        the rule the Panel already draws (Stop and Restart carry class 'jobbtn', which
        poll() disables while a job runs). Returned as a label rather than a bool so the
        refusal can name what is in the way."""
        with _panel_lock:
            return _panel_job["label"] if _panel_job["status"] == "running" else ""

    # ---- Automated tasks: run a SAFE job on an interval while the app is open ----
    # Persisted to out_dir/schedule.json. Only non-destructive actions are schedulable.
    # An in-process daemon: fires while the gallery is running (it is NOT an OS-level
    # cron -- for always-on, point Windows Task Scheduler at `--update` instead).
    _sched_lock = threading.Lock()

    def _log_job(job_id, **fields):
        """Append a job event to out_dir/jobs.jsonl for the Jobs card. Fails soft --
        activity logging must never break the request that triggered it."""
        try:
            import moonglade_backup as _core
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
                # Same lock /api/panel/schedule writes under -- reading the file while a
                # save is mid-write otherwise hands this loop a truncated (or stale) copy.
                with _sched_lock:
                    s = _load_sched()
                action = s.get("action")
                if not s.get("enabled") or action not in PANEL_ACTIONS \
                        or PANEL_ACTIONS[action]["destructive"] \
                        or PANEL_ACTIONS[action].get("advanced"):
                    # advanced actions are manual-run only (a full re-walk on a timer is a
                    # foot-gun; test-pull needs an N the scheduler can't supply) -- backstop
                    # to the dropdown already hiding them, in case an old schedule names one.
                    continue
                interval = max(1, int(s.get("interval_hours") or 6)) * 3600
                if _time.time() - (s.get("last_run") or 0) < interval:
                    continue
                if not _panel_run(action):
                    continue                   # panel busy -- retry on the next tick
                # Re-read under the lock before stamping: `s` was loaded up to a minute
                # ago, so writing that whole copy back would silently revert any setting
                # the owner saved through /api/panel/schedule in the meantime. The lock
                # can't span _panel_run -- it calls _load_sched() itself for `workers`.
                with _sched_lock:
                    s = _load_sched()
                    s["last_run"] = _time.time()
                    _save_sched(s)
            except Exception:              # noqa: BLE001 -- a bad schedule must not kill the loop
                pass

    threading.Thread(target=_scheduler_loop, daemon=True).start()

    # ---- Live-mirror watcher: event-driven backup over PixAI's push WebSocket -----
    # Keeps the CLI's --watch/--watch-backup machinery (moonglade_backup.py)
    # connected for as long as the gallery runs, auto-reconnecting with backoff on any
    # drop. Each generation is downloaded + cataloged the INSTANT it completes -- this
    # is what makes --update a fallback instead of the only way gens land locally.
    # Read-only listening + free downloads (no credits spent). Always-on by design.
    #
    # Staleness watchdog (2026-07-23): a real incident showed `connected` reading
    # True with no error for ~21 minutes while the socket had actually gone silent
    # -- no exception, no close frame, nothing to trip the reconnect logic below on
    # its own. core._watch_events_async now times out waiting on each individual
    # frame (core._WS_STALE_TIMEOUT, currently 4 minutes -- see that constant's own
    # comment for how the number was chosen) and raises core.WatchStaleError, which
    # lands in this loop's `except` below exactly like any other dropped connection
    # and gets reconnected the same way -- no separate thread, no polling, no new
    # control flow, just a bound on how long `await ws.recv()` is allowed to block.
    _watch_lock = threading.Lock()
    _watch_status = {"connected": False, "last_event_at": None, "mirrored": 0,
                      "events_seen": 0, "last_error": None, "started_at": None,
                      # New fields (additive -- see api_watch_status()): how many times
                      # the staleness watchdog below has had to force a reconnect, and
                      # when the most recent one happened. Existing readers of this dict
                      # (the Panel's watch-status UI, tests) only read the fields they
                      # already know about, so this is safe to add without touching them.
                      "stale_reconnects": 0, "last_stale_reconnect_at": None}

    # ---- Single-flight collect (per task id, in-process) -------------------------
    # THREE uncoordinated collectors live in this process: the always-on live-mirror
    # watcher below, /api/task-status's done-poll, and /api/import-task (whose
    # already-catalogued precheck narrows the window but cannot close it). Two of them
    # landing on the same just-finished task seconds apart used to run
    # core.collect_generation twice concurrently: download() skipped the second copy,
    # but both passes then ran video_faststart on the same clip, and the two
    # concurrent ffmpeg remuxes corrupted it (see video_faststart's docstring). Now
    # the first entrant per task id runs the real collect while any later entrant
    # waits, then answers from the catalog instead of re-downloading. In-process only
    # by design: the CLI's --watch-backup is a separate process, which is exactly why
    # video_faststart's unique temp name is the load-bearing cross-process guard --
    # this layer just stops the gallery process from double-collecting at all.
    _collect_mu = threading.Lock()          # guards the in-flight map itself
    _collect_inflight = {}                  # task_id -> {"lock", "waiters", "done"}

    def _collected_from_catalog(tid):
        """A finished collect's outcome, re-read from the catalog, in
        collect_generation's return shape (saved=0: THIS caller downloaded nothing)."""
        con = _connect(db_path)
        try:
            rows = con.execute("SELECT media_id, is_video FROM catalog WHERE task_id=?",
                               (str(tid),)).fetchall()
        finally:
            con.close()
        if not rows:
            return None
        return {"media_ids": [r[0] for r in rows], "saved": 0,
                "is_video": any(str(r[1] or "") == "1" for r in rows)}

    def _collect_single_flight(core, session, tid):
        """core.collect_generation, but never twice concurrently for the same task id."""
        tid = str(tid)
        with _collect_mu:
            ent = _collect_inflight.get(tid)
            if ent is None:
                ent = _collect_inflight[tid] = {"lock": threading.Lock(),
                                                "waiters": 0, "done": False}
            ent["waiters"] += 1
        try:
            with ent["lock"]:
                if ent["done"]:
                    # A concurrent collect for this task finished while we waited --
                    # its media is downloaded + catalogued, so report that instead of
                    # re-downloading (and, for a video, re-remuxing). If it somehow
                    # catalogued nothing (every download failed), fall through and
                    # retry for real.
                    got = _collected_from_catalog(tid)
                    if got is not None:
                        return got
                got = core.collect_generation(session, tid, str(out_dir))
                ent["done"] = True
                return got
        finally:
            with _collect_mu:
                ent["waiters"] -= 1
                if ent["waiters"] <= 0:
                    _collect_inflight.pop(tid, None)   # keep the map from growing forever

    def _log_mirrored_media(tid, got):
        """Record WHAT the watcher just collected against the job we already track, in the
        EXACT event shape /api/task-status's done branch writes (status='done', media_ids,
        is_video) -- so a reader of jobs.jsonl can't tell which collector produced it.

        The bug this closes (owner's production jobs.jsonl, 2026-07-24, two back-to-back
        generations): TWO writers can mark a generation terminal, and only one of them used
        to say what the task produced. /api/task-status's done branch logs media_ids;
        _reconcile_job, firing off the same WebSocket event, logs a BARE done. While the
        browser was still collecting gen #1 (several full-size downloads), the push event
        for gen #2 arrived and _reconcile_job won the race -- so gen #2's job went terminal
        carrying no media_ids, and nothing ever revisited it (the orphan sweep only
        re-checks jobs stuck at 'running'; this one was already 'done'). Its four images
        were downloaded and catalogued perfectly -- no data was lost -- but the Activity
        card rendered blank forever, because the tray (gallery/src/notify/ActivityTray.jsx,
        formerly static/mg-notify.js) builds its thumbnail from
        `(j.media_ids||[])[0]`. _watch_mirror had the answer in hand the whole time
        (_collect_single_flight returns {media_ids, saved, is_video}) and discarded it.
        Now whichever writer wins the race, the media ids get recorded.

        `duration` is deliberately NOT logged even though collect_generation returns one
        for videos: /api/task-status only puts it in its HTTP response, never in the job
        log, and the two writers must stay indistinguishable in the log.

        Three deliberate abstentions:
          * EMPTY media_ids writes nothing at all -- an empty list is indistinguishable
            from a real result to the tray, and would blank an entry another writer had
            already filled in correctly. Recording nothing beats recording nothing-shaped.
          * a task with NO job entry of its own writes nothing -- the same contract
            _reconcile_job keeps ("never invents one for a task generated on the website"),
            or every pixai.art generation would sprout a new Activity row here.
          * a job that ALREADY carries media_ids writes nothing -- there's nothing to add,
            and that's the common non-racing case (the browser poll got there first), so
            skipping keeps one event per generation instead of two.

        Unlike _close_orphan_if_resolved this does NOT require the job to be non-terminal:
        a job already sitting at a bare 'done' is precisely the case being fixed. Reads the
        raw reconstructed log for the same reason that helper does (an entry read_jobs()
        would already be hiding past JOBS_MAX_AGE still gets its media recorded), and skips
        a dismissed job rather than resurrecting it with a new event. Fails soft, and
        cannot raise into _watch_mirror's daemon thread: mirroring must never break,
        or lose its 'mirrored' count, because logging did."""
        try:
            import moonglade_backup as _core
            mids = (got or {}).get("media_ids") or []
            if not mids:
                return
            jobs_by_id, _order, _n = _core._reconstruct_jobs(out_dir)
            j = jobs_by_id.get(str(tid))
            if not j or j.get("dismissed") or (j.get("media_ids") or []):
                return
            _log_job(str(tid), status="done", media_ids=mids,
                     is_video=got.get("is_video", False))
        except Exception:                          # noqa: BLE001 -- logging must not break mirroring
            pass

    def _watch_mirror(tid):
        """Download + catalog one finished task off the watcher's event loop (own
        session per call, matching the CLI's --watch-backup pattern), then record what it
        collected in the job log -- see _log_mirrored_media for why throwing that answer
        away left a raced generation's Activity card permanently blank.

        Deliberately does NOT write a terminal 'failed' when the collect raises, matching
        the reasoning in api_task_status's catch-all `except` (a false terminal failure
        bricks the card for a generation that actually succeeded) -- and the case for
        abstaining is STRONGER here than there. api_task_status treats EmptyOutputsError as
        terminal because it asked PixAI for the task's status itself and got 'done' from
        the same read-your-writes surface the detail query then answered from: two
        consistent reads. This path's 'done' arrives on a different channel entirely (the
        WS push), so an empty-outputs read moments later is just as plausibly the detail
        query lagging the push as a genuinely empty task -- and writing 'failed' off it
        would overwrite a perfectly good done+media_ids event in read_jobs()'s
        last-event-wins merge. The authoritative failure writers stay /api/task-status and
        the orphan sweep; a mirror problem is recorded where it belongs, in
        _watch_status['last_error'] (surfaced by /api/watch/status and the Panel) --
        and ALSO in the persistent log (added 2026-08-05): last_error alone is
        in-memory-only, gone on restart and invisible to anyone reading moonglade.log
        after the fact. Found live: a task stuck failing every catch-up sweep for
        hours produced nothing but repeated "N finished task(s) were never mirrored"
        warnings in the log -- true, but silent about WHY, because the actual
        exception only ever reached last_error. A restart cleared the symptom (fresh
        process, fresh attempt) without anyone learning the cause."""
        import logging as _logging
        import moonglade_backup as core
        _log = _logging.getLogger(__name__)
        try:
            session = core._make_session(None)
            got = _collect_single_flight(core, session, tid)
            with _watch_lock:
                _watch_status["mirrored"] += 1
        except Exception as e:
            with _watch_lock:
                _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
            _log.warning("live mirror: failed to mirror task %s: %s: %s",
                         tid, type(e).__name__, _redact_host_paths(str(e))[:200])
            return
        # Outside the except above ON PURPOSE: _log_mirrored_media swallows its own
        # failures, and keeping it out of that handler makes it structurally impossible for
        # a logging problem to be reported as a mirror error on the watch-status line.
        _log_mirrored_media(tid, got)

    # The closures above are unreachable from outside create_app; the test suite
    # drives the watcher-mirror path through this seam (conftest disables the real
    # watcher thread via MOONGLADE_DISABLE_WATCH).
    app.extensions["mg_watch_mirror"] = _watch_mirror

    def _reconcile_job(tid, ws_status):
        """Resolve OUR Activity/job log for a task straight from a live event, so a
        generation whose Generate-card poller was closed (you navigated into the panel)
        still lands as done/failed instead of hanging at 'running' forever. Only touches a
        job we already track -- never invents one for a task generated on the website."""
        import moonglade_backup as core
        try:
            term = "failed" if ws_status in core._GEN_FAIL else "done"
            j = next((x for x in core.read_jobs(out_dir)
                      if str(x.get("job_id")) == str(tid)), None)
            if j and j.get("status") not in ("done", "failed"):
                _log_job(str(tid), status=term,
                         error=(ws_status if term == "failed" else None))
        except Exception:                          # noqa: BLE001 -- reconciling must not kill the watcher
            pass

    def _reconcile_orphan_jobs(min_age=0):
        """Ask PixAI the real status of any job still marked 'running' and resolve stale
        ones (read-only; no spend). Catches jobs orphaned when the app closed or a
        Generate card was dismissed before its poll resolved -- e.g. a task that failed
        while nobody was watching. Session is built lazily so a log with no qualifying
        running generate jobs costs nothing.

        `min_age` defaults to 0 -- check EVERYTHING immediately -- for the one-shot call
        at watcher startup (_watch_loop, below): anything still 'running' from a prior
        server session deserves an immediate look. api_jobs() below calls this on every
        poll with min_age=core.JOBS_ORPHAN_SWEEP_AGE instead, so a job only just
        submitted (still being actively polled by its own Generate card) is never asked
        about at all -- see resolve_orphan_jobs()'s and JOBS_ORPHAN_SWEEP_AGE's own
        docstrings for why 0 there would be wrong (re-checks a live video gen on every
        poll) and why --poll-timeout's 300s would ALSO be wrong (false-flags one)."""
        import moonglade_backup as core
        box = {"s": None}
        def _status(tid):
            if box["s"] is None:
                box["s"] = core._make_session(None)
            # The WHOLE dict, deliberately -- and this line has now been wrong in both
            # directions, so read before changing it.
            #
            # Originally the dict was passed through while resolve_orphan_jobs compared
            # the return against ("done","failed"): the comparison never matched, the
            # reaper resolved NOTHING, and it returned 0 forever while looking healthy.
            # The fix at the time was to send `["phase"]` instead. The reaper has since
            # been taught to accept BOTH shapes, and it now needs more than the phase: it
            # reads `started` to spot a task PixAI accepted but never dispatched (which
            # stays non-terminal for ~60min and otherwise spins silently). Sending the
            # bare string again would make that branch dead code in production while
            # every unit test around it still passed, because those call the library
            # function directly with their own stub.
            #
            # Guarded end-to-end by tests/test_jobs.py's
            # test_api_jobs_endpoint_marks_a_never_started_orphan_stale, which drives the
            # real endpoint rather than the library function.
            return core.generation_status(box["s"], tid)
        try:
            core.resolve_orphan_jobs(out_dir, _status, min_age=min_age)
        except Exception:                          # noqa: BLE001
            pass

    # How many recent tasks a catch-up examines. One page, deliberately: this runs unattended on
    # every reconnect, and a history walk on a flapping connection would hammer PixAI for no
    # benefit. Anything older than this page is what --sync / --update are for.
    WATCH_CATCHUP_TASKS = 30
    # Floor between catch-ups. A reconnect storm (flapping wifi, PixAI restarting) must not
    # become a request storm, so extra reconnects inside this window skip the sweep entirely.
    WATCH_CATCHUP_MIN_GAP = 300
    _catchup_lock = threading.Lock()
    _catchup_at = {"t": 0.0}

    def _watch_catchup(reason):
        """Collect finished tasks the mirror never saw. Safe to call on every reconnect.

        A push mirror is blind while disconnected, and reconnecting does not replay what it
        missed -- so without this, anything that completed during a drop is stranded until
        someone runs a manual sync. That is the gap; this closes it.

        Bounded, rate-limited and idempotent by construction: one page of recent tasks, at most
        one sweep per WATCH_CATCHUP_MIN_GAP, and a task is skipped unless the catalog is actually
        missing its media. Collection goes through the SAME _watch_mirror the event path uses, so
        its single-flight guard prevents a task being collected twice.

        Never raises -- a failed catch-up must not kill the watcher thread that called it."""
        import logging as _logging
        import time as _time
        import moonglade_backup as core
        _log = _logging.getLogger(__name__)
        with _catchup_lock:
            if _time.time() - _catchup_at["t"] < WATCH_CATCHUP_MIN_GAP:
                return
            _catchup_at["t"] = _time.time()
        try:
            session = core._make_session(None)
            conn = core.find_connection(
                core.gql(session, core.page_variables(WATCH_CATCHUP_TASKS)))
            edges = (conn or {}).get("edges") or []
            missed = []
            for edge in edges:
                node = edge.get("node", edge)
                tid = str(node.get("id") or "")
                if not tid or str(node.get("status") or "") not in core._GEN_DONE:
                    continue
                mids = [str(m) for m in (core.media_ids_for(node) or [])]
                if not mids:
                    continue
                # Absent from the catalog is the ONLY trigger. A task whose media is already
                # here needs nothing, and re-collecting it would be pure waste.
                if all(get_row(db_path, m) for m in mids):
                    continue
                missed.append(tid)
            if not missed:
                _log.info("live mirror: catch-up after %s -- nothing missed", reason)
                return
            _log.warning(
                "live mirror: catch-up after %s -- %d finished task(s) were never mirrored, "
                "collecting now: %s", reason, len(missed), ", ".join(missed[:10]))
            for tid in missed:
                _watch_mirror(tid)
                _time.sleep(1.0)          # paced -- be polite to their servers
        except Exception as e:
            _log.warning("live mirror: catch-up after %s failed: %s: %s",
                         reason, type(e).__name__, _redact_host_paths(str(e))[:200])

    # Test seam (same rationale as mg_watch_mirror above): the self-heal sweep is a closure
    # only ever called from the watcher thread, which the suite disables (MOONGLADE_DISABLE_WATCH).
    # Exposing it lets a test drive the gap-fill / skip / rate-limit BEHAVIOUR end to end, not
    # just grep the source for its guardrails.
    app.extensions["mg_watch_catchup"] = _watch_catchup

    def _periodic_catchup():
        """Backstop for _watch_catchup's other two triggers (startup, reconnect), both of
        which fire off a WS lifecycle event -- so a connection that stays nominally
        "subscribed" for a long stretch never gets a fresh sweep. Found live: PixAI's
        personalEvents push simply did not fire for an app-submitted generation (a
        website-submitted one, same session, did) -- no error, no disconnect, nothing to
        react to, so reconnect-triggered catch-up alone left it undiscovered. This loop
        just calls the same rate-limited, bounded _watch_catchup on a fixed clock, so
        discovery never depends entirely on the socket's own reconnect cadence."""
        import time as _time
        while True:
            _time.sleep(WATCH_CATCHUP_MIN_GAP)
            _watch_catchup("periodic")

    def _watch_loop():
        import asyncio
        import logging as _logging
        import time as _time
        import moonglade_backup as core
        # The mirror's state used to exist ONLY in _watch_status, in memory, readable solely
        # through /api/watch/status while the process lived. So when a generation failed to
        # mirror there was no way to answer "was it connected at the time?" -- not from the log,
        # not afterwards, not at all. Every transition below is now recorded in
        # out_dir/logs/moonglade.log. Transitions and mirrored tasks only, never per-event:
        # this stream can carry a lot of traffic and a per-event line would bury the signal.
        _log = _logging.getLogger(__name__)
        backed = set()   # task ids already mirrored this process's lifetime (a
                         # 'completed' event can repeat)
        with _watch_lock:
            _watch_status["started_at"] = _time.time()
        _log.info("live mirror: starting")
        _reconcile_orphan_jobs()   # clear any job left hanging at 'running' from a prior session
        # The app was closed until now, so by definition the mirror saw nothing in that window.
        # Off-thread: this does network I/O and must not delay the first subscribe.
        threading.Thread(target=_watch_catchup, args=("startup",), daemon=True).start()
        threading.Thread(target=_periodic_catchup, daemon=True).start()
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
                        _log.info("live mirror: connected and subscribed")
                        # Every connect covers a window we were blind for -- the gap since the
                        # last one. Rate-limited inside, so a flapping socket cannot turn this
                        # into a request storm, and threaded so it never blocks this callback
                        # (which is running on the WebSocket's own event loop).
                        threading.Thread(target=_watch_catchup, args=("reconnect",),
                                         daemon=True).start()
                        return
                    tu = ev.get("taskUpdated")
                    if not tu:
                        return
                    with _watch_lock:
                        _watch_status["events_seen"] += 1
                        _watch_status["last_event_at"] = _time.time()
                    status = tu.get("status")
                    tid = str(tu.get("id") or "")
                    # `in _GEN_DONE`, not `== _WS_DONE_STATUS`. This branch used to match ONE
                    # exact string while the reconcile branch below accepts five, off the same
                    # event -- so a done-status PixAI spells any other way would skip mirroring
                    # while still resolving the Activity row. Every task checked on 2026-07-26
                    # reports "completed", so this was not that day's cause, but the asymmetry
                    # produces exactly that symptom and is just as invisible.
                    if status in core._GEN_DONE and tid and tid not in backed:
                        backed.add(tid)
                        _log.info("live mirror: task %s reported %s -- mirroring", tid, status)
                        threading.Thread(target=_watch_mirror, args=(tid,), daemon=True).start()
                    # Reconcile the Activity log from the SAME event stream, so a job resolves
                    # even if the Generate card that was polling /api/task-status is gone.
                    if tid and (status in core._GEN_DONE or status in core._GEN_FAIL):
                        _reconcile_job(tid, status)

                asyncio.run(core._watch_events_async(auth, on_event, None))
                _log.info("live mirror: disconnected cleanly; reconnecting in %ss", backoff)
                backoff = 5   # a clean disconnect resets the backoff
            except core.WatchStaleError as e:
                # core._watch_events_async's own recv() timeout fired: the socket
                # reported no error and `connected` was already True, but nothing --
                # not even a keepalive ping -- arrived for core._WS_STALE_TIMEOUT
                # seconds. This is the exact failure this watchdog exists for (see
                # the module docstring above): a connection that LOOKS healthy on
                # every existing signal while silently seeing nothing. Recorded in
                # its own counter/timestamp, distinct from `last_error`'s generic
                # reconnect noise, so this specific failure mode stays visible in
                # /api/watch/status instead of looking like an ordinary drop.
                with _watch_lock:
                    _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
                    _watch_status["stale_reconnects"] += 1
                    _watch_status["last_stale_reconnect_at"] = _time.time()
                # WARNING, not info: this is the failure mode where the socket looked healthy
                # on every signal while seeing nothing, so anything that completed during the
                # silence was missed and will NOT arrive later. Worth finding in the log.
                _log.warning("live mirror: socket went silent (no traffic for %ss) -- "
                             "reconnecting. Anything that completed during the silence was "
                             "NOT mirrored.", getattr(core, "_WS_STALE_TIMEOUT", "?"))
            except Exception as e:
                with _watch_lock:
                    _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
                _log.warning("live mirror: %s: %s -- reconnecting in %ss",
                             type(e).__name__, _redact_host_paths(str(e))[:200], backoff)
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
    # Helpers
    # ------------------------------------------------------------------
    def _safe_next(url):
        """Only ever redirect to a same-site PATH after login -- ?next=https://evil.example
        or ?next=//evil.example (scheme-relative) must never be honored, or /login becomes
        an open redirect. A bare local path ('/loom', '/export-csv', ...) is the only
        shape every caller of this actually needs (redirect(url_for('login', next=request.path))
        is the only producer of a real `next`).

        Also rejects any embedded TAB/CR/LF control characters, not just a leading "//":
        Werkzeug's own Response.get_wsgi_headers() strips those control characters back out
        of a Location header value before writing it to the socket (via iri_to_uri), so a
        value like "/<TAB>/evil.example" sails past the plain "//" prefix check here yet
        gets rewritten by Werkzeug itself into a literal "//evil.example" scheme-relative
        redirect -- confirmed against the installed Flask/Werkzeug via a throwaway
        reproduction. The CR/LF variants don't even get that far: redirect() raises an
        unhandled ValueError ("Header values must not contain newline characters") instead,
        turning a real login into a 500. Regression -- see
        tests/test_web_auth.py's safe-next tests."""
        _UNSAFE_NEXT_CHARS = ("\\", "\t", "\r", "\n")
        if (url and url.startswith("/") and not url.startswith("//")
                and not any(c in url for c in _UNSAFE_NEXT_CHARS)):
            return url
        return None

    def _establish_session(username):
        """Populate a freshly-authenticated session for `username` -- the ONE place
        that decides what "you are now logged in" means, shared by BOTH a normal
        /login credential POST and the local-only first-account bootstrap POST
        below (factored out so the two paths can never drift apart on what a
        session looks like)."""
        import moonglade_backup as core
        session.clear()
        session["user"] = username
        session["sess_epoch"] = core.get_web_user_session_epoch(username)
        session["csrf"] = secrets.token_hex(16)
        session.permanent = True

    @app.route("/login")
    def login():
        """The sign-in page: serves the React shell (LoginPage.jsx) for EVERY request,
        including from the server's own machine -- there is no localhost bypass (see
        _is_authorized_request() above). GET-ONLY since the classic cut (2026-08-08):
        the real submit is POST /api/login (JSON; sign-in AND local-only first-run
        account creation, with the lockout/CSRF/bootstrap enforcement + its own test
        suite). The classic FORM POST branch and LOGIN_HTML died with the cut -- a
        stale pre-cut tab replaying a form POST now gets a 405 and a reload lands
        here. LoginPage.jsx renders one of three states off the boot flags below:
        sign-in (an account exists), local bootstrap-create (no_accounts + is_local),
        or the LAN-first-run safety message (no_accounts + NOT is_local)."""
        next_url = _safe_next(request.values.get("next", "")) or ""
        import moonglade_backup as core
        no_accounts = not core.list_web_users()
        is_local = _is_local_request()
        # setdefault, NEVER a fresh mint on GET: the front door redirects every
        # unauthenticated request here including the browser's own incidental asset
        # GETs (favicon, apple-touch-icon, ...) -- an unconditional mint orphaned the
        # token the visible page already held ("Your session expired" on every submit,
        # reproduced). Failed POSTs rotate the token in /api/login instead.
        session.setdefault("csrf", secrets.token_hex(16))
        brand = brand_context(out_dir)
        boot = {
            "authenticated": False,
            "csrf": session["csrf"],
            "no_accounts": no_accounts,
            "is_local": is_local,
            "next": next_url,
            "build_stamp": build_stamp,
            "mark_url": brand.get("mark_url") or "/branding/logo.png",
            "mark_anim": brand.get("mark_anim") or "classic",
            "mark_kind": brand.get("mark_kind") or "",
        }
        return render_template_string(
            LOGIN_PAGE.replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS),
            boot=boot)

    @app.route("/api/login", methods=["POST"])
    def api_login():
        """JSON sign-in AND first-run account creation for the React Login page
        (2026-08-02) -- docs/DECISIONS.md's 2026-07-31 feasibility map called
        this out explicitly: 'A SPA needs real POST /api/login -> JSON... before
        auth can be driven from React at all.' Public (see _PUBLIC_PATHS) -- an
        unauthenticated caller is exactly who needs to reach this.

        mode="create" (added once design_handoff/request-bootstrap-account-creation.md
        came back with a real spec) mirrors classic login()'s own bootstrap POST
        branch exactly -- same bootstrap_mode gate (no_accounts AND is_local,
        re-checked here independent of what GET rendered, so a hand-crafted
        mode=create POST from a non-local address or after the first account
        already exists is refused server-side regardless of client state), same
        core.username_problem/password_problem/add_or_update_web_user. Every
        other branch (lockout, CSRF, plain sign-in, error strings) is identical
        to before this existed -- shares _login_seconds_locked/_login_try_acquire/
        _login_clear (one IP-keyed counter for both modes), _establish_session,
        _safe_next. Errors are the identical generic strings login() gives, on
        purpose -- never which field was wrong for a sign-in attempt, and this
        and the classic form must never be distinguishable to an attacker by
        their error text."""
        body = request.get_json(silent=True) or {}
        import moonglade_backup as core

        def _fail(error):
            # Every failed POST rotates the session token, exactly like classic
            # login()'s POST branch ("a consumed/known-bad token must never stay
            # silently resubmittable" -- guarded there by test_web_auth.py's
            # rotation test; this route's missing rotation was found by the
            # 2026-08-07 /api/login test port). Unlike the classic form, which
            # re-renders with the fresh token embedded, a SPA holds its token in
            # JS -- so the fresh one rides back in the error payload for the
            # login page to adopt on the next attempt.
            session["csrf"] = secrets.token_hex(16)
            return jsonify({"error": error, "csrf": session["csrf"]})

        next_url = _safe_next(str(body.get("next") or "")) or ""
        no_accounts = not core.list_web_users()
        bootstrap_mode = no_accounts and _is_local_request()
        wants_create = body.get("mode") == "create"
        ip = _client_ip()
        locked_for = _login_seconds_locked(ip)
        if locked_for is not None:
            mins = max(1, (locked_for + 59) // 60)
            return _fail("Too many failed attempts from this address. "
                         "Try again in about {} minute{}.".format(
                             mins, "" if mins == 1 else "s"))
        if not _check_csrf(body):
            return _fail("Your session expired. Reload the page and try again.")
        if wants_create and not bootstrap_mode:
            # Same defense-in-depth as classic login()'s identical check: a
            # mode=create POST is only ever honored while bootstrap_mode is
            # true for THIS request, never inferred from CSRF validity alone.
            error = ("No account has been set up yet. Ask whoever runs this "
                    "server to sign in from the machine itself first.") if no_accounts \
                    else "Invalid username or password."
            return _fail(error)
        relocked_for = _login_try_acquire(ip)
        if relocked_for is not None:
            mins = max(1, (relocked_for + 59) // 60)
            return _fail("Too many failed attempts from this address. "
                         "Try again in about {} minute{}.".format(
                             mins, "" if mins == 1 else "s"))
        if wants_create:
            # bootstrap_mode is guaranteed True here -- the guard above already
            # rejected wants_create whenever it's False.
            username = str(body.get("username") or "").strip()
            password = str(body.get("password") or "")
            confirm = str(body.get("confirm") or "")
            un_problem = core.username_problem(username)
            pw_problem = core.password_problem(password)
            if un_problem:
                return _fail(un_problem)
            if pw_problem:
                return _fail(pw_problem)
            if password != confirm:
                return _fail("Passwords do not match.")
            core.add_or_update_web_user(username, password)
            _login_clear(ip)
            _establish_session(username)
            return jsonify({"ok": True, "next": next_url or "/"})
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if username and core.verify_web_user(username, password):
            _login_clear(ip)
            _establish_session(username)
            return jsonify({"ok": True, "next": next_url or "/"})
        error = "Invalid username or password."
        # Same "just tripped the lockout" report login()'s own POST branch
        # gives -- see that comment for why this can't just be inferred from
        # _login_try_acquire's own return value (it deliberately let THIS
        # attempt through so a correct 5th-try password still works).
        just_locked = _login_seconds_locked(ip)
        if just_locked is not None:
            mins = max(1, (just_locked + 59) // 60)
            error = ("Too many failed attempts from this address. "
                     "Try again in about {} minute{}.".format(mins, "" if mins == 1 else "s"))
        return _fail(error)

    # Served by logout() in place of a redirect -- see its own comment for why a
    # real page (not a 3xx) is required to run the Cache Storage purge. Static, no
    # Jinja/user input involved, so a plain string is safer than round-tripping it
    # through render_template_string for nothing.
    @app.route("/api/logout", methods=["POST"])
    def api_logout():
        """JSON sign-out for the React app (2026-08-02) -- POST-only mirror of
        logout()'s own POST branch; see that route's docstring for the full
        CSRF/revoke-scope reasoning, identical here (same shared
        bump_web_user_session_epoch, same scope="this-device" opt-out of the
        global revoke). Public (see _PUBLIC_PATHS): an already-dead cookie
        must still be able to shed itself locally with no valid session to
        check a CSRF token against -- same "fail toward MORE cleanup, never
        less" shape as the classic route, so this skips the CSRF check
        entirely (not just downgrades it) whenever `authorized` is false,
        exactly like logout() does.

        No HTML page to run the Cache Storage purge from this time -- the
        caller (React) does that purge itself in JS on a successful response,
        then navigates to /login. See LoginPage.jsx / App.jsx's logout
        handler."""
        import moonglade_backup as core
        body = request.get_json(silent=True) or {}
        user = session.get("user")
        # ORDER MATTERS, same as logout(): read `user` before any call that
        # might clear the session.
        authorized = bool(user) and _is_authorized_request()
        if authorized:
            if not _check_csrf(body):
                return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
            if body.get("scope") != "this-device":
                core.bump_web_user_session_epoch(user)
        session.clear()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # THE front door: DEFAULT-DENY for every request, enforced in one place.
    # ------------------------------------------------------------------
    # Allowlist is intentionally tiny: /login (GET-only since the classic cut,
    # 2026-08-08 -- it renders the React sign-in shell), the React JSON
    # sign-in/sign-out, and the public /branding/ art prefix below.
    # /branding/ IS public (see _PUBLIC_PREFIXES below): it was briefly left
    # gated on the theory that a missing logo is a harmless degrade, but the
    # actual effect was the real chosen mark/banner/favicon never rendering on
    # the one page every visitor -- including a not-yet-authenticated LAN
    # device -- is guaranteed to see. That route only serves static drop-in
    # art (banner/logo/marks/mascots) with path traversal already rejected
    # (see branding()); there's no user data, credential, or spend behind it,
    # so it carries the same public trust tier as /login itself.
    _PUBLIC_PATHS = frozenset({
        "/login",
        # The React app's JSON sign-in/sign-out (2026-08-02) -- an
        # unauthenticated caller is exactly who needs to reach /api/login,
        # and /api/logout must stay reachable by an already-dead cookie (an
        # expired session still deserves a clean local sign-out).
        "/api/login", "/api/logout",
    })
    _PUBLIC_PREFIXES = (
        "/branding/",
        # The React bundle (2026-08-02): LoginPage.jsx's own shell needs its
        # compiled CSS/JS to render at all, and it renders for a visitor who
        # by definition is not authenticated yet -- same public tier as
        # /branding/ and /manifest.webmanifest above (plain compiled code, no
        # user data, no catalog, no credential). LOGIN_PAGE below deliberately
        # does NOT reference the 4 /static/mg-*.js custom-element scripts
        # next_gallery()'s NEXT_PAGE loads -- none of that (pickers, cost
        # badge, upscale panel) exists on the login page, so those stay
        # exactly as gated as they always were.
        "/next/assets/",
    )
    # Routes whose contract is JSON, not an HTML page -- these get a JSON 401
    # instead of a login redirect, so a fetch(...).then(r => r.json()) caller
    # still gets parseable JSON instead of choking on the login page's HTML.
    # ONE prefix since the classic cut (2026-08-08): the two legacy non-/api/
    # JSON routes (/rate/<id>, /edit-prompt/<id>) were renamed under /api/.
    _JSON_GATE_PREFIXES = ("/api/",)

    @app.before_request
    def _enforce_front_door():
        """THE gate: every request must satisfy _is_authorized_request() (a
        logged-in session ONLY -- no localhost bypass, see that function's
        docstring further down) to reach anything beyond the tiny allowlist
        above. This replaced 43
        individual, easy-to-forget `if not _is_authorized_request(): ...` blocks
        that used to sit one-per-route (see CHANGELOG.md for the full list) with
        one place that can't be skipped when a new route is added later --
        exactly the gap a prior adversarial review flagged: `/`, `/image/<id>`,
        `/delete/<id>`, `/delete-bulk`, `/rate/<id>`, `/edit-prompt/<id>`,
        `/collection-add`, `/collection-remove`, `/bulk-replace-prompt`,
        `/panel`, `/duplicates`, `/health`, the raw asset routes (`/thumbs/`,
        `/img/`, `/video-file/`, `/full/`, `/badge-thumb/`,
        `/contact-sheet`), `/export-zip`, `/manifest.webmanifest`, `/sw.js`, and
        `/api/gallery-images`, `/api/similar`, `/api/collections`,
        `/api/contests`, `/api/achievements`, `/api/skin`, `/api/ach-event`,
        `/api/your-art`, `/api/loom/export-status`, `/api/loom/export-file`,
        `/api/ping` had NO auth check of any kind before this hook existed.
        `/branding/` is in that same "previously wide open" list, and
        deliberately went back to public (see `_PUBLIC_PREFIXES`) rather than
        joining the rest: it's static cosmetic art (logo/marks/mascots), not
        gallery content, and the login page itself needs to render it for a
        visitor who by definition isn't authenticated yet.

        `/api/branding/shortcut` is deliberately NOT loosened by this hook
        passing a logged-in remote session through as "authorized": its own
        handler re-checks the stricter `_is_local_request()` underneath,
        because it shells out to a host-local admin API on the machine the
        SERVER process runs on -- a categorically different trust tier than
        "browse the library" or "spend the owner's credits". See that route's
        docstring."""
        if request.path in _PUBLIC_PATHS or request.path.startswith(_PUBLIC_PREFIXES):
            return None
        if _is_authorized_request():
            return None
        if request.path.startswith(_JSON_GATE_PREFIXES):
            return jsonify({"error": "authentication required"}), 401
        return redirect(url_for("login", next=_safe_next(request.path) or ""))

    _health_cache = {"ts": 0, "payload": None}   # api_health's TTL cache -- see its docstring
    # (Used to live beside the classic /health page; the page died in the 2026-08-08 cut,
    # the cache moved here to its one surviving consumer.)

    @app.route("/api/health")
    def api_health():
        """The health dashboard's data as JSON -- gap-audit route #10, consumed by the
        React app's HealthOverlay (the in-app modal that replaces bouncing to the
        /health page). Same computation, same fields, same LOGIN tier as the page it
        un-bakes; the page route stays until demolition.

        ROUTE-LEVEL TTL CACHE (owner report 2026-08-06: "VERY slow" at 35k images).
        collection_health() walks the whole library; at production scale that is
        seconds of disk work per open, and the numbers it produces are glance-stats
        that do not change second to second. 120s of staleness on a dashboard is
        invisible; re-walking 70k files per open is not. The cache lives HERE, not in
        collection_health() itself, so every direct caller (the classic /health page,
        the tests) stays pure. ?fresh=1 bypasses -- the client sends it on an explicit
        user refresh, never on a plain open."""
        import time as _time
        now = _time.time()
        if (not request.args.get("fresh")
                and _health_cache.get("payload") is not None
                and now - _health_cache.get("ts", 0) < 120):
            return jsonify(_health_cache["payload"])
        payload = collection_health(out_dir, db_path)
        _health_cache["payload"] = payload
        _health_cache["ts"] = now
        return jsonify(payload)

    @app.route("/api/panel/summary")
    def api_panel_summary():
        """JSON twin of /panel's own aggregation, for the React Control Panel overlay --
        same data, same local/destructive action-visibility rule (see /panel's own long
        comment on panel_is_local), just packaged for fetch() instead of Jinja. Nothing
        computed here is new: every field is a value /panel already builds every request.
        LOGIN tier, matching /panel itself."""
        panel_is_local = _is_local_request()
        all_actions = [{"action": k, "label": v["label"], "destructive": v["destructive"],
                        "advanced": v.get("advanced", False),
                        "int_param": v.get("int_param", False),
                        "int_default": v.get("int_default"),
                        "int_range": v.get("int_range")}
                       for k, v in PANEL_ACTIONS.items()]
        actions = [a for a, (k, v) in zip(all_actions, PANEL_ACTIONS.items())
                  if v.get("panel_visible", True) and (panel_is_local or not v["destructive"])]
        import moonglade_backup as core
        session.setdefault("csrf", secrets.token_hex(16))
        try:
            sweep_branding_drops(out_dir)   # see api_branding()'s own GET for why
        except Exception:
            pass
        branding = load_branding(out_dir)
        # Control Panel.dc.html:226's {{ trashCount }} -- the Trash tile's own real
        # count, previously hardcoded to "--" on both platforms (nothing fetched
        # it; the real number only ever resolved once TrashSubOverlay's own
        # /api/trash/list call ran). Reuses list_quarantined()'s own total rather
        # than a second counting pass -- see that function's docstring for why an
        # os.scandir()-based count stays cheap even at a large trash size.
        trash_count = list_quarantined(out_dir, page=1, page_size=1)[1]
        return jsonify({
            "stats": catalog_counts(db_path),
            "trash_count": trash_count,
            "supervised": _supervised(),
            "panel_is_local": panel_is_local,
            "actions": actions, "all_actions": all_actions,
            "out_dir": str(out_dir) if panel_is_local else "",
            "web_users": core.list_web_users(),
            "current_username": session.get("user"),
            "csrf": session["csrf"],
            "branding": {"mark": branding["mark"], "anim": branding["anim"],
                        "anims": MARK_ANIMS, "marks": list_marks(out_dir),
                        "slots": branding_slots_payload(out_dir)},
        })

    def _check_csrf(body):
        """Shared CSRF check for this app's state-changing POSTs -- the Panel's
        Users tab (a parsed JSON body) and /logout (request.form) -- using the exact
        same session-based token pattern /login's form uses (see that route's
        docstring), reused rather than reinvented: every state-changing form in this
        app is meant to carry one. `body` only has to be .get()-able, so a dict and a
        request.form MultiDict both work.

        Called _check_panel_csrf until /logout became its second caller (the
        CSRF-able-GET fix) -- the "panel" in the name had stopped being true."""
        submitted_csrf = str((body or {}).get("csrf") or "")
        live_csrf = session.get("csrf", "") or ""
        return bool(live_csrf) and secrets.compare_digest(submitted_csrf, live_csrf)

    @app.route("/api/users/add", methods=["POST"])
    def api_users_add():
        """Add a new gallery web-login account from the Panel's Users tab.

        LOCALHOST-ONLY as of 2026-07-22. Previously gated by nothing beyond the
        front door, reasoned as "every account in this app's model already
        carries equal trust, so any logged-in session may manage accounts."
        That principle covers what an ALREADY-EXISTING account can do (generate,
        browse, curate) -- it was never weighed against a LAN guest minting
        itself a brand-new, persistent account. Closed alongside the matching
        fix to /api/users/remove: a LAN session used to be able to evict the
        owner's own account and then register a fresh one for itself, one
        finding with two halves (see the old state doc's Access & accounts section).
        Account creation now sits in the same trust class as
        api_setup_save_key/api_branding_shortcut/destructive Panel jobs -- a
        logged-in LAN account can use the gallery, not decide who else gets to.

        Refuses a duplicate username outright rather than silently resetting a
        stranger's password (that's still what add_or_update_web_user itself
        does, and stays available for the owner via --add-web-user for exactly
        that recovery case).

        The exists-check and the write happen in ONE call to
        core.add_web_user_if_new() (a single _accounts_lock acquisition), not a
        separate list_web_users() read followed by a separate
        add_or_update_web_user() write -- the latter shape was a TOCTOU: two
        concurrent requests claiming the same brand-new username could both pass
        the "doesn't exist yet" check before either write landed, and the second
        write would silently reset the first request's just-created password.
        (Same root-cause family as /api/users/remove's last-account race -- see
        that route's docstring.)"""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        import moonglade_backup as core
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        confirm = str(body.get("confirm") or "")
        # Same core.username_problem()/password_problem() the /login bootstrap form
        # and the --add-web-user CLI call use -- one policy, three entry points, no
        # drift. username_problem covers empty, over-length, and control chars.
        un_problem = core.username_problem(username)
        if un_problem:
            return jsonify({"error": un_problem}), 400
        pw_problem = core.password_problem(password)
        if pw_problem:
            return jsonify({"error": pw_problem}), 400
        if password != confirm:
            return jsonify({"error": "Passwords do not match."}), 400
        if not core.add_web_user_if_new(username, password):
            return jsonify({"error": "That username already exists."}), 400
        return jsonify({"ok": True, "username": username})

    @app.route("/api/users/remove", methods=["POST"])
    def api_users_remove():
        """Remove a gallery web-login account from the Panel's Users tab.

        Removing SOMEONE ELSE'S account is LOCALHOST-only, as of 2026-07-22;
        removing YOUR OWN account stays reachable from any logged-in session,
        local or LAN. Self-removal can only harm the caller -- that's a
        different, much smaller trust question than evicting another named
        account, which is the specific gap this closes: a LAN session used to
        be able to remove ANY account by name, including the owner's, with no
        guard beyond "not the last account left." A guest handed a tablet could
        boot the owner and (before the matching api_users_add fix) mint itself
        a durable login in the same motion. See the old state doc's Access &
        accounts section for the full reasoning; api_users_add closes the
        other half (a LAN session can no longer register a new account either).

        Refuses to remove the LAST remaining account: that would leave zero
        accounts, re-triggering the local-only bootstrap state and effectively
        locking out every remote LAN user until someone re-bootstraps from the
        server machine itself -- a real self-lockout risk, guarded against
        explicitly rather than left as a footgun. This applies even to a local
        session removing itself.

        The "how many accounts exist" check and the removal happen in ONE call
        to core.remove_web_user_guarded() (a single _accounts_lock acquisition),
        not a separate list_web_users() read followed by a separate
        remove_web_user() write -- the latter shape was a TOCTOU race,
        reproduced live against this real route (adversarial review,
        2026-07-19): with exactly 2 accounts, two concurrent removes of two
        DIFFERENT usernames could each read "2 accounts, safe to proceed" before
        either write landed, and both writes would go through -- leaving
        AUTH_USERS empty, the exact self-lockout this guard exists to prevent."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        username = str(body.get("username") or "").strip()
        if username != session.get("user") and not _is_local_request():
            return jsonify({"error": "localhost-only to remove another account"}), 403
        import moonglade_backup as core
        result = core.remove_web_user_guarded(username)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "last_account":
            return jsonify({"error": "Can't remove the last remaining account -- "
                                     "that would lock every remote device out until "
                                     "someone signs in locally to bootstrap a new one."}), 400
        return jsonify({"ok": True, "username": username})

    @app.route("/api/users/password", methods=["POST"])
    def api_users_password():
        """Change an account's password from the Panel's Users tab.

        Closes the last CLI-only account operation: until now a forgotten gallery password could
        only be reset with `--add-web-user` on the server machine (its add-or-update semantics
        doubling as a reset). Owner decision 2026-07-26: a user may change THEIR OWN password from
        anywhere, and changing anyone else's is an owner-machine action.

        Reading the code turned that into a single rule rather than two code paths, because the
        cases differ in exactly one respect -- whether the CURRENT password must be proved:

            LOCALHOST     may set ANY account's password without the current one.
            non-local     may set only its OWN, and must prove the current one.

        Both halves are load-bearing. Without the first, the forgotten-password case is not fixed
        at all, which is the entire point of the item -- and requiring the old password at the
        machine protects nothing, since anyone sitting there can edit config.json directly. Without
        the second, an already-authenticated LAN session -- a tablet left unlocked on the
        network -- could silently change the owner's password and lock him out of his own account,
        needing nothing but an open browser tab.

        The username check mirrors `api_users_remove` deliberately rather than inventing a stricter
        shape: an omitted username means "me", and a supplied one that is not yours demands
        LOCALHOST. That route's trust model has already survived an adversarial review, and
        consistency with it is worth more here than a second convention.

        The write bumps `sess_epoch`, so every session cookie issued under the old password stops
        working immediately -- which is the point on other devices and merely rude on this one. So
        when the caller changed their OWN password, this re-issues the current session's epoch: the
        browser you are standing in front of stays signed in, every other device drops. A local
        reset of SOMEONE ELSE's password deliberately does not do that, because the whole intent
        there is to evict whoever was using it.
        """
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        import moonglade_backup as core
        me = session.get("user")
        local = _is_local_request()
        target = str(body.get("username") or "").strip() or me
        new_pw = str(body.get("new_password") or "")

        if target != me and not local:
            return jsonify({"error": "localhost-only to change another account's password"}), 403
        # Same policy the Users tab already enforces when ADDING an account -- one rule, one
        # place, so a password that could not be registered cannot be set here either.
        problem = core.password_problem(new_pw)
        if problem:
            return jsonify({"error": problem}), 400

        # None means "do not check" and is reserved for a caller already proven local.
        current = None if local else str(body.get("current_password") or "")
        if current is not None and not current:
            return jsonify({"error": "Enter your current password."}), 400

        result = core.set_web_user_password_guarded(target, new_pw, current_password=current)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "bad_current":
            # Deliberately the same wording whether the account exists or not by this point --
            # the caller has already been established as the owner of `target` or as local, so
            # there is nothing left to leak, but keeping it vague costs nothing.
            return jsonify({"error": "That current password isn't right."}), 403

        if target == me:
            session["sess_epoch"] = core.get_web_user_session_epoch(me)
        return jsonify({"ok": True, "username": target,
                        "signed_out_elsewhere": True,
                        "still_signed_in_here": target == me})

    @app.route("/api/ping")
    def api_ping():
        """Cheap liveness probe — the Stop/Restart reconnect overlay polls this. Login required
        (any session, local or LAN)."""
        return jsonify({"ok": True})

    @app.route("/api/server/stop", methods=["POST"])
    def api_server_stop():
        """Shut the server down cleanly from the browser (Homebridge-style) instead of Task
        Manager. Login required (any session, local or LAN). Under the managed launcher this ends the whole app.

        Refused while a maintenance job is running, because os._exit kills only THIS
        process: the job's subprocess would outlive it, still walking the library with
        nothing reading its output and nothing able to cancel it. The Panel already says
        so -- Stop and Restart carry class 'jobbtn', which poll() disables for the life of
        a job -- but that is the browser's copy of the rule, and a tab loaded before the
        job started (or a second tab) still has live buttons. This is the same rule, kept
        where it cannot be bypassed. Cancel the job first; that is what it is for."""
        busy = _job_busy()
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't shut down while it works).".format(busy)}), 409
        _schedule_server_exit(0)
        return jsonify({"ok": True, "action": "stop"})

    @app.route("/api/library-path", methods=["GET", "POST"])
    def api_library_path():
        """Read or set the library folder (config.json's LIBRARY_DIR).

        LOCALHOST-ONLY on write: it rewrites config.json, the file that also holds
        AUTH_SECRET_KEY and AUTH_USERS, so it sits in the same trust class as
        /api/setup/save-key and /api/branding/shortcut. GET is LOGIN -- the Panel shows the
        current folder to whoever can already see the Panel, and it is the same host path
        /panel already withholds from non-local callers, so it is withheld here too.

        Setting this NEVER MOVES ANYTHING. It points the app at a different folder on the
        next start; the old folder is left exactly as it is. That is the whole contract, and
        it is why there is no "migrate" option here to get wrong.
        """
        import moonglade_backup as _core
        if request.method == "GET":
            local = _is_local_request()
            # BOTH path fields are withheld from a non-local caller, not just the first.
            # POST stores an ABSOLUTE path, so `stored` is the host path too -- blanking
            # `path` while returning `stored` handed it straight back, defeating the
            # withholding that /panel and this route's own docstring promise. `configured`
            # says whether a folder is set without saying where it is, which is all the
            # Panel needs to decide what to show.
            stored = str((_core._load_config() or {}).get(LIBRARY_DIR_KEY) or "")
            return jsonify({
                "path": str(out_dir) if local else "",
                "stored": stored if local else "",
                "configured": bool(stored),
                "default": DEFAULT_LIBRARY_DIR,
                "local": local,
                "supervised": _supervised(),
            })
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        want = str(body.get("path") or "").strip().strip('"')
        if not want:
            return jsonify({"error": "Enter a folder path."}), 200
        try:
            target = Path(want).expanduser()
            # Stored absolute: the server's working directory is the launcher's folder, and
            # a relative path stored here would silently mean somewhere else the moment
            # anything started it from elsewhere (a scheduled task, a terminal, a shortcut).
            target = target.resolve() if target.is_absolute() else (Path.cwd() / target).resolve()
        except (OSError, ValueError) as e:
            return jsonify({"error": "That path isn't usable: {}".format(e)[:160]}), 200
        if target.exists() and not target.is_dir():
            return jsonify({"error": "That path is a file, not a folder."}), 200
        if not target.exists():
            if not body.get("create"):
                return jsonify({"needs_create": True, "path": str(target),
                                "error": "That folder doesn't exist yet."}), 200
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return jsonify({"error": "Couldn't create it: {}".format(
                    _redact_host_paths(str(e)))[:160]}), 200
        # Written only AFTER the folder is known good -- never write first and hope, the
        # same order /api/setup/save-key follows for the API key.
        # Under _accounts_lock, which serializes every read-modify-write of config.json
        # in this process. Without it this handler can read the file, a concurrent /logout
        # can bump AUTH_EPOCH_SEQ, and this write then puts the stale epoch back -- which
        # un-revokes the session that just logged out. config.json holds auth state, not
        # just settings, so any writer of it belongs inside this lock.
        try:
            with _core._accounts_lock:
                cfg = _core._load_config() or {}
                cfg[LIBRARY_DIR_KEY] = str(target)
                _core._save_config(cfg)
        except OSError as e:
            return jsonify({"error": "Couldn't save the setting: {}".format(
                _redact_host_paths(str(e)))[:160]}), 200
        has_catalog = (target / "catalog.db").exists()
        return jsonify({"ok": True, "path": str(target), "has_catalog": has_catalog,
                        "supervised": _supervised(), "restart_needed": str(target) != str(out_dir)})

    @app.route("/api/server/restart", methods=["POST"])
    def api_server_restart():
        """Restart the server from the browser. Needs the managed launcher (Serve Gallery),
        which relaunches on exit code 42; otherwise the process would just stop. Login required (any session, local or LAN)."""
        if not _supervised():
            return jsonify({"error": "Restart needs the managed launcher — start via "
                                     "'Serve Gallery'. (Stop still works.)"}), 409
        busy = _job_busy()                       # same rule as Stop -- see api_server_stop
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't restart while it works).".format(busy)}), 409
        _schedule_server_exit(42)
        return jsonify({"ok": True, "action": "restart"})

    @app.route("/export-csv")
    def export_csv_download():
        """Download the catalog as a CSV -- from the browser you get a real file (Downloads),
        not a copy silently written into the backup folder. Built in memory. Authorized only.
        (The CLI --export-csv still writes to disk on purpose, for scripting.)

        Honours the gallery grid's OWN filter query string (?q=&model=&collection=&rating_min=
        &media=&from_year=...), so exporting from a filtered view exports that view rather
        than the whole library. With no filter args it stays the full dump it has always
        been -- load_catalog, not query_catalog, because the latter's `filename != ''`
        would quietly drop rows whose file isn't on disk yet."""
        import io
        import datetime
        filters = _filters_from_args(request.args)
        if filters:
            # ONE unpaginated query (page_size=None), deliberately. This used to COUNT the
            # matches and then ask a SECOND, later query for exactly that many rows, with no
            # lock or transaction across the pair -- so a catalog write landing in the gap
            # left the second query's LIMIT sized to the OLD count. The everyday case is not
            # exotic: "Sync now" is a Panel job that inserts rows for minutes at a time while
            # the owner keeps browsing, and the export it produced mid-sync shipped fewer
            # rows than matched with nothing in the file saying so. A single SELECT reads one
            # snapshot and cannot disagree with itself. `sort` isn't a filter (it never
            # changes WHICH rows match) so it stays a separate argument -- and an unknown
            # value falls back to the default order inside query_catalog.
            rows, _ = query_catalog(db_path, page=1, page_size=None,
                                    sort=request.args.get("sort", "newest"), **filters)
        else:
            rows = load_catalog(db_path)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({f: r.get(f, "") for f in CATALOG_FIELDS})
        mem = io.BytesIO(buf.getvalue().encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="text/csv", as_attachment=True,
                         download_name="moonglade-catalog-{}.csv".format(
                             datetime.date.today().isoformat()))

    @app.route("/api/panel/run", methods=["POST"])
    def api_panel_run():
        """Start a whitelisted maintenance job as a background subprocess. Safe/read-only
        actions are open to any authorized session (local or logged-in LAN); destructive
        actions (file-changing -- organize, dedup --apply, rebuild-thumbnails) additionally
        require the request to be from the local machine itself, same trust tier as
        /api/branding/shortcut -- a logged-in LAN account can generate and browse, but not
        run destructive maintenance on the owner's local files. Destructive actions also
        require confirm=true."""
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip()
        spec = PANEL_ACTIONS.get(action)
        if not spec:
            return jsonify({"error": "unknown action"}), 400
        if spec["destructive"] and not _is_local_request():
            return jsonify({"error": "this action changes files; localhost-only"}), 403
        if spec["destructive"] and not body.get("confirm"):
            return jsonify({"error": "this action changes files; confirm required"}), 400
        try:
            # `n` is only consumed by an int_param action (test-pull); _panel_run
            # clamps it into range and ignores it otherwise, so passing it always is safe.
            # The busy check lives INSIDE _panel_run, under the same lock that claims the
            # slot -- checking it here first would just be the race again.
            if not _panel_run(action, int_arg=body.get("n")):
                return jsonify({"error": "a job is already running"}), 409
            return jsonify({"ok": True, "action": action, "label": spec["label"]})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    def _close_orphan_if_resolved(tid, media_ids, is_video):
        """A task-id recovery (below) just independently confirmed real media for `tid`.
        If `tid` ALSO has its own job entry that's still non-terminal -- the orphan case:
        api_task_status()'s own done/failed write never ran for it (its polling browser
        tab stopped, or a transient exception left it at 'running' per that route's
        deliberate design), so it's been spinning in the Activity card forever even
        though the generation finished -- close THAT original entry too, not just the
        new 'import-<suffix>' job api_import_task logs for the recovery action itself.
        Otherwise the Activity card keeps showing a phantom stuck spinner permanently
        disconnected from reality, even after the real media has landed.

        Writes the EXACT event shape api_task_status()'s own done branch writes
        (status='done', media_ids, is_video) so a reader of jobs.jsonl can't tell "task-
        status resolved it" from "a manual recovery resolved it" -- same file, same
        fields, same convention.

        Reads the RAW reconstructed log (core._reconstruct_jobs), not read_jobs()'s
        filtered view, so a very old orphan -- one read_jobs() would already be hiding
        past JOBS_MAX_AGE -- still gets closed rather than silently left at 'running' in
        the log forever. Skips a job the owner already dismissed (respects that explicit
        action instead of resurrecting it with a new event). Fails soft: the recovery
        itself must succeed even if this bookkeeping doesn't."""
        try:
            import moonglade_backup as _core
            jobs_by_id, _order, _n = _core._reconstruct_jobs(out_dir)
            orig = jobs_by_id.get(tid)
            if orig and not orig.get("dismissed") and orig.get("status") not in _core._JOBS_TERMINAL:
                _log_job(tid, status="done", media_ids=media_ids, is_video=is_video)
        except Exception:                          # noqa: BLE001 -- bookkeeping must not break recovery
            pass

    @app.route("/api/import-task", methods=["POST"])
    def api_import_task():
        """Pull ONE generation/edit task's media into the gallery by its task id -- recovers
        edits + anything stuck in Favorites that --update's listing skips (edits aren't in that
        listing). Downloads the owner's OWN finished media; spends nothing.

        LOGIN tier, deliberately -- any signed-in session, local or LAN. This docstring
        used to say "Localhost-only", which was never true of the code and is exactly the
        bait a route-gating audit warned about: a stale claim like this invites someone to
        "restore" a gate that was never there, silently breaking the LAN-recovery case.
        The real tier is pinned by tests/test_route_tiers.py.

        Logs to the Activity card. Returns {saved, media_ids, is_video} or {error}."""
        tid = str((request.get_json(silent=True) or {}).get("task_id") or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "enter a numeric task id"}), 200
        # "Look behind the milk": if this task is already catalogued, don't re-fetch --
        # just report it's here + hand back its media so the UI can jump straight to it.
        con = _connect(db_path)
        try:
            pre_rows = con.execute(
                "SELECT media_id, is_video FROM catalog WHERE task_id=?", (tid,)).fetchall()
        finally:
            con.close()
        if pre_rows:
            pre = [r[0] for r in pre_rows]
            _close_orphan_if_resolved(tid, pre, bool(pre_rows[0][1]))
            return jsonify({"ok": True, "already": True, "saved": 0, "media_ids": pre})
        job_id = "import-" + tid[-8:]
        _log_job(job_id, status="running", type="import", label="Import task " + tid)
        try:
            core, session = _gen_session()
            res = _collect_single_flight(core, session, tid)
            n, mids = int(res.get("saved") or 0), (res.get("media_ids") or [])
            _log_job(job_id, status="done", media_ids=mids,
                     label="Imported {} media from task {}".format(n, tid))
            if mids:
                _close_orphan_if_resolved(tid, mids, bool(res.get("is_video")))
            return jsonify({"ok": True, "saved": n, "media_ids": mids,
                            "is_video": bool(res.get("is_video"))})
        except Exception as e:
            _log_job(job_id, status="failed", error=_redact_host_paths(str(e))[:200])
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/panel/status")
    def api_panel_status():
        """Live state of the running maintenance job, for the Panel's progress UI.

        `lines` is LOOPBACK-ONLY; the rest of the payload is not. The two halves of this
        response are different KINDS of data: status/action/label/rc/progress describe the
        job, but `lines` is the maintenance subprocess's own stdout -- absolute paths out of
        the owner's install, catalog internals, and whatever a CLI traceback happens to
        print. That is host detail, and Moonglade is explicitly not single-user, so a
        logged-in LAN account must not be able to poll it. See the Trust & Safety wiki page.

        Found 2026-07-21 by an adversarial review: STARTING a destructive job was gated
        (api_panel_run's `spec["destructive"] and not _is_local_request()`) and CANCELLING
        one was gated (api_panel_cancel), but READING the output was a bare `@app.route`
        with no tier check at all -- the one door in the set nobody had shut.

        Deliberately NOT a whole-route LOCALHOST gate, which is the obvious-looking fix and
        is wrong here: 14 of the 20 PANEL_ACTIONS are non-destructive, and a LAN account is
        allowed to run every one of them (api_panel_run only requires loopback when
        `spec["destructive"]`). Gating the whole route would let that account start a job
        and then watch a progress UI that never moves, across all three pollers (the Panel,
        the job tray, and the resume-on-load check). Redacting one field closes the leak
        without taking away anything a LAN caller is entitled to. The tier table entry
        therefore correctly stays LOGIN (tests/test_route_tiers.py).

        The replacement line is a real line rather than `[]` so the log area explains itself
        instead of just rendering blank, which reads as a bug -- the consumer at ~7385 does
        `if (d.lines) { log.textContent = d.lines.join('\\n') }`, and `[]` is truthy in JS."""
        local = _is_local_request()
        with _panel_lock:
            lines = (list(_panel_job["lines"]) if local
                     else ["(job output is shown only on the server's own screen)"])
            return jsonify({"status": _panel_job["status"], "action": _panel_job["action"],
                            "label": _panel_job["label"], "rc": _panel_job["rc"],
                            "progress": _panel_job["progress"],
                            "warn_count": _panel_job.get("warn_count") or 0,
                            "lines": lines})

    @app.route("/api/watch/status")
    def api_watch_status():
        """Live-mirror watcher health: is the push WebSocket connected right now, when
        did it last see an event, how many gens has it mirrored this server run."""
        with _watch_lock:
            return jsonify(dict(_watch_status))

    @app.route("/api/panel/cancel", methods=["POST"])
    def api_panel_cancel():
        """Stop the running maintenance job from the browser (no Task Manager). Terminates the
        subprocess; the reader marks it 'cancelled'.

        LOCALHOST-ONLY, and the check below is load-bearing: it was silently deleted in
        commit 0fd8cee -- the very commit that built the two-tier model for the sibling
        route /api/panel/run -- while this docstring's "Localhost-only" claim survived.
        Restored 2026-07-19 after a route-gating audit. This is the paired STOP control
        for jobs whose START requires loopback, so admitting a LAN caller here is the
        same trust violation from the other end: organize flushes its undo manifest per
        row but only writes catalog_updates via save_catalog() AFTER the loop, so a
        mid-run terminate leaves files physically moved on disk while catalog.db still
        points at their old paths. Undo survives; catalog/disk coherence does not."""
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
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:140]}), 200
        return jsonify({"ok": True, "action": "cancel"})

    @app.route("/api/panel/schedule", methods=["GET", "POST"])
    def api_panel_schedule():
        """Panel settings: the automated-task schedule + the download-workers count. GET
        returns the current settings; POST MERGES only the fields present (so the schedule
        toggle and the workers selector -- two separate controls writing this one file --
        never wipe each other). Only non-destructive actions are schedulable.

        GET is login-only so a LAN session's Panel still renders the current settings.
        WRITING is LOCALHOST-ONLY -- that check was silently dropped in commit 0fd8cee
        while this docstring's claim survived; restored 2026-07-19 after a route-gating
        audit. It matters more than "it's only settings" suggests: `sync-videos` is a
        real PANEL_ACTIONS key with destructive=False AND panel_visible=False, so a LAN
        caller could schedule a full-history feed sync at 16 workers, hourly, forever,
        surviving restarts -- via a background-only job with no Panel button, so the
        owner would never see it configured. And `workers` is not schedule-scoped:
        _panel_run reads it for EVERY run including the owner's own local button
        clicks, so this endpoint also sets the concurrency of local maintenance jobs."""
        if request.method == "POST" and not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
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

    def _batch_sibling_count(task_id):
        """How many catalog rows share this task. Used to say, before anything is deleted,
        whether the picture is one of a batch or the only one this task made -- because
        `deleteBatchMedia` on a task's last image is a different act from trimming one frame
        out of four, and the dialog should not make them look the same."""
        tid = str(task_id or "").strip()
        if not tid:
            return 0
        try:
            with sqlite3.connect(str(db_path)) as con:
                return int(con.execute(
                    "SELECT COUNT(*) FROM catalog WHERE task_id = ?", (tid,)).fetchone()[0])
        except sqlite3.Error:
            return 0

    @app.route("/api/delete-image", methods=["POST"])
    def api_delete_image():
        """Delete ONE image from its task on PixAI, leaving the task and its siblings alone.

        The finer-grained partner to /delete-tasks-bulk, which is task-level: deleting any
        image there takes the whole batch. Same trust tier and for the same reason --
        LOCALHOST-only, because this destroys on the owner's real cloud account, and a
        logged-in LAN session unlocks browsing and spending, not irreversible deletion.

        Local purge follows the cloud delete, exactly as the task-level path does, so cloud
        and catalog never drift. Order matters: if the cloud call fails, nothing local is
        touched and the image is still there to try again. The reverse order would leave a
        hole in the catalog for an image that still exists on PixAI.

        `confirm` is required -- the typed-DELETE prompt is the client's half of the same
        gate, and a route that acted without it would make that prompt decorative.
        """
        import moonglade_backup as core          # lazy: avoid import cycle
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "not confirmed"}), 400
        mid = str(body.get("media_id") or "").strip()
        row = get_row(db_path, mid) if mid else None
        if not row:
            return jsonify({"error": "No such image in the catalog."}), 200
        tid = str(row.get("task_id") or "").strip()
        if not tid:
            # An imported local file has no PixAI task behind it, so there is nothing on
            # their side to delete. Saying so beats a confusing API error, and points at the
            # control that DOES apply to it.
            return jsonify({"error": "This image was imported from your computer \u2014 PixAI "
                                     "has no copy to delete. Use Delete to remove it here."}), 200
        try:
            # _make_session takes a REQUIRED positional; every other call site in this
            # file passes None. Omitting it raised TypeError on every click, which the
            # except below turned into a 200 error body -- so the feature was dead while
            # looking like a PixAI-side failure.
            _core_session = core._make_session(None)
            core.delete_batch_media_gql(_core_session, tid, mid)
        except Exception as e:                        # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:240]}), 200
        try:
            purge_media_local(out_dir, thumb_dir, db_path, mid, row.get("filename"))
        except OSError as e:
            # The cloud delete above already happened and cannot be taken back, so a local
            # purge that fails has to come back through this route's own error contract
            # rather than a 500: the row (and the file) are still here, now pointing at an
            # image PixAI no longer has, and only the user can decide to retry.
            return jsonify({"error": "Deleted on PixAI, but the local copy could not be "
                                     "moved to the trash folder: "
                                     + _redact_host_paths(str(e))[:160]}), 200
        telem_bump("culled", out_dir=out_dir)
        return jsonify({"ok": True, "media_id": mid, "task_id": tid})

    @app.route("/api/delete-local", methods=["POST"])
    def api_delete_local():
        """JSON twin of /delete-bulk (and /delete/<id>) for fetch()-driven clients:
        quarantine the selected media to out_dir/_deleted/ through the SAME
        purge_media_local path the page routes use, so /api/trash/restore undoes it,
        minus the redirect-with-banner plumbing. LOGIN tier, exactly like the page
        routes it mirrors: local quarantine is reversible library curation, not
        cloud destruction (that is /api/delete-tasks, a different tier). The page
        routes stay -- classic still posts forms at them.

        Deduped via dict.fromkeys for the same reason /api/delete-preview does it:
        the count describes FILES quarantined, so a repeated id must not inflate it.
        Per-file OSError keeps the loop going, exactly as /delete-bulk's does -- one
        file the OS won't release must not strand the rest -- and comes back as a
        `failed` count with ok=false instead of a delerr banner."""
        body = request.get_json(silent=True) or {}
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        purged = failed = 0
        for mid in media_ids:
            row = get_row(db_path, mid)
            if not row:
                continue
            try:
                purge_media_local(out_dir, thumb_dir, db_path, mid, row.get("filename"))
                purged += 1
            except OSError:
                failed += 1
        if purged:
            telem_bump("culled", purged, out_dir=out_dir)           # The Great Sweep
        return jsonify({"ok": failed == 0, "count": purged, "failed": failed})

    def _purge_local(media_id, filename):
        """Remove a media's catalog row + thumbnail; quarantine its file to _deleted/
        (recoverable) rather than destroying it."""
        purge_media_local(out_dir, thumb_dir, db_path, media_id, filename)

    def _resolve_delete_targets(con, media_ids):
        """The shared selection -> (task ids, local-only rows) resolution behind BOTH
        /api/delete-preview and delete_tasks_bulk. Shared rather than copied so the
        preview cannot drift from the action it previews: a dialog that lists a different
        blast radius than the delete then takes is worse than showing nothing at all.

        Returns (sel_rows, task_ids, local_only) where task_ids is sorted+deduped (one
        cloud delete per task no matter how many of its images were selected) and
        local_only holds the rows with no task id at all -- imports, which have nothing
        on PixAI to delete and are purged locally only."""
        sel_rows = [con.execute(
            "SELECT media_id, task_id, filename FROM catalog WHERE media_id=?", (m,)
        ).fetchone() for m in media_ids]
        sel_rows = [dict(r) for r in sel_rows if r]
        task_ids = sorted({(r.get("task_id") or "").strip()
                           for r in sel_rows if (r.get("task_id") or "").strip()})
        local_only = [r for r in sel_rows if not (r.get("task_id") or "").strip()]
        return sel_rows, task_ids, local_only

    # sqlite's default host-parameter ceiling is 999, and this is well inside it while
    # still cutting a big selection to a handful of passes.
    _TASK_CHUNK = 400

    def _members_of_tasks(con, task_ids):
        """{task_id: [row, ...]} for every media in the given tasks, in ONE chunked pass
        instead of a query per task.

        `catalog` indexes media_id (its PRIMARY KEY), created_at, model_name, rating and
        batch -- there is NO index on task_id, so each `WHERE task_id=?` is a full table
        scan. Measured on a 36,000-row catalog: 24 such queries cost 216ms, 100 cost
        1.04s and 800 cost 8.6s, all of it inside the request /api/delete-preview's
        dialog is waiting on; the same 800 tasks fetched with chunked `IN` cost 38ms.
        Rows come back grouped and sorted here rather than relying on the query's order,
        because one statement now returns several tasks interleaved."""
        out = {}
        for i in range(0, len(task_ids), _TASK_CHUNK):
            chunk = task_ids[i:i + _TASK_CHUNK]
            rows = con.execute(
                "SELECT media_id, task_id, is_video, poster_media_id FROM catalog "
                "WHERE task_id IN ({})".format(",".join("?" * len(chunk))), chunk)
            for r in rows:
                out.setdefault(r["task_id"], []).append(r)
        for members in out.values():
            members.sort(key=lambda r: r["media_id"])
        return out

    def _preview_entry(row, selected_ids):
        """One /api/delete-preview media entry: what it is, whether the user actually
        picked it, and the media_id whose thumbnail exists on disk -- or None for
        `thumb`, so the client renders an id chip instead of a broken image. Videos fall
        back to their still-frame poster's thumb exactly as the gallery grid does (older
        sync runs never generated the video's own)."""
        mid = row["media_id"]
        thumb = None
        if (thumb_dir / "{}.jpg".format(mid)).exists():
            thumb = mid
        elif row["is_video"] == "1" and row["poster_media_id"]:
            poster = row["poster_media_id"]
            if (thumb_dir / "{}.jpg".format(poster)).exists():
                thumb = poster
        return {"media_id": mid, "is_video": row["is_video"] == "1",
                "selected": mid in selected_ids, "thumb": thumb}

    @app.route("/api/delete-preview", methods=["POST"])
    def api_delete_preview():
        """What "Delete from PixAI" would actually take, listed image by image, before
        anything fires. Read-only: a few catalog reads, no network, no PixAI call.

        Deleting on PixAI is TASK-level -- selecting one image of a batch deletes the
        whole batch, cloud AND local. The confirm dialog said that in prose but never
        showed WHICH siblings, so the single irreversible action in this app was also
        the only one whose real scope the user could not see before committing to it.
        This resolves the selection through _resolve_delete_targets (the same helper
        delete_tasks_bulk uses, deliberately) and then expands each task to its full
        catalog membership.

        LOCALHOST, mirroring the action it previews rather than the data it reads. The
        catalog rows themselves are ordinary LOGIN-tier browsing material (a LAN
        session can already list a whole batch via ?batch=<task_id>), so this is not
        about hiding them -- it is that the preview exists only as step one of a
        LOCALHOST flow whose button a LAN session cannot even see, and a preview
        reachable at a lower tier than its action is a gap waiting to be mistaken for
        an entry point. Weakens nothing: /delete-tasks-bulk still re-checks for itself.

        Truncation is DISPLAY-only (DELETE_PREVIEW_TASK_CAP): `totals` always describes
        the entire selection, because the totals are what the user reads to decide."""
        if not _is_local_request():
            return jsonify({"error": "deleting from PixAI is localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        # dict.fromkeys: deduped, order preserved. The blast radius is a set of FILES, so
        # a repeated id must not inflate "you picked N" (or drive `unselected` negative)
        # just because a caller sent the same one twice.
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400

        con = _connect(db_path)
        try:
            sel_rows, task_ids, local_only = _resolve_delete_targets(con, media_ids)
            selected = {r["media_id"] for r in sel_rows}
            members_by_task = _members_of_tasks(con, task_ids)
            tasks, total_media = [], 0
            for tid in task_ids:
                members = members_by_task.get(tid, [])
                total_media += len(members)
                if len(tasks) >= DELETE_PREVIEW_TASK_CAP:
                    continue          # keep counting, stop describing
                tasks.append({"task_id": tid,
                              "media": [_preview_entry(m, selected) for m in members]})
            # Imports have no task, so nothing about them is task-level -- but they ARE
            # part of what the button removes, and the dialog has to show them or its
            # file count won't add up. Capped on the same DISPLAY budget as the tasks.
            shown_local = [con.execute(
                "SELECT media_id, is_video, poster_media_id FROM catalog WHERE media_id=?",
                (r["media_id"],)).fetchone()
                for r in local_only[:DELETE_PREVIEW_TASK_CAP]]
            local_entries = [_preview_entry(m, selected) for m in shown_local if m]
        finally:
            con.close()

        return jsonify({
            "tasks": tasks,
            "local_only": local_entries,
            "truncated": (len(task_ids) > len(tasks)
                          or len(local_only) > len(local_entries)),
            "totals": {
                "selected": len(sel_rows),
                "tasks": len(task_ids),
                "media": total_media + len(local_only),
                "unselected": total_media + len(local_only) - len(sel_rows),
                "local_only": len(local_only),
            },
        })

    def _start_bulk_delete(task_ids, local_only, purge_local=True):
        """The shared engine behind BOTH /delete-tasks-bulk (form/redirect) and
        /api/delete-tasks (JSON) -- extracted from the former verbatim so the two
        routes cannot drift in what they actually DO, only in how they answer.
        Kicks the delete off-thread, reporting to the Activity card exactly as
        before.

        Returns (job_id, total, err): started when err is None; otherwise err is
        "busy" (a bulk delete is already running -- single-flight held) or
        "thread" (the worker thread could not start; single-flight released and
        the failure already logged to the job card). Callers check total > 0
        themselves -- this helper assumes there is work.

        purge_local=False is the JSON route's cloud-only mode (the CLI
        --delete-task behavior: cloud gone, local files + catalog intact). It
        drops the local_only imports HERE, not in the caller, because with no
        cloud side they would otherwise be pure local purges -- exactly what the
        flag says not to do."""
        import uuid
        import moonglade_backup as core   # lazy: avoid import cycle
        if not purge_local:
            local_only = []
        total = len(task_ids) + len(local_only)

        # Single-flight: never let two bulk deletes interleave their cloud calls.
        with _bulkdel_lock:
            if _bulkdel_running["on"]:
                return None, total, "busy"
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
                    if purge_local:
                        con2 = _connect(db_path)
                        try:
                            media = con2.execute(
                                "SELECT media_id, filename FROM catalog WHERE task_id=?", (tid,)
                            ).fetchall()
                        finally:
                            con2.close()
                        for m in media:
                            try:
                                _purge_local(m[0], m[1]); removed += 1
                            except OSError:
                                # This task's cloud delete has ALREADY fired, so one file the
                                # OS won't let go of must not take the whole loop down with it:
                                # every task still queued would be left deleted on PixAI but
                                # live in the catalog, and nothing would say so.
                                failed += 1
                    done += 1; _tick()
                for r in local_only:
                    try:
                        _purge_local(r["media_id"], r.get("filename")); removed += 1
                    except OSError:
                        failed += 1
                    done += 1; _tick()
                summary = "Deleted {} · purged {} local · {} failed".format(deleted, removed, failed)
                # ANY failure is a non-clean result -- surface it RED on the card. Don't bury
                # "3 failed" inside a green 'done': those tasks still exist on PixAI (drift).
                status = "failed" if failed else "done"
                _log_job(job_id, status=status, label=summary, done=total, total=total,
                         error=(summary if failed else None))
            except Exception as e:                               # noqa: BLE001
                _log_job(job_id, status="failed", error=_redact_host_paths(str(e))[:200])
            finally:
                with _bulkdel_lock:
                    _bulkdel_running["on"] = False

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception as e:                               # noqa: BLE001 -- OS thread exhaustion, etc.
            with _bulkdel_lock:                              # never wedge single-flight forever
                _bulkdel_running["on"] = False
            _log_job(job_id, status="failed", error="could not start delete thread: " + _redact_host_paths(str(e))[:160])
            return None, total, "thread"
        return job_id, total, None

    @app.route("/api/delete-tasks", methods=["POST"])
    def api_delete_tasks():
        """JSON twin of /delete-tasks-bulk: same LOCALHOST tier (and for the same
        reason -- this MUTATES THE OWNER'S REAL CLOUD ACCOUNT, irreversibly), same
        _resolve_delete_targets selection so /api/delete-preview keeps describing
        exactly what this route then does, and the same off-thread worker via
        _start_bulk_delete -- which routes every cloud delete through
        core.delete_task_gql, the single-attempt _check_read_only'd choke point the
        page route uses, never gql_adhoc. The page route stays until classic's
        demolition.

        Body: {task_ids: [...]} OR {media_ids: [...]} (task_ids win when both are
        sent -- they are already the unit the delete operates on), plus optional
        purge_local (default true, the page behavior: purge follows cloud so
        catalog and account never drift; false = cloud-only, the CLI
        --delete-task behavior, and imports are then left alone entirely).

        _check_read_only fires HERE, before the job even starts, on top of the one
        inside delete_task_gql: failing fast with one readable refusal beats
        spawning a job whose every task then fails red on the Activity card."""
        import moonglade_backup as core   # lazy: avoid import cycle
        if not _is_local_request():
            return jsonify({"error": "deleting from PixAI is localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        purge_local = bool(body.get("purge_local", True))
        task_ids = sorted({str(t).strip() for t in (body.get("task_ids") or [])
                           if str(t).strip()})
        local_only = []
        if not task_ids:
            media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
            if not media_ids:
                return jsonify({"error": "no task_ids or media_ids given"}), 400
            con = _connect(db_path)
            try:
                _sel_rows, task_ids, local_only = _resolve_delete_targets(con, media_ids)
            finally:
                con.close()
        if not purge_local:
            local_only = []          # cloud-only mode: imports have no cloud side
        if not (task_ids or local_only):
            return jsonify({"ok": True, "count": 0, "job_id": None,
                            "tasks": 0, "local_only": 0})
        if task_ids:
            try:
                core._check_read_only("delete tasks from your PixAI account")
            except core.PixAIError as e:
                return jsonify({"error": _redact_host_paths(str(e))[:240]}), 403
        job_id, total, err = _start_bulk_delete(task_ids, local_only,
                                                purge_local=purge_local)
        if err == "busy":
            return jsonify({"error": "a bulk delete is already running -- "
                                     "see the Activity card"}), 409
        if err:
            return jsonify({"error": "could not start bulk delete -- try again"}), 500
        return jsonify({"ok": True, "count": total, "job_id": job_id,
                        "tasks": len(task_ids), "local_only": len(local_only)})

    # -------------------------------------------------------------------
    # Trash / quarantine panel -- the floating panel opened from the Control
    # Panel (NOT a routed page of its own). See the 2026-07-21 audit's
    # restore-panel row for the decided design (floating overlay, directory
    # scan, restore=LOGIN, delete-forever/empty=LOCALHOST+typed confirm).
    # -------------------------------------------------------------------

    @app.route("/api/trash/list")
    def api_trash_list():
        """List out_dir/_deleted/ for the Control Panel's Trash panel -- a directory
        scan, not a catalog query (purge_media_local's whole point is that the
        catalog row is already gone by the time a file lands here). Paginated
        (?page=&limit=) so a ~12k-file quarantine never costs more than one page's
        worth of thumbnail work per request -- see list_quarantined()'s and
        _ensure_trash_thumbs()'s docstrings. Thumbnails are generated on demand for
        exactly the page returned and then served by the EXISTING /thumbs/<media_id>.jpg
        route (no new serving route needed -- see _ensure_trash_thumbs()). LOGIN tier:
        seeing what's recoverable is the same trust level as browsing the live
        gallery, not a destructive action."""
        try:
            page = max(1, int(request.args.get("page") or 1))
            limit = max(1, min(int(request.args.get("limit") or 60), 200))
        except ValueError:
            page, limit = 1, 60
        items, total, total_bytes = list_quarantined(out_dir, page=page, page_size=limit)
        _ensure_trash_thumbs(out_dir, thumb_dir, items)
        for it in items:
            it["thumb"] = "/thumbs/{}.jpg".format(it["media_id"])
        return jsonify({"items": items, "total": total, "total_bytes": total_bytes,
                        "page": page, "limit": limit})

    @app.route("/api/trash/restore", methods=["POST"])
    def api_trash_restore():
        """Restore one or more quarantined files back into the library. LOGIN tier --
        recovering something you (or anyone signed in) deleted is not the same trust
        question as permanently destroying it. Matches the decided design in
        the 2026-07-21 audit: restore=LOGIN, delete-forever/empty=LOCALHOST."""
        body = request.get_json(silent=True) or {}
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        restored, errors = [], []
        for mid in media_ids:
            res = restore_quarantined_media(out_dir, thumb_dir, db_path, mid)
            if res.get("ok"):
                restored.append(mid)
            else:
                errors.append({"media_id": mid, "error": res.get("error", "unknown error")})
        if restored:
            telem_bump("trash_restored", len(restored), out_dir=out_dir)
        return jsonify({"restored": restored, "errors": errors})

    @app.route("/api/trash/delete-forever", methods=["POST"])
    def api_trash_delete_forever():
        """Permanently destroy one or more SELECTED quarantined files -- no more
        recovery after this. LOCALHOST-only (the owner physically at the machine),
        same trust tier as /delete-tasks-bulk and the Panel's other destructive
        actions, and requires confirm=true in the body on top of that -- the same
        belt-and-suspenders shape api_panel_run already uses for its destructive
        actions. The client's own typed "DELETE" prompt (Trash.deleteSelected() in
        the Panel template, mirroring confirmBulkDeleteCloud()'s existing pattern) is
        what actually stands between a misclick and data loss; confirm=true here just
        proves the client meant to send the request at all, it is not itself the
        security boundary -- the LOCALHOST check is."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        n = sum(1 for mid in media_ids
               if delete_quarantined_forever(out_dir, thumb_dir, mid))
        telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    @app.route("/api/trash/empty", methods=["POST"])
    def api_trash_empty():
        """Empty the ENTIRE trash -- every file under out_dir/_deleted/, not just a
        selection. Same LOCALHOST + confirm=true contract as
        api_trash_delete_forever() (see its docstring); the client demands the same
        typed "DELETE" word first (Trash.emptyAll())."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        n = empty_trash(out_dir, thumb_dir)
        telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    @app.route("/api/rate/<media_id>", methods=["POST"])
    def rate(media_id):
        data = request.get_json(silent=True) or {}
        try:
            value = max(0, min(5, int(data.get("rating", 0))))
        except (TypeError, ValueError):
            return json.dumps({"ok": False}), 400, {"Content-Type": "application/json"}
        update_rating(db_path, media_id, value)
        return json.dumps({"ok": True, "rating": value}), 200, {"Content-Type": "application/json"}

    @app.route("/api/rebuild-poster/<media_id>", methods=["POST"])
    def rebuild_poster(media_id):
        """Regenerate ONE video's poster thumbnail from its file, replacing the cached
        one. For a clip whose cached poster is wrong -- e.g. a fade-in that was
        thumbnailed inside the fade before the representative-frame pick shipped
        (owner, 2026-08-22) -- without a whole --rebuild-thumbs pass. LOGIN tier like
        /api/rate: it only rewrites a regenerable local cache file, touches nothing on
        PixAI and no config. Videos only; an image's thumb is a straight resize and
        never wrong in this way."""
        if not media_id or "/" in media_id or "\\" in media_id or ".." in media_id:
            return json.dumps({"ok": False, "error": "bad id"}), 400, {"Content-Type": "application/json"}
        row = get_row(db_path, media_id)
        if not row:
            return json.dumps({"ok": False, "error": "not in the catalog"}), 404, {"Content-Type": "application/json"}
        if str(row.get("is_video") or "") != "1":
            return json.dumps({"ok": False, "error": "not a video"}), 400, {"Content-Type": "application/json"}
        # The catalog row's filename is canonical; the matcher is the fallback if the
        # file moved (and it must be told to look for VIDEO extensions -- its default
        # set is images only).
        src = out_dir / str(row.get("filename") or "")
        if not (row.get("filename") and src.is_file()):
            import moonglade_backup as core   # lazy, like every other gallery use of it
            files = find_files_for_media_id(out_dir, media_id, exts=core._VIDEO_EXTS)
            if not files:
                return json.dumps({"ok": False, "error": "video file not found"}), 404, {"Content-Type": "application/json"}
            src = Path(files[0])
        thumb = out_dir / "gallery" / "thumbs" / (media_id + ".jpg")
        ok = make_video_thumbnail(src, thumb)
        if not ok:
            return json.dumps({"ok": False, "error": "ffmpeg extract failed (is ffmpeg on PATH?)"}), 200, {"Content-Type": "application/json"}
        return json.dumps({"ok": True, "thumb": "/thumbs/" + media_id + ".jpg?v=" + str(int(time.time()))}), 200, {"Content-Type": "application/json"}

    @app.route("/api/edit-prompt/<media_id>", methods=["POST"])
    def edit_prompt(media_id):
        data = request.get_json(silent=True) or {}
        update_prompt_full(db_path, media_id, data.get("prompt", ""))
        return json.dumps({"ok": True}), 200, {"Content-Type": "application/json"}

    @app.route("/api/collection", methods=["POST"])
    def api_collection():
        """JSON twin of /collection-add + /collection-remove for fetch()-driven
        clients: one route, `action` picks the direction, same add_to_collection /
        remove_from_collection helpers underneath (comma-name scrubbing, the
        read-modify-write lock, no-op-if-already-there counting -- all of it), no
        redirect banner. LOGIN tier, exactly like both page routes it mirrors.
        `count` is rows actually CHANGED, the page banner's own number -- adding to
        a collection an image is already in counts zero, not one."""
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip()
        if action not in ("add", "remove"):
            return jsonify({"error": "action must be 'add' or 'remove'"}), 400
        name = str(body.get("collection") or "").strip()
        if not name:
            return jsonify({"error": "no collection name given"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        fn = add_to_collection if action == "add" else remove_from_collection
        return jsonify({"ok": True, "count": fn(db_path, media_ids, name)})

    @app.route("/api/replace-prompts", methods=["POST"])
    def api_replace_prompts():
        """JSON twin of /bulk-replace-prompt: same bulk_replace_prompt helper (plain
        substring find/replace over prompt_full, counting only rows that actually
        changed), no redirect banner. LOGIN tier, like the page route it mirrors.
        An empty `find` is a 400 here rather than the helper's silent 0: the page
        form can't submit one, so a JSON caller sending one is a bug worth naming."""
        body = request.get_json(silent=True) or {}
        find = str(body.get("find") or "")
        if not find:
            return jsonify({"error": "no find text given"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        changed = bulk_replace_prompt(db_path, media_ids, find,
                                      str(body.get("replace") or ""))
        return jsonify({"ok": True, "changed": changed})

    # Full images are write-once: /img/ is keyed by on-disk path and /full/ resolves to
    # the downloaded original, so the bytes behind a given URL never change. Cache those
    # forever -- pagination, back-navigation, and re-visits cost zero re-download, the
    # single biggest win on mobile / LAN.
    _IMMUTABLE = "public, max-age=31536000, immutable"

    # Thumbnails are NOT immutable, despite being keyed by media_id: `--rebuild-thumbs`
    # regenerates them IN PLACE at the same key (that is its whole job -- repairing
    # posters that ffmpeg missed). media_id is an identity, not a content hash, so an
    # `immutable` year-long cache pins the broken poster it was meant to fix. Short
    # max-age + the ETag send_from_directory already sets = a 304 on the common path.
    _THUMB_CACHE = "public, max-age=300"

    # The Sibling Strip's 32px tier (issue #30): derived from the EXISTING 768 thumb
    # (never the master), cached beside the badge cache under gallery/cache/_strip/
    # (badge_cache_dir()'s rule: regenerable caches live as siblings there, never in
    # the goods tree). Self-heals when the 768 thumb is newer (mtime) -- a rebuilt
    # poster re-cuts its strip thumb on the next request. Browser cache matches the
    # 768 thumb's own 300s policy (the block above): the strip URL carries NO ?v=, and
    # a rebuilt poster must not show its old tile for a day (adversarial review, 2026-08-22).
    _STRIP_CACHE = _THUMB_CACHE   # same 300s as the 768: media_id is an identity, not a hash
    _STRIP_ID_OK = re.compile(r"[0-9A-Za-z_-]+")

    def strip_cache_dir():
        return out_dir / "gallery" / "cache" / "_strip"

    def _strip_thumb(media_id):
        """Path of the cached 32px strip thumb for media_id, (re)cut from the 768
        thumb when missing or stale. None when there is no 768 thumb to derive from
        or the cut fails -- the caller then falls through to the normal thumb."""
        # ALLOWLIST the id here, inside the helper, so every caller is covered. A
        # denylist of / \ .. missed the Windows drive letter: pathlib's `/` RESETS to
        # a drive-relative path when the right operand carries one, so
        # thumb_dir / "C:x.jpg" == Path("C:x.jpg") == the drive ROOT -- and
        # send_from_directory would then serve C:\x.jpg (adversarial review,
        # 2026-08-22). Catalog ids are numeric (or local_<hex>); nothing else is valid.
        if not _STRIP_ID_OK.fullmatch(media_id or ""):
            return None
        src = thumb_dir / (media_id + ".jpg")
        if not src.is_file():
            return None
        dst = strip_cache_dir() / (media_id + ".jpg")
        try:
            src_mtime = src.stat().st_mtime
            if dst.is_file() and dst.stat().st_mtime >= src_mtime:
                return dst
            from PIL import Image
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Atomic: cut to a temp file and os.replace it in. An in-place save that died
            # mid-write (disk full, kill) left a truncated file carrying a FRESH mtime,
            # which then passed the staleness check and was served for the whole
            # cache window; a concurrent reader (4 siblings render the same URL at once
            # on a threaded server) could also read a half-written file.
            tmp = dst.with_suffix(".tmp")
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    im.thumbnail((32, 32))
                    im.save(tmp, "JPEG", quality=80)
                os.replace(tmp, dst)
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            return dst
        except Exception:
            return None

    @app.route("/thumbs/<media_id>.jpg")
    def thumb(media_id):
        # ?s=32 is an allowlist of exactly one size; anything else is the 768 thumb.
        if (request.args.get("s") or "") == "32" and "/" not in media_id \
                and "\\" not in media_id and ".." not in media_id:
            p = _strip_thumb(media_id)
            if p is not None:
                resp = send_from_directory(str(p.parent), p.name, max_age=86400)
                resp.headers["Cache-Control"] = _STRIP_CACHE
                return resp
        resp = send_from_directory(str(thumb_dir), "{}.jpg".format(media_id),
                                   max_age=300)
        resp.headers["Cache-Control"] = _THUMB_CACHE
        return resp

    @app.route("/video-file/<media_id>")
    def video_file(media_id):
        row = get_row(db_path, media_id)
        if not row or row.get("is_video") != "1":
            return "Video not found.", 404
        # Resolved through _find_local_video_file -- the SAME question the detail page asks
        # before it decides to draw a player at all. This route used to answer a narrower
        # one: it served `row["filename"]` and 404'd if that column was blank (an older row,
        # or one written before the download settled on a name) or stale (`--organize` moved
        # the clip, a re-download landed it under a different name). detail() has the
        # media-id fallback and this did not, so the two could disagree -- and when they
        # disagree the page renders <video><source> over a 404, which is a dead black box
        # with no message: M30's exact symptom, surviving on top of M30's own fix. An
        # existence check is only worth having if it is answered by whatever will serve the
        # bytes, so there is one resolver and both callers ask it.
        p = _find_local_video_file(media_id, row=row)
        if p is None:
            return "Video not found.", 404
        try:
            rel = str(p.relative_to(out_dir)).replace("\\", "/")
        except ValueError:
            # Only reachable if a catalog `filename` escaped the backup folder (an absolute
            # path, or one with ..). send_from_directory would refuse it below anyway; doing
            # it here keeps "found" meaning the same thing to the resolver and to the serve.
            return "Video not found.", 404
        # send_from_directory supports HTTP Range, so the <video> can seek
        resp = send_from_directory(str(out_dir), rel, max_age=31536000)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/full/<media_id>")
    def full_image(media_id):
        # Resolve a media_id to its full-res file on the fly (used by the
        # lightbox so the index page doesn't precompute 250 image paths).
        row = get_row(db_path, media_id)
        p = find_image_file(out_dir, media_id, row.get("filename") if row else "")
        if not p or not p.exists():
            return "Not found", 404
        # ?dl=1 -> force a SAVE with the real filename (the detail page's plain Download);
        # without it, inline (the lightbox displays the image). Same file either way.
        dl = bool(request.args.get("dl"))
        resp = send_from_directory(str(p.parent), p.name, max_age=31536000,
                                   as_attachment=dl, download_name=(p.name if dl else None))
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp

    @app.route("/export-zip", methods=["POST"])
    def export_zip():
        # Stream a ZIP of the selected files. Default is STORED (no recompression) --
        # they're already compressed. Optional export-time transforms: convert to
        # PNG/JPEG (`fmt`) and/or embed prompt+ids into the file (`embed`). Both run on a
        # COPY in a temp dir and are discarded after zipping -- the catalog and the
        # originals on disk are NEVER touched, and a converted file never re-enters the
        # catalog as a new row (the decided shape; the archive stays exactly as PixAI
        # delivered it). Videos are always passed through as-is (Pillow can't transform mp4).
        import io
        import zipfile
        import shutil
        import tempfile
        import moonglade_backup as core
        # Two entry points: a curated SELECTION (media_ids from the grid) or a whole
        # COLLECTION by name. For a collection we resolve its FULL membership here in SQL
        # (up to the same 2000 cap) rather than trusting the rendered checkboxes -- "download
        # this collection" must mean every item in it, even across pages the grid never
        # loaded. There is no "zip the entire catalog" path: absent both, ids is empty -> 404.
        coll = (request.form.get("collection") or "").strip()
        if coll:
            rows_c, _ = query_catalog(db_path, collection=coll, page=1, page_size=2000)
            ids = [r["media_id"] for r in rows_c]
        else:
            ids = request.form.getlist("media_ids")
        fmt = (request.form.get("fmt") or "original").lower()
        if fmt not in ("original", "png", "jpeg"):
            fmt = "original"
        embed = (request.form.get("embed") or "") in ("1", "true", "on", "yes")
        transforming = (fmt != "original") or embed
        tmp = tempfile.mkdtemp(prefix="mg_export_") if transforming else None
        mem = io.BytesIO()
        n = 0
        # convert_image()/embed_metadata() never raise -- they report failure via a
        # returned/discarded status NOTE and quietly hand back the untouched original. That
        # note used to be thrown away (convert's into `_note`, embed's not even captured),
        # so "export as JPEG + embed prompt" could silently ship untouched originals with
        # zero signal anywhere. This is a plain form POST -> file-download response (see
        # doExportDownload() in the page's own JS): there's no fetch/JSON leg for a status
        # message to ride, so the only channel that survives the download is a small report
        # INSIDE the zip itself, added only when something actually needed reporting.
        warnings = []
        try:
            with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
                seen_names = set()
                for mid in ids[:2000]:  # safety cap
                    row = get_row(db_path, mid)
                    if not row:
                        continue
                    p = find_image_file(out_dir, mid, row.get("filename"))
                    if not p or not p.exists():
                        continue
                    src = p
                    if tmp and not row.get("is_video"):
                        # Transform a COPY only -- never the original file.
                        work = Path(tmp) / p.name
                        try:
                            shutil.copy2(p, work)
                            if fmt != "original":
                                work, note = core.convert_image(work, fmt, keep_original=False)
                                if note not in ("ok", "already"):
                                    warnings.append("{}: convert to {} -> {} (shipped as-is)"
                                                     .format(p.name, fmt, note))
                            if embed:
                                enote = core.embed_metadata(work, {
                                    "prompt": row.get("prompt_full") or row.get("prompt") or "",
                                    "media_id": mid, "task_id": row.get("task_id") or "",
                                    "model": row.get("model") or "", "seed": row.get("seed") or "",
                                    "date": row.get("created_at") or ""})
                                if enote != "ok":
                                    warnings.append("{}: embed prompt -> {} (not embedded)"
                                                     .format(p.name, enote))
                            src = work
                        except Exception as e:
                            src = p        # any transform failure -> ship the original untouched
                            warnings.append("{}: transform failed ({}) -- shipped the original"
                                             .format(p.name, _redact_host_paths(str(e))[:120]))
                    name = src.name
                    if name in seen_names:
                        name = "{}_{}".format(mid, src.name)
                    seen_names.add(name)
                    z.write(src, arcname=name)
                    n += 1
                if warnings:
                    report = ("Some files in this export did not convert and/or embed the prompt "
                               "as requested -- they were shipped as their original file instead:\n\n"
                               + "\n".join(warnings) + "\n")
                    z.writestr("_export_warnings.txt", report)
            if not n:
                return "No matching images found.", 404
            mem.seek(0)
            resp = send_file(mem, mimetype="application/zip", as_attachment=True,
                             download_name="moonglade_selection_{}.zip".format(n))
            if warnings:
                resp.headers["X-Export-Warnings"] = str(len(warnings))
            return resp
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)   # bytes are already in `mem`

    # --- Generation surface (owner-only: local, or a logged-in LAN session) --
    # The Generate drawer talks to PixAI with the OWNER's API key and can spend
    # credits. Every generation endpoint (and the rest of the ~44-site LAN-auth
    # conversion -- panel, Loom, snippets/presets, branding writes, jobs,
    # account/claims) is gated to _is_authorized_request(), NOT this narrower
    # _is_local_request() -- exposing the gallery on the LAN (--host 0.0.0.0)
    # must never let an UNAUTHENTICATED device use the key or spend credits, but
    # a logged-in LAN session is deliberately trusted the same as the owner at
    # the keyboard (see CHANGELOG.md's "Real session-based web login" entry).
    # _is_local_request() itself now backs only the one deliberately-narrower
    # exception (/api/branding/shortcut, which shells out to the SERVER machine's
    # own PowerShell/COM) -- see that route's docstring.
    #
    # FAILS CLOSED on a missing/empty remote_addr: a prior version treated
    # "" as local, which is safe under
    # THIS app's actual deployment (app.run() -> Werkzeug's dev server always
    # populates remote_addr from the real TCP peer, never blank/None -- a plain
    # HTTP client cannot spoof it), but is a fail-OPEN default in a function
    # that now also gates the first-account bootstrap form/POST (above) plus
    # destructive Panel actions and /api/branding/shortcut (below) -- worth
    # being fail-closed on principle given how much rides on it, in case this
    # app is ever run behind a proxy/WSGI shim that doesn't populate the key.
    def _is_local_request():
        ra = (request.remote_addr or "").strip()
        return ra in ("127.0.0.1", "::1", "localhost")

    def _is_authorized_request():
        """THE canonical authorization gate for every network-originated request:
        true ONLY for a request carrying a valid logged-in session (see /login
        below). Deliberately has NO localhost/loopback bypass -- login is
        required on every path, localhost hostname or IP included; no request
        address is a trusted tier. A fresh install creates its
        first account either via `python moonglade_backup.py --add-web-user`
        or, while no accounts exist yet, through /login's own local-only
        bootstrap_mode form -- see login()'s docstring below for the real,
        shipped web-based bootstrap flow; account creation is NOT CLI-only.
        That bootstrap lives entirely inside login()'s own narrower gate, not
        here: `_is_authorized_request()` itself still has no bypass of any kind,
        so the web app remains unreachable, from any address including
        127.0.0.1, to anything but /login until an account exists and signs in.
        `_is_local_request()` still exists and is still used, but ONLY as an
        independent, stricter, ADDITIONAL requirement on the couple of routes
        that must never run for a remote session even when logged in
        (/api/branding/shortcut, destructive Panel actions) -- it is no longer
        consulted here.

        Every genuine access-control gate that used to read `_is_local_request()`
        was converted to this during the LAN-auth pass; a few purely-informational
        uses (a template flag, an enrichment branch) were also broadened here for
        consistency with the gates they mirror -- see CHANGELOG.md for the
        site-by-site list. It's a plain function closed over this app's
        `session`, so any FUTURE route added inside this same create_app() (e.g. a
        mobile view) can call it directly -- that's the whole point of factoring
        it out instead of inlining the check.

        A session is re-validated against config.json's AUTH_USERS on every call
        (not just trusted because `session.get("user")` is set): the plain Flask
        session is a stateless, client-side signed cookie with nothing server-side
        to revoke, so without this re-check a cookie captured off plain-HTTP LAN
        traffic would keep working forever -- surviving both the real user
        signing out (/logout bumps their sess_epoch) and the account being removed
        (get_web_user_session_epoch returns None once it's gone). See that
        function's docstring for the fuller writeup."""
        user = session.get("user")
        if user is None:
            return False
        import moonglade_backup as core
        current_epoch = core.get_web_user_session_epoch(user)
        if current_epoch is None or current_epoch != session.get("sess_epoch"):
            session.clear()   # stale/revoked -- drop it so later requests short-circuit above
            return False
        return True

    # ---- Login rate limiting: in-memory per-IP failed-attempt counter ----------
    # Lives in this closure (one dict per running server PROCESS), not config.json
    # or a database -- it exists to blunt casual brute force, not to be a durable
    # security ledger. Known, deliberate limitations (spelled out rather than
    # silently assumed away): (1) resets to empty on every server restart; (2) if
    # this app is ever run under a multi-worker server (gunicorn/uwsgi with >1
    # worker process), each worker process keeps its OWN counter, so the effective
    # lockout threshold becomes (workers x _LOGIN_MAX_FAILS) instead of the real
    # one -- a genuine multi-worker deployment would need a shared store (Redis, a
    # DB table) instead. Fine as-is for this app's normal deployment: one process,
    # `python moonglade_gallery.py`.
    _login_lock = threading.Lock()
    _login_attempts = {}   # ip -> {"fails": int, "first_fail": epoch, "locked_until": epoch|None}
    _LOGIN_MAX_FAILS = 5
    _LOGIN_WINDOW_S = 5 * 60     # failed attempts must land within this window to count together
    _LOGIN_LOCKOUT_S = 15 * 60   # lockout duration once max fails is hit within the window

    def _client_ip():
        return (request.remote_addr or "").strip() or "unknown"

    def _login_seconds_locked(ip):
        """None if `ip` may attempt a login right now; otherwise seconds remaining
        on its current lockout."""
        import time as _time
        with _login_lock:
            rec = _login_attempts.get(ip)
            if not rec or not rec.get("locked_until"):
                return None
            remaining = rec["locked_until"] - _time.time()
            if remaining <= 0:
                _login_attempts.pop(ip, None)   # lockout expired -- clean slate
                return None
            return int(remaining)

    def _login_try_acquire(ip):
        """Atomically re-check `ip`'s lockout status AND reserve/record this
        attempt as a (provisional) failure, in the SAME critical section --
        closes a TOCTOU race in the old check-then-act pattern (a fast, lock-
        protected `locked_for` read, then verify_web_user()'s slow -- and
        UNLOCKED -- scrypt comparison, then a separate fast, lock-protected write
        after). Under that old pattern, many concurrent requests from one IP each
        pass the early read before any of them reaches the write, so a burst of
        arbitrarily many guesses lands "free" before the counter reflects more
        than zero fails -- only the NEXT burst gets locked out, buying N guesses
        per 15-minute cycle instead of the intended 5. Reserving the attempt here,
        before the slow call runs, means the fail count (and therefore the lock)
        is committed atomically at admission time, not completion time. A
        genuinely correct login calls _login_clear() right after, which erases
        this reservation along with the rest of the counter, so a real user's own
        correct password is never penalized by it.

        Also opportunistically sweeps any OTHER address's record whose failure
        window has fully expired without ever reaching a lockout -- otherwise an
        IP that fails 1-4 times and never returns sits in this dict forever (no
        other code path ever removes it), an unbounded-growth vector from many
        distinct real source addresses (no header-spoofing needed: IPv6 privacy
        rotation or any real botnet/proxy pool). Low severity for a genuinely
        LAN-only deployment, real the moment --host 0.0.0.0 sits behind a
        port-forward or other routable path.

        Returns None if the attempt may proceed, else seconds remaining on the
        lockout that was already in effect (or was just now triggered)."""
        import time as _time
        now = _time.time()
        with _login_lock:
            stale = [k for k, r in _login_attempts.items()
                     if k != ip and not r.get("locked_until")
                     and now - r["first_fail"] > _LOGIN_WINDOW_S]
            for k in stale:
                _login_attempts.pop(k, None)

            rec = _login_attempts.get(ip)
            if rec and rec.get("locked_until"):
                remaining = rec["locked_until"] - now
                if remaining > 0:
                    return int(remaining)
                _login_attempts.pop(ip, None)   # lockout expired -- clean slate

            rec = _login_attempts.setdefault(
                ip, {"fails": 0, "first_fail": now, "locked_until": None})
            if now - rec["first_fail"] > _LOGIN_WINDOW_S:   # window expired -- start fresh
                rec["fails"] = 0
                rec["first_fail"] = now
            rec["fails"] += 1
            if rec["fails"] >= _LOGIN_MAX_FAILS:
                rec["locked_until"] = now + _LOGIN_LOCKOUT_S
            return None

    def _login_clear(ip):
        """Called on a successful login -- a real owner/user typing their own
        password correctly should never stay throttled by earlier typos."""
        with _login_lock:
            _login_attempts.pop(ip, None)

    def _gen_session():
        import moonglade_backup as core
        return core, core._make_session(None)

    # Membership is not stored anywhere -- it is a live GraphQL read per call -- and
    # /api/price fires on every keystroke in the drawer, so an uncached check would tax the
    # cost badge with a round trip per character. Five minutes is long enough to cost
    # nothing and short enough that a membership bought (or lapsed) mid-session is picked up
    # without a restart. An UNKNOWN result is deliberately not cached: it means the read
    # failed, and a transient failure must not pin a paying member to non-member behaviour.
    _entitle_cache = {"value": None, "at": 0.0}
    _ENTITLE_TTL = 300.0

    def _entitlements(core, session):
        """{"is_member": True/False/None, "lora_cap": int|None} -- what PixAI says this
        account may ask for. None anywhere means UNKNOWN and every caller fails open."""
        import time as _t
        now = _t.time()
        cached = _entitle_cache["value"]
        if cached is not None and (now - _entitle_cache["at"]) < _ENTITLE_TTL:
            return cached
        try:
            me = core.account_info(session)
            val = {"is_member": core.account_is_member(me),
                   "lora_cap": core.account_lora_cap(me)}
        except Exception:                                    # noqa: BLE001
            return {"is_member": None, "lora_cap": None}
        if val["is_member"] is not None:
            _entitle_cache["value"] = val
            _entitle_cache["at"] = now
        return val

    def _account_is_member(core, session):
        """True / False / None(unknown) -- entitlement for PixAI's members-only options."""
        return _entitlements(core, session)["is_member"]

    def _input_media_id(core, session, val):
        """Turn whatever the client sent into a media_id PixAI will accept as an INPUT.

        A media_id in our catalog identifies a generation OUTPUT. On 2026-07-20 PixAI
        refused one as an input (invalid_media_id / invalid_reference_image_media_id) and
        this helper was built to upload instead. PROBED since: i2vPro (2026-07-26) and
        referenceVideo (2026-08-22, 10 completed tasks) both accept catalog ids, so
        /api/loom/generate passes ids through and calls this only as the retry FALLBACK
        after a real invalid_*_media_id rejection. /api/edit and /api/fix still resolve
        through it on the main path.

        We hold the file on disk (that is what the backup IS), so upload it and hand
        PixAI an upload-kind id. Same free S3 handshake as --upload and /api/upload;
        spends nothing. Cached per media_id for the process lifetime.

        This lives at create_app scope, called by EVERY path that feeds a user-chosen
        image to PixAI -- /api/loom/generate, /api/edit, /api/fix. The first fix for this
        bug only patched the video route, which left the other input routes silently broken
        in exactly the same way; a shared helper is what stops the next input path from
        reintroducing it.

        Falls back to the value unchanged on ANY failure (no local copy, upload error)
        so PixAI's own error surfaces rather than a mystery 'no reference'.
        """
        s = str(val or "").strip()
        if not s or not s.isdigit():
            return s                       # data: URLs and blanks are handled by callers
        if s in _ref_upload_cache:
            return _ref_upload_cache[s]
        try:
            row = get_row(db_path, s)
            fp = find_image_file(out_dir, s, (row or {}).get("filename") or "")
            if not fp or not fp.exists():
                return s
            mid = core.upload_media(session, str(fp))
        except Exception:                  # noqa: BLE001 -- never 500 a generation over this
            return s
        if mid:
            _ref_upload_cache[s] = str(mid)
            return str(mid)
        return s

    @app.route("/api/model-search")
    def api_model_search():
        """Search PixAI models/LoRAs for the picker grid. Read-only, owner's key. Login required
        (any session, local or LAN).
        ?q=&kind=base|lora&size=N&cursor=&category=&sort=popular|newest&base_type=.

        Three data sources by design: REST /search (base models' default) has RICH rows
        (description / refCount / official badge) but silently ignores market filters AND
        has no per-row architecture field; the GraphQL `generationModels` connection honors
        category + a Newest sort AND (picker-parity-round2, 2026-07-24) carries
        modelType/loraBaseModelType per row too. LoRA search (kind=lora) ALWAYS uses GraphQL
        now, regardless of category/sort -- architecture-aware compat sort/badging
        (base_type=) needs that per-row data on every LoRA search, not just the
        category/Newest subset, and REST's oRPC endpoint has no equivalent field to request
        it from (confirmed by inspecting its full response shape -- see
        the 2026-07-21 audit). Base-model search is UNCHANGED (REST by default, GraphQL
        only for category/Newest) -- architecture filtering is a LoRA-picker concept only,
        base models don't get compat-sorted against anything.

        cursor= (owner report 2026-07-24: the picker "scrolls a few rows and stops -- no
        continuous scroll"): an OPAQUE token from a previous response's `next_cursor` --
        the client just echoes it back with no idea which search path is serving it; THIS
        route decides what it means for the CURRENT request. On the GraphQL path it's the
        real Relay endCursor, passed straight through as `after=`. On the REST path (which
        has no cursor concept, only a raw int offset) it's a base-10 offset string, parsed
        here and passed as `offset=`; the response's own `next_cursor` is then computed as
        offset+size so the next request stays a plain opaque round-trip either way. Always
        '' when the underlying `has_more` is false, regardless of what math would otherwise
        produce -- a client must never be handed a cursor that pages past a real end.
        Absent/malformed cursor == first page, same as no cursor was ever sent.

        base_type=<model_type>: the CALLER's already-resolved selected base model's own
        model_type (the Gallery/Loom already resolve this today for the post-selection
        is_lora_compatible() gate -- this just reuses it). ONE caller-supplied value, three
        layers, coarsest first:
          1. SERVER-SIDE FILTER (added 2026-07-24, the real fix): threaded into
             model_search_market_gql as lora_base_type, which asks PixAI for LoRAs whose
             base family matches -- generationModels(loraBaseModelTypes:[<enum>]). This is
             what stops a DiT.2 user's LoRA browse from being 24-of-24 SD 1.5 rows, which
             was the actual complaint (the standing workaround was keyword-searching "sdxl"
             on PixAI's own site). Approximate, not strict, and only applied for architecture
             values on core's whitelist -- anything else falls through unfiltered.
          2. per-page soft SORT (compatible-or-unknown first, confirmed-mismatch last).
          3. per-row `compat` tag -- the PRECISE layer, see annotate_lora_compat(). Kept
             deliberately: layer 1 is a coarse browse hint, so only this one can be trusted
             to badge an individual row.
        Absent/kind=base -> results pass through unmodified, exactly as before."""
        q = (request.args.get("q") or "").strip()
        usage = "LORA" if (request.args.get("kind") or "base").lower() == "lora" else "MODEL"
        category = (request.args.get("category") or "").strip().lower()
        sort = (request.args.get("sort") or "").strip().lower()
        base_type = (request.args.get("base_type") or "").strip()
        cursor = (request.args.get("cursor") or "").strip()
        # --- picker parity round 3 (2026-07-26).
        # `src` is WHICH LIST to browse (market / bookmark / mine) -- the thing PixAI renders as
        # tabs. `source` is a market FILTER (all / pixai / external), which they express through
        # the connection's `types` argument. Two different concepts with confusingly similar
        # names in their own UI; keeping our query keys distinct so a caller cannot mix them up.
        src = (request.args.get("src") or "market").strip().lower()
        source = (request.args.get("source") or "").strip().lower()
        license_ = (request.args.get("license") or "").strip().upper()
        # Posted-at. The DateRange shape was CAPTURED from the live site 2026-07-26 --
        # {"gt": "<ISO instant>"}, start of day N days back in local time -- so core
        # builds it from a whitelisted token and an unknown token yields None (no filter).
        posted = (request.args.get("posted") or "").strip().lower()
        # Their Model Type filter is multi-select, so this is a repeated param rather
        # than one value. Base-model searches only; a LoRA search narrows by
        # architecture through base_type instead.
        model_types = [t for t in request.args.getlist("model_type") if t.strip()]
        try:
            size = max(1, min(int(request.args.get("size") or 24), 50))
        except ValueError:
            size = 24
        try:
            core, session = _gen_session()
            if src == "bookmark":
                # Its own operation -- the market connection has no bookmark argument, so this
                # cannot be folded into the call below. Same row shape, so the grid does not care.
                payload = core.model_bookmarks_gql(
                    session, keyword=q, usage=usage, limit=size, after=(cursor or None),
                    lora_base_type=(base_type if usage == "LORA" else ""))
            elif src == "mine":
                # "My LoRAs" is NOT a separate operation: it is the ordinary market connection
                # filtered by the signed-in user's own id, exactly as their MY LORA tab does it.
                payload = core.model_search_market_gql(
                    session, keyword=q, category=category, sort=sort, usage=usage,
                    limit=size, after=(cursor or None),
                    lora_base_type=(base_type if usage == "LORA" else ""),
                    author_id=core.USER_ID or "")
            # GraphQL whenever ANY market filter or sort is in play. The owner reported that
            # under Popular the Model Type and Posted-at filters did nothing: base+Popular used
            # to fall through to REST, whose own docstring says it "silently ignores market
            # filters". REST survives only for a bare, unfiltered base browse, where its richer
            # rows (description / refCount / official badge) are worth having.
            elif (usage == "LORA" or category in core.MARKET_CATEGORIES
                  or posted or license_ or model_types
                  or (sort and sort not in ("trending", "popular"))):
                payload = core.model_search_market_gql(
                    session, keyword=q, category=category, sort=sort, usage=usage,
                    limit=size, after=(cursor or None),
                    # Same caller-supplied value that feeds the compat sort/badge below --
                    # resolved once by the client, used at every layer. core ignores it for
                    # a base-model search and for any architecture off its whitelist.
                    lora_base_type=(base_type if usage == "LORA" else ""),
                    source=source, permitted_use=license_,
                    time_range=core.posted_at_range(posted),
                    model_types=model_types)
            else:
                offset = int(cursor) if cursor.isdigit() else 0
                payload = core.model_search_rest(session, keyword=q, usage=usage,
                                                  size=size, offset=offset)
                payload["next_cursor"] = str(offset + size) if payload.get("has_more") else ""
            if usage == "LORA" and base_type:
                payload["results"] = core.annotate_lora_compat(payload["results"], base_type)
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "results": []}), 200

    @app.route("/api/model-version")
    def api_model_version():
        """Resolve a model_id (from the grid) to its generatable version id + the version
        metadata the picker needs: model_type (for LoRA↔base compat), lora_base_model_type,
        trigger_words (to offer inserting into the prompt), and the author's tuned preset.
        Login required; read-only, one API call.

        ?all=1 (picker-parity-round2, 2026-07-24): return EVERY published version instead of
        just the resolved latest -- {versions:[...]}, same per-row shape plus `label`/
        `is_latest` -- so the picker can offer a real choice (see
        core.list_model_versions). Default (no ?all) is UNCHANGED: the single resolved-latest
        shape every existing caller already expects.

        ?version_id=X (2026-08-02, the Runs reel's reuse-prefill): the REVERSE lookup --
        {"model_id": "..."} , "" if unresolvable. The catalog stores a run's model_id as the
        VERSION PixAI actually rendered with, not the base model id this route's other two
        modes take -- reuse-prefill needs this to feed applyModelRow the same real, current
        base id a fresh market pick would use, never the version id verbatim (see
        core.resolve_model_base_id)."""
        version_id = (request.args.get("version_id") or "").strip()
        if version_id:
            try:
                core, session = _gen_session()
                return jsonify({"model_id": core.resolve_model_base_id(session, version_id)})
            except Exception as e:
                return jsonify({"error": _redact_host_paths(str(e))[:200], "model_id": ""}), 200
        mid = (request.args.get("model_id") or "").strip()
        if not mid:
            return jsonify({"error": "model_id required", "version_id": ""}), 400
        try:
            core, session = _gen_session()
            if (request.args.get("all") or "").strip() in ("1", "true"):
                return jsonify({"versions": core.list_model_versions(session, mid)})
            return jsonify(core.resolve_version_meta(session, mid))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "version_id": ""}), 200

    @app.route("/api/task-params/<task_id>")
    def api_task_params(task_id):
        """A task's submit parameters, reduced to what Remix (issue #4) needs:
        the task's LoRAs -- exact {version_id, weight} pairs straight off
        parameters.lora, each resolved to its base model id for the composer,
        NEVER matched by name -- plus the exact model version id the task
        rendered with. Read-only; nothing here submits or spends, and the
        composer's own gates still stand between a prefill and a paid generate.

        Contract hardened by the 2026-08-13 adversarial review:
        - A task this library has no row for is refused (404) -- the route runs
          under the owner's credentials and must not be a free probe of
          arbitrary task ids for any signed-in LAN session (finding 4.3).
        - Video and chat tasks are refused (400) -- their recipes belong to
          their own pipelines (finding 4.2).
        - task_detail_gql returning None (its NETWORK-failure value -- it does
          not raise) answers {"error": ...}, never a success-shaped empty LoRA
          list: the client's disclosure branch keys on `error`, and without
          this the likeliest failure could structurally never be disclosed
          (finding 2.1).
        - retries=1: this is a prefill, not a lost generation -- the default
          retry ladder would hold the composer's 'restoring' state for minutes
          on a PixAI outage (finding 4.1).
        - An unparseable stored weight SKIPS the LoRA and counts it in
          `unresolved` -- never a silent plausible default (finding 1.5); a
          failed compatibility-meta lookup ships the row flagged `degraded`
          so the client can disclose it (finding 1.4)."""
        tid = (task_id or "").strip()
        if not tid:
            return jsonify({"error": "task id required"}), 400
        crow = get_row_by_task(db_path, tid)
        if not crow:
            return jsonify({"error": "no such task in this library"}), 404
        if str(crow.get("is_video") or "") == "1":
            return jsonify({"error": "not an image-generation task"}), 400
        try:
            core, session = _gen_session()
            task = core.task_detail_gql(session, tid, retries=1)
            if not task:
                return jsonify({"error": "couldn't read the task from PixAI"}), 200
            params = task.get("parameters") or {}
            if isinstance(params.get("chat"), dict):
                return jsonify({"error": "not an image-generation task"}), 400
            lora_map = params.get("lora") or {}
            rows, unresolved = [], 0
            meta_cache = {}
            if isinstance(lora_map, dict):
                for vid, weight in lora_map.items():
                    try:
                        w = float(weight)
                    except (TypeError, ValueError):
                        unresolved += 1
                        continue
                    base = core.resolve_model_base_id(session, str(vid))
                    if not base:
                        unresolved += 1
                        continue
                    if base not in meta_cache:
                        meta_cache[base] = core.resolve_version_meta(session, base) or {}
                    meta = meta_cache[base]
                    lbt = str(meta.get("lora_base_model_type") or "")
                    rows.append({
                        "model_id": base, "version_id": str(vid), "weight": w,
                        "title": str(core.model_name_gql(session, str(vid)) or "") or base,
                        "preview_url": "",
                        "lora_base_model_type": lbt,
                        "model_type": str(meta.get("model_type") or ""),
                        "degraded": not lbt,
                    })
            return jsonify({"task_id": tid, "loras": rows, "unresolved": unresolved,
                            "model_version_id": str(params.get("modelId") or "")})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/video-task-params/<task_id>")
    def api_video_task_params(task_id):
        """A VIDEO task's submit parameters, reduced to what "↺ Remix for videos"
        (SCOPE_2026-08-17 §2) needs: the shot kind (i2v / flf / r2v) and every
        recipe field the Video composer can set -- engine, duration, quality,
        camera, audio(+language), prompt-helper, negative, prompt, channel -- plus
        the source/reference media ids, each flagged in_lib against the local
        catalog so the client restores only what it actually holds.

        A deliberate SIBLING of /api/task-params rather than a widening of it: that
        route refuses videos (`not an image-generation task`) and its refusal test
        pins exactly that (tests/test_task_params.py). Widening it would blur the
        two recipes' shapes; a sibling keeps each honest. Same contract otherwise:
        read-only (nothing here submits or spends; the composer's own price-identity
        gate still stands between a prefill and a paid generate), membership-checked
        against the catalog (finding 4.3 -- no free probing of arbitrary task ids),
        retries=1 (a prefill, not a lost generation -- finding 4.1), and
        host-path-redacted errors.

        Refuses (mirroring the image sibling, inverted): an IMAGE row (its recipe
        belongs to /api/task-params) and a CHAT task -- both `not a video task`,
        400. task_detail_gql returning None (its NETWORK-failure value, not a raise)
        answers {"error": ...}, never a success-shaped empty recipe."""
        tid = (task_id or "").strip()
        if not tid:
            return jsonify({"error": "task id required"}), 400
        crow = get_row_by_task(db_path, tid)
        if not crow:
            return jsonify({"error": "no such task in this library"}), 404
        if str(crow.get("is_video") or "") != "1":
            return jsonify({"error": "not a video task"}), 400
        try:
            core, session = _gen_session()
            task = core.task_detail_gql(session, tid, retries=1)
            if not task:
                return jsonify({"error": "couldn't read the task from PixAI"}), 200
            params = task.get("parameters") or {}
            if not isinstance(params, dict):
                params = {}
            if isinstance(params.get("chat"), dict):
                return jsonify({"error": "not a video task"}), 400

            def _mref(mid):
                mid = str(mid or "")
                if not mid:
                    return None
                return {"media_id": mid, "in_lib": bool(get_row(db_path, mid))}

            def _mrefs(ids):
                out = []
                for mid in (ids or []):
                    r = _mref(mid)
                    if r:
                        out.append(r)
                return out

            def _dur(v):
                # i2vPro.duration is a string ("5"), referenceVideo.duration an int -- normalize
                # to a clean int (or None) so the client never has to guess the type.
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

            out = {
                "task_id": tid,
                "model_id": str(params.get("modelId") or ""),
                "is_private": bool(params.get("isPrivate")),
            }
            rv = params.get("referenceVideo")
            i2v = params.get("i2vPro") or params.get("i2v")
            if isinstance(rv, dict):
                out.update({
                    "kind": "r2v",
                    "video_model": str(rv.get("model") or ""),
                    "duration": _dur(rv.get("duration")),
                    "quality": str(rv.get("mode") or ""),
                    "camera": "",
                    "audio": bool(rv.get("generateAudio")),
                    "audio_language": str(rv.get("audioLanguage") or ""),
                    "prompt_helper": False,
                    "negative": "",                      # r2v carries no negative (builder omits it)
                    "prompt": str(rv.get("prompt") or ""),
                    "start": None, "end": None,
                    "image_refs": _mrefs(rv.get("referenceImageMediaIds")),
                    "video_refs": _mrefs(rv.get("referenceVideoMediaIds")),
                    "audio_refs": _mrefs(rv.get("referenceAudioMediaIds")),
                })
            elif isinstance(i2v, dict):
                tail = str(i2v.get("tailMediaId") or "")
                out.update({
                    "kind": "flf" if tail else "i2v",
                    "video_model": str(i2v.get("model") or ""),
                    "duration": _dur(i2v.get("duration")),
                    "quality": str(i2v.get("mode") or ""),
                    "camera": str(i2v.get("cameraMovement") or ""),
                    "audio": bool(i2v.get("generateAudio")),
                    "audio_language": str(i2v.get("audioLanguage") or ""),
                    "prompt_helper": bool(i2v.get("usePromptsHelper")),
                    "negative": str(i2v.get("negativePrompts") or ""),
                    "prompt": str(i2v.get("prompts") or ""),
                    "start": _mref(i2v.get("mediaId")),
                    "end": _mref(tail),
                    "image_refs": [], "video_refs": [], "audio_refs": [],
                })
            else:
                # A video ROW whose task has neither block: nothing safe to prefill from.
                return jsonify({"error": "not a video task"}), 400
            return jsonify(out)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/image-meta/<media_id>")
    def api_image_meta(media_id):
        """The one catalog row the Upscale panel needs, by media_id. Read-only, no network.

        Scoped deliberately narrow: the fields an i2i upscale submits (real pixel size, the
        model that made it, and the prompt it is re-rendered under) plus what the panel shows
        about them. NOT a general row dump -- `filename` in particular is a HOST PATH
        fragment and stays out, matching the same withholding /panel does for non-local
        callers.

        Not localhost-gated, for the reason /api/gallery-images spells out: it reads only the
        local catalog and returns what the gallery already serves openly, so a gate would add
        no protection while breaking the panel for the owner browsing over his own LAN.
        Spending stays gated on /api/generate, which is where the upscale is actually
        submitted.
        """
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"error": "no such image"}), 404
        # A model id is what makes an upscale submittable without asking. Locally imported
        # files have no PixAI task behind them and so can never carry one -- the panel says
        # so and offers its picker, rather than presenting a blank as though it were a
        # catalog gap the owner could go and fill.
        source = str(row.get("source") or "")
        return jsonify({
            "media_id": str(row.get("media_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "width": str(row.get("width") or ""),
            "height": str(row.get("height") or ""),
            "model_id": str(row.get("model_id") or ""),
            "model_name": str(row.get("model_name") or ""),
            "prompt": str(row.get("prompt_full") or row.get("prompt_preview") or ""),
            "negative": str(row.get("negative_prompt") or ""),
            "steps": str(row.get("steps") or ""),
            "cfg": str(row.get("cfg_scale") or ""),
            "is_video": str(row.get("is_video") or "") == "1",
            "source": source,
            "local_import": source == "local",
        })

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
            # is_nsfw rides along so every consumer of this route (the gallery Picker,
            # <mg-gallery-picker>, and the Generate drawer's reference slots) can set
            # data-nsfw the same way the Jinja template and /api/similar already do.
            # Audit 2026-07-21 S5: this was the one remaining projection gap -- without
            # it, Privacy Blur (body.privacy-blur .card[data-nsfw="1"] img) never saw an
            # NSFW thumbnail on any of these three surfaces.
            isnsfw = str(r.get("is_nsfw") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "is_nsfw": "1" if isnsfw else "",
                        "thumb": "/thumbs/{}.jpg".format(mid),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000],
                        "duration": (r.get("video_duration") or "") if isv else ""})
        return jsonify({"images": out, "total": total, "page": page, "limit": limit})

    @app.route("/api/similar/<media_id>")
    def api_similar(media_id):
        """'More like this': the k catalog images most visually similar to media_id, via the
        moonglade_similar CLIP sidecar index. Mirrors /api/gallery-images's shape so the client
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
            import moonglade_similar
            hits = moonglade_similar.similar(str(img_path), k=k, exclude_media_id=media_id)
        except Exception as e:
            return jsonify({"images": [], "total": 0,
                            "error": "similarity index unavailable: " + _redact_host_paths(str(e))[:180]}), 200
        # An EMPTY index is not the same as "no matches", and conflating the two hid a real
        # regression for three days. The 2026-07-25 module rename orphaned the stored index;
        # moonglade_similar._get_table() then CREATED a fresh empty one instead of raising, so this
        # route returned zero hits with no error at all and the client fell back to "the index may
        # still be building" -- a benign transient message covering a permanent broken state.
        # Reporting the size lets the client tell the truth and say what to do about it.
        if not hits:
            try:
                indexed = int(moonglade_similar.count())
            except Exception:
                indexed = None
            if indexed == 0:
                return jsonify({"images": [], "total": 0, "indexed": 0,
                                "error": "The similarity index is empty, so there is nothing to "
                                         "compare against. Rebuild it from the Control Panel "
                                         "(Rebuild similar index)."}), 200
        telem_bump("similar_uses", out_dir=out_dir)       # Kindred Spirits
        out = []
        for mid, score in hits:
            r = get_row(db_path, mid)
            if not r:
                continue        # the sidecar index can drift from later catalog deletes
            isv = str(r.get("is_video") or "") == "1"
            # is_nsfw rides along so the client's hand-cloned .card (Similar.open() below --
            # this modal builds its own DOM instead of reusing the server-rendered template at
            # the top of the page, unlike every other card-producing surface) can set
            # data-nsfw the same way the Jinja template does. Without it, Privacy Blur
            # (body.privacy-blur .card[data-nsfw="1"] img) never sees an NSFW lookalike here
            # at all, and it never gets blurred -- fixed alongside the client half below.
            isnsfw = str(r.get("is_nsfw") or "") == "1"
            out.append({"media_id": str(mid), "is_video": "1" if isv else "",
                        "is_nsfw": "1" if isnsfw else "",
                        "thumb": "/thumbs/{}.jpg".format(mid), "score": round(float(score), 3),
                        "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:2000]})
        return jsonify({"images": out, "total": len(out), "query": str(media_id)})

    @app.route("/api/collections")
    def api_collections():
        """Collection names for the picker/filter dropdowns. Read-only, local catalog."""
        return jsonify({"collections": unique_collections(db_path)})

    @app.route("/branding/<path:fname>")
    def branding(fname):
        """Serve branding art. The URL vocabulary is PUBLIC role names
        (/branding/marks/..., /branding/bridge/emotion/...); the on-disk tree
        and the container keys are CODED -- this route is the ONE place the
        two meet (_public_rel_to_coded, applied exactly once to the incoming
        rel). After translation: seal check, then a loose file under
        branding_root() first, the shipped container second (the loose-then-
        container contract every read path holds), and for the three banner
        flats a last fallback onto the slot's SHIPPED sealed default so a
        fresh install is dressed before its first crop. Absent everywhere ->
        404 so the header's onerror simply removes the <img>. Path-safe."""
        from flask import send_from_directory, abort
        import mimetypes
        bdir = branding_root().resolve()
        try:
            target = (bdir / fname).resolve()
            target.relative_to(bdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        coded = _public_rel_to_coded(target.relative_to(bdir).as_posix())
        # The unlock split, enforced (see _seal_rule, which judges the CODED
        # rel -- a probe that guesses a coded path passes through translation
        # unchanged, so it faces the same verdict): achievement-bound art only
        # serves once its achievement is earned, whether the bytes would come
        # from a loose file or the container.
        mode, seal_aid = _seal_rule(coded)
        if mode == "deny":
            abort(404)
        if mode == "earned" and seal_aid not in _earned_achievement_ids(
                out_dir, db_path, need=seal_aid):
            abort(404)
        if (bdir / coded).is_file():
            resp = send_from_directory(str(bdir), coded)
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"   # branding art gets re-cut; never serve a stale copy
            return resp
        # Container fallback keys on the CODED rel (posix separators -- the
        # container's native addressing; loose path == container key, always).
        raw = _branding_bytes(coded)
        if raw is None and coded in _BANNER_FLAT.values():
            # Rule-8 flat fallback: no per-install loose flat rendered yet ->
            # the slot's shipped sealed default (loose flat wins when present;
            # translation itself never rewrites the flat names).
            slot = next(s for s, n in _BANNER_FLAT.items() if n == coded)
            raw = _branding_bytes(_flat_default_rel(slot))
        if raw is None:
            abort(404)
        mime = mimetypes.guess_type(coded)[0] or "application/octet-stream"
        resp = app.response_class(raw, mimetype=mime)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    @app.route("/badge-thumb/<aid>.png")
    def badge_thumb(aid):
        """Cached ~256px badge for the Folio of Honors tiles (masters stay the source of
        truth). Lazily generated on first hit; path-safe (no slashes via <aid>)."""
        from flask import send_from_directory, abort
        if not aid or "/" in aid or "\\" in aid or ".." in aid:
            abort(404)
        # Achievement ids are canonically lowercase-kebab; the underlying resolve
        # is on a case-insensitive FS, so a case-variant (UNDER-THE-HOOD.png)
        # would otherwise skip the hidden-feat gate below (a frozenset of
        # lowercase ids) yet still read the real sealed master -- the same
        # fail-open leak _seal_rule casefolds against. Normalise once here so the
        # gate, _earned_achievement_ids, and the cache key all agree.
        aid = aid.lower()
        # Fail CLOSED, matching _seal_rule's badge branch. Only serve a thumb for
        # an id that IS in the roster; an unknown id -- OR ANY id when the roster
        # is unavailable (no/invalid container -> _ach_ids() empty) -- is denied.
        # Without this, _ach_hidden() also goes empty in that state, the hidden
        # gate below silently passes, and an unearned hidden feat's master serves
        # by id (the fail-open _seal_rule was written to avoid; the parallel gate
        # here missed it -- adversarial, 2026-08-22). Visible feats' thumbs still
        # serve unearned (the Folio's locked tiles show art by design).
        if aid not in _ach_ids():
            abort(404)
        # Hidden feats are masked in /api/achievements, but their ids sit in
        # this public source -- so an unearned hidden feat's badge must not be
        # fishable by id here either.
        if aid in _ach_hidden() and aid not in _earned_achievement_ids(
                out_dir, db_path, need=aid):
            abort(404)
        # The celebration toast asks for 384px so the enlarged medallion stays crisp
        # on HiDPI; the Folio grid keeps the 256 default. Allowlisted to those two so
        # the cache can't be spammed into unbounded sizes.
        size = 384 if request.args.get("size") == "384" else 256
        p = _badge_thumb(out_dir, aid, size)
        if isinstance(p, (bytes, bytearray)):
            # cache unwritable -> _badge_thumb handed us the image in memory
            resp = app.response_class(bytes(p), mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
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
        # This page is assembled with str.format(), NOT render_template_string, so it
        # gets NONE of Jinja's autoescaping -- every catalog/query value interpolated
        # below has to be escaped by hand or ?collection=<script>... is reflected XSS
        # straight into the logged-in session (markupsafe escapes ' and " too, which
        # the single-quoted src=' ' attributes here depend on).
        from markupsafe import escape
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
            title = "Collection: {}".format(escape(collection))
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
                    + "<div class='photo'><img src='/full/{}'></div>".format(escape(mids[0]))
                    + _autoprint + "</body></html>")

        if fmt == "strip" and mids:
            frames = [mids[i % len(mids)] for i in range(4)]
            frame_html = "".join(
                "<div class='frame'><img src='/full/{}'></div>".format(escape(m)) for m in frames)
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
                    escape(date), (" " + stars) if stars else "")
            cells.append(
                "<figure><img src='/thumbs/{}.jpg' alt=''>{}</figure>".format(
                    escape(mid), cap))
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

    @app.route("/api/contact-sheet")
    def api_contact_sheet():
        """JSON twin of /contact-sheet -- feeds the React ContactSheetOverlay's on-screen
        preview and its own native (window.print()) output. Same source selection as the
        page route (rows_for_media_ids / query_catalog); the page route stays untouched
        for classic's own use until demolition -- the new front door never calls it."""
        import datetime as _dt
        ids_arg = (request.args.get("ids") or "").strip()
        collection = (request.args.get("collection") or "").strip()
        if ids_arg:
            ids = [x for x in ids_arg.split(",") if x.strip()]
            rows = rows_for_media_ids(db_path, ids)
            collection_name = "{} selected".format(len(rows))
        elif collection:
            rows, _ = query_catalog(db_path, collection=collection, sort="newest",
                                    page=1, page_size=400)
            collection_name = collection
        else:
            rows, _ = query_catalog(db_path, sort="newest", page=1, page_size=60)
            collection_name = "Recent"

        frames = []
        for r in rows:
            mid = str(r.get("media_id") or "")
            if not mid:
                continue
            try:
                stars = "★" * int(r.get("rating") or 0)
            except (TypeError, ValueError):
                stars = ""
            title = ((r.get("title") or "").strip()
                     or (r.get("prompt_preview") or "").strip()[:60]
                     or "Untitled")
            frames.append({
                "media_id": mid,
                "title": title,
                "model": r.get("model_name") or "",
                "stars": stars,
                "thumb_url": "/thumbs/{}.jpg".format(mid),
            })

        d = _dt.datetime.now()
        printed_date = "{} {}, {}".format(d.strftime("%B"), d.day, d.year)
        return jsonify({
            "collectionName": collection_name,
            "frameCount": len(frames),
            "printedDate": printed_date,
            "frames": frames,
        })

    @app.route("/api/duplicates")
    def api_duplicates():
        """Real, working duplicate-groups listing for the React Duplicate Review overlay
        (the parked affordance in HealthOverlay.jsx's Duplicates/Reclaimable stat tiles).
        Owner-scoped "happy medium" (2026-08-02, docs/DECISIONS.md), FOUR tiers --
        3 EXACT-match with no invented data/percentage, plus one perceptual-similarity
        tier that carries a real, derived closeness score (see near_duplicate below) --

          same_media     Class A: the same PixAI media_id reused across >1 folder bucket.
                          duplicate_groups() (this module) -- the classic /duplicates
                          page's own engine, reused as-is (its 300-row cap is lifted here;
                          see the call below).
          identical_file Class B: byte-identical files under DIFFERENT media_ids.
                          moonglade_backup.audit_collection(content=True)'s size-bucketed
                          SHA pass -- reused as-is; not naive O(n^2).
          same_seed       Class C: catalog rows sharing (seed, prompt_full) -- a cheap
                          SQL GROUP BY (same_seed_groups(), this module), not a new
                          detection algorithm.
          near_duplicate  Class D (new): images whose dHash `phash` column (populated by
                          `--backfill-phash`, compute_dhash()) is within a Hamming-
                          distance threshold of another's -- catches an upscaled or
                          recompressed copy of the same image, which byte-hashing (Class
                          B) cannot, because the bytes genuinely differ. The ONE tier
                          that carries a `closeness_pct` per group (near_duplicate_groups(),
                          this module) -- real, Hamming-distance-derived, never invented;
                          the other three tiers stay percentage-free by design. Rows with
                          no phash yet (backfill not run / not yet reached that row)
                          simply don't participate -- they are not reported as "no match",
                          they are just absent from this tier until backfilled.

        Deliberately EXCLUDES the CLIP-embedding "similar composition" tier -- real
        infrastructure exists at /api/similar, but it measures visual resemblance, not
        duplication (see DECISIONS.md).

        Read-only, no filesystem mutation -- LOGIN tier, same trust class as the classic
        /duplicates page and api_health. Members are shaped identically across all four
        tiers (media_id/thumb/dims/rating/date/path/bucket/size/is_keeper) so the client
        never has to special-case by matchType."""
        import moonglade_backup as core

        def _member(mid, row, path, bucket, size, is_keeper):
            row = row or {}
            isv = str(row.get("is_video") or "") == "1"
            return {
                "media_id": str(mid),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "width": row.get("width") or "",
                "height": row.get("height") or "",
                "rating": row.get("rating") or "",
                "created_at": row.get("created_at") or "",
                "is_video": "1" if isv else "",
                "path": str(path).replace("\\", "/"),
                "bucket": bucket,
                "size": size,
                "is_keeper": bool(is_keeper),
            }

        groups = []

        # ---- same_media (Class A) -------------------------------------------
        # No arbitrary cap here -- the classic page's limit=300 exists to keep an HTML
        # render short, not because the underlying scan is expensive (one rglob pass,
        # no hashing); this route reports the real count instead of silently truncating.
        class_a = duplicate_groups(out_dir, limit=100000)
        rows_a = {r["media_id"]: r for r in rows_for_media_ids(db_path, [g["media_id"] for g in class_a])}
        for g in class_a:
            mid = g["media_id"]
            row = rows_a.get(str(mid))
            members = [_member(mid, row, c["rel"], c["bucket"], c["size"], c["rel"] == g["keeper"])
                       for c in g["copies"]]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "same_media:{}".format(mid), "matchType": "same_media",
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- identical_file (Class B) ----------------------------------------
        audit = core.audit_collection(out_dir, content=True)
        class_b = audit["class_b"]
        mids_b = sorted({str(item[4]) for g in class_b for item in g["files"]})
        rows_b = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_b)}
        for g in class_b:
            keeper_path = g["keeper"][0]
            members = [_member(mid, rows_b.get(str(mid)), rel, bucket, size, p == keeper_path)
                       for (p, rel, bucket, size, mid) in g["files"]]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "identical_file:{}".format(g["sha"]), "matchType": "identical_file",
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- same_seed (Class C) ----------------------------------------------
        seed_groups = same_seed_groups(db_path)
        mids_c = sorted({mid for g in seed_groups for mid in g["media_ids"]})
        rows_c = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_c)}
        for g in seed_groups:
            candidates = []
            for mid in g["media_ids"]:
                row = rows_c.get(str(mid))
                if not row:
                    continue        # a stale media_id (row deleted since indexed) -- skip, don't fabricate
                fpath = find_image_file(out_dir, mid, row.get("filename"))
                try:
                    size = fpath.stat().st_size if fpath else 0
                except OSError:
                    size = 0
                # Sort key: oldest real created_at first (the original generation is the
                # keeper); a blank date sorts LAST so an unknown-date row is never
                # mistaken for the original over a row with a real timestamp.
                sort_key = row.get("created_at") or "9999-99-99"
                candidates.append((sort_key, mid, row, fpath, size))
            if len(candidates) < 2:
                continue             # every media_id in this seed group turned out stale
            candidates.sort(key=lambda c: c[0])
            keeper_mid = candidates[0][1]
            members = [_member(mid, row, (str(fpath.relative_to(out_dir)) if fpath else ""),
                               "", size, mid == keeper_mid)
                       for (_, mid, row, fpath, size) in candidates]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "same_seed:{}:{}".format(g["seed"], g["prompt_hash"]),
                           "matchType": "same_seed", "seed": g["seed"],
                           "reclaimable_bytes": reclaim, "members": members})

        # ---- near_duplicate (Class D, new) ------------------------------------
        # Same "resolve real rows/files, oldest created_at is the keeper" shape as
        # same_seed above -- the only tier-specific addition is closeness_pct, carried
        # at the group level exactly like same_seed carries `seed`.
        near_groups = near_duplicate_groups(db_path)
        mids_d = sorted({mid for g in near_groups for mid in g["media_ids"]})
        rows_d = {r["media_id"]: r for r in rows_for_media_ids(db_path, mids_d)}
        for g in near_groups:
            candidates = []
            for mid in g["media_ids"]:
                row = rows_d.get(str(mid))
                if not row:
                    continue        # stale media_id (row deleted since phash was computed)
                fpath = find_image_file(out_dir, mid, row.get("filename"))
                try:
                    size = fpath.stat().st_size if fpath else 0
                except OSError:
                    size = 0
                sort_key = row.get("created_at") or "9999-99-99"
                candidates.append((sort_key, mid, row, fpath, size))
            if len(candidates) < 2:
                continue             # every media_id in this group turned out stale
            candidates.sort(key=lambda c: c[0])
            keeper_mid = candidates[0][1]
            members = [_member(mid, row, (str(fpath.relative_to(out_dir)) if fpath else ""),
                               "", size, mid == keeper_mid)
                       for (_, mid, row, fpath, size) in candidates]
            reclaim = sum(m["size"] for m in members if not m["is_keeper"])
            groups.append({"id": "near_duplicate:{}".format("-".join(g["media_ids"])),
                           "matchType": "near_duplicate", "closeness_pct": g["closeness_pct"],
                           "reclaimable_bytes": reclaim, "members": members})

        groups.sort(key=lambda g: -g["reclaimable_bytes"])
        counts = {"same_media": len(class_a), "identical_file": len(class_b),
                 "same_seed": len(seed_groups), "near_duplicate": len(near_groups)}
        return jsonify({
            "groups": groups,
            "counts": counts,
            "total_groups": len(groups),
            "total_reclaimable_bytes": sum(g["reclaimable_bytes"] for g in groups),
        })

    @app.route("/api/duplicates/resolve", methods=["POST"])
    def api_duplicates_resolve():
        """The destructive half of Duplicate Review: quarantines the LOSING
        copies of one or more duplicate groups into out_dir/_duplicates/, via
        quarantine_duplicate_file() above -- QUARANTINE ONLY, mirroring
        cmd_dedup()'s DEFAULT (--apply without --dedup-delete) behavior.
        --dedup-delete's hard-delete path is not reachable through this route
        under any body field.

        Body: {"csrf": "...", "resolutions": [ {group_id, keep, remove}, ... ]}
        -- OR the single-resolution shortcut, the same three fields at the TOP
        level (group_id/keep/remove), for the per-group "Resolve" button; the
        frontend's "Auto-resolve all" sends the batch shape instead of one
        request per group, so a many-group resolve is one round trip, not N.

        `keep` and each entry of `remove` are {"media_id": "...", "path": "..."}
        -- the exact (media_id, path) pair GET /api/duplicates already returned
        for that member. `path`, not media_id, is what actually disambiguates a
        member: a same_media group's members all share ONE media_id (that
        tier's whole definition -- the same generation saved in more than one
        folder), so media_id alone cannot say which COPY to keep vs remove;
        path can, because GET /api/duplicates already returns a distinct path
        per member in every tier.

        SAFETY -- enforced here, not just a disabled frontend button:
          * keep-count 0 (no valid `keep`, or nothing valid in `remove`) -> that
            resolution is refused with a clear per-group error and nothing is
            touched for it; "remove everything including the keeper" is not a
            resolve.
          * every path is validated to resolve strictly inside out_dir (no ../
            escape) and its own filename's encoded media_id (media_id_of())
            must match the media_id claimed for it.
          * the keep/remove pair is re-verified as a REAL duplicate
            relationship for the group_id's own matchType, against the actual
            files/catalog rows right now -- see _validate_duplicate_pair()'s
            docstring for the exact check run per tier.

        CSRF: explicit-token class (_check_csrf(), the same helper
        /api/users/add, /api/users/remove and /api/users/password use) -- a
        real, hard-to-undo-by-accident file mutation triggered by one web
        click, not the exempt spend-path class /api/generate etc. sit in.

        READ_ONLY in config.json refuses this exactly like submit_generation/
        submit_fixer/delete_task_gql/claim_reward -- see
        quarantine_duplicate_file().

        Response: {"quarantined": [...], "errors": [...], "reclaimed_bytes": N}.
        Per-item, not all-or-nothing -- one bad group in a batch (a stale
        group_id, a file already gone) does not block the rest, same "one file
        the OS won't release must not strand the rest" shape as
        /api/delete-local."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400

        resolutions = body.get("resolutions")
        if not isinstance(resolutions, list):
            single = {k: body.get(k) for k in ("group_id", "keep", "remove")}
            resolutions = [single] if single.get("group_id") else []
        if not resolutions:
            return jsonify({"error": "no resolutions given"}), 400

        quarantined, errors = [], []
        for res in resolutions:
            res = res if isinstance(res, dict) else {}
            group_id = str(res.get("group_id") or "").strip()
            keep = res.get("keep")
            remove_raw = res.get("remove")
            if not group_id:
                errors.append({"group_id": group_id, "error": "missing group_id"})
                continue
            if (not isinstance(keep, dict) or not str(keep.get("media_id") or "").strip()
                    or not str(keep.get("path") or "").strip()):
                errors.append({"group_id": group_id,
                               "error": "no keeper specified -- refusing to resolve "
                                        "(keep-count is 0)"})
                continue

            keep_path_str = str(keep.get("path") or "")
            # The keeper guard compares RESOLVED paths, not the raw client strings --
            # 'images//a.png', 'images\\a.png' and './images/a.png' all name the same
            # file as 'images/a.png', and a raw-string compare would let an aliased
            # spelling of the keeper slip into the remove list (the validator can't
            # catch it either: the keeper is byte-identical and same-media with
            # itself by definition). Found by the 2026-08-07 branch review.
            keep_resolved = _resolve_under(out_dir, keep_path_str)
            seen, remove_items = set(), []
            for item in (remove_raw if isinstance(remove_raw, list) else []):
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("media_id") or "").strip()
                path = str(item.get("path") or "").strip()
                if not mid or not path or path in seen:
                    continue
                item_resolved = _resolve_under(out_dir, path)
                if item_resolved is not None and item_resolved == keep_resolved:
                    continue                      # the keeper itself, however spelled
                if path == keep_path_str:
                    continue                      # raw match still caught if unresolvable
                seen.add(path)
                remove_items.append({"media_id": mid, "path": path})
            if not remove_items:
                errors.append({"group_id": group_id, "error": "nothing valid to remove"})
                continue

            match_type = group_id.split(":", 1)[0]
            ok, why = _validate_duplicate_pair(out_dir, db_path, match_type, keep, remove_items)
            if not ok:
                errors.append({"group_id": group_id, "error": why})
                continue

            keep_mid = str(keep.get("media_id"))
            for item in remove_items:
                result = quarantine_duplicate_file(out_dir, thumb_dir, db_path,
                                                   item["media_id"], item["path"], group_id)
                if result.get("ok"):
                    result["group_id"] = group_id
                    result["kept_media_id"] = keep_mid
                    quarantined.append(result)
                else:
                    errors.append({"group_id": group_id, "media_id": item["media_id"],
                                  "error": result.get("error")})

        if quarantined:
            telem_bump("duplicates_resolved", len(quarantined), out_dir=out_dir)
        return jsonify({"quarantined": quarantined, "errors": errors,
                        "reclaimed_bytes": sum(q.get("size", 0) for q in quarantined)})

    @app.route("/api/duplicates/undo", methods=["POST"])
    def api_duplicates_undo():
        """Reverses ONE quarantine_duplicate_file() call (see its own docstring
        and restore_quarantined_duplicate()): moves a single quarantined
        duplicate back to its exact original recorded location and restores its
        catalog row. Singular by design -- 'Undo' on one just-resolved item, not
        a batch undo; an 'Auto-resolve all' that needs undoing calls this once
        per item, the same acceptable simplification /api/duplicates/resolve's
        own docstring notes for the read side of this feature.

        Body: {"csrf": "...", "quarantine_path": "_duplicates/images/p_t2_333.webp"}
        -- the exact `quarantine_path` /api/duplicates/resolve returned for that
        item.

        Same CSRF class, same tier, same READ_ONLY gate as resolve (see
        restore_quarantined_duplicate()). Fails with a clear error -- never a
        silent no-op or a write to some OTHER location -- when the undo record
        is missing/stale or the original location is now occupied by something
        else."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        quarantine_path = str(body.get("quarantine_path") or "").strip()
        if not quarantine_path:
            return jsonify({"error": "quarantine_path required"}), 400
        result = restore_quarantined_duplicate(out_dir, thumb_dir, db_path, quarantine_path)
        if result.get("ok"):
            telem_bump("duplicates_undone", out_dir=out_dir)
        return jsonify(result)

    @app.route("/api/account")
    def api_account():
        """Credits + free-card balance for the header chip. Read-only; login required.
        Fails soft to nulls so the header never breaks."""
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
                # category (Model Card / Video Card) was fetched by list_kaisuukens all
                # along but dropped before reaching cards_by, so the header tooltip and the
                # new Account-detail modal's Cards tab couldn't tell the types apart. Default
                # to "" (not None) so the JS `k.category ? ... : ""` check always compares a
                # string. (Carried by hand from the card-coupon-ledger branch, 2026-08-07.)
                cards_by.append({"name": k.get("name"), "count": n, "expires": exp,
                                 "category": k.get("category") or ""})
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
            # Real per-account LoRA-per-generation entitlement, straight from PixAI's own
            # membership data -- already fetched by account_info() for the CLI's --account
            # dashboard (run_account_info), never previously reached the web app, so the
            # picker had no real cap to enforce or show. `lora` wins when present (mirrors
            # the CLI's own field-check order -- an account's live paid entitlement);
            # `freeUserLora` is the fallback for an account with no `lora` value at all.
            # Exact coexistence semantics of the two fields are unconfirmed (no live account
            # to probe against from this checkout) -- treated as a soft pre-submit guard the
            # client can warn from, not a hard block, since PixAI's own server is the real
            # authority on any submit that slips past it.
            # Shared with the submit-side guard so the number the drawer PAINTS and the
            # number the server ENFORCES can never disagree. Crucially this now returns the
            # free-tier cap for a non-member instead of null: null hid the counter and
            # switched the client guard off entirely the moment a membership lapsed.
            lora_cap = core.account_lora_cap(me)
            # Backup coverage: server's lifetime TASK count vs distinct tasks we hold locally.
            # Both are task counts (not images), so the ratio is honest.
            try:
                server_tasks = int((me.get("tasks") or {}).get("totalCount"))
            except (TypeError, ValueError):
                server_tasks = None
            local_tasks = distinct_task_count(db_path)
            coverage = (round(min(100.0, local_tasks / server_tasks * 100), 1)
                        if server_tasks else None)
            # Paid/free credit split for the rail sub-line (Account-detail design, drift
            # §37). A SUPPLEMENTARY read in its own guard: it must never break the core
            # account response (credits/cards/coverage) if the split call fails -- a failure
            # just leaves free/paid null, which the rail renders as an honest "split unknown".
            try:
                bal = core.credit_balance(session) or {}
            except Exception:
                bal = {}
            return jsonify({"credits": credits, "cards": cards,
                            "credits_free": bal.get("free"), "credits_paid": bal.get("paid"),
                            "cards_by": cards_by, "card_expiry": card_expiry,
                            "claim_credits": claim_credits, "claim_ids": claim_ids,
                            "sub": {"end": (sub.get("endAt") or "")[:10],
                                    "cancel": bool(sub.get("cancelAtPeriodEnd"))},
                            "server_tasks": server_tasks, "local_tasks": local_tasks,
                            "coverage_pct": coverage,
                            "followers": me.get("followerCount"),
                            "following": me.get("followingCount"),
                            "lora_cap": lora_cap,
                            # True / False / null=unknown. The drawer gates members-only
                            # controls on an explicit False only, so an unreadable account
                            # never strips a paying member's options.
                            "is_member": core.account_is_member(me)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    # --- Account detail (cards · coupons · credit ledger) -------------------------------
    # The web UI for the card-coupon-ledger branch's backend, wired into the Control Panel's
    # "PixAI account" modal (Account-detail design, drift §37). All three are READ-ONLY
    # account queries -- no mutation, no spend, no redeem -- and fail soft to {"error"}, 200
    # exactly like /api/account, so the modal degrades gracefully when PixAI is unreachable.
    def _acct_count(default, lo=1, hi=100):
        try:
            return max(lo, min(int(request.args.get("count") or default), hi))
        except (TypeError, ValueError):
            return default

    @app.route("/api/account/card-history")
    def api_account_card_history():
        """Benefit-card (kaisuuken) usage. ?all=1 -> the lifetime type roster
        (kaisuuken_type_catalog); otherwise the recent usage events (list_kaisuuken_logs,
        forward-paginated via ?after=<cursor>). Read-only."""
        try:
            core, session = _gen_session()
            if request.args.get("all") in ("1", "true", "yes"):
                return jsonify(core.kaisuuken_type_catalog(session))
            after = request.args.get("after") or None
            return jsonify(core.list_kaisuuken_logs(session, first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/coupons")
    def api_account_coupons():
        """Coupons / Credit Boost. On-hand (available|locked) by default; ?history=1 swaps
        to redeemed|expired. Informational only -- no redeem/apply here by design. Read-only,
        forward-paginated via ?after=<cursor>."""
        try:
            core, session = _gen_session()
            history = request.args.get("history") in ("1", "true", "yes")
            statuses = core.COUPON_STATUSES_HISTORY if history else core.COUPON_STATUSES_ON_HAND
            after = request.args.get("after") or None
            return jsonify(core.list_extra_package_boosts(session, statuses=statuses,
                                                          first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/credit-log")
    def api_account_credit_log():
        """Full credit movement history (purchase/gift/spend/refund). Newest-first;
        BACKWARD-paginated via ?before=<cursor>. Optional ?reason=<type> filter. Read-only."""
        try:
            core, session = _gen_session()
            before = request.args.get("before") or None
            reason = request.args.get("reason") or None
            return jsonify(core.list_credit_log(session, last=_acct_count(30),
                                                before=before, reason=reason))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/stats")
    def api_stats():
        """Catalog totals for fetch()-driven headers: the SAME numbers the classic
        template bakes into its banner (catalog_counts -- images, videos, distinct
        collections) plus the backed-up percent its cover-badge lazily pulls from
        /api/account, computed the identical way (server lifetime TASK count from
        account_info vs distinct_task_count locally; both are tasks, not images, so
        the ratio is honest -- see api_account above). LOGIN tier, matching index()
        and /api/account.

        The account read fails soft: coverage_pct/server_tasks come back null when
        PixAI is unreachable, which is exactly the case where the classic banner
        shows counts but hides its coverage badge. The catalog counts never depend
        on the network."""
        counts = catalog_counts(db_path)
        local_tasks = distinct_task_count(db_path)
        try:
            core, gsession = _gen_session()
            me = core.account_info(gsession)
            server_tasks = int((me.get("tasks") or {}).get("totalCount"))
        except Exception:                                    # noqa: BLE001
            server_tasks = None
        coverage = (round(min(100.0, local_tasks / server_tasks * 100), 1)
                    if server_tasks else None)
        return jsonify({"images": counts["images"], "videos": counts["videos"],
                        "collections": counts["collections"],
                        "local_tasks": local_tasks, "server_tasks": server_tasks,
                        "coverage_pct": coverage})

    @app.route("/api/setup/save-key", methods=["POST"])
    def api_setup_save_key():
        """First-run wizard: validate the submitted key with a real, read-only account_info
        call, and only write config.json AFTER that succeeds -- never write first and hope.

        Deliberately does NOT go through core._make_session()/load_token(): those prefer
        the module-cached core._cfg over a fresh config.json read (by design, so a running
        process doesn't need a restart to keep using its already-loaded key), which means
        validating "the same way normal calls authenticate" would silently validate against
        whatever key was cached at process start, not the one just pasted here. Confirmed
        live: a garbage key was reported as verified because the real cached key answered
        instead. Building the session by hand with the submitted key as the sole credential
        avoids that entirely.

        LOCALHOST-ONLY, enforced below -- this docstring has claimed it since the route
        was written, but the check itself was never actually present; a route-gating
        audit found and reproduced it 2026-07-19. It belongs in the same trust class as
        /api/branding/shortcut: it rewrites config.json, the file that also holds
        AUTH_SECRET_KEY and AUTH_USERS. Without the check, any logged-in LAN session
        could point the owner's generations at a foreign API key -- on a server started
        without a key (the exact first-run state this endpoint exists for) load_token's
        fresh-disk fallback picks it up on the very next spend."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        body = request.get_json(silent=True) or {}
        key = (body.get("api_key") or "").strip()
        if not key:
            return jsonify({"error": "paste your API key first"}), 400
        import moonglade_backup as core
        import requests as _requests
        test_session = _requests.Session()
        test_session.headers.update({
            "Authorization": "Bearer {}".format(key),
            "Accept": "application/json",
            "User-Agent": "pixai-personal-backup/1.0",
            "apollo-require-preflight": "true",
            "x-apollo-operation-name": core.OPERATION_NAME,
        })
        try:
            me = core.account_info(test_session, raise_on_error=True)
        except Exception as e:
            msg = _redact_host_paths(str(e))
            if "401" in msg or "Unauthorized" in msg:
                return jsonify({"error": "That key was rejected by PixAI -- double-check it."}), 200
            return jsonify({"error": "Couldn't verify that key (temporary connection issue) -- try again."}), 200
        cfg_path = Path(core.__file__).resolve().parent / "config.json"
        # Serialize against the account writers on core._accounts_lock. This is the only
        # config.json read-modify-write in the app that doesn't go through core's account
        # helpers (deliberately -- see the note above about the module-cached _cfg), which
        # made it the one writer that could lost-update: /api/users/add commits a new
        # account between this read and this write, and the write puts back a snapshot
        # that never had it, silently erasing the account. Same lock, so same queue.
        with core._accounts_lock:
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
            except ValueError:
                # Present but unparseable -- REFUSE rather than overwrite. The old
                # bare `cfg = {}` fallback wrote back a one-key stub, destroying
                # AUTH_USERS (dropping the install into local-bootstrap mode),
                # AUTH_SECRET_KEY (logging everyone out), and now AUTH_EPOCH_SEQ
                # (rewinding revocation state itself).
                return jsonify({"error": "config.json exists but could not be parsed; "
                                         "not overwriting it. Fix or restore the file, "
                                         "then save the key again."}), 200
            except OSError as e:
                return jsonify({"error": "Could not read config.json: {}".format(
                    _redact_host_paths(str(e)))}), 200
            cfg["PIXAI_API_KEY"] = key
            try:
                cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            except OSError as e:
                return jsonify({"error": "Key verified, but couldn't write config.json: {}".format(
                    _redact_host_paths(str(e)))}), 200
            # Writing the file is only half of "saved": load_token() prefers core's
            # import-time _cfg snapshot over a fresh disk read, so a server that already
            # had a key kept authenticating every generation/account call with the OLD
            # one -- rotating a revoked key or switching accounts changed nothing until a
            # restart, while this route reported success. Refreshed ONLY for the field
            # just persisted, and only after the write actually landed; the rest of the
            # snapshot keeps the caching behaviour the rest of the app relies on.
            core._cfg["PIXAI_API_KEY"] = key
        try:
            credits = int(me.get("quotaAmount") or 0)
        except (TypeError, ValueError):
            credits = None
        return jsonify({"ok": True, "credits": credits})

    @app.route("/api/assets/status")
    def api_assets_status():
        """The asset container's current state: whether a (re)fetch is needed and,
        if a fetch is running/just finished/just failed, its live progress. LOGIN
        tier -- a read-only status poll, same trust class as /api/panel/status's
        non-sensitive half (this payload carries no host paths or account detail
        to redact, so unlike that route there is no local-vs-LAN split here).

        `needs` is computed fresh each call (moonglade_assets.needs_download(),
        a marker-file comparison, not a full re-hash) so a container that just
        finished downloading -- or was hand-copied in from another machine mid-
        session -- is reflected on the very next poll, not after a restart."""
        job = _asset_job.status()
        manifest = moonglade_assets.read_manifest()
        return jsonify({
            "needs": moonglade_assets.needs_download(_container_path(), manifest),
            "manifest_present": manifest is not None,
            **job,
        })

    @app.route("/api/assets/fetch", methods=["POST"])
    def api_assets_fetch():
        """Start the asset container fetch. LOCALHOST-ONLY, same trust class as
        /api/setup/save-key just above -- it writes a real file into the app
        root. Single-flight: a second call while one is already running is a
        409, matching /api/panel/run's own busy shape, not a second job."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        started = _asset_job.start()
        if not started:
            st = _asset_job.status()
            if st["status"] == "running":
                return jsonify({"error": "a download is already running"}), 409
            return jsonify({"error": st.get("error") or "could not start"}), 200
        return jsonify({"ok": True})

    @app.route("/api/claim", methods=["POST"])
    def api_claim():
        """Claim ready daily rewards (free credits/stamina to the owner's OWN account -- no
        money moves). Login required; the header click IS the confirmation. One bad claim
        doesn't abort the rest. Returns {claimed, credits}."""
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
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    _snips_lock = threading.Lock()

    def _snips_dir():
        d = out_dir / "prompt_snippets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _snips_path(user):
        # _account_key (B14 residual): a case-safe key, so "Nel" and "nel" don't
        # collapse onto one file the way a bare quote(username) did on NTFS.
        return _snips_dir() / (_account_key(user) + ".json")

    def _legacy_snips_path():
        return out_dir / "prompt_snippets.json"

    def _read_snips_file(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(s) for s in data]
        except (OSError, ValueError):
            pass
        return []

    def _load_snippets(user):
        """This account's snippets, falling back to the legacy shared file -- same
        deliberately-read-only fallback as _load_view_presets: an account with no file
        of its own yet sees whatever the old shared file held (nothing disappears), and
        diverges the moment it saves its own."""
        own = _snips_path(user)
        if own.exists():
            return _read_snips_file(own)
        return _read_snips_file(_legacy_snips_path())

    @app.route("/api/snippets", methods=["GET", "POST"])
    def api_snippets():
        """Prompt snippets/favorites, stored PER-ACCOUNT (out_dir/prompt_snippets/<user>.json)
        so one signed-in account can't see or wholesale-clobber another's -- same split saved
        views already got. Falls back read-only to the legacy shared
        out_dir/prompt_snippets.json for an account that hasn't saved its own copy yet.
        Login required (any session, local or LAN)."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        with _snips_lock:
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                snips = body.get("snippets")
                if not isinstance(snips, list):
                    return jsonify({"error": "snippets must be a list"}), 400
                clean = [str(s)[:800] for s in snips if str(s).strip()][:200]
                try:
                    _snips_path(user).write_text(json.dumps(clean), encoding="utf-8")
                except OSError as e:
                    return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
                return jsonify({"snippets": clean})
            return jsonify({"snippets": _load_snippets(user)})

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
            return jsonify({"error": _redact_host_paths(str(e))[:200], "contests": []}), 200

    @app.route("/api/artwork-views")
    def api_artwork_views():
        """Live view count for one published artwork -> the detail page's Views metric.
        Login required; uses the owner's key. ?id=<artwork_id>."""
        aid = (request.args.get("id") or "").strip()
        if not aid:
            return jsonify({"views": None}), 400
        try:
            core, session = _gen_session()
            return jsonify({"views": core.artwork_views(session, aid)})
        except Exception as e:
            return jsonify({"views": None, "error": _redact_host_paths(str(e))[:120]}), 200

    @app.route("/api/your-art")
    def api_your_art():
        """'Your Art' panel: the owner's top published works ranked by likes (from the catalog,
        so it works over LAN) enriched with LIVE view counts (fetched per artwork_id, using the
        owner's key -- same trust level as /api/artwork-views, which this loop is really just a
        batched version of). Read-only, no spend.

        No `_is_authorized_request()` conjunct here: this whole route is now covered by the
        global front-door hook (see _enforce_front_door()'s docstring), so reaching this line
        already guarantees it -- an explicit re-check here would be dead-always-true, the same
        class of redundant check removed from the 43 individually-gated routes."""
        top = top_published_rows(db_path, 12)
        totals = published_totals(db_path)
        views_synced = False
        if top:
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

    @app.route("/api/myart/items")
    def api_myart_items():
        """Card-ready rows for the My Art tabbed gallery (Frontend Gallery.dc.html's
        ovMyArt, rebuilt 2026-08-06): every catalog row that exists as a PixAI ARTWORK
        (artwork_id set by --sync-artworks), public AND private -- the design's
        Visibility filter distinguishes them ('everything you've made, published or
        held back'). Pure catalog read, no network: title/likes/comments/tags/nsfw
        arrive via --sync-artworks; thumbs are the local /thumbs/<mid>.jpg the grid
        already serves. The Artworks/Animations tab split is the is_video flag."""
        con = _connect(db_path)
        try:
            rows = con.execute(
                "SELECT media_id, artwork_id, title, prompt_preview, is_video, is_nsfw,"
                " created_at, art_tags, is_published,"
                " CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) AS likes,"
                " CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER) AS comments"
                " FROM catalog WHERE COALESCE(artwork_id,'') != '' AND media_id != ''"
                " ORDER BY created_at DESC").fetchall()
        finally:
            con.close()
        items = []
        for (mid, aid, title, preview, is_video, is_nsfw, created, tags, pub,
             likes, comments) in rows:
            items.append({
                "media_id": mid, "artwork_id": aid,
                "title": (title or "").strip() or (preview or "").strip()[:60] or mid,
                "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": is_video == "1", "is_nsfw": is_nsfw == "1",
                "date": (created or "")[:10],
                "created_at": created or "",
                "tags": [t.strip() for t in (tags or "").split(",") if t.strip()][:4],
                "public": pub == "1", "likes": likes, "comments": comments,
            })
        # The card actions POST to /api/myart/publish, which is in the explicit-token
        # CSRF class; MG_BOOT doesn't carry the token, so it rides along here rather
        # than making the overlay fetch the whole Control Panel summary for one field.
        return jsonify({"items": items, "csrf": session.get("csrf", "")})

    def _artwork_row(mid):
        """The catalog row behind one media_id (artwork_id/task_id/title), or None."""
        con = _connect(db_path)
        try:
            r = con.execute(
                "SELECT media_id, artwork_id, task_id, title, art_tags, is_published"
                " FROM catalog WHERE media_id = ? LIMIT 1", (str(mid),)).fetchone()
        finally:
            con.close()
        if not r:
            return None
        return {"media_id": r[0], "artwork_id": r[1], "task_id": r[2],
                "title": r[3], "art_tags": r[4], "is_published": r[5]}

    @app.route("/api/myart/publish", methods=["POST"])
    def api_myart_publish():
        """Publish / unpublish / re-tag / delete one of the owner's artworks -- the My Art
        card actions and the Lightbox/Details Publish button.

        PREVIEW-FIRST, like every other account-mutating path in this app: without
        `confirm: true` the route performs NO network call and returns exactly what it
        WOULD do (action, target, resolved tag ids, and anything it could not resolve).
        The UI shows that preview and only then sends the confirmed call. READ_ONLY in
        config.json refuses the confirmed form regardless, inside the core functions.

        Actions:
          publish   -- createArtworkFromTaskV2 for a media_id that has no artwork yet
                       (needs its task_id + the image's index in that task)
          visibility-- upsertArtwork flipping public/private on an existing artwork
          tags      -- upsertArtwork replacing the tack list
          delete    -- deleteArtwork (irreversible on PixAI; local files untouched)

        CSRF: explicit-token class, matching /api/duplicates/resolve and the user-admin
        routes -- a real account mutation triggered by one web click."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        action = str(body.get("action") or "").strip()
        mid = str(body.get("media_id") or "").strip()
        if action not in ("publish", "visibility", "tags", "delete"):
            return jsonify({"error": "unknown action"}), 400
        row = _artwork_row(mid)
        if not row:
            return jsonify({"error": "unknown media id"}), 400
        confirm = bool(body.get("confirm"))
        tags = body.get("tags") if isinstance(body.get("tags"), list) else None
        private = body.get("private")
        title = body.get("title")

        if action == "publish" and row["artwork_id"]:
            return jsonify({"error": "already published -- use visibility/tags instead"}), 400
        if action != "publish" and not row["artwork_id"]:
            return jsonify({"error": "not published yet -- publish it first"}), 400
        if action == "publish" and not row["task_id"]:
            return jsonify({"error": "no task id for that image -- it can't be published from a task"}), 400

        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s" % e}), 502

        tack_ids, unmatched = [], []
        if tags is not None:
            tack_ids, unmatched = core.resolve_tack_ids(session, tags)   # read-only

        # Which image of its task this media_id is. Resolved SERVER-side from the task's
        # own ordered outputs, never taken from the client: publishing index 2 when the
        # user picked index 0 puts the wrong picture on their public profile, and that is
        # not a recoverable mistake. Read-only lookup, so it runs during preview too --
        # which is what lets the preview refuse an unresolvable image before confirming.
        media_index = None
        if action == "publish":
            media_index = core.task_media_index(session, row["task_id"], mid)
            if media_index is None:
                return jsonify({"error": "couldn't work out which image of task %s this is "
                                         "-- refusing to publish rather than risk the wrong "
                                         "one" % row["task_id"]}), 400

        if not confirm:
            return jsonify({"preview": True, "action": action, "media_id": mid,
                            "artwork_id": row["artwork_id"], "task_id": row["task_id"],
                            "title": title if title is not None else row["title"],
                            "private": private, "tack_ids": tack_ids,
                            "unmatched_tags": unmatched,
                            "media_index": media_index,
                            "spends_credits": False,
                            "irreversible": action == "delete"})
        try:
            if action == "publish":
                # Same null-preserving expression the preview above uses (line ~15873) --
                # an intentionally CLEARED title (title == "") must publish empty, not
                # silently fall back to the catalog's old title. `or` treats "" as falsy,
                # which is exactly the bug: the confirm sheet showed "(untitled)" but the
                # mutation went out with the stale title. Only an absent field (title is
                # None, the client never sent it) falls back. Found by ultrareview 2026-08-06.
                art = core.publish_artwork_from_task(
                    session, row["task_id"],
                    media_index=media_index,
                    title=(title if title is not None else row["title"]) or "",
                    description=body.get("description") or "",
                    tack_ids=tack_ids, private=bool(private),
                    hide_prompts=bool(body.get("hide_prompts")),
                    challenge=body.get("challenge") or None)
                result = {"artwork_id": art.get("id"), "published": True}
            elif action == "delete":
                core.delete_artwork(session, row["artwork_id"])
                result = {"deleted": True}
            else:
                art = core.update_artwork(
                    session, row["artwork_id"],
                    title=title,
                    tack_ids=(tack_ids if tags is not None else None),
                    private=(None if private is None else bool(private)))
                result = {"artwork_id": art.get("id") or row["artwork_id"], "updated": True}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

        # Mirror the change into the catalog so the grid reflects it without a full sync.
        con = _connect(db_path)
        try:
            if action == "delete":
                con.execute("UPDATE catalog SET artwork_id='', is_published='0' WHERE media_id=?", (mid,))
            else:
                if action == "publish":
                    con.execute("UPDATE catalog SET artwork_id=?, is_published=? WHERE media_id=?",
                                (result.get("artwork_id") or "", "0" if private else "1", mid))
                if private is not None:
                    con.execute("UPDATE catalog SET is_published=? WHERE media_id=?",
                                ("0" if private else "1", mid))
                if tags is not None:
                    con.execute("UPDATE catalog SET art_tags=? WHERE media_id=?",
                                (", ".join(str(t).lstrip("#").strip() for t in tags), mid))
                if title is not None:
                    con.execute("UPDATE catalog SET title=? WHERE media_id=?", (title, mid))
            con.commit()
        finally:
            con.close()
        result["unmatched_tags"] = unmatched
        return jsonify(result)

    def _lineage_card(row):
        """One image reduced to a lineage chip: id, thumb, video flag, and a title hint."""
        mid = row["media_id"]
        return {"media_id": mid, "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": (row["is_video"] == "1"),
                "title": (row["title"] or "").strip() or (row["prompt_preview"] or "").strip()[:48]}

    @app.route("/api/lineage/<media_id>")
    def api_lineage(media_id):
        """The family tree of one image, for Image Details' LINEAGE panel:
          * siblings -- the other outputs of the SAME generation task (share task_id; up to
            4 per batch). Free -- task_id is already indexed.
          * parent   -- the SOURCE image this one was derived from (source_media_id), plus
            the kind of derivation (edit/upscale/video).
          * children -- every image derived FROM this one (rows whose source_media_id == this).
        Pure catalog read, no network. Any dimension can be empty (an original txt2img with
        a batch size of 1 and no derivatives has an empty tree)."""
        mid = str(media_id or "").strip()
        con = _connect(db_path)
        try:
            me = con.execute(
                "SELECT media_id, task_id, source_media_id, derive_kind FROM catalog"
                " WHERE media_id = ? LIMIT 1", (mid,)).fetchone()
            if not me:
                return jsonify({"error": "unknown media id"}), 404
            cols = ("media_id, is_video, title, prompt_preview")
            siblings = []
            if me["task_id"]:
                siblings = [_lineage_card(r) for r in con.execute(
                    "SELECT %s FROM catalog WHERE task_id = ? AND media_id != ?"
                    " ORDER BY media_id" % cols, (me["task_id"], mid)).fetchall()]
            parent = None
            if me["source_media_id"]:
                pr = con.execute("SELECT %s FROM catalog WHERE media_id = ? LIMIT 1" % cols,
                                 (me["source_media_id"],)).fetchone()
                if pr:
                    parent = dict(_lineage_card(pr), kind=me["derive_kind"] or "derived")
            children = [dict(_lineage_card(r), kind=(r["derive_kind"] or "derived"))
                        for r in con.execute(
                            "SELECT %s, derive_kind FROM catalog WHERE source_media_id = ?"
                            " ORDER BY created_at" % cols, (mid,)).fetchall()]
        finally:
            con.close()
        return jsonify({"media_id": mid, "siblings": siblings,
                        "parent": parent, "children": children})

    @app.route("/api/siblings", methods=["POST"])
    def api_siblings():
        """Page-batched Sibling Strip data for the card placard (issue #30): every
        output of each requested task, in ONE query. The per-card /api/lineage fetch
        cost ~4.3s per 100-card page; this costs ~85ms (probe 2026-08-22).
        Body {"task_ids": [...]} (cap 200; blanks and non-strings dropped). Returns
        {"by_task": {task_id: [{media_id, is_video, thumb, batch_index}, ...]}},
        INCLUDING self (the client lights self by media_id); a task with
        fewer than 2 members is omitted -- a single output has no strip.
        ORDER (issue #33): when EVERY member of a task carries a batch_index --
        PixAI's own permanent output number, captured from getTaskById
        outputs.batch -- members come back in that order (media_id order can swap
        outputs); otherwise media_id order, as before. batch_index is an int, or
        null on a row that has none. Indexes are never renumbered or inferred: a
        deleted sibling leaves a true gap.
        An empty task_id is NEVER queried: every import shares '' and would
        otherwise become one giant pseudo-batch. Pure catalog read, no network."""
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        raw_ids = body.get("task_ids") or []
        if not isinstance(raw_ids, list):
            return jsonify({"error": "task_ids must be a list"}), 400
        ids = []
        seen = set()
        for t in raw_ids:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            ids.append(t)
            if len(ids) >= 200:
                break
        by_task = {}
        if ids:
            con = _connect(db_path)
            try:
                rows = con.execute(
                    "SELECT task_id, media_id, is_video, batch_index FROM catalog"
                    " WHERE task_id IN (%s) AND task_id != ''"
                    " ORDER BY task_id, media_id" % ",".join("?" * len(ids)),
                    ids).fetchall()
            finally:
                con.close()
            for r in rows:
                mid = str(r["media_id"] or "")
                if not mid:
                    continue
                # PixAI's own output number (issue #33): int in the payload, null when
                # the row has none. A non-integer value counts as absent -- the index is
                # only ever the site's own captured fact, never guessed.
                try:
                    bi = int(str(r["batch_index"] or "").strip())
                except ValueError:
                    bi = None
                by_task.setdefault(str(r["task_id"]), []).append({
                    "media_id": mid,
                    "is_video": str(r["is_video"] or "") == "1",
                    "thumb": "/thumbs/{}.jpg?s=32".format(mid),
                    "batch_index": bi,
                })
            by_task = {t: m for t, m in by_task.items() if len(m) >= 2}
            # Order by PixAI's own batch_index only when EVERY member of the task has
            # one (issue #33: media_id order can swap outputs). Any member without an
            # index means the batch order is not fully known -- keep media_id order
            # rather than half-sorting; indexes are never renumbered or inferred.
            for members in by_task.values():
                if all(m["batch_index"] is not None for m in members):
                    members.sort(key=lambda m: m["batch_index"])
        return jsonify({"by_task": by_task})

    @app.route("/api/series", methods=["POST"])
    def api_series():
        """Page-batched dial-in series membership for the card placard and the
        grouped grid (issue #34): which of the requested tasks belong to a
        multi-task series, and where in it. Body {"task_ids": [...]} -- the same
        hygiene as /api/siblings (cap 200; blanks/non-strings dropped; non-list
        400). Returns {"by_task": {tid: {sid, v, of, reroll, label, title}}}.
        ONLY tasks that are in a multi-task series appear: singletons (85% of
        the library) cost nothing here and the client renders nothing for an
        absent tid -- the same "a single output has no strip" shape as
        /api/siblings. Pure catalog read (through the series cache), no
        network."""
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        raw_ids = body.get("task_ids") or []
        if not isinstance(raw_ids, list):
            return jsonify({"error": "task_ids must be a list"}), 400
        ids = []
        seen = set()
        for t in raw_ids:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            ids.append(t)
            if len(ids) >= 200:
                break
        out = {}
        if ids:
            by_task_idx, by_sid = series_index(db_path)
            for tid in ids:
                hit = by_task_idx.get(tid)
                if not hit:
                    continue
                sid, v = hit
                s = by_sid.get(sid)
                if not s:
                    continue
                step = s["steps"][v - 1]
                out[tid] = {"sid": sid, "v": v, "of": s["count_tasks"],
                            "reroll": step["reroll"], "label": step["label"],
                            "title": s["title"]}
        return jsonify({"by_task": out})

    @app.route("/api/series/<sid>")
    def api_series_detail(sid):
        """One series' full struct for C's SESSION strip and B's expansion
        (issue #34): title, model, counts, [first_ts, last_ts] span, and the
        ordered steps {task_id, v, reroll, label, first_media_id, n}.
        first_media_id is the member task's first output in batch order when
        the order is known (#33), else lowest media_id. The sid is the FIRST
        member task's id -- deterministic across recomputes, so a bookmarked
        `?series=<sid>` URL keeps resolving (review item 1). 404 for a sid that
        is not a current multi-task series (including a sid whose series
        dissolved after deletions -- honest, like the v-numbers). Pure catalog
        read (through the series cache), no network."""
        _, by_sid = series_index(db_path)
        s = by_sid.get(str(sid or "").strip())
        if not s:
            return jsonify({"error": "unknown series id"}), 404
        return jsonify(s)

    @app.route("/api/train/recent-tasks")
    def api_train_recent_tasks():
        """Recent generations grouped by task, for the mobile Train dataset picker
        (Moonglade Mobile.dc.html's 'tap a task, it adds its images' tile grid). Desktop's
        picker selects individual images one at a time; the mobile design picks whole
        TASKS instead -- each tile is one generation, tapping it adds every real sibling
        image from that batch. The design's own mock assumes every task contributes
        exactly 4 images (a fixed demo constant); real batches are 1-4, so this returns
        each task's REAL image count and media_id list rather than a hardcoded number --
        the mobile picker's running total is a sum of real counts, not tiles*4.
        Pure catalog read, no network."""
        try:
            limit = max(1, min(int(request.args.get("limit") or 18), 60))
        except ValueError:
            limit = 18
        con = _connect(db_path)
        try:
            rows = con.execute(
                "SELECT media_id, task_id, is_video, created_at FROM catalog"
                " WHERE task_id != '' AND is_video != '1' AND filename != ''"
                " ORDER BY created_at DESC LIMIT 400").fetchall()
        finally:
            con.close()
        groups, order = {}, []
        for r in rows:
            tid = r["task_id"]
            if tid not in groups:
                if len(order) >= limit:
                    continue
                groups[tid] = []
                order.append(tid)
            if tid in groups:
                groups[tid].append(r["media_id"])
        tasks = [{"task_id": tid, "media_ids": groups[tid], "count": len(groups[tid]),
                  "thumb": "/thumbs/%s.jpg" % groups[tid][0]} for tid in order]
        return jsonify({"tasks": tasks})

    @app.route("/api/train/quota")
    def api_train_quota():
        """How many FREE LoRA trainings are left (PixAI quota `free::user_lora_training`,
        NOT a kaisuuken card -- the card pool is generation-only). Read-only, free."""
        try:
            core, session = _gen_session()
            return jsonify({"free_trainings": core.training_free_quota(session)})
        except Exception as e:
            return jsonify({"free_trainings": 0,
                            "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/train/models")
    def api_train_models():
        """Trainable base models grouped by architecture (the train panel's Model Type ->
        Model Theme picker). Read-only, free. Each model carries the VERSION id the submit
        needs, its real title, and a cover -- fixing the earlier build, which used the
        generic market search and rendered raw model ids with no architecture grouping."""
        try:
            core, session = _gen_session()
            return jsonify({"groups": core.list_trainable_base_models(),
                            "pricing": core._TRAIN_PRICING})
        except Exception as e:
            return jsonify({"groups": [], "error": _redact_host_paths(str(e))[:200]}), 200

    import requests as _rq

    @app.route("/api/train/cover")
    @app.route("/api/pixai-cdn/thumb")   # the general name -- covers My Art's LoRA cards too
    def api_train_cover():
        """Proxy a PixAI CDN thumbnail (images-ng.pixai.art), which the browser can't load
        cross-origin from localhost but the server fetches fine. Started as the Train
        panel's base-model covers; My Art's Models & LoRAs tab (2026-08-06) hit the exact
        same block for its own cover_url rows and reuses this route rather than growing a
        second proxy. SSRF-guarded: the URL host MUST be exactly the PixAI image CDN --
        nothing else is fetchable through here. Read-only, cached a day (these thumbnails
        are immutable)."""
        import urllib.parse as _up
        raw = request.args.get("u") or ""
        try:
            parsed = _up.urlparse(raw)
        except ValueError:
            return ("bad url", 400)
        if parsed.scheme != "https" or parsed.netloc != "images-ng.pixai.art":
            return ("forbidden host", 403)
        try:
            # PUBLIC CDN thumbnails -- no auth needed (verified). A PLAIN per-request
            # requests.get, NOT _gen_session() and NOT a shared Session: the panel loads
            # ~15 covers at once across Flask's request threads, and (a) minting an
            # authenticated PixAI session per image is too slow, while (b) sharing one
            # requests.Session across those threads is not thread-safe and hangs them.
            # A fresh get() per call is thread-safe and plenty fast for cached thumbnails.
            r = _rq.get(raw, timeout=20)
            if r.status_code != 200:
                return ("upstream %d" % r.status_code, 502)
            resp = app.response_class(r.content,
                                      mimetype=r.headers.get("content-type", "image/webp"))
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        except Exception:
            return ("fetch failed", 502)

    @app.route("/api/train/submit", methods=["POST"])
    def api_train_submit():
        """Submit a LoRA training task -- PREVIEW-FIRST, like /api/myart/publish.

        Without `confirm: true` this makes NO mutating call: it validates the request
        with the site's own rules and reports the real cost position (how many free
        trainings remain, whether this one is free).

        COST SAFETY. PixAI prices training CLIENT-side from a matrix, so there is no
        server value to quote (documented in private/GENERATOR_SURFACE.md). That gives
        exactly two honest states:
          * free quota > 0  -> this training is FREE and consumes one quota unit.
          * free quota == 0 -> it costs real credits, and this app CANNOT say how many.
            The confirmed call is then REFUSED unless the caller also sends
            `accept_credit_cost: true`, so nobody spends a large unknown amount by
            clicking the same button they used when it was free.
        READ_ONLY still refuses the confirmed form inside core. Explicit-token CSRF."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        media_ids = body.get("media_ids") if isinstance(body.get("media_ids"), list) else []
        base_model_id = str(body.get("base_model_id") or "").strip()
        title = str(body.get("title") or "")
        trigger = str(body.get("trigger_words") or "")
        category = str(body.get("category") or "")
        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s" % e}), 502

        try:
            tw = core.validate_training(base_model_id, media_ids, title, trigger, category)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        free_left = core.training_free_quota(session)
        is_free = free_left > 0
        price = core.training_price_for_version(base_model_id)   # credits, or None if unknown
        if is_free:
            cost_note = "Free — uses 1 of your %d free trainings." % free_left
        elif price is not None:
            cost_note = ("No free trainings left — this base costs %s credits to train."
                         % "{:,}".format(price))
        else:
            cost_note = ("No free trainings left, and this app can't price this base — "
                         "check the cost on PixAI before going ahead.")
        if not bool(body.get("confirm")):
            return jsonify({
                "preview": True, "image_count": len(media_ids),
                "title": title.strip(), "trigger_words": tw, "category": category,
                "free_trainings_left": free_left, "is_free": is_free,
                "price": price, "cost_note": cost_note,
            })
        if not is_free and not bool(body.get("accept_credit_cost")):
            return jsonify({"error": "This training charges credits (%s). Re-send with "
                                     "accept_credit_cost to proceed."
                                     % (("{:,}".format(price)) if price is not None
                                        else "amount unknown")}), 402
        try:
            task = core.submit_training(session, base_model_id, media_ids, title, trigger,
                                        category)
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"submitted": True, "task": task, "was_free": is_free,
                        "free_trainings_left": max(0, free_left - 1) if is_free else 0})

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
        that aren't earned go out MASKED -- collapsed to a single ??? placeholder
        so devtools can't spoil them or even count how many remain; the whole
        feat tab stays cloaked until the first feat lands."""
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
        # "Under the Hood"'s real trigger -- unlike sweep_telemetry above, this runs
        # EVERY call, not once a day: a curious user who just dropped a file into
        # branding/<slot>/ deserves the achievement on their next reload, not up to
        # a day later. See sweep_branding_drops()'s own docstring.
        try:
            sweep_branding_drops(out_dir)
        except Exception:
            pass
        metrics = achievement_metrics(db_path)
        metrics.update(telemetry_metrics(out_dir))
        # Gate the unlock toasts until the first full sync completes (see first_sync_complete):
        # first-light is images>=1, so without this it pops seconds into a fresh first sync.
        fsd = first_sync_complete(out_dir, db_path)
        persist_error = None
        with _ach_lock:
            state = load_ach_state(out_dir)
            result = compute_achievements(metrics, state.get("seen"),
                                          sets=load_telemetry(out_dir).get("sets", {}))
            newly = result["newly"]
            if not fsd:
                result["newly"] = []   # first sync still running -- withhold celebrations and
                newly = []             # leave `seen` untouched so the rungs fire on completion
            if fsd and request.args.get("mark") == "1":
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
                # save_ach_state()'s bool return used to be discarded here, so a disk-write
                # failure still answered 200 with no hint that "seen"/earned_at never made it
                # to disk -- the newly-earned toast would then re-fire on the next load since
                # the server forgot it already showed it. The achievements DATA below is still
                # correct either way (computed fresh from the catalog every call, not from the
                # state file), so this stays a soft error alongside a normal response rather
                # than failing the whole request.
                if not save_ach_state(out_dir, state):
                    persist_error = "could not save achievement progress (disk write failed)"
            earned_at = state.get("earned_at") or {}
        feats_revealed = any(
            a["earned"] for a in result["achievements"] if a["tier"] == "feat")
        unleashed = any(a["id"] == "triggered" and a["earned"]
                        for a in result["achievements"])
        # Masked feats COLLAPSE to a single placeholder (2026-08-13): the old
        # scheme kept one "hidden-feat-N" entry per undiscovered feat, so the
        # array length -- and any earned/total arithmetic a client renders --
        # counted exactly how many secrets were left. One placeholder says
        # "there are hidden feats" (which the placeholder itself publicizes)
        # and nothing more.
        masked_metrics, n_masked, visible = set(), 0, []
        for a in result["achievements"]:
            if a["hidden"] and not a["earned"]:
                n_masked += 1
                masked_metrics.add(a["metric"])
                continue
            if not a["earned"]:               # roasts are the reward, not a preview
                a["roast"] = ""
                a["roast_nsfw"] = ""
            elif not unleashed:               # uncensored lines stay locked until Triggered
                a["roast_nsfw"] = ""
            visible.append(a)
        if n_masked:
            visible.append({
                "id": "hidden-feat", "name": "???", "icon": "❓",
                "desc": "A hidden feat of the Athenaeum.",
                "tier": "feat", "bucket": "feat", "metric": "", "threshold": 1,
                "current": 0, "earned": False, "skin": "", "hidden": True,
                "banner_reward": False, "points": 0, "roast": "", "roast_nsfw": "",
            })
        result["achievements"] = visible
        # a masked feat's metric name/value must not leak through the metrics echo
        still_visible = {a["metric"] for a in result["achievements"] if a.get("metric")}
        for k in masked_metrics - still_visible:
            metrics.pop(k, None)
        result["feats_revealed"] = feats_revealed
        result["unleash_available"] = unleashed
        result["skin"] = state.get("skin", "moonglade")
        result["earned_at"] = earned_at   # {id: iso-date}; only earned ids -> no hidden-feat leak
        result["metrics"] = metrics
        if persist_error:
            result["error"] = persist_error
        return jsonify(result)

    @app.route("/api/skin", methods=["POST"])
    def api_skin():
        """Set the active cosmetic skin. Only an *earned* skin may be applied (server checks
        against current unlocks), so a client can't force a locked palette. Persists to
        out_dir/achievements.json. Cosmetic + local-only, no spend."""
        body = request.get_json(silent=True) or {}
        skin = str(body.get("skin") or "").strip()
        if skin not in _skin_ids():
            return jsonify({"error": "unknown skin"}), 400
        result = compute_achievements(achievement_metrics(db_path))
        earned = {s["id"] for s in result["skins"] if s["earned"]}
        if skin not in earned:
            return jsonify({"error": "skin locked", "skin": load_ach_state(out_dir)["skin"]}), 403
        with _ach_lock:
            state = load_ach_state(out_dir)
            changed = state.get("skin") != skin
            state["skin"] = skin
            saved = save_ach_state(out_dir, state)
        if not saved:
            # save_ach_state() is "best-effort; swallows write errors" by design (its own
            # docstring) -- but that return value used to be dropped on the floor here, so a
            # disk-write failure still answered 200 {"skin": skin} as if it had stuck. Report
            # what's ACTUALLY active (a fresh read, not the requested value) instead of lying.
            return jsonify({"error": "could not save skin (disk write failed)",
                            "skin": load_ach_state(out_dir)["skin"]}), 200
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

    @app.route("/api/mirror/status")
    def api_mirror_status():
        """Read-only status of 'Mirror to PixAI website': the toggle flag + the stored
        JWT's days-left, decoded OFFLINE (no network). NEVER returns the token (review
        F13). LOGIN tier."""
        import moonglade_backup as core
        jwt = (core.load_mirror_state().get("jwt") or "")
        return jsonify({"enabled": core.mirror_enabled(), "connected": bool(jwt),
                        "days_left": core.jwt_days_left(jwt) if jwt else None})

    @app.route("/api/mirror/enable", methods=["POST"])
    def api_mirror_enable():
        """Set the MIRROR_TO_PIXAI toggle in config.json. LOCALHOST-ONLY: it rewrites
        config.json (the file that also holds PIXAI_API_KEY, AUTH_USERS, AUTH_SECRET_KEY),
        so it is in the same trust class as /api/setup/save-key and /api/branding/shortcut --
        a logged-in LAN session must not be able to flip the owner's every generation onto
        the browser JWT. Reads the file DIRECTLY and REFUSES on a present-but-unparseable
        config rather than clobbering the whole auth block with a one-key stub (the exact
        wipe _save_config's docstring exists to prevent -- _load_config()'s ValueError->{}
        cannot tell a corrupt file from an empty one). Serialized on _accounts_lock with the
        other config writers."""
        if not _is_local_request():
            return jsonify({"error": "localhost-only"}), 403
        import moonglade_backup as core
        want = bool((request.get_json(silent=True) or {}).get("enabled"))
        cfg_path = Path(core.__file__).resolve().parent / "config.json"
        with core._accounts_lock:
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
            except ValueError:
                return jsonify({"error": "config.json exists but could not be parsed; not "
                                "overwriting it. Fix or restore the file, then try again."}), 200
            except OSError as e:
                return jsonify({"error": "Could not read config.json: {}".format(
                    _redact_host_paths(str(e)))}), 200
            # [MAJOR] Only ARM (true-write) when a usable browser JWT actually exists: arming the
            # mirror with no live session lets every Bridge/enhance submit hit the mirror-ON gate,
            # fail make_mirror_session(), and refuse -- an armed toggle that can run nothing. The
            # DISARM (false-write) is always allowed, so the owner can always turn it back off.
            if want and not core._jwt_usable(core.load_mirror_state().get("jwt") or ""):
                return jsonify({"error": "Connect the mirror first — not armed",
                                "enabled": False}), 200
            cfg["MIRROR_TO_PIXAI"] = want
            try:
                core._save_config(cfg)
            except OSError as e:
                return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
        return jsonify({"enabled": want})

    @app.route("/api/mirror/connect", methods=["POST"])
    def api_mirror_connect():
        """Bootstrap/refresh the mirror session: read the pixai.art session from THIS
        machine's browser, roll the JWT via refreshToken, store it. Reports only ok +
        days-left -- NEVER the token (review F13). No credential crosses the network: the
        server reads its own local browser store. LOGIN tier."""
        import moonglade_backup as core
        try:
            core._check_read_only("connect the PixAI mirror")   # refreshToken is account-mutating
            s = core.make_mirror_session(bootstrap_from_browser=True)
        except Exception as e:
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:160]}), 200
        if s is None:
            return jsonify({"ok": False, "error": "Couldn't read a pixai.art session from a "
                            "browser on this machine. Sign in to pixai.art in Chrome/Edge/Brave "
                            "(reload the page once so the token is written), then try again."}), 200
        jwt = (core.load_mirror_state().get("jwt") or "")
        return jsonify({"ok": bool(jwt),
                        "days_left": core.jwt_days_left(jwt) if jwt else None})

    @app.route("/api/branding", methods=["GET", "POST"])
    def api_branding():
        """The banner mark (the icon beside the title) + its animation. GET and POST both
        require login (any session, local or LAN) -- cosmetic, so any authorized device may
        read or change it, same as the rest of the LOGIN-tier settings surface.
        Persists to out_dir/branding.json."""
        if request.method == "GET":
            # Reflects a raw filesystem drop immediately, same as /api/achievements --
            # a caller reading branding state directly (this route, not the achievements
            # one) must never see a stale pre-adoption picture. Cheap; see
            # sweep_branding_drops()'s own docstring.
            try:
                sweep_branding_drops(out_dir)
            except Exception:
                pass
            cfg = load_branding(out_dir)
            return jsonify({"mark": cfg["mark"], "anim": cfg["anim"],
                            "anims": MARK_ANIMS, "marks": list_marks(out_dir),
                            "slots": branding_slots_payload(out_dir)})
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

    @app.route("/api/branding/slot", methods=["POST"])
    def api_branding_slot_upload():
        """Upload a new asset into one Branding slot (the three banner slots --
        Control Panel.dc.html's 'From disk' chip; mascots/rewards are NOT slots,
        see BRANDING_SLOTS' unlock-split note). LOGIN tier,
        matching /api/branding just above: cosmetic, no host-filesystem risk
        beyond writing into branding/, the same machine-local git-ignored tree
        marks already live in (NOT the shortcut route's stricter local-only gate).
        Re-encodes through Pillow rather than trusting the upload's own bytes/
        extension, the same defense-in-depth this app already applies to real
        library thumbnails (see _thumb_for, above)."""
        slot = request.form.get("slot") or ""
        if slot not in BRANDING_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        f = request.files.get("file")
        media_id = (request.form.get("media_id") or "").strip()
        if (f is None or not f.filename) and not media_id:
            return jsonify({"error": "no file"}), 400
        try:
            import io
            from PIL import Image
            if f is not None and f.filename:
                im = Image.open(f.stream)
            else:
                # "From the gallery..." (Control Panel.dc.html:342) -- source the asset
                # from the user's own library by media_id, via the same shared resolver
                # every other media_id->file path uses. Images only; a video id simply
                # resolves to no usable frame here.
                hits = find_files_for_media_id(out_dir, media_id)
                img_hit = next((p for p in hits if p.suffix.lower() in _IMAGE_EXTS), None)
                if img_hit is None:
                    return jsonify({"error": "no local image for that media id"}), 400
                im = Image.open(img_hit)
            im.load()
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        item = add_slot_asset(out_dir, slot, buf.getvalue())   # neutral transform to start
        return jsonify({"slot": slot, "item": item, "assets": list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/crop", methods=["POST"])
    def api_branding_slot_crop():
        """Update one uploaded asset's zoom/cropX/cropY transform (Control
        Panel.dc.html's three banner sliders). LOGIN tier, same as the upload
        route. Any of the three fields may be omitted to keep its stored value.
        Legacy `crop` (left/center/right) is still accepted for back-compat and
        mapped to a cropX pan. Widened 2026-08-06 from the old cycleCrop."""
        body = request.get_json(silent=True) or {}
        slot, item_id = body.get("slot"), str(body.get("id") or "")
        zoom, cropx, cropy = body.get("zoom"), body.get("cropX"), body.get("cropY")
        if zoom is None and cropx is None and cropy is None:
            legacy = {"left": 0, "center": 50, "right": 100}
            crop = str(body.get("crop") or "")
            if crop not in legacy:
                return jsonify({"error": "unknown crop value"}), 400
            cropx = legacy[crop]
        if not set_slot_crop(out_dir, slot, item_id, zoom=zoom, cropx=cropx, cropy=cropy):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"assets": list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/active", methods=["POST"])
    def api_branding_slot_active():
        """Pick which already-uploaded asset is active for a slot. LOGIN tier,
        same as the upload route. There is no "clear to none" -- see
        set_slot_active()'s own docstring for why."""
        body = request.get_json(silent=True) or {}
        slot, item_id = body.get("slot"), body.get("id")
        if not set_slot_active(out_dir, slot, str(item_id) if item_id else None):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"slots": branding_slots_payload(out_dir)})

    @app.route("/api/branding/mark/custom", methods=["POST"])
    def api_branding_mark_custom():
        """Upload The Great Library's custom mark (Control Panel.dc.html's 6th
        marks tile). LOGIN tier + a real server-side achievement check -- unlike
        the deferred banner-earned-art masking (still local-UI-only pending the
        SQLite asset-bundling project), this route actually performs a write, so
        it gets the same real gate /api/skin already applies to earned skins."""
        if not _mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "The Great Library hasn't been earned yet"}), 403
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        try:
            import io
            from PIL import Image
            im = Image.open(f.stream)
            im.load()
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        mark = add_custom_mark(out_dir, buf.getvalue())
        return jsonify({"mark": mark["id"], "marks": list_marks(out_dir)})

    @app.route("/api/branding/mark/custom/remove", methods=["POST"])
    def api_branding_mark_custom_remove():
        """Remove an uploaded custom mark (Control Panel.dc.html's Remove chip).
        LOGIN tier, same as the upload route above."""
        body = request.get_json(silent=True) or {}
        mark_id = str(body.get("id") or "")
        if not remove_custom_mark(out_dir, mark_id):
            return jsonify({"error": "unknown custom mark"}), 400
        cfg = load_branding(out_dir)
        return jsonify({"mark": cfg["mark"], "marks": list_marks(out_dir)})

    @app.route("/api/branding/banners/earned")
    def api_branding_banners_earned():
        """The earned-banner picks BannerEditor's locked/earned tile row renders.
        One entry today (great_library, gated on the-great-library); void_banner
        is deliberately NOT listed -- it rewards a future achievement (#57-60)
        and stays invisible until that lands. The png URL is the public role
        form and is itself seal-gated by the /branding/ route, so a locked
        banner's art can't be previewed by fetching the URL directly. LOGIN
        tier, mirroring /api/branding/mark/custom."""
        return jsonify({"banners": [{
            "id": "great_library",
            "label": "The Great Library",
            "earned": _mark_earned(out_dir, db_path, "the-great-library"),
            "png": "/branding/earned_banners/great_library.png",
        }]})

    @app.route("/api/branding/banner/earned", methods=["POST"])
    def api_branding_banner_earned():
        """Apply an earned banner as the banner_main flat. Server gate is
        authoritative (the UI's locked tile is cosmetic): 403 until the
        achievement is really earned, same _mark_earned check the custom-mark
        upload runs. On success the SEALED earned_banners bytes go through the
        exact _render_banner_flat pipeline every other banner write uses
        (banner_main ratio 4:1 -> 1920x480), so the applied banner can't
        differ from an uploaded one in shape or size. LOGIN tier, mirroring
        /api/branding/mark/custom."""
        body = request.get_json(silent=True)
        body = body if isinstance(body, dict) else {}   # a JSON array/string/number -> 400, not 500
        if str(body.get("id") or "") != "great_library":
            return jsonify({"error": "unknown banner"}), 400
        if not _mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "banner locked"}), 403
        raw = _branding_bytes(_role_rel("earned_banners", "great_library.png"))
        if raw is None or not _render_banner_flat("banner_main", raw):
            return jsonify({"error": "banner art unavailable"}), 400
        return jsonify({"ok": True})

    @app.route("/api/branding/shortcut", methods=["POST"])
    def api_branding_shortcut():
        """Write/refresh the Desktop launcher shortcut with the chosen mark's
        .ico. A .pyw can't carry an icon; the .lnk can -- this IS the app icon.
        Machine-local action -> owner-only.

        Deliberately gated to _is_local_request(), NOT the broader
        _is_authorized_request(): this calls make_launcher_shortcut(), which
        shells out to PowerShell/WScript.Shell COM to write to the Desktop of the
        machine the SERVER process runs on -- see that function's own docstring
        ("caller must gate to localhost"). A logged-in LAN account is meant to
        unlock spend-the-owner's-credits generation features, not trigger
        PowerShell execution / filesystem writes on the host -- a materially
        different trust boundary, so this one route was NOT broadened along with
        the rest of the branding-writes group during the LAN-auth conversion
        pass (unlike GET/POST /api/branding just above, which only writes
        out_dir/branding.json -- ordinary app data, correctly broadened)."""
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
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 400
        return jsonify({"ok": True, "lnk": lnk})

    @app.route("/api/suggest-prompt")
    def api_suggest_prompt():
        """Image-to-prompt for the gallery's 'Suggest prompt' button: PixAI's tag list +
        NL description for a media_id. Read-only and free; login required. ?media_id="""
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"suggestions": [], "error": "media_id required"}), 400
        try:
            core, session = _gen_session()
            return jsonify({"suggestions": core.suggest_prompt(session, mid)})
        except Exception as e:
            return jsonify({"suggestions": [], "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/tag-suggest")
    def api_tag_suggest():
        """Tag autocomplete for the drawer's prompt boxes (the site's Tag Suggestions
        dropdown). Read-only and free; login required. ?q=<prefix>."""
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"tags": []})
        try:
            core, session = _gen_session()
            return jsonify({"tags": core.tag_search_gql(session, q, first=8)})
        except Exception as e:
            return jsonify({"tags": [], "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        """Upload a local file from the picker -> PixAI media_id (the same free
        3-step S3 handshake as the CLI's --upload). Login required,
        spends nothing."""
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
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

    def _safe_extract_zip(zip_path, dest_dir):
        """Extract a zip into dest_dir, dropping any member whose resolved path would escape
        dest_dir (zip-slip). Localhost-only caller, but a crafted archive still shouldn't be
        able to write outside the temp dir."""
        import os as _os
        import zipfile as _zip
        import shutil as _sh
        root = _os.path.realpath(dest_dir)
        with _zip.ZipFile(zip_path) as z:
            for m in z.namelist():
                if m.endswith("/"):
                    continue
                target = _os.path.realpath(_os.path.join(dest_dir, m))
                if target != root and not target.startswith(root + _os.sep):
                    continue                          # zip-slip -> skip
                _os.makedirs(_os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as dst:
                    _sh.copyfileobj(src, dst)

    @app.route("/api/import-local", methods=["POST"])
    def api_import_local():
        """Import local files into the catalog as source='local' -- the web equivalent of the
        CLI's --import-local. Accepts multipart `files` (images/videos); a `.zip` is expanded.

        Localhost-only: it copies files into the backup (`imported/`) and shells out to build
        thumbnails on the machine the SERVER process runs on -- a host-filesystem write, the
        same trust tier as the destructive Panel jobs and /api/branding/shortcut, NOT the
        broader logged-in-LAN auth. A LAN device must never be able to write files onto the
        owner's machine. Nothing is uploaded to PixAI (that's /api/upload).

        Saves the uploads to a temp dir (expanding any zip), then reuses
        core.run_import_local (copy -> imported/ + catalog source='local' + thumbnail, path
        dedup), tags an optional collection, and returns counts. Synchronous for now."""
        if not _is_local_request():
            return jsonify({"error": "this imports files onto the server's machine; localhost-only"}), 403
        import os as _os
        import tempfile
        import shutil
        from types import SimpleNamespace
        import moonglade_backup as core
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "no files"}), 400
        collection = (request.form.get("collection") or "").strip()
        tmp = tempfile.mkdtemp(prefix="mg_import_")
        try:
            saved = 0
            for i, f in enumerate(files[:1000]):          # hard cap on one request
                base = _os.path.basename(f.filename or "")
                if not base:
                    continue
                # Own subdir per upload so two files sharing a basename don't collide in the
                # temp dir; run_import_local then copies each into imported/ by basename, so the
                # final names stay clean (matching the CLI's --import-local behavior).
                sub = _os.path.join(tmp, str(i))
                _os.makedirs(sub, exist_ok=True)
                dest = _os.path.join(sub, base)
                f.save(dest)
                if base.lower().endswith(".zip"):
                    try:
                        _safe_extract_zip(dest, sub)
                    finally:
                        try: _os.unlink(dest)
                        except OSError: pass
                saved += 1
            if not saved:
                return jsonify({"error": "no usable files"}), 400
            res = core.run_import_local(SimpleNamespace(out=str(out_dir), import_local=tmp))
            mids = res.get("media_ids") or []
            if collection and mids:
                add_to_collection(db_path, mids, collection)
            return jsonify({"ok": True, "imported": res["imported"], "skipped": res["skipped"],
                            "collection": collection or None})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _gen_args_from_payload(p):
        """Turn the Generate drawer's JSON into the SAME argparse-like namespace the CLI
        feeds to core._gen_parameters -- so web + CLI build identical params (one source
        of truth). Clamped to safe ranges, and every clamp that actually fired is listed on
        the returned namespace as `.clamped` = [{field, asked, used}] so the route can tell
        the caller its request was rewritten instead of charging for the difference."""
        from types import SimpleNamespace
        import moonglade_backup as core          # module-local, like every other use here
        p = p or {}
        def num(k, d, cast=int):
            try:
                return cast(p.get(k, d))
            except (TypeError, ValueError):
                return d
        # "Clamped to safe ranges" was, until this existed, true of `count` alone: width,
        # height, steps and cfg went through num() with no ceiling and straight into a real
        # paid submit, because core._gen_parameters only FLOORS width/height to 64 (via
        # _dim) and caps nothing at all. /api/generate is LOGIN-tier on purpose -- any
        # signed-in LAN device may spend -- so the drawer's own HTML min/max attributes are
        # the only bound a well-behaved client honours and a hand-rolled POST honours none:
        # {"width": 999999999, "steps": 999999} reached PixAI, priced at whatever that
        # produces. Clamp here, where the docstring promises it.
        #
        # The ceilings are read off the drawer's OWN controls, not invented:
        #   width/height  64..4096  -- #gen-cw / #gen-ch (min=64 max=4096 step=8), and the
        #                              drawer's d8() already clamps to exactly that before
        #                              it POSTs, so this is the same number twice
        #   steps         1..150    -- #gen-steps, and gateField()'s defMin/defMax
        #   cfg           1..30     -- #gen-cfg, and gateField()'s defMin/defMax
        # Same idiom core._gen_parameters uses for the Hires knobs ("bounds read off the
        # live dialog's own controls: strength 0.01-0.99, steps 1-50").
        #
        # These are NOT provably the widest the UI can emit, and an earlier draft of this
        # comment claimed they were ("a model publishing tighter `restrictions` narrows the
        # browser field further"). gateField() REPLACES the field's min/max with whatever
        # `restrictions` carries rather than clipping them, and `restrictions` is live PixAI
        # data -- so a model publishing samplingSteps.max = 200 would widen the drawer's own
        # control and the drawer would legitimately POST 200.
        #
        # Which is exactly why a clamp that FIRES is recorded instead of applied in silence.
        # Clamping is substitution on a paid path: the caller asked for one generation and
        # is charged for a different one, and doing that without a word is a worse failure
        # than the absurd value the clamp exists to refuse -- the money is gone either way,
        # and only the version that says so tells you what it bought. `adjusted` is that
        # receipt; /api/generate hands it back in the response (see api_generate). No
        # price/charge split comes of it either way: /api/price builds its params through
        # this same function, so the badge already quotes the clamped request.
        adjusted = []

        def clamp(field, v, lo, hi):
            c = max(lo, min(hi, v))
            if c != v:
                adjusted.append({"field": field, "asked": v, "used": c})
            return c
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
            width=clamp("width", num("width", 512), 64, 4096),
            height=clamp("height", num("height", 512), 64, 4096),
            steps=clamp("steps", num("steps", 25), 1, 150),
            cfg=clamp("cfg", num("cfg", 7, float), 1.0, 30.0),
            count=clamp("count", num("count", 1), 1, 4),
            # Ticked = High (1000, costs extra). Unticked = Turbo (500, free but
            # members-only); core's submit downgrades that to Low on its own if PixAI
            # says this account isn't entitled, so an expired membership no longer
            # breaks every generate/edit/upscale at once.
            priority=(core.PRIORITY_HIGH if hp else core.PRIORITY_TURBO),
            mode=(p.get("mode") or "auto"),
            seed=(int(seed_raw) if seed_raw.lstrip("-").isdigit() else None),
            lora=loras,
            # .lower() matters: a JSON `false` arrives as Python False, and
            # str(False) is "False" -- which did NOT match the lowercase tuple, so
            # every explicitly-disabled prompt helper was submitted as ENABLED.
            # Found 2026-07-29 reviewing the pilot's port; it bit the classic
            # drawer's unchecked box identically.
            prompt_helper=(str(p.get("prompt_helper", "1")).lower()
                           not in ("0", "false", "off", "none")),
            ref_media_id=str(p.get("ref_media_id") or "").strip(),
            ref_strength=num("ref_strength", 0.55, float),
            # Upscale + boosters. num() returns its default for a missing/blank value, so
            # None here means "the drawer's Upscale control is Off" and the builder omits
            # every one of these keys -- an absent control must not change the submit.
            enlarge=num("enlarge", None, float),
            enlarge_model=str(p.get("enlarge_model") or "").strip(),
            upscale=num("upscale", None, float),
            upscale_denoising_strength=num("upscale_denoise", None, float),
            upscale_denoising_steps=num("upscale_denoise_steps", None, int),
            face_fix=(p.get("face_fix") in (True, "1", "true", "on")),
            quality_tag=str(p.get("quality_tag") or "").strip(),
            kaisuuken_id="", no_card=bool(p.get("no_card")),
            # core._gen_parameters reads named attributes only, so carrying the receipt on
            # the namespace costs the submit shape nothing and keeps it beside the values it
            # describes -- a caller cannot pick up the args and lose the record of what was
            # changed to make them.
            clamped=adjusted)

    _presets_lock = threading.Lock()

    # Toolbox presets are PER-ACCOUNT, one file each under out_dir/toolbox_presets/ --
    # same shape as _view_presets_path/_snips_path/_loom_kv_path. They shipped
    # install-wide; Moonglade is explicitly not single-user (the repo is public and has
    # real external users), so on any install with more than one account, install-wide
    # meant every account could see, and overwrite, every other account's imported
    # presets. The legacy shared file stays a READ-ONLY fallback for an account with no
    # file of its own yet -- same no-migration-flag contract as _load_view_presets.
    def _toolbox_dir():
        d = out_dir / "toolbox_presets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _presets_path(user):
        # _account_key (B14 residual): same case-safe key as every other per-account
        # store -- toolbox_presets copied _view_presets_path's exact quote(username)
        # pattern (and its collision) when it was split, most recently of the four.
        return _toolbox_dir() / (_account_key(user) + ".json")

    def _legacy_presets_path():
        return out_dir / "toolbox_presets.json"

    def _read_presets_data(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):
            pass
        return {}

    def _load_presets(user):
        own = _presets_path(user)
        if own.exists():
            return _read_presets_data(own)
        return _read_presets_data(_legacy_presets_path())

    def _edit_params_from_payload(core, p, user, session=None):
        """Build the instruct-edit `chat` params from the Edit tab's JSON. Source is a
        catalog media_id (the image being edited). A `preset` name swaps in a locally
        banked Toolbox preset (canned prompt + sceneId + its modelId), looked up from
        `user`'s own per-account presets. Returns None if no source.

        `session` is REQUIRED for a real submit and deliberately omitted for pricing.
        With it, every source id is run through _input_media_id -- a catalog id is a
        generation OUTPUT and PixAI refuses it as an input. Without it, ids are left
        alone: /api/price only needs the SHAPE to compute a cost, and uploading on every
        cost check would upload the same file repeatedly while the user types."""
        p = p or {}
        src = str(p.get("source") or "").strip()
        if not src:
            return None
        instruction = (p.get("instruction") or "").strip()
        scene_id, model_id = "", ""
        preset_name = str(p.get("preset") or "").strip()
        if preset_name:
            pre = _load_presets(user).get(preset_name)
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
        if session is not None:            # real submit -- see the docstring
            media = [_input_media_id(core, session, m) for m in media]
        return core.build_chat_edit_parameters(instruction, media, **kwargs)

    @app.route("/api/presets", methods=["GET", "POST"])
    def api_presets():
        """Toolbox presets, stored per-account under out_dir/toolbox_presets/ (preset
        prompts are PixAI-authored content, so they live as the owner's own captured
        task data, never in the repo). GET lists {name: {label, scene_id}} (no prompt
        bodies). POST {task_id, label?} imports one from a task the owner ran on the
        site: fetches the task, extracts chat.prompts + sceneId + modelId, saves it.
        Login required; uses the owner's key on import.

        The account comes from the SESSION, never the request body -- same contract as
        /api/view-presets and /api/snippets: a client that could name its own key could
        read and overwrite anyone's presets."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "authentication required"}), 401
        with _presets_lock:
            presets = _load_presets(user)
            if request.method == "GET":
                return jsonify({"presets": {
                    k: {"label": v.get("label") or k, "scene_id": v.get("scene_id", "")}
                    for k, v in presets.items()}})
            body = request.get_json(silent=True) or {}
            tid = str(body.get("task_id") or "").strip()
            if not tid:
                return jsonify({"error": "task_id required"}), 400
            try:
                core, gsession = _gen_session()
                task = core.task_detail_gql(gsession, tid) or {}
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
                dest = _presets_path(user)
                tmp = dest.with_suffix(".tmp")
                tmp.write_text(json.dumps(presets, indent=1), encoding="utf-8")
                os.replace(tmp, dest)   # atomic: a torn write can't eat the set
                return jsonify({"imported": name,
                                "label": presets[name]["label"]})
            except Exception as e:
                return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    _view_presets_lock = threading.Lock()

    # Saved views are PER-ACCOUNT, one file each under out_dir/view_presets/.
    #
    # They shipped install-wide (a single out_dir/view_presets.json) by analogy with
    # /api/skin, which is the right analogy for a THEME and the wrong one here: a skin is
    # a cosmetic preference, whereas a saved view is a stored search -- names and query
    # strings that say what someone looks for in their own library. Moonglade is
    # explicitly not single-user (the repo is public and has real external users), so on
    # any install with more than one account, install-wide means every account reads, and
    # can overwrite or delete, every other account's saved searches.
    #
    # For the case this feature was built for -- one owner, desktop and tablet, same
    # account against one server -- per-account behaves identically. Nothing is lost.
    def _view_presets_dir():
        d = out_dir / "view_presets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _view_presets_path(user):
        # _account_key -- a case-safe key (B14 residual): the original quote(username,
        # safe="") here was case-PRESERVING, so "Nel" and "nel" quoted to two different
        # strings that named the SAME file on NTFS (case-insensitive-but-preserving),
        # even though account identity itself is case-sensitive. See _account_key's
        # own docstring for the full story; every per-account store shares this one
        # helper now instead of each re-deriving its own quote()-based key.
        return _view_presets_dir() / (_account_key(user) + ".json")

    def _legacy_view_presets_path():
        return out_dir / "view_presets.json"

    def _read_presets_file(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): v for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError):
            pass
        return {}

    def _load_view_presets(user):
        """This account's saved views, falling back to the legacy shared file.

        The fallback is deliberately READ-ONLY and needs no migration flag. An account
        with no file of its own yet sees whatever the old shared file held -- exactly what
        it saw before this change, so nothing disappears -- and the moment it saves, it
        gets its own file and diverges. No "who owns the legacy set" question, and no
        first-loader-claims-it race, which is the trap a migration flag would have walked
        into. Once every account has saved once, out_dir/view_presets.json is inert and
        can be deleted by hand."""
        own = _view_presets_path(user)
        if own.exists():
            return _read_presets_file(own)
        return _read_presets_file(_legacy_view_presets_path())

    def _ok_view_query(q):
        # Presets navigate via location.href = '/' + query on load. Requiring the
        # leading '?' (exactly what savePreset stores: location.search || '?') keeps
        # every stored value a same-page filter string -- a bare '//host' would resolve
        # protocol-relative and turn a saved view into an off-site redirect.
        return isinstance(q, str) and q.startswith("?") and len(q) <= 4096

    @app.route("/api/view-presets", methods=["GET", "POST"])
    def api_view_presets():
        """Saved-view presets (the gallery's "Saved views…" dropdown): {name: query
        string}, stored server-side under out_dir/view_presets/ so a view saved at the
        desktop exists on the tablet. Login tier (no spend, nothing destructive), and
        scoped to ONE ACCOUNT -- see _view_presets_dir() for why a saved search is not
        the same kind of thing as the install-wide skin choice. They lived in
        localStorage before this, one private set per browser; the client pushes a legacy
        set up through POST {merge} once, existing names winning ties. POST {name, query}
        saves one; POST {delete: name} removes one, wired to a "Delete" button next to the
        saved-view select (see deletePreset() in the page script).

        The account comes from the SESSION and is never accepted from the request body:
        a client that could name its own key could read and overwrite anyone's set, which
        would give back the exact cross-account exposure the per-account split removes."""
        user = str(session.get("user") or "")
        if not user:
            # Unreachable through the front door (/api/ is gated), so this is belt and
            # braces -- but the per-account contract must fail closed rather than fall
            # back to a shared or empty-named file if that ever stops being true.
            return jsonify({"error": "authentication required"}), 401
        with _view_presets_lock:
            presets = _load_view_presets(user)
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                if isinstance(body.get("merge"), dict):
                    for k, v in body["merge"].items():
                        k = str(k).strip()
                        if k and k not in presets and _ok_view_query(v):
                            presets[k] = v
                elif body.get("delete") is not None:
                    presets.pop(str(body.get("delete")), None)
                else:
                    name = str(body.get("name") or "").strip()
                    if not name:
                        return jsonify({"error": "name required"}), 400
                    if not _ok_view_query(body.get("query")):
                        return jsonify({"error": "query must be a '?…' filter string"}), 400
                    presets[name] = body["query"]
                dest = _view_presets_path(user)
                tmp = dest.with_suffix(".tmp")
                tmp.write_text(json.dumps(presets, indent=1), encoding="utf-8")
                os.replace(tmp, dest)   # atomic: a torn write can't eat the set
            return jsonify({"presets": presets})

    def _params_and_nocard(core, p, user, is_member=None):
        """Route a drawer payload to generate, edit, fix, or video params. Returns (params,
        no_card, note). note is set (params None) when something's missing. `user` is
        only consulted on the edit path (a preset lookup is per-account)."""
        p = p or {}
        if p.get("mode") == "edit":
            params = _edit_params_from_payload(core, p, user)
            return (params, bool(p.get("no_card")),
                    None if params else "pick an image to edit")
        if p.get("mode") == "fix":
            # A hand/face Fix is submitted over POST /v2/task/fixer, whose {mediaId, boxes}
            # body /v2/task-price cannot read -- but the taskKind=chat task PixAI builds from
            # it IS priceable, so build_fixer_price_parameters synthesizes that chat.fixer
            # shape (see its docstring for the measurement).
            src = str(p.get("source") or "").strip()
            if not src:
                return None, True, "pick an image to fix"
            try:
                params = core.build_fixer_price_parameters(src, p.get("boxes") or [])
            except core.PixAIError:
                return None, True, "drag a box over a hand or face"
            # no_card is forced True here and is NOT read off the payload: /v2/task/fixer
            # takes only mediaId + boxes, with no kaisuukenId field anywhere on it, so a free
            # card can never be spent on a Fix however well /v2/kaisuuken/check matches the
            # synthesized params. Letting the card check run would paint the badge emerald
            # "FREE -- a card covers this" over an action about to charge full credits.
            return params, True, None
        if p.get("mode") in ("I2V", "FLF", "R2V"):
            imgs = [str(i) for i in (p.get("images") or []) if str(i).strip()]
            vids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip()]
            auds = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip()]
            # I2V/FLF are image-anchored (source frame / start+end frame); R2V accepts
            # ANY reference kind alone (e.g. a video-only Multi-ref) -- gating all three
            # modes on `imgs` alone silently mispriced a video/audio-only R2V request as
            # "pick a source image", found 2026-07-18 while wiring the ref-slot expansion.
            has_ref = imgs or (p["mode"] == "R2V" and (vids or auds))
            if not has_ref:
                return None, bool(p.get("no_card")), "pick a source image"
            try:
                params = core.build_shot_video_params(
                    p["mode"], (p.get("prompt") or "").strip(), image_ids=imgs,
                    video_ids=vids, audio_ids=auds,
                    duration=p.get("duration") or 5,
                    generate_audio=bool(p.get("generate_audio") or p.get("audio")),
                    model=(p.get("video_model") or ""),
                    camera_movement=(p.get("camera_movement") or ""),
                    quality=(p.get("quality") or "professional"),
                    audio_language=(p.get("audio_language") or "english"),
                    negative=(p.get("negative") or "").strip(),
                    is_private=bool(p.get("is_private")),
                    use_prompt_helper=bool(p.get("prompt_helper")))
            except core.PixAIError as e:
                return None, bool(p.get("no_card")), _redact_host_paths(str(e))[:140]
            return params, bool(p.get("no_card")), None
        if p.get("mode") == "enhance":
            # [MAJOR] An enhance/panelplugin task is priced by its workflow id, which is
            # deliberately NOT in core._PRICE_SCALARS: pricing the workflow-less shape that would
            # survive the allowlist returns a confident WRONG number. So we do NOT call price_task
            # for enhance -- we return (None, ...) here, which api_price renders as cost:None
            # ("couldn't verify the cost"). Adding the workflow-id scalar to the allowlist needs a
            # live measurement first (a separately authorized step); until then, no number is the
            # honest answer. Returning here also keeps an enhance payload from ever reaching the
            # pricing endpoint (test_web_pick.py's enhance-price guard).
            return None, bool(p.get("no_card")), "couldn't verify the cost of an AI preset yet"
        args = _gen_args_from_payload(p)
        if not args.model:
            return None, args.no_card, "pick a model"
        # Same entitlement the submit applies, so the badge cannot quote a price for a
        # members-only option that will be stripped before it is sent.
        args.is_member = is_member
        try:
            return core._gen_parameters(args), args.no_card, None
        except core.PixAIError as e:
            # Same shape as the I2V branch above: a builder refusal (asking for both
            # upscale methods at once) becomes the badge's own note, not a 500.
            return None, args.no_card, _redact_host_paths(str(e))[:140]

    def _log_gen_failure(where, exc, params=None):
        """Record a failed spend attempt in the server log. Returns the redacted message so a
        caller can both log and return it in one line.

        This did not exist, and its absence is what made a 2026-07-26 video decline
        undiagnosable: the route handed the raw error to the browser, the browser's
        friendlyGenErr() replaced it with a guess ("PixAI's content filter blocked this"), and
        the actual text was written down nowhere. There was no way to tell a content block from
        a rejected parameter after the fact -- and those want opposite fixes, so the guess sent
        the owner off to rewrite a prompt that was fine.

        Logs the PARAMS too, because the shape is the diagnosis for this class of failure -- which
        model, which quality mode, what duration. No credential is involved: the API key travels
        in the session headers, never in `parameters`. Prompts do appear, which is correct -- a
        moderation decline is unreadable without the prompt -- and this log is local to the
        owner's own machine, the same file that already records every request.

        Never raises: a diagnostic that can break the error path it reports on is worse than
        no diagnostic."""
        msg = _redact_host_paths(str(exc))
        try:
            import json as _json
            import logging as _logging
            shape = ""
            if params:
                # A miswired caller that hands us a bare str/id instead of a params dict must
                # still LOG, not silently skip: dict("<a-string>") raises ValueError, which the
                # outer `except: pass` below would swallow -- taking the logging.error() with it,
                # since it sits after this block in the same try. That is exactly how the
                # /api/scene handler was blinded (adversarial review 2026-08-18). Coerce first so
                # the diagnostic this function exists to guarantee can never be killed by its arg.
                if not isinstance(params, dict):
                    params = {"value": params}
                # Truncate the PROMPT separately, then serialise. A flat [:700] on the whole
                # dict let a long prompt consume the entire budget and cut off isPrivate,
                # modelId, duration and mode -- the structural fields that ARE the diagnosis.
                # Hit immediately: the first real failure this logged (2026-07-26) lost exactly
                # those, and the shape had to be reconstructed from PixAI's site instead.
                slim = dict(params)
                for _blk in ("i2vPro", "referenceVideo"):
                    if isinstance(slim.get(_blk), dict):
                        inner = dict(slim[_blk])
                        for _k in ("prompts", "negativePrompts"):
                            if isinstance(inner.get(_k), str) and len(inner[_k]) > 120:
                                inner[_k] = inner[_k][:120] + "...<truncated {} chars>".format(
                                    len(slim[_blk][_k]) - 120)
                        slim[_blk] = inner
                for _k in ("prompts", "negativePrompts"):
                    if isinstance(slim.get(_k), str) and len(slim[_k]) > 120:
                        slim[_k] = slim[_k][:120] + "...<truncated>"
                shape = " params=" + _json.dumps(slim, ensure_ascii=False, default=str)[:900]
            _logging.getLogger(__name__).error(
                "%s failed: %s: %s%s", where, type(exc).__name__, msg[:400], shape)
        except Exception:
            pass
        return msg

    @app.route("/api/price", methods=["POST"])
    def api_price():
        """Live cost + free-card check for the drawer's current settings (generate OR
        edit). Read-only (no spend). Login required (any session, local or LAN)."""
        try:
            user = str(session.get("user") or "")
            # NOT `core, session = _gen_session()` -- session is assigned that way further
            # down in this same function, which (Python whole-function scoping) makes the
            # bare name `session` local for the ENTIRE function, so the read above would
            # raise UnboundLocalError instead of reading Flask's session. gsession names
            # the PixAI API session distinctly, the same fix already applied in api_presets.
            core, gsession = _gen_session()
            body = request.get_json(silent=True) or {}
            # Resolve a bare base model_id -> its current version, exactly as /api/generate
            # does, so a caller that knows only the base model still gets a real cost +
            # free-card check instead of a "pick a model" note. The Loom's Image tab is
            # precisely that caller: its model picker emits {model_id, title} with no
            # version_id, and its price check (confirmSpend) would otherwise always fall to
            # "couldn't verify the cost". The web drawer already sends version_id, so this
            # only fires for the model_id-only path.
            if (not str(body.get("version_id") or "").strip()
                    and str(body.get("model_id") or "").strip()
                    and not body.get("mode")):
                _vid = (core.resolve_version_meta(gsession, str(body["model_id"]).strip()) or {}).get("version_id") or ""
                if _vid:
                    body = {**body, "version_id": _vid}
            params, no_card, note = _params_and_nocard(
                core, body, user, _account_is_member(core, gsession))
            if params is None:
                return jsonify({"cost": None, "free": False, "note": note})
            cost = core.price_task(gsession, params)
            best = None if no_card else core.match_kaisuuken(gsession, params, enrich=True)
            # `free` is core.card_covers(best), NOT bool(best): a multi-ticket video can MATCH
            # a card the account holds too few tickets of (issue #15), and that case is paid
            # at the full price -- the site attaches nothing. One predicate shared with the
            # CLI preview and _apply_kaisuuken so this badge can never say FREE while the
            # submit charges. `cards` is the HELD count (kept under its old name for the
            # badge's "(N left)"); the job's ticket cost is `cards_needed`, and `card_short`
            # is the honest flag the badge renders as "not enough -- costs the full price".
            covered = core.card_covers(best)
            return jsonify({"cost": cost, "free": covered,
                            "cards": (best or {}).get("total"),
                            "cards_held": (best or {}).get("total"),
                            "cards_needed": (best or {}).get("consumeAmount"),
                            "card_short": bool(best) and not covered,
                            "card_name": (best or {}).get("name"),
                            # The Loom's batch tally keys its per-template ticket pool on
                            # this (falls back to card_name when absent) -- see
                            # loom-core.js tallyPricesDetailed.
                            "card_template": (best or {}).get("templateId"),
                            "card_expires": (best or {}).get("expiresAt")})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "cost": None}), 200

    @app.route("/api/generate", methods=["POST"])
    def api_generate():
        """Submit a generation from the drawer, wait, and catalog it into THIS gallery's
        backup. Login required -- any session, local or LAN, deliberately: spending from a
        signed-in tablet is the point of the login. A matching free card is
        auto-applied unless no_card is set. Returns {task_id, media_ids, paid_credit}."""
        try:
            core, session = _gen_session()
            body = request.get_json(silent=True) or {}
            args = _gen_args_from_payload(body)
            # Authoritative model resolution: if the drawer sent the base model_id, resolve
            # its REAL version list server-side and never trust the client's version_id blind.
            # picker-parity-round2 (2026-07-24): the client's version_id is now honored IF it
            # names one of model_id's own real versions (the version picker lets the owner
            # choose a specific release, not just the latest) -- otherwise (absent, stale from
            # a fast model switch, or belonging to a DIFFERENT model_id entirely) this falls
            # back to the newest version, exactly like before this existed. Either way the
            # client's raw version_id is NEVER submitted un-validated, which is what originally
            # stopped gens landing as "Unknown model" + missing the feed. Falls back to the
            # client version_id as-is only when no model_id was sent at all (back-compat).
            _mid = str(body.get("model_id") or "").strip()
            if _mid:
                _client_vid = str(body.get("version_id") or "").strip()
                _versions = core.list_model_versions(session, _mid)
                _chosen = next((v for v in _versions if v.get("version_id") == _client_vid),
                               None) if _client_vid else None
                if _chosen:
                    args.model = _chosen["version_id"]
                elif _versions:
                    args.model = _versions[0]["version_id"]
            if not args.model:
                return jsonify({"error": "pick a model first"}), 400
            if not args.prompt:
                return jsonify({"error": "enter a prompt"}), 400
            # Members-only options are dropped for an account PixAI reports as non-member.
            # Set on the args (not inside the builder) so the CLI keeps its own path and the
            # price call below can set the identical flag -- the badge must quote the shape
            # that will actually submit.
            _ent = _entitlements(core, session)
            args.is_member = _ent["is_member"]
            # The per-generation LoRA cap was CLIENT-ONLY until 2026-07-28: both the gallery
            # drawer and the Loom disable their own submit button over the cap, and nothing
            # checked it here -- so any path that is not one of those two buttons (a stale
            # page, the Loom before /api/account resolves, a hand-rolled POST) reached PixAI
            # and came back LORA_NUM_EXCEEDED / 40300027. Reproduced by the owner with six
            # LoRAs against a cap of three. Refuse rather than silently trim: dropping a LoRA
            # changes the picture he asked for, and a refusal costs nothing because no task
            # is created either way. Fails OPEN on an unknown cap.
            _cap = _ent["lora_cap"]
            if _cap is not None and len(getattr(args, "lora", None) or []) > _cap:
                return jsonify({"error": "Your account allows {} LoRA{} per generation — "
                                         "remove {} to continue.".format(
                                             _cap, "" if _cap == 1 else "s",
                                             len(args.lora) - _cap)}), 400
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
            out = {"task_id": task_id}
            if getattr(args, "clamped", None):
                # A clamp fired: this submit is NOT the one that was asked for, and the
                # caller has just been charged for it. Say so in the response rather than
                # letting the substitution pass unremarked -- the whole hazard M20's clamp
                # introduced is that it can quietly bill a different generation than the
                # one configured. Both kinds of caller can land here: a hand-rolled POST
                # (the finding's own threat model) and the drawer itself, whose steps/cfg
                # controls adopt a model's published `restrictions` verbatim and so can
                # legitimately offer a number this clamp then rewrites.
                out["adjusted"] = args.clamped
            return jsonify(out)
        except Exception as e:
            return jsonify({"error": _log_gen_failure(
                "/api/generate", e, locals().get("params"))[:300]}), 200

    @app.route("/api/edit", methods=["POST"])
    def api_edit():
        """Instruct-edit an existing gallery image ('make it night'). Login required;
        auto-applies an Edit-Pro card unless no_card. Catalogs the result into this
        backup, same as /api/generate. Returns {task_id, media_ids, paid_credit}."""
        try:
            from types import SimpleNamespace
            user = str(session.get("user") or "")
            # gsession, not `core, session = _gen_session()` -- see api_price's identical
            # comment: session is Flask's, reassigning it here would make every reference
            # to the bare name `session` in this function a local (UnboundLocalError on
            # the read above), not a read of Flask's session.
            core, gsession = _gen_session()
            p = request.get_json(silent=True) or {}
            params = _edit_params_from_payload(core, p, user, gsession)
            if params is None:
                return jsonify({"error": "pick an image to edit (and a valid preset if set)"}), 400
            if not (p.get("preset") or "").strip() and not (p.get("instruction") or "").strip():
                return jsonify({"error": "describe the edit"}), 400
            core._apply_kaisuuken(gsession, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(gsession, params)
            telem_bump("edits", out_dir=out_dir)          # The Restoration Wing
            telem_set_add("tools", "edit", out_dir=out_dir)
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": _log_gen_failure(
                "/api/edit", e, locals().get("params"))[:300]}), 200

    # Process cache for the Bridge preset prices: they are flat per workflow and account-
    # stable (source- AND priority-independent, verified live 2026-08-18), so a slab mount
    # need not be a dozen live REST calls. Only a REAL (mirror-reached) result is cached; a
    # null-priced result is not, so it retries once the mirror is back. TTL in seconds.
    _enh_price_cache = {"at": 0.0, "presets": None}
    _ENH_PRICE_TTL = 3600.0

    @app.route("/api/enhance/presets")
    def api_enhance_presets():
        """The six Bridge Enhance presets + LIVE per-preset cost (price + free-card), so the
        drawer's cost chips are honest rather than baked (the same 'fetch, don't bake' rule Fix
        follows). Cost comes from PixAI's own /v2/task-price + /v2/kaisuuken/check through the
        MIRROR session -- the identity that actually runs an enhance -- priced against a
        PLACEHOLDER media id (task-price prices the request SHAPE, not a specific owned image;
        verified 2026-08-18). No free card covers any panelplugin task on this account, so
        free_card comes back False across the board unless PixAI ever adds such a card, in which
        case this reports it truthfully. Fails soft: price=null when the mirror can't be reached
        (the slab only renders armed, but a price probe must never 500). LOGIN tier; read-only,
        spends nothing."""
        import moonglade_backup as core
        now = time.time()
        cached = _enh_price_cache["presets"]
        if cached is not None and (now - _enh_price_cache["at"]) < _ENH_PRICE_TTL:
            return jsonify({"presets": cached})
        s = core.make_mirror_session()          # stored session (no bootstrap) -- as the gate uses

        def _row(pr):
            row = {"key": pr.get("key"), "label": pr.get("label"),
                   "workflow_id": pr.get("workflow_id", ""),
                   "workflow_name": pr.get("workflow_name", ""),
                   "has_control": bool(pr.get("has_control")), "price": None, "free_card": False}
            if s is not None:
                try:
                    params = core.build_panelplugin_parameters(
                        "1", row["workflow_id"], workflow_name=row["workflow_name"])
                    row["price"] = core.price_task(s, params)
                    row["free_card"] = bool(core.match_kaisuuken(s, params))
                except Exception:
                    row["price"] = None
            return row

        # Price the six presets CONCURRENTLY. Each is two sequential PixAI round-trips (task-price
        # + kaisuuken-check), so done serially they stacked to ~5s and blocked the drawer's Enhance
        # slab from rendering at all (owner-reported). A small thread pool collapses that to about
        # one round-trip's latency; the result is cached (TTL above), so every later open -- and
        # every other user -- is instant. requests.Session is fine under concurrent GET/POST here
        # (it mutates no shared session state), and this is one small burst per cache-miss.
        if s is not None:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(core.BRIDGE_ENHANCE_PRESETS)) as ex:
                out = list(ex.map(_row, core.BRIDGE_ENHANCE_PRESETS))
        else:
            out = [_row(pr) for pr in core.BRIDGE_ENHANCE_PRESETS]
        if s is not None and all(r["price"] is not None for r in out):   # cache only a fully-real result
            _enh_price_cache["presets"] = out
            _enh_price_cache["at"] = now
        return jsonify({"presets": out})

    @app.route("/api/enhance", methods=["POST"])
    def api_enhance():
        """One-click AI preset (PixAI panelplugin workflow) on the Edit tab's source image --
        the mirror-gated Bridge tier (drift §44 / SCOPE §3). Accepts `workflow_id` OR
        `workflow_name`. Login required. Returns {task_id}; telemetry is DEFERRED to terminal
        success (see /api/task-status), never fired at submit-acceptance.

        A panelplugin task submitted on the API KEY is accepted, queued, CHARGED, then reaped
        unstarted at ~60 min -- so this route REFUSES unless the PixAI mirror is armed and has a
        live browser session, the only credential that dispatches one. The gate is the FIRST
        thing here, before any input upload / card check / builder / submit, so a mirror-off
        request creates nothing and spends nothing."""
        import moonglade_backup as core
        # [BLOCKER] Backend mirror gate, before _input_media_id / build_panelplugin_parameters /
        # _apply_kaisuuken / submit_generation. Do NOT lean on submit_generation's own
        # _session_for_create gate: its mirror-OFF branch intentionally falls back to the API-key
        # session (the paid-panelplugin-reaped-at-60-min bug this surface was deleted for, plus an
        # invariant-#7 cross-identity violation). mirror_enabled() catches OFF; make_mirror_session()
        # is None catches ON-but-no-usable-session. make_mirror_session is READ_ONLY-guarded and
        # never raises, so it is safe to call as a gate.
        if not core.mirror_enabled() or core.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to run AI presets — "
                                     "nothing was submitted, no credits spent"}), 409
        try:
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            src = _input_media_id(core, session, str(p.get("source") or "").strip())
            wid = str(p.get("workflow_id") or "").strip()
            wname = str(p.get("workflow_name") or "").strip()
            if not src:
                return jsonify({"error": "pick an image first"}), 400
            if not (wid or wname):
                return jsonify({"error": "pick an AI preset"}), 400
            # workflow_name wins inside the builder when both are set; a preset is pinned to
            # exactly one of the two (numeric id OR author/workflow name) in the caller.
            # Change Emotion carries a control: pass the picked expression, and ONLY for that
            # preset (an unknown input on the others would be a stray arg on a spend submit).
            # The picker sends the option KEY (filename stem); emotionlab's `prompt` arg wants the
            # danbooru TAG STRING, so translate key->tag here (unknown key falls back to itself).
            emotion_key = str(p.get("emotion") or "").strip()
            emotion_tag = core.ENHANCE_EMOTION_PROMPTS.get(emotion_key, emotion_key)
            extra = ({core.ENHANCE_EMOTION_ARG: emotion_tag}
                     if emotion_tag and wname == core.ENHANCE_EMOTION_WORKFLOW else None)
            params = core.build_panelplugin_parameters(src, wid, workflow_name=wname,
                                                       extra_inputs=extra)
            core._apply_kaisuuken(session, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(session, params)
            # [BLOCKER] Telemetry is DEFERRED, not fired here: submit_generation returns the id at
            # createGenerationTask ACCEPTANCE (before start/completion), and a panelplugin job can
            # be accepted then reaped. Record the identity ACTUALLY submitted (workflowName when a
            # name preset, else the numeric id) so telem_set_add -- which skips falsy values --
            # counts a workflowName preset too. The three producers fire from /api/task-status's
            # terminal-success branch via _fire_enhance_telemetry.
            with _enhance_pending_lock:
                _enhance_pending[str(task_id)] = wname or wid
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": _log_gen_failure(
                "/api/enhance", e, locals().get("params"))[:300]}), 200

    @app.route("/api/enhance/emotions")
    def api_enhance_emotions():
        """The staged Change-Emotion options: each emotion-role <key>.<img>
        (loose OR packed in the container), keyed by filename stem. The picker self-populates
        from whatever art is staged -- adding an emotion is dropping an image, no code change.
        Each option is flagged `membership` when PixAI gates it behind a paid tier.
        LOGIN tier; read-only, spends nothing. Disk/container scans are CODED;
        the emitted URLs keep the PUBLIC /branding/bridge/emotion/ form the
        front-end knows (the /branding/ route translates them back)."""
        import moonglade_backup as core
        exts = (".webp", ".png", ".jpg", ".jpeg")
        emo_prefix = (_role_rel("emotion") + "/").lower()
        found = {}
        box = _get_container()
        if box is not None:
            for rel in box.paths():
                low = rel.lower()
                if low.startswith(emo_prefix) and low.endswith(exts):
                    found.setdefault(Path(rel).stem,
                                     "/branding/bridge/emotion/" + Path(rel).name)
        edir = _role_dir("emotion")
        if edir.is_dir():
            for p in sorted(edir.iterdir()):
                if p.is_file() and p.suffix.lower() in exts:
                    found[p.stem] = "/branding/bridge/emotion/" + p.name   # loose overrides packed
        gated = getattr(core, "ENHANCE_EMOTION_MEMBERSHIP", frozenset())
        emotions = [{"key": k, "label": k.replace("-", " ").replace("_", " ").strip().title(),
                     "img": v, "membership": k in gated} for k, v in sorted(found.items())]
        return jsonify({"emotions": emotions})

    # The AI-Tools scene catalog (PixAI 'chat editing scenes'). Like the Enhance preset prices,
    # the list is fetched LIVE (not baked) so it self-updates the day PixAI adds/retires a scene,
    # and cached because it is account-stable. TTL in seconds.
    _scene_cache = {"at": 0.0, "scenes": None}
    _SCENE_TTL = 3600.0

    def _scene_label(key):
        """A display label for a preset/selector key -- PixAI's own `name` is the full workflow
        prompt (tarot) or an i18n key, so the human-readable form is the title-cased key
        ('the-sun' -> 'The Sun', 'facing-hug' -> 'Facing Hug')."""
        return (str(key or "").replace("-", " ").replace("_", " ").strip().title())

    def _scene_row(sc):
        """One raw chatEditingScene -> the control schema the drawer's scene generator renders:
        the preset chips, the selector dropdowns (language / aspect-ratio), whether it takes a
        custom text field, and how many source images it needs (1 for most, 2 for dual)."""
        presets = [{"key": p.get("key"), "label": _scene_label(p.get("key"))}
                   for p in (sc.get("presets") or []) if p.get("key")]
        selectors = [{"id": x.get("id"), "label": x.get("label") or _scene_label(x.get("id")),
                      "default": x.get("defaultKey"),
                      "options": [{"key": o.get("key"),
                                   "label": o.get("label") or _scene_label(o.get("key"))}
                                  for o in (x.get("options") or []) if o.get("key")]}
                     for x in (sc.get("selectors") or []) if x.get("id")]
        refs = sc.get("refImages") or {}
        ref_min = int(refs.get("minCount") or 1)
        ref_max = int(refs.get("maxCount") or max(ref_min, 1))
        return {"sceneId": sc.get("sceneId"), "modelId": sc.get("modelId"),
                "tier": (sc.get("permission") or {}).get("membershipTier"),
                "refMin": ref_min, "refMax": ref_max,
                "presets": presets, "selectors": selectors,
                "custom": bool(sc.get("custom"))}

    @app.route("/api/scenes")
    def api_scenes():
        """The AI-Tools scene catalog + each scene's control schema, so the nav modal browses
        and the gen drawer renders the right form. 'Fetch, don't bake': the list is pulled LIVE
        from listChatEditingScenes through the mirror session (the identity that runs a scene),
        cleaned to what the UI needs, and cached. Mirror-gated exactly like /api/enhance -- the
        AI-Tools tier only exists when the Bridge is armed. LOGIN tier; read-only, spends
        nothing."""
        import moonglade_backup as core
        if not core.mirror_enabled() or core.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to browse AI Tools"}), 409
        now = time.time()
        cached = _scene_cache["scenes"]
        if cached is not None and (now - _scene_cache["at"]) < _SCENE_TTL:
            return jsonify({"scenes": cached})
        try:
            raw = core.chat_editing_scenes(core.make_mirror_session())
        except Exception as e:
            return jsonify({"error": _log_gen_failure("/api/scenes", e, None)[:200]}), 200
        out = [_scene_row(sc) for sc in raw if sc.get("sceneId")]
        if out:
            _scene_cache["scenes"] = out
            _scene_cache["at"] = now
        return jsonify({"scenes": out})

    @app.route("/api/scene", methods=["POST"])
    def api_scene():
        """Generate one AI-Tools scene (createChatEditingSceneTask) on the picked source
        image(s). Mirror-gated FIRST, before any upload/build/submit: a scene task submitted on
        the API key is accepted, CHARGED, then reaped unstarted at ~60min (same reap as the
        panelplugin presets), so this refuses unless the mirror is armed with a live session and
        routes the submit through the JWT. Body: {scene_id, media_ids[], preset, custom?,
        selector_values?}. Login required; returns {task_id}."""
        import moonglade_backup as core
        if not core.mirror_enabled() or core.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to run AI Tools — "
                                     "nothing was submitted, no credits spent"}), 409
        try:
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            scene_id = str(p.get("scene_id") or p.get("sceneId") or "").strip()
            media = [_input_media_id(core, session, str(m).strip())
                     for m in (p.get("media_ids") or p.get("mediaIds") or []) if str(m).strip()]
            media = [m for m in media if m]
            if not scene_id:
                return jsonify({"error": "pick an AI tool"}), 400
            if not media:
                return jsonify({"error": "pick a source image"}), 400
            task_id = core.submit_scene(
                core.make_mirror_session(), scene_id, media,
                preset=str(p.get("preset") or "random"), custom=p.get("custom"),
                selector_values=(p.get("selector_values") or p.get("selectorValues") or []))
            return jsonify({"task_id": task_id})
        except Exception as e:
            # Pass the submit SHAPE as a dict (not the bare scene_id str) so _log_gen_failure
            # records the diagnosis -- the /api/enhance sibling passes locals().get("params")
            # the same way. submit_scene has no single builder-params dict at this site, so name
            # the shape explicitly (scene, preset, source count).
            return jsonify({"error": _log_gen_failure(
                "/api/scene", e, {"scene_id": locals().get("scene_id"),
                                  "preset": (p.get("preset") if "p" in locals() else None),
                                  "media_ct": len(locals().get("media") or [])})[:300]}), 200

    @app.route("/api/fix", methods=["POST"])
    def api_fix():
        """Submit a hand/face fixer task from the Edit-tab canvas. `boxes` are original-image
        pixel coords. Login required; returns {task_id} for the async poller."""
        try:
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            src = _input_media_id(core, session, str(p.get("source") or "").strip())
            boxes = p.get("boxes") or []
            if not src:
                return jsonify({"error": "pick an image first"}), 400
            if not boxes:
                return jsonify({"error": "draw a box over a hand or face"}), 400
            # The exact body submit_fixer POSTs to /v2/task/fixer, named here so the failure
            # log below has the REQUEST SHAPE to report, the same way /api/generate and
            # /api/edit hand it their `params`. Built from the route's own inputs rather
            # than re-running clean_fix_boxes(), so nothing on the error path can itself
            # raise; a box the cleaner would have dropped is still worth seeing, because
            # "which boxes did we actually ask about" is half the diagnosis.
            fix_params = {"mediaId": src, "boxes": boxes}
            task_id = core.submit_fixer(session, src, boxes)
            telem_set_add("tools", "fix", out_dir=out_dir)   # Full Toolbox
            return jsonify({"task_id": task_id})
        except Exception as e:
            # Fix is the ONE drawer action that always spends -- no free card ever covers a
            # fixer task -- so an unlogged failure here is money gone with nothing written
            # down. This route was the last holdout after _log_gen_failure was added for the
            # 2026-07-26 undiagnosable decline: it returned the redacted text to the browser,
            # friendlyGenErr() replaced it with a guess, and the real error was recorded
            # nowhere at all.
            return jsonify({"error": _log_gen_failure(
                "/api/fix", e, locals().get("fix_params"))[:300]}), 200

    # --- The Loom (Seedance storyboard) -------------------------------------
    # Storage is a small key->value store the Loom's window.storage shim reads via
    # /api/loom/*. Each key is now its OWN file, written atomically (tmp + os.replace,
    # the _save_telemetry idiom), so a crash mid-save corrupts at most the single key
    # being written -- one torn project can never take down every other storyboard.
    # The legacy single store.json (all boards + inline thumbs in one non-atomic write)
    # is migrated into per-key files on first touch and preserved as store.json.migrated.
    _loom_lock = threading.Lock()

    def _legacy_loom_kv_dir():
        """The pre-D-7 flat, install-wide store -- every account used to read and write
        the same files here. Now the shared, read-only fallback layer every account's
        _loom_kv_read falls through to until it saves its own copy of a given key."""
        d = out_dir / "loom" / "kv"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _legacy_loom_kv_path(key):
        from urllib.parse import quote
        return _legacy_loom_kv_dir() / (quote(str(key), safe="") + ".json")

    def _loom_kv_dir(user):
        # _account_key (B14 residual): a case-safe key for the per-account SUBDIRECTORY
        # -- same fix as _view_presets_path/_snips_path/_presets_path. The KEY portion
        # of a board's filename (_loom_kv_path below) is a separate concern (per-board
        # name collisions within one account's own dir, not account identity) and still
        # uses quote() unchanged.
        d = out_dir / "loom" / "kv" / _account_key(user)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _loom_kv_path(user, key):
        from urllib.parse import quote
        return _loom_kv_dir(user) / (quote(str(key), safe="") + ".json")

    def _loom_tomb_path(user, key):
        """Marks a legacy key this account has DELETED.

        Deleting only ever unlinked the account's own copy, and a board it had merely
        inherited from the legacy shared layer had no own copy to unlink -- so the delete
        reported success, the read fell straight back through to the legacy file, and the
        board came back. Every board predating the per-account split behaved that way:
        undeletable, with a fresh one deleting perfectly, which is what made it look like
        the list was showing the same board twice.

        A tombstone rather than deleting the legacy file itself, because that layer is
        shared and read-only to every account by design -- one account tidying its own
        board list must not remove a board out from under another. `.deleted` cannot
        collide with a real key: `quote(safe="")` percent-encodes any dot in a key name.
        """
        from urllib.parse import quote
        return _loom_kv_dir(user) / (quote(str(key), safe="") + ".deleted")

    def _loom_kv_write(user, key, value):
        """Atomically persist one key's value into the ACCOUNT'S OWN dir (tmp +
        os.replace). Never writes the legacy shared dir -- that stays exactly as
        _loom_migrate() left it, a read-only fallback."""
        p = _loom_kv_path(user, key)
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(value), encoding="utf-8")
        os.replace(tmp, p)
        # Writing a key un-buries it: an own copy now exists, so the tombstone has nothing
        # left to suppress, and leaving one behind would hide a board that was deliberately
        # re-created under the same key.
        try:
            _loom_tomb_path(user, key).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _loom_kv_read(user, key):
        """This account's value for `key`, falling back read-only to the legacy shared
        store if the account has never saved its own copy of this key -- same pattern as
        _load_view_presets/_load_snippets (D-7: storyboards were install-wide before this,
        so any signed-in account could read AND overwrite every other account's boards)."""
        own = _loom_kv_path(user, key)
        if own.exists():
            try:
                return json.loads(own.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return None
        if _loom_tomb_path(user, key).exists():
            return None      # this account deleted it; don't resurrect it from the legacy layer
        try:
            return json.loads(_legacy_loom_kv_path(key).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def _loom_migrate():
        """One-time split of the legacy single store.json into per-key files, in the
        LEGACY flat dir (unaffected by the D-7 per-account split -- it keeps writing the
        shared fallback layer every account now reads through). Idempotent + crash-safe:
        re-runs from the intact store.json until the final rename lands (a partial
        migration can't lose keys), then no-ops once store.json is gone."""
        legacy = out_dir / "loom" / "store.json"
        if not legacy.exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    p = _legacy_loom_kv_path(k)
                    tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
                    tmp.write_text(json.dumps(v), encoding="utf-8")
                    os.replace(tmp, p)
                except OSError:
                    return                      # leave store.json for the next touch to retry
        try:
            legacy.replace(legacy.with_name("store.json.migrated"))
        except OSError:
            pass

    # ==== THE NEW GALLERY -- React pilot ====================================
    # /next serves gallery/dist (Vite build: `npm run build` inside gallery/).
    # This is the FIRST-CLASS frontend the gallery UI is migrating to -- real
    # component files, its own purpose-built API below, NOT the Loom's delivery
    # and NOT the picker routes. The classic gallery at / is untouched; pieces
    # flip only on the owner's sign-off. Design lock + suite-shell rationale:
    # docs/DECISIONS.md "THE MIX is the pilot's locked direction" (2026-07-29).
    # Auth: covered by the global _enforce_front_door() hook like every route.
    _NEXT_DIST = Path(__file__).resolve().parent / "gallery" / "dist"

    # No vanilla web components ride along anymore: the video Generate drawer and
    # its cost badge became the React <VideoDrawer>/<CostBadge> in the 2026-08-08
    # no-vanilla port (the last of static/mg-*.js), joining the notify system
    # (toasts/tracker/celebrations) already in the React bundle -- so this shell
    # carries no <script src="/static/mg-*.js"> tags and no anchors.
    # __UPSCALE_CONST__ serves MG_LORA / MG_UPSCALE from their one Python source,
    # same idiom as the classic pages.
    NEXT_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moonglade Athenaeum</title>
<link rel="icon" href="/branding/favicon.ico">
<link rel="manifest" href="/next/assets/manifest.json">
<meta name="theme-color" content="#0a0818">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Moonglade">
<link rel="apple-touch-icon" href="/next/assets/icon-180.png">
<script>/* apply saved skin before first paint (no FOUC) */try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>""" + _AUTH_401_GUARD_JS + """
<link rel="stylesheet" href="/next/assets/app.css">
{# The app's ONE palette + every skin override, AFTER the bundle's stylesheet so
   the tokens win any same-specificity :root collision. Same idiom BASE_HTML and
   the Loom shell use -- deliberately not a /next/assets/tokens.css route, which
   would split the single source of truth. The notify system (in the React bundle
   as of the 2026-08-08 no-vanilla port) does the rest: it reconciles data-skin
   against /api/achievements on load. #}
<style>
__DESIGN_TOKENS__
</style>
</head><body>
<div id="root"></div>
{# The Job Tracker's #jobs-fab/#jobs-tray anchors lived here as body-level divs until the
   2026-08-08 no-vanilla port -- the React <ActivityTray> now renders them (same ids, still
   body-level via a portal), so the shell carries no notify markup, no pre-paint flash guard,
   and no mg-notify.js script tag. #}
{# |tojson, NOT json.dumps|safe: json.dumps does not escape "</script>", and boot
   carries third-party text (PixAI model titles via unique_models, collection
   names from any account). One "</script>" in a model title would break out of
   this inline script and run in a session that can POST the CSRF-exempt
   /api/generate -- i.e. spend without consent. Jinja's tojson escapes < > &. #}
<script>window.MG_BOOT = {{ boot|tojson }};</script>
__UPSCALE_CONST__
<script type="module" src="/next/assets/app.js"></script>
</body></html>"""

    # LoginPage.jsx's own shell (2026-08-02) -- deliberately its OWN, smaller
    # template rather than reusing NEXT_PAGE verbatim. Two real reasons, not
    # just tidiness:
    #   1. NEXT_PAGE's 8 <script src="/static/mg-*.js"> custom-element tags
    #      (pickers, cost badge, generate drawer, upscale panel) are for
    #      surfaces that don't exist on the login page at all -- dead weight
    #      to parse before a visitor has even signed in.
    #   2. Those files (and __UPSCALE_CONST__) are NOT on the public
    #      allowlist, and never needed to be until now -- only
    #      /next/assets/ (this page's own bundle/stylesheet) was added to
    #      _PUBLIC_PREFIXES. Reusing NEXT_PAGE unmodified would have 404/401'd
    #      an unauthenticated visitor's <script> requests for all 8 -- caught
    #      live: those requests 302'd back to /login (the front door redoing
    #      its own job on itself), the module script's own fetch got HTML
    #      back and threw "Unexpected token '<'", and the bundle never ran at
    #      all. Same app.js bundle either way (main.jsx statically imports
    #      both App and LoginPage, so Vite ships one file) -- only the SHELL
    #      differs, and the shell is what decides which one actually needs to
    #      reach an unauthenticated browser.
    LOGIN_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moonglade Athenaeum</title>
<link rel="icon" href="/branding/favicon.ico">
<link rel="manifest" href="/next/assets/manifest.json">
<meta name="theme-color" content="#0a0818">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Moonglade">
<link rel="apple-touch-icon" href="/next/assets/icon-180.png">
<script>/* apply saved skin before first paint (no FOUC) */try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>""" + _AUTH_401_GUARD_JS + """
<link rel="stylesheet" href="/next/assets/app.css">
<style>
__DESIGN_TOKENS__
</style>
</head><body>
<div id="root"></div>
{# |tojson, NOT json.dumps|safe -- same XSS reasoning as NEXT_PAGE's own boot
   script: Jinja's tojson escapes < > & so a stray "</script>" in, say, a
   redirected `next` path can never break out of this inline script. #}
<script>window.MG_BOOT = {{ boot|tojson }};</script>
<script type="module" src="/next/assets/app.js"></script>
</body></html>"""

    # "/" is the FRONT DOOR now (the flip, 2026-08-01); /next stays as a second
    # path to the same page so bookmarks and pushState URLs from the pilot era
    # keep working. One endpoint, two paths -- no redirect hop, same tier.
    @app.route("/")
    @app.route("/next")
    def next_gallery():
        session.setdefault("csrf", secrets.token_hex(16))
        brand = brand_context(out_dir)
        stats = catalog_counts(db_path)
        # First-run wizard gating -- SAME computation as classic's index() (see its own
        # long comment on why this is a fresh config.json read, not the module-cached
        # core._cfg): someone who just pasted a key via the wizard needs this to flip on
        # the very next load, not after a restart. No is_local/is_true_local conjunct here
        # either, matching index() exactly -- the front door's own auth gate is what keeps
        # an anonymous LAN visitor from ever reaching this line at all; a signed-in LAN
        # session sees the same wizard an owner does, and the real write endpoints
        # (/api/setup/save-key) enforce their own localhost-only check independently.
        import moonglade_backup as _core
        _fresh_cfg = _core._load_config()
        needs_key = not bool(_fresh_cfg.get("PIXAI_API_KEY") or _fresh_cfg.get("U3T"))
        catalog_empty = not needs_key and (stats["images"] + stats["videos"]) == 0
        # Asset container check (2026-08-10): cheap (marker-file compare, not a
        # re-hash) so it's safe on every boot, not just first-run. Placement of
        # the resulting UI moment (a Setup Wizard phase vs. standalone) is a
        # frontend decision -- this flag is UI-agnostic on purpose, same as
        # needs_key above, so either caller can drive it.
        needs_assets = moonglade_assets.needs_download(_container_path())
        boot = {
            "stats": stats,
            "needs_key": needs_key,
            "needs_assets": needs_assets,
            "catalog_empty": catalog_empty,
            "collections": unique_collections(db_path),
            "user": session.get("user") or "",
            "is_local": True,
            "is_true_local": _is_local_request(),
            "csrf": session["csrf"],
            "build_stamp": build_stamp,
            # The locked default; becomes a Branding-panel setting later
            # (docs/DECISIONS.md "Banner controls join the Branding panel").
            "band": {"height": 340, "crop": 30},
            # For the Advanced flyout: the model datalist + the From/To year range.
            "models": unique_models(db_path),
            "years": catalog_years(db_path),
            # The chosen branding: which mark, its animation, and whether it is a
            # rounded tile or a transparent floater. _inject_branding() already
            # puts these in every template's Jinja context; the pilot needs them
            # in JS because its mark is a React component, and the glint mask
            # needs the URL as a CSS variable (a built stylesheet cannot
            # Jinja-interpolate one). Without this the mark rendered dead.
            "mark_url": brand.get("mark_url") or "/branding/logo.png",
            "mark_anim": brand.get("mark_anim") or "classic",
            "mark_kind": brand.get("mark_kind") or "",
        }
        return render_template_string(
            NEXT_PAGE.replace("__UPSCALE_CONST__", _upscale_const_js())
                     .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS),
            boot=boot)

    @app.route("/next/assets/<path:fname>")
    def next_assets(fname):
        resp = send_from_directory(str(_NEXT_DIST), fname)
        # The bundle changes on every `npm run build` with NO url change, and this
        # response carried no Cache-Control -- so browsers HEURISTICALLY cached
        # app.css/app.js and kept painting days-old layout. Bit for real (2026-08-08):
        # the Details full-window takeover looked "overridden by the banner" on the
        # owner's everyday tab -- a stale cached app.css from BEFORE the takeover fix,
        # while a fresh session's probe of the same server looked perfect. no-cache
        # forces revalidation; ETag/Last-Modified make that a cheap 304 on localhost/
        # LAN, so repeat loads stay fast but can never be stale again.
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/api/next/library")
    def api_next_library():
        """The new gallery's own listing surface -- full filter set, clean field
        names, one purpose. Reads the same catalog engine (query_catalog) as
        everything else; nothing here is borrowed from the picker routes."""
        q = (request.args.get("q") or "").strip()
        try:
            page = max(1, int(request.args.get("page") or 1))
            page_size = max(1, min(int(request.args.get("page_size") or 100), 200))
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            page, page_size, rating_min = 1, 100, 0
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        sort = (request.args.get("sort") or "newest").strip()
        rows, total = query_catalog(
            db_path, q=q, sort=sort, page=page, page_size=page_size,
            rating_min=rating_min, media_type=media,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            # The Advanced flyout's fields -- same engine params the classic
            # gallery's form submits, same names where the URL is user-visible.
            model=(request.args.get("model") or "").strip(),
            lora=(request.args.get("lora") or "").strip(),
            date_from=(request.args.get("from") or "").strip(),
            date_to=(request.args.get("to") or "").strip(),
            art_tag=(request.args.get("tag") or "").strip(),
            # Not a flyout field -- reached only from the Details view's "View batch"
            # link (same engine param the classic gallery's own link sets).
            batch=(request.args.get("batch") or "").strip(),
            published_only=(request.args.get("published") or "") == "1")
        items = []
        for r in rows:
            mid = r.get("media_id")
            if not mid:
                continue
            items.append({
                "media_id": str(mid),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "is_video": str(r.get("is_video") or "") == "1",
                "is_nsfw": str(r.get("is_nsfw") or "") == "1",
                "model": str(r.get("model_name") or ""),
                "date": str(r.get("created_at") or "")[:10],   # UTC day -- fallback only; the
                "created_at": str(r.get("created_at") or ""),  # client derives the LOCAL day from this
                "rating": int(str(r.get("rating") or "0") or 0)
                          if str(r.get("rating") or "").isdigit() else 0,
                "w": str(r.get("width") or ""),
                "h": str(r.get("height") or ""),
                "prompt": (r.get("prompt_full") or r.get("prompt_preview") or "")[:1200],
                # The pilot's captions were missing metrics the classic card shows
                # (owner QA, 2026-07-30): where it came from, and the actual file.
                "source": str(r.get("source") or ""),
                "filename": str(r.get("filename") or ""),
                # The placard's Accession Stamp + Sibling Strip (issue #30): the
                # client batches task_ids into one POST /api/siblings per page.
                "task_id": str(r.get("task_id") or ""),
                "title": str(r.get("title") or "").strip(),
                "batch_index": str(r.get("batch_index") or ""),   # #33: PixAI's own output number
                "batch_size": str(r.get("batch_size") or ""),
            })
        pages = max(1, (total + page_size - 1) // page_size)
        return jsonify({"items": items, "total": total, "page": page, "pages": pages})

    @app.route("/api/next/detail/<media_id>")
    def api_next_detail(media_id):
        """The pilot's Details view backing data -- classic's detail() route (~12254),
        JSON instead of a server-rendered page. Full row, plus prev_id/next_id computed
        the SAME way: list_media_ids() under the CURRENT filter/sort (the same param
        names /api/next/library accepts), index looked up in that ordered id list.

        Deliberately does NOT precompute img_url/video_url/an existence check the way
        classic's route does -- classic needed that because a dead <img src> shows a
        broken-image icon with no explanation. The client already gets that signal for
        free (an <img>/<video> onError), so there is nothing here worth a filesystem
        stat the caller didn't ask for."""
        row = get_row(db_path, media_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        q = (request.args.get("q") or "").strip()
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        sort = (request.args.get("sort") or "newest").strip()
        try:
            rating_min = max(0, min(int(request.args.get("rating_min") or 0), 5))
        except ValueError:
            rating_min = 0
        nav_ids = list_media_ids(
            db_path, q=q, sort=sort, rating_min=rating_min, media_type=media,
            collection=(request.args.get("collection") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            model=(request.args.get("model") or "").strip(),
            lora=(request.args.get("lora") or "").strip(),
            date_from=(request.args.get("from") or "").strip(),
            date_to=(request.args.get("to") or "").strip(),
            art_tag=(request.args.get("tag") or "").strip(),
            published_only=(request.args.get("published") or "") == "1")
        try:
            idx = nav_ids.index(media_id)
        except ValueError:
            idx = -1
        prev_id = nav_ids[idx - 1] if idx > 0 else None
        next_id = nav_ids[idx + 1] if 0 <= idx < len(nav_ids) - 1 else None
        return jsonify({
            "row": row,
            "prev_id": prev_id, "next_id": next_id,
            # Same value the gallery's own "Delete from PixAI" is gated on. A LAN
            # session can browse and spend, but not destroy on the owner's real
            # cloud account.
            "can_delete_cloud": _is_local_request(),
            "siblings": _batch_sibling_count(row.get("task_id")),
        })

    def _history_ts(created_at):
        """Epoch seconds for a stored created_at, or None. Tolerant of the three forms
        the catalog holds: PixAI's 24-char `2026-08-17T06:14:10.545Z`, the 20-char
        no-millis `…Z` fallback, and 6 legacy local-import rows that are 19-char naive
        (`2026-07-29T21:47:44`) -- read as UTC, which is what they were written as."""
        from datetime import datetime, timezone
        s = str(created_at or "").strip()
        if s.endswith("Z"):
            s = s[:-1]
        try:
            base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        frac = s[19:]
        ms = 0.0
        if frac.startswith(".") and frac[1:].isdigit():
            ms = float("0" + frac)
        return base.timestamp() + ms

    @app.route("/api/next/history")
    def api_next_history():
        """Read-only feed for the Generate dock's History mode: the last `days` LOCAL
        calendar days of finished runs (catalog rows by created_at, newest first, empty
        days included as [] = "No runs"), with the live job log merged on top -- a
        running/stale/failed generate job that has no catalog rows yet becomes one
        synthetic row in its day; a done job is dropped (its media ARE catalog rows,
        saved before the done event ever lands), and a running job whose task already
        has rows in the window is dropped too (catalog wins). One indexed range query
        (`created_at >= ? AND created_at < ?`, no functions on the column) plus one
        seek for the paging cursor; core.read_jobs() DIRECTLY -- never /api/jobs's
        helpers, which reconcile against PixAI and rewrite the log. No network, no
        spend path, no _check_read_only: a local SQLite SELECT and a local file read.

        Params: days (1..31, default 7) · before (YYYY-MM-DD local, EXCLUSIVE cursor;
        absent = today is the newest bucket) · tz (minutes EAST of UTC, JS
        `-new Date().getTimezoneOffset()`; default = this server's local offset) ·
        source (online|api|local) · media (image|video) -- the last two in
        _build_where's own idiom. Day boundaries are computed HERE so the indexed
        window is exactly N local days and the empty days / `next_before` cursor are
        deterministic (and pytest-able) rather than a client-side guess."""
        import moonglade_backup as core
        from collections import Counter
        from datetime import datetime, timedelta, timezone
        try:
            days = max(1, min(int(request.args.get("days") or 7), 31))
        except ValueError:
            days = 7
        try:
            tz_min = int(request.args.get("tz") or "")
        except ValueError:
            tz_min = int(round((datetime.now().astimezone().utcoffset()
                                or timedelta(0)).total_seconds() / 60))
        tz_min = max(-14 * 60, min(tz_min, 14 * 60))
        tzinfo = timezone(timedelta(minutes=tz_min))
        before = (request.args.get("before") or "").strip()
        if before:
            try:
                end_local = datetime.strptime(before, "%Y-%m-%d").replace(tzinfo=tzinfo)
            except ValueError:
                return jsonify({"error": "before must be YYYY-MM-DD"}), 400
        else:
            today = datetime.now(tzinfo).date()
            end_local = datetime(today.year, today.month, today.day,
                                 tzinfo=tzinfo) + timedelta(days=1)
        start_local = end_local - timedelta(days=days)
        media = (request.args.get("media") or "").strip().lower()
        media = media if media in ("image", "video") else ""
        source = (request.args.get("source") or "").strip().lower()
        source = source if source in ("online", "api", "local") else ""

        def utc_iso(dt):
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        def local_date(ts):
            return datetime.fromtimestamp(ts, tzinfo).date()

        def as_int(s):
            s = str(s or "").strip()
            if not s:
                return None
            try:
                return int(float(s))
            except ValueError:
                return None

        where, params = _build_where("", "", "", "", media_type=media, source=source)
        since_utc, until_utc = utc_iso(start_local), utc_iso(end_local)
        con = _connect(db_path)
        try:
            rows = con.execute(
                "SELECT media_id, task_id, is_video, created_at, width, height, model_id, "
                "COALESCE(NULLIF(model_name,''), NULLIF(video_model,''), model_id, '') AS model, "
                "SUBSTR(COALESCE(NULLIF(prompt_full,''), prompt_preview, ''), 1, 300) AS prompt, "
                "video_duration, paid_credit, source "
                "FROM catalog WHERE {} AND created_at >= ? AND created_at < ? "
                "ORDER BY created_at DESC, media_id DESC".format(where),
                params + [since_utc, until_utc]).fetchall()
            # Paging cursor: the NEWEST row older than this window, so the next page
            # opens on a day that has runs instead of a run of empty days.
            older = con.execute(
                "SELECT created_at FROM catalog WHERE {} AND created_at < ? "
                "ORDER BY created_at DESC LIMIT 1".format(where),
                params + [since_utc]).fetchone()
            next_before, older_days = None, 0
            older_ts = _history_ts(older[0]) if older else None
            if older_ts is not None:
                nb_date = local_date(older_ts) + timedelta(days=1)
                nb_local = datetime(nb_date.year, nb_date.month, nb_date.day, tzinfo=tzinfo)
                next_before = nb_date.isoformat()
                older_days = len({
                    local_date(t) for t in (
                        _history_ts(r[0]) for r in con.execute(
                            "SELECT created_at FROM catalog WHERE {} AND created_at >= ? "
                            "AND created_at < ?".format(where),
                            params + [utc_iso(nb_local - timedelta(days=days)),
                                      utc_iso(nb_local)]).fetchall())
                    if t is not None})
        finally:
            con.close()

        buckets = {}
        for i in range(days):
            d = end_local - timedelta(days=i + 1)
            buckets[d.date().isoformat()] = []
        task_counts = Counter(str(r["task_id"] or "") for r in rows)
        for r in rows:
            ts = _history_ts(r["created_at"])
            if ts is None:
                continue
            key = local_date(ts).isoformat()
            if key not in buckets:
                continue
            mid = str(r["media_id"] or "")
            tid = str(r["task_id"] or "")
            is_video = str(r["is_video"] or "") == "1"
            pc = str(r["paid_credit"] or "").strip()
            duration = None
            if is_video:
                try:
                    duration = float(r["video_duration"]) if str(r["video_duration"] or "").strip() else None
                except ValueError:
                    duration = None
            buckets[key].append({
                "media_id": mid,
                "task_id": tid,
                "kind": "video" if is_video else "image",
                "state": "done",
                "created_at": str(r["created_at"] or ""),
                "ts": ts,
                "w": as_int(r["width"]),
                "h": as_int(r["height"]),
                "thumb": "/thumbs/{}.jpg".format(mid),
                "media_url": ("/video-file/{}" if is_video else "/full/{}").format(mid),
                "model": str(r["model"] or ""),
                "model_id": str(r["model_id"] or ""),
                "prompt": str(r["prompt"] or ""),
                "duration": duration,
                "paid_credit": as_int(pc) if pc else None,
                "source": str(r["source"] or ""),
                "count_in_task": task_counts[tid] if tid else 1,
            })

        # Live jobs on top, deduped against the catalog by task_id (== job_id for a
        # generate job). Jobs are always the dock's own runs (source 'api'), so a
        # feed narrowed to backed-up or imported rows has no live rows to add.
        try:
            jobs = core.read_jobs(out_dir)
        except Exception:
            jobs = []
        tasks_in_window = {str(r["task_id"] or "") for r in rows if r["task_id"]}
        for j in jobs:
            if j.get("type") != "generate":
                continue
            if j.get("status") not in ("running", "stale", "failed"):
                continue
            jid = str(j.get("job_id") or "")
            if not jid or jid in tasks_in_window:
                continue
            is_video = bool(j.get("is_video"))
            if (media == "video" and not is_video) or (media == "image" and is_video):
                continue
            if source in ("online", "local"):
                continue
            try:
                ts = float(j.get("started_at") or j.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            key = local_date(ts).isoformat()
            if key not in buckets:
                continue
            pc = j.get("paid_credit")
            try:
                count = max(1, int(j.get("count") or 1))
            except (TypeError, ValueError):
                count = 1
            buckets[key].append({
                "job_id": jid,
                "task_id": jid,
                "media_id": None,
                "kind": "video" if is_video else "image",
                "state": j.get("status"),
                "ts": ts,
                "created_at": datetime.fromtimestamp(ts, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"),
                "count": count,
                "label": j.get("label"),
                "error": j.get("error"),
                "eta_seconds": j.get("eta_seconds"),
                "started": j.get("started"),
                "paid_credit": (int(pc) if isinstance(pc, (int, float))
                                and not isinstance(pc, bool) else None),
                "w": None, "h": None, "thumb": None, "prompt": None, "model": None,
            })
        for key in buckets:
            buckets[key].sort(key=lambda x: (x["ts"], str(x.get("media_id") or "")),
                              reverse=True)
        return jsonify({
            "tz": tz_min,
            "days": [{"date": d, "label_hint": None, "rows": buckets[d]} for d in buckets],
            "next_before": next_before,
            "has_more": next_before is not None,
            "older_days": older_days,
        })

    @app.route("/loom/vendor/<path:fname>")
    def loom_vendor(fname):
        """Serve the Loom's vendored JS (React/ReactDOM UMD builds) from
        loom/vendor/ so the page paints with zero network calls. Path-safe; absent
        files 404. Not gated by _is_authorized_request() -- these are static library
        files, not gallery data, and /loom itself already enforces authorization above."""
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

    @app.route("/loom/dist/<path:fname>")
    def loom_dist(fname):
        """Serve the esbuild-bundled Loom (loom/dist/, built by `npm run build` in
        loom/) -- the Loom's SOLE delivery path since the Babel-standalone retirement
        (2026-08-08). Same path-safety pattern as loom_vendor(). Absent files 404;
        loom() below treats a missing bundle as 'not built yet' and says so (503).
        max_age=0 (unlike the vendor libs) since this output changes every rebuild."""
        from flask import send_from_directory, abort
        ddir = (Path(__file__).resolve().parent / "loom" / "dist").resolve()
        try:
            target = (ddir / fname).resolve()
            target.relative_to(ddir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(str(ddir), fname, max_age=0)

    @app.route("/loom")
    def loom():
        """Serve the Seedance video-storyboard tool inside the gallery, persisted to the
        backend (window.storage swapped for /api/loom/*). Authorized only.

        Bundle-ONLY since 2026-08-08 (the vanilla static/ -> React campaign): serves the
        pre-built esbuild bundle (loom/dist/master-storyboard.bundle.js, `npm run build` in
        loom/). The old in-browser Babel-standalone transpile was retired here -- the bundle
        is a real module build, so shared modules (loom-core, loom-mutations, the art-filter
        engine, ...) are plain imports esbuild resolves, with no hand-inlining. A checkout
        that hasn't built the bundle gets a clear message, not a silent fallback; the
        committed bundle + the CI staleness guard keep it current."""
        loom_dir = Path(__file__).resolve().parent / "loom"
        bundle_file = loom_dir / "dist" / "master-storyboard.bundle.js"
        if not bundle_file.is_file():
            return ("The Loom bundle is not built. Run `npm run build` in loom/ to "
                    "generate loom/dist/master-storyboard.bundle.js."), 503
        return LOOM_PAGE_BUNDLE.replace("__UPSCALE_CONST__", _upscale_const_js())

    @app.route("/api/loom/get")
    def loom_get():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        with _loom_lock:
            _loom_migrate()
            return jsonify({"value": _loom_kv_read(user, request.args.get("key") or "")})

    @app.route("/api/loom/set", methods=["POST"])
    def loom_set():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        p = request.get_json(silent=True) or {}
        k = p.get("key")
        if not k:
            return jsonify({"ok": False}), 400
        with _loom_lock:
            _loom_migrate()
            try:
                _loom_kv_write(user, k, p.get("value"))
            except OSError as e:
                return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:120]}), 500
        return jsonify({"ok": True})

    @app.route("/api/loom/list")
    def loom_list():
        from urllib.parse import unquote
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        pre = request.args.get("prefix") or ""
        with _loom_lock:
            _loom_migrate()
            # Union of the account's own keys and the legacy shared keys it hasn't
            # overridden yet -- mirrors _loom_kv_read's per-key fallback, so "list"
            # never omits a board a bare "get" on the same key would still return.
            own_keys = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.json")}
            legacy_keys = {unquote(f.stem) for f in _legacy_loom_kv_dir().glob("*.json")}
            # Minus anything this account has deleted. Without it a legacy board the
            # account never saved its own copy of stayed in the list forever: the delete
            # had nothing of its own to unlink, so it reported success and changed nothing.
            buried = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.deleted")}
            keys = (own_keys | legacy_keys) - buried
        return jsonify({"keys": sorted(k for k in keys if k.startswith(pre))})

    @app.route("/api/loom/delete", methods=["POST"])
    def loom_delete():
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        k = (request.get_json(silent=True) or {}).get("key")
        with _loom_lock:
            _loom_migrate()
            if k:
                # Unlinks only the account's OWN copy, never the legacy shared file --
                # matches _view_presets: the legacy layer is never written back to, so one
                # account tidying its board list cannot remove a board out from under
                # another.
                # That alone was not enough. A board the account had merely INHERITED from
                # the legacy layer has no own copy to unlink, so this reported success and
                # changed nothing: the next read fell straight back through to the legacy
                # file and the board returned. Every board predating the per-account split
                # was undeletable that way, while a freshly created one deleted perfectly
                # -- which reads as the list showing the same board twice. The gap was
                # known and judged not to bite a single owner; it does. Hence the tombstone
                # this comment used to propose.
                try:
                    _loom_kv_path(user, k).unlink()
                except FileNotFoundError:
                    pass    # already gone -- deleting a nonexistent key is still a success
                except OSError as e:
                    # A real failure (locked file, read-only mount, permissions) used to fall
                    # into the same bare `except OSError: pass` as "already gone" above, so
                    # {"ok": true} came back even though the file is still sitting there --
                    # matches loom_set's own OSError handling just above in this file.
                    return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:120]}), 500
                # Bury it only when the legacy layer would otherwise hand it straight back.
                # Fails soft: an unwritable tombstone leaves the old behaviour (the board
                # reappears), which is exactly what happened before and is not worth
                # turning a working delete into an error.
                if _legacy_loom_kv_path(k).exists():
                    try:
                        _loom_tomb_path(user, k).write_text("", encoding="utf-8")
                    except OSError:
                        pass
        return jsonify({"ok": True})

    def _find_local_video_file(mid, row=None):
        """Resolve a catalog media_id to its local video file on disk: try the catalog's
        stored filename first, then fall back to the shared media-id matcher (SAME exact
        media_id_of(p) == mid check and _duplicates/_deleted quarantine exclusion as every
        other matcher in this file -- B17, audit 2026-07-21: a bare glob fallback used to
        have neither, so a quarantined file was a valid hit and a shorter media_id could
        match as a substring of a longer, unrelated one's filename). find_files_for_media_id
        defaults to images, hence the explicit exts=vid_exts. Returns a Path or None.

        Shared by /api/loom/handoff (frame extraction), /api/loom/video-duration
        (footage-import fallback probe), the detail page's does-this-clip-exist check, and
        /video-file itself. That last one is the point rather than a nicety: while
        /video-file resolved `row["filename"]` on its own, the page could decide a clip was
        present (via the fallback here) and then link to a URL that 404s, which draws a dead
        player and says nothing -- the very failure the detail-page check was added to stop.
        One resolver, four callers, one answer.

        `row` is an already-loaded catalog row, passed by callers that just fetched it so
        this doesn't repeat a primary-key SELECT they already paid for. It is a cache, not
        an override: pass a DIFFERENT row and you get a different file, which is why only
        the two callers holding this exact mid's row use it."""
        import moonglade_backup as core
        # core._VIDEO_EXTS, not a hand-written tuple: the local copy was missing .m4v, which
        # core.run_import_local DOES copy in and catalog as is_video='1' (its media_exts is
        # _IMAGE_EXTS | _VIDEO_EXTS). Harmless while the only callers were Loom handoff/
        # duration -- a .m4v is never a generated shot -- but the detail page's existence
        # check below runs over a whole catalog, so the short list would have reported a
        # perfectly present imported clip as missing from disk.
        vid_exts = core._VIDEO_EXTS
        row = (row if row is not None else get_row(db_path, mid)) or {}
        fn = row.get("filename") or ""
        if fn:
            cand = out_dir / fn
            # The catalog's `filename` is joined onto out_dir, so a row carrying a traversing
            # path resolves outside the library. /video-file already refuses that (relative_to
            # + send_from_directory's own safe_join), which is exactly why this branch has to
            # agree: without the check THIS resolver says "present" for a file the serving
            # route will 404, and the detail page draws a player over it and says nothing --
            # M30's own symptom, reached by a different road. `.resolve()` is the load-bearing
            # part: relative_to alone does not normalise, so `..` walks straight through it.
            if (_is_under(cand.resolve(), Path(out_dir).resolve())
                    and cand.is_file() and cand.suffix.lower() in vid_exts):
                return cand
        fallback = find_files_for_media_id(out_dir, mid, exts=vid_exts)
        return fallback[0] if fallback else None

    @app.route("/api/loom/handoff", methods=["POST"])
    def loom_handoff():
        """Frame handoff: given a generated shot's video media_id, extract its LAST frame,
        upload it, and return the new frame media_id -- which the storyboard sets as the
        next shot's opening frame, chaining clips into one continuous scene. The clip must
        already be downloaded locally (it is, right after Generate-shot cataloged it).
        Login required; the upload is free."""
        body = request.get_json(silent=True) or {}
        mid = str(body.get("video_media_id") or "").strip()
        if not mid:
            return jsonify({"error": "video_media_id required"}), 400
        # Trim-aware: the previous shot's trimOut is where its cut actually ends, so hand
        # off the frame AT that point, not the untrimmed clip's real final frame. None/absent
        # -> the clip isn't trimmed, take the true last frame.
        try:
            trim_out = body.get("trim_out")
            trim_out = float(trim_out) if trim_out is not None else None
        except (TypeError, ValueError):
            trim_out = None
        try:
            core, session = _gen_session()
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "clip not downloaded yet -- generate/collect it first"}), 200
            fdir = out_dir / "loom" / "_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            png = fdir / (mid + "_last.png")
            if not core.extract_last_frame(str(vid), str(png), at_seconds=trim_out):
                return jsonify({"error": "could not extract the last frame (ffmpeg)"}), 200
            frame_mid = core.upload_media(session, str(png))
            dur = core.probe_video_duration(str(vid))
            return jsonify({"frame_media_id": str(frame_mid), "duration": dur})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/loom/import-frames", methods=["POST"])
    def loom_import_frames():
        """Give an IMPORTED clip the two stills it never had.

        A shot generated on the board gets its opening frame from whatever was fed in.
        An imported clip arrives already rendered, so nothing ever produced those stills
        and Deep Focus shows two empty slots -- even though the frames are sitting in the
        very file we already hold. ffmpeg has them: frame 0, and the last frame.

        Both are UPLOADED as well as thumbnailed, so they are real media ids rather than
        decoration: the close frame is then a valid continuity hand-off into the next shot,
        exactly like a generated shot's. Thumbnails are written because /thumbs/<id>.jpg
        serves from disk with no fetch-on-miss fallback, so an un-thumbnailed frame would
        render as a blank box. Login required; the upload is free.

        Partial success is a real outcome and is returned as one: if only one end extracts
        or uploads, that end still lands. The board fills whichever frames come back."""
        body = request.get_json(silent=True) or {}
        mid = str(body.get("video_media_id") or "").strip()
        if not mid:
            return jsonify({"error": "video_media_id required"}), 400
        try:
            core, session = _gen_session()
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "clip not downloaded yet -- collect it first"}), 200
            fdir = out_dir / "loom" / "_frames"
            fdir.mkdir(parents=True, exist_ok=True)
            out = {}
            # at_seconds=0.0 is the FIRST frame through the same primitive (it takes the
            # explicit-seek branch); None keeps the EOF-relative path for the last frame.
            for key, at in (("first", 0.0), ("last", None)):
                png = fdir / ("{}_{}.png".format(mid, key))
                if not core.extract_last_frame(str(vid), str(png), at_seconds=at):
                    continue
                try:
                    fmid = str(core.upload_media(session, str(png)))
                except Exception:                              # noqa: BLE001
                    continue                                   # one end failing is not fatal
                make_thumbnail(png, thumb_dir / (fmid + ".jpg"))
                out[key + "_media_id"] = fmid
            if not out:
                return jsonify({"error": "could not extract frames (ffmpeg)"}), 200
            return jsonify(out)
        except Exception as e:                                 # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/loom/video-duration")
    def loom_video_duration():
        """Real duration (seconds) of an already-catalogued video, via ffprobe on the local
        file -- fallback for the Footage tab's import-as-footage picker (loom/master-
        storyboard.jsx's importPickedFootage) when the catalog's own video_duration column
        is blank (rows predating that column, or whose request-duration was never captured
        -- see CATALOG_FIELDS/video_duration). Shares _find_local_video_file and
        probe_video_duration with /api/loom/handoff (the latter also powers the Edit Bay's
        reel) -- same resolver, same probing utility, nothing new invented. Read-only,
        local-file-only -- no PixAI session needed. Login required, matching every other
        /api/loom/* route."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"error": "media_id required", "duration": None}), 400
        try:
            vid = _find_local_video_file(mid)
            if vid is None:
                return jsonify({"error": "video file not found locally", "duration": None}), 200
            import moonglade_backup as core
            return jsonify({"duration": core.probe_video_duration(str(vid))})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "duration": None}), 200

    @app.route("/api/loom/generate", methods=["POST"])
    def loom_generate():
        """Generate a storyboard SHOT on PixAI (the video 'Copy shot' -> 'Generate shot').
        Resolves the shot's @-ordered images (upload data-URLs / pass media_ids) -> the PixAI
        video provider adapter -> card auto-apply (V4.0 = free) -> async submit. Login required
        (any session, local or LAN)."""
        try:
            import base64
            import hashlib
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            updir = out_dir / "loom" / "_uploads"
            updir.mkdir(parents=True, exist_ok=True)

            # I2V/FLF take a catalog media_id DIRECTLY; R2V still uploads. Measured 2026-07-26,
            # twice over. First by running the identical job on PixAI's own site and reading its
            # submit shape back with --dump-params (task 2038288375164786990, free): it sent
            # i2vPro.mediaId=747704233721405654 and tailMediaId=747643660108554296, BOTH rows in
            # this catalog -- generation OUTPUTS used as i2v INPUTS -- and the video rendered.
            # Then by surveying the owner's own history via getTaskById: 5 of 5 i2vPro tasks used
            # in-catalog ids, across three models, 2026-06-08 through 2026-07-22, including two
            # on 2026-07-20 itself.
            #
            # _input_media_id() assumes the opposite for every path, and its own cited evidence
            # shows why that overreached: `invalid_media_id` / `invalid_reference_image_media_id`
            # -- the second is the REFERENCE-VIDEO field. The requirement was real for R2V's
            # referenceImageMediaIds and got applied everywhere by a shared helper.
            #
            # For i2v it is worse than unnecessary. Uploading turns an image PixAI already holds
            # and already vetted into a BRAND-NEW upload, which its content scanner then checks
            # -- and that is what refused this owner's video with 403 NSFW_DETECTED while the
            # same frames sailed through on the website. The upload was manufacturing the
            # rejection. R2V uploaded too until the 2026-08-22 probe showed its field accepts
            # catalog ids as well -- see resolve_img.

            def resolve_img(val):
                s = str(val or "").strip()
                if not s:
                    return ""
                if s.isdigit():
                    # A catalog id passes through for EVERY mode. R2V was the last holdout,
                    # uploading on the belief that referenceImageMediaIds refuses a
                    # generation output. PROBED 2026-08-22 (getTaskById, 10 of the owner's own
                    # completed R2V tasks, read-only): two completed with ONLY in-library ids
                    # (one with six), four completed with library AND upload ids in the same
                    # submit. The field accepts catalog ids; the all-upload tasks were this
                    # very code re-uploading. (moonglade-internal/probes/
                    # PROBE_2026-08-22_r2v-refs-and-video-fields.md) If PixAI ever refuses
                    # an id synchronously, the upload-and-retry below catches it; see the
                    # note there on why the July refusal may have been asynchronous.
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

            resolved = [(str(x or "").strip(), resolve_img(x)) for x in (p.get("images") or [])]
            image_ids = [rid for _raw, rid in resolved if rid]
            video_ids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip().isdigit()]
            audio_ids = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip().isdigit()]

            def _params_for(imgs):
                return core.build_shot_video_params(
                    p.get("mode") or "R2V", (p.get("prompt") or "").strip(),
                    image_ids=imgs, video_ids=video_ids, audio_ids=audio_ids,
                    duration=p.get("duration") or 5,
                    generate_audio=bool(p.get("generate_audio") or p.get("audio")),
                    model=(p.get("video_model") or ""),
                    camera_movement=(p.get("camera_movement") or ""),
                    quality=(p.get("quality") or "professional"),
                    audio_language=(p.get("audio_language") or "english"),
                    negative=(p.get("negative") or "").strip(),
                    is_private=bool(p.get("is_private")),
                    use_prompt_helper=bool(p.get("prompt_helper")))

            def _card(prm):
                core._apply_kaisuuken(
                    session, prm,
                    SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))

            params = _params_for(image_ids)
            _card(params)
            try:
                task_id = core.submit_generation(session, params)
            except core.PixAIError as e:
                # SURVEYED, not guessed. getTaskById across the owner's own video history
                # (2026-07-26, read-only, no credits) found EVERY i2vPro task carrying an
                # in-catalog media id -- 5 of 5, zero uploads, across v3.2 / v4.0 / v4.0.1 and
                # spanning 2026-06-08 to 2026-07-22. Two of them are dated 2026-07-20, the very
                # day the "catalog ids are refused" bug was recorded, and they rendered fine.
                #
                # So PixAI never changed and i2vPro has always accepted a generation-OUTPUT id.
                # The July conclusion was generalised from the R2V error name
                # `invalid_reference_image_media_id`, and the resulting shared helper made every
                # gallery i2v re-upload its frame for a week.
                #
                # This fallback is therefore INSURANCE, not a coin-flip: cheap, already tested,
                # and it keeps a spend path working if that July observation turns out to be real
                # under some condition this survey did not cover.
                #
                # The passthrough attempt is what MATTERS for NSFW work: uploading converts an
                # image PixAI already holds and already vetted into a brand-new upload, and the
                # content scanner then refuses it (403 NSFW_DETECTED, no task) while the very
                # same frames pass on the website. The upload was manufacturing the rejection.
                #
                # Safe by submit_generation's own argument for its inferenceProfile retry: a
                # PixAIError means PixAI answered with a GraphQL error and REJECTED the task, so
                # there is nothing created and nothing charged to duplicate.
                # Both error names: `invalid_media_id` (i2vPro) and
                # `invalid_reference_image_media_id` (R2V's own field). The passthrough now
                # applies to every mode (probe 2026-08-22), so the fallback does too.
                #
                # HONEST SCOPE (adversarial review 2026-08-22): this only catches a
                # SYNCHRONOUS GraphQL rejection. The 2026-07-20 failures came "with a full
                # refund", which means those tasks were created and charged, then failed
                # ASYNCHRONOUSLY -- a path that surfaces through the poll's failure_reason
                # (_task_failure_reason), never through this except. So this is a free
                # belt-and-braces for a sync refusal, not a guarantee; the user-facing
                # safety net for an async refusal is the poll reporting the reason.
                err = str(e)
                if "invalid_media_id" not in err and "invalid_reference_image_media_id" not in err:
                    raise
                _logging_ = __import__("logging")
                _logging_.getLogger(__name__).info(
                    "passthrough refused (%s); uploading frames and retrying", err[:80])
                # Re-resolve ONLY the catalog (digit) ids through the upload path. Anything
                # else -- a Loom data: thumbnail already uploaded on the first pass, a bare
                # filename that resolved to "" -- keeps its first-pass result. Re-running
                # the raw payload here threw the thumbnail's upload away and sent the
                # base64 blob as a media id (adversarial review, 2026-08-22).
                image_ids = [m for m in ((_input_media_id(core, session, raw) if raw.isdigit() else rid)
                                         for raw, rid in resolved) if m]
                params = _params_for(image_ids)
                _card(params)
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
            return jsonify({"error": _log_gen_failure(
                "/api/loom/generate", e, locals().get("params"))[:300]}), 200

    def _run_export(cmd, out_path, total_sec):
        """Run the ffmpeg concat in a thread, parsing time= for progress. The output
        (--pix_fmt yuv420p h264) is a normal mp4 the browser can play + download."""
        import subprocess, re as _re
        tpat = _re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    text=True, bufsize=1, encoding="utf-8", errors="replace",
                                    creationflags=_NO_WINDOW)
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
                _export_job.update(status="failed", error=_redact_host_paths(str(e))[:200], proc=None)

    @app.route("/api/loom/export", methods=["POST"])
    def api_loom_export():
        """Trim each finished shot to its in/out and concat into one 720p mp4 -- the
        rough cut becomes a real deliverable. Async (ffmpeg in a thread); poll
        /api/loom/export-status, download /api/loom/export-file. Login required (any session, local or LAN).
        Each segment's real audio rides along when the clip has one (ffprobe-detected);
        segments with no audio stream (e.g. rendered without the "Generate audio" toggle)
        get matching-duration silence synthesized (anullsrc) so the concatenated audio
        track never desyncs across a segment boundary. "Matching" is load-bearing, not
        best-effort: a span is only ever a trim's own out point or a real ffprobe
        measurement, never a guess. When neither exists the export does NOT quietly pad --
        it either drops the audio track entirely (when there was no real audio anywhere, so
        nothing is lost) or refuses and names the shot (when real audio would be thrown out
        of sync by it). See the span pre-pass below. body: {clips:[{mid,in,out}], total_seconds}"""
        import shutil
        if not shutil.which("ffmpeg"):
            return jsonify({"error": "ffmpeg is not on PATH -- install it to export."}), 400
        # ffprobe deliberately is NOT gated here alongside ffmpeg. It usually ships in the
        # same package, and probe_has_audio()/probe_duration() both fail soft when it is
        # absent -- which means on a machine with ffmpeg but no ffprobe EVERY clip reads as
        # silent and no duration is readable, i.e. the common untrimmed shot would trip an
        # up-front gate and the owner would get no export at all. That machine used to get a
        # file (badly desynced, but a file), and taking the file away is a hard change to a
        # documented feature over a dependency the wiki does not ask for. So a missing
        # ffprobe DEGRADES here (see the span pre-pass: no measurable spans and no real
        # audio anywhere -> the cut is muxed without an audio track, which is the same thing
        # you would have heard, since every segment's audio was going to be synthesized
        # silence). A refusal is kept for the one case where continuing is definitively
        # corrupt: some shot HAS real audio and another cannot be measured, where a guessed
        # span shifts that real audio permanently out of sync.
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
            # Optional spatial crop: {x,y,w,h} fractions of the frame. Sanitized to a valid
            # in-bounds sub-rectangle; anything malformed or effectively full-frame -> no crop.
            crop = None
            cr = c.get("crop")
            if isinstance(cr, dict):
                try:
                    cx, cy = float(cr.get("x") or 0), float(cr.get("y") or 0)
                    cw, ch = float(cr.get("w") or 0), float(cr.get("h") or 0)
                    cx = min(max(cx, 0.0), 1.0); cy = min(max(cy, 0.0), 1.0)
                    cw = min(cw, 1.0 - cx); ch = min(ch, 1.0 - cy)
                    if cw > 0.05 and ch > 0.05 and (cw < 0.99 or ch < 0.99 or cx > 0.01 or cy > 0.01):
                        crop = (cx, cy, cw, ch)
                except (TypeError, ValueError):
                    crop = None
            # mid rides along purely so a per-segment failure below can name the shot the
            # owner has to go fix -- the on-disk path is a host path we don't hand back.
            segs.append((path, ci, co, probe_has_audio(path), crop, mid))
        if not segs:
            return jsonify({"error": "no finished shot videos found on disk to export"}), 400
        _export_dir.mkdir(parents=True, exist_ok=True)
        out_path = _export_dir / "loom_cut.mp4"
        W, H = 1280, 720
        parts, labels = [], ""
        # --- silence spans, resolved BEFORE a single filter string is built ----------
        # A silent segment needs an explicit numeric span to synthesize (anullsrc has no
        # natural end), and the number has to be RIGHT: concat lays each segment's audio
        # end-to-end, so silence shorter than its own video does not merely mute that shot's
        # tail -- every LATER segment's audio starts early and stays early for the rest of
        # loom_cut.mp4. Until 2026-07-27 an unreadable duration silently became
        # `max(0.1, (ci + 0.1) - ci)` == 0.1s, which manufactured exactly the desync this
        # whole path exists to prevent, in an export that reports "done" and looks finished
        # until you watch past the first shot.
        #
        # Doing the whole pass up front, instead of deciding shot-by-shot mid-assembly, is
        # what makes the fallback answerable: "can this export have a correct audio track at
        # all" is a question about the WHOLE clip list, and it has two very different
        # answers depending on whether any real audio is in play.
        spans = {}           # segment index -> silence span (silent segments only)
        unmeasurable = []    # media_ids of silent, untrimmed shots with no readable length
        for i, (path, ci, co, has_audio, crop, mid) in enumerate(segs):
            if has_audio:
                continue
            if co is not None:
                spans[i] = co - ci          # the trim's own end: exact, no probe needed
                continue
            dur = probe_duration(path)
            if dur is None:
                unmeasurable.append(mid)
                continue
            # Floor kept for the degenerate case a real measurement can still produce: a
            # trim-in at or past the clip's end leaves nothing, and atrim=duration=0 is not
            # a valid filter argument. This one IS a fudge, and a knowingly small one -- the
            # video side of such a segment is empty too, so the mismatch it can introduce is
            # bounded by 0.1s on a shot the owner has already trimmed into oblivion.
            spans[i] = max(0.1, dur - ci)
        have_real_audio = any(ha for (_p, _ci, _co, ha, _cr, _m) in segs)
        audio_track = True
        export_warning = ""      # set only when the cut comes out different from what was asked
        if unmeasurable and have_real_audio:
            # Some shot carries real recorded audio and another cannot be measured. Padding
            # the unmeasurable one with a guess would push that real audio permanently out
            # of sync, and dropping the track would throw the owner's actual audio away.
            # Both outcomes are worse than not producing a file, so this is the one refusal
            # left -- and since real audio was detected, ffprobe is demonstrably working,
            # which makes the named file itself the suspect.
            return jsonify({"error":
                "Shot %s has no audio track and no out point, so the export needs its real "
                "length to keep the shots that DO have audio in sync -- but ffprobe could "
                "not read its duration (the file may be truncated or still downloading). "
                "Set that shot's out point, or fix the file, then export again."
                % unmeasurable[0]}), 400
        if unmeasurable:
            # No real audio anywhere, so the entire audio track was going to be synthesized
            # silence. Mux without one instead of inventing lengths: the cut sounds exactly
            # the same, nothing can drift, and the owner gets the deliverable. This is the
            # ffmpeg-without-ffprobe machine's normal path -- probe_has_audio() answers
            # False for every clip there, so `have_real_audio` cannot be true.
            audio_track = False
            # Say it on the OWNER'S screen, not only in the log. A missing ffprobe is a
            # prerequisite problem with a one-line cure, and the person who can fix it is the
            # one staring at the export dialog -- handing them a quietly silent cut and filing
            # the reason in a log file they have no reason to open is how this stays a mystery.
            export_warning = (
                "Exported with no audio track. %d shot(s) (%s) have no audio, no out point, "
                "and their real length could not be measured, so there was nothing to keep in "
                "sync against.%s"
                % (len(unmeasurable), ", ".join(unmeasurable[:5]),
                   " ffprobe is not installed -- it ships with the full ffmpeg build, and "
                   "installing it restores measured lengths and audio."
                   if not shutil.which("ffprobe") else ""))
            try:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "loom export: %d shot(s) (%s) have no audio stream, no out point and no "
                    "readable duration%s -- exporting with no audio track rather than "
                    "padding with a guessed length.",
                    len(unmeasurable), ", ".join(unmeasurable[:5]),
                    " (ffprobe is not on PATH; it ships with the full ffmpeg build)"
                    if not shutil.which("ffprobe") else "")
            except Exception:
                pass
        need_silence = audio_track and any(not ha for (_p, _ci, _co, ha, _cr, _m) in segs)
        silence_idx = len(segs)   # the synthetic-silence input, appended after all real -i's
        for i, (path, ci, co, has_audio, crop, _mid) in enumerate(segs):
            tr = "trim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
            # A per-shot crop happens in SOURCE pixels (iw/ih), before the scale-to-canvas, so
            # the kept region fills the 1280x720 frame. No crop -> the chain is unchanged.
            crop_f = ("crop=iw*%.4f:ih*%.4f:iw*%.4f:ih*%.4f," % (crop[2], crop[3], crop[0], crop[1])) if crop else ""
            parts.append("[%d:v]%s,setpts=PTS-STARTPTS,%sscale=%d:%d:force_original_aspect_ratio=decrease,"
                         "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v%d]" % (i, tr, crop_f, W, H, W, H, i))
            if audio_track and has_audio:
                atr = "atrim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
                parts.append("[%d:a]%s,asetpts=PTS-STARTPTS[a%d]" % (i, atr, i))
            elif audio_track:
                # [silence_idx:a] is a raw decoder-input reference (the lavfi anullsrc), not a
                # named filter output -- ffmpeg allows referencing it multiple times (once per
                # silent segment) without an explicit asplit.
                parts.append("[%d:a]atrim=duration=%.3f,asetpts=PTS-STARTPTS[a%d]"
                             % (silence_idx, spans[i], i))
            # concat's input pads are PER-SEGMENT interleaved (v0,a0,v1,a1,...), never grouped
            # by stream type (v0,v1,...,a0,a1,...) -- ffmpeg errors "media type mismatch" if
            # the pad order doesn't match n*(v+a) in that exact per-segment sequence.
            labels += ("[v%d][a%d]" % (i, i)) if audio_track else ("[v%d]" % i)
        fc = ";".join(parts) + ";" + labels + (
            "concat=n=%d:v=1:a=1[vout][aout]" if audio_track else "concat=n=%d:v=1:a=0[vout]"
        ) % len(segs)
        cmd = ["ffmpeg", "-y"]
        for (path, _ci, _co, _ha, _cr, _m) in segs:
            cmd += ["-i", path]
        if need_silence:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += ["-filter_complex", fc, "-map", "[vout]"]
        if audio_track:
            cmd += ["-map", "[aout]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if audio_track:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [str(out_path)]
        with _export_lock:
            _export_job.update(status="running", progress=0, elapsed=0.0, out="",
                               error="", warning=export_warning, proc=None, cancelled=False)
        threading.Thread(target=_run_export, args=(cmd, out_path, total_sec), daemon=True).start()
        # `audio` is a fact about the file that is about to be written, returned so a caller
        # can tell the owner the cut came out silent-by-necessity. NOT a claim that anything
        # renders it today: the Loom's export dialog reads `error` on the POST and then polls
        # export-status, so as of this change the durable record of a dropped track is the
        # server log warning above. Stated plainly rather than dressed up, because a comment
        # promising a notice that no client draws is how this file rots.
        return jsonify({"ok": True, "shots": len(segs), "audio": audio_track})

    @app.route("/api/loom/export-status")
    def api_loom_export_status():
        with _export_lock:
            return jsonify({k: _export_job[k] for k in
                            ("status", "progress", "elapsed", "out", "error", "warning")})

    @app.route("/api/loom/export-file")
    def api_loom_export_file():
        name = _export_job.get("out") or "loom_cut.mp4"
        if not (_export_dir / name).exists():
            return "No export available.", 404
        return send_from_directory(str(_export_dir), name, as_attachment=True,
                                   download_name="moonglade-loom-cut.mp4")

    @app.route("/api/loom/export-cancel", methods=["POST"])
    def api_loom_export_cancel():
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

    # Tier 2 of the two-tier project export: a self-contained zip carrying every media
    # file a project actually references, alongside the same {project, thumbs} JSON tier 1
    # already produces client-side (see exportJSON in master-storyboard.jsx). A real
    # PixAI media_id is globally issued, not locally scoped, so the bundle keeps it as-is
    # end to end -- no path-rewriting inside the project object, ever. On import, a media
    # id already resolvable on the receiving machine is simply skipped (both sides already
    # have it); one that isn't gets copied into imported/ and cataloged fresh. That also
    # makes re-importing the same bundle twice a no-op the second time.
    _BUNDLE_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}  # mirrors backup.py's
    # _VIDEO_EXTS. It cannot be a MODULE-LEVEL import -- backup.py imports this file, so the
    # reverse at import time is a cycle -- but a function-body `import moonglade_backup as
    # core` inside create_app is fine and is what the rest of this file does (the delete
    # paths, _find_local_video_file). An earlier version of this comment said the constant
    # was "not imported directly" as if the layering forbade it outright; it doesn't, and
    # _find_local_video_file now reads core._VIDEO_EXTS exactly that way. This one stays a
    # literal only because it is bound while create_app is still building its namespace;
    # if the two lists ever drift, do the lazy import here too rather than re-typing them.

    def _loom_collect_media_ids(project):
        """Every real (catalog) media_id a project references -- resultMid, both frame
        slots, and every cast/asset entry -- mapped to WHERE each one was referenced from.
        thumbId references are NOT collected: they're client-only (base64 in `thumbs`) and
        already travel inside project.json as-is.

        Returns an insertion-ordered {media_id: [label, ...]} dict rather than the bare set
        this used to return, for two reasons. The labels are the whole difference between a
        useful missing-media report and the one export-bundle used to produce: "2 files are
        missing" with no way to tell which shot they belonged to left the owner hand-diffing
        every reference in the project against the zip's media/ folder. And insertion order
        makes the zip's media/ entries -- and the missing list -- come out identical twice
        for the same project, instead of following whatever order set hashing happened to
        pick that run. Callers that only want the ids still just iterate the dict.

        The labels mirror the Loom's own `A·01` shot codes (loom-core.js's actLetter +
        1-based card number) on purpose: a code in this report has to be one the owner can
        find on screen without translating it."""
        ids = {}

        def _note(mid, where):
            ids.setdefault(str(mid), []).append(where)

        for ai, act in enumerate(project.get("acts") or []):
            letter = chr(65 + ai) if ai < 26 else "A%d" % ai   # matches actLetter()'s wrap
            for ci, c in enumerate(act.get("cards") or []):
                code = "%s·%02d" % (letter, ci + 1)
                title = (c.get("title") or "").strip()
                code = "%s %s" % (code, title) if title else code
                if c.get("resultMid"):
                    _note(c["resultMid"], "%s (shot result)" % code)
                for slot in ("openFrame", "closeFrame"):
                    f = c.get(slot) or {}
                    if f.get("mediaId"):
                        _note(f["mediaId"], "%s (%s)" % (code, slot))
        for a in (project.get("assets") or []):
            if a.get("mediaId"):
                who = (a.get("name") or a.get("tag") or a.get("id") or "?")
                _note(a["mediaId"], "cast/asset %s" % who)
        return ids

    def _loom_resolve_media(mid):
        """A project can reference either an image OR a video by media_id (a shot's
        resultMid is very often a video), but find_files_for_media_id only ever sees
        images by design. Same fallback /api/loom/export already uses for exactly this
        reason: catalog row -> is_video + filename -> out_dir/filename. Returns a Path
        or None."""
        paths = find_files_for_media_id(out_dir, mid)
        if paths:
            return paths[0]
        row = get_row(db_path, mid)
        if row and str(row.get("is_video") or "") == "1" and row.get("filename"):
            p = out_dir / row["filename"]
            if p.exists():
                return p
        return None

    # Cap on the X-Bundle-Missing value. Nothing in HTTP bounds a header value, but every
    # mainstream server and proxy caps the header BLOCK (nginx/Apache land around 8 KB, and
    # the limit is on the whole block, not this one line), so a header that grows with the
    # project is how you get a bundle that downloads fine on the machine that built it and
    # is rejected by a proxy on the next one. ~900 bytes fits a few dozen ids with the rest
    # of the response's headers left comfortable.
    _BUNDLE_MISSING_HEADER_MAX = 900

    def _bundle_missing_header(missing):
        """The X-Bundle-Missing value: comma-separated, ASCII-only, length-capped media_ids.

        Filtered rather than trusted, because every id here came out of client-supplied
        project JSON: a value carrying CR/LF is header injection, and a non-latin-1 one makes
        Werkzeug raise while serialising the response -- turning a successful export into a
        500 for the owner. Ids that survive the filter but overflow the cap collapse into a
        trailing "+N more"; the complete list, with the act/shot each id came from, is in the
        zip's project.json regardless, which is why truncating here costs nothing."""
        safe = [s for s in (re.sub(r"[^A-Za-z0-9._-]", "", str(m["media_id"]))[:64]
                            for m in missing) if s]
        out, used = [], 0
        for i, mid in enumerate(safe):
            if used + len(mid) + 1 > _BUNDLE_MISSING_HEADER_MAX:
                out.append("+%d more" % (len(safe) - i))
                break
            out.append(mid)
            used += len(mid) + 1
        return ",".join(out)

    @app.route("/api/loom/export-bundle", methods=["POST"])
    def api_loom_export_bundle():
        """Full-bundle export: a zip of project.json (the lightweight Backup .json's
        {project, thumbs}, plus a `missing_media` manifest this tier alone can produce
        because only the server knows what's on disk) and every referenced media file under
        media/<id><ext>. Login required -- reads real files off disk, same trust level as
        /export-zip."""
        import io
        import zipfile
        body = request.get_json(silent=True) or {}
        project = body.get("project") or {}
        thumbs = body.get("thumbs") or {}
        if not project:
            return jsonify({"error": "no project given"}), 400
        mids = _loom_collect_media_ids(project)
        # Resolve everything BEFORE opening the archive so project.json can carry the missing
        # manifest and still be written first (a reader streaming the zip gets the project,
        # and the report about it, before megabytes of media).
        resolved, missing = [], []
        for mid in mids:
            p = _loom_resolve_media(mid)
            if p:
                resolved.append((mid, p))
            else:
                missing.append({"media_id": mid, "referenced_by": mids[mid]})
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
            z.writestr("project.json", json.dumps({"project": project, "thumbs": thumbs,
                                                   "missing_media": missing}))
            for mid, p in resolved:
                z.write(p, arcname="media/{}{}".format(mid, p.suffix.lower()))
        mem.seek(0)
        name = "{}_bundle.zip".format((project.get("name") or "loom_project").replace(" ", "_"))
        resp = send_file(mem, mimetype="application/zip", as_attachment=True, download_name=name)
        # Missing media doesn't fail the export (a partial bundle is still useful), so the
        # report has to reach the owner some other way. It goes to two places on purpose:
        #
        #   project.json's `missing_media` is the durable copy -- id plus the act/shot code
        #   each id was referenced from. It is IN the zip, so it survives the download, it
        #   travels to whoever the bundle is handed to, and it does not depend on a client
        #   noticing a response header at the moment of export. import-bundle ignores the key
        #   (it reads `project`/`thumbs`), so adding it costs the round trip nothing.
        #
        #   X-Bundle-Missing is the live copy, so the client can NAME what didn't travel
        #   instead of only counting it. This route shipped with the count alone under a
        #   comment claiming "the client surfaces this list" -- it could not; `missing` was
        #   discarded the moment len() was taken, and the owner was told "2 files are missing"
        #   with nowhere to look them up. X-Bundle-Missing-Count stays for the client that
        #   already reads it, and stays authoritative: it is the true total, while the header
        #   list may be truncated (see _bundle_missing_header).
        resp.headers["X-Bundle-Missing-Count"] = str(len(missing))
        hdr = _bundle_missing_header(missing)
        if hdr:
            resp.headers["X-Bundle-Missing"] = hdr
        return resp

    @app.route("/api/loom/import-bundle", methods=["POST"])
    def api_loom_import_bundle():
        """Accepts a full-bundle zip (see export-bundle), catalogs any media this machine
        doesn't already have (source='api' -- it's real PixAI media, just synced via the
        bundle instead of --update), and returns {project, thumbs} in the exact shape
        importJSON already expects, so both tiers share one client-side create-project path.
        Login required (any session, local or LAN)."""
        import io
        import time
        import zipfile
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        try:
            z = zipfile.ZipFile(io.BytesIO(f.read()))
            data = json.loads(z.read("project.json").decode("utf-8"))
        except Exception:
            return jsonify({"error": "not a valid bundle (couldn't read project.json)"}), 400
        project = data.get("project")
        if not project:
            return jsonify({"error": "bundle's project.json has no project"}), 400
        imported_dir = out_dir / "imported"
        rows = []
        for name in z.namelist():
            if not name.startswith("media/") or name.endswith("/"):
                continue
            mid = Path(name).stem
            if _loom_resolve_media(mid):
                continue  # already have it -- both sides share this media, nothing to do
            ext = Path(name).suffix.lower()
            imported_dir.mkdir(parents=True, exist_ok=True)
            dest = imported_dir / "{}{}".format(mid, ext)
            dest.write_bytes(z.read(name))
            is_vid = ext in _BUNDLE_VIDEO_EXTS
            thumb_path = thumb_dir / "{}.jpg".format(mid)
            if is_vid:
                make_video_thumbnail(dest, thumb_path)  # best-effort; --rebuild-thumbs backfills
            else:
                make_thumbnail(dest, thumb_path)
            row = {k: "" for k in CATALOG_FIELDS}
            row.update({
                "media_id": mid, "filename": str(dest.relative_to(out_dir)).replace("\\", "/"),
                "source": "api", "status": "imported",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "prompt_preview": dest.stem[:100], "is_video": "1" if is_vid else "",
            })
            rows.append(row)
        if rows:
            save_catalog(db_path, rows)
        return jsonify({"project": project, "thumbs": data.get("thumbs") or {},
                        "media_added": len(rows)})

    # ---- queue-vs-render phase, recorded for the Activity tray -----------------------
    # Maps a task id to the `started` value already written to the job log for it. The tray
    # (gallery/src/notify/ActivityTray.jsx) renders from /api/jobs, never from api_task_status()'s response,
    # so `started` has to be written DOWN to reach it -- and writing it here is what makes
    # the signal identical on both hosts, because the gallery's Jobs.poll(), the Loom's
    # pollShot/pollTaskWithCeiling and mg-generate-drawer.js's own poll all hit this one
    # route and none of them has to know the field exists.
    #
    # De-duped rather than written per poll for two concrete reasons: four pollers ask every
    # 3s per job, so a task PixAI sits on for its whole ~60-minute reap window would add
    # 1,200+ lines to jobs.jsonl; and each write refreshes that job's `ts`, which is the
    # clock JOBS_ORPHAN_SWEEP_AGE is measured against -- a heartbeat every 3s would mean the
    # ongoing orphan-reconciliation sweep never sees a job age in at all. At most two lines
    # per job survive this (queued, then started), and the entry is dropped the moment the
    # job reaches a terminal phase so the map stays bounded by tasks IN FLIGHT, not by uptime.
    _gen_phase_seen = {}
    _gen_phase_lock = threading.Lock()

    def _queue_estimate(core, session, tid):
        """PixAI's own queue-wait estimate for the model THIS task was submitted with, in
        seconds, or None. Two read-only calls (the task's stored submit parameters, then
        /v2/task/wait-time -- see core.queue_wait_estimate); fails soft, because an estimate
        must never turn a status poll into an error."""
        try:
            params = (core._task_detail_query(session, tid) or {}).get("parameters") or {}
            if not isinstance(params, dict):
                return None
            return core.queue_wait_estimate(session, params.get("priority"),
                                            params.get("modelId"))
        except Exception:                          # noqa: BLE001 -- a nicety, never fatal
            return None

    def _note_gen_phase(core, session, tid, started):
        """Write a generate job's queued/rendering phase to the job log, once per change.

        On the FIRST sighting of a job PixAI has accepted but not started, also record its
        queue estimate. Fetched here rather than per poll: a generation a worker picks up
        before its first poll costs zero extra calls, and one that really is queued costs
        two, once. The number is stored as the estimate PixAI gave when the job was seen
        queued and is rendered that way -- nothing recomputes it as the wait grows, and it
        is never presented as a countdown.

        Those two calls ride ONE poll of an already-queued job, which is why they are done
        inline rather than off-thread: the poll interval is 3s and this route already makes an
        un-timed PixAI call of its own on every single poll, so a second pair on one poll of
        one job is not the thing worth adding a thread for.
        """
        with _gen_phase_lock:
            if _gen_phase_seen.get(tid) == started:
                return
            first = tid not in _gen_phase_seen
            _gen_phase_seen[tid] = started
        fields = {"status": "running", "started": started}
        if first and not started:
            eta = _queue_estimate(core, session, tid)
            if eta is not None:
                fields["eta_seconds"] = eta
            # RE-CHECK before writing. The estimate above is two network calls long, and a
            # worker can pick the job up while we are inside it -- in which case a later poll
            # has already claimed and written the newer 'rendering' phase. Writing our
            # pre-fetch 'queued' on top of that would be permanent: the seen-map already
            # holds the newer value, so every subsequent poll returns early at the dedupe
            # check above and nothing ever corrects it. The job would render to completion
            # still displaying QUEUED. Dropping a stale write costs nothing; the newer phase
            # is already in the log.
            with _gen_phase_lock:
                if _gen_phase_seen.get(tid) != started:
                    return
        _log_job(tid, **fields)

    def _forget_gen_phase(tid):
        with _gen_phase_lock:
            _gen_phase_seen.pop(tid, None)

    def _fire_enhance_telemetry(tid):
        """Fire the three enhance-achievement producers exactly once, on TERMINAL SUCCESS (a
        done phase WITH output) of an enhance task THIS server submitted. Deferred from
        /api/enhance -- which only sees createGenerationTask ACCEPTANCE -- so a task that is
        accepted, charged, then reaped unstarted (or fails) never counts. A no-op for any
        task id that was not a pending enhance (normal generate/edit/video collect here too).

        Swallows EVERY failure: by the time this runs the credit has already been spent and the
        result collected, so a telemetry error must not propagate into api_task_status's except
        handler -- that would report a false 'failed'/'running' and, worse, prompt a re-poll
        that re-collects. Mirrors api_generate's LoRA-telemetry try/except."""
        with _enhance_pending_lock:
            identity = _enhance_pending.pop(str(tid), None)
        if identity is None:
            return
        try:
            telem_bump("enhances", out_dir=out_dir)                        # first-enhance milestone
            telem_set_add("tools", "enhance", out_dir=out_dir)             # Full Toolbox
            telem_set_add("enhance_workflows", identity, out_dir=out_dir)  # Enhance Adept: distinct rituals
        except Exception:                                                  # noqa: BLE001
            pass

    def _drop_enhance_pending(tid):
        """Forget a pending enhance without firing telemetry -- for a terminal FAILURE (reaped,
        cancelled, or done-but-empty). Keeps the map from leaking and guarantees a failed run
        never bumps a counter."""
        with _enhance_pending_lock:
            _enhance_pending.pop(str(tid), None)

    @app.route("/api/task-status")
    def api_task_status():
        """Poll a submitted task: {phase: running|done|failed}. On 'done' it downloads +
        catalogs the result into this backup and returns media_ids + paid_credit. Read-only
        until done; login required."""
        # Bound HERE, not inside the try: the except clause below names this module,
        # and an except expression is evaluated while handling the exception -- so if
        # _gen_session() were the thing that raised, a try-scoped name would turn a
        # handled error into a NameError.
        import moonglade_backup as _core
        tid = (request.args.get("task_id") or "").strip()
        if not tid:
            return jsonify({"phase": "failed", "error": "task_id required"}), 400
        try:
            core, session = _gen_session()
            st = core.generation_status(session, tid)
            if st["phase"] == "done":
                _forget_gen_phase(tid)
                got = _collect_single_flight(core, session, tid)
                # authoritative done event -- written server-side so the Jobs card gets the
                # outcome even if the browser tab that submitted it has since closed.
                # paid_credit is PixAI's server-authoritative actual cost. Logged, not just
                # returned to the browser: it is the one number that cannot be
                # reconstructed later without re-querying PixAI per task, and it is what
                # makes an unexpected spend visible in the Activity tray afterwards. Passed
                # through even when 0 -- a card-covered generation really is free, and
                # "free" must stay distinguishable from "unknown".
                _log_job(tid, status="done", media_ids=got["media_ids"],
                         is_video=got.get("is_video", False),
                         paid_credit=st.get("paid_credit"))
                # TERMINAL SUCCESS with output: the ONLY point an enhance is allowed to count
                # (deferred from /api/enhance's submit-acceptance). No-op for non-enhance tasks;
                # swallows its own errors so a post-charge telemetry blip can't fail this poll.
                _fire_enhance_telemetry(tid)
                return jsonify({"phase": "done", "media_ids": got["media_ids"],
                                "is_video": got.get("is_video", False),
                                "duration": got.get("duration"),
                                "paid_credit": st["paid_credit"]})
            if st["phase"] == "failed":
                _forget_gen_phase(tid)
                _drop_enhance_pending(tid)   # a reaped/cancelled enhance must NOT count
                # Carry PixAI's OWN reason (outputs.reason, e.g. "waiting timeout") into
                # both the job log and the response. This branch already fired correctly
                # for the owner's five reaped enhances -- it just logged the bare status,
                # so the tracker and the CLI could say no more than "cancelled", which
                # reads as though HE cancelled a job that in fact never started.
                reason = (st.get("reason") or "").strip()
                detail = core.describe_failure(st.get("status"), reason,
                                               started=bool(st.get("started")))
                _log_job(tid, status="failed", error=detail)
                return jsonify({"phase": "failed", "status": st["status"],
                                "reason": reason, "error": detail})
            # `started` distinguishes "queued, no worker has taken it" from real work --
            # both are phase=running over the wire, and without it a task PixAI never
            # dispatches is an indefinite spinner for the ~60 min until it is reaped.
            # Recorded in the job log as well as returned, because the Activity tray reads
            # the log (see _note_gen_phase); the response alone only reaches whoever polled.
            started = bool(st.get("started"))
            _note_gen_phase(core, session, tid, started)
            return jsonify({"phase": "running", "status": st["status"],
                            "started": started})
        except _core.EmptyOutputsError as e:
            # TERMINAL, unlike the transient case below: PixAI already told us the
            # task reached 'done', and collect then found its outputs empty. The task
            # produced nothing and never will, so this MUST write an authoritative
            # 'failed' -- without it the job spins on 'running' in the Jobs card
            # forever. (Observed: an enhance submitted with an unusable input media id
            # sat at 'running' indefinitely while PixAI considered it long finished.)
            _drop_enhance_pending(tid)   # done-but-empty is a failure: it must NOT count
            _log_job(tid, status="failed", error=_redact_host_paths(str(e))[:200])
            return jsonify({"phase": "failed", "error": _redact_host_paths(str(e))[:200]}), 200
        except (TypeError, AttributeError, NameError, KeyError, IndexError) as e:
            # A defect in THIS code, not a PixAI blip. The broad handler below deliberately
            # answers 'running' so a flaky network keeps getting retried -- but retrying a
            # TypeError just repeats it, so a genuinely broken poll used to present as a job
            # that was merely slow, for the full 6h polling ceiling, with nothing anywhere
            # saying otherwise. These are the errors that cannot come good on a retry, so
            # they get the authoritative 'failed' the paragraph below is right to withhold
            # from everything else.
            import logging as _logging          # module-local, as everywhere else in this file
            _log_job(tid, status="failed", error=_redact_host_paths(str(e))[:200])
            # The traceback is the whole point for this class: it names the line to fix, and
            # moonglade_logging keeps a rotating file log regardless of -v.
            _logging.getLogger(__name__).exception("task-status poll failed for %s", tid)
            return jsonify({"phase": "failed",
                            "error": "Moonglade hit an internal error checking this job "
                                     "({}). The generation itself may be fine -- check the "
                                     "Activity card.".format(_redact_host_paths(str(e))[:120])}), 200
        except Exception as e:
            # A transient PixAI blip (5xx/429/timeout) raises here even though the task may
            # still be running -- or already finished. Do NOT write an authoritative 'failed'
            # job event: that would brick the card with a sticky false failure + a red toast
            # for a task that likely succeeded. Leave the job at its last-known state (it ages
            # out, or the live-mirror watcher collects the real result). Only a genuine
            # st["phase"] == "failed" above logs a terminal failure.
            #
            # The RESPONSE used to say phase:'failed' too, which defeated the whole point of
            # the paragraph above: the Jobs poller (gallery/src/notify/jobs.js) treats phase==='failed'
            # as terminal and stops polling right there (it only reschedules on anything
            # else), so even with the job log correctly left alone, THIS live poll would
            # still brick the card with a false failure. Report it as non-terminal instead --
            # poll() falls into its 'running' branch on anything but 'done'/'failed' and just
            # tries again in 3s, up to its own 6h ceiling either way (audit fail-open fix).
            return jsonify({"phase": "running",
                            "status": "checking… ({})".format(_redact_host_paths(str(e))[:160])}), 200

    @app.route("/api/jobs")
    def api_jobs():
        """Reconstructed job list for the Jobs card (newest-first) -- the paper trail that
        survives a reload. The card polls this. Login required, like the creation suite.

        Also runs the ongoing orphan-reconciliation sweep (_reconcile_orphan_jobs,
        min_age=JOBS_ORPHAN_SWEEP_AGE) before reading -- the same "runs opportunistically
        off an existing poll" shape as maybe_compact_jobs just below it. This is what
        catches a job that gets orphaned WHILE the server keeps running (the watcher's own
        sweep only fires once, at startup) -- e.g. the browser tab polling
        /api/task-status was closed, or the live-mirror watcher missed the WS event, and
        the task finished on PixAI's side with nothing here ever the wiser. Fails soft
        (see _reconcile_orphan_jobs); a reconciliation problem must never break the card."""
        import moonglade_backup as core
        try:
            _reconcile_orphan_jobs(min_age=core.JOBS_ORPHAN_SWEEP_AGE)
            jobs = core.read_jobs(out_dir)
            core.maybe_compact_jobs(out_dir)   # keep the append-only log bounded
        except Exception:
            jobs = []
        return jsonify({"jobs": jobs})

    @app.route("/api/jobs", methods=["POST"])
    def api_jobs_register():
        """Register/update a job in the log. The Jobs card calls this the moment a gen is
        submitted (status=running) so it shows immediately; the authoritative done/failed
        events are written server-side by /api/task-status. Login required (any session, local or LAN)."""
        body = request.get_json(silent=True) or {}
        jid = str(body.get("job_id") or "").strip()
        if not jid:
            return jsonify({"ok": False, "error": "job_id required"}), 400
        # count: how many images this task was submitted to render (image-gen only --
        # absent on edit/fix/video/Loom registrations). Clamped to the same 1-4 range
        # /api/generate enforces; anything else is a caller bug or a stale client, not
        # data worth trusting into the log. Lets the React dock's Runs reel render a
        # real "N requested" placeholder for a running batch instead of one generic
        # tile (2026-08-02, closes the verify-flagged gap in the reel rebuild).
        _count = body.get("count")
        try:
            _count = int(_count)
            if not (1 <= _count <= 4):
                _count = None
        except (TypeError, ValueError):
            _count = None
        _log_job(jid, status=(body.get("status") or "running"),
                 type=body.get("type"), label=body.get("label"),
                 done=body.get("done"), total=body.get("total"), count=_count,
                 source=body.get("source") or "web")
        return jsonify({"ok": True})

    @app.route("/api/jobs/dismiss", methods=["POST"])
    def api_jobs_dismiss():
        """Dismiss one job (job_id) or every finished job (finished:true) from the card --
        this is how a sticky failure gets cleared. Login required (any session, local or LAN)."""
        import moonglade_backup as core
        body = request.get_json(silent=True) or {}
        if body.get("finished"):
            try:
                for j in core.read_jobs(out_dir):
                    if j.get("status") in core._JOBS_TERMINAL:
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
        """Live enhance-workflow catalog (id + name + type) for the Bridge picker. Read-only;
        login required (uses the owner's key). Restored 2026-08-18 for parity -- NOTE: this
        connection returns ZERO entries on our credential (probed 2026-08-16/17), so the six
        Bridge Enhance presets are hardcoded in the drawer, not sourced from here. Kept so the
        picker self-updates the day PixAI opens the connection to us."""
        try:
            core, session = _gen_session()
            return jsonify({"workflows": core.workflow_catalog(session)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "workflows": []}), 200

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

    @app.after_request
    def _code_assets_no_cache(resp):
        # Same staleness class as /next/assets (see next_assets): the shared
        # static/mg-*.js web components change on edit with no url change, and
        # heuristic caching kept old copies live in real tabs. Scoped to /static/
        # ONLY -- thumbnails and full media stay freely cacheable (huge, and a
        # media file's content never changes under its id).
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.after_request
    def _identify_server(resp):
        # Stamp EVERY response -- including the front door's 401 short-circuit -- with a
        # stable marker the "Serve Gallery" launcher uses to tell "our server is already
        # on this port" from "some other service is" (or nothing). It MUST ride the auth
        # gate: the launcher probes /api/ping without a session and now gets a 401, not a
        # 200, so a status-based check can't identify us. A fixed value, not __version__:
        # the launcher only needs identity, and broadcasting the exact build on every
        # response is needless disclosure for a public-repo app. after_request runs on
        # responses returned by before_request (the gate returns, never raises), so the
        # header lands on the 401 too -- pinned by test_web_auth.
        resp.headers["X-Moonglade"] = "1"
        return resp

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def port_owner(host, port, timeout=0.4):
    """Who, if anyone, is already listening on (host, port)?

    Returns "" if the port is free, "moonglade" if the thing answering is one of
    our own servers, and "other" if something is listening but isn't us.

    This exists because `app.run()` will NOT tell you. Werkzeug's dev server sets
    allow_reuse_address, and on Windows SO_REUSEADDR does something Unix does not:
    it lets a second socket bind a port that is ACTIVELY SERVING, rather than only
    reclaiming one stuck in TIME_WAIT. Both processes then hold :PORT and requests
    land on whichever the OS feels like -- so you edit a file, reload, and get the
    OLD server's response with no error anywhere. That is not hypothetical; it has
    burned this project twice (the old state doc's verification notes), each time
    costing a debugging session chasing a "fix that didn't work" which had in fact
    worked perfectly in a process nobody was talking to.

    `Serve Gallery.pyw` already probes the X-Moonglade header to decide "one of our
    servers is already up here" before launching. That check lived ONLY in the
    launcher, so `python moonglade_gallery.py --port N` -- how every script, test
    harness and background agent starts this thing -- walked straight past it.
    Same probe, moved to where it cannot be bypassed.

    The header is the right signal rather than the status code: /api/ping sits
    behind the login gate and answers 401, so "did it 200" would read a live
    gated server as a dead port (see tests/test_web_auth.py's
    test_every_response_carries_the_server_marker, which pins exactly this)."""
    import socket
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.create_connection((probe_host, port), timeout=timeout):
            pass
    except OSError:
        return ""                      # nothing there -- free to bind
    # Something is listening. Ask whether it is ours. Any failure here (HTTPS on
    # the other end, a non-HTTP service, a hang) means "listening but not
    # identifiably ours", which is still a refusal -- never a green light.
    try:
        from urllib.request import urlopen
        with urlopen("http://{}:{}/api/ping".format(probe_host, port), timeout=timeout) as r:
            return "moonglade" if r.headers.get("X-Moonglade") else "other"
    except Exception as e:                                  # noqa: BLE001
        hdrs = getattr(e, "headers", None)                  # HTTPError IS a response
        if hdrs is not None and hdrs.get("X-Moonglade"):
            return "moonglade"
        return "other"


def main():
    ap = argparse.ArgumentParser(description="Local PixAI gallery server.")
    # default=None, not "pixai_backup": argparse cannot tell "the user typed the default"
    # from "the user typed nothing", and the managed launcher used to always pass the
    # literal default -- which made config.json's LIBRARY_DIR permanently unreachable no
    # matter what was stored in it. None is the only value that means "not specified".
    ap.add_argument("--out", default=None,
                    help="backup folder containing the catalog. Defaults to LIBRARY_DIR in "
                         "config.json (set it in the Control Panel), or pixai_backup if that "
                         "is unset. An explicit --out here always wins.")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1; use 0.0.0.0 for LAN)")
    ap.add_argument("--allow-port-reuse", action="store_true",
                    help="start even if something is already listening on --port. Off by "
                         "default because Windows lets a SECOND server bind an actively "
                         "serving port, after which requests hit either one at random.")
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
                    help="open the gallery in your default browser ~1.5s after the server "
                         "starts (manual convenience for a terminal launch; the double-click "
                         "'Serve Gallery' launcher does NOT pass this -- it polls the server "
                         "until it actually answers and opens the browser itself)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show INFO-level log lines (request activity, startup steps) on the "
                         "console too -- the log FILE under out_dir/logs/ always captures them "
                         "regardless of this flag")
    args = ap.parse_args()

    out_dir = Path(resolve_library_dir(args.out))
    import moonglade_logging
    moonglade_logging.setup_logging(out_dir, verbose=args.verbose)
    # A fresh clone has neither the (git-ignored) output folder nor a catalog -- refusing
    # to start here used to be the ONLY thing a brand-new user saw: a console exit, before
    # the web app's own first-run wizard (paste a key, run the first sync) ever had a
    # chance to render. Create the folder and an empty, schema-initialized catalog instead
    # and let the server boot; the wizard banner is what guides them from there.
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path  = out_dir / "catalog.db"
    csv_path = out_dir / "catalog.csv"

    # Auto-migrate existing catalog.csv when db is missing or empty
    if _db_is_empty(db_path) and csv_path.exists():
        print("Migrating catalog.csv → catalog.db ...")
        n = migrate_csv_to_db(csv_path, db_path)
        print("Migrated {:,} rows.".format(n))
    elif _db_is_empty(db_path):
        init_db(db_path)
        print("No catalog yet in {} -- starting anyway. "
              "Use the setup wizard on the gallery's home page, "
              "or run `python moonglade_backup.py --sync` yourself.".format(out_dir))

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

    # REFUSE to become the second server on this port -- see port_owner()'s docstring
    # for why the OS will happily let us, and what that silently costs.
    if not getattr(args, "allow_port_reuse", False):
        owner = port_owner(args.host, args.port)
        if owner:
            who = ("another Moonglade server is ALREADY serving"
                   if owner == "moonglade" else "something else is listening")
            print("\nRefusing to start: {} on port {}.\n".format(who, args.port), file=sys.stderr)
            if owner == "moonglade":
                print("  Open the one that's already running:  http://localhost:{}/\n"
                      .format(args.port), file=sys.stderr)
            print("  Find it:  netstat -ano | findstr :{}      (then: taskkill /F /PID <pid>)\n"
                  "  Or just use a different port:  --port {}\n"
                  "\n"
                  "  Starting anyway would bind a SECOND server to the same port -- Windows\n"
                  "  allows that -- and requests would land on either one at random. Pass\n"
                  "  --allow-port-reuse if you genuinely want that.\n".format(args.port, args.port + 1),
                  file=sys.stderr)
            return 2

    app = create_app(out_dir)
    url = "{}://{}:{}/".format(
        scheme, "localhost" if args.host == "0.0.0.0" else args.host, args.port)
    print("\nGallery ready ->  {}".format(url))
    if ssl_context:
        print("(self-signed HTTPS: your browser/phone will show a one-time 'proceed anyway' warning)")
    print("Press Ctrl+C to stop.\n")
    if getattr(args, "open_browser", False):
        # fire just after app.run() starts blocking (a timer thread is the only way to
        # run code after a blocking call starts)
        import threading, webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # Per-port session cookie. Browsers scope cookies by HOST ONLY -- localhost:5757 and
    # localhost:5057 share one cookie jar entry -- so two Moonglade instances with the
    # default "session" name and different secrets evict each other's login on every
    # sign-in (discovered 2026-07-29: a sandbox and the run-copy silently logged each
    # other out all evening). Naming the cookie by port lets instances coexist. Costs one
    # re-login per instance when this ships, then never again.
    app.config["SESSION_COOKIE_NAME"] = "moonglade_session_{}".format(args.port)
    # Per-port session cookie. Browsers scope cookies by HOST ONLY -- localhost:5757 and
    # localhost:5057 share one cookie jar entry -- so two Moonglade instances with the
    # default "session" name and different secrets evict each other's login on every
    # sign-in (discovered 2026-07-29: a sandbox and the run-copy silently logged each
    # other out all evening). Naming the cookie by port lets instances coexist. Costs one
    # re-login per instance when this ships, then never again.
    app.config["SESSION_COOKIE_NAME"] = "moonglade_session_{}".format(args.port)
    # Companion IPv6 loopback listener -- the fix for "the Lightbox/Details sometimes
    # load slowly" (owner report, diagnosed live 2026-08-06). Chrome resolves
    # `localhost` dual-stack and tries IPv6 ::1 FIRST; bound only to 127.0.0.1, every
    # FRESH connection burns ~300ms failing that attempt before falling back to IPv4
    # (measured: connect 312ms vs 39ms of actual server work on /api/next/detail).
    # Keep-alive reuse hides it, every new connection pays it -- hence "sometimes."
    # A second werkzeug server on [::1], same port, same app, makes the browser's
    # first attempt succeed instead. The main IPv4 bind below is UNTOUCHED (LAN via
    # --host 0.0.0.0 keeps working exactly as before); an explicit non-loopback
    # --host skips this; no IPv6 stack on the machine -> fail-soft, nothing changes.
    if args.host in ("127.0.0.1", "0.0.0.0", "localhost"):
        try:
            import threading as _threading
            from werkzeug.serving import make_server as _make_server6
            _srv6 = _make_server6("::1", args.port, app, threaded=True,
                                  ssl_context=ssl_context)
            _threading.Thread(target=_srv6.serve_forever, daemon=True,
                              name="moonglade-ipv6-loopback").start()
        except Exception:
            pass                     # IPv6 unavailable -- IPv4-only, as ever
    app.run(host=args.host, port=args.port, debug=False, threaded=True, ssl_context=ssl_context)


if __name__ == "__main__":
    # sys.exit(main()) rather than a bare main(): the port pre-flight signals refusal
    # with `return 2`, and a bare call would discard it and exit 0 -- so a wrapper
    # script would read "server started fine" from a server that refused to start.
    sys.exit(main())

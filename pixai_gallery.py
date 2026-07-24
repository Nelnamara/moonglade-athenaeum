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
import re
import secrets
import sqlite3
import sys
import threading
from pathlib import Path

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
    nsfw_scores     TEXT DEFAULT '',
    paid_credit     TEXT DEFAULT ''
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
        return ("(',' || COALESCE(collections,'') || ',') LIKE ?",
                ["%," + value + ",%"])
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
     'track': 'archive', 'rung': 1, 'rungs_total': 5,
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
     'track': 'archive', 'rung': 2, 'rungs_total': 5,
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
     'track': 'archive', 'rung': 3, 'rungs_total': 5,
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
     'track': 'archive', 'rung': 4, 'rungs_total': 5,
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
     'track': 'archive', 'rung': 5, 'rungs_total': 5,
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
     'track': 'loom', 'rung': 1, 'rungs_total': 4,
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
     'track': 'loom', 'rung': 2, 'rungs_total': 4,
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
     'track': 'loom', 'rung': 3, 'rungs_total': 4,
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
     'track': 'loom', 'rung': 4, 'rungs_total': 4,
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
     'track': 'forge', 'rung': 1, 'rungs_total': 4,
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
     'track': 'forge', 'rung': 2, 'rungs_total': 4,
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
     'track': 'forge', 'rung': 3, 'rungs_total': 4,
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
     'track': 'forge', 'rung': 4, 'rungs_total': 4,
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
     'track': 'vault', 'rung': 1, 'rungs_total': 2,
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
     'track': 'vault', 'rung': 2, 'rungs_total': 2,
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
     'track': 'menagerie', 'rung': 1, 'rungs_total': 2,
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
     'track': 'menagerie', 'rung': 2, 'rungs_total': 2,
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
     'track': 'index', 'rung': 1, 'rungs_total': 3,
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
     'track': 'index', 'rung': 2, 'rungs_total': 3,
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
     'track': 'index', 'rung': 3, 'rungs_total': 3,
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
     'track': 'gallery', 'rung': 1, 'rungs_total': 2,
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
     'track': 'gallery', 'rung': 2, 'rungs_total': 2,
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
     'track': 'restoration', 'rung': 1, 'rungs_total': 3,
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
     'track': 'restoration', 'rung': 2, 'rungs_total': 3,
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
     'track': 'restoration', 'rung': 3, 'rungs_total': 3,
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
     'track': 'sweep', 'rung': 1, 'rungs_total': 2,
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
     'track': 'sweep', 'rung': 2, 'rungs_total': 2,
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
     'track': 'vigil', 'rung': 1, 'rungs_total': 2,
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
     'track': 'vigil', 'rung': 2, 'rungs_total': 2,
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

# The 10 Evolution Ladder tracks each ladder achievement's 'track' field points at
# (see ACHIEVEMENTS' 'track'/'rung'/'rungs_total' fields, sourced from
# docs/achievements_roster_57.json's roster.tracks). Single source of truth for
# ladder display names -- the Folio of Honors' carousel/ladder-grid groups by this,
# not a second hand-maintained id->name map in the frontend.
LADDER_TRACKS = [
    {"id": "archive",     "name": "The Archive",           "metric": "images"},
    {"id": "loom",        "name": "The Loom",               "metric": "videos"},
    {"id": "forge",       "name": "The Moonforge",          "metric": "local_gens"},
    {"id": "vault",       "name": "The Stacks",             "metric": "collections"},
    {"id": "menagerie",   "name": "The Menagerie",          "metric": "models"},
    {"id": "index",       "name": "The Index",              "metric": "tagged"},
    {"id": "gallery",     "name": "The Gallery",            "metric": "published"},
    {"id": "restoration", "name": "The Restoration Wing",   "metric": "edits"},
    {"id": "sweep",       "name": "The Great Sweep",        "metric": "culled"},
    {"id": "vigil",       "name": "The Vigil",              "metric": "days_used"},
]

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


_ACH_RUNG = _build_ach_rung(ACHIEVEMENTS)


def achievement_points(a):
    """Rung-scaled score for one achievement: tier base + 5*(rung-1). Feats score
    0 by design (pure bragging-rights flair), so the points total never reveals a
    hidden feat."""
    if a.get("tier") == "feat":
        return 0
    return _TIER_POINTS.get(a.get("tier"), 0) + 5 * (_ACH_RUNG.get(a["id"], 1) - 1)


# Closed-universe set achievements -> a per-criterion checklist (WHICH members are done),
# not just an N/M count. Maps achievement id -> (telemetry set key, ordered
# [(member, label)] universe). ONLY closed sets belong here; open-ended distinct-counts
# (loras, enhance_workflows) have no finite universe and stay count-only. `video_modes`
# tracks only i2v/flf/r2v (V2V is deliberately not counted -- see the loom/generate bump).
_ACH_CRITERIA = {
    "full-toolbox":       ("tools",       [("edit", "Edit"), ("enhance", "Enhance"), ("fix", "Fix")]),
    "master-of-the-loom": ("video_modes", [("i2v", "Image (I2V)"), ("flf", "First→Last (FLF)"),
                                           ("r2v", "Reference (R2V)")]),
}


def achievement_criteria(sets):
    """For each closed-universe set achievement, which of its criteria are met. `sets` =
    telemetry.json's 'sets' block (id -> list of members). Returns
    {achievement_id: [{"key","label","done"}, ...]}. Pure + fail-soft: a missing or
    non-list set reads as 'nothing done' rather than raising."""
    out = {}
    for aid, (set_key, universe) in _ACH_CRITERIA.items():
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
    for a in ACHIEVEMENTS:
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
    return {"achievements": achs, "skins": skins, "ladders": LADDER_TRACKS, "newly": newly,
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
    badge masters are 2000px (~300 MB total); the Folio of Honors renders these thumbs so
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
    deleted_dir = out_dir / DELETED_DIRNAME
    branding_dir = out_dir / "branding"

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
        if (p.name.endswith(".part") or _under(p, gallery_dir) or _under(p, quarantine_dir)
                or _under(p, deleted_dir) or _under(p, branding_dir)):
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
    in pixai_gallery_backup.py -- so the SAME exact-match + quarantine-exclusion
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

# ---------------------------------------------------------------------------
# Global 401 guard, injected into EVERY page head (BASE_HTML and _LOOM_SHELL).
#
# Why an interceptor and not a helper at each call site: there are ~90 fetch()
# calls across pixai_gallery.py's inline JS, static/*.js and the Loom bundle, and
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
_AUTH_401_GUARD_JS = r"""<script>/* Global 401 guard -- see _AUTH_401_GUARD_JS in pixai_gallery.py */
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
# lives in loom/master-storyboard.jsx; this page loads React+Babel+picker-core from
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
   body, and this shell deliberately mounts things there -- the Activity chip and tray, the
   toast stack, the ? FAB. Without it they fell back to the browser default font while the
   gallery's BASE_HTML gave them system-ui, so the same components looked different on the
   two pages. mg-notify now also states its own family (it is host-neutral and shouldn't
   depend on this), but the shell should not be handing anything an unstyled baseline. */
body { background: var(--base); margin: 0; font-family: system-ui, sans-serif; }
/* The shared Job Tracker (static/mg-notify.js) defaults #jobs-fab/#jobs-tray to
   bottom:14px;left:14px -- fine on the gallery's own layout, but in the Loom the left Cast
   panel's own "+ add from gallery"/"Import collection" buttons live at the BOTTOM of that
   same scrollable rail. Confirmed via live measurement 2026-07-18: an open (even empty) tray
   overlaps the top ~13px of those buttons once the panel is scrolled to its end -- worse with
   real jobs in the tray (it grows up to 600px tall). Shifted up just enough to clear that
   fixed ~70px control strip. No selector scoping needed -- this whole <style> block only ever
   ships inside _LOOM_SHELL, never the gallery's own page, so it's already Loom-exclusive by
   virtue of which page includes it (#jobs-fab/#jobs-tray are siblings of #root in this shell's
   body, not descendants of anything React renders, so a .sb-root-scoped selector couldn't
   have matched them anyway -- confirmed by testing that exact approach first and finding it
   silently did nothing). Repositioning left<->right instead of shifting up was considered and
   rejected -- the Generate drawer panel on the right is equally wide (560px) and would risk
   the identical collision with ITS OWN bottom controls instead of solving anything.
   !important is deliberate, not laziness: mg-notify.js injects its own <style> via JS at
   script-load time, which lands LATER in the cascade than this static block regardless of
   source order (confirmed live -- a plain same-specificity override here was silently losing
   the tie-break), so !important is the only way to reliably win without depending on load
   timing that could shift later. */
#jobs-fab, #jobs-tray { bottom: 88px !important; }
/* Lift the Activity chip (and the ? help FAB below, inline) above LoomV2's center view.
   .lv-overlay (master-storyboard.jsx: position:fixed; inset:0; z-index:400; background:
   var(--base) -- opaque) buries them: neither #root nor its .sb-root child forms a stacking
   context, so that 400 competes in the ROOT context directly against these body-level FABs
   (mg-notify.js gives them 234/235) and wins. 401/402 floats them over the board while staying
   UNDER the modal/celebration tier that must keep covering them -- .sb-seq / .sb-pick-ov and the
   frame picker <mg-gallery-picker> (all 500), #mg-toasts (510), .ach-m2 / .m2-conf (520/521).
   Loom-only: this block ships only in _LOOM_SHELL, so the gallery's own #jobs-fab keeps 234.
   !important for the same mg-notify.js cascade-timing reason as the bottom rule above. Known
   residual (z-only can't fix it): Deep Focus's .lv-df-veil (450) and the nested 600 preview
   flyouts render INSIDE .lv-overlay, so from the root they're part of the single 400 atom and
   these corner FABs paint over them -- cosmetic only; the real fix hoists those overlays to
   .sb-root level (owner-visible refactor, deferred). */
#jobs-fab  { z-index: 401 !important; }
#jobs-tray { z-index: 402 !important; }

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
__BABEL_LIB_TAG__
<script src="/static/picker-core.js"></script>
<script src="/static/mg-model-picker.js"></script>
<script src="/static/mg-gallery-picker.js"></script>
<!-- Before the drawer, deliberately: <mg-generate-drawer>'s cost line IS <mg-cost-badge> as of
     the consolidation, so the Loom's Video tab needs this file for a shot's cost to render at
     all. Same pairing the gallery shell above documents at length. -->
<script src="/static/mg-cost-badge.js"></script>
<script src="/static/mg-generate-drawer.js"></script>
<script src="/static/mg-notify.js"></script>
</head><body>
<div id="root"></div>
<div id="jobs-fab" onclick="JobsCard.open()" title="Activity"><span class="jf-dot"></span><span class="jf-badge" id="jobs-fab-badge"></span><span>Activity</span></div>
<div id="jobs-tray" aria-label="Job activity"></div>
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
    <p style="color:var(--subtext);">Full manual: <code>docs/LOOM.md</code> in the repo.</p>
  </div>
</div>
</body></html>"""

# Two delivery paths for the same master-storyboard.jsx, sharing everything except
# the runtime-script block (Phase 1 tooling pass, 2026-07-16):
#
#   LOOM_PAGE        -- DEFAULT. Loads babel.min.js and transpiles master-storyboard.jsx
#                       (+ loom/src/loom-core.js, inlined ahead of it) client-side, as
#                       it always has. This is the trusted fallback; it is NOT being
#                       removed or downgraded by the new path below.
#   LOOM_PAGE_BUNDLE -- NEW, opt-in via /loom?bundle=1. Loads the pre-transpiled
#                       loom/dist/master-storyboard.bundle.js (built by
#                       `npm run build` in loom/, via esbuild) instead -- no Babel,
#                       no client-side transpile. Only served if that file actually
#                       exists on disk (see loom() below); otherwise /loom?bundle=1
#                       silently falls back to LOOM_PAGE so a not-yet-built checkout
#                       never breaks.
LOOM_PAGE = (_LOOM_SHELL
    .replace("__BABEL_LIB_TAG__", '<script src="/loom/vendor/babel.min.js"></script>')
    .replace("__RUNTIME_SCRIPT_BLOCK__",
             '<script type="text/babel" data-presets="react">\n'
             'const { useState, useEffect, useRef, useCallback, useMemo } = React;\n'
             '__JSX__\n'
             'ReactDOM.createRoot(document.getElementById("root")).render(<App />);\n'
             '</script>')
    .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS))

LOOM_PAGE_BUNDLE = (_LOOM_SHELL
    .replace("__BABEL_LIB_TAG__", "")   # pre-transpiled bundle -- no Babel needed
    .replace("__RUNTIME_SCRIPT_BLOCK__",
             '<script src="/loom/dist/master-storyboard.bundle.js"></script>\n'
             '<script>ReactDOM.createRoot(document.getElementById("root"))'
             '.render(React.createElement(LoomBundle.default));</script>')
    .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS))


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
            stderr=subprocess.DEVNULL, timeout=4,
            creationflags=_NO_WINDOW).decode().strip()
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


def _account_key(username):
    """Filesystem-safe, case-COLLISION-safe key for `username` -- the ONE shared
    helper every per-account store (saved views, prompt snippets, Loom storyboards,
    toolbox presets) keys its own file/directory with (B14 residual).

    Account identity in this app is case-SENSITIVE: pixai_gallery_backup.py's
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


def create_app(out_dir: Path):
    app = Flask(__name__)

    # ---- Session-based auth: secret key + cookie hardening ------------------
    # AUTH_SECRET_KEY is generated once (secrets.token_hex(32)) and persisted to
    # config.json by get_or_create_secret_key() -- reused on every subsequent start
    # so restarting the server doesn't silently log everyone out. See
    # _is_authorized_request() below for the gate this session backs, and
    # /login /logout for the routes that populate it.
    import pixai_gallery_backup as _core_auth
    app.secret_key = _core_auth.get_or_create_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS can never read the session cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site POST/nav CSRF vectors
    # SESSION_COOKIE_SECURE is deliberately left False: this app is typically served
    # over plain HTTP on a LAN (`python pixai_gallery.py`, no TLS terminator). A Secure
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

    # Redacts THIS MACHINE's own filesystem paths out of an exception message before
    # it's stored or served to any LOGIN-tier caller (any signed-in LAN account, not
    # just the owner) -- str(e) on a file-not-found, permission, or upstream-API error
    # routinely embeds an absolute path, which routinely embeds the OS username.
    #
    # Literal-PREFIX replacement, NOT a regex. An earlier attempt (2026-07-21, docs/
    # AUDIT_2026-07-21.md's S3) used a regex (`[^\s'"<>\|]*`) that stopped matching at
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
        if not msg:
            return msg
        import tempfile
        # str(out_dir) resolved -- --out defaults to a relative "pixai_backup", and
        # main() never resolves it before create_app(out_dir). Unresolved, a caller who
        # started the server with (say) --out . would make out_dir's candidate a bare
        # ".", which then matches -- and redacts -- every single period in every error
        # message this function ever touches app-wide (found in adversarial review,
        # reproduced: an ordinary "retry in 0.5s" style message came back full of
        # "<host-path>" fragments). Resolving turns it into the same kind of real,
        # multi-component absolute path the other 4 candidates already are.
        candidates = [str(Path(out_dir).resolve()), os.path.expanduser("~"),
                     tempfile.gettempdir(), sys.prefix, os.getcwd()]
        seen, out = set(), str(msg)
        for path in sorted(set(candidates), key=len, reverse=True):
            # The length floor is a second, independent guard against the same class of
            # bug for candidates this function doesn't control the construction of --
            # no real absolute path on any real OS is this short, so it never rejects a
            # genuine candidate, only a degenerate one.
            if not path or len(path) < 4 or path in seen:
                continue
            seen.add(path)
            if path in out:
                out = out.replace(path, "<host-path>")
        return out

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
    # subprocess (isolation from the Flask process + natural stdout capture, so
    # the unmodified CLI script's own print output streams straight to the
    # Jobs card) with cwd = the checkout dir (where config.json lives).
    # ------------------------------------------------------------------
    _cli_path = str(Path(__file__).resolve().parent / "pixai_gallery_backup.py")
    _cli_dir = str(Path(__file__).resolve().parent)
    # catalog media_id -> upload-kind media_id, for references sent from the gallery.
    # PixAI refuses a generation-output id as an input (see resolve_img), so each
    # referenced image is uploaded once and reused. Process-lifetime only and
    # deliberately unbounded-but-tiny: one short string pair per image the owner has
    # ever referenced this run. Losing it on restart just re-uploads, which is free.
    _ref_upload_cache = {}

    _panel_lock = threading.Lock()
    _panel_job = {"status": "idle", "action": "", "label": "", "lines": [],
                  "rc": None, "started_at": None, "progress": None,
                  "proc": None, "cancelled": False, "warn_count": 0}
    _PROG_PREFIX = "~=MGPROG=~"        # matches PANEL_PROGRESS_PREFIX in pixai_gallery_backup.py
    _WARN_PREFIX = "~=MGWARN=~"        # matches PANEL_WARN_PREFIX in pixai_gallery_backup.py (D-4)
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
        # The "full audit" checkbox in the UI does NOT append a flag to the action above --
        # it selects this separate whitelisted entry. Same for dedup-delete below. Keeping
        # the client to a fixed set of action KEYS is what preserves the property the
        # whole runner is built on (see _panel_run: "a WHITELISTED argv, never an
        # arbitrary command"); letting a checkbox contribute argv would erode it.
        "audit-full":    {"args": ["--audit"], "label": "Duplicate audit (full — byte-compare, slower)", "destructive": False},
        "verify-dupes":  {"args": ["--verify-dupes"],
                          "label": "Verify _duplicates/ is safe to delete", "destructive": False},
        "rebuild-similar": {"args": ["--rebuild-similar"],
                            "label": "Rebuild the Similar index (slow, needs pixeltable)",
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
            _log_job(jid, status=("failed" if status == "failed" else
                                  "done_with_errors" if status == "done_with_errors" else "done"),
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
        proc = subprocess.Popen(argv, cwd=_cli_dir, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                encoding="utf-8", errors="replace", env=env,
                                creationflags=_NO_WINDOW)
        import uuid
        job_id = "panel-" + uuid.uuid4().hex[:12]
        with _panel_lock:
            _panel_job.update(status="running", action=action, label=spec["label"],
                              lines=["$ " + " ".join(action_args)], rc=None,
                              started_at=None, progress=None, proc=proc, cancelled=False,
                              job_id=job_id, warn_count=0)
        _log_job(job_id, status="running", type="panel", label=spec["label"])
        threading.Thread(target=_panel_reader, args=(proc,), daemon=True).start()

    # ---- Automated tasks: run a SAFE job on an interval while the app is open ----
    # Persisted to out_dir/schedule.json. Only non-destructive actions are schedulable.
    # An in-process daemon: fires while the gallery is running (it is NOT an OS-level
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
                        or PANEL_ACTIONS[action]["destructive"] \
                        or PANEL_ACTIONS[action].get("advanced"):
                    # advanced actions are manual-run only (a full re-walk on a timer is a
                    # foot-gun; test-pull needs an N the scheduler can't supply) -- backstop
                    # to the dropdown already hiding them, in case an old schedule names one.
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

    def _watch_mirror(tid):
        """Download + catalog one finished task off the watcher's event loop (own
        session per call, matching the CLI's --watch-backup pattern)."""
        import pixai_gallery_backup as core
        try:
            session = core._make_session(None)
            _collect_single_flight(core, session, tid)
            with _watch_lock:
                _watch_status["mirrored"] += 1
        except Exception as e:
            with _watch_lock:
                _watch_status["last_error"] = _redact_host_paths(str(e))[:200]

    # The closures above are unreachable from outside create_app; the test suite
    # drives the watcher-mirror path through this seam (conftest disables the real
    # watcher thread via MOONGLADE_DISABLE_WATCH).
    app.extensions["mg_watch_mirror"] = _watch_mirror

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
            # ["phase"], not the whole dict: resolve_orphan_jobs compares this return
            # against ("done","failed"), and generation_status returns
            # {status, phase, paid_credit}. Passing the dict straight through meant the
            # comparison never matched, so the reaper resolved NOTHING -- it just
            # returned 0 forever while looking healthy. The unit tests stubbed status_fn
            # with the documented string, so nothing caught the caller disagreeing.
            return core.generation_status(box["s"], tid)["phase"]
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
                    _watch_status["last_error"] = _redact_host_paths(str(e))[:200]
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
<script>/* apply saved skin before first paint (no FOUC) */try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}</script>""" + _AUTH_401_GUARD_JS + r"""
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
  .gen-nel-wrap{position:relative;display:inline-block;width:34px;height:34px;margin-right:6px;vertical-align:middle;flex:none;}
  .gen-nel{position:absolute;inset:5px;width:24px;height:24px;border-radius:50%;object-fit:cover;object-position:60% 32%;animation:gen-spin 1.6s linear infinite;}
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
  /* ---- BASE rules for the header nav, the LAN badge and the setup wizard ----
     These eleven were sitting INSIDE the @media (max-width: 680px) block below,
     so they applied ONLY on narrow viewports and were entirely absent on desktop
     -- exactly inverted. The indentation gave it away: the media query's own
     rules are at 4 spaces, this block was at 2, and .filter-toggle resumed at 4.
     Real consequences, all confirmed by rendering the page at both widths:
       - the first-run setup wizard (the FIRST thing a new user sees) had no
         card, no gold rule, and raw white browser inputs on a near-black page
       - the Panel's Add-user form rendered the same three raw white inputs
       - .setup-msg.err lost `color: var(--red)`, so "Invalid username or
         password" and the rate-limit lockout notice rendered in ordinary body
         text, visually identical to the instructions above them
       - .setup-row input's `flex: 1 1 320px` is a HORIZONTAL basis; in a
         column-direction container it becomes a 320px HEIGHT, so inputs
         rendered ~8x too tall on phones
     Found by a browser crawl that looked at screenshots. No test caught it:
     every response was a correct 200 and no console error ever fired. */
  .head-nav { margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
  .lan-note { font-size: 11.5px; color: var(--overlay0); font-style: italic; padding: 5px 10px; border: 1px dashed var(--surface1); border-radius: 7px; }
  .setup-wizard { margin: 10px 14px 0; }
  .setup-step { background: var(--surface0); border: 1px solid var(--surface1); border-left: 3px solid var(--gold); border-radius: 10px; padding: 14px 18px; color: var(--text); font-size: 13.5px; line-height: 1.5; }
  .setup-step a { color: var(--accent); }
  .setup-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .setup-row input { flex: 1 1 320px; min-width: 220px; background: var(--surface0); color: var(--text); border: 1px solid var(--surface1); border-radius: 6px; padding: 7px 10px; font-size: 13px; }
  .setup-row input:focus { outline: none; border-color: var(--accent); }
  .setup-msg { display: inline-block; margin-top: 8px; font-size: 12.5px; }
  .setup-msg.err { color: var(--red); }
  .setup-msg.ok { color: var(--green); }
  /* Mobile: collapse the filter bar behind a toggle so the grid leads. */
  @media (max-width: 680px) {
    header h1 { font-size: 16px; }
    header.bannered { padding: 0 14px 10px; }
    header .back-link { font-size: 12px; }
    /* A column-direction container turns .setup-row input's 320px flex-basis
       into a height. Reset the basis here so narrow viewports stack normally. */
    .setup-row { flex-direction: column; align-items: stretch; }
    .setup-row input { flex: 0 0 auto; min-width: 0; width: 100%; box-sizing: border-box; }
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
    /* The Loom is a dense multi-panel desktop/tablet tool -- not viable on a phone screen.
       Hidden here (phone-only breakpoint), stays visible at 481px+ incl. the tablet range. */
    .head-nav .b-loom { display: none; }

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
    #gen-drawer, #gen-drawer.wide, #gen-drawer.dock-left { width: 100%; max-width: 100vw; }
    #model-flyout, #gen-drawer.dock-left #model-flyout,
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

    /* FILTERS as a bottom sheet: on a phone the inline expand swallows most of the
       viewport, so small screens get a slide-up sheet instead. Reuses the existing
       toggleFilters() + .open class unchanged -- only what .open MEANS visually changes. */
    .filters { display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 220;
      max-height: 78vh; overflow-y: auto; background: var(--mantle); border-top: 1px solid var(--surface1);
      border-radius: 16px 16px 0 0; box-shadow: 0 -14px 40px rgba(0,0,0,.5);
      transform: translateY(100%); visibility: hidden; transition: transform .25s ease, visibility 0s linear .25s; }
    .filters.open { transform: translateY(0); visibility: visible; transition: transform .25s ease; }
    .filter-scrim { position: fixed; inset: 0; z-index: 219; background: rgba(0,0,0,.55);
      opacity: 0; pointer-events: none; transition: opacity .25s ease; }
    .filters.open ~ .filter-scrim { opacity: 1; pointer-events: auto; }
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
  /* All dropdowns share the button look: dark, rounded, custom lavender-grey caret.
     .pick-filters select (the gallery-picker modal's collection/source/rating/sort
     dropdowns) had NO styling at all until it joined this list -- the other half of the
     same native-select-styling-split audit row that gave .gen-sel's <select>s their arrow
     back, just above; there was never a comment anywhere suggesting either gap was
     deliberate. */
  .filters select, #preset-select, select.p-sel, .pick-filters select { -webkit-appearance: none; appearance: none;
    background-color: var(--surface0);
    background-image: url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="10" height="6"%3E%3Cpath d="M0 0l5 6 5-6z" fill="%239a93ab"/%3E%3C/svg%3E');
    background-repeat: no-repeat; background-position: right 10px center;
    border: 1px solid var(--surface1); border-radius: 7px; color: var(--text);
    padding: 6px 28px 6px 12px; font-size: 13px; cursor: pointer; font-family: inherit; }
  .filters select:hover, #preset-select:hover, select.p-sel:hover, .pick-filters select:hover { border-color: var(--lavender); }

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
  /* Clearance for the persistent Activity chip (#jobs-fab, static/mg-notify.js): it's
     position:fixed at left:14px;bottom:14px, and JobsCard.applyState() shows it via .show
     whenever the tray is CLOSED -- which is the default (mg_jobs_open unset), so on every
     ordinary page load it sits on top of the grid's bottom-left corner with no clearance at
     all, permanently eating clicks for whatever card scrolls under it -- not just while a
     job is actually running (audit row: "the dead zone is permanent, not intermittent").
     No page-side rule ever gave the grid room for it (unlike the Loom shell just above,
     which budgets the same 56px-ish FAB footprint + breathing room for its OWN #eb-help-btn
     via #root .lv-gen{padding-bottom:64px}). This is the last `.grid` rule in the sheet
     (deliberately -- see the mobile/portrait overrides above it), so it applies at every
     breakpoint without touching their own padding/gap values. The FAB keeps showing (that
     part is an intentional persistent entry point, not the bug); the grid just stops
     rendering content underneath it. */
  .grid { padding-bottom: 64px; }
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
  /* Panoramic sources (progress-bar/frame textures, letterboxed banners...) lose almost all
     their content to a square center-crop -- show those uncropped instead, letterboxed. */
  .card img.wide-thumb { object-fit: contain; }
  .card .no-thumb { width: 100%; aspect-ratio: 1; background: var(--surface0); display: flex; align-items: center; justify-content: center; color: var(--overlay0); font-size: 11px; }
  .card .meta { padding: 6px 8px; }
  .card .meta .title { font-size: 12px; color: var(--text); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .meta .model { font-size: 11px; color: var(--mauve); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .meta .date  { font-size: 10px; color: var(--overlay0); }
  /* Privacy blur (opt-in toggle): blur every thumbnail until hover. Useful on
     LAN / mobile / over-the-shoulder. NSFW-flagged cards (data-nsfw="1") blur
     more heavily when the flag is known. Audit 2026-07-21 S5: .pick-cell (the gallery
     Picker's own grid, .pick-modal below) never carried ANY of this -- picking an
     image painted the whole catalog unblurred regardless of Privacy Blur. Same two
     rules, same selector shape, just a second class. */
  body.privacy-blur .card img, body.privacy-blur .pick-cell img, body.privacy-blur #gen-ref-slot img { filter: blur(16px); transition: filter .12s; }
  body.privacy-blur .card[data-nsfw="1"] img, body.privacy-blur .pick-cell[data-nsfw="1"] img, body.privacy-blur #gen-ref-slot[data-nsfw="1"] img { filter: blur(28px); }
  body.privacy-blur .card:hover img, body.privacy-blur .pick-cell:hover img, body.privacy-blur #gen-ref-slot:hover img { filter: none; }
  .card .cb-wrap { position: absolute; top: 6px; left: 6px; }
  /* --accent, not --lavender: the two are the same colour in the default skin, so this
     read as correct, but a skin that retints --accent (nightfallen: #a678f0 vs a
     --lavender of #c9a6ff) left these grid checkboxes on the old skin's purple. The
     :root accent-color would already cover this -- the rule is kept only for the
     18px sizing -- so it must not pin a colour that drifts from the active skin. */
  .card .cb-wrap input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }
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
<div class="modal-bg" id="export-modal">
  <div class="modal">
    <h2 style="color:var(--text);">Download <span id="export-n"></span></h2>
    <p>Files download exactly as PixAI delivered them by default. Converting or embedding
       happens <b>only in this download</b> &mdash; your archive and catalog are never changed.</p>
    <div style="display:flex;flex-direction:column;gap:13px;margin-bottom:18px;">
      <label style="display:flex;flex-direction:column;gap:5px;font-size:11px;color:var(--overlay0);text-transform:uppercase;letter-spacing:.05em;">Format
        <select id="export-fmt" class="gen-sel" style="text-transform:none;letter-spacing:0;">
          <option value="original" selected>Original &mdash; no re-compression</option>
          <option value="png">PNG</option>
          <option value="jpeg">JPEG</option>
        </select></label>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text);cursor:pointer;">
        <input type="checkbox" id="export-embed"> Embed prompt &amp; ids into each file
        <span style="color:var(--overlay0);font-size:11px;">(PNG/JPEG)</span></label>
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="document.getElementById('export-modal').classList.remove('open')">Cancel</button>
      <button class="btn btn-primary" onclick="doExportDownload()">&#8681; Download</button>
    </div>
  </div>
</div>
<div class="modal-bg" id="import-modal">
  <div class="modal imp-modal">
    <h2 style="color:var(--text);margin-bottom:4px;">Import into your library</h2>
    <p style="margin-bottom:14px;">Bring local files into the catalog &mdash; copied into <b style="color:var(--text)">imported/</b> and tagged <b style="color:var(--text)">Imported (local)</b>. Nothing is uploaded to PixAI; this is your library, not a generation reference.</p>
    <div id="imp-drop" class="imp-drop" onclick="ImportUI.browse()">
      <div class="imp-ico">&#8593;</div>
      <div class="imp-big">Drop images, a folder, or a .zip here</div>
      <div class="imp-sub">or <span class="imp-link">browse files</span> &middot; <span class="imp-link" onclick="event.stopPropagation();ImportUI.browseFolder()">a folder</span></div>
    </div>
    <div id="imp-preview" style="display:none;">
      <div class="imp-sum" id="imp-sum"></div>
      <div id="imp-body"></div>
      <label class="imp-orow"><span class="imp-lbl">Add to collection</span>
        <select id="imp-collection" class="gen-sel" style="flex:1;" onchange="ImportUI.onCollectionChange()">
          <option value="">&mdash; none &mdash;</option>
          {% for c in collections %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
          <option value="__new__">&#65291; New collection&hellip;</option>
        </select></label>
      {# A collection is just a name applied to rows (add_to_collection), so an unseen name
         creates one -- this row is purely the way in, which the dropdown alone never gave.
         Reuses .gen-sel: it is a box style (background/border/radius/padding/font), not a
         select-specific one, so it dresses the input identically with no new CSS. #}
      <label class="imp-orow" id="imp-newcoll-row" style="display:none;">
        <span class="imp-lbl">New collection</span>
        <input id="imp-newcoll" class="gen-sel" style="flex:1;" maxlength="120"
               placeholder="name it &mdash; it&rsquo;s created when the import lands"></label>
    </div>
    <div id="imp-result" class="imp-result" style="display:none;"></div>
    <div class="modal-actions" style="margin-top:16px;">
      <button class="btn" onclick="ImportUI.close()">Cancel</button>
      <button class="btn btn-primary" id="imp-go" onclick="ImportUI.doImport()" style="display:none;">&#8593; Import</button>
    </div>
    <input type="file" id="imp-file" multiple accept="image/*,video/*,.zip" style="display:none" onchange="ImportUI.onPick(this.files)">
    <input type="file" id="imp-folder" webkitdirectory style="display:none" onchange="ImportUI.onPick(this.files)">
  </div>
</div>
<style>
  .imp-modal{max-width:560px;width:92%;}
  .imp-drop{border:2px dashed var(--surface1);border-radius:12px;padding:38px 20px;text-align:center;background:var(--surface0);cursor:pointer;transition:border-color .15s,background .15s;}
  .imp-drop.hot{border-color:var(--lavender);background:color-mix(in srgb,var(--lavender) 8%,var(--surface0));}
  .imp-ico{font-size:30px;color:var(--lavender);line-height:1;}
  .imp-big{font-size:14px;font-weight:600;margin:10px 0 3px;color:var(--text);}
  .imp-sub{font-size:12.5px;color:var(--subtext);}
  .imp-link{color:var(--lavender);text-decoration:underline;cursor:pointer;}
  .imp-sum{font-size:12.5px;color:var(--subtext);margin-bottom:10px;}
  .imp-sum b{color:var(--text);}
  .imp-list{display:flex;flex-direction:column;gap:6px;max-height:240px;overflow-y:auto;padding-right:2px;}
  .imp-row{display:flex;align-items:center;gap:9px;background:var(--surface0);border:1px solid var(--surface1);border-radius:8px;padding:6px 8px;}
  .imp-thumb{width:38px;height:38px;border-radius:5px;flex:none;background:var(--surface1);display:grid;place-items:center;font-size:15px;color:var(--subtext);overflow:hidden;}
  .imp-thumb img{width:100%;height:100%;object-fit:cover;}
  .imp-nm{flex:1;min-width:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text);}
  .imp-sz{font-size:10.5px;color:var(--subtext);flex:none;}
  .imp-x{background:none;border:none;color:var(--subtext);cursor:pointer;font-size:15px;line-height:1;flex:none;padding:0 2px;}
  .imp-x:hover{color:var(--red);}
  .imp-cap{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--gold);background:color-mix(in srgb,var(--gold) 8%,transparent);border:1px solid var(--gold);border-radius:8px;padding:6px 9px;margin-bottom:9px;line-height:1.4;}
  .imp-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:5px;}
  .imp-tg{aspect-ratio:1;border-radius:5px;overflow:hidden;background:var(--surface1);display:grid;place-items:center;font-size:13px;color:var(--subtext);}
  .imp-tg img{width:100%;height:100%;object-fit:cover;}
  .imp-more{aspect-ratio:1;border-radius:5px;border:1px dashed var(--surface1);background:var(--surface0);display:grid;place-items:center;text-align:center;color:var(--subtext);font-size:10px;font-weight:600;line-height:1.1;}
  .imp-orow{display:flex;align-items:center;gap:9px;margin-top:13px;}
  .imp-lbl{font-size:11px;color:var(--overlay0);text-transform:uppercase;letter-spacing:.05em;white-space:nowrap;}
  .imp-result{margin-top:12px;font-size:12.5px;padding:9px 11px;border-radius:8px;background:var(--surface0);border:1px solid var(--surface1);color:var(--text);line-height:1.5;}
  .imp-result.ok{border-color:var(--emerald);}
  .imp-result.err{border-color:var(--red);color:var(--red);}
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
  {# 70px, not 64: at 64 the "Mon" placeholder collided with the native dropdown
     arrow and rendered as "Mo|" -- measured intrinsic width is 69px. The year
     select beside it is 78px against a 71px intrinsic, so it was never affected. #}
  <select name="{{ prefix }}_month" style="width:70px">
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
    {# Owner-level surfaces (generation, The Loom, Panel, balance) are gated to
       _is_authorized_request() -- a logged-in session ONLY, no localhost bypass
       (see /login and that function's docstring). Hide them for anyone else and
       show a small read-only note instead of dead buttons. Browse/curate +
       community stay available to everyone.
       Import is the one documented exception inside this same gate: it renders for
       every LOGIN-tier session right alongside Generate/The Loom, but
       /api/import-local (below) is actually LOCALHOST-tier -- it writes files onto
       the server's own machine, so it re-checks _is_local_request() itself. A
       signed-in, non-local LAN session therefore sees a working-looking Import
       button that always 403s when clicked. Not a security hole (the real gate is
       correct and server-side) -- just a UX wart; gating the button's own
       visibility on the real local check instead of this blanket flag is a
       follow-up left to the owner, not done here. #}
    {% if is_local %}
    <a id="acct-chip" class="acct-chip" href="{{ url_for('panel') }}" title="Your PixAI balance — open the Control Panel" style="display:none;"></a>
    <button type="button" id="acct-claim" class="acct-claim" onclick="Acct.claim()" title="Claim your free daily credits" style="display:none;"></button>
    <button type="button" class="btn btn-primary" onclick="Gen.open()">&#10022; Generate</button>
    <button type="button" class="btn" onclick="ImportUI.open()" title="Import local files (images, a folder, or a .zip) into your library">&#8593; Import</button>
    <a class="btn b-loom" href="/loom" title="The Loom — video storyboard, where shots are woven into a sequence">&#9648; The Loom</a>
    {% endif %}
    <button type="button" class="btn b-ach" onclick="Ach.open()" title="Achievements &amp; skins">&#127942;</button>
    <button type="button" class="btn b-contest" onclick="Contests.open()" title="Live PixAI contests &mdash; the Oasis was never a 1-player game">&#127941; Contests</button>
    <button type="button" class="btn b-art" onclick="YourArt.open()" title="How your published art is doing &mdash; views, likes, comments">&#128200; My Art</button>
    {% if is_local %}
    <a class="btn b-panel" href="{{ url_for('panel') }}" title="Maintenance jobs, logs, settings">&#9881; Panel</a>
    {% else %}
    <span class="lan-note" title="Creation &amp; maintenance tools live on the owner's machine, or need you to sign in.">&#128065; read-only LAN view</span>
    {% endif %}
    <a class="btn b-health" href="{{ url_for('health') }}" title="Collection health dashboard">&#9825; Health</a>
    {% if logged_in_user %}
    {# A POST form, not an <a href>: /logout revokes every outstanding session for
       this account, and a bare GET that writes server state is reachable by any
       cross-site link, window.open or link-prefetcher -- SESSION_COOKIE_SAMESITE=
       "Lax" blocks a cross-site subresource but still sends the cookie on a
       top-level GET navigation. Same hidden-csrf-field convention /login's form
       uses. No styling needed: `* { margin: 0; padding: 0 }` (the reset near the
       top of BASE_HTML) means the form adds nothing, `.head-nav > *` already gives
       it the same flex treatment as its sibling buttons, and the .btn inside it is
       a plain <button class="btn"> exactly like Generate/Import/Contests. #}
    <form method="post" action="{{ url_for('logout') }}">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <button type="submit" class="btn" title="Signed in as {{ logged_in_user }} — sign out (on every device)">&#128274; Sign out</button>
    </form>
    {% endif %}
  </div>
</header>

{% if needs_key %}
<div class="setup-wizard" id="setup-wizard">
  <div class="setup-step">
    <b>Welcome to Moonglade Athenaeum.</b> Paste your PixAI API key to get started —
    <a href="https://platform.pixai.art" target="_blank" rel="noopener">generate one at platform.pixai.art</a>
    (free, lifetime up to ~2 years). Nothing else is required; your account id and everything
    else is resolved from it.
    <div class="setup-row">
      <input type="password" id="setup-key-input" placeholder="Your PixAI API key"
             autocomplete="off" onkeydown="if(event.key==='Enter')Setup.saveKey()">
      <button type="button" class="btn btn-primary" onclick="Setup.saveKey()">Connect</button>
    </div>
    <span id="setup-key-msg" class="setup-msg"></span>
  </div>
</div>
{% elif catalog_empty %}
<div class="setup-wizard" id="setup-wizard">
  <div class="setup-step">
    <b>You're connected.</b> Run your first sync to pull your PixAI generation history into
    this gallery — full resolution, searchable, yours to keep.
    <div class="setup-row">
      <button type="button" class="btn btn-primary" onclick="Setup.firstSync()">&#8635; Sync now</button>
    </div>
    <span id="setup-sync-msg" class="setup-msg"></span>
  </div>
</div>
{% endif %}

<button type="button" class="filter-toggle btn" onclick="toggleFilters()"
        aria-expanded="false">Filters &#9662;</button>
<form method="get" action="/" id="filter-form">
{% set adv_active = model_filter or lora_filter or date_from or date_to or batch_filter or rating_min or art_tag or source_filter or published_only %}
<div class="filters">
  <div class="f-grow">
    <label>Search prompt / task or media id</label><br>
    <input type="text" name="q" value="{{ q }}" placeholder="words, night* wildcard, an id, or model:tsubaki…"
           title="Multiple words are ANDed. Use * (any) and ? (one char), e.g. night* elf. Also matches task id / media id. Field operators: model: lora: tag: title: sampler: negative: batch: status: filename: collection: source: seed: task: media: — plus numbers (rating:>=3, width:>1000, aes:>6, likes:>0, steps: cfg: duration:), created:2026-07 dates, and video:/published:/nsfw: 1 or 0. Quote spaces: model:&quot;Ether Real&quot;.">
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
    {# Shown only while a collection is active. type=button so it never submits the filter
       form; the name rides a data attribute (HTML-escaped, decoded via dataset) so a
       collection name with quotes can't break the handler. #}
    {% if collection %}
    <button type="button" class="btn" style="margin-top:6px;font-size:12px;padding:5px 10px;"
      data-coll="{{ collection }}" onclick="downloadCollection(this.dataset.coll)"
      title="Download every item in this collection as a ZIP (optional convert/embed)">&#8681; Download collection</button>
    <button type="button" class="btn" style="margin-top:6px;font-size:12px;padding:5px 10px;"
      data-coll="{{ collection }}" onclick="contactSheetCollection(this.dataset.coll)"
      title="Open a printable contact sheet for every item in this collection">&#128424; Contact sheet</button>
    {% endif %}
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
<div class="filter-scrim" onclick="toggleFilters()"></div>
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
  <a class="clear-all" href="{{ url_for('export_csv_download') }}?{{ request.query_string.decode('utf-8', 'replace') }}" download
    title="Export exactly these filtered rows to CSV -- the whole-catalog dump stays on the Control Panel">&#11015; Export this view (CSV)</a>
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
{% if request.args.get('uncollected') %}
<div style="margin:8px 20px 0;padding:8px 12px;background:var(--mantle);border-left:3px solid var(--emerald, #4fc99a);border-radius:4px;color:var(--text);font-size:13px;">
  Removed {{ request.args.get('uncollected') }} item(s) from the collection. Files are untouched.</div>
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
      {# Only meaningful while a collection filter is active -- "remove from WHICH one?"
         has no answer otherwise. Same conditional shape as the "Download collection"
         button in the filter bar, and the name rides a data attribute (HTML-escaped,
         read back via dataset) so a name with quotes can't break the handler. #}
      {% if collection %}
      <button data-coll="{{ collection }}" onclick="bulkRemoveCollection(this.dataset.coll);closeActionsMenu()"
              title="Take the selected items out of this collection (a label only -- no files are deleted)">&#8722; Remove from &ldquo;{{ collection }}&rdquo;</button>
      {% endif %}
      <button onclick="bulkSendVideo();closeActionsMenu()">&#9654; Send to Video</button>
      <button onclick="bulkSendCast();closeActionsMenu()">&#9648; Send to The Loom (cast)</button>
      <button onclick="bulkContactSheet();closeActionsMenu()">&#128424; Print sheet</button>
      <button onclick="downloadZip();closeActionsMenu()">&#8681; Download ZIP</button>
      <button onclick="bulkReplacePrompt();closeActionsMenu()">Find / replace in prompts</button>
      <div class="am-div"></div>
      <button class="am-danger" onclick="confirmBulkDelete();closeActionsMenu()" title="Remove from this local catalog only (keeps the cloud task)">Delete locally</button>
      {% if can_delete_cloud %}
      <button class="am-danger" onclick="confirmBulkDeleteCloud();closeActionsMenu()" title="Delete the whole TASK from your PixAI account AND locally (irreversible)">Delete from PixAI</button>
      {% endif %}
    </div>
  </div>
  <!-- View controls (right) -->
  <div class="bulk-grp bulk-view">
    <button class="btn" id="blur-btn" onclick="toggleBlur()" title="Privacy blur: blur all thumbnails until you hover">Privacy blur</button>
    <select id="preset-select" onchange="loadPreset(this.value)" style="font-size:13px;"
            title="Saved views"><option value="">Saved views…</option></select>
    <button class="btn" onclick="deletePreset()" title="Delete the selected saved view"
            style="padding:6px 10px;">&#10005;</button>
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
           decoding="async" onload="this.classList.add('loaded');var r=this.naturalWidth/(this.naturalHeight||1);if(r>2.2||r<0.45)this.classList.add('wide-thumb')"
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
// Saved views live SERVER-SIDE (/api/view-presets -> out_dir/view_presets/<account>.json)
// so a view saved at the desktop exists on the tablet. Scoped to YOUR account, not the
// install: a saved view is a stored search, not a theme. localStorage ('gallery_presets')
// is only read once as the legacy store: any set found there is merged up (existing names
// win) and then cleared.
var viewPresets = {};
function legacyPresetsGet() { try { return JSON.parse(localStorage.getItem('gallery_presets') || '{}'); } catch(e) { return {}; } }
function renderPresets() {
  var s = document.getElementById('preset-select'); if (!s) return;
  s.innerHTML = '<option value="">Saved views…</option>';
  Object.keys(viewPresets).sort().forEach(function(n){ var o = document.createElement('option'); o.value = n; o.textContent = n; s.appendChild(o); });
}
function refreshPresets() {
  fetch('/api/view-presets').then(function(r){ return r.json(); }).then(function(d) {
    viewPresets = (d && d.presets) || {};
    var legacy = legacyPresetsGet();
    if (Object.keys(legacy).length) {
      fetch('/api/view-presets', { method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({merge: legacy}) })
        .then(function(r){ return r.json(); }).then(function(d2) {
          if (d2 && d2.presets) viewPresets = d2.presets;
          try { localStorage.removeItem('gallery_presets'); } catch(e) {}
          renderPresets();
        }).catch(function(){});
    }
    renderPresets();
  }).catch(function(){ renderPresets(); });
}
function savePreset() {
  var n = prompt('Name this view (the current filters):'); if (!n) return;
  fetch('/api/view-presets', { method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: n, query: location.search || '?'}) })
    .then(function(r){ return r.json(); }).then(function(d) {
      // Used to silently no-op on a server rejection (e.g. a >4096-char query string) --
      // the prompt() just closed and nothing else ever happened. Same fix shape as Snips.persist().
      if (d && d.presets) { viewPresets = d.presets; renderPresets(); }
      else if (window.Toast) Toast.show({kind:'err', title:'View not saved', msg:(d&&d.error)||'The server rejected the save.'});
    }).catch(function(){ if (window.Toast) Toast.show({kind:'err', title:'View not saved', msg:'Network error.'}); });
}
function deletePreset() {
  // The server has always supported POST {delete: name} (/api/view-presets), but no UI ever
  // called it -- a saved view could be created but never removed. This is the missing
  // control, wired to the select's own current value (the "select's reserved delete
  // affordance" the server route's docstring already anticipated).
  var s = document.getElementById('preset-select');
  var n = s && s.value;
  if (!n) return;
  if (!confirm('Delete the saved view "' + n + '"?')) return;
  fetch('/api/view-presets', { method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({delete: n}) })
    .then(function(r){ return r.json(); }).then(function(d) {
      if (d && d.presets) { viewPresets = d.presets; renderPresets(); }
      else if (window.Toast) Toast.show({kind:'err', title:'Delete failed', msg:(d&&d.error)||'The server rejected the delete.'});
    }).catch(function(){ if (window.Toast) Toast.show({kind:'err', title:'Delete failed', msg:'Network error.'}); });
}
function loadPreset(n) {
  if (!n) return;
  if (viewPresets[n] !== undefined) location.href = '/' + viewPresets[n];
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
// The export dialog serves two entry points. _exportColl holds a collection name when the
// download is "this whole collection", or null for a curated selection. Each opener sets it.
var _exportColl = null;
function downloadZip() {
  // Curated SELECTION -> dialog -> doExportDownload() POSTs the picked media_ids.
  var sel = [...selGet()];
  if (!sel.length) return;
  _exportColl = null;
  document.getElementById('export-n').textContent = sel.length + ' item' + (sel.length===1?'':'s');
  document.getElementById('export-modal').classList.add('open');
}
function downloadCollection(name) {
  // Whole COLLECTION -> dialog -> doExportDownload() POSTs collection=<name>; the server
  // resolves its full membership (every item, across pages), not the rendered checkboxes.
  if (!name) return;
  _exportColl = name;
  document.getElementById('export-n').textContent = 'collection “' + name + '”';
  document.getElementById('export-modal').classList.add('open');
}
function contactSheetCollection(name) {
  // Whole COLLECTION's ZIP-download twin (downloadCollection above): open the print-ready
  // contact sheet for every item in the collection, same as bulkContactSheet() does for a
  // curated selection (ids=) but with collection= -- the server resolves full membership.
  if (!name) return;
  window.open('/contact-sheet?collection=' + encodeURIComponent(name), '_blank');
}
function doExportDownload() {
  var fmt = document.getElementById('export-fmt').value;
  var embed = document.getElementById('export-embed').checked;
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/export-zip';
  if (_exportColl) {
    var ic = document.createElement('input'); ic.type='hidden'; ic.name='collection'; ic.value=_exportColl; f.appendChild(ic);
  } else {
    var sel = [...selGet()];
    if (!sel.length) return;
    sel.forEach(function(mid){
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = 'media_ids'; i.value = mid; f.appendChild(i);
    });
  }
  document.getElementById('export-modal').classList.remove('open');
  var ff = document.createElement('input'); ff.type='hidden'; ff.name='fmt'; ff.value=fmt; f.appendChild(ff);
  if (embed) { var fe = document.createElement('input'); fe.type='hidden'; fe.name='embed'; fe.value='1'; f.appendChild(fe); }
  document.body.appendChild(f); f.submit(); f.remove();
}
// --- Web import: drop local files -> POST /api/import-local (localhost-only route) ------------
var ImportUI = (function(){
  var CAP = 24;                 // preview is capped; the IMPORT itself is never capped
  // Sentinel for the "＋ New collection…" option. Double-underscored so it cannot collide
  // with a real collection name, and it is never sent to the server -- chosenCollection()
  // resolves it to the typed name (or refuses) before the request is built.
  var NEW_COLL = '__new__';
  var files = [];               // File[]
  var urls = [];                // objectURLs pending revoke
  var IMG = /[.](png|jpe?g|webp|gif|bmp|avif)$/i, VID = /[.](mp4|webm|mov|m4v)$/i, ZIP = /[.]zip$/i;
  function el(id){ return document.getElementById(id); }
  function kind(f){ var n=f.name||''; return ZIP.test(n)?'zip':VID.test(n)?'video':IMG.test(n)?'image':'other'; }
  function esc(s){ return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function fmtSize(b){ if(b<1024)return b+' B'; if(b<1048576)return (b/1024).toFixed(0)+' KB'; if(b<1073741824)return (b/1048576).toFixed(1)+' MB'; return (b/1073741824).toFixed(2)+' GB'; }
  function revoke(){ urls.forEach(function(u){ URL.revokeObjectURL(u); }); urls=[]; }
  function reset(){ files=[]; revoke();
    el('imp-drop').style.display=''; el('imp-preview').style.display='none';
    el('imp-result').style.display='none'; el('imp-go').style.display='none';
    var fi=el('imp-file'), fo=el('imp-folder'); if(fi)fi.value=''; if(fo)fo.value='';
    // The collection choice is per-import, not sticky: reset() runs on both open() and
    // close(), so a name typed for one batch can't silently ride along on the next.
    var cs=el('imp-collection'), cn=el('imp-newcoll'), cr=el('imp-newcoll-row');
    if(cs)cs.value=''; if(cn)cn.value=''; if(cr)cr.style.display='none'; }
  function open(){ reset(); el('import-modal').classList.add('open'); }
  function close(){ el('import-modal').classList.remove('open'); reset(); }
  function browse(){ el('imp-file').click(); }
  function browseFolder(){ el('imp-folder').click(); }
  function onPick(list){ add(list); }
  function add(list){
    for(var i=0;i<list.length;i++){ var f=list[i];
      if(kind(f)==='other') continue;                                  // skip non-media
      if(files.some(function(x){ return x.name===f.name && x.size===f.size; })) continue;   // de-dupe
      files.push(f);
    }
    render();
  }
  function remove(i){ files.splice(i,1); render(); }
  function render(){
    if(!files.length){ reset(); return; }
    el('imp-drop').style.display='none'; el('imp-preview').style.display=''; el('imp-go').style.display='';
    var nI=0,nV=0,nZ=0,bytes=0;
    files.forEach(function(f){ var k=kind(f); if(k==='image')nI++; else if(k==='video')nV++; else if(k==='zip')nZ++; bytes+=f.size; });
    var parts=[]; if(nI)parts.push(nI+' image'+(nI!==1?'s':'')); if(nV)parts.push(nV+' video'+(nV!==1?'s':'')); if(nZ)parts.push(nZ+' zip'+(nZ!==1?'s':''));
    el('imp-sum').innerHTML='<b>'+files.length+' file'+(files.length!==1?'s':'')+'</b> &middot; '+parts.join(' &middot; ')+' &middot; '+fmtSize(bytes);
    el('imp-go').textContent='↑ Import '+files.length+' file'+(files.length!==1?'s':'');
    revoke();
    var body=el('imp-body'), h, i;
    if(files.length<=CAP){                                             // few -> reviewable list
      h='<div class="imp-list">';
      files.forEach(function(f,idx){
        var badge=kind(f)==='video'?'▶':kind(f)==='zip'?'📦':'';
        h+='<div class="imp-row" data-i="'+idx+'"><span class="imp-thumb">'+badge+'</span><span class="imp-nm">'+esc(f.name)+'</span><span class="imp-sz">'+fmtSize(f.size)+'</span><button class="imp-x" title="remove" onclick="ImportUI.remove('+idx+')">×</button></div>';
      });
      h+='</div>'; body.innerHTML=h;
      files.forEach(function(f,idx){ if(kind(f)!=='image')return; var u=URL.createObjectURL(f); urls.push(u);
        var row=body.querySelector('.imp-row[data-i="'+idx+'"]'); if(row){ var t=row.querySelector('.imp-thumb'); if(t)t.innerHTML='<img src="'+u+'">'; } });
    } else {                                                           // many -> capped grid, all still import
      h='<div class="imp-cap">ⓘ Preview capped at '+CAP+' &mdash; <b>all '+files.length+' will import</b> (only the preview is capped).</div><div class="imp-grid">';
      for(i=0;i<CAP-1;i++){ var k=kind(files[i]); h+='<div class="imp-tg" data-i="'+i+'">'+(k==='video'?'▶':k==='zip'?'📦':'')+'</div>'; }
      h+='<div class="imp-more">+'+(files.length-(CAP-1))+'<br>more</div></div>'; body.innerHTML=h;
      for(i=0;i<CAP-1;i++){ if(kind(files[i])!=='image')continue; var u=URL.createObjectURL(files[i]); urls.push(u);
        var cell=body.querySelector('.imp-tg[data-i="'+i+'"]'); if(cell)cell.innerHTML='<img src="'+u+'">'; }
    }
  }
  function onCollectionChange(){
    var isNew=el('imp-collection').value===NEW_COLL;
    el('imp-newcoll-row').style.display=isNew?'':'none';
    if(isNew) el('imp-newcoll').focus();
  }
  // Resolve the dropdown to a real collection name, or '' for none. Returns null when the
  // user picked "New collection…" and left it blank -- doImport treats that as "not ready"
  // rather than silently importing uncollected, which is the failure you'd only notice
  // later, looking for files that went somewhere else.
  function chosenCollection(){
    var sel=el('imp-collection').value;
    if(sel!==NEW_COLL) return sel;
    var name=(el('imp-newcoll').value||'').trim();
    return name || null;
  }
  function doImport(){
    if(!files.length) return;
    var coll=chosenCollection();
    if(coll===null){ el('imp-newcoll').focus(); el('imp-newcoll').placeholder='give the collection a name first'; return; }
    var go=el('imp-go'); go.disabled=true; go.textContent='Importing…';
    var fd=new FormData();
    files.forEach(function(f){ fd.append('files', f, f.name); });        // basename; server ignores any path
    if(coll) fd.append('collection', coll);
    // No CSRF token: same as the app's other fetch-based mutating APIs (/api/generate,
    // /api/loom/generate, /api/delete) -- protected by SESSION_COOKIE_SAMESITE=Lax + the
    // global front-door auth gate, and here additionally by the route's localhost-only check.
    fetch('/api/import-local',{method:'POST',body:fd})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok,j:j}; }); })
      .then(function(o){
        go.disabled=false; go.textContent='↑ Import';
        var res=el('imp-result'); res.style.display='';
        if(!o.ok || o.j.error){ res.className='imp-result err'; res.textContent='⚠ '+((o.j&&o.j.error)||('import failed ('+o.ok+')')); return; }
        var d=o.j;
        res.className='imp-result ok';
        res.innerHTML='✓ Imported <b>'+d.imported+'</b> file'+(d.imported!==1?'s':'')
          +(d.skipped?' &middot; '+d.skipped+' skipped (already in library)':'')
          +(d.collection?' &middot; added to “'+esc(d.collection)+'”':'')
          +'. <a href="/" style="color:var(--lavender);font-weight:600;">Reload gallery →</a>';
        el('imp-preview').style.display='none'; el('imp-go').style.display='none';
      })
      .catch(function(){ go.disabled=false; go.textContent='↑ Import';
        var res=el('imp-result'); res.style.display=''; res.className='imp-result err'; res.textContent='⚠ network error'; });
  }
  document.addEventListener('DOMContentLoaded',function(){
    var dz=el('imp-drop'); if(!dz) return;
    ['dragenter','dragover'].forEach(function(e){ dz.addEventListener(e,function(ev){ ev.preventDefault(); dz.classList.add('hot'); }); });
    dz.addEventListener('dragleave',function(ev){ ev.preventDefault(); dz.classList.remove('hot'); });
    dz.addEventListener('drop',function(ev){ ev.preventDefault(); dz.classList.remove('hot');
      if(ev.dataTransfer && ev.dataTransfer.files) add(ev.dataTransfer.files); });
  });
  return {open:open, close:close, browse:browse, browseFolder:browseFolder, onPick:onPick, remove:remove, doImport:doImport, onCollectionChange:onCollectionChange};
})();
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
// Mirror of bulkAddCollection for the other direction. The collection is NOT prompted for:
// this button only exists while a collection filter is active, so the target is the one the
// grid is already showing -- passed in from the button's data attribute.
function bulkRemoveCollection(name) {
  var sel = [...selGet()];
  if (!sel.length) { alert('Select one or more images/videos first (check the boxes, or "Select all"), then use Remove from collection.'); return; }
  if (!name) return;
  if (!confirm('Remove ' + sel.length + ' item(s) from the collection \\u201c' + name + '\\u201d?\\n\\n'
    + 'Only the collection label is removed \\u2014 no files are deleted and nothing leaves your PixAI account.')) return;
  var f = document.createElement('form');
  f.method = 'post'; f.action = '/collection-remove';
  function add(n, v){ var i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); }
  // Strip the one-shot banner param before it becomes `back`: removing twice in a row
  // would otherwise stack ?uncollected=3&uncollected=1 and the banner (which reads the
  // FIRST value) would report the stale count.
  var back = new URL(location.href); back.searchParams.delete('uncollected');
  add('back', back.pathname + back.search); add('name', name);
  sel.forEach(function(mid){ add('media_ids', mid); });
  localStorage.removeItem('gallery_sel');   // consume the selection: those rows are about to leave this view
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
  .gen-sel{width:100%;background-color:var(--surface0);border:1px solid var(--surface1);border-radius:6px;color:var(--text);padding:6px 8px;font-size:12.5px;}
  .gen-sel:hover{border-color:var(--lavender);}
  /* Same custom-arrow treatment as .filters select/#preset-select/select.p-sel (native
     select styling split, audit row: three selectors got appearance:none + the lavender
     caret, .gen-sel's <select>s and the Picker's own selects never did -- no rationale
     anywhere for the split, just an oversight, so made consistent here instead of documented
     as intentional. `select.gen-sel`, not bare `.gen-sel`: the class is shared with several
     plain text/number <input>s in the same drawer (gen-seed, gen-cw/ch, imp-newcoll) that
     must NOT grow a dropdown arrow or the wider right padding a caret needs. */
  select.gen-sel{-webkit-appearance:none;appearance:none;cursor:pointer;
    background-image:url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="10" height="6"%3E%3Cpath d="M0 0l5 6 5-6z" fill="%239a93ab"/%3E%3C/svg%3E');
    background-repeat:no-repeat;background-position:right 8px center;padding-right:24px;}
  .gen-check{display:flex;align-items:center;gap:7px;color:var(--subtext);font-size:12px;margin-top:8px;cursor:pointer;}
  /* The two lines that used .gen-cost (Generate + Edit) are <mg-cost-badge> now, which brings
     its own box -- padding/radius/border/font were lifted from this rule verbatim when the
     component was written, so the swap is pixel-identical apart from the badge's explicit
     line-height 1.4 (this rule inherited the page's `normal`). .gen-cost.warn was already
     dead: nothing in this file ever set it. Deleted rather than left as an unused rule --
     stale copies of the cost styling are the exact drift the consolidation exists to end. */
  .gen-go{width:100%;padding:9px 0;border:none;border-radius:6px;background:var(--lavender);color:var(--base);font-size:13.5px;font-weight:600;cursor:pointer;}
  .gen-go:hover{opacity:.9;} .gen-go:disabled{opacity:.4;cursor:not-allowed;}
  .gen-moon{display:inline-block;width:15px;height:15px;border-radius:50%;background:var(--lavender);position:relative;overflow:hidden;vertical-align:-3px;margin-right:7px;box-shadow:0 0 9px rgba(182,146,230,.75);}
  .gen-moon::after{content:'';position:absolute;inset:0;border-radius:50%;background:var(--mantle);animation:gen-eclipse 2.6s ease-in-out infinite;}
  @keyframes gen-eclipse{0%{transform:translateX(-102%);}50%{transform:translateX(0);}100%{transform:translateX(102%);}}
  .gen-result{margin-top:12px;} .gen-result img{width:100%;border-radius:10px;display:block;margin-bottom:6px;}
  .gen-result a{color:var(--accent-soft);font-size:12px;text-decoration:none;}
  /* Concurrent generations (2026-07-23): each submission gets its OWN line inside the
     result strip instead of one shared div that a later submission's status update would
     overwrite. A hairline separator between entries is the only visual change from before
     when only one submission is ever in flight. */
  .gen-result-line{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
  .gen-result-line:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none;}
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
      <button id="gm-generate" class="on" onclick="Gen.setMode('generate')">Image</button>
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
        <summary style="cursor:pointer;color:var(--subtext);font-size:11px;">Advanced</summary>
        <textarea id="gen-neg" class="gen-ta" rows="2" placeholder="lowres, text, watermark&hellip;" style="margin-top:5px;"></textarea>
        <div style="display:flex;gap:10px;margin-top:6px;">
          <label style="font-size:11px;color:var(--subtext);flex:1;">Steps
            <input type="number" id="gen-steps" min="1" max="150" step="1" value="25" style="width:100%;margin-top:2px;">
          </label>
          <label style="font-size:11px;color:var(--subtext);flex:1;">CFG scale
            <input type="number" id="gen-cfg" min="1" max="30" step="0.5" value="7" style="width:100%;margin-top:2px;">
          </label>
        </div>
        <div id="gen-modeldefaults" style="display:none;justify-content:space-between;align-items:center;margin-top:6px;">
          <span style="font-size:10.5px;color:var(--overlay0);">&#10003; using this model's tuned preset</span>
          <button type="button" class="snip-btn" onclick="Gen.resetModelDefaults()">&#8630; reset</button>
        </div>
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
      <mg-cost-badge id="gen-cost" hint="Pick a model to see the cost." card-label="a card"></mg-cost-badge>
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
        <mg-cost-badge id="edit-cost" hint="Pick an image to see the cost." card-label="an Edit card"></mg-cost-badge>
        <button id="edit-go" class="gen-go" onclick="Gen.edit()">Apply edit</button>
        <div id="edit-result" class="gen-result" style="display:none;"></div>
      </div>
      <div id="edit-sub-enhance" style="display:none;">
        <div class="gen-lbl">One-click tools <span style="text-transform:none;color:var(--subtext);">&middot; official PixAI workflows &middot; runs on the source</span></div>
        <div class="enh-shelf">
          <div class="enh-sec">Upscale</div>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1794855217667308480','Upscale')" title="Upscale the image">Upscale</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1804744873525448983','Upscale 2×2')" title="Upscale in 2x2 tiles (higher detail)">Upscale 2&times;2</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1803967880822088690','Upscale + Enhance')" title="Upscale and re-detail">Upscale + Enhance</button>
          <div class="enh-sec">Cleanup</div>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1793505053210462325','Remove BG')" title="Remove the background">Remove BG</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1793473388466817128','Precise inpaint')" title="Precise masked inpaint / edit">Precise inpaint</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1793713293591365899','Outpaint')" title="Extend the frame outward (outpaint)">Outpaint</button>
          <div class="enh-sec">Convert</div>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1796053397111789217','To line art')" title="Convert to line art">To line art</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1793447160259872021','Sketch colorizer')" title="Colorize a sketch / line art">Sketch colorizer</button>
          <div class="enh-sec">Light</div>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1801729774701480692','Relight: sun')" title="Relight: warm sunshine">Relight: sun</button>
          <button type="button" class="enh-card" onclick="Gen.selectEnhance('1801752508134768728','Relight: backlight')" title="Relight: backlighting">Relight: backlight</button>
        </div>
        <div class="gen-lbl">Browse all workflows <span style="text-transform:none;color:var(--subtext);">&middot; 140+ community ComfyUI</span></div>
        <input class="gen-search" id="enh-q" placeholder="Search workflows &mdash; upscale, background, line art&hellip;" autocomplete="off">
        <div id="enh-list"></div>
        <div class="gen-lbl" id="enh-selected" style="display:none;"></div>
        <mg-cost-badge id="enhance-cost" hint="Pick a tool to see the cost." card-label="an Edit card"></mg-cost-badge>
        <button type="button" class="gen-go" id="enh-go" disabled onclick="Gen.runEnhance()">Run</button>
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
      {# Migrated to the shared <mg-generate-drawer> web component (static/mg-generate-drawer.js) --
         the SAME element the Loom already mounts in production. It renders the full-parity Video
         form (6 image + 3 video + 1 audio refs, negative prompt, Channel, the full model roster
         with capability gating) and owns its own submit/poll/result/pricing over
         /api/loom/generate. NO data-loom-ctx here, so Camera + Basic/Professional show -- the
         gallery mount, per the LOCKED artifact 74ad3fd0. The host wires the gallery Picker to the
         element's mg-pick-request event, and Gen.addVideoRefs feeds picked images via prefill()
         -- see Gen.init below. The old hand-rolled #gen-mode-video form (9 undifferentiated image
         slots, 5-model select, no video/audio refs, no negative, no channel) is gone. #}
      <mg-generate-drawer></mg-generate-drawer>
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
<div id="ach-modal" class="ach-modal ach-hall" aria-hidden="true" onclick="if(event.target===this)Ach.close()">
  <div class="ach-panel" role="dialog" aria-label="The Folio of Honors">
    <div class="hall-head">
      <div class="hall-title">&#127942; <b>The Folio of Honors</b>
        <img class="ach-nar" id="ach-nar" src="/branding/mascots/gen_nel.png" title="the narrator"
          alt="the narrator" onclick="Ach.poke()" onerror="this.remove()"><span id="ach-unleash-slot"></span></div>
      <div class="hall-score" id="ach-progress">&hellip;</div>
      <input id="ach-search" class="hall-search" type="search" placeholder="Search&hellip;"
        oninput="Ach.search(this.value)" aria-label="Search achievements">
      <button type="button" class="ach-x" onclick="Ach.close()" aria-label="Close">&times;</button>
    </div>
    <div class="hall-tabs" id="ach-tabs">
      <button type="button" class="htab on" data-tab="summary" onclick="Ach.tab('summary')">Summary</button>
      <button type="button" class="htab" data-tab="all" onclick="Ach.tab('all')">All</button>
      <button type="button" class="htab" data-tab="stats" onclick="Ach.tab('stats')">Statistics</button>
    </div>
    <div class="hall-body">
      <div class="hall-main" id="ach-main">
        <div id="ach-summary" class="hall-view"></div>
        <div id="ach-grid" class="ach-grid hall-view" style="display:none"></div>
        <div id="ach-stats" class="hall-view" style="display:none"></div>
      </div>
      <aside class="hall-rail" id="ach-rail"></aside>
    </div>
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
  /* .ach-modal (shared base modal chrome for #ach-modal/#contest-modal/#art-modal) now lives
     in static/mg-notify.js, loaded via <script src> below -- do not re-add it here. */
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
</style>
<style>
  #snip-menu{position:fixed;z-index:236;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:220px;max-width:min(340px, calc(100vw - 16px));max-height:300px;overflow-y:auto;padding:5px;}
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
  .acct-claim img.claim-ico{height:15px;width:15px;vertical-align:-2px;margin-right:3px;}
  #ctx-menu{position:fixed;z-index:230;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:180px;padding:4px;}
  #ctx-menu button{display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font-size:12.5px;padding:7px 10px;border-radius:5px;cursor:pointer;}
  #ctx-menu button:hover{background:var(--surface0);}
  #tag-suggest{position:fixed;z-index:240;background:var(--mantle);border:1px solid var(--surface1);border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:none;min-width:190px;max-width:min(320px, calc(100vw - 16px));padding:4px;}
  #tag-suggest .ts-head{display:flex;justify-content:space-between;gap:14px;color:var(--overlay0);font-size:10px;padding:3px 8px;text-transform:uppercase;letter-spacing:.05em;}
  #tag-suggest button{display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font-size:12.5px;padding:6px 9px;border-radius:5px;cursor:pointer;}
  #tag-suggest button.hot,#tag-suggest button:hover{background:var(--surface0);color:var(--lavender);}
</style>
<script src="/static/picker-core.js"></script>
<!-- <mg-cost-badge> is the one renderer for "this costs N credits / a free card covers it"
     (static/mg-cost-badge.js). Loaded FIRST because it is a hard dependency of three things on
     this page: the Generate and Edit tabs' own cost lines below, and <mg-generate-drawer>'s
     .mgd-cost. Without it those elements never upgrade, their setChecking()/setPrice() calls
     throw, and the cost line freezes on its idle hint while the Go button beside it still
     spends -- a silent failure on the spend path, which is why the pairing has a test
     (test_web_pick.py::test_cost_badge_ships_with_every_price_surface) and not just a habit. -->
<script src="/static/mg-cost-badge.js"></script>
<!-- The shared <mg-generate-drawer> now mounts in the gallery's Video tab too (not just the
     Loom, which loads it in _LOOM_SHELL). It's picker-agnostic -- no mg-model-picker /
     mg-gallery-picker dependency -- so this one script plus the badge above is all the gallery
     mount needs; the host wires its mg-pick-request to the gallery Picker in the inline JS
     below. -->
<script src="/static/mg-generate-drawer.js"></script>
<script src="/static/mg-notify.js"></script>
<script>
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
      : 'Ranked by likes (live views load lazily, from any signed-in device). Run <code>--sync-artworks</code> to refresh stats.';
  }
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  return { open:open, close:close };
})();
var Picker = (function(){
  // Browse/filter/page/infinite-scroll logic lives in PickerCore now (shared with the
  // Loom's GalleryPick); this IIFE is a thin DOM-binding shim over it -- same ids, same
  // CSS, same 3 call sites, same behavior as before the refactor.
  var cb=null, core=null, forcedType='';   // forcedType: a caller-forced media filter for one open session (e.g. 'video')
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
          if(m.is_nsfw==='1') c.setAttribute('data-nsfw','1');
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
  function open(callback, opts){ cb=callback; forcedType=(opts&&opts.type)||'';
    el('pick-scrim').classList.add('open'); el('pick-modal').classList.add('open');
    el('pick-q').value=''; markLoading();
    ensureCore().setFilters(Object.assign({q:''}, readFilters(), {type:forcedType}));
    setTimeout(function(){el('pick-q').focus();},120);
    try{ el('pick-copy').checked = localStorage.getItem('pick-copyprompt')==='1'; }catch(e){} }
  function close(){ el('pick-scrim').classList.remove('open'); el('pick-modal').classList.remove('open'); cb=null; forcedType=''; }
  function onInput(){ ensureCore().setQuery(el('pick-q').value.trim()); }
  function onFilter(){ markLoading(); ensureCore().setFilters(Object.assign(readFilters(), {type:forcedType})); }
  function pick(m, thumb){
    try{ if(el('pick-copy').checked && m.prompt && navigator.clipboard) navigator.clipboard.writeText(m.prompt); }catch(e){}
    var f=cb; close(); if(f) f(m.media_id, thumb||m.thumb, m.prompt||'', m.is_nsfw||'');
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
    if(b){ if(d.claim_credits){ b.innerHTML='<img class="claim-ico" src="/branding/rewards/claim.png" onerror="this.remove()">+'+Number(d.claim_credits).toLocaleString()+' claim'; b.style.display=''; }
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
/* ---- First-run wizard: paste a key, then trigger the first sync as a Panel job ---- */
var Setup = (function(){
  function msg(id, text, cls){
    var el=document.getElementById(id); if(!el) return;
    el.textContent=text; el.className='setup-msg'+(cls?' '+cls:'');
  }
  function saveKey(){
    var input=document.getElementById('setup-key-input');
    var key=(input&&input.value||'').trim();
    if(!key){ msg('setup-key-msg','Paste your API key first.','err'); return; }
    msg('setup-key-msg','Connecting\\u2026','');
    fetch('/api/setup/save-key',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({api_key:key})}).then(function(r){return r.json();}).then(function(d){
      if(d.error){ msg('setup-key-msg',d.error,'err'); return; }
      var extra=d.credits!=null?(' \\u2014 '+Number(d.credits).toLocaleString()+' credits'):'';
      msg('setup-key-msg','Connected'+extra+'. Reloading\\u2026','ok');
      setTimeout(function(){ location.reload(); },900);
    }).catch(function(){ msg('setup-key-msg','Network error \\u2014 try again.','err'); });
  }
  var poll=null;
  function firstSync(){
    var btn=event&&event.target; if(btn) btn.disabled=true;
    msg('setup-sync-msg','Starting\\u2026','');
    fetch('/api/panel/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'sync'})}).then(function(r){return r.json();}).then(function(d){
      if(d.error){ msg('setup-sync-msg',d.error,'err'); if(btn) btn.disabled=false; return; }
      poll=setInterval(tick, 1500); tick();
    }).catch(function(){ msg('setup-sync-msg','Network error \\u2014 try again.','err'); if(btn) btn.disabled=false; });
  }
  function tick(){
    fetch('/api/panel/status').then(function(r){return r.json();}).then(function(d){
      if(d.status==='running'){
        var p=d.progress;
        msg('setup-sync-msg', p ? ('Syncing\\u2026 '+p.done+' / '+p.total+(p.new?(' ('+p.new+' new)'):'')) : 'Syncing\\u2026', '');
        return;
      }
      clearInterval(poll); poll=null;
      if(d.status==='failed'){ msg('setup-sync-msg','Sync failed \\u2014 see the Panel for details.','err'); return; }
      msg('setup-sync-msg','Done! Reloading\\u2026','ok');
      setTimeout(function(){ location.reload(); },900);
    }).catch(function(){});
  }
  return {saveKey:saveKey, firstSync:firstSync};
})();
/* ---- Prompt snippets / favorites (server-stored) ---- */
var Snips = (function(){
  var list=null, target=null;
  function menu(){ return document.getElementById('snip-menu'); }
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  function load(){ return (list!==null?Promise.resolve():fetch('/api/snippets').then(function(r){return r.json();})
      .then(function(d){ list=d.snippets||[]; }).catch(function(){ list=[]; })); }
  function persist(){
    // Was fully fire-and-forget: the server answers 200 with an {error:...} body on a write
    // failure (see /api/snippets' except OSError branch), and nothing here ever looked at
    // the response -- a save/delete could silently not stick and the UI would still show it
    // as saved until the next reload wiped it back out. Surface a failure the same way
    // Acct.claim() already does (window.Toast), and only there -- a clean save stays silent
    // exactly as before.
    fetch('/api/snippets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snippets:list})})
      .then(function(r){return r.json();})
      .then(function(d){ if(!d || d.error){ if(window.Toast) Toast.show({kind:'err', title:'Snippet not saved', msg:(d&&d.error)||'The server rejected the save.'}); } })
      .catch(function(){ if(window.Toast) Toast.show({kind:'err', title:'Snippet not saved', msg:'Network error.'}); });
  }
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
  var kind='base', q='', selected=null, timer=null, seq=0, costSeq=0, costTimer=null, previewTimer=null;
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
      // Debounced (D-11): a raw mouseenter re-triggered an instant, un-animated,
      // freshly-repositioned popup on EVERY card the mouse passed over while scanning
      // a grid -- which is what "browsing" is. A short hover-intent delay means only a
      // genuine pause-to-look opens it; a fast scan across several cards never does.
      c.onmouseenter=function(){ scheduleShowPreview(m, c); };
      c.onmouseleave=cancelPreview;
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
  function scheduleShowPreview(m, anchor){
    clearTimeout(previewTimer);
    previewTimer=setTimeout(function(){ showPreview(m, anchor); }, 130);
  }
  function cancelPreview(){ clearTimeout(previewTimer); hidePreview(); }
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
               weight:0.7, lora_base_type:'', trigger_words:'', failed:false};
    loras.push(entry); c.classList.add('sel'); renderLoras(); updateGoState();
    fetch('/api/model-version?model_id='+encodeURIComponent(m.model_id))
      .then(function(r){return r.json();})
      .then(function(d){ entry.version_id=d.version_id||''; entry.lora_base_type=d.lora_base_model_type||'';
        entry.trigger_words=d.trigger_words||'';
        // An empty version_id here is ALSO a failure, not a quiet no-op -- a LoRA that
        // never resolves must not be able to vanish from the submit silently (see failed
        // below): it used to just sit there forever wearing the "still loading" hourglass.
        entry.failed=!entry.version_id;
        renderLoras(); refreshLoraNotes(); debouncedCost(); })
      .catch(function(){ entry.failed=true; renderLoras(); refreshLoraNotes(); });
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
  // A LoRA still missing its version_id -- whether the lookup is still in flight or has
  // permanently failed -- must block Generate. The old code let this fall through silently:
  // the submit payload just filtered the unresolved LoRA out (see payload()), so a paid
  // generation could fire missing a LoRA the user believed was included, with nothing on
  // screen but an hourglass that never explained itself.
  function anyLoraUnresolved(){ return loras.some(function(l){ return !l.version_id; }); }
  function updateGoState(){ var go=el('gen-go'); if(go) go.disabled = !(selected&&selected.version_id) || anyIncompat() || anyLoraUnresolved(); }
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
      var d=document.createElement('div'); d.className='lora-chip'+((loraIncompat(l)||l.failed)?' incompat':'');
      var badge=l.version_id?'':(l.failed?' \\u26a0':' \\u23f3');
      var titleAttr=l.failed?(esc(l.title)+' \\u2014 could not load; remove it (\\u00d7) and re-add to retry'):esc(l.title);
      d.innerHTML=(l.preview_url?'<img src="'+esc(l.preview_url)+'" alt="">':'')
        +'<span class="nm" title="'+titleAttr+'">'+esc(l.title)+badge+'</span>'
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
        selected.negative_prompt=d.negative_prompt||''; selected.sampling_steps=d.sampling_steps||null;
        selected.cfg_scale=d.cfg_scale||null;
        el('gen-selname').textContent=m.title+(d.version_id?'':' (no version!)');
        refreshLoraNotes();   // re-check any attached LoRAs against the new base + set go-state
        applyModelDefaults();
        refreshCost(); })
      .catch(function(){ if(mySeq===selSeq) el('gen-selname').textContent=m.title; });
  }
  // Prefill negative/steps/cfg from the model author's own tuned preset (resolve_version_meta
  // already fetches these; the drawer just never used them). Only for fields the model actually
  // has data for -- a model with no tuned preset leaves whatever's already in the fields alone.
  function applyModelDefaults(){
    var note=el('gen-modeldefaults'); if(!note) return;
    var s=selected||{}, has=s.negative_prompt||s.sampling_steps||s.cfg_scale;
    note.style.display = has ? 'flex' : 'none';
    if(!has) return;
    if(s.negative_prompt) el('gen-neg').value=s.negative_prompt;
    if(s.sampling_steps) el('gen-steps').value=s.sampling_steps;
    if(s.cfg_scale) el('gen-cfg').value=s.cfg_scale;
  }
  function resetModelDefaults(){ applyModelDefaults(); }
  var genRef=null;   // {media_id, thumb, is_nsfw} -- the img2img reference, or null
  function refPick(){
    if(genRef){ genRef=null; renderGenRef(); debouncedCost(); return; }   // click filled slot = clear
    Picker.open(function(mid, thumb, prompt, is_nsfw){ genRef={media_id:mid, thumb:thumb, is_nsfw:is_nsfw}; renderGenRef(); debouncedCost(); });
  }
  function renderGenRef(){
    var s=el('gen-ref-slot'), c=el('gen-ref-ctl'); if(!s) return;
    if(genRef){
      if(genRef.is_nsfw==='1') s.setAttribute('data-nsfw','1'); else s.removeAttribute('data-nsfw');
      s.innerHTML='<img src="'+genRef.thumb+'" style="width:100%;height:100%;object-fit:cover;">'
        +'<span style="position:absolute;top:1px;right:1px;background:rgba(21,19,28,.85);color:var(--subtext);border-radius:50%;width:15px;height:15px;font-size:10px;line-height:15px;text-align:center;">&times;</span>';
      s.style.borderStyle='solid'; s.title='Click to remove the reference';
      c.style.display='';
      s.onmouseenter=function(){ showRefPreview(genRef.media_id, s); }; s.onmouseleave=hidePreview;
    } else {
      s.removeAttribute('data-nsfw');
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
      steps:+el('gen-steps').value||25, cfg:+el('gen-cfg').value||7,
      count:+el('gen-count').value, seed:(el('gen-seed')?el('gen-seed').value.trim():''),
      high_priority:el('gen-hp').checked, prompt_helper:el('gen-ph').checked,
      ref_media_id:(genRef?genRef.media_id:''), ref_strength:+el('gen-ref-strength').value,
      loras:loras.filter(function(l){return l.version_id;}).map(function(l){return {version_id:l.version_id, weight:l.weight};}) }; }
  function refreshCost(){
    updateDimNote();
    var cost=el('gen-cost');
    // Was a bare early `return` that left whatever the line last said on screen. Harmless in
    // practice (`selected` is only ever assigned, never cleared) but clear() is the honest
    // shape and it costs nothing to be right here.
    if(!(selected&&selected.version_id)){ cost.clear(); return; }
    cost.setChecking();
    var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())})
      .then(function(r){return r.json();})
      // Same split as editCost above: the host owns the fetch/debounce/stale-guard, the badge
      // owns every state's wording and colour. This tab had TWO fail-open branches, both now
      // gone: an unpriceable {cost:null, free:false} response rendered "~ ? credits", and a
      // server `note` was never handled at all so it fell into that same string.
      .then(function(d){ if(mine===costSeq) cost.setPrice(d); })
      .catch(function(){ if(mine===costSeq) cost.setPrice(null); });
  }
  function debouncedCost(){ clearTimeout(costTimer); costTimer=setTimeout(refreshCost,250); }
  function renderResultInto(target, d, past){
    if(d.error){ target.innerHTML='<span style="color:var(--red);font-size:12px;">'+esc(d.error)+'</span>'; return; }
    var ids=d.media_ids||[];
    var cost = d.paid_credit===0 ? 'free (card used)' : ((d.paid_credit||0).toLocaleString()+' credits');
    var html='<div style="color:var(--emerald);font-size:12px;margin-bottom:6px;">\\u2713 '+past+' \\u2014 '+cost+'. Added to your gallery.</div>';
    ids.forEach(function(mid){ html+='<a href="/image/'+mid+'"><img src="/thumbs/'+mid+'.jpg" alt="result" loading="lazy"></a>'; });
    if(ids.length){ html+='<a href="#" onclick="Gen.setEditSource(\\''+ids[0]+'\\');Gen.setMode(\\'edit\\');return false;">Edit this result \\u2192</a>'; }
    target.innerHTML=html;
  }
  // Concurrent generations (owner-approved 2026-07-23): PixAI itself runs tasks in
  // parallel, so the Go button used to lock for no real reason -- every OTHER tab reused
  // this one runTask(), so fixing it here fixes Generate/Edit/Enhance/Fix together. Each
  // call now gets its OWN line appended into the result strip (never overwriting a sibling
  // submission's still-live status/result), and the button frees up the moment the SERVER
  // ANSWERS the submit -- accepted or rejected -- not when the task finishes rendering.
  // Jobs already polls each task_id independently (its own de-dupe map is keyed by id), so
  // nothing about the polling itself needed to change -- only who owns the button and
  // where a submission's own status gets rendered.
  function runTask(url, p, res, opts){
    opts=opts||{};
    res.style.display='block';
    var line=document.createElement('div'); line.className='gen-result-line';
    line.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Submitting\\u2026</span>';
    res.appendChild(line);
    if(opts.btn){ opts.btn.disabled=true; opts.btn.textContent=opts.busy; }
    function unlock(){ if(opts.btn){ opts.btn.disabled=false; opts.btn.textContent=opts.idle; } }
    fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
      .then(function(r){return r.json();})
      .then(function(d){
        unlock();   // the server answered -- free the button for the NEXT submission
        if(d.error || !d.task_id){ renderResultInto(line, {error:d.error||'submit failed'}); return; }
        line.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Queued \\u2014 running\\u2026</span>';
        // Jobs owns the polling, so the task (and its result) survive closing the drawer.
        // The callback below only ever touches THIS submission's own `line`.
        Jobs.track(d.task_id, opts.past||'Task', function(phase, data){
          if(phase==='done'){ renderResultInto(line, data, opts.past); Acct.refresh(); }
          else if(phase==='failed'){ renderResultInto(line, {error:data.error||('task '+(data.status||'failed'))}); }
          else { line.innerHTML='<span class="gen-moon"></span><span style="color:var(--subtext);font-size:12px;">Rendering under the eclipse\\u2026 (task '+String(d.task_id).slice(-6)+')</span>'; }
        });
      }).catch(function(){ unlock(); renderResultInto(line, {error:'network error'}); });
  }
  function generate(){
    var p=payload();
    if(!p.version_id) return;
    if(!p.prompt){ el('gen-prompt').focus(); return; }
    // Belt-and-suspenders alongside updateGoState()'s disabled attribute: never let a
    // paid submit fire while a LoRA the user added is still unresolved or failed --
    // payload() would otherwise just quietly drop it and spend credits on a mismatch.
    if(anyLoraUnresolved()){ el('gen-lora-note').scrollIntoView({block:'nearest'}); return; }
    runTask('/api/generate', p, el('gen-result'),
            {past:'Generated', btn:el('gen-go'), busy:'Generating\\u2026', idle:'Generate'});
  }
  function setMode(m){
    ['generate','edit','video'].forEach(function(x){
      var pane=el('gen-mode-'+x); if(pane) pane.style.display=(x===m)?'':'none';
      var btn=el('gm-'+x); if(btn) btn.classList.toggle('on', x===m); });
    el('gen-drawer').classList.toggle('wide', m==='video'||m==='edit');
    if(m==='edit'){ setEditModel(editModel); loadWorkflows().then(renderWorkflows); if(!presetsLoaded) loadPresets(); }
    // Video is the <mg-generate-drawer> web component now -- it self-renders on connect and
    // owns its own state; nothing to (re)build here (the old renderVideoSlots is gone).
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
    debEnhanceCost();   // Enhance's price also depends on the shared edit-src (D-12)
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
    if(!editSrc()){ cost.clear(); return; }
    cost.setChecking();
    var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(editPayload())})
      .then(function(r){return r.json();})
      // <mg-cost-badge> owns the whole classification now (idle / checking / free / paid /
      // could-not-verify), so this function keeps only what a HOST must own: the request, the
      // 250ms debounce (debEditCost) and the stale-response guard. Not just tidying -- the
      // branch this replaces rendered a {cost:null, free:false} response as the price-shaped
      // "~ ? credits". That shape is NOT rare: price_task() in pixai_gallery_backup.py fails
      // soft and returns None on any /v2/task-price error, so a transient PixAI hiccup used to
      // put a neutral, price-looking string on the one line whose job is to say whether this
      // spends money. The badge renders it red instead.
      .then(function(d){ if(mine===costSeq) cost.setPrice(d); })
      // setPrice(null), NOT clear(): a failed fetch is could-not-verify, never "not priced
      // yet". Conflating the two is exactly what the old neutral "cost unavailable" did.
      .catch(function(){ if(mine===costSeq) cost.setPrice(null); });
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
    if(!fixBoxes.length){
      var fr=el('fix-result'); fr.style.display='block';
      var w=document.createElement('div'); w.className='gen-result-line';
      w.innerHTML='<span style="color:var(--subtext);font-size:12px;">Drag a box over a hand or face first.</span>';
      fr.appendChild(w);   // append, not overwrite -- a fix task already in flight keeps its own line
      return;
    }
    // No price check exists for this action (audit 2026-07-21, unfiled-workflow-findings):
    // /v2/task/fixer is a separate endpoint from the createGenerationTask family /v2/task-price
    // mirrors, so it cannot be priced the way every other spend surface in this app is -- a
    // client-side badge would just always show nothing. Until PixAI's own API can price a fixer
    // task, a plain confirm is this app's established fail-closed guardrail for exactly that
    // situation (the same shape the Loom's Deep Focus tabs already use for their own confirmSpend).
    if(!window.confirm('Fix hand/face regions? This spends PixAI credits -- no cost preview is available for this action yet.')) return;
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
        b.onclick=function(){ selectEnhance(w.id, nm); }; list.appendChild(b);
      });
  }
  // D-12: was click-runs-immediately (price -> window.confirm -> fire), the one Enhance
  // path never converted to the persistent <mg-cost-badge> pattern every other price
  // surface already uses. Now select-then-run, mirroring the Edit sub-tab's own shape:
  // clicking a tool only SELECTS it (updates the badge), a separate Run button fires it,
  // and the badge alone is the warning -- no window.confirm left, same as everywhere else.
  var enhWid='', enhName='';
  function selectEnhance(wid, name){
    enhWid=wid; enhName=name||'';
    var sel=el('enh-selected');
    if(sel){ sel.style.display=''; sel.innerHTML='Selected: <b style="color:var(--text);">'+esc(enhName)+'</b>'; }
    el('enh-go').disabled=false;
    debEnhanceCost();
  }
  function enhanceCost(){
    var cost=el('enhance-cost');
    if(!enhWid || !editSrc()){ cost.clear(); return; }
    cost.setChecking();
    var mine=++costSeq;
    fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:'enhance', source:editSrc(), workflow_id:enhWid})})
      .then(function(r){return r.json();})
      .then(function(d){ if(mine===costSeq) cost.setPrice(d); })
      .catch(function(){ if(mine===costSeq) cost.setPrice(null); });
  }
  function debEnhanceCost(){ clearTimeout(costTimer); costTimer=setTimeout(enhanceCost,250); }
  function runEnhance(){
    var src=editSrc();
    if(!src){ el('edit-src').focus(); return; }
    if(!enhWid){ return; }
    runTask('/api/enhance', {source:src, workflow_id:enhWid}, el('enh-result'),
            {past:'Enhanced', btn:el('enh-go'), busy:'Running\\u2026', idle:'Run'});
  }
  function genDrawerEl(){ var w=el('gen-mode-video'); return w?w.querySelector('mg-generate-drawer'):null; }
  function addVideoRefs(refs){
    // Gallery bulk-send ("make a video from these"): feed the picked images straight into
    // the <mg-generate-drawer> via its prefill() -- the same shot-context entry the Loom
    // uses. Image bank is 6 now (the full-parity split), not the old 9. >1 image -> Multi-ref.
    refs=(refs||[]).slice(0,6); if(!refs.length) return;
    open(); setMode('video');
    var drawer=genDrawerEl(); if(!drawer) return;
    drawer.prefill({ mode: refs.length>1?'r2v':'i2v',
                     images: refs.map(function(r){ return {media_id:r.mid, thumb:r.thumb}; }) });
  }
  return {open:open, close:close, setKind:setKind, onInput:onInput, search:search,
          refreshCost:debouncedCost, generate:generate, setMode:setMode, edit:edit,
          editCost:debEditCost, setEditSource:setEditSource, openEdit:openEdit,
          selectEnhance:selectEnhance, runEnhance:runEnhance,
          renderWorkflows:renderWorkflows, fixTag:fixTag, fixClear:fixClear, fix:fix,
          setDock:setDock, toggleFlyout:toggleFlyout,
          previewSelected:previewSelected, hidePreview:hidePreview,
          refPick:refPick, refStrength:refStrength, presetImport:presetImport,
          loraWeight:loraWeight, loraRemove:loraRemove, openLoraBrowser:openLoraBrowser,
          insertTriggers:insertTriggers, setSort:setSort, setCat:setCat,
          // addVideoRefs stays: it's the gallery bulk-send entry, rewired to feed
          // <mg-generate-drawer>.prefill(). The old video machinery (setVideoMode /
          // videoGenerate / renderVideoSlots / videoCost / vp* / videoPromptText/Set) is
          // gone -- the component owns all of that now.
          setEditSub:setEditSub, setEditModel:setEditModel, addVideoRefs:addVideoRefs,
          resetModelDefaults:resetModelDefaults,
          get selected(){return selected;}};
})();
// Gallery mount wiring for <mg-generate-drawer>: the component is picker-agnostic and fires
// mg-pick-request (bubbling + composed) whenever a slot's "+ pick" is clicked. Open the
// gallery Picker filtered to the requested kind (image | video -> /api/gallery-images type)
// and hand the choice back through respond(media_id, thumb). Audio refs never arrive here --
// the component uploads those directly (there is no gallery/catalog concept for a raw audio
// file). One document-level listener; the drawer is the only source of this event.
document.addEventListener('mg-pick-request', function(e){
  var d=e.detail; if(!d||typeof d.respond!=='function') return;
  Picker.open(function(mid, thumb, prompt, is_nsfw){ d.respond(mid, thumb, is_nsfw); }, d.kind==='video'?{type:'video'}:null);
});
// mg-submit / mg-result: the drawer polls and renders ITS OWN result inline (self-contained,
// same as the Loom's mount) -- these two listeners are not for that. They are the two things
// runTask() gives every OTHER tab (Generate/Edit/Fix, still the pre-migration inline JS) that
// the Video tab silently lost when it moved to <mg-generate-drawer> and nothing was ever wired
// to replace them: Jobs.register (the Activity card entry that survives closing the drawer or
// navigating away -- the drawer's own poll dies with the page, per its `if(!self.isConnected)
// return;` guard, so without this a video that finishes after you leave shows NOWHERE) and
// Acct.refresh() (the header credit balance, which every other spend path already updates on
// completion). Found 2026-07-21 by the post-v2.2.0 audit (B4): verified the drawer dispatches
// both events (bubbles+composed) but the gallery bound neither, while the Loom's own mount
// binds both via bindGenDrawer -- and its onVideoSubmit comment explicitly says the "Rendered"
// label is chosen to match "the gallery's own existing label for this same endpoint", i.e. this
// wiring was always assumed to exist here. One document-level listener each, matching
// mg-pick-request immediately above: the drawer is the only source of either event.
document.addEventListener('mg-submit', function(e){
  var d=e.detail; if(!d||!d.task_id) return;
  if(window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, 'Rendered');
});
document.addEventListener('mg-result', function(){ Acct.refresh(); });
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
        // Mirrors the server template's own is_nsfw-gated data-nsfw attribute (see the main
        // grid's card markup) -- without it, Privacy Blur never touches an NSFW lookalike here.
        if(it.is_nsfw==='1') c.setAttribute('data-nsfw','1');
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
  // Gen.addVideoRefs() itself caps at 6 (the multi-ref drawer's real limit, see its own
  // comment) -- this used to slice(0,9), a stale number left over from before that cap
  // dropped 9->6 in the full-parity split. addVideoRefs's cap was always the authoritative
  // one, so nothing over-sent either way, but nobody was ever TOLD their extra picks got
  // dropped -- fixed here, not by raising the cap.
  if(refs.length>6 && window.Toast) Toast.show({kind:'err', title:'Only 6 images used',
    msg:'The video drawer takes up to 6 reference images — '+(refs.length-6)+' of your '+refs.length+' were left out.'});
  Gen.addVideoRefs(refs);
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
  // (#video-prompt + its chipify listeners are gone -- the <mg-generate-drawer> component
  // owns the video prompt box and its own @ref chip handling now.)
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
    <a class="btn" href="{{ url_for('full_image', media_id=row.media_id) }}?dl=1">&#8681; Download</a>
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
      title="Copy this image's media_id (paste into the Edit tab or the Loom)">Copy media id</button>
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
    if (d.error || !s.length) {
      // d.error is a server-side str(e)[:200] -- an upstream exception string. Build it
      // as a TEXT node, never innerHTML: this page (DETAIL_HTML) has no escaper in scope,
      // and concatenating raw server text into innerHTML is an injection sink. textContent
      // cannot inject, so no escaper is needed.
      box.textContent = '';
      var em = document.createElement('span');
      em.style.color = 'var(--overlay0)';
      em.textContent = d.error || 'No suggestion returned.';
      box.appendChild(em);
      return;
    }
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

    LOGIN_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
{# Splash background: three tinted radial washes, a procedurally-generated star
   field, and a vignette. The stars are an SVG feTurbulence filter, not an image
   asset -- so this renders identically on a fresh clone with no branding art
   dropped in, and costs no request. #}
<div class="login-splash" aria-hidden="true">
  <div class="splash-wash"></div>
  <svg class="splash-stars" xmlns="http://www.w3.org/2000/svg">
    <filter id="mg-stars">
      <feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="1" stitchTiles="stitch"/>
      <feColorMatrix type="luminanceToAlpha"/>
      <feComponentTransfer><feFuncA type="discrete" tableValues="0 0 0 0 0 0 0 0 0 1"/></feComponentTransfer>
      <feColorMatrix type="matrix" values="0 0 0 0 0.84  0 0 0 0 0.82  0 0 0 0 0.89  0 0 0 1 0"/>
    </filter>
    <rect width="100%" height="100%" filter="url(#mg-stars)"/>
  </svg>
  <div class="splash-vignette"></div>
</div>
<div class="login-wrap">
  <div class="login-stage" id="login-stage">
    {# Mascot, ported from the mock's .char-stub: rises from BEHIND the card while
       the card dims, on submit. Uses real mascot art when present; if it's absent
       the glow + sparkle behind it is exactly the mock's own placeholder, so a
       fresh install still gets the moment rather than a broken image. #}
    <div class="login-char" id="login-char" aria-hidden="true">
      {# Each rung must hand off to the NEXT rung, and the last must REMOVE the
         element -- an <img> left in the DOM after its final 404 paints a broken-image
         icon, and the `:has(img)` rule below would go on suppressing the sparkle
         placeholder because a (broken) img still matches. Removing it restores the
         mock's own glow-and-sparkle treatment on an install with no mascot art. #}
      <img src="/branding/mascots/login_nel.png" alt=""
           onerror="this.onerror=function(){this.remove();};this.src='/branding/mascots/gen_nel.png';">
    </div>
  <div class="login-card">
    <div class="login-brand">
      {# Prefers a login-specific banner (the gallery header's banner.png is cropped
         for a wide header, not this 280x64 slot), falling back to it, and finally to
         the container's gradient -- which is the mock's own "banner art" placeholder,
         so every rung of the ladder degrades to the design, never to a broken image. #}
      <div class="login-banner"><img src="/branding/login-banner.png" alt=""
           onerror="this.onerror=null;this.src='/branding/banner.png';this.onerror=function(){this.remove();};"></div>
      <h1>Moonglade Athenaeum</h1>
      <p class="login-tagline">a library against the Void</p>
    </div>
    {% if bootstrap_mode %}
      <div class="login-note">
        <b>First run:</b> there's no login account yet on this install. Create the
        first account below &mdash; from then on, sign in with it from any device.
      </div>
      <form method="post" class="login-form" action="{{ url_for('login', next=next_url) if next_url else url_for('login') }}">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input type="hidden" name="mode" value="create">
        <div class="login-field">
          <label for="lf-user">Username</label>
          <input id="lf-user" type="text" name="username" autocomplete="username" maxlength="64" autofocus required>
        </div>
        <div class="login-field">
          <label for="lf-pass">Password</label>
          <input id="lf-pass" type="password" name="password" autocomplete="new-password" required>
        </div>
        <div class="login-field">
          <label for="lf-conf">Confirm password</label>
          <input id="lf-conf" type="password" name="confirm" autocomplete="new-password" required>
        </div>
        {% if error %}<p class="login-err">{{ error }}</p>{% endif %}
        <button type="submit" class="login-submit">Create account</button>
      </form>
    {% elif no_accounts %}
      <div class="login-note" id="login-no-accounts-remote">
        <b>No account has been set up yet.</b> Ask whoever runs this server to
        create the first account from the server machine.
      </div>
    {% else %}
      <form method="post" class="login-form" action="{{ url_for('login', next=next_url) if next_url else url_for('login') }}">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <div class="login-field">
          <label for="lf-user">Username</label>
          <input id="lf-user" type="text" name="username" autocomplete="username" maxlength="64" autofocus required>
        </div>
        <div class="login-field">
          <label for="lf-pass">Password</label>
          <input id="lf-pass" type="password" name="password" autocomplete="current-password" required>
        </div>
        {% if error %}<p class="login-err">{{ error }}</p>{% endif %}
        <button type="submit" class="login-submit">Sign in</button>
      </form>
    {% endif %}
  </div>
  </div>
</div>
<script>
/* On submit, raise the mascot from behind the card and dim the card -- the mock's
   `l.submitted` state. Progressive: if anything here throws, the form still posts
   normally, because nothing calls preventDefault. */
(function(){
  var stage = document.getElementById('login-stage');
  var form  = stage && stage.querySelector('form.login-form');
  if (!form || !stage) return;
  form.addEventListener('submit', function(){ stage.classList.add('submitted'); });
})();
</script>
<style>
  /* ---- Login screen -------------------------------------------------------
     The composition is the design, not just the components: banner + splash
     behind a centered stack, with real uppercase field labels rather than
     placeholder-only inputs. Treat the values below as one tuned set --
     changing them piecemeal is how this page once drifted into reading as a
     different page entirely. */
  .login-splash { position: fixed; inset: 0; background: var(--base); overflow: hidden; z-index: 0; }
  .splash-wash { position: absolute; inset: 0;
    background:
      radial-gradient(ellipse 80% 60% at 15% 20%, color-mix(in srgb, var(--accent) 7%, transparent) 0%, transparent 60%),
      radial-gradient(ellipse 60% 80% at 85% 75%, color-mix(in srgb, var(--mauve) 5%, transparent) 0%, transparent 55%),
      radial-gradient(ellipse 100% 50% at 50% 100%, color-mix(in srgb, var(--mantle) 90%, transparent) 0%, transparent 50%); }
  .splash-stars { position: absolute; inset: 0; width: 100%; height: 100%; opacity: .55; }
  .splash-vignette { position: absolute; inset: 0;
    background: radial-gradient(ellipse 100% 100% at 50% 50%, transparent 40%, color-mix(in srgb, var(--mantle) 70%, transparent) 100%); }

  .login-wrap { position: relative; z-index: 1; min-height: 100vh; display: flex;
    align-items: center; justify-content: center; padding: 24px 16px; box-sizing: border-box; }
  /* The stage exists so the mascot can be positioned against the card and rise
     from BEHIND it (z-index 0 vs the card's 1) -- the mock's own arrangement. */
  .login-stage { position: relative; width: 100%; max-width: 380px; }
  .login-card {
    position: relative; z-index: 1;
    width: 100%; background: color-mix(in srgb, var(--surface0) 82%, transparent);
    backdrop-filter: blur(18px);
    border: 1px solid color-mix(in srgb, var(--surface1) 70%, transparent); border-radius: 14px;
    padding: 36px 32px; box-shadow: 0 32px 80px rgba(0,0,0,.6); box-sizing: border-box;
    transition: opacity .4s;
  }
  .login-stage.submitted .login-card { opacity: .5; }
  .login-char { position: absolute; bottom: 0; left: 50%; width: 150px; height: 190px;
    pointer-events: none; z-index: 0; opacity: 0; transform: translate(-50%, 0);
    background: radial-gradient(ellipse 70% 90% at 50% 100%, color-mix(in srgb, var(--accent) 55%, transparent), transparent 72%);
    filter: drop-shadow(0 -6px 20px color-mix(in srgb, var(--accent) 50%, transparent)); }
  .login-char::after { content: '\\2726'; position: absolute; top: 18%; left: 50%;
    transform: translateX(-50%); font-size: 38px; color: var(--text); opacity: .85;
    text-shadow: 0 0 18px color-mix(in srgb, var(--accent) 70%, transparent); }
  /* Real art, when present, sits over the glow and hides the sparkle stand-in. */
  .login-char img { position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: contain; object-position: bottom center; }
  .login-char:has(img)::after { display: none; }
  .login-stage.submitted .login-char {
    animation: login-char-rise 1.6s cubic-bezier(.22,1,.36,1) forwards; }
  @keyframes login-char-rise {
    0%   { opacity: 0; transform: translate(-50%, 40px) scale(.94); }
    100% { opacity: 1; transform: translate(-50%, 0) scale(1); }
  }
  @media (prefers-reduced-motion: reduce) {
    .login-stage.submitted .login-char { animation: none; opacity: 1; }
  }
  .login-brand { text-align: center; margin-bottom: 28px; }
  .login-banner { width: 100%; max-width: 280px; height: 64px; margin: 0 auto 12px; border-radius: 6px;
    background: linear-gradient(120deg, var(--purple-deep), var(--surface1) 45%, var(--accent) 100%);
    filter: drop-shadow(0 0 14px color-mix(in srgb, var(--accent) 40%, transparent));
    overflow: hidden; display: flex; align-items: center; justify-content: center; }
  .login-banner img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .login-card h1 { font-family: Georgia, 'Times New Roman', serif; font-size: 22px;
    font-weight: 400; color: var(--text); margin: 0 0 6px; letter-spacing: .04em; border: none; }
  .login-tagline { font-size: 12px; color: var(--overlay0); margin: 0;
    letter-spacing: .12em; text-transform: uppercase; }

  .login-form { display: flex; flex-direction: column; gap: 16px; }
  .login-field { display: flex; flex-direction: column; gap: 6px; }
  .login-field label { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--subtext); }
  .login-field input { width: 100%; background: var(--mantle); border: 1px solid var(--surface1);
    border-radius: 6px; padding: 10px 12px; color: var(--text); font: inherit; font-size: 14px;
    box-sizing: border-box; }
  .login-field input:focus { outline: none; border-color: var(--accent); }
  /* Browser autofill repaints inputs with its own near-white background, which
     overrides `background` outright -- so a saved password turned these fields
     stark white on a dark card. There is no property to unset it; the only
     reliable fix is to cover the painted area with an inset box-shadow and force
     the text colour. The absurd transition delay stops Chrome re-applying its
     colour a beat after load. Nothing else in this app had autofill handling. */
  .login-field input:-webkit-autofill,
  .login-field input:-webkit-autofill:hover,
  .login-field input:-webkit-autofill:focus,
  .login-field input:-webkit-autofill:active {
    -webkit-box-shadow: 0 0 0 1000px var(--mantle) inset !important;
    box-shadow: 0 0 0 1000px var(--mantle) inset !important;
    -webkit-text-fill-color: var(--text) !important;
    caret-color: var(--text);
    transition: background-color 9999s ease-in-out 0s;
  }
  .login-submit { width: 100%; background: var(--accent); color: var(--mantle); border: none;
    border-radius: 6px; padding: 11px 0; font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
  .login-submit:hover { filter: brightness(1.06); }
  /* First-run notice: the mock's gold callout. The remote "no account yet"
     message reuses it -- same weight of statement, same treatment. */
  .login-note { background: color-mix(in srgb, var(--gold) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold) 20%, transparent); border-radius: 6px;
    padding: 10px 12px; margin-bottom: 20px; font-size: 12px; color: var(--gold); line-height: 1.5; }
  .login-err { color: var(--red); font-size: 13px; margin: 0; padding: 8px 10px;
    background: color-mix(in srgb, var(--red) 8%, transparent); border-radius: 5px;
    border: 1px solid color-mix(in srgb, var(--red) 20%, transparent); }
</style>
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
    <code>--dedup</code> would quarantine the rest. Review below, then run Dedup from the
    <a href="{{ url_for('panel') }}">Control Panel</a>.
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
  /* Per-job option toggle. Sits inside its button but swallows the click, so ticking it
     configures the run instead of starting one. */
  .job-opt{display:flex;align-items:center;gap:5px;margin-top:5px;font-size:11.5px;color:var(--subtext);cursor:pointer;}
  .job-opt input{margin:0;accent-color:var(--accent);cursor:pointer;}
  .jobbtn.danger .job-opt{color:var(--red);}
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
  .st-running{color:var(--lavender);} .st-done{color:var(--emerald);} .st-failed{color:var(--red);} .st-warn{color:var(--peach);}
  .jobprog{margin:12px 0 4px;}
  .jp-bar{height:10px;border-radius:6px;background:var(--surface1);overflow:hidden;}
  .jp-bar i{display:block;height:100%;width:0;border-radius:6px;background:linear-gradient(90deg,var(--accent),var(--accent-soft));transition:width .4s ease;}
  .jp-txt{font-size:11.5px;color:var(--subtext);margin-top:5px;font-variant-numeric:tabular-nums;}
  /* Panel tab bar -- same .htab/.htab.on visual language as the Folio of Honors'
     Summary/All/Statistics tabs (static/mg-notify.js's injected styles), copied
     rather than shared via a <script src> because mg-notify.js also wires up the
     Jobs tray/Achievement modals that this page doesn't otherwise use; see
     panel()'s docstring. Do not restyle these independently of that source. */
  .p-tabs{display:flex;gap:4px;padding:0 0 10px;border-bottom:1px solid var(--surface0);margin-bottom:16px;}
  .htab{background:none;border:none;color:var(--subtext);font-size:13px;font-weight:600;cursor:pointer;padding:8px 14px;border-radius:8px 8px 0 0;border-bottom:2px solid transparent;}
  .htab:hover{color:var(--text);}
  .htab.on{color:var(--lavender);border-bottom-color:var(--lavender);background:rgba(182,146,230,.06);}
  .ptab-view{display:none;}
  .ptab-view.on{display:block;}
  .u-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;background:var(--surface0);border-radius:8px;border:1px solid var(--surface1);}
  .u-row + .u-row{margin-top:6px;}
  /* The name flexes and truncates; the Remove button never shrinks or moves. This
     is the layout half of the username-length fix -- new names are capped at 64,
     but a legacy over-long name in config must still not push the button off-card. */
  .u-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13.5px;color:var(--text);}
  .u-row .btn{flex:none;}
  .u-you{font-size:11px;color:var(--accent);margin-left:8px;}
</style>
<header>
  <div class="brand"><span class="mark anim-{{ mark_anim|default('classic', true) }}{% if mark_kind == 'tile' %} mk-tile{% endif %}"><span class="mark-m">M</span><img class="mark-logo" src="{{ mark_url|default('/branding/logo.png', true) }}" alt="" onerror="this.remove()"></span><h1>Control Panel</h1></div>
  <span id="acct-chip" class="acct-chip" title="Your PixAI balance" style="margin-left:auto;display:none;"></span>
  <a class="btn" href="{{ url_for('index') }}">↑ Back to gallery</a>
</header>
<div class="panel">
  <div class="p-tabs" id="panel-tabs">
    <button type="button" class="htab on" data-tab="maintenance" onclick="setPanelTab('maintenance')">Maintenance</button>
    <button type="button" class="htab" data-tab="users" onclick="setPanelTab('users')">Users</button>
  </div>
  <div id="ptab-maintenance" class="ptab-view on">
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
    <details class="jobs-adv" style="margin-top:16px;">
      <summary style="font-size:12px;color:var(--overlay0);cursor:pointer;user-select:none;">Advanced &middot; sync variants the one-click Sync doesn't cover</summary>
      <div style="font-size:11.5px;color:var(--overlay0);margin:8px 0;line-height:1.5;">These re-walk the full account rather than the incremental default. Slower, all read/append (never delete).</div>
      <div class="jobrow" id="jobs-advanced"></div>
    </details>
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
  <div id="ptab-users" class="ptab-view">
  <div class="p-sec">
    <h2>Accounts</h2>
    <div id="users-list">
      {% for u in web_users %}
      <div class="u-row" data-username="{{ u.username }}">
        <span class="u-name">{{ u.username }}{% if u.username == current_username %}<span class="u-you">you</span>{% endif %}</span>
        {% if panel_is_local or u.username == current_username %}
        <button type="button" class="btn btn-danger" onclick="removeUser(this)">Remove</button>
        {% endif %}
      </div>
      {% else %}
      <div class="p-note" id="users-empty">No accounts.</div>
      {% endfor %}
    </div>
  </div>
  <div class="p-sec">
    <h2>Add user</h2>
    {% if panel_is_local %}
    <form id="add-user-form" onsubmit="return addUser(event)">
      <div class="setup-row login-fields" style="max-width:380px;">
        <input type="text" id="new-username" placeholder="Username" autocomplete="off" maxlength="64" required>
        <input type="password" id="new-password" placeholder="Password" autocomplete="new-password" required>
        <input type="password" id="new-confirm" placeholder="Confirm password" autocomplete="new-password" required>
        <button type="submit" class="btn btn-primary">Add user</button>
      </div>
    </form>
    <div id="add-user-status" style="margin-top:8px;"></div>
    <div class="p-note">Once you're signed in, every account has equal access to this gallery (generate, browse, maintenance) &mdash; there's no separate admin tier. Adding a new account, or removing someone else's, is restricted to the machine running the gallery.</div>
    {% else %}
    <div class="p-note">Only the machine running the gallery can add new accounts. Ask the owner, or sign in from that machine. (You can still remove your own account above.)</div>
    {% endif %}
  </div>
  </div>
</div>
<div id="srv-overlay">
  <div class="srv-box"><div class="srv-spin" id="srv-spin"></div>
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
var CSRF = "{{ csrf }}";   // same session-based token every other mutating form in this app uses
function el(i){return document.getElementById(i);}
// --- Panel tab bar (Maintenance / Users) -----------------------------------
function setPanelTab(tab){
  document.querySelectorAll('#panel-tabs .htab').forEach(function(b){
    b.classList.toggle('on', b.getAttribute('data-tab') === tab); });
  el('ptab-maintenance').classList.toggle('on', tab === 'maintenance');
  el('ptab-users').classList.toggle('on', tab === 'users');
}
// --- Users tab: add / remove gallery web-login accounts --------------------
function escH2(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function addUser(evt){
  evt.preventDefault();
  var u=el('new-username').value.trim(), p=el('new-password').value, c=el('new-confirm').value;
  var st=el('add-user-status');
  fetch('/api/users/add',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:u, password:p, confirm:c, csrf:CSRF})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ st.innerHTML='<span class="st-failed">⚠ '+escH2(d.error)+'</span>'; return; }
      var empty=el('users-empty'); if(empty) empty.remove();
      // Built via DOM APIs (not innerHTML string concatenation) so an arbitrary
      // username can never be interpreted as HTML or JS -- the same reason the
      // server-rendered row below passes `this` to removeUser() instead of
      // templating the username into an inline onclick string.
      var row=document.createElement('div'); row.className='u-row'; row.setAttribute('data-username', d.username);
      var span=document.createElement('span'); span.className='u-name'; span.textContent=d.username;
      var btn=document.createElement('button'); btn.type='button'; btn.className='btn btn-danger'; btn.textContent='Remove';
      btn.onclick=function(){ removeUser(btn); };
      row.appendChild(span); row.appendChild(btn);
      el('users-list').appendChild(row);
      el('new-username').value=''; el('new-password').value=''; el('new-confirm').value='';
      st.innerHTML='<span class="st-done">✓ Account "'+escH2(d.username)+'" created.</span>';
    }).catch(function(){ st.innerHTML='<span class="st-failed">⚠ network error</span>'; });
  return false;
}
function removeUser(btn){
  // Read the username back off the row's data attribute rather than a
  // templated/interpolated JS argument -- see the comment in addUser() above.
  // Whether this is YOUR OWN row is read the same way, off the server-rendered
  // ".u-you" marker already on the page -- no second templated JS value needed.
  var row=btn.closest('.u-row');
  var username=row.getAttribute('data-username');
  var isSelf = !!row.querySelector('.u-you');
  var msg = isSelf
    ? 'Remove your own account "'+username+'"?\\n\\nYou will be signed out immediately, on every device.'
    : 'Remove account "'+username+'"?\\n\\nThey will be signed out on every device immediately.';
  if(!confirm(msg)) return;
  var st=el('add-user-status');
  fetch('/api/users/remove',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:username, csrf:CSRF})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ st.innerHTML='<span class="st-failed">⚠ '+escH2(d.error)+'</span>'; return; }
      // Self-removal kills the caller's own session server-side immediately
      // (get_web_user_session_epoch returns None once the account is gone) --
      // send them to /login rather than leave a dead session sitting on the
      // Panel page looking functional until their next click fails.
      if(isSelf){ location.href='/login'; return; }
      row.remove();
      if(!el('users-list').querySelector('.u-row')){
        var e=document.createElement('div'); e.className='p-note'; e.id='users-empty'; e.textContent='No accounts.';
        el('users-list').appendChild(e);
      }
    }).catch(function(){ st.innerHTML='<span class="st-failed">⚠ network error</span>'; });
}
// Option toggles. A checkbox here does NOT add a flag to the request -- it swaps which
// WHITELISTED action key gets sent, so the server still only ever accepts a fixed set of
// keys and the "never an arbitrary command" property of _panel_run is untouched. Any
// action listed as a `variant` is hidden from the button list so it can't also render as
// its own button (the checkbox IS its entry point).
var JOB_OPTIONS = {
  'audit':       {variant:'audit-full',   label:'full (byte-compare — slower)',
                  title:'Also hash file CONTENT to catch byte-identical duplicates saved under different ids (Class B). The default fast pass only finds the same id in two places.'},
  'dedup-apply': {variant:'dedup-delete', label:'DELETE instead of quarantining',
                  title:'Redundant copies are deleted outright instead of being moved to _duplicates/. There is no undo and no safety net -- run the preview and the verify step first.'}
};
function renderJobs(){
  var safe=el('jobs-safe'), danger=el('jobs-danger'), adv=el('jobs-advanced');
  var variants={}; Object.keys(JOB_OPTIONS).forEach(function(k){ variants[JOB_OPTIONS[k].variant]=1; });
  ACTIONS.forEach(function(a){
    if(variants[a.action]) return;              // reached via its checkbox, not its own button
    var opt=JOB_OPTIONS[a.action];
    var b=document.createElement('button'); b.className='jobbtn'+(a.destructive?' danger':'');
    b.innerHTML='<span class="t">'+a.label+'</span>';
    var cb=null, numInput=null;
    if(opt){
      var wrap=document.createElement('label');
      wrap.className='job-opt'; wrap.title=opt.title;
      cb=document.createElement('input'); cb.type='checkbox';
      wrap.appendChild(cb);
      wrap.appendChild(document.createTextNode(' '+opt.label));
      // Clicking the checkbox must not also fire the button it sits under.
      wrap.onclick=function(ev){ ev.stopPropagation(); };
      b.appendChild(wrap);
    }
    if(a.int_param){
      // A single bounded integer (test-pull's N), clamped again server-side. Lives inside
      // the button; interacting with it must not fire the run.
      var rng=a.int_range||[1,200];
      var nwrap=document.createElement('label'); nwrap.className='job-opt';
      nwrap.appendChild(document.createTextNode('N '));
      numInput=document.createElement('input'); numInput.type='number';
      numInput.min=rng[0]; numInput.max=rng[1];
      numInput.value=(a.int_default!=null?a.int_default:rng[0]);
      numInput.style.width='56px';
      nwrap.appendChild(numInput);
      nwrap.onclick=function(ev){ ev.stopPropagation(); };
      b.appendChild(nwrap);
    }
    b.onclick=function(){
      var chosen=a;
      if(opt && cb && cb.checked){
        var alt=ACTIONS.concat(ALL_ACTIONS).filter(function(x){ return x.action===opt.variant; })[0];
        if(alt) chosen=alt;
      }
      runJob(chosen, numInput ? numInput.value : null);
    };
    (a.advanced && adv ? adv : (a.destructive?danger:safe)).appendChild(b);
  });
}
var polling=false;
function runJob(a, n){
  if(a.destructive && !confirm('Run: '+a.label+'?\\n\\nThis changes files on disk (reversible). Continue?')) return;
  var payload={action:a.action, confirm:true};
  if(n!=null && n!=='') payload.n=n;           // only test-pull sends it; server clamps + ignores elsewhere
  fetch('/api/panel/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ el('jobstatus').innerHTML='<span class="st-failed">\\u26a0 '+escH2(d.error)+'</span>'; return; }
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
    if(d.status==='running'){ st.innerHTML='<span class="st-running">\\u25c9 running: '+escH2(d.label)+'\\u2026</span>'; stop.style.display=''; setButtons(true); setTimeout(poll,1000); }
    else { setButtons(false); polling=false; stop.style.display='none';
      if(d.status==='done'){ st.innerHTML='<span class="st-done">\\u2713 '+escH2(d.label||'job')+' finished (exit '+d.rc+')</span>'; loadAcct(); }
      else if(d.status==='done_with_errors'){ st.innerHTML='<span class="st-warn">\\u26a0 '+escH2(d.label||'job')+' finished with errors \\u2014 '+(d.warn_count||0)+' file(s) failed (exit '+d.rc+')</span>'; loadAcct(); }
      else if(d.status==='cancelled'){ st.innerHTML='<span class="st-failed">\\u25a0 '+escH2(d.label||'job')+' stopped by you</span>'; loadAcct(); }
      else if(d.status==='failed'){ st.innerHTML='<span class="st-failed">\\u26a0 '+escH2(d.label||'job')+' failed (exit '+d.rc+')</span>'; }
      else { st.innerHTML='<span class="st-warn">? '+escH2(d.label||'job')+' ended in an unrecognized state ('+escH2(String(d.status))+')</span>'; loadAcct(); }
    }
  }).catch(function(){ polling=false; setButtons(false); });
}
function stopJob(){
  if(!confirm('Stop the running job?\\n\\nDry-runs/backups have nothing to undo; Organize and Dedup are reversible (Organize writes an undo manifest, Dedup quarantines to _duplicates/, nothing is deleted).')) return;
  el('job-stop').disabled=true;
  fetch('/api/panel/cancel',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
    el('job-stop').disabled=false;
    if(d.error) el('jobstatus').innerHTML='<span class="st-failed">\\u26a0 '+escH2(d.error)+'</span>';
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
  st.innerHTML='<span class="st-running">\\u25c9 Pulling task '+escH2(tid)+'\\u2026</span>';
  fetch('/api/import-task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:tid})})
    .then(function(r){return r.json();}).then(function(d){
      if(d.error){ st.innerHTML='<span class="st-failed">\\u26a0 '+escH2(d.error)+'</span>'; return; }
      if(d.already){ var n=(d.media_ids||[]).length, mid=(d.media_ids||[])[0];
        st.innerHTML='<span class="st-done">\\u2713 Already in your gallery ('+n+' item'+(n===1?'':'s')+')'
          +(mid?' \\u2014 <a href="/image/'+mid+'" style="color:var(--lavender);text-decoration:underline;">view it \\u2192</a>':'')+'</span>'; return; }
      if(!d.saved){ st.innerHTML='<span class="st-failed">\\u26a0 Task resolved but no media to import.</span>'; return; }
      st.innerHTML='<span class="st-done">\\u2713 Imported '+d.saved+' item(s) from task '+escH2(tid)+' \\u2014 open the gallery to see it.</span>';
      document.getElementById('import-tid').value=''; loadAcct();
    }).catch(function(){ st.innerHTML='<span class="st-failed">\\u26a0 network error</span>'; });
}
function loadSchedule(){
  var sel=el('sch-action');
  ALL_ACTIONS.filter(function(a){return !a.destructive && !a.advanced;}).forEach(function(a){
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
// Echo the interval using the dropdown's OWN label for that value, never a
// re-formatted number: the confirmation used to read "every 168h" beside a
// dropdown reading "1 week", so the app appeared to have saved something other
// than what was picked. Reading the option back means the two cannot disagree
// again, including for any interval added to the list later.
function _schIntervalLabel(hours){
  var opts=el('sch-interval').options;
  for(var i=0;i<opts.length;i++){ if(+opts[i].value===+hours) return opts[i].text; }
  return hours+'h';   // value not in the list (hand-edited config): show the raw number
}
function saveSchedule(){
  var body={enabled:el('sch-enabled').checked, action:el('sch-action').value, interval_hours:+el('sch-interval').value};
  fetch('/api/panel/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).then(function(s){
      if(s.error){ el('sch-status').textContent='\\u26a0 '+s.error; return; }
      el('sch-status').innerHTML='<span style="color:var(--emerald)">\\u2713 saved'+(s.enabled?(' \\u00b7 every '+_schIntervalLabel(s.interval_hours)+' while open'):' \\u00b7 disabled')+'</span>';
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
        // A locked card was dimmed with opacity:.5, which composited its 10px
        // description down to a measured 2.57:1 and its "locked" label to 1.88:1 --
        // the latter under even the 3:1 large-text floor. .82 still reads as
        // clearly inactive but keeps the text legible (measured 9.00 name /
        // 4.77 desc / 4.77 locked). Re-measure if you change it; the label below
        // also had to come off --overlay0, which is too dim to survive any dimming.
        +(s.earned?'cursor:pointer;':'opacity:.82;');
      var sw=(SKIN_SW[s.id]||SKIN_SW.moonglade).map(function(h){
        return '<i style="flex:1;background:'+h+'"></i>'; }).join('');
      c.innerHTML='<div style="height:30px;border-radius:7px;display:flex;overflow:hidden;margin-bottom:7px;">'+sw+'</div>'
        +'<div style="font-size:12px;font-weight:600;color:var(--text);">'+escH(s.name)
        +(active?' <span style="color:var(--accent)">\\u2713</span>':'')+'</div>'
        +'<div style="font-size:10px;color:var(--subtext);margin-top:2px;">'+escH(s.desc)+'</div>'
        +(s.earned?'':'<div style="font-size:10px;color:var(--subtext);margin-top:3px;">\\ud83d\\udd12 locked</div>');
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
      // Transient confirmation: nothing else ever cleared #skin-status, so the "applied"
      // line lingered indefinitely -- and since a LOCKED card is inert (no handler), a
      // later click on one left the stale success showing, reading as though the locked
      // skin had applied. Clear it after a few seconds; re-arm on each pick.
      var st=el('skin-status'); st.innerHTML='<span style="color:var(--emerald)">\\u2713 skin applied suite-wide</span>';
      if(window._skinMsgTimer) clearTimeout(window._skinMsgTimer);
      window._skinMsgTimer=setTimeout(function(){ if(st) st.innerHTML=''; }, 3500);
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
        import pixai_gallery_backup as core
        session.clear()
        session["user"] = username
        session["sess_epoch"] = core.get_web_user_session_epoch(username)
        session["csrf"] = secrets.token_hex(16)
        session.permanent = True

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Session-based login gate for every non-localhost request (see
        _is_authorized_request() above). GET renders the form; POST verifies the
        CSRF token, then credentials, then signs in. Any failure (rate-limited,
        bad CSRF, bad credentials) re-renders the SAME form with one generic
        "invalid username or password" message -- never which field was wrong --
        and a freshly rotated CSRF token.

        Local-only first-account bootstrap (first-run setup happens in the
        browser, never the CLI): while NO
        accounts exist yet, a request from the machine the server itself runs on
        (_is_local_request()) gets this SAME form doubling as an account-creation
        form (a hidden mode=create field) instead of a banner pointing at
        --add-web-user. A request for that same zero-accounts state from a LAN
        address never even sees that form -- and `bootstrap_mode` below is the
        REAL race-condition guard, not just the template branch that hides the
        form from it: a hand-crafted mode=create POST from a non-local address,
        or one that arrives after the first account already exists, is refused
        before add_or_update_web_user is ever called, regardless of what HTML
        was ever rendered to that requester.

        The lockout check and the CSRF check run FIRST, ahead of that
        wants_create/bootstrap_mode gate, exactly like an ordinary credential
        POST -- a mode=create POST is not a different, lesser-checked request
        shape (regression fix: the gate used to sit ahead of
        both, so a mode=create POST from an already-lockout-triggering IP sailed
        through with neither the lockout message nor any CSRF requirement,
        confirmed reproducible). Reordering does NOT weaken the bootstrap
        boundary itself: passing the lockout/CSRF checks only earns a request
        the SAME generic error the old ordering gave it once bootstrap_mode is
        false -- create still never proceeds without bootstrap_mode true,
        checked explicitly right below, not inferred from CSRF validity."""
        error = None
        next_url = _safe_next(request.values.get("next", "")) or ""
        import pixai_gallery_backup as core
        no_accounts = not core.list_web_users()
        is_local = _is_local_request()
        bootstrap_mode = no_accounts and is_local
        if request.method == "POST":
            ip = _client_ip()
            locked_for = _login_seconds_locked(ip)
            submitted_csrf = request.form.get("csrf", "")
            live_csrf = session.get("csrf", "") or ""
            wants_create = request.form.get("mode") == "create"
            if locked_for is not None:
                mins = max(1, (locked_for + 59) // 60)
                error = ("Too many failed attempts from this address. "
                        "Try again in about {} minute{}.".format(mins, "" if mins == 1 else "s"))
            elif not (live_csrf and secrets.compare_digest(submitted_csrf, live_csrf)):
                error = "Your session expired. Reload the page and try again."
            elif wants_create and not bootstrap_mode:
                # Defense in depth: honor a create-account submission ONLY while
                # bootstrap_mode is true for THIS request -- a remote requester
                # can legitimately hold a valid csrf token for ITSELF (nothing
                # stops a LAN device from GETting /login and receiving one), so
                # csrf validity alone must never be read as "this create
                # request is allowed".
                error = ("No account has been set up yet. Ask whoever runs this "
                        "server to sign in from the machine itself first.") if no_accounts \
                        else "Invalid username or password."
            else:
                # Reserve this attempt atomically, immediately before the slow
                # password-hash comparison below runs. Closes a TOCTOU race:
                # `locked_for` above is a fast, lock-protected READ taken before
                # verify_web_user()'s slow (unlocked) scrypt comparison: many
                # concurrent requests from the same IP could all pass that read
                # while each was still inside its own verify_web_user() call, so
                # the counter wouldn't reflect any of them until the whole burst
                # finished -- N free guesses per lockout cycle instead of 5. See
                # _login_try_acquire's docstring. Applied identically to the
                # bootstrap create path (below) as to a normal credential guess --
                # same infrastructure, same reuse principle as the CSRF check.
                relocked_for = _login_try_acquire(ip)
                if relocked_for is not None:
                    mins = max(1, (relocked_for + 59) // 60)
                    error = ("Too many failed attempts from this address. "
                            "Try again in about {} minute{}.".format(mins, "" if mins == 1 else "s"))
                elif wants_create:
                    # bootstrap_mode is guaranteed True here -- the guard above
                    # already rejected wants_create whenever it's False.
                    username = (request.form.get("username") or "").strip()
                    password = request.form.get("password") or ""
                    confirm = request.form.get("confirm") or ""
                    un_problem = core.username_problem(username)
                    pw_problem = core.password_problem(password)
                    if un_problem:
                        error = un_problem
                    elif pw_problem:
                        error = pw_problem
                    elif password != confirm:
                        error = "Passwords do not match."
                    else:
                        core.add_or_update_web_user(username, password)
                        _login_clear(ip)
                        _establish_session(username)
                        return redirect(_safe_next(next_url) or url_for("index"))
                else:
                    username = (request.form.get("username") or "").strip()
                    password = request.form.get("password") or ""
                    if username and core.verify_web_user(username, password):
                        _login_clear(ip)
                        _establish_session(username)
                        return redirect(_safe_next(next_url) or url_for("index"))
                    error = "Invalid username or password."
                    # If THIS failure is the one that tripped the lockout, say so now.
                    # _login_try_acquire reserves the attempt up front and returns None
                    # so the attempt may proceed -- which is right, a correct password
                    # on the 5th try must still work -- but it means the request that
                    # crosses the threshold otherwise renders the ordinary "invalid"
                    # message and the user is locked WITHOUT BEING TOLD. They then wait,
                    # retype the correct password, and get refused for 15 minutes with no
                    # idea why. (The function's own docstring already promised to report
                    # a lockout that "was just now triggered"; the code did not.)
                    just_locked = _login_seconds_locked(ip)
                    if just_locked is not None:
                        mins = max(1, (just_locked + 59) // 60)
                        error = ("Too many failed attempts from this address. "
                                 "Try again in about {} minute{}.".format(
                                     mins, "" if mins == 1 else "s"))
        if request.method == "POST":
            # A POST that fell through to an error above: always hand back a
            # FRESH CSRF token -- one that was just consumed or never matched
            # must never be resubmittable.
            session["csrf"] = secrets.token_hex(16)
        else:
            # GET: reuse whatever token this session already holds rather than
            # unconditionally minting a new one. The front door redirects EVERY
            # unauthenticated request here, including ones a browser fires on
            # its own the instant this page loads (favicon.ico, sw.js,
            # manifest.webmanifest, apple-touch-icon, ...) via next=<asset
            # path> -- each of those is a real GET that used to silently
            # overwrite session["csrf"] before the human ever touched the
            # form, orphaning the token already baked into the visible page's
            # hidden input. Reproduced: load /login, let one such incidental
            # GET land, then submit the original form -- "Your session
            # expired" every time, unconditionally, no matter how many times
            # cookies are cleared or the server restarted (the bug re-fires
            # instantly on the very next page load). setdefault leaves an
            # existing token alone and only mints one the first time this
            # session has none, so the visible form's token stays valid
            # across any number of these background hits.
            session.setdefault("csrf", secrets.token_hex(16))
        return render_template_string(LOGIN_HTML, error=error, csrf=session["csrf"],
                                      next_url=next_url, no_accounts=no_accounts,
                                      bootstrap_mode=bootstrap_mode)

    # Served by logout() in place of a redirect -- see its own comment for why a
    # real page (not a 3xx) is required to run the Cache Storage purge. Static, no
    # Jinja/user input involved, so a plain string is safer than round-tripping it
    # through render_template_string for nothing.
    _LOGOUT_HTML = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Signing out…</title>"
        "<style>body{margin:0;height:100vh;display:flex;align-items:center;"
        "justify-content:center;background:#0b0a12;color:#cfd0e0;"
        "font:14px system-ui,sans-serif}</style></head>"
        "<body>Signing you out… <a href=\"/login\">Continue</a>"
        "<script>(function(){"
        "function go(){location.replace('/login');}"
        "if('caches' in window){"
        "caches.keys().then(function(ks){"
        "return Promise.all(ks.map(function(k){return caches.delete(k);}));"
        "}).catch(function(){}).then(go);"
        "}else{go();}"
        "})();</script>"
        "<noscript><meta http-equiv=\"refresh\" content=\"0;url=/login\"></noscript>"
        "</body></html>"
    )

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        """Sign out. A GET clears THIS browser's cookie and nothing else; a POST
        carrying the session's csrf token ALSO revokes every other outstanding
        session for this identity, by bumping its sess_epoch.

        The split exists because the global revoke used to hang off a bare GET with
        no token (docs/STATE.md's "/logout is a CSRF-able GET that revokes
        globally"). SESSION_COOKIE_SAMESITE="Lax" already killed the
        <img src=".../logout"> version of that -- a cross-site SUBRESOURCE carries
        no cookie, so the handler saw an anonymous request and skipped the bump --
        but Lax deliberately still sends the cookie on a cross-site TOP-LEVEL GET
        navigation. Any page that got the owner to follow a link (or ran
        location.href=, window.open, a meta refresh) signed them out on the desktop,
        the phone and the tablet at once. Same for any link-prefetcher or crawler
        that walks the header: a GET must not write server state, and this one did.
        Lax blocks a cross-site POST outright, and the csrf field checked below is
        the same session-bound token /login's form and the Panel's Users tab already
        carry -- belt and braces, so this does not silently re-open if SameSite is
        ever loosened for an HTTPS/reverse-proxy deployment.

        What a cross-site GET can still do is drop this one browser's cookie. That
        is the irreducible floor for any sign-out reachable by navigation, it writes
        NOTHING server-side, and the user recovers by signing in again -- versus the
        old behaviour, which kicked every other device they own.

        `scope=this-device` on the POST skips the global revoke (sign out here
        only). Its ABSENCE means global: a truncated or hand-built POST has to fail
        toward MORE revocation, never less, because the whole mechanism exists to
        kill a cookie captured off plain-HTTP LAN traffic (see
        pixai_gallery_backup.get_web_user_session_epoch's docstring)."""
        import pixai_gallery_backup as core
        user = session.get("user")
        # A DEAD cookie must not be allowed to REVOKE. /logout is in _PUBLIC_PATHS so
        # _enforce_front_door() never runs here, and app.secret_key persists across
        # restarts -- so an already-revoked cookie still DESERIALIZES, and without
        # this check it stayed a valid "log this identity out" token forever.
        # Replayed in a loop it bumped the epoch on every hit, kicking the real user
        # off the instant they signed back in: no credential needed, and recoverable
        # only by rotating AUTH_SECRET_KEY, which the owner has no signal to do.
        #
        # ORDER MATTERS: read `user` BEFORE calling _is_authorized_request(), which
        # calls session.clear() on the stale path. Swapping these two lines silently
        # disables the bump for everyone.
        authorized = bool(user) and _is_authorized_request()
        if request.method == "POST" and authorized:
            # _check_csrf is defined further down in this same create_app() closure
            # (with the Panel's Users tab, its other caller); it is bound long before
            # any request can reach this line.
            #
            # A bad token is a loud 400, NOT a quiet downgrade to a local-only sign
            # out: if the header form ever stopped emitting the field, a silent
            # downgrade would delete the global revoke and nothing would notice. The
            # session is deliberately left INTACT -- the user reloads and clicks
            # again. Note the token buys nothing against someone who already holds
            # the cookie (Flask's session cookie is signed, not encrypted, so the
            # token is readable inside it); the _is_authorized_request() check above
            # is what stops a stolen-cookie replay, and it stays.
            if not _check_csrf(request.form):
                return ("Your session expired. Reload the page and try again.", 400)
            if request.form.get("scope") != "this-device":
                # BEFORE the local clear, so this revokes EVERY outstanding cookie
                # for this username -- e.g. one captured off plain-HTTP LAN traffic
                # before the click -- not just this browser's copy.
                core.bump_web_user_session_epoch(user)
        # Unconditional and outside the guard: whoever holds an already-invalid cookie
        # must still be able to shed it locally. Client-side only, touches no server
        # state, and leaves the anonymous case a harmless no-op.
        session.clear()
        # Cache Storage (used by /sw.js for the installed/PWA view) is browser-side
        # state a redirect can't touch -- the server can clear the SESSION but not
        # what the browser itself cached under /img/ and /full/. A bare redirect()
        # never runs script, so the purge has to happen from an actual page: this
        # unconditional (same reasoning as session.clear() above -- even an
        # already-signed-out /logout hit should leave a clean cache) 200 response
        # deletes every Cache Storage entry client-side, then does the SAME
        # navigation to /login a redirect would have. This must NOT be hooked onto
        # /login instead: login() has no signed-in short-circuit, so purging there
        # would wipe a currently-signed-in user's cache on a stray bookmark/Back
        # hit to /login (the flaw that got an earlier draft of this fix rejected).
        return _LOGOUT_HTML

    # ------------------------------------------------------------------
    # THE front door: DEFAULT-DENY for every request, enforced in one place.
    # ------------------------------------------------------------------
    # Allowlist is intentionally tiny -- /login (GET, to render the form; POST,
    # to submit it) and /logout. LOGIN_HTML is BASE_HTML with fully inline CSS
    # (__DESIGN_TOKENS__ is a Python string substituted at import time via
    # .replace(), never a fetched stylesheet) and no <link>/<script src> to a
    # /static/ file is load-bearing for it to render or submit -- the mark
    # <img> already carries onerror="this.remove()" as a safety net either way.
    # /branding/ IS additionally public (see _PUBLIC_PREFIXES below): it was
    # briefly left gated on the theory that a missing logo is a harmless
    # degrade, but the actual effect was the real chosen mark/banner/favicon
    # never rendering on the one page every visitor -- including a
    # not-yet-authenticated LAN device -- is guaranteed to see. That route
    # only serves static drop-in art (banner/logo/marks/mascots) with path
    # traversal already rejected (see branding()); there's no user data,
    # credential, or spend behind it, so it carries the same public trust
    # tier as /login itself, not a re-opened security gap.
    # /manifest.webmanifest joined this set on 2026-07-21, on the same reasoning as
    # /branding/ and then some. Its handler builds a compile-time CONSTANT -- app name,
    # start_url "/", two hex colours and an inline data: URI SVG icon. There is no code
    # path in it that reflects a user, a catalog, an install path or a credential, so
    # there is nothing to withhold. The "but it fingerprints the install" objection dies
    # on inspection: /login is itself public and renders branded HTML that identifies
    # this app far more loudly than a manifest ever could.
    #
    # The positive reason to make it public is stronger than the neutral one. A browser
    # fires this request BY ITSELF the instant the login page loads, and the front door
    # answered it with a redirect to /login?next=/manifest.webmanifest -- which is
    # exactly the traffic that produced the csrf-overwrite bug documented at the GET
    # branch of login() ("Your session expired", unconditionally, on every submit).
    # setdefault fixed the symptom; letting these self-fired static assets through is
    # what removes the category.
    _PUBLIC_PATHS = frozenset({"/login", "/logout", "/manifest.webmanifest"})
    _PUBLIC_PREFIXES = ("/branding/",)
    # Routes whose EXISTING contract (long before this hook existed) was JSON,
    # not an HTML page -- these get a JSON 401 instead of a login redirect, so a
    # fetch(...).then(r => r.json()) caller still gets parseable JSON instead
    # of choking on the login page's HTML. Everything under /api/, plus the two
    # legacy non-/api/ JSON routes (/rate/<id>, /edit-prompt/<id>) match this.
    _JSON_GATE_PREFIXES = ("/api/", "/rate/", "/edit-prompt/")

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

    @app.route("/health")
    def health():
        return render_template_string(
            HEALTH_HTML, h=collection_health(out_dir, db_path))

    @app.route("/panel")
    def panel():
        # actions -> Maintenance buttons (panel_visible only). all_actions -> the
        # scheduler dropdown, which needs the background-only jobs too (that's their
        # only home now that they're not buttons).
        all_actions = [{"action": k, "label": v["label"], "destructive": v["destructive"],
                        "advanced": v.get("advanced", False),
                        "int_param": v.get("int_param", False),
                        "int_default": v.get("int_default"),
                        "int_range": v.get("int_range")}
                       for k, v in PANEL_ACTIONS.items()]
        actions = [a for a, (k, v) in zip(all_actions, PANEL_ACTIONS.items())
                  if v.get("panel_visible", True)]
        import pixai_gallery_backup as core
        # Reuse whatever csrf token this session already carries (set at login
        # time by _establish_session) -- only mint one here if it's somehow
        # missing. Unlike /login's form, the Users tab's Add/Remove actions are
        # fired via fetch() without a full page reload in between, so the token
        # must stay valid across multiple calls on the same page, not rotate
        # after each one.
        session.setdefault("csrf", secrets.token_hex(16))
        # out_dir is a HOST FILESYSTEM PATH -- withheld from a LAN caller the same way
        # /api/panel/status's job stdout is (2026-07-21 audit, S2): it's unrelated to
        # this route's actual trust decision. Usernames on this same page stay visible
        # to every signed-in session on purpose -- reading the roster isn't the same
        # action as adding to or removing from it, and that's a different, narrower
        # question than the one below. A server install path is a different kind of
        # fact -- it identifies the owner's machine, not a fellow account -- and the
        # front door never signed up to expose it past the loopback boundary.
        panel_out_dir = str(out_dir) if _is_local_request() else "(local to the server)"
        # panel_is_local drives the Users tab's UI: as of 2026-07-22, adding an account
        # or removing someone ELSE's is LOCALHOST-only (api_users_add/_remove) -- a LAN
        # session can still remove its OWN row. Hiding the controls it can't use avoids
        # a confirm-dialog-then-403 dead end; the server enforces the same boundary
        # regardless of what this flag renders, so getting this wrong is a UX
        # regression, not a security one.
        panel_is_local = _is_local_request()
        return render_template_string(
            PANEL_HTML, stats=catalog_counts(db_path), build_stamp=build_stamp,
            all_actions_json=json.dumps(all_actions),
            out_dir=panel_out_dir, actions_json=json.dumps(actions),
            supervised=_supervised(), panel_is_local=panel_is_local,
            web_users=core.list_web_users(), csrf=session["csrf"],
            current_username=session.get("user"))

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
        finding with two halves (see docs/STATE.md's Access & accounts section).
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
        import pixai_gallery_backup as core
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
        a durable login in the same motion. See docs/STATE.md's Access &
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
        import pixai_gallery_backup as core
        result = core.remove_web_user_guarded(username)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "last_account":
            return jsonify({"error": "Can't remove the last remaining account -- "
                                     "that would lock every remote device out until "
                                     "someone signs in locally to bootstrap a new one."}), 400
        return jsonify({"ok": True, "username": username})

    @app.route("/api/ping")
    def api_ping():
        """Cheap liveness probe — the Stop/Restart reconnect overlay polls this. Login required
        (any session, local or LAN)."""
        return jsonify({"ok": True})

    @app.route("/api/server/stop", methods=["POST"])
    def api_server_stop():
        """Shut the server down cleanly from the browser (Homebridge-style) instead of Task
        Manager. Login required (any session, local or LAN). Under the managed launcher this ends the whole app."""
        _schedule_server_exit(0)
        return jsonify({"ok": True, "action": "stop"})

    @app.route("/api/server/restart", methods=["POST"])
    def api_server_restart():
        """Restart the server from the browser. Needs the managed launcher (Serve Gallery),
        which relaunches on exit code 42; otherwise the process would just stop. Login required (any session, local or LAN)."""
        if not _supervised():
            return jsonify({"error": "Restart needs the managed launcher — start via "
                                     "'Serve Gallery'. (Stop still works.)"}), 409
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
            # query_catalog paginates: count the matches first, then take that many in a
            # single page, so a filtered export is never silently truncated. `sort` isn't a
            # filter (it never changes WHICH rows match) so it's passed separately -- and
            # an unknown value falls back to the default order inside query_catalog.
            _, total = query_catalog(db_path, page=1, page_size=1, **filters)
            rows, _ = query_catalog(db_path, page=1, page_size=max(total, 1),
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
        with _panel_lock:
            if _panel_job["status"] == "running":
                return jsonify({"error": "a job is already running"}), 409
        try:
            # `n` is only consumed by an int_param action (test-pull); _panel_run
            # clamps it into range and ignores it otherwise, so passing it always is safe.
            _panel_run(action, int_arg=body.get("n"))
            return jsonify({"ok": True, "action": action, "label": spec["label"]})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

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
            res = _collect_single_flight(core, session, tid)
            n, mids = int(res.get("saved") or 0), (res.get("media_ids") or [])
            _log_job(job_id, status="done", media_ids=mids,
                     label="Imported {} media from task {}".format(n, tid))
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

        stats = catalog_counts(db_path)
        # First-run wizard gating: a FRESH read of config.json, not the module-cached
        # core._cfg -- someone who just pasted a key via the wizard needs this to flip on
        # the very next page load, not after a process restart. Real catalog size (not the
        # current search/filter's `total`) is what decides "never synced yet".
        #
        # needs_key/catalog_empty no longer AND against _is_authorized_request(): reaching
        # this line at all now guarantees it -- the global _enforce_front_door() hook (see
        # its docstring) already enforced it for this exact request, since `/` carries no
        # allowlist exemption. Before that hook existed, `/` had NO gate of its own, so an
        # unauthenticated LAN viewer could land here and see the "paste your API key" setup
        # wizard; that conjunct hid it from them. That viewer can no longer reach this line.
        # `is_local` below (the header template's flag for showing the owner-only
        # Generate/Loom/Panel controls vs. the read-only note) is hardcoded True for the
        # identical reason -- same call site, same guarantee. Import is the one
        # documented exception: it renders under this same flag (grouped with
        # Generate/Loom in the header) but /api/import-local re-checks the stricter
        # _is_local_request() itself, so a signed-in, non-local LAN session sees the
        # button but always gets a 403 -- see the head-nav comment above the Import
        # button itself for the full explanation. `can_delete_cloud` is a
        # DIFFERENT, narrower flag: it drives whether the "Delete from PixAI" bulk-action
        # button renders at all. That button posts to /delete-tasks-bulk, which is gated
        # to the stricter _is_local_request() (irreversible cloud deletion, same trust
        # tier as /api/branding/shortcut) -- a real, un-hardcoded check, so a logged-in
        # LAN session sees "Delete locally" but not "Delete from PixAI".
        import pixai_gallery_backup as _core
        _fresh_cfg = _core._load_config()
        needs_key = not bool(_fresh_cfg.get("PIXAI_API_KEY") or _fresh_cfg.get("U3T"))
        catalog_empty = not needs_key and (stats["images"] + stats["videos"]) == 0
        can_delete_cloud = _is_local_request()
        # The header's Sign out control is a POST form now (see INDEX_HTML), so this
        # page has to carry the session's csrf token the same way /login's form and
        # the Panel do. setdefault, never a fresh mint: _establish_session already set
        # one at login, and overwriting it here would orphan the token baked into any
        # other tab the user has open -- the exact bug /login's GET branch documents
        # at length.
        session.setdefault("csrf", secrets.token_hex(16))

        return render_template_string(
            INDEX_HTML,
            chips=chips, published_only=published_only, art_tag=art_tag,
            lora_filter=lora_filter, media_type=media_type, source_filter=source,
            collection=collection, collections=collections,
            rows=page_rows, total=total, page=page, stats=stats,
            needs_key=needs_key, catalog_empty=catalog_empty,
            build_stamp=build_stamp, is_local=True, can_delete_cloud=can_delete_cloud,
            logged_in_user=session.get("user"), csrf=session["csrf"],
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
        to the Activity card; localhost-only (this destroys on the owner's account) --
        same trust tier as /api/branding/shortcut and destructive Panel actions, gated
        to the stricter _is_local_request(), NOT the broader _is_authorized_request()
        that the front-door hook enforces for everything else. A logged-in LAN session
        unlocks browsing and spending the owner's credits, not irreversible deletion
        from the owner's real cloud account. (This check was dropped during the
        LAN-auth conversion pass and restored 2026-07-19 per adversarial review --
        see CHANGELOG.md.)"""
        import urllib.parse
        import uuid
        import pixai_gallery_backup as core   # lazy: avoid import cycle
        back = request.form.get("back") or url_for("index")

        def _back(**params):
            sep = "&" if "?" in back else "?"
            return redirect(back + sep + urllib.parse.urlencode(params))

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
        # Same shape as /collection-add, including the one-shot count in the query
        # string: `back` normally carries the collection filter the removal happened
        # under, so the reloaded grid is missing those rows and the banner is the only
        # thing that says how many left. `uncollected` (not `removed`, which the
        # cloud-delete banner already owns) keeps the two banners independent.
        back = request.form.get("back") or url_for("index")
        ids = request.form.getlist("media_ids")
        name = request.form.get("name", "")
        n = remove_from_collection(db_path, ids, name)
        sep = "&" if "?" in back else "?"
        return redirect("{}{}uncollected={}".format(back, sep, n))

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

    @app.route("/thumbs/<media_id>.jpg")
    def thumb(media_id):
        resp = send_from_directory(str(thumb_dir), "{}.jpg".format(media_id),
                                   max_age=300)
        resp.headers["Cache-Control"] = _THUMB_CACHE
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
        # Cache-first for write-once originals; stale-while-revalidate for thumbnails;
        # network for everything else. Only OK (200) responses are cached -- NEVER a 404 --
        # so a thumbnail that didn't exist yet (poster-less video mid-collect) can't get its
        # miss frozen in. Bumping the cache name + deleting old caches on activate self-heals
        # any client holding a poisoned entry from an older version (no hard-refresh needed).
        #
        # v3: /thumbs/ moved OFF cache-first. This worker ignores Cache-Control entirely --
        # `c.match()` returns a hit without ever revalidating -- so cache-first pinned every
        # thumbnail for the lifetime of the cache. `--rebuild-thumbs` rewrites posters in
        # place at the same media_id URL, so the repair was invisible to any client that had
        # already cached the broken one. Same failure shape as the v1 404 poisoning, one
        # status code over. Originals stay cache-first: their bytes really are write-once.
        #
        # The thumb refetch passes cache:'no-cache' so it revalidates against the server
        # instead of being answered by the HTTP cache's own max-age -- otherwise the
        # "revalidate" half of stale-while-revalidate is a no-op until max-age expires.
        # It costs one conditional request per thumb per view, answered by a ~200-byte 304
        # off the ETag, and it never blocks paint (the cached bytes render immediately).
        # LAN viewers over plain http get no service worker at all (secure-context only) --
        # for them the route's short max-age + ETag is what bounds staleness.
        # v4: `resp.ok` is NOT a sufficient cache guard, because a GATED response here is
        # not a failure -- it is a 200. /thumbs/, /img/ and /full/ are not under
        # _JSON_GATE_PREFIXES, so an unauthorized request for one gets the front door's
        # `redirect(url_for("login", ...))`, and an <img> subresource has redirect mode
        # "follow" -- the browser follows it and hands the worker the LOGIN PAGE with
        # status 200, ok===true, redirected===true. That HTML then gets written into Cache
        # Storage under the IMAGE's url.
        #
        # On /thumbs/ it self-heals (stale-while-revalidate overwrites on the next good
        # fetch). On /img/ and /full/ it does not: that branch is `r=>r||fetch(...)`,
        # cache-first with no revalidation on a hit, so those images render broken from
        # then on -- surviving re-login, reloads and server restarts, curable only by
        # Ctrl+Shift+R or this cache-name bump.
        #
        # The trigger is routine, not exotic: the header's Sign out is a GLOBAL revoke
        # (bump_web_user_session_epoch), so signing out on the desktop kills the tablet's
        # session while its grid is still lazy-loading. Same shape as the v1 bug (froze
        # 404s) and the v2 bug (pinned stale posters), one status code over.
        sw = (
            "const C='pixai-img-v4';\n"
            "self.addEventListener('install',e=>self.skipWaiting());\n"
            "self.addEventListener('activate',e=>e.waitUntil(\n"
            "  caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))\n"
            "  .then(()=>self.clients.claim())));\n"
            "self.addEventListener('fetch',e=>{\n"
            " const u=new URL(e.request.url);\n"
            " if(e.request.method!=='GET') return;\n"
            " const isThumb=u.pathname.startsWith('/thumbs/');\n"
            " const isOrig=u.pathname.startsWith('/img/')||u.pathname.startsWith('/full/');\n"
            " if(!isThumb&&!isOrig) return;\n"
            " if(isOrig){\n"
            "  e.respondWith(caches.open(C).then(c=>c.match(e.request).then(\n"
            "   r=>r||fetch(e.request).then(resp=>{if(resp&&resp.ok&&!resp.redirected)c.put(e.request,resp.clone());return resp;}))));\n"
            "  return;\n"
            " }\n"
            " e.respondWith(caches.open(C).then(c=>c.match(e.request).then(r=>{\n"
            "  const n=fetch(e.request,{cache:'no-cache'})\n"
            "          .then(resp=>{if(resp&&resp.ok&&!resp.redirected)c.put(e.request,resp.clone());return resp;})\n"
            "          .catch(()=>r);\n"
            "  return r||n;\n"
            " })));\n"
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
        import pixai_gallery_backup as core
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
                             download_name="pixai_selection_{}.zip".format(n))
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
        first account either via `python pixai_gallery_backup.py --add-web-user`
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
        import pixai_gallery_backup as core
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
    # `python pixai_gallery.py`.
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
        import pixai_gallery_backup as core
        return core, core._make_session(None)

    def _input_media_id(core, session, val):
        """Turn whatever the client sent into a media_id PixAI will accept as an INPUT.

        A media_id in our catalog identifies a generation OUTPUT, and PixAI refuses one
        as an input -- invalid_media_id / invalid_reference_image_media_id, with a full
        refund. Readable is NOT usable-as-input: verified 2026-07-20 that both a
        month-old and a same-day catalog id still resolve fine through GET /v1/media, so
        this is media KIND, not expiry.

        We hold the file on disk (that is what the backup IS), so upload it and hand
        PixAI an upload-kind id. Same free S3 handshake as --upload and /api/upload;
        spends nothing. Cached per media_id for the process lifetime.

        This lives at create_app scope, called by EVERY path that feeds a user-chosen
        image to PixAI -- /api/loom/generate, /api/enhance, /api/edit, /api/fix. The
        first fix for this bug only patched the video route, which left enhance/edit/fix
        silently broken in exactly the same way; a shared helper is what stops the next
        input path from reintroducing it.

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
        ?q=&kind=base|lora&size=N&offset=N&category=&sort=popular|newest.

        Two data sources by design: the REST /search (default) has RICH rows (description /
        refCount / official badge) but silently ignores market filters; the GraphQL
        `generationModels` connection actually honors category + a Newest sort but has leaner
        rows. So we use GraphQL ONLY when a category or Newest is requested, REST otherwise --
        the card renders both (leaner rows just hide the missing fields)."""
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
            return jsonify({"error": _redact_host_paths(str(e))[:200], "results": []}), 200

    @app.route("/api/model-version")
    def api_model_version():
        """Resolve a model_id (from the grid) to its generatable version id + the version
        metadata the picker needs: model_type (for LoRA↔base compat), lora_base_model_type,
        trigger_words (to offer inserting into the prompt), and the author's tuned preset.
        Login required; read-only, one API call."""
        mid = (request.args.get("model_id") or "").strip()
        if not mid:
            return jsonify({"error": "model_id required", "version_id": ""}), 400
        try:
            core, session = _gen_session()
            return jsonify(core.resolve_version_meta(session, mid))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "version_id": ""}), 200

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
                            "error": "similarity index unavailable: " + _redact_host_paths(str(e))[:180]}), 200
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
        """Cached ~256px badge for the Folio of Honors tiles (masters stay the source of
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
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

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
        import pixai_gallery_backup as core
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
        try:
            credits = int(me.get("quotaAmount") or 0)
        except (TypeError, ValueError):
            credits = None
        return jsonify({"ok": True, "credits": credits})

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
        persist_error = None
        with _ach_lock:
            state = load_ach_state(out_dir)
            result = compute_achievements(metrics, state.get("seen"),
                                          sets=load_telemetry(out_dir).get("sets", {}))
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

    @app.route("/api/branding", methods=["GET", "POST"])
    def api_branding():
        """The banner mark (the icon beside the title) + its animation. GET and POST both
        require login (any session, local or LAN) -- cosmetic, so any authorized device may
        read or change it, same as the rest of the LOGIN-tier settings surface.
        Persists to out_dir/branding.json."""
        if request.method == "GET":
            cfg = load_branding(out_dir)
            return jsonify({"mark": cfg["mark"], "anim": cfg["anim"],
                            "anims": MARK_ANIMS, "marks": list_marks(out_dir)})
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
        import pixai_gallery_backup as core
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
        saves one; POST {delete: name} removes one (no UI for it yet -- the verb exists so
        the select's reserved delete affordance has something to call).

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

    def _params_and_nocard(core, p, user):
        """Route a drawer payload to generate, edit, or video params. Returns (params,
        no_card, note). note is set (params None) when something's missing. `user` is
        only consulted on the edit path (a preset lookup is per-account)."""
        p = p or {}
        if p.get("mode") == "edit":
            params = _edit_params_from_payload(core, p, user)
            return (params, bool(p.get("no_card")),
                    None if params else "pick an image to edit")
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
                    is_private=bool(p.get("is_private")))
            except core.PixAIError as e:
                return None, bool(p.get("no_card")), _redact_host_paths(str(e))[:140]
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
            params, no_card, note = _params_and_nocard(core, body, user)
            if params is None:
                return jsonify({"cost": None, "free": False, "note": note})
            cost = core.price_task(gsession, params)
            best = None if no_card else core.match_kaisuuken(gsession, params, enrich=True)
            return jsonify({"cost": cost, "free": bool(best),
                            "cards": (best or {}).get("total"),
                            "card_name": (best or {}).get("name"),
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
            return jsonify({"error": _redact_host_paths(str(e))[:300]}), 200

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
            return jsonify({"error": _redact_host_paths(str(e))[:300]}), 200

    @app.route("/api/enhance", methods=["POST"])
    def api_enhance():
        """One-click enhance (panelplugin) on the Edit tab's source image. Login required;
        auto-applies a card if one matches. A rejected/unknown workflow just errors (no
        credits spent). Returns {task_id, media_ids, paid_credit}."""
        try:
            from types import SimpleNamespace
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            src = _input_media_id(core, session, str(p.get("source") or "").strip())
            wid = str(p.get("workflow_id") or "").strip()
            if not src:
                return jsonify({"error": "pick an image first"}), 400
            if not wid:
                return jsonify({"error": "pick an enhance workflow"}), 400
            params = core.build_panelplugin_parameters(src, wid)
            core._apply_kaisuuken(session, params,
                                  SimpleNamespace(kaisuuken_id="", no_card=bool(p.get("no_card"))))
            task_id = core.submit_generation(session, params)
            telem_bump("enhances", out_dir=out_dir)       # first-enhance milestone
            telem_set_add("tools", "enhance", out_dir=out_dir)
            telem_set_add("enhance_workflows", wid, out_dir=out_dir)  # Enhance Adept: distinct rituals
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:300]}), 200

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
            task_id = core.submit_fixer(session, src, boxes)
            telem_set_add("tools", "fix", out_dir=out_dir)   # Full Toolbox
            return jsonify({"task_id": task_id})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:300]}), 200

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

    def _loom_kv_write(user, key, value):
        """Atomically persist one key's value into the ACCOUNT'S OWN dir (tmp +
        os.replace). Never writes the legacy shared dir -- that stays exactly as
        _loom_migrate() left it, a read-only fallback."""
        p = _loom_kv_path(user, key)
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(value), encoding="utf-8")
        os.replace(tmp, p)

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

    @app.route("/loom/vendor/<path:fname>")
    def loom_vendor(fname):
        """Serve the Loom's vendored JS (React/ReactDOM/Babel UMD builds) from
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
        loom/) -- the NEW, opt-in delivery path (/loom?bundle=1). Same path-safety
        pattern as loom_vendor(). Absent files 404; loom() below treats that as
        'bundle not built yet' and falls back to the Babel-standalone page rather
        than erroring. max_age=0 (unlike the vendor libs) since this output changes
        every time the source is rebuilt."""
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

        Two delivery paths (see LOOM_PAGE / LOOM_PAGE_BUNDLE above):
        default is the in-browser Babel-standalone transpile (unchanged); passing
        ?bundle=1 opts into the pre-built esbuild bundle IF loom/dist/ actually has
        one, else it quietly falls back to the default so a fresh checkout that
        hasn't run `npm run build` yet never breaks."""
        import re as _re
        loom_dir = Path(__file__).resolve().parent / "loom"
        src = loom_dir / "master-storyboard.jsx"
        try:
            jsx = src.read_text(encoding="utf-8")
        except OSError:
            return "Loom source not found (loom/master-storyboard.jsx).", 404

        wants_bundle = request.args.get("bundle") in ("1", "true", "yes")
        bundle_file = loom_dir / "dist" / "master-storyboard.bundle.js"
        if wants_bundle and bundle_file.is_file():
            return LOOM_PAGE_BUNDLE

        # ---- Babel-standalone path (default + bundle-requested-but-not-built) ----
        # loom/src/loom-core.js AND loom/src/loom-mutations.js (Phase 2, the
        # composed-hooks extraction, 2026-07-16) are real ES modules
        # master-storyboard.jsx imports from; this <script type="text/babel">
        # block isn't a real module system, so inline both modules' source
        # ahead of the JSX and strip `export` the same way "export default
        # function App()" is already stripped below.
        core_src = ""
        try:
            core_src = (loom_dir / "src" / "loom-core.js").read_text(encoding="utf-8")
        except OSError:
            pass
        core_inline = _re.sub(r"(?m)^export const ", "const ", core_src)
        # master-storyboard.jsx imports shotPayload aliased (`as buildShotPayload`)
        # for its own local wrapper; provide that name once the real `import {...}`
        # statement below is stripped out.
        if core_inline:
            core_inline += "\nconst buildShotPayload = shotPayload;\n"

        mut_src = ""
        try:
            mut_src = (loom_dir / "src" / "loom-mutations.js").read_text(encoding="utf-8")
        except OSError:
            pass
        mut_inline = _re.sub(r"(?m)^export const ", "const ", mut_src)
        mut_inline = _re.sub(r"(?m)^export function ", "function ", mut_inline)

        jsx = _re.sub(r"(?m)^\s*import\s+React.*$", "", jsx)          # React is a CDN global
        jsx = _re.sub(r"import\s*\{.*?\}\s*from\s*[\"']\./src/loom-core\.js[\"'];?",
                       "", jsx, count=1, flags=_re.S)                  # loom-core is inlined instead
        jsx = _re.sub(r"import\s*\{.*?\}\s*from\s*[\"']\./src/loom-mutations\.js[\"'];?",
                       "", jsx, count=1, flags=_re.S)                  # loom-mutations is inlined instead
        # master-storyboard.jsx imports moveCardToAct aliased (`as mvCardToAct`)
        # so the useShotMutations hook's own returned `moveCardToAct` doesn't
        # collide with the pure reducer of the same name; provide that alias
        # once the real `import {...}` statement above is stripped out.
        if mut_inline:
            mut_inline += "\nconst mvCardToAct = moveCardToAct;\n"
        jsx = jsx.replace("export default function App()", "function App()")
        return LOOM_PAGE.replace("__JSX__", core_inline + "\n" + mut_inline + "\n" + jsx)

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
            keys = own_keys | legacy_keys
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
                # matches _view_presets: the legacy layer is never written back to.
                # An account that never saved its own copy of an inherited/shared key
                # can't make a delete "stick" this way (a later GET still falls through
                # to the legacy value) -- accepted gap, not a bug: this only bites a
                # second account deleting a board it never touched itself, which doesn't
                # happen in the single-owner-plus-occasional-LAN-device use case this
                # feature was built for. Revisit with a per-key tombstone file if that
                # ever changes.
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
        return jsonify({"ok": True})

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
            vid_exts = (".mp4", ".webm", ".mov", ".mkv")
            vid = None
            # find_files_for_media_id defaults to images -- resolve via the catalog's
            # stored filename first, then fall back to the SAME shared matcher with
            # exts=vid_exts, so the fallback gets the same exact media_id_of(p) == mid
            # check and _duplicates/_deleted quarantine exclusion as every other
            # matcher in this file (B17, audit 2026-07-21: the fallback used to be a
            # bare '*<mid>.*' glob with neither -- a file under _deleted/ or
            # _duplicates/ was a valid hit, and a shorter media_id could match as a
            # substring of a longer, unrelated one's filename).
            row = get_row(db_path, mid) or {}
            fn = row.get("filename") or ""
            if fn:
                cand = out_dir / fn
                if cand.is_file() and cand.suffix.lower() in vid_exts:
                    vid = cand
            if vid is None:
                fallback = find_files_for_media_id(out_dir, mid, exts=vid_exts)
                if fallback:
                    vid = fallback[0]
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

            def resolve_img(val):
                s = str(val or "").strip()
                if not s:
                    return ""
                if s.isdigit():
                    # Shared with /api/enhance, /api/edit and /api/fix -- see
                    # _input_media_id. A catalog id is a generation OUTPUT and PixAI
                    # refuses it as an input, so upload the local file we hold.
                    return _input_media_id(core, session, s)
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
                audio_language=(p.get("audio_language") or "english"),
                negative=(p.get("negative") or "").strip(),
                is_private=bool(p.get("is_private")))
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
            return jsonify({"error": _redact_host_paths(str(e))[:300]}), 200

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
        track never desyncs across a segment boundary. body: {clips:[{mid,in,out}], total_seconds}"""
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
            segs.append((path, ci, co, probe_has_audio(path), crop))
        if not segs:
            return jsonify({"error": "no finished shot videos found on disk to export"}), 400
        _export_dir.mkdir(parents=True, exist_ok=True)
        out_path = _export_dir / "loom_cut.mp4"
        W, H = 1280, 720
        parts, labels = [], ""
        # A silent segment needs an explicit numeric span to synthesize (anullsrc has no
        # natural end); reuse the trim's own end if given, else probe the real file once.
        need_silence = any(not ha for (_p, _ci, _co, ha, _cr) in segs)
        silence_idx = len(segs)   # the synthetic-silence input, appended after all real -i's
        for i, (path, ci, co, has_audio, crop) in enumerate(segs):
            tr = "trim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
            # A per-shot crop happens in SOURCE pixels (iw/ih), before the scale-to-canvas, so
            # the kept region fills the 1280x720 frame. No crop -> the chain is unchanged.
            crop_f = ("crop=iw*%.4f:ih*%.4f:iw*%.4f:ih*%.4f," % (crop[2], crop[3], crop[0], crop[1])) if crop else ""
            parts.append("[%d:v]%s,setpts=PTS-STARTPTS,%sscale=%d:%d:force_original_aspect_ratio=decrease,"
                         "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v%d]" % (i, tr, crop_f, W, H, W, H, i))
            if has_audio:
                atr = "atrim=start=%.3f" % ci + ((":end=%.3f" % co) if co is not None else "")
                parts.append("[%d:a]%s,asetpts=PTS-STARTPTS[a%d]" % (i, atr, i))
            else:
                span = (co - ci) if co is not None else max(0.1, (probe_duration(path) or ci + 0.1) - ci)
                # [silence_idx:a] is a raw decoder-input reference (the lavfi anullsrc), not a
                # named filter output -- ffmpeg allows referencing it multiple times (once per
                # silent segment) without an explicit asplit.
                parts.append("[%d:a]atrim=duration=%.3f,asetpts=PTS-STARTPTS[a%d]" % (silence_idx, span, i))
            # concat's input pads are PER-SEGMENT interleaved (v0,a0,v1,a1,...), never grouped
            # by stream type (v0,v1,...,a0,a1,...) -- ffmpeg errors "media type mismatch" if
            # the pad order doesn't match n*(v+a) in that exact per-segment sequence.
            labels += "[v%d][a%d]" % (i, i)
        fc = ";".join(parts) + ";" + labels + "concat=n=%d:v=1:a=1[vout][aout]" % len(segs)
        cmd = ["ffmpeg", "-y"]
        for (path, _ci, _co, _ha, _cr) in segs:
            cmd += ["-i", path]
        if need_silence:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", str(out_path)]
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
    # _VIDEO_EXTS; not imported directly -- pixai_gallery.py is the lower module in the
    # three-file layering (backup.py imports this file, never the reverse).

    def _loom_collect_media_ids(project):
        """Every real (catalog) media_id a project references -- resultMid, both frame
        slots, and every cast/asset entry. thumbId references are NOT collected: they're
        client-only (base64 in `thumbs`) and already travel inside project.json as-is."""
        ids = set()
        for act in (project.get("acts") or []):
            for c in (act.get("cards") or []):
                if c.get("resultMid"):
                    ids.add(str(c["resultMid"]))
                for slot in ("openFrame", "closeFrame"):
                    f = c.get(slot) or {}
                    if f.get("mediaId"):
                        ids.add(str(f["mediaId"]))
        for a in (project.get("assets") or []):
            if a.get("mediaId"):
                ids.add(str(a["mediaId"]))
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

    @app.route("/api/loom/export-bundle", methods=["POST"])
    def api_loom_export_bundle():
        """Full-bundle export: a zip of project.json (identical shape to the lightweight
        Backup .json) plus every referenced media file under media/<id><ext>. Login required
        -- reads real files off disk, same trust level as /export-zip."""
        import io
        import zipfile
        body = request.get_json(silent=True) or {}
        project = body.get("project") or {}
        thumbs = body.get("thumbs") or {}
        if not project:
            return jsonify({"error": "no project given"}), 400
        mids = _loom_collect_media_ids(project)
        mem = io.BytesIO()
        missing = []
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
            z.writestr("project.json", json.dumps({"project": project, "thumbs": thumbs}))
            for mid in mids:
                p = _loom_resolve_media(mid)
                if not p:
                    missing.append(mid)
                    continue
                z.write(p, arcname="media/{}{}".format(mid, p.suffix.lower()))
        mem.seek(0)
        name = "{}_bundle.zip".format((project.get("name") or "loom_project").replace(" ", "_"))
        resp = send_file(mem, mimetype="application/zip", as_attachment=True, download_name=name)
        # Missing media doesn't fail the export (a partial bundle is still useful) -- the
        # client surfaces this list so the owner knows what didn't travel.
        resp.headers["X-Bundle-Missing-Count"] = str(len(missing))
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

    @app.route("/api/task-status")
    def api_task_status():
        """Poll a submitted task: {phase: running|done|failed}. On 'done' it downloads +
        catalogs the result into this backup and returns media_ids + paid_credit. Read-only
        until done; login required."""
        # Bound HERE, not inside the try: the except clause below names this module,
        # and an except expression is evaluated while handling the exception -- so if
        # _gen_session() were the thing that raised, a try-scoped name would turn a
        # handled error into a NameError.
        import pixai_gallery_backup as _core
        tid = (request.args.get("task_id") or "").strip()
        if not tid:
            return jsonify({"phase": "failed", "error": "task_id required"}), 400
        try:
            core, session = _gen_session()
            st = core.generation_status(session, tid)
            if st["phase"] == "done":
                got = _collect_single_flight(core, session, tid)
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
        except _core.EmptyOutputsError as e:
            # TERMINAL, unlike the transient case below: PixAI already told us the
            # task reached 'done', and collect then found its outputs empty. The task
            # produced nothing and never will, so this MUST write an authoritative
            # 'failed' -- without it the job spins on 'running' in the Jobs card
            # forever. (Observed: an enhance submitted with an unusable input media id
            # sat at 'running' indefinitely while PixAI considered it long finished.)
            _log_job(tid, status="failed", error=_redact_host_paths(str(e))[:200])
            return jsonify({"phase": "failed", "error": _redact_host_paths(str(e))[:200]}), 200
        except Exception as e:
            # A transient PixAI blip (5xx/429/timeout) raises here even though the task may
            # still be running -- or already finished. Do NOT write an authoritative 'failed'
            # job event: that would brick the card with a sticky false failure + a red toast
            # for a task that likely succeeded. Leave the job at its last-known state (it ages
            # out, or the live-mirror watcher collects the real result). Only a genuine
            # st["phase"] == "failed" above logs a terminal failure.
            #
            # The RESPONSE used to say phase:'failed' too, which defeated the whole point of
            # the paragraph above: static/mg-notify.js's Jobs.poll() treats phase==='failed'
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
        survives a reload. The card polls this. Login required, like the creation suite."""
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
        events are written server-side by /api/task-status. Login required (any session, local or LAN)."""
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
        this is how a sticky failure gets cleared. Login required (any session, local or LAN)."""
        import pixai_gallery_backup as core
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
        """Live enhance-workflow catalog (id + name + type) for the Edit tab picker.
        Read-only; login required (uses the owner's key)."""
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
    burned this project twice (docs/STATE.md's verification notes), each time
    costing a debugging session chasing a "fix that didn't work" which had in fact
    worked perfectly in a process nobody was talking to.

    `Serve Gallery.pyw` already probes the X-Moonglade header to decide "one of our
    servers is already up here" before launching. That check lived ONLY in the
    launcher, so `python pixai_gallery.py --port N` -- how every script, test
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
    ap.add_argument("--out", default="pixai_backup",
                    help="backup folder containing catalog.csv (default: pixai_backup)")
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

    out_dir = Path(args.out)
    import pixai_logging
    pixai_logging.setup_logging(out_dir, verbose=args.verbose)
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
              "or run `python pixai_gallery_backup.py --sync` yourself.".format(out_dir))

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
    app.run(host=args.host, port=args.port, debug=False, threaded=True, ssl_context=ssl_context)


if __name__ == "__main__":
    # sys.exit(main()) rather than a bare main(): the port pre-flight signals refusal
    # with `return 2`, and a bare call would discard it and exit 0 -- so a wrapper
    # script would read "server started fine" from a server that refused to start.
    sys.exit(main())

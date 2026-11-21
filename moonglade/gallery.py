#!/usr/bin/env python3
"""
moonglade/gallery.py
================
Local Flask web gallery for your PixAI backup collection.

Reads catalog.db (SQLite) and serves a browseable, filterable, paginated image
gallery at http://localhost:5000 . Supports single and bulk delete (removes
image file, thumbnail, and catalog row).

Requirements:
    pip install flask pillow

Usage (from the app's folder; normally the launcher, Moonglade Launcher, starts it):
    python -m moonglade.gallery
    python -m moonglade.gallery --out pixai_backup --port 5000
"""

import argparse
import csv
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from moonglade import about as _about
from moonglade import account_prefs as _account_prefs
from moonglade import achievements as _achievements
from moonglade import assets as moonglade_assets
from moonglade import branding as _branding
from moonglade import cards as _cards
from moonglade import cloud_delete as _cloud_delete
from moonglade import container as moonglade_container
from moonglade import contest_sync as _contest_sync
from moonglade import contest_wins
from moonglade import contests as _contests
from moonglade import dupes as _dupes
from moonglade import gen_cli as _gen_cli
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import health as _health
from moonglade import jobs as _jobs
from moonglade import living as _living
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import organize as _organize
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import pricing as _pricing
from moonglade import scan as _scan
from moonglade import series as _series
from moonglade import hostcheck as _hostcheck
from moonglade import settings as _settings
from moonglade import task_feed as _task_feed
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import training as _training
from moonglade import updater as _updater
from moonglade import secure_files as _secure_files
from moonglade import web_sessions as _web_sessions

try:
    from flask import (Flask, g as _flask_g, jsonify, redirect, render_template_string, request,
                       send_file, send_from_directory, session, url_for)
    from flask.sessions import SecureCookieSessionInterface
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
    "artwork_id", "title", "is_published", "is_nsfw", "is_sensitive",
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
    # TASK-level: written onto every row of the task, and it says nothing about which
    # individual images survive -- see cloud_deleted_at below for the per-image fact.
    "deleted_remote",
    # PER-IMAGE (2026-09-06): the ISO stamp PixAI puts on THIS image's entry in its task's
    # outputs.batch once the image itself is deleted (from the gallery's per-image delete,
    # or from PixAI's own site). Blank means PixAI still has it. Deliberately NOT
    # deleted_remote: that one is task-level and is cleared again on the next
    # --reconcile-deleted, while this is per-row and permanent. A row carrying this is one
    # whose LOCAL copy is the only copy left anywhere, so the whole-task delete path leaves
    # such rows and their files alone.
    "cloud_deleted_at",
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
    # VIEWS, SYNCED (2026-09-06). Views used to be LIVE-only: twelve GraphQL calls on
    # every My Art open, thrown away after summing. PROBE_2026-09-06 settled that the
    # ad-hoc bulk `artworks(authorId, first:N)` form accepts a `views` field (the metadata
    # listing never selects it: a read of `views` counts as a view), so views now ride
    # --sync-artworks in a handful of paced calls and land here like liked_count does.
    #
    # FOUR columns, not one, and the reason is the spike rule: a single `views` number
    # can only ever say "how many", never "is this taking off". The previous sweep's
    # reading and BOTH timestamps are what make a rate comparable to the work's own
    # normal rate. See views_spike().
    #
    # THE READ COSTS A VIEW. The same probe measured it: selecting `views` increments
    # the counter for EVERY artwork the query returns (a page of 40 moves all 40 by
    # one; a read that does not select `views` costs nothing). So consecutive sweep
    # readings always carry exactly +1 of our own making, and views_spike() subtracts
    # it. This is also why the sweep is bounded to --sync-artworks and never runs per
    # page-open.
    "views",           # latest swept count, '' = never swept (NOT zero)
    "views_prev",      # the sweep before that -- the spike baseline
    "views_at",        # ISO timestamp of the sweep that wrote `views`
    "views_prev_at",   # ISO timestamp of the sweep that wrote `views_prev`
    # EDIT PRO'S OUTPUT FORMAT (3.22 S5, DESIGN_3.22 5.3): what PixAI made -- the task's own
    # outputs.outputFormat, else the request's chat.modelConfig.outputFormat -- "svg" or "gif"
    # (a png edit sends none and is blank, like every ordinary picture). The source rules read
    # it before the file's extension. A GIF's frame count and frame length come from the
    # request; blank when it sent none (PixAI's own defaults then ran).
    "output_format",
    "frame_count",
    "frame_duration_ms",
]

THUMB_SIZE = (768, 768)
THUMB_QUALITY = 90


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
    is_sensitive    TEXT DEFAULT '',
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
    cloud_deleted_at TEXT DEFAULT '',
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
    batch_size        TEXT DEFAULT '',
    views             TEXT DEFAULT '',
    views_prev        TEXT DEFAULT '',
    views_at          TEXT DEFAULT '',
    views_prev_at     TEXT DEFAULT '',
    output_format     TEXT DEFAULT '',
    frame_count       TEXT DEFAULT '',
    frame_duration_ms TEXT DEFAULT ''
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
    """Create the catalog table if it doesn't exist yet. Schema UPGRADES -- the batch
    column + its index (issue #19 item 1), and every later column/index -- are migrate()'s
    job via _MIGRATIONS; the first catalog() for this path runs it lazily, and every init_db
    caller opens a catalog() (or migrates explicitly) right after, so init_db only creates a
    fresh table here."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.executescript(_CREATE_TABLE)
    con.commit()
    con.close()


# The video engines that publish a numeric version id: moonglade.backup.VIDEO_MODELS' non-empty
# `model_id`s, copied here because this module is the base the backup module imports (it cannot
# import them back at load time). dev/tests/test_video_tsubaki.py fails if the two drift.
# v3.0.1 and v2.7 have no id and are deliberately absent -- their rows keep the name.
_VIDEO_NAME_TO_ID = {
    "v4.0.1": "2003969750675682808",
    "v4.0": "2003968021137101826",
    "tbkv1.0.1": "2054378086834851904",
    "tbkv1.0": "2042030623542642408",
    "v3.2": "1961182207978260675",
    "v3.0.2": "2014412117889628958",
    "v3.0": "1919508300549460046",
}

# VIDEO ROW REPAIR (2026-09-26, PROBE_2026-09-26 V09). Every video collected at create time
# before this date stored the ENGINE NAME in model_id ("tbkv1.0.1", "v4.0.1") -- from the
# submitted block -- where every other road stores the numeric version id, so one model sat in
# the catalog under two ids and --fix-models handed the name to the version lookup. This moves
# the name to video_model and puts the engine's own id in model_id. Idempotent by its WHERE: a
# repaired row's model_id is numeric and never matches again; rows of a name with no id (v3.0.1,
# v2.7) and unknown names are left exactly as they are. model_name is left for --fix-models to
# title (owner ruling 3: video model names are dynamic) -- and CLEARED when it is only what the
# old name-as-id lookup could leave behind: --fix-models --relabel-removed's "Unknown or removed
# model" stamp, or the engine name itself. A stamp would otherwise read as a resolved name to
# _needs_model_fix and block the real title forever (review V-R3). SQLite evaluates every SET
# expression against the row as it was, so model_id is still the engine name inside that CASE.
_VIDEO_ROW_REPAIR_SQL = (
    "UPDATE catalog SET video_model = model_id, "
    "model_name = CASE WHEN model_name IN ('Unknown or removed model', model_id) THEN '' "
    "ELSE model_name END, model_id = CASE model_id "
    + " ".join("WHEN '{}' THEN '{}'".format(n, i) for n, i in _VIDEO_NAME_TO_ID.items())
    + " END WHERE is_video = '1' AND model_id IN ("
    + ", ".join("'{}'".format(n) for n in _VIDEO_NAME_TO_ID) + ")")

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
    # idx_batch moved here from init_db (issue #19 item 1): the `batch` column is both a
    # _CREATE_TABLE column and _MIGRATIONS[0]'s ALTER, so its index belongs on the SAME single
    # migrate() path rather than a duplicate ALTER + index inside init_db. It runs after the
    # batch ALTER above, so the column always exists by the time this CREATE INDEX fires.
    "CREATE INDEX IF NOT EXISTS idx_batch ON catalog(batch)",
    # artwork_id had no index while artwork_media_ids' own docstring called itself an
    # "indexed lookup" -- it was a full table scan, run two or three times per contest
    # overlay open (2026-09-03 ultrareview). Same shape as idx_task_id above, and the
    # column exists from _CREATE_TABLE, so it needs no ALTER ahead of it.
    "CREATE INDEX IF NOT EXISTS idx_artwork_id ON catalog(artwork_id)",
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
    # ARTWORK SENSITIVITY (2026-08-24, issue #20) -- PixAI's own moderation flag from the
    # listArtworks node, distinct from the binary is_nsfw (a work can be sensitive but not
    # nsfw). Already on the wire; the app just never read it. Blank until a --sync-artworks.
    "ALTER TABLE catalog ADD COLUMN is_sensitive TEXT DEFAULT ''",
    # SYNCED VIEWS (2026-09-06) -- see CATALOG_FIELDS for why this is four columns and
    # why the reading is self-inflating. Blank until a --sync-artworks sweeps them.
    "ALTER TABLE catalog ADD COLUMN views TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN views_prev TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN views_at TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN views_prev_at TEXT DEFAULT ''",
    # PER-IMAGE CLOUD DELETION (2026-09-06) -- the deletedAt stamp PixAI puts on this one
    # image's entry in its task's outputs.batch. Per-ROW and permanent, unlike the
    # task-level deleted_remote above, which --reconcile-deleted rewrites on every run.
    "ALTER TABLE catalog ADD COLUMN cloud_deleted_at TEXT DEFAULT ''",
    # EDIT PRO'S OUTPUT FORMAT (3.22 S5) -- see CATALOG_FIELDS. Blank on every existing row
    # (a --backfill-full-meta fills an SVG or GIF edit's), and the source rules fall back to
    # the file's extension, which collect has named .svg / .gif since 3.21.1.
    "ALTER TABLE catalog ADD COLUMN output_format TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN frame_count TEXT DEFAULT ''",
    "ALTER TABLE catalog ADD COLUMN frame_duration_ms TEXT DEFAULT ''",
    # ONE-TIME DATA REPAIRS (2026-09-26). A repair that must run ONCE -- not on every new
    # process, which is how often migrate() replays this list -- records its name here and
    # guards its own statement on that name, so each repair is three idempotent statements:
    # the table, the guarded UPDATE, the marker. The MARKER IS CONDITIONAL on the repair's
    # own postcondition, never written blind: migrate() swallows every OperationalError, so
    # an UPDATE that failed on "database is locked" followed by an unconditional marker would
    # record a repair that never ran, and it would never run again. Conditional, a failed
    # UPDATE leaves no marker and the next process retries it. Not a catalog column: nothing
    # reads it but the guards below, so the CATALOG_FIELDS three-place contract does not apply.
    "CREATE TABLE IF NOT EXISTS catalog_repairs (name TEXT PRIMARY KEY)",
    # LINEAGE FOR CONTEXT IMAGES (SCOPE_2026-09-26 E3). Until this pass source_media_of_task
    # never read parameters.contextImages, so a Tsubaki.3 / Flash picture made from a
    # reference filed as an ORIGINAL -- and --backfill-lineage stamped lineage_checked on it,
    # the "confirmed original" marker that makes every later run skip the task forever.
    # Clear that stamp ONCE on MMDIT26B rows (Tsubaki.3 2024383379556065549, Flash
    # 2050048243034896798) that still have no source, so the next --backfill-lineage re-reads
    # them with the fixed reader. Once, not on every open: a plain Tsubaki.3 txt2img has no
    # source either and is correctly re-stamped by that run; clearing it again on every
    # process start would re-fetch every one of them on every backfill.
    "UPDATE catalog SET lineage_checked = '' "
    "WHERE COALESCE(lineage_checked, '') != '' AND COALESCE(source_media_id, '') = '' "
    "AND model_id IN ('2024383379556065549', '2050048243034896798') "
    "AND NOT EXISTS (SELECT 1 FROM catalog_repairs WHERE name = 'lineage-context-images')",
    # The marker, only once no stamped sourceless MMDIT26B row is left -- i.e. only when the
    # UPDATE above really ran (see ONE-TIME DATA REPAIRS). On a file with no catalog table
    # yet this fails like the UPDATE does, harmlessly: the repair then runs on the first
    # open that has one, where there is nothing stamped for it to clear.
    "INSERT OR IGNORE INTO catalog_repairs (name) SELECT 'lineage-context-images' "
    "WHERE NOT EXISTS (SELECT 1 FROM catalog WHERE COALESCE(lineage_checked, '') != '' "
    "AND COALESCE(source_media_id, '') = '' "
    "AND model_id IN ('2024383379556065549', '2050048243034896798'))",
    # VIDEO ROW REPAIR (2026-09-26) -- a data statement, not DDL; see _VIDEO_ROW_REPAIR_SQL.
    # Last, so every column it reads (is_video, video_model) already exists.
    _VIDEO_ROW_REPAIR_SQL,
    # CURATION (Session N, 2026-09-29) -- two NEW tables, no catalog column and no rewrite of
    # any existing row, so an existing library upgrades in place with everything it holds
    # untouched. They are tables of their own, and not columns on `catalog`, for the same
    # reason `catalog_repairs` is: every re-pull and --update rewrites catalog rows through
    # _UPSERT, and a personal tag or a saved query living on that row would be at the mercy of
    # a writer that does not know it exists. Nothing here is ever sent to PixAI.
    #
    # personal_meta: the owner's own layer over a picture -- tags (comma-joined, lowercase,
    # hyphenated), a keeper|reject mark, a note. Keyed by media_id and NOT a foreign key: a
    # trash purge deletes the catalog row and a restore puts it back, and the layer must be
    # waiting when it does. A row whose three fields are all empty is deleted, never stored.
    "CREATE TABLE IF NOT EXISTS personal_meta ("
    "media_id TEXT PRIMARY KEY, tags TEXT NOT NULL DEFAULT '', "
    "mark TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', "
    "updated_at TEXT NOT NULL DEFAULT '')",
    # smart_collections: a saved SEARCH, never a membership list (N1). The picture set is
    # computed from `query` every time the collection is opened, so a rating, tag or mark
    # moves a picture in or out live and there is nothing here to go stale.
    "CREATE TABLE IF NOT EXISTS smart_collections ("
    "name TEXT PRIMARY KEY, query TEXT NOT NULL DEFAULT '', "
    "created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')",
    # MANUAL ORDER (Session P, P6, 2026-09-29) -- a NEW table, no catalog column and no rewrite
    # of any row, so an existing library gains an empty table and keeps every row byte for
    # byte. Membership stays the comma-joined `collections` label (add_to_collection writes
    # nothing here); `position` lives "on the membership" as one row per (collection,
    # picture). ordered_members() reads it; a row whose picture has left the collection is
    # ignored until the next order write prunes it. Hand-picked collections only: a smart
    # collection's membership is live, so it has no order to keep. Local; never PixAI.
    "CREATE TABLE IF NOT EXISTS collection_order ("
    "name TEXT NOT NULL, media_id TEXT NOT NULL, position INTEGER NOT NULL, "
    "PRIMARY KEY (name, media_id))",
    # MY ART'S 30 DAYS (2026-11-19, owner pick: an All time / 30 days switch). PixAI keeps only a
    # lifetime count, and the catalog only the latest reading (plus the one before it), so a
    # 30-day number needs history the app did not keep. One row per artwork per local day, the
    # day's freshest reading, written after each artwork sweep (record_artwork_snapshots) and
    # pruned past 120 days. `views` is NULL until a views sweep has read it: blank is not zero.
    # Its own table, not catalog columns: every catalog rewrite goes through _UPSERT, which would
    # not know to keep it. Local; never sent anywhere.
    "CREATE TABLE IF NOT EXISTS artwork_snapshots ("
    "artwork_id TEXT NOT NULL, day TEXT NOT NULL, views INTEGER, "
    "likes INTEGER NOT NULL DEFAULT 0, comments INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY (artwork_id, day))",
]

# ---------------------------------------------------------------------------
# THE CATALOG ROAD -- connect and migrate are two things
#
# Opening the catalog and upgrading its schema used to be ONE act: _connect()
# ran all of _MIGRATIONS on every single call, at ~39 call sites, so an ordinary
# read paid 41 ALTER TABLE / CREATE INDEX statements (each raising and swallowing
# an OperationalError once the column exists) before it could run its SELECT.
# They are now two:
#
#   catalog(db_path)  -- a context manager: open, row_factory, close. NO DDL.
#   migrate(db_path)  -- run _MIGRATIONS. Idempotent, and memoized per process
#                        per resolved path, so calling it is free after the first.
#
# LAZY SAFETY IS THE CONTRACT. Every entry point that touches the catalog -- the
# web app, the CLI through _ensure_db, moonglade/mcp_server.py, moonglade/similar.py,
# save_catalog, and any test that calls a helper straight at a fresh tmp db --
# used to be migrated implicitly by _connect, and still is: the FIRST catalog()
# for a given path in this process runs migrate() for it. No entry point has to
# remember to migrate; create_app and _ensure_db call migrate() explicitly only
# to say so out loud, and the memo makes that call cost nothing.
#
# A LOCKED CATALOG BACKS OFF (#58). When another process (a --sync) holds the
# write lock, migrate() gives up after MIGRATE_BUSY_TIMEOUT_S, leaves the path
# un-memoized so a later access finishes the job, and starts a back-off of
# MIGRATE_BUSY_BACKOFF_S: until it runs out, every catalog() skips the migration
# rather than waiting out the timeout again -- and so does every request thread
# that queued behind the locked attempt on _MIGRATE_LOCK, which used to wait its
# own timeout in turn. Kept short on purpose: during the window a table that a
# NEW release adds can still be missing.
# ---------------------------------------------------------------------------

# Resolved catalog paths already migrated in THIS process. Per-process by design:
# a new process re-checks the schema once, which is what makes an install upgraded
# by a new release pick the new columns up on its next run without a migration step.
_MIGRATED = set()
_MIGRATE_LOCK = threading.Lock()
# The back-off after a locked attempt: memo key -> time.monotonic() deadline. An
# entry exists only between a locked attempt and the next successful run.
_MIGRATE_RETRY_AT = {}
MIGRATE_BUSY_BACKOFF_S = 10.0
# How long one attempt waits on another process's lock (sqlite's own default).
# A module constant so a test can shorten it.
MIGRATE_BUSY_TIMEOUT_S = 5.0


def _catalog_key(db_path):
    """The memo key for one catalog file: absolute, symlink-resolved, and
    case-normalized, so `pixai_backup/catalog.db` and `PIXAI_BACKUP\\CATALOG.DB`
    are one entry rather than two on Windows."""
    try:
        resolved = str(Path(db_path).resolve())
    except OSError:                       # a path the OS refuses to resolve
        resolved = str(db_path)
    return os.path.normcase(resolved)


def migrate(db_path, force=False):
    """Bring an existing catalog.db up to the current schema by running
    _MIGRATIONS. Idempotent: almost every statement is an ALTER TABLE ADD COLUMN or a
    CREATE INDEX IF NOT EXISTS, and the OperationalError a re-run raises ("duplicate
    column name") is the success case, not a failure. The rest are the ONE-TIME DATA
    REPAIRS (2026-09-26): an idempotent UPDATE whose own WHERE matches nothing once it has
    run (the video-row repair), or a CREATE TABLE IF NOT EXISTS catalog_repairs, then per
    repair an UPDATE guarded on its name there and a marker INSERT guarded on the repair's
    own postcondition -- so an OperationalError swallowed here (a locked file, say) leaves
    the repair unmarked for the next process to run, rather than marked and never run.

    Memoized per process per resolved path -- the second and every later call for
    the same catalog returns without opening anything. That is what lets create_app
    and _ensure_db call it explicitly AND lets catalog() call it lazily without the
    two ever colliding into real work twice.

    A LOCKED catalog (another process holding the write lock past
    MIGRATE_BUSY_TIMEOUT_S) is left un-memoized and starts a back-off: for
    MIGRATE_BUSY_BACKOFF_S every call returns at once without opening anything,
    including the threads that were already queued on the lock behind the locked
    attempt. The first call after the window tries again; a run that completes
    clears the window and memoizes (#58).

    `force=True` runs the statements again anyway, ignoring the memo and the
    back-off. Nothing in the app needs it (a new process starts with an empty memo,
    which is exactly the upgrade path a new release takes); it exists so a test can
    prove the DDL really is re-runnable rather than proving only that the memo
    skipped it."""
    key = _catalog_key(db_path)
    if key in _MIGRATED and not force:
        return
    if not force and time.monotonic() < _MIGRATE_RETRY_AT.get(key, 0.0):
        return                               # locked a moment ago: don't wait on it again
    with _MIGRATE_LOCK:
        if key in _MIGRATED and not force:   # another thread got here first
            return
        if not force and time.monotonic() < _MIGRATE_RETRY_AT.get(key, 0.0):
            return                           # queued behind the attempt that found it locked
        con = sqlite3.connect(str(db_path), timeout=MIGRATE_BUSY_TIMEOUT_S)
        busy = False
        try:
            for sql in _MIGRATIONS:
                try:
                    con.execute(sql)
                    con.commit()
                except sqlite3.OperationalError as e:
                    # "duplicate column" / "already exists" is the re-run's success case. A
                    # LOCKED or BUSY catalog (a --sync holding its write lock past the busy
                    # timeout) is not: stop at once -- every later statement would wait out the
                    # same timeout -- and leave the catalog UN-memoized, so the next access
                    # runs the migration again instead of the new tables staying missing for
                    # the life of the process (red team 2026-10-01).
                    msg = str(e).lower()
                    if "locked" in msg or "busy" in msg:
                        busy = True
                        break
        finally:
            con.close()
        if busy:
            # One warning per window: the back-off is what keeps this from repeating
            # on every access.
            _MIGRATE_RETRY_AT[key] = time.monotonic() + MIGRATE_BUSY_BACKOFF_S
            import logging
            logging.getLogger(__name__).warning(
                "catalog migration deferred: %s is locked; it will run again on a "
                "catalog access after %ss", db_path, MIGRATE_BUSY_BACKOFF_S)
            return
        _MIGRATE_RETRY_AT.pop(key, None)
        _MIGRATED.add(key)


@contextmanager
def catalog(db_path):
    """The one way to open catalog.db: a migrated, sqlite3.Row-factory connection,
    closed when the block ends. Runs NO DDL of its own -- the lazy migrate above
    fires once per path per process and then never again.

        with catalog(db_path) as con:
            rows = con.execute("SELECT ...").fetchall()

    Writers commit inside the block; this closes the connection, it does not
    commit for you (an uncommitted write is rolled back on close, exactly as it
    was under _connect)."""
    migrate(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    # mg_loom_render(media_id) -> 1|0: is this picture a render the Loom made? Only the
    # `type:loom` search operator (and its Storage-bar segment) calls it; nothing runs it
    # unless asked, and it reads the Loom's boards from disk, never the network.
    # The set is read ONCE per connection, on the first row that asks: a search calls this for
    # every row it looks at, and a directory listing per row would cost more than the search.
    _loom_root = Path(db_path).parent
    _loom_seen = {}

    def _is_loom_render(mid):
        ids = _loom_seen.get("ids")
        if ids is None:
            ids = _loom_seen["ids"] = loom_render_ids(_loom_root)
        return 1 if str(mid or "") in ids else 0
    con.create_function("mg_loom_render", 1, _is_loom_render)
    con.create_function("mg_lora_weight", 4, _lora_weight_match, deterministic=True)
    try:
        yield con
    finally:
        con.close()


def catalog_csv_text(rows):
    """The catalog CSV text for `rows` (every CATALOG_FIELDS column, header first). The ONE
    writer behind the gallery's Export view and the command line's --export-csv, so the two
    files can never disagree about their columns."""
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CATALOG_FIELDS)
    writer.writeheader()
    for r in rows:
        writer.writerow({f: r.get(f, "") for f in CATALOG_FIELDS})
    return buf.getvalue()


def load_catalog(db_path):
    """Return all rows as a list of plain dicts, oldest-first."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with catalog(db_path) as con:
        rows = con.execute("SELECT * FROM catalog").fetchall()
        return [dict(r) for r in rows]


def save_catalog(db_path, rows):
    """Upsert a list of dicts into the catalog (replaces the old full-rewrite)."""
    db_path = Path(db_path)
    init_db(db_path)
    with catalog(db_path) as con:
        con.executemany(
            _UPSERT,
            [tuple(r.get(f, "") or "" for f in CATALOG_FIELDS) for r in rows],
        )
        con.commit()


def merge_over_current(row, snapshot_row, current_row, blank_keeps=True):
    """One row a long-running writer built, merged over the row the catalog holds NOW.

    `snapshot_row` is what the writer read when it started (None when the media_id was not
    cataloged then); `current_row` is what the catalog holds at write time (None when it has
    no row). A value in `row` equal to the snapshot's is only the snapshot echoed back, so
    whatever the catalog holds now wins -- that is how a rating, a collection, a prompt
    correction or a `cloud_deleted_at` set while a Sync ran survives the Sync's save. A
    value that differs from the snapshot is the writer's own news and wins.

    `blank_keeps`: a download row's blank means "not known here" and never clobbers (the
    `carry_local_fields` rule). A writer that loaded whole rows and edited them passes False,
    so a value it cleared on purpose is written as cleared."""
    snap = snapshot_row or {}
    base = dict(current_row or {})
    for k, v in row.items():
        if current_row is not None and k in snap and str(snap.get(k) or "") == str(v or ""):
            base.setdefault(k, v)            # an echo of the snapshot: the catalog's value wins
        elif v in ("", None) and blank_keeps:
            base.setdefault(k, "")
        else:
            base[k] = v
    return base


def save_catalog_over_snapshot(db_path, rows, snapshot, blank_keeps=True):
    """Upsert rows a writer built from an earlier read of the catalog (`snapshot`:
    media_id -> the row as it read it, the map `carry_local_fields` takes), without undoing
    anything another writer did in between.

    The current rows are re-read inside the same write transaction as the upsert, so no
    edit can land between the read and the write. Each row is merged with
    `merge_over_current`. A media_id the snapshot held that the catalog no longer holds was
    deleted while the writer worked, and is NOT written back. Returns the rows written.

    Before 2026-11-19 `run_download` merged its page rows over a snapshot taken when the
    Sync started and `_UPSERT` overwrote every column, so a rating, a collection or a delete
    made in the gallery during a Sync was undone by the next page save."""
    db_path = Path(db_path)
    init_db(db_path)
    snapshot = snapshot or {}
    ids = [str(r.get("media_id")) for r in rows if r.get("media_id")]
    written = []
    with catalog(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        current = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                    "SELECT * FROM catalog WHERE media_id IN ({})".format(ph), chunk):
                current[str(r["media_id"])] = dict(r)
        for r in rows:
            mid = str(r.get("media_id") or "")
            if mid in snapshot and mid not in current:
                continue   # deleted while the writer worked: never resurrect it
            written.append(merge_over_current(r, snapshot.get(mid), current.get(mid),
                                              blank_keeps=blank_keeps))
        con.executemany(
            _UPSERT,
            [tuple(r.get(f, "") or "" for f in CATALOG_FIELDS) for r in written],
        )
        con.commit()
    return written


def update_rating(db_path, media_id, value):
    """Update a single row's rating without touching the rest of the catalog."""
    with catalog(db_path) as con:
        con.execute(
            "UPDATE catalog SET rating=? WHERE media_id=?",
            (str(value) if value else "", media_id),
        )
        con.commit()


def delete_from_catalog(db_path, media_id):
    """Remove a single row by media_id."""
    with catalog(db_path) as con:
        con.execute("DELETE FROM catalog WHERE media_id=?", (media_id,))
        con.commit()


def update_prompt_full(db_path, media_id, text):
    """Overwrite a single row's prompt_full (manual annotation/correction)."""
    with catalog(db_path) as con:
        con.execute("UPDATE catalog SET prompt_full=? WHERE media_id=?",
                    (text or "", media_id))
        con.commit()


def bulk_replace_prompt(db_path, media_ids, find, replace):
    """Find/replace a substring in prompt_full across the given media_ids.
    Returns the number of rows actually changed."""
    if not find:
        return 0
    changed = 0
    with catalog(db_path) as con:
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


# The legacy catalog.csv migrate/export helpers were retired 2026-08-24 (#19): the silent
# auto-seed was a footgun and the on-disk dump was unused (catalog.db is the source of
# truth). The web CSV *download* (/export-csv) is a separate, live feature and is unchanged.

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

# "manual" (Session P, P6): a hand-picked collection's own order -- its saved positions, then
# the pictures added since, OLDEST first (ruling 9), the same order ordered_members() gives.
# Offered only on a hand-picked collection's view; anywhere else (no collection, or a smart one,
# which _expand_smart has already turned into a search) it falls back to the default sort.
_MANUAL_SORT_SQL = ("(SELECT o.position FROM collection_order o WHERE o.name = ? AND o.media_id = catalog.media_id) IS NULL, "
                    "(SELECT o.position FROM collection_order o WHERE o.name = ? AND o.media_id = catalog.media_id), "
                    "created_at ASC, media_id ASC")


def _order_sql(sort, collection=""):
    """(ORDER BY text, its parameters) for a sort key. Only "manual" takes parameters."""
    if sort == "manual":
        if collection:
            return _MANUAL_SORT_SQL, [collection, collection]
        return _DEFAULT_SORT_SQL, []
    return _SORT_SQL.get(sort, _DEFAULT_SORT_SQL), []


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
#   tag        the art_tags substring OR a whole personal tag (Session N3)
#   note       substring of the personal note (Session N3)
#   source     the dropdown's semantics (online = blank-or-online, deleted =
#              deleted_remote flag), else substring on the source column
#   aspect     width/height: W:H (within 3 percent), square, portrait, landscape, tall,
#              wide, >N, <N (Session N7)
#   type       image | video | loom, a partition of the library (Session N6)
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
# dev/tests/test_search_operators.py's hostile-value test.
_SEARCH_OPS = {
    "prompt":   ("prompt", None),
    "negative": ("text", "negative_prompt"), "negative_prompt": ("text", "negative_prompt"),
    "model":    ("text", "model_name"),      "model_name": ("text", "model_name"),
    "lora":     ("text", "loras"),           "loras": ("text", "loras"),
    # tag: reads BOTH tag stores (Session N3): PixAI's published art tags, substring as it
    # always did, and the owner's own personal tags, whole-tag. `art_tags:` keeps the
    # PixAI-only reading for anyone who needs it. See _operator_clause's "tag" kind.
    "tag":      ("tag", "art_tags"),         "tags": ("tag", "art_tags"),
    "art_tags": ("text", "art_tags"),
    # note: reads the owner's personal note (Session N3), substring, case-insensitive.
    "note":     ("note", None),              "notes": ("note", None),
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
    # ar: the picture's shape, read from the width and height already on every row (Session
    # N7). Evaluated HERE, in SQL, because the grid is paginated: a client-side filter would
    # only ever see the page it holds. See _aspect_clause for the accepted values.
    "ar":       ("aspect", None),            "aspect": ("aspect", None),
    # type: which kind of picture -- image, video or loom (Session N6). The three PARTITION the
    # library (a Loom render is a loom, whether it is a clip or a still), which is what lets
    # the Storage bars' segments add up to the total and each segment's click land on exactly it.
    "type":     ("type", None),
}

# Tokens: quoted runs group (model:"Ether Real" / "night elf" are ONE token each);
# everything else splits on whitespace exactly like q.split() always did.
_SEARCH_TOKEN_RE = re.compile(r'[^\s"]*"[^"]*"[^\s"]*|\S+')
_SEARCH_KEY_RE   = re.compile(r"[A-Za-z_]+")
_SEARCH_NUM_RE   = re.compile(r"^(>=|<=|>|<)?(-?\d+(?:\.\d+)?)$")
_SEARCH_DATE_RE  = re.compile(r"^(>=|<=|>|<)?(\d{4}(?:-\d{2}(?:-\d{2})?)?)$")
# Dates beyond a single prefix: a quarter (2026Q3) and an inclusive range (A..B, either end
# open), each end a year / month / day / quarter.
_SEARCH_DATE_PART_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?|[Qq]([1-4]))?$")
# lora:Name>0.7 -- a LoRA name (blank or * = any LoRA) then a weight comparison.
_SEARCH_LORA_WEIGHT_RE = re.compile(r"^(.*?)(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)$")
_LORA_ENTRY_RE = re.compile(r"\s*(.*?):(-?\d+(?:\.\d+)?)(?=,\s|$)")
_SEARCH_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SEARCH_FALSY  = frozenset({"0", "false", "no", "off"})


def _unquote(s):
    """Strip one pair of surrounding double quotes, if present."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _personal_tag_pattern(value):
    r"""LIKE pattern matching ONE whole personal tag inside personal_meta's `,a,b,` list.
    The value is folded the way tags are stored (lowercase, whitespace and underscores to
    hyphens) so `tag:"Pose Study"` finds pose-study; `*` and `?` keep their wildcard meaning."""
    t = re.sub(r"[\s_]+", "-", str(value).strip().lower())
    t = t.replace("\\", "\\\\").replace("%", "\\%")
    return "%," + t.replace("*", "%").replace("?", "_") + ",%"


# A leading `-` negates a search token (Session N3: `-reject`, `-tag:x`, `-blurry`). A `-` in
# front of a bare number stays what it always was, literal text -- "-5" is a prompt fragment.
_SEARCH_NEG_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_SEARCH_STAR_RE = re.compile("^★([0-5])\\+?$")


def _personal_mark_clause(mark):
    return ("EXISTS (SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
            "AND pm.mark = ?)", [mark])


def _search_token_clause(tok):
    """One whitespace-delimited search token -> (sql, params). The token is already stripped
    of any leading `-` negation by the caller."""
    # the bare marks are operators on their own (an UNQUOTED word: "reject" in quotes is a
    # phrase and stays a prompt search)
    if tok.lower() in ("keeper", "reject"):
        return _personal_mark_clause(tok.lower())
    m = _SEARCH_STAR_RE.match(tok)
    if m:
        # star-N-plus (and star-N): that many stars or more, unrated counting as 0 -- the
        # Min-rating dropdown's own semantics
        return ("CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) >= ?", [int(m.group(1))])
    if ":" in tok and not tok.startswith(":"):
        key, _, raw = tok.partition(":")
        if _SEARCH_KEY_RE.fullmatch(key):
            hit = _operator_clause(key, _unquote(raw))
            if hit:
                return hit
    term = _unquote(tok)
    if term.isdigit() and len(term) >= 8:
        return ("(task_id = ? OR media_id = ?)", [term, term])
    like = _like_pattern(term)
    return ("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')", [like, like])


# ---- ar: the aspect operator (Session N7) -------------------------------------------------
# The picture's shape as width / height. The width and height columns are TEXT and blank on
# old imports, so the ratio is NULL for those rows; every comparison below is wrapped in
# COALESCE(.., 0) so an unmeasured picture matches no ar: filter and, because NOT of a false
# is true, still shows up under `-ar:tall` (the unknown is not "tall").
#
#   ar:W:H        within 3 percent of W/H       ar:3:2  ar:9:16  ar:1.91:1
#   ar:square     0.97 to 1.03
#   ar:portrait   below 1                        ar:landscape   above 1
#   ar:tall       9:16 or taller                 ar:wide        16:9 or wider
#   ar:>N ar:<N   the ratio itself               ar:>2  ar:<0.5
#
# The bounds are the design page's own (Curation Handoff, N7): "tall" is 9/16 with 0.005 to
# spare and "wide" 16/9 with 0.01 to spare, so an exact 576x1024 and an exact 1920x1080
# count without a rounding argument. Values are bound parameters; only the fixed expression is interpolated.
_AR_EXPR = ("(CAST(COALESCE(NULLIF(width,''),'0') AS REAL) / "
            "NULLIF(CAST(COALESCE(NULLIF(height,''),'0') AS REAL), 0))")
AR_SQUARE = (0.97, 1.03)
AR_TALL_MAX = 9 / 16 + 0.005
AR_WIDE_MIN = 16 / 9 - 0.01
AR_TOLERANCE = 0.03
_AR_WH_RE = re.compile(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$")
_AR_CMP_RE = re.compile(r"^([<>])(\d*\.?\d+)$")


def _aspect_clause(value):
    """`ar:` value -> (sql, params), or None when the value is not one of the accepted forms
    (the token then degrades to a plain prompt search, like any malformed operator)."""
    v = str(value).strip().lower()
    e = _AR_EXPR
    if v == "square":
        return ("COALESCE({0} >= ? AND {0} <= ?, 0)".format(e), [AR_SQUARE[0], AR_SQUARE[1]])
    if v == "portrait":
        return ("COALESCE({} < 1, 0)".format(e), [])
    if v == "landscape":
        return ("COALESCE({} > 1, 0)".format(e), [])
    if v == "tall":
        return ("COALESCE({} <= ?, 0)".format(e), [AR_TALL_MAX])
    if v == "wide":
        return ("COALESCE({} >= ?, 0)".format(e), [AR_WIDE_MIN])
    m = _AR_CMP_RE.match(v)
    if m:
        return ("COALESCE({} {} ?, 0)".format(e, m.group(1)), [float(m.group(2))])
    m = _AR_WH_RE.match(v)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w <= 0 or h <= 0:
            return None
        n = w / h
        # within 3 percent of n, either side; the epsilon keeps an exact 3 percent in
        return ("COALESCE(ABS({} - ?) <= ?, 0)".format(e), [n, n * AR_TOLERANCE + 1e-9])
    return None


# ---- type: image | video | loom (Session N6) -----------------------------------------------
def _type_clause(value):
    v = str(value).strip().lower()
    if v == "loom":
        return ("mg_loom_render(media_id) = 1", [])
    if v == "video":
        return ("(is_video = '1' AND mg_loom_render(media_id) = 0)", [])
    if v == "image":
        return ("(COALESCE(is_video,'') != '1' AND mg_loom_render(media_id) = 0)", [])
    return None


_LOOM_IDS_CACHE = {}          # str(out_dir) -> (signature, frozenset of media ids)


def _loom_board_files(out_dir):
    """Every saved Loom board on disk: this install's per-account folders and the legacy shared
    layer, both under the Loom's kv/ (moonglade.paths.loom_root), keyed `storyboard:v2:proj:<id>` (the Loom's own PPRE) or the
    legacy single-project key. Read-only; a missing folder is simply no boards."""
    from urllib.parse import unquote
    kv = _paths.loom_root(out_dir) / "kv"
    out = []
    try:
        entries = list(kv.iterdir())
    except OSError:
        return out
    for p in entries:
        try:
            files = list(p.iterdir()) if p.is_dir() else [p]
        except OSError:
            continue
        for f in files:
            if f.suffix != ".json":
                continue
            key = unquote(f.stem)
            if key.startswith("storyboard:v2:proj:") or key == "storyboard:v2:project":
                out.append(f)
    return out


def loom_render_ids(out_dir):
    """The media ids the Loom rendered: every board's shot result and every re-roll attempt it
    kept, minus footage the owner imported into a shot (that is theirs, not a render). This is
    what "Loom renders" means in the Storage bars and `type:loom`.

    It reads the boards straight off disk -- nothing is written and no network is touched -- and
    remembers the answer until a board's file moves (path, mtime and size are the key), so a
    search that runs it per row costs one directory listing, not a re-parse."""
    files = _loom_board_files(out_dir)
    sig = []
    for f in files:
        try:
            st = f.stat()
            sig.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    sig = tuple(sorted(sig))
    hit = _LOOM_IDS_CACHE.get(str(out_dir))
    if hit and hit[0] == sig:
        return hit[1]
    ids = set()
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, str):            # the Loom stores a project as a JSON string
                data = json.loads(data)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for act in data.get("acts") or []:
            for card in (act or {}).get("cards") or []:
                if not isinstance(card, dict) or card.get("imported"):
                    continue
                if card.get("resultMid"):
                    ids.add(str(card["resultMid"]))
                for a in card.get("attempts") or []:
                    if isinstance(a, dict) and a.get("media_id"):
                        ids.add(str(a["media_id"]))
    frozen = frozenset(ids)
    _LOOM_IDS_CACHE[str(out_dir)] = (sig, frozen)
    return frozen


# ---------------------------------------------------------------------------
# THE LOOM'S MUSIC BED AND EDL EXPORT (Session P, Stage B1: NOTES P3/P4; BUILD-w5-p §5.1/§5.5;
# rulings 6-8 and 15; review F18/F19/N2). Pure helpers here; the routes are in create_app.
#
# A bed is one local audio file per storyboard, stored content-addressed at
# out_dir/_moonglade/loom/_beds/<account key>/<sha1>.<ext> -- never uploaded, never sent to PixAI, and
# never deleted automatically (an explicit, confirmed sweep of beds no board of the account
# references is offered instead). Its name is the sha1 of its bytes, so a duplicated board
# shares it and an imported bundle's bed is RE-HASHED on arrival, never trusted by name.
# ---------------------------------------------------------------------------

LOOM_BED_MAX_BYTES = 50 * 1024 * 1024
# The multipart envelope around the file (boundaries, headers, the csrf and board fields). A
# request whose declared length is over the cap plus this is refused before a byte is read.
LOOM_BED_FORM_SLACK = 64 * 1024
LOOM_BED_FILE_RE = re.compile(r"^[0-9a-f]{40}\.(mp3|wav|m4a|aac|ogg|flac)$")
# A bundle import stores at most this many beds (the one its board names), each under the cap
# above -- so one import writes at most LOOM_BED_MAX_BYTES of beds (spend review S5).
LOOM_BUNDLE_MAX_BEDS = 1
LOOM_BED_MIMES = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac",
                  "ogg": "audio/ogg", "flac": "audio/flac"}


# ---------------------------------------------------------------------------
# SIZE CAPS (app security review 2026-11-19, finding 9)
# ---------------------------------------------------------------------------
# Every request body has a ceiling, and every zip the app opens has one on what it unpacks.
# REQUEST_MAX_BYTES is the app-wide default (Flask's MAX_CONTENT_LENGTH): JSON bodies, the
# branding uploads, everything that names no larger cap. The few routes that take big files
# raise it for themselves before their form is read. A refusal is a 413 with a plain sentence.
# The import limits are sized for a whole library (a zip of years of pictures, a long video):
# they stop a runaway or hostile upload from filling the drive, not a real library. Past them,
# the command-line import (IMPORT_CLI_HINT) reads a folder in place with no upload at all.
_GB = 1024 ** 3
REQUEST_MAX_BYTES = 64 * 1024 * 1024
UPLOAD_MAX_BYTES = 8 * _GB                      # /api/upload: one file handed to PixAI
IMPORT_REQUEST_MAX_BYTES = 50 * _GB             # /api/import-local: one request (the page sends
                                                # batches of at most 256 MB; a lone bigger
                                                # file -- a library zip, a long video -- alone)
LOOM_BUNDLE_REQUEST_MAX_BYTES = 50 * _GB        # /api/loom/import-bundle
# What a zip may unpack to (Import's zips and Loom bundles): its member count, any one member,
# and the bytes of the whole -- all counted as they are written, never taken from the zip's own
# headers, which a zip bomb lies in.
ZIP_MAX_MEMBERS = 200000
ZIP_MAX_MEMBER_BYTES = 8 * _GB
ZIP_MAX_TOTAL_BYTES = 50 * _GB
IMPORT_CLI_HINT = ("For something this big, import it from the command line on this PC instead: "
                   "python -m moonglade --import-local \"<folder>\" (unzip it first).")
ZIP_TOO_MANY_MEMBERS = ("That zip holds more than {:,} files, so nothing in it was imported. "
                        .format(ZIP_MAX_MEMBERS) + IMPORT_CLI_HINT)
ZIP_MEMBER_TOO_BIG = ("A file in that zip unpacks to more than {} GB, so nothing in it was "
                      "imported. ".format(ZIP_MAX_MEMBER_BYTES // _GB) + IMPORT_CLI_HINT)
ZIP_TOO_BIG = ("That zip unpacks to more than {} GB, so nothing in it was imported. "
               .format(ZIP_MAX_TOTAL_BYTES // _GB) + IMPORT_CLI_HINT)


class ZipTooBig(ValueError):
    """A zip over ZIP_MAX_MEMBERS, ZIP_MAX_MEMBER_BYTES or ZIP_MAX_TOTAL_BYTES; str() is the
    plain sentence."""


def _too_large_sentence(limit):
    """The 413's words for a body over `limit` bytes."""
    if limit and limit >= 1024 ** 3:
        size = "{:g} GB".format(round(limit / 1024 ** 3, 1))
    elif limit:
        size = "{:g} MB".format(round(limit / 1024 ** 2, 1))
    else:
        size = "the limit"
    return ("That is more than Moonglade takes in one go ({}), so nothing was sent. Send "
            "fewer or smaller files at a time. ".format(size) + IMPORT_CLI_HINT)


# ---------------------------------------------------------------------------
# SESSIONS (app security review 2026-11-19, finding 6)
# ---------------------------------------------------------------------------
# A sign-in lasts at most SESSION_ABSOLUTE_LIFETIME_S from the moment it was made, however
# often it is used (the cookie itself still renews on use, Flask's permanent session, so an
# idle one also ends after SESSION_IDLE_LIFETIME_DAYS). Every session carries its own id, and
# Log Out records that id as signed out (moonglade.web_sessions), so a copy of the cookie stops
# working the moment the device that made it signs out.
SESSION_ABSOLUTE_LIFETIME_S = 30 * 86400
SESSION_IDLE_LIFETIME_DAYS = 30


# ---------------------------------------------------------------------------
# FILES FROM THE LIBRARY NEVER RUN AS A PAGE (red team, 2026-11-18)
# ---------------------------------------------------------------------------
# Every route that hands back a file someone else made -- a library picture or clip, a
# thumb, a music bed, a PixAI CDN cover, an export -- goes out through
# harden_file_response. A browser shown only a raster picture, a video or a sound has
# nothing to run; anything else (an SVG above all: Edit Pro makes them, the library
# catalogs them, and an SVG may carry <script>) opened at its own URL would run AS
# Moonglade, with the signed-in session. So: every such response says nosniff (the
# browser keeps to the stated type) and a CSP sandbox (no script, no same-origin even if
# it did render), and a type outside the list below is sent as a download. An <img>,
# <video> or <audio> ignores Content-Disposition, so in-page display is unchanged.
_INLINE_FILE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/pjpeg", "image/webp", "image/gif", "image/avif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
    "video/mp4", "video/webm", "video/quicktime", "video/x-m4v",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave", "audio/mp4",
    "audio/aac", "audio/ogg", "audio/flac", "audio/x-flac",
})
FILE_RESPONSE_CSP = "sandbox"
# An SVG (3.22 S5, DESIGN_3.22 5.4) goes out under its real type, image/svg+xml, so an <img src>
# (or a CSS background-image) can draw it -- an image context never runs SVG script. It is still
# always a download (an SVG is not on _INLINE_FILE_TYPES), so a direct visit never becomes a
# page on Moonglade's origin, and this policy is the belt if a browser ignores the disposition:
# sandboxed, nothing fetched, only its own inline styles. Never shown any other way: no
# <object>, <embed>, <iframe>, innerHTML, data URL from its text or fetch-then-inject.
SVG_FILE_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
# The library's own picture and clip types, named here rather than asked of the system's
# type table (on Windows that reads the registry, which can say anything).
_MEDIA_TYPE_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".avif": "image/avif", ".mp4": "video/mp4", ".webm": "video/webm",
    ".mov": "video/quicktime", ".m4v": "video/x-m4v",
    ".svg": "image/svg+xml",           # a download with SVG_FILE_CSP (harden_file_response)
}


def media_type_for(name):
    """The fixed type for a library picture or clip by its extension; None for anything
    else (the caller's guess then stands, and harden_file_response makes it a download)."""
    return _MEDIA_TYPE_BY_EXT.get(os.path.splitext(str(name or ""))[1].lower())


def _attachment_disposition(name):
    """`attachment; filename=...` for any name: an ASCII fallback plus the RFC 5987 form."""
    from urllib.parse import quote
    name = os.path.basename(str(name or "")) or "download"
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
    return "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(plain, quote(name, safe=""))


def harden_file_response(resp, filename=None):
    """Stamp a served file's response so it can never run as a page on this origin.

    Always: X-Content-Type-Options: nosniff and Content-Security-Policy: sandbox (an SVG,
    by its type or its name: the stricter SVG_FILE_CSP). And a type that is not a raster
    picture, a video or a sound goes out as a download (Content-Disposition: attachment),
    whatever the route asked for. Returns resp."""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    mime = (resp.mimetype or "").lower()
    svg = mime == "image/svg+xml" or str(filename or "").lower().endswith(".svg")
    resp.headers["Content-Security-Policy"] = SVG_FILE_CSP if svg else FILE_RESPONSE_CSP
    if mime not in _INLINE_FILE_TYPES:
        if not (resp.headers.get("Content-Disposition") or "").lower().startswith("attachment"):
            resp.headers["Content-Disposition"] = _attachment_disposition(filename)
    return resp


# ---------------------------------------------------------------------------
# THE APP'S OWN PAGES, AND WHERE A WRITE MAY COME FROM (app security review 2026-11-19)
# ---------------------------------------------------------------------------
# The policy every HTML page goes out with (create_app's _protective_headers). Scripts: this
# origin's files, plus the inline ones the page templates mark with CSP_NONCE_MARK, which the
# serving route replaces with a fresh nonce per request (_noncify) -- no 'unsafe-inline', no
# 'unsafe-eval' (neither bundle evaluates strings; the Loom has shipped pre-built since the
# Babel-standalone retirement). Styles may be inline: React writes style attributes and the
# pages carry their design tokens in a <style>, and a style cannot run anything. Pictures and
# video may come from https: (PixAI's own covers), data: and blob: (QR codes, import previews).
# Only Moonglade's own pages may frame one (the same-origin phone-layout check frames the app),
# and no page may submit a form or open a plugin elsewhere.
CSP_NONCE_MARK = "__CSP_NONCE__"
CSP_PAGE_POLICY = ("default-src 'self'; script-src 'self'{nonce}; "
                   "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
                   "media-src 'self' data: blob: https:; font-src 'self' data:; "
                   "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
                   "object-src 'none'; base-uri 'none'; form-action 'self'; "
                   "frame-ancestors 'self'")


def page_csp(nonce=None):
    """CSP_PAGE_POLICY for one response: with its nonce when the page used one."""
    return CSP_PAGE_POLICY.format(nonce=(" 'nonce-%s'" % nonce) if nonce else "")


CROSS_ORIGIN_REFUSED = ("That request came from a page that isn't one of this Moonglade's own, "
                        "so nothing was done. Open Moonglade itself and try again there.")
PLAIN_HTTP_REFUSED = ("Moonglade only takes this over an encrypted connection from another "
                      "device. Open Moonglade at {url} and try again there.")
CONNECT_TOKEN_NEEDS_HTTPS = ("Connect from PixAI from another device only works over an "
                             "encrypted connection, so nothing was saved. Open Moonglade at its "
                             "https:// address (the Control Panel's LAN card shows it), make the "
                             "Connect from PixAI bookmark again there, and click it on a "
                             "pixai.art tab.")


def _origin_tuple(url):
    """(scheme, host, port) of an http(s) URL or origin, the default port filled in; None for
    anything else ("null", an empty value, another scheme, a malformed port)."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(url or "").strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    return scheme, host, port or (443 if scheme == "https" else 80)


def same_origin_write(origin, referer, fetch_site, scheme, host):
    """Does a state-changing request come from this server's own origin? Pure.

    `origin`, `referer` and `fetch_site` are the request's Origin, Referer and Sec-Fetch-Site
    headers (None when absent); `scheme` and `host` are the request's own (request.scheme,
    request.host -- what the browser addressed). The rule, in order:
      * a Sec-Fetch-Site other than "same-origin" refuses (same-site is NOT enough: another
        port on this PC is same-site);
      * an Origin header decides alone, and "null" or anything unparseable refuses;
      * with no Origin, a Referer decides the same way;
      * with none of the three, the caller is not a browser and passes (it has no ambient
        cookie for another page to ride)."""
    own = _origin_tuple("{}://{}".format(scheme or "", host or ""))
    if own is None:
        return False
    if fetch_site is not None and fetch_site.strip().lower() != "same-origin":
        return False
    if origin is not None:
        return _origin_tuple(origin) == own
    if referer:
        return _origin_tuple(referer) == own
    return True
# A bed added in the last few minutes may belong to a board whose save has not landed yet, so
# the unused list never offers it (the sweep re-checks the same rule).
LOOM_BED_UNUSED_GRACE_S = 10 * 60
# A bed upload's or a bundle import's temp file (.upload-*.part / .import-*.part) that a crash
# left in _beds/<account>/ is swept at the next start once it is this old (spend review N5):
# the unused-bed list and its sweep only ever see finished, content-hashed names.
LOOM_BED_TEMP_SWEEP_AGE_S = 3600
# THE EDL ZIP'S NAMES -- the same patterns as loom/src/loom-edl-core.js's EDL_CLIP_FILE_RE and
# EDL_BED_NAME_RE (dev/tests/test_loom_p_routes.py compares the two sources).
LOOM_EDL_CLIP_RE = re.compile(r"^[A-Za-z0-9]{1,8}_t\d{1,4}\.mp4$")
LOOM_EDL_BED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(mp3|wav|m4a|aac|ogg|flac)$")
LOOM_MEDIA_ID_RE = re.compile(r"^(\d+|local_[0-9a-f]{12})$")
# A bundle's media entry: exactly media/<id><picture or video extension>, nothing else; the id
# is letters, digits, '_' and '-' only (no separator, drive letter, colon or dot).
# The name inside a zip is the sender's to choose, so it is never trusted as a path: anything
# else (another extension such as .html/.svg, a separator, a drive letter, "..") is skipped
# unread (red team 2026-10-01). Each entry is copied under this cap.
LOOM_BUNDLE_MEDIA_RE = re.compile(
    r"^media/([A-Za-z0-9][A-Za-z0-9_-]{0,63})\.(png|jpg|jpeg|webp|gif|avif|mp4|webm|mov|mkv|m4v)$")
LOOM_BUNDLE_MEDIA_MAX_BYTES = 1024 * 1024 * 1024
LOOM_EDL_MAX_EDL_CHARS = 1024 * 1024
LOOM_EDL_MAX_CSV_CHARS = 4 * 1024 * 1024
LOOM_EDL_MAX_CLIPS = 2000
LOOM_EXPORT_SWEEP_AGE_S = 3600

# THE CONTINUITY RIBBON'S FRAMES (Session P, P9; review F18). GET /api/loom/frame extracts ONE
# small still from a local clip -- ffmpeg on this machine, never an upload, never PixAI -- and
# keeps it in out_dir/_moonglade/loom/_frames/ as <mid>_<frame>.png, the time quantised to a 24 fps frame
# so a trim dragged across a second makes at most 24 files, not one per float. The cache is
# capped by count and by bytes, least-recently-used first, swept on every write; only files of
# exactly this name shape are ever swept (the ✂ splice's own <mid>_last.png is not).
LOOM_FRAME_FPS = 24
LOOM_FRAME_WIDTH = 160
LOOM_FRAME_MAX_SECONDS = 6 * 3600
LOOM_FRAME_CACHE_MAX_FILES = 600
LOOM_FRAME_CACHE_MAX_BYTES = 64 * 1024 * 1024
# GitHub #62: a frame spliced before 3.15.0 has no thumbs/<id>.jpg. /api/loom/frame-thumbs fills
# one from PixAI once (a media read, then the picture from the image CDN), at most this many ids
# a request, one at a time with this pause between PixAI calls.
LOOM_FRAME_THUMBS_MAX = 60
LOOM_FRAME_THUMBS_PAUSE_S = 0.3
LOOM_FRAME_THUMB_ID_RE = re.compile(r"^\d{1,32}$")
# <mid>_<frame>.png, or <mid>_end.png: the clip's true last frame, asked for when a take's
# length was never recorded (GitHub #63). The splice's <mid>_last.png is NOT this shape.
LOOM_FRAME_FILE_RE = re.compile(r"^(\d+|local_[0-9a-f]{12})_(\d{1,7}|end)\.png$")

# The page's bed rules (loom/src/loom-bed-core.js holds the same numbers for Play).
LOOM_BED_FADE_IN = 2.0
LOOM_BED_FADE_OUT = 3.0
LOOM_BED_DUCK_DB = -12


def sniff_audio_ext(head):
    """The audio type of a file from its first bytes -- the magic, never the file name.
    mp3 (an ID3 tag or an MPEG layer I-III frame sync), wav (RIFF/WAVE), m4a (an ISO-BMFF
    ftyp box of an audio brand), aac (ADTS), ogg (OggS), flac (fLaC). None for anything else,
    a video mp4 included."""
    b = bytes(head or b"")
    if len(b) < 4:
        return None
    if b[:4] == b"fLaC":
        return "flac"
    if b[:4] == b"OggS":
        return "ogg"
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "wav"
    if b[:3] == b"ID3":
        return "mp3"
    if len(b) >= 12 and b[4:8] == b"ftyp":
        try:
            size = int.from_bytes(b[:4], "big")
        except ValueError:
            size = 0
        box = b[8:min(len(b), max(16, size))]
        brands = {box[i:i + 4] for i in range(0, len(box) - 3, 4)}
        if brands & {b"M4A ", b"M4B ", b"M4P ", b"F4A ", b"F4B "}:
            return "m4a"
        return None
    if b[0] == 0xFF and (b[1] & 0xF0) == 0xF0 and ((b[1] >> 1) & 3) == 0:
        return "aac"                        # ADTS: 12-bit sync, layer 00
    if b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and ((b[1] >> 1) & 3) in (1, 2, 3):
        return "mp3"                        # MPEG audio frame sync, layer I-III
    return None


def _unlink_quiet(path):
    """Remove a file if it is there; a missing file or a held handle is not an error (the
    export sweep collects what a Windows handle kept)."""
    try:
        os.unlink(str(path))
    except OSError:
        pass


def loom_edl_zip_stem(name):
    """The export's file stem: the board's name kept to [A-Za-z0-9 _.-], 64 characters at
    most, never empty and never starting with a dot (review F19: it goes into
    Content-Disposition and the zip's entry names)."""
    s = re.sub(r"[^A-Za-z0-9 _.-]", "", str(name or ""))[:64].strip().lstrip(".").strip()
    return s or "storyboard"


_LOOM_BOARD_NAME_RE = re.compile(r'\s*\{\s*"name"\s*:\s*"((?:[^"\\\x00-\x1f]|\\.){0,600})"')


def _json_string_body(text):
    """The text inside a JSON string literal that starts `text`, unescaped as far as it goes
    (a torn file simply stops). Lenient on purpose: it only ever feeds the name salvage."""
    out, i, n = [], 1, len(text)
    simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while i < n:
        ch = text[i]
        if ch == '"':
            break
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= n:
            break
        esc = text[i + 1]
        if esc == "u" and re.match(r"[0-9a-fA-F]{4}$", text[i + 2:i + 6]):
            out.append(chr(int(text[i + 2:i + 6], 16)))
            i += 6
            continue
        out.append(simple.get(esc, esc))
        i += 2
    return "".join(out)


def loom_board_name_salvage(text):
    """A board's name from a file that will not read (GitHub #57), or "" when it cannot be
    read. Best effort and nothing else: the name is the first field of every board, so only a
    `"name": "..."` that opens the board counts (an act's or a cast member's name is never
    taken for it). A board stored as a JSON string (the Loom's own saves) is unescaped first.
    At most 120 characters; never any other content of the board."""
    t = str(text or "").lstrip()
    if t.startswith('"'):
        t = _json_string_body(t)
    m = _LOOM_BOARD_NAME_RE.match(t)
    if not m:
        return ""
    try:
        name = json.loads('"' + m.group(1) + '"')
    except ValueError:
        return ""
    return name.strip()[:120]


def loom_board_beds(projects):
    """The bed files a list of parsed boards references (project.bed.file), valid names only."""
    out = set()
    for p in projects or []:
        bed = p.get("bed") if isinstance(p, dict) else None
        f = str((bed or {}).get("file") or "") if isinstance(bed, dict) else ""
        if LOOM_BED_FILE_RE.match(f):
            out.add(f)
    return out


def loom_bed_windows(spans, own_audio, bed_len=None):
    """Where the bed ducks: [(start, end)] in cut seconds, one per run of consecutive shots
    with their own audio, clipped to the bed's length. `spans` and `own_audio` are per
    segment, in cut order (the twin of loom-bed-core.js's bedPlan windows)."""
    out, at = [], 0.0
    for span, own in zip(spans or [], own_audio or []):
        a, b = at, at + max(0.0, float(span or 0))
        at = b
        if not own:
            continue
        if bed_len is not None:
            b = min(b, float(bed_len))
        if b <= a:
            continue
        if out and abs(out[-1][1] - a) < 1e-9:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def loom_bed_audio_graph(bed_idx, db, cut_len, bed_dur=None, windows=(), cut_label="acut",
                         out_label="aout"):
    """The ffmpeg filter text that mixes a music bed under the Loom's local cut (⇧ Render),
    by the page's rules -- the server's twin of loom-bed-core.js, which Play uses:
      level `db` (−24…0), −12 dB more inside each duck window, a 2 s in-fade and a 3 s
      out-fade, the bed cut to the cut (atrim) and ending with its out-fade there; a shorter
      bed ends where it ends, with its own out-fade, and never loops.
    `bed_idx` is the bed's ffmpeg input index. With `cut_label` (the concatenated shots'
    audio) the two are summed by amix without normalising, so the shots keep their level;
    with cut_label=None the bed IS the cut's audio track. Returns filter chains joined by ';'.
    Pure: dev/tests/test_loom_p_routes.py pins the text."""
    cut_len = max(0.0, float(cut_len or 0))
    try:
        bd = float(bed_dur) if bed_dur not in (None, "") else None
    except (TypeError, ValueError):
        bd = None
    bed_len = min(bd, cut_len) if bd and bd > 0 else cut_len
    try:
        level = int(round(float(db)))
    except (TypeError, ValueError):
        level = -8
    level = max(-24, min(0, level))
    fin = min(LOOM_BED_FADE_IN, bed_len / 2.0)
    fout = min(LOOM_BED_FADE_OUT, bed_len / 2.0)
    chain = ["atrim=end=%.3f" % bed_len, "asetpts=PTS-STARTPTS",
             "aformat=sample_rates=48000:channel_layouts=stereo", "volume=%ddB" % level]
    wins = [(a, min(b, bed_len)) for (a, b) in (windows or ()) if min(b, bed_len) > a]
    if wins:
        chain.append("volume=%ddB:enable='%s'" % (
            LOOM_BED_DUCK_DB, "+".join("between(t,%.3f,%.3f)" % (a, b) for (a, b) in wins)))
    chain.append("afade=t=in:st=0:d=%.3f" % fin)
    chain.append("afade=t=out:st=%.3f:d=%.3f" % (max(0.0, bed_len - fout), fout))
    if cut_label is None:
        return "[%d:a]%s[%s]" % (bed_idx, ",".join(chain), out_label)
    return ";".join([
        "[%d:a]%s[bed]" % (bed_idx, ",".join(chain)),
        "[%s]aformat=sample_rates=48000:channel_layouts=stereo[acutf]" % cut_label,
        "[acutf][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[%s]" % out_label,
    ])


def _date_part_bounds(part):
    """One date spec (2026 / 2026-07 / 2026-07-04 / 2026Q3) -> (start, end_exclusive) as ISO
    prefixes that compare correctly against created_at strings, or None if it is not a real
    date. The end is the START of the next period, so `created_at >= start AND created_at <
    end` covers the whole period whatever the timestamp's length."""
    m = _SEARCH_DATE_PART_RE.match(part)
    if not m:
        return None
    y, mo, d, q = m.group(1), m.group(2), m.group(3), m.group(4)
    yi = int(y)
    if yi < 1:
        return None
    if q:
        sm = (int(q) - 1) * 3 + 1
        em, ey = sm + 3, yi
        if em > 12:
            em, ey = 1, yi + 1
        return ("%s-%02d" % (y, sm), "%04d-%02d" % (ey, em))
    if mo is None:
        return (y, "%04d" % (yi + 1))
    mi = int(mo)
    if not 1 <= mi <= 12:
        return None
    if d is None:
        return ("%s-%s" % (y, mo), "%04d-%02d" % (yi + (mi == 12), 1 if mi == 12 else mi + 1))
    import datetime as _dt
    try:
        day = _dt.date(yi, mi, int(d))
    except ValueError:
        return None
    return (day.isoformat(), (day + _dt.timedelta(days=1)).isoformat())


def _date_clause(value):
    """created: beyond a plain prefix -- a quarter (2026Q3), an inclusive range
    (2026-08..2026-10, 2026-09-15.., ..2026Q2), or a comparison against a quarter. None when
    the value is not one of those (the caller's prefix compare handles the rest)."""
    if ".." in value:
        lo, _, hi = value.partition("..")
        if not lo and not hi:
            return None
        parts, sql = [], []
        if lo:
            b = _date_part_bounds(lo)
            if not b:
                return None
            sql.append("created_at >= ?")
            parts.append(b[0])
        if hi:
            b = _date_part_bounds(hi)
            if not b:
                return None
            sql.append("created_at < ?")
            parts.append(b[1])
        return ("(" + " AND ".join(sql) + ")", parts)
    m = re.match(r"^(>=|<=|>|<)?(\d{4}[Qq][1-4])$", value)
    if not m:
        return None
    b = _date_part_bounds(m.group(2))
    op = m.group(1) or "="
    if op == "=":
        return ("(created_at >= ? AND created_at < ?)", [b[0], b[1]])
    if op == ">=":
        return ("created_at >= ?", [b[0]])
    if op == ">":
        return ("created_at >= ?", [b[1]])
    if op == "<":
        return ("created_at < ?", [b[0]])
    return ("created_at < ?", [b[1]])        # <=


def _lora_name_regex(name):
    name = name.strip()
    if name in ("", "*"):
        return None
    return re.compile(re.escape(name).replace(r"\*", ".*").replace(r"\?", "."), re.I)


def _lora_weight_match(loras, name_pat, op, num):
    """SQL function body: does any LoRA in the 'Name:0.7, Other:1' list match the name (a
    substring, * and ? wildcards, blank/* = any) AND have a weight satisfying `op num`?"""
    try:
        rx = re.compile(name_pat, re.I) if name_pat else None
        num = float(num)
    except (re.error, TypeError, ValueError):
        return 0
    for nm, w in _LORA_ENTRY_RE.findall(str(loras or "")):
        if rx is not None and not rx.search(nm):
            continue
        w = float(w)
        if ((op == ">" and w > num) or (op == ">=" and w >= num) or (op == "<" and w < num)
                or (op == "<=" and w <= num) or (op == "=" and abs(w - num) < 1e-9)):
            return 1
    return 0


def _lora_weight_clause(value):
    m = _SEARCH_LORA_WEIGHT_RE.match(value)
    if not m:
        return None
    rx = _lora_name_regex(_unquote(m.group(1).strip()))
    return ("mg_lora_weight(loras, ?, ?, ?) = 1",
            [rx.pattern if rx else "", m.group(2), float(m.group(3))])


def _operator_clause(key, value):
    """Compile one key:value search token into (sql_clause, params), or None when
    the token isn't a valid operator and should be searched as plain prompt text
    instead (unknown key, empty value, malformed number/date, unrecognized bool)
    -- the way search engines degrade, so a stray colon never errors or surprises."""
    spec = _SEARCH_OPS.get(key.lower())
    if not spec or value == "":
        return None
    kind, col = spec
    if kind == "aspect":
        return _aspect_clause(value)
    if kind == "type":
        return _type_clause(value)
    if kind == "tag":
        # Session N3: the published art tags (substring, as before) OR a whole personal tag.
        return ("(LOWER(COALESCE(art_tags,'')) LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
                "AND (',' || pm.tags || ',') LIKE ? ESCAPE '\\'))",
                [_like_pattern(value), _personal_tag_pattern(value)])
    if kind == "note":
        return ("EXISTS (SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
                "AND LOWER(pm.note) LIKE ? ESCAPE '\\')", [_like_pattern(value)])
    if kind == "text" and col == "loras":
        hit = _lora_weight_clause(value)
        if hit:
            return hit
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
        hit = _date_clause(value)
        if hit:
            return hit
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
                 collection="", no_svg=False):
    """Return (where_clause, params) for the common filter set. `no_svg` leaves SVG rows
    out (by the recorded output format, then the file's extension): the picture list the
    create pickers and the Apple TV client read, since tvOS cannot draw one and no create
    road takes one as a source (3.22 S5)."""
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
        # level by dev/tests/test_search_operators.py): each term may use * / ?
        # wildcards over prompt text, and a term that looks like a WHOLE task/media
        # id (all digits, long enough that a short numeric prompt word can't
        # collide -- PixAI ids run ~18-19 digits) also matches that id EXACTLY, so
        # pasting an id from PixAI's site (or --dump-params output) finds the row.
        # Short numeric terms stay prompt-only: a substring match on ids made a
        # term like "88" match ~14% of the whole catalog by id chance alone,
        # swamping any real prompt hits (found 2026-07-16).
        #
        # A leading `-` negates the token (Session N3): -reject, -tag:x, -"night elf". The
        # clause is wrapped, never rewritten, so a token without one builds the same SQL.
        for tok in _SEARCH_TOKEN_RE.findall(q):
            neg = len(tok) > 1 and tok[0] == "-" and not _SEARCH_NEG_NUMBER_RE.match(tok)
            clause, cparams = _search_token_clause(tok[1:] if neg else tok)
            clauses.append("NOT " + clause if neg else clause)
            params += cparams
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
    if no_svg:
        clauses.append("COALESCE(output_format,'') != 'svg' "
                       "AND LOWER(COALESCE(filename,'')) NOT LIKE '%.svg'")
    return " AND ".join(clauses), params


def get_row(db_path, media_id):
    """Return a single catalog row dict by media_id, or None."""
    with catalog(db_path) as con:
        row = con.execute("SELECT * FROM catalog WHERE media_id=?", (media_id,)).fetchone()
        return dict(row) if row else None


def get_row_by_task(db_path, task_id):
    """One catalog row for a task id, or None. Membership check for
    /api/task-params: a task id this library never downloaded from is refused
    there, so the route can't be used to probe arbitrary task ids under the
    owner's credentials (adversarial review 2026-08-13, finding 4.3)."""
    with catalog(db_path) as con:
        row = con.execute("SELECT * FROM catalog WHERE task_id=? LIMIT 1",
                          (task_id,)).fetchone()
        return dict(row) if row else None


def is_archive_only(row):
    """True when PixAI no longer has this picture, so the library's copy is the only one
    anywhere (#66): its task has left your PixAI history (`deleted_remote == '1'`, as of the
    last --reconcile-deleted, which rewrites it every run) or PixAI dropped this one image
    (`cloud_deleted_at`, per-row and permanent). Pure; `row` is a catalog row dict.

    The grid badges them ARCHIVE, and the bulk "Delete locally" and Duplicate Review name
    them in their confirms before they go with the rest (the owner's ruling, 2026-10-03:
    warn, don't block)."""
    if not row:
        return False
    return (str(row.get("deleted_remote") or "").strip() == "1"
            or bool(str(row.get("cloud_deleted_at") or "").strip()))


def _split_collections(s):
    return [c.strip() for c in (s or "").split(",") if c.strip()]


def unique_collections(db_path):
    """Distinct collection names across the catalog, case-insensitive sorted."""
    with catalog(db_path) as con:
        names = set()
        for (s,) in con.execute("SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
            names.update(_split_collections(s))
        return sorted(names, key=str.lower)


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
    contain spaces but not commas. Returns the number of rows changed.

    Raises CurationError for a SMART collection's name (Session N1): a smart collection
    is a saved search, not a list, so nothing can be added to it by hand."""
    name = (name or "").strip().replace(",", " ").strip()
    if not name or not media_ids:
        return 0
    if _is_smart_name(db_path, name):
        raise CurationError(
            "“{}” is a smart collection, a saved search. Pictures join it by matching "
            "the search, not by being added.".format(name))
    changed = 0
    with catalog(db_path) as con:
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
    return changed


def remove_from_collection(db_path, media_ids, name):
    """Remove a collection label from each media_id. Returns rows changed."""
    name = (name or "").strip()
    if not name or not media_ids:
        return 0
    changed = 0
    with catalog(db_path) as con:
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
    return changed


# ---------------------------------------------------------------------------
# CURATION (Session N, 2026-09-29): smart collections, the collections manager, and the
# personal layer (tags, a keeper|reject mark, a note).
#
# WHERE THINGS LIVE, and the fact the whole session hangs on: the app's "collections" are
# LOCAL. A collection is nothing but a label in the comma-joined `catalog.collections`
# column (moonglade.gallery.add_to_collection above); PixAI has no part in it and nothing in
# this block reaches the network. Hand-picked membership stays there, unchanged. Two new
# tables (see _MIGRATIONS) hold the rest:
#   smart_collections  a saved SEARCH -- the query is stored, the membership never is; it is
#                      computed from the query every time the collection is opened
#   personal_meta      the owner's tags / mark / note, keyed by media_id
# Both are additive: an existing library gains two empty tables and keeps every row.
#
# NOTHING HERE DELETES A PICTURE. Deleting or merging a collection rewrites LABELS on rows;
# it never removes a row, a file or a thumbnail (dev/tests/test_curation.py counts them).
# ---------------------------------------------------------------------------

class CurationError(ValueError):
    """A curation request refused for a reason the owner can read (a taken name, a smart
    collection used as a hand-picked one, an over-long tag). The routes answer it as a 400
    carrying str(e)."""


PERSONAL_MARKS = ("keeper", "reject")
PERSONAL_TAG_MAX_LEN = 32      # characters in one tag
PERSONAL_TAGS_MAX = 32         # tags on one picture (the handoff page's own cap, N3)
PERSONAL_NOTE_MAX = 500        # characters in a note
CURATE_MAX_IDS = 5000          # pictures one bulk request may touch

_TAG_SPACE_RE = re.compile(r"[\s_]+")
_TAG_STRIP_RE = re.compile(r"[^\w-]", re.UNICODE)
_TAG_DASHES_RE = re.compile(r"-{2,}")


def normalize_tag(raw):
    """A personal tag in its stored form: lowercase, hyphenated, letters/digits/hyphens only
    (any script). "Pose Study!" -> "pose-study". Returns "" when nothing is left. The length
    cap is the caller's to enforce (it wants to say so, not silently truncate)."""
    t = _TAG_SPACE_RE.sub("-", str(raw or "").strip().lower())
    t = _TAG_STRIP_RE.sub("", t)
    return _TAG_DASHES_RE.sub("-", t).strip("-")


def _split_tags(s):
    return [t for t in (s or "").split(",") if t]


_CURATION_LOCK = threading.Lock()


def _now_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean_collection_name(name):
    """A collection name as stored: commas become spaces (the column is comma-joined), runs of
    whitespace collapse, ends are trimmed."""
    return re.sub(r"\s+", " ", str(name or "").replace(",", " ")).strip()


def _all_collection_names(con):
    """(hand_picked, smart) name lists, from one open connection."""
    hand = set()
    for (s,) in con.execute("SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
        hand.update(_split_collections(s))
    smart = [r[0] for r in con.execute("SELECT name FROM smart_collections")]
    return sorted(hand, key=str.lower), sorted(smart, key=str.lower)


def _is_smart_name(db_path, name):
    """Does `name` belong to a smart collection (compared without regard to case, since
    names are unique that way)? A hand-picked label may not take a smart collection's name."""
    low = str(name or "").strip().lower()
    if not low:
        return False
    with catalog(db_path) as con:
        return any(r[0].lower() == low for r in con.execute("SELECT name FROM smart_collections"))


def list_smart_collections(db_path):
    """[{name, query}] for every smart collection, A-Z without regard to case."""
    with catalog(db_path) as con:
        rows = con.execute("SELECT name, query FROM smart_collections").fetchall()
    return sorted(({"name": r["name"], "query": r["query"]} for r in rows),
                  key=lambda d: d["name"].lower())


def smart_collection_query(db_path, name):
    """The saved query of the smart collection called exactly `name`, or None."""
    if not name:
        return None
    with catalog(db_path) as con:
        r = con.execute("SELECT query FROM smart_collections WHERE name=?", (str(name),)).fetchone()
    return r["query"] if r else None


def _expand_smart(db_path, q, collection):
    """(q, collection) with a smart collection folded into the search. Opening a smart
    collection IS running its saved query, ANDed with whatever the search field holds: its
    tokens are prepended to `q` and the collection filter drops away. A hand-picked name (or
    none) passes through untouched, so this costs one indexed lookup and only when a
    collection is named."""
    if not collection:
        return q, collection
    saved = smart_collection_query(db_path, collection)
    if saved is None:
        return q, collection
    return ((saved + " " + q).strip() if q else saved), ""


def _auto_smart_name(query):
    """The name a smart collection gets when the owner did not type one: the query with its
    operator punctuation softened, 28 characters at most (the handoff page's own rule)."""
    n = re.sub(r"\s+", " ", re.sub("[★:\"]", " ", str(query or ""))).strip()[:28].strip()
    return n or "Smart collection"


def save_smart_collection(db_path, query, name="", replace=""):
    """Create a smart collection from a search, or (with `replace`) save a new query over an
    existing one. Only the QUERY is stored. Returns {name, query, created}.

    A typed `name` that is taken raises CurationError; an unnamed one takes the query's own
    words and, when that is taken too, the next free "… 2", "… 3"."""
    q = " ".join(str(query or "").split())
    if not q:
        raise CurationError("Type a search first, then save it.")
    with catalog(db_path) as con:
        with _CURATION_LOCK:
            if replace:
                if not con.execute("SELECT 1 FROM smart_collections WHERE name=?",
                                   (replace,)).fetchone():
                    raise CurationError("There is no smart collection called “{}”.".format(replace))
                con.execute("UPDATE smart_collections SET query=?, updated_at=? WHERE name=?",
                            (q, _now_stamp(), replace))
                con.commit()
                return {"name": replace, "query": q, "created": False}
            hand, smart = _all_collection_names(con)
            taken = {n.lower() for n in hand + smart}
            typed = _clean_collection_name(name)
            base = typed or _auto_smart_name(q)
            if typed and base.lower() in taken:
                raise CurationError("A collection called “{}” already exists.".format(base))
            final, n = base, 2
            while final.lower() in taken:
                final = "{} {}".format(base, n)
                n += 1
            now = _now_stamp()
            con.execute("INSERT INTO smart_collections (name, query, created_at, updated_at) "
                        "VALUES (?,?,?,?)", (final, q, now, now))
            con.commit()
            return {"name": final, "query": q, "created": True}


def _rows_with_label(con, name):
    """(media_id, collections) of every catalog row carrying exactly the label `name`."""
    return con.execute(
        "SELECT media_id, collections FROM catalog WHERE (',' || COALESCE(collections,'') || ',') "
        "LIKE ? ESCAPE '\\'", ("%," + _like_escape(name) + ",%",)).fetchall()


def rename_collection(db_path, old, new):
    """Rename a collection, hand-picked or smart. The new name is trimmed and must be unique
    (case-insensitively) among ALL collections; renaming only the case of its own name is
    allowed. Every picture keeps its membership: a hand-picked rename rewrites the label on
    the rows that carry it, a smart rename changes one row of smart_collections."""
    old = str(old or "").strip()
    new = _clean_collection_name(new)
    if not old:
        raise CurationError("Say which collection to rename.")
    if not new:
        raise CurationError("A collection needs a name.")
    with catalog(db_path) as con:
        with _CURATION_LOCK, _COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            if old not in smart and old not in hand:
                raise CurationError("There is no collection called “{}”.".format(old))
            if new.lower() in {n.lower() for n in hand + smart if n != old}:
                raise CurationError("A collection called “{}” already exists.".format(new))
            if new == old:
                return {"name": new, "kind": "smart" if old in smart else "hand", "changed": 0}
            if old in smart:
                con.execute("UPDATE smart_collections SET name=?, updated_at=? WHERE name=?",
                            (new, _now_stamp(), old))
                con.commit()
                return {"name": new, "kind": "smart", "changed": 1}
            changed = 0
            # P6: the manual order follows the rename (any stale rows under the new name go
            # first, so the move cannot collide on the primary key).
            con.execute("DELETE FROM collection_order WHERE name=?", (new,))
            con.execute("UPDATE collection_order SET name=? WHERE name=?", (new, old))
            for r in _rows_with_label(con, old):
                cols = [new if c == old else c for c in _split_collections(r["collections"])]
                seen, out = set(), []
                for c in cols:            # a row can never end up holding the label twice
                    if c not in seen:
                        seen.add(c)
                        out.append(c)
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(out), r["media_id"]))
                changed += 1
            con.commit()
            return {"name": new, "kind": "hand", "changed": changed}


def merge_collections(db_path, names):
    """Merge two or more HAND-PICKED collections into the first name given: every picture in
    any of them ends up in the first (once, however many it was in), and the others cease to
    exist. A smart collection cannot merge (it holds no pictures to move). Returns
    {target, merged, pictures, changed}. No picture is removed from the library."""
    order = []
    for n in names or []:
        n = str(n or "").strip()
        if n and n not in order:
            order.append(n)
    if len(order) < 2:
        raise CurationError("Pick two or more hand-picked collections to merge.")
    with catalog(db_path) as con:
        with _CURATION_LOCK, _COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            for n in order:
                if n in smart:
                    raise CurationError("“{}” is a smart collection and can’t merge. "
                                        "Edit its query instead.".format(n))
                if n not in hand:
                    raise CurationError("There is no hand-picked collection called “{}”.".format(n))
            target, others = order[0], set(order[1:])
            changed = 0
            # P6: the target keeps its manual order; the merged-in pictures have no position
            # there, so they follow it, oldest first. The merged collections' orders go.
            con.executemany("DELETE FROM collection_order WHERE name=?", [(n,) for n in sorted(others)])
            for r in con.execute("SELECT media_id, collections FROM catalog "
                                 "WHERE COALESCE(collections,'') != ''").fetchall():
                cols = _split_collections(r["collections"])
                if not any(c in others for c in cols):
                    continue
                out = []
                for c in cols:
                    c = target if c in others else c
                    if c not in out:
                        out.append(c)
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(out), r["media_id"]))
                changed += 1
            con.commit()
            pictures = len(_rows_with_label(con, target))
    return {"target": target, "merged": order[1:], "pictures": pictures, "changed": changed}


def delete_collection(db_path, name):
    """Delete a collection: a hand-picked one loses its label from every picture, a smart one
    loses its saved query. THE PICTURES STAY, always; `kept` says how many were in it (for a
    smart collection, how many matched a moment ago). Returns {name, kind, kept}."""
    name = str(name or "").strip()
    if not name:
        raise CurationError("Say which collection to delete.")
    with catalog(db_path) as con:
        with _CURATION_LOCK, _COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            if name in smart:
                kind = "smart"
            elif name in hand:
                kind = "hand"
            else:
                raise CurationError("There is no collection called “{}”.".format(name))
    if kind == "smart":
        _, kept = query_catalog(db_path, collection=name, page=1, page_size=1)
        with catalog(db_path) as con:
            with _CURATION_LOCK:
                con.execute("DELETE FROM smart_collections WHERE name=?", (name,))
                con.commit()
        return {"name": name, "kind": "smart", "kept": kept}
    with catalog(db_path) as con:
        with _CURATION_LOCK, _COLLECTIONS_LOCK:
            kept = 0
            con.execute("DELETE FROM collection_order WHERE name=?", (name,))   # P6: its order goes too
            for r in _rows_with_label(con, name):
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(c for c in _split_collections(r["collections"]) if c != name),
                             r["media_id"]))
                kept += 1
            con.commit()
    return {"name": name, "kind": "hand", "kept": kept}


# ---- manual order (Session P, P6) --------------------------------------------

def _collection_kind(con, name):
    """"smart" | "hand" | None for a collection name, from one open connection."""
    hand, smart = _all_collection_names(con)
    if name in smart:
        return "smart"
    if name in hand:
        return "hand"
    return None


def ordered_members(db_path, name):
    """The members of collection `name`, in its order: {name, kind, media_ids, manual}.

    Hand-picked: the labelled pictures (those the collection's own view shows, a file on
    disk) -- the ones with a position first, by position; then the ones without (added since
    the order was saved) OLDEST first (ruling 9). A position whose picture has left the
    collection is ignored. `manual` says whether any position is in force.
    Smart: its query's current matches, oldest first; never manual (membership is live).
    Unknown name: kind None, no ids. Read-only."""
    name = str(name or "").strip()
    if not name:
        return {"name": "", "kind": None, "media_ids": [], "manual": False}
    with catalog(db_path) as con:
        kind = _collection_kind(con, name)
        if kind == "hand":
            rows = con.execute(
                "SELECT c.media_id, o.position FROM catalog c LEFT JOIN collection_order o "
                "ON o.name = ? AND o.media_id = c.media_id "
                "WHERE c.filename != '' AND (',' || COALESCE(c.collections,'') || ',') LIKE ? ESCAPE '\\' "
                "ORDER BY (o.position IS NULL), o.position, c.created_at ASC, c.media_id ASC",
                (name, "%," + _like_escape(name) + ",%")).fetchall()
            return {"name": name, "kind": "hand", "media_ids": [str(r[0]) for r in rows],
                    "manual": any(r[1] is not None for r in rows)}
    if kind == "smart":
        rows, _ = query_catalog(db_path, collection=name, sort="oldest", page_size=None)
        return {"name": name, "kind": "smart", "media_ids": [str(r["media_id"]) for r in rows],
                "manual": False}
    return {"name": name, "kind": None, "media_ids": [], "manual": False}


def set_collection_order(db_path, name, media_ids):
    """Save a hand-picked collection's manual order: positions 0..n-1 for `media_ids`, in ONE
    transaction, replacing the collection's old positions (which also prunes the rows of
    pictures no longer in it). Refuses a smart collection (its membership is live), an unknown
    one, a repeated id and any id that is not a member. Returns ordered_members() after."""
    name = str(name or "").strip()
    ids = [str(m).strip() for m in (media_ids or [])]
    if not name:
        raise CurationError("Say which collection to order.")
    if len(ids) > CURATE_MAX_IDS:
        raise CurationError("A collection order holds at most {} pictures.".format(CURATE_MAX_IDS))
    if len(set(ids)) != len(ids) or any(not m for m in ids):
        raise CurationError("Each picture appears once in an order.")
    with catalog(db_path) as con:
        with _CURATION_LOCK, _COLLECTIONS_LOCK:
            kind = _collection_kind(con, name)
            if kind == "smart":
                raise CurationError("“{}” is a smart collection. Its pictures are the search's "
                                    "matches, so it can’t be ordered by hand.".format(name))
            if kind != "hand":
                raise CurationError("There is no hand-picked collection called “{}”.".format(name))
            members = {str(r["media_id"]) for r in _rows_with_label(con, name)}
            stray = [m for m in ids if m not in members]
            if stray:
                raise CurationError("{} of those {} not in “{}”.".format(
                    len(stray), "is" if len(stray) == 1 else "are", name))
            con.execute("DELETE FROM collection_order WHERE name=?", (name,))
            con.executemany("INSERT INTO collection_order (name, media_id, position) VALUES (?,?,?)",
                            [(name, m, i) for i, m in enumerate(ids)])
            con.commit()
    return ordered_members(db_path, name)


def collection_summaries(db_path):
    """Every collection with what the manager and the list show: {name, kind, count, cover,
    query?}. Hand-picked counts are pictures that still have a file (the count a search
    would give); a smart collection's count is its query run right now. `cover` is the
    newest member's media_id. A-Z without regard to case, hand-picked and smart together.
    Read-only."""
    hand = {}
    with catalog(db_path) as con:
        for r in con.execute(
                "SELECT media_id, filename, collections FROM catalog "
                "WHERE COALESCE(collections,'') != '' ORDER BY created_at DESC"):
            for n in _split_collections(r["collections"]):
                h = hand.setdefault(n, {"count": 0, "cover": ""})
                if (r["filename"] or "") != "":
                    h["count"] += 1
                    if not h["cover"]:
                        h["cover"] = str(r["media_id"])
    out = [{"name": n, "kind": "hand", "count": h["count"], "cover": h["cover"]}
           for n, h in hand.items()]
    for s in list_smart_collections(db_path):
        rows, total = query_catalog(db_path, collection=s["name"], page=1, page_size=1)
        out.append({"name": s["name"], "kind": "smart", "count": total, "query": s["query"],
                    "cover": str(rows[0]["media_id"]) if rows else ""})
    return sorted(out, key=lambda d: d["name"].lower())


# ---- the personal layer -----------------------------------------------------

def personal_get(db_path, media_ids):
    """{media_id: {tags: [...], mark, note}} for the given pictures. Only pictures that have
    something are present -- a picture with no personal layer is simply absent, and the
    caller treats it as tags [] / mark "" / note ""."""
    ids = [str(m) for m in (media_ids or []) if str(m)]
    out = {}
    if not ids:
        return out
    with catalog(db_path) as con:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in con.execute(
                    "SELECT media_id, tags, mark, note FROM personal_meta WHERE media_id IN ({})"
                    .format(",".join("?" * len(chunk))), chunk):
                out[r["media_id"]] = {"tags": _split_tags(r["tags"]),
                                      "mark": r["mark"] or "", "note": r["note"] or ""}
    return out


def _curation_state(con, mid):
    """One picture's curation state -- {rating, mark, tags, note} -- or None when it is not in
    the catalog. `rating` is the ordinary catalog rating (the stars on every card); the rest
    is the personal layer."""
    row = con.execute("SELECT rating FROM catalog WHERE media_id=?", (mid,)).fetchone()
    if row is None:
        return None
    rs = str(row[0] or "")
    p = con.execute("SELECT tags, mark, note FROM personal_meta WHERE media_id=?", (mid,)).fetchone()
    return {"rating": min(5, int(rs)) if rs.isdigit() else 0,
            "mark": (p["mark"] if p else "") or "",
            "tags": _split_tags(p["tags"]) if p else [],
            "note": (p["note"] if p else "") or ""}


def _write_curation_state(con, mid, new, old):
    """Write `new` where it differs from `old`. The personal row is created, updated, or -- when
    all three fields are empty -- deleted, so the table only ever holds pictures that have
    something to say."""
    if new["rating"] != old["rating"]:
        con.execute("UPDATE catalog SET rating=? WHERE media_id=?",
                    (str(new["rating"]) if new["rating"] else "", mid))
    if (new["mark"], new["tags"], new["note"]) != (old["mark"], old["tags"], old["note"]):
        if not (new["mark"] or new["tags"] or new["note"]):
            con.execute("DELETE FROM personal_meta WHERE media_id=?", (mid,))
        else:
            con.execute("INSERT OR REPLACE INTO personal_meta (media_id, tags, mark, note, updated_at) "
                        "VALUES (?,?,?,?,?)",
                        (mid, ",".join(new["tags"]), new["mark"], new["note"], _now_stamp()))


def _clean_tag(raw):
    t = normalize_tag(raw)
    if not t:
        raise CurationError("A tag needs a letter or a number in it.")
    if len(t) > PERSONAL_TAG_MAX_LEN:
        raise CurationError("A tag is up to {} characters.".format(PERSONAL_TAG_MAX_LEN))
    return t


def _clean_note(raw):
    note = str(raw if raw is not None else "").strip()
    if len(note) > PERSONAL_NOTE_MAX:
        raise CurationError("A note is up to {} characters.".format(PERSONAL_NOTE_MAX))
    return note


def _clean_mark(raw):
    m = str(raw if raw is not None else "").strip().lower()
    if m in ("", "none", "null"):
        return ""
    if m not in PERSONAL_MARKS:
        raise CurationError("A mark is keeper, reject or none.")
    return m


def _clean_rating(raw):
    if isinstance(raw, bool):
        raise CurationError("A rating is a whole number from 0 to 5.")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise CurationError("A rating is a whole number from 0 to 5.")
    if not 0 <= n <= 5:
        raise CurationError("A rating is a whole number from 0 to 5.")
    return n


def _clean_ids(media_ids):
    if not isinstance(media_ids, (list, tuple)):
        raise CurationError("No pictures given.")
    seen, out = set(), []
    for m in media_ids:
        m = str(m).strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    if not out:
        raise CurationError("No pictures given.")
    if len(out) > CURATE_MAX_IDS:
        raise CurationError("That is more than {} pictures at once.".format(CURATE_MAX_IDS))
    return out


def curate_apply(db_path, media_ids, op):
    """Apply one change -- rating, mark, add_tag, remove_tag or note -- to every given picture.

    Returns {changed, prev, after, skipped, refused}. `prev` and `after` hold the full
    {rating, mark, tags, note} state of exactly the pictures that CHANGED, so the caller can
    put each picture back the way IT was (curate_restore) rather than resetting them all to
    one value, and so the count it shows is what really changed: setting a rating a picture
    already has is a no-op, not a change. `skipped` counts ids not in the catalog; `refused`
    counts pictures already at the tag cap. Local catalog only -- nothing here is sent to PixAI."""
    if not isinstance(op, dict) or not op:
        raise CurationError("Nothing to change.")
    clean = {}
    if "rating" in op:
        clean["rating"] = _clean_rating(op["rating"])
    if "mark" in op:
        clean["mark"] = _clean_mark(op["mark"])
    if "add_tag" in op:
        clean["add_tag"] = _clean_tag(op["add_tag"])
    if "remove_tag" in op:
        clean["remove_tag"] = normalize_tag(op["remove_tag"])
    if "note" in op:
        clean["note"] = _clean_note(op["note"])
    if not clean:
        raise CurationError("Nothing to change.")
    ids = _clean_ids(media_ids)
    prev, after, skipped, refused = {}, {}, 0, 0
    with catalog(db_path) as con:
        with _CURATION_LOCK:
            for mid in ids:
                cur = _curation_state(con, mid)
                if cur is None:
                    skipped += 1
                    continue
                new = {"rating": cur["rating"], "mark": cur["mark"],
                       "tags": list(cur["tags"]), "note": cur["note"]}
                if "rating" in clean:
                    new["rating"] = clean["rating"]
                if "mark" in clean:
                    new["mark"] = clean["mark"]
                if "add_tag" in clean and clean["add_tag"] not in new["tags"]:
                    if len(new["tags"]) >= PERSONAL_TAGS_MAX:
                        refused += 1
                    else:
                        new["tags"].append(clean["add_tag"])
                if "remove_tag" in clean:
                    new["tags"] = [t for t in new["tags"] if t != clean["remove_tag"]]
                if "note" in clean:
                    new["note"] = clean["note"]
                if new == cur:
                    continue
                _write_curation_state(con, mid, new, cur)
                prev[mid], after[mid] = cur, new
            con.commit()
    return {"changed": len(after), "prev": prev, "after": after,
            "skipped": skipped, "refused": refused}


def curation_rows(db_path):
    """The owner's whole curation layer as plain rows, for the curation sidecar export
    (moonglade/curation_io.py): {catalog: rows carrying a rating or a collection label,
    personal: every personal_meta row, smart: every smart collection, order: every manual
    position by name then position}. Read-only."""
    with catalog(db_path) as con:
        return {
            "catalog": [dict(r) for r in con.execute(
                "SELECT media_id, rating, collections FROM catalog "
                "WHERE COALESCE(media_id,'') != '' AND (COALESCE(NULLIF(rating,''),'0') != '0' "
                "OR COALESCE(collections,'') != '') ORDER BY media_id")],
            "personal": [dict(r) for r in con.execute(
                "SELECT media_id, tags, mark, note FROM personal_meta ORDER BY media_id")],
            "smart": [dict(r) for r in con.execute(
                "SELECT name, query FROM smart_collections ORDER BY name")],
            "order": [dict(r) for r in con.execute(
                "SELECT name, media_id, position FROM collection_order "
                "ORDER BY name, position")],
        }


def curate_restore(db_path, prev):
    """Undo for curate_apply: put each picture back to the state `prev` holds for it. Every
    entry is validated before anything is written, so a bad request changes nothing. Returns
    {restored, after}."""
    if not isinstance(prev, dict) or not prev:
        raise CurationError("Nothing to restore.")
    if len(prev) > CURATE_MAX_IDS:
        raise CurationError("That is more than {} pictures at once.".format(CURATE_MAX_IDS))
    wanted = {}
    for mid, st in prev.items():
        if not isinstance(st, dict):
            raise CurationError("A saved state is missing its values.")
        tags = []
        for t in st.get("tags") or []:
            t = _clean_tag(t)
            if t not in tags:
                tags.append(t)
        if len(tags) > PERSONAL_TAGS_MAX:
            raise CurationError("A picture holds at most {} tags.".format(PERSONAL_TAGS_MAX))
        wanted[str(mid)] = {"rating": _clean_rating(st.get("rating", 0)),
                            "mark": _clean_mark(st.get("mark")), "tags": tags,
                            "note": _clean_note(st.get("note"))}
    after = {}
    with catalog(db_path) as con:
        with _CURATION_LOCK:
            for mid, new in wanted.items():
                cur = _curation_state(con, mid)
                if cur is None or new == cur:
                    continue
                _write_curation_state(con, mid, new, cur)
                after[mid] = new
            con.commit()
    return {"restored": len(after), "after": after}


def query_catalog(db_path, q="", model="", date_from="", date_to="",
                  sort="newest", page=1, page_size=100, batch="", rating_min=0,
                  published_only=False, art_tag="", lora="", media_type="", source="",
                  collection="", series="", no_svg=False):
    """Return (rows, total) with filtering, sorting and pagination done in SQL. `no_svg`
    leaves SVG rows out (see _build_where).

    `series` constrains the result to one dial-in series' members (#34 direction
    B, the ?series=<sid> "open a stack" view): the sid resolves through the series
    cache to its member task_ids and the WHERE gains a parameterized
    `task_id IN (...)` over exactly that (naturally size-capped) list. An UNKNOWN
    sid resolves to no members, which becomes an always-false clause -- an empty
    result, never an error, and never a bare `IN ()` (a SQL syntax error). The ids
    are bound as placeholders, like /api/siblings, so a sid can't inject SQL.

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
    q, collection = _expand_smart(db_path, q, collection)
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection, no_svg=no_svg)
    where, params = _narrow_to_series(db_path, series, where, params)
    order, order_params = _order_sql(sort, collection)
    with catalog(db_path) as con:
        if page_size is None:
            rows = con.execute(
                "SELECT * FROM catalog WHERE {} ORDER BY {}".format(where, order),
                list(params) + order_params,
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
            list(params) + order_params + [page_size, (max(1, page) - 1) * page_size],
        ).fetchall()
        return [dict(r) for r in rows], total


def _narrow_to_series(db_path, series, where, params):
    """(where, params) narrowed to one dial-in series' members when `series` is set, else
    returned untouched. The ONE place the ?series=<sid> clause is built, so the paged
    listing (query_catalog) and the ordered id walk behind the picture page
    (list_media_ids) cannot drift apart: an UNKNOWN sid becomes an always-false clause
    (an empty result, never a bare `IN ()`), and the member task_ids are bound as
    placeholders."""
    if not series:
        return where, params
    member_ids = _series_member_task_ids(db_path, series)
    if member_ids:
        where += " AND task_id IN ({})".format(",".join("?" * len(member_ids)))
        return where, list(params) + member_ids
    return where + " AND 1=0", params   # unknown sid -> empty result, not an error


def _series_member_task_ids(db_path, sid):
    """Sanitized member task_ids for a dial-in series id, or [] for an unknown sid
    (#34 direction B, the ?series= filter). Resolved through the series cache; the
    list is exactly the series' own tasks -- so it is naturally capped at the
    series' real size -- each coerced to a non-empty, de-duplicated string, ready
    for safe parameterized IN-clause binding (query_catalog does the binding)."""
    _, by_sid = _series.series_index(db_path)
    s = by_sid.get(str(sid or "").strip())
    if not s:
        return []
    out, seen = [], set()
    for step in s.get("steps", []):
        tid = str(step.get("task_id") or "").strip()
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def batch_member_order(rows):
    """One task's surviving catalog rows in #33's BATCH order -- PixAI's own output
    number (`batch_index`) when EVERY row carries one, else media_id ascending.

    The all-or-nothing rule is compute_series' own (see its "member media_ids are
    ordered the way /api/siblings orders them" note): a partly-numbered task would
    otherwise interleave numbered and unnumbered rows into an order nothing else in
    the app agrees with. Keeping the rule here means a BATCH stack lists a task's
    pictures in exactly the order its sibling strip and its series run already do.
    Pure -- no db, so dev/tests/test_batch_stack.py drives it directly."""
    def _bi(r):
        try:
            return int(str(r.get("batch_index") or "").strip())
        except ValueError:
            return None
    if rows and all(_bi(r) is not None for r in rows):
        return sorted(rows, key=lambda r: (_bi(r), str(r.get("media_id") or "")))
    return sorted(rows, key=lambda r: str(r.get("media_id") or ""))


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
        # #34 direction B: a ?series= drill-down is a real filter query_catalog honours
        # (like batch above), so /export-csv must carry it too -- otherwise exporting an
        # open series stack drops the constraint and dumps the whole filtered library.
        "series":         args.get("series", ""),
    }
    # Every default here is falsy (""/0/False), so dropping falsy values is exactly
    # "drop the filters the user didn't set".
    return {k: v for k, v in found.items() if v}


def catalog_counts(db_path):
    """At-a-glance header stats: image count, video count, distinct collections.
    Cheap COUNTs over the catalog. Fails soft to zeros."""
    with catalog(db_path) as con:
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



# ---------------------------------------------------------------------------
# CATALOG VERBS -- the questions the web routes ask of the catalog
#
# Every one of these was raw SQL inside a route handler in create_app until
# 2026-08-23: eleven handlers and inner functions opened their own connection and
# wrote their own SELECT/UPDATE against `catalog`, which is exactly what
# architecture.md's "all I/O goes through helpers -- never raw SQL elsewhere" said
# did not happen. A verb is named for what the DOMAIN calls the question, takes a
# db_path, and returns PLAIN DATA (dicts, lists, ints) -- never a Row, never a live
# connection, never a Response. Shaping that data into a payload, and the URLs in
# it, stays at the handler; the SQL stays here.
#
# The SQL below is the SAME SQL those handlers held -- same columns, same WHERE,
# same ORDER BY, same LIMITs. This move was a relocation, not a rewrite.
# ---------------------------------------------------------------------------

def task_media(db_path, task_id):
    """Every catalog row belonging to one generation task: what the task produced,
    locally. Three callers needed exactly this and each had its own copy of the
    query -- the live-mirror's "a concurrent collect already finished, read the
    result back" path, /api/import-task's already-catalogued precheck, and the bulk
    delete's per-task local purge -- so they share one verb and one column list.
    Empty list for a task this library never downloaded.

    `cloud_deleted_at` rides along for the third caller: a row carrying it is one
    whose local copy is the only copy left anywhere, so the bulk purge has to know
    which rows to walk around before it takes the rest. `artwork_id` (2026-09-26) is the
    per-image delete dialog's catalog fallback for "is this generation published"."""
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, is_video, filename, cloud_deleted_at, artwork_id "
            "FROM catalog WHERE task_id=?",
            (str(task_id),)).fetchall()
        return [dict(r) for r in rows]


def media_dims(db_path, media_ids):
    """{media_id: (width, height)} for the given ids this catalog knows a positive size for,
    as ints; an id with no row, or a blank / zero / unreadable size, is simply absent. The
    LoRA-training image rule (core.check_training_images) reads it and lists an absent id as
    not checked. Chunked for SQLite's bound-parameter cap."""
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    out = {}
    with catalog(db_path) as con:
        for i in range(0, len(ids), _TASK_CHUNK):
            chunk = ids[i:i + _TASK_CHUNK]
            for r in con.execute(
                    "SELECT media_id, width, height FROM catalog WHERE media_id IN ({})"
                    .format(",".join("?" * len(chunk))), chunk):
                try:
                    w, h = int(float(r["width"] or 0)), int(float(r["height"] or 0))
                except (TypeError, ValueError):
                    continue
                if w > 0 and h > 0:
                    out[str(r["media_id"])] = (w, h)
    return out


def published_delete_note(published, unchecked=False, tasks=1, unchecked_tasks=None):
    """The delete dialogs' sentence about published artwork (SCOPE_2026-09-26 E5), or "".

    PixAI's own contract says its task delete also deletes the task's linked artwork. Whether
    the GraphQL delete this app sends does the same is unconfirmed, hence "may". `published`
    counts artworks the dialog knows of; a blank catalog artwork_id is "not known", so this
    never says that none are published -- when publication could not be looked up at all
    (`unchecked`) it says exactly that instead.

    PART-CHECKED. When only some of the tasks could not be checked (`unchecked_tasks` of
    `tasks`), or a count was just given, "whether any of these are published was not checked"
    would contradict what the dialog does know -- so it says how many tasks went unchecked.

    The per-image dialog words it here; the bulk dialog (ActionsMenu.jsx) words the same
    sentences from the preview's counts, and a guard on each side pins the wording."""
    parts = []
    n = int(published or 0)
    if n > 0:
        parts.append("{} of these {} published on PixAI. Deleting the {} may remove the "
                     "published artwork too.".format(n, "is" if n == 1 else "are",
                                                     "task" if tasks == 1 else "tasks"))
    if unchecked:
        k = int(unchecked_tasks or 0)
        if n > 0 or 0 < k < tasks:
            parts.append("{} not checked for published artwork{}".format(
                ("{} of the {} tasks {}".format(k, tasks, "was" if k == 1 else "were")
                 if k > 0 else "Some of the tasks were"),
                "." if n > 0 else " — deleting a task may remove its published artwork too."))
        else:
            parts.append("Whether any of these are published on PixAI was not checked "
                         "— deleting a task may remove its published artwork too.")
    return " ".join(parts)


def mark_cloud_deleted(db_path, media_id, when):
    """Record that PixAI no longer has THIS image: the `deletedAt` stamp its entry in the
    task's outputs.batch carries.

    Per-ROW and permanent, which is why it is not `deleted_remote` -- that one is a
    task-level advisory --reconcile-deleted rewrites on every run. Nothing local is removed
    by this: a row carrying the stamp is one whose local copy is now the only copy anywhere.
    Fails soft to 0 written; a marker that could break the delete dialog would be worse than
    a marker that is late."""
    mid = str(media_id or "").strip()
    stamp = str(when or "").strip()
    if not mid or not stamp:
        return 0
    try:
        with catalog(db_path) as con:
            n = con.execute("UPDATE catalog SET cloud_deleted_at=? WHERE media_id=?",
                            (stamp, mid)).rowcount
            con.commit()
            return n
    except sqlite3.Error:
        return 0


def task_media_count(db_path, task_id):
    """How many catalog rows share a task id -- is this picture one of a batch, or
    the only thing its task made? A COUNT rather than task_media() because the
    single delete-image dialog asks nothing else about them. Fails soft to 0: a
    number on a confirm dialog must never be able to break the dialog."""
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    try:
        with catalog(db_path) as con:
            return int(con.execute(
                "SELECT COUNT(*) FROM catalog WHERE task_id = ?", (tid,)).fetchone()[0])
    except sqlite3.Error:
        return 0


# sqlite's default host-parameter ceiling is 999, and this is well inside it while
# still cutting a big selection to a handful of passes.
_TASK_CHUNK = 400


def _delete_targets(con, media_ids):
    """The shared selection -> (task ids, local-only rows) resolution behind BOTH
    /api/delete-preview and the bulk delete. Shared rather than copied so the preview
    cannot drift from the action it previews: a dialog that lists a different blast
    radius than the delete then takes is worse than showing nothing at all.

    Returns (sel_rows, task_ids, local_only) where task_ids is sorted+deduped (one
    cloud delete per task no matter how many of its images were selected) and
    local_only holds the rows with no task id at all -- imports, which have nothing
    on PixAI to delete and are purged locally only.

    Takes a connection, not a db_path: delete_targets() and delete_preview_rows()
    both need this answer plus more from the SAME open connection."""
    sel_rows = [con.execute(
        "SELECT media_id, task_id, filename FROM catalog WHERE media_id=?", (m,)
    ).fetchone() for m in media_ids]
    sel_rows = [dict(r) for r in sel_rows if r]
    task_ids = sorted({(r.get("task_id") or "").strip()
                       for r in sel_rows if (r.get("task_id") or "").strip()})
    local_only = [r for r in sel_rows if not (r.get("task_id") or "").strip()]
    return sel_rows, task_ids, local_only


def _members_of_tasks(con, task_ids):
    """{task_id: [row, ...]} for every media in the given tasks, in ONE chunked pass
    instead of a query per task.

    Rows come back grouped and sorted here rather than relying on the query's order,
    because one statement now returns several tasks interleaved. (The chunked IN also
    predates the idx_task_id index: measured on a 36,000-row catalog, 800 per-task
    scans cost 8.6s inside the request /api/delete-preview's dialog was waiting on,
    against 38ms chunked.)"""
    out = {}
    for i in range(0, len(task_ids), _TASK_CHUNK):
        chunk = task_ids[i:i + _TASK_CHUNK]
        rows = con.execute(
            # cloud_deleted_at rides along (2026-09-07) for the delete preview's live
            # check: it is one of the two sources _rows_the_bulk_purge_must_keep keeps
            # rows back from, and reading it here costs nothing -- same statement, one
            # more column, so the chunked-pass guarantee above is untouched.
            # artwork_id rides along the same way (2026-09-26, SCOPE_2026-09-26 E5): the
            # preview's published-artwork count falls back to it for a task the live check
            # did not read (over its 40-task cap, or unanswered).
            "SELECT media_id, task_id, is_video, poster_media_id, cloud_deleted_at, artwork_id "
            "FROM catalog WHERE task_id IN ({})".format(",".join("?" * len(chunk))), chunk)
        for r in rows:
            out.setdefault(r["task_id"], []).append(dict(r))
    for members in out.values():
        members.sort(key=lambda r: r["media_id"])
    return out


def delete_targets(db_path, media_ids):
    """What a selection of media_ids actually resolves to for a delete:
    (sel_rows, task_ids, local_only). See _delete_targets for the shape."""
    with catalog(db_path) as con:
        return _delete_targets(con, media_ids)


def delete_preview_rows(db_path, media_ids, task_cap=None):
    """Everything "Delete from PixAI" needs to describe its own blast radius before
    anything fires, in ONE connection: the selection resolved to tasks, each task
    expanded to its FULL catalog membership (deleting on PixAI is task-level, so
    picking one image of a batch takes all four), and the display-capped rows for the
    task-less imports the same button purges locally.

    Returns {sel_rows, task_ids, local_only, members_by_task, local_rows}. The caps
    are DISPLAY bounds on `local_rows` only -- task_ids and local_only always describe
    the entire selection, because the totals are what the user reads to decide."""
    cap = DELETE_PREVIEW_TASK_CAP if task_cap is None else task_cap
    with catalog(db_path) as con:
        sel_rows, task_ids, local_only = _delete_targets(con, media_ids)
        members_by_task = _members_of_tasks(con, task_ids)
        shown = [con.execute(
            "SELECT media_id, is_video, poster_media_id FROM catalog WHERE media_id=?",
            (r["media_id"],)).fetchone() for r in local_only[:cap]]
        local_rows = [dict(r) for r in shown if r]
    return {"sel_rows": sel_rows, "task_ids": task_ids, "local_only": local_only,
            "members_by_task": members_by_task, "local_rows": local_rows}


def myart_items(db_path):
    """Every catalog row that exists as a PixAI ARTWORK (artwork_id set by
    --sync-artworks), public AND private -- the My Art gallery's whole population,
    newest first. Pure catalog read: title/likes/comments/tags/nsfw all arrive via
    --sync-artworks, so nothing here touches the network. `likes` and `comments` come
    back as ints (the columns are TEXT and blank means zero).

    `views` joins them as of 2026-09-06 and is the reason My Art can now draw a real
    number on EVERY card rather than a summed twelve. It keeps its raw text alongside
    (`views_raw`) precisely because blank and zero are different answers here: '' is "this
    library has never been swept", 0 is "swept, and nobody has looked at it". A card must
    be able to say the first without drawing the second."""
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, artwork_id, title, prompt_preview, is_video, is_nsfw,"
            " is_sensitive, created_at, art_tags, is_published,"
            " CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) AS likes,"
            " CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER) AS comments,"
            " CAST(COALESCE(NULLIF(views,''),'0') AS INTEGER) AS views,"
            " views AS views_raw"
            " FROM catalog WHERE COALESCE(artwork_id,'') != '' AND media_id != ''"
            " ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


SNAPSHOT_KEEP_DAYS = 120
MYART_WINDOW_DAYS = 30


def _local_day(today=None):
    import datetime as _dt
    return (today or _dt.date.today()).strftime("%Y-%m-%d")


def record_artwork_snapshots(db_path, today=None):
    """Write today's reading of every published artwork into artwork_snapshots -- the
    history My Art's 30-day switch is computed from.

    One row per artwork per local day; a second call the same day REPLACES the row with the
    freshest numbers, so the sweep's fifteen-minute cadence costs nothing but a rewrite. The
    numbers are the catalog's own current ones (likes/comments from the meta sweep, views from
    the views sweep), so this reads nothing from PixAI. `views` stays NULL while the catalog's
    views are blank -- never swept is not zero. An animation's poster row and its mp4 row share
    one artwork_id; the larger reading of the two wins. Prunes past SNAPSHOT_KEEP_DAYS.

    Called after apply_artwork_meta and apply_artwork_views. Fails soft: history is a
    nicety and must never break a sweep. Returns the number of rows written."""
    import datetime as _dt
    day = _local_day(today)
    try:
        with catalog(db_path) as con:
            cur = con.execute(
                "INSERT OR REPLACE INTO artwork_snapshots (artwork_id, day, views, likes, comments)"
                " SELECT artwork_id, ?,"
                " MAX(CASE WHEN COALESCE(views,'') = '' THEN NULL"
                "          ELSE CAST(views AS INTEGER) END),"
                " MAX(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),"
                " MAX(CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER))"
                " FROM catalog WHERE COALESCE(artwork_id,'') != ''"
                " GROUP BY artwork_id", (day,))
            n = cur.rowcount or 0
            cutoff = ((today or _dt.date.today())
                      - _dt.timedelta(days=SNAPSHOT_KEEP_DAYS)).strftime("%Y-%m-%d")
            con.execute("DELETE FROM artwork_snapshots WHERE day < ?", (cutoff,))
            con.commit()
            return n
    except sqlite3.Error:
        return 0


def myart_window(db_path, today=None, days=MYART_WINDOW_DAYS):
    """The last-`days` views and likes of each published artwork, from artwork_snapshots.

    Returns (per_artwork, window):
      per_artwork = {artwork_id: {"views": int|None, "likes": int}} -- the gain since the
                    baseline snapshot. views is None when this artwork's views were never swept.
      window      = {"days": N, "since": "YYYY-MM-DD", "full": bool, "seen": bool (any history)}

    THE BASELINE, and what is honest about it: the newest snapshot taken on or before
    (today - days) when the history reaches that far back -- then `full` is true and the number
    really is a 30-day figure. Until it does, the baseline is the artwork's OLDEST snapshot, the
    number is "since that day", and `full` is false so the surface says "since <date>" instead
    of "30 days". `since` is the oldest snapshot day anywhere (today when there is none yet). A
    gain never goes below zero (a work PixAI removed likes from reads as no change, not as a
    negative). Pure catalog read."""
    import datetime as _dt
    t = today or _dt.date.today()
    today_s = _local_day(t)
    edge = (t - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with catalog(db_path) as con:
            snaps = con.execute(
                "SELECT artwork_id, day, views, likes FROM artwork_snapshots"
                " ORDER BY artwork_id, day").fetchall()
            cur_rows = con.execute(
                "SELECT artwork_id,"
                " MAX(CASE WHEN COALESCE(views,'') = '' THEN NULL ELSE CAST(views AS INTEGER) END) AS views,"
                " MAX(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)) AS likes"
                " FROM catalog WHERE COALESCE(artwork_id,'') != '' GROUP BY artwork_id").fetchall()
    except sqlite3.Error:
        return {}, {"days": days, "since": today_s, "full": False, "seen": False}
    by_art = {}
    for r in snaps:
        by_art.setdefault(r["artwork_id"], []).append(r)
    since = min((r["day"] for r in snaps), default=today_s)
    out = {}
    for c in cur_rows:
        hist = by_art.get(c["artwork_id"]) or []
        base = None
        for r in hist:                       # newest snapshot on or before the edge
            if r["day"] <= edge:
                base = r
        if base is None and hist:
            base = hist[0]                   # not 30 days of history yet: the oldest we have
        if base is None:
            out[c["artwork_id"]] = {"views": None if c["views"] is None else 0, "likes": 0}
            continue
        v = None
        if c["views"] is not None:
            # the baseline's own views may be NULL (swept later); the first swept reading is it
            bv = base["views"]
            if bv is None:
                bv = next((h["views"] for h in hist if h["views"] is not None), c["views"])
            v = max(0, int(c["views"]) - int(bv))
        out[c["artwork_id"]] = {"views": v, "likes": max(0, int(c["likes"] or 0) - int(base["likes"] or 0))}
    return out, {"days": days, "since": since, "full": since <= edge, "seen": bool(snaps)}


def myart_coverage(db_path):
    """WHY My Art is empty, when it is (#42) -- the two counts that tell "you have
    published nothing" apart from "--sync-artworks has never run on this library".

    `artworks` is the population myart_items() returns: catalog rows carrying an
    artwork_id. `media` is the whole catalog. artwork_id and is_published are written
    EXCLUSIVELY by --sync-artworks (moonglade/backup.py's run_sync_artworks), so a
    catalog holding media with zero artworks has simply never been synced -- a state the
    rows alone cannot distinguish from a genuinely unpublished library, which is exactly
    the silence the empty state used to answer with.

    Two counts and not one because the pair is what makes the claim honest: `media` alone
    would have the surface blame a sync on an empty library, and `artworks` alone cannot
    tell an unsynced library from an unpopulated one. Fails soft to zeros -- an empty
    state that cannot explain itself is only the state it already had."""
    with catalog(db_path) as con:
        try:
            r = con.execute(
                "SELECT COUNT(*) AS media,"
                " COALESCE(SUM(CASE WHEN COALESCE(artwork_id,'') != '' THEN 1 ELSE 0 END),0)"
                " AS artworks FROM catalog").fetchone()
            return {"media": int(r["media"] or 0), "artworks": int(r["artworks"] or 0)}
        except sqlite3.Error:
            return {"media": 0, "artworks": 0}


def artwork_media_ids(db_path, artwork_ids):
    """{artwork_id: media_id} for the ids the catalog knows, skipping the ones it does
    not. Cheap by construction: --sync-artworks writes artwork_id onto the SAME row as
    the media_id it belongs to, so this is a lookup rather than any kind of join -- and
    since 2026-09-03 it is genuinely indexed (idx_artwork_id), which this docstring
    claimed for a while before the index existed. It is what lets an entries listing show real thumbnails (/thumbs/<media_id>)
    for artworks the local library already holds -- an entry made from another device
    simply has no local media and gets no thumb, which is the honest answer.

    Chunked because SQLite caps the number of bound parameters in one statement."""
    ids = [str(a).strip() for a in (artwork_ids or []) if str(a or "").strip()]
    if not ids:
        return {}
    out = {}
    with catalog(db_path) as con:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            rows = con.execute(
                "SELECT artwork_id, media_id FROM catalog WHERE artwork_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()
            for r in rows:
                aid, mid = str(r["artwork_id"] or ""), str(r["media_id"] or "")
                if aid and mid:
                    out[aid] = mid
    return out


def artwork_row(db_path, media_id):
    """The publish-relevant catalog row behind one media_id (artwork_id / task_id /
    title / art_tags / is_published), or None. What every My Art card action resolves
    its target through before it will talk to PixAI at all."""
    with catalog(db_path) as con:
        r = con.execute(
            "SELECT media_id, artwork_id, task_id, title, art_tags, is_published"
            " FROM catalog WHERE media_id = ? LIMIT 1", (str(media_id),)).fetchone()
    return dict(r) if r else None


def publish_state(db_path, media_id, artwork_id=None, published=None,
                  art_tags=None, title=None):
    """Mirror a completed PixAI publish/unpublish/re-tag/delete back into the catalog
    so the grid reflects it without a full --sync-artworks. Every field is optional and
    None means LEAVE IT ALONE -- an artwork whose visibility changed must not have its
    title or tags rewritten as a side effect.

    `published` is a bool (stored as the catalog's '1'/'0' TEXT), `art_tags` an
    already-formatted comma string. Unpublishing on PixAI is expressed here as
    artwork_id='' plus published=False: the local row survives, it just no longer
    claims an artwork. Returns the number of columns written."""
    sets, params = [], []
    if artwork_id is not None:
        sets.append("artwork_id=?"); params.append(str(artwork_id))
    if published is not None:
        sets.append("is_published=?"); params.append("1" if published else "0")
    if art_tags is not None:
        sets.append("art_tags=?"); params.append(str(art_tags))
    if title is not None:
        sets.append("title=?"); params.append(str(title))
    if not sets:
        return 0
    params.append(str(media_id))
    with catalog(db_path) as con:
        con.execute("UPDATE catalog SET {} WHERE media_id=?".format(", ".join(sets)),
                    params)
        con.commit()
    return len(sets)


# The eleven columns extract_artwork_meta() fills. Named here, once, because
# apply_artwork_meta below writes a column list into SQL and a typo'd or drifting
# name would either raise or -- worse -- silently stop writing a field. Every one is
# owned by PixAI (it is what listArtworks says about the work), so overwriting them
# from a sweep is a refresh, never a loss: nothing locally-authored lives in here.
ARTWORK_META_FIELDS = ("artwork_id", "title", "is_published", "is_nsfw", "is_sensitive",
                       "liked_count", "comment_count", "aes_score", "art_tags",
                       "blurhash", "nsfw_scores")


def apply_artwork_meta(db_path, metas):
    """Merge extract_artwork_meta() dicts onto existing catalog rows, one narrow UPDATE
    each, keyed by the media_id already on the dict.

    The row-level twin of --sync-artworks' merge step, and the reason the periodic
    living-library sweep is cheap enough to run every fifteen minutes: run_sync_artworks
    reads the WHOLE catalog into memory, edits the matched rows and upserts every row
    back (`load_catalog` -> `save_catalog`, moonglade/backup.py). That is correct but it
    rewrites ~36k rows to touch a handful. This writes only the rows the sweep actually
    saw, only the eleven PixAI-owned columns above, and never invents a row: a media_id
    with no catalog row (an artwork whose image was never downloaded) simply matches
    nothing, exactly as the full sync's own "unmatched artworks are skipped" does.

    `metas` may key the SAME artwork under two media_ids -- an animation's poster id and
    its mp4's id (see run_sync_artworks' by_video_mid, issue #20) -- and that is fine:
    they are two real catalog rows and both want the metadata.

    Returns the number of rows actually changed."""
    metas = [m for m in (metas or []) if m and m.get("media_id")]
    if not metas:
        return 0
    sql = "UPDATE catalog SET {} WHERE media_id=?".format(
        ", ".join("{}=?".format(f) for f in ARTWORK_META_FIELDS))
    changed = 0
    with catalog(db_path) as con:
        for m in metas:
            cur = con.execute(sql, [str(m.get(f, "") or "") for f in ARTWORK_META_FIELDS]
                              + [str(m["media_id"])])
            changed += cur.rowcount or 0
        con.commit()
    if changed:
        record_artwork_snapshots(db_path)   # My Art's 30-day history (2026-11-19)
    return changed


# The four view columns (views, views_prev, views_at, views_prev_at) are folded by their own
# verb rather than by ARTWORK_META_FIELDS. Deliberately NOT part of the meta list: the meta
# fields ride the fifteen-minute living-library sweep, and reading a view count on PixAI ADDS
# one to it (PROBE_2026-09-06 measured it: a page that selects `views` moves every row it
# returns by +1). So views are read ONCE per deliberate --sync-artworks and never on the
# sweep's cadence -- a rule that only holds while the two writes stay two separate statements.
def apply_artwork_views(db_path, views_by_artwork_id, now_iso):
    """Fold a bulk views sweep onto the catalog rows it names, one narrow UPDATE each,
    keyed by artwork_id (the id the sweep returns; media_id is what the row is keyed by).

    The row-level twin of apply_artwork_meta for the four view columns, and it exists for
    the same reason: run_sync_artworks used to fold views inside a whole-catalog
    `load_catalog -> save_catalog` round trip, which reverted every write that landed
    while the walk was running. This touches only the rows the sweep actually saw and only
    the four columns above, in ONE transaction, so nothing else in the table can be
    reached.

    The per-row rule, and the whole of it: a reading only slides
    down into `views_prev` when a genuinely new one arrives to replace it, so `views_prev`
    always holds THE PREVIOUS SWEEP's number and the spike rule's window keeps its meaning.
    A row whose `views` is still blank has nothing to slide, and keeps its (blank) baseline.
    Rows the sweep missed are not in the map and are not written at all, so a partial sweep
    leaves the last reading anyone actually took.

    Returns the number of rows actually changed."""
    fresh_by_aid = {}
    for aid, fresh in (views_by_artwork_id or {}).items():
        aid = str(aid or "")
        if aid and fresh is not None:
            fresh_by_aid[aid] = fresh
    if not fresh_by_aid:
        return 0
    ids = list(fresh_by_aid)
    changed = 0
    with catalog(db_path) as con:
        # Chunked so a library-sized sweep cannot walk into SQLite's bound-parameter
        # limit; idx_artwork_id makes each chunk an index lookup, never a table scan.
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            rows = con.execute(
                "SELECT media_id, artwork_id, views, views_at, views_prev, views_prev_at "
                "FROM catalog WHERE artwork_id IN ({})".format(
                    ", ".join("?" for _ in chunk)), chunk).fetchall()
            for r in rows:
                fresh = fresh_by_aid.get(str(r["artwork_id"] or ""))
                if fresh is None:
                    continue
                cur = str(r["views"] or "")
                prev = str(r["views_prev"] or "")
                prev_at = str(r["views_prev_at"] or "")
                if cur != "":
                    prev = cur
                    prev_at = str(r["views_at"] or "")
                upd = con.execute(
                    "UPDATE catalog SET views=?, views_prev=?, views_at=?,"
                    " views_prev_at=? WHERE media_id=?",
                    (str(int(fresh)), prev, now_iso, prev_at, str(r["media_id"])))
                changed += upd.rowcount or 0
        con.commit()
    if changed:
        record_artwork_snapshots(db_path)   # My Art's 30-day history (2026-11-19)
    return changed


def lineage(db_path, media_id):
    """The family tree of one image, as rows:
      * siblings -- the other outputs of the SAME generation task (share task_id).
      * parent   -- the SOURCE image this one was derived from (source_media_id),
                    carrying `kind`, the derivation (edit/upscale/video).
      * children -- every image derived FROM this one, each with its own `kind`.
    Returns {row, siblings, parent, children}, or None for a media_id the catalog does
    not know -- "unknown image" is the caller's refusal to make, not this verb's. Any
    dimension can be empty: an original txt2img with a batch of 1 and no derivatives
    has an empty tree. Pure catalog read, no network."""
    mid = str(media_id or "").strip()
    cols = "media_id, is_video, title, prompt_preview"
    with catalog(db_path) as con:
        me = con.execute(
            "SELECT media_id, task_id, source_media_id, derive_kind FROM catalog"
            " WHERE media_id = ? LIMIT 1", (mid,)).fetchone()
        if not me:
            return None
        siblings = []
        if me["task_id"]:
            siblings = [dict(r) for r in con.execute(
                "SELECT %s FROM catalog WHERE task_id = ? AND media_id != ?"
                " ORDER BY media_id" % cols, (me["task_id"], mid)).fetchall()]
        parent = None
        if me["source_media_id"]:
            pr = con.execute("SELECT %s FROM catalog WHERE media_id = ? LIMIT 1" % cols,
                             (me["source_media_id"],)).fetchone()
            if pr:
                parent = dict(pr, kind=me["derive_kind"] or "derived")
        children = [dict(r, kind=(r["derive_kind"] or "derived"))
                    for r in con.execute(
                        "SELECT %s, derive_kind FROM catalog WHERE source_media_id = ?"
                        " ORDER BY created_at" % cols, (mid,)).fetchall()]
    return {"row": dict(me), "siblings": siblings, "parent": parent,
            "children": children}


def sibling_media(db_path, task_ids):
    """Every output of each requested task, in ONE query, ordered by (task_id,
    media_id) -- the page-batched form of lineage()'s siblings, for the card
    placard's Sibling Strip. Includes each task's own members entire (the caller
    lights "self" by media_id).

    An EMPTY task_id is never queried: every import shares '', and one giant
    pseudo-batch of unrelated images is not a sibling strip."""
    ids = [str(t) for t in (task_ids or []) if str(t).strip()]
    if not ids:
        return []
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT task_id, media_id, is_video, batch_index FROM catalog"
            " WHERE task_id IN (%s) AND task_id != ''"
            " ORDER BY task_id, media_id" % ",".join("?" * len(ids)), ids).fetchall()
        return [dict(r) for r in rows]


def recent_train_task_page(db_path, limit=18, before=None, q=""):
    """Generations grouped by TASK, newest task first, for the Train dataset pickers (the
    phone's tiles are tasks; desktop's "Grouped" view) -- each entry is one generation and its
    real image count, never a fixed batch size (real batches are 1-4). Videos, task-less
    imports and rows with no file are excluded: a training set is made of images that exist on
    disk.

    PAGED BY TASK (issue #56: the phone stopped at the 18 newest). A task is ordered by its
    newest image; `before` is the previous page's `next_before` cursor -- that newest
    created_at and the task id, the tie-breaker -- and the page holds the next `limit` tasks
    strictly older than it. Every image of a task on the page comes with it, whatever its own
    timestamp, so a task is never split across two pages.

    `q` is the library's own search (_build_where: prompt words, field operators, a pasted
    id); a task is on the page when any of its images matches, and then all of its images come.

    Returns (tasks, next_before): tasks = [{task_id, media_ids, count, newest}], newest image
    first within a task; next_before is None when there is nothing older."""
    limit = max(1, int(limit))
    where = ("task_id != '' AND COALESCE(is_video,'') != '1' AND filename != ''")
    head_where, head_params = where, []
    if (q or "").strip():
        qw, qp = _build_where(q.strip(), "", "", "", media_type="image")
        head_where, head_params = where + " AND " + qw, qp
    params = []
    having = ""
    if before and before.get("at") is not None:
        having = " HAVING (newest < ? OR (newest = ? AND task_id < ?))"
        params = [before["at"], before["at"], str(before.get("task") or "")]
    with catalog(db_path) as con:
        heads = con.execute(
            "SELECT task_id, MAX(created_at) AS newest FROM catalog WHERE " + head_where +
            " GROUP BY task_id" + having +
            " ORDER BY newest DESC, task_id DESC LIMIT ?",
            head_params + params + [limit + 1]).fetchall()
        more = len(heads) > limit
        heads = heads[:limit]
        ids = [h["task_id"] for h in heads]
        rows = con.execute(
            "SELECT media_id, task_id FROM catalog WHERE " + where +
            " AND task_id IN (%s) ORDER BY created_at DESC, media_id" % ",".join("?" * len(ids)),
            ids).fetchall() if ids else []
    groups = {tid: [] for tid in ids}
    for r in rows:
        groups[r["task_id"]].append(r["media_id"])
    tasks = [{"task_id": h["task_id"], "media_ids": groups[h["task_id"]],
              "count": len(groups[h["task_id"]]), "newest": h["newest"]} for h in heads]
    nxt = ({"at": heads[-1]["newest"], "task": heads[-1]["task_id"]} if more and heads else None)
    return tasks, nxt


class TrainGuard:
    """The two spend guards the training routes keep ON DISK (train_guard.json among the
    library's records, _moonglade/records/), so neither a restart nor a second tab can clear
    them (spend review 2026-09-28, findings 1 and 2; BUILD-w3-train.md section 7).

      * BASIC START: a Basic run has no task id until PixAI creates it, so the per-task lock
        cannot cover it. The guard is keyed on what the run IS (base, dataset, name), checked
        and ARMED before the mutation under the one Basic lock, and resolved after it: a run
        PixAI started keeps it armed for DUPLICATE_WINDOW (a second identical Start inside a
        minute is a double click, not an intent); a definite refusal disarms it; an unclear
        failure -- a timeout, a dropped connection, a 5xx, after which PixAI may well have
        created and charged the run -- keeps it as "ambiguous" for AMBIGUOUS_WINDOW, and the
        panel says the run may have started.
      * RETRY: PixAI leaves a failed run as it is after a retry, so it would accept a second
        retry and charge a second run. The failed id is armed before the POST; a success
        records the new run's id for good; an unclear failure is "ambiguous" for
        AMBIGUOUS_RETRY_WINDOW; only a definite refusal disarms it.
      * ADVANCED DESCRIBE / START (spend review of waves 2+3, finding F1): the per-task lock
        covers two requests at once, and the task's status covers a POST PixAI answered --
        but after an UNCLEAR failure the status may not have moved yet, so a second confirm
        would send a second paid POST. Each is armed (keyed "<what>:<task id>", with the
        status it was confirmed from) before the POST; a success or a definite refusal
        clears it; an unclear failure keeps it "ambiguous" for AMBIGUOUS_WINDOW. While it
        stands, the next confirm is refused unless the task's status has moved on since.

    Every read-modify-write holds one lock, and the file is rewritten whole each time."""

    DUPLICATE_WINDOW = 60.0
    AMBIGUOUS_WINDOW = 15 * 60.0
    AMBIGUOUS_RETRY_WINDOW = 24 * 3600.0

    def __init__(self, path):
        # `path` may be a callable, asked at each use (the server's own guard): the library's
        # records can be brought across, or moved back by a round trip to 3.19, while the
        # server runs, and the guard must never keep writing where nobody reads.
        self._where = path if callable(path) else (lambda p=Path(path): p)
        self._lock = threading.Lock()

    @property
    def path(self):
        return Path(self._where())

    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("basic", {})
        d.setdefault("retried", {})
        d.setdefault("paid", {})
        return d

    def _save(self, d):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(self.path))

    @staticmethod
    def basic_key(base_model_id, media_ids, dataset_task_id, title):
        import hashlib
        parts = [str(base_model_id or ""), "reuse:" + str(dataset_task_id) if dataset_task_id
                 else ",".join(sorted(str(m) for m in (media_ids or []))),
                 " ".join(str(title or "").split()).lower()]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def basic_blocked(self, key, now=None):
        """None when a Basic start with this key may go ahead, else the refusal's words."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            e = d["basic"].get(key)
            if not isinstance(e, dict):
                return None
            age = now - float(e.get("at") or 0)
            # "armed" seen here is a start that never resolved -- the process stopped between
            # the arm and the answer (the one Basic lock means no live request can be holding
            # it) -- so it is as unclear as an ambiguous one.
            if e.get("state") in ("ambiguous", "armed") and age < self.AMBIGUOUS_WINDOW:
                return ("Your last start of this run may have gone through: PixAI didn't "
                        "answer clearly. Check Runs before starting it again (this guard "
                        "clears by itself after 15 minutes). Nothing was sent.")
            if e.get("state") == "started" and age < self.DUPLICATE_WINDOW:
                return ("You just started this run. Nothing was sent again; it is in Runs.")
            return None

    def basic_arm(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["basic"] = {k: v for k, v in d["basic"].items()
                          if now - float((v or {}).get("at") or 0) < self.AMBIGUOUS_WINDOW}
            d["basic"][key] = {"at": now, "state": "armed"}
            self._save(d)

    def basic_resolve(self, key, outcome, now=None):
        """outcome: "started" (keep for the duplicate window), "refused" (disarm),
        "ambiguous" (keep, say it may have started)."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            if outcome == "refused":
                d["basic"].pop(key, None)
            else:
                d["basic"][key] = {"at": now, "state": outcome}
            self._save(d)

    def retry_state(self, task_id, now=None):
        """None (never retried here, or an old unclear attempt), else {state, new_id}."""
        now = time.time() if now is None else now
        with self._lock:
            e = self._load()["retried"].get(str(task_id))
        if not isinstance(e, dict):
            return None
        st = e.get("state") or "armed"
        if st == "armed":            # never resolved: the process stopped mid-retry
            st = "ambiguous"
        if st == "ambiguous" and now - float(e.get("at") or 0) >= self.AMBIGUOUS_RETRY_WINDOW:
            return None
        return {"state": st, "new_id": e.get("new_id") or ""}

    def retry_arm(self, task_id, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["retried"][str(task_id)] = {"at": now, "state": "armed", "new_id": ""}
            self._save(d)

    def retry_resolve(self, task_id, outcome, new_id="", now=None):
        """outcome: "done" (keep for good, with the new run's id), "refused" (disarm),
        "ambiguous"."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            if outcome == "refused":
                d["retried"].pop(str(task_id), None)
            else:
                d["retried"][str(task_id)] = {"at": now, "state": outcome,
                                              "new_id": str(new_id or "")}
            self._save(d)

    @staticmethod
    def paid_key(what, task_id):
        return "%s:%s" % (what, task_id)

    def paid_blocked(self, what, task_id, status, now=None):
        """True when an earlier `what` ("caption" | "submit") confirm on this task may have
        gone through and the task's status (`status`, read just now) has not moved on from
        the one it was confirmed from. A status that moved clears the entry: PixAI took it,
        and the route's own status check says what happens next. "armed" seen here is a
        confirm that never resolved (the process stopped mid-POST): as unclear as
        "ambiguous"."""
        now = time.time() if now is None else now
        key = self.paid_key(what, task_id)
        with self._lock:
            d = self._load()
            e = d["paid"].get(key)
            if not isinstance(e, dict):
                return False
            fresh = now - float(e.get("at") or 0) < self.AMBIGUOUS_WINDOW
            if fresh and str(e.get("status") or "") == str(status or ""):
                return True
            d["paid"].pop(key, None)
            self._save(d)
            return False

    def paid_arm(self, what, task_id, status, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["paid"] = {k: v for k, v in d["paid"].items()
                         if now - float((v or {}).get("at") or 0) < self.AMBIGUOUS_WINDOW}
            d["paid"][self.paid_key(what, task_id)] = {"at": now, "state": "armed",
                                                       "status": str(status or "")}
            self._save(d)

    def paid_resolve(self, what, task_id, outcome, now=None):
        """outcome: "done" or "refused" (clear: PixAI answered, and its status now says what
        happened), "ambiguous" (keep for AMBIGUOUS_WINDOW)."""
        now = time.time() if now is None else now
        key = self.paid_key(what, task_id)
        with self._lock:
            d = self._load()
            if outcome == "ambiguous":
                e = d["paid"].get(key) or {}
                d["paid"][key] = {"at": now, "state": "ambiguous",
                                  "status": str(e.get("status") or "")}
            else:
                d["paid"].pop(key, None)
            self._save(d)

    def retried(self):
        """{failed_id: {state, new_id}} for the Runs list (a guarded id shows no Retry)."""
        with self._lock:
            ids = list(self._load()["retried"])
        out = {}
        for tid in ids:
            st = self.retry_state(tid)
            if st:
                out[tid] = st
        return out


def history_page(db_path, since_utc, until_utc, media="", source=""):
    """One window of the history feed: every catalog row created in
    [since_utc, until_utc), newest first, plus the cursor for the page below it.

    ONE indexed range query (`created_at >= ? AND created_at < ?`, no functions on the
    column) and one seek. The window is passed in already resolved to UTC strings
    because the DAY boundaries are the caller's business -- they depend on the viewer's
    timezone, and computing them at the route is what makes them deterministic and
    testable. `media`/`source` are _build_where's own idiom.

    Returns {rows, older_created_at}: `older_created_at` is the created_at of the
    NEWEST row older than this window (None if there is nothing older), so the caller
    can open the next page on a day that has runs instead of a run of empty days."""
    where, params = _build_where("", "", "", "", media_type=media, source=source)
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, task_id, is_video, created_at, width, height, model_id, "
            "COALESCE(NULLIF(model_name,''), NULLIF(video_model,''), model_id, '') AS model, "
            "SUBSTR(COALESCE(NULLIF(prompt_full,''), prompt_preview, ''), 1, 300) AS prompt, "
            "video_duration, paid_credit, source "
            "FROM catalog WHERE {} AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at DESC, media_id DESC".format(where),
            params + [since_utc, until_utc]).fetchall()
        older = con.execute(
            "SELECT created_at FROM catalog WHERE {} AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 1".format(where),
            params + [since_utc]).fetchone()
    return {"rows": [dict(r) for r in rows],
            "older_created_at": older[0] if older else None}


def history_created_ats(db_path, since_utc, until_utc, media="", source=""):
    """Just the created_at values in a window, for counting how many LOCAL days of
    the next page actually have runs ("Load N older days"). Values, not days: which
    local day a UTC timestamp falls in depends on the viewer's timezone, so the
    bucketing is the caller's to do."""
    where, params = _build_where("", "", "", "", media_type=media, source=source)
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT created_at FROM catalog WHERE {} AND created_at >= ? "
            "AND created_at < ?".format(where),
            params + [since_utc, until_utc]).fetchall()
    return [r[0] for r in rows]


def distinct_task_count(db_path):
    """How many distinct generation TASKS the local catalog holds. This is the apples-to-apples
    counterpart to the server's `me.tasks.totalCount` (also tasks, not images) -> backup coverage
    = local/server. Counts distinct non-empty task_id. Fails soft to 0."""
    with catalog(db_path) as con:
        try:
            return int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != ''"
            ).fetchone()[0] or 0)
        except sqlite3.Error:
            return 0


def backup_coverage(db_path, out_dir, server_tasks):
    """The header's Backed up pill: {pct, note, local, server, no_picture, missing, deleted}.

    WHAT IT USED TO COUNT, and why it never reached 100% (owner, 2026-11-18: "I have asked this
    question myself and you once told me to just run sync again. I gave up caring."): every
    distinct task in the catalog over PixAI's `me.tasks.totalCount`. Two things were wrong at
    once. The bottom counted every task PixAI lists, failed and cancelled ones too -- and
    those never made a picture, so no sync can ever fetch them. And the top counted tasks
    already deleted on PixAI (deleted_remote), which PixAI no longer counts, so they hid part
    of that gap. Now the top is the tasks here that PixAI still has, the bottom leaves out the
    ones with no picture (counted by the last full walk of the feed -- the deleted-on-PixAI
    check every Sync ends with -- and kept in reconcile_stamp.json), and the note says in plain
    words what is left and what fixes it. Rounded DOWN, so 100% means nothing is missing.
    `server_tasks` None (PixAI unreachable) -> pct None, as before."""
    import math
    with catalog(db_path) as con:
        try:
            local = int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != '' "
                "AND COALESCE(deleted_remote,'') != '1'").fetchone()[0] or 0)
            deleted = int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != '' "
                "AND COALESCE(deleted_remote,'') = '1'").fetchone()[0] or 0)
        except sqlite3.Error:
            local = deleted = 0
    from moonglade import backup as _core_cov
    stamp = _core_cov.read_reconcile_stamp(out_dir)
    walked = "no_picture" in stamp
    try:
        no_picture = max(0, int(stamp.get("no_picture") or 0))
        missing = max(0, int(stamp.get("missing") or 0))
    except (TypeError, ValueError):
        no_picture, missing, walked = 0, 0, False
    out = {"pct": None, "note": "", "local": local, "server": server_tasks,
           "no_picture": no_picture, "missing": missing, "deleted": deleted}
    if not server_tasks:
        return out
    bottom = max(1, int(server_tasks) - no_picture)
    out["pct"] = min(100.0, math.floor(local / bottom * 1000) / 10)
    fmt = "{:,}".format
    words = ["{} of the {} picture-making generations PixAI has for you are here.".format(
        fmt(min(local, bottom)), fmt(bottom))]
    if walked and no_picture:
        words.append("{} more failed or were cancelled on PixAI and never made a picture, "
                     "so there is nothing to back up and nothing can fix that; they are not "
                     "counted.".format(fmt(no_picture)))
    short = max(0, bottom - local)
    if short:
        words.append("{} {} not here yet: Sync now fetches {}.".format(
            fmt(short), "is" if short == 1 else "are", "it" if short == 1 else "them"))
    if deleted:
        words.append("{} you deleted on PixAI {} kept here and not counted.".format(
            fmt(deleted), "is" if deleted == 1 else "are"))
    if not walked:
        words.append("Failed and cancelled generations are counted until the next Sync "
                     "checks your whole PixAI history.")
    out["note"] = " ".join(words)
    return out


def rows_for_media_ids(db_path, ids):
    """Fetch catalog rows for a specific list of media_ids, preserving the given order.
    Used by the contact-sheet print view. Chunked to stay under SQLite's variable cap."""
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if not ids:
        return []
    with catalog(db_path) as con:
        found = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                "SELECT * FROM catalog WHERE media_id IN ({})".format(ph), chunk
            ).fetchall():
                found[str(r["media_id"])] = dict(r)
        return [found[i] for i in ids if i in found]


def paid_credit_for_tasks(db_path, task_ids):
    """{task_id: paid_credit text} from the catalog for these task ids: PixAI's own charge
    for the task, task-level on every row it made ('' when a row exists with no charge
    reported). A task with no row is absent. Chunked like rows_for_media_ids."""
    ids = sorted({str(t).strip() for t in (task_ids or []) if str(t or "").strip()})
    out = {}
    if not ids or not Path(db_path).exists():
        return out
    with catalog(db_path) as con:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                "SELECT task_id, paid_credit FROM catalog WHERE task_id IN ({})".format(ph), chunk
            ).fetchall():
                tid, pc = str(r["task_id"]), str(r["paid_credit"] or "").strip()
                if pc or tid not in out:          # a row that reports a charge wins
                    out[tid] = pc
    return out


def loom_cost(text):
    """A charge read off the catalog: an int, or None when nothing usable was reported. A
    blank, junk or non-finite value is unknown, never 0 -- 0 means a settled free render."""
    s = str(text if text is not None else "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    try:
        return int(v)
    except (OverflowError, ValueError):
        return None


# ---- THE LOOM'S SEND RECORD (2026-11-18): the one source of a board's "spent" figure --------
# One append-only file per account (_moonglade/loom/_sends/<account>.jsonl). A line is written
# when a render is SENT from a board -- the moment the journal records its task id -- never
# when a picture lands on a shot. So a clip linked, imported, remixed or seeded onto a card is
# not a send and never counts; a re-render is its own send and adds its own charge.
#
# Line kinds, folded by loom_sends_fold:
#   a send      {board, card, task_id|null, submit_id|null, kind, cost|null, at}
#               kind "render" (sent from the Loom) or "backfill" (found on a board saved
#               before this record existed); cost 0 when a free card was attached, else the
#               catalog's paid_credit once known, null until then (shown as unknown)
#   a cost      {task_id, cost}         the charge, read off the catalog once it is there
#   a void      {submit_id, void: true} an unclear send the owner released: nothing was made
#   a marker    {board, backfilled: at} that board's one backfill has run

def loom_send_key(rec):
    tid = str(rec.get("task_id") or "")
    return ("t:" + tid) if tid else ("s:" + str(rec.get("submit_id") or ""))


def loom_sends_fold(lines):
    """{"sends": {key: send}, "backfilled": {board ids}} from the record's lines. The first
    line for a task owns its board and card, so a task is one board's send, once."""
    sends, by_submit, backfilled = {}, {}, set()
    for rec in lines:
        if not isinstance(rec, dict):
            continue
        if rec.get("backfilled") and rec.get("board"):
            backfilled.add(str(rec["board"]))
        elif rec.get("void") and rec.get("submit_id"):
            k = by_submit.get(str(rec["submit_id"]))
            if k and k in sends and not sends[k].get("task_id"):
                sends[k]["void"] = True
        elif rec.get("board") and rec.get("kind"):
            k = loom_send_key(rec)
            if k in ("t:", "s:") or k in sends:
                continue
            sends[k] = dict(rec)
            if rec.get("submit_id"):
                by_submit[str(rec["submit_id"])] = k
        elif rec.get("task_id") and "cost" in rec:
            k = "t:" + str(rec["task_id"])
            if k in sends and sends[k].get("cost") is None and isinstance(rec["cost"], int):
                sends[k]["cost"] = rec["cost"]
    return {"sends": sends, "backfilled": backfilled}


def loom_backfill_sends(board, board_id, known_task_ids, journal_entries, at=0.0):
    """The one-time backfill of a board saved before the send record existed. A send is a
    real task id the board or the journal kept for a render of this board: a stored take
    with source "render" that is not imported, a superseded render's task, a render still
    pending, or a journal entry for this board that reached PixAI. A take with no task id
    is NOT a send -- a seeded, linked, imported or remixed clip -- and nothing is ever
    priced from a quote: cost stays null here and is read off the catalog afterwards.
    `known_task_ids` (every task already recorded, on any board) keeps it idempotent and a
    task one board's alone. Pure: returns the new send lines, writes nothing."""
    seen = {str(t) for t in (known_task_ids or ())}
    out = []

    def add(tid, card):
        tid = str(tid or "").strip()
        if not tid or tid in seen:
            return
        seen.add(tid)
        out.append({"board": board_id, "card": str(card or ""), "task_id": tid,
                    "submit_id": None, "kind": "backfill", "cost": None, "at": at})

    for act in ((board or {}).get("acts") or []):
        for c in ((act or {}).get("cards") or []):
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            for t in (c.get("takes") or []):
                if isinstance(t, dict) and t.get("source") == "render" and not t.get("imported"):
                    add(t.get("taskId"), cid)
            for tid in (c.get("supersededTasks") or []):
                add(tid, cid)
            add(c.get("pendingTaskId"), cid)
    for e in (journal_entries or ()):
        if isinstance(e, dict) and str(e.get("board") or "") == board_id \
                and e.get("task_id") and e.get("state") == "submitted":
            add(e.get("task_id"), e.get("card"))
    return out


def integrity_rows(db_path):
    """Every catalog row, narrowed to what the integrity pass (moonglade/integrity.py)
    needs: the file it claims, whether it is a video, and the two archive-only flags.
    Plain dicts, catalog order."""
    with catalog(db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT media_id, filename, is_video, deleted_remote, cloud_deleted_at "
            "FROM catalog WHERE COALESCE(media_id, '') != '' ORDER BY rowid").fetchall()]


def list_media_ids(db_path, q="", model="", date_from="", date_to="", sort="newest",
                   batch="", rating_min=0, published_only=False, art_tag="", lora="",
                   media_type="", source="", collection="", series=""):
    """Return ordered list of media_ids matching the filter (no row data).

    `series` narrows the walk to one dial-in series' members, exactly as query_catalog's
    does (_narrow_to_series), so the picture page opened from an opened stack counts and
    steps inside that stack. Empty = no narrowing, the walk is what it always was."""
    q, collection = _expand_smart(db_path, q, collection)
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    where, params = _narrow_to_series(db_path, series, where, params)
    order, order_params = _order_sql(sort, collection)
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id FROM catalog WHERE {} ORDER BY {}".format(where, order),
            list(params) + order_params
        ).fetchall()
        return [r[0] for r in rows]


def list_group_rows(db_path, q="", model="", date_from="", date_to="", sort="newest",
                    batch="", rating_min=0, published_only=False, art_tag="", lora="",
                    media_type="", source="", collection=""):
    """The minimal per-row columns needed to fold a filtered result set into dial-in
    series UNITS (#34 direction B's grouped listing): (media_id, task_id, created_at,
    is_video) for EVERY matching row in the active sort order, WITHOUT a page LIMIT.

    Same WHERE + ORDER as query_catalog / list_media_ids -- the grouped listing has
    to see the whole filtered set, because a series spans many rows across pages (up
    to 801 images) and a client-side collapse of one page would only ever group the
    fraction that landed on it. It needs just these four columns, though: task_id to
    map a row to its series, created_at + is_video to pick each unit's cover (newest
    surviving image), and media_id to fetch that one cover's full row afterwards.
    Bounded work -- ids-only over the catalog (~36k rows max); measured in
    dev/tests/test_series_grouping.py. No `series=` param here on purpose: grouping is
    the alternative to a single-series view, never combined with it."""
    q, collection = _expand_smart(db_path, q, collection)
    where, params = _build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    order, order_params = _order_sql(sort, collection)
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, task_id, created_at, is_video FROM catalog "
            "WHERE {} ORDER BY {}".format(where, order), list(params) + order_params
        ).fetchall()
        return [dict(r) for r in rows]


def unique_models(db_path):
    """Return sorted list of distinct non-empty model names in the catalog."""
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT DISTINCT model_name FROM catalog WHERE model_name != '' ORDER BY model_name"
        ).fetchall()
        return [r[0] for r in rows]


def backfill_batches(out_dir, db_path):
    """Scan batches/ on disk and populate the batch column for already-organized images.

    Safe to re-run — only updates rows where batch is currently empty.
    Returns number of rows updated.

    Rides the shared scan (`include=("batches",)` = walk only that subtree, no
    exclusions inside it) rather than its own iterdir+rglob pair, and takes the
    media_id from the scan instead of re-typing `stem.split("_")[-1]` inline --
    that inline copy was one of the two INVARIANT-1 re-implementations.
    """
    updates = {}  # media_id -> batch_name
    for e in _scan.scan_library(out_dir, kinds=("image",), include=("batches",), exclude=()):
        if len(e.rel.parts) < 3:
            continue          # a loose file sitting directly in batches/ has no batch dir
        updates[e.media_id] = e.rel.parts[1]
    if not updates:
        return 0
    with catalog(db_path) as con:
        updated = 0
        for mid, batch_name in updates.items():
            cur = con.execute(
                "UPDATE catalog SET batch=? WHERE media_id=? AND (batch='' OR batch IS NULL)",
                (batch_name, mid),
            )
            updated += cur.rowcount
        con.commit()
        return updated


def catalog_years(db_path):
    """Descending list of years (ints) present in catalog created_at, for the
    date-filter dropdowns. Empty if the catalog has no dated rows."""
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT DISTINCT SUBSTR(created_at,1,4) AS y FROM catalog "
            "WHERE created_at != '' AND y != '' ORDER BY y DESC"
        ).fetchall()
        return [int(r[0]) for r in rows if str(r[0]).isdigit()]


def find_image_file(out_dir, media_id, filename):
    """Locate an image file: try catalog filename first, then media-id fallback.

    Excludes out_dir/gallery/ so thumbnails are never returned as full-res images.
    """
    gallery_dir = out_dir / "gallery"
    deleted_dir = out_dir / _scan.DELETED_DIRNAME
    records_dir = out_dir / _scan.RECORDS_DIRNAME
    if filename:
        for candidate in out_dir.rglob(filename):
            # The fallback below (find_files_for_media_id) already skips zero-byte
            # files -- this fast path found candidate rglob before that fallback ever
            # runs, so it needs the same size check or a catalog row still pointing at
            # its original filename gets a truncated/interrupted download served back
            # as if it were the real image (audit 2026-07-21, invariant 3/6).
            try:
                if (candidate.is_file() and candidate.stat().st_size > 0
                        and not _scan._is_under(candidate, gallery_dir)
                        and not _scan._is_under(candidate, deleted_dir)
                        and not _scan._is_under(candidate, records_dir)):
                    return candidate
            except OSError:
                continue
    matches = _scan.find_files_for_media_id(out_dir, media_id)
    return matches[0] if matches else None


# DELETED_DIRNAME (the recoverable-purge folder) is defined in the LIBRARY SCAN
# section above, beside the other directory names every walker shares.

# How many tasks /api/delete-preview describes image-by-image before it stops and just
# counts the rest. A DISPLAY bound only -- the totals it returns are always exact for
# the whole selection. 24 tasks is up to ~100 thumbnails, which is already more than
# anyone reads in a confirm dialog; selecting a thousand images would otherwise build a
# megabyte of JSON and a thumbnail wall the modal cannot scroll through.
DELETE_PREVIEW_TASK_CAP = 24

# How many selected tasks /api/delete-preview will READ BACK FROM PIXAI before it stops
# checking and says the counts are an estimate (owner, 2026-09-07: "one live read per
# selected task, capped at 40; above that the preview says it is an estimate, and the
# delete still keeps back what the live read finds").
#
# Unlike DELETE_PREVIEW_TASK_CAP above -- a DISPLAY bound -- this one changes what the
# numbers MEAN. At or below it the preview is exact against the cloud: an image the owner
# deleted on PixAI's own website is reported as already gone rather than counted among the
# files this delete will take. Above it nothing is read and the modal says so, which is
# honest and costs nothing; the delete itself still reads every task before it acts
# (_rows_the_bulk_purge_must_keep), so nothing is at risk either way.
#
# 40 is the owner's number. Note it is ABOVE the display cap, deliberately: tasks 25-40 are
# never drawn as strips but their images are still counted, and the totals are what he reads
# to decide.
DELETE_PREVIEW_LIVE_CAP = 40
# The same pool width build_thumbnails() has used for its own fan-out (workers=8). 40 reads
# eight at a time is five rounds, not forty round trips in a row.
DELETE_PREVIEW_LIVE_WORKERS = 8
# A wall-clock ceiling on the whole fan-out, and a real one (2026-09-07): _preview_live_gone
# spends it three ways -- it starts no read after the deadline, gives each read a socket
# timeout no longer than the budget has LEFT, and stops collecting at the deadline without
# waiting for the pool to drain. The first of those was the whole enforcement until this
# date, which bounded only when a read STARTED: one connection that stalled after the
# handshake could run out the transport's own 60s and then retry for another, so the route
# could block for ~2 minutes against the 12 it promised. Whatever has not answered by the
# deadline is reported unverified, exactly like a read that failed.
#
# api.js's deletePreview carries a fetch timeout a little ABOVE this (DELETE_PREVIEW_MS),
# so the dialog always gets an answer -- the server's, in the ordinary case, and the
# client's plain "PixAI did not answer in time" only if the server itself goes silent.
DELETE_PREVIEW_LIVE_BUDGET_S = 12.0


def _trash_meta_path(out_dir, media_id):
    """Sidecar path for a quarantined item's snapshotted catalog row (see
    _snapshot_before_purge). Lives beside the quarantined file itself, keyed by
    media_id rather than filename so it's a one-line lookup from either direction."""
    return Path(out_dir) / _scan.DELETED_DIRNAME / "{}.json".format(media_id)


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
            qdir = out_dir / _scan.DELETED_DIRNAME
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


def compute_dhash(img_path, hash_size=_dupes.DHASH_SIZE):
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


# A picture the thumbnailer cannot draw (3.21.2, L3). An SVG is a vector document, never
# opened by Pillow and never rasterised here (3.21.1 keeps it a plain file, served only as an
# image or a download), so it has no thumbnail by design: a missing one is not a fault, and
# nothing may offer to "rebuild" it. The same holds for any picture type this Pillow cannot open.
_THUMBLESS_EXTS = frozenset({".svg"})


def thumbnail_renders(path):
    """True when make_thumbnail can draw a thumbnail for the picture at `path` (judged by its
    extension, so a missing file is judged the same). False for an SVG, and for a picture type
    this Pillow does not open. Without Pillow at all nothing renders, but the raster types
    still count as thumbnail-bearing, so a library check keeps reporting their thumbnails."""
    global _PIL_EXTS
    ext = Path(str(path or "")).suffix.lower()
    if ext in _THUMBLESS_EXTS:
        return False
    if Image is None or not ext:
        return True
    if _PIL_EXTS is None:
        try:
            _PIL_EXTS = frozenset(k.lower() for k in Image.registered_extensions())
        except Exception:                                    # noqa: BLE001 -- fail to today's
            return True
    return ext in _PIL_EXTS


_PIL_EXTS = None                                  # Pillow's openable extensions, read once


# See-through pictures (RGBA/LA/P-with-transparency) used to lose their alpha to a bare
# convert("RGB") and showed a black box with junk colours. They are flattened onto a dim
# checkerboard instead (owner's pick, 3.22 walk): 12px squares at the thumbnail's FINAL
# size, top-left square CHECKER_A. Opaque pictures keep the old convert path untouched.
CHECKER_A = (46, 49, 72)
CHECKER_B = (32, 35, 54)
CHECKER_SQUARE = 12
# One-time rebuild marker (see build_thumbnails): its presence means every see-through
# thumbnail already on disk was cut by the checkerboard-aware code.
CHECKER_MARKER = ".checkerboard-v1"


def _see_through_rgba(im):
    """The picture as RGBA when it has any genuinely see-through pixel, else None.
    A fully opaque RGBA (or a palette image whose transparent index is unused) is NOT
    see-through, so it keeps today's exact convert("RGB") path."""
    if im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 255:
            return rgba
    return None


def _checkerboard(size):
    from PIL import ImageDraw
    w, h = size
    board = Image.new("RGB", (w, h), CHECKER_B)
    draw = ImageDraw.Draw(board)
    n = CHECKER_SQUARE
    for ty in range(0, h, n):
        for tx in range(0, w, n):
            if ((tx // n) + (ty // n)) % 2 == 0:
                draw.rectangle([tx, ty, min(tx + n, w) - 1, min(ty + n, h) - 1], fill=CHECKER_A)
    return board


def thumb_rgb(im, size, resample=None):
    """`im` shrunk to fit `size` as an RGB image ready for a JPEG. Opaque: exactly the old
    convert-then-thumbnail. See-through: shrunk as RGBA, then pasted (alpha as the mask)
    onto the checkerboard laid out at the final size."""
    resample = Image.LANCZOS if resample is None else resample
    rgba = _see_through_rgba(im)
    if rgba is None:
        out = im.convert("RGB")
        out.thumbnail(size, resample)
        return out
    rgba.thumbnail(size, resample)
    board = _checkerboard(rgba.size)
    board.paste(rgba.convert("RGB"), (0, 0), rgba.getchannel("A"))
    return board


def _could_be_see_through(im):
    """Header-only test: the mode or the `transparency` info says the picture MAY have
    see-through pixels. Reads no pixel data, so an opaque RGB/L original costs one header read."""
    return im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in im.info


def source_is_see_through(img_path):
    """True when the original file has see-through pixels (a GIF is judged on its first
    frame, the one make_thumbnail draws). False on any read problem. The header (mode and
    `transparency` info) is looked at first; the alpha is decoded only for those candidates."""
    if Image is None:
        return False
    try:
        with Image.open(img_path) as im:
            if not _could_be_see_through(im):
                return False                 # opened on frame 0: no n_frames scan, no decode
            return _see_through_rgba(im) is not None
    except Exception:
        return False


def make_thumbnail(img_path, thumb_path):
    """Render one gallery thumbnail. ATOMIC: Pillow writes a same-directory temp file and
    the finished JPEG is os.replace()d into position -- the idiom download's own `.part`
    file, the telemetry ledger and every other persistence path in this app already use.

    Saving straight onto the final path was the bug. A kill, a crash or a full disk part-way
    through `im.save` left a TRUNCATED .jpg sitting at the real name, and every "is it built
    yet?" check in this app is `thumb_path.exists()` -- so a half-written thumbnail is
    treated as done and never rebuilt. That was survivable while the only way to run a
    thumbnail pass was to press a button and watch it; it stopped being survivable when
    --rebuild-thumbs joined the sixty-day staleness backstop (2026-09-06) and became
    something that starts by itself, unattended, with nobody to notice a torn file. Sixty
    days is now how long a corrupt thumbnail can sit there.

    The swap also keeps the OLD thumbnail readable until the new one is complete, which is
    what makes --rebuild-thumbs' "the gallery never goes blank mid-run" literally true
    rather than nearly true."""
    if Image is None:
        return False
    tmp = None
    try:
        from moonglade import backup as core
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory (os.replace is only atomic within one filesystem) and pid-tagged,
        # so two processes rebuilding the same library cannot collide on one temp name.
        # It does not end in .jpg, so --rebuild-thumbs' orphan sweep (thumb_dir.glob
        # ("*.jpg")) cannot mistake a live temp file for a stale thumbnail.
        tmp = thumb_path.with_name(thumb_path.name + ".tmp-%d" % os.getpid())
        with Image.open(img_path) as im:
            # A GIF (Edit Pro's animation, 3.22 S5) is drawn from its FIRST frame, a still:
            # how the grid animates one is the look board's call, never this file's.
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            im = thumb_rgb(im, THUMB_SIZE, Image.LANCZOS)
            im.save(tmp, "JPEG", quality=THUMB_QUALITY)
        # _atomic_replace, not a bare os.replace: on Windows an antivirus or the Search
        # Indexer briefly opens a file the instant it is created, and renaming it then
        # raises PermissionError for a few hundred ms. Same helper download() uses.
        core._atomic_replace(tmp, thumb_path)
        return True
    except Exception:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
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
    clips too short for the filter to get a batch.

    ffmpeg is reached through moonglade.backup's media_tools section -- one cached
    availability probe, one place that owns the no-window flag, the timeouts and the
    "never raises" rule. This used to run its own uncached shutil.which() per file
    and two differently-shaped subprocess.run() calls."""
    from moonglade import backup as core
    import tempfile
    if Image is None or not _media_tools.ffmpeg_path():
        return False
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        r = _media_tools.run_ffmpeg(["-y", "-loglevel", "error", "-i", str(video_path),
                             "-vf", "thumbnail=72", "-frames:v", "1", tmp],
                            timeout=_media_tools.THUMB_TIMEOUT)
        if not r.ok or not os.path.getsize(tmp):
            # clips shorter than the seek point: take the literal first frame
            r = _media_tools.run_ffmpeg(["-y", "-loglevel", "error", "-i", str(video_path),
                                 "-frames:v", "1", tmp],
                                timeout=_media_tools.THUMB_RETRY_TIMEOUT)
        if not r.ok or not os.path.getsize(tmp):
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
    from moonglade import backup as core
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return None
    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
    for p in qdir.glob("*"):
        if p.is_file() and p.suffix.lower() in media_exts and _scan.media_id_of(p) == media_id:
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
    bounded by however many sidecars actually exist. Returns (items, total, total_bytes).

    Each item also carries `archive_only` (#66): True when its sidecar snapshot says PixAI no
    longer has that picture, so the file in the trash is the only copy anywhere. The Trash's
    Delete forever / Empty trash name how many before they destroy them. A file with no
    sidecar (everything quarantined before 2026-07-24) is not claimed to be one: nothing
    recorded says so. _list_quarantined also hands back the count across the WHOLE trash,
    not just this page, because Empty trash takes every file."""
    items, total, total_bytes, _only = _list_quarantined(out_dir, page, page_size)
    return items, total, total_bytes


def _list_quarantined(out_dir, page=1, page_size=60):
    """list_quarantined's body, plus a fourth value: how many media files in the whole trash
    are the only copy (their sidecar snapshot passes is_archive_only). See list_quarantined."""
    from moonglade import backup as core
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return [], 0, 0, 0

    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
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
    only_total = sum(1 for name, _s, _m in entries
                     if is_archive_only(meta_by_id.get(_scan.media_id_of(name))))

    def _sort_key(entry):
        name, _size, mtime = entry
        meta = meta_by_id.get(_scan.media_id_of(name))
        return (meta or {}).get("_deleted_at") or mtime

    entries.sort(key=_sort_key, reverse=True)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    page_entries = entries[start:start + page_size]

    items = []
    for name, size, mtime in page_entries:
        media_id = _scan.media_id_of(name)
        is_video = Path(name).suffix.lower() in core._VIDEO_EXTS
        meta = meta_by_id.get(media_id)
        deleted_at = (meta or {}).get("_deleted_at") or mtime
        prompt = ((meta or {}).get("prompt_full") or (meta or {}).get("prompt_preview") or "")
        items.append({
            "media_id": media_id, "filename": name, "size": size,
            "deleted_at": deleted_at, "is_video": "1" if is_video else "",
            "prompt": prompt[:2000], "has_meta": bool(meta),
            "archive_only": is_archive_only(meta),
        })
    return items, total, total_bytes, only_total


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
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
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
    from moonglade import backup as core
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
    # Deliberately NOT moonglade.backup.build_catalog_row: this is a RESTORE, not a
    # capture. The sidecar already holds the whole row the user owned -- rating,
    # collections, title, published state -- and there is no task, no extract_full_meta
    # surface, and (purge_media_local deleted the row) nothing in the catalog to carry
    # forward. Seeding from the saved row is the inverse of the builder's contract
    # (blank template + task fields + carry), so it stays its own thing. Issue #19.
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
    qdir = Path(out_dir) / _scan.DELETED_DIRNAME
    if not qdir.exists():
        return 0
    from moonglade import backup as core
    media_exts = _scan._IMAGE_EXTS | core._VIDEO_EXTS
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
        mid = _scan.media_id_of(p)
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
# quarantine (moonglade/organize.py's cmd_dedup) preserves the source's
# real subfolder structure under _duplicates/, and this feature's undo is
# specified to put a file back exactly where it came from.
# ---------------------------------------------------------------------------
# DUPLICATES_DIRNAME (the dedup quarantine folder) is defined in the LIBRARY SCAN
# section above, beside the other directory names every walker shares.


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
    return candidate if _scan._is_under(candidate, out_dir) else None


def _reconcile_one_row_after_move(out_dir, db_path, media_id, row):
    """Targeted, single-row version of moonglade.organize.reconcile_catalog_with_disk
    -- point media_id's catalog row at whatever copy is still actually on disk,
    without rescanning/rewriting the whole catalog (that function's own approach,
    fine for a batch CLI run, is wasteful for a single synchronous HTTP request).
    Used when a duplicate quarantine or undo changes what's on disk for a
    media_id whose row is being KEPT (e.g. a same_media loser's row, still
    pointing at a keeper that survives elsewhere). No-op if nothing changed, and
    a no-op if the media_id has no surviving file at all (that case is the
    caller's row-delete branch instead, not this function's job)."""
    from moonglade import backup as core
    matches = _scan.find_files_for_media_id(out_dir, media_id)
    if not matches:
        return
    survivor = matches[0]
    rel_surv = survivor.relative_to(out_dir)
    bucket = _organize._bucket_of(rel_surv)
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
    moonglade/organize.py's cmd_dedup -- quarantine, never hard-delete,
    same collision-suffix rule (dest already exists -> "_dup" inserted before the
    extension). Called once per file by the /api/duplicates/resolve route, which
    has already re-verified the (group_id, media_id, path) triple names a real
    duplicate pair (see _validate_duplicate_pair) -- this function trusts that
    and only handles the mechanics: the move, the catalog reconciliation, and
    the undo sidecar. --dedup-delete's hard-delete behavior is not reachable
    through this function under any argument.

    _check_read_only() fires FIRST, before any path is even resolved -- the same
    position submit_generation/submit_fixer/delete_task/claim_reward give it
    (moonglade/backup.py's own contract for every account/filesystem mutation
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
    from moonglade import backup as core
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
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    deleted_root = out_dir / _scan.DELETED_DIRNAME
    if _scan._is_under(src, quarantine_root) or _scan._is_under(src, deleted_root):
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
        survivors = _scan.find_files_for_media_id(out_dir, media_id)
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
    from moonglade import backup as core
    try:
        core._check_read_only("undo a duplicate quarantine (Duplicate Review undo)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(out_dir).resolve()   # match _resolve_under()'s own resolution -- see
                                        # quarantine_duplicate_file()'s identical comment
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    src = _resolve_under(out_dir, quarantine_path)
    if src is None or not _scan._is_under(src, quarantine_root):
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
    from moonglade import backup as core
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
        if _scan.media_id_of(path) != mid:
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
            if dist > _dupes.NEAR_DUP_HAMMING_THRESHOLD:
                return False, ("{} is no longer within the near-duplicate threshold "
                              "of the keeper").format(mid)
        return True, ""

    return False, "unknown group type '{}'".format(match_type)


def probe_has_audio(path, timeout=None):
    """True if the media file has at least one audio stream (ffprobe). Fails soft to
    False (never raises) -- a probe failure means the Loom export treats the clip as
    silent and pads it, which is safe; it must never crash the export.

    Gallery-side face of moonglade.backup's `media_tools.has_audio`, which answers three
    ways: True, False, and None for "ffprobe could not look at all". The export's contract
    is the two-way one, so the unanswerable case reads as silent -- deliberately, and in
    this one place rather than at each of the export's own branches. `timeout=None` takes
    media_tools' probe policy; the number does not live here any more."""
    from moonglade import backup as core
    return bool(_media_tools.has_audio(path, timeout=timeout))


def probe_duration(path, timeout=None):
    """Real duration in seconds via ffprobe, or None on failure (missing ffprobe,
    unreadable file, non-numeric output). Never raises.

    Gallery-side face of moonglade.backup's `media_tools.duration` -- see it for why
    there is only one implementation of this question now, and why it answers at full
    precision. `timeout=None` takes media_tools' probe policy."""
    from moonglade import backup as core
    return _media_tools.duration(path, timeout=timeout)


def build_thumbnails(rows, out_dir, thumb_dir, force=False, progress_cb=None, workers=8,
                     recheck=True):
    """Generate JPEG thumbnails for rows that have a file. CPU-bound (Pillow),
    so a thread pool gives a real multi-core speedup (Pillow releases the GIL
    during decode/encode). workers<=1 runs serially. Each worker writes a distinct
    thumb file; progress is reported on the calling thread.

    Videos are included ONLY when their thumb is missing (the collected PixAI
    poster made it already when one existed): a poster-less video gets a local
    ffmpeg frame-extract instead of staying blank forever. `force` deliberately
    does NOT overwrite an existing video thumb -- the poster came from the
    network and can't be regenerated from the local file.

    `recheck` (default True) runs the one-time see-through re-check inline for the batch
    jobs (--sync, --rebuild-thumbs, after an update). The gallery start passes False so a
    missing-thumbnail build is all it waits for, and schedules recheck_see_through_thumbnails()
    to run behind the started server instead."""
    from moonglade import backup as core
    if Image is None:
        print("Warning: Pillow not installed -- thumbnails will not be generated.")
        return
    total = 0
    done = 0
    work = []
    # ONE-TIME REBUILD (3.22 walk): thumbnails cut before the checkerboard existed flattened
    # see-through pictures to a black box, and "is it built?" is thumb_path.exists(), so they
    # would never be redone. Until the marker file is written, every already-built IMAGE
    # thumbnail is re-checked ONCE against its original and only the see-through ones are
    # recut (opaque thumbnails are left alone). A forced rebuild recuts everything anyway.
    marker = thumb_dir / CHECKER_MARKER
    recheck = recheck and not force and not marker.exists()
    for row in rows:
        if not row.get("filename"):
            continue
        is_vid = row.get("is_video") == "1"
        total += 1
        thumb_path = thumb_dir / "{}.jpg".format(row["media_id"])
        if thumb_path.exists() and (is_vid or not force):
            if recheck and not is_vid and thumbnail_renders(row.get("filename")):
                work.append((row["media_id"], thumb_path, row.get("filename"), is_vid, True))
            else:
                done += 1
            continue
        if not is_vid and not thumbnail_renders(row.get("filename")):
            done += 1            # an SVG has no thumbnail by design: skipped, not a failure (L3)
            continue
        work.append((row["media_id"], thumb_path, row.get("filename"), is_vid, False))

    def _one(item):
        mid, thumb_path, filename, is_vid, only_if_see_through = item
        if only_if_see_through:
            src = find_image_file(out_dir, mid, filename)
            if not src or not source_is_see_through(src):
                return True              # opaque (or unreadable): the old thumbnail stands
            return bool(make_thumbnail(src, thumb_path))
        if is_vid:
            vp = Path(out_dir) / (filename or "")
            if not vp.exists():
                # exts=_VIDEO_EXTS, not the matcher's image-only default: this fallback
                # exists for a video whose stored filename is stale or blank, and an
                # image-only match can never find one, so the row stayed thumbless.
                m = _scan.find_files_for_media_id(Path(out_dir), mid, exts=core._VIDEO_EXTS)
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
    if recheck or force:
        _write_checker_marker(thumb_dir)
    if total and not progress_cb:
        print()


def _write_checker_marker(thumb_dir):
    try:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / CHECKER_MARKER).write_text(
            "see-through thumbnails sit on a checkerboard\n", encoding="utf-8")
    except OSError:
        pass


def recheck_see_through_thumbnails(rows, out_dir, thumb_dir, workers=2, cancel=None):
    """The one-time see-through re-check (3.22 walk) as its own pass, for running BEHIND a
    started gallery. Every already-built image thumbnail is checked against its original
    (header first, alpha only for candidates) and only see-through ones are recut. The marker
    is written ONLY when every item was handled; a cancel (`cancel.is_set()`), a worker error
    or a failed recut leaves no marker, so the pass simply runs again next start. Returns True
    when the marker was written, False otherwise (including: nothing to do, marker already there)."""
    marker = thumb_dir / CHECKER_MARKER
    if Image is None or marker.exists():
        return False
    items = []
    for row in rows:
        fn = row.get("filename")
        if not fn or row.get("is_video") == "1" or not thumbnail_renders(fn):
            continue
        thumb_path = thumb_dir / "{}.jpg".format(row["media_id"])
        if thumb_path.exists():
            items.append((row["media_id"], thumb_path, fn))

    def _one(item):
        if cancel is not None and cancel.is_set():
            return False
        mid, thumb_path, fn = item
        src = find_image_file(out_dir, mid, fn)
        if not src or not source_is_see_through(src):
            return True                  # opaque (or unreadable): the old thumbnail stands
        return bool(make_thumbnail(src, thumb_path))

    ok = True
    if workers and workers > 1 and items:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_one, items):
                ok = ok and res
    else:
        for it in items:
            ok = _one(it) and ok
    if not ok or (cancel is not None and cancel.is_set()):
        return False
    _write_checker_marker(thumb_dir)
    return True


def start_see_through_recheck(rows, out_dir, thumb_dir, workers=2, cancel=None):
    """Run recheck_see_through_thumbnails() on a daemon thread (the same off-thread startup
    idiom as _health_prime / _outside_prime), after the server is listening. Returns the thread,
    or None when the marker says there is nothing to do."""
    if (thumb_dir / CHECKER_MARKER).exists():
        return None

    def _run():
        try:
            recheck_see_through_thumbnails(rows, out_dir, thumb_dir, workers=workers, cancel=cancel)
        except Exception:                # noqa: BLE001 -- background polish, never a crash
            pass
    th = threading.Thread(target=_run, daemon=True, name="moonglade-thumb-recheck")
    th.start()
    return th


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

# Design tokens: the SINGLE source of truth for the gallery's palette + achievement
# skins, shared (via the __DESIGN_TOKENS__ marker + .replace()) by the React shells
# (APP_PAGE/LOGIN_PAGE) and LOOM_PAGE_BUNDLE so every surface
# re-skins together instead of the Loom carrying its own copy that silently drifts.
DESIGN_TOKENS_CSS = r"""
  /* Z BANDS (decided 2026-08-01, gallery-era redesign): exactly three, nothing between --
     components 0-7 · overlays/modals 300-500 · ambient/celebration 510-520 (the layer that
     must paint over any modal). Normalized 2026-09-28: the legacy 200s cluster and the
     stray 99 went with the classic surfaces, and every other value that sat outside a band
     was renumbered into one in its old order. The achievement moment is 519, not the
     design's 520: its parade's skip control must paint in front of it and 520 is the
     ceiling. The ladder is gallery/src/styles/overlays.css's -- do not add values outside
     the three bands. */
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
      by dev/tests/test_upscale_boosters.py); this exists so the new surface does not add a
      third place for those numbers to drift.

    Substituted into APP_PAGE and the Loom shells (the surfaces with upscale UI)
    since the classic cut (2026-08-08) removed the INDEX/DETAIL pages it was
    originally built for.
    """
    from moonglade import backup as core
    return ("<script nonce=\"__CSP_NONCE__\">window.MG_UPSCALE={};window.MG_LORA={};</script>".format(
        json.dumps({
            "enlargeModels": list(_gen_params.ENLARGE_MODELS),
            "defaultEnlargeModel": _gen_params.DEFAULT_ENLARGE_MODEL,
            "ceiling": _gen_params.UPSCALE_PIXEL_CEILING,
            # So the panel can upscale an image whose model the catalog never recorded,
            # instead of refusing until one is picked -- PixAI's own dialog has no model
            # control at all. Served rather than retyped, like everything else here. It is
            # a VERSION id, so the panel sends it as version_id; see core for why.
            "fallbackVersionId": _gen_params.UPSCALE_FALLBACK_VERSION_ID,
            "denoise": {"strength": _gen_params.DEFAULT_UPSCALE_DENOISING_STRENGTH,
                        "steps": _gen_params.DEFAULT_UPSCALE_DENOISING_STEPS},
        }, separators=(",", ":")),
        # LoRA weight bounds per base architecture -- DiT allows 0..1.2, the SD family
        # -2..2. One table, served, so the drawer's slider and the builder's clamp cannot
        # drift into offering a weight the architecture rejects.
        json.dumps({
            "ranges": {k: list(v) for k, v in _gen_params.LORA_WEIGHT_RANGES.items()},
            "fallback": [_gen_params.LORA_WEIGHT_MIN, _gen_params.LORA_WEIGHT_MAX],
            "step": _gen_params.LORA_WEIGHT_STEP,
        }, separators=(",", ":"))))


# ---------------------------------------------------------------------------
# THE PRE-PAINT BOOT SCRIPT, injected into EVERY page head (the React shells and
# _LOOM_SHELL), immediately before the 401 guard below.
#
# Two per-device looks are stored in localStorage and PAINT THE PAGE, so both have to be
# applied in <head> before the first frame or the app renders in the wrong colours/face
# and then visibly jumps:
#   skin   -- html[data-skin], read by every skin rule in DESIGN_TOKENS_CSS.
#   fonts  -- the System + Hero type pairing (2026-09-04, Identity Chrome handoff C1),
#             written as inline --font-hero/--font-system custom properties on <html>.
#             The stored record carries the STACKS themselves, not just an id, precisely
#             so this script needs no copy of the pairing table -- swapping the
#             (deliberately provisional) set in gallery/src/lib/fonts.js changes nothing
#             here. gallery/src/lib/fonts.js reconciles the id against the current table
#             once the bundle is up.
# Both reads are wrapped: storage throws outright in private mode / with site data
# blocked, and an unstyled page is a far better failure than a blank one.
#
# ONE COPY, three shells. The skin line used to be hand-pasted into APP_PAGE, LOGIN_PAGE
# and _LOOM_SHELL separately; a second stored look would have made that three drifting
# copies of two things instead of one.
_PREPAINT_BOOT_JS = r"""<script nonce="__CSP_NONCE__">/* apply the saved skin + type pairing before first paint (no FOUC)
   -- see _PREPAINT_BOOT_JS in moonglade_gallery.py. Same keys/origin the gallery writes,
   so a change made there re-dresses the Loom too. */
try{var _sk=localStorage.getItem('skin');if(_sk&&_sk!=='moonglade')document.documentElement.setAttribute('data-skin',_sk);}catch(e){}
try{var _ft=JSON.parse(localStorage.getItem('fonts')||'null');if(_ft&&typeof _ft==='object'){if(_ft.hero)document.documentElement.style.setProperty('--font-hero',_ft.hero);if(_ft.system)document.documentElement.style.setProperty('--font-system',_ft.system);}}catch(e){}</script>"""


# ---------------------------------------------------------------------------
# Global 401 guard, injected into EVERY page head (the React shells and _LOOM_SHELL).
#
# Why an interceptor and not a helper at each call site: when it was written there were ~90
# fetch() calls across moonglade_gallery.py's inline JS, static/*.js and the Loom bundle, and
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
_AUTH_401_GUARD_JS = r"""<script nonce="__CSP_NONCE__">/* Global 401 guard -- see _AUTH_401_GUARD_JS in moonglade_gallery.py */
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
# viewport-fit=cover for the same reason APP_PAGE carries it (2026-09-06): the Loom is
# reachable from the phone (AppMobile's Loom sheet links straight here) and
# master-storyboard.jsx's own chrome reads env(safe-area-inset-top/bottom) in five places,
# every one of which resolved to 0 while this meta stayed narrow.
_LOOM_SHELL = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>The Loom - Moonglade Athenaeum</title>
<link rel="icon" type="image/png" href="/branding/favicon.png">
""" + _PREPAINT_BOOT_JS + _AUTH_401_GUARD_JS + r"""
<style>
__DESIGN_TOKENS__
/* font-family here, not just in .sb-root: anything mounted OUTSIDE #root inherits from
   body, and this shell deliberately mounts things there -- the toast stack, the ? FAB.
   Without it they fell back to the browser default font while the gallery shell gave them
   system-ui, so the same components looked different on the two pages. notify.css now also
   states its own family (host-neutral by design), but the shell should not be handing
   anything an unstyled baseline. */
body { background: var(--base); margin: 0; font-family: var(--font-system, system-ui, sans-serif); }
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
<script nonce="__CSP_NONCE__">
/* Session P (BUILD-w5-p s3.5, review F15): every call now REJECTS on a failed answer instead
   of reading one as "nothing there" -- a failed or unreadable get used to come back null, and
   the boot path seeded a blank board over the key. get also hands back the board's rev (and
   missing:true for an absent key); set takes an optional {base_rev} and resolves {ok, rev} or
   {conflict, value, rev} (the server's compare-and-swap), throwing on anything else. */
window.storage = (function(){
  function fail(r, d){ var e = new Error((d && d.error) || ('HTTP ' + r.status)); e.status = r.status; e.unreadable = !!(d && d.error === 'unreadable'); throw e; }
  function body(r){ return r.json().catch(function(){ return null; }); }
  return {
    get:function(k){ return fetch('/api/loom/get?key='+encodeURIComponent(k)).then(function(r){ return body(r).then(function(d){ if(!r.ok || !d) fail(r, d); if (d.value != null) return {value:d.value, rev:d.rev}; return d.missing ? {value:null, missing:true, rev:d.rev} : null; }); }); },
    set:function(k,v,shared,opts){ var b={key:k,value:v}; if (opts && opts.base_rev != null) b.base_rev = opts.base_rev; return fetch('/api/loom/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(function(r){ return body(r).then(function(d){ if (r.status === 409 && d && d.conflict) return {conflict:true, value:d.value, rev:d.rev}; if(!r.ok || !d || d.ok === false) fail(r, d); return {ok:true, rev:d.rev}; }); }); },
    list:function(p){ return fetch('/api/loom/list?prefix='+encodeURIComponent(p||'')).then(function(r){ return body(r).then(function(d){ if(!r.ok || !d) fail(r, d); return {keys:(d.keys)||[]}; }); }); },
    delete:function(k){ return fetch('/api/loom/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})}).then(function(r){ return body(r).then(function(d){ if(!r.ok || (d && d.ok === false)) fail(r, d); return d; }); }); }
  };
})();
/* The feat beacon's per-render nonce (2026-09-07 ruling -- see api_ach_event()). Since
   Session I (2026-09-28) this shell posts NOTHING itself: the "?" below opens the guide, and
   the guide's own open sends the docs event through gallery/src/notify/achNonce.js, which the
   Loom bundle carries -- the one poster, with the one set of rules (send the nonce, adopt
   next_nonce, one conditional stale-page retry). That module reads its first nonce from
   here when there is no MG_BOOT. The value below is a PLACEHOLDER the /loom route substitutes
   on the way out -- a fresh mint per render, exactly as app_page puts one in MG_BOOT.
   (Naming the placeholder token in this comment would substitute it here too.) */
window.MG_ACH_NONCE = "__ACH_NONCE__";
</script>
__RUNTIME_SCRIPT_BLOCK__
<!-- The Loom's "?" (Session I decision 2): the hand-written quick guide that used to open
     here retired; the button opens the in-app guide (the wiki this install carries) on The
     Loom's page, through the verb the bundle publishes (gallery/src/help/helpStore.js). -->
<button id="eb-help-btn"
  style="position:fixed;bottom:18px;right:18px;z-index:401;width:38px;height:38px;border-radius:50%;background:var(--accent);color:var(--base);border:none;font-size:19px;font-weight:700;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5);"
  title="The Loom's page of the guide (?)" aria-label="Open the guide">?</button>
<!-- Its click is wired here, not in an onclick attribute: the page's script policy runs only
     nonced scripts (CSP_PAGE_POLICY), and an inline handler is not one. -->
<script nonce="__CSP_NONCE__">
document.getElementById("eb-help-btn").addEventListener("click", function () {
  if (window.mgHelp) window.mgHelp.open('The-Loom');
});
</script>
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
             '<script nonce="__CSP_NONCE__">ReactDOM.createRoot(document.getElementById("root"))'
             '.render(React.createElement(LoomBundle.default));</script>')
    .replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS))


def _build_stamp():
    """Version + short git SHA of the code THIS process loaded, computed once at
    startup. If you pull without restarting, this keeps showing the OLD sha -- which
    is precisely how you tell a stale server from a fresh one. Fails soft."""
    try:
        from moonglade import backup as _core
        ver = getattr(_core, "__version__", "?")
    except Exception:
        ver = "?"
    sha = ""
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_paths.APP_ROOT),
            stderr=subprocess.DEVNULL, timeout=4,
            creationflags=_NO_WINDOW).decode().strip()
    except Exception:
        sha = ""
    return "v{}".format(ver) + (" · {}".format(sha) if sha else "")


DEFAULT_LIBRARY_DIR = _paths.DEFAULT_LIBRARY_DIR    # relative: anchored to the app folder
DEFAULT_HOST = _settings.DEFAULT_HOST
DEFAULT_PORT = _settings.DEFAULT_PORT
DEFAULT_BONJOUR_NAME = _settings.DEFAULT_BONJOUR_NAME


def resolve_library_dir(explicit=None):
    """Where the library lives: an explicit --out for this one start, then settings.json's
    library_dir (the Control Panel's library folder), then the default beside the app --
    moonglade.settings.library_path(), the one resolver the server, the command line and the
    MCP server share (S8). Explicit beats stored on purpose: a one-off `--out somewhere` must
    neither be overridden by the shared setting nor quietly rewrite it. Returns a string.

    settings.json is read once per change of the file, so the value the Panel saved before a
    restart is the one the restarted server opens."""
    return str(_settings.library_path(explicit))


def resolve_server_settings(host_arg=None, port_arg=None):
    """Bind host/port + Bonjour discovery settings: an explicit --host/--port for this one
    start wins, else settings.json's host/port/bonjour (the Control Panel's Bonjour chip),
    else the defaults (moonglade.settings.server). Bonjour defaults OFF -- broadcast is
    opt-in, flipped on from the chip. A stored host that cannot be bound falls back to the
    default rather than crash the bind at startup."""
    return _settings.server(host_arg, port_arg)


def _supervised():
    """True when the server was started by the managed launcher (Moonglade Launcher), which sets
    MOONGLADE_SUPERVISED=1 and relaunches on exit code 42. Restart is only offered when True."""
    return os.environ.get("MOONGLADE_SUPERVISED") == "1"


# New on every server start: a notice keyed by it is said once per start in every open tab
# (gallery/src/notify/serverNotice.js remembers the key it last showed).
_SERVER_START = secrets.token_hex(8)
_SERVER_BOOT = time.monotonic()      # for "up" in the line the server writes when it stops


# THINGS OUTSIDE THE APP THAT NAME ITS OLD FILES (moonglade.outside; DECISIONS 2026-10-07,
# pick 5): a scheduled task, a Claude tools registration or a shortcut still running
# moonglade_backup.py, moonglade_mcp.py or Serve Gallery.pyw. A real start (main()) looks
# once, off the request path, and the notice offers **Fix them** to a tab on this machine.
# None until that look has run -- and in every app a test builds, since only main() looks.
_OUTSIDE = {"items": None}
_OUTSIDE_FIXING = threading.Lock()


def _outside_scan():
    """Look outside the app now and keep what was found. Never raises."""
    from moonglade import outside as moonglade_outside
    try:
        items = moonglade_outside.find()
    except Exception:                                   # noqa: BLE001 -- nothing found, then
        items = []
    _OUTSIDE["items"] = items
    return items


def _outside_prime():
    """main()'s one call: the look runs on its own thread (schtasks can take seconds), after
    the server is up."""
    threading.Thread(target=_outside_scan, daemon=True, name="moonglade-outside-scan").start()


def _shortcut_icon_bytes(stem):
    """A mark's .ico bytes by its file stem (mark_4), for a shortcut whose old icon is gone:
    the loose cut, else the pack's. Only a plain stem is ever looked up."""
    if not re.match(r"^[A-Za-z0-9_-]+$", stem or ""):
        return None
    return _branding._branding_bytes(_branding._role_rel("marks", stem + ".ico"))


def server_notice(local=False):
    """The notice every open tab shows once per server start (the /api/jobs poll carries it;
    gallery/src/notify/serverNotice.js shows the corner toast), or None. Read only.

    Today it is the one about things outside the app that still name its old files, and only
    for a tab on this machine (`local`): the fix rewrites this machine's tasks, configs and
    shortcuts, and its route is LOCALHOST. `fix` names the toast's button; the poll adds the
    session's CSRF token to it."""
    items = _OUTSIDE.get("items")
    if not local or not items:
        return None
    from moonglade import outside as moonglade_outside
    title, msg = moonglade_outside.notice_words(items)
    return {"key": _SERVER_START, "title": title, "msg": msg,
            "fix": {"label": moonglade_outside.fix_label(items)}}


# The running werkzeug server, so a web Stop/Restart handler can shut it down GRACEFULLY instead
# of hard-killing the process. main() stashes the server here right before it blocks in
# serve_forever(); _schedule_server_exit() records the intended exit code and asks the server to
# stop. main()'s `finally` then runs real cleanup (the IPv6 companion, and -- once it lands --
# the mDNS goodbye) and returns `code` to `sys.exit(main())`, which the supervisor reads
# (0 = stop, 42 = relaunch). This replaces the old os._exit() hard kill, which skipped every
# cleanup hook; os._exit() survives only as the fallback for the impossible "no server stashed"
# case so Stop/Restart can never go inert.
_SERVER_CONTROL = {"srv": None, "companion": None, "exit_code": 0}
_EXIT_LOCK = threading.Lock()


def _schedule_server_exit(code):
    """Ask the running server to stop with `code` (0 = stop; 42 = the supervisor's 'relaunch
    me' signal), letting the current HTTP response flush first. Factored out so tests can assert
    the intended exit code without actually killing the test process. First-wins: once a stop is
    scheduled, a second control click within the flush window is ignored, so two near-simultaneous
    clicks (Stop then Restart) can't race the exit code non-deterministically."""
    with _EXIT_LOCK:
        if _SERVER_CONTROL.get("exit_scheduled"):
            return
        _SERVER_CONTROL["exit_scheduled"] = True
        _SERVER_CONTROL["exit_code"] = code

    def _die():
        import time
        # Let THIS response finish writing on its own (daemon) request thread before the process
        # exits -- shutdown() stops ACCEPTING, but the exit that follows still kills daemon
        # threads, so the flush window is still wanted even with graceful shutdown.
        time.sleep(0.4)
        srv = _SERVER_CONTROL.get("srv")
        if srv is not None:
            srv.shutdown()                    # unblocks main()'s serve_forever() -> cleanup + return code
        else:
            os._exit(code)                    # fallback: server was never stashed (shouldn't happen)
    threading.Thread(target=_die, daemon=True).start()


RESTART_EXIT_CODE = 42        # the supervisor's "relaunch me" signal (see _schedule_server_exit)


# WHY THE SERVER ENDED (#95). A Stop, a Restart or an update leaves a request line in
# moonglade.log and nothing in serve.log, the file the launcher points at; so each now writes its
# reason when it asks (_note_server_exit) and main()'s `finally` writes one line saying what ended
# it (server_exit_reason). They are kept OUT of _schedule_server_exit, whose signature and body
# the tests pin.
def _clean_for_log(text, limit=100):
    """Text a client controls (a user name, a browser string) made safe for one log line: printable
    ASCII only, so no newline can forge a second line, a double quote turned into a single one
    so a value cannot close its own quotes, and cut to `limit`."""
    return re.sub(r'[^\x20-\x7e]|"', lambda m: "'" if m.group() == '"' else "?",
                  str(text or ""))[:limit]


def _span_words(seconds):
    """45s, 3m05s, 3h12m05s -- hours only when there are hours, minutes only when there are."""
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        s = 0
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    if h:
        return "%dh%02dm%02ds" % (h, m, sec)
    if m:
        return "%dm%02ds" % (m, sec)
    return "%ds" % sec


def _note_server_exit(why):
    """Remember who or what asked for the exit that is about to happen, and log it. First wins,
    like _schedule_server_exit: a second click keeps the first reason."""
    with _EXIT_LOCK:
        if _SERVER_CONTROL.get("exit_why"):
            return
        _SERVER_CONTROL["exit_why"] = why
    import logging as _logging
    _logging.getLogger(__name__).info("server exit requested: %s", why)


def server_exit_reason(scheduled, code, why, interrupted, errored=True):
    """The sentence for why the server is ending (pure): what main()'s `finally` writes.
    `errored`: an exception is leaving the serve loop (False when the loop returned)."""
    if scheduled and code == RESTART_EXIT_CODE:
        return "Restart requested " + (why or "(no details recorded)")
    if scheduled:
        return "Stop requested " + (why or "(no details recorded)")
    if interrupted:
        return "Ctrl+C in a terminal"
    if not errored:
        return "the server loop ended on its own, with no Stop or Restart asked for"
    return ("an unhandled error ended the server loop (its traceback follows in moonglade.log "
            "as CRITICAL, and in this file)")


def _install_signal_note():
    """Off Windows only: a SIGTERM or SIGHUP is logged, then the default action runs as it
    would have (the handler restores the default and sends the signal again). On Windows nothing
    is installed: a pythonw process is never handed one. Main thread only."""
    if sys.platform == "win32":
        return
    import signal
    import logging as _logging

    def _note(signum, frame):
        try:
            name = signal.Signals(signum).name
        except Exception:                               # noqa: BLE001
            name = str(signum)
        try:
            _logging.getLogger(__name__).info("server received %s", name)
        except Exception:                               # noqa: BLE001
            pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            if signal.getsignal(sig) is not signal.SIG_DFL:
                continue                  # ignored (nohup) or handled by someone: left as it is
            signal.signal(sig, _note)
        except (ValueError, OSError):
            pass


def _power_in_progress():
    """"stop" or "restart" once _schedule_server_exit has been called and the process has not
    yet gone, else "". This is the server's own record that a Stop/Restart is under way: the
    Control Panel reads it off /api/panel/status when it mounts, so a panel reopened (or a
    page remounted) after the click picks the reconnect watch back up instead of showing an
    idle panel (#84). It lives in the process and dies with it, so a fresh process always
    starts at "" -- there is no stale marker to clear."""
    with _EXIT_LOCK:
        if not _SERVER_CONTROL.get("exit_scheduled"):
            return ""
        return "restart" if _SERVER_CONTROL.get("exit_code") == RESTART_EXIT_CODE else "stop"


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
    directly by moonglade/jobs.py's `_cli_job_finish`, which logs a
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
                 tempfile.gettempdir(), sys.prefix, str(_paths.run_dir())]
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


# ---------------------------------------------------------------------------
# Auth tiers -- DECLARED AT THE ROUTE, enforced in one place
# ---------------------------------------------------------------------------
# A route's auth tier is a property OF THE ROUTE, so it is written on the route.
# It used to live in dev/tests/test_route_tiers.py's ROUTE_TIERS table instead, which
# meant every route addition edited two files in two repositories' worth of
# context -- and the table had already drifted past every credit-spending route
# once (see that file's own header). The decorator below hangs the declaration on
# the view function; _enforce_front_door() reads it back off app.view_functions at
# request time; create_app() refuses to return an app in which any registered rule
# has no declaration. The test still enumerates the url_map and still proves each
# tier against a live request -- it just no longer DECLARES anything.
PUBLIC = "PUBLIC"        # reachable with no session at all (the login surface itself)
LOGIN = "LOGIN"          # any logged-in session, local or LAN
LOCALHOST = "LOCALHOST"  # a logged-in session AND a loopback remote_addr
TIERS = (PUBLIC, LOGIN, LOCALHOST)

# The 403 body a LOCALHOST route refuses with. Three routes say something more
# specific instead (see their `message=`); the wording of all four is a contract
# the front end reads, so it is carried here verbatim rather than regenerated.
LOCALHOST_REFUSAL = "localhost-only"

_TIER_ATTR = "_mg_route_tier"


def tier(default, message=LOCALHOST_REFUSAL, **by_method):
    """Declare this view's auth tier. `@tier(LOGIN)`, `@tier(LOCALHOST)`, `@tier(PUBLIC)`.

    A per-method override keeps a split route declarative instead of pushing half
    of it back into the handler body: `/api/library-path` and `/api/panel/schedule`
    are `@tier(LOGIN, POST=LOCALHOST)` -- readable at the route, and enforced by
    the same gate as everything else.

    `message` overrides the `error` string in the 403 a LOCALHOST route refuses
    with, for the three routes whose hand-written guard said something more
    specific than "localhost-only" (deleting from PixAI; importing onto the
    server's machine). It is the message only -- the status and JSON shape are
    the same for every tier refusal.

    Pick the tier by what the handler can DO, not by what feels convenient:
      LOGIN     -- browse the library, spend the owner's credits, manage your OWN
                   account. A signed-in LAN device is NOT read-only; that is the
                   whole point of the tier (see moonglade-internal/DECISIONS.md).
      LOCALHOST -- irreversible cloud deletion, writes to config.json (which holds
                   PIXAI_API_KEY / AUTH_SECRET_KEY / AUTH_USERS), file-moving
                   maintenance, or shelling out on the SERVER machine.
      PUBLIC    -- the login surface and the static art it renders. Nothing else.

    A route whose LOCALHOST requirement depends on its ARGUMENTS rather than on
    its URL is not expressible as a tier and must not be forced into one:
    /api/panel/run demands loopback only for a destructive action, and
    /api/users/remove only for someone else's account. Those declare the floor
    the gate can actually enforce (LOGIN) and keep their own conditional check,
    which their own test files cover."""
    if default not in TIERS:
        raise ValueError("unknown auth tier {!r}; expected one of {}".format(default, TIERS))
    bad = {m: t for m, t in by_method.items() if t not in TIERS}
    if bad:
        raise ValueError("unknown auth tier(s) in per-method override: {!r}".format(bad))

    declaration = (default, {m.upper(): t for m, t in by_method.items()}, message)

    def _declare(view):
        setattr(view, _TIER_ATTR, declaration)
        return view
    return _declare


def route_tier(view, method):
    """The tier that governs `view` for `method`, or None if it declares none."""
    declaration = getattr(view, _TIER_ATTR, None)
    if declaration is None:
        return None
    default, by_method, _message = declaration
    return by_method.get(method, default)


def route_tier_message(view):
    """The `error` string this view's LOCALHOST refusal carries."""
    declaration = getattr(view, _TIER_ATTR, None)
    return LOCALHOST_REFUSAL if declaration is None else declaration[2]


def declare_endpoint_tier(app, endpoint, default, message=LOCALHOST_REFUSAL, **by_method):
    """Declare a tier for an endpoint whose view function this module does not define.

    Exactly one exists: Flask's built-in `static`. It is NOT special-cased away --
    `if rule.endpoint == "static": continue` is the single most common way a
    catch-all route rule grows a hole, and /static/ is gated like everything else."""
    view = app.view_functions[endpoint]
    try:
        tier(default, message=message, **by_method)(view)
    except (AttributeError, TypeError):
        # A bound method or C function can't carry an attribute; wrap it once.
        import functools

        @functools.wraps(view)
        def _shim(*a, **k):
            return view(*a, **k)
        app.view_functions[endpoint] = tier(default, message=message, **by_method)(_shim)


def assert_every_route_declares_a_tier(app):
    """Refuse to hand back an app in which any registered rule has no tier.

    This is the half of the old test table that could never be a test: a
    declaration that lives at the route can only be MISSING at the route, and the
    cheapest possible moment to say so is app creation, not CI. Adding a route
    without a tier now fails the very first request anyone makes -- including the
    developer's own."""
    missing = sorted(
        {(rule.endpoint, str(rule)) for rule in app.url_map.iter_rules()
         if route_tier(app.view_functions.get(rule.endpoint), "GET") is None})
    if missing:
        raise AssertionError(
            "{} registered route(s) declare NO auth tier:\n{}\n\n"
            "FIX: put @tier(...) on the view, under its @app.route(...):\n"
            "    @app.route(\"/api/thing\", methods=[\"POST\"])\n"
            "    @tier(LOGIN)\n"
            "    def api_thing():\n"
            "Choose by what the handler can DO -- see tier()'s own docstring. The\n"
            "tier is not paperwork: every credit-spending route was missing from\n"
            "the hand-maintained lists that preceded this mechanism, and nothing\n"
            "noticed until a route-gating audit found it."
            .format(len(missing),
                    "\n".join("    {} ({})".format(r, e) for e, r in missing)))


# --- the AI-Tools scene catalog ------------------------------------------------------
# PixAI's `listChatEditingScenes`, memoized module-level on the contest_board pattern: ONE
# snapshot every consumer shares, a lock around it, and FAILURES ARE NOT CACHED (a raise
# never reaches the store, and an empty answer is not banked as "the catalog is empty").
#
# Two consumers, one read: the AI-Tools nav modal browses the TILES and the gen drawer's
# scene generator reads the picked scene's CONTROL SCHEMA. Before 2026-09-04 the modal read
# nothing at all -- it rendered a hardcoded 28-entry array, so `daily-fortune`, `daily-setlog`
# and `mini-mart-ad` (live on PixAI, 31 scenes as of this writing) had no tile and were
# unreachable in the UI (issue #36). Both halves now come from here.
#
# TTL stays at an hour, NOT the contest board's 90s: a contest's entries change by the
# minute, the scene catalog gains a scene every few weeks, and the repo's standing rule is
# to be polite to their servers. The shared pattern is the memo, not the number.
SCENES_TTL = 3600.0
_scenes_cache = {}
_scenes_cache_lock = threading.Lock()

# Preset keys PixAI uses for the "pick a language" scenes. Every human-readable string in the
# catalog is an i18n key (`growth:chat-editing-scene.<slug>.title`), so the catalog cannot
# name a scene or a preset for us -- but the KEYS are stable, and these are the ones that mean
# "this scene's presets are languages" (captured live 2026-09-04: character-card
# english/japanese/chinese/korean, chatfic en/ja/ko/zh-tw, character-style-generator +
# daily-fortune + mini-mart-ad english/japanese/korean/traditional-chinese).
_SCENE_LANG_KEYS = {
    "english": "EN", "en": "EN", "japanese": "JP", "ja": "JP", "jp": "JP",
    "korean": "KR", "ko": "KR", "kr": "KR", "chinese": "CN", "zh": "CN", "zh-cn": "CN",
    "traditional-chinese": "TC", "zh-tw": "TC", "tw": "TC",
    "simplified-chinese": "CN", "zh-hant": "TC", "zh-hans": "CN",
}
# The only host the CDN thumbnail proxy will fetch (api_train_cover's SSRF guard). A catalog
# demo image on any other host is passed through as-is rather than pointed at a proxy that
# would 403 it.
_SCENE_CDN_HOST = "images-ng.pixai.art"


def pixai_cdn_url_ok(url):
    """THE host guard for fetching a PixAI picture server-side (api_train_cover's SSRF guard,
    shared with the Loom's frame-thumbnail fill): https, on exactly the PixAI image CDN."""
    import urllib.parse as _up
    try:
        p = _up.urlparse(str(url or ""))
    except ValueError:
        return False
    return p.scheme == "https" and p.netloc == _SCENE_CDN_HOST


def scene_catalog(core, session, force=False):
    """The WHOLE live scene catalog (listChatEditingScenes), memoized for SCENES_TTL.

    The one read both scene consumers go through, so opening the modal and then opening the
    generator costs a single round trip rather than two. `force` drops the memo.

    Failure handling is the point: `core.chat_editing_scenes` raising propagates BEFORE the
    store is touched (the next caller retries against PixAI instead of being served a
    remembered outage), and an empty list is likewise not banked -- an account that briefly
    answers `[]` must not blank the modal for the next hour."""
    now = time.time()
    with _scenes_cache_lock:
        ent = _scenes_cache.get("catalog")
        if not force and ent and (now - ent["at"]) < SCENES_TTL:
            return ent["rows"]
    rows = _gen_road.chat_editing_scenes(session)
    if rows:
        with _scenes_cache_lock:
            _scenes_cache["catalog"] = {"at": time.time(), "rows": rows}
    return rows


def _scene_label(key):
    """A display label for a scene/preset/selector key -- PixAI's own `name` is the full
    workflow prompt (tarot) and its `title` is an i18n key
    (`growth:chat-editing-scene.plushie.title`), so the human-readable form is the
    title-cased key ('the-sun' -> 'The Sun', 'daily-fortune' -> 'Daily Fortune')."""
    return (str(key or "").replace("-", " ").replace("_", " ").strip().title())


def _scene_shape(preset_keys, has_custom, ref_min):
    """Which control row a scene needs, from its live schema alone -- the tile's shape chip.

    Ordered most-specific first, and verified against all 28 curated tiles on 2026-09-04:
    this derivation reproduces every one of the shipped shapes, which is what makes it safe
    to let a scene PixAI adds tomorrow classify itself.
      dual   -- needs two source images (dual-character-generator)
      lang   -- its presets ARE the language list (character-card, chatfic, daily-fortune)
      text   -- it takes a custom text field (polaroid, vtuber, gacha-screen)
      select -- any other preset chips (tarot modes, fantasy classes, setlog times)
      click  -- no presets at all: one tap (plushie, lego, giant-statue)
    `lang` beats `text` deliberately: character-card has BOTH, and its shipped chip is
    Language."""
    keys = [str(k or "").strip().lower() for k in (preset_keys or []) if k]
    if int(ref_min or 1) >= 2:
        return "dual"
    if keys and all(k in _SCENE_LANG_KEYS for k in keys):
        return "lang"
    if has_custom:
        return "text"
    return "select" if keys else "click"


def _scene_detail(shape, preset_keys):
    """The tile's small grey line under the name, derived for scenes we carry no curated copy
    for. Deliberately modest -- it says what the live schema actually shows (language codes,
    the first few preset names, a count) and never invents flavour text."""
    keys = [str(k or "").strip().lower() for k in (preset_keys or []) if k]
    if shape == "lang":
        seen, codes = set(), []
        for k in keys:
            code = _SCENE_LANG_KEYS.get(k)
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return " / ".join(codes)
    if shape == "dual":
        return "2 refs · %d poses" % len(keys) if keys else "2 refs"
    if shape == "text":
        return "custom text"
    if shape == "select":
        if 0 < len(keys) <= 3:
            return " / ".join(_scene_label(k) for k in keys)
        return "%d options" % len(keys) if keys else ""
    return ""


def scene_thumb_url(images):
    """The catalog's OWN thumbnail for a scene, as a URL this app can actually load.

    PixAI serves scene demo art from its image CDN, which the browser cannot fetch
    cross-origin from localhost -- so a CDN url is handed back through the existing
    /api/pixai-cdn/thumb proxy (the same one the Train panel and My Art's LoRA cards use)
    rather than growing a second one. `images.demo` is a LIST of urls used directly as an
    <img src> by PixAI's own /ai-tools/<slug> page; `images.background` was empty on every
    one of the 31 scenes captured 2026-09-04, so demo[0] is the picture. Anything off the
    CDN host is passed through untouched -- the proxy's SSRF guard would refuse it, and a
    raw url at least has a chance of loading. Returns "" when the scene ships no art."""
    import urllib.parse as _up
    imgs = images if isinstance(images, dict) else {}
    cands = []
    for field in ("demo", "background"):
        val = imgs.get(field)
        if isinstance(val, str):
            cands.append(val)
        elif isinstance(val, (list, tuple)):
            cands.extend(val)
    for raw in cands:
        url = str(raw or "").strip()
        if not url:
            continue
        try:
            parsed = _up.urlparse(url)
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.netloc == _SCENE_CDN_HOST:
            return "/api/pixai-cdn/thumb?u=" + _up.quote(url, safe="")
        return url
    return ""


def scene_local_art(slug):
    """True when a curated local picture for this scene exists: bridge/scene_<slug>.webp, loose
    in the branding tree or packed in the container (the order /branding/<path> serves them).
    The AI Tools grid asks this before it requests the file, so a scene with no local art goes
    straight to the catalog's own picture instead of a 404 per tile."""
    slug = str(slug or "")
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return False
    try:
        coded = _branding._public_rel_to_coded("bridge/scene_{}.webp".format(slug))
        if (_branding.branding_root() / coded).is_file():
            return True
        box = _branding._get_container()
        return bool(box is not None and box.has(coded))
    except Exception:
        return False


def scene_row(sc):
    """One raw chatEditingScene -> the row both scene surfaces render.

    The CONTROL half (presets / selectors / custom / refMin) is what the gen drawer's scene
    generator builds its form from. The TILE half (label / shape / detail / thumb / tier) is
    what the AI-Tools modal's grid draws, and exists so a scene PixAI adds gets a tile with
    no code change -- the whole point of issue #36.

    Every human string in the catalog is an i18n key, so `label` is the title-cased sceneId,
    not PixAI's `title`. The modal still overlays its own curated copy where it has some
    ("Character Style Generator" ships as "Character Style"); this is the floor, not a
    redesign of the shipped tiles.

    NO price: the catalog carries no price/credit/cost field anywhere (confirmed over all 31
    live scenes, 2026-09-04), which is the same reason SceneTab's confirm names the spend
    instead of quoting it."""
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
    keys = [p["key"] for p in presets]
    shape = _scene_shape(keys, bool(sc.get("custom")), ref_min)
    return {"sceneId": sc.get("sceneId"), "modelId": sc.get("modelId"),
            "tier": (sc.get("permission") or {}).get("membershipTier"),
            "refMin": ref_min, "refMax": ref_max,
            "presets": presets, "selectors": selectors,
            "custom": bool(sc.get("custom")),
            "label": _scene_label(sc.get("sceneId")),
            "shape": shape,
            "detail": _scene_detail(shape, keys),
            "thumb": scene_thumb_url(sc.get("images"))}


# ---- the feat-beacon nonce, debounce and rate limit (2026-09-07) ------------------------
# What replaced the LOCALHOST gate on /api/ach-event. The gate's problem was that the
# beacon is the ONLY witness a feat gesture happened, so any signed-in session could POST
# a feat event from a console and arm the feat. Loopback made the gesture witnessable
# but cost every phone and LAN device the three feats outright. The owner's call
# (2026-09-07): "triggered should be obtainable easily on a phone just like desktop. For
# sure build the nonce."
#
# So the witness moves from WHERE the request came from to WHETHER IT CAME FROM A PAGE THE
# SERVER RENDERED. A nonce is minted into each render, is good for exactly one event inside
# 60 seconds, and is bound to the session it was minted for. A console POST has no nonce; a
# replayed one is already spent; one lifted from another session's page is not this
# session's to spend. That is a real (if soft) witness, and unlike loopback it is one a
# phone passes.
#
# Process-local by design, exactly like _login_attempts: one process, `python -m
# moonglade.gallery`. Under a multi-worker server each worker would keep its own table
# and a nonce minted by worker A would read as unknown at worker B -- the page would refresh
# once and carry on, so the failure mode is a wasted round trip, not a lost feat.
_ACH_NONCE_TTL_S = 60.0       # a nonce is good for one event inside this window
_ACH_NONCE_MAX = 4000         # hard cap on the table (sweep-first, then evict oldest)
_ACH_DEBOUNCE_S = 0.15        # the same (session, event) inside this counts once
_ACH_RATE_MAX = 30            # beacon calls per session per window (mint + event both count)
_ACH_RATE_WINDOW_S = 60.0
_ach_lock = threading.Lock()
_ach_nonces = {}   # nonce -> (issued_at, sid)
_ach_last = {}     # (sid, event) -> epoch of the last event that COUNTED
_ach_rate = {}     # sid -> [epoch, ...] of calls inside the rolling window


def _ach_sweep(now):
    """Drop expired nonces, stale debounce stamps and spent rate rows. The caller holds
    _ach_lock. Runs on every mint AND every check, so the tables cannot grow between two
    cold periods -- there is no other reaper."""
    for nonce, (issued, _sid) in list(_ach_nonces.items()):
        if now - issued > _ACH_NONCE_TTL_S:
            _ach_nonces.pop(nonce, None)
    for key, stamp in list(_ach_last.items()):
        if now - stamp > _ACH_RATE_WINDOW_S:
            _ach_last.pop(key, None)
    for sid, hits in list(_ach_rate.items()):
        fresh = [t for t in hits if now - t <= _ACH_RATE_WINDOW_S]
        if fresh:
            _ach_rate[sid] = fresh
        else:
            _ach_rate.pop(sid, None)


def _ach_mint(sid, now=None):
    """A fresh nonce for `sid`. Sweeps first; if the table is somehow still at its cap
    (a burst inside one 60s window), evicts the oldest entries rather than growing --
    an unbounded dict fed by any logged-in session is a memory vector, and losing the
    oldest nonce costs its page one refresh."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        overflow = len(_ach_nonces) - _ACH_NONCE_MAX + 1
        if overflow > 0:
            for nonce, _rec in sorted(_ach_nonces.items(), key=lambda kv: kv[1][0])[:overflow]:
                _ach_nonces.pop(nonce, None)
        nonce = secrets.token_urlsafe(16)
        _ach_nonces[nonce] = (now, sid)
        return nonce


def _ach_consume(nonce, sid, now=None):
    """True when `nonce` was minted for THIS session and is still inside its window.
    A match is spent whether or not it had expired (one event per nonce, always). A
    nonce belonging to another session is NOT spent -- refusing it is right, but burning
    it would let any logged-in session invalidate another's page at will."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        rec = _ach_nonces.get(nonce) if nonce else None
        if not rec:
            return False
        issued, owner = rec
        if owner != sid:
            return False
        _ach_nonces.pop(nonce, None)
        return (now - issued) <= _ACH_NONCE_TTL_S


def _ach_debounced(sid, event, now=None):
    """True when the same (session, event) already counted less than _ACH_DEBOUNCE_S ago.
    Records this event's stamp when it is not.

    This is a WALL-CLOCK gap and nothing else: it cannot see whether one gesture fired
    twice or a person tapped twice, so the window is the whole of the distinction. At the
    400ms it shipped with on 2026-09-07 it was not one -- a phone user tapping the narrator
    at an ordinary ~3 taps/sec had every second REAL poke discarded, so Triggered wanted
    about ten taps instead of five, while this docstring, the route's, and useFolio.js's
    all claimed separate clicks were never touched. Narrowed to 150ms the same day: a
    double-fired DOM event arrives inside a few milliseconds, and a hand cannot tap the
    same control twice inside 150ms, so the window now catches what those comments say it
    catches. Faster than a hand, not faster than a bug.

    A double fire also means one nonce sent twice -- the twin that loses the race is
    refused 403 as consumed, BEFORE reaching here. That refusal must stay silent on the
    client: gallery/src/notify/achNonce.js (and the Loom shell's own mgAchDocs) refresh and
    retry only when their nonce is missing or older than the 60s window, never on the
    immediate twin, or the retry would arrive with a fresh nonce and count the gesture a
    second time on any round trip slower than this window."""
    now = time.time() if now is None else now
    with _ach_lock:
        prev = _ach_last.get((sid, event))
        if prev is not None and (now - prev) < _ACH_DEBOUNCE_S:
            return True
        _ach_last[(sid, event)] = now
        return False


def _ach_rate_ok(sid, now=None):
    """False once `sid` has spent its 30 beacon calls in the rolling minute. Counts the
    call it admits, so a mint and an event draw on the same budget -- five pokes plus the
    odd refresh is nowhere near it, a scripted replay loop is."""
    now = time.time() if now is None else now
    with _ach_lock:
        _ach_sweep(now)
        hits = [t for t in _ach_rate.get(sid, ()) if now - t <= _ACH_RATE_WINDOW_S]
        if len(hits) >= _ACH_RATE_MAX:
            _ach_rate[sid] = hits
            return False
        hits.append(now)
        _ach_rate[sid] = hits
        return True


# --- The name hunt on the Bookmarked and Mine tabs (owner, 2026-09-07: "search is still
# shit"). Measured that day with the app's own client: the bookmarks operation takes a
# keyword and answers 24 rows that mostly do NOT carry it ("eyes" -> "Special Eyes XL" then
# a page of unrelated titles), and the author-filtered market connection ignores the keyword
# outright (the same four rows for "eyes" and for nothing). So neither tab searched. Both
# lists are the owner's OWN (a few hundred bookmarks, a handful of his LoRAs), so the honest
# search is to walk the list and keep the rows whose title or description carries the words --
# bounded, and the whole answer comes back in one page (no cursor), because a filtered walk
# cannot hand out a cursor that means anything to the next call.
_HUNT_MAX_PAGES = 20


def _hunt_by_name(fetch_page, q, size):
    """Walk `fetch_page(after)` (a callable returning the picker's payload shape: results /
    has_more / next_cursor) and keep the rows whose title or description contains every word
    of `q`, case-insensitively. Stops at the source's end, at _HUNT_MAX_PAGES, or once
    `size * 4` matches are in hand. Answers has_more False: the hunt is one page."""
    words = [w for w in (q or "").lower().split() if w]
    keep, after, pages = [], None, 0
    while pages < _HUNT_MAX_PAGES:
        page = fetch_page(after) or {}
        if page.get("error") and not page.get("results"):
            return page
        for row in page.get("results") or []:
            hay = ((row.get("title") or "") + " " + (row.get("description") or "")).lower()
            if all(w in hay for w in words):
                keep.append(row)
        pages += 1
        if not page.get("has_more") or not page.get("next_cursor") or len(keep) >= size * 4:
            break
        after = page["next_cursor"]
    return {"results": keep, "has_more": False, "next_cursor": "", "hunted_pages": pages}


# ---- The live mirror: when to reconnect, and when to catch up (#60) -------------------------
# PROBE_2026-10-02 (bridge-live-inbox-studio, task 2): PixAI neither idles sockets out nor caps
# their life. Drops are PixAI-side events that end several connections at once, cleanly
# (`complete`) or with no close frame at all, whatever their ping state -- so no keep-alive can
# prevent them. What the app controls is the gap after each one: how long it waits to reconnect,
# and whether it reads back what finished while it was gone. Both decisions are pure functions
# here, driven as tables by dev/tests/test_watch.py.

# A connection that subscribed and then lived at least one heartbeat (core._WS_HEARTBEAT) has
# proved itself; when it ends, the cause is PixAI's, not ours, and the reconnect comes at once.
WATCH_HEALTHY_S = 60
# "At once" in human terms. 1 s, not 0, so that no bug anywhere else can ever spin this loop.
WATCH_RECONNECT_WAIT = 1
# The ladder for everything else (a refused handshake, a drop seconds after subscribing).
WATCH_BACKOFF_FIRST = 5
WATCH_BACKOFF_MAX = 60
# The periodic backstop sweeps every this many seconds, and skips while a SUCCESSFUL sweep is
# younger than it.
WATCH_CATCHUP_MIN_GAP = 300
# No two sweeps start closer than this. A connect-triggered sweep inside it WAITS (it is never
# skipped: its gap is new); a periodic one inside it is skipped (it is only a backstop).
WATCH_SWEEP_FLOOR = 60
# `subscribed` fires when the subscribe frame is SENT. PixAI acknowledges nothing, so when the
# subscription actually starts delivering is unobservable; the sweep waits this long after the
# send before reading. A task finishing in that instant is delivered by the socket once the
# subscription is live, or found by this read, or -- if the subscription took longer than this to
# go live -- by the next periodic sweep. Unlikely, never silent for longer than one backstop.
WATCH_SUBSCRIBE_SETTLE = 2
# A task whose collect failed is left alone this long before a sweep tries it again.
WATCH_COLLECT_RETRY_S = 300


def watch_reconnect_plan(backoff, lived_s):
    """How long to wait before reconnecting, and the backoff to carry: `(wait_s, next_backoff)`.

    `lived_s` is how long the connection lived after it subscribed, or None if it never did.
    A healthy connection (lived >= WATCH_HEALTHY_S) reconnects after WATCH_RECONNECT_WAIT and
    resets the ladder, however it ended -- a clean `complete`, a stale watchdog, or a drop with no
    close frame. Everything else waits the current step and climbs 5/15/45/60. Healthy reconnects
    are therefore at least a minute apart by construction, which is the storm bound."""
    if lived_s is not None and lived_s >= WATCH_HEALTHY_S:
        return WATCH_RECONNECT_WAIT, WATCH_BACKOFF_FIRST
    return backoff, min(backoff * 3, WATCH_BACKOFF_MAX)


def catchup_plan(reason, now, last_started, last_ok, not_before=0.0):
    """Whether the catch-up worker may sweep now: ("run", 0), ("wait", seconds) or ("skip", 0).

    `last_started` is when the previous sweep started (None: never), `last_ok` when the last
    SUCCESSFUL one started (a failed read is not coverage), `not_before` the settle deadline the
    latest subscribe set. All on one monotonic clock.

    A connect-triggered sweep ("startup", "reconnect") is never skipped -- its gap is new, and
    skipping it is how a task that finished during a drop used to wait five minutes for the next
    periodic sweep. It waits for the settle deadline and for WATCH_SWEEP_FLOOR after the previous
    sweep, then reads. The periodic backstop skips while a successful sweep is younger than
    WATCH_CATCHUP_MIN_GAP, or any attempt younger than the floor."""
    if reason == "periodic":
        if last_ok is not None and now - last_ok < WATCH_CATCHUP_MIN_GAP:
            return ("skip", 0)
        if last_started is not None and now - last_started < WATCH_SWEEP_FLOOR:
            return ("skip", 0)
        return ("run", 0)
    wait = (not_before or 0.0) - now
    if last_started is not None:
        wait = max(wait, last_started + WATCH_SWEEP_FLOOR - now)
    return ("wait", wait) if wait > 0 else ("run", 0)


def watch_close_info(exc, redact=None):
    """How a live connection ended, from the exception that ended it, for the status record and
    the log. A websockets ConnectionClosed carries the Close frame it received (`rcvd`) and sent
    (`sent`): none either way is an abrupt drop ("no close frame received or sent"), today's usual
    kind. Anything else is an error before or around the socket. `redact` is create_app's
    host-path redactor, applied to the close reason. Never raises."""
    try:
        if hasattr(exc, "rcvd") and hasattr(exc, "sent"):
            frame = exc.rcvd or exc.sent
            if frame is None:
                return {"kind": "abrupt", "code": None, "reason": ""}
            return {"kind": "closed", "code": getattr(frame, "code", None),
                    "reason": (redact or str)(str(getattr(frame, "reason", "") or ""))[:80]}
    except Exception:                              # noqa: BLE001
        pass
    return {"kind": "error", "type": type(exc).__name__}


class _PerRequestSecureSessions(SecureCookieSessionInterface):
    """Flask's signed-cookie sessions, with the cookie's Secure flag taken from the request
    that sets it: Secure over HTTPS, not over this PC's plain-HTTP loopback (see create_app)."""

    def get_cookie_secure(self, app):
        try:
            return bool(request.is_secure)
        except RuntimeError:                       # no request (never, in save_session)
            return bool(app.config.get("SESSION_COOKIE_SECURE"))


def create_app(out_dir: Path):
    # Both named explicitly, because Flask's defaults are this MODULE's folder and both
    # belong to the app folder (moonglade.paths), wherever the module sits: root_path is
    # what send_from_directory()/send_file() join a RELATIVE path onto -- the default
    # library, `pixai_backup`, is one -- and static_folder serves /static/.
    app = Flask(__name__, root_path=str(_paths.APP_ROOT),
                static_folder=str(_paths.static_dir()))

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
    # logger either; moonglade.logs.setup_logging() configures the root logger.
    import logging as _logging
    try:
        from moonglade import backup as _core
        _swept = _jobs.resolve_interrupted_local_jobs(out_dir)
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
    from moonglade import backup as _core_auth
    app.secret_key = _core_auth.get_or_create_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS can never read the session cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # blocks cross-site POST/nav CSRF vectors
    # Secure PER REQUEST (2026-11-19): the cookie is marked Secure whenever the request that
    # sets it came over HTTPS -- every other device on the home network since moonglade.tls --
    # so a browser never sends it back over plain http://. This PC's own loopback may stay
    # plain HTTP, and a Secure cookie set there would be dropped by the browser and break
    # sign-in, so the flag follows the request rather than one app-wide setting.
    app.session_interface = _PerRequestSecureSessions()
    import datetime as _dt
    app.permanent_session_lifetime = _dt.timedelta(days=SESSION_IDLE_LIFETIME_DAYS)
    # The app-wide body ceiling (finding 9): routes that take big files raise it for themselves.
    app.config["MAX_CONTENT_LENGTH"] = REQUEST_MAX_BYTES
    # Which plain-HTTP visits the request gate sends to https:// (moonglade.tls's TLS_* names).
    # main() sets it from the listener it opened; a test sets it to try a mode.
    app.config.setdefault("MG_TLS_MODE", "off")
    app.config.setdefault("MG_TLS_FINGERPRINT", "")

    db_path = out_dir / "catalog.db"
    build_stamp = _build_stamp()
    init_db(db_path)
    migrate(db_path)          # say the schema upgrade out loud at the entry point --
                              # catalog() would do it lazily anyway, and the per-process
                              # memo makes this call free for every later open
    _telemetry.set_telemetry_out(out_dir)     # bare telem_* bumps land in this install's ledger
    backfill_batches(out_dir, db_path)
    thumb_dir = out_dir / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    _branding.ensure_branding_discovery_tree()   # the empty slot folders, created if absent
    # Banner renders are brought up to date ONCE, here, rather than lazily on a
    # request: /branding/<flat> is PUBLIC tier, and an anonymous LAN GET must not
    # be able to schedule a decode-crop-resize-save. Ordered after the scaffold
    # so a legacy install's role tree has already been folded into the coded
    # dirs, and after main()'s root-flat migration (which runs before create_app)
    # so a just-migrated flat is already stamped 'migrated' and is left alone.
    # Regenerates only a MISSING render or one whose record says its slot's pick
    # moved -- see _ensure_banner_flat.
    _branding._ensure_banner_renders(out_dir, db_path=db_path)
    # NOTE: two startup steps are deliberately NOT here, both because they write
    # somewhere branding_root() addresses rather than somewhere out_dir does, and
    # create_app() is called by ~every test with the tree unpatched: the root-flat
    # migration (_migrate_root_banner_flats), which MOVES a real render out of the
    # real coded tree, and the slot-pick record (_record_slot_resolution), which
    # rewrites settings.json's branding slots. Both run from main(), the one place
    # that knows this is a real server start. The ensure pass above only READS
    # those picks; everything it writes is under out_dir.
    #
    # The scaffold call above is additive; its ONE known exception is the
    # legacy-root migration it runs first (_migrate_legacy_branding_root), which
    # folds a pre-coded-tree install's own role-named `branding/` tree into the
    # coded dirs -- a move, never a delete, and the reason that migration is
    # described as additive-or-move-only. It predates this rule and stays here
    # because an install that still has that old tree is unusable until it runs.
    # Nothing else create_app() does relocates a file in the coded tree.

    # -- split: routes_gate (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import routes_gate as _routes_gate
    ctx = _SimpleNamespace(
        build_stamp=build_stamp,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_gate.register(app, ctx)
    MIRROR_CONNECT_PAGE = ctx.MIRROR_CONNECT_PAGE
    _account_is_member = ctx._account_is_member
    _ach_sid = ctx._ach_sid
    _check_csrf = ctx._check_csrf
    _csp_nonce = ctx._csp_nonce
    _entitlements = ctx._entitlements
    _gen_session = ctx._gen_session
    _input_media_id = ctx._input_media_id
    _is_local_request = ctx._is_local_request
    _noncify = ctx._noncify
    _note_power_request = ctx._note_power_request
    _redact_host_paths = ctx._redact_host_paths
    # -- end --

    # -- split: web_threads (split_move) --
    from moonglade import web_threads as _web_threads
    ctx = _SimpleNamespace(
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _web_threads.register(app, ctx)
    PANEL_ACTIONS = ctx.PANEL_ACTIONS
    _LIVING_STALE_ACTIONS = ctx._LIVING_STALE_ACTIONS
    _artworks_job_busy = ctx._artworks_job_busy
    _artworks_kick = ctx._artworks_kick
    _asset_job = ctx._asset_job
    _collect_single_flight = ctx._collect_single_flight
    _export_dir = ctx._export_dir
    _export_job = ctx._export_job
    _export_lock = ctx._export_lock
    _job_busy = ctx._job_busy
    _living_runnable = ctx._living_runnable
    _load_sched = ctx._load_sched
    _log_job = ctx._log_job
    _panel_job = ctx._panel_job
    _panel_lock = ctx._panel_lock
    _panel_run = ctx._panel_run
    _reconcile_orphan_jobs = ctx._reconcile_orphan_jobs
    _save_sched = ctx._save_sched
    _sched_lock = ctx._sched_lock
    _standing_action = ctx._standing_action
    _standing_runnable = ctx._standing_runnable
    _task_stream = ctx._task_stream
    _update_busy = ctx._update_busy
    _update_busy_refusal = ctx._update_busy_refusal
    _watch_lock = ctx._watch_lock
    _watch_status = ctx._watch_status
    # -- end --

    # Bulk cloud-delete runs OFF-THREAD (it's irreversible and can be many network calls)
    # and reports to the Activity card via the job log. Single-flight so two runs can never
    # interleave their deletes.
    _bulkdel_lock = threading.Lock()
    _bulkdel_running = {"on": False}

    @app.route("/api/health")
    @tier(LOGIN)
    def api_health():
        """The health dashboard's data as JSON -- gap-audit route #10, consumed by the
        React app's HealthOverlay (the in-app modal that replaces bouncing to the
        /health page). Same computation, same fields, same LOGIN tier as the page it
        un-bakes; the page route stays until demolition.

        THE CACHE IS health_cached() (module level -- see its own block for the reasoning):
        keyed on the CATALOG FILE with no time floor, serve-stale-while-recomputing, and
        primed off-thread at boot. It replaced the 120s TTL this route carried from
        2026-08-06, which was stale in one direction (a change made 5s ago stayed invisible
        for two minutes) and cold in the other (a first open after two idle minutes paid the
        whole walk with the user watching). The cache still lives OUTSIDE
        collection_health(), as it always has, so every direct caller -- the classic /health
        page, the tests -- gets a pure, uncached computation. ?fresh=1 bypasses; the client
        sends it on an explicit user refresh, never on a plain open."""
        return jsonify(_health.health_cached(out_dir, db_path,
                                     fresh=bool(request.args.get("fresh"))))

    # ---- Health's Broken files list (Session W, the Archive Integrity Handoff) ----
    # The list reads the last integrity check's report (moonglade.integrity.broken_list);
    # the owner's Mark lost / Keep as is are a local flag beside it (integrity_marks.json).
    # Neither touches a file, a catalog row or PixAI.

    @app.route("/api/integrity/broken")
    @tier(LOGIN)
    def api_integrity_broken():
        """The Broken files list: the last check's broken rows with each one's pill, the one
        action that applies, its chip and its local mark, plus what Fix all would do.
        `read_only` says whether re-downloads are off (READ_ONLY in config.json)."""
        from moonglade import backup as core
        from moonglade import integrity as moonglade_integrity
        doc = moonglade_integrity.broken_list(out_dir, db_path,
                                              avg_bytes=_health.health_avg_file_bytes())
        doc["read_only"] = bool(core.READ_ONLY or core._read_only_now())
        doc["run"] = _fix_runner.status()
        return jsonify(doc)

    @app.route("/api/integrity/mark", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_mark():
        """Mark lost / Keep as is / Undo: set one broken row's local mark ("lost", "kept",
        or "" to clear it) and answer the mark it had before, which Undo sends back. Only a
        row on the list can take a mark; clearing is allowed for any row that has one.
        Body: {csrf, media_id, mark}."""
        from moonglade import integrity as moonglade_integrity
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        mid = str(body.get("media_id") or "").strip()
        mark = str(body.get("mark") or "")
        if mark not in ("",) + moonglade_integrity.MARKS:
            return jsonify({"error": "That isn't a mark this list keeps."}), 400
        if mark and mid not in moonglade_integrity.listed_ids(out_dir):
            return jsonify({"error": "That file isn't on the Broken files list."}), 400
        if not mark and mid not in moonglade_integrity.read_marks(out_dir):
            return jsonify({"ok": True, "media_id": mid, "mark": "", "prev": ""})
        try:
            prev = moonglade_integrity.set_mark(out_dir, mid, mark)
        except (ValueError, OSError) as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 400
        return jsonify({"ok": True, "media_id": mid, "mark": mark, "prev": prev})

    # The fix run: moonglade.integrity.FixRunner, one per server, on its own thread so closing
    # Health never stops it. It refuses an archive-only row BY ITSELF (redownload_one reads the
    # catalog, whatever the client sent), READ_ONLY blocks its re-downloads but not its local
    # thumbnail rebuilds, and it deletes nothing. Test seam: app.extensions["mg_integrity_fix"].
    from moonglade import integrity as _integ
    _fix_runner = _integ.FixRunner(out_dir, db_path, log_job=_log_job)
    app.extensions["mg_integrity_fix"] = _fix_runner

    @app.route("/api/integrity/fix", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_fix():
        """Start a fix run over the chosen rows: one per-row Re-download / Rebuild, or Fix all
        recoverable. Body: {csrf, items: [{media_id, action}, ...]} -- every row with the action
        the list SHOWED ("redownload" or "rebuild"), which the runner holds it to: a file that
        changed since the check runs nothing (review finding 3). Rows not on the Broken files
        list come back in `refused`; 409 while a run is going. Answers the run's status with
        `started`."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        items = body.get("items")
        if (not isinstance(items, list) or not items
                or not all(isinstance(it, dict) and str(it.get("media_id") or "").strip()
                           and it.get("action") in _integ.FIX_ACTIONS for it in items)):
            return jsonify({"error": "No files were chosen."}), 400
        st = _fix_runner.start(items[:5000])
        if st is None:
            return jsonify({"error": "A fix is already running.", "busy": True}), 409
        st["started"] = bool(st["running"])
        return jsonify(st)

    @app.route("/api/integrity/fix/status")
    @tier(LOGIN)
    def api_integrity_fix_status():
        """The fix run as it stands: n / N, the current row's bytes, every result so far."""
        return jsonify(_fix_runner.status())

    @app.route("/api/integrity/fix/stop", methods=["POST"])
    @tier(LOGIN)
    def api_integrity_fix_stop():
        """Stop: the current file finishes, then the run ends. Nothing is rolled back."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        _fix_runner.stop()
        return jsonify({"ok": True})

    @app.route("/api/panel/summary")
    @tier(LOGIN)
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
        from moonglade import backup as core
        session.setdefault("csrf", secrets.token_hex(16))
        try:
            _branding.sweep_branding_drops(out_dir)   # see api_branding()'s own GET for why
        except Exception:
            pass
        branding = _branding.load_branding(out_dir)
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
            # On this PC or a private home network (the reach of Connect from PixAI): the
            # Mirror tile's Disconnect shows for it, not only for the page on 127.0.0.1.
            "home_network": bool(_mirror.home_network_address(request.remote_addr)),
            "actions": actions, "all_actions": all_actions,
            "out_dir": str(out_dir) if panel_is_local else "",
            "web_users": core.list_web_users(),
            "current_username": session.get("user"),
            "csrf": session["csrf"],
            "branding": dict(_branding._branding_tuning(branding),
                             mark=branding["mark"], anim=branding["anim"],
                             anims=_branding.MARK_ANIMS,
                             # The Control Panel reads its marks from HERE, not from
                             # GET /api/branding -- so the earned annotation the two
                             # gated mark grids render off (locked/dimmed) has to be
                             # computed here too, or the lock never shows and a bound
                             # mark only fails on click with a raw 403 toast (red team
                             # 2026-09-08). Same gate as the GET route below.
                             marks=_branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path)),
                             slots=_branding.branding_slots_payload(out_dir),
                             roles=_branding.branding_roles_payload(out_dir)),
        })

    @app.route("/api/users/add", methods=["POST"])
    @tier(LOCALHOST)
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
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
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
    @tier(LOGIN)
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
        from moonglade import backup as core
        result = core.remove_web_user_guarded(username)
        if result == "not_found":
            return jsonify({"error": "No such account."}), 404
        if result == "last_account":
            return jsonify({"error": "Can't remove the last remaining account -- "
                                     "that would lock every remote device out until "
                                     "someone signs in locally to bootstrap a new one."}), 400
        # S10: a removed login's per-login folder (prefs, state, snippets, presets, saved
        # views) goes with it.
        core.remove_login_files(out_dir, username)
        return jsonify({"ok": True, "username": username})

    @app.route("/api/users/password", methods=["POST"])
    @tier(LOGIN)
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
        from moonglade import backup as core
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
    @tier(LOGIN)
    def api_ping():
        """Cheap liveness probe — the Stop/Restart reconnect overlay polls this. Login required
        (any session, local or LAN)."""
        return jsonify({"ok": True})

    @app.route("/api/server/stop", methods=["POST"])
    @tier(LOGIN)
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
        if _update_busy():
            return _update_busy_refusal()
        busy = _job_busy()
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't shut down while it works).".format(busy)}), 409
        _note_power_request("Stop")
        _schedule_server_exit(0)
        return jsonify({"ok": True, "action": "stop"})

    @app.route("/api/library-path", methods=["GET", "POST"])
    @tier(LOGIN, POST=LOCALHOST)
    def api_library_path():
        """Read or set the library folder (settings.json's library_dir).

        LOCALHOST-ONLY on write: it decides which folder every later start opens (and the
        command line and the MCP server with it), so it sits in the same trust class as
        /api/setup/save-key and /api/branding/shortcut. GET is LOGIN -- the Panel shows the
        current folder to whoever can already see the Panel, and it is the same host path
        /panel already withholds from non-local callers, so it is withheld here too.

        Setting this moves nothing by itself, and the old folder is left exactly as it is: it
        points the app at a different folder on the next start, and there is no "migrate"
        option here to get wrong. That next launcher or server start does tidy the new folder
        when it holds an older Moonglade's layout (moonglade.migrate): its records come into
        its _moonglade folder -- only what is Moonglade's by its content; a folder of someone's
        own that merely shares an old name (logs, loom, branding) is left alone. A folder
        that is the program's own, or holds a Moonglade program, is refused here
        (moonglade.migrate.library_refusal), since every start would refuse it too.
        """
        from moonglade import backup as _core
        if request.method == "GET":
            local = _is_local_request()
            # BOTH path fields are withheld from a non-local caller, not just the first.
            # POST stores an ABSOLUTE path, so `stored` is the host path too -- blanking
            # `path` while returning `stored` handed it straight back, defeating the
            # withholding that /panel and this route's own docstring promise. `configured`
            # says whether a folder is set without saying where it is, which is all the
            # Panel needs to decide what to show.
            stored = _settings.library_dir()
            return jsonify({
                "path": str(out_dir) if local else "",
                "stored": stored if local else "",
                "configured": bool(stored),
                "default": DEFAULT_LIBRARY_DIR,
                "local": local,
                "supervised": _supervised(),
            })
        body = request.get_json(silent=True) or {}
        want = str(body.get("path") or "").strip().strip('"')
        if not want:
            return jsonify({"error": "Enter a folder path."}), 200
        try:
            target = Path(want).expanduser()
            # Stored absolute: the server's working directory is the launcher's folder, and
            # a relative path stored here would silently mean somewhere else the moment
            # anything started it from elsewhere (a scheduled task, a terminal, a shortcut).
            target = (target.resolve() if target.is_absolute()
                      else (_paths.run_dir() / target).resolve())
        except (OSError, ValueError) as e:
            return jsonify({"error": "That path isn't usable: {}".format(e)[:160]}), 200
        if target.exists() and not target.is_dir():
            return jsonify({"error": "That path is a file, not a folder."}), 200
        from moonglade import migrate as _migrate
        refused = _migrate.library_refusal(target)
        if refused:
            return jsonify({"error": "That folder can't be a library: {}. Choose a folder of "
                                     "its own.".format(refused)}), 200
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
        # same order /api/setup/save-key follows for the API key. settings.json is written
        # whole under its own lock (moonglade.settings), never config.json.
        try:
            _settings.set_values(**{_settings.LIBRARY_DIR: str(target)})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": "Couldn't save the setting: {}".format(
                _redact_host_paths(str(e)))[:160]}), 200
        has_catalog = (target / "catalog.db").exists()
        return jsonify({"ok": True, "path": str(target), "has_catalog": has_catalog,
                        "supervised": _supervised(), "restart_needed": str(target) != str(out_dir)})

    @app.route("/api/server/restart", methods=["POST"])
    @tier(LOGIN)
    def api_server_restart():
        """Restart the server from the browser. Needs the managed launcher (Moonglade Launcher),
        which relaunches on exit code 42; otherwise the process would just stop. Login required (any session, local or LAN)."""
        if not _supervised():
            return jsonify({"error": "Restart needs the managed launcher — start via "
                                     "'Moonglade Launcher'. (Stop still works.)"}), 409
        # An update restarts the server ITSELF when it is done; a restart in the middle of
        # one would land the process on half-pulled code. (The updater's own restart does
        # not come through here -- see _update_busy.)
        if _update_busy():
            return _update_busy_refusal()
        busy = _job_busy()                       # same rule as Stop -- see api_server_stop
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the server can't restart while it works).".format(busy)}), 409
        _note_power_request("Restart")
        _schedule_server_exit(42)
        return jsonify({"ok": True, "action": "restart"})

    @app.route("/api/update/check")
    @tier(LOGIN)
    def api_update_check():
        """Is a newer release out?

        Two cadences, one answer. In the background the server re-checks roughly hourly
        and announces what it finds (run_update_tick, off the scheduler's existing tick --
        owner ruling 2026-09-04, reversing 2026-09-01's "no background tick anywhere").
        Here, `?fresh=1` is the Control Panel OPENING: it bypasses the 30-minute cache,
        floored at UPDATE_PANEL_FLOOR seconds, so ten opens in a minute still cost GitHub
        one request. Any other caller reads the cache exactly as before.

        Never fails the Panel: an offline machine gets behind:false with the reason
        attached, at 200. See check_for_update for why the failure is not cached.

        This route only ever ANSWERS. Applying an update is /api/update/apply, behind the
        modal's explicit confirm -- nothing here can reach it."""
        from moonglade import backup as core
        if str(request.args.get("fresh") or "").lower() in ("1", "true", "yes"):
            return jsonify(_updater.check_for_update_fresh(core.__version__))
        payload = _updater.check_for_update(core.__version__)
        _updater.note_update_transition(payload)
        return jsonify(payload)

    @app.route("/api/update/status")
    @tier(LOGIN)
    def api_update_status():
        """The phase the apply is in, for the modal to poll:
        idle | backup | pulling | deps | restarting | failed (with the tool's verbatim error).
        `backup` names the catalog copy made before the pull, once it exists.

        The error is redacted on the way OUT, not on the way in: git and pip name real
        paths, and this payload is readable by any logged-in device on the LAN. The
        unredacted copy stays where it belongs -- the server's own console/log."""
        st = _updater.update_state()
        if st.get("error"):
            st["error"] = _redact_host_paths(st["error"])
        return jsonify(st)

    @app.route("/api/update/apply", methods=["POST"])
    @tier(LOGIN)
    def api_update_apply():
        """Pull the new release and restart into it. NEVER SILENT: the modal's explicit
        confirm is required, and this is the CSRF explicit-token class -- a real system
        mutation off one web click, the same class as publish and the user-admin routes.

        Every refusal names its own reason, because "no" without a why is the thing that
        makes a person start deleting files. Each also carries a machine-readable `kind`
        (2026-09-04, Identity Chrome handoff C2) so the modal can PRESENT it correctly
        without guessing from the wording: "busy" means come back in a minute and nothing
        is wrong (a job is running, or an apply already is); "failed" means this install
        will refuse until something is changed. The third presentation the modal has --
        offline -- is not a payload at all: it is the absence of one, decided client-side
        when the request never reached this server. Adding the field rather than
        string-matching the message is deliberate: the reasons below get reworded (three
        of them did in v3.7.2), and a UI keyed to their prose would silently mis-colour
        the next time one does. The gates:
          * confirm + CSRF          -- it was actually asked for, by this session
          * READ_ONLY               -- belt. Not a PixAI spend, but the owner's flag says
                                       "don't change my install", and this changes the
                                       install more than anything else here does
          * supervised              -- without the managed launcher, exit 42 stops the
                                       server instead of relaunching it: an update would
                                       be indistinguishable from "the app vanished"
          * no running panel job    -- same rule Restart uses; a pull under a running job
                                       swaps the code out from under it
          * on master               -- the recovered scope's own out-of-scope rule: a
                                       feature branch is somebody mid-work, not a stale
                                       install
          * no tracked edits        -- the update owns those paths and is about to write
                                       them; --ff-only would refuse anyway, and refusing
                                       here says WHICH files instead of a git error
          * no untracked file at a  -- and ONLY those. A stray folder the release has
            path the update writes     never heard of is not a reason to refuse: real
                                       installs collect them, and blocking on all of them
                                       (as the first live apply did, over a personal
                                       `boop/`) refuses every real machine forever
        The work itself runs off the panel-job slot on its own single-flight thread, so
        the restart it asks for cannot be refused by the job it is itself.

        WHY LOGIN AND NOT LOCALHOST, recorded because this route shells out and is the
        obvious candidate for the stricter tier: it runs FIXED arguments (no part of the
        request reaches a command line) against the owner's own repository over HTTPS,
        and it is deliberately LOGIN per the owner-approved P4 scope -- "every user, one
        click" -- and the Restart precedent it is modelled on, which is LOGIN for the same
        reason: the person who can restart this server should be able to update it."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again.",
                            "kind": "failed"}), 400
        if not body.get("confirm"):
            return jsonify({"error": "confirm required — the update is never applied silently",
                            "kind": "failed"}), 400
        from moonglade import backup as core
        if core.READ_ONLY or core._read_only_now():
            return jsonify({"error": "READ_ONLY is set in config.json — refusing to update "
                                     "this install. Remove it (or set it to false) to allow "
                                     "this.", "kind": "failed"}), 409
        if not _supervised():
            return jsonify({"error": "Updating needs the managed launcher — start via "
                                     "'Moonglade Launcher'. (Without it the server would stop "
                                     "instead of restarting into the new version.)",
                            "kind": "failed"}), 409
        busy = _job_busy()
        if busy:
            return jsonify({"error": "\"{}\" is still running — stop that job first "
                                     "(the code can't change while it works).".format(busy),
                            "kind": "busy"}), 409
        rc, branch = _updater._git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = (branch or "").strip()
        if rc != 0:
            return jsonify({"error": "couldn't read this checkout's branch: "
                                     + _redact_host_paths(branch)[:200],
                            "kind": "failed"}), 409
        if branch != "master":
            return jsonify({"error": "this checkout is on '%s', not master — updating a "
                                     "feature branch is out of scope. Switch to master "
                                     "first." % branch[:60], "kind": "failed"}), 409
        rc, dirty = _updater._git(["status", "--porcelain"])
        if rc != 0:
            return jsonify({"error": "couldn't read this checkout's state: "
                                     + _redact_host_paths(dirty)[:200],
                            "kind": "failed"}), 409
        tracked, untracked = _updater.split_porcelain(dirty)
        if tracked:
            return jsonify({"error": "this checkout has uncommitted changes — the update "
                                     "would overwrite them. In the way: "
                                     + _redact_host_paths(", ".join(tracked[:6])),
                            "kind": "failed"}), 409
        # The release the modal offered, and only that (app security review 2026-11-19,
        # finding 10): the apply fast-forwards to this tag's commit, never master's head.
        # Read from the last check, never fetched here.
        tag = _updater.announced_release()
        if not tag:
            return jsonify({"error": "no release has been announced to this install yet — "
                                     "open the Control Panel so it checks, then try again.",
                            "kind": "failed"}), 409
        cur_v, tag_v = _updater.version_tuple(core.__version__), _updater.version_tuple(tag)
        if cur_v and tag_v and tag_v <= cur_v:
            return jsonify({"error": "this install is already on %s or newer." % tag,
                            "kind": "failed"}), 409
        # Untracked entries are judged against what the update actually brings, not
        # blocked on sight -- see split_porcelain and untracked_in_the_way. This costs a
        # fetch, but only on a checkout that HAS stray files, and only the fetch the apply
        # was about to do regardless.
        ignored_untracked = 0
        if untracked:
            incoming, why = _updater.incoming_paths(tag)
            if incoming is None:
                return jsonify({"error": "couldn't work out what the update brings, so "
                                         "whether your untracked files are in its way is "
                                         "unknown — and this won't guess. git said: "
                                         + _redact_host_paths(why)[:300],
                                "kind": "failed"}), 409
            clash = _updater.untracked_in_the_way(untracked, incoming)
            if clash:
                return jsonify({"error": "an untracked file is where the update needs to "
                                         "write: "
                                         + _redact_host_paths(", ".join(clash[:6]))
                                         + " — move or delete it, then try again.",
                                "kind": "failed"}), 409
            ignored_untracked = len(untracked)
        with _updater._update_lock:
            if _updater._update_state["phase"] not in ("idle", "failed"):
                return jsonify({"error": "an update is already running", "kind": "busy"}), 409
            _updater._update_state.update(phase="backup", error="", at=time.time(), backup="")

        def _restart():
            # The SAME gates the restart route applies, re-checked at the moment it
            # actually happens rather than trusted from a minute ago -- then the same
            # one call it makes. Not a second restart mechanism.
            if not _supervised():
                raise RuntimeError("the managed launcher is gone")
            still = _job_busy()
            if still:
                raise RuntimeError('"%s" started while updating' % still)
            _schedule_server_exit(42)
            _note_server_exit("by the update just applied")

        # The activity log is the ONLY part of this that survives the restart a successful
        # update is about to trigger -- and the only record at all of one that failed while
        # nobody was watching the modal. Redacted like every other LAN-visible string.
        job_id = "update-" + secrets.token_hex(6)

        # ...and if the tree had stray files this update deliberately left alone, the log
        # line says how many. The record has to show that the guard chose to proceed --
        # otherwise "it updated over my files" and "it updated beside my files" leave the
        # same trace, and only one of those is a bug worth chasing.
        label = "Updated Moonglade"
        if ignored_untracked:
            label += " (ignored untracked: %d)" % ignored_untracked

        def _log_update(status, error=""):
            _log_job(job_id, status=status, type="update", label=label,
                     error=(_redact_host_paths(error)[:600] or None))

        threading.Thread(target=_updater.run_update, args=(_restart, tag),
                         kwargs={"log_fn": _log_update,
                                 "backup_fn": lambda: _updater.backup_catalog(db_path)},
                         daemon=True).start()
        return jsonify({"ok": True, "phase": "backup"})

    @app.route("/api/bonjour/status")
    @tier(LOGIN)
    def api_bonjour_status():
        """Live Bonjour/mDNS state for the Control Panel chip: is it broadcasting, under what
        name, at which reachable URLs, and is zeroconf even installed. Login required (local or
        LAN) -- reading the broadcast state is safe for a LAN device; only WRITING the settings
        (below) is localhost-only."""
        from moonglade import bonjour as moonglade_bonjour
        cfg = _settings.server()
        serving = _SERVER_CONTROL.get("serving") or {}
        adv = _SERVER_CONTROL.get("bonjour")
        host = str(serving.get("host") or cfg["host"])
        try:
            port = int(serving.get("port") or cfg["port"])
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        scheme = str(serving.get("scheme") or "http")
        enabled = bool(cfg["bonjour_enabled"])
        name = str(cfg["bonjour_name"])
        broadcasting = bool(adv is not None and adv.active)
        hostname = adv.hostname if broadcasting else moonglade_bonjour.hostname_label(name) + ".local"
        lan_bind = moonglade_bonjour.is_lan_bind(host)
        ip = adv.ip if broadcasting else moonglade_bonjour.lan_ip()
        urls = []
        if lan_bind and ip:
            urls = ["{}://{}:{}/".format(scheme, hostname, port),
                    "{}://{}:{}/".format(scheme, ip, port)]
        return jsonify({
            "enabled": enabled, "broadcasting": broadcasting, "name": name,
            "host": host, "port": port, "scheme": scheme, "hostname": hostname,
            "lan_bind": lan_bind, "lan_ip": ip, "reachable_urls": urls,
            "zeroconf_available": moonglade_bonjour.zeroconf_available(),
            "supervised": _supervised(),
            # HTTPS on the home network (moonglade.tls): the mode this start runs in, the
            # certificate's SHA-256 fingerprint for a device to check its warning against
            # (public, like the certificate itself), and why there is none when there isn't.
            "tls": str(app.config.get("MG_TLS_MODE") or "off"),
            "tls_fingerprint": str(app.config.get("MG_TLS_FINGERPRINT") or ""),
            "tls_problem": str(app.config.get("MG_TLS_PROBLEM") or ""),
        })

    @app.route("/moonglade-ca.crt")
    @tier(PUBLIC)
    def moonglade_ca_certificate():
        """This PC's certificate authority (moonglade.tls), for a phone, tablet or Mac to
        install once so its browser stops warning. PUBLIC: a certificate is public by nature --
        the server hands the same one to every client in every handshake -- and a device
        fetches it before it signs in. The person checks its SHA-256 fingerprint against the
        LAN card on the PC before trusting it. 404 when this start has no HTTPS."""
        from moonglade import tls as _tls_mod
        p = _tls_mod.ca_cert_path()
        if not app.config.get("MG_TLS_FINGERPRINT") or not p.is_file():
            return app.response_class("This Moonglade isn't serving HTTPS, so it has no "
                                      "certificate to install.", status=404,
                                      mimetype="text/plain")
        resp = send_file(str(p), mimetype="application/x-x509-ca-cert", as_attachment=True,
                         download_name="Moonglade-this-PC.crt", max_age=0)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.route("/api/bonjour/settings", methods=["POST"])
    @tier(LOGIN, POST=LOCALHOST)
    def api_bonjour_settings():
        """Write the Bonjour/mDNS settings (settings.json) and apply what can change live.
        Broadcast on/off and the name apply immediately (re-register); the bind host/port are
        launch-time, so those return restart_needed. LOCALHOST-only on write: a LAN device may
        SEE the state but only the server box may change how the server is exposed."""
        from moonglade import bonjour as moonglade_bonjour
        body = request.get_json(silent=True) or {}
        cfg = _settings.server()
        enabled = bool(body["enabled"]) if "enabled" in body else bool(cfg["bonjour_enabled"])
        name = str(body.get("name") if body.get("name") is not None
                   else cfg["bonjour_name"]).strip()
        new_host = str(body.get("host") if body.get("host") is not None
                       else cfg["host"]).strip()
        raw_port = body.get("port", cfg["port"])
        if not name:
            return jsonify({"error": "A name is required."}), 200
        if new_host not in ("127.0.0.1", "0.0.0.0"):
            return jsonify({"error": "Host must be 127.0.0.1 (this machine only) or 0.0.0.0 (LAN)."}), 200
        try:
            new_port = int(raw_port)
            if not (1 <= new_port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Port must be a whole number between 1 and 65535."}), 200
        try:
            _settings.set_values(**{_settings.BONJOUR: {"enabled": enabled, "name": name},
                                    _settings.HOST: new_host, _settings.PORT: new_port})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": "Couldn't save the setting: {}".format(
                _redact_host_paths(str(e)))[:160]}), 200
        # Apply live what needs no rebind: stop, then (re)start if it should be on, using the
        # CURRENTLY-serving host/port -- a host/port CHANGE only takes effect on the next restart.
        serving = _SERVER_CONTROL.get("serving") or {}
        cur_host = str(serving.get("host") or new_host)
        cur_port = int(serving.get("port") or new_port)
        adv = _SERVER_CONTROL.get("bonjour")
        broadcasting = False
        if adv is not None:
            adv.stop()
            if enabled and moonglade_bonjour.is_lan_bind(cur_host):
                broadcasting = adv.start(name, cur_port, str(serving.get("scheme") or "http"))
        restart_needed = (new_host != cur_host) or (new_port != cur_port)
        hostname = adv.hostname if (adv is not None and adv.active) else moonglade_bonjour.hostname_label(name) + ".local"
        return jsonify({"ok": True, "enabled": enabled, "name": name, "host": new_host,
                        "port": new_port, "broadcasting": broadcasting, "hostname": hostname,
                        "restart_needed": restart_needed, "supervised": _supervised()})

    @app.route("/export-csv")
    @tier(LOGIN)
    def export_csv_download():
        """Download the catalog as a CSV -- from the browser you get a real file (Downloads),
        not a copy silently written into the backup folder. Built in memory. Authorized only.

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
        mem = io.BytesIO(catalog_csv_text(rows).encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="text/csv", as_attachment=True,
                         download_name="moonglade-catalog-{}.csv".format(
                             datetime.date.today().isoformat()))

    @app.route("/export-curation")
    @tier(LOGIN)
    def export_curation_download():
        """Download the curation sidecar -- ratings, hand-picked collections and their manual
        order, smart collections, and the personal layer (tags, keeper/reject, notes) -- as
        one JSON file keyed by media id (moonglade/curation_io.py). The same browser
        download as /export-csv beside it, built in memory, never written into the library.
        It goes back in with `--import-curation` (dry run by default)."""
        import io
        import datetime
        from moonglade import curation_io as cio
        mem = io.BytesIO(cio.dumps(cio.export_curation(db_path)).encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="application/json", as_attachment=True,
                         download_name="moonglade-curation-{}.json".format(
                             datetime.date.today().isoformat()))

    @app.route("/api/panel/run", methods=["POST"])
    @tier(LOGIN)
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
        # The mirror of the apply route's own job check: code must not change under a
        # running job, and a job must not start under a changing codebase.
        if _update_busy():
            return _update_busy_refusal()
        # The published-artwork sweep writes the same catalog rows these jobs do, and it is
        # in-process rather than in the job slot, so _panel_run refuses one while the other
        # is in flight. The refusal is re-stated here only so the click gets a reason it can
        # read: _panel_run answers False for "the slot is taken" too, and "a job is already
        # running" would be the wrong sentence for a sweep that has no slot.
        if action in _living.ARTWORKS_TOUCHING_ACTIONS and _living.artworks_sweep_in_flight():
            return jsonify({"error": "the published-artwork sweep is reading PixAI into "
                                     "these same rows right now — wait a moment and press "
                                     "Run now again"}), 409
        try:
            # `n` is only consumed by an int_param action (test-pull); _panel_run
            # clamps it into range and ignores it otherwise, so passing it always is safe.
            # The busy check lives INSIDE _panel_run, under the same lock that claims the
            # slot -- checking it here first would just be the race again.
            # THE FOLLOW-ON IS A PROPERTY OF THE ACTION, not of who started it. The wiki
            # states the chain as a plain fact about Sync now -- "the one-shot refresh,
            # then a perceptual-hash backfill straight after it" -- and it was true only
            # when the living library's own tick was the trigger. A click got the sync
            # alone. Looked up from the same table _living_run reads, so there is one
            # answer to "what follows this job".
            if not _panel_run(action, int_arg=body.get("n"),
                              then=_living.LIVING_BY_ACTION.get(action, {}).get("then")):
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
            from moonglade import backup as _core
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            orig = jobs_by_id.get(tid)
            if orig and not orig.get("dismissed") and orig.get("status") not in _jobs._JOBS_TERMINAL:
                _log_job(tid, status="done", media_ids=media_ids, is_video=is_video)
        except Exception:                          # noqa: BLE001 -- bookkeeping must not break recovery
            pass

    @app.route("/api/import-task", methods=["POST"])
    @tier(LOGIN)
    def api_import_task():
        """Pull ONE generation/edit task's media into the gallery by its task id -- recovers
        edits + anything stuck in Favorites that --update's listing skips (edits aren't in that
        listing). Downloads the owner's OWN finished media; spends nothing.

        LOGIN tier, deliberately -- any signed-in session, local or LAN. This docstring
        used to say "Localhost-only", which was never true of the code and is exactly the
        bait a route-gating audit warned about: a stale claim like this invites someone to
        "restore" a gate that was never there, silently breaking the LAN-recovery case.
        The real tier is pinned by dev/tests/test_route_tiers.py.

        Logs to the Activity card. Returns {saved, media_ids, is_video} or {error}."""
        tid = str((request.get_json(silent=True) or {}).get("task_id") or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "enter a numeric task id"}), 200
        # "Look behind the milk": if this task is already catalogued, don't re-fetch --
        # just report it's here + hand back its media so the UI can jump straight to it.
        pre_rows = task_media(db_path, tid)
        if pre_rows:
            pre = [r["media_id"] for r in pre_rows]
            _close_orphan_if_resolved(tid, pre, bool(pre_rows[0]["is_video"]))
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
    @tier(LOGIN)
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
        therefore correctly stays LOGIN (dev/tests/test_route_tiers.py).

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
                            # "stop" | "restart" while one is under way, else "" (#84): the
                            # panel resumes its reconnect watch from this on mount.
                            "power": _power_in_progress(),
                            "lines": lines})

    @app.route("/api/watch/status")
    @tier(LOGIN)
    def api_watch_status():
        """Live-mirror watcher health: is the push WebSocket connected right now, when
        did it last see an event, how many gens has it mirrored this server run."""
        with _watch_lock:
            out = dict(_watch_status)
            out["task_stream"] = dict(_watch_status["task_stream"])
            return jsonify(out)

    @app.route("/api/panel/cancel", methods=["POST"])
    @tier(LOCALHOST)
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
    @tier(LOGIN, POST=LOCALHOST)
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
                if "jobs" in body:
                    # THE LIVING LIBRARY'S LIST. A PATCH, exactly like every other field
                    # here: the client sends only the rows it is changing, and only the
                    # two things it may change -- whether a job runs by itself, and how
                    # often. `action` and `last_run` are never taken from the body: an
                    # unknown action is dropped by living_merge (the shipped list is the
                    # only list), and a client that could write last_run could make a
                    # sixty-day staleness job fire on demand.
                    rows = {r["action"]: r for r in s["jobs"]}
                    for patch in (body.get("jobs") or []):
                        if not isinstance(patch, dict):
                            continue
                        row = rows.get(str(patch.get("action") or ""))
                        if not row:
                            continue
                        if "enabled" in patch:
                            row["enabled"] = bool(patch.get("enabled"))
                        if "interval_s" in patch:
                            # THE FLOOR IS ENFORCED HERE, not in the browser. The Panel
                            # renders no cadence selector for a staleness job -- but a
                            # POST is not the Panel, and living_clamp_interval is the one
                            # place that knows sixty days is a floor rather than a
                            # default. A patch asking for a full re-walk every minute
                            # comes back clamped, saved clamped, and answered clamped.
                            row["interval_s"] = _living.living_clamp_interval(
                                row["action"], patch["interval_s"],
                                default=row.get("interval_s"))
                            # the owner's own pick: a later default change never moves it
                            # (living_merge, LIVING_RETIRED_DEFAULTS)
                            row["chosen"] = True
                if not _standing_runnable(s.get("action")):
                    # ADVANCED IS REFUSED HERE TOO, not only at the tick. The tick has
                    # always skipped an advanced action -- a full re-walk on a six-hour
                    # timer is a foot-gun, and test-pull needs an N this path cannot
                    # supply -- but the save route did not, so the pair could be SAVED
                    # and then never run by anyone: _living_tick stood aside for a
                    # standing order that refuses the job, and the Panel said "the
                    # standing order below runs this one" about a job neither path would
                    # ever start. Both halves say the same thing now.
                    return jsonify({"error": "only safe jobs can be scheduled — a full "
                                             "re-walk, an inventory count and a test pull "
                                             "stay in Advanced, by hand"}), 400
                _save_sched(s)
            # `catalog` is what the Panel draws the "runs itself" rows from: the shipped
            # label, note and cadence beside each saved row, so the client never has to
            # keep its own copy of the job list (and never disagrees with the server's).
            #
            # `deferred` is the honest half of a collision the tick has always handled
            # silently: the legacy standing order still owns whatever action it names, so
            # _living_tick skips that action's row -- correctly, since two paths starting
            # one job would just take turns losing the single Panel slot. But the row went
            # on displaying its own cadence and its own "next in 3h", which is a schedule
            # it is NOT running. The skip stays; the row now says why.
            #
            # Read through _standing_action, the same function the tick defers by, so the
            # row and the tick can never disagree: a standing order naming a job that path
            # refuses to start owns nothing, and the row is not marked deferred to it.
            standing = _standing_action(s)
            return jsonify(dict(s, catalog=[
                {"action": j["action"], "label": j["label"], "note": j["note"],
                 "default_interval_s": j["interval_s"],
                 "stale": j["action"] in _LIVING_STALE_ACTIONS,
                 "needs_torch": j.get("needs") == "torch",
                 "deferred": j["action"] == standing,
                 "available": _living_runnable(j["action"])
                              and (j.get("needs") != "torch" or _living._torch_present())}
                for j in _living.LIVING_ALL]))

    @app.route("/api/panel/sweep", methods=["POST"])
    @tier(LOCALHOST)
    def api_panel_sweep():
        """RUN NOW for the published-artwork sweep -- the one living job that is not a
        PANEL_ACTIONS key, because it runs in-process (the CLI's --sync-artworks is the
        full re-walk and has no short-circuiting equivalent to spawn).

        LOCALHOST for the same reason /api/panel/schedule's writes are: this starts real,
        paced PixAI traffic on the owner's own credentials, and a logged-in LAN session
        unlocks browsing, not background work on his account. Forced -- the owner pressing
        Run now is asking past the fifteen-minute guard, exactly as the publish kick does.

        Answers immediately; the sweep runs off-thread and announces itself through the
        Activity ledger if it changed anything. It never touches the page the owner is
        looking at.

        `deferred` names the catalog-writing Panel job that held the sweep off, when one
        did (_artworks_job_busy) -- so an ok:false is never a silent nothing.

        NOT `scheduled`, and it is the only one of the four triggers that is not: this is a
        button the owner pressed, so it still toasts when it finishes, exactly like every
        other job he starts himself (owner's walk, 2026-09-07)."""
        deferred = _artworks_job_busy()
        return jsonify({"ok": bool(_artworks_kick(force=True)),
                        "deferred": deferred,
                        "action": _living.LIVING_SWEEP_ACTION})

    def _batch_sibling_count(task_id):
        """How many catalog rows share this task, for the Details view's own display.

        NOT what the delete dialog is worded from -- that has to come from the live read
        (/api/delete-image with confirm false), because this number counts LOCAL rows and
        cannot see a sibling deleted from PixAI's own website."""
        return task_media_count(db_path, task_id)

    def _delete_image_rows(plan, task_id, media_id):
        """Which catalog rows this delete takes with it, as [{media_id, filename}].

        Per-image: the one named image. Whole-task: every row of the task EXCEPT the ones
        whose image PixAI had already deleted -- their local copy is the only copy left
        anywhere, and removing the generation record on PixAI does not change that. The
        branch comes off the plan the delete itself reported, never off a local count."""
        if plan.plan == "per-image":
            row = get_row(db_path, media_id) or {}
            return [{"media_id": media_id, "filename": row.get("filename") or ""}]
        if plan.plan == "whole-task":
            keep = {str(m) for m in plan.keep_media}
            return [{"media_id": str(r["media_id"]), "filename": r.get("filename") or ""}
                    for r in task_media(db_path, task_id)
                    if str(r["media_id"]) not in keep]
        return []

    def _delete_image_message(plan, rows, task_id=""):
        """The dialog's own words, in plain language, off the live read.

        Every number here is PixAI's answer about this task, never a count of local rows --
        save one fallback: when the live read carried no artworkIds at all, whether the
        generation is published comes from the catalog's artwork_id over the task's whole
        membership (SCOPE_2026-09-26 E5). Only the whole-task branch says anything about
        published artwork: that branch sends the whole-task delete, the delete PixAI's
        contract says takes the linked artwork with it. What a one-image deleteBatchMedia
        does to an artwork is unknown, so the per-image branch makes no claim."""
        if plan.plan == "per-image":
            n = plan.live_siblings
            return ("This removes only this image from PixAI. {} other image{} in its "
                    "batch stay.".format(n, "" if n == 1 else "s"))
        if plan.plan == "whole-task":
            names = [Path(r["filename"] or r["media_id"]).name for r in rows]
            shown = ", ".join(names[:6]) + (
                " and {} more".format(len(names) - 6) if len(names) > 6 else "")
            msg = ("This is the last image of its generation on PixAI, so PixAI removes "
                   "the whole generation record. Locally, {} file{} move{} to your trash "
                   "folder: {}.".format(len(names), "" if len(names) == 1 else "s",
                                        "s" if len(names) == 1 else "", shown))
            if plan.keep_media:
                msg += (" The {} image{} of this generation you already deleted on PixAI "
                        "stay here — your copy is the only one left.".format(
                            len(plan.keep_media),
                            "" if len(plan.keep_media) == 1 else "s"))
            members = task_media(db_path, task_id) if task_id else []
            if plan.artwork_ids is not None:
                # Capped at the task's size ON PIXAI, never at the rows this library holds:
                # the delete takes PixAI's whole batch, and a library missing some of its
                # images must not under-count what may go with it. On this branch that batch
                # is this, the last live image, plus every member already deleted there.
                published = min(len(plan.artwork_ids),
                                max(1, len(members), len(plan.keep_media) + 1))
                unchecked = False
            else:
                published = sum(1 for r in members if str(r.get("artwork_id") or "").strip())
                unchecked = not myart_coverage(db_path)["artworks"]
            note = published_delete_note(published, unchecked)
            if note:
                msg += " " + note
            return msg
        return plan.reason

    @app.route("/api/delete-image", methods=["POST"])
    @tier(LOCALHOST)
    def api_delete_image():
        """Delete ONE image from its task on PixAI -- in TWO phases, ask then act.

        The finer-grained partner to /delete-tasks-bulk, which is task-level: deleting any
        image there takes the whole batch. Same trust tier and for the same reason --
        LOCALHOST-only, because this destroys on the owner's real cloud account, and a
        logged-in LAN session unlocks browsing and spending, not irreversible deletion.

        `POST {media_id, confirm: false}` is the PREVIEW: it reads the live task and answers
        `{plan, reason, live_siblings, local_rows, message}` with nothing deleted. The dialog
        is worded from THAT answer. It has to be: which mutation PixAI accepts, and how many
        images of the batch survive, are facts only PixAI holds -- the local catalog cannot
        see a sibling deleted from PixAI's own website, and for years this dialog promised
        "the rest of its batch stays" on deletes that took the whole generation.

        `POST {media_id, confirm: true, plan}` DELETES. It reads and routes again, and
        refuses when the fresh plan differs from the one the dialog showed, so the user
        cannot be made to agree to one thing and get another. `confirm` must be present
        either way: the typed-DELETE prompt is the client's half of the same gate, and a
        route that acted on a body without it would make that prompt decorative.

        Local purge follows the cloud delete, exactly as the task-level path does, so cloud
        and catalog never drift. Order matters: if the cloud call fails, nothing local is
        touched and the image is still there to try again. WHICH rows go is the plan's to
        say (`_delete_image_rows`), never this route's to re-derive from local counts.

        A CONFIRMED delete writes one Activity row (`del-<hex>`, `type: "delete"`) -- owner's
        walk 2026-09-07, "single delete did NOT show in the Activity tracker". A bulk delete
        has written one since it existed (`_start_bulk_delete`'s `bulkdel-<hex>`), so the
        finer-grained partner writes the same kind of row for the same event, and this
        library's whole record of what left it stops depending on which button was used. The
        PREVIEW writes nothing: nothing happened, and a row per dialog-open is noise.
        """
        from moonglade import backup as core          # lazy: avoid import cycle
        import uuid
        body = request.get_json(silent=True) or {}
        if "confirm" not in body:
            return jsonify({"error": "not confirmed"}), 400
        preview = not body.get("confirm")

        def _log_delete(status, label, error=None):
            """The one Activity row this delete leaves behind.

            Born terminal, unlike the bulk delete's two events: a single delete is one
            mutation and there is no progress to report between them. Everything else follows
            _start_bulk_delete exactly -- `type: "delete"` so the tray labels it Delete, and
            NO `scheduled` field, because the owner pressed this button and a job you press
            toasts its outcome (jobsStore.js's toastTransitions swallows only `scheduled`
            rows). `media_ids` carries the one image so the row can show its thumbnail, and it
            is written BEFORE the local purge, while that thumbnail is still on disk.

            Never on the preview -- callers check that themselves rather than this swallowing
            it, so the one caller that must not log reads as a decision at its own call site.
            """
            _log_job("del-" + uuid.uuid4().hex[:12], status=status, type="delete",
                     label=label, error=error, media_ids=[mid] if mid else None)
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
        if not preview and not str(body.get("plan") or "").strip():
            # A confirm carries the plan it confirms. Without one there is nothing to hold
            # the fresh read against, so it is refused here, before any call to PixAI.
            return jsonify({"error": _cloud_delete.NO_CONFIRMED_PLAN, "plan": "refuse"}), 400
        try:
            # _make_session takes a REQUIRED positional; every other call site in this
            # file passes None. Omitting it raised TypeError on every click, which the
            # except below turned into a 200 error body -- so the feature was dead while
            # looking like a PixAI-side failure.
            _core_session = core._make_session(None)
            if preview:
                plan = _cloud_delete.plan_image_delete(_core_session, tid, mid)
            else:
                plan = _cloud_delete.delete_image_routed(_core_session, tid, mid,
                                                confirmed_plan=body.get("plan") or None)
        except Exception as e:                        # noqa: BLE001
            line = _redact_host_paths(str(e))[:240]
            if not preview:
                # A delete he pressed that came back with an error is exactly the outcome the
                # tracker must not be silent about -- READ_ONLY, a PixAI 500, a lost token.
                _log_delete("failed", "PixAI delete failed", error=line)
            return jsonify({"error": line}), 200

        # The read this plan was made from is the only place the app learns that PixAI has
        # dropped an image, so every row it names is marked here -- on the preview as much as
        # on the confirm, and whichever branch the plan took. Nothing local is removed by it:
        # a marked row is one whose local copy is now the only copy anywhere, and it stays.
        # It cannot be left to --backfill-full-meta, which only re-fetches a row missing its
        # prompt or model detail: a complete row is never revisited, so in the ordinary case
        # that pass would never set this at all.
        for gone_media, when in plan.keep_media_deleted_at:
            mark_cloud_deleted(db_path, gone_media, when)

        if plan.plan == "refuse":
            answer = {"plan": "refuse", "reason": plan.reason, "live_siblings": 0,
                      "local_rows": [], "message": plan.reason}
            if not preview:
                answer["error"] = plan.reason
                # A refusal is a real outcome of a button he pressed, not a non-event: the
                # image is still on PixAI and the row says in the plan's own words why.
                _log_delete("failed", "Refused: " + plan.reason, error=plan.reason)
            return jsonify(answer), 200

        rows = _delete_image_rows(plan, tid, mid)
        if preview:
            return jsonify({"plan": plan.plan, "reason": plan.reason,
                            "live_siblings": plan.live_siblings,
                            "local_rows": [r["media_id"] for r in rows],
                            "message": _delete_image_message(plan, rows, tid)})

        # The cloud delete has already fired and cannot be taken back, so the row goes in now
        # -- what it records is what PixAI did, in the plan's own words. A local purge that
        # fails afterwards is a different fact and comes back through this route's own error
        # contract; it does not make the PixAI delete un-happen, so it does not rewrite this.
        _log_delete("done", "Deleted 1 image from PixAI" if plan.plan == "per-image"
                    else "Deleted the whole generation from PixAI (last image)")

        purged, failed = [], []
        for r in rows:
            try:
                purge_media_local(out_dir, thumb_dir, db_path, r["media_id"], r["filename"])
                purged.append(r["media_id"])
            except OSError as e:
                # The cloud delete above already happened and cannot be taken back, so a
                # local purge that fails has to come back through this route's own error
                # contract rather than a 500: the row (and the file) are still here, now
                # pointing at an image PixAI no longer has, and only the user can decide to
                # retry. The loop keeps going -- one file the OS will not release must not
                # strand the rest of a whole-task purge.
                failed.append(_redact_host_paths(str(e))[:160])
        try:                                     # The Great Sweep: each removed picture once
            _telemetry.telem_set_add_many("culled_keys", ["media:" + m for m in purged], out_dir=out_dir)
        except Exception:                        # noqa: BLE001
            pass
        if failed:
            return jsonify({"error": "Deleted on PixAI, but {} local file{} could not be "
                                     "moved to the trash folder: {}".format(
                                         len(failed), "" if len(failed) == 1 else "s",
                                         "; ".join(failed[:3])),
                            "plan": plan.plan, "local_rows": purged}), 200
        return jsonify({"ok": True, "media_id": mid, "task_id": tid, "plan": plan.plan,
                        "local_rows": purged})

    @app.route("/api/delete-local", methods=["POST"])
    @tier(LOGIN)
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
        `failed` count with ok=false instead of a delerr banner.

        ARCHIVE-ONLY PICTURES: WARN, DON'T BLOCK (#66; the owner's ruling on the 2026-10-03
        walk -- keeping them back was tedious). A row PixAI no longer has (is_archive_only)
        holds the only copy anywhere, and it goes with the rest: the Trash's Restore puts the
        file AND its whole catalog row back (restore_quarantined_media, from the snapshot
        purge_media_local writes first). What the bulk confirm needs is the count BEFORE it
        asks, so `preview: true` answers {"preview": true, "count", "archive_only"} -- the rows
        the delete would take and how many of them are the only copy -- and touches nothing."""
        body = request.get_json(silent=True) or {}
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        if body.get("preview") is True:
            rows = [r for r in (get_row(db_path, m) for m in media_ids) if r]
            return jsonify({"preview": True, "count": len(rows),
                            "archive_only": sum(1 for r in rows if is_archive_only(r))})
        purged, failed = [], 0
        for mid in media_ids:
            row = get_row(db_path, mid)
            if not row:
                continue
            try:
                purge_media_local(out_dir, thumb_dir, db_path, mid, row.get("filename"))
                purged.append(mid)
            except OSError:
                failed += 1
        try:              # The Great Sweep: each removed picture once (a restore + re-delete is one)
            _telemetry.telem_set_add_many("culled_keys", ["media:" + m for m in purged], out_dir=out_dir)
        except Exception:                                    # noqa: BLE001
            pass
        return jsonify({"ok": failed == 0, "count": len(purged), "failed": failed})

    def _purge_local(media_id, filename):
        """Remove a media's catalog row + thumbnail; quarantine its file to _deleted/
        (recoverable) rather than destroying it."""
        purge_media_local(out_dir, thumb_dir, db_path, media_id, filename)

    def _rows_the_bulk_purge_must_keep(session, task_id, rows):
        """Which of one task's local rows the bulk delete must leave exactly where they are.

        The same rule the single-image path follows through ImageDeletePlan.keep_media, and
        it is here for the same reason: an image the owner deleted on PixAI's own website is
        gone THERE, so this library's copy is the only one left anywhere. PixAI removing the
        generation record does not change that, and neither does deleting its siblings --
        so those rows and their files stay, and the whole-task purge walks around them.

        Two sources, deliberately both:
          * the live task, read once here. It fails SOFT: a read that could not be made must
            never WIDEN what a purge takes, so a blip leaves the catalog's own answer standing
            rather than replacing it with silence.
          * `cloud_deleted_at` on the rows themselves, which stands whether or not the read
            worked -- it was written the last time the app read this task.

        The read is also where the marker gets WRITTEN: every member PixAI reports deleted
        has its own row stamped here, so the catalog learns it from the read the delete was
        making anyway rather than from a network call of its own.

        Returns a set of media ids. Called BEFORE the cloud delete fires -- afterwards the
        generation record is gone and there is nothing left to read."""
        from moonglade import backup as core   # lazy: avoid import cycle
        keep = {str(r["media_id"]) for r in rows
                if str(r.get("cloud_deleted_at") or "").strip()}
        try:
            task = _task_reads.task_detail_gql(session, str(task_id)) if session is not None else None
        except Exception:                            # noqa: BLE001 -- fail soft, see above
            task = None
        batch = ((task or {}).get("outputs") or {}).get("batch")
        for mid in _cloud_delete.deleted_batch_media(batch):
            keep.add(str(mid))
            stamp = str((_cloud_delete.batch_entry(batch, mid) or {}).get("deletedAt") or "")
            if stamp:
                mark_cloud_deleted(db_path, mid, stamp)
        return keep

    def _preview_live_gone(task_ids):
        """Ask PixAI, once per task, which of these tasks' images it has already dropped.

        The preview's whole job is to say what "Delete from PixAI" would take before it
        fires, and until 2026-09-07 it answered entirely from the local catalog -- which
        cannot know about an image the owner deleted on PixAI's own website. The delete
        itself has always known (_rows_the_bulk_purge_must_keep reads every task and keeps
        those rows back), so the preview over-reported the blast radius against the one
        thing it was supposed to describe exactly. This is that same read, moved forward.

        Read-only ON PIXAI, and it stays that way: getTaskById, nothing else. It does
        write `cloud_deleted_at` on the rows the read finds already deleted, exactly as
        the delete's own read does (mark_cloud_deleted) -- REFINING this function's own
        2026-09-07 note, which held that a confirm dialog the owner may well cancel is no
        place to mutate the catalog from. It is, for this one column. The preview's whole
        promise is "that file stays in your backup, because this is the last copy of it
        anywhere", and a promise made from an answer nobody wrote down is only as good as
        the SECOND read that has to be made at delete time: if that one fails where this
        one succeeded, _rows_the_bulk_purge_must_keep falls back to the catalog, finds
        nothing, and purges the very rows this dialog named. Stamping here makes the
        catalog the one place both reads answer from, so the preview can only ever become
        a source of the same truth, never a different one. The stamp is not a deletion and
        does not become one if the owner cancels: `cloud_deleted_at` records what PIXAI
        did to its own copy, which is true whatever this dialog decides, and every path
        that reads it (the keep-back, the single-image plan) only ever keeps a row.

        FAILS SOFT, and in the SAFE direction. A task whose read raises, comes back
        empty, or never answers inside the budget is `unverified`: it keeps its local rows
        and is counted as if nothing had been read, so a blip can only ever make the
        preview say MORE will be deleted than really will. It can never quietly shrink an
        irreversible action's reported scope.

        WHY AN EMPTY ANSWER IS "unverified" AND NOT "already gone whole" -- this differs
        from the brief that ordered the work, on the module's own evidence. The ruling
        said a task the read cannot find at all should be reported as already gone whole.
        It cannot be: core.task_detail_gql collapses a transport failure to None (it
        catches PixAIError/RequestException and returns None), and the 2026-09-06
        read-only probe recorded at moonglade/backup.py's DELETING ONE IMAGE header found
        that "getTaskById still resolves a whole-task-deleted task, so it cannot be used
        to ask whether a task is gone". So None means "no answer", never "gone", and
        reading it as gone would take a network blip and turn it into a smaller reported
        delete -- the one direction this file's fail-soft rule forbids. What CAN be
        established, and is, is per-image: a deleted batch member keeps its place and
        gains `deletedAt`.

        retries=1, not the default 3: the caller here is a confirm dialog the owner is
        watching, and the fallback is a visible "could not be checked" rather than the
        lost-generation sentence task_detail_gql's own retries exist to prevent. Each read
        also gets the budget's REMAINING time as its socket timeout, so the confirm dialog
        is bounded by DELETE_PREVIEW_LIVE_BUDGET_S rather than by the transport's 60s.

        Returns (gone_by_task, unverified, artworks_by_task) -- {task_id: {media_id, ...}}
        for every task that answered, the set of task ids that did not, and {task_id:
        ((artwork_id, ...), batch_size)} for every answered task whose read carried
        `artworkIds` -- batch_size being the task's image count ON PIXAI -- (the
        published-artwork count the dialog words, SCOPE_2026-09-26 E5; a task missing from it
        falls back to the catalog, see api_delete_preview)."""
        from moonglade import backup as core   # lazy: avoid import cycle
        ids = [str(t) for t in task_ids]
        try:
            session = core._make_session(None)
        except Exception:                            # noqa: BLE001 -- no key, bad config
            # Nothing to read WITH. Every task is unverified; the preview still answers
            # from the catalog exactly as it did before this existed.
            return {}, set(ids), {}

        # THE CEILING IS WALL-CLOCK, and it is enforced in three places because one is not
        # enough (2026-09-07, correcting the same day's build, which checked it only here):
        #   * before a read STARTS -- the budget is spent, don't start another;
        #   * on the read ITSELF -- each one is given no more socket time than the budget
        #     has left, so a connection that stalls after the handshake cannot run out the
        #     transport's own 60s (and then retry for another 60);
        #   * on the COLLECTION -- as_completed stops at the deadline and the pool is left
        #     to drain on its own, so a worker still in flight cannot hold the route.
        # Anything not back by then is `unverified`, exactly like a read that failed.
        deadline = time.monotonic() + DELETE_PREVIEW_LIVE_BUDGET_S

        def _one(tid):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return tid, None                     # budget spent: don't start another
            try:
                task = _task_reads.task_detail_gql(session, tid, retries=1, timeout=remaining)
            except Exception:                        # noqa: BLE001 -- fail soft, see above
                return tid, None
            if task is None:
                return tid, None
            batch = (task.get("outputs") or {}).get("batch")
            gone_ids = {str(m) for m in _cloud_delete.deleted_batch_media(batch) if m}
            # WRITE IT DOWN, right here, with the same verb the delete's own read uses.
            # See the docstring: this is what stops the delete-time read's failure from
            # taking the rows this preview is about to promise would stay.
            for mid in gone_ids:
                stamp = str((_cloud_delete.batch_entry(batch, mid) or {}).get("deletedAt") or "")
                if stamp:
                    mark_cloud_deleted(db_path, mid, stamp)
            # The same read already carries the task's published artworks -- no second call --
            # and the task's size on PixAI, which is what the artwork count is capped at.
            return tid, (gone_ids, _cloud_delete.task_artwork_ids(task),
                         len(batch) if isinstance(batch, list) else 0)

        # Every task starts unverified and EARNS its way out, so a task whose worker never
        # answers -- the case the deadline exists for -- is counted the safe way by default
        # rather than by remembering to add it.
        gone, unverified, artworks = {}, set(ids), {}
        from concurrent.futures import (ThreadPoolExecutor, as_completed,
                                        TimeoutError as _FutureTimeout)
        # NOT a `with` block: its __exit__ is shutdown(wait=True), which waits for every
        # in-flight read and would put the whole ceiling back where it was.
        ex = ThreadPoolExecutor(max_workers=DELETE_PREVIEW_LIVE_WORKERS)
        try:
            futures = [ex.submit(_one, tid) for tid in ids]
            try:
                for fut in as_completed(futures,
                                        timeout=max(0.0, deadline - time.monotonic())):
                    try:
                        tid, res = fut.result()
                    except Exception:                # noqa: BLE001 -- a dead worker is unverified
                        continue
                    if res is not None:
                        gone[tid], aw, batch_n = res
                        if aw is not None:
                            artworks[tid] = (aw, batch_n)
                        unverified.discard(tid)
            except _FutureTimeout:
                pass                                 # the ceiling; the rest stay unverified
        finally:
            # Don't wait. A stalled read is already bounded by its own socket timeout and
            # writes nothing anyone is still listening to; the route answers now.
            ex.shutdown(wait=False, cancel_futures=True)
        return gone, unverified, artworks

    def _preview_entry(row, selected_ids, gone_ids=()):
        """One /api/delete-preview media entry: what it is, whether the user actually
        picked it, and the media_id whose thumbnail exists on disk -- or None for
        `thumb`, so the client renders an id chip instead of a broken image. Videos fall
        back to their still-frame poster's thumb exactly as the gallery grid does (older
        sync runs never generated the video's own).

        `already_gone` (2026-09-07) is the live read's answer for this one image: PixAI has
        already dropped it, so the delete will leave this row and its file alone
        (_rows_the_bulk_purge_must_keep). Always present and False when nothing was read,
        so the strip never has to guess which of the two it is looking at."""
        mid = row["media_id"]
        thumb = None
        if (thumb_dir / "{}.jpg".format(mid)).exists():
            thumb = mid
        elif row["is_video"] == "1" and row["poster_media_id"]:
            poster = row["poster_media_id"]
            if (thumb_dir / "{}.jpg".format(poster)).exists():
                thumb = poster
        return {"media_id": mid, "is_video": row["is_video"] == "1",
                "selected": mid in selected_ids, "thumb": thumb,
                "already_gone": mid in gone_ids}

    @app.route("/api/delete-preview", methods=["POST"])
    @tier(LOCALHOST, message="deleting from PixAI is localhost-only")
    def api_delete_preview():
        """What "Delete from PixAI" would actually take, listed image by image, before
        anything fires. Read-only in the sense that matters: it deletes nothing, here or
        on PixAI. It is no longer offline, and no longer writes NOTHING either -- the one
        thing it records is `cloud_deleted_at` on the rows PixAI says it has already
        dropped, so the delete keeps them back whether or not its own read works
        (_preview_live_gone). See THE LIVE CHECK below.

        Deleting on PixAI is TASK-level -- selecting one image of a batch deletes the
        whole batch, cloud AND local. The confirm dialog said that in prose but never
        showed WHICH siblings, so the single irreversible action in this app was also
        the only one whose real scope the user could not see before committing to it.
        This resolves the selection through the delete_preview_rows catalog verb,
        which shares its target resolution with /api/delete-tasks deliberately, and
        then expands each task to its full catalog membership.

        LOCALHOST, mirroring the action it previews rather than the data it reads. The
        catalog rows themselves are ordinary LOGIN-tier browsing material (a LAN
        session can already list a whole batch via ?batch=<task_id>), so this is not
        about hiding them -- it is that the preview exists only as step one of a
        LOCALHOST flow whose button a LAN session cannot even see, and a preview
        reachable at a lower tier than its action is a gap waiting to be mistaken for
        an entry point. Weakens nothing: /delete-tasks-bulk still re-checks for itself.

        Truncation is DISPLAY-only (DELETE_PREVIEW_TASK_CAP): `totals` always describes
        the entire selection, because the totals are what the user reads to decide.

        THE LIVE CHECK (owner, 2026-09-07). "One live read per selected task, capped at
        40; above that the preview says it is an estimate, and the delete still keeps back
        what the live read finds." At or below DELETE_PREVIEW_LIVE_CAP every selected task
        is read back from PixAI (_preview_live_gone), so an image the owner deleted on
        PixAI's own website is reported as ALREADY GONE instead of being counted among the
        files this delete will take -- which is what the catalog alone could never know,
        and what made the preview disagree with the delete it was previewing. Above the
        cap nothing is read and `estimate` says so.

        `totals` is UNCHANGED in meaning: it is still the full membership of the blast
        radius. The four new fields sit beside it, top-level, so nothing that reads
        `totals` today can be surprised:
          live_checked  how many tasks really were read back
          unverified    how many could not be (a blip, no credentials, or the budget)
          already_gone  IMAGES PixAI has already dropped -- subtract from totals.media for
                        "will be deleted"
          estimate      True when the selection was over the cap and nothing was read

        PUBLISHED ARTWORK (2026-09-26, SCOPE_2026-09-26 E5). PixAI's own contract says its
        task delete "soft-deletes a task ...: its linked artwork is deleted" -- and every
        task this dialog previews goes by the whole-task delete. Two more fields say how
        much published work that may take, for the dialog to put in one sentence:
          published            artworks across the selection's tasks: each task's LIVE
                               `artworkIds` off the read above (capped at the task's image
                               count on PixAI, or its library rows if that is more), else --
                               over the live cap, or a task that did not answer -- the
                               catalog rows of that task carrying an artwork_id. A blank
                               artwork_id is "not known", never "not published".
          published_unchecked  True when some task fell back to the catalog AND the catalog
                               records no artwork at all (the artworks sync has never filled
                               it), so publication was simply not checked.
          published_unchecked_tasks  how many tasks that is (0 when checked), so a dialog
                               that also has a live count can say "K of the N tasks were not
                               checked" instead of contradicting the count."""
        body = request.get_json(silent=True) or {}
        # dict.fromkeys: deduped, order preserved. The blast radius is a set of FILES, so
        # a repeated id must not inflate "you picked N" (or drive `unselected` negative)
        # just because a caller sent the same one twice.
        media_ids = list(dict.fromkeys(
            str(m) for m in (body.get("media_ids") or []) if str(m).strip()))
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400

        blast = delete_preview_rows(db_path, media_ids)
        sel_rows, task_ids = blast["sel_rows"], blast["task_ids"]
        local_only = blast["local_only"]
        selected = {r["media_id"] for r in sel_rows}

        # The live check, before the loop that spends it. Over the cap it does not happen
        # at all -- estimate, and the modal says so.
        estimate = len(task_ids) > DELETE_PREVIEW_LIVE_CAP
        gone_by_task, unverified, artworks_by_task = (
            ({}, set(), {}) if estimate else _preview_live_gone(task_ids))

        tasks, total_media, already_gone = [], 0, 0
        published, from_catalog = 0, 0
        for tid in task_ids:
            members = blast["members_by_task"].get(tid, [])
            total_media += len(members)
            # Published artwork, over the task's FULL membership (the delete takes the whole
            # task, not just the picked rows) -- see the docstring. The live count is capped at
            # the task's size ON PIXAI (or its library rows, if more): a library that never
            # collected some of a task's images must not under-count what the delete may take.
            if tid in artworks_by_task:
                aw, batch_n = artworks_by_task[tid]
                published += min(len(aw), max(1, len(members), batch_n))
            else:
                from_catalog += 1
                published += sum(1 for m in members
                                 if str(m.get("artwork_id") or "").strip())
            # A task that answered: the union of what the read says PixAI has dropped and
            # what the catalog was already told the last time anything read this task --
            # exactly the two sources _rows_the_bulk_purge_must_keep keeps back from, so
            # the count the owner reads here is the count the delete will honour. A task
            # that did NOT answer contributes nothing: it stands on its local rows whole,
            # which can only over-report the delete, never under-report it.
            gone = set()
            if tid in gone_by_task:
                gone = set(gone_by_task[tid])
                gone |= {str(m["media_id"]) for m in members
                         if str(m["cloud_deleted_at"] or "").strip()}
                gone &= {str(m["media_id"]) for m in members}
                already_gone += len(gone)
            if len(tasks) >= DELETE_PREVIEW_TASK_CAP:
                continue          # keep counting, stop describing
            tasks.append({"task_id": tid,
                          "unverified": tid in unverified,
                          "media": [_preview_entry(m, selected, gone) for m in members]})
        # Imports have no task, so nothing about them is task-level -- but they ARE
        # part of what the button removes, and the dialog has to show them or its
        # file count won't add up. Capped on the same DISPLAY budget as the tasks.
        local_entries = [_preview_entry(m, selected) for m in blast["local_rows"]]
        # The tasks whose publication nobody could answer: they fell back to a catalog the
        # artworks sync has never filled.
        published_unchecked_tasks = (
            from_catalog if from_catalog and not myart_coverage(db_path)["artworks"] else 0)

        return jsonify({
            "tasks": tasks,
            "local_only": local_entries,
            "truncated": (len(task_ids) > len(tasks)
                          or len(local_only) > len(local_entries)),
            # The live check's own answer, beside `totals` rather than inside it (see the
            # docstring). live_checked + unverified == len(task_ids) whenever it ran.
            "live_checked": len(gone_by_task),
            "unverified": len(unverified),
            "already_gone": already_gone,
            "estimate": estimate,
            "published": published,
            "published_unchecked": bool(published_unchecked_tasks),
            "published_unchecked_tasks": published_unchecked_tasks,
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

        purge_local=False is the JSON route's cloud-only mode (cloud gone, local files
        + catalog intact: what the removed --delete-task command used to do). It
        drops the local_only imports HERE, not in the caller, because with no
        cloud side they would otherwise be pure local purges -- exactly what the
        flag says not to do."""
        import uuid
        from moonglade import backup as core   # lazy: avoid import cycle
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
            kept = []
            step = max(1, total // 50)          # throttle progress writes (~every 2%)
            def _tick():
                if done % step == 0 or done == total:
                    _log_job(job_id, status="running", done=done, total=total)
            try:
                session = core._make_session(None) if task_ids else None
                for tid in task_ids:
                    # BEFORE the cloud delete: once the generation record is gone there is
                    # nothing left to read, and this is the read that says which local rows
                    # hold the only copy of their image left anywhere.
                    rows = task_media(db_path, tid) if purge_local else []
                    keep = (_rows_the_bulk_purge_must_keep(session, tid, rows)
                            if purge_local else set())
                    try:
                        _cloud_delete.delete_task(session, tid)          # cloud delete (irreversible)
                        deleted += 1
                    except Exception:                            # noqa: BLE001
                        failed += 1
                        done += 1; _tick(); continue
                    if purge_local:
                        for m in rows:
                            if str(m["media_id"]) in keep:
                                # PixAI had already deleted this one; this library holds the
                                # last copy in existence. Named on the card, never purged.
                                kept.append(str(m["media_id"]))
                                continue
                            try:
                                _purge_local(m["media_id"], m["filename"]); removed += 1
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
                if kept:
                    # Said out loud rather than left as a silent difference in the numbers:
                    # these files are still in the library on purpose.
                    summary += " · kept {} file{} PixAI had already deleted".format(
                        len(kept), "" if len(kept) == 1 else "s")
                # ANY failure is a non-clean result -- surface it RED on the card. Don't bury
                # "3 failed" inside a green 'done': those tasks still exist on PixAI (drift).
                status = "failed" if failed else "done"
                _log_job(job_id, status=status, label=summary, done=total, total=total,
                         kept_media=(kept or None),
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
    @tier(LOCALHOST, message="deleting from PixAI is localhost-only")
    def api_delete_tasks():
        """JSON twin of /delete-tasks-bulk: same LOCALHOST tier (and for the same
        reason -- this MUTATES THE OWNER'S REAL CLOUD ACCOUNT, irreversibly), same
        delete_targets selection so /api/delete-preview keeps describing
        exactly what this route then does, and the same off-thread worker via
        _start_bulk_delete -- which routes every cloud delete through
        core.delete_task (POST /v2/task/{id}/delete on the API key), the single-attempt
        _check_read_only'd choke point the page route uses, never gql_adhoc. The page
        route stays until classic's demolition.

        Body: {task_ids: [...]} OR {media_ids: [...]} (task_ids win when both are
        sent -- they are already the unit the delete operates on), plus optional
        purge_local (default true, the page behavior: purge follows cloud so
        catalog and account never drift; false = cloud-only, what the removed
        --delete-task command used to do, and imports are then left alone entirely).

        _check_read_only fires HERE, before the job even starts, on top of the one
        inside delete_task: failing fast with one readable refusal beats
        spawning a job whose every task then fails red on the Activity card."""
        from moonglade import backup as core   # lazy: avoid import cycle
        body = request.get_json(silent=True) or {}
        purge_local = bool(body.get("purge_local", True))
        task_ids = sorted({str(t).strip() for t in (body.get("task_ids") or [])
                           if str(t).strip()})
        local_only = []
        if not task_ids:
            media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
            if not media_ids:
                return jsonify({"error": "no task_ids or media_ids given"}), 400
            _sel_rows, task_ids, local_only = delete_targets(db_path, media_ids)
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
    @tier(LOGIN)
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
        items, total, total_bytes, archive_only_total = _list_quarantined(
            out_dir, page=page, page_size=limit)
        _ensure_trash_thumbs(out_dir, thumb_dir, items)
        for it in items:
            it["thumb"] = "/thumbs/{}.jpg".format(it["media_id"])
        # `archive_only` per file and `archive_only_total` for the whole trash (#66): the
        # typed-DELETE confirms of Delete forever and Empty trash name how many files are
        # the only copy anywhere before they go for good (Empty takes every page, so the
        # page alone cannot answer it).
        return jsonify({"items": items, "total": total, "total_bytes": total_bytes,
                        "archive_only_total": archive_only_total,
                        "page": page, "limit": limit})

    @app.route("/api/trash/restore", methods=["POST"])
    @tier(LOGIN)
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
            _telemetry.telem_bump("trash_restored", len(restored), out_dir=out_dir)
        return jsonify({"restored": restored, "errors": errors})

    @app.route("/api/trash/delete-forever", methods=["POST"])
    @tier(LOCALHOST)
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
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        media_ids = [str(m) for m in (body.get("media_ids") or []) if str(m).strip()]
        if not media_ids:
            return jsonify({"error": "no media_ids given"}), 400
        n = sum(1 for mid in media_ids
               if delete_quarantined_forever(out_dir, thumb_dir, mid))
        _telemetry.telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    @app.route("/api/trash/empty", methods=["POST"])
    @tier(LOCALHOST)
    def api_trash_empty():
        """Empty the ENTIRE trash -- every file under out_dir/_deleted/, not just a
        selection. Same LOCALHOST + confirm=true contract as
        api_trash_delete_forever() (see its docstring); the client demands the same
        typed "DELETE" word first (Trash.emptyAll())."""
        body = request.get_json(silent=True) or {}
        if not body.get("confirm"):
            return jsonify({"error": "confirm required"}), 400
        n = empty_trash(out_dir, thumb_dir)
        _telemetry.telem_bump("trash_purged_forever", n, out_dir=out_dir)
        return jsonify({"deleted": n})

    @app.route("/api/rate/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def rate(media_id):
        data = request.get_json(silent=True) or {}
        try:
            value = max(0, min(5, int(data.get("rating", 0))))
        except (TypeError, ValueError):
            return json.dumps({"ok": False}), 400, {"Content-Type": "application/json"}
        update_rating(db_path, media_id, value)
        # Lamplighter (curation_streak) + The Long Vigil (active_days): rating a piece --
        # including clearing it to 0 -- is curation. Keyed day-lists, idempotent, silent-soft.
        try:
            _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
        except Exception:
            pass
        return json.dumps({"ok": True, "rating": value}), 200, {"Content-Type": "application/json"}

    @app.route("/api/rebuild-poster/<media_id>", methods=["POST"])
    @tier(LOGIN)
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
            from moonglade import backup as core   # lazy, like every other gallery use of it
            files = _scan.find_files_for_media_id(out_dir, media_id, exts=core._VIDEO_EXTS)
            if not files:
                return json.dumps({"ok": False, "error": "video file not found"}), 404, {"Content-Type": "application/json"}
            src = Path(files[0])
        thumb = out_dir / "gallery" / "thumbs" / (media_id + ".jpg")
        ok = make_video_thumbnail(src, thumb)
        if not ok:
            return json.dumps({"ok": False, "error": "ffmpeg extract failed (is ffmpeg on PATH?)"}), 200, {"Content-Type": "application/json"}
        return json.dumps({"ok": True, "thumb": "/thumbs/" + media_id + ".jpg?v=" + str(int(time.time()))}), 200, {"Content-Type": "application/json"}

    @app.route("/api/edit-prompt/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def edit_prompt(media_id):
        data = request.get_json(silent=True) or {}
        update_prompt_full(db_path, media_id, data.get("prompt", ""))
        return json.dumps({"ok": True}), 200, {"Content-Type": "application/json"}

    @app.route("/api/collection", methods=["POST"])
    @tier(LOGIN)
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
        if action == "remove" and _is_smart_name(db_path, name):
            return jsonify({"error": "“{}” is a smart collection, a saved search. Pictures "
                                     "leave it by no longer matching.".format(name)}), 400
        fn = add_to_collection if action == "add" else remove_from_collection
        try:
            return jsonify({"ok": True, "count": fn(db_path, media_ids, name)})
        except CurationError as e:        # adding to a smart collection (N1)
            return jsonify({"error": str(e)}), 400

    # ------------------------------------------------------------------------------------
    # CURATION (Session N). Local catalog only: none of these routes touches PixAI, and none
    # can delete a picture or a file. Every POST checks the session's CSRF token (the token
    # rides in the body, as for the Panel's account routes).
    # ------------------------------------------------------------------------------------
    @app.route("/api/collections/detail")
    @tier(LOGIN)
    def api_collections_detail():
        """Every collection, hand-picked and smart, with its count and cover -- what the
        collections list and the manager draw. Read-only; a smart collection's count is its
        saved query run now."""
        return jsonify({"collections": collection_summaries(db_path)})

    @app.route("/api/collections/manage", methods=["POST"])
    @tier(LOGIN)
    def api_collections_manage():
        """The collections manager's writes and Save-as-smart, one route, `action` picks:
        rename {name, new_name} · merge {names: [target, ...others]} · delete {name} ·
        smart {query, name?, replace?}. Labels and saved queries only -- a delete or a merge
        never removes a picture. A refusal is a 400 with the reason in words."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        action = str(body.get("action") or "").strip()
        try:
            if action == "rename":
                res = rename_collection(db_path, body.get("name"), body.get("new_name"))
            elif action == "merge":
                names = body.get("names")
                res = merge_collections(db_path, names if isinstance(names, list) else [])
            elif action == "delete":
                res = delete_collection(db_path, body.get("name"))
            elif action == "smart":
                res = save_smart_collection(db_path, body.get("query"),
                                            name=body.get("name") or "",
                                            replace=str(body.get("replace") or "").strip())
            else:
                return jsonify({"error": "action must be rename, merge, delete or smart"}), 400
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    # ---- MANUAL ORDER (Session P, P6) -------------------------------------------------------
    # A hand-picked collection's order: read by the order editor, the collection view's
    # "Manual" sort, the Contact sheet and "as shots, in order". Local catalog only, never
    # PixAI; the write is one transaction and needs the session's CSRF token.
    @app.route("/api/collections/order", methods=["GET"])
    @tier(LOGIN)
    def api_collections_order_get():
        """{name, kind, media_ids, manual} -- the collection's members in its order
        (ordered_members). Read-only: opening the editor writes nothing."""
        name = (request.args.get("name") or "").strip()
        res = ordered_members(db_path, name)
        if res["kind"] is None:
            return jsonify(dict(res, error="There is no collection called “{}”.".format(name))), 404
        return jsonify(res)

    @app.route("/api/collections/order", methods=["POST"])
    @tier(LOGIN)
    def api_collections_order_set():
        """{csrf, name, media_ids} -> the saved order (ordered_members after). A smart
        collection, an unknown one and any id that is not a member are refused (400)."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        ids = body.get("media_ids")
        try:
            res = set_collection_order(db_path, body.get("name"), ids if isinstance(ids, list) else [])
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    @app.route("/api/curate", methods=["POST"])
    @tier(LOGIN)
    def api_curate():
        """Bulk (or single) curation: {media_ids, op} with op one of {rating: 0-5} ·
        {mark: keeper|reject|""} · {add_tag} · {remove_tag} · {note}. Answers what really
        changed -- `changed` counts pictures whose values differ afterwards, `prev` / `after`
        carry each changed picture's full state -- so the client can show an honest count and
        an Undo that restores each picture's OWN previous values (POST /api/curate/restore).
        Tags, marks and notes live in the local catalog and are never sent to PixAI."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        try:
            res = curate_apply(db_path, body.get("media_ids"), body.get("op"))
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        if res["changed"] and isinstance(body.get("op"), dict) and "rating" in body["op"]:
            # Rating is curation whichever door it came through (see /api/rate).
            try:
                _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
            except Exception:
                pass
        return jsonify(dict(res, ok=True))

    @app.route("/api/curate/restore", methods=["POST"])
    @tier(LOGIN)
    def api_curate_restore():
        """Undo for /api/curate: {prev: {media_id: {rating, mark, tags, note}}} -- exactly
        the `prev` map that call returned. Puts each picture back to its own previous
        values; a request with any invalid entry changes nothing."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        try:
            res = curate_restore(db_path, body.get("prev"))
        except CurationError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(dict(res, ok=True))

    @app.route("/api/replace-prompts", methods=["POST"])
    @tier(LOGIN)
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

    # The allowlist of derived thumb sizes, ?s=<key> -> (longest side in px, cache folder).
    # 32 is the Sibling Strip's; 256 is the phone's Data saver tier (Session Q, Q7): the
    # same derive-from-the-768, cache-beside-the-badges, self-healing shape, additive and
    # read-only -- an unlisted key still answers the plain 768 thumb.
    _THUMB_TIERS = {"32": (32, "_strip"), "256": (256, "_t256")}

    def _sized_thumb(media_id, key):
        """Path of the cached derived thumb (`key` names a tier in _THUMB_TIERS) for
        media_id, (re)cut from the 768 thumb when missing or stale. None when there is
        no 768 thumb to derive from or the cut fails -- the caller then falls through
        to the normal thumb."""
        side, folder = _THUMB_TIERS[key]
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
        dst = out_dir / "gallery" / "cache" / folder / (media_id + ".jpg")
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
                    im.thumbnail((side, side))
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
    @tier(LOGIN)
    def thumb(media_id):
        # ?s= is an allowlist (_THUMB_TIERS: 32 and 256); anything else is the 768 thumb.
        size_key = request.args.get("s") or ""
        if size_key in _THUMB_TIERS and "/" not in media_id \
                and "\\" not in media_id and ".." not in media_id:
            p = _sized_thumb(media_id, size_key)
            if p is not None:
                resp = send_from_directory(str(p.parent), p.name, max_age=86400,
                                           mimetype="image/jpeg")
                resp.headers["Cache-Control"] = _STRIP_CACHE
                return harden_file_response(resp, p.name)
        # An SVG has no server thumbnail by design (DESIGN_3.22 5.3): every grid, picker and
        # viewer builds /thumbs/<id>.jpg, so for an SVG row this route points the <img> (or CSS
        # background-image) at the library file route instead, which already serves it under
        # the 5.4 headers. A redirect, never the SVG's text inlined or a different element.
        if "/" not in media_id and "\\" not in media_id and ".." not in media_id \
                and not (Path(str(thumb_dir)) / "{}.jpg".format(media_id)).exists():
            row = get_row(db_path, media_id)
            sp = find_image_file(out_dir, media_id, row.get("filename") if row else "")
            if sp and str(sp).lower().endswith(".svg"):
                return redirect("/full/{}".format(media_id))
        resp = send_from_directory(str(thumb_dir), "{}.jpg".format(media_id),
                                   max_age=300, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = _THUMB_CACHE
        return harden_file_response(resp, "{}.jpg".format(media_id))

    @app.route("/video-file/<media_id>")
    @tier(LOGIN)
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
        resp = send_from_directory(str(out_dir), rel, max_age=31536000,
                                   mimetype=media_type_for(p.name))
        resp.headers["Cache-Control"] = _IMMUTABLE
        return harden_file_response(resp, p.name)

    @app.route("/full/<media_id>")
    @tier(LOGIN)
    def full_image(media_id):
        # Resolve a media_id to its full-res file on the fly (used by the
        # lightbox so the index page doesn't precompute 250 image paths).
        row = get_row(db_path, media_id)
        p = find_image_file(out_dir, media_id, row.get("filename") if row else "")
        if not p or not p.exists():
            return "Not found", 404
        # ?dl=1 -> force a SAVE with the real filename (the detail page's plain Download);
        # without it, inline (the lightbox displays the image). Same file either way.
        # A type that is not a raster picture (an SVG from Edit Pro) is a download either
        # way: harden_file_response never lets it open as a page on this origin.
        dl = bool(request.args.get("dl"))
        resp = send_from_directory(str(p.parent), p.name, max_age=31536000,
                                   mimetype=media_type_for(p.name),
                                   as_attachment=dl, download_name=(p.name if dl else None))
        resp.headers["Cache-Control"] = _IMMUTABLE
        return harden_file_response(resp, p.name)

    @app.route("/export-zip", methods=["POST"])
    @tier(LOGIN)
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
        from moonglade import backup as core
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
                                    "model": row.get("model_name") or row.get("model_id") or "",
                                    "seed": row.get("seed") or "",
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

    @app.route("/api/model-search")
    @tier(LOGIN)
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
             BROWSE ONLY since the owner's second walk (2026-09-07), which REFINES the
             2026-07-24 ruling rather than reversing it: see `server_lora_type` below.
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
        # The base-type filter is a BROWSE hint, not a SEARCH one -- owner's second walk
        # (2026-09-07: "searching for a known LoRA still fails"), REFINING the 2026-07-24
        # ruling that added layer 1, not reversing it. Typing a name is a hunt for a LoRA he
        # already knows, and the server filter answers that hunt by leaving the match OUT of
        # the results entirely: an SDXL LoRA searched for while Tsubaki.3 (MMDIT26B) is the
        # picked base simply is not there, the page fills up with other loosely-relevant
        # LoRAs, and the empty state never fires -- so the search reads as broken. With a
        # keyword we send NO filter and let layer 3 (annotate_lora_compat, the precise one)
        # show the match greyed with its "needs <arch>" badge instead of hiding it. Browsing
        # with no keyword keeps the filter exactly as 2026-07-24 set it: that wall
        # (24-of-24 SD 1.5 rows) is the whole reason layer 1 exists. `base_type` itself is
        # untouched -- it still feeds the sort and the badge on every LoRA search.
        server_lora_type = base_type if (usage == "LORA" and not q) else ""
        try:
            # The market is browsed AS THE WEBSITE (core.present_as_web): PixAI filters what it
            # returns by the client it believes it is talking to, and the API-key session's own
            # identity gets the stricter mobile-app policy -- a search that fills pages on the
            # site came back empty here (owner, 2026-09-07). Same key, same query, website
            # identity: the same rows the site shows.
            core, session = _gen_session()
            if src == "saved":
                # The Saved tab (Session S): one of the account's PixAI model collections --
                # Saved, the reserved default, unless `set` names a set -- 24 a page by cursor,
                # newest saved first. PixAI's own keyword search (cursor mode) and ONE LoRA
                # base (`base`, the chips) filter it; the kind is fixed by the picker. The plain
                # API-key session, as the 2026-10-03 probe read it (no website identity).
                rec = _recipes()
                set_id = (request.args.get("set") or "").strip()
                if not set_id:
                    found = rec.model_default(session, _recipe_user_id(core, session))
                    if found is None:
                        return jsonify({"results": [], "has_more": False, "next_cursor": ""})
                    set_id = found["id"]
                payload = rec.model_page(session, set_id, "lora" if usage == "LORA" else "base",
                                         cursor=cursor, query=q,
                                         lora_base=(request.args.get("base") or "").strip())
                if usage == "LORA" and base_type:
                    payload["results"] = _models.annotate_lora_compat(payload["results"], base_type)
                payload["read_only"] = _read_only_flag(core)
                return jsonify(payload)
            session = _mirror.present_as_web(session)
            if src == "bookmark":
                # Its own operation -- the market connection has no bookmark argument, so this
                # cannot be folded into the call below. Same row shape, so the grid does not care.
                def _bookmark_page(after):
                    return _models.model_bookmarks_gql(
                        session, keyword=q, usage=usage, limit=size, after=after,
                        lora_base_type=server_lora_type)
                payload = _hunt_by_name(_bookmark_page, q, size) if q else _bookmark_page(cursor or None)
            elif src == "mine":
                # "My LoRAs" is NOT a separate operation: it is the ordinary market connection
                # filtered by the signed-in user's own id, exactly as their MY LORA tab does it.
                def _mine_page(after):
                    return _models.model_search_market_gql(
                        session, keyword=q, category=category, sort=sort, usage=usage,
                        limit=size, after=after,
                        lora_base_type=server_lora_type,
                        author_id=_pixai_client._client_of(session).user_id or "")
                payload = _hunt_by_name(_mine_page, q, size) if q else _mine_page(cursor or None)
            # GraphQL whenever ANY market filter or sort is in play. The owner reported that
            # under Popular the Model Type and Posted-at filters did nothing: base+Popular used
            # to fall through to REST, whose own docstring says it "silently ignores market
            # filters". REST survives only for a bare, unfiltered base browse, where its richer
            # rows (description / refCount / official badge) are worth having.
            elif (usage == "LORA" or category in _models.MARKET_CATEGORIES
                  or posted or license_ or model_types
                  or (sort and sort not in ("trending", "popular"))):
                payload = _models.model_search_market_gql(
                    session, keyword=q, category=category, sort=sort, usage=usage,
                    limit=size, after=(cursor or None),
                    # The same caller-supplied value that feeds the compat sort/badge
                    # below, resolved once by the client -- but only on a keywordless BROWSE
                    # (see server_lora_type). core ignores it for a base-model search and for
                    # any architecture off its whitelist.
                    lora_base_type=server_lora_type,
                    source=source, permitted_use=license_,
                    time_range=_models.posted_at_range(posted),
                    model_types=model_types)
            else:
                offset = int(cursor) if cursor.isdigit() else 0
                payload = _models.model_search_rest(session, keyword=q, usage=usage,
                                                  size=size, offset=offset)
                payload["next_cursor"] = str(offset + size) if payload.get("has_more") else ""
            if usage == "LORA" and base_type:
                payload["results"] = _models.annotate_lora_compat(payload["results"], base_type)
            # Session S: every card's ⊕ Save dims under READ_ONLY before any tap (a local check)
            payload["read_only"] = _read_only_flag(core)
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "results": []}), 200

    @app.route("/api/model-version")
    @tier(LOGIN)
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
                session = _mirror.present_as_web(session)   # same policy as the search that found it
                return jsonify({"model_id": _models.resolve_model_base_id(session, version_id)})
            except Exception as e:
                return jsonify({"error": _redact_host_paths(str(e))[:200], "model_id": ""}), 200
        mid = (request.args.get("model_id") or "").strip()
        if not mid:
            return jsonify({"error": "model_id required", "version_id": ""}), 400
        try:
            core, session = _gen_session()
            session = _mirror.present_as_web(session)   # same policy as the search that found it
            if (request.args.get("all") or "").strip() in ("1", "true"):
                return jsonify({"versions": _models.list_model_versions(session, mid)})
            # with_profiles: this is a BASE-model resolve whose answer feeds the composer's
            # mode bar, so it is one of the two places that pays the second, version-keyed
            # inference-profiles read (the ?all=1 branch's own is_latest row is the other).
            # Every other caller of resolve_version_meta -- the LoRA/remix path below --
            # leaves it off and stays at one read (red team 2026-09-07).
            # The same opt-in carries the version's size rule, the false compatibility
            # entries from /features and whether a reference goes out as a context image
            # (core._attach_features, SCOPE_2026-09-26) -- read from the gate's own cache.
            return jsonify(_models.resolve_version_meta(session, mid, with_profiles=True))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "version_id": ""}), 200

    @app.route("/api/task-params/<task_id>")
    @tier(LOGIN)
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
            task = _task_reads.task_detail_gql(session, tid, retries=1)
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
                    base = _models.resolve_model_base_id(session, str(vid))
                    if not base:
                        unresolved += 1
                        continue
                    if base not in meta_cache:
                        # No with_profiles here on purpose: nothing below reads `profiles`
                        # and a LoRA never renders a mode bar, so asking for it would cost a
                        # second PixAI GET per unique LoRA base for a field this route drops
                        # (red team 2026-09-07).
                        meta_cache[base] = _models.resolve_version_meta(session, base) or {}
                    meta = meta_cache[base]
                    lbt = str(meta.get("lora_base_model_type") or "")
                    rows.append({
                        "model_id": base, "version_id": str(vid), "weight": w,
                        "title": str(_models.model_name_gql(session, str(vid)) or "") or base,
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
    @tier(LOGIN)
    def api_video_task_params(task_id):
        """A VIDEO task's submit parameters, reduced to what "↺ Remix for videos"
        (SCOPE_2026-08-17 §2) needs: the shot kind (i2v / flf / r2v) and every
        recipe field the Video composer can set -- engine, duration, quality,
        camera, audio(+language), prompt-helper, negative, prompt, channel -- plus
        the source/reference media ids, each flagged in_lib against the local
        catalog so the client restores only what it actually holds.

        A deliberate SIBLING of /api/task-params rather than a widening of it: that
        route refuses videos (`not an image-generation task`) and its refusal test
        pins exactly that (dev/tests/test_task_params.py). Widening it would blur the
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
            task = _task_reads.task_detail_gql(session, tid, retries=1)
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
                    # The source's output aspect ratio (Tsubaki engines only). Read so the
                    # Remix can SAY it is not carried -- the drawer has no ratio picker yet,
                    # and a hidden carried ratio would be priced and sent unseen (2026-09-26).
                    "ratio": str(rv.get("ratio") or ""),
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
    @tier(LOGIN)
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
    @tier(LOGIN)
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
            rating_min=rating_min, media_type=media_type,
            # No SVG on this list (3.22 S5, DESIGN_3.22 5.3): the Apple TV client reads it and
            # tvOS cannot draw one, and no create surface may take one as a source. In SQL, so
            # the page and the total stay true.
            no_svg=True)
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
                        "duration": (r.get("video_duration") or "") if isv else "",
                        # Session H: a context image's size, for the drawer's Auto frame
                        "w": str(r.get("width") or ""), "h": str(r.get("height") or ""),
                        "rating": str(r.get("rating") or "0")})
        return jsonify({"images": out, "total": total, "page": page, "limit": limit})

    @app.route("/api/similar/<media_id>")
    @tier(LOGIN)
    def api_similar(media_id):
        """'More like this': the k catalog images most visually similar to media_id, via the
        moonglade.similar CLIP sidecar index. Mirrors /api/gallery-images's shape so the client
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
            from moonglade import similar as moonglade_similar
            hits = moonglade_similar.similar(str(img_path), k=k, exclude_media_id=media_id)
        except Exception as e:
            return jsonify({"images": [], "total": 0,
                            "error": "similarity index unavailable: " + _redact_host_paths(str(e))[:180]}), 200
        # An EMPTY index is not the same as "no matches", and conflating the two hid a real
        # regression for three days. The 2026-07-25 module rename orphaned the stored index;
        # moonglade.similar._get_table() then CREATED a fresh empty one instead of raising, so this
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
        _telemetry.telem_bump("similar_uses", out_dir=out_dir)       # Kindred Spirits
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
    @tier(LOGIN)
    def api_collections():
        """Collection names for the picker/filter dropdowns. Read-only, local catalog."""
        return jsonify({"collections": unique_collections(db_path)})

    @app.route("/branding/<path:fname>")
    @tier(PUBLIC)
    def branding(fname):
        """Serve branding art. The URL vocabulary is PUBLIC role names
        (/branding/marks/..., /branding/bridge/emotion/...); the on-disk tree
        and the container keys are CODED -- this route is the ONE place the
        two meet (_public_rel_to_coded, applied exactly once to the incoming
        rel). After translation: seal check, then a loose file under
        branding_root() first, the shipped container second (the loose-then-
        container contract every read path holds). Absent everywhere -> 404 so
        the header's onerror simply removes the <img>. Path-safe.

        The three banner flats take their OWN branch, after the seal check and
        in place of the loose-root lookup (2026-09-10): they are per-install
        RENDERS, not tree assets, so the coded root is never read for them.
        This install's flat wins -- the only copy in banner_keep_dir() when the
        slot wears one, else its render in banner_cache_dir(); failing that the
        container's own copy, if an older pack carries one; failing that the
        slot's SHIPPED sealed default, so a fresh install is dressed before its
        first crop. And the coded ROOT's own top level is inert the same way: a
        bare rel translation did not recognize reads the container only, so a
        file parked at the root is never served.

        This route SERVES and never renders. It is PUBLIC tier -- an anonymous
        GET from anywhere on the LAN reaches it -- so it must not be able to
        schedule a Pillow decode-crop-resize-save, and it must not write into
        the cache. Keeping a render current is create_app's startup ensure pass
        (_ensure_banner_renders) plus the explicit user actions that change a
        pick; see _ensure_banner_flat."""
        from flask import send_from_directory, abort
        import mimetypes
        bdir = _branding.branding_root().resolve()
        try:
            target = (bdir / fname).resolve()
            target.relative_to(bdir)          # reject path traversal
        except (ValueError, OSError):
            abort(404)
        coded = _branding._public_rel_to_coded(target.relative_to(bdir).as_posix())
        # Pictures only (owner, 2026-11-18): any other type -- a hand-dropped .html or
        # .svg above all, on this PUBLIC route -- is a 404 before anything is read,
        # loose or packed. branding_serves_type names the one carve-out (the shipped
        # moments' clips and sounds) and why.
        if not _branding.branding_serves_type(coded):
            abort(404)
        # The unlock split, enforced (see _seal_rule, which judges the CODED
        # rel -- a probe that guesses a coded path passes through translation
        # unchanged, so it faces the same verdict): achievement-bound art only
        # serves once its achievement is earned, whether the bytes would come
        # from a loose file or the container.
        mode, seal_aid = _branding._seal_rule(coded)
        if mode == "deny":
            abort(404)
        if mode == "earned" and seal_aid not in _branding._earned_achievement_ids(
                out_dir, db_path, need=seal_aid):
            abort(404)
        if coded in _branding._BANNER_FLAT.values():
            # The flat branch. bdir is deliberately NOT consulted: the render
            # lives in the cache, and a file parked at the coded root is not a
            # render. Pure lookup -- whatever the startup ensure pass and the
            # explicit write paths left here is what is served.
            slot = next(s for s, n in _branding._BANNER_FLAT.items() if n == coded)
            cdir = _branding._served_flat_dir(out_dir, slot)
            try:
                have_render = (cdir / coded).is_file()
            except OSError:
                have_render = False
            if have_render:
                resp = send_from_directory(str(cdir), coded)
                resp.headers["Cache-Control"] = "no-cache, must-revalidate"
                return harden_file_response(resp, coded)
            # Container-ONLY read (not _branding_bytes, which would try the
            # coded root loose first): an older pack may carry a top-level flat.
            box = _branding._get_container()
            raw = box.get(coded) if box else None
            if raw is None:
                # Rule-8 flat fallback: nothing rendered on this install yet and
                # nothing to render FROM -> the slot's shipped sealed default
                # (translation itself never rewrites the flat names).
                raw = _branding._branding_bytes(_branding._flat_default_rel(slot))
        elif "/" not in coded:
            # A bare rel translation did not recognize (rule 7) addresses the
            # coded ROOT's own top level, and the root is inert (2026-09-10):
            # the app writes nothing there, the discovery walk does not count
            # what sits there, and this route does not serve it. Container only
            # -- loose root is never read.
            box = _branding._get_container()
            raw = box.get(coded) if box else None
        elif (coded.lower() in _branding._role_coded_rels() and (bdir / coded).is_file()
              and not _branding._role_file_decodes(bdir / coded)
              and (_branding._get_container() is not None and _branding._get_container().has(coded))):
            # Fail-soft (Session X): an override of a named role that will not decode is the
            # pack's default, silently. Container-ONLY, like the flat branch above -- the loose
            # bytes are exactly what must not be served. With no pack default to fall back to
            # there is nothing better to say, and the loose file is served as it always was.
            raw = _branding._get_container().get(coded)
        elif (bdir / coded).is_file():
            resp = send_from_directory(str(bdir), coded)
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"   # branding art gets re-cut; never serve a stale copy
            return harden_file_response(resp, coded)
        elif coded in _branding._moment_clip_rels():
            # A moment's clip, container-sourced (no loose copy): verified once,
            # then sliced from memory for every range the <video> asks for.
            raw = _branding._container_clip_bytes(coded)
        else:
            # Container fallback keys on the CODED rel (posix separators -- the
            # container's native addressing; loose path == container key, always).
            raw = _branding._branding_bytes(coded)
        if raw is None:
            abort(404)
        # Every body that reaches here is in memory -- the container's bytes, or a
        # flat's shipped default read through _branding_bytes -- rather than a file
        # send_from_directory streams, so it gets the Range handling that would
        # have given a loose file.
        mime = mimetypes.guess_type(coded)[0] or "application/octet-stream"
        return harden_file_response(
            _branding._ranged_bytes_response(app.response_class, raw, mime), coded)

    @app.route("/badge-thumb/<aid>.png", defaults={"ext": "png"})
    @app.route("/badge-thumb/<aid>.webp", defaults={"ext": "webp"})
    @tier(LOGIN)
    def badge_thumb(aid, ext):
        """Cached ~256px badge for the Folio of Honors tiles (masters stay the source of
        truth). Lazily generated on first hit; path-safe (no slashes via <aid>).

        TWO extensions, ONE gate. `.webp` answers the client's webp-first probe with the
        ANIMATED master passed through untouched (_badge_anim), and 404s when there is no
        animated master -- which is the normal answer for most ids, and the signal the
        chain falls back to `.png` on. Both rules land on this one view function
        deliberately: the roster/hidden-feat gate below is written once and cannot be
        half-applied to one extension, which is exactly how a second route would have
        leaked a sealed feat's art."""
        from flask import send_from_directory, abort
        if not aid or "/" in aid or "\\" in aid or ".." in aid:
            abort(404)
        # Achievement ids are canonically lowercase-kebab; the underlying resolve
        # is on a case-insensitive FS, so a case-variant (an upper-cased <ID>.png)
        # would otherwise skip the hidden-feat gate below (a frozenset of
        # lowercase ids) yet still read the real sealed master -- the same
        # fail-open leak _seal_rule casefolds against. Normalise once here so the
        # gate, _earned_achievement_ids, and the cache key all agree.
        aid = aid.lower()
        # Fail CLOSED, matching _seal_rule's badge branch. Only serve a thumb for
        # an id that IS in the roster; an unknown id -- OR ANY id when the roster
        # is unavailable (no/invalid container -> _ach_ids() empty) -- is denied.
        # Without this, _ach_hidden() also goes empty in that state, the hidden
        # gate below silently passes, and an unearned masked feat's master serves
        # by id (the fail-open _seal_rule was written to avoid; the parallel gate
        # here missed it -- adversarial, 2026-08-22). Visible feats' thumbs still
        # serve unearned (the Folio's locked tiles show art by design).
        if aid not in _achievements._ach_ids():
            abort(404)
        # Feats the roster marks hidden are masked in /api/achievements, but
        # their ids sit in this public source -- so an unearned masked feat's
        # badge must not be fishable by id here either.
        if aid in _achievements._ach_hidden() and aid not in _branding._earned_achievement_ids(
                out_dir, db_path, need=aid):
            abort(404)
        if ext == "webp":
            # Past the same gate the stills pass, so an unearned masked feat's
            # animation is no more fishable than its still. Served whole -- see
            # _badge_anim on why an animated master is never re-encoded here.
            raw = _achievements._badge_anim(aid)
            if raw is None:
                abort(404)             # no animated master -> the chain falls back to .png
            resp = app.response_class(raw, mimetype="image/webp")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        # The celebration toast asks for 384px so the enlarged medallion stays crisp
        # on HiDPI, and since 2026-09-07 so does the phone Folio's detail sheet, which
        # now shows the badge whole at the frame's full height; the Folio grid keeps the
        # 256 default. Allowlisted to those two so the cache can't be spammed into
        # unbounded sizes.
        size = 384 if request.args.get("size") == "384" else 256
        p = _achievements._badge_thumb(out_dir, aid, size)
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

    @app.route("/feat-mask/<token>.png")
    @tier(LOGIN)
    def feat_mask(token):
        """The veil card's silhouette: an alpha-only PNG (white on transparent) cut from the
        badge of the NEXT unfound feat, named in the URL by an opaque HMAC token
        (_feat_mask_token) that says nothing about the feat's id, name or file.

        It serves ONLY the current pick's mask. A token for any other feat, a token that is
        not one, a feat already earned (the pick has moved on) and every request made before
        a first feat is earned all answer the same bare 404, so the route is not an oracle
        for which feats exist or which is next. The pick is recomputed from a fresh earned
        set on every request -- never from the 5-second cache -- so the mask for the feat
        that became the veil a moment ago is never refused off stale state. Read-only; no
        spend and nothing written beyond the regenerable cache file."""
        from flask import abort
        if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
            abort(404)

        def has_art(aid):
            return _branding._branding_exists(_branding._role_rel("badges", aid + ".png"))

        # need="" is in no cached set, so the helper recomputes instead of answering from its
        # 5-second cache -- an earn that landed since the cache was filled is never missed.
        earned = _branding._earned_achievement_ids(out_dir, db_path, need="")
        pick = _branding._pick_masked_feat(earned, has_art=has_art)
        if pick is None:
            abort(404)
        if not hmac.compare_digest(_branding._feat_mask_token(app.secret_key, pick["id"]), token):
            abort(404)
        png = _branding._feat_mask_bytes(out_dir, pick["id"], token)
        if png is None:
            abort(404)
        resp = app.response_class(png, mimetype="image/png")
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    @app.route("/contact-sheet")
    @tier(LOGIN)
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
            # P6: a collection prints in its own order (a hand-picked one's manual order, then
            # pictures added since, oldest first; a smart one's matches, oldest first).
            rows = rows_for_media_ids(db_path, ordered_members(db_path, collection)["media_ids"][:400])
            title = "Collection: {}".format(escape(collection))
        else:
            rows, _ = query_catalog(db_path, sort="newest", page=1, page_size=60)
            title = "Recent"

        mids = [str(r.get("media_id")) for r in rows if r.get("media_id")]
        # The page's two scripts carry this response's nonce (CSP_PAGE_POLICY runs nothing
        # else), and the Print button is wired from the nonced script, not an onclick.
        _nonce = _csp_nonce()
        _autoprint = ("<script nonce='" + _nonce + "'>"
                      "var _p=document.getElementById('mg-print');"
                      "if(_p)_p.addEventListener('click',function(){window.print();});"
                      "window.addEventListener('load',function(){"
                      "setTimeout(function(){window.print();},350);});</script>")
        _bar = ("<div class='bar'><h1>{t}</h1><button id='mg-print'>"
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
  <button id="mg-print">&#128424; Print</button>
  <a href="/" style="margin-left:auto;">&larr; back to gallery</a></div>
<div class="grid">{cells}</div>
{autoprint}
</body></html>""".format(title=title, cols=cols, n=len(cells), cells="".join(cells),
                         autoprint=_autoprint)
        return html

    @app.route("/api/contact-sheet")
    @tier(LOGIN)
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
            # P6: the collection's own order, the same as the print view above.
            rows = rows_for_media_ids(db_path, ordered_members(db_path, collection)["media_ids"][:400])
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
    @tier(LOGIN)
    def api_duplicates():
        """Real, working duplicate-groups listing for the React Duplicate Review overlay
        (the parked affordance in HealthOverlay.jsx's Duplicates/Reclaimable stat tiles).
        Owner-scoped "happy medium" (2026-08-02, moonglade-internal/DECISIONS.md), FOUR tiers --
        3 EXACT-match with no invented data/percentage, plus one perceptual-similarity
        tier that carries a real, derived closeness score (see near_duplicate below) --

          same_media     Class A: the same PixAI media_id reused across >1 folder bucket.
                          duplicate_groups() (this module) -- the classic /duplicates
                          page's own engine, reused as-is (its 300-row cap is lifted here;
                          see the call below).
          identical_file Class B: byte-identical files under DIFFERENT media_ids.
                          moonglade.organize.audit_collection(content=True)'s size-bucketed
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
        from moonglade import backup as core

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
                # PixAI no longer has it (#66): in the same_seed / near_duplicate tiers it is
                # the only copy of its picture, and the Resolve confirms name it.
                "archive_only": is_archive_only(row),
            }

        groups = []

        # ---- same_media (Class A) -------------------------------------------
        # No arbitrary cap here -- the classic page's limit=300 exists to keep an HTML
        # render short, not because the underlying scan is expensive (one scan_library
        # pass, no hashing); this route reports the real count instead of truncating.
        class_a = _dupes.duplicate_groups(out_dir, limit=100000)
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
        audit = _organize.audit_collection(out_dir, content=True)
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
        seed_groups = _dupes.same_seed_groups(db_path)
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
        near_groups = _dupes.near_duplicate_groups(db_path)
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
    @tier(LOGIN)
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
        submit_fixer/delete_task/claim_reward -- see
        quarantine_duplicate_file().

        ARCHIVE-ONLY MEMBERS GO WITH THE REST (#66; the owner's ruling on the 2026-10-03
        walk: warn, don't block). In the same_seed and near_duplicate tiers a member PixAI no
        longer has (is_archive_only) is the only copy of ITS picture; the screens name it
        before Resolve (each member carries `archive_only`), and Undo puts its file and its
        snapshotted catalog row back (restore_quarantined_duplicate).

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
            _telemetry.telem_bump("duplicates_resolved", len(quarantined), out_dir=out_dir)
        return jsonify({"quarantined": quarantined, "errors": errors,
                        "reclaimed_bytes": sum(q.get("size", 0) for q in quarantined)})

    @app.route("/api/duplicates/undo", methods=["POST"])
    @tier(LOGIN)
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
            _telemetry.telem_bump("duplicates_undone", out_dir=out_dir)
        return jsonify(result)

    @app.route("/api/account")
    @tier(LOGIN)
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
            for k in _cards.list_kaisuukens(session):
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
                                 "category": k.get("category") or "",
                                 # Session Y (#69): each expiry date and its count, for the
                                 # chip's peach underline and "N <kind> expire <date>" lines.
                                 "expiry_counts": k.get("expiry_counts") or []})
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
            cov = backup_coverage(db_path, out_dir, server_tasks)
            local_tasks, coverage = cov["local"], cov["pct"]
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
                            "coverage_pct": coverage, "coverage_note": cov["note"],
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
    @tier(LOGIN)
    def api_account_card_history():
        """Benefit-card (kaisuuken) usage. ?all=1 -> the lifetime type roster
        (kaisuuken_type_catalog); otherwise the recent usage events (list_kaisuuken_logs,
        forward-paginated via ?after=<cursor>). Read-only."""
        try:
            core, session = _gen_session()
            if request.args.get("all") in ("1", "true", "yes"):
                return jsonify(_cards.kaisuuken_type_catalog(session))
            after = request.args.get("after") or None
            return jsonify(_cards.list_kaisuuken_logs(session, first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/coupons")
    @tier(LOGIN)
    def api_account_coupons():
        """Coupons / Credit Boost. On-hand (available|locked) by default; ?history=1 swaps
        to redeemed|expired. Informational only -- no redeem/apply here by design. Read-only,
        forward-paginated via ?after=<cursor>."""
        try:
            core, session = _gen_session()
            history = request.args.get("history") in ("1", "true", "yes")
            statuses = _cards.COUPON_STATUSES_HISTORY if history else _cards.COUPON_STATUSES_ON_HAND
            after = request.args.get("after") or None
            return jsonify(_cards.list_extra_package_boosts(session, statuses=statuses,
                                                          first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/credit-log")
    @tier(LOGIN)
    def api_account_credit_log():
        """Full credit movement history (purchase/gift/spend/refund). Newest-first;
        BACKWARD-paginated via ?before=<cursor>. Read-only."""
        try:
            core, session = _gen_session()
            before = request.args.get("before") or None
            return jsonify(_cards.list_credit_log(session, last=_acct_count(30),
                                                before=before))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/stats")
    @tier(LOGIN)
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
        try:
            core, gsession = _gen_session()
            me = core.account_info(gsession)
            server_tasks = int((me.get("tasks") or {}).get("totalCount"))
        except Exception:                                    # noqa: BLE001
            server_tasks = None
        cov = backup_coverage(db_path, out_dir, server_tasks)
        return jsonify({"images": counts["images"], "videos": counts["videos"],
                        "collections": counts["collections"],
                        "local_tasks": cov["local"], "server_tasks": server_tasks,
                        "coverage_pct": cov["pct"], "coverage_note": cov["note"]})

    @app.route("/api/setup/save-key", methods=["POST"])
    @tier(LOCALHOST)
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
        body = request.get_json(silent=True) or {}
        key = (body.get("api_key") or "").strip()
        if not key:
            return jsonify({"error": "paste your API key first"}), 400
        from moonglade import backup as core
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
        # THE config.json path (core._config_path(), i.e. moonglade.paths.config_path()) --
        # never rebuilt by hand: a hand-built copy is how a test once wrote the checkout's real
        # file (2026-08-02), and it would stop matching the moment the code left the app folder.
        cfg_path = core._config_path()
        # Serialize against the account writers on core._accounts_lock. This is the only
        # config.json read-modify-write in the app that doesn't go through core's account
        # helpers (deliberately -- see the note above about the module-cached _cfg), which
        # made it the one writer that could lost-update: /api/users/add commits a new
        # account between this read and this write, and the write puts back a snapshot
        # that never had it, silently erasing the account. Same lock, so same queue.
        with core._accounts_lock:
            try:
                cfg = json.loads(_paths.decode_text(cfg_path.read_bytes())) \
                    if cfg_path.exists() else {}
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
                # The atomic writer (a temp, flushed, then swapped in): a write cut short here
                # would leave a torn config.json, which stops every start in the move
                # (moonglade.migrate) where 3.19 still started.
                core._save_config(cfg)
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
    @tier(LOGIN)
    def api_assets_status():
        """The asset container's current state: whether a (re)fetch is needed and,
        if a fetch is running/just finished/just failed, its live progress. LOGIN
        tier -- a read-only status poll, same trust class as /api/panel/status's
        non-sensitive half (this payload carries no host paths or account detail
        to redact, so unlike that route there is no local-vs-LAN split here).

        `needs` is computed fresh each call (moonglade.assets.needs_download(),
        a marker-file comparison, not a full re-hash) so a container that just
        finished downloading -- or was hand-copied in from another machine mid-
        session -- is reflected on the very next poll, not after a restart."""
        job = _asset_job.status()
        manifest = moonglade_assets.read_manifest()
        return jsonify({
            "needs": moonglade_assets.needs_download(_branding._container_path(), manifest),
            "manifest_present": manifest is not None,
            **job,
        })

    @app.route("/api/assets/fetch", methods=["POST"])
    @tier(LOGIN)
    def api_assets_fetch():
        """Start the asset container fetch. LOGIN tier (was LOCALHOST until
        2026-08-26): a signed-in LAN device may start it, because the Setup
        Wizard on a LAN device is exactly where a first run hits this -- it
        drives the checking -> downloading phases off /api/assets/status and
        this POST, and a localhost gate made that whole phase unreachable from
        the only machine that needed it.

        WHY IT DOESN'T BELONG WITH /api/setup/save-key. That neighbour writes a
        CALLER-SUPPLIED value into config.json (the file holding PIXAI_API_KEY /
        AUTH_SECRET_KEY / AUTH_USERS) -- the caller chooses what lands. This
        route chooses nothing: it pulls ONE fixed asset, pinned in
        moonglade/manifest.json to a single Release URL, verified against that
        manifest's sha256 cold before the swap, into one known path
        (_container_path()). No argument reaches it -- request body ignored --
        so a LAN caller cannot aim it at a different source, a different file,
        or a different destination. It is a fetch of a constant, not a write of
        an input.

        WHY REPEAT 685MB FETCHES AREN'T A LAN BANDWIDTH LEVER. AssetFetchJob's
        single-flight guard already blocks concurrency: start() takes self._lock
        and returns False while _state["status"] == "running", so a second call
        never launches a second thread -- it is the 409 below, matching
        /api/panel/run's own busy shape. One job at a time is the ceiling, and
        it was the ceiling before this tier change too; the gate was never what
        bounded the traffic."""
        started = _asset_job.start()
        if not started:
            st = _asset_job.status()
            if st["status"] == "running":
                return jsonify({"error": "a download is already running"}), 409
            return jsonify({"error": st.get("error") or "could not start"}), 200
        return jsonify({"ok": True})

    @app.route("/api/claim", methods=["POST"])
    @tier(LOGIN)
    def api_claim():
        """Claim ready daily rewards (free credits/stamina to the owner's OWN account -- no
        money moves). Login required; the header click IS the confirmation. One bad claim
        doesn't abort the rest. Returns {claimed, credits}.

        A successful claim also writes its own ACTIVITY TRACKER line (jobs.jsonl, which is
        what /api/jobs serves the tray). Written here rather than in the client because
        the tracker renders server truth -- a line added client-side would vanish on the
        next poll -- and because this route is the single seam both claim triggers funnel
        through: the header pill and the mascot popup share one `claim` in
        useClaimModal.js, which posts here. One hook, both paths, plus anything that
        claims later."""
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
                _telemetry.telem_bump("claims", claimed, out_dir=out_dir)   # Claimant
                # Terminal the moment it is written: a claim is instantaneous, so the row
                # is born "done" rather than passing through running. Its own id keeps it
                # out of the orphan sweep (which only chases numeric PixAI task ids) and
                # lets each claim keep its own line instead of overwriting the last one.
                _log_job("claim-" + secrets.token_hex(6), status="done", type="claim",
                         label=_achievements.claim_job_label(claimed, credits))
            return jsonify({"claimed": claimed, "credits": credits})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    _snips_lock = threading.Lock()

    def _snips_path(user):
        # The login's own folder (moonglade.paths.account_dir, a case-safe key, so "Nel" and
        # "nel" don't collapse onto one file the way a bare quote(username) did on NTFS).
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "snippets.json"

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
        """This account's snippets. (The old install-wide file was copied into every login
        with none of its own by the move, moonglade.migrate, and is gone.)"""
        return _read_snips_file(_snips_path(user))

    @app.route("/api/snippets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_snippets():
        """Prompt snippets/favorites, stored PER-ACCOUNT (accounts/<key>/snippets.json in the
        library's _moonglade/) so one signed-in account can't see or wholesale-clobber
        another's -- same split saved views already got. Login required (any session, local
        or LAN)."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        with _snips_lock:
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                # The explicit token, like every other per-account write
                # (dev/tests/test_csrf_coverage.py): checked before anything is read or written.
                if not _check_csrf(body):
                    return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
                snips = body.get("snippets")
                if not isinstance(snips, list):
                    return jsonify({"error": "snippets must be a list"}), 400
                clean = [str(s)[:800] for s in snips if str(s).strip()][:200]
                try:
                    # A temp beside it, then swapped in: a write cut short never leaves a
                    # torn snippets.json (the move reads a torn new home as damaged).
                    target = _snips_path(user)
                    tmp = target.with_name(target.name + ".tmp")
                    tmp.write_text(json.dumps(clean), encoding="utf-8")
                    os.replace(tmp, target)
                except OSError as e:
                    return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
                return jsonify({"snippets": clean})
            return jsonify({"snippets": _load_snippets(user)})

    _ach_lock = threading.Lock()

    @app.route("/api/contests")
    @tier(LOGIN)
    def api_contests():
        """The live PixAI contest board (community + official). Read-only PUBLIC data (not
        owner-private, no spend), so NOT localhost-gated -- the owner browsing over LAN still
        sees it. ?all=1 includes ended contests; default is only the currently-running ones.

        MEMOIZED for CONTESTS_TTL. Four surfaces mount this on open -- Contests, My Art,
        Publish and the mobile screen -- and each was pulling the live board over the
        network on every mount, which is the stall the owner reported on a modest machine
        (2026-09-03). A contest board changes over days; ninety seconds of staleness costs
        nothing and turns four page-open round trips into one. The two variants cache
        separately because they are different answers to different questions.

        Soft-fail semantics are unchanged, and a failure is NOT cached: an offline blip
        must not pin an empty board for the next minute and a half."""
        show_all = request.args.get("all") == "1"
        # The board's Refresh: one full walk that rewrites the settled-row cache.
        refresh = request.args.get("refresh") == "1"
        try:
            core, session = _gen_session()
            if refresh:
                rows, stale_at = _contest_sync.contest_board(core, session, force=True, full=True), None
            else:
                # A cold open answers from the saved list at once and refreshes behind it.
                rows, stale_at = _contest_sync.contest_board_swr(core, session)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "contests": []}), 200
        # Both variants come off the ONE snapshot -- `active` is the server's own
        # runtimeStatus flag, the same thing list_contests(active_only=True) filters on.
        contests = rows if show_all else [c for c in rows if c.get("active")]
        # Whether the board was longer than the ceiling the reader walks to (the screens say
        # so under the list; until now only a log line did).
        bm = _contest_sync.contest_board_meta()
        board = {"truncated": bool(bm.get("truncated"))}
        if board["truncated"]:
            board["limit"] = int(bm.get("limit") or 0)
            board["total_count"] = int(bm.get("total_count") or 0)
        out = {"contests": contests,
               "official": sum(1 for c in contests if c["type"] == "official"),
               "community": sum(1 for c in contests if c["type"] != "official"),
               "board": board}
        if stale_at is not None:
            out["stale"] = True               # the saved list; a walk is refreshing it
            out["saved_at"] = stale_at
        return jsonify(out)

    @app.route("/api/contests/qualify")
    @tier(LOGIN)
    def api_contests_qualify():
        """For the contest cards' "you've used ..." line (2026-11-18): per running contest with
        rules, each rule's {kind, need, used, unknown} -- how many of the models/LoRAs it
        requires are ones this library's pictures were made with (moonglade/contest_qualify.py
        says exactly what "used" can and cannot mean). Read-only; the model-version reads it
        needs are capped, paced and kept a day. Soft-fails to {} like /api/contests."""
        from moonglade import contest_qualify as _cq
        try:
            core, session = _gen_session()
            rows = [c for c in _contest_sync.contest_board(core, session) if c.get("active")]
            return jsonify({"contests": _cq.board_qualify(core, session, rows, db_path)})
        except Exception as e:                           # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200], "contests": {}}), 200

    @app.route("/api/contest/<slug>/artworks")
    @tier(LOGIN)
    def api_contest_artworks(slug):
        """One page of a contest's public entries -> the detail view's preview grid.

        `?page=N` (default 1). Thumbnails are built from each row's mediaId with the same
        `/v1/media/{id}/thumbnail` pattern list_contests already uses for cover art -- the
        entries are other people's artworks, so there is nothing local to serve. Only what
        the preview renders comes back (id, author name, thumb): the raw upstream rows
        carry more, and none of it is needed to draw eight squares.

        Soft-error-as-200 with an empty list, matching /api/contests: a contest board
        hiccup must not turn a detail view into an error page."""
        try:
            page = max(1, int(request.args.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            core, session = _gen_session()
            env = _contests.contest_artworks(session, slug, page=page)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200],
                            "entries": [], "total_count": 0, "total_page": 0}), 200
        entries = []
        for r in env.get("data") or []:
            mid = str(r.get("mediaId") or "")
            entries.append({
                "id": str(r.get("id") or ""),
                "author_name": str(r.get("authorName") or ""),
                "thumb": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
            })
        return jsonify({"entries": entries,
                        "total_count": int(env.get("totalCount") or 0),
                        "total_page": int(env.get("totalPage") or 0)})

    @app.route("/api/contest/<slug>/winners")
    @tier(LOGIN)
    def api_contest_winners(slug):
        """The winners of one contest -> the detail view's winners strip.

        Empty until the contest's result date: PixAI answers a running contest with an
        empty array rather than an error, which is exactly the "not decided yet" the strip
        needs to stay hidden on. The caller is expected to ask only once result_at has
        passed; asking early is simply empty, never wrong.

        `mine` marks the owner's own row (the design's YOU chip) by comparing authorId to
        the authenticated account -- the id never reaches the client. `rank` is the row's
        real PRIZE TIER (its `entry.rank`: 1, 2 or 3, shared by every winner in that tier)
        and `prize_amount` what that tier paid (PROBE 2026-09-29). It used to be the row's
        position in the list and 0, which on a 65-winner podium read as places 1 to 65 with
        no prize. A row that carries no placement gets rank 0 (unknown), never a guess.
        Soft-error-as-200, like every other read on this surface."""
        try:
            core, session = _gen_session()
            rows = _contests.contest_winners(session, slug)
            uid = str(_pixai_client._client_of(session).user_id or "")
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "winners": []}), 200
        winners = []
        for w in rows or []:
            ent = contest_wins.entry_of(w)
            rank = ent["rank"] if ent and ent["rank"] else 0
            prize = ent["prize"] if ent else 0
            mid = str(w.get("mediaId") or "")
            aid = str(w.get("authorId") or "")
            winners.append({
                "id": str(w.get("id") or ""),
                "rank": rank,
                "author_name": str(w.get("authorName") or ""),
                "thumb": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
                "prize_amount": prize,
                "mine": bool(uid and aid == uid),
            })
        return jsonify({"winners": winners})

    @app.route("/api/contest/mine")
    @tier(LOGIN)
    def api_contest_mine():
        """This account's own contest entries, grouped by contest -> the My entries tab.

        TELEMETRY-DERIVED AND INSTANT. The entry record already lives locally (the same
        dedupe sets every entry path writes), so this route performs exactly ONE upstream
        call -- a single page of the contest board, purely to put titles and dates on the
        rows. It deliberately does not re-poll PixAI per contest: that is the detection
        sweep's job, on its own schedule, and a tab that fired N network calls on open
        would be unusable with twenty contests in flight.

        A failed board read is soft: the rows still come back, keyed by contest id with
        empty titles, because knowing you have entries somewhere beats an error page.

        Thumbs come from the local catalog by artwork_id (see artwork_media_ids); an
        artwork the library does not hold gets no thumb rather than a broken image.

        `won` is contest FACT and belongs on this surface -- the DC's results rows show
        it -- and since L3 it means VERIFIED: PixAI's own winners list carried the entry
        with an integer tier. `wins` lists them (tier, prize, how it was verified, the
        receipt link), `check` says where the daily check stands for the contest, and
        `unverified_legacy` marks a contest an older sweep once believed won that no check
        has confirmed yet. No metric name and no ladder language appears in this payload."""
        d = _telemetry.load_telemetry(out_dir)
        sets = d.get("sets") if isinstance(d.get("sets"), dict) else {}
        raw_keys = sets.get("contest_entry_keys")
        raw_legacy = sets.get("contest_win_keys")
        legacy_ids = {str(w) for w in raw_legacy} if isinstance(raw_legacy, list) else set()
        _e, _l, verified, checks = _contest_sync._cw_inputs(d)
        now_t = time.time()
        by_contest, order = {}, []
        for k in (raw_keys if isinstance(raw_keys, list) else []):
            cid, _, aid = str(k).partition(":")
            if not cid or not aid:
                continue
            if cid not in by_contest:
                by_contest[cid] = []
                order.append(cid)
            if aid not in by_contest[cid]:
                by_contest[cid].append(aid)
        board = {}
        try:
            core, session = _gen_session()
            # Titles only: the saved list is good enough, so this never waits on a walk.
            for c in _contest_sync.contest_board_swr(core, session)[0] or []:
                if isinstance(c, dict) and c.get("id"):
                    board[str(c["id"])] = c
        except Exception:                       # soft: key-only rows beat an error page
            board = {}
        thumbs = {}
        try:
            thumbs = artwork_media_ids(db_path, [a for cid in order for a in by_contest[cid]])
        except Exception:
            thumbs = {}
        rows = []
        shown_by_contest = {}
        for cid in order:
            c = board.get(cid) or {}
            aids = by_contest[cid]
            # No dedupe here, and the reason is worth keeping: media_id is the catalog's
            # PRIMARY KEY, so artwork_id -> media_id is injective and two keys can NEVER
            # resolve to one piece. The "defensive dedupe" that used to sit here could not
            # fire on any real store. The legacy double-key it was meant to cover is
            # healed where the truth actually is -- in the sweep, which sees both ids on
            # the upstream row and can discard the stale one.
            shown = list(aids)
            shown_by_contest[cid] = shown
            rows.append({
                "contest_id": cid,
                "slug": str(c.get("slug") or ""),
                "title": str(c.get("title") or ""),
                "type": str(c.get("type") or ""),
                "end_at": str(c.get("end_at") or ""),
                "result_at": str(c.get("result_at") or ""),
                "active": bool(c.get("active")),
                "url": str(c.get("url") or ""),
                "entry_artwork_ids": shown,
                "entries": [{"artwork_id": a, "media_id": thumbs.get(a, ""),
                             "thumb": ("/thumbs/%s.jpg" % thumbs[a]) if thumbs.get(a) else ""}
                            for a in shown],
                "won": bool(contest_wins.wins_for(verified, cid)),
                "wins": contest_wins.wins_for(verified, cid),
                "check": _contest_sync._cw_check_view(checks.get(cid), now_t),
                "unverified_legacy": bool(cid in legacy_ids
                                          and not contest_wins.wins_for(verified, cid)),
            })
        return jsonify({"contests": rows,
                        "total_entries": sum(len(shown_by_contest[cid]) for cid in order),
                        "sync_running": bool(_contest_sync._contest_sync_lock.locked()),
                        "last_sync_at": _contest_sync._contest_sync_last_ok.get("at", 0.0)})

    @app.route("/api/contest/enter", methods=["POST"])
    @tier(LOGIN)
    def api_contest_enter():
        """Enter one already-published artwork into a PixAI contest.

        ALWAYS-CONFIRM, and deliberately stronger than the house preview-first default:
        every submit gets an explicit confirm step, no exceptions (owner ruling F4,
        2026-08-31 contest-surface workshop). PixAI exposes no un-enter route, so there is
        no such thing as an entry worth firing without the owner saying so twice. Without
        `confirm: true` this route performs NO network call and returns what it WOULD do.

        `spends_credits` is None, NOT False. The contest contract declares an
        INSUFFICIENT_CREDITS error for this operation and no entry has ever been submitted
        to measure whether one is charged, so the honest answer is "unknown". False would
        be a promise the code cannot keep, on a screen a user reads before an irreversible
        action.

        THE CONTEST ID IS RESOLVED SERVER-SIDE, from the live board by slug -- a `contest_id`
        in the body is accepted and ignored. The id is what the ladder dedupes on, and the
        set it lands in is grow-only: a client that sent a wrong, stale or invented one would
        write a key nothing can ever correct. The board read is also what makes an unknown
        slug a 400 here rather than an upstream refusal later.

        LOGIN tier, not LOCALHOST: this is the owner managing their OWN account, the same
        class as publishing and claiming. CSRF: explicit-token class, matching
        /api/myart/publish -- a real account mutation triggered by one web click.
        READ_ONLY in config.json refuses the confirmed form regardless, inside core."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slug = str(body.get("slug") or "").strip()
        artwork_id = str(body.get("artwork_id") or "").strip()
        if not (slug and artwork_id):
            return jsonify({"error": "slug and artwork_id are both required"}), 400
        if not body.get("confirm"):
            return jsonify({"preview": True, "slug": slug, "artwork_id": artwork_id,
                            "spends_credits": None, "irreversible": True})
        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s"
                                     % _redact_host_paths(str(e))[:160]}), 502
        try:
            board = _contest_sync.contest_board(core, session)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 502
        contest_id = next((str(c.get("id") or "") for c in board or []
                           if isinstance(c, dict) and str(c.get("slug") or "") == slug), "")
        if not contest_id:
            return jsonify({"error": "unknown contest"}), 400
        try:
            resp = _contests.contest_enter(session, slug, artwork_id)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 502
        # A 2xx that says success:false is a refusal wearing a success code. Default True
        # for any other shape -- the response body is documented as {success} but only the
        # error paths were ever seen live, so absence must not read as failure.
        if isinstance(resp, dict) and not resp.get("success", True):
            return jsonify({"error": "the contest refused the entry"}), 502
        # OUTSIDE the try, silent-soft: the entry is already live and irreversible by the
        # time we get here, so a telemetry hiccup must never be reported as a failed entry.
        # Same key shape the detection sweep writes -- one dedupe set, so entering the same
        # artwork twice still counts once.
        try:
            _telemetry.telem_set_add("contest_entry_keys", "%s:%s" % (contest_id, artwork_id),
                          out_dir=out_dir)
        except Exception:
            pass
        return jsonify({"entered": True, "slug": slug, "artwork_id": artwork_id})

    @app.route("/api/contest/sync", methods=["POST"])
    @tier(LOGIN)
    def api_contest_sync():
        """Re-read this account's contest entries and wins from PixAI (see
        _contest_detection_sync). Catches entries made on pixai.art and wins decided while
        the app was closed -- neither of which produces any local event to hook.

        CSRF REQUIRED, like every sibling POST on this surface. It reaches PixAI with the
        owner's credentials on a cross-site-triggerable POST, which is what the token is
        for. (An earlier version of this docstring said the opposite; it described a route
        that no longer existed by the time anyone read it.)

        Single-flight via a module lock, and the answer is a STATE rather than a refusal --
        there is nothing for a caller to retry when a sweep is already running:
          {started: true}                     -- one is now running on its own thread
          {started: false, skipped: "recent"} -- one ran recently; nothing to do
          {started: false, busy: true}        -- one is already in flight
        Completion is NOT reported here: the sweep outlives this request. The client
        watches `sync_running` on /api/contest/mine instead.

        ONE count comes back, and only one. contest_wins is deliberately absent -- it is a
        hidden-only metric, and even a zero here would tell a reader that a win is something
        this app counts. What the sets contain never leaves the store either.

        CSRF, since 2026-09-03: every sibling POST on this surface carries the explicit
        token, and this one did not. It reaches PixAI with the owner's credentials on a
        cross-site-triggerable POST, which is exactly the shape the token exists for --
        cheap to add, and it makes the surface uniform instead of one-route-special.

        RETURNS IMMEDIATELY. The sweep runs on its own thread; the answer says whether one
        STARTED (or was skipped as recent, or was already busy), and the client watches
        /api/contest/mine's `sync_running` for completion."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        m = _telemetry.telemetry_metrics(out_dir)
        entries = int(m.get("contest_entries", 0) or 0)
        # RECENT: nothing to do, and nothing to wait for.
        if (time.time() - _contest_sync._contest_sync_last_ok.get("at", 0.0)) < _contest_sync.CONTEST_SYNC_RECENT_S:
            return jsonify({"started": False, "skipped": "recent",
                            "contest_entries": entries})
        if not _contest_sync._contest_sync_lock.acquire(False):
            return jsonify({"started": False, "busy": True, "contest_entries": entries})

        def _run():
            try:
                _contest_sync._contest_detection_sync(out_dir)
            finally:
                _contest_sync._contest_sync_lock.release()

        # OFF-THREAD, and this is the whole point: the sweep is paced (a third of a second
        # between contests, plus a read each) and can run 30-90 seconds against a real
        # board. It was doing that INSIDE the request, so opening the Contests overlay held
        # a worker and the browser's connection for the duration -- on a slow board the
        # overlay simply hung. The client watches /api/contest/mine's sync_running flag
        # instead, which costs a local telemetry read.
        try:
            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:                   # noqa: BLE001
            # The lock is acquired HERE and released by the thread, so a thread that never
            # starts would leave contest sync permanently "busy" for the life of the
            # process -- every later open answering busy:true forever. Release it here and
            # say what happened. (Found by its own test, which stubs Thread.start.)
            _contest_sync._contest_sync_lock.release()
            return jsonify({"started": False,
                            "error": _redact_host_paths(str(e))[:200],
                            "contest_entries": entries}), 200
        return jsonify({"started": True, "contest_entries": entries})

    @app.route("/api/contest/check", methods=["POST"])
    @tier(LOGIN)
    def api_contest_check():
        """The Check button (E4, L3): "it won but isn't shown". The owner pastes the link to an
        entry (or to its contest) and presses Check; the app reads that contest's winners
        ONCE and records a win ONLY when the entry's artwork id is in the list with an integer
        tier rank and the author is this account. The link is kept as the receipt. Nothing else
        counts: no self-reported wins, no name-alike, no empty list read as "lost" (it reads as
        "not published yet").

        Body: {csrf, url, contest_id?, slug?}. `contest_id` is a contest from the account's
        own entries (the picker); `slug` a contest typed in; either may be left off when the
        link names the contest or the app already recorded the linked artwork's contest. The
        answer is always 200 with {verified, state, message, wins[]} -- a miss is an answer,
        not an error; `state` is one of verified, undecided, not_found, no_placement,
        not_yours, not_pixai, no_link, no_contest, failed, cooldown.

        LOGIN tier, CSRF required (it reaches PixAI with the owner's credentials on a
        cross-site-triggerable POST, like /api/contest/sync). It is a GET of PixAI's winners
        list and nothing else: there is no write to PixAI on this road, so READ_ONLY has
        nothing to refuse. Only pixai.art links are accepted, the slug is shape-checked
        before it becomes a path, and a contest is not re-read within a few seconds."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        status, payload = _contest_sync.contest_win_check(out_dir, body)
        return jsonify(payload), status

    @app.route("/api/artwork-views")
    @tier(LOGIN)
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
    @tier(LOGIN)
    def api_your_art():
        """'Your Art' panel: the owner's top published works plus the library's real
        lifetime totals. Pure CATALOG read -- no network, no spend, works over LAN.

        THIS ROUTE USED TO MAKE TWELVE LIVE GRAPHQL CALLS ON EVERY OPEN, six at a time,
        to fetch view counts that no column existed for -- the lag saga, and the reason the
        panel could only ever report a "top 12" subtotal. PROBE_2026-09-06 established that
        the ad-hoc bulk `artworks(authorId, first:N)` query accepts `views`, so
        --sync-artworks now sweeps them into the catalog in a handful of paced calls and
        this route reads a column like every other number on the panel.

        That is not merely faster, it is more HONEST in two ways. The totals are now
        lifetime sums over the whole published library rather than a dozen rows. And the
        same probe measured that reading a view count COSTS a view -- so the old design
        inflated the owner's own twelve most-looked-at works by twelve views every single
        time he opened the panel to look at them. A sweep he runs deliberately still costs
        one view per work, but bounded to that sweep instead of to his curiosity.

        `views_synced` now means "the catalog has been swept", not "the live calls
        happened to succeed"; `?order=views` ranks by views instead of likes.

        No `_is_authorized_request()` conjunct here: this whole route is now covered by the
        global front-door hook (see _enforce_front_door()'s docstring), so reaching this line
        already guarantees it -- an explicit re-check here would be dead-always-true, the same
        class of redundant check removed from the 43 individually-gated routes."""
        order = "views" if (request.args.get("order") or "") == "views" else "likes"
        try:
            limit = max(1, min(int(request.args.get("limit") or 12), 200))
        except (TypeError, ValueError):
            limit = 12
        totals = _living.published_totals(db_path)
        top = _living.top_published_rows(db_path, limit, order=order)
        views_synced = totals.get("views_rows", 0) > 0
        for r in top:
            # '' and 0 are different answers (see myart_items): a never-swept row must not
            # render as a real zero, so it goes to the client as null.
            swept = (r.pop("views_raw", "") or "") != ""
            r["views"] = r["views"] if swept else None
            for k in ("views_prev", "views_at", "views_prev_at"):
                r.pop(k, None)
        return jsonify({"items": top, "totals": totals, "views_synced": views_synced,
                        "views_at": totals.get("views_at", ""),
                        # The blow-up note's payload. A LIST, capped, never a feed --
                        # see published_spikes() and views_spike().
                        "spikes": _living.published_spikes(db_path)})

    @app.route("/api/myart/items")
    @tier(LOGIN)
    def api_myart_items():
        """Card-ready rows for the My Art tabbed gallery (Frontend Gallery.dc.html's
        ovMyArt, rebuilt 2026-08-06): every catalog row that exists as a PixAI ARTWORK
        (artwork_id set by --sync-artworks), public AND private -- the design's
        Visibility filter distinguishes them ('everything you've made, published or
        held back'). Pure catalog read, no network: title/likes/comments/tags/nsfw
        arrive via --sync-artworks; thumbs are the local /thumbs/<mid>.jpg the grid
        already serves. The Artworks/Animations tab split is the is_video flag.

        `coverage` rides along (#42) so the overlay's empty state can say WHY it is
        empty: an unsynced library and a genuinely unpublished one produce the same
        zero rows here, and only the catalog-wide counts separate them. See
        myart_coverage()."""
        # First read on a library with no history yet: take today's reading now, so the window
        # has a baseline from the first open (a same-day rewrite is harmless).
        win, window = myart_window(db_path)
        if not window["seen"]:
            record_artwork_snapshots(db_path)
            win, window = myart_window(db_path)
        items = []
        for r in myart_items(db_path):
            mid, title, preview = r["media_id"], r["title"], r["prompt_preview"]
            created, tags = r["created_at"], r["art_tags"]
            items.append({
                "media_id": mid, "artwork_id": r["artwork_id"],
                "title": (title or "").strip() or (preview or "").strip()[:60] or mid,
                "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": r["is_video"] == "1", "is_nsfw": r["is_nsfw"] == "1",
                "date": (created or "")[:10],
                "created_at": created or "",
                "tags": [t.strip() for t in (tags or "").split(",") if t.strip()][:4],
                "public": r["is_published"] == "1",
                "sensitive": r["is_sensitive"] == "1",
                "likes": r["likes"], "comments": r["comments"],
                # null (never swept) vs 0 (swept, nobody looked) -- the card draws a
                # dash for the first and a real 0 for the second.
                "views": r["views"] if (r["views_raw"] or "") != "" else None,
                "views_30": win.get(r["artwork_id"], {}).get("views"),
                "likes_30": win.get(r["artwork_id"], {}).get("likes", 0),
            })
        # The card actions POST to /api/myart/publish, which is in the explicit-token
        # CSRF class; MG_BOOT doesn't carry the token, so it rides along here rather
        # than making the overlay fetch the whole Control Panel summary for one field.
        return jsonify({"items": items, "csrf": session.get("csrf", ""),
                        "coverage": myart_coverage(db_path),
                        # the All time / 30 days switch: `window` says whether the 30 is a full
                        # 30 days or only "since <date>" (history starts the day this shipped)
                        "window": window})

    @app.route("/api/myart/publish", methods=["POST"])
    @tier(LOGIN)
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
        row = artwork_row(db_path, mid)
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
        if action == "delete":
            publish_state(db_path, mid, artwork_id="", published=False)
        else:
            changed = {}
            if action == "publish":
                changed["artwork_id"] = result.get("artwork_id") or ""
                changed["published"] = not private
                # PUBLISH-AND-ENTER. Attaching `challenge` to the publish mutation does
                # NOT enter a contest -- found live 2026-09-01 (owner: "publish AND enter
                # from the publish NAV did not work; I published and then did the entry
                # successfully"). extra.challenge is artwork METADATA, the back-link
                # listArtworks returns on node.extra; the entry itself is a separate REST
                # call (POST /v2/contest/{slug}/artwork), which is exactly what the
                # working direct-entry path does. This publish path never made it, so the
                # contest row's "entering at publish is free" was a promise about
                # something that never happened.
                #
                # So make it happen: the artwork exists now and has an id, which is the
                # one thing the entry call needs. The client sends the contest ID (the
                # select's own value) and contest_enter needs the SLUG, so the board is
                # read to translate -- and that read doubles as validation, since an id
                # that is not on the board cannot be entered anyway.
                #
                # HONEST PARTIAL SUCCESS: the publish already happened and is
                # irreversible, so an entry failure can never turn this into a 502. It
                # comes back as {published: true, entry_error: ...} and the client says
                # both halves. Single attempt -- contest_enter is single-shot by
                # construction and READ_ONLY-guarded; a retry here would risk a second
                # entry for one click.
                challenge = str(body.get("challenge") or "")
                new_art_id = str(result.get("artwork_id") or "")
                if challenge and new_art_id:
                    try:
                        slug = next((str(c.get("slug") or "")
                                     for c in (_contest_sync.contest_board(core, session) or [])
                                     if isinstance(c, dict)
                                     and str(c.get("id") or "") == challenge), "")
                        if not slug:
                            result["entry_error"] = ("couldn't find that contest on the "
                                                     "board — the artwork was published, "
                                                     "but not entered")
                        else:
                            resp = _contests.contest_enter(session, slug, new_art_id)
                            if isinstance(resp, dict) and not resp.get("success", True):
                                result["entry_error"] = "the contest refused the entry"
                            else:
                                result["entered"] = True
                                # RECORD IT HERE. This path answered entered:true and wrote
                                # nothing, leaning on the sweep below -- which silently
                                # no-ops when the single-flight lock is held (a sweep from
                                # the overlay, or the previous publish's own kick). The
                                # entry then existed on PixAI and nowhere locally until
                                # some later sweep happened to catch it. The sweep is
                                # reconciliation; the path that KNOWS an entry just
                                # succeeded is the one that should say so. Same key shape
                                # every other writer uses -- artwork id, so the set dedupes
                                # against the sweep's own row rather than double-counting.
                                try:
                                    _telemetry.telem_set_add("contest_entry_keys",
                                                  "%s:%s" % (challenge, new_art_id),
                                                  out_dir=out_dir)
                                except Exception:
                                    pass
                    except Exception as e:                    # noqa: BLE001
                        result["entry_error"] = _redact_host_paths(str(e))[:200]
                elif challenge:
                    result["entry_error"] = ("the publish returned no artwork id, so the "
                                             "contest entry could not be made")
                # Then the detection sweep, which reads the truth back from PixAI: the
                # ladder counts what PixAI says happened, not what this route believes.
                # Off-thread and outside the try above, so nothing it does can delay this
                # response or turn an irreversible publish into a failure.
                if challenge:
                    try:
                        threading.Thread(target=_contest_sync._contest_sync_kick,
                                         args=(out_dir,), kwargs={"force": True},
                                         daemon=True).start()
                    except Exception:
                        pass
            if private is not None:
                changed["published"] = not private
            if tags is not None:
                changed["art_tags"] = ", ".join(
                    str(t).lstrip("#").strip() for t in tags)
                # Lamplighter (curation_streak) + The Long Vigil: tagging is curation.
                # Keyed day-lists, idempotent, silent-soft.
                try:
                    _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
                except Exception:
                    pass
            if title is not None:
                changed["title"] = title
            publish_state(db_path, mid, **changed)
        # THE PUBLISH KICK (the living library, owner call 2). publish_state above wrote
        # what THIS route believes into THIS machine's catalog, and nothing else on earth
        # heard about it: publishing is a local UPDATE, and the only way any install learns
        # a publish is by re-reading PixAI's own list. So re-read it, now -- the machine the
        # owner published from is authoritative at once instead of within one sweep, and
        # what lands in the catalog is what PixAI says, not what this route assumed.
        #
        # Forced (past the fifteen-minute guard), off-thread and outside the try above, for
        # the same reasons the contest sweep's own publish kick is: nothing it does may
        # delay this response or turn an irreversible publish into a failure. Fires for
        # unpublish, re-tag and delete too -- each is a change to what listArtworks returns.
        #
        # Scheduled, even though a click reached this route: what the owner pressed was
        # Publish, and he has the publish's own answer in front of him. The sweep is the
        # library keeping itself honest afterwards, so it belongs in the Activity window
        # rather than in a second corner notice about a job he never started (owner's
        # walk, 2026-09-07).
        try:
            _artworks_kick(force=True, scheduled=True)
        except Exception:                                    # noqa: BLE001
            pass
        result["unmatched_tags"] = unmatched
        return jsonify(result)

    def _lineage_card(row):
        """One image reduced to a lineage chip: id, thumb, video flag, and a title hint."""
        mid = row["media_id"]
        return {"media_id": mid, "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": (row["is_video"] == "1"),
                "title": (row["title"] or "").strip() or (row["prompt_preview"] or "").strip()[:48]}

    @app.route("/api/lineage/<media_id>")
    @tier(LOGIN)
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
        tree = lineage(db_path, mid)
        if tree is None:
            return jsonify({"error": "unknown media id"}), 404
        parent = tree["parent"]
        return jsonify({
            "media_id": mid,
            "siblings": [_lineage_card(r) for r in tree["siblings"]],
            "parent": (dict(_lineage_card(parent), kind=parent["kind"])
                       if parent else None),
            "children": [dict(_lineage_card(r), kind=r["kind"])
                         for r in tree["children"]],
        })

    @app.route("/api/siblings", methods=["POST"])
    @tier(LOGIN)
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
            for r in sibling_media(db_path, ids):
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

    @tier(LOGIN)
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
            by_task_idx, by_sid = _series.series_index(db_path)
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

    @tier(LOGIN)
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
        _, by_sid = _series.series_index(db_path)
        s = by_sid.get(str(sid or "").strip())
        if not s:
            return jsonify({"error": "unknown series id"}), 404
        return jsonify(s)

    @tier(LOGIN)
    @app.route("/api/batch/<task_id>")
    def api_batch_detail(task_id):
        """One BATCH's struct in the SAME shape /api/series/<sid> returns.

        Owner ruling, 2026-09-07: a batch card opens in the SERIES modal now,
        "separately tagged so you know what you're looking at, batch or series" --
        it no longer takes the library over the way the ?batch= drill-down did. One
        modal wants one payload shape, so this answers the series struct: a batch is
        simply a series of ONE run, so `steps` holds exactly one entry, count_tasks
        is 1, and its label is "one generation" rather than a dial-in delta.

        The rows are the task's SURVIVING catalog rows -- read through query_catalog's
        own `batch` predicate, which is `(batch = ? OR task_id = ?)`, so this and the
        pictures listing the modal fetches next (/api/library?batch=<id>) see
        exactly the same set and their counts cannot disagree. Order is #33's batch
        order (batch_member_order).

        404 for an unknown id AND for a LONE image: one surviving row is not a batch.
        The grouped grid marks a batch stack only at >= 2 survivors (see the folded-BATCH
        arm of /api/library), so nothing can open one -- answering 200 here would
        invent a stack the library never draws. Pure catalog read, no network."""
        tid = str(task_id or "").strip()
        rows = []
        if tid:
            rows, _ = query_catalog(db_path, batch=tid, page_size=None)
        if len(rows) < 2:
            return jsonify({"error": "unknown batch id"}), 404
        rows = batch_member_order(rows)
        first = rows[0]
        # The title is derived the way a series' is (_series_title over the same
        # capped prompt text), so the two stack kinds name themselves by one rule;
        # the row's own `title` column is the fallback when the prompt says nothing.
        title = _series._series_title(_series._series_text(first)) or str(first.get("title") or "").strip()
        stamps = sorted(str(r.get("created_at") or "") for r in rows
                        if str(r.get("created_at") or ""))
        return jsonify({
            "sid": tid,                 # the modal keys on this the same way it does a sid
            "task_id": tid,
            "title": title,
            "model": (str(first.get("model_name") or "")
                      or str(first.get("model_id") or "")),
            "count_tasks": 1,
            "count_images": len(rows),
            "span": [stamps[0], stamps[-1]] if stamps else ["", ""],
            "steps": [{
                "task_id": tid,
                "v": 1,
                "reroll": False,
                "label": "one generation",
                "first_media_id": str(first.get("media_id") or ""),
                "n": len(rows),
            }],
        })

    @app.route("/api/train/recent-tasks")
    @tier(LOGIN)
    def api_train_recent_tasks():
        """Recent generations grouped by task, for the mobile Train dataset picker
        (Moonglade Mobile.dc.html's 'tap a task, it adds its images' tile grid). Desktop's
        picker selects individual images one at a time; the mobile design picks whole
        TASKS instead -- each tile is one generation, tapping it adds every real sibling
        image from that batch. The design's own mock assumes every task contributes
        exactly 4 images (a fixed demo constant); real batches are 1-4, so this returns
        each task's REAL image count and media_id list rather than a hardcoded number --
        the mobile picker's running total is a sum of real counts, not tiles*4.

        PAGES BY TASK (issue #56): `next_before` is the cursor for the page below this one
        (null when there is nothing older); the picker sends it back as `before_at` +
        `before_task` when its sentinel scrolls into view, the desktop pool's mechanism.
        Pure catalog read, no network."""
        try:
            limit = max(1, min(int(request.args.get("limit") or 18), 60))
        except ValueError:
            limit = 18
        at = (request.args.get("before_at") or "").strip()
        before = {"at": at, "task": (request.args.get("before_task") or "").strip()} \
            if at else None
        page, nxt = recent_train_task_page(db_path, limit, before,
                                           (request.args.get("q") or "").strip())
        tasks = [dict(t, thumb="/thumbs/%s.jpg" % t["media_ids"][0]) for t in page]
        return jsonify({"tasks": tasks, "next_before": nxt})

    @app.route("/api/train/quota")
    @tier(LOGIN)
    def api_train_quota():
        """How many FREE LoRA trainings this account can use (PixAI's membership quota
        `free::user_lora_training`, counted only for a member -- core.training_free_quota).
        A training free card is the other free road; the submit preview checks for one per
        base (core.match_training_kaisuuken). Read-only, free."""
        try:
            core, session = _gen_session()
            return jsonify({"free_trainings": _training.training_free_quota(session)})
        except Exception as e:
            return jsonify({"free_trainings": 0,
                            "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/train/models")
    @tier(LOGIN)
    def api_train_models():
        """Trainable base models grouped by architecture (the train panel's Model Type ->
        Model Theme picker). Read-only, free. Each model carries the VERSION id the submit
        needs, its real title, and a cover -- fixing the earlier build, which used the
        generic market search and rendered raw model ids with no architecture grouping.

        Off PixAI's own training config (core.training_config: /config/trainLoraModels,
        cached, the 2026-09-26 snapshot as fallback), so Tsubaki.3 (DiT.3) is offered and
        priced. `default_version_id` is the base the panel pre-selects -- the first SDXL
        row, PixAI's own default (SCOPE_2026-09-26 E7) -- not the first group's first
        model, which with DiT.3 listed first would be the 100,000-credit base."""
        try:
            core, session = _gen_session()
            cfg = _training.training_config()
            pause = _training.training_pause()
            return jsonify({"groups": _training.list_trainable_base_models(config=cfg),
                            "pricing": cfg["pricing"],
                            "default_version_id": _training.default_training_base(cfg),
                            # Session J: the Recommended tab (6a), Advanced's two bases, the
                            # four goals, PixAI's own estimate at its default length, the set
                            # rule, and its pause switch -- all read here, nothing written
                            "recommended_arch": _training.TRAIN_RECOMMENDED_TYPE,
                            "advanced_bases": _training.advanced_training_bases(cfg),
                            "goals": [{"value": v, "label": lab} for v, lab in _training.TRAIN_GOALS],
                            "eta": _training.training_eta(
                                _training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
                            "image_constraints": cfg["image_constraints"],
                            "min_images": _training.TRAIN_MIN_IMAGES,
                            "max_images": _training.TRAIN_MAX_IMAGES,
                            "paused": pause is not None,
                            "resumes_at": (pause or {}).get("resumes_at") or ""})
        except Exception as e:
            return jsonify({"groups": [], "error": _redact_host_paths(str(e))[:200]}), 200

    import requests as _rq

    @app.route("/api/train/cover")
    @app.route("/api/pixai-cdn/thumb")   # the general name -- covers My Art's LoRA cards too
    @tier(LOGIN)
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
        if not pixai_cdn_url_ok(raw):
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
            # Someone else's file under this origin: a cover that is not a raster
            # picture goes out as a download, never as a page.
            return harden_file_response(resp, _up.urlparse(raw).path.rsplit("/", 1)[-1])
        except Exception:
            return ("fetch failed", 502)

    _basic_start_lock = threading.Lock()

    def _reuse_ok(core, session, dataset_task_id, media_ids):
        """Is this Basic start a REUSE of an earlier set (PixAI's `reuse` price, sent as
        `trainingTaskId` with no images)? Only for a FINISHED Basic run that made a LoRA --
        found in the account's own LoRA list, the list the import shows -- and only when the
        posted images are exactly that run's set, same length, same ids (the site's own
        check; spend review, finding 7). Anything else, a failed read included, is a fresh
        set priced and sent in full. Never raises."""
        try:
            loras = _training.list_my_trained_loras(session, pages=5)
        except Exception:                               # noqa: BLE001
            return False
        posted = [str(m) for m in (media_ids or [])]
        for m in loras:
            t = m.get("task") or {}
            if str(t.get("id") or "") != str(dataset_task_id):
                continue
            if t.get("trainingMode") == "advanced" or str(t.get("status") or "") != "completed":
                return False
            ds = [str(x) for x in ((t.get("parameters") or {}).get("mediaIds") or [])]
            return (len(ds) == len(posted) and len(set(posted)) == len(posted)
                    and set(ds) == set(posted))
        return False

    @app.route("/api/train/submit", methods=["POST"])
    @tier(LOGIN)
    def api_train_submit():
        """Submit a Basic LoRA training task -- PREVIEW-FIRST, like /api/myart/publish.

        Without `confirm: true` this makes NO mutating call: it validates the request
        with the site's own rules and reports the real cost position (how many free
        trainings remain, whether a training free card covers it, what it costs).

        VALIDATION (SCOPE_2026-09-26 E7), before anything else: PixAI's trigger-word rules
        on the normalized string (core.validate_training), and its image rule over this
        catalog's own image sizes (core.check_training_images). An image the rule refuses
        refuses the whole run, named; an image whose size the catalog does not know is
        listed as not checked, never passed as checked.

        A REUSED SET (Session J 2a, 2026-09-28). `dataset_task_id` names an earlier Basic run
        whose set the grid holds exactly (imported whole); when _reuse_ok confirms it, the run
        is priced at PixAI's `reuse` tier and sent as PixAI's own page sends it --
        `trainingTaskId` and no images. Anything that is not exactly such a set is a fresh run,
        priced and sent in full; the preview says which (`reuse`, `price_reason`).

        COST. PixAI's train pages price a run from the same config the base list comes
        from (core.training_config -- `price` for a fresh dataset, `reuse` for a reused one).
        A run is FREE when either
          * the account is a member (membership tier present, 0 included) with free-training
            quota left -- it consumes one quota unit; or
          * a training free card matches the base (core.match_training_kaisuuken, checked
            only when the quota does not cover the run -- a deliberate difference from the
            site, see the comment at the check) and its held count is known to cover it --
            its id rides the submit.
        Anything else charges credits, and the confirmed call is REFUSED unless the caller
        sends `accept_credit_cost` as the AMOUNT it showed, equal to this run's price (409
        when it is not). A bare `true` is accepted only for a run whose price could not be
        quoted; whenever there is a number to name, the number is required (spend review
        2026-09-28, finding 6). A card check that FAILS treats the run as paid (owner,
        2026-09-26).

        DOUBLE STARTS (spend review 2026-09-28, finding 1). A Basic run has no id until PixAI
        creates it, so one account-wide lock serialises confirms (a second concurrent one gets
        409), and the on-disk TrainGuard is checked and ARMED before the mutation: the same
        run confirmed again within a minute is refused as a double click, and an unclear
        failure (a timeout, a dropped connection, a 5xx -- PixAI may have created and charged
        it) keeps the guard for 15 minutes and says the run may have started. Only a definite
        refusal disarms it.

        ORDER on the confirm: CSRF -> READ_ONLY (before ANY read, the reuse read included) ->
        validation -> quota / card -> the lock -> the guard -> the pause switch -> the
        amount -> arm -> one createTrainingTask -> resolve. Single attempt."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        media_ids = body.get("media_ids") if isinstance(body.get("media_ids"), list) else []
        media_ids = [str(m) for m in media_ids if str(m).strip()]
        base_model_id = str(body.get("base_model_id") or "").strip()
        title = str(body.get("title") or "")
        trigger = str(body.get("trigger_words") or "")
        category = str(body.get("category") or "")
        dataset_task_id = str(body.get("dataset_task_id") or "").strip()
        confirming = bool(body.get("confirm"))
        if confirming:
            # READ_ONLY refuses the spend BEFORE the confirm's own reads -- the reuse check, the
            # free-card check and the pause switch -- so a read-only install makes no call on
            # the account for a submit it is going to refuse. submit_training checks it too.
            try:
                core._check_read_only("submit a LoRA training task")
            except Exception as e:                    # noqa: BLE001
                return jsonify({"error": str(e)}), 502
        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s" % e}), 502

        cfg = _training.training_config()
        reuse = bool(dataset_task_id) and dataset_task_id.isdigit() and \
            _reuse_ok(core, session, dataset_task_id, media_ids)
        try:
            tw = _training.validate_training(base_model_id, media_ids, title, trigger, category,
                                        training_task_id=dataset_task_id if reuse else "",
                                        config=cfg)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        unchecked, image_note = [], ""
        if not reuse:
            rejected, unchecked = _training.check_training_images(
                media_ids, media_dims(db_path, media_ids), cfg["image_constraints"])
            if rejected:
                return jsonify({"error": _training.describe_rejected_training_images(rejected),
                                "rejected_images": rejected}), 400
            image_note = ("" if not unchecked else
                          "%d image%s could not be checked against PixAI's size rule (this "
                          "library doesn't know %s size)." % (
                              len(unchecked), "" if len(unchecked) == 1 else "s",
                              "its" if len(unchecked) == 1 else "their"))

        free_left = _training.training_free_quota(session)
        free_by_quota = free_left > 0
        # credits, or None -- off `cfg`, the very config the validation above read, so one
        # request can never validate against the live config and price off the snapshot
        list_price = _training.training_price_for_version(base_model_id, cfg)
        price = _training.training_price_tier(base_model_id, "reuse", cfg) if reuse else list_price
        # The training free card (owner ruling 4): checked only when the quota does not
        # already make the run free -- "before a paid run", as SCOPE_2026-09-26 E7 words it.
        # A DELIBERATE DIFFERENCE FROM THE SITE: PixAI's basic trainer runs the card check
        # whatever the quota and attaches a matching card even when the quota covers the run
        # (so there the card is spent and the quota kept); here a member holding both spends a
        # quota unit and keeps the card. Recorded in DECISIONS with the other differences.
        # Read-only; the card is spent only by the submit that carries its id. A FAILED check
        # never refuses (owner, 2026-09-26): the run is treated as paid, so the paid confirm's
        # acknowledgement -- which names the amount -- is what lets it through.
        card, card_checked = None, True
        if not free_by_quota:
            try:
                best = _training.match_training_kaisuuken(session, base_model_id,
                                                     raise_on_error=True)
            except Exception:                         # noqa: BLE001
                best, card_checked = None, False
            # A card whose held count is UNKNOWN is not taken as covering, although
            # card_covers() assumes a 1-ticket job is covered: PixAI's own training check
            # keeps only matches with consumeAmount <= total, so it would not attach it
            # either -- and here it would skip the paid acknowledgement on a 25k-100k run.
            if best and best.get("id") and _cards.card_covers(best) \
                    and not best.get("balance_unknown"):
                card = best
        free_by_card = card is not None
        is_free = free_by_quota or free_by_card
        reason = "reusing a dataset" if reuse else ""
        if free_by_quota:
            cost_note = "Free — uses 1 of your %d free trainings." % free_left
        elif free_by_card:
            cost_note = ("Free — your training free card%s covers this base, and it is "
                         "used up by this run." % (" (%s)" % card["name"]
                                                   if card.get("name") else ""))
        elif price is not None:
            cost_note = ("No free trainings or training free card for this base — it costs "
                         "%s credits to train%s." % ("{:,}".format(price),
                                                     " (the rate for reusing a dataset)"
                                                     if reuse else ""))
        else:
            cost_note = ("No free trainings or training free card for this base, and PixAI's "
                         "price list has no price for it — the amount could not be quoted.")
        if is_free and price is not None:
            cost_note += " (Normally %s credits.)" % "{:,}".format(price)
        if not free_by_quota and not card_checked:
            cost_note += " (Your free cards couldn't be checked just now.)"
        if not confirming:
            return jsonify({
                "preview": True, "image_count": len(media_ids),
                "title": title.strip(), "trigger_words": tw, "category": category,
                "free_trainings_left": free_left, "is_free": is_free,
                "free_by": "quota" if free_by_quota else ("card" if free_by_card else None),
                "card": ({"name": card.get("name"), "expires": card.get("expiresAt")}
                         if card else None),
                "price": price, "list_price": list_price, "reuse": reuse,
                "price_reason": reason, "cost_note": cost_note,
                "eta": _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
                "unchecked_images": unchecked, "image_note": image_note,
            })
        if not _basic_start_lock.acquire(blocking=False):
            return jsonify({"error": "Another training start is already on its way. Nothing "
                                     "was sent again."}), 409
        try:
            key = TrainGuard.basic_key(base_model_id, media_ids,
                                       dataset_task_id if reuse else "", title)
            blocked = train_guard.basic_blocked(key)
            if blocked:
                return jsonify({"error": blocked}), 409
            pause = _training.training_pause()
            if pause is not None:
                return jsonify({"error": "PixAI has paused new LoRA training runs%s, so nothing "
                                         "was submitted. Runs already training carry on." %
                                         (" — it expects to be back around %s"
                                          % pause["resumes_at"]
                                          if pause.get("resumes_at") else "")}), 409
            accepted = body.get("accept_credit_cost")
            if not is_free:
                if price is None:
                    if not bool(accepted):
                        return jsonify({"error": "This training charges credits (amount "
                                                 "unknown). Re-send with accept_credit_cost "
                                                 "to proceed."}), 402
                elif accepted is None or accepted is False:
                    return jsonify({"error": "This training charges credits (%s). Re-send "
                                             "with accept_credit_cost to proceed."
                                             % "{:,}".format(price)}), 402
                elif not _exact_amount(accepted, price):
                    # The acknowledgement names an amount (the panels send the price they
                    # showed): it must still be THIS run's price. A base changed after the
                    # quote, a set no longer a reuse, or a price list that moved refuses here
                    # instead of charging a number nobody accepted; a bare `true` is refused
                    # because there IS a number to name.
                    return jsonify({"error": "The price changed since you accepted it — you "
                                             "accepted %s, and this training costs %s credits. "
                                             "Nothing was spent; check the cost and confirm "
                                             "again." % (
                                                 ("{:,} credits".format(accepted)
                                                  if isinstance(accepted, (int, float))
                                                  and not isinstance(accepted, bool)
                                                  else "an unnamed amount"),
                                                 "{:,}".format(price))}), 409
            train_guard.basic_arm(key)
            try:
                task = _training.submit_training(
                    session, base_model_id, [] if reuse else media_ids, title, trigger,
                    category, training_task_id=dataset_task_id if reuse else "",
                    kaisuuken_id=(card["id"] if free_by_card else ""), config=cfg)
            except Exception as e:
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.basic_resolve(key, "refused")
                    return jsonify({"error": str(e)}), 502
                train_guard.basic_resolve(key, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so this run may have "
                                         "started. Check Runs before starting it again.",
                                "maybe_started": True}), 502
            train_guard.basic_resolve(key, "started")
        finally:
            _basic_start_lock.release()
        _runs_dirty()
        # (The Academy counts runs PixAI reports finished -- api_train_runs -- not submits.)
        return jsonify({"submitted": True, "task": task, "was_free": is_free,
                        "used_card": free_by_card, "reuse": reuse,
                        "free_trainings_left": (max(0, free_left - 1) if free_by_quota
                                                else free_left)})

    # ---- Training, Session J (2026-09-28): the advanced flow, runs, publish -------------------
    # The design, its adversarial review and the guard order per route are in
    # ../moonglade-internal/design/notes/training/BUILD-w3-train.md. Every route here is LOGIN
    # tier like the rest of /api/train, every POST checks the CSRF token first, and every
    # confirm checks READ_ONLY before it reads anything else. OPENING a screen only reads
    # (DECISIONS 2026-09-28, "Nothing writes on open").
    #
    # LOCKS. One lock per training task (and per model, for make-public). The paid and
    # irreversible routes (describe, start, retry, publish, make public) take it WITHOUT
    # waiting and refuse with 409 when another request holds it: the second of two clicks, two
    # tabs or a phone and a desktop never sends a second paid POST. The free writes (the set,
    # a description) wait for it (up to 15 s), so quick edits queue instead of being dropped.
    _train_locks = {}
    _train_locks_mu = threading.Lock()

    def _train_lock(key):
        with _train_locks_mu:
            lk = _train_locks.get(key)
            if lk is None:
                lk = _train_locks[key] = threading.Lock()
            return lk

    _BUSY = ("Another request is already working on this run. Nothing was sent again -- give "
             "it a moment, then look again.")
    # An advanced describe/start confirm refused by TrainGuard.paid_blocked (finding F1).
    _PAID_MAYBE_REFUSAL = ("Your last confirm of %s may have gone through: PixAI didn't "
                           "answer clearly. Check Runs before trying again (this guard clears "
                           "by itself after 15 minutes). Nothing was sent.")
    train_guard = TrainGuard(lambda: _paths.records_path(out_dir, "train_guard.json"))
    _runs_cache = {"full": None, "light": None}

    def _runs_dirty():
        _runs_cache["full"] = _runs_cache["light"] = None

    def _train_csrf_body():
        body = request.get_json(silent=True) or {}
        return body, _check_csrf(body)

    def _train_refusal(e, status=502):
        from moonglade import backup as core
        if isinstance(e, core.PixAIRestError):
            payload = {"error": _training.training_error_words(e), "code": e.code}
            ids = e.data.get("mediaIds")
            if isinstance(ids, list):
                payload["rejected_ids"] = [str(x) for x in ids]
            return jsonify(payload), (e.status if e.status and 400 <= e.status < 500 else 502)
        return jsonify({"error": _redact_host_paths(str(e))[:300]}), status

    def _read_only_refusal(core, what):
        try:
            core._check_read_only(what)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"error": str(e)}), 502
        return None

    def _pause_refusal(core):
        pause = _training.training_pause()
        if pause is None:
            return None
        return jsonify({"error": "PixAI has paused LoRA training%s, so nothing was sent. Runs "
                                 "already training carry on." %
                                 (" -- it expects to be back around %s" % pause["resumes_at"]
                                  if pause.get("resumes_at") else ""),
                        "paused": True}), 409

    def _exact_amount(accepted, price):
        """The acknowledgement a paid confirm must carry: the NUMBER the user was shown, equal to
        the fresh quote. A bool is never an amount (True == 1 in Python), and a bare `true` is
        refused whenever there is a price to name (spend review, finding 6). A fractional
        amount is never the quote: int() would truncate 1200.5 onto a quote of 1200, so the
        number must be integer-valued AND equal (waves 2+3 review, finding F6)."""
        if isinstance(accepted, bool) or not isinstance(accepted, (int, float)):
            return False
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return False
        try:
            a, p = float(accepted), float(price)
        except (OverflowError, ValueError):
            return False
        return a.is_integer() and a == p

    def _amount_refusal(accepted, price, what):
        if accepted is None or accepted is False:
            return jsonify({"error": "%s costs %s credits. Nothing was sent: confirm the amount "
                                     "to go ahead." % (what, "{:,}".format(price))}), 402
        return jsonify({"error": "The price changed since you saw it -- %s now costs %s "
                                 "credits. Nothing was sent; check it and confirm again."
                                 % (what.lower(), "{:,}".format(price)),
                        "price": price}), 409

    def _base_names(cfg):
        return {m["version_id"]: m["title"] for m in cfg["models"]}

    def _thumb_for(mid):
        return "/api/train/thumb/%s" % mid if mid else ""

    @app.route("/api/train/datasets")
    @tier(LOGIN)
    def api_train_datasets():
        """Earlier training sets to import ("Import from previous datasets", Session J 2a): the
        account's own finished Basic runs that made a LoRA -- the list PixAI's own import
        dialog shows (advanced runs are left out, as there). Each: {task_id, model_id, title,
        trigger_words, category, base_version_id, media_ids, count, cover}. Read-only."""
        try:
            core, session = _gen_session()
            loras = _training.list_my_trained_loras(session, pages=3)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"datasets": [], "error": _redact_host_paths(str(e))[:200]}), 200
        out = []
        for m in loras:
            t = m.get("task") or {}
            p = t.get("parameters") or {}
            ids = [str(x) for x in (p.get("mediaIds") or []) if str(x).strip()]
            if not t.get("id") or t.get("trainingMode") == "advanced" or not ids \
                    or str(t.get("status") or "") != "completed":
                continue
            out.append({"task_id": str(t["id"]), "model_id": m["model_id"],
                        "title": str(p.get("title") or m["title"]),
                        "trigger_words": str(p.get("triggerWords") or ""),
                        "category": str(p.get("category") or ""),
                        "base_version_id": str(p.get("baseModelId") or ""),
                        "media_ids": ids, "count": len(ids),
                        "cover": _thumb_for(ids[0])})
        return jsonify({"datasets": out})

    _thumb_url_cache = {}

    @app.route("/api/train/thumb/<media_id>")
    @tier(LOGIN)
    def api_train_thumb(media_id):
        """A training-set image's picture, for any PixAI media id: this library's own thumbnail
        when it has one, otherwise PixAI's (an upload, or an image from an earlier set), read
        through the host-guarded CDN proxy. Read-only."""
        import urllib.parse as _up
        mid = str(media_id or "").strip()
        if not mid.isdigit():
            return ("bad id", 400)
        if (thumb_dir / ("%s.jpg" % mid)).is_file():
            return redirect("/thumbs/%s.jpg" % mid)
        url = _thumb_url_cache.get(mid)
        if url is None:
            try:
                core, session = _gen_session()
                url = core.media_thumbnail_url(session, mid) or ""
            except Exception:                           # noqa: BLE001
                url = ""
            if len(_thumb_url_cache) > 2000:
                _thumb_url_cache.clear()
            _thumb_url_cache[mid] = url
        if not url or _up.urlparse(url).netloc != "images-ng.pixai.art":
            return ("no picture", 404)
        return redirect("/api/pixai-cdn/thumb?u=" + _up.quote(url, safe=""))

    def _run_row_advanced(t, names, done=False):
        base = str(t.get("baseModelId") or "")
        row = {"id": str(t.get("id") or ""), "mode": "advanced",
               "title": str(t.get("title") or "") or "Untitled LoRA",
               "base_version_id": base, "base_name": names.get(base, ""),
               "image_count": int(t.get("mediaCount") or 0),
               "cover": "", "progress": None, "eta_left_ms": None, "reason": "",
               "model_id": "", "version_id": "", "visibility": "", "rebate": None,
               "trigger_words": ""}
        if done:
            row.update(status="done", model_id=str(t.get("modelId") or ""),
                       at=str(t.get("completedAt") or ""))
            row["published"] = bool(row["model_id"])
        else:
            st = str(t.get("status") or "")
            row.update(status=st, at=str(t.get("updatedAt") or ""), published=False)
            if st == "draft":
                row["step"] = "images" if row["image_count"] < 10 else "descriptions"
            elif st == "captioning":
                row["step"] = "describing"
            elif st == "captionReady":
                row["step"] = "descriptions"
        return row

    def _apply_detail(row, task):
        """Progress, the time left and PixAI's reason off a GraphQL TrainingTask."""
        extra = task.get("extra") or {}
        p = extra.get("progress")
        if isinstance(p, (int, float)) and row["status"] == "running":
            row["progress"] = max(0.0, min(100.0, float(p)))
            est = extra.get("estimatedTotalTime")
            if isinstance(est, (int, float)) and est > 0:
                row["eta_left_ms"] = int(est * (100.0 - row["progress"]) / 100.0)
        msg = ((task.get("outputs") or {}).get("message") or "")
        if row["status"] == "failed" and msg:
            row["reason"] = str(msg)[:300]
        ids = (task.get("parameters") or {}).get("mediaIds") or []
        if ids and not row.get("cover"):
            row["cover"] = _thumb_for(str(ids[0]))
        if (task.get("parameters") or {}).get("triggerWords"):
            row["trigger_words"] = str(task["parameters"]["triggerWords"])

    @app.route("/api/train/runs")
    @tier(LOGIN)
    def api_train_runs():
        """Runs (Session J 5c): advanced drafts, describe rounds, queued, training, failed and
        finished runs (PixAI's REST in-progress / completed lists) and Basic runs (the
        account's own LoRA list, where PixAI keeps them), one list, newest first, each with a
        status, PixAI's percentage while it trains, and the one action it offers. `running`
        is what the pinned strip shows. `?running=1` is the strip's light read (no finished
        runs). Read-only; answered from a 10-second cache so several open surfaces polling at
        once cost PixAI one read."""
        light = (request.args.get("running") or "") == "1"
        key = "light" if light else "full"
        hit = _runs_cache.get(key)
        if hit is not None and time.time() - hit[0] < 10.0:
            return jsonify(hit[1])
        errors = []
        try:
            core, session = _gen_session()
        except Exception as e:                          # noqa: BLE001
            return jsonify({"runs": [], "running": [], "error": str(e)[:200]}), 200
        cfg = _training.training_config()
        names = _base_names(cfg)
        rows, details = [], []
        try:
            for t in _training.list_training_in_progress(session, 100):
                rows.append(_run_row_advanced(t, names))
        except Exception as e:                          # noqa: BLE001
            errors.append("advanced runs: " + _redact_host_paths(str(e))[:120])
        loras = []
        try:
            loras = _training.list_my_trained_loras(session, pages=1 if light else 2)
        except Exception as e:                          # noqa: BLE001
            errors.append("your LoRAs: " + _redact_host_paths(str(e))[:120])
        by_model = {m["model_id"]: m for m in loras}
        # The Academy (loras_trained) counts runs PIXAI reports finished, by id: basic runs off
        # the account's LoRA list (every read), advanced ones off the finished list (the full
        # read). A failed run never lands here, so neither it nor its retry counts twice.
        finished = [str((m.get("task") or {}).get("id")) for m in loras
                    if (m.get("task") or {}).get("id")
                    and (m.get("task") or {}).get("trainingMode") != "advanced"
                    and str((m.get("task") or {}).get("status") or "") == "completed"]
        if not light:
            try:
                for t in _training.list_training_completed(session, 100):
                    if t.get("id"):
                        finished.append(str(t["id"]))
                    r = _run_row_advanced(t, names, done=True)
                    m = by_model.get(r["model_id"])
                    if m:
                        r["visibility"] = "private" if m["is_private"] else "public"
                        r["version_id"] = m["version_id"]
                        if m.get("task"):
                            _apply_detail(r, m["task"])
                    rows.append(r)
            except Exception as e:                      # noqa: BLE001
                errors.append("finished runs: " + _redact_host_paths(str(e))[:120])
        smap = {"completed": "done", "waiting": "waiting", "running": "running",
                "failed": "failed", "cancelled": "failed", "canceled": "failed"}
        for m in loras:
            t = m.get("task") or {}
            if not t.get("id") or t.get("trainingMode") == "advanced":
                continue                                 # advanced runs come from REST above
            st = smap.get(str(t.get("status") or ""), "")
            if not st or (light and st not in ("waiting", "running")):
                continue
            p = t.get("parameters") or {}
            r = {"id": str(t["id"]), "mode": "basic",
                 "title": str(p.get("title") or m["title"] or "Untitled LoRA"),
                 "base_version_id": str(p.get("baseModelId") or ""),
                 "base_name": names.get(str(p.get("baseModelId") or ""), ""),
                 "image_count": len(p.get("mediaIds") or []), "status": st,
                 "at": str(t.get("endAt") or t.get("updatedAt") or m["created_at"] or ""),
                 "cover": "", "progress": None, "eta_left_ms": None, "reason": "",
                 "model_id": m["model_id"], "version_id": m["version_id"],
                 "published": True, "rebate": None, "trigger_words": "",
                 "visibility": "private" if m["is_private"] else "public"}
            _apply_detail(r, t)
            rows.append(r)
        # PixAI's percentage for advanced runs that are training (the REST list has none) and
        # its reason for failed ones: a few GraphQL reads, newest first.
        for r in rows:
            if r["mode"] == "advanced" and r["status"] in ("running", "failed") \
                    and len(details) < (3 if light else 6):
                details.append(r)
        for r in details:
            try:
                _apply_detail(r, _training.training_task(session, r["id"]))
            except Exception:                           # noqa: BLE001
                pass
        guarded = train_guard.retried()
        for r in rows:
            g = guarded.get(r["id"])
            if g:
                r["retry"] = g
        # newest first, then (stable) the live ones on top: training, queued, describing
        order = {"running": 0, "waiting": 1, "captioning": 2}
        rows.sort(key=lambda r: r.get("at") or "", reverse=True)
        rows.sort(key=lambda r: order.get(r["status"], 3))
        running = [r for r in rows if r["status"] in ("running", "waiting")]
        payload = {"runs": rows if not light else running, "running": running,
                   "errors": errors}
        try:
            _telemetry.telem_set_add_many("trained_runs", finished, out_dir=out_dir)
        except Exception:                               # noqa: BLE001
            pass
        _runs_cache[key] = (time.time(), payload)
        return jsonify(payload)

    @app.route("/api/train/advanced/<task_id>")
    @tier(LOGIN)
    def api_train_advanced_get(task_id):
        """One advanced draft as its wizard needs it: the fixed set-up (name, trigger, category,
        base), the image set, each image's description (PixAI's machine text, and the owner's
        where he rewrote it), PixAI's describe quote while describing is possible, and its
        start quote once every image is described. READ-ONLY -- opening or continuing a draft
        writes nothing."""
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        try:
            core, session = _gen_session()
            t = _training.training_task(session, tid)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        if t.get("trainingMode") != "advanced":
            return jsonify({"error": "that run isn't an advanced one"}), 400
        cfg = _training.training_config()
        p = t.get("parameters") or {}
        ids = [str(x) for x in (p.get("mediaIds") or [])]
        status = str(t.get("status") or "")
        out = {"task": {"id": tid, "status": status, "title": str(p.get("title") or ""),
                        "trigger_words": str(p.get("triggerWords") or ""),
                        "category": str(p.get("category") or ""),
                        "base_version_id": str(p.get("baseModelId") or ""),
                        "base_name": _base_names(cfg).get(str(p.get("baseModelId") or ""), ""),
                        "media_ids": ids},
               "captions": {}, "caption_quote": None, "quote": None,
               "eta": _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
               "caption_max": _training.TRAIN_CAPTION_MAX, "errors": []}
        if status != "draft":
            try:
                items = _training.training_captions(session, tid)
            except Exception as e:                      # noqa: BLE001
                items = []
                out["errors"].append("descriptions: " + _redact_host_paths(str(e))[:120])
            from concurrent.futures import ThreadPoolExecutor

            def _texts(it):
                text = _training.fetch_caption_text(it["caption_url"])
                machine = text if it["source"] != "user" else \
                    _training.fetch_caption_text(it["machine_url"]) if it["machine_url"] else None
                return it["media_id"], {"source": it["source"], "text": text,
                                        "machine_text": machine}
            with ThreadPoolExecutor(max_workers=8) as ex:
                for mid, c in ex.map(_texts, items):
                    out["captions"][mid] = c
        if status in ("draft", "captionReady") and ids:
            try:
                out["caption_quote"] = _training.training_caption_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                out["errors"].append("describe price: " + _redact_host_paths(str(e))[:120])
        if status == "captionReady":
            try:
                out["quote"] = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                out["errors"].append("price: " + _redact_host_paths(str(e))[:120])
        return jsonify(out)

    @app.route("/api/train/advanced/draft", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_draft():
        """Create an advanced draft -- the user's deliberate "Next · creates a draft" and
        nothing else (Session J 3c). Free, but a write: CSRF, then READ_ONLY before any read,
        then PixAI's pause switch, then one createTrainingTask."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        refused = _read_only_refusal(core, "create a LoRA training draft")
        if refused:
            return refused
        refused = _pause_refusal(core)
        if refused:
            return refused
        try:
            core_, session = _gen_session()
            d = _training.create_advanced_training_draft(
                session, str(body.get("base_model_id") or ""), str(body.get("title") or ""),
                str(body.get("trigger_words") or ""), str(body.get("category") or ""))
        except core.PixAIError as e:
            return (_train_refusal(e) if isinstance(e, core.PixAIRestError)
                    else (jsonify({"error": str(e)}), 400))
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        _runs_dirty()
        return jsonify({"id": d["id"]})

    @app.route("/api/train/advanced/<task_id>/media", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_media(task_id):
        """Replace the draft's image set (PUT media; free). The per-side image rule runs over
        this library's sizes first and refuses a failing image by name, as Basic does."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        ids = body.get("media_ids") if isinstance(body.get("media_ids"), list) else None
        if not tid.isdigit() or ids is None:
            return jsonify({"error": "which run, and which images?"}), 400
        ids = [str(m) for m in ids if str(m).strip()]
        cfg = _training.training_config()
        rejected, _unchecked = _training.check_training_images(
            ids, media_dims(db_path, ids), cfg["image_constraints"])
        if rejected:
            return jsonify({"error": _training.describe_rejected_training_images(rejected),
                            "rejected_ids": [r["media_id"] for r in rejected]}), 400
        refused = _read_only_refusal(core, "change a LoRA training set")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(timeout=15):
            return jsonify({"error": _BUSY}), 409
        try:
            core_, session = _gen_session()
            saved = _training.replace_training_media(session, tid, ids)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"media_ids": saved})

    @app.route("/api/train/advanced/<task_id>/captions/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_caption_save(task_id, media_id):
        """Save the owner's own description for one image (PUT; free; 1 to 1,000 characters;
        only once PixAI has described it)."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid, mid = str(task_id or "").strip(), str(media_id or "").strip()
        text = str(body.get("text") or "").strip()
        if not tid.isdigit() or not mid.isdigit():
            return jsonify({"error": "which image?"}), 400
        if not text or len(text) > _training.TRAIN_CAPTION_MAX:
            return jsonify({"error": "A description is 1 to %s characters."
                                     % "{:,}".format(_training.TRAIN_CAPTION_MAX)}), 400
        refused = _read_only_refusal(core, "edit a LoRA training description")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(timeout=15):
            return jsonify({"error": _BUSY}), 409
        try:
            core_, session = _gen_session()
            saved = _training.save_training_caption(session, tid, mid, text)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        finally:
            lk.release()
        return jsonify({"text": saved})

    @app.route("/api/train/advanced/<task_id>/caption", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_caption(task_id):
        """PAID: PixAI describes the set's undescribed images (Session J 3c, corrected by the
        2026-09-28 capture: this is the only way in -- PixAI has no write-your-own path before
        it). Preview-first: without `confirm` it only quotes (GET caption-price: the count
        and the total, PixAI's own number, never the config's stale unit price). The confirm:
        CSRF -> READ_ONLY -> this run's lock (refuses when held) -> pause switch -> the run
        re-read (a draft or in review, at least 10 images) -> a FRESH quote -> nothing left
        to describe refuses -> `accept_credit_cost` must be the fresh total, as a number ->
        one POST caption."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "describe LoRA training images")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            st = str(t.get("status") or "")
            n = len((t.get("parameters") or {}).get("mediaIds") or [])
            if confirming and train_guard.paid_blocked("caption", tid, st):
                return jsonify({"error": _PAID_MAYBE_REFUSAL % "describing these images",
                                "maybe_started": True}), 409
            if t.get("trainingMode") != "advanced" or st not in ("draft", "captionReady"):
                return jsonify({"error": "PixAI is %s this run, so it can't be described "
                                         "now. Nothing was sent." %
                                         ("already describing" if st == "captioning"
                                          else "past that step on")}), 409
            if n < _training.TRAIN_MIN_IMAGES:
                return jsonify({"error": "Add at least %d more image%s first. Nothing was sent."
                                         % (_training.TRAIN_MIN_IMAGES - n,
                                            "" if _training.TRAIN_MIN_IMAGES - n == 1 else "s")}), 400
            try:
                q = _training.training_caption_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            per = (q["total_price"] // q["image_count"]) if q["image_count"] else None
            if not confirming:
                return jsonify({"preview": True, "image_count": q["image_count"],
                                "total_price": q["total_price"], "per_image": per})
            if q["image_count"] <= 0:
                return jsonify({"error": "Every image is described already. Nothing was "
                                         "sent."}), 409
            accepted = body.get("accept_credit_cost")
            if not _exact_amount(accepted, q["total_price"]):
                return _amount_refusal(accepted, q["total_price"], "Describing these images")
            train_guard.paid_arm("caption", tid, st)
            try:
                status = _training.start_training_captions(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.paid_resolve("caption", tid, "refused")
                    return _train_refusal(e)
                train_guard.paid_resolve("caption", tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so describing these "
                                         "images may have started. Check Runs before "
                                         "describing again.",
                                "maybe_started": True}), 502
            train_guard.paid_resolve("caption", tid, "done")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"started": True, "status": status or "captioning",
                        "charged": q["total_price"], "image_count": q["image_count"]})

    @app.route("/api/train/advanced/<task_id>/submit", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_submit(task_id):
        """PAID: start an advanced run (Session J 3c, Parameters -> Start). PixAI's own default
        options are sent verbatim (core.TRAIN_DEFAULT_OPTIONS) -- its page locks them, and its
        quote takes no length, so this route takes no parameters from the client (spend review,
        finding 3). No free card rides it, as on PixAI's page. Preview quotes GET price; the
        confirm: CSRF -> READ_ONLY -> the run's lock (refuses when held) -> pause switch ->
        the run re-read (in review, every image described) -> a FRESH quote ->
        `accept_credit_cost` equal to it (a quote of 0 needs none) -> one POST submit. The
        member quota is read before and after, so the answer can say if PixAI used one of the
        member's free trainings (whether it does for an advanced run is not known)."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "start a LoRA training run")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
                if confirming and train_guard.paid_blocked("submit", tid,
                                                           str(t.get("status") or "")):
                    return jsonify({"error": _PAID_MAYBE_REFUSAL % "this run",
                                    "maybe_started": True}), 409
                if t.get("trainingMode") != "advanced" or t.get("status") != "captionReady":
                    return jsonify({"error": "This run isn't waiting to start (PixAI says: %s). "
                                             "Nothing was sent." % (t.get("status") or "?")}), 409
                ids = [str(x) for x in ((t.get("parameters") or {}).get("mediaIds") or [])]
                described = {c["media_id"] for c in _training.training_captions(session, tid)}
                left = [m for m in ids if m not in described]
                if left:
                    return jsonify({"error": "Describe the %d remaining image%s first. Nothing "
                                             "was sent." % (len(left),
                                                            "" if len(left) == 1 else "s"),
                                    "undescribed": left}), 409
                price = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            eta = _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"])
            if not confirming:
                return jsonify({"preview": True, "price": price, "eta": eta,
                                "image_count": len(ids), "is_free": price == 0})
            accepted = body.get("accept_credit_cost")
            if price > 0 and not _exact_amount(accepted, price):
                return _amount_refusal(accepted, price, "This training")
            before = _training.training_free_quota(session)
            train_guard.paid_arm("submit", tid, t.get("status"))
            try:
                status = _training.submit_advanced_training(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.paid_resolve("submit", tid, "refused")
                    return _train_refusal(e)
                train_guard.paid_resolve("submit", tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so this run may have "
                                         "started. Check Runs before starting it again.",
                                "maybe_started": True}), 502
            train_guard.paid_resolve("submit", tid, "done")
            after = _training.training_free_quota(session)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"submitted": True, "status": status or "waiting", "price": price,
                        "used_free_training": bool(before > after)})

    @app.route("/api/train/runs/<task_id>/retry", methods=["POST"])
    @tier(LOGIN)
    def api_train_retry(task_id):
        """PAID, A NEW RUN: retry a failed advanced run (same set, same descriptions; charged
        again at PixAI's current price, its GET price quote). PixAI leaves the failed run as
        it is and would take a second retry, so the retry guard (on disk) is checked first and
        armed right before the POST; only a definite refusal disarms it. No free card rides
        it, as on PixAI's page."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "retry a LoRA training run")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            g = train_guard.retry_state(tid)
            if g:
                return jsonify({"error": ("This run was retried already -- the new run is in "
                                          "Runs. Nothing was sent." if g["state"] == "done" else
                                          "A retry of this run may have started: PixAI didn't "
                                          "answer clearly. Check Runs. Nothing was sent."),
                                "retry": g}), 409
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
                if t.get("trainingMode") != "advanced" or t.get("status") != "failed":
                    return jsonify({"error": "Only a failed advanced run can be retried. "
                                             "Nothing was sent."}), 409
                price = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            if not confirming:
                return jsonify({"preview": True, "price": price, "is_free": price == 0,
                                "eta": _training.training_eta(
                                    _training.TRAIN_DEFAULT_OPTIONS["trainingSteps"])})
            accepted = body.get("accept_credit_cost")
            if price > 0 and not _exact_amount(accepted, price):
                return _amount_refusal(accepted, price, "Retrying this run")
            train_guard.retry_arm(tid)
            try:
                res = _training.retry_training(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.retry_resolve(tid, "refused")
                    return _train_refusal(e)
                train_guard.retry_resolve(tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so the retry may have "
                                         "started. Check Runs before trying again.",
                                "maybe_started": True}), 502
            train_guard.retry_resolve(tid, "done", res.get("id") or "")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"retried": True, "id": res.get("id") or "", "price": price})

    _PUBLISH_TICKS = {"private": ["no_delete"], "public": ["no_delete", "no_private"]}

    @app.route("/api/train/runs/<task_id>/publish", methods=["POST"])
    @tier(LOGIN)
    def api_train_publish(task_id):
        """IRREVERSIBLE: publish a finished advanced run as a LoRA (Session J 4a). The request
        must carry every consequence the sheet ticked, exactly: private ["no_delete"], public
        ["no_delete", "no_private"]; rebates only when public. CSRF -> READ_ONLY -> the run's
        lock -> the finished list re-read (finished, not yet published) -> one POST publish."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        vis = str(body.get("visibility") or "")
        rebate = "join" if body.get("rebate") in (True, "join") else "decline"
        acks = body.get("acknowledged") if isinstance(body.get("acknowledged"), list) else []
        if not tid.isdigit() or vis not in _PUBLISH_TICKS:
            return jsonify({"error": "publish it private or public"}), 400
        if rebate == "join" and vis != "public":
            return jsonify({"error": "Only a public LoRA can join rebates. Nothing was "
                                     "sent."}), 400
        if sorted(str(a) for a in acks) != sorted(_PUBLISH_TICKS[vis]):
            return jsonify({"error": "Tick every line under \"This can't be undone\" to "
                                     "publish. Nothing was sent."}), 400
        refused = _read_only_refusal(core, "publish a trained LoRA")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            try:
                core_, session = _gen_session()
                done = {str(t.get("id")): t for t in _training.list_training_completed(session, 100)}
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            t = done.get(tid)
            if not t:
                return jsonify({"error": "That run hasn't finished training. Nothing was "
                                         "sent."}), 409
            if t.get("modelId"):
                return jsonify({"error": "That run is published already. Nothing was "
                                         "sent."}), 409
            try:
                res = _training.publish_training(session, tid, vis, rebate)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"published": True, "visibility": vis, "rebate": rebate == "join",
                        **res})

    @app.route("/api/train/models/<model_id>/rebates")
    @tier(LOGIN)
    def api_train_model_rebates(model_id):
        """Whether one of your LoRAs can join rebates (PixAI's check). Read-only."""
        mid = str(model_id or "").strip()
        if not mid.isdigit():
            return jsonify({"offered": False, "joined": False, "can_join": False}), 400
        try:
            core, session = _gen_session()
            return jsonify(core.lora_rebate_eligibility(session, mid))
        except Exception:                               # noqa: BLE001
            return jsonify({"offered": False, "joined": False, "can_join": False})

    @app.route("/api/train/models/<model_id>/make-public", methods=["POST"])
    @tier(LOGIN)
    def api_train_make_public(model_id):
        """IRREVERSIBLE: a private LoRA of yours goes public (Session J 4a, "Private -> public
        later": the same sheet, Public fixed, one tick), optionally joining rebates. Exactly
        PixAI's own two calls. CSRF -> the one tick -> READ_ONLY -> the model's lock -> the
        model re-read (yours, private) -> upsertGenerationModel {isPrivate: false} -> only
        when asked and PixAI offers it, the rebate PATCH."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        mid = str(model_id or "").strip()
        acks = body.get("acknowledged") if isinstance(body.get("acknowledged"), list) else []
        join = body.get("rebate") in (True, "join")
        if not mid.isdigit():
            return jsonify({"error": "which LoRA?"}), 400
        if [str(a) for a in acks] != ["no_private"]:
            return jsonify({"error": "Tick \"It can't go back to private\" to go on. Nothing "
                                     "was sent."}), 400
        refused = _read_only_refusal(core, "make a LoRA public")
        if refused:
            return refused
        lk = _train_lock("model:" + mid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            try:
                core_, session = _gen_session()
                m = _models.generation_model_brief(session, mid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            me = str(getattr(session, "user_id", "") or core.USER_ID or "")
            if me and m["author_id"] and m["author_id"] != me:
                return jsonify({"error": "That LoRA isn't yours. Nothing was sent."}), 403
            if not m["is_private"]:
                return jsonify({"error": "That LoRA is public already. Nothing was sent."}), 409
            try:
                core.make_model_public(session, mid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            joined, note = False, ""
            if join:
                try:
                    el = core.lora_rebate_eligibility(session, mid)
                    if el["can_join"]:
                        core.join_lora_rebates(session, mid)
                        joined = True
                    else:
                        note = "PixAI isn't offering rebates for it right now."
                except Exception:                       # noqa: BLE001
                    note = ("It is public, but joining rebates didn't go through; you can "
                            "try again from its run.")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"public": True, "rebate": joined, "note": note})

    _telem_day = {"day": None}   # once-per-day throttle for the passive marks

    @app.route("/api/achievements")
    @tier(LOGIN)
    def api_achievements():
        """Milestone progress + skin unlocks, computed from local catalog stats +
        the persisted telemetry counters. Read-only catalog data (no spend, no
        network) so — like the picker — it's NOT localhost-gated; the owner browsing
        over LAN still sees their trophies. ?mark=1 records the currently newly-earned
        achievements as 'seen' so the unlock toast fires exactly once.

        Side effects (cheap, fail-soft): marks today in the Vigil day ledger and sweeps
        the state-derived feat flags. (It no longer looks at the time of day: a page load
        is not evidence of anything -- see stamp_session_hour.) A feat the
        roster marks hidden goes out MASKED until it is earned -- collapsed with
        every other still-masked one into a single ??? placeholder, so devtools
        can't spoil them or even count how many remain; the whole feat tab stays
        cloaked until the first feat lands."""
        import datetime as _dt
        try:
            today = _dt.date.today().isoformat()
            if _telem_day["day"] != today:
                _telem_day["day"] = today
                _telemetry.telem_mark_day(out_dir=out_dir)
                _telemetry.sweep_telemetry(out_dir)
        except Exception:
            pass
        # ONE telemetry read for the whole request. This route wanted the store three
        # times -- the metric flatten, the first-sync gate, and compute's `sets` -- and
        # was reading and parsing the file for each. Same values, a third of the I/O.
        #
        # Loaded BEFORE the branding sweep, and handed to it, because the sweep's own
        # flag short-circuit wants exactly this store and used to parse it a second
        # time on every fetch. The sweep writes through to the file and mirrors the
        # FLAG it may set back into this dict, so the copy the rest of the request
        # reads from carries that write -- without that, a store loaded before the
        # sweep is one write stale for the remainder of the request. (A baseline the
        # sweep records is read only by the next scan, so it is not mirrored.)
        telem = _telemetry.load_telemetry(out_dir)
        # Unlike sweep_telemetry above, this runs EVERY call rather than once a day:
        # a file dropped into the tree since the last fetch is picked up on the next
        # reload, not up to a day later. See sweep_branding_drops()'s own docstring.
        try:
            _branding.sweep_branding_drops(out_dir, telem=telem)
        except Exception:
            pass
        metrics = _achievements.achievement_metrics(db_path)
        metrics.update(_telemetry.telemetry_metrics(out_dir, telem=telem))
        # Gate the unlock toasts until the first full sync completes (see first_sync_complete):
        # first-light is images>=1, so without this it pops seconds into a fresh first sync.
        fsd = _telemetry.first_sync_complete(out_dir, db_path, telem=telem)
        persist_error = None
        with _ach_lock:
            state = _achievements.load_ach_state(out_dir)
            result = _achievements.compute_achievements(metrics, state.get("seen"),
                                          sets=telem.get("sets", {}),
                                          earned_at=state.get("earned_at"))
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
                if not _achievements.save_ach_state(out_dir, state):
                    persist_error = "could not save achievement progress (disk write failed)"
            earned_at = state.get("earned_at") or {}
        feats_revealed = any(
            a["earned"] for a in result["achievements"] if a["tier"] == "feat")
        unleashed = any(a["id"] == "triggered" and a["earned"]
                        for a in result["achievements"])
        # Hidden feats never appear in the array until they are earned. They used to
        # collapse to ONE "???" placeholder entry (2026-08-13); Session G replaced that with
        # `feats.masked` below -- a riddle and a silhouette for one feat, and no entry at
        # all, so neither the array's length nor any entry in it says anything about how
        # many secrets remain.
        masked_metrics, n_masked, visible = set(), 0, []
        sealed_by_id = {r["id"]: r for r in _achievements._roster() if isinstance(r, dict)}
        earned_ids = {a["id"] for a in result["achievements"] if a["earned"]}
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
            if a["earned"]:                   # the roster flags go out only once earned
                a.update(_branding._earned_roster_flags(sealed_by_id.get(a["id"])))
            else:                             # "N to go": never a feat, never an unmeasured metric
                prog = _achievements.achievement_progress(a, metrics)
                if prog is not None:
                    a["progress"] = prog
            visible.append(a)
        result["feats"] = _branding._feats_payload(earned_ids, n_masked, feats_revealed, unleashed,
                                         app.secret_key)
        # The Folio's Marks row (relics by kind): earned, awarded marks only.
        try:
            result["relics"] = {"marks": _branding.earned_relic_marks(out_dir, earned_ids)}
        except Exception:
            result["relics"] = {"marks": []}
        result["achievements"] = visible
        # a masked feat's metric name/value must not leak through the metrics echo
        still_visible = {a["metric"] for a in result["achievements"] if a.get("metric")}
        for k in masked_metrics - still_visible:
            metrics.pop(k, None)
        # The Vigil chip (O5): the run of days with a generation, and the best run ever. From the
        # gen_days ledger; a fresh install with no days answers day 1, best 1.
        try:
            _gd = (telem.get("day_lists") or {}).get("gen_days")
            result["vigil"] = _telemetry.vigil_status(_gd if isinstance(_gd, list) else [])
        except Exception:
            result["vigil"] = {"day": 1, "best": 1}
        result["feats_revealed"] = feats_revealed
        result["unleash_available"] = unleashed
        result["skin"] = state.get("skin", "moonglade")
        result["earned_at"] = earned_at   # {id: iso-date}; only earned ids -> no hidden-feat leak
        result["metrics"] = metrics
        if persist_error:
            result["error"] = persist_error
        return jsonify(result)

    @app.route("/api/skin", methods=["POST"])
    @tier(LOGIN)
    def api_skin():
        """Set the active cosmetic skin. Only an *earned* skin may be applied (server checks
        against current unlocks), so a client can't force a locked palette. Persists to
        out_dir/_moonglade/records/achievements.json. Cosmetic + local-only, no spend."""
        body = request.get_json(silent=True) or {}
        skin = str(body.get("skin") or "").strip()
        if skin not in _achievements._skin_ids():
            return jsonify({"error": "unknown skin"}), 400
        # #38: this gate used to compute from achievement_metrics() ALONE -- no
        # telemetry merge, no earned_at -- so any telemetry-backed or pinned skin
        # unlock showed earned in the Folio yet 403'd here. It now runs the exact
        # recipe /api/achievements and _mark_earned() use (guarded by
        # dev/tests/test_achievements.py's gate-parity tests).
        _m = _achievements.achievement_metrics(db_path)
        _m.update(_telemetry.telemetry_metrics(out_dir))
        result = _achievements.compute_achievements(_m,
                                      sets=_telemetry.load_telemetry(out_dir).get("sets", {}),
                                      earned_at=_achievements.load_ach_state(out_dir).get("earned_at"))
        earned = {s["id"] for s in result["skins"] if s["earned"]}
        if skin not in earned:
            return jsonify({"error": "skin locked", "skin": _achievements.load_ach_state(out_dir)["skin"]}), 403
        with _ach_lock:
            state = _achievements.load_ach_state(out_dir)
            changed = state.get("skin") != skin
            state["skin"] = skin
            saved = _achievements.save_ach_state(out_dir, state)
        if not saved:
            # save_ach_state() is "best-effort; swallows write errors" by design (its own
            # docstring) -- but that return value used to be dropped on the floor here, so a
            # disk-write failure still answered 200 {"skin": skin} as if it had stuck. Report
            # what's ACTUALLY active (a fresh read, not the requested value) instead of lying.
            return jsonify({"error": "could not save skin (disk write failed)",
                            "skin": _achievements.load_ach_state(out_dir)["skin"]}), 200
        if changed:                       # Interior Decorator: an explicit re-dress
            _telemetry.telem_bump("skin_changed_runs", out_dir=out_dir)
        return jsonify({"skin": skin})

    @app.route("/api/ach-nonce")
    @tier(LOGIN)
    def api_ach_nonce():
        """A fresh beacon nonce for a page whose own has gone stale (idle past the 60s
        window, or spent). Same session budget as the events themselves -- see
        _ach_rate_ok(). The render seams (app_page, /loom) mint their first one inline;
        this is the top-up."""
        sid = _ach_sid()
        if not _ach_rate_ok(sid):
            return jsonify({"error": "slow down"}), 429
        return jsonify({"nonce": _ach_mint(sid)})

    @app.route("/api/ach-event", methods=["POST"])
    @tier(LOGIN)
    def api_ach_event():
        """Feat-event beacon from the front-end: the Starfall key-sequence moment and the
        in-app manual. Whitelisted event names only; each is a cosmetic local counter
        (no spend). Narrator pokes used to ride this beacon; they have their own route
        (/api/narrator/poke) since the ladder, which keeps its count and clocks per
        account on the server, and an event named "narrator" is refused here so no
        second road can move that count.

        LOGIN again since 2026-09-07, on the owner's ruling ("I feel like
        triggered should be obtainable easily on a phone just like desktop. For
        sure build the nonce."). The per-render nonce this route now requires is
        what makes LOGIN honest, and it is the work the 2026-08-26 comment here
        listed as "NOT DONE HERE".

        THE HISTORY, kept because the reasoning still stands. LOCALHOST from
        2026-08-26 to 2026-09-07: the beacon is the ONLY thing standing between a
        feat and being earned -- there is no server-side re-check that the
        gesture actually happened, so any signed-in session could POST
        a feat event straight from a console and arm the feat without ever
        entering the code. Narrowing to loopback meant a feat could only be armed
        at the server's own keyboard, the one place the gesture can be witnessed.
        The cost was that a phone or any other LAN device lost all three feats,
        and the owner judged that cost too high once the nonce was buildable.

        WHAT THE NONCE WITNESSES INSTEAD. Not where the request came from, but
        that it came from a page THIS SERVER RENDERED FOR THIS SESSION: the
        nonce is minted into the render (window.MG_BOOT.ach_nonce, or the Loom
        shell's own inline mint), is good for exactly one event inside 60
        seconds, and is refused when presented by another session. A console POST
        has none. A replay has a spent one. A nonce lifted from someone else's
        page is not this session's to spend. That is a softer witness than
        loopback -- someone determined can still read their own page's nonce out
        of MG_BOOT and curl it -- but it is the same class of witness CSRF gives
        us everywhere else, and it costs a phone nothing.

        Also here, so a real gesture stays one event: a 150ms debounce per
        (session, event), and 30 beacon calls per session per rolling minute,
        beyond which the answer is 429 and no counter moves. The debounce is a
        wall-clock gap, so its width IS its meaning: 150ms is under a hand and
        over a double-fired DOM event, which is the only thing it should fold
        together. It shipped at 400ms earlier the same day and swallowed every
        second tap of an ordinary phone tap-rate -- see _ach_debounced(). A
        debounced reply is accepted, hands back a nonce and counts nothing.

        The other half of one double-fired click is one nonce sent twice: the
        twin that loses is refused 403 as consumed. The clients do NOT refresh
        and retry that one -- see achNonce.js -- or the retry would count the
        same gesture twice from the other side.

        The clients still treat a refusal as a no-op by design: api.js never
        throws (a 403 comes back as an {error} body) and the key-sequence handler
        is explicitly fail-soft (the stars and toast still play). What is new
        is that every caller now goes through notify/achNonce.js, which adopts
        the `next_nonce` an accepted event returns and re-asks /api/ach-nonce
        once on a stale-page 403 before giving up quietly.

        THE EVENT NAMES ARE PUBLIC -- they sit in served JS and in this whitelist -- so they
        name the moment, never the gesture: the key sequence posts "starfall" (renamed
        2026-10-02 from a word that gave the egg away). There is no alias for the old name:
        a stale cached page's 400 is a silent no-op and the next press after a reload counts.
        The telemetry flag it sets keeps its key, which is the sealed roster's metric."""
        sid = _ach_sid()
        if not _ach_rate_ok(sid):
            return jsonify({"error": "slow down"}), 429
        body = request.get_json(silent=True) or {}
        ev = str(body.get("event") or "").strip()
        if ev not in ("starfall", "docs"):
            return jsonify({"error": "unknown event"}), 400
        # One refusal wording for missing, unknown, expired and foreign alike: which
        # check failed is exactly the thing a replay probe would want to learn, and
        # every one of them has the same fix for a real page.
        if not _ach_consume(str(body.get("nonce") or ""), sid):
            return jsonify({"error": "stale page — reload"}), 403
        # A consumed nonce always buys the next one, debounced or not -- otherwise the
        # second half of a double-fire leaves the page with no nonce at all.
        nxt = _ach_mint(sid)
        if _ach_debounced(sid, ev):
            return jsonify({"ok": True, "debounced": True, "next_nonce": nxt})
        if ev == "starfall":
            _telemetry.telem_flag("konami_triggered", out_dir=out_dir)
            return jsonify({"ok": True, "next_nonce": nxt})
        _telemetry.telem_bump("docs_opened", out_dir=out_dir)
        return jsonify({"ok": True, "next_nonce": nxt})

    @app.route("/api/narrator/poke", methods=["POST"])
    @tier(LOGIN)
    def api_narrator_poke():
        """One poke at the narrator. Body: {"csrf": "..."} and nothing else. Answer:
        {"ok": true, "line": "..."} -- and, on the one poke that ends the ladder, a `final`
        object carrying the two lines that poke is answered with.

        THE SERVER DECIDES, THE CLIENT PAINTS. The count, the clocks and the choice of line
        are this route's and moonglade.narrator.poke()'s (a pure core that takes the time as
        a parameter); the page is told a line and nothing else, so it can learn neither how
        far along it is, nor which stage, nor whether a poke counted. A poke that does not
        count answers exactly like one that does.

        WHICH ACCOUNT: the session's, never the body's. The state is per account and is
        kept where the account cannot write it (account_state_*, not the prefs store).

        WHAT IT WRITES: that account's own ladder state, and -- only on a poke that counted
        -- the install's `narrator_pokes` metric raised to that account's count (a maximum,
        not a sum, so two accounts never pool their pokes). Triggered is then earned the way
        every feat is: the metric meets the sealed roster's threshold, and the next
        achievements read stamps it. Nothing here spends, reaches PixAI or retries.

        LINES come only from the sealed pack (`poke_lines`); a pack with none for what is
        being said answers a bare ellipsis, never copy invented here. LOGIN tier, CSRF by
        the explicit token (_check_csrf), like the other per-account writes."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "authentication required"}), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import narrator as _nar
        pools = _nar.clean_pools(_achievements._poke_lines())
        now, today = _account_prefs._narrator_clock()
        try:
            with _account_prefs.account_state_locked(out_dir, user) as p:
                doc = _account_prefs.account_state_read(p)
                st, res = _nar.poke(doc.get("ladder"), now, today, pools)
                _account_prefs.account_state_write(p, dict(doc, ladder=st))
        except _account_prefs.AccountPrefsBusy as e:
            return jsonify({"error": str(e)}), 503
        except OSError:
            return jsonify({"error": "Could not save that."}), 500
        # The metric follows the count: only ever up, and re-asserted once the ladder is
        # done so a write that was lost once is repaired by the next poke.
        if res["counted"] or res["count"] >= _nar.FINAL:
            _telemetry.telem_max("narrator_pokes", res["count"], out_dir=out_dir)
        out = {"ok": True, "line": res["line"]}
        if res["final"]:
            final = {}
            out["line"] = _nar.NEUTRAL
            feat = next((a for a in _achievements._roster() if a.get("metric") == "narrator_pokes"), None)
            if feat and feat["id"] in _branding._earned_achievement_ids(out_dir, db_path, need=feat["id"]):
                final = {"id": feat["id"],
                         "clean": feat.get("roast") or feat.get("desc") or "",
                         "unleashed": feat.get("roast_nsfw") or ""}
                out["line"] = final["clean"] or _nar.NEUTRAL
                choice = _nar.clean_choice(_achievements._poke_lines().get("choice"))
                if choice:
                    final["choice"] = choice
            out["final"] = final
        return jsonify(out)

    @app.route("/api/mirror/status")
    @tier(LOGIN)
    def api_mirror_status():
        """Read-only status of 'Mirror to PixAI website': the toggle flag + the stored
        JWT's days-left, decoded OFFLINE (no network). NEVER returns the token (review
        F13). LOGIN tier.

        #71 adds what the ring is drawn from: `left_s` / `span_s` (core.mirror_token_span --
        the token's own life, never iat to exp) and `renewal` (core.mirror_renewal_status: ok,
        failed, paused, expired, off), so the tile warns only when a renewal actually failed
        or cannot run, not whenever the token sits in its normal renewal window."""
        from moonglade import backup as core
        state = _mirror.load_mirror_state()
        jwt = (state.get("jwt") or "")
        left_s, span_s = _mirror.mirror_token_span(state)
        return jsonify({"enabled": _mirror.mirror_enabled(), "connected": bool(jwt),
                        "days_left": _mirror.jwt_days_left(jwt) if jwt else None,
                        "left_s": int(left_s) if left_s is not None else None,
                        "span_s": int(span_s) if span_s is not None else None,
                        "renewal": _mirror.mirror_renewal_status()})

    @app.route("/api/mirror/enable", methods=["POST"])
    @tier(LOCALHOST)
    def api_mirror_enable():
        """Set the "Mirror to PixAI website" switch (settings.json's mirror_to_pixai).
        LOCALHOST-ONLY: it decides which credential rides the owner's every generation, so it
        is in the same trust class as /api/setup/save-key and /api/branding/shortcut -- a
        logged-in LAN session must not be able to flip the owner's every generation onto the
        browser JWT. settings.json is written whole under its own lock (moonglade.settings)."""
        from moonglade import backup as core
        want = bool((request.get_json(silent=True) or {}).get("enabled"))
        # [MAJOR] Only ARM (true-write) when a usable browser JWT actually exists: arming the
        # mirror with no live session lets every Bridge/enhance submit hit the mirror-ON gate,
        # fail make_mirror_session(), and refuse -- an armed toggle that can run nothing. The
        # DISARM (false-write) is always allowed, so the owner can always turn it back off.
        if want and not _mirror._jwt_usable(_mirror.load_mirror_state().get("jwt") or ""):
            return jsonify({"error": "Connect the mirror first — not armed",
                            "enabled": False}), 200
        try:
            _settings.set_values(**{_settings.MIRROR_TO_PIXAI: want})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
        return jsonify({"enabled": want})

    @app.route("/api/mirror/disconnect", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_disconnect():
        """The Mirror tile's Disconnect (app security review 2026-11-19, finding 7): forget the
        stored PixAI sign-in and stop renewing it (mirror.disconnect_mirror), and turn the
        switch off, since an armed Mirror with no sign-in refuses every create. LOGIN tier, a
        client on this machine or a private home network (mirror.home_network_address), the
        same reach as Connect from PixAI; the session's CSRF token. Body {csrf}. Answers ok, or
        a plain sentence; the sign-in is never read back."""
        if not _mirror.home_network_address(request.remote_addr):
            return jsonify({"ok": False, "error": _mirror.SITE_TOKEN_NOT_HOME}), 403
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        if not _mirror.disconnect_mirror():
            return jsonify({"error": "Moonglade couldn't delete the stored PixAI sign-in. "
                                     "Close anything that has its local folder open, then "
                                     "try again."}), 200
        try:
            if _mirror.mirror_enabled():
                _settings.set_values(**{_settings.MIRROR_TO_PIXAI: False})
        except (OSError, _settings.SettingsBusy) as e:
            return jsonify({"ok": True, "enabled": True,
                            "error": "The sign-in is gone, but the switch couldn't be turned "
                                     "off: " + _redact_host_paths(str(e))[:160]}), 200
        return jsonify({"ok": True, "enabled": False})

    def _connect_api_key_account():
        # The account the API key REALLY is, asked of PixAI every time: a USER_ID pinned
        # in config.json is a legacy override and must not decide whose sign-in is kept.
        from moonglade import backup as core
        s = core._make_session(None, resolve_user=False)
        try:
            return core.resolve_user_id(s)
        except core.PixAIAuthError:
            # PixAI refuses the key and no usable sign-in could answer for it (2026-11-19):
            # the account the STORED sign-in names, expired or not, is one this key was
            # already confirmed to be when that sign-in was connected. None stored: refuse.
            old = _mirror.load_mirror_state().get("jwt") or ""
            return str(_mirror.jwt_claims(old).get("sub") or "") if old else ""

    # One-click Connect (back 2026-11-19): read the pixai.art sign-in from THIS machine's
    # Chrome/Edge/Brave. The one thing the 3.20.7 route lacked is added: the token's `sub`
    # must be the account the API key resolves to (mirror.accept_site_token), so a browser
    # signed in as someone else is refused and nothing is stored.
    @app.route("/api/mirror/connect", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_connect():
        """Connect: read the pixai.art sign-in from this machine's browser, check it is the
        API key's own account, store it, run a due renewal. Answers only ok + days left, or a
        fixed plain sentence -- never the token, a claim or the account id. No credential
        crosses the network: the server reads its own local browser store. LOGIN tier, the
        session's CSRF token (body {csrf})."""
        from moonglade import backup as core
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not _check_csrf(body):
            return jsonify({"ok": False, "error": "Your session expired. Reload the page and "
                            "try again."}), 400
        try:
            core._check_read_only("connect the PixAI mirror")   # the renewal is account-mutating
        except Exception as e:                          # noqa: BLE001
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:160]}), 200
        try:
            bj = _mirror.read_browser_jwt()
        except Exception:                               # noqa: BLE001 -- the reader never raises
            bj = None
        if not bj:
            return jsonify({"ok": False, "error": "Couldn't read a pixai.art session from a "
                            "browser on this machine. Sign in to pixai.art in Chrome/Edge/Brave "
                            "(reload the page once so the token is written), then try again, "
                            "or use the Connect from PixAI bookmark."}), 200
        out = _mirror.accept_site_token(bj, _connect_api_key_account)
        if not out.get("ok"):
            return jsonify({"ok": False, "error": out.get("error") or "Not connected."}), 200
        try:
            _mirror.make_mirror_session(user_initiated=True)   # a due renewal, as before
        except Exception:                               # noqa: BLE001
            pass
        jwt = _mirror.load_mirror_state().get("jwt") or ""
        return jsonify({"ok": bool(jwt),
                        "days_left": _mirror.jwt_days_left(jwt) if jwt else None})

    @app.route("/mirror/connect")
    @tier(LOGIN)
    def mirror_connect_page():
        """The window the Control Panel's "Connect from PixAI" bookmark opens from a pixai.art
        tab. It tells its opener it is ready (to https://pixai.art only), takes the sign-in
        back only from that exact origin and that window, and hands it to
        /api/mirror/connect-token with this session's CSRF token. Login-gated like every page:
        a signed-out visitor goes through /login and lands back here, still the opener's
        window. Dressed in the login card's own classes -- no new design. Holds no credential
        itself; the page is marked no-store all the same."""
        session.setdefault("csrf", secrets.token_hex(16))
        resp = app.response_class(render_template_string(
            _noncify(MIRROR_CONNECT_PAGE.replace("__DESIGN_TOKENS__", DESIGN_TOKENS_CSS)),
            boot={"csrf": session["csrf"]}), mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.route("/api/mirror/connect-token", methods=["POST"])
    @tier(LOGIN)
    def api_mirror_connect_token():
        """Connect from PixAI: store the sign-in the user's own pixai.art tab handed over
        (body {csrf, token}). LOGIN tier, a client on this machine or a private home network
        (mirror.home_network_address) -- over HTTPS unless it is this machine -- the session's
        CSRF token, and a same-origin request
        only (an Origin header naming another site is refused). READ_ONLY refuses,
        as Connect always has. Then mirror.accept_site_token checks the token -- a PixAI JWT,
        unexpired, and for the SAME PixAI account the API key resolves to -- before storing
        it. Answers only ok + days left, or a plain sentence; never the token, a claim or the
        account id, and nothing here logs."""
        # Home network only (2026-11-18): never accept a sign-in from outside a home network.
        # Same client address the localhost-only checks read (request.remote_addr, the real
        # TCP peer; no forwarded header is trusted anywhere in this app).
        if not _mirror.home_network_address(request.remote_addr):
            return jsonify({"ok": False, "error": _mirror.SITE_TOKEN_NOT_HOME}), 403
        # And from another device, only over HTTPS (app security review 2026-11-19, finding
        # 1): a PixAI sign-in posted over plain http:// crosses the network readable by anyone
        # on it, and renews itself for whoever holds it. This PC's own loopback never leaves
        # the PC, so it may stay plain. Checked before the body is read.
        if not request.is_secure and not _is_local_request():
            return jsonify({"ok": False, "error": CONNECT_TOKEN_NEEDS_HTTPS}), 403
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"ok": False, "error": "That request didn't come from this "
                            "Moonglade page, so nothing was saved."}), 403
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not _check_csrf(body):
            return jsonify({"ok": False, "error": "Your session expired. Reload the page and "
                            "try again."}), 400
        from moonglade import backup as core
        try:
            core._check_read_only("connect the PixAI mirror")
        except Exception as e:                          # noqa: BLE001
            return jsonify({"ok": False, "error": _redact_host_paths(str(e))[:160]}), 200

        out = _mirror.accept_site_token(body.get("token"), _connect_api_key_account)
        if out.get("ok"):
            return jsonify({"ok": True, "days_left": out.get("days_left")})
        return jsonify({"ok": False, "error": out.get("error") or "Not connected."}), 200

    @app.route("/api/branding", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_branding():
        """The banner mark (the icon beside the title) + its animation. GET and POST both
        require login (any session, local or LAN) -- cosmetic, so any authorized device may
        read or change it, same as the rest of the LOGIN-tier settings surface.
        Persists to settings.json's branding (save_branding)."""
        if request.method == "GET":
            # Reflects a raw filesystem drop immediately, same as /api/achievements --
            # a caller reading branding state directly (this route, not the achievements
            # one) must never see a stale pre-adoption picture. Cheap; see
            # sweep_branding_drops()'s own docstring.
            try:
                _branding.sweep_branding_drops(out_dir)
            except Exception:
                pass
            cfg = _branding.load_branding(out_dir)
            return jsonify(dict(_branding._branding_tuning(cfg),
                                mark=cfg["mark"], anim=cfg["anim"],
                                anims=_branding.MARK_ANIMS,
                                marks=_branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path)),
                                slots=_branding.branding_slots_payload(out_dir),
                                roles=_branding.branding_roles_payload(out_dir)))
        body = request.get_json(silent=True) or {}
        cfg = _branding.load_branding(out_dir)
        _before = (cfg.get("mark"), cfg.get("anim"))
        _marks = _branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path))
        have = {m["id"] for m in _marks}
        if "anim" in body:
            anim = str(body["anim"])
            # A retired id is refused here rather than silently accepted: the picker
            # no longer offers one, so a POST carrying it is a stale client or a
            # hand-rolled call, and answering 400 is how it finds that out. (An
            # ALREADY-STORED retired pick is a different case -- load_branding wears
            # classic for it, so nobody's install breaks.)
            if anim not in _branding.MARK_ANIMS:
                return jsonify({"error": "unknown animation"}), 400
            cfg["anim"] = anim
        if "mark" in body:
            mark = str(body["mark"])
            if mark != "logo" and mark not in have:
                return jsonify({"error": "unknown mark"}), 400
            # Reward gate (2026-09-08): a mark bound to an achievement may be set
            # only once that achievement is earned -- the same refusal /api/skin
            # gives a locked skin, so a client can't force a locked mark. `logo`
            # and every free (unlock:"") mark pass; earned is computed above in
            # `_marks` off the shared recipe.
            locked = next((m for m in _marks
                           if m["id"] == mark and not m["earned"]), None)
            if locked is not None:
                # unlock_name is already spoiler-masked (empty while the feat is
                # masked -- see list_marks). NEVER fall back to the raw
                # unlock id: that would name the very feat the mask exists to
                # hide (feat/mark-gating spoiler audit 2026-09-08).
                return jsonify({"error": "mark locked",
                                "unlock": locked.get("unlock_name") or "",
                                "mark": cfg["mark"]}), 403
            cfg["mark"] = mark
        # The tuning fields: clamped, never refused. A slider that sends 4.0 gets
        # 3.0 back and the UI settles onto it -- an error toast for dragging too far
        # would be a worse answer than the honest ceiling.
        for k in ("anim_speed", "anim_scale", "glow_angle"):
            if k in body:
                cfg[k] = _branding._brand_num(k, body[k], cfg[k])
        if "glow_color" in body:
            colour = _branding._brand_color(body["glow_color"], None)
            if colour is None:
                return jsonify({"error": "glow_color must be #rrggbb"}), 400
            cfg["glow_color"] = colour
        _branding.save_branding(out_dir, cfg)
        if (cfg.get("mark"), cfg.get("anim")) != _before:   # Interior Decorator: a real change only
            _telemetry.telem_bump("skin_changed_runs", out_dir=out_dir)
        if cfg["anim"] == "eclipse":           # Eclipse: sun and moon in balance
            _telemetry.telem_flag("eclipse_anim_triggered", out_dir=out_dir)
        return jsonify(dict(_branding._branding_tuning(cfg),
                            mark=cfg["mark"], anim=cfg["anim"]))

    @app.route("/api/branding/slot", methods=["POST"])
    @tier(LOGIN)
    def api_branding_slot_upload():
        """Upload a new asset into one Branding slot (the three banner slots --
        Control Panel.dc.html's 'From disk' chip; the named roles have their own
        door, /api/branding/role, with a CSRF check this one predates). LOGIN tier,
        matching /api/branding just above: cosmetic, no host-filesystem risk
        beyond writing into branding/, the same machine-local git-ignored tree
        marks already live in (NOT the shortcut route's stricter local-only gate).
        Re-encodes through Pillow rather than trusting the upload's own bytes/
        extension, the same defense-in-depth this app already applies to real
        library thumbnails (see _thumb_for, above)."""
        slot = request.form.get("slot") or ""
        if slot not in _branding.BANNER_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        f = request.files.get("file")
        media_id = (request.form.get("media_id") or "").strip()
        if (f is None or not f.filename) and not media_id:
            return jsonify({"error": "no file"}), 400
        try:
            import io
            from PIL import Image
            if f is not None and f.filename:
                head = f.stream.read(64)
                f.stream.seek(0)
                _branding.guard_webp_canvas(head, _branding.BANNER_MAX_SIDE)       # before libwebp commits a declared canvas
                im = Image.open(f.stream)
            else:
                # "From the gallery..." (Control Panel.dc.html:342) -- source the asset
                # from the user's own library by media_id, via the same shared resolver
                # every other media_id->file path uses. Images only; a video id simply
                # resolves to no usable frame here.
                hits = _scan.find_files_for_media_id(out_dir, media_id)
                img_hit = next((p for p in hits if p.suffix.lower() in _scan._IMAGE_EXTS), None)
                if img_hit is None:
                    return jsonify({"error": "no local image for that media id"}), 400
                with open(img_hit, "rb") as fh:
                    _branding.guard_webp_canvas(fh.read(64), _branding.BANNER_MAX_SIDE)
                im = Image.open(img_hit)
            im.load()
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
        except _branding.ImageRefused as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        item = _branding.add_slot_asset(out_dir, slot, buf.getvalue())   # neutral transform to start
        return jsonify({"slot": slot, "item": item, "assets": _branding.list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/crop", methods=["POST"])
    @tier(LOGIN)
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
        if not _branding.set_slot_crop(out_dir, slot, item_id, zoom=zoom, cropx=cropx, cropy=cropy):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"assets": _branding.list_slot_assets(out_dir, slot)})

    @app.route("/api/branding/slot/active", methods=["POST"])
    @tier(LOGIN)
    def api_branding_slot_active():
        """Pick which already-uploaded asset is active for a slot. LOGIN tier,
        same as the upload route. There is no "clear to none" -- see
        set_slot_active()'s own docstring for why."""
        body = request.get_json(silent=True) or {}
        slot, item_id = body.get("slot"), body.get("id")
        if not _branding.set_slot_active(out_dir, slot, str(item_id) if item_id else None):
            return jsonify({"error": "unknown slot or asset"}), 400
        return jsonify({"slots": _branding.branding_slots_payload(out_dir)})

    @app.route("/api/branding/role", methods=["POST"])
    @tier(LOGIN)
    def api_branding_role_upload():
        """Make one picture the install's override of one image of a named role (the Branding
        tab's Roles section; a hidden, unlock-gated surface). Multipart: csrf, slot (a key of
        ROLE_SLOTS), key (one of that role's images) and either `file` (From disk) or `media_id`
        (From the gallery). LOGIN tier, with the explicit CSRF token this write class carries.
        The spec is checked and the file written in branding_role_upload() -- read that, it is the
        whole path; this handler only reads the request. The cap on the request is set before the
        form is parsed, so a body far past ROLE_MAX_BYTES is a 413 and is never spooled."""
        request.max_content_length = _branding.ROLE_MAX_BYTES + 64 * 1024     # the file, plus its form fields
        if not _check_csrf(request.form):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slot = request.form.get("slot") or ""
        if slot not in _branding.ROLE_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        body, status = _branding.branding_role_upload(
            out_dir, slot, (request.form.get("key") or "").strip(),
            upload=request.files.get("file"), media_id=(request.form.get("media_id") or "").strip(),
            check_only=request.form.get("check") == "1")
        return jsonify(body), status

    @app.route("/api/branding/role/restore", methods=["POST"])
    @tier(LOGIN)
    def api_branding_role_restore():
        """Go back to the pack's default for one role image: removes the install's override
        (the one file under the coded tree) and nothing else. LOGIN tier, CSRF-checked."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slot = str(body.get("slot") or "")          # a list or dict is not hashable: coerce before the lookup
        if slot not in _branding.ROLE_SLOTS:
            return jsonify({"error": "unknown slot"}), 400
        out, status = _branding.branding_role_restore(out_dir, slot, str(body.get("key") or ""))
        return jsonify(out), status

    @app.route("/api/branding/role/default/<slot>/<key>")
    @tier(LOGIN)
    def api_branding_role_default(slot, key):
        """The pack's own art for one role image, so the Roles row can show default beside
        yours while an override is in place. Only the nine named role images are reachable
        here; the bytes come from the container alone (never the loose tree), and an image the
        pack does not carry is a plain 404."""
        from flask import abort
        import mimetypes
        img = (_branding.ROLE_SLOTS.get(slot) or {}).get("images", {}).get(key)
        if img is None:
            abort(404)
        box = _branding._get_container()
        raw = box.get(_branding._public_rel_to_coded(img["public"])) if box else None
        if raw is None:
            abort(404)
        resp = app.response_class(raw, mimetype=mimetypes.guess_type(img["public"])[0]
                                  or "application/octet-stream")
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    @app.route("/api/branding/mark/custom", methods=["POST"])
    @tier(LOGIN)
    def api_branding_mark_custom():
        """Upload The Great Library's custom mark (Control Panel.dc.html's 6th
        marks tile). LOGIN tier + a real server-side achievement check -- unlike
        the deferred banner-earned-art masking (still local-UI-only pending the
        SQLite asset-bundling project), this route actually performs a write, so
        it gets the same real gate /api/skin already applies to earned skins."""
        if not _branding._mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "The Great Library hasn't been earned yet"}), 403
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        # An uploaded WEBP is stored verbatim, everything else is re-encoded to PNG.
        # Same reasoning as the filesystem-drop path: re-encoding an animated webp
        # keeps frame one and silently throws the animation away, which would make
        # the one format the owner authors animated marks in the one format this
        # route breaks. The bytes are still validated as an image before they land.
        raw = f.read()
        is_webp = str(f.filename).lower().endswith(".webp")
        try:
            import io
            from PIL import Image
            # The same two questions every user-picture upload asks first: a WebP's declared canvas
            # from its header (libwebp commits it all when Pillow merely opens the file), and only
            # the everyday formats ever opened.
            _branding.guard_webp_canvas(raw[:64], _branding.ROLE_MAX_SIDE)
            im = Image.open(io.BytesIO(raw), formats=_branding.ROLE_OPEN_FORMATS)
            im.load()
            if is_webp:
                art = raw
            else:
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, format="PNG")
                art = buf.getvalue()
        except _branding.ImageRefused as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "not a readable image"}), 400
        mark = _branding.add_custom_mark(out_dir, art, ext=".webp" if is_webp else ".png")
        return jsonify({"mark": mark["id"], "marks": _branding.list_marks(out_dir)})

    @app.route("/api/branding/mark/custom/remove", methods=["POST"])
    @tier(LOGIN)
    def api_branding_mark_custom_remove():
        """Remove an uploaded custom mark (Control Panel.dc.html's Remove chip).
        LOGIN tier, same as the upload route above."""
        body = request.get_json(silent=True) or {}
        mark_id = str(body.get("id") or "")
        if not _branding.remove_custom_mark(out_dir, mark_id):
            return jsonify({"error": "unknown custom mark"}), 400
        cfg = _branding.load_branding(out_dir)
        return jsonify({"mark": cfg["mark"], "marks": _branding.list_marks(out_dir)})

    @app.route("/api/branding/banners/earned")
    @tier(LOGIN)
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
            "earned": _branding._mark_earned(out_dir, db_path, "the-great-library"),
            "png": "/branding/earned_banners/great_library.png",
        }]})

    @app.route("/api/branding/banner/earned", methods=["POST"])
    @tier(LOGIN)
    def api_branding_banner_earned():
        """Apply an earned banner as the banner_main flat. Server gate is
        authoritative (the UI's locked tile is cosmetic): 403 until the
        achievement is really earned, same _mark_earned check the custom-mark
        upload runs. On success the SEALED earned_banners bytes go through the
        exact _render_banner_flat pipeline every other banner write uses
        (banner_main ratio 4:1 -> 1920x480), so the applied banner can't
        differ from an uploaded one in shape or size. The choice is stored in
        settings.json's branding.worn_banner ({"kind": "earned", "banner_id"}),
        the render beside it in the cache is stamped the same, and the ensure
        pass rebuilds it from the pack whenever the cache lacks it (B6). LOGIN
        tier, mirroring /api/branding/mark/custom."""
        body = request.get_json(silent=True)
        body = body if isinstance(body, dict) else {}   # a JSON array/string/number -> 400, not 500
        if str(body.get("id") or "") != "great_library":
            return jsonify({"error": "unknown banner"}), 400
        if not _branding._mark_earned(out_dir, db_path, "the-great-library"):
            return jsonify({"error": "banner locked"}), 403
        raw = _branding._branding_bytes(_branding._role_rel("earned_banners", "great_library.png"))
        record = {"kind": "earned", "banner_id": "great_library"}
        if raw is None or not _branding._render_banner_flat(out_dir, "banner_main", raw, record=record):
            return jsonify({"error": "banner art unavailable"}), 400
        if not _branding._set_worn_banner("banner_main", record):
            return jsonify({"error": "Couldn't save the banner choice; try again."}), 200
        return jsonify({"ok": True})

    @app.route("/api/branding/shortcut", methods=["POST"])
    @tier(LOCALHOST)
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
        settings.json's branding picks -- ordinary app data, correctly broadened)."""
        body = request.get_json(silent=True) or {}
        mark = str(body.get("mark") or _branding.load_branding(out_dir)["mark"])
        # Whitelist before anything touches the shell: only a known cut mark id
        # may become an icon path (no traversal, no quoting surprises). Gated on
        # EARNED too (red team 2026-09-08): the Desktop .lnk icon IS the app's
        # real icon, so a locked reward mark's art must not become it any more
        # than it may become the active in-app mark -- the same 403 POST
        # /api/branding gives. Free/logo marks and earned bound marks pass.
        _marks = _branding.list_marks(out_dir, _branding._earned_achievement_ids(out_dir, db_path))
        if mark not in {m["id"] for m in _marks}:
            return jsonify({"error": "unknown mark (no .ico cut for it)"}), 400
        locked = next((m for m in _marks if m["id"] == mark and not m["earned"]), None)
        if locked is not None:
            # Masked name only, never the raw unlock id -- a masked feat's
            # id must not leak through the shortcut 403 either (spoiler audit).
            return jsonify({"error": "mark locked",
                            "unlock": locked.get("unlock_name") or ""}), 403
        try:
            lnk = _branding.make_launcher_shortcut(out_dir, mark)
        except RuntimeError as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 400
        return jsonify({"ok": True, "lnk": lnk})

    @app.route("/api/outside/fix", methods=["POST"])
    @tier(LOCALHOST)
    def api_outside_fix():
        """**Fix them** on the notice about things outside the app that still name its old
        files (server_notice; moonglade.outside, DECISIONS 2026-10-07 pick 5): this machine's
        scheduled tasks, Claude tools registrations and shortcuts are looked at again, now,
        and each one found is rewritten to the new names -- a copy of it kept first in
        local\\.snapshot\\ -- and reported fixed or failed, with the reason, in plain words.

        LOCALHOST: it rewrites files and Task Scheduler entries on the machine the server runs
        on, the same trust class as /api/branding/shortcut. The CSRF explicit-token class: a
        real change to the machine off one click. One fix at a time."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        if not _OUTSIDE_FIXING.acquire(blocking=False):
            return jsonify({"error": "Already fixing them. Give it a moment."}), 409
        try:
            from moonglade import outside as moonglade_outside
            results = moonglade_outside.fix(provide_icon=_shortcut_icon_bytes)
            _outside_scan()
        finally:
            _OUTSIDE_FIXING.release()
        kind, title, msg = moonglade_outside.result_words(results)
        return jsonify({"ok": True, "kind": kind, "title": title, "msg": msg,
                        "results": [r.as_dict() for r in results]})

    @app.route("/api/suggest-prompt")
    @tier(LOGIN)
    def api_suggest_prompt():
        """Image-to-prompt for the gallery's 'Suggest prompt' button: PixAI's tag list +
        NL description for a media_id. Read-only and free; login required. ?media_id="""
        mid = (request.args.get("media_id") or "").strip()
        if not mid:
            return jsonify({"suggestions": [], "error": "media_id required"}), 400
        # 3.22 S5: PixAI reads no prompt from an SVG; refused here, before any request.
        why = _gen_params.source_refusal(_source_format_lookup(mid), "prompt")
        if why:
            return jsonify({"suggestions": [], "error": why}), 200
        try:
            core, session = _gen_session()
            return jsonify({"suggestions": core.suggest_prompt(session, mid)})
        except Exception as e:
            return jsonify({"suggestions": [], "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/tag-suggest")
    @tier(LOGIN)
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
    @tier(LOGIN)
    def api_upload():
        """Upload a local file from the picker -> PixAI media_id (the same free
        3-step S3 handshake as the CLI's --upload). Login required,
        spends nothing. At most UPLOAD_MAX_BYTES (a 413 with a plain sentence past it)."""
        request.max_content_length = UPLOAD_MAX_BYTES
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
            _telemetry.telem_bump("uploads", out_dir=out_dir)        # first-upload milestone
            return jsonify({"media_id": str(mid)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

    def _safe_extract_zip(zip_path, dest_dir, max_members=None, max_total=None):
        """Extract a zip into dest_dir, dropping any member whose resolved path would escape
        dest_dir (zip-slip). Localhost-only caller, but a crafted archive still shouldn't be
        able to write outside the temp dir.

        Capped (app security review 2026-11-19, finding 9): a zip with more than
        ZIP_MAX_MEMBERS files is refused before anything is written, and extraction stops
        the moment the bytes WRITTEN pass ZIP_MAX_TOTAL_BYTES -- counted as they are written,
        never taken from the zip's own size fields, which a zip bomb lies in. Either raises
        ZipTooBig with its plain sentence; the caller's temp dir is then thrown away."""
        import os as _os
        import zipfile as _zip
        max_members = ZIP_MAX_MEMBERS if max_members is None else max_members
        max_total = ZIP_MAX_TOTAL_BYTES if max_total is None else max_total
        root = _os.path.realpath(dest_dir)
        written = 0
        with _zip.ZipFile(zip_path) as z:
            members = [m for m in z.namelist() if not m.endswith("/")]
            if len(members) > max_members:
                raise ZipTooBig(ZIP_TOO_MANY_MEMBERS)
            for m in members:
                target = _os.path.realpath(_os.path.join(dest_dir, m))
                if target != root and not target.startswith(root + _os.sep):
                    continue                          # zip-slip -> skip
                _os.makedirs(_os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as dst:
                    member = 0
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        written += len(chunk)
                        member += len(chunk)
                        if member > ZIP_MAX_MEMBER_BYTES:
                            raise ZipTooBig(ZIP_MEMBER_TOO_BIG)
                        if written > max_total:
                            raise ZipTooBig(ZIP_TOO_BIG)
                        dst.write(chunk)
        return written

    @app.route("/api/import-local", methods=["POST"])
    @tier(LOCALHOST, message="this imports files onto the server's machine; localhost-only")
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
        import os as _os
        import tempfile
        import shutil
        from types import SimpleNamespace
        from moonglade import backup as core
        # Finding 9: one request is at most IMPORT_REQUEST_MAX_BYTES (the page's batches stay
        # far under it), and everything its zips unpack shares one ZIP_MAX_TOTAL_BYTES budget.
        request.max_content_length = IMPORT_REQUEST_MAX_BYTES
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "no files"}), 400
        collection = (request.form.get("collection") or "").strip()
        if collection and _is_smart_name(db_path, collection.replace(",", " ").strip()):
            # a smart collection is a saved search: refuse BEFORE any file is imported (N1)
            return jsonify({"error": "“{}” is a smart collection, a saved search; "
                                     "pictures can't be imported into it.".format(collection)}), 400
        tmp = tempfile.mkdtemp(prefix="mg_import_")
        try:
            saved = 0
            unzip_left = ZIP_MAX_TOTAL_BYTES
            # A guard, not the design: the web page sends a big folder in several requests
            # (hooks/useImport.js), so this is only reached by a caller that sends more at
            # once. What it does not take it COUNTS, and says so in the answer (#82) -- it
            # used to drop everything past the cap without a word.
            not_taken = max(0, len(files) - _scan.IMPORT_REQUEST_CAP)
            for i, f in enumerate(files[:_scan.IMPORT_REQUEST_CAP]):
                base = _os.path.basename(f.filename or "")
                if not base:
                    not_taken += 1          # a part with no file name: nothing to import
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
                        unzip_left -= _safe_extract_zip(dest, sub, max_total=unzip_left)
                    except ZipTooBig as e:
                        return jsonify({"error": str(e)}), 413
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
                            "not_taken": not_taken, "collection": collection or None})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    _presets_lock = threading.Lock()

    # Toolbox presets are PER-ACCOUNT, one file in each login's folder (presets.json) --
    # same shape as _view_presets_path/_snips_path. They shipped install-wide; Moonglade is
    # explicitly not single-user (the repo is public and has real external users), so on any
    # install with more than one account, install-wide meant every account could see, and
    # overwrite, every other account's imported presets. The old shared file was copied into
    # every login with none of its own by the move (moonglade.migrate), and is gone.
    def _presets_path(user):
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "presets.json"

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
        return _read_presets_data(_presets_path(user))

    @app.route("/api/presets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_presets():
        """Toolbox presets, stored per-account (presets.json in the login's folder) (preset
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
            # The explicit token, before the import reads the task from PixAI with the
            # owner's key (dev/tests/test_csrf_coverage.py).
            if not _check_csrf(body):
                return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
            tid = str(body.get("task_id") or "").strip()
            if not tid:
                return jsonify({"error": "task_id required"}), 400
            try:
                core, gsession = _gen_session()
                task = _task_reads.task_detail_gql(gsession, tid) or {}
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

    # Saved views are PER-ACCOUNT, one file in each login's folder (views.json).
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
    def _view_presets_path(user):
        # The login's own folder, keyed by a case-safe key (B14 residual): the original
        # quote(username, safe="") here was case-PRESERVING, so "Nel" and "nel" quoted to two
        # different strings that named the SAME file on NTFS (case-insensitive-but-preserving),
        # even though account identity itself is case-sensitive. See _account_key's own
        # docstring for the full story.
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "views.json"

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
        """This account's saved views. (The old install-wide file was copied into every login
        with none of its own by the move, moonglade.migrate, and is gone.)"""
        return _read_presets_file(_view_presets_path(user))

    def _ok_view_query(q):
        # Presets navigate via location.href = '/' + query on load. Requiring the
        # leading '?' (exactly what savePreset stores: location.search || '?') keeps
        # every stored value a same-page filter string -- a bare '//host' would resolve
        # protocol-relative and turn a saved view into an off-site redirect.
        return isinstance(q, str) and q.startswith("?") and len(q) <= 4096

    @app.route("/api/view-presets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_view_presets():
        """Saved-view presets (the gallery's "Saved views…" dropdown): {name: query
        string}, stored server-side in the login's folder so a view saved at the
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
                # The explicit token, like every other per-account write
                # (dev/tests/test_csrf_coverage.py): checked before the set is changed.
                if not _check_csrf(body):
                    return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
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

    # The one body shape POST /api/account/prefs accepts; anything else is refused.
    _ACCOUNT_PREFS_BODY_KEYS = frozenset(("set", "unset", "csrf"))

    @app.route("/api/account/prefs", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_account_prefs():
        """The signed-in account's own preferences document -- the store is
        account_prefs_get/account_prefs_update above (see their section header for the
        file, the key rules, the caps and the corrupt-file contract).

        GET  -> {"prefs": {...}, "csrf": "..."}. The token rides along the way
                /api/myart/items hands its own out, so the client hook needs no boot
                plumbing to make its first write.
        POST {"csrf": "...", "set": {key: value}, "unset": [key]} -> {"prefs": {...}},
                the whole updated document. Either of set/unset may be omitted, not
                both; any other top-level field is refused. One bad key or value refuses
                the whole change (400, plain message) and writes nothing.

        LOGIN tier -- per-account state, the same tier as /api/view-presets,
        /api/snippets and the Loom's store. CSRF: the explicit-token class
        (_check_csrf(), the helper /api/duplicates/resolve and the user-admin routes
        use), because this is a state-changing POST a single forged request could
        otherwise drive.

        The account comes from the SESSION, never the body -- same contract as every
        per-account store here: a client that could name the account could read and
        overwrite anyone's."""
        user = str(session.get("user") or "")
        if not user:
            # Unreachable through the front door; fails closed if that ever changes,
            # and never falls back to ACCOUNT_LOCAL or a shared file.
            return jsonify({"error": "authentication required"}), 401
        if request.method == "GET":
            session.setdefault("csrf", secrets.token_hex(16))
            return jsonify({"prefs": _account_prefs.account_prefs_get(out_dir, user),
                            "csrf": session["csrf"]})
        if (request.content_length or 0) > 2 * _account_prefs.ACCOUNT_PREFS_DOC_MAX:
            return jsonify({"error": "That change is too large to save."}), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object: "
                                     "{\"set\": {...}, \"unset\": [...]}."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        extra = sorted(str(k) for k in body if k not in _ACCOUNT_PREFS_BODY_KEYS)
        if extra:
            return jsonify({"error": "Unknown field(s): {}. Send only 'set' and "
                                     "'unset'.".format(", ".join(extra)[:120])}), 400
        if "set" not in body and "unset" not in body:
            return jsonify({"error": "Nothing to change: send 'set' and/or 'unset'."}), 400
        if "set" in body and not isinstance(body["set"], dict):
            return jsonify({"error": "'set' must be an object of {key: value}."}), 400
        if "unset" in body and not isinstance(body["unset"], list):
            return jsonify({"error": "'unset' must be a list of keys."}), 400
        try:
            prefs = _account_prefs.account_prefs_update(out_dir, user, set_=body.get("set"),
                                         unset=body.get("unset"))
        except _account_prefs.AccountPrefsError as e:
            return jsonify({"error": str(e)}), 400
        except _account_prefs.AccountPrefsBusy as e:
            return jsonify({"error": str(e)}), 503
        except OSError as e:
            return jsonify({"error": "Could not save preferences: "
                                     + _redact_host_paths(str(e))[:160]}), 500
        return jsonify({"prefs": prefs})

    # ---- the in-app guide (Session I) -- see the module-level section "THE IN-APP GUIDE
    # AND THE ABOUT CARD" for what each piece reads. All four are read-only and LOGIN tier:
    # the guide is for anyone who can sign in, LAN sessions included, and none of them
    # writes, spends or reaches PixAI. ------------------------------------------------------
    @app.route("/api/help/index")
    @tier(LOGIN)
    def api_help_index():
        """The guide's page list (sidebar order, with each page's headings for the search),
        the Glossary's terms, and the version stamp the overlay prints."""
        from moonglade import backup as core
        return jsonify({
            "version": core.__version__,
            "display_version": _about.display_version(core.__version__),
            "pages": _about.wiki_index(),
            "glossary": _about.wiki_glossary(),
            "wiki_url": _about.WIKI_WEB_URL,
        })

    def _help_page_file(slug):
        """The page file for `slug`, looked up in the listing -- never a path built from
        the request. None for anything the listing did not find."""
        if not _about._WIKI_SLUG_RE.match(str(slug or "")):
            return None
        return _about._wiki_pages_on_disk(_about.wiki_dir()).get(slug)

    @app.route("/api/help/page/<slug>")
    @tier(LOGIN)
    def api_help_page(slug):
        """One page's markdown, as text. The client parses it into plain data and renders
        it through React, so nothing here is ever HTML."""
        p = _help_page_file(slug)
        if p is None:
            return jsonify({"error": "That page is not in this install's guide."}), 404
        try:
            md = p.read_text(encoding="utf-8")
        except OSError as e:
            return jsonify({"error": "Could not read that page: "
                                     + _redact_host_paths(str(e))[:160]}), 500
        return jsonify({"slug": slug, "markdown": md, "url": _about.wiki_web_url(slug)})

    @app.route("/api/help/online/<slug>")
    @tier(LOGIN)
    def api_help_online(slug):
        """Does the online wiki carry a newer copy of this page? Asked after the page has
        rendered, so a slow or absent network never holds the reader up. Only consults
        GitHub when the updater's own cached answer says a newer release is out -- see
        wiki_online_differs -- so an up-to-date install never asks at all."""
        p = _help_page_file(slug)
        if p is None:
            return jsonify({"error": "That page is not in this install's guide."}), 404
        try:
            md = p.read_text(encoding="utf-8")
        except OSError:
            return jsonify({"differs": False, "url": _about.wiki_web_url(slug)})
        behind = bool((_updater._update_cache.get("payload") or {}).get("behind"))
        return jsonify({"differs": _about.wiki_online_differs(slug, md, behind),
                        "url": _about.wiki_web_url(slug)})

    @app.route("/api/help/about")
    @tier(LOGIN)
    def api_help_about():
        """The About card: this version's CHANGELOG entry, the release's size (which decides
        between the what's-new sheet and About after an update), the art pack, the earlier
        entries. Whether a newer release is out is /api/update/check's to say, not this."""
        from moonglade import backup as core
        return jsonify(_about.about_payload(core.__version__, _branding._container_path()))

    # -- split: web_loom_store (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import web_loom_store as _web_loom_store
    ctx = _SimpleNamespace(
        out_dir=out_dir,
    )
    _web_loom_store.register(app, ctx)
    _LOOM_ID_RE = ctx._LOOM_ID_RE
    _LOOM_REV_MISSING = ctx._LOOM_REV_MISSING
    _LoomUnreadable = ctx._LoomUnreadable
    _legacy_loom_kv_dir = ctx._legacy_loom_kv_dir
    _legacy_loom_kv_path = ctx._legacy_loom_kv_path
    _loom_bed_path = ctx._loom_bed_path
    _loom_beds_dir = ctx._loom_beds_dir
    _loom_beds_unreadable_answer = ctx._loom_beds_unreadable_answer
    _loom_board_saved = ctx._loom_board_saved
    _loom_journal_finish_task = ctx._loom_journal_finish_task
    _loom_journal_live_for = ctx._loom_journal_live_for
    _loom_journal_load = ctx._loom_journal_load
    _loom_journal_lock = ctx._loom_journal_lock
    _loom_journal_note = ctx._loom_journal_note
    _loom_kv_dir = ctx._loom_kv_dir
    _loom_kv_path = ctx._loom_kv_path
    _loom_kv_text = ctx._loom_kv_text
    _loom_kv_write = ctx._loom_kv_write
    _loom_lock = ctx._loom_lock
    _loom_migrate = ctx._loom_migrate
    _loom_rev_of = ctx._loom_rev_of
    _loom_send_note = ctx._loom_send_note
    _loom_sending_now = ctx._loom_sending_now
    _loom_sends_append = ctx._loom_sends_append
    _loom_sends_lines = ctx._loom_sends_lines
    _loom_sends_lock = ctx._loom_sends_lock
    _loom_store_bed = ctx._loom_store_bed
    _loom_tomb_path = ctx._loom_tomb_path
    _loom_unused_beds = ctx._loom_unused_beds
    # -- end --

    # The app's three data routes: /api/library, /api/detail/<media_id>, /api/history, each
    # on exactly one path. They used to answer on a second one under /api/next/, the React
    # app's pilot codename, for one release of grace; that is gone, and a page left open
    # from before 3.17.0 needs a reload (dev/tests/test_api_route_aliases.py pins it). The
    # /next/assets/ prefix above is NOT part of this: installed phone apps read their icons
    # from it, so it is never dropped.
    @app.route("/api/library")
    @tier(LOGIN)
    def api_library():
        """The new gallery's own listing surface -- full filter set, clean field
        names, one purpose. Reads the same catalog engine (query_catalog) as
        everything else; nothing here is borrowed from the picker routes.

        Two dial-in-series modes ride on top (#34 direction B), both no-ops unless
        the client opts in, so the default payload is exactly what it was before:
          * ?group=series -- fold the FULL filtered set into series UNITS: a
            multi-task series becomes ONE card (its cover row + a `series` key with
            the sid/counts/title), every other row stays its own card, and paging
            counts units, not rows. Grouping is server-side because a series spans
            many pages (up to 801 images) -- a client can't collapse what it never
            sees on one page.
          * ?series=<sid> -- the complement: the ungrouped listing constrained to
            one series' members (B's 'open a stack' navigation), resolved in SQL by
            query_catalog. Ignored while group=series (grouping supersedes it)."""
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
        group = (request.args.get("group") or "").strip()
        series = (request.args.get("series") or "").strip()
        # One filter set, keyed by query_catalog()/list_group_rows()'s own param
        # names, so the paged row query and the whole-set grouping query see an
        # IDENTICAL WHERE + ORDER.
        filters = dict(
            q=q, sort=sort, rating_min=rating_min, media_type=media,
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

        _pers = {}     # media_id -> personal layer, filled once per page (Session N3)

        def _card(r):
            """One grid card dict for a catalog row -- the SINGLE definition both the
            plain row listing and a grouped unit's cover build, so a series cover is
            byte-identical to that same media as an ordinary card (only the extra
            `series` key ever differs)."""
            mid = r.get("media_id")
            pl = _pers.get(str(mid)) or {}
            return {
                # The owner's own layer (N3): the keeper|reject mark the card wears, and the
                # tags. Local catalog only.
                "mark": pl.get("mark", ""),
                "tags": pl.get("tags", []),
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
                # Session H T3a: the Lightbox edit bar is offered on the same pictures as the
                # "Edit with Tsubaki" menu item -- every still, whatever model made it (owner
                # ruling, 2026-09-28). Never on a video.
                "tsubaki_edit": str(r.get("is_video") or "") != "1",
                # #66: PixAI no longer has it, so this is the only copy -- the card's
                # corner pill reads ARCHIVE.
                "archive_only": is_archive_only(r),
            }

        if group == "series":
            by_task, by_sid = _series.series_index(db_path)
            # The whole filtered set, ids + the four grouping columns only, in sort
            # order. Bounded (measured in dev/tests/test_series_grouping.py).
            unit_order, members = _series.fold_series_units(
                list_group_rows(db_path, **filters), by_task)
            total = len(unit_order)
            start = (page - 1) * page_size
            page_keys = unit_order[start:start + page_size]
            # Resolve this page's units to ONE cover media_id each (the newest
            # surviving image of the unit), then fetch just those full rows -- one
            # query, at most page_size rows.
            cover_ids = [str(_series._series_cover_row(members[k]).get("media_id") or "")
                         for k in page_keys]
            full = {str(r.get("media_id")): r
                    for r in rows_for_media_ids(db_path, cover_ids)}
            _pers.update(personal_get(db_path, cover_ids))
            items = []
            for k, mid in zip(page_keys, cover_ids):
                r = full.get(mid)
                if r is None:
                    continue
                card = _card(r)
                if k[0] == "series":
                    s = by_sid.get(k[1]) or {}
                    card["series"] = {
                        "sid": k[1],
                        # count_tasks is the series' FULL task (version) count from
                        # by_sid -- the dial's step count, a property of the series
                        # itself, not of the current filter. count_images is the
                        # SURVIVING member count (cheap -- we already hold them), so a
                        # filtered stack's image tally matches what the filter left
                        # visible rather than overcounting hidden members.
                        "count_tasks": s.get("count_tasks", 0),
                        "count_images": len(members[k]),
                        "title": s.get("title", ""),
                    }
                elif k[0] == "task" and len(members[k]) >= 2:
                    # A folded BATCH -- one task with >=2 surviving images (not a
                    # multi-task series). Mark it so the grid renders a BATCH stack that
                    # opens through the existing View-batch path (?batch=task_id). A lone
                    # image (one survivor) carries no marker and renders as today's plain
                    # singleton, indistinguishable from an ungrouped card.
                    card["batch"] = {"task_id": k[1], "count": len(members[k])}
                items.append(card)
        else:
            rows, total = query_catalog(
                db_path, page=page, page_size=page_size, series=series, **filters)
            _pers.update(personal_get(db_path, [r.get("media_id") for r in rows]))
            items = [_card(r) for r in rows if r.get("media_id")]
        pages = max(1, (total + page_size - 1) // page_size)
        return jsonify({"items": items, "total": total, "page": page, "pages": pages})

    @app.route("/api/detail/<media_id>")
    @tier(LOGIN)
    def api_detail(media_id):
        """The pilot's Details view backing data -- classic's detail() route (~12254),
        JSON instead of a server-rendered page. Full row, plus prev_id/next_id computed
        the SAME way: list_media_ids() under the CURRENT filter/sort (the same param
        names /api/library accepts), index looked up in that ordered id list.

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
            # The View batch drill-down (#81): the list route filters by it, so the walk
            # this picture sits in -- its "k of N" and Prev/Next -- must stay inside it too.
            batch=(request.args.get("batch") or "").strip(),
            # The opened stack (?series=<sid>), same reason: /api/library honours it, so the
            # walk a picture opened from a stack sits in stays inside that stack.
            series=(request.args.get("series") or "").strip(),
            published_only=(request.args.get("published") or "") == "1")
        try:
            idx = nav_ids.index(media_id)
        except ValueError:
            idx = -1
        prev_id = nav_ids[idx - 1] if idx > 0 else None
        next_id = nav_ids[idx + 1] if 0 <= idx < len(nav_ids) - 1 else None
        # Where this picture sits in the WHOLE filtered walk and how long the walk is --
        # the same list prev/next came from, so no second query (#64). The phone prints
        # them as "14 of 3,240"; a picture the filter does not contain has no position.
        position = idx + 1 if idx >= 0 else None
        pl = personal_get(db_path, [media_id]).get(str(media_id)) or {}
        out = {
            "row": row,
            # The owner's own layer over this picture (N3): tags, keeper|reject, a note.
            "personal": {"tags": pl.get("tags", []), "mark": pl.get("mark", ""),
                         "note": pl.get("note", "")},
            "prev_id": prev_id, "next_id": next_id,
            "position": position, "nav_total": len(nav_ids),
            # Same value the gallery's own "Delete from PixAI" is gated on. A LAN
            # session can browse and spend, but not destroy on the owner's real
            # cloud account.
            "can_delete_cloud": _is_local_request(),
            "siblings": _batch_sibling_count(row.get("task_id")),
            # #66: gone from PixAI as of the last check -- the record says so, and its
            # "Delete locally" names it the last copy before it asks.
            "archive_only": is_archive_only(row),
        }
        # Session M (NOTES 3): the run this picture came from, when the caller's own account
        # sent it through the dock -- History reuse restores the TEMPLATE from it, not the
        # resolved prompt. A read of the Runs store; absent for everything else.
        run = _run_for_task(row.get("task_id"))
        if run is not None:
            out["run"] = run
        return jsonify(out)

    def _run_for_task(task_id):
        try:
            from moonglade import runs
            found = runs.RunsStore(out_dir).find_task(task_id)
        except Exception:                                    # noqa: BLE001
            return None
        if not found:
            return None
        run, job = found
        if run.get("account") != str(session.get("user") or ""):
            return None
        return {"run_id": run.get("run_id"), "mode": run.get("mode"),
                "template": run.get("template") or "", "var_mode": run.get("var_mode") or "",
                "count": run.get("count"), "run_seed": run.get("run_seed"),
                "dock_seed": run.get("dock_seed") or "", "cell": job.get("cell"),
                "vars": job.get("vars") or []}

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

    @app.route("/api/history")
    @tier(LOGIN)
    def api_history():
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
        from moonglade import backup as core
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

        since_utc, until_utc = utc_iso(start_local), utc_iso(end_local)
        page = history_page(db_path, since_utc, until_utc, media=media, source=source)
        rows = page["rows"]
        # Paging cursor: the NEWEST row older than this window, so the next page
        # opens on a day that has runs instead of a run of empty days.
        next_before, older_days = None, 0
        older_ts = _history_ts(page["older_created_at"]) if page["older_created_at"] else None
        if older_ts is not None:
            nb_date = local_date(older_ts) + timedelta(days=1)
            nb_local = datetime(nb_date.year, nb_date.month, nb_date.day, tzinfo=tzinfo)
            next_before = nb_date.isoformat()
            older_days = len({
                local_date(t) for t in (
                    _history_ts(c) for c in history_created_ats(
                        db_path,
                        utc_iso(nb_local - timedelta(days=days)), utc_iso(nb_local),
                        media=media, source=source))
                if t is not None})

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
            jobs = _jobs.read_jobs(out_dir)
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

    def _find_local_video_file(mid, row=None):
        """Resolve a catalog media_id to its local video file on disk -- the app-bound face
        of the module-level find_local_video_file (which holds the whole rule and its
        reasons), supplying this library's out_dir and, when the caller has none, its row.

        Shared by /api/loom/handoff (frame extraction), /api/loom/video-duration
        (footage-import fallback probe), the detail page's does-this-clip-exist check, and
        /video-file itself. That last one is the point rather than a nicety: while
        /video-file resolved `row["filename"]` on its own, the page could decide a clip was
        present (via the fallback here) and then link to a URL that 404s, which draws a dead
        player and says nothing -- the very failure the detail-page check was added to stop.
        One resolver, four callers, one answer. (The fifth, since 2026-09-26, is the
        reference-video length lookup -- core.make_video_duration_lookup -- which calls the
        module-level function so the CLI's --reference-video reads the same answer.)

        `row` is an already-loaded catalog row, passed by callers that just fetched it so
        this doesn't repeat a primary-key SELECT they already paid for. It is a cache, not
        an override: pass a DIFFERENT row and you get a different file, which is why only
        the two callers holding this exact mid's row use it."""
        return _scan.find_local_video_file(out_dir, mid,
                                     row if row is not None else get_row(db_path, mid))

    def _loom_complete_clip(mid):
        """The library file for a clip id, only when it is a COMPLETE file (Invariant 3: a
        .part download and a zero-byte file are not there) inside the library. Or None."""
        p = _find_local_video_file(mid)
        if p is None:
            return None
        try:
            if (p.name.endswith(".part") or not p.is_file() or p.stat().st_size <= 0
                    or not _scan._is_under(p.resolve(), out_dir.resolve())):
                return None
        except OSError:
            return None
        return p


    # -- split: routes_generate (split_move) --
    from types import SimpleNamespace as _SimpleNamespace
    from moonglade import routes_generate as _routes_generate
    ctx = _SimpleNamespace(
        _LOOM_ID_RE=_LOOM_ID_RE,
        _account_is_member=_account_is_member,
        _check_csrf=_check_csrf,
        _collect_single_flight=_collect_single_flight,
        _entitlements=_entitlements,
        _gen_session=_gen_session,
        _input_media_id=_input_media_id,
        _is_local_request=_is_local_request,
        _load_presets=_load_presets,
        _log_job=_log_job,
        _loom_complete_clip=_loom_complete_clip,
        _loom_journal_finish_task=_loom_journal_finish_task,
        _loom_send_note=_loom_send_note,
        _reconcile_orphan_jobs=_reconcile_orphan_jobs,
        _redact_host_paths=_redact_host_paths,
        _task_stream=_task_stream,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_generate.register(app, ctx)
    _QUOTED_FREE_GONE = ctx._QUOTED_FREE_GONE
    _Reached = ctx._Reached
    _log_gen_failure = ctx._log_gen_failure
    _note_card_sent = ctx._note_card_sent
    _send_claim = ctx._send_claim
    _send_failed = ctx._send_failed
    _send_key = ctx._send_key
    _send_settle = ctx._send_settle
    _source_format_lookup = ctx._source_format_lookup
    _video_duration_lookup = ctx._video_duration_lookup
    # -- end --

    # -- split: routes_loom (split_move) --
    from moonglade import routes_loom as _routes_loom
    ctx = _SimpleNamespace(
        _LOOM_ID_RE=_LOOM_ID_RE,
        _LOOM_REV_MISSING=_LOOM_REV_MISSING,
        _LoomUnreadable=_LoomUnreadable,
        _QUOTED_FREE_GONE=_QUOTED_FREE_GONE,
        _Reached=_Reached,
        _ach_sid=_ach_sid,
        _check_csrf=_check_csrf,
        _export_dir=_export_dir,
        _export_job=_export_job,
        _export_lock=_export_lock,
        _find_local_video_file=_find_local_video_file,
        _gen_session=_gen_session,
        _input_media_id=_input_media_id,
        _legacy_loom_kv_dir=_legacy_loom_kv_dir,
        _legacy_loom_kv_path=_legacy_loom_kv_path,
        _log_gen_failure=_log_gen_failure,
        _loom_bed_path=_loom_bed_path,
        _loom_beds_dir=_loom_beds_dir,
        _loom_beds_unreadable_answer=_loom_beds_unreadable_answer,
        _loom_board_saved=_loom_board_saved,
        _loom_complete_clip=_loom_complete_clip,
        _loom_journal_live_for=_loom_journal_live_for,
        _loom_journal_load=_loom_journal_load,
        _loom_journal_lock=_loom_journal_lock,
        _loom_journal_note=_loom_journal_note,
        _loom_kv_dir=_loom_kv_dir,
        _loom_kv_path=_loom_kv_path,
        _loom_kv_text=_loom_kv_text,
        _loom_kv_write=_loom_kv_write,
        _loom_lock=_loom_lock,
        _loom_migrate=_loom_migrate,
        _loom_rev_of=_loom_rev_of,
        _loom_send_note=_loom_send_note,
        _loom_sending_now=_loom_sending_now,
        _loom_sends_append=_loom_sends_append,
        _loom_sends_lines=_loom_sends_lines,
        _loom_sends_lock=_loom_sends_lock,
        _loom_store_bed=_loom_store_bed,
        _loom_tomb_path=_loom_tomb_path,
        _loom_unused_beds=_loom_unused_beds,
        _noncify=_noncify,
        _note_card_sent=_note_card_sent,
        _redact_host_paths=_redact_host_paths,
        _send_claim=_send_claim,
        _send_failed=_send_failed,
        _send_key=_send_key,
        _send_settle=_send_settle,
        _source_format_lookup=_source_format_lookup,
        _video_duration_lookup=_video_duration_lookup,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_loom.register(app, ctx)
    # -- end --

    # --- Recipes (Session K + H3/H8/H10; lane w2-recipes) --------------------------------
    # PixAI's recipe market, a recipe's page, Mine, Sets and the creator's writes, over
    # moonglade.recipes (its module docstring has the whole contract). Reads are LOGIN, like
    # every other catalog-of-PixAI read here. Every write is a deliberate click: LOGIN,
    # explicit-token CSRF (_check_csrf), READ_ONLY refused inside moonglade.recipes before
    # its first network call, one attempt. Nothing here writes when a surface opens, and
    # GET /v2/recipes/draft (which CREATES a draft) is never called -- the creator's drafts
    # are the account's own prefs until the user publishes.

    def _recipes():
        from moonglade import recipes as moonglade_recipes
        return moonglade_recipes

    def _recipe_fail(e, **extra):
        """A read or write that failed, as the house's {error} answer (HTTP 200: the body
        is the answer, api.js's one rule)."""
        out = {"error": _redact_host_paths(str(e))[:240]}
        out.update(extra)
        return jsonify(out), 200

    def _recipe_user_id(core, gsession):
        uid = str(_pixai_client._client_of(gsession).user_id or "")
        if not uid:
            uid = core.resolve_user_id(gsession)
        return uid

    @app.route("/api/recipes/meta")
    @tier(LOGIN)
    def api_recipes_meta():
        """What every recipe surface needs once: the live category and model-type lists,
        the CSRF token for its writes, and the account's PixAI id (Mine and Sets)."""
        session.setdefault("csrf", secrets.token_hex(16))
        rec = _recipes()
        try:
            core, gsession = _gen_session()
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"categories": list(rec.CATEGORIES),
                            "model_types": list(rec.MODEL_TYPES),
                            "csrf": session["csrf"], "user_id": "",
                            "max_recipes": rec.MAX_RECIPES,
                            "error": _redact_host_paths(str(e))[:200]})
        try:
            uid = _recipe_user_id(core, gsession)
        except Exception:                                        # noqa: BLE001
            uid = ""
        return jsonify({"categories": rec.categories(gsession),
                        "model_types": rec.model_types(gsession),
                        "csrf": session["csrf"], "user_id": uid,
                        "max_recipes": rec.MAX_RECIPES})

    @app.route("/api/recipes/market")
    @tier(LOGIN)
    def api_recipes_market():
        """One page of the market: ?sort=trending|most-liked|most-used|latest, page,
        page_size, category, model_type, model_id, q (search; newest first)."""
        a = request.args
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().market(
                gsession, sort=a.get("sort", "trending"), page=a.get("page", 1),
                page_size=a.get("page_size", 24), category=a.get("category", ""),
                model_type=a.get("model_type", ""), model_id=a.get("model_id", ""),
                query=a.get("q", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/capability")
    @tier(LOGIN)
    def api_recipes_capability():
        """Which ingredient kinds a model takes, and how many of each (?model_type= or
        ?model_id=). Read live; the creator never guesses."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().capability(
                gsession, request.args.get("model_type", ""),
                request.args.get("model_id", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, slots=[])

    @app.route("/api/recipes/batch")
    @tier(LOGIN)
    def api_recipes_batch():
        """Recipe cards by id (?ids=a,b,c, up to 20) -- the dock's chips after a reload."""
        ids = [i for i in (request.args.get("ids") or "").split(",") if i.strip()]
        try:
            core, gsession = _gen_session()
            return jsonify({"items": _recipes().batch(gsession, ids)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/recent")
    @tier(LOGIN)
    def api_recipes_recent():
        """The picker's History tab: recipes this account used most recently."""
        try:
            core, gsession = _gen_session()
            return jsonify({"items": _recipes().recently_used(
                gsession, request.args.get("limit", 30), request.args.get("model_type", ""))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/mine")
    @tier(LOGIN)
    def api_recipes_mine():
        """Mine: this account's recipes, archived and in-review ones included (PixAI never
        lists drafts; the app's own drafts live in the account prefs)."""
        a = request.args
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().user_recipes(
                gsession, _recipe_user_id(core, gsession), sort=a.get("sort", "latest"),
                cursor=a.get("cursor", ""), limit=a.get("limit", 30),
                model_type=a.get("model_type", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/style-code")
    @tier(LOGIN)
    def api_recipes_style_code():
        """A legacy style code -> the recipe that replaced it (?code=&version_id=), or
        {recipe: null} for "No recipe replaces this code"."""
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": _recipes().by_style_code(
                gsession, request.args.get("code", ""), request.args.get("version_id", ""))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, recipe=None)

    @app.route("/api/recipes/from-image")
    @tier(LOGIN)
    def api_recipes_from_image():
        """⁂ Make a recipe (K decision 4). ?media_id=X&check=1 answers only whether the
        picture's model takes recipes (one cached /features read per model version); without
        `check`, the creator's step-2 prefill: the model, the task's LoRAs (version, weight,
        trigger words), the prompt, and the picture itself. The category is never guessed.
        A picture this library has no row for is refused (the route runs on the owner's
        credentials; the /api/task-params rule)."""
        mid = str(request.args.get("media_id") or "").strip()
        row = get_row(db_path, mid) if mid else None
        if not row:
            return jsonify({"error": "no such picture in this library", "capable": False}), 404
        if str(row.get("is_video") or "") == "1":
            return jsonify({"capable": False, "why": "a video"})
        vid = str(row.get("model_id") or "").strip()
        if not vid:
            return jsonify({"capable": False, "why": "this picture's model isn't recorded"})
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            feats = _models._model_features(gsession, vid)
            mtype = (feats or {}).get("model_type") or ""
            capable = bool(mtype) and mtype in rec.model_types(gsession)
            out = {"capable": capable, "model_type": mtype, "version_id": vid,
                   "model_title": str(row.get("model_name") or "")}
            if request.args.get("check") or not capable:
                return jsonify(out)
            base = _models.resolve_model_base_id(gsession, vid)
            prompt = str(row.get("prompt_full") or row.get("prompt_preview") or "")
            loras, unresolved = [], 0
            tid = str(row.get("task_id") or "").strip()
            task = _task_reads.task_detail_gql(gsession, tid, retries=1) if tid else None
            params = (task or {}).get("parameters") or {}
            if isinstance(params.get("prompts"), str) and params.get("prompts").strip():
                prompt = params["prompts"]
            lmap = params.get("lora") if isinstance(params.get("lora"), dict) else {}
            for lvid, weight in lmap.items():
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    unresolved += 1
                    continue
                lbase = _models.resolve_model_base_id(gsession, str(lvid))
                rows = _models.list_model_versions(gsession, lbase) if lbase else []
                vrow = next((r for r in rows if r.get("version_id") == str(lvid)), None) or {}
                loras.append({"version_id": str(lvid), "model_id": lbase, "weight": w,
                              "title": str(_models.model_name_gql(gsession, str(lvid)) or "")
                              or str(lvid),
                              "trigger_words": str(vrow.get("trigger_words") or "")})
            out.update({"model_id": base, "prompt": prompt, "loras": loras,
                        "unresolved": unresolved + (0 if task or not tid else 1),
                        "media_id": mid, "thumb": "/thumbs/{}.jpg".format(mid)})
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, capable=False)

    @app.route("/api/recipes/sets")
    @tier(LOGIN)
    def api_recipes_sets():
        """The Sets tab: this account's recipe sets (PixAI's collections of recipes)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().sets_list(gsession, _recipe_user_id(core, gsession),
                                                cursor=request.args.get("cursor", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/recipes/sets/for/<recipe_id>")
    @tier(LOGIN)
    def api_recipes_sets_for(recipe_id):
        """"Save to a recipe set": every set, each with whether it holds this recipe."""
        try:
            core, gsession = _gen_session()
            return jsonify({"sets": _recipes().sets_for(gsession, recipe_id)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/recipes/sets/<set_id>/items")
    @tier(LOGIN)
    def api_recipes_set_items(set_id):
        """One set's recipes."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().set_items(gsession, set_id,
                                                request.args.get("cursor", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/<recipe_id>")
    @tier(LOGIN)
    def api_recipes_detail(recipe_id):
        """One recipe (the owner's view carries its slots; everyone else's, kinds only)."""
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": _recipes().detail(gsession, recipe_id)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, recipe=None)

    @app.route("/api/recipes/<recipe_id>/artworks")
    @tier(LOGIN)
    def api_recipes_artworks(recipe_id):
        """"Made with it" on a recipe's page (?sort=latest|most-liked, page)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().artworks(
                gsession, recipe_id, request.args.get("sort", "latest"),
                request.args.get("page", 1), request.args.get("page_size", 12)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/<recipe_id>/tasks")
    @tier(LOGIN)
    def api_recipes_tasks(recipe_id):
        """This account's generations with a recipe (?usage=test|normal)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().tasks(
                gsession, recipe_id, request.args.get("usage", ""),
                request.args.get("page", 1), request.args.get("page_size", 12)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    def _recipe_write_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return None, (jsonify({"error": "Expected a JSON object."}), 400)
        if not _check_csrf(body):
            return None, (jsonify({"error": "Your session expired. Reload the page and "
                                            "try again."}), 400)
        return body, None

    @app.route("/api/recipes/publish", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_publish():
        """Publish the creator's draft (K decision 5): {csrf, draft, recipe_id?}. Creates
        the recipe on PixAI when there is no id yet (PixAI keeps ONE unfinished recipe per
        account and discards any other -- step 3 says so before this click), saves the full
        body, and moves it draft -> test -> published. Answers {recipe} or {error,
        recipe_id} -- the id of a recipe the create made before a later step failed, which
        the client keeps so the next attempt updates it rather than making another."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.publish(gsession, body.get("draft"),
                                                  body.get("recipe_id") or "")})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code, recipe_id=e.recipe_id)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/update", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_update():
        """Save an edit to an existing recipe (full replace): {csrf, recipe_id, draft,
        version}. `version` is the recipe's version when the creator opened it; a recipe
        changed on PixAI since is refused, not overwritten. Answers the recipe as PixAI
        reads it afterwards -- status `test` is "in review"."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.update(gsession, body.get("recipe_id"),
                                                 body.get("draft"), body.get("version"))})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/transition", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_transition():
        """Archive or unarchive (Mine): {csrf, recipe_id, to: archived|published}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.transition(gsession, body.get("recipe_id"),
                                                     str(body.get("to") or ""))})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/sets/create", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_set_create():
        """+ New set: {csrf, title}. A private collection of recipes on PixAI."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify({"set": _recipes().set_create(gsession, body.get("title"))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/sets/toggle", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_set_toggle():
        """A tick in "Save to a recipe set": {csrf, set_id, recipe_id, on, item_id?}.
        Applies at once (K decision 7: no Save button)."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().set_toggle(gsession, body.get("set_id"),
                                                 body.get("recipe_id"), bool(body.get("on")),
                                                 body.get("item_id") or ""))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    # ---- The model pickers' Saved tab (Session S): PixAI's model collections ----------------
    # Reads: the rail, a model's state (the "Keep this model" menu opens on it), the removed
    # models. Writes: ⊕ Save, a menu tick, taking a removed model's entry out, + New set --
    # each CSRF-checked here and READ_ONLY-checked first in moonglade.recipes, one attempt and
    # a read-back that decides the answer. A page of a set rides /api/model-search?src=saved.

    def _saved_kind():
        return "lora" if (request.args.get("kind") or "").lower() == "lora" else "base"

    def _read_only_flag(core):
        return bool(core.READ_ONLY or core._read_only_now())

    @app.route("/api/model-saved/sets")
    @tier(LOGIN)
    def api_model_saved_sets():
        """The rail: Saved first, then named sets A-Z, counting this picker's kind (?kind=base|
        lora), plus how many saved models PixAI no longer has, and whether READ_ONLY is on."""
        try:
            core, gsession = _gen_session()
            out = _recipes().model_sets(gsession, _recipe_user_id(core, gsession), _saved_kind())
            out["read_only"] = _read_only_flag(core)
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/model-saved/state")
    @tier(LOGIN)
    def api_model_saved_state():
        """One model's place in the account's sets (?model_id=): the selector, a read only."""
        try:
            core, gsession = _gen_session()
            out = _recipes().model_state(gsession, request.args.get("model_id", ""))
            out["read_only"] = _read_only_flag(core)
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/model-saved/old")
    @tier(LOGIN)
    def api_model_saved_old():
        """S2c: the old bookmarks Saved does not hold (?kind=base|lora), tagged "old". The old
        list is read as the Bookmarked tab read it (the website's identity)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_old_bookmarks(
                gsession, _mirror.present_as_web(gsession), _recipe_user_id(core, gsession),
                _saved_kind()))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, rows=[])

    @app.route("/api/model-saved/unavailable")
    @tier(LOGIN)
    def api_model_saved_unavailable():
        """"K not available ▸": the removed models in Saved (?expect=K stops the walk early)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_unavailable(
                gsession, _recipe_user_id(core, gsession), request.args.get("expect", 0)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/model-saved/save", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_save():
        """⊕ Save: {csrf, model_id} -> Saved on PixAI, then the read-back's answer."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_save(gsession, _recipe_user_id(core, gsession),
                                                 body.get("model_id")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/tick", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_tick():
        """A PixAI tick in "Keep this model": {csrf, set_id, model_id, on, item_id?}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_tick(gsession, body.get("set_id"),
                                                 body.get("model_id"), bool(body.get("on")),
                                                 body.get("item_id") or ""))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/remove", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_remove():
        """Take a removed model's entry out of Saved: {csrf, item_id}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_remove_gone(gsession, _recipe_user_id(core, gsession),
                                                        body.get("item_id")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/sets/create", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_set_create():
        """+ New set in "Keep this model": {csrf, title}. A private model set on PixAI."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            made = _recipes().set_create(gsession, body.get("title"), content_type="model")
            return jsonify({"set": made})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    # --- The inbox, comments, gifts and the current event (Sessions R + Y, lane R) -------
    # Over moonglade.inbox (its docstring has the contract and the four write rules). Reads
    # are LOGIN, like every other read of PixAI here. A write is a deliberate press: LOGIN,
    # explicit-token CSRF (_check_csrf), then moonglade.inbox's own function -- READ_ONLY
    # first, one attempt, a read-back that decides the answer. Nothing here writes when the
    # panel opens, a list scrolls or a push arrives. Strangers' words pass through to the
    # browser and are never written to the catalog, a file or a log line.

    def _inbox():
        from moonglade import inbox as moonglade_inbox
        return moonglade_inbox

    def _inbox_fail(e, **extra):
        """A read that failed, as the house's {error} answer (HTTP 200: the body is the
        answer, api.js's one rule). PixAI's own message only -- never the words of a comment."""
        out = {"error": _redact_host_paths(str(e))[:240]}
        out.update(extra)
        return jsonify(out), 200

    def _inbox_read_only():
        from moonglade import backup as core
        return bool(core.READ_ONLY or core._read_only_now())

    def _inbox_local_media(items):
        """Fill each work's local media id (Details opens on it), from the catalog."""
        ids = [i["artwork"]["id"] for i in items if i.get("artwork")]
        found = artwork_media_ids(db_path, ids) if ids else {}
        for i in items:
            if i.get("artwork"):
                i["artwork"]["media_id"] = found.get(i["artwork"]["id"], "")
        return items

    def _inbox_tasks_to_activity(tasks):
        """R2c: TASK is never an inbox row -- Activity tells a job. A recent finished generation
        PixAI names that Activity never saw joins it as an ordinary done row, source "pixai"
        (the website mark) and via "inbox"; a row Activity holds as failed or stalled that PixAI
        says finished gets the "PixAI says: done" note through /api/jobs. A local log line only:
        nothing is sent to PixAI. Fails soft -- the inbox read must never break over it."""
        if not tasks:
            return
        try:
            from moonglade import backup as core
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            for add in _inbox().task_activity(tasks, jobs_by_id):
                _log_job(add["job_id"], status="done", type="generate", label=add["label"],
                         source="pixai", via="inbox")
        except Exception:                                        # noqa: BLE001
            pass

    @app.route("/api/inbox/pushed")
    @tier(LOGIN)
    def api_inbox_pushed():
        """What the socket pushed since ?after=<seq>, as full inbox rows (the comment toast
        names who and which work). One read of the newest rows, none when nothing is new;
        nothing is marked read."""
        try:
            ib = _inbox()
            out = ib.pushed_since(ib.pixai_session(), request.args.get("after") or 0)
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[])
        out["items"] = _inbox_local_media(out["items"])
        return jsonify(out)

    @app.route("/api/inbox")
    @tier(LOGIN)
    def api_inbox():
        """One page of PixAI's inbox, newest first (?before=<cursor> pages older). Opening the
        panel is this one read and nothing else: no mark-read, no count write. Also answers
        read_only (the rows say why nothing gets marked) and the CSRF token its writes carry."""
        session.setdefault("csrf", secrets.token_hex(16))
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            page = ib.list_notifications(gsession, before=request.args.get("before") or None)
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[], csrf=session["csrf"],
                               read_only=_inbox_read_only())
        _inbox_tasks_to_activity(page["tasks"])
        return jsonify({"items": _inbox_local_media(page["items"]), "cursor": page["cursor"],
                        "has_more": page["has_more"], "csrf": session["csrf"],
                        "read_only": _inbox_read_only()})

    @app.route("/api/inbox/count")
    @tier(LOGIN)
    def api_inbox_count():
        """The doors' badges: PixAI's unread count (TASK excluded) for the inbox, the pending
        gifts for the gift box, and their total for the phone's Menu. Read on app open, on focus (the client debounces 30 s) and on a socket reconnect.
        Carries the CSRF token too, so a write that comes before the panel ever opened (a
        comment toast's Open thread) never goes out with an empty one."""
        session.setdefault("csrf", secrets.token_hex(16))
        try:
            out = dict(_inbox().unread_total(_inbox().pixai_session()))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, total=None, csrf=session["csrf"])
        out["csrf"] = session["csrf"]
        return jsonify(out)

    @app.route("/api/inbox/events")
    @tier(LOGIN)
    def api_inbox_events():
        """ON PIXAI NOW: the banners PixAI runs whose link is under /event/. Public and sent
        with no credential; cached an hour. The app never follows a link -- a press opens it."""
        return jsonify({"events": _inbox().current_events()})

    def _inbox_write_body():
        """The JSON body of an inbox write, or a refusal: CSRF before anything else."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return body, (jsonify({"error": "Your session expired. Reload the page and try "
                                            "again."}), 400)
        return body, None

    def _inbox_write(fn, *args):
        """Run one of moonglade.inbox's writes and hand back its answer. A crash past its own
        handling is an unclear answer, never a success."""
        ib = _inbox()
        try:
            return jsonify(fn(ib.pixai_session(), *args))
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"state": "unclear", "error": _redact_host_paths(str(e))[:200],
                            "message": "No clear answer. Nothing was sent twice; check on "
                                       "PixAI."})

    @app.route("/api/inbox/read", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_read():
        """Opening a row or a work card: {csrf, ids}. One mark-read write and its read-back."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        ids = body.get("ids") if isinstance(body.get("ids"), list) else []
        return _inbox_write(_inbox().mark_read, ids)

    @app.route("/api/inbox/read-all", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_read_all():
        """⋯ Mark all read: {csrf, tab}. One watermark write for the tab's unread types."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        return _inbox_write(_inbox().mark_all_read, str(body.get("tab") or ""))

    def _own_work(artwork_id):
        """True when `artwork_id` is one of the owner's own published works -- a row in this
        library. Replies are for those alone (v1), and the thread is read only for them."""
        aid = str(artwork_id or "").strip()
        return bool(aid.isdigit() and artwork_media_ids(db_path, [aid]))

    @app.route("/api/comments/<artwork_id>")
    @tier(LOGIN)
    def api_comments(artwork_id):
        """A published work's comment thread (?page=N, 50 a page, newest first): read live when
        Details' comments section scrolls into view, kept five minutes in memory, never
        archived. Also: who "you" are (the account's id and display name, for the reply's
        question), read_only (the reply box shows disabled with the reason) and the CSRF token."""
        session.setdefault("csrf", secrets.token_hex(16))
        extra = {"csrf": session["csrf"], "read_only": _inbox_read_only()}
        if not _own_work(artwork_id):
            return _inbox_fail("Comments show for your own published works only.",
                               items=[], **extra)
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            out = dict(ib.read_thread(gsession, artwork_id, request.args.get("page") or 1))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[], **extra)
        out.update(extra, my_name=ib.display_name(gsession))
        return jsonify(out)

    @app.route("/api/comments/<artwork_id>/reply", methods=["POST"])
    @tier(LOGIN)
    def api_comments_reply(artwork_id):
        """[Post publicly] in the reply's question: {csrf, reply_to, content}. One POST and its
        read-back (moonglade.inbox.post_reply). Your own works only."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        if not _own_work(artwork_id):
            return jsonify({"state": "refused", "message": "Replies are for your own published "
                                                           "works only. Nothing was posted."})
        return _inbox_write(_inbox().post_reply, artwork_id, body.get("reply_to"),
                            body.get("content"))

    @app.route("/api/comments/<artwork_id>/delete", methods=["POST"])
    @tier(LOGIN)
    def api_comments_delete(artwork_id):
        """[Delete] in "Delete my reply"'s question: {csrf, message_id}. One DELETE and its
        read-back (moonglade.inbox.delete_reply). Your own reply on your own work only."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        if not _own_work(artwork_id):
            return jsonify({"state": "refused", "message": "Only your own replies on your own "
                                                           "works. Nothing was deleted."})
        return _inbox_write(_inbox().delete_reply, artwork_id, body.get("message_id"))

    @app.route("/api/inbox/gifts")
    @tier(LOGIN)
    def api_inbox_gifts():
        """The Gifts tab and the phone's Gift box: PixAI's REWARD messages (the side-effect-free
        thread read -- never the DM mark-read) and the credit-pack bonuses on hand, which open
        PixAI. No thread at all is the real empty state."""
        session.setdefault("csrf", secrets.token_hex(16))
        extra = {"csrf": session["csrf"], "read_only": _inbox_read_only()}
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            out = dict(ib.list_gifts(gsession))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, gifts=[], bonuses=[], **extra)
        out.update(extra, bonuses=ib.credit_bonuses(gsession),
                   my_name=ib.display_name(gsession))      # the claim preview names the account
        return jsonify(out)

    @app.route("/api/inbox/gifts/claim", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_gifts_claim():
        """[Claim] in a gift's preview: {csrf, id}. One claim write and its status read-back."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        return _inbox_write(_inbox().claim_gift, body.get("id"))

    # Flask's own `static` endpoint is the one route this module does not define,
    # so it is the one that cannot carry a @tier at its `def`. It is declared
    # here rather than skipped: /static/ is gated by the front door exactly like
    # everything else, and `if rule.endpoint == "static": continue` is the single
    # most common way a catch-all route rule grows a hole.
    declare_endpoint_tier(app, "static", LOGIN)

    # Every registered rule must now carry a tier -- checked here, at app
    # creation, not in CI. See assert_every_route_declares_a_tier().
    assert_every_route_declares_a_tier(app)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# The line the server prints (to serve.log, under the launcher) before a move's stop sentence:
# the launcher shows the last such line when its server stops as it starts (S10).
PREPARE_MARK = "[prepare] "
# How long a server must serve before its start counts as clean (S1).
CLEAN_SERVE_S = 600.0


def _count_clean_start(prepared):
    """Count this server's start as clean (moonglade.setup.Prepared.count_clean_start) and log
    what that did. Never raises."""
    try:
        rep = prepared.count_clean_start()
        rep.log()
    except Exception:                                   # noqa: BLE001 -- bookkeeping only
        pass


def _say_port_refused(owner, port):
    who = ("another Moonglade server is ALREADY serving"
           if owner == "moonglade" else "something else is listening")
    print("\nRefusing to start: {} on port {}.\n".format(who, port), file=sys.stderr)
    if owner == "moonglade":
        print("  Open the one that's already running:  http://localhost:{}/\n"
              .format(port), file=sys.stderr)
    if _supervised():
        # Started by Moonglade Launcher, which passes no flags: the port and the switches are
        # in settings.json, and that is where the way out is.
        settings = _paths.settings_path()
        print("  Find it:  netstat -ano | findstr :{}      (then: taskkill /F /PID <pid>)\n"
              "  Or use a different port: set \"port\" to {} in {} (the launcher passes\n"
              "  no flags), then start Moonglade again.\n"
              "\n"
              "  Starting anyway would bind a SECOND server to the same port -- Windows\n"
              "  allows that -- and requests would land on either one at random. Add\n"
              "  \"--allow-port-reuse\" to \"launch_args\" in the same file if you genuinely\n"
              "  want that.\n".format(port, port + 1, settings), file=sys.stderr)
        return
    print("  Find it:  netstat -ano | findstr :{}      (then: taskkill /F /PID <pid>)\n"
          "  Or just use a different port:  --port {}\n"
          "\n"
          "  Starting anyway would bind a SECOND server to the same port -- Windows\n"
          "  allows that -- and requests would land on either one at random. Pass\n"
          "  --allow-port-reuse if you genuinely want that.\n".format(port, port + 1),
          file=sys.stderr)


def _say_port_unbindable(port, err):
    """The server could not open its port at all (a Windows excluded port range, a privileged
    port, another program that holds it exclusively): the same way out as a taken port."""
    print("\nRefusing to start: Moonglade can't open port {} ({}).\n".format(
        port, getattr(err, "strerror", None) or err), file=sys.stderr)
    if _supervised():
        print("  Use a different port: set \"port\" to {} in {} (the launcher passes no\n"
              "  flags), then start Moonglade again.\n".format(port + 1, _paths.settings_path()),
              file=sys.stderr)
    else:
        print("  Use a different port:  --port {}\n".format(port + 1), file=sys.stderr)
    print("  On Windows a port can be held back by the system (an excluded range); list those\n"
          "  with:  netsh int ipv4 show excludedportrange protocol=tcp\n", file=sys.stderr)


def _port_taken_early(args, planned):
    """S1: is this start's port already taken, judged before the move runs? `planned` is
    moonglade.setup.peek_server(): the host, port and launch switches this start will use
    once the settings are in place. Says why on stderr, as the later check does."""
    if getattr(args, "allow_port_reuse", False) or \
            "--allow-port-reuse" in (planned.get("launch_args") or []):
        return False
    owner = port_owner(planned["host"], planned["port"])
    if owner:
        _say_port_refused(owner, planned["port"])
        return True
    return False


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

    `Moonglade Launcher.pyw` already probes the X-Moonglade header to decide "one of our
    servers is already up here" before launching. That check lived ONLY in the
    launcher, so `python -m moonglade.gallery --port N` -- how every script, test
    harness and background agent starts this thing -- walked straight past it.
    Same probe, moved to where it cannot be bypassed.

    The header is the right signal rather than the status code: /api/ping sits
    behind the login gate and answers 401, so "did it 200" would read a live
    gated server as a dead port (see dev/tests/test_web_auth.py's
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


def prepare_tls(host, https_everywhere, bonjour_name, hostname=None, lan_ip=None):
    """HTTPS for this start (moonglade.tls): (mode, ssl context or None, the authority's SHA-256
    fingerprint, the plain sentence when there is no HTTPS). A bind other devices can reach, or
    --https, gets the certificate; anything at all that goes wrong making or loading it -- a
    PC name the certificate format cannot carry, a missing package, an unwritable folder --
    means plain HTTP and one line saying why, never a server that does not start."""
    import logging as _log_mod
    from moonglade import bonjour as moonglade_bonjour
    from moonglade import tls as _tls
    if not (https_everywhere or moonglade_bonjour.is_lan_bind(host)):
        return _tls.TLS_OFF, None, "", ""
    try:
        if hostname is None:
            import socket as _socket
            hostname = _socket.gethostname()
        ip = moonglade_bonjour.lan_ip() if lan_ip is None else lan_ip
        cert_p, key_p = _tls.ensure_certificate(
            dns_names=[hostname, hostname + ".local",
                       moonglade_bonjour.hostname_label(bonjour_name) + ".local"],
            ip_addresses=[ip or ""])
        ctx = _tls.server_context(cert_p, key_p)
        return (_tls.TLS_ALL if https_everywhere else _tls.TLS_LAN), ctx, _tls.fingerprint(), ""
    except Exception as e:                              # noqa: BLE001 -- HTTPS never stops a start
        problem = (str(e) if isinstance(e, _tls.TLSUnavailable) else
                   "Moonglade couldn't set up HTTPS ({}: {}).".format(type(e).__name__,
                                                                     str(e)[:200]))
        print("{}\nServing plain HTTP: another device's traffic is not encrypted, and "
              "Connect from PixAI works only on this PC.".format(problem))
        _log_mod.getLogger(__name__).warning("HTTPS off for this start: %s", problem)
        return _tls.TLS_OFF, None, "", problem


def main():
    # prog: the usage line names the command as it is typed (3.20).
    ap = argparse.ArgumentParser(prog="python -m moonglade.gallery",
                                 description="Local PixAI gallery server.")
    # default=None, not "pixai_backup": argparse cannot tell "the user typed the default"
    # from "the user typed nothing". None is the only value that means "not specified", and
    # then the library, host and port come from local/settings.json (the Control Panel).
    ap.add_argument("--out", default=None,
                    help="library folder for this start. Defaults to the library folder set in "
                         "the Control Panel, or pixai_backup beside the app. An explicit --out "
                         "here always wins, and is never stored.")
    ap.add_argument("--port", type=int, default=None,
                    help="bind port for this start (default: the Control Panel's Bonjour chip, "
                         "or 5000)")
    ap.add_argument("--host", default=None,
                    help="bind address for this start (default: the Control Panel's Bonjour "
                         "chip, or 127.0.0.1; use 0.0.0.0 for LAN). An explicit --host always "
                         "wins.")
    ap.add_argument("--allow-port-reuse", action="store_true",
                    help="start even if something is already listening on --port. Off by "
                         "default because Windows lets a SECOND server bind an actively "
                         "serving port, after which requests hit either one at random.")
    ap.add_argument("--https", action="store_true",
                    help="serve EVERY connection over HTTPS, this PC's own included. Other "
                         "devices on the home network get HTTPS without it whenever the server "
                         "listens there; this switch adds this PC. One self-signed certificate, "
                         "made once in local\\ (needs the 'cryptography' package); a browser "
                         "shows a one-time certificate warning")
    ap.add_argument("--rebuild-thumbs", action="store_true",
                    help="regenerate all thumbnails even if they already exist")
    ap.add_argument("--skip-thumbs", action="store_true",
                    help="don't build catalog thumbnails on startup (fast boot; missing "
                         "ones show 'no preview'). Per-generation thumbs are still made.")
    ap.add_argument("--open-browser", action="store_true",
                    help="open the gallery in your default browser ~1.5s after the server "
                         "starts (manual convenience for a terminal launch; the double-click "
                         "'Moonglade Launcher' does NOT pass this -- it polls the server "
                         "until it actually answers and opens the browser itself)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show INFO-level log lines (request activity, startup steps) on the "
                         "console too -- the log FILE in local/logs/ always captures them "
                         "regardless of this flag")
    args = ap.parse_args()
    from moonglade import setup as moonglade_setup
    # S1: a second server bows out BEFORE the move, so it never moves anything under a running
    # one. The port is read without changing anything (moonglade.setup.peek_server: the
    # stored settings, or the ones an older version left, read the way the merge will read
    # them); the full check below runs again once the settings are in place.
    if _port_taken_early(args, moonglade_setup.peek_server(args.host, args.port)):
        return 2
    # B2: the move runs FIRST -- the settings merge and the install half, then the library's --
    # before anything below reads a setting, a record or a log. A move that cannot finish (a
    # lock held past its wait, a file in use) stops the start with its plain sentence: the new
    # homes would otherwise read empty. The sentence goes to stderr (serve.log under the
    # launcher) behind PREPARE_MARK, which the launcher looks for to show it (S10).
    try:
        prepared = moonglade_setup.prepare("server", explicit_out=args.out)
    except moonglade_setup.MoveStopped as e:
        print("\n" + PREPARE_MARK + str(e) + "\n", file=sys.stderr)
        return 3
    # The launch switches settings.json keeps (launch_args, S17) apply to every start; this
    # start's own command line adds to them.
    stored = _settings.launch_args()
    if stored:
        args = ap.parse_args(stored + sys.argv[1:])
    # settings.json is the source of truth for host/port + Bonjour (the Control Panel's chip
    # writes it); an explicit --host/--port still overrides. Fill args in place so the rest of
    # main() -- port_owner, the companion gate, make_server, the cookie name -- is unchanged.
    _srv = resolve_server_settings(args.host, args.port)
    args.host, args.port = _srv["host"], _srv["port"]

    out_dir = Path(prepared.library)
    from moonglade import logs as moonglade_logging
    moonglade_logging.setup_logging(verbose=args.verbose)
    _install_signal_note()
    prepared.log()
    # A fresh clone has neither the (git-ignored) output folder nor a catalog -- refusing
    # to start here used to be the ONLY thing a brand-new user saw: a console exit, before
    # the web app's own first-run wizard (paste a key, run the first sync) ever had a
    # chance to render. Create the folder and an empty, schema-initialized catalog instead
    # and let the server boot; the wizard banner is what guides them from there.
    folder_was_there = out_dir.is_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # A library folder that was missing when prepare() looked but was here by now (a NAS waking
    # up, a drive put back) was not looked at: do it now, before anything reads it, or this
    # session would serve an un-moved library over empty spend guards. A folder this very
    # mkdir made holds nothing to move.
    if folder_was_there:
        try:
            prepared.late_library()
        except moonglade_setup.MoveStopped as e:
            print("\n" + PREPARE_MARK + str(e) + "\n", file=sys.stderr)
            return 3

    db_path = out_dir / "catalog.db"

    # No catalog yet -> schema-init an empty db and boot; the setup wizard guides from
    # there. The legacy catalog.csv auto-seed was retired 2026-08-24 (#19).
    if _db_is_empty(db_path):
        init_db(db_path)
        print("No catalog yet in {} -- starting anyway. "
              "Use the setup wizard on the gallery's home page, "
              "or run `python -m moonglade --sync` yourself.".format(out_dir))

    thumb_dir = out_dir / "gallery" / "thumbs"
    print("Loading catalog...")
    rows = load_catalog(db_path)
    if args.skip_thumbs:
        print("Skipping thumbnail build (--skip-thumbs).")
    else:
        print("Building thumbnails (new only — use --rebuild-thumbs to force all)...")
        # recheck=False: the gallery must not wait on the one-time see-through re-check (it
        # opens every original); it is scheduled behind the started server below instead.
        build_thumbnails(rows, out_dir, thumb_dir, force=args.rebuild_thumbs, recheck=False)

    # Secrets at rest (app security review 2026-11-19, finding 5): the copies already on disk
    # are limited to this user's account once per start; every later write does the same.
    _secure_files.restrict_existing_secrets()

    # HTTPS on the home network (finding 1; moonglade.tls). A server other devices can reach
    # speaks HTTPS to them with ONE certificate made once in local\ (its fingerprint shown in
    # the Control Panel's LAN card), while this PC's own loopback keeps plain HTTP; --https
    # makes every client, this PC included, use https://. Both protocols answer on the same
    # port, so the address only changes its scheme. Without the 'cryptography' package (or
    # with a certificate that can't be saved) it serves plain HTTP and says so.
    from moonglade import bonjour as moonglade_bonjour
    from moonglade import tls as _tls
    tls_mode, tls_ctx, tls_fp, tls_problem = prepare_tls(
        args.host, bool(getattr(args, "https", False)), _srv["bonjour_name"])
    # The scheme this PC's own address uses, and the one other devices use.
    scheme = "https" if tls_mode == _tls.TLS_ALL else "http"
    lan_scheme = "https" if tls_mode != _tls.TLS_OFF else "http"

    # REFUSE to become the second server on this port -- see port_owner()'s docstring
    # for why the OS will happily let us, and what that silently costs.
    if not getattr(args, "allow_port_reuse", False):
        owner = port_owner(args.host, args.port)
        if owner:
            _say_port_refused(owner, args.port)
            return 2

    # One-time, and only on a REAL start: move any rendered banner flat still
    # sitting at the coded root into this install's banner cache. Here rather
    # than in create_app() because it is the only startup step that WRITES
    # destructively to the coded tree, and create_app() is what every test
    # builds -- see _migrate_root_banner_flats' own docstring. The scaffold call
    # is additive and idempotent (create_app runs it again, to no effect); it is
    # repeated here so a legacy install's role-tree migration happens BEFORE the
    # flats are looked for, not after.
    _branding.ensure_branding_discovery_tree()
    _branding._migrate_root_banner_flats(out_dir)
    # Same rule, same reason: this WRITES settings.json's branding slots, which
    # are not out_dir-scoped, so it stays out of create_app().
    # Ordered last of the three -- after the scaffold, so a legacy install's
    # assets are already in the coded dirs to resolve against, and before
    # create_app(), so its ensure pass stamps renders with a recorded pick.
    _branding._record_slot_resolution(out_dir)
    # The pack's Explorer file type, per-user and fail-soft (register_pack_file_type). After
    # the rename and the scaffold, so the pack and a custom mark's .ico are where it looks.
    _branding.register_pack_file_type(out_dir)
    app = create_app(out_dir)
    app.config["MG_TLS_MODE"] = tls_mode
    app.config["MG_TLS_FINGERPRINT"] = tls_fp
    app.config["MG_TLS_PROBLEM"] = tls_problem
    url = "{}://{}:{}/".format(
        scheme, "localhost" if args.host == "0.0.0.0" else args.host, args.port)
    print("\nGallery ready ->  {}".format(url))
    import logging as _ready_logging
    _ready_logging.getLogger(__name__).info("server started: pid %d, supervised %s, https %s",
                                            os.getpid(), _supervised(), tls_mode)
    if tls_mode != _tls.TLS_OFF:
        _lan = moonglade_bonjour.lan_ip()
        if tls_mode == _tls.TLS_LAN and _lan:
            print("Other devices: https://{}:{}/".format(_lan, args.port))
        print("(self-signed HTTPS: a browser shows a one-time certificate warning; check it "
              "shows this SHA-256 fingerprint:\n {})".format(tls_fp))
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
    # (measured: connect 312ms vs 39ms of actual server work on /api/detail).
    # Keep-alive reuse hides it, every new connection pays it -- hence "sometimes."
    # A second werkzeug server on [::1], same port, same app, makes the browser's
    # first attempt succeed instead. The main IPv4 bind below is UNTOUCHED (LAN via
    # --host 0.0.0.0 keeps working exactly as before); an explicit non-loopback
    # --host skips this; no IPv6 stack on the machine -> fail-soft, nothing changes.
    # Both listeners are moonglade.tls's server (Werkzeug's threaded server, answering HTTPS
    # and plain HTTP on one port; plain only when tls_ctx is None), read once here so a test
    # that stands a fake in for moonglade.tls.make_server replaces both.
    _make_server = _tls.make_server
    if args.host in ("127.0.0.1", "0.0.0.0", "localhost"):
        try:
            import threading as _threading
            _srv6 = _make_server("::1", args.port, app, tls_context=tls_ctx)
            _SERVER_CONTROL["companion"] = _srv6
            _threading.Thread(target=_srv6.serve_forever, daemon=True,
                              name="moonglade-ipv6-loopback").start()
        except Exception:
            pass                     # IPv6 unavailable -- IPv4-only, as ever
    # Graceful serving: hold the server object (not app.run()'s fire-and-forget) so a web
    # Stop/Restart can srv.shutdown() it and let the `finally` below run real cleanup -- the same
    # make_server the [::1] companion above already uses. serve_forever() blocks until shutdown()
    # (web Stop/Restart) or Ctrl+C; the pending exit code then rides `sys.exit(main())` to the
    # supervisor (0 = stop, 42 = relaunch).
    try:
        srv = _make_server(args.host, args.port, app, tls_context=tls_ctx)
    except OSError as e:
        _say_port_unbindable(args.port, e)
        return 2
    _SERVER_CONTROL["srv"] = srv
    _SERVER_CONTROL["exit_code"] = 0
    # S1: this start counts toward deleting the move's safety snapshots only once it has
    # served for a while (CLEAN_SERVE_S), or when it is stopped cleanly (below) -- never for
    # a server that refused its port or fell over as it started.
    import threading as _count_threading
    _count_timer = _count_threading.Timer(CLEAN_SERVE_S, _count_clean_start, (prepared,))
    _count_timer.daemon = True
    _count_timer.start()
    # mDNS / Bonjour LAN advertising (opt-in, fail-soft). Register after make_server has bound
    # the socket, so the advertised service is immediately reachable; the goodbye fires in the
    # finally below -- which now actually runs, thanks to step 1's graceful shutdown. The
    # advertiser (and the running host/port/scheme with it) is stashed so the Control Panel's
    # Bonjour chip can toggle or re-point it live, no restart.
    # The scheme stashed and advertised is the one OTHER devices use (https:// once
    # moonglade.tls is on), since they are who the broadcast and the LAN card's address are for.
    _bonjour = moonglade_bonjour.BonjourAdvertiser()
    _SERVER_CONTROL["bonjour"] = _bonjour
    _SERVER_CONTROL["serving"] = {"host": args.host, "port": args.port, "scheme": lan_scheme}
    try:
        if _srv["bonjour_enabled"] and moonglade_bonjour.is_lan_bind(args.host):
            if _bonjour.start(_srv["bonjour_name"], args.port, lan_scheme):
                print("Bonjour: broadcasting as {}  ({}://{}:{}/)".format(
                    _bonjour.hostname, lan_scheme, _bonjour.hostname, args.port))
    except Exception:                    # noqa: BLE001 -- advertising must never stop the server
        pass
    # Warm the Health memo off-thread, now that the socket is bound and requests can already
    # be served. AFTER startup, never blocking it: this is a daemon thread doing a disk walk,
    # and its only job is to make the FIRST Health open of the session a memory read instead
    # of a full library walk with the user watching. See _health_prime / health_cached.
    _health._health_prime(out_dir, db_path)
    # Look for things outside the app that still name its old files (a scheduled task, a
    # Claude registration, a shortcut): off-thread, for the notice (server_notice).
    _outside_prime()
    # The one-time see-through thumbnail check, behind the started server, two workers.
    if not args.skip_thumbs and not args.rebuild_thumbs:
        start_see_through_recheck(rows, out_dir, thumb_dir)
    clean_stop = False
    interrupted = False
    try:
        srv.serve_forever()
        clean_stop = True
    except KeyboardInterrupt:
        clean_stop = True            # Ctrl+C on a terminal launch -> clean stop (exit 0)
        interrupted = True
    finally:
        # First, and wrapped: one line saying what ended the server (#95), in serve.log (a
        # flushed print: the console handler passes warnings only) and in moonglade.log. A
        # failure here can never stop the cleanup below.
        try:
            _stop_code = _SERVER_CONTROL.get("exit_code", 0)
            _stop_sched = bool(_SERVER_CONTROL.get("exit_scheduled"))
            if not clean_stop and not _stop_sched:
                _stop_code = 1               # an error is leaving: Python exits with 1
            _stop_why = server_exit_reason(_stop_sched, _stop_code,
                                           _SERVER_CONTROL.get("exit_why", ""), interrupted,
                                           errored=not clean_stop)
            _stop_up = _span_words(time.monotonic() - _SERVER_BOOT)
            import logging as _stop_logging
            _stop_logging.getLogger(__name__).info(
                "server stopping: %s (pid %d, up %s, exit code %d)",
                _stop_why, os.getpid(), _stop_up, _stop_code)
            print("[server] %s stopping: %s (pid %d, up %s, exit code %d)" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), _stop_why, os.getpid(), _stop_up,
                _stop_code), flush=True)
        except Exception:                    # noqa: BLE001 -- a log line only
            pass
        _count_timer.cancel()
        # A Stop (exit 0) is a clean start's end; a Restart (42) counts only through the
        # timer, so a run of quick Restarts never deletes the snapshots.
        if clean_stop and _SERVER_CONTROL.get("exit_code", 0) == 0:
            _count_clean_start(prepared)
        b = _SERVER_CONTROL.get("bonjour")
        if b is not None:
            b.stop()                 # mDNS goodbye -- devices drop moonglade.local promptly
        companion = _SERVER_CONTROL.get("companion")
        if companion is not None:
            try:
                companion.shutdown()
            except Exception:
                pass
            try:
                companion.server_close()
            except Exception:
                pass
        try:
            srv.server_close()
        except Exception:
            pass
    return _SERVER_CONTROL.get("exit_code", 0)


if __name__ == "__main__":
    # ONE SERVER (split phase 4). `python -m moonglade.gallery` runs this file as __main__, an
    # unregistered module. Code that moved out of create_app reaches gallery with a call-time
    # `from moonglade.gallery import ...`, which would load a SECOND copy whose _SERVER_CONTROL,
    # _OUTSIDE and exit record main() never set. So main() runs in the registered module, the one
    # every importer (and the test suite) gets; this copy only defined names and is not used again.
    # The engine's version of the same fix is moonglade/__main__.py (dev/tests/test_cli_one_engine.py).
    # sys.exit(...) rather than a bare call: main()'s return code (0 stop, 42 restart, 2 and 3
    # refusals) is the launcher's contract.
    import moonglade.gallery as _server
    sys.exit(_server.main())

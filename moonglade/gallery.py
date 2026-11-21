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
from moonglade import redact as _redact
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
from moonglade import watch_plans as _watch_plans
from moonglade import web_sessions as _web_sessions
from moonglade import web_tiers as _web_tiers

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

    # -- split: routes_panel (split_move) --
    from moonglade import routes_panel as _routes_panel
    ctx = _SimpleNamespace(
        PANEL_ACTIONS=PANEL_ACTIONS,
        _LIVING_STALE_ACTIONS=_LIVING_STALE_ACTIONS,
        _artworks_job_busy=_artworks_job_busy,
        _artworks_kick=_artworks_kick,
        _check_csrf=_check_csrf,
        _collect_single_flight=_collect_single_flight,
        _gen_session=_gen_session,
        _is_local_request=_is_local_request,
        _job_busy=_job_busy,
        _living_runnable=_living_runnable,
        _load_sched=_load_sched,
        _log_job=_log_job,
        _note_power_request=_note_power_request,
        _panel_job=_panel_job,
        _panel_lock=_panel_lock,
        _panel_run=_panel_run,
        _redact_host_paths=_redact_host_paths,
        _save_sched=_save_sched,
        _sched_lock=_sched_lock,
        _standing_action=_standing_action,
        _standing_runnable=_standing_runnable,
        _update_busy=_update_busy,
        _update_busy_refusal=_update_busy_refusal,
        _watch_lock=_watch_lock,
        _watch_status=_watch_status,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_panel.register(app, ctx)
    # -- end --

    # -- split: routes_delete (split_move) --
    from moonglade import routes_delete as _routes_delete
    ctx = _SimpleNamespace(
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_delete.register(app, ctx)
    _batch_sibling_count = ctx._batch_sibling_count
    # -- end --

    # -- split: routes_recipes (split_move) --
    from moonglade import routes_recipes as _routes_recipes
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
    )
    _routes_recipes.register(app, ctx)
    _read_only_flag = ctx._read_only_flag
    _recipe_user_id = ctx._recipe_user_id
    _recipes = ctx._recipes
    # -- end --

    # -- split: routes_library (split_move) --
    from moonglade import routes_library as _routes_library
    ctx = _SimpleNamespace(
        _batch_sibling_count=_batch_sibling_count,
        _check_csrf=_check_csrf,
        _csp_nonce=_csp_nonce,
        _gen_session=_gen_session,
        _is_local_request=_is_local_request,
        _read_only_flag=_read_only_flag,
        _recipe_user_id=_recipe_user_id,
        _recipes=_recipes,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_library.register(app, ctx)
    _find_local_video_file = ctx._find_local_video_file
    _loom_complete_clip = ctx._loom_complete_clip
    # -- end --


    # -- split: routes_account (split_move) --
    from moonglade import routes_account as _routes_account
    ctx = _SimpleNamespace(
        _asset_job=_asset_job,
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_account.register(app, ctx)
    _load_presets = ctx._load_presets
    # -- end --


    # -- split: routes_community (split_move) --
    from moonglade import routes_community as _routes_community
    ctx = _SimpleNamespace(
        _artworks_kick=_artworks_kick,
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _log_job=_log_job,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_community.register(app, ctx)
    # -- end --


    # -- split: routes_train (split_move) --
    from moonglade import routes_train as _routes_train
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
        thumb_dir=thumb_dir,
    )
    _routes_train.register(app, ctx)
    # -- end --


    # -- split: routes_ach (split_move) --
    from moonglade import routes_ach as _routes_ach
    ctx = _SimpleNamespace(
        _ach_sid=_ach_sid,
        _check_csrf=_check_csrf,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_ach.register(app, ctx)
    # -- end --


    # -- split: routes_mirror (split_move) --
    from moonglade import routes_mirror as _routes_mirror
    ctx = _SimpleNamespace(
        MIRROR_CONNECT_PAGE=MIRROR_CONNECT_PAGE,
        _check_csrf=_check_csrf,
        _is_local_request=_is_local_request,
        _noncify=_noncify,
        _redact_host_paths=_redact_host_paths,
    )
    _routes_mirror.register(app, ctx)
    # -- end --


    # -- split: routes_branding (split_move) --
    from moonglade import routes_branding as _routes_branding
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _redact_host_paths=_redact_host_paths,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_branding.register(app, ctx)
    # -- end --


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

    # -- split: routes_import (split_move) --
    from moonglade import routes_import as _routes_import
    ctx = _SimpleNamespace(
        _check_csrf=_check_csrf,
        _gen_session=_gen_session,
        _redact_host_paths=_redact_host_paths,
        _source_format_lookup=_source_format_lookup,
        db_path=db_path,
        out_dir=out_dir,
    )
    _routes_import.register(app, ctx)
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


    # Flask's own `static` endpoint is the one route this module does not define,
    # so it is the one that cannot carry a @tier at its `def`. It is declared
    # here rather than skipped: /static/ is gated by the front door exactly like
    # everything else, and `if rule.endpoint == "static": continue` is the single
    # most common way a catch-all route rule grows a hole.
    _web_tiers.declare_endpoint_tier(app, "static", _web_tiers.LOGIN)

    # Every registered rule must now carry a tier -- checked here, at app
    # creation, not in CI. See assert_every_route_declares_a_tier().
    _web_tiers.assert_every_route_declares_a_tier(app)

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

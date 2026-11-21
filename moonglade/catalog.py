"""
moonglade/catalog.py
====================
The catalog: catalog.db's schema (CATALOG_FIELDS, the table, the upsert), `init_db`, the
migrations and the one migrate road (`migrate`, its lock and busy back-off), the connection
opener `catalog()`, the whole-table loads and saves (`load_catalog`, `save_catalog`,
`save_catalog_over_snapshot`), the row writes, the sort and LIKE helpers, single-row reads
(`get_row`, `get_row_by_task`) and hand-picked collections (`add_to_collection`,
`remove_from_collection`, under `_COLLECTIONS_LOCK`). Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4); the engine, the gallery's routes, the MCP
server and the CLI all read the catalog through this module.

The two names it reads from the gallery's old top level (the curation error and the
smart-collection check) are imported inside the function that uses them, never at the top,
so importing this module never imports the gallery.
"""
import csv
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from moonglade import catalog_search as _catalog_search
from moonglade import loom_files as _loom_files


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
            ids = _loom_seen["ids"] = _loom_files.loom_render_ids(_loom_root)
        return 1 if str(mid or "") in ids else 0
    con.create_function("mg_loom_render", 1, _is_loom_render)
    con.create_function("mg_lora_weight", 4, _catalog_search._lora_weight_match, deterministic=True)
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
    from moonglade.curation import CurationError, _is_smart_name
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

# Architecture

Moonglade Athenaeum is four Python modules around one SQLite catalog.

```
pixai_gallery_backup.py   CLI engine: download, organize, generate, sync, delete, reconcile
pixai_gallery.py          Flask web gallery + ALL SQLite catalog helpers (the shared base)
pixai_similar.py          "more like this" CLIP sidecar index (optional `pixeltable` dep)
moonglade_mcp.py          local stdio MCP server: curation tools over the same helpers
```

`pixai_gallery_backup.py` and `moonglade_mcp.py` both import `pixai_gallery.py` for
catalog access — so catalog logic lives in exactly one place. `pixai_similar.py` owns no
catalog SQL; it's a sidecar index the gallery imports lazily inside the `/api/similar`
handler, never at startup. The forward architecture is two surfaces — the CLI and the web
gallery.

## Module reference

### `pixai_gallery_backup.py`

| Function | Role |
|---|---|
| `gql()` | Replay persisted GraphQL GET; retry/backoff; surfaces errors clearly |
| `find_connection()` | Schema-agnostic: walks JSON for Relay connection (`edges`+`pageInfo`) |
| `media_ids_for()` | `mediaId` + `batchMediaIds` for a task node |
| `extract_meta()` | Pulls `id`, `createdAt`, `promptsPreview`, `status` |
| `resolve_media()` | Fetch media object, pick the `PUBLIC` full-res URL |
| `download()` | Stream to disk with resume + retries; optional convert |
| `convert_image()` | WebP→PNG/JPEG via Pillow; flattens alpha for JPEG |
| `embed_metadata()` | Write prompt/IDs/date into PNG text chunks or JPEG EXIF |
| `build_stem_name()` | Filesystem-safe names from prompt |
| `already_downloaded()` | Existing-file check via the shared `find_files_for_media_id` matcher (both naming layouts, not just `*_<mediaId>.*`). Used by `run_sync_artworks`'s video resume — `run_download` does NOT call it; it builds its own on-disk `media_id` index at startup instead |
| `cmd_organize()` | Re-normalize the WHOLE backup (`rglob`) into ONE scheme — `YYYY-MM/` month folders, descriptive names, no `batches/`. Reversible via `organize_manifest.csv` / `--undo-organize` |
| `_ensure_db()` | Auto-migrates catalog.csv → catalog.db if needed; used by all commands |
| `audit_collection()` | Filesystem-truth duplicate audit: Class A (same media_id in >1 folder) + Class B (byte-identical, different id via size-bucketed hashing) |
| `cmd_audit()` / `cmd_dedup()` | Read-only report / quarantine-or-delete redundant copies, keep most-organized, reconcile catalog |
| `reconcile_catalog_with_disk()` | Repoint each catalog row's filename/batch at the surviving on-disk file |
| `delete_task_gql()` | Replay the `deleteGenerationTask` persisted **mutation** (POST, not the GET listing path). VOID mutation: returns `null` on success, raises on error. Single-attempt — no retry, so a flaky network can't double-fire a delete |
| `run_delete_tasks()` | Guarded `--delete-task` driver: dry-run by default, `--apply` + typed `delete` confirm (or `--yes`), counts deleted/failed. Leaves local files + `catalog.db` untouched |
| `vlog()` / `set_verbose()` | `-v/--verbose` diagnostics: timestamped per-page / per-image / download timing to stdout. No-op until enabled |
| `gql_adhoc()` | Generic ad-hoc GraphQL **POST** (full query document, no persisted hash). Works for queries AND mutations under the API-key Bearer. The foundation for client ops beyond the reverse-engineered listing path; `media_file_gql` + `account_info` use it. Raises `PixAIError` on GraphQL/HTTP error |
| `account_info()` / `run_account_info()` | Read-only account dashboard (credits/membership/subscription) via `gql_adhoc`. **Never moves money** — no payment/subscription mutations are implemented, by design |
| `run_generate()` | `--generate`: create images via `createGenerationTask` (ad-hoc POST), poll, download, catalog as `source='api'`. Preview unless `--confirm`. `--task-id` recovers an already-created task for free |
| `build_video_parameters()` / `run_generate_video()` | `--generate-video`: image-to-video (`i2vPro`) — VERIFIED submit `{priority, i2vPro:{model,mediaId,[tailMediaId],mode,duration,generateAudio,audioLanguage,[cameraMovement]…}, isPrivate, enablePreview, hidePrompts, modelId}`. **No top-level `channel` field** — `--video-channel` maps to the boolean `isPrivate`, not a `channel` key. Enums banked (`--camera-movement`, `--video-channel`, duration 5/6/10/15). Preview unless `--confirm`; captures `paidCredit`; downloads mp4 into `videos/` |
| `build_reference_video_parameters()` / `run_reference_video()` | `--reference-video`: multi-image/video/audio reference — VERIFIED **top-level `referenceVideo`** block (NOT i2vPro): `{priority, referenceVideo:{model,prompt,duration(int),referenceImageMediaIds/…VideoMediaIds/…AudioMediaIds}, isPrivate, modelId}`. `--ref-image/--ref-video/--ref-audio` (media_id OR local file, auto-uploaded), cited in `--prompt` as `@image1/@video1/@audio1`. Preview unless `--confirm` |
| `_download_video_task()` | Shared video download+catalog (used by both i2v and reference-video): `video_outputs` → `media_file_gql.fileUrl` → `download` → catalog `is_video='1'` + poster thumbnail |
| `_maybe_dump_params()` | `--dump-params`: print a task's full submit `parameters` (esp. on `--task-id` recovery) — bank any shape (multiRef/referenceVideo/…) with NO browser capture |
| `upload_media()` | `--upload`: local file → `media_id` via the 3-step S3 handshake (`uploadMedia` presign → PUT bytes → `uploadMedia` register). Plain mutation over `gql_adhoc`; **free**. Unblocks inpaint / Edit / LoRA "bring your own image" |
| `build_chat_edit_parameters()` / `run_edit_image()` | `--edit-image`: instruct editing via `createGenerationTask` with a `chat` block (`prompts`+`mediaId`/`mediaIds`+`modelId`+`modelConfig`). `--edit-src` takes a catalog `media_id` OR a local file (auto-uploaded on `--confirm`); repeat for multi-image reference. Preview unless `--confirm` |
| `list_kaisuukens()` / `match_kaisuuken()` / `_apply_kaisuuken()` / `run_cards()` | Free-generation cards ("kaisuuken" / 回数券) live on the oRPC **`/v2` REST API**, not GraphQL. `list_kaisuukens` = `GET /v2/kaisuuken/summary` (one row per template w/ count + locked model); `match_kaisuuken` = `POST /v2/kaisuuken/check {type:"generation-task", parameters}` → matching ticket ids. **Cards auto-apply**: `_apply_kaisuuken` runs on `--confirm` for every create path, calls `check`, and attaches the nearest-expiry `kaisuukenId` → 0 credits (like the website). Preview shows FREE/paid up-front. `--no-card` opts out; `--kaisuuken-id` forces one. `--cards` = read-only display. All fail soft. REST base `REST_API_BASE` + helpers `_rest_get`/`_rest_post` |
| `price_task()` | `GET /v2/task-price`: compute a generation's credit cost WITHOUT creating it (mirrors GraphQL `pricingTask`). Scalars → query params, nested blocks (`i2vPro`/`referenceVideo`/`chat`/`loraParameters`/…) → URL-encoded JSON. Returns `actualPrice` (int) or None. **READ-ONLY, spends nothing** — used in previews to show the real cost + card savings |
| `suggest_prompt()` / `run_suggest_prompt()` | `--suggest-prompt <media_id\|file>`: image-to-prompt via `GET /v2/tag/suggest-prompt/{mediaId}` → `{output:[…]}` (a Danbooru-style tag list + natural-language description variants). Local files upload first (free). **FREE / read-only**, no `--confirm` |
| `list_claims()` / `claim_reward()` / `run_claims()` | `--claims`: list claimable rewards (daily credits, agent stamina) via `GET /v2/claim` — **read-only**. `--claim <id\|all>`: claim ready rewards via `POST /v2/claim/{id}` — **gated behind `--confirm`**, previews otherwise, and never fires on a not-yet-claimable reward. Grants free credits/stamina to the owner's own account (no money moves) |

### `pixai_gallery.py`

| Symbol | Role |
|---|---|
| `CATALOG_FIELDS` | Single source of truth for all column names |
| `_IMAGE_EXTS` | Single source of truth for image extensions — import this, never redefine |
| `_MIGRATIONS` | List of ALTER TABLE statements run on every `_connect()` call — add new columns here |
| `init_db()` | Creates table + runs migrations; called at gallery startup and by `save_catalog` |
| `save_catalog()` | Upsert list of dicts; calls `init_db` first |
| `query_catalog()` | SQL-backed filter/sort/paginate for gallery index |
| `list_media_ids()` | Returns ordered media IDs for prev/next navigation |
| `backfill_batches()` | Scans `batches/` on disk and fills empty `batch` column; called on gallery startup |
| `media_id_of()` | Canonical media_id from a path (last `_`-chunk of stem). Invariant 1 — but NOT actually a single source: `backfill_batches()` (above, this same module) and `pixai_similar.py`'s `scan_dir` both re-implement the identical `stem.split("_")[-1]` inline instead of calling it |
| `find_files_for_media_id()` | All on-disk files for a media_id, BOTH layouts (prefixed `*_<mid>.*` AND bare `<mid>.*`), exact-id checked, gallery excluded. Used by the gallery's `find_image_file` — **not** by resume or the audit, which each still walk the tree independently (see Invariant 7) |
| `create_app()` | Flask app factory; calls `init_db` + `backfill_batches` before serving |

## CLI flags

`python pixai_gallery_backup.py --help` is the authoritative per-flag text (every flag has
help text; keep it that way when adding one). This map exists because the tuning knobs are
easy to miss next to the headline commands — the user-facing walkthroughs live in `wiki/`
(Backing-Up, Generating).

| Group | Flags | Notes |
|---|---|---|
| Edit tuning (`--edit-image`) | `--edit-model` `--edit-resolution` `--edit-aspect` `--edit-quality` | all four pass through `clamp_edit_config()`, which corrects them to what the chosen model really supports (e.g. Reference Pro: 2K/4K only, no quality knob) |
| Video tuning (`--generate-video`) | `--tail` `--camera-movement` `--audio-language` `--video-prompt-helper` `--video-channel` | `--tail` = FLF last frame; `--video-channel private` = the site's "Enhanced" channel and lands as `isPrivate` (dest is `args.vchannel`, not `video_channel`); video's prompt helper is OFF by default — the opposite of image gen |
| All create paths | `--params-json` `--poll-timeout` `--kaisuuken-id` `--no-card` | `--params-json` returns early from the param builders — it overrides every other generation flag; `--poll-timeout` is seconds (default 300) |
| Download shaping | `--delay` `--count-page-size` `--collect-only` `--name-length` `--name-sep` | `--delay` is a seconds float throttling most API loops, not just downloads; `--collect-only` forces the serial path; `--count-page-size` errors server-side above ~10k |
| Format conversion | `--convert` `--convert-existing` `--jpeg-quality` `--jpeg-bg` `--keep-webp` | need Pillow; `--convert-existing` is a standalone no-token pass and defaults to png; the `.webp` is replaced unless `--keep-webp` |
| Metadata backfill | `--backfill-meta` `--backfill-full-meta` `--with-loras` `--with-credit` | `--backfill-meta` fills url/width/height only; `--with-loras` widens `--backfill-full-meta` to rows missing LoRA data, `--with-credit` to rows missing their recorded credit cost (`paid_credit`) — each a long run |
| Catalog repair | `--fix-model-names` `--relabel-removed` `--faststart-videos` `--restore-orphans` | `--relabel-removed` only acts with `--fix-model-names`; `--restore-orphans` is the one thing that makes `--verify-dupes` write; `--faststart-videos` needs ffmpeg on PATH and is idempotent |
| Watch / niche | `--watch-seconds` `--all-contests` | modifiers for `--watch` (seconds; 0 = until Ctrl-C) and `--contests` (include ended) |

Pure modifiers do nothing alone — each acts only alongside its partner command named above.

## The one-shot sync (`--sync`)

One command runs the whole refresh chain; every step is idempotent (re-running on a
clean catalog costs almost nothing):

1. incremental pull WITH metadata (sets `--update --full-meta`, calls `run_download`)
2. re-resolve blank/numeric model names (`run_fix_models`)
3. fill any rows still missing prompt/seed/model (`run_backfill_full_meta`)
4. rebuild any missing gallery thumbnails (`build_thumbnails`, skips thumbs already on disk)
5. flag rows deleted on the website (`run_reconcile_deleted`)

> **Reconcile (step 5) is advisory and caught with a deliberately BROAD `except Exception`
> — do not narrow it back to `except PixAIError`.** It runs its own live-feed scan through
> `gql()`, which re-raises bare `requests` network/HTTP errors that are *not* `PixAIError`;
> a narrow catch would let a transient network blip crash the entire sync **after** the
> backup already succeeded. Guarded by `tests/test_sync.py` (chain order, flag-setting, and
> survival of both `PixAIError` and non-`PixAIError` reconcile failures).

## How it talks to PixAI

- **Auth** — your official API key (`PIXAI_API_KEY`) is the Bearer credential for
  every call. Your `USER_ID` is auto-resolved from it; HTTPS verification is always
  on. Setup is just the key — see [Setup](../../../wiki/Setup).
- **Personal-history operations** — PixAI has no official public API for managing
  *your own* work (listing your history, task detail, delete), so those reuse the
  website's own interfaces, with working defaults shipped in the app. You never
  capture anything by hand; if a default ever goes stale after a PixAI update you
  get a clear error and update one value — see [Troubleshooting](../../../wiki/Troubleshooting).
- **Media URLs** — task records carry `mediaId` / `batchMediaIds`, not URLs. The
  full-res URL comes from `GET /v1/media/<id>` (variant `PUBLIC`); videos expose
  their mp4 via the media object's `fileUrl`.

## The catalog (`catalog.db`)

SQLite, one row per media, keyed by `media_id`. All I/O goes through helpers in
`pixai_gallery.py` — never raw SQL elsewhere. Schema migrations go in **three
places**: the `CATALOG_FIELDS` list, the `_CREATE_TABLE` DDL, and the
`_MIGRATIONS` list (run on every connect, so existing DBs auto-upgrade).
`_IMAGE_EXTS` is the single source of truth for recognized image extensions —
defined once here, imported by `pixai_gallery_backup.py`, never redefined locally.

Notable columns: identity/timing (`media_id`, `task_id`, `filename`, `created_at`),
full meta (`prompt_full`, `seed`, `steps`, `sampler`, `cfg_scale`, `model_id/name`,
`loras`, `negative_prompt`, `clip_skip`), published-artwork data (`title`,
`is_published`, `liked_count`, `art_tags`, …), video (`is_video`,
`poster_media_id`, `video_duration`), provenance (`source` = online/api/local),
`deleted_remote` (flagged by reconcile), and `paid_credit` — the task's
server-reported actual credit cost, captured at poll/collect/full-meta time and
recoverable for older rows via `--backfill-full-meta --with-credit`. It is
task-level (repeated on each of the task's media rows, so spend totals count once
per `task_id`); `'0'` is a real value (free card / daily-free gen), `''` means
never captured.

## On-disk layout

```
pixai_backup/
├─ images/                flat downloads (pre-organize)
├─ 2024-03/                organize: month folders, descriptive names
│   └─ <prompt>_<taskid>_<mediaid>.<ext>
├─ unknown-date/           organize: fallback month folder for rows with no created_at
├─ videos/                 backed-up + imported videos (mp4)
├─ imported/               external media copied in via --import-local
├─ gallery/thumbs/         768px JPEG thumbnails, one per media_id (short-lived cache)
├─ branding/               machine-local marks, frames, badges, reward art
├─ branding.json           chosen mark + animation (POST /api/branding; separate from
│                          the branding/ art dir above)
├─ loom/                   The Loom's project store + exports
│   ├─ exports/             finished storyboard renders (ffmpeg trim+concat -> loom_cut.mp4)
│   ├─ kv/                  per-account key/value store: kv/<account>/<key>.json, with
│   │                      legacy flat kv/<key>.json files kept as a read-only fallback
│   ├─ _frames/             extracted last-frame PNGs (shot-to-shot chaining)
│   ├─ _uploads/            staged data-URL uploads before submit
│   └─ store.json           legacy pre-split store, migrated into kv/ on first touch
├─ prompt_snippets/        per-account saved prompt snippets (<account>.json)
├─ prompt_snippets.json    legacy install-wide snippets (read-only fallback)
├─ view_presets/           per-account saved gallery views (<account>.json)
├─ view_presets.json       legacy install-wide saved views (read-only fallback)
├─ toolbox_presets/        per-account imported Toolbox presets (<account>.json)
├─ toolbox_presets.json    legacy install-wide presets (read-only fallback)
├─ schedule.json           Control Panel's scheduled-task list
├─ _duplicates/            quarantine from --dedup (reversible)
├─ _deleted/               quarantine from gallery delete (recoverable)
├─ organize_manifest.csv   reversible move log (--undo-organize)
├─ catalog.db              the source of truth
├─ catalog.csv             legacy catalog format (auto-migrated in) / --export-csv output
├─ raw_tasks.jsonl         raw task data (for re-processing)
├─ achievements.json       earned achievements + earn dates
├─ telemetry.json          counters the achievement system reads
└─ jobs.jsonl              append-only activity/job log
```

Thumbnails are keyed by `media_id`, **not** content-addressed — the filename is an
identity, not a digest of the bytes. Because `--rebuild-thumbs` regenerates them IN PLACE
at that same key, they're served `public, max-age=300` (short, not immutable) so a repair
doesn't get pinned behind a year-long cache; the route's ETag still gives a 304 on the
common repeat-visit path.

**Organize** normalizes everything into `YYYY-MM/` month folders with readable
`<prompt>_<taskid>_<mediaid>` names (no batch subfolders), writing a reversible
manifest. It's idempotent, byte-safe, and dry-runnable. See the
[Backing Up](../../../wiki/Backing-Up) wiki page for usage.

## Invariants (do not break)

1. **`media_id` is always the last `_`-chunk of the filename stem.** Resume,
   organize, and lookup all parse `stem.split("_")[-1]`.
2. **Resume is keyed on media id.** True in the base case: `run_download`'s O(1)
   on-disk index is checked before any network call. **Not true under `--full-meta` /
   `--sync`**, though (`--sync` runs `--update --full-meta` under the hood): for every
   task on the page, `task_detail_gql` + `model_name_gql` + LoRA resolution all fire
   BEFORE the per-media resume check, in both the parallel and serial code paths — so
   re-running `--full-meta` over an already-complete backup still pays the full
   metadata network cost per task, not just per missing media.
3. **Incomplete files don't count as done** — `.part` temp files and zero-byte
   files are treated as not-downloaded; downloads are atomic (`*.part` → replace).
4. **`catalog.db` is the source of truth for `--organize`, resume, and gallery
   lookups.** **Not** for `--audit`/`--dedup`: `audit_collection()` (see its
   module-table entry above) is a deliberately filesystem-truth pass — it walks the
   actual on-disk bytes to find duplicates the catalog wouldn't know about, and
   keeper selection never consults `catalog.db`. That's why the (fixed) zero-byte-
   keeper defect needed its own filesystem-side size guard: catalog correctness
   alone couldn't have caught it.
5. **`--organize` re-normalizes the WHOLE backup via `rglob`** into one collapsed
   scheme — `out/YYYY-MM/<prompt_taskid_mediaid>` month folders. It stays idempotent
   (files already at target = "already in place"), byte-safe (identical dupes
   dropped, differing kept side-by-side), and reversible (`organize_manifest.csv` +
   `--undo-organize`). Skips `gallery/`, `_duplicates/`, `videos/`, `imported/`;
   leaves `source='local'` + videos untouched.
6. **`find_image_file` excludes `out_dir/gallery/`** to prevent thumbnails from
   being returned as full-res images.
7. **`find_files_for_media_id` recognizes both naming layouts** — prefixed
   `*_<mid>.*` and bare `<mid>.*` — but it is **not a single shared matcher**; that
   framing is aspirational, not current fact. Only the gallery's `find_image_file`
   calls it. Resume (`run_download`), the audit (`audit_collection`), `cmd_organize`,
   `run_import_local`, `duplicate_groups`, and `/api/loom/handoff`'s frame-extraction
   fallback (`loom_handoff`) each walk the tree independently instead, and each one's exclusion set
   (which quarantine/thumbnail directories it skips) is its own, not shared.
   Consolidating onto one real shared matcher is still open work, not yet done.

## The web suite

The Flask gallery (`pixai_gallery.py`) is a full creation suite, not just a browser.
Spend-capable routes are **LOGIN**-tier, not localhost: `/api/generate`, `/api/edit`,
`/api/enhance`, `/api/fix` and `/api/loom/generate` are reachable by any signed-in session,
because generating from the tablet is the point. **LOCALHOST** (`_is_local_request`) is
reserved for a different category — writes to the server's own filesystem, credential writes,
and irreversible cloud deletion. `tests/test_route_tiers.py` declares every route's tier and
asserts it against a live request, so it is the authority when prose and code disagree.

- **Generate drawer** (header ✦, dockable, persisted position): three tabs — *Generate*
  (base model + LoRA chips with weights, model/LoRA flyout with a hover preview card, live
  cost + free-card check), *Edit* (sub-tabs Edit | Enhance | Fix over a shared source —
  instruct-edit, the enhance-workflow catalog, hand/face fixer), *Video* (I2V / FLF / R2V
  modes, gallery Picker slots with @image badges, contenteditable prompt with @image chips,
  model picker, audio toggle, live cost + card count).
- **Picker** (`/api/gallery-images` + `/api/upload`): whole-catalog infinite scroll,
  search, Collection/Source/Rating/Sort filters, upload → media_id.
- **Tag Suggestions** (`/api/tag-suggest` → GraphQL `tags(q:...)`): Danbooru-style
  autocomplete in prompt boxes.
- **Gallery bridges**: lightbox Edit/To-Video buttons, right-click context menu, bulk-bar
  Send-to-Video.
- **The Loom** (`/loom`): the storyboard surface — current shape lives in `docs/STATE.md`;
  usage manual is `docs/LOOM.md`.
- **Async engine**: submit (`/api/generate|edit|enhance|fix|loom/generate`) → poll
  (`/api/task-status`) → auto-download + catalog (`source='api'`). Free cards auto-apply
  on every create path.
- **Live events** (`--watch`): a graphql-transport-ws subscription to
  `wss://gw.pixai.art/graphql` (root field `personalEvents`) drives `--watch-backup` and
  the gallery server's always-on **live-mirror** watcher, so gens land the instant they
  finish instead of waiting on the next `--update`.
- **Control Panel**: whitelisted CLI subprocesses with a live log + real progress bar
  (`~=MGPROG=~done|total|new` lines under `MOONGLADE_PROGRESS=1`), a cancel action, and an
  hour-granular scheduler (`destructive` actions excluded). Server Stop/Restart is
  Homebridge-style (`/api/server/stop|restart`; restart = exit 42, relaunched by the
  supervisor). CSV export (`/export-csv`) is a plain in-memory browser download, not a
  Panel subprocess.
- **Branding**: machine-local marks in `out_dir/branding/marks/`, `/api/branding` GET
  (open)/POST (LOGIN-tier, like the rest of the writes above — not localhost), animated
  banner marks. `/api/branding/shortcut` (the Desktop `.lnk` writer, LOCALHOST-only because
  it shells out to the host machine) is the actual localhost-gated route in this group.

## Shared web components (`static/`)

Five framework-neutral custom elements (the "Option-A cohesion migration") live in
`static/` as plain `mg-*.js` globals — no build step, no shadow DOM, loaded via a plain
`<script src>` tag, each self-injecting its own `<style>` that reads the shared
`DESIGN_TOKENS_CSS` custom properties so it re-skins with the rest of the app. Both the
vanilla gallery (`pixai_gallery.py`) and the React Loom (`loom/master-storyboard.jsx`)
mount the same files instead of each hand-duplicating the UI:

| File | Element / global | Role |
|---|---|---|
| `mg-model-picker.js` | `<mg-model-picker>` | Model/LoRA picker: search box + cover cards + hover preview card |
| `mg-gallery-picker.js` | `<mg-gallery-picker>` | Whole-catalog image picker modal (search, Collection/Source/Rating/Sort filters, infinite scroll); wraps `picker-core.js` |
| `mg-generate-drawer.js` | `<mg-generate-drawer>` | The full Generate/Edit/Video form (Multi-ref slots, cost line, submit+poll) |
| `mg-cost-badge.js` | `<mg-cost-badge>` | The one renderer for "this costs N credits" / "a free card covers it" |
| `mg-notify.js` | `Ach` / `Toast` / `Jobs` / `JobsCard` (plain globals, not a custom element) | Achievement-toast celebrations, the corner Toast utility, and the Job activity tracker |

`static/picker-core.js` is a sixth file worth knowing about but is not one of the five: it's
the framework-agnostic browse/filter/paginate/infinite-scroll logic that `mg-gallery-picker`
wraps (and that the Loom's own `GalleryPick` also shares) — no DOM, no custom element, just
the shared engine underneath.

## Testing

`python -m pytest -q` from the repo root — pure functions, filesystem, catalog, gallery
routes, mocked network. `tests/test_similar.py` needs the optional `pixeltable` dep and
skips itself cleanly without it (`--ignore=tests/test_similar.py` to exclude it explicitly).
The Loom's pure-logic modules have their own suite: `node --test` from `loom/`.
All must pass before merging.

The count is deliberately not written here — it was stated across six-plus docs and was wrong
in every one. `tests/test_docs_dont_hardcode_counts.py` enforces that. Ask `pytest`.

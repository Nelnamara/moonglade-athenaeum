# CLAUDE.md — Project Context for Claude Code

This file is committed so it is available on every machine that clones the repo.

---

## What this project is

**Moonglade Athenaeum** — *"a library against the Void."* A Python CLI (`pixai_gallery_backup.py`) with a PySide6 GUI (`pixai_gui.py`) and local Flask gallery (`pixai_gallery.py`). It began as a backup tool for the **owner's own** PixAI.art generations and grew into a full local PixAI **client**: back up · browse · generate · curate. Talks to the same API the browser uses, pages the entire history at full resolution, keeps a searchable SQLite catalog, **creates** new images via the API, and manages both the local archive and the cloud account.

Built by reverse-engineering site network traffic (catalogued privately in `private/API_OPERATIONS.md`, git-ignored). The `gql_adhoc()` ad-hoc POST path means most operations need no persisted-hash capture. There is no official API for listing your own generations. Be polite to their servers (paced requests). PixAI's terms grant users copyright of their generations. User-facing docs live in `docs/`.

---

## Working across machines (home ⇄ work) — READ THIS FIRST

This repo is edited from more than one machine. Cross-machine breakage here is almost
always **config drift, not real changes** — do not blame the user, do not "fix" it with a
mass commit. Follow this protocol:

1. **Line endings are pinned by `.gitattributes`** (LF in the repo). Do NOT change
   `core.autocrlf`, do NOT run line-ending "fixes", do NOT commit a mass line-ending diff.
   If `git status` shows *every* file modified, STOP — that's line-ending drift. Re-check
   `.gitattributes` is present and run `git add --renormalize .`; never `git checkout -- .`
   away someone's real work to make it "clean."
2. **Default working branch is `video-gen`** (until merged to master). `git checkout video-gen`
   before doing anything. Do not start committing on `master`.
3. **Pull before you start, push when you stop:** `git pull --rebase --no-edit` at session
   start, `git push` at session end. This is what prevents "updates were rejected" /
   divergence. If push is rejected, it's the remote moving — pull --rebase, then push.
4. **Never `git add -A` / `git add .`** — stray untracked files live here (`config.json`,
   `.coverage`, `design_refs/`, old `pixai_*.py` side scripts). Stage **explicit paths** only.
5. **`config.json` + `private/` are git-ignored and machine-local** — they will NOT be on the
   other machine, and that's correct. Don't recreate, commit, or complain about their absence.
6. **Commits: no `Co-Authored-By: Claude` trailer** (standing preference).

## Architecture / request flow

1. **Listing query is an Apollo persisted query (GET).** The site sends `operationName` + a `sha256Hash`; the query body lives on PixAI's server. Constants (`OPERATION_NAME`, `PERSISTED_QUERY_HASH`, `U3T`, `USER_ID`) are captured from the browser and stored in git-ignored `config.json`.

2. **It's a GET** with `operation`, `u3t`, `operationName`, `variables`, and `extensions` (carrying the persisted hash) as URL query params. See `gql()`.

3. **Apollo CSRF headers required** on that GET: `apollo-require-preflight: true` and `x-apollo-operation-name`. Set on the session in `main()`.

4. **Pagination is BACKWARD.** Variables are `{last, before, userId}`. Start with no `before` (newest page), follow `pageInfo.startCursor` → `before` while `hasPreviousPage` is true.

5. **Task summaries contain `mediaId` + `batchMediaIds`, NOT image URLs.** To get a URL, fetch `https://api.pixai.art/v1/media/<mediaId>`. Its `urls` list has variants; full-resolution is `variant: "PUBLIC"`. See `resolve_media()`.

6. **Auth** is a Bearer token (JWT) from the logged-in browser. Via `PIXAI_TOKEN` env, `token.txt`, or `--token`. HTTPS verification always on.

7. **SSL trust store**: `truststore.inject_into_ssl()` called at import if present — fixes corporate/antivirus HTTPS interception.

---

## Three-file architecture

| File | Role |
|---|---|
| `pixai_gallery_backup.py` | CLI downloader: download, organize, backfill, catalog stats |
| `pixai_gallery.py` | Flask gallery server + ALL SQLite catalog helpers; imported by both other files |
| `pixai_gui.py` | PySide6 GUI wrapping CLI commands in background Worker threads |

### Key functions in `pixai_gallery_backup.py`

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
| `already_downloaded()` | Resume check: rglob the whole tree for `*_<mediaId>.*` |
| `cmd_organize()` | Re-normalize the WHOLE backup (`rglob`) into ONE scheme — `YYYY-MM/` month folders, descriptive names, no `batches/` (collapsed 2026-06-27, `9e3f4a1`). Reversible via `organize_manifest.csv` / `--undo-organize` |
| `_ensure_db()` | Auto-migrates catalog.csv → catalog.db if needed; used by all commands |
| `audit_collection()` | Filesystem-truth duplicate audit: Class A (same media_id in >1 folder) + Class B (byte-identical, different id via size-bucketed hashing) |
| `cmd_audit()` / `cmd_dedup()` | Read-only report / quarantine-or-delete redundant copies, keep most-organized, reconcile catalog |
| `reconcile_catalog_with_disk()` | Repoint each catalog row's filename/batch at the surviving on-disk file |
| `delete_task_gql()` | Replay the `deleteGenerationTask` persisted **mutation** (POST, not the GET listing path). VOID mutation: returns `null` on success, raises on error. Single-attempt — no retry, so a flaky network can't double-fire a delete |
| `run_delete_tasks()` | Guarded `--delete-task` driver: dry-run by default, `--apply` + typed `delete` confirm (or `--yes`), counts deleted/failed. Leaves local files + `catalog.db` untouched |
| `vlog()` / `set_verbose()` | `-v/--verbose` diagnostics: timestamped per-page / per-image / download timing to stdout (the GUI log pane captures it). No-op until enabled |
| `gql_adhoc()` | Generic ad-hoc GraphQL **POST** (full query document, no persisted hash). Works for queries AND mutations under the API-key Bearer. The foundation for client ops beyond the reverse-engineered listing path; `media_file_gql` + `account_info` use it. Raises `PixAIError` on GraphQL/HTTP error |
| `account_info()` / `run_account_info()` | Read-only account dashboard (credits/membership/subscription) via `gql_adhoc`. **Never moves money** — no payment/subscription mutations are implemented, by design |
| `run_generate()` | `--generate`: create images via `createGenerationTask` (ad-hoc POST), poll, download, catalog as `source='api'`. Preview unless `--confirm`. `--task-id` recovers an already-created task for free |
| `build_video_parameters()` / `run_generate_video()` | `--generate-video`: image-to-video (`i2vPro`) — VERIFIED submit `{channel, i2vPro:{model,mediaId,[tailMediaId],mode,duration,generateAudio,audioLanguage,[cameraMovement]…}}`. Enums banked (`--camera-movement`, `--video-channel`, duration 5/6/10/15). Preview unless `--confirm`; captures `paidCredit`; downloads mp4 into `videos/` |
| `build_reference_video_parameters()` / `run_reference_video()` | `--reference-video`: multi-image/video/audio reference — VERIFIED **top-level `referenceVideo`** block (NOT i2vPro): `{priority, referenceVideo:{model,prompt,duration(int),referenceImageMediaIds/…VideoMediaIds/…AudioMediaIds}, isPrivate, modelId}`. `--ref-image/--ref-video/--ref-audio` (media_id OR local file, auto-uploaded), cited in `--prompt` as `@image1/@video1/@audio1`. Preview unless `--confirm` |
| `_download_video_task()` | Shared video download+catalog (used by both i2v and reference-video): `video_outputs` → `media_file_gql.fileUrl` → `download` → catalog `is_video='1'` + poster thumbnail |
| `_maybe_dump_params()` | `--dump-params`: print a task's full submit `parameters` (esp. on `--task-id` recovery) — bank any shape (multiRef/referenceVideo/…) with NO browser capture |
| `upload_media()` | `--upload`: local file → `media_id` via the 3-step S3 handshake (`uploadMedia` presign → PUT bytes → `uploadMedia` register). Plain mutation over `gql_adhoc`; **free**. Unblocks inpaint / Edit / LoRA "bring your own image" |
| `build_chat_edit_parameters()` / `run_edit_image()` | `--edit-image`: instruct editing via `createGenerationTask` with a `chat` block (`prompts`+`mediaId`/`mediaIds`+`modelId`+`modelConfig`). `--edit-src` takes a catalog `media_id` OR a local file (auto-uploaded on `--confirm`); repeat for multi-image reference. Preview unless `--confirm` |
| `list_kaisuukens()` / `match_kaisuuken()` / `_apply_kaisuuken()` / `run_cards()` | Free-generation cards ("kaisuuken" / 回数券) live on the oRPC **`/v2` REST API**, not GraphQL (verified 2026-07-03 from the app's own contract). `list_kaisuukens` = `GET /v2/kaisuuken/summary` (one row per template w/ count + locked model); `match_kaisuuken` = `POST /v2/kaisuuken/check {type:"generation-task", parameters}` → matching ticket ids. **Cards auto-apply now**: `_apply_kaisuuken` runs on `--confirm` for every create path, calls `check`, and attaches the nearest-expiry `kaisuukenId` → 0 credits (like the website). Preview shows FREE/paid up-front. `--no-card` opts out; `--kaisuuken-id` forces one. `--cards` = read-only display. All fail soft. REST base `REST_API_BASE` + helpers `_rest_get`/`_rest_post` |
| `price_task()` | `GET /v2/task-price`: compute a generation's credit cost WITHOUT creating it (mirrors GraphQL `pricingTask`). Scalars → query params, nested blocks (`i2vPro`/`referenceVideo`/`chat`/`loraParameters`/…) → URL-encoded JSON. Returns `actualPrice` (int) or None. **READ-ONLY, spends nothing** — used in previews to show the real cost + card savings. Verified exact: i2v/ref-video 27,500, edit 8,000 |
| `suggest_prompt()` / `run_suggest_prompt()` | `--suggest-prompt <media_id\|file>`: image-to-prompt via `GET /v2/tag/suggest-prompt/{mediaId}` → `{output:[…]}` (a Danbooru-style tag list + natural-language description variants). Local files upload first (free). **FREE / read-only**, no `--confirm` |
| `list_claims()` / `claim_reward()` / `run_claims()` | `--claims`: list claimable rewards (daily credits, agent stamina) via `GET /v2/claim` — **read-only**. `--claim <id\|all>`: claim ready rewards via `POST /v2/claim/{id}` — **gated behind `--confirm`**, previews otherwise, and never fires on a not-yet-claimable reward. Grants free credits/stamina to the owner's own account (no money moves) |

### Key helpers in `pixai_gallery.py`

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
| `media_id_of()` | Canonical media_id from a path (last `_`-chunk of stem). INVARIANT 1, single source |
| `find_files_for_media_id()` | SHARED matcher: all on-disk files for a media_id, BOTH layouts (prefixed `*_<mid>.*` AND bare `<mid>.*`), exact-id checked, gallery excluded. Resume, gallery, and audit all use it so they never drift apart |
| `create_app()` | Flask app factory; calls `init_db` + `backfill_batches` before serving |

---

## Catalog / SQLite

- **File:** `catalog.db` (SQLite), stored in `out_dir/`. Auto-migrated from `catalog.csv` on first run.
- **All catalog I/O** goes through helpers in `pixai_gallery.py` — never raw SQL elsewhere.
- **Schema migrations:** new columns go in THREE places: `CATALOG_FIELDS` list, `_CREATE_TABLE` DDL, and `_MIGRATIONS` list. The `_MIGRATIONS` list runs on every `_connect()` so existing DBs get the column automatically.
- **`_IMAGE_EXTS`:** defined once in `pixai_gallery.py`, imported by `pixai_gallery_backup.py`. Never redefine locally.

---

## GUI module cache

`pixai_gui.py` imports `pixai_gallery` at module level. Changes to `pixai_gallery.py` require a **full GUI restart** (close and reopen the app) — stopping and restarting just the gallery server thread is not enough to reload the Python module.

---

## INVARIANTS — do not break

1. **`media_id` is always the last `_`-delimited chunk of the filename stem.** Resume, `--organize`, and catalog lookup all parse it as `stem.split("_")[-1]`. Never append anything after the media id.

2. **Resume is keyed on media id, checked BEFORE any network call.** `already_downloaded(out, mid)` runs before `resolve_media()`/`download()`. Keep that order.

3. **Incomplete files must not count as done.** `.part` temp files and zero-byte files are treated as not-downloaded. Downloads write to `*.part` then atomically `replace()` the final name.

4. **`catalog.db` is the source of truth** for `--organize` and related commands. Don't make those modes depend on re-querying the API.

5. **`--organize` re-normalizes the WHOLE backup via `rglob`** into one collapsed scheme — `out/YYYY-MM/<prompt_taskid_mediaid>` month folders (since `9e3f4a1`, 2026-06-27; the old `images/`-only non-recursive glob and `batches/` mode are gone — do NOT reintroduce them). It stays idempotent (files already at target = "already in place"), byte-safe (identical dupes dropped, differing kept side-by-side), and reversible (`organize_manifest.csv` + `--undo-organize`). Skips `gallery/`, `_duplicates/`, `videos/`, `imported/`; leaves `source='local'` + videos untouched.

6. **`find_image_file` excludes `out_dir/gallery/`** to prevent thumbnails from being returned as full-res images.

7. **Media-id → file resolution goes through `find_files_for_media_id` ONLY.** It matches BOTH naming layouts — prefixed `*_<mid>.*` (flat/batch) and bare `<mid>.*` (single-image month files). Resume (`already_downloaded`), the gallery (`find_image_file`), and the audit all share it. Never reintroduce a `*_<mid>.*`-only glob: that mismatch (bare month files invisible to resume) is exactly what caused the historical images/+month duplication — re-downloads recreated flat copies that organize then orphaned.

---

## Critical constraints

- **NEVER** append `Co-Authored-By: Claude` trailers to commits.
- **NEVER** commit `config.json` — git-ignored; contains real user credentials (USER_ID, U3T, hashes).
- `token.txt`, `pixai_backup/`, `*.webp` are also git-ignored.
- No real credentials or user-specific values should appear in any committed file.
- All traffic is HTTPS with verification on; do not add `verify=False` anywhere.
- **Server page-size cap:** `last` above ~8,000–10,000 triggers a Prisma `Internal server error`. Keep download `--page-size` ≤ ~8,000.

---

## Security & GitHub hygiene

- `config.json` is git-ignored and will never be committed.
- `config.example.json` (committed) shows the required structure with placeholder values only.
- The output folder (`pixai_backup/`) contains images, prompts, and catalog — git-ignored.
- The repo is public on GitHub at `Nelnamara/pixai-gallery-backup`.

---

## Deleting tasks from your account (`--delete-task`)

- `deleteGenerationTask` is a persisted **mutation** sent by POST (Apollo blocks mutations over GET), unlike the GET listing/query path. It is a **void mutation: it returns `null` on success** — the meaningful signal is the ABSENCE of a GraphQL error, NOT the payload. (Verified against a real task via the site, which shows a "Task has been deleted" toast off that same null/no-error response. `getTaskById` is NOT a valid post-delete existence check — it still resolves deleted tasks.)
- Hash lives in `config.json` as `DELETE_TASK_HASH` with **no built-in default** — capturing it is a deliberate manual step so deletion can't fire without explicit setup.
- Guards: dry-run by default; `--apply` to perform; typed `delete` confirmation unless `--yes` (refused on non-interactive stdin). Single-attempt per task.
- Deletes ONLY the cloud generation; local image files + `catalog.db` are left intact.

> **Reverse-engineering detail (frontend handler flow, sibling mutations, hash-capture
> method) lives in `private/RE_NOTES.md`** — git-ignored, not public. Read it there when
> you need it.

## Verbose logging (`-v` / `--verbose`)

- `set_verbose()` + `vlog()`: timestamped diagnostics (per-page fetch, per-image resolve/download timing, startup disk-scan time) to stdout. No-op until enabled. GUI exposes it as a "Verbose logging" checkbox in the top bar (persisted in settings). NOT a full logging framework — file logging is a separate, still-open discussion.

## Recapture procedure (when PixAI changes their frontend)

Symptoms: `PersistedQueryNotFound`, "Cannot query field…", or sudden 400s. Step-by-step
recapture is in `private/RE_NOTES.md`.

---

## Creating: generate · video · reference-video · edit · upload · cards

All creation rides the SAME `createGenerationTask` mutation over `gql_adhoc` (no persisted hash),
differing only in the `parameters` object. **Every credit-spending path is preview-only until
`--confirm`**, `--task-id` recovers an already-created task for free, and `--dump-params` prints a
recovered task's full submit shape (bank any param shape with no browser capture).

- `--generate` → image (`parameters` = the image params).
- `--generate-video --image <media_id>` → i2vPro video (`{channel, i2vPro:{…, [tailMediaId], [cameraMovement]}}`);
  first/last-frame via `--tail`, enums via `--camera-movement`/`--video-channel`, duration 5/6/10/15.
- `--reference-video --ref-image/--ref-video/--ref-audio` → multi-reference video (top-level `referenceVideo`
  block, distinct from i2vPro); cite refs in `--prompt` as `@image1/@video1/@audio1`; local files auto-upload.
- `--edit-image --edit-src <media_id|file> --prompt "…"` → instruct edit (`{chat:{…}}`); local files
  auto-upload via `uploadMedia`; repeat `--edit-src` for multi-image reference.
- `--upload <file>` → prints a `media_id` (free; the 3-step S3 handshake).
- `--cards` → read-only free-card (kaisuuken) list (via `GET /v2/kaisuuken/summary`). Cards **auto-apply**:
  on `--confirm` the tool calls `/v2/kaisuuken/check`, attaches the matching card, and the gen is 0 credits.
  `--no-card` to pay credits anyway; `--kaisuuken-id <id>` to force a specific card.

Deeper RE detail (submit shapes, the full app op catalog, kaisuuken/upload/edit captures, pricing) is
in git-ignored `private/GENERATOR_SURFACE.md` + `private/APP_OPERATIONS_FULL.md`.

## The web suite (v1.9.0): the Generate drawer + The Loom

The Flask gallery is a full creation suite. Everything below is **localhost-gated**
(`_is_local_request`) -- LAN browsers can look, only the owner's machine can spend.

- **Generate drawer** (header ✦, dockable Left/Top/Bottom/Right, persisted): three tabs.
  - *Generate*: base model + attachable **LoRA chips with weights** (separate state; rides
    `loras:[{version_id,weight}]` -> `loraParameters`), model/LoRA browser in a **flyout**
    with a **hover preview card** (cover/likes/author/tags), live cost + free-card check.
  - *Edit* (600px wide): sub-tabs **Edit | Enhance | Fix** over a shared source; instruct-edit,
    the 80-workflow enhance catalog, hand/face fixer boxes.
  - *Video* (600px wide): I2V / FLF (first+last) / R2V modes, **gallery Picker slots** with
    @image badges + hover previews + remove, contenteditable prompt with **@image chips**,
    model picker (v4.0.1/v4.0/v3.2/v3.0.2/v3.0), audio toggle, **live cost + card count**.
- **Picker** (`/api/gallery-images` + `/api/upload`): whole-catalog infinite scroll, search,
  Collection/Source/Rating/Sort filters, upload -> media_id, optional copy-prompt-on-pick.
- **Tag Suggestions** (`/api/tag-suggest` -> GraphQL `tags(q:...)`): Danbooru-style
  autocomplete in the prompt boxes; TAB accepts. Field-probed 2026-07-04.
- **Gallery bridges**: lightbox ✎ Edit / ▶ To Video buttons; right-click context menu on
  cards; bulk-bar **Send to Video** (multi-select -> R2V refs).
- **The Loom** (`/loom`): the Seedance-style storyboard (acts/shots/cast/frame handoff)
  with **Generate shot** on PixAI + gallery picking for cast/frames. Manual: `docs/LOOM.md`.
- **Async engine**: submit (`/api/generate|edit|enhance|fix|loom/generate`) -> poll
  (`/api/task-status`) -> auto-download + catalog (`source='api'`, videos to `videos/`).
  Free cards auto-apply on every path.

## Since 1.9.x (shipped in v1.10.0)

- **Live events / push (`--watch`)**: graphql-transport-ws subscription to
  `wss://gw.pixai.art/graphql`, root field `personalEvents` (taskUpdated +
  newNotification; done status = `completed`). `--watch-backup` auto-collects each
  finished task the moment it completes — this is how website gens can land without
  polling. NOTE: only runs while the watcher runs; gens made on pixai.art otherwise
  still need `--update`/backfill. ("Live-mirror inside the server" is the planned fix.)
- **Control Panel jobs**: whitelisted CLI subprocesses with live log, a REAL progress
  bar (CLI emits `~=MGPROG=~done|total|new` lines when `MOONGLADE_PROGRESS=1`), a
  **Stop this job** cancel (`/api/panel/cancel`, terminates the subprocess, status
  `cancelled` not `failed`), and an hourly scheduler for safe jobs. Includes
  `backfill-meta` (`--backfill-full-meta`) — web parity with the GUI.
- **Server control**: Homebridge-style **Stop/Restart** from the Panel
  (`/api/server/stop|restart`; restart = exit 42 relaunched by the `Serve Gallery.pyw`
  supervisor, `MOONGLADE_SUPERVISED=1`; single-instance guard pings `/api/ping` and
  just opens the browser if already running; extra args in untracked `serve.txt`,
  child output in `serve.log`).
- **CSV export is a browser download** (`/export-csv`, in-memory, lands in Downloads)
  — deliberately NOT a panel subprocess.
- **Branding system**: machine-local marks in `out_dir/branding/marks/` (PNG +
  multi-res ICO + `marks.json`; green-keyed floaters or `mk-tile` rounded tiles),
  `branding.json` `{mark, anim}`, `/api/branding` GET/POST (POST localhost-only),
  15 banner-mark animations (`classic` legacy glow/glint/twinkle + glow/shine/aurora/
  twinkle/shoot/halo/eclipse/ripple/mist/prism/breathe/tilt/float/orbit — per-anim
  rules use !important over the mute rules; reduced-motion catch-all is
  class-tripled), Panel > Branding card, and `/api/branding/shortcut` which writes a
  Desktop `.lnk` (whitelisted mark -> `.ico`; a `.pyw` can't carry an icon, the
  shortcut can). A context processor injects `mark_url/mark_anim/mark_kind` into
  every page; corrupt branding JSON degrades to `logo.png`+classic, never a 500.
- **Header**: frosted glow-pill nav with per-destination hue (`--btn-hue` classes
  `b-loom/b-ach/b-contest/b-art/b-panel/b-health`); the balance chip caches
  last-known credits/cards in localStorage so it never blanks on navigation.
- **Community**: `--contests` + `/api/contests` (REST `/contest/list`); achievements
  + earnable skins (`/api/achievements`, `/api/skin`).

## Test suite

375 pytest tests in `tests/` (the count grows with every feature — trust `python -m pytest`
over this number). Run with `python -m pytest`. All tests must pass before merging to master.

---

## Current state

- **Version:** `1.10.0` on `master`
- **Branch strategy:** feature branches, merge to master with `--no-ff`, tag releases
- **Owner:** Nelnamara / Kil'jaeden — Balance Druid, WoW addon dev

---

## Quick command reference

```
python pixai_gallery_backup.py --probe                    # connection sanity check
python pixai_gallery_backup.py --count                    # tally tasks + images
python pixai_gallery_backup.py --max 40                   # small test download
python pixai_gallery_backup.py                            # full download (4 workers, 250/page)
python pixai_gallery_backup.py --update                   # fast incremental: stop at already-downloaded history
python pixai_gallery_backup.py --update --workers 8       # incremental + higher concurrency
python pixai_gallery_backup.py --workers 8 --page-size 500  # fast full backfill
python pixai_gallery_backup.py --full-meta                # download + full prompt/seed/model
python pixai_gallery_backup.py --backfill-full-meta       # fill existing rows
python pixai_gallery_backup.py --organize --dry-run       # preview month-folder normalize
python pixai_gallery_backup.py --organize                 # normalize into YYYY-MM/ (reversible; --organize-adv is an alias)
python pixai_gallery_backup.py --catalog-stats            # summarize catalog.db
python pixai_gallery_backup.py --export-csv               # export catalog.db → CSV
python pixai_gallery_backup.py --sync-artworks            # merge published-artwork metadata (title/likes/tags) by media_id
python pixai_gallery_backup.py --audit                    # read-only duplicate report → audit_report.csv
python pixai_gallery_backup.py --audit --no-content       # fast: same-media_id location dupes only
python pixai_gallery_backup.py --dedup                    # dry-run dedup plan (nothing changes)
python pixai_gallery_backup.py --dedup --apply            # quarantine redundant copies to _duplicates/
python pixai_gallery_backup.py --dedup --apply --dedup-delete  # delete instead of quarantine
python pixai_gallery_backup.py --verify-dupes             # confirm _duplicates/ is safe to delete
python pixai_gallery.py --out pixai_backup                # launch gallery at :5000 (+ /health dashboard)
python pixai_gallery_backup.py --delete-task <id> [<id> ...]        # DRY-RUN: list what would be deleted (nothing happens)
python pixai_gallery_backup.py --delete-task <id> --apply --yes     # actually delete from your account (irreversible; null=success)
python pixai_gallery_backup.py -v --update                # verbose: per-page / per-image timing diagnostics
python pixai_gallery_backup.py --watch                    # live event stream (WS push): watch tasks complete
python pixai_gallery_backup.py --watch --watch-backup     # + auto-collect each finished gen as it completes
python pixai_gallery_backup.py --contests                 # list live PixAI contests (read-only)
# --- creating (all preview-only until --confirm; --task-id recovers a task for free) ---
python pixai_gallery_backup.py --account                  # read-only credits/membership dashboard
python pixai_gallery_backup.py --cards                    # read-only free-card (kaisuuken) balances + ids
python pixai_gallery_backup.py --claims                   # read-only claimable rewards (daily credits, stamina)
python pixai_gallery_backup.py --claim all --confirm      # claim ready rewards (gated; grants to your account)
python pixai_gallery_backup.py --suggest-prompt <id|file> # image-to-prompt: tags + description (free)
python pixai_gallery_backup.py --upload path/to/image.png # local file -> media_id (free; S3 upload)
python pixai_gallery_backup.py --generate --prompt "..."               # preview an image gen (add --confirm to spend)
python pixai_gallery_backup.py --generate-video --image <media_id> --prompt "..."   # preview i2v (EXPENSIVE; --confirm)
python pixai_gallery_backup.py --reference-video --ref-image <id1> --ref-image <id2> --prompt "@image1 ... @image2 ..."  # preview multi-ref video
python pixai_gallery_backup.py --edit-image --edit-src <media_id|file> --prompt "make it night"  # preview an edit
python pixai_gallery_backup.py --generate-video --task-id <id> --dump-params  # recover a task (free) + print its full submit shape
```

**Free cards auto-apply** (shipped 2026-07-03): on `--confirm`, `_apply_kaisuuken` calls PixAI's
`/v2/kaisuuken/check` with the submit params, finds the nearest-expiry matching card, and attaches its
`kaisuukenId` → the generation costs **0 credits**, exactly like the website. Works for every create path
(generate / edit / video / reference-video). Preview prints FREE-vs-paid up front. `--no-card` forces
credits; `--kaisuuken-id <id>` forces a specific card. `--dump-params` banks any submit shape off a
recovered `--task-id` (no browser). Deep RE detail (incl. the full `/v2` REST surface) in git-ignored
`private/GENERATOR_SURFACE.md`.

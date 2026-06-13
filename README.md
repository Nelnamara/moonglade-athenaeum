# PixAI Gallery Backup

> **Language:** Python 3.8+ · **Platform:** Windows / macOS / Linux · **Author:** Nelnamara

A command-line tool (with optional desktop GUI) that backs up **your own** PixAI.art generated images at full resolution. PixAI's gallery UI only shows 20 images at a time; this talks to the same API the browser uses, pages through your entire generation history, downloads every image, and keeps a fully searchable catalog of prompts, seeds, model names, dimensions, and dates.

PixAI's terms grant users copyright of their own generations. This tool is rate-paced to be polite to their servers.

---

## Features

- **Full-resolution downloads** — bypasses the 20-image gallery limit; fetches every generation at the original size
- **Automatic resume** — interrupt any time and re-run; already-saved images are skipped by media ID
- **Persistent catalog** — `catalog.csv` is a deduplicated, append-safe database keyed by `media_id`; prior-session rows are never lost across interrupted or multi-session downloads
- **Full generation metadata** — `--full-meta` captures the complete prompt, seed, steps, sampler, CFG scale, and human-readable model name via a second API call per task; `--backfill-full-meta` fills existing catalog rows retroactively
- **Progress meter** — pre-flight library count feeds a live progress bar; resume runs open at the correct position based on files already on disk
- **Backward pagination** — walks newest → oldest through your entire generation history
- **Format conversion** — optionally convert WebP to PNG (lossless) or JPEG on download, or batch-convert existing files with `--convert-existing`
- **Organize mode** — sorts files into `batches/` folders (multi-image generations) and `YYYY-MM/` month folders (singles); writes per-folder `_prompt.txt` and `_index.csv`
- **Embedded metadata** — writes prompt, IDs, and date directly into PNG text chunks or JPEG EXIF on organize
- **Count mode** — tallies total tasks and images via the API without downloading
- **Probe mode** — connection sanity check; confirms it can see and resolve a full-res URL before committing to a run
- **Rate limiting** — configurable delay between requests (default 0.4 s)
- **SSL safety** — HTTPS verification always on; `truststore` support for corporate/antivirus environments

---

## GUI

A PySide6 desktop GUI (`pixai_gui.py`) wraps the full backup workflow in a tabbed window with a dark Catppuccin Mocha theme, background download thread, and live log output.

| Tab | What it does |
|---|---|
| **Download** | Configure token, output folder, page size, organize mode, conversion, and full-meta fetch; Start / Stop |
| **Organize** | Post-download rename (`--organize`) or full folder sort (`--organize-adv`); dry-run preview |
| **Convert** | Batch-convert existing `.webp` files to PNG or JPEG in place |
| **Utilities** | Probe, Count, Catalog Stats, Backfill url/width/height, Backfill Full Meta |

Settings (token, output folder, options) are saved to `pixai_gui_settings.json` next to the script (git-ignored).

**Run the GUI:**
```
pip install PySide6
python pixai_gui.py
```

---

## Requirements

| Package | Required | Notes |
|---|:---:|---|
| `requests` | ✅ | All network operations |
| `truststore` | ❌ | Recommended — fixes HTTPS cert errors from corporate proxies or antivirus (Python 3.10+) |
| `pillow` | ❌ | Needed for `--convert`, `--convert-existing`, and metadata embedding in `--organize` |
| `PySide6` | ❌ | Desktop GUI only (`pixai_gui.py`) |
| `flask` | ❌ | Local web gallery only (`pixai_gallery.py`, coming soon) |
| `pytest` + `pytest-mock` | ❌ | Development / testing only |

Install everything at once:

```
pip install requests truststore pillow PySide6
```

---

## Installation

1. Install Python 3.8 or newer — check with `python --version`
2. Install dependencies (above)
3. Put `pixai_gallery_backup.py` and `config.example.json` in a folder of their own
4. Copy `config.example.json` to `config.json` in the same folder and fill in your values (see [Configuration](#configuration) below)
5. All output is created next to the script in `pixai_backup/`

> **Tip:** Use a dedicated folder — the script creates its output directory alongside itself.

---

## Configuration

`config.json` lives next to the script and is git-ignored. It holds values captured once from your browser.

### Required keys

| Field | Where to find it |
|---|---|
| `USER_ID` | Your PixAI profile URL — the numeric ID at the end |
| `U3T` | Network tab → `graphql` row → Payload → `u3t` parameter |
| `PERSISTED_QUERY_HASH` | Network tab → `graphql` row → Payload → `extensions.persistedQuery.sha256Hash` |

To capture: log in to [pixai.art](https://pixai.art), open your gallery, press **F12 → Network**, filter by `graphql`, scroll once so a request appears, then click the `listUserTaskSummaries` row and read from the **Payload** tab.

### Optional keys (full meta)

See [Full Meta](#full-meta-full-prompt-seed-model) for details and capture instructions.

| Field | Purpose |
|---|---|
| `TASK_DETAIL_HASH` | Required for `--full-meta` and `--backfill-full-meta` |
| `MODEL_DETAIL_HASH` | Required for human-readable model names alongside `TASK_DETAIL_HASH` |

> **`config.json` is git-ignored** and will never be committed.

---

## Usage

### Getting Your Token

The script never sees your password. It uses a short-lived **Bearer token** from your logged-in browser.

1. Log in to [pixai.art](https://pixai.art) and open your gallery
2. Open DevTools — press **F12**
3. Click the **Network** tab and type `graphql` in the filter box
4. Scroll your gallery so a request appears; click any `graphql` row
5. In **Request Headers**, find `authorization: Bearer eyJ...` — copy everything **after** `Bearer `

Keep the token private — treat it like a password. It expires on its own (hours to a few days).

### Providing the Token

**Windows (PowerShell):**
```
$env:PIXAI_TOKEN="eyJ...your token..."
```

**macOS / Linux:**
```
export PIXAI_TOKEN="eyJ...your token..."
```

Or create `token.txt` next to the script containing just the token. Or pass `--token "eyJ..."` on the command line.

### First Run

```
python pixai_gallery_backup.py --probe        # confirm connection + full-res URL
python pixai_gallery_backup.py --count        # how many images you have
python pixai_gallery_backup.py --max 40       # small test download
python pixai_gallery_backup.py                # download everything
python pixai_gallery_backup.py --full-meta    # download + capture full prompt/seed/model
```

### Organizing Downloads

**Post-download (run after a download session):**
```
python pixai_gallery_backup.py --organize --dry-run        # preview rename plan
python pixai_gallery_backup.py --organize                  # rename to prompt_taskid_mediaid
python pixai_gallery_backup.py --organize-adv --dry-run    # preview full folder sort
python pixai_gallery_backup.py --organize-adv --convert png  # sort into folders + convert
```

**Live (sort as files download — one step, no separate organize pass):**
```
python pixai_gallery_backup.py --organize-adv-live --convert png   # download + folder sort
```

### Modes

| Flag | What it does |
|---|---|
| *(none)* | Download full history into `images/`, named `prompt_taskid_mediaid.ext` |
| `--probe` | Resolve one full-res URL and exit — connection sanity check |
| `--count` | Tally total tasks and images via the API (no downloads) |
| `--catalog-stats` | Summarize existing `catalog.csv` and count files on disk (no token needed) |
| `--collect-only` | Page through and write the catalog, skip image downloads |
| `--backfill-meta` | Fill missing `url`/`width`/`height` in catalog via `resolve_media` (no downloads) |
| `--backfill-full-meta` | Fill full prompt/seed/model/etc in catalog via `getTaskById`; also fills url/width/height |
| `--organize` | Rename files in `images/` to `prompt_taskid_mediaid` scheme using `catalog.csv` |
| `--organize-live` | Same naming applied live during download (makes intent explicit) |
| `--organize-adv` | Full sort: move files into `batches/` and `YYYY-MM/` folders, embed metadata |
| `--organize-adv-live` | Full sort applied live during download |
| `--convert-existing` | Convert all already-downloaded `.webp` files to `--convert` format (default `png`) |

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--token TOKEN` | — | Bearer token (else `PIXAI_TOKEN` env or `token.txt`) |
| `--out DIR` | `pixai_backup` | Output folder |
| `--page-size N` | `20` | Tasks per request during download (try `5000` for speed; keep ≤ ~8000) |
| `--max N` | `0` (all) | Stop after N tasks — use small numbers for testing |
| `--delay SECONDS` | `0.4` | Pause between requests |
| `--count-page-size N` | `5000` | Page size for `--count` (server errors above ~10000) |
| `--full-meta` | off | Fetch full prompt, seed, steps, sampler, CFG, and model name per task (requires `TASK_DETAIL_HASH` + `MODEL_DETAIL_HASH` in `config.json`) |
| `--name-length N` | `60` | Max prompt characters used in filenames |
| `--name-sep CHAR` | `_` | Word separator in filenames (`_` or `-`) |
| `--convert FMT` | off | Convert downloads: `png` or `jpeg` |
| `--jpeg-quality N` | `92` | JPEG quality (1–100) |
| `--jpeg-bg COLOR` | `white` | Background for transparency when converting to JPEG |
| `--keep-webp` | off | Keep the original `.webp` after converting |
| `--dry-run` | off | Preview `--organize` or `--organize-adv` without making changes |

---

## Output Structure

After a plain download:

```
pixai_backup/
├─ images/                 all images, flat — <prompt>_<taskid>_<mediaid>.<ext>
├─ catalog.csv             one row per image (see Catalog Columns below)
└─ raw_tasks.jsonl         full raw task data (kept for re-processing)
```

After `--organize-adv` or `--organize-adv-live`:

```
pixai_backup/
├─ batches/
│   └─ <prompt>_<taskid>/        one folder per multi-image generation
│       ├─ 01_<mediaid>.png
│       ├─ 02_<mediaid>.png
│       └─ _prompt.txt           shared prompt, IDs, date, image list
├─ 2025-03/                      single-image generations grouped by month
│   ├─ <prompt>_<taskid>_<mediaid>.png
│   └─ _index.csv
├─ 2026-06/
│   └─ ...
├─ images/                       (empties out as files are moved)
└─ catalog.csv
```

> **Keep `catalog.csv`.** It is the source of truth for full prompts, seeds, dates, and dimensions. Filenames are shortened and stripped of punctuation so the catalog is the only complete record.

### Catalog Columns

| Column | Added | Description |
|---|---|---|
| `task_id` | v4.0 | PixAI task ID |
| `media_id` | v4.0 | PixAI media ID (primary key) |
| `filename` | v4.0 | Local filename |
| `url` | v4.0 | Full-res media URL |
| `width` | v4.0 | Image width (px) |
| `height` | v4.0 | Image height (px) |
| `prompt_preview` | v4.0 | Truncated ~100-char prompt from task summary |
| `status` | v4.0 | Task status (e.g. `completed`) |
| `created_at` | v4.0 | ISO 8601 creation timestamp |
| `prompt_full` | v4.4 | Full untruncated prompt (`--full-meta`) |
| `natural_prompt` | v4.4 | Auto-generated natural language prompt (`--full-meta`) |
| `seed` | v4.4 | Generation seed (`--full-meta`) |
| `steps` | v4.4 | Inference steps (`--full-meta`) |
| `sampler` | v4.4 | Sampler name, e.g. "Euler a" (`--full-meta`) |
| `cfg_scale` | v4.4 | CFG scale (`--full-meta`) |
| `model_id` | v4.4 | Model version ID (`--full-meta`) |
| `model_name` | v4.4 | Human-readable model name, e.g. "Tsubaki.2 v1" (`--full-meta`) |

---

## Full Meta (Full Prompt, Seed, Model)

By default the download only captures `prompt_preview` — a truncated ~100-character summary from the task list API. The `--full-meta` flag makes an additional `getTaskById` call per task to capture the complete generation parameters.

### One-time config setup

Add these two keys to your `config.json`:

```json
"TASK_DETAIL_HASH": "2526f64c73c59fcfeff938b0f4a8b3b610f2294bc6eb6b6b281aa671ac81a08e",
"MODEL_DETAIL_HASH": "0d2ab28b2991e3fd74672ffec0adf8947e599d79e0039348a7d2642e0bf8c9bc"
```

If PixAI updates their frontend and these hashes stop working, recapture them:
1. Log in to [pixai.art](https://pixai.art) and click any image to open its detail view
2. DevTools → Network → filter `graphql`
3. Find `getTaskById` — copy its `extensions.persistedQuery.sha256Hash` → `TASK_DETAIL_HASH`
4. Find `getGenerationModelByVersionId` — copy its hash → `MODEL_DETAIL_HASH`

### Usage

```
# Fetch full meta on new downloads (one extra API call per unique task):
python pixai_gallery_backup.py --full-meta

# Backfill existing catalog rows:
python pixai_gallery_backup.py --backfill-full-meta
```

`--backfill-full-meta` makes one call per unique `task_id` — a 5-image batch costs one call, not five. At 0.4 s delay across ~8,857 unique tasks that is roughly 60 minutes. It also fills any missing `url`/`width`/`height` as a free bonus.

---

## Known Issues

| Issue | Status |
|---|---|
| WebP metadata embedding is unreliable | `--organize-adv` skips WebP files; pair with `--convert png` to get embedded metadata |
| Windows MAX_PATH (260 chars) | Batch images use short names (`NN_<mediaid>.ext`) inside prompt-named folders; `--name-length` defaults to 60 |
| Server errors above ~10,000 tasks per page | `--count-page-size` defaults to 5,000; lower further if you see `Internal server error` on `--count` |

---

## Changelog

### v4.4
- `--full-meta` flag — fetches full prompt, seed, steps, sampler, CFG, and model name per task via `getTaskById` + `getGenerationModelByVersionId`; model lookups cached in memory; one extra call per unique task_id (batches share one call)
- `--backfill-full-meta` — fills 8 new catalog fields for all existing rows; also backfills url/width/height from the task media object as a free side effect
- `--backfill-meta` — lighter alternative that fills only missing url/width/height via `resolve_media`
- 8 new catalog columns: `prompt_full`, `natural_prompt`, `seed`, `steps`, `sampler`, `cfg_scale`, `model_id`, `model_name` — backward compatible (existing rows get empty strings until backfilled)
- `config.json` gains two optional keys: `TASK_DETAIL_HASH` and `MODEL_DETAIL_HASH`
- GUI Download tab: **Fetch full prompt / seed / model** checkbox
- GUI Utilities tab: **Backfill url/width/height** and **Backfill Full Meta** buttons
- Test suite expanded to 68 tests

### v4.3
- `tests/` with pytest — 68 tests covering pure functions, filesystem, catalog persistence, and network functions with mocked `requests.Session`
- `pytest-mock` added to `requirements.txt`; `pytest.ini` added at repo root

### v4.2
- Download progress meter — pre-flight `_quick_count()` pass followed by live ASCII bar (CLI) and `QProgressBar` (GUI)
- Resume-aware progress — seeds bar from image files on disk via recursive glob; works for flat, `--organize-adv`, and `--organize-adv-live` layouts
- Config and token path resolution anchored to `Path(__file__).resolve().parent` so the GUI finds files regardless of working directory
- `_make_session()` re-reads and refreshes module-level globals on every call
- `gql()` non-JSON error converted from `sys.exit(1)` to `raise PixAIError`
- `pixai_gui_settings.json` added to `.gitignore`

### v4.1
- PySide6 GUI (`pixai_gui.py`) — tabbed Download / Organize / Convert / Utilities window with dark Catppuccin Mocha theme, background Worker thread, and settings persistence
- `PixAIError` exception class; all `sys.exit()` in library functions replaced with raises

### v4.0
- Switched to media object resolution: fetch `/v1/media/<id>` JSON and pick the `PUBLIC` variant URL
- Backward pagination (`last` / `before` / `hasPreviousPage`) with full resume support
- `--organize-adv` and `--organize-adv-live` modes with per-folder `_prompt.txt`, `_index.csv`, and embedded PNG/JPEG metadata
- `--organize` and `--organize-live` modes
- `--convert-existing` mode with `--dry-run` and `--keep-webp`
- `--convert` (WebP → PNG / JPEG) with Pillow, atomic `.part` temp writes
- `--count`, `--probe`, `--catalog-stats`, `--collect-only` modes
- Apollo CSRF headers required on all GraphQL requests
- `truststore` integration for corporate/antivirus HTTPS interception

---

## Roadmap

- [x] **`config.json` for captured constants** — `USER_ID`, `U3T`, and `PERSISTED_QUERY_HASH` loaded from git-ignored `config.json`
- [x] **Full prompt + seed + model** — `--full-meta` / `--backfill-full-meta` via `getTaskById` + `getGenerationModelByVersionId`
- [x] **`--convert-existing`** — batch-convert already-downloaded `.webp` files in place
- [x] **Foldering during live download** — `--organize-adv-live` sorts files as they download
- [x] **Persistent catalog** — deduplicated, append-safe `catalog.csv` keyed by `media_id`
- [x] **`tests/` with pytest** — 68 tests with mocked network layer
- [x] **GUI port** — PySide6 desktop app with tabbed layout, dark theme, and background worker
- [ ] **Local web gallery** — Flask + Jinja2 gallery server (`pixai_gallery.py`) with filters, pagination, and delete

---

## Feature Requests

Planned future enhancements — not yet scheduled:

- **Persistent cross-page selection in gallery** — checkbox selections that survive pagination via browser `localStorage`; currently selection is page-scoped only
- **Bulk re-tag / prompt edit** — edit `prompt_full` in the gallery and write back to `catalog.csv`
- **Tag system** — add freeform tags to images in the gallery, stored as an extra catalog column
- **Export selected** — download a ZIP of checked images directly from the gallery
- **PixAI favorites sync** — filter downloads to only favorited generations via the `favoritedAt` field already present in task summaries

---

## License

Personal use. Not affiliated with or endorsed by PixAI.

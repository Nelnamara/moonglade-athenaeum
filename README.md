# PixAI Gallery Backup

> **Language:** Python 3.8+ · **Platform:** Windows / macOS / Linux · **Author:** Nelnamara

A command-line tool that backs up **your own** PixAI.art generated images at full resolution. PixAI's gallery UI only shows 20 images at a time; this talks to the same API the browser uses, pages through your entire generation history, downloads every image, and keeps a searchable catalog of prompts, dimensions, and dates.

PixAI's terms grant users copyright of their own generations. This tool is rate-paced to be polite to their servers.

---

## Screenshots

> *Replace the placeholders below with your own terminal screenshots.*

| Download Run | Organize Output | Catalog Stats |
|:---:|:---:|:---:|
| ![Download run progress](docs/screenshot-download.png) | ![Organize folder output](docs/screenshot-organize.png) | ![Catalog stats summary](docs/screenshot-stats.png) |

---

## Features

- **Full-resolution downloads** — bypasses the 20-image gallery limit; fetches every generation at the original size
- **Automatic resume** — interrupt any time and re-run; already-saved images are skipped by media ID
- **Catalog** — `catalog.csv` records each image's prompt preview, dimensions, date, task ID, and media ID
- **Backward pagination** — walks newest → oldest through your entire generation history
- **Format conversion** — optionally convert WebP to PNG (lossless re-container) or JPEG on download
- **Organize mode** — sorts downloaded files into `batches/` folders (multi-image generations) and `YYYY-MM/` month folders (singles), writes per-folder `_prompt.txt` and `_index.csv` info files
- **Embedded metadata** — writes prompt, IDs, and date directly into PNG text chunks or JPEG EXIF on organize
- **Count mode** — tallies total tasks and images via the API without downloading
- **Probe mode** — connection sanity check; confirms it can see and resolve a full-res URL before committing to a run
- **Rate limiting** — configurable delay between requests (default 0.4 s)
- **SSL safety** — HTTPS verification always on; `truststore` support for corporate/antivirus environments

---

## Requirements

| Package | Required | Notes |
|---|:---:|---|
| `requests` | ✅ | All network operations |
| `truststore` | ❌ | Recommended — fixes HTTPS cert errors from corporate proxies or antivirus (Python 3.10+) |
| `pillow` | ❌ | Only needed for `--convert` and metadata embedding in `--organize` |

Install all at once:

```
pip install requests truststore pillow
```

---

## Installation

1. Install Python 3.8 or newer — check with `python --version`
2. Install dependencies (above)
3. Put `pixai_gallery_backup.py` and `config.example.json` in a folder of their own (e.g. a `pixai` folder on your Desktop)
4. Copy `config.example.json` to `config.json` in the same folder and fill in your values (see Configuration below)
5. All output is created next to the script

> **Tip:** Use a dedicated folder — the script creates a `pixai_backup/` output directory alongside itself.

---

## Configuration

The script reads three values from `config.json` next to the script. These are captured once from your browser and stay until PixAI changes their frontend.

1. Copy `config.example.json` to `config.json`
2. Fill in the three fields:

| Field | Where to find it |
|---|---|
| `USER_ID` | Your PixAI profile URL — the numeric ID at the end |
| `U3T` | Network tab → `graphql` row → Payload → `u3t` parameter |
| `PERSISTED_QUERY_HASH` | Network tab → `graphql` row → Payload → `extensions.persistedQuery.sha256Hash` |

To capture from the browser: log in to [pixai.art](https://pixai.art), open your gallery, press **F12 → Network**, filter by `graphql`, scroll once so a request appears, then click the `listUserTaskSummaries` row and read from the **Payload** tab.

> **`config.json` is git-ignored** and will never be committed. Keep it next to the script only.

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
```

### Organizing Downloads

```
python pixai_gallery_backup.py --organize --convert png --dry-run   # preview
python pixai_gallery_backup.py --organize --convert png             # apply
```

### Modes

| Flag | What it does |
|---|---|
| *(none)* | Download full history into `images/` and write `catalog.csv` |
| `--probe` | Resolve one full-res URL and exit — connection sanity check |
| `--count` | Tally total tasks and images via the API (no downloads) |
| `--catalog-stats` | Summarize existing `catalog.csv` and count files on disk (no token needed) |
| `--collect-only` | Page through and write the catalog, skip image downloads |
| `--rename-existing` | Rename already-downloaded files to the prompt-based scheme using the catalog |
| `--organize` | Sort files into `batches/` and `YYYY-MM/` folders, embed metadata |

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--token TOKEN` | — | Bearer token (else `PIXAI_TOKEN` env or `token.txt`) |
| `--out DIR` | `pixai_backup` | Output folder |
| `--page-size N` | `20` | Tasks per request during download (try `5000` for speed; keep ≤ ~8000) |
| `--max N` | `0` (all) | Stop after N tasks — use small numbers for testing |
| `--delay SECONDS` | `0.4` | Pause between requests |
| `--count-page-size N` | `10000` | Page size for `--count` |
| `--name-length N` | `60` | Max prompt characters used in filenames |
| `--name-sep CHAR` | `_` | Word separator in filenames (`_` or `-`) |
| `--convert FMT` | off | Convert downloads: `png` or `jpeg` |
| `--jpeg-quality N` | `92` | JPEG quality (1–100) |
| `--jpeg-bg COLOR` | `white` | Background for transparency when converting to JPEG |
| `--keep-webp` | off | Keep the original `.webp` after converting |
| `--dry-run` | off | Preview `--organize` or `--rename-existing` without making changes |

---

## Output Structure

After a plain download:

```
pixai_backup/
├─ images/                 all images, flat — <prompt>_<taskid>_<mediaid>.<ext>
├─ catalog.csv             one row per image: prompt, dimensions, date, IDs, filename
└─ raw_tasks.jsonl         full raw task data (kept for re-processing)
```

After `--organize`:

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

> **Keep `catalog.csv`.** It is the source of truth for full prompt previews, dates, and dimensions. Both `--organize` and `--rename-existing` read from it — filenames are shortened and stripped of punctuation, so the catalog is the complete record.

---

## Known Issues

| Issue | Status |
|---|---|
| `promptsPreview` is truncated — full prompt, seed, and model are not available in task summaries | Requires a separate task-detail API query; on the roadmap |
| WebP metadata embedding is unreliable | `--organize` skips WebP; pair with `--convert png` to get embedded metadata |
| Windows MAX_PATH (260 chars) | Batch images use short names (`NN_<mediaid>.ext`) inside prompt-named folders; `--name-length` defaults to 60 |
| `--convert` only affects new downloads | Already-downloaded WebP files are not converted on re-run; `--convert-existing` is on the roadmap |
| Server errors above ~10,000 tasks per page | `--count-page-size` defaults to 10,000; lower it if you see `Internal server error` on `--count` |

---

## Changelog

### v4.0
- Switched to media object resolution: fetch `/v1/media/<id>` JSON and pick the `PUBLIC` (full-resolution) variant URL, replacing direct variant-URL probing
- Backward pagination (`last` / `before` / `hasPreviousPage`) with full resume support
- `--organize` mode: sort into `batches/` and `YYYY-MM/` folders, per-folder `_prompt.txt` and `_index.csv`, embedded PNG/JPEG metadata
- `--convert` (WebP → PNG / JPEG) with Pillow, atomic `.part` temp writes
- `--count`, `--probe`, `--catalog-stats`, `--rename-existing`, `--collect-only` modes
- Apollo CSRF headers (`apollo-require-preflight`, `x-apollo-operation-name`) required on all GraphQL requests
- `truststore` integration for corporate/antivirus HTTPS interception

---

## Roadmap

- [x] **`config.json` for captured constants** — `USER_ID`, `U3T`, and `PERSISTED_QUERY_HASH` loaded from git-ignored `config.json`; `config.example.json` ships with the repo
- [ ] **Full prompt + seed + model** — capture the task-detail persisted query to store complete generation parameters (currently only the truncated preview)
- [ ] **`--convert-existing`** — convert already-downloaded WebP files in place
- [ ] **Foldering during live download** — apply the `--organize` layout as files arrive (one step instead of download-then-organize)
- [ ] **`tests/` with pytest** — mocked network layer for offline testing of API logic
- [ ] **GUI port** — C#/WinForms or Go/Wails desktop app with token field and progress bar (full API flow already mapped)

---

## License

Personal use. Not affiliated with or endorsed by PixAI.

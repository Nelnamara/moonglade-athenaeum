# Backing up

## First run

```bash
python pixai_gallery_backup.py --probe        # confirm connection
python pixai_gallery_backup.py --count        # how many images you have
python pixai_gallery_backup.py --max 40       # small test download
python pixai_gallery_backup.py                # download everything (parallel)
python pixai_gallery_backup.py --full-meta    # download + capture full prompt/seed/model
```

Everything lands in `pixai_backup/` (git-ignored): `images/`, `catalog.db`,
`raw_tasks.jsonl`, and — once organized — `YYYY-MM/` month folders.

## Fast downloads & incremental updates

The download path is parallel and incremental. For routine "grab what's new":

```bash
python pixai_gallery_backup.py --sync                      # one-shot: the whole refresh chain
python pixai_gallery_backup.py --update                    # stops when it reaches what you have
python pixai_gallery_backup.py --update --workers 8        # more concurrency
python pixai_gallery_backup.py --workers 8 --page-size 500 # fast full backfill
```

- `--sync` is the one-shot refresh: incremental pull **with** full metadata (same as
  `--update --full-meta`), then re-resolve unlabeled model names, fill any rows still
  missing prompts/seeds/models, build missing thumbnails, and flag rows deleted on the
  website. Every step is idempotent, so re-running it on a clean catalog costs almost
  nothing. `--update` on its own is the narrower primitive.
- `--workers N` (default 4) = how many images download at once. 6–8 saturates most
  connections; composes with every flag.
- `--update` stops after `--update-grace` consecutive already-on-disk pages (default
  2). To backfill items missing from the **middle** of your history, run **without**
  `--update` (it only reaches the newest items).
- The progress total comes from your catalog (instant). `--accurate-count` forces a
  full-history API count.

### Download tuning

| Flag | Default | Meaning |
|---|---|---|
| `--delay` | `0.4` | seconds between API requests (politeness throttle; applies to most commands, not just downloads) |
| `--count-page-size` | `5000` | page size `--count` uses to tally — bigger = fewer requests, but the server errors above ~10,000 |
| `--collect-only` | off | scan and catalog without downloading any files (also forces single-worker mode) |
| `--name-length` | `60` | max characters of the prompt used in filenames |
| `--name-sep` | `_` | word separator in filenames (`_` or `-`) |

## Full metadata

```bash
python pixai_gallery_backup.py --full-meta            # on new downloads
python pixai_gallery_backup.py --backfill-full-meta   # fill existing catalog rows
```

Captures the complete prompt, seed, steps, sampler, CFG, human-readable model name,
LoRAs, and the generation's actual credit cost (`paid_credit`; `0` = free via a card
or the daily free tier).

- `--backfill-full-meta --with-loras` widens the backfill to rows that already have
  full meta but no LoRA data yet (older images predate LoRA capture) — a long run,
  since each needs its task re-fetched.
- `--backfill-full-meta --with-credit` does the same for the credit cost: rows
  cataloged before cost tracking (2026-07-23) recover what they actually cost from
  the task record — also a long run. `--catalog-stats` then shows the spend total.
- `--backfill-meta` (no "full") is the lightweight sibling: it only fills missing
  url/width/height, no prompt/seed/model fetching.

## Videos & published artwork

```bash
python pixai_gallery_backup.py --sync-videos          # back up image-to-video mp4s
python pixai_gallery_backup.py --sync-artworks        # published titles/tags/likes/aesthetic
python pixai_gallery_backup.py --sync-artworks --with-videos
```

## Converting formats (`--convert`)

PixAI serves `.webp`; if you'd rather keep `.png` or `.jpeg` on disk (needs Pillow):

```bash
python pixai_gallery_backup.py --convert png            # convert as files download
python pixai_gallery_backup.py --convert-existing       # convert what's already on disk (no token needed)
python pixai_gallery_backup.py --convert-existing --dry-run   # preview first
```

| Flag | Default | Meaning |
|---|---|---|
| `--convert` | — | `png` or `jpeg`; replaces each `.webp` after download |
| `--convert-existing` | off | one-shot pass over already-downloaded `.webp` files (defaults to png if `--convert` isn't given) |
| `--keep-webp` | off | keep the original `.webp` alongside the converted copy |
| `--jpeg-quality` | `92` | JPEG quality 1–100 (with `--convert jpeg`) |
| `--jpeg-bg` | `white` | `white` or `black` — the color transparency is flattened onto for JPEG |

## Live watch (`--watch`)

A live WebSocket feed of your account: watch generations complete in real time, and
optionally auto-collect each one the moment it finishes.

```bash
python pixai_gallery_backup.py --watch                     # stream events until Ctrl-C
python pixai_gallery_backup.py --watch --watch-backup      # + download each finished gen immediately
python pixai_gallery_backup.py --watch --watch-seconds 600 # auto-stop after 10 minutes
```

## Importing your own media

From the **CLI**:

```bash
python pixai_gallery_backup.py --import-local         # catalog files dropped into the backup
python pixai_gallery_backup.py --import-local <DIR>   # copy an external folder in
```

Or from the **gallery** — click **↑ Import** in the header (next to Generate) to open the
drop-zone window. Drop images, a folder, or a `.zip` (or browse), review the preview, optionally
add everything to a collection, and import. A big drop previews a capped grid, but the whole
selection is imported. Web import writes files onto the machine the gallery is hosted from, so
the **↑ Import** button is visible to everyone signed in, but the import itself is refused for
anyone connecting from another device on the LAN — only a session on the server's own machine
can actually complete it. A LAN device can browse and generate, just not write files onto the host.

Either way: files are copied into `imported/`, tagged `source='local'`, and given an ffmpeg
poster if available (videos). They show under **Source → Imported** in the gallery. Nothing is
uploaded to PixAI — this is your own library, separate from sending a file to PixAI as a
generation reference.

## Organizing files

One mode: normalize the whole backup into `YYYY-MM/` month folders with readable
`<prompt>_<taskid>_<mediaid>` names. It's idempotent, byte-safe, dry-runnable, and
**reversible**.

```bash
python pixai_gallery_backup.py --organize --dry-run        # preview
python pixai_gallery_backup.py --organize                  # do it
python pixai_gallery_backup.py --organize --embed-metadata # also embed meta into PNG/JPEG
python pixai_gallery_backup.py --undo-organize             # roll back via the manifest
```

Organizing never breaks the gallery — file lookup is by `media_id`, so images can
live in any subfolder. (This is also why [Collections](Collections) survive
Organize.)

## Duplicate audit & dedup

```bash
python pixai_gallery_backup.py --audit          # report -> audit_report.csv
python pixai_gallery_backup.py --dedup          # dry-run plan
python pixai_gallery_backup.py --dedup --apply  # quarantine redundant copies
python pixai_gallery_backup.py --verify-dupes   # confirm quarantine is safe to delete
```

`--verify-dupes` is read-only — unless you add `--restore-orphans`, which moves any
quarantined file whose keeper no longer exists back into `images/`.

## Catalog repair one-shots

Each runs its pass and exits; all are idempotent and safe to re-run.

| Command | What it fixes |
|---|---|
| `--fix-model-names` | re-resolves catalog rows whose model name is blank or a raw numeric id (one API call per distinct model). Also runs inside `--sync`. |
| `--fix-model-names --relabel-removed` | additionally labels ids that no longer resolve (deleted models) as "Unknown or removed model" instead of leaving the raw number |
| `--backfill-meta` | fills missing url/width/height only (see [Full metadata](#full-metadata) for the full-meta variant) |
| `--faststart-videos` | losslessly rewrites every video so iOS/Safari can stream it over HTTP (`ffmpeg -c copy +faststart`; needs ffmpeg on PATH; skips already-fixed files) |

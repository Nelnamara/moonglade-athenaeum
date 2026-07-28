# Backing up

## First run

```bash
python moonglade_backup.py --probe        # confirm connection
python moonglade_backup.py --count        # how many images you have
python moonglade_backup.py --max 40       # small test download
python moonglade_backup.py                # download everything (parallel)
python moonglade_backup.py               # full metadata is captured by default
```

### Where the library lives

By default everything goes in `pixai_backup/` next to the app. To keep it somewhere else — a
big drive, an external disk — set the folder in **Control Panel ▸ Library at a glance**. It
takes effect when the server next starts, and it offers to restart for you.

**Changing it never moves anything.** It points Moonglade at a different folder; whatever is
in the old one stays exactly where it is. If you want to bring an existing library along, move
the folder yourself first, then point the setting at its new home.

The order of precedence, if you use more than one of these:

1. `--out <folder>` on the command line — always wins, so a one-off run or a scheduled job
   can point anywhere without disturbing the setting.
2. `LIBRARY_DIR` in `config.json` — what the Control Panel writes.
3. `pixai_backup` — the default.

```bash
```

Everything lands in `pixai_backup/` (git-ignored): `images/`, `catalog.db`,
`raw_tasks.jsonl`, and — once organized — `YYYY-MM/` month folders.

## Fast downloads & incremental updates

The download path is parallel and incremental. For routine "grab what's new":

```bash
python moonglade_backup.py --sync                      # one-shot: the whole refresh chain
python moonglade_backup.py --update                    # stops when it reaches what you have
python moonglade_backup.py --update --workers 8        # more concurrency
python moonglade_backup.py --workers 8 --page-size 500 # fast full backfill
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
| `--delay` | `0.4` | seconds between API requests (politeness throttle). Always paces the page listing, the per-task metadata fetch, and single-worker downloads. The **multi-worker** download stage is paced only when you type `--delay` yourself — left alone, it downloads as fast as your connection, which is what the `--workers` guidance above assumes. Typing `--delay` throttles the whole pool to one image per that interval, so it slows a big backfill down a lot; that is the point of it. |
| `--count-page-size` | `5000` | page size `--count` uses to tally — bigger = fewer requests, but the server errors above ~10,000 |
| `--collect-only` | off | scan and catalog without downloading any files (also forces single-worker mode) |
| `--name-length` | `60` | max characters of the prompt used in filenames |
| `--name-sep` | `_` | word separator in filenames (`_` or `-`) |

## Full metadata

```bash
python moonglade_backup.py                        # captured by default on every pull
python moonglade_backup.py --backfill-full-meta   # fill existing catalog rows
python moonglade_backup.py --catalog-stats        # how much is already filled in
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
python moonglade_backup.py --sync-videos          # back up image-to-video mp4s
python moonglade_backup.py --sync-artworks        # published titles/tags/likes/aesthetic
python moonglade_backup.py --sync-artworks --with-videos
```

## Converting formats (`--convert`)

PixAI serves `.webp`; if you'd rather keep `.png` or `.jpeg` on disk (needs Pillow):

```bash
python moonglade_backup.py --convert png            # convert as files download
python moonglade_backup.py --convert-existing       # convert what's already on disk (no token needed)
python moonglade_backup.py --convert-existing --dry-run   # preview first
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
python moonglade_backup.py --watch                     # stream events until Ctrl-C
python moonglade_backup.py --watch --watch-backup      # + download each finished gen immediately
python moonglade_backup.py --watch --watch-seconds 600 # auto-stop after 10 minutes
```

## Importing your own media

From the **CLI**:

```bash
python moonglade_backup.py --import-local         # catalog files dropped into the backup
python moonglade_backup.py --import-local <DIR>   # copy an external folder in
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
python moonglade_backup.py --organize --dry-run        # preview
python moonglade_backup.py --organize                  # do it
python moonglade_backup.py --organize --embed-metadata # also embed meta into PNG/JPEG
python moonglade_backup.py --undo-organize             # roll back via the manifest
```

Organizing never breaks the gallery — file lookup is by `media_id`, so images can
live in any subfolder. (This is also why [Collections](Collections) survive
Organize.)

## Duplicate audit & dedup

```bash
python moonglade_backup.py --audit          # report -> audit_report.csv
python moonglade_backup.py --dedup          # dry-run plan
python moonglade_backup.py --dedup --apply  # quarantine redundant copies
python moonglade_backup.py --verify-dupes   # confirm quarantine is safe to delete
```

`--verify-dupes` is read-only — unless you add `--restore-orphans`, which moves any
quarantined file whose keeper no longer exists back into `images/`.

## Catalog repair one-shots

Each runs its pass and exits; all are idempotent and safe to re-run.

| Command | What it fixes |
|---|---|
| `--fix-model-names` | re-resolves catalog rows whose model name is blank or a raw numeric id (one API call per distinct model). Also runs inside `--sync`. |
| `--fix-model-names --relabel-removed` | additionally labels ids that **PixAI answered about and had no name for** (deleted models) as "Unknown or removed model" instead of leaving the raw number. An id whose lookup simply *failed* — timeout, 5xx, a dropped connection — is a different thing, and is now left exactly as it was and reported as `not checked`, so the next run picks it up. It used to get the "Unknown or removed model" label too, which is a permanent-looking answer to a temporary problem: a re-run then read the row as already resolved and never came back for it. |
| `--backfill-meta` | fills missing url/width/height only (see [Full metadata](#full-metadata) for the full-meta variant) |
| `--faststart-videos` | losslessly rewrites every video so iOS/Safari can stream it over HTTP (`ffmpeg -c copy +faststart`; needs ffmpeg on PATH; skips already-fixed files; safe to run while the gallery or a live watch is collecting — each remux uses its own unique temp file) |

**Every clip the faststart sweep walks lands in exactly one of *rewritten*, *already OK*
or *failed*** — the closing `Done: … rewritten, … already OK, … failed (… total)` line
adds up. That's worth stating because you only ever run this command *because* a video
wouldn't play on your phone, and a clip ffmpeg refused to remux used to land in none of
the three: the totals quietly came out short and nothing named the file still broken. Now
a refusal is called out as it happens and listed again at the end as
`still not faststart:` with its full path, so you can go and look at it. Add `-v` and each
failure carries ffmpeg's own reason for refusing, which is the only thing that tells you
whether the file is salvageable.

## Reclaiming disk space

A mature backup accumulates things that are safe to remove. Nothing below touches your
images — but read the notes, because two of these are *regenerable* rather than *disposable*,
which is a different promise.

### Safe to delete outright

These are either regenerated on demand or superseded by something newer.

| Path | What it is |
|---|---|
| `pixai_backup/catalog.db.bak*` | Old catalog snapshots from past migrations. The live catalog is `catalog.db`; these are point-in-time copies kept in case a migration went wrong. Once you've used the app since, they're dead weight — and they are large, often ~85–100 MB each. |
| `pixai_backup/catalog.csv` | The **legacy** catalog format. `_ensure_db()` migrated it into `catalog.db` automatically and nothing reads the CSV any more. (`--export-csv` writes a *fresh* one on demand, so deleting this loses nothing.) |
| `serve.log` | The gallery server's console log. Rotating file logs live in `pixai_backup/logs/` instead. |
| `__pycache__/`, `.pytest_cache/` | Python bytecode and test caches. Regenerated automatically. |
| `pixai_gui_settings.json` | Settings for the **PySide6 desktop GUI, which was removed in v2.1.0**. Pure leftover. |
| A `0`-byte `catalog.db` in the *install root* | Not your catalog — that lives at `pixai_backup/catalog.db`. An empty stray file at the top level is an artefact of an old run. Check the size before deleting: if it isn't 0 bytes, stop and ask. |

```bash
# check before you delete -- the real catalog should be tens of MB, the stray one 0
ls -l catalog.db pixai_backup/catalog.db
```

### Safe once verified

**`pixai_backup/_duplicates/`** is the dedup quarantine — copies `--dedup --apply` moved aside
rather than deleted, precisely so you could change your mind. There is a command whose whole
job is to confirm emptying it is safe:

```bash
python moonglade_backup.py --verify-dupes
```

It re-checks that every quarantined file still has a surviving copy elsewhere in the backup.
Only delete the folder once that passes.

### Regenerable, but you'll pay to rebuild

**`pixai_backup/gallery/`** holds the gallery's thumbnails — one per image, so on a large
library it is tens of thousands of files and several GB. Deleting it costs you nothing
permanent, but the gallery will regenerate them on demand and the first browse afterwards
will be slow. Worth doing only if you're genuinely short of space.

### Not cruft — just untidy

If a lot of files sit directly in `pixai_backup/images/` rather than in `YYYY-MM/` month
folders, they simply predate (or postdate) the last organize run. That's cosmetic, not a
problem, and it's reversible:

```bash
python moonglade_backup.py --organize --dry-run   # preview, changes nothing
python moonglade_backup.py --organize             # normalize into YYYY-MM/
```

`--organize` writes `organize_manifest.csv` and `--undo-organize` reverses it, so this is a
safe thing to try.

### Where the space actually goes

Before deleting anything, it's worth knowing the shape of your own backup — on a large
library the answer is almost always "the images themselves", and the reclaimable cruft is a
rounding error by comparison:

```bash
python moonglade_backup.py --catalog-stats
```

**Images you've already deleted are counted separately, not as part of the library.** A
gallery delete moves the file into `pixai_backup/_deleted/` rather than destroying it (see
[Deleting & Sync](Deleting)), so it is still real bytes on your disk — but it is not part
of your collection any more, and folding it into "Image files on disk" inflated the exact
number you are reading this screen to decide about. It now gets its own line with its own
size and where to go and reclaim it:

```
  + 412 soft-deleted in _deleted/ (1.9 GB) -- purge in the gallery's Trash to reclaim
```

The line only appears when there is something in there. `--count` reports the same split
under its **On disk** heading.

> **A note on where your library lives.** By default `pixai_backup/` sits *inside* the
> install folder, which is why the app directory looks enormous. Nothing requires that —
> `--out` points anywhere you like, and keeping the library on a separate path (or drive)
> makes the app folder itself small, easy to back up, and easy to replace wholesale when you
> update.

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
python pixai_gallery_backup.py --update                    # stops when it reaches what you have
python pixai_gallery_backup.py --update --workers 8        # more concurrency
python pixai_gallery_backup.py --workers 8 --page-size 500 # fast full backfill
```

- `--workers N` (default 4) = how many images download at once. 6–8 saturates most
  connections; composes with every flag.
- `--update` stops after `--update-grace` consecutive already-on-disk pages (default
  2). To backfill items missing from the **middle** of your history, run **without**
  `--update` (it only reaches the newest items).
- The progress total comes from your catalog (instant). `--accurate-count` forces a
  full-history API count.

## Full metadata

```bash
python pixai_gallery_backup.py --full-meta            # on new downloads
python pixai_gallery_backup.py --backfill-full-meta   # fill existing catalog rows
```

Captures the complete prompt, seed, steps, sampler, CFG, human-readable model name,
and LoRAs.

## Videos & published artwork

```bash
python pixai_gallery_backup.py --sync-videos          # back up image-to-video mp4s
python pixai_gallery_backup.py --sync-artworks        # published titles/tags/likes/aesthetic
python pixai_gallery_backup.py --sync-artworks --with-videos
```

## Importing your own media

```bash
python pixai_gallery_backup.py --import-local         # catalog files dropped into the backup
python pixai_gallery_backup.py --import-local <DIR>   # copy an external folder in
```

Tagged `source='local'`; videos get an ffmpeg poster if available. Shows under
**Source → Imported** in the gallery.

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

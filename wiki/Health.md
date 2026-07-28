# Collection Health

The **`/health`** page is your analytics dashboard over `catalog.db`:

- Storage used, **Full-meta %** and **Model known %**, missing files, uncataloged files,
  total likes.

> **Two coverage numbers, not one.** *Full-meta* counts rows that have a prompt. *Model
> known* counts rows that have a model id — which only ever comes from a per-task detail
> fetch, and is what an image-view upscale needs. They can differ enormously: a catalog can
> read 98% full-meta while 1% of its rows can say which model made them, because a prompt
> and a seed can arrive without the rest. If the second number is low, run
> `--backfill-full-meta`. Locally imported files are left out of *Model known* — they have
> no PixAI task behind them, so they can never carry a model.
- Images-by-month.
- Top models, top LoRAs, top tags.
- A prompt word-cloud.

Reach it from the gallery header (**♡ Health**) or
`http://127.0.0.1:5000/health`.

## Uncataloged files

**Uncataloged** counts media files that physically exist in your backup folder but have
no row in `catalog.db` at all — the mirror image of "missing files" (a catalog row with
no file). This happens when files land on disk outside the normal backup flow. When the
count is nonzero, `/health` shows a note pointing at the fix: the gallery's **↑ Import**
button, or `python moonglade_backup.py --import-local` from the CLI — both catalog
any not-yet-known file it finds (see [Backing Up → Importing your own media](Backing-Up)).

**Opening a row whose file is gone tells you that.** A catalog row can outlive its file —
that's exactly what **Missing files** counts — and clicking through to one now says
"Video file not found on disk." in place of the player. Images have always degraded to
that line; videos used to draw a player over a 404 instead, which reads as a broken app
rather than a missing file, on the one screen you reached *because* Health told you
something was missing.

## Duplicates review

**`/duplicates`** shows cross-folder duplicate copies side-by-side before you dedup
(linked from `/health`). For the filesystem-level audit/dedup tooling, see
[Backing Up → Duplicate audit](Backing-Up).

## Thumbnails & health accuracy

Thumbnails are 768px JPEGs cached under `gallery/thumbs/` (videos get an
ffmpeg-extracted poster frame when `ffmpeg` is on PATH, and stay blank if it
isn't). Health resolves video/local rows by filename, so they aren't reported as
false "missing". Regenerate thumbnails any time:

```bash
python moonglade_gallery.py --out pixai_backup --rebuild-thumbs
```

---

*More metrics are planned for a future release.*

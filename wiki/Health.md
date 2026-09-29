# Collection Health

The **Health** overlay (the ♡ Health pill in the gallery header) is your analytics dashboard over `catalog.db`:

- **Full-meta %** and **Model known %**, missing files, uncataloged files, total likes.
- **Storage used**, drawn as stacked bars (below).

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
the ♡ Health pill in the gallery header.

## Storage used

The old single "Storage used" number is now a row of stacked bars, each one a different way of
cutting the same pictures. Sizes are the bytes each picture's file takes on disk (videos included).

- **By type** — images, videos, and **Loom renders**, coloured to follow your skin: images take the skin's accent, videos a darker tone of the same accent, and Loom renders are always the Loom's cyan, whichever skin is on. A
  Loom render is a picture or clip [The Loom](The-Loom) made, whether it is a still or a video, so
  the three add up to the whole with nothing counted twice.
- **By model** — your four biggest models by size, and **Other** for the rest (and for pictures whose
  model was never recorded).
- **By collection** — your four biggest hand-picked [collections](Collections) and **Other**. A
  picture in two collections counts in both, so this bar is marked **can overlap** and its
  segments are shares of *each other*, not of the library.

**Click a segment (or its name under the bar) and the gallery opens filtered to it** — the type,
the model or the collection, starting over from the whole library. **Other** is "everything not
named", so it doesn't open anything. On a phone the same bars are on the Health screen (☰ Menu →
Health) and a tap does the same.

The bars count pictures that are in your catalog *and* on disk. A file that is in the folder but
not in the catalog counts under **Uncataloged** below, and a catalog row whose file is gone counts
under **Missing files**; neither has a size to add here. The Loom split follows the Loom's saved
boards, so a shot rendered a minute ago is counted at the next re-measure (see *How fresh are these
numbers?* below).

## Uncataloged files

**Uncataloged** counts media files that physically exist in your backup folder but have
no row in `catalog.db` at all — the mirror image of "missing files" (a catalog row with
no file). This happens when files land on disk outside the normal backup flow. When the
count is nonzero, Health shows a note pointing at the fix: the gallery's **↑ Import**
button, or `python moonglade_backup.py --import-local` from the CLI — both catalog
any not-yet-known file it finds (see [Backing Up → Importing your own media](Backing-Up)).

**Opening a row whose file is gone tells you that.** A catalog row can outlive its file —
that's exactly what **Missing files** counts — and clicking through to one now says
"Video file not found on disk." in place of the player. Images have always degraded to
that line; videos used to draw a player over a 404 instead, which reads as a broken app
rather than a missing file, on the one screen you reached *because* Health told you
something was missing.

## Duplicates review

**Duplicate Review** (opened from Health's Duplicates tile) shows cross-folder duplicate copies side-by-side before you dedup. For the filesystem-level audit/dedup tooling, see
[Backing Up → Duplicate audit](Backing-Up).

## How fresh are these numbers?

Health measures the library by walking every file on disk, so on a large collection that is
real work. It is cached, and the caching is arranged so you never see a stale number and
rarely wait for a fresh one:

- **The server keeps the last measurement** and hands it back instantly for as long as
  nothing has moved. The moment anything writes to `catalog.db` (a sync, an import, a
  delete), the cached answer is dropped — no timer, no waiting for a window to expire.
- **Changes you make on disk count too.** Half of what Health reports is read off the folder
  rather than the catalog — how many files there are, how much space they take, what is in
  each folder, the duplicate counters, and the two drift numbers. Delete a picture in
  Explorer or drop one in by hand and the next open notices, with nothing having written to
  the catalog at all.
- **And it re-measures at least every ten minutes** even when nothing looks like it moved,
  so a change too deep for the quick check to see (an edit inside a batch folder, a file
  replaced under the same name) can never sit there indefinitely.
- **When something has changed**, the next open still answers immediately with the previous
  numbers and re-measures in the background, so a fresh set is ready the next time you look.
  Only the very first open of a server session can ever wait — and the server pre-measures
  once at startup so that one usually doesn't either.
- **Reopening any overlay** (Health, Folio, My Art, Contests, the Panel) paints the last
  numbers you saw straight away and refreshes them behind, rather than showing an empty
  panel while it loads.
- **Force a re-measure** any time by closing and reopening after a sync, or by reloading the
  page.

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

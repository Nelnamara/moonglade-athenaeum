# Collection Health

The **Health** overlay is your analytics dashboard over `catalog.db`:

- **The tiles**: **Images on disk**, **Catalog rows**, **Full-meta**, **Model known**, **Rated**,
  **Published**, **Total likes**, **Duplicates**, **Reclaimable**, **Missing files**,
  **Uncataloged**, **Zero-byte files**, **Missing thumbs** and **Last verified** (the last three
  are explained under *Library integrity* below).
- **Storage used**, drawn as stacked bars (below).
- Images by month, **Top models**, **Top tags & contests**, **Top LoRAs**, and a **Prompt word cloud**.

> **Two coverage numbers, not one.** *Full-meta* counts rows that have a prompt. *Model
> known* counts rows that have a model id — which only ever comes from a per-task detail
> fetch, and is what an image-view upscale needs. They can differ enormously: a catalog can
> read 98% full-meta while 1% of its rows can say which model made them, because a prompt
> and a seed can arrive without the rest. If the second number is low, run
> `--backfill-full-meta`. Locally imported files are left out of *Model known* — they have
> no PixAI task behind them, so they can never carry a model.

Reach it from **Health** in the row of destinations under the gallery's banner (on a phone,
**☰ Menu → Health**).

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
button, or `python -m moonglade --import-local` from the CLI — both catalog
any not-yet-known file it finds (see [Backing Up → Importing your own media](Backing-Up)).

**Opening a row whose file is gone tells you that.** A catalog row can outlive its file —
that's exactly what **Missing files** counts — and clicking through to one now says
"Video file not found on disk." in place of the player. Images have always degraded to
that line; videos used to draw a player over a 404 instead, which reads as a broken app
rather than a missing file, on the one screen you reached *because* Health told you
something was missing.

## Duplicates review

**Duplicate Review** (opened from Health's Duplicates tile) shows cross-folder duplicate copies side-by-side before you dedup.
In the **Same seed** and **Near-duplicate** groups the members are different pictures, so a
member PixAI no longer has (gone from your PixAI history as of the last check) is the only
copy of its picture. It goes with the rest, named first: its pill reads *✕ remove · only
copy*, **Resolve** says how many are only copies, and the **Auto-resolve all** confirm (and,
on a phone, the Resolve confirm) says *"2 of these are the only copy — PixAI no longer has
them."* **Undo** puts the file and its catalog row back. The byte-identical groups have
nothing to warn about — the copy you keep has the same bytes. For the filesystem-level audit/dedup tooling, see
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

## Library integrity

The tiles above count files; they do not look inside them. A file that is on disk but empty, or
cut short by an interrupted download, still counts under **Images on disk** and keeps its row
out of **Missing files**. Three tiles cover that:

- **Zero-byte files** — empty files in the library, counted every time Health measures.
  They still count in **Images on disk** and **Missing files** keeps its meaning; this tile
  says it plainly instead.
- **Missing thumbs** and **Last verified** — read from the last integrity check: **Control
  Panel → Check — read-only → Verify library integrity → run ▸** (or
  `python -m moonglade --verify-library`). They show "—" and "never" until it has run once.

The check looks at every catalogued file: missing, empty, no thumbnail (or, for a video, no
poster), an empty thumbnail, files with no catalog row, and thumbnails with no row. The Panel's
button also checks the end of each file without opening the picture — a PNG, JPEG, WebP or GIF
that stops before its end marker, or a video with no index, is listed as **suspect: truncated**.
"Suspect" on purpose: the check reads two small pieces of each file and decodes nothing, and an
unusual but valid file can look cut short.

It changes nothing: no file is deleted, moved, downloaded or rebuilt. It writes two reports
at the library root, `integrity_report.csv` (one line per problem: media id, problem, path,
size, recoverable) and `integrity_report.json` (the counts and when it ran), and the Panel's log
shows the summary and the first lines. A broken picture that PixAI no longer has says
**recoverable: no** — there is nothing left to download it from again. The check itself
repairs nothing; the **Broken files** list below is where you act on what it found.

### Broken files

When the last check found broken files, Health shows a **Broken files** section under the tiles
and above the storage bars. It is absent on a clean library. The **Zero-byte files**,
**Missing thumbs** and **Missing files** tiles turn peach while the list has rows of their kind,
and clicking one jumps to the list with that kind picked (**Missing files** opens it at **All**). **Control Panel → Check — read-only → Verify library
integrity** says "N broken · Review ▸" after a check that found some; that opens Health at the
list too.

The chips across the top are **All**, **Zero-byte**, **Thumbnail**, **Suspect** and **Lost**,
each with its count (a chip with nothing under it is hidden). A file that is missing altogether
has no chip of its own: it is listed under **All** (and under **Lost** if PixAI no longer has
it), reading "missing · <where the catalog expects it>". Each row shows the picture's
thumbnail (or a "?"), its id, the problem and where the file is, its size ("size unknown" for a
missing file, since the catalog doesn't record one), and a pill:

- **RECOVERABLE** — a missing or empty file PixAI still has, or a missing or empty thumbnail.
- **SUSPECT** (peach) — a file that stops before its end. "Suspect", never "corrupt": the
  check reads two small pieces of the file and decodes nothing.
- **LOST** (dashed) — a broken file PixAI no longer has, or one you marked lost. A picture
  PixAI no longer has also wears **ARCHIVE**, the same word the gallery uses, and its row says
  "Broken here, and gone from your PixAI history as of <date>. There's no copy left to
  re-download." The date is when the archive-only flag was last rewritten by a sync. If a
  later sync finds the picture on PixAI again, the row turns back into **RECOVERABLE**.

A row offers only the fix that applies to it (**Re-download** or **Rebuild**, see below) and a
**⋯** menu with **Open details**, **Mark lost** and **Copy path**. A LOST row never offers a
re-download; it offers **Open details** and **Keep as is**, which quiets it.

**Mark lost** and **Keep as is** are a note this app keeps for itself, in
`integrity_marks.json` at the library root beside the two reports. They delete nothing and
change nothing else, a lost row stops being counted for **Fix all**, and the toast that
confirms either one has an **Undo** for ten seconds.

#### Fixing a row

A row's own button runs straight away, with no confirm, because it is one file:

- **Re-download** asks PixAI for the picture again, once, the same way a backup does. The new
  copy is checked before it goes anywhere: it has to be a whole file of the same kind as the
  broken one. Only then does it replace the broken file, under the same name. A missing file
  goes back where the catalog expects it (a bare file name means the `images/` folder, or
  `videos/` for a clip), and only if that place is inside the library and holds nothing yet. If PixAI sends
  nothing, or what it sends doesn't check out, the old file is left exactly as it was and the
  row says so in peach.
- **Rebuild** makes the thumbnail again from the file on your disk. Nothing reaches PixAI.

Nothing in the list deletes or quarantines a file. A picture PixAI no longer has is never
re-downloaded — the app refuses it on the server whatever the screen asks — and with
`READ_ONLY` on, re-downloads are off (thumbnails can still be rebuilt). When a fix finishes, the
row shows **✓ FIXED** for two seconds and leaves the list, and the rows that were fixed are
checked again so the tiles and the report follow.

#### Fix all recoverable

The section's **Fix all recoverable (N)** button counts the missing, empty, cut-short and thumbnail rows
that can be fixed — never a LOST row, never a picture PixAI no longer has — and asks once:
how many files it will re-download from PixAI and about how much that is, how many thumbnails
it will rebuild here, how many lost files it leaves alone, and "Nothing is deleted." On a phone
whose Data saver is on over a metered connection, it says that too. With `READ_ONLY` on it
counts only the thumbnails.

While it runs, the section's header reads "5 / 12 fixed" with the moon filling as files finish,
and a **Stop** that lets the current file finish and then stops (nothing is rolled back). The
file being downloaded shows how many of its bytes have arrived. You can close Health: the run
carries on, the Activity window shows it as "Fixing 12 files · 5 / 12", and clicking that line
brings you back to the list. When it ends a note says what happened ("Fixed 11 of 12. 1
couldn't be re-downloaded.") with **Show**, and Health's tiles measure again.

#### On a phone

In **☰ Menu → Health** the **Zero-byte files**, **Missing thumbs** and **Missing files** tiles
turn peach the same way, and a **Broken files** row under the tiles (with "12 · 1 lost ›") opens the list as its own
screen; tapping a peach tile opens it at that kind. The chips scroll sideways, and tapping a row
opens a sheet with what applies to it: **Re-download** or **Rebuild**, **Open details**, and
**Mark lost** (a LOST row's sheet says why, and offers **Keep as is** instead). **Fix all
recoverable (N)** stays at the foot of the screen and confirms in a sheet with the same lines as
the desktop. While it runs, the top of the screen shows "n / N fixed" with the moon and **Stop**,
and the Activity sheet shows the run. The phone's **Control → Check — read-only** row says
"N broken · Review ▸" too.

## Thumbnails & health accuracy

Thumbnails are 768px JPEGs cached under `gallery/thumbs/` (videos get an
ffmpeg-extracted poster frame when `ffmpeg` is on PATH, and stay blank if it
isn't). Health resolves video/local rows by filename, so they aren't reported as
false "missing". Regenerate thumbnails any time:

```bash
python -m moonglade.gallery --out pixai_backup --rebuild-thumbs
```

---

*More metrics are planned for a future release.*

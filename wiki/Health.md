# Collection Health

The **`/health`** page is your analytics dashboard over `catalog.db`:

- Storage used, full-meta coverage %, missing files, uncataloged files, total likes.
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
button, or `python pixai_gallery_backup.py --import-local` from the CLI — both catalog
any not-yet-known file it finds (see [Backing Up → Importing your own media](Backing-Up)).

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
python pixai_gallery.py --out pixai_backup --rebuild-thumbs
```

---

*More metrics are planned for a future release.*

# Collection Health

The **`/health`** page is your analytics dashboard over `catalog.db`:

- Storage used, full-meta coverage %, missing files, total likes.
- Images-by-month.
- Top models, top LoRAs, top tags.
- A prompt word-cloud.

Reach it from the gallery header (**♡ Health**) or
`http://127.0.0.1:5000/health`.

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

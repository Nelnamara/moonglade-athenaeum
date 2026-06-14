# CLAUDE.md — Project Context for Claude Code

This file is committed so it is available on every machine that clones the repo.

---

## Project Overview

**PixAI Gallery Backup** — bulk-downloads a user's PixAI.art generations at full resolution, keeps a searchable SQLite catalog, and serves a local web gallery.

Three main files:
- `pixai_gallery_backup.py` — CLI downloader (Apollo persisted GraphQL GET, backward pagination)
- `pixai_gallery.py` — Flask gallery server + all SQLite catalog helpers
- `pixai_gui.py` — PySide6 desktop GUI wrapping the CLI

---

## Architecture Notes

- **Catalog**: `catalog.db` (SQLite), auto-migrated from `catalog.csv` on first run. All catalog I/O goes through helpers in `pixai_gallery.py` — never raw SQL elsewhere.
- **Schema migrations**: Added via `_MIGRATIONS` list in `_connect()` and explicit `ALTER TABLE` in `init_db()`. New columns always go in `_MIGRATIONS` AND in `_CREATE_TABLE` AND in `CATALOG_FIELDS`.
- **Flask app**: `create_app(out_dir)` factory in `pixai_gallery.py`. All templates are module-level string constants (BASE_HTML, INDEX_HTML, DETAIL_HTML). Restarting just the gallery thread in the GUI is NOT enough to reload Python module changes — requires full GUI restart.
- **GUI module cache**: `pixai_gui.py` imports `pixai_gallery` at module level. Schema changes require full GUI restart to take effect.
- **`_IMAGE_EXTS`**: Defined once in `pixai_gallery.py`, imported by `pixai_gallery_backup.py`. Do not redefine locally.

---

## Critical Constraints

- **NEVER** append `Co-Authored-By: Claude` trailers to commits.
- **NEVER** commit `config.json` — it is git-ignored and contains real user credentials (USER_ID, U3T, hashes).
- `token.txt` is also git-ignored.
- No real credentials or user-specific values should appear in any committed file.

---

## Key API Details (PixAI / Apollo)

- Uses Apollo persisted GraphQL GET (not POST) for `listUserTaskSummaries`
- Backward pagination: `before` cursor, `hasPreviousPage` / `startCursor`
- `getTaskById` for full meta (prompt, seed, steps, sampler, CFG, model)
- `getGenerationModelByVersionId` for human-readable model name
- All hashes captured from browser DevTools → stored in `config.json` (never committed)

---

## Current Version

`1.1.0` — on `master`. Development continues on feature branches.

## Test Suite

81 pytest tests in `tests/`. Run with `python -m pytest`. All tests must pass before merging.

---

## Owner

Nelnamara / Kil'jaeden — Balance Druid, WoW addon dev, PixAI user.

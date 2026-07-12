# Changelog

All notable changes to **Moonglade Athenaeum** — *a library against the Void.*

Format loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are
git tags. Full prose notes for tagged versions live on
[GitHub Releases](https://github.com/Nelnamara/moonglade-athenaeum/releases).

> **Maintenance note.** This file is the in-repo source of truth — **update the `[Unreleased]`
> section with every change, and cut it into a dated version block when you tag a release.**
> GitHub Releases were published through **v1.6.0**, then paused; **v1.8.0–v1.10.0 were tagged but
> never released** — their notes are reconstructed here from tag messages + git history and are being
> back-published. There is **no v1.7.x** (the series jumped 1.6.0 → 1.8.0).

## [Unreleased]

_On `loom-v2`, past the `v1.10.0` tag. Headline work; see git history for the full list._

### Added
- **The Loom V2** — a dockable-panel storyboard workspace (Acts & Shots board, runtime reel,
  Cast / Legend / Footage panels, timeline preview, and per-shot Generate tabs with
  continuity / camera / lighting), behind a **non-breaking "V2 layout" toggle** wrapped in an error
  boundary that falls back to the classic Loom. The **Video** and **Image** generate tabs are
  live — the Image tab generates a reference still for the selected shot (model picker +
  shot-seeded prompt over `/api/generate`, free-card aware) and **routes the result into the
  shot's open/close frame or cast**, so an in-Loom gen directly feeds the video render. Edit /
  Reference tabs still pending.
- **Multiple storyboards in the Loom** — the Loom is no longer single-project. Each storyboard
  is saved under its own key in the existing server-side store (`storyboard:v2:proj:<id>`), with
  a header **switcher** (New · Open · Duplicate · Delete; Rename via the name field) and an
  active-project pointer. Your existing project is **migrated in automatically** as the first
  storyboard on load; the legacy single-key project is preserved untouched as a backup. Verified
  end-to-end on a copy of real store data (migrate → new → switch, content intact).
- **Achievements art & moments** — 11 achievement-badge prompts + the Loom mark, a
  mascot-per-state activity tracker, a rarity-scaled "Nel presents" unlock pop with real badge art,
  a spinning-Nel generation loader, and a Konami-code Starfall easter egg.
- **Recover a task by ID** — a Control Panel action to import any generation/edit into the catalog
  by task id, with an "already in your gallery" check + jump link.
- **Edit card** — multi-image references (Edit Pro 4 / Reference Pro 10) and
  capability-clamped resolution/quality/aspect (fixes the 4K-on-unsupported-model bug).
- **Economy surface** — distinct credits/cards chip, claimable badge, and credit expiry/cliff warnings.
- **Mobile portrait pass** — responsive layout ≤480px across header, grid, filters, drawer, lightbox.

### Changed
- **`--sync` is now the full one-shot refresh** — pull + full-meta → fix-models → backfill →
  **build missing thumbnails → reconcile cloud-deletes**, all idempotent (previously stopped after
  backfill). Reconcile is advisory and caught with a deliberately **broad `except Exception`** so a
  transient network error during its feed scan can't sink an otherwise-successful backup. Guarded by
  `tests/test_sync.py`; documented in `CLAUDE.md → "The one-shot sync (--sync)"`.

### Docs
- **State of the Suite** — code-verified status assessment (`docs/STATE_OF_THE_SUITE_2026-07-10.md`
  + `docs/state-of-suite.html`); corrected the stale `docs/REFINEMENTS.md` "Next up" list; started
  this changelog file.

## [1.10.0] - 2026-07-05 — Consolidation release
- **Live event push** — `--watch` / `--watch-backup` (graphql-transport-ws `personalEvents`,
  auto-collect finishing gens) **plus an in-server live-mirror watcher** (gens land locally the
  instant they finish; no separate CLI process).
- **Control Panel** — live progress bar (MGPROG protocol), Stop-this-job cancel, hourly scheduler.
- **Server control** — Stop/Restart from the browser via the `Serve Gallery.pyw` supervisor
  (exit-42 relaunch, single-instance guard, `serve.txt` args, `serve.log`).
- **Branding system** — choosable banner mark + 15 animations, frosted-pill nav, Desktop launcher `.lnk`.
- **Community** — contests (`--contests` / `/api/contests`), achievements + earnable skins,
  "Your Art" views + account entitlements.
- **Fixes** — batch under-capture (saved the grid, not the images), catalog-stats thumbnail
  double-count, `USER_ID` auto-resolve in `--sync-artworks`; CSV export is a real browser download;
  balance chip caches last-known credits.

## [1.9.1] - 2026-07-03
- **Jobs tray** (tasks survive drawer close), header **balance chip**, **Suggest-prompt** button,
  **prompt snippets/favorites**, and **printing** (print-friendly detail view + contact sheets).
- Sanitized reverse-engineering mechanism detail out of the public docs/wiki.

## [1.9.0] - 2026-07-03 — The web creation suite
- **Generate / Edit / Video drawer** — dockable to any screen edge, model/LoRA flyout with hover
  preview cards, LoRAs as attachments (not model overrides), Tag Suggestions in every prompt box.
- **Picker** — 900px modal browsing the whole catalog (infinite scroll), Collection/Source/Rating/Sort
  filters, upload, copy-prompt-on-pick.
- **Gallery → create bridges** — lightbox actions, right-click menu, multi-select → Video;
  Edit tab Edit | Enhance | Fix sub-tabs; eclipse-moon status spinner; in-app quick guide + full manual.

## [1.8.3] - 2026-07-03 — Claimable rewards
- `--claims` / `--claim` via `/v2/claim` (daily credits / agent stamina; read-only list, gated claim).

## [1.8.2] - 2026-07-03 — Image-to-prompt
- `--suggest-prompt` via `/v2/tag/suggest-prompt` (image → Danbooru-style tags + description; free).

## [1.8.1] - 2026-07-03 — Real credit cost in previews
- `price_task` via `/v2/task-price` — a generation's real credit cost, computed without creating it.

## [1.8.0] - 2026-07-03 — Full create suite + free-card auto-apply
- The complete create surface on one `createGenerationTask`: `--generate`, `--edit-image`,
  `--generate-video` (i2vPro), `--reference-video` (multi image/video/audio), `--enhance`
  (panelplugin workflows: face-fix / upscale / bg-remove + art filters), `--upload`.
- Free **"kaisuuken" cards auto-apply** on `--confirm` via the `/v2/kaisuuken` REST surface;
  `--dump-params` banks a submit shape with no browser; server-authoritative cost (`paidCredit`).
- GUI Video / Ref Video / Edit tabs; gallery detail → creation bridges. Cross-machine protocol +
  pinned line endings (`.gitattributes`).

_(No v1.7.x — the series jumped from 1.6.0 to 1.8.0.)_

## [1.6.0] - 2026-06-28 — Curation + one-key setup
- **Collections** (images + videos), **select-mode + drag-paint** multi-select, scroll/selection
  persistence, detail-page keyboard nav.
- **One-key setup** — `config.json` is just `PIXAI_API_KEY`; `USER_ID` auto-resolves and the
  persisted-query hashes ship as built-in defaults.
- Fixed a JS error that killed the entire gallery script; added a `node --check` regression guard.

## [1.5.0] - 2026-06-27 — Moonglade Athenaeum 🌙
- **Rebrand** from "PixAI Gallery Backup" to a full local PixAI client (back up · browse · generate · curate).
- **`gql_adhoc()`** ad-hoc GraphQL POST — most ops need no persisted-hash capture; read-only `--account` dashboard.
- **Image generation** (`--generate` / Generate tab) with model + LoRA pickers, quality mode,
  priority, prompt-helper, aspect presets, `--task-id` recovery.
- **Manage & curate** — delete-from-PixAI (cloud + local), `--reconcile-deleted`, `--import-local`;
  Organize rebuilt into reversible `YYYY-MM/` month folders.

## [1.4.4] - 2026-06-24 — Media-type filter (All / Images / Videos).
## [1.4.3] - 2026-06-24 — 768px thumbnails (q90) for high-DPI displays.
## [1.4.2] - 2026-06-24 — Sharper thumbnails (512px / q90).
## [1.4.1] - 2026-06-24 — Video gallery fixes — posters generated during `--sync-videos`; click-to-play.
## [1.4.0] - 2026-06-23 — Image-to-video backup — `--sync-videos` downloads the real mp4 + gallery playback (`/video-file/<id>`, range support).
## [1.3.2] - 2026-06-23 — Fuller metadata (negative prompt, clip-skip), `/duplicates` review page, inline + bulk prompt editing.
## [1.3.1] - 2026-06-22 — Parallel workers (`--workers N`, default 4) for the batch jobs, not just downloads.
## [1.3.0] - 2026-06-22 — API-key auth, `--sync-artworks` (published metadata), LoRA tracking, dashboards, mobile/PWA, animated-artwork backup.
## [1.2.0] - 2026-06-22 — Duplicate audit/dedup (`--audit` / `--dedup` / `--verify-dupes`), gallery overhaul, parallel downloads + instant O(1) resume + incremental `--update`.
## [1.1.0] - 2026-06-13 — SQLite catalog (`catalog.db`, auto-migrate from CSV, `--export-csv`); SQL-backed gallery (~20× faster on large libraries); batch filter.
## [1.0.0] - 2026-06-13 — Initial release — bulk-download your own PixAI generations (backward pagination, media resolution, resume-by-media-id, catalog + prompt sidecar).

[Unreleased]: https://github.com/Nelnamara/moonglade-athenaeum/compare/v1.10.0...HEAD

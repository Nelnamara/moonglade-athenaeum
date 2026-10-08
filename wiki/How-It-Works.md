# How It Works

The Python modules below sit around one SQLite catalog, with the Loom's JS surface and the gallery's React front end on top.

```
moonglade/                the app's code (since 3.20), one package:
  backup.py               CLI engine: download, organize, generate, sync, delete, reconcile
                          (run it as `python -m moonglade`)
  gallery.py              Flask web gallery + ALL SQLite catalog helpers (the shared base)
                          (the launcher, Moonglade Launcher, runs it as `python -m moonglade.gallery`)
  similar.py              "more like this" sidecar: CLIP embeddings in Pixeltable (optional dep)
  mcp_server.py           local stdio MCP server: curation tools over the catalog, a duplicate
                          finder, and a read-only PixAI tag-suggestion tool
  recipes.py              PixAI recipes: the market, Mine and Sets, the creator, and attaching
                          recipes to a generation
  inbox.py                PixAI's inbox (the ✉ button) and the gift box's gifts and current
                          event (🎁), a published work's comments and your replies
  runs.py                 the prompt template (`{a|b}` variables, saved lists), Random and Matrix
                          runs, and the Runs store behind Inspect
  contest_wins.py         what counts as a verified contest win and when it is checked
  integrity.py            the read-only library integrity check (--verify-library) behind
                          Health's Zero-byte / Missing thumbs / Last verified tiles, and
                          Health's Broken files list: its local marks and its targeted
                          re-download / thumbnail-rebuild run
  curation_io.py          the curation sidecar: --export-curation / --import-curation and the
                          Control Panel's Download curation (JSON)
  paths.py                where the app's own files are: every app-folder path comes from here
  settings.py             local/settings.json: everything the app writes for this install
  setup.py                what every way of starting Moonglade runs first: the move below,
                          then the library to open
  migrate.py              the move: brings an older install's files into their homes, once
  outside.py              finds and fixes what outside the app still names the old files
                          (scheduled tasks, Claude tools registrations, shortcuts)
  logs.py                 the always-on log file, local/logs/moonglade.log
  manifest.json           which art pack this build wants, and where to fetch it
loom/                     The Loom's JS surface: esbuild bundle + its own `node --test` suite
```

Before 3.20 these were flat files beside the launcher (`moonglade_backup.py`,
`moonglade_gallery.py` and so on). They are gone: the launcher is the one Python file left
beside the program. A scheduled task, a Claude tools registration or a shortcut that still
names an old file is found by the app, which offers to fix it (**Fix it** or **Fix them** on its
notice), and a shortcut to the old launcher is re-pointed by itself the first time the new
launcher starts.

The CLI engine and the MCP server both import `moonglade/gallery.py` for catalog access — so
catalog logic lives in exactly one place. The two surfaces are the CLI and the web gallery:
the Loom, Control Panel, achievements, collections, and contact sheet are browser-only.
`--watch` and `--claims` have web equivalents too, not CLI-only surfaces: the gallery runs
its own always-on live-mirror watcher (Control Panel → **Live Mirror** status dot, backed by
`/api/watch/status`) and a header **claim** button (`/api/claim`) for daily rewards.

Two of the MCP tools report their own limits rather than papering over them, because an
agent can't see the gallery and has only the answer to go on:

- **`similar`** can return fewer neighbours than you asked for. The CLIP index and the
  catalog are separate stores, and deleting an image doesn't reach into the index — so a
  nearest-neighbour hit can point at a row that no longer exists. Those used to be dropped in
  silence, which made `count: 15` on a request for 24 read as *your library only has 15
  similar images*. The reply now carries `stale_index_entries` (and the ids in
  `stale_media_ids`) plus a note saying the shortfall is index drift, not a shortage — and
  that rebuilding clears it: `--rebuild-similar`, or the Control Panel's
  **Rebuild the Similar index** job. The tool doesn't clear them itself; a rebuild re-embeds
  the whole library and can take a long while, so it stays your call rather than a side
  effect of a lookup.
- **`set_rating`** returns `ok: false` for a `media_id` that isn't in the catalog. The write
  is a plain update, so a mistyped or stale id matched nothing and reported success anyway —
  which is how an agent working a review queue marks an image done and leaves it unrated
  forever.

## How it talks to PixAI — and why setup is just one key

PixAI has no official public API for managing your own work, so some operations
(listing your history, task detail, delete) reuse PixAI's own frontend interfaces.
The practical upshot:

- **Your API key is the only credential.** Your `USER_ID` is auto-resolved from it,
  and the persisted-query hashes ship with working defaults — so setup is just the key.
- **The hashes are not secrets.** They identify PixAI's own frontend operations and
  rarely change. If a PixAI frontend update ever breaks one, you'll get a clear error
  and can update that one value — see [Troubleshooting](Troubleshooting).
- **The legacy browser token is retired** — only a fallback for users without an API key.

## Media URLs
Task summaries carry `mediaId` / `batchMediaIds`, not URLs. Full-res comes from
`GET /v1/media/<id>` (variant `PUBLIC`). Videos expose their mp4 via the GraphQL
`media` object's `fileUrl` (REST returns an empty `urls[]` for videos).

## The catalog (`catalog.db`)
SQLite, one row per media, keyed by `media_id`. All I/O goes through helpers in
`moonglade/gallery.py`. Schema migrations live in **three places**: `CATALOG_FIELDS`,
the `_CREATE_TABLE` DDL, and `_MIGRATIONS`. `migrate()` runs them once per process, on the first `catalog()`
open for a path and memoized after, so existing DBs still auto-upgrade on first touch. Columns span identity/timing, full meta (prompt/seed/steps/sampler/
cfg/model/loras/negative/clip-skip), published-artwork data, video fields, `source`
(online/api/local), and `deleted_remote`.

## On-disk layout
```
pixai_backup/
├─ images/            flat downloads (pre-organize)
├─ 2024-03/           organize: month folders, descriptive names
├─ videos/  imported/ backed-up + imported media
├─ gallery/thumbs/    768px JPEG thumbnails (immutable cache)
├─ _duplicates/       quarantine from --dedup (reversible)
├─ _deleted/          quarantine from a gallery delete (reversible)
├─ catalog.db         the source of truth
└─ _moonglade/        your stuff, kept by the app (3.20; every scan of the library skips it)
   ├─ accounts/<key>/    one folder per login: its settings, presets, snippets, Toolbox
   │                     presets and saved views (your pinned goal, saved lists, recipe row
   │                     and drafts, and your answers to the first-run guide)
   ├─ loom/              the Loom's storyboards, beds and exports
   ├─ records/           achievements.json (earned achievements, earn dates, the skin),
   │                     telemetry.json (achievement counters), jobs.jsonl (the Control Panel's
   │                     job log), schedule.json, train_guard.json (the training spend guard),
   │                     runs.db (each multi-send's template and the exact request it sent),
   │                     raw_tasks.jsonl, and the reports: integrity_report.csv/.json,
   │                     audit_report.csv, verify_report.csv
   └─ decisions/         what you decided and must never lose: your Mark-lost choices,
                         organize_manifest.csv (the --undo-organize list), a curation import's
                         undo file
```

Beside the program, this PC's own things sit in `local/`: `settings.json` (everything the app
writes for this install: the library folder, host and port, LAN discovery, the Mirror switch,
the launch switches and the branding picks), `mirror_session.json`, the art pack
(`moonglade.mgpack` + `.version`), `icons/` (the shortcut icons), `banners/` (a worn banner that
is the only copy), `cache/` (badge thumbnails, masks and banner renders, all rebuildable) and
`logs/` (`serve.log` and `moonglade.log`). `config.json` stays beside the program and holds only
what a person types: the key, the logins, `READ_ONLY` and the overrides.

An older install (3.17 to 3.19) is brought into this layout the first time 3.20 starts: the
settings are merged into `settings.json` (each step of the merge journalled, so a cut-short
merge resumes with what `settings.json` holds), then each file is moved. On one drive that is a
single rename, journalled first; across drives each file is copied beside its new home, checked
(sha256; a database by `PRAGMA integrity_check` and its row counts), swapped in and recorded in a
journal, and only then deleted from its old place, so an interrupted start is finished by the
next. A copy keeps its file's own time, so where two copies meet, "keep the newer" means the one
really changed last. Before every start that moves anything, a safety snapshot of the small
records it touches is zipped; the app deletes the snapshot after five clean starts, counted by
the gallery once it has served for ten minutes or was stopped cleanly. Only the launcher and the
gallery move a library's files, and only the library this install uses; the command line and the
MCP server refuse a library still in an older layout, and every start stops when an older install
is still writing a library's old places. [Where Things Live](Where-Things-Live) answers the
everyday questions.

**Not shown above — the Pixeltable semantic-search index lives OUTSIDE `pixai_backup/`.**
It's a sidecar CLIP index over `catalog.db` (keyed by `media_id`), but Pixeltable stores
its own embedded-Postgres data at its default home, `~/.pixeltable`
(`%USERPROFILE%\.pixeltable` on Windows) — not under `out_dir`, so it's machine-local and
not part of an `out_dir` backup; a fresh machine rebuilds it rather than restoring it.

## Invariants (don't break)
1. **`media_id` is the last `_`-chunk of the filename stem.**
2. **Resume is keyed on media id, checked before any network call.**
3. **Incomplete/zero-byte files don't count as done**; downloads are atomic (`*.part` → replace).
4. **`catalog.db` is the source of truth.**
5. **The library folder is walked through one scanner** — `scan_library()` for the whole tree and
   `files_for()` for a single media id, in the `LIBRARY SCAN` section, which own what a walk skips and
   which extensions count. The ten callers that each used to walk the tree with their own exclusion set
   (resume, the audit, `--organize`, `--import-local`, the Health page, the disk counter, the Similar
   index and three more) now share it (2026-08-23); `find_files_for_media_id` recognizes both naming
   layouts and rides the same scan.

## Testing
Run `python -m pytest -q dev/tests` from the repo root (the suite and its tools live in
`dev/`) — pure functions, filesystem, catalog, gallery routes, mocked network, embedded-JS
syntax. `dev/tests/test_similar.py` needs the
optional `pixeltable` dep and skips itself cleanly without it. The Loom's pure-logic
modules have their own suite: `node --test` from `loom/`. All must pass before merging.

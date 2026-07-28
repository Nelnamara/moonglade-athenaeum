# How It Works

Four Python modules around one SQLite catalog, plus the Loom's JS surface.

```
moonglade_backup.py   CLI engine: download, organize, generate, sync, delete, reconcile
moonglade_gallery.py          Flask web gallery + ALL SQLite catalog helpers (the shared base)
moonglade_similar.py          "more like this" sidecar: CLIP embeddings in Pixeltable (optional dep)
moonglade_mcp.py          local stdio MCP server: curation tools over the catalog
loom/                     The Loom's JS surface: esbuild bundle + its own `node --test` suite
```

The CLI engine and the MCP server both import `moonglade_gallery.py` for catalog access — so
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
`moonglade_gallery.py`. Schema migrations live in **three places**: `CATALOG_FIELDS`,
the `_CREATE_TABLE` DDL, and `_MIGRATIONS` (run on every connect, so existing DBs
auto-upgrade). Columns span identity/timing, full meta (prompt/seed/steps/sampler/
cfg/model/loras/negative/clip-skip), published-artwork data, video fields, `source`
(online/api/local), and `deleted_remote`.

## On-disk layout
```
pixai_backup/
├─ images/            flat downloads (pre-organize)
├─ 2024-03/           organize: month folders, descriptive names
├─ videos/  imported/ backed-up + imported media
├─ gallery/thumbs/    768px JPEG thumbnails (immutable cache)
├─ branding/          marks, frames, badge thumbs (machine-local)
├─ loom/              the Loom's storyboard store + exports
├─ _duplicates/       quarantine from --dedup (reversible)
├─ _deleted/          quarantine from a gallery delete (reversible)
├─ view_presets/      per-account saved gallery views (<account>.json each)
├─ organize_manifest.csv   reversible move log (--undo-organize)
├─ achievements.json  earned achievements + earn dates
├─ telemetry.json     achievement counters
├─ jobs.jsonl         Control Panel job log
├─ schedule.json      Control Panel scheduled jobs
├─ prompt_snippets.json    saved prompt snippets
├─ toolbox_presets.json    saved Toolbox presets
├─ catalog.db         the source of truth
└─ raw_tasks.jsonl    raw task data
```

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
5. **`find_files_for_media_id` recognizes both naming layouts** — but it isn't one shared
   matcher yet. Only the gallery calls it today; resume, the audit, and `--organize` each still
   walk the tree independently with their own exclusion set. Consolidating onto a single matcher
   is open work, not yet done (see `docs/architecture.md`'s Invariants section for specifics).

## Testing
Run `python -m pytest -q` from the repo root — pure functions, filesystem, catalog,
gallery routes, mocked network, embedded-JS syntax. `tests/test_similar.py` needs the
optional `pixeltable` dep and skips itself cleanly without it. The Loom's pure-logic
modules have their own suite: `node --test` from `loom/`. All must pass before merging.

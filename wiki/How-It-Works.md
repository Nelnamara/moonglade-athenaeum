# How It Works

Three Python modules around one SQLite catalog.

```
pixai_gallery_backup.py   CLI engine: download, organize, generate, sync, delete, reconcile
pixai_gallery.py          Flask web gallery + ALL SQLite catalog helpers (the shared base)
pixai_gui.py              PySide6 desktop app: every workflow as a tab, background threads
```

Both the engine and the GUI import `pixai_gallery.py` for catalog access — so
catalog logic lives in exactly one place.

## How it talks to PixAI — and why setup is just one key

Your API key authenticates against PixAI's **public** GraphQL surface. Probed live,
that surface exposes:

- ✅ `me` (→ your `USER_ID` is auto-resolved), `generationModels` (model search),
  `createGenerationTask` (generation).
- ❌ **Not** your history feed, task detail, or delete — those return *"Cannot query
  field on type Query."*

So the private operations (`listUserTaskSummaries`, `getTaskById`,
`deleteGenerationTask`) are reached by **replaying PixAI's own frontend persisted
queries**, each identified by a `sha256Hash`. The endpoint validates *ad-hoc*
queries against the limited public schema but executes *persisted* (hash-registered)
queries against the full internal schema — a deliberate gateway design.

What this means in practice:

- **The hashes are not credentials.** They're public, per-frontend identifiers (the
  same for every user, embedded in PixAI's JS bundle). The tool **bakes in** the
  current ones, so you don't capture anything.
- **The legacy browser token is dead.** The persisted feed runs on just your API key
  + the hash; `U3T`/`token.txt` are only a fallback for users without an API key.
- Two mechanisms in the code:
  - `gql_adhoc()` — POSTs a full query document; used for `me`, model search,
    generation (public schema).
  - the persisted-query path — GET with `operationName` + `sha256Hash`; used for the
    feed, task detail, delete (private schema).

See [`API_OPERATIONS.md`](https://github.com/Nelnamara/moonglade-athenaeum/blob/master/API_OPERATIONS.md)
for the operation catalog.

## Media URLs
Task summaries carry `mediaId` / `batchMediaIds`, not URLs. Full-res comes from
`GET /v1/media/<id>` (variant `PUBLIC`). Videos expose their mp4 via the GraphQL
`media` object's `fileUrl` (REST returns an empty `urls[]` for videos).

## The catalog (`catalog.db`)
SQLite, one row per media, keyed by `media_id`. All I/O goes through helpers in
`pixai_gallery.py`. Schema migrations live in **three places**: `CATALOG_FIELDS`,
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
├─ _duplicates/       quarantine from --dedup (reversible)
├─ organize_manifest.csv   reversible move log (--undo-organize)
├─ catalog.db         the source of truth
└─ raw_tasks.jsonl    raw task data
```

## Invariants (don't break)
1. **`media_id` is the last `_`-chunk of the filename stem.**
2. **Resume is keyed on media id, checked before any network call.**
3. **Incomplete/zero-byte files don't count as done**; downloads are atomic (`*.part` → replace).
4. **`catalog.db` is the source of truth.**
5. **One shared media-id → file matcher** (`find_files_for_media_id`) recognizes both
   naming layouts, so resume / gallery / audit never drift.

## Testing
195 pytest tests in `tests/` (pure, filesystem, catalog, gallery routes, mocked
network, embedded-JS syntax). `python -m pytest`. All must pass before merging.

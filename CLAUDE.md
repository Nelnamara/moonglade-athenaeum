# CLAUDE.md — Project Context

> This file is auto-loaded by Claude Code as project memory. It explains how the
> tool works, the invariants that must not be broken when editing, known
> constraints, and the roadmap. Read this before modifying `pixai_gallery_backup.py`.

---

## What this project is

A single-file Python CLI (`pixai_gallery_backup.py`) that backs up the **owner's
own** PixAI.art generated images at full resolution. PixAI's gallery UI only exposes
20 images at a time; this talks to the same private API the website uses to page
through the entire generation history, download every image, and catalog it.

It was built by reverse-engineering the site's network traffic (see "How it was
figured out"). There is no official PixAI API for listing your own generations —
the official API only covers *creating* new images.

**Scope:** personal backup of content the user owns (PixAI's terms grant users
copyright of their generations). Be polite to PixAI's servers (paced requests).

---

## Architecture / request flow

The whole thing hinges on a few discovered facts. Preserve these when editing.

1. **Listing query is an Apollo *persisted query*.** The site does NOT send GraphQL
   query text — it sends an `operationName` + a `sha256Hash`; the real query lives
   on PixAI's server. We replay that exact request. Constants at the top of the
   script (`OPERATION_NAME`, `PERSISTED_QUERY_HASH`, `U3T`, `USER_ID`,
   `CLIENT_LIBRARY`) were captured from the browser.

2. **It's a GET**, with `operation`, `u3t`, `operationName`, `variables`, and
   `extensions` (carrying the persisted hash) as URL query params. See `gql()`.

3. **Apollo CSRF headers are required** on that GET or the server returns a 400:
   `apollo-require-preflight: true` and `x-apollo-operation-name`. Set on the
   session in `main()`.

4. **Pagination is BACKWARD.** Variables are `{last, before, userId}`. We start with
   no `before` (newest page) and follow `pageInfo.startCursor` into `before` while
   `hasPreviousPage` is true. (Not `first`/`after`.) See `page_variables()` and the
   download loop.

5. **Task summaries contain `mediaId` + `batchMediaIds`, NOT image URLs.** To get a
   URL, fetch the media object at `https://api.pixai.art/v1/media/<mediaId>` (no
   variant → returns JSON). Its `urls` list has variants; the full-resolution one is
   `variant: "PUBLIC"` (path `/gi/orig/...`). `THUMBNAIL` is the small one. See
   `resolve_media()` and `URL_VARIANT_PREFERENCE`.

6. **Auth** is a Bearer token (JWT) the user copies from their logged-in browser.
   The script never handles passwords. Token via `PIXAI_TOKEN` env, `token.txt`, or
   `--token`. HTTPS verification is always on.

7. **SSL trust store**: `truststore.inject_into_ssl()` is called at import if the
   package is present, so corporate/antivirus HTTPS interception doesn't break
   verification. Never disable verification — the token rides every request.

---

## Key functions (map of the file)

| Function | Role |
|---|---|
| `gql()` | Replay the persisted GraphQL GET; retry/backoff; surfaces 401/4xx/GraphQL errors clearly. |
| `find_connection()` | Schema-agnostic: walks JSON for the Relay connection (`edges`+`pageInfo`). |
| `media_ids_for()` | `mediaId` + `batchMediaIds` for a task node. |
| `extract_meta()` | Pulls `id`, `createdAt`, `promptsPreview`, `status`. |
| `resolve_media()` | Fetch media object, pick the `PUBLIC` full-res URL. |
| `download()` | Stream to disk with resume + retries; optional convert. |
| `convert_image()` | WebP→PNG/JPEG via Pillow; flattens alpha for JPEG. |
| `embed_metadata()` | Write prompt/IDs/date into PNG text chunks or JPEG EXIF. |
| `slug_from_prompt()` / `build_stem_name()` | Filesystem-safe names. |
| `already_downloaded()` | Resume check: rglob the whole tree for `*_<mediaId>.*`. |
| `cmd_organize()` | Sort flat files into `batches/` and `YYYY-MM/`, embed, write info files. |
| `main()` | Arg parsing + mode dispatch. |

---

## INVARIANTS — do not break these

These are load-bearing. Several features silently depend on each.

1. **`media_id` is ALWAYS the last `_`-delimited chunk of a filename stem.**
   Resume, `--rename-existing`, and `--organize` all parse it as
   `stem.split("_")[-1]`. Never append anything after the media id in a filename.

2. **Resume is keyed on media id, checked BEFORE any network call.** In the download
   loop, `already_downloaded(out, mid)` runs before `resolve_media()`/`download()`.
   Keep that order so re-runs don't waste lookups. Resume searches the whole `out`
   tree recursively, so it still finds files after `--organize` moves them.

3. **Incomplete files must not count as done.** `.part` temp files and zero-byte
   files are treated as not-downloaded. Downloads write to `*.part` then atomically
   `replace()` the final name.

4. **`catalog.csv` is the source of truth** for `--organize` and `--rename-existing`
   (prompt, dates, dimensions, task↔media mapping). Don't make those modes depend on
   re-querying the API.

5. **`--organize` only moves flat files in `images/`** (non-recursive glob), which is
   what makes it idempotent. Don't switch it to rglob the whole tree, or a second run
   would try to re-process already-organized files.

6. **`--probe` exits before other modes.** It's a sanity check. `--count` etc. must
   be run on their own (documented; there's a guard that warns if combined).

---

## Constraints & gotchas

- **Server page-size cap:** `last` above ~8,000–10,000 triggers a Prisma
  `Internal server error`. `--count-page-size` defaults to 10000 (clears a ~8,900
  library in one request). Keep download `--page-size` ≤ ~8000.
- **WebP metadata** embedding is unreliable, so `embed_metadata()` skips WebP. For
  embedded metadata, pair `--organize` with `--convert png`.
- **`promptsPreview` is TRUNCATED.** The full prompt + seed + model are not in the
  task summary; they'd require capturing a different persisted query (the task-detail
  one). This is the main known data limitation.
- **Windows MAX_PATH (260):** batch images use short names (`NN_<mediaid>.ext`)
  inside the prompt-named folder to avoid doubling the prompt into the path.
  `--name-length` defaults to 60 to keep paths safe.
- **Conversion is compatibility, not quality:** WebP→PNG is lossless re-container
  (bigger files); WebP→JPEG re-compresses. Don't market it as quality improvement.
- **`--convert` only affects NEW downloads.** Already-downloaded WebP files aren't
  converted unless re-processed. (A `--convert-existing` pass is on the roadmap.)

---

## Security & GitHub hygiene (IMPORTANT)

- **Never commit the token.** `token.txt` and `.env` are git-ignored. The token is a
  password-equivalent (short-lived). Prefer the `PIXAI_TOKEN` env var.
- **Never commit the downloaded library.** The output folder (`pixai_backup/`)
  contains the user's images, prompts (some may be private/NSFW), and `catalog.csv`.
  It's git-ignored. Keep it that way.
- **`USER_ID`, `U3T`, and `PERSISTED_QUERY_HASH` are loaded from the git-ignored
  `config.json`** — they are no longer hardcoded in the script. `config.example.json`
  (committed) shows the required structure. The repo is safe to make public once
  any other personal data is reviewed.
- All traffic is HTTPS with verification on; do not add `verify=False` anywhere.

---

## Recapture procedure (when PixAI changes their site)

Symptoms: `PersistedQueryNotFound`, "Cannot query field…", or sudden 400s.
Fix: update `config.json` with fresh values from DevTools → Network → filter `graphql` →
click the `listUserTaskSummaries` row → Payload tab (`operationName`, `variables`,
`persistedQuery.sha256Hash`). `USER_ID` is in the profile URL. Keep the token
private. The RECAPTURE note is also at the bottom of the script.

---

## Testing approach

No test framework is wired in yet; verification has been manual but real:

- **Syntax:** `python3 -m py_compile pixai_gallery_backup.py` after every change.
- **Conversion:** create a transparent WebP with Pillow, run `convert_image()` to
  PNG (expect RGBA preserved) and JPEG (expect RGB, alpha flattened), verify
  `--keep-webp` behavior.
- **Naming/slug:** feed prompts with forbidden chars (`\ / : * ? " < > |`), commas,
  quotes; assert none leak and that the media id stays last.
- **Count tally:** simulate batch + single nodes; assert images = mediaId +
  batchMediaIds.
- **Organize:** build a fake `catalog.csv` + WebP files spanning a batch task and
  singles across two months; assert folder layout, `_prompt.txt`, per-month
  `_index.csv`, embedded metadata keys, resume finding moved files, and idempotency
  on a second run.

**Roadmap:** move these into a `tests/` directory with `pytest`, mocking the network
layer (`gql`, `resolve_media`, `session.get`) so the API logic can be tested offline.

---

## Roadmap / open ideas

In rough priority order:

1. ~~**`config.json` for captured constants**~~ ✅ Done — `USER_ID`, `U3T`, and hash
   loaded from git-ignored `config.json`; `config.example.json` ships with the repo.
2. **Full prompt + seed + model:** capture the task-detail persisted query and store
   complete generation parameters (currently only the truncated preview).
3. **`--convert-existing`:** convert already-downloaded WebP files in place.
4. **Foldering during live download:** optionally apply the `--organize` layout as
   files arrive, so it's one step instead of download-then-organize.
5. **`tests/` with pytest** and a mocked network layer.
6. **GUI port** (discussed): C#/WinForms or Go/Wails desktop app with a token field
   and progress bar. The full API flow is mapped, so it's a port, not new research.

---

## Quick command reference

(Full docs in `README.md`.)

```
python pixai_gallery_backup.py --probe            # connection sanity check
python pixai_gallery_backup.py --count            # total tasks + images (no download)
python pixai_gallery_backup.py --max 40           # small test download
python pixai_gallery_backup.py --convert png      # full download as PNG
python pixai_gallery_backup.py --organize --convert png --dry-run   # preview foldering
python pixai_gallery_backup.py --organize --convert png             # apply foldering
python pixai_gallery_backup.py --catalog-stats    # summarize catalog.csv
```

Resume is automatic and independent of `--page-size`: re-running skips anything
already on disk (matched by media id across the whole backup tree).

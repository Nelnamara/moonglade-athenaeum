# Setup

## 1. Install

Python 3.8+ (`python --version`), then:

```bash
pip install requests pillow PySide6 flask truststore
```

| Package | Needed for |
|---|---|
| `requests` | all network operations (required) |
| `pillow` | thumbnails, conversion, metadata embedding |
| `PySide6` | the desktop GUI (`pixai_gui.py`) |
| `flask` | the local web gallery (`pixai_gallery.py`) |
| `truststore` | optional — fixes HTTPS cert errors behind corporate proxies / AV |
| `cryptography` | optional — only for the gallery's `--https` mode |
| `ffmpeg` (on PATH) | optional — generates posters for backed-up/imported videos |

## 2. Configure

Copy `config.example.json` to `config.json` (git-ignored) and fill **three** values:

```json
"PIXAI_API_KEY": "your-api-key",
"USER_ID": "your-numeric-id",
"PERSISTED_QUERY_HASH": "captured-hash"
```

### API key (one minute, lasts up to ~2 years)
Generate one at [platform.pixai.art](https://platform.pixai.art) and paste it as
`PIXAI_API_KEY`. It's the Bearer credential for **every** call — there's no
expiring browser token to recapture. This is the only credential that ever needs
refreshing.

### USER_ID + PERSISTED_QUERY_HASH (one-time capture)
PixAI has no public endpoint for listing *your own* history, so the listing
replays the same persisted GraphQL query the website uses. Capture two values once:

1. Log in to [pixai.art](https://pixai.art), open your gallery/profile.
2. **F12 → Network**, type `graphql` in the filter.
3. Scroll so requests fire, click a `listUserTaskSummaries` row → **Payload**.
4. Copy `variables.userId` → `USER_ID`, and
   `extensions.persistedQuery.sha256Hash` → `PERSISTED_QUERY_HASH`.

(Your numeric `USER_ID` isn't in the address bar — PixAI uses `@username` in URLs —
which is why this step exists.)

### Optional hashes (captured the same way)
| Key | For |
|---|---|
| `TASK_DETAIL_HASH` | `--full-meta`, `--backfill-full-meta`, recovering generations by id (`getTaskById`) |
| `MODEL_DETAIL_HASH` | model-name resolution (ships a working default; only set if names stop resolving) |
| `DELETE_TASK_HASH` | **required** for delete (`--delete-task`, gallery "Delete from PixAI") — no default, on purpose |

> No API key? You can run the legacy browser-token path instead (leave
> `PIXAI_API_KEY` blank, add `U3T`, supply the short-lived token via `token.txt` /
> `PIXAI_TOKEN` / `--token`). It expires every few hours — the API key exists to
> avoid that.

## 3. First run

Desktop:
```bash
python pixai_gui.py
```

Or headless:
```bash
python pixai_gallery_backup.py --probe        # connection sanity check
python pixai_gallery_backup.py --count        # how many images you have
python pixai_gallery_backup.py --max 40       # small test download
python pixai_gallery_backup.py                # download everything (parallel)
python pixai_gallery_backup.py --update       # later: grab only what's new
```

Everything lands in `pixai_backup/` (git-ignored): `images/`, `catalog.db`,
`raw_tasks.jsonl`, and (once organized) `YYYY-MM/` month folders.

When PixAI changes their frontend you may see `PersistedQueryNotFound` or
"Cannot query field" — just recapture the relevant hash the same way.

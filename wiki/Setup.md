# Setup

## 1. Install

Python 3.8+ (`python --version`), then:

```bash
pip install -r requirements.txt
```

| Package | Needed for |
|---|---|
| `requests` | all network operations (required) |
| `pillow` | thumbnails, conversion, metadata embedding |
| `PySide6` | the desktop GUI (`pixai_gui.py`) |
| `flask` | the local web gallery (`pixai_gallery.py`) |
| `websockets` | `--watch` / `--watch-backup`, and the web gallery's auto-starting live-mirror thread |
| `truststore` | optional — fixes HTTPS cert errors behind corporate proxies / AV |
| `cryptography` | optional — only for the gallery's `--https` mode |
| `ffmpeg` (on PATH) | optional — posters for backed-up/imported videos; required for The Loom's video export and last-frame extract |
| `pytest`, `pytest-mock`, `pytest-cov` | dev only — running the test suite |

## 2. Configure — one value

Copy `config.example.json` to `config.json` (git-ignored) and set **one** value:

```json
{ "PIXAI_API_KEY": "your-api-key" }
```

Generate a key at [platform.pixai.art](https://platform.pixai.art) (lifetime up to
~2 years). It's the Bearer credential for **every** call, and:

- **`USER_ID` is auto-resolved** from the key (via the `me` query) — no DevTools.
- **The persisted-query hashes ship with working defaults** — nothing to capture.

### Why are there still "hashes" in the example file?
PixAI's public API (what your key talks to) exposes generation and model search but
**not** the private ops that list *your own* history, fetch task detail, or delete
tasks. Those are reached by replaying PixAI's own frontend GraphQL queries,
identified by a persisted-query **hash**. These hashes are **public, not secret, and
the same for everyone** — so the tool bakes the current ones in. You only touch them
if PixAI overhauls their frontend and a default goes stale (you'll get a clear error
— see [Troubleshooting](Troubleshooting)). All hash fields in `config.json` are
optional overrides; leave them blank. More detail: [How It Works](How-It-Works).

> **No API key?** A legacy browser-token path still exists (leave `PIXAI_API_KEY`
> blank, add `U3T`, supply a short-lived token via `token.txt` / `PIXAI_TOKEN` /
> `--token`, set `USER_ID`). It expires every few hours — the API key avoids all of
> this.

## 3. First run

Web gallery (browse, generate, The Loom) — at [localhost:5000](http://localhost:5000):
```bash
python pixai_gallery.py --out pixai_backup
```

Desktop app (legacy — the PySide6 GUI is being folded into the web app):
```bash
python pixai_gui.py
```
Double-click launcher (no console): **`Moonglade Athenaeum.pyw`**.

Headless:
```bash
python pixai_gallery_backup.py --probe   # connection sanity check
python pixai_gallery_backup.py --count   # how many images you have
python pixai_gallery_backup.py --max 40  # small test download
python pixai_gallery_backup.py           # download everything
```

Everything lands in `pixai_backup/` (git-ignored). Next: **[Backing Up](Backing-Up)**.

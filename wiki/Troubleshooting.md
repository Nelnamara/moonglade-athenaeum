# Troubleshooting

## "PersistedQueryNotFound" / "Cannot query field … on type Query"
A built-in identifier went stale after a PixAI frontend update. These ship with the
app and are shared by everyone, so when one breaks it breaks for all users.

- **First, update to the latest release** (`git pull`) — refreshed defaults usually land
  there quickly.
- If it's still broken on the latest version, **open an issue** so the default can be
  updated for everyone.

## "401 Unauthorized"
Your `PIXAI_API_KEY` is missing, mistyped, or expired. Regenerate at
[platform.pixai.art](https://platform.pixai.art) and update `config.json`.

## "Could not auto-resolve your user id"
The `me` query failed (usually a bad/empty key). Fix the key, or set `USER_ID`
manually in `config.json` as a fallback.

## "Invalid modelId" when generating
You used a **model** id where a **version** id is required. Don't paste from a
`pixai.art/model/<id>` URL — use the drawer's **model search** or the CLI's
`--list-models` (they resolve the version id). See [Generating](Generating).

## "unknown inferenceProfile …"
The chosen **Mode** isn't supported by that model type. This is harmless everywhere now
(since 2026-07-24): the **CLI** (`--generate`) and the **web app's Generate tab** both
auto-fall-back to the model's default and generate anyway — a rejected submit costs no
credits either way, so the retry is free. You shouldn't see this raw message at all
anymore; if you do, it's a friendlier "That quality setting isn't available for this
model — try Auto instead" banner in most places, or (rarer) a case the retry itself
didn't catch. Leave Mode on **Auto** if you'd rather not think about it.

## HTTPS / SSL certificate errors
Behind antivirus or a corporate proxy: `pip install truststore` (Python 3.10+). The
tool uses it automatically when present.

## The gallery shows old behavior after I updated
After `git pull`, **restart the gallery server** so it loads the new code — Stop/Restart
from the browser, or relaunch **`Serve Gallery.pyw`**. Then **hard-refresh the browser
(Ctrl+F5)** to clear the cached front-end (or the service worker).

## Videos won't show a poster
Posters need `ffmpeg` on your PATH. Without it, videos still back up and play; they
just won't have a thumbnail.

## A generation isn't in the gallery yet
Generated tasks don't always flow into `--update` instantly. Recover by id without
spending credits: `python pixai_gallery_backup.py --generate --task-id <id>`.

To stop it stranding in the first place, use the live push path: the web gallery
runs a live-mirror thread automatically, and the CLI exposes the same machinery as
`python pixai_gallery_backup.py --watch --watch-backup`, which collects each
generation the moment it completes. Both need `websockets` — see [Setup](Setup).

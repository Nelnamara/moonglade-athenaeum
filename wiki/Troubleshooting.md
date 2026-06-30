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
`pixai.art/model/<id>` URL — use the **Model** dropdown or **Search PixAI…** (they
resolve the version id). See [Generating](Generating).

## "unknown inferenceProfile …"
The chosen **Mode** isn't supported by that model type. Harmless — the tool
auto-falls-back to the model's default and generates anyway (a rejected submit costs
no credits). Leave Mode on **Auto** to avoid it.

## HTTPS / SSL certificate errors
Behind antivirus or a corporate proxy: `pip install truststore` (Python 3.10+). The
tool uses it automatically when present.

## The gallery shows old behavior after I updated
The GUI imports the gallery module **once at startup** — Stop/Launch on the Gallery
tab restarts the *thread*, not the *code*. After `git pull`, **fully quit and reopen
the GUI**, then hard-refresh the browser (Ctrl+F5).

## Videos won't show a poster
Posters need `ffmpeg` on your PATH. Without it, videos still back up and play; they
just won't have a thumbnail.

## A generation isn't in the gallery yet
Generated tasks don't always flow into `--update` instantly. Recover by id without
spending credits: `python pixai_gallery_backup.py --generate --task-id <id>`.

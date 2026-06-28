# Troubleshooting

## "PersistedQueryNotFound" / "Cannot query field … on type Query"
A baked-in persisted-query hash went stale — PixAI changed their frontend. Recapture
just the affected one:

1. Log in to [pixai.art](https://pixai.art), **F12 → Network**, filter `graphql`.
2. Trigger the operation and click its request:
   - the feed → `listUserTaskSummaries` → `PERSISTED_QUERY_HASH`
   - full-meta / generation polling → `getTaskById` → `TASK_DETAIL_HASH`
   - delete → `deleteGenerationTask` → `DELETE_TASK_HASH`
   - model names → `getGenerationModelByVersionId` → `MODEL_DETAIL_HASH`
3. **Payload** tab → copy `extensions.persistedQuery.sha256Hash` into the matching
   key in `config.json`. It overrides the default.

(If you find a fresh working hash, opening an issue helps everyone — the defaults can
be updated.)

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

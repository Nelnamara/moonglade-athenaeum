# Troubleshooting

## Seeing more detail (`-v` / `--verbose`)

Add `-v` (or `--verbose`) to any command for a fuller running commentary — per-item
progress, why a step was skipped, and (for `--faststart-videos`) ffmpeg's own message when
it refuses a file. It's the first thing to reach for when a run does something you don't
expect.

## "PersistedQueryNotFound" / "Cannot query field … on type Query"
A built-in identifier went stale after a PixAI frontend update. These ship with the
app and are shared by everyone, so when one breaks it breaks for all users.

- **First, update to the latest release** — open the **Control Panel** and click the gold
  version stamp in its sidebar footer if one is offered (`git pull` by hand otherwise).
  Refreshed defaults usually land there quickly.
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

## A generate/edit/video failed with a connection or timeout error

Submitting is deliberately **single-attempt** (since 2026-07-26) — it is not retried for
you, on purpose. A retry can't tell "PixAI never got it" from "PixAI got it, made it,
charged you, and the reply was lost", so retrying could buy you a second generation. Reads
still retry normally; only the spending calls stop. **Check the gallery (or `--account`)
before re-submitting** — if the task did land, it will show up there, and you can recover
it for free with `--task-id <id>` instead of paying again.

## HTTPS / SSL certificate errors
Behind antivirus or a corporate proxy: `pip install truststore` (Python 3.10+). The
tool uses it automatically when present.

## Every image says "no url for media …"

If that line appears once, PixAI genuinely doesn't have that image any more. If it appears
for *everything*, it's almost certainly not PixAI — it's the same HTTPS interception above,
hitting the media CDN rather than the API. That case now prints the truststore guidance
once per run, above the flood of per-image lines, ending with:

> Every image resolve will fail the same way until this is fixed — this is a local trust
> problem, NOT PixAI missing your images. (Said once per process; every individual failure
> is in the log.)

It's said once rather than 17,000 times for the obvious reason; each individual failure is
still recorded in the rotating log at `pixai_backup/logs/moonglade.log`, whether or not you
ran with `-v`. The cure is the one above: `pip install truststore`, then re-run.

Two details worth knowing. The API host and the media CDN are different hosts, so one can be
trusted while the other isn't — which is why this used to look like a PixAI problem instead
of a local one. And "once per run" is literally once per *process*: on the long-lived gallery
server the paragraph appears on the console the first time and not again, so read the log
there rather than waiting for it to repeat.

## The gallery shows old behavior after I updated
The Control Panel's one-click update restarts the server and reloads the tab for you. If you
updated **by hand** with `git pull`, **restart the gallery server** so it loads the new code
— Stop/Restart from the browser, or relaunch **`Serve Gallery.pyw`**. Either way, if a page
still looks stale, **hard-refresh the browser (Ctrl+F5)** to clear the cached front-end (or
the service worker).

## The version stamp never turns gold, and no notice ever appears
That is the quiet, normal state: either you are already on the newest release, or the check
could not reach GitHub (no network, a firewall, or GitHub's hourly limit for anonymous
callers). The check is deliberately silent about its own failures — an update notice is not
worth an error banner on a Panel you opened to do something else. `git pull` by hand always
works; the app tries again about an hour later, and opening the Panel asks straight away.

The corner notice is shown **once per version** on purpose, so if you dismissed it, it will
not come back for that release — the gold stamp in the Panel's sidebar is the standing
reminder. And the hourly check only runs while the app is **running**: a machine that was
switched off for a week hears about the release when you start it up again, not before.

## "Update now" is refused
The refusal appears inside the update window itself, where the progress would have been,
and it is colour-coded: **grey** means the request never reached the server at all (you are
offline — nothing was attempted), **gold** means come back in a moment (something is still
running), and **red** means this install will keep refusing until something is changed. The
window names the reason either way. The usual ones:

- **The server wasn't started through `Serve Gallery.pyw`.** Only the launcher relaunches the
  app after an update — without it the server would simply stop.
- **A Control Panel job is still running.** Let it finish or cancel it; changing the code
  under a running job is how you get half-old, half-new behavior.
- **The checkout is on a branch other than `master`.** Updating somebody's work-in-progress
  branch is out of scope on purpose.
- **You have edited a file the app ships.** The update writes that file, so it would
  overwrite your edit — it refuses and names which files.
- **A file of your own is sitting exactly where the update needs to write.** Only then:
  files you have added yourself that the update doesn't touch — a notes file, a scratch
  folder, a launcher you keep beside the app — are left alone and don't stop anything.
  When one really is in the way the refusal says so and names it; move or delete it and
  try again.
- **`READ_ONLY` is set in `config.json`.** That flag means "don't change my install", and an
  update is the biggest change there is.

Each of those is fixable, and `git pull` by hand stays available regardless.

## An update failed part-way
The modal keeps git's or pip's own words, which is usually the whole diagnosis. Two shapes
are worth knowing:

- **The pull failed.** Nothing changed — the update pulls fast-forward-only, so it either
  applies cleanly or refuses.
- **The dependency install failed.** The update **rolls itself back** to the version you were
  on, so you are left on a working install rather than new code with old dependencies. Fix
  whatever pip reported (usually a network blip) and press Update again.

Either way the attempt is also recorded in the activity tracker, so it is still there after
the restart or the next time you open the app.

## Videos won't show a poster
Posters need `ffmpeg` on your PATH. Without it, videos still back up and play; they
just won't have a thumbnail.

## A generation isn't in the gallery yet
Generated tasks don't always flow into `--update` instantly. Recover by id without
spending credits: `python moonglade_backup.py --generate --task-id <id>`.

To stop it stranding in the first place, use the live push path: the web gallery
runs a live-mirror thread automatically, and the CLI exposes the same machinery as
`python moonglade_backup.py --watch --watch-backup`, which collects each
generation the moment it completes. Both need `websockets` — see [Setup](Setup).

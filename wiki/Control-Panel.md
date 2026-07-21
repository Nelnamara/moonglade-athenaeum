# The Control Panel

**`/panel`** — reached from **⚙ Panel** in the gallery header. It runs the same maintenance
commands the CLI does, as background jobs with a live log and a progress bar, so routine
upkeep never needs a terminal. It also holds the job scheduler, your login accounts, and
Stop / Restart for the server itself.

Like every page in the gallery, it needs a login (see [Setup](Setup)).

Two tabs: **Maintenance** and **Users**.

## Library at a glance

Images, videos and collections in your catalog, plus your live PixAI credit balance and
free-card count. **⬇ Download catalog (CSV)** saves the whole catalog to your browser's
Downloads — it does *not* write a file into your backup folder (the CLI's `--export-csv`
still does that, for scripting).

## Running a maintenance job

Click a button and the job starts as a background run of `pixai_gallery_backup.py`:

- **One job runs at a time.** While one is running the other buttons are disabled, and a
  second request comes back with *"a job is already running"*.
- The **live log** streams the command's output; a **progress bar** shows done / total
  (and how many are new) for jobs that report progress.
- When it ends you get *finished (exit 0)*, *failed*, or *stopped by you*.
- **■ Stop this job** terminates the run. Like the destructive jobs below, stopping is
  restricted to the machine hosting the gallery.

The buttons are grouped exactly as the risk splits.

### Safe · read-only or reversible

- **Sync now — pull new + fill metadata** — the one-shot refresh (`--sync`): incremental
  pull with full metadata, re-resolve unlabeled model names, fill rows still missing
  prompts/seeds/models, build missing thumbnails, and flag rows deleted on PixAI. This is
  the button you'll use most. See [Backing Up](Backing-Up).
- **Catalog stats** — counts summarized straight from `catalog.db`.
- **Duplicate audit (fast, read-only)** — the location-only duplicate report, written to
  `audit_report.csv`. The **full (byte-compare — slower)** checkbox on the button runs the
  content-hashing pass instead, which also catches byte-identical files saved under
  different ids.
- **Verify `_duplicates/` is safe to delete** — confirms every quarantined file is
  byte-identical to a surviving copy, and flags orphans, before you empty the folder.
- **Rebuild the Similar index (slow, needs pixeltable)** — re-embeds the visual-similarity
  index used by **✧ Similar** in the gallery. No network; needs the optional
  `pixeltable` install.
- **Organize — preview (dry run)** and **Dedup — preview (dry run)** — show the plan
  without moving anything.
- **Sync published-artwork metadata (full re-walk)** — merges titles, tags, likes and
  aesthetic scores onto matching rows.
- **Sync i2v videos — back up mp4s (full re-walk)** — finds image-to-video tasks and
  downloads their mp4s.

The two labelled *(full re-walk)* re-scan your whole history every run rather than stopping
at what's already downloaded, so they take much longer than **Sync now**. That's why the
label says so — they're good candidates for the scheduler rather than a click after every
generation.

### Changes files · asks first

- **Organize into month folders** — normalizes the backup into `YYYY-MM/` folders with
  readable filenames, writing an undo manifest.
- **Undo organize — move files back to their old paths** — replays that manifest backwards,
  then deletes it. There's no second manifest to undo the undo.
- **Dedup — quarantine dupes to `_duplicates/`** — moves redundant copies aside, keeping
  the most-organized one. The **DELETE instead of quarantining** checkbox on that button
  deletes them outright instead — no `_duplicates/` safety net, no undo. Run the preview
  and the verify job first.
- **Verify quarantine + restore orphans to `images/`** — the write-enabled version of the
  verify job: quarantined files with no surviving keeper are moved back.
- **Rebuild ALL thumbnails — uniform quality + video posters** — regenerates every
  thumbnail at current settings, extracts posters for poster-less videos, and sweeps
  orphans. It overwrites in place, so the gallery never goes blank.

Each of these asks you to confirm in a dialog before it runs, **and** only runs for a
request from the machine hosting the gallery. Signed in from a tablet on your LAN you can
browse, generate and run the safe jobs, but clicking one of these returns *"this action
changes files; localhost-only"* — deliberate, because they move or overwrite files on the
server's own disk.

### Advanced · sync variants the one-click Sync doesn't cover

Collapsed behind **Advanced** in the Maintenance card. All three are read/append (they never
delete), but each re-walks the full account instead of stopping at what you already have:

- **Full re-walk — re-pull ALL history + metadata (non-incremental)** — for filling gaps in
  the *middle* of your history, which an incremental sync can't reach.
- **Inventory count — tally account vs. backup (read-only, no download)** — counts what's on
  your account so you can compare it to what's local. Downloads nothing.
- **Test pull — fetch the N most-recent tasks** — the one job that takes a number. Set **N**
  in the box on the button (1–200, default 20); anything outside that range is clamped.
  Good for a quick smoke test after changing settings.

These are manual-run only — they don't appear in the scheduler dropdown.

## Download workers

The selector under the job buttons (1–16, default 4) sets how many images download in
parallel. It's saved with the schedule and used by **both** your button clicks and the
scheduled run. More workers mainly speed up a big metadata backfill or a first catch-up;
**Sync now** only pulls what's new, so it rarely needs many.

## Automated tasks (the scheduler)

Tick **Enabled**, pick a job under **Run**, pick an interval under **Every** (1 hour through
1 week), and **Save schedule**. The card then shows when it last fired.

- Only **safe, non-advanced** jobs can be scheduled — nothing that deletes or moves files.
- It's an **in-process timer, not an OS cron**: it fires only while the gallery is running,
  and skips its turn if a job is already going. For always-on backups, point Windows Task
  Scheduler at the CLI instead:

```bash
python pixai_gallery_backup.py --out pixai_backup --update
```

- Saving the schedule (like the destructive jobs) requires a request from the server's own
  machine. A LAN session still sees the current settings.

### Jobs with no button

A couple of actions are schedulable but have no button on purpose. **Reconcile deleted
(flag cloud-removed rows)** is the main one: `--sync` already runs it as its final step, so
a button would be a second path to work that just happened. Pick it from the **Run**
dropdown if you want it on its own cadence — see [Deleting & Sync](Deleting).

## Recover a task by ID

Paste a numeric task id and click **⬇ Import** to pull that one generation or edit straight
into your gallery. Handy for edits and anything in Favorites that the normal listing skips.
It downloads your own finished media and spends nothing; if the task is already catalogued
it tells you and links straight to it.

## Live Mirror

A status readout for the push connection that mirrors each generation the instant it
finishes: connected or reconnecting, when the last event arrived, and how many items it has
mirrored this session. It's read-only, free, and always on while the server runs — which is
why `--update` is a fallback rather than the only way new work lands locally.

## Server

- **↻ Restart server** — needs the managed **`Serve Gallery`** launcher (it relaunches the
  process); the button is disabled when the server was started headlessly.
- **■ Stop server** — shuts it down cleanly from the browser. No Task Manager.

Both are available to any signed-in session. A reconnect overlay waits for the server to
come back after a restart.

## Users

The **Users** tab lists your gallery login accounts.

- **Add user** — username, password, confirm. Duplicate usernames are refused outright
  rather than quietly resetting an existing account's password.
- **Remove** — takes effect immediately: that account is signed out on every device at once.
- The **last remaining account can't be removed** from here — that would lock every remote
  device out until someone signed in on the server machine to bootstrap a new one.

Every account has equal access (browse, generate, maintenance); there's no separate admin
tier. Locked out, or need a password reset? That's the CLI's job — see [Setup](Setup).

## Where jobs are recorded

Every panel job also writes to the shared activity log, so the paper trail survives a page
reload: open the **Activity** button in the gallery (bottom-left, also in The Loom) to see
runs from the panel, the CLI, and your generations in one newest-first list. It keeps the
50 most recent, ages finished entries out after a day, and lets you dismiss a finished or
failed row.

## This build

The last card shows the build you're running and the path to your library folder.

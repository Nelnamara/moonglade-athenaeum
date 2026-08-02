# The Control Panel

Reached from **⚙ Panel** in the gallery header. It runs the same maintenance commands the
CLI does, as background jobs with a live log and a progress bar, so routine upkeep never
needs a terminal. It also holds your login accounts, branding, and Stop / Restart for the
server itself.

**Two ways to reach it, same real jobs underneath:**
- On the current gallery (the default at `http://localhost:5000`), **⚙ Panel** opens the
  Panel as an **overlay on top of the gallery**, not a separate page — click it again or
  `Esc` to close. Its two tabs are **Maintenance** and **Branding**; **Accounts** and
  **Trash** are their own tiles inside Maintenance, each opening as a further overlay on
  top of the Panel itself. The job scheduler and the *(full re-walk)*/Advanced sync
  variants described below are on classic's page only (see next bullet) — not yet ported.
- On **Classic** (linked from the gallery header; retiring once the port above is
  complete), the Panel is still the full **`/panel`** page this article otherwise
  describes, with its own **Maintenance** and **Users** tabs and the scheduler.

Like every page in the gallery, it needs a login (see [Setup](Setup)). Everything below —
which jobs exist, what's destructive vs. safe, who can run what — is identical on both;
only the Panel's own shape (page vs. overlay, Users tab vs. Accounts tile) differs.

## Library at a glance

Images, videos and collections in your catalog, plus your live PixAI credit balance and
free-card count. **⬇ Download catalog (CSV)** saves the whole catalog to your browser's
Downloads — it does *not* write a file into your backup folder (the CLI's `--export-csv`
still does that, for scripting).

## Running a maintenance job

Click a button and the job starts as a background run of `moonglade_backup.py`:

- **One job runs at a time.** While one is running the other buttons are disabled, and a
  second request comes back with *"a job is already running"*.
- The **live log** streams the command's output when you're signed in locally; a LAN
  session sees a placeholder line instead — job output is shown only on the server's own
  screen. A **progress bar** shows done / total (and how many are new) for jobs that
  report progress, for both.
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
- **Top up the Similar index (adds only what's missing)** — embeds any images the
  visual-similarity index doesn't have yet and leaves everything already in it alone.
  **This is the one you normally want.** It can't lose existing work, and if a previous
  build was interrupted it carries on from where that stopped instead of starting over.
  No network; needs the optional `pixeltable` install.
- **Rebuild the Similar index (slow, needs pixeltable)** — drops the index and re-embeds
  **every** image from scratch. Reach for this only when the index is actually *broken*
  (wrong or duplicated results), not merely incomplete — on a large library it takes
  roughly three times as long as a top-up and discards whatever was already there.
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
python moonglade_backup.py --out pixai_backup --update
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

- **Add user** — username, password, confirm. Appears **only when you're using the browser on
  the server machine itself**; a LAN session gets a short note where the form would be, and a
  request made by hand comes back `localhost-only` (403). A new account is a permanent key to
  the whole library and can spend your PixAI credits, so creating one is an
  owner-at-the-keyboard action rather than something any open tab can do. Duplicate usernames
  are refused outright rather than quietly resetting an existing account's password.
- **Remove** — takes effect immediately: that account is signed out on every device at once.
  Removing **your own** account works from anywhere *unless it's the only account left* (see the
  next bullet — the button is still drawn on your own row, so on a single-account install this is
  the refusal you'll actually meet); removing **someone else's** is restricted to the server
  machine, for the same reason **Add user** is. (Signing yourself out of your own account can
  only cost you; evicting another account is the other half of the same mint-yourself-a-login
  problem.)
- The **last remaining account can't be removed** from here — from *any* address, loopback
  included, because that would leave the gallery with nobody able to sign in. To deliberately
  take the count to zero and re-open the first-run bootstrap, use `--remove-web-user` on the
  server machine; that's the escape hatch, and it's CLI-only on purpose.
- **Your password** — change your own from anywhere, including a tablet on the LAN. You have
  to enter your current password to prove it's you.
- **Reset password** — appears next to each *other* account, and only when you're using the
  browser **on the server machine itself**. It sets a new password without needing the old
  one, which is what makes it a recovery path rather than a convenience.

Reading the roster is not restricted — every signed-in session sees who exists. It's changing
the roster that needs the server machine.

There's no separate admin tier: every account has equal access to the gallery itself (browse,
generate, edit, Fix, curate, The Loom, the safe maintenance jobs), and no account holds a power
another one lacks. The line that actually exists is *where you're sitting*, not who you are —
adding an account, removing someone else's, resetting their password, the destructive jobs above,
emptying the Trash, deleting from your PixAI account, and writing the API key or library folder
all need the machine hosting the gallery, and they refuse the owner's own account just as firmly
when it's signed in from a tablet.

The two operations that *do* turn on a username — changing your own password, removing your own
account — aren't a privilege either: what varies is whose account is being changed, not what your
login is allowed to do. `tests/test_route_tiers.py` is what keeps this page honest; it enumerates
every route the app actually registers and fails the build if one doesn't declare and enforce its
tier against a live LAN request.

**Why the reset button is local-only.** Being at the server machine is the proof of identity
here — it's doing the job an emailed reset link does for a hosted app. That's also why there's
no *"forgot password?"* link on the login page and no email anywhere in Moonglade: without an
out-of-band channel, a logged-out reset would let anything on your network reset your account.
So recovery is three cases:

- **You know your password** → change it from anywhere, here in **Users → Your password**.
- **You forgot it** → someone at the server machine resets it, **Users → Reset password**.
- **It's the only account and you forgot it** → `--add-web-user` on the server machine, whose
  add-or-update behaviour still doubles as a reset. See [Setup](Setup).

## Where jobs are recorded

If the app is closed or the machine restarts while a job is running, that job is marked
**Interrupted** the next time the server starts, rather than sitting at "running" forever.
Nothing is corrupted when that happens — just start it again. (A top-up will pick up where the
interrupted one left off.)

Every panel job also writes to the shared activity log, so the paper trail survives a page
reload: open the **Activity** button in the gallery (bottom-left, also in The Loom) to see
runs from the panel, the CLI, and your generations in one newest-first list. It keeps the
50 most recent, ages finished entries out after a day, and lets you dismiss a finished or
failed row.

A generation's row says which phase it is in rather than just spinning. **Queued** means
PixAI has accepted the job and no worker has picked it up yet — nothing is rendering — and
the icon holds still to say so; it starts spinning once a worker takes it. While queued, the
row also shows the queue wait PixAI itself predicted for that model, and clicking the row
gives you the full version (`Est. wait — 27s (PixAI, when queued)`) right under a live
**Time Spent**, so a job that is genuinely stuck is obvious: a 27-second estimate beside six
minutes elapsed is your answer. That estimate is a prediction of the *wait*, taken once when
the job went into the queue — it is not a countdown, and there is no percentage or progress
bar, because PixAI does not report progress on a running task at all. A job that stays
unstarted long enough is marked **stale** with an explanation; PixAI cancels and refunds
tasks it never starts at about 60 minutes.

**That live Time Spent stops when the job does.** It only ever ticks while the job is
actually running, and it's re-checked on every poll rather than decided once when you opened
the popover — so leaving the popover open across a finish now leaves the real final duration
on screen. It used to keep counting: a second after the true figure rendered, the clock
overwrote it with an ever-growing "X so far" for a job that was already done. On a panel
whose whole purpose is telling a slow generation from a stuck one, an elapsed time that
never stops is worse than no elapsed time. (If a **stale** job is later heartbeated back to
running, the clock simply starts again — that status isn't final server-side.)

## This build

The last card shows the build you're running and the path to your library folder — when
you're signed in locally. A LAN session sees `(local to the server)` instead; the install
path never crosses the network boundary.

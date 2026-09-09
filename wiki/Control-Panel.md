# The Control Panel

Reached from **⚙ Panel** in the gallery header. It runs the same maintenance commands the
CLI does, as background jobs with a live log and a progress bar, so routine upkeep never
needs a terminal. It also holds your login accounts and Stop / Restart for the
server itself.

**Most of it runs itself.** The block at the top of the console — **Runs itself** — lists the
jobs the app performs on its own: what each one is, how often it runs, when it last ran, when
it next will, and a **Run now** beside it. The buttons below it are still there and still work;
they are simply no longer the only way anything happens. See
[Runs itself — the living library](#runs-itself--the-living-library).

**⚙ Panel** opens the Panel as an **overlay on top of the gallery**, not a separate
page — click it again or `Esc` to close. Its tab is **Maintenance**; **Accounts**,
**Trash**, and **PixAI account** (your cards, coupons and credit ledger) are their own
tiles inside Maintenance, each opening as a further overlay on top of the Panel itself.
**PixAI account** opens on a strip of figures — credits, how much of that is paid and how
much free, free cards on hand, coupons, and your **followers** and **following** — above
tabs for the card roster, coupons and the credit ledger. Every figure on it is a reading:
the window never spends, redeems, purchases, follows or unfollows anything.
The **Runs itself** list heads the job console; the older single **⏱ Standing order** — the
auto-sync schedule — still lives in that console's **Ledger** view. (The old separate
`/panel` page retired with the classic interface, 2026-08-08.)

Like every page in the gallery, it needs a login (see [Setup](Setup)).

## Library at a glance

Images, videos and collections in your catalog, plus your live PixAI credit balance and
free-card count. **⬇ Download catalog (CSV)** saves the whole catalog to your browser's
Downloads — it does *not* write a file into your backup folder.

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
  aesthetic scores onto matching rows. You rarely need it now: the **Published-artwork
  sweep** in [Runs itself](#runs-itself--the-living-library) keeps this current on its own.
  This button is the *whole* re-read, for when you want every work refreshed this instant.
- **Sync i2v videos — back up mp4s (full re-walk)** — finds image-to-video tasks and
  downloads their mp4s.

The two labelled *(full re-walk)* re-scan your whole history every run rather than stopping
at what's already downloaded, so they take much longer than **Sync now**. That's why the
label says so — and why the automatic versions of both are in
[Runs itself](#runs-itself--the-living-library) rather than being a click after every
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

These are manual-run only. None of them is on a cadence, and none can be put on one — the
**Full re-walk** appears in [Runs itself](#runs-itself--the-living-library) purely as a
sixty-day floor, never as a timer.

## Download workers

The selector under the job buttons (1–16, default 4) sets how many images download in
parallel. It's saved alongside the job list and used by **both** your button clicks and
every automatic run. More workers mainly speed up a big metadata backfill or a first
catch-up; **Sync now** only pulls what's new, so it rarely needs many.

## Runs itself — the living library

**Runs itself** is the block at the top of the console, above the buttons. It is the list of
jobs the app performs on its own, and each row says the same four things: what the job is,
**how often** it runs, **when it last ran**, and **when it next will** — with a **Run now**
beside it, because a job that runs itself should still be one you can start by hand.

Everything in it is on by default. Flip a row **off** to stop it; change its **every** to
change its cadence.

| Job | How often | What it does |
|---|---|---|
| **Published-artwork sweep** | every 15 minutes | Re-reads PixAI's list of your published works and refreshes their titles, tags, likes, comments and visibility. It never reads view counts. |
| **Sync now** | every 6 hours | The one-shot refresh (`--sync`), then a perceptual-hash backfill straight after it. |
| **View counts** | weekly | Reads how many views each published work has. Asking adds one view to each, so this is the only job that touches those numbers — see below. |
| **Sync i2v videos** | daily | Backs up your image-to-video generations. |
| **Reconcile deleted** | weekly | Flags catalog rows whose task is gone from PixAI. |
| **Top up Similar** | daily | Embeds anything the visual-similarity index is missing. Needs the optional ML install; without it the row stays asleep rather than failing nightly. |
| **Full re-walk** · **Rebuild Similar** · **Rebuild ALL thumbnails** | only if it hasn't run in 60 days | The three jobs with no incremental form. They are not on a cadence — this is a floor under them, so a library can't drift for months untended. |

### The sweep, and why it's cheap

The **published-artwork sweep** is the one that matters most, because publishing is written
only to *this* machine's catalog: nothing else on earth hears about it until something reads
PixAI's own list back. (That is how a piece published from the app could vanish from **My
Art** on the other install.) So the sweep reads it back — on a timer, once shortly after the
app starts, **and the instant you publish, unpublish or re-tag anything**, which makes the
machine you published from right immediately instead of within the next quarter hour.

It costs almost nothing because it stops early. It walks your published works newest-first
and gives up after two pages in a row that hold nothing it needs — the same "stop when you
reach what you already know" the incremental pull has always used. So a quiet sweep is one
or two pages, not your whole history.

Two consequences worth knowing:

- Works **younger than 90 days** have their like and comment counts refreshed on **every**
  sweep — those are the numbers still moving.
- **Older** works refresh at most **once every 48 hours**. Every two days the sweep walks
  the whole history once to collect them, and is quiet again after that.

The **Sync published-artwork metadata** button below is unchanged and still does the full
re-walk, for when you want every work re-read this instant.

### View counts have their own row, on purpose

Asking PixAI how many views a work has **adds one to that number** — PixAI's behaviour, not
Moonglade's, and there is no way to look without it counting. So the view read is not part
of anything that runs unattended:

- The **fifteen-minute sweep** never reads a view count at all.
- **View counts** is its own weekly row, on by default. Turn it off and your view numbers are
  never touched by the app again; press its **Run now** and it reads them once, that minute.
- A **scheduled** run of **Sync published-artwork metadata** — from this list, or from the
  standing order — skips the view read too. Clicking that button **by hand** still reads
  them, because that is you asking.
- With `READ_ONLY` set in `config.json`, the view read is skipped everywhere, by hand
  included: it changes a number on your account, so it sits behind the same switch as
  publishing and deleting.

### What never runs itself

**Nothing destructive, ever — not now, and not as an option.** Organize, undo organize,
dedup (quarantine or delete) and restore orphans have no row here and cannot be given one:
they stay buttons, with their confirm and their server's-own-machine gate exactly as before.

### The rest of the rules

- It's an **in-process timer, not an OS cron**: jobs fire only while the gallery is running.
  For always-on backups, point Windows Task Scheduler at the CLI instead:

```bash
python moonglade_backup.py --out pixai_backup --update
```

- **One job at a time**, as always. A job whose turn arrives while another is running simply
  waits for the next minute.
- **A finished job never moves the page you are reading.** It announces itself the way
  everything else does — the notice in the corner and a row in **Activity** — and touches
  nothing else: not your page, your search, your address or the pictures you have ticked.
- Changing a row (**on/off**, **every**, **Run now**) requires a request from the server's
  own machine, like the destructive buttons. A LAN session — including the phone — still
  **sees** the whole list and what it is doing.

### The standing order

The single **⏱ Standing order** in the console's **Ledger** view is still there and still
works: one job, one cadence, chosen from the **Run** dropdown. It predates the list above,
it is independent of it, and the list never doubles up on whatever job it names.

## Recover a task by ID

Paste a numeric task id and click **⬇ Import** to pull that one generation or edit straight
into your gallery. Handy for edits and anything in Favorites that the normal listing skips.
It downloads your own finished media and spends nothing; if the task is already catalogued
it tells you and links straight to it.

## This device

One display setting, kept in **this browser** rather than in your settings file — so the
same account can have it one way on the phone and another way at the desk.

**Blur behind popups.** The gallery's popups — the Panel itself and its own sub-windows
(Trash, the accounts pages, the Stop/Restart confirm), the Folio, My Art, Contests,
Publish, the command palette, the AI Tools catalog, the Generate dock's settings
— dim the gallery behind them and blur it. The blur is the expensive half: for as long as
the popup is open the browser is
re-blurring your whole library behind it, and on a phone or an older laptop that is the
single heaviest thing on screen.

Switch it **Off** and popups keep the dark backdrop exactly as before; the pictures behind
it just stay sharp. It applies the moment you click it, including to the Panel you clicked
it in, and it is remembered for next time on this device only. Turning it back **On**
restores the same blur — nothing else about how popups look or open changes either way.

The same switch is on the phone's **Control** screen.

## Identity

The **mark** beside the title and the **skin** the whole suite wears, in one strip at the
foot of the Maintenance tab, with a small sample showing the two together — a mark and a
palette are judged as a pair, so they are picked as one.

Free marks and unlocked skins are one click each and apply everywhere immediately; the
skin is saved to your account and follows you to every device. Anything still locked is
shown rather than hidden — a gold 🔒 tile that names what unlocks it when you hover over
it.

### Type

Five curated pairs of faces — one for the italic display voice (titles, headings, the
sample above) and one for everything else. Tap a pair and both change at once, everywhere.

Both faces come off **your own machine**: nothing is downloaded and nothing is served, so
the picker costs nothing to load and works with no network at all. A face a particular
computer doesn't have falls back inside the same pair, which is why each one is a short
list rather than a single name. Monospaced labels — the small uppercase kickers all over
the app — never change; they are meant to read as machine type whatever else is on screen.

Your pair is remembered **in this browser**, like the popup-blur switch above and unlike
the skin: the same account can read Verdana on the phone and Palatino at the desk. It is
applied before the page paints, so there is no flash of the old face on the way in.

## Live Mirror

A status readout for the push connection that mirrors each generation the instant it
finishes: connected or reconnecting, when the last event arrived, and how many items it has
mirrored this session. It's read-only, free, and always on while the server runs — which is
why `--update` is a fallback rather than the only way new work lands locally.

> Not to be confused with **Mirror to PixAI website** (Maintenance tab, below), which goes the
> *other* direction. Live Mirror pulls what you make on PixAI *into* your local library;
> Mirror to PixAI website files what you make *in Moonglade* out to your PixAI web library.

## Mirror to PixAI website

*(Maintenance tab.)* Off by default. When it's on, each new generation you make in Moonglade
is also filed into your **pixai.art web library** — the same place things land when you
generate on the website — instead of living only in your local backup. Handy if you like
having your work visible in your PixAI account too. When it's off, nothing changes.

It works by riding your own logged-in browser session:

1. Click **Connect…**. Moonglade reads the session from a browser signed in to PixAI **on
   the server machine** (Chrome, Edge, or Brave). Nothing is pasted, and the credential
   never leaves that machine — the tile shows *Connected · N days left*, never the token.
2. Flip the toggle to **on**. It refuses to turn on until a session is connected, and tells
   you so.
3. From then on it renews itself; you'll only need **Refresh session** if you sign out of
   PixAI in the browser or the tile drops back to *Not connected*.

Things worth knowing:

- Generations filed this way follow the **website's** content policy, not the stricter
  mobile-app one — the same rules as generating on pixai.art in a browser.
- **Every spend guard still applies.** `READ_ONLY` blocks it like everything else, it's a
  single create per submit, and if the session isn't usable it **refuses and spends
  nothing** rather than quietly falling back to your API key. See
  [Trust & Safety](Trust-and-Safety).
- `python moonglade_backup.py --mirror-check` verifies the renewal loop from the command
  line without spending anything.

## Server

- **↻ Restart server** — needs the managed **`Serve Gallery`** launcher (it relaunches the
  process); the button is disabled when the server was started headlessly.
- **■ Stop server** — shuts it down cleanly from the browser. No Task Manager.

Both are available to any signed-in session. A reconnect overlay waits for the server to
come back after a restart.

## Updates

Moonglade watches for new releases **while it is running** — it asks about once an hour, so
you find out that a version is out without having to come and look. When one turns up it
says so in three places at once: the **version stamp** at the foot of this sidebar turns
gold and reads *"v3.7.3 available — view"*, a single notice appears in the corner of
whatever screen you are on, and the stamp opens the update window when you click it.

**It never installs anything by itself.** The check tells you a release exists and stops
there; the update is pulled, applied and restarted only when you press **Update now** in
that window and confirm it. There is no silent update and no automatic one — see
[FAQ](FAQ) for what pressing it actually does.

**An update that worked says so when the app comes back.** Pressing **Update now** ends in
the page reloading into the new version, and a small note appears in the corner on the way
back in — *"Updated to v3.8.1"* — and waits there until you close it. It is checked, not
assumed: the note appears only when the version the app is really running is the one you
were promised. An update that failed or was rolled back says nothing at all, and cannot say
it later against some future release that happens to match. It appears once, for the update
that earned it; reloading the page again does not bring it back.

The corner notice appears **once per version** — not once an hour, and not again the next
time you load the page. Opening this Panel asks GitHub for a fresh answer rather than
showing you one that could be half an hour old; opening and closing it repeatedly costs
nothing, and neither does the hourly check (roughly two dozen requests a day against an
allowance of sixty an hour). A machine that is offline simply doesn't hear anything — the
check is deliberately quiet about its own failures.

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
tasks it never starts at about 60 minutes. The Generate dock's own runs strip shows the same
figure on a queued tile, in the same words — see
[Generating](Generating).

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

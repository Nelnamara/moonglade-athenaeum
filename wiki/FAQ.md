# FAQ

**Is this official / affiliated with PixAI?**
No. It's an unofficial, independently-run client that uses your own API key plus PixAI's
private frontend queries. Anyone can self-host it against their own account. PixAI's
terms grant you copyright of your own generations.

**Will this get my account banned / does it steal credits?**
It's built to do the opposite of abuse: it only reads/manages *your own* account,
defaults to the **cheaper** generation priority, has no purchase automation, and is
rate-paced to be polite. It does claim PixAI's own free rewards (`--claims`/`--claim`,
daily credits + agent stamina) and auto-apply your free cards — self-service on your
own account, not farming. `--claims` now separates "you have nothing to claim" from "I
couldn't read your rewards": a request that failed says so plainly and tells you to re-run
in a minute, instead of reporting the same cheerful *No claimable rewards found* it reports
for a genuinely empty account. They look identical and mean opposite things, and the one
that matters is the one where a ready reward is sitting there waiting. Nothing is claimed
either way. Generation spends your own credits: the CLI always asks
(`--confirm` is required to submit), while the web Generate drawer submits on click and
shows a live price estimate up front instead. One thing to know about video cards: they are
books of tickets, a clip costs one per 5 seconds, and if you don't hold enough for the
duration no card is used and the clip is charged in full — the preview says so plainly, and
Generate still spends if you click (see [Generating → Free cards and
videos](Generating#free-cards-and-videos)). For the full, precise list of what this
tool can and can't do to your account — plus a `READ_ONLY` config flag that refuses
every spend/delete path outright — see **[Trust & Safety](Trust-and-Safety)**.

**Do I really only need an API key?**
Yes. `USER_ID` auto-resolves from the key and the persisted-query hashes ship as
defaults. See [Setup](Setup) and [How It Works](How-It-Works).

**Why are there "hashes" if I don't need to set them?**
They're public identifiers of PixAI's own frontend queries (not secrets), baked in so
you don't capture anything. If PixAI overhauls their frontend and one goes stale, you
don't recapture it yourself — see [Troubleshooting](Troubleshooting): update to the
latest release, or open an issue so the shared default gets refreshed for everyone.

**Where do my files and credentials go?**
Everything is local. `config.json`, `token.txt`, and `pixai_backup/` are git-ignored.
Nothing phones home.

**Can I run it on my phone/tablet?**
Yes — launch the gallery with `--host 0.0.0.0 --https` and open it on your device
(installable as a PWA). [Select mode](Collections) is touch-friendly.

On a portrait phone the Generate drawer opens as a full-width sheet and the model browser
appears as a centred panel, with finger-sized dock and close buttons. (Before 2026-07-24 the
drawer left a dead strip down one side and the model browser opened half off the top of the
screen — if that is what you remember seeing, update.)

**As of v2.0.0 this needs a login, and a signed-in device can do real work.** The gallery
requires an account on every path — including on the machine running it. Sign in from your
phone and you can browse *and* generate, which is the point: the login exists so tablet
generation is possible, not to keep you out.

The rule is drawn around what you cannot take back: **permanent deletion, writes to
`config.json`, the destructive maintenance jobs, and creating a login are localhost-only;
everything else — including spending your credits — works from any signed-in device.**

So generating, editing and Fix all work over the LAN, as do rating, collections, The Loom, CSV
export, claiming rewards, the maintenance jobs that aren't marked destructive, and ordinary
delete-to-Trash and restore-from-Trash (your file moves, but you can move it back — which is why
moving files is not itself the thing that gets gated). What needs the machine running the server,
no matter who is signed in: the
destructive Control Panel jobs (organize, undo-organize, dedup-apply, dedup-delete,
restore-orphans, rebuild-thumbnails) plus cancelling a job or editing the schedule; emptying the
Trash or deleting from it forever; deleting from your PixAI account, per-image or in bulk;
setting the API key, the library folder, or the launcher icon; importing local files (**↑ Import**
/ `--import-local`); and changing the account roster — adding an account, removing someone
*else's*, or resetting someone else's password.

Still use a trusted network: the app is served over plain HTTP unless you pass `--https`,
and a signed-in session on a shared network can spend your credits.

**How do I add another person, or get back in if I'm locked out?**

Add accounts from **Panel → Users**, signed in **on the machine running the gallery** — the
**Add user** form only appears there, and the route refuses a LAN request outright. Any account
may do it; none may do it from across the network. There's no admin role — all accounts are
equal-trust, and the gate asks *where you're sitting*, never *who you are*, so this stops your own
tablet too. (The two account operations you can do to *yourself* from anywhere — change your own
password, remove your own account — aren't an exception to that: they turn on whose account is
being changed, not on any power your login holds. And removing your own account is still refused
when it's the last one left, from every address.) The login page *creates* an account only during
first-run setup (on the server's own machine, before any account exists), so once you've made
yours it goes back to sign-in only and no one on your network can register themselves. That's by
design — it's your library and your PixAI account behind it, not a public signup, and every
extra account is another key to both.

Locked out with an account already there? On the server machine,
The Control Panel's **Users** tab handles this in the browser — change your own password from
anywhere, or reset another account's when you're on the server machine. The CLI is the
fallback for being locked out of the only account:
`python moonglade_backup.py --add-web-user` prompts (hidden) for a username and password and
writes it to `config.json`. It *adds or updates*, so it also resets a forgotten password;
`--list-web-users` and `--remove-web-user <name>` are the companions. Full flow in
[Setup](Setup).

**Does organizing files break the gallery?**
No. Lookups are by `media_id`, so files can live in any subfolder.
[Collections](Collections) are catalog-based and survive Organize too.

**How do I update?**
**Moonglade tells you when there is something to update to.** While it runs it checks for a
new release about once an hour, and when one turns up a notice appears in the corner —
*"Moonglade v3.7.3 is ready — open the Control Panel to update"* — once per version, wherever
in the app you are. **Open the Control Panel** (it re-checks on the spot) and the version
stamp at the bottom of its sidebar is gold: *"v3.7.3 available — view"*. Click it and the
confirm tells you what will happen — the update is pulled atomically, dependencies install
only if they changed, the server restarts, and the tab reloads itself.
Nothing is applied until you press **Update now**; there is no silent update, ever. The app
notices releases by itself; it never installs one by itself.

Press it and that same window turns into the progress of the update — **pull**, then
**applying files**, then **restart** — ticking each one off as it really finishes, with how
long it took. The restart is the one step nobody can watch (the server is away), so it
shows what your machine's last restart took. When the third tick lands the window closes
itself and the version at the foot of the sidebar is the new one. If the update is refused
or fails, the refusal appears in the same window in place of the progress bar rather than
as a message you might miss.

The one-click path needs the managed launcher (**`Serve Gallery.pyw`**) — without it the
server would stop instead of restarting into the new version — and a clean checkout on
`master`. If yours is a working copy with local edits, or on a branch, the Panel says so
rather than touching it.

**By hand**, always available: `git pull`, then **restart the gallery server** so it loads
the new code (Stop/Restart, or relaunch `Serve Gallery.pyw`) and hard-refresh the browser —
see [Troubleshooting](Troubleshooting).

**Something broke after a PixAI change.**
See [Troubleshooting](Troubleshooting): update to the latest release first, or open an
issue if it's still broken.

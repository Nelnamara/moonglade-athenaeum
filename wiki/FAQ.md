# FAQ

**Is this official / affiliated with PixAI?**
No. It's an unofficial personal-use tool that uses your own API key plus PixAI's
private frontend queries. PixAI's terms grant you copyright of your own generations.

**Will this get my account banned / does it steal credits?**
It's built to do the opposite of abuse: it only reads/manages *your own* account,
defaults to the **cheaper** generation priority, has no purchase automation, and is
rate-paced to be polite. It does claim PixAI's own free rewards (`--claims`/`--claim`,
daily credits + agent stamina) and auto-apply your free cards — self-service on your
own account, not farming. Generation spends your own credits: the CLI always asks
(`--confirm` is required to submit), while the web Generate drawer submits on click and
shows a live price estimate up front instead. For the full, precise list of what this
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

**As of v2.0.0 this needs a login, and a signed-in device can do real work.** The gallery
requires an account on every path — including on the machine running it. Sign in from your
phone and you can browse *and* generate, which is the point: the login exists so tablet
generation is possible, not to keep you out.

A few things stay stricter than "signed in", because they act on the server machine itself
or delete irreversibly from your PixAI account: the destructive Control Panel jobs
(organize, dedup-apply, rebuild-thumbnails), cloud bulk-delete, setting the API key or
launcher icon, and importing local files into your library (**↑ Import** / `--import-local`).
Those require a request from the machine running the server, no matter who is signed in.

Still use a trusted network: the app is served over plain HTTP unless you pass `--https`,
and a signed-in session on a shared network can spend your credits.

**How do I add another person, or get back in if I'm locked out?**

Add accounts from **Panel → Users** once you're signed in — any account can, since they're all
equal-trust (there's no separate admin role). The login page *creates* an account only during
first-run setup (on the server's own machine, before any account exists), so once you've made
yours it goes back to sign-in only and no one on your network can register themselves. That's
by design — it's your library and your PixAI account behind it, not a public signup.

Locked out with an account already there? On the server machine,
`python pixai_gallery_backup.py --add-web-user` prompts (hidden) for a username and password and
writes it to `config.json`. It *adds or updates*, so it also resets a forgotten password;
`--list-web-users` and `--remove-web-user <name>` are the companions. Full flow in
[Setup](Setup).

**Does organizing files break the gallery?**
No. Lookups are by `media_id`, so files can live in any subfolder.
[Collections](Collections) are catalog-based and survive Organize too.

**How do I update?**
`git pull`. If using the GUI, **fully quit and reopen it** (Stop/Launch doesn't
reload the code) — see [Troubleshooting](Troubleshooting).

**Something broke after a PixAI change.**
See [Troubleshooting](Troubleshooting): update to the latest release first, or open an
issue if it's still broken.

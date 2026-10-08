# Setup

## 1. Install

Python 3.9+ (`python --version`), then:

```bash
pip install -r requirements.txt
```

| Package | Needed for |
|---|---|
| `requests` | all network operations (required) |
| `pillow` | thumbnails, conversion, metadata embedding |
| `flask` | the local web gallery (`moonglade/gallery.py`) |
| `websockets` | `--watch` / `--watch-backup`, and the web gallery's auto-starting live-mirror thread |
| `truststore` | optional — fixes HTTPS cert errors behind corporate proxies / AV |
| `cryptography` (**not** in `requirements.txt` — `pip install cryptography` separately) | optional — only for the gallery's `--https` mode |
| `ffmpeg` (on PATH) | optional — posters for backed-up/imported videos; required for The Loom's video export, last-frame splice, re-anchor and music bed, and it cuts the frames the Loom's continuity ribbon shows |
| `pytest`, `pytest-mock`, `pytest-cov` | dev only — running the test suite |

## 2. Configure — one value

**In the browser (recommended):** once you've signed in (below), a fresh install with no
key yet walks you through pasting one and running the first sync right there. If the art
pack (the app's own artwork, the file `moonglade.mgpack` in the `local` folder beside the program) hasn't arrived yet
it is fetched first — a one-time download with a progress bar (**↻ Try again** if it is
interrupted, or **Continue without the default artwork** to let it finish later). An install
that still has the pack under its old name, `moonglade.dat`, or beside the program where 3.19
kept it, renames it and moves it into `local` by itself when the app starts, so a current pack is
never downloaded twice. Then a short intro, a spot to paste the key (validated for
real before it's saved), a live sync progress screen, and a **Welcome home.** screen with what
your library holds. Nothing to edit by hand. Skip to [3. First run](#3-first-run) if you're
doing it this way.

**By hand (headless / scripting):** copy `config.example.json` to `config.json`
(git-ignored) and set **one** value:

```json
{ "PIXAI_API_KEY": "your-api-key" }
```

`config.json` is only for what you type yourself: the key, the logins, `READ_ONLY` and the
overrides. What you set in the Control Panel (the library folder, the port, LAN discovery, the
Mirror switch, branding) the app keeps in `local\settings.json` beside the program. See
[Where Things Live](Where-Things-Live).

Generate a key at [pixai.art → Profile → Settings → API](https://pixai.art) (requires
membership; lifetime up to ~2 years). It's the Bearer credential for **every** call, and:

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

Run every command in this guide from the app's folder (the one holding `config.json`):
`python -m moonglade` finds the app from there. From any other folder, name the code folder
instead: `python "C:\path\to\app\moonglade" --sync`. Before 3.20 the commands named the
files (`python moonglade_backup.py ...`); those files are gone. Going back to an earlier version
after 3.20 isn't supported, because it won't find your records or settings.

Web gallery (browse, generate, The Loom) — at [localhost:5000](http://localhost:5000):
```bash
python -m moonglade.gallery
```

**Create your login (v2.0.0+).** The gallery requires an account on every path, including on
the machine running it, so the first thing you'll see is the login page. On a fresh install
it offers to **create the first account** right there — no terminal step. That form appears
only for a request from the server's own machine while zero accounts exist, so nobody on
your network can claim the first account before you do. From then on, sign in with it from
any device.

**Adding more accounts.** The login page offers to *create* an account only during that
first-run bootstrap; once one account exists it goes back to sign-in only, so nobody on your
network can register themselves — deliberate, since it's your library and your PixAI account
behind it. To add a person or a second device after that, open **Panel → Users** *on the
machine running the gallery* and add them there. **Adding an account is localhost-only.** The
**Add user** form isn't even drawn for a browser that reached the Panel across the network,
and a request made by hand comes back `localhost-only` (403). The reason is real rather than
bureaucratic: a new account is a permanent key to your whole library and can spend your PixAI
credits, so minting one sits in the same tier as removing somebody else's account or resetting
their password — an owner-at-the-keyboard action.

That's not an admin role; there isn't one. Every account carries equal trust: once signed in, any
of them can browse, **generate, edit and run Fix**, curate, use The Loom, move things to the
Trash and pull them back out again, and run the safe maintenance jobs — and none of them can do
anything the others can't. What differs is *where you're sitting*, not who you are — sign
in as yourself from a tablet and minting an account is refused exactly as it would be for a
guest. Sit down at the server machine and the restriction lifts, whichever account you used.

The only account operations that turn on a username at all are the two you aim at *yourself*:
you may change your own password from anywhere (typing the current one), and remove your own
account from anywhere — unless it's the last one, which is refused everywhere. That isn't a
privilege tier either; it's the difference between acting on yourself and acting on someone else.

**Resetting a password.** Usually you don't need the command line for this: the Control
Panel's **Users** tab can change your own password from anywhere, and can reset any other
account when you're browsing from the server machine itself — see
[Control Panel](Control-Panel). The CLI below is the fallback for the one case the browser
can't cover: you're locked out of the *only* account, so you can't sign in to reach the
Panel at all.

**Locked out, or resetting a forgotten password.** On the server machine,
`python -m moonglade --add-web-user` prompts for a username (typed normally) and a
password (hidden — never echoed) and writes the hash straight to `config.json`. It *adds or updates*, so it doubles
as a password reset for an existing name. Companions: `--list-web-users` shows who exists,
`--remove-web-user <name>` deletes one — including the *last* one, which is the point: the count
drops to zero and the first-run bootstrap re-opens on the server machine, a deliberate escape
hatch rather than a bug. The Panel's **Remove** button deliberately won't do that from any
address, loopback included, so emptying the roster on purpose stays a CLI act you have to mean.

Prefer a double-click, no-console launcher? Use **`Moonglade Launcher.pyw`** — it starts the web
gallery (and supervises it) without a terminal window.

Headless:
```bash
python -m moonglade --probe          # connection sanity check
python -m moonglade --count          # how many images you have
python -m moonglade --max 40         # small test download
python -m moonglade                  # download everything
```

Everything lands in `pixai_backup/` (git-ignored). Next: **[Backing Up](Backing-Up)**.

**Finding your way around.** The first time you open the gallery, the Generate dock, The Loom,
the Folio and the Control Panel, a small welcome card offers a short tour (or **Got it** to skip
it), and a round **?** — or the **?** key — opens this wiki inside the app. See
[Help inside the app](Home#help-inside-the-app).

# Setup

## 1. Install

Python 3.8+ (`python --version`), then:

```bash
pip install -r requirements.txt
```

| Package | Needed for |
|---|---|
| `requests` | all network operations (required) |
| `pillow` | thumbnails, conversion, metadata embedding |
| `flask` | the local web gallery (`pixai_gallery.py`) |
| `websockets` | `--watch` / `--watch-backup`, and the web gallery's auto-starting live-mirror thread |
| `truststore` | optional — fixes HTTPS cert errors behind corporate proxies / AV |
| `cryptography` (**not** in `requirements.txt` — `pip install cryptography` separately) | optional — only for the gallery's `--https` mode |
| `ffmpeg` (on PATH) | optional — posters for backed-up/imported videos; required for The Loom's video export and last-frame extract |
| `pytest`, `pytest-mock`, `pytest-cov` | dev only — running the test suite |

## 2. Configure — one value

Copy `config.example.json` to `config.json` (git-ignored) and set **one** value:

```json
{ "PIXAI_API_KEY": "your-api-key" }
```

Generate a key at [platform.pixai.art](https://platform.pixai.art) (lifetime up to
~2 years). It's the Bearer credential for **every** call, and:

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

Web gallery (browse, generate, The Loom) — at [localhost:5000](http://localhost:5000):
```bash
python pixai_gallery.py --out pixai_backup
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
behind it. To add a person or a second device after that, open **Panel → Users** and add them
there. Any signed-in session can: every account carries equal trust, there's no separate admin
role.

**Locked out, or resetting a forgotten password.** On the server machine,
`python pixai_gallery_backup.py --add-web-user` prompts for a username (typed normally) and a
password (hidden — never echoed) and writes the hash straight to `config.json`. It *adds or updates*, so it doubles
as a password reset for an existing name. Companions: `--list-web-users` shows who exists,
`--remove-web-user <name>` deletes one. (Remove the last account and the first-run bootstrap
re-opens on the server machine — a deliberate escape hatch, not a bug.)

Prefer a double-click, no-console launcher? Use **`Serve Gallery.pyw`** — it starts the web
gallery (and supervises it) without a terminal window.

Headless:
```bash
python pixai_gallery_backup.py --probe   # connection sanity check
python pixai_gallery_backup.py --count   # how many images you have
python pixai_gallery_backup.py --max 40  # small test download
python pixai_gallery_backup.py           # download everything
```

Everything lands in `pixai_backup/` (git-ignored). Next: **[Backing Up](Backing-Up)**.

# Trust & safety — what this tool can and can't do to your account

One page, plain language, for anyone deciding whether to hand this tool their PixAI API key.

## What it can do

- **Spend credits** — generating an image, video, edit, or reference-video, or running an
  enhance/hand-face-fix workflow. Every one of these is gated: on the CLI you must pass
  `--confirm`; in the web app, the button click you press *is* the confirmation (there's no
  extra network step hiding behind it). Nothing spends silently in the background.
- **Delete a task from your PixAI account** — irreversible on PixAI's side. Gated behind
  `--apply` plus typing the word `delete` on the CLI (skippable with `--yes` only if you pass
  it explicitly), or typing `DELETE` in the gallery's confirm dialog.
- **Claim your own daily rewards** (credits/stamina) — a routine entitlement, not something
  that costs you anything, but it's still a real account change, so it's covered by the same
  guarantees below.
- **Read** your generation history, account/credit balance, and free-card status.

## What it will never do

- **Move money.** There is no payment or subscription code path in this tool at all — not
  behind a flag, not commented out, not planned. `--account` only ever *reads* your
  credits/membership status.
- **Touch anyone's account but yours.** Every request rides your own API key.
- **Be reached by anyone who hasn't signed in.** As of **v2.0.0** the gallery is default-deny:
  every route except the login page itself requires an account, and that applies on the
  machine running the server exactly as it does over the network. Nothing is browsable
  anonymously — the only things served without an account are the login page itself, its own
  sign-out endpoint (a harmless no-op if nobody's signed in — needed so a stale cookie can
  still be cleared locally), and the static pieces the login page needs to render: your
  branding art and the web-app manifest, none of which carries any library content. Sessions
  are signed cookies over scrypt-hashed passwords,
  rate-limited per address. **Sign out** signs you out *everywhere* — it revokes every
  outstanding session for that account on every device, which is what makes it the right thing
  to press if you think a session was captured. (Simply visiting the sign-out URL, rather than
  pressing the button, only clears the browser you're sitting at; nothing that merely *links*
  to it can knock your other devices offline.) **Sign out also clears anything your browser
  cached locally** — installing this as an app (see [FAQ](FAQ)) keeps a copy of images you've
  viewed so it can work offline, and signing out deletes that local copy too, so a shared or
  borrowed device doesn't keep showing them after you sign out.
  Account creation is **closed after the first local bootstrap**: the login page mints the very
  first account (only from the server's own machine, only while none exist), then never offers
  signup again. New accounts come only from **Panel → Users** (any signed-in session) or the
  `--add-web-user` CLI on the server machine — never a public registration form. Removing the
  last account re-opens that first-run bootstrap locally, which is the deliberate lockout
  escape hatch.

- **Touch the server machine, or irreversibly delete from your PixAI account, from another
  device — even signed in.** A signed-in phone or tablet *can* browse and generate; that is
  the point of the login. But three things stay stricter and require a request from the
  machine running the server no matter who is signed in: the destructive Control Panel jobs
  (organize, dedup-apply, rebuild-thumbnails, plus cancelling a running job and editing the
  schedule), cloud bulk-delete, writing the API key or launcher icon, and importing local
  files into your library (the **↑ Import** drop-zone / `--import-local`, which copies files
  onto the server machine). Those act on your files or delete from PixAI permanently, which is
  a different class of trust than spending credits.
- **Send your credentials anywhere but PixAI's own API.** `config.json` (your API key) and
  the git-ignored `private/` notes never leave your machine and are never logged or uploaded.

## The `READ_ONLY` flag

If you want a hard guarantee that nothing above can happen — for a first run, for testing,
for handing the tool to someone else — add this to your `config.json`:

```json
{ "READ_ONLY": true }
```

With it set, every path that can actually mutate your account — submitting a generation
(image, video, reference video, an edit, or an enhance), submitting a hand/face fix, deleting
a task, or claiming a reward — refuses itself with a clear error, **regardless of `--confirm`,
`--apply`, or `--yes`**, whether you triggered it from the CLI or the web app. Those flags
exist to skip prompts on a run you already trust; `READ_ONLY` is for a run you don't want to
trust yet, so it overrides them rather than just changing their default. Browsing, backing up,
and searching your existing catalog all keep working normally — only the account-mutating
paths refuse.

`READ_ONLY` does **not** cover purely local operations (`--organize`, `--dedup`) — those never
touch the network in the first place, so there's no account to protect. They're safe in a
different way, and **not the same way as each other**: `--dedup` is dry-run by default (an
explicit `--apply` makes it act), while `--organize` runs live by default and is instead
opted *out* of with `--dry-run` — its safety net is that moves are reversible
(`organize_manifest.csv` + `--undo-organize`), not that it waits for permission first. This
flag is specifically about your PixAI *account*, not your local files.

## Found a real gap in any of this?

If you find a way for a request to spend, delete, or read data it shouldn't, please **don't**
open a public issue — see the Security section of
[`CONTRIBUTING.md`](https://github.com/Nelnamara/moonglade-athenaeum/blob/master/CONTRIBUTING.md#security)
for how to report it privately.

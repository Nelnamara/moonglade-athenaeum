# Trust & safety — what this tool can and can't do to your account

One page, plain language, for anyone deciding whether to hand this tool their PixAI API key.

## What it can do

- **Spend credits** — generating an image, video, edit, or reference-video, or running a
  hand/face fix. Every one of these is gated: on the CLI you must pass `--confirm`; in the web
  app, the button click you press *is* the confirmation (there's no extra network step hiding
  behind it). Nothing spends silently in the background. (The **art filters** on the Edit tab are
  not in this list: they are gradient composites applied in your own browser, and they make no
  network request and cost nothing.)
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
- **Charge you twice for one generation.** A submit is sent **once**, never re-sent. That
  sounds obvious, but it isn't free: the tool retries ordinary *reads* when the network
  hiccups, and until **2026-07-26** a submit was treated the same way. The danger is that a
  lost reply looks exactly like a lost request — if PixAI creates and charges for your
  generation and the answer never makes it back (a timeout, a dropped connection, a proxy
  erroring after the fact), a retry would quietly buy a second one. Now it can't: submits,
  edits, videos, uploads and cloud deletes all go out through a path that has no retry to
  give. If the network eats one, you get an error and decide for yourself whether to try
  again.
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
  signup again. New accounts come only from **Panel → Users** *on the machine running the
  server* or the `--add-web-user` CLI there — never a public registration form, and never from
  across the network even with a valid session. A minted account is a lasting key to the whole
  library and to your PixAI spend, so it takes more than an open tab to create one. The lockout
  escape hatch is deliberately **CLI-only**: `--remove-web-user` on the server machine will take
  the count to zero and re-open that first-run bootstrap. The Panel's **Remove** button will
  not — it refuses to remove the *last remaining* account from every address, loopback included,
  because a browser is far too easy a place to strand yourself from with one click.

- **Touch the server machine, irreversibly delete anything, or hand out access to it, from
  another device — even signed in.** The boundary is drawn around **what you cannot take back**,
  not around what touches files: **permanent deletion, writes to `config.json`, the destructive
  maintenance jobs, and creating a login are localhost-only; everything else — including spending
  your credits — works from any signed-in device.**

  Note what that deliberately does *not* say. It is not "anything that moves files", because
  delete-to-Trash moves your file and is allowed from anywhere — it is reversible. It is not
  "anything that runs a maintenance job", because most of them are allowed too. The question the
  tier boundary asks is only ever *can this be undone*.

  So a signed-in phone or tablet really does do the work, and that is the point of the login —
  it exists so tablet generation is *possible*, not to keep you out. **Generating, editing and
  Fix all run over the LAN**, and so do rating, collections, The Loom, CSV export, claiming your
  daily rewards, stopping and restarting the server, the maintenance jobs that aren't marked
  destructive, and ordinary **delete-to-Trash and restore-from-Trash** — reversible by
  construction, which is exactly why they are not gated. ("Not destructive" is not the same as
  "read-only": rebuilding the Similar index, for instance, drops and re-embeds it, which costs
  time but loses nothing you can't regenerate.)

  What stays on the machine running the server, no matter who is signed in: the **destructive**
  Control Panel jobs (organize and undo-organize, dedup `--apply` and dedup-delete,
  restore-orphans, rebuild-thumbnails), plus cancelling a running job and editing the schedule;
  **emptying the Trash, or deleting from it forever** — the one Trash action with no way back;
  **deleting from your PixAI account**, per-image or in bulk; writing the **API key**, the
  **library folder**, or the launcher icon; **importing local files** (the **↑ Import**
  drop-zone / `--import-local`, which copies files onto the server machine); and **changing who
  has an account** — creating one, removing an account other than your own, or resetting another
  account's password.

  The first group acts on your files, rewrites your `config.json`, or destroys something with no
  undo; the last hands somebody a durable login to the library and your credits, or takes theirs
  away. Both are a different class of trust than spending credits, which a signed-in device is
  deliberately allowed to do — a generation you regret costs you credits, and every item above
  costs you something you cannot buy back.

  This is not an admin tier in disguise, and the distinction is worth stating exactly. **No
  account holds a power another one lacks.** The gate never asks *who* you are, only *where you
  are sitting*: your own account is refused from the LAN exactly like a guest's, and any account
  can do all of the above while sitting at the server machine.

  Two operations additionally ask *whose account you are acting on* — which is still not a
  privilege tier, just the difference between acting on yourself and acting on someone else.
  Changing **your own** password works from anywhere (you have to type the current one);
  resetting **someone else's** needs the server machine. Removing **your own** account works
  from anywhere **unless it is the only account left** — that is refused from every address,
  loopback included, and the CLI escape hatch above is the only way past it. Removing **someone
  else's** needs the server machine.

  None of this is kept honest by hand. `tests/test_route_tiers.py` walks the app's own routing
  table — every route it has, not a list someone remembered to update — and fails the build if
  any of them lacks a declared tier or fails to enforce it against a live LAN request. If this
  page and the app ever disagree, that test is the tie-breaker, not this paragraph.

- **Send your credentials anywhere but PixAI's own API.** `config.json` (your API key) and
  the git-ignored `private/` notes never leave your machine and are never logged or uploaded.

## The `READ_ONLY` flag

If you want a hard guarantee that nothing above can happen — for a first run, for testing,
for handing the tool to someone else — add this to your `config.json`:

```json
{ "READ_ONLY": true }
```

With it set, every path that can actually mutate your account — submitting a generation
(image, video, reference video, or an edit), submitting a hand/face fix, deleting a task, or
claiming a reward — refuses itself with a clear error, **regardless of `--confirm`,
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

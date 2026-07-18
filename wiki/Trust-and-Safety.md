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
- **Spend or delete from another device on your network.** The web app's generate/edit/
  enhance/fix/delete/claim routes all check that the request came from the machine running
  the server (`127.0.0.1`/`localhost`) and refuse otherwise — a phone or laptop browsing your
  gallery over LAN can look, but cannot spend or delete. (Read-only browsing, on purpose, is
  not localhost-gated — that's what lets you browse your own gallery from another device.)
- **Send your credentials anywhere but PixAI's own API.** `config.json` (your API key) and
  the git-ignored `private/` notes never leave your machine and are never logged or uploaded.

## The `READ_ONLY` flag

If you want a hard guarantee that nothing above can happen — for a first run, for testing,
for handing the tool to someone else — add this to your `config.json`:

```json
{ "READ_ONLY": true }
```

With it set, every one of the four functions that can actually mutate your account
(submitting a generation, submitting a hand/face fix, deleting a task, claiming a reward)
refuses itself with a clear error — from the CLI *or* the web app, and **regardless of
`--confirm`, `--apply`, or `--yes`**. Those flags exist to skip prompts on a run you already
trust; `READ_ONLY` is for a run you don't want to trust yet, so it overrides them rather than
just changing their default. Browsing, backing up, and searching your existing catalog all
keep working normally — only the account-mutating paths refuse.

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

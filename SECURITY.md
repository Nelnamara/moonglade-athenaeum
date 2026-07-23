# Security Policy

Moonglade Athenaeum is a personal-scale project (see [CONTRIBUTING.md](CONTRIBUTING.md)),
but it's a real web app with real gated actions behind it — spending your PixAI credits,
deleting from your PixAI account, importing files onto the host machine, managing sign-in
accounts. A bug that lets one of those trigger from a request that shouldn't be allowed to
is a genuine security issue, not just a UI glitch. See
[Trust & Safety](https://github.com/Nelnamara/moonglade-athenaeum/wiki/Trust-and-Safety) for
what the app can and can't do to your account today.

## Reporting a vulnerability

**If you find a way for a request to spend credits, delete data, or read/change an account
it shouldn't be able to** — bypassing login, escalating a signed-in session's access, or
reaching a localhost-only route from another device — please **don't** open a public issue.
Email the address listed on the maintainer's GitHub profile
([github.com/Nelnamara](https://github.com/Nelnamara)) with what you found, how to reproduce
it, and its impact, so it can be fixed before it's public.

This is a one-person project, so response time isn't guaranteed on any particular schedule,
but real reports are taken seriously and fixed promptly.

Ordinary bugs (crashes, wrong output, UI glitches) don't need this process — file them as a
normal [issue](https://github.com/Nelnamara/moonglade-athenaeum/issues), per
[CONTRIBUTING.md](CONTRIBUTING.md#reporting-bugs).

## Supported versions

There's no maintained backport branch. Fixes land on the current default branch and go out
in the next tagged release — please upgrade to the latest release before reporting, and check
[`CHANGELOG.md`](CHANGELOG.md) for what's already shipped.

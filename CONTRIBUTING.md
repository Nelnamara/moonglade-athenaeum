# Contributing to Moonglade Athenaeum

Thanks for considering it. This is a personal-scale project — expect a smaller, slower
review loop than a big OSS repo, but real contributions are genuinely welcome.

## Before you start

For anything beyond a small fix, open an issue first describing what you want to change.
It saves both of us the work of a PR that doesn't fit the project's direction.

**Please don't build against `private/`.** A few files under `private/` (reverse-engineering
notes, the full PixAI operation catalog) are git-ignored on purpose — they're the
owner's own research notes, not a stable contract. If you need something from there to
build a feature, ask in an issue instead of trying to reconstruct it.

## Setup

```bash
git clone https://github.com/Nelnamara/moonglade-athenaeum.git
cd moonglade-athenaeum
pip install -r requirements.txt
cp config.example.json config.json   # add your own PIXAI_API_KEY
```

See the [Setup wiki page](https://github.com/Nelnamara/moonglade-athenaeum/wiki/Setup) for
the full walkthrough, and the [How It Works wiki page](https://github.com/Nelnamara/moonglade-athenaeum/wiki/How-It-Works)
for how the modules fit together.

## Running the tests

```bash
python -m pytest -q --ignore=tests/test_similar.py
```

(`tests/test_similar.py` needs the optional `pixeltable` dependency and skips itself
cleanly without it — drop the `--ignore` if you have it installed.)

The Loom's pure-logic modules have their own suite:

```bash
cd loom && node --test
```

**All tests must pass before a PR merges.** CI runs both suites on every pull request and
on pushes to `master` — you can (and should) run them locally first with the commands above,
since a feature-branch push alone does not trigger CI.

## Code style

There's no linter gate today — match the surrounding code's style rather than reformatting
whole files. A few conventions that matter more than usual here:

- **A file is located by its `media_id`** (the last `_`-chunk of the filename stem), not by
  a stored absolute path — and since 2026-08-23 that really is centralized. The **LIBRARY
  SCAN** section of `moonglade_gallery.py` owns the one walk of the library folder
  (`scan_library()`) and the one media-id lookup (`files_for()`, behind the historical name
  `find_files_for_media_id()`), along with the exclusion vocabulary, the `.part` skip, the
  extension taxonomy, `bucket_of()` and `media_id_of()`. Resume, the audit, `--organize`,
  `--import-local`, the Health walk and the Similar index each used to walk the tree with
  their own copy of those rules; they now pass their own `kinds`/`exclude` to the shared
  scan instead. If you add a file-by-media_id lookup or a new walk of the library, call into
  that section. If your caller genuinely needs a different rule, give it a `kinds`/`exclude`
  argument and write the disagreement down in the section header, alongside the six
  deliberate ones already recorded there — a private copy is how this drifted twice before.
- **Catalog schema changes** touch three places together: `CATALOG_FIELDS`, the `_CREATE_TABLE`
  DDL, and the `_MIGRATIONS` list (so existing databases pick up the column automatically).
  All three live in `moonglade_gallery.py`.
- **Never commit `config.json`** or anything with a real API key, user id, or hash in it.
  `config.example.json` is the template; it ships with placeholder values only.
- **HTTPS verification stays on.** Don't add `verify=False` anywhere, even temporarily.

## Pull requests

- Keep them focused — one fix or one feature per PR is much easier to review than a bundle.
- Add or update tests for what you changed. A PR that touches catalog logic, a Flask route,
  or the Loom's pure-logic modules without a test change is the exception, not the norm.
- Update `CHANGELOG.md`'s `[Unreleased]` section for anything user-visible.
- Describe *why*, not just *what* — the reasoning is what's hard to reconstruct later, the
  diff already shows the what.

## Reporting bugs

Open an issue with: what you did, what you expected, what actually happened, and — for
anything visual — a screenshot or screen recording. For anything involving your own PixAI
account or catalog contents, please don't paste real API keys, media ids, or prompts you'd
rather keep private; a redacted or synthetic repro is fine.

## Security

If you find something that could let a request from another machine spend credits, delete
data, or read another user's account, please don't open a public issue — email the address
in the GitHub profile instead so it can be fixed before it's public. Ordinary bugs (crashes,
wrong output, UI glitches) are fine as regular issues.

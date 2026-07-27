# CLAUDE.md — Project Context for Claude Code

This file is committed so it is available on every machine that clones the repo.

---

## What this project is

**Moonglade Athenaeum** — *"a library against the Void."* It began as a backup tool for the **owner's own** PixAI.art generations and grew into a full local PixAI **client**: back up · browse · generate · curate. Talks to the same API the browser uses, pages the entire history at full resolution, keeps a searchable SQLite catalog, **creates** new images via the API, and manages both the local archive and the cloud account. See `docs/architecture.md` for the module breakdown, function reference, and catalog schema.

Built by reverse-engineering site network traffic (catalogued privately in `private/API_OPERATIONS.md`, git-ignored). The `gql_adhoc()` ad-hoc POST path means most operations need no persisted-hash capture. There is no official API for listing your own generations. Be polite to their servers (paced requests). PixAI's terms grant users copyright of their generations. User-facing docs live in `docs/`.

---

## Working across machines (home ⇄ work) — READ THIS FIRST

This repo is edited from more than one machine. Cross-machine breakage here is almost
always **config drift, not real changes** — do not blame the user, do not "fix" it with a
mass commit. Follow this protocol:

1. **Line endings are pinned by `.gitattributes`** (LF in the repo). Do NOT change
   `core.autocrlf`, do NOT run line-ending "fixes", do NOT commit a mass line-ending diff.
   If `git status` shows *every* file modified, STOP — that's line-ending drift. Re-check
   `.gitattributes` is present and run `git add --renormalize .`; never `git checkout -- .`
   away someone's real work to make it "clean."
2. **`master` is the trunk.** Work on a short-lived feature branch and merge back with
   `--no-ff`. Do not commit directly to `master` for anything beyond a doc typo.
   (Historical note so an old transcript does not mislead: `loom-v2` was the long-running
   default branch through v2.5.0 and `naming-pass` after it. Both are merged and deleted --
   `git checkout loom-v2` will fail, and any instruction to do so is out of date.)
3. **Pull before you start, push when you stop:** `git pull --rebase --no-edit` at session
   start, `git push` at session end. This is what prevents "updates were rejected" /
   divergence. If push is rejected, it's the remote moving — pull --rebase, then push.
4. **Never `git add -A` / `git add .`** — stray untracked files live here (`config.json`,
   `.coverage`, `design_refs/`, old `pixai_*.py` side scripts). Stage **explicit paths** only.
5. **`config.json` + `private/` are git-ignored and machine-local** — they will NOT be on the
   other machine, and that's correct. Don't recreate, commit, or complain about their absence.
6. **Commits: no `Co-Authored-By: Claude` trailer** (standing preference).

## Session checkpoint protocol (anti-compaction drift) — owner-agreed

Long sessions get compacted; summaries lose design intent. Standing rule:

1. **Checkpoint** after every shipped increment (and before starting any new build): update
   **`docs/DECISIONS.md`** + `CHANGELOG.md [Unreleased]` (what shipped, dated) + memory with
   what shipped, what's in flight, and the decided NEXT STEPS. **This includes `wiki/` — there
   was a standing pre-1.9.1 practice of updating docs AND the wiki on every commit as needed;
   it silently dropped because it was never written down here, only followed by habit. Writing
   it down now (2026-07-15) so it can't drop again the same way.** If a shipped change is
   user-facing, check whether any `wiki/` page describes the area it touched and update it in
   the same pass — don't let the wiki decay into a separate, forgotten catch-up task.
2. **After any compaction**, the FIRST act is to re-read **`docs/DECISIONS.md`** and re-open every
   artifact/doc the next task depends on — never build from the conversation summary alone.
   Say what was re-read before proceeding.
3. **Flair/user-visible features** name their locked design source (artifact id / doc
   section) in the plan, and verification includes a "does it match what was decided" pass.
   A "locked" marker in a doc is a deliverable, not background.
4. **Visual builds require a PIXEL source of truth** (a Figma frame via the Figma plugin's MCP,
   a Claude Design project via DesignSync, or a locked mockup artifact) — never prose alone —
   and the verify pass compares against that source. Restyling a shipped, owner-approved surface
   needs an explicit owner go. See `docs/STANDARDS.md` Part 2 (originally `docs/DESIGN_WORKFLOW.md`,
   added 2026-07-15 `6a0f99d` after the Trophy Hall reformat landed off-target from prose notes;
   merged into STANDARDS.md 2026-07-17).
5. **Hierarchy when sources disagree:** for a measurable fact (test count, version, branch lead,
   release status) the **code/git/pytest/gh answer wins over every doc** — never trust a number a
   command can answer. For decisions already taken, `docs/DECISIONS.md` wins. For how it works,
   the code, then `docs/architecture.md`. For owner preferences, memory wins. A memory that
   describes code is verified against the code before acting on it.

## Architecture / request flow

There is no official API for listing your own generations, so a few personal-history
operations (listing, task detail) reuse the website's own interfaces, with working defaults
already shipped in the app — you never capture anything by hand. Auth is your official API
key (`PIXAI_API_KEY`), auto-resolving `USER_ID`; HTTPS verification is always on. Media URLs
come from `GET /v1/media/<mediaId>` (variant `PUBLIC`); videos expose their mp4 via the media
object's `fileUrl`. SSL trust store: `truststore.inject_into_ssl()` called at import if
present — fixes corporate/antivirus HTTPS interception.

> **Reverse-engineering detail (the persisted-query/hash mechanism, pagination internals,
> `gql_adhoc()` technique, Apollo header requirements) lives in `private/ARCHITECTURE_RE.md`**
> — git-ignored, not public. Read it there when you need the specifics; this section stays at
> the same redacted level as the public `docs/architecture.md` on purpose (owner's IP/security
> boundary, set 2026-07-04 — public docs describe how to USE the tool, never how it
> reverse-engineers PixAI). **This section was found duplicating the excised detail verbatim on
> 2026-07-15 — the 2026-07-04 redaction only touched `docs/architecture.md`, not this file. Do
> not let mechanism detail creep back into this section.**

---

## Module map, functions, catalog schema

Four modules, one shared SQLite catalog, on-disk layout, and the full function/helper
reference all live in **`docs/architecture.md`** — do not restate them here; that's how
this file drifted (a stale "three-file" table, a wrong function shape) badly enough that
`tests/test_docs_dont_hardcode_counts.py` had to exist.

---

## INVARIANTS — do not break

The seven numbered invariants (media_id parsing, resume ordering, incomplete-file
handling, catalog-as-source-of-truth, `--organize` normalization, gallery-thumbnail
exclusion, and the shared media-id → file matcher) are documented in full, with the
historical bugs each one prevents, in **`docs/architecture.md`**'s Invariants section.
Read them before touching resume, organize, or file-resolution code — they are not
stylistic preferences, each one is there because breaking it caused a real, previously
shipped bug.

---

## Critical constraints

- **NEVER** append `Co-Authored-By: Claude` trailers to commits.
- **NEVER** commit `config.json` — git-ignored; contains a real user credential (`PIXAI_API_KEY`). USER_ID, U3T and the hashes are optional legacy overrides, absent from a normal live file (`USER_ID` auto-resolves; the hashes ship baked-in).
- `token.txt`, `pixai_backup/`, `*.webp` are also git-ignored.
- No real credentials or user-specific values should appear in any committed file.
- All traffic is HTTPS with verification on; do not add `verify=False` anywhere.
- **Server page-size cap:** `last` above ~8,000–10,000 triggers a Prisma `Internal server error`. Keep download `--page-size` ≤ ~8,000.
- **A mutation that spends or changes the account goes through `gql_mutate()`, never
  `gql_adhoc()`.** `gql_mutate` hard-codes `retries=0` and offers no retries argument; a
  re-POST after a lost response (read timeout, dropped connection, proxy 502 *after* the
  backend succeeded) submits and pays for a SECOND generation. `gql_adhoc`'s default is
  document-aware as a backstop (0 for a mutation, 3 for a query), but new spend paths call
  `gql_mutate` so the intent is reviewable. Guarded by `tests/test_spend_no_retry.py`.
- **`READ_ONLY` in config.json overrides `--confirm`/`--apply`/`--yes`.** Any new code path that
  submits a generation, submits a fix, deletes a task, or claims a reward must call
  `_check_read_only(...)` before the network call fires — it is not optional per-path opt-in,
  it is the contract the `Trust & Safety` wiki page makes to users. See
  `submit_generation`/`submit_fixer`/`delete_task_gql`/`claim_reward` for the pattern.

---

## Security & GitHub hygiene

- `config.json` is git-ignored and will never be committed.
- `config.example.json` (committed) shows the required structure with placeholder values only.
- The output folder (`pixai_backup/`) contains images, prompts, and catalog — git-ignored.
- The repo is public on GitHub at `Nelnamara/moonglade-athenaeum` (only the local directory is still named `pixai-gallery-backup`).

---

## Deleting tasks from your account (`--delete-task`)

- `deleteGenerationTask` is a persisted **mutation** sent by POST (Apollo blocks mutations over GET), unlike the GET listing/query path. It is a **void mutation: it returns `null` on success** — the meaningful signal is the ABSENCE of a GraphQL error, NOT the payload. (Verified against a real task via the site, which shows a "Task has been deleted" toast off that same null/no-error response. `getTaskById` is NOT a valid post-delete existence check — it still resolves deleted tasks.)
- Hash ships with a **built-in default** — no manual capture step. `DELETE_TASK_HASH` in `config.json` only *overrides* it if the hash rotates. Deletion is NOT gated by the hash being absent; the guards below (`--apply` + the typed confirm) are what stand between you and a real delete.
- Guards: dry-run by default; `--apply` to perform; typed `delete` confirmation unless `--yes` (refused on non-interactive stdin). Single-attempt per task.
- Deletes ONLY the cloud generation; local image files + `catalog.db` are left intact.

> **Reverse-engineering detail (frontend handler flow, sibling mutations, hash-capture
> method) lives in `private/RE_NOTES.md`** — git-ignored, not public. Read it there when
> you need it.

## Logging (`-v` / `--verbose`, and the persistent file log)

- `set_verbose()` + `vlog()`: timestamped diagnostics (per-page fetch, per-image resolve/download timing, startup disk-scan time) to stdout. Console output is a no-op until enabled with `-v` / `--verbose`.
- `moonglade_logging.py` is the persistent baseline: a rotating file at `out_dir/logs/moonglade.log`, always on regardless of `-v` (only the console mirror is verbose-gated). See `docs/architecture.md`'s module reference for the full design.

## Recapture procedure (when PixAI changes their frontend)

Symptoms: `PersistedQueryNotFound`, "Cannot query field…", or sudden 400s. Step-by-step
recapture is in `private/RE_NOTES.md`.

---

## Creating, the web suite, and feature history

All creation (generate/video/reference-video/edit/upload/cards) rides one
`createGenerationTask` mutation over `gql_mutate`, and every credit-spending path is
preview-only until `--confirm` — see `docs/architecture.md`'s function reference for the
per-command shapes and the **Quick command reference** below for usage. The Flask gallery
is a full web creation suite (Generate drawer, Picker, The Loom, live-events push, Control
Panel jobs, branding) — its structure lives in `docs/architecture.md`'s "The web suite"
section; dated history in `CHANGELOG.md`. Don't restate feature detail here —
that's how this file drifted badly enough to need `tests/test_docs_dont_hardcode_counts.py`.

`--sync`'s reconcile step (`run_reconcile_deleted`) is caught with a deliberately **BROAD
`except Exception`** — do NOT narrow it to `except PixAIError`, or a transient network blip
during the advisory reconcile scan can crash a sync that already succeeded. Guarded by
`tests/test_sync.py`; full rationale in `docs/architecture.md`.

Achievement/Folio-of-Honors art direction (badge style anchor, tier palette, prompt bank)
lives in `docs/ART.md` — don't restate hexes or sizes here.

## Test suite

Full run instructions live in `docs/architecture.md`'s Testing section. **Never write the
test count in this or any live doc** — `tests/test_docs_dont_hardcode_counts.py` fails the
suite if you do; it was wrong in every one of six-plus files it was ever stated in, most
recently within hours of a "correction." All tests must pass before merging to master.

---

## Current state

**`docs/STATE.md` was stripped and deleted on 2026-07-27**, together with
`docs/AUDIT_2026-07-21.md` and the whole `docs/archive/` tree. It is gone on purpose: it
accumulated contradictions faster than they could be reconciled, which is the exact failure
its own "delete a fact that stops being true, never annotate" rule existed to prevent. Do
not recreate it, do not cite it, and do not treat any older instruction to checkpoint into
it as live — an instruction to update `STATE.md` is out of date by definition.

What survived lives in **`docs/DECISIONS.md`** (decisions already taken). Version, branch
lead, and release status are commands, not prose — ask git/pytest/gh, never a doc. Owner:
Nelnamara / Kil'jaeden — Balance Druid, WoW addon dev. Branch strategy: feature branches,
merge to master with `--no-ff`, tag releases.

## Changelog & releases

- **`CHANGELOG.md` (repo root) is the source of truth** — update its `[Unreleased]` section with
  every notable change, and cut it into a dated `## [x.y.z]` block when a release is tagged.
- Releases are **git tags** + **GitHub Releases**. Whether a given tag has a published Release is a
  live fact — `gh release list` against `git tag` — not something to transcribe here and let drift.
  Two durable history notes that a command *won't* tell you: Releases were published through **v1.6.0**,
  paused, then **v1.8.0–v1.10.0 were back-published on 2026-07-10** from reconstructed notes; and
  **there is no v1.7.x** (the series jumped 1.6.0 → 1.8.0).

---

## Quick command reference

```
python moonglade_backup.py --probe                    # connection sanity check
python moonglade_backup.py --count                    # tally tasks + images
python moonglade_backup.py --max 40                   # small test download
python moonglade_backup.py                            # full download (4 workers, 250/page)
python moonglade_backup.py --update                   # fast incremental: stop at already-downloaded history
python moonglade_backup.py --update --workers 8       # incremental + higher concurrency
python moonglade_backup.py --workers 8 --page-size 500  # fast full backfill
python moonglade_backup.py --no-full-meta             # faster pull, but rows land with no prompt/seed/model
python moonglade_backup.py --backfill-full-meta       # fill existing rows
python moonglade_backup.py --sync                     # ONE-SHOT refresh: pull+full-meta → fix-models → backfill → thumbnails → reconcile-deleted (idempotent)
python moonglade_backup.py --organize --dry-run       # preview month-folder normalize
python moonglade_backup.py --organize                 # normalize into YYYY-MM/ (reversible; --organize-adv is an alias)
python moonglade_backup.py --catalog-stats            # summarize catalog.db
python moonglade_backup.py --export-csv               # export catalog.db → CSV
python moonglade_backup.py --sync-artworks            # merge published-artwork metadata (title/likes/tags) by media_id
python moonglade_backup.py --audit                    # read-only duplicate report → audit_report.csv
python moonglade_backup.py --audit --no-content       # fast: same-media_id location dupes only
python moonglade_backup.py --dedup                    # dry-run dedup plan (nothing changes)
python moonglade_backup.py --dedup --apply            # quarantine redundant copies to _duplicates/
python moonglade_backup.py --dedup --apply --dedup-delete  # delete instead of quarantine
python moonglade_backup.py --verify-dupes             # confirm _duplicates/ is safe to delete
python moonglade_gallery.py --out pixai_backup                # launch gallery at :5000 (+ /health dashboard)
python moonglade_backup.py --delete-task <id> [<id> ...]        # DRY-RUN: list what would be deleted (nothing happens)
python moonglade_backup.py --delete-task <id> --apply --yes     # actually delete from your account (irreversible; null=success)
python moonglade_backup.py -v --update                # verbose: per-page / per-image timing diagnostics
python moonglade_backup.py --watch                    # live event stream (WS push): watch tasks complete
python moonglade_backup.py --watch --watch-backup     # + auto-collect each finished gen as it completes
python moonglade_backup.py --contests                 # list live PixAI contests (read-only)
# --- creating (all preview-only until --confirm; --task-id recovers a task for free) ---
python moonglade_backup.py --account                  # read-only credits/membership dashboard
python moonglade_backup.py --cards                    # read-only free-card (kaisuuken) balances + ids
python moonglade_backup.py --claims                   # read-only claimable rewards (daily credits, stamina)
python moonglade_backup.py --claim all --confirm      # claim ready rewards (gated; grants to your account)
python moonglade_backup.py --suggest-prompt <id|file> # image-to-prompt: tags + description (free)
python moonglade_backup.py --upload path/to/image.png # local file -> media_id (free; S3 upload)
python moonglade_backup.py --generate --prompt "..."               # preview an image gen (add --confirm to spend)
python moonglade_backup.py --generate-video --image <media_id> --prompt "..."   # preview i2v (EXPENSIVE; --confirm)
python moonglade_backup.py --reference-video --ref-image <id1> --ref-image <id2> --prompt "@image1 ... @image2 ..."  # preview multi-ref video
python moonglade_backup.py --edit-image --edit-src <media_id|file> --prompt "make it night"  # preview an edit
python moonglade_backup.py --generate-video --task-id <id> --dump-params  # recover a task (free) + print its full submit shape
```

**Free cards auto-apply** (shipped 2026-07-03): on `--confirm`, `_apply_kaisuuken` calls PixAI's
`/v2/kaisuuken/check` with the submit params, finds the nearest-expiry matching card, and attaches its
`kaisuukenId` → the generation costs **0 credits**, exactly like the website. Works for every create path
(generate / edit / video / reference-video). Preview prints FREE-vs-paid up front. `--no-card` forces
credits; `--kaisuuken-id <id>` forces a specific card. `--dump-params` banks any submit shape off a
recovered `--task-id` (no browser). Deep RE detail (incl. the full `/v2` REST surface) in git-ignored
`private/GENERATOR_SURFACE.md`.

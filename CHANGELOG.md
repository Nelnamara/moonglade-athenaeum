# Changelog

All notable changes to **Moonglade Athenaeum** — *a library against the Void.*

Format loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are
git tags. Full prose notes for tagged versions live on
[GitHub Releases](https://github.com/Nelnamara/moonglade-athenaeum/releases).

> **Maintenance note.** This file is the in-repo source of truth — **update the `[Unreleased]`
> section with every change, and cut it into a dated version block when you tag a release.**
> GitHub Releases are published through **v2.2.0** — publishing paused after **v1.6.0**, and
> **v1.8.0–v1.10.0 were back-published** on 2026-07-10 from tag messages + git history. **v1.11.0 is
> tagged but has no Release of its own** — its commits reached master as part of **v2.0.0**, which
> does have a Release. There is **no v1.7.x** (the series jumped 1.6.0 → 1.8.0).

## [Unreleased]

Overnight audit sweep against `docs/AUDIT_2026-07-21.md`'s remaining safe/small items —
8 parallel agents plus 7 cross-file gap-fills, ~40 real fixes total. 872 Python tests pass,
128 Loom tests pass, CI green.

### Removed

- **Internal dev/creative-process narration is out of the shipped code.** Code comments and
  test docstrings across `pixai_gallery.py`, `pixai_gallery_backup.py`, `static/mg-notify.js`,
  `static/mg-generate-drawer.js`, `loom/master-storyboard.jsx`, and seven test files no longer
  cite the git-ignored login mockup file, quote design-conversation directives, or carry
  "owner directive <date>" / Figma-provenance attributions — one such comment was even being
  served to every browser inside /login's `<style>` block. Each site now states its technical
  rationale on its own terms; product copy (achievement roasts, narrator voice) is untouched.

### Added

- **`paid_credit` is persisted — what every generation actually cost is now catalog data**
  (2026-07-23; data layer only, no UI/charts yet). New catalog column `paid_credit` (the
  server-reported actual credit cost of the row's task; `'0'` = free via card/daily,
  `''` = never captured; task-level, repeated on each of the task's media rows), added via
  the three-place schema contract so existing databases auto-upgrade losslessly. Stored at
  every site that sees the value: `--generate` / `--edit-image` / video runs, the web
  suite's collect path (`/api/task-status` → `collect_generation`, which also covers the
  `--watch-backup` live mirror and `--task-id` recovery), `--sync-videos`, and the
  `--full-meta` / `--backfill-full-meta` task-detail mapping. **Historical recovery works:**
  the task-detail record returns the cost for old tasks too, so new
  `--backfill-full-meta --with-credit` (the `--with-loras` pattern) fills the column for
  rows cataloged before cost tracking existed. Read-only surfacing: the MCP `get_image`
  detail JSON gains the field, and `--catalog-stats` prints a spend total (counted once
  per task, never per batch image).
- **The search box speaks field operators** (audit Tier 6, Curator #3). `key:value` tokens
  reach every sanely filterable catalog column from the one search string: text fields
  (`model:` `lora:` `tag:` `title:` `sampler:` `negative:` `natural:` `batch:` `status:`
  `filename:`) as case-insensitive substrings with the usual `*`/`?` wildcards; numbers
  (`rating:>=3`, `width:>1000`, `aes:>6`, `likes:`, `steps:`, `cfg:`, `clip_skip:`,
  `comments:`, `duration:`) with `>` `<` `>=` `<=` or exact; exact ids (`seed:` `task:`
  `media:` `artwork:` `model_id:`); `video:`/`published:`/`nsfw:` booleans;
  `created:2026-07` date prefixes (with `<`/`>` compares); and `collection:`/`source:`
  mirroring their dropdowns. Quoted values carry spaces (`model:"Ether Real"`); unknown
  keys and malformed values degrade to plain prompt text, search-engine style. Plain
  free text compiles to byte-identical SQL as before (regression-pinned), everything is
  parameter-bound (hostile-value tested), and because `_build_where` is shared the grid,
  prev/next navigation, the filtered CSV export, all the pickers, saved views and the MCP
  server's `search_catalog` gained the syntax together. Grammar with copy-paste examples
  in `wiki/Gallery.md` § Search operators.
- **Every CLI flag is now documented, and `--help` is complete.** The 30 tuning/maintenance
  flags that existed with no documentation anywhere (edit tuning, video tuning,
  `--params-json`/`--poll-timeout`, format conversion, download shaping, catalog repair,
  `--watch-seconds`, `--all-contests`, `--restore-orphans`, …) are covered three ways:
  a grouped "CLI flags" map in `docs/architecture.md` (with the non-obvious gotchas —
  `--params-json` overrides everything, edit params clamp to the model, seconds-vs-count
  units, which modifiers need a partner flag), user-facing sections in `wiki/Backing-Up.md`
  (download tuning / converting formats / live watch / catalog repair) and
  `wiki/Generating.md` (edit tuning / video tuning / shared create flags / `--contests`),
  and real `help=` text added to the two flags that had none (`--audio-language`,
  `--poll-timeout`).

### Security

- **The Similar modal ("more like this") no longer leaks unblurred NSFW lookalikes.**
  `/api/similar` now includes `is_nsfw` in its response, and the client sets `data-nsfw`
  on its hand-cloned cards, so Privacy Blur now covers this surface like every other one.
- **Privacy Blur now reaches every surface that shows a catalog thumbnail, closing the
  last open Tier-1 security item.** `/api/gallery-images` now projects `is_nsfw` alongside
  `/api/similar`, and it's threaded through the pick-event chain on both host paths (the
  main gallery page and the Loom) so a picked reference thumbnail knows its own NSFW state
  too. The gallery Picker, `<mg-gallery-picker>`, the Generate drawer's reference slots, and
  the Edit tab's single reference slot (found during this pass, not in the original
  citation) each gained the same `data-nsfw` + blur-on-`body.privacy-blur` treatment `.card`
  already had — previously none of the four rendered `.card`, so Privacy Blur never touched
  any of them regardless of the flag.

### Fixed

- **Orphaned jobs no longer spin in the Activity card forever** (`docs/AUDIT_2026-07-21.md`,
  `owner-2026-07-23`, reproduced against the owner's own `jobs.jsonl`: task
  `2037215124834251576` logged one `"running"` event and never got a second one, though
  the generation had actually finished on PixAI's side). Two fixes:
  - **A task-id recovery (`/api/import-task`) now closes the ORIGINAL orphaned job entry
    too**, not just the new `import-<suffix>` job it logs for the recovery action itself —
    on either success path (a fresh collect, or the "already cataloged" short-circuit).
    Previously, recovering a stuck task correctly imported the media but left the Activity
    card spinning on the orphan forever, permanently disconnected from reality.
  - **`/api/jobs` now runs an ongoing reconciliation sweep** (`resolve_orphan_jobs(...,
    min_age=JOBS_ORPHAN_SWEEP_AGE)`, same "runs opportunistically off an existing poll"
    shape as `maybe_compact_jobs` beside it) that re-checks any `generate` job stuck
    `"running"` for more than `JOBS_ORPHAN_SWEEP_AGE` (30 minutes — comfortably past any
    real single generation, including video's own 600s `--poll-timeout`, while still
    surfacing an orphan same-day rather than waiting on `JOBS_MAX_AGE`'s 24h silent
    drop-from-view) against PixAI's real task status. A job that resolves for real gets its
    true terminal event; a job whose status check itself fails (PixAI unreachable) is
    marked a new, distinct, dismissable `"stale"` state instead of being silently left
    exactly as-is or guessed into a false `done`/`failed` — the owner can always see that a
    job got stuck. The live-mirror watcher's own startup sweep is unchanged (`min_age=0`,
    checks everything once immediately). Fail-first tested:
    `tests/test_web_pick.py::test_import_task_closes_the_original_orphaned_job_entry` (+ the
    already-cataloged and dismissed-orphan variants beside it) and
    `tests/test_jobs.py::test_stale_job_reconciliation_marks_stale_when_pixai_cannot_be_reached`
    (+ the min-age-gate, real-resolve, and ts-refresh-throttle variants beside it, plus an
    end-to-end `/api/jobs` test).
- **Generate no longer locks until the task finishes — PixAI itself runs generations in
  parallel, so every gen panel now does too** (owner field-test 2026-07-23). The lock was
  two separate mechanisms, both fixed the same way: the gallery's `runTask()` (shared by
  Generate/Edit/Enhance/Fix) and the shared `<mg-generate-drawer>` (the gallery's Video tab
  and the Loom's Deep Focus) each disabled their Go button from submit until the task's poll
  reached a terminal phase. Both now free the button the moment the **server answers the
  submit** — accepted or rejected — not when the render finishes, and each concurrent
  submission gets its own line appended into the result strip instead of one shared
  `innerHTML` a second submission would overwrite (the drawer's poll loop also moved off a
  single shared timer that a second submission used to clobber via `clearTimeout`, onto a
  per-submission timer set). The Loom's per-shot pipeline (`generateShot`/`pollShot`/
  `batchGenerate`) needed no change — it already keys generation state per shot id and fires
  polling without awaiting it, so different shots already rendered concurrently;
  `batchGenerate`'s own `todo` filter already refuses to resubmit a shot still `"wip"`. Spend
  gates (the Fix tab's `window.confirm`, the live `/api/price` check) are unchanged and still
  gate every submission. Fail-first tested: `tests/test_concurrent_generations.py`,
  `loom/test/mg-generate-drawer-concurrent.test.js`,
  `loom/test/loom-batch-generate-concurrency.test.js`.
- **Videos no longer corrupt on collect** (owner field-test 2026-07-23: two clips fine on
  PixAI's side truncated mid-play locally — byte forensics traced it to two concurrent
  `ffmpeg +faststart` remuxes interleaving writes into the SAME deterministic temp file,
  because the live-mirror watcher and a `/api/task-status` done-poll both collected the
  same finished task seconds apart). Three layers, each fail-first tested:
  - `video_faststart()` uses a **unique temp name per invocation** (uuid suffix, real
    extension kept last so ffmpeg still picks the muxer) — the load-bearing fix, and the
    only one that also covers the separate `--watch-backup` process; the swallowed
    remux-failure path now `vlog()`s instead of hiding a lost race.
  - **Single-flight collect per task id** inside the gallery process: the live-mirror
    watcher, `/api/task-status`, and `/api/import-task` share a per-task lock — the first
    entrant runs the real `collect_generation`, a concurrent entrant waits and then
    answers from the catalog without re-downloading.
  - `download()` now **verifies bytes written against `Content-Length`** (when the body
    is not content-encoded) and fails a short body through the existing retry/backoff
    path instead of promoting a truncated `.part` — closes the adjacent mid-stream-cut
    hole next to the B1 zero-byte guard (not the cause of this incident, but real).
- **Four silent-failure paths now surface real errors instead of lying about success.**
  `/api/skin` and `/api/achievements?mark=1` used to answer 200 even when the disk write
  failed; they now report the failure and the actually-active value. `/api/loom/delete`
  used to answer `{"ok": true}` on a real `OSError`, indistinguishable from "already
  gone"; it now distinguishes the two. Prompt-snippet saves and saved-view saves were both
  fire-and-forget against endpoints that can answer 200 with an error body — both now show
  a Toast on failure.
- **A transient PixAI blip on `/api/task-status` no longer bricks the poller.** It used to
  answer `phase: "failed"`, which the client treats as terminal and stops polling — even
  though the code's own comment said this exact branch should be a soft, non-terminal
  retry. Now answers `phase: "running"` so polling continues as intended.
- **`bulkSendVideo()` no longer silently drops picks past a stale cap.** It pre-sliced to
  9 images before handing off to a drawer that only holds 6; the extra 3 vanished with no
  signal. Now passes the full selection and warns how many were left out.
- **`/export-zip` no longer ships silently-untouched files with no signal.** A failed
  convert-to-format or embed-prompt step used to fail silently and ship the original
  unchanged; now collects every such case into a `_export_warnings.txt` inside the zip
  plus an `X-Export-Warnings` response header.
- **The stray root `HEAD` file, finally root-caused.** Two of `tests/test_panel.py`'s ten
  `FakeProc` ffmpeg mocks patched `subprocess.Popen` globally with no command guard;
  `create_app()`'s own `git rev-parse --short HEAD` call rode the same patched `Popen` and
  got its output written to a file literally named `HEAD` in the repo root. Both classes
  now guard on the command being `ffmpeg`. Fail-first verified: reverting the guard
  reproduces a freshly-written `HEAD` file; restoring it does not.
- Fixed a timing-flaky live-server test in `tests/test_port_preflight.py` (a fixed 0.4s
  probe timeout could occasionally lose a scheduling race under full-suite thread
  contention) and tightened three weak assertions in `tests/test_js_syntax.py`,
  `tests/test_read_only.py`, and `tests/test_web_pick.py` that couldn't actually catch
  the regressions their own docstrings described.
- Fixed a Loom bug where the shared `<mg-generate-drawer>`'s own Camera and quality
  controls rendered alongside the Loom's equivalent controls (missing `data-loom-ctx`
  attribute on the mount) — added, with a new regression test.
- Extended a font-inheritance fix (host-neutral `font-family` on toast/tray roots, shipped
  2026-07-21) to two roots it missed: the achievement celebration and the Folio of Honors
  panel, both of which fell back to the browser default on `/loom`.
- Native `<select>` styling made consistent across the Generate drawer and the
  gallery-picker's filter dropdowns (some had the custom lavender-caret treatment,
  some didn't, with no reason for the split).
- The persistent Activity FAB no longer permanently sits on top of the grid's bottom-left
  corner eating clicks — the grid now reserves clearance for it.
- Added the missing delete-view control for saved views — the server route existed, no UI
  ever called it.
- **`--generate-video`/`--reference-video` now snap their duration to an allowed length,
  matching what the Loom already did.** `--reference-video`'s default was also inconsistent
  across three places in the source (5, 15, and 15) — unified to 5, matching its i2v sibling.
- **`--suggest-prompt` now refuses a video up front** instead of hitting PixAI's image-only
  endpoint and surfacing a raw 500, matching the guard the web gallery already had.
- **The `_deleted/` quarantine is now respected by all six bulk file-tree walks, not one.**
  `cmd_organize` — the only one that actually moves/deletes files — could silently
  hard-delete or resurrect a purged file that happened to share a media_id with a live
  copy; reproduced and fixed, along with resume, the audit, `--import-local`, and
  `duplicate_groups`.
- **`--sync-artworks --with-videos`'s resume check now actually recognizes an
  already-downloaded video** instead of re-resolving it from the network on every run.
- **The Loom's frame-handoff fallback (`/api/loom/handoff`) now requires an exact media_id
  match and excludes quarantined files**, closing a path where a purged or
  substring-matching clip could get uploaded to seed the next shot.
- **A backup that fails partway through `--sync-artworks` (or loses a page mid-pagination)
  now reports it**, through the same `done_with_errors` signal `--sync`/`--download`
  already had, instead of a complete-looking "done."
- **Per-account storage (saved views, prompt snippets, Loom storyboards, toolbox presets)
  no longer collides on Windows for usernames differing only by case** ("Nel" and "nel"
  used to share one file on disk, reproduced and confirmed fixed for all four stores).
- **The Loom's board cards now show when a shot's opening frame is already continuity-linked
  to the previous shot's closing frame** — a small badge, restoring a pure-logic function
  (`frameLinked`/new `continuityLinked`) that had zero callers since the V1→V2 migration.

### Removed

- Deleted three zero-caller GUI-era wrapper functions (`run_audit`, `run_dedup`,
  `run_verify_dupes` — the removed PySide6 GUI was their only caller) and `is_lora_type()`
  (referenced nowhere). The real underlying logic is untouched.
- Deleted two orphaned CSS rules (`.gen-ce`, `.vp-chip`) with zero producers left anywhere
  in the app.
- Deleted the dead `--variant` CLI flag's whole self-referential support cluster
  (`detect_variant`, `test_variant`, `media_url`, `MEDIA_TMPL`, `VARIANT_CANDIDATES`) — the
  flag itself was already gone; this was the ~55-line machinery nothing called anymore, plus
  the module docstring's stale claim that the script "auto-detects the full-res variant."
- Deleted the unused `ARTWORK_DETAIL_HASH` config read (its live sibling `ARTWORK_LIST_HASH`
  is untouched) and the dead `generateShot` prop threaded through the Loom's `LoomV2`
  component (per-shot generation moved to `<mg-generate-drawer>` some time ago).
- A broader dead-CSS-selector sweep (every class selector in the gallery's inline
  `<style>` blocks, cross-checked for a real producer) found and removed two more:
  `#gen-drawer.dock-right` (structurally unreachable) and `#model-preview .mp-tags`
  (never populated).

### Added

- A "Contact sheet" button next to "Download collection" — the `?collection=` printable
  contact-sheet route existed with no way to reach it from the UI.

### Docs

- `docs/architecture.md`: documented the 5 shared `mg-*.js` web components as a group for
  the first time; corrected the thumbnail-cache description (short-lived + ETag, not
  immutable) and `already_downloaded()`'s real behavior.
- Fixed stale claims across `wiki/How-It-Works.md` (`--watch`/`--claims` have web
  surfaces, not CLI-only), `wiki/Generating.md` (`--suggest-prompt` caveat), and
  `wiki/Setup.md` (`cryptography` isn't in `requirements.txt`).
  `README.md`/`CONTRIBUTING.md` got several small corrections (Python 3.9+ floor, orphaned
  screenshot captions, module count).
- Added `SECURITY.md` (private vulnerability reporting is off for this repo; falls back to
  the existing email convention).
- `.gitignore` now generalizes ignored generated-file patterns to any `--out` directory
  name, not just the default `pixai_backup/` (previously only `jobs.jsonl` had this).
- `docs/curation_reference_builder.py` (a committed template script) no longer hardcodes a
  personal path — reads `CURATION_INPUT_DIR`/`CURATION_OUT_DIR` env vars instead.
- Corrected four false claims in `docs/architecture.md`'s Invariants section (one shared
  media-id matcher, checked-before-any-network-call, catalog-as-source-of-truth for
  organize, and `media_id_of()` as a single source of truth all overstated the real,
  verified behavior) and a matching false claim in `CONTRIBUTING.md`.
- Corrected two nearby code comments that named only some of the surfaces gated by the
  header's `is_local` flag, omitting the Import button (which is separately, correctly
  re-checked as LOCALHOST-tier server-side — never a real security gap, just a misleading
  comment) — and `_task_detail_query`'s docstring, which overclaimed a fallback its two
  real CLI callers don't actually get.
- Documented the video-generation model roster for the first time: all 7 engines, the real
  5/6/10/15s duration set (6s was never mentioned anywhere), per-model duration caps,
  which two models no free card ever covers, and which Shot modes are gated per model.
- `wiki/Collections.md` now documents the "Remove from «collection»" action and the
  Actions ▾ menu it lives behind.

## [2.3.0] - 2026-07-23 — More security hardening, the Folio of Honors, and LoRA support in the Loom

### Changed

- **Trophy Hall is now The Folio of Honors, with a full visual redesign.** The owner's
  pick off the standing rename shortlist, shipped alongside a redesign built from a
  finished Figma Make export — itself built partly from the legendary/feat frame
  dimensions handed off earlier the same night (confirmed byte-for-byte identical
  tier-triad colors to what the unlock celebration already shipped). The All tab now
  leads with an auto-rotating carousel showcasing the active ladder's tiers, a badge row
  to jump between all 10 ladders, and every ladder/Milestones/Masteries/Feats grouped
  under a glowing divider. Legendary and feat cards carry the same ornate 9-slice frame
  the unlock celebration always has — extended to the grid for the first time, a
  deliberate change from "toast only." The sidebar's category list now filters in place
  instead of just scrolling to a section, and Relics (skins) show all five with lock/
  active state, not just the ones you've already unlocked. The Statistics tab gained
  achieved/points/feats summary cards plus by-rarity and per-ladder-completion
  breakdowns. Ported to this app's existing vanilla JS/CSS rather than adopted as React
  (the Loom stays the only React surface); real badge art throughout, not the export's
  placeholder images. Backend gained `track`/`rung`/`rungs_total` per ladder achievement
  and a `ladders` list so the client doesn't need a second hand-maintained id→name map.

### Added

- **The Enhance sub-tab now shows its real cost before you run anything.** It was the
  one price surface that never got the `<mg-cost-badge>` treatment every other screen
  already has — click-a-tool used to price it and pop a `window.confirm()` on every
  single click. Reshaped to select-then-run, mirroring the Edit sub-tab: clicking a
  tool (from the curated shelf or the 140+ browse-all list) just selects it and shows
  its price in a persistent badge; a separate Run button fires it. The badge is now the
  only warning, same as everywhere else — no confirm dialog left in this path.

- **The Loom's Image, Edit, and Reference tabs now show their real cost before you
  generate.** These were the last three price surfaces missing an `<mg-cost-badge>`.
  Each tab gets its own badge, refreshed by a shared debounced read-only `/api/price`
  check as the model/prompt/source/references change. Unlike the Gallery's Enhance
  sub-tab above, each tab's existing `window.confirm()` at submit time is **kept, not
  removed** — that confirm dialog is this project's original fail-closed guardrail,
  built after these exact tabs used to lie about cost, so the badge is an added
  preview, not a replacement for it.

- **The Loom's Image tab can now use LoRAs.** Previously it only offered a base model —
  the Gallery's own Generate drawer has had full LoRA support (multi-select, per-item
  weight, trigger words, compatibility warnings) for a while, but the Loom's picker
  never gained it. `static/mg-model-picker.js` (the shared component both surfaces
  mount) gained an opt-in multi-select mode; single-value mode is completely
  unchanged. Each picked LoRA resolves its real generation metadata the same way the
  Gallery already does, and Generate is disabled while any LoRA is still resolving or
  failed to resolve — never silently dropped from what you asked for. Verified live
  against the real running app: pending/resolved/failed/removed states, and the
  Go-button gating, all confirmed working end to end.

  Deliberately deferred: unlike the Gallery drawer, the Loom doesn't yet warn you
  before submit if a LoRA doesn't match the base model's architecture (would need the
  Loom to additionally resolve the base model's own type, which it doesn't today).
  Functionally safe to defer — PixAI's own servers already reject a real mismatch and
  explain why — but it means one fewer heads-up than the Gallery gives you.

### Fixed

- **Error messages could leak this machine's own file paths — including your Windows
  username — to any signed-in LAN account, not just you.** A caught exception's text
  (`str(e)`) routinely embeds an absolute path on a file-not-found, permission, or
  upstream-API error, and 37 places across the web app either served that straight back
  in a JSON error or stashed it for a later request to read. An earlier attempt at this
  fix was reverted for a real flaw (a regex that stopped redacting at the first space,
  so a spaced Windows username like "John Smith" still leaked in full). This re-spin
  does literal-prefix matching instead of a regex, and both new tests are built around a
  deliberately spaced directory name to make sure that exact regression can't recur.
  Adversarially reviewed before shipping, which caught three more real gaps in the same
  pass: a relative `--out .` could have turned the fix inside-out (mangling ordinary
  punctuation in every error message instead of protecting anything); two sites built
  their error text a way the sweep's search didn't recognize; one site was missing its
  length cap. All three fixed in the same pass.

- **The CLI's `--edit-image` could submit a resolution/quality the picked model doesn't
  support.** The web Edit tab has always clamped its request to the resolved model's real
  capabilities (`clamp_edit_config`) — the CLI's own defaults (1K/medium) never ran through
  that guard, so editing with a model like Reference Pro (2K/4K only, no quality knob at
  all) could send an invalid combo straight into a credit spend. Now clamped in the same
  place the CLI already builds its edit config, so both the preview and the real submit
  are covered.

- **The last per-account split from tonight's earlier work: Toolbox presets.** Imported
  presets were still one shared file for every account, so anyone signed in could see —
  and overwrite, one import at a time — everyone else's. Same fix shape as prompt
  snippets and Loom storyboards earlier tonight: a file per account, with the old shared
  file kept as a read-only fallback for an account that hasn't saved its own yet.

- **A backup that partially failed reported itself identically to a clean one.** If some
  files failed to download after retries, the run still printed a tally but nothing
  distinguished it from success anywhere downstream — the CLI job log, the Panel's Jobs
  tray, all said "done." Exit code is unchanged by design (still 0 — a partial failure
  must not break a scheduled task over one transient blip); what's new is a real
  `done_with_errors` status that's visible and dismissable everywhere a job shows up,
  plus a much louder console notice for a bare-terminal run.

- **Signing out no longer leaves your images sitting in the browser's cache.** The
  installed/offline view caches image responses in Cache Storage, and nothing
  previously cleared that on sign-out — a shared or borrowed device could still show
  a previous account's thumbnails after that account signed out. `/logout` now serves
  a small page that deletes every cached entry client-side before continuing on to the
  login page, the same way a redirect always did, plus a visible fallback link for a
  browser that blocks the page's own script. Deliberately not hooked onto `/login`
  itself — that path has no way to tell "you're signing out" from "you're already
  signed in and just landed here by accident," which is exactly what sank an earlier
  attempt at this fix.

- **Seven tests that couldn't actually fail.** Each guarded a real, working feature with
  a check loose enough to pass even if that feature broke — a substring that also
  matched an unrelated comment, an `or` fallback that widened the match to something
  structurally different (a desktop CSS rule instead of the mobile one, one branch of
  a service worker instead of the other), or a slice that grabbed the wrong end of the
  string. Every one now checks the exact thing it claims to, and was verified by
  temporarily breaking the real feature and confirming the test actually catches it —
  the service worker's thumbnail revalidation, two Deep Focus prompt-field behaviors,
  two branding-render checks, the mobile drawer's full-width rule, and the v4.0 video
  cost warning.

- **A doc-truth-up sweep across the repo.** Route docstrings, help text, and comments that
  no longer matched what the code actually does, verified one at a time against the real
  current behavior rather than trusting the earlier audit's own wording (which was itself
  sometimes stale by the time this landed). Route tier docstrings corrected to match
  `ROUTE_TIERS` (four routes wrongly claimed Localhost/Open); the first-run bootstrap
  docstring updated to describe the real web-based flow; every remaining reference to the
  deleted PySide6 GUI removed from user-facing strings and code comments (five sites, not
  the two originally estimated), two of which kept their original reasoning rather than
  just losing the GUI comparison; `docs/architecture.md`'s on-disk layout diagram brought
  up to date (11 missing entries) and its `/api/branding` tier claim corrected;
  `docs/STATE.md`'s self-contradictions resolved (some turned out to already be fixed by
  earlier work tonight — checked rather than assumed); `CHANGELOG.md`'s own v2.2.0 entry
  and release-history maintenance note corrected against `gh release list` and
  `git merge-base`; `config.example.json` gained two real, previously-undocumented config
  overrides; README's feature table and wiki index gained the Loom, Folio of Honors, and
  Control Panel. Two real (not doc-only) gaps surfaced along the way were deliberately
  **not** fixed here and are tracked instead: `--full-meta`/`--backfill-full-meta` don't
  get the fallback resilience their own docstring claims, and a LAN-signed-in session can
  see an Import button that always 403s.

- **The model-preview tooltip "jumped" while browsing, making it hard to scan a grid.**
  Two independently-drifted copies of the hover-preview mechanism (the gallery's own
  `#model-flyout`, and the shared `<mg-model-picker>` the Loom mounts) both fired an
  instant, un-animated, freshly-repositioned popup on every single card the mouse
  passed over while scanning — not just the one you paused on. Both now wait ~130ms
  of genuine hover before opening, so a fast scan across several cards never triggers
  it at all.

- **Prompt snippets and Loom storyboards were install-wide — any signed-in account
  could read, overwrite, or delete every other account's.** Same problem saved views
  already got fixed for, just never applied here. Both are now per-account
  (`out_dir/prompt_snippets/<user>.json`, `out_dir/loom/kv/<user>/`), falling back
  read-only to the old shared file/dir for an account that hasn't saved its own copy
  yet — nothing disappears on upgrade. One accepted, documented gap: deleting a Loom
  board you inherited from the shared layer but never saved yourself doesn't stick
  (a later read still falls through to the shared copy) — narrow enough not to matter
  for how this is actually used, revisit if that changes.

- **The Folio of Honors rendered as a scrambled, overlapping mess on first ship.** `#ach-grid`
  still carried its pre-redesign CSS class, whose rule forced every direct child into a
  ~216px tiled grid column — correct for the old flat card layout, wrong for the new one,
  where every direct child is a full-width section (the carousel, the ladder row, each
  section group). Those sections were being auto-placed into narrow tiles instead of
  stacking, which is what actually showed up on screen. Fixed to a plain vertical stack;
  also removed ~30 CSS rules confirmed dead in the new render code, left behind from the old
  design and part of what caused the confusion.

- **A flaky free-card check could silently spend real credits after promising "0
  credits."** `match_kaisuuken`'s fail-soft contract (returns `None` on error) is right
  for read-only/preview callers, but `_apply_kaisuuken` — the spend-time check — used the
  same call, so a transient `/v2/kaisuuken/check` glitch was indistinguishable from
  "genuinely no free card exists," and the generation proceeded to spend credits either
  way. The spend-time check now retries once, then aborts the submission with a clear
  error instead of guessing. Covers both the CLI and the web `/api/generate`/`/api/edit`
  routes.

- **A LoRA whose version lookup failed could silently vanish from a paid generation.**
  Adding a LoRA in the Generate drawer kicks off a background lookup for its
  `version_id`; the chip showed an hourglass until it resolved. If that lookup ever
  failed, the hourglass just... stayed forever, with no distinct failure state — and
  the submit payload quietly filtered any LoRA still missing a `version_id` out of the
  request. The generation fired anyway, at full price, missing a LoRA the user believed
  was included. Now a failed lookup is tracked separately from a pending one (a
  warning icon + explanatory tooltip instead of an endless spinner), Generate is
  disabled while any added LoRA is unresolved, and the submit handler itself refuses
  to fire on an unresolved LoRA as a second guard.

- **`--generate`/`--edit-image` with `batch>1` catalogued only the composite grid,
  losing every individual image.** Both built their saved-media list by reading
  `outputs.mediaId` (the composite grid PixAI returns for any `batchSize>1` task) and
  `outputs.batchMediaIds` (null on modern tasks) directly, instead of going through
  `_task_image_media` — the helper that already correctly prefers `outputs.batch[]`,
  written for `_download_image_task`/`web_generate` but never wired into the CLI's own
  generate/edit-image runners. A 4-image batch run downloaded and catalogued exactly
  one file: the grid thumbnail, not any of the actual generations paid for. Both now
  use the same helper, and pick up each image's real per-batch seed in the process
  instead of the shared submitted one.

- **The published GitHub wiki was 4 releases stale.** README calls it "full
  documentation," but it was frozen at 2026-07-17: still told new users to
  `pip install PySide6` and run the deleted GUI, said nothing about the login wall
  v2.0.0 added to every path including localhost, and was missing three pages
  entirely (The-Loom, Control-Panel, Folio of Honors) that only ever existed in the
  repo's own `wiki/` folder. Pushed the current, fact-checked `wiki/` source to the
  live wiki (10 pages updated, 3 added). Confirmed with the owner before publishing,
  since it's a public surface outside this session's standing repo-push permission.
  Still open: whether to automate this push (a CI job on tag) so it can't silently
  drift a second time — decision D-10 in `docs/AUDIT_2026-07-21.md`.

- **A test guarding the port pre-flight's wildcard-host handling couldn't actually
  catch a regression.** `test_wildcard_bind_addresses_probe_loopback` probed a free
  port and asserted `""` — but a wildcard host (`0.0.0.0`/`::`/`""`) returns `""`
  against a free port whether or not `port_owner` rewrites it to `127.0.0.1` first,
  since a connection to a free port refuses either way. Rewritten to probe a live
  server through the wildcard host and require it to be recognized, which only
  passes if the rewrite genuinely happened.

- **A failed free-card check now says so in plain, on-theme language instead of a raw
  technical error.** "Lost to the Void — the free-card check didn't come back before
  submitting, so nothing was spent. Wait a moment and try again." Still refuses to
  guess and silently spend credits (unchanged); just says it in the app's own voice
  now, per the owner's D-1 answer, mirroring how PixAI's own site reports a similar
  random failure.

- **`--variant`, a CLI flag that did nothing, is gone.** Verified directly (not taken
  on a prior audit's word, per the owner's D-5 request): `args.variant` was parsed but
  read nowhere in the codebase — zero occurrences. The variant *auto-detection*
  machinery it was meant to override (`detect_variant`/`test_variant`, used by
  `--probe` and the normal download path) is untouched and very much alive; only the
  dead manual-override flag is removed.

- **The published wiki now syncs automatically on every release tag.**
  `.github/workflows/wiki-sync.yml` pushes `wiki/*.md` to the wiki repo whenever a `v*`
  tag lands, so it can't silently drift the way it did for 4 releases / 6 days before
  tonight's manual fix. A `workflow_dispatch` trigger lets it be smoke-tested by hand
  without waiting for the next real release.

### Removed

- **`ENHANCE_PLUGINS` and the dead `plugin=` branch of `/api/enhance`.** The Edit
  tab's Enhance UI has only ever sent `workflow_id`, never `plugin`, so the dict's
  three entries were unreachable. `hand-fix`/`face-fix` are superseded by the real,
  working box-based `/api/fix` (`submit_fixer`); `detail-fix`'s workflow is already
  reachable the normal way, through the same `workflow_id` path every other Enhance
  workflow uses.

### Known issue (not fixed — deliberately left for the design pass)

- **Roast/flavor text may be showing the uncensored "spicy" variant when it shouldn't.**
  Reported right after the layout fix above; not yet confirmed whether this is a real gating
  bug or a visual artifact of the (now-fixed) overlap bug making two different cards' text
  read as one. Owner wants to look at it himself before any further changes — see
  `docs/STATE.md`'s Folio of Honors section for what's on record.

### Fixed (continued)

- **A signed-in LAN account could evict the owner's own account, and register a fresh one
  for itself.** The only guard on removing an account was "not the last one left" — nothing
  stopped a caller from removing any *other* account by name, including yours, or from
  creating a brand-new one afterward. Adding an account, and removing anyone but yourself,
  now require the request to come from the machine running the gallery; removing your own
  account still works from anywhere, since that can only affect the person doing it. The
  Panel's Users tab reflects this directly — a LAN session no longer sees an "Add user" form
  or a "Remove" button on rows that aren't its own, rather than offering a control that
  would just 403.

- **The wiki said the Generate drawer and web import were more restricted than they
  actually are.** `wiki/Generating.md` claimed the Generate drawer was localhost-only —
  it's actually reachable from any signed-in device, including over the LAN, by
  deliberate design since v2.0.0. `wiki/Backing-Up.md` claimed the ↑ Import button only
  appears for a local session — the button shows for everyone signed in; only the actual
  import is refused from a LAN device. Both now describe the real (correct) restriction
  instead of a stricter one nobody built. Five smaller wiki corrections landed alongside
  these from the same fact-check pass: `Generating.md` (the web drawer doesn't
  auto-fall-back on an unsupported Mode — only the CLI does), `Setup.md` (only the
  password is hidden when adding a web user, not the username), `Deleting.md` (the CLI's
  typed `delete` confirmation is case-insensitive, and now mentions `READ_ONLY`),
  `Trophy-Hall.md` (The Moonforge counts Generated **and** Imported pieces, not just
  Generated), `Trust-and-Safety.md` (`/logout` was missing from the list of routes
  reachable without an account), `The-Loom.md` (Deep Focus's field list was missing its
  new Prompt field), `How-It-Works.md` (the on-disk layout diagram was missing four
  real files/folders), `Control-Panel.md` (a note on what a LAN session sees instead of
  the install path), and `README.md` (the Quickstart never mentioned that first login
  doubles as account creation).

- **The Control Panel no longer shows your library's file path to other accounts on your
  network.** `/panel` stays reachable to any signed-in account — managing accounts there is
  intentionally shared, same as the rest of the Panel — but the server's own install path is
  a different kind of fact, and only you see it now.
- **A job's logged error message could be unbounded in size.** Every other place that logs an
  error already trims it; one path — a bare terminal run hitting an unexpected failure — didn't,
  so an unusually long message could be written and later served back in full. It's capped now,
  the same as everywhere else.


- **Recovering a failed task said "completed."** If PixAI itself marked a task
  failed/cancelled/rejected, every recovery path (`--dump-params`, the web gallery's
  "⬇ Import", the CLI's own `--generate`/`--generate-video`/`--edit-image` recovery)
  still said *"task completed but no media ids found"* — which reads as a Moonglade bug
  even though the credits were already spent and PixAI genuinely rejected the task. The
  message now says which of the two actually happened. `--dump-params` also prints the
  task's status now, not just what was submitted — the params alone can't tell you
  whether PixAI ever ran the task, which is usually the whole reason you're recovering it.
- **A zero-byte file left by an interrupted download used to be permanent.** Nothing would
  ever re-download it — `--update`, `--sync`, and a full re-walk all treated it as
  "already have this one" — and the gallery would serve the empty file back if a filename
  match hit it first. All three sites now check size, not just that a file exists.
  `--dedup --apply --dedup-delete` could also pick an empty file as the "keeper" and
  hard-delete the real image with no safety net; a zero-byte file can no longer enter that
  comparison at all.
- **`READ_ONLY` now actually stops every CLI path that can spend credits.** It already covered
  the web app; on the CLI, five commands — `--generate`, `--generate-video`,
  `--reference-video`, `--enhance`, `--edit-image` — built their own submit call instead of
  going through the guarded choke point, so setting `READ_ONLY` in `config.json` and running
  any of them with `--confirm` still reached PixAI. Each now refuses itself before the
  free-card check or an upload runs, not just before the final submit.
- **The gallery's Video tab stopped showing up in the Activity card.** When it moved onto
  the shared `<mg-generate-drawer>` component, it lost the two listeners every other
  create tab (Image, Edit, Fix) still has: registering the new task with the Job Tracker,
  and refreshing your credit balance once it finishes. The drawer renders its own inline
  result, which is why this went unnoticed — the generation itself worked fine, it just
  never reached the Activity card or updated your balance on completion. The Loom's own
  mount already wired this correctly; the gallery now mirrors it.

## [2.2.0] - 2026-07-21 — Security fixes, the last two video models, and a sharper Loom

### Changed

- **Every cost display in the app is now the same component.** `<mg-cost-badge>` was built and
  then mounted nowhere while four surfaces each hand-rolled their own "is this free or does it
  cost credits" line — the one surface whose entire job is stopping an accidental 27,500-credit
  click. They are now one component: the Generate drawer (shared by the gallery's Video tab and
  the Loom), and the gallery's Image and Edit tabs. What you'll notice: the gallery's
  FREE line gains the card's name, how many are left, and when it expires (matching what the
  drawer already showed); and where a failed price check used to read as a neutral "cost
  unavailable", it now says plainly, in red, that the cost couldn't be verified and generating
  may spend credits. The V4.0-full caution stays **red** — a 15s clip is ~210,000 credits, and
  the app's loudest warning was not going to get quieter as a side effect of a refactor.
  Cost changes are now announced to screen readers.

### Added

- **The shot's prompt is editable in Deep Focus.** Until now the base prompt — the text that
  keeps recomposing as you change Camera, Lighting and cast — could only be written from the
  right-hand panel. Double-click a card and it's there, between the mode row and the frames,
  in the same reading order as the panel. Editing it clears an active drawer override and says
  so, the same way the panel already does.
- **You can create a collection while importing.** The "Add to collection" dropdown gained a
  **＋ New collection…** option: name it in the box that appears and it's created as the import
  lands. Previously you had to import loose and re-collect afterwards. Leaving the name blank
  won't quietly import into nothing — it asks you to name it first.

- **Export the current filtered view to CSV, from the gallery grid.** The filtered-export
  backend already shipped (an earlier blitz taught `/export-csv` to honour the grid's `?q=&model=…`
  filter args) but had no way in — the only CSV link lived on the Control Panel and always dumped
  the whole catalog, so a filtered view could not be exported at all. The grid's active-filter bar
  now grows an **⬇ Export this view (CSV)** link that carries the live query string to
  `/export-csv`, so you download exactly the rows you're looking at. It appears only when a filter
  is active (the whole-catalog dump stays the Panel's job); the empty-filter path is byte-identical
  to before. Exporting a *selection* of specific picked images is still a separate, unbuilt item.
- **The last two video models are selectable: V2.7 (High Dynamics) and V3.0 Flash.** They had
  shipped visible-but-disabled on the theory that a submit needs a numeric top-level `modelId`,
  which we only had for five of the seven. That theory was wrong. Two free `--dump-params`
  captures off real rendered tasks both carried an **image** checkpoint's id in `modelId`, and
  three read-only price probes settled it: the two models price *differently* (~56,000 vs
  ~44,800 credits for 10s) off an *identical* `modelId`, and dropping `modelId` entirely prices
  the same. `i2vPro.model` resolves the engine; the numeric id does not. Neither model is
  card-eligible — your free cards are V4.0-specific — so the cost badge honestly reads "no free
  card" rather than pretending otherwise.
- **Per-model duration caps in the Generate drawer.** 15s is exclusive to the V4.0 pair, but the
  duration control offered 5/6/10/15 for every model. Harmless while every enabled model allowed
  15s; enabling V2.7 and V3.0 Flash would have newly exposed an unsupported 15s option at roughly
  84,000 credits with no card to cover it. Over-cap options are now disabled *and* hidden — hiding
  alone leaves an `<option>` keyboard-selectable and still submittable.

- **You can take images back out of a collection from the UI.** `/collection-remove` had existed
  for a while with **zero callers** — the whole feature was written except the way in. While a
  collection filter is active, Actions gains **“− Remove from «name»”**, which takes the selected
  items out of *that* collection (the one the grid is already showing, so there's no "remove from
  which?" ambiguity). It's a label change only: no files are deleted and nothing leaves your PixAI
  account, and the confirm says so. A banner reports how many left.
- **Three new wiki pages** — **The Loom** (acts/shots, the frame handoff, cast & assets, generating
  a shot, Deep Focus, the two different Exports), **Control Panel** (every maintenance job with its
  real label, the risk tiers, the scheduler, Advanced sync, Users, the Activity log), and
  **Trophy Hall** (the ten evolution ladders and their rungs, milestones, masteries, and how rarity
  and points actually compute). All written against the code rather than the older docs.
- **`<mg-cost-badge>`** (`static/mg-cost-badge.js` + harness) — the last unbuilt shared web
  component. Renders the credit cost of a pending generation and whether a free card covers it,
  in five states (idle · checking · free · paid · couldn't verify). Host-neutral like its siblings:
  it never fetches, the host pushes an `/api/price` response in. **Not mounted anywhere yet.**
### Changed

- **95 dead CSS rules pruned from the Loom** — the classic (V1) render tree's leftovers.
  Retiring classic deleted its components but not their styles: 84 rules in `STYLES` (the
  classic header, board grid, card slate/body, editor rows, cast chips, reel bar, the old
  hand-rolled picker grid) plus 11 pre-redesign leftovers in `V2_STYLES` styled markup nothing
  renders anymore. Removed mechanically: every class token in a deleted rule was verified
  absent from the JSX, the Flask module, every `static/*.js`, and the Loom's `src`/`test`
  trees, with dynamically-constructed class names (`"sb-tick " + status` and friends) audited
  by hand — a rule survived unless *every* selector in it was provably unmatchable. `STYLES`
  shrank 39%; shared classes the Export dialog, ImportCollection, and Deep Focus still use
  (`.sb-pick-ov`, `.sb-field`, `.sb-btn`, …) are untouched, and the served bundle was rebuilt
  in the same commit (the stale-bundle gate enforces this now).

### Fixed

- **The Activity card, chip and toasts used a different typeface on The Loom than in the
  gallery.** They set their own text size but not their own typeface, so they picked up
  whatever the surrounding page used — and the Loom's page never specified one, leaving them
  on the browser's default font. Same components, two different looks depending on where you
  opened them. They now carry their own typeface, and the Loom's page sets a baseline for
  anything else mounted alongside them.

- **The Activity card was showing internal identifiers instead of words.** Every job run from
  a terminal read "Cli" underneath it — not a word — because the row printed the internal job
  type verbatim. Terminal runs also carried raw command names as their title, so
  "generate-video" sat in the list next to real sentences, and the completion toast popped
  "generate-video — done". Sources now read Terminal / Control Panel / Generate, and terminal
  jobs are titled in words: Image generation, Video render, Library sync, Incremental update,
  Full backup.

- **Saved views belong to your account, not to the whole install.** They shipped in a single
  shared file, by analogy with the skin choice — which is right for a theme and wrong for a
  saved search, since a view's name and query say what you look for in your own library. On an
  install with more than one login, everyone could read, overwrite and delete everyone else's.
  Now one file per account. Nothing is lost on upgrade: an account with no file of its own
  still reads the old shared set until its first save.
- **The Loom's ? help button no longer covers the Generate button or the cost readout.** Making
  it visible put a fixed circle in the bottom-right — which on `/loom` is where the Generate
  drawer lives — so scrolling the drawer to the end, right before submitting, tucked the edge of
  the Generate button and the tail of the cost line underneath it. The drawer now keeps clear
  space beneath its content.

- **Saved views now follow you between devices.** The gallery's "Saved views…" presets lived in
  each browser's own localStorage, so a view saved at the desktop simply didn't exist on the
  tablet sharing the same server. They now persist server-side (`/api/view-presets` →
  `out_dir/view_presets/<account>.json`, atomic write, login tier) — the same follows-you-everywhere
  contract as the skin choice. Any legacy localStorage set is merged up automatically on first
  load (server names win ties, so two browsers migrating in sequence can't fight over whose
  stale copy sticks) and then cleared. Stored queries must be `?…` filter strings — the client
  navigates a loaded preset via `location.href = '/' + query`, where a smuggled `//host` would
  resolve protocol-relative and turn a saved view into an off-site redirect; the server refuses
  those outright. A delete verb ships server-side (tested) with no UI control yet.
- **The Loom's help button and Activity chip are visible again.** Both the `?` help FAB
  (`z-index:300`) and the Activity chip (`#jobs-fab`, `z-index:234` from the shared `mg-notify.js`)
  are body-level widgets that the Loom's opaque `.lv-overlay` (`z-index:400`) painted straight over
  — invisible and unclickable on `/loom`, though the wiki documents both as usable there. A
  Loom-scoped raise to 401/402 (in `_LOOM_SHELL`, so the gallery's own `#jobs-fab` keeps 234) floats
  them over the board while staying under every modal/celebration tier that must cover them — the
  frame picker, Sequence/Export/Import overlays (500), toasts (510), and the unlock moment (520/521).
  The help FAB's own modal was raised too (it was buried at 301). One acknowledged residual: because
  Deep Focus's veil and the nested hover-preview flyouts render *inside* the overlay's stacking atom,
  the raised corner widgets now sit over those backdrops rather than under them — cosmetic only; the
  real fix (hoisting those overlays to root level) is a deferred refactor.
- **The Loom's gallery picker no longer ties the shell for z-index.** `<mg-gallery-picker>` sat
  at z-index 400 — exactly `.lv-overlay`'s own value — so the everyday frame/cast picker painted
  above the shell by DOM order alone, which is luck, not layering. Raised to 500, the shell's
  established full-screen-modal tier: above the overlay and Deep Focus's veil, below the
  notification toasts (510) and the unlock moment (520). The same fix `.sb-pick-ov` got a day
  earlier, closing out the z-400 sibling that review had found. The gallery loads the same
  script but never mounts the element yet, so the change has exactly one live surface.
- **Escape closes the Loom's project and Export menus.** Both popovers sit behind a
  full-viewport click-catching veil, so until this the only way out was finding somewhere to
  click — the rest of the app was dead until you did. They now close on Escape exactly like
  Deep Focus always has. (Shipped in the 2026-07-21 small-wins blitz; this entry was recorded
  after the fact — the fix predates it.)
- **`tools/name_inventory.py` was silently missing the launcher — and every machine-local
  file.** Two blind spots in the tool that sizes the `pixai_* → moonglade_*` rename: it split
  `git ls-files` output on whitespace, shattering `Serve Gallery.pyw` into two nonexistent
  paths that the read-error catch then swallowed without a word — dropping the launcher, one of
  the exact files the rename must not miss (now NUL-delimited via `-z`); and it walked tracked
  files only, blind to untracked and git-ignored files. It now also counts
  untracked-but-unignored files plus an existence-guarded machine-local set
  (`.claude/launch.json` · `config.json` · `serve.txt` · `private/`), reporting those
  separately since the rename branch can't fix them — each machine has to. The offline
  image cache only refused to store *failed* responses — but a request for an image you're no
  longer signed in for isn't a failure, it's a redirect to the login page, which arrives as a
  perfectly successful 200. The login page then got stored under the image's own address. For
  thumbnails that healed itself on the next load; for full-size images it never did, because
  those are served from cache without re-checking — so they stayed broken through re-login,
  reloads and restarts, fixable only with a hard refresh. The trigger was ordinary: Sign out
  revokes every device, so signing out at the desktop while the tablet was still loading its
  grid was enough. The cache now refuses redirected responses, and its version was bumped so
  anything already holding a poisoned entry clears itself.

- **The gallery refuses to become the second server on a port.** Windows lets a new server
  bind a port that another process is *actively serving* — both then hold it, and requests land
  on whichever the OS picks. The practical effect is that you change something, reload, and read
  a stale answer with no error anywhere; it has cost this project two debugging sessions chasing
  fixes that had actually worked, in a process nobody was talking to. Startup now probes the port
  first and stops with an explanation and the command to find the offender. The launcher had this
  check all along — it just lived only in the launcher, so starting the server directly walked
  straight past it. `--allow-port-reuse` opts back in.

- **Signing out is a button press again, not something a link can do to you.** `/logout` was a
  GET with no token that revoked *every* session for your account — so a page that got you to
  follow a link, or a link-prefetcher walking the header, could sign you out on your desktop,
  phone and tablet at once. (The `<img src=".../logout">` version never worked; `SameSite=Lax`
  already stopped that. A top-level navigation is the one Lax deliberately still allows.) Now:
  the header's **Sign out** is a POST carrying the same session token the login form uses, and
  it still revokes everywhere — that's the point of it. A bare GET only clears the browser
  you're sitting at and writes nothing on the server. `scope=this-device` opts out of the
  global revoke; its *absence* means global, so a malformed request fails toward more
  revocation, never less. A bad token is a visible error, never a quiet downgrade to a
  local-only sign-out.

- **`/manifest.webmanifest` is public now, and that removes a whole class of login bug.** The
  manifest handler returns a compile-time constant — app name, start URL, two colours, an inline
  icon — so there was never anything behind the gate to protect, and the login page is itself
  public and identifies the app far more loudly than a manifest could. What gating it *did* buy
  was a self-inflicted redirect: your browser requests the manifest on its own the instant the
  login page loads, the front door answered `302 -> /login?next=/manifest.webmanifest`, and that
  incidental traffic is what used to overwrite the login form's CSRF token and produce "Your
  session expired" on every attempt. `/sw.js` deliberately stays gated — serving the worker
  script is a separate question from what the worker caches.

- **`/api/panel/status` handed maintenance-job stdout to any logged-in account.** Starting a
  destructive Panel job required loopback, and cancelling one required loopback — but *reading
  the output* was a bare route with no tier check, so a logged-in account anywhere on your
  network could poll `lines`: the maintenance subprocess's own stdout, absolute paths out of
  your install and all. Moonglade is explicitly not single-user, so that mattered. `lines` is
  now loopback-only; a LAN caller gets one line saying so. Deliberately **not** a whole-route
  localhost gate — 14 of the 20 Panel actions are non-destructive and a LAN account is allowed
  to run every one of them, so gating the route would have left them watching a progress bar
  that never moves. Two tests pin both halves: the stdout stays hidden, and job state keeps
  reaching the LAN.

- **`V3.0 Flash` submitted a model string PixAI has never had.** The drawer shipped `v3.0f`, a
  guess; the real value is `v3.0.1`, confirmed by PixAI's own task detail ("Model Used: V3.0
  Flash") against that task's captured submit. The entry had been built from the correct model's
  tags with an invented value — it would have failed on the first real submit.

### Added

- **`tools/build_roster_board.py`** — renders the achievement roster JSON into one self-contained
  HTML board for review. Read-only; it never writes the roster back.
- **A real stale-bundle gate.** `loom/dist/master-storyboard.bundle.js` is committed and served
  verbatim by `/loom?bundle=1`, but nothing forced a rebuild — edit the `.jsx`, forget
  `npm run build`, and that route quietly serves old code (exactly how a blank-page bug once
  shipped). CI now rebuilds and fails if the committed bundle differs, with a message telling you
  what to run; a pytest mirror does the same locally and restores from a snapshot so a stale bundle
  is *reported*, never silently fixed. Both layers were negative-tested by corrupting the bundle on
  purpose. The narrower hook-preamble check stays.

## [2.1.1] - 2026-07-20 — Windows poster-lock fix

### Fixed

- **A finished video no longer vanishes from the panel when its poster thumbnail hits a Windows
  file-lock.** On Windows, antivirus / the Search Indexer briefly locks a just-written file, so
  the atomic rename of the poster's `.part` temp could throw `PermissionError [WinError 32]` — and
  because that happened *before* the video row was written, the clip downloaded to `videos/` but
  was never cataloged, so the Loom/Jobs panel never showed the completed result. Two guards:
  `download()`'s rename now retries a transient lock (`_atomic_replace`, a short backoff), and
  poster-thumbnail generation is now fail-soft in both the web collect (`_download_video_task`) and
  the CLI `--sync-videos` path — a poster failure logs and moves on, and the video is always
  cataloged (a missing thumb self-heals on the next `--rebuild-thumbs` / `--sync`).

## [2.1.0] - 2026-07-20 — Web parity, gallery fixes, and the retired desktop GUI

### Added

- **Web import — bring local files into the library from the browser** (closes web/CLI parity;
  unblocks the PySide6 GUI removal). A new **↑ Import** button (owner header, next to Generate)
  opens a drop-zone modal: drop images, a folder, or a `.zip` — or browse files / browse folder.
  The preview is adaptive — a removable thumbnail list for a handful, or a capped 24-tile grid
  with a "+N more" tile for a big drop — and the cap is *only* on the preview: the whole
  selection imports. Optionally tags everything to a collection. Server route
  `POST /api/import-local` is **localhost-only** (it writes into `imported/` and shells
  thumbnails on the server's machine — the same host-filesystem trust tier as the destructive
  Panel jobs, never the broader logged-in-LAN auth), reuses the CLI's `run_import_local`
  (copy → catalog `source='local'` → thumbnail, path-dedup), and expands zips with a zip-slip
  guard. Nothing is uploaded to PixAI — this is the web twin of `--import-local`, distinct from
  the PixAI `/api/upload`. Verified end-to-end in the browser: both preview states, a real
  multi-file upload into a named collection landing as catalogued local rows on disk.
- **Convert-and-download, on the surfaces the spec named.** Every download is an export-time
  transform on a temporary copy — your archive and catalog are never changed, and a converted
  file never re-enters the catalog. Three ways to reach it: the **detail page** has a plain
  one-click Download of the original (`/full/<id>?dl=1` saves the file rather than opening it in
  a tab); a **"Download collection"** button (shown while a collection filter is active) zips the
  collection's *full* membership, resolved server-side across pages; and the bulk **selection**
  Actions → Download ZIP opens an options dialog to convert to PNG/JPEG and/or embed the prompt +
  ids. Convert is always opt-in — the default (Original, no embed) is byte-identical. Videos
  always download as-is. There is no "zip the whole catalog" path — selection or named-collection
  only.
- **The gallery's Video generator is the full-parity form now.** The main-page Video tab was a
  hand-rolled "simple mode" (9 undifferentiated image slots, a 5-model select, no video/audio
  references, no negative prompt, no channel). It now mounts the shared `<mg-generate-drawer>`
  web component — the same one the Loom uses — giving the gallery the full split (6 image + 3
  video + 1 audio references), a negative prompt, the Channel control (Normal/Enhanced), and the
  complete model roster with capability gating, over the proven `/api/loom/generate` submit
  path. The video-reference slots browse your videos; "make a video from these" feeds the new
  form directly. Negative prompt and channel thread through server-side (negative in multi-ref
  is a PixAI API limitation, not ours). Retires ~130 lines of the old hand-rolled form.
- **Web entry points for five CLI-only maintenance actions** (web parity step 1). The Control
  Panel gained buttons for `--verify-dupes` and `--rebuild-similar`, surfaced `sync-artworks` /
  `sync-videos` (labeled "(full re-walk)"), and gave the existing audit/dedup buttons their
  missing variants — `audit-full` and `dedup-delete` — each as its own whitelisted action key.
  Groundwork for retiring the desktop GUI: what the GUI could do, the web can now reach.
- **Advanced sync options in the Control Panel** (web parity step 2). A collapsed "Advanced"
  section exposes the three sync variants the incremental "Sync now" can't do: a full
  non-incremental re-walk of all history (`--full-meta`), a read-only inventory count
  (`--count`, no download), and a test pull of the N most-recent tasks (`--max N`). Each is its
  own whitelisted action key; the test-pull's N is a single integer clamped server-side to
  [1, 200], so the panel's "whitelisted argv, never an arbitrary command" guarantee holds with a
  parameter in play. All three are read/append (never destructive) and kept off the scheduler.

### Removed

- **The legacy PySide6 desktop GUI is gone.** `pixai_gui.py` and its launcher
  `Moonglade Athenaeum.pyw` are deleted, and the `PySide6` dependency dropped. The two
  surfaces going forward are the **CLI** (`pixai_gallery_backup.py`) and the **web app**
  (`pixai_gallery.py`) — every GUI business capability already had a CLI flag and usually a
  web surface (a parity matrix confirmed zero GUI-only business capability), so nothing was
  lost; the GUI's only exclusives were local conveniences (open the quarantine folder in the
  OS file manager, a recently-used-models quick-pick). The web launcher `Serve Gallery.pyw`
  and the desktop-shortcut branding feature (which targets *that* launcher, not the GUI) are
  unaffected. Docs, wiki, CI comments, and the dependency list were scrubbed to match.

### Security

- **Error text is no longer an HTML-injection seam.** Several UI sinks concatenated a
  server-side `str(e)[:200]` exception string — plus job labels and a reflected task id —
  raw into `innerHTML`. The image detail page's "Suggest prompt" error now builds a text
  node (that page has no escaper in scope); the Control Panel's job-status and import sinks
  route every dynamic value through the `escH2` escaper. Proven in a browser: a crafted
  `<img src=x onerror=…>` returned as the API error renders as literal text with the handler
  never firing, and reverting the sink to `innerHTML` makes the same payload execute — so the
  fix genuinely neutralises a live payload. (`mg-notify.js` was already clean.)

### Fixed

- **Gallery-started generation, enhance, edit, and fix were failing outright (and refunding) —
  now fixed.** A catalog `media_id` is a generation *output*; the gallery drawer passed it
  straight to PixAI as an *input*, which PixAI rejected (`invalid_media_id` /
  `invalid_reference_image_media_id`) with a full credit refund — so every image, enhance, edit,
  and fix started from the gallery failed. All four paths (`/api/generate`, `/api/enhance`,
  `/api/edit`, `/api/fix`) now resolve the catalog id to its local file and upload it through
  PixAI's free S3 handshake, so PixAI receives an id it accepts — routed through one shared
  `_input_media_id()` helper.
- **An expired session no longer hangs the app instead of sending you back to login.** Around 90
  `fetch` call sites never checked the response status, so a `401` (expired login) resolved as if
  it were data: the job poller re-polled every 3s forever with the drawer stuck on "Rendering
  under the eclipse…", and the picker showed "No images found" for a full library. A single
  same-origin fetch wrapper now catches a `401` and redirects to `/login?next=<where you were>`.
- **Three more poll loops can no longer spin forever.** The Loom's `pollImg`, the Edit/Reference
  `runGen` poll, and the Jobs tray poll (`mg-notify.js`) lacked the `POLL_CEILING_MS` guard that
  `pollShot` already had, so a task that never reached a terminal state (or a persistently failing
  request) re-polled every few seconds indefinitely with the Go button stuck disabled. They now
  stop at the ceiling and report an error/stalled state.
- **A trailing-`*` wildcard no longer empties your search.** `night*` compiled to an anchored
  `LIKE 'night%'` that matched nothing (on a real library, `sample` → 24 rows, `sampl*` → 0),
  silently blanking a working search even though the box advertises the wildcard. Every term is
  now matched as a substring, so `night*` and `night` mean the same thing and a wildcard broadens
  rather than narrows; interior wildcards (`moon*light`, `n?ght`) keep their power.
- **The Loom's Image / Edit / Reference tabs now price-check before spending, like video does.**
  The video shots already verified cost + free-card coverage via `/api/price` and confirmed any
  credit spend (failing closed on an unverifiable price); the image/edit/reference generators
  only showed a flat "a free card auto-applies; otherwise it spends credits" confirm that never
  actually checked — a shot with no covering card spent silently past an OK click. A shared
  `confirmSpend()` now routes all three through the same fail-closed gate, pricing the exact
  submit body (so the number shown is what will run). `/api/price` also resolves a bare base
  `model_id` → current version the way `/api/generate` does, so the Loom's model_id-only Image
  picker gets a real cost instead of a "couldn't verify" fallback.
- **Usernames are length-bounded.** A 300-char username pushed a live **Remove** button ~980px
  outside its card, and there was no server-side limit anywhere. New `username_problem()` caps
  at 64 characters and rejects control characters — one policy shared by the `/login` bootstrap
  form, the Panel's Add-User, and `--add-web-user` — with a hard backstop in both account
  writers so even the CLI can't persist an over-long name. The account row now truncates the
  name with the Remove button pinned, so a legacy over-long name is contained too.
- **The skin-picker confirmation no longer lingers.** "✓ skin applied suite-wide" was written to
  the status line and never cleared, so it stayed on screen — and since a locked skin card is
  inert, a later click on one left the stale success showing, reading as though it had applied.
  The confirmation now clears after a few seconds.
- **The Loom's right rail no longer shows the tab strip twice.** Image/Edit/Reference/Video was
  rendered both in the rail header and again inside the generate panel, stacking a duplicate
  whenever the rail was expanded. It now lives only in the header, matching the left rail.
- **The `Serve Gallery` launcher no longer starts a second server on a port already in use.**
  Its single-instance guard bowed out only on a `200` from `/api/ping`, but that route now
  sits behind the login gate and answers an unauthenticated probe with `401`, which `urllib`
  raises — the bare `except` swallowed it and launched a second server every time (on Windows
  `SO_REUSEADDR` lets both bind the port and fight). Every response now carries an
  `X-Moonglade` marker (including the gated `401`, which runs no view), and the launcher keys
  off that: answered-with-marker → ours, connection-refused → nothing there. The browser-open
  poller shared the same blind spot and opened ~2 minutes late; it now uses the same check.
  No auth-boundary change — `/api/ping` stays gated.

- **The login lockout no longer locks you out silently.** The 5th failed attempt set
  `locked_until` but still rendered the ordinary "Invalid username or password", so you were
  locked without being told — and the *correct* password was then refused for 15 minutes with
  no stated reason. The attempt itself is unchanged (five real tries); only the message now
  tells you what happened. `_login_try_acquire`'s own docstring already promised to report a
  lockout that "was just now triggered".
- **The Jobs card no longer strands a job at "running" forever.** Two independent defects, both
  found by diagnosing one real stuck enhance:
  - `resolve_orphan_jobs` compares its `status_fn` return against `("done","failed")`, but the
    web caller passed `generation_status(...)` — which returns a *dict* — straight through. The
    comparison never matched, so **the orphan reaper resolved nothing on every run** while
    returning 0 and looking healthy. The unit tests stubbed `status_fn` with the documented
    string, so they honoured a contract the only real caller broke.
  - A task PixAI reports `done` whose outputs carry no media is terminal, but it fell into
    `/api/task-status`'s catch-all `except`, which deliberately withholds a terminal event so a
    transient 5xx cannot brick the card with a false failure. New `EmptyOutputsError`
    (subclassing `PixAIError`, so existing handlers are unaffected) separates the two.
- **Contrast and clipping, all measured in-browser rather than by eye:** the Loom's only exit
  ("← Gallery") rendered as an unstyled browser link at **1.69:1** because `.lv-top` styled only
  `button`/`label` and the control is an `<a>` — now **10.73:1**; locked skin cards used
  `opacity:.5`, dropping their description to 2.57:1 and the "locked" label to **1.88:1** (under
  even the large-text floor) — now `.82` with the label off `--overlay0`, measuring 9.00 / 4.77
  / 4.77; and the month filter was 64px against a 69px intrinsic width, so "Mon" collided with
  the native arrow and read "Mo|".
- **Native controls follow the theme.** `accent-color` was set on three individual controls, so
  everything else fell back to the browser's accent — bright blue on Windows Chrome. Declared
  once on `:root` (inherited, so a skin retinting `--accent` retints them free), plus
  `color-scheme: dark`, which is what actually stops *unchecked* boxes keeping white OS chrome
  over artwork. A grid checkbox that pinned `--lavender` now uses `--accent`, so it no longer
  drifts off-skin.
- **The saved-schedule confirmation matches the dropdown.** Picking "1 week" confirmed "every
  168h"; the status now reads the label back off the `<option>` rather than re-formatting the
  number, so the two cannot disagree again.

## [2.0.0] - 2026-07-19 — Multi-account auth, Loom V2, and the Trophy Hall

The first master update since 2026-07-07, carrying 179 commits: the Loom V2 rebuild, the
achievement system and Trophy Hall, the web creation suite, LICENSE/CI/community bucket, a
large docs consolidation, and a real multi-account authentication stack.

### ⚠ BREAKING

- **The gallery now requires a login on every path, including localhost.** Previously any
  request from the machine running the server was trusted implicitly; that bypass is gone, by
  explicit design decision — login is required from `127.0.0.1` exactly as it is from a LAN
  address. **On first run after upgrading, open the gallery locally and the login page will
  offer to create the first account.** That form appears *only* for a loopback request while
  zero accounts exist, so a LAN device can never claim the first account. Afterwards, sign in
  from any device. `--add-web-user` still exists as a recovery path but is no longer the
  primary one.
- **Password policy raised from 4 to 8 characters**, with a weak-password blocklist (repeated
  characters, sequential runs, common passwords). Applies at account *creation* only —
  existing accounts keep working and are not forced to rotate.
- **Classic Loom (V1) has been retired.** `/loom` opens straight into the V2 shell; the `v2`
  toggle and the `CardView`/`CardEditor` components are gone. There is one render tree now.
- **Destructive Control Panel actions and `/api/setup/save-key` are localhost-only.** A
  logged-in LAN session can browse and generate, but cannot organize/dedup, cancel a running
  job, edit the schedule, or overwrite the API key. `/api/server/stop` and `/restart` remain
  open to any logged-in session, deliberately.

### Known issues in this release

- **The `Serve Gallery` launcher's single-instance probe is broken.** It probes `/api/ping`
  unauthenticated to detect an already-running server; that route is now gated and answers
  401, so the probe fails and the launcher can start a *second* server on the same port.
  Observed for real during development. Fix pending — treat 401 as "ours, already running".
- **Service-worker registration fails on the login page.** `/sw.js` is gated, so a signed-out
  page gets a redirect and Chrome refuses to register a redirected worker script. It registers
  normally on the next navigation after signing in; the offline cache simply arms late.
- **`/logout` is a plain GET with no CSRF token** and revokes every session for that account on
  every device, so a hostile page can force-sign-you-out. Denial of convenience only — no data
  exposure — but tracked.

### Changed
- **Web-login password policy raised from 4 to 8 characters, with a weak-password blocklist**
  (2026-07-19, `pixai_gallery_backup.py`, `pixai_gallery.py`, `tests/`). The old rule advertised
  a 4-character minimum on a LAN-reachable app in a public repo — owner's call: "everyone is
  just gonna use 1111." New policy lives in one place, `core.password_problem()`, called by all
  three paths that can create an account (the `/login` first-run form, the Panel's Users tab, and
  the `--add-web-user` CLI recovery flag) — the previous rule was written out separately in two
  of them, so tightening it in one would have silently left the other weak. Deliberately shaped
  after NIST SP 800-63B: **length is the control, composition rules are not enforced** (forcing
  a symbol measurably pushes people toward `P@ssw0rd1` rather than toward entropy). What is
  rejected beyond length: one repeated character (`11111111`), a single ascending/descending run
  (`12345678`, `abcdefgh`), and a small common-password list, all case-insensitive. The low-level
  `add_or_update_web_user()` primitive is deliberately left unvalidated — policy belongs at the
  three human entry points, not the storage helper. Existing accounts are unaffected (the rule
  applies at creation, not at verification). 10 new tests, including the parametrized weak-password
  matrix and a guard that the policy is genuinely shared rather than re-duplicated. Also fixed a
  test that would have silently stopped testing what it claimed: the CLI mismatch test used a
  password that now trips the policy check first, so it would still have passed — for the wrong
  reason.

### Fixed
- **Four user-facing copy defects on the auth surface, two of them factually wrong**
  (2026-07-19, `pixai_gallery.py`). Found by a `/ux-copy` review pass. (1) `/login`'s sign-in
  state said *"Sign in to open this gallery from another device"* — false since the localhost
  bypass was removed, because the owner at the server keyboard now sees that exact line; now
  *"Sign in to open the Athenaeum."* (2) The zero-accounts message shown to LAN devices said to
  ask the owner to *"sign in from the machine itself"* — the wrong action, since there is no
  account to sign into; the owner must **create** the first one. (3) The same condition produced
  two different instructions — `/login` said *"session expired, please try again"* (advice that
  cannot work; the user already did) while the Users endpoints said *"refresh the page"*; both
  now say *"Your session expired. Reload the page and try again."* (4) The remove-account confirm
  warned *"This cannot be undone"*, which is both untrue (re-add the account) and less useful
  than the real consequence: it now says the person will be signed out on every device
  immediately, which is what session-epoch revocation actually does. Also replaced the ASCII `--`
  em-dash stand-ins with `&mdash;` in the two rendered strings that carried them.
- **The entire Control Panel's JS silently failed to parse, breaking everything on the page at
  once: no skins in the Skins grid, and clicking the Users tab did nothing** (2026-07-19,
  `pixai_gallery.py`, `tests/test_js_syntax.py`). Owner report: "All the skins are gone from the
  panel. Clicking the users tab does nothing." Root cause: `removeUser()`'s confirm-dialog string
  had a single-escaped `\n\n` instead of the double-escaped `\\n\\n` every other `confirm()` call in
  this file correctly uses — since the whole page is a Python triple-quoted string (not a raw
  string), Python's own lexer collapsed that `\n` into a real newline byte at *module load time*,
  before Jinja or the browser ever touched it. A JS single-quoted string literal can't contain a
  literal, un-escaped newline, so the browser's parser hit an unterminated string and refused to
  parse the *entire* `<script>` block — not just `removeUser()`. Every function it defines
  (`setPanelTab`, `loadSkins`, `renderJobs`, `loadAcct`, `loadBrand`, ...) silently never existed,
  and the tab buttons' inline `onclick` handlers failed with a swallowed `ReferenceError`. Pinned
  the exact line with `node --check` against the live-rendered page. One-character-class fix
  (`\n\n` → `\\n\\n`). The regression-guard test that exists precisely for this bug class
  (`tests/test_js_syntax.py`, Node-syntax-checks every embedded `<script>` block) never actually
  covered `/panel` — its parametrized path list predates the Users tab. Added `/panel` and `/login`
  to it so this class of bug can't silently ship again.
- **First-account creation on `/login` was completely broken: "Your session expired" on every
  attempt, surviving a cookie clear and a full server restart** (2026-07-19, `pixai_gallery.py`,
  `tests/test_web_auth.py`). Root cause: `_enforce_front_door()` redirects every unauthenticated
  request to `/login?next=<path>` — including background requests a browser fires on its own the
  instant the page loads (`favicon.ico`, `sw.js`, `manifest.webmanifest`, `/branding/*` images
  before that route went public, above). Each one is a real GET that lands on `login()`'s own GET
  branch, which used to unconditionally mint a fresh `session["csrf"]` on every single GET —
  silently orphaning the token already baked into the hidden input of whichever real, visible
  create-account/sign-in form the human had open, before they ever clicked submit. Reproduced
  deterministically via `fetch()`: load `/login`, let one incidental GET land, submit the
  *original* token — rejected, every time, which is exactly why clearing cookies or restarting the
  server never helped (the race re-fires on the very next page load, since a real browser tab
  always fires several of these background requests automatically). Fixed by only rotating the
  token unconditionally on a POST that falls through to an error (a consumed/bad token must never
  be resubmittable — unchanged); a GET now reuses the session's existing token via
  `session.setdefault("csrf", ...)`, only minting one the first time a session has none. Adversarially
  reviewed (Workflow tool, 4 independent passes): confirmed no other route has the same
  rotate-on-GET anti-pattern (`/panel` already used `setdefault`; `_check_panel_csrf` never writes
  the token at all), and confirmed the change introduces no new fixation/replay risk — the token
  was always session-scoped by design, "always mint fresh on GET" was never a deliberate security
  control, just the accidental cause of this bug. Two regression tests added
  (`test_incidental_get_does_not_invalidate_pending_csrf_token`,
  `test_failed_post_still_rotates_csrf_token`).
- **The new `/login` page didn't visually match its locked mock (`static/_mockup_login_panel.html`)
  in four separate, sequential ways** (2026-07-19, `pixai_gallery.py`, `tests/test_web_auth.py`).
  (1) Inputs had zero styling beyond `width:100%` — bare browser-default text fields on a dark
  page — fixed with real `--mantle` background/`--surface1` border/focus-ring CSS
  (`b03426f`). (2) `.login-card` itself had no background, border, radius, or shadow at all (just
  plain text floating on the page), and `.login-wrap` used `min-height:78vh` instead of the full
  viewport, pushing the card up off-center — fixed with the frosted-card treatment from the mock
  (`surface0`/`surface1` `color-mix`, 14px radius, real shadow) and a full-viewport centered wrap
  (`6578cbb`). (3) The shared brand mark's logo `<img>` (`/branding/logo.png`) was silently
  reduced to its bare "M" fallback on `/login` specifically: the front-door gate's allowlist never
  included `/branding/`, so an unauthenticated request for the image got a 302-to-`/login` instead
  of the PNG, tripped the image's own `onerror="this.remove()"`, and quietly dropped the real logo
  — invisible in the server logs unless you were watching for it. Fixed by adding `/branding/` back
  to `_enforce_front_door()`'s public allowlist (`_PUBLIC_PREFIXES`) — it's static cosmetic art
  (logo/marks/mascots) with path traversal already rejected in `branding()`, not gallery content, so
  it carries the same public trust tier as `/login` itself; a missing file still 404s, it just no
  longer redirects first. Regression test added (`test_branding_stays_public_unauthenticated`, both
  LAN and localhost) alongside removing `/branding/does-not-exist.png` from the "must be gated"
  parametrized list it used to sit in. (4) The "Moonglade Athenaeum" wordmark had no font styling of
  its own (not inside a `<header>`, so `header h1`'s rule never applied) and rendered as a plain
  bold browser-default sans H1, instead of the mock's deliberate editorial serif treatment —
  `Georgia,'Times New Roman',serif`, weight 400, 22px, `.04em` letter-spacing, plus an uppercase
  `.12em`-tracked tagline. Both are standard system serifs, no webfont needed. Scoped to
  `.login-card .brand-txt h1`/`.login-card .tagline` rather than editing the shared `.tagline` class
  every other page's header also uses. All four were only caught by live-rendering the page and
  comparing computed styles against the mock, never by reading the template.

### Added
- **Web-based first-account bootstrap + a Users tab on the Panel: no more CLI-only account
  creation** (2026-07-19, `pixai_gallery.py`, `tests/test_web_auth.py`,
  `tests/test_panel_users.py`). Owner directive, in reaction to the localhost-bypass removal
  just below making `--add-web-user` briefly the ONLY way into a fresh clone: "NO CLI first
  login bullshit... its why I built a fucking login screen in figma." Design source:
  `static/_mockup_login_panel.html` (also published as a Claude Artifact) -- its
  FieldSet/SubmitButton/ErrorLine components and two login states (normal / first-run) are now
  server-rendered in `LOGIN_HTML` instead of being a client-side mock, using this app's existing
  `.setup-step`/`.setup-row`/`.btn`/`.btn-primary` classes rather than a second style system.
  `/login`'s old CLI-pointing banner is gone entirely, replaced by three real states: (1) accounts
  exist -> the ordinary two-field sign-in form, unchanged; (2) zero accounts AND the request is
  from the machine the server itself runs on (`_is_local_request()`) -> the SAME form doubles as
  an account-creation form (username/password/confirm, a hidden `mode=create` field) that
  validates like the mock (non-empty username, password >= 4 chars, confirm match), creates the
  account via the existing `add_or_update_web_user()`, and signs the new owner in immediately via
  a new shared `_establish_session()` helper (factored out of the normal-login success path so
  both routes set up a session identically); (3) zero accounts AND the request is from a LAN
  address -> a plain "No account has been set up yet. Ask whoever runs this server to sign in
  from the machine itself first." message, no form, no CLI mention. `bootstrap_mode` (`no_accounts
  and is_local`, recomputed fresh every request) is the REAL race-condition guard, not just the
  template branch that hides the form: a hand-crafted `mode=create` POST from a LAN address is
  refused server-side even though it can carry a technically-valid CSRF token for its own session
  (a LAN device can legitimately GET `/login` and receive one) -- confirmed by a regression test
  that does exactly that. Same CSRF-token + per-IP rate-limiter infrastructure `/login` already
  had is reused as-is for the bootstrap path, not reimplemented.

  The Control Panel (`/panel`) gained a **Users tab** alongside the existing Maintenance content
  (now wrapped, unchanged, in its own tab pane) via a `.htab`/`.hall-tabs` tab bar matching the
  Trophy Hall's Summary/All/Statistics tabs (copied as plain CSS rather than loading
  `static/mg-notify.js` on this page, which would also drag in the Jobs tray/Achievement modals
  this page doesn't use). Lists accounts (`list_web_users()`, usernames only); an Add User form
  (mirroring the mock's validation, plus a "that username already exists" check so it can never
  silently overwrite a stranger's password -- `add_or_update_web_user()`'s update-or-add semantics
  stay reserved for the CLI recovery case) posts to new `/api/users/add`; each row's Remove button
  posts to new `/api/users/remove`, confirmed via the same native `confirm()` dialog the Panel's
  own Run-job/Stop-job buttons already use (not a new inline-confirm UI). Both endpoints require
  nothing beyond the existing front-door login (every account has equal trust in this app's model
  -- no admin tier was invented) and check the same session-based CSRF token pattern via a new
  `_check_panel_csrf()` helper. `/api/users/remove` refuses to remove the last remaining account
  (a real self-lockout risk -- zero accounts re-triggers the local-only bootstrap state and locks
  out every remote device until someone bootstraps a new one from the server machine). Usernames
  are rendered via `data-username` attributes and read back client-side with
  `element.closest('.u-row')` rather than being templated into inline `onclick="fn('...')"`
  strings -- an early draft did the latter and, despite HTML-escaping, was a JS-string-breakout/
  stored-injection risk for any username containing a quote or backslash; fixed before it shipped.
  The pre-existing `--add-web-user`/`--remove-web-user`/`--list-web-users` CLI flags are
  untouched and remain a valid recovery path (e.g. resetting access if the web form is somehow
  unreachable) -- just no longer the only path, and no longer advertised as the primary one.
  `tests/test_web_auth.py`'s old CLI-banner assertions were rewritten for the new bootstrap
  states; new tests cover the local-vs-LAN split, the direct-POST race guard, end-to-end bootstrap
  login, mock-parity validation, and a missing-field POST that must not crash. New
  `tests/test_panel_users.py` covers the Users tab end-to-end (list, add, duplicate-name refusal,
  CSRF enforcement on both endpoints, last-account refusal, 404 on an unknown username, front-door
  gating). Full suite green (669 tests).
- **Universal login required: the localhost bypass is gone** (2026-07-19, `pixai_gallery.py`).
  Owner directive: "I would expect to require login via any path with this new setup whether
  localhost hostname or IP." `_is_authorized_request()` -- the canonical gate the front-door hook
  and every owner-level surface below call -- no longer short-circuits true for a request from
  `127.0.0.1`/`::1`/`localhost`; a valid logged-in session is now the ONLY way in, from any
  address, including the machine the server itself runs on. `_is_local_request()` still exists
  and is still called, but now ONLY as an independent, STRICTER, additional requirement on the
  couple of routes that must never run for a remote session even when logged in
  (`/api/branding/shortcut`, destructive Panel actions -- see those entries below). A fresh
  clone/install therefore has no way in at all until an account exists, so `/login` now detects
  the zero-`AUTH_USERS` case (a fresh, uncached read of `list_web_users()`) and renders first-run
  guidance above the sign-in form -- run `python pixai_gallery_backup.py --add-web-user` on the
  server machine, then sign in -- so a confused first-time visitor sees why the form in front of
  them can't succeed yet. Account creation stays deliberately CLI-only; `list_web_users()` returns
  usernames only, never hashes, so the guidance can't leak anything.

  **Adversarial review of this exact change** (2026-07-19) found one confirmed regression that
  predates this pass but is exposed by it: `POST /delete-tasks-bulk` (irreversibly deletes tasks
  from the owner's real PixAI cloud account) had lost its own `_is_local_request()` re-check
  during the earlier LAN-auth conversion (`0fd8cee`) and was relying solely on the front door --
  meaning any logged-in LAN account, not just the owner at the keyboard, could trigger it once
  this pass made LAN logins reachable everywhere. Restored the check (same trust tier as
  `/api/branding/shortcut` and destructive Panel actions); the "Delete from PixAI" bulk-action
  button is now also hidden server-side for non-local sessions (new `can_delete_cloud` template
  flag, computed from a real `_is_local_request()`, not the always-true `is_local` the header nav
  uses) instead of rendering unconditionally for anyone who can reach the page. New regression
  test `tests/test_purge.py::test_bulk_delete_cloud_refuses_authenticated_lan_session` (logs in
  from a LAN address, asserts refusal + nothing fired/deleted, then confirms the same account
  still works from localhost) -- the pre-existing `test_bulk_delete_cloud_is_localhost_only` only
  ever exercised an *unauthenticated* remote client, so it was satisfied by the front door alone
  regardless of whether this route's own gate existed, which is exactly why the regression shipped
  unnoticed. Two stale docstrings/comments that still described localhost as an alternate path
  into `_is_authorized_request()` (`_enforce_front_door()`'s docstring and a template comment above
  the header nav) were corrected to match. Full suite green (653 tests).
- **Default-deny "front door": one global gate replaces 43 scattered per-route checks,
  and closes every route that had never had one** (2026-07-19, `pixai_gallery.py`). The
  LAN-auth work above converted existing `_is_local_request()` checks to the broader
  `_is_authorized_request()`, but a route was only ever gated if someone remembered to add
  the check when writing it -- exactly the model the owner rejected ("Gate delete and all
  critical functions behind login. It should just have a front door login screen in
  general for LAN access"). New `app.before_request`-registered `_enforce_front_door()` now
  runs `_is_authorized_request()` for EVERY request by default; the allowlist is just
  `/login` and `/logout` (LOGIN_HTML is fully inline CSS off `BASE_HTML`/`DESIGN_TOKENS_CSS`
  with no `/static/` dependency, so nothing else needs to be exempted). An unauthorized
  request gets a JSON `401 {"error": "authentication required"}` for `/api/*` (plus the two
  legacy non-`/api/` JSON routes, `/rate/<id>` and `/edit-prompt/<id>`), or a redirect to
  `/login?next=<path>` (via the existing `_safe_next()` open-redirect guard) for everything
  else. This closes every route a prior adversarial review found with **zero** auth check at
  all: `/`, `/image/<id>`, `/delete/<id>`, `/delete-bulk`, `/rate/<id>`, `/edit-prompt/<id>`,
  `/collection-add`, `/collection-remove`, `/bulk-replace-prompt`, `/panel`, `/duplicates`,
  `/health`, `/contact-sheet`, `/export-zip`, `/manifest.webmanifest`, `/sw.js`, the raw asset
  routes (`/thumbs/`, `/img/`, `/video-file/`, `/full/`, `/branding/`, `/badge-thumb/`), and
  `/api/gallery-images`, `/api/similar`, `/api/collections`, `/api/contests`,
  `/api/achievements`, `/api/skin`, `/api/ach-event`, `/api/your-art`,
  `/api/loom/export-status`, `/api/loom/export-file`, `/api/ping` -- the exact gap flagged as
  "pending an explicit owner decision" in the hardening entry below, now resolved by making
  login required everywhere rather than picking which of those stayed open.
  All 43 individual `if not _is_authorized_request(): ...` blocks were deleted as dead code
  now that the hook runs first for every request; `/api/branding/shortcut` is the one
  exception, kept gated on `_is_local_request()` specifically (layered underneath the global
  hook) since it shells out to the SERVER machine's own PowerShell/COM -- a categorically
  different trust tier than "browse the library" or "spend the owner's credits" that a LAN
  login is meant to unlock. `index()`'s `needs_key`/`catalog_empty`/`is_local` template flags
  and `/api/your-art`'s enrichment branch dropped their now-always-true
  `_is_authorized_request()` conjuncts, since reaching those lines at all now guarantees it;
  the "read-only LAN view" UI tier they used to gate is retired along with the last route
  that could show it to someone unauthenticated. `tests/test_web_auth.py` gained a
  parametrized regression suite (one case per previously-ungated route, denied from a LAN
  address + confirmed still working from localhost) plus `tests/test_web_pick.py` and
  `tests/test_purge.py` updates for routes whose real behavior changed (login-gated instead
  of silently open, or a login redirect instead of an in-app error banner); every other
  existing test that asserted the OLD per-route 403 was updated to the new global-hook 401.
  Full suite green (646 tests).

- **Real session-based web login, gating every non-localhost request** (2026-07-19,
  `pixai_gallery.py` + `pixai_gallery_backup.py`). The gallery is public code with real external
  users running their own instances -- LAN "read-only browsing" was never meant to mean
  "any-network-device browsing" once a mobile route lands, so this adds proper auth ahead of
  that. `config.json` gains `AUTH_SECRET_KEY` (generated once via `secrets.token_hex(32)`,
  persisted so sessions survive a restart) and `AUTH_USERS` (a list of
  `{username, password_hash}`, hashed with `werkzeug.security` -- scrypt as of modern werkzeug,
  timing-safe compare). Account lifecycle is CLI-only, by design: `--add-web-user` (interactive,
  `getpass` -- password never echoed/printed), `--remove-web-user <username>`,
  `--list-web-users` (usernames only, never hashes). No account ever exists by default -- an
  empty `AUTH_USERS` makes LAN login impossible until one is added.
  New `/login` (GET renders a themed form reusing `DESIGN_TOKENS_CSS`; POST verifies a
  session-bound CSRF token via `secrets.compare_digest`, then credentials) and `/logout`.
  Failed logins always show the same generic "Invalid username or password" regardless of which
  field was wrong. An in-memory per-IP counter locks out 15 minutes after 5 failures in 5
  minutes (documented as single-process-only -- resets on restart, doesn't share state across
  gunicorn/uwsgi workers). Session cookie is `HttpOnly` + `SameSite=Lax`; `Secure` stays off on
  purpose (this app is typically plain-HTTP LAN, not HTTPS -- a documented, accepted tradeoff,
  not an oversight). New canonical gate `_is_authorized_request()` = local request OR a logged-in
  session; every genuine `_is_local_request()` access-control site (44 of them, across the panel,
  generation surface, The Loom, snippets/presets, branding writes, jobs, account/claims, etc.)
  now uses it instead, preserving each route's existing response contract (JSON API routes still
  return their same JSON 401/403 shape; the two real HTML page routes, `/export-csv` and
  `/loom`, now redirect to `/login?next=...` instead of a bare 403 so browser navigation works).
  Four purely-informational uses (`needs_key`/`catalog_empty`/the `is_local` template flag, and
  `/api/your-art`'s live-views enrichment) were deliberately broadened to the same rule too, so
  an authenticated remote session gets the identical experience a local owner already had,
  instead of the UI silently hiding controls whose endpoints now accept that session. A handful
  of pre-existing routes with **no** `_is_local_request()` gate at all (`/`, `/image/<id>`,
  `/panel`, `/delete/<id>`, `/delete-bulk`, `/duplicates`, `/api/gallery-images`,
  `/api/contests`, `/api/achievements`) were left untouched -- out of this pass's explicit scope
  (converting existing gates, not inventing new ones on routes that never had one) and flagged
  as a known gap for a deliberate follow-up decision, since two of those (`/delete/<id>`,
  `/delete-bulk`) delete local backup files with no gate at all today. New
  `tests/test_web_auth.py` (21 tests): login success/failure/CSRF/rate-limit(+clear-on-success),
  the gate itself (local/LAN/authenticated-LAN), account CRUD + hashing, and the CLI flags. Full
  suite green (586 tests). `config.example.json` documents the two new fields with placeholders.
- **LAN-auth security hardening, from three independent adversarial reviews** (2026-07-19,
  `pixai_gallery.py` + `pixai_gallery_backup.py`), fixing three confirmed gaps in the pass above:
  - **Session revocation.** The plain Flask session is a stateless, client-side signed cookie --
    there was nothing server-side to revoke, so a cookie captured off plain-HTTP LAN traffic (the
    documented, accepted tradeoff of `SESSION_COOKIE_SECURE=False`) kept full account access
    after the real user signed out, and even after `--remove-web-user` deleted their account
    outright. AUTH_USERS entries now carry a `sess_epoch`; a session embeds the epoch current at
    login and `_is_authorized_request()` re-validates it (and that the account still exists) on
    every request. `/logout` bumps the epoch before clearing its own session, so signing out
    revokes every outstanding cookie for that identity, not just the browser that clicked it;
    removing an account or changing its password does the same. Exploit-confirmed via a real
    two-client PoC (a "stolen cookie" client kept 200ing after the victim's own logout) before the
    fix, 403 after -- see `tests/test_web_auth.py`'s
    `test_logout_revokes_a_stolen_cookie_on_another_client` /
    `test_removed_user_loses_access_via_old_session` / `test_password_change_revokes_old_session`.
  - **Login rate-limiter TOCTOU race.** The lockout check (fast, lock-protected) and the failure
    counter (also fast, lock-protected) sandwiched `verify_web_user()`'s slow, deliberately
    UNLOCKED scrypt comparison in between, so N concurrent requests from one IP (the dev server
    runs `threaded=True`) could all read "not locked yet" before any of them recorded a failure --
    N free guesses per 15-minute lockout cycle instead of 5. Replaced `_login_record_failure` with
    `_login_try_acquire`, which checks-and-reserves the attempt in the SAME critical section,
    before the slow call runs. `tests/test_web_auth.py::test_login_rate_limit_race_does_not_grant_extra_guesses`
    reproduces the race with real threads + an artificial delay and fails against the old code
    (confirmed by temporarily reverting the fix and re-running it) -- no more than 5 of 10
    concurrent guesses are ever evaluated now. The same reservation point also sweeps stale
    sub-threshold entries for other IPs, closing a minor unbounded-growth gap in the same dict.
  - **`/api/branding/shortcut` wrongly broadened.** This route shells out to PowerShell/
    `WScript.Shell` COM to write a `.lnk` onto the SERVER machine's own Desktop --
    `make_launcher_shortcut()`'s own docstring says "caller must gate to localhost." The 44-site
    conversion above swept it into the broader `_is_authorized_request()` along with the rest of
    "branding writes," but unlike its sibling (`POST /api/branding`, which only writes
    `out_dir/branding.json`), this one lets any authenticated LAN account trigger host-machine
    PowerShell execution -- a materially different trust boundary than the credit-spending
    features LAN login is meant to unlock. Reverted to `_is_local_request()`. New regression test
    `tests/test_branding.py::test_shortcut_refuses_authenticated_lan_session`.

  **Reviewed and confirmed NOT a bug in this pass** (left as-is, with the reasoning captured
  here rather than re-litigated later): plaintext-password storage, hash strength, secret-key
  generation, session fixation, session-data template escaping, cookie flags, CSRF-token
  handling on `/login` itself, brute-force IP keying (not header-spoofable), and timing-safe
  comparisons everywhere they matter -- all independently checked against the actual code and
  found correct. **Flagged but deliberately NOT changed, pending an explicit owner decision:**
  (1) CSRF tokens exist only for `/login`; every other mutating endpoint relies on
  `SameSite=Lax` alone -- a real inconsistency, but closing it means wiring a double-submit
  token through ~35 routes and their JS call sites, a scoped feature decision rather than a
  bug fix. (2) `/delete/<id>` and `/delete-bulk` still have no auth gate at all (pre-existing,
  called out in the entry above as a known follow-up) -- the header explicitly tells
  unauthenticated LAN visitors they have "read-only LAN view," which this contradicts, so it
  reads more like an oversight than the deliberate "curate stays open" tier the comments
  elsewhere suggest; needs a go/no-go rather than a silent change to the access model.
- **Front-door hardening, from two independent adversarial reviews** (2026-07-19,
  `pixai_gallery.py`), fixing one confirmed bug in the front-door gate above:
  - **Open redirect via TAB/CR/LF-smuggled `next=`.** `_safe_next()` blocked a literal leading
    `//` (scheme-relative) and a literal backslash, but not an embedded `\t`/`\r`/`\n`.
    Werkzeug's own `Response.get_wsgi_headers()` strips those control characters back out of a
    `Location` header value (via `iri_to_uri`) before it reaches the socket, so
    `next=/%09/evil.example` sailed past the `//`-prefix check here, yet Werkzeug itself rewrote
    it into a literal `//evil.example` scheme-relative redirect -- handed to a user immediately
    after they entered real credentials. The `\r`/`\n` variants didn't even reach a response:
    `redirect()` raised an unhandled `ValueError` ("Header values must not contain newline
    characters"), turning a real login into a 500 instead. Both reproduced end-to-end against
    the real `/login` flow before the fix (confirmed via a throwaway script against the actually-
    installed Flask 3.1.3 / Werkzeug 3.1.8). Fixed by rejecting any embedded TAB/CR/LF in
    `_safe_next()`, not just a leading `//`. New regression tests in `tests/test_web_auth.py`
    (`test_login_next_tab_bypass_no_longer_open_redirects`,
    `test_login_next_newline_bypass_no_longer_500s`, plus baseline coverage for the
    already-safe `//` case and confirming a normal `next=/loom` still redirects correctly) --
    `_safe_next()` had zero test coverage before this pass. Full suite green (650 tests).
  - **Stale comment fixed (not a code bug).** The comment above `_is_local_request()` still said
    "every generation endpoint is gated to local requests" -- true before the LAN-auth pass
    above, false since it landed (every generation/panel/Loom/snippets/branding-write/jobs/
    account/claims site was deliberately broadened to `_is_authorized_request()`, see that entry).
    Updated to state the real rule and point at `/api/branding/shortcut` as the one deliberate
    exception, so it stops misleading the next reader.

  **Reviewed and confirmed NOT a bug in this pass:** the allowlist-completeness sweep (no
  `Blueprint`/second Flask app/custom `static_folder`/reloader to route around the single
  `before_request` hook; `//login`, `/Login`, and double-slash API paths all still fall into the
  deny branch, just with an HTML-vs-JSON content-type wrinkle on the double-slash case, not an
  auth hole); `/api/branding/shortcut` staying local-only for a logged-in remote session (its own
  inner `_is_local_request()` check, confirmed live); and the LAN-auth broadening itself (~44
  sites moved from `_is_local_request()` to `_is_authorized_request()`, including the panel and
  server-stop/restart) -- that broadening is this project's own deliberate, already-documented
  design (see the "Real session-based web login" entry above), not something the front-door hook
  introduced. Also reviewed: an owner visiting their own box via its LAN IP/hostname (not literal
  `127.0.0.1`) with zero `AUTH_USERS` configured now hits a hard login wall instead of the old
  "no gate at all" degrade-gracefully behavior on routes like `/` and `/panel` -- this is the
  direct, intended effect of building the front door the owner explicitly asked for ("It should
  just have a front door login screen in general for LAN access"), already covered by
  `tests/test_web_auth.py::test_empty_auth_users_makes_lan_login_impossible`, not a regression to
  fix. Documentation-hygiene item, left as-is: ~30 route docstrings elsewhere in the file still
  say "Localhost-only" despite calling `_is_authorized_request()` (the broader LAN-login check),
  a leftover from the same LAN-auth pass -- cosmetically stale but not misleading about an actual
  gate the way the `_is_local_request()` comment fixed above was, and touching ~30 docstrings is
  a separate cleanup pass, not a security fix.

  **Owner decision (2026-07-19):** `/api/server/stop`/`/api/server/restart` stay in the
  broader "any logged-in LAN session" tier, unchanged. Destructive Panel actions (the
  `--dedup --apply --dedup-delete`/organize/rebuild-thumbnails class, reachable via
  `/api/panel/run`) get the same carve-out `/api/branding/shortcut` already has: gated on
  `_is_local_request()` in addition to the existing `confirm=true` requirement, so a logged-in
  LAN account can generate and browse but not run destructive maintenance on the owner's local
  files. New regression test `tests/test_panel.py::test_destructive_action_refuses_authenticated_lan_session`
  (proves a logged-in remote session gets 403 while the same account from the real local machine
  still works). Full suite green (651 tests).
- **Job Tracker Step 2 complete: the CLI now logs to the same activity feed** (2026-07-19,
  `pixai_gallery_backup.py`). Closes the last of the three original Step 2 sources — Control
  Panel actions and bulk cloud-delete were already wired; running the CLI bare from a terminal
  (`--sync`, `--update`, `--generate`, `--generate-video`, plain download) now also writes to
  `out_dir/jobs.jsonl`, each run getting a `cli-<uuid>` job id (mirroring the existing
  `panel-`/`bulkdel-` convention). Logging is fail-soft (wrapped so a logging error can never
  break the actual command) and a no-op when spawned by the panel (`MOONGLADE_PROGRESS=1`), so a
  panel-run job still logs exactly once, never twice. New `tests/test_cli_job_logging.py` (10
  tests) covers start→done, failure→`failed`+error+re-raise, progress-heartbeat collapsing into
  one job entry, and the panel-parity no-duplicate case. Full suite green.
- **Mobile polish: three popups no longer run off a 320px-wide screen** (2026-07-19). The Job
  Tracker/Activity tray (`#jobs-tray`) and the snippet/tag popups (`#snip-menu`, `#tag-suggest`)
  had flat `max-width`s that could exceed the viewport itself on the narrowest real phone widths
  (confirmed live at 320px: the tray hung 60px off the right edge). All three now clamp to
  `min(<old-max>, calc(100vw - Npx))`; desktop/tablet sizing is unchanged. Live-verified at
  320px.
- **Job Tracker + achievement toasts, now shared with the Loom** (2026-07-18, `static/mg-notify.js`
  — the fifth shared file, and now the single source: the gallery's own inline copies are
  deleted). Extracted `Ach` (the achievement modal + celebration toasts), `Toast` (general
  corner notices), and `Jobs`/`JobsCard` (the activity tracker) verbatim out of the gallery's
  inline `<script>`; both the gallery and the Loom now load one `<script src>`. The Loom's own
  shell gained the two DOM anchors (`#jobs-fab`/`#jobs-tray`) the visible tracker card needs —
  the achievement-toast path needs no anchor at all, since it builds its own DOM from scratch.
  `Ach.open()`/`close()` gained a null-guard (a global Escape-key listener calls `close()` on
  every keypress app-wide; the original was unguarded and would have thrown in any host without
  the Achievements modal). `Jobs` gained a new `register(id,label)` entry point — logs the
  generation into the shared activity card without starting a redundant second poll loop, for
  hosts whose own generation flow already owns a hardened, independently-completing poller
  (the Loom's `pollShot`/`<mg-generate-drawer>`'s `_poll`); both the board's `generateShot` and
  the drawer's submit path (via the Loom's own `onVideoSubmit`) now call it, closing the
  confirmed gap where `/api/loom/generate` never showed up in the activity log until caught
  after the fact by the orphan-job reconciler. `.ach-m2`/`#mg-toasts` z-index raised so a
  celebration or completion toast is never silently swallowed by the Loom's own full-screen
  overlays (Deep Focus, the Sequence Player) — both common Loom interactions the gallery
  doesn't have an equivalent of. The Job Tracker's default bottom-left position was confirmed
  (via live measurement, not assumption) to collide with the Loom's own left Cast panel once
  scrolled to its end — fixed with a small, Loom-scoped position override. Designed then
  adversarially reviewed (Workflow tool) before shipping — the review moved the drawer-side
  wiring off the host-agnostic `<mg-generate-drawer>` component onto the Loom's own code,
  caught a missing de-dupe guard on the new `register()`, flagged a shared CSS rule
  (`.ach-modal`, base chrome for three different modals, not achievement-exclusive) that needed
  an explicit "don't scope this independently" comment, and caught that the tray-collision risk
  was asserted but never actually measured — it turned out to be real. 555 Python + 111 Node
  tests green (+1 new Python smoke test). Live-verified on both surfaces: Trophy Hall and the
  Contests/YourArt modals render correctly on the gallery with zero regressions, a real
  `Jobs.register()` call round-trips through `/api/jobs` into a rendered tray row, the
  tray-collision fix measures clean, z-index values sit above the Loom's overlay ceiling, zero
  console errors anywhere.
- **Design-mockup pass: cast-row gallery picker, wider Generate panel, Duration/Audio dedup**
  (2026-07-18, owner-approved against a locked interactive Artifact mockup before
  implementation). Three bundled pieces:
  - **Cast & Assets per-row gallery picker**: each detailed cast row (image or video kind —
    audio has no gallery to pick from) gets an icon, sized to match the existing thumbnail
    slot (38×32px) and placed first in the row, that opens the shared gallery picker and sets
    that row's media directly — previously the only way to pick from your own gallery was the
    bottom "+ add from gallery" button, which always created a brand-new row. The existing
    local-file-upload thumbnail and both bottom buttons are unchanged.
  - **Generate panel widened 380px → 560px**: the old width forced the Multi-Reference
    image-ref grid (6 slots × 72px + gaps) to wrap into an uneven 4+2 layout; 560px is well
    past the 500px point where all 6 fit in a single row.
  - **Duration + Generate-audio/Audio-language write-back, mirroring Mode-sync's pattern**:
    new `mg-duration-commit` and `mg-audio-commit` drawer events (fired only from a real user
    change, never from `prefill()`'s programmatic writes) let the host durably persist these
    fields onto the card, so the Continuity panel's duplicate Duration chips and
    Generate-audio checkbox + Audio-language chips are deleted outright — no reducer needed,
    since neither field has any cross-field coupling (confirmed by full grep, unlike Mode/
    Connect or the prompt override). `shotPayload`/`shotText`/`generateShot`/`batchGenerate`
    needed zero changes — verified, not assumed, that they already read these fields directly
    off the card. The dead `AUDIO_LANGUAGES` const was removed alongside its only reference.
  - **The Prompt textarea is deliberately NOT touched this pass** — it's the only write site
    for a shot's *base* prompt (the string `shotText()` keeps recomposing alongside later
    Camera/Lighting/cast edits); the drawer's own prompt box only ever writes a frozen
    override that's never re-woven. Flagged by adversarial review as a real capability loss,
    not a mechanical dedup — owner chose to hold it out pending a separate decision (ship the
    override-only model, or give base-prompt editing a new home in Deep Focus, mirroring how
    Deep Focus stayed the sole way to set V2V after Mode's chips were deleted).
  Both the Duration/Audio dedup and the cast-row picker + panel width were designed (and the
  dedup piece independently adversarially reviewed) before implementation. 111 Node tests
  green, live-verified against a real project: the picker opens correctly filtered by row
  kind, and duration/audioGen/audioLanguage all persisted correctly through a full
  unbind/reselect (fresh prefill from the card), zero console errors.
- **Drawer↔card Mode-sync fix + legacy Mode-chip removal** (2026-07-18, found live-testing a
  real multi-reference shot: the drawer's mode segment kept visibly "bouncing back" to First
  Frame). Root cause: the drawer's mode-segment click handler called its internal `_setMode()`
  directly, which never told the host anything changed, so the next prefill re-sync silently
  reasserted whatever the card's `mode` field still said. Fixed by adding a `mg-mode-commit`
  event, fired ONLY from a direct user click on the drawer's own segment buttons (never from
  `_setMode()` itself, which `prefill()`/`_applyModelGating()`/`setRefs()` also call internally
  — dispatching from those would create a host↔drawer sync loop). The host listener maps the
  drawer's 3-value `r2v` to the card's `R2V` (never `V2V` — confirmed at the server layer that
  V2V/R2V already resolve to the identical generation path, and V2V is excluded from pricing/
  telemetry) and routes through the existing, tested `setShotMode` reducer, preserving its
  Continuity-reset coupling (`connect:"flf"→"new"`). **The old duplicate Continuity-panel Mode
  chips are deleted outright** — the drawer's segment is now the single source of truth for a
  bound shot's mode; Deep Focus's own, structurally separate Mode chips are deliberately left
  in place as the sole remaining way to set a card to V2V (no drawer is mounted in that modal).
  Designed then independently adversarially reviewed before implementation (Workflow tool,
  design + review agents) — the reviewer caught two real bugs the design missed: (1) a model-
  gating auto-switch (`_applyModelGating`) can make the drawer submit a different mode than the
  card believes, with nothing reconciling it if the owner generates immediately after browsing
  models, permanently desyncing badges/telemetry from what actually rendered — closed by
  reconciling `card.mode` from the actually-submitted payload in the existing `mg-submit`
  listener; (2) the drawer's 3-value display can't distinguish an existing V2V shot from R2V,
  so a redundant click on an already-highlighted Multi-Reference button would have silently
  downgraded a real V2V shot to R2V — closed with a no-op guard. Also rebuilt the opt-in
  `/loom?bundle=1` pre-built bundle (`npm run build`), flagged by the same review as going
  stale otherwise. Live-verified against a real project: drawer clicks now durably update the
  card with no bounce-back across re-renders, the FLF↔Continuity coupling still fires, the
  redundant-click guard no-ops cleanly, Deep Focus's Mode chips still work, zero console
  errors. 93 Node tests green (no new test coverage needed — reuses `setShotMode`/
  `setShotConnect`'s existing coverage unchanged).
- **Standing cost-to-finish pill + durable prompt overrides + batch-generate hardening**
  ("Batch 2" of the generation-flow shakedown, 2026-07-18). Three items, each designed then
  independently adversarially reviewed before any code was written (one design agent's first
  attempt came back as an unusable placeholder stub; the rescue plan written to replace it
  was itself given a second, independent review before being trusted) — both review passes
  caught real bugs that would have shipped otherwise: stale React closures that would have
  made a tally silently never update, a busy-guard wired to an effect dependency array that
  would never actually fire, and an empty-prompt check written against the always-non-empty
  COMPOSED prompt string instead of the shot's real raw field (structurally incapable of ever
  triggering).
  - **Cost-to-finish pill**: a live free/paid/credits/unpriced estimate next to
    "Generate all (N)", not gated behind the confirm dialog. A per-shot price cache
    fingerprints only the fields that actually affect `/api/price` (verified against the
    server's own price allowlist — prompt/camera/lighting never do), so editing prose never
    triggers a re-price; refreshes on a 600ms board debounce plus click-to-force.
  - **Durable prompt overrides**: hand-editing the drawer's composed-prompt box now persists
    (`c.promptOverride`/`c.promptOverrideText`) across a shot deselect/reselect and reload,
    instead of only affecting one immediate Generate click. `shotText()` returns it verbatim
    (never merged with Camera/Lighting/cast composition — merging would duplicate that
    scaffolding deeper into the text on every re-sync). The toolbar's "Generate all" button
    now flushes a pending edit and locally patches it in before submitting, since React
    defers re-rendering past the same synchronous click that would otherwise read stale data.
  - **Batch hardening**: `batchGenerate` now excludes already-"wip" shots (not just "done")
    from resubmission, flags empty-prompt shots in its confirm text, and drives a live
    "N submitted, M done, K failed" banner via a `batchTally` scoped to that run's own card
    ids and written exclusively through React's functional setState form (a plain read/write
    would silently corrupt under the submit-loop and poll-loop writing concurrently).
  Live-verified end to end against a real project (override surviving a real shot-switch
  round trip, the empty-prompt flag firing correctly in a real batch confirm, the cost pill
  computing a real estimate for an attached shot) — not just code review. 93 Node
  (+13 new) + 554 Python tests green.
- **`<mg-generate-drawer>` gets per-model mode gating**, off the newly-completed 7-model video
  capability matrix (`private/GENERATOR_SURFACE.md`, owner screenshots): the First
  Frame / First & Last Frames / Multi-Reference mode buttons now show only what the selected
  model actually supports (Multi-Reference is exclusive to the V4.0 pair; First & Last spans
  the three V3.0-generation models; V2.7 and V3.0 Flash are First-Frame-only), auto-switching
  off an invalid mode on model change rather than allowing a submit shape PixAI's own UI never
  offers. Same pass, all sourced from the matrix: the model roster reordered to match PixAI's
  real list (V4.0 Preview now before V4.0 Lite Preview, previously backwards); frame slots
  relabeled to PixAI's exact "Start Frame" / "End Frame (Optional)" (End now renders as its
  own block — leaving it empty already submits fine, matching PixAI's own optional-end
  behavior); the "Priority" control renamed "Basic / Professional" (PixAI's real tab pair, not
  a speed setting — a wrong label, not just an imprecise one); and the Camera-movement
  dropdown now uses PixAI's real option wording (Unset / Side-to-side move / Vertical Pan /
  Zoom in or out / Camera sweep / Tilt up or down / Camera spin) instead of internal-value
  placeholders. Verified live against a running server: all three gating tiers clicked
  through, zero console errors, 554 Python + 80 Node tests green. Investigated but **not**
  shipped this pass: removing the Loom's own duplicate Mode/Duration/Prompt/audio controls
  (per the locked convergence mockup v3) — a separate "Generate all" batch path reads those
  fields directly off the shot card, bypassing the drawer entirely, and the Video tab's prompt
  textarea is the only write site for it in the whole app; deleting the controls as designed
  would have silently frozen prompts/audio settings while real paid generations kept firing
  off stale data. Needs its own pass (see `docs/STATE.md`).
- **The Loom's Video tab now mounts `<mg-generate-drawer>`** — the same shared component the
  gallery panel's full-parity build produced, replacing the hand-rolled Generate button + bare
  prompt textarea. Mode, Continuity, the raw prompt, Duration, and Camera/Lighting/Transition
  in/out stay Loom-native fields (unchanged — still feed the reel, export, and the FLF-
  continuity coupling exactly as before) sitting above the drawer as a weave strip; the
  drawer's prompt box shows `shotText()`'s live composition and auto-re-syncs on any
  weave-field change unless the owner has hand-typed in the box since (tracked via the
  component's new `mg-dirty` event), with an explicit "↺ re-sync from shot" override. The
  drawer's own `mg-pick-request` (type-filtered), `mg-submit`, `mg-result`, and `mg-error`
  events bridge into the Loom's existing `genState`/`setCardStatus` machinery via two new
  handlers threaded down from the parent component (`onVideoSubmit`/`onVideoResult`/
  `onVideoError`), so the board card's live status badge, tab-close resume (`pendingTaskId`),
  and the finished clip landing on the shot all keep working identically to every other
  generation path — the component now owns the actual network calls, the Loom still owns what
  a submit/result means for that shot. R2V's image/video banks auto-populate from the shot's
  cast and other refs via `buildShotPayload` (loom-core.js) — the same tag-sorted composition
  `shotText()`'s `@imageN` citations are written against, so a resolvable cast member lands in
  the slot position its prompt citation actually references. (An initial version of this build
  left the banks empty for hand-filling, which silently broke those citations — a hand-picked
  slot order that doesn't match the text's tag numbering binds `@image1` to the wrong image or
  to nothing at all, wrong output with no error. Caught and fixed same day.) Continuity
  "extend" adds the previous shot's clip as an extra video ref on top; unresolvable placeholder
  cast (no image ever attached) is correctly excluded from the array while staying in the
  prompt text, matching the pre-existing system's own behavior. Audio refs remain the one gap
  `buildShotPayload` never covered, before or since. Found and fixed live while wiring this: an
  out-of-range shot duration (8s, no matching `<option>` in the drawer's fixed 5/6/10/15 list)
  silently resolved to no selection and submitted `duration:0` — `prefill()` now snaps to the
  nearest valid duration, matching the server's own `_snap_video_duration`. Live-verified
  against a real project end to end (mode/duration sync incl. the snap fix, hand-edit-wins +
  re-sync, cast auto-population landing in the correct tag-matching slot, a real type-filtered
  pick landing in a slot, and the submit/result event chain correctly updating the board card's
  status/thumbnail/duration), zero console errors, 549
  Python + 80 Node tests still green. The gallery keeps its own working Video tab — that swap
  is next, live-QA'd.
- **`<mg-generate-drawer>` reaches full PixAI Multi-ref parity.** Extends the Phase 1 Video
  form (2026-07-18 earlier today) to match the owner-locked "Video Tab — Full Parity Mockup
  v1": 6 image + 3 video + 1 audio reference slot (video slots show real poster thumbnails
  with a play badge; audio uploads directly to `/api/upload`, bypassing the gallery picker
  entirely since audio isn't catalogued anywhere), a negative-prompt field, Channel
  (Normal/Enhanced — PixAI's own wording, ships defaulting Normal), and the full 7-model
  roster with capability chips (2 models ship disabled pending a `--dump-params` capture:
  V3.0 Flash, V2.7 — the previously-planned "3 need capture" reading was wrong on inspection:
  the site's "V3.0 High Consistency" is our existing `v3.0` key under its fuller real name,
  not a 6th distinct model). `mg-pick-request` now carries a `kind` hint so a host filters
  image vs. video picks; `prefill()` gained `video_refs`/`audio_ref`/`negative`/`is_private`.
  Server-side: `build_shot_video_params()` threads `negative` (i2vPro only — referenceVideo's
  captured submit shape has no such field, a genuine API gap, not an oversight) and
  `is_private` through to both builders; `/api/loom/generate` and `/api/price` both read the
  new payload keys. Live-verified end to end against the real server: real catalog image +
  video picks (each correctly type-filtered), a real audio upload round-trip (`/api/upload`
  → real media_id → chip → payload), real `/api/price` pricing for a mixed image+video+
  negative+Enhanced request (84,000 credits), and bank isolation between i2v/flf's own slot
  and r2v's separate image bank on mode switch. Zero console errors across the whole sequence.
  +6 tests (549 total). Nothing mounts the component yet — the gallery keeps its own working
  tab; the Loom mount is next.

### Fixed
- **Give-up-timer softening: a slow-but-live render was being punished identically to a real
  server failure** (2026-07-18(pm)). The 20-minute give-up timer shipped earlier the same day
  fixed a real bug (a dead generation polling forever, indistinguishable from a live one) but
  traded it for an opposite one: at 20 minutes elapsed with no result, it wrote a REAL
  terminal `status:"error"` and severed `pendingTaskId`, unrecoverable short of a fresh submit
  — even though the owner's own motivating "lost generation" turned out to be a late-surfacing
  content-moderation rejection, not an actual timeout. Elapsed time alone no longer ends a shot
  in failure in either poll loop (the Loom's own `pollShot` or `<mg-generate-drawer>`'s
  independent `_poll` — both load-bearing, tracking different submission paths). Three tiers
  instead: 20min downshifts the poll cadence and shows "Taking longer than expected"; 90min
  downshifts further and shows "Still going after Nh — unusual"; a 6h ceiling stops this tab's
  own network polling (protects against a permanently wedged/deleted task) but leaves
  `status`/`pendingTaskId` untouched — a reload, or clicking the card's own "paused" badge,
  always gives it a completely fresh budget. Only a genuine server-reported failure
  (`classifyTaskStatus`'s `"failed"` phase, unchanged) can still end a shot in real error.
  `genStartedAt` is now persisted on the card (both submission paths) so the 6h ceiling means
  something across a reload — without it, every reload would silently re-arm a full fresh
  budget regardless of true elapsed time. `batchTally` gained a `stale` outcome, tracked via an
  `outcomes: {[cardId]: "done"|"failed"|"stale"}` map rather than flat counters, so a batch
  shot that later resolves after being marked stale doesn't double-count. Designed then
  independently adversarially reviewed (Workflow tool) before implementation — the review
  caught a Critical bug in the first draft (two new callbacks referenced in a dependency array
  without being threaded through `LoomV2`'s own props, which would have thrown
  `ReferenceError` on the very first render and replaced the entire Loom UI with its error
  boundary fallback), plus the stale-batchTally double-count, a scope bug in a shared time-
  formatting helper, and the missing `genStartedAt` persistence — all fixed before shipping.
  Also flagged, not yet acted on: `/api/task-status`'s exception handler returns HTTP 200
  `{phase:"failed"}` for a transient local blip, which both poll loops currently can't
  distinguish from a genuine PixAI-reported failure — a decision for the owner on whether to
  change that endpoint's error-branch shape. 111 Node tests green (+18 new, a permanent parity
  test guarding `<mg-generate-drawer>`'s local `friendlyGenErr` copy against silent drift from
  `loom-mutations.js`'s real one). Live-verified: no console errors on load (the fix for the
  Critical threading bug), normal wip/done card badges unaffected.
- **Timeline drawer's video preview was too small and left-justified** instead of centered —
  CSS-only: `.sb-shotprev`/`.sb-shotprev-wrap`'s `max-width` raised 340px→460px with
  `margin:auto` centering, and the preview zone/drawer's "full" height grown proportionally
  (280px→362px zone, 360px→442px drawer) so the larger preview doesn't overflow into the reel
  scrubber below it. Live-verified via direct DOM measurement (both centers align, an 11px
  safety margin below the preview, zero console errors) — the `computer` tool's screenshot
  capability was unreliable this session, so exact pixel geometry was confirmed via
  `getBoundingClientRect()` instead of a visual screenshot.
- **`<mg-generate-drawer>`'s own error rendering didn't recognize a content-moderation
  rejection** ("Sensitive content." from a real submit) and showed the raw server string
  instead of a friendly message — even though the Loom's own poll path
  (`loom/src/loom-mutations.js`'s `friendlyGenErr`/`classifyTaskStatus`) already had this
  mapping. The drawer is a plain host-agnostic `<script>` with no build step and
  deliberately can't import that ES module, so the fix is a local, verbatim port of
  `friendlyGenErr` (same regex patterns, same replacement text) inside
  `static/mg-generate-drawer.js`, wired into only the two call sites that carry a genuine
  raw server string — the submit-failure branch (`_generate()`) and the poll
  task-failure branch (`_poll()`) — not the audio-upload/network/timeout call sites,
  which are already hand-written friendly text. `esc()` still runs on the mapped message
  same as before, so no XSS regression. Flagged as a duplication risk (same
  acknowledgment style as `GIVE_UP_MS` mirroring the Loom's `POLL_GIVE_UP_MS`): if
  `friendlyGenErr` in `loom-mutations.js` ever changes wording, this copy needs a matching
  hand-edit. Because the component is shared, this also fixes the Loom's own Video-tab
  mount (`onVideoError` previously showed the same raw string) for free, and will cover
  the plain gallery's own Video tab automatically once it's swapped onto
  `<mg-generate-drawer>` (still pending — see "Web components" above).
- **Five generation-lifecycle bugs in the Loom, found live-testing real generations (a "great
  shakedown session").** `<mg-generate-drawer>` is now mounted once and permanently in the
  Video tab (CSS-hidden on other tabs, never conditionally unmounted) — switching tabs
  mid-render used to kill the drawer's in-flight poll outright and strand the shot at "wip"
  forever, recoverable only by a full reload. A completion handler now routes results/errors
  via the shot id captured at submit time instead of re-reading whichever shot happens to be
  selected when the event fires — switching shots mid-render used to attribute the finished
  clip (or failure) to the wrong card. A real terminal `status:"error"` now exists on the card
  (previously only todo/wip/done — a failed render left status:"wip" forever, indistinguishable
  from one still genuinely rendering, with no cancel button anywhere in generation); both poll
  loops now give up after 20 minutes instead of retrying forever. The drawer's image/video/
  audio reference slots now explicitly clear when a newly-selected shot or draft has none,
  instead of only overwriting when there's something new to show — switching from a shot with
  cast refs to an empty draft used to leave the previous shot's images sitting in the drawer,
  unnoticed, ready to submit against the wrong generation. And `promptDirtyRef` (tracks a
  hand-edit in the drawer's prompt box since the last auto-sync) now resets on an actual shot
  change, not only via the manual "↺ re-sync" button — it used to latch true forever after the
  first hand-edit anywhere in a session, freezing every other shot's drawer on stale prompt
  text with no warning. Live-verified end to end (DOM identity checks proving the drawer
  survives tab round-trips, real shot-switch/unbind sequences proving refs and prompt both
  clear correctly); 554 Python + 80 Node tests green.
- **`/api/price`'s video branch required an image even for a video- or audio-only Multi-ref.**
  Found while wiring the ref-slot expansion above: the price-preview gate checked only
  `images`, so a valid R2V request carrying nothing but a video or audio reference silently
  failed with "pick a source image" even though the same request would have submitted fine.
  Now accepts any reference kind alone for R2V specifically; I2V/FLF still correctly require
  an image (they're frame-anchored by definition).
- **The Loom silently dropped a shot's end frame from real generations.** Continuity's
  "First→Last" chip (its own hint: "land on an exact end frame") and Mode's separate `FLF`
  chip both read as the same thing to a user, but only `mode==="FLF"` actually made the close
  frame reach PixAI — `shotPayload` and the server's `build_shot_video_params` both check mode
  alone, with no fallback to Continuity. Setting Continuity to First→Last with Mode left on
  I2V (the default) generated normally, completed normally, and silently used only the open
  frame — confirmed against a real spent generation. Mode and Continuity are now coupled in
  both directions (`setShotMode`/`setShotConnect`, `loom/src/loom-mutations.js`): selecting
  First→Last forces Mode to FLF, and moving Mode away from FLF clears a Continuity claim that
  can no longer be true. This exact bug was found in the original Loom architecture audit and
  filed as "later phase" — it never got tracked past that now-archived doc. Live-verified: the
  failure state is unreachable through the UI in either direction.

### Added
- **`<mg-generate-drawer>` Phase 1 — the shared Video generation form.** Third Option-A web
  component (`static/mg-generate-drawer.js` + standalone harness): a faithful extraction of
  the gallery drawer's Video tab, which is the locked standard — I2V/FLF/R2V modes, picker
  slots with `@imageN` badges and hover previews, the chip-prompt contenteditable, model /
  duration / camera / priority selects, the audio checkbox + 5-language picker, live
  `/api/price` cost line (free-card + V4.0-warn branches), and the submit → poll → result
  lifecycle, all self-contained. Hosts integrate through events only (`mg-pick-request`
  keeps it picker-agnostic; `mg-submit` / `mg-result` / `mg-error` report the run) plus
  `setRefs()` / `prefill()`. Verified live against the real server: exact known pricing
  (i2v 27,500; v4.0 70,000/5s), real catalog picks through `<mg-gallery-picker>` servicing
  the pick-request seam. Nothing mounts it yet — the gallery keeps its working tab, and the
  Loom mount is the next step.
- **Video generation gained audio controls, on both surfaces.** PixAI's real audio-language
  options (English/Japanese/Chinese/Korean/**SE only** — sound effects with no spoken
  dialogue, not silence) were reverse-engineered in `private/GENERATOR_SURFACE.md` well before
  today but never reached a control anywhere. The Loom's Video tab had **no audio UI at all**;
  the main gallery's Video tab had a checkbox + 4-language picker but was missing SE-only. The
  Loom now has the same checkbox + 5-option language picker, threaded through `shotPayload` →
  `/api/loom/generate` and `/api/price` (the price preview previously only read the gallery's
  `audio` key, not the Loom's `generate_audio` — fixed so both surfaces' previews reflect the
  real cost). The gallery's picker gained the missing SE-only option.

### Docs
- **A second audit found the first consolidation's own gaps.** A 27-agent pass covering every
  live doc (root, `docs/`, and the whole wiki — 23 files) for renewed drift found 23 more
  false/stale claims, most concentrated in `docs/LOOM.md` (never updated for the classic-Loom
  retirement or the two-tier export/Draft/Look/ShotPreview-toolset work that shipped after it)
  and a `docs/STANDARDS.md` merge recommended 2026-07-16 that was never executed — the two
  originals sat standalone for a day and one of them (`DESIGN_WORKFLOW.md`) visibly drifted from
  its own merged copy in the meantime. Fixed: `docs/LOOM.md` decontaminated (wrong button glyph,
  a stale frame-handoff description, a removed "open full ↗" link, the old 2-tier export claim,
  and two real content gaps — the multi-storyboard switcher and the Footage tab were entirely
  undocumented); `docs/CURATION_STANDARD.md` + `docs/DESIGN_WORKFLOW.md` merged into
  `docs/STANDARDS.md` and the two originals frozen under `docs/archive/`; five dangling
  cross-references to the archived filenames fixed (`CLAUDE.md`, `docs/STATE.md` ×3); `CLAUDE.md`'s
  documented `build_video_parameters()` submit shape corrected (no top-level `channel` field —
  that's `isPrivate`); `README.md`'s in-repo-doc and wiki-page lists brought current;
  `CONTRIBUTING.md`'s "three main files" corrected to the real five modules; a broken
  `CHANGELOG.md` cross-reference and a self-contradicting dated entry fixed; five wiki pages
  corrected (`Generating.md`'s stale classic/V2 claim, `Troubleshooting.md`'s unscoped
  `inferenceProfile` auto-fallback claim, `FAQ.md`/`Home.md`'s false "Troubleshooting covers hash
  recapture" claim, and — highest priority — `Trust-and-Safety.md`'s incorrect claim that
  `--organize` is dry-run-by-default like `--dedup`; it isn't, it runs live by default and is
  opted out via `--dry-run`). `docs/` maintained files: 6 → 5.
- **`CLAUDE.md` trimmed from 466 to 264 lines**, executing the deferred plan above: the stale
  "three-file" table, both per-function reference tables, the `Catalog / SQLite` section, and the
  GUI module-cache note moved into a new `docs/architecture.md` "Module reference" section (plus
  two invariants and an `_IMAGE_EXTS` fact that were only ever stated in `CLAUDE.md`, now added to
  `architecture.md` too so nothing was lost); the redundant `Creating` section (a compressed
  restatement of the function tables) deleted outright; `The web suite` / `Since 1.9.x` condensed
  into a new `docs/architecture.md` "The web suite" section (structure) with current
  shipped/in-flight status left to `docs/STATE.md`; `Achievements & the Trophy Hall` trimmed to a
  pointer at `docs/STATE.md` (status) + `docs/ART.md` (art direction); the one-shot `--sync` step
  list moved to `docs/architecture.md`, with the broad-except landmine warning kept in `CLAUDE.md`
  since it's exactly the kind of gotcha that file exists to carry. `CLAUDE.md` is now rules and
  protocol; facts live in one place each, per its own hierarchy rule.

### Changed
- **Classic Loom (V1) retired — the Loom is now a single surface.** With V2 at full feature parity,
  the classic render tree is gone: the `CardView`/`CardEditor` components, the whole classic header /
  reel / board JSX, the `v2` layout toggle, and the "◫ V2 layout" / "← Back to classic" buttons are
  deleted. `/loom` opens straight into the V2 shell. The shared components it relied on
  (`ProjectSwitcher`, `FrameSlot`, `ShotPreview`, `SequencePlayer`, `ImportCollection`, the
  `ExportMenu`) and the pure state/logic layer are untouched, so there is now one render tree instead
  of two hand-duplicated ones. The bundle drops ~39 KB (206 → 167 KB). This is the final step of the
  Loom architecture audit's consolidation plan; render-tree unification is complete. (Dead classic-only
  `sb-*` CSS rules remain in the `STYLES` block — harmless, prune when convenient.)

### Added
- **The Loom — ShotPreview editing toolset.** The V2 timeline preview gains **fast-forward /
  rewind** (step the playhead for framing), **Split** (cut a shot in two at the playhead — both
  halves keep the same clip with the trim range divided, so Export plays them back-to-back as a
  real cut), and **Crop** (drag a rectangle over the frame; stored per shot and applied at export
  via ffmpeg's `crop` filter). Play/pause and hover-scrub already shipped.
- **The Loom — project "Look" block.** A project-level style line (in Cast & Assets) appended to
  every shot's prompt, so the whole film reads as one visual world — the project-level analogue of
  the per-shot cast block.
- **The Loom — Draft mode.** A top-strip toggle that renders every shot at the cheaper `basic`
  quality for blocking out an animatic; turn it off and re-generate the keepers at pro. The price
  preview reflects the draft quality too, so the cost shown is the cost charged.
- **First-run wizard** — the gallery's home page now guides a fresh clone from nothing to a
  working gallery without a manual `config.json` edit: no key configured shows a paste-a-key
  form (validated live against PixAI before it's saved), and a key with an empty catalog shows
  a "Sync now" button that runs the existing `--sync` Panel job and reloads when it finishes.
  Neither banner shows once the catalog has rows, or for a LAN request — this is an owner-only
  action. Fixed a real blocker found while verifying this live: `pixai_gallery.py`'s CLI entry
  point used to exit with a console error if the (git-ignored) output folder or `catalog.db`
  didn't exist yet, so the wizard could never render on an actual fresh clone; it now creates
  the folder and an empty catalog and starts normally. Also fixed, found the same way: the new
  save-key endpoint's first draft validated a freshly-pasted key by reusing the app's normal
  session-building path, which prefers an already-loaded in-memory key over a fresh file read
  — so a garbage key was silently "verified" against the real cached one instead. It now
  builds a throwaway session from the submitted key alone and only writes `config.json` after
  that call genuinely succeeds.
- **CI** (`.github/workflows/tests.yml`) — the Python suite and the Loom's `node --test` now
  run on every push and pull request, so "all tests must pass before merging" is enforced
  rather than trusted. PySide6 and `pixeltable` are deliberately not installed in CI: no test
  imports either, and pulling in Qt just to sit unused is exactly the kind of CI flakiness
  (headless-display system deps) worth avoiding.
- **`CONTRIBUTING.md`** — setup, running the tests, the conventions that matter most to an
  outside contributor (`media_id` resolution, three-place catalog-schema changes, never
  committing `config.json`), PR expectations, and a private channel for security reports.
- **`READ_ONLY` config flag** — set `"READ_ONLY": true` in `config.json` to refuse every
  account-mutating call outright: submitting a generation, submitting a hand/face fix,
  deleting a task, or claiming a reward. Applies to the CLI *and* the web app, and
  **overrides `--confirm`/`--apply`/`--yes`** rather than just changing their default — those
  flags are for a run you already trust; `READ_ONLY` is for one you don't want to trust yet.
  Gated at the four functions every generate/edit/enhance/fix/delete/claim path funnels
  through (`submit_generation`, `submit_fixer`, `delete_task_gql`, `claim_reward`), so both
  surfaces are covered from one place. Documented on the new wiki **Trust & Safety** page,
  which also spells out precisely what this tool can and can't do to your account. Scoped to
  the PixAI account specifically — `--organize`/`--dedup` are untouched, since they're a
  different, already-covered trust concern that never touches the network.
- **The Loom's two-tier project export** — one "Export ▾" menu off `ProjectSwitcher`
  (`ExportMenu`, shared by classic and V2) replaces three flat buttons: Shot list (.txt),
  Lightweight backup (.json — project + local-only thumbs, referencing your own catalog by
  media id), and a new **Full bundle (.zip)** built server-side at `/api/loom/export-bundle` —
  the same JSON plus every media file the project actually references, so it's shareable with
  someone who doesn't share your catalog. A real PixAI media_id is globally issued, so the
  bundle keeps ids as-is end to end; a shot's video result is resolved via the catalog row's
  filename, since `find_files_for_media_id` only ever sees images by design (the same fallback
  `/api/loom/export` already uses). Restore accepts either file back and sniffs which one it
  got; a bundle's media is reconciled at `/api/loom/import-bundle` (`source='api'`, since it's
  real PixAI media just synced by transfer) — a media_id already resolvable on the receiving
  machine is skipped, so importing the same bundle twice is a no-op the second time.

### Docs
- **Documentation consolidated from 16 `docs/` files to 6, with the rest frozen.** A 42-agent audit
  verified 914 documentation claims against the code and found 158 false or stale — a quarter of them
  in one file, `ROADMAP_LOOM_ACHIEVEMENTS.md`, because it was written as an append-only journal where
  corrections piled up beside the errors they replaced. New **`docs/STATE.md`** is the now-only state
  doc (present tense; a fact that stops being true is deleted, not annotated) and replaces the roadmap
  as the post-compaction re-read target; **`docs/ART.md`** merges the four art docs into one that
  reconciles against the code and, where the code settles nothing (e.g. the banner master size), says
  so instead of inventing an answer. `REFINEMENTS.md` and `ROADMAP.md` fold into `STATE.md`;
  `DOC_MAP.md` is deleted (its artifact ledger moved to `STATE.md`, its source-of-truth hierarchy to
  `CLAUDE.md`). The roadmap, the four art docs, `MODEL_DECK`, and the three dated snapshots are frozen
  under **`docs/archive/`** with banners pointing at their live successors. `CLAUDE.md`'s checkpoint
  protocol now points at `STATE.md`. New **`tests/test_docs_dont_hardcode_counts.py`** fails the suite
  if a live doc hardcodes the test count — the fact that was wrong in every one of the 6+ files that
  stated it. Live docs now name the command (`python -m pytest`) instead.

### Added
- **Loom nav button hidden on phone** — `.head-nav .b-loom` now hides at the sub-480px breakpoint;
  the Loom is a dense multi-panel tool that isn't viable on a phone screen. Still visible on tablets.
- **Mobile filters are now a bottom sheet** — `.filters` slides up from the bottom at the sub-480px
  breakpoint with a backdrop scrim, reusing the existing `toggleFilters()`/`.open` mechanism unchanged.
- **First shared web component — `<mg-model-picker>`** (the Option-A cohesion pilot from
  `docs/SUITE_ARCHITECTURE_AUDIT.md`): a framework-neutral custom element (search + rich cover cards +
  hover preview; emits a `mg-pick` event) loaded as a plain global like `picker-core.js` — **no build
  step** — styled off the shared design tokens. The **Loom's Image tab** now mounts it (replacing a thin
  type-in model search), so the Loom and gallery move toward **one picker instead of two**. Standalone
  harness at `/static/mg-model-picker.html`. Owner-verified live. (Gallery adoption of the shared element
  is a later step.)
- **Per-criteria checklists on set masteries** — the Trophy Hall now shows *which* criterion is
  outstanding (✓/○) on the two closed-universe set achievements — **Full Toolbox** (edit / enhance /
  fix) and **Master of the Loom** (i2v / flf / r2v) — instead of a bare `2/3`. Open-ended
  distinct-counts (LoRAs, enhance workflows) stay count-only. Pure `achievement_criteria(sets)`
  threaded through `compute_achievements(…, sets=)` and rendered in the Hall tile; unit-tested.
- **Model-tuned-preset prefill in the Generate drawer** — negative prompt / steps / CFG now prefill
  from the selected base model's own tuned settings (`resolve_version_meta` already fetched this,
  it just wasn't used), with a reset-to-defaults control. Models with no tuned preset leave existing
  field values untouched.
- **Daily-claim button art** — the header's claim button now renders the owner's chosen crystal art
  (`branding/rewards/claim.png`) instead of a hardcoded gift emoji.
- **Thumbnail size slider in the shared gallery-picker** (`<mg-gallery-picker>`) — 90–240px, persisted
  to localStorage, shared by every picker instance app-wide (Loom Cast, both FrameSlots, etc.).
- **The Loom's Cast panel can add existing videos from the gallery** — the picker's Image/Video/All
  type filter (already built into `<mg-gallery-picker>` but unused there) is now enabled for Cast's
  "+ add from gallery," and a picked video is correctly tagged `kind:"video"`/`@video1...` (was
  forced to `kind:"image"` regardless of what was picked) — feeds `video_refs` for R2V/V2V shots.
- **A Loom shot can use an existing video as its finished clip, skipping generation entirely** — a
  "Use an existing video instead" button in the Video tab opens the (video-locked) gallery-picker and
  writes `resultMid`/`actualDur` directly, same shape a completed generation writes. `/api/loom/export`
  needed no changes — it was already agnostic about where a clip came from.
- **Bigger spinning-Nel mascot, head now spins** (header banner + activity tracker) — sizes bumped
  (22px→34px banner, 34px→48px tracker), and the chibi head itself rotates now (not just the loading
  ring around it), on a slower cycle than the ring for a layered look.
- **Mystery-tile art for masked feats** — hidden feat achievements now show the owner's cloaked-Nel
  artwork (`branding/mystery/secret_feat.png`) instead of a plain grayscale `❓`, in full color (not
  grayscaled — it's meant as an intentional tease, not a disabled state). Name/description stay masked.

### Fixed
- **The Loom no longer strands a shot when the tab closes mid-render.** `pollShot` held the task id
  only in an in-memory loop that died with the page, leaving the shot stuck "wip" forever while its
  finished clip landed orphaned in the gallery. The task id is now persisted on the card
  (`pendingTaskId`) and a resume effect re-attaches the poll on load, so the clip lands where it
  belongs. Cleared on completion/failure.
- **The Loom's frame handoff is now trim-aware.** "Inherit prev close" extracted the *untrimmed*
  clip's final frame, so a trimmed previous shot handed off a frame the cut never plays — the
  continuity chain contradicted the edit. It now seeks to the previous shot's `trimOut` before
  extracting (`extract_last_frame(..., at_seconds=)`), falling back to the true last frame when the
  shot isn't trimmed.
- **`--rebuild-thumbs` repairs are now actually visible in the browser** — thumbnails were served
  `Cache-Control: immutable, max-age=31536000` on the reasoning that they're "content-addressed", but
  they're keyed by **`media_id`, which is an identity, not a content hash**: `--rebuild-thumbs`
  regenerates the poster *in place at the same URL*. Any browser that had cached a broken video poster
  would not re-fetch it **for a year**, so running the rebuild job appeared to do nothing. Worse, the
  service worker was pure cache-first (`c.match(…).then(r => r || fetch(…))`) and never consults
  `Cache-Control` at all, pinning the stale poster for the life of the cache regardless of headers.
  Thumbnails now use **stale-while-revalidate** (cached bytes still paint instantly; a `no-cache`
  refetch updates behind them, so the rebuild lands on the next view) and the route drops `immutable`
  for a short `max-age` + ETag — which is also what bounds staleness for LAN viewers, who get no
  service worker at all (secure-context only). The cache name is bumped to **`pixai-img-v3`**, so every
  client currently holding a stale poster self-heals on activate without a hard refresh. Write-once
  originals (`/img/`, `/full/`) keep the immutable cache-first path. This is the same failure shape as
  the `v1` 404-poisoning bug, one status code over. Regression-tested end-to-end.
- **`__version__` bumped to `1.11.0`** — the `v1.11.0` tag has been on `loom-v2` since the Trophy Hall
  landed, but the version string was never bumped, so the code reported `1.10.0` under a `1.11.0` tag.
- **`delete_task_gql`'s guard no longer claims a setup gate that doesn't exist** — its error told a
  maintainer that a missing `DELETE_TASK_HASH` meant "deletion can't run without an explicit setup
  step". The hash ships with a working 64-char default, so the guard is unreachable under normal
  config and deletion fires fine; `--apply` plus the typed `delete` confirm are the only real gates.
  The message (and the module comment, which named `--confirm` — a *generation* flag) now say so.
- **Loom V2 toggle tooltip** no longer calls the layout "dockable" — `c0c7399` removed the dockable
  shell in favour of the fixed 4-region layout.
- **Panoramic images no longer get cropped to near-nothing in the main gallery grid** — `.card img`
  forced every thumbnail into a square via `object-fit:cover`; an extreme-aspect source (progress-bar
  and frame textures) now gets `object-fit:contain` instead (detected via `naturalWidth`/`naturalHeight`
  on load), showing the whole image letterboxed. Normal-aspect thumbnails are unaffected.
- **Loom save/load is now crash-safe** — every storyboard used to live in one `store.json` rewritten
  *non-atomically* on each edit, so a crash mid-save could corrupt **every** board at once. Each
  storyboard (and every `window.storage` key) is now its own file written atomically (tmp +
  `os.replace`); the legacy `store.json` migrates into per-key files on first touch and is preserved as
  `store.json.migrated`. The `/api/loom/*` contract is unchanged, so the React app needs no change.
  (Thumbnails-out-of-document + import-creates-new-project are follow-ups per `SUITE_ARCHITECTURE_AUDIT.md` §7.)
- **Canonical roster thresholds reconciled to shipped code** — `docs/achievements_roster_57.json`
  carried three stale thresholds (marathon 1→100, triggered 0→5, read-the-manual 0→1); aligned to
  what the code enforces so the canonical roster stops disagreeing with behavior.

### Fixed
- **Trophy Hall reformat reverted (`0a8da3a`, reverts `c877919`)** — the rewards-under-grid layout,
  toast-styled cards, and ladder depth-carousel landed visually wrong and are backed out; the Hall is
  back to the pre-reformat rail-rewards/plain-grid layout. Clean revert (86 deletions / 6 insertions,
  the exact inverse of the original diff) — every commit between the two touched only docs, so no
  conflicts. 478 tests still pass. **This time actually confirmed with a real rendered screenshot**
  (Summary + All tabs, rewards back in the rail, no carousel), not just computed-style assertions —
  see `docs/archive/ROADMAP_LOOM_ACHIEVEMENTS_2026-07-16.md` §2b (frozen 2026-07-16; live state is
  `docs/STATE.md`). A ground-truth audit (10-agent read-only pass over the
  whole repo) preceded this: full doc-vs-code reconciliation, a CLI command map, a PySide6 removal
  recommendation, and a Loom consolidation verdict — see that section for the follow-up plan.

### Added — 2026-07-16
- **Loom state-layer consolidated via a composed-hooks extraction** (`ee4b33a`) — a decisive
  probe found the state layer (project store, shot mutations, generation pipeline, export
  pipeline) separates cleanly into `loom/src/loom-mutations.js` + four hooks *without* first
  merging classic Loom and V2's render trees, which reduces rather than confirms the case for
  a full render-tree rebuild. **The full rebuild is parked, not cancelled** — undecided,
  awaiting its own probe if ever revisited.
- **Loom V2 shell redesign shipped for real** (`c0c7399`) — the six free-floating dockable
  panels are gone; replaced with a fixed 4-region layout: a tabbed Cast & Assets / Footage
  card (left), the Acts & Shots board (center), a Generate drawer (right), and a fixed
  Timeline drawer (top, 3-state drag: hidden/slim/full). Legend became per-field on-demand
  "+terms" popovers instead of a persistent panel.
- **Draft generation** — the Generate drawer (Image/Edit/Reference/Video) now works with no
  shot selected, mirroring the main gallery's own drawer. A `draftCard` stands in for the
  selected shot everywhere the tabs read/write, keyed into the same generation-state dicts
  real shots already use. Results route into a chosen shot (Image/Edit/Reference) or attach
  to one (Video) via a small picker; cast routing needs no target since it writes to the
  project's asset pool directly. Live-tested end-to-end with two real generations.
- **Real playback controls in both Loom layouts** — V2's Timeline/Deep-Focus preview
  (`ShotPreview`) gained a play/pause button (honors the trim range); classic Loom's
  sequence player had a missing `muted` attribute fixed (could silently block autoplay).
  Scrub/fast-forward/rewind/split/crop were banked as a modest follow-on set at the time —
  since shipped; see the "ShotPreview editing toolset" entry above.
- **Gallery search now matches task id / media id**, not just prompt text — paste an id
  from PixAI's site (or `--dump-params` output) to jump straight to that generation.
- **Play sequence wired into V2** — the first item off the V1→V2 convergence punch list.
  Reuses the exact same `playSequence()`/`SequencePlayer` classic Loom already has (no new
  logic); a "▶▶ Play" button in V2's top banner, disabled until a shot has a result.

### Fixed — 2026-07-16
- **Health page vs. Panel page image counts disagreed** (43,829 vs. 31,064) — the Health
  page's disk scan counted `_deleted/` (recoverable trash from anything ever deleted through
  the gallery UI) and `branding/` (UI art assets) as "images on disk"; both are now excluded,
  matching the Panel's already-correct catalog-row count.
- **A real, pre-existing bug: the sequence player's close/next silently did nothing once
  playing.** Found live while wiring Play sequence into V2 (above) — `useExportPipeline`'s
  `onClose` called `setSeq` directly, but the hook never actually exposed `setSeq` (only
  `seq`), so every close click threw a silent `ReferenceError`. Predates this session
  entirely. Fixed by exposing a proper `closeSequence()` closer instead.
- **Three rounds of Loom V2 shell bugs**, found and fixed same day as the shell shipped:
  side-panel scroll clipping + Detailed cast rows made genuinely editable again; Detailed
  Cast & Assets widened 2× + Simple-density cards no longer look clickable when nothing's
  selected; the Generate drawer's frame-slot header didn't fit its own drawer width (widened
  the drawer, narrowed the `@tag` input specifically there).
- **Loom's own page scrollbar fought the shell's internal panel scrolling** — the V2 overlay
  is fixed and never visibly moves, but classic Loom's page underneath (a normal tall
  document) kept a live scrollbar; a wheel scroll not captured by an internal panel bubbled
  up and scrolled that instead. Body scroll is now locked while the V2 overlay is open.

### Fixed — 2026-07-17
- **Loom export no longer silently discards audio.** `/api/loom/export`'s ffmpeg concat hardcoded
  `a=0` (video-only) since the export feature shipped — a shot generated with "Generate audio" on
  would have that audio thrown away the moment it was stitched into a multi-shot export. New
  `probe_has_audio`/`probe_duration` (ffprobe-backed, fail-soft) detect real audio per segment;
  segments with audio trim+concat it, segments without get matching-duration synthesized silence
  (`anullsrc`) so the track can't desync across a boundary; both `[vout]`/`[aout]` are mapped with
  an AAC codec. Real-ffmpeg verified (not just mocked): a genuine two-clip export (one with audio,
  one silent) produced an mp4 with both a video and an audio stream, each exactly 3.000000s, no
  drift. A genuine ffmpeg-pad-ordering bug (concat needs `[v0][a0][v1][a1]...` interleaved per
  segment, not grouped by type) survived the mocked test suite entirely and was only caught by
  actually running ffmpeg — a dedicated assertion now pins the correct interleaving so it can't
  silently return. Scoped as a correctness fix only; the tabled audio-lane/multi-track-timeline
  feature remains explicitly out of scope (a scene-builder, not an NLE).

### Added — 2026-07-17
- **The Loom V2 shell can Export.** Item 1 of the V1→V2 convergence punch list — `exportCut`
  (from `useExportPipeline`) is now threaded into `LoomV2`'s props, with an Export button beside
  V2's existing Play button (same disabled-until-a-shot-has-a-result gate). No restructuring
  needed: the export-status overlay already renders above the V2 shell automatically (`.sb-seq`
  z-index 500 vs `.lv-overlay` 400) — the identical trick that already let Play's
  `SequencePlayer` work in V2 unchanged. Verified via `npm run build` (clean esbuild bundle,
  real JSX-syntax check) and `node --test` (66/66, unaffected); full Python suite unaffected
  (JS-only change).
- **The Loom V2 shell can batch-generate.** Next punch-list item — `batching`/`batchGenerate`
  (already returned by `useGenerationPipeline` for classic's own header) are now threaded into
  `LoomV2`'s props too, with a "Generate all" button matching classic's exactly: prices every
  not-done shot first so the confirm shows real cost + free-card coverage before anything
  spends, disabled while a batch is running or the board is empty. Same verification as Export
  (clean esbuild build, `node --test` 66/66, full Python suite unaffected). Classic Loom now
  retires once the one remaining punch-list item (per-shot "other references") lands in V2.
- **Deep Focus can add/edit/remove a shot's other references.** The last item on the V1→V2
  convergence punch list — `addRef`/`setRef`/`delRef` (from `useShotMutations`) are threaded
  into `LoomV2`, and Deep Focus's modal gains the same "Other references & @tags" section
  classic Loom's `CardEditor` has, reusing its exact markup/CSS verbatim (`FrameSlot` already
  proved `.sb-*` classes render correctly inside Deep Focus). Owner call (2026-07-17): lands in
  Deep Focus rather than the Video tab, since it's already the "everything about this one shot"
  view; may end up in both once usage shows whether refs are wanted without leaving the board.
  Verified via `npm run build` (clean esbuild bundle) and `node --test` (66/66); full Python
  suite unaffected (505 passing, JS-only change). The item that originally gated classic Loom's
  retirement has now landed in V2 — whether to actually retire classic Loom, or promote the two
  remaining smaller gaps to retirement-blockers first, is an open owner call.
- **The Loom V2 shell surfaces Export shot-list, Backup, Restore, and Import Collection.** Item 2
  of the punch list the owner promoted to retirement-blockers — `exportAll`/`exportJSON`
  (`useExportPipeline`) and `importJSON` (`useProjectStore`) are now threaded into `LoomV2`'s
  props, with three new buttons in V2's top strip ("Shot list (.txt)", "Backup (.json)", and a
  file-input-in-a-label "Restore") plus an "⇄ Import collection" button beside V2's existing
  "+ add from gallery" in the Cast panel (opens the same `ImportCollection` modal classic uses).
  Caught and fixed before shipping: `.lv-top button{...}`'s CSS only targeted `<button>`, so the
  new `<label>`-wrapped Restore control would have rendered unstyled — broadened to
  `.lv-top button,.lv-top label`. `ImportCollection`'s `.sb-pick-ov` overlay shares V2's overlay
  z-index (400, not a clean 500-over-400 tier like Export's `.sb-seq`) and relies on DOM paint
  order instead — flagged for a live check, not assumed safe. Verified via `npm run build` (clean
  esbuild bundle) and `node --test` (66/66); full Python suite unaffected (JS-only change).
- **Deep Focus gains audio cue, notes, the discreet toggle, manual status-cycle, and "Copy
  shot."** Item 1 of the same punch list — the five smaller classic-only fields all live on the
  card object and now render inside Deep Focus, ported verbatim from classic's `CardEditor`/
  `CardView` markup: a Music/audio-cue field with the `AUDIO_PALETTE` quick-pick chips, a Notes
  textarea, a blur-preview checkbox, the `.sb-tick` status button (todo → wip → done) in the
  header, and a "Copy shot" button wired to the existing `copyShot` (now threaded into `LoomV2`'s
  props; Deep Focus's own `live` var already matches the `{c,a,ai,ci,code}` shape it expects, so
  no adapter was needed). Deep Focus is an IIFE inside a conditional render, not a component, so
  the new `palFor`-equivalent local state (`dfPalFor`) had to be lifted to `LoomV2`'s own top
  level rather than declared with `useState` inside it — the same rule that already governs
  `deepFocus`/`setDeepFocus` itself. Verified via `npm run build` (clean esbuild bundle) and
  `node --test` (66/66); full Python suite green (509 passing). **Both items the owner promoted
  to retirement-blockers on 2026-07-17 are now landed — V2 has full feature parity with classic
  Loom. Retiring classic Loom itself is a separate step, open for the owner to call.**

### Fixed
- **Two concurrency bugs in the new web-based account bootstrap + Users tab, found by two
  independent adversarial reviews** (2026-07-19, `pixai_gallery_backup.py`, `pixai_gallery.py`,
  `tests/test_web_auth.py`, `tests/test_panel_users.py`). Both reviews were verified against the
  current code before anything was changed; three of their five combined confirmed-real findings
  needed a fix, two were confirmed clean (no change).
  - **Lost-update race in account create/remove** (both reviews, same root cause): `_load_config()`
    → mutate → `_save_config()` in `add_or_update_web_user()`/`remove_web_user()` was unlocked, so
    two threads (`app.run(..., threaded=True)`) could each read the pre-write state and the later
    write would silently clobber the earlier one — reproduced live as two concurrent local
    bootstrap POSTs for *different* usernames that both returned a 302 "success" redirect while
    only one username actually landed in `AUTH_USERS`. Fixed with a new module-level
    `_accounts_lock` (`pixai_gallery_backup.py`) serializing every read-modify-write of
    `AUTH_USERS`. New regression test
    `test_web_auth.py::test_concurrent_add_or_update_web_user_does_not_lose_either_account` forces
    the interleaving with a real delay + real threads (not just sequential calls) and confirms
    both accounts now survive.
  - **TOCTOU on "can't remove the last account"** (Users-tab review, Finding 2): `/api/users/remove`
    read `list_web_users()` as a snapshot, then separately called `remove_web_user()` to mutate —
    with exactly 2 accounts, two concurrent removes of two *different* usernames could each pass
    the "more than one left" check off their own stale snapshot and both proceed, leaving
    `AUTH_USERS` **empty** (reproduced live against the real Flask route). Fixed with new atomic
    helpers that do the check-and-mutate under one `_accounts_lock` acquisition:
    `remove_web_user_guarded()` (returns `"removed"`/`"not_found"`/`"last_account"`, replacing
    `/api/users/remove`'s separate read+write) and `add_web_user_if_new()` (closes the same class
    of race for `/api/users/add`'s duplicate-username check, hardening it proactively — not itself
    a reviewer-confirmed finding). New regression test
    `test_panel_users.py::test_concurrent_remove_of_two_different_accounts_cannot_empty_the_list`
    confirms at least one account always survives and exactly one of the two concurrent removes is
    turned away.
  - **`/login`'s `mode=create` bypassed the IP lockout and CSRF checks** (Bootstrap-race review,
    Finding 2): the `wants_create and not bootstrap_mode` guard used to run *ahead of* both
    `_login_seconds_locked()` and the CSRF compare, so a hand-crafted `mode=create` POST from an
    already-locked-out address (or with a forged CSRF token) sailed through with neither check
    applied — reproduced live. Reordered so the lockout check and the CSRF check run first,
    identically to an ordinary credential POST; the create/bootstrap-mode gate still runs before
    any account is ever created, just after those two, not before them. New regression tests
    `test_lockout_applies_uniformly_to_mode_create_requests` and
    `test_csrf_applies_uniformly_to_mode_create_requests`.
  - **`_is_local_request()` fail-open on missing/empty `remote_addr`** (Bootstrap-race review,
    Finding 3; pre-existing, not introduced by the bootstrap diff, but now backs the bootstrap
    gate too): `ra in ("127.0.0.1", "::1", "localhost", "")` treated an empty/`None` remote address
    as local. Safe under this app's actual deployment (Werkzeug's dev server always populates a
    real TCP peer address), but a fail-open default in a function multiple security boundaries now
    depend on — changed to fail closed (dropped the trailing `""`). New regression test
    `test_bootstrap_treats_empty_or_missing_remote_addr_as_not_local`.
  - **Confirmed NOT bugs (no change made)**: the Users-tab review's CSRF-bypass question (clean —
    `_check_panel_csrf()` is independent of auth and a cross-site form can't send the required
    `application/json` body at all); its self-removal-mid-session question (clean —
    `_is_authorized_request()` re-validates against `config.json` every request, so a graceful
    401/redirect follows, never a crash); its password-hash-leak question (clean —
    `list_web_users()` never even reads `password_hash` off the config dicts); and its
    Maintenance-tab-content question (clean — confirmed via `git diff` that the tab-bar refactor
    added only two wrapper `<div>`s around the untouched section). The Bootstrap-race review's
    "critical property" verdict (a LAN device cannot create the first account, via the form or a
    direct POST) was independently re-verified against the current code and stands confirmed.
  Full suite green: **674 passed** (`python -m pytest -q`; the 5 new regression tests above, on top
  of the reviews' reported 669).

## [1.11.0] — 2026-07-13 — Achievement flair & the Trophy Hall

_On `loom-v2`, past the `v1.10.0` tag. The 57-achievement system plus its flair layer (toast frames,
gift box, rung-scaled points) and the maximized-overlay Trophy Hall. `loom-v2` remains unmerged to
`master`; this tag sits on `loom-v2`. See git history for the full list._

### Added
- **The Trophy Hall** — the achievement window is now a **maximized full-screen overlay** (not a
  separate page): the existing modal grows to fill the screen — banner header, **Summary / All /
  Statistics** tabs, a **Summary landing** (Recent Achievements from earn-dates + Progress Overview
  bars), the bucket grid as collapsible tile sections, live **search**, and a **right rail**
  (category nav · Within Reach · Rewards Earned · mascot alcove). Instant open, gallery stays behind
  it, ESC out, animates from the 🏆 button; scoped so the contest/art modals are untouched; mobile
  stacks the rail under the grid.
- **Earn-date persistence + badge thumb-cache** (Hall infra) — `achievements.json` records
  `earned_at` per achievement (backfills existing earns; never leaks a hidden feat's date), and the
  57 badge masters (~300 MB) are served as lazy ~256 px thumbs via `/badge-thumb/<id>.png` so a
  full Hall doesn't pull the masters.
- **Tier flair frames on the unlock toast** — legendary + feat achievements now fire their unlock
  moment wrapped in an ornate **9-slice `border-image` frame** (LEG6 gold+emerald / FEAT13 ruby)
  that grows with the toast so the roast never overflows; common/rare/epic stay clean chrome (epic
  is a one-line flip). The reward ribbon's placeholder emoji is replaced by the **gift-box icon**.
  Frame + gift assets are machine-local in `branding/frames/` + `branding/rewards/`.
- **Achievement points** — every achievement carries a **rung-scaled score** (`tier base +
  5×(rung−1)`; common 5 / rare 10 / epic 25 / legendary 50; **feats 0**, so the total never hints
  at a hidden feat). Points show on the unlock toast, on each grid tile, and as a Warband-style
  running total in the panel header. Rung is *derived* from the roster (ladder families grouped by
  metric, ordered by threshold), reproducing the Archive ladder exactly (5 / 15 / 35 / 65 / 70);
  **960 points possible**.
- **The full 57-achievement roster is live** — the achievement system grew from 11 to all **57**
  designed achievements (29 ladder rungs across 10 tracks · 9 milestones · 8 masteries · 11 hidden
  **feats**), generated verbatim from the canonical `docs/achievements_roster_57.json` with every
  achievement carrying its `roast` (and an unlockable uncensored variant). The panel groups them
  into **Evolution Ladders / Milestones / Masteries / Feats of the Athenaeum** sections; earned
  cards show their roast; **The Great Library** is flagged as a banner reward.
- **The telemetry layer** — the persisted counters behind every non-catalog metric
  (`out_dir/telemetry.json`: counters / maxima / sets / flags / distinct-days, lock-guarded and
  fail-soft everywhere). ~15 call sites now report in: edits, enhances (+ distinct workflows),
  fixes, uploads, LoRA use (first / stacked / distinct), video modes, Loom shots, "more like this",
  claims, skin + branding changes, `--organize`, `--dedup` culls, `--task-id` recoveries, free-card
  applies, day-of-use tracking, and new catalog SQL for `local_gens` / `gens_in_a_day` /
  `distinct_keywords`. Feat events ride a new `/api/ach-event` beacon (Konami egg, the in-Loom
  manual, narrator pokes) plus state sweeps (custom branding, the eclipse animation) and a
  new-download **Time Capsule** check.
- **Hidden feats + the narrator** — feats serve masked (`???`) until earned and the whole feats
  section stays cloaked until the first one lands; **poke the narrator** (the chibi in the
  Achievements header) until it snaps to earn *Triggered* and reveal the **Unleash the AI**
  toggle that swaps every roast to its uncensored variant.
- **Per-achievement badge + mascot art** — the 57 voted badges/mascots are served from
  `branding/badges/<id>.png` and `branding/mascots/ach/<id>.png`; the unlock moment now presents
  with **that achievement's own mascot** (falling back to the tier chibi), and the celebration
  queue/summary-toast handles the first-load burst.
- **The unlock moment IS the locked toast v2 design** (artifact `335ef4e7`): the badge medallion
  **sweeps right-to-left into a cap** with a ring pulse and glow-ding, the **mascot leaps from the
  toast's top edge** over a tier glow, "New Achievement" eyebrow, the **roast rides a read-along
  shimmer**, and a metallic rarity pill with a sheen — rarity-scaled hold + flash for
  legendary/feat, click to dismiss, queued for bursts. The >3-unlock summary uses the same frame
  (trophy in the well). Feat tier inside the toast = gunmetal band/pill + ruby glow + ruby inner
  rim on the cap.

### Fixed
- **Poster-less videos finally get thumbnails** — when PixAI supplied no poster frame, a video's
  gallery tile stayed blank forever. `build_thumbnails` now includes videos whose thumb is missing
  and extracts an early frame locally via ffmpeg (`make_video_thumbnail`, fail-soft, same
  Pillow pipeline as image thumbs so quality stays uniform). Existing video posters are never
  overwritten (they came from the network and can't be regenerated). `--sync`'s thumbnail step
  picks these up automatically.

### Added
- **`--rebuild-thumbs`** (+ Panel job "Rebuild ALL thumbnails") — re-renders every image
  thumbnail from its original at today's size/quality settings (kills years of quality drift),
  sweeps orphaned thumbs whose media left the catalog, and ffmpeg-extracts posters for
  poster-less videos. Overwrites in place, so the gallery never goes blank mid-run.

### Changed
- **Feat tier restyle: gunmetal + ruby** — the feat tier's pink is gone; feats now wear a
  **gunmetal band** (`#8a93a2`) with a **ruby glow + ruby inner rim** (`#e0355e`) across the panel
  cards, section header, tier pill, unlock moment (ruby-tinted scrim, ruby/gunmetal confetti), and
  a new feat chime. New `--gunmetal` / `--ruby` design tokens.
- **Achievement quick-wins batch** — drop-in **SFX** (`branding/sfx/ach_<tier>.ogg` plays if
  present, synth chime otherwise) · legendary/feat **fanfare restored** (screen-level star rain +
  confetti, gold vs ruby-gunmetal) · **adaptive mascot seating** (each chibi's opaque artwork is
  measured and seated so ~75% rises above the toast band regardless of source-image padding) ·
  **reward ribbon** on unlock toasts (🎁 skin / ⚑ banner) · **Skins moved to the Control Panel**
  beside Branding (swatch grid, click-to-apply; the achievements modal links there).
- **The Loom V2** — a dockable-panel storyboard workspace (Acts & Shots board, runtime reel,
  Cast / Legend / Footage panels, timeline preview, and per-shot Generate tabs with
  continuity / camera / lighting), behind a **non-breaking "V2 layout" toggle** wrapped in an error
  boundary that falls back to the classic Loom. The **Video** and **Image** generate tabs are
  live — the Image tab generates a reference still for the selected shot (model picker +
  shot-seeded prompt over `/api/generate`, free-card aware) and **routes the result into the
  shot's open/close frame or cast**, so an in-Loom gen directly feeds the video render.
- **Loom Generate: Edit + Reference tabs** — all four Generate tabs are now live. **Edit**
  instruct-edits the shot's open frame (`/api/edit`, Edit Pro) and **Reference** composes a new
  still from the cast's `@image` members (Reference Pro, up to 10 refs); both poll and **route the
  result into the shot** exactly like the Image tab, share the balance line + friendly errors, and
  ride a shared `runGen`/`routeGen` so the proven Image path stays untouched.
- **Multiple storyboards in the Loom** — the Loom is no longer single-project. Each storyboard
  is saved under its own key in the existing server-side store (`storyboard:v2:proj:<id>`), with
  a **switcher in both the classic and V2 headers** (New · Open · Duplicate · Delete,
  close-on-outside-click; Rename via the name field) and an active-project pointer. Your existing project is **migrated in automatically** as the first
  storyboard on load; the legacy single-key project is preserved untouched as a backup. Verified
  end-to-end on a copy of real store data (migrate → new → switch, content intact).
- **Loom Generate: inline balance + friendly errors** — the Generate panel shows your live credit +
  card balance (`/api/account`) with a "+N claimable" hint, and gen failures now map the raw PixAI
  GraphQL error (e.g. `INSUFFICIENT_BALANCE`) to a human message ("out of balance — claim daily
  rewards or pick a card-covered model") instead of dumping the raw payload. Task-level failures
  now surface PixAI's own reason (the endpoint returns it as `status`, which the poll previously
  dropped) — content-moderation blocks read as a clear message instead of a bare "failed".
- **Achievements art & moments** — 11 achievement-badge prompts + the Loom mark, a
  mascot-per-state activity tracker, a rarity-scaled "Nel presents" unlock pop with real badge art,
  a spinning-Nel generation loader, and a Konami-code Starfall easter egg.
- **Recover a task by ID** — a Control Panel action to import any generation/edit into the catalog
  by task id, with an "already in your gallery" check + jump link.
- **Edit card** — multi-image references (Edit Pro 4 / Reference Pro 10) and
  capability-clamped resolution/quality/aspect (fixes the 4K-on-unsupported-model bug).
- **Economy surface** — distinct credits/cards chip, claimable badge, and credit expiry/cliff warnings.
- **Mobile portrait pass** — responsive layout ≤480px across header, grid, filters, drawer, lightbox.

### Changed
- **`--sync` is now the full one-shot refresh** — pull + full-meta → fix-models → backfill →
  **build missing thumbnails → reconcile cloud-deletes**, all idempotent (previously stopped after
  backfill). Reconcile is advisory and caught with a deliberately **broad `except Exception`** so a
  transient network error during its feed scan can't sink an otherwise-successful backup. Guarded by
  `tests/test_sync.py`; documented in `CLAUDE.md → "The one-shot sync (--sync)"`.

### Docs
- **State of the Suite** — code-verified status assessment (`docs/STATE_OF_THE_SUITE_2026-07-10.md`
  + `docs/state-of-suite.html`); corrected the stale `docs/REFINEMENTS.md` "Next up" list; started
  this changelog file.

## [1.10.0] - 2026-07-05 — Consolidation release
- **Live event push** — `--watch` / `--watch-backup` (graphql-transport-ws `personalEvents`,
  auto-collect finishing gens) **plus an in-server live-mirror watcher** (gens land locally the
  instant they finish; no separate CLI process).
- **Control Panel** — live progress bar (MGPROG protocol), Stop-this-job cancel, hourly scheduler.
- **Server control** — Stop/Restart from the browser via the `Serve Gallery.pyw` supervisor
  (exit-42 relaunch, single-instance guard, `serve.txt` args, `serve.log`).
- **Branding system** — choosable banner mark + 15 animations, frosted-pill nav, Desktop launcher `.lnk`.
- **Community** — contests (`--contests` / `/api/contests`), achievements + earnable skins,
  "Your Art" views + account entitlements.
- **Fixes** — batch under-capture (saved the grid, not the images), catalog-stats thumbnail
  double-count, `USER_ID` auto-resolve in `--sync-artworks`; CSV export is a real browser download;
  balance chip caches last-known credits.

## [1.9.1] - 2026-07-03
- **Jobs tray** (tasks survive drawer close), header **balance chip**, **Suggest-prompt** button,
  **prompt snippets/favorites**, and **printing** (print-friendly detail view + contact sheets).
- Sanitized reverse-engineering mechanism detail out of the public docs/wiki.

## [1.9.0] - 2026-07-03 — The web creation suite
- **Generate / Edit / Video drawer** — dockable to any screen edge, model/LoRA flyout with hover
  preview cards, LoRAs as attachments (not model overrides), Tag Suggestions in every prompt box.
- **Picker** — 900px modal browsing the whole catalog (infinite scroll), Collection/Source/Rating/Sort
  filters, upload, copy-prompt-on-pick.
- **Gallery → create bridges** — lightbox actions, right-click menu, multi-select → Video;
  Edit tab Edit | Enhance | Fix sub-tabs; eclipse-moon status spinner; in-app quick guide + full manual.

## [1.8.3] - 2026-07-03 — Claimable rewards
- `--claims` / `--claim` via `/v2/claim` (daily credits / agent stamina; read-only list, gated claim).

## [1.8.2] - 2026-07-03 — Image-to-prompt
- `--suggest-prompt` via `/v2/tag/suggest-prompt` (image → Danbooru-style tags + description; free).

## [1.8.1] - 2026-07-03 — Real credit cost in previews
- `price_task` via `/v2/task-price` — a generation's real credit cost, computed without creating it.

## [1.8.0] - 2026-07-03 — Full create suite + free-card auto-apply
- The complete create surface on one `createGenerationTask`: `--generate`, `--edit-image`,
  `--generate-video` (i2vPro), `--reference-video` (multi image/video/audio), `--enhance`
  (panelplugin workflows: face-fix / upscale / bg-remove + art filters), `--upload`.
- Free **"kaisuuken" cards auto-apply** on `--confirm` via the `/v2/kaisuuken` REST surface;
  `--dump-params` banks a submit shape with no browser; server-authoritative cost (`paidCredit`).
- GUI Video / Ref Video / Edit tabs; gallery detail → creation bridges. Cross-machine protocol +
  pinned line endings (`.gitattributes`).

_(No v1.7.x — the series jumped from 1.6.0 to 1.8.0.)_

## [1.6.0] - 2026-06-28 — Curation + one-key setup
- **Collections** (images + videos), **select-mode + drag-paint** multi-select, scroll/selection
  persistence, detail-page keyboard nav.
- **One-key setup** — `config.json` is just `PIXAI_API_KEY`; `USER_ID` auto-resolves and the
  persisted-query hashes ship as built-in defaults.
- Fixed a JS error that killed the entire gallery script; added a `node --check` regression guard.

## [1.5.0] - 2026-06-27 — Moonglade Athenaeum 🌙
- **Rebrand** from "PixAI Gallery Backup" to a full local PixAI client (back up · browse · generate · curate).
- **`gql_adhoc()`** ad-hoc GraphQL POST — most ops need no persisted-hash capture; read-only `--account` dashboard.
- **Image generation** (`--generate` / Generate tab) with model + LoRA pickers, quality mode,
  priority, prompt-helper, aspect presets, `--task-id` recovery.
- **Manage & curate** — delete-from-PixAI (cloud + local), `--reconcile-deleted`, `--import-local`;
  Organize rebuilt into reversible `YYYY-MM/` month folders.

## [1.4.4] - 2026-06-24 — Media-type filter (All / Images / Videos).
## [1.4.3] - 2026-06-24 — 768px thumbnails (q90) for high-DPI displays.
## [1.4.2] - 2026-06-24 — Sharper thumbnails (512px / q90).
## [1.4.1] - 2026-06-24 — Video gallery fixes — posters generated during `--sync-videos`; click-to-play.
## [1.4.0] - 2026-06-23 — Image-to-video backup — `--sync-videos` downloads the real mp4 + gallery playback (`/video-file/<id>`, range support).
## [1.3.2] - 2026-06-23 — Fuller metadata (negative prompt, clip-skip), `/duplicates` review page, inline + bulk prompt editing.
## [1.3.1] - 2026-06-22 — Parallel workers (`--workers N`, default 4) for the batch jobs, not just downloads.
## [1.3.0] - 2026-06-22 — API-key auth, `--sync-artworks` (published metadata), LoRA tracking, dashboards, mobile/PWA, animated-artwork backup.
## [1.2.0] - 2026-06-22 — Duplicate audit/dedup (`--audit` / `--dedup` / `--verify-dupes`), gallery overhaul, parallel downloads + instant O(1) resume + incremental `--update`.
## [1.1.0] - 2026-06-13 — SQLite catalog (`catalog.db`, auto-migrate from CSV, `--export-csv`); SQL-backed gallery (~20× faster on large libraries); batch filter.
## [1.0.0] - 2026-06-13 — Initial release — bulk-download your own PixAI generations (backward pagination, media resolution, resume-by-media-id, catalog + prompt sidecar).

[Unreleased]: https://github.com/Nelnamara/moonglade-athenaeum/compare/v1.10.0...HEAD

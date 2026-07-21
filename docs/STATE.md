# STATE — Moonglade Athenaeum

> ### How to write in this file
>
> **This file describes only what is true right now.** Present tense. When something stops
> being true, **delete the line**. Never strike it through, never mark it SUPERSEDED, never
> write "was X, now Y", never append a correction beside the thing it corrects. There is no
> "shipped recently" or "landed on <date>" section — a list of recent changes only ever grows,
> and that append-only growth is the exact failure this file exists to avoid.
>
> - What shipped → `CHANGELOG.md`. Not here.
> - How a decision was reached → git history + the frozen copies in `docs/archive/`. Not here.
> - How the system works → `docs/architecture.md`. Not here.
> - Rules and standards → `CLAUDE.md`. Not here.
> - **Never write a number a command can answer** — test counts, commits-ahead, version
>   strings. Name the command instead.
> - A commit SHA is fine as an *identifier* riding a present-tense fact ("Play runs the
>   sequence, 768aecf") — never as the subject of a change-story. Prefer symbol names over
>   line numbers.
> - Absolute dates only (`2026-07-17`), never "today" or "last week".
> - Rationale for every rule above: `CLAUDE.md` and the frozen copies in `docs/archive/`.

---

## Right now

Moonglade Athenaeum is a Python/Flask client for PixAI.art: it backs up the owner's own AI
generations, serves a local searchable web gallery, generates images and videos through
PixAI's API, and curates the archive. Two surfaces are current — the CLI
(`pixai_gallery_backup.py`) and the web app (`pixai_gallery.py`); the PySide6 desktop GUI is
legacy and folding into the web app. All work happens on the `loom-v2` branch; `master` has no
commits that aren't already in `loom-v2`. Merging `loom-v2` → `master` with `--no-ff` is the
single act that carries the Loom V2 set, the achievement system, `CHANGELOG.md` and `LICENSE`
to master. **The Loom is a single storyboard surface** — the V2 shell. Classic V1 (its render
tree, the `v2` toggle, and the `CardView`/`CardEditor` components) was retired 2026-07-17; `/loom`
opens straight into the V2 shell with no layout switch. The repo is public and has real external
users.

**Numbers live in commands, not in this file:**

| Question | Command |
|---|---|
| Test count | `python -m pytest` from the repo root (add `--ignore=tests/test_similar.py` when pixeltable isn't installed); the Loom's pure-logic suite is `node --test` from `loom/` |
| Current version | `grep __version__ pixai_gallery_backup.py` |
| How far `loom-v2` leads `master` | `git rev-list --count origin/master..origin/loom-v2` |
| Which tags have a GitHub Release | `gh release list` against `git tag` |
| Whether the C: repo and the D: run-copy agree | `git log -1` in each |

---

## The Loom

- V2 is the live storyboard surface: a fixed four-region shell — top strip, left card, center
  board, right Generate drawer (`.lv-top`, `.lv-side`, `.lv-board`). Nothing in V2 is
  draggable, resizable, or x/y/w/h-persisted (c0c7399).
- **Mode and Continuity's "First→Last" chip are coupled** (`setShotMode`/`setShotConnect`,
  loom-mutations.js) — a shot can no longer show Continuity "First→Last" while Mode is
  something other than `FLF`. Only `mode==="FLF"` ever made the close frame reach the real
  generation (`shotPayload`, `build_shot_video_params`); left uncoupled this silently dropped
  the close frame with no error, confirmed in a real production generation. A known defect
  since the original Loom audit, never tracked past the old roadmap doc — fixed 2026-07-18.
- **Video shots can request generated audio.** A Generate-audio checkbox + language chips
  (English/Japanese/Chinese/Korean/**SE only** — PixAI's real sound-effects-only value, not
  silence) sit under Duration in the Generate drawer's Video tab, threaded through
  `shotPayload` → `/api/loom/generate` and `/api/price`. Reverse-engineered in
  `private/GENERATOR_SURFACE.md` well before this; the gap was purely a missing control — the
  server already accepted `generate_audio`/`audio_language`. The main gallery's own Video tab
  had the same control already (checkbox + a 4-language `#video-lang` select) but was missing
  the SE-only option; both surfaces now expose the same five choices.
- The top strip's **Play** button runs the sequence, disabled until a shot has a result
  (768aecf).
- The top strip's **Export** button trims + stitches every finished shot into one mp4
  (`exportCut`), disabled until a shot has a result. The export-status overlay renders above the
  shell automatically (`.sb-seq` z-index 500 vs `.lv-overlay` 400), same as Play's
  `SequencePlayer`.
- The top strip's **Generate all** button batches every not-yet-done, non-"wip" shot
  (`batchGenerate`), pricing every shot first so the confirm shows real cost + free-card
  coverage before anything spends (fails CLOSED on a bad price check, same guardrail as the
  single-shot path) and flags any shot with no real prompt text yet by code. Disabled while a
  batch is running or the board is empty. It is a genuinely SEPARATE submission path from
  `<mg-generate-drawer>`'s own per-shot Generate button — both hit `/api/loom/generate`, and
  `batchGenerate`/`generateShot` always recompute the prompt fresh from the card's own fields
  (`shotPayload`/`shotText`), never reading the drawer's live DOM directly — but its onClick
  flushes and locally patches a pending drawer hand-edit into a promptOverride first, so a
  shot mid-edit still generates with the latest text regardless of React's render timing (see
  the prompt-override bullet below). A live-updating `batchTally` (submitted/done/failed,
  scoped to that run's own card ids via `Set` membership, written exclusively through React's
  functional setState form to survive concurrent submit-loop + poll-loop writes) drives a
  status banner while shots are still rendering, since the submit loop itself finishes long
  before the actual renders do.
- **Standing cost-to-finish estimate:** a pill next to "Generate all (N)" shows a live
  free/paid/credits/unpriced tally over every not-done shot, kept warm by a per-shot price
  cache (`priceCache`/`ensurePriced`) fingerprinted on only the fields that actually affect
  `/api/price` (mode/images/video_refs/duration/quality/audio — never prompt/camera/lighting,
  verified against the server's own price allowlist), refreshed on a 600ms board-debounce plus
  click-to-force. Deliberately NOT shared with `batchGenerate`'s own one-shot, must-be-fresh
  pricing pass right before the irreversible confirm — different staleness contracts, same
  pure tally math (`tallyPrices`, loom-core.js) underneath both.
- **Prompt override:** a hand-edit made directly in `<mg-generate-drawer>`'s composed-prompt
  box now durably persists (`c.promptOverride`/`c.promptOverrideText`), surviving a shot
  deselect/reselect and a reload — previously a hand-edit only affected that one immediate
  Generate click and was silently discarded the moment the owner looked at a different shot.
  `shotText()` returns the override verbatim instead of composing from Camera/Lighting/cast
  when one is active (never merged — composing scaffolding INTO an already-hand-edited
  override would duplicate it deeper on every re-sync cycle). Committed on a debounce/blur
  (`mg-prompt-commit`, distinct from the pre-existing per-keystroke `mg-dirty`) or flushed
  synchronously (`flushPromptEdit()`) whenever the host is about to read committed state
  faster than the debounce allows (a shot switch, or the toolbar's Generate-all button).
  Typing in the Loom's own native Prompt textarea clears an active override immediately
  (visibly — a brief self-clearing flash notice, not silent) since it means the same thing
  from the other surface. The "↺ re-sync from shot" button clears it and forces a fresh
  auto-compose. A visible badge distinguishes override-active from auto-composed.
  **All three of the above were designed, then independently adversarially reviewed twice**
  (one design agent's first attempt for the batch-hardening item came back as an unusable
  placeholder stub; the rescue plan a reviewer wrote to replace it was itself reviewed a
  second time before anything was implemented) — both passes caught real, since-fixed
  correctness bugs: stale React closures that would have made the tally never update, a
  busy-guard wired to an effect dependency array that would never fire, and an empty-prompt
  check against the always-non-empty COMPOSED string (structurally incapable of ever
  triggering) rather than the shot's actual raw prompt field. Live-verified end to end
  (override persisting across a real shot-switch round trip, the empty-prompt flag firing
  correctly in the batch confirm, the cost pill computing a real estimate), 93 Node + 554
  Python tests green.
- **Generation-lifecycle correctness fixes, 2026-07-18 (live-tested against a real project):**
  `<mg-generate-drawer>` is now mounted once, permanently, in the Video tab's DOM (CSS-hidden
  on other tabs instead of conditionally unmounted) — switching tabs mid-render used to kill
  the drawer's in-flight poll outright, stranding the shot at "wip" forever. A completion
  handler now routes via the shot id captured at submit time, not whichever shot happens to be
  selected when the result/error event actually fires (switching shots mid-render used to
  attribute the finished clip to the wrong card). A real terminal `status:"error"` now exists
  on the card (previously only "todo"/"wip"/"done" — a failed render left `status:"wip"`
  forever, indistinguishable from one still genuinely rendering — a real server-reported failure
  still writes this status; elapsed time alone no longer does, see the give-up-timer softening
  below). The drawer's prompt/image/video/audio
  reference slots now clear (not just overwrite) when the newly-selected shot/draft has none —
  switching from a shot with cast refs to an empty draft used to leave the previous shot's
  images sitting in the drawer, ready to submit against the wrong generation. And
  `promptDirtyRef` (tracks "the owner hand-edited the drawer's prompt since the last sync") now
  resets on an actual shot change, not just the manual "↺ re-sync" button — it used to latch
  true forever after the first hand-edit anywhere, freezing every other shot's drawer on stale
  text. None of these were introduced by the per-model-gating pass earlier the same day; all
  predate it and were found live-testing real generations.
- **Give-up-timer softening, 2026-07-18(pm):** elapsed time alone no longer ends a shot in
  `status:"error"` — only a real server-reported failure does. Both poll loops (the Loom's own
  `pollShot` and `<mg-generate-drawer>`'s independent `_poll`, tracking different submission
  paths) now escalate through three tiers instead: 20min downshifts cadence + shows "Taking
  longer than expected"; 90min downshifts further + shows "Still going after Nh — unusual"; a
  6h ceiling stops this tab's own polling (protects against a permanently wedged/deleted task)
  but leaves `status`/`pendingTaskId` untouched, genState phase `"paused"`. A reload (the
  resume effect, now passed a durably-persisted `c.genStartedAt` so the ceiling means something
  across reloads) or clicking the card's own "paused" badge always gives it a fresh budget.
  `batchTally` now tracks outcomes via a `{[cardId]: "done"|"failed"|"stale"}` map (not flat
  counters) so a batch shot that resolves after being marked stale doesn't double-count.
  Designed then adversarially reviewed (Workflow tool) before shipping — the review caught a
  Critical bug (two new callbacks used in a dependency array without being threaded through
  `LoomV2`'s props, which would have thrown on the very first render and blanked the whole Loom
  behind `V2Boundary`'s fallback), the batchTally double-count, a scope bug in a shared
  time-label helper, and the missing `genStartedAt` persistence — all fixed pre-ship. Flagged,
  not yet acted on: `/api/task-status`'s exception handler returns HTTP 200 `{phase:"failed"}`
  for a transient local blip, indistinguishable from a genuine PixAI failure to either poll
  loop — an owner decision on whether to change that endpoint's error shape. Node tests green,
  incl. a new permanent parity test guarding the drawer's local `friendlyGenErr` copy against
  drift. Live-verified: no console errors on load, normal wip/done badges unaffected by the
  new paused-aware busy-guards. The actual multi-hour tier escalation was verified via code
  review + the adversarial-review pass, not literally clocked in real time.
- **Drawer error-friendliness, 2026-07-18(pm):** `<mg-generate-drawer>`'s own error rendering
  (`_renderError`) now recognizes a content-moderation rejection the same way the Loom's own
  poll path already did — a local, verbatim port of `friendlyGenErr` (the drawer can't import
  `loom-mutations.js`, an ES module, and must stay a build-free `<script>`), wired into the two
  call sites that carry a genuine raw server string (submit failure, poll task failure). Fixes
  the Loom's own Video-tab mount for free (shared component) and will cover the gallery's own
  Video tab once it adopts `<mg-generate-drawer>` (still pending).
- **Timeline drawer's video preview was too small and left-justified** instead of centered —
  `.sb-shotprev`/`.sb-shotprev-wrap` max-width 340px→460px with `margin:auto` centering, the
  preview zone/drawer's "full" height grown proportionally (280px→362px / 360px→442px) so the
  larger preview doesn't overflow into the reel scrubber. Live-verified via direct DOM
  measurement (the `computer` tool's screenshot capability was unreliable this session).
- **Deep Focus** (double-click a board card) is a maximized single-shot editor: title, mode,
  duration, both `FrameSlot`s, and per-shot **other references** (add/edit/remove image, video,
  or audio refs and their `@tags`) via `addRef`/`setRef`/`delRef`. A "Select in Generate →" button
  binds the shot and
  closes the modal.
- The **Timeline** is a fixed drawer with three states (hidden / slim / full), video preview
  above the scrubber, drag handle on `.lv-tlhandle`.
- **Legend** is a per-field on-demand "+ terms" popover on Camera, Lighting, Transition in and
  Transition out (`lv-termsbtn` → `togglePal`, `CAM_PALETTE` / `TRANS_PALETTE`). There is no
  Legend panel anywhere.
- **Footage** is a second tab inside the left card beside Cast & assets, not a fourth region.
- The left card widens to 560px only when the Cast tab is on Detailed density; Simple mode and
  the Footage tab stay 280px. **The Generate drawer is 560px** (widened from 380px 2026-07-18,
  design-mockup pass — the exact point all 6 Multi-Reference image-ref slots fit in one row is
  500px; 560px leaves real breathing room past that bare minimum, owner's explicit pick over a
  live slider mockup). Both side rails collapse to 52px icon strips.
- Detailed cast rows are fully editable (name / tag / kind / lock / remove) and share state
  with Simple mode; Simple cards dim, drop the pointer cursor, and carry an explanatory
  tooltip when no shot is selected (ba1c82e, 48ac4dd).
- **Each detailed cast row has its own gallery-picker icon** (38×32px, matching the thumbnail
  slot's own size, sitting FIRST in the row — 2026-07-18 design-mockup pass, owner-approved
  against a locked interactive Artifact mockup). Opens the shared gallery picker filtered to
  the row's own kind (image or video; audio rows have none — there's no gallery of audio
  clips anywhere in the app) and sets that row's `mediaId` directly, no new row created. This
  is IN ADDITION to the existing local-file-upload thumbnail (image rows) and the two
  unchanged bottom buttons ("+ add from gallery" / "⇣ Import collection").
- **Draft generation:** all four Generate-drawer tabs (Image / Edit / Reference / Video) work
  with no shot selected, via a `__draft__` card keyed into the same gen-state dicts real shots
  use. A route-into-a-shot picker appears only in draft mode; bound-mode generation is
  unchanged (2874850).
- `ShotPreview` (the V2 timeline preview) carries play/pause honoring the trim range, hover-scrub,
  trim handles, and an editing toolset: fast-forward/rewind (playhead stepping), **Split**
  (`splitCardAt` — cuts a shot in two at the playhead, both halves keeping the same clip with the
  trim range divided, so Export plays them back-to-back), and **Crop** (drag a rect; stored per
  shot as `{x,y,w,h}` fractions, applied at export via ffmpeg's `crop` filter). Not a full NLE.
- A shot's **project "Look"** (a `project.look` style line, edited in Cast & Assets) is appended to
  every shot's prompt via `shotText`, and **Draft mode** (`project.draft`, a top-strip toggle) sends
  the cheaper `basic` quality on `shotPayload` for both the price preview and the submit.
- An interrupted render resumes: the shot's task id is persisted (`pendingTaskId`) and re-polled on
  load, so a mid-render tab close no longer strands the shot or orphans its clip.
- Frame handoff is trim-aware — it extracts the previous shot's frame at its `trimOut`, not the
  untrimmed clip's real last frame.
- Multiple named storyboards persist at `storyboard:v2:proj:<id>` with an active pointer, via the
  `ProjectSwitcher` in the top strip.
- The state layer is four composed hooks — `useProjectStore`, `useShotMutations`,
  `useGenerationPipeline`, `useExportPipeline` — with pure reducers/classifiers/builders in
  `loom/src/loom-mutations.js` (ee4b33a).
- Pure Loom logic (`flat`, `shotText`, `shotPayload`, tag math, continuity, `frameLinked`,
  `connectMeta`) lives in `loom/src/loom-core.js` as ES exports — no React, no DOM, no fetch —
  behind a Node/npm/esbuild toolchain scoped to `loom/`. The esbuild bundle is opt-in via
  `/loom?bundle=1`; Babel-standalone is the default, so **nothing requires a build step**. Node
  cases run from `loom/` with `node --test` (7231f83). Pricing is not in this module — it is a
  network call (`priceShot` → `POST /api/price`, inside `useGenerationPipeline`).
- The Loom inherits the gallery's design tokens (`--panel`→`--surface0`, `--ink`→`--text`,
  `--amber`→`--accent`), so switching skin in the gallery header re-colors the Loom. Every
  skin reaches both surfaces.
- `<mg-model-picker>` and `<mg-gallery-picker>` are live framework-neutral custom elements in
  `static/`, with standalone harnesses; the Loom mounts both via ref-callback bridges
  (c24837c).
- Loom projects persist as one atomically-written file per key under `out_dir/loom/kv`, with
  the legacy `store.json` auto-migrated in on first touch (1710f04).
- **Project export is a two-tier "Export ▾" menu** off `ProjectSwitcher` (the `ExportMenu`
  component): Shot list (.txt), Lightweight backup (.json — project +
  local-only thumbs, referencing your own catalog by media id), and Full bundle (.zip — the
  same plus the actual referenced media files, server-built at `/api/loom/export-bundle`). A
  real PixAI media_id is globally issued, so the bundle keeps ids as-is end to end; media
  resolution falls back to the catalog row's filename for videos, since
  `find_files_for_media_id` is image-only by design. Restore accepts either file back
  (`importBackup` sniffs which); a bundle's media is reconciled server-side at
  `/api/loom/import-bundle` (`source='api'`, since it's real PixAI media just synced by
  transfer) — a media_id already resolvable on the receiving machine is skipped, so
  re-importing the same bundle twice is a no-op the second time.

## Gallery

- Search matches a task/media id by **exact** equality, gated to all-digit terms of 8+
  characters; shorter numeric terms stay prompt-only. The box reads "Search prompt / task or
  media id" (c999ae6).
- The Health page's disk walk excludes `gallery/`, `_duplicates/`, `_deleted/` and
  `branding/`, so it agrees with the Panel's catalog-row count.
- Thumbnails serve stale-while-revalidate under the `pixai-img-v3` service-worker cache;
  write-once originals are cache-first. Bumping the cache key is how a stale-thumbnail sweep is
  forced.
- Base-model tuned presets prefill the drawer: `resolve_version_meta` returns the author's
  negative prompt / sampling steps / cfg scale and `applyModelDefaults()` fills those fields,
  showing a note row with a "↺ reset" button. A model with no tuned preset leaves the fields
  alone (f1e35d1).
- The Loom nav button is hidden below 480px and visible from tablet up; the gallery's filters
  become a bottom sheet at the same breakpoint. The Job Tracker/Activity tray (`#jobs-tray`,
  `static/mg-notify.js`) and the snippet/tag popups (`#snip-menu`, `#tag-suggest`,
  `pixai_gallery.py`) clamp their `max-width` to `calc(100vw - Npx)` so none of them run off a
  320px-wide screen (below their previous flat max-widths).
- **All three Job Tracker sources now log to the same `out_dir/jobs.jsonl` activity feed**:
  Control Panel actions and bulk cloud-delete (already wired), and now a bare CLI run from a
  terminal too (`--sync`, `--update`, `--generate`, `--generate-video`, plain download) — each
  gets a `cli-<uuid>` job id (mirroring `panel-`/`bulkdel-`), logged fail-soft so a logging hiccup
  can never break the actual command. A panel-spawned subprocess still logs exactly once (no
  duplicate entry) via the existing `MOONGLADE_PROGRESS=1` path.
- The Generate drawer's Edit ▸ Enhance sub-tab promotes ten one-click PixAI workflows
  (upscale / upscale 2×2 / upscale+enhance / remove-bg / precise-inpaint / outpaint / line-art
  / sketch-colorize / relight-sun / relight-backlight), each firing `Gen.enhance(<workflow_id>)`
  → `/api/enhance`, priced-and-confirmed before it spends. A search box below browses the rest
  of PixAI's ComfyUI catalog into `#enh-list`. The Fix sub-tab is a separate box-coordinate
  hand/face fixer (`/api/fix` → `submit_fixer`).

## Achievements / Trophy Hall

- The Trophy Hall is a **maximized overlay** grown from `#ach-modal` — Summary / All /
  Statistics tabs, main grid, right rail (category nav, Within Reach, Rewards Earned, mascot
  alcove), collapsible sections, search, mobile stacking. All Hall CSS is scoped to
  `.ach-hall` so the contest/art modals sharing `.ach-panel` are untouched (8836086, 911b2ef).
  The rail carries the rewards; the grid tiles are plain.
- Points are tier base + 5×(rung−1), driven by `_TIER_POINTS` (common 5 / rare 10 / epic 25 /
  legendary 50 / feat 0) and a derived `_ACH_RUNG`; feats score 0 so the total never hints at
  a hidden feat. Points render on the toast, tiles, and a Warband-style header total.
- 9-slice tier frames wrap the unlock toast for **legendary and feat only**; grid tiles carry
  no frame. Adding epic is a one-key change to the framed map in `_mkMoment`.
- Per-criteria checklists render on the two closed-universe set masteries (Full Toolbox =
  edit/enhance/fix; Master of the Loom = i2v/flf/r2v) via `_ACH_CRITERIA` /
  `achievement_criteria`. Open-ended sets stay count-only.
- `achievements.json` carries `earned_at:{id:iso}` for earned ids only (no hidden-feat leak),
  fail-soft; `/badge-thumb/<id>.png` serves lazy ~256px copies into `branding/_thumbs`.
- Masked feats show the cloaked-Nel art in full color (not grayscaled); name and description
  stay masked server-side (43014ef).
- The canonical roster is `docs/achievements_roster_57.json`: 57 achievements, `art_candidate`
  assigned on every one. Badge and mascot art serves from the D: branding tree
  (`D:\Moonglade Athenaeum\pixai_backup\branding\`); the pre-57 badge originals are preserved
  unserved in `badges\_pre57_backup\`.

## Public repo / community

- **CI** (`.github/workflows/tests.yml`) runs both suites on every push and pull request: the
  Python suite (`--ignore=tests/test_similar.py`, no `pixeltable`/PySide6 installed — no test
  imports either) and the Loom's `node --test` after an esbuild rebuild.
- **`CONTRIBUTING.md`** covers setup, running tests, the invariants that matter most to an
  outside contributor (`media_id` resolution, catalog-schema three-place changes, never
  committing `config.json`), PR expectations, and a private channel for security reports.
- **`READ_ONLY` in `config.json`** refuses every account-mutating call outright — submitting a
  generation, submitting a hand/face fix, deleting a task, claiming a reward — from the CLI or
  the web app, and regardless of `--confirm`/`--apply`/`--yes`. The four choke points
  (`submit_generation`, `submit_fixer`, `delete_task_gql`, `claim_reward`) are the only places
  every generate/edit/enhance/fix/delete/claim path funnels through, CLI and web alike, so
  gating there covers both surfaces from one place. Scoped to the PixAI account specifically —
  `--organize`/`--dedup` are untouched (already dry-run-by-default, never network). Documented
  for users on the wiki's **Trust & Safety** page.
- **A first-run wizard banner** appears on the gallery's home page, gated only on a fresh
  (not module-cached) read of `config.json` and the true unfiltered catalog count: no key
  configured → paste-a-key form; key present but zero rows → a "Sync now" button. Neither
  shows once the catalog has real rows. There is no separate local-vs-LAN check on the
  banner itself -- reaching `/` at all already requires `_is_authorized_request()` (the
  front-door login gate), so any authorized viewer (the owner at the keyboard, or a
  logged-in LAN account) sees it under the identical `needs_key`/`catalog_empty` condition.
  `/api/setup/save-key` validates the submitted key by hand-building a session with it as the
  sole credential — deliberately NOT via `core._make_session()`/`load_token()`, which prefer
  the module-cached `core._cfg` over a fresh file read (correct for normal operation, wrong
  for validating a just-pasted key: confirmed live, a garbage key was reported as verified
  because the cached real key answered instead). Config is written only after that call
  actually succeeds — never written first and rolled back. "Sync now" reuses the existing
  Panel job machinery (`/api/panel/run` action `sync`, polled via `/api/panel/status`) — no
  new job-running code. A second fix was needed for the wizard to be reachable on a genuine
  fresh clone at all: `pixai_gallery.py`'s CLI entry point used to `sys.exit` outright when
  the (git-ignored) output folder or `catalog.db` didn't exist yet — a console error before
  Flask ever started, with no page for the wizard to render on. It now creates the folder and
  an empty, schema-initialized catalog and boots normally instead.

---

## Access & accounts

The gallery is **default-deny**. One `@app.before_request` hook (`_enforce_front_door()`)
gates every route; the public surface is exactly three things — `/login`, `/logout`, and
`/branding/` (static cosmetic art the login page itself needs). There is **no localhost
bypass**: login is required from `127.0.0.1` exactly as from a LAN address.

**Three tiers.** PUBLIC (the three above) · LOGIN (everything else — any signed-in session,
local or LAN; this is what makes tablet generation work) · LOCALHOST (a signed-in session
*and* a loopback address). Only five routes are LOCALHOST, and each acts on the server's own
files or deletes irreversibly from PixAI: `api_panel_run` (destructive actions only),
`api_panel_cancel`, `api_panel_schedule` POST, `api_setup_save_key`, `api_branding_shortcut`.
`/api/server/stop` and `/restart` are deliberately LOGIN, by owner decision.

The tier table is **enforced, not documented**: `tests/test_route_tiers.py` enumerates
`app.url_map`, fails any route that declares no tier, and — critically — asserts a LOCALHOST
route refuses an *authenticated non-local* session. That last assertion's absence is what let
three gate regressions ship in one week. Verified to fail when the gate is broken.

**First run** creates the first account through the login page itself, offered only to a
loopback request while zero accounts exist, so a LAN device can never claim it. Ongoing
management is **Panel → Users**. `--add-web-user` remains a recovery path only.

**Passwords:** 8-character minimum with a weak-password blocklist (repeated characters,
sequential runs, common list), NIST-shaped — length is the control, no composition rules.
One helper, `core.password_problem()`, serves all three creation paths.

**Revocation** rides an install-wide monotonic counter, `AUTH_EPOCH_SEQ` in `config.json`,
not a per-account one — a per-account counter died with the account, so re-creating a username
reset it to the value stale cookies carried and un-revoked them. A legacy config gets a
1,000,000 margin on first mint so an account removed *before* the upgrade can't be walked back
through. `_save_config` is atomic (tmp + `os.replace`), because a torn read returns `{}`, which
reads as zero accounts and drops the install into bootstrap mode.

---

## In flight

- Gated on nothing, ready whenever there's capacity: further V2 shell work, the Loom
  visual-refinement pass, and the video-control base set.

---

## Next

### Documentation

- **The published `wiki/` has a real catch-up backlog.** Four current areas are undocumented
  there: **The Loom** (V2 shell + generation), the **Control Panel** (maintenance jobs, the
  scheduler, Advanced sync options, Users), **Trophy Hall / achievements**, and
  **branding / mascots**. `wiki/` today is only Backing-Up · Collections · Deleting · FAQ ·
  Gallery · Generating · Health · How-It-Works · Setup · Troubleshooting · Trust-and-Safety. This
  is a discrete deliverable, distinct from CLAUDE.md's go-forward "update the wiki on every
  commit" rule — that rule is what makes the backlog a live obligation, not a nice-to-have.
  (Surfaced 2026-07-20 by a DASHBOARD↔STATE reconciliation; the item had lived only in the
  git-ignored local dashboard.)

### The Loom — other

- **Export carries real audio.** Segments with a detected audio stream (`probe_has_audio`) trim
  and concat it; segments without one get matching-duration synthesized silence (`anullsrc`) so
  the track can't desync across a boundary. `ffmpeg`'s `concat` filter requires its input pads
  interleaved per segment (`[v0][a0][v1][a1]...`), not grouped by stream type — a real ffmpeg
  constraint, not a style choice. A multi-track audio lane remains out of scope (see below).
- **Visual-refinement pass.** The skin system already reaches the Loom, so what's left is
  polish against a real design pass, not wiring.
- **Opt-in larger text/button scale** covering *both* the V2 shell's side panels and the
  board's `.lv-card` shot cards, as one consistent option. Desktop-only, not a responsive ask.
  The compact spec stays the default in both places. Likely a compact/comfortable toggle
  driving a CSS custom-property scale, not two maintained layouts. Revisit after the visual
  pass, not before.

### Web components (Option A migration)

Order lives in `docs/archive/SUITE_ARCHITECTURE_AUDIT_2026-07-13.md` §6.

- `<mg-generate-drawer>` (`static/mg-generate-drawer.js` + its harness
  `static/mg-generate-drawer.html`) is the third shared component: the **Video tab**, at
  FULL PixAI Multi-ref parity per the locked mockup — 6 image + 3 video + 1 audio ref slot
  (video slots show real poster thumbs; audio uploads directly via `/api/upload`, no gallery
  picker involved since audio isn't catalogued), negative prompt (i2vPro only — referenceVideo
  has no such field, a genuine PixAI API gap, not an oversight), Channel (Normal/Enhanced,
  PixAI's own wording, defaults Normal), and the full 7-model roster with capability chips
  (2 models ship disabled pending a `--dump-params` capture: V3.0 Flash, V2.7). It owns the
  whole lifecycle (form → `/api/price` cost → `/api/loom/generate` submit → `/api/task-status`
  poll → result strip) and stays picker-agnostic via `mg-pick-request` (carries a `kind` hint
  so a host filters image vs. video picks; `mg-submit`/`mg-result`/`mg-error` report the run;
  `mg-dirty` fires on a genuine hand-edit to the prompt box, distinct from a programmatic
  `prefill()`; `setRefs()`/`prefill()` are the bridge/shot-context entries, `prefill()` taking
  `video_refs`/`audio_ref`/`negative`/`is_private`, snapping an out-of-range duration to the
  nearest real option rather than leaving the `<select>` on no match). Server-side,
  `build_shot_video_params()` threads `negative`/`is_private` through to both builders, and
  `/api/price`'s video branch accepts ANY reference kind alone for R2V (was image-only — a
  video- or audio-only Multi-ref used to silently mis-price as "pick a source image").
  **Mounted in the Loom's Video tab** (`master-storyboard.jsx`'s `LoomV2`): Mode, Continuity,
  the raw prompt, Duration, and Camera/Lighting/Transition in/out stay Loom-native fields
  (structured, feed the reel/export/FLF-continuity coupling unchanged) sitting above the
  drawer as a weave strip; the drawer's own prompt box shows `shotText()`'s live composition
  and re-syncs on any weave-field change UNLESS the owner has hand-typed in it since
  (`mg-dirty`-tracked), with an explicit "↺ re-sync from shot" override. `mg-submit`/
  `mg-result`/`mg-error` write into `genState` (board card's live status badge) and
  `setCardStatus` (`pendingTaskId` for tab-close resume, `resultMid`/`actualDur` for the
  finished clip landing on the shot) via two new handlers (`onVideoSubmit`/`onVideoResult`/
  `onVideoError`) threaded down from the parent component, mirroring exactly what
  `generateShot`/`pollShot` already write for every other generation path — same board/resume
  behavior regardless of which UI submitted. **Per-model mode gating shipped 2026-07-18**,
  off the completed 7-model capability matrix (`private/GENERATOR_SURFACE.md`): the mode
  segment (First Frame / First & Last Frames / Multi-Reference) now shows only the modes a
  selected model actually supports (Multi-Reference is V4.0-pair-only; First & Last is the
  three V3.0-generation models; V2.7/V3.0 Flash are First-Frame-only), auto-switching off an
  invalid mode rather than allowing a submit shape PixAI's own UI never offers. Same pass:
  model roster reordered to PixAI's real order (V4.0 Preview before V4.0 Lite Preview — was
  backwards), frame slots relabeled to PixAI's exact "Start Frame" / "End Frame (Optional)"
  (End renders as its own block, confirming leaving it empty already submits fine), the
  "Priority" control renamed "Basic / Professional" (PixAI's real tab pair, not a speed
  setting), and the Camera-movement dropdown uses PixAI's real option wording. Verified live
  (all 3 gating tiers clicked through, zero console errors) — see the convergence mockup v3
  in the artifact ledger below. **R2V's image/video banks auto-populate from the
  shot's cast + other refs**, via `buildShotPayload` (loom-core.js) — the exact tag-sorted
  composition `shotText()`'s "@imageN" / "Keep consistent" citations are written against. This
  is load-bearing, not a convenience: an initial build left these banks empty for the owner to
  fill by hand, which silently broke the citations already in the composed prompt (a hand-filled
  slot order that doesn't match the text's tag numbering binds "@image1" to the wrong image, or
  to nothing — wrong output with no error, found and fixed same day, 2026-07-18). Continuity
  "extend" adds the previous shot's clip as an extra video ref on top. Audio refs are the one
  gap `buildShotPayload` never covered, before or now — that's pre-existing, not new. Live-
  verified against a real project with real cast: a resolvable cast member (real `mediaId`)
  correctly lands in slot 1 matching the prompt's `@image1`; an unresolvable placeholder cast
  member (no image ever attached) is correctly excluded from the image array while still
  listed in the prompt text, matching the old system's own behavior exactly. Also verified:
  mode/duration sync (incl. the out-of-range-duration snap bug found and fixed live), prompt
  composition + hand-edit-wins + re-sync, the real picker bridge (type-filtered, real pick
  landed in the slot), and the submit/result event chain correctly updating the board card
  (status badge, thumbnail, duration) — all with zero console errors. **The gallery keeps its
  own working Video tab** — adoption there is a later, live-QA'd swap, same as the model-picker
  precedent.
- **BLOCKER found 2026-07-18, Mode resolved 2026-07-18 (live-tested against a real project):**
  the Loom's Video tab showed its own Mode chips / Duration chips / Prompt textarea / audio
  checkbox+language chips ABOVE the mounted drawer, duplicating fields the drawer also owns —
  the "convoluted... multiple sets of the same button groups" state the owner flagged (and the
  root cause of a real bug: clicking the drawer's own mode segment never wrote back to the
  card, so the segment visibly "bounced back" the moment anything re-triggered the prefill
  sync). **Mode is fixed and the legacy Continuity-panel Mode chips are deleted outright** —
  the drawer's own mode-segment buttons (First Frame / First & Last Frames / Multi-Reference)
  are now the single source of truth for a bound shot's mode. A new `mg-mode-commit` event
  fires ONLY from a direct user click on those buttons (never from the drawer's internal
  `_setMode()`, which `prefill()`/`_applyModelGating()`/`setRefs()` also call — dispatching
  from those would create a host↔drawer sync loop); the host listener maps the drawer's 3-value
  `r2v` to the card's `R2V` (never `V2V` — the drawer has no V2V concept, and at the real submit
  layer V2V/R2V already resolve to the identical generation path) and routes through the
  existing, tested `setShotMode` reducer, so its Continuity-reset coupling
  (`connect:"flf"→"new"`) keeps firing exactly as before. A guard skips the write when the
  drawer's collapsed display already matches the card's mode, specifically so a redundant click
  on an already-highlighted Multi-Reference button can't silently clobber an existing **V2V**
  shot down to R2V — Deep Focus's own, deliberately separate Mode chips are now the sole
  remaining way to set a card to V2V, left in place on purpose (no `<mg-generate-drawer>` is
  mounted in that modal). A second gap an adversarial review caught before this shipped: model
  gating (`_applyModelGating`) can force the drawer to submit a mode different from what the
  card believes, with no write-back at change-time (browsing models must not silently corrupt a
  card's real mode) — closed by reconciling `card.mode` from the actually-submitted payload's
  mode in the existing `mg-submit` listener, the one moment the true mode is known for certain.
  **Duration + audio also resolved 2026-07-18 (design-mockup pass):** the Continuity panel's
  Duration chips and Generate-audio checkbox + Audio-language chips are deleted outright —
  the drawer's own Duration select and Generate-audio/Audio-language controls are now the
  single source of truth, mirroring Mode's exact pattern. A new `mg-duration-commit` event
  (fired only from a real user change on the drawer's Duration `<select>`, never from
  `prefill()`'s plain `.value=` assignment, which never fires a native `change` event) and a
  shared `mg-audio-commit` event (fired from a new `_userToggleAudioGen()` wrapper around the
  Generate-audio checkbox, mirroring `_setMode()`/`_userSetMode()`'s split so `prefill()`'s
  own programmatic sync can't re-dispatch, plus a brand-new change listener on the
  Audio-language select which previously had none at all) write straight onto `c.duration`/
  `c.audioGen`/`c.audioLanguage` as plain field patches — confirmed via full grep that neither
  field has any cross-field coupling the way Mode/Connect or the prompt override do, so no new
  reducer was needed. `shotPayload`/`shotText`/`generateShot`/`batchGenerate` needed zero
  changes (verified, not assumed): they already read these fields directly off the card. The
  dead `AUDIO_LANGUAGES` const was deleted alongside its only remaining reference. Designed
  then adversarially reviewed (Workflow tool) before shipping.
  **The Prompt textarea is the one piece deliberately held back, owner's explicit call
  2026-07-18:** it is still the **only write site for `c.prompt` in the entire app** (no Deep
  Focus equivalent) — a "base" string `shotText()` keeps recomposing alongside every later
  Camera/Lighting/cast edit. The drawer's own composed-prompt box only ever writes
  `c.promptOverride`/`c.promptOverrideText` (a frozen, never-re-woven verbatim replacement,
  by that feature's own explicit design) — deleting the native textarea would make every
  hand-typed prompt an override going forward, silently retiring the compose-from-fields
  machinery for any shot ever hand-touched. Owner chose to hold this out rather than decide
  yet; two live options if/when revisited: ship the override-only model as a deliberate
  simplification, or give base-prompt editing a new home in Deep Focus (mirroring exactly how
  Deep Focus stayed the sole remaining way to set a card to V2V after Mode's own chips were
  deleted). Not a blocker on anything else shipping.
- The opt-in pre-built Loom bundle (`/loom?bundle=1`, `loom/dist/master-storyboard.bundle.js`,
  `npm run build` in `loom/`) must be rebuilt whenever `master-storyboard.jsx` changes, or that
  path keeps serving whatever bug the default Babel-in-browser path already fixed — flagged by
  an adversarial review 2026-07-18, rebuilt as part of the Mode fix landing. Not yet on any
  automated rebuild step; still a manual reminder.
- `<mg-cost-badge>` remains unbuilt. Nothing exists in `static/` for it.
- Gallery adoption of `<mg-model-picker>` (replacing the working `#model-flyout`) is a later,
  live-QA'd step.
- **`static/mg-notify.js` (2026-07-18, the fifth shared file)** carries the achievement-toast
  celebration system (`Ach`), the general-purpose corner `Toast`, and the Job activity tracker
  (`Jobs` + `JobsCard`) — extracted verbatim from the gallery's own inline `<script>`, now the
  **single source** for all three (the gallery's inline copies were deleted; both surfaces load
  `<script src="/static/mg-notify.js">`). Unlike the other four shared files this isn't a
  custom element — `Ach`/`Toast`/`Jobs`/`JobsCard` are plain global IIFEs operating on
  `document.body`/`getElementById`, matching exactly what they were inline; it self-injects one
  `<style>` tag so a single script tag carries both behavior and styling. The Loom's shell now
  carries `#jobs-fab`/`#jobs-tray` anchors (the achievement-toast path needs no anchor at all —
  `_mkMoment`/`celebrate` build their own DOM from scratch, confirmed by reading `render()`'s
  own defensive `if(el)` guards; only the VISIBLE Job Tracker card needs somewhere to render
  into). `Ach.open()`/`close()` gained a null-guard (the original was unguarded, and a global
  Escape-key listener calls `close()` on every keypress app-wide — would have thrown in any
  host without the Achievements modal, found live-testing before it shipped). `Jobs` gained a
  new `register(id,label)` — registers with the server activity log without starting a second
  polling loop, for hosts (the Loom) whose own generation flow already owns a hardened,
  independently-completing poll loop (`pollShot`/`_poll`) and would otherwise double-poll the
  same task; both `generateShot` and the Loom's `onVideoSubmit` (the drawer's `mg-submit`
  handler) now call it, closing the confirmed gap that `/api/loom/generate` never logged a job
  at submission time on its own (client-side only, by this app's own architecture — the Python
  route itself was never the gap). `.ach-m2`/`#mg-toasts` z-index raised (430/420 → 520/510) so
  a celebration or completion toast is never silently swallowed by the Loom's own full-screen
  overlays (Deep Focus veil z-index 450, Sequence Player z-index 500 — both everyday
  interactions the gallery doesn't have). The Job Tracker's default bottom-left position
  collides with the Loom's own left Cast panel (confirmed via live measurement: an open tray
  covers the top of the "+ add from gallery"/"Import collection" buttons once that panel is
  scrolled to its end) — fixed with a `!important`-scoped `bottom:88px` override living in
  `_LOOM_SHELL`'s own `<style>` block (an ID-selector tie against the script's JS-injected
  style otherwise silently loses regardless of source order, confirmed by trying the
  non-`!important` version first and finding it did nothing); the gallery's own position is
  untouched. `.ach-modal` is shared base chrome for THREE modals (`#ach-modal`/
  `#contest-modal`/`#art-modal`, not achievement-exclusive) — flagged with an explicit comment
  so a future edit doesn't scope or drop it independently of Contests/YourArt. Designed then
  adversarially reviewed (Workflow tool) before shipping; the review caught the drawer-wiring
  location (moved off `mg-generate-drawer.js`, which must stay host-agnostic, onto the Loom's
  own `onVideoSubmit`), the missing `seen{}` de-dupe guard on `register()`, the shared
  `.ach-modal` coupling, and the untested tray-collision claim (which turned out to be real).
  Full suite green (`python -m pytest -q`), including a new Python smoke test asserting the
  Loom shell carries the script tag and both anchors. Live-verified: Trophy Hall + Contests/YourArt modals render
  correctly on the gallery with zero regressions, `Jobs.register()` round-trips through the
  real `/api/jobs` endpoint into a rendered tray row, the tray-collision fix measured clean
  (0px overlap, was 12.7px), z-index values confirmed above the Loom's overlay ceiling, zero
  console errors anywhere.

### Achievements

- Populate `docs/achievements_roster_57.json`'s `badge` field — most entries are blank even
  though every badge ships. A bookkeeping gap, not an art gap.
- Build a new roster board from `docs/achievements_roster_57.json`.

### Control Panel / web parity

Sequenced **ahead of** the PySide6 GUI removal so nothing CLI-only goes dark.

- **`--restore-orphans` and `--undo-organize` have no Panel button** — the two remaining
  CLI-only maintenance actions. (`sync-artworks` / `sync-videos` / `reconcile-deleted` run via
  `/api/panel/run` and the scheduler but render no button by design, `panel_visible: False`.)
  (`PANEL_ACTIONS` in `pixai_gallery.py`.)
- ~~**Web import into the catalog.**~~ ✅ **Shipped 2026-07-20.** The **↑ Import** button (owner
  header) opens a drop-zone modal (drop images / a folder / a `.zip`, or browse), with an adaptive
  preview (thumbnail list when few, capped 24-tile grid when many — import is uncapped) and
  add-to-collection. `POST /api/import-local` is localhost-only (host-filesystem write tier),
  reuses `run_import_local` (`source='local'` → `imported/` → thumbnail, path-dedup), and expands
  zips with a zip-slip guard. This was the last web-parity item.

---

## Priority order (agreed 2026-07-19)

Ranked, with the reason each sits where it does. Ordering changed once already when the
owner pointed out that **web parity gates GUI removal** — anything only reachable from the
PySide6 GUI or the CLI needs a web equivalent *before* that GUI can go.

1. **Web parity** — ✅ **COMPLETE 2026-07-20.** ✅ force-full-resync (Advanced Panel) · ✅
   video/audio reference slots in the live gallery drawer's Multi-ref (the `<mg-generate-drawer>`
   swap) · ✅ convert-and-download for `/export-zip` · ✅ web import into the catalog (the
   drop-zone modal + `/api/import-local`). Nothing CLI-only stands in front of the PySide6
   removal now — that removal (item below) is unblocked.
2. **Gallery QoL easy wins** — chiefly the collection-remove UI: `/collection-remove` exists
   with **zero callers**, so the route is already written and only the UI is missing.
3. **The 401 batch and the search wildcard** — ✅ both shipped 2026-07-19. What remains of
   the 401 finding is the poll-ceiling half (see Known defects).
4. **The naming pass** (`pixai_* → moonglade_*`) — sequenced here for *timing*, not value:
   it is cleanest immediately after a merge while `master` and the working branch are
   identical. Size it with `python tools/name_inventory.py modules` before committing to it.
5. **The Design Pass** (below) — one body of work, not five separate ones.

### The Design Pass (consolidated)

Grouped by owner decision 2026-07-19: these were tracked as separate items but are one
coherent visual effort and should be scoped and executed together rather than piecemeal.

- The **Trophy Hall redesign**, blocked on the owner's own Figma frame.
- The **Loom visual-refinement pass** — the skin system already reaches the Loom, so what
  remains is refinement rather than plumbing.
- The **gallery search-bar redesign**, blocked on owner input.
- The **owner's layout/function note-taking pass**, which gates several deferred items.
- Epic-tier frame art, per-tile ornate frames, the "earned rewards" display, the
  toast-badge-to-home-marker motion, and toast tier colours vs shipped badge art — all
  previously filed individually under Open owner calls.

---

## Open owner calls

- **Trophy Hall redesign** is blocked on the owner's own Figma frame. Ask for the frame URL; do
  not re-suggest the screenshot-decomposition checklist. The Figma plugin is live and
  authenticated. (`docs/STANDARDS.md` Part 2.)
- **Trophy Hall rename** undecided. Shortlist: *The Vault Against the Void* / *The Folio of
  Honors* / *The Ledger of the World Tree* (banner subtext: "The Pillar of the Vault").
- **Epic-tier frame art** undecided. The owner wants epic to read "deep-purple WoW epic /
  tier-gear," leaning Nelnamara's Dreamwalker feathers + Balance-Druid Moonfire flair, without
  out-shouting legendary-gold or feat-ruby. Enabling it is a one-key change: the framed map in
  `_mkMoment` takes `epic:1` once art exists.
- **Per-tile ornate frames** are unbuilt — the unlock toast has them, grid tiles do not
  (`border-image` is scoped to `.ach-m2`; there's no rule on `.ach-card`). Open question: frame
  the current modal cards, or defer until Hall tiles become mini-toasts?
- **"Earned rewards" as its own display** — shape TBD.
- **"Toast badge grows to its home marker"** needs the owner to finish articulating it before
  it is buildable.
- **Real SFX for the unlock toast** need owner-supplied sound. The loader ships and fails soft,
  but no `branding/sfx/` folder exists on the served tree, so the synth chime is the only sound
  that ever plays. Sources scouted: Kenney / Sonniss GDC / freesound / OpenGameArt (CC0), or
  Stable Audio Open via Pinokio; the owner has 1–2 WoW sounds.
- **Toast tier colors vs. shipped badge art.** Whether to realign the code's toast tier-glow
  colors and rarity pill to the shipped badges' tier scheme. The recommended scheme (rarity
  carried on gem + glow, ring reinforces; legendary warmed toward amber) was never
  owner-confirmed; the code still runs the original (common = steel-blue `#9fbad6`, with
  `--gunmetal #8a93a2` / `--ruby #e0355e`).
- **PySide6 GUI removal** (`pixai_gui.py` + `Moonglade Athenaeum.pyw`) is decided but **not
  executed** — both files are present. **Now UNBLOCKED: the web-parity gate cleared 2026-07-20
  (web import was the last item).** Owner, 2026-07-19: *"Pending the web parity solutions"* — that
  condition is met. A GUI/web/CLI parity matrix confirmed zero GUI-only business capability; the only
  GUI-only items are two local conveniences (an "open `_deleted/` in Explorer" button and a
  "recently-used models" quick-pick). The phase-out is surgical — strip the redundant spend
  surfaces (the Generate/Video/Edit clones, which are strictly worse and have no cost/free-card
  safety), not a wholesale delete. The GUI is excluded from the web-component cohesion
  migration. Full deprecation also requires repointing the `Moonglade Athenaeum.pyw` launcher.
- **Gallery search-bar redesign** is unstarted and deliberately blocked on the owner's
  layout-notes pass. Banked design: a LEFT Filters drawer mirroring the right Generate drawer.
  Sketch only after that pass.
- **The owner's layout/function note-taking pass** is pending and gates several deferred
  cosmetic items: the image picker's further visual polish, taste-level width/spacing tweaks on
  Generate/Edit/Enhance, and the Composer's collapsed-stack fan animation. Features are built
  cheap-to-rearrange in anticipation of it.
- **Generation Flags** — the owner asked 2026-07-19 for a scope call rather than another
  deferral: *"either we keep deferring this or it's actually done. WHAT is the scope."*
  Current state is zero code, no spec, and two unanswered product questions (what a pass
  flags — anatomy / artifacts / NSFW / duplication — and where the verdict lives). It is not
  dependency-free: numpy is not a current dep and the CLIP index rides heavy optional ones.
  It is **not** the shipped Pixeltable "Similar / more like this" search.
  **Recommendation on the table: shrink or drop.** The only version that is concrete and
  nearly free today is *"flag near-duplicate generations"*, which the existing Pixeltable
  CLIP index can already answer with no new dependencies. Anatomy/artifact/NSFW detection is
  a research project rather than a backlog item, and should be named as one or dropped.
- **File logging** has never entered any tracker, despite `CLAUDE.md` calling it "a separate,
  still-open discussion" since `-v/--verbose` shipped. It is a loose thread, not a parked
  decision: decide whether it is in scope, or drop it.

---

## Known defects

*Found 2026-07-19 by a Playwright browser crawl (185 controls, 60 screenshots reviewed by eye).
None of these produce a console error or a wrong HTTP response, which is why the suite was fully
green throughout. Ranked.*

*Every entry re-verified against the code 2026-07-20; fixed ones are deleted, per this file's
rule. Two claims did not survive: the Loom's **cost pill is not dead** (`refreshEstimate` has
been wired since the pill's introducing commit — the crawler most likely clicked it while
prices were already settled), and **`#del-modal` is not dead markup** (`confirmDelete()` drives
both the per-row and bulk delete paths; it being what a crawl agent's XPath matched is a
crawler-targeting note, not a defect). Two more were crawl-environment artifacts rather than
bugs: **"Set launcher icon" 400s only where no `branding/marks/` exists**, so there is no `.ico`
to point at and the 400 carries a correct explanatory message — the real install has cuts for
marks 4/12/62/63/74; and **`mg-notify.js`'s mascot paths are consistent** — all use
`/branding/mascots/`. The genuine gap there is that no `login_nel.png` art exists, so the login
page's `onerror` chain degrades to `gen_nel.png` as designed.*

- **`/logout` is a CSRF-able GET that revokes globally.** No token, and it bumps `sess_epoch`,
  so a cross-site *top-level navigation* (link, `window.open`, `location=`) signs the user out
  on every device. Denial of convenience only. *Not* closed by the revocation fix — the
  victim's cookie is still valid, so the bump proceeds legitimately. Fix is a POST + CSRF, or
  splitting local sign-out from global revocation. **Note:** the `<img src=".../logout">`
  vector originally cited here never worked — `SESSION_COOKIE_SAMESITE = "Lax"` predates the
  crawl, so a cross-site subresource GET carries no cookie and the bump is skipped. The defect
  is real; only its cheapest vector was wrong.
- **Escape doesn't close the Loom's project or Export menus**, and their backdrop is a
  full-viewport `pointer-events:auto` veil — so the entire app is unclickable until the user
  happens to click outside. Deep Focus's own Escape handler works correctly in the same app.
- **Service-worker registration fails on the login page.** `/sw.js` is gated, so a signed-out
  page gets a redirect and Chrome refuses a redirected worker script. It registers on the next
  navigation after signing in; the thumbnail cache simply arms late.
- **Native `<select>`s are styled two inconsistent ways.** `.filters select` / `#preset-select` /
  `select.p-sel` get `appearance:none` + a custom caret; `.pick-filters select`
  (`pixai_gallery.py`), `.lv-sel` and `.sb-pick-filters select` (the Loom) keep the native OS
  arrow. `accent-color` has no effect on `<select>`, so this needs a real styling pass rather
  than a token. *(The checkbox half of this finding is fixed: `color-scheme: dark` +
  `accent-color` on `:root` — see CHANGELOG.)*
- **Two Loom widgets are invisible but report as visible.** The help FAB (`z-index:300`) and
  Activity chip (`z-index:234`) are siblings of `#root` in `_LOOM_SHELL`, and `LoomV2`
  unconditionally renders an opaque `z-index:400` `.lv-overlay` over them. Real bounding rects
  and `visibility: visible`, so a DOM crawler marks them healthy.
- **The Activity chip is a 79×31 click dead zone over a grid card's link** — on the *gallery*
  page, which has its own `#jobs-fab` and no `.lv-overlay`. (Distinct from the entry above: on
  the Loom an opaque overlay swallows those clicks first, so it cannot also be a dead zone
  there. These were one entry until verification separated them.)
- **Smaller:** upstream exceptions still print verbatim into the UI as a minor UX nit (34
  `str(e)` sites) — but they are no longer an injection seam: the `innerHTML` sinks now escape
  (`escH2`) or build text nodes, verified in a browser (see CHANGELOG).
- **`index()` passes `is_local=True` as a literal**, so the header's "read-only LAN view" branch
  is unreachable and the variable name is a misnomer for "authorized". This is *deliberate and
  documented* at the call site — the front-door hook guarantees an authorized request reaches
  that line — so it is a naming/clarity wart, not a bug. Renaming it touches auth-adjacent
  template logic and wants an owner nod rather than a drive-by.

- **No UI for removing an image from a collection.** The `/collection-remove` POST route exists
  with zero callers anywhere in the codebase. A real gap, not a design choice.
- **`ImportCollection`'s `.sb-pick-ov` overlay shares z-index 400 with `.lv-overlay`** rather than
  a clean 500-over-400 hierarchy — it relies on DOM paint order, which holds today. Worth a live
  look the next time that stacking area changes. Low severity.
- **Saved-view presets are localStorage-only** (`gallery_presets`), so they do not roam between
  the home and work machines this project is already edited from.
### Machine-local layout (a standing drift hazard, not a bug)

- The **live gallery server runs from the D: run-copy** (`D:\Moonglade Athenaeum\`), a separate
  `loom-v2` checkout from the C: repo, and branding art serves from
  `D:\...\pixai_backup\branding\`. The two checkouts drift: compare `git log -1` in each before
  assuming they match, and never mass-commit to "fix" the difference.
- **Art-in-progress lives at `D:\Art Scratch\`** (Badges, Icon Sheets, Chibli Sheets, the
  sorted Canva dump, Live Nel Cutouts, Nelnamara Fine Images, Banners, `logos_cut`, Stickers,
  App icon candidates, Forge, plus `make_anim_webp.bat` / `make_green_source.bat` /
  `_assemble_webp.py`). The served `D:\...\branding\` set stays live and separate.
- A **stale duplicate branding folder** (marks + banners only) sits at
  `C:\Users\gwilkins\Desktop\pixai-gallery-backup-master\pixai_backup\branding`. Flag it; do
  not auto-delete.

---

## Later epics

- **Render-tree unification is done** — there is one Loom render tree (the V2 shell); the classic
  tree it would have been merged with is gone (retired 2026-07-17). Nothing is filed under a
  "rebuild" umbrella. Remaining Loom render-layer cleanup is ordinary dead-CSS pruning: the
  `STYLES` block still carries classic-only `sb-*` rules (e.g. `.sb-top`, `.sb-card`) alongside the
  live shared ones (`.sb-shotprev`, `.sb-frame*`, `ProjectSwitcher`, the export/picker overlays) —
  safe to prune when convenient, not a blocker.
- **Loom tooling.** React + esbuild + Vitest/RTL is the combo. Preact is an optional later
  spike; Svelte and hand-rolled vanilla+signals are rejected for a solo-dev migration of
  untested code; canvas is not needed for the reel at this scale. If docking is ever needed
  again, Dockview and FlexLayout (both mature, MIT-licensed, actively maintained) are the
  candidate replacements for hand-rolled docking chrome.
- **A multi-track timeline** (layered clips + a visible audio lane) is out of scope. The tool's
  job is building 5–15s scenes and stitching them cohesively; the stitched output goes to a
  real video editor for post. Per-shot audio cues aligned to their own timeline segment cover
  the real need.
- **Epic A — The Foundry (image → 3D print).** Four stages, gated on an explicit owner go.
  Stage 1 (spike) is the go/no-go: one gallery image → Hunyuan3D-2 mini/turbo → GLB, judged on
  a real Nelnamara render; pivot to the Meshy API if 12 GB is insufficient. Stage 2 = headless
  Blender → watertight STL — **not wired; nothing Blender-related exists in the repo yet**,
  install and script it as part of that stage. Stage 3 = "Send to Foundry" button + async job +
  three.js GLB preview + STL download. Stage 4 folds into Epic B. Hardware: RTX 4070 Super
  12 GB + resin Anycubic. Resin-first (skip texture baking; orient hallucinated backs toward
  the plate). Separate optional install, gated behind its own extra, **never bundled**. This is
  the nearer of the two provider-seam epics — self-contained, no external account.
- **Epic B — The Provider Deck (multi-platform generation).** Gated on an explicit owner go,
  and bigger than Epic A; it benefits from the Foundry proving the provider-seam pattern a
  second time first. PixAI is already provider #1 behind the seam — `submit_generation` /
  `generation_status` / `collect_generation` + `build_shot_video_params` *are* the interface.
  Shape: a git-ignored `providers.json` (keys + enabled providers), a provider picker in the
  drawer/Loom, one adapter file per provider. Provider #2 = Seedance 2.0 direct
  (`api.seedance2.ai`): Bearer `sk_live_`, `POST /v1/videos/generations` → taskId, poll
  `GET /v1/tasks/:id` (≤1/10s) or webhook; modes map 1:1 to T2V/I2V/FLF/R2V/V2V and share the
  `@image1` / `@video1` / `@audio1` grammar. The one genuinely new problem: Seedance wants
  publicly-reachable URLs for input media and a localhost server cannot provide one — resolve
  during the spike via Seedance's own upload endpoint, a temporary tunnel, or a short-lived
  presigned upload. Discipline: add the seam only when the second real provider lands, so two
  concrete cases shape it.
- **Mio.2 — PixAI's agent surface.** Filed here by owner directive 2026-07-19, moved out of
  Open owner calls: it is an epic-sized bet, not a pending decision. Cookie-authed — the `sk-`
  Bearer 401s — and the contract is bankable free from the JS bundle, but integration means a
  cookie-jar rewrite. Worth it only as a deliberate agent-UX bet. **Do not capture cookies
  without owner direction.**
- **Epic C — Publish & Community (core + web).** Roadmapped into the next core + web
  passes. Independent of A/B — no provider-seam prerequisite; it can move whenever core+web
  capacity allows. `createArtworkFromTaskV2`, `upsertArtwork` / `deleteArtwork`, `markArtwork`
  (like/bookmark) and `setFollowState` are reverse-engineered and documented in `private/` but
  deliberately **off**; this epic changes that default on purpose. Scope: publish first — CLI
  `--publish-artwork <media_id>` plus a Publish action on the gallery detail page/lightbox —
  explicit-confirm gated like delete. The gate is deliberateness, not cost: publishing is free.
  Never a background or automatic action, never default-on for a batch. Like/follow only if a
  concrete use appears. Distinct from `--sync-artworks`, which is read-only published-history
  sync.
- **BlurHash grid placeholders** — deferred at low ROI; a small banked item, not an epic. The
  `blurhash` column exists and is populated from `extra.imageBlurHash`, but stays empty until
  `--sync-artworks` runs, covers published rows only, and needs a JS decoder that does not
  exist. Revisit if published coverage grows. (The detail-page NSFW breakdown from the same
  capture *is* surfaced.)
- **Gallery QoL backlog**, each verified absent from the code: rate/delete from inside the
  lightbox without closing it; bulk "set rating" on a selection; an unrated-only filter; export
  just the current search/selection instead of the whole catalog; a random/shuffle sort; a
  manual side-by-side two-image compare (distinct from the algorithmic Similar search); and
  roaming saved-view presets.
- **WoW-style casting-bar frame art** is a banked candidate for a themed generation/render
  progress bar, plus ladder-achievement and Panel job progress. The art is the FRAME; the
  dynamic fill composites inside via 9-slice so ornate ends don't stretch. Prefer the cleaner
  rounded frames over the maximalist spiky-lightning ones for constant on-screen use. The
  moon-phase progress gauge (artifact `812e82b4`) is near-finished-asset quality and enacts the
  app's own name.
- **The suite-wide standalone-app question** is explicitly low-priority and not the preferred
  direction. The question is the whole app, not the Loom.

---

## Locked design

Do not re-litigate these. Build against the named source, and verify against it before calling
anything done — that is `docs/STANDARDS.md` Part 2's rule, and it governs any user-visible
surface: no visual build from prose alone.

- **The V2 shell's pixel source of truth** is the interactive *Loom — Shell Mockup v1*
  artifact: left card with Cast & Assets / Footage tabs +
  Simple/Detailed density + collapse-to-rail; center acts/shots board with a gold selected-shot
  ring; right Generate drawer with collapse-to-rail and a bound-to-shot chip; the fixed
  Timeline drawer with its three-state drag; a live "+terms" popover.
- **The workspace shell is three named elements with nothing free-floating:** left Cast &
  Assets (Simple = name/tag/ref-preview card; Detailed = the full V1-style editable row;
  Footage as a second tab), center Acts & Shots board, right Generate drawer
  (Image/Video/Edit/Reference, collapsible, mirroring the gallery drawer's positioning and
  behavior). Top is the fixed Timeline drawer. A **full** generate panel belongs inside the
  Loom — generating straight from the board for establishing shots stays; nothing links back
  out to the gallery.
- **The Timeline** is a fixed drawer attached to the top banner, never a draggable/dockable
  panel. Three states: default visible at a slim height at full page width; fully pushed away,
  collapsing to nothing; pulled down to a set full size with the video preview **above** the
  scrubber. A side-by-side preview stays banked as a secondary layout worth exploring later.
- **Front-end direction is Option A:** promote duplicated widgets to framework-neutral custom
  elements (gallery-owned, no build step, loaded like `picker-core.js`) that both the vanilla
  gallery and the React Loom mount. "No framework" means *no build step / framework-neutral
  shared widgets* — **not** "no framework": the Loom is React by design. Migration order in
  `docs/archive/SUITE_ARCHITECTURE_AUDIT_2026-07-13.md` §6.
- **The Trophy Hall's form factor is a maximized overlay**, not a page or route: grow the
  existing `#ach-modal` to full-screen — instant open, gallery stays mounted behind, ESC out,
  animates from the trophy button. Owner screenshots tune the INTERIOR only; the form factor is
  settled.
- **All art direction — the badge style anchor, tier palette, frame direction, slot sizes, and
  the prompt bank — lives in `docs/ART.md`.** It reconciles against the code, and where the code
  settles nothing it says so. Do not restate hexes or sizes here; `ART.md` is the one home.
- **The canonical achievement roster is `docs/achievements_roster_57.json`** — 57 achievements,
  each carrying `roast` (default/spicy) and `roast_nsfw` and a `rung`, in buckets 29 ladder / 9
  milestone / 8 mastery / 11 feat. The Great Library is a **banner** reward, not a badge. The
  Descent is deliberately shelved. There is room for ~3 more against a 60 ceiling.
- **Model strategy** is banked in the frozen `docs/archive/MODEL_DECK_2026-07-11.md` (re-verify
  before relying on it — it is dated external research). Krea2 on Maestro is the local quality
  lane for ornate frame/ornament work; the badge benchmark is PixAI Tsubaki.2 v1 with detailed
  prose and no LoRA (the Hoardsmith dragon, task `2031115782282256404`). Do not assume Krea2 /
  ComfyUI / ChatGPT emit alpha — verify per file, not per model.

### Artifact ledger

**Locked**

| Artifact | What it is | Status |
|---|---|---|
| [The Loom — Shell Mockup v1](https://claude.ai/code/artifact/e41a3020-32fb-4baa-ae81-69814d5ee4c9) | Interactive pixel source of truth for the V2 shell | **LOCKED** — matches the shipped shell |
| [Video Tab — Full Parity Mockup v1](https://claude.ai/code/artifact/74ad3fd0-ff82-4430-bfe5-275194afa556) | Pixel source of truth for the `<mg-generate-drawer>` Video form, both mounts: 6 image + 3 video + audio ref slots, negative prompt, channel (ships default Normal, persisted), full roster w/ capability tags, Loom shot-weave | **LOCKED** 2026-07-18 (owner-approved) — the full-parity build verifies against it |
| [Loom Convergence Mockup v3](https://claude.ai/code/artifact/e6659d99-8376-400a-a4e5-04a3419d4ca4) | Side-by-side Gallery\|Loom source of truth: one shared drawer, Loom-only shot chrome (Continuity/Camera/Lighting/Transitions/Cast) kept, live per-model mode-gating demo, Camera+Basic/Professional hidden in the Loom (owned by the shot Camera field + Draft toggle) | **LOCKED** 2026-07-18 (owner-approved, interactively verified) — component-side fixes (gating, labels, model order) + Mode/Duration/Audio control-removal all shipped from it; only the Prompt textarea half remains, held back by owner choice (see "The Loom" section) |
| [Cast-row picker + panel width](https://claude.ai/code/artifact/d868e4fe-a376-4886-bd5e-1efa4c667472) | Interactive mock (real tokens/components): per-row gallery-picker icon on Cast & Assets rows, Generate panel width slider showing the 6-slot ref grid reflow | **LOCKED** 2026-07-18 (owner-approved: icon 38×32px matching the thumbnail slot, first in row; 560px width) — shipped |
| [toast_mockup](https://claude.ai/code/artifact/335ef4e7-2459-4c99-990a-b8c5751324c3) | The unlock-moment design (the real toast is `.ach-m2`) | **LOCKED** — shipped, `077e1f0` |
| [loom_selectshot](https://claude.ai/code/artifact/0d9c4e02-200e-44f9-982c-e3add482b905) | Selected-shot interaction model | **LOCKED** — shipped in V2 |
| [Moonglade — Finalists In Action](https://claude.ai/code/artifact/b45a39a3-b6a8-4e73-9f62-e03cb390bd00) | Finalists in context: frames wrapping a real unlock, bars filling live, claim icons in the header chip | Current — pairs with `docs/ART.md` §3 (picks ledger) |
| [Timeline Drawer — Wireframe v1](https://claude.ai/code/artifact/84be1748-2c7d-4304-967c-8ac22cd37687) | Timeline drawer detail | Reference only — the Shell Mockup is the pixel source |
| [Web Import — Drop-zone Mockup v2](https://claude.ai/code/artifact/066d181e-1a6e-4f84-97c6-6e2b91c6f90d) | Pixel source of truth for web import (the LAST web-parity item): drop zone + browse; **adaptive populated states** — thumbnail review when few, a **capped 24-tile preview** when many (import is uncapped — the cap is only on the preview), folder/zip **summary cards** (never N rows); dupe-by-content-hash skip, add-to-collection, `source='local'` into `imported/` | **LOCKED** 2026-07-20 (owner-approved) — the build verifies against it; `PREVIEW_CAP=24`. Open per-build calls: cap number, folder-recursion, structure→collections |

**Live tools & references**

| Artifact | What it is | Status |
|---|---|---|
| [The Curation Standard](https://claude.ai/code/artifact/6d6b9d2d-281e-4fd5-b1dc-7a11c599950e) | House standard for vote/selection artifacts | Mirror — `docs/STANDARDS.md` Part 1 is truth |
| [Curation Workspace](https://claude.ai/code/artifact/ef9f5853-5c8f-40eb-87f2-8cf123f0b6ef) | Reference builder: lightbox + pick + rank + tray + export | Clone this for new selection passes |
| [Moonglade Roster Board](https://claude.ai/code/artifact/31d6c68a-bd54-4824-886f-9017c6012912) | The 57-achievement three-lane voting board | Reference board (votes complete) — the model for the new board to build from `achievements_roster_57.json` |
| [ledger](https://claude.ai/code/artifact/d1ee39a1-db65-487b-a6ef-067ea6d1392d) | Per-achievement mascot + badge assignment | Live |
| [Chibi Library · assign uses](https://claude.ai/code/artifact/1998636d-9043-41e8-900d-797c67fd04f2) | Chibi browser + use assignment | Live |
| [Cohesion Map](https://claude.ai/code/artifact/4229e98c-4ac3-4e86-820a-72a57465c066) | Top-down app map | Live |
| [Moonglade Banners — defaults & unlocks](https://claude.ai/code/artifact/7919cec3-aec7-41d0-8efc-8fb2d0f4cdb5) | Banner picks; feeds the banner-unlock reward | Live |
| [Moonglade Model Deck](https://claude.ai/code/artifact/9f16f42d-2541-4dd9-935a-0f9d0f39c7c4) | Model research deck | Mirror — `docs/archive/MODEL_DECK_2026-07-11.md` is truth |

**Parked**

| Artifact | What it is | Status |
|---|---|---|
| [Badge Prompts v2](https://claude.ai/code/artifact/771f84d9-cacb-4f5c-8300-9c8575fb8431) | The badge prompt system | Mirror — live home is `docs/ART.md` §5; original in `docs/archive/badge_generation_prompts_2026-07-16.md`; parked |
| [Feat badge prompts — gunmetal](https://claude.ai/code/artifact/73372456-f09c-418c-920b-3e139988ef91) | 11 feat badge-art prompts | Parked — owner: maybe when credits allow |

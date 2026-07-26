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
PixAI's API, and curates the archive. Two surfaces: the CLI (`moonglade_backup.py`) and
the web app (`moonglade_gallery.py`). Work happens on the `loom-v2` branch; `master`'s last release
is **v2.4.0** (2026-07-24 — concurrent generations, a trash/quarantine restore panel,
field-operator search, real credit-cost tracking, a full unification of the model/image
pickers across the Loom and the gallery, a data-loss video-corruption bug fixed, the last
open Privacy Blur security gap closed, and the audit board's Tier 1-5 defect list driven to
zero open items; full detail in `CHANGELOG.md`'s `[2.4.0]` block). `loom-v2` and `master` are
in sync as of that release — check
`git rev-list --count origin/master..origin/loom-v2` for the live count rather than trusting
a number here, since new work may already have landed on `loom-v2` since. See
`docs/AUDIT_2026-07-21.md` for what's still open. Each release is a `--no-ff` merge of
`loom-v2` → `master`, tagged and published as
a GitHub Release. **The Loom is a single storyboard surface** — the V2 shell. Classic V1 (its render
tree, the `v2` toggle, and the `CardView`/`CardEditor` components) was retired 2026-07-17; `/loom`
opens straight into the V2 shell with no layout switch. The repo is public and has real external
users.

**Numbers live in commands, not in this file:**

| Question | Command |
|---|---|
| Test count | `python -m pytest` from the repo root (add `--ignore=tests/test_similar.py` when pixeltable isn't installed); the Loom's pure-logic suite is `node --test` from `loom/` |
| Current version | `grep __version__ moonglade_backup.py` |
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
  call sites that carry a genuine raw server string (submit failure, poll task failure). Covers
  both mounts of the shared component — the Loom's own Video tab and, since the gallery's
  Option-A migration (`2b20806`), the gallery's Video tab too.
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
- A board card shows a small "linked" badge when its opening frame already matches the previous
  shot's closing frame (`continuityLinked`, wired to the pure `frameLinked` check), next to the
  mode/duration tags. Silent/positive-only — there is no "not linked" warning state, since most
  shots are deliberately disconnected from their neighbor. **Owner has not yet visually confirmed
  this — built 2026-07-23, treat the exact placement/behavior as a first cut pending a look.**
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
  `static/`, with standalone harnesses. **Both surfaces mount both components now** (O12/O13,
  2026-07-24): the Loom via ref-callback bridges (c24837c), the gallery's own Generate tab
  (`#model-flyout` → two `<mg-model-picker>` instances) and its own image picker
  (`#pick-modal` → `<mg-gallery-picker>`) via the same mount/unmount pattern, replacing the
  old hand-rolled duplicates outright rather than adding a third copy alongside them.
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
- **A remote session says so in the header.** When `_is_local_request()` is false, the
  head-nav renders `#lan-chip` ("LAN session · local-only tools hidden"), whose tooltip names
  every LOCALHOST-tier control the page is withholding — Import, Delete from PixAI, Set
  launcher icon, the destructive Panel jobs — and says to open the gallery on the serving
  machine's own localhost address to get them. It branches on `is_true_local`, the same value
  the Import button and `can_delete_cloud` already read, so it is a label on a decision the
  tier helpers have already made and gates nothing. It replaced an unreachable "read-only LAN
  view" note hung off `is_local`, which is hardcoded `True` at index()'s render call (and was
  wrong on the facts as well: a signed-in LAN session browses, generates and drives the Loom
  and Panel exactly like the owner at the keyboard).
- **"Delete from PixAI" shows its blast radius before the typed gate.** Cloud deletion is
  task-level — one selected image takes its whole batch — so `POST /api/delete-preview`
  (LOCALHOST, read-only, no network) resolves the selection through the same helper
  `/delete-tasks-bulk` itself uses and `#cloud-del-modal` renders every file that will go,
  thumbnailed and grouped by task, with the ones the user actually picked outlined and imports
  called out as local-only removals. Counts always describe the whole selection even when the
  thumbnail strip is capped (`DELETE_PREVIEW_TASK_CAP`); an unreachable preview falls back to
  the prose-only confirm rather than a dead click. The typed `DELETE` prompt and the localhost
  gate are unchanged — this makes the consequence visible, it does not replace a guard.
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
  `moonglade_gallery.py`) clamp their `max-width` to `calc(100vw - Npx)` so none of them run off a
  320px-wide screen (below their previous flat max-widths).
- **All three Job Tracker sources now log to the same `out_dir/jobs.jsonl` activity feed**:
  Control Panel actions and bulk cloud-delete (already wired), and now a bare CLI run from a
  terminal too (`--sync`, `--update`, `--generate`, `--generate-video`, plain download) — each
  gets a `cli-<uuid>` job id (mirroring `panel-`/`bulkdel-`), logged fail-soft so a logging hiccup
  can never break the actual command. A panel-spawned subprocess still logs exactly once (no
  duplicate entry) via the existing `MOONGLADE_PROGRESS=1` path.
  Every WEB generation surface registers too: the gallery's Generate/Edit/Fix/Enhance tabs, the
  shared Generate drawer, and all four of the Loom's own submit paths (per-shot video plus the
  Image / Edit / Reference tabs, which had never registered at all until 2026-07-24). Each uses
  `Jobs.register()` — registration without a second poll loop — because every one of them already
  owns a private poller that polls `/api/task-status`, the route that writes the authoritative
  terminal event.
- **A job PixAI accepts but never starts is detected and surfaced, not left spinning.**
  `generation_status()` returns `started` (false until PixAI actually assigns a worker) and
  `reason` (PixAI's own explanation, e.g. `"waiting timeout"`) alongside its original
  `{status, phase, paid_credit}`; both come from `startedAt` and `outputs` on `_GEN_STATUS`.
  An undispatched task is non-terminal for ~60 minutes, so status alone cannot tell it from
  real work. On that: the CLI poller reports a never-dispatched task honestly instead of
  claiming it is "STILL RUNNING", a terminal `cancelled` carries PixAI's reason, and the orphan
  reaper marks such a job **`stale`** — a non-terminal status the tracker already renders with
  a warning glyph, so a task that does eventually start can still resolve to done. The check is
  `started is False`, never `not started`: a status source that omits the field means *unknown*,
  and unknown must not brand every in-flight job stale. The reaper's caller passes the whole
  status dict, not `["phase"]` — sending the bare string makes the detection dead code in
  production, guarded end-to-end through `/api/jobs`.
- **The Activity tray shows that phase immediately, not only after the 30-minute sweep.**
  `/api/task-status` writes `started` into `out_dir/jobs.jsonl`, so the tray — which renders
  from `/api/jobs`, never from a poll response — draws a distinct **QUEUED** row: the same
  mascot icon with both animations stopped (`.jt-spin.jt-queued`) plus an uppercase `queued`
  pill, flipping to the ordinary spinner when a worker takes the job. `started` absent still
  means *unknown* and keeps the plain spinner, so Control Panel / CLI / delete / import rows
  and any job logged before this are untouched. Written once per phase change (four pollers ask
  every 3s; a per-poll write would bloat the log and keep refreshing the `ts` the orphan
  sweep's age check reads), and the in-process de-dupe entry is dropped at a terminal phase so
  it stays bounded by in-flight tasks. Because every submit surface's poller — the gallery's,
  both of the Loom's, and `mg-generate-drawer.js`'s — calls that one route, the signal reaches
  both trays with no per-host wiring; `tests/test_render_harness.py` measures the rendered
  result on `/` and `/loom` and asserts they are identical.
  Alongside it, `queue_wait_estimate()` reads PixAI's own pre-submit queue estimate
  (`GET /v2/task/wait-time`, params `priority` + `modelVersionId` — a submit's `modelId` is a
  model *version* id to that route; `priority` is a validated enum, 500/1000) and the tray
  records it once, when a job is first seen queued, showing `est. Ns wait` and
  `Est. wait · Ns (PixAI, when queued)` in the detail popover beneath the live Time Spent.
  There is deliberately **no** percentage, progress bar or countdown for a PixAI generation:
  PixAI exposes no progress on a task (probed with a control — no `progress`/`percent`/`step`/
  `eta`/`queuePosition` fields exist), the estimate is never recomputed as the wait grows, and
  it disappears once the job starts rather than becoming an implied render ETA.
- **The Fix sub-tab is priced, named and labelled like the rest of the suite** (2026-07-25).
  A Fix submits as `{mediaId, boxes}` over `POST /v2/task/fixer`, but PixAI turns that into a
  `taskKind=chat` generation carrying a `chat.fixer` block — which `/v2/task-price` prices
  (measured flat 8,000, invariant to box count, canvas size and priority; without the chat
  block the same call returns the 1,200 base floor). So the tab carries an `<mg-cost-badge>`
  fed by `/api/price` `mode:'fix'` → `build_fixer_price_parameters`, with the number fetched
  rather than hardcoded, `no_card` forced on (there is no `kaisuukenId` field on
  `/v2/task/fixer`, so no free card can ever cover a Fix), and the `window.confirm()` kept as
  a genuine spend gate that quotes the badge. Output naming and metadata match: a Fix is named
  `<source-prompt>_fix-face_<task>_<media>` from the SOURCE image rather than from the fixed
  template prompt PixAI writes into every fixer task, and its Model resolves to "Reference
  Pro" via `EDIT_MODELS` while Seed/Steps/Sampler/CFG stay empty — a chat task records none of
  them, and an em-dash is the honest answer. Naming applies to new output only.

- **The Generate drawer's Edit ▸ Enhance sub-tab is the art-filters surface — twelve filters,
  free and offline, and the panel is a side-by-side comparison.** Art filters are gradient-overlay
  recipes composited in the browser: no Generate button, no price. `static/mg-art-filters.js`
  holds **two sets**. `FILTERS` is PixAI's seven, baked verbatim from their public unauthenticated
  config endpoint (`GET https://api.pixai.art/config/imageArtFilters`, verified 2026-07-25) and
  kept verbatim so refreshing it stays a paste. `MOONGLADE_FILTERS` is **ours** — Moonglade,
  Nightfallen, Moonlit Silver, Embercourt, Verdant Grove — derived from the five skin palettes,
  each recipe built from its skin's accent and lead colours and tagged with the `skin` it came
  from; `tests/..` pins every stop colour to a real token of that skin's CSS block, so a retint
  that leaves its filter behind fails by name. Ours use **only** the six exactly-mapping blend
  modes and carry **no** `image_parameters`, so their export is their preview and what shipped is
  what was approved as swatches. `get()`/`list()` walk both; `groups()` returns
  `[{source,label,ids}]`, ours first, and drives the rail's two headed sections.

  Rendering is client-side either way: CSS `mix-blend-mode` overlays for the live preview, one
  canvas gradient fill per layer for the export, both pinned to the same gradient geometry so they
  agree. Picking a filter makes **zero** network requests (measured). The working surface is
  `#filters-flyout`, a top-level fixed panel placed by `Gen.placeFilters()` on the `_place()` rule
  (side with room, then clamp) — beside the drawer in the left/right docks, centred over it
  otherwise, and centred too whenever the side room is under `AF_MIN_SIDE` (1050px), which is set
  by the width at which both pictures are still worth judging rather than by what merely fits.
  Its three columns are **original | filtered preview | swatch rail**, `align-items:stretch` with
  `flex:1` frames so the pictures are matted and centred instead of stranded above a void, and the
  original is a **second `<img>`** — sharing one would filter both and leave nothing to compare.
  Actions: `No filter`, `Save to library` (bakes at full resolution, posts to `/api/import-local`,
  lands in `imported/` with a thumbnail and a `source='local'` row), `Send to image gen`
  (`Gen.filterSend()` — composite → `/api/upload`, the free S3 handshake → `media_id` → Edit
  source; spends nothing, the generation you then run is the priced step), and `Publish`, disabled
  until Epic C.

  Six of the eight blend modes map exactly to CSS/canvas; `darker-color` and `lighter-color` are
  Photoshop whole-colour comparisons with no CSS equivalent, approximated by `darken`/`lighten`
  and flagged `exact:false` in `BLEND_MODE_MAP` with the reason — which is why PixAI's M1/M2/M5/M6
  can differ slightly from their own render and none of ours can. The paid path
  (`build_filter_parameters`, `--filter-id`, `--enhance`, `run_enhance`) is gone: it charged
  credits and waited on a worker queue for a handful of gradient fills.
- **The QUEUED phase + queue ETA are VERIFIED against a live generation** (2026-07-25, task
  `2037959839192719439`). `/v2/task/wait-time` is real and per-priority: probed at
  Tsubaki.2 v1, priority 500 answered 34.8s twice while 1000 answered 30.8s then 26.7s. On
  the generation itself the tracker quoted **21s** and the job log's own timestamps put the
  actual queue wait at **26.7s** (`started:false` 1785036905.86 -> `started:true`
  1785036932.58), then 82s of rendering. So the estimate is sound and honestly labelled as a
  WAIT, not a countdown; the earlier "both gens said 3 seconds" was a genuinely short queue,
  not a constant. The one real defect the run exposed — an in-flight card reading
  "Generated" — is fixed. Wave 2's last item is closed.
- **No mutation that spends or changes the account can be retried** (2026-07-26).
  `gql_mutate()` is the one way a mutation goes out: it hard-codes `retries=0` and takes no
  retries argument, so the unsafe value cannot be asked for. `submit_generation` (and with
  it every web generate/edit route), the CLI's `run_generate_video` /
  `run_reference_video` / `run_edit_image`, `upload_media` and `delete_batch_media_gql` all
  ride it. Before this, only the delete passed `retries=0` by hand and every spending path
  inherited `gql_adhoc`'s three retries — so a lost RESPONSE (read timeout, dropped
  connection, a proxy's 502 *after* PixAI already created and charged for the task) made the
  retry submit and pay for a second generation. `gql_adhoc`'s own default is now
  document-aware as a backstop (0 for a mutation, 3 for a query). The REST spend paths
  (`submit_fixer`, `claim_reward` over `_rest_post`) were already single-attempt and are now
  pinned as such. Guarded by `tests/test_spend_no_retry.py`.
- **Per-image cloud delete shipped** (2026-07-25). `POST /api/delete-image` (LOCALHOST)
  drives `core.delete_batch_media_gql` — `updateGenerationTask(id, input:{deleteBatchMedia:
  {mediaId}})`, single attempt. The detail page carries both paths, worded apart: **Delete locally** (quarantine to
  `_deleted/`, recoverable, a later sync restores it) and **Delete from PixAI** (irreversible,
  names the surviving sibling count from `_batch_sibling_count`, typed `DELETE`). Cloud call
  first, local purge only on a clean return — the reverse would leave a catalog hole for an
  image PixAI still has. Button hidden for a local import (no PixAI task) and for a LAN
  session.
- **The library folder is settable again, from the Control Panel** (2026-07-25). It stopped
  being settable when the PySide6 GUI was removed in v2.1.0 and nothing replaced its folder
  picker. `resolve_library_dir()` in `moonglade_gallery.py` is the order of precedence: an
  explicit `--out`, then `config.json`'s `LIBRARY_DIR`, then `pixai_backup`. `--out`'s argparse
  default is now `None` — argparse cannot distinguish "typed the default" from "typed
  nothing" — and **`Serve Gallery.pyw` no longer hardcodes `--out pixai_backup`**, which it
  always passed and which made any stored setting permanently unreachable; `serve.txt` still
  appends, so an explicit `--out` there deliberately pins that launcher. `/api/library-path`
  is GET=LOGIN (host path withheld from non-local, as `/panel` already does) / POST=LOCALHOST
  (it rewrites config.json). It validates before writing, asks before creating a missing
  folder, refuses a path that is a file, and **never moves, copies or deletes anything** —
  pinned by a test that greps the handler for `shutil.move`/`copytree`/`rename`/`unlink`.
- **Upscale lives on the image view; the drawer keeps only the Enhance Details booster**
  (2026-07-25). PixAI invokes Upscale on a picture that already exists, so the drawer's old
  three-way Off/Upscale/Hires segment is gone — it was not where PixAI offers it, and a drawer
  has no source, so the ratio cap and predicted output size were derived from the size the
  generation was about to be. `static/mg-upscale-panel.js` (`<mg-upscale-panel>`) is the
  surface: a full inline panel on the detail page, and a flyout in the lightbox (z-index 320,
  above `.lb`'s 300, and the overlay stays open behind it) closed by `closeLightbox`/`lbStep`
  so it can never outlive the picture it was opened for. Both methods with PixAI's own control
  asymmetry — `enlarge` + `enlargeModel` (5-option picker) vs `upscale` +
  `upscaleDenoisingStrength/Steps` — and a ratio cap derived from the SOURCE's real dimensions
  against `UPSCALE_PIXEL_CEILING`, served to the client via the `__UPSCALE_CONST__` marker
  (index + detail pages only; four other templates share `BASE_HTML`) so no second hand port
  exists. Submits through the existing `/api/price` + `/api/generate` as plain i2i
  (`ref_media_id` + `ref_strength`); there is deliberately **no** `/api/upscale`. Model is
  prefilled from the row when known, and otherwise falls back to the shared
  `<mg-model-picker>` — it never guesses, since a different model restyles the picture. New
  read-only `/api/image-meta/<media_id>` (LOGIN tier) serves the one row the lightbox needs;
  it withholds `filename` (a host-path fragment).
- PixAI's one-click **panelplugin workflows** cannot run here at all, and the surface for them is
  deleted. PixAI never assigns a worker to a panelplugin task submitted with an API key — it
  accepts it, queues it, charges it, then cancels it at ~60 minutes with `outputs.reason`
  "waiting timeout" and refunds (their own official preset ids included, while their web client
  runs the same workflow in 1-3s), so the ten one-click cards, the ComfyUI catalog search,
  `/api/enhance`, `/api/workflows`, `build_panelplugin_parameters`, `workflow_catalog` and
  `--workflow-id` were all deleted 2026-07-24. The Enhance pane says so and points at Fix. The
  Fix sub-tab is a separate box-coordinate hand/face fixer (`/api/fix` → `submit_fixer`) and works.
- **The LoRA picker now shows and enforces the account's real per-generation LoRA cap, on
  both the gallery and the Loom** (2026-07-24). `membership.privilege.{lora,freeUserLora}` —
  real data PixAI's own account API already returns — is fetched by `account_info()`
  (previously only surfaced in the `--account` CLI dashboard) and now exposed via
  `/api/account`'s `lora_cap` field, which the Loom already polls into its own `acct` state
  (no new fetch needed there). Both surfaces show a live "N / cap" count (red once over) and
  disable Generate with a clear "remove N to continue" message when exceeded — a soft
  pre-submit guard, not a hard block in the picker itself, since refusing the pick there would
  leave a card visually selected in `<mg-model-picker>`'s own multi-select state that never
  actually landed in the host's LoRA list, the same reason the old 6-LoRA cap was never
  reproduced during the O12 migration. The comparison itself (`overLoraCap`) is a shared pure
  function in `loom/src/loom-mutations.js`, mirroring the gallery's identical inline logic.
  Exact coexistence semantics of `lora` vs `freeUserLora` are unconfirmed (no live subscribed
  account available to probe from this checkout) — `lora` wins when both are present,
  mirroring the CLI's own field-check order.
- **Per-LoRA version selection, on both the gallery and the Loom** (2026-07-24). Mirrors the
  base model's own version switcher (`#gen-version`/`.lv-versel`, picker-parity-round2):
  resolving a LoRA (`mg-model-picker.js`'s `_toggleMulti`) now hits `/api/model-version`
  with `&all=1` instead of the plain single fetch, so the entry carries a full `versions`
  array (every published release), not just the silently-assumed latest. A version `<select>`
  appears on a LoRA's chip only when it actually has more than one release — the common
  single-version case renders nothing extra — and switching applies that version's own
  `version_id`/`lora_base_type`/`trigger_words` with no new network call, since the full list
  was already resolved at pick time. Shared component change, so both surfaces got the real
  version data for free; only the per-chip UI (`renderLoras()` in `moonglade_gallery.py`, the
  `imgLoras.map` chip render in `master-storyboard.jsx`) needed writing twice.
- **Capability gating on the Advanced panel (Negative prompt / Steps / CFG scale), on both
  the gallery and the Loom** (2026-07-24). `extra.compatibility` (which of these a model
  actually honors — probed live 2026-07-06, memory `pixai-model-capability-schema`, e.g.
  Tsubaki.2 ignores CFG scale entirely and runs steps FIXED at 16) and `extra.restrictions`
  (real min/max bounds) are now extracted by `_version_row_to_meta()` — previously fetched
  nowhere, so an editable control that silently did nothing was indistinguishable from one
  that worked. A field the model doesn't honor is disabled (never hidden) with a plain
  tooltip; fails open on unknown/absent data — only an explicit `false` disables anything,
  matching every other fail-open gate in this app. **Real bug caught live, not by source
  reading:** the gallery's first version only set an input's `min`/`max` when the new
  model's `restrictions` had them, so switching FROM a restricted model TO an unrestricted
  one left the field's bounds stuck at the previous model's numbers — confirmed
  reproducible, then fixed so `gateField()` always resolves min/max to either the model's
  real bounds or the field's own default. The Loom's declarative JSX never had this failure
  mode (it recomputes fresh every render) — the same class of bug an imperative DOM-mutation
  copy is prone to and a declarative one structurally can't have.
- **The picker's continuous scroll, and a real Loom-only version-dropdown bug, both found
  during the owner's first live test against his real account** (2026-07-24). Three
  findings, all confirmed against real behavior, not source reading alone:
  - **Pagination never worked, on either surface.** `has_more` had been computed correctly
    server-side since picker-parity-round2 — nothing client-side had ever read it or asked
    for a next page, and for the GraphQL path (every LoRA search, plus any base-model
    search using a category filter or "Newest" sort) there was no way to even ask: the
    query requested `pageInfo{hasNextPage}` but not `endCursor`, and accepted no `after`
    argument. Added forward Relay-cursor paging (`model_search_market_gql`'s `after`
    param) — the same Relay Connection spec this app already relies on elsewhere
    (`page_variables`'s before/last cursor paging for task history, just the reverse
    direction), not a guess. `/api/model-search` now accepts a single opaque `cursor=` the
    client just echoes back; the route decides what it means per-request (a real GraphQL
    cursor on the market path, a plain offset on the REST path) so the client never needs
    to know which path is serving it. `<mg-model-picker>`'s `.mg-grid` now has a scroll
    listener that fetches and APPENDS a next page near the bottom, sharing one URL-builder
    with the initial search so a continuation can never silently drift onto different
    filters, with its own staleness guard (a fresh search supersedes an in-flight
    continuation) and a visible "loading more…" indicator. A transient error mid-scroll
    leaves pagination state untouched rather than wedging it closed, so the next scroll
    simply retries. Live-verified end to end: two mocked pages, confirmed the grid holds
    both (not replaced), in order, with `has_more`/`cursor` updating correctly at each step.
  - **A real Loom-only bug in the base-model version-resolve guard**, confirmed by the
    owner testing the identical model on both surfaces: the gallery showed a version
    dropdown, the Loom didn't. The Loom's resolve-fetch updater carried an extra
    `cur.model_id === m.model_id` condition on top of the sequence-counter guard the
    Gallery's own `onBasePick` has always used alone — redundant for the "a newer pick
    superseded this one" case the counter already covers correctly, but a real liability
    for anything else that can touch `imgModel` while the fetch is in flight, silently
    dropping the entire versions/compatibility/restrictions payload with nothing visibly
    wrong. Simplified to match the Gallery's proven, simpler guard exactly.
  - **The architecture-aware LoRA sort/badge mechanism was traced end to end and found
    structurally correct** — `base-type` is set correctly on both surfaces, the server
    requests the right GraphQL fields and soft-sorts correctly, the client renders the
    `compat` badge correctly. No bug found; still needs the owner's live confirmation it's
    now visibly working, since fixing pagination changes how much of the sorted list is
    ever on screen at once to judge it by.
- **Two performance fixes, same day, after the owner reported scrolling "still slow and a
  bit choppy" and called the picker "a step backward in function" post-pagination.** Both
  are genuine performance bugs, not correctness bugs — the first round verified the
  feature worked, not that it worked *well*:
  - **The scroll listener did an unthrottled layout read on every native scroll event**
    (`scrollHeight`/`scrollTop`/`clientHeight`), on a grid whose DOM now grows on every
    load-more instead of staying capped at 24 cards forever like the old flyout did —
    exactly the shape of real scroll jank. Throttled to one check per animation frame via
    `requestAnimationFrame`, the standard fix for this class of problem.
  - **Opening the flyout fired two full searches at once, not one.** Both the Gallery's
    `ensurePickers()` and the Loom's `pickerMounted` create and mount a `kind="base"` AND a
    `kind="lora"` picker together on first open (so switching tabs never re-fetches), but
    the hidden one searched anyway — every open competed a real search against a wasted one
    for a tab nobody had asked to see. `<mg-model-picker>` now defers its own
    browse-on-open search when it starts hidden, and each host calls a new `ensureSearched()`
    the moment it actually reveals that instance — idempotent, so tab-switching still never
    re-fetches. Live-verified: exactly one search fires on open, one more the first time
    each tab is actually viewed, none on switching back.
  - The scroll-triggered load-more chain itself (native scroll event → throttled rAF →
    fetch) could not be fully exercised end-to-end in this session's sandboxed browser
    automation — synthetic `dispatchEvent('scroll')` didn't reliably reach the throttled
    callback, a known simulation gap, not a sign of a bug (`_loadMore()` itself, called
    directly, appends correctly every time). Needs the owner's real scrolling to confirm
    the choppiness is actually gone.

- **Upscale and the Generate-tab boosters are ordinary generation parameters**, built by
  `_gen_parameters` on the same t2i/i2i submit every image gen already uses. PixAI's two
  upscale methods are mutually exclusive and their radio values are the parameter names:
  *Upscale* = `enlarge` + `enlargeModel` (one of five upscaler networks), *Hires* = `upscale`
  + `upscaleDenoisingStrength`/`Steps`/`Sampler`. Boosters are `enableADetailer` (Face Fix)
  and `qualityTag` (Quality Tag). Every key is emitted **only when asked for**, so a submit
  that does not opt in is byte-identical to before. The ratio ceiling is **computed**
  (`max_upscale_ratio`, from a per-method output-pixel ceiling) because the same method
  allows a different maximum on a different source size; the drawer carries a hand port of it
  so the slider shows the live max plus `1400×784 → 1952×1096` while dragging, pinned to the
  Python by a Node parity test. CLI: `--enlarge`/`--enlarge-model`/`--upscale`/
  `--upscale-denoise`/`--upscale-denoise-steps`/`--face-fix`/`--quality-tag`.

## Achievements / The Folio of Honors

- **Renamed from "Trophy Hall" 2026-07-22** (owner's pick off the shortlist). Same
  **maximized overlay** grown from `#ach-modal` — Summary / All / Statistics tabs, main
  grid, right rail (category nav — now click-to-filter, not just scroll-to — Within Reach,
  Relics, mascot alcove), collapsible sections, search, mobile stacking. All Hall CSS is
  scoped to `.ach-hall` so the contest/art modals sharing `.ach-panel` are untouched.
- **Redesigned the same day**, from the owner's own Figma Make export (built partly from
  the legendary/feat frame slice values handed off earlier that night — confirmed
  byte-for-byte identical tier-triad colors to what the toast already shipped). The All tab
  now leads with an auto-rotating carousel showcasing the active ladder's tiers, a
  ladder-badge selector row (all 10 tracks), the selected ladder's tiers as cards, then
  every ladder grouped under a glowing pill divider, then Milestones/Masteries/Feats the
  same way. Real badge art (`/badge-thumb/<id>.png`) throughout, not placeholder images —
  each ladder's badge is its first rung's art, chosen deliberately over the top (spoiler)
  tier's. `moonglade_gallery.py`'s `ACHIEVEMENTS`/`compute_achievements()` gained `track`/
  `rung`/`rungs_total` per ladder achievement plus a top-level `ladders` list (`LADDER_TRACKS`)
  so the client can group without a second hand-maintained id→name map.
- Points are tier base + 5×(rung−1), driven by `_TIER_POINTS` (common 5 / rare 10 / epic 25 /
  legendary 50 / feat 0) and a derived `_ACH_RUNG`; feats score 0 so the total never hints at
  a hidden feat. Points render on the toast, tiles, and a Warband-style header total.
- **9-slice tier frames now wrap legendary/feat grid tiles too, not just the unlock toast**
  — the 2026-07-22 redesign's explicit answer to the open "frame the current modal cards, or
  defer" question. Same served frame assets (`/branding/frames/legendary.png` / `feat.png`)
  and slice values as the toast, applied via a `.hall-frame` overlay div rather than
  `border-image` on the card itself (the card needs its own border for the non-framed
  tiers). Adding epic is still a one-key change to the framed-tier set.
- Per-criteria checklists render on the two closed-universe set masteries (Full Toolbox =
  edit/enhance/fix; Master of the Loom = i2v/flf/r2v) via `_ACH_CRITERIA` /
  `achievement_criteria`. Open-ended sets stay count-only.
- `achievements.json` carries `earned_at:{id:iso}` for earned ids only (no hidden-feat leak),
  fail-soft; `/badge-thumb/<id>.png` serves lazy ~256px copies into `branding/_thumbs`.
- Masked feats show the cloaked-Nel art in full color (not grayscaled); name and description
  stay masked server-side.
- The canonical roster is `docs/achievements_roster_57.json`: 57 achievements, `art_candidate`
  assigned on every one. Badge and mascot art serves from the D: branding tree
  (`D:\Moonglade Athenaeum\pixai_backup\branding\`); the pre-57 badge originals are preserved
  unserved in `badges\_pre57_backup\`.
- **Real layout bug, found and fixed same day (`34f2078`):** `#ach-grid` still carried its
  pre-redesign `class="ach-grid"`, whose CSS forced `display:grid;grid-template-columns:
  repeat(auto-fill,minmax(216px,1fr))` — correct for the OLD layout where every direct child
  was one ~216px tile, wrong for the new one where every direct child is a full-width section
  (the carousel, the ladder row, each `.hall-block`). Auto-placed those sections into narrow
  tiled columns instead of stacking them — the owner caught it on the live D: install as a
  scrambled, overlapping render. Fixed to `display:flex;flex-direction:column`. Also removed
  ~30 CSS rules (`.ach-card`/`.ach-sect`/`.ach-bar`/`.ach-crit`/`.ach-roast` + tier variants)
  confirmed to have zero producers left in the new render code — dead scaffolding that encoded
  the exact wrong mental model that caused the bug. **Lesson, already added to memory:**
  verification that checks individual elements (text content, one element's computed style) in
  isolation can be 100% green while cross-element GEOMETRY is broken — this needs
  `getBoundingClientRect()` comparisons between siblings, or a real screenshot, neither of
  which ran before this shipped the first time (screenshot capture was unavailable all
  session).

### ⚠️ OPEN — roast text (flavor commentary) may be leaking uncensored/"spicy" lines it
shouldn't. Owner-reported 2026-07-22, immediately after the layout fix above, from the live
D: install. **Deliberately NOT investigated further or fixed tonight — owner wants to look
himself first, and has flagged this for the actual design pass, not a quick patch.** What's
on record so far, from a read-only code check (no changes made):
- The gating as written: server-side, `roast_nsfw` is blanked to `""` for every achievement
  unless the **Triggered** feat (poke the narrator until it snaps) is earned on that account
  (`api_achievements()`, `moonglade_gallery.py` — `unleashed = any(a["id"]=="triggered" and
  a["earned"] ...)`). Client-side, `card()` (`static/mg-notify.js`) shows exactly ONE roast
  string per card — `roast_nsfw` only if BOTH the server sent a non-empty one AND the local
  "Unleash the AI" checkbox (`Ach.setUnleash`, a `localStorage` preference, separate from the
  server flag) is checked. On paper this reads as correctly gated, and neither of those two
  checks was touched by tonight's redesign or the layout fix.
- Two live possibilities, NOT distinguished yet: (a) a genuine gating bug somewhere in this
  chain; (b) the owner's report describes what was on screen while the layout bug above was
  still live — two different cards' (or the same card's two renderings, since ladder tiers
  render once in the active-ladder grid AND again in "All Ladder Tiers") text visually
  overlapping could easily read as "two flavors shown for one achievement" without any
  roast-logic bug at all.
- **Update, same day, after the layout fix shipped:** the owner earned Triggered live (real
  play, screenshot in hand) — `unleash_available` genuinely flips true, the toggle appears,
  and the celebration toast fired. Claude read the toast text back against the achievement's
  own `roast` field and it was an exact, word-for-word match — reported that as "expected:
  the toggle just hasn't been checked yet." **The owner said this explanation is incorrect.**
  What's specifically wrong about it was not established — do not reuse Claude's toggle
  theory as a starting point next time without re-deriving it. Owner wants to compare the
  `roast` and `roast_nsfw` fields for himself (both sit side by side per-achievement in
  `moonglade_gallery.py`'s `ACHIEVEMENTS` list, easy to diff directly) on his work machine before
  deciding anything.
- **Do not resume work on this without the owner's go** — explicit scope boundary he set.

## Public repo / community

- **CI** (`.github/workflows/tests.yml`) runs both suites on every push and pull request: the
  Python suite (`--ignore=tests/test_similar.py`, no `pixeltable` installed — no test imports
  it) and the Loom's `node --test` after an esbuild rebuild.
- **`tests/test_render_harness.py` asserts that the CSS renders, not that it exists** — a real
  chromium (playwright) against the real app on a real ephemeral port, guarding the picker
  grid's panel fill, `#model-flyout`'s viewport containment, Deep Focus's veil-over-FAB
  stacking outcome, and per-skin re-tint plus pre-paint application; it skips cleanly without
  playwright or a browser binary, which is why it currently skips in CI and runs locally.
- **`tests/csshelp.py` covers the one axis the harness can't reach in CI.** Because the harness
  skips where no playwright is installed — which is every CI run today — a cascade regression
  could land on `loom-v2` unseen. This resolves which declaration actually *wins* (`!important`,
  specificity, document order) from the served HTML in pure stdlib, no browser, so it runs
  everywhere; `test_portrait_mobile_drawer_rules_actually_win` asserts on it. Strictly weaker
  than the harness (it proves the winner, not the pixels) and explicitly not a reason to skip
  writing a rendering test.
- **`CONTRIBUTING.md`** covers setup, running tests, the invariants that matter most to an
  outside contributor (`media_id` resolution, catalog-schema three-place changes, never
  committing `config.json`), PR expectations, and a private channel for security reports.
- **`READ_ONLY` in `config.json`** refuses every account-mutating call outright — submitting a
  generation, submitting a hand/face fix, deleting a task, claiming a reward — from the CLI or
  the web app, and regardless of `--confirm`/`--apply`/`--yes`. The four choke points
  (`submit_generation`, `submit_fixer`, `delete_task_gql`, `claim_reward`) are the only places
  every generate/edit/fix/delete/claim path funnels through, CLI and web alike, so
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
  fresh clone at all: `moonglade_gallery.py`'s CLI entry point used to `sys.exit` outright when
  the (git-ignored) output folder or `catalog.db` didn't exist yet — a console error before
  Flask ever started, with no page for the wizard to render on. It now creates the folder and
  an empty, schema-initialized catalog and boots normally instead.

---

## Access & accounts

The gallery is **default-deny**. One `@app.before_request` hook (`_enforce_front_door()`)
gates every route; the public surface is exactly four things — `/login`, `/logout`,
`/branding/` (static cosmetic art the login page itself needs), and `/manifest.webmanifest`
(a compile-time constant the browser fetches unprompted from the login page). There is **no
localhost bypass**: login is required from `127.0.0.1` exactly as from a LAN address.

Spend-capable routes are **LOGIN**, not localhost — `/api/generate`, `/api/edit`, `/api/fix`
and `/api/loom/generate` are all reachable by any signed-in session, which is deliberate (the
tablet generates). LOCALHOST is reserved for writes to the
server's own disk, credential writes, and irreversible cloud deletion. `tests/test_route_tiers.py`
is the authority.

**Three tiers.** PUBLIC (the four above) · LOGIN (everything else — any signed-in session,
local or LAN; this is what makes tablet generation work) · LOCALHOST (a signed-in session
*and* a loopback address). `tests/test_route_tiers.py`'s `ROUTE_TIERS` is the authority for
which routes are LOCALHOST — read it from there rather than trust this prose if the two ever
disagree (a hardcoded count here has drifted twice already, so there is deliberately no
number). Each one acts on the server's own files, mints a new account, or deletes
irreversibly from PixAI: `api_panel_run` (destructive actions only), `api_panel_cancel`,
`api_panel_schedule` POST, `api_setup_save_key`, `api_branding_shortcut`,
`delete_tasks_bulk`, `api_delete_preview`, `api_import_local`, `api_users_add`,
`api_trash_delete_forever`, `api_trash_empty`. `api_delete_preview` is the one that reads
rather than writes: it is declared at the tier of the action it previews (step one of
`delete_tasks_bulk`'s own flow, called from nowhere else), not of the catalog rows it
returns. `/api/server/stop` and `/restart` are deliberately LOGIN, by owner decision.

`api_users_remove` doesn't fit either bucket cleanly and is declared LOGIN with a nuance
the tier table can't express structurally: removing your OWN account is allowed from any
signed-in session (it can only harm the caller), removing anyone ELSE's is refused unless
the request is local — enforced inside the handler against `session["user"]`, not by tier.
Fixed 2026-07-22 after being flagged and deliberately left for the owner the day before:
previously any LAN session could remove *any* account by name (guard was only "not the
last one left"), so a borrowed-tablet guest could evict the owner and — before the
matching `api_users_add` fix — register itself a fresh, persistent login in the same
motion. Owner's explicit choice on scope: self-removal stays LAN-reachable.

The tier table is **enforced, not documented**: `tests/test_route_tiers.py` enumerates
`app.url_map`, fails any route that declares no tier, and — critically — asserts a LOCALHOST
route refuses an *authenticated non-local* session. That last assertion's absence is what let
three gate regressions ship in one week. Verified to fail when the gate is broken.

**First run** creates the first account through the login page itself, offered only to a
loopback request while zero accounts exist, so a LAN device can never claim it. Ongoing
management is **Panel → Users** — adding an account, or removing one that isn't yours, from
the server's own machine; removing your own account works from anywhere. `--add-web-user`
remains a recovery path only (it's also currently the *only* way to reset a forgotten
password — see Next).

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

- Gated on nothing, ready whenever there's capacity: further V2 shell work.

---

## Next

### Documentation debt, deliberately deferred to after the naming pass (2026-07-25)

The naming pass renames the modules these files are thick with, so updating them now would be
paying twice. Measured exposure: `wiki/Generating.md` 17 `pixai_*` references,
`docs/architecture.md` 11. What is owed, specifically:

- **`docs/architecture.md`** knows none of wave 2's surfaces. Zero mentions of
  `/api/image-meta`, `/api/delete-image`, `/api/library-path`, `static/mg-upscale-panel.js`
  or `resolve_library_dir` — so both its route table and its "Shared web components"
  section are incomplete, on top of the renames.
- **`wiki/Generating.md`** has the new Upscale section but will need every command example
  re-pointed.

Already reconciled and NOT owed: `CHANGELOG.md` (four entries that the per-wave passes had
missed were added — the two filters-panel review bugs, the delete mutation's single-attempt
enforcement, the failure-reason tally and the pool pacing), `docs/AUDIT_2026-07-21.md` (the
HIGH `upscale-boosters-are-plain-params` row still read "PARTIALLY DONE — do not close" and
"the PLACEMENT is wrong", which had become the opposite of true; closed), `wiki/Deleting.md`
(it described cloud deletion as task-level only — a safety page under-describing a live
irreversible action, so it was done despite the deferral), and this file.


### Documentation

- **The wiki backlog is closed — and branding/mascots stays deliberately undocumented there
  (owner call, 2026-07-21). Do not write that page.** The branding surface is itself a
  hidden-feat trigger field: the Konami Starfall egg, picking the *eclipse* mark animation,
  and adding a custom mark file all set feat flags (`api_ach_event`, `telem_flag` —
  `konami_triggered` / `eclipse_anim_triggered` / `branding_custom_file`), and the
  per-achievement mascot chain, reward art, and tier-SFX slots are unlock-moment surprises the
  feat system masks server-side (`api_achievements` cloaks and scrubs masked metrics). A wiki
  page inventorying marks/animations/mascots would put those spoilers in the user reading
  path. The README's one-line "make it yours" mention is the intended ceiling of public
  documentation for this surface.

### The Loom — other
- **Opt-in larger text/button scale** covering *both* the V2 shell's side panels and the
  board's `.lv-card` shot cards, as one consistent option. Desktop-only, not a responsive ask.
  The compact spec stays the default in both places. Likely a compact/comfortable toggle
  driving a CSS custom-property scale, not two maintained layouts. Revisit after the visual
  pass, not before.

### Web components (Option A migration)

Order lives in `docs/archive/SUITE_ARCHITECTURE_AUDIT_2026-07-13.md` §6.

- **The Prompt textarea still has no shared web-component home** — it stayed a plain React
  `<textarea>` rather than migrating like `<mg-generate-drawer>` did. There are now **two
  write sites for `c.prompt`**: the right panel's own Prompt field, and Deep Focus's own
  matching field (same placement in both — after Mode/Duration, before the frames), each
  clearing an active `c.promptOverride` the instant the owner types there, since typing a
  base prompt means "auto-compose from this text now." A "base" string `shotText()` keeps
  recomposing alongside every later Camera/Lighting/cast edit. The drawer's own
  composed-prompt box (`<mg-generate-drawer>`) is unrelated — it only ever writes
  `c.promptOverride`/`c.promptOverrideText` (a frozen, never-re-woven verbatim replacement,
  by that feature's own explicit design).
- `<mg-cost-badge>` now covers the drawer's `.mgd-cost` (`static/mg-generate-drawer.js`,
  shared by the gallery Video tab and the Loom's Video tab), `moonglade_gallery.py`'s Generate
  and Edit tabs, and the Loom's Image/Edit/Reference Deep Focus tabs (D-12, 2026-07-22) —
  each of those three Loom tabs kept its existing `confirmSpend`/`window.confirm()` gate
  alongside the new badge, deliberately: that dialog
  is this project's original fail-closed guardrail, built after those exact tabs used to lie
  about cost, so the badge there is an added preview, not a replacement. Still no badge:
  `generateShot`'s own `priceShot` + `window.confirm` gate for shot-level/batch video
  generation (the Loom board's per-shot/"Generate all" path, distinct from the Video Deep
  Focus tab above), and `loom/src/loom-core.js`'s aggregate summary behind the cost-to-finish
  pill.
- **`<mg-cost-badge>`'s `compact` attribute and `mg-cost` event have no production consumer
  yet — by design, not as dead code.** Both are declared public API of a deliberately
  host-agnostic component (see the file's own header comment): `compact` was built for the
  not-yet-wired cost-to-finish pill above, and `mg-cost` is precisely the DOM-level signal
  that would carry a price update across the no-build-global (`static/*.js`) <-> esbuild-module
  (`loom/*.jsx`) wall the Option-A consolidation stopped at. Do NOT delete either as unused —
  a future pass wiring the cost-to-finish pill / the D-12 architecture consolidation needs
  exactly this surface. (Audit O14/L479, confirmed still true 2026-07-24.)
- Gallery adoption of `<mg-model-picker>`/`<mg-gallery-picker>` (replacing `#model-flyout`/
  `#pick-modal`) shipped 2026-07-24 (O12/O13) — live-QA'd against a real running server. See
  the Web components note above and `CHANGELOG.md`'s `[Unreleased]` for the full detail.

### Control Panel / web parity

What's still CLI-only, tracked so the web surface stays complete:

> **Read this list before filing a "no Panel button" item.** The board has twice raised
> "maintenance commands have no Panel button", and both times the answer was already here. The
> commands below are CLI-only by DECISION, not by omission, and a recurring correction is worth
> stating once: a modifier (`--embed-metadata`, `--convert`) does not want a button, an already
> integrated step (`--faststart-videos`) does not want a second trigger, and a repair tool
> (`--backfill-meta`) actively should not have one, because a button implies you ought to press it.


- **Password reset.** The only way to reset a forgotten password today is
  `python moonglade_backup.py --add-web-user` on the server machine (it *adds or
  updates*, so re-running it for an existing username doubles as a reset — `wiki/Setup.md`
  documents this). Owner request, 2026-07-22: give this a home in the Panel's Users tab
  too, so a forgotten password doesn't require CLI access.
  **DECIDED 2026-07-26 (owner): a user may reset THEIR OWN password from anywhere; resetting
  anyone else's is an owner-machine action only.** So it splits into two paths rather than one
  trust call: self-service reset inherits the self-only carve-out `api_users_remove` already
  uses, and admin reset-for-another-user is LOCALHOST, like adding an account. That was the
  blocker on this item; it is now a build, not a question.

  Worth stating the boundary plainly because it is the kind of thing that drifts: "reset my own"
  must not accept a username parameter at all — it acts on the session's own account, so a LAN
  visitor cannot aim it at the owner's login by editing a request.
- (`--restore-orphans` and `--undo-organize` now render Panel buttons. `reconcile-deleted`
  runs via `/api/panel/run` and the scheduler but renders no button by design,
  `panel_visible: False`. `PANEL_ACTIONS` in `moonglade_gallery.py`. Still genuinely CLI-only,
  with no web route at all: `--convert-existing` (bulk-converts already-downloaded `.webp`
  files to the `--convert` format) and `--backfill-meta`/`--backfill-full-meta` (fill in
  missing catalog fields for existing rows). `--faststart-videos` is deliberately CLI-only
  for a different reason: it's a one-time remux for videos downloaded before the
  auto-faststart path shipped — every current video-acquisition path (`run_sync_videos`,
  `_download_video_task`, `run_import_local`) already calls `video_faststart()` at collect
  time, so there's nothing left for a Panel button to do going forward. Deprecated-in-place
  by owner decision — D-6, `docs/AUDIT_2026-07-21.md`.)

---

## The naming pass — decisions locked 2026-07-25

**Flat names, package folder LATER** (owner call). Rename-only; **no shims** (clean cut).

| from | to |
|---|---|
| `moonglade_backup.py` | `moonglade_backup.py` |
| `moonglade_gallery.py` | `moonglade_gallery.py` |
| `moonglade_similar.py` | `moonglade_similar.py` |
| `moonglade_logging.py` | `moonglade_logging.py` |

**There is a FOURTH module.** `moonglade_logging` (36 refs). Easy to miss — it is imported by both
main modules and earlier notes framed this as a three-module rename.

**`pixai_backup` (81 refs) is NOT renamed** — the output directory, named in every install's
config.json. See the prefix trap in the priority list below.

**Measured scope** (`python tools/name_inventory.py modules`, 2026-07-25): **941 references in
135 files** — code 430, docs 414, js 66, other 21, cfg 10. Nine are in machine-local
git-ignored files the branch cannot fix. `pixai_gui` / `pixai_gui_settings` (8) are dead
mentions of the PySide6 GUI removed in v2.1.0; sweep as encountered so they stop reading as
live modules.

**Docs split, and only one half moves with the rename:**
- **Live instructions change in the same pass**, or the release ships commands that do not
  exist: `CLAUDE.md` (43), `wiki/Backing-Up.md` (48), this file (26).
- **Historical record stays as written**: `CHANGELOG.md` (45), `docs/AUDIT_2026-07-21.md`
  (109). A v1.9 entry naming `moonglade_backup.py` is TRUE about v1.9.
- Deferred by owner call: `docs/architecture.md`, `wiki/Generating.md` (see the doc-debt
  section above).

**Verification cannot be the test suite alone.** Both renamed modules are runnable scripts;
a green suite proves imports, not the ~116 documented `python pixai_*.py` invocations, the
launcher's child command (`Serve Gallery.pyw`), or the Panel's subprocess runner
(`_cli_path`). Verify the COMMAND surface separately.

**Sequencing, 2026-07-25:** the priority list's rebase warning does not bite — `master` has
NOT diverged (`loom-v2` +85, `master` +0, fast-forwardable). So: dedicated branch off
`loom-v2` → verify → merge to `loom-v2` → `master` → tag **2.5.0**, keeping the rename in the
same release so the new commands are learned once rather than across two.

### The folder tidy (separate, later pass)
Owner's motivation for `/moonglade`, 2026-07-25: achievement and branding files sit loose in
the install root, and **"a tidy install folder says a lot and implies good design etiquette
across the suite."** A different job from renaming four modules, so it gets its own pass and
"rename-only" stays honest.

## ✅ SOLVED: app generations DO mirror to the PixAI library (live test 2026-07-26)

**Confirmed by a real submission.** One generation submitted with the owner's **browser session
JWT** instead of the API key appeared in the pixai.art generations list and **stayed there through
a refresh**. This closes the question first raised 2026-07-05 and re-raised repeatedly since:
*"app gens pop up on the website then vanish unless favourited."*

The cause was never a missing parameter. It is the **credential**, exactly as the 2026-07-11
capture concluded: a browser JWT files a generation into the account; a bare API key does not, no
matter how the request is dressed (that was tested too — API key plus browser-id header plus
pixai.art origin was accepted, created, charged, and still dropped off the feed).

### What the fix actually is
A **credential switch**, not a new feature:
- **Mirror to PixAI** → submit with the JWT. The gen lands in the library like a website gen.
- **Local only** → submit with the API key. Stays private, temp-storage media, download at once.

Both still download locally, so the redundancy the owner asked for is real either way. The
plumbing largely exists: `_make_session` already builds `Authorization: Bearer` from whatever
token it is handed and its own error text still offers the legacy `U3T + token.txt` path, and
`submit_generation` submits through `gql_mutate(session, ...)` — so handing it a JWT-authenticated
session is most of the work.

### The credential facts, measured not assumed (2026-07-26)
| what | length | life | how it is maintained |
|---|---|---|---|
| the JWT | 287 chars | **~27 days** | one paste; possibly self-renewing (see below) |
| `_udt` (= the `u3t` value) | 45 chars | **~1 hour** | **refreshed by Set-Cookie on every response** |
| `_bsid` (browser session id) | 36 chars, a UUID | ~30 min | refreshed by Set-Cookie |

**This is why the old token path felt like endless harvesting:** `U3T` is stored as a static
string in `config.json` and it has a ONE-HOUR life. It was stale almost immediately. A
`requests.Session` keeps a cookie jar, so `_udt`/`_bsid` maintain themselves — they were never
things to harvest, they were things to stop hard-coding. Note also that a read-only query
succeeded with **no `u3t` sent at all**, so it is not required for auth on that path.

Token lifetime moved from ~12 days (2026-07-11) to ~27 days (2026-07-26) — one of several signs
their site is actively changing under us.

### Apollo CSRF: the gotcha that will bite any new client code
PixAI's Apollo rejects requests it considers CSRF-able with a `BAD_REQUEST` unless one of
`x-apollo-operation-name` / `apollo-require-preflight` is present. `_make_session` already sends
**both**, which is exactly why the API-key path never hit this and a fresh probe did immediately.
Any hand-rolled request needs them.

### Renewal: ANSWERED — not header-based, and it does not matter
**Measured 2026-07-26:** there is **no `token` response header** on a mutation response, nor on a
read-only query. `Access-Control-Expose-Headers` does still list `token`, so the mechanism exists
somewhere in their own flow (login, or their near-expiry refresh), but not on any call this app
would make. **The design must not depend on it.**

That is fine, because the pain was never the JWT:
- **`U3T` was the problem.** A ~1-hour credential stored as a static string in `config.json` —
  stale within the same sitting, invisibly, with no signal. That is what "constant harvesting"
  actually was. It is fixed structurally by using a `requests.Session` cookie jar, since `_udt`
  and `_bsid` are refreshed by Set-Cookie on every response.
- **The JWT lasts ~27 days**, and its expiry is readable **locally** from its own `exp` claim with
  no network call.

So the shipped design is a **visible countdown, not silent staleness**:
1. decode the JWT's `exp` at startup (offline; the probe already does this in ~10 lines),
2. the Panel shows "PixAI mirror: N days left" beside the toggle,
3. under 5 days it becomes a warning with a paste field,
4. `_udt` / `_bsid` need no attention at all.

That is roughly 13 deliberate ten-second pastes a year, each one announced in advance — a
different category of annoyance from the invisible hourly failure the owner rejected.

**`refreshToken` is therefore NOT a dependency.** It stays an optional nicety to weigh later, on
its own merits, and remains untested on purpose: it is a credential mutation and rotation could
log the owner's browser out mid-session.

### ❌ NOT the fix, and do not re-propose it
Auto-favouriting each gen via `upsertBookmark`. Rejected by the owner 2026-07-26, and he says he
disliked it when it was first raised. Bookmarking puts things in the FAVOURITES shelf, not the
generations library — the wrong shelf. An earlier note recorded it as an agreed plan; that was
wrong and has been corrected at the source.

## BANKED for the design pass: the three free achievement slots, and Enhance Adept's replacement

**"Enhance Adept" is dead and must be retooled or retired.** Its metric computes from a counter
nothing increments any more — Enhance was deleted — so it can never be earned. It is the only
achievement in that state; all 36 metrics were checked. Its shape is *"five different X"*, epic
tier, mastery bucket, and the cleanest fix keeps the shape and changes the X.

**Recommended: "generate on five different base architectures"** (DiT.1 / DiT.2 / DiT.3 / SDXL /
SD 1.5). The enum work of 2026-07-26 is exactly what makes this measurable — the tokens are now
known and `model_id` is already stored per image, so the metric is one `COUNT(DISTINCT)`. It also
survives the rename thematically: "refinement in every register" becomes fluency in every dialect,
and it rewards breadth of craft rather than clicking something five times.

**Alternative the owner raised: five distinct art filters applied.** A direct like-for-like swap,
and filters are local and free so it is earnable without spend. Weaker for an EPIC, because it is
a clicking achievement.

**Alternative to resist for now: gate it behind the filter creator.** The best fit of the three,
but the creator is not built — and gating an epic behind an unbuilt feature is precisely how
Enhance Adept became unearnable. Move it there later if the creator ships.

### The three free slots (57 of 60 used)
- **One is earmarked for a Dungeon Crawler Carl reference.** The native hook is DESCENT — something
  that fires on reaching the true bottom (the oldest image, or the literal end of 35,000). Carl art
  already exists in the chibi library. The other DCC-native option is an achievement whose ROAST is
  written as a sponsor announcement, letting the voice do the work instead of the metric.
- **The other two should stay unspent.** The two most obvious candidates — first LoRA trained (the
  owner has two) and first generation mirrored to the PixAI library — only become meaningful once
  training and the JWT toggle are real. Minting them early repeats the Enhance Adept mistake.

## DECIDED: which of PixAI's community features Moonglade gets (owner, 2026-07-26)

The whole surface is mapped -- 39 operations with hashes, from
`tools/harvest_api_surface.py`. The owner picked from that list rather than from a proposal:

| capability | verdict | note |
|---|---|---|
| **Like / react** | **YES** | `markGenerationModel` / `markArtwork` share one shape: `($id, $type, $target)`. So liking a LoRA and liking an image are ONE function with a different id, not two features. `liked` already comes back on every picker row, so this lights up a field we already fetch. |
| **Bookmark write** | **YES** | Read is shipped. Write is `upsertBookmark` + `updateBookmarkItem`, so you can bookmark from our picker instead of bouncing to their site. |
| **Follow** | **YES** | The owner's only wanted social link, and specifically because of the model-market click-through below — follow/unfollow a creator whose page you just opened. `setFollowState($userId, $target, $private)`. |
| **Publish** | **YES** | Epic C, already roadmapped. Their publish page still needs capturing; note their MOBILE app offers a Mio-powered helper that writes the description for you, which is worth seeing before we design ours. |
| **Notifications** | **YES** | `listMyNotifications`. Pairs with the training page's credit-rebate promise — it is how you would learn someone used your LoRA. |
| **Comments** | **NO, and solved differently** | There is no post/read/delete comment operation in their bundle at all — all three comment ops are *turnstile* (anti-bot) controls. So it was never optional, it was absent. The owner's answer is better than building anything: comments live on a model's MARKET PAGE, so make a selected model in the Generate panel **clickable through to that page** and their social side stays theirs. Same instinct as reusing the Loom's existing controls rather than inventing UI. |
| **Block / report** | **NO** | Moderation tools for a site we do not host. Owner: "Not going to be flagging my OWN work." |

**The click-through is the piece that makes the rest small.** With it, we never build a comment
surface, a creator feed, or a moderation queue — one link covers all three, and follow/unfollow is
the only social write we own.

## THE API SURFACE IS NOW HARVESTED WHOLESALE (`tools/harvest_api_surface.py`, 2026-07-26)

Every hand-probe uncovered another layer, so the probing stopped and the whole surface got
mined instead. **182 operations — 102 queries, 80 mutations/subscriptions — each with its full
GraphQL document, typed variables, and a sha256 hash.** Run `fetch` then `extract`; `show
--grep <word>`, `doc <op>` and `diff` read the result. Output lands in git-ignored
`private/harvest/`.

### What was measured, replacing what was assumed
- **PixAI is NOT a Next.js app.** It is React Router bundled with Rolldown. Two attempts inside
  this tool failed on the old assumption before anyone looked.
- **Their JS is not served from pixai.art at all** but from a VERSIONED CDN path:
  `https://cdn.pixai.art/artifacts/app-1.0.2605/assets/<name>-<HASH>.js`, referenced by
  `<link rel="modulepreload">` — 526 on the homepage alone, 868 reached by crawling imports.
  `app-1.0.2605` is a build fingerprint, so `diff` reports "they shipped a new build", not just
  "a hash moved".
- **The crawl follows imports transitively.** This is the fix for the documented scoping bug: a
  previous pass scanned "all 204 chunks on the enhancement page" and concluded a value did not
  exist, when it sat in a LAZY chunk that page never loaded.
- **The sha256 hashes are NOT in the bundle** — zero 64-hex strings across 868 chunks / 16 MB.
  Apollo computes them at runtime.
- **But the documents ARE, as pre-parsed AST literals** (`{kind:"Document",definitions:[..]}`,
  191 in one chunk), with complete field projections and typed variable definitions.

### Hashes are DERIVED, and the derivation is PROVEN
Apollo hashes the printed document, so the tool prints the AST exactly as graphql-js does and
sha256s it. Three hashes seen on real requests are baked in as an oracle; `extract` tries four
print variants and keeps only one that reproduces **all three**. Exactly one did —
`typename,no-newline` (Apollo injects `__typename` before hashing; no trailing newline). If none
passes it writes no hashes at all, because plausible-and-wrong is worse than absent.

**This is the answer to "what happens when PixAI changes their frontend."** Re-run fetch+extract
and the hashes re-pin themselves. The `Recapture procedure` in CLAUDE.md is now a fallback, not
the first move.

### Notable operations we had no idea existed
- `subscribeGeneratorPreviewEvents` — a live subscription streaming in-progress preview images
  by `taskId`. This is the mechanism behind their new generation page.
- `cancelGenerationTask`, `rerunGenerationTask`, `updateGenerationTask` — the Job Tracker
  currently cannot cancel or rerun anything.
- Bookmarks are full CRUD: `upsertBookmark`, `deleteBookmark`, `updateBookmarkItem`,
  `listMyBookmarkItems` (this is what "Manage Bookmarks" opens), `listBookmarkItems`.
- `listSimilarLoras`, `listLoraRecommendationsByModel` — their own similar/recommended LoRA
  endpoints, adjacent to our Pixeltable work.
- `createWebhook` / `listMyWebhooks` / `deleteWebhook` — webhooks, which could push events to
  us instead of us polling.
- `createAccessToken` / `listMyAccessTokens` / `revokeAccessToken`, `listMySessions` /
  `terminateSession` — API-key and session management.
- `getMyTaskStats`, `listMyQuotaLogs` (credit history), `getUserYearWrappedStats`.
- `getManga` / `getMangaChapter` / `markManga` — a manga feature we did not know they had.
- Moderation ops ship in the public bundle (`opBanUser`, `opModerationNSFW`, …). They would
  fail without permissions; do not call them.
- Payment ops exist (`intentToPay`, `cancelSubscription`, …) and stay **permanently out of
  scope** per the standing money rule.

### Safety, by construction
`fetch` and `extract` never touch api.pixai.art — static CDN files only. `replay` takes ONE
operation, refuses any mutation outright, requires an allowlist entry or explicit `--force`, and
refuses to send an unproven hash. There is deliberately **no** "replay everything" mode: calling
a harvested catalog blind could delete tasks, submit generations and spend real credits.

## CAPTURED SPEC: LoRA training (read from the page + bundle, 2026-07-26, zero credits spent)

The owner has **8 free trainings**. A paid run is **75,000 credits** — roughly 23 Hires
upscales — so the free slots are worth real money and none were spent to get this.

`createTrainingTask` is in the harvest with its hash and return projection. Input types live in
the schema, not the document, so the inner field names came from the training page's own chunk
(`_app.train-lora-main-*.js`), where the form assembles the object:

    CreateTrainingTaskInput {
      baseModelId          required
      mediaIds             the dataset
      title                required, length >= 1
      type                 UserMultiLora  (matches the USER_MULTI_LORA seen on his own LoRAs)
      triggerWords
      primaryLoraModelId   set when retraining FROM an existing LoRA
      trainingTaskId       set when reusing a previous dataset
      category
      kaisuukenId          ** the free card **
    }

**`kaisuukenId` is the headline.** The free trainings are kaisuuken cards — the same mechanism
`_apply_kaisuuken` already implements for image generation. Our existing free-card path applies
directly rather than needing a new one.

**Validation rules, read off their code (not inferred):**
- `mediaIds` under 10 is rejected **unless `trainingTaskId` is set** — reusing a dataset waives
  the ten-image minimum.
- Max 100 images, and submit is blocked while any image is still uploading.
- `triggerWords`: empty rejected; over 256 rejected; and **under 30 characters rejected when the
  model type is MMDIT26** — that is the "Tsubaki.2 needs a 30-character trigger word" rule,
  enforced per architecture.
- Three price tiers, in their own precedence order: free-to-train → 0; `datasetId` present →
  `prices.reuse`; `primaryLoraModelId` present → `prices.retrain`; otherwise `prices.price`.
- Failure returns `INSUFFICIENT_BALANCE`; success returns `refId`, the new model's id, and the
  site navigates to `/model/<refId>`.

**From the page itself:** Model Type on the TRAINING page is DiT.2 (NEW) / DiT.1 / SDXL /
Other… — note **DiT.3 is absent here though it appears in the generate picker**, so DiT.3 is
generate-only for now, which is part of why its enum never got captured. Model Theme offers
Illustrious-v1.0, NoobAI XL, Hinata v2, Illustrious-v0.1 and more. Dataset sources are upload,
**import from generation history**, or reuse a previous dataset. Rebates go up to 5% of credits
when others generate with your LoRA. Membership grants 3/5/10 free trainings a month for
Starter/Plus/Premium.

**Their category dropdown is currently rendering raw i18n keys** (`market:lora-categories.*`),
a live bug on their side, which handed over the canonical list: character, animal, style,
realistic, pose, clothing, background, detail, other. That confirms our `MARKET_CATEGORIES` is
missing **animal** and **realistic**.

**Still not obtainable without a real run:** whether the submit is accepted from an API key.
That is the same question panelplugin failed, and it cannot be answered by reading — only by
submitting. Do not build a training feature as though it is settled.

## CAPTURED SPEC: PixAI's model + LoRA pickers (live capture 2026-07-25)

Read off the running site with the owner driving Chrome, plus a network capture of the picker's
own calls. Every value here is measured, not inferred. This settles the long-open
"bookmarked LoRA" question that `private/API_OPERATIONS.md` and a 2026-07-04 recon flatly
contradicted each other about.

### The two operations, solved

**BOOKMARK tab** — a persisted query, its own operation:

    operation / operationName : listMyBookmarkedGenerationModels
    variables                 : {modelTypes: ["ANY_LORA"],
                                 loraBaseModelTypes: ["MMDIT26A_MODEL"],
                                 first: 36}
    persistedQuery sha256Hash : 2281653492ff54ef17707104736fd74e7a8d70dc314e024e595f0e71ff2945b9

**MY LORA tab** — NOT a separate operation. The ordinary list, filtered by author:

    operation / operationName : listGenerationModels
    variables                 : {last: 36, types: ["ANY_LORA"], feed: "trending",
                                 loraBaseModelTypes: ["MMDIT26A_MODEL"],
                                 authorId: "<the signed-in user's own id>"}
    persistedQuery sha256Hash : b7a2d663bc0381dd6eb26f8c68f702cb928bea720982f6f5553ea1629a8e871d

Note the argument names DIFFER between the two and must not be assumed shared: bookmarks take
`modelTypes` + `first`, the list takes `types` + `last` + `feed`. `feed` is how the sort is
expressed (`"trending"` for Trending).

### Why our ad-hoc probe said both were ABSENT
`listMyBookmarkedGenerationModels` probed as *"Cannot query field ... on type Query"* over
`gql_adhoc`, yet the website calls it successfully. It is reachable **only through the
persisted-query path** (operation name + sha256Hash + u3t), the same mechanism this repo
already uses for the listing and task-detail operations — not through an ad-hoc POST document.
So the contradiction in the private docs was not an error in either: the op is real AND absent
from the ad-hoc Query root.

**A heuristic that looked clever and was WRONG, recorded so it is not trusted again.** PixAI
redacts the content of GraphQL's "Did you mean ...?" hint but not its existence, so a probe was
built treating "absent, but a hint fired" as a near-miss. Two invented names produced hints; the
REAL name produced none. Driving the browser answered in three clicks what the probe had
actively misled us about. For a surface the website itself uses, capture the request — do not
probe the schema.

### GO/NO-GO: both operations WORK with our own API key (measured 2026-07-25)
Called with the captured hashes over the persisted-GET path using the owner's API key rather
than a browser `u3t` session. **HTTP 200, real data, both of them.** This was the one thing
that could have killed the feature: `listMyBookmarkedGenerationModels` is absent from the
ad-hoc Query root, so the persisted path is the only door, and panelplugin had already taught
us that a door the website walks through can be shut to an API key. It is not shut here.
`totalCount: 3` came back for MY LORA, matching the three LoRAs in his picker.

**Do not re-litigate this.** It is measured, not inferred.

### Response projection (what a picker can render)
`generationModels { edges { node {...} cursor } pageInfo {...} totalCount }` — a standard Relay
connection. On each `node`:

    id  authorId  title  mediaId  createdAt  updatedAt
    type                 e.g. USER_MULTI_LORA for the owner's own LoRAs
    category             e.g. "character" (mirrors the LoRA-category filter)
    loraBaseModelTypes   [..]  the architecture list we already gate on
    isNsfw  isDownloadable  isPrivate  visibilityType  permittedUse  userPermission
    likedCount  liked  refCount  commentCount
    flag { shouldBlur }
    media { id type width height imageType urls[{variant,url}] flag{shouldBlur} ... }
    extra { baseModelId description triggerWords category isRealistic isSensitive
            isEarlyAccess accessRoleList archived archivedByPicture
            permissions { personalUses commercialUses shareImagesOnline shouldCreditAuthor }
            nsfwPredict { porn sexy hentai neutral drawings }
            censorSensitiveFlag  recognizedNsfw  sensitiveKeywords[..]  ... }

`pageInfo { hasNextPage hasPreviousPage startCursor endCursor }` plus `totalCount`, and a
`cursor` on every edge.

**Four things this answers that were open:**
- **`refCount` is the number printed on each card.** The picker's "184" is refCount (uses), not
  likes — `likedCount` was 0 on the same row. Our own grid labels that figure; check it matches.
- **`extra.permissions` is the data behind their License Type filter.**
  `commercialUses` is what "Allows Commercial Use" filters on. We have no such filter and now
  know exactly what it would read.
- **`type: USER_MULTI_LORA`** is the token for a user's own LoRA. `LORA_BASE_MODEL_TYPES`'s
  comment already notes MULTI_LORA is "a LoRA's OWN type"; USER_MULTI_LORA is the variant the
  owner's trained models carry.
- **`extra.censorSensitiveFlag` / `archivedByPicture` most likely explain the grey "No Cover"
  tiles** in the picker screenshots — a model whose cover art was moderation-rejected still
  lists, with no usable thumbnail. Worth confirming before our grid renders a broken image
  where PixAI renders a placeholder.

### Still uncaptured after this pass
- The `feed` tokens for the other three sorts (only `"trending"` seen; Most Liked / Most Used /
  Latest unknown).
- The cursor ARGUMENT names for paging (`pageInfo` gives cursors back; whether the request
  takes `after`/`before` alongside `first`/`last` was not exercised).
- **DiT.3's enum token** — see the hole in the LoRA weight-range table below. Same technique
  fixes it: select a DiT.3 base in the picker and read the `loraBaseModelTypes` it sends.

### Architecture mapping, one confirmed
**`MMDIT26A_MODEL` = DiT.2** (the picker sent it while Tsubaki.2 was the selected base). Their
Model Type filter offers **All / DiT.3 / DiT.2 / DiT.1 / SDXL / Community DiT / SD 1.5**, so
**DiT.3 is a real type we have no enum for** — `LORA_BASE_MODEL_TYPES` carries five values and
the owner's LoRA-weight ranges (DiT 0..1.2, SD -2..+2) never mentioned DiT.3 either. Treat the
weight-range table as having a known hole until DiT.3's enum and range are captured the same way.

### Filter vocabulary, read off the UI
| picker | control | values |
|---|---|---|
| base model | tabs | PRESET · MARKET · BOOKMARK |
| base model | sort (MARKET) | Trending · Most Liked · Most Used · Latest |
| base model | sort (BOOKMARK) | Oldest · Latest **only** |
| base model | Model Type | All · DiT.3 · DiT.2 · DiT.1 · SDXL · Community DiT · SD 1.5 |
| base model | Posted at | All Time · Yesterday · Past 7 Days · Past 30 Days |
| base model | License Type | All · Allows Commercial Use |
| LoRA | tabs | MARKET · BOOKMARK · MY LORA |
| LoRA | sort (MARKET) | Trending · Most Liked · Most Used · Latest |
| LoRA | sort (BOOKMARK / MY LORA) | Latest, and **no Filters button at all** |
| LoRA | Source | All · PixAI · External |
| LoRA | LoRA category | All · Character · Animal · Style · Realistic · Pose · Clothing · Background · Detail Enhancement · Other |
| LoRA | Posted at / License Type | as base model |

### Gaps against what we ship
- **They call it `strength`; we label it "Weight."** Their selected-LoRA panel reads
  `strength (?)` with the value beside a slider. Cheap label-fidelity fix.
- **`MARKET_CATEGORIES` is short by two** — ours has 7, theirs 10: missing **Animal** and
  **Realistic** (our `detail` is presumably their *Detail Enhancement*).
- **No `Source` filter** (PixAI vs External) and **no `License Type` filter** anywhere in our
  code — zero references to either.
- **Cap is displayed as `Max Allowed: n/15`** in the form and `Selected LoRAs (n/15)` in the
  picker, corroborating the `membership.privilege.lora` work.
- **`Train your own LoRA`** is a first-class button we have no equivalent for.
- **Bookmark is also an ACTION** on the selected LoRA in the right-hand panel, and
  **`Manage Bookmarks`** appears on both bookmark tabs.
- **Incompatible LoRAs are GROUPED, not hidden**: compatible above, then a
  `Not compatible with the selected model` divider, incompatible greyed below but still listed.
  A better answer than hiding, and worth copying.
- The generator form shows **`Est. wait ~26 seconds`** beside Generate — the same queue
  estimate we shipped in the Job Tracker, in their own words.

### Still uncaptured
The strength slider's min/max labels (the handle sat at 0.7, consistent with a 0..1.2 DiT
range), what `Manage Bookmarks` opens, DiT.3's enum token, and the base-model picker's PRESET
tab (it shows no sort or filter controls). Screenshots live in
`C:\Users\gwilkins\Desktop\Screenshots for Moonglade refs` along with unread recordings
(`Model-lora picker`, `Loom issue`) and a `diagrams/` folder.

## Banked idea: package the assets like an MPQ (possible epic, NOT scoped)

Owner, 2026-07-25. **Explicitly not DRM** — his framing: *"if someone pokes around and just
reads a json file all the secrets are out. just not trying to leave breadcrumbs."* Plus the
presentation goal: a tidy install that reflects the work.

**Mechanism, best first:**
- **SQLite as the container.** One file; a table of `(path, bytes, sha256, mtime)`;
  hash-indexed random access; transactional updates; no extraction step. Behaviourally the
  closest thing to MPQ, and closer still to CASC (content-addressed). No new dependency — the
  catalog already links SQLite.
- **A zip.** Read natively by Python, servable straight from Flask. Simpler, more
  inspectable; marginally worse at many-tiny-file random access, irrelevant at this scale.
- **Not `zipapp`/`.pyz`** — bundles code, not runtime assets.

**Delivers:** a tidy install; atomic versioned distribution (one file, cannot half-install);
tamper-evidence via a signed hash manifest, so a swapped mark becomes DETECTABLE; and a
container whose format you must know rather than a folder you can browse.

**Cannot deliver, and must not be scoped as:** secrecy for displayed art. What the browser
renders, the browser has.

**The spoiler half is a SEPARATE decision, and packaging does not solve it — but something
simpler does.** `docs/achievements_roster_57.json` is **2.98 MB and committed to the public
repo**, so the whole roster is readable on GitHub and no install-folder packaging un-publishes
it. **Checked 2026-07-25: NO runtime code loads that file.** `moonglade_gallery.py:1528` only cites
it in a comment (the runtime roster is the `ACHIEVEMENTS` catalog in the module itself), and
its only reader is `tools/build_roster_board.py`, a dev-only board generator that already
accepts a `--roster` path. Owner's recollection was right: it is the build-time record from
when the 57 were designed, not a shipped asset.

So moving it to git-ignored `private/` would remove the breadcrumb from GitHub AND 2.98 MB from
the repo, at the cost of one dev tool's default path. The real price is that the canonical
design record leaves version control — it would live only on the owner's disks and needs to be
inside his own backup. That is the owner call here, and it is a SEPARATE change from the naming
pass (rename-only). (Server-side masking already works and is unaffected — unearned feats are
cloaked and their metrics scrubbed before reaching any client, which is real protection
precisely because those bytes never leave the machine.)

**Design tension to respect:** branding is DROP-IN today (a file in `out_dir/branding/` is
picked up) and "make it yours" is a shipped, intended feature. A sealed container must keep an
override layer — packaged defaults, loose files winning — or that feature dies to tidiness.

## Priority order (agreed 2026-07-19)

Ranked, with the reason each sits where it does.

1. **The naming pass** (`pixai_* → moonglade_*`) — a focused 4–6 hours;
   `python tools/name_inventory.py modules` sizes the live surface, including the machine-local
   git-ignored files (`.claude/launch.json` · `config.json` · `serve.txt` · `private/`) the
   branch can't fix and each machine must touch itself. Do it on its own branch in its own
   session, after clearing the runway — `loom-v2` currently leads `master`, and a rename that
   moves this much makes a later rebase miserable. Two traps: `moonglade_gallery` is a strict prefix
   of `moonglade_backup` **and** `pixai_backup` is the output directory named in every
   install's `config.json`, so a prefix-wildcard sweep silently repoints people's archives at
   nothing; and both modules are runnable scripts invoked as `python pixai_*.py` in ~116
   documented commands, the launchers and the Panel's subprocess runner — an import-only shim
   leaves the whole suite green while breaking every one of those.
2. **The Design Pass** (below) — one body of work, not five separate ones.

### The Design Pass (consolidated)

Grouped by owner decision 2026-07-19: these were tracked as separate items but are one
coherent visual effort and should be scoped and executed together rather than piecemeal.
**The Folio of Honors redesign (formerly listed here) shipped 2026-07-22 on its own** —
it had a finished design in hand while the other two didn't, so it went ahead rather than
waiting; the "together" grouping still applies to what's left below.

- The **Loom visual-refinement pass** — the skin system already reaches the Loom, so what
  remains is refinement rather than plumbing. Its whole palette funnels through a six-line
  alias block at the top of `master-storyboard.jsx`'s `STYLES` (`--bg`/`--panel`/`--ink`/
  `--amber`/`--cyan`/`--coral`, each one `var()` hop from a skin token), so retinting is
  editing six lines rather than auditing hundreds of rules.
  - **Deep Focus previews are too small to read what you attached** (owner, 2026-07-21).
    `.sb-frameprev` is `height:84px` and `.sb-refprev` is a `64×48` thumbnail, so a frame or
    an @tag reference is often unidentifiable at a glance. The real constraint is not those
    two rules: `.lv-df` is `width:min(640px,92vw)`, so the panel itself caps how large any
    preview can get. Treat this as "how wide should Deep Focus be, and what does it show at
    that width", not as a one-number bump.
- The **gallery search-bar redesign**, blocked on owner input.
- The **owner's layout/function note-taking pass**, which gates several deferred items.
- Epic-tier frame art, the "earned rewards" display, the toast-badge-to-home-marker motion,
  and toast tier colours vs shipped badge art each also has its own line under Open owner
  calls below — grouping them here is about execution order, not fewer decisions. (Per-tile
  ornate frames shipped with the Folio of Honors redesign, 2026-07-22 — no longer on this
  list.)

---

## Open owner calls

- **Epic-tier frame art — deferred to the Design Pass.** The owner is now on the fence about
  the whole premise: considering REMOVING the ornate per-tile frames from Legendary/Feat
  rather than adding a matching Epic one (2026-07-23). Not the "deep-purple WoW epic /
  tier-gear" direction previously banked — that's shelved pending this bigger question.
- **"Earned rewards" display — CORRECTION 2026-07-23, this is already LIVE, not TBD.**
  A previous pass (and this file, until now) wrongly carried it as an unbuilt idea. It's a
  real section in the Folio of Honors today, currently showing only **skin** unlocks. Open
  (not a shape question — a build-more question): extend it to also cover **banner** and
  **icon** unlocks, plus the easter egg (see below). Exact current render location in
  `moonglade_gallery.py` / `static/mg-notify.js` not yet re-confirmed against the
  post-Folio-of-Honors code — ask the owner to point at it directly rather than re-deriving
  from git history next time this comes up.
- **The reward system's real shape, per the owner (2026-07-23) — bigger than one banner.**
  The original design intent was a **bundle**, not an isolated flag: a qualifying achievement
  was meant to unlock a **banner + an icon/mark + a matching skin together**, and the reward
  *type* was meant to track achievement **tier** — low-tier unlocks an icon, epic-tier
  unlocks a skin, legendary-tier unlocks a banner. This tier→reward mapping was never fully
  built; **Feats (the 11-item tier in the 57-roster) grew out of this same reward-design
  thinking** — they're a byproduct of working out what each tier should give, not a
  separately-invented category. `D-8` (audit board) undersold this as "build the unlock pool
  or delete the promise" — it's actually "finish designing and building a tier-based reward
  architecture that's partially there." The 57-vs-60 gap (below) was also seeded with this in
  mind: room for ~3 more achievements was deliberately left to round out reward-tier coverage,
  still waiting on the Design Pass.
- **Owner's concrete mark (icon) decisions, 2026-07-23 — apply when the reward system is
  built:**
  - **Void Sentinel** — ships as the **default** icon (free, not achievement-gated).
  - **Gem Tome** — owner dislikes it; **remove it** from the mark roster entirely.
  - **Moonwell Eclipse** — unlocks together with the **Nightfallen** skin.
  - **Vine Crescent** — unlocks together with the **Verdant Grove** skin.
  - **Winged Crescent** — owner wants to **remake the art**; unlocks together with the
    **Ember Court** skin once remade.
  - Recurring, standing complaint (not new): **marks render too small** wherever they show in
    the app (today: the header at 42px) — the owner has said so since the beginning. Treat as
    a real sizing defect to fix alongside any mark-system work, not a taste question.
- **Reward-tier schema proposal — scoped 2026-07-24 on branch `reward-bundle-scoping`
  (shape only, not built, not populated — filling it in is the owner's creative call).**
  `docs/achievements_roster_57.json`'s `roster.achievements[]` already carries a prestige
  `tier` field (`common`/`rare`/`epic`/`legendary`/`feat`) plus two ad hoc, already-populated
  reward fields — `skin` (a skin id string, non-empty on 3 of 57) and `banner_reward` (bool,
  true on exactly 1 of 57) — so no new TIER field is needed; what's missing is a REWARD field
  distinct from prestige tier. Proposed addition, same shape on every achievement object:
  **`reward_kind`** (`none` / `icon` / `skin` / `banner` — deliberately not named
  `reward_tier` as D-8's own phrasing suggests, to avoid colliding with the existing `tier`
  field; related concepts, not the same one) plus **`reward_id`** (a string bundle/asset
  pointer, e.g. `"nightfallen"`, empty when `reward_kind` is `none`). Two achievements sharing
  one `reward_id` (say, a low-tier one and an epic one) is what expresses "these unlock
  together as one themed bundle" without forcing every bundle piece onto a single
  achievement. Optionally, a new top-level `roster.bundles[]` catalog (sibling to
  `buckets`/`tracks`) gives each theme one place to name its actual mark id / skin id / banner
  asset — today that mapping exists only as prose in this file. **Two reconciliation notes for
  whoever builds this:** (1) `moonglade_gallery.py`'s `ACHIEVEMENTS` list (`:781`) is a
  hand-transcribed runtime copy of the JSON roster, not loaded from the JSON at runtime (same
  pattern as the `LADDER_TRACKS` comment at `:1526-1530`) — any new field lands in both places
  by hand, whenever it's actually populated; (2) the existing `skin`/`banner_reward` values on
  `hoardsmith`/`reel-director`/`menagerie`/`the-great-library` predate the bundle design and
  each carry only one piece (a skin id, or a bare flag with no specific banner named) — they
  need reconciling into the new fields, not just left alongside them.
- **Reward-bundle decision ledger + gap list — scoped 2026-07-24.** Every mark/banner/skin
  pairing decided so far, compiled from D-8 (`docs/AUDIT_2026-07-21.md`) and the mark-decisions
  bullet above, cross-checked against the live code rather than re-derived from scratch:

  | Bundle theme | Mark | Skin | Banner | Status |
  |---|---|---|---|---|
  | *(default)* | Void Sentinel | — | — | ships free/ungated |
  | *(removed)* | ~~Gem Tome~~ | — | — | owner: delete from the mark roster |
  | Nightfallen | Moonwell Eclipse | Nightfallen (currently **free** — see below) | #100 | picked |
  | Verdant Grove | Vine Crescent | Verdant Grove | *(none picked yet)* | picked, no banner yet |
  | Ember Court | Winged Crescent (**art not remade yet**) | Embercourt | *(none picked yet)* | picked, blocked on art |
  | Moonlit Silver | *(none picked yet)* | Moonlit Silver | task `2030243024291694139` | picked, no mark yet |

  Plus the standalone default: **banner #62 is the current live default** (`banner.png`,
  already shipped, not tied to any achievement).

  **Open tension found while compiling, not recorded in any prior doc:** `nightfallen` and
  `moonglade` are the two skins flagged `"free": True` in `SKINS` (`moonglade_gallery.py:1512-1523`)
  — Nightfallen is not achievement-gated at all today. The Moonwell-Eclipse-unlocks-with-
  Nightfallen decision doesn't say whether Nightfallen should become gated too, or stay free
  while only its matching mark is the gated half of that bundle. Needs an explicit owner call.

  **Observation, not a decision:** the app's only 3 skin-gated achievements today are all
  epic-tier ladder rungs, and their skin ids already match 3 of the 4 bundle themes above —
  `hoardsmith`→`moonlit` (Moonlit Silver), `reel-director`→`ember` (Embercourt),
  `menagerie`→`verdant` (Verdant Grove). If the owner wants to reuse rather than reassign,
  those three are natural anchors for those three bundles' skin half; only Nightfallen has no
  existing achievement anchor at all.

  **Gap count — how many of the 57 still need a reward assignment:**

  | Bucket | Total | Carry *any* existing reward marker | Gap |
  |---|---:|---:|---:|
  | ladder | 29 | 4 — `hoardsmith`/`reel-director`/`menagerie` (a bare skin id each); `the-great-library` (the banner flag, no specific banner named) | 25 |
  | milestone | 9 | 0 | 9 |
  | mastery | 8 | 0 | 8 |
  | feat | 11 | 0 (2 carry unrelated hardcoded rewards outside this system entirely — `under-the-hood` unlocks custom branding, `triggered` unlocks the roast-toggle — see below) | 11 |

  None of the 4 "marked" achievements has a complete `reward_kind` + `reward_id` under the new
  bundle model — a bare skin id or a bare boolean isn't a bundle pointer to a specific mark or
  banner. So the honest count is **0 of 57 fully assigned under the new design, 4 partially
  (and in need of reconciling, not just extending), 53 blank**.

  **Structural constraint worth knowing before assigning:** not every ladder reaches every
  prestige tier — `vault`/`gallery`/`sweep`/`vigil` cap at 2 rungs each (never reach
  `legendary`; `vault`/`gallery` never touch `common` either), so a strict per-track "climb to
  legendary, get the banner" rule can't produce a banner for those four tracks without adding a
  rung. Milestones (9 achievements, `common`/`rare` tiers only) and Masteries (8, `rare`/`epic`
  only) never reach `legendary` at all, so a uniform `tier`→`reward_kind` rule can't produce a
  banner outside the ladder bucket either. Also open: the owner's own phrasing named
  `low→icon / epic→skin / legendary→banner` — whether `rare` counts as "low" alongside
  `common`, or wants its own `reward_kind`, isn't stated anywhere yet.

  **Ready to wire up once tiers are assigned (not built):** `compute_achievements()`
  (`moonglade_gallery.py:1759-1817`) is where `earned_skins` gets built and `banner_reward` passed
  through today — there is no equivalent mark/bundle logic yet. `SKINS` (`:1512-1524`) is the
  only existing reward-asset catalog; there is no parallel `MARKS` list gating icons to
  achievements — the marks system (`list_marks`/`load_branding`, `:1562-1620`) is purely a
  machine-local file-drop, unconditional for anyone regardless of achievement state. `docs/ART.md`
  §2 row 18 confirms the banner slot itself is singular today (`branding/banner.png`, one file,
  no pool) — building "banner defaults vs. unlock pool" is new infrastructure, not just a data
  mapping. Client-side, the reward line renders at `static/mg-notify.js:519-520` (`card()`, the
  Folio's grid tiles) and `:863-865` (`_mkMoment()`, the unlock toast's reward ribbon) — both
  read `skin`/`banner_reward` directly today and would need a third `reward_kind==='icon'`
  branch alongside once marks are wired to achievements.
- **The easter egg — CONFIRMED 2026-07-23: `under-the-hood` IS it, but its current trigger
  logic is wrong and the owner wants it rethought.** Today it fires (unlocking nothing, just
  a hidden feat) when ANY custom mark file exists in `branding/marks/` — i.e. the achievement
  requires the folder to have started EMPTY and the user to have dropped in their own art. The
  owner rejects this premise on two grounds: (1) it assumes a stranger randomly discovers an
  empty branding folder and knows to drop an image in it — an unrealistic trigger for a real
  easter egg; (2) more fundamentally, **the branding folder was never supposed to ship empty**
  — the app should ship the owner's own default marks/banner by design, so "empty folder" as
  a precondition doesn't even hold once defaults ship correctly. A prior session apparently
  argued against shipping the owner's own art using the "this is a public, not single-user,
  tool" reasoning ([[feedback_not_single_user]]) — the owner is explicit that this was a
  **misapplication**: "not single-user" is about building real security/access strength for
  real external users, not a reason to withhold the app's OWN default branding from everyone
  who downloads it. **Not decided yet, needs its own design pass:** what the egg's real
  trigger should be once defaults ship correctly (the current "empty folder" condition stops
  making sense the moment there IS a default), and how the "unlocks full custom branding"
  payoff should work when defaults are already unlocked for everyone.
  **Three trigger-redesign options, scoped 2026-07-24 (not picked — needs the owner's go):**
  1. **Non-default mark, not just any mark.** Keep the existing `list_marks()`-based detection
     (`sweep_telemetry()`, `moonglade_gallery.py:2048-2058`) but compare against a known
     shipped-default id set instead of "count ≥ 1" — fire only when a mark id absent from that
     set appears. Smallest change (still file-drop detection, still literally "you dropped in
     your own mark"), but needs the shipped defaults to be identifiable in code (today
     `marks.json` carries no "is this a shipped default" flag) — and it only answers the
     owner's objection (2) (the empty-folder precondition), not objection (1): a stranger still
     has to already know the file-drop mechanic exists before they can trigger it at all.
  2. **Visiting an internals-only surface for the first time.** The name fits an admin/
     engine-room page more literally than a file-drop — e.g. a first visit to `/panel` (if it
     turns out not to be prominently linked from the main nav) or a raw diagnostics view. Easy
     to detect (a page-view event), no shipped-defaults bookkeeping needed. Risk: the Control
     Panel is core to running the app day to day (syncs, jobs), so it may not read as "hidden"
     enough to feel like a real find — needs checking how discoverable it already is before
     this reads as an egg rather than a normal feature tour.
  3. **A genuine hidden technical action** — a devtools-console-only hook (a `window.___`
     function a curious user finds by reading the page's JS, in the spirit of the classic
     "you opened the console" web easter egg), an undocumented CLI flag, or a direct hit on an
     unlinked API route/query param. Closest to the name and the roast text ("you opened a
     door you had no business finding") and fully decoupled from the branding-defaults problem
     — no precondition about what ships in `branding/` at all. `api_ach_event()`
     (`moonglade_gallery.py:10780-10792`) already whitelists named front-end event beacons
     (`konami`/`docs`/`narrator`) into `telem_flag()` calls — a console hook could reuse that
     exact mechanism with one new event name, so this is less new infrastructure than it first
     sounds. Tradeoff: several sub-choices (console hook vs. CLI flag vs. URL param), each with
     a different discoverability profile, need picking.

  All three leave the **payoff** open too (this file's own prior wording, still true): marks
  already work for anyone regardless of achievement state today — there is no code gate an
  earned `under-the-hood` currently switches on — so whichever trigger is picked, the reward
  stays celebratory (badge, roast, the file-map pictogram art) unless the owner also wants a
  real functional gate added, which is a separate decision.
- **"Toast badge grows to its home marker" — CORRECTION 2026-07-23, this was a REAL
  regression, not an unfinished idea.** Owner: "this was actually live until the achievement
  revamp debacle... one of the lost facts." The archived note this file's prior wording was
  sourced from ("owner articulating the idea separately, AWAITING") predates that — it must
  have been built and shipped sometime after, then lost when the Hall got reworked. A
  `c877919`→`0a8da3a` Trophy Hall reformat (2026-07-14/15, reverted) is confirmed real and
  touched the adjacent "Rewards Earned" bar, but a quick pass did not turn up the specific
  grow-to-marker animation code in that commit or the later `a47ec41` Figma-ported Folio of
  Honors ship — needs either owner git-archaeology guidance or a fresh re-description, not
  further guessing.
- **Real SFX for the unlock toast — deferred to the Design Pass.** The loader ships and
  fails soft, but no `branding/sfx/` folder exists on the served tree, so the synth chime is
  the only sound that ever plays. Sources scouted: Kenney / Sonniss GDC / freesound /
  OpenGameArt (CC0), or Stable Audio Open via Pinokio; the owner has 1–2 WoW sounds.
- **Toast tier colors vs. shipped badge art — owner says resolved 2026-07-23, specifics to
  land in the Design Pass.** Which direction (realign the code's toast/rarity-pill colors to
  the shipped badges' tier scheme, or keep the code's original common/gunmetal/ruby scheme)
  wasn't restated when he called it resolved — confirm before touching the CSS.
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
---

## The audit board

**`docs/AUDIT_2026-07-21.md` is the live backlog.** A 16-lens, 33-agent audit of the code and
every scattered document, run against v2.2.0 with an adversarial reviewer per lens: 227 findings,
51 killed on refutation, ~82 surviving work items with a `file:line` each. It supersedes the
per-defect bullets below for anything it covers, and it carries what four other documents had
each been holding separately.

It is **not** archived and must not be moved to `docs/archive/` until it is empty. That is the
precise mechanism by which `SWEEP_2026-07-16.md` lost three sections of live content: archived
with work still in it, and `CLAUDE.md` makes `docs/archive/` "historical record, never current
fact", so roughly twenty items became contractually invisible until this audit went looking.

## Machine-local layout (a standing drift hazard, not a bug)

- The **live gallery server runs from the D: run-copy** (`D:\Moonglade Athenaeum\`), a separate
  `loom-v2` checkout from the C: repo, and branding art serves from
  `D:\...\pixai_backup\branding\`. The two checkouts drift: compare `git log -1` in each before
  assuming they match, and never mass-commit to "fix" the difference.
- **Art-in-progress lives at `D:\Art Scratch\`** (Badges, Icon Sheets, Chibli Sheets, the
  sorted Canva dump, Live Nel Cutouts, Nelnamara Fine Images, Banners, `logos_cut`, Stickers,
  App icon candidates, Forge, plus `make_anim_webp.bat` / `make_green_source.bat` /
  `_assemble_webp.py`). The served `D:\...\branding\` set stays live and separate.
- **Watch for stale duplicate checkouts elsewhere on this machine.** The 2026-07-17 doc
  consolidation that created this section originally carried a fourth bullet here flagging a
  stale duplicate `branding/` folder under `Desktop\pixai-gallery-backup-master` — dropped in
  that pass and never restored (found + re-verified 2026-07-24; that specific folder is
  confirmed gone now, so it isn't repeated as a live fact). The standing rule it existed to
  state still holds: if another copy of this repo or its assets turns up anywhere on disk,
  don't assume it's safe to ignore or silently delete — flag it to the owner and confirm which
  copy is actually live before touching either, same caution as the D:/C: drift above.

---

## Later epics

- **Loom tooling (banked).** Preact remains an optional later spike; Svelte and
  hand-rolled vanilla+signals are rejected for a solo-dev migration of untested code;
  canvas is not needed for the reel at this scale. Docking (Dockview / FlexLayout) stays a
  banked pick, but its precondition is closed — nothing in V2 is draggable/resizable/
  persisted, and the Timeline is a fixed drawer by design.
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
  sync. The rest of the reachable read-only community surface, scouted 2026-07-04 and never
  folded in here: per-artwork view counts (dwarf likes — 345 views vs. 4 likes on one probed
  post), lifetime task/credit/follower stats off `me{}`, the full contest catalog (now partly
  surfaced — see the recovered bullet below), a notifications/engagement feed (LIKE/FOLLOW only,
  no actor identity), and server bookmarks-to-local-collections. Two ops relevant to the
  picker-favorites item below — `listMyBookmarkedGenerationModels` / `listUserLikedGenerationModel`
  — are named as real operations in `private/API_OPERATIONS.md`, but a dated 2026-07-04 recon in
  `private/APP_OPERATIONS_FULL.md` found the equivalent surface **absent on the Query root**;
  neither doc has an actual captured response for them. This is a live contradiction, not a
  known-good op — it needs a probe before it's scoped, not an assumption in either direction.
- **Recovered from the 2026-07-16 persona sweep.** `docs/archive/SWEEP_2026-07-16.md`'s "PixAI
  power user + community member" persona bucket held live, unactioned feature requests that went
  invisible when the file was archived — the same failure the audit-board reconciliation already
  fixed once (see "The audit board" above), recurring in a section that reconciliation never
  reached. Checked against the current code 2026-07-22; still genuinely open: **credit ledger — the
  VIEW half only** (the data half shipped 2026-07-23 on branch `paid-credit-persist`: the
  `paid_credit` catalog column is written at every capture site and recoverable for old rows
  via `--backfill-full-meta --with-credit`; spend charts / cost-per-model views remain
  unbuilt); **remix from the lightbox** (load an image's full recipe — prompt/negative/
  model/LoRAs/size/seed — back into the Generate drawer; no matching code found under any name);
  **model/LoRA favorites + recents in the picker**, originally scoped local-only ("server-stored
  like Snippets") — the owner's 2026-07-22 ask wants these sourced from the user's real PixAI
  bookmarks instead, which folds this into the Epic C contradiction noted above rather than
  making it a free-standing small item; **prompt-matrix queue runs** (same prompt across models/
  LoRA-weight sweeps); **a real card-utilization digest** ("what's free today, on which model" +
  expired-unused tracking — `--cards`/`--claims` expose the raw balances this would sit on top
  of, but the digest view itself doesn't exist); **contest deadline tracking + shortlist-to-
  collection staging** (the contest catalog browser shipped since — official/community tabs,
  `/api/contests` — but staging for the future publish pipeline didn't); **metadata recovery for
  hand-made folders** (matching browser-saved PixAI files back to tasks by filename/hash).
  Already shipped and correctly dropped from this list: the first-run wizard, `CONTRIBUTING.md`,
  CI, and the `READ_ONLY` config flag. **The sweep's other two persona buckets (Loom video
  creator, gallery curator — 18 more bullets) have not had this same check yet** and carry the
  identical risk until someone does.
- **BlurHash grid placeholders** — deferred at low ROI; a small banked item, not an epic. The
  `blurhash` column exists and is populated from `extra.imageBlurHash`, but stays empty until
  `--sync-artworks` runs, covers published rows only, and needs a JS decoder that does not
  exist. Revisit if published coverage grows. (The detail-page NSFW breakdown from the same
  capture *is* surfaced.)
- **Gallery QoL backlog**, each verified absent from the code: rate/delete from inside the
  lightbox without closing it; bulk "set rating" on a selection; an unrated-only filter; export
  the current **selection** (specific picked media_ids) to CSV — a bigger surface than the
  filtered-view export, which now ships (the grid's "Export this view" link → the filter-honoring
  `/export-csv`); a random/shuffle sort; and a manual side-by-side two-image compare (distinct
  from the algorithmic Similar search).
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
- **The Folio of Honors' form factor is a maximized overlay**, not a page or route: grow the
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
| [Mobile Gallery — working port of the Figma Make mock](https://claude.ai/code/artifact/e0ce50a0-2475-48e2-adc0-efceee17d518) | The phone layout, and the pixel source for the mobile design pass. A REVIEWED port, not a raw Figma dump — its own comments record where the Figma invented things and what replaced them: the Nature/Architecture/Portrait/Abstract taxonomy does not exist in this app (media type does), model names swapped for real families,  corrected to , and Generate+Video merged into one **Create** tab with an internal Image/Video switch because the desktop drawer already works that way. 3-tab shell (Gallery/Create/Control), 5 skins, 160px stats hero, 2-column staggered grid, lightbox, and the full Control tab. | Current — direction for the mobile pass, NOT locked. Lives at git-ignored , so the artifact is the durable copy; refreshed 2026-07-26 after the naming pass rewrote its comments. **It predates a lot of shipped work** — the upscale panel, art filters, the LoRA row and its architecture-aware weights, the Job Tracker, boosters, Mode, seed, and the picker sources/filters are all absent from it — so bringing it to parity is the first job of the design pass, not something to build from as-is |
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
| [Moonglade Banners — defaults & unlocks](https://claude.ai/code/artifact/7919cec3-aec7-41d0-8efc-8fb2d0f4cdb5) | The 194-candidate banner board with the judging panel's pre-scores (top: #100 and #82 at 19/20) — NOT final picks: the owner's Default/Unlock tags saved only to the voting browser's localStorage (`mg_banner_board_v1`), never exported back. Re-open in the voting browser and Export to recover them, or re-tag. Feeds D-8 | Live |
| [Moonglade Model Deck](https://claude.ai/code/artifact/9f16f42d-2541-4dd9-935a-0f9d0f39c7c4) | Model research deck | Mirror — `docs/archive/MODEL_DECK_2026-07-11.md` is truth |

**Parked**

| Artifact | What it is | Status |
|---|---|---|
| [Badge Prompts v2](https://claude.ai/code/artifact/771f84d9-cacb-4f5c-8300-9c8575fb8431) | The badge prompt system | Mirror — live home is `docs/ART.md` §5; original in `docs/archive/badge_generation_prompts_2026-07-16.md`; parked |
| [Feat badge prompts — gunmetal](https://claude.ai/code/artifact/73372456-f09c-418c-920b-3e139988ef91) | 11 feat badge-art prompts | Parked — owner: maybe when credits allow |

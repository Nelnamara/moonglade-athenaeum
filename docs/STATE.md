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
PixAI's API, and curates the archive. Two surfaces: the CLI (`pixai_gallery_backup.py`) and
the web app (`pixai_gallery.py`). Work happens on the `loom-v2` branch; `master`'s last release
is **v2.3.0** (2026-07-23 — the Folio of Honors redesign, LoRA support + cost badges across
the Loom's Image/Edit/Reference tabs, per-account splits for the last three shared-file
stores (Toolbox presets, prompt snippets, Loom storyboards), the account-eviction gate, a
2026-07-22 sweep through the rest of the audit board's high-severity list, and two further
security fixes — Cache Storage purge on sign-out, and a host-path redaction re-spin covering
37 sites — both adversarially reviewed before shipping; full detail in `CHANGELOG.md`'s
`[2.3.0]` block). `loom-v2` and `master` are in sync as of that release — check
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
  tier's. `pixai_gallery.py`'s `ACHIEVEMENTS`/`compute_achievements()` gained `track`/
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
  (`api_achievements()`, `pixai_gallery.py` — `unleashed = any(a["id"]=="triggered" and
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
  `pixai_gallery.py`'s `ACHIEVEMENTS` list, easy to diff directly) on his work machine before
  deciding anything.
- **Do not resume work on this without the owner's go** — explicit scope boundary he set.

## Public repo / community

- **CI** (`.github/workflows/tests.yml`) runs both suites on every push and pull request: the
  Python suite (`--ignore=tests/test_similar.py`, no `pixeltable` installed — no test imports
  it) and the Loom's `node --test` after an esbuild rebuild.
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
gates every route; the public surface is exactly four things — `/login`, `/logout`,
`/branding/` (static cosmetic art the login page itself needs), and `/manifest.webmanifest`
(a compile-time constant the browser fetches unprompted from the login page). There is **no
localhost bypass**: login is required from `127.0.0.1` exactly as from a LAN address.

Spend-capable routes are **LOGIN**, not localhost — `/api/generate`, `/api/edit`,
`/api/enhance`, `/api/fix` and `/api/loom/generate` are all reachable by any signed-in
session, which is deliberate (the tablet generates). LOCALHOST is reserved for writes to the
server's own disk, credential writes, and irreversible cloud deletion. `tests/test_route_tiers.py`
is the authority.

**Three tiers.** PUBLIC (the four above) · LOGIN (everything else — any signed-in session,
local or LAN; this is what makes tablet generation work) · LOCALHOST (a signed-in session
*and* a loopback address). Eight routes are LOCALHOST — `tests/test_route_tiers.py`'s
`ROUTE_TIERS` is the authority, not this count; re-derive it from there rather than trust
this prose if the two ever disagree. Each acts on the server's own files, mints a new
account, or deletes irreversibly from PixAI: `api_panel_run` (destructive actions only),
`api_panel_cancel`, `api_panel_schedule` POST, `api_setup_save_key`,
`api_branding_shortcut`, `delete_tasks_bulk`, `api_import_local`, `api_users_add`.
`/api/server/stop` and `/restart` are deliberately LOGIN, by owner decision.

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
  shared by the gallery Video tab and the Loom's Video tab), `pixai_gallery.py`'s Generate
  and Edit tabs, the Gallery's Enhance sub-tab (`enhance-cost`, reshaped select-then-run —
  its old `window.confirm()` is gone, the badge is the only warning), and the Loom's Image/
  Edit/Reference Deep Focus tabs (D-12, 2026-07-22) — each of those three kept its existing
  `confirmSpend`/`window.confirm()` gate alongside the new badge, deliberately: that dialog
  is this project's original fail-closed guardrail, built after those exact tabs used to lie
  about cost, so the badge there is an added preview, not a replacement. Still no badge:
  `generateShot`'s own `priceShot` + `window.confirm` gate for shot-level/batch video
  generation (the Loom board's per-shot/"Generate all" path, distinct from the Video Deep
  Focus tab above), and `loom/src/loom-core.js`'s aggregate summary behind the cost-to-finish
  pill.
- Gallery adoption of `<mg-model-picker>` (replacing the working `#model-flyout`) is a later,
  live-QA'd step.

### Control Panel / web parity

What's still CLI-only, tracked so the web surface stays complete:

- **Password reset.** The only way to reset a forgotten password today is
  `python pixai_gallery_backup.py --add-web-user` on the server machine (it *adds or
  updates*, so re-running it for an existing username doubles as a reset — `wiki/Setup.md`
  documents this). Owner request, 2026-07-22: give this a home in the Panel's Users tab
  too, so a forgotten password doesn't require CLI access. Would need its own trust call
  (self-only, like `api_users_remove`'s self-removal carve-out? or LOCALHOST like adding a
  new account?) rather than inheriting one by default — not decided yet, not started.
- (`--restore-orphans` and `--undo-organize` now render Panel buttons. `reconcile-deleted`
  runs via `/api/panel/run` and the scheduler but renders no button by design,
  `panel_visible: False`. `PANEL_ACTIONS` in `pixai_gallery.py`. Still genuinely CLI-only,
  with no web route at all: `--convert-existing` (bulk-converts already-downloaded `.webp`
  files to the `--convert` format) and `--backfill-meta`/`--backfill-full-meta` (fill in
  missing catalog fields for existing rows). `--faststart-videos` is deliberately CLI-only
  for a different reason: it's a one-time remux for videos downloaded before the
  auto-faststart path shipped — every current video-acquisition path (`run_sync_videos`,
  `_download_video_task`, `run_import_local`) already calls `video_faststart()` at collect
  time, so there's nothing left for a Panel button to do going forward. Deprecated-in-place
  by owner decision — D-6, `docs/AUDIT_2026-07-21.md`.)

---

## Priority order (agreed 2026-07-19)

Ranked, with the reason each sits where it does.

1. **The naming pass** (`pixai_* → moonglade_*`) — a focused 4–6 hours;
   `python tools/name_inventory.py modules` sizes the live surface, including the machine-local
   git-ignored files (`.claude/launch.json` · `config.json` · `serve.txt` · `private/`) the
   branch can't fix and each machine must touch itself. Do it on its own branch in its own
   session, after clearing the runway — `loom-v2` currently leads `master`, and a rename that
   moves this much makes a later rebase miserable. Two traps: `pixai_gallery` is a strict prefix
   of `pixai_gallery_backup` **and** `pixai_backup` is the output directory named in every
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
  **icon** unlocks (assets already exist per the owner), plus a secret easter egg that
  unlocks full custom branding. Exact current render location in `pixai_gallery.py` /
  `static/mg-notify.js` not yet re-confirmed against the post-Folio-of-Honors code — ask the
  owner to point at it directly rather than re-deriving from git history next time this
  comes up.
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
- **File logging** has never entered any tracker, despite `CLAUDE.md` calling it "a separate,
  still-open discussion" since `-v/--verbose` shipped. It is a loose thread, not a parked
  decision: decide whether it is in scope, or drop it.

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

# Changelog

All notable changes to **Moonglade Athenaeum** — *a library against the Void.*

Format loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are
git tags. Full prose notes for tagged versions live on
[GitHub Releases](https://github.com/Nelnamara/moonglade-athenaeum/releases).

> **Maintenance note.** This file is the in-repo source of truth — **update the `[Unreleased]`
> section with every change, and cut it into a dated version block when you tag a release.**
> GitHub Releases are published through **v1.10.0** — publishing paused after **v1.6.0**, and
> **v1.8.0–v1.10.0 were back-published** on 2026-07-10 from tag messages + git history. **v1.11.0 is
> tagged but has no Release yet.** There is **no v1.7.x** (the series jumped 1.6.0 → 1.8.0).

## [Unreleased]

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
  see `docs/ROADMAP_LOOM_ACHIEVEMENTS.md` §2b. A ground-truth audit (10-agent read-only pass over the
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
  Scrub/fast-forward/rewind/split/crop remain a modest follow-on set, not yet built.
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

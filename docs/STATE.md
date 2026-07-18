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
to master. **V2 is the live storyboard surface** and has full feature parity with classic Loom;
whether to retire classic (delete its render tree and the `v2` toggle) is an open owner call —
see *Open owner calls*. The repo is public and has real external users.

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
- The top strip's **Play** button runs the sequence, disabled until a shot has a result
  (768aecf).
- The top strip's **Export** button trims + stitches every finished shot into one mp4
  (`exportCut`, shared with classic Loom unchanged), disabled until a shot has a result. The
  export-status overlay renders above V2 automatically (`.sb-seq` z-index 500 vs `.lv-overlay`
  400), same as Play's `SequencePlayer`.
- The top strip's **Generate all** button batches every not-yet-done shot (`batchGenerate`,
  shared with classic Loom unchanged), pricing every shot first so the confirm shows real
  cost + free-card coverage before anything spends. Disabled while a batch is running or the
  board is empty.
- **Deep Focus** (double-click a board card) is a maximized single-shot editor: title, mode,
  duration, both `FrameSlot`s, and per-shot **other references** (add/edit/remove image, video,
  or audio refs and their `@tags`) — the same `addRef`/`setRef`/`delRef` classic Loom's
  `CardEditor` uses, reusing its exact markup. A "Select in Generate →" button binds the shot and
  closes the modal.
- The **Timeline** is a fixed drawer with three states (hidden / slim / full), video preview
  above the scrubber, drag handle on `.lv-tlhandle`.
- **Legend** is a per-field on-demand "+ terms" popover on Camera, Lighting, Transition in and
  Transition out (`lv-termsbtn` → `togglePal`, `CAM_PALETTE` / `TRANS_PALETTE`). There is no
  Legend panel anywhere.
- **Footage** is a second tab inside the left card beside Cast & assets, not a fourth region.
- The left card widens to 560px only when the Cast tab is on Detailed density; Simple mode and
  the Footage tab stay 280px. The Generate drawer is 380px. Both side rails collapse to 52px
  icon strips.
- Detailed cast rows are fully editable (name / tag / kind / lock / remove) and share state
  with Simple mode; Simple cards dim, drop the pointer cursor, and carry an explanatory
  tooltip when no shot is selected (ba1c82e, 48ac4dd).
- **Draft generation:** all four Generate-drawer tabs (Image / Edit / Reference / Video) work
  with no shot selected, via a `__draft__` card keyed into the same gen-state dicts real shots
  use. A route-into-a-shot picker appears only in draft mode; bound-mode generation is
  unchanged (2874850).
- `ShotPreview` has a play/pause button that honors the trim range (pauses and rewinds to
  `trimIn` at the trimmed-out point) and disables hover-scrub during playback.
- Multiple named storyboards persist at `storyboard:v2:proj:<id>` with an active pointer; a
  shared `ProjectSwitcher` renders in both the classic and V2 headers.
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
  component, shared by classic and V2): Shot list (.txt), Lightweight backup (.json — project +
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
  become a bottom sheet at the same breakpoint.
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
- **A first-run wizard banner** appears on the gallery's home page for the owner only,
  gating on a fresh (not module-cached) read of `config.json` and the true unfiltered catalog
  count: no key configured → paste-a-key form; key present but zero rows → a "Sync now"
  button. Neither shows once the catalog has real rows, or for a LAN request.
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

## In flight

- **The Loom's V1 → V2 feature convergence is complete** (2026-07-17) — V2 has everything
  classic has. Classic Loom's actual retirement (deleting its render tree and the `v2` toggle)
  is the remaining step; see *Open owner calls*.
- Gated on nothing, ready whenever there's capacity: further V2 shell work, the Loom
  visual-refinement pass, and the video-control base set. Render-tree unification is parked
  (see *Later epics*) and is orthogonal to all three.

---

## Next

### The Loom — V1 → V2 gap (the only copy of this list)

**Empty.** Both retirement-blocking items the owner set on 2026-07-17 have landed in V2: Deep
Focus now carries audio cue, notes, the discreet/blur toggle, manual status-cycle, and "Copy
shot"; and V2's top strip/Cast panel now surface Export shot-list, Backup, Restore, and Import
Collection. `ImportCollection`'s `.sb-pick-ov` overlay still shares a z-index with `.lv-overlay`
(400, not a clean 500-over-400 hierarchy) rather than a bug — it relies on DOM paint order, which
holds today but is worth a live look next time that stacking area changes. Classic Loom's
retirement itself is next — see *Open owner calls*.

### The Loom — other

- **`ShotPreview` base control set:** fast-forward, rewind, split (cut a clip into two), crop.
  Play/pause and hover-scrub already ship. Explicitly not a full NLE.
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

- `<mg-cost-badge>` is the next component. Nothing exists in `static/` for it yet.
- `<mg-generate-drawer>` is what would make "same component as the gallery" literally true for
  the Loom's Generate panel. The Loom's `genImage` / `runGen` / `genEdit` / `genRef` and
  all Generate-tab chrome are hand-rolled in `master-storyboard.jsx`; `<mg-model-picker>` is
  the only thing actually shared with the gallery's drawer.
- Gallery adoption of `<mg-model-picker>` (replacing the working `#model-flyout`) is a later,
  live-QA'd step.

### Achievements

- Populate `docs/achievements_roster_57.json`'s `badge` field — most entries are blank even
  though every badge ships. A bookkeeping gap, not an art gap.
- Build a new roster board from `docs/achievements_roster_57.json`.

### Control Panel / web parity

Sequenced **ahead of** the PySide6 GUI removal so nothing CLI-only goes dark.

- No Panel buttons for `--rebuild-similar`, `--verify-dupes`, `--restore-orphans` or
  `--undo-organize`. `sync-artworks` / `sync-videos` / `reconcile-deleted` are runnable via
  `/api/panel/run` and the scheduler but render no button (`panel_visible: False`). The Audit
  button is hardcoded to `--audit --no-content` with no full-audit toggle. The Dedup button has
  no `--dedup-delete` checkbox. (`PANEL_ACTIONS` in `pixai_gallery.py`.)
- **Sync options.** "Sync now" runs a bare `--sync`. There is no web way to force a complete
  non-incremental re-walk of full history, to catalog rows without downloading files (fast
  inventory pass), or to pull a handful of tasks as a quick test. Needs its own scoping pass to
  pick the UI shape (a Panel "Advanced" section vs. per-run options).
- **Video negative prompts** are unreachable from the web drawer and the Loom.
  `build_video_parameters()` accepts a `negative` kwarg and emits `i2v["negativePrompts"]`, but
  the shared adapter `build_shot_video_params()` — used by both surfaces — has no `negative`
  parameter and threads nothing to `build_video_parameters` or
  `build_reference_video_parameters`. Fix: add the param, thread it to both call sites, add a
  UI field. Reference-video (R2V) may be a genuine API gap — its captured submit shape has no
  negative field.
- **Convert-and-download.** `/export-zip` streams selected full-res files with `ZIP_STORED` —
  no format conversion, no metadata embedding, no whole-collection scope. Decided shape: the
  catalog stays exactly as PixAI delivers it; conversion is an export-time transform only and
  never re-enters the catalog as a new row. An "embed metadata" checkbox (prompt / task-id /
  media-id into a PNG text chunk or JPEG EXIF) belongs on this same export flow — that is where
  `--embed-metadata` gets a web home, not a bulk Organize checkbox. CLI-side machinery already
  exists (`embed_metadata()`, `--embed-metadata`, `convert_image()`).
- **Web import into the catalog.** `--import-local [DIR]` is CLI-only and a blind scan-and-add
  with no preview or confirm step. No web route imports into the catalog (`/api/upload` sends a
  file to PixAI for use as a generation reference; `/api/import-task` banks a Toolbox task id).
  Wanted: a button or drag-and-drop target accepting a single file, a folder, or a zip, with a
  preview/confirm step before commit. Builds on existing conventions — the `source='local'`
  catalog tag and the `imported/` folder already exist.

### Release

- **Merge `loom-v2` → `master` with `--no-ff`.** The single act that carries the Loom V2 set,
  achievements, `CHANGELOG.md` and `LICENSE` to master. `master` has no commits that aren't
  already in `loom-v2`; merge-tree is clean.
- **Publish a GitHub Release for the newest tag** — it is the only tag without one; every
  earlier tag is released.

---

## Open owner calls

- **Retire classic Loom?** V2 has reached full feature parity with classic (see *The Loom —
  V1 → V2 gap*, now empty) — the condition the owner set for retirement is met. Not yet acted
  on: removing classic's render tree, the `v2` toggle, and the classic-only code path is a
  distinct, larger step from the parity work itself, and needs an explicit owner go before
  any of it is deleted.
- **Trophy Hall redesign** is blocked on the owner's own Figma frame. Ask for the frame URL; do
  not re-suggest the screenshot-decomposition checklist. The Figma plugin is live and
  authenticated. (`docs/DESIGN_WORKFLOW.md`.)
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
  executed** — both files are present. The GO is gated on the Panel web additions above landing
  first. A GUI/web/CLI parity matrix confirmed zero GUI-only business capability; the only
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
- **Generation Flags** (an AI QA pass) has zero code footprint and no spec. Blocked on two
  decisions: what a pass flags (anatomy / artifacts / NSFW / duplication?), and where the
  verdict lives. It is not dependency-free — numpy is not a current dep and the CLIP index
  rides heavy optional deps. It is **not** the shipped Pixeltable "Similar / more like this"
  search.
- **Mio.2** (PixAI's agent surface) is deferred pending explicit owner direction. It is
  cookie-authed — the `sk-` Bearer 401s — and the contract is bankable free from the JS bundle,
  but integration means a cookie-jar rewrite. Worth it only as a deliberate agent-UX bet. **Do
  not capture cookies without owner direction.**
- **Deleting the stale branches** needs a go-ahead. `generate-drawer`, `suite-polish` and
  `video-gen` each have zero commits not already in `loom-v2` — safe, no-data-loss deletes.
  `suite-polish` exists only locally; the other two also exist on origin. Keep
  `loom-extract-hook`: it holds the disproven single-hook extraction attempt (2321cac) as the
  documented record.
- **File logging** has never entered any tracker, despite `CLAUDE.md` calling it "a separate,
  still-open discussion" since `-v/--verbose` shipped. It is a loose thread, not a parked
  decision: decide whether it is in scope, or drop it.

---

## Known defects

- **No UI for removing an image from a collection.** The `/collection-remove` POST route exists
  with zero callers anywhere in the codebase. A real gap, not a design choice.
- **Saved-view presets are localStorage-only** (`gallery_presets`), so they do not roam between
  the home and work machines this project is already edited from.
- **`master` is missing `CHANGELOG.md` and `LICENSE`**, and master's README still points at
  five `docs/img/*.png` files that do not exist in its tree (only `docs/img/README.md` is
  there). These reach master only when `loom-v2` merges.

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

- **Render-tree unification** (merging the classic and V2 trees) is **parked, untested and
  undecided** — it has never had the rigor the state-layer probe got. Nothing may be filed
  under, deferred because of, or scoped relative to a "rebuild" umbrella. The genuinely
  unsolved part is the state↔view coupling: the shared gallery-picker DOM bridge, status writes
  mid-generation-poll, entries being per-render-derived, V2-panel-layout storage sharing,
  per-project selection reset.
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
anything done — that is `docs/DESIGN_WORKFLOW.md`'s rule, and it governs any user-visible
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
| [toast_mockup](https://claude.ai/code/artifact/335ef4e7-2459-4c99-990a-b8c5751324c3) | The unlock-moment design (the real toast is `.ach-m2`) | **LOCKED** — shipped, `077e1f0` |
| [loom_selectshot](https://claude.ai/code/artifact/0d9c4e02-200e-44f9-982c-e3add482b905) | Selected-shot interaction model | **LOCKED** — shipped in V2 |
| [Moonglade — Finalists In Action](https://claude.ai/code/artifact/b45a39a3-b6a8-4e73-9f62-e03cb390bd00) | Finalists in context: frames wrapping a real unlock, bars filling live, claim icons in the header chip | Current — pairs with `docs/ART.md` §3 (picks ledger) |
| [Timeline Drawer — Wireframe v1](https://claude.ai/code/artifact/84be1748-2c7d-4304-967c-8ac22cd37687) | Timeline drawer detail | Reference only — the Shell Mockup is the pixel source |

**Live tools & references**

| Artifact | What it is | Status |
|---|---|---|
| [The Curation Standard](https://claude.ai/code/artifact/6d6b9d2d-281e-4fd5-b1dc-7a11c599950e) | House standard for vote/selection artifacts | Mirror — `docs/CURATION_STANDARD.md` is truth |
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

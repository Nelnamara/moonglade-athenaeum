# Moonglade Athenaeum — Active Roadmap (Loom V2 + Achievements)

> Consolidated 2026-07-11 from every relevant artifact + repo doc + the live code/branch state.
> **This is the source of truth for the two active threads. Read it at session start instead of re-deriving.**
> Operating rule (owner, hard): **roadmap/notate here BEFORE building. No plowing.**
> (Far-horizon epics — the Foundry + Provider Deck — live in `docs/ROADMAP.md`. Near-term tracker: `docs/REFINEMENTS.md`.)

---

## 0. Tonight's scope + parked items

- **Focus:** Loom V2 · Achievement art. Keep it fun, not infrastructure.
- **Generation Flags → TABLED to Sunday.** Genuinely unbuilt; needs a taxonomy spec first; NOT dependency-free (numpy isn't a current dep; the CLIP index rides heavy optional deps). Least important item on the board.
- **Pixeltable** = the shipped "Similar / more like this" search. It works; it is NOT Generation Flags. Don't conflate them again.

---

## 0.4 · TROPHY HALL REGRESSION — RESOLVED (revert) + THE DESIGN WORKFLOW STANDARD (2026-07-14/15) — see `docs/DESIGN_WORKFLOW.md`

**The reformat commit `c877919` landed way off the owner's intended visual target** — cards
reorganized, the ladder-carousel mechanic itself rejected outright ("didn't even work and looked like
dogwater... not what I asked for... one of those charge-ahead sessions with no design questions"),
locked/DONE work undone without permission. **Recovery: Option A (revert) was chosen and executed
2026-07-15** — `c877919` reverted clean as `0a8da3a` on the C: repo, confirmed with a real rendered
screenshot. The reverted commit's CSS/JS is kept filed as a reference artifact only — **not** a
recommended starting point for the rebuild. **The Hall redesign itself is NOT done, but the owner
already has real Figma mocks built** (told this repeatedly this session — do not re-suggest the
screenshot-decomposition checklist, ask for the frame URL instead) for a rename+rebuild. Rename
shortlist as of 2026-07-15: The Vault Against the Void / The Folio of Honors / the owner's own "The
Ledger of the World Tree" (banner subtext: "The Pillar of the Vault"). Full incident detail, tooling
state (Figma plugin — **confirmed live and authenticated 2026-07-15**, no more one-time-OAuth
blocker; Claude Design + `DesignSync`), the two not-actually-regressions caveats (feats-cloak =
original spec; machine-local branding art), and the model-strategy guidance ALL live in
**`docs/DESIGN_WORKFLOW.md`** — read it before touching any user-visible surface. **Standing rule from this incident: no visual
build from prose alone; verify against the pixel source before calling it done.**

---

## 0.5 · Suite architecture decisions (OWNER-LOCKED 2026-07-13) — see `docs/SUITE_ARCHITECTURE_AUDIT.md`

The 5-agent front-end cohesion audit ran → `docs/SUITE_ARCHITECTURE_AUDIT.md`. Owner calls:
- **Front-end direction = OPTION A (web components), all the way.** Promote the duplicated widgets to
  framework-neutral custom elements (gallery-owned, no build step, loaded like `picker-core.js`); both the
  vanilla gallery and the React Loom mount them, natures unchanged. **Pilot = `<mg-model-picker>`** (the
  model/LoRA flyout + hover card) — which also delivers **D** (upgrades the Loom's Image-tab picker for free).
  Migration order in audit §6.
- **Loom save/load fix = DO FIRST (data-safety, independent of the web-component work).** The whole store is
  one non-atomically-written `store.json` (`_loom_save` `pixai_gallery.py:9137-9139`) → a crash mid-save can
  corrupt every board. Rework to **file-per-project + atomic `os.replace`** (idiom already at line 1620);
  thumbnails-as-media_id + import-creates-new-project as follow-ups. **Ships first.**
- **PySide6 GUI = phase out, surgically.** Owner has been slimming it as the web side grew; plan is to shrink
  it to **pure dev-tool status** and strip the redundant spend surfaces (Generate/Video/Edit clones — strictly
  worse, no cost/free-card safety). NOT a wholesale delete yet. Excluded from the cohesion migration. (Full
  deprecation later requires repointing the `Moonglade Athenaeum.pyw` launcher.)
- **"No framework" note clarified:** the real, confirmed value is **no build step / framework-neutral shared
  widgets**, NOT "no framework" (the Loom is React by design). `REFINEMENTS.md:72` reworded; stop citing it as a rule.

**✅ PILOT SHIPPED + VERIFIED LIVE (2026-07-13) — `<mg-model-picker>` (Option A step 1 = D):** framework-neutral
custom element in `static/mg-model-picker.js` (search + rich cards + hover preview; emits a `mg-pick` CustomEvent),
loaded as a plain global like `picker-core.js`, styled off the shared `DESIGN_TOKENS_CSS`, owning its own preview
(dissolves the singleton-`#model-preview` problem). Standalone `static/mg-model-picker.html` harness for isolated
verification. First adoption = the **Loom V2 Image tab** (React↔element bridge via a `ref` callback listening for
`mg-pick`), replacing the thin type-in search → **delivers D**. **Owner-verified live 2026-07-13** — both the
standalone harness AND the Loom Image tab render the rich cards + hover preview and pick correctly (`c24837c` +
CSS/CHANGELOG cleanup). Gallery adoption (replacing the working `#model-flyout`) is the LATER, live-QA'd step.
**✅ STEP 2 VERIFIED LIVE (2026-07-13) — `<mg-gallery-picker>`:** `static/mg-gallery-picker.js`, a full
"pick an image" modal wrapping the already-shared `PickerCore` (mount-to-open / unmount-to-close, same
idiom as the Loom's `pickCb` pattern it replaces). Optional attrs (`show-type`/`show-source`/
`show-upload`/`show-copy-prompt`) all OFF by default — the Loom's FIRST adoption is a byte-for-byte
behavior match of the retired `GalleryPick` component (no scope creep), which is now fully removed
(`.sb-pick-*` CSS kept — still used by the Export dialog + ImportCollection). Bridged via
`bindGalleryPicker` (mirrors `bindPicker`); wired at the ONE `pickCb &&` mount point used app-wide
(Cast add-from-gallery, both FrameSlots, etc.) so every picker call site upgrades at once. Standalone
harness `static/mg-gallery-picker.html` (two buttons: Loom-parity vs all-features-on).
**Verified 2026-07-13 evening** (a real Loom + catalog, headless-browser QA since the owner's own
session was time-budgeted): the empty-open bug (`1a83d51`) holds fixed — Cast "Pick from the gallery"
opens, browses-on-open, filters (confirmed `type=video` against 5 real video rows: correct request,
correct render, correct `mg-pick` payload, clean unmount), and closes with zero console errors. The
other call sites (both FrameSlots) share the exact same `pickCb`/`bindGalleryPicker` mount — one JSX
conditional, no per-caller logic — so they're the same verified path, not a separate one.
**NEXT after this = `<mg-cost-badge>`.** Save/load crash-safe fix shipped separately (`1710f04`,
re-verified: migration + atomic per-key writes both confirmed live + 5 dedicated tests green).

---

## 1. Loom V2 — REBUILD DEFERRED 2026-07-16 (Phase 1 probe result); state-layer extraction ships as consolidation instead — see the Phase 1 verdict below before reading anything past Phase 0 as still-current

**Everything below this point (the V2.1 rail-layout arc, the shot-mechanics work) is now historical — read for context, not as the active plan.** After the Trophy Hall incident forced a full ground-truth audit of the suite (2026-07-15), the Loom's classic/V2 fork got its own dedicated scrutiny: a first comprehensive-plan pass built independent consolidate and rebuild plans, then a focused 7-agent adversarial audit (2026-07-16, Sonnet/Opus/Fable mix) stress-tested both from multiple angles — a fresh skeptical re-read explicitly hunting for reasons rebuild was wrong, an off-the-shelf prior-art survey, a Loom-scoped standalone-app survey, a render-architecture-options survey, an adversarial stress-test of the rebuild plan's real costs, a Fable-model synthesis, and an Opus adversarial verify checking the synthesis for the same one-sidedness this exact decision had already shown in both directions.

**What that audit actually found, load-bearing for everything after:** the "~600 good state-layer lines lift out cleanly" premise both plans shared is **false as stated** — two independent passes confirmed the real state layer (`generateShot`/`pollShot`/`exportCut`/the multi-project store) is React closures woven through ~150 setter call-sites inside `App()` (1024–1701), not a separable module; the genuinely pure, cheaply-testable core is ~150–200 lines. The audit also found real bugs living *inside* that "solid" layer, not just in the classic/V2 render fork: `importJSON` silently clobbers the currently-open project with no confirm (real data-loss risk); `CONNECT[c.connect]` is unguarded and can throw on a stale/legacy card; `shotPayload` defaults both open and close frames to the same `@image9` tag; generation polls have no abort/cleanup and leak if a card is deleted mid-render; the continuity indicator is broken *by the app's own headline frame-handoff feature* (handoff writes `mediaId`, the indicator only checks `thumbId`); and there are ~7 duplicate tag-numbering call sites in 3 different algorithm shapes (not the originally-counted 4). No off-the-shelf storyboard app or render-layer replacement exists to shortcut this (checked and ruled out) — though **Dockview or FlexLayout** (both mature, MIT-licensed, actively maintained) are real candidates to replace the hand-rolled `DockablePanel` docking chrome if/when the rebuild reaches that piece, rather than hand-rolling it again. React + esbuild + Vitest/RTL remains the right tooling combo (Preact is a legitimate but optional later spike; Svelte and hand-rolled vanilla+signals were both explicitly rejected for a solo-dev migration of untested code; canvas isn't needed for the reel at this scale).

**Owner decision (2026-07-16): rebuild is the destination.** Not gated behind a probe-first decision tree — the owner weighed the evidence (including the audit's own "probe first, decide second" hybrid suggestion, which a subsequent adversarial-verify pass caught quietly pre-committing to rebuild's tooling anyway) and chose to commit directly, starting with:

**✅ PHASE 0 SHIPPED (2026-07-16, commit `b4303f5`):**
1. `frameLinked(a,b)` helper checking both `thumbId` and `mediaId` — fixes the continuity indicator. (Not ported to V2 — V2 never had this indicator at all; adding it there is later-phase feature-parity work, not a Phase 0 bugfix.)
2. `nextTag`/`maxTagNum(assets, prefix)` helpers — unified all 7 duplicate tag-numbering call sites (V2 cast-add, URL cast-import, `importCollection`, `routeImg`, `routeGen`, classic "+Add reference", `addRef`) onto one anchored-regex-max algorithm.
3. `dupCard` resets `resultMid`/`status`/`actualDur`/`trimIn`/`trimOut` on clone (also fixes Export's double-include-footage side effect).
4. `connectMeta(connect)` guards every `CONNECT[...]` index (3 call sites) against undefined/stale/legacy values, falling back to "new scene" instead of throwing.
5. `importJSON` creates a new storyboard + confirms instead of clobbering the open board in place.
6. (Found during implementation, not in the original 5:) `shotPayload`'s untagged-frame fallback gave both open AND close frame the same literal `@image9` tag on an FLF shot with neither tagged — now distinct fallbacks (`@image8`/`@image9`) so both images actually reach the model.

Verified: babel-in-node transpile clean, full pytest suite 474/474, live browser check (tag numbering + continuity indicator confirmed working end-to-end, zero console errors). `dupCard`/`importJSON` verified by code read, not live-triggered (would need either a faked rendered-shot state or a real PixAI generation call — declined per the standing hands-off-PixAI-generation rule).

These are shared, in-file helpers — no build step, no module system change, matches "no new tooling" exactly.

**✅ PHASE 1a — esbuild + pure-core extraction — SHIPPED 2026-07-16 (commit `7231f83`, pushed, live on `loom-v2`).** First Node/npm toolchain ever in this repo (`loom/package.json`, esbuild). `flat`/`shotText`/`shotPayload`/tag-math/continuity/pricing extracted into `loom/src/loom-core.js` (no React import), 30 `node --test` cases. The esbuild bundle is reachable only via an opt-in `?bundle=1` flag on `/loom`; Babel-standalone stays the untouched default. Verified for real: live Flask server hit both ways in-browser (identical render, zero console errors), full 474-test Python suite unaffected.

**⚠️ PHASE 1b — the decisive `useLoomProject` extraction — RUN FOR REAL 2026-07-16, and it changed the plan.** First attempt failed to even start (worktree-isolation tooling bug, fixed — see the dashboard for that detail); the re-run completed cleanly: two independent agents each extracted the ~450-line state/mutation layer in isolated worktrees (single monolithic hook vs. four composed hooks: `useProjectStore`/`useShotMutations`/`useGenerationPipeline`/`useExportPipeline`), each reviewed by 2 independent adversarial skeptics instructed to try to refute a "clean" claim, synthesized by Opus.

**What actually happened — read this before assuming "rebuild" is still the plan:**
- **The single-hook attempt claimed genuinely-clean and was wrong.** Its own skeptics split (one said clean, one didn't) — the synthesis agent independently verified the dissenting skeptic's evidence directly against the files and confirmed it: `loom/src/useLoomProject.js`'s `exportAll()` calls `fmt()` without importing it from `loom-core.js` — a real `ReferenceError` on the esbuild-bundle path, invisible because `exportAll` has zero test coverage. Separately, `duplicateProject` now silently clears the V2 shot selection via a blanket `useEffect`, where the original code deliberately preserved it — a real, undisclosed behavioral regression the self-report called "provably behavior-identical." **The skeptic that missed both is exactly the "adversarial verify quietly favoring the flattering read" failure mode this whole decision has already been caught in twice before — surfacing again, one layer down, inside the thing built specifically to catch it.**
- **The composed (four smaller hooks) attempt did NOT claim clean** (`cleanExtractionClaim: false`, three specific named blockers disclosed up front) **and its account held up completely** under its one real skeptic's independent re-execution (the second "skeptic" was a stub/failed run returning literal placeholder text — correctly disregarded by the synthesis). No runtime bug, no behavioral regression, only two trivial pre-existing edge-case deltas.
- **The real, load-bearing finding:** the state layer genuinely CAN be lifted out cleanly — via the composed strategy — but doing so does **not** require first merging classic+V2's render trees. The actually-hard, still-unsolved part in BOTH attempts is the state↔view coupling (the shared gallery-picker DOM bridge, status writes mid-generation-poll, `entries` being per-render-derived data no hook can own, the V2-panel-layout storage sharing, per-project selection reset) — exactly what a "unified render tree" rebuild exists to solve, and this probe deliberately never tested that part.

**Opus synthesis recommendation (full text in the workflow journal, not yet condensed to an artifact):** *do the state extraction now, using the composed strategy, against the CURRENT classic/V2 fork, as a consolidation step — not as step one of a rebuild.* This reduces rather than strengthens the rebuild's case, because the main problem the rebuild was supposed to solve (the tangled state layer) turns out to be solvable in place. The render-tree unification itself was never tested here and remains genuinely open — not validated, not ruled out.

**✅ MERGED 2026-07-16 (commit `ee4b33a` on `loom-v2`, pushed) — owner call: merge the composed extraction, park the full rebuild.** After walking through what the probe actually meant (the state layer being separable reduces rather than strengthens the case for merging the render trees — the expensive, still-unvalidated part of a full rebuild), the owner chose speed and evidence over the earlier gut-call: ship the working, adversarially-verified consolidation now; stop treating full render-tree rebuild as a locked destination since it was never actually earned by data. `loom/src/loom-mutations.js` (pure reducers/classifiers/builders) + the four composed hooks in `master-storyboard.jsx` are live. Re-verified independently in the real repo post-merge, not just trusted from the worktree: `node --test` 66/66, `npm run build` clean, `python -m pytest` 474/474 (the composed worktree's own report showed 467/7 due to a fresh-worktree missing `config.json` — confirmed environmental, not a regression, and indeed 474/474 in the real repo where the file exists), live Flask server hit fresh (`loom-verify` config, not a stale process), zero console errors, a real populated project with real acts/shots/continuity-check state rendering correctly. The single-hook attempt's branch (`loom-extract-hook`) is kept, unmerged, as the documented record of what a "genuinely clean" claim that wasn't held up looks like. Both experimental worktree directories can be removed now that composed is safely merged (their content lives in `loom-v2` history) — housekeeping, not a decision.

**Rebuild status: PARKED, not cancelled, not locked.** The full render-tree unification (classic+V2 merge) remains genuinely untested and undecided — nobody has run the same rigor against it that this probe just ran against the state layer. It stays on the table for whenever that gets its own real probe; it is not the active plan. The shell/Timeline design work already done and owner-approved stays valid regardless — that's front-end layout, entirely orthogonal to this state-layer question, and applies to whatever render tree eventually exists.

**Timeline → fixed drawer: SPEC IS LOCKED (owner has stated this identically 2026-07-13/14 and again 2026-07-16) — this is NOT an open design question, stop treating it as one.**

The ask, unchanged across every restatement: a **fixed drawer attached to the top banner — never a draggable/dockable panel.** Three states: (1) **default = visible at a slim height** (not hidden), full page width; (2) **can be fully pushed away, collapsing the whole space to nothing**; (3) **pulled down, it extends to a set full size showing the video preview ABOVE the scrubber** (not beside it). "Preview-above-scrubber" was already marked LOCKED on 2026-07-13/14 (owner: "the gold standard for a reason") — the owner repeated the full spec again 2026-07-16, word for word matching what's recorded here, specifically because it kept not getting built.

**What actually happened, verified against the live code (2026-07-16):** the Timeline is still just one more entry in `V2_DEFAULT` (`loom/master-storyboard.jsx:399`), rendered through the exact same generic `<DockablePanel>` component (`:1011`) as Cast/Legend/Board/Generate/Footage — draggable, resizable, x/y/w/h-persisted, identically to every other panel. The 2026-07-14 "Timeline collapse fixed" work (blunt `display:none` → a real slim scrubber strip) fixed the *collapsed-view rendering bug* only — it never touched the structural ask (make it a fixed, non-draggable drawer). That fix most likely got reported/treated as "Timeline: done," which is why the core ask kept surviving, unbuilt, underneath a series of "it's handled" checkpoints. Naming the pattern so it doesn't repeat: a partial fix to a related bug is not the same as verifying against the full locked spec.

**Descoped from the old "needs its own scoping pass" framing (2026-07-14, historical section below):** that framing bundled three unrelated things together and let a fully-specified small item hide behind two genuinely big ones. Splitting them for real:
- **#1, this item (fixed drawer + preview-above-scrubber) — fully specified, zero scoping left, ready to build whenever picked up.** Small and contained; doesn't touch the other panels and doesn't depend on the Phase 1 rebuild-probe outcome.
- **#2, panels snap/dock together** (free x/y/w/h → tiling/split-pane) — **owner call, 2026-07-16: only matters if the rebuild keeps a modular/multi-panel design at all — not worth deciding until that's settled.** See the workspace-paradigm question below; this item is downstream of it, not independent.
- **#3, multi-track timeline** (layered clips + audio lane) — **owner call, 2026-07-16: a nice-to-have, explicitly not important.** The tool's actual job is building 5–15s scenes and stitching them cohesively — the stitched output then goes to a real video editor for post. Not trying to be an NLE. Per-shot audio cues (already tabled above) cover the real need; a full multi-track timeline doesn't fit the tool's scope and isn't worth building.

Only #1 is ready now. #2/#3 aren't just unscoped, they may not be needed at all depending on the paradigm question.

**✅ WORKSPACE SHELL — owner answered 2026-07-16: replaces the 6-arbitrary-draggable-panel model with 3 named elements, nothing else free-floating.** The question was reframed correctly by the owner as "what needs to be open and in front of us at all times in the scene-builder flow," not an abstract modular-vs-not debate. V1 (simple, no docking) vs. V2 ("muddied what do I do first and when do I use this") is the diagnostic; the answer:
1. **Cast & Assets — always present**, two view states: **simple** (small square card: name + tag + ref-image preview only) and **detailed** (the full V1-style row: name/tag/kind/lock/thumbnail). Owner's own analogy for the simple→detailed expand: similar in spirit to the gallery's Generate-drawer sliding-card reveal (different platform, same interaction idea) — not a literal component reuse, just the reference feel.
2. **Generate panel (Image/Video/Edit/Reference) — a collapsible drawer, matching the GALLERY's actual drawer**, not a Loom-only lookalike. Owner: *"this was my ask from the get go on this and I got a lot of push."* **Verified against the live code 2026-07-16: that push was real and the drift is confirmed** — the Loom's `genImage`/`runGen`/`genEdit`/`genRef` and all Generate-tab chrome are hand-rolled inside `master-storyboard.jsx` itself; the ONLY thing actually shared with the gallery's drawer is the `<mg-model-picker>` widget. The 2026-07-11 plan explicitly promised "same component as the gallery — one mental model" and what shipped instead was a parallel reimplementation that merely resembles it. **The fix isn't a new idea — it's finishing the already-decided suite-wide front-end direction** (`docs/SUITE_ARCHITECTURE_AUDIT.md`, owner-locked 2026-07-13: promote shared UI to framework-neutral web components so the vanilla gallery AND the React Loom mount the *same* element, no build step) and applying it to the one place it was skipped. `<mg-model-picker>`/`<mg-gallery-picker>` are the proof this playbook works; a `<mg-generate-drawer>` would make "same component as the gallery" literally true this time.
3. **Timeline & preview** — the fixed drawer, spec'd above.

**✅ Overall shell — owner's mental picture (2026-07-16), matches V1's structure plus one new addition:**
- **Left: Cast & Assets, a collapsing card.**
- **Center: Acts & Shots board** (unnamed by the owner because it's the obvious main content — same as V1).
- **Right: the Generate drawer (Image/Video/Edit/Reference), collapsible, "no different than gallery layout"** — mirrors the gallery's own drawer positioning/behavior, not just its component identity (see `<mg-generate-drawer>` note above).
- **Top: the fixed Timeline drawer**, spec'd separately above.
- **Confirmed staying:** generating straight from the board for establishing shots — the owner re-confirmed the earlier call that a FULL generate panel belongs inside the Loom itself (not a stub linking back to the gallery), so nothing has to leave the tool to reach the real generation flows.

This is essentially V1's proven layout (top reel + left cast + center board) plus exactly one new region (right Generate drawer) for the one capability V1 never had — not a new invented shape.

**Footage (Asset Bin) — real intent clarified:** lets you pull an ALREADY-RENDERED video into a scene for stitching/reference (PixAI's video gen already supports video refs, not just images) — the owner still wants this, it's the bridge that makes the Loom double as a lightweight video-ref tool. Correction to the earlier hypothesis: NOT folded into the on-demand `<mg-gallery-picker>` modal — owner wants it "hidable, just like Cast and Assets" (persistent-but-collapsible, not summon-only). **Open fork, Claude's lean offered, not decided:** own collapsible card, or a second tab inside the same left-side Cast & Assets card (both are fundamentally "browse existing visuals to pull into a shot," and folding it in keeps the "only a few persistent regions" principle intact instead of growing back to four). Owner to confirm.

**✅ Legend & notes — DECIDED (owner, 2026-07-16): revive V1's inline "+terms" mechanism, no persistent home at all.** Agreed outright — Legend goes back to being a per-field on-demand popover (Camera/Lighting/Transition), not a panel anywhere.

**✅ Footage — DECIDED (owner, 2026-07-16): folds into the same left card as a tab alongside Cast & Assets, "just like gens"** (i.e. the same tabbed-drawer pattern as the Generate panel). One left-side card, two tabs (Cast & Assets · Footage), not a 4th region.

**✅ PIXEL SOURCE OF TRUTH — full shell mockup built + browser-verified (2026-07-16): [`loom_shell_mockup.html`](https://claude.ai/code/artifact/e41a3020-32fb-4baa-ae81-69814d5ee4c9).** Interactive, not static — real design tokens, all pieces demonstrated working together: left card (Cast&Assets/Footage tabs, Simple/Detailed density toggle, collapse-to-icon-rail), center board (acts/shot cards, gold selected-shot ring), right Generate drawer (Image/Video/Edit/Ref tabs, collapse-to-rail, bound-to-shot chip), the fixed Timeline drawer (ported from the standalone Timeline wireframe, same 3-state drag mechanic), and a live "+terms" popover on the Camera field proving the Legend decision concretely instead of just describing it. Verified interactively (tab switches, density toggle, both sides' collapse/expand via rail icons, terms popover append) with zero layout breakage after one text-wrap fix (bound-chip + cost row). **Owner reviewed 2026-07-16 — reaction: "Wow. Just wow. Beautiful mockup," 3 fixes requested, all shipped same pass:**
1. Preview box was full-width-but-short (~3.4:1) instead of a real video frame — fixed to `aspect-ratio:16/9`, centered, generous size; full-drawer height grown 260→400px to fit it properly instead of squeezing it.
2. "Where's the Legend hiding" — valid catch: only Camera had a "+ terms" trigger. Added it to Transition In and Transition Out too (matching V1's actual `CAM_PALETTE`/`TRANS_PALETTE` scope exactly), generalized the JS so any `.termsbtn`/`.termspal` pair works without per-field code.
3. Footage tab needed a way to reach footage beyond this project, plus external drag-and-drop — added a "Browse library" button (opens the shared gallery-picker concept) and a drop-zone with live dragover/dragleave visual feedback, "same picker + drop-to-upload pattern as the gallery's Generate panel" (owner's framing). Video vs. image cells now visually distinguished (play badge).

**Status: shell shape + all 3 fixes owner-approved in spirit ("excellent design"); this is now the working pixel source of truth for the rebuild's shell.** Supersedes the standalone Timeline-only wireframe (`https://claude.ai/code/artifact/84be1748-2c7d-4304-967c-8ac22cd37687`, kept for reference).

**Follow-up round (2026-07-16), owner reactions + Claude verification:**
- Preview box: "Chef Kiss," no notes.
- "+terms" location — owner asked where else it shows up. Re-verified live against the actual published URL (not just local): Camera/Transition In/Transition Out all correctly show it in the Video tab. Two real reasons it looks absent elsewhere, both disclosed: (1) the mockup's Image/Edit/Ref tab buttons are cosmetic-only right now — clicking them doesn't swap panel content, so exploring those tabs just re-shows the same Video fields; (2) more importantly, Camera/Transition genuinely ARE video-only concepts in the real app — `genEdit`/`genRef` only ever took `source(s)+instruction`, no camera/transition params — so there's nothing missing, Video is the only tab where these fields exist by nature of what they represent.
- Footage scroll — owner asked if it scrolls once full. Grew the demo data to 8 items and measured directly in-browser rather than asserting from the CSS: `sidebody` clientHeight 585 vs. scrollHeight 646, `overflow-y:auto` confirmed engaged. It scrolls.

**✅ Project save/delete/import/export — DECIDED (owner, 2026-07-16): "a killer take on the idea."** Previously unaddressed rebuild surface — the owner asked directly, after hating "the volatile browser cache and server side saves." Verified against the actual current code first, not memory: the old crash-safety fix (single `store.json` blob → atomic per-key files, already shipped) solved a *different* problem than this one. A "project" today still isn't one real portable thing — it's one key-file for the project JSON plus a scattered pile of separate key-files, one per uploaded reference-image thumbnail, tied together only by ID references inside the JSON. The existing `Backup (.json)`/`Restore` buttons already bundle the project structure plus small embedded thumbnail JPEGs — but a project's actual finished shots (`resultMid`) only travel as a reference into the local PixAI catalog, so handing that `.json` to anyone else, or opening it on a fresh install, leaves every finished shot blank.

**Locked design — two deliberate tiers, not one ad hoc export button:**
1. **Lightweight (default, quiet background save)** — one real project file (not a buried KV key), media referenced by catalog `media_id`. Fast, small, correct for the owner's own cross-machine use (home ⇄ work), since both sides share the same catalog.
2. **Full bundle (for real sharing)** — a zip containing the project JSON *plus the actual referenced media copied in* (full-res images and video, not just thumbnails), with references rewritten to point inside the bundle instead of the catalog. This is the one that means anything to another person, or to a install with a different catalog. Import auto-detects which kind it received.
- **Delete** stays simple either way once this lands — removing one project's file, no change from today's UX.
- **UI touchpoint:** lives off the `ProjectSwitcher` as an "Export ▾" menu (Lightweight / Full bundle), not new persistent chrome — consistent with the shell redesign's "only a few persistent regions" principle.
- **Why it matters beyond personal use:** the owner explicitly flagged this as a real feature if Moonglade ever gets used more publicly — sharing a storyboard project is a genuinely good capability once the tool has users beyond just its own author, not just a backup nicety.

Not yet built — this is a rebuild-scope design decision, sequenced alongside (not gating) the Phase 1 extraction probe.

**Standalone-app note, corrected twice by the owner:** "standalone" was scoped Loom-only in the 2026-07-16 audit by mistake — the owner's real question is **suite-wide** (the whole Moonglade Athenaeum app, not just the Loom), and they added real history: **"The loom started standalone and its how we got in this mess"** — the classic/V2 fork and general disconnection from the rest of the suite's patterns trace back to the Loom's own standalone-then-merged past. Treat that as a cautionary data point for whenever the suite-wide question gets its own real scoping pass, not an argument for or against outright. Not blocking the current rebuild — explicitly low-priority, "not the currently preferred direction" per the owner's own words.

---

### Historical: the V2.1 rail-layout arc (superseded by the rebuild decision above, kept for provenance)

**State (git + transpile verified):** branch `loom-v2`, **6 commits ahead of master, unmerged**, transpiles clean. A **non-breaking opt-in overlay** behind a "V2 layout" toggle; classic waterfall Loom is default and untouched. All V2 code in `loom/master-storyboard.jsx`.

**Locked design:**
- **6-panel layout** (shipped verbatim as `V2_DEFAULT`, canvas ~1498×820). Coords (x,y,w,h):
  - Timeline & preview `0,0,1498,271` (full-width top) · Asset bin—footage `5,275,286,538` · Cast & assets `301,276,255,284` · Legend & notes `301,565,256,244` (STATIC) · Acts & shots (board) `562,278,628,536` · ⚙ Generate—shot `1198,276,294,540` (full-height).
  - The "alternate, fixed" layout: Generate full-height, Cast wider, board narrowed so it clears Generate. Persists to store key `storyboard:v2:layout`.
- **Selected-shot interaction model** (owner-approved via `loom_selectshot`): click a shot → binds Generate + panels to it; LOUD selection (gold ring + timeline glow + name in headers); two-way live edit; double-click = deep-focus modal; board never moves in place.
- **Collapsing:** timeline collapses to keep just the scrubber; app banner header = "Collapsing" mode (sticky 260px, collapses on scroll; modes Collapsing/Always-slim/Off). Banner default = mark **#62**.

**Wired / working (browser-verified):** V2 toggle · error boundary · layout persistence · real acts&shots board · timeline reel + `ShotPreview` trim · Cast (toggle refs, +add from gallery) · static Legend · Footage grid · **all 4 Generate tabs functional** (Video/Image/Edit/Reference — real gens verified live 2026-07-12 with real task IDs, routed into open/close frame/cast).

**✅ SHOT MECHANICS SHIPPED (2026-07-14) — V2 is now mechanically complete:**
- **Add / reorder / duplicate / delete shots in V2** — `addCard`/`moveCard`/`dupCard`/`delCard`/`moveCardToAct` (the same functions classic Loom always used) now wired into the V2 board. Per-card icon row (↑↓⧉✕ + "move to act…").
- **Add / reorder / delete ACTS in V2 too** — `addAct`/`moveAct`/`delAct`/`setAct` wired in; the board now iterates `project.acts` directly instead of the entries-derived `grouped`, so a freshly-added **empty act stays visible** (with its own "+ Add shot" button) instead of disappearing.
- **`FrameSlot` (open/close frame) reparented into Generate** — sits above the tab bar so it applies across modes, exact same splice/inherit-from-previous mechanics as classic (`/api/loom/handoff`).
- Browser-verified end-to-end: add act → shows immediately (incl. empty) → add shot → shows "first shot" placeholder → add a 2nd shot → shows "↳ inherit A·01 close" correctly. Zero console errors; Babel-transpile-checked clean.
- **Still stubbed:** Timeline collapse-to-scrubber is **buggy** (blunt hide-body, not a real slim scrubber); no snap-to-grid; no double-click deep-focus in the overlay yet; no rail/icon-strip Generate collapse. These are item **#2 — the rail layout restructure** (next).

**✅ V2 can now replace classic Loom for full shot-building** — the two literal blockers ("still needs classic Loom for add-shots + frame-setting") are closed. Remaining work is ergonomics (rail/collapse) + polish (deep-focus/snap-grid), not missing mechanics.

**✅ DECIDED (owner, 2026-07-11) — OFFICIAL PLAN: Loom V2.1 "drawer-ized" build. NEXT MAJOR BUILD after the achievement implementation.**
The ref-gen question is resolved as **Option A + bridge** (supersedes the open decision below):

1. **Shared Generate drawer mounts in the Loom** (same component as the gallery — one mental model) with a **shot-context bridge**: bound-shot chip at top · refs pickable from Cast/Footage · **output routing** one-clicks on completion (→ open frame · → close frame · → cast · → footage bin). Delivers the original "Edit-deck" per-shot pitch via the shared component. Mostly wiring: drawer already emits media_id; Loom already has FrameSlot/Cast/Footage targets.
2. **Rail layout (progressive disclosure) — ✅ PARTLY SHIPPED (2026-07-14):**
   - **Timeline collapse fixed** — was a blunt full-hide (`display:none` regardless of panel id, the "buggy" collapse); now collapses to a real slim scrubber strip (just the reel + target marker, no preview/info line), height 78px, full width kept.
   - **Generate collapses to a right-edge icon rail** — ✦ Image · ✎ Edit · 🖼 Reference · 🎬 Video, exactly as specified. Collapse axis is per-panel now (`DockablePanel` takes an optional `collapsedView`): Generate collapses in **width** (294px→52px, full height kept, since it's the tall right-edge column) while Timeline collapses in **height** (full width kept) — the old code only ever shrank height uniformly, which is why Generate could never have worked as a rail before. Clicking a rail icon expands the panel AND switches to that tab in one click (`setTab(t); collapse("generate")`). Browser-verified end-to-end (rail renders at 52px/full-height, correct icon reflects the live tab, click expands + switches, zero console errors).
   - **"Center panels become dynamic reflowing panels" — ✅ RESOLVED, no build needed (owner, 2026-07-14):** the phrase just meant the existing free drag/resize (already built, already persisted per-layout). Mystery closed, not a gap.
   - **✅ Panel-drag SNAP-TO-GRID shipped (2026-07-14)** — `DockablePanel`'s drag/resize now rounds x/y/w/h to a 16px grid (`snap()` in `startDrag`/`startResize`). Browser-verified: dragged Cast to (368,320) — both exact multiples of 16.
   - **✅ Deep Focus modal shipped (2026-07-14)** — double-click a board card → a maximized distraction-free editor for just that shot (title, mode chips, duration, both `FrameSlot`s via the same shared component, a "Select in Generate →" button that selects + closes). Escape/backdrop/× all close it. Browser-verified: opens with correct shot data, Escape closes, the Generate button selects the right shot in the main panel and closes the modal.
   - **✅ V2 scroll bug FIXED (2026-07-14, owner-reported)** — root cause: `.lv-scaler{overflow:hidden}` plus `transform:scale()` on `.lv-canvas`, which doesn't shrink an element's contribution to its parent's *scrollable*-overflow size (only its paint size) — so on a short viewport the excess just clipped, with the page's own unrelated scrollbar moving uselessly (exactly the "scrollbar moves, does nothing" report). Fix: a `.lv-canvaswrap` sized to the REAL scaled footprint (`1498*scaleV × 820*scaleV`) so `.lv-scaler{overflow:auto}` computes the correct scroll range. Verified exactly: at a forced 400px-tall viewport, scrollable range was 177px = precisely `scrollHeight(516) − clientHeight(339)`.
   - **⚠️ MAJOR — design drift surfaced (2026-07-14, owner).** Owner described a substantially different Timeline vision than anything built or found in any artifact: **Timeline as a fixed drawer attached to the top banner** (not a draggable panel) — full page width, default visible at a slim height, fully collapsible to hidden, pulling down extends it to a set size showing the **video preview ABOVE the scrubber** (not beside it, as the one located mockup showed). Checked `loom_mockup` (artifact `8bd885e1`, 2026-07-10) — it does NOT match: timeline there is 55%-width (not full), preview sits BESIDE the track (not above), and its own Legend panel literally lists *"Timeline: dock‑collapse vs drag‑open?"* as an **open, unresolved question** at the time. The owner's fuller vision (this + panel snap/dock + multi-track timeline) apparently came from an unrecoverable "weekend" conversation — searched this session's full transcript, only this message matches. **Nothing built yet.** *[Corrected 2026-07-16 — see §1 above: item #1 below was never actually unscoped, it was locked from the first restatement. Only #2/#3 genuinely needed a scoping pass.]* Three components tangled together, sized separately:
     1. **Timeline → fixed top drawer** (hide/extend, preview-above-scrubber) — small, contained, doesn't touch the other panels' architecture.
     2. **Panels snap/dock together** (replace free x/y/w/h per panel with a tiling/split-pane layout) — a real architecture change, multi-session.
     3. **Multi-track timeline** (layered clips + a visible audio lane) — a data-model change (shots are currently one sequential list, not parallel tracks) — also multi-session, separate from #2.
     Also asked: can the docked panels occupy the drawer's dead space beside the preview when fully extended? (falls out of #2, not separate work.)

   **✅ OWNER DECISIONS on the design-drift items (2026-07-13/14), + 3 more V2 polish items SHIPPED:**
   - **Preview-above-scrubber: LOCKED as the direction** for the eventual fixed-drawer timeline (item #1 above) — owner: "the gold standard for a reason," but ALSO wants to keep a side-by-side preview option available (their existing mockup idea) as a secondary layout worth exploring later. Novel ideas come after the drawer/dock/multi-track architecture (#1–#3) is actually built — not before.
   - **Audio lane: TABLED, roadmapped only, NOT built.** Owner leans per-shot audio cues aligned to their own timeline segment (a single extra layer, not a full multi-track system) — captured as the shape of a future #3 (multi-track timeline) increment, not scoped further tonight.
   - **Docking into the drawer's dead space: parked in the "a boy can dream" pile.** Owner's own framing — it was a musing tied to snap-together frames (part of #2, panel snap/dock), not as deep a request as it first read. Small panels using the preview's dead space when the drawer is down, returning home when it collapses, is a nice-to-have IF #2 gets built, not a requirement driving it.
   - **✅ Panel resize cap SHIPPED + browser-verified (2026-07-14):** owner's call — "most panels don't need to get very wide, ever" (width capped) but "height can be a bit more liberal" (only bounded by the canvas floor). `startResize` in `master-storyboard.jsx` caps non-timeline panels at `min(800, canvas_edge - x)` width; Timeline stays exempt (still full-width by design) — verified live by dragging the Cast panel far past 800px (pinned at 800×496 across three escalating drag attempts) and the Timeline panel past 800px width (grew to 1504px, confirming its exemption).
   - **✅ Loom nav button blocked on phone, not tablet (2026-07-14):** `.head-nav .b-loom{display:none}` added inside the existing sub-480px breakpoint in `pixai_gallery.py` — the Loom is a dense multi-panel tool that isn't viable on a phone screen. Verified live: hidden at 390px, visible at 768px (tablet range untouched).
   - **✅ Bottom-sheet mobile filters SHIPPED (2026-07-14):** `.filters` becomes a fixed bottom sheet at the sub-480px breakpoint (slide up/down via the existing `toggleFilters()`/`.open` mechanism, unchanged JS) + a `.filter-scrim` backdrop. Browser-verified correct in both directions — a false alarm surfaced mid-verification (getComputedStyle read before the CSS transition's animation frame had advanced, an artifact of the automated test tab pausing its render timeline, confirmed via `getAnimations()` showing `localTime` stuck at 0) — the actual CSS/cascade was correct the whole time, no code fix needed.
   - **Committed + pushed** (`loom-v2`, commit `3a69827`) and fast-forwarded to the D: run-copy. All 474 tests green.

3. Folded-in mechanicals — **✅ FULLY SHIPPED (2026-07-14):** add/reorder/duplicate/delete shots AND acts · reparent `FrameSlot` into Generate · double-click deep-focus modal · snap-to-grid. Nothing left in this bullet.
4. **Estimate ~two focused sessions** (1: drawer mount + bridge routing · 2: collapse states + reflow + mechanicals), then `pytest` + merge `loom-v2 → master` (`--no-ff`).

**Sequencing (owner-locked):** Achievements first (board selection → wire winners → telemetry layer) → **then Loom V2.1**.

**⏳ V2.1 INCREMENT 1 BUILT (2026-07-11) — the shot-context bridge, in `loom/master-storyboard.jsx`:** the dead **Image tab** now generates a reference image for the selected shot — model picker (via `/api/model-search`), image-prompt + "seed from shot", "✦ Generate reference image" (reuses `/api/generate` + spend-confirm), and **output routing** buttons (→ open frame / close frame / cast) that patch the shot so the gen feeds its video render. App-level `genImage`/`pollImg`/`routeImg` + `genImgState`/`imgModel` state; passed to `LoomV2`. **Verified live:** renders, model search returns hits, selection binds. **Pipeline confirmed end-to-end (2026-07-11):** a real shot gen reached PixAI's `createGenerationTask` and was rejected *only* with `INSUFFICIENT_BALANCE` (owner's free rewards spent on badges that day) — i.e. request build/auth/submit all work; the last-inch "watch it land + route" test is DEFERRED to when free rewards refresh, NOT re-verification of the wiring. Do not re-litigate whether the bridge works. **✅ FULLY VERIFIED LIVE 2026-07-12 (owner, with daily-reward credits): Image gen (task 2033281781419406134), Edit (2033281140142052223), Reference (2033280508060971303) all SUCCEEDED end-to-end — generated, landed, and clicking the result routed the image into the shot's scene reference each time. The bridge is done; nothing left to prove on the gen pipeline.** **Bug found+fixed:** seed button called `shotText` (App-scoped, not in `LoomV2`) → crashed on click → rewrote seed inline from card fields. **⚠️ ENV: live server runs from the D: run-copy (`D:\Moonglade Athenaeum\`), NOT the C: repo — edits made in C: (loom-v2) AND synced to D: so the live server serves them. The two loom-v2 checkouts are at different commits (C: eeb1c0a vs D: 2673936) — pre-existing cross-machine drift, DON'T mass-commit-fix (per CLAUDE.md); the loom .jsx itself matched.** C: repo changes are UNCOMMITTED (owner to commit/reconcile). **Remaining V2.1:** rail layout · reparent FrameSlot · add/reorder shots · Edit/Reference tabs.

**✅ MULTI-PROJECT PERSISTENCE (2026-07-11) — the long-standing "only one project persists" gap, closed.** The Loom now saves multiple named storyboards: each lives at `storyboard:v2:proj:<id>` in the existing server-side KV store (`out_dir/loom/store.json`), with an `active` pointer and a header **switcher** (New · Open · Duplicate · Delete; Rename via the name field). The legacy single-key project (`storyboard:v2:project`) **auto-migrates** in as storyboard #1 on first load and is preserved untouched as a backup. No new server code — reuses `/api/loom/get|set|list|delete`. **Verified end-to-end** on a copy of the real store: migrate → new → switch, name + content intact, no crash. **Hardening pass (2026-07-11, same day):** switcher extracted to a shared `ProjectSwitcher` component now rendered in **both** the classic header and the V2 header; **outside-click-close** added (fixed veil at z-59); **Duplicate + Delete interactively verified** on isolated real-data — this caught + fixed a real bug where deleting the *active* project re-created it (the switch-away `openProject()` flushed the doomed project back to the store). Minor cosmetic detail left: in V2, the hidden classic switcher shares `projMenu` state so both popups mount, but the classic one is fully occluded by the z-400 V2 overlay (invisible, harmless).

**✅ SLICE 2 — balance + friendly errors (2026-07-11).** Generate panel shows live credits + cards from `/api/account` (`⚡ N credits · M cards`, themed, conditional "+N claimable"), verified rendering real data (`0 credits · 2 cards`). `friendlyGenErr()` maps raw PixAI `INSUFFICIENT_BALANCE` GraphQL to a human message, wired at all 4 gen error-set points (submit + poll, shot + image); unit-tested against the real error string. **✅ SLICE 4 — Edit + Reference tabs (2026-07-11).** All four Generate tabs live. **Edit** → `/api/edit` `{source: open-frame mediaId, instruction, edit_model:"edit-pro"}` (Edit Pro). **Reference** → `/api/edit` `{source: refs[0], sources:[cast @image mediaIds], instruction, edit_model:"reference-pro"}` (Reference Pro, ≤10 refs). Both poll + route (open/close frame · cast) via shared `runGen`/`routeGen` — the verified Image path (`genImage`/`routeImg`) left untouched. Verified on isolated real-data: Edit shows the shot's real open-frame thumb + enabled button; Reference shows 1 real cast ref + enabled button; no crash; balance line on both. Live edit/ref gen awaits balance (contract-verified: payload matches `_edit_params_from_payload`). **✅ NOW LIVE-VERIFIED 2026-07-12 — Edit + Reference both succeeded with real task IDs (see Increment 1 above), routed into the shot.**

**⏳ LOOM REFINEMENT (owner feedback 2026-07-12, post-verification):** the Image tab's model selection is a type-in `/api/model-search` box — NOT intuitive (you have to discover it's a search). Owner wants the **gallery's model/LoRA picker flyout reused in the Loom** (the one with hover preview cards: cover/likes/author/tags + LoRA chips), instead of reinventing a thinner picker. This is a [[feedback-cohesion]] win — the gallery Generate drawer already solved this well; the Loom should mount the SAME component, not a parallel one. Fold into the V2.1 "shared Generate drawer in the Loom" plan (§1 Option A+bridge already calls for the shared drawer — this is concrete evidence for doing it). NEXT concrete Loom task candidate.

**All three picked slices (1·2·4) shipped.** Remaining Loom work = **#3 rail layout** — the focused-session restructure, to pair with the cohesion audit.

*(Superseded original decision list, kept for provenance:)*
1. ~~[BIG DECISION] In-Loom ref-gen scope~~ → resolved: A+bridge.
2. ~~Reparent `FrameSlot` into Generate~~ → folded into V2.1 item 3.
3. ~~Polish: collapse-scrubber bug · deep-focus · snap-to-grid · add/reorder shots~~ → folded into V2.1 items 2–3.
4. `pytest` + merge — unchanged, end of V2.1.

---

## 2. Achievements — the system (code)

- **✅ THE FULL 57 SHIPPED (2026-07-12, loom-v2).** `ACHIEVEMENTS` is now all 57, generated verbatim from `docs/achievements_roster_57.json` (three roster threshold data-bugs fixed per their own trigger text: marathon 1→100, read-the-manual 0→1, triggered 0→5). Browser-verified against the real 31k catalog — 18 auto-earned on first compute, incl. 2 feats (Under the Hood, The Long Night/marathon):
  - **Telemetry layer** — `out_dir/telemetry.json` (counters/maxima/sets/flags/days; `telem_bump/_max/_set_add/_flag/_mark_day` in `pixai_gallery.py`, lock-guarded, fail-soft; `set_telemetry_out()` wired in `create_app` + CLI `main`). ~15 call sites bump: `/api/edit·enhance·fix·upload·similar·claim·generate(LoRAs)·loom/generate(video modes + origin:"loom-shot")·skin·branding·delete-bulk` + CLI `--organize`, `--dedup`, `--claim`, `--task-id` recovery, `_apply_kaisuuken` (free cards), new-download Time-Capsule check. New SQL metrics: `local_gens` (source api|local), `gens_in_a_day`, `distinct_keywords`. Compute post-passes: `skins_unlocked`, `all_non_feat_earned`.
  - **Hidden feats** masked server-side (`???`, no roast/name leak); the feats section stays cloaked until the first feat earns. **Narrator poke** (chibi in the panel header, 5 pokes → *Triggered*) reveals the **Unleash the AI** toggle → `roast_nsfw` everywhere. Feat events via `/api/ach-event` (konami/docs/narrator) + state sweeps (custom mark → *Under the Hood*, eclipse anim → *Eclipse*).
  - **Feat tier = GUNMETAL + RUBY** (`--gunmetal #8a93a2`, `--ruby #e0355e`): panel band/inner-rim/glow, section header, moment pill/scrim/confetti, its own chime. The pink is gone.
  - Panel groups by bucket (Ladders/Milestones/Masteries/Feats); earned cards show roasts; Great Library carries `banner_reward` (flag only — the banner-unlock pool mechanic is still future work). The moment presents with the achievement's OWN mascot (`branding/mascots/ach/<id>.png` → tier-chibi fallback).
  - Tests: **459 passing** incl. new `tests/test_telemetry.py`.
- **✅ Art COMPLETE ON DISK (`D:\Moonglade Athenaeum\pixai_backup\branding\`): badges 57/57 + mascots/ach 57/57.** The final 9 (loremaster + moonweaver silent replacements, forgemaster, vernissage, against-the-void, read-the-manual, the-konami-code, time-capsule, under-the-hood) plus a first-frame v2 replacement were already keyed in the owner's `badges_keyed` folder (rename pass hadn't landed) — placed + alpha-verified 2026-07-12. All pre-existing versions preserved in `badges\_pre57_backup\`. LE10_Q3 remains an unassigned spare. Remaining art thread = Phase 2 items only (mystery tiles · 9-slice frames · optional SFX/ribbon/animated-chibi — see the Art Worklist artifact `13712183`).
- **✅ FRAME DIRECTION LOCKED (2026-07-13) — see `docs/ART_PICKS.md` §Decisions:** ornate frames **wrap the toast, 9-sliced** (WoW-style: corners fixed, edges stretch, frame grows to content — the earlier "frame the page cards" mock was a wrong turn). **Tier-gated: legendary + feat ONLY** wear the custom frame + toast, on the toast moment AND the page tile; common/rare/epic stay clean (epic TBC). **Points come to toasts + cards** (feats = 0 → show none). CLAIM7 gift box → the toast reward ribbon. Finalists wrapping the real toast in artifact `3655423e`. **WINNERS (2026-07-13): legendary = LEG6 (gold+emerald), feat = FEAT13 (ruby thorns); BAR4 parked as a future test (gem-window→badge edit).** Real toast = `.ach-m2` (locked `335ef4e7`).
- **✅ FLAIR SLICE SHIPPED (2026-07-13, `loom-v2`, commits `3e91af4` + `3572b22`, 464 tests green):** (1) 9-slice tier **frames on the unlock toast** — legendary `branding/frames/legendary.png` (=LEG6) / feat `frames/feat.png` (=FEAT13); a `.tframe` wrapper in `_mkMoment` carries the `border-image` and grows with the roast (slices legendary 16.8%/13.3%, feat 15.8%/10.3%; borders 46/44 + 46/38). (2) **CLAIM7 gift box** in the `.rwd` ribbon (`branding/rewards/gift.png`, replaces the emoji). (3) **Rung-scaled points** — `_TIER_POINTS` + derived `_ACH_RUNG` + `achievement_points()`; `compute_achievements` emits per-ach `points` + `earned_points`/`possible_points`; shown on the toast (gold `+N` chip), grid tiles, and a Warband-style total in the panel header (960 possible; Archive ladder verified 5/15/35/65/70; feats 0 so no hidden-feat leak). Epic left clean — `framed={legendary:1,feat:1}` in `_mkMoment`, add `epic:1` to enable. **NEXT (owner call): frames on the achievement-page TILES — frame the current modal cards now, or defer to the Trophy Hall where tiles become mini-toasts. Then the Trophy Hall — a **maximized OVERLAY, not a page** (grow `#ach-modal` to full-screen; tiles become mini-toasts that carry the frames), Phase 2.**
- **✅ The full 57 is CATALOGUED DURABLY at `docs/achievements_roster_57.json`** (2026-07-11) — 57 achievements, ALL with `roast` (default/spicy) + `roast_nsfw` (unhinged), buckets 29 ladder/9 milestone/8 mastery/11 feat. This is the canonical roster file; it no longer lives only in artifact `31d6c68a` or chat. **Tabled-ideas check:** the 5 workshopped feats (Triggered, For the Viewers, Read the Manual, The Lexicon, Since the First Floor) are all IN; The Descent is deliberately shelved (owner). Room for ~3 more (60 ceiling).
- **⬆ PARKED IDEA UPGRADED (2026-07-12 evening):** owner cooked 5 NEW casting-bar renders (celestial gold/silver + a literal **moon-phase progress gauge** — waning→full→star→gibbous→crescent, segmented fill track, gold+amethyst end-caps) in the Selection v3 artifact (`812e82b4`) "Bonus: WoW UI bars" section. The moon-phase one is near-finished-asset quality and directly enacts the app's own name — this bumps the feature from "someday" toward "seriously consider soon." Original verdict below still holds for the wider casting-bar system design.
- **Original PARKED note (real potential, Claude viewed the art 2026-07-11):** owner's `Potential… items?` collection + catalog (78–102 rows) hold WoW-style void-purple-metal cast-bar FRAMES + bronze/teal sliding tracks on #00FF00. **Best fit = a themed "casting" progress bar for generation/render** (thematically perfect — you're casting a gen), plus ladder-achievement progress + Panel job progress. **Caveats:** it's a real UI build (art = the FRAME, dynamic fill composited inside via 9-slice so ornate ends don't stretch); prefer the CLEANER rounded frames over the maximalist spiky-lightning ones for constant on-screen use. Park like the Foundry/Provider epics — not tonight.
- **BADGE THEME — Claude viewed all 52 Part Deux gens (2026-07-11): the set is COHESIVE and confirms the anchor.** Tiered ring working (blue-steel rare = books/frames · amethyst-gold epic = dragons/masks · royal-gold legendary = cathedrals/cinematheque/conclave), violet field + cardinal gem accents + scene-inside, keyed on green. The "duplicates" are a SELECTION TRAY (~4–6 variants/achievement). Remaining work: (1) pick winner per slot, (2) key the few on purple/transparent, (3) gen the ~40 gaps in this style. One outlier = the flat clapperboard (decide: keep flat "ward" look or ring it to match).
- **✅ Toast "moment" v2 SHIPPED (2026-07-12):** the unlock moment is the locked `335ef4e7` design verbatim — medallion sweeps R→L into the cap (+ring pulse/ding), mascot leaps from the TOP edge over a tier glow, "New Achievement" eyebrow, roast on the read-along shimmer, metallic rarity pill w/ sheen, rarity-scaled hold + legendary/feat flash, click-to-dismiss, queued. Summary (>3 unlocks) shares the frame. Feat = gunmetal band/pill + ruby glow + ruby cap rim. Browser-verified (feat: gunmetal `rgb(138,147,162)` band + ruby `rgb(224,53,94)` glow/rim; epic: real badge art loads + amethyst band).

---

## 2b. Achievements PHASE 2 — "the Trophy Hall" (✅ SHIPPED 2026-07-13, v1.11.0, `loom-v2`)

**✅ SHIPPED (commits `8836086` backend foundation + `911b2ef` Hall, 466 tests green):** the achievement
window is now a **maximized full-screen overlay** (grew `#ach-modal`, scoped to `.ach-hall`; NOT a
page) — banner header + points total + search, **Summary / All / Statistics** tabs, a Summary landing
(Recent Achievements from `earned_at` + Progress Overview bars), the bucket grid as collapsible tile
sections (via the `/badge-thumb` cache), a right rail (category nav · Within Reach · Rewards Earned ·
mascot alcove), and mobile stacking. Backend: earn-date persistence + badge thumb-cache (A0). Runtime-
verified (mock payload) across every render path. **Owner's WoW screenshots now tune the INTERIOR only.**
**Deferred polish:** per-*tile* ornate frames (toast has them), ~~per-criteria checklists on set
achievements~~ (⏳ IN FLIGHT 2026-07-13, see below), ~~owner-made mystery-tile art~~ (✅ SHIPPED
2026-07-14, see below).

**✅ Mystery-tile art SHIPPED (2026-07-14, commit `43014ef`).** Masked feats showed a plain grayscale
`❓` emoji before this; now use the owner's own cloaked-Nel artwork (`SecretCurtainSquare.png`, sourced
from `Downloads/7.12`, downsized 2000×2000→512×512, served at `branding/mystery/secret_feat.png`).
Shown in **full color, not grayscaled** — a pre-existing `.ach-card.t-feat.masked .ico` rule was
force-graying it, changed to `filter:none` since the art is meant to read as an intentional tease
(you can see *something*, just not the name/criteria) rather than a disabled state. Name/description
still masked server-side as before (`"???"` / "A hidden feat of the Athenaeum.") — no spoiler risk,
a bare badge image with no text doesn't tell you what unlocks it. `SecretCurtainRectangle.png`
(badge-in-center composition) banked for a possible future reveal-moment treatment, not used now.

**✅ RESOLVED 2026-07-15 — reverted, not fixed-in-place.** `c877919` was reverted clean
(`0a8da3a`, inverse diff, zero conflicts — every commit in between was docs-only). The Hall is back
to the pre-reformat rail-rewards/plain-grid layout, confirmed with an actual rendered screenshot this
time (not just computed-style checks — see the lesson below for why that distinction matters). Tests
still 474/474. **This does not mean the Hall redesign is abandoned** — the owner is building a Figma
mock (screenshot-decomposition of the real app + a proper carousel/"lightboard" treatment for the
ladder rungs) as the actual pixel source of truth, and the Hall is getting renamed as part of that
rebuild. Treat the revert as returning to a known-good baseline to design forward from, not as the
final answer. D: was independently rolled back further by the owner (to the point custom
Legendary/Feat frames were introduced) and is not necessarily in sync with this C: revert point —
don't assume the two match without checking.

- **What actually landed:** rewards moved from the narrow 290px rail into a `.hall-rewards-bar`
  spanning the full grid width (rail widened 290px→370px); `.ach-card` restyled toward the unlock
  toast's visual language (64px badge, tier-colored top accent, `minmax(340px,1fr)` columns);
  ladder-bucket achievements grouped by `metric` client-side into a horizontal depth-carousel
  (current rung centered/full-color/spotlight-glowed, others recede + grayscale by distance).
- **Why "shipped" was the wrong word:** every check that session was a `getComputedStyle`/DOM-assertion
  call (grid-template-columns, rung scale/opacity/grayscale math, element presence) — genuinely correct
  readings of *those specific properties*, but never an actual look at the rendered page, because
  screenshot capture was unreliable all session and I leaned on programmatic checks instead of pushing
  to get a real visual. That gap is almost certainly how something is wrong without having been caught —
  a real screenshot or the owner's own eyes would have said differently than the computed styles did.
  **Lesson for next time:** for a visual/layout task specifically, a passing `getComputedStyle` check is
  not equivalent to "verified" — get an actual rendered view before claiming done, or say plainly that
  visual confirmation is still outstanding instead of reporting success.
- **Owner's exact words:** "Well you fucked that up." No detail yet on what's wrong specifically.
- **Next step (Thursday):** re-open the Hall with the owner watching, find out exactly what's broken
  (layout overlap? carousel rendering wrong? toast-cards illegible? something else entirely?), fix it
  for real this time, and get an actual visual confirmation — screenshot or the owner looking at it
  live — before marking this done again.

**⏳ IN FLIGHT (2026-07-13, this session) — quick wins A + B:**
- **A · per-criteria checklists (set masteries):** the two CLOSED-universe set masteries — **Full Toolbox**
  (`tools` = edit/enhance/fix) and **Master of the Loom** (`video_modes` = i2v/flf/r2v; V2V is NOT tracked) —
  get a ✓/○ checklist on their Hall tiles so you see WHICH criterion is missing, not just `2/3`. Open-ended
  sets (loras, enhance_workflows) stay count-only. Impl: pure `achievement_criteria(sets)` + `_ACH_CRITERIA`
  map → threaded into `compute_achievements(…, sets=)` → rendered in `card()`; unit-tested.
- **B · roster threshold reconcile:** aligned the 3 stale thresholds in `achievements_roster_57.json`
  (marathon 1→100, triggered 0→5, read-the-manual 0→1) to shipped code; cleared the `DOC_MAP` stale note.
- **C · epic frames: DEFERRED — owner deciding art style.** Wants epic to read "deep-purple WoW epic /
  tier-gear," leaning **Nelnamara's Dreamwalker (feathers) + Balance-Druid Moonfire flair**, WITHOUT
  out-shouting legendary-gold / feat-ruby. Suggestions delivered this session; art TBD.
- **D · Loom picker cohesion:** to discuss next (owner-flagged §1 refinement).

_Original design notes (now realized) below for reference:_

**A0. PREREQUISITE — badge serving cache:** the 57 badge masters total **321 MB** (2000² PNGs, vernissage alone 8.4 MB) served raw into 46px cards; a 57-tile Trophy Hall would pull all of it. Build a branding thumb cache (server auto-generates ~256px copies, masters stay the source of truth) BEFORE the Hall renders all 57. Also on record: 4 badge masters are sub-2000² (eclipse 416² · gallery-opening 597×504 · first-cull 1024² · starsmith 1024²) — owner may re-export for uniformity, not blocking; mascots/ach are native chibi-cutout sizes (~400–600px), fine at toast display sizes.

**A-ref. WOW SCREENSHOT ANALYSIS (owner supplied 2026-07-12; "nothing this ornate", "simpler sidebar on the RIGHT"):** ideas adopted into the Hall plan — (1) **Summary landing**: Recent Achievements rows (needs NEW earn-date persistence in achievements.json) + Progress Overview (overall + per-category bars); (2) **Statistics tab**: label/value rows from the existing telemetry/metrics bundle (nearly free); (3) **per-criteria checklists** on set-based achievements (Full Toolbox/Master of the Loom/Skin Changer etc. — telemetry sets already hold members; expose contents, not just counts); (4) toast-banner archetype validated; 9-slice frames may carry transparent-margin corners so flourishes overflow the toast rectangle; (5) search box. SKIPPED: shields, nested subcats, heavy chrome. **OWNER CALLS PENDING:** points economy y/n (roster's "feats worth no points" implies tiers could carry points) · Summary landing vs straight-to-grid · right-sidebar contents (nav + mascot + detail?).

**A-decisions (OWNER LOCKED 2026-07-12 evening):** (1) **POINTS ECONOMY: YES** — `points = tier base + 5×(rung−1)` for ladders, flat base for one-shots, feats = 0; bases common 5 / rare 10 / epic 25 / legendary 50 (e.g. Archive ladder: 5/15/35/65/70); Warband-style total in the Hall header; data-driven, "can evolve as needed"; NOTE: re-add the `rung` field to the code roster (dropped as unused). (2) **FRONT DOOR: Summary landing** (Recent Achievements rows + Progress Overview bars), sections one click away. (3) **RIGHT SIDEBAR, top→bottom:** banner → simple category nav → chibi mascot alcove (tooltip/chat-bubble emotes) → bottom = Recent Rewards chips + "Within Reach" (3 closest-to-earning w/ mini bars). Frames in production on **Krea2 via Maestro** (prose prompts issued; overflow-corner technique). Reward ribbons stay emoji (owner: nice-to-have, not needed).

**A. The panel → maximized overlay (decided direction), "the Trophy Hall" (`b-ach` hue exists):**
1. Wider layout; tiles become **mini-toasts** (same design language as the shipped toast v2: cap + band + body).
2. **Right rail**: detail/tooltip pane + a mascot presence + rewards display (ties to C2/C3); room for future ideas.
3. **Banner header** for the panel (the 201-banner pool; possibly where banner rewards display).
4. **Feats more mysterious** — owner wants them NOT visible unless earned. Two modes on the table: (a) truly hidden (server omits; section shows count only), (b) mystery tiles obscured by owner-made mascot art. OWNER CALL with screenshots.
5. **Collapsible category sections.**
6. Form factor: **LOCKED = MAXIMIZED OVERLAY** (owner-confirmed 2026-07-13 via the pinned chat section "🎨 1.6 — the best-of-both answer"). **NOT a page/route** — grow the existing `#ach-modal` to full-screen: instant open (DOM already there, zero nav / zero reload), gallery stays mounted behind it, ESC out, can animate open from the 🏆 button. Page-scale real estate for wide mini-toast tiles + banner header + right rail + collapsing sections. **Screenshots tune the INTERIOR only — the form factor is settled.**

**B. Toast refinements:**
1. Badge bigger / "grows as it hits its home marker" — owner articulating the idea separately. AWAITING.
2. **Real SFX** replacing the synth chimes — build a drop-in `branding/sfx/` loader (per-tier ogg, fail-soft to synth). Sources: Kenney (CC0), Sonniss GDC, freesound CC0, OpenGameArt; Pinokio lane = Stable Audio Open (local SFX gen) to scout on request. Owner has 1–2 WoW sounds (their call, local app).
3. Legendary/Feat need MORE: ornate 9-slice frame art (owner-generated — SAME tech as the parked cast-bar frames), god-rays/vignette/particles.
4. Mascot pop height: make seating ADAPTIVE per image (read natural size, seat ~75% above the toast band) instead of the global 158px headroom.
5. **✅ Animated chibis: PIPELINE PROVEN LIVE (2026-07-12).** First animated presenter shipped (Happy Horse 1.1 gen → keyed → in-app, owner: "ZOMG they look great"). The pipeline: gen on flat #00FF00 (models repaint it as their own studio green — the keyer tolerates it) → drag mp4 onto `D:\Art Scratch\make_anim_webp.bat` (ffmpeg keys/de-spills → **Pillow assembles**; ffmpeg's own webp muxer writes broken blend/dispose flags = frame-trail smears, never use it for assembly) → drop as `mascots/ach/<id>.webp` (loader tries .webp before .png, `d00b39d`). Companion helpers: `make_green_source.bat` (still → green field for i2v) + `_assemble_webp.py`. GOTCHA for viewers: browsers/Photos render transparency as WHITE — verify on a dark canvas or in the app. Known cosmetic: soft despilled ground-shadow survives keying (reads fine on the toast; tunable on request).
6. **REGRESSION to fix:** the mockup-verbatim port dropped the screen-wide fanfare — restore stars + confetti at screen level for legendary + feat ("make the screen blow up a bit").

**C. Rewards & skins:**
1. Skins move out of the panel bottom → **Control Panel beside Branding** (cosmetics live together).
2. Reward notice ON the toast (mini ribbon/sub-toast: "unlocks <skin>/banner") + rewards shown in the right rail on replay (speech bubble from the mascot presence).
3. "Earned rewards" as its own display — shape TBD with the redesign.

**✅ Quick wins SHIPPED (2026-07-12, owner-green-lit):** B2 sfx loader (drop `branding/sfx/ach_<tier>.ogg` → plays; missing → synth chime) · B6 fanfare restored (screen-level stars+confetti for legendary gold / feat ruby-gunmetal) · B4 adaptive mascot seating (alpha-bbox measured per image, ~75% of the character above the band) · C1 skins→Control Panel card beside Branding (ach modal now links there) · C2 toast reward ribbon (🎁 skin / ⚑ banner, emoji pending owner art). Browser-verified on isolated real data; 459 tests green. **Feat obscurity DECIDED: mystery tiles under owner-made art (design pending). Panel direction leaning MAXIMIZED OVERLAY (modal fluidity + page real estate) — final with screenshots.**

---

## 3. Achievement ART — the STYLE ANCHOR + reconciled picks

### 3a. THE STYLE ANCHOR (the fix for the off-brand briefs)

From `docs/ART_PROMPTS.md` (L164–187), owner-confirmed. **The house badge style is a TIERED RING over a FIXED violet/emerald field — NOT a universal gold frame.** Gold is the *legendary ring only*.

**Canonical 11-badge template (verbatim):**
> A circular World-of-Warcraft-style achievement emblem, an ornate **{RING}** ring with a soft glow, **{ICON}** centered inside on deep violet (#33236d), lavender highlights (#b692e6) and a faint emerald inner glow (#4fc99a), polished and iconic, reads clearly at small size. Flat pure-green #00FF00 background, no shadow, no text.

**Ring by tier:** common → `weathered silver` · rare → `polished blue-steel` · epic → `ornate amethyst-and-gold` · legendary → `radiant royal gold`.

**Fixed for every badge:** field `#33236d` · highlights `#b692e6` · emerald inner glow `#4fc99a` · flat `#00FF00` cut-out · 256×256, reads at ~64px.
**Palette (say the hex):** ground `#0c0a1c`, violet `#33236d`/`#643aac`, lavender `#b692e6`, mauve `#c4a6f0`, gold `#d4af37` (sparingly), emerald `#4fc99a`.

**Prompt-craft ruling (owner):** for badge BATCHES use the **simple single-paragraph template above** — NOT the LOCK-block / NOT-fence / fixed-seed machinery (that's reserved for one-off brand marks + character sheets). "Simple is king" for these. *The rejected briefs broke exactly this — flattened the tier ring to always-gold and over-scaffolded.*

**✅ RESOLVED via gallery ground-truth (2026-07-11).** Parsed the owner's `Moonglade Icons/Badges Part Deux` collection (52 real gens) in `catalog.db`. It holds BOTH styles side by side: (a) the OFF-BRAND rejects — universal "ornate polished GOLD ring filigree, crown-grade polished gold, radiant amethyst-purple aura" (my briefs: Menagerie/Starsmith/Cinematheque) — and (b) the GOOD canonical set = the **docs TIERED RING executed exactly**: Archivist "ornate polished **blue-steel** ring + open ancient tome" (rare), Gallery Opening "blue-steel ring + empty picture frame", Hoardsmith/Menagerie/Tagsmith "ornate **amethyst-and-gold** ring" (epic) — Menagerie even carries the exact hexes #33236d/#b692e6/#4fc99a. **VERDICT: the tiered ring is correct (blue-steel rare · amethyst-and-gold epic · royal-gold legendary over the violet field), NOT universal gold.** Owner's evolution ON TOP: some badges swap the single flat icon for a **small SCENE inside the ring** (e.g. "grand elven library entrance with spires + glowing tomes floating like birds"). **Write the new prompts to: tiered ring + optional scenic icon; reject the universal-gold flat versions.** (The earlier v1–v4 doc variation is superseded by this ground-truth.)

**TIER-COLOR SCHEME — owner wants WoW-rarity literacy (green/blue/purple/orange). DECISION PENDING owner confirm (2026-07-11).** Part Deux is already ~75% there (rare=blue ✓, epic=purple/amethyst ✓, legendary=gold ✓). Two collisions to respect: (a) **common = green ring FIGHTS the #00FF00 green key** → put green on the GEM+GLOW, not the ring; (b) **epic = purple ring FIGHTS the #33236d violet field** → keep epic purple BRIGHTER than the field. **Recommended scheme (rarity carried on GEM+GLOW, ring reinforces):** common → silver ring + emerald-green (#4fc99a) gem/glow · rare → blue-steel ring + sapphire-blue gem/glow · epic → amethyst ring (less gold) + bright-amethyst gem/glow · legendary → gold ring WARMED toward amber/orange + rays · feat → most-ornate gold, UNIQUE per-feat (obsidian+gold), no tier uniformity. **Downstream consistency:** the code toast tier-glow colors + rarity pill (pixai_gallery.py; currently common=steel-blue #9fbad6) must be realigned to match whatever badge scheme is locked. **PRE-GENERATION LOCK-LIST:** (1) tier-color scheme (2) green on gem/glow not ring (3) legendary→orange (4) feats distinct (5) icon-vs-scene per achievement (6) toast+pill colors realigned (7) 64px readability on scene-heavy ones (8) gaps to fill + winners picked from dupe tray.

### 3b. The 11 shipped badges — art picked, swap pending

Old ornate versions are serving on D: now. The **2026-07-07 owner vote** picked upgraded art (F#/G# codes): First Light→F8 · Archivist→F39 · Hoardsmith→F34 · Loremaster→F31 · First Frame→G56 · Moonweaver→G38 · Reel Director→F27 · Curator→F22 · Menagerie→F14 · Gallery Opening→F43 · Tagsmith→F11. **Swap not yet executed.**

### 3c. ⚠️ CONFLICT to resolve (owner call)

The **session ledger** (my picks, Z-codes) disagrees with the **2026-07-07 vote** (F#/G#) on the 11 — e.g. First Light Z12 vs F8, Reel Director G50 vs F27, Menagerie "generate" vs F14, Gallery Opening "chibi #1 Nel+Mio" vs F43. Three numbering universes (F#=PixAI batch, G#=Grok slices, Z#=zip) are **not reconciled.**
**Recommendation:** the 2026-07-07 vote is authoritative for the 11 medallions; the ledger is the later opinion for the un-locked 46 + a re-open flag on Gallery Opening (badge vs the Nel+Mio chibi).

### 3d. The other 46

- **Mascots: DONE** — every one of the 57 has a finalized `art_candidate` chibi #.
- **Badges: 16 seeded, 41 still need a pick.** Ledger tally for the full 57: 9 locked · 22 in-pool · 24 generate · 1 special · 1 banner.
- **The Great Library** = BANNER reward, not a badge (banner art ← G65–G67).
- Full per-achievement mascot+badge table lives in roster board `31d6c68a` + ledger `d1ee39a1`.

---

## 4. Image consolidation (owner's active task)

- **Served (KEEP live):** `D:\Moonglade Athenaeum\pixai_backup\branding\` — badges (11), mascots (10), marks (5 +ico +marks.json), banners/logo/favicon/starfall a-v. The app serves from here.
- **Staging (Downloads):** Icon Sheets (23) · Icons (19) · grok-group (26) · grok-assets (6) · Chiblis (217, deduped chibi library) · Chibli Sheets (35) · Chibli Stickers (1) · export-20260709T231731Z-1 (463 — full Canva account dump, **cherry-pick only**) · loose from-PixAI (7) / Gemini (8) / grok-* (55) / Untitled design (4) · scratchpad `menagerie_badge` (4 — tonight's gens).
- **Stale duplicate (flag, don't auto-delete):** `C:\Users\gwilkins\Desktop\pixai-gallery-backup-master\pixai_backup\branding` (marks + banners only).
- **✅ CONSOLIDATED (owner, 2026-07-11) → `D:\Art Scratch\`** — the art-IN-PROGRESS home; all working art lives here now. Structure (675 files): `Badges` (26) · `Icon Sheets` (23) · `Chibli Sheets` (35) · `Canva image dump - sorted by claude - new items added` (525) · `Live Nel Cutouts` (8) · `Nelnamara Fine Images` (29) · `Surprise flair the original ogs` (9) · `App icon candidates` (4) · `Banners` (8) · `logos_cut` (5) · `Stickers` (1) + loose `DCC-micdropNel.png`. The served `D:\...\branding\` set stays live + separate. Good moment to scaffold `mascots.json` (asset→role registry).

---

## 5. Next actions (notated — NOT started)

| Who | Action |
|---|---|
| **owner** | Flag favorite badges into a gallery collection → I pull their prompts + realign the badge briefs to §3a |
| **owner** | Consolidate images → `art-library\` (see §4) |
| **owner call** | Resolve the F#/G# vote vs ledger conflict for the 11 (§3c) |
| **owner decision** | Loom in-Loom ref-gen scope (§1 next-1) |
| **NOW → owner** | Generate the **40 blank badges** from `docs/badge_generation_prompts.md` (written 2026-07-11, Solid Style) → keepers into `D:\Art Scratch` → then a NEW roster board from `docs/achievements_roster_57.json` |
| **later** | Execute the 11-badge swap · then wire 46→code (telemetry layer) |
| **later** | Rebuild roster board `31d6c68a`: **BIGGER cards + previews** (owner readability), KEEP layout + faceted sort + style; fresh rebuild AFTER new art is generated. Owner returning with a "final submission" first — HOLD until then. |

**FLOW (SUPERSEDED 2026-07-11 evening — owner flipped it):** the board is now the selection tool, built FIRST. **Roster board `31d6c68a` REBUILT + republished (same URL) 2026-07-11:** FULL RESET of all badge+mascot selections (incl. the 11 live — their art is back in the pool as `P:*`; the F/G/Z-vs-ledger conflict is mooted). Three voting lanes: **Nel / Claude (pre-seeded: 51 badge votes + 57 mascot seeds from prior assignments) / Family (wife+daughter)**. Pools embedded: Part Deux 52 · **Part Tree 133 (incl. Edit Pro keepers, confirmed mirrored)** · Art Scratch\Badges 46 · legacy G/Z/P 134 · 332 chibis · 8 banners (Great Library slot only). Features: per-achievement picker w/ auto-grouped "For this" tab · **▶ toast preview** (lifted from toast_mockup `335ef4e7`, plays the real unlock moment w/ selected art) · NSFW roast toggle · bucket + general notes · JSON/summary export w/ verified copy buttons · localStorage persistence. **Board v3 (2026-07-11, same URL):** REFRESHED the mascot pipeline — re-deduped the entire Canva dump (406→312 unique, tight perceptual thresh so distinct chibis aren't merged), VISION-classified every survivor → **300 clean chibis + 9 badge-art rescued to the badge pool + 3 grids dropped**; Carl/DCC (#311) + mic-drop (#312) folded in. Mascot thumbs now **208px WEBP-with-ALPHA** (was 150px flattened — that was the "preview looks bad"). Badge picker consolidated **8 tabs → 2** (For-this + All(432) + id-search, e.g. `CB`=canva badges, `MI`=originals). One-time **localStorage pick-migration** (`st.v→3`, `D.remap` old#→new#) preserves in-progress votes across the renumber; badge picks are pool-ID-stable. Source of truth for pools: `scratchpad/pools_v3.json` + `refresh_unique.json` (idx→disk path). **Next: owner+family select → export → Claude wires winners into `branding\` + manifest → gap list → gen run (PixAI Tsubaki prose recipe) → telemetry layer.**

**Local-gen reality check (2026-07-11 · UPDATED 2026-07-12): Krea2 on Maestro is the new local quality lane** — owner: "we hit the motherload" on the legendary/feat frame run; ornate-effect prompts "just come through." First local model to meet the house art bar; prefer it for frames/ornament work going forward. **CORRECTION (same day):** some frame/icon renders in the 2026-07-12 haul carry real alpha because the OWNER keyed them by hand before sharing, not because Krea2/ComfyUI/ChatGPT output alpha natively — don't assume any of these tools produce transparent output on their own; verify per-file, not per-model. (Prior state: Maestro Flux/Chroma + Forge WAI infra worked but neither matched the badge bar — the benchmark is **PixAI Tsubaki.2 v1, detailed prose, NO LoRA** (the Hoardsmith dragon, task 2031115782282256404). Model research (Track 2) ✅ DELIVERED 2026-07-11 → **`docs/MODEL_DECK.md`** (25 verified entries + methods; artifact 9f16f42d). Headlines: WAI v11→**v17** upgrade (no token) · NoobAI-XL V-Pred = crispness lane (vpred settings mandatory) · badge stack = Game Icon Institute V4_XL / ZavyChromaXL+Zavy Fantasy Icons LoRA (glow trigger) / game-icon-XL LoRA (full-frame icon LoRAs WANT high weight — the overcook rule inverts) · SpatterXL verdict: SKIP (dated; Black Magic absorbed the look) · lifelike = Illustrij/Equinox/Semi-Real MM + Chroma1-HD prose recipes · **train Nel LoRA locally on Illustrious via OneTrainer (12GB ok; 50-150 imgs; FLUX.1 via FluxGym ok, Flux2/Chroma = cloud)** · Pinokio adds: ComfyUI, BEN2 bg-remover (green-key killer), Invoke · newcomer to watch: Anima (Cosmos 2B, ComfyUI). Next: owner picks downloads → bake-off vs Tsubaki dragon benchmark. Loom ref-gen call ✅ DECIDED → see §1 "Loom V2.1" official plan (A+bridge, rail layout, after achievements). Board v2.1 republished same URL with Originals (74, `Moonglade Icons` collection) + 201 banners (7 Art Scratch + 194 `Moonglade Banners` gallery); Add-On/App Icons (227) deliberately excluded like the Canva dump.

_Superseded/older roadmap artifacts (kept for provenance, not authoritative for these threads): 51a7931d, a67437b9, placement_report, Final Placement, Assignment Board. This doc supersedes them for Loom V2 + Achievements._

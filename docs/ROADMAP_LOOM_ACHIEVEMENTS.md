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

## 1. Loom V2 — built, working, one decision from mergeable

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
   - **⚠️ MAJOR — design drift surfaced (2026-07-14, owner).** Owner described a substantially different Timeline vision than anything built or found in any artifact: **Timeline as a fixed drawer attached to the top banner** (not a draggable panel) — full page width, default visible at a slim height, fully collapsible to hidden, pulling down extends it to a set size showing the **video preview ABOVE the scrubber** (not beside it, as the one located mockup showed). Checked `loom_mockup` (artifact `8bd885e1`, 2026-07-10) — it does NOT match: timeline there is 55%-width (not full), preview sits BESIDE the track (not above), and its own Legend panel literally lists *"Timeline: dock‑collapse vs drag‑open?"* as an **open, unresolved question** at the time. The owner's fuller vision (this + panel snap/dock + multi-track timeline) apparently came from an unrecoverable "weekend" conversation — searched this session's full transcript, only this message matches. **Nothing built yet — this needs its own scoping pass.** Three components tangled together, sized separately:
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
achievements~~ (⏳ IN FLIGHT 2026-07-13, see below), owner-made mystery-tile art (masked feats reuse the cloaked-card look).

**🎨 Layout mockup tool (2026-07-14) — owner is hand-arranging the Hall's regions.** Owner wants to
propose their own spatial layout rather than have it dictated from the shipped defaults. Built a
standalone drag+resize mockup artifact (7 blocks: header, tabs, main grid, category nav, within-reach,
rewards-earned, mascot alcove — matches the shipped default positions as the starting point) on a
1400×820 canvas with a 16px grid (same convention as the Loom's snap-to-grid), live x/y/w/h readouts,
and a copy-JSON export so the owner's final arrangement comes back as exact numbers, not a screenshot
to eyeball. **Owner sent a first revision (2026-07-14)** widening the rewards-earned lane to full grid
width (1008px, room for real text labels like "Unlocks skin: Ember") and moving it below the grid
instead of a cramped vertical sliver — confirmed there's still comfortable room for full 680px toast-width
cards in the main grid column at that size. **Still awaiting a final locked arrangement.**

**🎨 Ladder-family display — LOCKED (2026-07-14), not built:** a straight list of every rung breaks
badly once toast-styled cards land in the grid. Locked direction: a **horizontal depth-carousel** per
ladder family, current/next-unearned rung centered + full-size + full-color, earned rungs recede to the
left and locked ones recede to the right, each step smaller + more desaturated by
`distance = index - currentIndex` (`scale: max(.55, 1-|d|*.15)`, `opacity: max(.4, 1-|d|*.18)`,
`filter: grayscale(min(1,|d|*.3))`). **Grayscale, NOT blur** — owner's call after comparing: blur
destroys medallion legibility at these small icon sizes (fine for photos, bad for small badges you
still need to identify at a glance), grayscale keeps the shape readable while still reading as "not
the current focus," and is cheaper to render. **Plus a spotlight glow** on the centered/current rung —
a soft light halo blooming from behind it (radial gradient / glow, not just size+color) so it reads as
genuinely illuminated, not just "bigger." **No scroll/drag needed, confirmed against the real roster:**
longest ladder family is The Archive at 5 rungs (First Light → Archivist → Hoardsmith → Loremaster →
The Great Library); everything else is 2–4. All rungs always fit at full size in any reasonable panel
width — the overflow/clip/drag question from the first pass at this design is moot, not deferred.
Static/computed-at-render, no JS animation needed.

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

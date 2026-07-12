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

## 1. Loom V2 — built, working, one decision from mergeable

**State (git + transpile verified):** branch `loom-v2`, **6 commits ahead of master, unmerged**, transpiles clean. A **non-breaking opt-in overlay** behind a "V2 layout" toggle; classic waterfall Loom is default and untouched. All V2 code in `loom/master-storyboard.jsx`.

**Locked design:**
- **6-panel layout** (shipped verbatim as `V2_DEFAULT`, canvas ~1498×820). Coords (x,y,w,h):
  - Timeline & preview `0,0,1498,271` (full-width top) · Asset bin—footage `5,275,286,538` · Cast & assets `301,276,255,284` · Legend & notes `301,565,256,244` (STATIC) · Acts & shots (board) `562,278,628,536` · ⚙ Generate—shot `1198,276,294,540` (full-height).
  - The "alternate, fixed" layout: Generate full-height, Cast wider, board narrowed so it clears Generate. Persists to store key `storyboard:v2:layout`.
- **Selected-shot interaction model** (owner-approved via `loom_selectshot`): click a shot → binds Generate + panels to it; LOUD selection (gold ring + timeline glow + name in headers); two-way live edit; double-click = deep-focus modal; board never moves in place.
- **Collapsing:** timeline collapses to keep just the scrubber; app banner header = "Collapsing" mode (sticky 260px, collapses on scroll; modes Collapsing/Always-slim/Off). Banner default = mark **#62**.

**Wired / working (browser-verified):** V2 toggle · error boundary · layout persistence · real acts&shots board · timeline reel + `ShotPreview` trim · Cast (toggle refs, +add from gallery) · static Legend · Footage grid · **Generate VIDEO tab fully functional** (real `generateShot`, mode/prompt/duration/continuity/camera/lighting w/ palette chips).

**Stubbed / NOT in V2 yet:**
- Image / Edit / Reference generate tabs are **placeholders** (only Video generates).
- **Cannot add shots** in V2 (cards are select-only).
- **Cannot set open/close frames** in V2 (`FrameSlot` exists but not reparented into Generate).
- Timeline collapse-to-scrubber is **buggy**; no snap-to-grid; no double-click deep-focus in the overlay yet.

**⚠️ NOT ready to ship as a standalone workspace** — it still needs classic Loom for add-shots + frame-setting. (I wrongly said "just merge it" once; retracted.)

**✅ DECIDED (owner, 2026-07-11) — OFFICIAL PLAN: Loom V2.1 "drawer-ized" build. NEXT MAJOR BUILD after the achievement implementation.**
The ref-gen question is resolved as **Option A + bridge** (supersedes the open decision below):

1. **Shared Generate drawer mounts in the Loom** (same component as the gallery — one mental model) with a **shot-context bridge**: bound-shot chip at top · refs pickable from Cast/Footage · **output routing** one-clicks on completion (→ open frame · → close frame · → cast · → footage bin). Delivers the original "Edit-deck" per-shot pitch via the shared component. Mostly wiring: drawer already emits media_id; Loom already has FrameSlot/Cast/Footage targets.
2. **Rail layout (progressive disclosure):** Timeline+preview collapses to a slim top scrubber strip (fixing the existing buggy collapse as part of the feature) · Generate collapses to a right-edge icon rail (✦ image · ✎ edit · 🎬 video · 🖼 ref) that expands on demand, gallery-drawer muscle memory · center panels (Acts&Shots board, bins, Cast, Legend) become dynamic reflowing panels using the existing layout-persistence store. Scene builder gets the real estate by default.
3. Folded-in mechanicals: add/reorder shots · reparent `FrameSlot` into Generate · double-click deep-focus · snap-to-grid.
4. **Estimate ~two focused sessions** (1: drawer mount + bridge routing · 2: collapse states + reflow + mechanicals), then `pytest` + merge `loom-v2 → master` (`--no-ff`).

**Sequencing (owner-locked):** Achievements first (board selection → wire winners → telemetry layer) → **then Loom V2.1**.

**⏳ V2.1 INCREMENT 1 BUILT (2026-07-11) — the shot-context bridge, in `loom/master-storyboard.jsx`:** the dead **Image tab** now generates a reference image for the selected shot — model picker (via `/api/model-search`), image-prompt + "seed from shot", "✦ Generate reference image" (reuses `/api/generate` + spend-confirm), and **output routing** buttons (→ open frame / close frame / cast) that patch the shot so the gen feeds its video render. App-level `genImage`/`pollImg`/`routeImg` + `genImgState`/`imgModel` state; passed to `LoomV2`. **Verified live:** renders, model search returns hits, selection binds. **Bug found+fixed:** seed button called `shotText` (App-scoped, not in `LoomV2`) → crashed on click → rewrote seed inline from card fields. **⚠️ ENV: live server runs from the D: run-copy (`D:\Moonglade Athenaeum\`), NOT the C: repo — edits made in C: (loom-v2) AND synced to D: so the live server serves them. The two loom-v2 checkouts are at different commits (C: eeb1c0a vs D: 2673936) — pre-existing cross-machine drift, DON'T mass-commit-fix (per CLAUDE.md); the loom .jsx itself matched.** C: repo changes are UNCOMMITTED (owner to commit/reconcile). **Remaining V2.1:** rail layout · reparent FrameSlot · add/reorder shots · Edit/Reference tabs.

**✅ MULTI-PROJECT PERSISTENCE (2026-07-11) — the long-standing "only one project persists" gap, closed.** The Loom now saves multiple named storyboards: each lives at `storyboard:v2:proj:<id>` in the existing server-side KV store (`out_dir/loom/store.json`), with an `active` pointer and a header **switcher** (New · Open · Duplicate · Delete; Rename via the name field). The legacy single-key project (`storyboard:v2:project`) **auto-migrates** in as storyboard #1 on first load and is preserved untouched as a backup. No new server code — reuses `/api/loom/get|set|list|delete`. **Verified end-to-end** on a copy of the real store: migrate → new → switch, name + content intact, no crash. Known v1 gaps (follow-ups): switcher lives in the classic header only (not the V2 rail yet); popup closes on action/toggle, not yet on outside-click.

*(Superseded original decision list, kept for provenance:)*
1. ~~[BIG DECISION] In-Loom ref-gen scope~~ → resolved: A+bridge.
2. ~~Reparent `FrameSlot` into Generate~~ → folded into V2.1 item 3.
3. ~~Polish: collapse-scrubber bug · deep-focus · snap-to-grid · add/reorder shots~~ → folded into V2.1 items 2–3.
4. `pytest` + merge — unchanged, end of V2.1.

---

## 2. Achievements — the system (code)

- **Code ships 11 feats, FULLY WIRED:** `compute_achievements` (pure/data-driven), badge `<img>` render (modal grid + the mid-screen "Nel presents" moment), rarity toast, per-tier chimes, 5-skin system. 450 tests green.
- **The 11 badge PNGs + 10 mascot PNGs ARE ON DISK and serving:** `D:\Moonglade Athenaeum\pixai_backup\branding\badges` (11) + `\mascots` (10). *(The source repo has none — it reads branding from D:. Do NOT re-derive that badges are missing.)*
- **The 57-roster is DESIGN-COMPLETE but only 11 are in code.** 11→57 = a **~19–30-counter telemetry layer** (built from scratch; every current metric is a catalog COUNT) + `roast`/`roast_nsfw` fields + the NSFW "unleash" toggle. Mechanical, **later** — not tonight.
- **✅ The full 57 is CATALOGUED DURABLY at `docs/achievements_roster_57.json`** (2026-07-11) — 57 achievements, ALL with `roast` (default/spicy) + `roast_nsfw` (unhinged), buckets 29 ladder/9 milestone/8 mastery/11 feat. This is the canonical roster file; it no longer lives only in artifact `31d6c68a` or chat. **Tabled-ideas check:** the 5 workshopped feats (Triggered, For the Viewers, Read the Manual, The Lexicon, Since the First Floor) are all IN; The Descent is deliberately shelved (owner). Room for ~3 more (60 ceiling).
- **PARKED IDEA — themed cast/progress bars (VERDICT: real potential, Claude viewed the art 2026-07-11):** owner's `Potential… items?` collection + catalog (78–102 rows) hold WoW-style void-purple-metal cast-bar FRAMES + bronze/teal sliding tracks on #00FF00. **Best fit = a themed "casting" progress bar for generation/render** (thematically perfect — you're casting a gen), plus ladder-achievement progress + Panel job progress. **Caveats:** it's a real UI build (art = the FRAME, dynamic fill composited inside via 9-slice so ornate ends don't stretch); prefer the CLEANER rounded frames over the maximalist spiky-lightning ones for constant on-screen use. Park like the Foundry/Provider epics — not tonight.
- **BADGE THEME — Claude viewed all 52 Part Deux gens (2026-07-11): the set is COHESIVE and confirms the anchor.** Tiered ring working (blue-steel rare = books/frames · amethyst-gold epic = dragons/masks · royal-gold legendary = cathedrals/cinematheque/conclave), violet field + cardinal gem accents + scene-inside, keyed on green. The "duplicates" are a SELECTION TRAY (~4–6 variants/achievement). Remaining work: (1) pick winner per slot, (2) key the few on purple/transparent, (3) gen the ~40 gaps in this style. One outlier = the flat clapperboard (decide: keep flat "ward" look or ring it to match).
- **Toast "moment" v2 locked:** badge = medallion that sweeps R→L into a cap; mascot leaps from the TOP edge; "New Achievement" eyebrow; rarity-scaled flair.

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

**Local-gen reality check (2026-07-11):** Maestro (Flux/Chroma, cached) + Forge (WAI + PIP_CONSTRAINT fix, 4 SDXL badge LoRAs staged) are working infra but neither matches the badge bar — the benchmark is **PixAI Tsubaki.2 v1, detailed prose, NO LoRA** (the Hoardsmith dragon, task 2031115782282256404). Model research (Track 2) ✅ DELIVERED 2026-07-11 → **`docs/MODEL_DECK.md`** (25 verified entries + methods; artifact 9f16f42d). Headlines: WAI v11→**v17** upgrade (no token) · NoobAI-XL V-Pred = crispness lane (vpred settings mandatory) · badge stack = Game Icon Institute V4_XL / ZavyChromaXL+Zavy Fantasy Icons LoRA (glow trigger) / game-icon-XL LoRA (full-frame icon LoRAs WANT high weight — the overcook rule inverts) · SpatterXL verdict: SKIP (dated; Black Magic absorbed the look) · lifelike = Illustrij/Equinox/Semi-Real MM + Chroma1-HD prose recipes · **train Nel LoRA locally on Illustrious via OneTrainer (12GB ok; 50-150 imgs; FLUX.1 via FluxGym ok, Flux2/Chroma = cloud)** · Pinokio adds: ComfyUI, BEN2 bg-remover (green-key killer), Invoke · newcomer to watch: Anima (Cosmos 2B, ComfyUI). Next: owner picks downloads → bake-off vs Tsubaki dragon benchmark. Loom ref-gen call ✅ DECIDED → see §1 "Loom V2.1" official plan (A+bridge, rail layout, after achievements). Board v2.1 republished same URL with Originals (74, `Moonglade Icons` collection) + 201 banners (7 Art Scratch + 194 `Moonglade Banners` gallery); Add-On/App Icons (227) deliberately excluded like the Canva dump.

_Superseded/older roadmap artifacts (kept for provenance, not authoritative for these threads): 51a7931d, a67437b9, placement_report, Final Placement, Assignment Board. This doc supersedes them for Loom V2 + Achievements._

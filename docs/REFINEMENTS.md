# Refinements — the suite polish tracker

Owner's working list (2026-07-03) + triage. Status: ✅ done · 🔧 building · 📋 queued · 💬 discuss.

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Model/LoRA selector in its own pop-out card; preview with info (not just image); L/R/Top/Bottom docking | ✅ | Flyout + hover preview card + dock control shipped. **Preview enriched (2026-07-04):** probed for a per-model detail endpoint — none exists, but the `/v2` search rows are far richer than we read (real key is `modelDescription`, plus `category` base-family, `curations` in-house badge, `commentCount`). Card now shows a base-model chip, an **Official** badge, comment count, and the real description. |
| 1a | Model and LoRA are SEPARATE selections — currently both override one field | ✅ | Base model keeps its slot; LoRAs toggle onto a chip list (≤6) with editable weights (0–2, default 0.7). Rides `loras:[{version_id,weight}]` → `loraParameters`. |
| 2 | Image picker larger + robust filters (Collection, etc.) — "a MESS to look at" | ✅ | 900px × 84vh modal; Collection / Source / Rating / Sort filters; whole-catalog infinite scroll + Upload + copy-prompt. Further visual polish → owner's notes pass. |
| 3 | Edit card needs more real estate | ✅ | Edit mode widens to 600px; tools split into Edit \| Enhance \| Fix sub-tabs over a shared source picker. |
| 4 | Generate/Edit/Enhance all a bit cramped | ✅ | Same pass as #3 + base width 420 + docking. Remaining taste-level tweaks → notes pass. |
| 5 | Edit Bay full README + instructions ("even for me :P") | ✅ | In-app ❓ quick-guide overlay on /edit-bay + full manual at docs/EDIT_BAY.md. |
| 6 | Detail-page action buttons (Edit / create video) in the lightbox; right-click menu on thumbnail cards | ✅ | Lightbox: ✎ Edit + ▶ To Video. Right-click a card: Edit / Send to Video / Copy media id / Details. |
| 7 | Multi-select images in gallery → send directly to the video workspace | ✅ | Bulk bar "▶ Send to Video": selection (tap/drag-paint) → Video tab refs (≤9, auto Multi-ref). Later: send to Edit Bay cast. |
| 8 | Gallery search bar bolder/deeper — redesign for the suite ("This is more than a gallery. It is a SUITE.") | 💬 | The banked two-drawer design: LEFT Filters drawer mirroring the right Generate drawer. Sketch AFTER the owner's layout-notes pass. |
| 9 | Printer integration? | ✅ | Letter contact sheets (grid) + **4x6 photo** + **photo-booth strip** (`?format=photo|strip`, for the owner's Sinfonia 4x6/strip printer); detail-page Print / 4x6 / Strip buttons; bulk "Print sheet". Refine layouts later. |
| 10 | Image → 3D model → 3D printer? | 📋 (roadmap) | **CONFIRMED for roadmap.** HW: RTX 4070 Super **12GB** + resin **Anycubic**. Plan: local **Hunyuan3D-2 mini/turbo** (fits ~12GB) → GLB → Blender (already wired) cleanup → **STL** → Photon Workshop; resin target (hide hallucinated back). "Foundry" module, separate install. Work breakdown below. |
| 11 | What are we missing? | ✅ | All four shipped: **Jobs tray** (tasks survive drawer close), **credits + card balance chip**, **Suggest-prompt button**, **prompt snippets/favorites** (server-stored). |
| 11a | Robust, eye-popping top banner + header | ✅ (core) | **Header pass shipped:** images/videos/collections stats + live "N generating" badge; rotating tagline (anchor "a library against the Void"); animated eclipse `M` mark (prefers-reduced-motion honored); `/branding/<file>` drop-in banner slot (owner has art + launch icons ready). Remaining → owner's art + skins + achievements (roadmap). |
| 12 | Contest / community linkage — "the Oasis was never a 1-player game" | 💬 | pixai.art/contest is community surface. v1: link out + maybe surface ongoing official contests. Needs an op capture to list contests via API. |
| 13 | Toolbox preset generators (Lego / Trading Card / Standee / Desktop Pet / Stadium Screen…) | ✅ | CAPTURED + BUILT (2026-07-04). A preset = the normal `chat` edit + a canned prompt + `sceneId`. Edit tab gains a **Toolbox preset** dropdown + **import-by-task-id** ("＋ bank"): run any Toolbox item once on the site, paste the task id, it's yours locally forever — and **a held Edit card makes it FREE via our tool** (the site charged 8,000). Prompts stored locally only (PixAI-authored content, never committed). |
| 14 | Reference Image slot on the IMAGE generator ("use as reference", 0/1 + upload) | ✅ | CAPTURED + BUILT (2026-07-04). Not ipAdapter — plain **img2img**: top-level `mediaId` + `strength`. Generate tab gains a Picker-fed **reference slot** + strength slider (0.1–1, default 0.55); click the filled slot to clear; hover previews. |
| 15 | Model Market parity for the flyout | 💬 (scoped) | **Audit 2026-07-04 mapped what's reachable read-only:** category chips (style/character/pose/clothing/background/detail/other — NOT 'concept') + Latest/Newest sort + posted-at are reachable, **but ONLY via the GraphQL `generationModels` connection** — the REST `/search` we use today accepts every market param with 200 OK and **silently ignores them** (the trap). Official/PixAI badge = `curations:['inhouse']` (already have `official`). **Dead ends (need a capture, don't chase read-only):** server-side Trending/Most-liked sort, and comment threads/bodies. Owner still making a dedicated video before we build. Detail in `private/GENERATOR_SURFACE.md`. |
| 🥚 | An easter egg | ✅ | Hidden. The moon guides those who remember the old codes. |

**Eclipse moon status spinner** ✅ — rebuilt (the original lived only in a chat mockup): CSS eclipsing-moon `.gen-moon` now fronts every submitting/queued/rendering status line in the drawer.

## Also queued (pre-existing, same arc)

- ✅ Video card: real cost + card count, model picker, audio toggle (shipped).
- ✅ Composer parity: slot badges/remove/hover previews + `@image1` prompt chips (shipped; the
  literal collapsed-stack fan animation deferred to the notes pass — cosmetic only).
- ✅ Picker in the Edit Bay (GalleryPick on cast rows + frame slots; mediaId rides Generate-shot).
- ✅ Housekeeping: merged → master v1.9.0; CLAUDE.md + wiki/Generating.md updated.
- ✅ **Achievements & skins** shipped (2026-07-04) — see below.
- ✅ **Turbo-mode RESOLVED** (captured 2026-07-04 off a real turbo gen, task `2030099...557262`): Turbo is **not a submit parameter** — the whole task object had no turbo/tier/speed field, just `priority: 1000` + `inferenceProfile: lite` + a free card (`paidCredit 0`). It's the fast **member runner** granted server-side, which our `priority:1000` path (CLI `--priority 1000` + web "High priority · Turbo" checkbox) + free-card auto-apply already trigger. Nothing to build; relabeled the drawer checkbox to make it discoverable. Detail in `private/GENERATOR_SURFACE.md`.
- Horizon: multi-provider deck (Seedance 2.0 direct), PySide6 ref-video tab.

### Audit-surfaced correctness/spend wins (2026-07-04, model-surface audit — awaiting owner greenlight)
- 📋 **LoRA↔base compatibility gate** *(high impact / small effort)* — block a guaranteed-fail submit (which burns a gen/free-card) when the LoRA's resolved `loraBaseModelType` ≠ the base's `modelType` (exact enum equality). Data already fetched-and-discarded by `resolve_latest_version`. Touches web drawer + CLI `--generate` preview. **Must be labeled a hard architecture-mismatch block, NOT a quality guarantee** (the enum collapses Pony/Illustrious/NoobAI/vanilla-SDXL into one `SDXL_MODEL` bucket).
- 📋 **LoRA trigger-word insertion** *(high impact / medium effort)* — a LoRA without its activation tokens silently no-ops on a PAID gen. `latestVersion.extra.triggerWords` is free to fetch (GraphQL, no extra round-trip); offer to auto-insert into the prompt on chip-attach (editable). Highest-value miss for actually getting usable LoRA output.
- 📋 **refCount as "uses" + surfacing** *(small — reverses my over-cautious call)* — `refCount` is verified real (PixAI's own default sort key, monotonic, stable, not an id). Show it formatted (e.g. 207.7M) as the uses/popularity metric; keep likedCount as a separate likes badge; offer a "most-used" sort on a fetched page.
- 📋 **Base-model tuned preset prefill** *(medium)* — `latestVersion.extra` ships the author's `negativePrompts`/`samplingMethod`/`samplingSteps`/`cfgScale`/`capabilities`; prefill the drawer from it (with a "reset to model defaults") instead of hardcoded defaults. Piggybacks the same `extra` fetch as trigger words.

## Roadmap — banked ideas

**Achievements & skins** ✅ **SHIPPED (2026-07-04)** — eleven WoW-flavored feats computed from local catalog stats (images/videos/collections/distinct-models/published/tagged), read-only, no spend. A trophy button in the header opens a modal (tier-colored badges, progress bars); a gold **Achievement unlocked** toast fires once per feat (collapses to one summary toast for a returning full catalog, so a 19k-image catalog doesn't fire a barrage). Earning an **epic** feat unlocks a cosmetic **skin** — a CSS-variable palette applied via `<html data-skin>` (pre-paint from localStorage, no FOUC), server-validated so a locked skin can't be forced. Ships Nightfallen (free) + Moonlit/Ember/Verdant (unlockable) beside the default Moonglade. State persists to `out_dir/achievements.json`. *Milestone thresholds/badge-art (owner has the Blood Elf / Night Elf / Nightfallen candidates) are easy to retune later.* Verified live in-browser: modal, gallery-wide skin swap, reload persistence, one-shot toast.

**The Foundry — image → 3D print (item 10) work breakdown:**
1. **Spike (prove it):** standalone script — one gallery image → Hunyuan3D-2 (mini/turbo, `pip` + ~several-GB weights, CUDA on the 4070S 12GB, CPU-offload if VRAM-tight) → export GLB. Confirm quality on a real Nelnamara render. *~a session; the go/no-go gate.*
2. **Blender cleanup pass:** headless Blender (already wired) — import GLB → decimate, make-manifold, recompute normals, auto-orient for resin (weak/hallucinated back facing the plate) → export **watertight STL**. *~a session.*
3. **Gallery integration:** "Send to Foundry" button (detail + right-click) → async job (reuse submit/poll/collect + Jobs tray) → **mesh preview** (three.js GLB viewer) → **STL download**. Store meshes beside the image in the catalog. *~a session.*
4. **Provider seam (later):** Meshy/Tripo API as a fallback provider behind the same interface (same pattern as the Seedance deck).
Constraints: separate optional install (NOT bundled — heavy deps + weights); resin-first (skip texture baking; color irrelevant); single-image backs are hallucinated (orient to hide). Detail in [[edit-bay-project]] deck pattern.

## Working agreement

Owner will spend days note-taking on layout/function once features are in place — build features cheap-to-rearrange (flat CSS, no framework), expect furniture to move.

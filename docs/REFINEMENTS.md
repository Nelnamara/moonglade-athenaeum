# Refinements — the suite polish tracker

Owner's working list (2026-07-03) + triage. Status: ✅ done · 🔧 building · 📋 queued · 💬 discuss.

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Model/LoRA selector in its own pop-out card; preview with info (not just image); L/R/Top/Bottom docking | ✅ | Flyout + hover preview card + dock control shipped. **Preview enriched (2026-07-04):** probed for a per-model detail endpoint — none exists, but the `/v2` search rows are far richer than we read (real key is `modelDescription`, plus `category` base-family, `curations` in-house badge, `commentCount`). Card now shows a base-model chip, an **Official** badge, comment count, and the real description. |
| 1a | Model and LoRA are SEPARATE selections — currently both override one field | ✅ | Base model keeps its slot; LoRAs toggle onto a chip list (≤6) with editable weights (0–2, default 0.7). Rides `loras:[{version_id,weight}]` → `loraParameters`. |
| 2 | Image picker larger + robust filters (Collection, etc.) — "a MESS to look at" | ✅ | 900px × 84vh modal; Collection / Source / Rating / Sort filters; whole-catalog infinite scroll + Upload + copy-prompt. Further visual polish → owner's notes pass. |
| 3 | Edit card needs more real estate | ✅ | Edit mode widens to 600px; tools split into Edit \| Enhance \| Fix sub-tabs over a shared source picker. |
| 4 | Generate/Edit/Enhance all a bit cramped | ✅ | Same pass as #3 + base width 420 + docking. Remaining taste-level tweaks → notes pass. |
| 5 | Loom full README + instructions ("even for me :P") | ✅ | In-app ❓ quick-guide overlay on /loom + full manual at docs/LOOM.md. |
| 6 | Detail-page action buttons (Edit / create video) in the lightbox; right-click menu on thumbnail cards | ✅ | Lightbox: ✎ Edit + ▶ To Video. Right-click a card: Edit / Send to Video / Copy media id / Details. |
| 7 | Multi-select images in gallery → send directly to the video workspace | ✅ | Bulk bar "▶ Send to Video": selection (tap/drag-paint) → Video tab refs (≤9, auto Multi-ref). Later: send to Loom cast. |
| 8 | Gallery search bar bolder/deeper — redesign for the suite ("This is more than a gallery. It is a SUITE.") | 💬 | The banked two-drawer design: LEFT Filters drawer mirroring the right Generate drawer. Sketch AFTER the owner's layout-notes pass. |
| 9 | Printer integration? | ✅ | Letter contact sheets (grid) + **4x6 photo** + **photo-booth strip** (`?format=photo|strip`, for the owner's Sinfonia 4x6/strip printer); detail-page Print / 4x6 / Strip buttons; bulk "Print sheet". Refine layouts later. |
| 10 | Image → 3D model → 3D printer? | 📋 (roadmap) | **CONFIRMED for roadmap.** HW: RTX 4070 Super **12GB** + resin **Anycubic**. Plan: local **Hunyuan3D-2 mini/turbo** (fits ~12GB) → GLB → Blender (already wired) cleanup → **STL** → Photon Workshop; resin target (hide hallucinated back). "Foundry" module, separate install. Work breakdown below. |
| 11 | What are we missing? | ✅ | All four shipped: **Jobs tray** (tasks survive drawer close), **credits + card balance chip**, **Suggest-prompt button**, **prompt snippets/favorites** (server-stored). |
| 11a | Robust, eye-popping top banner + header | ✅ (core) | **Header pass shipped:** images/videos/collections stats + live "N generating" badge; rotating tagline (anchor "a library against the Void"); animated eclipse `M` mark (prefers-reduced-motion honored); `/branding/<file>` drop-in banner slot (owner has art + launch icons ready). Remaining → owner's art + skins + achievements (roadmap). |
| 12 | Contest / community linkage — "the Oasis was never a 1-player game" | ✅ SHIPPED (2026-07-04) | Live board from REST `GET /v2/contest/list` (the correct source; NOT the stale GraphQL `contests()`). `--contests` CLI + `/api/contests` + a header **Contests** modal (official/community split, cover art, prize, vote type, client-computed days-left, deep-link out). Active = `runtimeStatus=="running"`. Verified live: 13 running (1 official + 12 community). Future: link the owner's own entries via the `challenge` (contest-id) field on `Artwork.extra` when that sync lands. |
| 13 | Toolbox preset generators (Lego / Trading Card / Standee / Desktop Pet / Stadium Screen…) | ✅ | CAPTURED + BUILT (2026-07-04). A preset = the normal `chat` edit + a canned prompt + `sceneId`. Edit tab gains a **Toolbox preset** dropdown + **import-by-task-id** ("＋ bank"): run any Toolbox item once on the site, paste the task id, it's yours locally forever — and **a held Edit card makes it FREE via our tool** (the site charged 8,000). Prompts stored locally only (PixAI-authored content, never committed). |
| 14 | Reference Image slot on the IMAGE generator ("use as reference", 0/1 + upload) | ✅ | CAPTURED + BUILT (2026-07-04). Not ipAdapter — plain **img2img**: top-level `mediaId` + `strength`. Generate tab gains a Picker-fed **reference slot** + strength slider (0.1–1, default 0.55); click the filled slot to clear; hover previews. |
| 15 | Model Market parity for the flyout | 💬 (scoped) | **Audit 2026-07-04 mapped what's reachable read-only:** category chips (style/character/pose/clothing/background/detail/other — NOT 'concept') + Latest/Newest sort + posted-at are reachable, **but ONLY via the GraphQL `generationModels` connection** — the REST `/search` we use today accepts every market param with 200 OK and **silently ignores them** (the trap). Official/PixAI badge = `curations:['inhouse']` (already have `official`). **Dead ends (need a capture, don't chase read-only):** server-side Trending/Most-liked sort, and comment threads/bodies. Owner still making a dedicated video before we build. Detail in `private/GENERATOR_SURFACE.md`. |
| 16 | Gallery-picker thumbs in the Loom look poor quality | 📋 | **Owner-reported 2026-07-14** (screenshot: `<mg-gallery-picker>` inside the Loom, e.g. Cast "Pick from the gallery") — grid cells look soft/blurry. NOT the same bug as the model-picker fix (`3bf155a`, PixAI CDN `thumb` vs `orig`) — this is OUR OWN locally-generated `/thumbs/<id>.jpg` pipeline (768px, JPEG q90, `make_thumbnail`/`make_video_thumbnail` in `pixai_gallery.py`). Root cause NOT YET INVESTIGATED (deliberately deferred — time-budgeted session). Candidates to check first: are these VIDEO poster thumbs specifically (ffmpeg frame-extract quality/scaling) vs image thumbs; CSS `object-fit`/cell-size upscaling a smaller cached copy; a stale/pre-768px thumb never regenerated. Compare the SAME media in the main gallery grid (same `/thumbs/` files) to isolate picker-CSS vs source-thumb as the cause. |
| 🥚 | An easter egg | ✅ | Hidden. The moon guides those who remember the old codes. |

**Eclipse moon status spinner** ✅ — rebuilt (the original lived only in a chat mockup): CSS eclipsing-moon `.gen-moon` now fronts every submitting/queued/rendering status line in the drawer.

## Also queued (pre-existing, same arc)

- ✅ Video card: real cost + card count, model picker, audio toggle (shipped).
- ✅ Composer parity: slot badges/remove/hover previews + `@image1` prompt chips (shipped; the
  literal collapsed-stack fan animation deferred to the notes pass — cosmetic only).
- ✅ Picker in the Loom (GalleryPick on cast rows + frame slots; mediaId rides Generate-shot).
- ✅ Housekeeping: merged → master v1.9.0; CLAUDE.md + wiki/Generating.md updated.
- ✅ **Achievements & skins** shipped (2026-07-04) — see below.
- ✅ **Turbo-mode RESOLVED** (captured 2026-07-04 off a real turbo gen, task `2030099...557262`): Turbo is **not a submit parameter** — the whole task object had no turbo/tier/speed field, just `priority: 1000` + `inferenceProfile: lite` + a free card (`paidCredit 0`). It's the fast **member runner** granted server-side, which our `priority:1000` path (CLI `--priority 1000` + web "High priority · Turbo" checkbox) + free-card auto-apply already trigger. Nothing to build; relabeled the drawer checkbox to make it discoverable. Detail in `private/GENERATOR_SURFACE.md`.
- Horizon: multi-provider deck (Seedance 2.0 direct), PySide6 ref-video tab.

### Audit-surfaced correctness/spend wins (2026-07-04, model-surface audit — awaiting owner greenlight)
- ✅ **LoRA↔base compatibility gate** SHIPPED (2026-07-04) — `resolve_version_meta` keeps the version metadata `resolve_latest_version` discarded; `is_lora_compatible` = exact enum equality (fails open on unknown). Drawer blocks a guaranteed-fail submit (red warning + disabled Generate) when a LoRA's base family ≠ the selected base, clearing dynamically. Labeled a hard architecture-mismatch block, NOT a quality promise. Verified live in-browser (Tsubaki MMDiT × SDXL LoRA → blocked; base→SDXL → cleared).
- ✅ **LoRA trigger-word insertion** SHIPPED (2026-07-04) — on attaching a compatible LoRA that ships trigger tokens, a green offer appears to insert them into the prompt (editable). Verified live (Eris Greyrat → `Eris Greyrat (Adult), red hair, …` inserted).
- ✅ **refCount as "uses"** SHIPPED (2026-07-04) — reverses the earlier over-cautious suppression; shown formatted (◈207.9M) on model + LoRA cards, most-used-first. Verified live.
- ✅ **Model Market via GraphQL** SHIPPED (2026-07-04) — `model_search_market_gql` honors category + a Newest sort the REST /search ignores; route uses it only when category/newest is requested (keyword/Popular stays rich REST). Category chips + Popular/Newest on the **LoRAs tab only** (categories are 100% LoRAs; new base uploads are rare). Verified live.
- 📋 **Base-model tuned preset prefill** *(medium — data already fetched)* — `resolve_version_meta` now ALSO returns the author's `negative_prompt`/`sampling_method`/`sampling_steps`/`cfg_scale`/`capabilities`; prefill the drawer from it (with a "reset to model defaults") instead of hardcoded defaults. The one audit item not yet wired (the plumbing is in place).

### App-surface recon results (2026-07-04) — "did we hit bedrock?" → not quite; read-only incremental wins remain
Ranked by mission value. All reachable over `gql_adhoc` NOW (no capture); detail in `private/APP_OPERATIONS_FULL.md`.
- ✅ **Server backup-coverage stat** SHIPPED (2026-07-04) — `me.tasks.totalCount` (19,623) vs distinct local `task_id`s → header badge "💾 N% backed up" (green/lavender/peach) + `--account` line + follower counts. Verified live.
- ✅ **Live push + event-driven backup** SHIPPED (2026-07-04) — push IS reachable read-only (the deep probe corrected the earlier "dead end"). graphql-transport-ws at **wss://gw.pixai.art/graphql**, `connection_init{Authorization}` → ack, subscribe `personalEvents` (taskUpdated + newNotification). Owner captured the lifecycle (waiting → running → **completed**), so `--watch --watch-backup` now mirrors each gen into `--out` the instant it hits `completed` (daemon thread off the event loop; per-session dedupe) — the poll loop becomes a fallback. Verified live end-to-end (connect + subscription accepted; collect_generation on the owner's real completed task pulled + cataloged the exact media). The "batch scraper → live mirror" upgrade.
- ✅ **Contests** SHIPPED (2026-07-04) — `--contests` + `/api/contests` + header modal (official/community, cover art, prize, days-left, deep-link). Source REST `/v2/contest/list`, active = `runtimeStatus=="running"`. Verified live (13 running: 1 official + 12 community).
- ✅ **Artwork.extra capture** SHIPPED (2026-07-04) — `extract_artwork_meta` now lifts `imageBlurHash` (→ `blurhash` col, for future instant placeholders) + `nsfwPredict` (→ `nsfw_scores` JSON col) from the `extra` block the sync already fetches. **Honest scope correction:** the probe's promised `challenge` (contest-id) link was NOT in the extra block (verified) and it's published-only — so it's capture-for-later, not the contest linkage. Surfacing (placeholder render / granular blur) is a follow-up.
- ✅ **Ad-hoc `task(id:)` + BATCH-CAPTURE FIX** SHIPPED (2026-07-04) — `_task_detail_query` falls back to ad-hoc `task(id:)` when TASK_DETAIL_HASH is missing (unblocks `--full-meta`). **Surfaced a real backup bug:** a batchSize>1 task stores a 2×2 composite GRID under `outputs.mediaId` and the individuals under `outputs.batch[]` (with `batchMediaIds` null) — the download path saved the GRID and dropped the real images. `_task_image_media` now saves the batch individuals (never the grid) + each image's own seed. Fixes `collect_generation` → web-gen, `--task-id` recovery, and `--watch-backup`. Verified live: a batch-4 task now saves 4×1920×480 (was 1×3840×960 grid).
- ✅ **VIEWS + "Your Art"** SHIPPED (2026-07-04) — header "My Art" modal ranks published works by likes (catalog, LAN-safe) + live views per `artwork(id){views}` (localhost); detail page shows a live Views metric. Verified live.
- ✅ **Dashboard entitlements** SHIPPED (2026-07-04) — `--account` now prints credit ceiling / LoRA + private-model slots / extra-package / referral code (privilege was fetched, only 2/8 keys shown). `me.preferences` was a leaf not the recon's object — skipped.
- ✅ **`--update` batch integrity CHECKED** (2026-07-04) — the listing node populates `batchMediaIds` (the reals), so `--update` captured all batch images; NO images lost. It also keeps the grid composite (minor clutter; over-capture is right for a backup tool) — left as-is. The collect-path bug (grid-only) was the real issue, already fixed.
- 📋 **BlurHash grid placeholders** *(deferred, low ROI now)* — data captured (`blurhash` col) but empty until `--sync-artworks` + published-only + needs a JS decoder. Detail-page NSFW breakdown IS surfaced. Do the grid decoder if published coverage grows.
- **DEAD ENDS (stop chasing):** engagement feed (no actor identity; NOT a completion signal — the WS is the completion channel instead); comment bodies; who-liked; server-side "my/liked/saved models"; User aggregate rollups; a global config/enums op; lineage/remix chains. **Mio.2** DEFERRED — cookie-authed (sk- Bearer 401s), contract bankable free from the JS bundle but integration = a cookie-jar rewrite; only worth it as a deliberate agent-UX bet (do NOT capture cookies without owner direction).

## Roadmap — banked ideas

**Achievements & skins** ✅ **SHIPPED (2026-07-04)** — eleven WoW-flavored feats computed from local catalog stats (images/videos/collections/distinct-models/published/tagged), read-only, no spend. A trophy button in the header opens a modal (tier-colored badges, progress bars); a gold **Achievement unlocked** toast fires once per feat (collapses to one summary toast for a returning full catalog, so a 19k-image catalog doesn't fire a barrage). Earning an **epic** feat unlocks a cosmetic **skin** — a CSS-variable palette applied via `<html data-skin>` (pre-paint from localStorage, no FOUC), server-validated so a locked skin can't be forced. Ships Nightfallen (free) + Moonlit/Ember/Verdant (unlockable) beside the default Moonglade. State persists to `out_dir/achievements.json`. *Milestone thresholds/badge-art (owner has the Blood Elf / Night Elf / Nightfallen candidates) are easy to retune later.* Verified live in-browser: modal, gallery-wide skin swap, reload persistence, one-shot toast.

**The Foundry — image → 3D print (item 10) work breakdown:**
1. **Spike (prove it):** standalone script — one gallery image → Hunyuan3D-2 (mini/turbo, `pip` + ~several-GB weights, CUDA on the 4070S 12GB, CPU-offload if VRAM-tight) → export GLB. Confirm quality on a real Nelnamara render. *~a session; the go/no-go gate.*
2. **Blender cleanup pass:** headless Blender (already wired) — import GLB → decimate, make-manifold, recompute normals, auto-orient for resin (weak/hallucinated back facing the plate) → export **watertight STL**. *~a session.*
3. **Gallery integration:** "Send to Foundry" button (detail + right-click) → async job (reuse submit/poll/collect + Jobs tray) → **mesh preview** (three.js GLB viewer) → **STL download**. Store meshes beside the image in the catalog. *~a session.*
4. **Provider seam (later):** Meshy/Tripo API as a fallback provider behind the same interface (same pattern as the Seedance deck).
Constraints: separate optional install (NOT bundled — heavy deps + weights); resin-first (skip texture baking; color irrelevant); single-image backs are hallucinated (orient to hide). Detail in [[edit-bay-project]] deck pattern.

## Working agreement

Owner will spend days note-taking on layout/function once features are in place — build features cheap-to-rearrange (flat CSS; the real constraint is **no build step / framework-neutral** shared widgets, NOT "no framework" — the Loom is deliberately React), expect furniture to move. *(Clarified 2026-07-13 per `docs/SUITE_ARCHITECTURE_AUDIT.md`; the earlier "no framework" wording was never an enforced rule.)*

## v1.10.0 (2026-07-05) — consolidation release

Shipped since 1.9.1:
- Live events: --watch / --watch-backup (WS push, personalEvents; auto-collect finishing gens)
- Panel: job progress bar (MGPROG protocol), Stop-this-job cancel, schedulable safe jobs, backfill-meta parity with GUI (label now says prompts/seeds/models)
- Server: Stop/Restart from the browser; Serve Gallery.pyw supervisor (exit-42 relaunch, single-instance ping guard, serve.txt args)
- Export CSV = real browser download (/export-csv)
- Branding system: choosable banner mark (5 cut marks) + 15 animations, frosted-pill nav, Panel Branding card, Desktop-launcher icon via .lnk
- Balance chip caches last-known credits (no more blank flicker)
- Contests / achievements / skins surfaces
- Fixes: batch under-capture (grid vs reals), catalog-stats thumbnail double-count, USER_ID auto-resolve in --sync-artworks, reduced-motion + corrupt-manifest hardening

Backlog status (verified against code 2026-07-10 — see `docs/STATE_OF_THE_SUITE_2026-07-10.md`):
- ✅ **Sync-on-pull pipeline** — `--sync` now runs pull + full-meta → fix-models → backfill → **thumbnails → reconcile** in one idempotent pass (`main()` sync branch).
- ✅ **Live-mirror watcher inside the server** — auto-starts in `create_app` (`_watch_loop`); no separate CLI process.
- ✅ **Pixeltable semantic search** — `/api/similar` + lightbox/right-click "Similar" shipped (the `pixeltable` backend is just an optional/uninstalled dep here).
- ✅ **Loom trim/preview/export** — non-destructive trim + Play + ffmpeg `/api/loom/export` shipped.
- ✅ **Banner picker + achievement unlocks** — branding + achievements/skins shipped; owner is iterating on the mascot/badge **art** now.
- ⬜ **Generation Flags (AI QA pass)** — the lone unbuilt item; no code footprint yet, needs a spec (what it flags, where the verdict lives).

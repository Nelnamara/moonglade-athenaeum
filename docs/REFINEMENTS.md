# Refinements — the suite polish tracker

Owner's working list (2026-07-03) + triage. Status: ✅ done · 🔧 building · 📋 queued · 💬 discuss.

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Model/LoRA selector in its own pop-out card; preview with info (not just image); L/R/Top/Bottom docking | ✅ | Flyout + hover preview card + dock control shipped. Preview shows author/description/tags only when the search API returns them — probe the per-model detail endpoint if thin. |
| 1a | Model and LoRA are SEPARATE selections — currently both override one field | ✅ | Base model keeps its slot; LoRAs toggle onto a chip list (≤6) with editable weights (0–2, default 0.7). Rides `loras:[{version_id,weight}]` → `loraParameters`. |
| 2 | Image picker larger + robust filters (Collection, etc.) — "a MESS to look at" | ✅ | 900px × 84vh modal; Collection / Source / Rating / Sort filters; whole-catalog infinite scroll + Upload + copy-prompt. Further visual polish → owner's notes pass. |
| 3 | Edit card needs more real estate | ✅ | Edit mode widens to 600px; tools split into Edit \| Enhance \| Fix sub-tabs over a shared source picker. |
| 4 | Generate/Edit/Enhance all a bit cramped | ✅ | Same pass as #3 + base width 420 + docking. Remaining taste-level tweaks → notes pass. |
| 5 | Edit Bay full README + instructions ("even for me :P") | ✅ | In-app ❓ quick-guide overlay on /edit-bay + full manual at docs/EDIT_BAY.md. |
| 6 | Detail-page action buttons (Edit / create video) in the lightbox; right-click menu on thumbnail cards | ✅ | Lightbox: ✎ Edit + ▶ To Video. Right-click a card: Edit / Send to Video / Copy media id / Details. |
| 7 | Multi-select images in gallery → send directly to the video workspace | ✅ | Bulk bar "▶ Send to Video": selection (tap/drag-paint) → Video tab refs (≤9, auto Multi-ref). Later: send to Edit Bay cast. |
| 8 | Gallery search bar bolder/deeper — redesign for the suite ("This is more than a gallery. It is a SUITE.") | 💬 | The banked two-drawer design: LEFT Filters drawer mirroring the right Generate drawer. Sketch AFTER the owner's layout-notes pass. |
| 9 | Printer integration? | 💬 | v1: print stylesheet + Print button on detail (image centered, chrome hidden) + contact sheets from a selection/collection. OS dialog does paper handling. |
| 10 | Image → 3D model → 3D printer? | 💬 | Viable: Hunyuan3D-2 (open weights, figurine-grade from one image), TRELLIS, TripoSR, Meshy (API). Pipeline: image → GLB → Blender cleanup → watertight STL → slicer. Roadmap spike: a "Foundry" module in the provider-deck pattern. |
| 11 | What are we missing? | 💬 | Claude's adds: **Jobs tray** (running/recent tasks survive drawer close), **credits + card balance in the header**, **Suggest-prompt button** on images (engine built, no UI), **prompt snippets/favorites**. |
| 11a | Robust, eye-popping top banner + header — "this is a suite, not an AOL home page with dancing hamsters" | 💬 | Part of the #8 identity redesign; owner's notes pass drives it. |
| 12 | Contest / community linkage — "the Oasis was never a 1-player game" | 💬 | pixai.art/contest is community surface. v1: link out + maybe surface ongoing official contests. Needs an op capture to list contests via API. |
| 13 | Toolbox preset generators (Lego / Trading Card / Standee / Desktop Pet / Stadium Screen…) | 📋 | NOT the same as our Enhance workflows — they're preset templates at /generator/preset/&lt;name&gt;. Plan: owner runs ONE toolbox gen on the site → `--task-id <id> --dump-params` banks the shape free → if it's canned `chat`/params, ship a "Presets" row in the Edit tab. |
| 14 | Reference Image slot on the IMAGE generator ("use as reference", 0/1 + upload) | 📋 | The site's image gen takes a reference image (likely `ipAdapter` — already in _PRICE_NESTED). Needs one dump-params capture of a reference-image gen to pin the shape, then add a ref slot (Picker-fed) to the Generate tab. |
| 15 | Model Market parity for the flyout | 💬 | Seen in the site browser: category filters (Character/Style/Pose/Clothing/…), source (PixAI/External), posted-at, Trending sort, type badges, train/upload. Owner making a dedicated video before we build. |
| 🥚 | An easter egg | ✅ | Hidden. The moon guides those who remember the old codes. |

**Eclipse moon status spinner** ✅ — rebuilt (the original lived only in a chat mockup): CSS eclipsing-moon `.gen-moon` now fronts every submitting/queued/rendering status line in the drawer.

## Also queued (pre-existing, same arc)

- ✅ Video card: real cost + card count, model picker, audio toggle (shipped).
- ✅ Composer parity: slot badges/remove/hover previews + `@image1` prompt chips (shipped; the
  literal collapsed-stack fan animation deferred to the notes pass — cosmetic only).
- ✅ Picker in the Edit Bay (GalleryPick on cast rows + frame slots; mediaId rides Generate-shot).
- ✅ Housekeeping: merged → master v1.9.0; CLAUDE.md + wiki/Generating.md updated.
- Horizon: multi-provider deck (Seedance 2.0 direct), Turbo-mode capture, PySide6 ref-video tab.

## Working agreement

Owner will spend days note-taking on layout/function once features are in place — build features cheap-to-rearrange (flat CSS, no framework), expect furniture to move.

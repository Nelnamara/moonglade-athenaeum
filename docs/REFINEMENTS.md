# Refinements — the suite polish tracker

Owner's working list (2026-07-03) + triage. Status: ✅ done · 🔧 building · 📋 queued · 💬 discuss.

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Model/LoRA selector in its own pop-out card; preview with info (not just image); L/R/Top/Bottom docking | ✅ | Flyout + hover preview card + dock control shipped. Preview shows author/description/tags only when the search API returns them — probe the per-model detail endpoint if thin. |
| 1a | Model and LoRA are SEPARATE selections — currently both override one field | 🔧 | **Top priority — correctness bug.** Base-model slot + attachable LoRA chip list with weights (`loraParameters` already supported by the engine). |
| 2 | Image picker larger + robust filters (Collection, etc.) — "a MESS to look at" | 📋 | Whole-catalog scroll + Upload + copy-prompt shipped. Filters are UI-only: `query_catalog` already supports collection/batch/rating/date/source/model. Bigger modal + visual cleanup. |
| 3 | Edit card needs more real estate | 📋 | Give Edit the 600px wide mode like Video; split into sub-tabs: Edit \| Enhance \| Fix. |
| 4 | Generate/Edit/Enhance all a bit cramped | 📋 | Same pass as #3; dock-bottom already relieves it — the width game changes per dock. |
| 5 | Edit Bay full README + instructions ("even for me :P") | 📋 | Wiki page + in-app ❓ help overlay. Part of the docs pass. |
| 6 | Detail-page action buttons (Edit / create video) in the lightbox; right-click menu on thumbnail cards | 📋 | Lightbox chrome buttons + small context menu (Edit / Video ref / Copy media id). |
| 7 | Multi-select images in gallery → send directly to the video workspace | 📋 | Reuse existing multi-select; "Send to Video" opens the drawer in Multi-ref with slots pre-filled (≤9). Later: send to Edit Bay cast. |
| 8 | Gallery search bar bolder/deeper — redesign for the suite ("This is more than a gallery. It is a SUITE.") | 💬 | The banked two-drawer design: LEFT Filters drawer mirroring the right Generate drawer. Sketch AFTER the owner's layout-notes pass. |
| 9 | Printer integration? | 💬 | v1: print stylesheet + Print button on detail (image centered, chrome hidden) + contact sheets from a selection/collection. OS dialog does paper handling. |
| 10 | Image → 3D model → 3D printer? | 💬 | Viable: Hunyuan3D-2 (open weights, figurine-grade from one image), TRELLIS, TripoSR, Meshy (API). Pipeline: image → GLB → Blender cleanup → watertight STL → slicer. Roadmap spike: a "Foundry" module in the provider-deck pattern. |
| 11 | What are we missing? | 💬 | Claude's adds: **Jobs tray** (running/recent tasks survive drawer close), **credits + card balance in the header**, **Suggest-prompt button** on images (engine built, no UI), **prompt snippets/favorites**. |
| 11a | Robust, eye-popping top banner + header — "this is a suite, not an AOL home page with dancing hamsters" | 💬 | Part of the #8 identity redesign; owner's notes pass drives it. |
| 🥚 | An easter egg | ✅ | Hidden. The moon guides those who remember the old codes. |

## Also queued (pre-existing, same arc)

- Video card: real cost + card count row (`🎫 1/9` style), model picker (V4.0/Lite/3.2), Add-audio toggle.
- Reference deck fan-out + hover previews on picked refs + inline `@image1` prompt chips (composer parity).
- Picker into the Edit Bay's React side (Cast/frames are upload-only there).
- Housekeeping: push, merge `generate-drawer` → master (v1.9.0), CLAUDE.md test count, wiki (drawer / Video tab / /edit-bay).
- Horizon: multi-provider deck (Seedance 2.0 direct), Turbo-mode capture, PySide6 ref-video tab.

## Working agreement

Owner will spend days note-taking on layout/function once features are in place — build features cheap-to-rearrange (flat CSS, no framework), expect furniture to move.

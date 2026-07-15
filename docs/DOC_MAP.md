# Moonglade Athenaeum — Doc Map & Artifact Ledger

> The catalog of every document and Claude artifact this project maintains, and where each
> one stands. **Maintained under the checkpoint protocol** (see `CLAUDE.md`): updated after
> shipped increments, and whenever a new artifact is published its entry lands in the
> ledger below. Last full refresh: **2026-07-12**.

---

## 1. Repo docs (committed — on every machine)

### Root
| File | Role | Status |
|---|---|---|
| `CLAUDE.md` | Claude's standing project context: architecture, invariants, cross-machine + checkpoint protocol, security rules | **Active** — edited when working rules change |
| `CHANGELOG.md` | Source of truth for releases; `[Unreleased]` gets every notable change | **Active** — every increment |
| `README.md` | Public repo readme / user docs | Release-time only |

### `docs/` — active
| File | Role | Status |
|---|---|---|
| `ROADMAP_LOOM_ACHIEVEMENTS.md` | ⭐ **THE active roadmap** — source of truth for the current threads (Loom V2.1 · Achievements). Checkpointed after every increment; re-read after every compaction | **Active** |
| `REFINEMENTS.md` | Near-term tracker: small web-suite fixes/polish | Active |
| `ROADMAP.md` | Far-horizon epics only (the Foundry, Provider Deck) | Active, rarely touched |
| `achievements_roster_57.json` | Canonical 57-achievement roster (names/tiers/triggers/roasts) — code generates from this. Thresholds reconciled to shipped code 2026-07-13 (marathon 100 · read-the-manual 1 · triggered 5) | **Canonical data** |
| `DOC_MAP.md` | This file | Active |
| `CURATION_STANDARD.md` | ⭐ **House baseline for selection/vote artifacts** (owner-approved 2026-07-12): 10 non-negotiables, pick/rank/view/note model, build discipline | **Active standard** |
| `curation_reference_builder.py` | Reference implementation of the Curation Standard — clone for any vote artifact (swap input/classify/picks, keep the rest) | Reference |
| `ART_PICKS.md` | Owner's achievement-flair selections (2026-07-12) from the Curation Workspace — feat/bar decided, LEG needs edits, CLAIM open, + repurpose ideas | **Active (provisional picks)** |
| `LOOM.md` | The Loom user manual | Active |
| `DESIGN_WORKFLOW.md` | ⭐ **The pixel-source-of-truth standard (2026-07-14)** — born from the Trophy Hall reformat incident: no visual build from prose alone; Figma plugin (bidirectional, auth via `/mcp`) + Claude Design/DesignSync tooling; Trophy Hall recovery options; model strategy | **Active standard** |
| `SUITE_ARCHITECTURE_AUDIT.md` | ⭐ **Front-end cohesion audit (2026-07-13)** — every surface's stack, the duplication map, the web-component recommendation + migration order (pilot = model picker), and the Loom save/load defect + fix. Basis for the front-end direction decision | **Active (awaiting owner calls)** |
| `MODEL_DECK.md` | 25-entry verified model research deck (badge/lifelike/local lanes) | Reference |
| `ART_PROMPTS.md` | House badge style anchor (tiered-ring template, locked hexes) + brand prompt bank | Reference |
| `ART_SPECS.md` | Art asset specs (sizes, keying, formats) | Reference |
| `badge_generation_prompts.md` | Badge prompt system v2 + 11 gunmetal feat prompts | **Parked** (owner: maybe when credits allow) |

### `docs/` — historical (kept, not maintained)
| File | Note |
|---|---|
| `STATE_OF_THE_SUITE_2026-07-10.md` | Point-in-time snapshot |
| `architecture.md` | Older architecture notes |

---

## 2. `private/` — git-ignored, machine-local (reverse-engineering detail)

`API_OPERATIONS.md` · `APP_OPERATIONS_FULL.md` · `GENERATOR_SURFACE.md` · `RE_NOTES.md`
(recapture procedure) · `VIDEO_GEN.md` · `VIDEO_MODELS.md` · `ARCHITECTURE_RE.md` ·
`DISCOVERIES.md` · `ROADMAP.md` (old notes). Updated when new PixAI API surface is
captured. **Never committed** — contains op hashes + account specifics.

---

## 3. Claude's cross-session memory

Lives at `~\.claude\projects\C--Users-gwilkins-source-repos\memory\` — survives every
session. `MEMORY.md` is the index (one line per memory, loaded at session start). ~25 of
the 56 files are the Moonglade cluster: project state, PixAI API knowledge, and the
owner's standing rules (checkpoint protocol, design-intent rule, commit style, push
cadence, PixAI hands-off, etc.).

**Hierarchy when sources disagree:** repo docs win for project state
(`ROADMAP_LOOM_ACHIEVEMENTS.md` above all) · memory wins for owner preferences ·
memories describing code get verified against the code before acting.

---

## 4. Artifact Ledger (claude.ai — the browser-tab collection)

Snapshot artifact of this map: see ledger entry ⬥ below. Descriptions best-effort — corrections welcome.

⬥ **This map, browsable:** [Doc Map & Artifact Ledger](https://claude.ai/code/artifact/6e855faa-caa1-41f5-9214-d63aec1bae52) — snapshot artifact, redeployed on request; this file is truth.

### Locked designs (decided; implementation status noted)
| Artifact | Status |
|---|---|
| [toast_mockup](https://claude.ai/code/artifact/335ef4e7-2459-4c99-990a-b8c5751324c3) | **LOCKED + SHIPPED** — the unlock-moment design, in-app since `077e1f0` |
| [loom_selectshot](https://claude.ai/code/artifact/0d9c4e02-200e-44f9-982c-e3add482b905) | LOCKED — owner-approved Loom selected-shot interaction model (shipped in V2) |

### Living tools & references (still useful to open)
| Artifact | Purpose |
|---|---|
| [The Curation Standard](https://claude.ai/code/artifact/6d6b9d2d-281e-4fd5-b1dc-7a11c599950e) | ⭐ The browsable house standard for vote/selection artifacts (mirrors `docs/CURATION_STANDARD.md`) |
| [Curation Workspace](https://claude.ai/code/artifact/ef9f5853-5c8f-40eb-87f2-8cf123f0b6ef) | The live reference example — 227 art candidates, lightbox + pick + rank + tray + export |
| [Moonglade — Art Worklist](https://claude.ai/code/artifact/13712183-1824-4f14-b9aa-9d9cc03fc20b) | The active find/generate art run (2026-07-12): 9 badge gaps w/ recorded picks + thumbnails, mystery-tile starters, 9-slice frame prompts (legendary/feat), SFX list |
| [Art Haul — 2026-07-12](https://claude.ai/code/artifact/f80347bf-8c54-4bd1-8435-003ce276481b) | First-pass parse of the frame/icon/mystery-tile production run (155 files); superseded by the Selection picker below for actual choosing |
| [Selection v3 — Claim Icons, Frames, Mystery Tiles](https://claude.ai/code/artifact/812e82b4-ace3-43af-aba8-cc2de8c065ec) | Interactive 5-star ranked picker (CLAIM/LEG/FEAT/MYS). Superseded by v5 workspace + the final-push picker below |
| Final-push picker (selection6) — artifact id `e3175c08…` | Cloned from the Curation Standard reference builder: final-10 CLAIM + newly alpha'd frames/bars scored against prior picks. Where the finalists were chosen (find full URL via the browser artifact gallery) |
| [⭐ Finalists In Action](https://claude.ai/code/artifact/b45a39a3-b6a8-4e73-9f62-e03cb390bd00) | **Current — the "big artifact":** finalists shown in context (frames wrap a real unlock, bars fill live, claim icons in the header chip). For the final call. See `docs/ART_PICKS.md` §Finalists |
| [Doc Map & Artifact Ledger](https://claude.ai/code/artifact/6e855faa-caa1-41f5-9214-d63aec1bae52) | Browsable snapshot of this file |
| [Moonglade Roster Board](https://claude.ai/code/artifact/31d6c68a-bd54-4824-886f-9017c6012912) | The 57-achievement 3-lane voting board (votes complete; the reference board) |
| [ledger](https://claude.ai/code/artifact/d1ee39a1-db65-487b-a6ef-067ea6d1392d) | Per-achievement mascot+badge session ledger |
| [Moonglade — Final Select](https://claude.ai/code/artifact/e7253fbf-98c7-40a9-9503-fa750ae7904c) | Final badge compare/select panel |
| [Moonglade Model Deck](https://claude.ai/code/artifact/9f16f42d-2541-4dd9-935a-0f9d0f39c7c4) | Model research deck (mirrors `docs/MODEL_DECK.md`) |
| [Badge Prompts v2](https://claude.ai/code/artifact/771f84d9-cacb-4f5c-8300-9c8575fb8431) | The badge prompt system (mirrors `docs/badge_generation_prompts.md`) |
| [Chibi Library (335)](https://claude.ai/code/artifact/1998636d-9043-41e8-900d-797c67fd04f2) | The full chibi browser + use assignment |
| [Cohesion Map](https://claude.ai/code/artifact/4229e98c-4ac3-4e86-820a-72a57465c066) | Top-down app map |
| [Moonglade Banners — defaults & unlocks](https://claude.ai/code/artifact/7919cec3-aec7-41d0-8efc-8fb2d0f4cdb5) | Banner picks (feeds the future banner-unlock mechanic) |
| [Moonglade Marks — score/sort/animate](https://claude.ai/code/artifact/525d8581-4284-407f-8975-921239312e9c) | Mark selection + animation picker |

### Concepts that shipped (kept for provenance)
| Artifact | Shipped as |
|---|---|
| [Activity Tracker + spinning Nel](https://claude.ai/code/artifact/a7adddf2-e6d7-4384-8aec-3ddb0bf0d213) | The jobs/activity card |
| [Easter Egg: Nel casts Starfall](https://claude.ai/code/artifact/bb3cde49-d06c-4bdc-9c88-95379f187468) | The Konami egg (now also a feat) |
| [Filter Bar Layout](https://claude.ai/code/artifact/5acecb0f-aacc-4bbd-9682-1f0fbef27980) | The gallery filter bar |
| [The six — collapsing header](https://claude.ai/code/artifact/9908695c-6e59-4124-91dd-7fe6c3f7e6e7) | The collapsing banner header |
| [Notification System Concept](https://claude.ai/code/artifact/b7807a1e-2e93-48ad-a7ba-92f85787a840) | Toasts/notification design language |
| [loom_mockup](https://claude.ai/code/artifact/8bd885e1-f343-4ca4-bc02-cfe17f9e57cd) · [loom_canvas](https://claude.ai/code/artifact/c9e28b8e-612d-4302-b1c1-049844e810da) · [loom-v2-blueprint](https://claude.ai/code/artifact/e2e146d9-22d1-4a50-8947-66d2af93ad40) | Loom V2 layout/blueprint mockups |

### Parked
| Artifact | Note |
|---|---|
| [Feat badge prompts — gunmetal](https://claude.ai/code/artifact/73372456-f09c-418c-920b-3e139988ef91) | 11 feat badge-art prompts — owner: maybe when credits allow |

### Historical — selection passes complete / superseded
[Assignment Board](https://claude.ai/code/artifact/d53cefd9-3d20-484c-bcd9-a855a75a3adf) ·
[Final Placement & Bank](https://claude.ai/code/artifact/5864d380-1d7c-47de-91a9-1f95f554071c) ·
[Art Vote candidates](https://claude.ai/code/artifact/8e74e091-9ed0-4595-9130-9f5c47aecf65) ·
[Nel Presents candidates](https://claude.ai/code/artifact/4a7493cb-e83e-4c84-b0bf-d0f8dc3caff1) ·
[App-state mascots](https://claude.ai/code/artifact/5ab9a5f8-dafc-444a-92dc-01ec282f6073) ·
[Mascot Grid](https://claude.ai/code/artifact/f2c24d44-e01b-4cfd-bd63-a5f457545741) ·
[Late badge selector](https://claude.ai/code/artifact/dd59baa4-0526-47bf-ae6b-38617f84979c) ·
[Late replacements — picks](https://claude.ai/code/artifact/fa539fbe-21a5-4175-8fe4-2b9bfa34eeb3) ·
[briefs](https://claude.ai/code/artifact/3128a8cc-7895-494f-9149-a1b631586707) ·
[placement_report](https://claude.ai/code/artifact/099eed28-7452-43a1-827b-83d8c4ea1981) ·
[App Icon Vote](https://claude.ai/code/artifact/6781a082-291a-4397-9e10-167198484ad7) ·
[icon_board](https://claude.ai/code/artifact/3c992745-d97a-403b-9189-0f852d06f68f) ·
[sticker_board](https://claude.ai/code/artifact/da8dfcad-ff7c-4146-a615-5723ef22a230) ·
[art_inventory](https://claude.ai/code/artifact/e0236c40-9700-4be8-845c-5443d36281c0) ·
[Art Generation Worklist](https://claude.ai/code/artifact/81c6ff46-c333-469e-85d4-a541ca8a8cdf) ·
[roadmap](https://claude.ai/code/artifact/51a7931d-d44f-483c-b62d-f527bda2542d) (superseded by `ROADMAP_LOOM_ACHIEVEMENTS.md`) ·
[state-of-play](https://claude.ai/code/artifact/a67437b9-3e7b-4ff4-ad4a-4fd5d98d5525) ·
[State of the Suite](https://claude.ai/code/artifact/45209cae-e88f-45c7-a2c8-72ce11d3445a) ·
[weekend_recap](https://claude.ai/code/artifact/42bb8caf-e852-45a6-b15d-882565a5e983) ·
[debacles](https://claude.ai/code/artifact/63533f06-8676-413a-b13d-ac85892e3668) ·
[Under the Hood](https://claude.ai/code/artifact/63df9423-b9d1-4be3-8956-c271c016db77) ·
[pixai-capability-atlas](https://claude.ai/code/artifact/953a97db-2f7f-4ed6-9d52-44aa74f57c58) ·
[pixai-atlas-2](https://claude.ai/code/artifact/8d208bf4-a712-4c04-a128-7cb41b105fd9)

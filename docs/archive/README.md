# docs/archive — frozen records

Everything in this folder is a **dated, point-in-time record**. None of it is maintained, and
none of it should be edited — a frozen doc's whole value is that it says what was believed on its
date. If a fact here is still true and still needed, it lives in a **live** doc; copy it forward,
don't edit the frozen copy.

Where the live truth is:

| For… | See |
|---|---|
| Current project state (shipped / in flight / next / open calls / defects) | `docs/STATE.md` |
| How the system is built | `docs/architecture.md` |
| Art direction, slots, palette, prompt bank | `docs/ART.md` |
| What changed and when | `CHANGELOG.md` |
| The Loom manual | `docs/LOOM.md` |

## What's here, and why it was frozen

- **`ROADMAP_LOOM_ACHIEVEMENTS_2026-07-16.md`** — the project's source-of-truth roadmap from
  2026-07-11 to 2026-07-16. Retired because it was an append-only journal and became the single
  rottenest file in the repo (40 of the 158 stale claims a 2026-07-16 audit found). Replaced by
  `docs/STATE.md`, which forbids the journaling habit. Kept for the decision narrative it holds.
- **`ART_PROMPTS_2026-07-16.md`, `ART_SPECS_2026-07-16.md`, `ART_PICKS_2026-07-16.md`,
  `badge_generation_prompts_2026-07-16.md`** — the four art docs, merged into `docs/ART.md` and
  frozen (owner's call: keep the full prompt text as reference craft). They disagreed with each
  other and themselves; `ART.md` is the reconciled truth. A hex or size here that disagrees with
  `ART.md` is stale.
- **`MODEL_DECK_2026-07-11.md`** — dated external research (Civitai / HuggingFace / Pinokio).
  Decays on its own schedule; re-verify before relying on it, especially for the Nel-LoRA run.
- **`STATE_OF_THE_SUITE_2026-07-10.md`** — a 2026-07-10 code-verified snapshot. The first of three
  attempts at a single state doc; `STATE.md` is the third.
- **`SUITE_ARCHITECTURE_AUDIT_2026-07-13.md`** — the 2026-07-13 cohesion audit. Its direction was
  acted on (the `mg-*` web components shipped); kept as the record of why.
- **`SWEEP_2026-07-16.md`** — the 2026-07-16 defect sweep. All 10 defects are fixed; kept as the
  record of how they were found and verified.

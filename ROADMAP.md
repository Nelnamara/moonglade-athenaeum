# Roadmap

Planned and outstanding work for Moonglade Athenaeum. **One home per fact:**

- **Shipped** → `CHANGELOG.md` (dated taglines). Nothing here once it ships — it *moves*.
- **Why a decision was made** → `docs/DECISIONS.md` (banked reasoning only, no status).
- **Bugs** → GitHub Issues.
- **Planned work** → this file.

Format is Now / Next / Later. Each item says what it is, why, and what it touches. When an
item ships, delete it here and add a CHANGELOG line — never annotate "done" in place.

---

## Now — active

- **Achievement ladder rungs — redefinition** *(owner)*
  The rung/threshold definitions are being reworked. Scope is *which rungs exist and their
  thresholds*, not the celebration timing (that gate already shipped). Hands off the definitions
  until the owner lands them.

---

## Next — scoped, not started

- **Remix from the lightbox**
  Load a picture's *full recipe* (prompt + negative + seed + model + LoRAs) back into the Generate
  drawer in one click. Today the lightbox only sends the *image* to Edit or Video; the recipe slab
  is read-only. Asked for repeatedly; no code exists yet. (Overlaps GitHub issue #4 — reconcile.)

- **Stack by batch (gallery grid)**
  Collapse the grid into per-batch/per-task stacks instead of one flat wall. Related surfaces exist
  but don't cover it: a batch-filter drill-down and the Image Details lineage-siblings section. The
  grid-stacking itself is unbuilt.

- **Hidden-achievement response hardening**
  Masked feats are blanked in the API response, but the *number* of undiscovered ones is still
  countable in the raw payload. Deferred until the asset bundle shipped (it now has), so this is a
  live follow-up — collapse/withhold the masked slots so the count doesn't leak.

- **Loom per-project spend ledger (historical)**
  The live *cost-to-finish* roll-up shipped; what's missing is a per-Loom-project record of what a
  project has *already* spent. Only the global account credit ledger tracks historical spend today.
  Low priority, but needs scoping before build.

- **Contest workbench (beyond Shortlist)**
  The "☆ Shortlist" staging step shipped. The larger workbench — deadline tracking, submission
  management — is still just wanted, not scoped.

---

## Later — directional / banked

- **Epic A — The Foundry (image → 3D print).** Gated on an explicit go, resin-first, its own optional
  install, never bundled. Stage 1 is a go/no-go spike (one image → mesh → printable). Low priority.
- **Epic B — Provider Deck.** A provider seam so a second generation backend can plug in; build it
  only when a real second provider actually lands (so two concrete cases shape it). Low priority.
- **Themed progress bar art.** A moon-phase gauge (near-finished art already banked) for
  generation/render/job progress. Decided in principle, unbuilt.
- **Real unlock SFX.** The loader ships and falls back to a synth chime; the actual sound assets are
  still to be sourced/added.
- **Feat badge art.** The 11 feat-tier badge prompts are written but generation is parked on cost.
- **BlurHash grid placeholders.** A `blurhash` column is stored but there's no front-end decoder /
  placeholder render. Low ROI; revisit if it matters.
- **Branding-unlock fanfare.** A large celebration for the hidden branding unlock, in the same class
  as the Konami one. Banked, unscoped.
- **Loom preview / placement follow-ups.** A handful of small Loom tweaks on a surface the owner
  already likes. Low priority, deliberately unscoped — owner to walk it.
- **Public-docs spoiler-hygiene pass.** `ART.md` / roadmap notes still describe achievement
  internals; decide what moves to private, what's trimmed, what stays. Low priority.
  **Known live leaks:** `wiki/Folio-of-Honors.md` prints the skin-unlock threshold table, and
  `wiki/Control-Panel.md` names the gated Branding tab — both need the same scrub the changelog
  already got.

- **Dead achievements in Completionist's pool.** Three required achievements are permanently
  unearnable (`first-enhance`, `enhance-adept`, `full-toolbox` — all depend on the removed
  `/api/enhance`), so Completionist cannot be earned as it stands. Needs a call: exempt them,
  repoint the metrics, or replace the rungs. Folds into the ladder-rung rework.

- **`mark_12` (Gem Tome) removal never executed.** Owner ruled 2026-07-23 to remove it; it is
  still shipped in `marks.json`. Small, just never done.

---

## Backlog — needs scoping

From the 2026-07-16 persona sweep, tagged "Scope": wanted, but each needs a real definition before
it's actionable. Listed so they aren't lost, not because they're ready.

- **Loom:** takes / per-shot generation history · draft-quality blocking pass · project "Look" block ·
  re-anchor warnings on the reel · music bed under Play · editor handoff export (per-shot trims + CSV/EDL).
- **Curator:** smart collections (saved queries as live collections) · search operators
  (`seed:` `aes:>` `ar:`) · collections manager (rename/merge/delete) · archive-integrity job.
- **Power user:** prompt-matrix queue runs · metadata recovery for hand-made folders.

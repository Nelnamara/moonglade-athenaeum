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

- **Remix: send a picture's recipe back to Generate** — [issue #4](https://github.com/Nelnamara/moonglade-athenaeum/issues/4)
  Load a picture's *full recipe* (prompt + negative + seed + model + LoRAs) into the Generate
  drawer in one click, the way PixAI itself does — the point is going back to a good image and
  re-running it against different models. Today the lightbox/details only send the *image* to Edit
  or Video; the recipe slab is read-only display. Verified: no code for this exists anywhere.
  A "send to image" button on Image Details is the asked-for shape; the grid right-click menu
  already exists as a second entry point.

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

- **Marks render too small, everywhere they appear**
  A recurring complaint since the beginning that keeps getting deprioritised as cosmetic. It is a
  real sizing defect, not a taste question — fix it alongside any mark-system work. The header is
  the current worst example.

- **Earned rewards: extend beyond skins**
  The Folio's "earned rewards" section is real and shipped, but only shows **skin** unlocks. Extend
  it to cover **banner** and **icon** unlocks plus the easter egg. Build-more, not a reshape.

- **Real generation progress, if PixAI exposes it**
  An old rule said never show progress because PixAI exposes none — that's wrong: the site shows
  graphical progress. Worth probing what's actually available and surfacing it honestly. The one
  hard constraint that stands: never *fabricate* progress, and never let a queue-wait estimate
  read as a render ETA.

- **Retest the V3.0 Lite 15s decline in the new UI**
  The old cause (audio fields sent to a model that rejects them) was found and fixed, but that was
  on the classic UI. Not re-verified since the React cut — submit V3.0 Lite at 15s and confirm it
  snaps to 10s and renders rather than declining.

- **Test the branding drop-file detection end to end**
  A dropped file in `branding/` is detected on the next Panel/branding surface load (deliberate
  design — no filesystem watcher), and that same sweep is what arms the hidden achievement.
  Verify it directly on a real install: drop a file, load the surface, confirm it's adopted and
  the flag arms. If a dropped file goes undetected, that's a bug in the sweep, not the design.

- **Confirm the live mirror really self-heals**
  The mirror is supposed to recover its own gaps automatically after a drop, stale socket or
  restart — no manual Panel job. That was the requirement ("im not suppposed to have to"), but it
  hasn't been re-confirmed lately. Verify it in practice; if it holds, the old guardrail note can
  stay retired.

- **Contest workbench (beyond Shortlist)**
  The "☆ Shortlist" staging step shipped. The larger workbench — deadline tracking, submission
  management — is still just wanted, not scoped.

---

## Design-pass reworks — owner wants these rescoped, not just built

- **Masked-feats presentation.** Today a masked feat shows its art in full color with name/text
  withheld. Owner wants to rescope/redesign the whole masked-fields idea, not just keep the
  old call.
- **Ladder representative badges.** Ladders currently show their FIRST rung's art (to avoid
  top-tier spoilers). Owner wants a new design pass on ladder badges.
- **Roast NSFW gating.** The spicy-roast double gate (server withholds unless the feat is
  earned + a local preference) needs a rework.
- **Achievement roster: 57 → 60, possibly more.** The 60 ceiling is under discussion — the
  roster may grow past it. Folds into the ladder-rung rework.
- **Community features YES-list revisit.** The 2026-07-26 pick-list (like/react etc.) predates
  v3.0 — revisit what Moonglade should get now the React app is the whole front end.
- **Sign-in ⇄ create-account toggle.** The login design showed a mode toggle that was
  deliberately not shipped (`no_accounts` decides the mode). Owner wants to explore options.
- **Project export tiers.** Shot list / lightweight backup / full bundle works but may deserve
  a better shape — scope alternatives.

## Scoped-but-unbuilt — decided once, never executed

- **Generation Flags: scope it or drop it.** Owner, verbatim: "either we keep deferring this
  or it's actually done. WHAT is the scope." The one concrete near-free version: flag
  near-duplicate generations. Still unanswered.
- **Reward-marker reconciliation.** The handful of achievements carrying ad-hoc reward markers
  (bare skin id, bare banner boolean) predate the bundle design and must be reconciled INTO
  bundles, not extended alongside. First deliverable: inventory what is currently PROMISED
  anywhere in the UI so promises are honoured before new rewards are assigned.
- **Enhance-achievement retool.** The banked replacement for the three dead achievements:
  "generate on five different base architectures" (DiT.1/DiT.2/DiT.3/SDXL/SD 1.5) at 1/3/5
  rungs. Designed, deliberately not built until the booster fix landed — unblock and build.
- **Booster gating fix.** PixAI offers boosters PER-MODEL (measured live: Tsubaki.2 offers only
  Quality Tag + To Video, both members-only); our drawer offers all three on everything. The
  proper fix needs a probe of the real per-model booster matrix, then scope.
- **Similarity-index incremental sync.** Decided: ship an incremental top-up entry point for
  the embedding index instead of a faster full rebuild. Never built.
- **Install-folder tidy.** "A tidy install folder says a lot" — achievement/branding files
  still sit loose at the install root. Partly addressed by the container; finish the thought
  (possibly alongside the final naming pass, which may move `branding/` once more).
- **JWT mirror toggle.** Mirroring generations into the PixAI library is a credential switch
  (browser JWT instead of API key) — proven by a real submission. The toggle was scoped once
  and the scoping notes were possibly lost in the docs purge (re-derive from git history if
  needed). Bonus worth probing: the JWT bridge may make some panel apps unreachable to the API
  key accessible to us.
- **Community read-only surface.** Scouted data (per-artwork view counts — which dwarf likes —
  lifetime stats, contest catalog). Much has since shipped in some form; audit what's left
  worth surfacing before building anything.
- **Dead-code sweep.** With the React rebuild done, sweep for orphaned code the classic cut
  left behind (e.g. `--faststart-videos` is deprecated in place; what else is dead?).
- **Enforce the bundle's unlock split in code.** The decided split (branding slots open on the
  "Under the Hood" unlock; badges, Konami assets, tier frames, and any file carrying achievement
  data stay sealed to the achievements that earn them) is NOT yet what the code does — badges,
  Konami assets and frames are still counted as part of "Branding." Split them out so the
  branding unlock cannot reach them, and verify the boundary is exactly the documented one
  (mascots are Flair and open; badges are "the sauce" and sealed).

## Open questions — need a call before they can be scoped

- **Does the Loom become part of the same app?**
  Today they are two separate builds: the gallery app (`gallery/dist/app.js`) and the Loom
  (`loom/dist/master-storyboard.bundle.js`), with the gallery reaching the Loom by full-page
  navigation to `/loom`. Nothing says whether they should merge. This is not a wiring task — the
  two load React by incompatible means, and the Loom's root component would have to be broken up
  before it could be embedded. Worth deciding deliberately, not drifting into.

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

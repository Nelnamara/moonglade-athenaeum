# The Curation Standard — Moonglade house baseline

> **Owner-approved 2026-07-12** ("that's the baseline"). The baseline every **selection /
> vote artifact** is built to — so we clone one proven pattern instead of rebuilding it
> (and losing features) each time. Every rule below exists because its absence broke a real
> vote this project ran.
>
> Browsable version (the presentable spec): artifact **6d6b9d2d-281e-4fd5-b1dc-7a11c599950e**.
> Reference implementation: **`docs/curation_reference_builder.py`** (a copy of the build that
> produced the approved Curation Workspace). **Never start a picker from a blank file — clone it.**

**When to use:** any time Claude presents **more than ~5 candidates** for the owner to choose
among — art picks, model/LoRA picks, design options, badge/frame/icon selection, etc.

---

## §1 — The Non-Negotiables

Ten things every selection artifact has. The ones marked **MUST** are hard requirements.

1. **Completeness, asserted — MUST.** Every candidate appears. The builder ends with a hard
   `assert len(placed) == len(folder_imgs)` that **fails the build** rather than let a file slip.
   A catch-all **"Everything Else"** section absorbs anything the classifier doesn't place —
   still rankable, never hidden.
   *Why: a filename classifier silently dropped ~half the gems. Nothing gets cherry-picked out again.*
2. **See it — click to enlarge — MUST.** Every thumbnail opens a **lightbox**: large image,
   arrow-key ←→ through the section, `Esc` to close, `P` to pick. Alpha shown over a checkerboard.
   *Why: tiny non-clickable thumbnails make real judgment impossible — you can't score facet quality at 130px.*
3. **Pick is the primary action — MUST.** A binary **Pick** toggle on every card and in the
   lightbox. This is the decision; it glows when selected. Ranking is a separate, optional layer —
   never the only way to choose.
   *Why: forcing a 1–5 star score to "pick" something is fiddly and wrong — "I can score but can't pick."*
4. **Rank is optional, and implies a pick.** Up to **5 stars** per section to order favorites
   (#1–#5). Starring auto-picks; clearing all stars leaves the pick intact.
5. **Notes per section, autosaved** to `localStorage` on every keystroke.
6. **A picks tray** — a docked, expandable strip showing the current selection grouped by
   section, in ranked order, each removable. The running decision is always visible.
7. **Export — copyable handoff — MUST.** One button assembles picks + ranks + notes into a
   plain-text block with a Copy button. The artifact sandbox blocks downloads — **always a
   copy-panel, never a download** (see `feedback_artifact_sandbox`).
   *Why: the output has to come back to Claude to get wired.*
8. **Persistence — MUST.** Picks, ranks and notes live in `localStorage` — work survives a
   reload or a redeploy of the same artifact.
9. **Claude's read, grounded.** Recommendations are marked **on the cards** (a `✦ my pick`
   badge) *and* explained per section — always after **actually viewing** the art, with the
   technical facts (alpha %, dimensions, composition), never guessed from filenames.
   *Why: ranking crystals by alpha-percentage without looking produced a wrong pick.*
10. **Metadata on every card.** Stable ID (`SECTION+n`), source tag (gallery vs folder), a
    real-alpha dot, and dimensions in the lightbox caption.

## §2 — The four verbs (keep separate)

Conflating Pick and Rank is what broke the last three attempts.

- **Pick** — *the decision.* Binary, "yes this one." Primary, big, one click. Collects in the tray.
- **Rank** — *optional.* Order your picks #1–#5 within a section. Auto-picks.
- **View** — *judgment.* Click to enlarge; the only way to actually assess art. Keyboard-navigable.
- **Note** — *context.* Per-section thoughts; rides along in the export.

## §3 — Do & Don't (the graveyard — every "don't" already happened here)

| Do | Don't |
|---|---|
| Show **every** candidate; assert the count in the build | Let a **filename classifier** quietly drop candidates |
| Make thumbnails **click to enlarge** | Ship **tiny, un-clickable** thumbnails |
| Give a clear binary **Pick** toggle | Make **ranking the only** way to select |
| Recommend only **after viewing** the art | Judge quality from **alpha % or filenames** |
| **Clone** the reference builder & smoke-test it | **Rebuild from scratch** — features drift and vanish |
| Group by need, with a catch-all for the unsure | Offer a download (sandbox **blocks** it) instead of a copy-panel |

## §4 — House tokens (so every vote artifact reads as one system)

Dark, single-theme — the Athenaeum's violet world, deliberately.

- Ground `#0d0b1a` · panel `#191530` · line `#322a52`
- Lavender (accent) `#b692e6` · mauve `#c9a6ff`
- **Emerald = picked `#4fc99a`** · **Gold = ranked `#e0c268`** · blue = has-alpha `#7fb0f4`
- Ruby `#e0355e` · gunmetal `#8a93a2` (feat tier)
- Display: **Georgia serif** (titles/section heads) · Body/UI: system sans · Data: `ui-monospace`
  (IDs, counts, hex, tabular numbers)
- Semantic colour (picked/ranked/alpha) is separate from the lavender accent.

## §5 — Build discipline (how one gets made, every time)

1. **Clone `docs/curation_reference_builder.py`.** Never start from a blank file.
2. **Source candidates comprehensively** — iterate the whole folder/collection; classify into
   sections and route anything unmatched to "Everything Else."
3. **Assert completeness** — `assert len(placed) == len(folder_imgs)`; the build refuses to run if
   a file is missing.
4. **Ground the picks** — view the candidates, then write recommendations with real technical +
   thematic reasons; mark them on the cards.
5. **Smoke-test before publishing** — serve it, drive pick/rank/lightbox/export in a browser.
   (This caught a real crash — ranking while the lightbox was closed.)
6. **Watch the weight** — inline images add up; past ~6–8 MB, drop embed resolution or give
   reference-only items smaller thumbs.
7. **Publish & log** — redeploy to the same URL on updates; add the artifact to the ledger in
   `docs/STATE.md` (§ Locked design → Artifact ledger).

---

*Drafted from the selection-artifact work of 2026-07-12; approved by the owner with no changes.
Related: `feedback_artifact_sandbox`, `feedback_cohesion`, `feedback_design_intent`.*

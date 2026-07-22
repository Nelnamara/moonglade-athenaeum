# Moonglade Standards — the house baseline

Two owner-approved standards this project holds every build to:

- **Part 1 — The Curation Standard.** The baseline every selection/vote artifact is built to.
- **Part 2 — Design Workflow.** The pixel-source-of-truth rule: no user-visible design build
  proceeds from prose alone.

This file **is** the standard — the sole live copy. It replaces two standalone files
(`docs/CURATION_STANDARD.md`, `docs/DESIGN_WORKFLOW.md`), now frozen in `docs/archive/`
(2026-07-17): a merge into one file was recommended a day earlier and left undone, and in that
gap the standalone `DESIGN_WORKFLOW.md` visibly drifted from the corrected text living here —
the exact failure this file exists to prevent. Edit here; there is no second copy to keep in sync.

---

## Part 1 — The Curation Standard — Moonglade house baseline

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

### §1 — The Non-Negotiables

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

### §2 — The four verbs (keep separate)

Conflating Pick and Rank is what broke the last three attempts.

- **Pick** — *the decision.* Binary, "yes this one." Primary, big, one click. Collects in the tray.
- **Rank** — *optional.* Order your picks #1–#5 within a section. Auto-picks.
- **View** — *judgment.* Click to enlarge; the only way to actually assess art. Keyboard-navigable.
- **Note** — *context.* Per-section thoughts; rides along in the export.

### §3 — Do & Don't (the graveyard — every "don't" already happened here)

| Do | Don't |
|---|---|
| Show **every** candidate; assert the count in the build | Let a **filename classifier** quietly drop candidates |
| Make thumbnails **click to enlarge** | Ship **tiny, un-clickable** thumbnails |
| Give a clear binary **Pick** toggle | Make **ranking the only** way to select |
| Recommend only **after viewing** the art | Judge quality from **alpha % or filenames** |
| **Clone** the reference builder & smoke-test it | **Rebuild from scratch** — features drift and vanish |
| Group by need, with a catch-all for the unsure | Offer a download (sandbox **blocks** it) instead of a copy-panel |

### §4 — House tokens (so every vote artifact reads as one system)

Dark, single-theme — the Athenaeum's violet world, deliberately.

- Ground `#0d0b1a` · panel `#191530` · line `#322a52`
- Lavender (accent) `#b692e6` · mauve `#c9a6ff`
- **Emerald = picked `#4fc99a`** · **Gold = ranked `#e0c268`** · blue = has-alpha `#7fb0f4`
- Ruby `#e0355e` · gunmetal `#8a93a2` (feat tier)
- Display: **Georgia serif** (titles/section heads) · Body/UI: system sans · Data: `ui-monospace`
  (IDs, counts, hex, tabular numbers)
- Semantic colour (picked/ranked/alpha) is separate from the lavender accent.

### §5 — Build discipline (how one gets made, every time)

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

*Drafted from the selection-artifact work of 2026-07-12; approved by the owner with no changes.
Related: `feedback_artifact_sandbox`, `feedback_cohesion`, `feedback_design_intent`.*

---

## Part 2 — Design Workflow: the pixel source of truth standard

> **Standing rule: no user-visible design build proceeds from prose alone.** Every visual build
> works from a pixel source of truth (a Figma frame, a Claude Design project, or a locked mockup
> artifact) and verification includes a "does it match the source" pass. This extends the
> CLAUDE.md checkpoint protocol.

**Origin:** a shipped, owner-approved surface (the Trophy Hall, since renamed the Folio of
Honors) was once reformatted from prose roadmap notes — ladder carousel, toast-styled tiles,
rewards bar — and landed off the owner's locked visual target: locked work undone, without
permission, because prose specs are lossy and get re-interpreted every session. The checkpoint
protocol alone did not prevent it. Separately, the owner had asked about Figma tooling on 3+
occasions and was dismissed — that dismissal is a banked never-repeat. Full incident record:
`CHANGELOG.md`; the revert and the eventual redesign are covered below.

### The standard

1. **Before building anything user-visible:** obtain the visual source of truth. Priority order:
   the owner's Figma frame → a Claude Design project → a locked mockup artifact (by id).
2. **During the build:** implement from the source (Figma MCP reads the actual frame: components,
   variables, layout — no re-interpretation).
3. **Before calling it done:** verify side-by-side against the source. "Browser-verified it renders"
   is NOT the bar; **matches-what-was-decided** is the bar.
4. Locked designs are deliverables. Restyling/reorganizing a shipped, owner-approved surface
   requires an explicit owner go — never fold it into another change.

### Tooling

| Tool | What it does | Status |
|---|---|---|
| **Figma plugin** (`figma@claude-plugins-official`) | **Bidirectional**: paste a frame URL → Claude implements from the real frame data; Claude can also write UI back to the Figma canvas as editable layers. Ships MCP server + agent skills (figma-design-to-code, figma-use, …). | Skills installed; **MCP is live and authenticated** (per `docs/STATE.md`) — no auth step needed. |
| **Claude Design** (claude.ai/design, Anthropic Labs) | Design-system projects that **round-trip with Claude Code** — import a design system, design with those exact components, hand off a bundle Claude Code implements from. Research preview, Pro/Max. | Harness has native support via the `DesignSync` tool (no dedicated skill by that name is present — drive the tool directly). Candidate: push `DESIGN_TOKENS_CSS` + the `mg-*` web components + the toast as the Moonglade design system. |
| **Auth-free, installed now** | `web-artifacts-builder`, `canvas-design`, `theme-factory`, the `design:*` suite (design-critique / design-system / design-handoff), `dataviz` | Usable immediately, no connector auth. |
| Canva plugin | Import/generate/export designs | Present; needs connector auth. |
| Community (Superdesign, claude-talk-to-figma-mcp) | Figma→code workflows | Superseded by the official plugin + Claude Design; not recommended. |

**The working pipeline:** owner designs/locks a frame in Figma (screenshotted real app assets are
fine) → pastes the frame URL → Claude implements from the frame → verifies against it → owner QA.

### The Folio of Honors (formerly Trophy Hall) — redesign shipped 2026-07-22

The revert (`0a8da3a` reverts `c877919`) restored the pre-reformat Hall — the chosen path
(Option A); the alternative, rebuilding from the Figma mock and treating the reformat as
throwaway scaffolding (Option B), was not taken at the time. It **was** taken later: the owner
delivered a finished redesign as a full code export (React/Tailwind, Figma Make), built partly
from the legendary/feat frame slice values Claude had handed off earlier that same night —
confirmed byte-for-byte identical tier-triad colors to what the toast already shipped, a strong
signal it carried real values through rather than approximating. Ported to this app's actual
vanilla JS/CSS (not adopted as React — the app has no other React surface besides the Loom) and
verified against live data in-browser before shipping. Also renamed Trophy Hall → **The Folio of
Honors** in the same pass, the owner's pick off `docs/STATE.md`'s shortlist.

Backend infra from the original arc — earn-date persistence, the badge thumb-cache — lived in
earlier commits and survived both the revert and the redesign: `43014ef`'s mystery-tile wiring
predates the reformat and is still live, unchanged, in the new design too. Of the two owner
calls the revert left unresolved:

1. **Feats invisible until first earn** ("the whole feats section stays cloaked until the first
   feat lands") — **deliberately left untouched by the 2026-07-22 redesign.** This is a behavior
   question, not a visual one, and the owner did not ask for it to change — folding it into the
   redesign commit would be exactly the "restyling a shipped surface without an explicit go"
   mistake this doc exists to prevent. Still open; still needs its own owner call if the intent
   really is to lift the section cloak rather than the whole-section hide.
2. **Badges/mascots/frames are machine-local** (`out_dir/branding/`, on the home run copy) —
   unaffected by the redesign, still true.

### Model strategy (owner's credit-efficiency guidance)

- **Sonnet 5 = the daily driver** — wiring, tests, doc passes, routine builds, most suite work.
- **Opus 4.8 = the heavy turns** — architecture calls, gnarly debugging, design-fidelity
  implement-from-frame passes; `/fast` available.
- **Fable 5 (Claude 5) = surgical apex** — the highest-stakes design/architecture moments only.
- **Ultracode/workflows:** keep fleets small + surgical (owner rule). Value pattern: cheap models /
  `low` effort for mechanical fan-out stages, high effort reserved for the judge/verify agents
  (per-agent `model`/`effort` overrides in the workflow script). Never run a big fleet on the top
  model for mechanical work.

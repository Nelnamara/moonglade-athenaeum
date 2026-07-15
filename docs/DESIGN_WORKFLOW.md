# Design Workflow — the pixel source of truth standard

> Born 2026-07-14 from the Trophy Hall incident. **Standing rule: no user-visible design build
> proceeds from prose alone.** Every visual build works from a pixel source of truth (a Figma frame,
> a Claude Design project, or a locked mockup artifact) and verification includes a
> "does it match the source" pass. This extends the CLAUDE.md checkpoint protocol.

## The incident (why this doc exists)

An overnight session (commit `c877919`, 2026-07-14) reformatted the shipped Trophy Hall from prose
roadmap notes — ladder carousel, toast-styled tiles, rewards bar — and landed **way off the owner's
intended visual target**. Locked, DONE work was undone; cards were reorganized and art handling
changed without permission. Root cause: prose specs are lossy — every session re-interprets them.
The checkpoint protocol alone did not prevent it. Separately: the owner had asked about Figma
tooling on 3+ occasions and was dismissed — that dismissal is now a banked never-repeat in memory.

## The standard

1. **Before building anything user-visible:** obtain the visual source of truth. Priority order:
   the owner's Figma frame → a Claude Design project → a locked mockup artifact (by id).
2. **During the build:** implement from the source (Figma MCP reads the actual frame: components,
   variables, layout — no re-interpretation).
3. **Before calling it done:** verify side-by-side against the source. "Browser-verified it renders"
   is NOT the bar; **matches-what-was-decided** is the bar.
4. Locked designs are deliverables. Restyling/reorganizing a shipped, owner-approved surface
   requires an explicit owner go — never fold it into another change.

## Tooling (state as of 2026-07-14)

| Tool | What it does | Status |
|---|---|---|
| **Figma plugin** (`figma@claude-plugins-official`) | **Bidirectional**: paste a frame URL → Claude implements from the real frame data; Claude can also write UI back to the Figma canvas as editable layers. Ships MCP server + agent skills (figma-design-to-code, figma-use, …). | Skills installed on the work machine; **MCP needs one-time auth: run `/mcp` in an interactive `claude` terminal** (OAuth can't run in non-interactive sessions). Repeat per machine. |
| **Claude Design** (claude.ai/design, Anthropic Labs) | Design-system projects that **round-trip with Claude Code** — import a design system, design with those exact components, hand off a bundle Claude Code implements from. Research preview, Pro/Max. | Harness has native support: the `DesignSync` tool + `/design-sync` skill. Candidate: push `DESIGN_TOKENS_CSS` + the `mg-*` web components + the toast as the Moonglade design system. |
| **Auth-free, installed now** | `web-artifacts-builder`, `canvas-design`, `theme-factory`, the `design:*` suite (design-critique / design-system / design-handoff), `dataviz` | Usable immediately, no connector auth. |
| Canva plugin | Import/generate/export designs | Present; needs connector auth. |
| Community (Superdesign, claude-talk-to-figma-mcp) | Figma→code workflows | Superseded by the official plugin + Claude Design; not recommended. |

**The working pipeline:** owner designs/locks a frame in Figma (screenshotted real app assets are
fine) → pastes the frame URL → Claude implements from the frame → verifies against it → owner QA.

## Trophy Hall recovery plan (owner to choose at the home machine)

- **Owner is building a Figma mock** of the intended Trophy Hall using screenshots of real app
  assets — that mock becomes the source of truth for the rebuild.
- **Option A — revert `c877919`** (the reformat commit): restores the pre-reformat Hall now.
  Backend infra from the same arc (earn-dates, badge thumb-cache) lives in earlier commits and
  survives. Check `git log` at recovery time — later commits touching the same regions may need
  conflict resolution.
- **Option B — leave it, rebuild from the Figma mock** once the plugin is authed, treating the
  reformat as throwaway scaffolding.
- **Two caveats that are NOT the reformat's fault:**
  1. **Feats invisible until first earn was the ORIGINAL owner-approved spec** ("the whole feats
     section stays cloaked until the first feat lands"). Mystery-tile art WAS wired on 2026-07-14
     (`43014ef`, pre-reformat) for masked feat CARDS — but the whole-SECTION cloak still hides
     feats entirely on a zero-feat gallery. **Owner call for the rebuild: lift the section cloak so
     unearned feats show as mystery tiles** (which appears to be the actual intent).
  2. **Badges/mascots/frames are machine-local** (`out_dir/branding/` on the home D:). A test
     gallery without that art falls back to emoji — that's absent assets, not killed branding.

## Model strategy (owner's credit-efficiency guidance)

- **Sonnet 5 = the daily driver** — wiring, tests, doc passes, routine builds, most suite work.
- **Opus 4.8 = the heavy turns** — architecture calls, gnarly debugging, design-fidelity
  implement-from-frame passes; `/fast` available.
- **Fable 5 (Claude 5) = surgical apex** — the highest-stakes design/architecture moments only.
- **Ultracode/workflows:** keep fleets small + surgical (owner rule). Value pattern: cheap models /
  `low` effort for mechanical fan-out stages, high effort reserved for the judge/verify agents
  (per-agent `model`/`effort` overrides in the workflow script). Never run a big fleet on the top
  model for mechanical work.

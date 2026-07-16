# Roadmap — the two horizon epics

Confirmed direction, deliberately *not* started yet. Each stacks on the job-runner /
provider-seam patterns the suite already has. See `docs/REFINEMENTS.md` for the near-term
tracker; this file is the far-horizon plan.

---

## Epic A — The Foundry (image → 3D print) · item #10

**Confirmed.** Hardware: RTX 4070 Super **12 GB** + resin **Anycubic**. Resin-first
(skip texture baking — color is irrelevant for resin; single-image backs are hallucinated,
so orient the weak side toward the build plate).

**Separate optional install** — several GB of model weights + CUDA deps, NEVER bundled into
the main tool. Gated behind its own extra.

| Stage | Work | Gate |
|---|---|---|
| **1 · Spike** | Standalone script: one gallery image → **Hunyuan3D-2 mini/turbo** (pip + weights, CUDA, CPU-offload if VRAM-tight) → export **GLB**. Judge quality on a real Nelnamara render. | **Go/no-go.** If 12 GB + mini gives figurine-grade output, proceed. If not, pivot to Meshy API (Epic B provider). *Waiting on owner's go.* |
| **2 · Cleanup** | Headless Blender (already wired): import GLB → decimate, make-manifold, recompute normals, auto-orient for resin → export **watertight STL**. | Clean STL that slices in Photon Workshop. |
| **3 · Integration** | "Send to Foundry" button (detail + right-click) → async job (reuses submit/poll/collect + **Jobs tray**) → **three.js GLB mesh preview** → **STL download**. Mesh stored beside the image in the catalog. | Owner picks an image, gets an STL. |
| **4 · Provider seam** | Meshy / Tripo API as a fallback provider behind the same interface — **this is Epic B**. | — |

---

## Epic B — The Provider Deck (multi-platform generation) · the architectural one

Turn the single-provider create surface into a **deck** of backends, keyed by API keys.
PixAI is already **provider #1** behind the seam — `submit_generation` /
`generation_status` / `collect_generation` + `build_shot_video_params` ARE the interface.

**Shape:**
- `providers.json` (owner-local, git-ignored): API keys + enabled providers.
- A **provider picker** in the drawer / Loom (choose backend per generation).
- Each provider is one adapter file mirroring the interface — Seedance is a *second file*,
  not a rewrite (the discipline that kept PixAI Phase-2 seam-clean).

**Provider #2 — Seedance 2.0 direct** (`api.seedance2.ai`):
- `Authorization: Bearer sk_live_…`, `POST /v1/videos/generations` → taskId, poll
  `GET /v1/tasks/:id` (≤1/10s) or webhook.
- Modes text / image(1-2) / reference(≤9 img, 3 vid, 3 audio) → map 1:1 to our
  T2V/I2V/FLF/R2V/V2V. Same `@image1/@video1/@audio1` grammar as PixAI.
- Credits reserve-on-submit / charge-on-success / refund-on-fail (same as PixAI).
- **The one genuinely new problem:** Seedance wants **publicly-reachable URLs** for input
  media; a localhost server can't hand it a reachable URL. Options to solve when we build:
  (a) Seedance's own upload endpoint if it has one, (b) a temporary tunnel, (c) a short-lived
  presigned upload. Bank the answer during the spike.

**Provider #3+ — the Foundry's Meshy/Tripo** rides this exact pattern (a mesh provider
instead of a video provider).

**Discipline:** do NOT build the full abstraction speculatively. Add the seam only when the
second real provider (Seedance) lands, so it's shaped by two concrete cases, not one.

---

---

## Epic C — Publish & Community integration (core + web) · added 2026-07-15

**Confirmed direction, roadmapped into the next core + web passes** — owner's presence/art is
gaining real traction, reopening a capability that was deliberately shelved earlier in the
project's life ("just a backup tool" then; not anymore).

**Already reverse-engineered, documented, deliberately OFF today** (`private/API_OPERATIONS.md`
+ `private/APP_OPERATIONS_FULL.md`): `createArtworkFromTaskV2` (publish a generation as an
artwork), `upsertArtwork`/`deleteArtwork`, `markArtwork` (like/bookmark), follow, and read
metadata on your own published artworks (already live via `--sync-artworks`, distinct from
this — that's read-only history sync, this is publish/social *action*).

**Standing design constraint carried over from `private/APP_OPERATIONS_FULL.md`'s own note:**
*"Never used for spend/social/publish without explicit owner direction... mutations exist but
stay OFF by design."* This epic changes that default deliberately, not by accident — scope as:

- **Core (CLI):** a `--publish-artwork <media_id>` (or similar) command, explicit-confirm gated
  like every other spend-adjacent action, even though publishing itself is free — the gate here
  is about deliberateness, not cost.
- **Web:** a Publish action from the gallery detail page / lightbox, with the same "you did this
  on purpose" confirmation model as delete — never a background/automatic action, never
  default-on for a whole batch.
- **Like/follow:** lower priority than publish; scope only if there's a concrete use (e.g.
  liking your own cross-posted variants, following collaborators) — don't build speculative
  social-graph features nobody asked for.

**Discipline, matching Epic A/B's own rule:** don't build the full surface speculatively — start
with publish (the concrete, stated want), let like/follow follow only if a real need shows up.

---

## Sequencing note
Both epics wait on an explicit "go." Foundry Stage 1 is the nearer of the two (self-contained
spike, no external account). The Provider Deck is bigger and benefits from the Foundry proving
the provider-seam pattern a second time first. Epic C (Publish & Community) is independent of
A/B and can move whenever core+web capacity allows — it doesn't share the provider-seam
prerequisite the other two do.

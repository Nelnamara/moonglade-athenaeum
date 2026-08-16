# Roadmap

Planned and outstanding work for Moonglade Athenaeum. **One home per fact:**

- **Shipped** → `CHANGELOG.md` (dated taglines). Nothing here once it ships — it *moves*.
- **Why a decision was made** → the internal decisions ledger (private companion repo).
- **Bugs** → GitHub Issues.
- **Planned work** → this file. (A small set of internal design items lives in the private
  companion repo's roadmap instead; this file is the default home for everything else.)

Format is Now / Next / Later. Each item says what it is, why, and what it touches. When an
item ships, delete it here and add a CHANGELOG line — never annotate "done" in place.

---

## Now — active

*(the current active thread is internal design work — see Next for what's queued)*

---

## Next — scoped, not started

- **Stack by batch (gallery grid)**
  Collapse the grid into per-batch/per-task stacks instead of one flat wall. Related surfaces exist
  but don't cover it: a batch-filter drill-down and the Image Details lineage-siblings section. The
  grid-stacking itself is unbuilt.

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
  it to cover **banner** and **icon** unlocks. Build-more, not a reshape.

- **Real generation progress, if PixAI exposes it**
  An old rule said never show progress because PixAI exposes none — that's wrong: the site shows
  graphical progress. Worth probing what's actually available and surfacing it honestly. The one
  hard constraint that stands: never *fabricate* progress, and never let a queue-wait estimate
  read as a render ETA.

- **Confirm the live mirror really self-heals**
  The mirror is supposed to recover its own gaps automatically after a drop, stale socket or
  restart — no manual Panel job. That was the requirement ("im not suppposed to have to"), but it
  hasn't been re-confirmed lately. **Test recipe:** create the gap on purpose — stop the server,
  complete one generation while it's down (site or CLI from another window; or kill the network
  for a minute mid-generation instead), start it back up. The piece must appear in the gallery on
  its own within the sweep interval, with no manual sync. If the button has to be pressed, it
  failed.

- **Contest workbench (beyond Shortlist)**
  The "☆ Shortlist" staging step shipped. The larger workbench — deadline tracking, submission
  management — is still just wanted, not scoped.

- **Bonjour / mDNS advertising: the server announces itself on the LAN**
  Today a LAN device reaches the gallery only by a name the owner already knows and types
  (`http://<pc-name>.local:5000`, which works because every modern OS resolves `.local` on its
  own — that part needs no code). What's missing is *discovery*: the server registering an
  `_http._tcp` DNS-SD service (the `zeroconf` library, one new dependency) so a phone, tablet, or
  Bonjour-aware browser just **sees "Moonglade" on the network and taps it** — and so the app can
  own its advertised name (`moonglade.local`) instead of borrowing the PC's. Owner already runs a
  production server on `--host 0.0.0.0` under the machine name and wants this on top of it.
  **What it touches:** the `moonglade_gallery.py` startup path (register on start, unregister
  cleanly on stop/restart so a stale record doesn't linger after a `/api/server/restart`), and
  `Serve Gallery.pyw`. **Constraints already settled by reading the code:** (1) register only when
  the bind is a real LAN address (`--host 0.0.0.0` / a non-loopback host) — advertising a
  loopback-only server announces something no other device can reach; (2) it widens **reachability
  only, never trust** — the LAN gate is `_is_authorized_request()` (login on every path, no
  loopback bypass), so a discovered `moonglade.local` still has to sign in, and that must stay
  true; (3) `--https` currently uses Werkzeug's `"adhoc"` self-signed cert, which won't carry the
  advertised name — a discovered HTTPS service therefore needs a proper cert with the `.local`
  name in its SAN (mkcert-style), or the advertise step is HTTP-only until that lands. Pick one
  deliberately, don't ship a name that throws a cert warning on tap. **Design step first** — it's
  user-visible (what name/label appears in a device's discovery list, whether the mobile/QR access
  flow adopts it) — quick workshop, not a full pixel pass.

- **Generate drawer History: a real, scrolling 7-day run history with day markers** ([#13](https://github.com/Nelnamara/moonglade-athenaeum/issues/13))
  The `History` button in the Runs reel is hollow: it flips a flag and relabels the header
  "grouped by day," but the reel only ever holds `today` + `yesterday` from a 24-hour activity trail
  (`jobs.jsonl`), so there's never more than a day *to* group and older runs are compacted off disk.
  That two-bucket shape is a **literal port of the design prototype's demo limitation** — the spec
  (`design_handoff/design_handoff_moonglade_suite/generate-runs-spec.md`) was an in-memory demo with
  fake runs and names "back it with the actual generation-history API" as its own known gap. The
  gap was never closed. **Owner requirement:** History opens a *scrolling 7-day history with day
  markers*. **Build direction (decided, not a candidate):** catalog-backed — page 7 days of real
  finished generations out of the catalog (`created_at`), grouped by day with markers, scrolling;
  the live `jobs.jsonl` window covers only in-flight / just-finished runs layered on top. Reuse-
  prefill already works from a bare `media_id`, so no new storage, nothing to expire, and it survives
  every restart. Bumping `JOBS_KEEP`/`JOBS_MAX_AGE` instead is rejected (a second record drifting
  from the catalog; can't give a real 7-day scroll). Pairs with the full-metadata capture (richer
  recipes to prefill from) and with Remix (#4), which rides the same prefill path. **What it
  touches:** `RunsReel.jsx` (day grouping/markers/scroll), `GenerateDrawer.jsx` (the History
  toggle), a catalog-backed history route in `moonglade_gallery.py`. **Design step first** — the
  spec already provides the tile/cluster/sharpen-in reveal, so the delta is the day-marker
  treatment and scroll behaviour: quick workshop, not a full pixel pass.

---

## Design-pass reworks — rescope, don't just build

- **Ladder representative badges.** Ladders currently show their FIRST rung's art. A new design
  pass on ladder badges is wanted.
- **Community features YES-list revisit.** The 2026-07-26 pick-list (like/react etc.) predates
  v3.0 — revisit what Moonglade should get now the React app is the whole front end.
- **Sign-in ⇄ create-account toggle.** The login design showed a mode toggle that was
  deliberately not shipped (`no_accounts` decides the mode). Options to explore.
- **Project export tiers.** Shot list / lightweight backup / full bundle works but may deserve
  a better shape — scope alternatives.

## Scoped-but-unbuilt — decided once, never executed

- **Generation Flags: scope it or drop it.** Owner, verbatim: "either we keep deferring this
  or it's actually done. WHAT is the scope." The one concrete near-free version: flag
  near-duplicate generations. Still unanswered.
- **Install-folder tidy.** "A tidy install folder says a lot" — achievement/branding files
  still sit loose at the install root. Partly addressed by the container; finish the thought
  (possibly alongside the final naming pass, which may move `branding/` once more).
- **Community read-only surface.** Scouted data (per-artwork view counts — which dwarf likes —
  lifetime stats, contest catalog). Much has since shipped in some form; audit what's left
  worth surfacing before building anything.
- **Dead-code sweep.** With the React rebuild done, sweep for orphaned code the classic cut
  left behind (e.g. `--faststart-videos` is deprecated in place; what else is dead?).

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
- **BlurHash grid placeholders.** A `blurhash` column is stored but there's no front-end decoder /
  placeholder render. Low ROI; revisit if it matters.
- **Loom preview / placement follow-ups.** A handful of small Loom tweaks on a surface the owner
  already likes. Low priority, deliberately unscoped — owner to walk it.
- **Split the two megamodules (`moonglade_backup.py` / `moonglade_gallery.py`).** They are the
  repo's two largest, highest-complexity, most-churned modules — the top regression-risk / hotspot
  / refactor targets (Flare tracks the live scores). Split into cohesive modules to cut the risk.
  This is SPEND-PATH code, so it's **its own project with a design + adversarial review, NOT a side
  effect of the naming/tidy pass** — naming is a moving axis, this is a splitting axis. The smaller
  god-files (`loom-core.js`, `loom-mutations.js`, `CostBadge.jsx`, `UpscalePanel.jsx`,
  `videoDrawerCore.js`) can ride a structural pass instead; these two are banked as their own effort.

---

## Backlog — needs scoping

From the 2026-07-16 persona sweep, tagged "Scope": wanted, but each needs a real definition before
it's actionable. Listed so they aren't lost, not because they're ready.

- **Loom:** takes / per-shot generation history · draft-quality blocking pass · project "Look" block ·
  re-anchor warnings on the reel · music bed under Play · editor handoff export (per-shot trims + CSV/EDL).
- **Curator:** smart collections (saved queries as live collections) · search operators
  (`seed:` `aes:>` `ar:`) · collections manager (rename/merge/delete) · archive-integrity job.
- **Power user:** prompt-matrix queue runs · metadata recovery for hand-made folders.
- **Mobile:** Remix and Send to Video on the mobile details sheet — both need their own
  wiring into CreateMobile's composer (the sheet has no dock hand-off; Send to Video is
  already a disclosed stub there, Remix now ships desktop-only the same way).

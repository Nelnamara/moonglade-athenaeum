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

- **Recently shipped is not listed here** — the achievement sealing (definitions + art in the
  sealed pack, public source holds only opaque ids) landed in 3.5.0; this session's toast polish and
  video-Remix fix are in `CHANGELOG.md` (the 3.6.0 release), per the rule at the top of this file.

---

## In review — built, not merged

Every branch that is built but not on `master` is listed here with its review sheet, so work in
flight is never invisible. On 2026-09-06 six built branches existed that nothing named, which is
why this section exists.

- **`release/3.10.2`** — the 3.10.2 point release: the art-pack manifest now points at the current
  pack (so installs fetch it), plus the public-records spoiler scrub and the donor test-gate. Built,
  tests green, awaiting the boop to cut.

## Next — scoped, not started

- **The Loom inside the gallery — is a modal on one surface viable, and what would it take?**
  *(owner's scoping order, 2026-09-06, corrected the same evening)* The standing question "does
  the Loom become part of the same app?" is **not answered**; it has a scope order. The owner's
  ask: scope the viability of the Loom living inside the gallery as a modal, on one surface, and
  what rolling it onto one surface would involve. His lean ("it works best as its own arena
  connected to the gallery") is the thing that scope tests, not the answer. The 3.9.0 arena
  plumbing (a storyboard's own address, the return trip's memory, phones opening the phone
  layout) and the crossing design page in `../moonglade-internal/design/loom-arena/` are inputs,
  built on the earlier reading. Sources for the scope: the locked desktop and phone Loom Design
  Handoffs, the gallery's Design Handoffs, and the two-build fact (the gallery is
  `gallery/dist/app.js`, the Loom is `loom/dist/master-storyboard.bundle.js`, React loaded two
  incompatible ways, the Loom's root component would need breaking up). Next step: a workshop-prep
  document that walks each seam in three columns — what the design pages say, what the code does,
  what is undecided — then a workshop the owner drives. Frame and sources:
  `../moonglade-internal/scopes/PENDING_2026-09-06.md` §3; the decision record's 2026-09-06 entry.

- **Full mobile-surface audit against the designs.** *(owner, 2026-09-05, after the wave
  walkthrough)* "The next audit is going to be the full mobile surface against the designs."
  The walkthrough surfaced real phone breakage (contest detail scroll bleeding into the
  Control screen; a false "no search field on mobile" claim) — sweep every phone screen
  against its design source and the desktop behavior it mirrors, screen by screen, in a
  driven browser at phone size. The design-queue wave has merged, so nothing gates this.

- **Does a tablet tier exist?** *(tabled — owner wants to play in the app on the iPad first, 2026-08-23)*
  Today one hook (`MOBILE_QUERY` 430px + a coarse-pointer fallback that also requires width ≤ 430)
  routes every tablet to the DESKTOP build in both orientations. Three coherent answers: raise the
  breakpoint so tablets get the mobile build (one number, least work, most side effects on a
  desktop-shaped surface); add a real third tier; or keep the split and port touch affordances
  (always-visible card controls on coarse pointers, 44px targets) into the desktop components.
  The input for the call: `../moonglade-internal/QA_tablet-2026-08-23.md` — a targeted poke list
  built from the refit review's findings; which sections bite decides which answer.

- **The dial-in series — optional local-VLM naming** (the last remnant of [#34](https://github.com/Nelnamara/moonglade-athenaeum/issues/34))
  Everything else on this line shipped: the engine, grid stacking, the Session strip and
  prompt-derived names in 3.6.0; the series MODAL with its runs rail and facet chips (E) in
  3.8.0 (see `CHANGELOG.md`). What remains is only the **optional local-VLM module** (Provider
  Deck era, rerolls only) that would name a series from the *image* rather than the prompt —
  banked for when the Provider Deck seam exists.

- **Gift icon on promo cards** *(the last slice of [#26](https://github.com/Nelnamara/moonglade-athenaeum/issues/26))*
  The icon on the claim chip shipped 2026-08-22 and the claimed-reward line in the activity tracker
  shipped 2026-08-31 (3.7.0). What remains is the gift icon on future promo gifts — blocked until a
  promo/card-claim surface exists to carry it.


---

- **Full surface audit — Phases B and C** *(kept on the books — owner, 2026-09-04)*
  Phase A (the owner's walk, 2026-08-29) is done and fed #42–#51 and the S4 batch. What has never run:
  **Phase B**, a per-surface comp-diff of all 24 surfaces against their design mockups (one agent
  fan-out each), and **Phase C**, triage + re-verify of B's findings. Scope and severity scale:
  `../moonglade-internal/scopes/SCOPE_2026-08-26_surface-audit.md`. Not dropped; run when scheduled.

## Design-pass reworks — rescope, don't just build

- **PixAI inbox and comment replies.** Likes, bookmarks and follows are dropped (owner,
  2026-09-07: no reason to like or bookmark his own work). What stays: being told about comments
  and likes on his works, and replying to comments. A probe first, then a design session, then the
  build; a reply is the first write to PixAI other than generate and delete.

## Scoped-but-unbuilt — decided once, never executed

- **Install-folder tidy.** "A tidy install folder says a lot" — achievement/branding files
  still sit loose at the install root. Partly addressed by the container; finish the thought
  (possibly alongside the final naming pass, which may move `branding/` once more). Folds into the
  naming pass's Phase 2, scoped after 3.10 (owner, 2026-09-07).
- **Dead-code sweep.** With the React rebuild done, sweep for orphaned code the classic cut
  left behind (e.g. `--faststart-videos` is deprecated in place; what else is dead?). **Partly
  overtaken, not done (2026-08-24):** the architecture refactor wasn't a dedicated dead-code pass, but
  it removed real cruft in passing — the `_connect` catalog shim and the front-end `postJSON` helper are
  gone, `LibraryBar` shed thirteen dead props, and dozens of hand-rolled call sites collapsed onto single
  seams (the request module, the price transport, the library scan, `media_tools`). The item still stands
  as a deliberate sweep — the job is to hunt what's *left* (deprecated-in-place flags, orphaned
  classic-era code), not to bank the refactor's incidental cleanup as the sweep.

## Open questions — need a call before they can be scoped

- **App security review** *(owner, 2026-09-06: "I wonder if there is a better way to secure the
  app now that it has grown to this level")* — a proper audit of the auth surface: login and the
  no-accounts mode, session/JWT/cookie handling, the localhost trust model, mirror/write gating,
  and what "grown to this level" changes about the threat picture. Runs on the owner's go.
  Runs after 3.10 (owner, 2026-09-07).

---

## Later — directional / banked

- **Epic A — The Foundry (image → 3D print).** Gated on an explicit go, resin-first, its own optional
  install, never bundled. Stage 1 is a go/no-go spike (one image → mesh → printable). Low priority.
- **Epic B — Provider Deck.** A provider seam so a second generation backend can plug in. Per
  NORTH_STAR (locked 2026-08-25) the seam comes *before* the second provider — it is how the core
  proves itself provider-agnostic — and it follows the Loom-unify decision in that sequence. Low
  priority until that decision is taken.
- **Themed progress bar art.** A moon-phase gauge (near-finished art already banked) for
  generation/render/job progress. Decided in principle, unbuilt.
- **UPnP / SSDP (or WS-Discovery) LAN presence — show up in Windows Explorer's "Network".**
  Bonjour/mDNS (shipped) makes the server discoverable to phones/tablets and resolvable at
  `moonglade.local`, but Windows Explorer's Network folder browses UPnP/SSDP + WS-Discovery, NOT
  mDNS — so Moonglade never appears there (confirmed live 2026-08-25: the `.local` URL works from
  Windows, but nothing lists in Explorer). A separate advertiser — an SSDP/UPnP `rootdevice`, or
  the Windows-native WS-Discovery — would surface it as a device/link in Explorer's Network.
  Different protocol from Bonjour, its own dependency; cosmetic/convenience, not reachability. Low
  priority.
- **Give the asset pack a real file type.** In Explorer `moonglade.dat` shows a blank Type column and
  a generic icon (owner nitpick, 2026-08-22). `.dat` is too generic to claim system-wide, so the clean
  fix is an app-specific extension (`.mgpack` or similar) plus a ProgID the app registers for the
  current user on first run / from the launcher-shortcut path (friendly name "Moonglade asset pack",
  the app icon) — the same per-user registry spot the Desktop-shortcut code already writes. Touches the
  manifest/downloader file name, `_container_path()`, the builder's default `--out`, and the Release
  asset name, so it rides a pack rebuild, not a point release. Cosmetic; low priority.
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
  effect of the naming/tidy pass** — naming is a moving axis, this is a splitting axis. **The premise
  shifted (2026-08-24):** the architecture refactor did **not** split either file, so the item stands — but
  it carved named internal seams *within* both that a future split can lift out cleanly. In
  `moonglade_backup.py`: the `pixai_client` (PixAIClient) and `media_tools` sections and the
  `build_request`/`GenerationRequest` payload road; in `moonglade_gallery.py`: the `LIBRARY SCAN`,
  `CATALOG VERBS`, and catalog-road (`catalog()` / `migrate()`) sections. The seams are the hard part of a
  split, so the work is more tractable than it was — but still unbuilt, and still its own reviewed effort.
  The smaller god-files (`loom-core.js`, `loom-mutations.js`, `CostBadge.jsx`, `UpscalePanel.jsx`,
  `videoDrawerCore.js`) can ride a structural pass instead; these two are banked as their own effort.

---

## Backlog — needs scoping

- **First run, before the pack: the sign-in page is bare.** Until the setup wizard has downloaded
  the art pack, every branding image 404s by design, so a fresh install's sign-in page shows no
  banner and no mascot; the only art the code carries is the wizard's own downloader mascot
  (`gallery/src/art/nelWizard.js`). Owner, 2026-09-07, walking a fresh install: look at embedding the
  login banner (and the login mascot) the same way, since the pack's default login banner is small
  enough to carry in the bundle. A scoping question, not a defect: which art, at what size, and
  whether the sign-in page should say the pack is still to come.

- **Docs: CLI + code-map refresh** *(owner-flagged 2026-08-31)* — the command reference and the
  internal code map have fallen well behind the 3.5→3.7 run (bundle v2, the emotions control, the
  contest verbs, the `/v2` REST growth, the React front door). Scope: audit `--help` + the wiki
  command pages against what actually ships, then finish the code map's missing chapters (PixAI
  layer · achievements engine · server routes · React+Loom · sidecars — ranked gaps already listed
  at the map's EOF). Docs-only, no behavior changes.

From the 2026-07-16 persona sweep, tagged "Scope": wanted, but each needs a real definition before
it's actionable. Listed so they aren't lost, not because they're ready.

- **Loom:** takes / per-shot generation history · draft-quality blocking pass · project "Look" block ·
  re-anchor warnings on the reel · music bed under Play · editor handoff export (per-shot trims + CSV/EDL).
- **Curator:** smart collections (saved queries as live collections) · search operators
  (`seed:` `aes:>` `ar:`) · collections manager (rename/merge/delete) · archive-integrity job.
- **Power user:** prompt-matrix queue runs · metadata recovery for hand-made folders.
- **Mobile:** the card placard (accession stamp + sibling strip) — the phone grid is a separate
  component and has none of it yet; and the mobile details sheet's View-batch chip still gates on the
  legacy `batch` column (re-point at `task_id` like desktop did in #30) · Remix and Send to Video on the mobile details sheet — both need their own
  wiring into CreateMobile's composer (the sheet has no dock hand-off; Send to Video is
  already a disclosed stub there, Remix now ships desktop-only the same way).

From the **2026-08-17 persona sweep** (7 archetypes; full ranked brief + rationale in
`../moonglade-internal/PERSONA_SWEEP_2026-08-17.md` §2), the net-new asks not already covered
above, tagged "Scope":

- **Power / workflow:** wildcards / prompt-variable expansion (`{a|b|c}`, `__lists__`) · a saved
  **default negative prompt** · composer-recipe persistence (restore-last + named "Styles" presets) ·
  a quick-pick chip row for recent/favourite models & LoRAs · an in-UI raw-recipe inspector (copy
  JSON / copy-as-CLI). **Spend constraint (from the red-team):** any fan-out submit — matrix,
  wildcard, bulk re-gen — MUST show an aggregate credit + free-card confirm before it fires; never
  spend a batch on the strength of a per-image badge.
- **Curator:** a personal metadata layer (user tags / keeper-reject flags / notes, searchable) · a
  full per-file archive-integrity pass (zero-byte / truncated / missing-thumb + a "last verified"
  stamp, beyond today's missing/orphan tiles) · bulk rate + bulk tag from a selection · keyboard
  rating hotkeys (1–5) · storage breakdown (space by collection / model / type) · a round-trippable
  curation-only sidecar export.
- **Completionist:** quantified Folio progress ("N to go" on every visible ladder/milestone, sorted
  fewest-remaining, each with a jump to the surface that advances it) · a spoiler-safe grand
  completion meter · a "closest to earning" unearned-sort · a pinnable single-goal tracker chip · a
  persistent Vigil day-streak chip · an exportable Honors card (PNG). *(Roster-growth and new-rung
  specifics are internal — `../moonglade-internal/ROADMAP-internal.md`.)*
- **Loom:** cast a collection as an ordered shot-sequence scaffold · manual ordering within a
  collection · a cross-storyboard (series) cast library · find-in-storyboard search · a continuity
  ribbon (each shot's close frame beside the next shot's open frame).
- **Mobile:** pull-to-refresh +
  optional infinite scroll · a single-column full-bleed reading feed · a data-saver mode
  (medium-first, full-res on tap) · proper landscape handling · a "new since last visit" marker +
  jump-to-newest · an opt-in "remember this device" longer LAN session (still authenticated) ·
  QR-connect onboarding (URL only, login gate unchanged).

Small integrity fixes the sweep surfaced (issue-candidates, not features): the mobile Details
"k of N" index counts one loaded page, not the true result total; Contact Sheet Mobile renders
placeholder thumbs where real art exists; and `deleted_remote` (archive-only) pieces aren't badged
and can be swept by a bulk quarantine. Detail in the sweep doc §3. (The sweep's fourth item, Loom
draft-vs-professional marking on rendered shots, was dropped by the owner on 2026-09-07.)

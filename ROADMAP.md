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
  video-Remix fix are in `CHANGELOG.md` under *Unreleased*, per the rule at the top of this file.

---

## Next — scoped, not started

- **Image Details: stamp headline + the wide-image layout** ([#31](https://github.com/Nelnamara/moonglade-athenaeum/issues/31)) *(owner-reported live, 2026-08-22)*
  The other half of the placard design: the "Placard identity" artifact designs the **Details view's
  placard** ("placard" is this view's own class name) as one identity with the grid card; #30 built
  the card half and this half was missed. The Details headline still leads with the word-salad
  **filename** for every untitled image — apply direction A (a typed title only, else the accession
  stamp; never a machine name) and E's sibling strip in the record. And a **wide** image (ratio > 1.6)
  clips off the top of the viewport while the record paints over its lower half: `.placard-wide`
  stacks the columns but never sizes the rows, so the art and the record auto-split into two equal
  rows the image can't fit. Measured live; a two-line CSS fix (`grid-template-rows: auto minmax(0,1fr)`,
  frame `align-self: start`). Small, real, no design gate.

- **Does a tablet tier exist?** *(tabled — owner wants to play in the app on the iPad first, 2026-08-23)*
  Today one hook (`MOBILE_QUERY` 430px + a coarse-pointer fallback that also requires width ≤ 430)
  routes every tablet to the DESKTOP build in both orientations. Three coherent answers: raise the
  breakpoint so tablets get the mobile build (one number, least work, most side effects on a
  desktop-shaped surface); add a real third tier; or keep the split and port touch affordances
  (always-visible card controls on coarse pointers, 44px targets) into the desktop components.
  The input for the call: `../moonglade-internal/QA_tablet-2026-08-23.md` — a targeted poke list
  built from the refit review's findings; which sections bite decides which answer.

- **Per-batch / per-task grid stacking** *(standalone — kept, owner 2026-08-19)*
  Collapse the gallery wall so a multi-image generation (a batch of, say, 4) shows as **one
  stack/card** instead of N flat tiles — de-cluttering the grid for batch gens. Kept as its own
  item after the layout follow-ons (including Group-by, which would have generalized it) were cut.
  Design-first (user-visible surface); the stack render + expand-to-see-the-batch interaction are the build.

- **Gallery layout switcher — mobile pass only (maybe)** *(desktop base shipped 2026-08-19)*
  The desktop switcher (**Masonry / Grid / Timeline**) shipped and moved to `CHANGELOG.md`; the owner
  has minor visual fixes queued on top. The persona-sweep follow-on layouts (Group-by, Justified,
  Filmstrip, density/proof, data-table) are **CUT** — not worth the payoff (owner, 2026-08-19). What
  *may* remain is a **mobile** switcher (column density + per-device memory), but the owner is
  skeptical these layouts are even viable on a phone — so this is a maybe pending a look, not a
  committed build.

- **Loom per-project spend ledger (historical)**
  The live *cost-to-finish* roll-up shipped; what's missing is a per-Loom-project record of what a
  project has *already* spent. Only the global account credit ledger tracks historical spend today.
  Low priority, but needs scoping before build.

- **Marks render too small, everywhere they appear** *(scope + workshop the right size — owner, 2026-08-19)*
  A recurring, real sizing defect ("song as old as time"), long deprioritised as cosmetic. The header
  is the worst example. Owner call: **workshop it and settle the right size**, then apply everywhere
  marks appear — don't spot-fix one surface. **Same workshop, added 2026-08-22:** the mark
  *animations* — the 16 picks in the Branding tab save but nothing applies them since the 3.0 header,
  and the header draws an accent tile + "M" behind alpha marks ([#24](https://github.com/Nelnamara/moonglade-athenaeum/issues/24)).
  Owner: "many if not all look janky now — workshop fixes or new ones", so this is a design pass
  (which animations survive, which are new, what the mark sits on), not a port of the classic CSS.

- **Login page: render the Banner — login slot, restore the welcome hold** ([#25](https://github.com/Nelnamara/moonglade-athenaeum/issues/25))
  The Branding tab sells three banner slots; since the 3.0 React login nothing draws the login one
  (the card shows the header mark instead), and the designed welcome hold was removed for a test
  expectation, so the login mascot barely plays. The hold is a small fix; the banner needs a design
  call first (`Login.dc.html` has no banner element). Separate from the bundle-v2 merge.

- **Let LAN clients trigger the asset-pack download** ([adversarial review, 2026-08-22]) *(fast-follow, own branch)*
  The default-art pack (`moonglade.dat`) auto-downloads on the **server** machine's first launch after an
  update (the Setup Wizard checks `/api/assets/status` and starts the fetch itself). But `/api/assets/fetch`
  is **localhost-only**, so a LAN device that opens the app *before* the server ever did can't kick off the
  download — it has to be done from the server. Owner: it's a vital package function; allow LAN clients to
  trigger it. Low-risk (the route pulls one fixed, sha-verified, pinned Release asset to one known path,
  single-flight), but it's a **security-tier change** (`api_assets_fetch` LOCALHOST → LOGIN) so it gets its
  own tiny branch + sanity check: `tests/test_route_tiers.py:113`, the route's `_is_local_request` guard, the
  wizard calling it on a non-local device, and a confirm that repeat 685 MB fetches can't be weaponised
  (single-flight already blocks concurrency). Not bolted onto the bundle-v2 merge.

- **Claimable-reward notice in the activity tracker + gift icon on promo cards** *(the icon half of
  [#26](https://github.com/Nelnamara/moonglade-athenaeum/issues/26) shipped 2026-08-22; this is the
  remaining design step)* — a notice when credits become claimable, and the gift icon on future promo gifts.

- **Real generation progress — build the honest "starts in ~N" from the wait estimate** *(owner call, 2026-08-19)*
  PixAI does **not** expose true render progress. It once showed the image taking shape (a blurred
  wireframe resolving into focus), but that's gone; today it gives only a **start time + an estimated
  wait**. Our own honest treatment (mascot + indeterminate shimmer, no fabricated %) already ships.
  The build: surface a clearly-labelled "**about N minutes before this starts**" from that start-time
  + estimated-wait — a QUEUE wait, never dressed as a render ETA. **Probe (2026-08-16):** the site calls `/v2/task/wait-time` on the
  generate surface — that is a **queue-wait** figure, i.e. exactly the thing the constraint above
  says must never be dressed as render progress. It may still be worth showing *as what it is*
  ("about N minutes before this starts"). The dock's running tiles ship the honest treatment in the
  meantime: mascot + indeterminate shimmer, no percentage.

- **Contest workbench (beyond Shortlist)**
  The "☆ Shortlist" staging step shipped. The larger workbench — deadline tracking, submission
  management — is still just wanted, not scoped.

- **Bonjour / mDNS advertising: the server announces itself on the LAN** *(greenlit to scope + prep — owner, 2026-08-19)*
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
- **Give the asset pack a real file type.** In Explorer `moonglade.dat` shows a blank Type column and
  a generic icon (owner nitpick, 2026-08-22). `.dat` is too generic to claim system-wide, so the clean
  fix is an app-specific extension (`.mgpack` or similar) plus a ProgID the app registers for the
  current user on first run / from the launcher-shortcut path (friendly name "Moonglade asset pack",
  the app icon) — the same per-user registry spot the Desktop-shortcut code already writes. Touches the
  manifest/downloader file name, `_container_path()`, the builder's default `--out`, and the Release
  asset name, so it rides a pack rebuild, not a point release. Cosmetic; low priority.
- **Real unlock SFX.** The loader ships and falls back to a synth chime; the actual sound assets are
  still to be sourced/added.
- **Animated achievement-toast badges (exploring).** The mascot already takes an animated
  `<id>.webp` (drop it beside the stills and it moves); the badge does not -- the toast loads a
  static `/badge-thumb/<id>.png` and the server PIL-thumbnails masters to PNG, so an animated master
  would flatten to one frame. Owner is playing with animating the medallions for fun (the ornate-frame
  direction for the Legendary/feat tiers was dropped). To wire it: a webp-first client chain like the
  mascot's, plus a badge-serve path that passes an animated webp through (bypass the PNG thumbnail for
  webp -- serve the webp master or an animated thumb). For funsies; low priority.
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
- **Mobile:** the card placard (accession stamp + sibling strip) — the phone grid is a separate
  component and has none of it yet; and the mobile details sheet's View-batch chip still gates on the
  legacy `batch` column (re-point at `task_id` like desktop did in #30) · Remix and Send to Video on the mobile details sheet — both need their own
  wiring into CreateMobile's composer (the sheet has no dock hand-off; Send to Video is
  already a disclosed stub there, Remix now ships desktop-only the same way).

From the **2026-08-17 persona sweep** (7 archetypes; full ranked brief + rationale in
`../moonglade-internal/PERSONA_SWEEP_2026-08-17.md` §2), the net-new asks not already covered
above, tagged "Scope":

- **Power / workflow:** a keyboard + `Ctrl/Cmd-K` command-palette layer with a one-click "↻ Again —
  new seed" re-roll · wildcards / prompt-variable expansion (`{a|b|c}`, `__lists__`) · a saved
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
- **Mobile:** the layout switcher on phone (column density + per-device memory) · pull-to-refresh +
  optional infinite scroll · a single-column full-bleed reading feed · a data-saver mode
  (medium-first, full-res on tap) · proper landscape handling · a "new since last visit" marker +
  jump-to-newest · an opt-in "remember this device" longer LAN session (still authenticated) ·
  QR-connect onboarding (URL only, login gate unchanged).

Small integrity fixes the sweep surfaced (issue-candidates, not features): the mobile Details
"k of N" index counts one loaded page, not the true result total; Contact Sheet Mobile renders
placeholder thumbs where real art exists; `deleted_remote` (archive-only) pieces aren't badged and
can be swept by a bulk quarantine; Loom Draft-vs-professional quality isn't marked on rendered
shots. Detail in the sweep doc §3.

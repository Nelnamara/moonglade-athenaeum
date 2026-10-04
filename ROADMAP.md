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

- Nothing in flight. What shipped is in `CHANGELOG.md` (latest: 3.17.0 — Mail Call,
  2026-10-04), per the rule at the top of this file.

---

## In review — built, not merged

Every branch that is built but not on `master` is listed here with its review sheet, so work in
flight is never invisible. On 2026-09-06 six built branches existed that nothing named, which is
why this section exists.

- Nothing in review.

## Next — scoped, not started

- **Tsubaki.3 feature controls.** *(2026-09-26)* What is left of PixAI's Tsubaki.3 release: style
  keys and custom styles, which the app cannot express yet. Needs a design session first.

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
  Owner, 2026-10-02 (iPad, last played before 3.11): content cut off in the Lightbox and Details, and
  overlapping buttons in the main gallery
  ([#72](https://github.com/Nelnamara/moonglade-athenaeum/issues/72)); the mobile-surface audit walks
  iPad sizes too. Today one hook (`MOBILE_QUERY` 520px + a coarse-pointer fallback for a phone-width screen held in portrait)
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


---

- **Full surface audit — Phases B and C** *(kept on the books — owner, 2026-09-04)*
  Phase A (the owner's walk, 2026-08-29) is done and fed #42–#51 and the S4 batch. What has never run:
  **Phase B**, a per-surface comp-diff of all 24 surfaces against their design mockups (one agent
  fan-out each), and **Phase C**, triage + re-verify of B's findings. Scope and severity scale:
  `../moonglade-internal/scopes/SCOPE_2026-08-26_surface-audit.md`. Not dropped; run when scheduled.

## Design-pass reworks — rescope, don't just build

- None right now.

## Scoped-but-unbuilt — decided once, never executed

- **Install-folder tidy.** "A tidy install folder says a lot." Half done: the art pack and its
  coded tree replaced the old loose `branding/` folder, which no longer exists. Before anything is
  scoped, re-audit what still sits loose at the install root today (owner, 2026-10-02: "old topic and
  half done now").
- **Dead-code sweep.** With the React rebuild done, sweep for orphaned code the classic cut
  left behind (what else is dead?). `--faststart-videos` is live and stays (it rewrites a video so it
  starts playing before it has fully downloaded). `--delete-task`, deprecated since 2026-09-06 in favour
  of the gallery's Delete, is removed in the next minor release. **Partly
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
  and what "grown to this level" changes about the threat picture. **Go (owner, 2026-10-02): after
  Wave 1, as a read-only audit that ends in a ranked list.** Most state-changing routes skip the
  explicit CSRF token today; Wave 1 fixes three and the review ranks the rest. Ruled already: a
  signed-in device on the LAN keeps spending and deleting with no extra step (owner: keep), and
  Log Out signs out only the device it was pressed on
  ([#70](https://github.com/Nelnamara/moonglade-athenaeum/issues/70)).

---

## Later — directional / banked

- **Epic A — The Foundry (image → 3D print).** Gated on an explicit go, resin-first, its own optional
  install, never bundled. Stage 1 is a go/no-go spike (one image → mesh → printable). Low priority.
- **Epic B — Provider Deck.** A provider seam so a second generation backend can plug in. Per
  NORTH_STAR (locked 2026-08-25) the seam comes *before* the second provider — it is how the core
  proves itself provider-agnostic — and it follows the Loom-unify decision in that sequence. Low
  priority until that decision is taken.
- **UPnP / SSDP (or WS-Discovery) LAN presence — show up in Windows Explorer's "Network".**
  *(owner, 2026-10-02: scope it; macOS is covered by Bonjour)*
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
  asset name, so it rides a pack rebuild, not a point release. Cosmetic; low priority. Owner,
  2026-10-02: yes to the extension and to the per-user registry entry, in pack v7.
- **Real unlock SFX.** The loader ships and falls back to a synth chime; the actual sound assets are
  still to be sourced/added. Sources scouted in July (recovered 2026-10-02 from the deleted STATE
  notes): Kenney, the Sonniss GDC bundles, freesound and OpenGameArt (free/CC0 libraries), or Stable
  Audio Open run locally through Pinokio to generate them; the owner has one or two WoW sounds of
  his own.
- **Loom preview / placement follow-ups.** A handful of small Loom tweaks on a surface the owner
  already likes. Low priority, deliberately unscoped — owner to walk it. The items on record are
  listed as an agenda in the Loom-in-the-gallery workshop prep (2026-10-02).
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

- **Remake the AI Tools thumbnails.** *(owner plan, 2026-09-08)* The Enhance preset thumbnails
  shipped; the owner intends to redo the AI Tools thumbnails himself. Nothing to build until the
  art lands.

---

## Backlog — needs scoping

- **Docs: code-map follow-ups** *(owner-flagged 2026-08-31)* — what is left of the docs refresh once
  `--help` and the wiki command pages match what ships and the internal code map has all its
  chapters. A presence-gated test that diffs the map's flag set and stated defaults against
  argparse (skipping when the private repo is absent), so the map cannot drift unseen; a generator
  script so a refresh is a re-run; the two original chapters' line numbers replaced with symbol
  names (after the module split lands); and the gaps listed at the map's end (a first-commands
  on-ramp, argparse's own vocabulary, a flag-to-column table, the `--sync` stage-to-column table).
  Docs-only, no behavior changes.

From the **2026-08-17 persona sweep** (7 archetypes; full ranked brief + rationale in
`../moonglade-internal/PERSONA_SWEEP_2026-08-17.md` §2), the net-new asks not already covered
above, tagged "Scope":

- **Curator:** an in-app screen for importing a curation backup (the export, and the command-line
  import, are built in Wave 1; a screen needs a design step).
- **Mobile:** an opt-in "remember this device" longer LAN session (still authenticated). Designed
  (design Session V) and held for the app security review below.

(The sweep's Loom draft-vs-professional marking on rendered shots was dropped by the owner on
2026-09-07.)

- **The achievements' stats cache can miss an edit.** The memo that feeds the honors is keyed on the
  catalog's row count and newest picture, so rating, tagging or publishing an existing picture may not
  move the matching counts until a new picture arrives (found by the 2026-10-02 code-map pass). Design
  work, not a defect: decide what invalidates the memo.

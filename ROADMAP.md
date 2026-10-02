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

- Nothing in flight. What shipped is in `CHANGELOG.md` (latest: 3.15.0 — The Reading Room,
  2026-10-01), per the rule at the top of this file.

---

## In review — built, not merged

Every branch that is built but not on `master` is listed here with its review sheet, so work in
flight is never invisible. On 2026-09-06 six built branches existed that nothing named, which is
why this section exists.

- Nothing in review.

## Next — scoped, not started

- **Tsubaki.3 feature controls.** *(2026-09-26)* What is left of PixAI's Tsubaki.3 release: style
  keys and custom styles, which the app cannot express yet. Needs a design session first.

- **Edit Pro V2.0 in the Edit card.** *(2026-10-02 probe)* PixAI's new Edit Pro version takes up
  to 10 reference images at v1.0's price. The Edit card still sends v1.0 with a 4-image cap from
  two hand-kept tables. Add a V2.0 row beside v1.0, which stays because the AI Tools scenes still
  run on it. A data change plus a test:
  [#67](https://github.com/Nelnamara/moonglade-athenaeum/issues/67).

- **Free cards: say when they expire, and open PixAI's current event.** *(owner, 2026-10-02)*
  Event cards have been expiring unused. Add a plain warning before held cards run out, and a
  link to whatever event PixAI is running, read from its public home-banner list. No per-event
  check-in: PixAI has no read-only check-in status, and each event's routes differ. The
  placement needs a short design session first:
  [#69](https://github.com/Nelnamara/moonglade-athenaeum/issues/69). Related: expired cards read
  as "consumed" on the Account screen,
  [#68](https://github.com/Nelnamara/moonglade-athenaeum/issues/68).

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

- **Retire the `/next` name from the app's data routes and asset paths.** *(owner, 2026-09-29)*
  The React app shipped under the `/next` pilot codename. #51 (2026-09-04) removed the page route and
  deliberately left two prefixes: the `/api/next/*` JSON routes the app reads (library, details, history)
  and the `/next/assets/` static prefix baked into the build, the page templates and the installed-app
  manifest. Rename the API routes to plain names (`/api/library`, `/api/detail/<id>`, `/api/history`) on
  one shared handler with the old paths kept as aliases for a release, send every client call through one
  constants module (the call sites are scattered today), and leave payloads untouched. The assets prefix is
  decided separately and never simply dropped: installed phone apps read their icons from it. Built after
  the open work is merged and walked, not alongside it (the details route keeps gaining fields). Scope,
  measured blast radius, phases, tests and risks:
  `../moonglade-internal/scopes/SCOPE_2026-09-29_retire-the-next-namespace.md`.

## Design-pass reworks — rescope, don't just build

- **PixAI inbox and comment replies.** Being told about everything PixAI's inbox carries for his
  works (all kinds: comments, likes, follows; owner, 2026-10-02), and replying to comments. Liking,
  bookmarking and following are not actions the app takes (owner, 2026-09-07). The promo gift folds
  in, with a gift-box button by the credits chip, which issue #26 always intended. A probe (running
  2026-10-02), then design Session R, then the build; a reply is the first write to PixAI other than
  generate and delete.

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

- **Model bookmarks → PixAI's collections.** *(deferred, 2026-08-17)* PixAI turned bookmarks into
  named public/private collections. The model picker's Bookmarked tab still works on the older
  call, so nothing is broken; a check in the build warns when that call leaves PixAI's site.
  Adopting collections needs one read-only capture of their shapes and a design step for the
  picker's source tabs.

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
  2026-10-02: yes to the extension, in pack v7; the per-user registry entry is his call.
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

- **Docs: CLI + code-map refresh** *(owner-flagged 2026-08-31)* — the command reference and the
  internal code map have fallen well behind the 3.5→3.7 run (bundle v2, the emotions control, the
  contest verbs, the `/v2` REST growth, the React front door). Scope: audit `--help` + the wiki
  command pages against what actually ships, then finish the code map's missing chapters (PixAI
  layer · achievements engine · server routes · React+Loom · sidecars — ranked gaps already listed
  at the map's EOF). Docs-only, no behavior changes.

From the 2026-07-16 persona sweep, tagged "Scope": wanted, but each needs a real definition before
it's actionable. Listed so they aren't lost, not because they're ready.

- **Curator:** archive-integrity job.
- **Mobile:** the mobile details sheet's View-batch chip still gates on the legacy `batch` column
  (re-point at `task_id` like desktop did in #30).

From the **2026-08-17 persona sweep** (7 archetypes; full ranked brief + rationale in
`../moonglade-internal/PERSONA_SWEEP_2026-08-17.md` §2), the net-new asks not already covered
above, tagged "Scope":

- **Curator:** a full per-file archive-integrity pass (zero-byte / truncated / missing-thumb + a
  "last verified" stamp, beyond today's missing/orphan tiles) · a round-trippable curation-only
  sidecar export.
- **Mobile:** optional infinite scroll, after the phone gallery itself is fixed
  ([#73](https://github.com/Nelnamara/moonglade-athenaeum/issues/73)) · an opt-in "remember this device" longer LAN session (still
  authenticated) · QR-connect onboarding (URL only, login gate unchanged).

Small integrity fixes the sweep surfaced are filed as Issues: the phone record's "k of N" ([#64](https://github.com/Nelnamara/moonglade-athenaeum/issues/64)),
the phone's View batch chip ([#65](https://github.com/Nelnamara/moonglade-athenaeum/issues/65)) and archive-only pieces
([#66](https://github.com/Nelnamara/moonglade-athenaeum/issues/66)). The phone Contact Sheet shows real thumbnails
instead of grey squares (owner, 2026-10-02: the 2026-08-03 placeholder call was a misreading); it rides
Wave 1's phone lane. (The sweep's fourth item, Loom draft-vs-professional
marking on rendered shots, was dropped by the owner on 2026-09-07.)

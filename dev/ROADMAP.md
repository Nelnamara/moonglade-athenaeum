# Roadmap

Planned and outstanding work for Moonglade Athenaeum. **One home per fact:**

- **Shipped** → `CHANGELOG.md` (dated taglines). Nothing here once it ships — it *moves*.
- **Why a decision was made** → the internal decisions ledger (private companion repo).
- **Bugs** → GitHub Issues.
- **Planned work** → this file. (A small set of internal design items lives in the private
  companion repo's roadmap instead; this file is the default home for everything else.)

Sections follow what each item waits on: **Now**, **In review**, **Next** (ready to build, nothing
waiting), **Needs a call** (an owner decision), **Waiting on design**, **Waiting on art**, **Waiting
on something outside** (another piece of work, a date, PixAI, a device), and **Later** (parked or
banked). Each item says what it is, why, and what it touches. When an item ships, delete it here and
add a CHANGELOG line — never annotate "done" in place. Reconciled against the code, git, the
CHANGELOG and the open issues on 2026-10-08.

---

## Now — active

- Nothing in flight. What shipped is in `CHANGELOG.md` (latest: 3.20.1 — Clean Sweep,
  2026-10-08), per the rule at the top of this file.

---

## In review — built, not merged

Every branch that is built but not on `master` is listed here with its review sheet, so work in
flight is never invisible. On 2026-09-06 six built branches existed that nothing named, which is
why this section exists.

- Nothing in review.

---

## Next — ready to build, nothing waiting

In the recommended order.

- **The 3.20 follow-ups ([#79](https://github.com/Nelnamara/moonglade-athenaeum/issues/79)).** The
  release gate's edge cases for the move: none blocked 3.20, all are worth closing. Take first the
  ones next to data loss (an old file winning on a copied timestamp, a pack removed without a
  comparison, two `runs.db` copies not merged, a banner parked and then deleted), then the slow first
  move on a large Loom folder, then the wording and setup edges. Touches `moonglade/migrate.py`,
  `moonglade/outside.py`, `moonglade/setup.py`.

- **Split the two megamodules, phases 0-3 (`moonglade/backup.py` / `moonglade/gallery.py`).** The
  last open part of Wave 4 (owner, 2026-10-04), planned as 3.21.0. They are the repo's two largest,
  most-churned modules and its top regression risk. Phase 0 maps the seams in a test and retargets the
  test patches; phases 1-3 move whole sections verbatim into their own modules (library scan,
  duplicates, organize and series; health, account state, the job log, training, the PixAI client,
  the updater; the mirror, media tools, achievements), with no internal re-exports and a full test
  gate per phase. `create_app`'s route families and the spend path are NOT in this split (see Later).

- **App security review.** A read-only audit that ends in a ranked list: the threat model, login and
  the no-accounts mode, session cookie handling, the localhost and LAN trust model, request
  integrity (the CSRF debt the 3.16.0 coverage guard lists, headers, CSP), file and input handling,
  credentials at rest. Owner's go of 2026-10-02 ("after Wave 1"); Wave 1 shipped in 3.16.0. Already
  ruled: a signed-in LAN device keeps spending and deleting with no extra step. Its rulings unblock
  remember-this-device and the QR change below.

- **Convert the rest of the tests that read code as text.** *(test review, 2026-10-05)* Many Loom
  and gallery tests look for words in a component's source instead of running it, so a small change
  means editing many tests that prove little, and some hide real money-safety checks. The setup to
  draw a component in a node test (`loom/test-support/render.mjs`) shipped with the first converted
  files; the per-test inventory (render / logic / keep / delete-covered, with the money-safety guards
  flagged) is in the private repo's `scopes/test-audit/render_2026-10-08/`. Convert file by file, each
  conversion checked by mutating the code it guards, as the first ones were. Rides along: the Loom's
  multi-hour give-up tiers tested against an injected clock, and a drawn check of the Enhance
  drawer's layout. The tests that cover only older-version fallbacks retire with those fallbacks (see
  the expiry rule under Needs a call).

- **Finish the approved 2026-10-05 cleanup.** Two pieces the 3.20.1 pass missed: the
  `--credit-log-reason` flag and the credit log's `?reason=` parameter are accepted and never sent
  (PixAI's read takes no filter), and `wiki/Backing-Up.md` still promises the filter, so the flag, its
  help and the wiki row go; and the phone app repeats its own background-read check inline instead of
  calling the tested helper in `phoneCore.js`. Small.

- **Trash: say how many files are the only copy.** The bulk delete has shown the archive-only count
  since 3.16.0; **Delete forever** and **Empty trash** don't yet. Read each trashed file's saved row and
  name the count in their typed confirms. Small.

- **Honor counts after an edit.** The memo behind the achievements' counts is keyed on the catalog's
  row count and newest picture, so rating, tagging or publishing an existing picture may not move a
  count until a new picture arrives (found by the 2026-10-02 code-map pass). The writers that change a
  counted field drop the memo, with a test that a rating moves its count. Small.

- **Unlock sounds: the loader, before the files arrive.** Fall back to the synth chime only on a real
  failure (unsupported or missing), not on the browser's autoplay refusal; serve `.ogg` as
  `audio/ogg`; tests for the sound route and the loader. Small; the sound files themselves wait on art.

- **Small tidy-ups.** Four telemetry counters are written and never read (trash restored, purged
  forever, duplicates resolved, duplicates undone): delete them or say why they stay. The Loom's
  Import-collection dialog uses its own three catalog fetches instead of the shared picker helper.
  The goal tiles' unused glyph data goes (owner-approved 2026-10-05). Small each.

- **Claude tools: library analytics.** A read-only tool over the catalog: top models and LoRAs, prompt
  keywords, cadence by day and month, credit spend over time, with a test. From the 2026-09-09
  Claude-tools scope. Medium.

- **Code map and CLI docs.** A generator for the CLI chapter from argparse, a test that diffs the
  map's flags and defaults against argparse (skipping when the private repo is absent), symbol names
  instead of line numbers in the two original chapters, and the gaps listed at the map's end (a
  first-commands on-ramp, argparse's own vocabulary, a flag-to-column table, the `--sync`
  stage-to-column table). Docs only.

---

## Needs a call — waiting on the owner

Each is a decision only the owner can make; most carry a recommendation.

- **The Loom inside the gallery — is a modal on one surface viable, and what would it take?**
  *(owner's scoping order, 2026-09-06)* The standing question "does the Loom become part of the same
  app?" is **not answered**. The workshop-prep document is written (private
  `scopes/WORKSHOP_PREP_2026-10-02_loom-in-the-gallery.md`): it walks each seam in three columns (what
  the design pages say, what the code does, what is undecided) against the two-build fact (the
  gallery is `gallery/dist/app.js`, the Loom is `loom/dist/master-storyboard.bundle.js`, React loaded
  two incompatible ways) and recommends a one-to-two-day spike first. **Next step: the workshop the
  owner drives.** Its answer gates the arena crossing's visible half (designed 2026-09-06, parked),
  the "one build" move, the Loom preview follow-ups and Epic B.

- **The full mobile-surface audit against the designs.** *(owner, 2026-09-05)* About 85 phone and
  iPad-size screens checked against their design sources in batches on seeded data, then one pass on
  the real library. Its own scope says "run on the owner's go", and it is the input for #72 and #73.
  Needs the go.

- **The sign-in welcome hold under reduced motion.** Today the welcome holds about 5.6 s even with
  animations off. Keep it, shorten it, or skip it for reduced-motion users (a timing change on a
  designed surface).

- **QR connect without the security review.** Show the QR whenever a LAN address exists (not only
  while broadcasting), with the address as text under it and a short wiki paragraph. No credential
  and no new control are involved, so the scope recommends lifting the review's hold for this part
  alone.

- **An expiry rule for upgrade fallbacks.** Code that reads older versions' files (and the 3.20 move's
  migrations, which must outlive 3.21 because an install can skip 3.20) needs a removal rule: N
  releases after it lands, or tied to the oldest version still allowed to update straight to current.

- **Change Emotion's unknown key.** An expression key the app doesn't know is sent as the raw prompt
  of a paid run. Recommended: refuse it before the spend, with a test.

- **Upscaling a Tsubaki picture.** Whether a DiT source upscales on PixAI's fixed upscale version or
  keeps its own (PixAI's site offers no Hires on DiT pictures).

- **Publish: "Browse from disk".** Publishing a picture straight from disk needs one test call on the
  owner's account (disclosed first) and his answer on whether such a picture joins the catalog.

- **Claude tools that delete.** Should an agent ever delete a picture? The scope's lean is no: deleting
  stays in the gallery's two-step flow.

- **Smaller design calls.** The marks' default animation speed (1.0, or the 0.80 the owner exported);
  the design drift report's two open items (whether 500 per page is wanted; whether "tap only" should
  allow the Lightbox swipe); the MODE & CHANNEL label on one Design Handoff page (fix the page or
  record the shipped label as a deviation); the design kit's handoff map (rebuild or retire); whether
  the search bar's banked left Filters drawer, and the layout note-taking pass that gated it, still
  stand after the September redesigns.

- **Ideas never adopted, recommended to drop.** From the 2026-08-17 AI persona sweep, never asked for
  by the owner: a chrome-free proof mode, a filmstrip review layout, a compare view, a sortable data
  table, aspect-locked cinema cells, a landmark layout, two search operators (`has:no-metadata`,
  `credit:`), a recipe JSONL export beside the CSV, and bulk re-generate from a selection. One answer
  covers them all. Also recommended to decline: replaying a stale split after a two-tab conflict
  (option B of #59; option A shipped in 3.16.0), editing the Loom's Look from the phone, and the
  advanced-training capture (about 1,500 credits).

- **Housekeeping on the owner's say.** The old worktree folders and the leftover remote branches; the
  `D:\moonglade-dev` test libraries; a loose art file in this PC's coded art tree that makes the
  Mirror read mascots from disk. Nothing of his is deleted without the word.

---

## Waiting on design

A visible change gets a design or workshop step first.

- **An in-app screen for importing a curation backup.** The export and the command-line import
  (dry run, apply, undo) shipped in 3.16.0; a screen to upload, preview with the unmatched list,
  apply and undo needs a Design Handoff.
- **Hero layout shapes.** The shapes workshop the owner asked for on 2026-08-17 (latest drop, cover
  plus strip, champion plinth) was never held.
- **Shareable view links.** Layout, sort, filters and search kept in the address, with a Copy view
  link button; decide which state goes in and how it meets saved views.
- **Training runs in the Activity panel.** The strip's component and hook exist (Session J); its
  place in the panel and what View does were never drawn.
- **Repaint (inpaint, outpaint, SDEdit).** After a read-only look at PixAI's own Repaint page: a
  Design Handoff for the mask canvas, redraw vs extend, strength and the presets; spend-path review
  before any submit.
- **PixAI's kiss and hug tools.** A two-image stitch the site does in the browser; no owner ask on
  record, a parity gap. Design first, or drop.

---

## Waiting on art

- **The unlock sounds.** Five short Ogg files (one per tier, or one motif pitched per tier) with a
  licence recorded in the art notes; sources scouted in July (Kenney, the Sonniss GDC bundles,
  freesound, OpenGameArt, Stable Audio Open run locally through Pinokio, or the owner's own). The
  loader fixes are in Next.
- **The AI Tools thumbnails.** The owner redoes them himself; they ride the next pack rebuild.
- **The system art flagged "needs work".** Six roles still to redraw: the narrator, the Setup Wizard
  poses, the Claim pill icon, the drop-in logo, the favicon and the PWA icons. (The Branding roles
  section lets the owner swap four roles himself; it doesn't redraw them.)
- **The Loom's banner.** A Moonglade-mark strip for the 12:1 banner slot; a fresh install shows the
  gradient.

---

## Waiting on something outside

- **Remember this device** (opt-in longer LAN session, designed as Session V): waits on the security
  review's rulings (lifetime, whether a remembered device may spend). The "Log Out signs out only this
  device" half shipped in 3.16.0.
- **The phone and iPad layouts ([#73](https://github.com/Nelnamara/moonglade-athenaeum/issues/73),
  [#72](https://github.com/Nelnamara/moonglade-athenaeum/issues/72))** wait on the mobile-surface
  audit's defect list; **Chrome on iPhone after a turn
  ([#75](https://github.com/Nelnamara/moonglade-athenaeum/issues/75))** needs a measurement on the
  device itself.
- **Windows Explorer's Network folder** *(scoped 2026-10-02)*. Moonglade shows up for phones through
  Bonjour, but Explorer's Network folder lists UPnP/SSDP and WS-Discovery devices, not mDNS. A
  half-day spike needs the owner at a second Windows PC; drop it if Explorer won't list it. Then a
  switch beside Bonjour (off by default, after a design step) and a wiki page. Cosmetic, not
  reachability.
- **Unlimited Mode ends 2026-10-25.** After that date, check that the switch goes away and a stale
  lane request is refused. (Extending Unlimited Mode to the Loom, the command line or a history
  marker is only worth it if the entitlement is renewed.)
- **Video v4.0.3** joins the model list once PixAI offers it (the monthly probe watches).
- **First real use, nothing to build:** claiming a real PixAI gift, the first real publish with a
  contest picked, and the first real Edit Pro V2.0 edit each confirm a path that was built against
  PixAI's documented shape but never exercised for real.
- **Advanced training's parameters** stay at PixAI's defaults until PixAI unlocks them.

---

## Later — parked or banked

- **Epic A — The Foundry (image → 3D print).** Gated on an explicit go, resin-first, its own optional
  install, never bundled. Stage 1 is a go/no-go spike (one image → mesh → printable).
- **Epic B — Provider Deck.** A provider seam so a second generation backend can plug in. Per
  NORTH_STAR (locked 2026-08-25) the seam comes *before* the second provider and follows the
  Loom-in-the-gallery decision. After the seam: a provider chooser on the backup and generate
  surfaces (design first), and the dial-in series' optional local-VLM naming (rerolls only), the last
  remnant of [#34](https://github.com/Nelnamara/moonglade-athenaeum/issues/34).
- **The Loom's structure, after the Loom-in-the-gallery answer.** Moving the Loom onto the gallery's
  build ("one build, two entries", deleting the two React bridges), and splitting
  `loom/master-storyboard.jsx` into smaller files. Spend-path code, each its own reviewed effort.
- **Loom preview / placement follow-ups.** A handful of small Loom tweaks on a surface the owner
  already likes, deliberately unscoped: the owner walks it. The items on record are the appendix
  agenda of the Loom workshop prep.
- **Split phases 4-5.** `create_app`'s route families, then the spend path (the generation road,
  cards and price, models, deleting one image), after phases 0-3; each its own design and adversarial
  review. Then revisit where `gallery/`, `loom/`, `wiki/` and `static/` live.
- **Does a tablet tier exist?** *(tabled until the owner plays on the iPad)* Today one hook
  (`MOBILE_QUERY` 520px plus a coarse-pointer fallback) routes every tablet to the desktop build.
  Three answers: raise the breakpoint, add a real third tier, or keep the split and port touch
  affordances into the desktop components. Input: the private `QA_tablet-2026-08-23.md` poke list and
  the #72 audit.
- **A warning-free `.local` certificate and an iPad home-screen app.** A certificate carrying the
  `.local` name, and the HTTPS path for an installed iPad app. Deferred 2026-08-25; overlaps the
  security review.
- **Parked gallery layouts.** Group-by sections and Justified rows (owner, 2026-09-04: overkill for
  now); a phone 1/2/3-across picker.
- **A background-sync progress chip** in the gallery header for a first sync after the wizard (the
  Activity window covers it meanwhile; a new element, so design first).
- **An always-on library** that runs the schedule while the app is closed (an opt-in Task Scheduler
  entry or service). A user can schedule the command line by hand today.
- **The Edit card's caps read live from PixAI** instead of two hand-kept tables (a parity test keeps
  them in step today).
- **Contest extras.** Follow and unfollow, hosting, voting, a paged entries view.
- **Claude tools that spend.** Generate (preview, then confirm) and claim rewards: each needs the
  owner's go, a design document and an adversarial review before any code.
- **A Windows installer and standalone desktop app** (PyInstaller plus Velopack), if ever pulled.
- **The full surface audit, Phases B and C.** A per-surface check of the main surfaces against their
  Design Handoffs, then triage and re-verify. The surface list predates the 3.15.0 rebuild and needs a
  refresh first. Kept on the books (owner, 2026-09-04); runs on his go.
- **Branding roles held back from the 3.17.0 cut.** The Claim popup, the drop-in logo, the favicon
  and the PWA icons; not requested.
- **Optional test-speed leftovers.** The full run met its under-10-minute target in 3.20.1. Left
  unbuilt and optional: one shared app for the read-only tests, fixed sleeps turned into waits on the
  real condition, and why desktop-size browser tests take longer than phone-size ones.

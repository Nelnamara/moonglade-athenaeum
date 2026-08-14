# Decisions

**What this file is.** The reasoning behind Moonglade Athenaeum — decisions, rejected
approaches, standing rules, settled constraints, and which artifact is the pixel source for
which surface. Rescued from `docs/STATE.md` before it was cut down, because this is the part
that **cannot be recovered by reading the code**.

**What this file deliberately is NOT.** It holds no state. Nothing here says what is shipped,
open, in flight, or next; no test counts, versions, branch names or release status; no
`file.py:123` citations. All of that is derivable, all of it rots, and a stale claim in a
trusted document is worse than no document — `STATE.md` reached 2,231 lines carrying 30
already-shipped items and 24 outright false claims, including a first paragraph naming a branch
that had been deleted weeks earlier.

**Where the other things live.** What shipped → `CHANGELOG.md`. Planned/outstanding work →
`ROADMAP.md`. Bugs → GitHub Issues. How it works → `docs/architecture.md`. How to work here →
`CLAUDE.md`. Current state → ask the code: `git`, `pytest`, `gh`. Art direction → `docs/ART.md`.

**Reading it.** Grep it, don't read it end to end. It is a reference, not a narrative.

**Adding to it.** Only when a decision's *reasoning* would otherwise be lost. If a future
reader could work it out from the code, it does not belong here.

**Removing from it.** If an entry contains a status word — shipped, done, deferred, in
progress, next — it is in the wrong file. **Delete it, never annotate it.** Annotating
"UPDATE: resolved" in place is exactly what made this file grow-only and what killed
`STATE.md` before it; git keeps the history, so a deletion loses nothing.

---

## Contents

- [Standing rules](#standing-rules)
- [Settled constraints](#settled-constraints)
- [Rejected — do not re-propose](#rejected-do-not-re-propose)
- [Design sources](#design-sources)
- [Decisions](#decisions)

---

## Standing rules

*Product rules the app must keep honouring — what it refuses to do, and what must not be
"helpfully" fixed. Several exist because the owner had to say them more than once.*

> **The behavioural rules — how a session should WORK here — moved to `CLAUDE.md` on 2026-08-13**
> (§ Standing rules — how to work here). They live there because CLAUDE.md loads every session and
> this file does not, so a working rule kept here was a rule not in force. Don't add behavioural
> rules back to this file.

### Branding/mascots stays undocumented in the wiki  ·  *2026-07-21*

The wiki backlog is closed, and the branding/mascots page is deliberately never to be written. The README's one-line "make it yours" mention is the intended ceiling of public documentation for this surface. "Do not write that page."

**Needs revisiting once the bundling project is finished** — with default art shipping inside the container, what a user can and should be told about `branding/` changes shape. Get specific then; until then the ceiling stands.

**Why.** The branding surface is itself a hidden-feat trigger field: the Konami Starfall egg, picking the eclipse mark animation, and adding a custom mark file all set feat flags; the per-achievement mascot chain, reward art, and tier-SFX slots are unlock-moment surprises the feat system masks server-side. A wiki page inventorying marks/animations/mascots would put those spoilers directly in the user reading path.

### Roast/flavor text: the gate was verified present; the owner still owns the last step  ·  *2026-07-22 · updated 2026-07-28*

The reported leak of uncensored/"spicy" roast lines was deliberately not patched blind. The verification has since been done, read-only: both gates (server blanks `roast_nsfw` unless Triggered is earned; the toggle renders only when the server says so) shipped 2026-07-12 in a single commit and were never absent — the surviving explanation for what was seen is the same-day Folio grid-overlap bug (two renderings stacked, fixed f09cd3b). The one real roast defect ran the opposite direction: the carousel never printed a roast at all, fixed 2026-07-26 (f5cc94b) with a pinned test. The owner still wants to diff the two roast fields himself before final closure.

**Why.** His explicit scope boundary stands. Related standing rule: never audit or sanitize the owner's own product-copy language — the roasts and swearing are deliberate voice.

### "Not single-user" was MISAPPLIED to block shipping the owner's own default art  ·  *2026-07-23*

A prior session argued against shipping the owner's own default branding using the "this is a public, not single-user, tool" reasoning. The owner is explicit that this was a **misapplication**: "not single-user" is about building real security/access strength for real external users — it is NOT a reason to withhold the app's OWN default branding from everyone who downloads it. The app ships the owner's default marks/banner by design.

**Why.** The rule exists to make access control genuinely strong, not to strip the product of its identity. Recording the misapplication is what stops the same argument being re-made against default art.

### Cost badge's compact attribute and cost event are public API, not dead code  ·  *2026-07-24*

The shared cost-badge component's `compact` attribute and its `mg-cost` event have no production consumer yet — by design, not as an oversight. Do NOT delete either as unused.

**Why.** Both are declared public API of a deliberately host-agnostic component. `compact` was built for the not-yet-wired cost-to-finish pill, and `mg-cost` is precisely the DOM-level signal that would carry a price update across the no-build-global vs. esbuild-module wall where the Option-A consolidation stopped. A future pass wiring the cost-to-finish pill or continuing that consolidation needs exactly this surface.

**Update 2026-08-08 (React port, campaign 4/8):** still true, just renamed. The vanilla `<mg-cost-badge>` became `CostBadge.jsx`; `compact` is now the `compact` PROP (rendered by SeparatorBar's chip) and the `mg-cost` DOM event became the `onCost` PROP (SeparatorBar's reveal hook). Both remain DORMANT — SeparatorBar mounts the compact chip but nothing drives it yet, exactly the not-yet-wired cost-to-finish pill this entry reserved. Keep both; a future GenerateDock refit forwards a ref to that chip to show the desktop price there.

### One activity feed for every job source, logged fail-soft  ·  *2026-07-24*

All Job Tracker sources log to the same out_dir/jobs.jsonl activity feed: Control Panel actions, bulk cloud-delete, and a bare CLI run from a terminal (--sync, --update, --generate, --generate-video, plain download), each with a cli-<uuid> id mirroring panel-/bulkdel-. A panel-spawned subprocess logs exactly once, no duplicate entry.

**Why.** Logging is deliberately fail-soft "so a logging hiccup can never break the actual command" — the feed must never be able to take down the work it describes.

### Web surfaces register jobs — they never add a second poll loop  ·  *2026-07-24*

Every web generation surface (the gallery's Generate/Edit/Fix/Enhance tabs, the shared Generate drawer, and all four Loom submit paths) registers via Jobs.register() — registration without a second poll loop.

**Why.** Every one of them already owns a private poller hitting /api/task-status, which is the route that writes the authoritative terminal event. A second loop would duplicate traffic and create a competing source of truth.

### Host filesystem paths are withheld from non-local callers  ·  *2026-07-25*

Read endpoints that would reveal server paths return them only to a local session (the library-path GET, and the per-image metadata route withholds the filename field because it is a host-path fragment). Writes to config are localhost-only.

**Why.** Consistent with the existing Control Panel behavior — a LAN viewer is a trusted generator, not someone who should learn the server's directory layout.

### Packaged assets must keep a loose-file override layer  ·  *2026-07-25*

Any sealed asset container must keep an override layer — packaged defaults, **loose files in `branding/` always win**. Two reasons, both load-bearing: "make it yours" drop-in branding is a shipped feature, and **the branding folder winning is what keeps the hidden achievement earnable** — the trigger fires on a real user-dropped file, which only works if `branding/` stays empty on a fresh install and a file placed there takes precedence over the packed default.

**Why.** Design tension to respect: tidiness must not kill a shipped feature. Without the override layer, packaging silently removes user branding.

### The library-path setter never moves, copies or deletes anything  ·  *2026-07-25*

Setting the library folder only repoints configuration. It validates before writing, asks before creating a missing folder, refuses a path that is a file, and is pinned by a test that greps the handler for move/copytree/rename/unlink.

**Why.** Re-pointing a library must never be able to relocate or destroy the owner's archive as a side effect; the grep-test exists so a future convenience feature can't quietly add data movement to this path.

### Do not call PixAI's moderation operations  ·  *2026-07-26*

Their moderation operations ship in the public bundle. They would fail without permissions — do not call them.

**Why.** They are present and therefore tempting to exercise; they are not ours to use.

### Do not wipe the vector store after a hard reset  ·  *2026-07-26*

Check before reaching for a store wipe on the next hard reset — the recovery path works.

**Why.** Postgres survived the hard lock cleanly: WAL replay succeeded and nothing was corrupt. Resume was also proven safe — the crashed rebuild was resumed rather than restarted, and post-resume similarity scores were byte-identical to pre-resume ones, proving the surviving rows were untouched.

### Easter-egg panel: keep it gated, no UI hint, don't couple it to bundling  ·  *2026-07-26*

Do not make the panel available ungated — that deletes the feature. Do not add a hint anywhere in the UI. Do not block this on the bundling epic; they are independent.

**Why.** Discovery through the filesystem IS the mechanic. A hint or an ungated entry point removes the thing being shipped.

### Log prompts on their own truncation budget  ·  *2026-07-26*

In spend-failure logging, truncate the prompt separately so the structural fields (privacy flag, model id, duration) always survive.

**Why.** A flat 700-character truncation let a long prompt eat the whole budget and cut off exactly the fields the diagnosis needed. The first real failure exposed this, and that diagnosis only existed at all because the logging had shipped an hour earlier.

### Never gate an achievement behind an unbuilt feature  ·  *2026-07-26*

Gating the retooled epic behind the (unbuilt) filter creator is the best thematic fit of the three options and is to be RESISTED for now. Move it there later only if the creator actually ships.

**Why.** "Gating an epic behind an unbuilt feature is precisely how Enhance Adept became unearnable." The same reasoning is why the two remaining free slots stay unspent.

### Never run the similarity/embedding index job alongside anything heavy  ·  *2026-07-26*

The embedding index build must not run next to other GPU/RAM-heavy processes, and that warning belongs wherever the job is launched.

**Why.** The hard machine lock was commit-charge exhaustion (RAM + pagefile), not Pixeltable and not disk — the postgres log carries Windows error 1455 and exception 0xC000012D repeatedly, plus out-of-memory, failed autovacuum fork, failed shared-memory reattach. Owner identified the other party: a forgotten Pinokio process (Forge/WAI-Illustrious) holding GPU and several GB while the rebuild ran. The embed job's own working set is ~18.5 GB, so the two together exceeded what the box could commit. Not a code defect.

### No "replay everything" mode, ever  ·  *2026-07-26*

The replay path takes ONE operation, refuses any mutation outright, requires an allowlist entry or an explicit force flag, and refuses to send an unproven hash. There is deliberately no bulk mode.

**Why.** Calling a harvested catalog blind could delete tasks, submit generations, and spend real credits.

### No email, and no logged-out password reset — permanently  ·  *2026-07-26*

Owner, 2026-07-26, DECIDED PERMANENTLY: there is no mail path anywhere in the project (no SMTP library, no SMTP config — verified, not assumed) and a "forgot password?" link on the login page is deliberately never going to exist. "This will read like a gap to any audit. It is not."

**Why.** Physical access to the server machine IS the out-of-band identity proof — exactly the job an emailed reset link performs in a hosted app, and being at the machine proves it more strongly. The app is locally hosted with closed registration, so that channel already exists. Without an out-of-band channel, a logged-out reset would be a vulnerability rather than a feature: any device on the LAN could trigger a reset against the owner's account. Closing that with email would mean SMTP credentials living in config.json beside the auth secret, deliverability problems on a home network, and a token-expiry surface to get wrong — all to replace walking to the machine.

### No spending mutation may ever be retried  ·  *2026-07-26*

Every mutation that spends credits or changes the PixAI account goes out through the single mutation helper that hard-codes zero retries and offers no retries argument at all, so the unsafe value cannot even be requested. Generate/edit/video/upload/delete-media all ride it. The generic ad-hoc GraphQL path's default was made document-aware as a backstop (0 for a mutation, 3 for a query), and the REST spend paths are pinned single-attempt.

**Why.** A lost RESPONSE (read timeout, dropped connection, a proxy 502 *after* PixAI had already created and charged for the task) made the retry submit and pay for a SECOND generation. Only the delete had been passing retries=0 by hand; every other spending path silently inherited three retries. The API cannot be trusted to be idempotent, so the safety has to be structural (no argument to get wrong) rather than per-path opt-in.

### Not every achievement gets a reward  ·  *2026-07-26*

Reward assignment is about choosing WHICH achievements carry a reward, not populating all of them. Owner, verbatim: *"We don't give a reward for every fucking one."* The 53 blank reward slots were never a gap to fill.

**Why.** Standing correction of a wrong framing that treated blank reward fields as missing work. Do not resurface the blanks as a completeness gap or generate rewards to fill them.

### The antivirus exclusion is the owner's call, not ours  ·  *2026-07-26*

Do not add the Defender exclusion for the Pixeltable data directory ourselves. Catch the cold-start timeout and report it in plain language instead.

**Why.** "a security setting is not ours to change." The underlying facts: the postgres start timeout is 10s but a cold start here needs ~36s, nearly all of it syncing the data directory after a file sharing violation, and postgres's own hint blames antivirus/backup software. So a cold similarity search or rebuild can fail at the starting line with a timeout error that says nothing about the real cause.

### The Feats section is cloaked on purpose — do not "fix" it  ·  *2026-07-26*

With no feat earned yet, the whole Feats section correctly does not exist at all. Once the first feat lands, the section appears and the unearned feats show as mystery cards. Two states, not one. Owner, verbatim: "The feats are a true mystery until the first lands, then the unearned ones have the mystery card. That way unlocking them really feels like opening a new tier."

**Why.** Recorded rather than left to a code comment because the failure mode here is a HELPFUL fix: a sweep reads "section disappears", finds the mystery-tile art and style sitting right there apparently unused, concludes someone forgot to wire it up, and wires it up — destroying the reveal in the name of consistency. The mystery tile is not unused; it is waiting for the second state.

### `started is False`, never `not started` — unknown must stay unknown

Undispatched-job detection tests `started is False`, never `not started`. Absent `started` means *unknown* and keeps the ordinary spinner, so Control Panel / CLI / delete / import rows and any job logged before the feature are untouched. The reaper's caller passes the whole status dict, not just the phase string.

**Why.** "a status source that omits the field means *unknown*, and unknown must not brand every in-flight job stale." Passing the bare phase string instead of the dict makes the detection dead code in production.

### A missing ffprobe degrades the Loom export — it never blocks it

The render export needs each silent, untrimmed shot's real length to build a matching span of silence. Where no length is readable and nothing in the cut carries real audio, the file is muxed with no audio track at all and the export dialog says so in amber, naming ffprobe and the full ffmpeg build it ships with. One refusal remains, for the definitively-corrupt case: a shot carrying real audio alongside a shot whose length cannot be read, where a guessed span would push that real audio permanently out of sync.

**Why.** An earlier repair refused the whole export whenever a length could not be measured. On a machine with ffmpeg but no ffprobe that is *every* untrimmed shot, so the owner got no file at all where they previously got a usable one. Owner's call, 2026-07-27: a missing prerequisite is something to TELL the user about — not to hand them a bare failure over, and not to silently degrade around either.

### A pasted API key must be validated with a hand-built session, never the normal client path

The setup wizard's save-key route validates a submitted key by hand-building a session with that key as the sole credential, deliberately NOT through the normal session/token helpers.

**Why.** Confirmed live: those helpers prefer the module-cached config over a fresh file read — correct for normal operation, wrong for validating a just-pasted key — and a garbage key was reported as verified because the cached real key answered instead. This trap will be re-fallen-into by anyone who reuses the convenient helper.

### achievements.json records earned_at for EARNED ids only

The persisted `achievements.json` writes `earned_at:{id:iso}` for earned achievements only, never a full-roster map, and reads fail-soft.

**Why.** An entry for an unearned achievement would leak hidden feats through a file the client can read — the same spoiler boundary that cloaks the Feats section, scrubs masked metrics server-side, scores feats at zero points so the header total can't hint at one, and picks a ladder's FIRST rung art as its representative badge. A future pass that "completes" the map to track progress-toward would silently defeat all of that.

### Batch generation fails CLOSED on a bad price check

"Generate all" prices every shot first so the confirm shows real cost plus free-card coverage before anything spends, and fails CLOSED if the price check fails — the same guardrail as the single-shot path. It also flags any shot with no real prompt text yet.

**Why.** Spend is irreversible; a failed price check must block the batch rather than let it proceed uncosted. Consistency with the existing single-shot guardrail was explicit.

### Cloud-delete preview makes the blast radius visible — it does not replace a guard

"Delete from PixAI" shows every file that will go, thumbnailed and grouped by task, with the ones actually picked outlined and imports called out as local-only removals. Counts always describe the whole selection even when the thumbnail strip is capped; an unreachable preview falls back to the prose-only confirm rather than a dead click. The typed DELETE prompt and the localhost gate are unchanged.

**Why.** Task-level cloud deletion takes the whole batch, so the consequence has to be visible. "this makes the consequence visible, it does not replace a guard." The preview endpoint is read-only and makes no network call. **Single-media-id deletion now also exists**, so the batch-wide blast radius is no longer the only option — but the preview and guards still apply to the task-level path.

### Every skin reaches every surface

The Loom inherits the gallery's design tokens (--panel→--surface0, --ink→--text, --amber→--accent), so switching skin in the gallery header re-colors the Loom. **A skin must reach ALL surfaces** — not just the two that existed when this was written. Any new surface inherits the same tokens rather than theming itself.

**Why.** One design language across the app rather than per-surface theming.

### loom-core.js purity boundary; pricing is deliberately excluded

Pure Loom logic (flat, shotText, shotPayload, tag math, continuity, frameLinked, connectMeta) lives in loom-core.js as ES exports with no React, no DOM and no fetch. Pricing is deliberately NOT in this module — it is a network call living in the generation pipeline hook. The state layer above it is four composed hooks with pure reducers/classifiers/builders.

**Why.** Keeps the logic Node-testable with no browser or network; pricing can't be pure because it is a server round-trip, so it stays outside the boundary rather than diluting it.

### Some maintenance commands are CLI-only by decision, not omission

Read the CLI-only list before filing a "no Panel button" item. The board has twice raised "maintenance commands have no Panel button" and both times the answer was already recorded. The recurring correction, stated once: a modifier (--embed-metadata, --convert) does not want a button; an already-integrated step (--faststart-videos) does not want a second trigger; and a repair tool (--backfill-meta) actively should not have one. reconcile-deleted likewise runs via the Panel's run route and the scheduler but renders no button by design.

**Why.** A button implies you ought to press it. Surfacing a repair tool or a redundant trigger invites users to run operations that either do nothing the sync has not already done, or that are not standalone actions at all.

### The default download speed is unpaced — `--delay` reaches the parallel stage only when typed

`--delay` always paces the page listing, the per-task metadata fetch, and single-worker downloads. The multi-worker download stage — the default `--workers 4` path — is paced only when the flag is passed explicitly. Left alone it runs at full connection speed, exactly as it always has.

**Why.** The finding (`M07`) was that the wiki documented `--delay` as applying to downloads and on the default path it did not. Making it always-on at the shipped `0.4` capped the whole pool at one image per 0.4s regardless of worker count — it made `--workers` decorative, made the Panel's own workers selector decorative, and turned a 17,000-image first backup from roughly 35 minutes into nearly two hours. That is a silent 3–6x regression on the tool's single most common command, traded for a throttling problem that has never once been reported. The mismatch was mostly a documentation defect, so the wiki was corrected and the flag made to work when it is actually asked for.

### The pure-stdlib cascade test is not a substitute for a rendering test

A stdlib helper resolves which CSS declaration actually wins (important, specificity, document order) from the served HTML so a cascade regression can't land unseen in CI, where the real-browser render harness always skips for lack of playwright. It is explicitly documented as strictly weaker — it proves the winner, not the pixels — and explicitly not a reason to skip writing a rendering test.

**Why.** Without it, a cascade regression could ship unseen on every CI run. With it, there is a temptation to stop writing browser tests; the doc closes that door on purpose.

### The tier test must assert that a LOCALHOST route refuses an authenticated NON-LOCAL session

The route-tier test enumerates the URL map, fails any route declaring no tier, and critically asserts that a localhost-tier route rejects a signed-in remote session. It is verified to fail when the gate is broken.

**Why.** The absence of that one assertion is what let three gate regressions ship in a single week. Enumerating tiers without proving refusal tests nothing.

### The tray renders from the job log, never from a poll response

The Activity tray renders from /api/jobs, never from a poll response. /api/task-status writes `started` into jobs.jsonl, and the tray draws a distinct QUEUED row (mascot with both animations stopped plus an uppercase `queued` pill) that flips to the ordinary spinner when a worker takes the job. The phase is written once per phase change, not once per poll, and the in-process de-dupe entry is dropped at a terminal phase so it stays bounded by in-flight tasks.

**Why.** Four pollers ask every 3s; a per-poll write would bloat the log and keep refreshing the `ts` that the orphan sweep's age check reads. Rendering from the log means the signal reaches both trays with no per-host wiring, since every submit surface's poller calls that one route.

## Settled constraints

*Framing and scope that is decided. These read like gaps to a fresh audit and are not gaps — each one is a choice. Do not resurface them as open questions.*

### Model-bookmark ops are a live contradiction — probe before scoping  ·  *2026-07-04*

The two ops relevant to picker-favorites (bookmarked / liked generation models) are named as real operations in one private RE doc, but a dated recon in another found the equivalent surface **absent on the Query root**, and neither doc has an actual captured response. This is a live contradiction, not a known-good op — it needs a probe before it is scoped, and no assumption in either direction.

**Why.** Both docs look authoritative; scoping picker-favorites on the optimistic reading would build against an operation that may not exist, and dropping it on the pessimistic reading may discard a working surface.

### PixAI's speed channels: 500 is members-only Turbo, not the cheap tier  ·  *2026-07-27*

Read off their own bundle: `{default: 1000, turboMode: 500, low: 0}` (an XHigh 1500 also exists). **1000 is High Priority — anyone may use it and it COSTS EXTRA. 500 is TurboMode — free, ~7.6x faster, and MEMBERS ONLY. 0 is standard.** Their client never submits a tier you are not entitled to, because it normalises first: a member asking for Low is upgraded to Turbo, a non-member asking for Turbo is downgraded to Low.

**Why.** This app had the two backwards in its own comments and defaulted every submit to 500 as "standard, cheaper". Nothing was wrong while the membership was live — it just ran fast and free — so the error was undetectable until the day it lapsed and PixAI began refusing every create path at once with `REQUIRE_MEMBERSHIP`. Reading entitlement before each submit would cost a round trip per generation, so `submit_generation` corrects on the refusal instead and remembers for the session; that is safe for the same reason the neighbouring inferenceProfile retry is (PixAI answered with a GraphQL error, so the task was rejected — nothing created, nothing charged). This also closes the open question in `private/GENERATOR_SURFACE.md` that said Turbo's submit value was never captured: it is 500, pinned from the bundle, no submit and no credits spent.

### An upscale does not choose a model, and the catalog's model_id is a VERSION id  ·  *2026-07-27*

PixAI's upscale dialog has no model control at all: their submit spreads the enlarge/upscale params, sets a FIXED model version, and takes prompts/width/height off the source's original task. Separately, `catalog.model_id` is populated from a task's submitted `modelId`, and a submit's `modelId` **is a model version id** — only a model chosen in the picker is a real model id.

**Why.** Both facts were learned the expensive way. Sending the catalog's value in the `model_id` field put a version id through the model→versions lookup, which matched nothing and refused the submit with "pick a model first" on a picture that was displaying its model on screen. And requiring a model at all was this app's own invention, which left every locally imported file unupscalable behind a dead button. Recorded because neither is guessable from the code alone, and both look like the opposite of a bug until you read PixAI's own submit builder.

**Recurred 2026-08-02** in the Runs reel's reuse-prefill (`GenerateDrawer.jsx`'s `prefillFromRun`), which fed a catalog row's `model_id` into `applyModelRow` the same wrong way — this doc entry existed the whole time and neither the build nor the adversarial verify pass consulted it before shipping. Silent failure this time (a toast, not a blocked submit), caught live during a real test generation. Fixed for real with a reverse lookup instead of a workaround: `moonglade_backup.resolve_model_base_id(session, version_id)` calls PixAI's `getGenerationModelByVersionId` (the same op `model_name_gql` already uses) and reads the `model.id` field it returns but nobody was extracting, exposed via `/api/model-version?version_id=X`. Any future surface that needs a base model id FROM a catalog row (not from a fresh market pick) should call that, not feed the row's `model_id` straight into a versions lookup a third time.

### The Panel's "Stop this job" button is shown to every session on purpose  ·  *2026-07-27*

Stopping a maintenance job is localhost-only and server-enforced. The BUTTON is nonetheless rendered for every signed-in session, including LAN devices, which means a LAN user can confirm the dialog and then be refused. That is the owner's call and it stands: do not "fix" it by hiding the control.

**Why.** It reads like an authorization-UX defect to a fresh audit (it was filed as one), and the obvious repair — hide the button off `_is_local_request()` — would be wrong twice over: it moves a security rule into the UI layer where it cannot be trusted, and it makes the control's absence look like a bug to the owner on his own LAN device. The refusal is the correct behaviour; only the wording of it is ever worth revisiting.

### Masked achievements are not worth hardening before the asset bundle exists  ·  *2026-07-27*

`/api/achievements` masks hidden, unearned Feats to a `???` placeholder but leaves them in the array, so the COUNT of undiscovered feats is readable in the raw JSON. This contradicts the wiki's "no placeholder count… found by playing, not by reading", and it is deliberately NOT being fixed at the JSON layer.

**Why.** The achievement and branding assets are to be bundled into a package format (the MPQ-style container the owner has raised repeatedly), which changes what is discoverable at a level a response tweak cannot reach — anyone can read a JSON response, bundled or not, but the whole discoverability model shifts once the assets stop being loose files. Masking the array now is work thrown away against that design, and would also have to be undone or reconciled when the bundle lands. Revisit as part of the bundling design, not before. See [[Packaged assets must keep a loose-file override layer]].

### mg-generate-drawer must stay a build-free <script>  ·  *2026-07-18* — SUPERSEDED 2026-08-08

**SUPERSEDED by "Vanilla campaign 7/8 COMPLETE" (2026-08-08):** the whole no-vanilla directive
reversed this. The drawer is now the React `<VideoDrawer>`, bundled into both hosts' builds; the
friendlyGenErr copy moved to `gallery/src/gen/videoDrawerCore.js` and its parity test (against
loom-mutations.js) moved with it. Kept below for history. ~~The shared generate drawer cannot
import from loom-mutations.js (an ES module) and must stay a build-free `<script>`.~~

~~Shared logic it needs (e.g. the friendly generation-error mapper) is a local, verbatim port, with a permanent parity test guarding the copy against drift.~~

~~**Why.** The component is framework-neutral and mounted by two different hosts; requiring a build step would break that. A duplicated-with-parity-test copy is the accepted cost of the constraint, not an oversight.~~ (Both hosts now have a build — the Loom went bundle-only in campaign step 1 — so the constraint no longer holds.)

### RESOLVED: /api/task-status conflated a local blip with a real PixAI failure  ·  *2026-07-18, resolved since*

~~Flagged, deliberately not acted on: /api/task-status's exception handler returns HTTP 200 {phase:"failed"} for a transient local blip, which is indistinguishable from a genuine PixAI failure to either poll loop.~~ **Resolved in code (confirmed 2026-08-07 doc-parity audit):** the transient `except Exception` branch now returns `{"phase":"running","status":"checking…"}` (non-terminal), NOT `"failed"` — genuine code defects are split out to get the authoritative `"failed"`. So a local blip no longer reads as a real PixAI failure to the pollers. See the "audit fail-open fix" comment at the exception handler in `moonglade_gallery.py` (grep `checking…` / `audit fail-open`).

**Why (historical).** Was left open rather than changed unilaterally because altering the error shape changes what every poller treats as terminal; the eventual fix made the transient branch non-terminal without touching the genuine-failure path.

### The multi-hour give-up tiers were never clocked in real time  ·  *2026-07-18*

The 20-minute / 90-minute / 6-hour escalation tiers on the generation give-up timer were verified by code review plus an adversarial-review pass — not by observing a real generation run that long. Treat the escalation as reviewed, not measured.

**Why.** Everything around it was live-tested against real generations, so the section reads as fully verified. Recording the gap keeps someone from citing this as proven behaviour, and keeps the honest option (actually clock one, or drive it with an injected clock) on the table instead of being assumed done.

### The output directory name is not part of the rename  ·  *2026-07-19*

`pixai_backup` is the output directory named in every existing install's `config.json`, so it must NOT be swept along by a prefix rename. Two traps recorded from the naming-pass planning: a prefix-wildcard sweep silently repoints people's archives at nothing; and an import-only shim leaves the whole test suite green while breaking every one of the ~116 documented commands that invoke the modules as scripts (plus the launchers and the Panel's subprocess runner). The pass was scoped rename-only, on its own branch, in its own session.

**Why.** Both failure modes are silent — one destroys user archives without an error, the other passes CI. The module rename is done; these constraints outlive it because the output directory still carries the old name by design.

### Toast tier colors — owner called it resolved, but the direction wasn't restated  ·  *2026-07-23*

The owner said the toast/rarity-pill color question versus the shipped badge art is resolved, but did not restate WHICH direction (realign the code's colors to the shipped badges' tier scheme, or keep the code's original common/gunmetal/ruby scheme). Confirm with him before touching the CSS. Specifics land in the Design Pass.

**Why.** Acting on either reading risks restyling a shipped, owner-approved surface against his actual intent.

### A uniform tier→reward rule cannot cover the whole roster  ·  *2026-07-24*

Structural constraint to know BEFORE assigning rewards: not every ladder track reaches every prestige tier (four tracks cap out short of legendary), and the milestone and mastery buckets never reach legendary at all. So a strict "climb to legendary, get the banner" rule cannot produce a banner for those tracks or those buckets without adding rungs. Also still unstated: the owner's phrasing was `low→icon / epic→skin / legendary→banner` — whether `rare` counts as "low" alongside `common`, or wants its own reward kind, has never been decided.

**Why.** Anyone implementing the tier→reward mapping as a uniform rule will produce a roster where most achievements can never earn a banner; the mapping needs per-bucket design, not one formula.

### Nightfallen's free-vs-gated status is an unresolved owner call  ·  *2026-07-24*

Open tension, not recorded in any prior doc: Nightfallen is one of two skins currently flagged free and is not achievement-gated at all. The "Moonwell Eclipse unlocks with Nightfallen" decision does not say whether Nightfallen should become gated too, or stay free while only its matching mark is the gated half of the bundle. Needs an explicit owner call before either is built.

**Why.** Building either interpretation silently would either revoke something users already have free, or ship a half-gated bundle — both are owner-facing choices, not implementation details.

### Scroll-triggered load-more cannot be proven by synthetic events  ·  *2026-07-24*

Dispatching a synthetic scroll event does not reliably reach the animation-frame-throttled callback in sandboxed browser automation; the load-more function called directly appends correctly every time. Treated as a known simulation gap, not evidence of a bug — it needs the owner's real scrolling to confirm.

**Why.** Recorded so nobody burns a session hunting a phantom defect in the throttle chain, and so nobody claims that chain "verified" off a synthetic dispatch.

### When both LoRA cap fields are present, `lora` wins over `freeUserLora`  ·  *2026-07-24*

The account's per-generation LoRA cap comes from the membership privilege data PixAI's own account API already returns; where both fields appear, `lora` is used, mirroring the CLI dashboard's existing field-check order.

**Why.** The exact coexistence semantics are unconfirmed — there is no live subscribed account available to probe from this checkout — so the tie-break was chosen to match existing behavior rather than invented. Flagged as unverified so a future probe knows to check rather than assume.

### Booster and upscale parameters are emitted only when opted in  ·  *2026-07-25*

Every upscale/booster key is added to the submit only when actually requested, so a generation that does not opt in produces a byte-identical payload to before the feature existed. The two upscale methods are mutually exclusive and their radio values ARE the parameter names.

**Why.** Byte-identical submits mean the feature cannot perturb pricing or output for anyone who never touches it — the safest way to extend a shared spend path.

### LoRA weight-range table has a known hole until DiT.3 is captured  ·  *2026-07-25*

`MMDIT26A_MODEL` is confirmed to mean DiT.2. PixAI's Model Type filter offers All / DiT.3 / DiT.2 / DiT.1 / SDXL / Community DiT / SD 1.5, so **DiT.3 is a real type we have no enum for** — and the owner's LoRA-weight ranges (DiT 0..1.2, SD -2..+2) never mentioned DiT.3 either. Treat the weight-range table as INCOMPLETE until DiT.3's enum token and range are captured the same way (select a DiT.3 base in the picker and read the sent architecture list). Note also that DiT.3 is absent from the training page's Model Type list though it appears in the generate picker — it is generate-only for now, which is part of why its enum was never captured.

**Why.** Prevents shipping a weight slider that silently mis-ranges DiT.3, and prevents someone assuming the five known enum values are the complete set.

### Packaging must not be scoped as secrecy for displayed art  ·  *2026-07-25*

Packaging **cannot** deliver secrecy for art that is displayed, and must not be scoped or sold as though it can. "What the browser renders, the browser has."

**Why.** Hard limit of the medium. Stated so nobody scopes the epic against a promise it can't keep.

### Queue-ETA verification: the "3 seconds" reading was a real short queue, not a bug  ·  *2026-07-25*

The QUEUED phase and queue ETA were verified against a live generation (task 2037959839192719439). PixAI's wait-time route is real and per-priority: at Tsubaki.2 v1, priority 500 answered 34.8s twice while 1000 answered 30.8s then 26.7s. On the generation itself the tracker quoted 21s while the job log's own timestamps put the actual queue wait at 26.7s, then 82s of rendering. The earlier "both gens said 3 seconds" was a genuinely short queue.

**Why.** Recorded so nobody re-investigates a low estimate as a defect — the estimate is sound and the small numbers were real. Also note the route takes a model *version* id as its model parameter, and priority is a validated enum (500/1000).

### The 57-roster JSON is gone: removed from the repo and scrubbed from history  ·  *opened 2026-07-25 · executed 2026-07-27*

`docs/achievements_roster_57.json` (2.98 MB, the complete 57-achievement design record — every hidden feat, trigger and roast) should never have been published; owner, 2026-07-27: it should have been pulled long ago. It was removed from the tree on 2026-07-27, and the same day the repo's ENTIRE history was rewritten (git filter-repo + force push) so no historical version of the file is browsable on GitHub either — a plain deletion would have left every old version one click away, because pulling a file and un-publishing it are different operations. The canonical design record now lives only in the owner's own backups, deliberately OUTSIDE version control. `tools/build_roster_board.py` still accepts a roster path (`--roster`); point it at the backup copy for any future board rebuild — its committed default path is now intentionally dead.

**Why.** The 2026-07-25 tradeoff (losing version control of the canonical record) was weighed and overruled by the owner: no-spoilers wins, and he keeps his own backups. Server-side masking of unearned feats was never affected: cloaked entries have their metrics scrubbed before reaching any client. Note for future readers: prose references to pre-rewrite commit hashes (in this file, the changelog, the wiki) date from before the history rewrite and may no longer resolve — they are historical labels, not links.

### The job log's `started` phase is written once per phase change, never per poll  ·  *2026-07-25*

`/api/task-status` writes the `started` signal into the activity log exactly once per phase transition, de-duplicated in-process, with the de-dupe entry dropped at a terminal phase so the table stays bounded by in-flight tasks.

**Why.** Four independent pollers hit that one route every 3 seconds. A per-poll write would both bloat the log and — the part that actually breaks something — keep refreshing the event timestamp that the orphan sweep's age check reads, so a wedged job would never look old enough to be reaped. Anyone simplifying the de-dupe away as redundant bookkeeping would silently disable silent-death detection.

### The output directory name is not renamed  ·  *2026-07-25*

The `pixai_backup` output directory is explicitly NOT part of the rename, despite being the single largest reference count.

**Why.** It is named in every install's config.json — renaming it would break existing installs' configuration, which is a different and much more invasive change than renaming source modules.

### Apollo CSRF headers are required on any new client code  ·  *2026-07-26*

PixAI's Apollo rejects requests it considers CSRF-able with a BAD_REQUEST unless one of the apollo operation-name / require-preflight headers is present. The existing session builder already sends both. Any hand-rolled request needs them.

**Why.** Recorded because it is the gotcha that will bite any new client code: it is exactly why the existing API-key path never hit this error and a fresh hand-written probe hit it immediately — the failure looks like a malformed query rather than a missing header.

### Asset bundling does not gate the branding easter egg  ·  *2026-07-26*

The MPQ-style asset bundling is a SEPARATE want (a tidy install folder) and is not a prerequisite for "Under the Hood."

**Why.** The owner's own art already never ships — the output directory is git-ignored wholesale, so branding lives only in his machine-local output folder and a fresh install contains none of it. The problem bundling would solve is already solved for this purpose.

### DiT.3 is generate-only for now  ·  *2026-07-26*

The training page's Model Type list offers DiT.2 (NEW), DiT.1, SDXL and Other. DiT.3 is absent there even though it appears in the generate picker — so DiT.3 is generate-only, which is part of why its enum value was never captured.

**Why.** Stops a future pass from hunting for a DiT.3 training enum that does not exist yet.

### Empty branding slot folders are blocked on packaged assets  ·  *2026-07-26*

Sequence is fixed: bundle the default assets FIRST, and only then are the empty slot folders ungated. The "Under the Hood" trigger redesign is therefore blocked on the packaged-assets work, not on a trigger decision.

**Why.** Owner set the dependency explicitly so the trigger question stops being treated as the blocker. Don't design a trigger for folders that shouldn't be exposed yet.

### LoRA training spec captured for zero credits  ·  *2026-07-26*

The whole LoRA-training spec was read off their page and bundle with zero credits spent, deliberately. Owner has 8 free trainings; a paid run is 75,000 credits — roughly 23 upscales — so the free slots are worth real money and none were burned to learn this.

**Why.** The habit is the point: capture the spec from the page and bundle rather than by spending a slot to see what happens.

### Never re-upload an image the account already hosts  ·  *2026-07-26*

Do not re-upload a frame just to feed it into a generation. A fresh upload gets content-scanned; an image already hosted on the owner's own account does not.

**Why.** An NSFW frame he could animate fine on PixAI's site was refused through our tool with a 403 content-scanner error at task creation — before any task existed, which is why nothing ever appeared on his account. The content was never the problem and neither was the model version: our upload manufactured the rejection. Proven by read-only survey (zero credits): 5 of 5 of his own i2v-Pro tasks carried an in-catalog media id, zero uploads, spanning 2026-06-08 to 2026-07-22 across three model versions and including two dated 2026-07-20 itself that rendered fine. PixAI never changed; that path has always accepted a generation-OUTPUT id.

### Omitting the video mode field is the EXPENSIVE default  ·  *2026-07-26*

Always send the i2v-Pro mode field explicitly. Omitting it priced at 50,000 credits against 18,000 for an explicit 'professional' — nearly 3x. (Measured: professional 10s = 18,000; basic 10s = 14,000; the newer model professional 10s = 55,000; mode omitted 10s = 50,000.)

**Why.** Anywhere the code drops that field to be "safe" is silently choosing the costliest option. The image path's documented pattern of "omit it and let PixAI pick the default" is a claim about VALIDITY, not about COST — do not carry it over to a spend-shaped parameter. Latent rather than live today, but a real trap for any future caller.

### Payment operations stay permanently out of scope  ·  *2026-07-26*

Their payment and subscription operations exist in the harvest and stay permanently out of scope, per the standing money rule.

**Why.** A standing prohibition, not a prioritisation call — presence in the surface map is not a reason to revisit it.

### refreshToken stays untested on purpose  ·  *2026-07-26*

refreshToken is NOT a dependency of the mirror feature. It remains an optional nicety to weigh later on its own merits, and stays deliberately untested.

**Why.** It is a credential mutation, and rotating the token could log the owner's browser out mid-session. Not worth probing when the design does not need it.

### Self-reset must take no username parameter at all  ·  *2026-07-26*

The "reset my own password" path must not accept a username parameter of any kind — it acts on the session's own account only.

**Why.** Stated plainly because it is the kind of boundary that drifts: if the endpoint accepts a target username, a LAN visitor can aim it at the owner's login simply by editing a request.

### The gitignore entry ships in the same commit as the branding move  ·  *2026-07-26*

Branding was made contingent on its gitignore entry landing in the same commit as the folder move.

**Why.** Otherwise the first person to drop a mascot in and check git status sees their own art as untracked repo content — and staging everything is already banned here for exactly that class of accident.

### The mirror design must not depend on token auto-renewal  ·  *2026-07-26*

Renewal is answered: measured 2026-07-26, there is NO token response header on a mutation response nor on a read-only query. The expose-headers list still mentions one, so the mechanism exists somewhere in PixAI's own flow (login, or their near-expiry refresh), but not on any call this app would make. The design must not depend on it.

**Why.** Building on a refresh mechanism the app never actually observes would produce a credential path that silently stops working — exactly the failure mode the U3T experience already taught.

### The queue estimate is a WAIT, not a countdown  ·  *2026-07-26*

The generation ETA presented in the tracker is an estimated wait.

**Why.** An earlier reading of two generations both reporting three seconds was mistaken for a hardcoded constant; it was a genuinely short queue. Recorded so the number isn't "fixed" again as if it were fake.

### 320px is the support floor for web surfaces

The Job Tracker/Activity tray and the snippet/tag popups clamp max-width to calc(100vw - Npx) so none of them run off a 320px-wide screen (replacing flat max-widths). The gallery's filters become a bottom sheet below 480px.

**Why.** 320px is treated as the narrowest screen that must work.

### The Loom is reachable at every width — REVERSED 2026-07-27

The Loom nav button was hidden below 480px. **That gate is deleted** (owner, 2026-07-27): V2 is the live surface and is usable out of the box in landscape, so hiding its only entry point did not protect anyone — it made a shipped feature unreachable from a phone entirely, with no hint it existed.

**Why the original call was wrong, so it isn't re-made.** "Don't offer it broken" is sound when the surface *is* broken; it became stale the moment V2 landed and nobody revisited the CSS. A capability gate that outlives the limitation it was written for reads to the user as a missing feature. Portrait on a phone is still cramped — that is a **known, deferred polish gap, not a reason to hide the door**; rotating the phone is a thing the user can do and discover, hunting for an invisible button is not.

### Config writes must be atomic

The config save writes to a temp file and replaces.

**Why.** A torn read returns an empty dict, which reads as zero accounts and drops the entire install into first-run bootstrap mode — i.e. a crash mid-write could hand the install to whoever loads the login page next.

### Gallery search-bar redesign is deliberately blocked on the owner's layout-notes pass

Unstarted on purpose. Banked design direction: a LEFT Filters drawer mirroring the right Generate drawer. Do not sketch until the owner's layout pass happens.

**Why.** Deliberate sequencing, not neglect — the layout pass defines the space this would live in.

### Nothing in the Loom requires a build step

The esbuild bundle is opt-in via /loom?bundle=1; Babel-standalone is the default. Pure logic still lives in real ES modules with a Node/npm/esbuild toolchain scoped to loom/, but no build is ever required to run the app.

**Why.** Keeps the app runnable straight from the repo with no toolchain in the way; the bundle is an optimization, not a dependency.

### READ_ONLY is a user-facing contract, and it overrides every confirmation flag

A config flag refuses every account-mutating call outright — submitting a generation, submitting a hand/face fix, deleting a task, claiming a reward — from CLI or web, regardless of --confirm/--apply/--yes. It is enforced at the four choke points every such path funnels through. Any new path that spends or mutates must call the check before the network call fires. Scoped to the PixAI account specifically: the local organize/dedup operations are untouched (already dry-run by default, never network).

**Why.** It is the promise the Trust & Safety wiki page makes to users, not a per-path convenience — so it is not optional opt-in. Gating at the four shared choke points covers both surfaces from one place.

### READ_ONLY is scoped to the PixAI account only — local commands stay untouched

`READ_ONLY` gates exactly the four account-mutating choke points (submit generation, submit fix, delete task, claim reward). Local-only maintenance — `--organize`, `--dedup` — is deliberately NOT gated by it.

**Why.** Those commands are already dry-run-by-default and never touch the network, so gating them would add nothing and would misrepresent what the flag promises. The flag's contract to users (the wiki's Trust & Safety page) is specifically "nothing happens to your PixAI account," not "the tool becomes inert" — so a later pass that widens it to every mutating path would break the stated contract rather than strengthen it.

### Registration stays closed: the first account is loopback-only, and the CLI adder is recovery only

The first account is created through the login page itself, offered only to a loopback request while zero accounts exist. Ongoing management is Panel → Users (adding, or removing an account that isn't yours, from the server's own machine; removing your own works from anywhere). The CLI add-user flag remains a recovery path only — and is currently the only way to reset a forgotten password.

**Why.** Bootstrap-on-loopback means a LAN device can never claim the install. There is deliberately no public signup; do not resurface closed registration as a gap.

### Repo is public with real external users

Moonglade is a public repo with real external users — not a personal/single-user tool.

**Why.** Stated as a standing framing fact that governs how features (especially access/security) are built.

### ShotPreview is not a full NLE

The timeline preview carries play/pause honoring the trim range, hover-scrub, trim handles, playhead stepping, Split (cuts a shot in two at the playhead, both halves keeping the same clip with the trim range divided) and Crop (per-shot {x,y,w,h} fractions applied at export). "Not a full NLE."

**Why.** Explicit scope ceiling on the editing toolset — enough to assemble a cut, not a video editor.

### The gallery is default-deny, with no localhost bypass

One before-request hook gates every route. The public surface is exactly four things: login, logout, the branding art the login page itself needs, and the web manifest (a compile-time constant the browser fetches unprompted from the login page). Login is required from 127.0.0.1 exactly as from a LAN address.

**Why.** This is a public repo with real external users, not a personal single-user tool — access control gets real strength, not a convenience shortcut. A localhost bypass is exactly the kind of shortcut that erodes it.

### The owner's layout/function note-taking pass gates several cosmetic items

Pending, and it gates: the image picker's further visual polish, taste-level width/spacing tweaks on Generate/Edit/Enhance, and the Composer's collapsed-stack fan animation. Features are deliberately built cheap-to-rearrange in anticipation of it.

**Why.** The "build it cheap to rearrange" posture is a design choice made because the layout is known to be about to change; it explains why these surfaces look unfinished on purpose.

---

## Rejected — do not re-propose

*Tried and failed, or considered and turned down. This section exists so nobody spends a day rediscovering a dead end.*

### Do not fabricate data to satisfy a validation rule  ·  *2026-07-27*

A repair pass "fixed" an empty-prompt rejection on upscale by inventing a fallback prompt string in the client and sending it to the paid generation endpoint. Reverted the same day. A second pass "fixed" Stop/Restart orphaning a maintenance job by making the server KILL the job — the opposite of what the Panel already enforced (both buttons carry class `jobbtn`, which the poller disables for the life of a job). Also reverted; the routes now refuse with a 409, which is what the UI had always implied.

**Why.** Both are the same failure with different faces: an agent met a wall, invented a plausible way through, and shipped a behaviour nobody had chosen. The prompt one would have steered a real re-diffusion on the owner's credits; the Stop one contradicted a rule the app already had. The rule that came out of it, and that now leads every repair brief: if a fix needs a product or behaviour decision — inventing a default, choosing what reaches a paid API, picking between two defensible behaviours — **stop and report the choice**. "I stopped here, and here is the choice" is a success. A plausible invention is a failure, even when the tests pass.

### Claude's "the toggle just isn't checked" explanation of the roast leak is WRONG — do not restart from it  ·  *2026-07-22*

After the owner earned the Triggered feat live (real play, screenshot in hand), the unleash flag genuinely flipped true, the toggle appeared, and the toast text matched the achievement's normal roast field word-for-word. Claude reported this as "expected — the toggle just hasn't been checked yet." The owner said that explanation is incorrect. Resolved 2026-07-28: of the two possibilities recorded below, (b) is the survivor — the gate was never absent (both gate lines shipped 2026-07-12, one commit, untouched since), so the report described the screen while the grid-overlap bug was live.

**Why.** Recorded so the next session does not adopt the toggle theory as a starting point without re-deriving it. The two possibilities were: (a) a genuine gating bug somewhere in the chain, or (b) the report describing what was on screen while the grid layout bug was still live — ladder tiers render twice, and two overlapping renderings read as "two flavors shown for one achievement" with no roast-logic bug at all. The owner's own roast-field diff remains his step before anything further is decided.

### The easter egg IS `under-the-hood`, and its current trigger premise is rejected  ·  *2026-07-23*

Confirmed: `under-the-hood` is the easter egg. Its current trigger (fires when any custom mark file exists in the branding folder — i.e. it requires the folder to have started EMPTY and the user to have dropped in their own art) is rejected by the owner on two grounds: (1) it assumes a stranger randomly discovers an empty branding folder and knows to drop an image into it — an unrealistic trigger for a real easter egg; (2) more fundamentally, **the branding folder was never supposed to ship empty** — the app should ship the owner's own default marks/banner by design, so "empty folder" as a precondition doesn't even hold once defaults ship correctly.

**Why.** Objection (2) invalidates the entire mechanism rather than just tuning it: the moment defaults ship, the precondition can never be met. Any redesign must start from "defaults exist", not from patching the file-drop check.

### PixAI one-click panelplugin workflows are impossible here — surface deleted, do not rebuild  ·  *2026-07-24*

The ten one-click cards, the ComfyUI catalog search, the enhance/workflows endpoints, the parameter builder, the workflow catalog and the --workflow-id flag were all deleted. The Enhance pane now says so and points at Fix. The Fix sub-tab (a separate box-coordinate hand/face fixer) is unrelated and works.

**Why.** PixAI never assigns a worker to a panelplugin task submitted with an API key: it accepts it, queues it, charges it, then cancels at roughly 60 minutes with reason "waiting timeout" and refunds — including their own official preset ids, while their web client runs the identical workflow in 1-3 seconds. Zero images were ever produced. This is a server-side entitlement, not something a client fix can reach.

### Art filters are free, offline, and client-side — the paid enhance path is DELETED  ·  *2026-07-25*

The paid filter/enhance path (build_filter_parameters, --filter-id, --enhance, run_enhance) is gone. Art filters are gradient-overlay recipes composited in the browser: no Generate button, no price, and picking a filter makes ZERO network requests (measured). Rendering is client-side both ways — CSS mix-blend-mode overlays for the live preview, one canvas gradient fill per layer for the export, both pinned to the same gradient geometry so they agree.

**Why.** The paid path "charged credits and waited on a worker queue for a handful of gradient fills." Do not rebuild it. (Consistent with the separately settled finding that the panel/Enhance surface never dispatches at all for an API-key client.)

### The asset container is SQLite — DECIDED; zipapp rejected  ·  *ranked 2026-07-25 · decided 2026-07-27*

**Owner decision, 2026-07-27, verbatim: "sqlite is the no-brainer. it already houses our catalog."** The bundle is its OWN single file shipped with the app — not rows added to the user's machine-local `catalog.db`. The bundle is a versioned, distributable artifact; the catalog is user data; merging them would break atomic one-file distribution. Shape as ranked: one file, a table of (path, bytes, sha256, mtime), hash-indexed random access, transactional updates, no extraction step, and no new dependency since the catalog already links SQLite. Runner-up was **a plain zip** (read natively by Python, servable straight from Flask, simpler and more inspectable; marginally worse at many-tiny-file random access, irrelevant at this scale). **`zipapp` / `.pyz` is rejected** — it bundles code, not runtime assets. What packaging buys: a tidy install, atomic versioned distribution (one file, cannot half-install), tamper-evidence via a signed hash manifest so a swapped mark becomes DETECTABLE, and a container whose format you must know rather than a folder you can browse.

**Why.** SQLite is behaviourally closest to MPQ and closer still to CASC (content-addressed) while adding nothing to the dependency set. The zipapp rejection is a category error worth recording so it isn't re-suggested. The mechanism is now settled; what remains unscoped is the contents inventory, the signing scheme, the loose-file override layering, and the masked-achievements revisit — see [[Masked achievements are not worth hardening before the asset bundle exists]] and [[Packaged assets must keep a loose-file override layer]].

### The "Did you mean" hint heuristic was wrong — capture, don't probe  ·  *2026-07-25*

Rejected and recorded so it is never trusted again: a probe was built on the idea that PixAI redacts the *content* of GraphQL's "Did you mean ...?" hint but not its *existence*, treating "absent, but a hint fired" as a near-miss. Two invented names produced hints; the REAL name produced none. Driving the browser answered in three clicks what the probe had actively misled us about. **Standing rule: for a surface the website itself uses, capture the request — do not probe the schema.**

**Why.** The heuristic looked clever and was actively misleading, which is worse than useless. Recorded because a plausible-sounding probe is exactly the kind of thing that gets re-invented.

### Upscale belongs on the image view, not in the generate drawer  ·  *2026-07-25*

The drawer's old three-way Off/Upscale/Hires segment was removed; only the Enhance Details booster stays there. Upscale is now a dedicated component: a full inline panel on the detail page and a flyout in the lightbox.

**Why.** PixAI invokes Upscale on a picture that already exists, so the drawer was not where PixAI offers it. Worse, a drawer has no source image, so the ratio cap and predicted output size had to be derived from the size the generation was *about* to be — a guess. On the image view the real source dimensions are known.

### Auto-favouriting each generation via upsertBookmark  ·  *2026-07-26*

REJECTED by the owner 2026-07-26, and he says he disliked it when it was first raised. Do not re-propose it. An earlier note recorded it as an agreed plan; that note was wrong and has been corrected at the source.

**Why.** Bookmarking puts things in the FAVOURITES shelf, not the generations library — the wrong shelf. It does not solve the actual problem, which was that API-key generations never file into the account at all.

### Block / report: NO  ·  *2026-07-26*

No moderation tooling. Owner: "Not going to be flagging my OWN work."

**Why.** They are moderation tools for a site we do not host, aimed at content that is his own.

### Bundle scans must follow imports transitively  ·  *2026-07-26*

Never conclude a value does not exist from scanning only the chunks one page happened to load.

**Why.** A previous pass scanned "all 204 chunks on the enhancement page" and concluded a value did not exist, when it actually sat in a LAZY chunk that page never loaded. That is the documented scoping bug the transitive crawl exists to fix.

### Comments: NO — solved by a model-page click-through instead  ·  *2026-07-26*

We build no comment surface. Instead, make a selected model in the Generate panel clickable through to that model's market page, where their comments already live.

**Why.** There is no post/read/delete comment operation in their bundle at all — all three comment-shaped operations are anti-bot turnstile controls. So comments were never optional, they were absent. The owner's answer is better than building anything: their social side stays theirs. Same instinct as reusing existing controls rather than inventing UI. The click-through is what makes the rest small — with it we never build a comment surface, a creator feed, or a moderation queue (one link covers all three), and follow/unfollow becomes the only social write we own.

### Epic-tier frame art and the deep-purple tier-gear direction  ·  *2026-07-26*

Rejected. Do not propose Epic-tier ornate frames, and do not revive the previously banked "deep-purple WoW epic / tier-gear" art direction for them — it was shelved 2026-07-23 while the owner was on the fence about the whole premise, and the 2026-07-26 decision (Feats only) settled it by removing frames from Legendary too.

**Why.** The premise itself was wrong, not the execution: framing signals opening a new tier, which only a Feat does. Recorded so the epic-frame question is not re-opened as an art task.

### Five distinct art filters as the Enhance Adept swap  ·  *2026-07-26*

An alternative the owner raised: swap in "five distinct art filters applied." Weaker choice, kept on the bench rather than adopted.

**Why.** It is a direct like-for-like swap and filters are local and free, so it would be earnable without spend — but it is a clicking achievement, which is too thin for an EPIC tier.

### Generation Flags: measured not-feasible list  ·  *2026-07-26*

From the Generation Flags scoping survey: **bad hands / anatomy errors is NOT feasible**, and **zero-shot CLIP NSFW scoring was measured and fails**. Do not re-propose either as a flag.

**Why.** Both were actually measured during scoping rather than estimated, so re-proposing them costs the same measurement again. Recorded as rejected, not as "hard".

### Making the branding panel plainly available  ·  *2026-07-26*

REJECTED. The proposal was to make the branding panel plainly available and demote the achievement to mere recognition, on the reasoning that gating utility behind an unbuilt epic creates deadlocks. Sound in general, wrong here.

**Why.** The gate is the reward mechanism, not an obstacle in front of one. Removing it deletes the feature's entire purpose (rewarding the user who pokes around) and leaves a settings tab nobody was meant to just find.

### PixAI is NOT a Next.js app  ·  *2026-07-26*

It is React Router bundled with Rolldown, and their JavaScript is not served from their own site at all but from a versioned CDN path carrying a build fingerprint.

**Why.** Two attempts inside this tool failed on the old Next.js assumption before anyone actually looked. The build fingerprint in the path is useful in its own right: a diff can report "they shipped a new build" rather than just "a hash moved".

### Ruled out for the V3.0 Lite decline  ·  *2026-07-26*

Four free read-only price probes (the pricing call takes the same parameters dict as a submit and spends nothing) all priced fine, including his exact settings. So: the param shape is VALID and PixAI quotes it; the theory that the model label was simply lying is NOT supported for his case; and the 15s duration gate found alongside is not his cause either — he was on 10s. A prompt-level moderation rejection, which would create no task, remains a live possibility.

**Why.** Recorded so nobody re-proposes shape-invalidity, a lying label, or the duration gate as the explanation. The failure happens after the shape check.

### A multi-track timeline is OUT OF SCOPE

Layered clips plus a visible audio lane are explicitly out of scope for the Loom. Per-shot audio cues aligned to their own timeline segment cover the real need.

**Why.** The tool's job is building 5–15s scenes and stitching them cohesively; the stitched output goes to a real video editor for post. Rebuilding an NLE inside the Loom duplicates the tool that already comes next in the pipeline.

### Figma-invented mobile concepts, rejected

In porting the Figma Make mobile mock, specific Figma inventions were rejected and replaced (the artifact's own comments record this): the Nature/Architecture/Portrait/Abstract taxonomy DOES NOT EXIST in this app (media type does); invented model names were swapped for the real model families; and Generate+Video were merged into ONE "Create" tab with an internal Image/Video switch because the desktop drawer already works that way.

**Why.** These are the corrections that make the port trustworthy. Without them recorded, a future pass re-imports the Figma's fictional taxonomy and split tabs as if they were design intent.

### Footage is a tab, not a fourth region

Footage is a second tab inside the left card beside Cast & assets — not a fourth region of the shell.

**Why.** The shell is deliberately four fixed regions; new content goes inside an existing region rather than adding one.

### LAN sessions are NOT read-only — only LOCALHOST-tier controls are hidden

A signed-in LAN session browses, generates, and drives the Loom and Panel exactly like the owner at the keyboard. What a remote session loses is only the LOCALHOST-tier controls (Import, Delete from PixAI, Set launcher icon, the destructive Panel jobs). The header's #lan-chip names those withheld controls in its tooltip and says to open the gallery on the serving machine's own localhost address to get them; it branches on the same value the Import button and can_delete_cloud already read, so it is a LABEL on a decision the tier helpers have already made and gates nothing itself.

**Why.** It replaced an unreachable "read-only LAN view" note that was both dead code (hung off a value hardcoded True at render) and wrong on the facts. Do not reintroduce "LAN = read-only" framing.

### Loom tooling — Svelte and hand-rolled vanilla+signals are REJECTED

Banked/rejected picks for any Loom migration: Preact remains an optional later spike. **Svelte and hand-rolled vanilla+signals are rejected.** Canvas is not needed for the reel at this scale. A docking library (Dockview / FlexLayout) stays a banked pick, but its precondition is closed — nothing in Loom V2 is draggable, resizable, or persisted, and the Timeline is a fixed drawer **by design**.

**Why.** Rejections are about the situation, not the frameworks: a solo dev migrating untested code cannot absorb a full-framework rewrite. And docking has nothing to dock — the fixed Timeline drawer is an intentional choice, so the library would be solving a problem the design doesn't have.

### No Legend panel — per-field "+ terms" popovers instead

Legend is a per-field, on-demand "+ terms" popover on Camera, Lighting, Transition in and Transition out. "There is no Legend panel anywhere."

**Why.** Rejected as a standing panel; terms are surfaced where they're used rather than in a separate region competing for shell space.

### Standalone desktop app — not the preferred direction

The suite-wide standalone-app question is explicitly low-priority and not the preferred direction. "The question is the whole app, not the Loom."

**Why.** Framing matters: nobody should re-open this as "should the Loom be standalone?" — it is a whole-suite question, and the answer today is no/low-priority.

### The Descent — shelved

The Descent achievement is deliberately shelved.

**Why.** The doc records it as a deliberate shelving with no further reason given — capture so it is not re-proposed as an oversight or a gap in the roster.

---

## The design pass — the owner's answers, 2026-07-27

*A five-way sweep of the docs produced ten candidate open design items; the owner answered all of
them in one pass. Five CLOSE here. Recorded so the next survey does not re-open them — an
unanswered item gets re-derived, and re-derivation of settled state is the specific failure this
tracker exists to stop.*

### Deep Focus — CLOSED as a design question, with one real gap underneath it

Owner: *"Deep focus looks AMAZING since the update... I am very happy with the look and size."*
The 2026-07-26 wrapping change (frames wrap at a larger size instead of being divided into the old
width) settled it. **Do not restyle Deep Focus.** There is no open width question.

Two follow-ups survive, and neither is a restyle:

1. **Imported shots land with no first or last frame — SHIPPED 2026-07-27.** A shot card built
   from an already-produced, imported video rendered correctly (thumbnail, `I2V 15s`, `IMPORTED`,
   `DONE`) but its endpoint frames were empty, because nothing ever produced them: the video
   arrived finished rather than being generated from a start frame.

   Fixed by `/api/loom/import-frames` + `importedFramesPatch`. Three facts found while scoping it,
   worth keeping because they are not obvious from the names:

   - **`extract_last_frame()` is a general frame primitive.** `at_seconds=0.0` takes its
     explicit-seek branch and yields the FIRST frame; `None` keeps the EOF-relative path. No new
     extraction code was needed, and nothing should be written that duplicates it.
   - **A thumbnail is mandatory, not decoration.** `/thumbs/<id>.jpg` serves straight from disk
     with no fetch-on-miss, so an uploaded frame without a thumb renders as a blank box with a
     perfectly good media id behind it.
   - **Both frames are UPLOADED, not just saved locally.** Free, and it makes them real media
     ids, so an imported clip's closing frame is a valid continuity hand-off into the next shot.
     A display-only still would have looked identical and failed the first time anyone chained
     off it.

   The card lands instantly and the frames fill in asynchronously — landing the footage is the
   Footage tab's whole action and ffmpeg plus two uploads take a second or two. Partial success is
   a real outcome and is returned as one.
2. **Small shot cards could be taller — SHIPPED 2026-07-27, and it was not cosmetic.** Filed as
   a nicety, but measuring it showed a real crop: `.lv-cframe` was 48px tall inside a card whose
   content width is 144px at the narrowest column, and `object-fit: cover` therefore threw away
   ~40% of the frame's height. A 16:9 frame needs ~81px at that width; the owner's own 2048x1072
   clips need ~75px. Now 80px, guarded by `loom/test/loom-board-card-frame-height.test.js`, which
   asserts the height against the column geometry rather than freezing a magic number — 48px
   looked perfectly deliberate until it was measured against the card.

   Sequencing note worth keeping: this was only visible AFTER (1) shipped. An empty frame slot
   and a frame cropped to a middle band look the same when there is no frame to crop.

### Publish — the capture may already exist; read before capturing again

Owner: the publish screen and the train-LoRA pages were likely grabbed in a Chrome dive over the
2026-07-25 weekend. `createArtworkFromTaskV2` (`taskId`, `input: CreateArtworkFromTaskInput!`) is
already recorded in `private/API_OPERATIONS.md`. **So the next step is reading what we hold, not
another capture run.** Only if the input type's fields turn out not to be enumerated does a fresh
capture become necessary. Where Publish lives and how it is gated were already decided; the open
part is only the screen behind the (already present, already disabled) button.

### The Loom's video button is renamed "Render" — DECIDED

Two buttons in the Loom's top bar both read "Export". The one that renders and stitches finished
shots into a single video becomes **Render**; the one that saves project files keeps **Export**.
Owner's call, owner's voice. Small enough to ride any Loom commit.

### Rewards do not map across all 57 achievements

Owner: *"Not all 57 get a reward — only a select few, most of which are active, banked, and 1
broken."* **There is therefore no ladder-wide reward rule to invent**, which is what the survey
assumed when it called this an open brainstorm. The work is finding the one broken reward, not
designing a scheme for 57.

### The Loom gets Moonglade branding and a Mark — on a much thinner banner

Owner wants the branding system and a Mark on the Loom, using a **deliberately much thinner banner
image so it does not hog space** — the Loom's header is a working surface, not a lobby. This is
the second of the two art gaps named on 2026-07-06 (the badge half is finished).

**Decide the ratio before any art is generated.** The banked banner rule (1920×480, 4:1, composed
subject-left) does not cover a slim variant, and generating against an unstated ratio is how art
gets made twice.

### "Under the Hood" — gated on bundling the assets and clearing the branding folder

Owner: it *"still needs flushing out and is gated on bundling the assets and clearing the branding
folder."*

**The trigger itself is correct and does not need replacing.** `branding/` is gitignored and
`list_marks()` documents itself as *"Empty on a fresh install (assets are machine-local)"* — so
the folder holds only what a user put there, and the achievement fires on exactly that. Bundling
the default assets somewhere other than `branding/`, and clearing that folder, is what preserves
this property; it is the fix, not a hazard.

*(A 2026-07-27 survey pass claimed the opposite — that shipping defaults would arm the
achievement for every user. It was wrong: it missed that the folder is gitignored and cannot carry
shipped defaults. Deleted rather than annotated; noted only because the wrong version briefly
reached a commit message.)*

### Community — enumerate PixAI's news and notices first, then scope

Owner: *"We need to enumerate their news and notices if possible and scope this for the community
items already placeheld."* So the next step is a **read-only enumeration** of PixAI's news/notices
surface, and only then a scope against the placeholders already in the app. This also answers the
survey's objection that PixAI's events carry no "who": if a notices surface exists, it may carry
the identity the raw event stream lacks. Nothing gets designed before that probe runs.

### Open, LOW PRIORITY: more Loom previews and placement, owner to walk it

Owner, 2026-07-27, right after the board-card frame height landed: there are *"some other
previews and misc placement items to discuss in the loom"*, explicitly **lower priority**.

**Nothing is scoped yet, and nothing should be guessed.** No list of likely candidates belongs
here — inventing one is the manufactured-need failure mode, and it would also pre-empt the
walkthrough that is the actual next step. The note exists so this is not forgotten, not so it can
be worked on.

Two pieces of context that make it easier to pick up cold:

- This is **not** the Loom visual pass, which is closed — V2 got a full mock when the Edit Bay
  and Loom V1 were retired, and the owner is happy with it, iPad included. This is a narrower
  set of follow-ups on top of a surface he likes.
- The two frame items settled the same day are a useful precedent for how these tend to go: both
  were filed as cosmetic niceties and one turned out to be a real 40%-of-the-frame crop that only
  measurement exposed. So when this conversation happens, **measure the thing against its
  container before agreeing it is cosmetic** — and equally, before agreeing it is a bug.

### Two items are CLOSED outright

- **The lost unlock-toast animation is live again.** It was found and restored from a long-lost
  artifact. The survey listed it as needing the owner to describe the motion; that is stale.
- **The Loom's visual pass is done.** V2 received a full visual mock when the Edit Bay and Loom V1
  were retired. Owner: *"Its honestly pretty solid overall... I like it, especially on iPad."*
  Possible follow-up beyond branding only — not a pass, not a restyle.

### Known defect surfaced by the same sweep: Completionist cannot be earned

`Completionist` requires every non-feat, non-banner achievement. Two achievements hang off the
**deleted Enhance surface** — `enhances` (common) and `enhance_workflows_distinct` (epic). Both
are non-feat, so both sit in the required pool, and neither metric can ever increment, because
Enhance never dispatches for an API-key client. **The top of the ladder is therefore unreachable
by anyone.** Recorded here as a defect, not a design item.

## Design sources

*Mockups and artifacts that are the pixel source of truth for a surface. A visual build verifies against the named source — never against prose.*

### Moonglade Model Deck (mirror)  ·  *2026-07-11*

https://claude.ai/code/artifact/9f16f42d-2541-4dd9-935a-0f9d0f39c7c4 — the model research deck. MIRROR — the original MODEL_DECK_2026-07-11.md was deleted from the repo with `docs/archive/` (2026-07-27); the surviving copy is on the owner's Desktop `Moonglade MD archive/MODEL_DECK_2026-07-11.md` (and in git history). Dated external research — re-verify before relying on.

**Why.** Keeps one truth for model research and flags it as time-sensitive external data rather than settled fact.

### Cast-row picker + panel width (LOCKED)  ·  *2026-07-18*

https://claude.ai/code/artifact/d868e4fe-a376-4886-bd5e-1efa4c667472 — interactive mock built from real tokens/components: a per-row gallery-picker icon on Cast & Assets rows, and a Generate panel width slider showing the 6-slot reference grid reflow. LOCKED 2026-07-18, owner-approved with exact values: icon 38×32px matching the thumbnail slot and placed FIRST in the row; panel width 560px. Shipped.

**Why.** Records the owner's chosen numbers (38×32, first-in-row, 560px) so the reflow and icon placement are not re-derived or re-argued.

### Locked design sources referenced in this slice (no ids recorded)  ·  *2026-07-18*

Two owner-approved pixel sources are cited in lines 1-400 of the deleted doc but NEITHER carries an artifact id or URL there: (1) a live slider mockup used to pick the Generate drawer's 560px width, and (2) a locked interactive Artifact mockup used to approve the per-row gallery-picker icon on detailed cast rows (38×32px, first in the row). Both belong to the 2026-07-18 design-mockup pass.

**Why.** Recorded so the approvals aren't mistaken for prose-only decisions — but the artifact ledger entries themselves must be recovered from elsewhere, since this section named the mockups without identifying them.

### Loom Convergence Mockup v3 (LOCKED)  ·  *2026-07-18*

https://claude.ai/code/artifact/e6659d99-8376-400a-a4e5-04a3419d4ca4 — the side-by-side Gallery|Loom source of truth: ONE shared drawer; Loom-only shot chrome (Continuity / Camera / Lighting / Transitions / Cast) kept; a live per-model mode-gating demo; Camera and Basic/Professional deliberately HIDDEN in the Loom because the shot's own Camera field and the Draft toggle own them. LOCKED 2026-07-18, owner-approved and interactively verified. Gating, labels, model order and the Mode/Duration/Audio control removals all shipped from it; the Prompt-textarea half remains deliberately held back by owner choice.

**Why.** Settles the gallery/Loom convergence question — shared drawer, but with named Loom-only chrome retained and named controls suppressed to avoid duplicate ownership. The withheld prompt half is an owner choice, not an unfinished task to "fix".

### Video Tab — Full Parity Mockup v1 (LOCKED)  ·  *2026-07-18*

https://claude.ai/code/artifact/74ad3fd0-ff82-4430-bfe5-275194afa556 — pixel source of truth for the generate drawer's Video form on BOTH mounts (gallery + Loom): 6 image + 3 video + audio reference slots, negative prompt, channel (ships default Normal, persisted), the full model roster with capability tags, and the Loom shot-weave. LOCKED 2026-07-18, owner-approved; the full-parity build verifies against it.

**Why.** Owner-approved parity target for the video form — the source that settles slot counts, the persisted channel default, and roster presentation.

### Web Import — Drop-zone Mockup v2 (LOCKED)  ·  *2026-07-20*

https://claude.ai/code/artifact/066d181e-1a6e-4f84-97c6-6e2b91c6f90d — pixel source of truth for web import: drop zone + browse; ADAPTIVE populated states (thumbnail review when few, a capped 24-tile preview when many — the IMPORT is uncapped, the cap is only on the preview); folder/zip SUMMARY CARDS, never N rows; dupe-by-content-hash skip; add-to-collection; source='local' into the imported/ folder. LOCKED 2026-07-20, owner-approved, PREVIEW_CAP=24. Open per-build calls left deliberately: the cap number, folder recursion, structure→collections.

**Why.** The cap-is-preview-only distinction and the never-N-rows rule are the two things most easily broken by a well-meaning re-implementation. Also names what was intentionally left open rather than decided.

### Canonical achievement roster and preserved pre-57 badge originals  ·  *2026-07-22*

The canonical roster is the committed 57-achievement roster JSON in docs/, with an art candidate assigned to every entry. Badge and mascot art serves from the D: branding tree. The pre-57 badge originals are preserved, unserved, in a backup folder under badges/.

**Why.** One canonical roster prevents a second hand-maintained id→name map; the pre-57 originals are kept rather than deleted because the roster expansion re-assigned art and the earlier pieces may still be wanted.

### LOCKED pixel source: the owner's own Figma Make export for the Folio redesign  ·  *2026-07-22*

The Folio's All-tab redesign (auto-rotating carousel of the active ladder's tiers, a ladder-badge selector row for all 10 tracks, the selected ladder's tiers as cards, then every ladder grouped under a glowing pill divider, then Milestones/Masteries/Feats the same way) was built from the owner's own Figma Make export, itself built partly from the legendary/feat frame slice values handed off earlier that night. Its tier-triad colors were confirmed byte-for-byte identical to what the unlock toast already shipped.

**Why.** This is the pixel source of truth for the Folio — visual builds require a pixel source, never prose. Note it is HIS export, not a Claude-authored mockup: an earlier Claude-designed carousel was rejected, his own carousel model was not.

### Picker capture reference material (screenshots, recordings, diagrams)  ·  *2026-07-25*

The live-capture reference set for the picker work lives at `C:\Users\gwilkins\Desktop\Screenshots for Moonglade refs`, along with as-yet-unread screen recordings (`Model-lora picker`, `Loom issue`) and a `diagrams/` folder. These screenshots are the visual source for the picker's tabs, sort/filter vocabulary, selected-LoRA panel and the grey "No Cover" tiles.

**Why.** Off-repo material that no grep will ever find; named so the picker work has a pixel/behaviour source instead of prose, and so the unwatched recordings aren't forgotten.

### Captured LoRA-training input shape and validation rules  ·  *2026-07-26*

Input fields (inner names read from the training page's own chunk, since the input types are in the schema not the document): baseModelId (required), mediaIds (the dataset), title (required, length >= 1), type = UserMultiLora, triggerWords, primaryLoraModelId (set when retraining FROM an existing LoRA), trainingTaskId (set when reusing a previous dataset), category, kaisuukenId (the free card). Validation rules read off their code, not inferred: under 10 dataset images is rejected UNLESS a previous training-task id is set, so reusing a dataset waives the ten-image minimum; max 100 images; submit is blocked while any image is still uploading; trigger words empty is rejected, over 256 is rejected, and under 30 characters is rejected when the model architecture is MMDIT26 — that is the "Tsubaki.2 needs a 30-character trigger word" rule, enforced per architecture. Price tiers in their own precedence order: free-to-train wins at 0, then dataset reuse price, then retrain price, otherwise base price. Failure returns INSUFFICIENT_BALANCE; success returns a ref id (the new model's id) and their site navigates to that model page.

**Why.** This is external captured spec, not in our repo — deleting it means paying a page-and-bundle capture (or a credit) to learn it again. The waived minimum and the per-architecture trigger-word length in particular are non-obvious rules that would otherwise be re-derived by hitting errors.

### Generation Flags scoping survey (recovered records)  ·  *2026-07-26*

A 76-record scoping survey exists: 38 flags already possible today, 18 small additions, 9 needing a new dependency, 11 not feasible. Recovered from workflow `wf_8cba73eb-ff2`; full records saved alongside that pass. Headline findings worth not re-deriving: the **aesthetic-score flag is already built end to end and 0% populated**; roughly **54%** of the library is already-known near-duplicates answerable in plain SQL; **43,072 CLIP vectors** already exist on disk as raw material.

**Why.** The survey is expensive to redo and its headline findings change what the work IS (a population problem, not a build problem, for aesthetic score; SQL rather than ML for near-dupes). Keeping the workflow id so the full records can be found.

### Mobile Gallery — working port of the Figma Make mock, parity pass done (2 rounds)  ·  *2026-07-27*

https://claude.ai/code/artifact/e0ce50a0-2475-48e2-adc0-efceee17d518 — the phone layout and pixel source for the mobile design pass: 3-tab shell (Gallery / Create / Control), 5 skins, 160px stats hero, 2-column staggered grid, lightbox, and the full Control tab. Status: Current DIRECTION for the mobile pass, still NOT locked — locking is the owner's call. The local copy is git-ignored, so THE ARTIFACT IS THE DURABLE COPY.

**Round 1.** The parity gap this entry used to describe is closed: Create now has the real Mode (quality-tier select) / Seed / Boosters (Face Fix, Quality Tag, Enhance Details + its Ratio/Denoise disclosure) / LoRA row with architecture-aware weight ranges (DiT 0–1.2, SD/SDXL ±2) and a red incompatible-architecture warning; the video sub-tabs were corrected to the real three modes (First Frame / First & Last Frames / Multi-Reference) with a conditional End Frame slot and a condensed multi-reference note (real desktop is 6 image + 3 video + audio slots individually — condensed here); the lightbox gained an Upscale flyout (Method segment, Ratio slider, cost) and a full-screen Art Filters take-over (12 filters, Moonglade-then-PixAI grouping, Strength/Angle); a Job Tracker FAB + tray covers every real state including the rare `total`-bearing progress bar; and a Models & LoRAs picker sheet (tabs, source row, sort chips, category/model-type chips) backs the new "+ Add LoRA" button.

**Round 2.** Round 1 verified only headlessly (Node, no browser) and scoped research to the specific gaps this entry named — both were mistakes, caught by the owner. The real top-level page header/nav (moonglade_gallery.py ~5147-5226) had never been looked at at all: it carries Generate / Import / The Loom / Achievements ("The Folio of Honors") / Contests / My Art / Panel entry points plus an account balance chip, and its own real ≤480px collapse (one row, nav becomes a horizontal swipe strip) — ported here rather than invented. All of it is now in the mock, using the real button labels/icons and real screen structure for each (Import: drop-zone + adaptive preview, cross-checked against this doc's own locked Import mockup entry; Achievements: tier ladders/milestones/masteries with the real cloaked-Feats behavior and real tier hex colors; Contests: read-only, links out, no entry/voting UI, matching the real app; My Art: views-led stat ordering). The Loom is explicitly LINKED, not omitted and not rebuilt for mobile — the real desktop CSS hides it below 480px, but the owner confirmed it already works well in landscape and only wants a link; a mobile-specific Loom redesign is deliberately deferred to much later. Verified this time by actually loading the published artifact in an authenticated browser (Claude in Chrome) and clicking through every new screen, not just a headless render check — a real bug (full-screen panels spanning the whole preview window instead of staying in the phone-width column) was caught this way and fixed. One more correction landed the same day: an earlier pass had put the skin switcher in the header and called that placement "deliberate" without ever actually asking the owner — it wasn't. Skins switch on the Control tab in the real app; the mock's switcher moved there too, and the header lost the toggle entirely.

Known gaps, deliberately not guessed at: video-tab boosters/seed/LoRA parity was never confirmed against the real app. The picker's Models tab has no sample data (LoRAs tab does). The 5 ESRGAN upscaler names and the sample LoRAs/achievements/contests/art posts are plausible stand-ins (same convention as the mock's existing MODELS_IMAGE list), not captured exact values. The Folio's Statistics tab and its full 57-item roster weren't built — a representative subset stands in.

**Why.** Records that the "parity first" blocker this artifact carried is resolved (twice — round 1 missed a whole layer), exactly which surfaces still don't have confirmed real-app data, and the verification method that actually catches layout bugs (load it for real, don't just check it doesn't crash) — so a future pass doesn't repeat either mistake.

**Handoff, same day, machine boundary:** next work is swapping real gallery thumbnails and real branding (logo/banner) into the mock in place of the gradient-placeholder tiles and the static "M" mark — the owner wants it, and confirmed real images are fine to embed (his own private artifact, his own content). Artifacts have a strict CSP that blocks remote image loads entirely; embedding has to be `data:` URIs baked into the HTML, so this means picking a modest sample (not literally thousands), resizing/recompressing each with Pillow (confirmed installed) before base64-embedding, or the file balloons. **Do this from the D: install, not a C: checkout** — the owner named D: "the master of masters": ~35k images and full real branding assets live there, versus a given C: checkout's `pixai_backup/` which is a smaller, older, machine-local partial backup (this session's own C: checkout had only 5,668 thumbnails and zero branding files anywhere). Consistent with the standing D:/C: dual-checkout rule above: read from D: for source material, never mass-edit to "reconcile" the two. Separately, still unresolved: the owner said "I'm iffy about the top" about the header (round-2 rebuild) but the session ended before what specifically was wrong got asked — ask directly, don't guess a fix and hope it lands.

### Other captured facts from the LoRA training page  ·  *2026-07-26*

Model Theme offers Illustrious-v1.0, NoobAI XL, Hinata v2, Illustrious-v0.1 and more. Dataset sources are upload, import from generation history, or reuse a previous dataset. Rebates go up to 5% of credits when others generate with your LoRA. Membership grants 3 / 5 / 10 free trainings per month for Starter / Plus / Premium.

**Why.** Captured surface facts about their product that our code cannot answer. The rebate is also the reason notifications were wanted — it is how you learn someone used your LoRA.

### Their site sends video fields we do not (unprobed)  ·  *2026-07-26*

From the same task dump: their website sends width/height (1536x864), a channel value of "private", and an empty lora object. (A clause here previously read "it OMITS the audio-generation fields we always send" — stale: we stopped always sending them the same day, `VIDEO_AUDIO_MODELS`, commit c8724b5.) CLOSED 2026-07-28: all three unsent fields are captured, every real task renders without them, and the builder's false "there is NO channel field" docstring is corrected — the only further test would be a paid submit A/B nothing is asking for. A spend, not a probe.

**Why.** Measured evidence off a real task, not inference. Kept so the false in-code assertion isn't trusted again and so the discrepancy isn't re-discovered from scratch.

### Badge Prompts v2 (parked mirror)

https://claude.ai/code/artifact/771f84d9-cacb-4f5c-8300-9c8575fb8431 — the badge prompt system. PARKED mirror; the live home is docs/ART.md §5. The original badge_generation_prompts_2026-07-16.md was deleted with `docs/archive/` (2026-07-27); a copy survives on the owner's Desktop `Moonglade MD archive/`.

**Why.** Prevents the parked artifact being edited as if it were the live prompt bank.

### Chibi Library · assign uses

https://claude.ai/code/artifact/1998636d-9043-41e8-900d-797c67fd04f2 — chibi browser + use assignment. LIVE.

**Why.** Live surface for assigning chibis to uses; the picks live in the tool, not in code.

### Cohesion Map

https://claude.ai/code/artifact/4229e98c-4ac3-4e86-820a-72a57465c066 — the top-down app map. LIVE.

**Why.** The one whole-app view used to keep features extending a single product rather than landing as drop-ins.

### Curation Workspace (reference builder)

https://claude.ai/code/artifact/ef9f5853-5c8f-40eb-87f2-8cf123f0b6ef — reference builder: lightbox + pick + rank + tray + export. CLONE THIS for new selection passes.

**Why.** Standing pattern for any future curation/voting pass — don't build a new voting UI from scratch, clone this one.

### Feat badge prompts — gunmetal (parked)

https://claude.ai/code/artifact/73372456-f09c-418c-920b-3e139988ef91 — 11 feat badge-art prompts. PARKED — owner: "maybe when credits allow."

**Why.** Parked on COST, not on quality or direction. It resumes when credits allow; nobody should re-pitch the concept or assume it was rejected on merit.

### loom_selectshot (LOCKED)

https://claude.ai/code/artifact/0d9c4e02-200e-44f9-982c-e3add482b905 — the selected-shot interaction model. LOCKED, shipped in V2.

**Why.** Source of truth for how shot selection behaves on the board (paired with the gold selected-shot ring in the Shell Mockup).

### Mascot/badge assignment ledger

https://claude.ai/code/artifact/d1ee39a1-db65-487b-a6ef-067ea6d1392d — titled "ledger": the per-achievement mascot + badge assignment. LIVE.

**Why.** The live mapping of which mascot/badge belongs to which achievement — assignments exist only here.

### Moon-phase progress gauge (artifact 812e82b4)

The moon-phase progress gauge, artifact `812e82b4` (only the short id is recorded in the doc), is near-finished-asset quality and enacts the app's own name. Banked as the standout candidate for the themed progress bar.

**Why.** It is close to shippable art and thematically self-justifying (Moonglade), so it should be the first thing reached for rather than regenerating progress-bar art from scratch.

### Moonglade Banners — defaults & unlocks (tags NOT exported)

https://claude.ai/code/artifact/7919cec3-aec7-41d0-8efc-8fb2d0f4cdb5 — the 194-candidate banner board carrying the judging panel's pre-scores (top: #100 and #82, both 19/20). The pre-scores are NOT final picks. CRITICAL: the owner's Default/Unlock tags saved only to the voting browser's localStorage key mg_banner_board_v1 and were NEVER exported back — recover them by re-opening the board in the voting browser and using Export, or re-tag from scratch. Feeds the D-8 banner-unlock work. LIVE.

**Why.** Real owner decisions (which banners are defaults vs unlocks) exist ONLY in browser localStorage. If that is lost the tagging work is lost, and the pre-scores must not be mistaken for the owner's picks.

### Moonglade Roster Board

https://claude.ai/code/artifact/31d6c68a-bd54-4824-886f-9017c6012912 — the 57-achievement three-lane voting board. Votes are complete; it is the MODEL for any new board, which should be built from the owner's off-repo backup of the roster JSON (the committed copy was scrubbed 2026-07-27 — point `tools/build_roster_board.py --roster` at the backup).

**Why.** Records that its votes are done (not re-runnable) while keeping it as the template, and that a new board reads the roster JSON rather than hardcoding entries.

### Moonglade — Finalists In Action

https://claude.ai/code/artifact/b45a39a3-b6a8-4e73-9f62-e03cb390bd00 — finalists shown in context: frames wrapping a real unlock, bars filling live, claim icons in the header chip. Current; pairs with docs/ART.md §3 (the picks ledger).

**Why.** Judging art in isolation misleads — this artifact is the in-context view the frame/badge picks were chosen against.

### The Curation Standard (mirror)

https://claude.ai/code/artifact/6d6b9d2d-281e-4fd5-b1dc-7a11c599950e — the house standard for vote/selection artifacts. Status: MIRROR — docs/STANDARDS.md Part 1 is truth.

**Why.** Artifacts are disposable views, never hand-maintained copies; the doc wins if they disagree.

### The Loom — Shell Mockup v1 (LOCKED)

https://claude.ai/code/artifact/e41a3020-32fb-4baa-ae81-69814d5ee4c9 — the interactive PIXEL SOURCE OF TRUTH for the V2 shell. Contains: left card with Cast & Assets / Footage tabs + Simple/Detailed density + collapse-to-rail; center acts/shots board with a gold selected-shot ring; right Generate drawer with collapse-to-rail and a bound-to-shot chip; the fixed Timeline drawer with its three-state drag; a live "+terms" popover. Status: LOCKED — matches the shipped shell.

**Why.** It is the artifact every V2 shell change verifies against; the Timeline wireframe is explicitly subordinate to it.

### Timeline Drawer — Wireframe v1 (reference only)

https://claude.ai/code/artifact/84be1748-2c7d-4304-967c-8ac22cd37687 — Timeline drawer detail. REFERENCE ONLY; the Shell Mockup is the pixel source.

**Why.** Explicitly subordinate — prevents two artifacts both claiming to be the Timeline's pixel truth.

### toast_mockup (LOCKED)

https://claude.ai/code/artifact/335ef4e7-2459-4c99-990a-b8c5751324c3 — the achievement unlock-MOMENT design (the shipped toast is the .ach-m2 treatment). LOCKED, shipped.

**Why.** Pixel source for the unlock moment — the one piece of celebratory chrome whose feel was designed rather than coded ad hoc.

---

## Decisions

*What was decided and why. The WHY is the part no amount of code-reading recovers.*

### The mount-race lesson held up the very next time it mattered — Lightbox Mobile found a third, differently-shaped instance proactively, and correctly left desktop's own latent copy alone  ·  *2026-08-03*

The entry directly below this one recorded a rule after Image Details Mobile shipped a
mount-race bug missed by two independent passes. The very next build (Lightbox Mobile),
briefed explicitly to check for this failure class from the start, found a **third, newly-
shaped instance of it during the build itself**, not after: `LightboxMobile.jsx`'s `if (!it)
return null` guard can fire on a transient render mid-page-boundary-navigation (`items`
already updated to a shorter page, `index` not yet caught up), tearing down the Upscale host
div underneath a `[]`-keyed mount effect exactly like the original bug. Fixed by keying the
effect to `[mid]` instead, so any real navigation's next valid render recreates it.

Desktop `Lightbox.jsx` has the identical `[]`-keyed effect and, structurally, the identical
exposure — but the build correctly did **not** silently patch it. It flagged the finding
separately (as a real, open question: does desktop's own step() logic actually hit this same
transient window, or does something about its timing avoid it) rather than fixing something
out of this surface's scope on its own authority.

**Why.** Two things worth keeping distinct: (1) a written-down rule changing behavior on the
very next relevant task is the actual test of whether a "general lesson" entry was useful, not
just documentation — this one passed; (2) finding a plausible instance of a known bug class in
a file you weren't asked to touch is a report, not a mandate to fix it there too — `[[feedback-no-unilateral-deviations]]`'s
same reasoning applies to bug fixes outside a task's stated scope, not just design deviations.

### A custom-element mount-once effect must be keyed to when its host div actually renders, not to when the component mounts — the same bug shipped twice, caught the second time only by testing against a real network fetch  ·  *2026-08-03*

Building Image Details Mobile surfaced (and fixed) two real, pre-existing desktop bugs in
`DetailsView.jsx`'s Upscale panel: the host div for the shared `<mg-upscale-panel>` custom
element only rendered once `upscaleOpen` was already true, but the mount effect that creates
the element runs exactly once, immediately after the *first* commit — while `upscaleOpen` is
still false — so the button was silently permanently dead. Fixed (and independently reviewed)
by rendering the host div unconditionally. Both fixes shipped, reviewed, and reported clean.

Live-verifying against the real account afterward (not the build/review's own stubbed-fetch
check) found a **third occurrence of the identical bug shape**, missed by both prior passes:
`ImageDetailsMobile.jsx` has an early-return for its loading state before its main JSX (which
contains the now-unconditional host div) ever renders. On a real network fetch, the mount
effect's one-shot first run still lands during that loading branch — the div genuinely doesn't
exist yet, `upHost.current` is null, the effect bails, and an empty dependency array means it
never gets a second attempt once the loaded content actually paints. Fixed by keying the effect
to `row` (the fetched data) instead of mount, so it re-fires the moment the real content exists;
the existing `firstChild` guard keeps every subsequent re-render a no-op.

**Why this survived two independent review passes:** both the build and the review verified
this exact interaction using a stubbed/mocked `fetch` (unauthenticated dev sessions can't reach
the real backend), which resolves near-instantly — fast enough that the loading branch may
never actually paint before the effect's first run, dodging the race entirely. A real network
round-trip has enough latency to reliably land the effect's first run during the loading state,
which is exactly why testing against the owner's real, live account — not a mock, not a stub —
caught it immediately on the very first interaction.

**The general rule, for every future custom-element mount effect in this codebase:** an effect
with an empty dependency array that reaches for a ref is only ever as reliable as "this ref's
element is guaranteed to exist by the time this effect's first run happens." Any early return
(loading, error, auth-gated, whatever) between the component's mount and the JSX containing the
target div breaks that guarantee — the fix is to key the effect to whatever state transition
actually makes the div appear (here, `row` becoming non-null), never to leave it on `[]` and
assume the first render is the only one that matters. And: a stubbed-fetch live check is real
verification for logic and data shape, but it is not a substitute for at least one pass against
a genuine, latent network call when the code under test is itself timing-sensitive.

### A component's own nested Escape-key ladder is dead code if `App.jsx`'s capture-phase handler already owns Escape for that overlay — verified live, corrected a review's claim  ·  *2026-08-03*

Extracting `ControlPanelOverlay.jsx`'s logic into `useControlPanel.js` (see the entry below)
left one piece behind as component-local: an Escape-key effect meant to close whichever layer
is on top (a sub-overlay first, then the whole Panel), whose dependency array changed from
`[]` to `[power, subOverlay]` as an incidental part of the same diff. An independent review
flagged this as a real, positive, unremarked behavioral fix — a stale closure that used to
always fall through to closing the whole modal, now correctly scoped. Verified live against
the real running app before accepting that conclusion: opened the Panel, opened the Trash
sub-overlay, pressed Escape — **the whole Panel closed anyway**, sub-overlay and all,
contradicting the "fixed" behavior. Root cause: `App.jsx` already registers its own Escape
handler in the **capture phase** (`addEventListener("keydown", onKey, true)`) that calls
`e.stopPropagation()` and closes the entire overlay whenever one is open — by design, per its
own comment ("Esc closes the overlay FIRST — capture beats the drawer's own Esc ladder").
Capture fires before bubble, so `App.jsx`'s handler always wins and the event never reaches
`ControlPanelOverlay`'s own bubble-phase listener at all. The dependency-array change is real
but **functionally inert** — a code-quality improvement to a handler that can never actually
run, not a behavior change a user would ever see. Not a regression either: the observable
behavior (Escape always closes the whole Panel) is identical before and after this session's
refactor.

**Why.** The general lesson: before crediting or reverting any fix to a nested overlay's own
Escape/keyboard handling in this app, check whether `App.jsx`'s outer capture-phase handler
already owns that key for the surface in question — if it does, the inner handler is
observably dead regardless of what its dependency array says, and "verified by reading the
diff" is not the same as "verified by pressing the key." This is why a live check (a real
Escape press against the real running app, not a source read) is what caught the
discrepancy — the same category of lesson as [[feedback-visual-verification]], one layer
removed from CSS into event handling.

### Control's job console checked against the OUTER-tab-switch rule and found a DIFFERENT, equally valid fix already in place — not lifted like VideoMode  ·  *2026-08-03*

The entry directly below this one (same day) named Control's own Sync/Tend job console as the
next surface that needed the outer-tab-switch check applied "from the start." Built
`ControlMobile.jsx` + extracted `useControlPanel.js` (the data layer `ControlPanelOverlay.jsx`
now consumes too, instead of holding a second copy — same "refactor the one place this state
lived" call `useLibrary.js` made for `App.jsx`) and checked explicitly before shipping: does
switching Gallery/Create ↔ Control mid-job stop tracking a real, still-running operation, the
way an unmounted `<mg-generate-drawer>` would? Answer: no, and not by luck. Unlike the video
drawer's `disconnectedCallback` — which actively sweeps every poll timer on unmount with no way
back, forcing that element to never conditionally unmount — `useControlPanel()`'s job-status
poll already re-fetches `/api/panel/status` on every mount and rebuilds `running`/`progress`/
`log` from server truth (this existed before this pass; the mount-time "a job can already be
running" resume check is original to `ControlPanelOverlay.jsx`). These are local maintenance
jobs the header comment already describes as "designed to keep running with no browser tab
involved" — not billed PixAI generations — so unmounting just pauses this component's own
polling, never the job itself, and remounting resumes tracking correctly. `useControlPanel()`
is therefore deliberately NOT lifted above `AppMobile.jsx`'s tab conditional; doing so would
have been reflexively applying VideoMode's fix pattern to a surface that doesn't share its
failure mode. One real, disclosed, NOT-fixed-here gap: the Stop/Restart ping-poll has no
resume-on-mount check on either desktop or mobile — pre-existing, not introduced by this pass,
and not a billing risk (the POST fires once, irreversibly, before any unmount could happen).

**Why.** Confirms the general rule the entry below states — "evaluated against the outermost
switch" — is an evaluation, not a reflex: the right response can be "this surface already has
an equivalent, differently-shaped fix," not only "lift it like VideoMode." Recording which one
applies and why stops a future session from either skipping the check (the failure this rule
exists to prevent) or over-applying VideoMode's specific mechanism where a mount-time resume
already does the same job more cheaply.

### Any mobile surface hosting a paid, poll-tracked task must survive the OUTER tab switch, not just its own internal mode switches  ·  *2026-08-03*

The mobile Create tab's Video mode mounts the shared `<mg-generate-drawer>` element, whose
`disconnectedCallback` deliberately sweeps every outstanding poll timer on unmount — correct
and necessary internally, but only safe if the element is truly never unmounted mid-submit.
The first build got the *inner* half of this right (the drawer survives an Image/Edit/Video
segmented-control switch, mirroring desktop's own "never conditionally unmount" rule) but
missed the *outer* half: the whole `CreateMobile.jsx` component — drawer included — was still
nested inside `AppMobile.jsx`'s `{tab === "create" && ...}` conditional, so switching the
bottom-nav tab to Gallery or Control unmounted it anyway, silently killing UI-side tracking of
an already-charged, in-flight video render (~210,000 credits for a 15s v4.0 render) while the
job kept running and billing server-side regardless. Caught by review before it shipped, not
after. Fixed by lifting the video host out of `CreateMobile.jsx` entirely, up to
`AppMobile.jsx` — mounted once for the app's whole lifetime, visibility toggled by CSS only —
the same "lift state above the switch that would reset it" pattern already used for
`useLibrary()`/`useGenerate()`, just applied to a mounted DOM element instead of React state.

**Why.** The general rule for every future mobile surface: any component whose unmount has a
*side effect beyond losing UI state* — stopping a poll loop on a paid task is the sharpest
example, but a WebSocket, a file upload, or any other real in-flight operation qualifies too —
must be evaluated against the OUTERMOST switch that could unmount it (the bottom-nav tab bar),
not just the more obvious inner one (a segmented control within that tab). A component that
"never conditionally unmounts" one level up can still be unmounted two levels up if nobody
checks. Verified three ways before trusting it: an instrumented reproduction of the bug itself
(proving the failure mode was real, not theoretical), an instrumented proof of the fix (same
harness, same clicks, opposite result), and a live check against the real running app with the
real account. Recording the pattern, not re-deriving it, for Control/hamburger-destination
work still ahead — any of those touching a real job-polling surface (Control's own Sync/Tend
job console, for instance) needs this same "outer switch, not just inner" check applied from
the start, not discovered by review after the fact a second time.

### A live-verification screenshot pane can become genuinely unavailable mid-session, not just occasionally stale — have a non-visual fallback ready  ·  *2026-08-02*

Verifying Setup Wizard Mobile, the sandboxed preview browser's `computer{screenshot}` failed
four consecutive times with "the Browser pane is not displayed, so the page is not
compositing frames" — not the previously-seen staleness/hang pattern
([[feedback-visual-verification]]), a flat unavailability that didn't clear with a wait or an
interaction. The real-Chrome fallback (`claude-in-chrome`) was already known-broken for this
specific session (its `resize_window` reports success without the page's actual
`window.innerWidth` changing — see the Login Mobile entry above). With neither screenshot
path available, verification fell back to direct DOM/interaction checks: confirming the real
`window.innerWidth`/`innerHeight` matched the requested viewport, confirming the mobile
component's real CSS classes were present via `querySelector`, dispatching a real `.click()`
on the "Next" button and re-reading the DOM afterward to confirm the carousel state actually
advanced (not just that static markup rendered once), and reading `document.body.innerText`
to confirm real copy matched the shipped desktop wizard verbatim.

**Why.** [[feedback-visual-verification]] already establishes that computed-style/DOM checks
alone are not a substitute for a real screenshot when one is available — that still holds.
This is the narrower, adjacent case: what to do when NEITHER available screenshot path
actually works, which is different from "a screenshot looked wrong" or "a screenshot is slow."
The honest move in that state is real interaction + DOM confirmation, stated plainly as what
it is (not silently upgraded to "visually confirmed" in a report) — a click that provably
changes DOM state is meaningfully stronger evidence than a static render, even without a
pixel image, and dispatching one costs nothing extra once `javascript_tool` is already in use
for the viewport check.

### Mobile pass scope: installability-only PWA, tablet stays on the desktop layout, architecture is a shared hook per surface  ·  *2026-08-02*

Three owner decisions locked in before any mobile surface was built. **PWA scope is
installability-only** — manifest.json + icons + "Add to Home Screen", no service worker, no
offline caching. Owner's own words: full offline support is "overkill for this app." This
matters because none of the 7 mobile designs actually show a service worker or offline
behavior either — the README calls the suite "PWA-ready" but that claim was already scoped to
installability metadata only, this decision just makes it explicit and closes the question
rather than leaving "should we build real offline support" open indefinitely.
**Tablets/larger screens use the existing desktop layout**, not a scaled-down mobile one — no
tablet design exists in the handoff (all 7 mobile files prove out exactly one 390×844 fixed
viewport), so this avoids inventing a tablet layout nobody designed.
**Architecture: a shared data/logic hook per surface, with separate desktop and mobile
presentation components reading from it**, chosen over three alternatives (pure responsive
CSS on the existing desktop components; fully separate mobile-only components/routes
mirroring the design handoff's one-file-per-page structure; deferring all 7 surfaces and
shipping installability only). A 9-agent survey reading all 7 mobile designs in full found the
same pattern in every one: mobile isn't a reflowed desktop layout, it's a different navigation
idiom (bottom tabs + hamburger bottom-sheet + full-screen push/pop stack vs. desktop's
floating dock + top nav + in-place overlays) wrapped around mostly the SAME underlying data —
5 of 7 surfaces confirmed identical field shapes/API needs to their shipped desktop
counterparts. Pure CSS breakpoints don't cover incompatible nav models; fully separate
components risk desktop/mobile logic silently drifting apart with no data-flow bug fixed in
only one place. The shared-hook approach avoids both failure modes at the cost of an upfront
logic/presentation split per surface — paid once per surface, not accumulated as drift risk
forever.

**Why.** Recorded so a future session doesn't re-litigate any of these three from scratch —
the survey's full reasoning (with the other three options' real pros/cons) is preserved in
this session's transcript and in [[moonglade-handoff-package]] memory, not restated here per
this file's own no-derivable-detail rule. The concrete first build against this architecture
(Login Mobile) is the entry immediately below.

### A build task touching a surface with a real, already-shipped counterpart must name that counterpart, not just hand over the design file  ·  *2026-08-02*

Folio of Honors' click-to-replay interaction was scoped from `Folio of Honors.dc.html`'s own prototype markup, which renders its achievement-earn toast as a small, self-contained ~360px corner card — because a static design prototype has no way to call into a real running app's JS, so its toast necessarily has to be its own standalone mockup, not a pointer to the real thing. The build agent ported that prototype markup as if it were the target. The result was smaller than the real thing, had zero confetti/fanfare, and — worse — never auto-dismissed, sitting open "like a warning" until manually closed. The actual, already-shipped celebration a genuine achievement unlock gets — `_mkMoment()`/`_play()`/`_fanfare()`/`_chime()` in `static/mg-notify.js`, confirmed byte-for-byte matching `Ambient Layer.dc.html`'s own locked ambient-layer spec (badge medallion sweep, mascot pop, ring pulse, tier-colored glow, and on legendary/feat tiers a full 84-piece confetti + 46-star fanfare) — sat unused the entire time, a few files away. The owner caught it live, not a review pass: *"The agents custom built a new achievement engine?"* / *"We need to make sure agents know whats SHIPPED when we assign build. this can't happen."* Fixed by adding one new export, `Ach.replay(achievement, opts)`, to the real engine — reusing `_mkMoment`/`_play`/`_fanfare`/`_chime` unchanged — and rewiring the Folio's replay/ruby-scramble logic to drive that real DOM via a returned handle, deleting the custom toast component outright rather than keeping it as a fallback.

**Why.** The general failure mode: a design handoff file (`.dc.html`) is a static prototype and will always contain a self-contained, simplified stand-in for anything that, in the real app, is a shared runtime system — a celebration engine, a toast queue, a job tracker, anything with its own JS module and its own state. Handing an agent only the design file for a surface that touches one of these lets it build a second, drifting, incomplete copy right next to the real one, because nothing in the design file tells it the real one exists. **Standing rule going forward: when scoping a build task for a surface that has a real, live counterpart elsewhere in the app — a shared engine, an existing API route, an established component pattern — the task assignment must explicitly name that counterpart and its location, and instruct the agent to reuse it, not just attach the design file and let the agent port it blind.** This is the same shape of lesson as "install as specified" governs visible copy/content questions, but for behavior: the design file wins on what a surface *looks like* and *says*; a real shared system already in the codebase wins on how a *shared mechanic* actually behaves, every time.

### Control Panel is a modal, not the page `Control Panel.dc.html` itself specifies  ·  *2026-08-02*

`Control Panel.dc.html`'s own markup says, in its own tooltip text, "the Panel is a page in the suite, not a floating window," and its `backToGallery()` navigates via `window.location.href`. The owner's live, direct correction supersedes that: *"Control panel is now ALSO modal. no separate pages anymore."* `ControlPanelOverlay.jsx` carries the DC's real content (tabs, tiles, Users/Trash sub-overlays, the power modal) but mounts inside the same `.mgv-scrim`/`.mgv-host` shell every other nav overlay uses, launched from the Panel nav pill's `overlay:"panel"` (changed from `href:"/panel"`), not a page navigation.

**Why.** This is a case where the shipped design artifact had gone stale relative to a decision the owner made after it was authored — not a misreading of the file, and not a case for "install as specified" (that rule governs visible content/copy questions on an otherwise-current spec, not a structural fact the owner has since overridden in conversation). Recorded so a future pass reading the DC file cold doesn't "restore" the page-based navigation thinking the modal was an unauthorized deviation from spec.

### A dedicated adversarial backend-contract review is worth running before shipping any large, security-relevant overlay  ·  *2026-08-02*

Before the Control Panel overlay shipped, a 5-dimension review workflow (one agent per sub-feature — Maintenance job console, Users, Trash, Branding, Power — each independently reading both the component and the real backend route code, then a second independent pass verifying each raised finding against the code itself before trusting it) found and confirmed 13 real, concrete, currently-reachable defects in a single pass: a finished job's own output being discarded before it could ever be seen, several backend error responses (LAN 403s, busy-job 409s, "skin locked" 403s) silently swallowed with zero UI feedback, destructive Maintenance buttons rendering from the wrong (unfiltered) action list for LAN sessions, a typed-DELETE confirmation that wasn't scoped to the action it was confirming, a skin picker that updated its own checkmark but never actually retinted the app, and Stop/Restart having no confirmation step at all where classic gates both behind `window.confirm()`. All 13 were fixed in the same pass, before any of it reached the owner.

**Why.** This component touches real user accounts, permanent file deletion, and the server's own process lifecycle (Stop/Restart) — genuinely consequential, hard-to-notice-from-a-demo failure classes (a silently-swallowed 403, a stale cached "unlocked" skin, a confirm dialog that doesn't snapshot its own selection) that a single careful build pass reliably misses, because they only show up when you deliberately go looking for "what does the client do when the server says no" rather than "does the happy path work." The pattern is worth repeating for any future surface with this shape: real accounts, real destructive actions, real process control. It is not a substitute for the live E2E test against real routes (`tests/test_render_harness.py`) — that test proves the happy path and a couple of real failure paths actually execute; the review pass is what surfaces the OTHER failure paths worth building tests for in the first place.

### `config.json`-writing test fixtures must redirect BOTH path mechanisms, not just `core._config_path()`  ·  *2026-08-02*

Most of this app's config-touching code reads/writes via `core._config_path()`, and every render-harness/test-client fixture that needed an isolated config redirected exactly that. `/api/setup/save-key` does not: its own docstring explains it deliberately builds `cfg_path = Path(core.__file__).resolve().parent / "config.json"` instead, specifically so key-validation never consults the module-cached `core._cfg` a normal call would prefer. `tests/test_setup_wizard.py` already carries a dedicated `_redirect_config_to()` helper for exactly this reason. A new render-harness fixture for the Setup Wizard, written by copying the OTHER fixtures' `core._config_path()` pattern instead of reaching for that existing helper, missed it — and a real Playwright test's fake key landed directly in the actual checkout's real `config.json`, silently overwriting the owner's real `PIXAI_API_KEY`. Caught immediately by checking the file after the test ran (not by the test itself, which had no way to know), but the real key value could not be recovered — nothing had ever captured it — and the owner had to obtain and re-paste a fresh one.

**Why.** The general rule, for any future fixture that needs an isolated `config.json`: **grep for `core.__file__` before assuming `core._config_path()` redirection is sufficient** — this app has two distinct, independently-used path-resolution mechanisms for the same file, and a fixture that only redirects one is not actually isolated for routes using the other. `tests/test_setup_wizard.py`'s `_redirect_config_to()` should have been reused verbatim rather than re-derived from a different fixture's pattern; a helper that already exists for exactly this problem is the thing to search for first, not the thing to rediscover the hard way against a real file.

### An unauthenticated React page needs its OWN shell, not the authenticated one  ·  *2026-08-02*

`/login`'s GET (the common case: a real account already exists) serves a new, deliberately minimal `LOGIN_PAGE` template instead of reusing `next_gallery()`'s `NEXT_PAGE` verbatim, even though both mount the exact same `app.js` bundle (`main.jsx` statically imports both `App` and `LoginPage`, so Vite ships one file either way). `NEXT_PAGE` loads 8 `<script src="/static/mg-*.js">` custom-element files (pickers, cost badge, generate drawer, upscale panel) that only the authenticated gallery needs — and none of those files were ever on the public allowlist, because nothing unauthenticated had ever needed them before. Reusing `NEXT_PAGE` for the login page literally shipped a 401/302 loop for every one of those 8 requests: an unauthenticated caller's `<script src>` fetch got bounced back to `/login`, the browser tried to parse the HTML redirect body as JS, and the whole bundle died with "Unexpected token '<'" before React ever mounted — caught live in a Playwright run, not by reasoning about it. Fixed by giving the login page its own minimal shell (skin script, 401 guard, `app.css`, boot script, `app.js` — nothing else) and adding only `/next/assets/` (the bundle itself) to the public prefix list, not the 8 component scripts.

**Why.** The general lesson, for the next unauthenticated React surface (Setup Wizard's own key-entry step will hit this too): don't reuse the authenticated shell's asset list for a page an anonymous visitor can reach. Either give it its own minimal shell (this fix), or audit every `<script src>`/`<link href>` the shared shell pulls in and confirm each one is genuinely on the public allowlist before shipping. The failure mode is silent in dev (an already-authenticated browser tab never notices — every one of those requests just... works, because the session cookie is already valid) and only shows up for a genuinely logged-out visitor, which is exactly the case manual testing is least likely to cover by accident.

### `no_accounts`, not `bootstrap_mode`, is the switch for "does the classic login form still apply"  ·  *2026-08-02*

`/login`'s GET branches on `no_accounts` (any account exists at all) to decide whether to serve the React LoginPage shell, NOT `bootstrap_mode` (`no_accounts AND is_local`). Those two conditions differ for exactly one state: zero accounts, non-local request — a LAN device hitting a fresh, not-yet-bootstrapped install. `bootstrap_mode` is already false there (correctly refusing the create-account form to a non-local caller), but there is STILL no account to sign into — a React sign-in form in that state would be functional nonsense, submitting credentials against an account that doesn't exist with no path to create one. That state keeps the classic "no account has been set up yet, ask whoever runs this server to sign in from the machine itself first" safety message, same as bootstrap_mode's own local case — neither has a design yet (see `design_handoff/request-bootstrap-account-creation.md`), and both are about to change together whenever that design lands.

**Why.** `bootstrap_mode` reads like the obvious switch (it already gates the ONE other special login state), and using it here was the first, wrong instinct — it would have quietly shipped a broken sign-in form to any LAN device that discovers a not-yet-configured install before the owner bootstraps it, a state that is rare but not impossible (a fresh server on the LAN before its first local sign-in). Caught by tracing what `test_login_page_shows_safe_message_for_lan_request_when_no_accounts` was actually asserting, not by design review.

### `Frontend Gallery.dc.html` bundles seven overlay designs, not one — enumerating the handoff by FILE undercounts it  ·  *2026-08-02*

A survey this session (via a delegated workflow) enumerated the design handoff by treating each `.dc.html` file as one surface, and reported My Art/Publish/Train/Import/Contests as having **no design at all** — "not even in the design handoff's 18-surface canonical list." That was wrong, and the owner caught it directly and forcefully: all five are real, complete designs, sitting as nested `sc-if value="{{ ovXxx }}"` overlay blocks **inside** `Frontend Gallery.dc.html` itself — the same file the audit chain had already opened for other reasons (Health's overlay came from it) without ever checking whether it held more than the main grid. `Frontend Gallery.dc.html` alone contains Health (shipped first), `ovMyArt` (567-599), `ovPublish` (288-358), `ovTrain` (360-484), `ovContests` (601-645), `ovImport` (723-763), plus `<dc-import>` references to Duplicate Review and Folio of Honors as further overlays reachable from the same gallery. The file's own `NAV_OVERLAY` JS map (`{'My Art':'myart','Contests':'contests','Health':'health','Publish':'publish','Train':'train','Import':'import'}`) matches `NavSpine.jsx`'s real overlay-key convention exactly — the design was never ambiguous about where these mount.

**Why.** The general lesson, for any future design-handoff survey: **a `.dc.html` file is not the unit of "one surface."** A single file can bundle a main view plus N nested overlay states, each independently complete, gated by its own `sc-if`. Enumerating "surfaces built" by counting top-level files will silently undercount every time a design nests multiple states in one prototype file the way this one does. The only reliable check is to open each file and grep for `sc-if value="{{ ov`-style blocks, not to trust a file list. This session also confirmed, once corrected: the owner's manually-provided Desktop zip dumps are the sole trusted source for this project's design handoff — DesignSync/the claude.ai Design project tool has failed to locate files repeatedly and should not be used for this project going forward; when the owner hands over a zip, that supersedes whatever a prior sync round found.

### A component's own success confirmation must not be gated behind the input state the success itself clears  ·  *2026-08-02*

`ImportOverlay.jsx`'s first pass rendered its `files.length === 0` check as the switch between "empty drop zone" and "everything else, including the result banner." `doImport()` clears `files` on a successful response (nothing left to show once it's imported) — so the instant an import succeeded, the view fell back into the `files.length === 0` branch and the confirmation banner it had just set never painted. The server-side import was completely real and correct; a live Playwright test caught the UI silently swallowing its own success message (`.mgim-result.ok` never appeared, 10s timeout) before any human saw it. Fixed by branching on three explicit states — empty / staged / done — rather than deriving "done" implicitly from an input array that a successful submit is expected to clear.

**Why.** The general shape to watch for in any future overlay/form: if a success handler clears the state that ALSO drives which branch of the render renders, the confirmation UI can end up gated behind a condition the success path itself just made false. Whenever a submit handler resets its input state on success, check that the confirmation view's own visibility does not depend on that same state still being non-empty.

### Completions route by the shot id captured at submit time  ·  *2026-07-18*

A generation completion handler routes via the shot id captured at submit time, not whichever shot happens to be selected when the result/error event fires. The drawer's prompt/image/video/audio reference slots CLEAR (not just overwrite) when the newly-selected shot/draft has none.

**Why.** Switching shots mid-render used to attribute the finished clip to the wrong card, and switching from a shot with cast refs to an empty draft left the previous shot's images sitting in the drawer, ready to submit against the wrong generation.

### Elapsed time alone never marks a generation failed  ·  *2026-07-18*

A shot only enters a terminal status:"error" on a real server-reported failure — elapsed time alone never does. Both independent poll loops escalate through three tiers instead: 20min downshifts cadence and shows "Taking longer than expected"; 90min downshifts further and shows "Still going after Nh — unusual"; a 6h ceiling stops that tab's polling but leaves status/pendingTaskId untouched (genState phase "paused"). A reload, or clicking the card's own "paused" badge, always grants a fresh budget.

**Why.** A slow-but-alive render is indistinguishable from a dead one by clock alone, and wrongly branding it failed destroys a real in-flight generation's tracking. The ceiling protects against a permanently wedged/deleted task without asserting failure. The multi-hour escalation was verified by code review plus the adversarial-review pass, not literally clocked in real time.

### Mode and Continuity "First→Last" are coupled  ·  *2026-07-18*

A shot can no longer show Continuity "First→Last" while Mode is something other than FLF — the two controls are coupled.

**Why.** Only mode==="FLF" ever made the close frame reach the real generation. Left uncoupled, this silently dropped the close frame with no error — confirmed in a real production generation. A known defect since the original Loom audit that was never tracked past the old roadmap doc.

### Per-row gallery picker on detailed cast rows — additive, and no audio picker  ·  *2026-07-18*

Each detailed cast row has its own gallery-picker icon, 38×32px (matching the thumbnail slot's size), sitting FIRST in the row. It opens the shared gallery picker filtered to that row's kind and sets the row's mediaId directly, creating no new row. Audio rows get no picker. This is IN ADDITION to the existing local-file-upload thumbnail (image rows) and the two unchanged bottom buttons ("+ add from gallery" / "⇣ Import collection") — nothing was replaced.

**Why.** Owner-approved against a locked interactive Artifact mockup in the 2026-07-18 design-mockup pass. Audio rows have no picker because there is no gallery of audio clips anywhere in the app.

### Prompt textarea deliberately excluded from the shared-component migration  ·  *2026-07-18*

The Loom's Prompt textarea is the one piece of the Convergence Mockup that was NOT migrated to a shared web component — it stays a plain React `<textarea>`, and the ledger records the reason as "held back by owner choice." Consequence that must be preserved with it: there are deliberately TWO write sites for a shot's base prompt (the right panel's Prompt field and Deep Focus's matching field, same placement in both — after Mode/Duration, before the frames), each clearing an active prompt override the instant the owner types there. The Generate drawer's own composed-prompt box is a separate thing and only ever writes the frozen override.

**Why.** Everything else in that locked mockup shipped, so an audit reading "one half remains" will read this as unfinished migration work and finish it. It is not incomplete — the owner chose to stop there, and the two-write-site shape is intentional rather than duplication to consolidate.

### The Generate drawer is mounted once, permanently — CSS-hidden, never unmounted  ·  *2026-07-18*

<mg-generate-drawer> is mounted once, permanently, in the Video tab's DOM and CSS-hidden on other tabs instead of being conditionally unmounted.

**Why.** Switching tabs mid-render used to kill the drawer's in-flight poll outright, stranding the shot at "wip" forever. This is the general rule for any surface that owns an in-flight poll: hide it, don't unmount it.

### Deep Focus preview size is a width question, not a number bump  ·  *2026-07-21*

Owner, 2026-07-21: Deep Focus previews are too small to read what you attached — a frame or an @tag reference is often unidentifiable at a glance. The real constraint is the panel's own max width, not the two thumbnail rules. **Treat this as "how wide should Deep Focus be, and what does it show at that width", not as a one-number bump.**

**Why.** Bumping the thumbnail heights inside a narrow panel cannot fix it; the panel caps how large any preview can get. Framing recorded so the fix isn't attempted as a CSS one-liner.

### Faststart remux is deprecated in place, CLI-only  ·  *2026-07-21*

--faststart-videos stays CLI-only and is deprecated in place by owner decision (recorded as D-6 in the 2026-07-21 audit). It is a one-time remux for videos downloaded before the auto-faststart path shipped.

**Why.** Every current video-acquisition path already performs the faststart step at collect time, so there is nothing left for a Panel button to do going forward — only the historical backlog, which is a one-time job.

### "Trophy Hall" is now "The Folio of Honors"  ·  *2026-07-22*

Renamed 2026-07-22, the owner's own pick off the rename shortlist.

**Why.** Owner naming choice — the surface, structure and CSS scoping were unchanged by the rename.

### Cost badge is an added preview, never a replacement for the confirm gate  ·  *2026-07-22*

The three Loom Deep Focus tabs (Image/Edit/Reference) each kept their existing confirmSpend/window.confirm gate alongside the new shared cost badge, deliberately. The badge is an added preview, not a replacement.

**Why.** That confirm dialog is this project's original fail-closed guardrail, built specifically after those exact tabs used to lie about cost. Removing it in favour of a display-only badge would remove the guardrail and keep only the thing that was previously wrong.

### Feats score zero points  ·  *2026-07-22*

Points are tier base + 5×(rung−1) (common 5 / rare 10 / epic 25 / legendary 50 / feat 0), rendered on the toast, the tiles, and a Warband-style header total.

**Why.** Feats scoring 0 means the point total can never hint that a hidden feat exists — the same reason earned timestamps are recorded for earned ids only, and masked feats keep name and description masked server-side.

### Per-criteria checklists only exist for closed-universe sets  ·  *2026-07-22*

The two set masteries with a finite, enumerable criteria list (edit/enhance/fix; i2v/flf/r2v) render per-criteria checklists. Open-ended sets stay count-only.

**Why.** A checklist implies a complete, knowable list; showing one for an open-ended set would misrepresent what remains.

### Picker favorites re-sourced from real PixAI bookmarks  ·  *2026-07-22*

Model/LoRA favorites + recents in the picker were originally scoped local-only ("server-stored like Snippets"); the owner's 2026-07-22 ask instead wants them sourced from the user's REAL PixAI bookmarks. That re-scope folds the item into the Epic C (publish/community) surface rather than leaving it a free-standing small item.

**Why.** Changes the item's size and dependency: it is no longer a local-storage nicety but depends on bookmark operations whose existence is itself contradicted between two private recon docs, so it needs a probe before scoping.

### Self-removal stays LAN-reachable; removing anyone else requires a local request  ·  *2026-07-22*

Removing your OWN account is allowed from any signed-in session (it can only harm the caller); removing anyone else's is refused unless the request is loopback. Enforced inside the handler against the session identity, because the tier table cannot express this structurally.

**Why.** Owner's explicit choice on scope. The fix was needed because any LAN session could previously remove ANY account by name (the only guard was "not the last one left"), so a borrowed-tablet guest could evict the owner and — before the matching add-user fix — register itself a fresh persistent login in the same motion.

### The Folio stays a maximized overlay, not a separate page  ·  *2026-07-22*

It is the same maximized overlay grown from the existing achievements modal — tabs, main grid, right rail (category nav, now click-to-filter rather than only scroll-to, Within Reach, Relics, mascot alcove), collapsible sections, search, mobile stacking. All its CSS is scoped so the contest and art modals sharing the same panel class are untouched.

**Why.** "Maximized overlay" was the locked decision; drifting to a new page has been a repeated mistake. The CSS scoping is what keeps a Folio redesign from restyling unrelated modals.

### Continuity "linked" badge is positive-only — no "not linked" warning  ·  *2026-07-23*

A board card shows a small "linked" badge when its opening frame already matches the previous shot's closing frame. It is silent/positive-only — there is deliberately no "not linked" warning state.

**Why.** "most shots are deliberately disconnected from their neighbor" — a warning would fire constantly on correct storyboards. Note: the owner had not yet visually confirmed this as of the doc; built 2026-07-23, exact placement/behavior is a first cut pending his look.

### Owner's concrete mark (icon) decisions  ·  *2026-07-23*

Apply these when the reward system is built: **Void Sentinel** ships as the **default** icon (free, not achievement-gated). **Gem Tome** — owner dislikes it, **remove it from the mark roster entirely**. **Moonwell Eclipse** unlocks together with the **Nightfallen** skin. **Vine Crescent** unlocks together with the **Verdant Grove** skin. **Winged Crescent** — owner wants the **art remade**; unlocks with the **Ember Court** skin once remade.

**Why.** Direct owner picks; each pairing is the bundle model applied to a specific theme rather than an arbitrary assignment.

### Reward system's real shape is a BUNDLE, not an isolated flag  ·  *2026-07-23*

Per the owner: a qualifying achievement was always meant to unlock a **banner + an icon/mark + a matching skin together**, and the reward *type* tracks achievement **tier** — low-tier unlocks an icon, epic-tier unlocks a skin, legendary-tier unlocks a banner. This tier→reward mapping was never fully built. The audit board's framing of this as "build the unlock pool or delete the promise" is wrong; the real task is "finish designing and building a tier-based reward architecture that's partially there."

**Why.** Original design intent, recovered directly from the owner. Also the origin story of a whole achievement category: **Feats (the 11-item tier in the 57-roster) grew out of this same reward-design thinking** — they are a byproduct of working out what each tier should give, not a separately-invented category. And the 57-vs-60 gap was deliberately seeded with this in mind: room for ~3 more achievements was left to round out reward-tier coverage.

### A continuation page can never drift onto different filters, and a failed page never wedges pagination  ·  *2026-07-24*

The load-more path shares one URL builder with the initial search, carries a staleness guard so a fresh search supersedes an in-flight continuation, and on a transient error leaves pagination state untouched so the next scroll simply retries.

**Why.** An independently-built continuation URL would silently mix results from different filters into one grid. Clearing pagination state on error would wedge the list closed permanently for a blip.

### A LoRA version selector appears only when there is more than one release  ·  *2026-07-24*

Resolving a LoRA fetches the full published-version list up front, so switching versions applies the new version id / base type / trigger words with no additional network call. The common single-version case renders no extra control.

**Why.** The previous behavior silently assumed the latest release. Fetching everything at pick time keeps switching instant; hiding the control in the single-version case keeps the chip uncluttered. This mirrors the base model's own version switcher rather than inventing a second interaction.

### Both pickers mount together on first open, but the hidden one does not search  ·  *2026-07-24*

Each host still creates and mounts a base picker AND a LoRA picker on first open; the picker now defers its browse-on-open search when it starts hidden, and each host calls an idempotent "ensure searched" the moment it actually reveals that instance.

**Why.** Mounting both is deliberate so switching tabs never re-fetches. But the hidden one was searching anyway, so every open raced a real search against a wasted one for a tab nobody had asked to see. The deferred+idempotent shape preserves the no-refetch-on-tab-switch property while firing exactly one search per open.

### Easter-egg PAYOFF is a separate decision from the trigger  ·  *2026-07-24*

Whichever trigger is picked, the reward stays celebratory (badge, roast, the file-map pictogram art). Marks already work for anyone regardless of achievement state — there is no code gate that earning `under-the-hood` currently switches on. Adding a real functional gate is a separate owner decision, not part of the trigger redesign.

**Why.** Keeps the two questions from being tangled again: fixing discoverability does not require inventing a functional lock, and inventing one is a product change the owner has not asked for.

### Existing epic-tier skin achievements are the natural bundle anchors  ·  *2026-07-24*

Observation offered to the owner, not a decision made for him: the app's only three skin-gated achievements are all epic-tier ladder rungs, and their skin ids already line up with three of the four bundle themes (Moonlit Silver, Embercourt, Verdant Grove). If the owner wants to reuse rather than reassign, those three are the natural anchors for those bundles' skin half. Only Nightfallen has no existing achievement anchor at all.

**Why.** Preserves the reuse option so a future pass doesn't reassign skins from scratch and accidentally orphan three already-working gates.

### Picker pagination uses the Relay cursor spec already in use, with one opaque cursor at the API edge  ·  *2026-07-24*

Forward Relay-cursor paging was added to the market search (the query previously asked for hasNextPage but never endCursor and accepted no after argument). The search endpoint takes a single opaque cursor the client just echoes back; the route decides per-request whether that means a real GraphQL cursor or a plain offset.

**Why.** The same Relay Connection spec already backs task-history paging in the reverse direction, so this is the app's existing mechanism rather than a guess. Keeping the cursor opaque means the client never needs to know which backend path is serving it, so the two paths can't diverge into client-side special-casing.

### Reward field named `reward_kind`, deliberately NOT `reward_tier`  ·  *2026-07-24*

Scoped shape only (not built, not populated): add **`reward_kind`** (`none`/`icon`/`skin`/`banner`) plus **`reward_id`** (a string bundle/asset pointer, e.g. `"nightfallen"`, empty when kind is `none`) to each achievement. No new TIER field is needed — a prestige `tier` field already exists. Two achievements sharing one `reward_id` is what expresses "these unlock together as one themed bundle", so a bundle doesn't have to be forced onto a single achievement. Optionally a top-level `bundles[]` catalog gives each theme one place to name its actual mark / skin / banner asset.

**Why.** The name `reward_tier` (which the audit's own phrasing suggested) would collide with the existing prestige `tier` field — they are related concepts but not the same one, and conflating them in the schema is exactly the confusion this design is trying to escape. Populating the fields is explicitly the OWNER'S creative call, not an implementer's.

### Reward-bundle ledger — every mark/skin/banner pairing decided so far  ·  *2026-07-24*

Bundle themes as decided: **(default)** Void Sentinel mark, ships free/ungated. **(removed)** Gem Tome — delete from the mark roster. **Nightfallen** — Moonwell Eclipse mark + Nightfallen skin (currently free) + banner #100. **Verdant Grove** — Vine Crescent mark + Verdant Grove skin, no banner picked yet. **Ember Court** — Winged Crescent mark (art not remade yet) + Embercourt skin, no banner picked yet, blocked on art. **Moonlit Silver** — skin picked plus banner generation task `2030243024291694139`, no mark picked yet. Standalone: **banner #62 is the current live default**, already shipped and not tied to any achievement.

**Why.** This is the compiled, cross-checked record of pairing decisions that previously existed only scattered across an audit doc and prose; it is the thing that stops the pairings being re-picked from scratch.

### The Gallery's simpler resolve guard is canonical; both surfaces match it exactly  ·  *2026-07-24*

The Loom's extra "same model id" condition on top of the sequence-counter guard was removed so its version-resolve guard is identical to the Gallery's.

**Why.** Confirmed by the owner testing the same model on both surfaces — the Gallery showed a version dropdown, the Loom didn't. The extra condition was redundant for the superseded-pick case the counter already handles, but a real liability for anything else touching model state mid-fetch: it dropped the whole versions/compatibility/restrictions payload with nothing visibly wrong. Divergent guards on two surfaces of one component are a defect source.

### The LoRA cap is a soft pre-submit guard, not a block inside the picker  ·  *2026-07-24*

Both surfaces show a live "N / cap" count (red once over) and disable Generate with a "remove N to continue" message; the picker itself still lets the pick happen. The comparison is one shared pure function, mirrored by identical inline gallery logic.

**Why.** Refusing the pick in the picker would leave a card visually selected in the picker's own multi-select state that never actually landed in the host's LoRA list — the exact reason the old 6-LoRA cap was never reproduced during the picker migration. Disabling submit keeps the UI truthful.

### A Fix is named from the SOURCE image, and empty chat-task fields show an em-dash  ·  *2026-07-25*

A Fix output is named <source-prompt>_fix-face_<task>_<media> from the SOURCE image, not from the fixed template prompt PixAI writes into every fixer task. Its Model resolves to "Reference Pro" while Seed/Steps/Sampler/CFG stay empty. Naming applies to NEW output only — nothing is retroactively renamed.

**Why.** PixAI stamps every fixer task with the same template prompt, which would make every Fix identically and uselessly named. "a chat task records none of them, and an em-dash is the honest answer" — inventing plausible sampler values would be a lie.

### Cloud delete happens before the local purge, never after  ·  *2026-07-25*

Per-image deletion calls PixAI first and only purges locally on a clean return.

**Why.** The reverse order would leave a catalog hole for an image PixAI still has — the local archive must never be missing something the cloud still holds.

### Filter actions: local save, free handoff to gen, Publish deferred to Epic C  ·  *2026-07-25*

Filter panel actions are: No filter; Save to library (bakes at full resolution, posts to the local-import route, lands in imported/ with a thumbnail and a source='local' row); Send to image gen (composite → upload, the free S3 handshake → media_id → Edit source); and Publish, disabled until Epic C.

**Why.** "Send to image gen" spends nothing — the generation you then run is the priced step, so the handoff itself must never look like a spend. Publish is deliberately disabled rather than hidden because the publish/community epic is roadmapped, not abandoned.

### Filter panel placement threshold is set by "worth judging", not by what fits  ·  *2026-07-25*

The filters flyout is a top-level fixed panel placed on the side-with-room-then-clamp rule: beside the drawer in the left/right docks, centred over it otherwise — and centred too whenever the side room is under 1050px (AF_MIN_SIDE).

**Why.** 1050px "is set by the width at which both pictures are still worth judging rather than by what merely fits." A cramped-but-technically-fitting side placement is not acceptable for a comparison surface.

### Fix is priced from a fetched badge, can never use a free card, and keeps its confirm  ·  *2026-07-25*

The Fix sub-tab carries a cost badge fed by the price endpoint, with the number FETCHED rather than hardcoded; `no_card` is forced on; and the window.confirm() is kept as a genuine spend gate that quotes the badge.

**Why.** A Fix submits as {mediaId, boxes} but PixAI turns it into a chat-kind generation carrying a chat.fixer block, which the price route does price — measured flat 8,000, invariant to box count, canvas size and priority (without the chat block the same call returns the 1,200 base floor). No free card can ever cover a Fix because there is no kaisuukenId field on the fixer route at all. The badge is fetched rather than baked so a price change doesn't silently lie.

### Group incompatible LoRAs rather than hiding them  ·  *2026-07-25*

PixAI groups rather than hides: compatible LoRAs above, then a "Not compatible with the selected model" divider, with incompatible ones greyed but still listed. Judged "a better answer than hiding, and worth copying" for our own picker.

**Why.** Hiding makes a LoRA the user knows they own look missing; grouping explains why it can't be used. Captured as the preferred direction so a capability-gating pass doesn't default to filtering rows out.

### Launchers must not pin --out; the explicit one in serve.txt is intentional  ·  *2026-07-25*

The .pyw launcher stopped hardcoding an output path, and the CLI's --out default became None so "typed the default" is distinguishable from "typed nothing". An explicit --out in serve.txt still appends and is deliberately left there to pin that launcher.

**Why.** The hardcoded launcher argument always won over the stored setting, making any configured library folder permanently unreachable — the folder became unsettable when the desktop GUI (and its folder picker) was removed and nothing replaced it. argparse cannot tell a typed default from an absent flag, hence the None sentinel.

### Local delete and cloud delete are worded apart on purpose  ·  *2026-07-25*

The detail page carries both paths with deliberately different language: "Delete locally" (quarantine to a recoverable folder, a later sync restores it) and "Delete from PixAI" (irreversible, names the surviving sibling count, requires typing DELETE). The cloud button is hidden entirely for a local import (no PixAI task exists) and for a LAN session.

**Why.** The two actions have opposite reversibility, so they must not read as variants of one another; naming the sibling count exists because deleting one image of a batch affects what remains. LAN sessions are not trusted with irreversible cloud destruction.

### Our filters use only exactly-mapping blend modes and no image_parameters  ·  *2026-07-25*

Moonglade's own filters use ONLY the six blend modes that map exactly to CSS/canvas, and carry NO image_parameters. PixAI's darker-color and lighter-color are Photoshop whole-colour comparisons with no CSS equivalent, approximated by darken/lighten and flagged exact:false with the reason recorded in the blend-mode map.

**Why.** "their export is their preview and what shipped is what was approved as swatches" — a filter must not render differently from the swatch the owner signed off on. It is also why PixAI's M1/M2/M5/M6 can differ slightly from PixAI's own render while none of ours can.

### Our five filters derive from the five skins, and a test pins them to skin tokens  ·  *2026-07-25*

MOONGLADE_FILTERS — Moonglade, Nightfallen, Moonlit Silver, Embercourt, Verdant Grove — are ours, derived from the five skin palettes, each recipe built from its skin's accent and lead colours and tagged with the skin it came from. A test pins every stop colour to a real token of that skin's CSS block. groups() returns ours first and drives the rail's two headed sections.

**Why.** The pinning test means "a retint that leaves its filter behind fails by name" — a skin recolor can't silently desynchronize its filter.

### Picker bookmark/my-LoRA operations: settled and measured, do not re-litigate  ·  *2026-07-25*

Settled by live capture with the owner driving Chrome plus a network capture: the BOOKMARK tab is its own persisted operation (`listMyBookmarkedGenerationModels`), while MY LORA is NOT a separate operation — it is the ordinary `listGenerationModels` list filtered by the signed-in user's own author id. Argument names differ between the two and must not be assumed shared. `listMyBookmarkedGenerationModels` is reachable **only through the persisted-query path**, which is why an ad-hoc probe reported it absent — so the contradiction between the private API doc and the 2026-07-04 recon was not an error in either: the op is real AND absent from the ad-hoc Query root. GO/NO-GO measured 2026-07-25: **both operations return HTTP 200 with real data using the owner's own API key**, not a browser session. **Do not re-litigate this. It is measured, not inferred.**

**Why.** This was the one thing that could have killed the picker feature, it had two docs flatly contradicting each other, and the answer cost a live capture to get. Marked do-not-re-litigate explicitly.

### PixAI's seven filters are kept verbatim so refreshing stays a paste  ·  *2026-07-25*

The PixAI filter set is baked verbatim from their public unauthenticated config endpoint (GET api.pixai.art/config/imageArtFilters, verified 2026-07-25) and kept verbatim.

**Why.** So refreshing it stays a paste rather than a reconciliation exercise.

### The comparison panel uses a second <img> for the original  ·  *2026-07-25*

The filter panel's three columns are original | filtered preview | swatch rail, align-items:stretch with flex:1 frames so the pictures are matted and centred instead of stranded above a void. The original is a SECOND <img> element.

**Why.** "sharing one would filter both and leave nothing to compare."

### The upscale flyout can never outlive the picture it was opened for  ·  *2026-07-25*

The lightbox flyout sits above the overlay (the overlay deliberately stays open behind it) and is force-closed by both the lightbox close and step-to-next-image paths.

**Why.** An upscale panel still showing after the user has navigated to a different image would submit against the wrong source.

### There is deliberately no /api/upscale endpoint  ·  *2026-07-25*

Upscale submits through the existing price + generate routes as a plain image-to-image request (reference media id + strength).

**Why.** Upscale and the Generate-tab boosters are ordinary generation parameters, not a separate feature — adding a parallel endpoint would fork the spend path and duplicate pricing/guard logic.

### Upscale never guesses the model  ·  *2026-07-25*

The model is prefilled from the catalog row when known, and otherwise falls back to the shared model picker so the user chooses.

**Why.** A different model restyles the picture rather than just enlarging it, so a silent default would silently alter the owner's art.

### "Under the Hood": the gate IS the feature  ·  *2026-07-26*

The easter-egg gate on custom branding is not incidental — it is the point of the feature. Owner's framing, quoted verbatim: **"The point is to reward the nosy power user. A generic user just playing with this to grab their gallery and run gens isn't going to give my branding a 2nd thought... The point is to leave the folders available for those people that poke around and look for the nuts and bolts. This is one of the rarest unlocks in the bunch. You have to tinker and play to find the sauce."**

**Why.** Recorded emphatically because the opposite was proposed and had to be corrected. The product's own copy already committed to this design: the roast reads "Look who went spelunking in the walls... Custom branding: unlocked. Tell no one." The design was written down in the product's voice, just not anywhere a doc sweep would look.

### branding/ lives in the APP ROOT, not inside the code package — likely moves once more  ·  *2026-07-26*

**Owner note 2026-08-13: this location will likely move one more time in the final naming pass.** The decision below records why it left the code package; the eventual home is not final.

The branding folder (marks, mascots, banners) sits at the top level of the app folder, beside the gallery launcher — deliberately NOT inside the code package that the naming pass creates.

**Why.** Three reasons, and the third decides it. (1) The package folder will be CODE; putting user art inside it re-creates the exact problem the move exists to fix — the owner's words were that he noticed achievements and suchlike sitting in the core folder and wanted them tucked away, so moving code IN is the tidy, moving content in undoes it. (2) A package folder acquires caches, an init file, and is the natural unit to zip or install; images inside that boundary will eventually be treated as code by something. (3) It would break the easter egg: a tinkerer opens the app folder and scans the top level, so branding/ there is findable, while a level deeper inside a folder that looks like source they would see a wall of .py files and back out. The resulting root reads correctly — the package is obviously the machinery, branding/ is obviously theirs, and both user-facing things sit at top level. It also makes the code move simpler, because then everything moving into the package is code with no exceptions.

### Catch-up sweep guardrails, and testing it at source level on purpose  ·  *2026-07-26*

The watcher catch-up sweep is bounded, rate-limited, absent-only, paced, off-thread, cannot raise, and spends nothing. It was deliberately tested at source level rather than refactoring the watcher to create a test seam.

**Why.** The catch-up is a closure inside the app factory, called only from a thread the suite disables, so there is no seam to drive it without restructuring the watcher — not worth the churn. The tests pin the guardrails plus the fact that the sweep can never fire during tests.

### Dead local jobs resolve by process identity, not a timeout heuristic  ·  *2026-07-26*

A local (panel/delete) job's owning process IS the server, so any non-terminal local job whose last event predates this server process's start is dead by definition. Sweep those at startup and mark them interrupted.

**Why.** The clean rule needs no timeout guessing. Existing orphan resolution only covers PixAI-task-keyed generate jobs, on the premise that local jobs are self-reporting — which is true right up until the process is killed, and then nothing ever writes the terminal event. The silent-death detection shipped the day before does not cover this class at all.

### Default shipping bundle is settled  ·  *2026-07-26*

The defaults are: **Moonglade** skin, **Void Sentinel** icon, and the **current banner** — all free, all ungated.

**Why.** Settled by the owner on the triage board so the default-bundle question stops being re-asked; free/ungated is deliberate, the defaults are not a reward.

### Free LoRA trainings ride the EXISTING free-card path  ·  *2026-07-26*

The training input's free-card field is the same kaisuuken mechanism already implemented for image generation, so the existing free-card path applies directly — no new mechanism needed.

**Why.** The 8 free trainings are kaisuuken cards. This is the headline finding of the capture: what looked like a separate entitlement system is the one we already handle.

### Keep the light backfill command, never surface it  ·  *2026-07-26*

Keep --backfill-meta, and never give it a Panel button or any other UI surface. It is SUPERSEDED, not obsolete: the full backfill fills the same three columns as a free side effect and full-meta is the default on a normal pull, so new rows arrive complete. Its one remaining unique capability is that the two commands take different routes to the data — the light one resolves via the media object, the full one via the task — so the light one alone can repair a row whose MEDIA still resolves but whose TASK is gone (a generation deleted from the PixAI account where the local image survives but the record describing it does not). Rare, and it recovers dimensions only, not prompt or seed.

**Why.** Asked and answered 2026-07-26 because nobody could remember why it existed. It is kept for that one narrow repair case; it is never surfaced because a button would imply pressing it achieves something the sync has not already done.

### Never hard-code a short-lived credential (the U3T lesson)  ·  *2026-07-26*

The old "constant token harvesting" pain was not the JWT — it was U3T stored as a static string in config.json when that value has a ONE-HOUR life. It was stale almost immediately, invisibly, with no signal. The structural fix is a session cookie jar: the short-lived cookies refresh themselves via Set-Cookie on every response. "They were never things to harvest, they were things to stop hard-coding." A read-only query also succeeded with no U3T sent at all, so it is not required for auth on that path.

**Why.** Measured, not assumed (2026-07-26): the JWT is ~27 days (up from ~12 days measured 2026-07-11 — one of several signs their site is changing under us), the u3t cookie ~1 hour and refreshed on every response, the browser-session id ~30 minutes and likewise refreshed. Storing an hourly credential in a config file guarantees silent failure inside the same sitting.

### Nightfallen is gated behind The Great Library  ·  *2026-07-26 · gate finalized 2026-08-09*

Nightfallen is gated behind **The Great Library** achievement, and the **Moonwell Eclipse** icon gates *with* it — one bundle, two pieces, one achievement. (An earlier draft gated it behind Night Keeper; The Great Library is the final gate.) Its free status was never intentional — free only because the reward plan hadn't landed yet.

### No filesystem watcher for dropped branding files  ·  *2026-07-26*

Detecting a dropped branding file is done by checking on Panel/branding load. A real filesystem watcher is deliberately not needed.

**Why.** The check only has to be true by the time the user looks at the branding surface, so a load-time scan is sufficient and avoids a long-lived watcher for a once-per-install event.

### One free achievement slot earmarked for Dungeon Crawler Carl  ·  *2026-07-26*

Of the three free slots (57 of 60 used), one is earmarked for a Dungeon Crawler Carl reference. The native hook is DESCENT — something that fires on reaching the true bottom (the oldest image, or the literal end of 35,000). Carl art already exists in the chibi library. The other DCC-native option is an achievement whose ROAST is written as a sponsor announcement.

**Why.** DESCENT is the thematically native hook rather than a bolted-on reference, and the sponsor-announcement variant lets the voice do the work instead of the metric — which is the cheaper and more characterful of the two.

### Password reset splits into self-service vs. owner-machine  ·  *2026-07-26*

Owner, 2026-07-26: "a user may reset THEIR OWN password from anywhere; resetting anyone else's is an owner-machine action only." Self-service reset inherits the self-only carve-out the existing user-removal route already uses; admin reset-for-another-user is LOCALHOST, like adding an account. This was the blocker on the item — it is now a build, not a question.

**Why.** It splits the trust question into two paths rather than forcing one trust call for both cases: changing your own credential needs no elevated trust, while changing someone else's is an administrative act that should require being at the machine.

### Persisted hashes are derived — and plausible-and-wrong is worse than absent  ·  *2026-07-26*

The hashes are not in their bundle at all (zero 64-hex strings across 868 chunks / 16 MB — Apollo computes them at runtime), but the documents ARE, as pre-parsed AST literals with complete field projections and typed variables. So we print the AST the way graphql-js does and hash that. Three hashes observed on real requests are baked in as an oracle; of four print variants tried, exactly one reproduces all three (inject the typename field before hashing, no trailing newline). If no variant passes, the tool writes NO hashes at all.

**Why.** Plausible-and-wrong is worse than absent on a surface that spends money. This is also the standing answer to "what happens when PixAI changes their frontend": re-run the harvest and the hashes re-pin themselves, which demotes the manual recapture procedure to a fallback rather than the first move.

### R2V uploads deliberately left in place  ·  *2026-07-26*

Image-to-video and first/last-frame pass the catalog media id straight through with no re-upload. Reference-video was deliberately NOT changed and still uploads.

**Why.** The requirement that forced every input through an upload came from an error name specific to the reference-VIDEO field: it was real for R2V and only wrongly generalised to i2v, where it never applied. A read-only survey of the owner's own history found reference-video tasks split 3 catalog-id / 3 uploaded, so the evidence is mixed and the error name was specific. Banked follow-up: if R2V turns out not to need uploads either, the same content-scanner trap applies there too.

### Harvest the whole surface for MAPPING; hand-probe for specifics  ·  *2026-07-26 · reframed 2026-08-13*

The full-surface harvest (182 operations — 102 queries, 80 mutations/subscriptions — each with its full document, typed variables, and hash, landing in a git-ignored folder) is the right tool for *mapping* what exists. But the original "stop hand-probing" framing was too strong — targeted hand-probes keep finding real things the harvest alone doesn't surface, and regular scheduled probes of the website (to catch code-altering changes) are planned. Both tools, each for its job.

**Why.** The fetch and extract steps never touch their API — static CDN files only. Owner correction 2026-08-13: "we keep finding MORE by hand probing specific things."

### The other two achievement slots stay unspent  ·  *2026-07-26*

Do not mint the two most obvious remaining candidates — first LoRA trained (the owner has two) and first generation mirrored to the PixAI library — yet.

**Why.** They only become meaningful once LoRA training and the JWT mirror toggle are real features. Minting them early repeats the Enhance Adept mistake of an achievement whose metric has nothing behind it.

### The password recovery story is complete as it stands  ·  *2026-07-26*

Three sentences, and no fourth is owed: know your password → change it from anywhere via Panel → Users; forgot it → someone at the server machine resets it via Panel → Users; you are the only account and you forgot it → run the add-web-user CLI command at the machine, whose add-or-update semantics double as a reset. That CLI path is kept for exactly this case.

**Why.** Recorded so the CLI path is not "cleaned up" as redundant once the Panel has reset buttons — it is the only recovery route when there is a single account and no session to authenticate.

### Two branding tests deliberately bypass the isolation fixture  ·  *2026-07-26*

An autouse fixture redirects the branding resolver to a temp dir for the whole suite (mirroring what already happens for the auth config). Two tests deliberately opt out: one pins the absolute app-root location and asserts no library setting can steer it, the other pins the sibling relationship of the branding config file.

**Why.** The resolver resolves from the module's own location, so without isolation every test writing a fake mark would drop PNGs into the real checkout, and any "no marks installed" assertion would pass or fail based on whatever real art sat on that machine. But isolation also means a green suite proves nothing about the production path — hence the deliberate bypass. Do not "clean up" those two by putting them back under the fixture.

### Upload-and-retry-once kept as insurance on the spend path  ·  *2026-07-26*

On an invalid-media-id error the route uploads once and retries once, rather than deleting the old upload behaviour outright.

**Why.** Keeps the July behaviour as insurance on a path that spends money, and it is safe by the submit path's own argument — an error back means the task was rejected, so there is nothing created to double-charge.

### Visible countdown, not silent staleness  ·  *2026-07-26*

The shipped mirror design is a visible countdown: decode the JWT's expiry at startup (offline, no network call), the Panel shows "PixAI mirror: N days left" beside the toggle, under 5 days it becomes a warning with a paste field, and the short-lived cookies need no attention at all. That is roughly 13 deliberate ten-second pastes a year, each announced in advance.

**Why.** "A different category of annoyance from the invisible hourly failure the owner rejected." An announced, predictable ten-second task is acceptable; a credential that dies silently mid-session is not.

### Watcher state must be logged, not just held in memory  ·  *2026-07-26*

The watcher's state may not live only in an in-memory status object — every transition goes to the log file, with the silent-socket case at WARNING saying explicitly that anything completing during the silence was NOT mirrored.

**Why.** Because "was it even connected?" was unanswerable after a missed video. An observability gap on a background process turns one missed generation into an uninvestigable mystery.

### Which PixAI community features Moonglade gets — YES list  ·  *2026-07-26*

Owner picked from the harvested operation list rather than from a proposal. YES to: Like/react (liking a LoRA and liking an image share one operation shape, so it is ONE function with a different id, not two features — and the liked flag already comes back on every picker row, so it lights up a field we already fetch); Bookmark WRITE (read already shipped; write means you bookmark from our picker instead of bouncing to their site); Follow (his ONLY wanted social link, and specifically because of the model-market click-through — follow/unfollow a creator whose page you just opened); Publish (already roadmapped as Epic C — their publish page still needs capturing, and note their MOBILE app offers an AI-powered helper that writes the description for you, worth seeing before we design ours); Notifications (pairs with the LoRA training credit-rebate promise — it is how you would learn someone used your LoRA).

**Why.** He chose off a measured inventory of what actually exists on their side, so these are grounded picks rather than a wishlist. The reasons attached to each one are the part that would be lost.

### A fresh clone boots instead of exiting

When the git-ignored output folder or the catalog does not exist yet, the gallery creates the folder and an empty schema-initialized catalog and boots normally.

**Why.** It used to exit outright — a console error before the web server ever started, so there was no page for the first-run wizard to render on. The wizard was unreachable on a genuine fresh clone, which defeats its entire purpose.

### A hand-edited prompt override is never merged with auto-composed text

When a prompt override is active, shotText() returns the override verbatim instead of composing from Camera/Lighting/cast. Overrides persist durably across shot deselect/reselect and reload. The "↺ re-sync from shot" button clears the override and forces a fresh auto-compose; a visible badge distinguishes override-active from auto-composed.

**Why.** "composing scaffolding INTO an already-hand-edited override would duplicate it deeper on every re-sync cycle." Previously a hand-edit only affected that one immediate Generate click and was silently discarded the moment the owner looked at a different shot.

### A model with no tuned preset leaves the fields alone

Base-model tuned presets prefill the drawer (author's negative prompt / sampling steps / cfg scale) with a note row and a "↺ reset" button. A model with no tuned preset leaves the fields alone.

**Why.** Absence of a preset must not clobber whatever the user already typed.

### A preview route takes the tier of the action it previews

The bulk-delete preview endpoint is declared at the tier of the deletion it previews (step one of that flow, called from nowhere else), not at the tier its read-only catalog rows would suggest.

**Why.** Tiering a preview by what it reads rather than what it leads to would open a loophole on every future confirm-then-act flow.

### An undispatched job is marked `stale`, a non-terminal status

generation_status() returns `started` and `reason` (PixAI's own explanation, e.g. "waiting timeout") alongside status/phase/paid_credit. The CLI poller reports a never-dispatched task honestly instead of claiming it is "STILL RUNNING"; a terminal cancelled carries PixAI's reason; and the orphan reaper marks an undispatched job `stale` — a non-terminal status the tracker already renders with a warning glyph.

**Why.** An undispatched task is non-terminal for ~60 minutes, so status alone cannot tell it from real work. Marking it stale rather than failed means a task that does eventually start can still resolve to done.

### Audio language chips include "SE only"; both surfaces expose the same five

Video shots can request generated audio, with language chips English / Japanese / Chinese / Korean / SE only. "SE only" is PixAI's real sound-effects-only value — it is NOT silence. The main gallery's Video tab already had the checkbox and a 4-language select but was missing SE-only; both surfaces now expose the same five choices.

**Why.** Parity between the two generation surfaces is deliberate. The server already accepted generate_audio/audio_language (reverse-engineered long before) — the gap was purely a missing control, so nothing new had to be invented, only exposed identically in both places.

### Batch submit is a deliberately separate path; prompts recomputed, never read from the DOM

batchGenerate is a genuinely SEPARATE submission path from the Generate drawer's own per-shot Generate button (both hit /api/loom/generate). Both batchGenerate and generateShot always recompute the prompt fresh from the card's own fields, never reading the drawer's live DOM directly. The one concession: the toolbar's onClick flushes and locally patches a pending drawer hand-edit into a promptOverride first, so a shot mid-edit still generates with the latest text regardless of React's render timing.

**Why.** Reading the drawer's DOM would couple the batch path to whichever shot happens to be mounted/selected; recomputing from card state makes each submission self-describing. The flush exists so "latest text wins" doesn't depend on render timing.

### Clearing an override is visible, never silent

Typing in the Loom's own native Prompt textarea clears an active drawer override immediately — and does so visibly, via a brief self-clearing flash notice rather than silently.

**Why.** Editing the prompt from the other surface means the same thing as clearing the override, but the user must be told their override just went away rather than discovering it later.

### Config is written only after validation succeeds — never written first and rolled back

The wizard persists the key only after the validation call actually succeeds.

**Why.** Write-then-roll-back leaves a broken credential on disk if the rollback itself fails.

### Cost-to-finish pill deliberately does NOT share the batch's pre-confirm pricing

The standing free/paid/credits/unpriced cost pill runs off a warm per-shot price cache (600ms board-debounce plus click-to-force). It is deliberately NOT shared with batchGenerate's own one-shot, must-be-fresh pricing pass immediately before the irreversible confirm. Both use the same pure tally math underneath.

**Why.** "different staleness contracts" — a browsing estimate may be slightly stale; the number shown at the moment of spending may not be.

### Folio of Honors form factor = maximized overlay

The Folio of Honors is a maximized overlay, NOT a page or a route: grow the existing achievements modal to full-screen — instant open, gallery stays mounted behind, ESC out, animates from the trophy button. Owner screenshots tune the INTERIOR only; the form factor is settled.

**Why.** Keeping the gallery mounted behind makes open instant and preserves context; a page/route was considered and rejected. Interior screenshots must not be read as reopening the form-factor question.

### Health disk walk excludes derived/quarantine folders

The Health page's disk walk excludes gallery/, _duplicates/, _deleted/ and branding/.

**Why.** So its number agrees with the Panel's catalog-row count — derived thumbnails, quarantined duplicates, soft-deleted files and branding art are not archive contents.

### Id search is exact-match and gated to 8+ digit terms

Gallery search matches a task/media id by EXACT equality, gated to all-digit terms of 8 or more characters; shorter numeric terms stay prompt-only. The box reads "Search prompt / task or media id".

**Why.** Short numeric strings are far more likely to be prompt content than an id, so they must not be hijacked into an id lookup.

**Why.** Two separately maintained layouts would double the maintenance surface; framing it as a responsive concern would drag in mobile work that was not asked for. Deferring until after the visual pass avoids scaling a design that is about to change.

### Loom workspace shell — three named elements

The workspace shell is three named elements with nothing free-floating: left Cast & Assets (Simple = name/tag/ref-preview card; Detailed = the full V1-style editable row; Footage as a second tab), center Acts & Shots board, right Generate drawer (Image/Video/Edit/Reference, collapsible, mirroring the gallery drawer's positioning and behavior). Top is the fixed Timeline drawer. A FULL generate panel belongs inside the Loom — generating straight from the board for establishing shots stays — and nothing links back out to the gallery.

**Why.** Cohesion: the Loom is a self-contained workspace, not a launcher that bounces the user back to the gallery to generate. "Nothing free-floating" rules out ad-hoc panels appearing outside the three named regions.

### No separate local-vs-LAN check on the first-run banner

The first-run wizard banner shows to any authorized viewer (owner at the keyboard or a logged-in LAN account) under the identical no-key / empty-catalog condition, gated only on a fresh (not module-cached) config read and the true unfiltered catalog count.

**Why.** Reaching the home page at all already requires passing the front-door login gate, so a second location check would add nothing. Neither state shows once the catalog has real rows.

### Passwords are NIST-shaped: length is the control, no composition rules

8-character minimum plus a weak-password blocklist (repeated characters, sequential runs, common list). No character-class requirements. One shared helper serves all three account-creation paths.

**Why.** Deliberate modern-guidance choice over composition rules; the single helper prevents the three creation paths from drifting to different strengths.

### Price-cache fingerprint covers only fields that actually change price

The per-shot price cache is fingerprinted on only mode/images/video_refs/duration/quality/audio — never prompt/camera/lighting — verified against the server's own price allowlist.

**Why.** Fingerprinting on prompt text would invalidate the cache on every keystroke for fields the pricing endpoint ignores.

### Server stop and restart are deliberately LOGIN

By owner decision, the stop and restart endpoints are reachable from any signed-in session rather than localhost-only.

**Why.** Owner's explicit call — he wants to be able to bounce the server from the tablet.

### Session revocation rides an install-wide counter, not a per-account one

Revocation uses a single monotonic counter in config. A legacy config gets a 1,000,000 margin on its first mint.

**Why.** A per-account counter died with the account, so re-creating the same username reset it to the value stale cookies already carried — silently un-revoking them. The 1,000,000 margin exists so an account removed BEFORE the upgrade cannot be walked back through either.

### Spend-capable routes are LOGIN, not LOCALHOST — because the tablet generates

Generate, edit, fix and the Loom's generate are all reachable by any signed-in session. LOCALHOST is reserved for writes to the server's own disk, credential writes, and irreversible cloud deletion.

**Why.** Deliberate: the owner generates from a tablet over LAN, so restricting spend to loopback would break the primary use case. The tier boundary is drawn around irreversibility and host-machine access, not around cost.

### The wizard reuses the existing Panel job machinery

"Sync now" drives the existing Panel run/status endpoints rather than introducing any new job-running code.

**Why.** No second job runner to keep in sync; one mechanism for background work.

### Timeline is a fixed drawer, never dockable

The Timeline is a fixed drawer attached to the top banner — never a draggable/dockable panel. Three states: default visible at a slim height at full page width; fully pushed away, collapsing to nothing; pulled down to a set full size with the video preview ABOVE the scrubber. A side-by-side preview stays banked as a secondary layout worth exploring later.

**Why.** Draggable/dockable panels were explicitly rejected for this surface; the drag is a three-state height gesture, not free positioning. Preview-above-scrubber is the chosen layout; side-by-side is banked, not dead.

### Typing a base prompt clears the frozen prompt override

Both write sites for a shot's base prompt (the right panel's Prompt field and Deep Focus's matching field, in the same placement in both — after Mode/Duration, before the frames) clear an active prompt override the instant the owner types there. The base string keeps recomposing alongside every later Camera/Lighting/cast edit. The generate drawer's own composed-prompt box is unrelated: it only ever writes the override, which is a frozen, never-re-woven verbatim replacement by that feature's own explicit design.

**Why.** Typing a base prompt means "auto-compose from this text now" — so an override that would silently win over what the owner just typed has to be dropped. Conversely the drawer's override is deliberately frozen: its whole point is a verbatim replacement that later edits do not re-weave.

### V2 shell is fixed, not a free-form canvas

Loom V2 is a fixed four-region shell (top strip, left card, center board, right Generate drawer). Nothing in V2 is draggable, resizable, or x/y/w/h-persisted.

**Why.** Stated as a deliberate property of the shell; no further rationale recorded in the doc.

### The bundle's unlock split: branding opens, achievement assets stay sealed  ·  *2026-07-27*

Contents and unlock model, decided in chat: ALL of the owner's branding goes into the container (a small owner audit of the base items is still owed before the list is final). Earning "Under the Hood" unlocks the full branding folder — the user-facing customization slots are **Icons/marks · Banners (main + login screen) · Mascots · Rewards** — but NOT badges, the Mystery Konami-code assets, or the tier frames: those stay sealed to the achievements that earn them. Likewise sealed: ANY file carrying achievement data or descriptions. This needs recoding — badges, Konami assets and frames are currently counted as part of "Branding" and must be split out so the branding unlock cannot reach them.

Ruled 2026-07-27, same conversation: **mascots — including the per-achievement animations — are Flair, open to branding customization; they are NOT part of the achievement itself.** The badges are, owner verbatim, "the sauce on achievements" — badges stay sealed.

**Why.** The branding unlock is the "make it yours" surface; the sealed set is earned surprises, and one achievement must not open another's reward. The mascot bucket was flagged as a boundary to pin and the owner ruled immediately: flair travels with branding, sauce stays with the achievement. The roster JSON is no longer a caveat here — it is out of the repo entirely, see [[The 57-roster JSON is gone: removed from the repo and scrubbed from history]].

### Marks come in three layers, and the selector moves on unlock  ·  *2026-07-27*

The included mark/icon set is the DEFAULT set — the launcher-icon picker keeps working out of the box, nothing users have today is taken away. Some included marks are gated by their own achievements (a mark can be an achievement's reward). The "Under the Hood" branding unlock adds ONE user-custom mark/icon on top of the included set, selectable in the Control Panel. And once full branding unlocks, the skin and mark selector MOVE into the unlocked branding panel — the branding tab becomes the customization hub. See [[The bundle's unlock split: branding opens, achievement assets stay sealed]].

**Why.** Owner's design, answering the "are the tab/launcher icons gated?" question with something better than a yes/no: the default experience stays whole, achievements keep gating their own marks, and the unlock's reward is additive — your own mark, plus the hub to manage all of it.

### What Moonglade actually is: official key, INTERNAL endpoints  ·  *2026-07-28*

**Moonglade authenticates with an official long-lived PixAI API key and drives PixAI's own GraphQL API.** Official credential, internal endpoints, same host. One `Authorization: Bearer <PIXAI_API_KEY>` on every request (`load_token`/`_make_session`); no JWT in the live path. Generation, edit, video, listing and deletion all go to `api.pixai.art/graphql` via `createGenerationTask` — the `apollo-require-preflight` + `x-apollo-operation-name` headers we always send are Apollo CSRF headers and are the proof. Exactly FOUR official `/v2` REST endpoints are used: `/task/fixer`, `/kaisuuken/check`, `/task-price`, `/task/{id}`. **`/v2/image/create` is never called.**

**The 2026-06-22 switch was AUTH-ONLY.** Commits "Support official API key as preferred auth" → "Auth: API key is the only required credential" swapped the expiring browser JWT for the long-lived key and moved no endpoint. It was never framed as partial, so the owner reasonably believed the whole stack had migrated to an official API. It had not.

**Why.** Recorded because the owner discovered the gap on 2026-07-28 and it cost real trust. It also REFRAMES a board item: F13 ("a browser JWT files a generation into the pixai.art account, a bare API key does not") is **the bill for the June 22 switch**, not a missing feature — "Mirror to PixAI" is a restoration of what that migration cost. See [[PixAI's official API v2 exists, is enrollment-gated, and cannot build this app]].

### API-key MANAGEMENT is membership-gated; existing keys keep working  ·  *2026-07-29*

Measured by the owner across his own lapse and renewal. While the membership was lapsed the API-key interface was **gone from the site**; on renewing, it **came back with his two-year keys intact**. So the gate is on *managing* keys — issuing, viewing, rotating — not on the keys themselves, which keep authenticating throughout.

**Why.** This is a different shape from what a whole session assumed, and it corrects two things at once. First, a lapsed member does not lose API access, so nothing in Moonglade breaks on a lapse for that reason — the failures seen on 2026-07-28 were per-feature entitlement checks (Quality Tag, Edit Pro, Reference Pro, the LoRA cap), never the credential. Second, it explains how the owner holds long-lived keys at all: they were issued while a member, and their two-year lifetime outlives the membership that produced them. Practical consequence worth remembering: **do not let a key expire while lapsed** — the key would keep working to its expiry, but there would be no interface to issue a replacement without renewing first. Related: [[PixAI's official API v2 exists, is enrollment-gated, and cannot build this app]] — the enrollment programme is a separate product on top of this, and this finding does not change that.

---

### A locally-imported file could save and never appear on page 1 — created_at's timezone, not a duplicate or a sandbox artifact  ·  *2026-07-29*

Owner, after Save to library started reporting success: **"It says saved but does not appear in
the gallery."** First explanation offered was wrong and worth recording as a lesson: reading the
default "All, newest first" view, two thumbnails looked blank at a glance and were assumed to be
the new saves; zooming in showed they were unrelated real images — a second misread in the same
investigation (the first was mistaking a JPEG-compression artifact for a broken tile). The
owner pushed back correctly: **"I would think they would be in line with the timestamp and
appear at the top."** That instinct was right. Checked the actual `catalog.db` rather than
trust a screenshot a third time.

**Root cause:** `_SORT_SQL`/`_DEFAULT_SORT_SQL` (`moonglade_gallery.py`) sort `created_at` as a
**plain SQL string**, no `datetime()` wrapping. `run_import_local()` (`moonglade_backup.py`)
stamped it via `time.strftime(..., time.localtime(stored.stat().st_mtime))` — **naive local
time, no timezone marker** — while every PixAI-collected row's `createdAt` arrives (and is
stored) as **UTC with a trailing `Z`**. A file saved at 23:0X PDT reads as the string
`"2026-07-29T23:0X:XX"`; a PixAI row collected minutes earlier reads as
`"2026-07-30T06:0X:XX.XXXZ"` — and `"2026-07-30…" > "2026-07-29…"` lexicographically, regardless
of the fact that 06:0X UTC on the 30th *is* 23:0X PDT on the 29th, the same evening. The row was
never missing: correctly written, correctly thumbnailed, correctly counted (`source=local`
filter surfaced all 6 test saves immediately, and `total` had incremented on every one) — it
simply never sorted near the top of a plain-string "newest first" comparison against
UTC-stamped rows.

**Fix:** stamp UTC + `Z` instead of naive local time, in `run_import_local()` and in the four
`result.get("createdAt") or time.strftime(...)` fallbacks on the generate/edit/video/
reference-video collect paths (`moonglade_backup.py`) — same latent inconsistency, same shape,
fixed everywhere it appears rather than only where it was reported. Required a full server
restart to take effect: `import moonglade_backup as core` runs inside each request handler, but
Python caches the module in `sys.modules` on first import, so an edited `.py` file is invisible
to an already-running process until it restarts (this server runs with `debug=False`, no
auto-reloader). Verified live post-restart: a fresh save's `created_at` lands as `…Z` UTC and is
genuinely the first tile in the default view, ahead of every previously-collected row.

---

## 2026-08-01 — design-kit merged; the handoff map is NOT trusted until audited after the React conversion

The `design-kit` branch was merged to master on the owner's explicit instruction, with the
owner's verdict on record: the kit was supposed to be *"the UI kit and linkage, function
names and what interconnects what — basically the entire click map"*, and what it delivered
was mostly *"style sheets and formatting constraints"*. Getting even that into Claude Design
took multiple passes and the linkage info was still incorrect/conflicting. Accordingly:

* **`static/design-handoff.html` (the handoff map / linkage card) is unaudited and not to be
  treated as a reliable source** for component linkage or interconnection. Do not build from
  it or cite it as authority.
* **Standing follow-up: audit the design kit after the React conversion lands** — the
  conversion will change the real linkage anyway, so auditing before it is wasted work. A
  trustworthy click map must be rebuilt **bottom-up from the source** (walk every route,
  button, and function, verify each edge against code), never authored top-down from memory.
* The token machinery (exporter + drift test + generated token pages) is unaffected by this
  verdict — it is generated from `DESIGN_TOKENS_CSS` and pinned by the suite.

**Why.** Merging keeps the token discipline and the Claude Design mirror live without
carrying an unmerged branch, while the verdict on the handoff map is written down so no
future session mistakes a merged file for a trusted one.

---

## 2026-08-02 — Contact Sheet + Duplicate Review scoping: neither is a straight port

Full re-verification of the local `design_handoff/` copy against the newest zip on the
owner's Desktop (`Moonglade_handoff v3 8.2.26 415am.zip`) found the local copy current
(byte-identical, assets aside) — every relay/correction doc in `uploads/` was already
answered and folded into `drift-report.md`. One genuine gap: `Glitch Reveal Demo.dc.html`
(the 3-option Folio "Unleash" reveal demo) sat at the zip root but was never copied into the
synced `design_handoff_moonglade_suite/` bundle — copied in; its outcome (style A, ruby
scramble) was already fully captured in `folio-glitch-spec.md`, so nothing was missed
functionally.

**Contact Sheet and Duplicate Review, scoped for build, are NOT ports like the previous
five surfaces (Health/My Art/Contests/Import/Panel):**

- **Contact Sheet's DC design is a static print mockup with fabricated data**, while the
  REAL backend (`/contact-sheet`, `moonglade_gallery.py:13834`) is already more capable —
  3 print formats, real ratings, real model names. Owner's explicit call, after an initial
  plan to hand off to the classic route for the actual print action: **"do it correctly, not
  the short way"** — the classic interface is being fully retired, so nothing in the new
  front door should redirect to it, even for a working feature. Built natively: a new JSON
  endpoint (`GET /api/contact-sheet`, same data functions, LOGIN tier) plus a React overlay
  whose print output is genuinely native (`window.print()` + `@media print`), not a
  `window.open('/contact-sheet?...')` redirect.
- **Duplicate Review's DC design assumes fuzzy, percentage-scored, human-reasoned duplicate
  detection** ("92% similar", "same seed · re-rolled 2×") that does not exist. Real detection
  is exact-match only: same media_id reused (Class A, `duplicate_groups()`,
  `moonglade_gallery.py:2509`) or byte-identical files (Class B, `audit_collection()`,
  `moonglade_backup.py:3704`). Scoped to a **happy medium** with the owner: ship every tier
  that's honestly real, including two not built yet but cheap/well-scoped to add — same-seed
  grouping (real column, `seed` is populated in `CATALOG_FIELDS`, just an unwritten SQL
  query) and a new perceptual-hash ("upscaled/recompressed original") tier. **Explicitly
  excluded:** the CLIP-embedding "similar composition" tier — real infrastructure
  (`/api/similar`) exists, but it measures visual resemblance, not duplication; wiring it to
  a *destructive* action risks quarantining genuinely distinct images on a false positive,
  and it already serves its actual purpose (browsing "more like this") elsewhere in the app.
- **Duplicate Review's Resolve action will really quarantine files** — owner's explicit
  choice, not the read-only/advisory default first proposed. Scoped to **quarantine only,
  never hard-delete** (moves losers to `_duplicates/`, matching the CLI's own safe default —
  `--apply` alone quarantines, hard delete needs the separate `--dedup-delete` flag, which
  the new web route will never expose), gated by `_check_read_only()`, CSRF-protected
  (explicit-token class, not the exempt spend-path class), with a real Undo (restores both
  the file and its `catalog.db` row) since the DC design has a real Undo affordance next to
  every resolved group and shipping Resolve without it would be a broken half-feature.
  Auto-resolve-all (multi-group in one click) gets its own extra confirm step beyond
  per-group Resolve, given the larger blast radius.

**Two real bugs caught live during Contact Sheet's browser verification**, both from testing
against the owner's *real* library rather than a handful of mock images (owner: "I had a
feeling ;) it's why I asked for some random selections"): a classic CSS grid overflow (a
grid item's `min-width:auto` default let a real large `<img>` force its column wider than
its track — the mock's placeholder art was too small to ever trip it), and a much bigger one
— printing produced ~8 near-solid dark blank pages, because the overlay was nested inline
deep inside `#root`, *after* the entire multi-thousand-image gallery grid in DOM order, and
`visibility:hidden` hides paint but not layout height — print pagination reflected the whole
hidden grid's real height, with the actual content buried many pages down. Fixed by
portaling the overlay straight to `document.body` (matching `ActionsMenu.jsx`'s own portal
precedent) so print CSS can hide `#root` outright instead of relying on visibility tricks.
Full detail in `CHANGELOG.md`'s `[Unreleased]` entry of the same date.

**Why.** Both scoping calls (matching-tier honesty, real-vs-advisory Resolve) were owner
decisions, not engineering defaults — recorded so a future pass doesn't quietly walk either
back. The portal fix is recorded because it's a real, non-obvious architectural pattern (the
only overlay so far that needs to print) that the next "print a modal" feature should reuse
rather than rediscover.

---

### Branding tab gated behind the real `under-the-hood` achievement — owner decision  ·  *2026-08-05*

Prior entries left this genuinely undecided: 2026-07-24's "Easter-egg PAYOFF is a separate
decision from the trigger" explicitly recorded that *"there is no code gate that earning
`under-the-hood` currently switches on... adding a real functional gate is a separate owner
decision."* Asked directly this session; owner, verbatim: **"Must Gate - We want to get that
groundwork done- Claude design did not have the specific code and gating info in context."**

Implemented as a single derived boolean in `useControlPanel.js` (`brandingUnlocked`, read off
`/api/achievements`' own real earned-state for the `under-the-hood` id — masked to a fake
`hidden-feat-N` id until earned, per that route's own docstring, so "no real id present" IS
the locked check, no separate flag needed) — gating the ✦ Branding tab button, its
Maintenance-tab quick-tile, and mobile's Branding tile identically on both platforms. A
`useEffect` forces `tab` back to `"maint"` if it's ever `"brand"` while locked, as insurance
against a future second entry point reopening the gate, not because today's single entry
point (the tab button) can actually reach it while hidden.

**Why.** Closes the exact gap the 2026-07-24 entry named, on an explicit, dated owner
instruction — not a default the code drifted into.

### Near-miss: the branding-drop sweep would have deleted real, already-shipped assets  ·  *2026-08-05*

The first version of `sweep_branding_drops()` (previous entry) scanned all 4 `BRANDING_SLOTS`
(`banner_main`/`banner_login`/`mascots`/`rewards`) plus `marks/`. It was built and tested
entirely against isolated pytest tmp_paths and this machine's own `branding/` folder, which
was empty before this session — so nothing caught that `mascots/` and `rewards/` are NOT
empty user-customizable buckets in the real, already-shipped app. They already hold a family
of specifically-named, role-bound files real code reads by exact filename: `gen_nel.png` (the
narrator mascot, referenced from `FolioOverlay.jsx`, `SetupWizard.jsx`, the classic template,
and more), `nel_carl.png`/`nel_micdrop.png` (Setup Wizard poses), `login_nel.png`/`.webp`,
`nel_shutdown.png`/`nel_restart.png` (the Power modal), `claim.png` (the header claim icon),
and a per-achievement `mascots/ach/<id>.png` chain with no fixed, grep-able list. `banner_main`
and `banner_login` had the same class of miss, just non-destructively: the real header/login
templates read flat files (`branding/banner.png`, `branding/login-banner.png`) that this
system's new manifest-based storage never wrote to at all.

Caught by the owner mid-session, not by any test — the full 1500+ test suite stayed green
throughout, because nothing in it guarded those specific filenames. Owner: **"I think you
reinvented the wheel a bit. the branding folder already exists... The entire tree is built in
the code already... Please be sure to check these things in codebase before starting brand
new backend work. some frameworks are in place."** Full audit (`grep` across both
`moonglade_gallery.py` and `gallery/src/`) confirmed the real tree; nothing had actually been
lost — this machine's `branding/` was empty before this session, every earlier test ran
against isolated tmp_paths, and none of this had reached the home machine, where the real
files live.

**Fix, live-verified twice:** `sweep_branding_drops()` now only ever scans `_SWEEPABLE_SLOTS`
(`banner_main`, `banner_login`) plus `marks/` — never `mascots`/`rewards`. Not a denylist of
known filenames (already proven incomplete by the per-achievement chain); the two folders are
excluded from the scan entirely until they get a real design. Verified in pytest
(`test_sweep_never_touches_mascots_or_rewards`, a hard regression guard) AND live against the
real server: planted files named exactly `gen_nel.png`/`claim.png` in the real `branding/`
folder, hit all three trigger routes several times, confirmed both survived untouched under
their own names.

**CLOSED, not open — see the 2026-08-05 correction entry below ("Mascots/Rewards permanently
excluded from Branding").** ~~Still open, needs a real product decision before Mascots/Rewards
can be anything more than excluded~~: the real `mascots/`/`rewards/` folders hold multiple
SPECIFIC named roles at once (narrator, login companion, shutdown pose, restart pose, claim
icon, per-achievement art) — not "many uploaded options, pick one active" the way `marks/` and
the two banner slots work. Owner confirmed exclusion is permanent, not pending a design pass.
Saved as a standing project memory (`moonglade-audit-existing-conventions-first`) so a future
session greps for existing conventions before building new backend storage, not after.

**Why.** The whole point of recording this in full, not just fixing it quietly: this is
exactly the class of mistake `docs/architecture.md`'s Invariants section and this file both
exist to prevent recurring — a plausible-looking new system that silently duplicates and then
destroys an existing one, caught this time by the owner's own knowledge of the real tree, not
by any test or review this session ran. The next session designing storage for anything under
`branding/` should read this before writing a line of code.

### Mascots/Rewards permanently excluded from Branding — owner correction, not a pending decision  ·  *2026-08-05*

The entry above ("Still open, needs a real product decision before Mascots/Rewards can be
anything more than excluded") framed this as open. Owner, reviewing the punch list directly:
**"Mascots do not get included in branding - this was made clear."** This is a correction, not
a new call: Mascots/Rewards do not get a slot-picker, upload flow, or any adoption path under
the Branding tab, full stop — not "pending a design pass," not "likely a checklist of named
roles," just excluded. `sweep_branding_drops()`'s existing exclusion of `mascots`/`rewards`
(the near-miss fix, same date) already matches this; only the doc's framing of it as open was
wrong.

**Why.** Standing rule: verbatim owner words only, never a manufactured "still open" where the
owner has already closed it. Leaving the prior framing in place risked a future session
re-opening a design-pass conversation for something already decided.

### Mascots-in-Branding: the exclusion was over-broad — owner correction  ·  *2026-08-06*

Owner, verbatim: "I think an older decision was misunderstood or mistakenly overturned.
Mascots were removed completely from the branding panel and my plan was to allow the
system mascots be customizable. Not Achievements - Just system."

Corrected reading of the 2026-08-05 rulings: what is permanently excluded from Branding
is **achievement-bound art** (the 57 badges, the per-achievement mascot poses under
`mascots/ach/`, tier art) — "one achievement never opens another's reward" stands. What
is IN scope for future Branding customization is the **system mascot/flair set**: the
named-role files real chrome reads by filename (narrator, login companion, Setup Wizard
poses, Power-modal poses, claim popup, the Job-Tracker spinner + status poses, the claim/
gift icons, the easter-egg set). Shape stays what the near-miss entry predicted: a
checklist of named roles to individually override, not a pick-one-active gallery. The
sweep still must not auto-adopt into `mascots/`/`rewards/` until that design exists — the
protection was right, the scope note around it was wrong. The art-inventory artifact is
being updated with a SYSTEM / SHARED / ACHIEVEMENT classification so the owner can mark
which roles become user-unlockable behind Under the Hood; that pick-list is the input to
the eventual design pass.

### Browse-from-disk: the 2026-08-06 "not blocked" correction was itself wrong — and a real scope  ·  *2026-08-07*

Answering a status check ("how are we on the lists"), I re-read the 2026-08-06
correction that reclassified Publish's omitted "⬆ Browse from disk…" control from
"hard blocker" to "buildable" (`uploadMedia` -> `/api/upload` -> `upsertArtwork`). That
correction was wrong too, on a different axis than the original claim -- and both
`PublishOverlay.jsx` and today's `PublishMobile.jsx` carried a version of the wrong
story until this entry. Corrected both header comments; this entry is the real scope.

**What the harvested contract chunks actually show** (`private/harvest/chunks/
contract-CfBjORe9.js`, not previously read this deep for this control):

- `createFromMedia` is a **REST** endpoint, not a GraphQL mutation — the 2026-08-06
  correction's own proposed fix (`upsertArtwork`) was never going to work; `upsertArtwork`
  only **edits an existing** artwork (`update_artwork` always sends `id: artwork_id`),
  it has no create-from-bare-mediaId mode. The real router: `a.prefix("/artwork")...
  createFromMedia: POST /from-media`, input `{mediaId (required), title?, isPrivate?,
  visibility?, tags?, tackIds?, hidePrompts?, extra?}` -- the same shape
  `publish_artwork_from_task`'s input already uses, just keyed by `mediaId` instead of
  `taskId`+`mediaIndex`. By exact structural match to the sibling `/kaisuuken` router
  (`a.prefix("/kaisuuken")...`, whose `/check` path is already live at `REST_API_BASE +
  "/kaisuuken/check"`), the real call is `_rest_post(session, "/artwork/from-media",
  body)` -- `REST_API_BASE` already resolves to `.../v2`.
- The endpoint's own contract **description** reads: *"Creates a new artwork from
  user-uploaded media. Requires authentication and Turnstile verification for web
  clients."* That is the server's own stated contract, not client-side UI copy.
- The **calling code** (`z(e,r){const t={}; return r&&(t["X-Turnstile-Token"]=r),
  S.artwork.createFromMedia(e,{context:{headers:t}})}`) only attaches the token when one
  exists -- consistent with either a soft/best-effort check, or a hard check that just
  always has a token in practice because it's only ever called from a page that solved
  one first.

Those two facts don't resolve to an answer by reading more code -- the contract's own
"Requires... Turnstile verification" line is real evidence FOR a hard gate that the
2026-08-06 correction didn't have (or didn't weigh) when it called this buildable.

**Scope, if it turns out to be buildable:**
1. Backend: `create_artwork_from_media(session, media_id, title, description, tack_ids,
   private, hide_prompts, extra)` in `moonglade_backup.py`, symmetric to
   `publish_artwork_from_task` (line ~7791) but via `_rest_post` instead of `gql_mutate`
   -- single attempt, no retry, same account-mutation discipline either way.
2. A new dedicated route, not an extra branch on `/api/myart/publish` -- that route's
   whole shape (`_artwork_row(mid)` lookup, task_id requirement) assumes a catalog row
   that an uploaded file doesn't have. Preview-then-confirm, same as every other
   account-mutating route here.
3. Frontend: the actual "⬆ Browse from disk…" button (currently absent, not just
   disabled) in both `PublishOverlay.jsx` and `PublishMobile.jsx` -- file input ->
   `/api/upload` (already free, already proven) -> the new route.
4. **Open product question, not mine to decide:** does a published-from-upload image
   join the local catalog as a new row (so it shows up in My Art / gets backed up /
   dedup-checked like everything else), or stay purely a PixAI-side publish with nothing
   local? Every other publish path here starts from a catalog row; this is the first one
   that wouldn't.

**Before any of #1-3 gets written:** one real, disclosed, single test call is the only
way to actually settle the Turnstile question -- calling the endpoint with a real
`/api/upload` media_id and no token, live. That would either 400/403 cleanly (blocker
confirmed, stays omitted) or genuinely publish something to the account (needs deleting
after, or keeping if it's a real image you want up anyway). It's real and account-visible
either way, so it's not something to run unilaterally -- next step is your call on
whether to spend that one test.

### OWNER RULING: the system-art pick-list — all 14 roles decided  ·  *2026-08-07*

The open "mascot/system-art pick-list" (waiting on owner since the 2026-08-06
correction) is DECIDED. The Art Asset Inventory artifact was rebuilt with live previews
of the real art + per-role decision controls; the owner worked through every card and
pasted the export back. Ruling, verbatim from the export:

**KEEP FIXED (never customizable):**
- Narrator (`mascots/gen_nel.png`) — ⚑ art needs work
- Setup Wizard poses (`nel_carl`/`nel_micdrop`) — ⚑ art needs work
- Hidden-feat mask (`mystery/secret_feat.png`)
- Easter-egg set (`ee_nelstarfall` + both oggs) — owner note: **"Never replaced"**
  (sealed permanently; do not re-propose)

**UNDER-THE-HOOD (user-customizable once the bundle lands):**
- Login companion (`login_nel.webp`)
- Power poses (`nel_shutdown`/`nel_restart`)
- Claim popup (`nel_redeem` — still not installed, see 2026-08-07 findings)
- Job-Tracker spinner (root `gen_nel.png`) — ⚑ art needs work
- Job status poses (`trk_done`/`trk_fail`/`trk_empty`)
- Claim pill icon (`rewards/claim.png`) — ⚑ art needs work
- Gift icon (`rewards/gift.png`)
- Drop-in logo (`logo.png`) — ⚑ art needs work · owner note: **"This should not be the
  default - Default should be Void Sentinel"** (= `marks/mark_4`, per marks.json). The
  bundle's default logo asset ships Void Sentinel, not the current logo.png art.
- Favicon (`favicon.png`) — ⚑ art needs work (opens up the previously-fixed
  "favicon stays the Gem Tome" call)
- PWA icons (`gallery/public/icon-*.png`) — ⚑ art needs work · owner note: "This is
  terrible" (note: PWA icons are the one git-tracked art set; customization implies a
  per-install build step — the UTH mechanics here need a design look)

**Art-redo work list (7):** Narrator, Setup Wizard poses, Job-Tracker spinner, Claim
pill icon, Drop-in logo, Favicon, PWA icons. No sealed achievement art was flagged.

**Orphans:** frames/ (feat + legendary) — DELETE → **executed**, both files + the empty
dir removed from the C: dev tree same day (zero code refs re-verified first; the loom
"frames" grep hits are storyboard shot-frames, unrelated). The D: run copy still has its
stale copies — notify-only rule, owner clears that side. ART.md rows updated.

**present_* tier mascots — DELETE ruling HELD, wrong premise found.** The inventory
artifact called present_common/rare/epic/legendary "orphaned, zero refs in shipped
code" — that was WRONG. `static/mg-notify.js:1056` builds the path dynamically
(`'/branding/mascots/present_'+mfall+'.png'`): it is the third rung of the achievement
toast's fail-soft mascot chain (`ach/<id>.webp` → `ach/<id>.png` → `present_<tier>.png`
→ no mascot), documented in moonglade_gallery.py:10573 and tests/test_branding.py:530.
A literal-filename grep missed the concatenation — the exact class of miss the
config-isolation standing rule exists for. All 57 ach ids currently have art, so the
rung only fires when an ach file is missing — which is a REAL case (the D: run copy is
exactly such a partially-copied tree). Deleting them doesn't crash anything (the chain
ends at "no mascot"), but it removes a live safety net, so the ruling went back to the
owner with the corrected facts instead of being executed on the bad ones.

**Re-ruled with corrected facts, same day: DELETE — executed.** Owner: *"Delete them.
We don't need a fallback anymore. we can mark that code as deprecated once the bundling
and transition is complete."* All four present_* files removed from the C: dev tree
(D: run copy notify-only, as with frames/). The mg-notify.js chain rung itself stays in
code untouched for now — it fail-softs through the 404 to "no mascot" — and gets marked
deprecated as part of the bundle-transition work, per the owner's sequencing, not
before.

### Job-tracker frontend redesign — DEFERRED to a design pass after the faithful notify port  ·  *2026-08-08*

Owner asked (before the notify port) whether a design change to the **job tracker specifically**
should go to design now or after. **Decision: port `mg-notify.js` faithfully first, redesign the
job-tracker frontend as a focused follow-up** — the same "built faithful, design pass pending"
pattern GalleryPicker already follows.

**Why.** `mg-notify.js` is two layers: the ENGINE (`Jobs.track` -- the spend-critical poller that
drives paid-generation completion, silent-death detection, per-job cost, QUEUED/ETA; plus `Ach`
and `Toast`) and the CHROME (the `#jobs-fab`, `#jobs-tray`, job cards). The faithful port moves the
*engine* to React verbatim; a redesign only restyles the *chrome*. Doing both at once would fuse a
redesign into the biggest, most spend-critical component and lose the "does the ported behavior
still match the old one" verify safety net a spend surface needs — and a restyle needs a locked
pixel mockup first anyway (STANDARDS.md Part 2 / the standing mock-before-code rule). So: (1) notify
ported faithfully → static/ empties → merge + v3.0; (2) the job-tracker redesign lands after, as its
own isolated change against the React component, with a locked mockup as the source of truth.

**Design exploration MAY start now, in parallel** — it's about the *appearance* of the FAB/tray/
cards, independent of the React internals, so it neither blocks nor is invalidated by the port.
Give the designer the CURRENT job tracker as the starting point (a real, recently-shipped surface:
silent-death detection, per-job cost, QUEUED + ETA, 2026-07-25) so the redesign is a deliberate
evolution, not a from-scratch guess. **Flagged so it is not lost when the port lands.**

### The asset container, re-scoped from scratch: format and delivery decided  ·  *2026-08-10*

The bundling effort restarted from a clean slate (all prior branches deleted, master the
only branch). The full intent, owner-dictated in chat and now the standing scope, is three
layers that must hold TOGETHER: (1) the app's default art ships WITH the app on every
install, out of the box; (2) ONE sealed container carries the art, the root-level JSON
defaults, and all achievement definitions -- protection bar is WoW-MPQ-class: opaque to
casual inspection, crackable by a determined power user who studies the format, and that is
accepted; (3) shipping the defaults sealed is exactly what lets `branding/` stay empty on a
fresh install (the existing discovery mechanic depends on that emptiness). Any design that
satisfies fewer than all three layers misses the point of the effort.

**Decisions taken (owner, in chat, after a 6-agent researched-options pass with two
independent fact-checkers -- every quota/price/library claim verified against primary
sources):**

- **Container format: a custom packed binary** -- Moonglade's own header/index/blob layout
  with an encrypted table of contents and encrypted slices; stdlib `struct`/`io`/`mmap`
  plus optionally `cryptography` for AES-CTR (which uniquely allows partial reads, so HTTP
  Range serving works naturally). Chosen because it is the only option where cracking
  requires actually writing code against the published reader. Rejected: encrypted SQLite
  (DB Browser's built-in SQLCipher prompt + the public key = a two-minute browse) and
  AES-zip (the file listing stays readable without a password, leaking names).
- **Delivery: GitHub Release asset + a first-run downloader.** Releases are verified
  2 GiB/file, explicitly no bandwidth limit, $0. A small committed manifest (container
  version + sha256 + ordered mirror URL list) drives it: on launch the app checks the
  local container against the manifest; missing/stale -> streamed download with progress,
  fingerprint verify, atomic rename, retry on failure; the app still runs undressed if
  offline. ~100-200 lines beside the existing loose-file-wins override layer. Git LFS
  explicitly rejected: 10 GiB/month bandwidth is ~25 downloads of a 400 MB file and then
  every user's fetch is blocked until the calendar flips, and each rebuild permanently
  consumes storage quota.
- **Distribution model: stay git-based now; a real Windows installer is BANKED, not
  scoped** -- when it comes, PyInstaller onedir + Velopack (MIT, delta updates make a
  400 MB payload livable). The downloader design above works unchanged under either model,
  which is why it goes first.

**Open, deliberately:** live-state JSON placement (owner: scope in naming pass Phase 2);
how far the achievement-definition move out of committed source goes (current-tree vs
history -- owner has not ruled); source-repo visibility. Build has NOT started -- owner
fenced implementation until an explicit go.

### P1 test-suite audit — two surgical fixes landed (spend-safety runtime tests + de-flaked pacing)  ·  *2026-08-11*

A three-agent read-only audit of the test suite on `master` (coverage gaps, test quality/flake,
frontend-e2e scope). Verdict: broad and well-documented; the two structural guards it was built
around (GraphQL spend-no-retry, Flask route-tiers) are genuinely catch-all. Two findings were
worth fixing immediately because they protect real credits and CI trust, and both are branch-
independent of the asset-downloader work:

- **The training/artwork account-mutations had only a SOURCE-GREP guard, no runtime test.**
  `submit_training`, `publish_artwork_from_task`, `update_artwork`, `delete_artwork` were listed
  in `test_spend_no_retry.SPEND_PATHS` (so `test_no_spend_path_calls_gql_adhoc_directly` proved
  they don't call `gql_adhoc`), but nothing exercised them at runtime -- deleting their
  `_check_read_only` line or making them re-POST would still have passed green, and in `test_panel`
  they are mocked away. Added real runtime tests: READ_ONLY refusal with `post.assert_not_called()`
  (`test_read_only.py::TestTrainingAndArtworkMutationsReadOnly`) and single-attempt via the
  `gql_calls` recorder (`test_spend_no_retry.py::TestSpendingPathsAreSingleAttempt`). Training is
  the sharp one: a re-POST after a lost response starts a SECOND LoRA training = a large real
  charge.

- **The request-pacing tests asserted on real wall-clock and flaked under load** (they were the
  lone red in the 2026-08-11 full run, clean in isolation -- the same class DECISIONS already
  noted flaking once). Root cause: the per-slot assertions compared `time.monotonic()` deltas
  between RECORDED timestamps, which measured OS scheduling jitter (the recording runs after the
  gate returns), not the gate. Fix: `_pace_gate` grew keyword-only `clock`/`sleep` injectables
  (resolved at call time when omitted, so production behaviour -- including anything monkeypatching
  `core.time` -- is byte-identical). The `TestPaceGate` unit tests now drive a FROZEN clock + a
  recording sleep and assert on the slots BOOKED (deterministic, hammered 8x); the integration
  tests keep only the aggregate-span lower bound (real `time.sleep` is a floor, so load can only
  push it higher, never red) and the serial-check keeps only its overlap assertion (concurrency,
  not speed). Same de-flake applied to `test_network.py`'s pool-pacing test.

Rejected doing more of the audit now: the container build-tooling gaps (`tools/build_container.py`
untested, the multi-block `_xor_at` path unexercised by units) and the Playwright DOM smoke layer
(D8, approved) are real but sequenced AFTER the bundle ships, per the owner. Landed on branch
`p1-safety-and-flake-fixes-2026-08-11` off master. Full audit detail was delivered in-session, not
transcribed here.

### The first-run download mascot ships INLINE, not from the container  ·  *2026-08-12*

Chicken-and-egg: the download screen ("Furnishing the Athenaeum") is shown WHILE the asset
container downloads, but its mascot was loaded from that same not-yet-present container
(`<img src="/branding/mascots/gen_nel.png">`) with no `onError` fallback -- so on a genuinely
fresh install it rendered broken, exactly on the one screen a first-timer always sees. Fix:
the mascot (`nel_wizard.webp`) is embedded as a base64 data-URI in `gallery/src/art/nelWizard.js`
and applied as a CSS `background-image`, so it ships in the app BUILD and is present before the
container is. This is the one deliberate exception to "default art lives in the container": art
shown *during* the fetch cannot depend on the fetch. Keep it inline -- do not move it into the
container to "tidy up," or the fresh-install bug returns. Only this download/checking-phase
mascot is inline; the interrupted/done status icons and the `nel_narrator` sync-screen mascot
still load normally (they appear after the container exists). The download screen got its OWN
classes (`wz-syncmascotart`, `wz-synchalo-steam`) rather than reusing `.wz-syncmascotimg`/
`.wz-synchalo`, which the narrator screen shares -- editing those would have restyled a screen
this change was scoped to leave alone. The glow's `wzHaloSurge` (9.1s, purple peak ~46%) is a
loose match to the webp's own steam surge, same period so they re-align each loop; it is
approximate by design, not frame-locked.

### First-sync achievement gate + a mid-sync exit from the wizard  ·  *2026-08-13*

Two first-run-wizard fixes, owner-directed.

**Achievements gated to first-sync completion.** `first-light` is `metric:images,
threshold:1`, and the notify system (mounted during the wizard) polls
`/api/achievements?mark=1`, so it celebrated the instant image #1 landed -- seconds into a
fresh install's first sync, with every image rung crossing the same way. Fix: a telemetry
flag `first_sync_done`. While it is unset, `/api/achievements` withholds `newly` (no toasts)
AND leaves `seen` untouched, so the rungs earned during the first sync are not lost -- they
fire together once the flag flips. The flag is set at `--sync`'s completion (in
moonglade_backup's `--sync` handler, after "Sync complete."); the wizard's "Sync now" job
runs that same `--sync`, so one setter covers both paths. **Backfill for pre-existing
installs is keyed on prior achievement recognition (`seen`/`earned_at` present), NOT on
images>0** -- an images-based backfill (the first cut we discussed) would flip the flag
mid-first-sync as the count climbs past zero and reintroduce the bug; any install that has
ever surfaced an achievement has non-empty `seen`/`earned_at`, a fresh mid-sync one cannot.
Fail-open if telemetry is unreadable (a broken gate must not hide trophies forever). Guarded
by `test_first_sync_gate_*` in test_achievements.py; two existing tests now set the flag to
model a normal post-first-sync install.

The "feel" (owner left it to me): the earned rungs **fire on completion** rather than being
swallowed -- a payoff at the right moment. **The ladder rungs themselves are being redone by
the owner -- do NOT touch the rung/threshold definitions as part of this; the gate is about
WHEN they fire, not WHICH exist.**

**Exit from the sync screen.** The wizard forced a wait through the entire first sync (only
"Enter the Athenaeum" on the post-sync ready screen let you out) -- brutal for a 35k-item
library. Added "Browse the gallery" on the sync screen (desktop + mobile) that reuses the
existing `enter()` nav. **Gated to appear once `progress.done >= 50`** to clear the
`catalog_empty` boot-bounce (next_gallery routes back into the wizard while images+videos==0;
sync inserts rows as it pages, so 50 is safely past that). Safe because the sync is a
server-side subprocess -- leaving the wizard doesn't stop it. **Still deferred:** the
background-sync progress chip in the gallery (Part 2) -- exiting relies on the existing
Activity tray for progress visibility until that lands.

### HARD RULE: easter eggs are DISCOVERED, never announced  ·  *2026-08-09*

Easter eggs and the features they unlock get **ZERO mention in any public artifact** — not the
public `CHANGELOG.md`, GitHub Release notes, `docs/`, `wiki/`, published Artifacts, or commit
messages. The Branding tab is gated by a hidden achievement, so it is **omitted entirely** from
anything public — not hinted, not genericized, left out. Also externally forbidden: the hidden
trigger mechanics, real achievement progress numbers, the roster count, specific achievement/feat
names, and how-to-earn thresholds. Internal record lives in git-ignored `private/EASTER_EGGS.md`.

**Why.** Owner rule, reiterated more than once and with visible frustration. Discovery IS the
feature; a changelog line describing it destroys the thing being built.

### Three achievements are permanently unearnable, and Completionist depends on them  ·  *2026-08-09*

`first-enhance`, `enhance-adept` and `full-toolbox` can never be earned: all three need the
`/api/enhance` path, which was removed, so nothing ever writes `"enhance"` into the `tools`
telemetry set. `full-toolbox` has no `banner_reward` key, so it sits in Completionist's required
pool too — **Completionist cannot be earned as it stands**.

**Why.** Recorded because an earlier "all metrics checked" pass missed `full-toolbox`, so the
count was believed to be two. The fix (exempt, repoint, or replace) is a live roadmap item, not
a decision already taken.


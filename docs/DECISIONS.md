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

**Where the other things live.** What shipped → `CHANGELOG.md`. How it works →
`docs/architecture.md`. How to work here → `CLAUDE.md`. Current state → ask the code:
`git`, `pytest`, `gh`, or a fresh survey pass. Art direction → `docs/ART.md`.

**Reading it.** Grep it, don't read it end to end. It is a reference, not a narrative.

**Adding to it.** Only when a decision's *reasoning* would otherwise be lost. If a future
reader could work it out from the code, it does not belong here.

---

## Contents

- [Standing rules](#standing-rules) &mdash; 61
- [Settled constraints](#settled-constraints) &mdash; 45
- [Rejected — do not re-propose](#rejected-do-not-re-propose) &mdash; 26
- [Design sources](#design-sources) &mdash; 29
- [Decisions](#decisions) &mdash; 130

---

## Standing rules

*How to work on this project. These are behavioural: violating one is a mistake, not a preference. Several exist because the owner had to say them more than once.*

### Archiving a doc must not bury its live items  ·  *2026-07-16*

When a doc is archived or consolidated, its live/unactioned items must be reconciled out first. The 2026-07-16 persona sweep's "PixAI power user + community member" bucket held live feature requests that went invisible the moment the file was archived — the same failure the audit-board reconciliation had already fixed once, recurring in a section reconciliation never reached. The sweep's other two persona buckets (Loom video creator, gallery curator) have never had that check and carry the identical risk.

**Why.** This is a repeat failure mode, not a one-off: archive-then-forget silently deletes decisions and asks. Recorded so the remaining unchecked buckets are known and so the next consolidation reconciles before it archives.

### Adversarial review before shipping generation-lifecycle changes  ·  *2026-07-18*

Generation-lifecycle/batch work is designed, then independently adversarially reviewed before implementation — twice in one case (a design agent's first attempt came back as an unusable placeholder stub; the rescue plan a reviewer wrote to replace it was itself reviewed a second time before anything was implemented).

**Why.** The passes caught real correctness bugs that testing would have missed or attributed elsewhere: stale React closures that would have made the tally never update, a busy-guard wired to an effect dependency array that could never fire, an empty-prompt check against the always-non-empty COMPOSED string (structurally incapable of triggering), a batchTally double-count, and missing genStartedAt persistence — plus a Critical that would have blanked the whole Loom on first render.

### Mio.2 (PixAI's agent surface) — an epic-sized bet, and do not capture cookies  ·  *2026-07-19*

Filed as a later epic by owner directive and deliberately moved OUT of open owner calls: it is an epic-sized bet, not a pending decision — stop presenting it as something to decide. It is cookie-authed (the API-key Bearer 401s), and the contract is bankable free from the site's JS bundle, but integration means a cookie-jar rewrite. Worth it only as a deliberate agent-UX bet. **Do not capture cookies without owner direction.**

**Why.** Reclassifying it stops it resurfacing as a decision the owner has to make again. The cookie rule is a hard boundary: cookie capture is a different, more invasive auth posture than the official API key the whole app is built on.

### Closed signup and deferred invite links are not reopenable via email  ·  *2026-07-20*

Web signup is closed by design, and invite links were deferred on the same reasoning (2026-07-20). Do not propose email as a way to reopen either.

**Why.** Both rest on the same premise as the no-email decision: a locally hosted install with physical access as the trust anchor does not need — and is not improved by — an outbound mail channel.

### Branding/mascots stays undocumented in the wiki  ·  *2026-07-21*

The wiki backlog is closed, and the branding/mascots page is deliberately never to be written. The README's one-line "make it yours" mention is the intended ceiling of public documentation for this surface. "Do not write that page."

**Why.** The branding surface is itself a hidden-feat trigger field: the Konami Starfall egg, picking the eclipse mark animation, and adding a custom mark file all set feat flags; the per-achievement mascot chain, reward art, and tier-SFX slots are unlock-moment surprises the feat system masks server-side. A wiki page inventorying marks/animations/mascots would put those spoilers directly in the user reading path.

### Element-level verification can be fully green while geometry is broken  ·  *2026-07-22*

Verification of a layout change must include sibling bounding-box comparisons or a real screenshot — not only text content and single-element computed styles. Alongside the layout fix, roughly 30 CSS rules with zero remaining producers were deleted rather than left in place.

**Why.** A stale grid class survived the redesign and auto-placed full-width sections into narrow tiled columns; the owner caught it on the live install as a scrambled, overlapping render. Every per-element check had passed. The dead rules were removed, not annotated, because they encoded the exact wrong mental model that caused the bug. Screenshot capture was unavailable that whole session, which is why nothing caught it.

### Roast/flavor text: do not resume work without the owner's explicit go  ·  *2026-07-22*

The reported leak of uncensored/"spicy" roast lines was deliberately NOT investigated further or fixed. The owner wants to look himself first and has flagged it for the actual design pass, not a quick patch. Only a read-only code check was made; no changes.

**Why.** His explicit scope boundary. Related standing rule: never audit or sanitize the owner's own product-copy language — the roasts and swearing are deliberate voice.

### Two persona buckets of the archived 2026-07-16 sweep have never been reconciled  ·  *2026-07-22*

Only ONE of the three persona buckets in `docs/archive/SWEEP_2026-07-16.md` ("PixAI power user + community member") was ever checked against current code and its live items recovered. The other two — Loom video creator, and gallery curator, roughly 18 more bullets — have never had that check and are still sitting in an archived file that project rules define as "historical record, never current fact."

**Why.** This is the exact failure the archive rule causes and that the audit-board reconciliation already had to fix once: live, unactioned requests become contractually invisible by being archived with work still in them. The pointer to WHICH buckets remain unmined is the only thing that makes them recoverable; without it, those ~18 items are lost silently rather than deliberately.

### "Earned rewards" display is LIVE — correction, not a TBD  ·  *2026-07-23*

Correction logged 2026-07-23: the "earned rewards" display was wrongly carried as an unbuilt idea. It is a real, shipped section in the Folio of Honors, currently showing **skin** unlocks only. The open item is a build-more question, not a shape question: extend it to cover **banner** and **icon** unlocks plus the easter egg. Standing preference for next time this comes up: **ask the owner to point at it directly rather than re-deriving its location from git history.**

**Why.** The item was mis-tracked as unbuilt across multiple passes. The ask-the-owner instruction exists because re-deriving from history is what produced the wrong entry in the first place.

### "Not single-user" was MISAPPLIED to block shipping the owner's own default art  ·  *2026-07-23*

A prior session argued against shipping the owner's own default branding using the "this is a public, not single-user, tool" reasoning. The owner is explicit that this was a **misapplication**: "not single-user" is about building real security/access strength for real external users — it is NOT a reason to withhold the app's OWN default branding from everyone who downloads it. The app ships the owner's default marks/banner by design.

**Why.** The rule exists to make access control genuinely strong, not to strip the product of its identity. Recording the misapplication is what stops the same argument being re-made against default art.

### A stray copy of the repo or its assets is a flag-to-owner, never a silent delete  ·  *2026-07-24*

If another copy of this repo or its assets turns up anywhere on disk, do not assume it's safe to ignore and do not silently delete it — flag it to the owner and confirm which copy is actually live before touching either. (A specific stale duplicate branding folder on the Desktop that once prompted this rule is confirmed gone, so it is no longer a live fact — but the rule stands.)

**Why.** Same caution as the D:/C: drift: the wrong copy can be the live one, and deletion is unrecoverable.

### An imperative DOM copy must reset every attribute it sets, not only set-when-present  ·  *2026-07-24*

The gallery's gating helper always resolves min/max to either the model's real bounds or the field's own default, rather than only writing them when the incoming model declares restrictions.

**Why.** Found live, not by reading source: switching FROM a restricted model TO an unrestricted one left the bounds stuck at the previous model's numbers. The Loom's declarative JSX never had this failure mode because it recomputes fresh every render — this is the class of bug an imperative mutation-based port is structurally prone to, so any future port of a declarative control needs this lens.

### Cost badge's compact attribute and cost event are public API, not dead code  ·  *2026-07-24*

The shared cost-badge component's `compact` attribute and its `mg-cost` event have no production consumer yet — by design, not as an oversight. Do NOT delete either as unused.

**Why.** Both are declared public API of a deliberately host-agnostic component. `compact` was built for the not-yet-wired cost-to-finish pill, and `mg-cost` is precisely the DOM-level signal that would carry a price update across the no-build-global vs. esbuild-module wall where the Option-A consolidation stopped. A future pass wiring the cost-to-finish pill or continuing that consolidation needs exactly this surface.

### One activity feed for every job source, logged fail-soft  ·  *2026-07-24*

All Job Tracker sources log to the same out_dir/jobs.jsonl activity feed: Control Panel actions, bulk cloud-delete, and a bare CLI run from a terminal (--sync, --update, --generate, --generate-video, plain download), each with a cli-<uuid> id mirroring panel-/bulkdel-. A panel-spawned subprocess logs exactly once, no duplicate entry.

**Why.** Logging is deliberately fail-soft "so a logging hiccup can never break the actual command" — the feed must never be able to take down the work it describes.

### Owner's verdict on the picker after pagination landed: performance is part of the feature  ·  *2026-07-24*

The owner reported scrolling was "still slow and a bit choppy" and called the picker "a step backward in function" after pagination shipped. The follow-up work treated both findings as genuine performance bugs, not correctness bugs.

**Why.** His words, and the lesson attached to them: the first round verified the feature *worked*, not that it worked *well*. The picker has already been rebuilt several times and he is fatigued with it — the speed of the original bounded grid is the benchmark, so any new picker chrome that costs scroll smoothness reads to him as regression regardless of added capability.

### Unsupported model controls are disabled, never hidden — and gating fails open  ·  *2026-07-24*

Advanced fields a model does not honor (negative prompt / steps / CFG) are disabled with a plain tooltip, using the model's real compatibility and min/max restriction data. Unknown or absent capability data leaves everything enabled — only an explicit false disables anything.

**Why.** An editable control that silently did nothing was indistinguishable from one that worked (e.g. one model ignores CFG entirely and runs steps fixed at 16). Disabling teaches; hiding hides the model's nature. Fail-open matches every other gate in this app: incomplete provider data must never lock the owner out of his own controls.

### Web surfaces register jobs — they never add a second poll loop  ·  *2026-07-24*

Every web generation surface (the gallery's Generate/Edit/Fix/Enhance tabs, the shared Generate drawer, and all four Loom submit paths) registers via Jobs.register() — registration without a second poll loop.

**Why.** Every one of them already owns a private poller hitting /api/task-status, which is the route that writes the authoritative terminal event. A second loop would duplicate traffic and create a competing source of truth.

### Derived constants are served to the client, not hand-ported twice  ·  *2026-07-25*

The upscale pixel ceiling and ratio cap are injected into the two pages that need them via a single marker rather than restated in JS; where a hand port was unavoidable (the drawer's live ratio math) it is pinned to the Python by a Node parity test.

**Why.** Only two of six templates share the base HTML, so a second hand-maintained copy would drift silently. The ratio ceiling is *computed* rather than a constant because the same upscale method allows a different maximum on a different source size.

### Do not build LoRA training as though it is settled  ·  *2026-07-25*

Whether a LoRA-training submit is accepted from an API key is NOT obtainable by reading — only by actually submitting. It is the same question panelplugin failed. Do not build a training feature as though the answer is known.

**Why.** panelplugin already proved a door the website walks through can be shut to an API key, so an unproven submit path is a real risk of building a dead feature. Reading the page yields everything except the one blocking fact.

### Historical records keep the old module names  ·  *2026-07-25*

Only half the docs move with a rename. Live instructions (project CLAUDE.md, the wiki's Backing-Up page, the state doc) change in the same pass or the release ships commands that do not exist. Historical record stays exactly as written: CHANGELOG entries and dated audit docs are not rewritten. Architecture docs and the wiki's Generating page were deferred by owner call.

**Why.** "A v1.9 entry naming pixai_backup.py is TRUE about v1.9." Rewriting history to use current names makes the record lie about what the software was called at the time. Live instructions have the opposite obligation — they must match the shipping commands.

### Host filesystem paths are withheld from non-local callers  ·  *2026-07-25*

Read endpoints that would reveal server paths return them only to a local session (the library-path GET, and the per-image metadata route withholds the filename field because it is a host-path fragment). Writes to config are localhost-only.

**Why.** Consistent with the existing Control Panel behavior — a LAN viewer is a trusted generator, not someone who should learn the server's directory layout.

### No percentage, progress bar or countdown for a PixAI generation — ever  ·  *2026-07-25*

There is deliberately no percentage, progress bar or countdown for a PixAI generation. What is shown is PixAI's own pre-submit queue estimate, recorded ONCE when a job is first seen queued, displayed as "est. Ns wait" and "Est. wait · Ns (PixAI, when queued)" beneath the live Time Spent — never recomputed as the wait grows, and it disappears once the job starts rather than becoming an implied render ETA.

**Why.** PixAI exposes no progress on a task — probed with a control, and no progress/percent/step/eta/queuePosition fields exist. Anything progress-shaped would be fabricated. The estimate is honestly labelled a WAIT, not a countdown, and must not survive into the render phase where it would read as an ETA.

### Packaged assets must keep a loose-file override layer  ·  *2026-07-25*

Any sealed asset container must keep an override layer — packaged defaults, loose files winning. Branding is drop-in today (a file dropped into the output branding folder is picked up) and "make it yours" is a shipped, intended feature.

**Why.** Design tension to respect: tidiness must not kill a shipped feature. Without the override layer, packaging silently removes user branding.

### Rename verification must exercise the command surface, not just tests  ·  *2026-07-25*

Verification of a module rename cannot be the test suite alone. Both renamed modules are runnable scripts; a green suite proves imports, not the ~116 documented command invocations, the desktop launcher's child command, or the Panel's subprocess runner. Verify the COMMAND surface separately.

**Why.** A passing test suite creates false confidence for this specific class of change: imports resolve while every documented command line, the launcher, and the Panel's subprocess path can all still be pointing at names that no longer exist.

### Safety documentation is exempt from the doc-debt deferral  ·  *2026-07-25*

All documentation touched by the module renames was frozen until after the naming pass — except `wiki/Deleting.md`, which was updated anyway because it described cloud deletion as task-level only. A safety page that under-describes a live irreversible action gets fixed immediately, deferral or not.

**Why.** Paying the doc cost twice is the reason for the freeze, and that reasoning is sound for command examples and architecture prose. It is not sound for a page a user reads before doing something unrecoverable — the cost of being wrong there is not rework. Stating the carve-out keeps a future freeze from swallowing the same class of page by consistency.

### The library-path setter never moves, copies or deletes anything  ·  *2026-07-25*

Setting the library folder only repoints configuration. It validates before writing, asks before creating a missing folder, refuses a path that is a file, and is pinned by a test that greps the handler for move/copytree/rename/unlink.

**Why.** Re-pointing a library must never be able to relocate or destroy the owner's archive as a side effect; the grep-test exists so a future convenience feature can't quietly add data movement to this path.

### 57-vs-60 achievement gap stays open  ·  *2026-07-26*

The gap is still open and that is fine. Owner, verbatim: *"Don't rush me LOL. We are thinking."* Do not re-ask.

**Why.** Owner is deliberately deferring; re-asking reads as pressure. Explicitly marked do-not-re-ask.

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

### No migration code for the branding move — do not add a shim  ·  *2026-07-26*

The branding relocation is a plain default change: no dual-read, no copy step, no fallback path. Owner, 2026-07-26: "I can move my own branding folder after the update."

**Why.** He relocates his own files by hand on the production install once the change ships. Worth stating because the obvious instinct is to write a compatibility shim, and he explicitly does not want one for a single install he controls. Do not add one.

### No spending mutation may ever be retried  ·  *2026-07-26*

Every mutation that spends credits or changes the PixAI account goes out through the single mutation helper that hard-codes zero retries and offers no retries argument at all, so the unsafe value cannot even be requested. Generate/edit/video/upload/delete-media all ride it. The generic ad-hoc GraphQL path's default was made document-aware as a backstop (0 for a mutation, 3 for a query), and the REST spend paths are pinned single-attempt.

**Why.** A lost RESPONSE (read timeout, dropped connection, a proxy 502 *after* PixAI had already created and charged for the task) made the retry submit and pay for a SECOND generation. Only the delete had been passing retries=0 by hand; every other spending path silently inherited three retries. The API cannot be trusted to be idempotent, so the safety has to be structural (no argument to get wrong) rather than per-path opt-in.

### Not every achievement gets a reward  ·  *2026-07-26*

Reward assignment is about choosing WHICH achievements carry a reward, not populating all of them. Owner, verbatim: *"We don't give a reward for every fucking one."* The 53 blank reward slots were never a gap to fill.

**Why.** Standing correction of a wrong framing that treated blank reward fields as missing work. Do not resurface the blanks as a completeness gap or generate rewards to fill them.

### Self-healing, not a button  ·  *2026-07-26*

The live mirror must recover from its own gaps automatically — a drop, a stale socket or a restart must not leave generations stranded until someone runs a manual Panel job. Owner's objection is the standard to hold: **"I know theres a fuckin button to do it but the point is... im not suppposed to have to."** The catch-up sweep is bounded and rate-limited so a flapping socket cannot become a request storm, runs off-thread so it never blocks the event loop, only collects tasks whose media is genuinely absent, and spends nothing.

**Why.** A push mirror only sees what completes while its socket is up, and reconnecting did not replay the gap. The existence of a manual repair button is not an answer — automatic recovery is the requirement, and the guardrails exist so automatic recovery cannot itself become an abuse of their servers or the credit balance.

### The antivirus exclusion is the owner's call, not ours  ·  *2026-07-26*

Do not add the Defender exclusion for the Pixeltable data directory ourselves. Catch the cold-start timeout and report it in plain language instead.

**Why.** "a security setting is not ours to change." The underlying facts: the postgres start timeout is 10s but a cold start here needs ~36s, nearly all of it syncing the data directory after a file sharing violation, and postgres's own hint blames antivirus/backup software. So a cold similarity search or rebuild can fail at the starting line with a timeout error that says nothing about the real cause.

### The Feats section is cloaked on purpose — do not "fix" it  ·  *2026-07-26*

With no feat earned yet, the whole Feats section correctly does not exist at all. Once the first feat lands, the section appears and the unearned feats show as mystery cards. Two states, not one. Owner, verbatim: "The feats are a true mystery until the first lands, then the unearned ones have the mystery card. That way unlocking them really feels like opening a new tier."

**Why.** Recorded rather than left to a code comment because the failure mode here is a HELPFUL fix: a sweep reads "section disappears", finds the mystery-tile art and style sitting right there apparently unused, concludes someone forgot to wire it up, and wires it up — destroying the reveal in the name of consistency. The mystery tile is not unused; it is waiting for the second state.

### V3.0 Lite instant video decline: do not close as fixed  ·  *2026-07-26*

Do not mark the V3.0 Lite instant-decline as solved. It was made diagnosable, not solved.

**Why.** Owner reported that submitting a video on V3.0 Lite from the gallery generator declines instantly with nothing appearing on PixAI's side, showing "PixAI's content filter blocked this generation — that's decided on PixAI's side, not in the Loom." His diagnostic instinct was the useful part: a real denial normally stays visible on their account for a while even for API generations, so nothing appearing there means no task was ever created. The doc's instruction is explicit — read the raw error and param shape from the log before theorising further. (Recorded beside a same-day entry that identified our own re-upload as the root cause of content-filter refusals; the warning still stands as written — verify from the log before declaring it closed.)

### `started is False`, never `not started` — unknown must stay unknown

Undispatched-job detection tests `started is False`, never `not started`. Absent `started` means *unknown* and keeps the ordinary spinner, so Control Panel / CLI / delete / import rows and any job logged before the feature are untouched. The reaper's caller passes the whole status dict, not just the phase string.

**Why.** "a status source that omits the field means *unknown*, and unknown must not brand every in-flight job stale." Passing the bare phase string instead of the dict makes the detection dead code in production.

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

**Why.** Cloud deletion is task-level — one selected image takes its whole batch — so the consequence has to be visible. "this makes the consequence visible, it does not replace a guard." The preview endpoint is read-only and makes no network call.

### D:/C: dual-checkout drift is a standing hazard — never mass-commit to "fix" it

The live gallery server runs from the D: run-copy, a separate checkout from the C: repo, with branding art serving from the D: tree. The two checkouts drift by design. Compare each one's latest commit before assuming they match, and **never mass-commit to "fix" the difference**. Art-in-progress lives in a separate D: scratch area (badge/icon/chibi sheets, the sorted Canva dump, cutouts, banners, stickers, app-icon candidates, plus the animated-webp build scripts); the served branding set stays live and separate from it.

**Why.** The difference between the checkouts is normal operation, not corruption — treating it as a repo to reconcile destroys either the live run-copy or real in-progress work.

### docs/ART.md is the one home for art direction

All art direction — badge style anchor, tier palette, frame direction, slot sizes, and the prompt bank — lives in docs/ART.md. It reconciles against the code, and where the code settles nothing it says so. Do not restate hexes or sizes anywhere else.

**Why.** Duplicated hexes/sizes across docs is exactly how the docs drifted; one home prevents two files describing the same pixel fact differently.

### Every skin reaches both surfaces

The Loom inherits the gallery's design tokens (--panel→--surface0, --ink→--text, --amber→--accent), so switching skin in the gallery header re-colors the Loom. Every skin reaches both surfaces.

**Why.** One design language across the app rather than per-surface theming.

### loom-core.js purity boundary; pricing is deliberately excluded

Pure Loom logic (flat, shotText, shotPayload, tag math, continuity, frameLinked, connectMeta) lives in loom-core.js as ES exports with no React, no DOM and no fetch. Pricing is deliberately NOT in this module — it is a network call living in the generation pipeline hook. The state layer above it is four composed hooks with pure reducers/classifiers/builders.

**Why.** Keeps the logic Node-testable with no browser or network; pricing can't be pure because it is a server round-trip, so it stays outside the boundary rather than diluting it.

### Marks render too small — a defect, not a taste question

Standing, recurring owner complaint since the beginning: marks render too small everywhere they appear in the app (the header being the current example). Treat this as a real sizing defect to fix alongside any mark-system work — do not relitigate it as a matter of taste or leave it as a cosmetic nice-to-have.

**Why.** The owner has raised it repeatedly and it keeps being deprioritized as cosmetic; classifying it as a defect is what stops that cycle.

### Never assume a model emits alpha

Do not assume Krea2 / ComfyUI / ChatGPT emit alpha — verify per FILE, not per model.

**Why.** Transparency claims are per-output, not per-tool; assuming per-model has burned the pipeline before (AI art ships fake/painted transparency).

### Never write the LOCALHOST route count in prose

The route-tier test is the authority for which routes are LOCALHOST; the prose deliberately carries no number and instructs the reader to trust the test over the prose if they disagree.

**Why.** A hardcoded count there had already drifted twice. Same family as the standing ban on writing the test count in any live doc.

### No visual build from prose alone

The "Locked design" items are closed: "Do not re-litigate these. Build against the named source, and verify against it before calling anything done." This is docs/STANDARDS.md Part 2's rule and it governs ANY user-visible surface — a visual build needs a pixel source (locked mockup artifact / Figma frame), never prose notes, and the verify pass compares against that source.

**Why.** A "locked" marker is a deliverable, not background. Prose-only builds landed off-target before (the Trophy Hall reformat), which is why the rule exists at all.

### Some maintenance commands are CLI-only by decision, not omission

Read the CLI-only list before filing a "no Panel button" item. The board has twice raised "maintenance commands have no Panel button" and both times the answer was already recorded. The recurring correction, stated once: a modifier (--embed-metadata, --convert) does not want a button; an already-integrated step (--faststart-videos) does not want a second trigger; and a repair tool (--backfill-meta) actively should not have one. reconcile-deleted likewise runs via the Panel's run route and the scheduler but renders no button by design.

**Why.** A button implies you ought to press it. Surfacing a repair tool or a redundant trigger invites users to run operations that either do nothing the sync has not already done, or that are not standalone actions at all.

### State doc is present-tense only — delete, never annotate

The state doc describes only what is true right now. When something stops being true, DELETE the line — "never strike it through, never mark it SUPERSEDED, never write 'was X, now Y', never append a correction beside the thing it corrects." There is no "shipped recently" or "landed on <date>" section. Never write a number a command can answer (test counts, commits-ahead, version strings) — name the command instead. Absolute dates only (2026-07-17), never "today"/"last week". A commit SHA is allowed as an *identifier* riding a present-tense fact, never as the subject of a change-story; prefer symbol names over line numbers. What shipped → CHANGELOG. How a decision was reached → git history + frozen copies in docs/archive/. How it works → architecture doc. Rules → CLAUDE.md.

**Why.** "a list of recent changes only ever grows, and that append-only growth is the exact failure this file exists to avoid." Its predecessor (docs/ROADMAP_LOOM_ACHIEVEMENTS.md, now frozen in docs/archive/) died holding 40 stale claims precisely because it was an append-only journal.

### The live audit backlog must NOT be archived until it is empty

`docs/AUDIT_2026-07-21.md` is the live backlog and must not be moved to `docs/archive/` while it still has work in it. It supersedes older per-defect bullets for anything it covers.

**Why.** This is the exact mechanism by which an earlier sweep doc lost three sections of live content: it was archived with work still in it, and the project contract makes `docs/archive/` "historical record, never current fact" — so roughly twenty real work items became contractually invisible until an audit went looking for them.

### The pure-stdlib cascade test is not a substitute for a rendering test

A stdlib helper resolves which CSS declaration actually wins (important, specificity, document order) from the served HTML so a cascade regression can't land unseen in CI, where the real-browser render harness always skips for lack of playwright. It is explicitly documented as strictly weaker — it proves the winner, not the pixels — and explicitly not a reason to skip writing a rendering test.

**Why.** Without it, a cascade regression could ship unseen on every CI run. With it, there is a temptation to stop writing browser tests; the doc closes that door on purpose.

### The tier test must assert that a LOCALHOST route refuses an authenticated NON-LOCAL session

The route-tier test enumerates the URL map, fails any route declaring no tier, and critically asserts that a localhost-tier route rejects a signed-in remote session. It is verified to fail when the gate is broken.

**Why.** The absence of that one assertion is what let three gate regressions ship in a single week. Enumerating tiers without proving refusal tests nothing.

### The tray renders from the job log, never from a poll response

The Activity tray renders from /api/jobs, never from a poll response. /api/task-status writes `started` into jobs.jsonl, and the tray draws a distinct QUEUED row (mascot with both animations stopped plus an uppercase `queued` pill) that flips to the ordinary spinner when a worker takes the job. The phase is written once per phase change, not once per poll, and the in-process de-dupe entry is dropped at a terminal phase so it stays bounded by in-flight tasks.

**Why.** Four pollers ask every 3s; a per-poll write would bloat the log and keep refreshing the `ts` that the orphan sweep's age check reads. Rendering from the log means the signal reaches both trays with no per-host wiring, since every submit surface's poller calls that one route.

---

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

### The Panel's "Stop this job" button is shown to every session on purpose  ·  *2026-07-27*

Stopping a maintenance job is localhost-only and server-enforced. The BUTTON is nonetheless rendered for every signed-in session, including LAN devices, which means a LAN user can confirm the dialog and then be refused. That is the owner's call and it stands: do not "fix" it by hiding the control.

**Why.** It reads like an authorization-UX defect to a fresh audit (it was filed as one), and the obvious repair — hide the button off `_is_local_request()` — would be wrong twice over: it moves a security rule into the UI layer where it cannot be trusted, and it makes the control's absence look like a bug to the owner on his own LAN device. The refusal is the correct behaviour; only the wording of it is ever worth revisiting.

### Masked achievements are not worth hardening before the asset bundle exists  ·  *2026-07-27*

`/api/achievements` masks hidden, unearned Feats to a `???` placeholder but leaves them in the array, so the COUNT of undiscovered feats is readable in the raw JSON. This contradicts the wiki's "no placeholder count… found by playing, not by reading", and it is deliberately NOT being fixed at the JSON layer.

**Why.** The achievement and branding assets are to be bundled into a package format (the MPQ-style container the owner has raised repeatedly), which changes what is discoverable at a level a response tweak cannot reach — anyone can read a JSON response, bundled or not, but the whole discoverability model shifts once the assets stop being loose files. Masking the array now is work thrown away against that design, and would also have to be undone or reconciled when the bundle lands. Revisit as part of the bundling design, not before. See [[Packaged assets must keep a loose-file override layer]].

### mg-generate-drawer must stay a build-free <script>  ·  *2026-07-18*

The shared generate drawer cannot import from loom-mutations.js (an ES module) and must stay a build-free <script>. Shared logic it needs (e.g. the friendly generation-error mapper) is a local, verbatim port, with a permanent parity test guarding the copy against drift.

**Why.** The component is framework-neutral and mounted by two different hosts; requiring a build step would break that. A duplicated-with-parity-test copy is the accepted cost of the constraint, not an oversight.

### OPEN OWNER CALL: /api/task-status conflates a local blip with a real PixAI failure  ·  *2026-07-18*

Flagged, deliberately not acted on: /api/task-status's exception handler returns HTTP 200 {phase:"failed"} for a transient local blip, which is indistinguishable from a genuine PixAI failure to either poll loop. Changing that endpoint's error shape is an owner decision that was never made.

**Why.** Left open on purpose rather than changed unilaterally — altering the error shape changes what every poller treats as terminal.

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

### The 57-roster JSON spoiler question is an open owner call, separate from the naming pass  ·  *2026-07-25*

`docs/achievements_roster_57.json` is 2.98 MB and committed to the public repo, so the whole roster is readable on GitHub — and no install-folder packaging un-publishes it. Verified 2026-07-25: **no runtime code loads that file** (its only reader is a dev-only board generator that already accepts a roster path), confirming the owner's recollection that it is the build-time record from when the 57 were designed, not a shipped asset. Moving it to git-ignored `private/` would remove both the breadcrumb and 2.98 MB from the repo, at the cost of one dev tool's default path. The real price: the canonical design record leaves version control, living only on the owner's disks, and would need to be inside his own backup. **This is the owner's call, and it is a SEPARATE change from the naming pass (which is rename-only).**

**Why.** Keeps the tradeoff intact — the objection is not technical difficulty, it is losing version control of the canonical design record. Also fences it off from the naming pass so scope doesn't creep. Server-side masking of unearned feats already works and is unaffected: cloaked entries have their metrics scrubbed before reaching any client, which is real protection precisely because those bytes never leave the machine.

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

After the owner earned the Triggered feat live (real play, screenshot in hand), the unleash flag genuinely flipped true, the toggle appeared, and the toast text matched the achievement's normal roast field word-for-word. Claude reported this as "expected — the toggle just hasn't been checked yet." The owner said that explanation is incorrect. What is specifically wrong about it was never established.

**Why.** Recorded so the next session does not adopt the toggle theory as a starting point without re-deriving it. Two live possibilities were never distinguished: (a) a genuine gating bug somewhere in the chain, or (b) the report describing what was on screen while the grid layout bug was still live — ladder tiers render twice (active-ladder grid and All Ladder Tiers), and two overlapping renderings could read as "two flavors shown for one achievement" with no roast-logic bug at all. The owner wants to diff the two roast fields himself on his work machine before anything is decided.

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

## The gallery top — LOCKED 2026-07-27

*The owner did the placement himself in a component editor. This is the source of truth for that
surface; a build verifies against it, not against prose.*

### The principle: sort by persistence, not by available space

The header is `position:sticky` and collapses on scroll, so the page has two zones with completely
different value. **Destinations** (Panel, Health, Contests, My Art, Publish, Folio, Profile, Sign
out, notifications) live in the transient upper banner — you use them on arrival, not while
working, so losing them to a scroll costs nothing. **Everything operational** (search, Media,
Collection, Per page, Blur, Select, Clear, Filter, Reset, Import, Generate, The Loom, credits,
brand, stats) lives in the strip that survives.

This was the owner's insight and it is better than three alternative headers that sorted by where
there happened to be room. Do not "tidy" a destination down into the persistent strip or an
operational control up into the banner — the split is the design.

### The filter bar is DELETED, not shrunk

There is no `.filters` row. Its contents went three ways:
- **out to the bar as pills/chips** — Media (three pills), Collection (chip), Per page (stepper)
- **into the advanced flyout** — Search prompt, Sort, Saved views, Model, LoRA, From/To dates,
  Min rating, Source, Tag/contest, Published only, plus the search-operator helper text
- **to Deep Focus** — Thumb size

`More` is gone entirely: once the bar it belonged to does not exist, it has nothing to reveal.
**Filter and Reset stay visible on the page** — owner's explicit requirement, for same-page
convenience.

### The advanced flyout is ANCHORED, never placed

Its position is derived from the search field: aligned to the input's left edge, ~6px below it.
There is no flyout coordinate to capture, and a fixed `y` is wrong — it must survive the field
being resized or the row reflowing. The **activator sits inside the search field at its right end**
(`Advanced ▾`). The editor could not drag the flyout low enough because a tall component was
clamped inside the stage; that was an artefact of the tool, not the intent.

### Metal, and why colour is rationed

Neutral controls take a **metallic** treatment — top-edge highlight, vertical gradient, seated
shadow, built from white-alpha over the skin's own surface so it re-tints with every skin rather
than being hard-coded. Applied to Clear, Select, Filter, Reset, Import, the search field, the
Actions menu header, and the five destination buttons.

**Colour means something and is not spent on ornament:** lavender = the primary action (Generate),
cyan = The Loom, gold = credits, red = destructive. Giving Filter/Reset/Select their own hues would
leave no hierarchy at all. Metal gives them physical presence without costing colour — and the
owner's hunch was right that it makes the themes read more strongly, because the metal borrows the
active skin instead of fighting it.

**Back glow on exactly three things** — Generate (lavender), The Loom (cyan), the credit badge
(gold). Nothing else glows, which is what keeps the glow meaningful.

### The Loom is cyan/teal

Driven by a single `--loomc` token. Chosen because it is already one of the Loom's own internal
palette aliases (so not invented), because cyan reads as screen/motion for a video surface, and
because it sits far from Generate's lavender so the two loudest buttons do not compete. **Known
collision:** cyan is also the "1 running" status pill — accepted, since that is a readout rather
than a button. **Coral** (`--peach`) is the banked alternative if the collision ever grates; it is a
one-line token swap.

### The persistent strip is 72px, not 62px

Raised from the live app's `--bnr-slim: 62px` because the owner fits two rows into it with nothing
to spare. Shipping it means changing that one token — the bulk bar's own JS reads the same value to
position itself, so both move in step.

### Banner composition is now a RULE, not a habit

Banners are **1920×480 (4:1), composed subject-left**, because the right side carries UI. Only the
bottom 72px is guaranteed visible. A banner with its subject on the right breaks the layout.
Note `banner_legacy.png` is 2048×1024 (2:1) and is **incompatible** with this rule. Also worth
knowing: the app caps display at 300px, so ~37% of every 480px banner is never shown — raising the
clamp is available at zero art cost whenever wanted.

### Control shapes: one language, three behaviours

Pills toggle (Media, Blur). Chips open menus (Collection, Sort where it appears). A stepper steps
(Per page — **deliberately not a slider**, because its values are discrete: 50/100/200/500, and a
slider makes 200 hard to hit). Same visual family, different mechanics.

The five destination buttons — **Panel, Health, Contests, My Art, Publish** — share one width
(112px, centred), set by "Contests" as the longest label, so the right rail reads as a set. The rail
steps evenly by 40px.

### Select all: CUT

Removed 2026-07-27. It looked like a capability and is only a convenience: `selectAll()` walks the
checkboxes **rendered on the current page** and *adds* them to the existing set — and the selection
lives in `localStorage` precisely so it survives pagination, which means **drag-select accumulates
across pages exactly the same way**. So its sole advantage over drag-select was one click versus one
drag, and the owner reaches for drag-select. `Select` and `Clear` stay, grouped ~8px apart.

Two wrong justifications were argued for keeping it before the code was read — that it selects
everything matching the filter (it does not, it is page-scoped) and that it uniquely accumulates
across pages (it does not, drag-select does too). Recorded so nobody re-derives them.

**Kept behaviour worth not breaking:** a fresh tab wipes the selection via a `sessionStorage`
marker, so a stale multi-page selection cannot be inherited and acted on by accident.

### The Actions menu

Appears only when a selection exists; placed left of the search field. Its eight items and the two
destructive ones in red are as shipped. **Its pill is a nudge smaller** than the other metal pills.

### Coordinates

The owner's own placement export lives with the design editor artifact. Treat the export as the
positions and this section as the reasoning — if they ever disagree, the export is the geometry and
this text is why.

## Design sources

*Mockups and artifacts that are the pixel source of truth for a surface. A visual build verifies against the named source — never against prose.*

### Moonglade Model Deck (mirror)  ·  *2026-07-11*

https://claude.ai/code/artifact/9f16f42d-2541-4dd9-935a-0f9d0f39c7c4 — the model research deck. MIRROR — docs/archive/MODEL_DECK_2026-07-11.md is truth (and is frozen, dated external research to re-verify before relying on).

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

### Mobile Gallery — working port of the Figma Make mock  ·  *2026-07-26*

https://claude.ai/code/artifact/e0ce50a0-2475-48e2-adc0-efceee17d518 — the phone layout and pixel source for the mobile design pass: 3-tab shell (Gallery / Create / Control), 5 skins, 160px stats hero, 2-column staggered grid, lightbox, and the full Control tab. Status: Current DIRECTION for the mobile pass, NOT locked. The local copy is git-ignored, so THE ARTIFACT IS THE DURABLE COPY; refreshed 2026-07-26. It predates a lot of shipped work (upscale panel, art filters, the LoRA row and its architecture-aware weights, the Job Tracker, boosters, Mode, seed, picker sources/filters), so bringing it to parity is the FIRST job of the design pass — not something to build from as-is.

**Why.** It is a REVIEWED port, not a raw Figma dump, and the only durable copy exists as the artifact. The "not locked / parity first" framing stops someone treating a stale mock as a spec.

### Other captured facts from the LoRA training page  ·  *2026-07-26*

Model Theme offers Illustrious-v1.0, NoobAI XL, Hinata v2, Illustrious-v0.1 and more. Dataset sources are upload, import from generation history, or reuse a previous dataset. Rebates go up to 5% of credits when others generate with your LoRA. Membership grants 3 / 5 / 10 free trainings per month for Starter / Plus / Premium.

**Why.** Captured surface facts about their product that our code cannot answer. The rebate is also the reason notifications were wanted — it is how you learn someone used your LoRA.

### Their site sends video fields we do not (unprobed)  ·  *2026-07-26*

From the same task dump: their website sends width/height (1536x864), a channel value of "private", and an empty lora object, and it OMITS the audio-generation fields we always send. Our own video-parameter builder's comment asserting there is no channel field is demonstrably false. Unknown whether any of it matters — probe before assuming.

**Why.** Measured evidence off a real task, not inference. Kept so the false in-code assertion isn't trusted again and so the discrepancy isn't re-discovered from scratch.

### Badge Prompts v2 (parked mirror)

https://claude.ai/code/artifact/771f84d9-cacb-4f5c-8300-9c8575fb8431 — the badge prompt system. PARKED mirror; the live home is docs/ART.md §5, with the original in docs/archive/badge_generation_prompts_2026-07-16.md.

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

https://claude.ai/code/artifact/31d6c68a-bd54-4824-886f-9017c6012912 — the 57-achievement three-lane voting board. Votes are complete; it is the MODEL for any new board, which should be built from docs/achievements_roster_57.json.

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

### Scouted read-only community surface (banked, not built)  ·  *2026-07-04*

Reachable read-only community data already scouted and never folded into the plan: per-artwork **view counts, which dwarf likes** (one probed post: 345 views vs 4 likes), lifetime task/credit/follower stats, the full contest catalog (now partly surfaced), a notifications/engagement feed carrying LIKE/FOLLOW events only with **no actor identity**, and server-side bookmarks mappable to local collections.

**Why.** The view-vs-like ratio is the interesting finding — it says view count is the meaningful engagement signal to surface, not likes. The missing actor identity is a hard limit on what any notifications feature could ever show.

### Model lanes for badge/ornament art  ·  *2026-07-11*

Model strategy is banked in the frozen docs/archive/MODEL_DECK_2026-07-11.md and must be re-verified before being relied on (it is dated external research). Krea2 on Maestro is the local quality lane for ornate frame/ornament work. The badge benchmark is PixAI Tsubaki.2 v1 with detailed prose and NO LoRA — the Hoardsmith dragon, task 2031115782282256404.

**Why.** Gives a reproducible benchmark (a specific real task, a specific model+no-LoRA recipe) so badge art quality is judged against something concrete instead of re-litigated per session. The deck is external research with a shelf life, hence the re-verify caveat.

### Epic C — Publish & Community: publishing is gated on DELIBERATENESS, not cost  ·  *2026-07-15*

Roadmapped into the next core + web passes; independent of Epics A/B, no provider-seam prerequisite. The publish/like/bookmark/follow operations are reverse-engineered and documented privately but are **deliberately off** — this epic changes that default on purpose. Scope: **publish first** — a CLI publish flag plus a Publish action on the gallery detail page/lightbox, explicit-confirm gated exactly like delete. **The gate is deliberateness, not cost: publishing is free.** Never a background or automatic action, never default-on for a batch. Like/follow only if a concrete use appears. Distinct from the read-only published-history sync.

**Why.** Publishing costs nothing, so the usual spend-guard rationale doesn't apply — the guard exists because putting the owner's work in public is irreversible in a social sense. That's why it can never be automatic or batched-by-default even though it's free.

### One storyboard surface — Classic V1 Loom retired  ·  *2026-07-17*

The Loom is a single storyboard surface: the V2 shell. Classic V1 (its render tree, the `v2` toggle, and the CardView/CardEditor components) was retired; /loom opens straight into the V2 shell with no layout switch.

**Why.** Deliberately no layout switch to choose between or maintain — one storyboard surface rather than a V1/V2 toggle.

### Completions route by the shot id captured at submit time  ·  *2026-07-18*

A generation completion handler routes via the shot id captured at submit time, not whichever shot happens to be selected when the result/error event fires. The drawer's prompt/image/video/audio reference slots CLEAR (not just overwrite) when the newly-selected shot/draft has none.

**Why.** Switching shots mid-render used to attribute the finished clip to the wrong card, and switching from a shot with cast refs to an empty draft left the previous shot's images sitting in the drawer, ready to submit against the wrong generation.

### Elapsed time alone never marks a generation failed  ·  *2026-07-18*

A shot only enters a terminal status:"error" on a real server-reported failure — elapsed time alone never does. Both independent poll loops escalate through three tiers instead: 20min downshifts cadence and shows "Taking longer than expected"; 90min downshifts further and shows "Still going after Nh — unusual"; a 6h ceiling stops that tab's polling but leaves status/pendingTaskId untouched (genState phase "paused"). A reload, or clicking the card's own "paused" badge, always grants a fresh budget.

**Why.** A slow-but-alive render is indistinguishable from a dead one by clock alone, and wrongly branding it failed destroys a real in-flight generation's tracking. The ceiling protects against a permanently wedged/deleted task without asserting failure. The multi-hour escalation was verified by code review plus the adversarial-review pass, not literally clocked in real time.

### Generate drawer width is 560px — owner's explicit pick  ·  *2026-07-18*

The Generate drawer is 560px (widened from 380px). Side rails collapse to 52px icon strips; the left card widens to 560px only on the Cast tab's Detailed density, staying 280px for Simple mode and the Footage tab.

**Why.** The exact point at which all 6 Multi-Reference image-ref slots fit in one row is 500px; 560px leaves real breathing room past that bare minimum. This was the owner's explicit pick, made against a live slider mockup, during the 2026-07-18 design-mockup pass.

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

### Generation Flags — owner demanded a scope call, recommendation is shrink or drop  ·  *2026-07-19*

Owner, refusing another deferral: *"either we keep deferring this or it's actually done. WHAT is the scope."* Recommendation on the table: **shrink or drop**. The only version that is concrete and nearly free is *"flag near-duplicate generations"*, answerable with the existing CLIP index and no new dependencies. Anatomy / artifact / NSFW detection is a research project rather than a backlog item and should be named as one or dropped. It is **not** the shipped "Similar / more like this" search, and it is not dependency-free in its large form.

**Why.** The feature had zero code, no spec, and two unanswered product questions (what a pass flags, and where the verdict lives) — the owner's point is that an item in that state should be scoped down to something real or removed from the board, not deferred a fourth time.

### The Design Pass is one consolidated effort  ·  *2026-07-19*

Owner decision: the Loom visual-refinement pass, the gallery search-bar redesign, and the owner's layout/function note-taking pass were tracked as separate items but are ONE coherent visual effort — scope and execute them together rather than piecemeal. The Folio of Honors redesign was the deliberate exception: it went ahead alone because it had a finished design in hand while the others didn't. Grouping the remaining items is about execution order, not about collapsing them into fewer decisions — each still has its own open owner call.

**Why.** Piecemeal visual work produces a patchwork; one pass produces one design language. The Folio exception records the rule for splitting one out: a finished design in hand beats waiting for the group.

### Deep Focus preview size is a width question, not a number bump  ·  *2026-07-21*

Owner, 2026-07-21: Deep Focus previews are too small to read what you attached — a frame or an @tag reference is often unidentifiable at a glance. The real constraint is the panel's own max width, not the two thumbnail rules. **Treat this as "how wide should Deep Focus be, and what does it show at that width", not as a one-number bump.**

**Why.** Bumping the thumbnail heights inside a narrow panel cannot fix it; the panel caps how large any preview can get. Framing recorded so the fix isn't attempted as a CSS one-liner.

### Faststart remux is deprecated in place, CLI-only  ·  *2026-07-21*

--faststart-videos stays CLI-only and is deprecated in place by owner decision (recorded as D-6 in the 2026-07-21 audit). It is a one-time remux for videos downloaded before the auto-faststart path shipped.

**Why.** Every current video-acquisition path already performs the faststart step at collect time, so there is nothing left for a Panel button to do going forward — only the historical backlog, which is a one-time job.

### "Trophy Hall" is now "The Folio of Honors"  ·  *2026-07-22*

Renamed 2026-07-22, the owner's own pick off the rename shortlist.

**Why.** Owner naming choice — the surface, structure and CSS scoping were unchanged by the rename.

### 9-slice tier frames wrap legendary/feat grid tiles too — the answer to "frame or defer"  ·  *2026-07-22*

The redesign resolved the previously-open question by framing legendary and feat grid tiles with the same served frame assets and slice values as the unlock toast, applied as an overlay div rather than a border-image on the card itself. Adding epic later is a one-key change to the framed-tier set.

**Why.** The overlay approach is required because the card still needs its own border for the non-framed tiers. Recorded so the frame-or-defer question is not re-opened as if undecided.

### A ladder's representative badge is its FIRST rung's art, not its top tier's  ·  *2026-07-22*

Each ladder in the selector row shows the badge art of its first rung.

**Why.** The top tier's art is a spoiler. Chosen deliberately over the visually flashier option.

### Cost badge is an added preview, never a replacement for the confirm gate  ·  *2026-07-22*

The three Loom Deep Focus tabs (Image/Edit/Reference) each kept their existing confirmSpend/window.confirm gate alongside the new shared cost badge, deliberately. The badge is an added preview, not a replacement.

**Why.** That confirm dialog is this project's original fail-closed guardrail, built specifically after those exact tabs used to lie about cost. Removing it in favour of a display-only badge would remove the guardrail and keep only the thing that was previously wrong.

### Feats score zero points  ·  *2026-07-22*

Points are tier base + 5×(rung−1) (common 5 / rare 10 / epic 25 / legendary 50 / feat 0), rendered on the toast, the tiles, and a Warband-style header total.

**Why.** Feats scoring 0 means the point total can never hint that a hidden feat exists — the same reason earned timestamps are recorded for earned ids only, and masked feats keep name and description masked server-side.

### Masked feats show their art in full color, not grayscaled  ·  *2026-07-22*

A masked feat displays the cloaked mascot art at full saturation while its name and description stay masked server-side.

**Why.** Deliberate art direction — the mystery is carried by the cloaked subject and the withheld text, not by desaturating the badge.

### Per-criteria checklists only exist for closed-universe sets  ·  *2026-07-22*

The two set masteries with a finite, enumerable criteria list (edit/enhance/fix; i2v/flf/r2v) render per-criteria checklists. Open-ended sets stay count-only.

**Why.** A checklist implies a complete, knowable list; showing one for an open-ended set would misrepresent what remains.

### Picker favorites re-sourced from real PixAI bookmarks  ·  *2026-07-22*

Model/LoRA favorites + recents in the picker were originally scoped local-only ("server-stored like Snippets"); the owner's 2026-07-22 ask instead wants them sourced from the user's REAL PixAI bookmarks. That re-scope folds the item into the Epic C (publish/community) surface rather than leaving it a free-standing small item.

**Why.** Changes the item's size and dependency: it is no longer a local-storage nicety but depends on bookmark operations whose existence is itself contradicted between two private recon docs, so it needs a probe before scoping.

### Roast NSFW text is double-gated: earned feat server-side AND a local preference  ·  *2026-07-22*

The spicy roast field is blanked server-side for every achievement unless the Triggered feat is earned on that account, and the client shows exactly one roast string per card — the spicy one only if the server sent a non-empty value AND a separate local "Unleash the AI" preference is checked.

**Why.** The server gate is account state; the local toggle is a per-device preference. They are deliberately independent so earning the feat never forces the spicier voice on someone who didn't opt in on that device.

### Self-removal stays LAN-reachable; removing anyone else requires a local request  ·  *2026-07-22*

Removing your OWN account is allowed from any signed-in session (it can only harm the caller); removing anyone else's is refused unless the request is loopback. Enforced inside the handler against the session identity, because the tier table cannot express this structurally.

**Why.** Owner's explicit choice on scope. The fix was needed because any LAN session could previously remove ANY account by name (the only guard was "not the last one left"), so a borrowed-tablet guest could evict the owner and — before the matching add-user fix — register itself a fresh persistent login in the same motion.

### The Folio stays a maximized overlay, not a separate page  ·  *2026-07-22*

It is the same maximized overlay grown from the existing achievements modal — tabs, main grid, right rail (category nav, now click-to-filter rather than only scroll-to, Within Reach, Relics, mascot alcove), collapsible sections, search, mobile stacking. All its CSS is scoped so the contest and art modals sharing the same panel class are untouched.

**Why.** "Maximized overlay" was the locked decision; drifting to a new page has been a repeated mistake. The CSS scoping is what keeps a Folio redesign from restyling unrelated modals.

### "Toast badge grows to its home marker" was a real REGRESSION, not an unbuilt idea  ·  *2026-07-23*

Correction to this document's own earlier framing. Owner: *"this was actually live until the achievement revamp debacle... one of the lost facts."* It shipped and was lost when the Trophy Hall got reworked. A quick archaeology pass did not turn up the specific grow-to-marker animation in the suspected commits — this needs either the owner's git-archaeology guidance or a fresh re-description from him, **not further guessing**.

**Why.** Filed as an "unfinished idea" it would be re-designed from scratch; filed as a regression it gets restored. And the guessing pass already failed once, so another one is waste.

### Continuity "linked" badge is positive-only — no "not linked" warning  ·  *2026-07-23*

A board card shows a small "linked" badge when its opening frame already matches the previous shot's closing frame. It is silent/positive-only — there is deliberately no "not linked" warning state.

**Why.** "most shots are deliberately disconnected from their neighbor" — a warning would fire constantly on correct storyboards. Note: the owner had not yet visually confirmed this as of the doc; built 2026-07-23, exact placement/behavior is a first cut pending his look.

### Epic-tier frame art — premise itself is on the fence  ·  *2026-07-23*

Deferred to the Design Pass. The owner is now considering REMOVING the ornate per-tile frames from Legendary/Feat entirely rather than adding a matching Epic one. The previously banked "deep-purple WoW epic / tier-gear" direction is shelved pending that bigger question — do not build it.

**Why.** The question changed from "what should the Epic frame look like" to "should tier frames exist at all", so producing an Epic frame would be work against a premise that may be dropped.

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

### Easter-egg trigger redesign — three scoped options, none picked  ·  *2026-07-24*

Scoped but explicitly NOT chosen (needs the owner's go): (1) **Non-default mark, not just any mark** — keep file-drop detection but compare against a known shipped-default set. Smallest change, but only answers objection (2), not (1): a stranger still has to already know the file-drop mechanic exists. (2) **First visit to an internals-only surface** — fits the name more literally; easy to detect; risk is that the Control Panel is core to running the app day to day, so it may not read as "hidden" enough to feel like a real find. (3) **A genuine hidden technical action** — a devtools-console-only hook, an undocumented CLI flag, or an unlinked API route/param. Closest to the name and the roast text ("you opened a door you had no business finding"), and fully decoupled from the branding-defaults problem; an existing whitelisted front-end event-beacon mechanism can carry it with one new event name, so it is less new infrastructure than it sounds. Its tradeoff is several sub-choices with different discoverability profiles.

**Why.** Each option was weighed against the owner's two specific objections; keeping the tradeoffs means the next pass picks rather than re-scopes. Option 3 is the only one that survives both objections cleanly.

### Existing epic-tier skin achievements are the natural bundle anchors  ·  *2026-07-24*

Observation offered to the owner, not a decision made for him: the app's only three skin-gated achievements are all epic-tier ladder rungs, and their skin ids already line up with three of the four bundle themes (Moonlit Silver, Embercourt, Verdant Grove). If the owner wants to reuse rather than reassign, those three are the natural anchors for those bundles' skin half. Only Nightfallen has no existing achievement anchor at all.

**Why.** Preserves the reuse option so a future pass doesn't reassign skins from scratch and accidentally orphan three already-working gates.

### Picker pagination uses the Relay cursor spec already in use, with one opaque cursor at the API edge  ·  *2026-07-24*

Forward Relay-cursor paging was added to the market search (the query previously asked for hasNextPage but never endCursor and accepted no after argument). The search endpoint takes a single opaque cursor the client just echoes back; the route decides per-request whether that means a real GraphQL cursor or a plain offset.

**Why.** The same Relay Connection spec already backs task-history paging in the reverse direction, so this is the app's existing mechanism rather than a guess. Keeping the cursor opaque means the client never needs to know which backend path is serving it, so the two paths can't diverge into client-side special-casing.

### Pre-bundle reward markers must be RECONCILED, not extended alongside  ·  *2026-07-24*

The handful of achievements already carrying an ad hoc reward marker (a bare skin id, or a bare banner boolean with no specific banner named) predate the bundle design and each carry only one piece of a bundle. They need reconciling INTO the new reward fields — not left sitting alongside them as a second parallel system.

**Why.** Leaving both means two competing reward mechanisms in one roster; the honest assessment is that 0 of 57 are fully assigned under the new design, a few are partially assigned and misleading, and the rest are blank.

### Reward field named `reward_kind`, deliberately NOT `reward_tier`  ·  *2026-07-24*

Scoped shape only (not built, not populated): add **`reward_kind`** (`none`/`icon`/`skin`/`banner`) plus **`reward_id`** (a string bundle/asset pointer, e.g. `"nightfallen"`, empty when kind is `none`) to each achievement. No new TIER field is needed — a prestige `tier` field already exists. Two achievements sharing one `reward_id` is what expresses "these unlock together as one themed bundle", so a bundle doesn't have to be forced onto a single achievement. Optionally a top-level `bundles[]` catalog gives each theme one place to name its actual mark / skin / banner asset.

**Why.** The name `reward_tier` (which the audit's own phrasing suggested) would collide with the existing prestige `tier` field — they are related concepts but not the same one, and conflating them in the schema is exactly the confusion this design is trying to escape. Populating the fields is explicitly the OWNER'S creative call, not an implementer's.

### Reward-bundle ledger — every mark/skin/banner pairing decided so far  ·  *2026-07-24*

Bundle themes as decided: **(default)** Void Sentinel mark, ships free/ungated. **(removed)** Gem Tome — delete from the mark roster. **Nightfallen** — Moonwell Eclipse mark + Nightfallen skin (currently free) + banner #100. **Verdant Grove** — Vine Crescent mark + Verdant Grove skin, no banner picked yet. **Ember Court** — Winged Crescent mark (art not remade yet) + Embercourt skin, no banner picked yet, blocked on art. **Moonlit Silver** — skin picked plus a banner generation task, no mark picked yet. Standalone: **banner #62 is the current live default**, already shipped and not tied to any achievement.

**Why.** This is the compiled, cross-checked record of pairing decisions that previously existed only scattered across an audit doc and prose; it is the thing that stops the pairings being re-picked from scratch.

### Shared components replaced the hand-rolled duplicates outright  ·  *2026-07-24*

<mg-model-picker> and <mg-gallery-picker> are framework-neutral custom elements mounted by BOTH surfaces: the Loom via ref-callback bridges, and the gallery's own Generate tab and image picker via the same mount/unmount pattern. They replaced the old hand-rolled duplicates outright "rather than adding a third copy alongside them."

**Why.** Avoids a third parallel implementation of the same control; one component, many hosts.

### The Gallery's simpler resolve guard is canonical; both surfaces match it exactly  ·  *2026-07-24*

The Loom's extra "same model id" condition on top of the sequence-counter guard was removed so its version-resolve guard is identical to the Gallery's.

**Why.** Confirmed by the owner testing the same model on both surfaces — the Gallery showed a version dropdown, the Loom didn't. The extra condition was redundant for the superseded-pick case the counter already handles, but a real liability for anything else touching model state mid-fetch: it dropped the whole versions/compatibility/restrictions payload with nothing visibly wrong. Divergent guards on two surfaces of one component are a defect source.

### The LoRA cap is a soft pre-submit guard, not a block inside the picker  ·  *2026-07-24*

Both surfaces show a live "N / cap" count (red once over) and disable Generate with a "remove N to continue" message; the picker itself still lets the pick happen. The comparison is one shared pure function, mirrored by identical inline gallery logic.

**Why.** Refusing the pick in the picker would leave a card visually selected in the picker's own multi-select state that never actually landed in the host's LoRA list — the exact reason the old 6-LoRA cap was never reproduced during the picker migration. Disabling submit keeps the UI truthful.

### A Fix is named from the SOURCE image, and empty chat-task fields show an em-dash  ·  *2026-07-25*

A Fix output is named <source-prompt>_fix-face_<task>_<media> from the SOURCE image, not from the fixed template prompt PixAI writes into every fixer task. Its Model resolves to "Reference Pro" while Seed/Steps/Sampler/CFG stay empty. Naming applies to NEW output only — nothing is retroactively renamed.

**Why.** PixAI stamps every fixer task with the same template prompt, which would make every Fix identically and uselessly named. "a chat task records none of them, and an em-dash is the honest answer" — inventing plausible sampler values would be a lie.

### Asset packaging is explicitly NOT DRM  ·  *2026-07-25*

The banked "package the assets like an MPQ" idea is a possible epic and is NOT scoped. Its goal is breadcrumb reduction plus presentation, not protection. Owner, verbatim: *"if someone pokes around and just reads a json file all the secrets are out. just not trying to leave breadcrumbs."* Plus the presentation goal: a tidy install that reflects the work.

**Why.** Framing it as DRM invites the wrong design (and the wrong argument). The owner's bar is "don't leave breadcrumbs lying around", which a container meets and DRM-thinking overshoots.

### Cloud delete happens before the local purge, never after  ·  *2026-07-25*

Per-image deletion calls PixAI first and only purges locally on a clean return.

**Why.** The reverse order would leave a catalog hole for an image PixAI still has — the local archive must never be missing something the cloud still holds.

### Documentation debt deliberately deferred until after the naming pass  ·  *2026-07-25*

The architecture doc and the generating wiki page are knowingly stale (missing wave-2 surfaces, and thick with the old module names) and were left that way on purpose until the rename lands.

**Why.** The naming pass renames the very modules those files are full of, so updating them first would be paying twice. Deferral is a decision, not neglect — but the debt is owed, not forgiven.

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

### Naming pass: flat names, no shims, package folder later  ·  *2026-07-25*

Owner call, 2026-07-25: flat module names, with a package folder deferred to LATER. Rename-only, with NO compatibility shims — a clean cut.

**Why.** Keeping the pass to a rename (rather than also restructuring into a package) keeps the scope honest and the verification tractable; no shims means there is exactly one name for each thing after the cut, instead of two live spellings to maintain and re-explain.

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

### Rename ships in the same release as the rest of the work  ·  *2026-07-25*

The rename goes out in the same release rather than being split across two, on a dedicated branch, merged forward and tagged with the release.

**Why.** So the new commands are learned once rather than across two releases.

### The comparison panel uses a second <img> for the original  ·  *2026-07-25*

The filter panel's three columns are original | filtered preview | swatch rail, align-items:stretch with flex:1 frames so the pictures are matted and centred instead of stranded above a void. The original is a SECOND <img> element.

**Why.** "sharing one would filter both and leave nothing to compare."

### The install-folder tidy is a separate, later pass  ·  *2026-07-25*

Tidying the install root (a /moonglade folder for achievement and branding files that currently sit loose) is its own pass, separate from renaming the modules.

**Why.** Owner's motivation, 2026-07-25: **"a tidy install folder says a lot and implies good design etiquette across the suite."** It is a different job from renaming four modules, so keeping it separate is what lets "rename-only" stay honest.

### The upscale flyout can never outlive the picture it was opened for  ·  *2026-07-25*

The lightbox flyout sits above the overlay (the overlay deliberately stays open behind it) and is force-closed by both the lightbox close and step-to-next-image paths.

**Why.** An upscale panel still showing after the user has navigated to a different image would submit against the wrong source.

### There is deliberately no /api/upscale endpoint  ·  *2026-07-25*

Upscale submits through the existing price + generate routes as a plain image-to-image request (reference media id + strength).

**Why.** Upscale and the Generate-tab boosters are ordinary generation parameters, not a separate feature — adding a parallel endpoint would fork the spend path and duplicate pricing/guard logic.

### Upscale never guesses the model  ·  *2026-07-25*

The model is prefilled from the catalog row when known, and otherwise falls back to the shared model picker so the user chooses.

**Why.** A different model restyles the picture rather than just enlarging it, so a silent default would silently alter the owner's art.

### "Under the Hood" intended flow  ·  *2026-07-26*

Scoped flow: (1) a fresh install has the branding slot folders present but EMPTY, and nested; (2) the deepest folder holds a single README breadcrumb — something like "Maybe something goes in here" — which is the only hint; (3) the user drops any PNG/JPEG into a slot folder and the app adopts it into that slot; (4) that adoption fires the achievement; (5) the achievement unlocks a Control Panel branding tab showing every available slot, a file picker (from the gallery or from disk), and spec guidance per slot such as banner dimensions.

**Why.** The breadcrumb is the only hint by design — finding it is the point. The nested empty folder tree is the true blocker on this feature: today nothing creates those folders, so there is nothing to find.

### "Under the Hood": the gate IS the feature  ·  *2026-07-26*

The easter-egg gate on custom branding is not incidental — it is the point of the feature. Owner's framing, quoted verbatim: **"The point is to reward the nosy power user. A generic user just playing with this to grab their gallery and run gens isn't going to give my branding a 2nd thought... The point is to leave the folders available for those people that poke around and look for the nuts and bolts. This is one of the rarest unlocks in the bunch. You have to tinker and play to find the sauce."**

**Why.** Recorded emphatically because the opposite was proposed and had to be corrected. The product's own copy already committed to this design: the roast reads "Look who went spelunking in the walls... Custom branding: unlocked. Tell no one." The design was written down in the product's voice, just not anywhere a doc sweep would look.

### Branding scan exclusions deliberately still point at the OLD location  ·  *2026-07-26*

The exclusions that keep branding art out of gallery and backup scans were deliberately left pointing at the pre-move library location.

**Why.** An install predating the move still has files there, and a local import would otherwise catalogue someone's banner and mascots as gallery images. Excluding an absent path costs nothing, so there is no reason to repoint it.

### branding/ lives in the APP ROOT, not inside the code package  ·  *2026-07-26*

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

### Enhance Adept must be retooled or retired  ·  *2026-07-26*

"Enhance Adept" is dead. Its metric computes from a counter nothing increments any more (the Enhance surface was deleted), so it can never be earned. It is the only achievement in that state — all 36 metrics were checked. The cleanest fix keeps its shape ("five different X", epic tier, mastery bucket) and changes the X.

**Why.** An unearnable achievement is worse than no achievement: it permanently blocks completion. Keeping the shape preserves the tier and bucket balance of the roster so only the metric has to be re-reasoned.

### Free LoRA trainings ride the EXISTING free-card path  ·  *2026-07-26*

The training input's free-card field is the same kaisuuken mechanism already implemented for image generation, so the existing free-card path applies directly — no new mechanism needed.

**Why.** The 8 free trainings are kaisuuken cards. This is the headline finding of the capture: what looked like a separate entitlement system is the one we already handle.

### Gallery search / front-end real-estate spec  ·  *2026-07-26*

A real spec, not a note. The left of the gallery screen is largely unused and filter controls are buried under the far-right More link. Wanted: (a) move **search up with the main controls**, or another obvious place; (b) an **advanced-search affordance on the search field itself**, opening either the left panel or — preferred — a **small floating pop-up panel** carrying Search prompt, Media, Collection, Sort, per page; (c) **Filter and Reset must stay reachable on the same page** for convenience; (d) **thumb size moves into Deep Focus**. Owner explicitly wants **design inspiration / options** on this one — it is the single item on the triage board he asked for options on rather than a decision from.

**Why.** Wasted left-hand real estate plus buried filters. Recorded in full because the previous carry of this item was a one-line "blocked on owner input" note that lost every requirement; and because the options-vs-decision distinction is unique to this item.

### Incremental top-up beats a faster full rebuild  ·  *2026-07-26*

Ship an incremental sync entry point for the similarity index first; the parked thumbnail-embedding work is downgraded from a priority to a genuinely optional optimisation.

**Why.** Thumbnail embedding existed to make a full REBUILD faster, but the crash's real lesson is that a full rebuild is almost never the right operation — the only available button was the destructive one, and taking the obvious action would have destroyed 26,400 good rows and cost ~38 minutes instead of ~12. Incremental skipping already exists and is already tested; exposing it is thin.

### Keep the light backfill command, never surface it  ·  *2026-07-26*

Keep --backfill-meta, and never give it a Panel button or any other UI surface. It is SUPERSEDED, not obsolete: the full backfill fills the same three columns as a free side effect and full-meta is the default on a normal pull, so new rows arrive complete. Its one remaining unique capability is that the two commands take different routes to the data — the light one resolves via the media object, the full one via the task — so the light one alone can repair a row whose MEDIA still resolves but whose TASK is gone (a generation deleted from the PixAI account where the local image survives but the record describing it does not). Rare, and it recovers dimensions only, not prompt or seed.

**Why.** Asked and answered 2026-07-26 because nobody could remember why it existed. It is kept for that one narrow repair case; it is never surfaced because a button would imply pressing it achieves something the sync has not already done.

### Mirroring to the PixAI library is a credential switch, not a feature  ·  *2026-07-26*

Confirmed by a real submission on 2026-07-26: one generation submitted with the owner's browser session JWT instead of the API key appeared in the pixai.art generations list and stayed there through a refresh. The cause was never a missing parameter — it is the CREDENTIAL. A browser JWT files a generation into the account; a bare API key does not, no matter how the request is dressed. The fix is therefore a credential switch: "Mirror to PixAI" submits with the JWT, "Local only" submits with the API key. Both paths still download locally.

**Why.** This closes a question first raised 2026-07-05 and re-raised repeatedly since ("app gens pop up on the website then vanish unless favourited"). The alternative theory — a missing request parameter — was tested and disproved: API key plus browser-id header plus pixai.art origin was accepted, created, and CHARGED, and the generation still dropped off the feed. Keeping local download on both paths means the redundancy the owner asked for is real either way.

### Never hard-code a short-lived credential (the U3T lesson)  ·  *2026-07-26*

The old "constant token harvesting" pain was not the JWT — it was U3T stored as a static string in config.json when that value has a ONE-HOUR life. It was stale almost immediately, invisibly, with no signal. The structural fix is a session cookie jar: the short-lived cookies refresh themselves via Set-Cookie on every response. "They were never things to harvest, they were things to stop hard-coding." A read-only query also succeeded with no U3T sent at all, so it is not required for auth on that path.

**Why.** Measured, not assumed (2026-07-26): the JWT is ~27 days (up from ~12 days measured 2026-07-11 — one of several signs their site is changing under us), the u3t cookie ~1 hour and refreshed on every response, the browser-session id ~30 minutes and likewise refreshed. Storing an hourly credential in a config file guarantees silent failure inside the same sitting.

### Nightfallen becomes gated behind Night Keeper  ·  *2026-07-26*

Nightfallen is gated behind the **Night Keeper** achievement, and the **Moonwell Eclipse** icon gates *with* it — one bundle, two pieces, one achievement. Its current free status is not intentional.

**Why.** It is free today only because the reward plan had not landed yet. This resolves the open "should Nightfallen stay free" tension directly.

### No filesystem watcher for dropped branding files  ·  *2026-07-26*

Detecting a dropped branding file is done by checking on Panel/branding load. A real filesystem watcher is deliberately not needed.

**Why.** The check only has to be true by the time the user looks at the branding surface, so a load-time scan is sufficient and avoids a long-lived watcher for a once-per-install event.

### One free achievement slot earmarked for Dungeon Crawler Carl  ·  *2026-07-26*

Of the three free slots (57 of 60 used), one is earmarked for a Dungeon Crawler Carl reference. The native hook is DESCENT — something that fires on reaching the true bottom (the oldest image, or the literal end of 35,000). Carl art already exists in the chibi library. The other DCC-native option is an achievement whose ROAST is written as a sponsor announcement.

**Why.** DESCENT is the thematically native hook rather than a bolted-on reference, and the sponsor-announcement variant lets the voice do the work instead of the metric — which is the cheaper and more characterful of the two.

### Only Feats keep ornate per-tile frames  ·  *2026-07-26*

Frames are for Feats only. There will be no Epic-tier frame art, and the Legendary per-tile frames are being DROPPED as well. Practical consequence: the framed-tile logic in the notify layer must have its legendary branch taken OUT rather than gaining an epic branch, and the art-direction doc's frame guidance needs the same correction.

**Why.** Owner's reasoning: only a Feat is "truly opening a new tier", so only Feats should carry special framing. This closes the long-running epic-frame question by removing the premise rather than answering it.

### Password reset splits into self-service vs. owner-machine  ·  *2026-07-26*

Owner, 2026-07-26: "a user may reset THEIR OWN password from anywhere; resetting anyone else's is an owner-machine action only." Self-service reset inherits the self-only carve-out the existing user-removal route already uses; admin reset-for-another-user is LOCALHOST, like adding an account. This was the blocker on the item — it is now a build, not a question.

**Why.** It splits the trust question into two paths rather than forcing one trust call for both cases: changing your own credential needs no elevated trust, while changing someone else's is an administrative act that should require being at the machine.

### Persisted hashes are derived — and plausible-and-wrong is worse than absent  ·  *2026-07-26*

The hashes are not in their bundle at all (zero 64-hex strings across 868 chunks / 16 MB — Apollo computes them at runtime), but the documents ARE, as pre-parsed AST literals with complete field projections and typed variables. So we print the AST the way graphql-js does and hash that. Three hashes observed on real requests are baked in as an oracle; of four print variants tried, exactly one reproduces all three (inject the typename field before hashing, no trailing newline). If no variant passes, the tool writes NO hashes at all.

**Why.** Plausible-and-wrong is worse than absent on a surface that spends money. This is also the standing answer to "what happens when PixAI changes their frontend": re-run the harvest and the hashes re-pin themselves, which demotes the manual recapture procedure to a fallback rather than the first move.

### Promised rewards must be inventoried before new ones are assigned  ·  *2026-07-26*

The first deliverable in the reward work is the list of what is currently PROMISED — existing skin/banner reward values plus anything the UI already tells a user they will get — so those promises can be honoured before anything new is assigned.

**Why.** Owner's stated need: honour what users have already been told, then decide new assignments. Ordering matters more than volume here.

### R2V uploads deliberately left in place  ·  *2026-07-26*

Image-to-video and first/last-frame pass the catalog media id straight through with no re-upload. Reference-video was deliberately NOT changed and still uploads.

**Why.** The requirement that forced every input through an upload came from an error name specific to the reference-VIDEO field: it was real for R2V and only wrongly generalised to i2v, where it never applied. A read-only survey of the owner's own history found reference-video tasks split 3 catalog-id / 3 uploaded, so the evidence is mixed and the error name was specific. Banked follow-up: if R2V turns out not to need uploads either, the same content-scanner trap applies there too.

### Recommended replacement: five different base architectures  ·  *2026-07-26*

BANKED for the design pass: retool Enhance Adept as "generate on five different base architectures" (DiT.1 / DiT.2 / DiT.3 / SDXL / SD 1.5).

**Why.** The 2026-07-26 enum work is exactly what makes it measurable — the tokens are now known and the model id is already stored per image, so the metric is a single distinct-count. It also survives the rename thematically ("refinement in every register" becomes fluency in every dialect), and it rewards breadth of craft rather than clicking something five times.

### Stop hand-probing PixAI's API; harvest the whole surface  ·  *2026-07-26*

Hand-probing was abandoned in favour of mining the entire frontend surface at once (182 operations — 102 queries, 80 mutations/subscriptions — each with its full document, typed variables, and hash). Output lands in a git-ignored folder.

**Why.** "Every hand-probe uncovered another layer, so the probing stopped and the whole surface got mined instead." The fetch and extract steps never touch their API — static CDN files only.

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

### Watcher state must be logged, not only held in memory  ·  *2026-07-26*

Every watcher transition is written to the persistent log, and the silent-socket case logs at WARNING stating explicitly that anything completing during the silence was NOT mirrored.

**Why.** The watcher's state existed only in memory, which is why "was it even connected?" was unanswerable after a missed video. The point is that an unknowable gap must announce itself rather than look like a clean run.

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

### BlurHash grid placeholders — deferred, low ROI

BlurHash grid placeholders are deferred at low ROI — a small banked item, not an epic. Revisit only if published coverage grows.

**Why.** The blurhash data covers PUBLISHED rows only, stays empty until an artwork sync runs, and would need a JS decoder that does not exist. The cost/coverage ratio does not justify it today.

### Canonical achievement roster (57, with a 60 ceiling)

The canonical roster is docs/achievements_roster_57.json — 57 achievements, each carrying roast (default/spicy), roast_nsfw and a rung, in buckets of 29 ladder / 9 milestone / 8 mastery / 11 feat. The Great Library is a BANNER reward, not a badge. There is room for ~3 more against a 60 ceiling.

**Why.** Fixes the roster as data (one JSON file) rather than prose, and pre-answers "can we add more?" — yes, about three, then stop at 60. The Great Library being a banner keeps it out of badge-art scope.

### Casting-bar frame art — the art is the frame

WoW-style casting-bar frame art is banked as a candidate for a themed generation/render progress bar plus ladder-achievement and Panel job progress. The art is the FRAME; the dynamic fill composites INSIDE via 9-slice so ornate ends don't stretch. Prefer the cleaner rounded frames over the maximalist spiky-lightning ones for constant on-screen use.

**Why.** 9-slice is what keeps ornate end-caps from distorting as the bar fills. The rounded-over-spiky preference is a taste call for something that sits on screen constantly — the maximalist option was looked at and passed over.

### Clearing an override is visible, never silent

Typing in the Loom's own native Prompt textarea clears an active drawer override immediately — and does so visibly, via a brief self-clearing flash notice rather than silently.

**Why.** Editing the prompt from the other surface means the same thing as clearing the override, but the user must be told their override just went away rather than discovering it later.

### Config is written only after validation succeeds — never written first and rolled back

The wizard persists the key only after the validation call actually succeeds.

**Why.** Write-then-roll-back leaves a broken credential on disk if the rollback itself fails.

### Cost-to-finish pill deliberately does NOT share the batch's pre-confirm pricing

The standing free/paid/credits/unpriced cost pill runs off a warm per-shot price cache (600ms board-debounce plus click-to-force). It is deliberately NOT shared with batchGenerate's own one-shot, must-be-fresh pricing pass immediately before the irreversible confirm. Both use the same pure tally math underneath.

**Why.** "different staleness contracts" — a browsing estimate may be slightly stale; the number shown at the moment of spending may not be.

### Epic A — The Foundry (image → 3D print): gated, resin-first, never bundled

Four stages, gated on an explicit owner go. Stage 1 is a spike that is the go/no-go: one gallery image → Hunyuan3D-2 mini/turbo → GLB, **judged on a real Nelnamara render**; pivot to the Meshy API if 12 GB proves insufficient. Stage 2 is headless Blender → watertight STL (nothing Blender-related exists yet — install and script it as part of that stage). Stage 3 is a "Send to Foundry" button + async job + GLB preview + STL download. Stage 4 folds into Epic B. Hardware is a 12 GB RTX 4070 Super plus a resin Anycubic. **Resin-first**: skip texture baking, and orient hallucinated backs toward the plate. It is a **separate optional install behind its own extra, NEVER bundled**.

**Why.** Resin-first is what makes the pipeline cheap — resin printing doesn't need textures, and orienting the model's guessed-at back surface toward the build plate hides the part the generator invents. The never-bundled rule keeps a heavy 3D dependency stack out of everyone else's install. Judging the spike on a real Nelnamara render (not a generic test mesh) is the honest quality bar. It is the nearer of the two provider-seam epics because it's self-contained with no external account.

### Epic B — Provider Deck: build the seam only when the SECOND real provider lands

Gated on an explicit owner go, and bigger than Epic A — it benefits from the Foundry proving the provider-seam pattern a second time first. PixAI is already provider #1 behind the seam; the existing submit/status/collect/param-build calls *are* the interface. Shape: a git-ignored `providers.json` (keys + enabled providers), a provider picker in the drawer/Loom, one adapter file per provider. Provider #2 is Seedance 2.0 direct, whose modes map 1:1 onto the existing T2V/I2V/FLF/R2V/V2V grammar. **Discipline: add the seam only when the second real provider actually lands, so two concrete cases shape it.**

**Why.** Abstracting off one implementation produces a seam shaped like that implementation. The genuinely new problem to solve in the spike is that Seedance wants publicly-reachable URLs for input media and a localhost server cannot provide one — resolve it via their own upload endpoint, a temporary tunnel, or a short-lived presigned upload.

### Folio of Honors form factor = maximized overlay

The Folio of Honors is a maximized overlay, NOT a page or a route: grow the existing achievements modal to full-screen — instant open, gallery stays mounted behind, ESC out, animates from the trophy button. Owner screenshots tune the INTERIOR only; the form factor is settled.

**Why.** Keeping the gallery mounted behind makes open instant and preserves context; a page/route was considered and rejected. Interior screenshots must not be read as reopening the form-factor question.

### Front-end direction is Option A (and what "no framework" means)

Promote duplicated widgets to framework-neutral custom elements (gallery-owned, no build step, loaded the way picker-core.js is) that both the vanilla gallery and the React Loom mount. Explicit clarification: "No framework" means *no build step / framework-neutral shared widgets* — NOT "no framework": the Loom is React by design. Migration order is in the archived suite-architecture audit §6.

**Why.** The phrase "no framework" was being misread as a ban on React and would have driven a pointless rewrite of the Loom. The real constraint is no build step, so one widget can mount in both surfaces.

### Health disk walk excludes derived/quarantine folders

The Health page's disk walk excludes gallery/, _duplicates/, _deleted/ and branding/.

**Why.** So its number agrees with the Panel's catalog-row count — derived thumbnails, quarantined duplicates, soft-deleted files and branding art are not archive contents.

### Id search is exact-match and gated to 8+ digit terms

Gallery search matches a task/media id by EXACT equality, gated to all-digit terms of 8 or more characters; shorter numeric terms stay prompt-only. The box reads "Search prompt / task or media id".

**Why.** Short numeric strings are far more likely to be prompt content than an id, so they must not be hijacked into an id lookup.

### Loom comfortable-text option: desktop-only, one toggle, compact stays default

The wanted opt-in larger text/button scale must cover BOTH the V2 shell's side panels and the board's shot cards as one consistent option. It is desktop-only and explicitly NOT a responsive ask. The compact spec stays the default in both places. Implementation should be a compact/comfortable toggle driving a CSS custom-property scale, not two maintained layouts. Revisit after the visual pass, not before.

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

### Project export tiers, and image-only media resolution by design

Project export is a two-tier "Export ▾" menu: Shot list (.txt), Lightweight backup (.json — project plus local-only thumbs, referencing your own catalog by media id), and Full bundle (.zip — the same plus the actual referenced media files, server-built). Restore sniffs which file it was handed. Bundles keep media ids as-is end to end. Media resolution falls back to the catalog row's filename for videos because the shared media-id→file matcher is image-only BY DESIGN. Bundle import reconciles server-side with source='api', and a media_id already resolvable on the receiving machine is skipped.

**Why.** A real PixAI media_id is globally issued, so ids are safe to carry across machines unchanged — which is what makes re-importing the same bundle twice a no-op the second time. source='api' because it is real PixAI media that merely arrived by transfer rather than by download.

### Real SFX for the unlock toast — deferred, sources banked

Deferred to the Design Pass. The synth chime is the only sound that plays because no sfx folder exists on the served tree; the loader ships and fails soft by design. Sources already scouted so they don't need re-scouting: Kenney / Sonniss GDC / freesound / OpenGameArt (CC0), or Stable Audio Open via Pinokio. The owner has 1–2 WoW sounds of his own.

**Why.** Deliberate deferral, not an oversight — and the scouting work is the part that would otherwise be redone.

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

---

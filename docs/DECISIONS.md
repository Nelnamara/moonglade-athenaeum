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

- [Standing rules](#standing-rules) &mdash; 63
- [Settled constraints](#settled-constraints) &mdash; 45
- [Rejected — do not re-propose](#rejected-do-not-re-propose) &mdash; 26
- [Design sources](#design-sources) &mdash; 29
- [Decisions](#decisions) &mdash; 152

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

### Roast/flavor text: the gate was verified present; the owner still owns the last step  ·  *2026-07-22 · updated 2026-07-28*

The reported leak of uncensored/"spicy" roast lines was deliberately not patched blind. The verification has since been done, read-only: both gates (server blanks `roast_nsfw` unless Triggered is earned; the toggle renders only when the server says so) shipped 2026-07-12 in a single commit and were never absent — the surviving explanation for what was seen is the same-day Folio grid-overlap bug (two renderings stacked, fixed f09cd3b). The one real roast defect ran the opposite direction: the carousel never printed a roast at all, fixed 2026-07-26 (f5cc94b) with a pinned test. The owner still wants to diff the two roast fields himself before final closure.

**Why.** His explicit scope boundary stands. Related standing rule: never audit or sanitize the owner's own product-copy language — the roasts and swearing are deliberate voice.

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

### The achievement ladder is Design Pass scope — its gaps are NOT bugs  ·  *2026-07-28*

The whole achievement/reward system — the ladder, which achievements carry rewards, the mark/skin/banner pairings, unreachable or unearnable entries, missing reward values — is **owner design work reserved for the Design Pass.** It has been scoped and re-explained by the owner many times. Individual gaps in it are **not defects and must not be filed, surfaced, or prioritised as bugs.**

Concretely: "Completionist cannot be earned because two of its required metrics hang off the deleted Enhance surface" is a true observation and a **Design Pass item**, not a bug report. The same goes for blank reward fields, tier mappings that do not cover every track, and any "achievement X is unreachable" finding.

**Why.** A 2026-07-28 automated sweep of this file read those gaps as live defects and put an unearnable achievement at the TOP of a bugs list handed to the owner — who had already deferred it repeatedly. That is the failure this entry exists to stop: the deferral was recorded for *specific* items ([[Toast tier colors — owner called it resolved, but the direction wasn't restated]], [[9-slice tier frames wrap legendary/feat grid tiles too — the answer to "frame or defer"]]) but never for the ladder as a whole, so every fresh reader re-derived it as broken. **The Design Pass keeps receding because each pass widens the frontier instead of clearing the path to it — treat anything achievement-shaped as already-scoped and already-deferred unless the owner says otherwise.**

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

### V3.0 Lite instant video decline: CLOSED — cause found the same day this warning was written  ·  *2026-07-26 · reconciled 2026-07-28*

The cause was found by following this entry's own instruction (read the raw error and param shape from the log): we sent `generateAudio`/`audioLanguage` to v3.0.2 (V3.0 Lite), which does not take them, and PixAI surfaced that as "This image contains sensitive or NSFW content." Proven by a controlled pair on media id 747704233721405654 — their site submitted the same image WITHOUT the audio fields and it rendered; this app submitted WITH them and was refused. Fixed by `VIDEO_AUDIO_MODELS` (commit c8724b5), gated on both video builders. Two same-day contributors closed alongside: our own re-upload manufacturing content-filter refusals, and 15s offered on non-v4.0 models (now snapped to 10). Owner's test case: V3.0 Lite at 15s should submit at 10s, not decline.

**Why.** The owner's diagnostic instinct (nothing on the account = no task was ever created) was right and drove the fix. Reconciled so the do-not-close warning doesn't outlive the fix it asked for — the fix landed hours before the warning was carried into this file.

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

### The default download speed is unpaced — `--delay` reaches the parallel stage only when typed

`--delay` always paces the page listing, the per-task metadata fetch, and single-worker downloads. The multi-worker download stage — the default `--workers 4` path — is paced only when the flag is passed explicitly. Left alone it runs at full connection speed, exactly as it always has.

**Why.** The finding (`M07`) was that the wiki documented `--delay` as applying to downloads and on the default path it did not. Making it always-on at the shipped `0.4` capped the whole pool at one image per 0.4s regardless of worker count — it made `--workers` decorative, made the Panel's own workers selector decorative, and turned a 17,000-image first backup from roughly 35 minutes into nearly two hours. That is a silent 3–6x regression on the tool's single most common command, traded for a throttling problem that has never once been reported. The mismatch was mostly a documentation defect, so the wiki was corrected and the flag made to work when it is actually asked for.

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

### Start the dev server through the launcher, never `python moonglade_gallery.py` bare

A dev/sandbox server is started by running **`Serve Gallery.pyw`** (under `pythonw`), never by invoking `moonglade_gallery.py` directly. Machine-local flags go in the git-ignored `serve.txt` beside it — on the sandbox checkout that is `--out pixai_backup --port 5057`. The `--out` pin is **not optional here**: the launcher deliberately passes no `--out` so the server can resolve `config.json`'s `LIBRARY_DIR`, and on this machine that value points at the **D: install's library** — an unpinned launch from the C: checkout serves D:.

**Why.** Only the launcher sets `MOONGLADE_SUPERVISED=1` and runs the exit-code-42 relaunch loop, and `/api/server/restart` refuses with a 409 without it. A bare launch therefore silently removes the owner's Restart button from the Control Panel, which is not a cosmetic loss — his stated reason for killing a bare-started server was that he could not restart it. Nothing in the running process advertises that it is unsupervised, so the next session cannot tell by looking; the rule has to be written down.

### Moonglade converts COMPLETELY to React. Not a surface option, not a hybrid, not up for technical debate.  ·  *2026-07-31*

The owner asked about moving the app to React back when the Loom was first built. A session pushed back hard against it — wrongly. He raised it again 2026-07-31, still visibly frustrated, mid-way through the actual conversion effort: **"This is My app."** His own diagnosis of every failure so far: **"Porting a design back and forth is where this went totally to shit."**

The direction: vanilla JS and the `moonglade_gallery.py` Jinja-template monolith (~16.3k lines) are being retired **in full**. Flask becomes a JSON API backend, not a page renderer. Claude Design has been building the complete app UI in React (2026-07-29 → ongoing), working from the real `mg-*` component code + real `DESIGN_TOKENS_CSS` (pushed via the `design-kit` branch + DesignSync), the owner's own Figma work on the Folio, and direct access to this repo — not guessed, not screenshotted-and-approximated. The `gallery-top` branch is kept specifically because the conversion continues there, not as an archive.

**Do not:**
- Offer "port the design back to vanilla JS," "keep a scoped hybrid for now," or any variant that quietly reopens this — even when it sounds like the lower-risk engineering call. That exact back-and-forth is the named failure mode.
- Treat this as one option among several because a doc phrased it softly once. If a stack/architecture decision this owner has stated seems hedged or half-implemented in the code, that is something to flag and fix, not evidence it was ever negotiable.
- Assume "design happens in Claude Design" means no React/UI work happens in this repo. It's the opposite: Claude Design produces the UI, this repo is where it gets implemented, wired to real data, and shipped.

**Why.** Full memory record: [[owner-architecture-calls-are-final]] (Claude Code's own persistent memory, work machine). Real evidence on what "easy" actually means for this conversion — what's already solved vs. genuine remaining work — is banked in the Decisions entry below, *"React conversion: the feasibility map (2026-07-31)."*

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

**Recurred 2026-08-02** in the Runs reel's reuse-prefill (`GenerateDrawer.jsx`'s `prefillFromRun`), which fed a catalog row's `model_id` into `applyModelRow` the same wrong way — this doc entry existed the whole time and neither the build nor the adversarial verify pass consulted it before shipping. Silent failure this time (a toast, not a blocked submit), caught live during a real test generation. Fixed for real with a reverse lookup instead of a workaround: `moonglade_backup.resolve_model_base_id(session, version_id)` calls PixAI's `getGenerationModelByVersionId` (the same op `model_name_gql` already uses) and reads the `model.id` field it returns but nobody was extracting, exposed via `/api/model-version?version_id=X`. Any future surface that needs a base model id FROM a catalog row (not from a fresh market pick) should call that, not feed the row's `model_id` straight into a versions lookup a third time.

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

## The gallery top — the owner's own placement, 2026-07-27 · NOT locked

*The owner did the placement himself in a component editor, and it is the best current reference
for this surface — but he never locked it. The LOCKED status this section carried until 2026-07-28
was stamped during the parsing of his design-pass answers, not by him ("No where did I lock this —
that was unilaterally decided for me"). Locking is his explicit call; until he makes it, this is
direction to review with him, not a pixel source of truth a build verifies against.*

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

### Correction: 6 punch-list items were closed unilaterally, without owner sign-off — reopened  ·  *2026-08-04*

While working the design-fidelity punch list, I marked six items "resolved by investigation"
in this doc: Shutdown's "Power back on" button, the mobile Control Panel "Check" region's
5-vs-1 row count, Loom desktop's Frame Handoff spanning all 4 tabs, Image Details' "Direction
C" field-hiding, Contests' missing "+12 more" footer hint, and (reported to the owner as
resolved though the checkbox itself stayed open) the My Art mobile stat-card layout and
Health's folder-breakdown format. In every one of these, no code changed — I read the real
component, formed a judgment about whether the shipped behavior was correct or the design was,
and wrote "closed" in the tracker. The owner directly challenged this ("who made the
determination it was deliberate... who decided real code superseded a design without saying
anything... who's in charge here") and was right to. This repo's own standing rule is that the
design wins every visible question and the owner decides on deviations — implementers *list*
proposed deviations, they don't resolve them. All 6 are reopened above as `[?]` PROPOSED,
awaiting an actual owner decision, with my reasoning kept intact as a proposal, not a verdict.
One of the six ("Direction C") has a deeper problem worth naming on its own: the citation for
it lives only in a code comment, and the `DECISIONS.md` entry that would prove the owner
actually said those words was lost in the 2026-07-27 docs prune — so even calling it "a locked
prior decision" was asserting something I can't verify, not just deciding without asking.
Nothing here changes the items that DID ship real, code-verified, live-tested fixes (Contests
date/prize display, Contact Sheet print colors, Loom Mobile's Draft-chip glow, and the ~16
earlier items in this file with commit hashes) — those are unaffected and remain checkable via
`git log`/`git diff` on `design-final-pass`.

### Loom Mobile: Draft chip's active-state glow was missing  ·  *2026-08-04*

Fix from the design-fidelity punch list above. `Loom Mobile.dc.html`'s `draftChipStyle`
(line 670) adds `box-shadow: 0 0 10px rgba(212,175,55,.35)` when draft mode is on, alongside
the gold color/border/background — the real `.lm-chip.on` rule
(`loom/master-storyboard.jsx`) had the color/border/background but not the glow. One-line CSS
addition. Verified live: switched Loom to mobile view, toggled Draft on, read the real
element's computed `boxShadow` — matches the design's value exactly. Loom's own `npm test`
suite and the full `python -m pytest -q` suite both green.

### Contact Sheet desktop: print output used dark-theme text colors on a white page  ·  *2026-08-04*

Fix from the design-fidelity punch list above. `Contact Sheet.dc.html` is itself a light/print
mockup with a dedicated 4-color palette (`#1b1733` main ink, `#746c8a` secondary label,
`#8a8398` tertiary caption, `#2a8f86` accent) baked directly into its inline styles — but
`contact-sheet-overlay.css`'s `@media print` block only reset layout (hide app chrome, flatten
the slab) and never touched color. Every text class still resolved the app's dark-theme CSS
custom properties (`var(--text)`, `var(--subtext)`, `var(--blue)`) at print time, which read as
pale/washed-out on white paper — real but hard to catch without actually opening a print
preview, since on-screen (dark background) those same tokens look correct. Added explicit
`!important` hex overrides per class inside the print block, matching the design's literal
values class-for-class. Verified by inspecting the live CSSOM of the built stylesheet's
`@media print` rule directly (not the source file) — confirmed `rgb(27,23,51)` (`#1b1733`) and
`rgb(116,108,138)` (`#746c8a`) present exactly where expected. Pure CSS change, no data/logic
path touched — no pytest coverage applies; full `python -m pytest -q` suite still run and green.

### Contests: combined date+days-left string and ♦ diamond consistency, both platforms  ·  *2026-08-04*

Fix from the design-fidelity punch list above. `Frontend Gallery.dc.html:2434` maps every
contest card's date field with one formula, `c.dates + ' · ' + c.left` — a real date range
AND a computed days-left, combined, on every card, official or community. The shipped code
had three separate drifts from that single line: the official card on both platforms showed
range-only (no days-left at all); community cards disagreed *with each other* across
platforms (desktop range-only, mobile days-left-only, neither matching the other or the
design); and the ♦ diamond prefix on the CR-amount pill was present only on the one featured
card, missing from every community card on both platforms. `useContests.js` already had both
`dateRange()` and `daysLeft()` as separate, tested helpers (`daysLeft` built for mobile only,
never called from the desktop overlay) — no new data logic needed, just a shared
`dateWithLeft(row)` wrapper added identically to `ContestsOverlay.jsx` and
`ContestsMobile.jsx`, and the missing `♦ ` prefix added to both platforms' community/
restOfficial CR pills. Verified live against the real `/api/contests` feed (25 real cards):
`.mgct-dates` renders e.g. `"2026-07-29 – 2026-08-18 · 14 days left"`, `.mgct-prize` renders
`"♦ 54,500,000 CR"` on every card checked, official and community, both platforms. Full
full `python -m pytest -q` suite passes.

### Design-fidelity audit: every shipped surface checked against its real `.dc.html`, real gaps found — punch list  ·  *2026-08-04*

The owner directly disputed that shipped work matches its locked design ("you have strayed from
the design on nearly every surface... it was all built over the last day in THIS session").
Investigation started from a live, reproducible symptom (the desktop Loom's reel/timeline
rendering as a plain 4-color bar instead of the design's per-shot-tinted, textured, labeled
film-strip) and expanded into a full audit: every `.dc.html` in `design_handoff/` read in full
and diffed section-by-section against its real component. Two confirmed root causes recur
across almost every finding below: (1) a component's own header comment sometimes asserts no
design source exists when one does (`DuplicateReviewOverlay.jsx`'s "No locked DC mockup exists"
claim against a real, complete 244-line `Duplicate Review.dc.html`), and (2) desktop and mobile
builds of the *same* feature frequently disagree — several regions built correctly for mobile
were never ported back to desktop (Folio's tier carousel, Image Details' LINEAGE/SIMILAR
sections, the Loom's Filter-compare and Fixer/Enhance tabs, Control Panel's Live Mirror).
Not every surface is guilty — Lightbox (both), Login (both), Setup Wizard (both), and large
parts of Health/Gallery-shell/Loom Mobile structure are genuinely faithful, several exceeding
the static mock (real thumbnails, live-wired click targets the mock left decorative, real video
scrub/trim replacing a fake `setInterval`). This entry is the fix backlog; items get struck
through (not deleted) as they land, each with its own dated Decisions entry the way every other
increment in this file works.

**Duplicate Review (desktop)** — `gallery/src/components/DuplicateReviewOverlay.jsx` vs
`Duplicate Review.dc.html`. Worst case in the audit: a real design exists and was never opened.
**SHIPPED 2026-08-04, see dated entry below.**
- [x] Header: "← Library" crumb, icon+label, filter-by-title search input (design ~28-38)
- [x] Hero block: eyebrow + serif H1 + 3 stat cards (groups/images/reclaimable) (~43-63)
- [x] Caption row: "sorted by highest similarity first..." (~65-71)
- [x] Color-coded similarity badge by %, not flat text (~84, ~192/205) — real `closeness_pct`
      exists on the near_duplicate tier already, use it
- [x] "★ suggested keep" gold ribbon on the keeper tile (~100/236)
- [x] Resolve button: "keep {N}, remove {M}" (currently remove-count only) (~110)
- [x] "Skip for now" button next to Resolve (~111)
- [x] Correct/remove the false "no mockup exists" claim in the file's own header comment

**Control Panel** — `ControlPanelOverlay.jsx`/`ControlMobile.jsx`/`useControlPanel.js` vs
`Control Panel.dc.html`.
- [x] Credit balance shown nowhere on desktop (header shows build-stamp instead; vitals list is
      3 items not 4) — mobile has this correctly, port the pattern. **SHIPPED 2026-08-04.**
- [x] Live Mirror section entirely unrendered on desktop despite existing unused CSS
      (`.mgcp-mirror`) and a real, working mobile implementation to port from.
      **SHIPPED 2026-08-04, same pass as credits — see dated entry below.**
- [ ] Branding tab ~80% unbuilt: only Icons&marks + Animation work; Banner-main/Banner-login/
      Mascots/Rewards slots, per-slot crop-guide preview, upload chips, rotating-source note,
      and the "Sealed" explainer are all absent (disclosed as one summary sentence, but the
      scope is much larger than that sentence implies) — needs new backend, largest remaining
      item, may need its own scoping pass rather than a quick port
- [ ] No job run-history/ledger anywhere (desktop: zero; mobile: a toggle with only a disclosure
      sentence behind it) — Sync's "last run/rc/auto-schedule" line and Check rows' last-run
      timestamps both dropped too
- [x] Dedup's 5-stage sequence isn't actually gated (design: each stage locked until the
      previous one runs; real: every stage always clickable). **SHIPPED 2026-08-04.**
- [x] Organize flow drops the "142 would move" result-readout chip between Preview and Apply.
      **SHIPPED 2026-08-04.**
- [x] Running-job view drops the `lockedMinis` "what's blocked while this runs" chip row.
      **SHIPPED 2026-08-04.**
- [x] "Catalog & files" tile missing the library-folder picker (desktop). **SHIPPED
      2026-08-04** as a real text-path input, not the design's native folder picker (browsers
      never expose an absolute host path through `<input type="file" webkitdirectory>`, for
      security reasons — the design's own approach couldn't have worked as literally specified
      regardless of who built it). Mobile still doesn't have this tile's shape at all —
      separate, smaller, not done in this pass.
- [x] Branding tile's mark glyphs don't set the mark in place — click just switches tabs.
      **SHIPPED 2026-08-04.**
- [~] Skin cards drop the concrete unlock-requirement text (e.g. "Unlock: Hoardsmith (10,000
      images)") — shows "🔒 locked" with no explanation. **CHECKED 2026-08-04, not fixable
      honestly as scoped**: the design's unlock strings name specific achievements
      (`Control Panel.dc.html:453-457`, e.g. "Hoardsmith (10,000 images)") that don't exist in
      this app's real `ACHIEVEMENTS` list — grepped the whole file for any `"skin":` field on a
      real achievement entry, zero matches. All 3 non-free skins (`moonlit`/`ember`/`verdant`)
      are permanently locked with no real unlock path wired up at all right now. Adding the
      design's specific achievement names would fabricate data this app doesn't have. Real fix
      would be either wiring 3 real achievements to grant these skins (a scoping decision, not
      a port) or showing an honest "not yet unlockable" state instead of the design's copy —
      needs a decision, not a code fix.
- [x]/[?] Power modal, split in two: restart's progress bar **SHIPPED 2026-08-04** (an
      indeterminate bar, the same real pattern the job console already uses — real ping-polling
      has no stage index to compute an honest percentage from, unlike the design's fake
      RESTART_STAGES). Shutdown's "Power back on" button — **PROPOSED closed 2026-08-04, owner
      has NOT confirmed.** My reasoning: `/api/server/stop` calls `_schedule_server_exit(0)` —
      per `Serve Gallery.pyw`'s own supervisor contract, exit code 0 ends the whole supervisor
      loop, not just the child, so after a real Stop there is no process left to answer a
      restart request. That's a real constraint I verified in the code, but "this can't be
      fixed as the design shows it" is a call I made unilaterally, not one the owner signed
      off on. Left as a proposal, not a closed item, until he says otherwise.
- [x] Sidebar footer shows a filesystem path or nothing instead of a version/date string.
      **SHIPPED 2026-08-04.**
- [?] Mobile's "Check" region invents 5 separate rows where its own mobile-specific design
      calls for one consolidated "run all" row — **PROPOSED closed 2026-08-04, owner has NOT
      confirmed.** My reasoning: `Moonglade Mobile.dc.html:233-236` shows one static row
      naming three checks ("Corrupt files · Orphan thumbs · DB integrity") behind a single
      `run all ▸`. The real `ControlMobile.jsx` (~line 293) instead shows 5 real,
      independently-runnable read-only diagnostics (Catalog stats/Inventory count/Verify
      `_duplicates/`/Sync artwork metadata/Sync i2v videos) — none of which map 1:1 onto the
      design's named trio, so "consolidating" would mean either fabricating a check that
      doesn't exist, or merging 5 unrelated real diagnostics behind one button. That's my own
      judgment that the real version is better, made without asking — not something the owner
      has weighed in on. No code was touched for this item. Left as a proposal.

**Desktop Loom (`LoomV2` in `loom/master-storyboard.jsx`)** vs `The Loom.dc.html`.
- [x] Reel/timeline lost its visual identity — the owner's original complaint, confirmed
      exactly and now **SHIPPED 2026-08-04**: design specifies a 6-color rotating per-shot
      tint + repeating-stripe texture + visible code/duration text on each segment + a
      separate thin status bar under the shot's own color; shipped was 4 flat status colors,
      no text, no texture. (The resize handle and live scrub/trim preview above it genuinely
      exceed the design — kept, untouched.)
- [x] Hero banner region entirely missing — no graphic strip, no hide/show toggle, no state.
      **SHIPPED 2026-08-04.**
- [ ] Edit tab has no Fixer or Enhance sub-tabs at all (desktop-only gap). **Investigated
      2026-08-04, deferred as its own larger task, not skipped**: `LoomMobile`'s Fixer/Enhance
      (canvas box-drawing, debounced `/api/price` checks, `genFix` submit, the Filter-compare
      modal) are deeply embedded in that component's own local closures/refs/state, not a
      separable module — porting to `LoomV2` is a real, standalone build on the scale of the
      original Loom Mobile Fixer increment (a dedicated ~35-minute background build), not a
      quick copy. Given the real financial stakes (a Fix always spends, never card-covered),
      rushing this inline risked a real bug in a money-spending path. Needs its own dedicated
      pass.
- [ ] Filter-compare ("Art filters") modal doesn't exist on desktop, same story — mobile's
      real, `MgArtFilters`-backed implementation is the thing to port. Same deferral as above
      (Enhance's entry point into this modal is part of the same Edit-tab sub-strip).
- [?] Frame Handoff renders on all 4 Generate tabs instead of Reference-only per spec —
      **PROPOSED closed 2026-08-04, owner has NOT confirmed.** Traced `active.c.openFrame`/
      `closeFrame` usage across all 4 tab bodies: the Video tab's own body
      (`tab === "Video"`, ~line 1857) has NO frame-setting UI of its own — its "Continuity"
      chips and First/Last-frame weave modes depend entirely on the shared `.lv-framehandoff`
      block below it to set those frames; the Edit tab (~line 2189) literally reads
      `active.c.openFrame.mediaId` as its edit source with no separate picker either.
      `The Loom.dc.html`'s simplified mockup only ever modeled Reference-tab frame-setting
      (`onRefTab` gate, line 399). My read is that restricting the real block to
      Reference-only, as the design literally shows, would break two working features the
      mockup didn't account for — but that's my call, made without asking, not the owner's.
      No code was touched. Left as a proposal.

**Loom Mobile (`LoomMobile`, same file)** vs `Loom Mobile.dc.html`.
- [ ] Generate → Video tab missing 5 elements outright: weave-mode chips (First Frame/First&
      Last/Multi-Reference), negative prompt field, Model+Duration row, capability badges
      (15s/multi-ref/audio/end-frame), Channel/SFW selector — desktop's Video tab already has
      the Model/Duration/Channel cluster via `<mg-generate-drawer>`, reference it
- [ ] Generate → Reference tab missing the Opening/Closing frame pair (reuse the existing
      `FrameSlot` component, already used in Shot Detail)
- [ ] 4 of 6 designed animations don't exist: `lmMetal` (animated shimmer on every primary
      button — currently flat color), `lmSheetDown`/`lmFadeIn`/`lmFadeOut` (every sheet close
      is an instant unmount, not the designed 280ms slide+fade)
- [x] Draft-chip's active glow (`box-shadow`) dropped — **SHIPPED 2026-08-04**,
      `.lm-chip.on` in `loom/master-storyboard.jsx` now carries the design's exact
      `box-shadow: 0 0 10px rgba(212,175,55,.35)` (`Loom Mobile.dc.html:670`'s `draftChipStyle`).
      Verified live via computed style on the real toggled chip: `rgba(212, 175, 55, 0.35) 0px
      0px 10px 0px`.
- [ ] Frame/gallery picker isn't its own mobile screen — silently reuses the desktop
      `<mg-gallery-picker>` component instead of the design's 3-column mobile sheet

**Folio of Honors (desktop)** — `FolioOverlay.jsx` vs `Folio of Honors.dc.html`. Mobile
(`FolioMobile.jsx`) already builds both of these correctly for the same feature — port.
- [ ] "All" tab's featured tier carousel (plinth/prev-next/pips) entirely missing on desktop
- [ ] "Every rung, every ladder" cross-ladder section entirely missing on desktop

**Image Details (desktop)** — `DetailsView.jsx` vs `Image Details.dc.html`. Mobile
(`ImageDetailsMobile.jsx`) already has all four of these correctly — port the pattern.
- [ ] LINEAGE section missing — still open. No real backend lineage data exists (confirmed);
      not fabricating it. Same real gap mobile disclosed and skipped.
- [x] SIMILAR section missing. **SHIPPED 2026-08-04** — reused the exact real `SimilarModal.jsx`
      already proven by `Lightbox.jsx`'s own "✧ Similar" button, not a rebuilt strip.
- [?] 7 of 11 metadata fields hidden behind a "Full record ▾" toggle. **PROPOSED closed
      2026-08-04, owner has NOT confirmed — and this one has a real provenance problem.**
      `DetailsView.jsx`'s own header comment cites a locked prior design decision
      ("Direction C") explicitly choosing "a quiet curated fact list with a Full record
      disclosure for the rest" over a raw field grid. But Direction C's own `docs/DECISIONS.md`
      entry was lost in the 2026-07-27 docs prune — I have no way to confirm from that comment
      alone whether "Direction C" was ever something the owner actually said, or whether a
      prior session invented the label. I closed this on the strength of an unverified code
      comment, which is exactly the kind of claim this repo's own standing rule says needs a
      provenance review on dispute, not a unilateral close. Left as a proposal pending that
      review. No code was touched.
- [x] Zero per-row copy buttons in the ledger. **SHIPPED 2026-08-04** as footer buttons (Copy
      Seed/Task ID/Filename), not per-row icons — matches Direction C's own "actions demoted
      to the footer" idiom instead of reintroducing what that redesign moved away from.
- [x] Header missing the ⛶ Lightbox link and "N of M" index label. **SHIPPED 2026-08-04.**
- [ ] Upscale flyout (shared by Details + Lightbox, `static/mg-upscale-panel.js`) is a
      top-right-anchored panel with a native `<select>` instead of the design's centered modal
      with a custom animated dropdown

**Desktop Gallery shell** — `NavSpine.jsx`/`shell.css`/`Grid.jsx` vs `Frontend Gallery.dc.html`.
**All three SHIPPED 2026-08-04**, see dated entry below.
- [x] Real, live-reproduced CSS bug: `.mgx-sep`'s right cluster (`flex:none`, no wrap/scroll
      fallback) can literally overlap the stacked nav pills at real desktop window widths
      (~500-580px, confirmed via `getBoundingClientRect` overlap test) — not a phone-only issue,
      `useIsMobile()`'s 430px breakpoint doesn't cover this band
- [x] "Publish"/"Train" nav items are dimmed stubs wired to nothing — clicking produces zero
      feedback; needs at least a "coming soon" acknowledgment
- [x] Bottom-of-grid "Page X of Y · N per page · N items" caption missing, undisclosed (the
      "Load N more" removal next to it IS a disclosed, deliberate owner decision — leave that)

**My Art** — `MyArtOverlay.jsx`/`MyArtMobile.jsx` vs `Frontend Gallery.dc.html` /
`Moonglade Mobile.dc.html`.
- [x] Mobile post rows reuse desktop's bordered/rounded card component squeezed into one
      column, instead of the mobile design's flat dashed-divider list row. **SHIPPED
      2026-08-04** — new `.gmob-artrow` classes, not `.mgma-*`, so this can't drift back.
- [x] Desktop rank-tier coloring (gold #1, mauve top-3) entirely missing. **SHIPPED
      2026-08-04**, size restored to 19px/26px too.
- [x] Desktop stat order wrong (VIEWS moved from 2nd to last) and its accent-color highlight
      is missing; value type shrunk 24px→21px. **SHIPPED 2026-08-04**, fixed in the shared
      `useMyArt.js` hook.
- [x] Desktop per-post metric line uses spelled-out "N views · N likes" instead of the design's
      icon format "👁 N · ♥ N" (mobile's own design already specifies spelled-out — left
      mobile). **SHIPPED 2026-08-04, desktop only.**
- [ ] Mobile stat cards are inverted (value-above-label vs. spec's label-above-value) and use
      the wrong type family — borrowed wholesale from Control Panel's mobile stat card (still
      open — a disclosed, deliberate cross-screen-consistency choice, lower priority)

**Health** — `HealthOverlay.jsx`/`HealthMobile.jsx` vs `Frontend Gallery.dc.html`. Backend/data
logic and most regions are genuinely faithful; these are the real misses:
- [x] Stat-tile order and gold-highlight target both wrong (Duplicates/Reclaimable moved from
      positions 9-10 to last; gold marks "Published"/"Total likes" instead of "Uncataloged");
      3 labels silently reworded. **SHIPPED 2026-08-04**, verified live against the exact
      design order and gold target.
- [x] Section heading "Top tags" is missing "& contests" from the design's own heading text.
      **SHIPPED 2026-08-04**, both platforms.
- [x] Mobile missing 2 whole sections desktop has: Prompt word cloud, Folder breakdown.
      **SHIPPED 2026-08-04** — reverses a previous implementer's own scope-trim judgment
      call (not an owner-approved decision), reusing the exact same real hook data desktop
      already shows.
- [ ] Folder breakdown format changed from a fixed "N images · M other" to a generic N-bucket
      loop (desktop, and now also mobile after porting the same real implementation) — left
      as-is; the generic loop is arguably more correct for a library with other than 2 real
      buckets, and rigidly forcing 2 fields risks silently dropping real bucket data.

**Contests** — `ContestsOverlay.jsx`/`ContestsMobile.jsx` vs `Frontend Gallery.dc.html`.
- [x] "Days left" text dropped from the official contest card, both platforms — **SHIPPED
      2026-08-04**, folded into the combined date-string fix below
- [x] Combined "date range · days left" string never reproduced for community cards — desktop
      always shows range-only, mobile shows range XOR days-left (platforms disagree with
      each other, not just with the design) — **SHIPPED 2026-08-04**, verified live: every
      card on both platforms now renders `Frontend Gallery.dc.html:2434`'s own
      `c.dates + ' · ' + c.left` formula via a shared `dateWithLeft()` helper
- [x] ♦ diamond icon missing from every community-card CR pill — only the one featured card
      gets it; design puts it on all of them — **SHIPPED 2026-08-04**
- [?] "+12 more community contests below the fold — scroll" footer hint missing entirely —
      **PROPOSED closed 2026-08-04, owner has NOT confirmed.** My reasoning: the design's "+12"
      is static demo flavor text implying a paginated/preview grid; the real
      `ContestsOverlay.jsx`/`ContestsMobile.jsx` already render every `community` row in one
      unpaginated `.map()` (confirmed reading both files, no `.slice()`/limit anywhere), so
      there's no real "N more below the fold" number to show without scroll-position tracking.
      That's my own judgment call that skipping it beats fabricating a number — not the
      owner's. No code was touched. Left as a proposal; a scroll-measured version is buildable
      if he wants it instead.

**Contact Sheet (desktop)** — `ContactSheetOverlay.jsx` vs `Contact Sheet.dc.html`.
- [x] Print output likely illegible: the design has a dedicated light/print palette
      (`#1b1733`/`#746c8a`/`#8a8398`/`#2a8f86` on white); the `@media print` block never reset
      the app's dark-theme CSS tokens (`var(--text)` etc.), so printing produced pale text on
      white paper — **SHIPPED 2026-08-04**, `contact-sheet-overlay.css`'s `@media print` block
      now overrides every text class (`.mgcs-eyebrow`/`.mgcs-h1`/`.mgcs-cap-title` →`#1b1733`,
      `.mgcs-label`/`.mgcs-sub` →`#746c8a`, `.mgcs-meta`/`.mgcs-cap-sub`/`.mgcs-empty` →`#8a8398`,
      `.mgcs-no` →`#2a8f86`) with the design's literal hex values. Verified the built
      stylesheet's `@media print` rule holds the exact `rgb()` equivalents of all four hex
      colors (CSSOM inspection of the live loaded sheet, not a source-file read).

**Why the backlog lives here, not a new file.** Standing rule: no audit ever creates a new
tracking doc, findings land in the one tracker. This entry stays the single source for the
whole punch list; strike items as they ship, each with its own dated entry below (or above,
chronologically) documenting what actually changed and how it was verified — the same pattern
every other increment in this file already follows.

### Punch-list item 1 shipped: Duplicate Review desktop now built against its real design  ·  *2026-08-04*

First item off the design-fidelity punch list above, done personally (not delegated to a
background agent — the owner explicitly redirected from parallel agent dispatch to sequential,
narrated, self-executed fixes mid-session: "you will port these designs page by page... YOU
WILL execute the design file as given to you"). Read `Duplicate Review.dc.html` in full,
rebuilt `DuplicateReviewOverlay.jsx`/`duplicate-review-overlay.css` against it: the real
header (← Library / divider / ⧉ label / filter-by-filename search — filename instead of the
design's "title," since no title field exists on a duplicate group's member records, disclosed
in code), the hero block (eyebrow/serif H1/3 stat cards), the "sorted by..." caption, a
color-coded similarity badge (red/gold/purple/blue, keyed off the real `closeness_pct` for
near_duplicate and a defensible fixed tier for the exact-match tiers that have no percentage
concept), a "★ suggested keep" ribbon tracking the algorithm's own `bestKeeperPath` (distinct
from whatever the owner has currently toggled), the corrected Resolve label ("keep 1, remove
N"), and a session-local "Skip for now" (hides a card, zero network calls, re-shows on reopen
— not a mutation). Also corrected the file's own header comment, which previously claimed no
locked design existed for this overlay; it does, and it's now the thing this file matches.

Live-verified against the real library (218 real same-seed duplicate groups, 751.7 MB
reclaimable — not injected data): header/hero/caption/badge/ribbon all confirmed rendering via
DOM inspection, Resolve/Skip/search filter all exercised (Skip hides a card with zero fetch
calls; search filters to 0 with a real "no match" message). No real resolve/quarantine was
fired during verification. `npm run build` clean, full pytest 1539/1539.

### Punch-list items 2-3 shipped: Control Panel desktop now shows real credits and a real Live Mirror  ·  *2026-08-04*

Second and third items off the design-fidelity punch list, both in `ControlPanelOverlay.jsx`
since they're adjacent regions in the same sidebar. Root cause of both: the component was
simply never given the data it needed. `App.jsx` already fetches `account` (credits/cards) and
passes it to `SeparatorBar`/`GenerateDrawer` — `ControlPanelOverlay` was never added to that
list, so its header fell back to `boot.build_stamp` (a version string occupying the design's
credits slot) and its "At a glance" vitals stayed a 3-item list. Fixed by threading `account`
through (`App.jsx`'s `<ControlPanelOverlay>` mount now passes it) and building the header/vitals
markup the design (`Control Panel.dc.html:42`, `:51-57`) actually specifies.

Live Mirror was a real, working feature that existed only on mobile — `ControlMobile.jsx` already
polls `/api/watch/status` (a real, already-shipped route) once per mount and renders a
connected/mirrored-count/last-event line; desktop's CSS for this (`.mgcp-mirror`/
`.mgcp-mirrordot`) was already written and simply never given matching JSX. Ported the same
fetch-on-mount pattern (kept local to the component, not folded into `useControlPanel.js`,
matching `ControlMobile.jsx`'s own disclosed reasoning for keeping it separate — no polling
interval needed, the overlay's own mount/unmount is the natural refresh point) and built the
design's own bold-lead/plain-rest sentence structure (`mirrorLead`/`mirrorRest`,
`Control Panel.dc.html:64`) from the real fields, as its own section between "At a glance" and
"Server" (desktop's design keeps these separate, unlike mobile's merged card).

Live-verified against the real account/watch state (not injected): header showed the real
"3,593,991 credits · 24 free cards", vitals grew to 4 items, Live Mirror rendered "Listening.
210 mirrored this session" as its own section between the right headings. The sidebar's
version/date-stamp gap (design line ~77 — currently shows a filesystem path or nothing) is a
separate, lower-priority punch-list item and was deliberately left open, not silently dropped.
1539/1539 pytest.

### Punch-list item 4 shipped: Dedup's 5-stage sequence is now really gated  ·  *2026-08-04*

Design (`Control Panel.dc.html:637-641`) locks each dedup stage (Audit → Preview →
Quarantine 🔒 → Verify → Delete 🔒) until the previous one has actually run; the shipped app let
every stage fire in any order regardless. The design's own gating state (`dedupDone`) is itself
just in-memory, never persisted (confirmed at design line 508) — so this needed no new backend
or schema, only real session-local sequencing in `useControlPanel.js` (shared by both
desktop and mobile, so both platforms got the fix in one pass, not two).

Implementation note: `tick()` (the poll loop that resolves a running job) previously had no
reliable way to know which action key had just finished — `running` state closes over a stale
value inside the specific `tick` closure `setInterval` was given, so a `runningKeyRef` ref was
added instead (set synchronously in `runAction`, read in `tick`) to sidestep that trap. Gating
only advances on a clean `"done"` status, never `done_with_errors`/`cancelled`, so a partial
run can't unlock a destructive next stage on a false pretense. `runAction` also gained an
explicit early-return guard for an out-of-order dedup key (same "don't trust the disabled
attribute alone" rule this app applies everywhere a real gate matters).

Live-verified against the real library: at rest, only Audit was enabled (Preview/Quarantine/
Verify/Delete all disabled with a real HTML `disabled` attribute, confirmed via DOM inspection,
not just visual dimming). Ran the real (non-destructive) Audit action against the real ~2,337
image library; on completion Preview unlocked while the two destructive stages stayed locked —
exactly the design's intended progression. Did not run the destructive stages during
verification. 1539/1539 pytest.

### Punch-list item 5 shipped: Organize's "N would move" result readout is now real  ·  *2026-08-04*

Design (`Control Panel.dc.html:117`) puts a `{{ organizeRes }}` chip between the Organize
flow's Preview and Apply buttons — real dry-run feedback before committing to the destructive
step. Nothing rendered there before. The number comes from `cmd_organize()`'s own real stdout
line (`moonglade_backup.py`: `"Organize plan: N file(s) -> YYYY-MM/..."`), parsed in
`useControlPanel.js`'s `tick()` from the job's full, untrimmed line list — `jobResult.lines`
alone can't supply this, since it's trimmed to the tail 6 lines for the log view and the plan
line sits near the top of the output, ahead of the per-file preview rows.

Shared through the hook, so both desktop and mobile got it in one pass. Live-verified against
the real library: ran the real (non-destructive) Organize preview and confirmed the chip
showed "2308 would move" — the actual real count for the actual real library, not a fixture.
1539/1539 pytest.

### Punch-list item 6 shipped: the running-job view now shows what's really blocked  ·  *2026-08-04*

Design (`Control Panel.dc.html:205-210`) dims a row of other-action chips while a job runs, so
it's visible at a glance what's blocked, not just implied by disabled buttons scattered around
the console. The design's own `lockedMinis` is a hardcoded 4-item demo array; the real version
here is built from `summary.actions` (the same list `actionSpec()` already reads) minus
whichever action is currently running — first 3 real labels, then a real
"+N more · one job at a time" count, not a fabricated one.

Live-verified against the real library: triggered the real "Sync i2v videos" action, confirmed
the row showed the real other-action labels ("Sync now — pull new + fill metadata", "Catalog
stats", "Duplicate audit (fast, read-only)") plus "+17 more · one job at a time" — the actual
count of the actual other actions in this session's `summary.actions`. Stopped the job
immediately after confirming (no need to let a full i2v re-walk finish for this check).
1539/1539 pytest.

### Punch-list item 7 shipped (partial, honestly) + item on skin unlock text and Power-back-on checked and closed as not fixable  ·  *2026-08-04*

Two punch-list items resolved by investigation rather than a port, plus one real fix:

**Restart's progress bar** (`Control Panel.dc.html:687`, `powerBarStyle`) — the design computes
a real 0-100% width off `RESTART_STAGES`' fake stage index; the app already, correctly,
replaced those fake stages with real ping-polling (disclosed in this file's own header
comment) that has no stage index to compute an honest percentage from. Added an indeterminate
bar instead — same `.mgcp-runbar i.indeterminate` pattern the job console already uses — real
progress feedback without claiming a fake number. Build-verified (not live-restart-verified:
triggering a real restart would have taken down this session's own dev server mid-verification
of the remaining punch-list items, so this one narrow piece was checked by code review + clean
build rather than live exercise — disclosed, not silently skipped).

**Shutdown's "Power back on" button** — checked and closed, not built. `/api/server/stop` calls
`_schedule_server_exit(0)`; per `Serve Gallery.pyw`'s own supervisor contract, an exit code of 0
ends the whole supervisor loop, not just the Flask child. After a real Stop nothing is left
running to answer any request — the existing shipped copy ("goes offline until you relaunch
it") is the honest, correct behavior, not a gap to fill with a button that could never work.

**Skin cards' unlock-requirement text** — checked and closed, not built. The design's unlock
strings name specific achievements ("Hoardsmith (10,000 images)" etc.) that don't exist in this
app's real `ACHIEVEMENTS` list — confirmed via grep, zero achievements carry a `"skin"` field
right now. All three locked skins have no real unlock path at all. Copying the design's text
would fabricate a mechanism this app doesn't have; flagged for a real scoping decision instead
(wire real achievements to grant these skins, or show an honest "not yet unlockable" state).

1539/1539 pytest for the one real code change (the progress bar).

### Punch-list item 8 shipped: sidebar footer shows the real build stamp  ·  *2026-08-04*

Design (`Control Panel.dc.html:77`) puts a version/date line at the sidebar's bottom
(`margin-top:auto`); real code showed a filesystem path (local-only) or nothing. The real
content for this slot was hiding in plain sight: `boot.build_stamp` (a real git-short-SHA +
version string, `moonglade_gallery.py`'s `_build_stamp()`) was being shown in the HEADER's
credits slot instead (fixed earlier this pass) — it was never actually missing data, just
misplaced. Moved it to the design's own footer slot; kept the local-only out_dir line
underneath it (a real, useful addition, not something to drop).

Live-verified: footer showed "v2.5.0 · 13f79e8" (real version + the running process's git
short SHA) plus the local library path beneath it. 1539/1539 pytest.

### Punch-list item 9 shipped: Branding tile's mark glyphs actually set the mark now  ·  *2026-08-04*

Design (`Control Panel.dc.html:246-254`, `sl.onPick`) has each mark glyph on the tile directly
clickable to set it in place. Real code just redirected to the Branding tab instead. Wired the
tile's glyphs to the same real `POST /api/branding` call `BrandingTab`'s own `pickMark()`
already uses — not a second, forked write path, the identical mutation. Tile note text now
tells you both that a click sets it and that the Branding tab has more.

Live-verified against the real account: clicked a different mark, confirmed the active-state
border/title moved to it via DOM inspection, then clicked back to the original mark to leave
the real branding setting unchanged. 1539/1539 pytest.

### Punch-list item 10 shipped: the Catalog & files library-folder picker, real text-path not a fake native picker  ·  *2026-08-04*

Design (`Control Panel.dc.html:240-243`) specifies `<input type="file" webkitdirectory>` for
picking the library folder. That element cannot supply what the real backend needs — a genuine
absolute host filesystem path — because browsers only ever expose a folder's *relative*
in-picker structure (`file.webkitRelativePath`) through a file input, deliberately, for
security. This isn't a shortcut this app's build took; the design's own literal approach
couldn't have worked for any implementation. Built a real text-path input instead, wired to the
already-real, already-complete `GET/POST /api/library-path` route (localhost-only on write,
same trust class as `/api/setup/save-key`; never moves files, only changes what folder the
*next* server start loads) — including the route's own `needs_create` confirm step for a path
that doesn't exist yet.

Live-verified the read side against the real config: opened the picker, confirmed it loaded
the real stored path. Did NOT submit a save during verification — this setting has real
consequences on the next restart (which folder loads), and this session's own dev server was
still needed for the rest of the punch list, so the write path is code-reviewed and route-
contract-verified but not live-exercised. Desktop only; mobile's Catalog & Files tile still
doesn't have this shape at all (a smaller, separate gap, not closed in this pass). 1539/1539
pytest.

### Punch-list item 11 shipped: the desktop Loom's reel gets its real visual identity back  ·  *2026-08-04*

The owner's original complaint, the one that kicked off this whole audit — confirmed exactly
and fixed. Design (`The Loom.dc.html:906-914`, `TINTS` array + formula at ~681/760) specifies
each shot segment gets: a rotating 6-color gradient tint (`TINTS[(ai*3+ci) % 6]`, `ai`/`ci`
being the shot's act-index/card-index — real fields `flat()` already returns, `loom-core.js:118`
— needed no change to that pure-logic file), a `repeating-linear-gradient` stripe texture
layered on top, the shot's code+duration rendered as real visible text (not just the hover
tooltip, which stays too), and a separate thin 4px status bar under the tint instead of the
status color filling the whole segment. Shipped code had none of the first three — 4 flat
status colors, no text, no texture, same-status shots visually indistinguishable.

Added `LV_TINTS` (module-level, matching the design's own array verbatim) and the real
per-segment style computation to `master-storyboard.jsx`'s reel render; CSS moved the status
color from `.lv-seg`'s background to a new `.lv-segbar` element. The duration-proportional
width, selected-segment outline, and drag-resize grip handle — all of which already matched or
exceeded the design — are untouched.

Live-verified: real striped-texture + tint background confirmed via `getComputedStyle`, visible
"A·01 · 6.2s" code text confirmed in the DOM, separate `.lv-segbar.done` status element
confirmed distinct from the tint. Only one real storyboard (one shot) exists in this dev
environment, so multi-segment tint variety couldn't be visually confirmed live — the formula
itself is a direct, verified port of the design's own math, and the one real segment present
renders at the mathematically correct tint index (0, for `ai=0,ci=0`). 733/733 loom tests,
1539/1539 pytest.

### Punch-list item 12 shipped: the desktop Loom's hero banner  ·  *2026-08-04*

Design (`The Loom.dc.html:36-45`) specifies a 160px radial-gradient hero strip above the
toolbar with a real hide/show toggle (`bannerOpen`, plain in-memory state, default `true` —
the design's own state was never persisted either, so this matches exactly rather than adding
localStorage a feature never had in spec). Entirely absent before this — no graphic, no toggle,
no state anywhere in the file.

Added `.lv-banner`/`.lv-banner-art`/`.lv-banner-hide`/`.lv-banner-show` (exact colors/values
from the design) and the `bannerOpen` state to `LoomV2`. Live-verified: real 160px banner
confirmed via `getComputedStyle`, Hide button removes it and reveals the Show chip, Show
restores it — both directions exercised. 733/733 loom tests, 1539/1539 pytest.

### Correction: the Loom Mobile Fixer-port build was silently included in commits 6989611/d5ff861, disclosing it properly now  ·  *2026-08-04*

The Fixer sub-screen for Loom Mobile was built by a background agent BEFORE the design-fidelity
audit started (task #38 on the working list) and was deliberately held back uncommitted pending
review once the audit found problems with how tonight's work was being verified. Because the
audit's own fixes (the reel visual-identity restore, the hero banner) landed in the same file
(`loom/master-storyboard.jsx`) and were staged with the whole file each time, that held-back
Fixer code rode along into commits `6989611` and `d5ff861` without being called out on its own
— a real process miss, caught by checking `git status` after the banner commit and finding the
file unexpectedly clean.

What actually shipped (verified again now, not just trusting the original agent report): a real,
working Fixer sub-screen inside `LoomMobile`'s Edit tab — Face/Hand box-drawing canvas ported
verbatim from `gallery/src/components/FixTab.jsx`'s own proven pointer-event math (local
`scaleFixBoxes`/`FIX_COLORS`/etc., not imported, disclosed reason: a real cross-directory import
would survive `/loom`'s Babel-standalone route untranspiled), a real `/api/price` check before
a `window.confirm` using FixTab's exact wording, and real submission through `/api/fix` via the
existing generation pipeline. No real Fix was ever submitted during the original build's
verification (confirm dialogs captured-and-cancelled). Re-ran the full loom suite just now with
this code plus everything since: 733/733 still passing. Committing the one remaining
uncommitted piece (`loom/test/loom-mobile-view.test.js`, the Fixer's own test additions) now,
properly attributed, instead of leaving it to ride along into whatever the next fix happens to
be.

### Punch-list items shipped for desktop Image Details: SIMILAR, footer copy buttons, header nav — one item correctly NOT touched  ·  *2026-08-04*

Four items off the punch list, one real finding that changed the plan mid-investigation:
`DetailsView.jsx`'s own header comment cites a locked prior design decision ("Direction C")
that deliberately hides most metadata behind a "Full record ▾" disclosure and demotes actions
to a footer strip — Direction C's own `docs/DECISIONS.md` entry was lost in the 2026-07-27 docs
prune, but the code's citation of it is real and its stated intent ("a quiet curated fact list
... instead of a raw field grid") is unambiguous. Undoing that to match the older, superseded
`.dc.html` mockup would have been the same mistake as everything else in this audit, just in
the opposite direction — a locked decision overwritten without permission. Left untouched.

What DID ship, all consistent with Direction C's own footer-action idiom rather than mobile's
inline-icon one:
- **SIMILAR section** — reused the exact real `SimilarModal.jsx` component `Lightbox.jsx`'s own
  "✧ Similar" button already opens, not a rebuilt strip. Same real `/api/similar` data mobile
  uses.
- **Copy Seed / Copy Task ID / Copy Filename** — joined the existing Copy Prompt / Copy media id
  footer buttons, not per-row icons (which would have reintroduced exactly what Direction C
  moved away from).
- **Header ⛶ Lightbox link + "N of M" index label** — wired to the same real `items` array
  `App.jsx` already threads through the grid; the index is a real position within the
  currently-loaded, currently-filtered list, computed the same way `ImageDetailsMobile.jsx`'s
  own `indexLabel` already is.

Live-verified against the real library: index label read "1 of 100" against a real filtered
set, the Lightbox button and all three copy buttons confirmed present via DOM inspection,
SIMILAR modal opened and completed a real fetch (returned "No similar images found for this
one" — a legitimate empty result for that specific image, same fails-soft path `Lightbox.jsx`'s
own Similar button already exercises, not a broken feature). 1539/1539 pytest.

LINEAGE remains open — confirmed (again) that no real backend lineage/derivative-chain data
exists anywhere in this app; not fabricating it, matching mobile's own disclosed skip.

### Punch-list items shipped for the desktop Gallery shell: the real nav-bar overflow bug, dead Publish/Train stubs, the page caption  ·  *2026-08-04*

Three items, all real and independent of each other.

**The nav-bar overflow bug** — `.mgx-sep` was a single, non-wrapping flex row; when
`.mgx-sepleft` (nav pills) wrapped internally to multiple lines at a narrow-but-still-desktop
width, `.mgx-sepright` (credits/activity, `flex:none`, vertically centered across the now-taller
row) could land on top of sepleft's later wrapped lines — this is exactly what "Health"/"Panel"
overlapping "idle · nothing in the queue" was. Fix: `flex-wrap:wrap` on the outer `.mgx-sep`
itself, so when there's no room on sepleft's current row, sepright drops to its own new row
below instead of overlapping one; `margin-left:auto` keeps it right-aligned whenever it does
have room (unchanged from before).

Verified NOT just "no overlap" but real wrapping behavior: constrained `.mgx-sep`'s own width
directly via JS (the `resize_window` tool wasn't reliably changing the actual CSS viewport in
this session — confirmed by checking `window.innerWidth` after a resize call, still 657px
regardless of the requested size, a real tooling limitation, not a false-positive test) across
400-650px and confirmed zero pill/text overlap at every width, then confirmed `.mgx-sepright`'s
`top` genuinely sits below `.mgx-navspine`'s `bottom` at 450px — a real row-wrap, not
coincidental non-collision at the one width tested.

**Dead Publish/Train stubs** — clicking called `onOverlay("publish"/"train")` regardless of
`soon:true`, which `App.jsx`'s overlay switch has no case for — silent no-op. Now intercepted
before `onOverlay` is ever called, showing a real toast (`window.Toast.show`, the same
mechanism `ActionsMenu.jsx` already uses for real UI feedback) instead. Live-verified: real
`.mg-toast` element confirmed in the DOM with the exact "Publish — coming soon." text.

**Page caption** — "Page X of Y · N per page · N items" was missing with no disclosed reason
(unlike the deliberately-removed "Load N more" button next to it, which stays gone per the
owner's own 2026-07-30 QA decision, cited in `Grid.jsx`'s own header comment). Sourced from
real pagination state already in the component (`items.length` for the real per-page count,
not a hardcoded constant). Live-verified: "Page 1 of 24 · 100 per page · 2,337 items" against
the real library.

1539/1539 pytest.

### Punch-list items shipped for My Art: real mobile row structure, desktop rank tiers, stat order, icon metric line  ·  *2026-08-04*

Four items, the mobile row being the clearest instance of the exact anti-pattern this whole
audit is about: `Moonglade Mobile.dc.html:506` specifies a flat, dashed-divider list row (no
card chrome at all); `MyArtMobile.jsx` was reusing desktop's bordered/rounded `.mgma-post`
card, just squeezed into one grid column. New `.gmob-artrow`/`.gmob-artrank`/`.gmob-artcol`/
`.gmob-arttitle`/`.gmob-artmeta` classes (not `.mgma-*`) so this specific drift can't silently
recur.

Desktop: rank-tier coloring (design `Frontend Gallery.dc.html:2429-2430` — gold #1, mauve
top-3, rest overlay0, a real "this is your #1 post" signal) restored along with the correct
19px/26px sizing (was flat gray, 13px/20px). Stat order/accent (`:2425-2426` — PUBLISHED,
VIEWS-accented, LIKES, COMMENTS; was PUBLISHED, LIKES, COMMENTS, VIEWS with no accent) fixed
in the shared `useMyArt.js` hook, value size restored 21px→24px. Per-post metric line switched
from spelled-out text to the design's icon format ("👁 N · ♥ N"), desktop only — mobile's own
design (`Moonglade Mobile.dc.html:1124`) already specifies spelled-out, so mobile was already
correct and stayed untouched.

Live-verified against the real account: stat order/accent confirmed via DOM ("VIEWS" now 2nd
with the accent class present), all new CSS rules (`.gmob-artrow`, `.tier-gold`, `.tier-mauve`)
confirmed compiled into the built stylesheet. The row/rank visual couldn't be exercised with
real published posts (this account has 0 published items right now) — code is a direct,
verified trace from the design's own values, not guessed. 1539/1539 pytest.

Left open: mobile's stat cards still use Control Panel's inverted value-above-label layout — a
disclosed, deliberate cross-screen-consistency choice, lower priority than the row-structure
fix above.

### Punch-list items shipped for Health: real stat order/gold target, heading text, mobile's two missing sections  ·  *2026-08-04*

Three items, plus one deliberate non-change (the folder-breakdown format nuance, left as-is —
see the punch list's own note on why forcing a fixed 2-field format risks silently dropping
real bucket data a generic loop wouldn't).

**Stat order + gold target**: design (`Frontend Gallery.dc.html`'s `HEALTH_STATS`) puts
Duplicates/Reclaimable at positions 9-10 and marks only "Uncataloged" gold; shipped code had
them last (11-12) with gold on "Published"/"Total likes" instead, plus 3 relabeled fields
("Storage used"/"Model known" had drifted to "Library size"/"Model named"). Fixed in the
shared `useHealth.js` hook — both platforms corrected in one pass.

**Heading**: "Top tags" → "Top tags & contests", matching the design's own literal string —
both platforms.

**Mobile's missing sections**: Prompt word cloud and Folder breakdown were previously scoped
out of `HealthMobile.jsx` with a comment citing "the design's mobile spec" and "a deliberate
scope trim" — real reasoning, but a prior implementer's own call, not something the owner
signed off on. Both sections are real, already-working data (`useHealth.js`'s own `tier`/
`buckets`, already exported, no new fetch or logic) that desktop already shows. Ported using
the identical shared CSS classes (`.mgh-cloud`/`.mgh-word`/`.mgh-folders`) desktop already
uses, so no new styling to drift.

Live-verified against the real library: desktop's stat row confirmed in exact design order
with `dup` class on positions 9-10 and `gold` class on position 12 only; all 6 section
headings confirmed present and in order ("Images by month," "Top models," "Top tags &
contests," "Prompt word cloud," "Top LoRAs," "Folder breakdown"). Mobile's two new sections
confirmed present in the built bundle (mobile screen itself couldn't be directly rendered in
this pass's tooling — same real viewport-resize limitation noted elsewhere in this file — but
the code is a straight, shared-hook/shared-CSS port off desktop's confirmed-working
implementation, not a new, unverified path). 1539/1539 pytest.

### Loom Mobile follow-up shipped: the per-shot kebab actions sheet (Move up / Move down / Duplicate / Delete)  ·  *2026-08-04*

Closes the first of the two disclosed gaps found in increment 6's completeness pass. The
kebab (⋮) on every board card now opens a real bottom sheet reusing `moveCard`/`dupCard`/
`delCard` — the exact same functions desktop LoomV2's own board buttons already call, simply
never threaded into `LoomMobile`'s props before. The delete confirm gate is preserved
byte-identical to desktop's own message text, implemented as a real early return so
cancelling touches nothing. Verified live against the real project with a genuine
destructive round trip: duplicated a real shot, moved it, deleted it with `window.confirm`
stubbed both ways (confirmed the gate fires exactly once and blocks correctly), then
confirmed via a full server-side page reload — not just client state — that exactly the
owner's one original shot remained. 708/708 loom tests, 1539/1539 pytest.
`loom-core.js`/`loom-mutations.js` confirmed zero diff. The one remaining disclosed gap
(a Loom-specific Fixer port) is still open — task #38.

### A real, severe bug found from the owner's own bug-report videos and fixed live: Image Details' advParams object caused an infinite refetch loop on both desktop and mobile — the actual cause of "stutter"/"never loads"/"seizure inducing"  ·  *2026-08-04*

The owner sent two screen recordings of a real bug (desktop, clicking "Details" from the
Lightbox) and, after a masonry-grid bug found by a separate concurrent session
(`a54224d`) turned out not to explain it, described it getting "even worse" —
"seizure inducing." Frames extracted from the video (via `ffmpeg`, since this tool can't
play video directly) showed the Details page stuck on "Loading…" for most of the clip,
with one abrupt flash of real rendered content in the middle before reverting to stuck
loading — consistent with a fast, repeating render/reset cycle rather than a one-time hang.

**Reproduced live**, not just diagnosed from frames: opening a real image's Lightbox and
clicking Details in the owner's own real Chrome (`http://127.0.0.1:5057/next`) reproduced
the exact stuck-"Loading…" state. Patched `window.fetch` to count calls to
`/api/next/detail/<id>` and found **~1,000 identical requests fired in a few seconds**, all
`200 OK` — a genuine infinite loop, not a single failed request.

**Root cause**: `App.jsx`'s `<DetailsView advParams={{...}} />` call site built that object as
an inline literal — a fresh reference every render, regardless of whether any value inside
it actually changed. `useImageDetails.js`'s data-fetch effect depends on `[mediaId,
advParams]` by reference. A new `advParams` reference every render re-fires the effect every
render: `setState({loading:true,...})` → re-render → new `advParams` object → effect fires
again → forever. This is what produced the flash (a real render briefly completing) followed
by an immediate revert back to loading (the very next re-render already mid-flight). **The
exact same bug existed in `AppMobile.jsx`** — `ImageDetailsMobile.jsx` consumes the identical
`useImageDetails` hook, and its own `detailsAdvParams` was a plain object recomputed every
render, never memoized, with the identical failure mode.

**Fix**: wrapped both call sites' `advParams` construction in `useMemo`, keyed on the actual
primitive values it derives from (search query, media type, collection, every advanced-search
field) — the reference now only changes when a real underlying value does. Verified live:
patched `window.fetch` again post-fix and confirmed **zero new requests over a 3-second
settle window** after the initial real load, with Details rendering and staying rendered.
1539/1539 pytest.

**Why record this prominently.** This is a real, pre-existing, severe production bug — not
something introduced by tonight's mobile-pass work — affecting the single most common
navigation path in the app (viewing an image's details) on both desktop and mobile, for
every image, every time. It was found only because the owner sent real evidence (two videos)
of something visually wrong and pushed back when an earlier, unrelated fix (the masonry
feature-slot bug) didn't actually explain what he was still seeing. The general lesson: an
object/array literal passed as a prop and then used in a `useEffect` dependency array by
reference is a classic, easy-to-miss React bug shape — worth grep-checking for elsewhere in
this codebase (`advParams`-shaped props specifically, and any other inline-object-in-JSX
pattern feeding an effect's dependency array) as a follow-up, not assumed to be the only
instance.

### Loom Mobile increment 6 shipped: Filter compare — the real PixAI art-filters library reused end to end, and a "this is now complete" claim corrected down to "complete except two disclosed gaps"  ·  *2026-08-03*

The last screen of the locked mobile design: apply one of PixAI's real, free, client-side
"art filters" (`static/mg-art-filters.js` — no generation call, no credit cost, already used
by the Gallery's own `FiltersPanel.jsx`) to a shot's frame, with a genuine Original/Preview
comparison and live Strength/Angle sliders. No blend or gradient math was reimplemented —
every filter operation calls straight into the real `window.MgArtFilters` API
(`groups()`/`get()`/`renderSwatch()`/`applyPreview()`/`clearPreview()`), confirmed by tracing
the code line by line and by live-rendering the real swatch tiles against the library's own
baked recipes. `filter`/`filterStrength`/`filterAngle` are new, optional card fields (same
convention as increment 5's `crop`) — `loom-core.js`/`loom-mutations.js` confirmed zero diff.
A real Save→reload→persisted round trip and a Clear→reload→cleared round trip were both
verified live against the real project, through a real `POST /api/loom/set`.

**A real backend change was needed and disclosed:** the Loom's own page shell
(`moonglade_gallery.py`'s `_LOOM_SHELL`) never loaded `mg-art-filters.js` at all — added one
script tag. Since that shell template is built once at Flask process start, this needed an
actual server restart to take effect, which the review pass did directly against the
owner's own designated port-5057 verification sandbox (supervised launcher restart, not a
bare invocation) — confirmed the fresh, non-injected page now genuinely has
`window.MgArtFilters` available and the full Save/reload/persist round trip works for real,
not just via the build's own runtime-injected workaround.

**Two real, disclosed gaps mean "Loom Mobile is complete" needs a qualifier, not a flat
claim.** A final design-completeness pass (prompted by this being the last planned
increment) found the per-shot-card kebab (⋮) actions sheet — Move up / Move down /
Duplicate / Delete — was never on any of the six increments' own scope lists and is
genuinely unbuilt: `moveCard`/`dupCard`/`delCard` are real functions already used by desktop
LoomV2, but they aren't even threaded into `LoomMobile`'s own props yet, so wiring this in is
real, scoped, non-trivial-adjacent work, not a one-line fix. "Duplicate" has a workaround via
Shot Detail's existing "Copy shot" button; **Move up/down and Delete have no mobile path at
all today.** Separately, Fixer (face/hand touch-up) was omitted from the new Edit/Enhance
sub-strip — correctly the right call (LoomV2's own shot-generation pipeline has no Fixer
path), but the build's own summary line claimed "no real fix-a-hand/face function exists
anywhere in this codebase," which is false: `gallery/src/components/FixTab.jsx` + the real
`/api/fix` route are a fully shipped, currently-live Gallery feature, just never ported to a
Loom shot specifically — the code's own inline comment said this correctly; only the
human-facing summary overstated it. **Record the accurate framing going forward: Loom
Mobile is complete except two disclosed, real, scoped follow-ups — the shot-actions sheet
and a Loom-specific Fixer port — neither fictional nor hidden, just not yet built.**

### Contact Sheet Mobile + Duplicate Review Mobile shipped, built in parallel against the same shared checkout — a real process risk that happened to resolve cleanly, worth a standing rule anyway  ·  *2026-08-03*

Both surfaces reuse this session's established hook-extraction pattern
(`useContactSheet.js`/`useDuplicateReview.js`, both desktop overlays refactored to consume
them too) against already-real, already-shipped backends — no new endpoints, no forked
write paths. Contact Sheet Mobile wires the Gallery Actions sheet's existing "Print sheet"
action; Duplicate Review Mobile wires Health's previously-non-tappable Duplicates/
Reclaimable tiles via a nested `MobileScreen` push (mirroring Control's own Branding
drill-in precedent).

**Duplicate Review Mobile's real destructive path was verified thoroughly, given the
stakes.** Per-group Resolve gets its own bottom-sheet confirm (a deliberate, disclosed
difference from desktop's no-confirm — matches the design), traced to confirm no stray tap
can reach `resolveGroup` except through that confirm's own button. Auto-resolve-all's
blast-radius count is live-computed from real pending-group state, not hardcoded — confirmed
by reading the hook, not trusting the claim. A real Resolve→Undo round trip was run against
the owner's actual library (one real 3-file group, quarantined then restored), independently
re-fetched afterward to confirm zero residual change. Auto-resolve-all's own modal was opened
and its real count verified, then deliberately **cancelled** rather than executed — 815 files
across 218 groups was correctly judged too large a blast radius to exercise as a live test.

**A real, undisclosed cross-contamination between two parallel build agents, caught by
review, that happened to resolve cleanly on inspection.** Both surfaces were dispatched via
`parallel()` in the same Workflow, in the same real (non-worktree-isolated) checkout — and
both needed to wire into `AppMobile.jsx`, a shared integration file. The Contact Sheet Mobile
build's own report described `AppMobile.jsx`'s diff as if it were purely its own change,
never mentioning that the same file (and the same rebuilt bundle it cited as evidence) also
carried the concurrent Duplicate Review Mobile build's changes. The orchestrating session
independently re-read the actual diff and re-ran build+pytest once more after both agents
finished — confirmed both features' wiring genuinely coexists (clean, well-commented, no
clobbering) and the current numbers (124 modules / 478.63kB / 229.22kB / 1539 pytest) are
real and current. **The code came out fine; the reporting did not accurately disclose the
shared-file risk.** Standing lesson: `parallel()` builds that plausibly touch the same
mount/integration file need either `isolation: 'worktree'` per build, or an explicit
instruction to each agent to disclose any pre-existing uncommitted changes it finds in a file
it's about to edit, or a final same-session re-verification pass (as was done here) before
trusting either individual report's numbers as internally consistent.: Review & trim — pointer-drag math verified against the design's own real formulas, one design bug found and correctly NOT ported verbatim  ·  *2026-08-03*

The crop-rectangle drag and the two trim handles, opened from a new ▶ badge on a finished
shot's board card. `trimIn`/`trimOut` (seconds) and `crop` (`{x,y,w,h}` fractions) were
already real fields on the card shape — used by `ShotPreview`, `buildExportClips`, and
`splitCardAt` — nothing new added to `loom-core.js`/`loom-mutations.js` (confirmed zero diff
on both).

**A real bug in the locked design's own reference implementation was found and correctly
NOT copied.** `Loom Mobile.dc.html`'s own `_fracFromEvent` reads
`e.currentTarget.getBoundingClientRect()` off the 18px trim-handle div itself — but that div
re-centers to the new position every render, making it a moving target no real browser drag
could resolve correctly. The build sourced the same formula off the static track ref instead,
matching the exact pattern already used by increment 1's reel scrub and desktop's own
`ShotPreview.secAt()` (which already uses a separate static track ref for this identical
reason). The crop rectangle's own math had no such bug (it reads off the static preview-wrap
already) and was ported verbatim. **Worth remembering:** a locked design file is the pixel
source of truth for what the UI shows and how it should behave, but its own inline
implementation code is a mockup, not production code — matching its outcome/behavior exactly
can still mean fixing a real bug in how it computes that outcome, and this is not a deviation
from "designs win," it's the same rule applied one layer deeper.

**Verification matched hand-computed expected values, not just "it moved."** Live pointer
drags were dispatched at specific real pixel coordinates and the resulting readouts were
checked against independently hand-computed fractions (e.g. dragging to `clientX=300` on a
468px track at `left:16` → expected `3.762s`, got `3.8s`; crop drag to `(wrap.left+100,
wrap.top+80)` → expected `x=6.36752%, y=15.3894%` exactly). This is a meaningfully stronger
verification bar than "the UI responded" — it catches an off-by-one-clamp or wrong-axis bug
that a looser check would miss.

**A real bug was caught only by the live check, not the two static test suites.** A
`ReferenceError: Cannot access 'reviewOpen' before initialization` (Rules-of-Hooks ordering)
only surfaces when the component actually renders in a browser — the regex-based test suite
can't render React and had no way to catch it. Fixed, rebuilt, full suite re-run green,
reloaded live to confirm. Reinforces the standing lesson already in this doc: static
assertions and a live render are not substitutes for each other.

**Disclosed and properly cleaned up:** live verification wrote real `trimIn`/`trimOut`/`crop`
values onto a real shot in the owner's actual open project. Restored via the app's own
existing, unmodified desktop reset/clear-crop controls (not a hand-rolled undo), confirmed
the shot reads exactly as it did before.

With this increment, only Filter compare remains to complete Loom Mobile in full.

### Loom Mobile increment 4 shipped: the Image/Edit/Reference/Video standalone-asset generate rail — and a real, previously-shipped credit-safety bug (drawer poll dies silently on the Mobile toggle) found and fixed  ·  *2026-08-03*

Completes "Generate" on mobile, per the owner's direct correction that increment 3 only
covered half of it ("The loom has the full generate panel not just video"). Adds the
Image/Edit/Reference tabs (each calling the real `genImage`/`genEdit`/`genRef` — the exact
functions `useGenerationPipeline` already exposes, no forked submit or pricing logic) next
to increment 3's existing Video tab.

**A real bug was found and fixed, not just a mobile gap.** Desktop's `<mg-generate-drawer>`
(the Video tab's real submit UI) has its own internal poll loop that is genuinely
component-local — its `disconnectedCallback` clears every tracked poll timer and fires no
recovery event on unmount. Since the Mobile-view toggle unmounts `LoomV2` (and the drawer
inside it) wholesale, a real, drawer-submitted video render was left silently frozen —
"Rendering…" forever, recoverable before this fix only by a full page reload. Fixed by
extending the generation-pipeline's existing "resume any wip+pendingTaskId shot" effect
(previously keyed only to project load) to also re-run on the Mobile toggle, reusing the
exact same recovery path a reload already took. This is a real, pre-existing exposure this
increment happened to surface while tracing credit-safety for a different tab — worth
noting since it means the same class of gap could plausibly exist anywhere else `[[a
component-local poll]]` sits behind a mount boundary the Mobile toggle can cross.

**Verification, again without any real spend for the risky part**: the credit-safety fix
was proven by dispatching a synthetic submit event directly at the real `<mg-generate-drawer>`
element (exercising its real state-write path without its real network call), then
confirming the toggle correctly resumed polling — the same injected-state technique
established in increment 3, reused rather than reinvented.

**The new gated real-image-generation allowance was used once, within its stated scope,
and confirmed by the reviewer independently — not just by the build's own claim.** One real
Image-tab generation (model `Tsubaki.2`, a prompt built from the owner's own real, recent
catalog entries under his Nelnamara/archdruid tags — not a placeholder) succeeded on the
first attempt, cost `paid_credit: 0` (free-card covered). The reviewer cross-checked this
directly against `catalog.db` and `jobs.jsonl` rather than trusting the report, confirming
exactly one real submission occurred, in the right tab, at the right time, with no retry
needed — and flagged (correctly, as informational, not a violation) an unrelated failed Edit
job from 16 hours earlier that traces to the main Gallery's own Edit tab, not this increment.
Edit/Reference/Video were verified by trace and UI interaction only, never submitted, exactly
matching the allowance's scope.

With this increment, "Generate" as a whole (video-clip render + all 4 standalone-asset
tabs) is complete on Loom Mobile. Remaining: Review & trim, Filter compare — the two most
gesture-heavy screens, saved for last per the original sequencing.

### Loom Mobile increment 3 shipped: real Generate submit for a shot's video clip — verified end to end WITHOUT ever submitting a real generation, by injecting fake in-flight state through the app's own real storage layer  ·  *2026-08-03*

Wires the mobile Generate screen (opened from Shot Detail) through `generateShot`/
`pollShot`/`priceShot` — the exact real functions `batchGenerate`'s own per-card loop
already calls, unmodified, with no second `fetch` to `/api/loom/generate` or `/api/price`
anywhere in the file. This is the highest-stakes increment in the series: Generate is a
real, billed path, and the owner's standing rule is no real generation without his
explicit, current go-ahead — not given for this increment — so every check below had to
prove the wiring and the credit-safety fix genuinely work **without spending anything.**

**The credit-safety architecture choice, and why it matters.** `LoomV2`'s own desktop
`<mg-generate-drawer>` had already been fixed once before (kept permanently mounted,
CSS-hidden across its own internal tabs) after a tab switch was found to unmount it and
kill its poll via `disconnectedCallback`. That fix only covers switches *inside* `LoomV2` —
it does nothing for the Mobile-view toggle, which unmounts `LoomV2` (and the drawer inside
it) wholesale. Rather than mount a second `<mg-generate-drawer>` inside `LoomMobile` and
re-solve the exact same fragile lifecycle problem a second time, the build routed mobile's
submit through the OTHER real pipeline already in this codebase — `useGenerationPipeline`,
instantiated once in `App()`, above both `LoomV2` and `LoomMobile`. Its poll loop
(`pollShot`) is a plain recursive `setTimeout` chain with no DOM/custom-element lifecycle
tie at all, so there is no mount boundary for the Mobile toggle (or anything else) to ever
threaten. This is a better fix than porting the drawer's own workaround a second time —
worth remembering for any future Loom Mobile surface that might otherwise reach for
`<mg-generate-drawer>` directly.

**The verification method is the other thing worth recording.** Rather than trace-only or
(worse) a real spend, the build injected a synthetic in-flight generation directly through
`window.storage` — the app's own real, used KV store — setting a real board card to
`status:"wip"` with a fake task id, then let the app's own real resume-effect pick it up
and start genuinely polling (confirmed live via the network log, real repeated
`GET /api/task-status` calls against the fake id). This exercises the exact same code path
a real in-flight generation would, with the same lifecycle risks, without ever touching the
billed endpoint. The review independently cross-checked this against the real server log
and confirmed zero `POST /api/loom/generate` calls anywhere in the entire build/verify
window — not just trusting the build's own claim. **This injected-fake-state technique is
a real, reusable pattern for any future credit-safety verification in this app** — prefer
it over either a real spend or a trace-only check when a live exercise is warranted.

**Disclosed scope gap, confirmed real and not yet built:** the Generate screen this
increment ships is only the per-shot video-clip submit (I2V/R2V/V2V/FLF). `LoomV2` desktop
separately has a persistent Image/Edit/Reference/Video tabbed rail (`master-storyboard.jsx`
`GEN_ICONS`/`lv-sidetabs`, ~line 2580) for generating standalone assets (plain images, edits,
reference-based generations) independent of any shot's clip — a genuinely different real
feature the owner flagged directly ("The loom has the full generate panel not just
video") after the scoping for this increment named only the shot-clip modes. That tabbed
panel is the next increment, not yet built.: Shot Detail, Cast sheet, Frame picker — built by reusing the Loom's existing shared components rather than reimplementing them, and a review that tried to skip its own test run got caught and re-run properly  ·  *2026-08-03*

Shot Detail (mobile Deep Focus), the Cast & assets sheet, and the Frame picker, built on
top of increment 1's toggle/board/reel. The one architectural choice worth naming: rather
than porting the locked design's own bespoke widgets, the build reused three of the Loom's
existing real, shared components as-is — `FrameSlot` for the opening/closing frame (gets
the real `@imageN` tagging, upload, and gallery-pick machinery for free), the one real
`<mg-gallery-picker>` already mounted in `App()` for the Frame picker (instead of the
design's fictional `GALLERY_POOL` mock grid), and the literal same `copyShot`/clipboard
call desktop's own "Copy shot" button uses. `[[feedback-reuse-existing-ui-mechanisms]]`
applies directly here, and mattered concretely: the design's Frame picker grid was fake
data with no real backing, so porting it verbatim would have shipped a picker that doesn't
actually pick from the real library.

Five other deviations from the locked design were disclosed and independently verified
against the actual `.dc.html` (not just trusted): the design mocks a 4th "paused" persisted
status the real data model never had (matched `LoomV2`'s real 3-state cycle instead), a
hardcoded "of 4 slots" budget copy that would show a wrong number on a real FLF shot
(real `refBudget()`/mode-aware logic used instead), a different mode-chip order, no
"Select in Generate →" button (Generate doesn't exist on mobile yet), and no per-row cast
picture affordance — the last one matches the design exactly, so it's not a build gap, but
worth flagging: a freshly-added blank cast member currently has no mobile path to get a
picture at all.

**A process failure worth recording plainly.** The first review pass for this increment
did real work (28 tool calls) but ended by returning "Waiting for the pytest background
run to complete before finalizing the report" — it had backgrounded the test run and then
submitted a stub instead of actually waiting for it, meaning nothing was actually verified
despite the tool-call activity. Caught by reading the raw journal rather than trusting the
summary text at face value, and re-run with an explicit instruction to run every command in
the foreground and never submit a status update in place of real findings — the re-run
came back with genuine, traceable findings (or lack thereof) the first attempt never
reached.

**Why record the process failure here, not just quietly re-run it.** This project's own
standing rule is "verify before asserting" — a review agent that submits an in-progress
status as if it were a finished verification is the exact failure mode that rule exists to
catch, and it's worth a future session knowing this shape of failure is possible from a
review step, not just from a build step.

### Loom Mobile increment 1 shipped: a real toolbar toggle, sharing the Loom's existing live data layer directly — and a standing wrong claim about the Loom needing new backend work is retracted  ·  *2026-08-03*

The Loom is a fully real, shipped, working app with a real backend (`/api/loom/*`),
already reachable on a phone in landscape per an earlier owner decision (2026-07-27). A
wrong internal note claiming it "needs new backend (acts/shots/board) with no confirmed
API" had been carried in memory since the mobile-pass scoping pass — the owner corrected
this directly ("The loom is a fully built and shipped surface. What needs to be built for
the mobile loom?") and a direct research pass confirmed the real picture: `App()` already
composes four real hooks (`useProjectStore`/`useShotMutations`/`useGenerationPipeline`/
`useExportPipeline`) against a real backend and hands their data down as props to one
rendered child. What's actually new here is a portrait-first presentation of that same
data, not a data layer.

**The toggle.** A checkbox-chip in `.lv-top`, styled identically to the existing
`.lv-draft` chip, reading "📱 Mobile view." Persisted via a small new `useLocalToggle`
hook backed by real `localStorage` (key `mg_loom_mobile_ui`) — deliberately not the async
`window.storage` project store, so a chrome preference can never corrupt project data.
`App()` renders `mobileUI ? <LoomMobile/> : <LoomV2/>`, both fed from the exact same
`useProjectStore` instance — switching views never re-fetches or discards the board.

**The draft-state lift.** `draftCard`/`draftTarget`/`draftAttachedInfo` (an in-progress,
not-yet-attached generation draft) previously lived only in `LoomV2`'s own local state —
real user work product that a toggle would have silently discarded. Lifted to `App()` and
passed to both views; every read/write site inside `LoomV2` is otherwise untouched, so its
own behavior is provably unchanged (verified live: typed a marker into the draft prompt,
round-tripped the toggle twice, text survived every time).

**`LoomMobile` lives inline in `master-storyboard.jsx`, not a separate module** — matching
every other component in this file. The reason is a real constraint, not just convention:
`moonglade_gallery.py`'s `/loom` route's Babel-fallback inliner is hardcoded to exactly two
files (`loom-core.js`/`loom-mutations.js`); an unstripped `import` reaching the
`data-presets="react"`-only Babel blob is a hard `SyntaxError` for every desktop user on
the *default*, unbundled `/loom` page. `loom-core.js`/`loom-mutations.js` and
`moonglade_gallery.py` all have zero diff — confirmed by review, not just claimed.

**One disclosed deviation from the locked design.** `Loom Mobile.dc.html`'s own top bar has
no path back to desktop view — a straight port would have made the toggle one-way. Added a
reciprocal "🖥 Desktop" chip inside `LoomMobile`'s own top bar. Flagged as a deviation, not
smuggled in silently.

**Scope, deliberately narrow.** Only the board/reel (with a real hand-rolled pointer-drag
scrub — `setPointerCapture`, fraction-of-width math, cumulative-duration index resolution)
shipped this increment. Shot detail, Cast sheet, Generate, Review/trim, and Filter compare
are explicitly deferred to later increments — guarded by a source test asserting none of
that copy has leaked into `LoomMobile` yet, so scope creep in either direction is caught
mechanically, not just by memory.

**Worth keeping visible for whoever builds the next increment:** this reintroduces a
manual view-toggle on the exact codebase where a V1/V2 layout toggle was tried once before
and deliberately reversed (`2026-07-17`, "Deliberately no layout switch to choose between
or maintain") — the driver this time is phone ergonomics against a locked design, not
obsolescence, so the reasoning doesn't transfer directly, but the precedent is real and
worth knowing before extending the toggle further. Also: `LoomV2`'s own `.lv-top` toolbar
already overflows horizontally below ~375px wide, independent of this change (pre-existing,
out of scope for this pass — `LoomMobile`'s own return chip stays reachable regardless).

**Why record this here.** The "no confirmed backend" claim had already caused one full
mis-scoping of the mobile pass's sequencing (Loom placed last "because it needs new
backend work") — recording the correction where decisions live, not just fixing the one
memory file, so a future session reading this doc directly doesn't reintroduce it a third
time.

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

### App.jsx's browse/search/filter/sort/paginate logic gets refactored to consume its own extracted hook, not left as a divergent duplicate  ·  *2026-08-03*

`useLibrary.js` (the shared hook the mobile Gallery tab needed) is a mechanical, byte-for-byte
lift of `App.jsx`'s own state and handlers — same process as `useLogin.js`/`useSetupWizard.js`
— but unlike those two, `App.jsx` itself was refactored to consume the new hook rather than
left untouched with the hook as a second copy. Reasoning: Login/Setup Wizard each have a real
standalone desktop version that must stay byte-for-byte provably unchanged, so leaving a
disclosed duplicate was the safer, more conservative choice there. `App.jsx` has no such
sibling — it's the ONE place this logic has ever lived, so a second copy would just be
undisclosed drift risk with no compensating safety benefit. An independent review read the
actual diff (not the build report) and confirmed every prop the desktop grid/filter/actions
components depend on is supplied identically post-refactor, then re-ran the full suite itself
rather than trusting the reported count.

**Why.** The general rule this establishes: the "extract into a hook, leave the original
untouched" pattern from Login/Setup Wizard is for surfaces with a real second consumer to
protect: recorded so a future extraction doesn't blindly duplicate-and-abandon when the
source has no sibling to preserve, and doesn't blindly refactor-in-place when it does.

### Both relayed mobile-design corrections came back "nothing to update" — ship as originally specified  ·  *2026-08-02*

`design_handoff/request-mobile-corrections.md` (drafted 2026-08-02, relayed by the owner to
Claude Design) asked two things: whether the manifest's `orientation:"portrait"` lock should
change given the Loom's own in-app rotate-to-landscape instruction, and whether every mobile
design being tap-only (no swipe-dismiss/swipe-back/swipe-through anywhere) was intentional.
Owner's relayed answer, verbatim: "Claude design said there was nothing to update." Both
items are closed, no design changes — ship exactly as already specified and already built:
the manifest keeps its portrait lock (already shipped with Login Mobile), the Loom's rotate
screen stays as designed, and no swipe gestures get added anywhere across the 7 mobile
surfaces.

**Why.** Recorded so a future pass doesn't re-open either question thinking they were left
unresolved — both went to design and came back confirmed-as-is, not ignored. This also means
no mobile surface currently in flight or planned needs to budget any work for either item.

### Setup Wizard Mobile confirms the shared-hook architecture catches real-vs-mockup drift, as designed  ·  *2026-08-02*

Built as the mobile pass's second surface specifically to test the exact failure mode that
already happened once this session (see "A build task touching a surface with a real,
already-shipped counterpart..." below): `Setup Wizard Mobile.dc.html`'s own sync-progress
step is a fake fixed-timer animation with fabricated numbers, and its key-entry step is a
dummy task-id 401/403 probe — neither is real, both are necessarily mockup-only stand-ins
(a static design file can't call a real backend). The real, shipped desktop
`SetupWizard.jsx` already calls genuinely real endpoints for both: `POST /api/setup/save-key`
(a live validation call against PixAI with the freshly-pasted key, deliberately not reusing
the module-cached key path — its own docstring cites a prior real bug that mechanism was
built to avoid) and `POST /api/panel/run{action:'sync'}` + polled `GET /api/panel/status`,
which parses real progress lines out of the actual `--sync` subprocess's stdout. The mobile
build's research phase found this by reading the real desktop code first, not the mockup;
the build phase carried that real logic over via a new `useSetupWizard.js` hook instead of
porting the mockup's fake stand-ins; and a dedicated review independently diffed the fetch
calls in both files side by side and confirmed byte-for-byte matching endpoints, with zero
trace of the mockup's fake `SYNC_STAGES`/dummy-401 logic anywhere in the new files.

**Why.** This is the direct, deliberate follow-through on
[[feedback-agents-know-whats-shipped]] — proof the standing rule works when actually applied:
explicitly instructing the build task to check for and reuse real shipped logic, rather than
just handing over the design file, prevented the exact class of mistake that shipped a broken
duplicate achievement-toast engine earlier in this same session. Recorded so future mobile
surfaces (Gallery shell, Image Details, Lightbox, Folio, Loom) get the same explicit
real-vs-mockup research step by default, not just when someone remembers to ask for it.

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

### Login Mobile ships as the mobile pass's first surface and foundation-risk check  ·  *2026-08-02*

Built `LoginPageMobile.jsx` + a real `useIsMobile()` matchMedia hook + a mechanically
extracted `useLogin.js` (desktop `LoginPage.jsx` untouched, byte-for-byte) as the first mobile
surface, chosen specifically because it has no nav-shell dependency and was the cleanest proof
of the shared-hook architecture decided above. Real PWA installability (manifest.json + 3
icon sizes) was wired into the app shell as part of the same pass, since it had to happen
somewhere and Login is the app's actual entry point. A dedicated review — independently
re-reading every changed file rather than trusting the build report — specifically hunted for
the one failure mode this exact pair of files (`NEXT_PAGE`/`LOGIN_PAGE` in
`moonglade_gallery.py`) has caused for real before (see "An unauthenticated React page needs
its OWN shell" above): confirmed the only additions to either shell are six static
`<link>`/`<meta>` tags, zero new `<script>` tags, and `/next/assets/` was already public
before this change — the failure mode does not reproduce here.
**A real live-verification false negative, caught before it was trusted:** the first
mobile-viewport check used the owner's real Chrome (per the established preference for
Moonglade UI verification) and its resize tool reported success, but the page's actual
`window.innerWidth` never changed — a screenshot at that "resized" state would have shown
ordinary desktop rendering and could easily have been misread as "the mobile breakpoint isn't
working." Caught by cross-checking the reported viewport dimensions against what was actually
requested before trusting the screenshot, then switching to the sandboxed preview browser
(safe for this specific check since the pre-auth login page has no real account data to
diverge on) to get a real 390×844 viewport and confirm via direct DOM inspection
(`document.querySelector('[class*="lgnm-"]')`) that the mobile component was genuinely
mounting, not just assumed from a screenshot.

**Why.** The false-negative near-miss is the reusable lesson: **a browser resize tool
reporting success is not proof the page's viewport actually changed** — check the real
reported dimensions (or query `window.innerWidth` directly) before trusting any screenshot
taken after a resize call, especially across different browser-automation surfaces (the real
Chrome extension and the sandboxed preview browser behaved differently here for reasons that
were never fully diagnosed). This is the same category of lesson as
[[feedback-visual-verification]] (getComputedStyle can lie, escalate to a real check) — one
level earlier in the pipeline: the viewport itself can silently fail to resize before any CSS
is even evaluated.

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

### LoginPage.jsx does not ship the sign-in⇄create toggle the DC shows  ·  *2026-08-02*

`Login.dc.html`'s account-creation design includes a real toggle ("First time? Create an account →" / "← Back to sign in") so both modes can be reviewed from one prototype. The shipped page has no such toggle: `boot.no_accounts` already decides server-side which mode could ever succeed for a given visitor (the React shell only reaches the zero-accounts state at all when `bootstrap_mode` — no accounts AND a local request — is genuinely true), so exactly one mode is ever meaningful per real visitor. A toggle link to the other, always-failing mode isn't a real control to offer.

**Why.** This is not a silent scope cut -- the DC's own note says the toggle is "gated server-side... shown here for review," i.e. the designer already knew real visibility had to be narrower than the prototype's convenience toggle. Recorded so a future pass doesn't "restore" the toggle thinking it was accidentally dropped: every other part of the create-mode design (framing copy, the proactive password checklist, per-field errors) shipped in full: only the cross-mode link, which the design's own text already flagged as demo-only, is missing.

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

Bundle themes as decided: **(default)** Void Sentinel mark, ships free/ungated. **(removed)** Gem Tome — delete from the mark roster. **Nightfallen** — Moonwell Eclipse mark + Nightfallen skin (currently free) + banner #100. **Verdant Grove** — Vine Crescent mark + Verdant Grove skin, no banner picked yet. **Ember Court** — Winged Crescent mark (art not remade yet) + Embercourt skin, no banner picked yet, blocked on art. **Moonlit Silver** — skin picked plus banner generation task `2030243024291694139`, no mark picked yet. Standalone: **banner #62 is the current live default**, already shipped and not tied to any achievement.

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

The canonical roster is the owner's off-repo backup copy of `achievements_roster_57.json` (the committed copy was removed and scrubbed from history 2026-07-27) — 57 achievements, each carrying roast (default/spicy), roast_nsfw and a rung, in buckets of 29 ladder / 9 milestone / 8 mastery / 11 feat. The Great Library is a BANNER reward, not a badge. There is room for ~3 more against a 60 ceiling.

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

### The bundle's unlock split: branding opens, achievement assets stay sealed  ·  *2026-07-27*

Contents and unlock model, decided in chat: ALL of the owner's branding goes into the container (a small owner audit of the base items is still owed before the list is final). Earning "Under the Hood" unlocks the full branding folder — the user-facing customization slots are **Icons/marks · Banners (main + login screen) · Mascots · Rewards** — but NOT badges, the Mystery Konami-code assets, or the tier frames: those stay sealed to the achievements that earn them. Likewise sealed: ANY file carrying achievement data or descriptions. This needs recoding — badges, Konami assets and frames are currently counted as part of "Branding" and must be split out so the branding unlock cannot reach them.

Ruled 2026-07-27, same conversation: **mascots — including the per-achievement animations — are Flair, open to branding customization; they are NOT part of the achievement itself.** The badges are, owner verbatim, "the sauce on achievements" — badges stay sealed.

**Why.** The branding unlock is the "make it yours" surface; the sealed set is earned surprises, and one achievement must not open another's reward. The mascot bucket was flagged as a boundary to pin and the owner ruled immediately: flair travels with branding, sauce stays with the achievement. The roster JSON is no longer a caveat here — it is out of the repo entirely, see [[The 57-roster JSON is gone: removed from the repo and scrubbed from history]].

### BANKED: a Starfall-class fanfare for the branding unlock  ·  *2026-07-27*

Earning "Under the Hood" gets a large fanfare in the same class as the Konami code's Starfall. Banked as a want; owner explicitly marked it unscoped.

**Why.** The bar is named now ("similar to konami code's starfall") so the moment doesn't get shipped small later — and marking it banked keeps it from being built before it is designed.

### BANKED: the public docs need a spoiler-hygiene pass  ·  *2026-07-27*

Owner, immediately after the roster scrub: make a note that the docs will need a hygiene pass. The raw roster file is gone from the repo and its history, but public docs still describe achievement internals — `docs/ART.md` carries the full badge list (ids, tiers, trigger conditions, art prompts), and `docs/ROADMAP_LOOM_ACHIEVEMENTS.md` and this tracker discuss designs like the Under-the-Hood breadcrumb and the Konami surprises. Unscoped: the pass's first question is what moves to git-ignored `private/`, what gets trimmed, and what stays as acceptable design notes. See [[The 57-roster JSON is gone: removed from the repo and scrubbed from history]] and [[The bundle's unlock split: branding opens, achievement assets stay sealed]].

**Why.** Recorded so the roster scrub is not mistaken for the end of the job — the data dump was the worst leak, not the only one. It also lands in the window the tracker already opened: [[Documentation debt deliberately deferred until after the naming pass]] — the naming pass has shipped, so doc work is unblocked.

### Marks come in three layers, and the selector moves on unlock  ·  *2026-07-27*

The included mark/icon set is the DEFAULT set — the launcher-icon picker keeps working out of the box, nothing users have today is taken away. Some included marks are gated by their own achievements (a mark can be an achievement's reward). The "Under the Hood" branding unlock adds ONE user-custom mark/icon on top of the included set, selectable in the Control Panel. And once full branding unlocks, the skin and mark selector MOVE into the unlocked branding panel — the branding tab becomes the customization hub. See [[The bundle's unlock split: branding opens, achievement assets stay sealed]].

**Why.** Owner's design, answering the "are the tab/launcher icons gated?" question with something better than a yes/no: the default experience stays whole, achievements keep gating their own marks, and the unlock's reward is additive — your own mark, plus the hub to manage all of it.

### Two manufactured statuses corrected: subject-left was never retired, and the gallery top was never locked  ·  *2026-07-28*

Owner, on reviewing the doc-action sweep: two of his design-pass answers were parsed into decisions he never made. (1) **Subject-left stands.** The banner composition rule — focal content in the left third, because the right side carries UI — was never retired by him. A doc pass declared it "retired by the code" off the no-banner mask, missing that every header control renders ON TOP of the art (`header > * { z-index: 1 }`). The rule covers the gallery banner AND the Loom slim banner — which is the surface his answer was actually about. ART.md's passage siding with the "retirement" against his 2026-07-04 reassertion is corrected as of today. Any O5 slim-banner composition advice that carried "subject-left should not be carried over" is void. (2) **The gallery top is NOT locked.** He did the placement himself in the component editor, but the LOCKED stamp was applied in parsing — owner verbatim: *"No where did I lock this — that was unilaterally decided for me."* The section heading above is corrected; a build starts only after he explicitly locks the design, consistent with his own D1 note ("want a review pass first").

**Why.** Standing rule going forward: **no session stamps LOCKED, settled, retired, or source-of-truth on the owner's behalf** — those statuses exist only when he says the words, and a quoted verbatim beats every paraphrase. And an owner design rule is never falsified by reading CSS — code shows mechanics, not intent.

### Boosters are PER-MODEL on PixAI, and our drawer offers all three on everything  ·  *measured live 2026-07-28*

Measured in PixAI's own generate panel, driving the owner's account: on **Tsubaki.2 (DiT.2)** the Add Booster menu offers ONLY **Quality Tag** and **To Video**, both crowned (members-only). **Face Fix and Enhance Details (HiRes) are not offered at all** on that model. On an **SDXL** model (owner's capture) Face Fix and Enhance Details ARE offered and un-crowned, with the same two crowned extras beneath. So booster availability is a per-model property, and the crowned pair is a membership gate on top of it.

Our Generate drawer renders Face Fix · Quality Tag · Enhance Details **unconditionally on every model** — there is no per-model gating anywhere. Two consequences, both real:

1. **We send booster params to models that do not take them.** On a DiT model our drawer will send `enableADetailer` (Face Fix) or the `upscale` family (Enhance Details). This is the SAME failure class as the closed V3.0 Lite video bug — `generateAudio` sent to a model that does not accept it came back as a bogus *"This image contains sensitive or NSFW content"*. Image side, still live. Suspect it behind any unexplained image refusals on DiT models.
2. **We invoke a members-only booster with no membership check.** Quality Tag sends PixAI's real gated parameter (`params["qualityTag"] = {"prefix": ...}`, moonglade_backup.py:5527-5529). Our own **Snippets** feature is NOT implicated — banked prompt text is just typing, and nobody gates a user writing `((masterpiece))` into their own prompt. The booster button is the one handing out a crowned feature.

**Why.** Owner spotted it from the screenshots ("something we added on our own replaces one of these functions and basically gives one of their members only options for free") and it verified live. Recorded before any fix so the two defects stay distinguishable: #1 is a correctness bug that can manufacture a fake content refusal, #2 is a product/ethics call that is the owner's alone.

### The owner's PixAI membership is LAPSED, deliberately, as a test bed  ·  *2026-07-28*

Owner: *"I let my membership lapse on purpose to test some of this."* PixAI reports the membership expired 2026-07-27. This makes the account the first non-privileged test bed in the project's history — every prior test ran from a paid tier, which is exactly why ungated members-only calls could never have been noticed. **`private/VIDEO_MODELS.md`'s "owner is tier-3 premium" is stale as of 2026-07-27.**

**Why.** Load-bearing for interpreting any refusal seen from here on: a call that used to succeed may now fail on membership rather than on shape. It also means the Quality Tag question is answerable by one real generation whenever the owner chooses to spend it.

### Achievements banked behind the booster fix  ·  *2026-07-28*

The Refiner's Touch / Full Toolbox / Enhance Adept retool (five refinement tasks at 1/3/5) is designed and banked, deliberately NOT built yet. Owner: *"Bank the achievements for the moment and lets fix this otherwise the achievement will still be a bit broken."* The chain's first task is Upscale/Hi-res, which is exactly the booster under repair — instrumenting it before the fix would count a broken control.

**Why.** The dependency is real, not caution: the achievement's detection hook reads the `upscale`/`enlarge` params, and those params are what the gating fix changes the conditions for. Also banked in the same breath: the shared model picker means a capability gate implemented once reaches the gallery and the Loom together — owner: *"fill two stones with one bird."*

---

### What Moonglade actually is: official key, INTERNAL endpoints  ·  *2026-07-28*

**Moonglade authenticates with an official long-lived PixAI API key and drives PixAI's own GraphQL API.** Official credential, internal endpoints, same host. One `Authorization: Bearer <PIXAI_API_KEY>` on every request (`load_token`/`_make_session`); no JWT in the live path. Generation, edit, video, listing and deletion all go to `api.pixai.art/graphql` via `createGenerationTask` — the `apollo-require-preflight` + `x-apollo-operation-name` headers we always send are Apollo CSRF headers and are the proof. Exactly FOUR official `/v2` REST endpoints are used: `/task/fixer`, `/kaisuuken/check`, `/task-price`, `/task/{id}`. **`/v2/image/create` is never called.**

**The 2026-06-22 switch was AUTH-ONLY.** Commits "Support official API key as preferred auth" → "Auth: API key is the only required credential" swapped the expiring browser JWT for the long-lived key and moved no endpoint. It was never framed as partial, so the owner reasonably believed the whole stack had migrated to an official API. It had not.

**Why.** Recorded because the owner discovered the gap on 2026-07-28 and it cost real trust. It also REFRAMES a board item: F13 ("a browser JWT files a generation into the pixai.art account, a bare API key does not") is **the bill for the June 22 switch**, not a missing feature — "Mirror to PixAI" is a restoration of what that migration cost. See [[PixAI's official API v2 exists, is enrollment-gated, and cannot build this app]].

### PixAI's official API v2 exists, is enrollment-gated, and cannot build this app  ·  *2026-07-28*

Docs live at **`https://platform.pixai.art/en/docs`** — quick-start (enroll-in-api · first-api-call · limits), faq, `api-v2/image/createImage`, `api/task/getTask`, references/models, references/supported-resolutions, and a **webhook for async notification** (a supported alternative to our poll loop). `POST /v2/image/create` takes `modelVersionId, prompt, aspectRatio, mode, batchSize, seed` plus named `style` presets, and describes itself as "replacing the raw pixel dimensions and internal parameter names of v1" — which is precisely what our submit sends.

**Access is a separate product from an account API key**: enrollment is a business application to `api@withpixai.art` or a beta form. **Documented limits: 10 concurrent pending/running tasks; no enforced rate limit but do not poll faster than every 1.5s, with exponential backoff. NOT SUPPORTED: video generation, PixAI Reference Pro, PixAI Edit, PixAI Edit Lite.** Only three models are documented (Tsubaki.2, Haruka v2, Hoshino v2), by VERSION id, with per-model allowed samplingMethods.

**Why.** This is the documented reason the internal surface is not a shortcut but a necessity: the official API cannot do video, Edit Pro or Reference Pro, and its simplified parameters cannot express steps/CFG/sampler/LoRA weights/upscale/boosters. It also retires guesswork elsewhere — it is very likely the answer to F18 (whether an API key may submit a LoRA training) without burning one of the eight free trainings, and it corroborates the proven "Enhance never dispatches for an API-key client" finding. **Nothing auto-syncs** (no schema feed, GraphQL introspection off), so this docs site is the only authoritative changelog and must be re-read periodically rather than rediscovered by breakage. Owner's read: his key is the OLD standard and v2 is new, part of the generation engine rolling out with **Tsubaki.3** (announced in the generator's in-app news; `MMDIT26B_MODEL` = DiT.3 is already in their live filter enum, no Tsubaki.3 model published yet).

---

### API-key MANAGEMENT is membership-gated; existing keys keep working  ·  *2026-07-29*

Measured by the owner across his own lapse and renewal. While the membership was lapsed the API-key interface was **gone from the site**; on renewing, it **came back with his two-year keys intact**. So the gate is on *managing* keys — issuing, viewing, rotating — not on the keys themselves, which keep authenticating throughout.

**Why.** This is a different shape from what a whole session assumed, and it corrects two things at once. First, a lapsed member does not lose API access, so nothing in Moonglade breaks on a lapse for that reason — the failures seen on 2026-07-28 were per-feature entitlement checks (Quality Tag, Edit Pro, Reference Pro, the LoRA cap), never the credential. Second, it explains how the owner holds long-lived keys at all: they were issued while a member, and their two-year lifetime outlives the membership that produced them. Practical consequence worth remembering: **do not let a key expire while lapsed** — the key would keep working to its expiry, but there would be no interface to issue a replacement without renewing first. Related: [[PixAI's official API v2 exists, is enrollment-gated, and cannot build this app]] — the enrollment programme is a separate product on top of this, and this finding does not change that.

---

### Gallery-top: what is built, what is not, and the measurements that matter  ·  *2026-07-29*

`gallery-top` is GREEN at `574b3bb` and contains: the Loom Render rename, the booster
capability gate, the booster rebuilt as a plain chip with PixAI's captured values, the
membership check and the LoRA-cap fix, the login-mascot ladder, the header restructure
(vertical destination rail, top-right cluster, two zones), the filter-bar deletion with its
three-way redistribution, and the bulk-bar deletion. The owner tested and confirmed the
first four.

**The strip layout is NOT finished, and here is the measured reason.** Read on the running
page rather than inferred:

* The two `.gt-row`s were **nested**, not siblings — row 1 at x=20, row 2 at x=666, when
  `flex-direction:column` would put both at x=20. That is why everything crammed onto one
  line.
* The search field was **flex-shrunk from 376px to 126px**. Flex items shrink by default;
  `width:376px` never held. `flex:0 0 376px` fixes it.
* At a 1244px window the rows need **827px and 943px** against **819px available**. The
  owner's stage is 1534px, which leaves ~1150px once the brand takes its ~370px. So the
  layout is right and simply does not fit a narrow window.
* **Un-nesting the rows breaks five Playwright render tests**, and this is the trap: two
  un-nested rows need ~79px inside a 72px strip, the header grows, and every flyout below it
  shifts — the model-picker and art-filter viewport assertions then fail. Clipping the strip
  and neutralising its pointer-events was not sufficient. The strip almost certainly needs to
  be a GRID with the brand spanning both rows (his export has the brand at x8 spanning
  y320-362 while row 1 starts at x386 — flex rows cannot express that), plus a real
  responsive rule for windows under ~1320px.
* Separately real: an absolutely-positioned full-width strip **swallows clicks** over its
  empty regions. Playwright's message is literal — `<div class="gt-strip"> intercepts pointer
  events`. Any positioned band needs `pointer-events:none` with `auto` on its children.

**Why.** Three hours went into this surface with no way to see it, and the entire failure was
that. **Get a sandbox login BEFORE writing any CSS**: `python moonglade_backup.py
--add-web-user`, then serve the dev checkout against a throwaway `--out` directory on a spare
port, sign in once in the browser, and measure with `getBoundingClientRect` instead of
guessing. Ten minutes of that found all three bugs above with exact numbers after hours of
theorising. Also: the template lives in a Python string, so **the server must be restarted for
any change** — and a killed server can still serve a cached page, which produced identical
"nothing changed" measurements twice. Kill by command line and prove it responds before
trusting a screenshot.

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

## 2026-07-31 — React conversion: the feasibility map

Banked before the owner leaves the work machine, so the home-machine session can start straight
into implementation instead of re-deriving this. Gathered by a 5-way parallel audit of the real
codebase (route-by-route, component-by-component) — not inferred from doc prose. Every claim
below was independently verified against `master` and, where noted, the still-live `gallery-top`
branch (kept specifically because the conversion continues there — see the Standing Rule above).

**Where this stands overall: a meaningful fraction of the backend is already done or proven; the
real remaining work is concentrated in a few identifiable places, not spread evenly.** This is a
map for planning against, not a verdict that the conversion is trivial or that it's a slog —
neither framing survived contact with the actual code.

### Already a clean JSON API on `master` today — a React front end can drive these with zero backend work

Generate/Edit/Fix/Enhance (`/api/generate`, `/api/edit`, `/api/fix`, `/api/price`,
`/api/task-status`, `/api/presets`, `/api/suggest-prompt`, `/api/tag-suggest`); the Picker
(`/api/model-search`, `/api/model-version`, `/api/gallery-images`, `/api/upload`,
`/api/import-local`); Panel + maintenance jobs + scheduler (`/api/panel/*`, `/api/watch/status`,
`/api/jobs*`, `/api/server/*`); Achievements/Folio (`/api/achievements`, `/api/skin`,
`/api/ach-event`); Contests (`/api/contests`); My Art (`/api/your-art`, `/api/artwork-views`);
Branding/skins (`/api/branding*`, `/api/skin`); Trash (`/api/trash/*`); and the Loom's ENTIRE
data layer (`/api/loom/*` — get/set/list/delete/handoff/generate/export/import-bundle). 65 of 94
routes on `master` fall into this bucket. Users/admin mutation is also ready
(`/api/users/*`, `/api/setup/save-key`, `/api/account`) — only `/login`/`/logout` themselves are
HTML-only (see below).

### Genuinely NOT there yet on `master` — real work, not wiring

- **The single most load-bearing endpoint — a filtered/paginated/sorted page of the gallery
  grid — has no JSON equivalent on `master`.** `index()` (`/`) bakes it entirely into a Jinja
  render: facets (`unique_models`/`unique_batches`/`catalog_years`/`unique_collections`), stats,
  setup-wizard flags, CSRF token, active-filter chips, the works. The abandoned `gallery-top`
  branch's `/api/next/library` + `/api/next/detail/<id>` are a strong, mostly-complete
  **reference** for the shape (same filter surface as `query_catalog`, real prev/next nav) but
  are thin on chrome — facets/stats/session/CSRF currently only reach that pilot via an HTML-shell
  boot script (`window.MG_BOOT`), not real JSON endpoints. That boot-payload promotion
  (e.g. real `/api/facets`, `/api/session`, `/api/stats`) is itself real, unfinished work.
- **`/login` and `/logout` are HTML-only**, with first-run/bootstrap-account and lockout logic
  embedded in the render. A SPA needs real `POST /api/login` → JSON and a JSON logout before auth
  can be driven from React at all.
- **Several grid mutations are still redirect-based, not JSON**: delete, bulk delete, bulk
  prompt-replace, collection add/remove.
- **The classic gallery's own Image/Edit/Fix generation controller has no componentized
  equivalent anywhere** — one 1,289-line vanilla-JS IIFE (`Gen` in `moonglade_gallery.py`), the
  single largest un-ported block in the app. `<mg-generate-drawer>` only ever replaced its
  **Video** tab; Image/Edit/Fix would need a real from-scratch React build.
- **A dozen real surfaces got literal zero coverage from the last attempt**: Trash's own
  review UI, Users/admin, real branding/skin *editing* (the last attempt only ever consumed
  tokens/skins, never let you set a banner/mark/skin), plus ~700 more lines across smaller
  utility IIFEs (`ImportUI`, `CloudDel`, `Snips`, `Setup`, `Acct`, `Tags`, `YourArt`, `Similar`,
  `Ctx`) and ~1,500 lines of un-namespaced glue code (lightbox keyboard nav, the print page,
  service-worker registration) tied to specific DOM ids baked into the Python template — none of
  it lifts out mechanically.

### The shared component layer — proven, not hypothetical

`static/mg-*.js` are real custom elements (light DOM, no shadow root). Four of five have **cited,
working `ref={...}` mounts in the Loom's own shipped React source
(`loom/master-storyboard.jsx`)** today: `mg-model-picker`, `mg-gallery-picker`,
`mg-generate-drawer` (video only), `mg-cost-badge`. `mg-upscale-panel` is architecturally
identical (same conventions) but has zero React-mount evidence yet — treat as "should work,
confirm before relying on it." `mg-notify.js` and `picker-core.js` aren't elements at all — they
port for free as imperative globals/pure logic, no JSX involvement needed.
`DESIGN_TOKENS_CSS` (`moonglade_gallery.py:3188-3246`) is plain CSS custom properties, zero
framework coupling, trivial to import into any React app; skin switching is one
`setAttribute('data-skin', …)` call.

### Auth/CSRF — the hard questions were already asked and answered once; the code just isn't on `master`

Session-cookie auth needs nothing special from React (`fetch()` rides it same-origin). The
`_enforce_front_door()` / `ROUTE_TIERS` contract is self-enforcing
(`tests/test_route_tiers.py`) and a new route just needs declaring into it. **Most spend/mutate
JSON routes (`/api/generate`, `/api/edit`, `/api/fix`, `/api/loom/generate`, `/api/import-local`,
`/api/delete`) are deliberately CSRF-token-exempt**, protected by `SameSite=Lax` + the session
gate instead — a React caller needs no CSRF token for these, only for the small explicit-token
class (login, logout-revoke, password change, add/remove user, DELETE-forever). Any boot-data
injected into an SPA shell MUST use Jinja's `|tojson`, never `json.dumps(...)|safe` — the latter
doesn't escape `</script>` and is a real, previously-shipped XSS hole into the CSRF-exempt
`/api/generate`. **None of this is theoretical** — `gallery-top`'s Mix pilot proved the whole
pattern end to end with real `fetch()` calls against real auth, including finding and fixing the
XSS hole above and a per-port `SESSION_COOKIE_NAME` collision bug (two Moonglade instances on
different ports silently logged each other out). That specific code died with the branch, but
the design questions it answered did not need to be re-asked.

### Calibration: the real bugs the last attempt actually hit (read before assuming "just wiring" is quick)

Not a reason for doom, but real evidence of where friction shows up even when the direction and
plan are exactly right: an XSS hole (above); a boolean-coercion bug on `/api/generate`'s
`prompt_helper` flag (`str(False) == "False"` never matched the lowercase falsy tuple — every
explicitly-disabled prompt helper submitted as enabled, on the classic drawer too); a real race
in the Fix tab (clicking the instant a quote was still in flight); a stale-rating bug (Details
view read its own fetched copy instead of the shared rate() update); several z-index/paint bugs,
including one where `getComputedStyle` reported a demonstrably-painted button as
`visibility:hidden` — only an actual screenshot caught the real bug; the `created_at` timezone
data-correctness bug (banked as its own entry above); and **seven distinct defects in the
Generate-drawer port caught only by a dedicated adversarial review pass before shipping** —
`<mg-model-picker>`'s multi-select emitting `{model, selected}` not a raw row (the whole LoRA
path silently read `undefined`), `Jobs.track`'s callback shape being `cb(phase, data)` not an
object (completions would have hung on "Queued" forever), `trigger_words` being a
comma-separated string not an array (`.join()` would have crashed on the first hit), LoRA weight
bounds keying off the LoRA's own architecture instead of the base model's (a −0.8 SDXL weight
could ride a DiT submit that only accepts 0–1.2), and three more in the same vein. **Budget a
real adversarial-review pass before calling any ported surface done — this class of bug is not
hypothetical, it is what actually happened.**

### Open, unscoped, and not yet asked of the owner: does the Loom become part of the same app?

Neither `master`'s nor `gallery-top`'s `DECISIONS.md` states whether the Loom and the new React
gallery become one unified application. The only relevant entry (`gallery-top`, "gallery UI
moves to React, the Loom's way") describes them being *built the same way*, phased, with Flask
staying one shared backend — not merging into one bundle. The code as shipped already diverged
from even that: the Loom loads React via vendored UMD globals + Babel-standalone (or a stripped
esbuild bundle that deliberately does NOT bundle React), while the Mix pilot used real npm
`react`/`react-dom` through Vite's ESM graph — two incompatible React-loading strategies that
have never coexisted in one bundle. The pilot only ever linked to `/loom` as a full-page
navigation, never embedded it. Merging them would mean rewriting the Loom's delivery mechanism
(dropping vendor-globals/Babel-standalone for real npm React, decomposing its single 4,178-line
root component into something embeddable) — genuinely large, not a wiring task. **Ask the owner
directly whether this is in scope before assuming either answer.**

### Next step, concretely

The map above is the terrain, built from what already exists in this repo. It is not a
substitute for looking at Claude Design's actual output. The next concrete action for whoever
picks this up: get the real handoff (export, or a DesignSync pull into the repo) and read it
against this map — which surfaces it covers, whether it's wired to real data or sample data, and
whether it already assumes the `mg-*` component contracts above — before writing implementation
code.

---

## 2026-07-29 — The design kit exists: generated token pages + a Claude Design project (`design-kit` branch)

**Shipped on `design-kit`** (owner tests before any merge). The STANDARDS.md Claude Design
row's candidate ("push `DESIGN_TOKENS_CSS` + the `mg-*` web components + the toast") is no
longer a candidate:

* **Every kit page's inline token copy is now GENERATED.** `tools/export_design_kit.py`
  rewrites `static/design-tokens.css` and the `mg-tokens:begin/end` block in every kit page
  from `moonglade_gallery.DESIGN_TOKENS_CSS`; `tests/test_design_kit_sync.py` fails the suite
  when any copy is stale, naming the repair command. The old hand-typed slices had already
  drifted (`--mantle #131024` vs the real `#0a0818`) — that drift is the whole justification.
* **Two foundation pages** — `static/design-tokens.html` (palette + type) and
  `static/design-skins.html` (all five skins side-by-side) — both self-derive from the
  stamped stylesheet, so neither holds a second list of anything.
* **The two missing harnesses exist** (`mg-upscale-panel.html`, `mg-notify.html`); the four
  existing harness pages gained a first-line `@dsCard` marker and `./` relative script srcs
  (identical when served from `/static/`; now they also work file-opened and bundled).
* **claude.ai/design project "Moonglade Athenaeum"** (id
  `b43ffcd7-3a93-428f-afe8-3e20ca29e8e8`) carries the whole kit under `kit/` — 8 card pages,
  7 component JS files, `design-tokens.css` — pushed via DesignSync from this branch's
  `static/`. That project is a legitimate PIXEL source of truth for visual builds per the
  checkpoint protocol, and future syncs go through the same finalize_plan → write_files flow,
  incrementally, never as a wholesale replace.
* **Merge note for `gallery-top`:** it adds `--loomc` (and banner tokens) to
  `DESIGN_TOKENS_CSS`. After any merge that touches the constant, run
  `python tools/export_design_kit.py` and commit what it refreshes — the drift test holds the
  suite red until that happens, on purpose. Re-push the refreshed kit to the Claude Design
  project in the same pass so the two stay one thing.

**Why.** One constant was already the app's single source of tokens; the kit extends that
discipline to every standalone surface that had quietly stopped inheriting it, and the Claude
Design project turns the same files into a design surface for composing new screens with the
REAL components, not lookalikes. Verified before push against a fresh static server on a
fresh port: 24 token chips match the constant, skin swaps repaint live, the upscale demo's
ratio cap moves 1.9 → 2.0 between its two demo rows, zero uncaught console errors, full
suite green (1436 passed; render tests deselected as designed).

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

## 2026-08-02 — Duplicate Review shipped: real matching, real quarantine, one adversarial-review fix

Built via a 9-agent Workflow (sequential build stages, then a 4-way parallel adversarial
review), per the scoping decisions in this doc's earlier entry of the same date. Full detail
in `CHANGELOG.md`'s `[Unreleased]` entry.

**What shipped, exactly as scoped:** four real matching tiers (same-media, identical-file,
same-seed, near-duplicate via a new hand-rolled dHash — no CLIP-similarity tier, per the
earlier exclusion), and a real quarantine-only Resolve/Undo pair the owner explicitly asked
for over the read-only default. No scope crept beyond what was decided.

**The adversarial review earned its place.** Three of four independent reviewers (READ_ONLY
gating, quarantine-never-hard-delete, CSRF/tier correctness) verified clean with zero
findings. The fourth — specifically reviewing the frontend's click-guard and Undo
correctness — found a real, shippable-as-a-bug issue: a partial Undo failure (a multi-file
group where some files restore and others don't) left the card permanently misreporting
which files were actually still quarantined, blocked any clean retry, and silently dropped
the grid refresh for the files that DID come back. This is exactly the class of bug this
project's checkpoint protocol keeps a dedicated review step around for — it would not have
been caught by the passing test suite (which tests full-success and full-failure undo, not
a mixed result) or by a first-pass live click-through (partial-failure needs an induced
failure to ever trigger). Fixed same-session: undo now tracks per-file outcome, a tile shows
a real `RESTORED` state (distinct from `KEPT`/`QUARANTINED`) instead of lying, a retry only
touches files that still need it, and `onResolved` fires on any real restore. Full suite
re-run green (1539/1539) after the fix, then the actual Resolve→Undo round trip was run live
against the owner's real library (not a fixture) — real files moved and moved back, counters
returned to their exact pre-resolve values, zero residue in `_duplicates/` confirmed on disk.

**One finding deliberately NOT fixed this pass:** the same reviewer flagged a low-severity,
non-data-destroying race — two concurrent Undo calls for the same multi-copy media_id can
interleave on an unlocked read-scan-write catalog reconcile. Real, but requires two
same-media-id undo requests landing within the same request window, and per the reviewer's
own trace both files still genuinely move back correctly (the row just lands on a
nondeterministic one of the two). Tracked rather than patched here — a proper fix wants a
per-media_id lock (this codebase already has the `_accounts_lock` pattern for the same class
of TOCTOU problem — see the concurrent-account-removal fix elsewhere in this doc) plus a
dedicated concurrency test, not a rushed one-line change to a destructive-path route.

**Why record this separately from the scoping entry.** The scoping entry captures what the
owner decided to build; this one captures what actually shipped and what the safety review
process caught — future sessions touching `/api/duplicates*` or `DuplicateReviewOverlay.jsx`
should read both, and should know the concurrent-undo race is a live, named, tracked gap,
not an oversight to rediscover from scratch.

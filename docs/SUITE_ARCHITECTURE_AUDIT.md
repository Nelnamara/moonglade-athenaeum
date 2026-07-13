# Suite Architecture & Cohesion Audit — Moonglade Athenaeum

> **Produced 2026-07-13** by a 5-agent parallel audit (one auditor per surface + synthesis), then
> spot-verified. The highest-severity finding (§7 — the non-atomic single-file `store.json` write at
> `pixai_gallery.py:9137-9139`, with the repo's own atomic tmp+`os.replace` idiom at line 1620 sitting
> unused) was confirmed against the code. Line anchors elsewhere are auditor-reported; the
> `REFINEMENTS.md:72` "no framework" note is unconfirmed and is raised as an open question, not a rule.

## 1. Executive summary

The suite is already unified where it matters most: a single Flask process (`create_app`), one generation engine (`pixai_gallery_backup.py`), one SQLite catalog (`catalog.db`), one JSON API surface, one localhost spend-gate, and one `DESIGN_TOKENS_CSS` palette feed both UI natures. The real seam is entirely **front-end widget-render code**: a handful of cohesion-critical widgets (model/LoRA picker, generate drawer, cost/free-card chip, hover preview card, cards) are hand-authored twice — once as vanilla JS in the gallery's Python string templates, once as React in the Loom's JSX — even though they call identical endpoints and read identical tokens. `static/picker-core.js` already proves that framework-neutral sharing works in this codebase with no build step. **Recommendation in one line: promote those duplicated widgets to framework-neutral Web Components loaded exactly like `picker-core.js` (plain `<script src>`, gallery-owned), mounted by both surfaces — starting with the model picker as a pilot — while keeping each surface's nature exactly as designed.**

## 2. Surface inventory

| Surface | Stack | Entry points | Key widgets |
|---|---|---|---|
| **Flask Gallery (the hub)** | Server-rendered Jinja/Python raw-string templates (`BASE_HTML` ~2850, `INDEX_HTML` 3348) + vanilla ES5-style IIFE islands; no framework, no build step | Flask route rendering `INDEX_HTML` ~7780; `DESIGN_TOKENS_CSS` 2386; `static/picker-core.js` at :4999 | Model/LoRA picker flyout + `#model-preview`; LoRA chips; Generate drawer (Gen/Edit/Video); Gallery Picker; Lightbox; Card grid |
| **The Loom** | React 18 UMD global + in-browser Babel; `loom/master-storyboard.jsx` (1,985 lines, one `<App/>`) string-injected into `LOOM_PAGE` (2451, `__JSX__` at 2478) | `GET /loom` (localhost-gated 9158); `/loom/vendor/<f>`; `/api/loom/*`; `ReactDOM.createRoot` at 2479 | App (God-component); ProjectSwitcher; CardView/CardEditor/FrameSlot; ShotPreview; SequencePlayer; GalleryPick; LoomV2 dockable workspace; reel/timeline |
| **PySide6 desktop GUI** | Vanilla imperative PySide6 QWidgets; ~155-line `DARK_QSS` (Catppuccin Mocha); imports engine + Flask app in-process | `pixai_gui.py` main() :2563; `Moonglade Athenaeum.pyw`; settings in `pixai_gui_settings.json` | Download/Organize/Convert; Generate/Video/Ref-Video/Edit; Utilities ("Library"); GalleryTab (re-hosts the web app) |
| **Backend / shared foundation** | Python Flask app-factory + engine module + SQLite; GraphQL/oRPC to PixAI | `create_app(out_dir)` 2540; 70+ routes 7474–9534; engine imported as `core` | Generation engine (`submit_generation`/`generation_status`/`collect_generation`/`_apply_kaisuuken`); catalog helpers; tokens; `picker-core.js`; `_is_local_request` spend-gate |

## 3. What's already shared (credit given)

This is the strong part of the architecture — the migration should touch none of it.

- **Generation engine.** Every gen path on both surfaces rides the same `createGenerationTask` family in `pixai_gallery_backup.py` — `gql_adhoc` (983), `build_shot_video_params` (3073), `upload_media` (3286), `submit_generation` (3714), `generation_status` (3755), `collect_generation` (3766), `_apply_kaisuuken` free-card auto-apply (4870). Gallery `/api/generate|edit|enhance|fix` and Loom `/api/loom/generate` both delegate via `core.`.
- **Single SQLite catalog.** All catalog I/O funnels through `pixai_gallery.py` helpers (`CATALOG_FIELDS`, `init_db`, `save_catalog`, `query_catalog`, `find_files_for_media_id`); the engine imports them *from* the server (reverse dependency at `pixai_gallery_backup.py:53-55`), so CLI, gallery, and Loom cannot drift on schema.
- **Shared JSON API.** `/api/gallery-images`, `/api/collections`, `/api/price`, `/api/task-status`, `/api/account`, `/api/upload`, `/api/model-search` are each called by both the gallery and the Loom.
- **Design tokens + skins.** One `DESIGN_TOKENS_CSS` palette (line 2386) is injected into both `BASE_HTML` and `LOOM_PAGE` via the `__DESIGN_TOKENS__` marker; skin choice is shared cross-surface via `localStorage 'skin'` + `data-skin` pre-paint, so re-skinning the gallery header re-colors the Loom with no FOUC.
- **`picker-core.js` — the working precedent.** A framework-neutral, no-DOM/no-JSX browse+paginate core loaded via plain `<script src>` by both surfaces (gallery :4999 / :5465, Loom :2465 / jsx:1674). This is the existing proof that the proposed pattern already works here.
- **One process, one spend-gate.** `create_app` factory + `_is_local_request` enforce the same LAN-read / owner-spend policy everywhere.

The backend auditor's verdict is blunt and worth repeating: **zero backend-owned duplication.** The seam is front-end only.

## 4. The duplication map

Widgets that exist in more than one stack, with anchors:

- **Model/LoRA picker.** Gallery: rich flyout with hover preview, LoRA chips, category chips, Popular/Newest sort — markup `pixai_gallery.py` 4513–4538, JS `Gen.render` 5850 / `showPreview` 5881 / `toggleFlyout` 5792 / `setKind` 5805 (~5805–5870). Loom: a stripped search-box + flat list over the **same** `/api/model-search`, emitting `setImgModel` — `master-storyboard.jsx:681-708` (and V2 682–692). Same endpoint, two divergent UIs; the Loom's is the inferior reimplementation. **This is the flagged, highest-value duplication.**
- **Cards.** Authored twice within the gallery alone: server-side Jinja `.card` (3617–3648) and a hand-maintained client-side `innerHTML` clone inside `Similar.open` (6555–6564) — they can silently drift on badges/data-attrs.
- **Picker chrome.** Logic is correctly shared via `PickerCore`, but rendering is still duplicated: gallery builds `.pick-cell` divs (`Picker` 5472), Loom builds `.sb-pick-cell` JSX (`GalleryPick` 1660) — two renderers over one core.
- **Reel / timeline — duplicated *inside* the Loom.** Classic `.sb-reel` (jsx:1343) vs V2 `.lv-reel` (jsx:637); segment/status-color logic written twice.
- **Cost + free-card preview.** Loom's `priceShot` + confirm dialogs (1084–1101, 1266–1274) mirror the gallery drawer's live cost/card check over `/api/price`.
- **Generate/poll engine (client-side).** Loom re-implements submit→poll→route (1091–1207) against the same endpoints the gallery drawer's `runTask` (`pixai_gallery.py:6439`) drives.
- **Hover preview element.** `#model-preview` is already a de-facto shared widget *trapped inside* the Gen IIFE — one node reused for both model cards (`showPreview` 5881) and reference thumbnails (`showRefPreview` 5912).
- **Cross-boundary data tables.** `EDIT_CAPS` (6129) mirrors server `core.EDIT_MODELS` caps — a table duplicated across the Python/JS boundary.
- **PySide6 GUI** duplicates the entire Generate/Video/Edit surface and the Control-Panel job surface, but as *strictly worse* clones (no live cost, no free-card check) — see §8.

## 5. Options for the front-end seam

### Option A — Web-component-ize the shared widgets (the lead)

Extract the cohesion-critical widgets as framework-neutral custom elements, styled purely with the existing `DESIGN_TOKENS_CSS` vars, loaded as plain global scripts like the vendored React files (not ESM). The gallery owns them (hub); its vanilla islands and the Loom's JSX both mount the same element. Pass rich data via **properties**, receive results via **CustomEvents** (so Loom's `setImgModel` becomes an event listener).

- **Pros:** Fits the no-build constraint that both surfaces already live under; `picker-core.js` proves the pattern works here. Kills the worst duplication and *upgrades the Loom to the gallery's rich flyout for free*. Keeps both surfaces' natures intact (owner's stated goal). Zero backend blast radius — same `/api/*`, same tokens. Cheap-to-rearrange: each widget can be extracted and adopted independently.
- **Cons / effort:** Must break the gallery's singleton-DOM-id assumption (esp. the single `#model-preview` reused for two purposes) and the pervasive inline `onclick="Gen.foo()"` wiring. React↔custom-element needs the standard `ref`/`addEventListener` bridge (React synthetic events don't auto-bind to custom-element events; VDOM re-renders can fight an element that owns its own subtree). Must drop into **both** the classic `sb-*` and V2 `lv-*` Loom trees or divergence continues. No JS test coverage, so each extraction is verified by manual browser exercise. Components must consume gallery tokens (`--accent`/`--surface0`) directly, not the Loom's private aliases (`--amber`/`--panel`). **Effort: medium, incremental** — one widget at a time.

### Option B — Rewrite the Loom into vanilla

Fold the Loom into the gallery's IIFE/innerHTML model to eliminate the framework split at the source.

- **Pros:** One stack; no cross-framework bridge; no web-component-per-tree concern.
- **Cons / effort:** **Contradicts the owner's explicit design intent** — the Loom is a stateful reactive editor (immutable spreads, submit→poll→route state machines, debounced persistence, dockable V2 layout) that manual imperative DOM would fight. Throws away working code and re-introduces the maintenance burden the gallery's own auditor flags (stringly-typed `innerHTML`, scattered closure state, manual `seq` guards). **Effort: high, high-risk. Not recommended.**

### Option C — Status quo + matched copies

Keep two implementations; add discipline (shared checklists, mirrored PRs) so the duplicated widgets stay visually and behaviorally in sync.

- **Pros:** Zero migration cost today; no bridge risk; honors cheap-to-rearrange by deferring.
- **Cons / effort:** The drift is structural, not incidental — only CSS tokens are shared, not markup/behavior, so the model picker, preview card, cost chip, and cards will keep diverging (the Loom's picker is *already* the inferior copy). Every future change lands twice. **Effort: low now, compounding forever.**

## 6. Recommendation & migration order

Adopt **Option A**, incrementally, gallery-owned, no build step. Migrate in value order so each step ships independently and can be halted without stranding work:

1. **Pilot: `<mg-model-picker>`** — the model/LoRA picker flyout + its hover preview card. Highest-value, most-divergent widget; the Loom's "Generate shot" visibly needs it, and adopting it upgrades the Loom for free. This pilot also exercises the two hard problems once (singleton-`#model-preview` reuse, React property/event bridge) so later widgets inherit the pattern.
2. **`<mg-gallery-picker>`** — formalize the already-shared `PickerCore` into a full element, folding the duplicated `.pick-cell` / `.sb-pick-cell` chrome into one.
3. **`<mg-cost-badge>`** (live cost + free-card/kaisuuken chip) — small, safety-relevant, removes the mirrored `priceShot`/`/api/price` copies.
4. **LoRA chip strip** — weight/compat/trigger-word logic out of the Gen IIFE.
5. **`<mg-card>`** — unify the Jinja card and the `Similar.open` JS clone behind one element.
6. **Lightbox** — last, most entangled with cross-global bridges (`Gen.openEdit`, `Gen.addVideoRefs`).

Keep `DESIGN_TOKENS_CSS` as the single style layer — components read the shared CSS vars and must **not** ship their own palette. Do **not** make the gallery reactive or move it into React; the server-rendered card grid + IIFE model is deliberate and fine.

## 7. The Loom project save/load

**Current mechanism.** `window.storage` is swapped from browser localStorage onto `/api/loom/get|set|list|delete` (`LOOM_PAGE:2469-2474`), backed by a single `store.json`. A `useEffect` on `[project, activeId]` debounces 600ms then writes the whole project (`sSet(PPRE+activeId, …)`, jsx:980–985). The server writer `_loom_save` is a bare `write_text` (`pixai_gallery.py:9137-9139`).

**Why it feels volatile (the owner's real pain point).** `store.json` holds **all** projects **plus** all inline base64 thumbnails in one file, rewritten **non-atomically** on every debounced edit. A crash mid-write can corrupt *every* storyboard at once — the auditor rates this the highest-severity current defect. Import also **overwrites the open project** rather than creating a new one, so a pull-in can clobber in-progress work. The single fat file is what makes save/load feel clunky and unsafe.

**Recommended model** (orthogonal to the web-component migration — do it regardless):

- **File-per-project.** Write each board to `out_dir/loom/projects/<id>.json` with a light index file; a corrupt or mid-write single project can never take down the others.
- **Atomic writes.** Write to a temp file + `os.replace()` so a crash mid-write leaves the previous good version intact.
- **Thumbnails out of the document.** Push local-upload thumbnails through the existing `upload_media → media_id` / catalog path so the project JSON carries `media_id` references, not inline base64 — shrinking the hot-path write dramatically.
- **Import creates a new named project** instead of overwriting the open one.
- **One-time migration + interchange.** Import existing `store.json` boards once, and preserve the `.json` Backup/Restore path as the machine-to-machine interchange (`store.json` is correctly git-ignored + machine-local per the cross-machine workflow).

## 8. Open questions for the owner

- **The "no framework / flat CSS" doc note (`REFINEMENTS.md:72`).** You don't recognize this line, so treat it as an **open question, not a constraint**: is framework-neutralism a real project value to honor, or a stale doc artifact? The auditors read the *no-build-step* value as firmly real (stated in `picker-core.js`'s header and enforced by the Loom's in-browser Babel paint), and the Web Component plan honors that regardless — but this note should be confirmed or struck so it doesn't get cited as a rule later.
- **The PySide6 GUI's role and fate.** The desktop GUI reimplements **zero** business logic — every tab is a thin arg-builder over the same engine (`core.run_download`, `run_generate`, …), and its Gallery tab literally re-hosts the same `create_app` the web suite serves. But it has drifted (last touched 2026-07-04 vs. daily commits on the server; title still shows `1.10.0`), lacks every post-1.10 capability (no Loom, no cost/free-card safety on its spend tabs), and **cannot** consume the shared web-component layer — there is no `QWebEngineView` anywhere. Options: (a) **trim** it to the offline-only bricks (Download/Organize/Convert/Library + one-click gallery launch) and drop the strictly-worse Generate/Video/Edit clones; or (b) **deprecate wholesale** in favor of `Serve Gallery.pyw` + the browser. Either way it should be **excluded** from the cohesion migration. Decision needed — and note that deprecating requires repointing the flagship `Moonglade Athenaeum.pyw` launcher first.
- **Where do capability caps live?** `EDIT_CAPS` / model-type enums are duplicated across the Python/JS boundary. A shared component must decide: caps served from `/api`, or a single shared constant — to avoid creating a *third* copy.
- **Shadow DOM vs light DOM** for the custom elements? (Affects token piercing and skin propagation — see §9.)

## 9. Honest risks & costs of the recommended path

- **No-build discipline is non-negotiable.** Shared components must be authored as plain ES that runs untranspiled as a global, served from `/static` or `/loom/vendor`. Anything needing JSX/a bundler breaks the Loom's zero-network paint model. This is the same discipline `picker-core.js` already follows — a known, met bar, but a real one.
- **Breaking the singleton-id assumption.** The gallery welds widgets to hard-coded ids (`gen-grid`, `model-flyout`, `model-preview`) and inline `onclick` handlers throughout `BASE_HTML`. Naive extraction can break the `#model-preview` dual-reuse or the inline wiring. The pilot must solve this cleanly once.
- **React ↔ custom-element bridge.** Attributes are strings, so objects pass via properties and results return via CustomEvents; React's synthetic events need a `ref`/`addEventListener` bridge, and VDOM re-renders can desync an element that owns its subtree. A front-end integration cost, paid per mount point.
- **Two Loom trees.** The V2 dockable layout re-implements every widget in `lv-*` CSS. A shared component must drop into **both** classic and V2 or the divergence simply continues in one of them — doubling the adoption surface inside the Loom.
- **Token aliasing drift.** The Loom aliases gallery tokens into private names (`--amber = var(--accent)`, etc., jsx:10–25). A shared component must reach for the gallery tokens directly or it will look wrong when hosted in the gallery. If shadow DOM is used, verify `:root`-scoped skin rules and `data-skin` propagation pierce the boundary (custom properties inherit through shadow boundaries — fine — but non-inherited/`:root` skin rules need checking).
- **No JS test safety net.** The 440+ pytest suite is Python-side; the JS blob has no coverage. Every extraction is verified only by manual browser exercise, so picker/flyout/lightbox regressions are easy to miss. Budget manual QA per widget.
- **Escaping/templating hazards on extraction.** The gallery JS lives in a Python raw string with `\u`-escaped unicode and interspersed Jinja `{% %}` (e.g. picker filters ~4550). Moving code to a `.js` file changes escaping/templating semantics and must preserve the Jinja-injected bits (collections dropdown).
- **Implicit cross-widget contracts.** Shared `seq`/`costSeq` counters and cross-global calls (`Gen.addVideoRefs`, `Gen.openEdit` from the lightbox) mean extraction must preserve those contracts or introduce an explicit event bus — added scope if the lightbox is migrated.

**Net:** the recommended path is medium-effort, incremental, and reversible at every step (cheap-to-rearrange honored). Its costs are concentrated in the pilot (id-singleton break + React bridge) and in manual QA; its backend blast radius is zero. The save/load fix is independent and should proceed on its own timeline regardless of the widget decision.

---

*File anchors reference `pixai_gallery.py` and `loom/master-storyboard.jsx` line numbers as reported by the per-surface auditors; the `REFINEMENTS.md:72` "no framework" note is unconfirmed and is raised as an open question, not a constraint.*
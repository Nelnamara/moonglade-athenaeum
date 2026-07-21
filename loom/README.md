# The Loom — source & build tooling

This folder holds the Loom's **source and its Node toolchain**. The Loom itself is not a
standalone page any more: it is a surface of the web app, served at **`/loom`** by
`pixai_gallery.py`, and its React source is **`master-storyboard.jsx`**.

**The user-facing manual is [`docs/LOOM.md`](../docs/LOOM.md)** — features, shortcuts, the
storyboard model. This file only covers what lives in `loom/`.

| Path | What it is |
|---|---|
| `master-storyboard.jsx` | The Loom's React source (the V2 shell). |
| `src/loom-core.js`, `src/loom-mutations.js` | Pure, framework-agnostic logic, `node --test`-able. |
| `test/` | The node test suite (`cd loom && npm test`). |
| `scripts/build.mjs` | esbuild bundler → `dist/master-storyboard.bundle.js`. |
| `dist/` | The pre-built bundle (committed). |

> **History:** this began as a standalone, double-clickable `Edit_Bay.html`, built from a
> `seedance-storyboard.jsx` by a `build_html.py` script, with its own `window.storage`
> shim over IndexedDB/localStorage. None of those files exist any more — the tool was
> absorbed into the app, which now owns persistence, uploads and generation. If you want
> that version, it is in the git history, not on disk.

---

## The Seedance continuity model (the reasoning baked into the board)

Kept because it is the *why* behind the board's shape, and it is model knowledge rather
than code knowledge — it doesn't rot with the app.

**`@reference` in plain terms.** An `@tag` names a file you upload, numbered in upload
order: first image = `@image1`, first video = `@video1`, first audio = `@audio1`. In the
prompt you state what each one is *for* (identity, opening frame, camera motion, the
beat). The model is a conditioning engine — text sets the scene, references anchor it.

**Three ways to keep clips flowing (mix all three):**
1. **Extend** — feed the previous clip in as `@video1`; the model anchors to its final
   frames and continues forward. Keep each extension ~5–10s for the cleanest result.
2. **First → Last frame** — give the shot a start image and an end image and prompt the
   *motion between them*, not the stills. Use "smooth, continuous, seamless, no hard cut,"
   and keep the two frames similar in composition/scale or the subject warps.
3. **Cast lock** — reuse the same reference for each recurring person/place and name what
   to preserve ("maintain exact appearance from @image1") every time it appears.

**The drift rule.** Consistency fades the further you chain. Re-anchor to your original
cast reference roughly every **4–5 shots**, and make each shot's closing frame the next
shot's opening frame. That chain is exactly what the board tracks.

Because the app owns the upload, it sends a shot's assets in a fixed order and remaps the
tags to match — so the old "confirm your tag numbers on the day" caveat no longer applies.

---

## Build tooling (Phase 1, 2026-07-16)

The rest of the repo has no Node/npm toolchain; this is the first one, scoped entirely
to `loom/` via `loom/package.json`.

- `loom/src/loom-core.js` — pure, framework-agnostic logic pulled out of
  `master-storyboard.jsx` (`flat`, `shotText`, `nextTag`/`maxTagNum`, `frameLinked`,
  `connectMeta`, `shotPayload`, `durOf`/`reelStats`, plus the `CONNECT` table and a
  couple of small constants/formatters they depend on). No React import, no DOM access
  — safe to `node --test` directly.
- `loom/test/loom-core.test.js` — unit tests for every exported function
  (`cd loom && npm test`, or `node --test`).
- `loom/scripts/build.mjs` — bundles `master-storyboard.jsx` (+ its `loom-core.js`
  import) into `loom/dist/master-storyboard.bundle.js` via esbuild
  (`cd loom && npm run build`; `npm install` once first).

**Two delivery paths, both live in `pixai_gallery.py`:**
- `/loom` (default) — unchanged in-browser Babel-standalone transpile. `loom()` inlines
  `loom-core.js` ahead of the JSX (stripping `export`, same trick already used for
  `export default function App()`) so it works without a build step, exactly as before.
- `/loom?bundle=1` (opt-in) — serves the pre-built `loom/dist/` bundle instead (no
  Babel, no client-side transpile). Falls back to the default page automatically if the
  bundle hasn't been built yet, so a fresh checkout never breaks.

The Babel-standalone path remains the trusted default; the bundle path is additive and
opt-in until it's proven out. **The bundle is committed and has no automated rebuild** —
if you change `master-storyboard.jsx`, run `npm run build` and commit `dist/`, or the
`?bundle=1` path serves stale code. (`tests/test_js_syntax.py` catches only the narrower
case where the bundle's React-hook preamble drifts from the source.)

---

*Built as a personal creative tool. Not affiliated with ByteDance/Seedance or PixAI.*

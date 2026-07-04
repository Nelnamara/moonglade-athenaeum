# The Edit Bay — Seedance 2.0 Storyboard / Shot-Blocking Tool

A reusable, single-file storyboard board for planning multi-clip AI-video pieces
(built around Seedance 2.0's prompting + `@reference` grammar, but model-agnostic —
PixAI and other generators that share the `@reference` convention work the same way).

It organizes a video as **Acts → Shots (cards)**, tracks the **frame handoff** between
consecutive clips so the piece stays fluid, and assembles paste-ready, continuity-aware
prompts.

Version: v2 · Last updated 2026-06-30

---

## Contents

| File | What it is | Use it for |
|------|------------|-----------|
| `Edit_Bay.html` | Self-contained, double-clickable build. React + Babel load from a CDN; runs in any modern browser. | **Just using the tool.** |
| `seedance-storyboard.jsx` | The React source component. | Dropping into a real React project, or future integration work. |
| `README.md` | This file. | Reference. |

---

## Quick start

### Desktop (easiest)
Double-click **`Edit_Bay.html`**. It opens in your default browser and runs — no Node,
no build step. The **first** open needs an internet connection (it fetches React from a
CDN); after that the browser caches it and it works offline.

To make it feel like an app: open in Chrome/Edge → menu → *Install page as app*
(or *Create shortcut → open in window*).

### iPad / mobile
iPadOS won't run a local `.html` as a live page. Serve it instead:
```
cd <folder containing Edit_Bay.html>
python -m http.server
```
Then on the iPad, open `http://<desktop-ip>:8000/Edit_Bay.html` in Safari →
Share → *Add to Home Screen*. Stays on your home network.

### As source
`seedance-storyboard.jsx` is a single default-exported `<App />` component. Tailwind is
**not** required — all styling is in an injected `<style>` block. It expects a
`window.storage` object with `get/set/list/delete` (see **Persistence** below).

---

## What it does

- **Acts & shots** — fully add / rename / reorder / delete. Reusable across projects.
- **The reel** — a runtime strip at the top; each clip is a segment scaled to its
  duration and colored by status, with a marker at the 8:00 target so you can see when
  you drift over budget.
- **Frame handoff** — every card has an **opening frame** and a **closing frame**
  (thumbnail + `@tag` + description). The *"↳ inherit [prev] close"* button copies the
  previous shot's closing frame into this shot's opening frame. A link indicator shows
  ✓ when the handoff is locked or ⚠ when there's an unintended gap.
- **Connection method** per shot — New scene / Cut (in edit) / First→Last / Extend prev —
  which drives how the prompt is assembled.
- **Cast & Assets** — define recurring people/places/audio once, each with a stable
  `@tag` and a **lock** toggle ("maintain exact appearance"). Tick which appear in a shot.
- **Camera / transition term palettes** — clickable vocabulary (shot sizes, moves,
  lens, transition types).
- **Copy shot** — assembles a continuity-aware, paste-ready prompt block.
- **Export shot list (.txt)** and **Backup / Restore (.json)**.

---

## The Seedance 2.0 continuity model (the reasoning baked into the tool)

**`@reference` in plain terms.** An `@tag` is a name for a file you upload, numbered in
upload order: first image = `@image1`, first video = `@video1`, first audio = `@audio1`.
In the prompt you state what each one is *for* (identity, opening frame, camera motion,
the beat). The model is a conditioning engine — text sets the scene, references anchor it.

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

> Note: tag *numbers* are whatever order you upload files in on the day. Treat the tags in
> the tool as your plan and confirm they match the upload order in the generator —
> unless/until the tool owns the upload itself (see integration notes).

---

## Persistence & data

The component reads/writes through a small async interface: `get(key)`, `set(key, val)`,
`list(prefix)`, `delete(key)` — all values are strings (JSON).

- **Inside a Claude artifact:** backed by the artifact's `window.storage`.
- **In `Edit_Bay.html`:** a built-in shim provides `window.storage` backed by
  **IndexedDB** for thumbnails (large capacity) with a **localStorage** fallback, and
  localStorage for the project JSON.

**Storage keys (namespaced):**
```
storyboard:v2:project        -> the whole board (JSON, no image data inline)
storyboard:v2:thumb:<id>     -> one resized JPEG data-URL per attached image
```

**Important:** storage is **per-device, per-browser**. Copies do not sync on their own.
Use **Backup (.json) / Restore** to move a project between machines or browsers — and as a
real safety net, since browser storage can be cleared (Safari may purge after ~a week of
not opening the page). Backup includes thumbnails.

---

## How `Edit_Bay.html` is generated from the source

For future-you, so the HTML build is reproducible. It's a mechanical transform of the
`.jsx`:
1. Strip the `import React …` line (React is a CDN UMD global instead).
2. Add `const { useState, useEffect, useRef, useCallback } = React;`
3. Change `export default function App()` → `function App()`.
4. Append `ReactDOM.createRoot(document.getElementById("root")).render(<App />);`
5. Wrap in an HTML page that loads React + ReactDOM + `@babel/standalone` from a CDN and
   runs the component inside a `<script type="text/babel" data-presets="react">` block.
6. Prepend the `window.storage` shim (IndexedDB + localStorage).

The original build script (`build_html.py`) does steps 1–6 automatically.

---

## Integration notes — Moonglade Athenaeum (PixAI)

The tool is structured to drop into a real app with generation:

- **Storage adapter swap.** Everything goes through `get/set/list/delete`. Re-point those
  four methods at the app's backend (and add a project/user prefix to the keys, which are
  already namespaced) — no rewrite.
- **Generate from a card.** "Copy shot" becomes a Generate button. Because the app owns
  the upload, it can upload a card's assets (cast + frames + refs) in a fixed order and
  remap `@image1`/`@video1` to match — so tags are *guaranteed* correct, eliminating the
  "confirm on the day" caveat.
- **Auto frame handoff.** Capture the rendered clip's final frame and write it into the
  next card's `openFrame`; the ✓ link then reflects real continuity, not just intent.
- **Generation state drives the card.** Status advances itself
  (todo → queued → rendering → done), the finished clip attaches, and the reel reflects
  real durations.

Component tree is already clean for this: `App → CardView → CardEditor → FrameSlot`.
The only standalone-isms are the global `window.storage` (make it a prop / adapter) and
the inline `<style>` (move to a stylesheet).

---

*Built as a personal creative tool. Not affiliated with ByteDance/Seedance or PixAI.*

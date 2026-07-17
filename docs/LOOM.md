# The Loom — full manual

The Loom is Moonglade Athenaeum's **video storyboard**: a shot-blocking board for
planning a multi-clip AI video, wired directly into PixAI's video engine so every card
can render itself. Open it from the gallery header (**▦ The Loom**) or at
`http://localhost:<port>/loom`.

It is deliberately **engine-agnostic**: the same board that generates on PixAI can hand
its prompts to any Seedance-style generator via **Copy shot**. Plan here, render anywhere.

---

## The mental model

```
Project
└── Acts            (chapters of your piece)
    └── Shot cards  (one generated clip each)
        ├── mode      I2V / R2V / V2V / FLF
        ├── connect   new / cut / flf / extend
        ├── duration  feeds the reel-bar runtime
        ├── open + close frames   (continuity chain)
        ├── shot text (the prompt, with @refs)
        └── camera / transition notes
Cast & Assets       (reusable @image1 / @video1 / @audio1 references)
```

The **reel bar** totals every card's duration against your target runtime (default 8:00)
so you always know how much piece you've planned.

## Shot modes

| Mode | What it does | Engine mapping |
|------|--------------|----------------|
| `I2V` | Animate a single image | i2vPro — the image is the first frame |
| `FLF` | Morph from a start frame to an end frame | i2vPro with `tailMediaId` |
| `R2V` | Multi-reference: cast + scene images | referenceVideo (`@image1…`) |
| `V2V` | Extend / transform an existing clip | referenceVideo with the clip as `@video1` |

There is no text-only mode: every shot needs an input frame or reference, and one with nothing
attached refuses with *"PixAI video needs a frame or a reference image/video for this shot"*.
(`T2V` was retired from the picker on 2026-07-06 for exactly that reason.)

## Cast & Assets

Reusable references live once and get cited everywhere. In shot text, refer to them as
**`@image1`, `@image2`, `@video1`, `@audio1`** — lowercase (PixAI normalizes case, but
lowercase is the canonical grammar). The **lock** checkbox on a cast row marks that member as the
consistency anchor across shots.

## Frame handoff (continuity)

Each card has an **open frame** and a **close frame**. Click **↳ inherit prev close** to
chain the previous shot's last frame into this shot's first — the ✓ / ⚠ link dots show
whether the chain is intact. This is how a sequence of independent 5–15s clips reads as
one continuous scene.

## ▶ Generate shot

The button on every card renders it for real:

1. Cast/frames referenced by the card upload in @-tag order (uploads are free).
2. The assembled shot text becomes the prompt; the mode picks the engine path.
3. The task runs async on PixAI — the card shows **wip → done** and plays the clip inline;
   **open full ↗** opens it in the gallery (`/image/<media_id>`) in a new tab.
4. The finished mp4 is downloaded and **cataloged into the gallery** like any other
   generation. **Free when a V4.0 video card covers it** (cards auto-apply); otherwise
   the credit price applies — same rules as everywhere else in the suite.

The Loom is **localhost-only** — the board *and* generation. Another device on your network can
browse the gallery, but the header's **▦ The Loom** button is hidden for it and `/loom` answers
*"The Loom is localhost-only."* (403) — it can't look, and it can't spend.

## Copy shot (the engine-agnostic path)

**Copy shot** assembles the same continuity-aware prompt (connect notes, camera, @refs)
and puts it on your clipboard for pasting into an external generator — e.g. a Seedance
2.0 interface, which uses the same @reference grammar.

Tip: in the gallery's image picker there's a **"Copy the image's prompt to the clipboard
when picking"** checkbox — useful for carrying source-image context into the Bay while
you cast shots.

## Saving, backup, export

- The board **autosaves to the gallery server** (one atomically-written file per key under
  `loom/kv/` in your backup folder) — it survives restarts and browser changes. A legacy
  `loom/store.json` is split into that layout on first touch and left behind as
  `store.json.migrated`.
- **Backup .json** exports the whole project; importing one restores it.
- **Export .txt** writes the full shot list as text — a script you can read, annotate,
  or hand to someone else.

## Two layouts: classic and V2

The Loom has two visual layouts over the exact same project data — nothing about switching
between them changes or risks your board.

**Classic** is the original layout described above: a vertical waterfall of acts and shot
cards, each expanding in place to edit.

**V2** (open via **⛛ V2 layout**, return via **← Back to classic Loom**) is a fixed
4-region shell: a **Cast & Assets / Footage** tabbed card on the left (with a Simple/Detailed
density toggle), the **Acts & Shots board** in the center (click a shot to select it — the
whole workspace binds to it), a **Generate drawer** on the right (Image/Edit/Reference/Video
tabs), and a fixed **Timeline drawer** across the top (hidden/slim/full, drag to resize;
pulling it to full shows the selected shot's trimmable preview above the scrubber, with a
play/pause button).

**Draft generation** — V2's Generate drawer also works with *no shot selected*: pick a mode,
write a prompt, generate, then either route the result into a shot (Image/Edit/Reference —
open frame / close frame / cast) or attach it (Video — pick a shot from a small "route into"
dropdown). This is for exploring a look before you've decided which shot it belongs to; the
main gallery's own Generate drawer behaves the same way for the same reason.

**V2 is not yet at full parity with classic** — **Export** (trim + stitch into one mp4),
**Generate all** (batch-render every unfinished shot), and **Copy shot** are only reachable
from classic Loom today; switch back for those. (**Play sequence** — play every finished shot
back-to-back — now has a **▶▶ Play** button in V2's top banner.) A few card fields (audio cue,
notes, the discreet/blur toggle, per-shot "other references") also don't have a home in V2 yet.
Everything else — shot editing, cast/assets, frame handoff, acts/shots management — works the
same in both.

## Workflow suggestions

1. Block the whole piece first (acts, shots, durations) until the reel bar hits target.
2. Cast your characters/scenes once in Cast & Assets; cite with @refs.
3. Chain frames (`↳ inherit prev close`) through each act for continuity.
4. Generate the anchor shots first (act openers, hero moments); review; then batch the rest.
5. Everything lands in the gallery — rate, collect, and curate clips like images.

## Relationship to the Generate drawer's Video tab

The drawer's **Video tab** is the *simple mode*: one shot, picked images, prompt,
duration, go. The Loom is the *production mode*: many shots with continuity,
cast, and a runtime target. They share the same engine underneath.

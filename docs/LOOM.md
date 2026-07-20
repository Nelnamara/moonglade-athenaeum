# The Loom — full manual

The Loom is Moonglade Athenaeum's **video storyboard**: a shot-blocking board for
planning a multi-clip AI video, wired directly into PixAI's video engine so every card
can render itself. Open it from the gallery header (**▰ The Loom**) or at
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

The **reel bar** (in the Timeline drawer) shows a colored segment per shot and a
target-position tick against your target runtime (default 8:00) — a quick-glance
pacing cue, not a numeric total.

## Shot modes

| Mode | What it does | Engine mapping |
|------|--------------|----------------|
| `I2V` | Animate a single image | i2vPro — the image is the first frame |
| `FLF` | Morph from a start frame to an end frame | i2vPro with `tailMediaId` |
| `R2V` | Multi-reference: cast + scene images | referenceVideo (`@image1…`) |
| `V2V` | Extend / transform an existing clip | referenceVideo with the clip as `@video1` |

There is no text-only mode: every shot needs an input frame or reference, and one with nothing
attached refuses with *"attach a frame or cast image first"*. (`T2V` was retired from the
picker on 2026-07-06 for exactly that reason.)

## Cast & Assets

Reusable references live once and get cited everywhere. In shot text, refer to them as
**`@image1`, `@image2`, `@video1`, `@audio1`** — lowercase (PixAI normalizes case, but
lowercase is the canonical grammar). The **lock** checkbox on a cast row marks that member as the
consistency anchor across shots. Two ways to add references beyond drawing them from a
generation result: **+ add from gallery** picks a single image/video from your catalog; **↖
Import collection** pulls a whole gallery collection in at once as reusable `@image` refs.

The left panel's second tab, **Footage**, is a separate browsable grid of every shot that's
actually finished rendering in *this* project — not a cast/reference list. Its own **⤓ Browse
library** button and a drag-and-drop zone both add media in as a *cast* reference (a picked
video becomes `@video`, a dropped image becomes `@image`) — Footage itself only ever shows
this project's own rendered clips.

## Project look

The Cast & Assets panel has a collapsible **🎨 Project look** textarea. Whatever you write
there is appended to *every* shot's assembled prompt as `Look (consistent across the film):
<text>` — use it for a visual style or mood you want held across the whole piece instead of
repeating it in every shot's text.

## Frame handoff (continuity)

Each card has an **open frame** and a **close frame**. The right-hand Generate drawer always
shows a frame-handoff row — it isn't gated by act boundaries, only by overall project order:

- With a shot selected, the row is actionable as long as there's a shot before it anywhere in
  the project (across all acts) — the first shot of Act 2 still gets it, from the last shot of
  Act 1. Only the very first shot of the whole project has none.
- With no shot selected (including draft mode), the row shows a static hint instead of a
  button — there's no prior shot to inherit from.

The button itself:

- **↳ inherit `<code>` close** — copies the previous shot's stored close-frame metadata
  forward as this shot's open frame (`<code>` is the previous shot's code, e.g. `A·01`).
- Once the previous shot has a rendered clip, the same button becomes **✂ splice
  `<code>`'s last frame** — it extracts the actual last video frame from that rendered clip
  (via the server) instead of just copying stored metadata.

This is how a sequence of independent 5–15s clips reads as one continuous scene. There is no
separate link-status indicator — the button itself is the only signal of whether a handoff is
available.

## Deep Focus (single-shot editor)

Double-click any board card to open **Deep Focus** — a maximized overlay for that one shot.
It holds: status (click to cycle), title, mode, duration, the discreet/blur toggle, open and
close frame slots, **Other references & @tags**, the audio cue, notes, a **Copy shot**
button, and **Select in Generate →** (jumps that shot into the right-hand Generate drawer).

Deep Focus's frame slots have no handoff control of their own — chaining a shot's open frame
to the previous shot's close frame (see *Frame handoff* above) only works from the board +
Generate drawer, not from inside Deep Focus.

## ▶ Generate shot

There's no per-card Generate control on the board — **▶ Generate shot** lives in the
right-hand Generate drawer's Video tab and renders whichever shot is selected (or the draft
card, if nothing is selected):

1. Cast/frames referenced by the shot upload in @-tag order (uploads are free).
2. The assembled shot text becomes the prompt; the mode picks the engine path.
3. The task runs async on PixAI — the card shows **wip → done** with its status badge and a
   static frame thumbnail. To actually watch the clip, select the shot and pull the Timeline
   drawer to **full** (see *Reviewing and trimming a finished shot* below) — that's the only
   place a finished clip plays.
4. The finished mp4 is downloaded and **cataloged into the gallery** like any other
   generation. **Free when a V4.0 video card covers it** (cards auto-apply); otherwise
   the credit price applies — same rules as everywhere else in the suite.

**💾 Use an existing video instead** (in the Video tab) skips generation entirely — pick a
video you already have in your gallery and it's attached straight onto the shot as its
finished clip.

The Loom is **localhost-only** — the board *and* generation. Another device on your network can
browse the gallery, but the header's **▰ The Loom** button is hidden for it and `/loom` answers
*"The Loom is localhost-only."* (403) — it can't look, and it can't spend.

## Storyboards (multiple projects)

The top bar's **▾** button opens a popover listing every saved storyboard, each showing its
name and shot count. From there: **open** any storyboard, **delete** one (✕), **+ New** (blank
storyboard), or **⎘ Duplicate** the currently-open one. Storyboards are fully independent —
each has its own acts, cast, and Draft/Look settings — so there's no limit on how many pieces
you can have in flight.

## Draft mode (render quality)

The top bar's **⚡ Draft** checkbox is project-wide: while it's on, every shot renders at the
cheaper "basic" quality instead of "professional." Block out the whole animatic in Draft, then
turn it off and re-generate the keepers at full quality.

## Generating without a selected shot

The Generate drawer also works with **no shot selected**: pick a mode, write a prompt,
generate — then a shared **"Route results into a shot"** dropdown (the same one regardless
of tab) picks the destination shot. What happens next depends on the tab: **Image / Edit /
Reference** offer three destination buttons per result (open frame / close frame / cast —
cast doesn't need a target shot chosen); **Video** has one **attach** action. Use this to
explore a look before you've decided which shot it belongs to; the main gallery's own
Generate drawer behaves the same way for the same reason.

## Reviewing and trimming a finished shot

Select a shot with a rendered clip and pull the Timeline drawer to **full** to open its
preview:

- Hover the preview to scrub through the clip; a **⏸/▶** button toggles play/pause.
- **⏪ / ⏩** step the playhead in 0.25s nudges.
- Drag the in/out handles on the scrub track to **trim** the clip non-destructively — both
  **Play sequence** and **Export** honor the trim.
- **✂ Split** cuts the shot into two shots at the playhead.
- **⛶ Crop** — drag a rectangle over the preview; it's applied via an ffmpeg crop filter on
  export.

## Copy shot (the engine-agnostic path)

Double-click a shot card to open **Deep Focus**, then click **Copy shot**. It assembles the
same continuity-aware prompt (connect notes, camera, @refs) and puts it on your clipboard for
pasting into an external generator — e.g. a Seedance 2.0 interface, which uses the same
@reference grammar.

Tip: in the gallery's image picker there's a **"Copy the image's prompt to the clipboard
when picking"** checkbox — useful for carrying source-image context into the Bay while
you cast shots.

## Saving, backup, export

- The board **autosaves to the gallery server** (one atomically-written file per key under
  `loom/kv/` in your backup folder) — it survives restarts and browser changes. A legacy
  `loom/store.json` is split into that layout on first touch and left behind as
  `store.json.migrated`.
- The **Export ▾** dropdown offers three tiers:
  - **Shot list .txt** — the full shot list as text, a script you can read, annotate, or
    hand to someone else.
  - **Lightweight backup .json** — the project data only.
  - **Full bundle .zip** — the project JSON plus every referenced media file.
- Importing a backup **always creates a new storyboard** — it never overwrites or restores
  the currently open project in place.
- The top bar's **↓ Export** button is unrelated: see *Layout* below.

## Layout

The Loom is a fixed 4-region shell: a **Cast & Assets / Footage** tabbed card on the left
(with a Simple/Detailed density toggle), the **Acts & Shots board** in the center (click a
shot to select it — the whole workspace binds to it), a **Generate drawer** on the right
(Image/Edit/Reference/Video tabs), and a **Timeline drawer** fixed across the top
(hidden/slim/full, drag to resize).

The top bar also carries:

- **▾** — the Storyboards switcher, see *Storyboards* above.
- **▶ Generate all (N)** — batch-renders every unfinished shot.
- **⚡ Draft** — see *Draft mode* above.
- **↓ Export** — trims and stitches every finished shot into one mp4 via ffmpeg. This is a
  different feature from the **Export ▾** file-export dropdown above (both are labeled
  "Export" — don't confuse them).
- **▶▶ Play** — plays every finished shot back-to-back (Play sequence).

## Workflow suggestions

1. Block the whole piece first (acts, shots, durations) until the segment bar reaches the
   target tick.
2. Cast your characters/scenes once in Cast & Assets; cite with @refs.
3. Chain frames (`↳ inherit <code> close`) across acts for continuity.
4. Generate the anchor shots first (act openers, hero moments); review; then batch the rest.
5. Everything lands in the gallery — rate, collect, and curate clips like images.

## Relationship to the Generate drawer's Video tab

The drawer's **Video tab** is the *simple mode*: one shot, picked images, prompt,
duration, go. The Loom is the *production mode*: many shots with continuity,
cast, and a runtime target. They share the same engine underneath.

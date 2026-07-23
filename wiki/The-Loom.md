# The Loom

The storyboard for multi-clip video. Where the Generate drawer's **Video** tab makes *one*
clip, the Loom plans a whole piece — acts, shots, cast, continuity — and renders each shot
on the same PixAI video engine.

Open it from the gallery header (**▰ The Loom**) or go to `/loom`:

```bash
python pixai_gallery.py --out pixai_backup      # then http://127.0.0.1:5000/loom
```

You need to be signed in, exactly like the rest of the gallery — so the Loom works from a
tablet on your LAN too. It's a dense four-panel tool, so the header button is hidden at
phone widths.

It is also deliberately **engine-agnostic**: every shot can hand you its assembled prompt
via **Copy shot**, so you can plan here and render somewhere else.

## The mental model

```
Storyboard
└── Acts             (chapters of your piece)
    └── Shot cards   (one generated clip each)
        ├── mode          I2V / R2V / V2V / FLF
        ├── continuity    New scene / Cut / First→Last / Extend prev
        ├── duration      feeds the reel bar
        ├── open + close frames
        └── prompt, camera, lighting, transitions, notes
Cast & Assets        (reusable @image1 / @video1 / @audio1 references)
```

Shots are numbered by position — `A·01`, `A·02`, `B·01` — so the code always tells you
which act a shot is in and where it falls.

## The layout

Four fixed regions:

- **Left** — **Cast & assets** / **Footage**, with a Simple/Detailed density toggle.
- **Center** — the **Acts & Shots** board. Click a shot to select it; the whole workspace
  binds to it.
- **Right** — the **Generate drawer** (Image / Edit / Reference / Video tabs).
- **Top** — the **Timeline drawer** (hidden / slim / full — drag the grip to resize).

Both side rails collapse to an icon strip; clicking an icon re-opens the rail on that tab.

## Acts & shots

**+ New act** adds a chapter; **+ Add shot to \<act\>** adds a card to it. Each card carries
its code, title, mode, duration and a status badge, plus small controls to move it up/down,
duplicate it, delete it, or move it to another act. **Double-click a card** to open
[Deep Focus](#deep-focus).

The **reel bar** in the Timeline drawer draws one colored segment per shot, sized by
duration, with a tick marking the 8-minute target — a glance-level pacing cue rather than a
number. Once a shot has rendered, its segment uses the clip's real length instead of the
planned one.

## Shot modes

| Mode | What it does |
|---|---|
| **I2V** | Animate a single image — it becomes the first frame; prompt only the motion |
| **FLF** | First & last frame: interpolate from a start frame to an end frame |
| **R2V** | Multi-reference — lock identity/style/motion through `@tags` |
| **V2V** | Extend or transform an existing clip |

There is no text-only mode: these video models need an input frame or reference, so every
shot needs one.

## Connecting shots

The Video tab's **Continuity** chips say how a shot joins the one before it:

- **New scene** — an intentional break, fresh look or place.
- **Cut (in edit)** — a hard/match cut you'll join in your editor; rhyme the frames.
- **First→Last** — land on an exact end frame and prompt the motion between.
- **Extend prev** — feed the previous clip in as `@video1` and continue seamlessly.

The last two also append a "smooth, continuous, seamless — no hard cut" line to the
assembled prompt.

### Frame handoff

Every card has an **open frame** and a **close frame**, shown as two slots in the Generate
drawer. When there's a shot before this one anywhere in the project (across acts, not just
inside one), a button appears under the open slot:

- **↳ inherit `A·01` close** — copies the previous shot's stored close-frame forward.
- **✂ splice `A·01`'s last frame** — once that previous shot has actually rendered, the
  same button extracts the real last frame from its clip (honoring the trim) and uploads it.

That's how a run of independent 5–15s clips reads as one continuous scene. The very first
shot of the project has no previous frame, and neither does draft mode — you get a hint
instead of a button.

## Cast & Assets

References live once and get cited everywhere. Add them with **+ add from gallery** (one
image or video from your catalog) or **↖ Import collection** (a whole
[collection](Collections) at once), and they're tagged **`@image1`, `@video1`, `@audio1`**
in tag order. Write those tags into a shot's prompt to cite them; the **lock** checkbox
marks a member as the consistency anchor ("maintain exact appearance") instead of a loose
reference.

With a shot selected, clicking a cast card toggles that member into or out of that shot.

**🎨 Project look** is a collapsible textarea at the top of the panel. Whatever you write
there is appended to *every* shot's assembled prompt as `Look (consistent across the film):
…` — a style or grade you want held across the whole piece, written once.

The second tab, **Footage**, is different: it's a grid of *this project's own* rendered
shots. Its **⤓ Browse library** button and the drag-and-drop zone below it both add media in
as a **cast** reference (a picked video becomes `@video`, a dropped image becomes `@image`).

## Generating a shot

Select a shot, open the Generate drawer's **Video** tab, and press **Generate video**. What
happens:

1. The shot's cast and frames upload in `@tag` order (uploads are free).
2. The assembled shot text becomes the prompt; the mode picks the engine path.
3. The card shows **wip → done** as the task runs. If a render goes quiet, the badge pauses
   and you can click it to check again.
4. The finished mp4 downloads and is cataloged into your gallery like any other generation.

**It's free when a V4.0 video card covers it** — cards auto-apply, same as everywhere else
in the suite; otherwise the credit price applies. See [Generating](Generating).

Other controls in the top bar:

- **⚡ Draft** — project-wide: render every shot at the cheaper *basic* quality. Block out
  the animatic in Draft, then turn it off and re-generate the keepers.
- **▶ Generate all (N)** — renders every shot that isn't done yet, one after another, with a
  running batch tally. The pill beside it is a standing cost-to-finish estimate (click to
  refresh).
- **💾 Use an existing video instead** (Video tab) — skip generation entirely and attach a
  video you already have as this shot's clip.

### Generating without a shot selected

With nothing selected the drawer switches to **draft generation** — pick a mode, write a
prompt, generate, and explore a look before you've decided where it belongs. A **Route
results into a shot** dropdown then picks the destination: Image / Edit / Reference results
offer *open frame* / *close frame* / *cast* (cast needs no target), and Video offers a
single *attach*.

## Reviewing and trimming

Select a shot that has rendered and pull the Timeline drawer to **full** — that's where the
clip actually plays:

- Hover the preview to scrub; **⏸/▶** toggles playback, **⏪ / ⏩** nudge by 0.25s.
- Drag the in/out handles to **trim** non-destructively — both Play and Export honor it.
- **✂ Split** cuts the shot in two at the playhead.
- **⛶ Crop** — drag a rectangle over the preview; it's applied on export.

**▶▶ Play** in the top bar plays every finished shot back-to-back, trims and all — a rough
cut with nothing rendered.

## Deep Focus

Double-click any card for a maximized single-shot editor: status (click to cycle), title,
mode, duration, a **blur previews** toggle for discreet shots, a **Prompt** field for the
shot's base prompt (Camera/Lighting/cast are still woven in on top when it generates), both
frame slots, **Other references & @tags** (add image/video/audio refs with roles), the audio
cue, notes, **Copy shot**, and **Select in Generate →** to jump the shot into the drawer.
`Esc` closes it.

Frame handoff isn't available inside Deep Focus — chain frames from the board plus the
Generate drawer.

## Copy shot

**Copy shot** (in Deep Focus) assembles the same continuity-aware prompt — connect notes,
camera, lighting, cast, `@refs`, project look — and puts it on your clipboard for any
external generator that speaks the same `@reference` grammar. Plan here, render anywhere.

## Storyboards

The top bar's **▾** opens the storyboard switcher, listing every saved board with its shot
count. From there: **open** one, **+ New** a blank one, **⎘ Duplicate** the open one, or
delete one with ✕. Boards are fully independent — their own acts, cast, look and Draft
setting — so you can keep several pieces in flight.

## Saving & export

The board **autosaves to the gallery server** (one file per key under `loom/kv/` in your
backup folder), so it survives restarts and follows you between browsers and devices.

**Export ▾** offers three tiers, plus restore:

| Export | What you get |
|---|---|
| **Shot list `.txt`** | the whole board as readable text — a script to annotate or hand off |
| **Lightweight backup `.json`** | the project data only |
| **Full bundle `.zip`** | that JSON plus every referenced media file |

Restoring either file **always creates a new storyboard** — your open board is never
overwritten. Importing a bundle also catalogs any media this machine doesn't already have,
so a board moved between machines arrives with its images and clips intact.

Don't confuse that menu with the top bar's **↓ Export**, which is the actual render: it
trims and stitches every finished shot into one 720p mp4 via ffmpeg (with progress, and a
Stop button). That one needs **ffmpeg on your PATH** — without it the export refuses and
tells you so.

## Where to go next

- The **?** button at the bottom-right of `/loom` is a quick in-page guide.
- `docs/LOOM.md` in the repo is the full manual — the same ground covered in more depth.
- [Generating](Generating) covers the credits, free cards, and the simple one-clip Video tab.
- [Collections](Collections) — bulk-select images in the gallery and **Send to The Loom
  (cast)**.

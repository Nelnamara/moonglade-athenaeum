# The Loom

The storyboard for multi-clip video. Where the Generate drawer's **Video** tab makes *one*
clip, the Loom plans a whole piece — acts, shots, cast, continuity — and renders each shot
on the same PixAI video engine.

Open it from the gallery header (**▰ The Loom**) or go to `/loom`:

```bash
python moonglade_gallery.py --out pixai_backup      # then http://127.0.0.1:5000/loom
```

You need to be signed in, exactly like the rest of the gallery — so the Loom works from a
tablet on your LAN too. The header button is there at every screen width, phones included.
It's a dense four-panel tool, so **turn a phone to landscape** — portrait works but is
cramped.

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
duplicate it, delete it (it asks first — a card carries its prompt, cast, frames and any
rendered result, and there is no undo), or move it to another act. **Double-click a card** to open
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

**Not every model offers all four.** Multi-Reference (R2V) only works on the V4.0 pair;
V3.0 Flash and V2.7 only ever offer First Frame (I2V) — the Generate drawer hides the
modes a selected model doesn't support. See [Generating](Generating#video-models-and-shot-mode-gating)
for the full per-model breakdown (durations, free-card eligibility, mode support).

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
in tag order. That stored tag is the member's *project-wide name*; what a given **shot**
actually cites them as is positional, and the two have no reason to match — a shot's
Opening Frame is always `@image1` and its Closing Frame `@image2` (in the modes that use
one: First & Last and Multi-Reference), so cast and extra references number from `@image3`.
The panel shows both when a shot is bound: the editable `@tag` you named them with, and a
read-only `→ @imageN` beside it — the number that shot's prompt and generator really use.
A **reference budget** line above the rows keeps the arithmetic honest: PixAI takes six
images, attached frames claim theirs first, and anything past the remainder is marked
rather than silently trimmed. Write tags into a shot's prompt to cite members; the **lock**
checkbox marks a member as the consistency anchor ("maintain exact appearance") instead of
a loose reference.

With a shot selected, clicking a cast card toggles that member into or out of that shot.

A cast member can only be *cited* in a shot that actually has a picture for them, so one you
have added to a shot but not yet given an image is left out of that shot's assembled prompt
rather than referenced by a tag with nothing behind it. The shot card says so — a small
**"…: no image"** badge naming who — so it is visible while you build rather than discovered
in the output.

**🎨 Project look** is a collapsible textarea at the top of the panel. Whatever you write
there is appended to *every* shot's assembled prompt as `Look (consistent across the film):
…` — a style or grade you want held across the whole piece, written once.

The second tab, **Footage**, is different: it's a grid of *this project's own* rendered
shots. Its **⤓ Browse library** button imports an already-rendered video from your gallery
**straight onto the board as a real, placeable shot** — not as a reference. That's the
Footage tab's whole purpose: "bring this video in", not "cite it in a prompt". Cast & Assets
keeps its own separate **+ add from gallery** button for the reference use case. The
drag-and-drop zone below takes local *image* files, which land as `@image` references.

When you import a finished video this way, the Loom pulls its **first and last frame out of
the clip itself** and fills the shot's opening and closing frames with them — so an imported
shot looks like any other in Deep Focus, and its closing frame can hand off to the next shot's
opening frame just like a shot you rendered here. The card appears straight away; the two
frames catch up a second or two later.

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

**When the bundle can't find a file, it names it.** A shot can reference a clip that was
moved, deleted, or rendered on another machine and never synced. The zip still exports —
a partial bundle is still worth having — and a dialog then lists what didn't travel, by the
same `A·01` shot codes the board shows, rather than handing you a count and leaving you to
diff every reference against the zip's `media/` folder by hand. If a great many are missing
the dialog lists what it can and ends with "+N more, not listed here" — but the **complete**
list always rides inside the zip, as a `missing_media` entry in `project.json` — each id
alongside every place it
was referenced from, whether that's a shot's result, one of its frame slots, or a cast entry
— so it survives the download and reaches whoever you hand the bundle to.

Don't confuse that menu with the top bar's **↓ Export**, which is the actual render: it
trims and stitches every finished shot into one 720p mp4 via ffmpeg (with progress, and a
Stop button).

### What the render needs

- **ffmpeg on your PATH** — required. Without it the export refuses and tells you so.
- **ffprobe — strongly recommended, and it ships with the full ffmpeg build.** It's what
  reads a clip's real length and whether it has any sound. Without it (some minimal ffmpeg
  builds omit it) the export still runs, but every clip reads as silent and no length is
  measurable, so as soon as one shot has no out point of its own the cut is muxed with **no
  audio track at all**. The dialog says so in amber, right above the Download button, and
  names ffprobe — rather than handing you a quietly silent file and filing the reason in a
  log you have no reason to open. Dropping the track isn't a compromise: the whole track was
  going to be synthesized silence anyway, so a file with no track sounds identical — and
  can't drift.

Setting aside the obvious refusals — no ffmpeg, no finished shots to export, or an export
already running — there is exactly one case where the audio handling refuses instead of
degrading: **some shot has real audio, and another shot's length can't be measured.**
Silence has no natural end, so
each silent segment needs a number — either its own out point or a real measurement. Guess
one and the concatenated audio doesn't merely mute that shot's tail; every later shot's
sound starts early and stays early for the rest of the cut. Rather than hand you a file that
looks finished and desyncs after the first shot, it names the shot and asks you to set its
out point (which supplies the length exactly) or fix the file. Since real audio was detected
somewhere, ffprobe is demonstrably working, so that one file is the suspect.

## Where to go next

- The **?** button at the bottom-right of `/loom` is a quick in-page guide.
- `docs/LOOM.md` in the repo is the full manual — the same ground covered in more depth.
- [Generating](Generating) covers the credits, free cards, and the simple one-clip Video tab.
- [Collections](Collections) — bulk-select images in the gallery and **Send to The Loom
  (cast)**.

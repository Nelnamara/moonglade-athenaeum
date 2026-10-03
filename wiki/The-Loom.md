# The Loom

The storyboard for multi-clip video. Where the Generate drawer's **Video** tab makes *one*
clip, the Loom plans a whole piece — acts, shots, cast, continuity — and renders each shot
on the same PixAI video engine.

Open it from the gallery header (**▰ The Loom**) or go to `/loom`:

```bash
python moonglade_gallery.py --out pixai_backup      # then http://127.0.0.1:5000/loom
```

**A storyboard has its own address.** `/loom` opens whichever board you had open last, as it
always has. `/loom?board=<id>` opens *that* one — so a storyboard is somewhere you can
bookmark and come back to, or send to yourself on another machine. The address in the bar
follows whichever board is open, so you can copy it at any time; the id appears there for
you rather than being something you type. An address naming a storyboard this account
doesn't have isn't an error page — it opens the board you'd have got anyway and says so in
the corner.

**← Gallery puts you back where you were** — the page of the library you were on, the
picture you had open, and how far down you had scrolled. (Your search and filters are not
carried across; the library clears those on any reload, as it always has.) A `/loom` opened
straight from a bookmark, in a tab that was never in the library, goes to the front door.

That promise is for the **same tab** — the ordinary case, where you leave the library and
the Loom takes its place. If you open the Loom in a **new tab** instead (middle-click, or
ctrl/cmd-click the header button), the library tab never leaves, so it never records where
you got to: **← Gallery** in that new tab lands on whatever the library was showing when
the tab was opened. You still have the library itself sitting in the other tab, which is
why it works this way rather than the library writing a note on every scroll.

You need to be signed in, exactly like the rest of the gallery — so the Loom works from a
tablet on your LAN too, and signing back in returns you to the exact storyboard you asked
for. The header button is there at every screen width, phones included.

**On a phone the Loom opens its phone layout by itself** — a board-and-reel view built for
the narrow screen. Tablets are unaffected and still get the full desktop tool. Both switches
still work and always win: untick **📱 Mobile view** (in the storyboards **▾** menu) to get the wide board on
a phone, or tap **🖥 Desktop** in the phone bar, and the Loom remembers your choice in that
browser from then on. A phone that is already **held sideways** when the Loom opens gets the
wide four-panel board straight away; held upright it gets the board-and-reel view.

The choice is decided once, when the Loom opens, and after that only those two switches
change it. Turning the phone over mid-session will not swap the tool out from under you.

A browser that had already used the older **Mobile view** switch keeps whatever it was set
to — the auto-open speaks only for a browser that has never answered.

It is also deliberately **engine-agnostic**: every shot can hand you its assembled prompt
via **Copy shot**, so you can plan here and render somewhere else.

## The mental model

```
Storyboard
└── Acts             (chapters of your piece)
    └── Shot cards   (one clip each -- every render of it kept as a take, one of them ★)
        ├── mode          I2V / R2V / V2V / FLF
        ├── continuity    New scene / Cut / First→Last / Extend prev
        ├── duration      feeds the reel bar
        ├── open + close frames
        └── prompt, camera, lighting, transitions, notes
Cast & Assets        (reusable @image1 / @video1 / @audio1 references,
                      ticked from your cast library)
Music bed            (one audio file under the whole cut, kept on this machine)
```

Shots are numbered by position — `A·01`, `A·02`, `B·01` — so the code always tells you
which act a shot is in and where it falls.

## The layout

The **top bar** is one row: the open storyboard's **name** with its **▾** (see
[Storyboards](#storyboards)), the **find in storyboard** field and its chips, **⚡ Draft**, then
**▶ Generate all** with its cost estimate, **▶▶ Play**, **⇩ Render** and **Export ▾**, and at the far
end the **spent** figure, a goal you have pinned in the Folio, **Activity** and **← Gallery**. On a
narrow window the bar wraps, but **← Gallery** never sits alone on a row. A banner sits above it;
**⌄ Hide banner** folds it away and **🖼 Banner** brings it back.

Four fixed regions:

- **Left** — **Cast & assets** / **Footage** / **Library**, with a Simple/Detailed density toggle
  (Cast opens in Simple).
- **Center** — the **Acts & Shots** board. Click a shot to select it; the whole workspace
  binds to it.
- **Right** — the **Generate drawer**. Its header names the selected shot (**✕ unbind** lets go of
  it, **›** folds the drawer), **Image / Edit / Reference / Video** is one row of tabs, and the
  fields sit in rounded panels with the prompt outlined.
- **Top** — the **Timeline drawer** (hidden / slim / full). The grip under the reel is a button:
  **click it** and it steps hidden → slim → full → hidden (there is no dragging). Full always
  leaves part of the board in view; inside it the preview shrinks first, and when its rows still
  do not fit the drawer scrolls on its own.

Both side rails collapse to an icon strip, and the Loom opens with both collapsed so the board
is what you see first; clicking an icon opens the rail on that tab, floating over the board,
which dims behind it.

## Acts & shots

**+ New act** adds a chapter; the dashed **+ Add shot to \<act\>** tile at the end of an act's
cards adds a card to it. An act's header has its name (edit it in place), **↑ ↓** to move it,
**⌃** to fold its cards away (**⌄** brings them back — the act stays folded when you come back
to the board) and **✕** to delete it. Each card carries
its code, title, mode, duration and a status badge, its [takes](#takes) with **Render** /
**Re-render**, plus small controls to move it up/down,
duplicate it, delete it (it asks first — a card carries its prompt, cast, frames and any
rendered result, and there is no undo), or move it to another act. **Double-click a card** to open
[Deep Focus](#deep-focus).

The **reel bar** in the Timeline drawer draws one colored segment per shot, each sized by its
share of the whole cut, so the shots always span the bar; a segment names its shot code and
length, and a thin bar under it shows the shot's status. Once a shot has rendered, its segment
uses the clip's real length instead of the planned one. A peach underline on a segment means
that shot's [anchor changed](#re-anchor).

## Find in storyboard

**⌘F** (Mac) or **Ctrl F** puts you in the **find in storyboard** field in the top bar (it only
takes over the browser's own find while the Loom's board is on screen). Type anything and it
looks through each shot's **code** (`A·01`, `A01` and `a1` all work), **title**, **prompt**,
the **@tags** of its cast and its **notes**. The chips beside the field narrow it: **⚠ only**
(a changed anchor, or a ⚠ the card itself is showing), then the statuses and the modes that
are actually on this board. Chips in one group widen each other (**todo** and **error** finds
both); the groups and the text narrow together.

While a find is on, shots that don't match dim to 35%, the matching segments on the reel are
ringed, and the count reads **2 of 5**. **↑ ↓** (the arrows or the keys) and **Enter** step
through the matches, selecting each shot and scrolling to it; the current one wears a brighter
ring. **Esc** clears the text and the chips. Find only looks and selects: it never changes a
shot, prices or renders anything.

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

Splice and Re-anchor upload the frame to your PixAI account (free, never a render) and save its
thumbnail beside it, so the frame draws in the drawer and on the next shot's card. With
`READ_ONLY` set they are refused like every other write to your account.

That's how a run of independent 5–15s clips reads as one continuous scene. The very first
shot of the project has no previous frame, and neither does draft mode — you get a hint
instead of a button. The splice uploads the still to your PixAI account — free, but it is a
write, so `READ_ONLY` in `config.json` refuses it (and Re-anchor, below, which does the same).

### Re-anchor

A spliced frame remembers where it came from: which shot, which of its takes, and where that
take was cut. If that shot later uses a **different take** (or is cut at a different point),
the frame no longer matches what plays before it. The dependent shot says so — a peach
underline on its reel segment, a peach dot on its pair in the [continuity
ribbon](#the-continuity-ribbon), and on its card **⚠ anchor changed · its open frame came from
A·01 take 1; A·01 now uses take 2** — with two buttons:

- **Re-anchor** takes the new close frame, exactly as **✂ splice** does (the still is cut from
  the clip on this machine and uploaded free). **Nothing is rendered**: the card then says
  **Open frame updated. Render a new take to match it.**, and that render is your own click.
- **Keep** accepts the mismatch for this pair of takes only. If that shot changes take again,
  the warning comes back.

There is never an automatic re-render. A shot that hasn't rendered yet is warned too — that is
exactly where an out-of-date frame would cost you a render.

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

### The cast library

Your cast members live in one **library** that all your storyboards share, and each storyboard
**ticks** the ones it uses — so a series keeps "Nelnamara" in one place while a one-off doesn't
inherit everyone. The **Library** tab (beside Cast & assets and Footage) lists them: a tick box,
the member's picture, its name (🔒 when its appearance is locked), and a line like
**@image1 · in 3 storyboards · A·02 A·03** — its tag here, how many storyboards use it, and
the shots on this board that cast it.

- **Tick** a member to use it in this storyboard; it keeps its tag unless this storyboard
  already uses that tag, in which case it takes the next free one.
- **Untick** takes it out of this storyboard. If shots here cast it, you're asked first, by name
  (**Nelnamara is used by A·02, A·03. Remove from this storyboard anyway?**), and it is taken out
  of those shots' cast too. The library keeps the member.
- **Change its picture** (click the round picture) or its **🔒**, here or in the Cast & assets
  rows, and it changes **everywhere it's used**: in the library, on this storyboard and on every
  other storyboard that ticks it. Each of those is saved carefully — one that changed in
  another tab meanwhile is re-read and updated once more — and any storyboard that couldn't be
  updated is named rather than skipped quietly. A name, a tag or a kind stays each storyboard's
  own.
- **+ Add** picks a picture or video from your gallery (or **upload** one from this computer)
  and puts it in the library, ticked here.
- **⎘ Duplicate** of a storyboard keeps its ticks.

Members a storyboard had before the library existed show as **this storyboard only**. Nothing
changes on its own: one joins the library the first time you untick it or change its picture or
lock. Opening the Library tab only reads — your library and your other storyboards, to count
where each member is used — and never writes anything.

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

Press **Render** on a shot's card (**Re-render** once it has a take), or select the shot, open
the Generate drawer's **Video** tab, and press **Generate video**. What happens:

1. The shot's cast and frames upload in `@tag` order (uploads are free).
2. The assembled shot text becomes the prompt; the mode picks the engine path.
3. The card shows **wip → done** as the task runs. If a render goes quiet, the badge pauses
   and you can click it to check again.
4. The finished mp4 downloads and is cataloged into your gallery like any other generation,
   and lands on the shot as a new [take](#takes).

The price is shown before anything is sent, and a paid render asks first, whether you press a
card's **Render** or the drawer's **Generate video**: the same question, priced off exactly what
will be sent, and a **No** sends nothing. A render a free card
covers doesn't ask (as everywhere in the suite) — and if that card has been used somewhere else
by the time the render goes out, it is refused rather than charged: **Nothing was sent. Press
Render again to see the new price.** A shot that is already rendering can't be started a
second time, whether from a double click, a second tab or the drawer. A shot whose open frame
is a picture you imported into your library (not a PixAI picture) is marked **imported picture —
can't be sent to PixAI yet**, and rendering it is refused before anything is priced.

**It's free when a V4.0 video card covers it** — cards auto-apply, same as everywhere else
in the suite; otherwise the credit price applies. A video card is a book of **tickets**, and
a shot costs one per 5 seconds (5s = 1, 10s = 2, 15s = 3): the drawer's cost line reads
"uses N of H cards", and if you hold fewer than the shot needs, no card is used, the shot
costs the full credit price, and it says so before you press Generate — which, matching the
website, still spends if you do. See [Generating → Free cards and videos](Generating#free-cards-and-videos).

Other controls in the top bar:

- **⚡ Draft** — project-wide: render every shot at the cheaper *basic* quality. Block out
  the animatic in Draft, then turn it off and re-generate the keepers.
- **▶ Generate all (N)** — renders every shot that has no take yet, one after another, with a
  running batch tally (a shot whose last re-render failed keeps its ★ take and is not re-sent). The pill beside it is a standing cost-to-finish estimate (click to
  refresh). The batch confirm counts each shot's tickets against the pool you hold, in order,
  so a batch that outruns your cards is called out shot by shot — "this one will spend" — before
  you confirm, rather than after the tally comes up short.
- **`~1,180 cr spent`** — beside it, what this project has *already* cost. The two read as
  before and after, and they are different kinds of number: the estimate is a quote (**≈**),
  this is a record (**~**) — PixAI's own charge for each finished shot, taken from your
  catalog. Hover for the act-by-act breakdown; click to re-read it. Every re-roll counts, not
  just the take that survived, so "spent" means spent — though attempts you re-rolled before
  this existed were never recorded and cannot be counted now. Two things are deliberately not
  folded into the total: a shot whose charge PixAI never reported and one whose picture has
  since been deleted ride alongside as **(+N unk)**, because an unknown is not a zero; and a
  clip you brought in from your library rather than rendered here is left out entirely — that
  money was spent elsewhere — and named on hover. Nothing is fetched from PixAI to work it out.
- **💾 Use an existing video instead** (Video tab) — skip generation entirely and attach a
  video you already have as this shot's clip.

### Takes

Every render of a shot is kept as a **take**; nothing is overwritten. The newest take becomes
the **★ selected** one, and ★ is what **▶▶ Play**, **⇩ Render**, **Export** and the
[continuity ribbon](#the-continuity-ribbon) use. Under each card the takes strip shows the
newest six (a **+N** before them counts the older ones) with the ★ one outlined; click another
to make it ★ — that only chooses, it never renders or prices anything. The line under it reads
**Take 2 of 3 ★ used by Play · Render · Export**.

A shot's full take list sits beside its preview when the Timeline drawer is pulled to
[full](#reviewing-and-trimming): when each landed and what it was rendered with, and per take
**★ Use**, **Reuse settings** (puts that take's mode, duration, prompt and the rest back on the
shot — nothing is rendered until you press Render) and **Delete…**. Deleting asks first — **Delete
take 2? Its clip stays in your library.** — and that is exactly what happens: **deleting a take
never deletes its clip**, which stays in your library like any other video, and what it cost
still counts in *spent*. You can't delete the ★ take; select another one first. Take numbers are
never reused, so an exported `A01_t3.mp4` always means the same clip.

A re-render that fails leaves the shot on its ★ take and says **Last render didn't land** on the
card. A shot rendered before takes existed shows its clip as take 1; its earlier re-rolls still
count in *spent* but aren't listed as takes. If the same storyboard is open in two tabs and both
save, the one that saved second is told **This storyboard changed in another tab. Your takes
were kept; other edits from this tab were replaced.**, naming any shot whose ★ or take numbers
moved.

### When the server didn't confirm a render

If the page loses touch with the server while a render is being sent, the Loom can't know
whether it went out — so it doesn't guess, and it never sends it again on its own. The shot stays
held, and the card says **The server didn't confirm this render. Check Activity before rendering
again.**

- **↻ Check** asks the server again what became of it. It never re-sends.
- **I checked Activity — release this shot** is for when Activity shows it never started: it
  frees the shot so you can render it again. Releasing **never re-sends the old render**; if the
  server knows that render did go out, the shot follows it instead of being released. And if it
  somehow went through anyway, its clip still lands in your library.

A copy of a storyboard (⎘ Duplicate, or a restored backup) never carries a render in flight — the
render belongs to the storyboard it was made on.

### Generating without a shot selected

With nothing selected the drawer switches to **draft generation** — pick a mode, write a
prompt, generate, and explore a look before you've decided where it belongs. A **Route
results into a shot** dropdown then picks the destination: Image / Edit / Reference results
offer *open frame* / *close frame* / *cast* (cast needs no target), and Video offers a
single *attach*.

## Reviewing and trimming

Select a shot that has rendered and pull the Timeline drawer to **full** — that's where the
clip (its ★ take) actually plays, with the shot's [take list](#takes) beside it:

- Hover the preview to scrub; **⏸/▶** toggles playback, **⏪ / ⏩** nudge by 0.25s.
- Drag the in/out handles to **trim** non-destructively — both Play and Render honor it.
- **✂ Split** cuts the shot in two at the playhead.
- **⛶ Crop** — drag a rectangle over the preview; it's applied on export.

**▶▶ Play** in the top bar plays every finished shot back-to-back, trims and all — a rough
cut with nothing rendered. The full view also holds the [music bed](#the-music-bed) and the
[continuity ribbon](#the-continuity-ribbon).

### The music bed

One audio file can sit under the whole cut. **♪ Add a music bed** (under the reel in the full
view) picks an mp3, wav, m4a, aac, ogg or flac file of up to 50 MB. It is **kept on this machine
and never uploaded** — nothing about it reaches PixAI. Its waveform sits under the reel.

- **Level** −24 to 0 dB (−8 to start).
- It fades in over **2 s** and out over **3 s**, and ducks **−12 dB** under shots that carry their
  own audio (one rendered with **Generate audio** on, a Multi-Reference shot with an audio
  reference, or a V2V shot's source sound) — those stretches are hatched.
- A bed longer than the cut ends with the cut, faded out; a shorter one simply ends — it never
  loops.

**▶▶ Play** and **⇩ Render** mix it in, the full bundle carries it, and the edit decision list
lists it as an audio event. **✕** takes it off this storyboard; the file itself stays. Bed files
are never deleted on their own: when some are no longer on any storyboard, the full view offers
**Remove…** for exactly those, and asks first. If one of your storyboards won't read (a file torn by a crash, say),
nothing is offered for removal: the line names that storyboard, when it was saved, and where its
file is under the library's `loom/kv/` folder, so you can restore it from a backup or delete it.

### The continuity ribbon

Under the reel in the full view, **CONTINUITY RIBBON · close frame → next open frame** pairs each
cut: a shot's closing frame beside the next shot's opening frame (**A·01 out** · **A·02 in**),
both from the ★ takes and their trims, so a jump in light, pose or costume shows at a glance.
Shots with nothing rendered are left out, as Play leaves them out.

A pair gets a **peach dot** when the second shot's [anchor changed](#re-anchor), or when the two
frames' colours differ strongly — measured as the average colour difference in Lab (ΔE over 25).
That second one is **a heuristic, not a verdict**: a deliberate cut to night should trip it.
Hover a pair for which it is. The frames are cut from your clips on this machine with ffmpeg —
nothing is uploaded — so without ffmpeg, or for a clip that isn't on this machine, a pair shows
plain tints and only a changed anchor can mark it.

**Click a pair** to open both shots: the second is selected and find narrows to exactly those
two, so both cards and both reel segments stand out. **Esc** lets them go.

## Deep Focus

Double-click any card for a maximized single-shot editor: status (click to cycle), title,
mode, duration, a **blur previews** toggle for discreet shots, a **Prompt** field for the
shot's base prompt (Camera/Lighting/cast are still woven in on top when it generates), both
frame slots, **Other references & @tags** (add image/video/audio refs with roles), the audio
cue, notes, **Copy shot**, and **Select in Generate →** to jump the shot into the drawer (it opens
on the **Video** tab). `Esc` closes it.

Frame handoff isn't available inside Deep Focus — chain frames from the board plus the
Generate drawer.

## Copy shot

**Copy shot** (in Deep Focus) assembles the same continuity-aware prompt — connect notes,
camera, lighting, cast, `@refs`, project look — and puts it on your clipboard for any
external generator that speaks the same `@reference` grammar. Plan here, render anywhere.

Tip: the gallery's image picker has a **"Copy the image's prompt to the clipboard when
picking"** checkbox — useful for carrying source-image context along while you cast shots.

## Storyboards

Click the storyboard's name in the top bar (or its **▾**) and the **Storyboards** list opens,
with every saved board and its shot count. From there: **open** one, **+ New** a blank one,
**⎘ Duplicate** the open one, or delete one with ✕; **📱 Mobile view** is the last row. Boards
are fully independent — their own acts, cast, look and Draft setting — so you can keep several
pieces in flight.

## Saving & export

The board **autosaves to the gallery server** (one file per key under `loom/kv/` in your
backup folder), so it survives restarts and follows you between browsers and devices.

**Export ▾** offers three tiers, the editor handoff, plus restore:

| Export | What you get |
|---|---|
| **Shot list `.txt`** | the whole board as readable text — a script to annotate or hand off |
| **Lightweight backup `.json`** | the project data only |
| **Full bundle `.zip`** | that JSON plus every referenced media file (every take's clip, and the music bed) |
| **Edit decision list `.edl` + `.csv`** | a zip for finishing in Resolve, Premiere or Final Cut |

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

### Edit decision list

**Export ▾ → Edit decision list .edl + .csv** opens a preview of both files (switch between
**.edl** and **.csv**) worked out from the board as it is now; **Download** gives one zip:

- a **CMX3600 `.edl`** at 24 fps non-drop — one event per rendered shot, from its ★ take with
  its trims and splits, record times back to back from 01:00:00:00;
- a **`.csv`** with one row per shot: order, code, title, take, file, in, out, duration, mode,
  prompt;
- **each ★ take's clip**, named like `A01_t2.mp4` (the shot code without its dot, and the take),
  and the music bed if there is one (as an audio event in the `.edl`).

Shots with no render are left out, and a comment line in the `.edl` lists them. A clip that isn't
complete on this machine is not put in the zip; a `MISSING.txt` inside it names what's missing.
Nothing here renders or reaches PixAI. It is a desktop export — the phone layout doesn't offer it.

That menu is for project *files*. The top bar's **⇩ Render** is the video: it trims and
stitches every finished shot into one 720p mp4 via ffmpeg (with progress, and a Stop
button).

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

When ffmpeg itself fails partway, the export says why: the message carries ffmpeg's own last
lines (with your paths redacted) instead of a bare exit code.

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

## Sending pictures from the gallery

In the gallery, select pictures and open **Actions** (or open a hand-picked collection's order
editor): **▮ Send to The Loom** has two choices.

- **as cast** — the pictures join the cast as `@image` members (and your
  [cast library](#the-cast-library)), ticked on the storyboard that opens.
- **as shots, in order** — a new act with one image-to-video shot per picture: the picture is
  the shot's opening frame, the shot is 5 s long and is titled from the picture's prompt. The
  order is the collection's own [manual order](Collections#manual-order) when it has one, oldest
  first otherwise (a smart collection sends its current matches). Videos are left out, up to 60
  pictures go at once (more is refused, not cut short), and the Loom asks once before adding
  the act. **Nothing is rendered** — the shots wait for your own Render.

## On a phone

The phone layout carries the same work, sized for a finger:

- **Takes** — open a shot: the ★ take's still sits at the top with its takes strip under it.
  **Swipe the still** sideways to use the next or previous take; **hold a take** to make it ★; tap
  one for **★ Use this take**, **Reuse settings** and **Delete…** (the same rules as the desktop —
  its clip stays in your library). Swiping never renders.
- **Re-anchor** — a changed anchor shows as a peach underline on the scrub reel and **⚠ anchor
  changed** on the card; **Re-anchor** and **Keep** are in the shot's screen.
- **Music bed** — **♪ Bed** in **Review & trim** picks the file; with one on the storyboard it
  opens a sheet with the level, the fades, a different file, and remove.
- **Cast library** — the cast sheet (👥 in a shot's screen) has a **Library** tab beside Cast &
  assets and Footage: tap a member to tick or untick it (the same question when shots use it).
- **Find** — **⌕** in the header opens the find field and its chips; matches ring on the scrub
  reel, the rest dim, and the arrows step through them.
- **Continuity ribbon** — a swipeable strip of the same pairs at the bottom of **Review & trim**;
  tap one to open both shots on the board.
- The **edit decision list** is desktop only.

## A workflow that works

1. Block the whole piece first (acts, shots, durations) and read the reel bar as the shape
   of the cut.
2. Cast your characters/scenes once in Cast & Assets; cite them with `@refs`.
3. Chain frames (**↳ inherit … close**) across acts for continuity.
4. Generate the anchor shots first (act openers, hero moments); review; then batch the rest
   with **▶ Generate all**.
5. Everything lands in the gallery — rate, collect, and curate clips like images.

## Where to go next

- The **?** button at the bottom-right of `/loom` opens the app's guide on this page (the same guide the ? key opens anywhere).
- [Generating](Generating) covers the credits, free cards, and the simple one-clip Video tab.
- [Collections](Collections) — bulk-select images in the gallery and **▮ Send to The Loom**,
  as cast or as shots in order.

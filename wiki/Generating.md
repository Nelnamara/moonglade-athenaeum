# Generating images

Moonglade Athenaeum can **create** images via PixAI, not just back them up. Every
generation is downloaded into your backup and catalogued as `source='api'`, so it
appears in the gallery alongside your history.

> **Generation spends PixAI credits.** Downloading/cataloging is free; the generation
> is the paid part. The tool **previews unless you explicitly confirm**, and defaults
> to the cheaper priority.

## In the web gallery (the Generate drawer)

Open the gallery and click **✦ Generate** to slide out the **Generate drawer** — the
creation surface, with the live credit cost and free-card check up front (covered
generations cost 0). Its controls map onto the same PixAI parameters:

| Control | Maps to | Notes |
|---|---|---|
| **Prompt** / **Negative** | `prompts` / `negativePrompts` | natural language is fine |
| **Model** picker | `modelId` | search resolves the correct *version* id automatically |
| **LoRAs** → Add | `lora` + `loraParameters` | search → pick → weight; stack several |
| **Aspect** / dimensions | `width`/`height` | presets at SDXL-friendly dims |
| Steps / CFG / Count / Seed | the obvious params | blank seed = random; dims rounded to /8 |
| **Mode** | `inferenceProfile` | Auto (default) · Lite · Standard · Pro · Ultra |
| **Prompt helper** | `promptHelper` | on by default; uncheck to use your prompt literally |
| **High priority** | `priority` | off = Turbo (500) if your membership covers it, otherwise standard (0) — both free; on = High (1000), faster and **costs extra credits** |

Submit and the result drops straight into your catalog, tagged `source='api'`, and
appears in the gallery. Submitting doesn't lock the button — PixAI itself runs
generations in parallel, so you can queue up several in a row (Generate, Edit, Enhance,
Fix, and the Video tab all work this way) and each one tracks and reports its own result
independently.

### The model-vs-version-id gotcha
`createGenerationTask` needs a model's **version id**, not its model id. A model page
URL (`pixai.art/model/<id>`) gives the *model* id, which generation rejects
("Invalid modelId"). The drawer's **model search** (and the CLI's `--list-models`) hand
you the correct version id — prefer those.

### Modes are model-specific
Lite/Standard suit older SD models; Pro/Ultra are for newer types. The Mode picker
doesn't filter by model, so you can still pick an unsupported combination — pick
**Auto** if you're not sure which your model takes. You don't have to get it right by
hand, though: since 2026-07-24, an unsupported Mode no longer errors out. The shared
submit path every generate/edit route goes through (the web Generate tab, and anything
else submitting through it, including the Loom's own reference-image generation) now
auto-falls-back to the model's default and resubmits once instead of failing — a
rejected submit costs no credits either way, so the retry is free — matching the CLI's
own long-standing behavior (see `--mode` below). If you ever see the raw error text
itself instead of a friendly message, see
[Troubleshooting](Troubleshooting#unknown-inferenceprofile-).

### LoRAs are add-ons, not base models
A LoRA can't be the **base** model. The base picker excludes LoRAs; add them via the
**LoRAs** row.

### Finding a model or LoRA
The picker opens on **Market** — everything on PixAI. Two other places to look sit next
to it:

- **Bookmarked** — whatever you have bookmarked on pixai.art. It reads your live
  bookmarks, so anything you bookmark on their site shows up here.
- **Mine** — LoRAs you trained yourself. LoRAs only; you don't author base models.

On Market you can also narrow by **category** (character, animal, style, realistic, pose,
clothing, background, detail, other), by **when it was posted**, by **source**
(PixAI-trained or brought in from elsewhere), and to models that **allow commercial use**.

The filter row disappears on **Bookmarked**, and that is deliberate rather than an
oversight: PixAI's bookmark list only supports a search term, so a category or date
control there would look like it worked and quietly do nothing. Search still works, and if
you have a base model selected the list is still limited to LoRAs that fit it.

**If Bookmarked looks emptier than you expect**, that is usually the compatibility filter
rather than a fault — with a base model selected, only LoRAs matching its architecture are
shown. Clear the base model to see all of them.

## On the CLI

```bash
# preview only (no credits):
python moonglade_backup.py --generate --prompt "a night elf druid, moonlit grove"

# really generate (spends credits):
python moonglade_backup.py --generate --confirm \
    --prompt "..." --negative "lowres, text" \
    --model 1983308862240288769 --batch-size 1 \
    --mode standard --lora 1686550608832816741:0.7

# find model / LoRA version ids:
python moonglade_backup.py --list-models "anime"

# recover an already-created task by id (no new credits):
python moonglade_backup.py --generate --task-id <id>
```

| Flag | Default | Meaning |
|---|---|---|
| `--prompt` / `--negative` | — | the prompts |
| `--model` | Tsubaki.2 | model **version** id |
| `--lora VERSIONID:WEIGHT` | — | repeatable |
| `--mode` | `auto` | `auto`/`lite`/`standard`/`pro`/`ultra` — an unsupported mode auto-falls-back to the model's default and retries once instead of erroring (a rejected submit costs no credits either way); the web Generate tab does the same since 2026-07-24 |
| `--priority` / `--high-priority` / `--low-priority` | `500` | PixAI's speed channels: `0` standard (free) · `500` Turbo, ~7.6× faster and free but **members only** · `1000` High, ~10× faster and **costs extra** · `1500` extra high. Turbo is the default and falls back to `0` on its own if the account is not a member |
| `--no-prompt-helper` | off | use the prompt literally |
| `--width`/`--height`/`--steps`/`--cfg`/`--batch-size`/`--seed` | 512/512/25/7/1/random | |
| `--enlarge RATIO` | off | upscale the finished image with an upscaler network (PixAI's **Upscale** method). 0.1 steps, clamped to the biggest ratio your `--width`/`--height` allows |
| `--enlarge-model NAME` | `R-ESRGAN 4x+ Anime6B` | which upscaler `--enlarge` runs: `ESRGAN_4x`, `R-ESRGAN 4x+`, `R-ESRGAN 4x+ Anime6B`, `SwinIR_4x`, `Lollypop` |
| `--upscale RATIO` | off | re-render at the larger size (PixAI's **Hires** method) — adds detail rather than just resolution, allows a smaller maximum ratio, costs roughly 3× `--enlarge`. Mutually exclusive with it |
| `--upscale-denoise` / `--upscale-denoise-steps` | `0.6` / `26` | Hires denoising (strength 0.01–0.99, steps 1–50). PixAI's own hint: strength works better between 0.4 and 0.6 |
| `--face-fix` | off | run PixAI's face restorer over the result (their **Face Fix** booster) |
| `--quality-tag [PREFIX]` | off | prepend a quality booster to the prompt (their **Quality Tag**; bare flag uses `Masterpiece`) |
| `--confirm` | off | **required** to spend credits |
| `--task-id` | — | fetch/catalog an existing task instead of creating one |
| `--poll-timeout` | `300` | seconds to wait for a submitted task to finish before giving up (every create path) |
| `--params-json` | — | raw parameters object, submitted as-is — **overrides every other generation flag** (every create path) |

Generated images are tagged `source='api'` — filter to them in the gallery via
**Source → Generated**.

**`--generate --task-id` pointed at a *video* task now files it as a video.** It's an easy
id to mispaste, and a script looping over a mixed list will do it eventually. That used to
drop the mp4 into `images/` with the video flag left blank, so the gallery served it as a
picture: a broken tile with an mp4 behind it, no poster frame, and none of the faststart
remux videos need. The clip is now handed to the video path instead — `videos/`,
`is_video=1`, poster thumbnail, faststart — and the run says so. When the task turned out to
hold *only* video, it also names the direct route (`--generate-video --task-id <id>`); a task
carrying both images and video just collects both. One honest caveat: on that detour the *file*
always arrives, but the metadata is best-effort. A multi-reference task recovers its prompt
and duration; a plain image-to-video one lands with prompt, duration and model blank and
wants a `--backfill-full-meta` pass afterwards.

> **The two upscale methods, and why the flag names look backwards.** PixAI's own dialog
> labels them *Upscale* and *Hires*, but the parameters those two buttons actually send are
> named `enlarge` and `upscale` — so the flags are named after the parameters (what
> `--dump-params` shows you) rather than the buttons. *Upscale*/`--enlarge` runs an upscaler
> network over the finished picture; *Hires*/`--upscale` re-renders it larger and can invent
> new detail. **The maximum ratio is not fixed** — it falls out of an output-size ceiling, so
> the same method offers a bigger ratio on a small image than on a large one (a 1400×784
> image tops out at 1.9× with `--enlarge` but 1.4× with `--upscale`). Ask for more and it is
> clamped down to what your size allows; ask on an image that is already at the ceiling and
> the upscale is dropped rather than submitted as a pointless 1×. The web Generate drawer
> shows the live maximum and the resulting size (`1400×784 → 1952×1096`) as you drag.

---

## Animate an image → video (`--generate-video`)

Turn any catalog image into a short clip (image-to-video). Same preview/confirm safety —
but **video is expensive** (a V4.0 5-second clip is ~27,500 credits, ~50–100× an image),
so the preview shouts the cost, and the actual charge is read back from the server
(`paidCredit`) after it runs and stored in the catalog (`paid_credit`). Clips download
into `videos/` and catalog as `is_video`.

**Web:** the Generate drawer's **Video** tab — pick a source image, set model / duration
(5/6/10/15s; 15 is V4.0-only, see below) / mode (Basic cheaper, Professional), optional
audio, optional end frame for first/last-frame interpolation, then submit (the cost +
free-card check show first).

```bash
# preview (free): prints the exact request + the ~credit cost
python moonglade_backup.py --generate-video --image <media_id> --prompt "she turns slowly toward camera"
# really animate (EXPENSIVE — spends credits):
python moonglade_backup.py --generate-video --image <media_id> --prompt "..." \
    --video-model v4.0.1 --duration 5 --video-mode professional --confirm
# recover a finished clip for free:
python moonglade_backup.py --generate-video --task-id <id>
```

### Video models and shot-mode gating

Seven video engines are selectable (newest first), and they are **not interchangeable** —
each has its own duration cap, free-card eligibility, and which of the Loom's four
[Shot modes](The-Loom#shot-modes) (I2V / FLF / R2V / V2V) it actually supports. The web
drawer's duration picker offers exactly four values — **5, 6, 10, and 15 seconds** — and
enforces the current model's cap (see below); an out-of-range value (e.g. inherited from
an older Loom project) snaps to the nearest one. The CLI's `--duration` is a plain
integer with no enforced choices — pass any of the four to match the drawer's behavior.

| Model (`--video-model`) | Max duration | Free card ever? | Shot modes available |
|---|---|---|---|
| V4.0 Preview (`v4.0`) | 15s | Yes (V4.0 cards) | First Frame · First+Last · Multi-Reference |
| V4.0 Lite Preview (`v4.0.1`, default) | 15s | Yes (V4.0 cards) | First Frame · First+Last · Multi-Reference |
| V3.2 (`v3.2`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 Lite (`v3.0.2`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 (High Consistency) (`v3.0`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 Flash (`v3.0.1`) | 10s | **No — never covered** | First Frame only |
| V2.7 (High Dynamics) (`v2.7`) | 10s | **No — never covered** | First Frame only |

Notes:
- **Multi-Reference (R2V) only works on the V4.0 pair.** First+Last (FLF) also works on
  the three V3.0-generation models. V3.0 Flash and V2.7 only ever offer First Frame
  (I2V) — the drawer hides the mode buttons a model can't do rather than letting you
  submit a combination PixAI would reject.
- **Free cards are V4.0-specific.** V3.0 Flash and V2.7 always cost real credits — the
  drawer's cost badge correctly reads "no card" for them; that's expected, not a bug.
- **15s is exclusive to the V4.0 pair.** Every other model caps at 10s, and the web
  drawer disables + hides the 15s option entirely once you pick a capped model (rather
  than letting you choose it and fail at submit); the CLI has no equivalent guard, so a
  hand-typed `--duration 15` on a non-V4.0 model is on you to avoid.

### Video tuning flags

| Flag | Default | Meaning |
|---|---|---|
| `--tail <media_id>` | — | last-frame image → first/last-frame (FLF) interpolation between `--image` and this |
| `--camera-movement` | unset | `horizontal`/`pan`/`roll`/`tilt`/`vertical-pan`/`zoom`; unset omits it (camera direction can also just go in the prompt) |
| `--audio` / `--audio-language` | off / `english` | generate audio with the clip; the language only matters with `--audio` |
| `--video-prompt-helper` | off | let PixAI expand your video prompt (off by default — the **opposite** of image gen, where the helper is on unless `--no-prompt-helper`) |
| `--video-channel` | `private` | `private` = the site's "Enhanced" channel (Plus/Premium); `normal` otherwise |

## Edit an image with words (`--edit-image`)

Describe a change and let PixAI's Edit model apply it — "make it nighttime", "add a hat".
Source can be a **catalog `media_id`** or a **local file** (uploaded automatically); pass
`--edit-src` more than once for multi-image reference. Results catalog as `source='api'`.

**Web:** the Generate drawer's **Edit** tab — pick the source image(s) from your gallery,
type the change, set resolution/aspect/quality, then submit.

```bash
# preview (free; local files show as placeholders, nothing uploads):
python moonglade_backup.py --edit-image --edit-src <media_id> --prompt "make it nighttime, add snow"
# edit a LOCAL image (uploads it, then edits) — spends credits:
python moonglade_backup.py --edit-image --edit-src "C:\pics\her.png" --prompt "..." --confirm
```

| Flag | Default | Meaning |
|---|---|---|
| `--edit-model` | Edit Pro | edit model id (e.g. Reference Pro's id for reference-style edits) |
| `--edit-resolution` | `1K` | output resolution (`1K`/`2K`/…) |
| `--edit-aspect` | `3:4` | output aspect ratio |
| `--edit-quality` | `medium` | quality tier |

The four are clamped to what the chosen model really supports before submit — e.g.
Reference Pro only offers 2K/4K and has no quality knob, so out-of-range values are
corrected (and shown in the preview) rather than rejected.

**Edits made with a model Moonglade doesn't know locally still get a real name.** It
recognizes PixAI's two edit models by name without asking anyone; anything else — a newer
`modelId` pushed through `--params-json`, or `--task-id` recovering a chat task you made on
PixAI's own site — used to land in the catalog as the literal word "Edit". That was worse
than leaving it blank, because "Edit" *looks* like a resolved name: `--fix-model-names`
counted the row as finished and never came back for it, so it stayed generic forever and
lost which edit model actually made it. Such a row now goes through the same name lookup an
ordinary generation does, and if that lookup can't answer, the row is left blank or holding
the raw id — the two states `--fix-model-names` is built to pick up on a later run.

## Upscale — on the picture, not in the drawer

PixAI upscales an image you already have, so that is where Moonglade puts it. Open any image
and use **↱ Upscale** — from the **Details** page, or from the lightbox, where it opens as a
flyout so you can still see the picture while you choose.

Two methods, and they are genuinely different jobs:

| | **Upscale** (ESRGAN) | **Hires** |
|---|---|---|
| what it does | runs an upscaler network over the finished picture | re-renders it at the larger size |
| result | the same picture, larger | more detail, not just more pixels |
| controls | a choice of 5 upscaler networks | denoising strength and steps |
| ratio | bigger ratios allowed | smaller ratios allowed |
| cost | cheaper | roughly 3× |

**The maximum ratio depends on the picture.** It is worked out from that image's real width
and height against a pixel ceiling, so the panel tells you the real answer for the image in
front of you — "max 2.7× for this picture" — and shows the exact output size as you drag.

**You do not have to pick a model.** Normally the panel fills it in from the image itself,
which is the better answer when it is known — Hires re-renders the picture, so the model that
made it keeps the style. Two cases where it cannot: your catalog has not captured it yet (run
`--backfill-full-meta`, and see [Backing up](Backing-Up)), or you imported the file from your
own computer, in which case PixAI has no record of it and never will. Those upscale anyway,
on the same model PixAI's own upscale uses — their dialog has no model control either. You
can still pick one yourself if you want a different look; it is the same picker the Generate
drawer uses.

The cost is shown before you commit, and a matching free card is applied automatically, the
same as any other generation.

> **In the Generate drawer** you will find **Enhance Details** among the boosters instead.
> That is PixAI's Hires applied to the image you are about to make — the same family of
> settings, but part of the generation rather than something you do to a finished picture.

## Art filters — free, in your browser

**Art filters** are not generations. Each one is two or three gradient overlays with a blend mode
and an opacity, plus an optional brightness/contrast/saturation trim. PixAI's seven come from a
public config endpoint that their own site reads and composites in the browser — which is why
their Filters tab has no Generate button and never quotes a price.

Moonglade does the same thing locally, and adds five of its own. Open the Generate drawer →
**Edit** → **Enhance** → **Open filters**:

| Set | Filters |
|---|---|
| **Moonglade** | Moonglade · Nightfallen · Moonlit Silver · Embercourt · Verdant Grove |
| **PixAI** | M1 – M7 |

The five Moonglade filters are derived from the app's five **skins**, each built from that skin's
own accent and lead colours, so a filtered image reads as the app rather than as a generic wash —
and they stay matched to the skins they came from, because a retinted skin fails the test that
pins them to it. They are also **exact-only**: every blend mode they use has a real CSS and canvas
equivalent, so the saved PNG is the preview, pixel for pixel.

The panel is a comparison. The **original** sits on the left, the **filtered preview** beside it,
and the swatch rail with the strength and angle sliders on the right — judging a filter means
seeing both at once, not toggling one image back and forth. Picking a filter costs **nothing** and
makes **no network request at all**; it works with the connection down.

Four actions sit under the rail:

- **No filter** — clear the preview back to the original.
- **Save to library** — bake the result at full resolution into `imported/`, with a thumbnail and
  a catalog row, exactly as importing any local file does. Nothing is uploaded to PixAI.
- **Send to image gen** — upload the filtered image to PixAI (free, the same handshake as
  **↑ Import**) and load it straight into the Edit tab as the source, so you can generate *from*
  the filtered version. The upload spends nothing; only the generation you then run costs.
- **Publish** — not built yet, and shown disabled with that reason.

Two of the eight blend modes PixAI uses are Photoshop's whole-colour *Darker Color* / *Lighter
Color*, which have no CSS or canvas equivalent; they are rendered with `darken` / `lighten`
(per-channel min/max), so PixAI's M1, M2, M5 and M6 can differ slightly from PixAI's own render
where a gradient crosses the image's hue. Every other filter — including all five Moonglade ones
— is exact.

There is no CLI flag for this — it's a browser-side composite, and the old credit-spending
`--enhance --filter-id` submit was removed rather than kept as a worse way to get the same
pixels.

> **PixAI's one-click *workflow* tools are not available here.** Their tiled upscale,
> background removal, line-art and relight presets run only on pixai.art itself: a task
> submitted with an API key is accepted and queued, then cancelled about an hour later without
> ever being started. There is no `--workflow-id`, and the web drawer's **Enhance** sub-tab
> says the same thing. For hands and faces, use the **Fixer** instead — it goes through a
> different endpoint and works. Plain **Upscale** and **Hires** do work: they're ordinary
> generation settings on the Generate tab, not workflows.

## Multi-reference video (`--reference-video`)

A different video mode (V4.0): drive a clip from **multiple reference images / videos / audio**
instead of a single start frame. You cite each reference in the prompt with `@image1`, `@video1`,
`@audio1` (they map by position). Refs can be catalog `media_id`s or local files (auto-uploaded).

```bash
# preview (free): shows the exact referenceVideo request
python moonglade_backup.py --reference-video \
    --ref-image <id1> --ref-image "C:\pics\pose.png" \
    --prompt "@image1 in the outfit from @image2, slow orbit"
# really generate — a matching V4.0 card is auto-applied (0 credits); --no-card to pay instead:
python moonglade_backup.py --reference-video --ref-image <id1> --ref-image <id2> \
    --prompt "@image1 ... @image2 ..." --confirm
```

| Flag | Meaning |
|---|---|
| `--ref-image` / `--ref-video` | a reference (media_id **or** a local file, uploaded for you), **repeatable** — `@image1`, `@image2`, … |
| `--ref-audio` | a reference — **media_id only**, *not* a local file, **repeatable**. PixAI's uploader takes images and videos only, so there's nothing to upload a bare audio file as. To use audio from your own machine, put it into a video (even just a still image with the audio track) and pass that with `--ref-video`. |
| `--prompt` | cite refs by `@imageN` / `@videoN` / `@audioN` |
| `--duration` / `--video-mode` / `--audio` | as with `--generate-video` (15s uses 3 V4.0 cards) |
| `--confirm` | **required** to submit |

## Upload a local image (`--upload`)

Get a reusable `media_id` for any local file — **free**. Useful to pre-upload once and
reuse the id across edit/video runs.

```bash
python moonglade_backup.py --upload "C:\pics\her.png"     # prints: Uploaded media_id: <id>
```

## Image → prompt (`--suggest-prompt`)

Reverse a prompt out of any image (PixAI's *"Image to prompt"*). Point it at a catalog
`media_id` or a local file (uploaded first, free) and it prints suggested prompts — a
Danbooru-style **tag list** plus one or two **natural-language descriptions**. **Free**,
read-only — no `--confirm`.

```bash
python moonglade_backup.py --suggest-prompt 739411069833281443    # a catalog media_id
python moonglade_backup.py --suggest-prompt "C:\pics\ref.png"     # a local file (uploads first)
```

> **Images only.** This calls PixAI's own image-to-prompt endpoint, which reads back tags
> from a still image — it has no video support, and a video `media_id` returns a clear refusal
> rather than a suggestion (`--suggest-prompt` checks locally before ever reaching the
> network). (The web gallery's own Suggest Prompt button only ever appears on image detail
> pages for exactly this reason.) Point it at an image, not a clip.
>
> The exact catalog `media_id` above is just an example from this repo's own history and
> won't exist in your catalog — swap in any image `media_id` from your own catalog. The
> endpoint is image-only, full stop; it isn't age-limited (an earlier version of this note
> guessed otherwise and was wrong).

Copy a suggestion straight into `--generate --prompt "…"` to riff on an image's style.

## Free cards (`--cards`) — auto-applied

PixAI grants free-generation cards — **kaisuuken** (回数券, "ticket book") — through membership
and events. Each is **locked to one model**.

> **✅ Cards auto-apply — just generate.** On `--confirm`, the tool asks PixAI which of your
> cards matches this generation (the same `check` call the website makes), attaches the
> nearest-expiry one, and that generation costs **0 credits**. The **preview** tells you
> up-front whether it'll be free — and the **real credit cost** (via PixAI's `task-price`
> estimate, which spends nothing):
>
> ```
> FREE: a matching card covers this -- with --confirm it costs 0 credits (saves ~1,600 credits) …
> NO FREE CARD matches -- with --confirm this will cost ~27,500 credits.
> ```

```bash
python moonglade_backup.py --cards        # read-only: your cards, counts, model, expiry
```

Just generate on a model you have a card for — the match is automatic:

| Card | Just run | 
|---|---|
| **Tsubaki.2** | `--generate` (default model) |
| **Edit Pro** | `--edit-image` (default model) |
| **Reference Pro** | `--generate --model 1948514378441961474` |
| **V4.0 video** | `--generate-video` / `--reference-video` (5s = 1 card, 15s = 3) |

Overrides: **`--no-card`** forces paying credits even when a card matches; **`--kaisuuken-id <id>`**
forces a specific card. Cards closest to expiry are used first.

## Contests (`--contests`)

```bash
python moonglade_backup.py --contests                 # live contests (read-only)
python moonglade_backup.py --contests --all-contests  # include ended ones too
```

Lists PixAI's contests — name, dates, entry tag — so you can aim a generation at one.
The web gallery has the same list under **Contests** in the header. Read-only either way.

---

## The Generate drawer (web gallery, v1.9.0)

Everything above also lives in the **web gallery** as a dockable drawer — click **✦ Generate**
in the header. It is **login-tier, not localhost-only**: any signed-in device — local or
elsewhere on your LAN — can open the drawer and spend credits or cards. That's deliberate,
so a tablet or second device can generate too; see [Trust & Safety](Trust-and-Safety) for
what *is* restricted to the server's own machine.

- **Generate** — pick a base model in the pop-out browser (hover any card for a full preview),
  attach **LoRAs with weights** up to your account's own limit (read live from your PixAI
  membership and shown as `LORAS · n/max` — it is not a fixed number, and Generate blocks
  rather than letting you submit over it), aspect/mode/count, live credit cost with the
  free-card check up front.
- **Edit** — instruct edits ("make it night") and the drag-a-box hand/face **Fixer**, in
  sub-tabs over one source image. The third sub-tab, **Enhance**, is where PixAI's seven
  **art filters** live: gradient overlays applied right in your browser, so they cost nothing,
  make no request, and work offline.
  The Fixer shows its live credit cost as soon as you mark a region, and always asks before
  it submits: unlike everything else in the drawer, a fix can't be covered by a free card, so
  it always spends. Fixed images are filed under the name of the image they repaired plus a
  `fix-face` / `fix-hand` marker, so a repair sits next to its original in the folder.
  The two edit models take different numbers of reference images (Edit Pro up to 4,
  Reference Pro up to 10, and the picture being edited counts as one of them), so switching
  from the roomier one to the tighter one can't keep everything you picked. **It now tells
  you what it dropped** — "Only 3 reference images kept … 3 of your 6 references were left
  out" — instead of thinning the strip in silence and letting you submit a paid edit
  believing all six were still attached.
- **Video** — first-frame / first+last / multi-reference shots; pick reference images straight
  from your own gallery (badged `@image1…`, removable, hover to preview); typing `@image1` in
  the prompt turns into a chip; model + duration + audio; live cost shows **FREE + how many
  video cards you have left** when a card covers it.
  Multi-Reference keeps its picks in their own bank, and First Frame / First & Last have
  nowhere to display them — so leaving Multi-Reference empties those slots on screen. It used
  to happen wordlessly, and worst of all when you hadn't asked for it: Multi-Reference only
  runs on the V4.0 pair, so picking any other model switches the mode for you, taking every
  image, video and audio reference out of view with it. **Now it says what carried over** —
  "Still held for Multi-Reference: 4 image refs, 1 video ref and the audio ref. Nothing was
  deleted…" — because nothing *is* deleted: come back to Multi-Reference, on a model that
  offers it, and every pick is still there.
- **Tag Suggestions** — Danbooru-style autocomplete in the **Generate** prompt, the **Generate**
  negative, and the **Edit** instruction (not the Video tab's prompt); **TAB** accepts.
- **Bridges from the gallery**: right-click any thumbnail (Edit / Send to Video / Copy media id),
  the same buttons in the lightbox, and multi-select → **Send to Video** in the bulk bar.
- Results are downloaded and cataloged automatically (`source='api'`; videos into `videos/`),
  so everything you make lands in your own library the moment it finishes.

**The numbers are bounded on the server, and you're told when one moved.** Because the
drawer is login-tier, the sliders and number boxes in your browser are the only limit a
well-behaved client honours — and anything POSTing to `/api/generate` by hand honours none,
so a width of 999,999,999 or 999,999 steps used to go straight through to PixAI and be
priced at whatever that produced. Width and height are now held to 64–4096, steps to 1–150,
CFG to 1–30 and count to 1–4, the same bounds the drawer's own controls carry. When a clamp
actually fires the response says so and the drawer raises it — "Settings were adjusted
before submitting … steps 200 → 150 — this generation used the adjusted values." — because
that submit is already made and already charged, and quietly billing you for a different
generation than the one you configured is worse than the absurd number being refused. You
can meet this from the drawer itself, not only from a hand-rolled request: a model that
publishes wider limits of its own widens the browser field to match.

**The Loom** (`/loom`) is the storyboard for multi-clip video — acts, shots, cast,
frame handoff, and per-shot **Generate** on the same engine. It's a fixed 4-region shell
(Cast & Assets / Footage on the left, the Acts & Shots board center, the Generate drawer
right, a Timeline drawer across the top) with a "draft generation" mode for exploring a
look before assigning it to a shot, multiple independently-saved storyboards, project-wide
Draft-quality rendering, and a two-tier project export. Full manual: `docs/LOOM.md` (or the
? button on the page).

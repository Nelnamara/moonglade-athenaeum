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
| **High priority** | `priority` | off (500, cheaper) by default; on = 1000 (faster, more credits) |

Submit and the result drops straight into your catalog, tagged `source='api'`, and
appears in the gallery.

### The model-vs-version-id gotcha
`createGenerationTask` needs a model's **version id**, not its model id. A model page
URL (`pixai.art/model/<id>`) gives the *model* id, which generation rejects
("Invalid modelId"). The drawer's **model search** (and the CLI's `--list-models`) hand
you the correct version id — prefer those.

### Modes are model-specific
Lite/Standard suit older SD models; Pro/Ultra are for newer types. The drawer's Mode
picker doesn't filter by model, so picking an unsupported combination shows an error on
submit rather than falling back (a rejected submit still costs no credits) — pick
**Auto** if you're not sure. The CLI's `--mode` (below) does auto-fall-back and retry
once on an unsupported mode.

### LoRAs are add-ons, not base models
A LoRA can't be the **base** model. The base picker excludes LoRAs; add them via the
**LoRAs** row.

## On the CLI

```bash
# preview only (no credits):
python pixai_gallery_backup.py --generate --prompt "a night elf druid, moonlit grove"

# really generate (spends credits):
python pixai_gallery_backup.py --generate --confirm \
    --prompt "..." --negative "lowres, text" \
    --model 1983308862240288769 --batch-size 1 \
    --mode standard --lora 1686550608832816741:0.7

# find model / LoRA version ids:
python pixai_gallery_backup.py --list-models "anime"

# recover an already-created task by id (no new credits):
python pixai_gallery_backup.py --generate --task-id <id>
```

| Flag | Default | Meaning |
|---|---|---|
| `--prompt` / `--negative` | — | the prompts |
| `--model` | Tsubaki.2 | model **version** id |
| `--lora VERSIONID:WEIGHT` | — | repeatable |
| `--mode` | `auto` | `auto`/`lite`/`standard`/`pro`/`ultra` |
| `--priority` / `--high-priority` | `500` | 500 = standard (cheaper), 1000 = high |
| `--no-prompt-helper` | off | use the prompt literally |
| `--width`/`--height`/`--steps`/`--cfg`/`--batch-size`/`--seed` | 512/512/25/7/1/random | |
| `--confirm` | off | **required** to spend credits |
| `--task-id` | — | fetch/catalog an existing task instead of creating one |
| `--poll-timeout` | `300` | seconds to wait for a submitted task to finish before giving up (every create path) |
| `--params-json` | — | raw parameters object, submitted as-is — **overrides every other generation flag** (every create path) |

Generated images are tagged `source='api'` — filter to them in the gallery via
**Source → Generated**.

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
python pixai_gallery_backup.py --generate-video --image <media_id> --prompt "she turns slowly toward camera"
# really animate (EXPENSIVE — spends credits):
python pixai_gallery_backup.py --generate-video --image <media_id> --prompt "..." \
    --video-model v4.0.1 --duration 5 --video-mode professional --confirm
# recover a finished clip for free:
python pixai_gallery_backup.py --generate-video --task-id <id>
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
python pixai_gallery_backup.py --edit-image --edit-src <media_id> --prompt "make it nighttime, add snow"
# edit a LOCAL image (uploads it, then edits) — spends credits:
python pixai_gallery_backup.py --edit-image --edit-src "C:\pics\her.png" --prompt "..." --confirm
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

## Enhance an image (`--enhance`) — one-click PixAI workflows

Run one of PixAI's own preset enhance tools on an image: a **panelplugin workflow**
(`--workflow-id` — face fix, upscale, background removal, and similar one-click tools) or an
**art filter** (`--filter-id`). Source is a catalog `media_id` or a local file (auto-uploaded on
`--confirm`). Preview-only until `--confirm`, same as every other spend-capable command here.

**Web:** the Generate drawer's **Edit ▸ Enhance** sub-tab lists PixAI's own curated workflow
shelf and a search box over the rest of its ComfyUI catalog — that's the easiest way to find a
real `--workflow-id`/`--filter-id` without guessing. `--dump-params` off a real enhance task
(recovered via `--task-id`) also prints the exact ids and shape it used.

```bash
# preview a panelplugin workflow (e.g. an upscale) on a catalog image:
python pixai_gallery_backup.py --enhance --src <media_id> --workflow-id <id>
# apply an art filter, with strength, spending credits:
python pixai_gallery_backup.py --enhance --src <media_id> --filter-id filter-v1-m2 --strength 0.77 --confirm
```

> **No cost preview.** Unlike every other spend-capable command in this file, `--enhance` has
> no `--price`-style estimate before `--confirm` — PixAI's own cost-preview endpoint doesn't
> cover this task family. Preview mode (no `--confirm`) still shows you exactly what would be
> submitted, so you can sanity-check the workflow/filter id and source image first.

## Multi-reference video (`--reference-video`)

A different video mode (V4.0): drive a clip from **multiple reference images / videos / audio**
instead of a single start frame. You cite each reference in the prompt with `@image1`, `@video1`,
`@audio1` (they map by position). Refs can be catalog `media_id`s or local files (auto-uploaded).

```bash
# preview (free): shows the exact referenceVideo request
python pixai_gallery_backup.py --reference-video \
    --ref-image <id1> --ref-image "C:\pics\pose.png" \
    --prompt "@image1 in the outfit from @image2, slow orbit"
# really generate — a matching V4.0 card is auto-applied (0 credits); --no-card to pay instead:
python pixai_gallery_backup.py --reference-video --ref-image <id1> --ref-image <id2> \
    --prompt "@image1 ... @image2 ..." --confirm
```

| Flag | Meaning |
|---|---|
| `--ref-image` / `--ref-video` / `--ref-audio` | a reference (media_id or local file), **repeatable** — `@image1`, `@image2`, … |
| `--prompt` | cite refs by `@imageN` / `@videoN` / `@audioN` |
| `--duration` / `--video-mode` / `--audio` | as with `--generate-video` (15s uses 3 V4.0 cards) |
| `--confirm` | **required** to submit |

## Upload a local image (`--upload`)

Get a reusable `media_id` for any local file — **free**. Useful to pre-upload once and
reuse the id across edit/video runs.

```bash
python pixai_gallery_backup.py --upload "C:\pics\her.png"     # prints: Uploaded media_id: <id>
```

## Image → prompt (`--suggest-prompt`)

Reverse a prompt out of any image (PixAI's *"Image to prompt"*). Point it at a catalog
`media_id` or a local file (uploaded first, free) and it prints suggested prompts — a
Danbooru-style **tag list** plus one or two **natural-language descriptions**. **Free**,
read-only — no `--confirm`.

```bash
python pixai_gallery_backup.py --suggest-prompt 739411069833281443    # a catalog media_id
python pixai_gallery_backup.py --suggest-prompt "C:\pics\ref.png"     # a local file (uploads first)
```

> **Images only.** This calls PixAI's own image-to-prompt endpoint, which reads back tags
> from a still image — it has no video support, and a video `media_id` returns a clear refusal
> rather than a suggestion (`--suggest-prompt` checks locally before ever reaching the
> network). (The web gallery's own Suggest Prompt button only ever appears on image detail
> pages for exactly this reason.) Point it at an image, not a clip.
>
> The exact catalog `media_id` above is just an example from this repo's own history — PixAI's
> endpoint can fail on sufficiently old media even when it's a real image, so don't be
> surprised if that specific number doesn't reproduce; swap in any recent image `media_id`
> from your own catalog.

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
python pixai_gallery_backup.py --cards        # read-only: your cards, counts, model, expiry
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
python pixai_gallery_backup.py --contests                 # live contests (read-only)
python pixai_gallery_backup.py --contests --all-contests  # include ended ones too
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
  attach up to 6 **LoRAs with weights**, aspect/mode/count, live credit cost with the free-card
  check up front.
- **Edit** — instruct edits ("make it night"), the one-click **Enhance** workflow catalog, and
  the drag-a-box hand/face **Fixer**, in sub-tabs over one source image.
- **Video** — first-frame / first+last / multi-reference shots; pick reference images straight
  from your own gallery (badged `@image1…`, removable, hover to preview); typing `@image1` in
  the prompt turns into a chip; model + duration + audio; live cost shows **FREE + how many
  video cards you have left** when a card covers it.
- **Tag Suggestions** — Danbooru-style autocomplete in the **Generate** prompt, the **Generate**
  negative, and the **Edit** instruction (not the Video tab's prompt); **TAB** accepts.
- **Bridges from the gallery**: right-click any thumbnail (Edit / Send to Video / Copy media id),
  the same buttons in the lightbox, and multi-select → **Send to Video** in the bulk bar.
- Results are downloaded and cataloged automatically (`source='api'`; videos into `videos/`),
  so everything you make lands in your own library the moment it finishes.

**The Loom** (`/loom`) is the storyboard for multi-clip video — acts, shots, cast,
frame handoff, and per-shot **Generate** on the same engine. It's a fixed 4-region shell
(Cast & Assets / Footage on the left, the Acts & Shots board center, the Generate drawer
right, a Timeline drawer across the top) with a "draft generation" mode for exploring a
look before assigning it to a shot, multiple independently-saved storyboards, project-wide
Draft-quality rendering, and a two-tier project export. Full manual: `docs/LOOM.md` (or the
? button on the page).

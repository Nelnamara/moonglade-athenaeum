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
| **Frame** | `width`/`height` | a **Portrait \| Landscape** switch over eleven ratios (1:1 · 5:4 · 9:7 · 4:3 · 3:2 · 5:3 · 16:9 · 2:1 · 21:9 · 3:1 · 4:1). On a model with PixAI's own size tiers (Tsubaki.3: **XL · L · M**) each tier reads PixAI's live sizes; elsewhere the long-edge stops stay. A custom W × H is held to your account's limit. The size line under it is exactly the size that is sent |
| Steps / CFG / Count / Seed | the obvious params | blank seed = random; dims rounded to /8 — to /16 on DiT models (Tsubaki and friends), held to the model's own size range |
| **Profile** / **Mode** | `inferenceProfile` | on a model with profiles, the rows under the model read PixAI's live list with each one's price over the default (Tsubaki.3: **Pro**, **Ultra +500**); a members-only row reads *Members* for a non-member and can't be picked. Other models keep the Auto · Lite · Standard · Pro · Ultra bars |
| **Creativity** / **Prompt helper** | `promptHelper` | on Tsubaki.3, three stops: **As written** (off) · **Light touch** (low) · **Embellished** (medium, the default). Elsewhere the prompt helper is on or off |
| **High priority** | `priority` | off = Turbo (500) if your membership covers it, otherwise standard (0) — both free; on = High (1000), faster and **costs extra credits** |

A control the picked model does not take reads **disabled** and is not sent: Face Fix and
Enhance Details on Tsubaki.2, Tsubaki.3, Flash and community-trained DiT models; Quality Tag on
any model version that publishes no quality tag of its own (Tsubaki.2, Tsubaki.3, Flash and
some SDXL models); the negative prompt on Tsubaki.3 Flash. The drawer reads this off the
model's newest version. On an older version picked from the version list, Face Fix, Enhance
Details and the negative box can stay live and the size line keeps the /8 rule. The server
still drops or moves what that version does not take, and the cost badge names it before you
spend.

Whenever the server adjusts a request (a size moved onto the model's grid, a field the model
ignores), the cost badge names the change **before** you spend.

### Tsubaki.3: context images and @image prompts

On Tsubaki.3 and Tsubaki.3 Flash the settings' first panel is **MODEL & INPUTS**, and a
**LoRAs | Context images** switch takes the place of the single reference slot (other models
keep the reference slot and its strength slider). Each side keeps its own picks; switching
never deletes anything.

- **Context images:** up to 3 (PixAI's live limit), from your history, the gallery or an
  upload. Name them in the prompt as **@image1**, **@image2**, **@image3** — type **@** and pick
  one from the menu (on a phone the choices sit as a row of chips under the prompt). A chip is
  one token: backspace removes it whole, and it is sent as the plain text `@image1`.
- Remove a picture and the chips **renumber**; a chip that pointed at the removed picture turns
  peach and reads *no image*, and Generate waits until you fix or delete it.
- With context images, **LoRAs, recipes, the colour palette and the negative prompt are held**:
  dimmed, marked *Held · not sent with context images*, and restored the moment you switch back.
  The first switch while any of them is set asks first. **Unlimited Mode** doesn't run with
  context images, and **creativity** is set to Embellished by them.
- The frame starts on **Auto**: the size follows @image1's own shape ("✦ Output size W × H ·
  from @image1"). Picking a ratio or an orientation leaves Auto.
- The cost badge names what the pictures add: "2 context images +1,800 · not Unlimited". When
  you pick Ultra it adds "profile Ultra +500". Both are PixAI's own prices for this request.

**Edit with Tsubaki.** Right-click a picture (or open its Details on a phone) and choose
**Edit with Tsubaki**: the Image tab opens on Tsubaki.3 with that picture as @image1 and the
prompt started as "Use @image1 …". Nothing is spent until you press Generate. The Edit card is
unchanged (Edit Pro and Reference Pro are PixAI's own edit models).

**The Lightbox edit bar.** Every still picture shows **Describe your edits…**
over the foot of the Lightbox (on a phone, a bar under the picture). Type the change and press
↵: it sends a Tsubaki.3 run with that picture as @image1, your words as the prompt, the dock's
profile and an Auto size — no LoRAs, recipes, palette or negative. The price shows in the bar
before you send, and the run joins the dock's reel and the Activity tray while the Lightbox stays
open. **E** jumps to the bar; **Esc** leaves it (a second Esc closes the Lightbox).

### Colour palette

Tsubaki.3 and Flash can steer a picture's colours with a **colour palette** — up to three groups
(overall · background · character), each 1 to 12 colours with a share of the whole. The drawer's
**Palette** row (the dock's Tuning column; the phone's Advanced screen) shows the palette in use
and opens the palette window:

- **Library** — PixAI's own palettes, each a cover picture with its colour strip. Pick one and
  **Use palette**, or **Customise** it into your own.
- **Custom** — your saved palettes, kept with your Moonglade account (they are not saved to
  PixAI). **+ New colour palette** opens the editor.
- **The editor** — turn each group on or off (overall or background must stay on; turning one on
  starts it with six even colours), drag the dividers between colours to trade their shares,
  change a colour, its share, its order or the number of colours in the list below, replace the
  colours with a Library palette, or **Extract from image** (a gallery picture or an upload — read
  in your browser, nothing is uploaded) to fill the group you are on. The preview card repaints
  as you go. **Save & apply** saves it to Custom and uses it.

A palette is sent only to a model that takes one, and never with a context image: in either case
the row says **Held** and the palette stays picked for when it applies again. It does not change
the price.

### Recipes

A **recipe** is PixAI's saved bundle of generation inputs (prompt words, LoRAs, pictures) made
for one kind of model. The **RECIPES** row sits in the settings' first panel under the LoRAs |
Context images switch (on a phone, under the LoRAs on the Create screen). **+ Browse** (or
**browse ›**) opens the recipe picker — the market, your Sets, Mine and History, plus a
**Style code** lookup that finds the recipe an old style code became — and **+ Add** puts a
recipe in the row. The command palette's **Browse recipes** opens the full-size market, and
**⁂ Make a recipe** in the Lightbox starts the recipe creator from that picture.

- Up to **10** recipes, applied in the row's order; **×** removes one. The row is remembered with
  your Moonglade account.
- A recipe beside a LoRA warns (*A recipe beside a LoRA can fight it*) but still sends.
- A recipe that doesn't fit the request — made for another model, no longer available, for the
  author's followers only, a prompt that would run too long, or refused by PixAI when the price
  was checked — turns **peach with "!"**, its reason on hover, and Generate waits until you fix
  or remove it.
- With context images the row is **held**: dimmed, *Held · not sent with context images*, and
  sent again when you switch back to LoRAs.
- On Tsubaki.3, recipes run **creativity one step lower**, as PixAI's own site does: Embellished
  runs as Light touch and Light touch as As written. The cost badge names the change.
- The cost badge prices the request **with** its recipes. If PixAI can't price it, the badge
  says why (or *couldn't verify the price with these recipes*) and never reads FREE.

Submit and the result drops straight into your catalog, tagged `source='api'`, and
appears in the gallery. Submitting doesn't lock the button — PixAI itself runs
generations in parallel, so you can queue up several in a row (Generate, Edit, Enhance,
Fix, and the Video tab all work this way) and each one tracks and reports its own result
independently.

### Several at once: variables, Random and Matrix — and the one confirm

**Anything that sends more than one generation asks first, once.** A batch of 2–4, a Random
run and every Matrix run open one confirm card under the prompt: how many, the total credits
(PixAI's own price for what will actually be sent, checked on the server) and how many free
cards cover it. **Cancel · nothing is sent** is exactly that. There is no "don't ask again".
A single picture sends as it always has, with no confirm.

**Variables in the prompt.** `{silver|cobalt|ember}` is a variable: each option is one value.
Only braces with a `|` inside make a variable — ordinary braces like `{masterpiece}` or
`{{best quality}}` are plain prompt text and are sent exactly as you typed them, and so is a
backslash (a kaomoji's `\_` stays). `__poses__` reads one of your **saved lists** (the
**Lists ▾** button in the composer's header beside **Presets**: a name, one item per line,
saved with your Moonglade account so the phone sees them too).
Variables work in the prompt only; the negative is sent as typed. They are tinted in the line
under the prompt, and anything that can't be read — a `{` with a `|` after it that never
closes, a variable inside other braces, an empty `{ | }`, a list you don't have — is tinted
peach and blocks Send until you fix it. To send a `{a|b}` or a `__name__` as plain text, put a
backslash before it: `\{a|b}`, `\__name__`.

- **Random** draws one value per picture, ×1–4, from the run seed (the Seed field when it holds
  a number, otherwise a draw of its own that **⚄ Reroll** changes), so the same prompt, settings
  and seed give the same run again. Each picture is its own task and its own run.
- **Matrix** sends every combination, one picture each, queued one after another — at most 24;
  over that, Send says *narrow an axis* and nothing goes. The reel shows a matrix as a grid:
  the last variable across, the rest down. **Free cards never cover matrix cells** — a card
  belongs to a model and a function.

The dock previews what each picture will get before you send. After Go, the pictures go out
one at a time; if PixAI refuses one (moderation, a recipe that doesn't fit that cell's
prompt) the rest are **not** sent and the result line says which cell and why. A cell whose
answer never came back reads *may have started — check the Activity tray*; nothing is ever
re-sent on its own. If the price, your free cards or anything about the request changed
between the confirm and Go, nothing is sent and the confirm comes back with the new numbers.

Reusing a run from the reel or History puts back its **template** (the variables, Random or
Matrix, the count and the seed), not just one resolved prompt. An older picture's prompt comes
back with any `{a|b}` or `__name__` in it escaped, so sending it again sends exactly the same
text.

**Inspect `{ }`** (beside the snippets button, on each finished tile in the reel, and under **⋯**
on a picture's record page) shows the
exact request a picture was — or will be — sent with, after the variables were filled in, with
the template and the drawn values beside it. The API key, cookies and session tokens are
removed from it on the server, never merely hidden. **Copy JSON** copies it; **Copy as CLI**
copies the matching `python moonglade_backup.py --generate …` command, quoted for the shell the
server runs in — PowerShell on Windows, bash elsewhere, named beside the button (not the old
Command Prompt, cmd.exe, where its quoting doesn't hold). It never includes `--confirm`, so pasting it previews
first; a request the CLI's flags can't say (context images, recipes, a palette, creativity)
copies as `--params-json`.

### Your defaults, ↺ Last, Presets and quick picks

These live with your Moonglade account, so the phone has the same ones. **Nothing is saved just
by opening the dock** — each of them is written by a click of your own, or by a send that
PixAI accepted.

- **A default negative for each base family.** Type a negative, then press **☆ Set as default**
  on the NEGATIVE row (the ▲ settings must be open); the button then reads **★ Default · DiT**
  (or SDXL, Pony, Illustrious, Flux — whichever family the model belongs to), and pressing it
  again clears that family's default. When you pick a model, the negative fills in with its
  family's default **only if the box is empty or still holds the previous family's default** —
  a negative you typed yourself is never replaced. A model whose author ships a preset still
  applies it, and its note says the preset replaces your default. On the phone it is the same
  row under Create → Advanced.
- **↺ Last** refills the composer from your last **successful** send — model, LoRAs and their
  weights, the prompt template, negative, frame, count, steps, CFG, toggles and the seed. It is
  greyed until you have sent something, and it never sends.
- **Presets ▾** saves the composer as a named preset: the same things as ↺ Last, **except the
  seed**, up to thirty. Picking one fills everything in and says nothing was sent; if its model
  is no longer available the rest is still filled and the note says so. ✕ deletes one. Presets
  hold the Image tab only. On the phone, ↺ Last and Presets are two chips above the prompt and
  presets open as a sheet.
- **Quick picks** are the MODELS and LORAS rows above the prompt: your last three sends' models
  and LoRAs plus the ones you ★ (the ☆ in the corner of a card in the model and LoRA pickers),
  six to a row, then **+ more** into the picker. A model chip switches the model the same way
  the picker does. A LoRA chip adds that LoRA at the weight you last used, and tapping it again
  removes it; a LoRA for another model family is dimmed, with the reason in its tooltip. On the
  phone they are one scrolling row of large chips, models then LoRAs.

**On the phone** the prompt has a small toolbar: **{ }** puts a variable at the cursor for you
to type over, and **Lists** opens your saved lists as a sheet. Variables are tinted the same
way. Random works on the phone; **setting up a Matrix is done on a computer**, but a matrix's
results open as a grid from **⋯ → View this matrix as a grid** on any of its pictures' records,
and **⋯ → Inspect the request** shows the exact request with **Copy JSON**.

### Tsubaki.3 Unlimited Mode

When your account holds PixAI's **Unlimited Mode** for Tsubaki.3 (a time-limited grant you
claim on PixAI's own site — the app only reads it, it never claims), picking Tsubaki.3 shows a
**∞ Tsubaki.3 Unlimited Mode** row under the model with the days you have left, in the
Generate drawer's settings and on the phone Create screen. The **?** beside the name lists the
rules.

Switch it on and an **"∞ Unlimited Mode is on"** band sits over the prompt, with **Turn off**
beside it, and the cost badge reads **Free ∞**: the picture costs nothing and no free card is
used. Unlimited Mode runs on PixAI's own terms, so the drawer holds the rest to match:

- **Mode** is fixed on Pro, the **count** on 1, and **High priority** is off.
- Sizes over **1792 × 1792** read disabled (checked on the size that is actually sent, after it
  snaps onto Tsubaki.3's grid). A reference picture can't be used.
- Switching it on is refused while a reference picture is set or the size is too large; the
  switch and the line under it say which.
- **One at a time:** while an Unlimited Mode picture is still being made, Generate waits. One
  started on PixAI's own site isn't visible to the app — PixAI refuses the second one, and
  nothing is spent.

Anything Unlimited Mode doesn't allow is **refused before sending**, in one plain sentence on the
cost badge — never quietly changed, never turned into a paid generation, and never retried as
an ordinary one. If PixAI itself refuses the task, the result line says so and nothing was
spent. The switch stays on until you turn it off, even across a model change; on a model
without Unlimited Mode the badge shows the refusal. When the grant ends the switch is no longer
offered. `READ_ONLY` still refuses first.

### The model-vs-version-id gotcha
`createGenerationTask` needs a model's **version id**, not its model id. A model page
URL (`pixai.art/model/<id>`) gives the *model* id, which generation rejects
("Invalid modelId"). The drawer's **model search** (and the CLI's `--list-models`) hand
you the correct version id — prefer those.

### Modes are model-specific
Lite/Standard suit older SD models; Pro/Ultra are for newer types. A model that lists its own
profiles shows only those (the rows under the model), and a mode it doesn't offer is **refused
before sending** rather than quoted and swapped. If PixAI refuses a profile the model *does*
list — Ultra on an account without the membership — the app says so and **does not** resubmit
it on Pro: that would be a different picture at a different price than the one you saw. Where
the app can't read a model's profile list, the older behaviour still holds: an unsupported Mode
falls back to the model's default and resubmits once (a rejected submit costs no credits), as
the CLI always has (see `--mode` below). If you ever see the raw error text itself instead of a
friendly message, see [Troubleshooting](Troubleshooting#unknown-inferenceprofile-).

### LoRAs are add-ons, not base models
A LoRA can't be the **base** model. The base picker excludes LoRAs; add them via the
**LoRAs** row.

### Trigger words go in by themselves
Most LoRAs only wake up when their **activation words** are in the prompt — attach one
without them and it quietly does nothing to a picture you paid for. So picking a LoRA
writes its words into the prompt for you, on the desktop dock and on the phone alike, the
same way PixAI's own composer does.

It won't write a word that's already there, so picking, un-picking and re-picking a LoRA
never leaves you with the same token three times. If you delete the words on purpose and
want them back, the **+words** button on the LoRA's row (its chip, on the phone) puts them
in again — and it's harmless to press when they're already in place.

**Removing a LoRA takes its words back out**, the same way PixAI does — so un-picking one
doesn't leave you generating against activation words for a LoRA that isn't attached any
more. A word that a LoRA you're *still* using also needs is left alone: if two of them
share an activation word, dropping one never disarms the other. Only the words themselves
go; the rest of your prompt closes up around the gap and is otherwise untouched. If you'd
reworded a word, or written it into a sentence of your own, that's your writing and it
stays — and **+words** puts a LoRA's words back whenever you want them.

One thing it deliberately doesn't do: **Remix doesn't add or remove anything** — restoring
a recipe gives you the prompt that actually made the picture, word for word.

### Finding a model or LoRA
The picker opens on **Market** — everything on PixAI. Two other places to look sit next
to it:

- **Bookmarked** — whatever you have bookmarked on pixai.art. It reads your live
  bookmarks, so anything you bookmark on their site shows up here.
- **Mine** — LoRAs you trained yourself. LoRAs only; you don't author base models.

On Market you can also narrow by **category** (character, animal, style, realistic, pose,
clothing, background, detail, other), by **when it was posted**, by **source**
(PixAI-trained or brought in from elsewhere), and to models that **allow commercial use**.

Whatever the tab, the app browses the market the way your own browser does, so a search
returns the same rows pixai.art returns for your account — including LoRAs the site only
shows a signed-in adult account. If a search that fills pages on the site comes back empty
here, that is a bug, not a setting.

The filter row disappears on **Bookmarked**, and that is deliberate rather than an
oversight: PixAI's bookmark list only supports a search term, so a category or date
control there would look like it worked and quietly do nothing. Search still works, and if
you have a base model selected the list is still limited to LoRAs that fit it.

**If Bookmarked looks emptier than you expect**, that is usually the compatibility filter
rather than a fault — with a base model selected, only LoRAs matching its architecture are
shown. Clear the base model to see all of them.

### Training your own LoRA

**Train** in the side rail (on the phone: **Train a LoRA**) trains a LoRA on PixAI. Opening it
only reads: nothing is sent to PixAI until you press a button that says what it does.

It opens on a chooser: **Basic training** (about 30 minutes, good for your first LoRA),
**Advanced training** (about 1 to 2 hours: you check the description PixAI writes for every
image) and **Runs**. While something is training, a strip on top shows the newest run with
its progress, and **View ›** opens Runs. Each wizard has **‹ Back** to the chooser and a link
across to the other one.

The phone has the same flows, one step per screen: the step you are on shows at the top
right, and the **‹** at the top goes back one step (from the chooser it closes the screen).
Image sources open as one sheet from the bottom (Upload, From history, Import a dataset), the
set is a three-column grid, and a long press takes a picture out. Starting a run on the phone
still asks in the **Queue training run** sheet, whose button names the price.

**Basic training** is PixAI's own three steps:

1. **Choose a goal** — Character, Art style, Outfit or Something else.
2. **Add images** — from **Upload** (your device), **From history** (your library, Grouped by
   generation or All pictures, with the library's search; it keeps loading as you scroll) or
   **Import a dataset** (the image sets of your earlier Basic runs, with their counts; a set
   that won't fit what's left of 100 is dimmed, and importing one fills in its old name,
   trigger words and goal where those are still empty). Everything lands in one grid, each
   picture once, with a mark for where it came from.
3. **Review and start** — the LoRA's name, its trigger words and the base model, then a
   summary with the price, the time it takes, and **Start training**.

- **Base models** are PixAI's own training list, one tab per architecture — DiT.3 (Tsubaki.3,
  marked Recommended and selected first), DiT.2 (Tsubaki.2), DiT.1, SDXL and SD 1.5 — read from
  PixAI when the panel opens, with a built-in copy of that list if PixAI can't be reached.
- **What it costs** is on the summary before you press Start, with the base's normal price
  struck through when the run is free. A run is free when your membership still has free
  trainings left (they only count while you are a member), or when you hold a training free
  card for that base — the card is used up by the run. If your free cards can't be checked at
  that moment, the run is quoted as paid. If you have both, this app uses one of your free
  trainings and keeps the card (PixAI's own page would use the card). Reusing a whole earlier
  set exactly as it was (imported, nothing added or taken out) is priced at PixAI's lower rate
  for reusing a dataset, and the summary says so.
- **Start training asks once.** It first gets PixAI's price for exactly this run (nothing is
  spent), then shows one confirm whose button names that amount — for a paid run you also tick
  that you will spend it. Change the base, the images or any field and the confirm closes;
  a run is never started at a price you did not see and tick. If PixAI doesn't answer clearly
  after you confirm, the panel says the run **may have started**: check Runs before starting
  it again (starting the same run again is refused for a while, so a double click can't charge
  twice).
- **Trigger words** are tidied the way PixAI tidies them before they are sent: line breaks
  become commas, extra spaces and repeated commas are removed, and everything is lowercased.
  Up to 256 characters; a DiT.2 or DiT.3 base needs at least 30. The line under the box shows
  the tidied length when it is too short or too long, counted the way PixAI counts it (an
  emoji counts as 2).
- **Images**: between 10 and 100, PNG, JPG or WebP, each at least 512 pixels on both sides and
  no longer than 3:1. An upload that fails the rule never leaves your computer and is listed
  with its reason. A picture from your library that fails it is marked in the grid with its
  reason in peach and is not counted or sent — take it out or add others. An image whose size
  your library doesn't know is listed as not checked.
- **If PixAI has paused new training runs**, starting one is refused (nothing is spent) and,
  when PixAI says, the message names when it expects to be back. Runs already training carry
  on.

**Advanced training** is PixAI's own advanced steps:

1. **Set up** — the LoRA's name, its trigger words (at least 30 characters and up to 256 once
   tidied; the line under the box counts them, and warns about double spaces or a space at the
   start or end, which are taken out before sending), what you are training, and the base:
   **Tsubaki.3** (Recommended) or **Tsubaki.2**. **Next · creates a draft** is the one button
   that creates the draft on PixAI (free), and the base can't be changed after that.
2. **Descriptions** — add the images here (**Upload** or **From history**, 10 to 100, the same
   picture rule as Basic; adding or taking out a picture changes the draft on PixAI, free).
   PixAI then describes every image: **Describe automatically (N images)** shows PixAI's own
   price for describing this set (it is charged per image, when it runs) and is the only way
   in — PixAI has no way to write the descriptions yourself before it has described them. One
   press sends exactly the amount on the button (on the phone the button opens a sheet that
   asks once); if PixAI's price moved in the meantime, nothing is charged and the new price
   is shown. Once they are described:
   - the grid shows every image with the start of its description, with filters for **All**,
     **Auto**, **Edited** and **Not described yet**, and an edited one has a small lavender dot;
   - **⌕ find** with **replace with…** and **Replace**, or a tag with **+ tag** and **− tag**,
     change every described image (or only the ones you ticked), and **Restore automatic
     (selected)** puts PixAI's own words back;
   - a tile (or **⤢ Focus**) opens one image with its whole description, up to 1,000
     characters, with **Restore automatic**; **← →** or **J / K** move between images and
     **Esc** goes back to the grid.
   Edits save by themselves a moment after you stop typing, one at a time, and the buttons
   below wait for them. **Next: parameters** stays off until every image is described.
3. **Parameters → start** — the length, learning rate and detail capacity are shown at PixAI's
   own defaults (325 steps, learning rate 6e-4, rank 64, and gradient accumulation 2) and are
   locked for now, as they are on PixAI's own page. PixAI's price for the run and the time it
   takes are shown, and **Start training** names that price; one press sends exactly it.

A draft keeps its place on PixAI: **Continue** in Runs opens it at its descriptions. Opening
a draft only reads it.

**Runs** lists your training runs, newest first, with filters for All, Drafts, Done and
Failed. Each row shows the run's status — a draft and the step it stopped at, Queued,
Training with PixAI's percentage (and a moon that fills as it goes), Done or Failed (PixAI's
reason on hover) — and one thing you can do with it:

- **Continue** opens an Advanced draft at the step it stopped at.
- **View** opens a queued or training run's progress.
- **Publish** (a finished Advanced run) opens a sheet: Private or Public, and for a public
  LoRA whether it joins LoRA rebates. Under **This can't be undone** each permanent
  consequence is its own line to tick — you can no longer delete the LoRA, and a public one
  can't go back to private — and Publish stays off until every line is ticked. Joining
  rebates can't be undone either. A private LoRA's **Private** label opens the same sheet to
  make it public later.
- **Retry** (a failed Advanced run) starts a new run on the same set: it asks PixAI's price
  first and the confirm's button names it; nothing is spent until you tick and confirm.
- **Use** adds a trained LoRA to the Generate dock (on the phone, to the Create tab), trigger
  words and all. If the dock was on **Context images**, it switches back to **LoRAs** so the
  LoRA is sent; your context images stay in their slots, held, for when you switch back.
  Nothing is generated until you press Generate.

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
free-card check show first — for a video that check counts **tickets**, see
[Free cards and videos](#free-cards-and-videos) below).

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

Nine video engines are selectable (newest first), and they are **not interchangeable** —
each has its own duration cap, free-card eligibility, and which of the Loom's four
[Shot modes](The-Loom#shot-modes) (I2V / FLF / R2V / V2V) it actually supports. The web
drawer's duration picker offers exactly four values — **5, 6, 10, and 15 seconds** — and
enforces the current model's lengths (see below); an out-of-range value (e.g. inherited from
an older Loom project) snaps to the nearest one. The CLI's `--duration` is a plain integer
that snaps the same way, to the nearest length the chosen model takes.

| Model (`--video-model`) | Max duration | Free card ever? | Shot modes available |
|---|---|---|---|
| V4.0 Preview (`v4.0`) | 15s | Yes (V4.0 cards) | First Frame · First+Last · Multi-Reference |
| V4.0 Lite Preview (`v4.0.1`, default) | 15s | Yes (V4.0 cards) | First Frame · First+Last · Multi-Reference |
| Tsubaki Video (`tbkv1.0.1`) | 15s (5 / 10 / 15 only) | Not established — the cost badge checks each clip | First Frame · First+Last · Multi-Reference |
| Tsubaki Video Flash (`tbkv1.0`) | 15s (5 / 10 / 15 only) | Not established — the cost badge checks each clip | First Frame · First+Last · Multi-Reference |
| V3.2 (`v3.2`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 Lite (`v3.0.2`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 (High Consistency) (`v3.0`) | 10s | Yes (V4.0 cards) | First Frame · First+Last |
| V3.0 Flash (`v3.0.1`) | 10s | **No — never covered** | First Frame only |
| V2.7 (High Dynamics) (`v2.7`) | 10s | **No — never covered** | First Frame only |

Notes:
- **Multi-Reference (R2V) only works on the V4.0 pair and the Tsubaki pair.** First+Last (FLF)
  also works on the three V3.0-generation models. V3.0 Flash and V2.7 only ever offer First Frame
  (I2V) — the drawer hides the mode buttons a model can't do rather than letting you
  submit a combination PixAI would reject.
- **The Tsubaki engines are different in four ways.** They take **5, 10 or 15 seconds — no 6**
  (the 6 stop reads dimmed, and a 6 s request goes out as 5); **no negative prompt and no
  camera move** (both controls read disabled — anything you typed stays in the box but is not
  sent); **no video references** in Multi-Reference (images and audio only — video references
  you already picked are held, dimmed and not sent, never deleted); and a reference video can
  set an **output aspect ratio** — Auto (PixAI works it out from the references), 1:1, 2:3,
  3:2, 3:4, 4:3, 9:16, 16:9 or 21:9. In the drawer it is the ratio chip on the prompt bar (the
  phone shows the choices in Multi-Reference itself); on the CLI it is `--video-ratio`. A Remix
  of a Tsubaki Multi-Reference clip brings its ratio back with it. Multi-Reference jobs on these
  engines have run on PixAI's own site, but Moonglade sends them a different way, and that has
  not run yet; First Frame and First & Last follow PixAI's own site and price quotes. The first
  real run of each mode from Moonglade is the proof it goes through.
- **Free cards are V4.0-specific.** V3.0 Flash and V2.7 always cost real credits — the
  drawer's cost badge correctly reads "no card" for them; that's expected, not a bug.
- **A longer clip costs more tickets.** A video card is a book of tickets and a clip uses
  one per 5 seconds (5s = 1, 10s = 2, 15s = 3), so "you have a V4.0 card" is not the whole
  question — see [Free cards and videos](#free-cards-and-videos).
- **15s is exclusive to the V4.0 pair and the Tsubaki pair.** Every other model caps at 10s,
  and the web drawer dims the 15s option once you pick a capped model (rather than letting
  you choose it and fail at submit); the CLI snaps a `--duration 15` on a capped model down
  to 10.

### Video tuning flags

| Flag | Default | Meaning |
|---|---|---|
| `--tail <media_id>` | — | last-frame image → first/last-frame (FLF) interpolation between `--image` and this |
| `--camera-movement` | unset | `horizontal`/`pan`/`roll`/`tilt`/`vertical-pan`/`zoom`; unset omits it (camera direction can also just go in the prompt) |
| `--audio` / `--audio-language` | off / `english` | generate audio with the clip; the language only matters with `--audio` |
| `--video-prompt-helper` | off | let PixAI expand your video prompt (off by default — the **opposite** of image gen, where the helper is on unless `--no-prompt-helper`) |
| `--video-channel` | `private` | `private` = the site's "Private" channel — your generated works cannot be published; `normal` otherwise |

## Edit an image with words (`--edit-image`)

Describe a change and let PixAI's Edit model apply it — "make it nighttime", "add a hat".
Source can be a **catalog `media_id`** or a **local file** (uploaded automatically); pass
`--edit-src` more than once for multi-image reference. Results catalog as `source='api'`.

**Web:** the Generate drawer's **Edit** tab — pick the source image(s) from your gallery,
type the change, set resolution/aspect/quality, then submit. Three edit models: **Edit v4.0**
(new — up to 10 images, 1K/2K/4K, ratios down to 1:8 and 8:1 under **More**, no quality
setting), **Edit Pro** and **Reference Pro**.

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
| `--edit-aspect` | the model's own | output aspect ratio. Edit Pro defaults to `3:5` (it also offers `5:3`). Reference Pro defaults to `auto`, which sends no aspect ratio and lets PixAI choose the frame — it does not promise to keep your source's shape |
| `--edit-quality` | `medium` | quality tier |

The four are clamped to what the chosen model really supports before submit — e.g.
Reference Pro only offers 2K/4K and has no quality knob, so out-of-range values are
corrected (and shown in the preview) rather than rejected.

**Edits made with a model Moonglade doesn't know locally still get a real name.** It
recognizes PixAI's three edit models by name without asking anyone; anything else — a newer
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
on the same model PixAI's own upscale uses — their dialog has no model control either.

The cost is shown before you commit, and a matching free card is applied automatically, the
same as any other generation.

> **In the Generate drawer** you will find **Enhance Details** among the boosters instead.
> That is PixAI's Hires applied to the image you are about to make — the same family of
> settings, but part of the generation rather than something you do to a finished picture.

## Art filters — the Darkroom, free and in your browser

**Art filters** are not generations. Each one is two or three gradient overlays with a blend mode
and an opacity, plus an optional brightness/contrast/saturation trim. PixAI's seven come from a
public config endpoint that their own site reads and composites in the browser — which is why
their Filters tab has no Generate button and never quotes a price.

Moonglade does the same thing locally, and adds five of its own. They live in **the Darkroom**, a
full-screen room of their own: open the Generate drawer → **Edit** → **Enhance** →
**Open the Darkroom ▸**. **Esc** closes it, and it remembers your filter and strength for the rest
of the session.

| Set | Filters |
|---|---|
| **Moonglade** | Moonglade · Nightfallen · Moonlit Silver · Embercourt · Verdant Grove |
| **PixAI** | M1 – M7 |

The five Moonglade filters are derived from the app's five **skins**, each built from that skin's
own accent and lead colours, so a filtered image reads as the app rather than as a generic wash —
and they stay matched to the skins they came from, because a retinted skin fails the test that
pins them to it. They are also **exact-only**: every blend mode they use has a real CSS and canvas
equivalent, so the saved PNG is the preview, pixel for pixel.

The Darkroom is a comparison. The filter rail runs down the left — ours first, then PixAI's, each
row showing that filter's own gradients as its swatch — and the stage holds two panes: your
**source** and the **filtered** version beside it. Judging a filter means seeing both at once, not
toggling one image back and forth. **Strength** and **angle** sit under the panes. Picking a filter
costs **nothing** and makes **no network request at all**; it works with the connection down.

Three actions sit under the stage:

- **Save to library** — bake the result at full resolution into `imported/`, with a thumbnail and
  a catalog row, exactly as importing any local file does. Nothing is uploaded to PixAI.
- **Send to Edit** — upload the filtered image to PixAI (free, the same handshake as
  **↑ Import**) and load it straight into the Edit tab as the source, so you can generate *from*
  the filtered version. The upload spends nothing; only the generation you then run costs.
- **Reset to source** — clear the filter. Your strength and angle stay where you set them.

Two of the eight blend modes PixAI uses are Photoshop's whole-colour *Darker Color* / *Lighter
Color*, which have no CSS or canvas equivalent; they are rendered with `darken` / `lighten`
(per-channel min/max), so PixAI's M1, M2, M5 and M6 can differ slightly from PixAI's own render
where a gradient crosses the image's hue. Every other filter — including all five Moonglade ones
— is exact.

There is no CLI flag for this — it's a browser-side composite, and the old credit-spending
`--enhance --filter-id` submit was removed rather than kept as a worse way to get the same
pixels.

> **PixAI's one-click *workflow* tools now work here — when the mirror is armed.** Background
> removal, line-art, sketch coloring, hand-fix, face-enhance and change-emotion are PixAI
> "panelplugin" workflows that dispatch only on a logged-in browser identity, never a bare API
> key (submitted with a key they are accepted, queued, then cancelled about an hour later
> without ever starting). So the Generate drawer's **Enhance** sub-tab offers them as
> selectable presets that run **only while _Mirror to PixAI_ is turned on** (Control Panel →
> Maintenance) — with the mirror off, the sub-tab says so and points you at the toggle. Each
> spends credits and **no free card covers a panelplugin task**, so the price shows before you
> generate. **Change Emotion** asks which expression you want, sorted into five families —
> Bright, Soft, Dark, Startled, Playful — one family on screen at a time, so you pick from a
> handful rather than scrolling every expression PixAI ships. A purple ♛ means that expression
> needs a PixAI membership. There is still no CLI `--workflow-id`: these are web-only and mirror-gated.
> Separately, the box-coordinate hand/face **Fixer** (Edit → Fix) works on any credential and
> always has, and plain **Upscale** and **Hires** are ordinary generation settings on the
> Generate tab, not workflows.

## Multi-reference video (`--reference-video`)

A different video mode (V4.0): drive a clip from **multiple reference images / videos / audio**
instead of a single start frame. You cite each reference in the prompt with `@image1`, `@video1`,
`@audio1` (they map by position). Refs can be catalog `media_id`s or local files (auto-uploaded).

```bash
# preview (free): shows the exact referenceVideo request
python moonglade_backup.py --reference-video \
    --ref-image <id1> --ref-image "C:\pics\pose.png" \
    --prompt "@image1 in the outfit from @image2, slow orbit"
# really generate — a matching V4.0 card is auto-applied (0 credits) when you hold enough
# tickets for the duration; --no-card to pay instead:
python moonglade_backup.py --reference-video --ref-image <id1> --ref-image <id2> \
    --prompt "@image1 ... @image2 ..." --confirm
```

| Flag | Meaning |
|---|---|
| `--ref-image` / `--ref-video` | a reference (media_id **or** a local file, uploaded for you), **repeatable** — `@image1`, `@image2`, … |
| `--ref-audio` | a reference — **media_id only**, *not* a local file, **repeatable**. PixAI's uploader takes images and videos only, so there's nothing to upload a bare audio file as. To use audio from your own machine, put it into a video (even just a still image with the audio track) and pass that with `--ref-video`. |
| `--prompt` | cite refs by `@imageN` / `@videoN` / `@audioN` |
| `--duration` / `--video-mode` / `--audio` | as with `--generate-video` (15s uses 3 V4.0 tickets — see [Free cards and videos](#free-cards-and-videos)) |
| `--video-ratio` | Tsubaki engines only (`--video-model tbkv1.0.1` / `tbkv1.0`): the output aspect ratio — `adaptive`, `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `9:16`, `16:9` or `21:9`. Left out (or `adaptive`), PixAI works it out from the references |
| `--confirm` | **required** to submit |

**A video reference is priced by its length, too.** PixAI bills a reference video over the
output seconds *plus* the length of every video reference. Moonglade sends each reference
clip's real length — measured from the file in your library, or the length it was generated
at — and the web badge and the CLI preview both show that price. If any reference's length
can't be read (the clip isn't in your library), it sends none, and PixAI prices a flat 15 s
of input in total — the CLI preview prints a note saying so. That can be more than the truth
for one short clip and less for two or more long ones.

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
> nearest-expiry one that covers it, and that generation costs **0 credits**. The **preview**
> tells you up-front whether it'll be free — and the **real credit cost** (via PixAI's
> `task-price` estimate, which spends nothing):
>
> ```
> FREE: Tsubaki.2 Only covers this -- with --confirm it costs 0 credits (saves ~1,600 credits) …
> FREE: V4.0 Preview Lite Only covers this -- uses 3 of 5 cards; with --confirm it costs 0 credits …
> NOT free -- you hold 2 of the 3 V4.0 Preview Lite Only tickets this needs -- not enough, so no card is used -- this costs the full ~82,500 credits with --confirm.
> NO FREE CARD matches -- with --confirm this will cost ~27,500 credits.
> ```
>
> The second and third lines are the video case: a video card is spent one ticket per 5 seconds
> (a 15-second clip needs 3), the preview names how many of yours it uses, and if you don't hold
> enough it says so plainly — no card is attached and the clip costs its full price. If your
> ticket balance can't be read at all, it says *that* rather than guessing ("couldn't read how
> many … tickets you hold … so no card will be attached").

```bash
python moonglade_backup.py --cards        # read-only: your cards, held counts, model, expiry
```

Just generate on a model you have a card for — the match is automatic:

| Card | Just run | 
|---|---|
| **Tsubaki.2** | `--generate` (default model) |
| **Edit Pro** | `--edit-image` (default model) |
| **Reference Pro** | `--generate --model 1948514378441961474` |
| **V4.0 video** | `--generate-video` / `--reference-video` (5s = 1 ticket, 10s = 2, 15s = 3 — see below) |

Overrides: **`--no-card`** forces paying credits even when a card matches; **`--kaisuuken-id <id>`**
forces a specific card. Cards closest to expiry are used first.

### Free cards and videos

An image or edit card is one card, one generation. A **video card is a book of tickets**, and a
clip costs **one ticket per 5 seconds** — 5s = 1, 10s = 2, 15s = 3 — all taken from the same
V4.0 card. So the question the preview answers for a video is not "do I have a card" but "do I
hold enough tickets for this duration". It says so in those terms: **"uses N of H cards"**
(N this clip needs, H you hold), and `--cards` shows the held count per card.

If you don't hold enough — say 2 tickets and a 15s clip — **no card is used at all** and the
clip costs the **full credit price**; nothing is partially applied and nothing is topped up. The
preview states this plainly ("you hold 2 of the 3 tickets this needs — not enough, so no card is
used — this costs the full ~N credits"), and then, matching the website, **Generate still spends
if you click**. It is not refused — you may well want the clip anyway — the point is that you
are never told a paid clip is free. Shorten the clip to what your tickets cover, or wait for
your next card, if you'd rather not pay. See [Trust & Safety](Trust-and-Safety#what-it-can-do)
for the wider guarantee this sits under.

## Contests (`--contests`)

```bash
python moonglade_backup.py --contests                 # live contests (read-only)
python moonglade_backup.py --contests --all-contests  # include ended ones too
```

Lists PixAI's contests — name, dates, entry tag — so you can aim a generation at one.
The CLI command is read-only: it looks, it never enters.

The web gallery goes further. Under **Contests** in the header, opening a contest gives you
its full page: PixAI's own **brief** (what they're actually asking for), the **prize
breakdown** tier by tier — how much each rank pays, how many people place there, and what
that adds up to — and the **requirements**: the tag an entry must carry, whether the contest
restricts you to particular models or LoRAs, a link to its rules document if it published
one, and how the winners get decided. Below that sit both dates, a preview of the entries,
and the winners once results land.

From there you can **enter** a published piece — also from **My Art**, or by picking a
contest while you publish. Entering is an account write, not a browse: the artwork goes into a public contest
under your name, PixAI offers no way to withdraw it, and every entry path asks you to
confirm first. `READ_ONLY` in `config.json` refuses all of them — see
[Trust & Safety](Trust-and-Safety).

**On a phone** the same board, the same contest pages and the same entry road are all
there — under **Contests** in the ☰ menu. The official contest sits at the top as a wide
picture with the community ones listed below it, and **MY ENTRIES** in the corner shows
that same list narrowed to the contests you have a piece in, with where each one stands. A
contest's page folds the brief, the prizes and the requirements so only the part you are
reading is open, and keeps the deadline and **Enter this contest** at the bottom of the
screen. Entering opens a full-screen picker where you can tap **more than one** picture —
the bar underneath counts them and waits for you to confirm, so nothing enters on a single
tap. You can also start an entry from the full-screen viewer or from a published picture's
details, and the picker opens with that picture already ticked.

---

## The Generate drawer (web gallery, v1.9.0)

Everything above also lives in the **web gallery** as a dockable drawer — click **✦ Generate**
in the header. It is **login-tier, not localhost-only**: any signed-in device — local or
elsewhere on your LAN — can open the drawer and spend credits or cards. That's deliberate,
so a tablet or second device can generate too; see [Trust & Safety](Trust-and-Safety) for
what *is* restricted to the server's own machine.

Every submit button here — Generate, ✦ Edit, ✦ Fix, and the Upscale panel's — **waits for a
price that belongs to what it is about to send.** Change a setting and the cost line blanks to
"Checking cost…" and the button greys out for as long as the check takes, so a quote can never
be spent against a job it wasn't for. Typing a prompt or an edit instruction doesn't trigger
that (the wording never changes the price), and if a check fails the badge says so in red and
the button comes back — the app will tell you it doesn't know rather than leave you stuck.

- **Generate** — pick a base model in the pop-out browser (hover any card for a full preview),
  attach **LoRAs with weights** up to your account's own limit (read live from your PixAI
  membership and shown as `LORAS · n/max` — it is not a fixed number, and Generate blocks
  rather than letting you submit over it), aspect/mode/count, live credit cost with the
  free-card check up front.
- **Edit** — instruct edits ("make it night") over one source image. The **Enhance** sub-tab
  holds PixAI's one-click presets and the door to **the Darkroom**, where the **art filters**
  live: gradient overlays applied right in your browser, so they cost nothing, make no request,
  and work offline. The drag-a-box hand/face **Fixer** is not built yet: the computer's Edit
  tab has no Fixer control, and the phone's Edit tab shows a "coming next" placeholder for it.
  The edit models take different numbers of reference images (Edit Pro up to 4, Edit v4.0 and
  Reference Pro up to 10, and the picture being edited counts as one of them), so switching
  from the roomier one to the tighter one can't keep everything you picked. **It now tells
  you what it dropped** — "Only 3 reference images kept … 3 of your 6 references were left
  out" — instead of thinning the strip in silence and letting you submit a paid edit
  believing all six were still attached.
- **Video** — first-frame / first+last / multi-reference shots; pick reference images straight
  from your own gallery (badged `@image1…`, removable, hover to preview); typing `@image1` in
  the prompt turns into a chip; model + duration + audio, and a **Video prompt helper**
  switch (off by default — on, PixAI expands your motion prompt the way the image helper
  does); live cost shows **FREE + "uses N of
  H cards"** when a card covers it — and when it doesn't (a longer clip than your tickets
  cover), it says no card is used and shows the full price, which Generate then spends if you
  click. See [Free cards and videos](#free-cards-and-videos).
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
- **Bridges from the gallery**: right-click any thumbnail (Edit / Send to Video / Remix / Copy
  media id — and **Rebuild poster** on a video), the same Edit/Video buttons in the lightbox,
  **↺ Remix** in Image Details, and multi-select → **Send to Video** in the bulk bar.
- **↺ Remix** loads a picture's *full recipe* into the Generate tab — prompt, negative, size,
  steps/CFG/seed, the model at the exact version it rendered with, and its LoRAs at their real
  weights (recovered from the task itself, never guessed by name). It only fills the composer;
  generating is still your click. If any part can't be restored — the model's gone, a LoRA was
  delisted — the "↺ from #…" chip turns amber and says exactly what's missing, so review it
  before you spend. Desktop for now.
- Results are downloaded and cataloged automatically (`source='api'`; videos into `videos/`),
  so everything you make lands in your own library the moment it finishes. **It lands without
  moving you.** If you are reading page 4 when a job completes, the page you are on, its
  address, the pictures on it and your place among them all stay put — the finished picture
  announces itself with a notice in the corner and a row in **Activity** whose thumbnail opens
  it. On page 1 the library refreshes where it stands, because that is where the new picture
  arrives anyway — nothing moves there either, the new one simply appears at the top.
  **Anything you are holding open is held still too**, at page 1 as much as anywhere: a
  picture open full-screen stays that picture rather than quietly becoming its neighbour, and
  a **◈ Similar** view or an open session stack keeps the library beneath it exactly as you
  left it. **And a page you asked for is the page you get** — turning to page 2 the instant
  something lands is your own hand, and your hand wins; the page you asked for is the one that
  loads and keeps its address, on the phone's **Next** as much as at the desk. If you had
  pictures ticked, any that are no longer in front of you afterwards are un-ticked, so a bulk
  action can never reach something you cannot see.
- **Runs** — the strip across the top of the dock is *today's* runs: each finished picture is
  a tile as soon as it lands (blur → sharp), a batch still cooking shows as one 2×2 cluster,
  and a running tile carries the mascot and a moving bar rather than a made-up percentage
  (PixAI reports no per-image progress, so none is shown). While a run is still *queued* —
  accepted by PixAI, no worker on it yet — the tile also reads **est. 27s wait**: the queue
  wait PixAI itself predicted for that model, the same figure the Activity tracker shows for
  the same job. It is an estimate of the *wait*, taken once when the job went into the queue;
  it is not a countdown, it does not tick, and it disappears the moment a worker picks the job
  up. Click any finished tile to load its settings back into the composer.
- **History** — the **History** button turns the strip into a **seven-day timeline** read from
  your own catalog (not just this session): one column per day, newest first, two rows deep so
  a busy day reads as a compact block, empty days say "No runs", and **Load N older days ⌄** at
  the end pages further back for as long as there is history. Tiles keep their real shape,
  video tiles carry a ▶ tag, and hovering any tile shows what it is — tag and time, model,
  size (or length for a video), the prompt, and what it actually cost. Anything still running
  today sits at the top of the same timeline. History has its own room (the dock may grow to
  the top of the window while it's open) and it composes with the ▲ settings: open both and
  the timeline sits above the settings. Click a finished picture to reuse its settings — that
  closes History and opens the composer on the recipe. Escape closes one layer at a time:
  settings, then History, then the dock.

**The numbers are bounded on the server, and you're told when one moved.** Because the
drawer is login-tier, the sliders and number boxes in your browser are the only limit a
well-behaved client honours — and anything POSTing to `/api/generate` by hand honours none,
so a width of 999,999,999 or 999,999 steps used to go straight through to PixAI and be
priced at whatever that produced. Width and height are now held to 64–4096, steps to 1–150
and CFG to 1–30, the same bounds the drawer's own controls carry. The count is not clamped
at all: `/api/generate` sends exactly one generation and refuses any other count, and a
prompt written with variables, because more than one — and every template — goes through the
confirm above, where the server itself expands, counts, caps and prices the run. When a clamp
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
Draft-quality rendering, and a two-tier project export. Full manual: [The Loom](The-Loom) (or
the ? button on the page).

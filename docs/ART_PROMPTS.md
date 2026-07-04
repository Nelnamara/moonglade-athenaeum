# Art prompts for Mio — Moonglade Athenaeum branding

Copy-paste prompts to generate the branding art (see `docs/ART_SPECS.md` for sizes/slots).
Written for Mio's natural-language style. Two standing rules:

- **Palette** (say the hex): deep violet `#33236d` / `#643aac`, lavender `#b692e6`,
  emerald Void-glow `#4fc99a`, rare gold `#d4af37`, near-black ground `#0c0a1c`.
- **Cut-outs** (logo, favicon, badges): Mio paints *fake* transparency. Generate on a
  **flat pure-green `#00FF00`** background, no shadow — I key it out cleanly after.

---

## 1. Header banner ⭐ (do this first — slot is live)
**Aspect ratio: 16:9** (widest). I crop it to the header strip, so keep the hero in the
**left third, vertically centered**, and let the right side fall into darkness.

> A wide cinematic banner for an arcane moonlit library. On the left third, the silhouette
> of a night elf archdruid standing before towering candlelit bookshelves, long hair drifting
> as if underwater, a faint emerald arcane glow cupped in her hands. Deep violet and indigo
> shadows (#33236d), soft lavender moonlight (#b692e6) rimming her figure, rare glints of gold
> filigree (#d4af37) along the shelves, a thin wisp of emerald Void-light (#4fc99a) in the air.
> Dark, moody, atmospheric, low detail, painterly. High contrast between the moonlit left side
> and the shadowed empty right, which fades into near-black. No text, no title. Ultra-wide,
> horizontal composition.

*Variant (no character):* replace the figure with "an open glowing tome on a lectern, moonlight
falling through a tall arched window onto endless bookshelves that recede into violet darkness."

## 2. Logo mark + favicon (one image serves both)
**Aspect ratio: 1:1.** Reads tiny (16–42px), so keep it bold and simple.

> A minimalist arcane emblem: a crescent moon caught mid-eclipse, a single tiny glowing gold
> star-point at its upper-right edge, rendered in lavender (#b692e6) and deep violet with a
> soft emerald inner glow (#4fc99a). Bold, clean, iconic, symmetrical, high contrast, centered,
> instantly readable at small size. Flat solid pure-green #00FF00 background, no shadow, no
> gradient, no border. Logo / sigil design.

*Variant A (bookish):* "a closed arcane tome seen from the front, a crescent moon rising above
its spine, gold clasp, lavender and violet." *Variant B (monogram):* "a stylized letter M formed
from three phases of the moon — crescent, eclipse, crescent — lavender on flat #00FF00 green."

## 3. Launch icon (double-click shortcut)
Same emblem as #2 works — generate at **1:1** on green, a touch more detail/depth since it
shows larger on the desktop. Send me the file and I make the multi-size `.ico`.

---

## Roadmap art (generate whenever, banked for later)

### 4. Skin banners (theme packs) — each **16:9**, same composition rules as #1
- **Emerald Dream:** "...verdant, jade and emerald tones (#4fc99a), a dreaming forest of glowing
  green mist and floating motes, the Emerald Dream, serene and alive..."
- **The Void:** "...oppressive deep-purple and black, tendrils of shadow creeping over the
  shelves, faint violet corruption, a library under siege by the Void, ominous..."
- **Elune's Light:** "...silver-white moonlight, Elune's blessing, pristine and ethereal, cool
  blue-white glow, soft and holy, hopeful..."

### 5. Achievement badges — **1:1**, on flat `#00FF00` green
> A circular achievement emblem, ornate gold ring with a soft glow, [ICON] centered inside on
> deep violet, lavender highlights, World-of-Warcraft achievement style, polished, flat pure-green
> #00FF00 background, no shadow.

Swap **[ICON]** per milestone: an open book (catalog size), a stacked film reel (videos made), a
full moon (streaks), a crossed brush + quill (creations), a treasure chest (collections).

---

## Banner v2 + emblem — the "Dumbledore's got style" pass (2026-07-04)

**Hard composition rules for the HEADER banner** (learned from v1):
- Ultra-wide (2048×512 or wider). The header shows it at ~16% opacity behind the title.
- **All important art in the LEFT third** — the CSS mask fades the banner to fully
  transparent by 62% across. Anything right of center is invisible.
- **No text anywhere in the image** (say it twice to Mio — it loves signage).
- It sits BEHIND UI: favor atmosphere over subject detail; high contrast shapes read best.

### Banner prompt A — The Archmage's Library (pure atmosphere)
> Ultra-wide fantasy banner, no text anywhere. The grand study of an archmage at night,
> left-weighted composition: towering bookshelves of ancient tomes climbing out of frame on the
> far left, a tall arched window spilling silver moonlight, dozens of floating candles drifting
> at different heights, gold filigree scrollwork on dark violet walls, sparkling motes of arcane
> dust hanging in the air, a crescent moon visible through the window. Deep purple and midnight
> blue palette with rich antique gold accents, opulent, stately, wizardly grandeur, painterly
> semi-realistic style, soft glow, the right half fading into plain darkness.

### Banner prompt B — Nelnamara, Keeper of the Athenaeum (subject + flair)
> Ultra-wide fantasy banner, no text anywhere. A stunning night elf woman with purple-lavender
> skin and glowing pupil-less silver eyes stands at the far left in a magnificent midnight-violet
> robe embroidered with gold celestial patterns — flowing sleeves, high ornate collar, moon-phase
> clasps down the front, tasteful and regal like a beloved old headmaster's finest robes. She
> holds a staff crowned with a softly glowing crescent moon. Behind her, floating candles and
> towering bookshelves dissolve into darkness toward the right. Deep purples, silver moonlight,
> antique gold trim, drifting sparkles, painterly semi-realistic, majestic and warm.

### Emblem / header icon (replaces the "M" tile — the slot ANIMATES it)
The gallery now animates ANY custom logo: a lavender glow that hugs the art's silhouette, a
light-glint that sweeps INSIDE the shape, and a gold twinkle. Strong silhouettes glint best.
> A single ornate emblem, centered, on a flat pure-green #00FF00 background, no shadow, no text.
> A crescent moon wrapped in delicate gold filigree scrollwork, a tiny four-pointed star caught
> in the curve, wizardly and elegant, deep violet and silver with antique gold accents, clean
> bold silhouette, flat vector-like fantasy crest, crisp edges.

Ask for the **#00FF00 flat background** so the transparency cut is clean (AI "transparent"
backgrounds are painted fakes — we key the green out instead). Drop the finished cut at
`pixai_backup/branding/logo.png` (512px, transparent PNG) and it's live on refresh — glow,
glint, twinkle and all. Banner goes to `pixai_backup/branding/banner.png`.

# Art prompts for Mio — Moonglade Athenaeum branding

> ## ❄️ FROZEN — historical record, do not edit. Live art doc is `docs/ART.md`.
>
> **Frozen 2026-07-17.** Merged into **`docs/ART.md`** (the one live art doc), then frozen — not
> deleted, by the owner's call: these prompt bodies are kept as reference craft. The four art docs
> (this one, `ART_SPECS`, `ART_PICKS`, `badge_generation_prompts`) disagreed with each other and with
> themselves on sizes, hexes, and which art shipped — a 2026-07-16 audit found 32 false/stale claims
> across them. `ART.md` reconciles against the code and, where the code settles nothing, says so
> plainly instead of picking. Use `ART.md` for what is true now; use this file only for the full
> original prompt text. A hex or size here that disagrees with `ART.md` is stale — `ART.md` wins.


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
shows larger on the desktop. No hand-off needed: marks ship as PNG + multi-res `.ico`, so pick the
mark in **Panel > Branding** and hit **Set launcher icon** — `/api/branding/shortcut` writes the
Desktop `.lnk` itself.

---

## Roadmap art (generate whenever, banked for later)

### 4. Skin banners (theme packs) — each **16:9**, same composition rules as #1
**Never built.** The five shipped skins are **Moonglade · Nightfallen · Moonlit Silver · Embercourt ·
Verdant Grove**, and they are accent-palette swaps (`html[data-skin]`), not banners — none of the
three below is a shipped skin id or name. Kept here as prompt sketches only:

- **Emerald Dream:** "...verdant, jade and emerald tones (#4fc99a), a dreaming forest of glowing
  green mist and floating motes, the Emerald Dream, serene and alive..."
- **The Void:** "...oppressive deep-purple and black, tendrils of shadow creeping over the
  shelves, faint violet corruption, a library under siege by the Void, ominous..."
- **Elune's Light:** "...silver-white moonlight, Elune's blessing, pristine and ethereal, cool
  blue-white glow, soft and holy, hopeful..."

### 5. Achievement badges — **1:1**, on flat `#00FF00` green
**Superseded:** the ring is tier-encoded, not always gold — see **Ring by tier** in the 2026-07-06
worklist below. A blanket `ornate gold ring` is the old v1 template and is only right for legendary.

> A circular achievement emblem, ornate **{RING}** ring with a soft glow, [ICON] centered inside on
> deep violet, lavender highlights, World-of-Warcraft achievement style, polished, flat pure-green
> #00FF00 background, no shadow.

Swap **[ICON]** per milestone: an open book (catalog size), a stacked film reel (videos made), a
full moon (days used — *distinct* days, NOT a streak), a crossed brush + quill (creations), a
treasure chest (collections). **This is a v1 sketch:** the shipped system has ~26 non-feat metrics
across 10 tracks plus 11 hidden feats — `docs/achievements_roster_57.json` is the real list.

---

## Banner v2 + emblem — the "Dumbledore's got style" pass (2026-07-04)

**Hard composition rules for the HEADER banner** (learned from v1):
- Ultra-wide. **No agreed master size:** this doc has said 2048×512 or wider, `docs/ART_SPECS.md` §1
  says 1920×480, and the code enforces neither — the header img is `object-fit: cover`, so any
  ultra-wide crop works.
- **The whole frame is visible** — stale since the collapsing-banner header landed. A real
  `banner.png` renders at FULL opacity with NO mask, in a 150–300px hero header that slides up to a
  62px slim bar on scroll, cropped `object-position: center 32%`. (The ~16% opacity + fade-to-
  transparent-by-62% mask is the NO-banner base case only, so the old "all important art in the LEFT
  third, anything right of center is invisible" rule no longer applies.)
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
The gallery animates ANY custom logo, with **15 selectable mark animations** (plus `none`) chosen in
`branding.json` / **Panel > Branding**: `classic` — the default, and the legacy combo of a lavender
glow that hugs the art's silhouette, a light-glint that sweeps INSIDE the shape, and a gold twinkle
— plus glow · shine · aurora · twinkle · shoot · halo · eclipse · ripple · mist · prism · breathe ·
tilt · float · orbit. Any non-`classic` choice explicitly mutes those three and drives its own.
Strong silhouettes glint best.
> A single ornate emblem, centered, on a flat pure-green #00FF00 background, no shadow, no text.
> A crescent moon wrapped in delicate gold filigree scrollwork, a tiny four-pointed star caught
> in the curve, wizardly and elegant, deep violet and silver with antique gold accents, clean
> bold silhouette, flat vector-like fantasy crest, crisp edges.

Ask for the **#00FF00 flat background** so the transparency cut is clean (AI "transparent"
backgrounds are painted fakes — we key the green out instead). Drop the finished cut at
`pixai_backup/branding/logo.png` (512px, transparent PNG) and it's live on refresh — glow,
glint, twinkle and all. Banner goes to `pixai_backup/branding/banner.png`.

---

## Banner + icon v3 — "protection against the Void" (2026-07-04)

Aesthetic correction from v2: DROP the gold filigree / baroque ornament. North star is a WARD,
not a jewel — a shield of moonlight holding back the dark. Clean, iconic, resolute. Two-tone
(moonlight-lavender/silver vs void-black), ONE emerald spark (Nel's gems). Strong bold silhouette
(the header glint masks to the logo's alpha, so clean shapes read best). Emblem on flat #00FF00
for a clean key-out. Banner: all art in the LEFT third, no text anywhere.

### Launch/header ICON — pick one, all on flat pure-green #00FF00, no text, no shadow
**A - The Moonward (clean sigil)**
> A single bold emblem on a flat pure-green #00FF00 background, no text, no shadow. A luminous
> crescent moon enclosed within a simple circular warding rune — clean geometric lines, a
> protective sigil of moonlight. Soft lavender-white glow along the crescent, one small emerald
> gem at the center. Minimalist, iconic, strong bold silhouette, flat vector crest style. NO gold,
> no filigree, no ornamentation — restrained and powerful. Deep violet and silver-white palette.

**B - Shield of Elune (the barrier)**
> A single emblem on flat pure-green #00FF00, no text, no shadow. A crescent moon forming a
> protective shield, faint tendrils of dark void-shadow recoiling from its glowing edge, held back
> by the light. Clean and bold, two-tone: pale moonlight-lavender against deep void-black, one
> emerald spark. Minimal iconic silhouette, flat modern fantasy crest. Absolutely NO gold or
> baroque detail — this is a ward, not a jewel.

**C - The Sealed Moon (keeper of the archive)**
> A single emblem on flat pure-green #00FF00, no text, no shadow. A crescent moon set as a seal
> over an open book, a simple ring of soft arcane light around it — the moon guarding the archive.
> Clean minimal geometry, lavender and silver glow, one emerald accent, bold readable silhouette,
> flat vector crest. NO gold filigree, restrained and elegant.

### BANNER — ultra-wide, NO text anywhere, all art in the LEFT third (header masks the right ~62%)
**A - The Warded Sanctum**
> Ultra-wide fantasy banner, NO text anywhere. A moonlit sanctuary at night: a serene archive
> bathed in a dome of protective pale-blue moonlight on the LEFT, with the encroaching Void — deep
> violet-black shadow and faint creeping tendrils — held back at the edge, unable to cross the
> light. Cool silver-blue and deep violet palette, one emerald glow. Atmospheric, protective, calm
> strength. Minimal, NOT ornate — no gold, no clutter. The right half dissolving into plain darkness.

**B - Bulwark of Moonlight**
> Ultra-wide fantasy banner, NO text. Tall archive shelves on the LEFT lit by a clean shaft of
> silver moonlight from a high window, a subtle luminous barrier of light between the shelves and
> the void-black pressing in from the right. Restrained, atmospheric, protective. Deep violet and
> moonlight-silver, one emerald accent. Painterly but CLEAN — no gold filigree, no baroque
> decoration. Right side fading to darkness.

Cut the finished icon on flat green (AI "transparent" backgrounds are painted fakes — key the
green out), drop to pixai_backup/branding/logo.png (512, transparent PNG) and banner.png; both go
live on refresh, glow/glint/twinkle included.

---

## The generation worklist (2026-07-06) — copy-paste ready

The interactive worklist artifact renders these. All cut-outs on flat **`#00FF00`**, no shadow.

### The first 11 achievement badges (2000×2000 masters, circular, WoW-achievement look)
The shipped roster is **57 achievements** (11 of them feats) — `docs/achievements_roster_57.json`.
These 11 were the 2026-07-06 worklist and are now a subset of it; all 11 are still in the roster with
exactly the tiers/thresholds below. Masters are **2000px**; the app derives its own ~256px thumbs
(`/badge-thumb/<id>.png`), so don't generate at 256. Base each on this, swapping the **ring by tier**
and the **[ICON]**:

> A circular World-of-Warcraft-style achievement emblem, an ornate **{RING}** ring with a soft
> glow, **{ICON}** centered inside on deep violet (#33236d), lavender highlights (#b692e6) and a
> faint emerald inner glow (#4fc99a), polished and iconic, reads clearly at small size. Flat
> pure-green #00FF00 background, no shadow, no text.

**Ring by tier:** common → `weathered silver` · rare → `polished blue-steel` · epic →
`ornate amethyst-and-gold` · legendary → `radiant royal gold` · feat → `brushed gunmetal` with a
crowned ruby cabochon and a ruby inner-rim glow (the off-ladder 5th tier — see
`docs/badge_generation_prompts.md`).

| # | Achievement | Tier | Milestone | **{ICON}** |
|---|---|---|---|---|
| 1 | First Light | common | first image backed up | a slender new-moon crescent with the first dawning glow along its edge |
| 2 | Archivist | rare | 1,000 images | an open ancient tome with faintly glowing lavender pages |
| 3 | Hoardsmith | epic | 10,000 images | a small dragon coiled protectively around a hoard of glowing tomes and gems |
| 4 | Loremaster | legendary | 25,000 images | a regal crown of moonlight and gold resting above an open book, radiant |
| 5 | First Frame | common | first video | a single strip of film with one illuminated frame, a tiny crescent moon within it |
| 6 | Moonweaver | rare | 10 videos | a crescent moon with silver threads woven across it like a loom |
| 7 | Reel Director | epic | 50 videos | a film clapperboard crossed with a reel, a small moon on the clapper |
| 8 | Curator | rare | 10 collections | neatly organized folio cards fanned in an arc, one tabbed with a crescent |
| 9 | Menagerie | epic | 25 distinct models | a pair of ornate theatre masks framed by curling arcane motifs |
| 10 | Gallery Opening | rare | publish 10 works | an ornate empty picture frame with a soft gallery spotlight, a crescent in the corner |
| 11 | Tagsmith | epic | tag 500 pieces | a hanging label tag stamped with a crescent, a tiny smith's hammer beside it |

### 7. Loom mark — clapperboard-meets-moon (256×256, on flat #00FF00)
**There is no Loom mark slot** — both Loom headers are pure text (classic renders a ▰ glyph plus
"The Loom", V2 renders "The Loom · V2"), and `_LOOM_SHELL` doesn't consume the branding context vars
at all. Nothing animates a mark there; the slot has to be built before art can land. Keep it a
**bold clean silhouette** anyway so it glints if the slot ever animates. Pick one:

**A — Clapper-Moon (most legible as "video")**
> A single small emblem on a flat pure-green #00FF00 background, no text, no shadow. A film
> clapperboard whose top clapper-bar is a slim crescent moon, clean bold geometry, deep violet and
> silver-lavender with one emerald spark, minimal iconic silhouette, flat modern crest, reads
> clearly at small size.

**B — Reel-Moon**
> A single emblem on flat pure-green #00FF00, no text, no shadow. A crescent moon cradled inside a
> film reel, the reel's spokes forming a soft star, lavender and violet with a faint emerald glow,
> clean bold silhouette, flat vector fantasy crest, iconic at small size.

**C — The Woven Reel (ties to the "Loom" name)**
> A single emblem on flat pure-green #00FF00, no text, no shadow. A short strip of film curving like
> a woven thread on a loom, a crescent moon rising behind it, silver-lavender and deep violet with
> one emerald mote, minimal and elegant, bold readable silhouette, flat crest style.

**Sizing:** the Loom mark would be **256×256** like every other mark. Note that `/loom` does **not**
reuse the gallery header — it's its own `_LOOM_SHELL` page with its own React-rendered `.sb-brand` /
`.lv-top` header, sharing only the design tokens and the `skin` key with the gallery. So neither a
mark slot nor a page-banner slot exists there today; either one has to be built into the Loom's own
header first.

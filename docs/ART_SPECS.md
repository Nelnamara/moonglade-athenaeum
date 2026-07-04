# Art specs — Moonglade Athenaeum

Every image the app consumes (or will), with exact dimensions and where it lands.
Generate at the master size; the app crops/scales as noted.

## Global rules (read once)

**Palette** — match these so art sits in the UI, not on top of it:
| Token | Hex | Role |
|---|---|---|
| base | `#0c0a1c` | page background (near-black violet) |
| mantle | `#0a0818` | header/panels (darkest) |
| lavender | `#b692e6` | **primary accent** — the "leads" color |
| mauve | `#c4a6f0` | soft accent |
| purple-deep | `#33236d` | deep armor violet |
| purple-bright | `#643aac` | brighter violet |
| gold | `#d4af37` | rare filigree/trim (use sparingly) |
| emerald | `#4fc99a` | the "magic" glow (gems, Void-light) |

**Theme:** Moonglade / night-elf / a-library-against-the-Void. Moonlit, arcane, deep
violet with emerald magic-glow and rare gold. Dark and moody, not bright.

**Format:** JPG for full backdrops (no transparency needed). **PNG for anything with
transparency** (logo, favicon, badges).

**Transparency gotcha (important):** PixAI/Mio output has *fake, painted* transparency —
it won't give a real alpha channel. For any cut-out asset, **generate on a solid pure-green
`#00FF00` background** and say so in the prompt ("subject centered on a flat chroma-green
#00FF00 background, no shadow"). We key the green out cleanly afterward. A "transparent
background" prompt gives a checkerboard *painted into* the image — unusable.

---

## 1. Header banner — LIVE slot, ready now
**Drop at:** `pixai_backup/branding/banner.png` (or `.jpg`) → appears instantly, no restart.
- **Master size:** **1920 × 480 px** (≈ 4:1). JPG fine.
- **How it's shown:** stretched to cover the full-width header strip (~58 px tall),
  **cropped to the vertical center**, at **16% opacity**, and **faded out left→right**
  (solid at the left edge, gone by ~62% across).
- **Compose for that:** put the hero element in the **vertical center** and the **left
  40%** of the frame — that band is all that shows; the right half dissolves behind the
  wordmark area. Everything is dimmed to 16%, so **high-contrast silhouettes read; fine
  detail disappears**. Think "moonlit Nelnamara silhouette / Moonglade canopy," not a busy
  scene. Deep violet with an emerald glow accent is ideal.
- No transparency needed (it's a backdrop).

## 2. Favicon / browser-tab icon — hook not wired yet (I'll add on request)
- **Master:** **512 × 512 px PNG**, transparent (green-screen method).
- The eclipse-moon or the "M" sigil. Must read at **16 px** — bold, one clear shape, high
  contrast. No text, no fine detail.

## 3. Logo mark — optional, replaces the CSS "M" tile
- **Master:** **512 × 512 px PNG**, transparent, square.
- Displays at **~28 px** in the header, so same rule: one bold sigil (crescent + gem, or a
  stylized M with the gold dot), reads tiny. Currently a lavender rounded tile with a gold
  dot and an eclipse sweep — a real mark should keep that eclipse/gold-dot DNA.

## 4. Windows launch icon — external (your double-click shortcut)
- Provide a **256 × 256 px PNG** (transparent) and I'll convert to a multi-size `.ico`
  (16/32/48/256) for the desktop shortcut. Same sigil as the logo mark works.

---

## Roadmap art (spec now, build later)

## 5. Skins (theme packs)
Each skin = **one banner** (spec #1) + an accent-color swap. Generate one 1920×480 backdrop
per skin (e.g. "Emerald Dream," "Void," "Elune's Light"), each keyed to a different accent.

## 6. Achievement badges (the "IT'S OVER 9000" system)
- **Master:** **256 × 256 px PNG**, transparent (green-screen), **circular emblem** style —
  WoW-achievement look: gold ring, icon in the center, glow. One per achievement.
- Displays ~64 px; keep the icon readable small.

## 7. Edit Bay mark — optional
Small square sigil for the `/edit-bay` header (currently "▰ The Edit Bay" text). 256×256 PNG,
transparent. A clapperboard-meets-moon motif.

---

## Priority order
1. **Header banner** (live slot — highest impact, works the moment you drop it).
2. **Favicon + logo mark** (identity; I wire the two small hooks when you have the files).
3. Launch icon (you mentioned you have basics — send the 256px and I'll make the .ico).
4. Skins / achievement badges — when we build those systems.

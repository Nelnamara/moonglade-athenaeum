# ART — Moonglade Athenaeum

Every image the app consumes, the palette it must match, the picks that landed, and the prompt
bank that feeds new art. One file. It replaces `ART_PROMPTS.md` + `ART_SPECS.md` + `ART_PICKS.md`
+ `badge_generation_prompts.md`, which are frozen under `docs/archive/` in the same commit that
added this file — preserved, not deleted (§6).

**The three rules that keep this file from rotting.** It replaced four docs that had spent a month
arguing with each other — and with themselves — about a banner size, a generation size, and a hex.

1. **One palette table (§1), transcribed from the code.** A *palette* hex written anywhere else in
   this file that disagrees with §1 is a **bug**, not a variant. The code wins; fix the doc.
2. **One slot table (§2), measured — not specced.** Each slot has exactly one master size: the file
   that is actually on disk. Where the code enforces nothing and the sources disagreed, §2 says so
   and leaves it open rather than inventing a reconciliation.
3. **Prompts cite; they never restate.** No prompt below carries a *slot* dimension, and the only
   place a *palette* hex is retyped outside §1 is the five shared ring blocks (§5.1) — a prompt has
   to say the hex out loud to the model, so those five blocks are the exception, and they are the
   only one. (`reads clearly at 64px` in those blocks is a craft target, not a slot size — §4.)

**Do not trust a claim here that the code can settle — go settle it.** Line numbers below are a
hint, not a contract; grep the named symbol or CSS selector, which survives a refactor.

Art lives in `out_dir/branding/` — machine-local and git-ignored. The C: dev checkout carries only
a sample subset; the full tree is on the run copy (`D:\Moonglade Athenaeum\pixai_backup\branding\`).
All sizes below were measured there on 2026-07-17.

---

## 1. Palette — the one table

### 1.1 The tokens

Transcribed from `DESIGN_TOKENS_CSS`, **`pixai_gallery.py:2405-2416`**. That block is the single
source: `BASE_HTML` and `LOOM_PAGE` both inline it via the `__DESIGN_TOKENS__` marker, so the
gallery and the Loom re-skin together. Re-derive this table from those lines; never edit a hex here
without editing it there.

| Token | Hex | Role |
|---|---|---|
| `--base` | `#0c0a1c` | page ground |
| `--mantle` | `#0a0818` | header / panels |
| `--surface0` / `--surface1` | `#211f3a` / `#3a3460` | cards / raised |
| `--overlay0` | `#6a6088` | borders |
| `--text` / `--subtext` | `#d6d2e2` / `#9a93ab` | copy |
| `--lavender` / `--mauve` | `#b692e6` / `#c4a6f0` | **primary accent** / soft |
| `--accent` | `#b692e6` | = lavender |
| `--accent-soft` / `--emerald` | `#4fc99a` / `#4fc99a` | the "magic" glow — identical values |
| `--gold` | `#d4af37` | rare filigree |
| `--purple-deep` / `--purple-bright` | `#33236d` / `#643aac` | armor violets |
| `--red` · `--peach` · `--green` · `--blue` · `--sapphire` | `#f38ba8` · `#fab387` · `#46d488` · `#47cbc3` · `#3a8a93` | status |
| `--gunmetal` / `--gunmetal-deep` | `#8a93a2` / `#4a515c` | **feat band** |
| `--ruby` / `--ruby-deep` | `#e0355e` / `#a11238` | **feat glow** — the code's own comment: "NOT pink" |

**Theme:** Moonglade / night-elf / a-library-against-the-Void. Moonlit, arcane, deep violet, with
emerald as the magic-glow and gold used sparingly. Dark and moody, never bright.

**`#00FF00` is not a palette colour.** It is the chroma key (§4). It never appears in the UI and
must never be reconciled against this table.

**Skins do not need art.** The five shipped skins (`SKINS`, `:1246` — Moonglade · Nightfallen ·
Moonlit Silver · Embercourt · Verdant Grove; the first two free) are `html[data-skin]` overrides of
a subset of the tokens above. Nothing else.

### 1.2 Tier chrome

Code-only literals — no source doc carried these. Tiles: `.ach-card.t-*` (`:4766-4772`). Toast:
`.ach-m2 .t-*` (`:4898-4903`), which also sets a lighter `--tcl` and a darker `--tcd` per tier.

| Tier | Tile band (`border-left-color`) | Toast `--tc` |
|---|---|---|
| common | `#8a8298` | `#9fbad6` |
| rare | `var(--blue)` | `#7fb0f4` |
| epic | `var(--purple-bright)` | `#c69cff` |
| legendary | `var(--gold)` | `#e8cb7c` |
| feat | `var(--gunmetal)` | `var(--ruby)` |

The toast ramp is deliberately its own thing — a lighter set tuned for the glow, with no token
equivalent. It is not a palette drift and there is nothing to reconcile.

**The frame gate is literal** (`:5303`) — legendary and feat only, and never on a summary toast:

```js
var framed=(!!({legendary:1,feat:1}[tier]))&&opts.badge!==false;
```

Adding `epic:1` to that object is the whole change if epic ever joins the framed tiers.

### 1.3 Unreconciled literals — hexes the tokens do not cover

Recorded so nobody "fixes" the palette table to match them. These are real, and two of them
contradict a token that exists — which by rule 1 makes them bugs, filed here, not doc rot:

| Literal | Where | Verdict |
|---|---|---|
| `#cba6f7` (tile) + `#1e1e2e` (stroke) | the inline-SVG favicon fallback, `:2902` | **Bug.** Pre-Moonglade Catppuccin identity. No token is close. Only renders when `favicon.png` is missing (§2 row 2). Its gold dot *is* `--gold`. |
| `#7ee0a8` | `.ach-crit span.on{color:var(--green,#7ee0a8)}`, `:4765` | **Bug (latent).** `--green` is `#46d488` and is always defined, so the fallback never fires — but it is the wrong colour if it ever does. |
| `rgba(17,17,27,…)` = `#11111b` | the bannered header's `::after` scrim, `:2924` | Unreconciled. Neither `--base` nor `--mantle`. Reads fine; nobody has decided whether it should be a token. |
| `#8a8298` / `#a9a1b8` | the common tile band + its tier text, `:4766` | Deliberate. Common is the only tier with no token of its own. |

---

## 2. Slots — the one table

Root is `out_dir/branding/`, served by `/branding/<path>` (`branding()`, `:8406`) —
path-traversal-safe, `Cache-Control: no-cache`. **Most `<img>`s are `onerror="this.remove()"`**, so
a missing or misnamed file usually fails silently: no art, no error, no clue. Three exceptions are
wired to fall back visibly instead — the toast badge (emoji, `:5320`), the toast mascot (a 3-step
chain, `:5332`) and the favicon (inline SVG, `:2902`). Sizes below are measured off the run copy,
not specced.

| # | Slot | File the code looks for | Master (on disk) | How the code renders it | State |
|---|---|---|---|---|---|
| 1 | **Header banner** | `banner.png` — name hard-coded (`:1330` existence probe, `:3427` `<img id="brand-banner">`). A `.jpg` is silently ignored | **1920×480** RGB | `object-fit:cover`, **no ratio enforced**. `header.bannered` (`:2919`): `--bnr-hero: clamp(150px,22vw,300px)` sliding to `--bnr-slim:62px` on scroll; `object-position:center 32%`; opacity **1**, mask **none**, plus an `::after` scrim `rgba(17,17,27,.04→.4→.9)`. The opacity-`.16` + fade-to-transparent-at-62% mask (`:2912`) is the **no-banner base only** | ✅ |
| 2 | **Favicon** | `favicon.png` (`:2900`) | **128×128** RGB — **no alpha** | `<link rel="icon">`. Fallback = the inline SVG data-URI at `:2902` (§1.3). Only in `BASE_HTML` — **`/loom` ships no favicon link at all** | ✅ |
| 3 | **Logo mark** (legacy fallback) | `logo.png` | **512×512** RGBA | 42px `.brand .mark`. Used **only** when `marks/` is empty (`:1335`) | ✅ |
| 4 | **Marks system** | `marks/marks.json` + `marks/<id>.png` (+ optional `<id>.ico`) (`:1279`) | PNG **512×512** RGBA; ICO carries **7 frames** (16·24·32·48·64·128·256). 5 marks live: `mark_4` + `mark_12` (`kind:"tile"`), `mark_62` / `mark_63` / `mark_74` (`kind:"alpha"`) | 42px. `"tile"` → `.mk-tile` rounded tile, `"alpha"` → floater. 16 `MARK_ANIMS` (15 + `none`, `:1268`). The `.ico` feeds the Desktop `.lnk` via `/api/branding/shortcut` (`:1349`) | ✅ |
| 5 | **Badge masters** | `badges/<achievement-id>.png` | **2000×2000** RGBA — 53 of 57 (4 exceptions below). 57 files; ids match `docs/achievements_roster_57.json` exactly, 0 missing / 0 extra | Tiles **46px** (`.ach-card .ico`) + Recent rail **38px**, both via `/badge-thumb/<id>.png` (`_badge_thumb(…, size=256)`, lazy into `_thumbs/`, mtime self-heal, master fallback). **The toast pulls the MASTER at 100px** (`.ach-m2 .badge`, `:4928`) — not the thumb | ✅ |
| 6 | **Mystery tile** | `mystery/secret_feat.png` (`:5107`) | **512×512** RGBA | Fills the 46px `.ico` well for masked feats | ✅ MYS8 |
| 7 | **Legendary frame** | `frames/legendary.png` (`:4980`) | **1100×829** RGBA | 9-slice `border-image`; `border-width:46px 44px`; `slice:16.8% 13.3% 16.8% 13%`; `outset:6px` | ✅ LEG6 |
| 8 | **Feat frame** | `frames/feat.png` (`:4981`) | **1100×719** RGBA | 9-slice; `border-width:46px 38px`; `slice:15.8% 10.3% 16.8% 10%`; `outset:6px` | ✅ FEAT13 |
| 9 | **Reward · gift** | `rewards/gift.png` (`:5310`) | **128×119** RGBA | **15×15** in the toast reward ribbon `.rwd .giftbox` | ✅ CLAIM7 |
| 10 | **Reward · claim** | `rewards/claim.png` (`:5620`) | **128×128** RGBA | **15×15** in the header credit chip `.claim-ico` | ✅ CLAIM3 |
| 11 | **Toast mascot** (per-ach) | chain: `mascots/ach/<id>.webp` → `<id>.png` → `mascots/present_<tier>.png` (`:5332`) | 57 png + **1 webp** (`first-light.webp`, 480×480, 76 frames — the only animated file; `first-light` also ships a `.png`). PNGs span **389×400** (`kindred-spirits`) to **1846×1871** (`triggered.png`): most are ~390–600 wide (the single most common exact size is 597×504), three are **landscape 597×336** (`first-spark` · `night-owl` · `under-the-hood`), and there are **two** large outliers — `moonwatch.png` **1728×1152** and `triggered.png` **1846×1871** (the largest — a live feat mascot, byte-identical to the `nel_carl.png` orphan below). `present_*` 269–359 × 256–263 | Walks the chain on 404, removes itself only at the end. feat falls back to `present_legendary`. Adaptive alpha-bbox seating via `_seatMascot` | ✅ |
| 12 | **Narrator / rail mascot** | `mascots/gen_nel.png` (`:4667`, `:5229`) | **378×387** RGBA | Narrator button + Trophy Hall rail alcove | ✅ |
| 13 | **Spinner mascot** | `gen_nel.png` — **root, not `mascots/`** (`:5732`, `:5760`) | **160×160** RGBA | Job-tracker spinner + live chip | ✅ ⚠️ |
| 14 | **Job-tracker mascots** | `mascots/trk_done.png` · `trk_fail.png` · `trk_empty.png` | 329×364 / 324×365 / 402×356 | Job card states | ✅ |
| 15 | **Easter egg** | `ee_nelstarfall.png` + `ee_starfall_cast.ogg` + `ee_starfall_loop.ogg` (`:3391-3399`) | 684×704 + 2 ogg | Konami Starfall overlay | ✅ |
| 16 | **Tier SFX** | `sfx/ach_<tier>.ogg` (`_chime`, `:5264-5270`) | **absent** | Slot is wired; `_synth` covers the absence with a per-tier chime. Drop a file in and it plays | ⬜ slot only |
| 17 | **Loom mark** | — | — | **No slot exists.** `_LOOM_SHELL` consumes no `mark_url` / `has_banner` / `brand-banner`; `loom/master-storyboard.jsx` contains zero `branding/` references. Since classic Loom's retirement there is only one header, plain text (`The Loom · V2`). Prompts A/B/C are banked in the archived `ART_PROMPTS` (§6) — build the slot first | ⬜ unbuilt |
| 18 | **Skin banners** | — | — | **No slot.** The 5 shipped skins are token swaps only (§1.1). "One banner per skin" was specced but never built; there is exactly one banner slot (#1), shared by every skin. Three sketch prompts are archived (§6) — none of the three names a shipped skin | ⬜ unbuilt |
| 19 | **Progress-bar frames** | — | — | **No slot.** BAR9 was picked (§3) but `.ach-bar` is pure CSS (`:4760` — `--surface1` track, `--accent` fill) and no `branding/bar*` file is referenced anywhere | ⬜ decided, unbuilt |

### On the banner size — unresolved, and the code will not settle it

`banner.png` on disk is **1920×480**, and that is the master. Nothing enforces it: the code requires
only that the file be named `banner.png`, and `#brand-banner` is `object-fit: cover`, so any
ultra-wide crop renders.

The sources never agreed, and they did not even agree about what they disagreed on:

- **ART_SPECS §1** specs **2048×512 or wider**, and calls 1920×480 a retired figure that "no longer
  describes anything" — i.e. it retires the number that actually shipped.
- **ART_PROMPTS** (banner-v2 pass) says there is **"no agreed master size"**, and attributes
  **1920×480 to ART_SPECS** — which is not what ART_SPECS says.
- **ART_PROMPTS §1** (banner v1) specs a third thing again: **16:9**.

**Unresolved. Pick one when the banner is next regenerated** and write it into the row above.

The *composition* rule, unlike the size, is settled — by the code, against the docs. With a real
banner present the whole frame shows at full opacity with the mask off, cropped `center 32%`. So:

- **True:** keep the hero element in the **upper-middle** band; the bottom is scrimmed and the top
  crops away first as the header collapses. Full opacity means fine detail survives, but the art
  sits **behind** the wordmark and nav — favour atmosphere over busy subject detail.
- **False:** "all art in the LEFT third, the header masks the right ~62%." That is the v1/v3 rule,
  and v3 (2026-07-04) reasserted it *after* v2 had already correctly retired it. It describes the
  no-banner base state (`:2912`) only. Ignore it.

### The four off-spec badge masters

`first-cull` + `starsmith` = **1024×1024** · `eclipse` = **416×416** · `gallery-opening` =
**597×504** (non-square). All four are genuine, distinct badge art — none is a stray copy of the
matching `mascots/ach/` file (hash-checked). They are simply under-sized: the toast renders the
master at 100px so they hold up there, and they are thin for anything larger. See §4 on why two of
them are exactly 1024².

### Orphans on disk — referenced by no code

`banner_legacy.png` (2048×1024) · `mascots/nel_micdrop.png` (1737×1899) · `badges/_pre57_backup/`
(11 files) · `mascots/nel_carl.png` (1846×1871) — but note `nel_carl.png` is **byte-identical to
`mascots/ach/triggered.png`**, which *is* live. The path is dead; the art is not.

### Two code smells (not doc rot — real, and worth an issue)

- **`gen_nel.png` exists at two paths as two different files** — root (160×160, the spinner) and
  `mascots/` (378×387, the narrator). Verified distinct by hash. Both live, trivially confusable,
  one rename away from a silent `onerror` blank.
- **`first-spark.png` never had its chroma key removed inside the medallion** — the field that
  should be deep-violet `--purple-deep` is flat generation-green (§5.4). It is the only master
  where the key survived into the shipped art.

---

## 3. Picks ledger

Owner selections from the Curation Workspace, verified landed. The 2026-07-12 "provisional" caveat
and the 2026-07-13 "alpha gaps" are both **closed**: every winner is keyed, on disk, and wired.

| Slot | Winner | Why it won | Landed at | Verified |
|---|---|---|---|---|
| Legendary frame | **LEG6** | gold + emerald = the house palette | `frames/legendary.png` | ✅ 1100×829 |
| Feat frame | **FEAT13** | ruby thorns — the showstopper; feats are 0-point pure bragging rights, so the most dramatic frame fits | `frames/feat.png` | ✅ 1100×719 |
| Claim icon (daily) | **CLAIM3** | the re-keyed gallery gem — "a BETTER GEM" | `rewards/claim.png` | ✅ 128×128 |
| Reward ribbon (redeem) | **CLAIM7** | gift box | `rewards/gift.png` | ✅ 128×119 |
| Mystery tile | **MYS8** | SecretFeatSquareAlpha | `mystery/secret_feat.png` | ✅ 512×512 |
| Progress-bar pilot | **BAR9** | moon-phase gauge; BAR6 was the 2nd trial | — | ⬜ **decided, no slot** (§2 row 19) |

**Set aside:** LEG4 · LEG7 · BAR4 · FEAT12 · FEAT_LateEntry · CLAIM1 / 2 / 8 / 9.
**Ideas only, never built:** OTHER1 (card-specific redemption) · OTHER15 (reserve badge) ·
spinning-Nel in the BAR6/BAR7 end-cap windows · BAR8 flipped into a toast/notice frame (BAR8 is a
**solid** nebula panel, not hollow — probed, so it can't be a see-through frame) · wide-MYS as a
"Feats of the Athenaeum" section banner · BAR4's built-in left gem window as the badge holder.

The ranked export lists, shortlists and scoring history are frozen with `ART_PICKS` (§6).

### Why the flair looks like this

Locked 2026-07-13 out of the "in action" review, all three now verifiable in code:

1. **Frames wrap the TOAST, 9-sliced** — corners fixed, edges stretch, so the frame grows with the
   content and the roast never overflows. Not the Hall's tiles; that was a wrong turn.
2. **Tier-gated: legendary + feat only** (§1.2, the `framed` literal). Tiles get a tier band +
   earned glow instead. Common / rare / epic stay clean chrome. *"WoW-like, our own flavor."*
3. **CLAIM7 → the toast reward ribbon; CLAIM3 → the header credit chip.** Two different surfaces —
   daily credit claim vs earned goodies / card redemption. Do not conflate them again.

**Locked design sources** (re-open these, never work from a summary): toast v2 `335ef4e7` · frames
wrapping the real toast `3655423e` · finalists in context `b45a39a3` · final-push picker `e3175c08` ·
the pick export `ef9f5853`.

---

## 4. Standing craft rules

None of this is code-enforced — it is how the art gets made. Attribution matters here, because
"all four docs agreed" was itself one of the false claims this file was written to kill:
**`ART_PICKS` is a picks ledger and is silent on every rule below.** At best three of the four
sources carry any given one.

- **Chroma key, always.** *(ART_SPECS · ART_PROMPTS · badge_generation_prompts)* PixAI/Mio
  "transparent" backgrounds are *painted fakes* — a checkerboard drawn into the pixels. Generate
  every cut-out on a **flat pure-green `#00FF00`** background and say so in the prompt ("flat
  pure-green #00FF00 background, no shadow"). Key it out afterward — and check that you did:
  `first-spark.png` shipped with the key still in it (§2, §5.4).
- **No text.** *(ART_PROMPTS · badge_generation_prompts)* Say it twice — the models love signage.
  It is also in the negatives (§5.2).
- **"Reads clearly at 64px."** *(ART_SPECS · badge_generation_prompts only — ART_PROMPTS' worklist
  says "reads clearly at small size" instead)* Badges land at 46px (tiles), 38px (rail) and 100px
  (toast). Design to 64 and all three work. This is a design target, not a file size.
- **Strong silhouettes.** *(ART_PROMPTS)* Marks are masked to their own alpha for the glow/glint
  animations, so a clean bold shape glints and a fussy one smears.
- **Format:** *(ART_SPECS · ART_PROMPTS)* PNG for anything with transparency. The banner is a
  backdrop and needs none — but it is still PNG, because the filename rule is absolute (§2 row 1).

### Badge generation size — unresolved

**The delivered master is 2000×2000** (§2 row 5, measured — 53 of 57). What to *generate* at was
never agreed, and this file will not invent an answer:

- **ART_SPECS §6** says "**Master: 2000 × 2000 px PNG**" under a doc-wide "**Generate at the master
  size**" — i.e. generate at 2000². It never mentions 1024.
- **ART_PROMPTS** worklist agrees: "2000×2000 masters", "Masters are **2000px**". It never mentions
  1024 either. Both docs add: **never generate at 256** — the app derives its own ~256px thumbs and
  the masters stay the source of truth.
- **badge_generation_prompts** — the doc that actually holds the prompts in §5 — says
  "**1:1, 1024², batch 2–4**", in both its v2 header and its feat section. It never mentions 2000.

Nothing in the repo records which setting produced the shipped 57, and the disk shows both:
`first-cull` and `starsmith` are exactly **1024×1024** — the prompt doc's output size, shipped as
the master and never upscaled. There is no evidence of a 1024→2000 upscale step anywhere; do not
assume one exists. **Pick one before the next badge run** and write it into §5.2.

---

## 5. Prompt bank

All 57 achievements, in roster order, one entry each — so a coverage gap is visible rather than
buried in whichever doc didn't have it. `docs/achievements_roster_57.json` is the roster's source of
truth; ids, tiers and triggers below are transcribed from it (57 achievements: 14 common · 15 rare ·
11 epic · 6 legendary · 11 feat).

### Which sets are live

| Set | Status | Notes |
|---|---|---|
| **v2 scene set** (2026-07-11, 6-designer + art-director pass) | **LIVE** — §5.5–5.7 | 41 full-scene entries. Subject leads, meaning-driven, the ring follows |
| **Feat set · gunmetal-ruby** (2026-07-12) | **LIVE** — §5.8 | 11 feats. Replaced the obsidian set; adds `against-the-void` |
| **Worklist-11 icon briefs** (2026-07-06) | **LIVE** — marked *(icon brief)* below | An icon phrase, not a scene. The **sole** prompt record for those 11 |
| Feat set · obsidian-and-gold (10) | **FROZEN** (§6) | Its own doc marks it "SUPERSEDED — do not generate from this section" |
| Badge template v1 (blanket gold ring) | **FROZEN** (§6) | Its own doc marks it superseded: gold is legendary-only |

"LIVE" means *this is the adopted prompt-craft going forward*. It does **not** mean these prompts
made the shipped masters — read §5.4 before assuming that, because they largely did not.

### 5.1 Ring blocks — the shared tail

**Every hex here comes from §1** (`--purple-deep` · `--lavender` · `--emerald` · `--ruby`), and
`#00FF00` is the chroma key, not a palette colour. These five blocks are the **only** place in this
file a palette hex is retyped (rule 3). Edit them here and nowhere else.

The source doc phrased this tail three different ways ("Framed by…" / "Rendered as…" / "Enclose it
all in…") and used them interchangeably. Normalised to one phrasing per tier; the ring *content* is
unchanged.

**`{{RING: common}}`**
> Enclose it all in a circular World-of-Warcraft-style achievement MEDALLION with a **WEATHERED SILVER** ring (common tier) and a soft glow. Deep-violet #33236d inner field, lavender #b692e6 highlights, faint emerald #4fc99a inner glow. High-detail anime illustration, iconic and clean, reads clearly at 64px. Flat pure-green #00FF00 background, no shadow, NO TEXT.

**`{{RING: rare}}`**
> Enclose it all in a circular World-of-Warcraft-style achievement MEDALLION with a **POLISHED BLUE-STEEL** ring (rare tier) and a soft cool glow. Deep-violet #33236d inner field, lavender #b692e6 highlights, faint emerald #4fc99a inner glow. High-detail anime illustration, iconic and clean, reads clearly at 64px. Flat pure-green #00FF00 background, no shadow, NO TEXT.

**`{{RING: epic}}`**
> Enclose it all in a circular World-of-Warcraft-style achievement MEDALLION with an **ORNATE AMETHYST-AND-GOLD** ring (epic tier), jeweled and filigreed, with a soft radiant glow. Deep-violet #33236d inner field, lavender #b692e6 highlights, faint emerald #4fc99a inner glow. High-detail anime illustration, iconic and clean, reads clearly at 64px. Flat pure-green #00FF00 background, no shadow, NO TEXT.

**`{{RING: legendary}}`**
> Enclose it all in a circular World-of-Warcraft-style achievement MEDALLION with a **RADIANT ROYAL-GOLD** ring (legendary tier) crowned with bursting light-rays and a bright glow. Deep-violet #33236d inner field, lavender #b692e6 highlights, faint emerald #4fc99a inner glow. High-detail anime illustration, iconic and clean, reads clearly at 64px. Flat pure-green #00FF00 background, no shadow, NO TEXT.

**`{{RING: feat}}`** — the off-ladder 5th tier, distinct from the four ladder metals
> Enclose it all in a circular World-of-Warcraft-style achievement MEDALLION with a brushed dark **GUNMETAL** ring, a single crowned faceted **RUBY** cabochon set at the very top (12 o'clock), and a soft ruby #e0355e inner-rim glow with a faint ruby outer halo — the distinct mark of the feat tier. Deep-violet #33236d inner field, lavender #b692e6 highlights. High-detail anime illustration, iconic and clean, reads clearly at 64px. Flat pure-green #00FF00 background, no shadow, NO TEXT.

### 5.2 Style suffix + generation params

Verbatim from the source doc. See §4 — the generation size is disputed and this line is one side of
the dispute, not a settled rule.

> **Style:** `highly detailed anime illustration, sharp clean line art, crisp showcase quality, best quality`
>
> **Negatives:** `text, letters, words, watermark, signature, drop shadow, cluttered background, extra objects, blurry, low quality, photorealistic`
>
> 1:1 · 1024×1024 · batch 2–4 · the same model the Part Deux / Part FOE set used.

### 5.3 How to assemble

Every fenced block below is a **subject only**. To use one:

> **prompt = subject + the `{{RING: …}}` block named at the end of its fence + the style suffix.**

Where an entry adds a *ring add-on*, append that clause to the ring block for that generation only.

### 5.4 What this bank is not

**It records the prompts that were written. It is not a manifest of how the 57 shipped masters were
made** — nothing in the repo records that, and the art says it would not hold. Eleven masters were
rendered and compared against their entry here (2026-07-17). **None matches cleanly.**

- `first-spark` — **closest on concept, wrong on execution.** Right anvil-and-first-flame idea and
  the weathered-silver ring, but a large orange-gold flame plume where the entry calls for "just ONE
  tiny mote"/"one lone emerald ember as the focal point", no crescent moon overhead, and — instead
  of the `{{RING: common}}` deep-violet field — **a flat bright green disc: the `#00FF00` chroma key
  was never keyed out inside the medallion** (§2, §4). A real art defect, not a prompt mismatch.
- `starsmith` — closest of the set: gold anvil, a star struck into being, bursting light-rays, gold
  ring. No moonbeam, no recoiling Void.
- `night-owl` — the **archived** owl-on-tomes-and-guttering-candle subject (§6), not this bank's
  sleeping-on-a-cloud one.
- `marathon` — carries a variant of the **archived obsidian `time-capsule`** subject (§6): lavender
  hands over a cobwebbed tome beside a run-out hourglass. Not its own rocket-plume scene. This bank
  gives `time-capsule` a **pocket-watch**, not an hourglass.
- `time-capsule` — the same archived tableau. So `marathon` and `time-capsule` shipped as near-twins
  of each other.
- `gallery-opening` — an open book of two chibi portraits, not the worklist's empty picture frame.
- `eclipse` — a crescent moon in a blue-steel ring. Matches neither its own prompt (no sun/moon
  fusing, no Nel) nor any feat ring.
- `first-cull` — the **sigil-plate wall** this bank gives to `polyglot-of-sigils`, not its own
  pruning-shears scene.
- `the-winnowing` — the **pruning-shears** scene this bank gives to `first-cull`, not its own
  besom-sweep. So the Sweep track's two masters are swapped relative to this bank.
- `polyglot-of-sigils` — a mandala of cards: precisely the "fan of cards" its prompt was recast to
  forbid ("distinctly NOT a fan of cards").
- `stacked-deck` — a flat fan of cards, which its prompt also explicitly rules out ("NOT a flat fan
  of cards").

The pattern is consistent: **the masters were made from earlier briefs than the ones in this file.**
The two prompts recast *away* from cards both shipped as cards; two feats carry archived subjects.

**On the feat rings specifically** — all 11 feat masters were rendered and inspected:

| What the ring is | Feats |
|---|---|
| Gold ring set with crimson/ruby cabochons (the **archived obsidian-and-gold** look, §6) | `night-owl` · `marathon` · `time-capsule` · `completionist` — **4** |
| Some other ring entirely | `against-the-void` (teal-green runic) · `eclipse` (blue-steel, amethyst points) · `triggered` (silver-and-amethyst) · `read-the-manual` (green inner rim, amethyst + ruby points) · `since-the-first-floor` (plain gold, no cabochons) — **5** |
| **Not a medallion at all — no ring of any kind** | `under-the-hood` (a gold key with an amethyst bow) · `the-konami-code` (a purple die bound in gold vines) — **2** |
| The gunmetal band + 12-o'clock ruby cabochon `{{RING: feat}}` specifies | **0** |

**That is not a UI defect: the shipped tier signal is the frame + tile band (§1.2, §2 rows 7–8), not
the ring painted into the art.** A feat reads as a feat because of its gunmetal band and ruby glow
in the chrome, whatever its medallion looks like — which is also why two feats can be a key and a
die and still read correctly. So use §5.1 as prompt-craft for *new* art, and treat any "this prompt
made that badge" claim as unsupported.

---

### 5.5 Ladders

Tiered progression tracks whose art escalates rung by rung — one concept, many rungs.

#### LADDER · Archive — `images`

##### First Light · `first-light` — common · `images ≥ 1` *(icon brief)*
```
A slender new-moon crescent with the first dawning glow along its edge, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: common}}
```

##### Archivist · `archivist` — rare · `images ≥ 1000` *(icon brief)*
```
An open ancient tome with faintly glowing lavender pages, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: rare}}
```

##### Hoardsmith · `hoardsmith` — epic · `images ≥ 10000` *(icon brief)*
```
A small dragon coiled protectively around a hoard of glowing tomes and gems, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: epic}}
```

##### Loremaster · `loremaster` — legendary · `images ≥ 25000` *(icon brief)*
```
A regal crown of moonlight and gold resting above an open book, radiant, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: legendary}}
```

##### The Great Library · `the-great-library` — legendary · `images ≥ 50000`
> ⬜ **No prompt on record** in any of the four merged docs. The master exists on disk.
> Roster note: its reward is an **unlocked banner**, not a badge (`banner_reward`).

#### LADDER · Loom — `videos`

##### First Frame · `first-frame` — common · `videos ≥ 1` *(icon brief)*
```
A single strip of film with one illuminated frame, a tiny crescent moon within it, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: common}}
```

##### Moonweaver · `moonweaver` — rare · `videos ≥ 10` *(icon brief)*
```
A crescent moon with silver threads woven across it like a loom, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: rare}}
```

##### Reel Director · `reel-director` — epic · `videos ≥ 50` *(icon brief)*
```
A film clapperboard crossed with a reel, a small moon on the clapper, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: epic}}
```

##### Cinematheque · `cinematheque` — legendary · `videos ≥ 100`
> ⬜ **No prompt on record.** The master exists on disk.

#### LADDER · The Moonforge — `local_gens`

##### First Spark · `first-spark` — common · `local_gens ≥ 1`

*Already excellent. A distinct, humble, meaning-true scene (first gen ever = the Moonforge's very first spark), tied to the archive/moon world, and clearly the base rung of the Moonforge track (one ember) that the later rungs escalate from.*

```
A small cold crescent-shaped anvil of dark silvered stone sitting dormant on a plain forge-block, and a single bright emerald spark leaping up from its surface at the exact instant of the first hammer-tap — just ONE tiny mote of moonlight-fire catching, a faint curl of pale vapor rising, the anvil still mostly dark and unlit, everything hushed and humble like a flame taking hold for the very first time. A slender crescent moon glows faintly overhead as the spark's source. Centered icon, simple and readable, one lone emerald ember as the focal point.
{{RING: common}}
```
> ⚠️ The shipped master departs from this on almost every point and kept its chroma key — §5.4.

##### Apprentice of the Forge · `apprentice-smith` — rare · `local_gens ≥ 100`

*Strong. Escalates the Moonforge track correctly (one spark → active repeated labor, a shard being shaped), meaning-true (100 gens by your own hand), story-like and hands-on rather than a stock icon.*

```
A night-elf apprentice's lavender-skinned hand gripping a pair of glowing tongs that hold a half-finished crescent-moon shard of luminous moonlight-metal against a blue-steel anvil, a small hammer caught mid-swing above it, and a bright fan of emerald sparks spraying outward from the strike — the shard glowing hot lavender-white, a rolled sleeve and a leather apron-edge visible, the honest sweat-and-repetition energy of a craftsman who has done this a hundred times. A crescent moon hums softly in the background as the forge-light. Dynamic diagonal composition, the hammer-strike as the focal action.
{{RING: rare}}
```

##### Forgemaster · `forgemaster` — epic · `local_gens ≥ 500`

*Excellent. Escalates cleanly (shard-being-shaped → forge self-completing multiple works unbidden), meaning-true (500 gens, the forge answers before you ask), and visibly distinct from its neighbors via the resting hammer + ascending crescents motif.*

```
A grand ornate forge blazing with amethyst and gold fire, its hammer laid to rest untouched across the anvil, while THREE fully-formed radiant crescent-moon artworks rise and float upward out of the flames on their own — self-forged, unbidden, drifting free with trailing emerald glow, as if the forge now completes the work before the master even lifts a tool. Curling arcane runes hang in the air around the rising pieces, the fire roaring rich purple-gold. Sense of effortless mastery and a forge that answers ahead of its smith. Balanced heraldic composition, the resting hammer below and three ascending crescents above.
{{RING: epic}}
```

##### Starsmith · `starsmith` — legendary · `local_gens ≥ 1000`

*The gold-standard of the set. Perfect escalation (shaping metal → forging light itself and cowing the Void), maximal meaning payoff (1000 gens), radial legendary grandeur, unmistakably distinct.*

```
A radiant beam of pure moonlight pouring straight down from a full moon onto a golden celestial anvil, where a hammer of light strikes a newborn blazing STAR into existence — brilliant royal-gold light-rays bursting outward in every direction from the point of creation, the star searing white-gold with an emerald core, molten starlight arcing off the anvil like sparks made of constellations. At the far dark edges of the scene, creeping purple-black Void shadow-tendrils shrink and recoil away, driven back and held at bay by the sheer brilliance of the forging. Awe-struck, triumphant, the smith forging light itself rather than metal. Grand radial composition centered on the exploding star, the recoiling Void confined to the outer rim.
{{RING: legendary}}
```
*Ring add-on:* the ring throws light-rays.

#### LADDER · Vault — `collections`

##### Curator · `curator` — rare · `collections ≥ 10` *(icon brief)*
```
Neatly organized folio cards fanned in an arc, one tabbed with a crescent, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: rare}}
```

##### Grand Curator · `grand-curator` — epic · `collections ≥ 50`

*Strong and specific. Meaning-true (every piece finds its slot) with a distinct honeycomb-of-niches + conducting-hand + filing-threads image that won't be confused with any other badge.*

```
A vast candlelit archive hall compressed into a single tableau: dozens of glowing tomes and small framed paintings float in mid-air and glide in orderly streams into their exact niches within an amethyst honeycomb wall of shelf-alcoves, each niche marked with a tiny crescent-moon sigil; at the focal center a poised lavender-skinned night-elf archdruid's hand, palm-up with fingers spread, conducts the sorting like a maestro, and faint emerald filing-threads link each drifting piece to its one perfect slot — a scene of flawless, total order where nothing is out of place.
{{RING: epic}}
```

#### LADDER · Menagerie — `models`

##### Menagerie · `menagerie` — epic · `distinct models ≥ 25` *(icon brief)*
```
A pair of ornate theatre masks framed by curling arcane motifs, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: epic}}
```

##### Conclave of Hands · `conclave` — legendary · `distinct models ≥ 75`

*Strong. 75 distinct models as a summoning conclave of diverse maker-spirits is a genuine meaning-driven read (breadth of hands commanded), legendary-grand, and distinct via the varied-implements ring around Nel.*

```
A grand moonlit summoning ring in which a full conclave of many spectral makers answers a single call: a wide circle of translucent hooded artisan-spirits and disembodied glowing hands, each wielding a DIFFERENT implement — brush, chisel, quill, stylus, loom-shuttle, sculptor's blade — all turned inward toward Nelnamara who stands at the center, one arm raised and pupil-less silver eyes blazing, calling them forth; radiant golden light-rays fan out between the figures and emerald sparks drift on the air, conveying an overwhelming sense of many diverse hands united and answering at your command.
{{RING: legendary}}
```

#### LADDER · Index — `tagged`

##### Tag Scribe · `tag-scribe` — common · `tagged ≥ 50`

*Well-judged as the humble base of the Index track (one quill, one label, one piece), deliberately modest so catalogus-magnus can tower over it. Distinct and meaning-true.*

```
An intimate candlelit scribe's nook shown small and quiet: a single quill of pale moonlight hovers over one glowing index-card and inscribes a single luminous rune-label, which peels free of the card and flutters upward to fasten neatly onto a modest floating artwork just beside it; a short, tidy stack of blank cards waits at the corner of a worn wooden desk, one inkwell glinting — a humble, hushed first-step moment, one tag placed, one word found.
{{RING: common}}
```
*Ring add-on:* the silver is weathered and **plain**.

##### Tagsmith · `tagsmith` — epic · `tagged ≥ 500` *(icon brief)*
```
A hanging label tag stamped with a crescent, a tiny smith's hammer beside it, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: epic}}
```

##### Catalogus Magnus · `catalogus-magnus` — legendary · `tagged ≥ 2500`

*Deliberately steered `the-lexicon` AWAY from this so the two no longer collide. This retains the sole rights to the 'cosmic constellation-catalogue, Nel dwarfed by the totality' image; it escalates the naming-ritual into an entire indexed universe.*

```
A colossal master-index revealed as a living constellation: an immense open tome as wide as the night sky, its two pages a deep-violet star-field where thousands of tagged pieces glow as pinpoint stars, each star tethered by a fine emerald thread to a small labeled rune, and all the threads streaming back to converge on a towering wall of glowing card-catalog drawers behind — the complete cosmic catalogue of the entire Athenaeum; Nelnamara stands tiny before it, arms spread wide, utterly dwarfed by the totality she has indexed, evoking awe, completion and sheer grandeur.
{{RING: legendary}}
```

#### LADDER · Gallery — `published`

##### Gallery Opening · `gallery-opening` — rare · `published ≥ 10` *(icon brief)*
```
An ornate empty picture frame with a soft gallery spotlight, a crescent in the corner, centered inside the medallion, polished and iconic, reads clearly at small size.
{{RING: rare}}
```

##### Vernissage · `vernissage` — epic · `published ≥ 100`

*Excellent 'the whole city came' opening-night scene, meaning-true (100th publish), distinct from `for-the-viewers` (its humble common-tier counterpart) by scale: cut ribbon, packed crowd, hung picture-wall.*

```
A grand gallery opening night inside a moonlit night-elf athenaeum: a long candlelit hall whose walls are hung floor-to-arch with rows of glowing framed artworks, a velvet rope and a freshly cut silver ribbon in the foreground, a crowd of elegant night-elf patrons rendered as lavender silhouettes gathering and gazing upward, warm gallery spotlights raking down the picture wall, a tall arched window at the back spilling silver moonlight and a crescent moon, motes of arcane dust and a faint emerald sparkle drifting in the celebratory air, opulent and jubilant, a packed private-view 'the whole city came' moment.
{{RING: epic}}
```
*Ring add-on:* antique gold filigree (`--gold`, §1).

#### LADDER · Restoration — `edits`

##### Restorer · `restorer` — common · `edits ≥ 1`
> ⬜ **No prompt on record.** The master exists on disk.

##### Restitcher · `restitcher` — rare · `edits ≥ 50`

*Strong. The in-progress mending act (needle drawing a rip shut into emerald light) is intimate, meaning-true (50 edits), and correctly distinct from `masterworker`'s finished-payoff scene.*

```
An intimate close-up of a torn, glowing portrait-tapestry being mended: two slender lavender-skinned night-elf hands draw a fine silver needle trailing a luminous thread of moonlight, stitching a jagged rip in the fabric closed so the seam knits back together in a line of soft emerald light, loose silver threads and a tiny spool resting nearby, a magnifying loupe glinting at the edge, the mended cloth's image healing before your eyes, focused and tender craftsmanship, 'every flaw a chance to remake'.
{{RING: rare}}
```
*Ring add-on:* the emerald inner glow runs **along the seam**.

##### Masterworker · `masterworker` — epic · `edits ≥ 200`

*Good escalation from `restitcher` (in-progress stitch → finished, tools-laid-down mastery). Meaning-true (200 edits, nothing leaves unfinished) and visually distinct via the completed-easel + resting-tools atelier.*

```
A master restorer's atelier in the Athenaeum's Restoration Wing at night: at center, an ornate easel holds a fully restored, radiantly glowing portrait — flawless, luminous, its colors perfected — while the master's tools lie neatly set down in completion around it: fine brushes in a jar, a threaded needle, a loupe, a palette, all at rest because the work is done, shelves of finished masterworks gleaming softly behind, a crescent moon through a high window casting silver light, an air of accomplished mastery, 'nothing leaves unfinished'.
{{RING: epic}}
```
*Ring add-on:* antique gold accents (`--gold`, §1).

#### LADDER · Sweep — `culled`

> ⚠️ Both masters in this track shipped with the other's subject, and `first-cull`'s carries
> `polyglot-of-sigils`' scene — §5.4.

##### First Cull · `first-cull` — common · `culled ≥ 1`

*Apt druidic first-deletion (pruning one blighted twig). Humble base of the cull track, meaning-true, distinct from `the-winnowing`'s mass-sweep.*

```
A quiet druidic pruning moment: a single lavender-skinned hand holds a pair of slim silver garden shears and snips one withered, greyed, blighted twig away from an otherwise healthy small glowing moonlit sapling, the dead brittle scrap tumbling off into soft shadow below while the living branch brightens with renewed emerald life, a few tidy leaves catching moonlight, humble and clean, the satisfying first tidy cut, 'pruning a dead branch'.
{{RING: common}}
```
*Ring add-on:* the emerald inner glow sits **on the living wood**.

##### The Winnowing · `the-winnowing` — rare · `culled ≥ 100`

*Escalates the cull track well (single snip → broad besom-sweep of 100 duplicates into the Void). Meaning-true, distinct, and integrates the Void motif purposefully.*

```
A sweeping purge at the edge of the archive: a broom-besom bound with moonlight sweeps a heap of dim, greyed, duplicate art-cards and misfired tomes off the edge of a stone ledge, the redundant scraps tumbling in a scattering arc down into a churning void-abyss below where emerald void-light swallows and dissolves them into deep purple-black nothing, a few faint shadow-tendrils recoiling at the light's edge, the good work left clean and glowing behind the sweep, decisive winnowing of chaff from grain, 'swept back into the Void'.
{{RING: rare}}
```
*Ring add-on:* the emerald glow is the **void-glow in the abyss**.

#### LADDER · Vigil — `days_used`

##### Night Keeper · `night-keeper` — common · `distinct days used ≥ 7`

*Cozy caretaker base rung (light one lantern, seven star-flames for seven nights). Meaning-true and distinct from `moonwatch`'s grander communion.*

```
A humble night-keeper's ritual in the candlelit stacks: a lavender-skinned hand lifts a small taper to light a single glass lantern nestled among towering shelves of softly glowing tomes, the warm flame catching, and above it a gentle arc of seven tiny star-like flames strung across the dark marking seven nights kept, a crescent moon just visible through a narrow window, cozy and quiet and devoted, the caretaker's nightly vigil begun, warm amber light against deep violet shadow.
{{RING: common}}
```
*Ring add-on:* the emerald inner glow sits **among the tomes**.

##### Moonwatch · `moonwatch` — rare · `distinct days used ≥ 30`

*Strong escalation (one candle → full personal communion with the moon, 30-phase arc). Meaning-true (30 nights), distinct, and features Nel directly for a rare-tier lift.*

```
A devoted archdruid keeping vigil under a great full moon: a night-elf woman with lavender-purple skin and glowing pupil-less silver eyes stands at a high arched window or balcony of the athenaeum, face and open palms turned up into a broad silver moonbeam that bathes her, her long hair drifting as if underwater, and across the night sky above her curves a faint luminous arc of thirty small moon phases from new to full marking thirty nights kept, a quiet communion of long loyalty, the moon seeming to answer her, serene, reverent, silver-blue and deep violet with one soft emerald mote at her heart, 'the moon knows your name'.
{{RING: rare}}
```

---

### 5.6 Milestones

One-shot first-times. Each fires at threshold 1 — the moment you first touch a capability.

##### Keeper of Order · `keeper-of-order` — rare · `organize_runs ≥ 1`
> ⬜ **No prompt on record.** The master exists on disk.

##### Interior Decorator · `interior-decorator` — common · `skin_changed_runs ≥ 1`
> ⬜ **No prompt on record.** The master exists on disk.

##### Refiner's Touch · `first-enhance` — common · `enhances ≥ 1`

*The literal ENHANCE act (blur snapping to crystalline detail under a fingertip) is vivid, specific and distinct. Reads instantly as 'it just became sharp.' Base of the enhance track.*

```
A slender lavender-skinned fingertip drawing a stroke of clarifying moonlight straight across a single arcane manuscript page — the LEFT side of the page is muddy, blurred, full of grainy static and noise, and where the finger passes the RIGHT side snaps into razor-crisp crystalline detail, fine inked linework and glinting silver illumination revealed. A bright emerald spark of sharpening-magic trails the fingertip along the exact seam between blur and clarity. Intimate close-up, the wondrous 'it just became sharp' moment.
{{RING: common}}
```

##### Woven In · `first-lora` — common · `lora_used ≥ 1`

*'borrowed magic bent to your will' as one foreign thread braided into a moonlight weave is an inventive, abstract read that smartly avoids colliding with the video Loom. Distinct base of the LoRA track.*

```
A single vivid, foreign-colored thread of borrowed magic — glowing a warm gold-amber, clearly not from here — being pulled taut and braided INTO a neat vertical weave of pale silver-lavender moonlight threads on an unseen loom, the outsider strand bending and submitting into the pattern, becoming one with the fabric of the spell. A gentle emerald mote glows where the alien thread fuses into the moonlight weave. Elegant, tactile, the satisfying 'borrowed power, bent to my will' moment.
{{RING: common}}
```

##### Brought From Afar · `first-upload` — common · `uploads ≥ 1`

*'crossing the threshold, outside-in' arrival is a genuinely distinct read of a first upload and uses the archway/night-sky world well. Warm and specific.*

```
A small framed portrait being carried IN through a tall moonlit stone archway of the athenaeum, crossing the threshold from a cold starry night-sky outside into the warm violet candlelit interior — faint dust of the road still clinging to its edges, a wisp of night-breeze trailing behind it, welcomed home into the archive. The picture glows faintly as it passes the doorway's warding line. An emerald spark marks the moment it crosses inside. Warm 'brought here from far away' arrival mood, clear outside-to-inside composition.
{{RING: common}}
```

##### Storyweaver · `storyweaver` — rare · `storyboards ≥ 1`

*The Loom's core act (plan a sequence, ignite the shot) as beaded shot-panels on a thread is distinct and meaning-true. Base of the video/Loom track; escalates cleanly into `master-of-the-loom`.*

```
Three or four small ornate framed storyboard panels strung in a left-to-right row along a single taut silver moonlight thread, like beads on a weaver's loom — each panel a tiny moonlit scene, arranged into a deliberate sequence, a faint connecting thread of light drawn between them showing the story's flow. The final panel on the right is bursting ALIVE, its still image igniting into motion with a vivid emerald render-glow and streaks of light spilling from its frame as it is sent off to render. Cinematic, purposeful, the 'I planned a whole sequence and sent the shot' moment.
{{RING: rare}}
```

##### Kindred Spirits · `kindred-spirits` — common · `similar_uses ≥ 1`

*'more like this' as sympathetic resonance between mirror-twin motes (with the shelves leaning in) is an uncanny, specific read, not a stock icon. Distinct and on-theme.*

```
Two small glowing image-motes, near-identical mirror twins of one another, being drawn magnetically toward each other across a dark violet space until they nearly touch — a single taut resonant EMERALD line of recognition strung between them, humming with sympathetic light, tiny sparks leaping across the gap. Faint bookshelf silhouettes in the background lean subtly inward toward the pair, as if the whole library turned to point at the match. Serene, uncanny 'it understood exactly what I meant' resonance.
{{RING: common}}
```

##### Claimant · `claimant` — common · `claims ≥ 1`

*'the Void pays its daily tithe' as one coin dripping from a tendril into a cupped palm is wry, restrained and distinct, with good use of the Void motif at a humble scale.*

```
A single cupped, upturned lavender-skinned open palm held out in the dark, catching ONE small glowing emerald coin — a single credit-mote — as it drips slowly from the curled tip of a thin dark void-shadow tendril reaching down from above, the Void grudgingly paying out its small daily stipend. Just the one coin, humble and wry, a soft emerald glow pooling in the palm, the void-tendril recoiling back into shadow above. Quiet, slightly comic 'here's your allowance' mood, restrained and small.
{{RING: common}}
```

##### For the Viewers · `for-the-viewers` — common · `published ≥ 1`

*'debut before the narrator's imaginary crowd of watching eyes' is a witty, distinct first-publish read that ties to the unhinged-narrator conceit. Humble common counterpart to `vernissage`'s epic.*

```
A single framed artwork revealed on a wall under a warm downward gallery spotlight cone, freshly unveiled — and out beyond the light, floating in the surrounding deep-violet darkness, a scattering of small glowing pairs of silver eyes hovering and watching it, an audience of imaginary spectators conjured from the void, curious and attentive. The framed piece catches an emerald highlight along its edge; the little watching eyes glint silver-lavender in the dark. Theatrical 'debut before your imaginary crowd' mood, wry and warm.
{{RING: common}}
```

---

### 5.7 Masteries

Breadth over depth: use all N of a thing, or gather N distinct.

##### Master of the Loom · `master-of-the-loom` — epic · `video_modes_used == 3`

*The three-video-modes-mastered read (single-still spin, first/last-frame stretch, reference-braid) is specific and escalates `storyweaver` correctly. Distinct from `first-lora`'s single-thread braid by scale, the full loom, and Nel at the shuttle.*

```
A magnificent arcane LOOM woven from strands of moonlight, its silver frame threading THREE distinct glowing ribbons of film side by side: the first ribbon spinning outward from a single floating still-frame, the second ribbon stretched taut between two framed pictures at its ends (a first and a last), the third ribbon braided together from a bundle of many luminous reference-threads. Nelnamara, a lavender-skinned night-elf archdruid with pupil-less silver eyes, stands at the loom guiding the shuttle, moon-and-stars motes drifting from the weave, emerald Void-light pooling where the three ribbons meet. Dynamic, intricate, a sense of three crafts mastered as one.
{{RING: epic}}
```

##### The Full Toolbox · `full-toolbox` — rare · `tools_used == 3`

*'every tool touched' as a tool-roll with three implements mid-use (graver/lens/needle) is a tidy, specific tableau. Distinct from `enhance-adept` (which is about the five ENHANCE spells, not the three edit/enhance/fix tools).*

```
An open arcane CRAFTSMAN'S TOOL-ROLL of unfurled violet velvet laid flat, holding exactly THREE glowing implements arranged in a fan, each caught mid-use: a fine silver GRAVER carving a new detail into a floating portrait (edit), a faceted crystal POLISHING-LENS beaming light that sharpens and enriches an image behind it (enhance), and a delicate golden MENDING-NEEDLE stitching a splint over a cracked, malformed hand-sculpture (fix). Small emerald Void-sparks jump from each tool's tip, moonlit workbench grain beneath, orderly and complete, nothing missing.
{{RING: rare}}
```

##### Stacked Deck · `stacked-deck` — epic · `lora_stacked ≥ 3`

*New take makes the ACT unmistakable and grander than `polyglot-of-sigils`: three LoRA sigils are no longer loose cards but three molten rune-rings physically FORGED/welded into one interlocked seal held aloft — the danger being they'd tear each other apart, held instead in blazing equilibrium. Vertical, sculptural, high-energy — clearly distinct from polyglot's flat horizontal fan.*

```
THREE massive glowing rune-rings — each a different LoRA sigil blazing in a different color (one crimson-gold, one arcane-blue, one emerald) — interlocked like forged chain-links and FUSED at their crossing points into a single suspended composite seal, held aloft above a lavender-skinned night-elf's upturned open palm. Violent arcs of tension crackle where the three rings bite into one another, yet they hold in perfect roaring equilibrium rather than tearing apart; at their locked center a unified master-glyph blooms, moon-crescents stamped at each ring's crown, molten emerald Void-light welding the whole structure together. A vertical, sculptural, high-tension feat of three powers bound as one stable casting — NOT a flat fan of cards.
{{RING: epic}}
```
> ⚠️ The shipped master is a flat fan of cards — the exact thing this prompt forbids (§5.4).

##### Polyglot of Sigils · `polyglot-of-sigils` — rare · `lora_distinct ≥ 15`

*This one is about BREADTH (15 distinct LoRAs = fluency in many magical tongues), so it was recast away from 'cards in a hand' into a scholar's SPELL-TONGUE WALL: a wide pinned wall of 15+ clearly different sigil-scripts, each labeled and lit, Nel reading across them like a linguist's reference — a study of variety, flat and encyclopedic. `stacked-deck` now owns 'fusing few into one' (vertical, forged); this owns 'commanding many, side by side' (horizontal, catalogued). Cleanly separated.*

```
A scholar's SIGIL-TONGUE WALL in the archive: a broad moonlit study wall hung with a grid of at least fifteen small framed sigil-plates, every single one inscribed in a COMPLETELY DIFFERENT magical script and hue — runic, celestial star-map, floral, geometric, serpentine, crystalline — no two alike, each with a tiny glowing name-tab beneath it, a whole polyglot reference-library of arcane dialects. A lavender-skinned night-elf scholar stands before it, one hand raised tracing between plates as if reading fluently across many tongues, faint emerald Void-threads linking the plates as a common grammar, moon-motes drifting. Encyclopedic, wide, many-voiced fluency — a horizontal catalogued wall, distinctly NOT a fan of cards or a forged seal.
{{RING: rare}}
```
> ⚠️ This scene shipped as `first-cull.png`; `polyglot-of-sigils.png` shipped as a card mandala — §5.4.

##### Skin-Changer · `skin-changer` — rare · `skins_unlocked ≥ 5`

*The rotating five-facet prism showing the same reading-room in five theme-palettes is a clever, literal, distinct read of unlocking all 5 skins. On-theme and unmistakable.*

```
A tall rotating five-sided arcane PRISM standing on a pedestal, each of its FIVE visible facets showing the SAME candlelit library reading-room rendered in a completely different skin: one facet verdant emerald dream-mist, one oppressive Void purple-black with shadow-tendrils, one pristine silver Elune's-light, one warm antique-gold, one deep default violet — the identical bookshelves and arched window recolored five ways. The prism half-turned mid-shift so the palettes bleed into each other at the edges, moon-motes drifting, a single emerald Void-spark at its core. Shape-shifting, many-faced, one place five moods.
{{RING: rare}}
```

##### Enhance Adept · `enhance-adept` — epic · `enhance_workflows_distinct ≥ 5`

*The five simultaneous enhance-rituals (upscale/outpaint/relight/inpaint/bg-removal) around one portrait is specific, meaning-true, and the clear epic escalation of `first-enhance`'s single blur-to-sharp stroke. Distinct from `full-toolbox` (three tools) by being five transmutations on one image.*

```
An arcane ENHANCEMENT ALTAR where a single floating portrait is being transmuted by FIVE distinct rituals at once, each shown as its own glowing act around the frame: a magnifying crystal DOUBLING its resolution into crisp detail (upscale), the canvas EXTENDING outward past its original border with newly-painted scenery (outpaint), a shifting moon-lamp RE-CASTING the light and shadows across the face (relight), a needle of light RE-WEAVING a torn patch seamlessly (inpaint), and the subject figure LIFTING cleanly up off a dissolving background (background-removal). Five spell-glyphs orbit the portrait, emerald Void-energy feeding each ritual, an adept's mastery of transformation.
{{RING: epic}}
```

##### Thrifty Archivist · `thrifty-archivist` — rare · `free_cards_applied ≥ 50`

*'the Void pays its own way' via free-passes tumbling out to fund the art (untouched coin-pouch beside a finished frame) is a specific, wry read of zero-cost gens. Distinct from `claimant` (one coin) by being about spending free-passes, not claiming them.*

```
A shrewd, delighted archivist figure holding up a finished glowing portrait while the swirling VOID beside her disgorges a fan of luminous MOONLIGHT FREE-PASSES — arcane crescent-stamped tickets tumbling out of the dark like coupons of pure light — a neat spent stack of them already piled on the desk, each ticket paying for a picture so no credits leave her purse. A tiny closed coin-pouch sits untouched, a satisfied 'zero-cost' crescent glows above the stack, emerald Void-sparks drifting off the tickets. Frugal, clever, the dark paying its own way.
{{RING: rare}}
```

##### The Lexicon · `the-lexicon` — rare · `distinct_keywords ≥ 100`

*The original (open tome breathing a constellation of tag-words) was a near-clone of `catalogus-magnus` AND overlapped the fanned-cards motif of polyglot/stacked-deck. Recast as a NAMING RITUAL: Nel as scholar breathing words that fly out to LAND on and label many different waiting artworks — the act of applying 100 distinct tags (vocabulary in use, not vocabulary displayed). It sits ALONGSIDE the Index track rather than being a rung of it — that ladder runs `tag-scribe` → `tagsmith` → `catalogus-magnus` on the same `tagged` metric, while this is a separate mastery on distinct tags: bigger than the ladder's humble base, smaller than the cosmic master-index.*

```
A luminous NAMING RITUAL in the candlelit stacks: a lavender-skinned night-elf scholar seated at a lectern with lips parted, breathing out a bright ribbon of many DISTINCT glowing tag-words — each a small silver rune-name in its own hue — that streams up from her mouth and fans outward through the air, every single word peeling off to land on and label a DIFFERENT waiting artwork arranged in a shallow arc around her, each piece brightening the instant its true name touches it. Not a star-map and not a fan of cards but a living current of spoken names finding their pictures, dozens of little labeled works lit one by one. A crescent moon glows in a window behind her; emerald motes drift along the ribbon of words. Warm, erudite, the satisfying moment of the whole collection being correctly named.
{{RING: rare}}
```

---

### 5.8 Feats of the Athenaeum

Hidden prestige, off-ladder, **worth 0 points** — pure bragging rights, so the total never hints at a
hidden feat. This is the 2026-07-12 gunmetal-ruby set; the earlier obsidian-and-gold set (10) is
frozen (§6). **Read §5.4 first:** not one shipped feat master carries the ring below, and two are
not medallions at all.

##### Under the Hood · `under-the-hood` — feat · `branding_custom_file ≥ 1`
*Add your own mark via Panel > Branding (a mark listed in `branding/marks/marks.json` with its `.png` on disk).*

```
A pair of lavender-skinned night-elf hands reaching UP into the open underside of a great glowing arcane machine-organ of the Athenaeum — exposed brass gears, moonlight-conduits and a floating file-map pictogram of glowing nodes-and-threads revealed inside the housing — one hand pressing a custom personal sigil-plate into an empty socket, the whole mechanism lighting up in recognition. A tinkerer who found the door in the walls — 'the house is yours now.'
{{RING: feat}}
```

##### The Konami Code · `the-konami-code` — feat · `konami_triggered ≥ 1`
*Enter the shipped Starfall easter egg (↑↑↓↓←→←→ B A).*

```
Nelnamara, a lavender-skinned night-elf archdruid with pupil-less silver eyes, mid-cast indoors with both arms flung upward, having just entered the sacred sequence — and the vaulted ceiling of the Athenaeum splits open to the night sky as a barrage of green-gold STARFALL rains down in streaking astral bolts and moonfire-green comets crashing among the bookshelves, a faint ghostly constellation of up-up-down-down arrow-glyphs glowing in the sky above her. Chaotic, joyous, a Balance-Druid nerd's triumph, the sky answering a cheat code.
{{RING: feat}}
```

##### Against the Void · `against-the-void` — feat · `recover_events ≥ 1`
*Recover a lost/deleted work by task-id.*

```
A single lavender-skinned night-elf hand plunged wrist-deep INTO a churning purple-black Void-swirl / cosmic maw, fingers clamped around a lost glowing artwork and DRAGGING it back out by force — the reclaimed piece trailing torn shadow-tendrils that recoil and snap away, a bloom of emerald recovery-light flaring as it crosses back into the living world, the screaming Void receding around the rescue. Defiant, triumphant, 'pulled it back by the ankles.'
{{RING: feat}}
```

##### Night Owl · `night-owl` — feat · a session active between 2am and 4am
*A session active between 2am and 4am.*

```
A drowsy lavender-skinned night-elf curled up fast ASLEEP on a small drifting moonlit cloud high in the deep-violet night sky, a great full moon glowing behind her, a heavy open tome slipping from her slackening hands, a soft scatter of stardust 'Zzz' motes rising and a faint '3:00' cluster of tiny stars nearby, the darkened archive far below — up far, far too late, the moon quietly keeping the watch she can't. Cozy, sheepish, tender.
{{RING: feat}}
```
> ⚠️ The shipped master is the **archived** owl-and-candle scene, not this one (§5.4, §6).

##### The Long Night · `marathon` — feat · `gens_in_a_day ≥ 100`
*100+ pieces generated in a single day.*

```
A tiny night-elf ASTRONAUT in moonlit silver armor riding a blazing vertical rocket-plume made of a hundred stacked glowing artworks, launching straight upward through the sky — behind the ascent a sweeping arc from a setting sun on one horizon to a rising sun on the other, the entire night crossed in one unbroken burn, the forge-trail never cooling beneath. Relentless, obsessive, exhilarating — a launch that simply would not stop.
{{RING: feat}}
```
> ⚠️ The shipped master is the **archived `time-capsule`** hourglass scene, and a near-twin of what
> `time-capsule.png` shipped with (§5.4, §6).

##### Eclipse · `eclipse` — feat · `eclipse_anim_triggered ≥ 1`
*The sun-and-moon Balance mark animation plays.*

```
A perfect ECLIPSE held at the exact center: a golden sun and a silver crescent moon sliding INTO one another to form a single balanced disc, half molten-gold and half cool-silver, ringed by a corona of green-gold Balance energy flaring outward; below it Nelnamara stands silhouetted with both arms outstretched, one palm to the sun and one to the moon, holding the two celestial halves in perfect equilibrium. Serene, cosmic, a quiet nod to a Balance Druid — 'balance in all things.'
{{RING: feat}}
```

##### Time Capsule · `time-capsule` — feat · a new backup insert more than 730 days old
*Back up a work more than 730 days old.*

```
A large ornate arcane POCKET-WATCH floating open in the dark, its face a slow spiral of years winding backward, and drawn up OUT of the deep past through the watch's glowing portal-face comes a single ancient dusty artwork — cobwebbed, age-worn, its old light rekindling as it is pulled into the present, faint emerald preservation-glow around it, the watch's hands spinning back through the years. Nostalgic and reverent — the old light the Void nearly kept.
{{RING: feat}}
```
> ⚠️ The shipped master is the **archived** hourglass-and-cobwebbed-tome scene, not this
> pocket-watch (§5.4, §6).

##### Master of the Athenaeum · `completionist` — feat · every non-feat, non-banner achievement earned
*Every non-feat, non-banner achievement earned.*

```
A crowned golden TROPHY / grand completion-emblem risen radiant at the very center of the Athenaeum, encircled by a full orbiting ring of every other achievement-sigil rendered as tiny glowing medallions, all of them lit and complete; a laurel of moonlight wreathes the trophy and a small crown sits atop it, Nelnamara standing crowned and arms-crossed before it in quiet triumph. Grand, conclusive — every ladder climbed, nothing left to earn.
{{RING: feat}}
```

##### Triggered · `triggered` — feat · pester the narrator until it snaps
*Pester the narrator until it snaps and reveals its real voice.*

```
The Athenaeum's spectral NARRATOR itself caught mid-SNAP: a floating serene silver moon-mask / glowing sigil-face, its calm surface now fracturing as jagged cracks of hot ruby-red light split across it, one carved eye twitching, a burst of static erupting from its mouth as its polite composure finally shatters — the exact instant it drops the mask and its real, unhinged voice breaks through. Wry, meta, a little dangerous, purple-black behind it.
{{RING: feat}}
```

##### Read the Manual · `read-the-manual` — feat · `docs_opened ≥ 1`
*Open the in-app docs / help screen.*

```
A single heavy glowing OPEN MANUAL / grimoire held reverently in two lavender-skinned hands and actually being READ — one fingertip tracing a line of fine arcane text, a soft halo of comprehension-light blooming off the page with one tiny surprised sparkle, a puff of long-settled dust lifting from its long-unopened cover, a satin bookmark ribbon trailing. Quiet, wry, improbably virtuous — the one soul who actually opened the docs.
{{RING: feat}}
```

##### Since the First Floor · `since-the-first-floor` — feat · `distinct days used ≥ 100`
*100+ distinct days used.*

```
A sweeping view straight UP the inside of an endless moonlit spiral TOWER-staircase of the Athenaeum, a small determined night-elf figure still climbing near the distant top, and far, far below on the ground floor a faint ghostly first footprint still glows where the long crawl began — a hundred small glowing day-markers spiralling up the steps between then and now. Quiet endurance — still climbing, all this time later, the one who never left.
{{RING: feat}}
```

---

## 6. Archive — frozen, not deleted

Freeze-not-delete was the owner's call: these are gold-standard prompt-craft reference. The reason
they are out of the live doc is that reading them beside the current text produces exactly the
conflicting-data-points problem this file exists to end — `ART_SPECS` alone still specs a favicon
master (512×512, transparent) that is not the file on disk (§2 row 2), a banner size the banner has
never been (§2), and a badge generation size the prompt doc contradicts (§4).

They are frozen verbatim under `docs/archive/`, each keeping its name plus the date suffix this
repo's archive convention uses — `ls docs/archive/` for the exact filenames.

| Frozen | What it holds | Why it is not live |
|---|---|---|
| `ART_PROMPTS` | Banner v1 / v2 / v3 · emblem A–C · launch-icon A–C · the badge template v1 · the 3 skin-banner sketches · **Loom mark A/B/C** · the 2026-07-06 worklist-11 table | The rounds **contradict each other by design** — v3 explicitly reverses v2's gold filigree ("a WARD, not a jewel") and reasserts a left-third composition rule v2 had correctly retired (§2). The worklist-11 ICONs are carried live in §5.5–5.7; the Loom mark prompts wait on a slot (§2 row 17); the skin-banner sketches describe a model that was never built (§2 row 18) and name no shipped skin |
| `ART_SPECS` | Slot dimensions, the transparency gotcha, the 2026-07-05 build order | Superseded by §2, which measures instead of speccing. Its priority list is fully discharged — every hook on it shipped. Its favicon, banner and ICO figures are all wrong against the disk |
| `ART_PICKS` | The full pick export: ranked lists, shortlists, the alpha-tag pass, the "in action" showcase findings | Superseded by §3, which carries the winners and the reasoning. The runners-up and the scoring history are the part that belongs frozen |
| `badge_generation_prompts` | The v2 set + the **obsidian-and-gold PRESTIGE feat set (10)** | §5 carries the v2 set and the gunmetal-ruby feats. The obsidian feat set is **not a subset** of its replacement — the 10 subjects were fully rewritten (Night Owl went from an owl-and-candle to sleeping on a cloud) and `against-the-void` was added — so it is preserved whole. No `obsidian` or `crimson` token exists in the code (§1). Per §5.4 it is also the closest thing we have to an authorship record: 4 of the 11 shipped feat masters carry its ring, and 2 carry its subjects |

**Do not resurrect a frozen prompt into this file.** If a frozen idea is wanted, build the slot first
(§2), then write the prompt against §5.1 and §1.

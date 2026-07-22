# The Folio of Honors

Click **🏆** in the gallery header and **The Folio of Honors** opens as a maximized
overlay over the grid — not a separate page. `Esc` or ✕ closes it and you're back exactly
where you were. (Renamed from "Trophy Hall" 2026-07-22, alongside a full visual redesign.)

It's a scoreboard for the work you've already done. Nothing in it spends credits or
talks to PixAI: progress is counted from your local `catalog.db` plus a small counter
file in your backup folder. It's also **not localhost-gated** — sign in from a tablet
and your trophies come with you.

## The three visible categories

### Evolution Ladders

The backbone. Ten tracks, each one concept climbed rung by rung — common at the foot,
legendary at the crown.

| Track | Counts | Rungs |
|---|---|---|
| **The Archive** | images backed up | First Light (1) · Archivist (1,000) · Hoardsmith (10,000) · Loremaster (25,000) · The Great Library (50,000) |
| **The Loom** | videos | First Frame (1) · Moonweaver (10) · Reel Director (50) · Cinematheque (100) |
| **The Moonforge** | generations made *in* the app | First Spark (1) · Apprentice of the Forge (100) · Forgemaster (500) · Starsmith (1,000) |
| **The Stacks** | collections | Curator (10) · Grand Curator (50) |
| **The Menagerie** | distinct models drawn from | Menagerie (25) · Conclave of Hands (75) |
| **The Index** | tagged pieces | Tag Scribe (50) · Tagsmith (500) · Catalogus Magnus (2,500) |
| **The Gallery** | published works | Gallery Opening (10) · Vernissage (100) |
| **The Restoration Wing** | edits run | Restorer (1) · Restitcher (50) · Masterworker (200) |
| **The Great Sweep** | pieces culled | First Cull (1) · The Winnowing (100) |
| **The Vigil** | distinct days you opened the app | Night Keeper (7) · Moonwatch (30) |

**The Archive** counts everything in your library; **The Moonforge** counts only what you
made here — pieces the gallery's Source filter calls **Generated or Imported**, not
everything The Archive counts, but broader than **Source → Generated** alone (which
excludes Imported).

### Milestones

One-shot first-times. They fire the first time you touch a capability, so they mostly
double as a tour of the app: **Keeper of Order** (run [Organize](Backing-Up)),
**Interior Decorator** (wear a skin), **Refiner's Touch** (first enhance), **Woven In**
(first LoRA), **Brought From Afar** (first upload), **Storyweaver** (send a shot from
The Loom), **Kindred Spirits** (use ✧ Similar), **Claimant** (claim a daily reward), and
**For the Viewers** (publish a work).

### Masteries

Breadth rather than depth — use *all* of a thing, or gather *N* distinct ones:
**Master of the Loom** (all three ways to move a frame), **The Full Toolbox** (edit,
enhance and fix), **Stacked Deck** (three LoRAs on one summoning), **Polyglot of Sigils**
(15 distinct LoRAs), **Enhance Adept** (five different enhance workflows), **Skin-Changer**
(unlock every skin), **Thrifty Archivist** (50 free cards spent), and **The Lexicon**
(100 distinct keywords).

**Master of the Loom** and **The Full Toolbox** show a per-item checklist on the card, so
you can see *which* piece you're still missing rather than just "2 / 3".

### …and one more

There is a fourth category — **Feats of the Athenaeum** — and it stays completely
cloaked. No tab, no rail entry, no placeholder count, until the day you earn your first
one. After that it appears as its own section with the rest still masked as **???**.
Feats are worth **no points** on purpose, so your score can never quietly hint that one
is out there. They're found by playing, not by reading. Good luck.

## Rarity and points

Every achievement carries a tier, and the tier sets a base score:

| Tier | Points |
|---|---|
| common | 5 |
| rare | 10 |
| epic | 25 |
| legendary | 50 |

Ladder rungs add **+5 per step up the track**, so a crown is worth more than the same
tier sitting on its own — *Loremaster* (rung 4 of The Archive) is 65, not 50. Feats
score 0.

The header keeps a running total: how many of the visible achievements you've earned,
and your points out of the possible total.

## Getting around the Folio

Three tabs across the top:

- **Summary** — your six most recent unlocks with the date you earned them, plus a
  progress bar for the overall roster and for each category.
- **All** — an auto-rotating showcase of your active ladder's tiers up top, a badge row
  to switch between all 10 ladders, that ladder's tiers as cards, then every ladder in
  turn under its own divider, then Milestones/Masteries/Feats the same way. Legendary and
  feat cards carry the same ornate 9-slice frame the unlock celebration uses. Earned
  cards light up and carry a one-line commentary from the narrator; locked ones show a
  progress bar and `current / threshold`.
- **Statistics** — achieved/points/feats at a glance, plus breakdowns by category, by
  rarity, and by ladder completion, and underneath all the raw numbers behind the
  thresholds: images archived, videos, collections, models used, published works, tagged
  pieces, local generations, best day, distinct keywords, edits, enhances, uploads,
  culled, days visited, LoRA uses, distinct LoRAs, Loom shots, more-like-this uses,
  rewards claimed, free cards used.

The **search box** in the header filters by name, description or tier and jumps you to
the **All** tab as you type. The right-hand rail's **Categories** list now filters
in place — click one to show only that category, click again to clear it — alongside
**Within Reach** (the three locked achievements you're closest to finishing) and
**Relics**, a read-only look at all five skins (locked ones dimmed with a lock icon,
your active one checked). Picking a skin still only happens from the Control Panel.

Unlocks announce themselves with a mid-screen moment — badge, chime, and flair that
scales with rarity. If a whole stack lands at once (a first run over an existing
library, say) you get one summary toast instead of a barrage. **Click any earned card
to replay its celebration.**

## Skins

Some epic achievements unlock a **skin** — a palette swap applied across the whole
suite. Five ship in total:

| Skin | How you get it |
|---|---|
| **Moonglade** | free (the default — lavender leads, emerald magic) |
| **Nightfallen** | free (void-touched violet and star-ash) |
| **Moonlit Silver** | Hoardsmith — 10,000 images |
| **Embercourt** | Reel Director — 50 videos |
| **Verdant Grove** | Menagerie — 25 distinct models |

A card tells you up front if it unlocks one (**★ unlocks … skin**), and unlocking all
five earns **Skin-Changer**.

Skins are applied from the **Control Panel** (`/panel` → **🎨 Skins**), not from the
Hall — all the cosmetics live together. Your choice is saved server-side, so it follows
you to every device and every page of the suite. Picking a locked skin is refused by the
server, so there's nothing to cheat.

## Where progress comes from

Most metrics are counted live off `catalog.db` every time you open the Hall — images,
videos, collections, models, published, tagged, local generations, keywords. The rest
are **persisted counters** kept in `telemetry.json` beside your catalog, bumped as you
work: edits, enhances, uploads, culls, days visited, LoRA uses, Loom shots, claims and
free cards.

Those counters are bumped from the **CLI too**, not just the web UI — so an `--organize`
run, a `--dedup --apply`, a `--claim`, and every free card auto-applied to a generation
all count toward your trophies:

```bash
python pixai_gallery_backup.py --organize          # Keeper of Order
python pixai_gallery_backup.py --dedup --apply     # The Great Sweep
python pixai_gallery_backup.py --claim all --confirm   # Claimant
```

Your earned dates, the skin you're wearing, and which unlocks have already been
celebrated live in `achievements.json` in the same folder. Both files fail soft — if
either goes missing or gets corrupted, nothing breaks; the catalog-derived achievements
simply recompute themselves on the next open, and the counter-derived ones start again
from zero.

---

*Read-only, local, and entirely cosmetic. The Folio of Honors never spends a credit.*

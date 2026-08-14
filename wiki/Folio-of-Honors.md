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
legendary at the crown. Each track follows one thing you do here: your archive's growth,
videos woven in The Loom, generations made in the app, collections, the breadth of models
you draw from, tagging, publishing, edits, curation culls, and simply showing up.

Every ladder's cards are right there in the Folio — locked rungs show their name, their
progress bar, and `current / threshold`, so the climb is never a secret once you're
looking at it. What the next crown asks of you is best discovered on the shelf itself.

### Milestones

One-shot first-times. They fire the first time you touch a capability, so they mostly
double as a tour of the app — the first time you organize the library, wear a skin,
upload a piece, send a shot from The Loom, claim a daily reward, publish a work… each
gets its moment. If you're exploring the app, you're earning them.

### Masteries

Breadth rather than depth — use *all* of a thing, or gather *N* distinct ones. Where a
mastery has a short, knowable list behind it, its card shows a per-item checklist so you
can see *which* piece you're still missing rather than just "2 / 3".

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
tier sitting on its own. Feats score 0.

The header keeps a running total: how many of the visible achievements you've earned,
and your points out of the possible total.

## Getting around the Folio

Three tabs across the top:

- **Summary** — your six most recent unlocks with the date you earned them, plus a
  progress bar for the overall roster and for each category.
- **All** — an auto-rotating showcase of your active ladder's tiers up top, a badge row
  to switch between all 10 ladders, that ladder's tiers as cards, then every ladder in
  turn under its own divider, then Milestones/Masteries/Feats the same way. Earned
  cards light up and carry a one-line commentary from the narrator; locked ones show a
  progress bar and `current / threshold`.
- **Statistics** — achieved/points/feats at a glance, plus breakdowns by category, by
  rarity, and by ladder completion, and underneath all the raw numbers behind the
  thresholds: images archived, videos, collections, models used, published works, tagged
  pieces, local generations, best day, distinct keywords, edits, uploads,
  culled, days visited, LoRA uses, distinct LoRAs, Loom shots, more-like-this uses,
  rewards claimed, free cards used.

The **search box** in the header filters by name, description or tier and jumps you to
the **All** tab as you type. The right-hand rail's **Categories** list filters
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
suite. Five ship in total: two free (**Moonglade**, the lavender-and-emerald default,
and the void-touched **Nightfallen**) and three earned. A card tells you up front if it
unlocks one (**★ unlocks … skin**), so the Folio itself is the map — and unlocking all
five earns **Skin-Changer**.

Skins are applied from the **Control Panel** (⚙ Panel → **🎨 Skins**), not from the
Hall — all the cosmetics live together. Your choice is saved server-side, so it follows
you to every device and every page of the suite. Picking a locked skin is refused by the
server, so there's nothing to cheat.

## Where progress comes from

Most metrics are counted live off `catalog.db` every time you open the Hall — images,
videos, collections, models, published, tagged, local generations, keywords. The rest
are **persisted counters** kept in `telemetry.json` beside your catalog, bumped as you
work: edits, uploads, culls, days visited, LoRA uses, Loom shots, claims and
free cards.

Those counters are bumped from the **CLI too**, not just the web UI — so an `--organize`
run, a `--dedup --apply`, a `--claim`, and every free card auto-applied to a generation
all count toward your trophies. Working from the terminal never costs you a moment.

Your earned dates, the skin you're wearing, and which unlocks have already been
celebrated live in `achievements.json` in the same folder. Both files fail soft — if
either goes missing or gets corrupted, nothing breaks; the catalog-derived achievements
simply recompute themselves on the next open, and the counter-derived ones start again
from zero.

---

*Read-only, local, and entirely cosmetic. The Folio of Honors never spends a credit.*

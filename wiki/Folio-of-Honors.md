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
one. After that it appears as its own section: the feats you have found, in the order you
found them, and after them a single dashed **veil** card holding a riddle and the shadow
of a badge. It is always one card, however many are left, so nothing here tells you how
many secrets remain — the section's count only ever says how many you have **found**.
Solve the riddle and the shadow becomes the feat: the card flickers, snaps to its badge
and wears a **newly found** ribbon until you close the Folio, and the next riddle takes
its place. Find them all and the veil gives way to a line saying so. (With reduced motion
turned on, the card simply appears at rest with its ribbon.) The search box never matches
the veil. On a phone the veil is a banner heading the Feats list, and new finds carry a
**NEW** chip. Feats are worth **no points** on purpose, so your score can never quietly
hint that one is out there. They're found by playing, not by reading. Good luck.

A feat's earn moment carries a **See it in the Folio** button that opens the Folio at its
card.

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

The header keeps a running total: how many of the ladder rungs, milestones and masteries
you've earned, your points out of the possible total, and a **completion** meter (see
*For completionists* below). Feats are never part of any total; they are shown only as how
many you have found.

## Getting around the Folio

Three tabs across the top:

- **Summary** — your six most recent unlocks with the date you earned them, plus a
  progress bar for the overall roster and for each category.
- **All** — an auto-rotating showcase of your active ladder's rungs up top, then a badge
  row to switch between all 10 ladders, then every ladder in turn under its own divider,
  then Milestones/Masteries/Feats the same way. Earned cards light up and carry a one-line
  commentary from the narrator; locked ones show a progress bar and `current / threshold`.
  Each ladder's badge in that row wears **the art of the highest rung you have earned on
  it**, ringed in that rung's rarity colour and marked with its number — so the row reads
  as how far up each track you are, and a badge upgrades itself the moment a higher rung
  lands. A track you have not started shows its first rung, dimmed. Every rung appears
  exactly once on this tab, in *Every rung, every ladder*; the ladder you have selected is
  detailed by the showcase at the top rather than repeated as a second grid.
- **Statistics** — achieved/points/feats at a glance, plus breakdowns by category, by
  rarity, and by ladder completion, and underneath all the raw numbers behind the
  thresholds: images archived, videos, collections, models used, published works, tagged
  pieces, local generations, best day, distinct keywords, edits, uploads,
  culled, days visited, LoRA uses, distinct LoRAs, Loom shots, more-like-this uses,
  rewards claimed, free cards used.

The **search box** in the header filters by name, description or tier and jumps you to
the **All** tab as you type. The right-hand rail's **Categories** list filters
in place — click one to show only that category, click again to clear it — alongside
**Within Reach** (the three locked achievements you're closest to finishing, each with a
moon that fills as you close in) and **Relics**: the rewards your honors have handed you,
in up to three rows — **Skins**, **Banners** and **Marks**, newest first. A row with
nothing in it simply isn't there, and nothing you haven't earned is shown as a locked
tile. Tap a skin to wear it; a banner or a mark opens **✦ Branding** in the Control Panel.

Unlocks announce themselves with a mid-screen moment — badge, chime, and flair that
scales with rarity. If a whole stack lands at once (a first run over an existing
library, say) they play as a parade: each takes the middle of the screen in turn, then
recedes down behind the next, with a running count of how many you have earned. Click
the moment to move straight to the next one — or press **Esc**, or the **skip** chip
beside the count, to end the parade there and then. Every achievement is recorded as
earned whether or not its moment played. **Click any earned card to replay its
celebration.**

## For completionists

The Folio also helps you finish the record, without ever counting the feats.

- **N to go.** Every locked ladder rung, milestone and mastery that the app can measure
  shows how many are left ("12 to go") beside a small moon that fills as you close in, and
  a **→** that jumps to the place that advances it: Generate for images and videos, The
  Loom for storyboards, Contests for entries, Publish for published works. An honor the app
  can't measure shows no count, no moon and no jump. Feats never show one.
- **Completion.** The meter in the header covers ladder rungs, milestones and masteries
  only, rounded down, so 100% means everything in them is done. Finding a feat never moves
  it; feats sit beside it as "N found", with no total.
- **Sort.** The **All** tab can sort by **Default**, **Closest to earning** (what's nearest
  first, then what's earned), **Rarest** or **Newest earned**. Feats are in none of the
  orders. The choice is remembered on the device you made it on.
- **Pin a goal.** The pin beside a row's **→** puts that honor in the app header, beside
  your credits on the gallery, the Generate dock and The Loom: the moon, its name and how
  many to go. One pin at a time — pinning another replaces it. Click the chip to open the
  Folio on that row, ✕ to let it go. It clears itself when you earn the honor, as the
  earn moment plays, and steps aside whenever a celebration is on screen. Your pin is
  saved to your account, so it follows you between devices. On a phone it's a slim chip
  above the tab bar, and you swipe it away to unpin.
- **The Vigil.** A count of the days in a row you've made something: a day counts when at
  least one generation was collected that day, by the clock of the machine running the
  gallery. It's always in the Folio's header with your **best** run beside it, and a
  switch there can show it in the app header too (on a phone, in the row above the tab bar
  beside your pin). Miss a day and it simply starts again at day 1 — no message, no toast.
- **The Honors card.** **⇩ Honors card** draws a 1200 × 630 picture on your own device:
  your name and mark, your points, the completion percentage, your Vigil, and the three
  rarest honors you've earned as their badge art, in the colours of the skin you're
  wearing. Feats appear only as "N found" — never named or pictured. **Save** it or
  **Copy** it; on a phone, **Share** opens the phone's own share sheet. Nothing is
  uploaded anywhere.

None of this writes anything when you merely look: your pin, the Vigil switch and your
sort are saved only when you click them.

## Skins

Some epic achievements unlock a **skin** — a palette swap applied across the whole
suite. Five ship in total: two free (**Moonglade**, the lavender-and-emerald default,
and the void-touched **Nightfallen**) and three earned. A card tells you up front if it
unlocks one (**❖ unlocks … skin**), so the Folio itself is the map — and unlocking all
five earns **Skin-Changer**.

Skins are applied from the **Control Panel**, in its **Identity** strip — all the
cosmetics live together, and the strip pairs the skins with the mark that sits beside the
title so you can judge the two together — or with a tap on the skin in the Folio's
**Relics**. Your choice is saved server-side,
so it follows you to every device and every page of the suite. Picking a locked skin is
refused by the server, so there's nothing to cheat.

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

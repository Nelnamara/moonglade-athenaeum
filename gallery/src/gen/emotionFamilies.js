/* CHANGE EMOTION -- the five families, as DATA (issue #49, handoff comp A3).
   Kept out of EnhanceTab.jsx for the same two reasons gen/sceneCatalog.js is: it can be
   tested without a React harness, and it can be RE-CUT WITHOUT TOUCHING CODE. Re-homing an
   expression, renaming a family or adding one is an edit to the table below and nothing else.

   THE PROBLEM IT SOLVES. PixAI ships ~35 expressions for the emotionlab workflow. Drawn as
   one flat grid they scrolled forever and read as an undifferentiated wall -- you could not
   find "the angry one" without hunting every tile. Five families, one on screen at a time,
   4 across: every family fits without scrolling.

   THE KEYS ARE REAL. They are moonglade_backup.py's ENHANCE_EMOTION_PROMPTS keys -- the
   staged-art filename stems the picker sends up, captured verbatim from PixAI's
   config/constants imageEnhancementPlugins.emotion. The mapping below is OURS (PixAI ships
   no grouping); the assignments follow each key's own danbooru tag string, which is why
   `focused` (v-shaped eyebrows, frown) sits with the dark ones and `mania` (crazy smile)
   with the playful ones.

   NOTHING IS EVER DROPPED. groupFamilies() renders from the LIVE staged list, so a key
   PixAI adds -- or one the owner stages art for that this table has never heard of --
   lands in a visible "More" tab instead of vanishing. That tab appears only when it has
   something in it, so the ordinary case is still five tabs.

   COLOURS FOLLOW THE HUE LAW and are GLYPH TINT ONLY (handoff A3): the tiles stay neutral
   surface, and the family's colour rides the glyph. gold = bright, lavender = soft,
   ruby = dark, cyan (--loomc) = startled, emerald = playful. No new hues. */

/** The five, in tab order. `keys` is the design-time mapping; `glyph` is the family mark. */
export const FAMILIES = [
  {
    id: "bright", label: "Bright", glyph: "☼", color: "var(--gold)",
    keys: ["happy", "laughing", "pumped", "moved", "affection", "amazed"],
  },
  {
    id: "soft", label: "Soft", glyph: "☾", color: "var(--lavender)",
    keys: ["cute", "shy", "nervous", "sympathy", "blush-stickers", "aroused"],
  },
  {
    id: "dark", label: "Dark", glyph: "☂", color: "var(--ruby)",
    keys: ["upset", "mad", "annoyed", "scowl", "sickened", "speechless", "pouting", "focused"],
  },
  {
    id: "startled", label: "Startled", glyph: "!", color: "var(--loomc, #47cbc3)",
    keys: ["afraid", "shocked", "awkward", "confused", "doubt", "stunned", "aggrieved"],
  },
  {
    id: "playful", label: "Playful", glyph: "~", color: "var(--emerald)",
    keys: ["smug", "playful", "sassy", "naughty", "nosebleed", "impatience", "mania", "glasgow-smile"],
  },
];

/** The catch-all. Not in FAMILIES: it exists only when something falls into it. */
export const MORE = { id: "more", label: "More", glyph: "·", color: "var(--subtext)" };

/**
 * Sort the LIVE staged emotions into the families above, in the table's own key order.
 *
 * @param {Array<{key: string}>} emotions the /api/enhance/emotions rows, as served.
 * @returns {Array<{id, label, glyph, color, items}>} only the families that have
 *          something staged, plus a trailing "More" holding every unmapped key.
 */
export function groupFamilies(emotions) {
  const rows = Array.isArray(emotions) ? emotions : [];
  const byKey = new Map(rows.map((e) => [e.key, e]));
  const claimed = new Set();
  const out = [];
  for (const fam of FAMILIES) {
    // The TABLE's order, not the server's: a family reads as an authored set, and a
    // staged key the table doesn't list simply isn't here (it lands in More below).
    const items = fam.keys.map((k) => byKey.get(k)).filter(Boolean);
    items.forEach((e) => claimed.add(e.key));
    if (items.length) out.push({ ...fam, items });
  }
  const rest = rows.filter((e) => !claimed.has(e.key));
  if (rest.length) out.push({ ...MORE, items: rest });
  return out;
}

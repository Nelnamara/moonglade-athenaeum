/* The AI-Tools scene grid's data layer -- kept out of AiToolsModal.jsx so it can be tested
   without a React harness (loom/test/ai-tools-live-scenes.test.js), the same split the drawer's
   videoDrawerCore.js / dockLayout.js already use.

   ISSUE #36. The modal used to render this file's CURATION as the whole grid: a hardcoded 28
   tiles that could not see a scene PixAI added. `daily-fortune`, `daily-setlog` and
   `mini-mart-ad` were live on PixAI and simply had no tile -- unreachable in the UI, and the
   "All 28" count was a lie. The grid now comes from GET /api/scenes (live
   listChatEditingScenes, normalized server-side), and this file's 28 rows keep two jobs:

     1. CURATED COPY. Every human string in PixAI's catalog is an i18n key, so the server can
        only derive a label from the slug. These rows carry the shipped names and detail lines
        ("Character Style", not "Character Style Generator"; "5 classes", not "5 options") and
        are overlaid onto the live rows, so no shipped tile's copy changes.
     2. OFFLINE FALLBACK. If the fetch fails -- mirror unarmed, PixAI down, no network -- the
        grid renders these instead, so the modal is never empty.

   A scene with no curated row gets the server's derived label/shape/detail and the catalog's
   own thumbnail; that is what makes the grid self-updating. */

// [name, slug (thumbnail file), shape, tier, detail] -- from the comp's scene table (475-504),
// slugs matched to the captured scene_*.webp set.
export const CURATION = [
  ["Acrylic Standee", "acrylic-standee", "click", false, ""],
  ["Anime Badge", "anime-badge", "click", false, ""],
  ["Anime Figure", "anime-figure", "select", false, "Figure / With-char"],
  ["Blush & Glasses", "blush-and-glasses", "click", true, ""],
  ["Character Ad", "character-ad", "select", true, "Billboard / Pop-up"],
  ["Character Card", "character-card", "lang", true, "+ Other"],
  ["Character Style", "character-style-generator", "lang", true, "EN / JP / KR / TC"],
  ["Chatfic", "chatfic", "lang", true, "EN / JP / KR / TC"],
  ["Christmas", "christmas", "select", false, "Hat / Scarf / Outfit"],
  ["Dakimakura", "dakimakura", "click", false, ""],
  ["Desktop Pet", "desktop-pet", "select", true, "Landscape / Portrait"],
  ["Duo Character", "dual-character-generator", "dual", true, "2 refs · ~26 poses"],
  ["Fantasy Character", "fantasy-character", "select", true, "5 classes"],
  ["Gacha Screen", "gacha-screen", "text", true, "name + lang"],
  ["Galgame", "galgame", "text", true, "name + lang"],
  ["Giant Statue", "giant-statue", "click", false, ""],
  ["JRPG Guide", "jrpg-guidebook", "select", true, "4 classes"],
  ["Lego", "lego", "click", false, ""],
  ["Magazine Cover", "magazine-cover", "click", false, ""],
  ["Paper Cutout", "paper-cutout", "select", true, "Silhouette / Layered"],
  ["Plushie", "plushie", "click", false, ""],
  ["Polaroid", "polaroid", "text", true, "name + lang"],
  ["RPG Gameplay", "rpg-gameplay", "text", true, "name + lang"],
  ["Stadium Big Screen", "stadium-big-screen", "click", true, ""],
  ["Summer Magazine", "summer-magazine", "click", true, ""],
  ["Tarot Card", "tarot-card", "select", false, "4 modes"],
  ["Trading Card", "trading-card", "click", true, ""],
  ["VTuber", "vtuber", "text", true, "name + lang"],
];

const BY_SLUG = new Map(CURATION.map((r) => [r[1], r]));

/** One display tile. `thumb` is the CATALOG's own art (or "") -- the local
    /branding/bridge/scene_<slug>.webp is still tried first by the tile itself. */
function row(name, slug, shape, tier, detail, thumb) {
  return { name, slug, shape, tier: !!tier, detail: detail || "", thumb: thumb || "" };
}

/** The offline grid: the 28 curated tiles, exactly as they shipped. No catalog thumbnails --
    offline is precisely when those cannot load either. */
export const FALLBACK_SCENES = CURATION.map(
  ([name, slug, shape, tier, detail]) => row(name, slug, shape, tier, detail, ""));

/** Live rows from GET /api/scenes -> display tiles, curated copy overlaid, sorted the way the
    shipped grid was (alphabetical by display name). A live scene we have no curated row for
    keeps the server's derived label/shape/detail, so it gets a real tile the day it appears. */
export function mergeScenes(live) {
  const rows = (Array.isArray(live) ? live : [])
    .filter((s) => s && s.sceneId)
    .map((s) => {
      const cur = BY_SLUG.get(s.sceneId);
      return row(cur ? cur[0] : (s.label || s.sceneId),
                 s.sceneId,
                 cur ? cur[2] : (s.shape || "click"),
                 // The live membership tier is authoritative -- a scene PixAI moves behind
                 // (or out from behind) tier 1 must re-badge itself without a code change.
                 s.tier != null ? !!s.tier : !!(cur && cur[3]),
                 cur ? cur[4] : (s.detail || ""),
                 s.thumb || "");
    });
  rows.sort((a, b) => a.name.localeCompare(b.name, "en"));
  return rows;
}

/** What the grid renders. The live catalog when we have one; the curated 28 when the fetch
    failed or has not answered yet -- the modal must never open onto an empty grid. */
export function sceneRows(live) {
  const merged = mergeScenes(live);
  return merged.length ? merged : FALLBACK_SCENES;
}

// The footer's shape tally, in the order it shipped. Computed rather than written down: it
// was the string "11 one-click · 8 select · 5 text · 3 language · 1 dual", which went stale
// the moment PixAI added a scene -- the same class of bug as the grid itself.
const TALLY_ORDER = [["click", "one-click"], ["select", "select"], ["text", "text"],
                     ["lang", "language"], ["dual", "dual"]];

export function shapeTally(rows) {
  const n = {};
  (rows || []).forEach((s) => { n[s.shape] = (n[s.shape] || 0) + 1; });
  return TALLY_ORDER.filter(([k]) => n[k])
    .map(([k, word]) => n[k] + " " + word).join(" · ");
}

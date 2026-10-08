/* The goal tile's picture, as rules (Session T, Goal Tile Art Handoff T1a / T2b / T3c; issue #61).
   Pure: loom/test/goal-tile-core.test.js holds them, components/train/GoalTile.jsx draws them.

   WHERE THE PICTURE COMES FROM, in this order (T3c: pack, then module, then tint):
     1. the art pack's own copy, training/goal_<goal>.png, read through the /branding/ route like
        every other pack asset (pack v7 will carry it; until then this simply is not there);
     2. the app's own copy, art/goalTiles.js (dev/tools/art/build_goal_tiles.py), shipped in the bundle;
     3. neither loads: the flat goal tint, with no glyph and no note (the label beside the tile
        carries the meaning).
   The names are GOALS' values behind goal_ (gen/trainCore.js): goal_character, goal_style,
   goal_clothing, goal_other. */

export const PACK_DIR = "training";

// T2b's one timing that lives in script. The tint paints at once; a lavender sheen crosses it until
// the picture decodes or 3 s have passed, whichever is first. The sheen's 1.6 s loop and the
// picture's .42 s fade are CSS (styles/train.css).
export const SHEEN_STOP_MS = 3000;

export function goalArtName(goalValue) {
  return "goal_" + goalValue;
}

export function packUrl(name) {
  return "/branding/" + PACK_DIR + "/" + name + ".png";
}

/** The candidate sources for one goal, best first. `moduleArt` is art/goalTiles.js's namespace
    (or any {name: dataUri} map); a goal it has no picture for is pack-only. */
export function artSources(name, moduleArt) {
  const out = [{ from: "pack", src: packUrl(name) }];
  const own = moduleArt && moduleArt[name];
  if (typeof own === "string" && own) out.push({ from: "module", src: own });
  return out;
}

/** The first source `load(src)` says decodes, or null (the flat tint). `load` answers a Promise
    of a boolean; a rejection counts as "did not load". Later sources are not tried once one
    wins, so a pack that has the picture costs the module nothing. */
export async function resolveGoalArt(name, load, moduleArt) {
  for (const cand of artSources(name, moduleArt)) {
    let ok = false;
    try { ok = !!(await load(cand.src)); } catch (e) { ok = false; }
    if (ok) return cand;
  }
  return null;
}

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* Session T (Training goal-tile art, issue #61; Goal Tile Art Handoff T1a / T2b / T3c). The
   rules the goal tile's picture follows, held without a browser: which names the art goes by,
   which source wins (pack, then the app's own module, then the flat tint), and the three
   timings the handoff fixes. components/train/GoalTile.jsx draws them;
   dev/tests/test_render_harness.py measures the tile in a real browser once the bundle is built. */

import { GOALS } from "../../gallery/src/gen/trainCore.js";
import {
  FADE_MS, PACK_DIR, SHEEN_LOOP_MS, SHEEN_STOP_MS, artSources, goalArtName, packUrl, resolveGoalArt,
} from "../../gallery/src/lib/goalTileCore.js";
import * as MODULE_ART from "../../gallery/src/art/goalTiles.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

describe("the names", () => {
  test("goal_ plus the GOALS value: the pack's file names and the module's exports", () => {
    assert.deepEqual(GOALS.map((g) => goalArtName(g.value)),
      ["goal_character", "goal_style", "goal_clothing", "goal_other"]);
  });
  test("the module carries exactly one picture per goal, as a WebP data URI", () => {
    for (const g of GOALS) {
      const uri = MODULE_ART[goalArtName(g.value)];
      assert.match(uri, /^data:image\/webp;base64,[A-Za-z0-9+/=]{500,}$/, g.value);
    }
    const exported = Object.keys(MODULE_ART).filter((k) => k.startsWith("goal_"));
    assert.equal(exported.length, GOALS.length, "no stray exports beside GOALS'");
  });
  test("the pack serves training/<name>.png", () => {
    assert.equal(PACK_DIR, "training");
    assert.equal(packUrl("goal_style"), "/branding/training/goal_style.png");
  });
});

describe("precedence: pack, then module, then the tint", () => {
  const mod = { goal_style: "data:image/webp;base64,MODULE" };
  test("the sources come in that order, and the tint is what is left when none loads", () => {
    assert.deepEqual(artSources("goal_style", mod), [
      { from: "pack", src: "/branding/training/goal_style.png" },
      { from: "module", src: "data:image/webp;base64,MODULE" },
    ]);
    assert.deepEqual(artSources("goal_other", mod), [
      { from: "pack", src: "/branding/training/goal_other.png" },
    ], "a goal the module lacks has only the pack");
  });
  test("the pack's copy wins when it loads, and the module is never fetched", async () => {
    const tried = [];
    const got = await resolveGoalArt("goal_style", async (s) => { tried.push(s); return true; }, mod);
    assert.deepEqual(got, { from: "pack", src: "/branding/training/goal_style.png" });
    assert.equal(tried.length, 1);
  });
  test("a pack without it falls to the module", async () => {
    const got = await resolveGoalArt("goal_style", async (s) => s.startsWith("data:"), mod);
    assert.deepEqual(got, { from: "module", src: "data:image/webp;base64,MODULE" });
  });
  test("neither loading is a null: the flat tint, and no throw", async () => {
    assert.equal(await resolveGoalArt("goal_style", async () => false, mod), null);
    assert.equal(await resolveGoalArt("goal_style", async () => { throw new Error("boom"); }, mod), null);
  });
});

describe("the handoff's timings (T2b)", () => {
  test("a 1.6 s sheen loop that stops at 3 s, and a .42 s fade", () => {
    assert.equal(SHEEN_LOOP_MS, 1600);
    assert.equal(SHEEN_STOP_MS, 3000);
    assert.equal(FADE_MS, 420);
  });
});

describe("the tile draws the picture and no glyph (T1a, T2b)", () => {
  const css = src("styles/train.css");
  const block = (sel) => {
    const at = css.indexOf("\n" + sel + " {");
    assert.ok(at >= 0, "no rule for " + sel);
    return css.slice(at, css.indexOf("}", at));
  };
  test("the picture is a computed background, covering, on a child of the tint square", () => {
    const pic = block(".mgtr-goal-pic");
    assert.match(pic, /position:\s*absolute/);
    assert.match(pic, /inset:\s*0/);
    assert.match(pic, /background-size:\s*cover/);
    assert.match(pic, /animation:\s*mgtr-pic-in\s+\.42s/);
  });
  test("no frame, scrim or tint over the art: nothing paints above the picture", () => {
    const tint = block(".mgtr-goal-tint");
    assert.match(tint, /position:\s*relative/);
    assert.match(tint, /overflow:\s*hidden/);
    assert.doesNotMatch(tint, /box-shadow|outline|border:/);
    const pic = block(".mgtr-goal-pic");
    assert.doesNotMatch(pic, /opacity:\s*0?\.[0-9]+;|filter|mix-blend/);
    // the sheen is a layer BENEATH the picture: it is the loading state, not an overlay
    assert.match(block(".mgtr-goal-tint.sheen::after"), /z-index:\s*0/);
    assert.match(pic, /z-index:\s*1/);
  });
  test("the sheen loops for 1.6 s; reduced motion has neither sheen nor fade", () => {
    assert.match(css, /@keyframes mgtr-sheen/);
    assert.match(block(".mgtr-goal-tint.sheen::after"), /animation:\s*mgtr-sheen\s+1\.6s\s+linear\s+infinite/);
    const at = css.indexOf("@media (prefers-reduced-motion: reduce) { .mgtr-goal");
    assert.ok(at >= 0, "a reduced-motion rule for the goal tile");
    const rm = css.slice(at, css.indexOf("\n}", at) + 2);
    assert.match(rm, /\.mgtr-goal-tint\.sheen::after[^}]*display:\s*none/s);
    assert.match(rm, /\.mgtr-goal-pic[^}]*animation:\s*none/s);
  });
  test("no glyph: neither screen renders GOALS' mark, both render the GoalTile", () => {
    for (const file of ["components/train/TrainBasic.jsx", "components/TrainMobile.jsx"]) {
      const s = src(file);
      assert.doesNotMatch(s, /g\.mark/, file + " must not draw the glyph");
      assert.match(s, /<GoalTile\s+goal=\{g\}\s*\/>/, file);
    }
  });
  test("the fallback tint is frame 02's: one colour per goal, flat", () => {
    const want = { character: "#3a2e5a", style: "#2e4a5a", clothing: "#5a3a4a", other: "#2e5a46" };
    for (const [goal, hex] of Object.entries(want)) {
      assert.match(block(".mgtr-goal-tint.g-" + goal), new RegExp("background:\\s*" + hex + ";"), goal);
    }
    assert.match(src("components/train/GoalTile.jsx"), /"mgtr-goal-tint g-" \+ goal\.value/);
  });
  test("the phone row's picture is 44 px, beside its name and description", () => {
    const phone = readFileSync(path.join(SRC, "styles", "train-mobile.css"), "utf8");
    assert.match(phone, /\.trm-row\.goal \.mgtr-goal-tint\s*\{[^}]*width:\s*44px;\s*height:\s*44px/);
    const m = src("components/TrainMobile.jsx");
    assert.match(m, /<span className="trm-row-sub">\{g\.desc\}<\/span>/, "the phone row keeps the description");
  });
});

/* Frame 01 of the Goal Tile Art Handoff, as DRAWN (the owner picked T1a from the options page, which
   draws the same big squares): step 1's desktop goals are four square picture tiles in one row, the
   picture edge to edge under the slot radius, the label in a strip beneath it, and only the label.
   Every number below is the frame's own (tiles() in Goal Tile Art Handoff.dc.html). */
describe("the desktop goal tile, as frame 01 draws it", () => {
  const css = src("styles/train.css");
  const block = (sel) => {
    const at = css.indexOf("\n" + sel + " {");
    assert.ok(at >= 0, "no rule for " + sel);
    return css.slice(at, css.indexOf("}", at));
  };
  test("four tiles in one row, 8 px apart", () => {
    const row = block(".mgtr-goals");
    assert.match(row, /display:\s*grid/);
    assert.match(row, /grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/);
    assert.match(row, /gap:\s*8px/);
  });
  test("the tile: .82 tall-to-wide, 6 px inside a 1 px border, radius 12, the label at the foot", () => {
    const t = block(".mgtr-goal");
    assert.match(t, /aspect-ratio:\s*\.82/);
    assert.match(t, /padding:\s*6px/);
    assert.match(t, /border-radius:\s*12px/);
    assert.match(t, /border:\s*1px solid var\(--surface1\)/);
    assert.match(t, /flex-direction:\s*column/);
    assert.match(t, /justify-content:\s*flex-end/);
    assert.match(t, /font-size:\s*10px/);
    assert.match(t, /font-weight:\s*700/);
    assert.match(t, /background:\s*rgba\(33,\s*31,\s*58,\s*\.45\)/);
  });
  test("the picture fills the top 78 % edge to edge, cover; the rest is the label's strip", () => {
    const pic = block(".mgtr-goal .mgtr-goal-tint");
    assert.match(pic, /position:\s*absolute/);
    assert.match(pic, /top:\s*0/);
    assert.match(pic, /left:\s*0/);
    assert.match(pic, /width:\s*100%/);
    assert.match(pic, /height:\s*78%/);
    assert.match(pic, /border-radius:\s*0/);
  });
  test("selected keeps the lavender border and nothing else; the picture is never tinted by selection", () => {
    const on = block(".mgtr-goal.on");
    assert.match(on, /border-color:\s*var\(--lavender\)/);
    assert.doesNotMatch(on, /background/);
  });
  test("the tile shows only the label; the description is the tooltip and the accessible description", () => {
    const s = src("components/train/TrainBasic.jsx");
    const goals = s.slice(s.indexOf('<div className="mgtr-goals">'), s.indexOf("Need to edit descriptions"));
    assert.match(goals, /title=\{g\.desc\}/);
    assert.match(goals, /<span className="n">\{g\.label\}<\/span>/);
    assert.doesNotMatch(goals, /className="d"/, "no description text drawn in the tile");
    assert.doesNotMatch(css, /\.mgtr-goal \.d\b/);
  });
  test("the module's pictures are big enough for a 2x screen at that tile", async () => {
    const mod = await import("../../gallery/src/art/goalTiles.js");
    assert.ok(mod.GOAL_TILE_PX >= 264, "a ~132 px tile on a 2x screen needs 264 px or more: " + mod.GOAL_TILE_PX);
  });
});

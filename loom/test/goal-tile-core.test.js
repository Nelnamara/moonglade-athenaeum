import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* Session T (Training goal-tile art, issue #61; Goal Tile Art Handoff T1a / T2b / T3c). The
   rules the goal tile's picture follows, held without a browser: which names the art goes by,
   which source wins (pack, then the app's own module, then the flat tint), and the three
   timings the handoff fixes. components/train/GoalTile.jsx draws them;
   tests/test_render_harness.py measures the tile in a real browser once the bundle is built. */

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
      assert.match(s, /<GoalTile\s+goal=\{g\}\s+tint=\{GOAL_TINT\[i\]\}\s*\/>/, file);
    }
  });
  test("the phone row's picture is 44 px; the desktop tile keeps the 34 px it shipped with", () => {
    assert.match(block(".mgtr-goal-tint"), /width:\s*34px;\s*height:\s*34px/);
    const phone = readFileSync(path.join(SRC, "styles", "train-mobile.css"), "utf8");
    assert.match(phone, /\.trm-row\.goal \.mgtr-goal-tint\s*\{[^}]*width:\s*44px;\s*height:\s*44px/);
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* A thing the owner found on screen in Train a LoRA (walk, 2026-09-29), held at the source.
   dev/tests/test_render_harness.py measures it in a real browser once the bundle is built; this
   fails first, without one.

   "From history" drew every picture as a sliver a few pixels tall, in Basic and Advanced,
   Grouped and All. The pool's grid scrolls inside a max-height, and a tile clips its picture
   (overflow: hidden), so its automatic minimum height is 0: CSS Grid then grows auto rows
   only until they fill the cap, sharing 300 px among every row. max-content rows hold each
   row at the tile's own square height.

   (The same walk found Basic's goal tiles blank; a glyph stood in until Session T put a
   picture in each. That half of this file moved to goal-tile-core.test.js.) */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

/** The declarations of the one rule whose selector is exactly `sel`. */
function rule(css, sel) {
  const at = css.indexOf("\n" + sel + " {");
  assert.ok(at >= 0, "no rule for " + sel);
  return css.slice(at, css.indexOf("}", at));
}

describe("the From history pool draws square tiles", () => {
  const css = src("styles/train.css");
  test("its rows are max-content, so a capped, scrolling grid cannot crush them", () => {
    const grid = rule(css, ".mgtr-pool-grid");
    assert.match(grid, /grid-auto-rows:\s*max-content/);
    assert.match(grid, /max-height:\s*300px/, "the cap the rows are sized against is still there");
    assert.match(grid, /overflow-y:\s*auto/, "the grid is still its own scroller (the paging sentinel's root)");
  });
  test("a tile is still a square that clips its picture", () => {
    const tile = rule(css, ".mgtr-pool-tile");
    assert.match(tile, /aspect-ratio:\s*1/);
    assert.match(tile, /overflow:\s*hidden/);
  });
});

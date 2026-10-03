import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { pagerInView, showNewest } from "../../gallery/src/lib/phoneCore.js";

/* The owner's walk, 2026-10-03: at the bottom of the phone gallery the floating "↑ Newest" sat on top
   of the pager row ("‹ Prev · Page 1 of 380 · 37,917 matches · Next ›") and hid its middle, upright
   and sideways. The phone handoffs draw the jump with no pager under it, so they do not settle it;
   the rule is the brief's: while the pager row is on screen -- where the page ends anyway -- the jump
   steps aside. showNewest's one-screen rule is unchanged. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (rel) => readFileSync(path.join(here, "..", "..", "gallery", "src", rel), "utf8").split("\r\n").join("\n");

describe("pagerInView: is any of the pager row inside the scroller's visible box?", () => {
  const view = { top: 120, bottom: 760 };
  test("on screen, wholly or in part", () => {
    assert.equal(pagerInView({ top: 700, bottom: 744 }, view), true);
    assert.equal(pagerInView({ top: 750, bottom: 794 }, view), true, "its top edge peeking in counts");
    assert.equal(pagerInView({ top: 100, bottom: 130 }, view), true);
  });
  test("below or above the visible box, or not there at all", () => {
    assert.equal(pagerInView({ top: 760, bottom: 804 }, view), false);
    assert.equal(pagerInView({ top: 2000, bottom: 2044 }, view), false);
    assert.equal(pagerInView({ top: 60, bottom: 120 }, view), false);
    assert.equal(pagerInView(null, view), false);
    assert.equal(pagerInView({ top: 700, bottom: 744 }, null), false);
  });
  test("the one-screen rule itself is unchanged", () => {
    assert.equal(showNewest(601, 600), true);
    assert.equal(showNewest(600, 600), false);
  });
});

describe("the gallery asks both questions", () => {
  test("the jump shows after a screen of scrolling AND only while the pager row is not on screen", () => {
    const g = src("components/GalleryMobile.jsx");
    assert.match(g, /showNewest\(host\.scrollTop, host\.clientHeight\)\s*&&\s*!pagerInView\(/);
    assert.match(g, /querySelector\("\.glm-pager"\)/);
  });
});

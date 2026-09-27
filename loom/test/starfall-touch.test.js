// The code's touch form (gallery/src/moments/touchCode.js): eight swipes and two taps, read
// passively. The classifier and the matcher are pure, so these run without a browser.
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { TOUCH_SEQ, GAP_MS, classify, createMatcher } from "../../gallery/src/moments/touchCode.js";

describe("classify: one gesture", () => {
  test("swipes read by their dominant axis; a finger moving up is up", () => {
    assert.equal(classify(0, -120, 200, false), "U");
    assert.equal(classify(0, 120, 200, false), "D");
    assert.equal(classify(-120, 10, 200, false), "L");
    assert.equal(classify(120, -10, 200, false), "R");
  });
  test("a tap off a control is T; on a control it breaks the sequence (X)", () => {
    assert.equal(classify(3, 2, 120, false), "T");
    assert.equal(classify(3, 2, 120, true), "X");
  });
  test("slow drags and long presses are neither", () => {
    assert.equal(classify(0, -120, 2000, false), null);
    assert.equal(classify(2, 2, 900, false), null);
    assert.equal(classify(20, 20, 100, false), null);
  });
});

describe("the matcher: the code, in order", () => {
  const run = (gs, step = 200) => {
    const m = createMatcher();
    let t = 0, hits = 0;
    for (const g of gs) { t += step; if (m(g, t)) hits++; }
    return hits;
  };
  test("the full code completes exactly once", () => {
    assert.deepEqual(TOUCH_SEQ, ["U", "U", "D", "D", "L", "R", "L", "R", "T", "T"]);
    assert.equal(run(TOUCH_SEQ), 1);
  });
  test("a wrong gesture restarts it; a leading up counts as the first step", () => {
    assert.equal(run(["U", "U", "D", "L", ...TOUCH_SEQ]), 1);
    assert.equal(run(["U", ...TOUCH_SEQ]), 1);
    assert.equal(run(TOUCH_SEQ.slice(0, 9).concat(["X", "T"])), 0, "a tap on a control breaks it");
  });
  test("a pause longer than the gap starts over", () => {
    const m = createMatcher();
    let t = 0, hits = 0;
    TOUCH_SEQ.forEach((g, i) => { t += i === 5 ? GAP_MS + 1 : 200; if (m(g, t)) hits++; });
    assert.equal(hits, 0);
  });
});

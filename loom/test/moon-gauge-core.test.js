import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* The moon gauge (Small Calls handoff L4; DECISIONS 2026-09-28 "The moon gauge fills only on a
   true fraction"). The readers answer null for anything that is not a real fraction, and the
   component draws nothing for null -- that is how a generation, which reports no progress,
   can never grow a gauge. */

import {
  GAUGE_SIZES, fractionFromPercent, fractionOf, gaugePhase, moonFrame, percentText,
} from "../../gallery/src/lib/moonGaugeCore.js";

describe("only true fractions", () => {
  test("a count out of a known total", () => {
    assert.equal(fractionOf(7, 10), 0.7);
    assert.equal(fractionOf("3", "4"), 0.75);
    assert.equal(fractionOf(12, 10), 1);          // clamped, never past full
    assert.equal(fractionOf(-1, 10), 0);
  });
  test("no total, or a total of nothing, is not a fraction", () => {
    for (const [d, t] of [[3, 0], [3, -2], [3, null], [3, undefined], [null, 10], ["x", 10], [3, ""]]) {
      assert.equal(fractionOf(d, t), null, JSON.stringify([d, t]));
    }
  });
  test("a reported percentage", () => {
    assert.equal(fractionFromPercent(62), 0.62);
    assert.equal(fractionFromPercent("100"), 1);
    assert.equal(fractionFromPercent(140), 1);
    for (const v of [null, undefined, "", "abc", NaN]) assert.equal(fractionFromPercent(v), null);
  });
});

describe("phase and reading", () => {
  test("the nearest of the strip's frames, new to full", () => {
    assert.equal(moonFrame(0, 17), 0);
    assert.equal(moonFrame(1, 17), 16);
    assert.equal(moonFrame(0.5, 17), 8);
    assert.equal(moonFrame(0.62, 17), 10);        // 9.92 -> 10
    assert.equal(moonFrame(0.03, 17), 0);
    assert.equal(moonFrame(0.04, 17), 1);
    assert.equal(moonFrame(NaN, 17), 0);
  });
  test("the glow is for finished only; 0 is the new-moon outline", () => {
    assert.equal(gaugePhase(0), "new");
    assert.equal(gaugePhase(0.999), "wax");
    assert.equal(gaugePhase(1), "full");
  });
  test("the exact reading never says 100% early", () => {
    assert.equal(percentText(0.62), "62%");
    assert.equal(percentText(0.999), "99%");
    assert.equal(percentText(1), "100%");
    assert.equal(percentText(0), "0%");
  });
  test("the handoff's four sizes", () => {
    assert.deepEqual({ ...GAUGE_SIZES }, { folio: 16, runs: 16, strip: 18, phone: 14 });
  });
});

describe("the component", () => {
  const src = readFileSync(new URL("../../gallery/src/components/MoonGauge.jsx", import.meta.url), "utf8");
  test("draws nothing for a non-fraction", () => {
    assert.match(src, /if \(typeof fraction !== "number" \|\| !Number\.isFinite\(fraction\)\) return null;/);
  });
  test("the BAR9 art ships in the app build, set once, not per instance", () => {
    const art = readFileSync(new URL("../../gallery/src/art/moonGauge.js", import.meta.url), "utf8");
    for (const name of ["MOON_PHASES", "BAR_LEFT", "BAR_RAIL", "BAR_RIGHT"]) {
      assert.match(art, new RegExp("export const " + name + " = \"data:image/webp;base64,"));
    }
    assert.match(src, /let injected = false;/);
    assert.doesNotMatch(src, /style=\{\{[^}]*MOON_PHASES/);
  });
});

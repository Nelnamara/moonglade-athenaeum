import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner, 2026-07-27, with a screenshot of an imported A-02 card: "I still say the small outer
// focus shot cards are too small... Just needs a nudge taller to see the proper side thumbnail."
//
// The frame was NOT missing -- this landed right after imported clips started getting real
// first/last frames -- it was being cropped out of view. .lv-cframe is object-fit:cover inside
// a card whose content width is 144px at the narrowest column (.lv-cards minmax(158px) minus
// .lv-card's 7px padding either side). A 16:9 frame wants ~81px at that width and a 2048x1072
// clip wants ~75px, so a 48px box discarded ~40% of the height and showed a middle band.
//
// This is a plain source-text check: master-storyboard.jsx has no JSX render harness in this
// suite, and its CSS lives in a template literal inside the component. Same technique as
// loom-df-veil-stacking.test.js. The point is not to freeze a number -- it is that the number
// and the geometry it was derived from must move TOGETHER, because 48px looked perfectly
// deliberate until someone measured it against the card.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

const decl = (sel) => {
  const m = src.match(new RegExp("\\" + sel + "\\{([^}]*)\\}"));
  assert.ok(m, sel + " not found -- the selector was renamed, so this guard is now blind");
  return m[1];
};
const px = (body, prop) => {
  const m = body.match(new RegExp(prop + ":\\s*(\\d+)px"));
  assert.ok(m, prop + " not found in: " + body);
  return Number(m[1]);
};

describe("a board card's frame is tall enough to actually show the frame", () => {
  test("the narrowest card column still leaves 144px of frame width", () => {
    // If either of these changes, the height below stops being the right number.
    const cards = decl(".lv-cards");
    const card = decl(".lv-card");
    const minCol = Number(cards.match(/minmax\((\d+)px/)[1]);
    const pad = px(card, "padding");
    assert.equal(minCol, 158);
    assert.equal(pad, 7);
    assert.equal(minCol - pad * 2, 144);
  });

  test(".lv-cframe is tall enough for a 16:9 frame at that width", () => {
    const h = px(decl(".lv-cframe"), "height");
    const need16by9 = Math.round(144 * 9 / 16);          // 81
    // Allow a hair under the exact 16:9 ideal (a 1-2px crop is invisible), but nothing like
    // the 48px that prompted this -- that cropped ~40% of the height away.
    assert.ok(h >= need16by9 - 3,
      `.lv-cframe height ${h}px crops a 16:9 frame at 144px wide (needs ~${need16by9}px)`);
    // And it must clear the owner's own footage shape: 2048x1072 -> 144/1.910 = 75px.
    assert.ok(h >= Math.round(144 / (2048 / 1072)),
      `.lv-cframe height ${h}px crops a 2048x1072 clip`);
  });

  test("cover is deliberate, so the height is what governs how much frame you see", () => {
    // With object-fit:cover the box height IS the crop. If this ever becomes `contain`, the
    // height requirement above stops being a correctness claim and this guard should be
    // rewritten rather than quietly relaxed.
    assert.match(decl(".lv-cframe img"), /object-fit:\s*cover/);
  });
});

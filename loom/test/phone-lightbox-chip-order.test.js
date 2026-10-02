import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// THE PHONE LIGHTBOX'S CHIP ROW (owner walk 2026-09-29). At 390px only four chips show before the
// row scrolls; with ⁂ Make a recipe between Similar and Upscale, Upscale fell out of view and
// Details › needed a sideways swipe. The design's five come first -- ✎ Edit · ▶ To Video ·
// ◈ Similar · ⇱ Upscale · Details › -- then the app's extras. And, as on every other surface
// (upscale-stills-only.test.js), Upscale is not offered on a video.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const lb = src("gallery/src/components/LightboxMobile.jsx");

function row() {
  const open = '<div className="lbm-actsrow">';
  const i = lb.indexOf(open);
  assert.ok(i >= 0, "the phone Lightbox has its action row");
  const end = lb.indexOf('<div className="lbm-hint">', i);
  assert.ok(end > i, "the hint follows the row");
  return lb.slice(i, end);
}

test("the design's five come first, in the design's order, then the extras", () => {
  const r = row();
  const at = (s) => { const k = r.indexOf(s); assert.ok(k >= 0, s + " is on the row"); return k; };
  const order = [">✎ Edit<", ">▶ To Video<", ">◈ Similar<", ">⇱ Upscale<", ">Details ›<",
    "<MakeRecipeChip", ">★ Enter contest<", '"▶ Slideshow"'].map(at);
  for (let k = 1; k < order.length; k++) {
    assert.ok(order[k] > order[k - 1], "chip " + k + " comes after chip " + (k - 1));
  }
});

test("Upscale is offered on a still only", () => {
  assert.match(row(), /\{!it\.is_video \? \(\n\s*<button type="button" className=\{"lbm-chip" \+ \(sheetOpen \? " on" : ""\)\} onClick=\{toggleUpscale\}>⇱ Upscale<\/button>\n\s*\) : null\}/);
});

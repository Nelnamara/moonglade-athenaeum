import { test } from "node:test";
import assert from "node:assert/strict";
import { boxesToOriginal, scaleBoxes } from "../../gallery/src/gen/editCore.js";

/* #96: on the phone the Loom's Fixer drew on the 768-px thumbnail and scaled the boxes by that
   picture's naturalWidth, so on any larger picture PixAI was sent a smaller box in the wrong
   place -- and the repair it charged for landed somewhere else. The fix: one scaler with the
   picture's REAL width as an explicit argument. These are the pure-function reproduction. */

const box = [{ x: 100, y: 50, w: 60, h: 40, tag: "face" }];

test("boxesToOriginal scales by the original picture's width over the shown width", () => {
  // a 1536 x 864 picture shown 360 px wide
  assert.deepEqual(boxesToOriginal(box, 360, 1536), [{ x: 427, y: 213, width: 256, height: 171, tag: "face" }]);
});

test("the bug it fixes: scaling by the 768-px thumbnail sends a half-size box in the wrong place", () => {
  const right = boxesToOriginal(box, 360, 1536);
  const thumb = boxesToOriginal(box, 360, 768);   // what master sent: the thumbnail as the original
  assert.equal(thumb[0].x, 213);
  assert.notDeepEqual(thumb, right);
  assert.ok(thumb[0].width < right[0].width);
});

test("a missing width on either side is null -- a refusal, never the old scale-1 fallback", () => {
  assert.equal(boxesToOriginal(box, 0, 1536), null);
  assert.equal(boxesToOriginal(box, 360, 0), null);
  assert.equal(boxesToOriginal(box, undefined, 1536), null);
  assert.equal(boxesToOriginal(box, 360, null), null);
});

test("scaleBoxes (FixTab and the desktop Loom) keeps its behaviour: the <img>'s own scale, scale 1 without one", () => {
  assert.deepEqual(scaleBoxes(box, { clientWidth: 360, naturalWidth: 1536 }), boxesToOriginal(box, 360, 1536));
  // master's scale-1 fallback, unchanged for the surfaces that draw on /full/<id>
  assert.deepEqual(scaleBoxes(box, null), [{ x: 100, y: 50, width: 60, height: 40, tag: "face" }]);
  assert.deepEqual(scaleBoxes(box, { clientWidth: 0, naturalWidth: 1536 }), [{ x: 100, y: 50, width: 60, height: 40, tag: "face" }]);
  // master's arithmetic byte for byte: Math.round(v * (natural / client)), including a not-yet-decoded
  // picture (naturalWidth 0) under a laid-out one, which zeroes every box exactly as before
  const masterScale = (boxes, img) => {
    const s = img && img.clientWidth ? (img.naturalWidth / img.clientWidth) : 1;
    return boxes.map((b) => ({ x: Math.round(b.x * s), y: Math.round(b.y * s), width: Math.round(b.w * s), height: Math.round(b.h * s), tag: b.tag }));
  };
  const many = [{ x: 33, y: 17, w: 81, h: 57, tag: "hand" }, { x: 0.5, y: 2.5, w: 7.5, h: 12.5, tag: "face" }];
  for (const img of [{ clientWidth: 360, naturalWidth: 1536 }, { clientWidth: 412, naturalWidth: 2560 },
    { clientWidth: 777, naturalWidth: 1000 }, { clientWidth: 400, naturalWidth: 0 }, { clientWidth: 0, naturalWidth: 900 }, null]) {
    assert.deepEqual(scaleBoxes(many, img), masterScale(many, img), JSON.stringify(img));
  }
});

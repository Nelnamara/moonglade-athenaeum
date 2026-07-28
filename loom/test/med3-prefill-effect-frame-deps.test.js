import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The prefill effect's dependency list must cover the FRAMES (2026-07-27, closing-frame
   pass). Every branch of that effect reads c.openFrame/c.closeFrame -- i2v/flf hand them
   to the drawer directly, r2v folds them in through buildShotPayload() -- yet no frame
   field was a dependency, so attaching or replacing a frame never re-ran the prefill: the
   drawer kept showing (and pricing, and submitting) the bank from BEFORE the change until
   an unrelated dep -- `tab`, usually -- happened to fire the effect. That is the owner's
   "toggling a tab fixes the missing frame" symptom, and behind it the quieter one: a
   picker pick reports a bank SLOT INDEX, and the host resolves that index against the
   fresh list (pickTarget) while the drawer's bank was stale -- slot N names a different
   entity on each side, the reference-picker-corruption class.

   This runner has no jsdom (see mg-generate-drawer-concurrent.test.js's comment), so a
   React effect's firing can't be exercised here; what CAN be pinned is the dependency
   list itself, the same way loom-picker-frame-video-persistence.test.js pins the
   mg-pick-request wiring. The pin is on the frames' IDENTITY fields
   (mediaId/thumbId/source -- exactly what resolvedImage()/shotImageRefs() resolve a
   picture from), NOT the frame objects: FrameSlot's desc/tag inputs mint a fresh frame
   object per keystroke, and re-prefilling per keystroke of text that cannot change which
   image is attached is churn the effect's own comment forbids. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

// The prefill effect is the one that ends with `el.prefill(payload);` followed by its
// dependency array. Capture that array's text (comments included -- we match names only).
const m = jsx.match(/el\.prefill\(payload\);\s*\n\s*\/\/ eslint-disable-next-line react-hooks\/exhaustive-deps\s*\n\s*\}, \[([\s\S]*?)\]\);/);

describe("the prefill effect depends on the frames' identity fields", () => {
  test("the effect (el.prefill(payload) + deps array) is still recognizable", () => {
    assert.ok(m, "could not locate the prefill effect's dependency array in " +
      "master-storyboard.jsx -- if the effect was restructured, update this pattern, " +
      "don't delete the test");
  });

  for (const frame of ["openFrame", "closeFrame"]) {
    for (const field of ["mediaId", "thumbId", "source"]) {
      test(`${frame}.${field} is a dependency`, () => {
        assert.ok(m, "prefill effect not found (see the first test)");
        const re = new RegExp("active\\.c\\." + frame + "[^\\n]*\\)\\." + field);
        assert.match(m[1], re,
          `the prefill effect must re-run when ${frame}'s ${field} changes -- without it, ` +
          `a frame change reaches the drawer only when an unrelated dependency fires`);
      });
    }
  }
});

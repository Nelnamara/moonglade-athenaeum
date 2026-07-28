import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The Folio-of-Honors carousel auto-rotates on a 3.5s setInterval, stored in _actTimer.
// renderCarousel() and renderGrid() each clear it before re-arming, so it is well behaved
// while the modal is OPEN -- but Ach.close() never cleared it. Dismissing the modal left the
// interval firing forever, rebuilding hidden DOM every 3.5 seconds for the life of the page,
// and once MORE per time the modal had been opened.
//
// Invisible without a profiler, which is exactly why it needs a guard: nothing on screen
// changes, the page just does steadily more work the longer it is used.
//
// close() is also the Escape-key path, so it is the single exit every route out of the modal
// passes through -- which is why the clear belongs there and not on the X button alone.

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(HERE, "..", "..", "static", "mg-notify.js"), "utf8");

function bodyOf(name) {
  const i = SRC.indexOf("function " + name + "()");
  assert.ok(i !== -1, name + "() not found -- was it renamed?");
  // Up to the next top-level `function ` at the same indent, which is enough to bound it.
  const next = SRC.indexOf("\n    function ", i + 1);
  return SRC.slice(i, next === -1 ? i + 1200 : next);
}

describe("Folio carousel timer", () => {
  test("Ach.close() stops the auto-rotate interval", () => {
    const close = bodyOf("close");
    assert.match(close, /clearInterval\(_actTimer\)/,
      "closing the achievements modal must stop the carousel; otherwise the interval keeps " +
      "firing every 3.5s and rebuilding hidden DOM for the life of the page");
    assert.match(close, /_actTimer\s*=\s*null/,
      "and null it, so a later close cannot clear an id that is no longer live");
  });

  test("the timer is still armed and re-cleared by the renderers", () => {
    // The fix must not have been 'achieved' by deleting the carousel's rotation.
    assert.match(SRC, /_actTimer\s*=\s*setInterval\(/, "the carousel should still auto-rotate");
    const clears = SRC.match(/clearInterval\(_actTimer\)/g) || [];
    assert.ok(clears.length >= 3,
      "renderCarousel, renderGrid and close should each clear it; found " + clears.length);
  });
});

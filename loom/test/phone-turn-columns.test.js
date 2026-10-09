import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { LANDSCAPE_QUERY, TURN_SETTLE_MS } from "../../gallery/src/lib/phoneCore.js";

/* The owner's walk, 2026-10-03: after the phone was held sideways, the upright gallery kept the
   sideways column count -- a column hung off the right edge and the page scrolled sideways. A phone can
   deliver a turn's events while the orientation query still answers for the old way up, and fire
   nothing once it settles; the columns were read only on those events. The render harness reproduces
   it (test_a_turn_back_upright_puts_the_phone_grid_back_to_two_columns, with a lagging turn); these pin
   the pieces: the re-read after the turn settles, and the CSS that holds an upright phone to two
   columns whatever the script last read. (The column choice itself is pinned in phone-landscape.test.js.) */

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.join(here, "..", "..", "gallery", "src", rel), "utf8").split("\r\n").join("\n");

describe("a turn is read again once it has settled", () => {
  const hook = read("hooks/usePhoneLandscape.js");
  test("the delays are short and rising", () => {
    assert.ok(TURN_SETTLE_MS.length >= 2);
    assert.ok(TURN_SETTLE_MS.every((ms, i) => ms > 0 && ms <= 1500 && (i === 0 || ms > TURN_SETTLE_MS[i - 1])));
  });
  test("every turn event reads now, on the next frame and at each delay", () => {
    assert.match(hook, /const settle = \(\) => \{\s*sync\(\);/);
    assert.match(hook, /requestAnimationFrame\(\(\) => \{ raf = 0; sync\(\); \}\)/);
    assert.match(hook, /TURN_SETTLE_MS\.map\(\(ms\) => setTimeout\(sync, ms\)\)/);
    for (const ev of [/window\.addEventListener\("resize", settle\)/, /window\.addEventListener\("orientationchange", settle\)/,
      /mql\.addEventListener\("change", settle\)/, /vv\.addEventListener\("resize", settle\)/]) {
      assert.match(hook, ev);
    }
  });
  test("and lets every timer go when the gallery goes", () => {
    assert.match(hook, /timers\.forEach\(clearTimeout\);\s*\};\s*\}, \[\]\);/);
  });
});

describe("the CSS backstop", () => {
  const css = read("styles/gallery-mobile.css");
  test("outside the landscape condition the sideways grid is two shrinkable tracks", () => {
    const rule = "@media not all and " + LANDSCAPE_QUERY + " {\n"
      + "  .glm-grid.glm-grid-rows { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }";
    assert.ok(css.includes(rule), "gallery-mobile.css holds an upright phone to two shrinkable columns");
  });
  test("the library's scroller never scrolls sideways", () => {
    assert.match(css, /\.glm-body \{[^}]*overflow-x: hidden;/);
  });
});

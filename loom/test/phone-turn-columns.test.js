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

describe("the ?turndebug readout (#75)", () => {
  const hook = read("hooks/usePhoneLandscape.js");
  test("it starts only behind ?turndebug and leaves with the gallery", () => {
    assert.match(hook, /\/\[\?&\]turndebug\\b\/\.test\(window\.location\.search \|\| ""\) \? startTurnDebug\(\(\) => safe\) : null/);
    assert.match(hook, /if \(stopDebug\) stopDebug\(\);/);
    assert.match(hook, /return \(\) => \{ clearInterval\(timer\); box\.remove\(\); \};/);
  });
  test("it shows the grid's resolved tracks, the reading that found #75", () => {
    assert.match(hook, /getComputedStyle\(grid\)\.gridTemplateColumns/);
  });
  test("it also shows the safe areas, the screen and whether the sides count as kept (#73)", () => {
    assert.match(hook, /"safe L T R B " \+ sf\.l \+ " " \+ sf\.t \+ " " \+ sf\.r \+ " " \+ sf\.b/);
    assert.match(hook, /"  screen " \+ screen\.width \+ "x" \+ screen\.height/);
    assert.match(hook, /"  sides kept " \+ \(sf\.kept \? "yes" : "no"\)/);
  });
});

describe("the side room is counted once (#73)", () => {
  const hook = read("hooks/usePhoneLandscape.js");
  test("every read sets the attribute from the window's shape, never from an angle", () => {
    assert.match(hook, /de\.toggleAttribute\("data-mg-sides-kept", kept\)/);
    assert.match(hook, /const sync = \(\) => \{\s*readSafe\(\);/);
    assert.match(hook, /const landscape = read\(\)\.landscape;/);
    assert.match(hook, /sidesKept\(\{ landscape, innerW: window\.innerWidth/);
    assert.doesNotMatch(hook.replace(/\/\*[\s\S]*?\*\//g, ""), /screen\.orientation|window\.orientation|\.angle/);
  });
  test("the four insets come from one hidden probe, made once and removed with the hook", () => {
    assert.equal((hook.match(/document\.createElement\("div"\)/g) || []).length, 1);
    assert.match(hook, /padding:env\(safe-area-inset-top\) env\(safe-area-inset-right\) env\(safe-area-inset-bottom\) env\(safe-area-inset-left\)/);
    assert.match(hook, /visibility:hidden;pointer-events:none/);
    assert.match(hook, /probe\.remove\(\);/);
  });
  test("the attribute comes off when the last phone-shell user goes, never while another lives", () => {
    assert.match(hook, /if \(--live === 0\) \{ de\.removeAttribute\("data-mg-sides-kept"\); de\.removeAttribute\("data-mg-slide"\); \}/);
    assert.match(hook, /live \+= 1;/);
  });
  test("the slide is asked for only when the state flips while the phone was already sideways", () => {
    assert.match(hook, /if \(wasLandscape && landscape && de\.hasAttribute\("data-mg-sides-kept"\) !== kept\) \{\s*de\.setAttribute\("data-mg-slide", ""\);/);
    assert.match(hook, /setTimeout\(\(\) => de\.removeAttribute\("data-mg-slide"\), 700\)/);
    assert.match(hook, /de\.removeAttribute\("data-mg-slide"\)/);
  });
  test("it is only ever set under the landscape query, so an upright phone never carries it", () => {
    // sidesKept's first test is `landscape`, and the hook feeds it read().landscape (the media query's answer)
    const core = read("lib/phoneCore.js");
    assert.match(core, /export function sidesKept\([^)]*\) \{\s*if \(!landscape\) return false;/);
    assert.match(read("styles/phone-landscape.css"), /:root\[data-mg-sides-kept\] \{ --mg-safe-l: 0px; --mg-safe-r: 0px; \}/);
  });
});

describe("the CSS backstop", () => {
  const css = read("styles/gallery-mobile.css");
  test("outside the landscape condition the sideways grid is two shrinkable tracks", () => {
    const rule = "@media not all and " + LANDSCAPE_QUERY + " {\n"
      + "  .glm-grid.glm-grid-rows { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }";
    assert.ok(css.includes(rule), "gallery-mobile.css holds an upright phone to two shrinkable columns");
  });
  test("the upright grid's two tracks size from the grid, never from their tiles (#75)", () => {
    assert.match(css, /\.glm-grid \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
    assert.doesNotMatch(css, /\.glm-grid \{[^}]*grid-template-columns: 1fr 1fr;/);
    assert.match(css, /\.glm-col \{[^}]*min-width: 0;/);
  });
  test("the library's scroller never scrolls sideways", () => {
    assert.match(css, /\.glm-body \{[^}]*overflow-x: hidden;/);
  });
});

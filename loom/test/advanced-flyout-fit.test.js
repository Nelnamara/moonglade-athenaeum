import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// THE ADVANCED FLYOUT NEVER RUNS OFF THE SCREEN (owner walk 2026-09-29). On a 1600x900 window
// (a 708px page) its last row -- Clear · Contact sheet · Export view · Apply · ✕ -- sat below the
// screen, and the wheel scrolled the grid behind it. The flyout now measures its own top, is
// capped at the rest of the visible height, scrolls inside, keeps that action row stuck to its
// bottom, and spends a wheel it cannot use instead of passing it to the page.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const fly = src("gallery/src/components/Flyout.jsx");
const shell = src("gallery/src/styles/shell.css");
const sheet = src("gallery/src/styles.css");

describe("Flyout.jsx measures itself and owns its wheel", () => {
  test("its top is measured before paint and again on resize, and handed to CSS as --fly-top", () => {
    assert.match(fly, /useLayoutEffect\(\(\) => \{\n\s*const fit = \(\) => \{ if \(flyRef\.current\) setTop\(Math\.round\(flyRef\.current\.getBoundingClientRect\(\)\.top\)\); \};/);
    assert.match(fly, /window\.addEventListener\("resize", fit\);/);
    assert.match(fly, /window\.removeEventListener\("resize", fit\);/);
    assert.match(fly, /<div className="fly" role="dialog" aria-label="Advanced search" ref=\{flyRef\}\n\s*style=\{top != null \? \{ "--fly-top": top \+ "px" \} : undefined\}>/);
  });

  test("a wheel it cannot use is stopped, natively and non-passively, and zoom is left alone", () => {
    assert.match(fly, /el\.addEventListener\("wheel", onWheel, \{ passive: false \}\);/);
    assert.match(fly, /if \(!e\.deltaY \|\| e\.ctrlKey\) return;/);
    assert.match(fly, /const room = e\.deltaY > 0 \? el\.scrollHeight - el\.clientHeight - el\.scrollTop : el\.scrollTop;\n\s*if \(room < 1\) e\.preventDefault\(\);/);
  });

  test("the action row is still the flyout's last child, so it is the part that sticks", () => {
    const ft = fly.indexOf('<div className="flyft">');
    assert.ok(ft > fly.indexOf('<div className="flygrid">'), "the footer follows the fields");
    assert.match(fly.slice(ft), /<\/div>\n\s*<\/div>\n\s*\);\n\}\s*$/);
  });
});

describe("shell.css caps it at the visible height and pins its action row", () => {
  test("capped at the rest of the screen below its own top, scrolling inside, never chaining out", () => {
    assert.match(shell, /\.mgx-libslot \.fly \{ overflow-y: auto; overscroll-behavior: contain; padding-bottom: 0;/);
    assert.match(shell, /max-height: max\(180px, calc\(100vh - var\(--fly-top, 0px\) - 12px\)\);/);
    assert.match(shell, /max-height: max\(180px, calc\(100dvh - var\(--fly-top, 0px\) - 12px\)\);/);
  });

  test("the action row sticks to the bottom on the flyout's own ground, carrying its bottom padding", () => {
    assert.match(shell, /\.mgx-libslot \.fly \.flyft \{ position: sticky; bottom: 0; z-index: 1; padding-bottom: 11px;\n\s*background: var\(--mantle\); \}/);
    // the ground it paints is the flyout's own, and the padding it carries is the one the
    // flyout gives up -- so at rest it looks exactly as before
    assert.match(sheet, /\.fly \{[^}]*background: var\(--mantle\);/);
    assert.match(sheet, /\.fly \{[^}]*padding: 12px 13px 11px;/);
  });

  test("the rules outrank styles.css, which loads after every component sheet", () => {
    // main.jsx imports styles.css LAST, so an equal-specificity rule elsewhere would lose to it
    const main = src("gallery/src/main.jsx");
    assert.ok(main.indexOf('import "./styles.css";') > main.indexOf('import App from "./App.jsx";'));
    assert.match(sheet, /\n\.fly \{ position: absolute;/);
    assert.match(sheet, /\n\.flyft \{ display: flex;/);
    // .mgx-libslot is where the bar (and so the flyout) is mounted
    const banner = src("gallery/src/components/Banner.jsx");
    assert.match(banner, /<div className="mgx-libslot">\{libraryBar \|\| null\}<\/div>/);
  });
});

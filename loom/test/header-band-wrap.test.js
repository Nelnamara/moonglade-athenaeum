import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// THE HEADER ON AN IPAD (owner walk 2026-09-29). The iPad runs the desktop build, and at 820px
// the banner's right column (stat pills over ? · Generate · The Loom · Folio, flex:none) left the
// library column ~350px; its bar could not wrap, so Select, Actions and the layout cells ran on
// under Generate, and with Filters open the Operators chips went under the IMAGES pill. Two
// rules hold it now, and these guards pin both: below 1181px the band stacks into rows, and the
// bar wraps wherever a row runs short -- down to the 521px line where the phone build takes over.
// Source guards, like details-actions.test.js; the orchestrator's live walk is the pixel check.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const shell = src("gallery/src/styles/shell.css");
const bar = src("gallery/src/styles/librarybar.css");

// the body of the first `@media (max-width: 1180px)` block
function tabletBlock() {
  const i = shell.indexOf("@media (max-width: 1180px) {");
  assert.ok(i >= 0, "shell.css has the tablet block for the banner's band");
  let depth = 0;
  for (let k = shell.indexOf("{", i); k < shell.length; k++) {
    if (shell[k] === "{") depth++;
    else if (shell[k] === "}" && --depth === 0) return shell.slice(i, k + 1);
  }
  throw new Error("the tablet block never closes");
}

describe("below 1181px the band's two columns become rows", () => {
  const block = tabletBlock();

  test("the band stacks, the right column on top and the library below it at full width", () => {
    assert.match(block, /\.mgx-bottom \{[^}]*flex-direction: column-reverse;[^}]*align-items: stretch;/);
    // DOM order is library then right column, so column-reverse is what puts the buttons on top
    const banner = src("gallery/src/components/Banner.jsx");
    assert.ok(banner.indexOf('className="mgx-libslot"') < banner.indexOf('className="mgx-bnrright"'),
      "the library slot comes first in the band's markup");
  });

  test("stats and actions share one right-aligned row when they fit, and wrap when they do not", () => {
    assert.match(block, /\.mgx-bnrright \{[^}]*flex-direction: row;[^}]*flex-wrap: wrap;[^}]*justify-content: flex-end;/);
    assert.match(block, /\.mgx-statsrow, \.mgx-actrow \{ flex-wrap: wrap; \}/);
  });

  test("the tablet line sits above an iPad Pro and the 521px phone line sits under every tablet", () => {
    // iPad mini 744, iPad Air 820, iPad Pro 1024 (portrait) all fall inside the block
    const max = Number((shell.match(/@media \(max-width: (\d+)px\) \{\n  \.mgx-bottom/) || [])[1]);
    assert.ok(max >= 1024 && max < 1280, "the stacking line covers the iPads and spares a 1280 desktop: " + max);
    const hook = src("gallery/src/hooks/useIsMobile.js");
    assert.match(hook, /const MOBILE_QUERY = "\(max-width: 520px\)";/);
  });

  test("above the line the hero band is the drawn one: side by side, the right column never shrinks", () => {
    assert.match(shell, /\n\.mgx-bottom \{ position: relative; z-index: 2; display: flex; align-items: flex-end;/);
    assert.match(shell, /\n\.mgx-bnrright \{ flex: none; display: flex; flex-direction: column; align-items: flex-end;/);
    assert.match(shell, /\n\.mgx-libslot \{ flex: 1 1 auto; min-width: 0; \}/);
  });
});

describe("the library bar wraps rather than running on under anything", () => {
  test("the bar row wraps", () => {
    assert.match(bar, /\n\.mgl-bar \{ display: flex; flex-wrap: wrap;/);
    assert.doesNotMatch(bar, /\.mgl-bar \{[^}]*nowrap/);
  });

  test("the search slab starts at 170px and grows to its old 320px, so a bar that fits keeps one row", () => {
    // growing FROM 170 up to a 320 cap settles on the same width the old 320-basis shrink did
    // wherever the row fits; the line break reads the 170, so a short row wraps the pills instead
    assert.match(bar, /\n\.mgl-search \{[^}]*flex: 1 1 170px; max-width: 320px; min-width: 170px;/);
  });

  test("with the Similar token in it the slab keeps room for the token before the pills wrap", () => {
    assert.match(bar, /\.mgl-search\.simon \{[^}]*flex-basis: 300px; max-width: 430px;/);
  });

  test("every bar control shows from the 521px line up -- the four view buttons included", () => {
    // Owner walk 2026-09-29, second pass: at 744 and 820 the four view buttons after Actions
    // were gone -- shell.css hid the strip below 861px, though an iPad runs the desktop build.
    // No stylesheet may hide a library-bar control in a max-width block above the phone line.
    const barBits = /\.mgx-lay\b|\.mgx-laycell\b|\.mgl-bar\b|\.mgl-search\b|\.mgl-pill\b|\.mgl-filters\b|\.mgl-clear\b|\.mgl-wrap\b|\.mgx-libslot\b|\.mgx-bottom\b/;
    const dir = path.join(here, "..", "..", "gallery", "src");
    const files = ["styles.css", ...readdirSync(path.join(dir, "styles")).filter((f) => f.endsWith(".css")).map((f) => "styles/" + f)];
    for (const f of files) {
      const css = readFileSync(path.join(dir, f), "utf8").replace(/\r\n/g, "\n");
      const re = /@media \(max-width: (\d+)px\) \{/g;
      let m;
      while ((m = re.exec(css))) {
        if (Number(m[1]) <= 520) continue;
        let depth = 0, k = css.indexOf("{", m.index), end = k;
        for (; k < css.length; k++) {
          if (css[k] === "{") depth++;
          else if (css[k] === "}" && --depth === 0) { end = k; break; }
        }
        for (const rule of css.slice(m.index, end).split("}")) {
          const [sel, body = ""] = rule.split("{").slice(-2);
          if (sel && barBits.test(sel) && /display:\s*none/.test(body)) {
            assert.fail(f + " hides a library-bar control at max-width " + m[1] + "px: " + sel.trim());
          }
        }
      }
    }
    assert.match(shell, /@media \(max-width: 520px\) \{ \.mgx-lay \{ display: none; \} \}/,
      "the strip still hides where the phone build takes over");
  });

  test("the bar's own header comment no longer promises a row that never wraps", () => {
    const panel = src("gallery/src/components/FiltersPanel.jsx");
    assert.doesNotMatch(panel, /the bar itself never wraps/);
    assert.doesNotMatch(bar, /NEVER wraps/);
  });
});

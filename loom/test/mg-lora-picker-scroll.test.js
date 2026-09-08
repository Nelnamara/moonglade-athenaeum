import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The model/LoRA picker's list must SCROLL inside whichever shell floats it (owner walk,
// 2026-09-07: "LoRA picker in gen drawer does not scroll past first few (old bug)").
//
// WHAT WAS WRONG. ModelFlyout renders a head plus one pane; styles.css gives that pane
// `.mfly > div:not(.mfly-head) { flex: 1 1 auto; overflow-y: auto; }` -- so it is the
// scroller. Both shells cap the flyout's height and hide its own overflow: the phone sheet
// (create-mobile.css) and the desktop dock palette (dock.css, max-height:46vh). But a flex
// ITEM defaults to min-height:auto -- never smaller than its content -- so the pane refused
// to shrink to that cap and the shell clipped it. `overflow-y:auto` on an element that is
// never shorter than its content scrolls nothing. min-height:0 is the whole fix.
//
// The phone got it on 2026-08-24; the desktop dock rule predates that and never did, which is
// why the same bug lived on only on desktop. This guard holds BOTH shells to it, so a future
// re-anchor of the flyout cannot ship one without the other.
//
// Source-presence guards in the style of mg-lora-sheet-done.test.js: nothing here can boot a
// browser, so these pin the exact declarations the layout depends on.

const here = path.dirname(fileURLToPath(import.meta.url));
// Comments come OUT first, as in dead-css-sweep.test.js: these very rules are documented by
// comments that quote their own selectors, and prose is not a rule.
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8")
  .replace(/\r\n/g, "\n").replace(/\/\*[\s\S]*?\*\//g, " ");

const dock = src("gallery/src/styles/dock.css");
const phone = src("gallery/src/styles/create-mobile.css");
const base = src("gallery/src/styles.css");

/** The declaration block of the first rule whose selector text contains `sel`. */
function ruleFor(css, sel) {
  const i = css.indexOf(sel);
  assert.ok(i > 0, "no rule found for: " + sel);
  const open = css.indexOf("{", i);
  assert.ok(open > i, "selector has no block: " + sel);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("the picker's scroll wrapper can shrink inside both shells", () => {
  test("styles.css still makes the flyout's non-head child the scroller", () => {
    // Both shell rules are refinements OF this one; if it moves, they are pointing at nothing.
    const r = ruleFor(base, ".mfly > div:not(.mfly-head)");
    assert.match(r, /flex:\s*1 1 auto/);
    assert.match(r, /overflow-y:\s*auto/);
  });

  for (const [shell, css, sel] of [
    ["the phone sheet", phone, ".cm-modelwrap .mfly > div:not(.mfly-head)"],
    ["the desktop dock palette", dock, ".mgx-dock-host .mfly > div:not(.mfly-head)"],
  ]) {
    test(shell + " gives that wrapper min-height:0 so it shrinks to the cap", () => {
      const r = ruleFor(css, sel);
      assert.match(r, /min-height:\s*0\b/,
        "without min-height:0 the flex item never shrinks and the shell clips the list");
      assert.match(r, /overflow-y:\s*auto/,
        "the shrunk wrapper must still be the thing that scrolls");
    });
  }

  test("each shell caps the flyout's height and hides its own overflow", () => {
    // The cap is what makes min-height:0 matter: no cap, nothing to shrink to.
    const palette = ruleFor(dock, ".mgx-dock-host .mfly ");
    assert.match(palette, /max-height:\s*46vh/);
    assert.match(palette, /overflow:\s*hidden/);
    assert.match(palette, /min-height:\s*0\b/, "the palette itself is also a flex item");
  });

  test("the desktop rule is scoped under the dock host, so it cannot leak", () => {
    // .mfly is also mounted by the old side drawer and by the phone sheet; an unscoped
    // `min-height:0` here would change both.
    const i = dock.indexOf(".mfly > div:not(.mfly-head)");
    assert.ok(i > 0);
    assert.equal(dock.slice(0, i).endsWith(".mgx-dock-host "), true,
      "the only dock.css rule for the picker pane must be prefixed .mgx-dock-host");
  });
});

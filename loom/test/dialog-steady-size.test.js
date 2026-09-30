import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// DIALOGS DO NOT RESIZE UNDER THE POINTER (owner walk 2026-09-29). The Recipes picker shrank
// and re-centred when a tab changed from Market to Sets or Mine, so the next click landed on the
// scrim and closed it; the Contests dialog grew when "loading live contests…" gave way to the
// board, so a click aimed at "My entries" landed on a contest. Both now hold one size -- a
// height, not a content-driven max-height -- whatever their tab or loading state.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

describe("the Recipes picker (compact size)", () => {
  const css = src("gallery/src/styles/recipes.css");
  const jsx = src("gallery/src/recipes/RecipesOverlay.jsx");

  test("the compact slab has a HEIGHT -- the box Market's grid fills -- not only a max-height", () => {
    assert.match(css, /\n\.rcp-compact \{ width: min\(780px, calc\(100vw - 32px\)\); height: min\(86vh, 760px\); height: min\(86dvh, 760px\); \}/);
    assert.doesNotMatch(css, /\.rcp-compact \{[^}]*max-height/);
  });

  test("every tab's content flexes into that box and scrolls inside it", () => {
    assert.match(css, /\n\.rcp-slab \{[^}]*display: flex; flex-direction: column; overflow: hidden;/);
    assert.match(css, /\n\.rcp-body \{ flex: 1; min-height: 0; display: flex; \}/);
    assert.match(css, /\n\.rcp-scroll \{ flex: 1; min-height: 0; overflow-y: auto;/);
    assert.match(css, /\n\.rcp-setview \{ flex: 1; min-height: 0;/);
    assert.match(css, /\n\.rcp-page \{ flex: 1; min-height: 0;[^}]*overflow-y: auto;/);
    // the size class is the only thing a tab switch could have changed, and it does not change
    assert.match(jsx, /className=\{"rcp-slab " \+ \(size === "market" \? "rcp-mkt" : "rcp-compact"\)\}/);
  });

  test("the market size was already fixed: inset from the viewport, never content-sized", () => {
    assert.match(css, /\n\.rcp-mkt \{ position: absolute; inset: 24px; width: auto; max-height: none; \}/);
  });
});

describe("the Contests dialog", () => {
  const css = src("gallery/src/styles/overlays.css");
  const jsx = src("gallery/src/components/ContestsOverlay.jsx");

  test("the slab opts into the steady size", () => {
    assert.match(jsx, /<div className="mgv-slab mgct-slab mgv-steady" role="dialog" aria-label="Contests">/);
  });

  test("a steady slab holds the full height the shared slab caps at, so loading, tabs and detail share it", () => {
    assert.match(css, /\n\.mgv-slab\.mgv-steady \{ height: 90vh; height: 90dvh; \}/);
    // the shared slab's cap is that same 90, and it still scrolls inside
    assert.match(css, /\n\.mgv-slab \{[^}]*max-height: 90vh; max-height: 90dvh; overflow-y: auto;/);
  });

  test("the loading line, both tabs and the detail all render inside that one slab", () => {
    const slab = jsx.indexOf('<div className="mgv-slab mgct-slab mgv-steady"');
    for (const piece of ["<ContestDetail", "<ContestMyEntries", "loading live contests…", 'className="mgct-tabs"']) {
      assert.ok(jsx.indexOf(piece) > slab, piece + " is inside the steady slab");
    }
  });
});

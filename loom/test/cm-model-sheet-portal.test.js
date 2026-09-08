/* The phone's model/LoRA sheet lives outside the scrolling body, sized by the visible viewport.

   Owner's 5059 screenshot, 2026-09-07: the sheet with no head at all -- no Models/LoRAs tabs,
   no Confirm selection, no search box -- the hero sitting above it and the tab bar below, both
   undimmed. Two iPhone-Safari behaviours produced it, and neither desktop engine has either:
   (1) a position:fixed element inside a touch scroller (.glm-body) is confined to that
   scroller's box, and (2) `vh` is the screen with the toolbars hidden, so a 78vh sheet is
   taller than its space whenever the toolbars are up. The sheet grew past the body's top edge
   and lost exactly its head and search row. So the 390x844 desktop-Chromium proof passed while
   his phone did not.

   The browser harness (tests/test_render_harness.py, IPHONE_PRO_MAX, WebKit when installed)
   measures the geometry and pins "not a descendant of .glm-body"; this file pins the source
   so a refactor that quietly un-portals the sheet, or drops the dvh line, fails here too. */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(here, "../../gallery/src/components/CreateMobile.jsx"), "utf8");
const css = readFileSync(path.join(here, "../../gallery/src/styles/create-mobile.css"), "utf8");

describe("the sheet and its scrim are portaled out of the scrolling body", () => {
  test("CreateMobile portals the scrim and the .cm-modelwrap together, to the app stage", () => {
    assert.match(jsx, /import \{ createPortal \} from "react-dom";/);
    assert.match(jsx, /const \[sheetHost, setSheetHost\] = useState\(null\);/);
    assert.match(jsx, /setSheetHost\(document\.querySelector\("\.glm-stage"\) \|\| document\.body\)/,
      "the host is the fixed, non-scrolling app stage (font and tokens still inherit), body as fallback");
    assert.match(jsx, /\{sheetHost && createPortal\(\s*<>\s*\{flyOpen && <div className="glm-scrim"[\s\S]*?<div className="cm-modelwrap">[\s\S]*?<ModelFlyout[\s\S]*?<\/>,\s*sheetHost\)\}/,
      "scrim and sheet must ride the SAME portal -- a scrim left inside the scroller would dim only the body");
  });

  test("nothing else renders the sheet wrapper in the flow", () => {
    assert.equal(jsx.split('className="cm-modelwrap"').length, 2, "exactly one .cm-modelwrap, and it is the portaled one");
  });
});

describe("the sheet is sized by the visible viewport, with the old unit as the fallback", () => {
  // The rule's OWN block: from its selector to its own closing brace, never past it. A dvh
  // line in some other rule must not satisfy this (a first draft sliced to the first "}"
  // after wherever "78dvh" occurred, which any later rule could satisfy -- red team 2026-09-08).
  const start = css.indexOf(".cm-modelwrap .mfly {");
  assert.ok(start >= 0, "no .cm-modelwrap .mfly rule");
  const block = css.slice(start, css.indexOf("}", start));
  const decls = block.replace(/\/\*[\s\S]*?\*\//g, "");   // comments out, declarations only

  test("inside the rule, the vh fallback comes first and the dvh size overrides it", () => {
    const vh = decls.indexOf("height: 78vh;");
    const dvh = decls.indexOf("height: 78dvh; max-height: 78dvh;");
    assert.ok(vh >= 0, "the 78vh fallback is gone from the .cm-modelwrap .mfly rule: " + decls);
    assert.ok(dvh > vh, "78dvh must be declared AFTER 78vh inside .cm-modelwrap .mfly, so a browser " +
      "without dvh keeps the fallback and one with it takes the visible-viewport size: " + decls);
  });

  test("the fallback caps the sheet below the notch: 100% of the fixed viewport minus the safe area", () => {
    // Pre-dvh iOS with viewport-fit=cover: 78vh of the toolbars-hidden screen can put the head
    // under the status bar. A fixed element's 100% is the visible viewport even there.
    assert.match(decls, /max-height: calc\(100% - env\(safe-area-inset-top, 0px\) - 64px\);/,
      "the pre-dvh fallback lost its safe-area cap: " + decls);
    const cap = decls.indexOf("max-height: calc(100%");
    const dvh = decls.indexOf("max-height: 78dvh;");
    assert.ok(cap >= 0 && dvh > cap, "the safe-area cap is the fallback and must come before the dvh max-height");
  });

  test("no other rule sizes the sheet in vh behind its back", () => {
    const rest = css.slice(0, start) + css.slice(css.indexOf("}", start));
    assert.doesNotMatch(rest, /\.cm-modelwrap \.mfly\s*\{[^}]*height:\s*\d+vh/,
      "a second .cm-modelwrap .mfly rule sets a vh height and would override the dvh one");
  });
});

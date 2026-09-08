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
  test("the vh declaration comes first and the dvh declaration overrides it", () => {
    const i = css.indexOf("height: 78vh; max-height: 78vh;");
    const j = css.indexOf("height: 78dvh; max-height: 78dvh;");
    assert.ok(i > 0 && j > i, "78vh must be declared before 78dvh inside .cm-modelwrap .mfly, so a browser " +
      "without dvh keeps the vh size and one with it takes the visible-viewport size");
    const rule = css.slice(css.indexOf(".cm-modelwrap .mfly {"), css.indexOf("}", j));
    assert.ok(rule.includes("78dvh"), "the dvh line must be inside the .cm-modelwrap .mfly rule itself");
  });
});

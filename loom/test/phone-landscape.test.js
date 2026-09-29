import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  LANDSCAPE_QUERY, PHONE_MAX, anchorScrollTop, isPhoneViewport, phoneColumns, pickAnchor,
} from "../../gallery/src/lib/phoneCore.js";

/* Session Q, Q4 (Phone Handoff.dc.html, "Q4 · LANDSCAPE · 740 x 360"): the phone turned sideways. The
   rules that decide it (what a phone is, how many columns, which picture to keep in place), and the
   shape of the stylesheet and the components that draw it. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rd = (p) => readFileSync(path.resolve(__dirname, "..", "..", p), "utf8");
const css = rd("gallery/src/styles/phone-landscape.css");

describe("Q4 what a phone is, sideways", () => {
  const phone = (o) => isPhoneViewport({ coarse: true, portrait: false, ...o });

  test("a phone held sideways is a phone: its short side is under the line", () => {
    assert.equal(phone({ width: 844, screenW: 844, screenH: 390 }), true, "Android reports the swapped screen");
    assert.equal(phone({ width: 932, screenW: 430, screenH: 932 }), true, "iOS keeps the upright screen: the minimum still says phone");
    assert.equal(phone({ width: 667, screenW: 667, screenH: 375 }), true, "an iPhone SE");
  });

  test("a tablet or a laptop is not one, either way round", () => {
    assert.equal(phone({ width: 1133, screenW: 1133, screenH: 744 }), false, "iPad mini sideways");
    assert.equal(phone({ width: 1180, screenW: 820, screenH: 1180 }), false, "iPad Air, iOS-style screen numbers");
    assert.equal(isPhoneViewport({ width: 1440, coarse: false, portrait: false, screenW: 1440, screenH: 900 }), false);
  });

  test("the Loom can ask for the old, upright-only answer", () => {
    assert.equal(phone({ width: 844, screenW: 844, screenH: 390, landscapePhones: false }), false);
    assert.equal(isPhoneViewport({ width: 390, portrait: true, coarse: true, screenW: 390, screenH: 844, landscapePhones: false }), true);
  });

  test("upright, nothing changed: width alone, or the coarse + screen fallback", () => {
    assert.equal(isPhoneViewport({ width: 390, coarse: false, portrait: true, screenW: 390, screenH: 844 }), true);
    assert.equal(isPhoneViewport({ width: 1024, coarse: true, portrait: true, screenW: 390, screenH: 844 }), true);
    assert.equal(isPhoneViewport({ width: 768, coarse: true, portrait: true, screenW: 768, screenH: 1024 }), false);
    assert.equal(isPhoneViewport({ width: 1024, coarse: false, portrait: true, screenW: 390, screenH: 844 }), false, "a mouse is never the fallback");
    assert.equal(PHONE_MAX, 520);
  });

  test("a missing screen never makes a phone of a desktop", () => {
    assert.equal(isPhoneViewport({ width: 1280, coarse: false, portrait: false }), false);
    assert.equal(isPhoneViewport({ width: 1280, coarse: true, portrait: false, screenW: 0, screenH: 0 }), false);
  });
});

describe("Q4 the gallery's columns", () => {
  test("two upright; four sideways, three under 700 px wide", () => {
    assert.equal(phoneColumns(390, false), 2);
    assert.equal(phoneColumns(844, true), 4);
    assert.equal(phoneColumns(700, true), 4, "700 itself is not 'under 700'");
    assert.equal(phoneColumns(699, true), 3);
    assert.equal(phoneColumns(667, true), 3, "an iPhone SE sideways");
    assert.equal(phoneColumns(NaN, true), 4);
  });
});

describe("Q4 rotation keeps your place", () => {
  const tiles = [
    { id: "a", top: -400, bottom: -100 },
    { id: "b", top: -60, bottom: 180 },      // straddles the view's top edge
    { id: "c", top: 20, bottom: 300 },
    { id: "d", top: 310, bottom: 600 },
  ];
  test("the anchor is the highest picture still in view, and how far below the edge it sat", () => {
    assert.deepEqual(pickAnchor(tiles, 0), { id: "b", offset: -60 });
    assert.deepEqual(pickAnchor(tiles, 100), { id: "b", offset: -160 });
    assert.deepEqual(pickAnchor(tiles, 290), { id: "c", offset: -270 });
  });
  test("nothing in view is no anchor", () => {
    assert.equal(pickAnchor([], 0), null);
    assert.equal(pickAnchor([{ id: "x", top: -50, bottom: -10 }], 0), null);
    assert.equal(pickAnchor(null, 0), null);
  });
  test("scrolling puts the same picture back at the same offset, never above zero", () => {
    // after the turn the picture sits at 500 while the view starts at 100: move the scroller down 400 - offset
    assert.equal(anchorScrollTop(1000, 500, 100, 0), 1400);
    assert.equal(anchorScrollTop(1000, 500, 100, -60), 1460);
    assert.equal(anchorScrollTop(10, 20, 100, 0), 0);
    assert.equal(anchorScrollTop(0, NaN, 0, 0), 0);
  });
});

describe("Q4 the stylesheet", () => {
  test("every landscape rule sits under the one query, written the same in CSS and in the core", () => {
    assert.equal(LANDSCAPE_QUERY, "(orientation: landscape) and (max-height: 520px)");
    const medias = [...css.matchAll(/@media\s+([^{]+)\{/g)].map((m) => m[1].trim());
    assert.ok(medias.length >= 2);
    for (const m of medias) {
      if (m.startsWith("(max-width")) continue;                    // the hero's nested small-screen tweak
      assert.ok(m.startsWith(LANDSCAPE_QUERY), "unexpected condition: " + m);
    }
  });

  test("the page's numbers: a 56 px rail of 44 px tiles, a 380 px panel", () => {
    assert.match(css, /grid-template-columns: calc\(56px \+ env\(safe-area-inset-left\)\) minmax\(0, 1fr\)/);
    assert.match(css, /width: 44px; height: 44px/);
    assert.match(css, /width: min\(380px, 100%\)/);
  });

  test("the safe areas are read on both sides", () => {
    for (const side of ["left", "right", "top", "bottom"]) {
      assert.ok(css.includes("env(safe-area-inset-" + side + ")"), side);
    }
  });

  test("the rail names its tabs for a screen reader, and the sheets share one panel animation", () => {
    assert.match(rd("gallery/src/components/TabBarMobile.jsx"), /aria-label=\{t\.label\}/);
    assert.match(css, /animation-name: glmPanelIn/);
    assert.match(css, /animation-name: glmPanelOut/);
  });

  test("it loads last, so it can re-flow the sheets it turns", () => {
    const app = rd("gallery/src/components/AppMobile.jsx");
    const imports = [...app.matchAll(/^import "\.\.\/styles\/([^"]+)";$/gm)].map((m) => m[1]);
    assert.equal(imports[imports.length - 1], "phone-landscape.css");
  });
});

describe("Q4 the pieces stay put across a turn", () => {
  test("the shell keeps ONE component for both orientations (a turn is CSS, not a remount)", () => {
    const hook = rd("gallery/src/hooks/useIsMobile.js");
    assert.match(hook, /isPhoneViewport\(\{/);
    assert.match(hook, /landscapePhones/, "the Loom can still ask for the upright-only answer");
    assert.doesNotMatch(hook, /return coarse && portrait/, "the old portrait-only return is gone");
  });

  test("the grid deals across `cols` and tags every picture for the scroll anchor", () => {
    const grid = rd("gallery/src/components/GalleryGridMobile.jsx");
    assert.match(grid, /data-mid=\{it\.media_id\}/);
    assert.match(grid, /cols = 2/);
    assert.match(grid, /glm-grid-rows/);
    const gal = rd("gallery/src/components/GalleryMobile.jsx");
    assert.match(gal, /useScrollAnchor\(rootRef, "\.glm-body"/);
    assert.match(gal, /cols=\{cols\}/);
  });

  test("the scroll anchor reads and then writes scrollTop once per turn, and stores nothing", () => {
    const h = rd("gallery/src/hooks/useScrollAnchor.js");
    assert.equal((h.match(/\.scrollTop =/g) || []).length, 1);
    assert.doesNotMatch(h, /localStorage|sessionStorage|fetch\(|apiGet|apiPost/);
  });

  test("the landscape files reach no generation, price or submit call (Q2's promise holds sideways)", () => {
    for (const f of ["gallery/src/hooks/usePhoneLandscape.js", "gallery/src/hooks/useScrollAnchor.js"]) {
      assert.doesNotMatch(rd(f), /\/api\/(generate|price|panel|jobs)|submit|gql_/i, f);
    }
  });

  test("the record wraps its panel so upright it has no box", () => {
    assert.match(rd("gallery/src/components/ImageDetailsMobile.jsx"), /<div className="idm-rec">/);
    assert.match(css, /\.idm-rec \{ display: contents; \}/);
  });

  test("the phone's Loom sheet no longer asks for a rotation", () => {
    const app = rd("gallery/src/components/AppMobile.jsx");
    const sheet = app.slice(app.indexOf('title="THE LOOM"'));
    const block = sheet.slice(0, sheet.indexOf("</MobileSheet>"));
    const note = block.slice(block.indexOf('<div className="glm-loom-note">'), block.indexOf('<div className="glm-sheet-actions">'));
    assert.doesNotMatch(note, /turn the phone/i);
    assert.doesNotMatch(note, /Rotate to landscape/i);
    assert.match(note, /board and reel/);
    assert.match(note, /Desktop/);
  });
});

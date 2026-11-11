import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  LANDSCAPE_QUERY, PHONE_MAX, anchorScrollTop, isPhoneViewport, phoneColumns, pickAnchor, sidesKept,
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
    // The lagging turn (owner's walk, 2026-10-03; loom/test/phone-turn-columns.test.js): the width
    // can still read sideways while the orientation query already says upright. Upright is two at ANY width.
    assert.equal(phoneColumns(844, false), 2, "upright at a sideways width is still two");
    assert.equal(phoneColumns(844, true), 4);
    assert.equal(phoneColumns(700, true), 4, "700 itself is not 'under 700'");
    assert.equal(phoneColumns(699, true), 3);
    assert.equal(phoneColumns(667, true), 3, "an iPhone SE sideways");
    assert.equal(phoneColumns(NaN, true), 4);
  });
});

describe("sides kept (#73): the side safe areas are counted once", () => {
  // iOS Chrome / Safari report the upright screen (393 x 852) whichever way the phone is held
  const base = { landscape: true, screenW: 393, screenH: 852 };
  test("Safari: the window is the whole screen, both insets stay", () => {
    assert.equal(sidesKept({ ...base, innerW: 852, left: 59, right: 59 }), false);
  });
  test("Chrome that already kept its own room: a 734 window in an 852 screen, 59 + 59 asked", () => {
    assert.equal(sidesKept({ ...base, innerW: 734, left: 59, right: 59 }), true);
  });
  test("an Android cutout (one side only) is never treated as kept, however narrow the window", () => {
    assert.equal(sidesKept({ landscape: true, innerW: 804, screenW: 844, screenH: 390, left: 30, right: 0 }), false);
    assert.equal(sidesKept({ landscape: true, innerW: 700, screenW: 844, screenH: 390, left: 0, right: 30 }), false);
  });
  test("upright, or not a landscape phone (iPad, desktop): never", () => {
    assert.equal(sidesKept({ ...base, landscape: false, innerW: 734, left: 59, right: 59 }), false);
    assert.equal(sidesKept({ landscape: false, innerW: 393, screenW: 393, screenH: 852, left: 0, right: 0 }), false);
  });
  test("no insets, or numbers it cannot trust: never", () => {
    assert.equal(sidesKept({ ...base, innerW: 734, left: 0, right: 0 }), false, "a desktop window or a phone without a notch");
    assert.equal(sidesKept({ landscape: true, innerW: 734, screenW: NaN, screenH: undefined, left: 59, right: 59 }), false);
    assert.equal(sidesKept({ ...base, innerW: NaN, left: 59, right: 59 }), false);
    assert.equal(sidesKept({ ...base, innerW: 0, left: 59, right: 59 }), false);
    assert.equal(sidesKept({ ...base, left: 59, right: 59 }), false, "no window width at all");
  });
  test("a window wider than the screen (zoomed, or a desktop-wide layout viewport) is never kept", () => {
    assert.equal(sidesKept({ ...base, innerW: 980, left: 59, right: 59 }), false);
  });
  test("iOS screen numbers work either way round", () => {
    assert.equal(sidesKept({ landscape: true, innerW: 734, screenW: 852, screenH: 393, left: 59, right: 59 }), true);
    assert.equal(sidesKept({ landscape: true, innerW: 734, screenW: 393, screenH: 852, left: 59, right: 59 }), true);
  });
  test("the room the browser kept must MATCH what the insets ask, within a few px, both ways", () => {
    // 59 + 59 = 118 asked; the 4 px slack lets 114..122 of kept room count
    assert.equal(sidesKept({ ...base, innerW: 738, left: 59, right: 59 }), true);   // 114
    assert.equal(sidesKept({ ...base, innerW: 739, left: 59, right: 59 }), false);  // 113
    assert.equal(sidesKept({ ...base, innerW: 730, left: 59, right: 59 }), true);   // 122
    assert.equal(sidesKept({ ...base, innerW: 729, left: 59, right: 59 }), false);  // 123
  });
  test("Page Zoom above 100% shrinks the window without the browser keeping any room: a real inset stays (review #73)", () => {
    assert.equal(sidesKept({ ...base, innerW: Math.round(852 / 1.25), left: 59, right: 59 }), false, "125%, insets unscaled");
    assert.equal(sidesKept({ ...base, innerW: Math.round(852 / 1.25), left: 47, right: 47 }), false, "125%, insets in CSS px");
    assert.equal(sidesKept({ ...base, innerW: Math.round(852 / 1.15), left: 51, right: 51 }), false, "115%");
    assert.equal(sidesKept({ ...base, innerW: 568, left: 39, right: 39 }), false, "150%");
    assert.equal(sidesKept({ ...base, innerW: 734, left: 59, right: 59 }), true, "control: Chrome's shape is still kept");
  });
  test("the two sides must agree within the slack", () => {
    assert.equal(sidesKept({ ...base, innerW: 734, left: 59, right: 55 }), true);
    assert.equal(sidesKept({ ...base, innerW: 734, left: 59, right: 40 }), false);
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
    assert.match(css, /grid-template-columns: calc\(56px \+ var\(--mg-safe-l\)\) minmax\(0, 1fr\)/);
    assert.match(css, /width: 44px; height: 44px/);
    assert.match(css, /width: min\(380px, 100%\)/);
  });

  test("the safe areas are read on both sides, the side ones counted once (#73)", () => {
    // top and bottom stay straight env() reads
    for (const side of ["top", "bottom"]) {
      assert.ok(css.includes("env(safe-area-inset-" + side + ")"), side);
    }
    // the side ones go through two variables, defined in one place each...
    assert.ok(css.includes("--mg-safe-l: env(safe-area-inset-left)"));
    assert.ok(css.includes("--mg-safe-r: env(safe-area-inset-right)"));
    assert.match(css, /:root\[data-mg-sides-kept\] \{ --mg-safe-l: 0px; --mg-safe-r: 0px; \}/, "kept zeroes both");
    assert.match(css, /@property --mg-safe-l \{ syntax: "<length>"; inherits: true; initial-value: 0px; \}/);
    assert.match(css, /@property --mg-safe-r \{ syntax: "<length>"; inherits: true; initial-value: 0px; \}/);
    // ...and nothing else reads them raw
    const raw = css.replace(/--mg-safe-[lr]: env\(safe-area-inset-(left|right)\)/g, "");
    assert.doesNotMatch(raw, /env\(safe-area-inset-(left|right)\)/, "a raw side env() would be counted twice in Chrome");
    for (const v of ["--mg-safe-l", "--mg-safe-r"]) assert.ok(css.includes("var(" + v + ")"), v);
  });

  test("the side room slides over half a second for a late correction only, and not at all under reduced motion", () => {
    assert.match(css, /:root\[data-mg-slide\] \{ transition: --mg-safe-l \.5s ease, --mg-safe-r \.5s ease; \}/);
    assert.doesNotMatch(css, /(^|\n)\s*:root \{ transition: --mg/, "a bare :root transition would slide every turn");
    const rm = css.slice(css.indexOf("prefers-reduced-motion: reduce"));
    assert.match(rm, /:root, :root\[data-mg-slide\] \{ transition: none; \}/);
  });

  test("no other phone stylesheet reads a raw side inset, and the toast keeps clear of the island", () => {
    const dir = path.resolve(__dirname, "..", "..", "gallery", "src", "styles");
    const sheets = readdirSync(dir).filter((f) => f.endsWith(".css") && f !== "phone-landscape.css");
    assert.ok(sheets.includes("notify.css"));
    for (const f of sheets) assert.doesNotMatch(readFileSync(path.join(dir, f), "utf8"), /env\(safe-area-inset-(left|right)\)/, f);
    assert.match(rd("gallery/src/styles/notify.css"), /#mg-toasts\{[^}]*right:calc\(16px \+ var\(--mg-safe-r,0px\)\)/);
  });

  test("the record's picture is its own shape, not a stretched grey frame (#73)", () => {
    assert.match(css, /\.idm-body > \.idm-frame \{ flex: 0 1 auto; align-self: center; width: auto; margin: 0 auto; \}/);
    assert.match(css, /\.idm-body > \.idm-frame:not\(:has\(img, video\)\) \{ min-width: min\(240px, 100%\); \}/, "only a note-only frame keeps a floor");
    // the frame is the picture's shape, as big as the room allows, and the picture fills it (a thumbnail too)
    assert.match(css, /\.idm-body > \.idm-frame\.hasar \{[^}]*width: min\(100%, calc\(var\(--idm-h\) \* var\(--idm-ar\)\)\); aspect-ratio: var\(--idm-ar\); \}/);
    assert.match(css, /\.idm-frame\.hasar img, \.idm-frame\.hasar video \{ position: absolute; inset: 0; width: 100%; height: 100%;/);
    assert.match(css, /\.idm-frame \.lbm-tapfull \{ white-space: normal;/, "the pill wraps instead of being clipped");
    assert.match(css, /\.idm-body \{ flex-direction: row; gap: 14px;/, "the picture keeps a gutter beside the panel");
    const comp = rd("gallery/src/components/ImageDetailsMobile.jsx");
    assert.match(comp, /\(frameAR \? " hasar" : ""\)/);
    assert.match(comp, /style=\{frameAR \? \{ "--idm-ar": frameAR \} : undefined\}/);
    assert.match(css, /\.idm-frame img, \.idm-frame video \{ width: auto; max-width: 100%;/);
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

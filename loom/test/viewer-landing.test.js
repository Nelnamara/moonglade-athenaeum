import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { landingAfterViewer } from "../../gallery/src/lib/viewerLanding.js";

/* WHERE THE VIEWER PUTS YOU DOWN (owner, 2026-09-07).

   "When the viewer closes, land on the picture you were viewing; if it is off-page -- the
   viewer stepped onto another page -- the top of its page."

   The DECISION is a real import: viewerLanding.js takes no React and no DOM, exactly so it
   can be exercised here, the same reason blurPref.js and markdownLite.js are importable
   (there is no React harness in this runner). The WIRING -- who takes the snapshot, when it
   is spent, and what stops it firing into a locked viewport -- is a source guard, the
   established pattern for this suite (see gallery-stands-still.test.js, whose ruling this
   one refines rather than bends). */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const app = src("App.jsx");
const grid = src("components/Grid.jsx");

/** A viewport 900px tall with 150px of sticky chrome across the top of it. */
const VIEW = { viewportTop: 150, viewportBottom: 900 };

describe("the decision", () => {
  test("a page change lands at the top, whatever the card measures", () => {
    // The offset he had is meaningless on a page he has never seen -- and the card
    // measurements, if there are any at all, belong to that new page.
    assert.equal(landingAfterViewer({ pageChanged: true, cardTop: 200, cardBottom: 400, ...VIEW }), "top");
    assert.equal(landingAfterViewer({ pageChanged: true, cardTop: null, cardBottom: null, ...VIEW }), "top");
  });

  test("a picture already fully on screen is left alone -- nothing moves", () => {
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 200, cardBottom: 700, ...VIEW }), "stay");
  });

  test("flush against either edge still counts as fully on screen", () => {
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 150, cardBottom: 900, ...VIEW }), "stay");
  });

  test("half a card is not on screen -- that is the case the ruling exists for", () => {
    // Cut off at the bottom...
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 700, cardBottom: 1100, ...VIEW }), "card");
    // ...and cut off at the top, behind the sticky chrome, which is NOT the same as y=0.
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 100, cardBottom: 400, ...VIEW }), "card");
  });

  test("a card entirely above or below the viewport is fetched back", () => {
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: -800, cardBottom: -400, ...VIEW }), "card");
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 2000, cardBottom: 2400, ...VIEW }), "card");
  });

  test("no card for the picture means stay, not top", () => {
    // Filtered out, or hidden under a stack cover. Moving him to the top of a page he was
    // reading, over a picture that is simply not drawn, is worse than not moving at all --
    // and "the library stands still" is the default this falls back to.
    for (const m of [{ cardTop: null, cardBottom: null }, { cardTop: undefined, cardBottom: undefined },
                     { cardTop: NaN, cardBottom: NaN }]) {
      assert.equal(landingAfterViewer({ pageChanged: false, ...m, ...VIEW }), "stay");
    }
  });
});

describe("the wiring: the snapshot", () => {
  test("only the viewer's OWN close takes it", () => {
    // Edit, To Video, Similar, Details and the deep-link reset all clear lbIndex and go
    // somewhere else entirely; a landing hung on the lbIndex transition would fire on all
    // of them. It hangs on the close handler instead.
    assert.match(app, /const closeLightbox = useCallback\(\(\) => \{\s*lbLandPending\.current = lbLandRef\.current;\s*setLbIndex\(null\);/);
    assert.match(app, /onClose=\{closeLightbox\}/);
    assert.doesNotMatch(app, /onClose=\{\(\) => setLbIndex\(null\)\}/,
      "the bare close is what this replaced");
  });

  test("the page it OPENED on is kept across every step, not overwritten by each one", () => {
    // Two steps forward and one back is still the page he started on, and still not a
    // page change.
    assert.match(app, /openPage: prev \? prev\.openPage : page,/);
  });

  test("the snapshot is spent once and cleared", () => {
    assert.match(app, /const snap = lbLandPending\.current;\s*if \(!snap\) return;\s*lbLandPending\.current = null;/);
  });
});

describe("the wiring: the move", () => {
  test("it waits for the viewer's scroll lock to lift before it scrolls", () => {
    // useScrollLock hides body overflow, which makes the viewport unscrollable: a
    // scrollTo fired before the unmounting viewer's passive teardown releases it is
    // simply swallowed, and the landing would silently do nothing.
    assert.match(app, /document\.body\.style\.overflow === "hidden"/);
    assert.match(app, /requestAnimationFrame\(run\)/);
    assert.match(app, /return \(\) => cancelAnimationFrame\(raf\)/);
  });

  test("instant, never smooth -- the same idiom the grid's own page flip settled", () => {
    const eff = app.slice(app.indexOf("const snap = lbLandPending.current;"),
                          app.indexOf("}, [lbIndex]);   // eslint-disable-line"));
    assert.match(eff, /"instant" in document\.documentElement\.style \? "instant" : "auto"/);
    assert.doesNotMatch(eff, /behavior: "smooth"/);
    assert.match(grid, /behavior: "instant" in document\.documentElement\.style \? "instant" : "auto"/,
      "the grid's page flip is where this idiom comes from");
  });

  test("the sticky header is measured, not guessed", () => {
    assert.match(app, /getPropertyValue\("--mgx-chrome-h"\)/);
  });

  test('the card is brought in by "nearest", so scroll-margin-top can clear the chrome', () => {
    assert.match(app, /scrollIntoView\(\{ block: "nearest", inline: "nearest", behavior \}\)/);
    assert.match(src("styles/grid.css"), /\.mgg-card \{ scroll-margin-top:/);
  });

  test("the decision is imported, not re-implemented in the shell", () => {
    assert.match(app, /import \{ landingAfterViewer \} from "\.\/lib\/viewerLanding\.js";/);
    assert.match(app, /const where = landingAfterViewer\(\{/);
  });

  test("a changed page does not wait for a card that will never paint", () => {
    // The answer there is the top of the page and needs no card; waiting twenty frames
    // for one would put a third of a second of visible delay on the exact case this
    // exists to fix.
    assert.match(app, /!pageChanged && snap\.mediaId && !cardFor\(snap\.mediaId\)/);
    assert.match(app, /\+\+waited < 20/, "the wait is bounded -- a close can never hang");
  });
});

describe("the wiring: finding the card", () => {
  test("every grid card carries its own id", () => {
    assert.match(grid, /data-id=\{it\.media_id\}/);
  });

  test("App looks it up by that attribute and survives an id that is not a selector", () => {
    assert.match(app, /\.mgg-card\[data-id="/);
    assert.match(app, /CSS\.escape/);
    assert.match(app, /catch \{ return null; \}/);
  });
});

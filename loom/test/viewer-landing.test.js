import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { landingAfterViewer, landInScroller, viewportOfScroller }
  from "../../gallery/src/lib/viewerLanding.js";

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

  test("instant, never smooth -- asked for outright, not feature-tested", () => {
    /* This used to pin `"instant" in document.documentElement.style ? "instant" : "auto"`,
       copied from Grid.jsx's page flip. That test is ALWAYS false -- CSSStyleDeclaration
       exposes one member per CSS property, and `instant` is a value of scroll-behavior,
       not a property -- so the guard pinned a branch that could never be taken, and the
       landing's non-smoothness rested on nothing but no stylesheet setting
       scroll-behavior: smooth. What matters is the property itself: smooth is never
       requested, by the shell or by the helper that does the moving. */
    const eff = app.slice(app.indexOf("const snap = lbLandPending.current;"),
                          app.indexOf("}, [lbIndex]);   // eslint-disable-line"));
    assert.match(eff, /const behavior = "instant";/);
    assert.doesNotMatch(eff, /"instant" in document\.documentElement\.style/,
      "the guard can never be true -- it is not a fallback, it is dead code");
    assert.doesNotMatch(eff, /"smooth"/);
    assert.doesNotMatch(src("lib/viewerLanding.js"), /"smooth"/,
      "the helper that actually scrolls must never ask for a smooth behavior either");
  });

  test("the sticky header is measured, not guessed", () => {
    assert.match(app, /getPropertyValue\("--mgx-chrome-h"\)/);
  });

  test('the card is brought in by "nearest", so scroll-margin-top can clear the chrome', () => {
    assert.match(src("lib/viewerLanding.js"),
      /scrollIntoView\(\{ block: "nearest", inline: "nearest", behavior \}\)/);
    assert.match(src("styles/grid.css"), /\.mgg-card \{ scroll-margin-top:/);
  });

  test("the decision is imported, not re-implemented in the shell", () => {
    assert.match(app, /import \{ landingAfterViewer, landInScroller, viewportOfScroller \}\s*\n?\s*from "\.\/lib\/viewerLanding\.js";/);
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

describe("the landing happens in the container that scrolls the cards", () => {
  /* THE TIMELINE HOLE (2026-09-07, correcting the same day's build). Masonry, grid and hero
     scroll the document, so window.scrollTo was right for three layouts out of four.
     Timeline's cards live in .mgg-tl-cols, a pane with its own overflow-y (grid.css) --
     the document does not move at all there, so the "top" landing did nothing and the owner
     was left at his old offset inside a page he had never seen: exactly the placement this
     ruling exists to fix. The helper takes the scroller and lands in it. */

  /** A scroll container that records what it was asked to do, with no DOM behind it. */
  const fakeScroller = (top = 0, bottom = 800) => {
    const calls = [];
    return { calls, getBoundingClientRect: () => ({ top, bottom }),
             scrollTo: (o) => calls.push(o) };
  };
  const fakeCard = () => {
    const calls = [];
    return { calls, scrollIntoView: (o) => calls.push(o) };
  };

  test('"top" scrolls the pane it was given, not the window', () => {
    const pane = fakeScroller();
    assert.equal(landInScroller("top", { scroller: pane, card: null, behavior: "instant" }), "top");
    assert.deepEqual(pane.calls, [{ top: 0, behavior: "instant" }]);
  });

  test('"card" lands through the card, which scrolls that same pane', () => {
    // block:"nearest" scrolls the nearest scrollable ancestor -- the pane -- and is what
    // lets .mgg-card's scroll-margin-top clear the sticky chrome. Re-deriving the offset
    // against the pane by hand would lose that margin.
    const pane = fakeScroller();
    const card = fakeCard();
    assert.equal(landInScroller("card", { scroller: pane, card, behavior: "instant" }), "card");
    assert.deepEqual(card.calls,
      [{ block: "nearest", inline: "nearest", behavior: "instant" }]);
    assert.deepEqual(pane.calls, [], "the pane is moved BY the card, not twice");
  });

  test('"stay" moves nothing, and neither does a "card" with no card left', () => {
    const pane = fakeScroller();
    const card = fakeCard();
    assert.equal(landInScroller("stay", { scroller: pane, card }), "stay");
    assert.equal(landInScroller("card", { scroller: pane, card: null }), "stay");
    assert.deepEqual(pane.calls, []);
    assert.deepEqual(card.calls, []);
    // A scroller that cannot scroll (nothing was found) is not an error either.
    assert.equal(landInScroller("top", { scroller: null, card: null }), "stay");
  });

  test('"already on screen" is measured against the pane, not the window', () => {
    // The timeline pane starts below the sticky chrome and ends at the bottom of the
    // window; a card at y=1000 is inside a 1200px window and well below the pane's fold.
    const WINDOW = { viewportTop: 150, viewportBottom: 1200 };
    const pane = fakeScroller(150, 700);
    const vp = viewportOfScroller(pane, WINDOW);
    assert.deepEqual(vp, { viewportTop: 150, viewportBottom: 700 });
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 900, cardBottom: 1100, ...vp }),
      "card", "a card below the pane's fold is not on screen, whatever the window says");
    assert.equal(landingAfterViewer({ pageChanged: false, cardTop: 900, cardBottom: 1100, ...WINDOW }),
      "stay", "...which is precisely what measuring against the window got wrong");
  });

  test("the window keeps the caller's own measurement -- it has no rect of its own", () => {
    const WINDOW = { viewportTop: 150, viewportBottom: 900 };
    assert.deepEqual(viewportOfScroller({ scrollTo() {} }, WINDOW), WINDOW);
    assert.deepEqual(viewportOfScroller(null, WINDOW), WINDOW);
    // A pane that measures as nothing (display:none, not yet laid out) is no measurement.
    assert.deepEqual(viewportOfScroller({ getBoundingClientRect: () => ({ top: 0, bottom: 0 }) },
      WINDOW), WINDOW);
  });

  test("the shell hands the helper the scroller, and no longer scrolls the window itself", () => {
    assert.match(app, /const scroller = cardScroller\(card\);/);
    assert.match(app, /landInScroller\(where, \{ scroller, card, behavior \}\)/);
    const eff = app.slice(app.indexOf("const snap = lbLandPending.current;"),
                          app.indexOf("}, [lbIndex]);   // eslint-disable-line"));
    assert.doesNotMatch(eff, /window\.scrollTo/,
      "the window is the scroller for three layouts out of four -- cardScroller returns it "
      + "when it is, and .mgg-tl-cols when it is not");
    assert.match(app, /viewportOfScroller\(scroller, \{/);
  });

  test("the pane is found by walking up from the card, with the timeline pane by name", () => {
    // Walked, so a layout that grows its own pane later is right without a second edit;
    // named, because with no card to walk from (the page changed) there is nothing else
    // to walk. And a pane that cannot actually scroll is not a scroller.
    assert.match(app, /function cardScroller\(card\)/);
    assert.match(app, /for \(let n = card && card\.parentElement; n; n = n\.parentElement\)/);
    assert.match(app, /document\.querySelector\("\.mgg-tl-cols"\)/);
    assert.match(app, /el\.scrollHeight > el\.clientHeight \+ 1/);
    assert.match(src("styles/grid.css"), /\.mgg-tl-cols \{[\s\S]*?overflow-y: auto/,
      "the pane this looks for must still be the one that scrolls");
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

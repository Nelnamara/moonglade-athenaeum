import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  readGuide, afterWelcome, afterTour, afterNote, tourSteps, noteText, firstPresentNote,
  placeBeside, placeClear, rectShowing, guideKey, GUIDE_SURFACES, CHIP_ROW, LAYER_SELECTORS,
  layerOpen, HEADER_BAND, HEADER_CONTROLS, NOTE_AVOID,
} from "../../gallery/src/help/guideCore.js";
import { GUIDE, stepsFor } from "../../gallery/src/help/guideSteps.js";

/* The first-run guide's state machine and placement (gallery/src/help/guideCore.js), and
   the shape of its one data file (gallery/src/help/guideSteps.js) that later waves edit. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const HOST_SRC = readFileSync(path.resolve(__dirname, "../../gallery/src/help/GuideHost.jsx"), "utf8");

describe("the stored state", () => {
  test("absent is the first visit; unknown is done, never a second welcome", () => {
    assert.deepEqual(readGuide(undefined), { phase: "welcome", n: 0 });
    assert.deepEqual(readGuide("tour"), { phase: "tour", n: 0 });
    assert.deepEqual(readGuide("notes:3"), { phase: "notes", n: 3 });
    assert.deepEqual(readGuide("done"), { phase: "done", n: 0 });
    assert.deepEqual(readGuide({ weird: true }), { phase: "done", n: 0 });
    assert.equal(guideKey("dock"), "guide.dock");
  });
  // Owner walk 2026-09-29: "forced to do the first run tutorial with no way out of it".
  // "Got it" used to start a chain of notes (notes:0) and Skip handed them the rest of the
  // tour (notes:k+1); both now END the guide for the surface.
  test("the welcome card's answers: Got it is done, no notes follow", () => {
    assert.equal(afterWelcome("tour"), "tour");
    assert.equal(afterWelcome("gotit"), "done");
  });
  test("a skipped tour is done; only a finished one hands the notes what it did not reach", () => {
    assert.equal(afterTour(3, 4), "notes:4");         // finished with Done: notes after the tour
    assert.equal(afterTour(9, 4), "notes:4");         // clamped
    assert.equal(afterTour(0, 4, true), "done");      // Skip (or Escape) on step 1
    assert.equal(afterTour(2, 4, true), "done");      // ... or on any step
  });
  test("a used note moves the cursor; past the end is done", () => {
    assert.equal(afterNote(1, 6), "notes:2");
    assert.equal(afterNote(5, 6), "done");
  });
  test("a note whose control is not on screen is passed over for now", () => {
    const steps = [{ id: "a" }, { id: "b" }, { id: "c" }];
    assert.equal(firstPresentNote(steps, 0, (s) => s.id !== "a"), 1);
    assert.equal(firstPresentNote(steps, 2, () => false), -1);
  });
});

describe("placement", () => {
  const vp = { w: 1280, h: 900 };
  test("below the control, lined up with its left edge on the left half", () => {
    const p = placeBeside({ left: 100, top: 40, right: 160, bottom: 70 }, { w: 240, h: 100 }, vp);
    assert.deepEqual(p, { left: 100, top: 80, placement: "below" });
  });
  test("right-aligned on the right half, and above when there is no room below", () => {
    const p = placeBeside({ left: 1100, top: 830, right: 1200, bottom: 870 }, { w: 240, h: 100 }, vp);
    assert.deepEqual(p, { left: 960, top: 720, placement: "above" });
  });
  test("never off screen", () => {
    const p = placeBeside({ left: -50, top: 10, right: 5, bottom: 20 }, { w: 240, h: 100 }, vp);
    assert.equal(p.left, 12);
    assert.equal(rectShowing({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }, vp), false);
    assert.equal(rectShowing({ left: 10, top: 10, right: 50, bottom: 40, width: 40, height: 30 }, vp), true);
  });
});

// Owner walk 2026-09-29: the banner Generate's note sat below it, right over the separator
// bar's pin chip (and its ✕) and the Vigil.
describe("a note keeps clear of the header's chip row", () => {
  const vp = { w: 1280, h: 900 };
  const gen = { left: 1000, top: 300, right: 1150, bottom: 340 };     // the banner's Generate
  const chips = [{ left: 880, top: 356, right: 1180, bottom: 386 }];  // pin chip + Vigil below it
  const size = { w: 250, h: 70 };
  test("nothing to avoid: exactly placeBeside's spot", () => {
    assert.deepEqual(placeClear(gen, size, vp, [], 12), placeBeside(gen, size, vp, 12));
    assert.deepEqual(placeClear(gen, size, vp, null, 12), placeBeside(gen, size, vp, 12));
  });
  test("the natural spot below would cover the chips, so the note goes above its control", () => {
    const below = placeBeside(gen, size, vp, 12);
    assert.equal(below.placement, "below");
    const p = placeClear(gen, size, vp, chips, 12);
    assert.equal(p.placement, "above");
    assert.ok(p.top + size.h <= gen.top, "the card ends above the control");
  });
  test("slides along the row before it gives up a side", () => {
    // a chip under the control's right half only: the left-aligned card below clears it
    const ctl = { left: 500, top: 20, right: 700, bottom: 50 };
    const p = placeClear(ctl, size, vp, [{ left: 740, top: 60, right: 900, bottom: 90 }], 12);
    assert.equal(p.placement, "below");
    assert.ok(p.left + size.w <= 740);
  });
  test("no spot clears the chips: null, and that note is not shown", () => {
    const all = [{ left: 0, top: 0, right: 1280, bottom: 290 }, { left: 0, top: 350, right: 1280, bottom: 900 }];
    assert.equal(placeClear(gen, size, vp, all, 12), null);
  });
  test("an empty rect (a chip that is not drawn) blocks nothing", () => {
    const p = placeClear(gen, size, vp, [{ left: 900, top: 356, right: 900, bottom: 356 }], 12);
    assert.equal(p.placement, "below");
  });
  test("the row is the goal chips, the credits, the claim and Activity", () => {
    for (const sel of [".mgg-chips", ".mgx-cred", ".mgx-claim", ".mgx-act-wrap"]) {
      assert.ok(CHIP_ROW.split(",").map((s) => s.trim()).includes(sel), sel);
    }
  });
});

// Owner walk 2026-09-29, second pass: after the tour's Done, the note "Filters live here." sat
// right under Filters -- over the nav row (IMPORT · CONTESTS · HEALTH · PANEL) -- and a click on
// HEALTH landed on the note. A note keeps clear of EVERY control in the header and nav band, and
// a header control's note drops below the band, over the grid.
describe("a note never covers another control in the header", () => {
  // the owner's walk: a 1568×744 page, the hero banner over the nav band, Filters in the bar
  const vp = { w: 1568, h: 744 };
  const filters = { left: 285, top: 210, right: 346, bottom: 236 };
  const band = { top: 0, bottom: 286 };                       // the sticky header's foot
  const nav = [[263, 300], [316, 372], [386, 430], [446, 498], [515, 562]]   // IMPORT … LOG OUT
    .map(([l, r]) => ({ left: l, top: 252, right: r, bottom: 270 }));
  const bar = [{ left: 18, top: 210, right: 278, bottom: 236 }, filters,
    { left: 354, top: 210, right: 400, bottom: 236 }, { left: 408, top: 210, right: 482, bottom: 236 }];
  const size = { w: 250, h: 46 };
  const hits = (p, rects) => rects.some((a) => p.left < a.right && a.left < p.left + size.w
    && p.top < a.bottom && a.top < p.top + size.h);

  test("the spot under Filters covers the nav links, so the note drops below the band, lined up with Filters", () => {
    const natural = placeBeside(filters, size, vp, 12);
    assert.ok(hits(natural, nav), "the old spot sat on IMPORT · CONTESTS · HEALTH · PANEL");
    const p = placeClear(filters, size, vp, [...nav, ...bar], 12, undefined, band);
    assert.ok(p, "there is a clear spot");
    assert.ok(!hits(p, [...nav, ...bar]), "covers no control");
    assert.equal(p.top, band.bottom + 12, "just below the header, over the grid");
    assert.equal(p.left, filters.left);
  });
  test("a clear natural spot still wins -- the band is the second choice, not the first", () => {
    const p = placeClear(filters, size, vp, [], 12, undefined, band);
    assert.deepEqual(p, placeBeside(filters, size, vp, 12));
  });
  test("a control outside the band (the dock's) gets no below-the-band spot", () => {
    const dockCtl = { left: 600, top: 500, right: 700, bottom: 530 };
    const all = [{ left: 0, top: 0, right: 1568, bottom: 490 }, { left: 0, top: 540, right: 1568, bottom: 744 }];
    assert.equal(placeClear(dockCtl, size, vp, all, 12, undefined, band), null);
  });
  test("no clear spot anywhere -- the band's foot too near the screen's -- null: the note is skipped", () => {
    const tall = { top: 0, bottom: 700 };
    const all = [{ left: 0, top: 0, right: 1568, bottom: 209 }, { left: 0, top: 237, right: 1568, bottom: 744 }];
    assert.equal(placeClear(filters, size, vp, all, 12, undefined, tall), null);
  });
  test("what counts: every clickable, typable or draggable thing in the header band, and the chips", () => {
    assert.equal(HEADER_BAND, ".mgx-hdr");
    const sels = HEADER_CONTROLS.split(",").map((s) => s.trim());
    for (const s of ["button", "a[href]", "input", "select", '[role="button"]', '[role="link"]',
      '[role="slider"]', ".mgl-search", '[tabindex]:not([tabindex="-1"])']) {
      assert.ok(sels.includes(HEADER_BAND + " " + s), s);
    }
    assert.ok(sels.every((s) => s.startsWith(HEADER_BAND + " ")), "scoped to the header band");
    assert.ok(NOTE_AVOID.startsWith(CHIP_ROW + ", "), "the chip row stays in");
    // App.jsx's header IS the band: the banner (library bar inside it) and the nav band
    const app = readFileSync(path.resolve(__dirname, "../../gallery/src/App.jsx"), "utf8");
    const hdr = app.slice(app.indexOf('<header className="mgx-hdr"'), app.indexOf("</header>"));
    assert.ok(hdr.includes("<Banner") && hdr.includes("<SeparatorBar") && hdr.includes("<LibraryBar"));
  });
  test("GuideHost measures the header's controls and its band for every desktop note", () => {
    assert.match(HOST_SRC, /document\.querySelectorAll\(NOTE_AVOID\)/);
    assert.match(HOST_SRC, /document\.querySelector\(HEADER_BAND\)/);
    assert.equal((HOST_SRC.match(/placeClear\([^\n]*?, ob\.avoid, 12, undefined, ob\.band\)/g) || []).length, 2,
      "both the look-up and the card's placement use the same obstacles");
    assert.doesNotMatch(HOST_SRC, /chipRects\(\)/, "no longer only the chips");
  });
});

// Owner walk 2026-09-29: notes sat on top of the Generate model picker, the Colour palette
// dialog and the recipe market.
describe("the welcome card and the notes never draw over an open layer", () => {
  test("any open dialog, menu, list or picker that is not the surface itself", () => {
    assert.equal(layerOpen([]), false);
    assert.equal(layerOpen([{ showing: true, own: false, holdsAnchor: false }]), true);
  });
  test("the guide's own cards, the surface's own slab and hidden layers do not count", () => {
    assert.equal(layerOpen([{ showing: true, own: true, holdsAnchor: false }]), false);
    assert.equal(layerOpen([{ showing: true, own: false, holdsAnchor: true }]), false);   // the dock, the Folio
    assert.equal(layerOpen([{ showing: false, own: false, holdsAnchor: false }]), false); // a closed model browser
    assert.equal(layerOpen([
      { showing: true, own: false, holdsAnchor: true },
      { showing: true, own: false, holdsAnchor: false },
    ]), true);
  });
  test("the layers it looks for include the three the owner met", () => {
    const sels = LAYER_SELECTORS.split(",").map((s) => s.trim());
    for (const sel of ['[role="dialog"]', '[aria-modal="true"]', '[role="menu"]', '[role="listbox"]',
      ".mfly.open", ".mg-gallery-picker"]) {
      assert.ok(sels.includes(sel), sel);
    }
  });
  test("GuideHost holds the welcome card and the notes while a layer is up", () => {
    assert.match(HOST_SRC, /const layerUp = useLayerOver\(guide, watch\)/);
    assert.match(HOST_SRC, /\|\| \(watch && layerUp\)\) return null/);
    assert.match(HOST_SRC, /st\.phase === "welcome" \|\| \(st\.phase === "notes" && !notesOff\)/);
  });
});

describe("every note has a way out", () => {
  test("hide notes is on the desktop note and the phone note, and it is Help's switch", () => {
    assert.match(HOST_SRC, /onClick=\{\(\) => setNotesHidden\(true\)\}/);
    assert.match(HOST_SRC, />hide notes<\/button>/);
    assert.match(HOST_SRC, /<div className="mgguide-nfoot phone">\{hide\}<\/div>/);
    assert.match(HOST_SRC, /\{hide\}\s*<button type="button" className="mgguide-gotit" onClick=\{wave\}>got it<\/button>/);
  });
  test("Escape waves off the note on screen, like got it", () => {
    assert.match(HOST_SRC, /const wave = useCallback\(\(\) => onAdvance\(afterNote\(j, total\)\)/);
    assert.match(HOST_SRC, /showing \? claimEscape\(wave\) : undefined/);
  });
  test("Skip and Escape end the tour as skipped; only Done is finished", () => {
    assert.match(HOST_SRC, /onEnd\(afterTour\(lastIdx, tourCount, !finished\)\)/);
    assert.match(HOST_SRC, /last \? end\(true\) : setK\(k \+ 1\)/);
    assert.match(HOST_SRC, /claimEscape\(\(\) => end\(false\)\)/);
  });
});

describe("the step data file", () => {
  test("every surface has a welcome card, a 3-4 step tour and notes, on both layouts", () => {
    for (const surface of GUIDE_SURFACES) {
      for (const phone of [false, true]) {
        const g = stepsFor(surface, phone);
        assert.ok(g, surface + (phone ? " phone" : ""));
        assert.ok(g.welcome.title && g.welcome.body, surface + " welcome copy");
        const tour = tourSteps(g.steps);
        assert.ok(tour.length >= 3 && tour.length <= 4, surface + " tour is 3-4 marks, got " + tour.length);
        // the tour is the list's PREFIX -- the cursor arithmetic depends on it
        assert.deepEqual(g.steps.slice(0, tour.length), tour, surface + ": tour steps come first");
        assert.ok(g.steps.length > tour.length, surface + " has notes past the tour");
        for (const s of g.steps) {
          assert.ok(s.id && s.at && noteText(s), surface + " step " + s.id);
        }
        const ids = g.steps.map((s) => s.id);
        assert.equal(new Set(ids).size, ids.length, surface + " step ids are unique");
      }
    }
    assert.deepEqual(Object.keys(GUIDE).sort(), [...GUIDE_SURFACES].sort());
  });
  test("no step's copy names a feat or how the Branding tab is earned", () => {
    const text = JSON.stringify(GUIDE).toLowerCase();
    for (const word of ["under the hood", "unlock", "earn the", "feat"]) {
      assert.ok(!text.includes(word), "guide copy mentions '" + word + "'");
    }
  });
});

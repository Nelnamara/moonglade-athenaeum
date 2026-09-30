import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  readGuide, afterWelcome, afterTour, afterNote, tourSteps, noteText, firstPresentNote,
  placeBeside, placeClear, rectShowing, guideKey, GUIDE_SURFACES, CHIP_ROW, LAYER_SELECTORS,
  layerOpen,
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

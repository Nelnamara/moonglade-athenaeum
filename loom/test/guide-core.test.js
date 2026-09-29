import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  readGuide, afterWelcome, afterTour, afterNote, tourSteps, noteText, firstPresentNote,
  placeBeside, rectShowing, guideKey, GUIDE_SURFACES,
} from "../../gallery/src/help/guideCore.js";
import { GUIDE, stepsFor } from "../../gallery/src/help/guideSteps.js";

/* The first-run guide's state machine and placement (gallery/src/help/guideCore.js), and
   the shape of its one data file (gallery/src/help/guideSteps.js) that later waves edit. */

describe("the stored state", () => {
  test("absent is the first visit; unknown is done, never a second welcome", () => {
    assert.deepEqual(readGuide(undefined), { phase: "welcome", n: 0 });
    assert.deepEqual(readGuide("tour"), { phase: "tour", n: 0 });
    assert.deepEqual(readGuide("notes:3"), { phase: "notes", n: 3 });
    assert.deepEqual(readGuide("done"), { phase: "done", n: 0 });
    assert.deepEqual(readGuide({ weird: true }), { phase: "done", n: 0 });
    assert.equal(guideKey("dock"), "guide.dock");
  });
  test("the welcome card's answers", () => {
    assert.equal(afterWelcome("tour"), "tour");
    assert.equal(afterWelcome("gotit"), "notes:0");
  });
  test("the tour hands the notes what it did not reach", () => {
    assert.equal(afterTour(3, 4), "notes:4");      // finished: notes start after the tour
    assert.equal(afterTour(0, 4), "notes:1");      // skipped on step 1
    assert.equal(afterTour(9, 4), "notes:4");      // clamped
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

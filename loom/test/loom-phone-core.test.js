import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { SWIPE_MIN_PX, LONG_PRESS_MS, swipeDir, adjacentTakeN } from "../src/loom-phone-core.js";
import { landTake, beginRender, adoptTask, selectTake } from "../src/loom-takes-core.js";

/* The phone Loom's take gestures (Session P, Stage B2; the page's P1 "Phone:" line). */

// A card with three takes, the middle one ★ (take 1 legacy, takes 2 and 3 rendered here).
function threeTakes() {
  let c = { id: "c1", status: "done", resultMid: "901", actualDur: 5, trimIn: 0, trimOut: null };
  for (const [sub, task, mid] of [["s2", "t2", "902"], ["s3", "t3", "903"]]) {
    c = beginRender(c, { submitId: sub, settings: null, anchor: null, board: "b", at: "2026-09-29T00:00:00Z" });
    c = adoptTask(c, sub, task);
    c = landTake(c, { mid, taskId: task, dur: 5, at: "2026-09-29T00:00:01Z" }).card;
  }
  return selectTake(c, 2);
}

describe("swipeDir: a sideways swipe past the threshold, never a scroll", () => {
  test("left is the next take, right the previous; short or vertical is nothing", () => {
    assert.equal(SWIPE_MIN_PX, 40);
    assert.equal(LONG_PRESS_MS, 500);
    assert.equal(swipeDir(-60, 4), 1);
    assert.equal(swipeDir(60, -4), -1);
    assert.equal(swipeDir(-39, 0), 0, "under the threshold");
    assert.equal(swipeDir(-60, 70), 0, "more vertical than sideways: the sheet is scrolling");
    assert.equal(swipeDir(-60, 50), 0, "not clearly sideways");
    assert.equal(swipeDir(undefined, undefined), 0);
  });
});

describe("adjacentTakeN: the take a swipe lands on", () => {
  test("from the ★ take, by number, without wrapping", () => {
    const c = threeTakes();
    assert.equal(adjacentTakeN(c, 1), 3);
    assert.equal(adjacentTakeN(c, -1), 1);
    const last = selectTake(c, 3);
    assert.equal(adjacentTakeN(last, 1), null, "past the newest take nothing happens");
    assert.equal(adjacentTakeN(selectTake(c, 1), -1), null, "past the oldest take nothing happens");
    assert.equal(adjacentTakeN(c, 0), null);
  });
  test("an unrendered shot has no take to swipe to; a legacy one has only take 1", () => {
    assert.equal(adjacentTakeN({ id: "x", status: "todo" }, 1), null);
    assert.equal(adjacentTakeN({ id: "x", status: "done", resultMid: "5" }, 1), null);
  });
  test("it only names a number: the card is not written", () => {
    const c = threeTakes();
    const before = JSON.stringify(c);
    adjacentTakeN(c, 1); adjacentTakeN(c, -1);
    assert.equal(JSON.stringify(c), before);
  });
});

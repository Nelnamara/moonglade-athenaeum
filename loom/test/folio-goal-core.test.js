import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  PIN_KEY, VIGIL_HEADER_KEY, pinnedId, vigilInHeader, canPin, togglePin, pinView, pinEarned,
  vigilView, SWIPE, swipedAway,
} from "../../gallery/src/folio/goalCore.js";

/* The pinned goal (O4) and the Vigil chip (O5), pure. Every honor is invented. The rule under
   every pin test is the one the code keeps: FEATS LEAK NOTHING. A pin only ever resolves to an
   honor that has a count, which is never a feat, never an unmeasured metric, never one already
   earned -- so a hand-edited account document that names one draws no chip and raises nothing. */

const P = (current, threshold) => ({ current, threshold, left: Math.max(0, threshold - current),
  fraction: Math.min(1, current / threshold) });
const H = (id, over = {}) => ({ id, name: "Honor " + id, tier: "common", bucket: "ladder",
  metric: "images", threshold: 10, current: 0, earned: false, points: 5, progress: P(4, 10), ...over });

describe("the account's keys", () => {
  test("the pin and the switch are valid lowercase dotted account keys", () => {
    const re = /^[a-z][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)*$/;
    assert.match(PIN_KEY, re);
    assert.match(VIGIL_HEADER_KEY, re);
    assert.notEqual(PIN_KEY, VIGIL_HEADER_KEY);
  });

  test("pinnedId is a plain non-empty id, else none", () => {
    assert.equal(pinnedId({ [PIN_KEY]: "honor-1" }), "honor-1");
    for (const bad of [undefined, null, "", 7, true, {}, [], "x".repeat(97)]) {
      assert.equal(pinnedId({ [PIN_KEY]: bad }), "", String(bad));
    }
    assert.equal(pinnedId(null), "");
    assert.equal(pinnedId(undefined), "");
  });

  test("the Vigil switch is on only for a real true", () => {
    assert.equal(vigilInHeader({ [VIGIL_HEADER_KEY]: true }), true);
    for (const v of [false, "true", 1, null, undefined]) {
      assert.equal(vigilInHeader({ [VIGIL_HEADER_KEY]: v }), false);
    }
    assert.equal(vigilInHeader(null), false);
  });
});

describe("O4: what can be pinned", () => {
  test("an unearned honor with a count can", () => {
    assert.equal(canPin(H("a")), true);
  });

  test("no count means no pin: no progress, unknown metric, earned, or a feat of any kind", () => {
    assert.equal(canPin(H("a", { progress: undefined })), false);
    assert.equal(canPin(H("a", { earned: true })), false);
    for (const over of [{ tier: "feat" }, { bucket: "feat" }, { bucket: "meta" }]) {
      assert.equal(canPin(H("a", over)), false, JSON.stringify(over));
    }
    assert.equal(canPin(null), false);
  });

  test("a pin is ONE: pinning another replaces it, pinning the pinned lets go", () => {
    assert.equal(togglePin("", H("a")), "a");
    assert.equal(togglePin("a", H("b")), "b");
    assert.equal(togglePin("a", H("a")), "");
  });

  test("a click on something that cannot be pinned writes nothing (null)", () => {
    assert.equal(togglePin("a", H("f", { tier: "feat" })), null);
    assert.equal(togglePin("a", H("g", { progress: undefined })), null);
    assert.equal(togglePin("a", null), null);
  });
});

describe("O4: the chip's view", () => {
  const list = [H("a", { name: "Rung A", progress: P(4, 10), metric: "images" }),
    H("done", { earned: true }), H("f", { tier: "feat", bucket: "feat", progress: P(1, 2) }),
    H("nometric", { progress: undefined })];

  test("the name, the true fraction, N to go and the jump", () => {
    const v = pinView(list, "a");
    assert.equal(v.id, "a");
    assert.equal(v.name, "Rung A");
    assert.equal(v.fraction, 0.4);
    assert.equal(v.left, 6);
    assert.equal(v.toGo, "6 to go");
    assert.equal(v.text, "Rung A · 6 to go");
    assert.equal(v.jump, "generate");
  });

  test("an honor with a count but no surface still draws, with no jump", () => {
    const v = pinView([H("z", { metric: "some_metric_nobody_routes" })], "z");
    assert.equal(v.jump, "");
    assert.equal(v.toGo, "6 to go");
  });

  test("no chip for: no pin, an id not in the payload, an earned honor, a feat, an unmeasured metric", () => {
    for (const id of ["", "missing", "done", "f", "nometric"]) assert.equal(pinView(list, id), null, id);
    assert.equal(pinView(null, "a"), null);
    assert.equal(pinView(undefined, "a"), null);
  });

  test("the last stretch reads nearly there, never 0 to go", () => {
    const v = pinView([H("n", { progress: P(10, 10) })], "n");
    assert.equal(v.toGo, "nearly there");
  });
});

describe("O4: clearing when it is earned", () => {
  test("only the marking read's newly-earned list clears the pin", () => {
    assert.equal(pinEarned("a", ["b", "a"]), true);
    assert.equal(pinEarned("a", ["b"]), false);
    assert.equal(pinEarned("", ["a"]), false);
    assert.equal(pinEarned("a", undefined), false);
    assert.equal(pinEarned("a", "a"), false);
  });
});

describe("O5: the Vigil view", () => {
  test("day and best, as the chip says them", () => {
    assert.deepEqual(vigilView({ day: 6, best: 9 }), { day: 6, best: 9, text: "Vigil · day 6", bestText: "best 9" });
  });

  test("a miss is a smaller number and nothing else: no message, no flag", () => {
    const v = vigilView({ day: 1, best: 9 });
    assert.deepEqual(Object.keys(v).sort(), ["best", "bestText", "day", "text"]);
    assert.equal(v.text, "Vigil · day 1");
    assert.equal(v.bestText, "best 9");
  });

  test("best is never shown below the day", () => {
    assert.equal(vigilView({ day: 5, best: 2 }).best, 5);
    assert.equal(vigilView({ day: 5 }).bestText, "best 5");
  });

  test("nothing usable is no chip", () => {
    for (const bad of [null, undefined, "x", {}, { day: 0 }, { day: -1 }, { day: 1.5 }, { day: "3" }, { day: NaN }]) {
      assert.equal(vigilView(bad), null, JSON.stringify(bad));
    }
  });
});

describe("the phone's swipe", () => {
  test("far enough and mostly sideways is an unpin, either way", () => {
    assert.equal(swipedAway(SWIPE.MIN_PX, 0), true);
    assert.equal(swipedAway(-120, 10), true);
  });
  test("too short, or more vertical than sideways, is not", () => {
    assert.equal(swipedAway(SWIPE.MIN_PX - 1, 0), false);
    assert.equal(swipedAway(80, 70), false);
    assert.equal(swipedAway(0, 200), false);
    assert.equal(swipedAway(undefined, undefined), false);
  });
});

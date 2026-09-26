import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* Train a LoRA -- the two rules both train panels share with the server (SCOPE_2026-09-26 E7,
   review fixes). normalizeTrigger is the same five steps as core.normalize_trigger_words
   (tests/test_training_parity.py holds the Python side with these same cases), and the
   counter shows its `length`: UTF-16 code units, the unit PixAI's own 256 / 30 rule counts.
   acceptCostField is what the confirm sends: the AMOUNT the ticked box named, which the
   server refuses (409) once it is no longer the run's price. */

import { acceptCostField, normalizeTrigger } from "../../gallery/src/gen/trainCore.js";

describe("trigger words, as PixAI tidies and counts them", () => {
  const cases = [
    ["  nel   druid  ", "nel druid"],
    ["Nel\r\nDruid", "nel, druid"],
    ["A\n\n\nB", "a, b"],
    ["a,, ,b", "a, b"],
    [",, x ,,", "x"],
    ["Hatsune Miku,  , Aqua Hair\n", "hatsune miku, aqua hair"],
    ["\t tab\tand  space ", "tab and space"],
    [null, ""],
    [undefined, ""],
  ];
  for (const [raw, want] of cases) {
    test(JSON.stringify(raw) + " -> " + JSON.stringify(want), () => {
      assert.equal(normalizeTrigger(raw), want);
    });
  }

  test("the counter's number is the tidied length, an emoji counting 2", () => {
    assert.equal(normalizeTrigger("   " + "y".repeat(25) + "   \n\n  ").length, 25);
    assert.equal(normalizeTrigger("\u{1F319}".repeat(15)).length, 30);
  });
});

describe("the confirm's accept_credit_cost", () => {
  test("nothing for a free run", () => {
    assert.deepEqual(acceptCostField({ is_free: true, price: 25000 }, true), {});
    assert.deepEqual(acceptCostField(null, true), {});
  });

  test("the amount the box named, true only when none could be quoted", () => {
    assert.deepEqual(acceptCostField({ is_free: false, price: 25000 }, true),
      { accept_credit_cost: 25000 });
    assert.deepEqual(acceptCostField({ is_free: false, price: null }, true),
      { accept_credit_cost: true });
    assert.deepEqual(acceptCostField({ is_free: false, price: 25000 }, false),
      { accept_credit_cost: false });
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { moveItem, moveBy, orderChanged, dropIndex, orderNote } from "../../gallery/src/curation/collectionOrderCore.js";

/* Session P, P6 (manual order), the gallery's pure half. The server owns the stored order
   (tests/test_collection_order.py); these pin what the order editor decides before it asks. */

describe("the order editor's moves", () => {
  const L = ["a", "b", "c", "d"];
  test("a drag moves one row to where it is dropped", () => {
    assert.deepEqual(moveItem(L, 0, 2), ["b", "c", "a", "d"]);
    assert.deepEqual(moveItem(L, 3, 0), ["d", "a", "b", "c"]);
    assert.deepEqual(moveItem(L, 1, 1), L);
    assert.deepEqual(moveItem(L, 5, 0), L);
    assert.deepEqual(L, ["a", "b", "c", "d"], "never mutates what it is given");
  });
  test("▲ ▼ are the same move by one; the ends do nothing", () => {
    assert.deepEqual(moveBy(L, 1, -1), ["b", "a", "c", "d"]);
    assert.deepEqual(moveBy(L, 2, 1), ["a", "b", "d", "c"]);
    assert.deepEqual(moveBy(L, 0, -1), L);
    assert.deepEqual(moveBy(L, 3, 1), L);
  });
  test("changed, the drop row, the note", () => {
    assert.equal(orderChanged(L, L.slice()), false);
    assert.equal(orderChanged(L, moveBy(L, 0, 1)), true);
    assert.equal(dropIndex([0, 40, 80], [40, 40, 40], 10), 0);
    assert.equal(dropIndex([0, 40, 80], [40, 40, 40], 70), 2);
    assert.equal(dropIndex([0, 40, 80], [40, 40, 40], 500), 2);
    // the dragged row's own slot never counts: row 0 dragged down past the middle of row 3
    // takes row 3's place (the phone's long-press drag dropped it one place too far before)
    const tops = [0, 60, 120, 180, 240], hs = [54, 54, 54, 54, 54];
    assert.equal(dropIndex(tops, hs, 215, 0), 3);
    assert.deepEqual(moveItem(["a", "b", "c", "d", "e"], 0, dropIndex(tops, hs, 215, 0)), ["b", "c", "d", "a", "e"]);
    assert.equal(dropIndex(tops, hs, 20, 0), 0);            // still over its own slot: stays
    assert.equal(dropIndex(tops, hs, 70, 3), 1);            // row 3 dragged up above row 1's middle
    assert.equal(dropIndex(tops, hs, 20, 3), 0);
    assert.equal(dropIndex(tops, hs, 999, 1), 4);
    assert.match(orderNote({ manual: false, count: 3, dirty: false }), /oldest first/);
    assert.match(orderNote({ manual: true, count: 3, dirty: false }), /added later go to the end, oldest first/);
    assert.match(orderNote({ manual: true, count: 3, dirty: true }), /Save keeps it/);
  });
});

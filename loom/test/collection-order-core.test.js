import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  SHOTS_HANDOFF_CAP, FROM_SELECTION, moveItem, moveBy, orderChanged, dropIndex, orderNote,
  shotsOrder, shotsSend, shotsNonce,
} from "../../gallery/src/curation/collectionOrderCore.js";
import { SHOTS_HANDOFF_CAP as LOOM_CAP, readShotsMeta } from "../src/loom-url.js";
import { parseCastIdsFromSearch } from "../src/loom-mutations.js";

/* Session P, P6 (manual order) and P5 (as shots, in order), the gallery's pure half. The
   server owns the stored order (tests/test_collection_order.py); these pin what the order
   editor and the Actions menu decide before they ask. */

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

describe("which pictures go, in which order", () => {
  const ordered = ["m3", "m1", "m2", "m9"];            // the collection's own order
  const dated = { m1: "2026-01-01", m2: "2026-01-02", m3: "2026-01-03", m9: "2026-01-09", x: "2025-12-31" };
  test("a collection's order, restricted to the selection", () => {
    assert.deepEqual(shotsOrder({ selection: ["m2", "m3"], ordered, dated }), ["m3", "m2"]);
    assert.deepEqual(shotsOrder({ selection: new Set(["m9", "m1"]), ordered, dated }), ["m1", "m9"]);
  });
  test("no selection: the whole collection in its order", () => {
    assert.deepEqual(shotsOrder({ selection: [], ordered, dated }), ordered);
  });
  test("a plain selection: date order, oldest first (ruling 9)", () => {
    assert.deepEqual(shotsOrder({ selection: ["m9", "m1", "m3"], ordered: null, dated }), ["m1", "m3", "m9"]);
  });
  test("a selected picture the order does not list goes after it, oldest first", () => {
    assert.deepEqual(shotsOrder({ selection: ["m2", "x"], ordered, dated }), ["m2", "x"]);
  });
});

describe("the send", () => {
  test("the Loom's own builder makes the address: ids in order, the collection, the nonce", () => {
    const r = shotsSend({ ids: ["12", "34", "56"], videos: new Set(["34"]), from: "Loom stills", nonce: "k3f9" });
    assert.equal(r.ok, true);
    assert.deepEqual(r.ids, ["12", "56"], "videos are left out, as 'as cast' leaves them out");
    assert.equal(r.href, "/loom?shots=12%2C56&from=Loom+stills&n=k3f9");
    const back = new URL("http://x" + r.href);
    assert.deepEqual(parseCastIdsFromSearch(back.search, "shots"), ["12", "56"]);
    assert.deepEqual(readShotsMeta(back.search), { from: "Loom stills", nonce: "k3f9" });
  });
  test("a plain selection says so", () => {
    const r = shotsSend({ ids: ["1"], videos: [], from: "", nonce: "n" });
    assert.match(r.href, /from=your\+selection/);
    assert.equal(FROM_SELECTION, "your selection");
  });
  test("the cap is ONE constant, shared with the Loom -- and past it is refused, naming it", () => {
    assert.equal(SHOTS_HANDOFF_CAP, 60);
    assert.equal(SHOTS_HANDOFF_CAP, LOOM_CAP);
    const ids = Array.from({ length: 61 }, (_, i) => String(1000 + i));
    const r = shotsSend({ ids, videos: [], from: "Big", nonce: "n" });
    assert.equal(r.ok, false);
    assert.match(r.error, /61 pictures/);
    assert.match(r.error, /at most 60/);
    assert.match(r.error, /Nothing was sent/);
    assert.equal(shotsSend({ ids: ids.slice(0, 60), videos: [], from: "Big", nonce: "n" }).ok, true, "exactly the cap is fine");
    // videos do not count against it
    assert.equal(shotsSend({ ids, videos: [ids[0]], from: "Big", nonce: "n" }).ok, true);
  });
  test("nothing left to send is said, never a silent no-op", () => {
    const r = shotsSend({ ids: ["9"], videos: ["9"], from: "C", nonce: "n" });
    assert.equal(r.ok, false);
    assert.match(r.error, /Only pictures become shots/);
    assert.equal(shotsSend({ ids: ["1", "1"], videos: [], nonce: "n" }).ids.length, 1, "a repeated id is sent once");
  });
  test("a nonce the Loom will accept", () => {
    let k = 0;
    const n = shotsNonce(() => ((k += 7) % 100) / 100);
    assert.match(n, /^[A-Za-z0-9_-]{1,32}$/);
    assert.match(shotsNonce(), /^[a-z0-9]{1,12}$/);
  });
});

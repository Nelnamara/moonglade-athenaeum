import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  anchorInfo, anchorState, staleText, needsNewTake, reanchorPatch, splicePatch, keepAnchor,
  makeAnchor, landTake, selectTake,
} from "../src/loom-takes-core.js";

// Session P, P2 (BUILD-w5-p §2, review N1). The page: a shot whose open frame came from
// another shot's close frame records anchor {shot, take}; when that shot's ★ take changes,
// the dependent shows "⚠ anchor changed"; Re-anchor swaps the frame WITHOUT rendering and
// says to render a new take; Keep accepts that pair only.

const src = (extra) => ({ id: "A1", status: "done", resultMid: "MA1", actualDur: 8, trimIn: 0, trimOut: null, ...(extra || {}) });
const renderTake = (c, mid, tid) =>
  landTake({ ...c, status: "wip", pendingSubmitId: "S" + tid, pendingTaskId: tid }, { mid, taskId: tid, dur: 8 }).card;
const dep = (s, extra) => {
  const a = makeAnchor(s, "F1", "splice");
  return { id: "A2", status: "done", resultMid: "MA2", openFrame: { mediaId: "F1" }, anchor: a, ...(extra || {}) };
};
const byId = (...cards) => Object.fromEntries(cards.map((c) => [c.id, c]));

describe("anchorState", () => {
  test("ok while the source uses the anchored take at the same cut", () => {
    const s = src();
    assert.equal(anchorState(dep(s), byId(s)), "ok");
  });
  test("stale when the source's ★ take changes", () => {
    const s0 = src();
    const d = dep(s0);
    const s1 = renderTake(s0, "MA1b", "T2");
    const info = anchorInfo(d, byId(s1));
    assert.equal(info.state, "stale");
    assert.equal(staleText(info, () => "A·01"), "its open frame came from A·01 take 1; A·01 now uses take 2.");
    assert.equal(anchorState(d, byId(selectTake(s1, 1))), "ok", "back on the anchored take");
  });
  test("N1: stale when the source's ★ take is re-trimmed (the handoff frame moved)", () => {
    const s0 = src();
    const d = dep(s0);
    const info = anchorInfo(d, byId({ ...s0, trimOut: 3.2 }));
    assert.equal(info.state, "stale");
    assert.match(staleText(info, () => "A·01"), /now cut at 3\.2 s/);
  });
  test("none: no anchor, source gone, source unrendered, or the frame replaced another way", () => {
    const s = src();
    assert.equal(anchorState({ id: "x" }, byId(s)), "none");
    assert.equal(anchorState(dep(s), {}), "none");
    assert.equal(anchorState(dep(s), byId({ ...s, resultMid: "" })), "none");
    assert.equal(anchorState({ ...dep(s), openFrame: { mediaId: "picked" } }, byId(s)), "none");
  });
  test("an UNRENDERED dependent is flagged too (open call 2)", () => {
    const s0 = src();
    const d = { ...dep(s0), resultMid: "", status: "todo" };
    assert.equal(anchorState(d, byId(renderTake(s0, "MA1b", "T2"))), "stale");
  });
  test("a legacy card (no anchor) is never stale", () => {
    assert.equal(anchorState({ id: "L", openFrame: { mediaId: "x", desc: "handed off from A·01" } }, byId(src())), "none");
  });
  test("a Map works as the lookup too", () => {
    const s = src();
    assert.equal(anchorState(dep(s), new Map([["A1", s]])), "ok");
  });
});

describe("Keep accepts this take pair only", () => {
  test("kept for the pair, stale again when the source changes again", () => {
    const s0 = src();
    const s1 = renderTake(s0, "MA1b", "T2");
    const d = keepAnchor(dep(s0), s1);
    assert.deepEqual(d.anchorKept, { from: 1, to: 2, at: 8 });
    assert.equal(anchorState(d, byId(s1)), "kept");
    const s2 = renderTake(s1, "MA1c", "T3");
    assert.equal(anchorState(d, byId(s2)), "stale");
  });
  test("a new take of the DEPENDENT does not re-warn (open call 11)", () => {
    const s0 = src();
    const s1 = renderTake(s0, "MA1b", "T2");
    let d = keepAnchor(dep(s0), s1);
    d = renderTake(d, "MA2b", "T9");
    assert.equal(anchorState(d, byId(s1)), "kept");
  });
});

describe("Re-anchor swaps the frame and never renders", () => {
  test("touches only openFrame / anchor / anchorKept", () => {
    const s0 = src();
    const s1 = renderTake(s0, "MA1b", "T2");
    const d = { ...dep(s0), takes: [{ n: 1, mid: "MA2" }], selectedTake: 1, takeSeq: 1,
      pendingTaskId: null, pendingSubmitId: null, status: "done", anchorKept: { from: 1, to: 2 } };
    const out = reanchorPatch(d, { frameMid: "F2", src: s1, srcCode: "A·01", expect: d.anchor });
    assert.equal(out.openFrame.mediaId, "F2");
    assert.equal(out.openFrame.desc, "handed off from A·01 take 2");
    assert.deepEqual(out.anchor, { shot: "A1", take: 2, at: 8, frame: "F2", via: "reanchor" });
    assert.equal(out.anchorKept, null);
    ["status", "takes", "selectedTake", "takeSeq", "resultMid", "pendingTaskId", "pendingSubmitId"]
      .forEach((k) => assert.deepEqual(out[k], d[k], k));
    assert.equal(anchorState(out, byId(s1)), "ok");
    assert.equal(needsNewTake(out), true, "the card says to render a new take");
  });
  test("a stale click (the anchor moved since) patches nothing", () => {
    const s0 = src();
    const d = dep(s0);
    const moved = { ...d, anchor: { ...d.anchor, take: 5 } };
    assert.equal(reanchorPatch(moved, { frameMid: "F2", src: s0, expect: d.anchor }), moved);
  });
  test("needsNewTake clears once a take rendered from the new anchor is selected", () => {
    const s1 = renderTake(src(), "MA1b", "T2");
    let d = reanchorPatch(dep(src()), { frameMid: "F2", src: s1, srcCode: "A·01", expect: dep(src()).anchor });
    assert.equal(needsNewTake(d), true);
    d = landTake({ ...d, status: "wip", pendingSubmitId: "S", pendingTaskId: "Tn", pendingAnchor: d.anchor },
      { mid: "MA2new", taskId: "Tn" }).card;
    assert.equal(needsNewTake(d), false);
    d = selectTake(d, 1);
    assert.equal(needsNewTake(d), true, "the old take does not match the new frame");
  });
  test("the splice records an anchor only when the source has a render", () => {
    const d = splicePatch({ id: "A2", openFrame: {} }, { frameMid: "F1", src: src(), srcCode: "A·01" });
    assert.equal(d.anchor.via, "splice");
    assert.equal(d.openFrame.desc, "handed off from A·01");
    const e = splicePatch({ id: "A2", openFrame: {} }, { frameMid: "F1", src: { id: "A1", resultMid: "" } });
    assert.equal(e.anchor, null);
  });
});

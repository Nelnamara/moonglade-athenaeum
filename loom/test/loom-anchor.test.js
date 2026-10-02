import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  anchorInfo, anchorState, staleText, needsNewTake, reanchorPatch, splicePatch, keepAnchor,
  makeAnchor, landTake, selectTake, cutPointOf,
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

/* Owner walk 2026-09-30: E·02's open frame was spliced from E·01's END (5.0 s); after E·01 was
   trimmed to 3.2 s the card said "its open frame came from E·01 take 1 at 0.0 s". E·01's take
   had no recorded clip length (actualDur null), and Number(null) is 0, so the anchor recorded
   0 -- and a Re-anchor of such a shot asked the handoff for the frame at 0, the FIRST frame.
   The anchor now records where the handoff really cut ({at, end}, the route's own answer), and
   an unknown length stays unknown. */
describe("the anchor records where the frame really came from", () => {
  const e01 = (extra) => src({ id: "E1", resultMid: "ME1", actualDur: null, duration: 5, ...(extra || {}) });
  const spliced = (s, took) => ({ id: "E2", status: "done", resultMid: "ME2",
    ...splicePatch({ id: "E2", openFrame: {} }, { frameMid: "FE", src: s, srcCode: "E·01", took }) });
  test("an unknown clip length is unknown, never 0 (and never asks the handoff for the first frame)", () => {
    assert.equal(cutPointOf(e01()), null);
    assert.equal(cutPointOf(e01({ actualDur: "" })), null);
    assert.equal(cutPointOf(e01({ trimOut: 3.2 })), 3.2);
    assert.equal(cutPointOf(src()), 8, "a known length is the cut point of an untrimmed take");
  });
  test("the walk: spliced from the end, then the source is trimmed to 3.2 s", () => {
    const s = e01();
    const d = spliced(s, { at: 5.04, end: true });
    assert.deepEqual(d.anchor, { shot: "E1", take: 1, at: 5.04, frame: "FE", via: "splice", end: true });
    assert.equal(anchorState(d, byId(s)), "ok", "a true handoff reads as the same cut");
    const info = anchorInfo(d, byId({ ...s, trimOut: 3.2 }));
    assert.equal(info.state, "stale");
    assert.equal(staleText(info, () => "E·01"),
      "its open frame came from E·01 take 1 at 5.0 s; E·01 is now cut at 3.2 s.");
  });
  test("an end frame stays the same cut while the source plays to its end, whatever its length", () => {
    const s = e01();
    const d = spliced(s, { at: 5.04, end: true });
    assert.equal(anchorState(d, byId({ ...s, actualDur: 5.04 })), "ok");
    assert.equal(anchorState(d, byId({ ...s, trimOut: 5.02 })), "ok", "cut at that very point");
    assert.equal(anchorState(spliced(s, { at: null, end: true }), byId({ ...s, trimOut: 3.2 })), "stale");
  });
  test("a frame from a trim point: the same cut until the source is cut elsewhere, or not at all", () => {
    const s = e01({ trimOut: 3.2 });
    const d = spliced(s, { at: 3.2, end: false });
    assert.equal(d.anchor.at, 3.2);
    assert.equal(anchorState(d, byId(s)), "ok");
    const info = anchorInfo(d, byId({ ...s, trimOut: null }));
    assert.equal(info.state, "stale");
    assert.equal(staleText(info, () => "E·01"), "its open frame came from E·01 take 1 at 3.2 s; E·01 is now cut at 5.0 s.",
      "untrimmed, of unknown length: its planned length");
  });
  test("Re-anchor records the handoff's own answer too", () => {
    const s0 = e01();
    const d = spliced(s0, { at: 5.04, end: true });
    const s1 = { ...s0, trimOut: 3.2 };
    const out = reanchorPatch(d, { frameMid: "FE2", src: s1, srcCode: "E·01", expect: d.anchor, took: { at: 3.2, end: false } });
    assert.deepEqual(out.anchor, { shot: "E1", take: 1, at: 3.2, frame: "FE2", via: "reanchor", end: false });
    assert.equal(anchorState(out, byId(s1)), "ok");
  });
  test("an older build's splice anchor (0 for 'the end, length unknown') reads as the end", () => {
    const s = e01();
    const d = { id: "E2", status: "done", resultMid: "ME2", openFrame: { mediaId: "FE" },
      anchor: { shot: "E1", take: 1, at: 0, frame: "FE", via: "splice" } };
    assert.equal(anchorState(d, byId(s)), "ok");
    const info = anchorInfo(d, byId({ ...s, trimOut: 3.2 }));
    assert.equal(staleText(info, () => "E·01"), "its open frame came from E·01 take 1 at its end; E·01 is now cut at 3.2 s.");
  });
  test("with no answer from the handoff (an older server) the anchor falls back to the card, as before", () => {
    assert.deepEqual(makeAnchor(src(), "F1", "splice"), { shot: "A1", take: 1, at: 8, frame: "F1", via: "splice" });
  });
});

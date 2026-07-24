import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  patchCard, patchCardById, patchAct, patchAssets,
  appendCardToAct, buildDuplicateCard, insertCardAfter, removeCard, splitCardAt,
  moveCardInAct, moveCardToAct, nextActName, appendAct, removeAct, moveActInProject,
  buildNewRef, patchRef, removeRef, countShots, setShotMode, setShotConnect,
  parseCastIdsFromSearch,
  friendlyGenErr, classifyTaskStatus,
  buildShotListText, buildPlaySequence, buildExportClips,
  setPromptOverride, clearPromptOverride,
  loraIncompat, resolveLoraPayload, anyLoraUnresolved,
  landInFirstAct, importedFootagePatch,
} from "../src/loom-mutations.js";
import { flat, shotText, actLetter } from "../src/loom-core.js";

/* ---------- fixtures ---------- */

function makeCard(overrides = {}) {
  return {
    id: overrides.id || "c1",
    title: "untitled", mode: "R2V", duration: 8, connect: "new", prompt: "",
    cast: [], refs: [], camera: "", lighting: "", audioCue: "", transIn: "", transOut: "", notes: "",
    openFrame: { thumbId: "", source: "", desc: "", tag: "" },
    closeFrame: { thumbId: "", source: "", desc: "", tag: "" },
    status: "todo",
    ...overrides,
  };
}
function makeAct(id, cards = [], overrides = {}) { return { id, name: id, collapsed: false, cards, ...overrides }; }
function makeProject(acts, assets = []) { return { name: "Test", target: 60, assets, acts }; }

/* ---------- patchCard / patchCardById / patchAct / patchAssets ---------- */

describe("patchCard", () => {
  test("patches only the targeted card in the targeted act, leaves others untouched", () => {
    const p = makeProject([
      makeAct("a1", [makeCard({ id: "c1", title: "one" }), makeCard({ id: "c2", title: "two" })]),
      makeAct("a2", [makeCard({ id: "c3", title: "three" })]),
    ]);
    const out = patchCard(p, "a1", "c2", (c) => ({ ...c, title: "TWO" }));
    assert.equal(out.acts[0].cards[0].title, "one");
    assert.equal(out.acts[0].cards[1].title, "TWO");
    assert.equal(out.acts[1].cards[0].title, "three");
    // original untouched (immutability)
    assert.equal(p.acts[0].cards[1].title, "two");
  });
});

describe("setShotMode / setShotConnect (FLF coupling)", () => {
  // Regression coverage for a confirmed production bug: Continuity's "First->Last" chip
  // (connect:"flf") and Mode's "FLF" chip both read as "First->Last" to a user, but only
  // mode gates whether the close frame reaches the real generation (shotPayload /
  // build_shot_video_params check mode==="FLF" alone). Left uncoupled, a shot could show
  // connect:"flf" with mode:"I2V" -- both frames filled in on screen, the generation submits
  // and finishes with no error, and the close frame is silently never used.

  test("selecting First->Last Continuity forces Mode to FLF", () => {
    const c = makeCard({ mode: "I2V", connect: "new" });
    const out = setShotConnect(c, "flf");
    assert.equal(out.connect, "flf");
    assert.equal(out.mode, "FLF");
  });

  test("selecting a non-FLF Continuity leaves Mode alone", () => {
    const c = makeCard({ mode: "R2V", connect: "new" });
    const out = setShotConnect(c, "extend");
    assert.equal(out.connect, "extend");
    assert.equal(out.mode, "R2V");
  });

  test("moving Mode away from FLF clears a 'First->Last' Continuity that can no longer be true", () => {
    const c = makeCard({ mode: "FLF", connect: "flf" });
    const out = setShotMode(c, "I2V");
    assert.equal(out.mode, "I2V");
    assert.equal(out.connect, "new");
  });

  test("moving Mode to FLF doesn't force Continuity (only the dangerous direction is guarded)", () => {
    const c = makeCard({ mode: "I2V", connect: "new" });
    const out = setShotMode(c, "FLF");
    assert.equal(out.mode, "FLF");
    assert.equal(out.connect, "new");
  });

  test("moving Mode between two non-FLF values never touches an unrelated Continuity", () => {
    const c = makeCard({ mode: "I2V", connect: "extend" });
    const out = setShotMode(c, "R2V");
    assert.equal(out.connect, "extend");
  });

  test("the exact reported failure state is unreachable through either setter", () => {
    // Continuity="First->Last" with Mode stuck on something other than FLF must never occur.
    let c = makeCard({ mode: "I2V", connect: "new" });
    c = setShotConnect(c, "flf");
    assert.ok(!(c.connect === "flf" && c.mode !== "FLF"));
    c = setShotMode(c, "R2V");
    assert.ok(!(c.connect === "flf" && c.mode !== "FLF"));
  });
});

describe("patchCardById", () => {
  test("finds the card across ALL acts by id alone", () => {
    const p = makeProject([
      makeAct("a1", [makeCard({ id: "c1" })]),
      makeAct("a2", [makeCard({ id: "c2" })]),
    ]);
    const out = patchCardById(p, "c2", { status: "done", resultMid: "m1" });
    assert.equal(out.acts[0].cards[0].status, "todo");
    assert.equal(out.acts[1].cards[0].status, "done");
    assert.equal(out.acts[1].cards[0].resultMid, "m1");
  });
});

describe("setPromptOverride / clearPromptOverride", () => {
  test("setPromptOverride sets both fields and leaves everything else untouched", () => {
    const c = makeCard({ camera: "dolly out", prompt: "raw" });
    const out = setPromptOverride(c, "hand-edited text");
    assert.equal(out.promptOverride, true);
    assert.equal(out.promptOverrideText, "hand-edited text");
    assert.equal(out.camera, "dolly out");
    assert.equal(out.prompt, "raw");   // raw prompt field is untouched, only the override fields change
    assert.equal(c.promptOverride, undefined);   // original object not mutated
  });
  test("clearPromptOverride resets both fields to their off state", () => {
    const c = setPromptOverride(makeCard(), "some text");
    const out = clearPromptOverride(c);
    assert.equal(out.promptOverride, false);
    assert.equal(out.promptOverrideText, "");
  });
  test("round-trips: set then clear then set again produces the latest text only", () => {
    let c = makeCard();
    c = setPromptOverride(c, "first");
    c = clearPromptOverride(c);
    c = setPromptOverride(c, "second");
    assert.equal(c.promptOverride, true);
    assert.equal(c.promptOverrideText, "second");
  });
});

describe("patchAct / patchAssets", () => {
  test("patchAct merges patch into the named act only", () => {
    const p = makeProject([makeAct("a1"), makeAct("a2")]);
    const out = patchAct(p, "a2", { name: "Renamed", collapsed: true });
    assert.equal(out.acts[0].name, "a1");
    assert.equal(out.acts[1].name, "Renamed");
    assert.equal(out.acts[1].collapsed, true);
  });
  test("patchAssets applies fn to the assets array", () => {
    const p = makeProject([], [{ id: "x" }]);
    const out = patchAssets(p, (a) => [...a, { id: "y" }]);
    assert.equal(out.assets.length, 2);
    assert.equal(p.assets.length, 1);
  });
});

/* ---------- card CRUD: add / duplicate / delete / move ---------- */

describe("appendCardToAct / insertCardAfter", () => {
  test("appendCardToAct adds to the end of the named act", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" })])]);
    const out = appendCardToAct(p, "a1", makeCard({ id: "c2" }));
    assert.deepEqual(out.acts[0].cards.map((c) => c.id), ["c1", "c2"]);
  });
  test("insertCardAfter places the new card right after the original, not at the end", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" }), makeCard({ id: "c2" }), makeCard({ id: "c3" })])]);
    const out = insertCardAfter(p, "a1", "c1", makeCard({ id: "cNew" }));
    assert.deepEqual(out.acts[0].cards.map((c) => c.id), ["c1", "cNew", "c2", "c3"]);
  });
});

describe("landInFirstAct", () => {
  test("appends the card to the project's first act, leaving other acts untouched", () => {
    const p = makeProject([
      makeAct("a1", [makeCard({ id: "c1" })]),
      makeAct("a2", [makeCard({ id: "c2" })]),
    ]);
    const card = makeCard({ id: "imported1", status: "done", resultMid: "M1" });
    const out = landInFirstAct(p, card, "unused-act-id");
    assert.deepEqual(out.acts[0].cards.map((c) => c.id), ["c1", "imported1"]);
    assert.deepEqual(out.acts[1].cards.map((c) => c.id), ["c2"]);   // second act untouched
    assert.equal(p.acts[0].cards.length, 1, "original project must not be mutated");
  });
  test("creates a first act (via nextActName) when the project has none yet", () => {
    const p = makeProject([]);
    const card = makeCard({ id: "imported1", status: "done", resultMid: "M1" });
    const out = landInFirstAct(p, card, "new-act-id");
    assert.equal(out.acts.length, 1);
    assert.equal(out.acts[0].id, "new-act-id");
    assert.equal(out.acts[0].name, "Act 1");
    assert.deepEqual(out.acts[0].cards.map((c) => c.id), ["imported1"]);
  });
});

describe("importedFootagePatch", () => {
  test("marks the patch done + imported, with the picked media as resultMid and a full reset trim", () => {
    const patch = importedFootagePatch("MEDIA123", "12.5");
    assert.equal(patch.status, "done");
    assert.equal(patch.resultMid, "MEDIA123");
    assert.equal(patch.imported, true);
    assert.equal(patch.trimIn, 0);
    assert.equal(patch.trimOut, null);
    assert.equal(patch.actualDur, 12.5);
  });
  test("omits actualDur (leaving newCard's own default duration standing) when the duration is blank, zero, or negative", () => {
    assert.equal("actualDur" in importedFootagePatch("M1", ""), false);
    assert.equal("actualDur" in importedFootagePatch("M1", undefined), false);
    assert.equal("actualDur" in importedFootagePatch("M1", "0"), false);
    assert.equal("actualDur" in importedFootagePatch("M1", "-3"), false);
    assert.equal("actualDur" in importedFootagePatch("M1", "not-a-number"), false);
  });
  test("accepts a real (already-parsed) number, not just a string", () => {
    assert.equal(importedFootagePatch("M1", 9).actualDur, 9);
  });
});

describe("buildDuplicateCard", () => {
  test("resets render state so a dupe never shows done / plays the original clip", () => {
    const card = makeCard({
      id: "orig", status: "done", resultMid: "media123", actualDur: 7.5, trimIn: 1, trimOut: 6,
      refs: [{ id: "r1", kind: "image", tag: "@image1" }],
    });
    const clone = buildDuplicateCard(card, "new-id", ["new-r1"]);
    assert.equal(clone.id, "new-id");
    assert.equal(clone.status, "todo");
    assert.equal(clone.resultMid, "");
    assert.equal(clone.actualDur, null);
    assert.equal(clone.trimIn, 0);
    assert.equal(clone.trimOut, null);
    assert.equal(clone.refs[0].id, "new-r1");
    assert.equal(clone.refs[0].tag, "@image1");   // ref content otherwise preserved
  });
  test("is a deep clone -- mutating the clone's nested objects doesn't touch the original", () => {
    const card = makeCard({ id: "orig", openFrame: { thumbId: "", source: "", desc: "d", tag: "@image1" } });
    const clone = buildDuplicateCard(card, "new-id", []);
    clone.openFrame.desc = "changed";
    assert.equal(card.openFrame.desc, "d");
  });
});

describe("splitCardAt", () => {
  test("divides one rendered shot into two halves of the SAME clip at the playhead", () => {
    const p = makeProject([makeAct("a1", [
      makeCard({ id: "c1", title: "Take", status: "done", resultMid: "M9", actualDur: 8, trimIn: 1, trimOut: 7 }),
      makeCard({ id: "c2", title: "Next" }),
    ])]);
    const out = splitCardAt(p, "a1", "c1", 4, "c1b");
    const cards = out.acts[0].cards;
    assert.deepEqual(cards.map((c) => c.id), ["c1", "c1b", "c2"]);   // new half inserted right after
    // left half keeps the clip, trimmed to the cut
    assert.equal(cards[0].resultMid, "M9"); assert.equal(cards[0].trimIn, 1); assert.equal(cards[0].trimOut, 4);
    // right half is the SAME clip (not a fresh todo), picking up where the left ended
    assert.equal(cards[1].resultMid, "M9"); assert.equal(cards[1].status, "done");
    assert.equal(cards[1].trimIn, 4); assert.equal(cards[1].trimOut, 7);
    assert.match(cards[1].title, /cont\./);
  });
  test("a null trimOut (kept to the real end) splits into [in..t] + [t..null]", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1", status: "done", resultMid: "M", trimIn: 0, trimOut: null })])]);
    const out = splitCardAt(p, "a1", "c1", 3, "c1b");
    assert.equal(out.acts[0].cards[0].trimOut, 3);
    assert.equal(out.acts[0].cards[1].trimIn, 3);
    assert.equal(out.acts[0].cards[1].trimOut, null);
  });
  test("no-ops when the cut would make a zero-length half (at/outside the kept range)", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1", status: "done", resultMid: "M", trimIn: 2, trimOut: 6 })])]);
    assert.equal(splitCardAt(p, "a1", "c1", 2, "x").acts[0].cards.length, 1);   // at the in-edge
    assert.equal(splitCardAt(p, "a1", "c1", 6, "x").acts[0].cards.length, 1);   // at the out-edge
    assert.equal(splitCardAt(p, "a1", "c1", 9, "x").acts[0].cards.length, 1);   // past the end
  });
});

describe("removeCard / moveCardInAct / moveCardToAct", () => {
  test("removeCard drops exactly one card from one act", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" }), makeCard({ id: "c2" })])]);
    const out = removeCard(p, "a1", "c1");
    assert.deepEqual(out.acts[0].cards.map((c) => c.id), ["c2"]);
  });
  test("moveCardInAct swaps with the neighbor in the move direction", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" }), makeCard({ id: "c2" }), makeCard({ id: "c3" })])]);
    const down = moveCardInAct(p, "a1", 0, 1);
    assert.deepEqual(down.acts[0].cards.map((c) => c.id), ["c2", "c1", "c3"]);
  });
  test("moveCardInAct is a no-op past either edge", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" }), makeCard({ id: "c2" })])]);
    const past = moveCardInAct(p, "a1", 0, -1);
    assert.deepEqual(past.acts[0].cards.map((c) => c.id), ["c1", "c2"]);
  });
  test("moveCardToAct relocates the card object between acts", () => {
    const card = makeCard({ id: "c1" });
    const p = makeProject([makeAct("a1", [card]), makeAct("a2", [])]);
    const out = moveCardToAct(p, "a1", card, "a2");
    assert.equal(out.acts[0].cards.length, 0);
    assert.deepEqual(out.acts[1].cards.map((c) => c.id), ["c1"]);
  });
  test("moveCardToAct is a no-op when source === destination", () => {
    const card = makeCard({ id: "c1" });
    const p = makeProject([makeAct("a1", [card])]);
    const out = moveCardToAct(p, "a1", card, "a1");
    assert.equal(out, p);   // same reference -- true no-op, not just equal content
  });
});

/* ---------- act CRUD ---------- */

describe("act CRUD", () => {
  test("nextActName counts from the current act length", () => {
    assert.equal(nextActName(makeProject([])), "Act 1");
    assert.equal(nextActName(makeProject([makeAct("a1"), makeAct("a2")])), "Act 3");
  });
  test("appendAct / removeAct roundtrip", () => {
    const p = makeProject([makeAct("a1")]);
    const added = appendAct(p, makeAct("a2"));
    assert.equal(added.acts.length, 2);
    const removed = removeAct(added, "a1");
    assert.deepEqual(removed.acts.map((a) => a.id), ["a2"]);
  });
  test("moveActInProject swaps acts and no-ops past the edges", () => {
    const p = makeProject([makeAct("a1"), makeAct("a2"), makeAct("a3")]);
    const swapped = moveActInProject(p, 1, -1);
    assert.deepEqual(swapped.acts.map((a) => a.id), ["a2", "a1", "a3"]);
    const clamped = moveActInProject(p, 0, -1);
    assert.equal(clamped, p);
  });
});

/* ---------- refs ---------- */

describe("ref CRUD", () => {
  test("buildNewRef produces an empty ref of the given kind/id", () => {
    const r = buildNewRef("video", "rid1");
    assert.deepEqual(r, { id: "rid1", kind: "video", tag: "", role: "", source: "", thumbId: "" });
  });
  test("patchRef / removeRef operate on one ref within one card", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1", refs: [{ id: "r1", kind: "image", tag: "@image1", role: "", source: "" }] })])]);
    const patched = patchRef(p, "a1", "c1", "r1", { role: "identity" });
    assert.equal(patched.acts[0].cards[0].refs[0].role, "identity");
    const removed = removeRef(patched, "a1", "c1", "r1");
    assert.equal(removed.acts[0].cards[0].refs.length, 0);
  });
});

describe("countShots", () => {
  test("sums cards across all acts", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" }), makeCard({ id: "c2" })]), makeAct("a2", [makeCard({ id: "c3" })])]);
    assert.equal(countShots(p), 3);
  });
  test("handles missing acts/cards gracefully", () => {
    assert.equal(countShots({}), 0);
  });
});

/* ---------- parseCastIdsFromSearch ---------- */

describe("parseCastIdsFromSearch", () => {
  test("extracts comma-separated numeric ids from ?cast=", () => {
    assert.deepEqual(parseCastIdsFromSearch("?cast=123,456,789"), ["123", "456", "789"]);
  });
  test("drops non-numeric junk and ignores other query params", () => {
    assert.deepEqual(parseCastIdsFromSearch("?foo=bar&cast=1,abc,2"), ["1", "2"]);
  });
  test("empty/missing search yields no ids", () => {
    assert.deepEqual(parseCastIdsFromSearch(""), []);
    assert.deepEqual(parseCastIdsFromSearch(undefined), []);
  });
});

/* ---------- friendlyGenErr / classifyTaskStatus ---------- */

describe("friendlyGenErr", () => {
  test("recognizes insufficient-balance errors", () => {
    assert.match(friendlyGenErr("INSUFFICIENT_BALANCE"), /Out of balance/);
    assert.match(friendlyGenErr("error 40300010"), /Out of balance/);
  });
  test("recognizes content-moderation errors", () => {
    assert.match(friendlyGenErr("content policy violation"), /content filter/);
  });
  test("falls back to the raw string, or a default for empty input", () => {
    assert.equal(friendlyGenErr("weird one-off error"), "weird one-off error");
    assert.equal(friendlyGenErr(""), "generation failed");
    assert.equal(friendlyGenErr(null), "generation failed");
  });
});

describe("classifyTaskStatus", () => {
  test("done -> phase done + first media id, duration passed through when present", () => {
    assert.deepEqual(classifyTaskStatus({ phase: "done", media_ids: ["m1", "m2"] }), { phase: "done", mid: "m1" });
    assert.deepEqual(classifyTaskStatus({ phase: "done", media_ids: ["m1"], duration: 12 }), { phase: "done", mid: "m1", duration: 12 });
  });
  test("done with no media_ids still resolves (empty mid, not a crash)", () => {
    assert.deepEqual(classifyTaskStatus({ phase: "done" }), { phase: "done", mid: "" });
  });
  test("failed -> phase failed + friendly message", () => {
    const out = classifyTaskStatus({ phase: "failed", error: "INSUFFICIENT_BALANCE" });
    assert.equal(out.phase, "failed");
    assert.match(out.msg, /Out of balance/);
  });
  test("anything else (running, missing, null) is pending", () => {
    assert.deepEqual(classifyTaskStatus({ phase: "running" }), { phase: "pending" });
    assert.deepEqual(classifyTaskStatus({}), { phase: "pending" });
    assert.deepEqual(classifyTaskStatus(null), { phase: "pending" });
  });
});

/* ---------- export / playback builders ---------- */

function fmt(s) { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

describe("buildShotListText", () => {
  test("includes project name, cast list, and every act/shot's shotText", () => {
    const p = makeProject(
      [makeAct("a1", [makeCard({ id: "c1", title: "Shot one", prompt: "hello" })])],
      [{ id: "as1", tag: "@image1", name: "Her", kind: "image", lock: true }],
    );
    const out = buildShotListText(p, fmt, actLetter, shotText);
    assert.match(out, /Test/);
    assert.match(out, /Cast & assets:/);
    assert.match(out, /@image1\s+Her \(image\) · lock appearance/);
    assert.match(out, /Shot one/);
    assert.match(out, /hello/);
  });
  test("omits the cast section entirely when there are no assets", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" })])], []);
    const out = buildShotListText(p, fmt, actLetter, shotText);
    assert.doesNotMatch(out, /Cast & assets:/);
  });
});

describe("buildPlaySequence", () => {
  test("keeps only finished shots, preserving board order and trim", () => {
    const p = makeProject([makeAct("a1", [
      makeCard({ id: "c1", resultMid: "m1", trimIn: 1, trimOut: 5, title: "A" }),
      makeCard({ id: "c2" }),   // not rendered -- excluded
      makeCard({ id: "c3", resultMid: "m3", title: "C" }),
    ])]);
    const seq = buildPlaySequence(flat(p));
    assert.deepEqual(seq.map((s) => s.mid), ["m1", "m3"]);
    assert.equal(seq[0].in, 1);
    assert.equal(seq[0].out, 5);
    assert.equal(seq[1].in, 0);   // default trimIn when unset
  });
});

describe("buildExportClips", () => {
  test("computes span from actual duration when rendered, planned otherwise", () => {
    const p = makeProject([makeAct("a1", [
      makeCard({ id: "c1", resultMid: "m1", actualDur: 6, duration: 8, trimIn: 1, trimOut: 4 }),
      makeCard({ id: "c2", resultMid: "m2", duration: 10 }),   // no actualDur -> falls back to planned
    ])]);
    const { clips, total } = buildExportClips(flat(p));
    assert.equal(clips[0].span, 3);          // 4 - 1
    assert.equal(clips[1].span, 10);         // full planned duration, no trim
    assert.equal(total, 13);
  });
  test("never produces a zero/negative span (0.1s floor)", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1", resultMid: "m1", trimIn: 5, trimOut: 5 })])]);
    const { clips } = buildExportClips(flat(p));
    assert.equal(clips[0].span, 0.1);
  });
  test("excludes shots with no rendered result", () => {
    const p = makeProject([makeAct("a1", [makeCard({ id: "c1" })])]);
    const { clips, total } = buildExportClips(flat(p));
    assert.equal(clips.length, 0);
    assert.equal(total, 0);
  });
  test("carries a meaningful crop rect, drops full-frame/tiny ones", () => {
    const p = makeProject([makeAct("a1", [
      makeCard({ id: "c1", resultMid: "m1", crop: { x: 0.1, y: 0.2, w: 0.5, h: 0.6 } }),   // real crop
      makeCard({ id: "c2", resultMid: "m2", crop: { x: 0, y: 0, w: 1, h: 1 } }),           // full frame -> dropped
      makeCard({ id: "c3", resultMid: "m3", crop: { x: 0, y: 0, w: 0.02, h: 0.9 } }),      // too tiny -> dropped
      makeCard({ id: "c4", resultMid: "m4" }),                                              // no crop
    ])]);
    const { clips } = buildExportClips(flat(p));
    assert.deepEqual(clips[0].crop, { x: 0.1, y: 0.2, w: 0.5, h: 0.6 });
    assert.equal(clips[1].crop, undefined);
    assert.equal(clips[2].crop, undefined);
    assert.equal(clips[3].crop, undefined);
  });
});

describe("loraIncompat (D-11, ported from pixai_gallery.py's identical function)", () => {
  test("exact match is compatible", () => {
    assert.equal(loraIncompat("SDXL_MODEL", "SDXL_MODEL"), false);
  });
  test("case-insensitive", () => {
    assert.equal(loraIncompat("sdxl_model", "SDXL_MODEL"), false);
  });
  test("architecture mismatch is incompatible", () => {
    assert.equal(loraIncompat("DIT7B_MODEL", "SDXL_MODEL"), true);
  });
  test("fails OPEN on unknown/empty -- never blocks a submit on missing data", () => {
    assert.equal(loraIncompat("", "SDXL_MODEL"), false);
    assert.equal(loraIncompat("SDXL_MODEL", ""), false);
    assert.equal(loraIncompat(null, null), false);
  });
});

describe("resolveLoraPayload / anyLoraUnresolved (D-11)", () => {
  test("only resolved LoRAs (a real version_id) are ever sent", () => {
    const loras = [
      { model_id: "1", version_id: "v1", weight: 0.7 },
      { model_id: "2", version_id: "", weight: 0.5 },       // still pending
      { model_id: "3", version_id: "", weight: 0.9, failed: true },  // failed lookup
    ];
    assert.deepEqual(resolveLoraPayload(loras), [{ version_id: "v1", weight: 0.7 }]);
  });
  test("empty/absent list is safe", () => {
    assert.deepEqual(resolveLoraPayload([]), []);
    assert.deepEqual(resolveLoraPayload(undefined), []);
  });
  test("anyLoraUnresolved is true while ANY entry lacks a version_id (pending or failed)", () => {
    assert.equal(anyLoraUnresolved([{ version_id: "v1" }]), false);
    assert.equal(anyLoraUnresolved([{ version_id: "v1" }, { version_id: "" }]), true);
    assert.equal(anyLoraUnresolved([{ version_id: "", failed: true }]), true);
    assert.equal(anyLoraUnresolved([]), false);
  });
});

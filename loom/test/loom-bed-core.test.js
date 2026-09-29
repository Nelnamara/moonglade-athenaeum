import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  BED_DB_DEFAULT, BED_DB_MIN, BED_DB_MAX, BED_FADE_IN, BED_FADE_OUT, BED_DUCK_DB, BED_FILE_RE,
  clampBedDb, makeBed, bedOf, bedClock, dbLabel, hasOwnAudio, cutSegments, bedPlan, dbToGain,
  bedDbAt, bedGainAt, bedAutomation, peaksToBuckets, peakAt, cutStatusLine,
} from "../src/loom-bed-core.js";
import { flat, bundleMissingReport } from "../src/loom-core.js";

/* THE MUSIC BED (Session P, P3): the one definition of "own audio", the level and fade rules,
   and the timing math Play (WebAudio) and ⇧ Render (ffmpeg, tests/test_loom_p_routes.py) share.
   The page: −24…0 dB (default −8), 2 s in / 3 s out, −12 dB more under a shot with its own
   audio, a long bed cut to the cut with its out-fade, a short one ending where it ends. */

const SHA = "0123456789abcdef0123456789abcdef01234567";
const card = (id, extra = {}) => ({ id, title: id, status: "done", mode: "I2V", duration: 5, trimIn: 0, trimOut: null,
  resultMid: "7" + id.replace(/\D/g, "").padStart(3, "0"), actualDur: 5, cast: [], refs: [], ...extra });
const board = (cards, extra = {}) => ({ name: "b", assets: [], acts: [{ id: "a1", name: "Act 1", cards }], ...extra });
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, a + " ≈ " + b);

describe("the level and the bed record", () => {
  test("the page's numbers", () => {
    assert.equal(BED_DB_DEFAULT, -8);
    assert.equal(BED_DB_MIN, -24);
    assert.equal(BED_DB_MAX, 0);
    assert.equal(BED_FADE_IN, 2);
    assert.equal(BED_FADE_OUT, 3);
    assert.equal(BED_DUCK_DB, -12);
  });
  test("clampBedDb: −24…0, whole dB, junk -> the default", () => {
    assert.equal(clampBedDb(-30), -24);
    assert.equal(clampBedDb(5), 0);
    assert.equal(clampBedDb(-8.4), -8);
    assert.equal(clampBedDb("-12"), -12);
    assert.equal(clampBedDb("loud"), -8);
    assert.equal(clampBedDb(null), -8);
  });
  test("makeBed: the default level and the fixed fades; a replaced bed keeps its level", () => {
    assert.deepEqual(makeBed({ file: SHA + ".mp3", name: "elune-theme.mp3", dur: 102 }),
      { file: SHA + ".mp3", name: "elune-theme.mp3", dur: 102, db: -8, fadeIn: 2, fadeOut: 3 });
    assert.equal(makeBed({ file: SHA + ".wav", name: "x", dur: null }, -3).db, -3);
    assert.equal(makeBed({ file: SHA + ".wav", name: "x", dur: "nope" }).dur, null);
  });
  test("bedOf: absent on an old board; a bed naming no stored file is no bed", () => {
    assert.equal(bedOf(board([])), null);
    assert.equal(bedOf(board([], { bed: { file: "../../catalog.db", db: -8 } })), null);
    assert.equal(bedOf(board([], { bed: { file: SHA + ".exe" } })), null);
    const b = bedOf(board([], { bed: { file: SHA + ".ogg", name: "n", dur: 10, db: -40, fadeIn: 9, fadeOut: 9 } }));
    assert.deepEqual(b, { file: SHA + ".ogg", name: "n", dur: 10, db: -24, fadeIn: 2, fadeOut: 3 });
  });
  test("the file pattern is the server's own", () => {
    assert.ok(BED_FILE_RE.test(SHA + ".flac"));
    assert.ok(!BED_FILE_RE.test(SHA.toUpperCase() + ".mp3"));
    assert.ok(!BED_FILE_RE.test(SHA + ".mp3/../x"));
  });
  test("labels", () => {
    assert.equal(bedClock(102), "1:42");
    assert.equal(bedClock(null), "");
    assert.equal(dbLabel(-8), "−8 dB");
    assert.equal(dbLabel(0), "0 dB");
  });
  test("reading a board never writes it", () => {
    const p = board([card("c1")], { bed: { file: SHA + ".mp3", name: "x", dur: 3, db: -8, fadeIn: 2, fadeOut: 3 } });
    const before = JSON.stringify(p);
    bedOf(p); cutSegments(flat(p), p); bedPlan(cutSegments(flat(p), p), bedOf(p));
    assert.equal(JSON.stringify(p), before);
  });
});

describe("hasOwnAudio -- the ONE definition the bed ducks under", () => {
  const assets = [{ id: "au1", kind: "audio", tag: "@audio1" }, { id: "im1", kind: "image", tag: "@image1" }];
  const p = { assets };
  test("a take rendered with Generate audio on", () => {
    assert.equal(hasOwnAudio(card("c1", { audioGen: true }), p), true);
    // the ★ take's settings decide, not the card's current toggle
    const t = { id: "t1", n: 1, mid: "7001", settings: { mode: "I2V", audioGen: true } };
    assert.equal(hasOwnAudio(card("c1", { resultMid: "7001", takes: [t], selectedTake: 1, audioGen: false }), p), true);
    const t2 = { id: "t1", n: 1, mid: "7001", settings: { mode: "I2V", audioGen: false } };
    assert.equal(hasOwnAudio(card("c1", { resultMid: "7001", takes: [t2], selectedTake: 1, audioGen: true }), p), false);
  });
  test("V2V carries its source audio", () => {
    assert.equal(hasOwnAudio(card("c1", { mode: "V2V" }), p), true);
  });
  test("R2V with an @audio reference: an audio ref, or an audio cast member", () => {
    assert.equal(hasOwnAudio(card("c1", { mode: "R2V", refs: [{ id: "r", kind: "audio", tag: "@audio2" }] }), p), true);
    assert.equal(hasOwnAudio(card("c1", { mode: "R2V", cast: ["au1"] }), p), true);
    assert.equal(hasOwnAudio(card("c1", { mode: "R2V", cast: ["im1"], refs: [{ kind: "image" }] }), p), false);
  });
  test("an audio reference on anything but R2V does not count; a silent I2V/FLF does not", () => {
    assert.equal(hasOwnAudio(card("c1", { mode: "FLF", cast: ["au1"] }), p), false);
    assert.equal(hasOwnAudio(card("c1", { mode: "I2V" }), p), false);
    assert.equal(hasOwnAudio(null, p), false);
  });
});

describe("the cut and the bed's plan", () => {
  const p = board([
    card("c1"),                                                   // 0-5
    card("c2", { resultMid: "", status: "todo" }),                // unrendered: skipped
    card("c3", { mode: "V2V", trimIn: 1, trimOut: 4 }),          // 5-8, own audio
    card("c4", { actualDur: 6 }),                                // 8-14
  ]);
  const segs = cutSegments(flat(p), p);
  test("rendered shots only, with the local cut's spans", () => {
    assert.deepEqual(segs.map((s) => [s.code, s.start, s.end, s.ownAudio]),
      [["A·01", 0, 5, false], ["A·03", 5, 8, true], ["A·04", 8, 14, false]]);
    assert.equal(cutStatusLine(flat(p), segs), "cut length 14.0 s · 1 unrendered skipped");
    assert.equal(cutStatusLine([], []), "nothing rendered yet");
  });
  test("a bed longer than the cut is cut to the cut; its out-fade ends at the cut's end", () => {
    const plan = bedPlan(segs, { file: SHA + ".mp3", dur: 102, db: -8 });
    assert.equal(plan.cutLen, 14);
    assert.equal(plan.bedLen, 14);
    assert.deepEqual(plan.windows, [{ start: 5, end: 8 }]);
    assert.equal(bedGainAt(plan, 14), 0, "nothing after the cut");
    near(bedGainAt(plan, 12.5), dbToGain(-8) * 0.5, 1e-9);        // half way down the 3 s out-fade
  });
  test("a shorter bed ends where it ends, with its own out-fade, and never loops", () => {
    const plan = bedPlan(segs, { file: SHA + ".mp3", dur: 10, db: -8 });
    assert.equal(plan.bedLen, 10);
    assert.equal(bedGainAt(plan, 10), 0);
    assert.equal(bedGainAt(plan, 13), 0, "no second pass");
    near(bedGainAt(plan, 8.5), dbToGain(-8) * 0.5, 1e-9);
  });
  test("an unknown bed length plays the whole cut", () => {
    assert.equal(bedPlan(segs, { file: SHA + ".mp3", dur: null, db: -8 }).bedLen, 14);
  });
  test("the level, the duck and the fades at chosen times", () => {
    const plan = bedPlan(segs, { file: SHA + ".mp3", dur: 102, db: -6 });
    assert.equal(bedDbAt(plan, 3), -6);
    assert.equal(bedDbAt(plan, 6), -18, "−12 dB more under a shot with its own audio");
    assert.equal(bedDbAt(plan, 8), -6, "back up the moment that shot ends");
    near(bedGainAt(plan, 0), 0);
    near(bedGainAt(plan, 1), dbToGain(-6) * 0.5, 1e-9);           // half way up the 2 s in-fade
    near(bedGainAt(plan, 3), dbToGain(-6), 1e-9);
    assert.equal(bedDbAt(plan, -1), null);
  });
  test("adjacent own-audio shots duck as one window; a duck is clipped to a short bed", () => {
    const q = board([card("c1", { mode: "V2V" }), card("c2", { mode: "V2V" }), card("c3")]);
    const plan = bedPlan(cutSegments(flat(q), q), { file: SHA + ".mp3", dur: 7, db: -8 });
    assert.deepEqual(plan.windows, [{ start: 0, end: 7 }]);
  });
  test("no cut, or no bed: no plan", () => {
    assert.equal(bedPlan([], { file: SHA + ".mp3" }), null);
    assert.equal(bedPlan(segs, null), null);
  });
  test("very short beds scale their fades so they never overlap", () => {
    const plan = bedPlan(segs, { file: SHA + ".mp3", dur: 2, db: -8 });
    assert.equal(plan.fadeIn, 1);
    assert.equal(plan.fadeOut, 1);
  });
});

describe("bedAutomation -- the gain points Play schedules", () => {
  const p = board([card("c1"), card("c2", { mode: "V2V" }), card("c3")]);
  const plan = bedPlan(cutSegments(flat(p), p), { file: SHA + ".mp3", dur: 102, db: -8 });
  test("every point agrees with bedGainAt; duck edges are steps", () => {
    const pts = bedAutomation(plan, 0);
    assert.equal(pts[0].t, 0);
    assert.equal(pts[0].v, 0);
    const at = (t) => pts.filter((x) => Math.abs(x.t - t) < 1e-9);
    // entering the duck at 5 s: the ramp arrives at the undipped level, then steps down
    const five = at(5);
    near(five[0].v, dbToGain(-8), 1e-9);
    assert.ok(five[1].step);
    near(five[1].v, dbToGain(-20), 1e-9);
    // leaving it at 10 s: steps back up
    const ten = at(10);
    near(ten[ten.length - 1].v, dbToGain(-8), 1e-9);
    // the end of the cut is silence
    near(pts[pts.length - 1].v, 0, 1e-12);
    assert.equal(pts[pts.length - 1].t, 15);
    // between points the gain is linear: sample a ramp's midpoint against bedGainAt
    near(bedGainAt(plan, 1), (pts[0].v + at(2)[0].v) / 2, 1e-9);
  });
  test("resuming mid-cut starts from that time's gain", () => {
    const pts = bedAutomation(plan, 6);
    assert.equal(pts[0].t, 6);
    near(pts[0].v, bedGainAt(plan, 6), 1e-12);
    assert.ok(pts.every((x) => x.t >= 6));
  });
  test("past the bed's end: silence", () => {
    assert.deepEqual(bedAutomation(plan, 99), [{ t: 99, v: 0, step: true }]);
    assert.deepEqual(bedAutomation(null, 0), []);
  });
});

describe("the waveform peaks", () => {
  test("peaksToBuckets: max |sample| per bucket, normalised", () => {
    const s = new Float32Array([0, 0.5, -1, 0.25, 0, 0.1, -0.2, 0]);
    assert.deepEqual(peaksToBuckets(s, 4).map((v) => Math.round(v * 100) / 100), [0.5, 1, 0.1, 0.2]);
    assert.deepEqual(peaksToBuckets(new Float32Array(0), 3), [0, 0, 0]);
    assert.deepEqual(peaksToBuckets(new Float32Array([0, 0]), 2), [0, 0]);
  });
  test("peakAt maps a bed second onto the file's peaks", () => {
    const peaks = [0.1, 0.2, 0.3, 0.4];
    assert.equal(peakAt(peaks, 8, 0), 0.1);
    assert.equal(peakAt(peaks, 8, 7.9), 0.4);
    assert.equal(peakAt(peaks, 8, 8), 0, "past the file's end: nothing to draw");
    assert.equal(peakAt([], 8, 1), 0);
  });
});

describe("the full bundle names a bed that did not travel (ruling 8)", () => {
  test("the report says 'music bed', the server's own label for it", () => {
    const p = board([card("c1")], { bed: { file: SHA + ".mp3", name: "x", db: -8 } });
    const r = bundleMissingReport(p, "1", SHA + ".mp3");
    assert.deepEqual(r.rows, [{ mid: SHA + ".mp3", where: ["music bed"] }]);
  });
});

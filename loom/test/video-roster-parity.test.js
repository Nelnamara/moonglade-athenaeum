import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  MODELS, MODEL_VMODES, MODEL_MAXDUR, MODEL_CARD, MODEL_DURATIONS, MODEL_FIELDS, MODEL_REFCAPS,
  DURATIONS, modelMeta, snapDuration, durationAllowed, modelTakes, refCap,
  applyModelGating, applyPrefill, buildPayload,
} from "../../gallery/src/gen/videoDrawerCore.js";
import { NUMERIC_TO_NAME, resolveEngine, videoRemixFromRow } from "../../gallery/src/gen/videoRemixCore.js";

/* The Tsubaki video engines (SCOPE_2026-09-26 lane V, PROBE_2026-09-26 V01-V07).

   ROSTER PARITY. The engine roster lives twice -- moonglade_backup.VIDEO_MODELS (and its per-
   engine tables) on the server, the drawer's MODELS / NUMERIC_TO_NAME / MODEL_VMODES /
   MODEL_MAXDUR / MODEL_DURATIONS / MODEL_FIELDS / MODEL_REFCAPS in the browser -- and a drift is a
   spend-path bug: an engine the drawer offers but the server pairs with another model's id, a
   15 s stop the server snaps to 10, a field the drawer sends that the server drops unannounced.
   The Python side is READ from moonglade_backup.py (no Python runtime here), the JS side is the
   real module. Then the drawer transitions are executed, not grepped. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const py = src("moonglade_backup.py");

// VIDEO_MODELS = { "name": {"model_id": "123", "label": "..."}, ... }
function pyVideoModels() {
  const block = py.slice(py.indexOf("VIDEO_MODELS = {"), py.indexOf("\n}\n", py.indexOf("VIDEO_MODELS = {")));
  const out = {};
  for (const m of block.matchAll(/"([\w.]+)":\s*\{"model_id":\s*"(\d*)",\s*"label":\s*"([^"]*)"\}/g)) {
    out[m[1]] = { model_id: m[2], label: m[3] };
  }
  return out;
}
function pyTuple(name) {
  const m = py.match(new RegExp("^" + name + " = \\(([^)]*)\\)", "m"));
  assert.ok(m, "expected a " + name + " tuple in moonglade_backup.py");
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}
const TBKV = pyTuple("TSUBAKI_VIDEO_MODELS");
const REF = (id) => ({ media_id: id, thumb: "/thumbs/" + id + ".jpg" });

function state(init) {
  return Object.assign({
    mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 5, camera: "unset", quality: "professional", channel: "normal",
    audioGen: false, audioLanguage: "english", videoHelper: false, negative: "", modeNote: "",
  }, init);
}

describe("roster parity: the server's VIDEO_MODELS and the drawer's tables are one roster", () => {
  const vm = pyVideoModels();

  test("the parse found the whole server roster, both Tsubaki engines included", () => {
    assert.deepEqual(TBKV, ["tbkv1.0", "tbkv1.0.1"]);
    assert.equal(vm["tbkv1.0.1"].model_id, "2054378086834851904");
    assert.equal(vm["tbkv1.0"].model_id, "2042030623542642408");
    assert.equal(Object.keys(vm).length, 9);
  });
  test("MODELS offers exactly the server's engines, labelled with the same titles for tbkv", () => {
    assert.deepEqual(new Set(MODELS.map((m) => m.value)), new Set(Object.keys(vm)));
    for (const t of TBKV) assert.equal(MODELS.find((m) => m.value === t).label, vm[t].label);
  });
  test("the grid follows the site's picker order: the Tsubaki pair right after the V4.0 pair", () => {
    assert.deepEqual(MODELS.slice(0, 4).map((m) => m.value), ["v4.0", "v4.0.1", "tbkv1.0.1", "tbkv1.0"]);
  });
  test("NUMERIC_TO_NAME is exactly the engines that publish an id", () => {
    const want = {};
    for (const [name, m] of Object.entries(vm)) if (m.model_id) want[m.model_id] = name;
    assert.deepEqual(NUMERIC_TO_NAME, want);
  });
  test("MODEL_VMODES covers every engine; the Tsubaki pair takes all three (owner ruling 2)", () => {
    assert.deepEqual(new Set(Object.keys(MODEL_VMODES)), new Set(Object.keys(vm)));
    for (const t of TBKV) assert.deepEqual(MODEL_VMODES[t], ["i2v", "flf", "r2v"]);
  });
  test("the 15 s engines agree with VIDEO_15S_MODELS", () => {
    const js = Object.keys(MODEL_MAXDUR).filter((k) => MODEL_MAXDUR[k] === 15);
    assert.deepEqual(new Set(js), new Set(pyTuple("VIDEO_15S_MODELS")));
  });
  test("per-engine durations, fields and reference caps mirror the server's tables", () => {
    assert.match(py, /^VIDEO_MODEL_DURATIONS = \{m: \(5, 10, 15\) for m in TSUBAKI_VIDEO_MODELS\}/m);
    assert.deepEqual(Object.keys(MODEL_DURATIONS).sort(), [...TBKV].sort());
    for (const t of TBKV) assert.deepEqual(MODEL_DURATIONS[t], [5, 10, 15]);
    assert.match(py, /^VIDEO_NO_NEGATIVE_MODELS = TSUBAKI_VIDEO_MODELS$/m);
    assert.match(py, /^VIDEO_NO_CAMERA_MODELS = TSUBAKI_VIDEO_MODELS$/m);
    assert.deepEqual(Object.keys(MODEL_FIELDS).sort(), [...TBKV].sort());
    assert.match(py, /^VIDEO_REF_CAPS = \{m: \{"images": 6, "videos": 0, "audios": 3\} for m in TSUBAKI_VIDEO_MODELS\}/m);
    for (const t of TBKV) assert.deepEqual(MODEL_REFCAPS[t], { images: 6, videos: 0, audios: 3 });
    // the existing engines keep the shared four (the 6 s stop is not changed by this branch)
    assert.deepEqual(DURATIONS, [5, 6, 10, 15]);
    assert.match(py, /^VIDEO_DURATIONS = \(5, 6, 10, 15\)/m);
  });
  test("the default engine is still v4.0.1 on both sides", () => {
    assert.match(py, /^DEFAULT_VIDEO_MODEL = "v4\.0\.1"$/m);
  });
});

describe("tbkv in the drawer: what it shows and what it sends", () => {
  test("no card claim for tbkv: the meta line defers to the badge", () => {
    for (const t of TBKV) {
      assert.equal(MODEL_CARD[t], null);
      assert.equal(modelMeta(t), "15s max · card coverage checked at price time");
    }
    assert.equal(modelMeta("v4.0.1"), "15s max · V4.0 cards apply");     // unchanged
    assert.equal(modelMeta("v2.7"), "10s max · never card-covered");      // unchanged
  });
  test("6 s is not a tbkv stop; 15 s is; the existing engines keep 6", () => {
    assert.equal(durationAllowed("tbkv1.0.1", 6), false);
    assert.equal(durationAllowed("tbkv1.0.1", 15), true);
    assert.equal(durationAllowed("v4.0.1", 6), true);
    assert.equal(durationAllowed("v3.2", 15), false);
    assert.equal(snapDuration(6, "tbkv1.0"), 5);
    assert.equal(snapDuration(6), 6);
  });
  test("picking tbkv at 6 s snaps the priced duration to 5; v4.0.1 at 6 s is untouched", () => {
    const s = state({ duration: 6 });
    applyModelGating(s, true);
    assert.equal(s.duration, 6);
    s.model = "tbkv1.0.1";
    applyModelGating(s, true);
    assert.equal(s.duration, 5);
    assert.equal(buildPayload(s, "").duration, 5);
  });
  test("a remixed tbkv clip keeps its 15 s (it used to be cut to 10)", () => {
    const s = state();
    applyPrefill(s, { mode: "r2v", video_model: "tbkv1.0", duration: 15, images: [REF("1")] });
    assert.equal(s.duration, 15);
  });
  test("video refs are HELD on tbkv: kept in the bank, left out of the payload, named once", () => {
    const s = state({ mode: "r2v", imgSlots: [REF("1")], vidSlots: [REF("V1")] });
    assert.deepEqual(buildPayload(s, "").video_refs, ["V1"]);
    s.model = "tbkv1.0.1";
    applyModelGating(s, true);
    assert.equal(s.vidSlots.length, 1, "nothing was deleted");
    assert.deepEqual(buildPayload(s, "").video_refs, []);
    assert.equal(s.modeNote, "Tsubaki Video takes no video references. Still held: 1 video ref. Nothing was deleted.");
    s.model = "v4.0.1";                         // back to an engine that takes them
    applyModelGating(s, true);
    assert.deepEqual(buildPayload(s, "").video_refs, ["V1"]);
    assert.equal(s.modeNote, "", "the previous engine's sentence does not stay standing");
  });
  // Changed on purpose (review V-R5; SCOPE_2026-09-26 V1 "names them in the mode note"): this
  // used to pin SILENCE on a prefill, so a Loom shot or handoff carrying video refs into a
  // drawer already on Tsubaki quoted and submitted a job without them, with only a dimmed slot
  // to say so. The note is about the CURRENT banks, so it is not a stale-sentence risk.
  test("a host re-sync (prefill) holds them AND names them", () => {
    const s = state();
    applyPrefill(s, { mode: "r2v", video_model: "tbkv1.0", images: [REF("1")], video_refs: [REF("V1"), REF("V2")] });
    assert.equal(s.vidSlots.length, 2);
    assert.deepEqual(buildPayload(s, "").video_refs, []);
    assert.equal(s.modeNote, "Tsubaki Video Flash takes no video references. Still held: 2 video refs. Nothing was deleted.");
  });
  test("a prefill onto an engine that takes video refs says nothing about them", () => {
    const s = state({ model: "tbkv1.0", modeNote: "Tsubaki Video Flash takes no video references. Still held: 1 video ref. Nothing was deleted." });
    applyPrefill(s, { mode: "r2v", video_model: "v4.0.1", images: [REF("1")], video_refs: [REF("V1")] });
    assert.deepEqual(buildPayload(s, "").video_refs, ["V1"]);
    assert.equal(s.modeNote, "");
  });
  test("refCap: the drawer's own banks elsewhere, the tbkv panel's caps on tbkv", () => {
    assert.equal(refCap("v4.0.1", "videos"), 3);
    assert.equal(refCap("tbkv1.0.1", "videos"), 0);
    assert.equal(refCap("tbkv1.0.1", "images"), 6);
  });
  test("negative and camera: kept in the form, never sent on tbkv; sent as before elsewhere", () => {
    const s = state({ model: "tbkv1.0.1", negative: "blurry", camera: "zoom", slots: [REF("1")] });
    const p = buildPayload(s, "x");
    assert.equal(p.negative, "");
    assert.equal(p.camera_movement, "unset");
    assert.equal(s.negative, "blurry", "the typed text stays in the box");
    assert.equal(s.camera, "zoom");
    assert.equal(modelTakes("tbkv1.0", "negative"), false);
    const v = buildPayload(state({ negative: "blurry", camera: "zoom", slots: [REF("1")] }), "x");
    assert.equal(v.negative, "blurry");
    assert.equal(v.camera_movement, "zoom");
  });
});

describe("Remix of a Tsubaki clip", () => {
  const tp = (init) => Object.assign({
    kind: "r2v", video_model: "tbkv1.0.1", duration: 15, quality: "professional", camera: "",
    audio: true, audio_language: "english", prompt_helper: false, negative: "", prompt: "p",
    is_private: true, start: null, end: null, image_refs: [{ media_id: "1", in_lib: true }],
    video_refs: [], audio_refs: [], ratio: "",
  }, init);
  const row = (init) => Object.assign({ video_model: "", model_id: "", video_duration: "" }, init);

  test("both numeric ids resolve to their engines (catalog rows now store the number)", () => {
    assert.equal(resolveEngine("2054378086834851904"), "tbkv1.0.1");
    assert.equal(resolveEngine("2042030623542642408"), "tbkv1.0");
    const { prefill, notes } = videoRemixFromRow(row({ model_id: "2042030623542642408" }), null);
    assert.equal(prefill.video_model, "tbkv1.0");
    assert.ok(!notes.includes("engine no longer in the roster"));
  });
  test("a set ratio is named, not carried; adaptive or none says nothing", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({ ratio: "3:2" }));
    assert.ok(notes.includes("aspect ratio 3:2 not carried — PixAI will infer it"));
    assert.equal(prefill.ratio, undefined, "the ratio never rides the prefill");
    assert.deepEqual(videoRemixFromRow(row({}), tp({ ratio: "adaptive" })).notes, []);
    assert.deepEqual(videoRemixFromRow(row({}), tp({})).notes, []);
  });
  test("a recovered negative or camera on tbkv is disclosed; the same recipe on v4.0.1 is not", () => {
    const i2v = { kind: "i2v", negative: "blurry", camera: "zoom", start: { media_id: "1", in_lib: true } };
    const { notes } = videoRemixFromRow(row({}), tp(Object.assign({ video_model: "tbkv1.0" }, i2v)));
    assert.ok(notes.includes("negative prompt / camera not used by this engine"));
    const v4 = videoRemixFromRow(row({}), tp(Object.assign({ video_model: "v4.0.1" }, i2v)));
    assert.ok(!v4.notes.includes("negative prompt / camera not used by this engine"));
  });
  test("a 15 s tbkv remix is not 'lowered to the engine's max'", () => {
    const { notes } = videoRemixFromRow(row({}), tp({ duration: 15 }));
    assert.ok(!notes.includes("duration lowered to the engine's max"));
  });
});

describe("VideoDrawer source guards (no React harness in this suite)", () => {
  const vdraw = src("gallery/src/components/VideoDrawer.jsx");
  test("a duration stop is live only when the engine takes it", () => {
    assert.match(vdraw, /const ok = durationAllowed\(s\.model, d\);/);
  });
  test("the negative box and the CAMERA select read disabled from the per-model table", () => {
    assert.match(vdraw, /const negOn = modelTakes\(s\.model, "negative"\);/);
    assert.match(vdraw, /disabled=\{!negOn\}/);
    assert.match(vdraw, /className="mgd-sel mgd-cam"[^\n]*disabled=\{!modelTakes\(s\.model, "camera"\)\}/);
  });
  test("the video bank's cap is the engine's, and at 0 the '+ video' slot reads 'not on this engine'", () => {
    assert.match(vdraw, /const vCap = refCap\(s\.model, "videos"\);/);
    assert.match(vdraw, /caption: "\+ video", title: "not on this engine", off: true/);
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  MODELS, DEFAULT_MODEL, VIDEO_MODEL_RETIRED, modelRetired, pickerModels, retiredNote,
  applyPrefill, applyModelGating, setVideoClock,
} from "../../gallery/src/gen/videoDrawerCore.js";
import { videoRemixFromRow } from "../../gallery/src/gen/videoRemixCore.js";
import { engineOf, engineLabel } from "../src/loom-core.js";
import { doneNotice, addsToGallery } from "../../gallery/src/notify/doneNotice.js";

/* V3.2 retires on 2026-11-23 03:00 UTC (PixAI, 10 Nov). Every check names its instant. */
const CUT = Date.parse("2026-11-23T03:00:00Z");
const BEFORE = CUT - 1000;

describe("V3.2 retirement (front end)", () => {
  test("the date is the announced instant", () => {
    assert.equal(VIDEO_MODEL_RETIRED["v3.2"], "2026-11-23T03:00:00Z");
  });
  test("before the cut: picker, prefill and remix are unchanged", () => {
    assert.equal(modelRetired("v3.2", BEFORE), false);
    assert.ok(pickerModels(BEFORE).some((m) => m.value === "v3.2"));
    const s = { mode: "i2v", duration: 5, model: DEFAULT_MODEL, slots: [], vidSlots: [], audSlot: null };
    setVideoClock(() => BEFORE);
    try { applyPrefill(s, { video_model: "v3.2", now: BEFORE }); } finally { setVideoClock(null); }
    assert.equal(s.model, "v3.2");
    const r = videoRemixFromRow({ video_model: "v3.2" }, null, BEFORE);
    assert.equal(r.prefill.video_model, "v3.2");
    assert.ok(!r.notes.some((n) => /retired/.test(n)));
  });
  test("after the cut: not offered, label map keeps V3.2", () => {
    assert.equal(modelRetired("v3.2", CUT), true);
    assert.ok(!pickerModels(CUT).some((m) => m.value === "v3.2"));
    assert.equal(pickerModels(CUT).length, MODELS.length - 1);
    assert.equal(MODELS.find((m) => m.value === "v3.2").label, "V3.2");   // old videos keep it
    assert.equal(modelRetired("v4.0.1", CUT + 1e12), false);
  });
  test("a prefill naming it falls to the default with the plain note", () => {
    const s = { mode: "i2v", duration: 5, model: "v4.0", slots: [], vidSlots: [], audSlot: null };
    setVideoClock(() => CUT);
    try { applyPrefill(s, { video_model: "v3.2", now: CUT }); } finally { setVideoClock(null); }
    assert.equal(s.model, DEFAULT_MODEL);
    assert.equal(s.modeNote, "V3.2 was retired by PixAI on 23 Nov; using V4.0 Lite Preview instead.");
    assert.equal(retiredNote("v3.2"), s.modeNote);
  });
  test("a remix of a V3.2 clip lands on the default with a note", () => {
    const row = { video_model: "v3.2", video_duration: 5 };
    for (const tp of [null, { kind: "i2v", video_model: "v3.2", duration: 5 }]) {
      const r = videoRemixFromRow(row, tp, CUT);
      assert.equal(r.prefill.video_model, DEFAULT_MODEL);
      assert.ok(r.notes.includes(retiredNote("v3.2")));
    }
  });
  test("the numeric modelId of V3.2 resolves then retires the same way", () => {
    const r = videoRemixFromRow({ model_id: "1961182207978260675" }, null, CUT);
    assert.equal(r.prefill.video_model, DEFAULT_MODEL);
  });
  test("gating never leaves a retired engine in a payload", () => {
    const s = { mode: "i2v", duration: 5, model: "v3.2", slots: [], vidSlots: [], audSlot: null };
    applyModelGating(s, false, CUT);
    assert.equal(s.model, DEFAULT_MODEL);
  });
  test("a Loom shot on it reads as the default engine once retired", () => {
    try {
      setVideoClock(() => BEFORE);
      assert.equal(engineOf({ videoModel: "v3.2" }), "v3.2");
      setVideoClock(() => CUT);
      assert.equal(engineOf({ videoModel: "v3.2" }), DEFAULT_MODEL);
      assert.equal(engineLabel("v3.2"), "V4.0 Lite Preview");
    } finally { setVideoClock(null); }
  });
});

describe("done notice wording", () => {
  test("art-adding jobs say Added to your gallery", () => {
    for (const j of [
      { type: "generate", label: "Generated" }, { type: "import", label: "Import task 1" },
      { type: "panel", action: "sync" }, { type: "panel", action: "resync-full" },
      { type: "panel", action: "test-pull" }, { type: "panel", action: "sync-videos" },
    ]) assert.equal(doneNotice(j).msg, "Added to your gallery.", JSON.stringify(j));
  });
  test("Control Panel maintenance jobs say only done", () => {
    for (const action of ["audit", "stats", "organize-dry", "dedup-dry", "inventory", "verify-library",
      "sync-similar", "backfill-phash", "audit-full"]) {
      const d = doneNotice({ type: "panel", action, label: "Duplicate audit (read-only)" });
      assert.equal(d.title, "Duplicate audit (read-only) — done");
      assert.equal(d.msg, "");
      assert.equal(addsToGallery({ type: "panel", action }), false);
    }
  });
  test("delete keeps its own wording; unknown types add nothing", () => {
    assert.deepEqual(doneNotice({ type: "delete", label: "Deleted 2" }), { title: "Deleted 2", msg: "Gone from PixAI." });
    assert.equal(doneNotice({ type: "cli", label: "x" }).msg, "");
    assert.equal(doneNotice({}).title, "Generation — done");
  });
});

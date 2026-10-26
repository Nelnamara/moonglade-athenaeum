import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  MODELS, DURATIONS, gatedShot, applyModelGating, applyPrefill, buildPayload,
} from "../../gallery/src/gen/videoDrawerCore.js";

/* ISSUE #90 -- the drawer half of "the Loom's shot keeps its engine" (SPEC_final C, D).

   1. gatedShot(mode, duration, model) is the ONE rule for where a shot lands on an engine: the
      Loom computes a card's mode/duration from it, and the drawer's applyModelGating applies it.
      If the two ever disagree, the card prices one job and the drawer shows (and Go sends)
      another -- so the parity matrix below runs every engine x mode x duration through both.
   2. C4, the cross-shot frames leak: a Multi-Reference prefill whose engine has no Multi-
      Reference (V3.2, V2.7) is gated to First & Last / First Frame, and the Start/End Frame bank
      still held the PREVIOUS shot's frames -- which buildPayload then sent. Measured on this
      module before the fix; pinned here on the real transition.
   3. same_shot: the one echo prefill that follows a commit from the drawer keeps the ratio and
      the mode note the owner just caused; a different shot resets both, as before. */

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", videoHelper: false,
    ratio: "adaptive", negative: "", modeNote: "",
  }, init);
}

// The object master-storyboard.jsx's prefill effect builds for a shot: mode, and the banks
// ALWAYS stated, even when empty.
function shot(mode, images, extra) {
  return Object.assign({
    mode, duration: 5, audio: false, audio_language: "english", quality: "professional",
    images: images || [], video_refs: [], audio_ref: null,
  }, extra);
}

const MODES = ["i2v", "flf", "r2v"];
// DURATIONS is the matrix the spec names; the off-set lengths ride along so the snap half of
// the rule is compared too (a hand-typed 8, a 12 from an older board, an over-cap 20).
const LENGTHS = [...DURATIONS, 3, 8, 12, 20];

describe("gatedShot is the drawer's own gating rule, as a pure function", () => {
  test("parity: every engine x mode x duration lands where applyModelGating leaves the drawer", () => {
    let n = 0;
    for (const { value: model } of MODELS) {
      for (const mode of MODES) {
        for (const duration of LENGTHS) {
          for (const userDriven of [false, true]) {
            const s = drawer({ mode, duration, model, imgSlots: [ref(1)], slots: [ref(2), ref(3)] });
            applyModelGating(s, userDriven);
            assert.deepEqual(gatedShot(mode, duration, model), { mode: s.mode, duration: s.duration },
              model + " / " + mode + " / " + duration + "s (userDriven " + userDriven + ")");
            n++;
          }
        }
      }
    }
    assert.equal(n, MODELS.length * MODES.length * LENGTHS.length * 2);
    assert.equal(MODELS.length, 9, "the roster the spec's matrix names");
  });

  test("the rule's own answers: last supported mode, the cap, the engine's own set", () => {
    assert.deepEqual(gatedShot("r2v", 15, "v3.2"), { mode: "flf", duration: 10 }, "V3.2 from Multi-Reference: First & Last, 10 s cap");
    assert.deepEqual(gatedShot("flf", 15, "v2.7"), { mode: "i2v", duration: 10 });
    assert.deepEqual(gatedShot("r2v", 6, "tbkv1.0.1"), { mode: "r2v", duration: 5 }, "no 6 s stop on Tsubaki");
    assert.deepEqual(gatedShot("i2v", 15, "v4.0"), { mode: "i2v", duration: 15 }, "nothing to move");
  });

  test("a raw card mode reads the same as its drawer mode (drawerModeFor, then the gate)", () => {
    // master-storyboard.jsx's drawerModeFor, as it ships: FLF / I2V by name, everything else r2v.
    const drawerModeFor = (m) => { const u = (m || "R2V").toUpperCase(); return u === "FLF" ? "flf" : u === "I2V" ? "i2v" : "r2v"; };
    for (const { value: model } of MODELS) {
      for (const raw of ["I2V", "FLF", "R2V", "V2V", "i2v", "flf", "r2v", "", undefined, null]) {
        assert.deepEqual(gatedShot(raw, 10, model), gatedShot(drawerModeFor(raw), 10, model),
          model + " / " + JSON.stringify(raw));
      }
    }
  });

  test("applyModelGating calls gatedShot -- no second copy of the rule", () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(path.join(here, "../../gallery/src/gen/videoDrawerCore.js"), "utf8").replace(/\r\n/g, "\n");
    const start = src.indexOf("export function applyModelGating(");
    const body = src.slice(start, src.indexOf("\n}\n", start));
    assert.match(body, /gatedShot\(s\.mode, s\.duration, s\.model\)/, "applyModelGating must take its mode and duration from gatedShot");
    for (const copy of ["MODEL_VMODES[", "MODEL_MAXDUR[", "snapDuration(", "durationAllowed("]) {
      assert.ok(!body.includes(copy), "applyModelGating re-derives the rule itself again (" + copy + ")");
    }
  });
});

describe("a Multi-Reference prefill gated off Multi-Reference sends none of the previous shot's frames (C4)", () => {
  for (const engine of ["v3.2", "v2.7"]) {
    for (const firstEngine of ["v4.0.1", engine]) {
      test("FLF 111/222 on " + firstEngine + ", then R2V 999 on " + engine, () => {
        const d = drawer();
        applyPrefill(d, shot("flf", [ref(111), ref(222)], { video_model: firstEngine }));
        assert.deepEqual(buildPayload(d, "").images, firstEngine === "v2.7" ? ["111"] : ["111", "222"], "the first shot is set up");
        applyPrefill(d, shot("r2v", [ref(999)], { video_model: engine }));
        const p = buildPayload(d, "");
        assert.equal(d.mode, engine === "v3.2" ? "flf" : "i2v", "gated off Multi-Reference");
        for (const leaked of ["111", "222"]) {
          assert.ok(!p.images.includes(leaked), "the previous shot's frame " + leaked + " is in this shot's paid payload: " + JSON.stringify(p.images));
        }
        assert.ok(!p.images.includes("999"), "M27: a Multi-Reference pick is never carried into a frame");
        assert.deepEqual(p.images, [], "nothing to price: the drawer asks for a frame");
      });
    }
  }

  test("an i2v prefill that more than one picture forces into Multi-Reference is covered too", () => {
    const d = drawer();
    applyPrefill(d, shot("flf", [ref(111), ref(222)], { video_model: "v3.2" }));
    applyPrefill(d, shot("i2v", [ref(901), ref(902)], { video_model: "v3.2" }));
    assert.deepEqual(buildPayload(d, "").images, []);
  });

  test("a prefill with no picture list leaves the frames alone (only keys present apply)", () => {
    const d = drawer();
    applyPrefill(d, shot("flf", [ref(111), ref(222)], { video_model: "v3.2" }));
    applyPrefill(d, { duration: 10 });
    assert.deepEqual(buildPayload(d, "").images, ["111", "222"]);
  });

  test("on an engine that has Multi-Reference the shot's own references still go out", () => {
    const d = drawer();
    applyPrefill(d, shot("flf", [ref(111), ref(222)]));
    applyPrefill(d, shot("r2v", [ref(999)], { video_model: "tbkv1.0.1" }));
    assert.equal(d.mode, "r2v");
    assert.deepEqual(buildPayload(d, "").images, ["999"]);
  });
});

describe("same_shot: the echo of a commit keeps the ratio and the mode note; another shot resets them", () => {
  // The owner on a Multi-Reference Tsubaki shot with a 16:9 ratio picks V3.2: the drawer switches
  // to First & Last and says so. The host writes the card and echoes ONE prefill of that shot.
  function pickedV32() {
    const d = drawer({ mode: "r2v", model: "tbkv1.0.1", ratio: "16:9", imgSlots: [ref(1), ref(2)] });
    d.model = "v3.2";
    applyModelGating(d, true);
    assert.match(d.modeNote, /^V3\.2 has no Multi-Reference, so the shot mode switched to First & Last\./);
    return d;
  }

  test("the same shot keeps both", () => {
    const d = pickedV32();
    const note = d.modeNote;
    applyPrefill(d, shot("flf", [ref(7)], { video_model: "v3.2", same_shot: true }));
    assert.equal(d.modeNote, note, "the sentence vanished the instant it appeared");
    assert.equal(d.ratio, "16:9");
    assert.equal(d.mode, "flf");
    assert.deepEqual(buildPayload(d, "").images, ["7"], "the echo still applies the shot's own frames");
  });

  test("a different shot resets both, as before", () => {
    for (const same_shot of [undefined, false]) {
      const d = pickedV32();
      applyPrefill(d, shot("flf", [ref(7)], { video_model: "v3.2", same_shot }));
      assert.equal(d.modeNote, "", "a sentence about the previous shot sits over this one");
      assert.equal(d.ratio, "adaptive", "the previous shot's ratio rode into this one (N7)");
    }
  });

  test("a ratio the prefill names wins on the same shot too", () => {
    const d = pickedV32();
    applyPrefill(d, shot("flf", [ref(7)], { video_model: "v3.2", same_shot: true, ratio: "9:16" }));
    assert.equal(d.ratio, "9:16");
  });

  test("the no-video-refs note is never kept: the gate re-derives it from the banks the echo leaves", () => {
    const d = drawer({ mode: "r2v", model: "tbkv1.0.1", imgSlots: [ref(1)], vidSlots: [ref(50)] });
    applyModelGating(d, false);
    assert.match(d.modeNote, /takes no video references/);
    applyPrefill(d, shot("r2v", [ref(1)], { video_model: "tbkv1.0.1", same_shot: true, video_refs: [ref(50)] }));
    assert.match(d.modeNote, /takes no video references\. Still held: 1 video ref\./, "still true, so still said");
    applyPrefill(d, shot("r2v", [ref(1)], { video_model: "tbkv1.0.1", same_shot: true, video_refs: [] }));
    assert.equal(d.modeNote, "", "the bank holds no video ref any more, and the note said it did");
  });
});

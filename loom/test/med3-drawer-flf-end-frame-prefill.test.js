import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  applyPrefill, applySetRefs, buildPayload,
} from "../../gallery/src/gen/videoDrawerCore.js";

// FLF END-FRAME DELIVERY (2026-07-27, closing-frame pass).
//
// The Loom's prefill effect builds an flf shot's image list as [openFrame, closeFrame] and states
// mode:'flf' in the same prefill() call -- but prefill() routed EVERY images array through
// setRefs(), whose multi-image branch exists for the gallery's bulk "Send to Video" and therefore
// force-switches to r2v (`refs.length > 1 -> r2v`) and writes the r2v bank. Net effect on a First
// & Last shot with both frames attached:
//
//   prefill -> mode 'flf'                (the host's stated mode)
//   prefill -> setRefs([open, close])    -> r2v, imgSlots = [open, close]
//
// The drawer silently left the mode the host just stated, and the End Frame never landed in the
// End Frame box (slots[1]) -- not on first prefill, not on any re-prefill. No host-side fix exists:
// prefill()/setRefs() are the drawer's whole public surface and neither could write slots[1]
// (setRefs must not -- a one-image gallery send wiping a hand-picked End Frame is data loss). So
// applyPrefill now maps a host-stated flf image list of <= 2 onto the two frame slots POSITIONALLY
// (images[0] -> Start, images[1] -> End), with no mode switch and no event.
//
// Since the no-vanilla port (2026-08-08) the transition logic is the PURE state layer in
// gallery/src/gen/videoDrawerCore.js, exercised here directly -- see med-mg-generate-drawer-mode-
// carry.test.js's header. The single-image / empty-list / omitted-key behaviors this must NOT
// disturb are pinned by med2-mg-generate-drawer-prefill-leak.test.js; the guards below re-state
// the two closest from this angle.

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 10, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}

// The exact object master-storyboard.jsx's prefill effect builds for an flf shot.
function shot(mode, images) {
  return {
    mode, duration: 10, audio: false, audio_language: "english", quality: "professional",
    images: images || [], video_refs: [], audio_ref: null,
  };
}

describe("a host-stated flf prefill lands its End Frame -- and stays flf", () => {
  test("both frames attached: images[0] -> Start, images[1] -> End, on FIRST prefill", () => {
    const d = drawer({});
    applyPrefill(d, shot("flf", [ref("B_open"), ref("B_close")]));
    assert.equal(d.mode, "flf",
      "setRefs' bulk-send branch bounced the drawer into Multi-Reference against the mode the " +
      "host stated two lines earlier in the same call");
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["B_open", "B_close"],
      "the End Frame must be IN the End Frame box (slots[1]) with no tab toggle");
    const p = buildPayload(d, "");
    assert.equal(p.mode, "FLF");
    assert.deepEqual(p.images, ["B_open", "B_close"]);
  });

  test("re-prefilling after a frame replace updates the slots in place", () => {
    const d = drawer({});
    applyPrefill(d, shot("flf", [ref("open_v1"), ref("close")]));
    applyPrefill(d, shot("flf", [ref("open_v2"), ref("close")]));
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["open_v2", "close"]);
    assert.equal(d.mode, "flf");
  });

  // Guards: the behaviors this branch must NOT disturb (med2-mg-generate-drawer-prefill-leak.test.js
  // owns the fuller versions).
  test("one image still means Start only, End explicitly emptied", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applyPrefill(d, shot("flf", [ref("B_open")]));
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["B_open", null]);
  });

  test("an empty images array still clears both frames", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applyPrefill(d, shot("flf", []));
    assert.deepEqual(d.slots.map((s) => s && s.media_id), [null, null]);
  });

  test("an r2v prefill still routes multiple images to the r2v bank", () => {
    const d = drawer({});
    applyPrefill(d, shot("r2v", [ref("R1"), ref("R2"), ref("R3")]));
    assert.equal(d.mode, "r2v");
    assert.deepEqual(d.imgSlots.map((s) => s && s.media_id), ["R1", "R2", "R3"]);
  });

  test("the gallery's DIRECT setRefs bulk-send still promotes to r2v even from flf", () => {
    // setRefs without a surrounding prefill has no host-stated mode to honor -- a multi-image
    // gallery send really does mean Multi-Reference, exactly as before.
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applySetRefs(d, [ref("S1"), ref("S2"), ref("S3")]);
    assert.equal(d.mode, "r2v");
    assert.deepEqual(d.imgSlots.map((s) => s && s.media_id), ["S1", "S2", "S3"]);
  });
});

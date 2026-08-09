import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  applyMode, applySetRefs, applyPrefill, buildPayload, hasAnyRef,
} from "../../gallery/src/gen/videoDrawerCore.js";

// M27, repair round -- ANOTHER SHOT'S MEDIA IN A PAID PAYLOAD.
//
// The first M27 repair (2026-07-27, reverted the same day) hung a "carry the outgoing Multi-
// Reference picks into the Start Frame" step off the mode switch. A mode switch is not a user
// gesture: prefill() runs it too, and runs it FIRST, before setRefs has written the incoming
// shot's images. The Loom drives that path on every shot click.
//
//   Loom is on r2v shot A, imgSlots = [A1, A2, A3].
//   User clicks flf shot B whose close frame is not picked yet, so the Loom's payload carries
//   images: [B_open] -- one element, a normal intermediate state (master-storyboard builds it as
//   [openFrame, closeFrame].filter(...)).
//   prefill -> mode 'flf' -> carry fills room=2 -> slots = [A1, A2].
//   prefill -> setRefs([B_open]) -> one ref, mode !== 'r2v' -> writes slots[0] ONLY.
//   slots = [B_open, A2].  payload().images = ["B_open", "A2"].
//
// A2 belongs to shot A. The cost badge prices it and Generate spends credits on it. Two separate
// defects have to stay closed for that to be impossible, and this file pins both:
//   1. a host-driven re-sync must not act like a user mode change (nothing carried, nothing
//      narrated) -- applyMode's `userDriven` flag;
//   2. an explicit images array is the COMPLETE list for its shot, so prefill has to empty the flf
//      End Frame setRefs does not write. That second one is older than the repair: flf shot C
//      [C1, C2] followed by flf shot B images:[B_open] already gave ["B_open", "C2"] -- same
//      money, different route in.
//
// Since the no-vanilla port (2026-08-08) the transition logic is the PURE state layer in
// gallery/src/gen/videoDrawerCore.js, exercised here directly against a plain state object -- see
// med-mg-generate-drawer-mode-carry.test.js's header for the full rationale.

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 10, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}

// The exact object master-storyboard.jsx builds for a shot (see its prefill effect): mode, and
// images/video_refs/audio_ref ALWAYS stated, even when empty.
function shot(mode, images, video_refs, audio_ref) {
  return {
    mode, duration: 10, audio: false, audio_language: "english", quality: "professional",
    images: images || [], video_refs: video_refs || [], audio_ref: audio_ref || null,
  };
}

describe("a host prefill never lets one shot's media into another shot's payload (M27)", () => {
  test("r2v shot A -> flf shot B with only its open frame picked", () => {
    const d = drawer({ mode: "r2v", imgSlots: [ref("A1"), ref("A2"), ref("A3")] });
    applyPrefill(d, shot("flf", [ref("B_open")]));
    assert.deepEqual(buildPayload(d, "").images, ["B_open"],
      "shot A's reference reached shot B's payload -- Generate would spend on it");
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["B_open", null]);
  });

  test("r2v shot A -> i2v shot B with no refs at all leaves nothing behind, and says nothing", () => {
    const d = drawer({
      mode: "r2v",
      imgSlots: [ref("A1")],
      vidSlots: [ref("AV1")],
      audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    applyPrefill(d, shot("i2v", [], [], null));
    assert.deepEqual(buildPayload(d, "").images, []);
    assert.equal(hasAnyRef(buildPayload(d, "")), false, "an empty shot arrived priced");
    // The notice was false in every clause on this route: nothing was carried (setRefs nulled it)
    // and the video/audio refs were not held (prefill wiped them) -- and it must not sit on screen
    // over the next shot's slots.
    assert.equal(d.modeNote, "",
      "the drawer told the user about the PREVIOUS shot's references: " + JSON.stringify(d.modeNote));
  });

  test("a notice raised against the previous shot is cleared even when the mode does not change", () => {
    const d = drawer({ mode: "r2v", imgSlots: [ref("A1"), ref("A2")] });
    applyMode(d, "i2v", true);                       // user gesture: notice is legitimate here
    assert.notEqual(d.modeNote, "");
    applyPrefill(d, { images: [ref("B1")] });         // host re-sync, no mode key
    assert.equal(d.modeNote, "",
      "a sentence about shot A's references survived onto shot B");
  });

  // Older than the repair, same money: setRefs writes slots[0] and nothing else, so an flf shot
  // whose close frame is not picked yet inherited the last flf shot's End Frame.
  test("flf shot C -> flf shot B does not inherit C's End Frame", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applyPrefill(d, shot("flf", [ref("B_open")]));
    assert.deepEqual(buildPayload(d, "").images, ["B_open"],
      "shot C's End Frame is priced and submitted as part of shot B");
  });

  test("an flf shot that really has no images at all clears both frames", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applyPrefill(d, shot("flf", []));
    assert.deepEqual(buildPayload(d, "").images, []);
    assert.equal(hasAnyRef(buildPayload(d, "")), false);
  });

  // The other half of setRefs' contract, unchanged and load-bearing: a caller with NO opinion must
  // not have slots wiped. The gallery's lightbox "Send to Video" sends one image and has nothing
  // to say about an End Frame the user picked by hand.
  test("a prefill that omits images touches neither frame", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applyPrefill(d, { duration: 5 });
    assert.deepEqual(buildPayload(d, "").images, ["C1", "C2"],
      "a prefill with no opinion about images destroyed the user's picks");
  });

  test("setRefs on its own still leaves a hand-picked End Frame alone", () => {
    const d = drawer({ mode: "flf", slots: [ref("C1"), ref("C2")] });
    applySetRefs(d, [ref("S1")]);                     // gallery bulk "Send to Video"
    assert.deepEqual(buildPayload(d, "").images, ["S1", "C2"],
      "the gallery's one-image send wiped an End Frame it knows nothing about");
  });
});

describe("the r2v banks are the host's to overwrite, not a mode switch's to raid", () => {
  test("prefilling a new r2v shot replaces the previous shot's banks wholesale", () => {
    const d = drawer({
      mode: "r2v",
      imgSlots: [ref("A1"), ref("A2")],
      vidSlots: [ref("AV1")],
      audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    applyPrefill(d, shot("r2v", [ref("B1")], [ref("BV1")], { media_id: "BA1", filename: "b.wav" }));
    const p = buildPayload(d, "");
    assert.deepEqual(p.images, ["B1"]);
    assert.deepEqual(p.video_refs, ["BV1"]);
    assert.deepEqual(p.audio_refs, ["BA1"]);
  });

  test("video and audio refs still cannot leak out of Multi-Reference into a paid i2v submit", () => {
    const d = drawer({
      mode: "r2v",
      imgSlots: [ref("A1")],
      vidSlots: [ref("AV1")],
      audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    applyMode(d, "i2v", true);
    const p = buildPayload(d, "");
    assert.deepEqual(p.video_refs, [], "a surviving r2v video ref inflated an i2v payload");
    assert.deepEqual(p.audio_refs, []);
  });
});

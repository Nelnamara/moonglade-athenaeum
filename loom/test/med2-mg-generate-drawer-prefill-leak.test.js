import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// M27, repair round -- ANOTHER SHOT'S MEDIA IN A PAID PAYLOAD.
//
// The first M27 repair (2026-07-27, reverted the same day) hung a "carry the outgoing
// Multi-Reference picks into the Start Frame" step off _setMode. _setMode is not a user
// gesture: prefill() calls it too, and calls it FIRST, before setRefs() has written the
// incoming shot's images. The Loom drives that path on every shot click.
//
//   Loom is on r2v shot A, _imgSlots = [A1, A2, A3].
//   User clicks flf shot B whose close frame is not picked yet, so the Loom's payload
//   carries images: [B_open] -- one element, a normal intermediate state (master-storyboard
//   builds it as [openFrame, closeFrame].filter(...)).
//   prefill -> _setMode('flf') -> carry fills room=2 -> _slots = [A1, A2].
//   prefill -> setRefs([B_open]) -> one ref, mode !== 'r2v' -> writes _slots[0] ONLY.
//   _slots = [B_open, A2].  payload().images = ["B_open", "A2"].
//
// A2 belongs to shot A. The cost badge prices it and Generate spends credits on it. Measured
// against the pre-repair working tree; measured as ["B_open"] against git HEAD, i.e. the
// repair introduced it.
//
// Two separate defects have to stay closed for that to be impossible, and this file pins
// both:
//   1. a host-driven re-sync must not act like a user mode change (nothing carried, nothing
//      narrated) -- _setMode's `userDriven` flag;
//   2. an explicit images array is the COMPLETE list for its shot, so prefill has to empty
//      the flf End Frame setRefs() does not write. That second one is older than the repair:
//      flf shot C [C1, C2] followed by flf shot B images:[B_open] already gave
//      ["B_open", "C2"] at HEAD -- same money, different route in.
//
// Extraction pattern and its rationale: see med-mg-generate-drawer-mode-carry.test.js.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-generate-drawer.js"), "utf8")
  .replace(/\r\n/g, "\n");

function extractMethod(name) {
  const re = new RegExp("\\n    " + name + "\\([^)]*\\) \\{\\n[\\s\\S]*?\\n    \\}\\n");
  const m = src.match(re);
  assert.ok(m, `expected to find a "${name}(...) {" method in mg-generate-drawer.js -- if it ` +
               `was renamed or re-indented, update this pattern, don't delete the test`);
  return m[0];
}
function extractDecl(re, label) {
  const m = src.match(re);
  assert.ok(m, `expected to find ${label} in mg-generate-drawer.js`);
  return m[0];
}

const api = new Function(`
  ${extractDecl(/var MODE_LBL = \{[\s\S]*?\n  \};/, "MODE_LBL")}
  ${extractDecl(/var MODE_PH = \{[\s\S]*?\n  \};/, "MODE_PH")}
  ${extractDecl(/var MODEL_VMODES = \{[\s\S]*?\n  \};/, "MODEL_VMODES")}
  ${extractDecl(/var MODEL_MAXDUR = \{[^}]*\};/, "MODEL_MAXDUR")}
  ${extractDecl(/var DURATIONS = \[[^\]]*\];/, "DURATIONS")}
  ${extractDecl(/function snapDuration\(d\) \{[\s\S]*?\n  \}/, "snapDuration")}
  ${extractDecl(/function joinAnd\(parts\) \{[\s\S]*?\n  \}/, "joinAnd")}
  return {
    _primary() { return this._mode === 'r2v' ? this._imgSlots : this._slots; },
    _setPrimary(arr) { if (this._mode === 'r2v') this._imgSlots = arr; else this._slots = arr; },
    ${extractMethod("_setMode")},
    ${extractMethod("_noteR2vHeld")},
    ${extractMethod("_noteMode")},
    ${extractMethod("_applyModelGating")},
    ${extractMethod("setRefs")},
    ${extractMethod("prefill")},
    ${extractMethod("payload")},
    ${extractDecl(/_hasAnyRef\(p\) \{[^\n]*\}/, "_hasAnyRef")}
  };
`)();

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

function drawer(init) {
  const d = Object.assign({
    _mode: "i2v",
    _slots: [null],
    _imgSlots: [null],
    _vidSlots: [],
    _audSlot: null,
    _modeNote: { textContent: "", style: { display: "none" } },
    _slotsLbl: { textContent: "" },
    _ce: { setAttribute() {} },
    _neg: { value: "" },
    _cam: { value: "" },
    _camWrap: { style: {} },
    _vidLbl: { style: {} }, _vidWrap: { style: {} },
    _audLbl: { style: {} }, _audRow: { style: {} },
    _model: { value: "v4.0.1" },
    _quality: { value: "professional" },
    _channel: { value: "normal" },
    _lang: { value: "english" },
    _audio: { checked: false },
    _langWrap: { style: {} },
    _dur: { value: "10", querySelectorAll: () => [] },
    querySelectorAll: () => [],
    _promptText: () => "",
    _promptSet() {},
    _renderSlots() {}, _renderVidSlots() {}, _renderAudioRow() {},
    _renderModelCaps() {}, _renderChanCap() {}, _audioToggle() {}, _debCost() {},
  }, init);
  return Object.assign(d, api);
}

// The exact object master-storyboard.jsx builds for a shot (see its prefill effect): mode,
// and images/video_refs/audio_ref ALWAYS stated, even when empty.
function shot(mode, images, video_refs, audio_ref) {
  return {
    mode, duration: 10, audio: false, audio_language: "english", quality: "professional",
    images: images || [], video_refs: video_refs || [], audio_ref: audio_ref || null,
  };
}

describe("a host prefill never lets one shot's media into another shot's payload (M27)", () => {
  test("r2v shot A -> flf shot B with only its open frame picked", () => {
    const d = drawer({ _mode: "r2v", _imgSlots: [ref("A1"), ref("A2"), ref("A3")] });
    d.prefill(shot("flf", [ref("B_open")]));
    assert.deepEqual(d.payload().images, ["B_open"],
      "shot A's reference reached shot B's payload -- Generate would spend on it");
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["B_open", null]);
  });

  test("r2v shot A -> i2v shot B with no refs at all leaves nothing behind, and says nothing", () => {
    const d = drawer({
      _mode: "r2v",
      _imgSlots: [ref("A1")],
      _vidSlots: [ref("AV1")],
      _audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    d.prefill(shot("i2v", [], [], null));
    assert.deepEqual(d.payload().images, []);
    assert.equal(d._hasAnyRef(d.payload()), false, "an empty shot arrived priced");
    // The notice was false in every clause on this route: nothing was carried (setRefs nulled
    // it) and the video/audio refs were not held (prefill wiped them) -- and it stayed on
    // screen over the next shot's slots because only _setMode ever cleared it.
    assert.equal(d._modeNote.textContent, "",
      "the drawer told the user about the PREVIOUS shot's references: " +
      JSON.stringify(d._modeNote.textContent));
  });

  test("a notice raised against the previous shot is cleared even when the mode does not change", () => {
    const d = drawer({ _mode: "r2v", _imgSlots: [ref("A1"), ref("A2")] });
    d._setMode("i2v", true);                       // user gesture: notice is legitimate here
    assert.notEqual(d._modeNote.textContent, "");
    d.prefill({ images: [ref("B1")] });            // host re-sync, no mode key
    assert.equal(d._modeNote.textContent, "",
      "a sentence about shot A's references survived onto shot B");
    assert.equal(d._modeNote.style.display, "none");
  });

  // Older than the repair, same money: setRefs writes _slots[0] and nothing else, so an flf
  // shot whose close frame is not picked yet inherited the last flf shot's End Frame.
  test("flf shot C -> flf shot B does not inherit C's End Frame", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.prefill(shot("flf", [ref("B_open")]));
    assert.deepEqual(d.payload().images, ["B_open"],
      "shot C's End Frame is priced and submitted as part of shot B");
  });

  test("an flf shot that really has no images at all clears both frames", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.prefill(shot("flf", []));
    assert.deepEqual(d.payload().images, []);
    assert.equal(d._hasAnyRef(d.payload()), false);
  });

  // The other half of setRefs' contract, unchanged and load-bearing: a caller with NO opinion
  // must not have slots wiped. The gallery's lightbox "Send to Video" sends one image and has
  // nothing to say about an End Frame the user picked by hand.
  test("a prefill that omits images touches neither frame", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.prefill({ duration: 5 });
    assert.deepEqual(d.payload().images, ["C1", "C2"],
      "a prefill with no opinion about images destroyed the user's picks");
  });

  test("setRefs on its own still leaves a hand-picked End Frame alone", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.setRefs([ref("S1")]);                        // gallery bulk "Send to Video"
    assert.deepEqual(d.payload().images, ["S1", "C2"],
      "the gallery's one-image send wiped an End Frame it knows nothing about");
  });
});

describe("the r2v banks are the host's to overwrite, not a mode switch's to raid", () => {
  test("prefilling a new r2v shot replaces the previous shot's banks wholesale", () => {
    const d = drawer({
      _mode: "r2v",
      _imgSlots: [ref("A1"), ref("A2")],
      _vidSlots: [ref("AV1")],
      _audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    d.prefill(shot("r2v", [ref("B1")], [ref("BV1")], { media_id: "BA1", filename: "b.wav" }));
    const p = d.payload();
    assert.deepEqual(p.images, ["B1"]);
    assert.deepEqual(p.video_refs, ["BV1"]);
    assert.deepEqual(p.audio_refs, ["BA1"]);
  });

  test("video and audio refs still cannot leak out of Multi-Reference into a paid i2v submit", () => {
    const d = drawer({
      _mode: "r2v",
      _imgSlots: [ref("A1")],
      _vidSlots: [ref("AV1")],
      _audSlot: { media_id: "AA1", filename: "a.wav" },
    });
    d._setMode("i2v", true);
    const p = d.payload();
    assert.deepEqual(p.video_refs, [], "a surviving r2v video ref inflated an i2v payload");
    assert.deepEqual(p.audio_refs, []);
  });
});

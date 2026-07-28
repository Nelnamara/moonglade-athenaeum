import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// FLF END-FRAME DELIVERY (2026-07-27, closing-frame pass).
//
// The Loom's prefill effect builds an flf shot's image list as [openFrame, closeFrame] and
// states mode:'flf' in the same prefill() call -- but prefill() routed EVERY images array
// through setRefs(), whose multi-image branch exists for the gallery's bulk "Send to
// Video" and therefore force-switches to r2v (`refs.length > 1 -> _setMode('r2v')`) and
// writes the r2v bank. Net effect on a First & Last shot with both frames attached:
//
//   prefill -> _setMode('flf')             (the host's stated mode)
//   prefill -> setRefs([open, close])      -> _setMode('r2v'), _imgSlots = [open, close]
//
// The drawer silently left the mode the host just stated, and the End Frame never landed
// in the End Frame box (_slots[1]) -- not on first prefill, not on any re-prefill, since
// every re-sync repeated the same route. No host-side fix exists: prefill()/setRefs() are
// the drawer's whole public surface and neither could write _slots[1] (setRefs must not --
// a one-image gallery send wiping a hand-picked End Frame is data loss, see its comment).
// So prefill() now maps a host-stated flf image list of <= 2 onto the two frame slots
// POSITIONALLY (images[0] -> Start, images[1] -> End), with no _setMode call and no event
// (the same no-dispatch discipline as the _setMode/_userSetMode split).
//
// Extraction pattern and its rationale: med-mg-generate-drawer-mode-carry.test.js. The
// single-image / empty-list / omitted-key behaviors this must NOT disturb are pinned by
// med2-mg-generate-drawer-prefill-leak.test.js; the guards at the bottom re-state the two
// closest ones from this angle.
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
    d.prefill(shot("flf", [ref("B_open"), ref("B_close")]));
    assert.equal(d._mode, "flf",
      "setRefs' bulk-send branch bounced the drawer into Multi-Reference against the mode " +
      "the host stated two lines earlier in the same call");
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["B_open", "B_close"],
      "the End Frame must be IN the End Frame box (_slots[1]) with no tab toggle");
    const p = d.payload();
    assert.equal(p.mode, "FLF");
    assert.deepEqual(p.images, ["B_open", "B_close"]);
  });

  test("re-prefilling after a frame replace updates the slots in place", () => {
    const d = drawer({});
    d.prefill(shot("flf", [ref("open_v1"), ref("close")]));
    d.prefill(shot("flf", [ref("open_v2"), ref("close")]));
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["open_v2", "close"]);
    assert.equal(d._mode, "flf");
  });

  // Guards: the behaviors this branch must NOT disturb (all pass before AND after the fix;
  // med2-mg-generate-drawer-prefill-leak.test.js owns the fuller versions).
  test("one image still means Start only, End explicitly emptied", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.prefill(shot("flf", [ref("B_open")]));
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["B_open", null]);
  });

  test("an empty images array still clears both frames", () => {
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.prefill(shot("flf", []));
    assert.deepEqual(d._slots.map((s) => s && s.media_id), [null, null]);
  });

  test("an r2v prefill still routes multiple images to the r2v bank", () => {
    const d = drawer({});
    d.prefill(shot("r2v", [ref("R1"), ref("R2"), ref("R3")]));
    assert.equal(d._mode, "r2v");
    assert.deepEqual(d._imgSlots.map((s) => s && s.media_id), ["R1", "R2", "R3"]);
  });

  test("the gallery's DIRECT setRefs bulk-send still promotes to r2v even from flf", () => {
    // setRefs without a surrounding prefill has no host-stated mode to honor -- a multi-
    // image gallery send really does mean Multi-Reference, exactly as before.
    const d = drawer({ _mode: "flf", _slots: [ref("C1"), ref("C2")] });
    d.setRefs([ref("S1"), ref("S2"), ref("S3")]);
    assert.equal(d._mode, "r2v");
    assert.deepEqual(d._imgSlots.map((s) => s && s.media_id), ["S1", "S2", "S3"]);
  });
});

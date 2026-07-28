import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { resolvedImage } from "../src/loom-core.js";

/* FLF POSITIONAL PREFILL (2026-07-27, round 3 -- the MONEY BUG of the round-2 review).

   Round 2 taught the drawer's prefill() to map a host-stated flf image list onto the two
   frame slots POSITIONALLY (images[0] -> Start box, images[1] -> End box; see
   med3-drawer-flf-end-frame-prefill.test.js). But the HOST kept building that list by
   FILTERING:

     payload.images = [openFrame, closeFrame].filter((f) => f && f.mediaId).map(...)

   A filter destroys position. An flf shot whose END frame is gallery-picked while its
   start frame is still empty (a completely normal intermediate state) produced
   images=[close] -- a ONE-item list -- and the drawer's positional branch put the
   intended END frame in the START box. Generate then spent real credits rendering FROM
   the end frame. Both round-2 reviewers reproduced it.

   The repair: the host passes [Start-or-null, End-or-null] with nulls PRESERVED, and the
   drawer's flf branch maps a null to "clear that slot". The same host change also stops
   testing bare f.mediaId and resolves through resolvedImage() -- so a locally-uploaded
   (thumbId-only) frame ships as its data-URL, the shape the r2v bank already uses and
   the server's resolve_img() (moonglade_gallery.py /api/loom/generate) base64-uploads
   for EVERY mode, flf included.

   The end-to-end test below does not simulate the host's list-building -- it EXTRACTS the
   actual flf branch from master-storyboard.jsx and executes it, then feeds its output to
   the drawer methods extracted from mg-generate-drawer.js. Against the round-2 tree it
   fails on the money trigger itself (end frame lands in the Start box); against the
   repaired tree the End Frame stays an End Frame and the Start box stays empty.
   Extraction pattern and its rationale: med-mg-generate-drawer-mode-carry.test.js. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const drawerSrc = readFileSync(path.join(__dirname, "../../static/mg-generate-drawer.js"), "utf8")
  .replace(/\r\n/g, "\n");
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; every pattern below assumes LF

/* ---- the host half: the ACTUAL flf branch out of the prefill effect ---- */

const branchM = jsx.match(/\} else if \(nextMode === "flf"\) \{\n([\s\S]*?)\n {4}\} else if \(nextMode === "r2v"\) \{/);
assert.ok(branchM, "could not locate the prefill effect's flf branch in master-storyboard.jsx -- " +
  "if the effect was restructured, update this pattern, don't delete the test");

// Everything the branch body references, injected. asRef/imgSrc/frameSrc mirror the
// component's own definitions (imgSrc resolves a thumbId against `thumbs` state; the
// fixture passes the lookup directly).
const runFlfBranch = (openFrame, closeFrame, thumbs = {}) => {
  const payload = { images: [] };
  const active = { c: { openFrame, closeFrame } };
  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);
  const asRef = (d) => ({ media_id: d, thumb: /^\d+$/.test(d) ? ("/thumbs/" + d + ".jpg") : d });
  const frameSrc = (f) => (f && f.thumbId ? thumbs[f.thumbId] : (f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null));
  new Function("active", "payload", "resolvedImage", "imgSrc", "asRef", "frameSrc", branchM[1])(
    active, payload, resolvedImage, imgSrc, asRef, frameSrc);
  return payload.images;
};

/* ---- the drawer half: same extraction harness as med3-drawer-flf-end-frame-prefill ---- */

function extractMethod(name) {
  const re = new RegExp("\\n    " + name + "\\([^)]*\\) \\{\\n[\\s\\S]*?\\n    \\}\\n");
  const m = drawerSrc.match(re);
  assert.ok(m, `expected to find a "${name}(...) {" method in mg-generate-drawer.js`);
  return m[0];
}
function extractDecl(re, label) {
  const m = drawerSrc.match(re);
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

const flfPrefill = (images) => ({
  mode: "flf", duration: 10, audio: false, audio_language: "english",
  quality: "professional", images, video_refs: [], audio_ref: null,
});
const emptyFrame = { mediaId: "", thumbId: "", source: "", desc: "", tag: "" };
const galleryFrame = (mid) => ({ mediaId: mid, thumbId: "", source: "", desc: "", tag: "" });

describe("host -> drawer, end to end: the flf image list is positional", () => {
  test("MONEY TRIGGER: end frame picked first -> lands in the END slot, Start stays empty", () => {
    const images = runFlfBranch(emptyFrame, galleryFrame("747000000000000001"));
    const d = drawer({});
    d.prefill(flfPrefill(images));
    assert.equal(d._mode, "flf");
    assert.equal(d._slots[0], null,
      "the Start box must stay EMPTY -- round 2's host filter collapsed [empty, close] " +
      "to a one-item list and the drawer put the intended END frame here, so Generate " +
      "rendered FROM the end frame on real credits");
    assert.equal(d._slots[1] && d._slots[1].media_id, "747000000000000001",
      "the gallery-picked END frame must be in the End Frame box");
  });

  test("both frames attached still lands [Start, End] in order", () => {
    const images = runFlfBranch(galleryFrame("111"), galleryFrame("222"));
    const d = drawer({});
    d.prefill(flfPrefill(images));
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["111", "222"]);
  });

  test("start-only shot: End slot is explicitly cleared, not left holding a stale frame", () => {
    const d = drawer({ _mode: "flf", _slots: [{ media_id: "C1", thumb: "t" }, { media_id: "C2", thumb: "t" }] });
    d.prefill(flfPrefill(runFlfBranch(galleryFrame("333"), emptyFrame)));
    assert.deepEqual(d._slots.map((s) => s && s.media_id), ["333", null]);
  });

  test("thumbId-only (locally uploaded) frame ships as its data-URL, same shape r2v uses", () => {
    // The server's resolve_img() (/api/loom/generate) base64-uploads a data: URL for
    // every mode, flf included -- so this shape is genuinely submittable, not just
    // visible. Round 2's `f.mediaId` test silently dropped this frame from the drawer
    // while the board card numbered it @image2.
    const dataUrl = "data:image/png;base64,QUJD";
    const localFrame = { mediaId: "", thumbId: "t1", source: "shot.png", desc: "", tag: "" };
    const images = runFlfBranch(galleryFrame("444"), localFrame, { t1: dataUrl });
    const d = drawer({});
    d.prefill(flfPrefill(images));
    assert.equal(d._slots[1] && d._slots[1].media_id, dataUrl,
      "the End Frame slot must hold the local frame's data-URL");
    assert.deepEqual(d.payload().images, ["444", dataUrl],
      "payload() must carry the data-URL through to /api/price and /api/loom/generate");
  });

  test("the host branch preserves nulls -- it never filters", () => {
    // The structural pin behind the behavioral tests above: the list is ALWAYS
    // [Start-or-null, End-or-null]. A future `.filter(...)` reintroduction collapses
    // positions again no matter how the drawer behaves.
    assert.deepEqual(runFlfBranch(emptyFrame, emptyFrame), [null, null]);
    assert.equal(runFlfBranch(emptyFrame, galleryFrame("555")).length, 2,
      "an flf image list is always length 2 -- position IS the meaning");
    // Comment lines dropped first (same discipline as loom-jsx-imports-complete.test.js):
    // the branch's own comment QUOTES round 2's filter while explaining why it was wrong.
    const branchCode = branchM[1].split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
    assert.ok(!/\.filter\(/.test(branchCode),
      "the flf branch must not filter the frame list -- filtering is exactly what " +
      "destroyed position in round 2");
  });
});

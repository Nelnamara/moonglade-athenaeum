import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// M27 -- changing the Model dropdown silently emptied every Multi-Reference pick.
//
// r2v (Multi-Reference) keeps its picks in the separate _imgSlots/_vidSlots/_audSlot banks
// while i2v/flf use _slots. _applyModelGating() force-switches the mode via _setMode() the
// moment the selected model's MODEL_VMODES doesn't list the current one (V3.0 Flash allows
// i2v only), and _setMode() then runs `this._slots = [this._slots[0] || null]` on a _slots
// array nothing had written to for the whole time the user was in r2v. Four picked image
// refs, a video ref and an audio ref vanished from the drawer at once -- no confirmation, no
// message, no mg-error -- and the user had no way to know they were still there.
//
// THE FIX IS A NOTICE, NOT A CARRY, and the distinction is the whole point of this file.
// Nothing was ever actually destroyed: _setMode does not touch the r2v banks on the way out,
// so returning to Multi-Reference renders every pick again. What the user lost was the
// knowledge of that. The first attempt (2026-07-27, reverted the same day) instead COPIED
// _imgSlots[0] into the Start Frame, which put a reference image the user picked for
// style/subject influence into the primary input of an expensive paid render, priced it in
// the cost badge, and armed Go -- off a switch the user never asked for. These tests pin the
// repaired shape: the priced banks are never written by a mode switch, and the notice only
// ever speaks for a gesture a human actually made.
//
// static/mg-generate-drawer.js is a plain <script> with no build step (only loom/ has a
// bundle -- loom/scripts/build.mjs takes master-storyboard.jsx + loom/src/ and nothing from
// static/), and there is no jsdom in this runner. So, following the pattern established by
// mg-generate-drawer-concurrent.test.js / mg-generate-drawer-parity.test.js: methods are
// extracted as REAL callables and invoked against a stand-in `this`, with source-presence
// assertions for the parts that are pure DOM wiring.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks this out as CRLF on Windows) -- extractMethod's regexes
// anchor on exact `\n` + indent boundaries around braces.
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

// The methods under test, plus every module-scope value they close over, pulled out together:
// `new Function`'s body runs in the GLOBAL scope, not the IIFE's, so MODE_LBL/MODE_PH/
// MODEL_VMODES/MODEL_MAXDUR/joinAnd have to travel with them. They are extracted from the
// real source rather than restated here, so this test can never pass against a table it made
// up itself. payload()/_hasAnyRef are pulled in too: "did the mode switch put something
// priceable in front of the user" is the assertion that actually matters, and only the real
// payload() can answer it.
const api = new Function(`
  ${extractDecl(/var MODE_LBL = \{[\s\S]*?\n  \};/, "MODE_LBL")}
  ${extractDecl(/var MODE_PH = \{[\s\S]*?\n  \};/, "MODE_PH")}
  ${extractDecl(/var MODEL_VMODES = \{[\s\S]*?\n  \};/, "MODEL_VMODES")}
  ${extractDecl(/var MODEL_MAXDUR = \{[^}]*\};/, "MODEL_MAXDUR")}
  ${extractDecl(/function joinAnd\(parts\) \{[\s\S]*?\n  \}/, "joinAnd")}
  return {
    _primary() { return this._mode === 'r2v' ? this._imgSlots : this._slots; },
    ${extractMethod("_setMode")},
    ${extractMethod("_noteR2vHeld")},
    ${extractMethod("_noteMode")},
    ${extractMethod("_applyModelGating")},
    ${extractMethod("payload")},
    ${extractDecl(/_hasAnyRef\(p\) \{[^\n]*\}/, "_hasAnyRef")}
  };
`)();

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

// A stand-in drawer: the element references _setMode/payload touch, stubbed to the minimum
// that makes the real code run, plus the four slot banks as real arrays so the effect of a
// switch can be observed for what it is -- data movement, not a repaint.
function drawer(init) {
  const d = Object.assign({
    _mode: "r2v",
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
    _dur: { value: "10", querySelectorAll: () => [] },
    querySelectorAll: () => [],
    renders: 0,
    _promptText: () => "",
    _renderSlots() { this.renders++; },
    _renderVidSlots() {},
    _renderAudioRow() {},
  }, init);
  return Object.assign(d, api);
}

const note = (d) => d._modeNote.textContent;
const priced = (d) => d._hasAnyRef(d.payload());

describe("leaving Multi-Reference names what is held and prices nothing (M27)", () => {
  // THE REGRESSION, in the form the finding filed it. Against the old _setMode this fails on
  // the notice asserts: the drawer said nothing at all, so a user watching four thumbnails
  // disappear had no way to learn they were still in the element.
  test("r2v -> i2v by user click: every ref is named, none is promoted to a priced slot", () => {
    const d = drawer({
      _imgSlots: [ref(101), ref(102), ref(103), ref(104)],
      _vidSlots: [ref(201)],
      _audSlot: { media_id: "301", filename: "waves.wav" },
    });
    d._setMode("i2v", true);
    assert.match(note(d), /Still held for Multi-Reference: 4 image refs, 1 video ref and the audio ref\./,
      "the refs that can't travel were dropped without a word: " + JSON.stringify(note(d)));
    assert.equal(d._modeNote.style.display, "", "the notice was written but left hidden");
    // The half that matters for money: the Start Frame is the primary input of a paid render.
    assert.deepEqual(d._slots, [null],
      "a mode switch wrote into the Start Frame -- that is a spend decision the user did not make");
    assert.equal(priced(d), false,
      "the cost badge would price a render whose source image the user never chose");
  });

  test("the notice does not promise a return trip gating can refuse", () => {
    // On V3.0 Flash _applyModelGating sets display:none on the Multi-Reference button, so
    // "switch back" is unreachable until the user picks an r2v-capable model. The first
    // wording ("back as soon as you return to it") was simply false there.
    const d = drawer({ _imgSlots: [ref(101)] });
    d._setMode("i2v", true);
    assert.match(note(d), /on a model that offers it/,
      "the notice tells the user to switch back without saying the button may be hidden");
    assert.match(note(d), /Nothing was deleted/);
    // ...and it describes state, not capability. "only apply in Multi-Reference" was false
    // with an empty Start Frame -- an image ref applies there fine; the user just hadn't
    // said to put it there, which is exactly the decision this notice must not make for them.
    assert.doesNotMatch(note(d), /only appl/i,
      "the notice makes a capability claim about the refs that the drawer cannot back up");
  });

  test("flf gets its own name in the notice, and its End Frame is left alone too", () => {
    const d = drawer({ _imgSlots: [ref(101), ref(102), ref(103)] });
    d._setMode("flf", true);
    assert.deepEqual(d._slots, [null, null], "the flf frames were filled from a bank flf cannot submit");
    assert.match(note(d), /First & Last Frames has nowhere to show that/);
    assert.match(note(d), /Still held for Multi-Reference: 3 image refs\./);
  });

  test("one ref reads as singular", () => {
    const d = drawer({ _imgSlots: [ref(101)], _vidSlots: [ref(201)] });
    d._setMode("i2v", true);
    assert.match(note(d), /1 image ref and 1 video ref\./);   // not "1 image refs"
  });

  test("a Start Frame the user already picked is neither overwritten nor re-priced", () => {
    const d = drawer({ _slots: [ref(999)], _imgSlots: [ref(101), ref(102)] });
    d._setMode("i2v", true);
    assert.deepEqual(d._slots, [ref(999)], "an existing Start Frame pick was overwritten");
    assert.equal(priced(d), true, "the user's own earlier pick stopped being priced");
    assert.match(note(d), /2 image refs\./);
  });

  test("the r2v banks survive the switch, so returning restores every ref", () => {
    const d = drawer({
      _imgSlots: [ref(101), ref(102)],
      _vidSlots: [ref(201)],
      _audSlot: { media_id: "301", filename: "waves.wav" },
    });
    d._setMode("i2v", true);
    d._setMode("r2v", true);
    assert.deepEqual(d._imgSlots, [ref(101), ref(102)], "image refs were spliced out of the bank");
    assert.deepEqual(d._vidSlots, [ref(201)]);
    assert.deepEqual(d._audSlot, { media_id: "301", filename: "waves.wav" });
    assert.deepEqual(d.payload().images, ["101", "102"], "the notice's promise does not hold");
    assert.equal(note(d), "", "the notice outlived the switch it was describing");
    assert.equal(d._modeNote.style.display, "none");
  });

  // The aliasing bug the carry introduced: the same object sat in _imgSlots AND _slots, and
  // the carry only filled EMPTY target slots, so a ref the user later deleted in r2v stayed
  // behind in the Start Frame -- still rendered, still priced, still submitted.
  test("a ref deleted in Multi-Reference cannot survive in the Start Frame", () => {
    const d = drawer({ _imgSlots: [ref(101), ref(102)] });
    d._setMode("i2v", true);
    d._setMode("r2v", true);
    d._imgSlots.splice(0, 1);                        // user deletes @image1
    d._setMode("i2v", true);
    assert.deepEqual(d._slots, [null],
      "an image the user explicitly deleted is still in the priced Start Frame");
    assert.deepEqual(d.payload().images, []);
  });

  test("an empty Multi-Reference bank produces no notice at all", () => {
    const d = drawer({ _imgSlots: [null] });
    d._setMode("i2v", true);
    assert.equal(note(d), "", "a switch that lost nothing still nagged the user");
    assert.equal(d._modeNote.style.display, "none");
  });

  test("video and audio refs alone are still reported, even with no image refs", () => {
    const d = drawer({
      _imgSlots: [null],
      _vidSlots: [ref(201), ref(202)],
      _audSlot: { media_id: "301", filename: "waves.wav" },
    });
    d._setMode("i2v", true);
    assert.match(note(d), /^Still held for Multi-Reference: 2 video refs and the audio ref\./);
  });

  test("switching between i2v and flf never invents a notice (r2v isn't involved)", () => {
    const d = drawer({ _mode: "i2v", _slots: [ref(999)], _imgSlots: [ref(101)] });
    d._setMode("flf", true);
    assert.equal(note(d), "");
    assert.deepEqual(d._slots, [ref(999), null], "the End Frame was filled from a bank flf doesn't use");
  });

  test("the first _setMode of the element's life (mode undefined) says nothing", () => {
    const d = drawer({ _mode: undefined, _imgSlots: [ref(101)] });
    d._setMode("i2v");
    assert.deepEqual(d._slots, [null]);
    assert.equal(note(d), "");
  });
});

describe("the model-gating path itself -- the way M27 was actually hit", () => {
  test("picking V3.0 Flash (i2v only) while in Multi-Reference explains itself", () => {
    const d = drawer({
      _model: { value: "v3.0.1" },                 // V3.0 Flash: MODEL_VMODES = ['i2v']
      _imgSlots: [ref(101), ref(102), ref(103), ref(104)],
      _vidSlots: [ref(201)],
      _audSlot: { media_id: "301", filename: "waves.wav" },
    });
    d._applyModelGating(true);                     // what the Model <select>'s change listener does
    assert.equal(d._mode, "i2v", "gating no longer forces an unsupported mode off r2v");
    assert.match(note(d), /Still held for Multi-Reference: 4 image refs, 1 video ref and the audio ref\./,
      "changing the Model dropdown still empties the drawer without a word");
    assert.deepEqual(d._slots, [null],
      "a model change armed the Start Frame of a paid render on its own");
    assert.equal(priced(d), false);
  });

  // The gate that keeps the notice honest. _applyModelGating is ALSO called by prefill() and
  // by connectedCallback, where the mode change is the host re-syncing the drawer onto a
  // different shot -- narrating that as "your Multi-Reference picks are held" describes the
  // PREVIOUS shot's banks over the new shot's slots.
  test("gating re-asserted without a user gesture stays silent", () => {
    const d = drawer({ _model: { value: "v3.0.1" }, _imgSlots: [ref(101), ref(102)] });
    d._applyModelGating();                         // no userDriven flag: prefill()/mount route
    assert.equal(d._mode, "i2v");
    assert.equal(note(d), "",
      "a host-driven re-sync narrated itself as a choice the user made");
  });

  test("picking a model that still supports r2v changes nothing", () => {
    const d = drawer({ _model: { value: "v4.0" }, _imgSlots: [ref(101), ref(102)] });
    d._applyModelGating(true);
    assert.equal(d._mode, "r2v");
    assert.deepEqual(d._imgSlots, [ref(101), ref(102)]);
    assert.equal(note(d), "");
  });
});

describe("the _setMode / _userSetMode split is untouched", () => {
  test("_setMode still dispatches nothing -- only _userSetMode may commit a mode", () => {
    // prefill(), _applyModelGating() and setRefs() all call _setMode(); if it ever dispatched,
    // a click -> mg-mode-commit -> host update -> prefill() -> _setMode() -> re-dispatch loop
    // results. The notice hook added for M27 must not have smuggled an event in.
    const setModeSrc = extractMethod("_setMode");
    assert.doesNotMatch(setModeSrc, /dispatchEvent/,
      "_setMode dispatches an event -- that is _userSetMode's job, and only from a real click");
    assert.doesNotMatch(extractMethod("_noteR2vHeld"), /dispatchEvent/,
      "the notice path dispatches an event; mg-error is contractually a REAL server failure only");
    assert.match(setModeSrc, /if \(userDriven && from === 'r2v' && m !== 'r2v'\) this\._noteR2vHeld\(m\);/,
      "_setMode no longer names the Multi-Reference picks a user switch leaves behind");
  });

  test("_noteR2vHeld writes no slot -- it is a message, not a data move", () => {
    // The guard against the reverted first repair coming back by accident. Any assignment
    // into _slots from here is a spend decision made on the user's behalf.
    const holdSrc = extractMethod("_noteR2vHeld");
    assert.doesNotMatch(holdSrc, /this\._slots\[/,
      "the hold notice writes into the priced Start/End Frame bank");
    assert.doesNotMatch(holdSrc, /_setPrimary/);
  });

  test("only the Model <select>'s own change listener passes userDriven", () => {
    assert.match(src, /this\._model\.addEventListener\('change', function \(\) \{ self\._renderModelCaps\(\); self\._applyModelGating\(true\); self\._debCost\(\); \}\);/,
      "the user's model change no longer explains where the Multi-Reference picks went");
    assert.match(src, /\n      this\._applyModelGating\(\);\n    \}/,
      "connectedCallback's mount-time gating call now claims to be a user gesture");
    assert.match(src, /^      this\._applyModelGating\(\);$/m);
    assert.match(extractMethod("_userSetMode"), /this\._setMode\(m, true\);/,
      "a real click on a mode button no longer counts as user-driven");
  });

  test("the notice element ships in MARKUP and is bound in connectedCallback", () => {
    assert.match(src, /'<div class="mgd-modenote" style="display:none;"><\/div>' \+/,
      "the mode-switch notice has no element to render into");
    assert.match(src, /this\._modeNote = this\.querySelector\('\.mgd-modenote'\);/,
      "_modeNote is never bound, so _noteMode would throw on the first mode switch");
    assert.match(src, /mg-generate-drawer \.mgd-modenote\{/,
      "the notice has no styling -- it would render as unreadable default-colored body text");
  });
});

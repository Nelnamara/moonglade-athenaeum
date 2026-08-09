import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  applyMode, applyModelGating, buildPayload, hasAnyRef, heldRefsNotice,
} from "../../gallery/src/gen/videoDrawerCore.js";

// M27 -- changing the Model dropdown silently emptied every Multi-Reference pick.
//
// r2v (Multi-Reference) keeps its picks in the separate imgSlots/vidSlots/audSlot banks while
// i2v/flf use `slots`. applyModelGating() force-switches the mode via applyMode() the moment the
// selected model's MODEL_VMODES doesn't list the current one (V3.0 Flash allows i2v only), and
// applyMode() then runs `slots = [slots[0] || null]` on a `slots` array nothing had written to for
// the whole time the user was in r2v. Four picked image refs, a video ref and an audio ref
// vanished from the drawer at once -- no confirmation, no message, no mg-error -- and the user had
// no way to know they were still there.
//
// THE FIX IS A NOTICE, NOT A CARRY, and the distinction is the whole point of this file. Nothing
// was ever actually destroyed: applyMode does not touch the r2v banks on the way out, so returning
// to Multi-Reference renders every pick again. What the user lost was the knowledge of that. The
// first attempt (2026-07-27, reverted the same day) instead COPIED imgSlots[0] into the Start
// Frame, which put a reference image the user picked for style/subject influence into the primary
// input of an expensive paid render, priced it in the cost badge, and armed Go -- off a switch the
// user never asked for. These tests pin the repaired shape: the priced banks are never written by
// a mode switch, and the notice only ever speaks for a gesture a human actually made.
//
// Since the no-vanilla port (2026-08-08) the transition logic is the PURE state layer in
// gallery/src/gen/videoDrawerCore.js (applyMode/applyModelGating/buildPayload/heldRefsNotice), the
// SAME functions the React <VideoDrawer> drives. So this file executes the real transition against
// a plain state object -- no source extraction, no DOM stubs -- which is a stronger check than the
// pre-port version that regex-extracted the vanilla <mg-generate-drawer> class methods.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

function ref(id) { return { media_id: String(id), thumb: "/thumbs/" + id + ".jpg" }; }

// A plain drawer-state object: the four slot banks as real arrays, so the effect of a mode switch
// can be observed for what it is -- data movement, not a repaint. Defaults to r2v (M27's scene).
function drawer(init) {
  return Object.assign({
    mode: "r2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 10, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}
const note = (d) => d.modeNote;
const priced = (d) => hasAnyRef(buildPayload(d, ""));

describe("leaving Multi-Reference names what is held and prices nothing (M27)", () => {
  // THE REGRESSION, in the form the finding filed it. Against the old carry this fails on the
  // priced-slot asserts: a mode switch had put a ref into the Start Frame of a paid render.
  test("r2v -> i2v by user click: every ref is named, none is promoted to a priced slot", () => {
    const d = drawer({
      imgSlots: [ref(101), ref(102), ref(103), ref(104)],
      vidSlots: [ref(201)],
      audSlot: { media_id: "301", filename: "waves.wav" },
    });
    applyMode(d, "i2v", true);
    assert.match(note(d), /Still held for Multi-Reference: 4 image refs, 1 video ref and the audio ref\./,
      "the refs that can't travel were dropped without a word: " + JSON.stringify(note(d)));
    assert.notEqual(note(d), "", "the notice was written but left empty");
    // The half that matters for money: the Start Frame is the primary input of a paid render.
    assert.deepEqual(d.slots, [null],
      "a mode switch wrote into the Start Frame -- that is a spend decision the user did not make");
    assert.equal(priced(d), false,
      "the cost badge would price a render whose source image the user never chose");
  });

  test("the notice does not promise a return trip gating can refuse", () => {
    const d = drawer({ imgSlots: [ref(101)] });
    applyMode(d, "i2v", true);
    assert.match(note(d), /on a model that offers it/,
      "the notice tells the user to switch back without saying the button may be hidden");
    assert.match(note(d), /Nothing was deleted/);
    assert.doesNotMatch(note(d), /only appl/i,
      "the notice makes a capability claim about the refs that the drawer cannot back up");
  });

  test("flf gets its own name in the notice, and its End Frame is left alone too", () => {
    const d = drawer({ imgSlots: [ref(101), ref(102), ref(103)] });
    applyMode(d, "flf", true);
    assert.deepEqual(d.slots, [null, null], "the flf frames were filled from a bank flf cannot submit");
    assert.match(note(d), /First & Last Frames has nowhere to show that/);
    assert.match(note(d), /Still held for Multi-Reference: 3 image refs\./);
  });

  test("one ref reads as singular", () => {
    const d = drawer({ imgSlots: [ref(101)], vidSlots: [ref(201)] });
    applyMode(d, "i2v", true);
    assert.match(note(d), /1 image ref and 1 video ref\./);   // not "1 image refs"
  });

  test("a Start Frame the user already picked is neither overwritten nor re-priced", () => {
    const d = drawer({ slots: [ref(999)], imgSlots: [ref(101), ref(102)] });
    applyMode(d, "i2v", true);
    assert.deepEqual(d.slots, [ref(999)], "an existing Start Frame pick was overwritten");
    assert.equal(priced(d), true, "the user's own earlier pick stopped being priced");
    assert.match(note(d), /2 image refs\./);
  });

  test("the r2v banks survive the switch, so returning restores every ref", () => {
    const d = drawer({
      imgSlots: [ref(101), ref(102)],
      vidSlots: [ref(201)],
      audSlot: { media_id: "301", filename: "waves.wav" },
    });
    applyMode(d, "i2v", true);
    applyMode(d, "r2v", true);
    assert.deepEqual(d.imgSlots, [ref(101), ref(102)], "image refs were spliced out of the bank");
    assert.deepEqual(d.vidSlots, [ref(201)]);
    assert.deepEqual(d.audSlot, { media_id: "301", filename: "waves.wav" });
    assert.deepEqual(buildPayload(d, "").images, ["101", "102"], "the notice's promise does not hold");
    assert.equal(note(d), "", "the notice outlived the switch it was describing");
  });

  // The aliasing bug the carry introduced: the same object sat in imgSlots AND slots, and the
  // carry only filled EMPTY target slots, so a ref the user later deleted in r2v stayed behind in
  // the Start Frame -- still rendered, still priced, still submitted.
  test("a ref deleted in Multi-Reference cannot survive in the Start Frame", () => {
    const d = drawer({ imgSlots: [ref(101), ref(102)] });
    applyMode(d, "i2v", true);
    applyMode(d, "r2v", true);
    d.imgSlots.splice(0, 1);                        // user deletes @image1
    applyMode(d, "i2v", true);
    assert.deepEqual(d.slots, [null],
      "an image the user explicitly deleted is still in the priced Start Frame");
    assert.deepEqual(buildPayload(d, "").images, []);
  });

  test("an empty Multi-Reference bank produces no notice at all", () => {
    const d = drawer({ imgSlots: [null] });
    applyMode(d, "i2v", true);
    assert.equal(note(d), "", "a switch that lost nothing still nagged the user");
  });

  test("video and audio refs alone are still reported, even with no image refs", () => {
    const d = drawer({
      imgSlots: [null],
      vidSlots: [ref(201), ref(202)],
      audSlot: { media_id: "301", filename: "waves.wav" },
    });
    applyMode(d, "i2v", true);
    assert.match(note(d), /^Still held for Multi-Reference: 2 video refs and the audio ref\./);
  });

  test("switching between i2v and flf never invents a notice (r2v isn't involved)", () => {
    const d = drawer({ mode: "i2v", slots: [ref(999)], imgSlots: [ref(101)] });
    applyMode(d, "flf", true);
    assert.equal(note(d), "");
    assert.deepEqual(d.slots, [ref(999), null], "the End Frame was filled from a bank flf doesn't use");
  });

  test("the first mode set of the drawer's life (mode undefined) says nothing", () => {
    const d = drawer({ mode: undefined, imgSlots: [ref(101)] });
    applyMode(d, "i2v");
    assert.deepEqual(d.slots, [null]);
    assert.equal(note(d), "");
  });
});

describe("the model-gating path itself -- the way M27 was actually hit", () => {
  test("picking V3.0 Flash (i2v only) while in Multi-Reference explains itself", () => {
    const d = drawer({
      model: "v3.0.1",                              // V3.0 Flash: MODEL_VMODES = ['i2v']
      imgSlots: [ref(101), ref(102), ref(103), ref(104)],
      vidSlots: [ref(201)],
      audSlot: { media_id: "301", filename: "waves.wav" },
    });
    applyModelGating(d, true);                       // what the Model <select>'s change listener does
    assert.equal(d.mode, "i2v", "gating no longer forces an unsupported mode off r2v");
    assert.match(note(d), /Still held for Multi-Reference: 4 image refs, 1 video ref and the audio ref\./,
      "changing the Model dropdown still empties the drawer without a word");
    assert.deepEqual(d.slots, [null],
      "a model change armed the Start Frame of a paid render on its own");
    assert.equal(priced(d), false);
  });

  // The gate that keeps the notice honest. applyModelGating is ALSO called by prefill (host
  // re-sync onto a different shot); narrating that as "your Multi-Reference picks are held"
  // describes the PREVIOUS shot's banks over the new shot's slots.
  test("gating re-asserted without a user gesture stays silent", () => {
    const d = drawer({ model: "v3.0.1", imgSlots: [ref(101), ref(102)] });
    applyModelGating(d);                             // no userDriven flag: prefill()/mount route
    assert.equal(d.mode, "i2v");
    assert.equal(note(d), "",
      "a host-driven re-sync narrated itself as a choice the user made");
  });

  test("picking a model that still supports r2v changes nothing", () => {
    const d = drawer({ model: "v4.0", imgSlots: [ref(101), ref(102)] });
    applyModelGating(d, true);
    assert.equal(d.mode, "r2v");
    assert.deepEqual(d.imgSlots, [ref(101), ref(102)]);
    assert.equal(note(d), "");
  });
});

describe("the notice path writes no slot, and only a user gesture can commit a mode", () => {
  test("heldRefsNotice is a pure read -- it writes no priced slot", () => {
    const d = drawer({ imgSlots: [ref(101), ref(102)], slots: [null] });
    const before = JSON.stringify(d.slots);
    const msg = heldRefsNotice(d, "i2v");
    assert.match(msg, /2 image refs/);
    assert.equal(JSON.stringify(d.slots), before,
      "the hold notice wrote into the priced Start/End Frame bank -- that is a spend decision");
  });

  // The pure applyMode CANNOT dispatch a DOM event (it has no DOM). The React side owns the event:
  // only userSetMode emits mg-mode-commit; the setMode wrapper (and prefill's internal gating) do
  // not, so a click -> mg-mode-commit -> host update -> prefill -> setMode -> re-dispatch loop is
  // impossible by construction. These source checks pin that the event wiring stays that way.
  const drawerSrc = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8");
  const gtCss = readFileSync(path.join(__dirname, "../../gallery/src/styles/gen-drawer.css"), "utf8");

  test("only userSetMode emits mg-mode-commit, and it passes userDriven=true", () => {
    assert.match(drawerSrc, /const userSetMode = \(m\) => \{ setMode\(m, true\); emit\("mg-mode-commit", \{ vmode: m \}\); \};/,
      "a real click on a mode button no longer commits the mode / emits its event");
    // The Model <select>'s change listener is the one path that passes userDriven to gating.
    assert.match(drawerSrc, /applyModelGating\(true\)/,
      "the user's model change no longer explains where the Multi-Reference picks went");
  });

  test("the notice element renders and is styled", () => {
    assert.match(drawerSrc, /\{s\.modeNote \? <div className="mgd-modenote">/,
      "the mode-switch notice has no element to render into");
    assert.match(gtCss, /\.gen-drawer \.mgd-modenote\{/,
      "the notice has no styling -- it would render as unreadable default-colored body text");
  });
});

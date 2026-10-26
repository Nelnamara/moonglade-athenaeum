import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  newCardShape, flat, shotText, shotPayload, shotSendBody, priceFingerprint, PRICE_FP_SKIP,
  engineOf, engineLabel, drawerModeFor, cardModeForVmode, shotModeOf, gatedEntry,
  SHOT_SETTINGS_FIELDS, shotSettingsOf, inheritedShotSettings, inheritSourceCard,
  applySettingsToAllCards, shotSendProblem, shotThumbIds, heldVideoRefsLine,
} from "../src/loom-core.js";
import { shotsFromPictures, SHOT_SECONDS } from "../src/loom-shots-core.js";
import { buildDuplicateCard, splitCardAt, importedFootagePatch, attachedVideoPatch } from "../src/loom-mutations.js";
import {
  snapshotSettings, reuseSettingsPatch, stripInFlight, mergeBoards, FRESH_CARD_CLEARS,
} from "../src/loom-takes-core.js";
import { edlPlan, CSV_HEADER } from "../src/loom-edl-core.js";
import {
  MODELS, DEFAULT_MODEL, MODEL_VMODES, SHOT_LABEL, DURATIONS, gatedShot,
} from "../../gallery/src/gen/videoDrawerCore.js";

/* ISSUE #90 -- THE SHOT KEEPS ITS ENGINE, CHANNEL AND HELPER (the pure half; SPEC_final 2026-10-26
   sections A, C, E, F, G, I, J). The owner set all twenty shots to Tsubaki and the ≈-to-finish
   total never moved: the engine lived only in the drawer, shotPayload carried none, the server
   read a blank engine as V4.0 Lite, and the price fingerprint did not name an engine at all. Here
   the card holds it, every payload states it, the fingerprint sees it, a shot its engine cannot
   take is refused before anything is priced, new shots inherit it, and one button writes it onto
   every shot -- each rule pinned against the real modules. The mounted half (the drawer refills
   on open, the commits, echo-safety) lives with the mount harness. */

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = readFileSync(path.join(here, "fixtures", "board-legacy.json"), "utf8");
const legacy = () => JSON.parse(FIXTURE);

const frame = (o = {}) => ({ thumbId: "", source: "", desc: "", tag: "", ...o });
const card = (id, o = {}) => newCardShape(id, { title: id.toUpperCase(), prompt: "she walks in", ...o });
const board = (acts, assets = []) => ({ name: "Board", target: 60, assets, acts });
const act = (id, cards) => ({ id, name: id, collapsed: false, cards });
const one = (c, assets = []) => { const p = board([act("a1", [c])], assets); return { p, e: flat(p)[0] }; };
// Every input a shot can carry, by gallery media id (no resolver needed): two frames, a cast
// picture, an image ref and a video ref.
const FULL = {
  openFrame: frame({ mediaId: "700000000000000001" }), closeFrame: frame({ mediaId: "700000000000000002" }),
  cast: ["as1"], refs: [{ id: "r1", kind: "image", tag: "@image4", mediaId: "700000000000000004", source: "" },
    { id: "v1", kind: "video", tag: "@video1", source: "700000000000000009" }],
};
const ASSETS = [{ id: "as1", kind: "image", tag: "@image1", name: "Ari", mediaId: "700000000000000003" }];
const ENGINES = MODELS.map((m) => m.value);

describe("A. the card holds its engine, Channel and helper", () => {
  test("a new shot is on no engine, Normal, helper off -- and those keys are on its shape", () => {
    const c = newCardShape("x");
    assert.equal(c.videoModel, "");
    assert.equal(c.isPrivate, false);
    assert.equal(c.videoHelper, false);
    assert.equal(newCardShape("x", { videoModel: "tbkv1.0.1" }).videoModel, "tbkv1.0.1", "extra still wins");
  });
  test("engineOf: blank, whitespace, missing or unknown read as the drawer's default; a real id is itself", () => {
    assert.equal(DEFAULT_MODEL, "v4.0.1");
    for (const v of ["", "   ", undefined, null, "v9.9", "tbkv", 42]) assert.equal(engineOf({ videoModel: v }), DEFAULT_MODEL, String(v));
    assert.equal(engineOf({}), DEFAULT_MODEL, "a card saved before the key existed");
    assert.equal(engineOf(null), DEFAULT_MODEL);
    for (const id of ENGINES) assert.equal(engineOf({ videoModel: id }), id);
    assert.equal(engineOf({ videoModel: " tbkv1.0 " }), "tbkv1.0", "padding around a real id is not a different engine");
  });
  test("engineLabel names the drawer's own label; an unknown id names the default's", () => {
    assert.equal(engineLabel("tbkv1.0.1"), "Tsubaki Video");
    assert.equal(engineLabel(""), "V4.0 Lite Preview");
    assert.equal(engineLabel("nope"), "V4.0 Lite Preview");
  });
  test("drawerModeFor / cardModeForVmode: V2V shares Multi-Reference, and r2v always comes back as R2V", () => {
    assert.deepEqual(["I2V", "FLF", "R2V", "V2V", "", undefined, "i2v"].map(drawerModeFor), ["i2v", "flf", "r2v", "r2v", "r2v", "r2v", "i2v"]);
    assert.deepEqual(["i2v", "flf", "r2v"].map(cardModeForVmode), ["I2V", "FLF", "R2V"]);
  });
});

describe("C. the payload states the engine and is sent in a mode that engine has", () => {
  test("video_model is ALWAYS explicit -- a blank, missing or unknown engine is the default by name", () => {
    for (const v of ["", undefined, "bogus"]) {
      const { p, e } = one(card("c1", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }), videoModel: v }));
      assert.equal(shotPayload(e, p, () => null).video_model, DEFAULT_MODEL, String(v));
    }
    const { p, e } = one(card("c1", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }), videoModel: "tbkv1.0.1" }));
    assert.equal(shotPayload(e, p, () => null).video_model, "tbkv1.0.1");
  });
  test("prompt_helper and is_private ride the payload; the card's POST body carries both", () => {
    const { p, e } = one(card("c1", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }), videoHelper: true, isPrivate: true }));
    const pl = shotPayload(e, p, () => null);
    assert.equal(pl.prompt_helper, true);
    assert.equal(pl.is_private, true);
    const body = shotSendBody(pl, { boardId: "b", cardId: "c1", submitId: "s" });
    assert.equal(body.video_model, DEFAULT_MODEL);
    assert.equal(body.prompt_helper, true);
    const off = one(card("c1", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }) }));
    assert.equal(shotPayload(off.e, off.p, () => null).prompt_helper, false);
  });
  test("the mode is the one the drawer's gating lands on: the card's own when its engine has it", () => {
    for (const engine of ENGINES) {
      for (const mode of ["I2V", "FLF", "R2V", "V2V"]) {
        const c = card("c1", { mode, videoModel: engine, ...FULL });
        const want = gatedShot(drawerModeFor(mode), c.duration, engine).mode;
        const sent = shotPayload(one(c, ASSETS).e, one(c, ASSETS).p, () => null).mode;
        assert.equal(drawerModeFor(sent), want, engine + " " + mode);
        // the card's own string survives whenever the engine has its drawer mode (V2V stays V2V)
        if (MODEL_VMODES[engine].includes(drawerModeFor(mode))) assert.equal(sent, mode, engine + " " + mode);
        assert.equal(shotModeOf(c), sent);
      }
    }
    // the named cases: V3.2 takes Multi-Reference to First & Last, V2.7 to First Frame
    assert.equal(shotModeOf(card("c", { mode: "R2V", videoModel: "v3.2" })), "FLF");
    assert.equal(shotModeOf(card("c", { mode: "V2V", videoModel: "v3.2" })), "FLF");
    assert.equal(shotModeOf(card("c", { mode: "R2V", videoModel: "v2.7" })), "I2V");
    assert.equal(shotModeOf(card("c", { mode: "FLF", videoModel: "v3.0.1" })), "I2V");
    assert.equal(shotModeOf(card("c", { mode: "V2V", videoModel: "tbkv1.0.1" })), "V2V");
  });
  test("gatedEntry is the SAME entry when the mode stands, and a copy carrying the gated mode when not", () => {
    const ok = one(card("c1", { mode: "R2V", videoModel: "tbkv1.0" }));
    assert.equal(gatedEntry(ok.e), ok.e);
    const moved = one(card("c1", { mode: "R2V", videoModel: "v2.7" }));
    const g = gatedEntry(moved.e);
    assert.notEqual(g, moved.e);
    assert.equal(g.c.mode, "I2V");
    assert.equal(moved.e.c.mode, "R2V", "the board's own card is never touched");
  });
  test("the images and the prompt are composed for the mode that goes out (R2V on V2.7 drops the closing frame from both)", () => {
    const c = card("c1", { mode: "R2V", videoModel: "v2.7", ...FULL });
    const { p, e } = one(c, ASSETS);
    const pl = shotPayload(e, p, () => null);
    assert.equal(pl.mode, "I2V");
    assert.ok(!pl.images.includes("700000000000000002"), "an I2V job sends no closing frame");
    assert.equal(pl.images[0], "700000000000000001");
    assert.equal(pl.prompt, shotText({ ...e, c: { ...c, mode: "I2V" } }, p, () => null), "the prompt cites the numbering the images carry");
    // and a coherent shot is byte-identical to composing from the card as it is
    const k = card("c1", { mode: "R2V", ...FULL });
    const kk = one(k, ASSETS);
    assert.equal(shotPayload(kk.e, kk.p, () => null).prompt, shotText(kk.e, kk.p, () => null));
  });
  test("video refs past the ENGINE's cap are held back (0 on Tsubaki, 3 by default) and never deleted", () => {
    const vids = [1, 2, 3, 4].map((i) => ({ id: "v" + i, kind: "video", tag: "@video" + i, source: "70000000000000001" + i }));
    const base = { mode: "R2V", refs: vids, openFrame: frame({ mediaId: "700000000000000001" }) };
    const tb = one(card("c1", { ...base, videoModel: "tbkv1.0.1" }));
    assert.deepEqual(shotPayload(tb.e, tb.p, () => null).video_refs, []);
    assert.equal(tb.e.c.refs.length, 4, "held on the card");
    const df = one(card("c1", base));
    assert.deepEqual(shotPayload(df.e, df.p, () => null).video_refs, vids.slice(0, 3).map((v) => v.source));
    // a Tsubaki shot whose only input is a video ref has nothing to send
    const only = one(card("c1", { mode: "R2V", refs: vids.slice(0, 1), videoModel: "tbkv1.0" }));
    assert.equal(shotPayload(only.e, only.p, () => null).hasInput, false);
  });
});

describe("C. shotSendProblem: a shot its engine has no road for is refused before any price or POST", () => {
  const pl = (o) => ({ mode: "R2V", images: ["1"], video_refs: [], video_model: "v4.0.1", ...o });
  test("the refused pairs, each in plain words ending the Loom's way", () => {
    const cases = [
      [pl({ mode: "R2V", video_model: "v3.2" }), /^V3\.2 has no Multi-Reference/],
      [pl({ mode: "V2V", video_model: "v2.7", images: ["1", "2"] }), /^V2\.7 \(High Dynamics\) has no Multi-Reference/],
      [pl({ mode: "FLF", images: ["1"], video_model: "v3.2" }), /^First & Last needs a start and an end frame; without both this shot goes out as Multi-Reference, which V3\.2 doesn't have/],
      [pl({ mode: "FLF", images: ["1", "2"], video_model: "v2.7" }), /^V2\.7 \(High Dynamics\) has no First & Last/],
      [pl({ mode: "I2V", images: [], video_refs: ["9"], video_model: "v3.0.1" }), /^First Frame needs a start frame; without one this shot goes out as Multi-Reference, which V3\.0 Flash doesn't have/],
      [pl({ mode: "R2V", video_refs: ["9"], video_model: "tbkv1.0.1" }), /^Tsubaki Video takes no video references, and this shot has 1/],
      [pl({ mode: "R2V", video_refs: ["7", "8", "9", "10"] }), /^V4\.0 Lite Preview takes at most 3 video references, and this shot has 4/],
    ];
    for (const [p, re] of cases) {
      const why = shotSendProblem(p);
      assert.match(why, re, JSON.stringify(p));
      assert.match(why, /Nothing was sent\.$/);
    }
  });
  test("coherent pairs pass", () => {
    assert.equal(shotSendProblem(pl({})), "");
    assert.equal(shotSendProblem(pl({ mode: "FLF", images: ["1", "2"], video_model: "v3.2" })), "");
    assert.equal(shotSendProblem(pl({ mode: "I2V", video_model: "v2.7" })), "");
    assert.equal(shotSendProblem(pl({ mode: "R2V", video_model: "tbkv1.0" })), "");
    assert.equal(shotSendProblem(pl({ mode: "FLF", images: ["1"] })), "", "one frame on V4.0 Lite rides Multi-Reference, which it has");
    assert.equal(shotSendProblem(pl({ mode: "I2V", video_refs: ["9"], video_model: "tbkv1.0.1" })), "", "an I2V job never sends its video refs");
    assert.equal(shotSendProblem(pl({ mode: "R2V", video_refs: ["7", "8", "9"] })), "");
    assert.equal(shotSendProblem(pl({ video_model: "" })), "", "a blank engine is the default's");
  });
  test("a payload with nothing to send is left to the Loom's own no-input refusal", () => {
    assert.equal(shotSendProblem(pl({ images: [], video_model: "v2.7" })), "");
    assert.equal(shotSendProblem(null), "");
  });
  test("every shotPayload a full card builds on every engine, in every mode, is sendable", () => {
    for (const engine of ENGINES) {
      for (const mode of ["I2V", "FLF", "R2V", "V2V"]) {
        const { p, e } = one(card("c1", { mode, videoModel: engine, ...FULL }), ASSETS);
        assert.equal(shotSendProblem(shotPayload(e, p, () => null)), "", engine + " " + mode);
      }
    }
  });
});

/* The issue #90 review (spend lens + sync lens): the server reads images[0] / images[1] of a First
   Frame / First & Last job as its start / end frame, whatever they are. shotPayload took the
   images from shotImageRefs in every mode, so a shot SHORT of its frames sent its cast pictures in
   their place -- reachable from every Multi-Reference shot by one engine click (V3.2 writes First &
   Last onto the card, V2.7 First Frame) -- while the drawer showed an empty frame bank and its own
   Go refused. */
describe("C. a First Frame / First & Last job sends its frames, never a cast or reference picture in their place", () => {
  const TWO_CAST = [{ id: "as1", kind: "image", tag: "@image1", name: "Ari", mediaId: "700000000000000003" },
    { id: "as2", kind: "image", tag: "@image2", name: "Bo", mediaId: "700000000000000005" }];
  const OPEN = frame({ mediaId: "700000000000000001" }), CLOSE = frame({ mediaId: "700000000000000002" });
  const sent = (o) => { const { p, e } = one(card("c1", { cast: ["as1", "as2"], ...o }), TWO_CAST); return shotPayload(e, p, () => null); };
  const FLF_SHORT = /^First & Last needs a start and an end frame; its cast and reference pictures are never sent in place of them\. Nothing was sent\.$/;
  const I2V_SHORT = /^First Frame needs a start frame; its cast and reference pictures are never sent in place of it\. Nothing was sent\.$/;
  test("an R2V shot of two cast pictures, gated onto V3.2 / V2.7 (Deep Focus's type chips, a legacy Reuse): no frame, nothing sent", () => {
    for (const [engine, mode, re] of [["v3.2", "FLF", FLF_SHORT], ["v3.0", "FLF", FLF_SHORT], ["v2.7", "I2V", I2V_SHORT], ["v3.0.1", "I2V", I2V_SHORT]]) {
      for (const own of ["R2V", "V2V"]) {
        const pl = sent({ mode: own, videoModel: engine });
        assert.equal(pl.mode, mode, engine + " " + own);
        assert.deepEqual(pl.images, [], engine + " " + own + ": neither portrait goes out as a frame");
        assert.equal(pl.held.images, 2);
        assert.match(shotSendProblem(pl), re, engine + " " + own);
      }
    }
  });
  test("the same shot after the engine pick wrote the moved type onto its card (mg-model-commit): the same refusal", () => {
    // What the host's handler writes for an R2V card when V3.2 / V2.7 is picked (its own mode, worked out by gatedShot).
    for (const [engine, re] of [["v3.2", FLF_SHORT], ["v2.7", I2V_SHORT]]) {
      const mode = cardModeForVmode(gatedShot("r2v", 5, engine).mode);
      const pl = sent({ mode, videoModel: engine });
      assert.equal(pl.mode, mode);
      assert.deepEqual(pl.images, [], engine);
      assert.match(shotSendProblem(pl), re, engine);
    }
    // ...and on an engine that has every type too: First & Last with only cast is no First & Last job
    assert.match(shotSendProblem(sent({ mode: "FLF" })), FLF_SHORT);
    assert.match(shotSendProblem(sent({ mode: "I2V", videoModel: "tbkv1.0.1" })), I2V_SHORT);
    // a video ref alongside does not make the cast a frame (it would have ridden Multi-Reference)
    assert.match(shotSendProblem(sent({ mode: "FLF", refs: [{ id: "v1", kind: "video", tag: "@video1", source: "700000000000000009" }] })), FLF_SHORT);
  });
  test("short by one: First & Last with only its opening frame sends that frame alone -- never a cast picture as its end", () => {
    const pl = sent({ mode: "FLF", openFrame: OPEN });
    assert.deepEqual(pl.images, ["700000000000000001"]);
    assert.equal(pl.held.images, 2);
    assert.equal(shotSendProblem(pl), "", "one frame rides Multi-Reference on V4.0 Lite, as the drawer's own Go sends it");
    assert.match(shotSendProblem(sent({ mode: "FLF", openFrame: OPEN, videoModel: "v3.2" })),
      /^First & Last needs a start and an end frame; without both this shot goes out as Multi-Reference, which V3\.2 doesn't have\. Nothing was sent\.$/);
  });
  test("every frame there: unchanged -- the cast follows the frames (the server reads past them)", () => {
    assert.deepEqual(sent({ mode: "FLF", openFrame: OPEN, closeFrame: CLOSE }).images,
      ["700000000000000001", "700000000000000002", "700000000000000003", "700000000000000005"]);
    assert.deepEqual(sent({ mode: "I2V", openFrame: OPEN }).images, ["700000000000000001", "700000000000000003", "700000000000000005"]);
    assert.equal(sent({ mode: "I2V", openFrame: OPEN }).held.images, 0);
    assert.deepEqual(sent({ mode: "R2V" }).images, ["700000000000000003", "700000000000000005"], "Multi-Reference: every picture, as before");
  });
  test("a GATED shot sends exactly the drawer's frame bank, even with every frame there", () => {
    const pl = sent({ mode: "R2V", videoModel: "v3.2", openFrame: OPEN, closeFrame: CLOSE });
    assert.equal(pl.mode, "FLF");
    assert.deepEqual(pl.images, ["700000000000000001", "700000000000000002"]);
    assert.equal(pl.held.images, 2);
    assert.equal(shotSendProblem(pl), "");
    const i2v = sent({ mode: "R2V", videoModel: "v2.7", openFrame: OPEN, closeFrame: CLOSE });
    assert.deepEqual(i2v.images, ["700000000000000001"], "First Frame: the opening frame alone");
  });
  test("held is client-only: never POSTed, never fingerprinted", () => {
    const pl = sent({ mode: "FLF", openFrame: OPEN });
    assert.ok(!("held" in shotSendBody(pl, { boardId: "b", cardId: "c1", submitId: "s" })));
    assert.equal(priceFingerprint(pl), priceFingerprint({ ...pl, held: { images: 0, videos: 0 } }));
  });
});

describe("C. video refs an engine can't take are HELD on the card road, as in the drawer, and said", () => {
  const VIDS = [1, 2].map((i) => ({ id: "v" + i, kind: "video", tag: "@video" + i, source: "70000000000000002" + i }));
  const PIC = { id: "r1", kind: "image", tag: "@image1", mediaId: "700000000000000004", source: "" };
  test("a Tsubaki Multi-Reference card with a picture and a video ref: sent without the ref, which stays on the card", () => {
    const { p, e } = one(card("c1", { mode: "R2V", videoModel: "tbkv1.0.1", refs: [PIC, VIDS[0]] }));
    const pl = shotPayload(e, p, () => null);
    assert.deepEqual(pl.video_refs, []);
    assert.deepEqual(pl.images, ["700000000000000004"]);
    assert.deepEqual(e.c.refs, [PIC, VIDS[0]], "held on the card, never deleted");
    assert.equal(pl.held.videos, 1);
    assert.equal(shotSendProblem(pl), "", "held, not refused -- the drawer sends it the same way");
    assert.equal(heldVideoRefsLine(pl), "Tsubaki Video takes no video references: 1 video reference on this shot is held back, not sent and not deleted.");
    assert.ok(!("held" in shotSendBody(pl, { boardId: "b", cardId: "c1", submitId: "s" })));
  });
  test("a Tsubaki card whose only input is video refs is refused in those words -- not 'attach a frame or cast image first'", () => {
    for (const mode of ["R2V", "V2V"]) {
      const { p, e } = one(card("c1", { mode, videoModel: "tbkv1.0", refs: VIDS }));
      const pl = shotPayload(e, p, () => null);
      assert.equal(pl.hasInput, false);
      assert.equal(shotSendProblem(pl), "Tsubaki Video Flash takes no video references, and this shot has 2. Nothing was sent.", mode);
    }
  });
  test("past the default cap of three: held and named the same way", () => {
    const four = [1, 2, 3, 4].map((i) => ({ id: "v" + i, kind: "video", tag: "@video" + i, source: "70000000000000003" + i }));
    const { p, e } = one(card("c1", { mode: "R2V", refs: [PIC, ...four] }));
    const pl = shotPayload(e, p, () => null);
    assert.equal(pl.video_refs.length, 3);
    assert.equal(heldVideoRefsLine(pl), "V4.0 Lite Preview takes at most 3 video references: 1 video reference on this shot is held back, not sent and not deleted.");
  });
  test("a frame-mode card's video refs are not 'held' (a First Frame job never sends them), and nothing held says nothing", () => {
    const { p, e } = one(card("c1", { mode: "I2V", videoModel: "tbkv1.0.1", openFrame: frame({ mediaId: "700000000000000001" }), refs: [VIDS[0]] }));
    const pl = shotPayload(e, p, () => null);
    assert.equal(pl.held.videos, 0);
    assert.equal(heldVideoRefsLine(pl), "");
    assert.equal(heldVideoRefsLine(null), "");
    assert.equal(heldVideoRefsLine({ video_model: "tbkv1.0.1" }), "", "a payload built elsewhere (the drawer's) holds nothing to say");
  });
});

describe("E. the price fingerprint names every payload key but the prompt and the client-only hasInput / held", () => {
  const full = () => {
    const { p, e } = one(card("c1", { mode: "R2V", audioGen: true, audioLanguage: "japanese", isPrivate: true,
      videoHelper: true, videoModel: "tbkv1.0.1", ...FULL }), ASSETS);
    p.draft = true;
    return shotPayload(e, p, () => null);
  };
  test("the skip list is exactly the drawer's rule for a Loom payload (plus its two client-only keys)", () => {
    assert.deepEqual(PRICE_FP_SKIP, ["prompt", "hasInput", "held"]);
  });
  test("STRUCTURAL: every key of a real shotPayload moves the fingerprint, or is on the skip list", () => {
    const base = full();
    const keys = Object.keys(base);
    for (const k of ["mode", "images", "video_refs", "duration", "quality", "generate_audio", "audio_language",
      "is_private", "video_model", "prompt_helper"]) assert.ok(keys.includes(k), k + " is on the payload");
    const other = (v) => (Array.isArray(v) ? v.concat(["x"]) : typeof v === "boolean" ? !v
      : typeof v === "number" ? v + 1 : String(v) + "-changed");
    for (const k of keys) {
      const moved = priceFingerprint({ ...base, [k]: other(base[k]) }) !== priceFingerprint(base);
      assert.equal(moved, !PRICE_FP_SKIP.includes(k), k + (moved ? " is skipped yet moved the fingerprint" : " is NOT fingerprinted"));
    }
    // and a key a later build adds is fingerprinted without anyone listing it
    assert.notEqual(priceFingerprint({ ...base, ratio: "16:9" }), priceFingerprint(base));
  });
  test("engine, helper and channel each move it; '' and the default engine are one fingerprint", () => {
    const fp = (o) => { const { p, e } = one(card("c1", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }), ...o })); return priceFingerprint(shotPayload(e, p, () => null)); };
    assert.equal(fp({ videoModel: "" }), fp({ videoModel: DEFAULT_MODEL }));
    assert.equal(fp({}), fp({ videoModel: DEFAULT_MODEL }), "an old card with no key prices as it always did");
    assert.notEqual(fp({ videoModel: "tbkv1.0.1" }), fp({}));
    assert.notEqual(fp({ videoHelper: true }), fp({}));
    assert.notEqual(fp({ isPrivate: true }), fp({}));
    assert.equal(fp({ prompt: "other words" }), fp({}), "typing never re-prices");
  });
});

describe("F. a new shot takes the settings of the one before it", () => {
  test("inheritedShotSettings is a whitelist of seven, never a spread of the card", () => {
    const prev = card("p", { videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true, audioGen: true,
      audioLanguage: "japanese", mode: "FLF", duration: 10, connect: "flf", camera: "dolly", ...FULL });
    const got = inheritedShotSettings(prev);
    assert.deepEqual(Object.keys(got).sort(), ["audioGen", "audioLanguage", "duration", "isPrivate", "mode", "videoHelper", "videoModel"]);
    assert.deepEqual(got, { videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true, audioGen: true,
      audioLanguage: "japanese", mode: "FLF", duration: 10 });
    assert.deepEqual(inheritedShotSettings(null), {});
    assert.deepEqual(inheritedShotSettings(undefined), {});
  });
  test("mode and duration are what the drawer shows for the previous shot (gated onto its engine)", () => {
    assert.equal(inheritedShotSettings(card("p", { videoModel: "tbkv1.0", duration: 6 })).duration, 5, "Tsubaki has no 6 s");
    assert.equal(inheritedShotSettings(card("p", { videoModel: "v2.7", duration: 15 })).duration, 10, "a 10 s engine");
    assert.equal(inheritedShotSettings(card("p", { duration: 8 })).duration, gatedShot("i2v", 8, DEFAULT_MODEL).duration);
    assert.equal(inheritedShotSettings(card("p", { mode: "R2V", videoModel: "v3.2" })).mode, "FLF");
    assert.equal(inheritedShotSettings(card("p", { mode: "V2V" })).mode, "V2V");
    // an old card reads as the defaults
    assert.deepEqual(inheritedShotSettings({ id: "old", mode: "I2V", duration: 5 }),
      { videoModel: "", isPrivate: false, videoHelper: false, audioGen: false, audioLanguage: "english", mode: "I2V", duration: 5 });
  });
  test("a new shot built from it keeps its own id, frames, cast, connect and render state", () => {
    const prev = card("p", { videoModel: "v3.2", mode: "FLF", connect: "flf", status: "done", resultMid: "1", ...FULL });
    const c = newCardShape("n", inheritedShotSettings(prev));
    assert.equal(c.id, "n");
    assert.equal(c.videoModel, "v3.2");
    assert.equal(c.mode, "FLF");
    assert.equal(c.connect, "cut");
    assert.equal(c.status, "todo");
    assert.deepEqual(c.cast, []);
    assert.deepEqual(c.openFrame, frame());
    assert.ok(!("resultMid" in c));
  });
  test("the source: the nearest preceding non-imported card, from the end of the target act, then earlier acts", () => {
    const p = board([
      act("a1", [card("c1", { videoModel: "v3.2" }), card("c2", { videoModel: "v2.7" })]),
      act("a2", [card("c3", { videoModel: "tbkv1.0" }), card("c4", { imported: true, videoModel: "v4.0" })]),
      act("a3", []),
      act("a4", [card("c5", { imported: true })]),
    ]);
    assert.equal(inheritSourceCard(p, "a2").id, "c3", "imported footage is skipped");
    assert.equal(inheritSourceCard(p, "a1").id, "c2", "the END of the target act");
    assert.equal(inheritSourceCard(p, "a3").id, "c3", "an empty act takes the one before it");
    assert.equal(inheritSourceCard(p, "a4").id, "c3", "an act of only imported footage too");
    assert.equal(inheritSourceCard(p, null).id, "c3", "no act: the end of the board");
    assert.equal(inheritSourceCard(p, "gone").id, "c3", "an act not on the board: the end of the board");
    assert.equal(inheritSourceCard(board([act("a1", [card("x", { imported: true })])]), "a1"), null);
    assert.equal(inheritSourceCard(board([]), "a1"), null);
    assert.equal(inheritSourceCard(null, "a1"), null);
  });
  test("shotsFromPictures with inherit: the five settings ride every shot; mode, 5 s, title and frame stay as built", () => {
    const pics = [{ id: "733917871331404290", prompt: "Owl on the lectern" }, { id: "733917871331404291", prompt: "" }];
    const prev = card("p", { videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true, audioGen: true,
      audioLanguage: "korean", mode: "R2V", duration: 15, connect: "extend" });
    const a = shotsFromPictures(pics, { actNumber: 2, name: "C", nonce: "n", inherit: inheritedShotSettings(prev) });
    for (const [i, c] of a.cards.entries()) {
      for (const k of SHOT_SETTINGS_FIELDS) assert.deepEqual(c[k], shotSettingsOf(prev)[k], k);
      assert.equal(c.mode, "I2V");
      assert.equal(c.duration, SHOT_SECONDS);
      assert.equal(c.connect, "cut");
      assert.equal(c.openFrame.mediaId, pics[i].id);
    }
    assert.deepEqual(a.cards.map((c) => c.title), ["Owl on the lectern", "Picture 2"]);
    // a raw card works as `inherit` too -- still only the five
    const raw = shotsFromPictures(pics, { inherit: prev }).cards[0];
    assert.equal(raw.videoModel, "tbkv1.0.1");
    assert.equal(raw.mode, "I2V");
  });
  test("shotsFromPictures without inherit: the blank shape's defaults, exactly as before", () => {
    const c = shotsFromPictures([{ id: "1", prompt: "x" }], {}).cards[0];
    const blank = newCardShape(c.id, {});
    for (const k of SHOT_SETTINGS_FIELDS) assert.deepEqual(c[k], blank[k], k);
  });
});

describe("F. the copy matrix: every road that copies a card carries the three new fields", () => {
  const set = { videoModel: "tbkv1.0", isPrivate: true, videoHelper: true };
  test("a duplicate carries them; FRESH_CARD_CLEARS does not name them", () => {
    const c = card("c1", { ...set, refs: [{ id: "r1", kind: "image", tag: "@image1", source: "" }] });
    const d = buildDuplicateCard(c, "d1", ["r9"]);
    for (const [k, v] of Object.entries(set)) assert.equal(d[k], v, k);
    for (const k of Object.keys(set)) assert.ok(!FRESH_CARD_CLEARS.includes(k), k);
  });
  test("a split's right half carries them (and the left keeps them)", () => {
    const p = board([act("a1", [card("c1", { ...set, status: "done", resultMid: "200000000000000001", trimIn: 0, trimOut: 8 })])]);
    const out = splitCardAt(p, "a1", "c1", 4, "c1b");
    const [left, right] = out.acts[0].cards;
    assert.equal(right.id, "c1b");
    for (const [k, v] of Object.entries(set)) { assert.equal(right[k], v, "right " + k); assert.equal(left[k], v, "left " + k); }
  });
  test("imported footage does not set them (the blank shape's defaults stand under the patch)", () => {
    for (const patch of [importedFootagePatch("1", 5), attachedVideoPatch("1", 5)]) {
      for (const k of Object.keys(set)) assert.ok(!(k in patch), k);
    }
  });
  test("a backup round-trips them and a copied board keeps them (exportJSON / _adoptBackup's stripInFlight)", () => {
    const p = board([act("a1", [card("c1", { ...set, status: "wip", pendingTaskId: "T" }), card("c2", set)])]);
    const back = stripInFlight(JSON.parse(JSON.stringify({ project: p })).project);
    for (const c of back.acts[0].cards) for (const [k, v] of Object.entries(set)) assert.equal(c[k], v, c.id + " " + k);
  });
  test("the EDL and its CSV are byte-identical with and without them", () => {
    const p = legacy();
    const withSet = { ...p, acts: p.acts.map((a) => ({ ...a, cards: a.cards.map((c) => ({ ...c, ...set })) })) };
    const a = edlPlan(p), b = edlPlan(withSet);
    assert.equal(b.csv.split(/\r?\n/)[0], CSV_HEADER);
    assert.equal(CSV_HEADER, "order,code,title,take,file,in,out,duration,mode,prompt");
    assert.equal(b.csv, a.csv);
    assert.equal(b.edl, a.edl);
  });
  test("the two-tab merge: a shared card keeps REMOTE's values; a local-only card kept for its footage keeps its own", () => {
    const remote = board([act("a1", [card("c1", { videoModel: "v3.2", isPrivate: false, videoHelper: false })])]);
    const local = board([act("a1", [card("c1", { videoModel: "tbkv1.0", isPrivate: true, videoHelper: true }),
      card("c9", { ...set, status: "done", resultMid: "200000000000000077",
        takes: [{ id: "t1", n: 1, mid: "200000000000000077", taskId: "T9", settings: null }], selectedTake: 1, takeSeq: 1 })])]);
    const out = mergeBoards(local, remote, {}).project;
    const c1 = out.acts[0].cards.find((c) => c.id === "c1");
    assert.deepEqual([c1.videoModel, c1.isPrivate, c1.videoHelper], ["v3.2", false, false]);
    const c9 = out.acts[0].cards.find((c) => c.id === "c9");
    assert.ok(c9, "the local-only card with a landed clip is kept");
    for (const [k, v] of Object.entries(set)) assert.equal(c9[k], v, k);
  });
});

describe("G. shotThumbIds: the thumbs a shot's payload and prompt can ask for", () => {
  const assets = [
    { id: "as1", kind: "image", tag: "@image1", name: "Ari", thumbId: "th-cast1" },
    { id: "as2", kind: "image", tag: "@image2", name: "Bo", thumbId: "th-cast2", mediaId: "" },
    { id: "as3", kind: "video", tag: "", name: "Clip", thumbId: "th-castvid" },
    { id: "as4", kind: "image", tag: "@image3", name: "Not in shot", thumbId: "th-other-cast" },
  ];
  const shot = (o) => card("c1", { cast: ["as1", "as2", "as3"],
    openFrame: frame({ thumbId: "th-open" }), closeFrame: frame({ thumbId: "th-close" }),
    refs: [{ id: "r1", kind: "image", tag: "@image5", thumbId: "th-ref1", source: "" },
      { id: "r2", kind: "video", tag: "@video1", source: "700000000000000009", thumbId: "th-refvid" }], ...o });
  test("the cast's image pictures, the image refs and both frames -- nothing of another shot's", () => {
    const p = board([act("a1", [shot({}), card("c2", { openFrame: frame({ thumbId: "th-c2" }) })])], assets);
    assert.deepEqual(shotThumbIds(flat(p)[0], p), ["th-cast1", "th-cast2", "th-ref1", "th-open", "th-close"]);
    assert.deepEqual(shotThumbIds(flat(p)[1], p), ["th-c2"]);
    assert.deepEqual(shotThumbIds({ c: card("c3") }, { assets: [] }), []);
  });
  test("PARITY: every thumb id shotPayload and shotText ask the resolver about is in the key's set, on every engine and mode", () => {
    for (const engine of ENGINES) {
      for (const mode of ["I2V", "FLF", "R2V", "V2V"]) {
        const p = board([act("a1", [shot({ mode, videoModel: engine })])], assets);
        const e = flat(p)[0];
        const asked = new Set();
        const rec = (thumbId, source) => { if (thumbId) asked.add(thumbId); return thumbId ? "data:image/jpeg;base64," + thumbId : (source || null); };
        shotPayload(e, p, rec);
        shotText(e, p, rec);
        shotText(gatedEntry(e), p, rec);
        const key = new Set(shotThumbIds(e, p));
        for (const id of asked) assert.ok(key.has(id), engine + " " + mode + ": " + id + " is asked for but not keyed");
        assert.ok(!key.has("th-other-cast") && !key.has("th-castvid"));
      }
    }
  });
});

describe("I. the take's snapshot records the engine and the helper; Reuse restores them only from a snapshot that has them", () => {
  test("snapshotSettings records the RESOLVED engine and the helper beside the channel", () => {
    const s = snapshotSettings(card("c1", { videoModel: "tbkv1.0.1", videoHelper: true, isPrivate: true }), board([]), "sent", "professional");
    assert.equal(s.videoModel, "tbkv1.0.1");
    assert.equal(s.videoHelper, true);
    assert.equal(s.isPrivate, true);
    const d = snapshotSettings(card("c1"), board([]), "sent");
    assert.equal(d.videoModel, DEFAULT_MODEL, "a card on no engine rendered on the default, by name");
    assert.equal(d.videoHelper, false);
    assert.equal(snapshotSettings({ id: "old" }, board([]), "x").videoModel, DEFAULT_MODEL);
  });
  test("Reuse settings brings the engine and helper back", () => {
    const take = { settings: snapshotSettings(card("c1", { videoModel: "v3.2", videoHelper: true }), board([]), "x"), anchor: null };
    const c = reuseSettingsPatch(card("c1", { videoModel: "tbkv1.0", videoHelper: false }), take);
    assert.equal(c.videoModel, "v3.2");
    assert.equal(c.videoHelper, true);
  });
  test("a LEGACY snapshot (recorded before the engine was) leaves the card's engine and helper alone", () => {
    const s = snapshotSettings(card("c1"), board([]), "x");
    delete s.videoModel; delete s.videoHelper;
    const c = reuseSettingsPatch(card("c1", { videoModel: "tbkv1.0", videoHelper: true, isPrivate: true }), { settings: s, anchor: null });
    assert.equal(c.videoModel, "tbkv1.0");
    assert.equal(c.videoHelper, true);
    assert.equal(c.isPrivate, false, "the channel keeps its existing rule: the snapshot always recorded it");
  });
});

describe("J. Use these settings for every shot", () => {
  const S = { model: "tbkv1.0.1", isPrivate: true, audioGen: true, audioLanguage: "japanese", videoHelper: true };
  const snapTake = (mid) => ({ status: "done", resultMid: mid, selectedTake: 1, takeSeq: 1,
    takes: [{ id: "t1", n: 1, mid, taskId: "T", settings: { mode: "I2V", audioGen: false } }] });
  const mk = () => board([
    act("a1", [card("c1", { mode: "I2V", ...FULL }), card("c2", { mode: "R2V" }), card("imp", { imported: true, status: "done", resultMid: "300000000000000001" })]),
    act("a2", [card("leg", { status: "done", resultMid: "200000000000000001" }), card("snap", snapTake("200000000000000002")),
      card("v2v", { mode: "V2V" })]),
  ]);
  test("the five settings land on every shot; mode and duration are never touched", () => {
    const p = mk();
    const out = applySettingsToAllCards(p, S);
    for (const id of ["c1", "c2", "snap", "v2v"]) {
      const c = flat(out.project).find((e) => e.c.id === id).c;
      assert.deepEqual(shotSettingsOf(c), { videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true, audioGen: true, audioLanguage: "japanese" }, id);
      const was = flat(p).find((e) => e.c.id === id).c;
      assert.equal(c.mode, was.mode);
      assert.equal(c.duration, was.duration);
    }
    assert.equal(out.shots, 6);
  });
  test("SKIPS, counted: imported footage, and a shot whose mode the engine lacks", () => {
    const p = mk();
    const out = applySettingsToAllCards(p, { ...S, model: "v3.2" });
    const by = (id) => flat(out.project).find((e) => e.c.id === id).c;
    assert.equal(by("imp"), flat(p).find((e) => e.c.id === "imp").c, "imported: the very same object");
    assert.equal(by("c2"), flat(p).find((e) => e.c.id === "c2").c, "V3.2 has no Multi-Reference: left as it is");
    assert.equal(by("v2v"), flat(p).find((e) => e.c.id === "v2v").c, "V2V is Multi-Reference too");
    assert.equal(by("c1").videoModel, "v3.2");
    assert.equal(out.imported, 1);
    assert.equal(out.modeLacking, 2);
    assert.deepEqual(out.modes, ["r2v"]);
    assert.equal(out.left, 3);
    assert.deepEqual(out.modes.map((m) => SHOT_LABEL[m]), ["Multi-Reference"]);
    assert.equal(applySettingsToAllCards(p, S).left, 1, "Tsubaki takes every mode: only the imported shot is left");
  });
  test("SKIPS, counted: a Multi-Reference shot holding video refs the engine can't take (issue #90 review)", () => {
    const vid = (i) => ({ id: "v" + i, kind: "video", tag: "@video" + i, source: "70000000000000004" + i });
    const p = board([act("a1", [
      card("v2v", { mode: "V2V", refs: [{ id: "r1", kind: "image", tag: "@image1", mediaId: "700000000000000004", source: "" }, vid(1), vid(2)] }),
      card("vonly", { mode: "R2V", refs: [vid(3)] }),
      card("i2v", { mode: "I2V", openFrame: frame({ mediaId: "700000000000000001" }), refs: [vid(4)] }),
      card("plain", { mode: "R2V", cast: ["as1"] }),
    ])], ASSETS);
    const out = applySettingsToAllCards(p, S);
    const by = (id) => flat(out.project).find((e) => e.c.id === id).c;
    const was = (id) => flat(p).find((e) => e.c.id === id).c;
    assert.equal(by("v2v"), was("v2v"), "a picture and two clips never quietly becomes a picture-only job");
    assert.equal(by("vonly"), was("vonly"));
    assert.equal(by("i2v").videoModel, "tbkv1.0.1", "a First Frame shot never sends its video refs: it moves");
    assert.equal(by("plain").videoModel, "tbkv1.0.1");
    assert.deepEqual([out.videoLacking, out.videoCap, out.left, out.changed], [2, 0, 2, 2]);
    const lite = applySettingsToAllCards(p, { ...S, model: "v4.0.1" });
    assert.deepEqual([lite.videoLacking, lite.videoCap, lite.left], [0, 3, 0], "V4.0 Lite takes three: nothing is left");
  });
  test("a ★ take with no settings snapshot keeps the card's AUDIO (the bed reads it); its engine still moves", () => {
    const out = applySettingsToAllCards(mk(), S);
    const leg = flat(out.project).find((e) => e.c.id === "leg").c;
    assert.equal(leg.videoModel, "tbkv1.0.1");
    assert.equal(leg.isPrivate, true);
    assert.equal(leg.videoHelper, true);
    assert.equal(leg.audioGen, false);
    assert.equal(leg.audioLanguage, "english");
    assert.equal(out.audioKept, 1, "only the legacy take: a snapshotted take and an unrendered shot take the audio");
    assert.equal(flat(out.project).find((e) => e.c.id === "snap").c.audioGen, true);
  });
  test("IDENTITY: an unchanged card is the same object; a changed one is a spread that keeps its frames, cast and refs", () => {
    const p = mk();
    const out = applySettingsToAllCards(p, S);
    const was = flat(p).find((e) => e.c.id === "c1").c;
    const now = flat(out.project).find((e) => e.c.id === "c1").c;
    assert.notEqual(now, was);
    for (const k of ["cast", "refs", "openFrame", "closeFrame"]) assert.equal(now[k], was[k], k + " keeps its identity");
    const again = applySettingsToAllCards(out.project, S);
    assert.equal(again.project, out.project, "nothing to change: the very same board");
    assert.equal(again.changed, 0);
    assert.equal(again.shots, 6);
    // an act none of whose cards changed keeps its identity
    const half = board([act("a1", [card("x", shotSettingsOf({ videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true, audioGen: true, audioLanguage: "japanese" }))]), act("a2", [card("y")])]);
    const h = applySettingsToAllCards(half, S);
    assert.equal(h.project.acts[0], half.acts[0]);
    assert.notEqual(h.project.acts[1], half.acts[1]);
    assert.equal(h.changed, 1);
    // ...and inside an act that DID change, a card that did not is still the same object
    const mixed = board([act("a1", [half.acts[0].cards[0], card("z")])]);
    const m = applySettingsToAllCards(mixed, S);
    assert.notEqual(m.project.acts[0], mixed.acts[0]);
    assert.equal(m.project.acts[0].cards[0], mixed.acts[0].cards[0]);
    assert.notEqual(m.project.acts[0].cards[1], mixed.acts[0].cards[1]);
  });
  test("an engine is compared through engineOf: a card on '' is already on V4.0 Lite", () => {
    const p = board([act("a1", [card("c1")])]);
    const out = applySettingsToAllCards(p, { model: DEFAULT_MODEL, isPrivate: false, audioGen: false, audioLanguage: "english", videoHelper: false });
    assert.equal(out.project, p);
    assert.equal(out.changed, 0);
    assert.equal(applySettingsToAllCards(p, { videoModel: "v3.2" }).project.acts[0].cards[0].videoModel, "v3.2", "videoModel is read in place of model");
    assert.equal(applySettingsToAllCards(p, { model: "junk" }).project, p, "an unknown engine is the default's");
  });
  test("the board it was given is never mutated", () => {
    const p = mk();
    const before = JSON.stringify(p);
    applySettingsToAllCards(p, S);
    assert.equal(JSON.stringify(p), before);
  });
});

describe("the gating rule the Loom uses is the drawer's own (the import is real, not a second roster)", () => {
  test("every MODELS x mode x DURATIONS cell: shotModeOf agrees with gatedShot", () => {
    for (const engine of ENGINES) for (const mode of ["I2V", "FLF", "R2V"]) for (const d of DURATIONS) {
      assert.equal(drawerModeFor(shotModeOf({ mode, duration: d, videoModel: engine })), gatedShot(drawerModeFor(mode), d, engine).mode);
    }
  });
});

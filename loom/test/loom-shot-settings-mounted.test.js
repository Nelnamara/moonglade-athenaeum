import { test, describe, after } from "node:test";
import assert from "node:assert/strict";
// FIRST: mount.mjs installs the fake DOM before anything loads react-dom (its gotcha 1).
import { mountLoomV2, core, act, FEvent, fetchLog } from "../test-support/mount.mjs";
import { patchCard } from "../src/loom-mutations.js";
import { gatedShot, MODELS } from "../../gallery/src/gen/videoDrawerCore.js";

/* ISSUE #90 ON THE REAL <LoomV2> (mounted, effects running -- loom/test-support/mount.mjs).

   The owner's report (2026-10-25): the Generate drawer's shot settings revert to V4.0 Lite with
   every option off, the ≈-to-finish total never moved after setting 20 shots to Tsubaki, and the
   reference image does not show until a video-type button is clicked. Measured causes: the right
   panel starts collapsed and the drawer mounts only while it is open, and the prefill effect had
   no dependency that moves when a node mounts (the MOUNT GAP); nothing recorded the engine,
   channel or helper on the shot; and a thumb-only picture selected before the bulk thumb load
   stayed missing (thumbs was not a dependency).

   What is pinned here, each on the mounted component, never on its source text:
     1. the owner's path: select a shot, click the rail's Video button, and the drawer shows the
        shot's engine, channel, helper, audio + language, length and frame with NO other
        interaction; collapse and reopen: still the shot's;
     2. a prompt typed into the drawer is flushed onto its shot AT the collapse click, and the
        new drawer after a reopen shows it;
     3. the engine / channel / helper commits write the card (and the draft) in ONE update, with
        the mode and length worked out from the CARD's mode (the leak guard), and cause exactly
        one echo prefill, which keeps the engine's mode note;
     4. "Use these settings for every shot": its confirm, cancel writes nothing, and the shot on
        screen is left the same object (zero prefills after the click);
     5. thumbs: an unrelated thumb landing refills nothing; the shot's own refills once;
     6-8 (the issue #90 review): an engine pick that moves a Multi-Reference shot's type leaves
        the card road sending no cast picture as a frame, and refusing where the drawer's Go
        would; over every engine and type, the card's road sends the drawer's images; and a
        Tsubaki shot's video refs stay HELD in the drawer, note and all, through the pick's echo. */

const FRAME = "900000000000000001";
const CAST_MID = "900000000000000002";
const THUMB = "data:image/jpeg;base64,AAAA";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const frame = (mediaId) => ({ ...core.newCardShape("x").openFrame, mediaId });
const projectOf = (acts, assets = []) => ({ name: "T", target: 480, look: "", draft: false, assets, acts });
const actOf = (id, cards) => ({ id, name: id, collapsed: false, cards });
const ASSET_MID = { id: "a1", name: "Her", kind: "image", tag: "@image1", mediaId: CAST_MID, thumbId: "", source: "", lock: true };
const ASSET_MID2 = { id: "a2", name: "Him", kind: "image", tag: "@image2", mediaId: "900000000000000003", thumbId: "", source: "", lock: true };
const VREF = { id: "v1", kind: "video", tag: "@video1", source: "900000000000000009" };

// A board that follows the host's writes the way App's setCard does (patchCard: a new card /
// act / project, every other object kept), folded in and re-rendered on demand (gotcha 5).
function boardOf(project) {
  const b = { project, calls: [], draftCalls: [] };
  b.setCard = (aId, cId, fn) => { b.calls.push({ aId, cId, fn }); };
  b.setDraftCard = (fn) => { b.draftCalls.push(fn); };
  b.card = (id) => core.flat(b.project).find((e) => e.c.id === id).c;
  b.fold = async (m) => {
    const calls = b.calls.splice(0);
    for (const { aId, cId, fn } of calls) b.project = patchCard(b.project, aId, cId, fn);
    if (calls.length) await m.rerender({ project: b.project });
    return calls.length;
  };
  return b;
}

const mounted = [];
const mount = async (o) => { const m = await mountLoomV2(o); mounted.push(m); return m; };
after(async () => { for (const m of mounted) await m.unmount(); });

/** One click on a drawer control (React's onClick listens at the root, so a bubbling click does). */
const click = async (el) => { await act(async () => { el.dispatchEvent(new FEvent("click", { bubbles: true })); }); };
const engineChip = (node, label) => node.querySelectorAll(".mgd-engchip")
  .find((c) => (c.querySelector(".mgd-englabel") || {}).textContent === label);
const channelBtn = (node, label) => node.querySelectorAll(".mgd-channel").find((b) => b.textContent === label);

/** The window.confirm answers for one test, and every question asked. */
function confirms(answer) {
  const asked = [];
  const real = globalThis.confirm;
  globalThis.confirm = (text) => { asked.push(text); return typeof answer === "function" ? answer(text) : answer; };
  return { asked, restore: () => { globalThis.confirm = real; } };
}

describe("1. the owner's path: the drawer shows the shot's own settings the moment the panel opens", () => {
  test("select a shot, click the rail's Video button: engine, channel, helper, audio, length and frame, with no other click; collapse + reopen: still the shot's", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "I2V", duration: 12, prompt: "she walks in",
      audioGen: true, audioLanguage: "japanese", videoModel: "tbkv1.0.1", isPrivate: true, videoHelper: true,
      openFrame: frame(FRAME) });
    const project = projectOf([actOf("act1", [c1])]);
    const m = await mount({ project, selShot: "c1" });
    assert.equal(m.node, null, "the panel starts collapsed: no drawer yet");
    const want = gatedShot("i2v", 12, "tbkv1.0.1");     // Tsubaki takes 5/10/15 s: 12 is snapped
    const shows = (node, when) => {
      const p = node.payload();
      assert.equal(p.video_model, "tbkv1.0.1", when + ": the shot's engine, not V4.0 Lite");
      assert.equal(p.is_private, true, when + ": the shot's Private channel");
      assert.equal(p.prompt_helper, true, when + ": the shot's prompt helper");
      assert.equal(p.audio, true, when + ": the shot's audio");
      assert.equal(p.audio_language, "japanese", when + ": the shot's audio language");
      assert.equal(p.mode, "I2V", when + ": the shot's type");
      assert.equal(p.duration, want.duration, when + ": the shot's length, as the engine takes it");
      assert.deepEqual(p.images, [FRAME], when + ": the shot's opening frame is in the bank");
      assert.match(node.promptText(), /she walks in/, when + ": the shot's composed prompt");
    };
    const before = m.prefillCalls.length;
    const first = await m.openPanel("Video");
    assert.equal(m.prefillCalls.length - before, 1, "opening the panel fills the new drawer exactly once");
    shows(first, "first open");
    await m.collapse();
    const again = m.prefillCalls.length;
    const second = await m.openPanel("Video");
    assert.notEqual(second, first, "a reopen is a NEW drawer node");
    assert.equal(m.prefillCalls.length - again, 1, "the reopened drawer is filled exactly once");
    shows(second, "after collapse and reopen");
    assert.equal(fetchLog.calls.filter((c) => c.path === "/api/loom/generate").length, 0, "nothing was sent");
  });

  test("the drawer is always TOLD the engine: none chosen, or an id the roster does not list, is the default it renders on", async () => {
    for (const videoModel of ["", "  ", "no-such-engine"]) {
      const c1 = core.newCardShape("c1", { title: "Shot one", mode: "I2V", duration: 5, openFrame: frame(FRAME), videoModel });
      const m = await mount({ project: projectOf([actOf("act1", [c1])]), selShot: "c1" });
      const node = await m.openPanel("Video");
      const sent = m.prefillCalls[m.prefillCalls.length - 1];
      assert.equal(sent.video_model, "v4.0.1", JSON.stringify(videoModel) + ": stated outright, never a raw unknown string");
      assert.equal(node.payload().video_model, "v4.0.1");
    }
  });
});

describe("2. a prompt typed into the drawer survives a collapse", () => {
  test("the collapse click flushes it onto its shot at once; the reopened drawer shows it", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1"], prompt: "two figures" });
    const b = boardOf(projectOf([actOf("act1", [c1])], [ASSET_MID]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    const ce = node.querySelector(".mgd-ce");
    await act(async () => { ce.textContent = "my own words for this shot"; ce.dispatchEvent(new FEvent("input", { bubbles: true })); });
    assert.equal(b.calls.length, 0, "inside the drawer's 300 ms debounce: nothing written yet");
    const panel = m.container.querySelectorAll(".lv-panel").find((p) => p.classList.contains("right"));
    await click(panel.querySelector(".lv-col"));
    assert.equal(b.calls.length, 1, "the collapse click itself wrote the pending edit (not the debounce, 300 ms later)");
    const written = b.calls[0].fn(b.card("c1"));
    assert.equal(written.promptOverride, true);
    assert.equal(written.promptOverrideText, "my own words for this shot");
    await act(async () => { await sleep(420); });
    assert.equal(m.node, null, "the panel collapsed");
    assert.equal(b.calls.length, 1, "and the edit was written once");
    await b.fold(m);
    const reopened = await m.openPanel("Video");
    assert.notEqual(reopened, node);
    assert.equal(reopened.promptText(), "my own words for this shot", "the new drawer shows the text typed into the old one");
    assert.equal(b.calls.length, 0, "the refill wrote nothing back");
  });
});

describe("3. the engine, channel and helper commits write the shot", () => {
  test("an engine pick that drops the shot's mode: ONE card update (engine, gated length, mode), then ONE echo that keeps the note", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 15, cast: ["a1"], prompt: "two figures" });
    const b = boardOf(projectOf([actOf("act1", [c1])], [ASSET_MID]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    assert.equal(node.mode, "r2v");
    await click(engineChip(node, "V3.2"));
    assert.equal(b.calls.length, 1, "one update for the pick");
    const next = b.calls[0].fn(b.card("c1"));
    assert.equal(next.videoModel, "v3.2");
    assert.equal(next.duration, 10, "V3.2's 10 s cap");
    assert.equal(next.mode, "FLF", "V3.2 has no Multi-Reference: the card moves to the mode the drawer landed on");
    const echoFrom = m.prefillCalls.length;
    assert.equal(await b.fold(m), 1);
    const echoes = m.prefillCalls.slice(echoFrom);
    assert.equal(echoes.length, 1, "exactly one echo prefill");
    assert.equal(echoes[0].same_shot, true, "the echo is for the shot the drawer already shows");
    assert.equal(echoes[0].video_model, "v3.2");
    assert.equal(echoes[0].mode, "flf");
    assert.match(m.container.textContent, /V3\.2 has no Multi-Reference, so the shot mode switched/,
      "the echo kept the engine's note");
    assert.equal(b.calls.length, 0, "the echo wrote nothing back (no loop)");
  });

  test("the leak guard: a drawer gated to First & Last by a prefill never writes FLF onto the R2V shot", async () => {
    // An R2V shot on V3.2 (its type set in Deep Focus after its engine): the drawer shows it as
    // First & Last. Picking an engine that HAS Multi-Reference must leave the card R2V.
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1"], videoModel: "v3.2" });
    const b = boardOf(projectOf([actOf("act1", [c1])], [ASSET_MID]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    assert.equal(node.mode, "flf", "the drawer gated the shot onto V3.2's First & Last");
    await click(engineChip(node, "V4.0 Lite Preview"));
    assert.equal(node.mode, "flf", "the drawer's own mode did not move (First & Last is on V4.0 Lite too)");
    assert.equal(b.calls.length, 1);
    const next = b.calls[0].fn(b.card("c1"));
    assert.equal(next.videoModel, "v4.0.1");
    assert.equal(next.mode, "R2V", "worked out from the CARD's mode, never the drawer's");
    await b.fold(m);
    assert.equal(node.mode, "r2v", "the echo puts the drawer back in the shot's own mode");
    assert.deepEqual(node.payload().images, [CAST_MID], "with the shot's own bank");
  });

  test("Channel and helper: one update each, from the owner's own click; the draft is written the same way", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "I2V", duration: 5, openFrame: frame(FRAME) });
    const b = boardOf(projectOf([actOf("act1", [c1])]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard, setDraftCard: b.setDraftCard });
    const node = await m.openPanel("Video");
    await click(channelBtn(node, "Private"));
    assert.equal(b.calls.length, 1);
    assert.equal(b.calls[0].fn(b.card("c1")).isPrivate, true);
    await b.fold(m);
    const helper = node.querySelector("input.mgd-helper");
    // React routes a checkbox's onChange through the click only when the node's `type` PROPERTY
    // says checkbox; a real input reflects the attribute there, the fake DOM keeps attributes
    // only (mount.mjs gotcha 8 sets `checked`, and needs this too).
    helper.type = helper.getAttribute("type");
    helper.checked = !helper.checked;
    await click(helper);
    assert.equal(b.calls.length, 1);
    assert.equal(b.calls[0].fn(b.card("c1")).videoHelper, true);
    await b.fold(m);
    assert.equal(b.draftCalls.length, 0, "a shot is selected: the draft is untouched");
    // No shot selected: the draft card is what the drawer is bound to.
    await m.rerender({ selShot: null });
    await m.dispatch("mg-model-commit", { model: "tbkv1.0.1", duration: 6 });
    assert.equal(b.calls.length, 0, "no board card written for a draft commit");
    assert.equal(b.draftCalls.length, 1);
    const draft = b.draftCalls[0](m.props().draftCard);
    assert.equal(draft.videoModel, "tbkv1.0.1");
    assert.equal(draft.duration, gatedShot("i2v", 6, "tbkv1.0.1").duration, "the length as Tsubaki takes it");
  });
});

describe("4. \"Use these settings for every shot\"", () => {
  const settingsCard = { videoModel: "tbkv1.0.1", isPrivate: true, audioGen: true, audioLanguage: "japanese", videoHelper: false };
  const board = () => boardOf(projectOf([
    actOf("act1", [
      core.newCardShape("c1", { title: "One", mode: "R2V", duration: 5, cast: ["a1"], ...settingsCard }),
      core.newCardShape("c2", { title: "Two", mode: "I2V", duration: 5 }),
      core.newCardShape("c3", { title: "Borrowed", mode: "I2V", imported: true, status: "done", resultMid: "800000000000000001" }),
    ]),
    actOf("act2", [core.newCardShape("c4", { title: "Four", mode: "FLF", duration: 5 })]),
  ], [ASSET_MID]));

  test("asks once, in the drawer's words; writes the other shots; the shot on screen stays the same object (zero prefills)", async () => {
    const b = board();
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    const q = confirms(true);
    try {
      const shown = b.card("c1");
      const before = m.prefillCalls.length;
      await click(node.querySelector(".mgd-applyall"));
      assert.deepEqual(q.asked, ["Use Tsubaki Video, Private, audio on (Japanese), helper off for all 4 shots? 1 shot is left as it is (imported)."]);
      assert.deepEqual(b.calls.map((x) => x.cId), ["c2", "c4"], "the imported clip and the shot already on these settings are not written");
      await b.fold(m);
      assert.equal(b.card("c1"), shown, "the shot on screen is the same object");
      for (const id of ["c2", "c4"]) {
        const c = b.card(id);
        assert.deepEqual([c.videoModel, c.isPrivate, c.audioGen, c.audioLanguage, c.videoHelper], ["tbkv1.0.1", true, true, "japanese", false], id);
      }
      assert.equal(b.card("c2").mode, "I2V", "mode is never touched");
      assert.equal(b.card("c4").mode, "FLF");
      assert.equal(m.prefillCalls.length - before, 0, "nothing to echo: the drawer was not refilled");
      assert.equal(fetchLog.calls.filter((c) => c.path === "/api/loom/generate").length, 0, "nothing sent");
    } finally { q.restore(); }
  });

  test("Cancel writes nothing", async () => {
    const b = board();
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    const q = confirms(false);
    try {
      await click(node.querySelector(".mgd-applyall"));
      assert.equal(q.asked.length, 1);
      assert.equal(b.calls.length, 0);
    } finally { q.restore(); }
  });

  test("an engine without the shots' mode: they are counted and named in the question, and left as they are", async () => {
    const b = board();
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    await m.openPanel("Video");
    const q = confirms(true);
    try {
      await m.dispatch("mg-apply-all-request", { model: "v2.7", isPrivate: false, audioGen: false, audioLanguage: "english", videoHelper: true });
      assert.deepEqual(q.asked, ["Use V2.7 (High Dynamics), Normal, audio off, helper on for all 4 shots? "
        + "3 shots are left as they are (imported, or their engine has no Multi-Reference or First & Last)."]);
      assert.deepEqual(b.calls.map((x) => x.cId), ["c2"], "only the First Frame shot can go to V2.7");
    } finally { q.restore(); }
  });

  test("Tsubaki and a Multi-Reference shot holding video refs: left as it is, and the question says why (issue #90 review)", async () => {
    const pic = { id: "r1", kind: "image", tag: "@image1", mediaId: FRAME, source: "" };
    const b = boardOf(projectOf([actOf("act1", [
      core.newCardShape("c1", { title: "One", mode: "R2V", duration: 5, cast: ["a1"] }),
      core.newCardShape("c2", { title: "Two", mode: "V2V", duration: 5, refs: [pic, VREF, { ...VREF, id: "v2", tag: "@video2", source: "900000000000000008" }] }),
    ])], [ASSET_MID]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    await m.openPanel("Video");
    const q = confirms(true);
    try {
      await m.dispatch("mg-apply-all-request", { model: "tbkv1.0.1", isPrivate: false, audioGen: false, audioLanguage: "english", videoHelper: false });
      assert.deepEqual(q.asked, ["Use Tsubaki Video, Normal, audio off, helper off for all 2 shots? "
        + "1 shot is left as it is (their engine takes no video references)."]);
      assert.deepEqual(b.calls.map((x) => x.cId), ["c1"], "a picture and two clips never quietly becomes a picture-only job");
    } finally { q.restore(); }
  });
});

describe("5. the shot's own thumbnails landing refill the drawer; an unrelated one does not", () => {
  test("unrelated thumb: 0 prefills; the shot's own cast thumb: exactly 1, and the bank holds it", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1"], prompt: "two figures" });
    const asset = { id: "a1", name: "Her", kind: "image", tag: "@image1", mediaId: "", thumbId: "T1", source: "her.png", lock: true };
    const m = await mount({ project: projectOf([actOf("act1", [c1])], [asset]), selShot: "c1", thumbs: {} });
    const node = await m.openPanel("Video");
    assert.deepEqual(node.payload().images, [], "the thumb has not landed yet");
    const n0 = m.prefillCalls.length;
    await m.rerender({ thumbs: { T9: THUMB } });
    assert.equal(m.prefillCalls.length - n0, 0, "another shot's thumb refills nothing");
    await m.rerender({ thumbs: { T9: THUMB, T1: THUMB } });
    assert.equal(m.prefillCalls.length - n0, 1, "this shot's own thumb refills it once");
    assert.deepEqual(node.payload().images, [THUMB], "and the bank holds the picture");
  });
});

// The images the server reads off a card payload (backup.py build_shot_video_params): First Frame
// its first, First & Last with two its first two, anything else every one (Multi-Reference).
const roadImages = (pl) => (pl.mode === "I2V" && pl.images.length ? pl.images.slice(0, 1)
  : pl.mode === "FLF" && pl.images.length >= 2 ? pl.images.slice(0, 2) : pl.images);
const OPEN = frame(FRAME);
const CLOSE = frame("900000000000000004");
const FLF_SHORT = /^First & Last needs a start and an end frame; its cast and reference pictures are never sent in place of them\. Nothing was sent\.$/;
const I2V_SHORT = /^First Frame needs a start frame; its cast and reference pictures are never sent in place of it\. Nothing was sent\.$/;

describe("6. an engine pick that moves a Multi-Reference shot's type: no cast picture goes out as a frame", () => {
  test("R2V of two cast pictures, V3.2 / V2.7 picked: the card it writes is refused on the card road, and its images are the drawer's", async () => {
    for (const [label, mode, re] of [["V3.2", "FLF", FLF_SHORT], ["V2.7 (High Dynamics)", "I2V", I2V_SHORT]]) {
      const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1", "a2"], prompt: "two figures" });
      const b = boardOf(projectOf([actOf("act1", [c1])], [ASSET_MID, ASSET_MID2]));
      const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
      const node = await m.openPanel("Video");
      await click(engineChip(node, label));
      assert.equal(await b.fold(m), 1, label + ": the pick wrote the card");
      assert.equal(b.card("c1").mode, mode, label + ": the card's own type moved");
      const pl = core.shotPayload(core.flat(b.project)[0], b.project, () => null);
      assert.equal(pl.mode, mode);
      assert.deepEqual(pl.images, [], label + ": neither portrait goes out as a frame (it used to send C1 -> C2)");
      assert.deepEqual(node.payload().images, pl.images, label + ": the card's images are the drawer's bank");
      assert.match(core.shotSendProblem(pl), re, label + ": refused, as the drawer's Go refuses");
    }
  });
});

describe("7. DIFFERENTIAL: on every engine and type, the card's road sends the drawer's images", () => {
  const SETS = {
    "two cast pictures, no frame": { cast: ["a1", "a2"] },
    "both frames and two cast pictures": { cast: ["a1", "a2"], openFrame: OPEN, closeFrame: CLOSE },
    "the opening frame and two cast pictures": { cast: ["a1", "a2"], openFrame: OPEN },
  };
  for (const [name, set] of Object.entries(SETS)) {
    test(name, async () => {
      let project = projectOf([actOf("act1", [core.newCardShape("c1", { title: "Shot one", duration: 5, prompt: "x", ...set })])], [ASSET_MID, ASSET_MID2]);
      const m = await mount({ project, selShot: "c1" });
      const node = await m.openPanel("Video");
      for (const engine of MODELS.map((x) => x.value)) {
        for (const mode of ["I2V", "FLF", "R2V", "V2V"]) {
          project = patchCard(project, "act1", "c1", (c) => ({ ...c, mode, videoModel: engine }));
          await m.rerender({ project });
          const where = mode + " on " + engine;
          const pl = core.shotPayload(core.flat(project)[0], project, () => null);
          assert.equal(node.mode, core.drawerModeFor(pl.mode), where + ": the drawer shows the type the card sends");
          assert.deepEqual(roadImages(pl), node.payload().images, where + ": the server reads the drawer's images off the card");
          if (!pl.images.length && pl.held.images) assert.match(core.shotSendProblem(pl), pl.mode === "FLF" ? FLF_SHORT : I2V_SHORT, where);
        }
      }
    });
  }
});

describe("8. Tsubaki holds a shot's video refs in the drawer, and says so, through the echo of the pick", () => {
  const NOTE = /Tsubaki Video takes no video references\. Still held: 1 video ref\. Nothing was deleted\./;
  test("R2V of a picture and a video ref, Tsubaki picked: the one echo hands the drawer the ref, and the note survives it", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1"], refs: [VREF], prompt: "x" });
    const b = boardOf(projectOf([actOf("act1", [c1])], [ASSET_MID]));
    const m = await mount({ project: b.project, selShot: "c1", setCard: b.setCard });
    const node = await m.openPanel("Video");
    assert.equal(node.payload().video_refs.length, 1, "on V4.0 Lite the ref goes out");
    await click(engineChip(node, "Tsubaki Video"));
    assert.match(m.container.textContent, NOTE, "the pick raised the drawer's note");
    const from = m.prefillCalls.length;
    assert.equal(await b.fold(m), 1);
    const echo = m.prefillCalls.slice(from);
    assert.equal(echo.length, 1, "one echo");
    assert.equal(echo[0].video_model, "tbkv1.0.1");
    assert.equal(echo[0].video_refs.length, 1, "the echo hands over the shot's ref at the bank's size, not Tsubaki's cap of none");
    assert.match(m.container.textContent, NOTE, "the note survives the echo");
    assert.deepEqual(node.payload().video_refs, [], "held: out of the drawer's payload");
    const pl = core.shotPayload(core.flat(b.project)[0], b.project, () => null);
    assert.deepEqual(pl.video_refs, node.payload().video_refs, "the card's road sends what the drawer sends");
    assert.equal(pl.held.videos, 1, "and knows what it holds, for the spend asks");
    assert.deepEqual(b.card("c1").refs, [VREF], "never deleted");
  });
  test("a shot already on Tsubaki opens with its video ref held and the note up", async () => {
    const c1 = core.newCardShape("c1", { title: "Shot one", mode: "R2V", duration: 5, cast: ["a1"], refs: [VREF], videoModel: "tbkv1.0.1" });
    const m = await mount({ project: projectOf([actOf("act1", [c1])], [ASSET_MID]), selShot: "c1" });
    const node = await m.openPanel("Video");
    assert.equal(m.prefillCalls[m.prefillCalls.length - 1].video_refs.length, 1);
    assert.match(m.container.textContent, NOTE);
    assert.deepEqual(node.payload().video_refs, []);
  });
});

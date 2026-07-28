import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { shotImageRefs, positionTag, pickTarget, shotText, flat } from "../src/loom-core.js";

/* M35 -- pickTarget() stored an "@imageN" with no relation to the shot, and that number
   reached the model as a citation. The same un-synced-@imageN-numbering bug class
   loom-core.js's FRAME RESERVATION comment already counts three prior manifestations of
   (commits 2e714fd, c7aaff2, and the frame reservation itself), arriving this time through
   the append branch of a picker pick.

   shotImageRefs() stamps an UNTAGGED open/close frame with the structural fallback tags
   "@image8"/"@image9" so an FLF shot's two frames can never collide on one literal. Those
   numbers are invented for one render pass: nothing is written back to the frame, and no
   ordering depends on them (frames rank by KIND). But pickTarget() fed the whole item list to
   nextTag(items, "@image") to get "the next tag past everything this shot already uses", so
   the invented 8/9 counted as claims: an FLF shot with two untagged frames plus one "@image1"
   cast member -- 3 real images -- stored its 4th picked reference as "@image10".

   Two distinct harms, and the first repair closed neither:
     (a) the stored tag was numerically disconnected from the shot -- the shot's 4th image
         should read "@image4", by position;
     (b) it LEAKS. shotText() fell back to a ref's raw .tag whenever positionTag() had no live
         slot to give it (momentarily unresolvable, or trimmed past PixAI's real 6-image cap),
         so the composed prompt cited a picture the shot does not have.
   Filtering the invented tags back out of the max only changed the wrong number: "@image2" on
   the finding's own fixture, which is a number that shot really does use (the Closing Frame).
   An out-of-range "@image10" is noise a model drops; an in-range "@image2" is an instruction
   it follows, aimed at the wrong picture -- strictly the worse half of the hazard loom-core's
   header says the whole positional-numbering design exists to prevent.

   FIX, in two parts:
     - ordering stops depending on the appended ref's own tag (REF ORDER: refs rank behind
       cast by KIND and keep c.refs array order), which frees pickTarget() to store the ref's
       REAL position -- bumped up only to avoid displaying a number another entity on the card
       already shows, the same guard pickVideoTarget() has always had for the video bank;
     - shotText() never cites a raw .tag for an image ref with no live slot. */

const imgSrc = () => null;   // every fixture image below already carries a mediaId

function makeFlfProject({ openTag = "", closeTag = "", assets, cast, refs } = {}) {
  return {
    name: "Test", target: 60, look: "",
    assets: assets || [{ id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "mid-nel", lock: false }],
    acts: [{ id: "a1", name: "Act", cards: [{
      id: "shot1", title: "A-01", mode: "FLF", duration: 5, connect: "flf",
      prompt: "the two of them at dawn",
      camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
      cast: cast || ["nel"], refs: refs || [],
      openFrame:  { thumbId: "", source: "", desc: "wide establishing", mediaId: "mid-open",  tag: openTag },
      closeFrame: { thumbId: "", source: "", desc: "close on faces",    mediaId: "mid-close", tag: closeTag },
      promptOverride: false, promptOverrideText: "",
    }] }],
  };
}

// Exactly what master-storyboard.jsx's mg-pick-request listener does with an "append" plan.
const applyAppend = (project, plan, patch) => {
  const card = project.acts[0].cards[0];
  card.refs = [...card.refs, { id: "r-new", kind: "image", tag: plan.tag, role: "", source: "", thumbId: "", mediaId: "", ...patch }];
  return flat(project)[0];
};

describe("M35 -- an appended pick is tagged by its real position, never by an inflated max", () => {
  test("the finding's own fixture: the shot's 4th image is stored @image4, not @image10 and not @image2", () => {
    const project = makeFlfProject();
    const entry = flat(project)[0];
    const items = shotImageRefs(entry, project, imgSrc);
    // 3 real images: both frames (reserved first, by kind) and one cast member.
    assert.deepEqual(items.map((it) => it.id), ["openFrame", "closeFrame", "nel"]);
    const plan = pickTarget(entry, project, imgSrc, 3);
    assert.equal(plan.type, "append");
    assert.equal(plan.tag, "@image4");
    assert.notEqual(plan.tag, "@image10", "the invented frame fallbacks must not be counted as claims");
    assert.notEqual(plan.tag, "@image2", "@image2 is the Closing Frame's live slot -- an in-range number aimed at the wrong picture");
  });

  test("the stored tag and the LIVE positional tag agree once the pick is written -- the whole point", () => {
    const project = makeFlfProject();
    const plan = pickTarget(flat(project)[0], project, imgSrc, 3);
    const entry = applyAppend(project, plan, { mediaId: "mid-new" });
    assert.deepEqual(shotImageRefs(entry, project, imgSrc).map((it) => it.id),
      ["openFrame", "closeFrame", "nel", "r-new"]);
    assert.equal(positionTag(entry, project, imgSrc, "r-new"), plan.tag,
      "the tag the host durably stores must be the number the drawer and the prompt both show");
  });

  test("a ref with no live slot cites NO @imageN at all -- the leak the finding is about", () => {
    // The ref has no resolvable picture right now, so shotText() has no live position for it.
    // Whatever it stores, it must not put a number into a prompt that already numbers other
    // pictures: "@image2" here is the Closing Frame, so the citation would name a real image
    // that is not the one the ref means.
    const project = makeFlfProject();
    const plan = pickTarget(flat(project)[0], project, imgSrc, 3);
    const entry = applyAppend(project, plan, { role: "the locket" });
    assert.equal(positionTag(entry, project, imgSrc, "r-new"), null, "fixture sanity: no live slot to number");
    const text = shotText(entry, project, imgSrc);
    // Not "cited without a number" -- not cited AT ALL. The composed prompt is sent to PixAI,
    // so a line announcing a missing reference is noise in a generation request; the board card
    // is where an unattached reference belongs (the same rule castMissingImages applies to cast).
    const line = text.split("\n").find((l) => l.includes("the locket"));
    assert.equal(line, undefined,
      `an unresolvable ref must not reach the prompt at all, got: ${line}`);
    // And nothing anywhere in the prompt claims a picture twice.
    const cited = text.match(/@image\d+/g) || [];
    assert.deepEqual(cited, [...new Set(cited)], "no @imageN may be cited for two different things in one prompt");
  });

  test("a ref trimmed by the real 6-image cap is not cited, rather than citing a slot it lost", () => {
    // 6 cast members + 2 frames = 8 resolvable images; the cap keeps 6, and this ref -- which
    // DOES have a picture the owner chose -- is one of the ones dropped.
    const assets = [], cast = [];
    for (let i = 1; i <= 6; i++) {
      assets.push({ id: `c${i}`, name: `Cast ${i}`, kind: "image", tag: `@image${i}`, mediaId: `mid-c${i}`, lock: false });
      cast.push(`c${i}`);
    }
    const project = makeFlfProject({ assets, cast,
      refs: [{ id: "r-new", kind: "image", tag: "@image9", role: "the locket", source: "", thumbId: "", mediaId: "mid-locket" }] });
    const entry = flat(project)[0];
    assert.equal(shotImageRefs(entry, project, imgSrc).length, 6, "fixture sanity: the cap is what drops it");
    assert.equal(positionTag(entry, project, imgSrc, "r-new"), null);
    const line = shotText(entry, project, imgSrc).split("\n").find((l) => l.includes("the locket"));
    assert.equal(line, undefined,
      "a ref the 6-image cap dropped is not being sent, so the prompt must not name it either");
  });

  test("a VIDEO ref keeps citing its own @videoN -- a separate namespace nothing renumbers", () => {
    const project = makeFlfProject({
      refs: [{ id: "v1", kind: "video", tag: "@video1", role: "the chase plate", source: "9001", thumbId: "", mediaId: "" }] });
    const line = shotText(flat(project)[0], project, imgSrc).split("\n").find((l) => l.includes("the chase plate"));
    assert.match(line, /@video1 — the chase plate/);
  });
});

describe("M35 -- regressions the first repair introduced, pinned so they cannot come back", () => {
  test("two image refs on one card never end up displaying the same @imageN", () => {
    // "+ reference" in Deep Focus creates a ref with an empty source/mediaId (buildNewRef),
    // so it is absent from shotImageRefs() while still showing its tag on screen. Computing
    // the appended tag off the resolvable items alone handed the next pick that same tag.
    const project = makeFlfProject({ assets: [], cast: [],
      refs: [{ id: "r-old", kind: "image", tag: "@image1", role: "", source: "", thumbId: "", mediaId: "" }] });
    const entry = flat(project)[0];
    const plan = pickTarget(entry, project, imgSrc, shotImageRefs(entry, project, imgSrc).length);
    const after = applyAppend(project, plan, { mediaId: "mid-new" });
    const tags = after.c.refs.filter((r) => r.kind === "image").map((r) => r.tag);
    assert.deepEqual(tags, [...new Set(tags)], `two refs share a tag: ${tags.join(", ")}`);
    assert.notEqual(plan.tag, "@image1");
  });

  test("the same guard with nothing else in the shot -- the bump is what keeps the tag unique", () => {
    const project = makeFlfProject({ assets: [], cast: [],
      refs: [{ id: "r-old", kind: "image", tag: "@image1", role: "", source: "", thumbId: "", mediaId: "" }] });
    const card = project.acts[0].cards[0];
    card.openFrame = { thumbId: "", source: "", desc: "", mediaId: "", tag: "" };
    card.closeFrame = { thumbId: "", source: "", desc: "", mediaId: "", tag: "" };
    // Position 1 is free, but @image1 is already on screen for r-old, so the pick takes @image2.
    assert.equal(pickTarget(flat(project)[0], project, imgSrc, 0).tag, "@image2");
  });

  test("the picture lands in the slot the drawer reported, even past an owner-typed non-@image tag", () => {
    // Ref tags are free-text (Deep Focus's tag input). "ref3" claims nothing in the @imageN
    // namespace, but the old ordering read a bare `(\d+)` out of it and gave it slot 3, so an
    // appended pick sorted AHEAD of it and the picture appeared one slot up from the one the
    // owner clicked. Ordering no longer looks at the appended ref's tag at all.
    const project = makeFlfProject({ assets: [], cast: [],
      refs: [{ id: "r-old", kind: "image", tag: "ref3", role: "", source: "", thumbId: "", mediaId: "mid-old" }] });
    const plan = pickTarget(flat(project)[0], project, imgSrc, 3);
    const entry = applyAppend(project, plan, { mediaId: "mid-new" });
    const items = shotImageRefs(entry, project, imgSrc);
    assert.equal(items.findIndex((it) => it.id === "r-new"), 3, "the pick must land in slot 3, the slot the drawer asked for");
    assert.equal(positionTag(entry, project, imgSrc, "r-new"), plan.tag);
  });
});

describe("M35 -- what must NOT change", () => {
  test("an appended ref still never reuses a number a cast member is showing", () => {
    // Pinned since the picker-persistence pass: project-global cast tags run to @image4 here,
    // so the shot's 3rd position is bumped past both of them rather than doubling one up.
    const project = makeFlfProject({
      assets: [
        { id: "nel",  name: "Nelnamara", kind: "image", tag: "@image3", mediaId: "mid-nel",  lock: false },
        { id: "greg", name: "Greg",      kind: "image", tag: "@image4", mediaId: "mid-greg", lock: false },
      ],
      cast: ["nel", "greg"],
    });
    const card = project.acts[0].cards[0];
    card.openFrame = { thumbId: "", source: "", desc: "", mediaId: "", tag: "" };
    card.closeFrame = { thumbId: "", source: "", desc: "", mediaId: "", tag: "" };
    assert.deepEqual(pickTarget(flat(project)[0], project, imgSrc, 2), { type: "append", tag: "@image5" });
  });

  test("a frame's REAL owner-typed tag is honoured as a claim, not as a floor", () => {
    // The Opening Frame carries a real "@image8" the owner typed into FrameSlot's tag input.
    // The appended ref takes its own position (@image4) -- 8 is not a number it has to climb
    // past, only one it must not duplicate.
    const project = makeFlfProject({ openTag: "@image8" });
    const plan = pickTarget(flat(project)[0], project, imgSrc, 3);
    assert.equal(plan.tag, "@image4");
    assert.notEqual(plan.tag, "@image8", "a number the Opening Frame is already showing");
    const entry = applyAppend(project, plan, { mediaId: "mid-new" });
    assert.equal(positionTag(entry, project, imgSrc, "r-new"), "@image4");
  });

  test("FRAME RESERVATION survives: frames still take the first slots regardless of any tag", () => {
    const project = makeFlfProject({ openTag: "@image7", closeTag: "@image9" });
    const entry = flat(project)[0];
    assert.equal(positionTag(entry, project, imgSrc, "openFrame"), "@image1");
    assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), "@image2");
    assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image3");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { shotImageRefs, positionTag, shotPayload, castMissingImages, shotText, flat } from "../src/loom-core.js";

/* CLOSING-FRAME PARTICIPATION -- the FIFTH manifestation of loom-core.js's un-synced-
   @imageN-numbering bug class (see shotImageRefs()'s FRAME RESERVATION / REF ORDER comments
   for the third and fourth).

   shotImageRefs() gated the closing frame on `c.mode === "FLF"` alone, but the server
   builds R2V and V2V payloads through the exact same buildShotPayload() -> shotImageRefs()
   route (CHANGELOG: both resolve to build_shot_video_params; the owner confirms end-frame
   reference works on V4.0). On the owner's own repro -- an R2V shot with both frames
   attached and two cast members -- that one gate produced every reported symptom at once:

     * the card's Closing Frame read "--" (positionTag() had no item to number),
     * the cast numbered from @image2 instead of @image3,
     * and the closing frame never reached the generator at all -- silently absent from
       payload.images, on a paid render.

   This file deliberately imports ONLY names that exist at HEAD, so each test's pass/fail
   against the pre-fix tree is meaningful on its own (the new-API half of this fix --
   usesCloseFrame/castPastBudget/refBudget -- is pinned in
   med3-ref-budget-past-limit.test.js, which cannot load at HEAD at all). The I2V/FLF/
   empty-close tests below PASS at HEAD by design: they are the guards that keep this fix
   from repeating round 1's refuted mistakes (reserving empty slots, changing modes that
   were fine), not demonstrations of the bug.

   NOTE on shotText(): its frame-description block stays gated on FLF alone, ON PURPOSE.
   Re-gating it onto the new modes in round 1 reintroduced the raw-.tag fallback M35
   deleted (wrong-picture citations) and emitted "Opening frame @image1: --" noise on every
   R2V shot. Composed-prompt handling of R2V frames is deliberately unanswered today; the
   last test pins that boundary. */

const imgSrc = () => null;   // every fixture image below carries a durable mediaId

function makeCard(overrides = {}) {
  return {
    id: overrides.id || "c1", title: "untitled", mode: "R2V", duration: 8, connect: "new",
    prompt: "", cast: [], refs: [], camera: "", lighting: "", audioCue: "",
    transIn: "", transOut: "", notes: "",
    openFrame: { thumbId: "", source: "", desc: "", tag: "" },
    closeFrame: { thumbId: "", source: "", desc: "", tag: "" },
    ...overrides,
  };
}
const makeProject = (cards, assets = []) =>
  ({ name: "Test", target: 60, look: "", assets, acts: [{ id: "a1", name: "Act", cards }] });

// The owner's repro, parameterized by mode: both frames attached, two cast members.
function twoFrameTwoCastProject(mode) {
  const assets = [
    { id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "mid-nel", lock: false },
    { id: "greg", name: "Greg", kind: "image", tag: "@image2", mediaId: "mid-greg", lock: false },
  ];
  const card = makeCard({
    mode, cast: ["nel", "greg"],
    openFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-open" },
    closeFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-close" },
  });
  return makeProject([card], assets);
}

describe("the closing frame joins the numbering for R2V and V2V (owner repro)", () => {
  for (const mode of ["R2V", "V2V"]) {
    test(`${mode}: open=@image1, close=@image2, cast @image3/@image4, close in payload.images`, () => {
      const project = twoFrameTwoCastProject(mode);
      const entry = flat(project)[0];
      assert.deepEqual(shotImageRefs(entry, project, imgSrc).map((it) => it.id),
        ["openFrame", "closeFrame", "nel", "greg"],
        "frames first (open before close), then cast -- the closing frame must be IN the list");
      assert.equal(positionTag(entry, project, imgSrc, "openFrame"), "@image1");
      assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), "@image2",
        "the card's Closing Frame read '--' because this was null");
      assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image3",
        "cast numbered from @image2 at HEAD -- one lower than the generator's real bank");
      assert.equal(positionTag(entry, project, imgSrc, "greg"), "@image4");
      assert.deepEqual(shotPayload(entry, project, imgSrc).images,
        ["mid-open", "mid-close", "mid-nel", "mid-greg"],
        "the closing frame must actually reach the generator's payload");
    });
  }

  test("I2V is unchanged: the close frame stays out, cast numbers from @image2", () => {
    const project = twoFrameTwoCastProject("I2V");
    const entry = flat(project)[0];
    assert.deepEqual(shotImageRefs(entry, project, imgSrc).map((it) => it.id),
      ["openFrame", "nel", "greg"]);
    assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), null,
      "I2V generation consumes only the opening frame; closeFrame's continuity roles read the field directly");
    assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image2");
    assert.deepEqual(shotPayload(entry, project, imgSrc).images, ["mid-open", "mid-nel", "mid-greg"]);
  });

  test("FLF is unchanged: open @image1, close @image2, cast @image3", () => {
    const project = twoFrameTwoCastProject("FLF");
    const entry = flat(project)[0];
    assert.equal(positionTag(entry, project, imgSrc, "openFrame"), "@image1");
    assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), "@image2");
    assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image3");
  });

  test("an EMPTY close frame in R2V claims nothing -- cast at @image2/@image3", () => {
    // The guard against round 1's refuted "reserve @image2 while the slot is empty": that
    // put two entities on screen claiming one @imageN (the empty slot's hold-tag vs a live
    // cast member's). An unattached frame is simply absent; numbers shift up when it is
    // attached, and that is correct.
    const project = twoFrameTwoCastProject("R2V");
    project.acts[0].cards[0].closeFrame = { thumbId: "", source: "", desc: "", tag: "" };
    const entry = flat(project)[0];
    assert.deepEqual(shotImageRefs(entry, project, imgSrc).map((it) => it.id),
      ["openFrame", "nel", "greg"], "no placeholder / reserved-empty entry for the close frame");
    assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), null);
    assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image2");
    assert.equal(positionTag(entry, project, imgSrc, "greg"), "@image3");
    assert.equal(shotPayload(entry, project, imgSrc).images.length, 3);
  });
});

describe("the 6-image cap trims cast, and castMissingImages no longer calls that 'no image'", () => {
  test("R2V with 2 frames + 5 pictured cast: 4 cast sent, the 5th is capped -- NOT pictureless", () => {
    const assets = [1, 2, 3, 4, 5].map((n) => ({
      id: "as" + n, name: "Cast" + n, kind: "image", tag: "@image" + n, mediaId: "mid-" + n, lock: false,
    }));
    const card = makeCard({
      mode: "R2V", cast: assets.map((a) => a.id),
      openFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-open" },
      closeFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-close" },
    });
    const project = makeProject([card], assets);
    const entry = flat(project)[0];
    const items = shotImageRefs(entry, project, imgSrc);
    assert.equal(items.length, 6, "PixAI's real cap");
    assert.deepEqual(items.map((it) => it.id),
      ["openFrame", "closeFrame", "as1", "as2", "as3", "as4"],
      "frames survive the cap by sorting first; the LAST cast member is what gets trimmed");
    assert.equal(positionTag(entry, project, imgSrc, "as5"), null,
      "the trimmed member has no live slot -- that null is the cap's own signal");
    assert.deepEqual(castMissingImages(entry, project, imgSrc), [],
      "Cast5 has a perfectly good picture: reporting it as 'no image' tells the owner to " +
      "fix a picture that was never broken (the round-1 misfire)");
  });

  test("a genuinely pictureless cast member is still flagged", () => {
    const assets = [
      { id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "mid-nel", lock: false },
      { id: "ghost", name: "Ghost", kind: "image", tag: "@image2", lock: false },   // no mediaId/thumbId
    ];
    const card = makeCard({
      mode: "R2V", cast: ["nel", "ghost"],
      openFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-open" },
      closeFrame: { thumbId: "", source: "", desc: "", tag: "", mediaId: "mid-close" },
    });
    const project = makeProject([card], assets);
    const entry = flat(project)[0];
    assert.deepEqual(castMissingImages(entry, project, imgSrc), ["Ghost"]);
  });
});

describe("shotText's frame-description block stays FLF-only (round-1 boundary)", () => {
  test("an R2V shot with both frames attached emits no Opening/Closing frame lines", () => {
    // Round 1 re-gated these lines onto the new modes and (a) reintroduced the raw-.tag
    // fallback M35 deleted -- wrong-picture citations -- and (b) printed
    // "Opening frame @image1: --" noise on every R2V shot with a frame and no desc.
    // Composed-prompt handling of R2V frames is a separate, deliberately-unanswered
    // question; until it is answered, these lines stay FLF-only.
    const project = twoFrameTwoCastProject("R2V");
    const text = shotText(flat(project)[0], project, imgSrc);
    assert.doesNotMatch(text, /Opening frame/);
    assert.doesNotMatch(text, /Closing frame/);
    // ...while the cast citations DO use the shifted, frame-aware numbering:
    assert.match(text, /Nelnamara — reference @image3/);
    assert.match(text, /Greg — reference @image4/);
  });
});

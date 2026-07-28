import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  CLOSE_FRAME_MODES, usesCloseFrame, resolvedImage,
  castMissingImages, castPastBudget, refBudget, flat,
} from "../src/loom-core.js";

/* The new-API half of the closing-frame fix (see med3-close-frame-joins-numbering.test.js
   for the bug itself and why that file imports only HEAD-era names -- THIS file cannot
   even load against the pre-fix tree, which is its whole point: every export here was
   born with the fix).

     * usesCloseFrame/CLOSE_FRAME_MODES -- the ONE place the "which modes consume an end
       frame" list lives, exported so no surface (the JSX included) ever re-derives it ad
       hoc and drifts.
     * castPastBudget -- the honest counterpart to castMissingImages: a cast member whose
       picture is fine but who lost PixAI's 6-slot contest (frames first). Derived from
       positionTag()'s null, i.e. from the SAME ordering shotImageRefs() actually trims
       with -- never a second implementation of the ordering.
     * refBudget -- the Cast & assets panel's "N of M reference slots used" arithmetic
       (owner decision): budget is 6 minus ATTACHED frames (an empty frame claims nothing
       -- round 1 was refuted for reserving slots for empty ones), and `used` is
       deliberately uncapped so used > budget is visible instead of silently trimmed. */

const imgSrc = () => null;   // fixtures carry durable mediaIds

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
const frame = (mid) => ({ thumbId: "", source: "", desc: "", tag: "", mediaId: mid });
const castAsset = (n) => ({ id: "as" + n, name: "Cast" + n, kind: "image", tag: "@image" + n, mediaId: "mid-" + n, lock: false });

describe("usesCloseFrame / CLOSE_FRAME_MODES", () => {
  test("FLF, R2V and V2V consume the closing frame; I2V does not", () => {
    assert.deepEqual(CLOSE_FRAME_MODES, ["FLF", "R2V", "V2V"]);
    for (const m of CLOSE_FRAME_MODES) assert.equal(usesCloseFrame(m), true, m);
    assert.equal(usesCloseFrame("I2V"), false);
    assert.equal(usesCloseFrame(undefined), false, "a stale/absent mode claims nothing");
  });
});

describe("castPastBudget vs castMissingImages -- two different repairs", () => {
  test("2 frames + 5 pictured cast: the trimmed 5th is past-budget, not missing", () => {
    const assets = [1, 2, 3, 4, 5].map(castAsset);
    const card = makeCard({
      cast: assets.map((a) => a.id),
      openFrame: frame("mid-open"), closeFrame: frame("mid-close"),
    });
    const project = makeProject([card], assets);
    const entry = flat(project)[0];
    assert.deepEqual(castMissingImages(entry, project, imgSrc), []);
    assert.deepEqual(castPastBudget(entry, project, imgSrc), ["Cast5"],
      "the board card must say 'past the reference limit -- not sent', never 'no picture'");
  });

  test("a genuinely pictureless member is missing, never past-budget", () => {
    const assets = [castAsset(1), { id: "ghost", name: "Ghost", kind: "image", tag: "@image9", lock: false }];
    const card = makeCard({ cast: ["as1", "ghost"], openFrame: frame("mid-open"), closeFrame: frame("mid-close") });
    const project = makeProject([card], assets);
    const entry = flat(project)[0];
    assert.deepEqual(castMissingImages(entry, project, imgSrc), ["Ghost"]);
    assert.deepEqual(castPastBudget(entry, project, imgSrc), []);
  });

  test("under budget, neither list has anything to say", () => {
    const assets = [castAsset(1), castAsset(2)];
    const card = makeCard({ cast: ["as1", "as2"], openFrame: frame("mid-open"), closeFrame: frame("mid-close") });
    const project = makeProject([card], assets);
    const entry = flat(project)[0];
    assert.deepEqual(castMissingImages(entry, project, imgSrc), []);
    assert.deepEqual(castPastBudget(entry, project, imgSrc), []);
  });
});

describe("refBudget -- 6 minus ATTACHED frames, used counted uncapped", () => {
  test("both frames attached: budget 4; one: 5; none: 6", () => {
    const assets = [castAsset(1)];
    const both = makeCard({ cast: ["as1"], openFrame: frame("mid-open"), closeFrame: frame("mid-close") });
    const one = makeCard({ cast: ["as1"], openFrame: frame("mid-open") });
    const none = makeCard({ cast: ["as1"] });
    for (const [card, budget, frames] of [[both, 4, 2], [one, 5, 1], [none, 6, 0]]) {
      const project = makeProject([card], assets);
      const b = refBudget(flat(project)[0], project, imgSrc);
      assert.equal(b.budget, budget);
      assert.equal(b.frames, frames);
      assert.equal(b.used, 1);
    }
  });

  test("an EMPTY close frame claims no slot (round 1's refuted reservation)", () => {
    const assets = [castAsset(1)];
    const card = makeCard({ cast: ["as1"], openFrame: frame("mid-open") });   // close stays empty
    const project = makeProject([card], assets);
    const b = refBudget(flat(project)[0], project, imgSrc);
    assert.equal(b.frames, 1);
    assert.equal(b.budget, 5, "an unattached frame must not shrink the budget");
  });

  test("used counts in-cast image assets + image refs, uncapped past the budget", () => {
    const assets = [1, 2, 3, 4, 5].map(castAsset);
    const card = makeCard({
      cast: assets.map((a) => a.id),
      refs: [
        { id: "r1", kind: "image", tag: "@image7", role: "", mediaId: "mid-r1", thumbId: "", source: "" },
        { id: "r2", kind: "image", tag: "@image8", role: "", thumbId: "", source: "" },       // no picture: not used
        { id: "r3", kind: "video", tag: "@video1", role: "", thumbId: "", source: "12345" },  // video: own bank, never counted
      ],
      openFrame: frame("mid-open"), closeFrame: frame("mid-close"),
    });
    const project = makeProject([card], assets);
    const b = refBudget(flat(project)[0], project, imgSrc);
    assert.equal(b.budget, 4);
    assert.equal(b.used, 6, "5 pictured cast + 1 pictured image ref -- NOT clipped to the budget");
  });
});

describe("resolvedImage -- the one shared picture-resolution rule", () => {
  test("mediaId wins; the injected lookup covers thumbId/source; nothing resolves to null", () => {
    const lookup = (thumbId) => (thumbId === "t1" ? "data:img" : null);
    assert.equal(resolvedImage({ mediaId: "m1", thumbId: "t1" }, lookup), "m1");
    assert.equal(resolvedImage({ thumbId: "t1", source: "" }, lookup), "data:img");
    assert.equal(resolvedImage({ thumbId: "", source: "" }, lookup), null);
    assert.equal(resolvedImage(null, lookup), null);
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { shotText, shotPayload, shotImageRefs, positionTag, pickTarget, flat } from "../src/loom-core.js";

/* AUDIT_2026-07-21.md, lens `owner-2026-07-23`, row "Loom shot-card reference sending bugs
   out past 2 images": pinned from a frame-by-frame video review of the Loom's Video tab
   (Deep Focus, Multi-Reference/R2V mode). Simply OPENING the "Pick from your gallery"
   reference-add picker -- even without selecting anything -- corrupted the shot's
   auto-composed prompt: a correct citation of Greg's own cast tag ("...her lover Greg
   @image4 lying face down...") became "...her lover@image3..." (Nelnamara's tag, wrongly
   reassigned onto Greg's mention), then lost its tag entirely, then froze as a hand-edited
   "override active" prompt that Camera/Lighting/Cast could no longer re-compose.

   ROOT CAUSE: two un-synced numbering systems both writing "@imageN" syntax.
     1. Each cast asset's own project-GLOBAL tag (assigned once, in cast-add order -- see
        nextTag/maxTagNum -- e.g. a cast member added 4th is "@image4" forever, project-wide,
        regardless of which shots actually use them). shotText() used to cite THIS tag
        verbatim in its "Keep consistent"/"Other references" lines.
     2. The Multi-Reference drawer's OWN numbering (static/mg-generate-drawer.js's
        _refMap()/_renderSlots()) -- it has zero concept of a global tag namespace and always
        labels whatever lands in its image bank "@image1", "@image2", ... purely by ARRAY
        POSITION, in the exact order shotPayload()/buildShotPayload() hands it.
   These only agree when a shot happens to use every cast member from @image1 up with no
   gaps. The moment a shot uses a later-numbered cast member without also using every
   earlier one (exactly the owner's scenario: Greg's cast tag is @image4, but this shot's
   own reference bank only ever holds 2 pictures), a real, machine-generated "@imageN"
   citation in the composed prompt names a DIFFERENT number than the drawer's own bank
   would ever assign to that same picture -- and whenever the drawer is forced to
   round-trip the composed text through its own chip/reference system (opening the picker
   steals DOM focus off the drawer's contenteditable prompt box; its blur handler
   synchronously re-interprets the text against its own map), a citation that used to
   correctly name one cast member can get reinterpreted as naming a different one, or
   dropped, and the resulting mismatch against a fresh shotText() recompute freezes as a
   promptOverride ("override active").

   This suite is a pure-logic reproduction against loom-core.js -- it does not touch the
   DOM/drawer at all (this test runner has no jsdom; see mg-generate-drawer-concurrent.
   test.js's own comment on why real interaction verification needs a real browser). It
   proves the underlying DATA MISMATCH shotText()/shotPayload() must never produce again:
   whatever @imageN the composed prompt names for a picture must always be the exact same
   @imageN position that picture lands at in shotPayload()'s own sorted image list -- the
   one thing static/mg-generate-drawer.js's positional numbering can never disagree with,
   because it IS that same order. */

function makeProject() {
  return {
    name: "Test", target: 60, look: "",
    assets: [
      { id: "her",  name: "Her",       kind: "image", tag: "@image1", mediaId: "mid-her",  lock: false },
      { id: "nel",  name: "Nelnamara", kind: "image", tag: "@image3", mediaId: "mid-nel",  lock: false },
      { id: "room", name: "The room",  kind: "image", tag: "@image2", mediaId: "",         lock: false }, // never resolvable -- not in this shot's cast anyway
      { id: "greg", name: "Greg",      kind: "image", tag: "@image4", mediaId: "mid-greg", lock: false },
    ],
    acts: [{ id: "a1", name: "Act", cards: [{
      id: "shot1", title: "A-01", mode: "R2V", duration: 5, connect: "new",
      prompt: "her lover Greg lying face down, morning light",
      camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
      cast: ["nel", "greg"], refs: [], openFrame: {}, closeFrame: {},
      promptOverride: false, promptOverrideText: "",
    }] }],
  };
}
const imgSrc = () => null;   // every resolvable asset above carries a mediaId already

describe("reference picker corruption (AUDIT_2026-07-21.md owner-2026-07-23 row)", () => {
  test("shotPayload's Multi-Reference image bank is [Nelnamara, Greg] in that exact order", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, imgSrc);
    assert.deepEqual(payload.images, ["mid-nel", "mid-greg"]);
  });

  test("shotText cites each cast member by the drawer's OWN positional slot, not their raw project-global tag", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    const text = shotText(entry, project, imgSrc);
    // Position 1 in shotPayload's bank is Nelnamara's picture, position 2 is Greg's (see the
    // previous test) -- the composed prompt's citation for each of them must match THAT, not
    // their stable, project-global cast tags (@image3 / @image4).
    assert.match(text, /Nelnamara — reference @image1/);
    assert.match(text, /Greg — reference @image2/);
    // The exact corruption traced from the owner's video: citing Greg's raw project-global
    // tag (@image4) is a real, valid-looking "@imageN" token that the drawer's OWN numbering
    // never assigns to Greg's picture at all in this shot (its bank only ever has 2 slots) --
    // exactly the kind of citation that can be silently reinterpreted, or simply orphaned,
    // once the drawer's chip system gets a chance to round-trip the text.
    assert.doesNotMatch(text, /Greg — reference @image4/);
    assert.doesNotMatch(text, /Nelnamara — reference @image3/);
  });

  test("positionTag() agrees with shotPayload's own image order for every resolvable picture in the shot", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    const items = shotImageRefs(entry, project, imgSrc);
    const payload = shotPayload(entry, project, imgSrc);
    assert.equal(items.length, 2);
    items.forEach((it, i) => {
      assert.equal(payload.images[i], it.d, `shotImageRefs()[${i}] must be the same picture shotPayload().images[${i}] sends the drawer`);
      assert.equal(positionTag(entry, project, imgSrc, it.id), "@image" + (i + 1));
    });
  });

  test("an asset with no resolvable image in this shot falls back to its own stored tag (nothing live for the drawer to number)", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    assert.equal(positionTag(entry, project, imgSrc, "room"), null);
  });

  test("regression guard: every @imageN token shotText() actually emits matches the drawer's own positional slot for that picture", () => {
    // Broader, name-independent version of the tests above -- a future edit that
    // reintroduces a raw .tag citation anywhere in shotText()'s cast/ref blocks fails this
    // even if it doesn't happen to touch Greg/Nelnamara specifically.
    const project = makeProject();
    const entry = flat(project)[0];
    const text = shotText(entry, project, imgSrc);
    const items = shotImageRefs(entry, project, imgSrc);
    const usedCast = project.assets.filter((as) => entry.c.cast.includes(as.id) && items.some((it) => it.id === as.id));
    assert.ok(usedCast.length > 0, "fixture sanity: expected at least one resolvable cast member in this shot");
    usedCast.forEach((as) => {
      const idx = items.findIndex((it) => it.id === as.id);
      const wantTag = "@image" + (idx + 1);
      const m = text.match(new RegExp(`${as.name} — (?:reference|maintain exact appearance from) (@image\\d+)`));
      assert.ok(m, `expected a "Keep consistent" citation line for ${as.name}`);
      assert.equal(m[1], wantTag, `${as.name}'s citation must match the drawer's own positional slot, not a raw project-global tag`);
    });
  });

  test("shotPayload's own composed prompt (what the drawer's prefill() actually receives) carries the positional citations too", () => {
    // shotPayload() used to call shotText(entry, project) WITHOUT imgSrc -- this pins that
    // the payload actually handed to prefill() (master-storyboard.jsx line ~1019/1335) is
    // built with the same resolver used to number the image bank, not a separately
    // (and possibly differently) resolved prompt.
    const project = makeProject();
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, imgSrc);
    assert.match(payload.prompt, /Greg — reference @image2/);
  });
});

describe("Multi-Reference picker add/replace persistence (requirement 2: a 3rd/4th reference must actually stick)", () => {
  test("picking into a slot BEYOND the shot's current bank appends a new reference, tagged past every tag already in use", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    // The shot's own bank currently has 2 entries (slots 0 and 1) -- slot 2 is the "+ add"
    // placeholder the drawer renders past its filled slots.
    const plan = pickTarget(entry, project, imgSrc, 2);
    assert.deepEqual(plan.type, "append");
    // Must sort past EVERY tag already in play this shot (project-global cast tags go up to
    // @image4), not just a same-kind refs-only counter that could collide with @image1..@image4.
    assert.equal(plan.tag, "@image5");
  });

  test("picking on an EXISTING filled slot replaces that entity's picture, not some other one", () => {
    const project = makeProject();
    const entry = flat(project)[0];
    // Slot 0 = Nelnamara's picture (position 1), slot 1 = Greg's (position 2) -- see the
    // shotImageRefs ordering test above.
    const replaceNel = pickTarget(entry, project, imgSrc, 0);
    assert.deepEqual(replaceNel, { type: "replace", kind: "cast", id: "nel" });
    const replaceGreg = pickTarget(entry, project, imgSrc, 1);
    assert.deepEqual(replaceGreg, { type: "replace", kind: "cast", id: "greg" });
  });

  test("a shot-level ref (not a cast member) is correctly identified as the replace target too", () => {
    const project = makeProject();
    project.acts[0].cards[0].cast = ["greg"];
    project.acts[0].cards[0].refs = [{ id: "r1", kind: "image", tag: "@image9", role: "", source: "", thumbId: "", mediaId: "mid-extra" }];
    const entry = flat(project)[0];
    // Bank order: Greg (@image4) sorts before the ref (@image9).
    const items = shotImageRefs(entry, project, imgSrc);
    assert.deepEqual(items.map((it) => it.id), ["greg", "r1"]);
    assert.deepEqual(pickTarget(entry, project, imgSrc, 1), { type: "replace", kind: "ref", id: "r1" });
  });
});

/* Owner live-test 2026-07-23: a shot with 2 cast members AND both Opening Frame + Closing
   Frame set (FLF mode). Screenshots showed the shot detail popover and the Generate drawer
   BOTH statically labeling the fields "OPENING FRAME @image1" / "CLOSING FRAME @image2"
   (c.openFrame.tag/c.closeFrame.tag -- a freely owner-editable text field, FrameSlot's own
   tag input, master-storyboard.jsx ~line 3083), while the composed prompt actually cited
   @image1/@image3/@image4 for cast, and the drawer's own live Image References bank showed
   yet a THIRD story. Owner's diagnosis (matches a first read of the code): a frame's own
   independently-stored .tag is a SEPARATE piece of state from cast tags (as.tag, assigned in
   cast-add order), and shotImageRefs()'s old sort-by-raw-tag-text scheme let a cast member's
   real, stable project-global tag silently tie with -- and, by push-order, always beat -- a
   frame's own stored tag for the same disputed "@imageN" slot, even though the frame's own UI
   kept statically claiming it. This is the THIRD manifestation of the un-synced-numbering bug
   class the giant comment above shotImageRefs() describes -- follow-up to commit 2e714fd
   (cast tag vs drawer positional numbering) and commit c7aaff2 (extended persistence to i2v/
   FLF frame picks and r2v video refs). FIX: Opening/Closing Frame now ALWAYS reserve the
   first slot(s) -- @image1, and @image2 when Closing Frame applies -- regardless of any raw
   .tag stored on the frame or any cast/ref tag that happens to collide with it; cast/refs
   fill in from @image3 on. */
describe("frame/cast @imageN slot collision (owner live-test 2026-07-23, 3rd manifestation -- follow-up to 2e714fd, c7aaff2)", () => {
  function makeFrameCollisionProject() {
    return {
      name: "Test", target: 60, look: "",
      assets: [
        { id: "nel",  name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "mid-nel",  lock: false },
        { id: "greg", name: "Greg",      kind: "image", tag: "@image4", mediaId: "mid-greg", lock: false },
      ],
      acts: [{ id: "a1", name: "Act", cards: [{
        id: "shot1", title: "A-01", mode: "FLF", duration: 5, connect: "flf",
        prompt: "Nelnamara is with her lover Greg, morning light",
        camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
        cast: ["nel", "greg"], refs: [],
        // Opening/Closing Frame each carry their OWN independently-stored .tag -- exactly
        // what the shot detail popover and Generate drawer statically displayed in the
        // owner's live test. Opening Frame's stored tag collides head-on with Nelnamara's
        // real, stable project-global cast tag (@image1).
        openFrame:  { thumbId: "", source: "", desc: "wide establishing shot", mediaId: "mid-open",  tag: "@image1" },
        closeFrame: { thumbId: "", source: "", desc: "close on their faces",   mediaId: "mid-close", tag: "@image2" },
        promptOverride: false, promptOverrideText: "",
      }] }],
    };
  }
  const imgSrc = () => null;   // every resolvable asset above already carries a mediaId

  test("Opening/Closing Frame always win the first slots -- @image1/@image2 -- no matter what a cast member's own tag says", () => {
    const project = makeFrameCollisionProject();
    const entry = flat(project)[0];
    const items = shotImageRefs(entry, project, imgSrc);
    assert.deepEqual(items.map((it) => it.id), ["openFrame", "closeFrame", "nel", "greg"],
      "frames must sort ahead of cast/refs by KIND, not by whichever raw .tag text happens to tie/collide");
    assert.equal(positionTag(entry, project, imgSrc, "openFrame"), "@image1");
    assert.equal(positionTag(entry, project, imgSrc, "closeFrame"), "@image2");
    // Nelnamara's real project-global tag is @image1 too (the actual collision) -- she must
    // be bumped to @image3, never allowed to usurp the frame's reserved slot.
    assert.equal(positionTag(entry, project, imgSrc, "nel"), "@image3");
    assert.equal(positionTag(entry, project, imgSrc, "greg"), "@image4");
  });

  test("the Multi-Reference image bank (what actually reaches /api/loom/generate) is frame-first, matching the reserved slots", () => {
    const project = makeFrameCollisionProject();
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, imgSrc);
    assert.deepEqual(payload.images, ["mid-open", "mid-close", "mid-nel", "mid-greg"]);
  });

  test("the composed prompt's frame-description lines cite the LIVE reserved slot, not a stale independently-stored .tag", () => {
    // Give each frame a raw .tag that is deliberately WRONG for its guaranteed position (as
    // if the shot's cast composition changed since the owner last looked at the frame
    // fields) -- the composed prompt must still cite the real, live @image1/@image2, exactly
    // what the Multi-Reference drawer's own bank shows for the same two pictures, never the
    // stale text still sitting in c.openFrame.tag/c.closeFrame.tag.
    const project = makeFrameCollisionProject();
    project.acts[0].cards[0].openFrame.tag = "@image7";
    project.acts[0].cards[0].closeFrame.tag = "@image9";
    const entry = flat(project)[0];
    const text = shotText(entry, project, imgSrc);
    assert.match(text, /Opening frame @image1: wide establishing shot/);
    assert.match(text, /Closing frame @image2: close on their faces/);
    assert.doesNotMatch(text, /@image7/);
    assert.doesNotMatch(text, /@image9/);
  });

  test("the 'Keep consistent' cast citations also shift past the reserved frame slots", () => {
    const project = makeFrameCollisionProject();
    const entry = flat(project)[0];
    const text = shotText(entry, project, imgSrc);
    assert.match(text, /Nelnamara — reference @image3/);
    assert.match(text, /Greg — reference @image4/);
    assert.doesNotMatch(text, /Nelnamara — reference @image1/);
  });
});

/* Owner-flagged real PixAI limits: at most 6 image refs, at most 3 @video refs on a
   reference-video generation. Reserving 2 frame slots ahead of cast/refs must not let a
   busy shot silently exceed either cap -- it must apply the same "keep the highest-priority
   N, the rest are left out" truncation pixai_gallery.py's bulkSendVideo()/Gen.addVideoRefs()
   already establishes for the gallery's own bulk-send-to-video path (trims to the same
   6-image limit before ever reaching submit). Frames are reserved FIRST specifically so they
   are never among the casualties when a shot has to drop something to fit under the cap. */
describe("PixAI's real caps (6 image refs / 3 video refs) survive frame reservation", () => {
  test("shotImageRefs() never returns more than 6 images, and the reserved frame slots are never the ones dropped", () => {
    const assets = [];
    const cast = [];
    for (let i = 1; i <= 6; i++) {
      assets.push({ id: `cast${i}`, name: `Cast ${i}`, kind: "image", tag: `@image${i + 10}`, mediaId: `mid-cast${i}`, lock: false });
      cast.push(`cast${i}`);
    }
    const project = {
      name: "Test", target: 60, look: "", assets,
      acts: [{ id: "a1", name: "Act", cards: [{
        id: "shot1", title: "A-01", mode: "FLF", duration: 5, connect: "flf",
        prompt: "", camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
        cast, refs: [],
        openFrame:  { thumbId: "", source: "", desc: "", mediaId: "mid-open",  tag: "" },
        closeFrame: { thumbId: "", source: "", desc: "", mediaId: "mid-close", tag: "" },
        promptOverride: false, promptOverrideText: "",
      }] }],
    };
    const entry = flat(project)[0];
    // 2 frames + 6 cast = 8 resolvable images total -- must truncate to PixAI's real 6-image
    // cap, and the frames (structurally load-bearing for FLF) must survive every time.
    const items = shotImageRefs(entry, project, () => null);
    assert.equal(items.length, 6);
    assert.deepEqual(items.slice(0, 2).map((it) => it.id), ["openFrame", "closeFrame"]);
  });

  test("shotPayload() caps video_refs at 3, the same real PixAI limit the image-side truncation mirrors", () => {
    const card = {
      id: "shot1", title: "A-01", mode: "R2V", duration: 5, connect: "new",
      prompt: "", camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
      cast: [], refs: [
        { id: "v1", kind: "video", tag: "@video1", source: "9001" },
        { id: "v2", kind: "video", tag: "@video2", source: "9002" },
        { id: "v3", kind: "video", tag: "@video3", source: "9003" },
        { id: "v4", kind: "video", tag: "@video4", source: "9004" },
      ],
      openFrame: {}, closeFrame: {}, promptOverride: false, promptOverrideText: "",
    };
    const project = { name: "Test", target: 60, look: "", assets: [], acts: [{ id: "a1", name: "Act", cards: [card] }] };
    const payload = shotPayload(flat(project)[0], project, () => null);
    assert.deepEqual(payload.video_refs, ["9001", "9002", "9003"]);
  });
});

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

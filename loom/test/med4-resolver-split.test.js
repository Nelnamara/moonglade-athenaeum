import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { flat, shotText, shotPayload } from "../src/loom-core.js";

/* PROMPT vs BANK RESOLVER SPLIT (2026-07-27, round 3; pre-existing, WIDENED by round 2 --
   both round-2 reviewers hit it).

   master-storyboard.jsx's prefill effect built the drawer's image BANK thumbs-aware
   (buildShotPayload(active, project, imgSrc)) while composing the drawer's PROMPT with no
   resolver (shotText(active, project) -- the mediaId-only noImgSrc path). A thumbId-only
   frame or cast picture was therefore IN the bank but INVISIBLE to the prompt's
   numbering: the entity itself went uncited (or, for a thumb-only frame, the frame
   uncounted) and every citation past it was off by one. Reproduced in review: bank held
   frame=@image1, Nelnamara=@image2; the prompt cited "Nelnamara — reference @image1".

   THE TRAP (why this was never a one-line fix): the hand-edit detection compares
   composed text at four other sites -- mg-prompt-commit, the prefill effect's
   outgoing-shot flush, the re-sync button, and the Generate-all flush. If the prefill
   composes WITH imgSrc and any comparator composes WITHOUT, every purely-prefilled
   prompt on a thumb-carrying shot reads as hand-edited and freezes as an override --
   silent, sticky corruption. So ALL drawer-coupled sites move to imgSrc TOGETHER, and
   copyShot / the shot-list export stay noImgSrc (standalone renderings that never feed
   or get compared against the drawer). This file pins both halves.

   The behavioral tests read the prefill site's ACTUAL call shape out of the JSX and
   compose with exactly what the tree does -- so against the round-2 tree they fail on
   the real off-by-one, not on a style opinion. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; every pattern below assumes LF

const thumbs = { tloc: "data:image/png;base64,TE9DQUw=" };
const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
  : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);

const baseCard = {
  title: "resolver split", mode: "R2V", duration: 8, connect: "new",
  prompt: "two figures under the eclipse", refs: [],
  camera: "", lighting: "", audioCue: "", transIn: "", transOut: "", notes: "",
};
const noFrame = { mediaId: "", thumbId: "", source: "", desc: "", tag: "" };
const makeProject = (card, assets) =>
  ({ name: "T", target: 60, look: "", assets, acts: [{ id: "a1", name: "Act", cards: [card] }] });

// The composed prompt exactly as the prefill effect ships it to the drawer: same
// shotText, same arguments the JSX site actually passes. Third argument present ->
// thumbs-aware; absent -> the round-2 noImgSrc composition.
const prefillSite = jsx.match(/payload\.prompt = shotText\(active, project(, imgSrc)?\);/);
assert.ok(prefillSite, "could not find the prefill effect's payload.prompt composition in " +
  "master-storyboard.jsx -- if it was restructured, update this pattern, don't delete the test");
const asPrefilled = (entry, project) =>
  prefillSite[1] ? shotText(entry, project, imgSrc) : shotText(entry, project);

describe("the drawer's prompt cites the drawer's own bank positions", () => {
  test("thumbId-only CAST member: every prompt citation == its bank position", () => {
    const assets = [
      // thumbId-only: resolvable ONLY through the live resolver -- invisible to noImgSrc
      { id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "", thumbId: "tloc", source: "nel.png", lock: false },
      { id: "greg", name: "Greg", kind: "image", tag: "@image2", mediaId: "900000000000000002", thumbId: "", source: "", lock: false },
    ];
    const project = makeProject({ ...baseCard, id: "c1", cast: ["nel", "greg"],
      openFrame: { ...noFrame, mediaId: "900000000000000001" }, closeFrame: noFrame }, assets);
    const entry = flat(project)[0];
    const bank = shotPayload(entry, project, imgSrc).images;
    assert.deepEqual(bank, ["900000000000000001", thumbs.tloc, "900000000000000002"],
      "fixture drift -- the bank should hold [frame, Nelnamara(thumb data-URL), Greg]");
    const prompt = asPrefilled(entry, project);
    const nelSlot = "@image" + (bank.indexOf(thumbs.tloc) + 1);
    const gregSlot = "@image" + (bank.indexOf("900000000000000002") + 1);
    assert.match(prompt, new RegExp(`Nelnamara — reference ${nelSlot}\\b`),
      "Nelnamara is IN the bank the drawer was handed, so the prompt must cite her at " +
      "her bank position -- round 2 composed the prompt mediaId-only, which could not " +
      "see her at all and cited nothing");
    assert.match(prompt, new RegExp(`Greg — reference ${gregSlot}\\b`),
      "every citation AFTER a thumb-only entity was off by one in round 2 (Greg sat in " +
      "bank slot 3 while the prompt cited @image2)");
  });

  test("thumbId-only FRAME (the reviewers' exact repro): cast citation == bank position", () => {
    const assets = [
      { id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "900000000000000002", thumbId: "", source: "", lock: false },
    ];
    const project = makeProject({ ...baseCard, id: "c2", cast: ["nel"],
      openFrame: { ...noFrame, thumbId: "tloc", source: "open.png" }, closeFrame: noFrame }, assets);
    const entry = flat(project)[0];
    const bank = shotPayload(entry, project, imgSrc).images;
    assert.deepEqual(bank, [thumbs.tloc, "900000000000000002"],
      "fixture drift -- the bank should hold [frame(thumb data-URL), Nelnamara]");
    assert.match(asPrefilled(entry, project), /Nelnamara — reference @image2\b/,
      "bank holds frame=@image1, Nelnamara=@image2; round 2's prompt cited " +
      "'Nelnamara — reference @image1' -- the generator then bound her instruction " +
      "to the frame image");
    // Fixture truth, pinning WHY the one-resolver family rule exists: the two resolvers
    // genuinely diverge on this shot, so any site composing one way while another
    // compares the other way manufactures a phantom hand-edit override.
    assert.match(shotText(entry, project), /Nelnamara — reference @image1\b/,
      "noImgSrc composition really does renumber past the invisible thumb-only frame -- " +
      "if this stops holding, the fixtures above have drifted");
  });
});

/* ---- the family audit, pinned at the source level (the comparators can't run without
       React, but their call SHAPES are exactly what the trap is about) ---- */

describe("every drawer-coupled shotText site composes with the live resolver", () => {
  const coupled = [
    ["prefill effect payload.prompt", /payload\.prompt = shotText\(active, project, imgSrc\);/],
    ["mg-prompt-commit comparator", /shotText\(a, projectRef\.current, resolve\)/],
    ["outgoing-shot flush comparator", /shotText\(outEntry, project, imgSrc\)/],
    ["re-sync button composition", /shotText\(\{ \.\.\.active, c: \{ \.\.\.active\.c, promptOverride: false \} \}, project, imgSrc\)/],
    ["Generate-all flush comparator", /shotText\(a, project, imgSrc\)/],
  ];
  for (const [label, re] of coupled) {
    test(`${label} passes a resolver`, () => {
      assert.match(jsx, re,
        `${label} must compose thumbs-aware -- one drawer-coupled site composing ` +
        `noImgSrc while the prefill composes with imgSrc freezes every thumb-carrying ` +
        `prefilled prompt as a hand-edit override (the round-2 trap)`);
    });
  }

  test("copyShot stays deliberately noImgSrc (standalone family)", () => {
    assert.match(jsx, /const copyShot = \(entry\) => navigator\.clipboard\?\.writeText\(shotText\(entry, project\)\);/,
      "copyShot is a standalone rendering -- it never feeds or gets compared against " +
      "the drawer, and a clipboard citation numbered off a session-local data-URL " +
      "means nothing outside this app. If this changes on purpose, move it to the " +
      "coupled list above WITH its comparators -- never alone");
  });

  test("the shot-list export stays deliberately noImgSrc (standalone family)", () => {
    assert.match(jsx, /buildShotListText\(project, fmt, actLetter, shotText\)/,
      "exportAll hands shotText over unbound (composes noImgSrc inside " +
      "buildShotListText) -- a standalone .txt rendering, same reasoning as copyShot");
  });
});

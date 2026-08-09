import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { resolvedImage } from "../src/loom-core.js";
import { applyPrefill, buildPayload } from "../../gallery/src/gen/videoDrawerCore.js";

/* FLF POSITIONAL PREFILL (2026-07-27, round 3 -- the MONEY BUG of the round-2 review).

   Round 2 taught prefill() to map a host-stated flf image list onto the two frame slots
   POSITIONALLY (images[0] -> Start box, images[1] -> End box; see
   med3-drawer-flf-end-frame-prefill.test.js). But the HOST kept building that list by FILTERING:

     payload.images = [openFrame, closeFrame].filter((f) => f && f.mediaId).map(...)

   A filter destroys position. An flf shot whose END frame is gallery-picked while its start frame
   is still empty (a normal intermediate state) produced images=[close] -- a ONE-item list -- and
   the drawer's positional branch put the intended END frame in the START box. Generate then spent
   real credits rendering FROM the end frame. Both round-2 reviewers reproduced it.

   The repair: the host passes [Start-or-null, End-or-null] with nulls PRESERVED, and the drawer's
   flf branch maps a null to "clear that slot".

   The end-to-end test below does not simulate the host's list-building -- it EXTRACTS the actual
   flf branch from master-storyboard.jsx and executes it, then feeds its output to the drawer's
   PURE prefill layer (gallery/src/gen/videoDrawerCore.js). The host half is unchanged by the
   no-vanilla port (2026-08-08); only the drawer half moved from the vanilla <mg-generate-drawer>'s
   extracted class methods to the pure functions the React <VideoDrawer> now drives. Against the
   round-2 tree it fails on the money trigger (end frame lands in the Start box); against the
   repaired tree the End Frame stays an End Frame and the Start box stays empty. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; every pattern below assumes LF

/* ---- the host half: the ACTUAL flf branch out of the prefill effect ---- */

const branchM = jsx.match(/\} else if \(nextMode === "flf"\) \{\n([\s\S]*?)\n {4}\} else if \(nextMode === "r2v"\) \{/);
assert.ok(branchM, "could not locate the prefill effect's flf branch in master-storyboard.jsx -- " +
  "if the effect was restructured, update this pattern, don't delete the test");

// Everything the branch body references, injected. asRef/imgSrc/frameSrc mirror the component's
// own definitions (imgSrc resolves a thumbId against `thumbs` state; the fixture passes the lookup
// directly).
const runFlfBranch = (openFrame, closeFrame, thumbs = {}) => {
  const payload = { images: [] };
  const active = { c: { openFrame, closeFrame } };
  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);
  const asRef = (d) => ({ media_id: d, thumb: /^\d+$/.test(d) ? ("/thumbs/" + d + ".jpg") : d });
  const frameSrc = (f) => (f && f.thumbId ? thumbs[f.thumbId] : (f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null));
  new Function("active", "payload", "resolvedImage", "imgSrc", "asRef", "frameSrc", branchM[1])(
    active, payload, resolvedImage, imgSrc, asRef, frameSrc);
  return payload.images;
};

/* ---- the drawer half: the PURE prefill/payload layer the React <VideoDrawer> drives ---- */

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 10, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}

const flfPrefill = (images) => ({
  mode: "flf", duration: 10, audio: false, audio_language: "english",
  quality: "professional", images, video_refs: [], audio_ref: null,
});
const emptyFrame = { mediaId: "", thumbId: "", source: "", desc: "", tag: "" };
const galleryFrame = (mid) => ({ mediaId: mid, thumbId: "", source: "", desc: "", tag: "" });

describe("host -> drawer, end to end: the flf image list is positional", () => {
  test("MONEY TRIGGER: end frame picked first -> lands in the END slot, Start stays empty", () => {
    const images = runFlfBranch(emptyFrame, galleryFrame("747000000000000001"));
    const d = drawer({});
    applyPrefill(d, flfPrefill(images));
    assert.equal(d.mode, "flf");
    assert.equal(d.slots[0], null,
      "the Start box must stay EMPTY -- round 2's host filter collapsed [empty, close] to a " +
      "one-item list and the drawer put the intended END frame here, so Generate rendered FROM " +
      "the end frame on real credits");
    assert.equal(d.slots[1] && d.slots[1].media_id, "747000000000000001",
      "the gallery-picked END frame must be in the End Frame box");
  });

  test("both frames attached still lands [Start, End] in order", () => {
    const images = runFlfBranch(galleryFrame("111"), galleryFrame("222"));
    const d = drawer({});
    applyPrefill(d, flfPrefill(images));
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["111", "222"]);
  });

  test("start-only shot: End slot is explicitly cleared, not left holding a stale frame", () => {
    const d = drawer({ mode: "flf", slots: [{ media_id: "C1", thumb: "t" }, { media_id: "C2", thumb: "t" }] });
    applyPrefill(d, flfPrefill(runFlfBranch(galleryFrame("333"), emptyFrame)));
    assert.deepEqual(d.slots.map((s) => s && s.media_id), ["333", null]);
  });

  test("thumbId-only (locally uploaded) frame ships as its data-URL, same shape r2v uses", () => {
    // The server's resolve_img() (/api/loom/generate) base64-uploads a data: URL for every mode,
    // flf included -- so this shape is genuinely submittable, not just visible.
    const dataUrl = "data:image/png;base64,QUJD";
    const localFrame = { mediaId: "", thumbId: "t1", source: "shot.png", desc: "", tag: "" };
    const images = runFlfBranch(galleryFrame("444"), localFrame, { t1: dataUrl });
    const d = drawer({});
    applyPrefill(d, flfPrefill(images));
    assert.equal(d.slots[1] && d.slots[1].media_id, dataUrl,
      "the End Frame slot must hold the local frame's data-URL");
    assert.deepEqual(buildPayload(d, "").images, ["444", dataUrl],
      "payload must carry the data-URL through to /api/price and /api/loom/generate");
  });

  test("the host branch preserves nulls -- it never filters", () => {
    // The structural pin behind the behavioral tests above: the list is ALWAYS
    // [Start-or-null, End-or-null]. A future `.filter(...)` reintroduction collapses positions.
    assert.deepEqual(runFlfBranch(emptyFrame, emptyFrame), [null, null]);
    assert.equal(runFlfBranch(emptyFrame, galleryFrame("555")).length, 2,
      "an flf image list is always length 2 -- position IS the meaning");
    const branchCode = branchM[1].split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
    assert.ok(!/\.filter\(/.test(branchCode),
      "the flf branch must not filter the frame list -- filtering is exactly what destroyed " +
      "position in round 2");
  });
});

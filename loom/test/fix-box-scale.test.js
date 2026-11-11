import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { boxesToOriginal, pictureRect, scaleBoxes } from "../../gallery/src/gen/editCore.js";

/* The Fixer's one box scaler (editCore.js), as pure functions.

   #96: on the phone the Loom's Fixer drew on the 768-px thumbnail and scaled the boxes by that
   picture's naturalWidth, so on any larger picture PixAI was sent a smaller box in the wrong
   place -- and the repair it charged for landed somewhere else.

   #93 review F1: the desktop Loom's `.lv-fixwrap img` is `max-height:280px; object-fit:contain`,
   so a square or portrait picture is LETTERBOXED inside a W x 280 element. Scaling by the
   element's width and ignoring the gap sent a portrait face 384 px too high at 40 % of its size.
   The boxes now map through the picture's RENDERED rect, on every surface. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const box = [{ x: 100, y: 50, w: 60, h: 40, tag: "face" }];
const S = (width, height) => ({ width, height });

// master's arithmetic (one scale, natural / shown width, no offset) -- what a landscape keeps
const masterScale = (boxes, cw, nw) => boxes.map((b) => {
  const s = nw / cw;
  return { x: Math.round(b.x * s), y: Math.round(b.y * s), width: Math.round(b.w * s), height: Math.round(b.h * s), tag: b.tag };
});

test("boxesToOriginal scales by the original picture over the shown picture", () => {
  // a 1536 x 864 picture shown 360 px wide (height auto: 202.5 -> laid out 203)
  assert.deepEqual(boxesToOriginal(box, S(360, 203), S(1536, 864)), [{ x: 427, y: 213, width: 256, height: 171, tag: "face" }]);
});

test("the #96 bug: scaling by the 768-px thumbnail sends a half-size box in the wrong place", () => {
  const right = boxesToOriginal(box, S(360, 203), S(1536, 864));
  const thumb = boxesToOriginal(box, S(360, 203), S(768, 432));   // what master sent
  assert.equal(thumb[0].x, 213);
  assert.notDeepEqual(thumb, right);
  assert.ok(thumb[0].width < right[0].width);
});

test("the desktop letterbox (review F1): a portrait picture in a 378 x 280 contain box", () => {
  // Chromium's own layout of the real CSS (review_93/probe_desktop_letterbox): the picture is
  // drawn 157.5 x 280, 110.25 px in from the element's left edge.
  const r = pictureRect(378, 280, 864, 1536);
  assert.equal(r.top, 0);
  assert.equal(r.left, 110.25);
  assert.equal(r.scale, 1536 / 280);
  // a 40 x 40 box over the picture's centre (189, 140) in the element
  const centre = [{ x: 169, y: 120, w: 40, h: 40, tag: "face" }];
  assert.deepEqual(boxesToOriginal(centre, S(378, 280), S(864, 1536)), [{ x: 322, y: 658, width: 219, height: 219, tag: "face" }]);
  // what master sent for it: x 386 y 274, 91 px -- 384 px too high, 40 % of the size
  assert.deepEqual(masterScale(centre, 378, 864), [{ x: 386, y: 274, width: 91, height: 91, tag: "face" }]);
  // and a square one: x 439 y 439, 146 px (master: x 458 y 325, 108 px)
  assert.deepEqual(boxesToOriginal(centre, S(378, 280), S(1024, 1024)), [{ x: 439, y: 439, width: 146, height: 146, tag: "face" }]);
});

test("a landscape picture (no letterbox) maps exactly as before, whatever the layout rounded its height to", () => {
  const many = [{ x: 33, y: 17, w: 81, h: 57, tag: "hand" }, { x: 0.5, y: 2.5, w: 7.5, h: 12.5, tag: "face" },
    { x: 150, y: 60, w: 40, h: 40, tag: "face" }];
  // 1536 x 864 at 378 wide is 212.625 tall: laid out as 212 or 213, and either is not a letterbox
  for (const ch of [212, 213]) {
    assert.deepEqual(boxesToOriginal(many, S(378, ch), S(1536, 864)), masterScale(many, 378, 1536), "height " + ch);
  }
  for (const [cw, ch, nw, nh] of [[360, 203, 1536, 864], [412, 232, 2560, 1440], [777, 437, 1920, 1080]]) {
    assert.deepEqual(boxesToOriginal(many, S(cw, ch), S(nw, nh)), masterScale(many, cw, nw), [cw, ch, nw, nh].join("x"));
  }
});

test("a box is clipped to the picture: the letterbox gap and anything past an edge are not sent", () => {
  // portrait letterbox: the picture spans x 110.25 .. 267.75 of the 378-px element
  const inGap = [{ x: 20, y: 100, w: 60, h: 40, tag: "face" }];          // wholly in the left gap
  assert.deepEqual(boxesToOriginal(inGap, S(378, 280), S(864, 1536)), [],
    "nothing on the picture: the box is dropped, not sent 0 wide (review 2, F3)");
  // a bar-only box beside a real one: only the real one is sent (and counted by the confirm)
  const mixed = boxesToOriginal(inGap.concat([{ x: 169, y: 120, w: 40, h: 40, tag: "face" }]), S(378, 280), S(864, 1536));
  assert.deepEqual(mixed, [{ x: 322, y: 658, width: 219, height: 219, tag: "face" }]);
  // a box that rounds to nothing is dropped too
  assert.deepEqual(boxesToOriginal([{ x: 10, y: 10, w: 0.1, h: 20, tag: "hand" }], S(400, 300), S(400, 300)), []);
  const straddle = [{ x: 90, y: 100, w: 60, h: 40, tag: "face" }];       // 20 px in the gap, 40 on the picture
  const [s] = boxesToOriginal(straddle, S(378, 280), S(864, 1536));
  assert.equal(s.x, 0);
  assert.equal(s.width, Math.round((150 - 110.25) * (1536 / 280)));
  // past the right / bottom edge of a plain landscape picture
  const [r] = boxesToOriginal([{ x: 300, y: 250, w: 200, h: 100, tag: "hand" }], S(400, 300), S(1600, 1200));
  assert.equal(r.x + r.width, 1600);
  assert.equal(r.y + r.height, 1200);
});

test("a missing size on either side is null -- a refusal, never the old scale-1 fallback", () => {
  for (const [shown, natural] of [[S(0, 280), S(1536, 864)], [S(360, 0), S(1536, 864)], [S(360, 203), S(0, 864)],
    [S(360, 203), S(1536, 0)], [null, S(1536, 864)], [S(360, 203), undefined]]) {
    assert.equal(boxesToOriginal(box, shown, natural), null, JSON.stringify([shown, natural]));
  }
});

test("scaleBoxes reads the four sizes off the <img> (or a remembered measurement); null when it cannot", () => {
  const img = { clientWidth: 378, clientHeight: 280, naturalWidth: 864, naturalHeight: 1536 };
  assert.deepEqual(scaleBoxes(box, img), boxesToOriginal(box, S(378, 280), S(864, 1536)));
  assert.equal(scaleBoxes(box, null), null);
  assert.equal(scaleBoxes(box, { ...img, clientWidth: 0 }), null, "hidden / not laid out");
  assert.equal(scaleBoxes(box, { ...img, naturalWidth: 0 }), null, "not decoded yet: never zeroed, never scale 1");
  assert.equal(scaleBoxes(box, { clientWidth: 378, naturalWidth: 864 }), null, "no heights: cannot place a letterbox");
});

test("every Fixer surface maps through scaleBoxes -- one formula on desktop, phone and FixTab", () => {
  const sb = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");
  const mobileStart = sb.indexOf("function LoomMobile({");
  const desktop = sb.slice(sb.indexOf("function LoomV2("), mobileStart), mobile = sb.slice(mobileStart);
  assert.equal((desktop.match(/scaleBoxes\(fixBoxes, fixImgRef\.current\)/g) || []).length, 3,
    "the desktop's price effect, its ✦ Fix disabled check and its click all use it");
  assert.match(mobile, /return scaleBoxes\(fixBoxes, img\);/, "phoneFixBoxes() maps through it");
  // the desktop CSS that letterboxes is why the rect matters -- if it changes, re-check the probe
  assert.match(sb, /\.lv-fixwrap img\{[^}]*object-fit:contain/);
  const fixTab = readFileSync(path.join(__dirname, "../../gallery/src/components/FixTab.jsx"), "utf8");
  assert.ok(fixTab.includes("naturalHeight: img.naturalHeight"), "FixTab remembers the heights too");
});

// Kept as source pins: the desktop Loom and FixTab have no render harness here; the phone's
// identical shape is driven for real in loom-mobile-view.test.js ("the picture's load ...").
test("a picture's load re-runs the price on every Fixer surface (review 2, F1)", () => {
  const sb = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");
  const mobileStart = sb.indexOf("function LoomMobile({");
  const desktop = sb.slice(sb.indexOf("function LoomV2("), mobileStart), mobile = sb.slice(mobileStart);
  for (const [name, part] of [["desktop", desktop], ["phone", mobile]]) {
    assert.match(part, /const \[fixImgTick, setFixImgTick\] = useState\(0\);/, name + " counts the loads");
    assert.match(part, /, fixBoxes, fixImgTick\]\);/, name + "'s price effect depends on the load count");
  }
  assert.match(desktop, /const onFixImgLoad = \(\) => \{ fixPaint\(\); setFixImgTick\(\(n\) => n \+ 1\); \};/);
  assert.match(desktop, /onLoad=\{onFixImgLoad\}/);
  assert.match(mobile, /onLoad=\{\(\) => \{ fixPaint\(\); setFixImgTick\(\(n\) => n \+ 1\); \}\}/);
  const fixTab = readFileSync(path.join(__dirname, "../../gallery/src/components/FixTab.jsx"), "utf8");
  assert.match(fixTab, /onLoad=\{\(\) => \{ paint\(\); setImgTick\(\(n\) => n \+ 1\); \}\}/);
  assert.match(fixTab, /\}, \[source, boxes, imgTick\]\);/, "FixTab's build re-runs on a load");
  assert.match(fixTab, /\[source, boxes, imgTick, probe\.refresh\]/, "...and so does its re-price");
});

test("every Fixer surface shuts ✦ Fix when no box is on the picture, and says why (review 2, F3)", () => {
  const sb = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");
  assert.match(sb, /!\(scaleBoxes\(fixBoxes, fixImgRef\.current\) \|\| \[\]\)\.length/, "desktop button");
  assert.match(sb, /fixPriceEntry && fixPriceEntry\.offPicture \? FIX_NO_BOX_ON_PICTURE/, "desktop line");
  assert.match(sb, /!\(phoneFixBoxes\(\) \|\| \[\]\)\.length/, "phone button");
  const fixTab = readFileSync(path.join(__dirname, "../../gallery/src/components/FixTab.jsx"), "utf8");
  assert.match(fixTab, /\|\| !\(scaleBoxes\(boxes, scaleEl\(\)\) \|\| \[\]\)\.length;/, "FixTab button");
  assert.match(fixTab, /scaled && !scaled\.length\) \? FIX_NO_BOX_ON_PICTURE/, "FixTab badge line");
});

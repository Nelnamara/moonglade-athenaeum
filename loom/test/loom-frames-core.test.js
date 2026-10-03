import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  FRAME_THUMBS_MAX, FRAME_GONE_TEXT, collectFrameIds, frameThumbSrc, frameGone, applyFrameThumbs, emptyFrameFix,
} from "../src/loom-frames-core.js";

/* GitHub #62: a frame spliced before 3.15.0 is a PixAI media id with no thumbs/<id>.jpg, so the
   board card, Deep Focus and the drawer's frame box drew a broken picture. On opening a board the
   Loom posts its frame ids once (POST /api/loom/frame-thumbs fills a missing thumbnail once from
   PixAI); a filled one is re-drawn with a cache-busting suffix, and one PixAI could not give back
   is drawn as "Frame not on this machine. Splice again." instead of a broken image. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "..", "master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/\s.*$/gm, "");
const CODE = codeOnly(SRC);

const board = () => ({ name: "b", assets: [{ id: "as1", kind: "image", mediaId: "9001" }], acts: [
  { id: "a", cards: [
    { id: "c1", openFrame: { mediaId: "111" }, closeFrame: { mediaId: "222" }, refs: [{ mediaId: "9002" }], cast: ["as1"],
      anchor: { shot: "x", frame: "9003" }, takes: [{ n: 1, mid: "7001", settings: { openFrame: { mediaId: "9004" } } }] },
    { id: "c2", openFrame: { mediaId: "222" }, closeFrame: { thumbId: "t1", mediaId: "" } },
  ] },
  { id: "b", cards: [
    { id: "c3", openFrame: { mediaId: "local_0123456789ab" }, closeFrame: { mediaId: "333", thumbId: "t2" } },
    { id: "c4", openFrame: { mediaId: " 444 " }, closeFrame: {} },
    { id: "c5" },
  ] },
] });

describe("collectFrameIds: the board's open and close frames that are PixAI media ids", () => {
  test("frames only, digits only, no picture the thumbs store holds, de-duplicated in board order", () => {
    assert.deepEqual(collectFrameIds(board()), ["111", "222", "444"]);
  });
  test("cast, references, anchors and take snapshots are not frames on the board", () => {
    const ids = collectFrameIds(board());
    for (const x of ["9001", "9002", "9003", "9004", "7001"]) assert.ok(!ids.includes(x), x);
  });
  test("nothing to collect from no board", () => {
    for (const p of [null, undefined, {}, { acts: null }, { acts: [{ cards: null }] }]) assert.deepEqual(collectFrameIds(p), []);
  });
  test("reading writes nothing onto the board", () => {
    const p = board();
    const before = JSON.stringify(p);
    collectFrameIds(p);
    assert.equal(JSON.stringify(p), before);
  });
  test("the server's cap", () => assert.equal(FRAME_THUMBS_MAX, 60));
});

describe("frameThumbSrc / frameGone: what a frame slot draws", () => {
  const thumbs = { t1: "data:image/jpeg;base64,AAAA" };
  test("as before: the thumbs store first, else the shared thumbnail; nothing for no frame", () => {
    const fix = emptyFrameFix();
    assert.equal(frameThumbSrc({ thumbId: "t1", mediaId: "5" }, thumbs, fix), thumbs.t1);
    assert.equal(frameThumbSrc({ mediaId: "5" }, thumbs, fix), "/thumbs/5.jpg");
    assert.equal(frameThumbSrc({}, thumbs, fix), null);
    assert.equal(frameThumbSrc(null, thumbs, fix), null);
    assert.equal(frameThumbSrc({ mediaId: "5" }, thumbs, undefined), "/thumbs/5.jpg", "no fix yet: today's answer");
  });
  test("a frame PixAI could not give back draws nothing (the placeholder says why); a filled one is re-asked for", () => {
    let fix = applyFrameThumbs(emptyFrameFix(), { fetched: ["5"], gone: ["6"] }, 1234);
    assert.equal(frameThumbSrc({ mediaId: "5" }, thumbs, fix), "/thumbs/5.jpg?v=1234");
    assert.equal(frameThumbSrc({ mediaId: "6" }, thumbs, fix), null);
    assert.equal(frameGone({ mediaId: "6" }, fix), true);
    assert.equal(frameGone({ mediaId: "5" }, fix), false);
    assert.equal(frameGone({ mediaId: "6", thumbId: "t1" }, fix), false, "a stored picture is never gone");
    assert.equal(frameGone({}, fix), false);
    fix = applyFrameThumbs(fix, { fetched: [], gone: ["7"] }, 99);
    assert.ok(fix.gone.has("6") && fix.gone.has("7"), "what was known stays known");
    assert.equal(fix.bust["5"], 1234);
    assert.equal(FRAME_GONE_TEXT, "Frame not on this machine. Splice again.");
  });
  test("applyFrameThumbs never mutates the fix it was given", () => {
    const a = emptyFrameFix();
    const b = applyFrameThumbs(a, { fetched: ["1"], gone: ["2"] }, 5);
    assert.notEqual(a, b);
    assert.equal(a.gone.size, 0);
    assert.deepEqual(a.bust, {});
  });
});

describe("the wiring: once per board per session, from an effect, never a board write", () => {
  const hook = () => {
    const i = CODE.indexOf("function useFrameThumbs(project, activeId) {");
    assert.ok(i >= 0, "useFrameThumbs is gone -- re-point this test, never drop it");
    return CODE.slice(i, CODE.indexOf("\n}\n", i));
  };
  test("the effect posts the board's frame ids once per board, and only fills the per-session fix", () => {
    const h = hook();
    assert.match(h, /if \(!activeId \|\| !isBoard\(project\) \|\| FRAME_THUMBS_CHECKED\.has\(activeId\)\) return;/);
    assert.match(h, /FRAME_THUMBS_CHECKED\.add\(activeId\);/);
    assert.match(h, /const ids = collectFrameIds\(project\);/);
    assert.match(h, /setFix\(\(f\) => applyFrameThumbs\(f, ans, Date\.now\(\)\)\)/);
    assert.match(h, /\}, \[activeId, project\]\);/);
    assert.doesNotMatch(h, /setProject|persistBoard|saveBoardNow|queueRef|sSet\(|storeThumb/, "opening a board still writes nothing");
    assert.match(CODE, /const FRAME_THUMBS_CHECKED = new Set\(\);/);
    assert.match(CODE, /const frameFix = useFrameThumbs\(project, activeId\);/);
  });
  test("the post goes to the local route in chunks of the cap, with the session's token", () => {
    const i = CODE.indexOf("async function checkFrameThumbs(ids) {");
    assert.ok(i >= 0);
    const b = CODE.slice(i, CODE.indexOf("\n}\n", i));
    assert.match(b, /fetch\("\/api\/loom\/frame-thumbs", \{ method: "POST"/);
    assert.match(b, /csrf: await loomCsrf\(\), media_ids: ids\.slice\(i, i \+ FRAME_THUMBS_MAX\)/);
  });
  test("both views draw frames through frameThumbSrc, and say so where a frame is gone", () => {
    assert.equal((CODE.match(/const frameSrc = \(f\) => frameThumbSrc\(f, thumbs, frameFix\);/g) || []).length, 2, "LoomV2 and LoomMobile");
    assert.doesNotMatch(CODE, /"\/thumbs\/" \+ f\.mediaId \+ "\.jpg"/, "no frame src built by hand any more");
    assert.match(CODE, /<span className="lv-cframeph">\{frameGone\(e\.c\.openFrame, frameFix\) \? FRAME_GONE_TEXT : e\.c\.mode\}<\/span>/, "the board card");
    assert.match(CODE, /\{img \? <img src=\{img\} alt=\{which\} \/> : frame && frame\.mediaId && !frame\.thumbId \? FRAME_GONE_TEXT : "＋ attach frame"\}/,
      "a frame slot holding a frame that is gone says so, not '+ attach frame'");
    assert.match(CODE, /: frameGone\(c\.openFrame, frameFix\) \? FRAME_GONE_TEXT : "no frame"\}/, "the phone's Deep Focus, open");
    assert.match(CODE, /: frameGone\(c\.closeFrame, frameFix\) \? FRAME_GONE_TEXT : "no frame"\}/, "the phone's Deep Focus, close");
    assert.equal((CODE.match(/frameFix=\{frameFix\}/g) || []).length, 2, "App hands it to both views");
  });
});

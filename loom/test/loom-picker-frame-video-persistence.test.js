import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { shotVideoRefs, pickVideoTarget } from "../src/loom-core.js";

/* Follow-up to loom-reference-picker-corruption.test.js / commit 2e714fd (branch
   loom-reference-picker-corruption). That fix durably persisted a pick made in the r2v/
   Multi-Reference bank (bank:"primary", mode:"r2v") -- before it, a pick only ever wrote
   into <mg-generate-drawer>'s own private in-memory slots, silently discarded the next
   time any host-tracked field changed and the prefill effect (master-storyboard.jsx, the
   useEffect around active.c.mode/duration/cast/refs/etc) rebuilt the drawer's banks fresh
   from buildShotPayload(). It deliberately left two other banks on the SAME ephemeral-only
   behavior (still correct for a submit -- the drawer's own payload() reads its live slots
   directly -- but invisible to Deep Focus's own frame/ref UI, the composed prompt, and any
   other host-side view of the shot, and wiped the moment anything else re-triggers prefill):

     1. i2v/flf mode's Start Frame / End Frame slots (bank:"primary", mode:"i2v"|"flf") --
        picking one must durably land in c.openFrame / c.closeFrame.
     2. r2v mode's SEPARATE video-reference bank (bank:"vid") -- picking a video must
        durably land in c.refs (kind:"video"), which -- unlike image refs' .mediaId --
        stores its media id in .source as a numeric string (see shotPayload()'s `vids`
        computation in loom-core.js).

   Part 1 (pickVideoTarget/shotVideoRefs) is pure logic, tested directly against
   loom-core.js like pickTarget()'s own suite. Part 2 (the mg-pick-request handler actually
   calling into that logic, and the i2v/flf frame branch, which needs no loom-core.js
   helper at all -- slot 0/1 map unambiguously to openFrame/closeFrame) lives in a React
   component with no jsdom in this test runner -- source-presence assertions are the
   established pattern (see loom-picker-video-import.test.js, mg-generate-drawer-parity.
   test.js) for pinning behavior there. */

describe("pickVideoTarget()/shotVideoRefs() -- pure logic for the r2v video-reference bank", () => {
  function makeEntry(refs) {
    return { c: { id: "shot1", refs } };
  }

  test("shotVideoRefs() only counts video refs that already resolve to a numeric media id", () => {
    const entry = makeEntry([
      { id: "r1", kind: "video", tag: "@video1", source: "9001" },
      { id: "r2", kind: "image", tag: "@image1", source: "9002" },        // wrong kind
      { id: "r3", kind: "video", tag: "@video2", source: "" },            // not yet resolved
      { id: "r4", kind: "video", tag: "@video3", source: "not-a-number" }, // not yet resolved
      { id: "r5", kind: "video", tag: "@video4", source: "9003" },
    ]);
    const items = shotVideoRefs(entry);
    assert.deepEqual(items.map((it) => it.id), ["r1", "r5"]);
  });

  test("picking on an EXISTING filled slot replaces that ref's picture, not some other one", () => {
    const entry = makeEntry([
      { id: "r1", kind: "video", tag: "@video1", source: "9001" },
      { id: "r2", kind: "video", tag: "@video2", source: "9002" },
    ]);
    assert.deepEqual(pickVideoTarget(entry, 0), { type: "replace", id: "r1" });
    assert.deepEqual(pickVideoTarget(entry, 1), { type: "replace", id: "r2" });
  });

  test("picking into a slot BEYOND the shot's current video bank appends a new ref, tagged past every video tag in use", () => {
    const entry = makeEntry([
      { id: "r1", kind: "video", tag: "@video1", source: "9001" },
    ]);
    // The bank only has 1 filled slot -- slot 1 is the "+ add" placeholder.
    const plan = pickVideoTarget(entry, 1);
    assert.deepEqual(plan, { type: "append", tag: "@video2" });
  });

  test("a not-yet-resolved video ref's tag is still protected against collision on append", () => {
    // Deep Focus's own "+ Video" button assigns a tag immediately (addRef()), before the
    // owner has typed anything into the "file name or URL" field -- shotVideoRefs() (slot
    // alignment) correctly ignores this unresolved ref, but nextTag() must still see its
    // tag, or a pick appended right after could mint a DUPLICATE "@video2".
    const entry = makeEntry([
      { id: "r1", kind: "video", tag: "@video1", source: "9001" },
      { id: "r2", kind: "video", tag: "@video2", source: "" },
    ]);
    const plan = pickVideoTarget(entry, 1); // slot 1 is past shotVideoRefs()'s single resolved item
    assert.deepEqual(plan, { type: "append", tag: "@video3" });
  });

  test("an empty video bank appends at @video1", () => {
    const entry = makeEntry([]);
    assert.deepEqual(pickVideoTarget(entry, 0), { type: "append", tag: "@video1" });
  });
});

describe("master-storyboard.jsx: mg-pick-request durably persists i2v/flf frames and r2v video refs", () => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");

  test("loom-core.js's pickVideoTarget is imported", () => {
    assert.match(src, /pickVideoTarget/, "master-storyboard.jsx must import pickVideoTarget from ./src/loom-core.js to persist a video-bank pick");
  });

  test("i2v/flf's primary bank writes a completed pick into c.openFrame/c.closeFrame, not just the drawer's own slot", () => {
    assert.match(src, /reqMode === "i2v" \|\| reqMode === "flf"/,
      "the handler must branch on the i2v/flf primary bank specifically, the same way it already branches on the r2v/primary case");
    assert.match(src, /slot === 1 \? "closeFrame" : "openFrame"/,
      "slot 0 must resolve to openFrame and slot 1 (flf's End Frame, the only mode that ever requests slot 1) to closeFrame");
  });

  test("r2v's separate video-reference bank (bank:\"vid\") goes through pickVideoTarget, not the ephemeral-only fallback", () => {
    assert.match(src, /bank === "vid"/, "the handler must have a dedicated branch for the video-reference bank");
    assert.match(src, /pickVideoTarget\(a, slot\)/, "the vid-bank branch must call pickVideoTarget to decide replace-vs-append");
  });

  test("a replaced video ref writes into r.source (a numeric string), not r.mediaId -- the shape shotPayload()'s `vids` computation reads", () => {
    assert.match(src, /r\.id !== plan\.id \? r : \{ \.\.\.r, source: String\(mid\), thumbId: "" \}/,
      "video refs carry their media id in .source, per loom-core.js's shotPayload() `vids` filter -- writing .mediaId here would be silently invisible to generation");
  });

  test("an appended video ref is built with kind:\"video\" and the plan's tag", () => {
    assert.match(src, /buildNewRef\("video", uid\(\)\), tag: plan\.tag, source: String\(mid\)/,
      "a genuinely new video reference (past everything the shot's video bank already supplies) must persist as a real c.refs entry, not vanish on the next prefill");
  });

  test("the original ephemeral-only fallback call shape survives (pinned by tests/test_web_pick.py's S5 privacy-blur regression guard)", () => {
    assert.match(src, /openPick\(\(mid, thumb, isVideo, duration, isNsfw\) => e\.detail\.respond\(mid, thumb, isNsfw\)/,
      "tests/test_web_pick.py pins this exact one-liner call shape (is_nsfw must reach respond()) -- it must remain reachable as the final fallback for any bank/mode combination the dedicated branches don't recognize");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Concurrent generations (owner-approved 2026-07-23): PixAI allows multiple tasks running
// at once, and the Loom's own per-shot generation pipeline (useGenerationPipeline inside
// master-storyboard.jsx) already turns out to be built that way -- genState/pendingTaskId
// are keyed per SHOT (card id), and pollShot is fired without being awaited, so one shot
// finishing has never blocked another from starting. This file locks in the two guarantees
// the feature's owner-approved scope calls out explicitly:
//   1. Per-shot integrity: a shot already "wip" must still refuse a second submit for THAT
//      shot (batchGenerate's own todo filter, and the single-shot path via the shared
//      <mg-generate-drawer> -- see loom-gen-drawer-loom-ctx.test.js and
//      mg-generate-drawer-concurrent.test.js for that half).
//   2. Two DIFFERENT shots can render simultaneously: generateShot submits and returns
//      (its own await only covers the /api/loom/generate POST, not the render), then hands
//      polling to a fire-and-forget pollShot() call -- batchGenerate's per-shot loop moves
//      on to the NEXT shot's submit while earlier ones are still rendering in the
//      background, not one full generate-then-wait cycle per shot.
//
// master-storyboard.jsx has no JSX/React test harness in this suite (no jsdom) --
// source-presence assertions are the established pattern (mirrors loom-cost-badges.test.js,
// loom-v2-dead-generate-shot-prop.test.js). Real interaction verification needs a browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

// Session P (BUILD-w5-p §3.3/§3.4, review F12/F14) CHANGED ON PURPOSE what three of these pins
// hold. "wip" is no longer the lock: the card's own in-flight marker is (beginRender, saved
// before the POST), a shot is in the batch when it NEEDS a render (no ★ take, nothing in flight
// -- needsRender), and the batch sends only what it priced (the confirmed fingerprint). Each pin
// below is the replacement property, and each is at least as strict as the one it replaces.
import { needsRender } from "../src/loom-takes-core.js";

const genBody = () => {
  const m = src.match(/const generateShot = async \(entry, opts = \{\}\) => \{[\s\S]*?\n  \};/);
  assert.ok(m, "expected to find the generateShot implementation");
  return m[0];
};
const loopBody = () => {
  const m = src.match(/for \(const \[i, e\] of todo\.entries\(\)\) \{[\s\S]*?\n    \}/);
  assert.ok(m, "expected to find batchGenerate's per-shot submit loop");
  return m[0];
};

describe("Generate all (batchGenerate) never resubmits a shot that is already rendering", () => {
  test("the todo list is the CURRENT board's shots that need a render (needsRender), not a status filter", () => {
    assert.match(src, /const board = projectRef\.current \? flat\(projectRef\.current\) : \(entries \|\| \[\]\);\n\s*const todo = board\.filter\(\(e\) => needsRender\(e\.c\)\);/,
      "batchGenerate must pick its shots from the store's current board with needsRender -- a " +
      "status filter re-renders a rendered shot whose retake failed (F14) and a stale entries " +
      "list sends content the owner has since changed (F12)");
    // What needsRender means, run rather than read:
    assert.equal(needsRender({ status: "wip", pendingSubmitId: "S" }), false, "a send in flight");
    assert.equal(needsRender({ status: "wip", pendingTaskId: "T" }), false, "a task being polled");
    assert.equal(needsRender({ status: "wip" }), false, "a marker-less wip (a pre-P crash) is never guessed at by a batch");
    assert.equal(needsRender({ status: "error", resultMid: "M1" }), false, "a failed retake keeps its ★ take (F14)");
    assert.equal(needsRender({ status: "done", resultMid: "M1", imported: true }), false, "imported footage is a take");
    assert.equal(needsRender({ status: "todo" }), true);
    assert.equal(needsRender({ status: "error" }), true, "a shot with no take whose render failed may be rendered again");
  });

  test("generateShot latches BEFORE its first await, and saves the lock BEFORE the network submit", () => {
    const fn = genBody();
    const latch = fn.indexOf("inflightRef.current.add(cardId);");
    const firstAwait = fn.indexOf("await ");
    const lock = fn.indexOf("beginRender(");
    const flush = fn.indexOf("await saveBoardNow(boardId)");
    const post = fn.indexOf('fetch("/api/loom/generate"');
    assert.ok(latch >= 0 && firstAwait > latch, "the synchronous latch must be set before generateShot's first await");
    assert.ok(lock >= 0 && flush > lock && post > flush,
      "the in-flight marker (beginRender) must be written and SAVED before /api/loom/generate is " +
      "called -- a batch, a second click or another tab reads it and must see the shot as taken");
  });
});

describe("Two different shots can render at the same time", () => {
  test("generateShot hands polling to pollShot without awaiting it (fire-and-forget)", () => {
    assert.match(genBody(), /(?<!await )pollShot\(cardId, cls\.taskId, startedAt, boardId\);/,
      "generateShot now awaits pollShot -- a batch run (or a resumed poll) would block on " +
      "one shot's ENTIRE render before ever submitting the next, instead of letting " +
      "multiple shots render concurrently");
  });

  test("batchGenerate's per-shot loop only awaits the SUBMIT (generateShot), never a full render", () => {
    const loop = loopBody();
    assert.match(loop, /await generateShot\(e, \{ skipConfirm: true, onlyIfNeeded: true, confirmedFp: fps\[i\], expectFree: covered\[i\],/,
      "each shot goes out pre-confirmed, held to the fingerprint the confirm priced (F12) and " +
      "sent expect_free only when the pool-aware tally counted it covered (F13)");
    // The loop's only other await is the deliberate stagger between SUBMITS (so requests
    // don't collide) -- not a wait for any shot's render to finish.
    assert.match(loop, /await new Promise\(\(res\) => setTimeout\(res, 2200\)\);/,
      "expected the submit-to-submit stagger between shots, not a wait on completion");
    assert.doesNotMatch(loop, /await pollShot/, "batchGenerate must never await a shot's own render");
  });

  test("per-shot generation state is keyed by card id, not one global flag", () => {
    // genState/the render markers are all per-card -- this is WHY two shots don't fight over
    // one lock: there is no single "is anything rendering" flag anywhere in the pipeline.
    assert.match(src, /setGenState\(\(s\) => \(\{ \.\.\.s, \[c\.id\]: \{ phase: "submitting"/,
      "generateShot's own submitting state is no longer keyed per-shot");
    assert.match(genBody(), /patchCardNow\(cardId, \(cc\) => adoptTask\(cc, submitId, cls\.taskId\)\);/,
      "the persisted resume state (the adopted task id) is no longer written on this shot alone");
    assert.match(src, /const inflightRef = useRef\(new Set\(\)\);/,
      "the render latch must be a per-card set, never one flag");
  });
});

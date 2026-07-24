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

describe("Generate all (batchGenerate) never resubmits a shot that is already wip", () => {
  test("the todo filter excludes status === \"wip\" alongside \"done\"", () => {
    assert.match(
      src,
      /const todo = entries\.filter\(\(e\) => e\.c\.status !== "done" && e\.c\.status !== "wip"\);/,
      "batchGenerate's todo filter no longer excludes already-wip shots -- a batch run " +
      "could resubmit a shot that's already rendering (started individually via the " +
      "drawer, or reattached by the resume-on-load effect), firing a duplicate " +
      "/api/loom/generate for it"
    );
  });

  test("generateShot marks the shot wip via setCardStatus BEFORE the network submit", () => {
    const m = src.match(/const generateShot = async \(entry, opts = \{\}\) => \{[\s\S]*?\n  \};/);
    assert.ok(m, "expected to find the generateShot implementation");
    const fn = m[0];
    const wipIdx = fn.indexOf('setCardStatus(c.id, { status: "wip" });');
    const fetchIdx = fn.indexOf('fetch("/api/loom/generate"');
    assert.ok(wipIdx >= 0, "generateShot no longer marks the card wip before submitting");
    assert.ok(wipIdx < fetchIdx,
      "the card must be marked wip BEFORE the network call, not after -- a batch run (or a " +
      "second click) reads card.status synchronously and would otherwise still see the " +
      "shot as eligible while its submit is in flight");
  });
});

describe("Two different shots can render at the same time", () => {
  test("generateShot hands polling to pollShot without awaiting it (fire-and-forget)", () => {
    const m = src.match(/const generateShot = async \(entry, opts = \{\}\) => \{[\s\S]*?\n  \};/);
    assert.ok(m);
    assert.match(m[0], /(?<!await )pollShot\(c\.id, d\.task_id, startedAt\);/,
      "generateShot now awaits pollShot -- a batch run (or a resumed poll) would block on " +
      "one shot's ENTIRE render before ever submitting the next, instead of letting " +
      "multiple shots render concurrently");
  });

  test("batchGenerate's per-shot loop only awaits the SUBMIT (generateShot), never a full render", () => {
    const m = src.match(/for \(const e of todo\) \{[\s\S]*?\n    \}/);
    assert.ok(m, "expected to find batchGenerate's per-shot submit loop");
    assert.match(m[0], /await generateShot\(e, \{ skipConfirm: true \}\);/);
    // The loop's only other await is the deliberate stagger between SUBMITS (so requests
    // don't collide) -- not a wait for any shot's render to finish.
    assert.match(m[0], /await new Promise\(\(res\) => setTimeout\(res, 2200\)\);/,
      "expected the submit-to-submit stagger between shots, not a wait on completion");
    assert.doesNotMatch(m[0], /await pollShot/, "batchGenerate must never await a shot's own render");
  });

  test("per-shot generation state is keyed by card id, not one global flag", () => {
    // genState/pendingTaskId/status are all per-card -- this is WHY two shots don't fight
    // over one lock: there is no single "is anything rendering" flag anywhere in the
    // pipeline, only per-id state.
    assert.match(src, /setGenState\(\(s\) => \(\{ \.\.\.s, \[c\.id\]: \{ phase: "submitting"/,
      "generateShot's own submitting state is no longer keyed per-shot");
    assert.match(src, /setCardStatus\(c\.id, \{ pendingTaskId: d\.task_id, genStartedAt: startedAt \}\);/,
      "the persisted resume state (pendingTaskId) is no longer keyed per-shot");
  });
});

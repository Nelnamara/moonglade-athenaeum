import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// AUDIT_2026-07-21.md, owner-2026-07-23 lens, two rows investigated together (same root
// cause): "The Loom's own Activity tracker widget is functionally dead" (shows the initial
// job entry, then never updates, while the gallery's own tracker -- reading the SAME
// backend job data -- shows live progress) and "Status mismatch: a generation in the Loom
// shows as actively rendering while the Job Tracker simultaneously lists the same task as
// rendered/still."
//
// Root cause: generateShot's own comment (a few lines above pollShot) already says why the
// Loom calls Jobs.register() instead of Jobs.track() -- pollShot below owns real completion
// handling, so a second poll loop would be redundant. That reasoning is right about polling,
// but it left a gap: static/mg-notify.js's OWN gallery-side poller (Jobs.poll(), used by
// runTask via Jobs.track()) calls `JobsCard.refresh()` the INSTANT it sees phase==='done' or
// 'failed' (mg-notify.js:1048-1049) -- that immediate nudge is what makes the gallery's
// tracker look "live". The Loom's pollShot has never done the equivalent: it updates
// genState/setCardStatus (the per-shot badge, which the owner likes and this file does not
// touch) but never tells the shared Activity tray (JobsCard) to refresh itself. The tray is
// therefore only ever as fresh as its OWN independent, unsynchronized ~2.5-7s poll cycle
// (static/mg-notify.js's JobsCard.schedule()) instead of catching up the moment pollShot --
// the demonstrably live, real-time signal the per-shot badge already trusts -- learns the
// truth. That extra, unsynchronized hop is what let the two surfaces visibly disagree, and
// what let the tray read as frozen when that independent cycle lagged.
//
// Fix: pollShot's own tick() nudges window.JobsCard.refresh() on the SAME two branches
// mg-notify.js's Jobs.poll() does (done, failed) -- mirroring the already-working gallery
// pattern exactly, without adding any new poll loop and without touching the per-shot badge.
//
// master-storyboard.jsx has no JSX/React test harness in this suite (no jsdom) --
// source-presence assertions are the established pattern (mirrors loom-cost-badges.test.js,
// loom-v2-dead-generate-shot-prop.test.js, loom-batch-generate-concurrency.test.js).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

function pollShotBody() {
  const m = src.match(/const pollShot = \([\s\S]*?\n  \};/);
  assert.ok(m, "expected to find the pollShot implementation");
  return m[0];
}

describe("pollShot nudges the shared Activity tracker exactly when it learns the real state", () => {
  test("the done branch calls window.JobsCard.refresh(), same as mg-notify.js's own Jobs.poll()", () => {
    const fn = pollShotBody();
    const doneIdx = fn.indexOf('cls.phase === "done"');
    const failedIdx = fn.indexOf('cls.phase === "failed"');
    assert.ok(doneIdx >= 0 && failedIdx >= 0, "expected both done and failed branches in pollShot");
    const doneBranch = fn.slice(doneIdx, failedIdx);
    assert.match(
      doneBranch,
      /if \(window\.JobsCard && window\.JobsCard\.refresh\) window\.JobsCard\.refresh\(\);/,
      "pollShot's done branch never nudges the shared Activity tracker (window.JobsCard.refresh()) " +
      "-- the tray only catches up on its own independent, unsynchronized poll cycle instead of the " +
      "moment this shot's own (working, live) poll learns the task is done"
    );
  });

  test("the failed branch calls window.JobsCard.refresh() too", () => {
    const fn = pollShotBody();
    const failedIdx = fn.indexOf('cls.phase === "failed"');
    const ceilingIdx = fn.indexOf("elapsed > POLL_CEILING_MS");
    assert.ok(failedIdx >= 0 && ceilingIdx >= 0, "expected both failed and give-up branches in pollShot");
    const failedBranch = fn.slice(failedIdx, ceilingIdx);
    assert.match(
      failedBranch,
      /if \(window\.JobsCard && window\.JobsCard\.refresh\) window\.JobsCard\.refresh\(\);/,
      "pollShot's failed branch never nudges the shared Activity tracker -- a shot that fails would " +
      "leave the tray showing stale 'running' state until its own independent cycle happens to refresh"
    );
  });

  test("the per-shot badge's own state writes are untouched (setGenState/setCardStatus still fire first)", () => {
    // Guard-rail: the owner explicitly likes the per-shot RENDERING.../done/failed badge and
    // wants it kept as-is. The nudge must be an ADDITION alongside the existing state writes,
    // not a replacement of them.
    const fn = pollShotBody();
    assert.match(fn, /setGenState\(\(s\) => \(\{ \.\.\.s, \[cardId\]: \{ phase: "done", msg: "Done"/,
      "the per-shot badge's own 'done' state write must still be here, unmodified");
    assert.match(fn, /setGenState\(\(s\) => \(\{ \.\.\.s, \[cardId\]: \{ phase: "error", msg: cls\.msg \} \}\)\);/,
      "the per-shot badge's own 'failed' state write must still be here, unmodified");
  });
});

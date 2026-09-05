import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";

import { WAIT_MIN_TILE, isQueuedRun, queueWaitText } from "../../gallery/src/gen/queueWait.js";

/* ROADMAP, "Queue-wait on the dock's queued tiles -- the last slice of 'starts in ~N'"
   (owner call 2026-08-19, built 2026-09-04).

   The honest queue-wait readout has shipped in the Activity tray's queued rows since
   2026-07-25 (notify/ActivityRow.jsx's .at-eta chip, pinned by mg-notify-queue-phase.test.js).
   The Generate dock's own queued run tiles showed only the mascot and an indeterminate
   shimmer for the very same job. This file pins the dock's half: the SAME figure, from the
   SAME feed, in the SAME words.

   The standing constraint is the whole reason the rule is extracted rather than inlined in
   RunsReel.jsx: /v2/task/wait-time is a QUEUE wait, never a render ETA. It may only be
   shown while the task is actually waiting, it must say WAIT, and nothing about it may tick.
   RunsReel.jsx is JSX and this suite cannot import it, so the decision of whether a figure
   is shown at all lives in gen/queueWait.js -- the same reason hooks/contestSyncFlow.js
   exists -- and is asserted here by calling the real function. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(__dirname, "../../", p), "utf8");
const reel = read("gallery/src/components/RunsReel.jsx");
const dockCss = read("gallery/src/styles/dock.css");
const tray = read("gallery/src/notify/ActivityRow.jsx");
const rule = read("gallery/src/gen/queueWait.js");

const queued = (extra) => Object.assign({ status: "running", started: false }, extra);

describe("the queue-wait readout is shown only while a job is actually queued", () => {
  test("a queued job with a recorded estimate gets the tray's exact wording", () => {
    assert.equal(queueWaitText(queued({ eta_seconds: 27 })), "est. 27s wait");
    // fmtDuration's two-unit form, unchanged -- the dock does not re-format the figure.
    assert.equal(queueWaitText(queued({ eta_seconds: 95 })), "est. 1m 35s wait");
  });

  test("a job a worker has PICKED UP shows nothing", () => {
    // The constraint in one assertion: the instant the task leaves the queue the readout is
    // gone. There is no render ETA to fall back on -- PixAI publishes no progress at all.
    assert.equal(queueWaitText({ status: "running", started: true, eta_seconds: 27 }), "");
  });

  test("an ABSENT `started` field means unknown, not queued", () => {
    // `started` is absent on every non-PixAI job (panel/cli/delete/import) and on rows
    // written before the phase feature. A `!j.started` check would brand all of them queued
    // and quote them a wait they were never given.
    assert.equal(queueWaitText({ status: "running", eta_seconds: 27 }), "");
    assert.equal(isQueuedRun({ status: "running", eta_seconds: 27 }), false);
    assert.equal(isQueuedRun({ status: "running", started: false }), true);
  });

  test("a finished job shows nothing, whatever it still carries", () => {
    for (const status of ["done", "failed", "done_with_errors", "stale"]) {
      assert.equal(queueWaitText({ status, started: false, eta_seconds: 27 }), "",
        "a " + status + " job is not waiting for anything");
    }
  });

  test("an empty queue (0s) is a real answer, not a missing one", () => {
    // `j.eta_seconds &&` would collapse an honest 0 into "no estimate" -- the same
    // truthiness trap the tray's guard avoids.
    assert.equal(queueWaitText(queued({ eta_seconds: 0 })), "est. 0s wait");
  });

  test("a missing or non-finite estimate shows nothing rather than a made-up figure", () => {
    for (const eta of [undefined, null, "27", NaN, Infinity, -Infinity]) {
      assert.equal(queueWaitText(queued({ eta_seconds: eta })), "",
        "eta_seconds " + String(eta) + " must not produce a readout");
    }
  });

  test("a null/undefined job never throws", () => {
    assert.equal(queueWaitText(null), "");
    assert.equal(queueWaitText(undefined), "");
    assert.equal(isQueuedRun(null), false);
  });
});

describe("both surfaces quote the same number in the same words", () => {
  test("the tray still renders `est. <duration> wait`", () => {
    // If the tray's wording ever moves, this fails and the dock is told to move with it --
    // two surfaces quoting the same field in different words is how one of them starts
    // reading as a countdown.
    assert.match(tray, /est\. \{fmtDuration\(j\.eta_seconds\)\} wait/,
      "the Activity tray's readout wording changed; gen/queueWait.js must match it");
  });

  test("both are built from `eta_seconds` -- the field /api/jobs already serves", () => {
    // The dock must NOT poll PixAI a second time for this. The reel already GETs /api/jobs
    // (GenerateDrawer), and the estimate rides that row.
    assert.match(tray, /j\.eta_seconds/);
    assert.match(rule, /j\.eta_seconds/);
    assert.doesNotMatch(rule, /fetch\(|apiGet|wait-time"/,
      "the rule module must not reach for the network -- the figure comes off the jobs feed");
  });
});

describe("the dock's queued tile carries it", () => {
  test("RunsReel renders the readout under the shared rule, not a local copy", () => {
    assert.match(reel, /import \{ WAIT_MIN_TILE, queueWaitText \} from "\.\.\/gen\/queueWait\.js";/,
      "the reel must use the shared rule -- a second copy is how the two surfaces drift");
    assert.match(reel, /const wait = th >= WAIT_MIN_TILE \? queueWaitText\(j\) : "";/,
      "the reel's readout is no longer computed from the shared rule + the tile-size floor");
    assert.match(reel,
      /\{wait \? \(\s*<span className=\{"mgdock-runwait" \+ \(cluster \? " up" : ""\)\}>\{wait\}<\/span>\s*\) : null\}/,
      "the readout span is gone, or no longer rendered under the `wait` guard");
  });

  test("it is added to the tile, and takes nothing away from it", () => {
    // The caption's cost line, the mascot, the halo and the shimmer are all untouched: this
    // feature ADDS one line of text and removes nothing.
    assert.match(reel, /const cost = showCost && !cluster \? costText\(/,
      "the caption's cost line must be unchanged -- the readout does not stand in for it");
    assert.match(reel, /\{cluster \? <ClusterFace count=\{c\.count\} \/> : running \? <RunningFace \/> : null\}/,
      "the mascot/halo/shimmer face must be unchanged");
  });

  test("a tile too small to hold the words shows none of them", () => {
    // Measured against the committed CSS at every tier gen/dockLayout.js can produce
    // (132/104/96/84/64): below 96 the line runs into the mascot and the ellipsis eats the
    // word "wait" -- and a readout that has lost the word "wait" is the exact thing the
    // standing constraint forbids. Same shape as the reel's own REEL_MIN_ROOM.
    assert.equal(WAIT_MIN_TILE, 96);
  });
});

describe("its styling is the tray's role, not a new one", () => {
  test("the class exists and is the same small overlay0 caption the tray uses", () => {
    const css = /\.mgdock-runwait \{[^}]*\}/.exec(dockCss);
    assert.ok(css, ".mgdock-runwait has no rule in dock.css");
    assert.match(css[0], /font-size: 9\.5px/, "the readout must stay at the caption size");
    assert.match(css[0], /color: var\(--overlay0\)/,
      "the readout must keep the tray's own colour role (.at-sub / .mgdock-runcost)");
    assert.match(css[0], /pointer-events: none/,
      "the readout sits inside the tile and must never steal the hover that raises the tooltip");
  });

  test("nothing about it moves", () => {
    // A ticking or animated readout is a countdown, and this number is not one: it is the
    // estimate PixAI gave once, when the job was first seen queued, and nothing recomputes it.
    for (const m of dockCss.match(/\.mgdock-runwait[^{]*\{[^}]*\}/g) || []) {
      assert.doesNotMatch(m, /animation|transition/,
        "the queue-wait readout must not animate -- motion reads as a countdown");
    }
    assert.doesNotMatch(rule, /setInterval|setTimeout|Date\.now/,
      "nothing may tick the estimate down");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// M25 -- the job-detail popover's live "Time Spent" ticker outliving the job it was timing.
//
// openDetail() started a 1s setInterval whenever the job was 'running' at open time, and the
// only thing that ever cleared it was closeDetail() -- which render() calls only when the job
// VANISHES from jobsById, never when it merely finishes. So a generation that completed while
// its popover stayed open rendered its correct final duration on the next poll and then, one
// second later, had it overwritten by the still-live interval with `Date.now()/1000 -
// started_at` + " so far", climbing forever for a job that was already done. That popover
// exists precisely so an owner can diagnose a slow generation without server access (field
// report 2026-07-23), which makes a lying clock the worst thing it could do.
//
// The fix moves the decision into syncTick(j): the clock's lifetime follows the JOB's status,
// re-decided by every renderDetail() (i.e. every poll). Terminal-ness is derived as
// "not 'running'" rather than from a list of finished statuses -- see the related H18, where
// toastTransitions()' hardcoded TERMINAL map forgets 'stale' -- so the tests below deliberately
// exercise 'stale' as well as 'done'.
//
// static/mg-notify.js is a plain global-IIFE <script> (no ES module exports, no build step --
// only loom/ has a bundle, see loom/scripts/build.mjs, which touches master-storyboard.jsx and
// loom/src/ only). So, matching this repo's established convention for it (see
// mg-notify-job-detail.test.js): the self-contained logic is extracted as REAL callables and
// exercised for real -- here with stand-in timers so the 1s interval can be fired on demand --
// and the DOM wiring around it is covered by source-presence assertions.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks these out as CRLF on Windows) -- the extraction regexes
// below anchor on exact `\n` + indent boundaries.
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8")
  .replace(/\r\n/g, "\n");

function extract(re, label) {
  const m = src.match(re);
  assert.ok(m, `expected to find ${label} in static/mg-notify.js -- if it was renamed or ` +
               `re-indented, update this extraction pattern, don't delete the test`);
  return m[0];
}

// stopTick + syncTick, pulled out together: syncTick calls stopTick, and `new Function`'s body
// runs in the GLOBAL scope, not JobsCard's closure, so anything it closes over has to come out
// with it (same technique as mg-notify-job-detail.test.js's MONTHS..fmtDuration block).
const tickBlock = extract(
  /function stopTick\(\)\{[\s\S]*?\n {4}function syncTick\(j\)\{[\s\S]*?\n {4}\}/,
  "the stopTick/syncTick block");

// Everything else syncTick closes over is supplied here as a stand-in: fake timers (so the 1s
// interval is fired on demand instead of waited on), a fake popover element, and a
// renderDetail that mirrors the real one's ONE relevant behavior -- it calls syncTick, which is
// what makes the clock's lifetime follow the job.
function harness() {
  return new Function(`
    var log = { intervals: [], cleared: [], rendered: [], closed: 0 };
    var nextId = 1;
    var detailTick = null, detailJobId = null, jobsById = {};
    var spentEl = { textContent: "" };
    var setInterval = function (fn, ms) { var id = nextId++; log.intervals.push({ id: id, fn: fn, ms: ms }); return id; };
    var clearInterval = function (id) { log.cleared.push(id); };
    function detailEl() { return { querySelector: function () { return spentEl; } }; }
    function renderDetail(j) { log.rendered.push(j.job_id); spentEl.textContent = "FINAL"; syncTick(j); }
    function closeDetail() { log.closed++; stopTick(); detailJobId = null; }
    function fmtDuration(s) { return String(Math.max(0, Math.round(s))) + "s"; }
    ${tickBlock}
    return {
      syncTick: syncTick, stopTick: stopTick, log: log, spent: spentEl,
      ticking: function () { return detailTick !== null; },
      openOn: function (id, jobs) { detailJobId = id; jobsById = jobs; },
      setJobs: function (jobs) { jobsById = jobs; },
      fire: function () {
        var last = log.intervals[log.intervals.length - 1];
        if (!last) throw new Error("no interval was ever registered");
        last.fn();
      }
    };
  `)();
}

const RUNNING = { job_id: "j1", status: "running", started_at: 1000, ts: 1000 };

describe("syncTick -- the live Time Spent clock follows the JOB's status, not the popover", () => {
  test("a running job gets exactly one clock, and repeated repaints don't stack more", () => {
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);
    h.syncTick(RUNNING);
    h.syncTick(RUNNING);
    assert.equal(h.log.intervals.length, 1, "each poll's repaint started another interval");
    assert.equal(h.log.intervals[0].ms, 1000);
    assert.ok(h.ticking());
  });

  test("while the job really is running, the tick writes a live 'so far' figure", () => {
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);
    h.fire();
    assert.match(h.spent.textContent, /so far$/, "the running job's clock stopped updating");
  });

  // THE M25 REGRESSION. Old behavior: the interval body read the job out of jobsById and
  // wrote `Date.now()/1000 - started_at` + " so far" unconditionally, so this assertion fails
  // against it -- the final duration is clobbered by a fictitious, still-growing one.
  test("a job that finishes under an open popover: the tick never overwrites the final duration", () => {
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);                                   // popover opened while running
    const done = { job_id: "j1", status: "done", started_at: 1000, ts: 1130 };
    h.setJobs({ j1: done });                               // the poll sees it finish...
    h.fire();                                              // ...and one second later the clock fires
    assert.doesNotMatch(h.spent.textContent, /so far/,
      "the ticker wrote a live 'X so far' onto a job that had already finished");
    assert.equal(h.ticking(), false, "the clock kept running past the job's completion");
    assert.deepEqual(h.log.rendered, ["j1"], "the popover was not repainted with the true final figure");
  });

  test("a repaint of an already-finished job stops the clock outright", () => {
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);
    assert.ok(h.ticking());
    h.syncTick({ job_id: "j1", status: "done", started_at: 1000, ts: 1130 });
    assert.equal(h.ticking(), false);
    assert.equal(h.log.cleared.length, 1, "the interval was never actually cleared");
  });

  // The H18 concern, from the other side: 'stale' is a real status this file renders with its
  // own glyph, and it is absent from toastTransitions()' TERMINAL map. A fix that copied that
  // map's shape would keep counting forever for exactly the job most likely to have a popover
  // open on it. Deriving terminal-ness as "not running" is what makes these two pass.
  test("'stale' (the server's orphan sweep) stops the clock too, not just done/failed", () => {
    for (const st of ["done", "failed", "done_with_errors", "stale", "some_future_status"]) {
      const h = harness();
      h.openOn("j1", { j1: RUNNING });
      h.syncTick(RUNNING);
      h.syncTick({ job_id: "j1", status: st, started_at: 1000, ts: 1130 });
      assert.equal(h.ticking(), false, `status '${st}' left the Time Spent clock running`);
    }
  });

  test("a stale job the next sweep heartbeats back to 'running' gets its clock back", () => {
    // resolve_orphan_jobs deliberately keeps 'stale' OUT of the server's _JOBS_TERMINAL, so a
    // later sweep can write status:'running' again for the same job. Because the decision is
    // re-made on every repaint, that just restarts the clock.
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);
    h.syncTick({ job_id: "j1", status: "stale", started_at: 1000, ts: 1130 });
    assert.equal(h.ticking(), false);
    h.syncTick(RUNNING);
    assert.equal(h.ticking(), true, "the clock never came back for a job that resumed running");
    assert.equal(h.log.intervals.length, 2);
  });

  test("opening the popover on an already-finished job starts no clock at all", () => {
    const h = harness();
    const done = { job_id: "j1", status: "done", started_at: 1000, ts: 1130 };
    h.openOn("j1", { j1: done });
    h.syncTick(done);
    assert.equal(h.log.intervals.length, 0);
    assert.equal(h.ticking(), false);
  });

  test("a job that vanishes entirely still closes the popover (unchanged guard)", () => {
    const h = harness();
    h.openOn("j1", { j1: RUNNING });
    h.syncTick(RUNNING);
    h.setJobs({});                       // dismissed / aged out of the log
    h.fire();
    assert.equal(h.log.closed, 1, "a dismissed job no longer closes its own popover");
    assert.equal(h.ticking(), false);
  });
});

describe("the tick is wired to the repaint, not to the popover's open/close lifecycle", () => {
  test("renderDetail() re-decides the clock on every repaint (i.e. every poll)", () => {
    const renderDetailFn = extract(/function renderDetail\(j\)\{[\s\S]*?\n {4}\}/, "renderDetail");
    assert.match(renderDetailFn, /syncTick\(j\);/,
      "renderDetail no longer re-decides the clock -- a job finishing under an open popover " +
      "would keep its interval until the popover is closed by hand");
  });

  test("openDetail() no longer owns an interval of its own", () => {
    const openFn = extract(/function openDetail\(jid, anchorEl\)\{[\s\S]*?\n {4}\}/, "openDetail");
    assert.doesNotMatch(openFn, /setInterval/,
      "openDetail starts its own ticker again -- there must be exactly one owner (syncTick), " +
      "or the two can drift apart the way M25 did");
    assert.match(openFn, /stopTick\(\);/,
      "opening the popover on a different row must not inherit the previous job's clock");
  });

  test("terminal-ness is derived, not enumerated (H18's TERMINAL map must not be copied here)", () => {
    const syncFn = extract(/function syncTick\(j\)\{[\s\S]*?\n {4}\}/, "syncTick");
    assert.match(syncFn, /\(j\.status\|\|'running'\)!=='running'/,
      "syncTick must test 'is it still running', not a hardcoded set of finished statuses");
    assert.doesNotMatch(syncFn, /done_with_errors/,
      "syncTick enumerates finished statuses -- that list is exactly what forgets 'stale' (H18)");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// M25 -- the job-detail popover's live "Time Spent" ticker outliving the job it was timing.
//
// (History, kept because the discipline it bought is what this file still guards:) the vanilla
// openDetail() started a 1s setInterval whenever the job was 'running' at open time, and the
// only thing that ever cleared it was closeDetail() -- which render() calls only when the job
// VANISHES from jobsById, never when it merely finishes. So a generation that completed while
// its popover stayed open rendered its correct final duration on the next poll and then, one
// second later, had it overwritten by the still-live interval with `Date.now()/1000 -
// started_at` + " so far", climbing forever for a job that was already done. That popover
// exists precisely so an owner can diagnose a slow generation without server access (field
// report 2026-07-23), which makes a lying clock the worst thing it could do.
//
// The vanilla fix moved the decision into syncTick(j): the clock's lifetime follows the JOB's
// status, re-decided by every renderDetail() (i.e. every poll). Terminal-ness is derived as
// "not 'running'" rather than from a list of finished statuses -- see the related H18, where
// toastTransitions()' hardcoded TERMINAL map forgets 'stale' -- so the tests below deliberately
// exercise 'stale' as well as 'done'.
//
// Port note 2026-08-08 (no-vanilla campaign, component 6): static/mg-notify.js is DELETED.
// The popover is now the Detail component in gallery/src/notify/ActivityTray.jsx, and the
// syncTick discipline survives as React idiom: `running = (job.status||"running")==="running"`
// is computed in the component body (i.e. re-decided on EVERY render/poll repaint), and the
// 1s interval lives in a useEffect gated on that flag with deps [running] -- mount it while
// running, clean it up the moment the job stops being running, remount if a later sweep
// heartbeats it back. This runner has no jsdom/React (loom/package.json: esbuild only), so a
// real render can't happen here; instead, matching this repo's convention for React effects
// (med3-prefill-effect-frame-deps.test.js pins a deps array; the old version of THIS file
// extracted syncTick as a real callable), the self-contained head of Detail -- the `running`
// derivation + the gated effect -- is extracted and REALLY EXECUTED under a faithful little
// effect-commit loop (Object.is dep diff, cleanup-before-rerun, exactly React's contract)
// with stand-in timers, and the JSX wiring around it is covered by source-presence pins.
// One vanilla pin has no React equivalent and was folded away rather than ported: "openDetail
// must stopTick() so a different row doesn't inherit the old job's clock" -- in React,
// switching rows re-renders the SAME mounted Detail with the new job prop, and the interval
// callback is a job-agnostic state bump (`tick(n=>n+1)`); every visible number derives from
// the CURRENT prop at render time, so there is no clock to inherit. Its surviving core --
// exactly one owner of the clock interval -- is pinned below.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks these out as CRLF on Windows) -- the extraction regexes
// below anchor on exact `\n` boundaries.
const src = readFileSync(
  path.join(__dirname, "../../gallery/src/notify/ActivityTray.jsx"), "utf8",
).replace(/\r\n/g, "\n");

function extract(hay, re, label) {
  const m = hay.match(re);
  assert.ok(m, `expected to find ${label} in gallery/src/notify/ActivityTray.jsx -- if it was ` +
               `renamed or restructured, update this extraction pattern, don't delete the test`);
  return m[0];
}

// The Detail component, sliced out so the pins below can't accidentally match Row (which
// legitimately enumerates finished statuses for its OWN concern, the dismiss-button styling)
// or ActivityTray (whose `running` is a count, not a flag).
const detailSrc = extract(src, /function Detail\(\{ job, anchor, onClose \}\) \{[\s\S]*?\n\}/,
  "the Detail component");

// The head of Detail: the `running` derivation through the clock effect, pulled out together
// (the effect closes over `running`, so the derivation has to come out with it -- same
// closure-scope technique as the old file's stopTick/syncTick block). The regex's tail
// anchors on `}, [running]);` -- the deps array ITSELF -- so if the effect ever stops being
// keyed on `running`, extraction fails loudly here rather than a test passing vacuously.
const detailHead = extract(detailSrc,
  /const running = \(job\.status \|\| "running"\) === "running";[\s\S]*?\}, \[running\]\);/,
  "Detail's running derivation + gated clock effect");
assert.ok(detailHead.includes("setInterval"),
  "the extracted effect no longer contains the clock interval -- the extraction grabbed the wrong block");

// Everything the head closes over is supplied as a stand-in: `job` (the prop), `tick` (the
// useState bump), fake timers, and a `useEffect` the harness's commit loop provides.
const evalDetailHead = new Function(
  "job", "useEffect", "tick", "setInterval", "clearInterval",
  detailHead + "\n  return { running: running, startedAt: startedAt };");

// The Time Spent figure itself, extracted as a REAL callable: frozen at job.ts once the job
// is not running, live off Date.now() only while it is. This is the line that makes a
// finished job's final duration final.
const spentLine = extract(detailSrc,
  /const spent = \(running \? \(Date\.now\(\) \/ 1000\) : \(job\.ts \|\| startedAt\)\) - startedAt;/,
  "the spent expression");
const spentOf = new Function("running", "job", "startedAt", spentLine + "\n  return spent;");

// A minimal, faithful stand-in for React's effect contract, one slot's worth: after each
// "render", if the deps array differs element-wise (Object.is) from last commit -- or this is
// the first render -- run the previous cleanup, then the new effect. A `tick` from the fake
// interval re-renders with the same job, exactly what the real setState does.
function harness() {
  const log = { intervals: [], cleared: [], renders: 0, ticks: 0 };
  let nextId = 1;
  let slot = null;      // { deps, cleanup }
  let lastJob = null;
  const fakeSetInterval = (fn, ms) => {
    const id = nextId++;
    log.intervals.push({ id, fn, ms });
    return id;
  };
  const fakeClearInterval = (id) => { log.cleared.push(id); };
  const live = () => log.intervals.filter((i) => log.cleared.indexOf(i.id) === -1);
  function render(job) {
    lastJob = job;
    log.renders++;
    let scheduled = null;
    const useEffect = (cb, deps) => { scheduled = { cb, deps }; };
    const out = evalDetailHead(job, useEffect, tick, fakeSetInterval, fakeClearInterval);
    assert.ok(scheduled, "Detail's head no longer registers its clock effect");
    const changed = !slot
      || slot.deps.length !== scheduled.deps.length
      || scheduled.deps.some((d, i) => !Object.is(d, slot.deps[i]));
    if (changed) {
      if (slot && slot.cleanup) slot.cleanup();
      const ret = scheduled.cb();
      slot = { deps: scheduled.deps, cleanup: typeof ret === "function" ? ret : null };
    }
    return out;
  }
  function tick() { log.ticks++; if (lastJob) render(lastJob); }
  function unmount() { if (slot && slot.cleanup) slot.cleanup(); slot = null; }
  return {
    render, unmount, log,
    ticking: () => live().length > 0,
    fire: () => {
      const l = live();
      if (!l.length) throw new Error("no live interval to fire");
      l[l.length - 1].fn();
    },
  };
}

const RUNNING = { job_id: "j1", status: "running", started_at: 1000, ts: 1000 };

describe("Detail's live Time Spent clock follows the JOB's status, not the popover", () => {
  test("a running job gets exactly one clock, and repeated repaints don't stack more", () => {
    const h = harness();
    h.render(RUNNING);
    h.render(RUNNING);
    h.render(RUNNING);
    assert.equal(h.log.intervals.length, 1, "each poll's repaint started another interval");
    assert.equal(h.log.intervals[0].ms, 1000);
    assert.ok(h.ticking());
  });

  test("while the job really is running, the tick repaints and the figure is live", () => {
    // Port note 2026-08-08: the vanilla tick WROTE the 'so far' string into the DOM itself;
    // the React tick bumps state so the component re-renders and the render writes it. Both
    // halves are exercised: the interval's callback really re-renders, and the spent
    // expression really tracks Date.now() while running (the " so far" suffix wording is a
    // JSX pin in the wiring block below).
    const h = harness();
    h.render(RUNNING);
    const before = h.log.renders;
    h.fire();
    assert.equal(h.log.ticks, 1, "the interval's callback never bumped the tick state");
    assert.ok(h.log.renders > before, "a tick did not repaint -- the figure would freeze while running");
    const startedAt = Date.now() / 1000 - 42;
    const spent = spentOf(true, { ts: 0 }, startedAt);
    assert.ok(Math.abs(spent - 42) < 2,
      "a running job's Time Spent is not tracking the actual clock: " + spent);
  });

  // THE M25 REGRESSION. Old behavior: the interval body read the job out of jobsById and
  // wrote `Date.now()/1000 - started_at` + " so far" unconditionally. In the React shape the
  // same rot would be an effect NOT keyed on `running` (interval survives the status flip) or
  // a spent expression reading Date.now() unconditionally -- both asserted against here.
  test("a job that finishes under an open popover: the tick never overwrites the final duration", () => {
    const h = harness();
    h.render(RUNNING);                                     // popover opened while running
    const done = { job_id: "j1", status: "done", started_at: 1000, ts: 1130 };
    const out = h.render(done);                            // the poll repaints with the finished job
    assert.equal(h.ticking(), false, "the clock kept running past the job's completion");
    assert.equal(h.log.cleared.length, 1,
      "the status flip did not clear the interval -- there is nothing left to fire, so the " +
      "final figure can never be clobbered the M25 way");
    assert.equal(spentOf(false, done, out.startedAt), 130,
      "the finished job's Time Spent is not frozen at ts - started_at (the true final figure)");
  });

  test("a repaint of an already-finished job stops the clock outright", () => {
    const h = harness();
    h.render(RUNNING);
    assert.ok(h.ticking());
    h.render({ job_id: "j1", status: "done", started_at: 1000, ts: 1130 });
    assert.equal(h.ticking(), false);
    assert.equal(h.log.cleared.length, 1, "the interval was never actually cleared");
  });

  // The H18 concern, from the other side: 'stale' is a real status this tray renders with its
  // own glyph, and toastTransitions()' TERMINAL map is exactly the shape that forgets it. A
  // clock gated on "is it still running" -- not on a list of finished statuses -- is what
  // makes these pass, future statuses included.
  test("'stale' (the server's orphan sweep) stops the clock too, not just done/failed", () => {
    for (const st of ["done", "failed", "done_with_errors", "stale", "some_future_status"]) {
      const h = harness();
      h.render(RUNNING);
      h.render({ job_id: "j1", status: st, started_at: 1000, ts: 1130 });
      assert.equal(h.ticking(), false, `status '${st}' left the Time Spent clock running`);
    }
  });

  test("a stale job the next sweep heartbeats back to 'running' gets its clock back", () => {
    // resolve_orphan_jobs deliberately keeps 'stale' OUT of the server's _JOBS_TERMINAL, so a
    // later sweep can write status:'running' again for the same job. Because `running` is
    // re-derived on every render and the effect is keyed on it, that just remounts the clock.
    const h = harness();
    h.render(RUNNING);
    h.render({ job_id: "j1", status: "stale", started_at: 1000, ts: 1130 });
    assert.equal(h.ticking(), false);
    h.render(RUNNING);
    assert.equal(h.ticking(), true, "the clock never came back for a job that resumed running");
    assert.equal(h.log.intervals.length, 2);
  });

  test("opening the popover on an already-finished job starts no clock at all", () => {
    const h = harness();
    h.render({ job_id: "j1", status: "done", started_at: 1000, ts: 1130 });
    assert.equal(h.log.intervals.length, 0);
    assert.equal(h.ticking(), false);
  });

  test("a job that vanishes entirely still closes the popover (unchanged guard)", () => {
    // Port note 2026-08-08: the close itself is ActivityTray's job now -- a vanished job
    // makes detailJob null and an effect closes the popover (pinned here); React then
    // unmounts Detail, whose effect cleanup is what stops the clock (exercised for real).
    assert.match(src, /if \(detailId && !detailJob\) closeDetail\(\);/,
      "a dismissed/aged-out job no longer closes its own popover");
    const h = harness();
    h.render(RUNNING);
    h.unmount();                         // what the closeDetail-triggered unmount does
    assert.equal(h.ticking(), false, "unmounting the popover leaked its interval");
    assert.equal(h.log.cleared.length, 1);
  });
});

describe("the tick is wired to the repaint, not to the popover's open/close lifecycle", () => {
  test("the popover repaints from every poll's FRESH jobs list (what renderDetail's re-decide became)", () => {
    // ActivityTray looks detailId up against the current jobs on every render and hands
    // Detail the result as a prop -- so every poll repaints the popover with server truth,
    // and `running` is re-derived from it. That is the syncTick discipline, in React.
    assert.match(src, /const detailJob = detailId \? jobs\.find\(\(j\) => j\.job_id === detailId\) : null;/,
      "the popover's job is no longer looked up fresh each render -- a job finishing under " +
      "an open popover would keep its stale status (and its clock) until closed by hand");
    assert.match(src, /<Detail job=\{detailJob\} anchor=\{anchorRef\.current\} onClose=\{closeDetail\} \/>/,
      "Detail no longer receives the freshly-looked-up job as its prop");
  });

  test("exactly one owner of the clock interval (openDetail's competing ticker stays dead)", () => {
    // The vanilla M25 root cause was TWO owners (openDetail's interval vs syncTick's)
    // drifting apart. The React file must have exactly one setInterval -- the one inside the
    // [running]-keyed effect extracted above.
    const owners = src.match(/setInterval\(/g) || [];
    assert.equal(owners.length, 1,
      "more than one setInterval in ActivityTray.jsx -- two clock owners is exactly how M25 happened");
    assert.match(detailSrc, /\}, \[running\]\);/,
      "the clock effect is no longer keyed on [running] -- a status flip would not stop it");
  });

  test("terminal-ness is derived, not enumerated (H18's TERMINAL map must not be copied here)", () => {
    assert.match(detailSrc, /const running = \(job\.status \|\| "running"\) === "running";/,
      "Detail must test 'is it still running', not a hardcoded set of finished statuses");
    assert.doesNotMatch(detailSrc, /done_with_errors/,
      "Detail enumerates finished statuses -- that list is exactly what forgets 'stale' (H18)");
  });

  test("the ' so far' suffix rides the same running flag as the clock", () => {
    // Port note 2026-08-08: in the vanilla this was the tick-written string; in React it is
    // a render expression, so the pin is on the JSX -- same flag, same render, so the suffix
    // and the live figure can never disagree about whether the job is running.
    assert.match(detailSrc, /\{fmtDuration\(spent\)\}\{running \? " so far" : ""\}/,
      "Time Spent's ' so far' suffix is not gated on the same running flag as the clock");
  });
});

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
// started_at` + " so far", climbing forever for a job that was already done.
//
// Port note 2026-08-08 (no-vanilla campaign, component 6): static/mg-notify.js is DELETED.
// The popover became the Detail component in gallery/src/notify/ActivityTray.jsx; the
// syncTick discipline survived as a `running`-keyed effect.
//
// RE-PORT 2026-08-09 (Claude Design handoff, drift item 39): the floating #jt-detail popover
// is retired -- its content expands INLINE under the row (gallery/src/notify/ActivityRow.jsx)
// instead of mounting a separate Detail component only while a popover is open. That changes
// the gating: a row that is running but COLLAPSED has no visible "so far" figure to keep live,
// so the clock effect is now keyed on BOTH `running` AND `expanded` (was `[running]` alone,
// because the old Detail simply didn't exist unless its popover was already open -- the new
// ActivityRow always exists, so `expanded` is the explicit stand-in for "a popover is open").
// The M25 guarantee itself -- a finished job's clock stops and never overwrites the real final
// duration -- is unchanged and re-verified below against the new shape.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks these out as CRLF on Windows) -- the extraction regexes
// below anchor on exact `\n` boundaries.
const src = readFileSync(
  path.join(__dirname, "../../gallery/src/notify/ActivityRow.jsx"), "utf8",
).replace(/\r\n/g, "\n");

function extract(hay, re, label) {
  const m = hay.match(re);
  assert.ok(m, `expected to find ${label} in gallery/src/notify/ActivityRow.jsx -- if it was ` +
               `renamed or restructured, update this extraction pattern, don't delete the test`);
  return m[0];
}

// The head of ActivityRow: the `running`/`startedAt` derivation through the clock effect,
// pulled out together (the effect closes over `running`/`expanded`, so the derivation has to
// come out with it). The regex's tail anchors on `}, [running, expanded]);` -- the deps array
// ITSELF -- so if the effect ever stops being keyed on both, extraction fails loudly here
// rather than a test passing vacuously.
const tickHead = extract(src,
  /const running = st === "running";\s*\n\s*const startedAt = j\.started_at \|\| j\.ts \|\| 0;[\s\S]*?\}, \[running, expanded\]\);/,
  "ActivityRow's running/startedAt derivation + gated clock effect");
assert.ok(tickHead.includes("setInterval"),
  "the extracted effect no longer contains the clock interval -- the extraction grabbed the wrong block");

// Everything the head closes over is supplied as a stand-in: `j` (the prop), `expanded` (the
// prop), `tick` (the useState bump), fake timers, and a `useEffect` the harness's commit loop
// provides. `st` is derived from `j` the same way the real component does.
const evalTickHead = new Function(
  "j", "expanded", "useEffect", "tick", "setInterval", "clearInterval",
  'const st = j.status || "running";\n' + tickHead + "\n  return { running: running, startedAt: startedAt };");

// The Time Spent figure itself, extracted as a REAL callable: frozen at job.ts once the job
// is not running, live off Date.now() only while it is. This is the line that makes a
// finished job's final duration final.
const spentLine = extract(src,
  /const spent = \(running \? \(Date\.now\(\) \/ 1000\) : \(j\.ts \|\| startedAt\)\) - startedAt;/,
  "the spent expression");
const spentOf = new Function("running", "j", "startedAt", spentLine + "\n  return spent;");

// A minimal, faithful stand-in for React's effect contract, one slot's worth: after each
// "render", if the deps array differs element-wise (Object.is) from last commit -- or this is
// the first render -- run the previous cleanup, then the new effect. A `tick` from the fake
// interval re-renders with the same (job, expanded), exactly what the real setState does.
function harness() {
  const log = { intervals: [], cleared: [], renders: 0, ticks: 0 };
  let nextId = 1;
  let slot = null;      // { deps, cleanup }
  let last = null;      // { job, expanded }
  const fakeSetInterval = (fn, ms) => {
    const id = nextId++;
    log.intervals.push({ id, fn, ms });
    return id;
  };
  const fakeClearInterval = (id) => { log.cleared.push(id); };
  const live = () => log.intervals.filter((i) => log.cleared.indexOf(i.id) === -1);
  function render(job, expanded) {
    last = { job, expanded };
    log.renders++;
    let scheduled = null;
    const useEffect = (cb, deps) => { scheduled = { cb, deps }; };
    const out = evalTickHead(job, expanded, useEffect, tick, fakeSetInterval, fakeClearInterval);
    assert.ok(scheduled, "ActivityRow's head no longer registers its clock effect");
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
  function tick() { log.ticks++; if (last) render(last.job, last.expanded); }
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

describe("ActivityRow's live Time Spent clock follows the JOB's status AND whether the row is expanded", () => {
  test("an expanded, running row gets exactly one clock, and repeated repaints don't stack more", () => {
    const h = harness();
    h.render(RUNNING, true);
    h.render(RUNNING, true);
    h.render(RUNNING, true);
    assert.equal(h.log.intervals.length, 1, "each poll's repaint started another interval");
    assert.equal(h.log.intervals[0].ms, 1000);
    assert.ok(h.ticking());
  });

  test("running but COLLAPSED: no clock at all -- there is nothing visible to keep live", () => {
    // New gate, 2026-08-09: unlike the old popover (which simply didn't exist unless open),
    // ActivityRow always exists, so a running-but-collapsed row must not tick in the
    // background -- there is no "so far" figure on screen for it to keep honest.
    const h = harness();
    h.render(RUNNING, false);
    assert.equal(h.log.intervals.length, 0, "a collapsed row started a clock nobody can see");
    assert.equal(h.ticking(), false);
  });

  test("expanding a running row starts the clock; collapsing it again stops it", () => {
    const h = harness();
    h.render(RUNNING, false);
    assert.equal(h.ticking(), false);
    h.render(RUNNING, true);
    assert.equal(h.ticking(), true, "expanding the row did not start the live clock");
    h.render(RUNNING, false);
    assert.equal(h.ticking(), false, "collapsing the row left its clock running unseen");
  });

  test("while the job really is running and expanded, the tick repaints and the figure is live", () => {
    // Port note: the vanilla tick WROTE the 'so far' string into the DOM itself; the React
    // tick bumps state so the component re-renders and the render writes it. Both halves are
    // exercised: the interval's callback really re-renders, and the spent expression really
    // tracks Date.now() while running (the " so far" suffix wording is a JSX pin below).
    const h = harness();
    h.render(RUNNING, true);
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
  // wrote `Date.now()/1000 - started_at` + " so far" unconditionally. In this shape the same
  // rot would be an effect not keyed on `running` (interval survives the status flip) or a
  // spent expression reading Date.now() unconditionally -- both asserted against here.
  test("a job that finishes under an expanded row: the tick never overwrites the final duration", () => {
    const h = harness();
    h.render(RUNNING, true);                               // row expanded while running
    const done = { job_id: "j1", status: "done", started_at: 1000, ts: 1130 };
    const out = h.render(done, true);                      // the poll repaints with the finished job
    assert.equal(h.ticking(), false, "the clock kept running past the job's completion");
    assert.equal(h.log.cleared.length, 1,
      "the status flip did not clear the interval -- there is nothing left to fire, so the " +
      "final figure can never be clobbered the M25 way");
    assert.equal(spentOf(false, done, out.startedAt), 130,
      "the finished job's Time Spent is not frozen at ts - started_at (the true final figure)");
  });

  test("a repaint of an already-finished row stops the clock outright", () => {
    const h = harness();
    h.render(RUNNING, true);
    assert.ok(h.ticking());
    h.render({ job_id: "j1", status: "done", started_at: 1000, ts: 1130 }, true);
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
      h.render(RUNNING, true);
      h.render({ job_id: "j1", status: st, started_at: 1000, ts: 1130 }, true);
      assert.equal(h.ticking(), false, `status '${st}' left the Time Spent clock running`);
    }
  });

  test("a stale job the next sweep heartbeats back to 'running' gets its clock back", () => {
    // resolve_orphan_jobs deliberately keeps 'stale' OUT of the server's _JOBS_TERMINAL, so a
    // later sweep can write status:'running' again for the same job. Because `running` is
    // re-derived on every render and the effect is keyed on it, that just remounts the clock.
    const h = harness();
    h.render(RUNNING, true);
    h.render({ job_id: "j1", status: "stale", started_at: 1000, ts: 1130 }, true);
    assert.equal(h.ticking(), false);
    h.render(RUNNING, true);
    assert.equal(h.ticking(), true, "the clock never came back for a job that resumed running");
    assert.equal(h.log.intervals.length, 2);
  });

  test("expanding an already-finished row starts no clock at all", () => {
    const h = harness();
    h.render({ job_id: "j1", status: "done", started_at: 1000, ts: 1130 }, true);
    assert.equal(h.log.intervals.length, 0);
    assert.equal(h.ticking(), false);
  });

  test("unmounting an expanded, running row (job dismissed/aged out) cleans up its clock", () => {
    // Port note 2026-08-08/09: the close-on-vanish decision itself now lives in useActivity.js
    // (an expanded row whose job disappears from the store clears expandedId); the interval
    // cleanup exercised here is the same React unmount guarantee either way.
    const h = harness();
    h.render(RUNNING, true);
    h.unmount();
    assert.equal(h.ticking(), false, "unmounting the row leaked its interval");
    assert.equal(h.log.cleared.length, 1);
  });
});

describe("the tick is wired to the repaint, not to a separate popover lifecycle", () => {
  test("exactly one owner of the clock interval per row", () => {
    // The vanilla M25 root cause was TWO owners (openDetail's interval vs syncTick's)
    // drifting apart. ActivityRow.jsx must have exactly one setInterval -- the one inside the
    // [running, expanded]-keyed effect extracted above (the copy button's setTimeout is a
    // different timer entirely and doesn't count here).
    const owners = src.match(/setInterval\(/g) || [];
    assert.equal(owners.length, 1,
      "more than one setInterval in ActivityRow.jsx -- two clock owners is exactly how M25 happened");
    assert.match(src, /\}, \[running, expanded\]\);/,
      "the clock effect is no longer keyed on [running, expanded] -- a status flip or a " +
      "collapse would not stop it");
  });

  test("terminal-ness is derived, not enumerated (H18's TERMINAL map must not be copied here)", () => {
    assert.match(src, /const running = st === "running";/,
      "ActivityRow must test 'is it still running', not a hardcoded set of finished statuses");
  });

  test("the ' so far' suffix rides the same running flag as the clock", () => {
    // In React the tick is a render expression, so the pin is on the JSX -- same flag, same
    // render, so the suffix and the live figure can never disagree about whether the job is
    // running.
    assert.match(src, /\{fmtDuration\(spent\)\}\{running \? " so far" : ""\}/,
      "Time Spent's ' so far' suffix is not gated on the same running flag as the clock");
  });
});

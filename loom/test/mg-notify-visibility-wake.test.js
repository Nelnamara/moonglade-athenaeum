import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner field report 2026-08-25: a finished video (task 2048878297915860241, viewable on
// pixai.art) kept spinning in the gallery Video drawer, then "landed" after an unusual delay --
// "usually simultaneous." Root cause (not a stuck job -- it DID resolve): the completion poll in
// gallery/src/notify/jobs.js is a bare self-perpetuating setTimeout chain, and a BACKGROUNDED
// tab's setTimeout is throttled by the browser to ~once/min (frozen harder after a few minutes).
// Switching to the PixAI tab to watch the clip finish is exactly what backgrounds the Moonglade
// tab, so the fast 3s poll went to sleep and the completion only landed when the throttled timer
// next fired.
//
// Fix under test: a `visibilitychange` handler (wakePending) pulls each in-flight task's NEXT
// poll forward the instant the tab is refocused. Because jobs.js is the SPEND-CRITICAL Jobs
// engine, the danger is not the feature but its failure modes -- a second poll loop, a resubmit,
// or a double completion callback. These assertions pin the properties that keep it safe. The
// suite has no DOM/timer harness for this module (see mg-generate-drawer-concurrent.test.js),
// so -- as everywhere jobs.js is tested -- these are source-structure checks; true interaction
// verification is a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/notify/jobs.js"), "utf8")
  .replace(/\r\n/g, "\n");

// wakePending()'s body: from its signature to the FIRST column-0 closing brace (its own -- the
// inner for-loop closes at a 2-space-indented "\n  }", which "\n}" cannot match).
function wakeBody() {
  const i = src.indexOf("function wakePending() {");
  assert.ok(i >= 0, "expected wakePending() in jobs.js");
  const j = src.indexOf("\n}", i);
  assert.ok(j > i, "could not find the end of wakePending()");
  return src.slice(i, j + 2);
}

describe("refocus wake pulls a throttled poll forward without forking the spend loop", () => {
  test("a visibilitychange listener is registered on document", () => {
    assert.match(src, /addEventListener\(\s*["']visibilitychange["']\s*,\s*wakePending\s*\)/,
      "jobs.js must wire wakePending to visibilitychange");
  });

  test("wake acts only on the VISIBLE transition -- the hide half is a no-op", () => {
    assert.match(wakeBody(),
      /document\.visibilityState\s*&&\s*document\.visibilityState\s*!==\s*["']visible["']\)\s*return/,
      "wakePending must return early unless the tab is visible");
  });

  test("wake CLEARS the pending timer BEFORE it re-polls -- never a second loop", () => {
    const w = wakeBody();
    const clr = w.indexOf("clearTimeout(");
    const rep = w.indexOf("poll(");
    assert.ok(clr >= 0, "wake must clearTimeout the throttled handle");
    assert.ok(rep >= 0, "wake must re-enter poll()");
    assert.ok(clr < rep, "clearTimeout must come BEFORE the re-poll, or two loops can run");
  });

  test("wake skips a task whose read is already open (the inflight guard)", () => {
    assert.match(wakeBody(), /p\.inflight/,
      "wake must skip an already-in-flight task so it can't double the fetch");
  });

  test("wake re-enters poll() only -- never register()/track()/apiPost/fetch, so no resubmit", () => {
    const w = wakeBody();
    assert.match(w, /\bpoll\(/, "wake resumes via poll()");
    assert.doesNotMatch(w, /\b(register|track|apiPost)\s*\(/,
      "wake must not POST job metadata or start a fresh tracked loop");
    assert.doesNotMatch(w, /\bfetch\s*\(/,
      "wake owns no fetch of its own -- it defers to poll()'s single read");
  });

  test("poll() has the re-entry guard that closes the timer-vs-visibility race", () => {
    assert.match(src, /if \(existing && existing\.inflight\) return;/,
      "poll() must bail if a read for the same id is already open");
  });

  test("one-entry-one-timer: the single schedule stores its handle", () => {
    assert.match(src, /pending\[id\]\.timer = setTimeout\(/,
      "the scheduled poll's handle must be recorded so wake can clear exactly it");
    // and there is exactly ONE setTimeout in the module (the scheduler) -- no stray second timer
    assert.equal((src.match(/setTimeout\(/g) || []).length, 1,
      "jobs.js must schedule through a single setTimeout site");
  });

  test("terminal states drop the pending entry -- done, failed, AND the 6h ceiling", () => {
    // done + failed both clearPending, inside the fetch-resolve block
    const i = src.indexOf(".then((d) => {");
    const j = src.indexOf("again(d, 0); }", i);
    assert.ok(i >= 0 && j > i, "expected the fetch-resolve block");
    const resolve = src.slice(i, j);
    assert.ok((resolve.match(/clearPending\(id\)/g) || []).length >= 2,
      "both the done and failed branches must clearPending");
    // the stalled (6h) branch clears too
    const s = src.indexOf('cb("stalled"');
    const sEnd = src.indexOf("return;", s);
    assert.ok(s >= 0 && sEnd > s && src.slice(s, sEnd).includes("clearPending(id)"),
      "the 6h ceiling branch must clearPending");
  });

  test("a throwing terminal cb cannot resurrect the poll -- cleanup is atomic", () => {
    // done/failed callbacks are wrapped so clearPending runs even if cb throws, and clearPending
    // precedes trayRefresh so a throwing refresh can't strand a live pending entry for .catch to
    // reschedule. Closes the one double-mg-result vector the adversarial review surfaced.
    assert.match(src, /try \{ if \(cb\) cb\("done", d\); \} catch[^]*?clearPending\(id\); trayRefresh\(\)/,
      "the done branch must swallow a throwing cb and still clearPending, before trayRefresh");
    assert.match(src, /try \{ if \(cb\) cb\("failed", d\); \} catch[^]*?clearPending\(id\); trayRefresh\(\)/,
      "the failed branch must do the same");
  });

  test("the spend-dedup contract (`seen`) is untouched -- one submit, one loop per id", () => {
    assert.match(src, /export function register\(id, label, count\) \{\s*\n\s*if \(!id \|\| seen\[id\]\) return;/,
      "register() must still short-circuit on a seen id (no double POST)");
    assert.match(src, /export function track\(id, label, cb, count\) \{\s*\n\s*if \(!id \|\| seen\[id\]\) return;/,
      "track() must still short-circuit on a seen id (no second loop)");
  });
});

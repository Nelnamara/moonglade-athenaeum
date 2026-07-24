import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner field-report 2026-07-23: two generations sat spinning in the Activity tray with no
// way to get their task id (the one thing the existing "Import task" recovery flow needs) --
// he was completely stuck without direct developer access to the server. static/mg-notify.js's
// row(j) never surfaced the task id anywhere; this test file covers the fix, a click-to-open
// job detail popover showing Task ID (+ copy), Time Sent, and Time Spent.
//
// static/mg-notify.js is a plain global-IIFE <script> (no ES module exports, no build step),
// same situation as master-storyboard.jsx and static/mg-generate-drawer.js -- so, matching
// this repo's established convention (see loom-activity-tracker-live-update.test.js and
// mg-generate-drawer-parity.test.js): pure/self-contained helper functions are extracted as
// REAL callables and unit-tested for real; everything else (DOM wiring, event listeners) is
// covered by source-presence assertions since there is no DOM/jsdom harness here.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

function extract(re, label) {
  const m = src.match(re);
  assert.ok(m, `expected to find ${label} in static/mg-notify.js`);
  return m[0];
}

// ---------------------------------------------------------------------------
// fmtClock(ts) -- real clock time ("Time Sent"). Hand-formatted (no toLocaleString) so it
// can't depend on the runner's ICU/locale data. Tested TZ-agnostically: build each ts from
// EXPLICIT LOCAL calendar components via `new Date(y, mo, d, h, mi).getTime()/1000`, so
// whatever timezone the test runner is actually in, fmtClock's own `new Date(ts*1000)`
// reconstructs the exact same local components -- the round-trip is symmetric regardless of
// the machine's offset, so this exercises the REAL formatting logic without hardcoding a
// wall-clock string that would only be correct in one timezone.
//
// fmtClock closes over MONTHS/pad2 (both declared just above it in the same IIFE scope), so
// extracting fmtClock alone would leave those unresolved when called via `new Function`
// (whose body runs in the GLOBAL scope, not JobsCard's closure) -- pull the whole
// MONTHS..fmtDuration block out together and return both functions from one wrapper, same
// idea as mg-generate-drawer-parity.test.js's single self-contained extraction, just two
// functions' worth instead of one.
// ---------------------------------------------------------------------------
const clockBlock = extract(/var MONTHS=\[[\s\S]*?function fmtDuration\(s\)\{[\s\S]*?\n {4}\}/,
  "the MONTHS/pad2/fmtClock/fmtDuration block");
const { fmtClock, fmtDuration } = new Function(
  clockBlock + "\nreturn { fmtClock: fmtClock, fmtDuration: fmtDuration };"
)();

function localTs(y, mo, d, h, mi) {
  return new Date(y, mo, d, h, mi, 0, 0).getTime() / 1000;
}

describe("fmtClock -- Time Sent, a real readable clock time (not row()'s relative ago())", () => {
  test("falsy ts renders an em dash, not '12:00 AM' off epoch 0 or NaN off undefined", () => {
    assert.equal(fmtClock(0), "—");
    assert.equal(fmtClock(null), "—");
    assert.equal(fmtClock(undefined), "—");
  });

  test("afternoon time, minute needing zero-padding", () => {
    assert.equal(fmtClock(localTs(2026, 6, 23, 14, 5)), "Jul 23, 2:05 PM");
  });

  test("midnight is 12 AM, not 0 AM", () => {
    assert.equal(fmtClock(localTs(2026, 0, 1, 0, 0)), "Jan 1, 12:00 AM");
  });

  test("noon is 12 PM, not 0 PM", () => {
    assert.equal(fmtClock(localTs(2026, 11, 31, 12, 0)), "Dec 31, 12:00 PM");
  });

  test("single-digit minute pads to two digits", () => {
    assert.equal(fmtClock(localTs(2026, 5, 5, 9, 7)), "Jun 5, 9:07 AM");
  });

  test("one minute before midnight rolls to 11:59 PM, not '23:59'", () => {
    assert.equal(fmtClock(localTs(2026, 5, 5, 23, 59)), "Jun 5, 11:59 PM");
  });
});

// ---------------------------------------------------------------------------
// fmtDuration(s) -- "Time Spent", an elapsed DURATION (not row()'s "3m ago" bucketing, which
// drops everything below its chosen unit). Pure arithmetic, no TZ dependency at all.
// (extracted together with fmtClock above -- see that block's comment)
// ---------------------------------------------------------------------------

describe("fmtDuration -- Time Spent, an honest two-unit elapsed duration", () => {
  test("under a minute: bare seconds", () => {
    assert.equal(fmtDuration(0), "0s");
    assert.equal(fmtDuration(45), "45s");
    assert.equal(fmtDuration(59), "59s");
  });

  test("minutes + seconds, two units of precision (not bucketed away like ago())", () => {
    assert.equal(fmtDuration(60), "1m 0s");
    assert.equal(fmtDuration(125), "2m 5s");
    assert.equal(fmtDuration(3599), "59m 59s");
  });

  test("hours + minutes past the hour boundary", () => {
    assert.equal(fmtDuration(3600), "1h 0m");
    assert.equal(fmtDuration(5400), "1h 30m");
    assert.equal(fmtDuration(86399), "23h 59m");
  });

  test("days + hours past the day boundary", () => {
    assert.equal(fmtDuration(86400), "1d 0h");
    assert.equal(fmtDuration(90061), "1d 1h");   // 1d 1h 1m 1s -> two units only
  });

  test("negative/falsy input clamps to 0s instead of a negative or NaN string", () => {
    assert.equal(fmtDuration(-5), "0s");
    assert.equal(fmtDuration(null), "0s");
    assert.equal(fmtDuration(undefined), "0s");
  });
});

// ---------------------------------------------------------------------------
// copyText(s) -- the one-click copy button. Per spec: a graceful fallback / silent no-op if
// the clipboard API isn't available, never a thrown error -- unlike this app's OTHER copy
// buttons (pixai_gallery.py's copyPrompt/copyCmd), which call navigator.clipboard.writeText
// direct and unguarded. Real behavioral tests against a mocked global `navigator`, since the
// bug this guards against (a bare, unguarded `navigator.clipboard.writeText(s)`) throws
// synchronously the instant navigator.clipboard is missing -- exactly reproducing that
// unguarded shape here is what makes these tests fail first.
// ---------------------------------------------------------------------------
// Non-greedy-to-first-"\n\s*}" would stop at the inner if-block's own closing brace (this
// function has one) rather than the function's -- anchor on the exact 4-space indent its own
// closing brace is written at, same technique as loom-activity-tracker-live-update.test.js's
// pollShotBody() extractor.
const copyText = new Function("return (" + extract(/function copyText\(s\)\s*\{[\s\S]*?\n {4}\}/, "copyText") + ")")();

// Node 21+ defines a lazy, getter-only `navigator` on globalThis (its own experimental
// navigator.userAgent), so a plain `globalThis.navigator = {...}` throws
// "Cannot set property navigator ... which has only a getter" under strict mode (every ESM
// module is strict). Delete it first -- it's configurable -- then a plain assignment installs
// an ordinary, restorable data property.
function mockNavigator(v) { delete globalThis.navigator; globalThis.navigator = v; }

describe("copyText -- one-click task-id copy, never throws", () => {
  test("calls navigator.clipboard.writeText with the given string when available", () => {
    const calls = [];
    mockNavigator({ clipboard: { writeText(s) { calls.push(s); return Promise.resolve(); } } });
    try {
      assert.doesNotThrow(() => copyText("2037215124834251576"));
      assert.deepEqual(calls, ["2037215124834251576"]);
    } finally {
      delete globalThis.navigator;
    }
  });

  test("navigator.clipboard entirely missing: silent no-op, not a TypeError", () => {
    mockNavigator({});
    try {
      assert.doesNotThrow(() => copyText("some-id"));
    } finally {
      delete globalThis.navigator;
    }
  });

  test("navigator itself missing (no browser clipboard API at all): silent no-op, not a ReferenceError", () => {
    delete globalThis.navigator;
    assert.doesNotThrow(() => copyText("some-id"));
  });

  test("a rejected write promise does not become an unhandled rejection", async () => {
    mockNavigator({ clipboard: { writeText() { return Promise.reject(new Error("denied")); } } });
    let leaked = null;
    const onUnhandled = (err) => { leaked = err; };
    process.once("unhandledRejection", onUnhandled);
    try {
      copyText("some-id");
      await new Promise((r) => setTimeout(r, 20));   // let the microtask queue settle
      assert.equal(leaked, null, "a rejected clipboard write leaked as an unhandled rejection");
    } finally {
      process.removeListener("unhandledRejection", onUnhandled);
      delete globalThis.navigator;
    }
  });
});

// ---------------------------------------------------------------------------
// Wiring / composition -- source-presence, matching loom-activity-tracker-live-update.test.js's
// established style for this non-module file.
// ---------------------------------------------------------------------------
describe("job detail popover is wired into row(), click/keyboard handling, and the tray lifecycle", () => {
  test("row() stamps data-job on the row itself so a click can look the job back up", () => {
    assert.match(src, /<div class="jt-item'\+cls\+'" data-job="'\+esc\(j\.job_id\)\+'" tabindex="0" role="button"/,
      "row() no longer carries data-job/tabindex/role on .jt-item -- the detail popover has no row to bind to");
  });

  test("detailHtml renders all three required fields with the right source data", () => {
    assert.match(src, />Task ID</, "detail popover is missing the Task ID label");
    assert.match(src, />Time Sent</, "detail popover is missing the Time Sent label");
    assert.match(src, />Time Spent</, "detail popover is missing the Time Spent label");
    assert.match(src, /var startedAt=j\.started_at\|\|j\.ts\|\|0;/,
      "detail popover does not read started_at (falling back to ts for pre-fix log lines)");
    assert.match(src, /data-copy="'\+esc\(tid\)\+'"/, "the copy button does not carry the raw task id");
  });

  test("clicking a row toggles the popover, but a thumbnail-link click is left alone", () => {
    // \b anchors on a standalone `t` -- without it, "t.addEventListener" also matches as a
    // SUBSTRING of "documen[t].addEventListener", and since that false match sits later in
    // the file, an unanchored regex happens to still find the right (earlier) block today by
    // luck of ordering alone, not by actually discriminating the two.
    const clickBlock = extract(/\bt\.addEventListener\('click', function\(e\)\{[\s\S]*?\n\s*\}\);/, "the tray's click listener");
    assert.match(clickBlock, /e\.target\.closest\('\.jt-thumb'\)\) return;/,
      "a click on the result thumbnail must not also toggle the detail popover (it should just navigate)");
    assert.match(clickBlock, /toggleDetail\(row\.getAttribute\('data-job'\), row\);/,
      "row clicks no longer open/toggle the detail popover");
  });

  test("Enter/Space on a keyboard-focused row also opens the popover", () => {
    const keyBlock = extract(/\bt\.addEventListener\('keydown', function\(e\)\{[\s\S]*?\n\s*\}\);/, "the tray's keydown listener");
    assert.match(keyBlock, /e\.key!=='Enter' && e\.key!==' '/, "only Enter/Space should trigger the popover from the keyboard");
    assert.match(keyBlock, /toggleDetail\(row\.getAttribute\('data-job'\), row\);/);
  });

  test("Escape closes the popover (existing app-wide precedent: Ach's own modal does the same)", () => {
    assert.match(src, /document\.addEventListener\('keydown', function\(e\)\{ if\(e\.key==='Escape'\) closeDetail\(\); \}\);/,
      "no Escape-key handler closes the job detail popover");
  });

  test("clicking outside both the tray and the popover closes it", () => {
    const outsideBlock = extract(/document\.addEventListener\('click', function\(e\)\{\s*if\(!detailJobId\) return;[\s\S]*?\n\s*\}\);/,
      "the document-level outside-click handler");
    assert.match(outsideBlock, /var insideDetail=e\.target\.closest && e\.target\.closest\('#jt-detail'\);/);
    assert.match(outsideBlock, /var insideTray=e\.target\.closest && e\.target\.closest\('#jobs-tray'\);/);
    assert.match(outsideBlock, /if\(!insideDetail && !insideTray\) closeDetail\(\);/);
  });

  test("collapsing the tray (the header's '–' button) also closes any open popover", () => {
    assert.match(src, /function close\(\)\{ setOpen\(false\); closeDetail\(\); \}/,
      "closing the tray leaves an orphaned floating popover on screen");
  });

  test("a poll refresh keeps an open popover's numbers live, and closes it if its job vanished", () => {
    const renderTop = extract(/function render\(jobs\)\{[\s\S]*?running\+\+; \}\);/, "the top of render(jobs)");
    assert.match(renderTop, /if\(jobsById\[detailJobId\]\) renderDetail\(jobsById\[detailJobId\]\);/,
      "an open popover is not refreshed on every poll -- Time Spent would go stale while open");
    assert.match(renderTop, /else closeDetail\(\);/,
      "a popover left open for a job that just got dismissed/aged out is not closed");
  });
});

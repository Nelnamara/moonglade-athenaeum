import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { fmtClock, fmtDuration, groupThousands } from "../../gallery/src/notify/format.js";

// Owner field-report 2026-07-23: two generations sat spinning in the Activity tray with no
// way to get their task id (the one thing the existing "Import task" recovery flow needs) --
// he was completely stuck without direct developer access to the server. The old row() never
// surfaced the task id anywhere; this test file covers the fix, a click-to-open job detail
// popover showing Task ID (+ copy), Time Sent, and Time Spent.
//
// Port note 2026-08-08 (no-vanilla campaign, component 6): static/mg-notify.js is DELETED and
// the system reimplemented in React. What that means for this suite:
//   - the pure formatters (fmtClock/fmtDuration/groupThousands) are now REAL exports in
//     gallery/src/notify/format.js, imported and run directly above -- no more regex-extracting
//     an IIFE body out of a vanilla file. Their tests below are byte-for-byte the originals.
//   - the popover/tray DOM is JSX in gallery/src/notify/ActivityTray.jsx (same ids: #jobs-fab /
//     #jobs-tray / #jt-detail). There is still no DOM/jsdom harness here, so the wiring coverage
//     keeps this suite's established split -- self-contained logic extracted as REAL callables
//     (the Detail component's copy handler and the Cost row's render gate are plain JS inside
//     the JSX), everything else covered by source-presence assertions, now against the JSX.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks these out as CRLF on Windows) -- the extraction regexes
// below anchor on exact `\n` + indent boundaries.
const traySrc = readFileSync(path.join(__dirname, "../../gallery/src/notify/ActivityTray.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

function extract(re, label) {
  const m = traySrc.match(re);
  assert.ok(m, `expected to find ${label} in gallery/src/notify/ActivityTray.jsx`);
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
// (Port note 2026-08-08: the old MONTHS..fmtDuration new-Function extraction dance is gone --
// fmtClock and fmtDuration are the real exports from format.js, imported at the top.)
// ---------------------------------------------------------------------------

function localTs(y, mo, d, h, mi) {
  return new Date(y, mo, d, h, mi, 0, 0).getTime() / 1000;
}

describe("fmtClock -- Time Sent, a real readable clock time (not the row's relative ago())", () => {
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
// fmtDuration(s) -- "Time Spent", an elapsed DURATION (not the row's "3m ago" bucketing, which
// drops everything below its chosen unit). Pure arithmetic, no TZ dependency at all.
// (imported for real from format.js -- see the port note above)
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
// The copy button. Per spec: a graceful fallback / silent no-op if the clipboard API isn't
// available, never a thrown error -- unlike this app's OTHER copy buttons (moonglade_gallery.py's
// copyPrompt/copyCmd), which call navigator.clipboard.writeText direct and unguarded. Real
// behavioral tests against a mocked global `navigator`, since the bug this guards against
// (a bare, unguarded `navigator.clipboard.writeText(s)`) throws synchronously the instant
// navigator.clipboard is missing -- exactly reproducing that unguarded shape here is what makes
// these tests fail first.
//
// Port note 2026-08-08: the vanilla's standalone copyText(s) became the Detail component's
// `copy` callback -- plain JS inside the JSX, so it can still be extracted and CALLED for real.
// It closes over `job` (it copies job.job_id instead of taking the string as an argument) and
// over React's setCopied/setTimeout for the new "copied!" flash; those are supplied as recording
// stand-ins. The guard shape under test is unchanged: guarded access, a caught throw, a
// .catch(() => {}) on the write promise.
// ---------------------------------------------------------------------------
// Anchor on the exact 2-space indent the callback's own closing `};` is written at (the same
// don't-stop-at-an-inner-brace technique the vanilla version of this file used).
const copyBlock = extract(/const copy = \(\) => \{[\s\S]*?\n {2}\};/, "the Detail component's copy callback");
function makeCopy(job) {
  const feedback = [];
  const copy = new Function(
    "job", "setCopied", "setTimeout",
    copyBlock + "\nreturn copy;",
  )(job, (v) => feedback.push(v), () => {});   // setTimeout stub: don't run the 1200ms reset
  return { copy, feedback };
}

// Node 21+ defines a lazy, getter-only `navigator` on globalThis (its own experimental
// navigator.userAgent), so a plain `globalThis.navigator = {...}` throws
// "Cannot set property navigator ... which has only a getter" under strict mode (every ESM
// module is strict). Delete it first -- it's configurable -- then a plain assignment installs
// an ordinary, restorable data property.
function mockNavigator(v) { delete globalThis.navigator; globalThis.navigator = v; }

describe("the Detail copy callback -- one-click task-id copy, never throws", () => {
  test("calls navigator.clipboard.writeText with the job's task id when available", () => {
    const calls = [];
    mockNavigator({ clipboard: { writeText(s) { calls.push(s); return Promise.resolve(); } } });
    try {
      const { copy, feedback } = makeCopy({ job_id: "2037215124834251576" });
      assert.doesNotThrow(copy);
      assert.deepEqual(calls, ["2037215124834251576"]);
      // The React port's visible feedback: the button flips to "copied!" via setCopied(true).
      assert.deepEqual(feedback, [true]);
    } finally {
      delete globalThis.navigator;
    }
  });

  test("navigator.clipboard entirely missing: silent no-op, not a TypeError", () => {
    mockNavigator({});
    try {
      assert.doesNotThrow(makeCopy({ job_id: "some-id" }).copy);
    } finally {
      delete globalThis.navigator;
    }
  });

  test("navigator itself missing (no browser clipboard API at all): silent no-op, not a ReferenceError", () => {
    delete globalThis.navigator;
    assert.doesNotThrow(makeCopy({ job_id: "some-id" }).copy);
  });

  test("a rejected write promise does not become an unhandled rejection", async () => {
    mockNavigator({ clipboard: { writeText() { return Promise.reject(new Error("denied")); } } });
    let leaked = null;
    const onUnhandled = (err) => { leaked = err; };
    process.once("unhandledRejection", onUnhandled);
    try {
      makeCopy({ job_id: "some-id" }).copy();
      await new Promise((r) => setTimeout(r, 20));   // let the microtask queue settle
      assert.equal(leaked, null, "a rejected clipboard write leaked as an unhandled rejection");
    } finally {
      process.removeListener("unhandledRejection", onUnhandled);
      delete globalThis.navigator;
    }
  });
});

// ---------------------------------------------------------------------------
// Wiring / composition -- source-presence, this suite's established style for DOM wiring
// without a jsdom harness. Port note 2026-08-08: retargeted from static/mg-notify.js's string
// building + addEventListener wiring to the equivalent JSX/hooks in ActivityTray.jsx. Each
// vanilla guarantee has a named React counterpart below.
// ---------------------------------------------------------------------------
describe("job detail popover is wired into the Row, click/keyboard handling, and the tray lifecycle", () => {
  test("a row is a focusable button that hands its own job id to the popover opener", () => {
    // Vanilla stamped data-job on .jt-item so the click handler could look the job back up in
    // the DOM; React closes over j.job_id directly, so the equivalent guarantee is the Row's
    // root keeping the button semantics and passing j.job_id through onOpenDetail.
    assert.match(traySrc, /className=\{"jt-item" \+ cls\} tabIndex=\{0\} role="button"/,
      "Row no longer carries tabIndex/role on .jt-item -- the detail popover has no row to bind to");
    assert.match(traySrc, /onClick=\{\(e\) => onOpenDetail\(j\.job_id, e\.currentTarget\)\}/,
      "a row click no longer opens/toggles the detail popover for its own job");
  });

  test("the Detail component renders all three required fields with the right source data", () => {
    const detailSrc = extract(/function Detail\(\{ job, anchor, onClose \}\) \{[\s\S]*?\n\}/,
      "the Detail component");
    assert.match(detailSrc, />Task ID</, "detail popover is missing the Task ID label");
    assert.match(detailSrc, />Time Sent</, "detail popover is missing the Time Sent label");
    assert.match(detailSrc, />Time Spent</, "detail popover is missing the Time Spent label");
    assert.match(detailSrc, /const startedAt = job\.started_at \|\| job\.ts \|\| 0;/,
      "detail popover does not read started_at (falling back to ts for pre-fix log lines)");
    assert.match(detailSrc, /navigator\.clipboard\.writeText\(job\.job_id \|\| ""\)/,
      "the copy button does not copy the raw task id");
    assert.match(detailSrc, /title="Copy task ID" onClick=\{copy\}/,
      "the copy button is not wired to the copy callback");
  });

  test("clicking a row toggles the popover, but a thumbnail-link click is left alone", () => {
    // Vanilla: the tray's delegated click listener bailed on e.target.closest('.jt-thumb').
    // React: the thumbnail anchor stops propagation itself, so the Row's onClick never fires.
    // 2026-08-09: the thumbnail no longer does a real /next?image= page navigation either (it
    // was the one bare <a> in the app with no preventDefault -- a genuine full-page reload on
    // click, found live when it landed on a blank page). It now stops propagation AND, for a
    // plain click, dispatches mg-open-details for App.jsx's own listener to open in-app --
    // same "in-app or fall through to a real new tab" contract every other Details link
    // already has, and the one thing that must never regress here is the stopPropagation.
    assert.match(traySrc, /className="jt-thumb" href=\{[^}]*\}\s*\n\s*onClick=\{\(e\) => \{\s*\n\s*e\.stopPropagation\(\);/,
      "a click on the result thumbnail must not also toggle the detail popover");
    assert.match(traySrc, /document\.dispatchEvent\(new CustomEvent\("mg-open-details", \{ bubbles: true, composed: true, detail: \{ mid \} \}\)\);/,
      "the thumbnail no longer opens Details in-app -- likely reverted to a real page navigation");
    // ...and "toggle" is real: re-clicking the open row's id closes it.
    const toggleBlock = extract(/const toggleDetail = useCallback\(\(jid, anchorEl\) => \{[\s\S]*?\}, \[\]\);/,
      "toggleDetail");
    assert.match(toggleBlock, /if \(cur === jid\) \{ anchorRef\.current = null; return null; \}/,
      "re-clicking the same row no longer closes (toggles) its own popover");
  });

  test("Enter/Space on a keyboard-focused row also opens the popover", () => {
    const keyBlock = extract(/onKeyDown=\{\(e\) => \{[\s\S]*?\}\}/, "the Row's keydown handler");
    assert.match(keyBlock, /if \(e\.key !== "Enter" && e\.key !== " "\) return;/,
      "only Enter/Space should trigger the popover from the keyboard");
    assert.match(keyBlock, /onOpenDetail\(j\.job_id, e\.currentTarget\);/);
  });

  test("Escape closes the popover (existing app-wide precedent: Ach's own modal does the same)", () => {
    assert.match(traySrc, /const onKey = \(e\) => \{ if \(e\.key === "Escape"\) onClose\(\); \};/,
      "no Escape-key handler closes the job detail popover");
  });

  test("clicking outside both the tray and the popover closes it", () => {
    const outsideBlock = extract(/const onDoc = \(e\) => \{[\s\S]*?\};/,
      "the document-level outside-click handler");
    assert.match(outsideBlock, /e\.target\.closest && e\.target\.closest\("#jt-detail"\)/);
    assert.match(outsideBlock, /e\.target\.closest && e\.target\.closest\("#jobs-tray"\)/);
    assert.match(outsideBlock, /if \(!inDetail && !inTray\) onClose\(\);/);
  });

  test("collapsing the tray (the header's '–' button) also closes any open popover", () => {
    assert.match(traySrc, /onClick=\{\(\) => \{ closeTray\(\); closeDetail\(\); \}\}/,
      "closing the tray leaves an orphaned floating popover on screen");
  });

  test("a store refresh keeps an open popover's numbers live, and closes it if its job vanished", () => {
    // Vanilla: render(jobs) called renderDetail(jobsById[detailJobId]) / else closeDetail().
    // React: the Detail's job prop is re-derived from FRESH store state on every repaint (so
    // each poll repaints the numbers), and an effect closes the popover when the job is gone.
    assert.match(traySrc, /const detailJob = detailId \? jobs\.find\(\(j\) => j\.job_id === detailId\) : null;/,
      "an open popover's job is not re-derived from fresh store state on every repaint -- Time Spent would go stale while open");
    assert.match(traySrc, /if \(detailId && !detailJob\) closeDetail\(\);/,
      "a popover left open for a job that just got dismissed/aged out is not closed");
  });
});

// ---------------------------------------------------------------------------
// Cost row. /api/task-status logs PixAI's server-authoritative `paidCredit` onto the done
// event, so the popover can show what a generation actually cost -- the one number the owner
// cannot reconstruct later without re-querying PixAI task by task.
//
// Port note 2026-08-08: the vanilla's detailHtml(j) string builder is gone; the row is JSX.
// The load-bearing 0-vs-absent distinction now lives in the row's render gate, so the gate's
// EXACT source expression is extracted and executed for real (not source-matched) -- a
// card-covered generation genuinely costs 0, and "free" must not render as "unknown" -- and
// the number formatting rides the real groupThousands import from format.js, which the row is
// source-asserted to call.
// ---------------------------------------------------------------------------
describe("Detail cost row", () => {
  const costRow = extract(/\{typeof job\.paid_credit === "number" && isFinite\(job\.paid_credit\) \? \([\s\S]*?\) : null\}/,
    "the Cost row block (typeof+isFinite gate + JSX)");
  // The REAL gate expression, run for real: paste it into a predicate and feed it jobs.
  const costShown = new Function("job",
    'return (typeof job.paid_credit === "number" && isFinite(job.paid_credit));');

  test("shows the actual cost when the job recorded one", () => {
    assert.ok(costShown({ job_id: "4242", ts: 1000, started_at: 1000, status: "done", paid_credit: 3700 }),
      "no Cost row for a job that recorded paid_credit");
    assert.match(costRow, />Cost</, "the gated row is not the Cost row");
    assert.match(costRow, /groupThousands\(job\.paid_credit\)\} credits/,
      "the Cost row does not render a thousands-separated credit figure");
    assert.equal(groupThousands(3700), "3,700", "cost not thousands-separated");
  });

  test("renders a free (card-covered) generation as 0, not as absent", () => {
    assert.ok(costShown({ job_id: "4243", ts: 1000, started_at: 1000, status: "done", paid_credit: 0 }),
      "a genuinely free generation hid its cost row");
    assert.equal(groupThousands(0), "0", "free generation did not render an explicit 0");
  });

  test("omits the row entirely when cost is unknown", () => {
    assert.equal(costShown({ job_id: "4244", ts: 1000, started_at: 1000, status: "running" }), false,
      "showed a Cost row for a job with no cost recorded -- unknown must not read as free");
    assert.equal(costShown({ job_id: "4244", ts: 1000, paid_credit: null }), false,
      "null must not read as a recorded cost");
    assert.equal(costShown({ job_id: "4244", ts: 1000, paid_credit: NaN }), false,
      "NaN would render as 'NaN credits' -- the isFinite half of the gate exists for this");
  });

  test("still renders the three original rows alongside the cost row", () => {
    const detailSrc = extract(/function Detail\(\{ job, anchor, onClose \}\) \{[\s\S]*?\n\}/,
      "the Detail component");
    assert.match(detailSrc, />Task ID</);
    assert.match(detailSrc, />Time Sent</);
    assert.match(detailSrc, />Time Spent</);
  });
});

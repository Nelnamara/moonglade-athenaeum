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
// view showing Task ID (+ copy), Time Sent, and Time Spent.
//
// Port note 2026-08-08 (no-vanilla campaign, component 6): static/mg-notify.js is DELETED and
// the system reimplemented in React. What that means for this suite:
//   - the pure formatters (fmtClock/fmtDuration/groupThousands) are now REAL exports in
//     gallery/src/notify/format.js, imported and run directly above.
//   - the popover/tray DOM is JSX in gallery/src/notify/ActivityTray.jsx.
//
// RE-PORT 2026-08-09 (Claude Design handoff, drift item 39): the floating tray and its
// side-anchored #jt-detail popover are both retired. gallery/src/notify/ActivityTray.jsx is
// DELETED; each row is now <ActivityRow> (gallery/src/notify/ActivityRow.jsx) and its detail
// expands INLINE under the row on click, in the SAME component -- no separate Detail
// component, no anchor-position math, no click-outside/Escape listener of its own (the
// PANEL as a whole gets outside-click/Escape now, in gallery/src/components/SeparatorBar.jsx
// + gallery/src/notify/useActivity.js -- a row's own expand/collapse is a plain click toggle,
// the same idiom as any other accordion row in this app). Self-contained logic is still
// extracted as REAL callables (the copy handler, the cost-row render gate); DOM wiring is
// still source-presence assertions, now against ActivityRow.jsx.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes stores LF, but
// core.autocrlf legitimately checks these out as CRLF on Windows) -- the extraction regexes
// below anchor on exact `\n` + indent boundaries.
const rowSrc = readFileSync(path.join(__dirname, "../../gallery/src/notify/ActivityRow.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

function extract(re, label) {
  const m = rowSrc.match(re);
  assert.ok(m, `expected to find ${label} in gallery/src/notify/ActivityRow.jsx`);
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
// Re-port note 2026-08-09: the copy callback now takes the click event itself (`(e) =>`, it
// calls e.stopPropagation() so clicking Copy doesn't also collapse the row it lives inside)
// and closes over `j` (the row's own job prop, renamed from the old Detail's `job`) instead of
// a bare `job` argument. The guard shape under test is unchanged: guarded access, a caught
// throw, a .catch(() => {}) on the write promise.
// ---------------------------------------------------------------------------
// Anchor on the exact 2-space indent the callback's own closing `};` is written at (the same
// don't-stop-at-an-inner-brace technique the vanilla version of this file used).
const copyBlock = extract(/const copy = \(e\) => \{[\s\S]*?\n {2}\};/, "the copy callback");
function makeCopy(j) {
  const feedback = [];
  const copy = new Function(
    "j", "setCopied", "setTimeout",
    copyBlock + "\nreturn copy;",
  )(j, (v) => feedback.push(v), () => {});   // setTimeout stub: don't run the 1200ms reset
  return { copy: (e) => copy(e || { stopPropagation() {} }), feedback };
}

// Node 21+ defines a lazy, getter-only `navigator` on globalThis (its own experimental
// navigator.userAgent), so a plain `globalThis.navigator = {...}` throws
// "Cannot set property navigator ... which has only a getter" under strict mode (every ESM
// module is strict). Delete it first -- it's configurable -- then a plain assignment installs
// an ordinary, restorable data property.
function mockNavigator(v) { delete globalThis.navigator; globalThis.navigator = v; }

describe("the copy callback -- one-click task-id copy, never throws", () => {
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

  test("clicking Copy does not also collapse the row it lives inside", () => {
    assert.match(copyBlock, /e\.stopPropagation\(\);/,
      "the copy callback no longer stops propagation -- clicking Copy would also toggle the row");
  });
});

// ---------------------------------------------------------------------------
// Wiring / composition -- source-presence, this suite's established style for DOM wiring
// without a jsdom harness.
// ---------------------------------------------------------------------------
describe("the inline detail is wired into the row, click/keyboard handling, and the store lifecycle", () => {
  test("a row is a focusable button that hands its own job id to the toggle", () => {
    assert.match(rowSrc, /className=\{"at-row" \+ cls \+ \(expanded \? " open" : ""\)\} tabIndex=\{0\} role="button"/,
      "the row no longer carries tabIndex/role -- the inline detail has no row to bind to");
    assert.match(rowSrc, /onClick=\{\(\) => onToggle\(j\.job_id\)\}/,
      "a row click no longer opens/toggles its own inline detail");
  });

  test("the row renders all three original detail fields with the right source data", () => {
    assert.match(rowSrc, />TASK</, "row detail is missing the TASK label");
    assert.match(rowSrc, />SENT</, "row detail is missing the SENT label");
    assert.match(rowSrc, />SPENT</, "row detail is missing the SPENT label");
    assert.match(rowSrc, /const startedAt = j\.started_at \|\| j\.ts \|\| 0;/,
      "row does not read started_at (falling back to ts for pre-fix log lines)");
    assert.match(rowSrc, /navigator\.clipboard\.writeText\(j\.job_id \|\| ""\)/,
      "the copy button does not copy the raw task id");
    assert.match(rowSrc, /title="Copy task ID" onClick=\{copy\}/,
      "the copy button is not wired to the copy callback");
  });

  test("clicking a row toggles its own inline detail, but a thumbnail-link click is left alone", () => {
    // Vanilla: the tray's delegated click listener bailed on e.target.closest('.jt-thumb').
    // React: the thumbnail anchor stops propagation itself, so the row's onClick never fires.
    // The thumbnail also doesn't do a real /next?image= page navigation (it was the one bare
    // <a> in the app with no preventDefault -- a genuine full-page reload on click, found live
    // when it landed on a blank page). It stops propagation AND, for a plain click, dispatches
    // mg-open-details for App.jsx's own listener to open in-app -- same "in-app or fall through
    // to a real new tab" contract every other Details link already has.
    assert.match(rowSrc, /className="at-thumb" href=\{[^}]*\}\s*\n\s*onClick=\{\(e\) => \{\s*\n\s*e\.stopPropagation\(\);/,
      "a click on the result thumbnail must not also toggle the row's inline detail");
    assert.match(rowSrc, /document\.dispatchEvent\(new CustomEvent\("mg-open-details", \{ bubbles: true, composed: true, detail: \{ mid \} \}\)\);/,
      "the thumbnail no longer opens Details in-app -- likely reverted to a real page navigation");
    // ...and "toggle" is real, in the shared hook that owns expandedId.
    const useActivitySrc = readFileSync(
      path.join(__dirname, "../../gallery/src/notify/useActivity.js"), "utf8");
    assert.match(useActivitySrc, /const toggleRow = useCallback\(\(jid\) => \{\s*\n\s*setExpandedId\(\(cur\) => \(cur === jid \? null : jid\)\);/,
      "re-clicking the same row no longer closes (toggles) its own inline detail");
  });

  test("Enter/Space on a keyboard-focused row also toggles the inline detail", () => {
    const keyBlock = extract(/onKeyDown=\{\(e\) => \{[\s\S]*?\}\}/, "the row's keydown handler");
    assert.match(keyBlock, /if \(e\.key !== "Enter" && e\.key !== " "\) return;/,
      "only Enter/Space should toggle the inline detail from the keyboard");
    assert.match(keyBlock, /onToggle\(j\.job_id\);/);
  });

  test("a row whose job vanishes (dismissed/aged out) has its expanded state closed", () => {
    // Port note 2026-08-09: this guard moved OUT of the row (which no longer knows about the
    // full job list) and INTO useActivity.js, the shared hook that owns expandedId against the
    // live jobs array from the store.
    const useActivitySrc = readFileSync(
      path.join(__dirname, "../../gallery/src/notify/useActivity.js"), "utf8");
    assert.match(useActivitySrc,
      /if \(expandedId && !jobs\.find\(\(j\) => j\.job_id === expandedId\)\) setExpandedId\(null\);/,
      "an expanded row left open for a job that just got dismissed/aged out is not closed");
  });
});

// ---------------------------------------------------------------------------
// Cost row. /api/task-status logs PixAI's server-authoritative `paidCredit` onto the done
// event, so the row's inline detail can show what a generation actually cost -- the one number
// the owner cannot reconstruct later without re-querying PixAI task by task.
//
// The load-bearing 0-vs-absent distinction lives in the row's render gate, so the gate's EXACT
// source expression is extracted and executed for real (not source-matched) -- a card-covered
// generation genuinely costs 0, and "free" must not render as "unknown" -- and the number
// formatting rides the real groupThousands import from format.js, which the row is
// source-asserted to call.
// ---------------------------------------------------------------------------
describe("inline detail cost row", () => {
  const costRow = extract(/\{typeof j\.paid_credit === "number" && isFinite\(j\.paid_credit\) \? \([\s\S]*?\) : null\}/,
    "the Cost row block (typeof+isFinite gate + JSX)");
  // The REAL gate expression, run for real: paste it into a predicate and feed it jobs.
  const costShown = new Function("j",
    'return (typeof j.paid_credit === "number" && isFinite(j.paid_credit));');

  test("shows the actual cost when the job recorded one", () => {
    assert.ok(costShown({ job_id: "4242", ts: 1000, started_at: 1000, status: "done", paid_credit: 3700 }),
      "no Cost row for a job that recorded paid_credit");
    assert.match(costRow, />COST</, "the gated row is not the COST row");
    assert.match(costRow, /groupThousands\(j\.paid_credit\)\} credits/,
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

  test("still renders the other original rows alongside the cost row", () => {
    assert.match(rowSrc, />TASK</);
    assert.match(rowSrc, />SENT</);
    assert.match(rowSrc, />SPENT</);
  });
});

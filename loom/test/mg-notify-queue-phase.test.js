import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner complaint 2026-07-25, verbatim: a plain generation "goes right to generated and
// spins until done. That's it." The Panel's job cards show a real done/total; the Activity
// tray showed one indefinite spinner for the entire life of a job -- including the stretch
// where PixAI has accepted the task and no worker has taken it, which can be the whole
// ~60 minutes before an undispatched task is reaped.
//
// PixAI publishes NO progress on a task (probed against a live control: none of progress/
// percent/percentage/step/steps/currentStep/eta/estimatedTime/queuePosition/position/
// waitTime exist), so there is no percentage to show and inventing one is off the table.
// Two honest signals exist and both are covered here:
//   1. PHASE -- `started` (written to the job log by /api/task-status) separates QUEUED from
//      rendering. Absent means unknown and must keep the old spinner.
//   2. The queue WAIT PixAI itself predicted (`eta_seconds`, GET /v2/task/wait-time). Shown
//      only while queued, worded as an estimate of the wait, never as a countdown.
//
// static/mg-notify.js is a plain global-IIFE <script> with no exports, so this follows the
// file's established convention (mg-notify-job-detail.test.js): extract the pure formatter
// as a REAL callable and exercise it, plus source-presence for the CSS.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

function extract(re, label) {
  const m = src.match(re);
  assert.ok(m, `expected to find ${label} in static/mg-notify.js`);
  return m[0];
}

// row(j) closes over esc / kindLabel / ago / fmtDuration, all of which have their own tests
// (or are trivial) -- supplied here as stand-ins so the assertions below are about the row's
// STATE LOGIC, not about formatting that is already covered elsewhere. fmtDuration's stand-in
// echoes the seconds so an ETA chip's number stays checkable.
const row = new Function(
  "var esc=function(s){return String(s==null?'':s);};" +
  "var kindLabel=function(t){return t||'Job';};" +
  "var ago=function(ts){return 'just now';};" +
  "var fmtDuration=function(s){return s+'s';};" +
  // row() closes over labelFor now: the card shows the PRESENT tense while a job is in
  // flight, because the stored label is the completion wording written at submit time.
  // Echoed here so this file's assertions stay about STATE -- the tense rule itself is
  // covered in mg-notify-label-tense.test.js.
  "var labelFor=function(j,t){return j.label||'Generation';};" +
  extract(/function row\(j\)\{[\s\S]*?\n {4}\}/, "row(j)") + "\nreturn row;"
)();

const QUEUED_PILL = /class="jt-phase"/;
const QUEUED_ICON = /class="jt-spin jt-queued"/;
const SPINNER = /class="jt-spin/;

describe("row() tells a queued generation apart from one that is actually rendering", () => {
  test("a job PixAI has not started yet reads as QUEUED", () => {
    const html = row({ job_id: "1", status: "running", started: false, label: "Generated" });
    assert.match(html, QUEUED_PILL,
      "a queued job renders no phase label at all -- it is indistinguishable from active " +
      "rendering, which is exactly the indefinite spinner the owner reported");
    assert.match(html, /queued/i, "the phase label does not say what phase it is in");
  });

  test("the queued icon is the SAME mascot, with its animation stopped", () => {
    // Deliberately the existing .jt-spin element plus a modifier, not a new parallel glyph:
    // the whole reason a spinner is wrong here is that motion reads as work in progress.
    // Stopping it is the honest version of the same idiom.
    const html = row({ job_id: "1", status: "running", started: false });
    assert.match(html, QUEUED_ICON,
      "the queued row does not mark its spinner as queued, so it keeps spinning as though " +
      "work were happening");
    assert.match(html, /src="\/branding\/gen_nel\.png"/,
      "the queued row should keep the same mascot the running row uses");
  });

  test("a job a worker has picked up keeps the ordinary spinner and no queued label", () => {
    const html = row({ job_id: "2", status: "running", started: true });
    assert.match(html, SPINNER);
    assert.doesNotMatch(html, QUEUED_ICON, "a genuinely rendering job was marked queued");
    assert.doesNotMatch(html, QUEUED_PILL);
  });

  test("`started` absent means UNKNOWN, and unknown keeps the spinner it always had", () => {
    // Back-compat, and the reason the check is `j.started===false` rather than `!j.started`:
    // panel / cli / delete / import jobs never carry the field, and neither does any generate
    // job logged before this shipped. Branding all of those "queued" would be a lie, and
    // would hit every Control Panel job in the tray.
    for (const j of [{ job_id: "3", status: "running" },
                     { job_id: "4", status: "running", type: "panel", label: "Sync" },
                     { job_id: "5", status: "running", started: null },
                     { job_id: "6", status: "running", started: undefined }]) {
      const html = row(j);
      assert.doesNotMatch(html, QUEUED_PILL,
        "job with no known phase was labelled queued: " + JSON.stringify(j));
      assert.doesNotMatch(html, QUEUED_ICON, JSON.stringify(j));
    }
  });

  test("a job with no status at all defaults to running, not to queued", () => {
    assert.doesNotMatch(row({ job_id: "7" }), QUEUED_PILL);
  });

  test("a terminal status wins over a stale `started:false` on the same record", () => {
    // A done/failed event and a late 'running' phase event can both exist for one job id
    // (two pollers racing). _reconstruct_jobs makes the terminal one stick server-side; the
    // row must not contradict that by drawing a queued pill on a finished job.
    for (const st of ["done", "failed", "done_with_errors", "stale"]) {
      const html = row({ job_id: "8", status: st, started: false, error: "x" });
      assert.doesNotMatch(html, QUEUED_PILL, st + " job rendered a queued label");
      assert.doesNotMatch(html, QUEUED_ICON, st + " job rendered a queued spinner");
    }
  });

  test("the existing states are untouched -- done still ticks, failed still warns", () => {
    assert.match(row({ job_id: "9", status: "done", media_ids: ["m1"] }), /jt-ok/);
    assert.match(row({ job_id: "9", status: "failed", error: "nope" }), /jt-err/);
    assert.match(row({ job_id: "9", status: "stale", error: "nope" }), /jt-warn/);
    assert.match(row({ job_id: "9", status: "running", total: 10, done: 5 }),
      /class="jt-bar"/, "the Panel-style done/total bar must still render");
  });
});

describe("the queue estimate is shown as a WAIT, and only while the wait is still on", () => {
  test("a queued job shows the wait PixAI predicted", () => {
    const html = row({ job_id: "1", status: "running", started: false, eta_seconds: 27 });
    assert.match(html, /class="jt-eta"/, "the recorded queue estimate is not shown anywhere");
    assert.match(html, /27s/, "the estimate's own number is missing: " + html);
    assert.match(html, /wait/i,
      "the estimate must be worded as a WAIT -- a bare duration beside a spinner reads as " +
      "time remaining, which is the one thing PixAI does not tell us");
  });

  test("it names PixAI as the source and says it is not a countdown", () => {
    const html = row({ job_id: "1", status: "running", started: false, eta_seconds: 27 });
    const m = html.match(/class="jt-eta" title="([^"]*)"/);
    assert.ok(m, "the estimate chip carries no explanatory title: " + html);
    assert.match(m[1], /PixAI/, "the title does not say whose estimate it is");
    assert.match(m[1], /not a countdown/i,
      "the title must rule out the countdown reading -- the number is frozen at the moment " +
      "the job was seen queued and nothing recomputes it as the wait grows");
  });

  test("once the job is rendering, the queue estimate disappears", () => {
    // It was an estimate of the QUEUE. Leaving it on screen next to a job that has started
    // would turn it into an implied render ETA, which we have no data for at all.
    const html = row({ job_id: "1", status: "running", started: true, eta_seconds: 27 });
    assert.doesNotMatch(html, /class="jt-eta"/,
      "a started job still advertises its old queue estimate, which now reads as a " +
      "render ETA we do not have");
  });

  test("no estimate recorded: the phase still shows, just without a number", () => {
    const html = row({ job_id: "1", status: "running", started: false });
    assert.match(html, QUEUED_PILL);
    assert.doesNotMatch(html, /class="jt-eta"/);
  });

  test("a zero-second estimate renders as 0s rather than vanishing", () => {
    // Same 0-vs-absent distinction the Cost row already makes: an empty queue really is
    // ~0s, and "no wait" must not be indistinguishable from "we never asked".
    assert.match(row({ job_id: "1", status: "running", started: false, eta_seconds: 0 }),
      /class="jt-eta"/, "an empty queue collapsed into 'unknown'");
  });

  test("a non-numeric estimate is ignored instead of printing NaN or undefined", () => {
    for (const bad of ["soon", null, NaN, Infinity, {}]) {
      const html = row({ job_id: "1", status: "running", started: false, eta_seconds: bad });
      assert.doesNotMatch(html, /class="jt-eta"/, "rendered a chip for " + String(bad));
    }
  });
});

// ---------------------------------------------------------------------------
// The detail popover already shows Task ID / Time Sent / Time Spent / Cost. The queue
// estimate belongs there in full: it is only meaningful READ AGAINST Time Spent (an
// estimate of 27s beside 6m spent is the whole diagnosis), and the popover has room to
// label it properly where a 366px-wide tray row does not.
// ---------------------------------------------------------------------------
describe("detailHtml surfaces the estimate labelled, next to the elapsed time", () => {
  const detailHtml = new Function(
    "var esc=function(s){return String(s==null?'':s);};" +
    "var fmtClock=function(t){return 'CLOCK';};" +
    "var fmtDuration=function(s){return s+'s';};" +
    extract(/function detailHtml\(j\)\{[\s\S]*?\n {4}\}/, "detailHtml") + "\nreturn detailHtml;"
  )();

  test("shows the recorded estimate, attributed and time-qualified", () => {
    const html = detailHtml({ job_id: "1", ts: 1000, started_at: 1000,
                              status: "running", started: false, eta_seconds: 27 });
    assert.match(html, />Est\. wait</, "no estimate row in the detail popover");
    assert.match(html, /27s/, "the estimate's number is missing: " + html);
    assert.match(html, /PixAI/, "the row does not attribute the estimate to PixAI");
    assert.match(html, /queued/i,
      "the row must say WHEN the estimate was taken -- an unqualified 'Est. wait' beside a " +
      "live Time Spent reads as time remaining");
  });

  test("omits the row entirely when nothing was recorded", () => {
    const html = detailHtml({ job_id: "2", ts: 1000, started_at: 1000, status: "running" });
    assert.doesNotMatch(html, />Est\. wait</);
  });

  test("the four existing rows are untouched", () => {
    const html = detailHtml({ job_id: "3", ts: 1000, started_at: 1000,
                              status: "done", paid_credit: 3700, eta_seconds: 27 });
    assert.match(html, />Task ID</);
    assert.match(html, />Time Sent</);
    assert.match(html, />Time Spent</);
    assert.match(html, />Cost</);
  });
});

describe("the queued state is styled, and styled the same on both hosts", () => {
  test("the queued modifier stops both animations rather than hiding the icon", () => {
    assert.match(src, /\.jt-spin\.jt-queued \.jt-nel\{[^}]*animation:none/,
      "the mascot keeps spinning on a queued job -- motion is precisely what reads as " +
      "'work is happening', which is the bug");
    assert.match(src, /\.jt-spin\.jt-queued \.gen-ring\{[^}]*animation:none/,
      "the progress ring keeps spinning on a queued job");
  });

  test("the phase pill and the estimate chip have their own quiet styling", () => {
    assert.match(src, /\.jt-sub \.jt-phase\{/, "no style for the queued phase pill");
    assert.match(src, /\.jt-sub \.jt-eta\{/, "no style for the queue-estimate chip");
    // Not the warning colour. `stale` and `done_with_errors` own --peach/.st-warn; a job
    // sitting in a normal ~25s queue is not a problem and must not be dressed as one.
    const pill = src.match(/\.jt-sub \.jt-phase\{[^}]*\}/)[0];
    assert.doesNotMatch(pill, /--peach|--red/,
      "the queued pill uses a warning colour, so every ordinary generation would look " +
      "broken for its first half-minute: " + pill);
  });

  test("nothing in the Loom shell can override these -- it only moves the tray", () => {
    // The gallery and the Loom load this same file; the Loom's own <style> (_LOOM_SHELL)
    // touches ONLY #jobs-fab/#jobs-tray bottom + z-index. If it ever starts restyling .jt-*
    // the two hosts can drift apart again, which is a defect that has already happened once
    // (the tray's font-family, 2026-07-21).
    const shell = readFileSync(path.join(__dirname, "../../moonglade_gallery.py"), "utf8")
      .match(/_LOOM_SHELL = r"""[\s\S]*?"""/)[0];
    assert.doesNotMatch(shell, /\.jt-[a-z]/,
      "the Loom shell has started styling .jt-* classes -- the shared tray would then " +
      "render differently on /loom than in the gallery");
  });
});

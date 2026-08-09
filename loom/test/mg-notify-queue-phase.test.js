import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";

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
// PORTED 2026-08-08 (no-vanilla campaign, component 6): static/mg-notify.js is DELETED. The
// row()/detailHtml() builders this file used to extract-and-call are now the <Row>/<Detail>
// React components in gallery/src/notify/ActivityTray.jsx, and the injected MG_CSS moved to
// gallery/src/styles/notify.css (ridden by both hosts' bundles). No jsdom/React harness in
// this runner (same as cost-badge.test.js / ModelPicker), so the extraction tests become
// source-text pins on the exact expressions that encode each rule -- queued is one guard
// (`st === "running" && j.started === false`) and one guarded chip, so pinning the guard IS
// pinning the behavior. The old stand-ins (esc/ago/fmtDuration/labelFor) are obsolete: those
// are real exports of gallery/src/notify/format.js now, with their own tests -- the tense rule
// the labelFor stand-in echoed is still covered in mg-notify-label-tense.test.js.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tray = readFileSync(
  path.join(__dirname, "../../gallery/src/notify/ActivityTray.jsx"), "utf8");
const css = readFileSync(
  path.join(__dirname, "../../gallery/src/styles/notify.css"), "utf8");

describe("Row tells a queued generation apart from one that is actually rendering", () => {
  test("a job PixAI has not started yet reads as QUEUED", () => {
    // The whole feature is this one guard...
    assert.match(tray, /const queued = st === "running" && j\.started === false;/,
      "the queued gate is gone (or reworded) -- without it a queued job is indistinguishable " +
      "from active rendering, which is exactly the indefinite spinner the owner reported");
    // ...feeding one guarded pill, which must literally say what phase it is in.
    assert.match(tray, /\{queued \? \(\s*<span className="jt-phase"[^>]*>queued<\/span>\s*\) : null\}/,
      "the phase pill is not rendered under the queued flag, or no longer says 'queued'");
  });

  test("the queued icon is the SAME mascot, with its animation stopped", () => {
    // Deliberately the existing .jt-spin element plus a modifier, not a new parallel glyph:
    // the whole reason a spinner is wrong here is that motion reads as work in progress.
    // Stopping it is the honest version of the same idiom (the animation:none half of this
    // lives in notify.css, pinned in the styling describe below).
    assert.match(tray,
      /<span className=\{"jt-spin" \+ \(queued \? " jt-queued" : ""\)\}>\s*<img className="jt-nel" src="\/branding\/gen_nel\.png"/,
      "the queued row must be the SAME .jt-spin spinner with a .jt-queued modifier, keeping " +
      "the same gen_nel mascot the running row uses -- not a separate queued glyph");
  });

  test("a job a worker has picked up keeps the ordinary spinner and no queued label", () => {
    // Structural inverse of the two pins above: the modifier and the pill exist ONLY behind
    // the queued flag, so started:true (queued=false) yields the plain spinner and no pill.
    assert.equal(tray.split("jt-queued").length, 2,
      "jt-queued appears somewhere outside the one (queued ? ...) ternary -- a genuinely " +
      "rendering job could be marked queued");
    assert.equal(tray.split("jt-phase").length, 2,
      "jt-phase appears somewhere outside the one {queued ? ...} guard");
  });

  test("`started` absent means UNKNOWN, and unknown keeps the spinner it always had", () => {
    // Back-compat, and the reason the check is `j.started===false` rather than `!j.started`:
    // panel / cli / delete / import jobs never carry the field, and neither does any generate
    // job logged before this shipped. Branding all of those "queued" would be a lie, and
    // would hit every Control Panel job in the tray.
    assert.match(tray, /j\.started === false/,
      "the strict === false comparison is gone -- a truthiness check would brand every " +
      "no-phase job (panel/cli/delete/import, pre-feature rows) as queued");
    // The rationale is load-bearing enough that the component documents it in place; keep it.
    assert.match(tray, /absent means UNKNOWN/,
      "the in-source warning about absent-means-unknown was dropped -- the next refactor " +
      "will 'simplify' this to !j.started again");
  });

  test("a job with no status at all defaults to running, not to queued", () => {
    // st defaults to "running", and queued still ALSO requires started===false -- so a bare
    // {job_id} row (no status, no started) renders the plain running spinner.
    assert.match(tray, /const st = j\.status \|\| "running";/);
  });

  test("a terminal status wins over a stale `started:false` on the same record", () => {
    // A done/failed event and a late 'running' phase event can both exist for one job id
    // (two pollers racing). _reconstruct_jobs makes the terminal one stick server-side; the
    // row must not contradict that by drawing a queued pill on a finished job. Encoded twice:
    // queued's first conjunct is st === "running" (pinned above), and every terminal status
    // takes its own icon branch BEFORE the spinner fallback can render at all.
    const spinIdx = tray.indexOf('"jt-spin" + (queued');
    assert.ok(spinIdx > -1, "the spinner fallback is gone");
    for (const st of ["done", "done_with_errors", "failed", "stale"]) {
      const idx = tray.indexOf(`st === "${st}" ?`);
      assert.ok(idx > -1, `no icon branch for terminal status '${st}'`);
      assert.ok(idx < spinIdx,
        `the '${st}' branch must be decided before the spinner fallback, or a ${st} job ` +
        "with a stale started:false could render a queued spinner");
    }
  });

  test("the existing states are untouched -- done still ticks, failed still warns", () => {
    assert.match(tray, /className="jt-ok jt-glyph"/);
    assert.match(tray, /className="jt-err jt-glyph"/);
    assert.match(tray, /className="jt-warn jt-glyph"/);
    assert.match(tray, /const pct = \(st === "running" && j\.total\)/,
      "the Panel-style done/total percentage must still be computed for running jobs");
    assert.match(tray, /\{pct != null \? <div className="jt-bar">/,
      "the Panel-style done/total bar must still render");
  });
});

describe("the queue estimate is shown as a WAIT, and only while the wait is still on", () => {
  test("a queued job shows the wait PixAI predicted", () => {
    assert.match(tray, /<span className="jt-eta"/,
      "the recorded queue estimate is not shown anywhere");
    assert.match(tray, /est\. \{fmtDuration\(j\.eta_seconds\)\} wait/,
      "the estimate must be worded as a WAIT -- a bare duration beside a spinner reads as " +
      "time remaining, which is the one thing PixAI does not tell us");
  });

  test("it names PixAI as the source and says it is not a countdown", () => {
    const m = tray.match(/<span className="jt-eta" title="([^"]*)"/);
    assert.ok(m, "the estimate chip carries no explanatory title");
    assert.match(m[1], /PixAI/, "the title does not say whose estimate it is");
    assert.match(m[1], /not a countdown/i,
      "the title must rule out the countdown reading -- the number is frozen at the moment " +
      "the job was seen queued and nothing recomputes it as the wait grows");
  });

  test("once the job is rendering, the queue estimate disappears", () => {
    // It was an estimate of the QUEUE. Leaving it on screen next to a job that has started
    // would turn it into an implied render ETA, which we have no data for at all. Encoded as
    // the chip's guard leading with `queued &&` -- started:true makes queued false.
    assert.match(tray,
      /\{queued && typeof j\.eta_seconds === "number" && isFinite\(j\.eta_seconds\) \? \(\s*<span className="jt-eta"/,
      "the jt-eta chip is no longer gated on queued -- a started job would still advertise " +
      "its old queue estimate, which now reads as a render ETA we do not have");
  });

  test("no estimate recorded: the phase still shows, just without a number", () => {
    // The pill's guard is `queued` ALONE; only the chip's guard mentions eta_seconds. If the
    // pill ever picks up an eta condition, a queued job with no recorded estimate would lose
    // its phase label too.
    const pill = tray.match(/\{queued( && [^?]*)? \? \(\s*<span className="jt-phase"/);
    assert.ok(pill, "the jt-phase pill guard is gone");
    assert.equal(pill[1], undefined,
      "the phase pill must not depend on eta_seconds -- phase and estimate are separate " +
      "signals and only one of them needs the number: " + pill[0]);
  });

  test("a zero-second estimate renders as 0s rather than vanishing", () => {
    // Same 0-vs-absent distinction the Cost row already makes: an empty queue really is
    // ~0s, and "no wait" must not be indistinguishable from "we never asked". typeof, not
    // truthiness -- `j.eta_seconds &&` would collapse 0 into 'unknown'.
    assert.match(tray, /typeof j\.eta_seconds === "number"/,
      "an empty queue (eta_seconds: 0) would collapse into 'unknown' under a truthiness check");
  });

  test("a non-numeric estimate is ignored instead of printing NaN or undefined", () => {
    // isFinite kills NaN/Infinity; the typeof pinned above kills "soon"/null/{}.
    assert.match(tray, /isFinite\(j\.eta_seconds\)/,
      "without isFinite a NaN/Infinity estimate would render as a chip");
  });
});

// ---------------------------------------------------------------------------
// The detail popover already shows Task ID / Time Sent / Time Spent / Cost. The queue
// estimate belongs there in full: it is only meaningful READ AGAINST Time Spent (an
// estimate of 27s beside 6m spent is the whole diagnosis), and the popover has room to
// label it properly where a 366px-wide tray row does not.
// (Port note 2026-08-08: detailHtml(j) is now the <Detail> component in ActivityTray.jsx;
// same rows, same source-text pins.)
// ---------------------------------------------------------------------------
describe("the Detail popover surfaces the estimate labelled, next to the elapsed time", () => {
  test("shows the recorded estimate, attributed and time-qualified", () => {
    assert.match(tray, />Est\. wait</, "no estimate row in the detail popover");
    assert.match(tray, /\{fmtDuration\(job\.eta_seconds\)\} \(PixAI, when queued\)/,
      "the row must attribute the estimate to PixAI AND say WHEN it was taken -- an " +
      "unqualified 'Est. wait' beside a live Time Spent reads as time remaining");
  });

  test("omits the row entirely when nothing was recorded", () => {
    assert.match(tray,
      /\{typeof job\.eta_seconds === "number" && isFinite\(job\.eta_seconds\) \? \(\s*<div className="jd-row"><span className="jd-k">Est\. wait<\/span>/,
      "the Est. wait row is not guarded on a recorded, finite number -- an unrecorded " +
      "estimate would render as 'undefined' or 'NaN'");
  });

  test("the four existing rows are untouched", () => {
    assert.match(tray, />Task ID</);
    assert.match(tray, />Time Sent</);
    assert.match(tray, />Time Spent</);
    assert.match(tray, />Cost</);
  });
});

describe("the queued state is styled, and styled the same on both hosts", () => {
  // Port note 2026-08-08: the styles moved verbatim from mg-notify.js's injected MG_CSS to
  // gallery/src/styles/notify.css, which rides BOTH hosts' bundles (gallery/dist/app.css and
  // loom/dist/master-storyboard.bundle.css) -- one file, so the two hosts cannot drift.
  test("the queued modifier stops both animations rather than hiding the icon", () => {
    assert.match(css, /\.jt-spin\.jt-queued \.jt-nel\{[^}]*animation:none/,
      "the mascot keeps spinning on a queued job -- motion is precisely what reads as " +
      "'work is happening', which is the bug");
    assert.match(css, /\.jt-spin\.jt-queued \.gen-ring\{[^}]*animation:none/,
      "the progress ring keeps spinning on a queued job");
  });

  test("the phase pill and the estimate chip have their own quiet styling", () => {
    assert.match(css, /\.jt-sub \.jt-phase\{/, "no style for the queued phase pill");
    assert.match(css, /\.jt-sub \.jt-eta\{/, "no style for the queue-estimate chip");
    // Not the warning colour. `stale` and `done_with_errors` own --peach/.st-warn; a job
    // sitting in a normal ~25s queue is not a problem and must not be dressed as one.
    const pill = css.match(/\.jt-sub \.jt-phase\{[^}]*\}/)[0];
    assert.doesNotMatch(pill, /--peach|--red/,
      "the queued pill uses a warning colour, so every ordinary generation would look " +
      "broken for its first half-minute: " + pill);
  });

  test("nothing in the Loom shell can override these -- it only moves the tray", () => {
    // The gallery and the Loom load this same stylesheet; the Loom's own <style> (_LOOM_SHELL)
    // touches ONLY #jobs-fab/#jobs-tray bottom + z-index. If it ever starts restyling .jt-*
    // the two hosts can drift apart again, which is a defect that has already happened once
    // (the tray's font-family, 2026-07-21).
    // Port note 2026-08-08: _LOOM_SHELL is now a CONCATENATION (r"""...""" + _AUTH_401_GUARD_JS
    // + r"""..."""), so the old /r"""[\s\S]*?"""/ extraction stops at the FIRST segment's
    // closing quotes -- 495 chars of <head>, no <style> block -- and the .jt- check below would
    // pass vacuously. The regex now follows the concatenation, and the #jobs-fab sanity pin
    // proves the extraction actually reached the style block before the real assertion runs.
    const shellSrc = readFileSync(path.join(__dirname, "../../moonglade_gallery.py"), "utf8");
    const m = shellSrc.match(
      /_LOOM_SHELL = r"""[\s\S]*?"""(?:\s*\+\s*[A-Za-z_]\w*\s*\+\s*r"""[\s\S]*?""")*/);
    assert.ok(m, "could not extract _LOOM_SHELL from moonglade_gallery.py");
    const shell = m[0];
    assert.match(shell, /#jobs-fab/,
      "sanity: the extracted shell no longer reaches the #jobs-fab overrides -- the " +
      "extraction is truncating at a segment boundary again and the .jt- check below " +
      "proves nothing");
    assert.doesNotMatch(shell, /\.jt-[a-z]/,
      "the Loom shell has started styling .jt-* classes -- the shared tray would then " +
      "render differently on /loom than in the gallery");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// AUDIT_2026-07-21.md, owner field test 2026-07-24: generating from the Loom's IMAGE tab
// produced NOTHING in either Activity tracker -- not the Loom's, not the gallery's. Verified
// against the owner's real jobs.jsonl: zero entries for the task id (retrieved from PixAI's
// own site), while the generation itself succeeded and all four of its images were collected
// into the catalog by the live-mirror watcher.
//
// This is NOT a tracker defect -- both trays were correctly empty, because nothing ever told
// them the generation existed. genImage() POSTed /api/generate, took d.task_id, and handed it
// straight to its own private pollImg(); the shared job log (static/mg-notify.js's Jobs +
// /api/jobs) was never informed. genEdit()/genRef() had the identical gap via their shared
// runGen() helper. Only generateShot (the per-shot VIDEO path) and the shared drawer's
// mg-submit listener ever registered anything.
//
// Fix: each of the three image submit paths calls Jobs.register() on its success path, the
// same register-ONLY entry point generateShot uses (see mg-notify.js:1021 and generateShot's
// own comment) -- registration WITHOUT a second poll loop, because these paths already own a
// working private poller. Jobs.track() here would duplicate a poll for the same task id.
//
// Terminal resolution is already safe: pollImg and runGen's poll both route through
// pollTaskWithCeiling, which polls /api/task-status -- the SAME endpoint whose done/failed
// branches write the authoritative terminal job event (pixai_gallery.py:13148/13155). So a
// registered job gets resolved by the very poll that was already running; registration cannot
// leave these jobs spinning at 'running' forever.
//
// master-storyboard.jsx has no JSX/React test harness in this suite (no jsdom) --
// source-presence assertions are the established pattern (mirrors
// loom-activity-tracker-live-update.test.js, loom-cost-badges.test.js,
// loom-v2-dead-generate-shot-prop.test.js).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");
const notify = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

// The established guard shape, copied verbatim from generateShot's own call (line ~2716):
// the Loom must not hard-depend on mg-notify.js having loaded.
const GUARDED_REGISTER = /if \(window\.Jobs && window\.Jobs\.register\) window\.Jobs\.register\(/;

function body(re, what) {
  const m = src.match(re);
  assert.ok(m, "expected to find the " + what + " implementation");
  return m[0];
}
const genImageBody = () => body(/const genImage = async \(entry\) => \{[\s\S]*?\n  \};/, "genImage");
const runGenBody = () => body(/const runGen = async \([\s\S]*?\n  \};/, "runGen");
const genEditBody = () => body(/const genEdit = \(entry\) => \{[\s\S]*?\n  \};/, "genEdit");
const genRefBody = () => body(/const genRef = \(entry\) => \{[\s\S]*?\n  \};/, "genRef");
const pollCeilingBody = () => body(/const pollTaskWithCeiling = \([\s\S]*?\n  \};/, "pollTaskWithCeiling");

// These functions are heavily commented, and the comments legitimately DISCUSS Jobs.track()
// (explaining why it is deliberately not used). A "must not call track()" assertion has to
// look at code only, or the very comment justifying the choice trips it.
const codeOnly = (s) => s.replace(/^\s*\/\/.*$/gm, "");

describe("every Loom image submit path registers its generation in the shared Job Tracker", () => {
  test("genImage registers the task (the Image-tab bug the owner hit on 2026-07-24)", () => {
    assert.match(genImageBody(), GUARDED_REGISTER,
      "genImage never calls Jobs.register() -- it POSTs /api/generate, takes d.task_id and goes " +
      "straight to its own pollImg(), so the shared job log is never told the generation exists " +
      "and BOTH Activity trays stay (correctly) empty for a generation that really ran");
  });

  test("runGen registers the task, so genEdit and genRef are covered too", () => {
    assert.match(runGenBody(), GUARDED_REGISTER,
      "runGen (the shared submit helper behind genEdit and genRef) never calls Jobs.register() -- " +
      "same gap as genImage: an Edit or a Reference generate leaves both trays empty");
  });

  test("registration happens on the success path only -- after the task_id check", () => {
    for (const [name, fn] of [["genImage", genImageBody()], ["runGen", runGenBody()]]) {
      const checkIdx = fn.indexOf("!d.task_id");
      const regIdx = fn.search(GUARDED_REGISTER);
      assert.ok(checkIdx >= 0, name + ": expected the !d.task_id submit-failure check");
      assert.ok(regIdx > checkIdx,
        name + " registers before/inside its own submit-failure check -- a rejected submit " +
        "would put a phantom job in the tray that no task will ever resolve");
    }
  });

  test("registration happens BEFORE the private poll starts", () => {
    const img = genImageBody();
    assert.ok(img.search(GUARDED_REGISTER) >= 0 && img.indexOf("pollImg(c.id, d.task_id)") >= 0,
      "genImage must contain both a guarded Jobs.register() and its pollImg() call");
    assert.ok(img.search(GUARDED_REGISTER) < img.indexOf("pollImg(c.id, d.task_id)"),
      "genImage must register before pollImg() -- the row should exist in the tray from the " +
      "moment the server accepts the submit, not after the first poll tick");
    const rg = runGenBody();
    assert.ok(rg.search(GUARDED_REGISTER) >= 0 && rg.indexOf("poll(d.task_id)") >= 0,
      "runGen must contain both a guarded Jobs.register() and its poll() call");
    assert.ok(rg.search(GUARDED_REGISTER) < rg.indexOf("poll(d.task_id)"),
      "runGen must register before its poll() -- same reason");
  });

  test("it REGISTERS rather than TRACKS -- no second poll loop for the same task id", () => {
    // mg-notify.js's register() is the register-ONLY entry point; track() also starts its own
    // poll. These paths already own pollTaskWithCeiling, so track() would poll the same task
    // twice from one page.
    assert.match(notify, /function register\(id, label\)\{/,
      "mg-notify.js must still expose the register-ONLY entry point this fix depends on");
    assert.doesNotMatch(src, /window\.Jobs\.track\(/,
      "master-storyboard.jsx must never call Jobs.track() -- every generation path in this file " +
      "already owns a private poll loop (pollShot / pollTaskWithCeiling), so track()'s own " +
      "polling would be a redundant duplicate poll of the same task id");
    for (const [name, fn] of [["genImage", genImageBody()], ["runGen", runGenBody()]]) {
      assert.doesNotMatch(codeOnly(fn), /Jobs\.track/, name + " must use Jobs.register, not Jobs.track");
      assert.match(codeOnly(fn), /Jobs\.register\(/, name + " must actually call Jobs.register()");
    }
  });
});

describe("the tray labels distinguish the three image paths and name the shot", () => {
  // .jt-lab is `white-space:nowrap;overflow:hidden;text-overflow:ellipsis` inside a 366px
  // tray (static/mg-notify.js), so a long shot title truncates the TAIL -- whatever has to
  // survive must come first. Hence: tab name, then shot code, then title. The tab names are
  // the owner's own vocabulary (the Loom's side tabs are literally Image / Edit / Reference /
  // Video), so a row maps 1:1 onto the button that was clicked.
  test("genImage's label leads with the tab name, then the shot code + title", () => {
    assert.match(genImageBody(), /"Image · " \+ entry\.code \+ " · " \+ \(c\.title \|\| "untitled"\)/,
      'genImage should label the job "Image · <shot code> · <title>" -- a bare "Generated" ' +
      "would repeat the owner's standing complaint that the tracker is not informative");
  });

  test("genEdit passes its own Edit label through to runGen", () => {
    assert.match(genEditBody(), /"Edit · " \+ entry\.code \+ " · " \+ \(c\.title \|\| "untitled"\)/,
      'genEdit should label the job "Edit · <shot code> · <title>"');
  });

  test("genRef's label carries the reference count, which is the fact that path is about", () => {
    assert.match(genRefBody(), /"Reference ×" \+ refs\.length \+ " · " \+ entry\.code \+ " · " \+ \(c\.title \|\| "untitled"\)/,
      'genRef should label the job "Reference ×N · <shot code> · <title>" -- how many ' +
      "references went in is the one number that path's own confirm already surfaces");
  });

  test("runGen takes the job label as its own parameter (not reusing the confirm text)", () => {
    // `label` is already taken: it's the confirmSpend() question ("Edit the open frame of X?"),
    // which is a prompt, not a tray row. The job label has to be its own argument.
    assert.match(src, /const runGen = async \(setState, cardId, endpoint, body, priceBody, label, jobLabel\) =>/,
      "runGen should take an explicit jobLabel parameter so genEdit/genRef each supply their own " +
      "tray label, instead of reusing the confirm-dialog question");
    assert.match(runGenBody(), /window\.Jobs\.register\(d\.task_id, jobLabel\)/,
      "runGen should register with the jobLabel its caller supplied");
  });
});

describe("pollTaskWithCeiling nudges the tray the moment it learns the real state", () => {
  // Same treatment pollShot got (loom-activity-tracker-live-update.test.js): the /api/task-status
  // response that reports done/failed is the very call that made the server write the
  // authoritative terminal job event, so refreshing right then can't race it -- and without the
  // nudge the tray is only ever as fresh as its own independent ~2.5-7s cycle.
  const NUDGE = /if \(window\.JobsCard && window\.JobsCard\.refresh\) window\.JobsCard\.refresh\(\);/;

  test("the done branch calls window.JobsCard.refresh()", () => {
    const fn = pollCeilingBody();
    const doneIdx = fn.indexOf('cls.phase === "done"');
    const failedIdx = fn.indexOf('cls.phase === "failed"');
    assert.ok(doneIdx >= 0 && failedIdx >= 0, "expected both done and failed branches");
    assert.match(fn.slice(doneIdx, failedIdx), NUDGE,
      "pollTaskWithCeiling's done branch never nudges the shared Activity tracker, so an " +
      "Image/Edit/Reference row sits on stale 'running' until the tray's own unsynchronized " +
      "poll cycle happens to catch up -- the same defect pollShot was already fixed for");
  });

  test("the failed branch calls window.JobsCard.refresh() too", () => {
    const fn = pollCeilingBody();
    const failedIdx = fn.indexOf('cls.phase === "failed"');
    const elseIdx = fn.indexOf("else again(4000)");
    assert.ok(failedIdx >= 0 && elseIdx > failedIdx, "expected the failed branch and the retry tail");
    assert.match(fn.slice(failedIdx, elseIdx), NUDGE,
      "pollTaskWithCeiling's failed branch never nudges the tray -- a failed still would leave " +
      "the row showing 'running' until an independent cycle refreshed it");
  });

  test("the ceiling branch does NOT nudge -- nothing server-side changed there", () => {
    // Deliberate asymmetry, mirroring pollShot's pause(): hitting the 6h ceiling only means
    // THIS TAB stopped asking. No terminal event was written, so there is nothing new for the
    // tray to read; the server's own orphan-reconciliation sweep owns that case.
    const fn = pollCeilingBody();
    const againIdx = fn.indexOf("const again = (ms) =>");
    assert.ok(againIdx >= 0, "expected the again()/ceiling helper");
    assert.doesNotMatch(fn.slice(againIdx), NUDGE,
      "the ceiling path must not nudge the tray -- no job event was written, so a refresh " +
      "would just re-read the same 'running' row");
  });

  test("the per-drawer state writes are untouched (the badges still work as before)", () => {
    const fn = pollCeilingBody();
    assert.match(fn, /setState\(\(s\) => \(\{ \.\.\.s, \[cardId\]: \{ phase: "done", msg: "Done", mid: cls\.mid \} \}\)\);/,
      "the drawer's own 'done' state write must stay unmodified");
    assert.match(fn, /setState\(\(s\) => \(\{ \.\.\.s, \[cardId\]: \{ phase: "error", msg: cls\.msg \} \}\)\);/,
      "the drawer's own 'failed' state write must stay unmodified");
  });
});

describe("nothing that is registered can be left spinning forever (the make-it-worse risk)", () => {
  // Registering a job that nothing ever resolves would be WORSE than the silent miss it
  // replaces: a permanently spinning card. These assertions pin the end-to-end chain.
  test("the poller these paths use polls /api/task-status, the endpoint that writes the terminal event", () => {
    assert.match(pollCeilingBody(), /fetch\("\/api\/task-status\?task_id=" \+ tid\)/,
      "pollTaskWithCeiling must poll /api/task-status -- that route's done/failed branches are " +
      "what write the authoritative terminal job event (media_ids included). If these paths " +
      "polled anything else, registration alone would strand every job at 'running'.");
  });

  test("both private pollers route through it, so all three paths share that guarantee", () => {
    assert.match(src, /const pollImg = \(cardId, tid\) => pollTaskWithCeiling\(tid, setGenImgState, cardId\);/,
      "pollImg (genImage) must route through pollTaskWithCeiling");
    assert.match(runGenBody(), /const poll = \(tid\) => pollTaskWithCeiling\(tid, setState, cardId\);/,
      "runGen (genEdit/genRef) must route through pollTaskWithCeiling");
  });

  test("registration uses type 'generate' + a numeric task id, so the server's orphan sweep can reap it", () => {
    // Backstop for a tab closed mid-render: these three paths (unlike pollShot) have no
    // resume-on-reload, so if the page goes away nothing client-side ever polls again.
    // resolve_orphan_jobs (pixai_gallery_backup.py) only considers jobs whose type is
    // 'generate' and whose job_id is all digits -- which is exactly what Jobs.register posts
    // for a PixAI task id.
    assert.match(notify, /type:'generate'/,
      "Jobs.register must post type:'generate' or the server-side orphan-reconciliation sweep " +
      "(resolve_orphan_jobs, run on every /api/jobs read) will skip these jobs and a closed tab " +
      "would leave the row spinning until it simply aged out");
  });
});

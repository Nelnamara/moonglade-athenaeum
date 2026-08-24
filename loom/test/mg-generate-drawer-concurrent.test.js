import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Concurrent generations (owner-approved 2026-07-23): PixAI runs tasks in parallel, so the video
// Generate drawer (the React <VideoDrawer> the Gallery Video tab AND the Loom's Deep Focus both
// mount) does NOT lock its own Go button for the whole render. doGenerate() frees the button the
// moment the server answers (accepted or rejected) instead of waiting on a terminal phase, and
// each submission gets its OWN appended line (setResults concat) instead of one shared strip a
// second submission would overwrite.
//
// [2026-08-23: the drawer's own POST + poll loop are GONE -- it rides gen/submitTask.js and the
// Jobs engine's single poller (see submit-road-structure.test.js for why). Every property below
// is the same property; only where it is enforced moved. The old "each poll loop tracks its
// timeout in a shared pollTimers ref array so a second submission cannot clearTimeout the first
// one's" guard is replaced by a STRONGER one: this component owns no poll timers at all, and the
// engine's `seen` map makes two loops for one task id impossible from anywhere.]
//
// Since the no-vanilla port (2026-08-08) this is a plain source-text check on the React component
// (the suite has no React render harness); before the port it read static/mg-generate-drawer.js's
// class methods. Real interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8")
  .replace(/\r\n/g, "\n");
const jobs = readFileSync(path.join(__dirname, "../../gallery/src/notify/jobs.js"), "utf8")
  .replace(/\r\n/g, "\n");

function genBody() {
  const i = src.indexOf("const doGenerate = async () => {");
  assert.ok(i >= 0, "expected to find doGenerate() in VideoDrawer.jsx");
  // Declared at the component's 2-space indent, so its own closing brace is the first "\n  };"
  // after it (its nested closures all close at the 4-space "    };").
  const end = src.indexOf("\n  };", i);
  assert.ok(end > i, "could not find the end of doGenerate()");
  return src.slice(i, end);
}

function phaseBody() {
  const body = genBody();
  const i = body.indexOf("const onPhase = (phase, d) => {");
  assert.ok(i >= 0, "expected to find doGenerate's onPhase handler");
  const end = body.indexOf("\n    };", i);
  assert.ok(end > i, "could not find the end of onPhase");
  return body.slice(i, end);
}

describe("<VideoDrawer> frees its Go button on submit-answer, not on task completion", () => {
  test("doGenerate() unlocks the moment the road returns, before branching on the answer", () => {
    assert.match(src, /const unlock = \(\) => \{ st\.current\.rendering = false; rerender\(\); \};/,
      "the submit-freeing closure must exist");
    const body = genBody();
    const awaitIdx = body.indexOf("await submitTask(");
    const unlockIdx = body.indexOf("unlock();", awaitIdx);
    const errIdx = body.indexOf("if (!tid)");
    assert.ok(awaitIdx >= 0, "expected the awaited submitTask call");
    assert.ok(unlockIdx >= 0 && errIdx >= 0);
    assert.ok(awaitIdx < unlockIdx && unlockIdx < errIdx,
      "unlock() must run as soon as the road answers the submit, before checking whether it " +
      "was accepted -- otherwise a rejected submit could leave the button disabled, or an " +
      "accepted one stays locked until some later check");
  });

  test("the phase handler never frees the Go button -- only renders into its line", () => {
    const body = phaseBody();
    assert.doesNotMatch(body, /rendering\s*=\s*false/,
      "a tracker phase must not touch the rendering/Go-button flag -- unlocking happens once, at submit-answer");
    assert.doesNotMatch(body, /hostBusy\s*=/,
      "a tracker phase must not touch the host-busy flag either");
  });
});

describe("<VideoDrawer> gives each submission its own result line", () => {
  test("pushLine() appends a fresh line (setResults concat), it does not overwrite the strip", () => {
    assert.match(src, /setResults\(\(rs\) => rs\.concat\(/,
      "concurrent submissions need their own line -- the result list must be appended, never " +
      "replaced wholesale, or a second submission would wipe the first task's still-live status");
  });

  test("every phase renders into its OWN line via updateLine(id, …), never the whole strip", () => {
    // The core concurrency guard (restored after the 2026-08-08 port dropped it): a submission's
    // status/result must target ONLY its own line by id, never a wholesale rewrite of the shared
    // result list that would erase a SECOND concurrent submission's still-live status. `id` is
    // the line this submission opened; both the road's emit adapter and the phase handler close
    // over it, so two concurrent submits write to two different lines by construction.
    const body = genBody();
    assert.match(body, /const emitLine = \(patch\) => \{/,
      "the road paints through this drawer's own line adapter");
    assert.ok((body.match(/updateLine\(id,/g) || []).length >= 4,
      "the adapter and the phase handler must both patch this submission's line by id");
    assert.doesNotMatch(body, /setResults\(\s*\[/,
      "a submission must not replace the whole result list with a fresh array");
    assert.doesNotMatch(body, /updateLine\(\s*(?:lineSeq|results)/,
      "a line must be addressed by the id this submission opened, never by position or by a shared counter");
    assert.match(src, /const updateLine = \(id, patch\) => setResults\(\(rs\) => rs\.map\(/,
      "updateLine must map-patch the matching line by id (rs.map, id===id ? {...l,...patch} : l), " +
      "not overwrite the strip -- a wholesale setResults([...]) here is the exact concurrent-wipe regression");
  });
});

describe("<VideoDrawer> tracks concurrent submissions independently", () => {
  test("the drawer owns no poll timers at all -- tracking is the Jobs engine's", () => {
    // Stronger than the pollTimers-array guard it replaces (2026-08-23): there is no per-drawer
    // timer bookkeeping left to get wrong, so a second concurrent submission has nothing of the
    // first one's to clobber. The engine keys the loop off the task id instead.
    assert.ok(!src.includes("pollTimers"),
      "a private poll-timer array has come back -- the drawer must not run its own poll loop");
    assert.doesNotMatch(src, /fetch\("\/api\/task-status/,
      "the drawer must not poll /api/task-status; notify/jobs.js is the one poller");
    assert.match(src, /import \{ submitTask \} from "\.\.\/gen\/submitTask\.js";/);
  });

  test("the engine cannot start two loops for one task id, from any host", () => {
    assert.match(jobs, /export function track\(id, label, cb, count\) \{\n\s*if \(!id \|\| seen\[id\]\) return;/,
      "track() must refuse a task id it has already seen -- that de-dupe is what makes a stray " +
      "double-call unable to double-POST /api/jobs or start a competing poll loop");
    assert.match(jobs, /export function register\(id, label, count\) \{\n\s*if \(!id \|\| seen\[id\]\) return;/,
      "register() is de-duped by the same map, which is why a host may keep its own belt-and-braces " +
      "register beside the road's (the Loom does)");
  });

  test("the unmount effect sweeps only paint timers -- never anything tracking a charged task", () => {
    const i = src.indexOf("useEffect(() => () => {");
    assert.ok(i >= 0, "expected the unmount cleanup effect");
    const body = src.slice(i, src.indexOf("}, []);", i));
    assert.match(body, /clearTimeout\(chipTimer\.current\); clearTimeout\(previewTimer\.current\);/,
      "the chip and preview paint timers are this component's and must still be swept");
    assert.doesNotMatch(body, /poll|task|connected/i,
      "unmount must not stop tracking a submitted task. It used to sweep its own poll timers here, " +
      "which is precisely why a host had to defer unmount and mount the mobile drawer a level " +
      "higher: closing a view mid-render silently stopped watching an already-charged ~210k-credit " +
      "task while the server kept billing it. The Jobs engine's poller holds no component " +
      "reference and outlives this node on purpose");
  });
});

// Adversarial-review fixes (2026-08-08, commit after 134dcb9).
describe("<VideoDrawer> never orphans a paid submit when it unmounts mid-round-trip (review #2)", () => {
  test("emit() dispatches off a node ref that SURVIVES unmount, not the React-nulled rootRef", () => {
    assert.match(src, /const liveNode = useRef\(null\);/, "a retained node ref must exist");
    assert.match(src, /const setRoot = useCallback\(\(n\) => \{ rootRef\.current = n; if \(n\) liveNode\.current = n; \}, \[\]\);/,
      "setRoot must stash the node into liveNode and never null it");
    const emitIdx = src.indexOf("const emit = useCallback");
    const emitBody = src.slice(emitIdx, src.indexOf("}, []);", emitIdx));
    assert.match(emitBody, /const n = liveNode\.current;/,
      "emit must dispatch off the retained liveNode -- rootRef is nulled on unmount, and a submit " +
      "resolving after unmount would then drop the spend-tracking mg-submit and orphan a charged render");
    assert.match(src, /<div ref=\{setRoot\}/, "the root div must use the setRoot callback ref");
  });
});

describe("<VideoDrawer> reports submit-time failures to the host (review #3)", () => {
  const road = readFileSync(path.join(__dirname, "../../gallery/src/gen/submitTask.js"), "utf8")
    .replace(/\r\n/g, "\n");

  test("doGenerate emits mg-error on a server rejection AND on a network error", () => {
    // Both failure classes now arrive as the SAME signal -- the road returns null -- so the host
    // half is one branch instead of two. The Loom's onVideoError must still run either way, or a
    // rejected shot shows no error badge on the board when the Video tab is collapsed.
    assert.match(genBody(), /if \(!tid\) \{ emit\("mg-error", \{ error: lastErr \|\| "submit failed" \}\); return; \}/,
      "a null task id from the road must raise mg-error to the host, carrying whatever the road said");
    assert.match(genBody(), /lastErr = patch\.text;/,
      "the adapter must remember the road's error text -- a submit-time rejection never reaches " +
      "onPhase, so this is the only place the host's message can come from");
  });

  test("the road really does return null for BOTH -- a rejection and no answer at all", () => {
    // The branch above is only as good as this: if either failure path stopped returning null,
    // the drawer would report success on a submit that never happened.
    const rejection = road.indexOf("if (d.error || !d.task_id) {");
    const transport = road.indexOf("} catch {");
    assert.ok(rejection >= 0 && transport >= 0, "expected both failure paths in submitTask");
    assert.match(road.slice(rejection, rejection + 260), /return null;/,
      "an HTTP-200 {error} rejection must return null");
    assert.match(road.slice(transport, transport + 400), /return null;/,
      "a transport failure must return null too -- and its own message says the task MAY exist, " +
      "which is why the drawer no longer says the bare 'network error' that invited a resubmit");
  });
});

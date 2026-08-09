import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Concurrent generations (owner-approved 2026-07-23): PixAI runs tasks in parallel, so the video
// Generate drawer (the React <VideoDrawer> the Gallery Video tab AND the Loom's Deep Focus both
// mount) does NOT lock its own Go button for the whole render. doGenerate() frees the button the
// moment fetch() resolves (server answered, accepted or rejected) instead of waiting on poll() to
// reach a terminal phase, and each submission gets its OWN appended line (setResults concat)
// instead of one shared strip a second submission would overwrite. poll() tracks its timeout in a
// shared pollTimers REF ARRAY instead of a single field a second concurrent submission would
// clobber via clearTimeout -- silently killing the first submission's poll loop.
//
// Since the no-vanilla port (2026-08-08) this is a plain source-text check on the React component
// (the suite has no React render harness); before the port it read static/mg-generate-drawer.js's
// class methods. Real interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

function pollBody() {
  const i = src.indexOf("const poll = (taskId, lineId) => {");
  assert.ok(i >= 0, "expected to find poll() in VideoDrawer.jsx");
  // poll() is declared at the component's 2-space indent, so its own closing brace is the first
  // "\n  };" after it (nested schedule/tick/pause close at 4-space "    };").
  const end = src.indexOf("\n  };", i);
  return src.slice(i, end);
}

describe("<VideoDrawer> frees its Go button on submit-answer, not on task completion", () => {
  test("doGenerate() unlocks inside the submit .then(), before branching on d.error", () => {
    assert.match(src, /const unlock = \(\) => \{ st\.current\.rendering = false; rerender\(\); \};/,
      "the submit-freeing closure must exist");
    const thenIdx = src.indexOf(".then((d) => {", src.indexOf("/api/loom/generate"));
    assert.ok(thenIdx >= 0, "expected the submit response .then((d) => { ... handler");
    const body = src.slice(thenIdx);
    const unlockIdx = body.indexOf("unlock();");
    const errIdx = body.indexOf("if (d.error || !d.task_id)");
    assert.ok(unlockIdx >= 0 && errIdx >= 0);
    assert.ok(unlockIdx < errIdx,
      "unlock() must run as soon as the server answers the submit, before checking whether it " +
      "was accepted -- otherwise a rejected submit could leave the button disabled, or an " +
      "accepted one stays locked until some later check");
  });

  test("poll()'s own body never frees the Go button -- only renders into its line", () => {
    const body = pollBody();
    assert.doesNotMatch(body, /rendering\s*=\s*false/,
      "poll() must not touch the rendering/Go-button flag -- unlocking happens once, at submit-answer");
    assert.doesNotMatch(body, /hostBusy\s*=/,
      "poll() must not touch the host-busy flag either");
  });
});

describe("<VideoDrawer> gives each submission its own result line", () => {
  test("pushLine() appends a fresh line (setResults concat), it does not overwrite the strip", () => {
    assert.match(src, /setResults\(\(rs\) => rs\.concat\(/,
      "concurrent submissions need their own line -- the result list must be appended, never " +
      "replaced wholesale, or a second submission would wipe the first task's still-live status");
  });
});

describe("<VideoDrawer> tracks concurrent poll loops independently", () => {
  test("poll() keys its timeout off the shared pollTimers ref array, not a single field", () => {
    const body = pollBody();
    assert.match(body, /pollTimers\.current\.push\(timer\)/,
      "expected poll()'s schedule() to push its timeout into the shared pollTimers array");
    assert.match(body, /pollTimers\.current\.indexOf\(timer\)/,
      "expected poll()'s schedule() to splice the spent timer out of the shared array by identity " +
      "-- a second concurrent submission must not be able to clobber the first one's pending timeout");
  });

  test("the unmount effect sweeps every tracked poll timer, not just the most recent one", () => {
    assert.match(src, /pollTimers\.current\.forEach\(\(t\) => clearTimeout\(t\)\)/,
      "the unmount cleanup must clear every outstanding poll timeout -- with concurrent submissions " +
      "clearing only the most recent would leave every other task's poll loop running after unmount");
  });
});

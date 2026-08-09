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

  test("poll() renders each status/result into its OWN line via updateLine(lineId, …), never the whole strip", () => {
    // The core concurrency guard (restored after the 2026-08-08 port dropped it): a submission's
    // poll status/result must target ONLY its own line by id, never a wholesale rewrite of the
    // shared result list that would erase a SECOND concurrent submission's still-live status.
    const body = pollBody();
    assert.match(body, /updateLine\(lineId,/,
      "poll() must patch its own submission's line by id, not the whole strip");
    assert.doesNotMatch(body, /setResults\(\s*\[/,
      "poll() must not replace the whole result list with a fresh array");
    assert.match(src, /const updateLine = \(id, patch\) => setResults\(\(rs\) => rs\.map\(/,
      "updateLine must map-patch the matching line by id (rs.map, id===id ? {...l,...patch} : l), " +
      "not overwrite the strip -- a wholesale setResults([...]) here is the exact concurrent-wipe regression");
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
  test("doGenerate emits mg-error on a server rejection AND on a network error", () => {
    const genIdx = src.indexOf("const doGenerate =");
    const genBody = src.slice(genIdx, src.indexOf("\n  };", genIdx));
    assert.match(genBody, /updateLine\(id, \{ kind: "error", text: msg, moon: false \}\);\s*\n\s*emit\("mg-error", \{ error: msg \}\);/,
      "the submit-rejection branch must emit mg-error (matching the vanilla _renderErrorInto)");
    assert.match(genBody, /updateLine\(id, \{ kind: "error", text: "network error", moon: false \}\); emit\("mg-error", \{ error: "network error" \}\);/,
      "the submit .catch must emit mg-error");
  });
});

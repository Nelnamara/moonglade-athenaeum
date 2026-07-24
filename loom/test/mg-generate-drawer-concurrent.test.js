import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Concurrent generations (owner-approved 2026-07-23): PixAI itself runs tasks in parallel,
// so <mg-generate-drawer> (the shared Video-tab component the Gallery AND the Loom's Deep
// Focus both mount) no longer locks its own Go button for the whole render. _generate()
// now frees the button the moment fetch() resolves (server answered, accepted or
// rejected) instead of waiting on _poll() to reach a terminal phase, and each submission
// gets its OWN appended line inside .mgd-result instead of one shared innerHTML a second
// submission would overwrite. _poll() itself now tracks its timeout in this._pollTimers
// (an array of every outstanding timeout) instead of the old single this._pollTimer field,
// which a second concurrent submission's _poll() call used to clobber via clearTimeout --
// silently killing the FIRST submission's poll loop the moment a second one started.
//
// static/mg-generate-drawer.js is a plain <script>, no build step, no jsdom in this test
// runner -- source-presence assertions are the established pattern here (see
// mg-generate-drawer-parity.test.js, mg-model-picker-multi-select.test.js). Real
// interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Normalized to LF regardless of local checkout line endings (.gitattributes normalizes
// the stored blob to LF, but core.autocrlf legitimately checks it out as CRLF on Windows)
// -- extractMethod's regexes below anchor on exact `\n` boundaries around braces, which a
// stray `\r` would break.
const src = readFileSync(path.join(__dirname, "../../static/mg-generate-drawer.js"), "utf8")
  .replace(/\r\n/g, "\n");

function extractMethod(name) {
  // Methods are `name(...) {` at class-body indent (4 spaces) -- grab from the signature to
  // the next same-indent `}` on its own line (the method's closing brace).
  const re = new RegExp("\\n    " + name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&") + "\\([^)]*\\) \\{\\n([\\s\\S]*?)\\n    \\}\\n");
  const m = src.match(re);
  assert.ok(m, `expected to find a "${name}(...) {" method in mg-generate-drawer.js`);
  return m[0];
}

describe("<mg-generate-drawer> frees its Go button on submit-answer, not on task completion", () => {
  const generateFn = extractMethod("_generate");

  test("_generate() unlocks the button inside the fetch().then(), before branching on d.error", () => {
    assert.match(generateFn, /function unlock\(\) \{/, "the submit-freeing closure must exist");
    const thenIdx = generateFn.indexOf(".then(function (d) {");
    assert.ok(thenIdx >= 0, "expected the submit response .then(function (d) { ... handler");
    const body = generateFn.slice(thenIdx);
    const unlockIdx = body.indexOf("unlock();");
    const errCheckIdx = body.indexOf("if (d.error || !d.task_id)");
    assert.ok(unlockIdx >= 0 && errCheckIdx >= 0);
    assert.ok(unlockIdx < errCheckIdx,
      "unlock() must run as soon as the server answers the submit, before checking whether " +
      "it was accepted -- otherwise a rejected submit could leave the button disabled, or " +
      "an accepted one stays locked until some later check");
  });

  test("_poll() is no longer handed a button-unlock callback", () => {
    // The old signature was _poll(taskId, done) where `done` unlocked the button on a
    // terminal phase. It must now take the submission's own result `line` instead --
    // completion should only ever render into that line, never touch the button.
    assert.match(generateFn, /self\._poll\(d\.task_id, line\)/,
      "_generate() must hand _poll() this submission's own result line, not a button-unlock callback");
    assert.doesNotMatch(generateFn, /self\._poll\(d\.task_id, done\)/,
      "_poll() is still being driven by a button-unlock callback -- the button would stay " +
      "locked for the whole render again, exactly the bug this feature fixes");
  });

  test("_poll()'s own body never frees the Go button -- only renders into its line", () => {
    const pollFn = extractMethod("_poll");
    assert.doesNotMatch(pollFn, /_go\.disabled\s*=\s*false/,
      "_poll() must not touch the Go button directly -- unlocking happens once, at submit-answer");
    assert.doesNotMatch(pollFn, /\bdone\(\)/,
      "_poll() still calls a done()-style unlock callback on a terminal phase");
  });
});

describe("<mg-generate-drawer> gives each submission its own result line", () => {
  test("_generate() appends a fresh line via _newResultLine() instead of overwriting .mgd-result", () => {
    const generateFn = extractMethod("_generate");
    assert.match(generateFn, /var line = this\._newResultLine\(\);/,
      "concurrent submissions need their own line -- .mgd-result must never be overwritten wholesale");
    assert.doesNotMatch(generateFn, /this\._result\.innerHTML\s*=/,
      "_generate() still rewrites the whole result strip -- a second submission would wipe " +
      "the first task's still-live status/result");
  });

  test("_newResultLine() appends, it does not replace", () => {
    const newLineFn = extractMethod("_newResultLine");
    assert.match(newLineFn, /this\._result\.appendChild\(line\);/,
      "_newResultLine() must append the new line, not assign over the strip's own innerHTML");
  });

  test("completion/error/slow/paused renders inside _poll() all target the submission's own `line`, never `this._result`", () => {
    const pollFn = extractMethod("_poll");
    assert.doesNotMatch(pollFn, /this\._result\.innerHTML/,
      "a status update inside _poll() writes to the whole strip instead of this submission's own line");
    assert.match(pollFn, /line\.innerHTML/, "expected _poll() to still render into `line` somewhere");
  });
});

describe("<mg-generate-drawer> tracks concurrent poll loops independently", () => {
  test("_poll() no longer keys its timeout off a single shared this._pollTimer field", () => {
    // The old code did `this._pollTimer = setTimeout(...)` and `clearTimeout(this._pollTimer)`
    // at the top of every _poll() call -- a second submission's _poll() would silently kill
    // the FIRST submission's still-pending poll timeout the moment it started.
    const pollFn = extractMethod("_poll");
    // (?!s) so this doesn't false-positive on this._pollTimerS, the new plural field --
    // "_pollTimer" is a literal PREFIX of "_pollTimers".
    assert.doesNotMatch(pollFn, /this\._pollTimer(?!s)/,
      "_poll() still reads/writes a single this._pollTimer -- a second concurrent submission " +
      "would clobber the first one's pending poll timeout via clearTimeout, silently killing " +
      "its poll loop");
    assert.match(pollFn, /this\._pollTimers/,
      "expected _poll() to track its timeout in the shared this._pollTimers array instead");
  });

  test("disconnectedCallback() sweeps every tracked poll timer, not just the most recent one", () => {
    const m = src.match(/disconnectedCallback\(\) \{\n([\s\S]*?)\n    \}\n/);
    assert.ok(m, "expected to find disconnectedCallback()");
    assert.doesNotMatch(m[1], /clearTimeout\(this\._pollTimer\)/,
      "disconnectedCallback() only clears the old single this._pollTimer -- with concurrent " +
      "submissions this would leave every OTHER task's poll loop running after the element " +
      "is removed from the DOM");
    assert.match(m[1], /this\._pollTimers/, "expected disconnectedCallback() to sweep this._pollTimers");
  });
});

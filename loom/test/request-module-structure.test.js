import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* ONE REQUEST MODULE (2026-08-23). Third sibling of price-probe-structure.test.js and
   submit-road-structure.test.js, and the same argument in a wider place: this is a STRUCTURAL
   property, and structural properties rot back, because the cheapest way to "just call the API
   from here" is another inline fetch.

   What it prevents is not duplication for its own sake. Before this, 46 files hand-rolled
   fetch + r.json() + an error decision, and `postJSON` existed in FOUR copies that DISAGREED
   about which answer was authoritative:

     api.js                       ignored r.ok entirely -- the body was the whole answer
     hooks/useControlPanel.js     ignored r.ok, {error: String(e)} on a throw
     hooks/useDuplicateReview.js  !r.ok || d.error -> {error}
     components/ActionsMenu.jsx   the same again, hand-copied

   plus a private getJSON in AccountSubOverlay.jsx. This app's spend routes deliberately answer
   errors with HTTP 200 {"error": ...} (gen/submitTask.js's contract), so a copy that keys off
   r.ok reads a refusal as a success. That is the failure mode a fifth copy would re-introduce,
   and it is invisible in any one file -- exactly the kind of thing only a tree-level check
   catches. There is no jsdom/React harness in this runner, so source-level guards are the
   established pattern for files in this position. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const MODULE = "api.js";

/* The three files allowed to keep their own fetch. Each is here because api.js's ONE error
   rule -- the body's {error} is authoritative -- deliberately collapses a distinction that
   file's own contract depends on. Adding a fourth name is a deliberate edit to this list. */
const EXEMPT = {
  "gen/usePriceProbe.js":
    "owns the AbortController + timeout, and must tell an ABORTED price check (setPrice(null)) "
    + "apart from an HTTP-200 {error} body (setPrice(d)) -- the spend gate reads that difference",
  "gen/submitTask.js":
    "the spend road: a transport failure says 'the task MAY still have been submitted', which is "
    + "a different sentence from a body error, and that difference is a spend-safety guarantee",
  "notify/jobs.js":
    "the /api/task-status poller: the fetch REJECTION is its retry trigger (again(4000)), and an "
    + "{error} body would read as a non-terminal phase and re-poll at the wrong cadence",
};

function walk(dir, out = []) {
  readdirSync(dir).forEach((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(js|jsx)$/.test(name)) out.push(full);
  });
  return out;
}
const files = walk(SRC);
const rel = (f) => path.relative(SRC, f).split(path.sep).join("/");
const read = (f) => readFileSync(f, "utf8").replace(/\r\n/g, "\n");
// A "no file may do X" assertion has to read CODE only: the comments explaining why a call was
// removed name it, and would otherwise trip the very guard they document. (Same device, same
// reason, as submit-road-structure.test.js's own codeOnly.)
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const fileNamed = (r) => {
  const f = files.find((x) => rel(x) === r);
  assert.ok(f, "expected " + r + " to exist");
  return read(f);
};

describe("api.js is the only place a request is made", () => {
  test("fetch( appears only in api.js and the three named exemptions", () => {
    const callers = files.filter((f) => /\bfetch\(/.test(codeOnly(read(f)))).map(rel).sort();
    const expected = [MODULE, ...Object.keys(EXEMPT)].sort();
    assert.deepEqual(callers, expected,
      "a hand-rolled fetch means a fifth private answer to 'is the status or the body "
      + "authoritative?', on an app whose spend routes answer errors with HTTP 200 {error}. "
      + "Call apiGet/apiPost/apiUpload instead. Found: " + JSON.stringify(callers));
  });

  test("api.js itself makes exactly one request and reads exactly one body", () => {
    // If the module grew a second fetch, the one error rule would already have two homes.
    const api = fileNamed(MODULE);
    assert.equal((codeOnly(api).match(/\bfetch\(/g) || []).length, 1,
      "api.js must funnel every call through its single request() helper");
    assert.equal((codeOnly(api).match(/\.json\(\)/g) || []).length, 1,
      "one place parses the body, so one place decides what an error is");
  });

  test("the one error rule is written once, and keys off the body first", () => {
    const api = codeOnly(fileNamed(MODULE));
    const bodyWins = api.indexOf("if (d && d.error)");
    const statusFallback = api.indexOf("if (!r.ok)");
    assert.ok(bodyWins >= 0 && statusFallback >= 0, "expected both halves of the rule in api.js");
    assert.ok(bodyWins < statusFallback,
      "the BODY's {error} must be read before the status -- a spend route refuses with HTTP 200 "
      + "{error}, and reading r.ok first turns that refusal into a success");
    assert.match(api, /error: "network error: "/,
      "a transport failure must resolve to an {error}, not reject -- callers branch once");
  });

  test("each exemption is still the file it says it is", () => {
    // A name left on the list after its reason evaporated is a licence, not an exemption.
    for (const name of Object.keys(EXEMPT)) {
      assert.match(codeOnly(fileNamed(name)), /\bfetch\(/,
        name + " no longer fetches -- take it off the exemption list rather than leaving a "
        + "standing permission behind: " + EXEMPT[name]);
    }
  });
});

describe("no file keeps a private poster or getter of its own", () => {
  test("nothing under gallery/src defines postJSON or getJSON", () => {
    const DEF = /(?:function|const|let|var)\s+(?:postJSON|getJSON)\b|(?:postJSON|getJSON)\s*[:=]\s*(?:async\s*)?(?:function|\()/;
    const offenders = files.filter((f) => DEF.test(codeOnly(read(f)))).map(rel).sort();
    assert.deepEqual(offenders, [],
      "postJSON was four hand-maintained copies that disagreed about the error rule, and getJSON "
      + "was a fifth, private one. apiPost/apiGet replaced all five. Found: "
      + JSON.stringify(offenders));
  });
});

describe("every caller gets the seam from the one module", () => {
  test("a file that calls apiGet/apiPost/apiUpload imports them from api.js", () => {
    const CALL = /\bapi(?:Get|Post|Upload)\(/;
    const IMPORT = /from\s+"\.{1,2}(?:\/\.\.)*\/?api\.js"/;
    const offenders = files
      .filter((f) => rel(f) !== MODULE)
      .filter((f) => CALL.test(codeOnly(read(f))))
      .filter((f) => !IMPORT.test(read(f)))
      .map(rel).sort();
    assert.deepEqual(offenders, [],
      "a local apiGet/apiPost would be the same divergence wearing the new name. Found: "
      + JSON.stringify(offenders));
  });

  test("the migration actually happened -- most of the tree rides the seam", () => {
    // Guards against the whole suite passing vacuously if the callers were deleted rather than
    // migrated. The floor is deliberately low; the number itself lives in the changelog.
    const callers = files.filter((f) => /\bapi(?:Get|Post|Upload)\(/.test(codeOnly(read(f))));
    assert.ok(callers.length >= 40,
      "expected the request module to have the whole tree as callers, found " + callers.length);
  });
});

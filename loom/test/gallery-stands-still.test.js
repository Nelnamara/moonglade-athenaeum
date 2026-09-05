import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE LIBRARY STANDS STILL (owner, 2026-09-05).

   The policy in one sentence: nothing moves the owner's view of the library except his own
   hands. A generation finishing announces itself -- the completion toast, the Activity row
   whose thumbnail opens the new record -- and never restacks the grid under a reader.

   What it replaced: App.jsx's `const refresh = () => { load(1, true); ... }`, fired by
   mg-gen-done (gen/submitTask.js dispatches it for every edit / enhance / fix / scene /
   generate / upscale) and by mg-result (the video drawer). Reading page 7, a job you queued
   ten minutes ago lands, and page 1 replaces the grid you were reading.

   tests/test_render_harness.py::test_a_finished_generation_never_moves_the_page_the_owner_
   is_reading measures the DESKTOP behaviour in a real browser: page 2 stays, page 1
   refreshes. These are the source-structure guards for the parts that harness cannot see --
   the phone shell (no rendering test drives a phone completion), the selection prune, and
   the third hard-coded jump the same policy governs (Details' onDeleted). Same pattern and
   same reason as loom/test/overlay-open-perf.test.js: no React test renderer here, so what
   can be pinned is the structure the behaviour rests on. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const app = src("App.jsx");
const mobile = src("components/AppMobile.jsx");
const library = src("hooks/useLibrary.js");

/** The body of the arrow function assigned to `name`, from the `=>` to the line that closes
    it at the given indent. Enough to read one handler in isolation. */
function bodyOf(source, opener, closer) {
  const i = source.indexOf(opener);
  assert.ok(i >= 0, "not found: " + opener);
  const j = source.indexOf(closer, i);
  assert.ok(j > i, "no close for: " + opener);
  return source.slice(i, j);
}

describe("the desktop shell: a completion refreshes only from the default perch", () => {
  const refresh = bodyOf(app, "const refresh = () => {", "    };");

  test("the unconditional half is the credits chip, and only the credits chip", () => {
    assert.match(refresh, /fetchAccount\(\)\.then\(setAccount\);/);
    // The bare page-1 jump is GONE. This exact line is what the policy retired.
    assert.doesNotMatch(app, /const refresh = \(\) => \{ load\(1, true\); fetchAccount\(\)/);
  });

  test("page 1 is the gate, read off the ref that already tracks the loaded page", () => {
    assert.match(refresh, /if \(pageRef\.current !== 1\) return;/);
    // ...and the gate comes BEFORE the load, not after it.
    assert.ok(refresh.indexOf("pageRef.current !== 1") < refresh.indexOf("load(1, true)"),
      "the page-1 guard must precede the load it guards");
    assert.match(refresh, /load\(1, true\)\.then\(/);
    // pageRef is kept fresh by the same effect the popstate handler relies on.
    assert.match(app, /useEffect\(\(\) => \{ pageRef\.current = page; loadRef\.current = load; \}\);/);
  });

  test("both completion channels ride the one refresh, and the dep array is intact", () => {
    const i = app.indexOf('window.addEventListener("mg-gen-done", onGenDone);');
    assert.ok(i > 0);
    assert.match(app, /const onGenDone = \(\) => \{ refresh\(\); if \(window\.Ach\) window\.Ach\.check\(\); \};/);
    const result = bodyOf(app, "const onResult = () => {", "    };");
    assert.match(result, /refresh\(\);/);
    assert.match(app.slice(i, i + 1400), /\}, \[load\]\);/);
  });

  test("the selection is pruned after the background swap, never left pointing at nothing", () => {
    assert.match(refresh, /if \(data\) pruneSelected\(setSelected, data\.items\);/);
    assert.match(app, /import useLibrary, \{ filterQueryString, pruneSelected \} from "\.\/hooks\/useLibrary\.js";/);
  });
});

describe("Details' delete reloads the page it was opened from", () => {
  const deleted = bodyOf(app, "onDeleted={() => {", "              }}");

  test("the third hard-coded jump to page 1 is gone", () => {
    assert.doesNotMatch(app, /onDeleted=\{\(\) => \{ closeDetails\(\); load\(1, true\); \}\}/);
    assert.match(deleted, /closeDetails\(\);/);
    assert.match(deleted, /const p = Math\.max\(1, pageRef\.current\);/);
    assert.match(deleted, /load\(p, true\)\.then\(/);
  });

  test("an emptied page steps DOWN one, and emptiness is read off the response", () => {
    assert.match(deleted, /if \(p > 1 && !\(data\.items \|\| \[\]\)\.length\) load\(p - 1, true\);/);
    // never below page 1
    assert.doesNotMatch(deleted, /load\(0, true\)/);
  });
});

describe("the phone learns completions exist -- announce-only", () => {
  test("AppMobile listens on BOTH channels the desktop does", () => {
    assert.match(mobile, /window\.addEventListener\("mg-gen-done", onDone\);/);
    assert.match(mobile, /document\.addEventListener\("mg-result", onDone\);/);
    assert.match(mobile, /window\.removeEventListener\("mg-gen-done", onDone\);/);
    assert.match(mobile, /document\.removeEventListener\("mg-result", onDone\);/);
  });

  test("it refreshes the credits chip and nudges the Folio, guarded like every window.* call", () => {
    const onDone = bodyOf(mobile, "const onDone = () => {", "    };");
    assert.match(onDone, /fetchAccount\(\)\.then\(setAccount\);/);
    assert.match(onDone, /if \(window\.Ach\) window\.Ach\.check\(\);/);
  });

  test("the library moves only from the phone's own default view: page 1, and not under ◈ Similar", () => {
    const onDone = bodyOf(mobile, "const onDone = () => {", "    };");
    assert.match(onDone, /if \(genPageRef\.current !== 1 \|\| genSimilarRef\.current\) return;/);
    assert.ok(onDone.indexOf("genPageRef.current !== 1") < onDone.indexOf("genLoadRef.current(1, true)"),
      "the default-view guard must precede the load it guards");
    assert.match(onDone, /genLoadRef\.current\(1, true\)\.then\(/);
    assert.match(onDone, /if \(data\) pruneSelected\(setLibSelected, data\.items\);/);
  });

  test("refs, because the listeners mount once and load's identity follows the filters", () => {
    assert.match(mobile, /const genPageRef = useRef\(lib\.page\);/);
    assert.match(mobile, /const genLoadRef = useRef\(lib\.load\);/);
    assert.match(mobile, /const genSimilarRef = useRef\(similarFor\);/);
    assert.match(mobile, /genPageRef\.current = lib\.page;/);
    assert.match(mobile, /genLoadRef\.current = lib\.load;/);
    assert.match(mobile, /genSimilarRef\.current = similarFor;/);
  });

  test("STILL no Jobs.register on the phone shell -- registration belongs to the submit road", () => {
    assert.doesNotMatch(mobile, /Jobs\.register\(/);
  });
});

describe("pruneSelected: the one prune, shared by both shells", () => {
  const fn = bodyOf(library, "export function pruneSelected(setSelected, items) {",
                    "\n}\n");

  test("it is exported from the hook that owns `selected`, and both shells import it", () => {
    assert.match(library, /export function pruneSelected\(setSelected, items\) \{/);
    assert.match(app, /pruneSelected\(setSelected, data\.items\)/);
    assert.match(mobile, /import useLibrary, \{ pruneSelected \} from "\.\.\/hooks\/useLibrary\.js";/);
  });

  test("it reads the previous Set through the updater, and returns it UNCHANGED when nothing dropped", () => {
    assert.match(fn, /setSelected\(\(old\) => \{/);
    assert.match(fn, /if \(!dropped\) return old;/);
    assert.match(fn, /const live = new Set\(\(items \|\| \[\]\)\.map\(\(it\) => it\.media_id\)\);/);
  });

  test("afterMutation is untouched: a USER-initiated mutation still clears the set outright", () => {
    assert.match(app, /const afterMutation = async \(\) => \{/);
    const after = bodyOf(app, "const afterMutation = async () => {", "  };");
    assert.match(after, /setSelected\(new Set\(\)\);/);
    assert.doesNotMatch(after, /pruneSelected/);
  });
});

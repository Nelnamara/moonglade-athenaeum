import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  DEFAULT_PAGING, KEY_LONG_PRESS_MS, PAGINGS, PAGING_LABELS, parsePaging,
} from "../../gallery/src/lib/phoneCore.js";
import {
  PAGING_HINT_KEY, PAGING_KEY, readPaging, readPagingHintSeen, writePaging, writePagingHintSeen,
} from "../../gallery/src/lib/phonePrefs.js";

/* Session U, "Phone paging" (Phone Paging and Nudge Handoff.dc.html, U1b-U5c): the rules behind the
   Pages | Continuous choice, the continuous footer, new-since over stacked pages, the mounted window and
   selection across pages, run as the page states them, plus the structure that wires them in. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const read = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");
const code = (rel) => read(rel).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

function recorder(seed) {
  const data = new Map(Object.entries(seed || {}));
  const log = [];
  return {
    log, data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { log.push(["set", k, v]); data.set(k, String(v)); },
  };
}

describe("U1 the paging choice: the value", () => {
  test("Pages is the default; only an exact 'continuous' is Continuous", () => {
    assert.equal(DEFAULT_PAGING, "pages");
    assert.deepEqual([...PAGINGS], ["pages", "continuous"]);
    assert.equal(parsePaging("continuous"), "continuous");
    for (const v of ["pages", "", null, undefined, "CONTINUOUS", "infinite", 1]) assert.equal(parsePaging(v), "pages");
    assert.deepEqual({ ...PAGING_LABELS }, { pages: "Pages", continuous: "Continuous" });
  });

  test("the long-press on a layout key is the page's 500 ms", () => {
    assert.equal(KEY_LONG_PRESS_MS, 500);
  });

  test("per device: a fresh phone reads Pages and an unseen hint, and writes nothing", () => {
    const s = recorder();
    assert.equal(readPaging(s), "pages");
    assert.equal(readPagingHintSeen(s), false);
    assert.deepEqual(s.log, []);
  });

  test("each writer writes its own key once, normalised; junk reads as the default without a rewrite", () => {
    const s = recorder();
    assert.equal(writePaging("continuous", s), true);
    assert.equal(writePagingHintSeen(s), true);
    assert.deepEqual(s.log.map((e) => e[1]), [PAGING_KEY, PAGING_HINT_KEY]);
    assert.equal(readPaging(s), "continuous");
    assert.equal(readPagingHintSeen(s), true);
    const w = recorder();
    writePaging("sideways", w);
    assert.equal(w.data.get(PAGING_KEY), "pages");
    const junk = recorder({ [PAGING_KEY]: "endless" });
    assert.equal(readPaging(junk), "pages");
    assert.deepEqual(junk.log, []);
  });
});

describe("U1 the paging choice: where it lives", () => {
  test("the hook only wraps the writers in callbacks a tap must invoke, never an effect", () => {
    const hook = code("hooks/usePhonePrefs.js");
    assert.match(hook, /const setPaging = useCallback\(\(v\) => \{ writePaging\(v\); \}, \[\]\);/);
    assert.match(hook, /const markSeen = useCallback\(\(\) => \{ writePagingHintSeen\(\); \}, \[\]\);/);
    assert.doesNotMatch(hook, /useEffect\([^)]*write/);
  });

  test("a long-press on either layout key opens the sheet; a tap still only switches the layout", () => {
    const g = code("components/GalleryMobile.jsx");
    // both keys carry the long-press and keep their own tap
    assert.equal([...g.matchAll(/\{\.\.\.keyPress\}/g)].length, 2, "both ▦ and ▭ carry the long-press");
    assert.match(g, /onClick=\{\(\) => tapKey\("grid"\)\}/);
    assert.match(g, /onClick=\{\(\) => tapKey\("feed"\)\}/);
    // the long-press opens the paging sheet and clears the one-time dot
    assert.match(g, /openSheet\("paging"\)/);
    assert.match(g, /markHintSeen\(\)/);
    assert.match(g, /KEY_LONG_PRESS_MS/);
    // the sheet holds Layout and Paging
    const sheet = code("components/LayoutPagingSheet.jsx");
    assert.match(sheet, /<Row label="Layout" /);
    assert.match(sheet, /<Row label="Paging" /);
    assert.match(sheet, /PAGINGS\.map/);
  });

  test("Control's Library paging row sits right after Data saver and reads the same pref", () => {
    const c = code("components/ControlMobile.jsx");
    assert.match(c, /import PagingRow from "\.\/PagingRow\.jsx";/);
    const saver = c.indexOf("<DataSaverRow />");
    const paging = c.indexOf("<PagingRow />");
    assert.ok(saver > 0 && paging > saver, "Library paging is Data saver's neighbour");
    const row = code("components/PagingRow.jsx");
    assert.match(row, /usePaging\(\)/);
    assert.match(row, /Library paging/);
  });

  test("the keys are private to lib/phonePrefs.js", () => {
    for (const rel of ["components/GalleryMobile.jsx", "components/PagingRow.jsx", "components/LayoutPagingSheet.jsx",
      "hooks/usePhonePrefs.js", "components/AppMobile.jsx"]) {
      let text = "";
      try { text = code(rel); } catch { continue; }
      assert.doesNotMatch(text, /mg_phone_paging/, rel);
    }
  });
});

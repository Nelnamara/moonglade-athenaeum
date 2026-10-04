import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  CONTINUOUS_PAGE, CONTINUOUS_PAGE_METERED, DEFAULT_PAGING, KEY_LONG_PRESS_MS, PAGINGS, PAGING_LABELS,
  PREFETCH_SCREENS, appendUnique, connectionInfo, continuousDone, continuousPageSize, countLabel, endLabel,
  footerState, nearEnd, nextContinuousPage, parsePaging,
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

describe("U2 continuous loading: the rules", () => {
  const wifi = connectionInfo({ type: "wifi" });
  const cell = connectionInfo({ type: "cellular" });
  const unknown = connectionInfo(null);

  test("100 a page; 50 only while Data saver acts on a metered connection", () => {
    assert.equal(CONTINUOUS_PAGE, 100);
    assert.equal(CONTINUOUS_PAGE_METERED, 50);
    assert.equal(continuousPageSize(false, cell), 100, "saver off: the metered connection changes nothing");
    assert.equal(continuousPageSize(true, cell), 50);
    assert.equal(continuousPageSize(true, wifi), 100, "Always on Wi-Fi is not metered");
    assert.equal(continuousPageSize(true, unknown), 100, "a browser that cannot tell is not metered");
    assert.equal(continuousPageSize(true, connectionInfo({ type: "wifi", saveData: true })), 50, "the user's own save-data ask");
  });

  test("the next page follows what is loaded, whatever size cut it (a prepend or a size change overlaps, never gaps)", () => {
    assert.equal(nextContinuousPage(0, 100), 1);
    assert.equal(nextContinuousPage(100, 100), 2);
    assert.equal(nextContinuousPage(300, 100), 4);
    assert.equal(nextContinuousPage(105, 100), 2, "five prepended: page 2 starts 5 before the end and overlaps");
    assert.equal(nextContinuousPage(200, 50), 5, "the size changed to 50: the next 50 start at 200");
    assert.equal(nextContinuousPage(150, 0), 2, "no size is the default 100");
  });

  test("an append keeps only what is not already loaded, in order", () => {
    const a = [{ media_id: "1" }, { media_id: "2" }, { media_id: "3" }];
    const out = appendUnique(a, [{ media_id: "3" }, { media_id: "4" }, { media_id: "5" }]);
    assert.deepEqual(out.map((x) => x.media_id), ["1", "2", "3", "4", "5"]);
    assert.equal(appendUnique(a, [{ media_id: "2" }]), a, "nothing new: the same list, no re-render");
    assert.deepEqual(appendUnique([], [{ media_id: "9" }]).map((x) => x.media_id), ["9"]);
  });

  test("the end is everything the filter matches; no total yet is not the end", () => {
    assert.equal(continuousDone(620, 620), true);
    assert.equal(continuousDone(625, 620), true, "deleted since: more loaded than the total is still the end");
    assert.equal(continuousDone(600, 620), false);
    assert.equal(continuousDone(0, null), false);
    assert.equal(continuousDone(0, 0), true, "an empty filter is its own end");
  });

  test("the next page is asked for when the last row is within 1.5 screens of view", () => {
    assert.equal(PREFETCH_SCREENS, 1.5);
    assert.equal(nearEnd(2000, 800, 800), true, "1200 px below the view: exactly 1.5 screens");
    assert.equal(nearEnd(2001, 800, 800), false);
    assert.equal(nearEnd(500, 800, 800), true, "already in view");
  });

  test("the header count and the end line, formatted like the pager", () => {
    assert.equal(countLabel(300, 3240), "300 of 3,240");
    assert.equal(countLabel(0, null), "");
    assert.equal(endLabel(3240), "That's all 3,240.");
  });

  test("the footer says one thing: loading, the peach retry, the end, or nothing", () => {
    assert.equal(footerState({ busy: true, failed: false, done: false }), "loading");
    assert.equal(footerState({ busy: false, failed: true, done: false }), "failed");
    assert.equal(footerState({ busy: false, failed: false, done: true }), "end");
    assert.equal(footerState({ busy: false, failed: false, done: false }), "idle");
  });
});

describe("U2 continuous loading: the wiring", () => {
  test("useLibrary's append keeps only new pictures and a load can name its page size", () => {
    const lib = code("hooks/useLibrary.js");
    assert.match(lib, /setItems\(\(old\) => \(replace \? data\.items : appendUnique\(old, data\.items\)\)\)/);
    assert.match(lib, /page_size: size \|\| sizeRef\.current \|\| perPage/);
    // the size is a ref the shell sets, so it never changes load's identity (no refetch on its own)
    assert.match(lib, /const setPageSize = useCallback\(/);
    assert.doesNotMatch(lib, /\[applied, media, shelf, perPage, adv, group, [^\]]*size/);
  });

  test("the phone loads the next page through the owner's own road, one request at a time, no automatic retry", () => {
    const app = code("components/AppMobile.jsx");
    assert.match(app, /const loadMore = useCallback\(/);
    assert.match(app, /if \(moreBusy\.current\) return/);
    assert.match(app, /nextContinuousPage\(/);
    assert.match(app, /continuousPageSize\(/);
    // the background refresh after a generation never reflows the stacked list
    assert.match(app, /if \(continuousRef\.current\) return;/);
    // a retry is the same single request
    assert.doesNotMatch(app, /setTimeout\([^)]*loadMore/);
  });

  test("Continuous replaces the pager with the footer and puts the count before the layout keys", () => {
    const g = code("components/GalleryMobile.jsx");
    // no pager in Continuous: the pager reads a page count of 1 there
    assert.match(g, /const pages = continuous \? 1 : pageCount;/);
    assert.match(g, /\{!similar && !loading && pages > 1 && \(/);
    assert.match(g, /className="glm-cfoot"/);
    assert.match(g, /className="glm-pgcount"/);
    assert.ok(g.indexOf('className="glm-pgcount"') < g.indexOf('className="glm-layout"'), "the count sits before the keys");
    // the jump steps aside for the footer as it does for the pager
    assert.match(g, /host\.querySelector\("\.glm-pager, \.glm-cfoot"\)/);
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  CONTINUOUS_PAGE, CONTINUOUS_PAGE_METERED, DEFAULT_PAGING, KEY_LONG_PRESS_MS, PAGINGS, PAGING_LABELS,
  PREFETCH_SCREENS, PREPEND_MAX_PAGES, appendUnique, connectionInfo, continuousDone, continuousPageSize,
  countLabel, endLabel, footerState, isFrontPage, nearEnd, newSince, newestAbove, nextContinuousPage,
  parsePaging, prependUnique, WINDOW_PAGE, WINDOW_PAGES, mountWindow, remountShift, rulePage, stripRange,
  windowPageCount, windowPageOf, RANGE_CARD_MS, allLoadedLabel, rangeCardText, rangeOf, readPagesFor,
  splitRange,
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
    assert.match(lib, /pageQuery\(p, size \|\| sizeRef\.current \|\| perPage\)/);
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

describe("U3 new since over stacked pages: the rules", () => {
  const ids = (list) => list.map((x) => x.media_id);
  const mk = (...a) => a.map((m) => ({ media_id: String(m) }));

  test("a stacked list is the library's front page whatever page it has loaded down to", () => {
    const base = { advCount: 0, applied: "", media: "", shelf: "", similar: false, loaded: true };
    assert.equal(isFrontPage({ ...base, page: 4, continuous: true }), true);
    assert.equal(isFrontPage({ ...base, page: 4 }), false, "Pages: page 4 is not the front page");
    assert.equal(isFrontPage({ ...base, page: 1 }), true);
    assert.equal(isFrontPage({ ...base, page: 2, continuous: true, media: "video" }), false, "a filter is never the front page");
    assert.equal(isFrontPage({ ...base, page: 1, continuous: true, similar: true }), false);
  });

  test("what is new at the top is the run before the first picture already loaded", () => {
    const have = new Set(["5", "6", "7"]);
    assert.deepEqual(newestAbove(mk(9, 8, 5, 6), have), { fresh: mk(9, 8), met: true });
    assert.deepEqual(newestAbove(mk(5, 6), have), { fresh: [], met: true }, "nothing new");
    assert.deepEqual(newestAbove(mk(12, 11, 10), have), { fresh: mk(12, 11, 10), met: false }, "a whole page new: read on");
    assert.equal(PREPEND_MAX_PAGES, 5);
  });

  test("a pull prepends the new ones above everything loaded and keeps every page", () => {
    const old = mk(5, 6, 7, 8);
    assert.deepEqual(ids(prependUnique(mk(9, 8), old)), ["9", "5", "6", "7", "8"], "8 was already loaded: once, where it was");
    assert.equal(prependUnique([], old), old, "nothing new: the same list");
  });

  test("the rule stays with the marker picture: new ones prepended above it push it down, nothing else moves it", () => {
    const marker = { id: "5", ts: 0, at: 0 };
    const before = mk(5, 6, 7);
    assert.equal(newSince(before, marker).count, 0, "nothing new yet: no rule");
    const after = prependUnique(mk(9, 8), before);
    assert.equal(newSince(after, marker).count, 2, "the two prepended sit above the rule");
  });
});

describe("U3 new since over stacked pages: the wiring", () => {
  test("a pull in Continuous prepends through useLibrary and never replaces the stacked list", () => {
    const app = code("components/AppMobile.jsx");
    const pull = app.slice(app.indexOf("const refreshFromPull = useCallback("));
    const body = pull.slice(0, pull.indexOf("}, [userLoad]);"));
    assert.match(body, /if \(continuousRef\.current\) \{\s*await libNowRef\.current\.prependNewest\(\);/);
    assert.match(app, /isFrontPage\(\{[\s\S]{0,240}continuous,?\s/);
    const lib = code("hooks/useLibrary.js");
    assert.match(lib, /const prependNewest = useCallback\(/);
    assert.match(lib, /setItems\(\(old\) => prependUnique\(fresh, old\)\)/);
    assert.match(lib, /newestAbove\(/);
  });

  test("↑ Newest only scrolls: it never reloads or unloads", () => {
    const g = code("components/GalleryMobile.jsx");
    const fn = g.slice(g.indexOf("const toNewest = () => {"));
    const body = fn.slice(0, fn.indexOf("};") + 2);
    assert.match(body, /host\.scrollTo\(/);
    assert.doesNotMatch(body, /load|setItems|onLoadMore/);
  });
});

describe("U4 the mounted window: the rules", () => {
  test("a window page is 100 pictures and at most 5 are mounted", () => {
    assert.equal(WINDOW_PAGE, 100);
    assert.equal(WINDOW_PAGES, 5);
    assert.equal(windowPageCount(0), 0);
    assert.equal(windowPageCount(100), 1);
    assert.equal(windowPageCount(620), 7);
    assert.equal(windowPageOf(0), 0);
    assert.equal(windowPageOf(99), 0);
    assert.equal(windowPageOf(100), 1);
  });

  test("the window is centred on the page in view, held inside the list, never more than five", () => {
    assert.deepEqual(mountWindow(0, 7), { start: 0, end: 4 });
    assert.deepEqual(mountWindow(3, 7), { start: 1, end: 5 });
    assert.deepEqual(mountWindow(6, 7), { start: 2, end: 6 });
    assert.deepEqual(mountWindow(1, 3), { start: 0, end: 2 }, "a short list is all mounted");
    assert.deepEqual(mountWindow(9, 7), { start: 2, end: 6 }, "a stale centre is held inside the list");
    assert.deepEqual(mountWindow(0, 0), { start: 0, end: -1 });
    for (let c = 0; c < 40; c += 1) {
      const w = mountWindow(c, 40);
      assert.ok(w.end - w.start + 1 <= 5 && w.start <= c && c <= w.end, JSON.stringify([c, w]));
    }
  });

  test("the new-since rule belongs to the page its last new picture is on", () => {
    assert.equal(rulePage(0), -1, "no rule");
    assert.equal(rulePage(1), 0);
    assert.equal(rulePage(100), 0, "exactly a page new: the rule closes page 0");
    assert.equal(rulePage(101), 1);
  });

  test("a page wholly above the view that changes height moves the view by the difference, so nothing in view moves", () => {
    assert.equal(remountShift(9000, 9040, -3000, 0), 40, "above the view: follow it");
    assert.equal(remountShift(9000, 8990, -3000, 0), -10);
    assert.equal(remountShift(9000, 9040, 0, 0), 40, "its foot exactly at the top of the view is still above it");
    assert.equal(remountShift(9000, 9000, -3000, 0), 0, "an exact spacer: nothing moves");
  });

  test("a page the view is in, or one below it, is never corrected: growing at its foot moves nothing in view", () => {
    assert.equal(remountShift(5000, 10000, 400, 0), 0, "the next pictures appended into the page in view");
    assert.equal(remountShift(9000, 9040, 2000, 0), 0, "below the view");
  });

  test("the viewer's film strip is the window page the picture is on", () => {
    assert.deepEqual(stripRange(0, 620), { start: 0, end: 100 });
    assert.deepEqual(stripRange(250, 620), { start: 200, end: 300 });
    assert.deepEqual(stripRange(615, 620), { start: 600, end: 620 });
  });
});

describe("U4 the mounted window: the wiring", () => {
  test("Continuous draws the windowed list; Pages keeps the grid as shipped", () => {
    const g = code("components/GalleryMobile.jsx");
    assert.match(g, /continuous \? \(\s*<ContinuousGridMobile/);
    const c = code("components/ContinuousGridMobile.jsx");
    assert.match(c, /mountWindow\(/);
    assert.match(c, /className="glm-cpage-spacer"/);
    assert.match(c, /<GalleryGridMobile/, "each mounted page is the shipped grid");
    assert.match(c, /remountShift\(/);
  });

  test("the viewer crosses a page edge by id, asking for the next page when it must", () => {
    const lb = code("components/LightboxMobile.jsx");
    assert.match(lb, /if \(continuous\) \{/);
    assert.match(lb, /await loadMore\(\)/);
    assert.match(lb, /pendingFrom\.current = /);
    assert.match(lb, /items\.findIndex\(\(x\) => x\.media_id === want\.from\)/);
  });

  test("closing the viewer in Continuous brings its picture back into view, even from a dropped page", () => {
    const app = code("components/AppMobile.jsx");
    assert.match(app, /setReveal\(\{ mid: /);
    assert.match(app, /reveal=\{reveal\}/);
    const c = code("components/ContinuousGridMobile.jsx");
    assert.match(c, /reveal/);
  });
});

describe("U5 selection across pages: the rules", () => {
  test("a range is every place between the two tiles, inclusive, whichever was pressed first", () => {
    assert.deepEqual(rangeOf(7, 3), { lo: 3, hi: 7 });
    assert.deepEqual(rangeOf(3, 7), { lo: 3, hi: 7 });
    assert.deepEqual(rangeOf(5, 5), { lo: 5, hi: 5 });
  });

  test("which places of a range are loaded: the run the loaded list covers, by absolute index", () => {
    // Continuous: the list runs from the top, so a range between two tiles is all loaded
    assert.deepEqual(splitRange(10, 139, 0, 300), { n: 130, k: 0, from: 10, to: 139 });
    // Pages: ticked on page 1 (place 10), pressed on page 3 (places 200-299 are loaded)
    assert.deepEqual(splitRange(10, 250, 200, 100), { n: 241, k: 190, from: 200, to: 250 });
    // nothing of it loaded
    assert.deepEqual(splitRange(0, 49, 100, 100), { n: 50, k: 50, from: -1, to: -2 });
  });

  test("the card and the bar's words, formatted like the pager", () => {
    assert.equal(rangeCardText(140, 40), "Selected 140, including 40 not loaded yet.");
    assert.equal(rangeCardText(1400, 1000), "Selected 1,400, including 1,000 not loaded yet.");
    assert.equal(allLoadedLabel(300), "All loaded (300)");
    assert.equal(RANGE_CARD_MS, 4000);
  });

  test("the reads that cover the places not loaded, at the route's largest page", () => {
    assert.deepEqual(readPagesFor(10, 199, 200), [1]);
    assert.deepEqual(readPagesFor(10, 450, 200), [1, 2, 3]);
    assert.deepEqual(readPagesFor(400, 400, 200), [3]);
  });
});

describe("U5 selection across pages: the wiring", () => {
  test("in select mode a second long-press selects the range from the last ticked tile, by absolute index", () => {
    const g = code("components/GalleryMobile.jsx");
    assert.match(g, /const armSelect = \(mid\) => \{[\s\S]{0,400}if \(selectMode && anchor\.current/);
    assert.match(g, /splitRange\(/);
    assert.match(g, /rangeCardText\(/);
    assert.match(g, /RANGE_CARD_MS/);
    // what is not loaded is read (ids only) and added; Actions waits for it, so a confirm counts it all
    assert.match(g, /idsAt\(/);
    assert.match(g, /disabled=\{resolving > 0\}/);
  });

  test("Continuous's select bar offers All loaded (L); Pages keeps the shipped bar", () => {
    const g = code("components/GalleryMobile.jsx");
    assert.match(g, /continuous \? \(\s*<button type="button" className="glm-allloaded"/);
    assert.match(g, /allLoadedLabel\(items\.length\)/);
  });

  test("in Continuous a filter change clears the selection with a 10 s Undo", () => {
    const g = code("components/GalleryMobile.jsx");
    assert.match(g, /curation\.curate\.say\("The filter changed, so the selection was cleared\.", null, "", /);
    const cur = code("hooks/useCurate.js");
    assert.match(cur, /if \(t\.undoFn\) \{ dismiss\(\); t\.undoFn\(\); return; \}/);
    const toast = code("components/CurateToast.jsx");
    assert.match(toast, /toast\.prev \|\| toast\.undoFn/);
  });

  test("useLibrary reads the ids at absolute places without touching the list", () => {
    const lib = code("hooks/useLibrary.js");
    const fn = lib.slice(lib.indexOf("const idsAt = useCallback("));
    const body = fn.slice(0, fn.indexOf("}, ["));
    assert.match(body, /readPagesFor\(/);
    assert.doesNotMatch(body, /setItems|setTotal|setPage|setLoading|reqSeq/);
  });
});

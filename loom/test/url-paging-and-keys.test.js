import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// #31, "Where the Refit Broke" #7 -- two vanilla-parity losses the React refit dropped:
//   A. URL page addressing (?page=N): read on init, written on page change, re-read on
//      popstate, and NEVER thrown away by closeDetails() (it used to push a bare "/").
//   B. Grid arrow-key navigation: a focus ring the arrows move, Enter opens the lightbox,
//      Home/End, and Right/Left flipping pages at the edges -- gated off while any layer
//      is up, and never stealing keys from a text field.
// Source guards (like placard.test.js) + pure-logic tests for the URL builder.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");
const urlState = await import("../../gallery/src/gen/urlState.js");

describe("gen/urlState.js: the ONE URL builder (pure)", () => {
  const { buildUrl, readPage, readImage } = urlState;

  test("page 1 omits the param entirely; page N > 1 writes it", () => {
    assert.equal(buildUrl({ page: 1 }, ""), "/");
    assert.equal(buildUrl({ page: 3 }, ""), "/?page=3");
    assert.equal(buildUrl({ page: "7" }, ""), "/?page=7");
    // junk / 0 / negative all mean page 1
    assert.equal(buildUrl({ page: 0 }, ""), "/");
    assert.equal(buildUrl({ page: -2 }, ""), "/");
    assert.equal(buildUrl({ page: "abc" }, ""), "/");
    assert.equal(buildUrl({ page: null }, ""), "/");
  });
  test("page 3 + image keeps both; dropping one never drops the other", () => {
    const both = buildUrl({ page: 3, image: "m1" }, "");
    const p = new URLSearchParams(both.slice(both.indexOf("?")));
    assert.equal(p.get("page"), "3");
    assert.equal(p.get("image"), "m1");
    // open details from page 3: page preserved from the current search
    assert.equal(buildUrl({ image: "m2" }, "?page=3"), "/?page=3&image=m2");
    // close details (THE TRAP): page survives
    assert.equal(buildUrl({ image: null }, "?page=3&image=m2"), "/?page=3");
    assert.equal(buildUrl({ image: "" }, "?page=3&image=m2"), "/?page=3");
    // flip page while details are open: image survives
    assert.equal(buildUrl({ page: 4 }, "?page=3&image=m2"), "/?page=4&image=m2");
    // reset to page 1 while details are open: only the page param goes
    assert.equal(buildUrl({ page: 1 }, "?page=3&image=m2"), "/?image=m2");
  });
  test("an untouched key is left exactly as it was; a patch names only what it changes", () => {
    assert.equal(buildUrl({}, "?page=5&image=x"), "/?page=5&image=x");
    assert.equal(buildUrl(null, "?page=5"), "/?page=5");
    // an unrelated param rides along untouched
    assert.equal(buildUrl({ page: 2 }, "?foo=bar"), "/?foo=bar&page=2");
  });
  test("built from URLSearchParams, not string-concat: the image id is encoded", () => {
    const u = buildUrl({ image: "a b&c" }, "");
    assert.doesNotMatch(u, /a b&c/);
    assert.equal(new URLSearchParams(u.slice(1)).get("image"), "a b&c");
  });
  // The literal used to be "/next" -- the gallery's pilot-era second path, retired
  // with the codename (issue #51). The PROPERTY under test is unchanged: whatever
  // pathname the caller hands in comes back out. The app only ever hands it "/".
  test("pathname is preserved when given, defaults to /", () => {
    assert.equal(buildUrl({ page: 2 }, "", "/sub"), "/sub?page=2");
    assert.equal(buildUrl({ page: 1 }, "", "/sub"), "/sub");
    assert.equal(buildUrl({ page: 2 }, "", ""), "/?page=2");
  });
  test("readPage: integer >= 1, else 1", () => {
    assert.equal(readPage("?page=3"), 3);
    assert.equal(readPage("?page=3&image=x"), 3);
    assert.equal(readPage(""), 1);
    assert.equal(readPage("?page=0"), 1);
    assert.equal(readPage("?page=-4"), 1);
    assert.equal(readPage("?page=abc"), 1);
    assert.equal(readPage("?page=2.9"), 2);
    assert.equal(readPage(undefined), 1);
  });
  test("readImage: the id or null", () => {
    assert.equal(readImage("?image=m9"), "m9");
    assert.equal(readImage("?page=2"), null);
    assert.equal(readImage(""), null);
  });
});

describe("A. URL page addressing (App.jsx)", () => {
  const app = src("gallery/src/App.jsx");
  const lib = src("gallery/src/hooks/useLibrary.js");

  test("(a) init reads ?page= and the hook's mount load honors it", () => {
    assert.match(app, /import \{ buildUrl, readPage, readImage, readSeries \} from "\.\/gen\/urlState\.js";/);
    assert.match(app, /const \[initialPage\] = useState\(\(\) => readPage\(window\.location\.search\)\);/);
    // #34 direction B: the hook also takes the persisted `group` toggle (default off)
    assert.match(app, /useLibrary\(\{ initialPage, group \}\)/);
    // the hook: the mount load takes initialPage; later filter changes still reset to 1
    assert.match(lib, /export default function useLibrary\(\{ initialPage = 1, group = "" \} = \{\}\)/);
    assert.match(lib, /load\(first \? Math\.max\(1, initialPage \| 0\) : 1, true\);/);
    assert.doesNotMatch(lib, /useEffect\(\(\) => \{ load\(1, true\); \}, \[load\]\);/);
  });
  test("(b) ONE URL helper, and closeDetails uses it -- the bare pushState('/') is GONE", () => {
    assert.doesNotMatch(app, /pushState\(\{\}, "", "\/"\)/);
    assert.doesNotMatch(app, /"\/\?image="/);
    // exactly one place builds an address, and it is the shared helper
    assert.equal((app.match(/buildUrl\(/g) || []).length, 1);
    assert.match(app, /const setUrl = useCallback\(\(patch, replace\) => \{/);
    assert.match(app, /buildUrl\(patch, window\.location\.search, window\.location\.pathname\)/);
    // every history write in App goes through setUrl
    const writes = app.match(/history\.(pushState|replaceState)\(/g) || [];
    const helper = app.slice(app.indexOf("const setUrl = useCallback"), app.indexOf("const openDetails ="));
    const inHelper = helper.match(/history\.(pushState|replaceState)\(/g) || [];
    // the only write outside the helper is the pre-existing #hash strip (replaceState of path+search)
    assert.equal(writes.length - inHelper.length, 1);
    assert.match(app, /window\.history\.replaceState\(null, "", window\.location\.pathname \+ window\.location\.search\);/);
    // closeDetails: drop image only, keep the page
    // openDetails/closeDetails/goToPage are useCallback'd since 2026-09-04 (they are props
    // on the memoized <Grid>); what these slices pin -- which keys each one patches -- is
    // unchanged.
    const close = app.slice(app.indexOf("const closeDetails = useCallback(() => {"), app.indexOf("const pageRef"));
    assert.match(close, /setUrl\(\{ image: null \}\)/);
    assert.doesNotMatch(close, /setUrl\(\{ page/);
    // openDetails: patch the image, keep the page
    const open = app.slice(app.indexOf("const openDetails = useCallback((mid) => {"), app.indexOf("const closeDetails"));
    assert.match(open, /setUrl\(\{ image: mid \}\)/);
  });
  test("goToPage pushes ?page=N through the helper, then loads", () => {
    const goAt = app.indexOf("const goToPage = useCallback((p) => {");
    const go = app.slice(goAt, app.indexOf("}, [", goAt));
    assert.match(go, /setUrl\(\{ page: p \}\);/);
    assert.match(go, /load\(p, true\);/);
    assert.match(app, /goToPage=\{goToPage\}/);
    assert.doesNotMatch(app, /goToPage=\{\(p\) => load\(p, true\)\}/);
  });
  test("(c) the popstate handler re-reads page (and image) and loads a changed page", () => {
    const i = app.indexOf("const onPop = () => {");
    assert.ok(i > 0);
    const pop = app.slice(i, app.indexOf('window.addEventListener("popstate", onPop);', i));
    assert.match(pop, /setDetailsFor\(readImage\(window\.location\.search\)\);/);
    assert.match(pop, /const p = readPage\(window\.location\.search\);/);
    assert.match(pop, /if \(p !== pageRef\.current\) loadRef\.current\(p, true\);/);
  });
  test("filter/search/sort resets keep the URL honest: the settled page is mirrored with replaceState", () => {
    const i = app.indexOf("if (loading || total == null) return;");
    assert.ok(i > 0, "the mirror waits for the first load to land");
    const eff = app.slice(app.lastIndexOf("useEffect(() => {", i), app.indexOf("}, [page, loading, total, setUrl]);", i));
    assert.match(eff, /setUrl\(\{ page \}, true\);/);
  });
});

describe("B. Grid arrow-key navigation (Grid.jsx)", () => {
  const grid = src("gallery/src/components/Grid.jsx");
  const css = src("gallery/src/styles/grid.css");
  const start = grid.indexOf('window.addEventListener("keydown", onKey);');
  assert.ok(start > 0, "a window keydown listener exists");
  const handler = grid.slice(grid.indexOf("const onKey = (e) => {", grid.indexOf("const pendingFocus")), start);

  test("(d) one keydown handler covers ArrowLeft/Right/Up/Down, Enter, Home, End", () => {
    assert.match(grid, /const NAV_KEYS = \["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "Enter"\];/);
    for (const k of ["ArrowLeft", "ArrowRight", "ArrowDown", "Home", "End", "Enter"]) {
      assert.match(handler, new RegExp('k === "' + k + '"'), k + " handled");
    }
    // Up is the other branch of the Down test
    assert.match(handler, /const dir = k === "ArrowDown" \? 1 : -1;/);
    // Left/Right by one; Home/End to the ends; Enter opens the lightbox on the focused card
    assert.match(handler, /if \(cur > 0\) next = cur - 1;/);
    assert.match(handler, /if \(cur < last\) next = cur \+ 1;/);
    assert.match(handler, /else if \(k === "Home"\) next = 0;/);
    assert.match(handler, /else if \(k === "End"\) next = last;/);
    // Enter opens the lightbox on a focused singleton -- or the stack's own view when
    // the focused card is a stack (#34 direction B: a stack navigates, never lightboxes).
    assert.match(handler, /if \(stackKind\(itCur\)\) openStackFor\(itCur\);/);
    assert.match(handler, /else openLightbox\(origIndexByMid\.get\(itCur\.media_id\)\);/);
    // Up/Down from the rendered layout: rects first, the first row's card count as the fallback
    assert.match(grid, /const verticalNeighbor = \(root, el, dir\) => \{/);
    assert.match(grid, /getBoundingClientRect\(\)/);
    assert.match(grid, /const colsOnScreen = \(root\) => \{/);
    assert.match(handler, /next = verticalNeighbor\(root, card, dir\);/);
  });
  test("cross-page: Right on the last card -> next page (focus first); Left on the first -> previous (focus last)", () => {
    assert.match(handler, /else if \(page < pages\) \{ pendingFocus\.current = "first"; go\(page \+ 1\); \}/);
    assert.match(handler, /else if \(page > 1\) \{ pendingFocus\.current = "last"; go\(page - 1\); \}/);
    // the landing happens once the new page's cells render
    assert.match(grid, /focusCard\(want === "last" \? cells\.length - 1 : 0\);/);
  });
  test("(e) keys are gated on the overlay-open prop, and never stolen from a text field or a chord", () => {
    assert.match(grid, /keysEnabled = true,/);
    assert.match(grid, /if \(!keysEnabled\) return undefined;/);
    assert.match(handler, /e\.altKey \|\| e\.ctrlKey \|\| e\.metaKey/);
    assert.match(handler, /t\.closest\("input, textarea, select, \[contenteditable=''\], \[contenteditable='true'\]"\)/);
    // App computes the gate from every layer that owns the keys
    const app = src("gallery/src/App.jsx");
    assert.match(app, /keysEnabled=\{gridKeys\}/);
    const gate = app.slice(app.indexOf("const gridKeys ="), app.indexOf(";", app.indexOf("const gridKeys =")));
    for (const flag of ["lbIndex == null", "!detailsFor", "!overlay", "!ctxMenu", "!similarFor", "!dockActive", "!claimModal.open"]) {
      assert.ok(gate.includes(flag), "gate includes " + flag);
    }
    // App now hands Grid the real openDetails, so the Details chip keeps ?page= too
    assert.match(app, /onOpenDetails=\{openDetails\}/);
  });
  test("(f) cards have tabIndex, and the ring is :focus-visible-only in the accent", () => {
    const fig = grid.slice(grid.indexOf("<figure"), grid.indexOf("className=", grid.indexOf("<figure")));
    assert.match(fig, /tabIndex=\{0\}/);
    assert.match(css, /\.mgg-card:focus-visible \{\s*outline: 2px solid var\(--lavender, var\(--accent\)\);\s*outline-offset: 2px;\s*\}/);
    assert.match(css, /\.mgg-card:focus \{ outline: none; \}/);
  });
  test("the Grid's own fallback bridge rides the same builder (no bare '/?image=' anywhere)", () => {
    assert.doesNotMatch(grid, /"\/\?image="/);
    assert.match(grid, /buildUrl\(\{ image: mid \}, window\.location\.search, window\.location\.pathname\)/);
  });
});

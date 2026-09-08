/* Load-more must fire whichever ancestor scrolls (owner, 2026-09-07, desktop AND phone: every
   list stopped dead at its first page). The grid's own onScroll only fires when .mg-grid is the
   scroller, and on the phone sheet and the desktop dock palette it is not -- the wrapper
   `.mfly > div:not(.mfly-head)` is. So the picker watches a 1px sentinel after the grid with an
   IntersectionObserver, which sees it through any clipping ancestor. */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(here, "../../gallery/src/components/ModelPicker.jsx"), "utf8");
const css = readFileSync(path.join(here, "../../gallery/src/styles/model-picker.css"), "utf8");

describe("load-more watches a sentinel, not the grid's own scroll", () => {
  test("a sentinel element sits after the grid and before the loading line", () => {
    const i = src.indexOf('className="mg-grid"'), j = src.indexOf('className="mg-sentinel"'), k = src.indexOf('className={"mg-loadmore"');
    assert.ok(i > 0 && j > i && k > j, "order must be grid, sentinel, loading line");
    assert.match(src, /ref=\{sentinelRef\} className="mg-sentinel"/);
    assert.match(css, /\.model-picker \.mg-sentinel\{height:1px;flex:none;\}/);
  });
  test("an IntersectionObserver on the sentinel calls loadMore, rooted on the pane that scrolls with a page of head start", () => {
    assert.match(src, /new IntersectionObserver\(\(entries\) => \{\s*if \(entries\.some\(\(e\) => e\.isIntersecting\)\) loadMore\(\);/);
    // root = the scrolling ancestor (picker/mergeRows.js scrollParentOf), NOT null: with the
    // viewport as root the pane's clip wins and the margin buys nothing, so every page waited a
    // full server round trip at the bottom of the list ("it does but its slow", owner 2026-09-07).
    assert.match(src, /\{ root: scrollParentOf\(el\), rootMargin: "720px 0px", threshold: 0 \}/);
    assert.match(src, /import \{ uniqueRows, appendRows, scrollParentOf, rowKey \} from "\.\.\/picker\/mergeRows\.js";/);
    assert.match(src, /io\.observe\(el\);\s*return \(\) => io\.disconnect\(\);/);
    // re-armed whenever the list grows, so the sentinel is re-observed below the new rows
    assert.match(src, /\}, \[visible, loadMore, rows\.length\]\);/);
  });
  test("the grid's own onScroll stays as the second road", () => {
    assert.match(src, /<div className="mg-grid" role="listbox" ref=\{gridRef\} onScroll=\{onScroll\}/);
  });
  test("a touch screen never opens the hover preview (a tap fires mouseenter and nothing fires mouseleave)", () => {
    assert.match(src, /const schedulePreview = \(m, anchorEl\) => \{\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*if \(typeof window !== "undefined" && window\.matchMedia && window\.matchMedia\("\(hover: none\)"\)\.matches\) return;/);
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner report 2026-07-24: "It scrolls about 4 extra rows and then stops on both
// model/lora -- no continuous scroll." Root cause was server-side (see
// tests/test_model_grid.py's cursor-pagination tests and tests/test_web_pick.py's
// threads_cursor test): has_more had been computed correctly the whole time, nothing
// client-side ever read it or asked for a next page. mg-model-picker.js has no
// jsdom/React harness in this runner -- source-presence assertions are the established
// pattern here (see mg-model-picker-multi-select.test.js, mg-model-picker-preview-
// debounce.test.js); real scroll/fetch interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");

describe("Continuous scroll / load-more (owner report 2026-07-24)", () => {
  test("pagination state is initialized and reset on every fresh search", () => {
    assert.match(src, /this\._cursor = '';\s*\n\s*this\._hasMore = false;\s*\n\s*this\._loadingMore = false;/,
      "pagination state must exist on the element");
    assert.match(src, /this\._cursor = ''; this\._hasMore = false;.*a fresh search is a new list/,
      "_search() must reset cursor/hasMore -- a NEW query is a new list, not a continuation " +
      "of whatever the previous search's pagination state was");
  });

  test("_search() and _loadMore() share ONE url-builder, so a continuation can never silently use different filters", () => {
    assert.match(src, /_searchUrl\(cursor\)\s*\{/);
    assert.match(src, /fetch\(this\._searchUrl\(\)\)/, "_search() must call the shared builder with no cursor");
    assert.match(src, /fetch\(this\._searchUrl\(this\._cursor\)\)/, "_loadMore() must call the shared builder WITH the current cursor");
    assert.match(src, /if \(cursor\) u \+= '&cursor=' \+ encodeURIComponent\(cursor\);/);
  });

  test("_search() captures has_more/next_cursor from the response", () => {
    assert.match(src, /self\._hasMore = !!\(d && d\.has_more\);\s*\n\s*self\._cursor = \(d && d\.next_cursor\) \|\| '';\s*\n\s*self\._render\(\(d && d\.results\) \|\| \[\], d && d\.error, false\);/);
  });

  test("_loadMore() is guarded against firing with no more results or while already loading", () => {
    assert.match(src, /_loadMore\(\)\s*\{\s*\n\s*if \(!this\._hasMore \|\| this\._loadingMore\) return;/,
      "must refuse to fetch when the server already said there's nothing more, or a fetch " +
      "is already in flight (a fast scroll re-firing the listener many times in a row)");
  });

  test("_loadMore() APPENDS results and never clears the grid or the empty-state message", () => {
    assert.match(src, /self\._render\(\(d && d\.results\) \|\| \[\], null, true\);/,
      "must call _render with append=true");
    assert.match(src, /_render\(rows, err, append\) \{\s*\n\s*var g = this\._grid, e = this\._empty, self = this;\s*\n\s*if \(!append\) g\.innerHTML = '';/,
      "the grid must only be cleared on a FRESH search (append=false), never on a continuation " +
      "-- clearing it on append would defeat the entire feature, wiping what's already loaded");
    assert.match(src, /if \(!append && !rows\.length\) \{ e\.textContent = 'No results/,
      "an appended page's rows are additive -- an empty continuation page must not overwrite " +
      "the empty-state message onto a grid that already has real results in it");
  });

  test("a transient error or network failure during load-more does not permanently kill pagination", () => {
    // Both paths must leave _hasMore/_cursor untouched (not force-false) so the NEXT scroll
    // near the bottom simply retries -- one flaky response must not silently wedge the grid
    // into "no more results" forever with nothing visibly wrong on screen.
    assert.match(src, /if \(d && d\.error\) return;\s*\n\s*self\._hasMore = !!\(d && d\.has_more\);/,
      "a server-side {error:...} response must bail out BEFORE touching _hasMore/_cursor");
    assert.match(src, /\}\)\.catch\(function \(\) \{\s*\n\s*self\._loadingMore = false;\s*\n\s*if \(self\._loadmore\) self\._loadmore\.classList\.remove\('on'\);\s*\n\s*\/\/ A failed load-more leaves _hasMore as it was/,
      "a network failure must also leave pagination state untouched, same reasoning");
  });

  test("_loadMore() uses the same staleness guard as _search() -- a fresh search supersedes an in-flight continuation", () => {
    assert.match(src, /var mine = this\._seq, self = this;\s*\n\s*this\._loadingMore = true;/,
      "captures the CURRENT seq (does not increment it -- only a real new _search() does " +
      "that) so a _search() started while this load-more is in flight correctly invalidates it");
    assert.match(src, /if \(mine !== self\._seq\) return;   \/\/ a fresh search superseded this continuation/);
  });

  test("a scroll listener near the bottom of the grid triggers _loadMore(), with no separate debounce needed", () => {
    assert.match(src,
      /this\._grid\.addEventListener\('scroll', function \(\) \{\s*\n\s*var g = self\._grid;\s*\n\s*if \(g\.scrollHeight - g\.scrollTop - g\.clientHeight < 150\) self\._loadMore\(\);/,
      "_loadMore()'s own _hasMore/_loadingMore guards make a separate scroll-event debounce " +
      "unnecessary -- a fast scroll re-checking cheap arithmetic many times is fine, only " +
      "one fetch is ever actually allowed through");
  });

  test("a loading-more indicator toggles visibly during the fetch, not silently in the background", () => {
    assert.match(src, /'<div class="mg-loadmore" aria-hidden="true">loading more…<\/div>'/);
    assert.match(src, /if \(this\._loadmore\) this\._loadmore\.classList\.add\('on'\);/);
    assert.match(src, /mg-loadmore\.on\{display:block;\}/);
  });
});

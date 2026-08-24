import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner report 2026-07-24: "It scrolls about 4 extra rows and then stops on both
// model/lora -- no continuous scroll." Root cause was server-side (see
// tests/test_model_grid.py's cursor-pagination tests and tests/test_web_pick.py's
// threads_cursor test): has_more had been computed correctly the whole time, nothing
// client-side ever read it or asked for a next page.
//
// The <mg-model-picker> custom element was ported to a React component
// (gallery/src/components/ModelPicker.jsx) + gallery/src/styles/model-picker.css, and the
// vanilla file was deleted. The continuous-scroll pagination survives verbatim -- a port,
// not a redesign -- so these source-presence assertions (the established pattern here, no
// jsdom/React harness in this runner; see mg-model-picker-preview-debounce.test.js) were
// retargeted to the React source. The vanilla -> React mapping used below:
//   this._cursor/_hasMore/_loadingMore  -> cursorRef/hasMoreRef/loadingMoreRef (useRef)
//   this._seq                           -> seqRef.current
//   _searchUrl(cursor)                  -> const searchUrl = useCallback((cursor) => ...)
//   _search()                           -> const doSearch = useCallback(...)  (setRows replaces)
//   _loadMore()                         -> const loadMore = useCallback(...)  (setRows concats)
//   _render(rows,err,append) grid clear -> replace-vs-concat on setRows (no innerHTML dance)
//   the .mg-grid scroll addEventListener -> const onScroll + <div ... onScroll={onScroll}>
//   connectedCallback display:none gate -> the `visible` prop + the browse-on-open useEffect
//   ensureSearched()/_searched/_stale   -> lastKeyRef guard (unchanged key => no refetch)
// Real scroll/fetch interaction verification still needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8");
const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/model-picker.css"), "utf8");

describe("Continuous scroll / load-more (owner report 2026-07-24)", () => {
  test("pagination state is initialized and reset on every fresh search", () => {
    assert.match(src, /const cursorRef = useRef\(""\);\s*\n\s*const hasMoreRef = useRef\(false\);\s*\n\s*const loadingMoreRef = useRef\(false\);/,
      "pagination state must exist as refs on the component (mutated synchronously, not " +
      "React state -- a stale closure would let a re-fired scroll double-fetch)");
    assert.match(src, /const doSearch = useCallback\(\(\) => \{\s*\n\s*const mine = \+\+seqRef\.current;\s*\n\s*cursorRef\.current = ""; hasMoreRef\.current = false;/,
      "doSearch() must reset cursor/hasMore -- a NEW query is a new list, not a continuation " +
      "of whatever the previous search's pagination state was");
  });

  test("doSearch() and loadMore() share ONE url-builder, so a continuation can never silently use different filters", () => {
    assert.match(src, /const searchUrl = useCallback\(\(cursor\) => \{/);
    // Re-anchored 2026-08-23: both reads ride api.js's apiGet. The property under test is
    // unchanged -- ONE builder feeds both calls, so a continuation cannot drift from its search.
    assert.match(src, /apiGet\(searchUrl\(\)\)/, "doSearch() must call the shared builder with no cursor");
    assert.match(src, /apiGet\(searchUrl\(cursorRef\.current\)\)/, "loadMore() must call the shared builder WITH the current cursor");
    assert.match(src, /if \(cursor\) u \+= "&cursor=" \+ encodeURIComponent\(cursor\);/);
  });

  test("doSearch() captures has_more/next_cursor from the response", () => {
    assert.match(src, /hasMoreRef\.current = !!\(d && d\.has_more\);\s*\n\s*cursorRef\.current = \(d && d\.next_cursor\) \|\| "";\s*\n\s*setErr\(d && d\.error \? d\.error : ""\);\s*\n\s*setRows\(\(d && d\.results\) \|\| \[\]\);/);
  });

  test("loadMore() is guarded against firing with no more results or while already loading", () => {
    assert.match(src, /const loadMore = useCallback\(\(\) => \{\s*\n\s*if \(!hasMoreRef\.current \|\| loadingMoreRef\.current\) return;/,
      "must refuse to fetch when the server already said there's nothing more, or a fetch " +
      "is already in flight (a fast scroll re-firing the handler many times in a row)");
  });

  test("loadMore() APPENDS results and never clears the grid or the empty-state message", () => {
    assert.match(src, /setRows\(\(old\) => old\.concat\(\(d && d\.results\) \|\| \[\]\)\);/,
      "the continuation must CONCAT onto the existing rows, not replace them");
    assert.match(src, /setRows\(\(d && d\.results\) \|\| \[\]\);/,
      "a FRESH search (doSearch) replaces the row list outright -- the replace-vs-concat split " +
      "is what the vanilla `if (!append) g.innerHTML = ''` used to do; clearing on a continuation " +
      "would defeat the entire feature, wiping what's already loaded");
    assert.match(src, /!rows\.length \? <div className="mg-empty"[^\n]*>No results/,
      "the 'No results' empty-state is gated on !rows.length -- because loadMore concats onto " +
      "the existing rows, an empty continuation page can never blank a grid that already holds " +
      "real results (the additive-continuation contract)");
  });

  test("a transient error or network failure during load-more does not permanently kill pagination", () => {
    // Both paths must leave hasMore/cursor untouched (not force-false) so the NEXT scroll
    // near the bottom simply retries -- one flaky response must not silently wedge the grid
    // into "no more results" forever with nothing visibly wrong on screen.
    assert.match(src, /if \(d && d\.error\) return;[^\n]*\n\s*hasMoreRef\.current = !!\(d && d\.has_more\);/,
      "a server-side {error:...} response must bail out BEFORE touching hasMore/cursor");
    assert.match(src, /\}\)\.catch\(\(\) => \{ loadingMoreRef\.current = false; setLoadingMore\(false\); \}\);/,
      "a network failure must ONLY reset the loading flags -- it must not touch hasMore/cursor, " +
      "so the next scroll near the bottom simply retries (same reasoning as the error bail)");
  });

  test("loadMore() uses the same staleness guard as doSearch() -- a fresh search supersedes an in-flight continuation", () => {
    assert.match(src, /const mine = seqRef\.current;\s*\n\s*loadingMoreRef\.current = true; setLoadingMore\(true\);/,
      "captures the CURRENT seq (does NOT increment it -- only a real new doSearch() does " +
      "that, via ++seqRef.current) so a doSearch() started while this load-more is in flight " +
      "correctly invalidates it");
    assert.match(src, /if \(mine !== seqRef\.current\) return;\s+\/\/ a fresh search superseded this continuation/);
  });

  test("a scroll handler near the bottom of the grid triggers loadMore(), throttled to one check per animation frame", () => {
    // Owner report 2026-07-24: "still slow and a bit choppy". The FIRST version of this
    // listener ran its scrollHeight/scrollTop/clientHeight layout read on every single
    // scroll event, unthrottled -- with the DOM now growing on every load-more, that's a
    // synchronous layout recalculation on an ever-larger tree, many times per frame during
    // a fast scroll. requestAnimationFrame collapses any number of events within one frame
    // down to a single check, right before the browser paints anyway.
    assert.match(src, /const scrollRafRef = useRef\(null\);/);
    assert.match(src,
      /const onScroll = \(\) => \{\s*\n\s*if \(scrollRafRef\.current\) return;\s*\n\s*scrollRafRef\.current = requestAnimationFrame\(\(\) => \{\s*\n\s*scrollRafRef\.current = null;\s*\n\s*const g = gridRef\.current;\s*\n\s*if \(g && g\.scrollHeight - g\.scrollTop - g\.clientHeight < 150\) loadMore\(\);/,
      "the layout read + loadMore() check must be deferred to a single rAF callback, " +
      "with a second scroll event during the same pending frame doing nothing at all " +
      "(scrollRafRef already set) rather than queuing a second frame");
    assert.match(src, /<div className="mg-grid"[^\n]*onScroll=\{onScroll\}/,
      "the grid must actually be wired to the throttled handler (React's onScroll prop " +
      "replaces the element's addEventListener('scroll', ...))");
  });

  test("a loading-more indicator toggles visibly during the fetch, not silently in the background", () => {
    assert.match(src, /<div className=\{"mg-loadmore" \+ \(loadingMore \? " on" : ""\)\} aria-hidden="true">loading more…<\/div>/,
      "the indicator's `on` class must be driven by the loadingMore state");
    assert.match(src, /loadingMoreRef\.current = true; setLoadingMore\(true\);/,
      "entering the fetch must flip loadingMore true so the indicator shows");
    assert.match(css, /\.mg-loadmore\.on\{display:block;\}/,
      "and the ported CSS must still reveal it on the `on` class");
  });

  test("the browse-on-open search is deferred while the instance is not `visible`", () => {
    // Owner report 2026-07-24 ("still slow"): both the Gallery and the Loom mount a
    // kind="base" AND a kind="lora" picker TOGETHER on first flyout open, with only one
    // actually visible -- searching the hidden one anyway meant every open fired two full
    // searches competing for the same connection, for a tab nobody had asked to see. The
    // vanilla element gated its browse-on-open on style.display !== 'none'; the React port
    // gates the same search on the `visible` prop inside the browse-on-open effect.
    assert.match(src, /useEffect\(\(\) => \{\s*\n\s*if \(!visible\) return;\s*\n\s*const key = searchUrl\(\);\s*\n\s*if \(key === lastKeyRef\.current\) return;\s*\n\s*lastKeyRef\.current = key;\s*\n\s*doSearch\(\);/,
      "the browse-on-open (and re-search-on-filter-change) effect must early-return when " +
      "!visible, so a hidden instance never fires a competing search");
  });

  test("re-revealing an already-searched instance is a no-op -- each keeps its own last search (the ensureSearched idempotency contract)", () => {
    // The vanilla ensureSearched() was idempotent: once searched, switching tabs back and
    // forth must never re-fetch, matching the "each keeps its OWN last-searched results
    // independently" contract. The React port folds that into the browse-on-open effect:
    // the fresh-list url is the search KEY, and an unchanged key on re-reveal is skipped.
    // The _stale escape hatch (a base-type change while hidden) is inherent -- baseType is
    // part of the key, so a changed base re-searches once on reveal.
    assert.match(src, /const key = searchUrl\(\);\s*\n\s*if \(key === lastKeyRef\.current\) return;/,
      "must skip the fetch when the fresh-list search key is unchanged since the last search " +
      "-- a plain re-reveal must not re-fetch, only a genuine query/filter/baseType change");
  });
});

// AUDIT_2026-07-21 follow-up (vanilla): picking a base model sets base-type on the (still
// hidden) LoRA picker, which searched unconditionally -- opening the LoRA tab afterwards
// fired the IDENTICAL request a second time. In the React port the same class of redundant
// request is closed by the single search site (the effect) plus the key guard.
describe("No redundant LoRA search when a base model is picked (AUDIT_2026-07-21)", () => {
  test("the search effect owns the last-searched marker, so ANY search counts as searched", () => {
    assert.match(src, /lastKeyRef\.current = key;\s*\n\s*doSearch\(\);/,
      "lastKeyRef (the vanilla _searched/_stale equivalent) must be set at the ONE search " +
      "site, immediately before doSearch() -- not at scattered call sites that happen to " +
      "know about it. A base-type-triggered search that left the marker stale is exactly " +
      "what made the next reveal re-run the same request in the vanilla bug");
  });

  test("baseType is threaded into the search key, so a base-type change while hidden defers to the next reveal", () => {
    assert.match(src, /if \(kind === "lora" && baseType\) u \+= "&base_type=" \+ encodeURIComponent\(baseType\);/,
      "baseType must be part of the fresh-list url (the search key)");
    assert.match(src, /if \(!visible\) return;/,
      "while hidden the effect early-returns, so a base-type change does NOT search then; " +
      "because baseType is in the key, the next reveal re-searches once with it already in place");
    assert.match(src, /\}, \[kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType\]\);/,
      "searchUrl must depend on baseType, or the key would not recompute when the base changes");
  });

  test("a base-type change on a VISIBLE instance still re-searches immediately", () => {
    // The original picker-parity-round2 behavior must survive: switching the selected base
    // while actually looking at the LoRA grid re-sorts/re-badges it on the spot. In React
    // that falls out of searchUrl being an effect dependency: baseType change -> new
    // searchUrl -> new key -> (visible) -> doSearch fires.
    assert.match(src, /\}, \[visible, searchUrl, doSearch\]\);/,
      "the browse-on-open effect must depend on searchUrl (and visible), so a visible " +
      "instance re-runs the moment any filter -- including baseType -- changes the key");
  });

  test("lastKeyRef is initialized to null so it is never undefined on a first reveal", () => {
    assert.match(src, /const lastKeyRef = useRef\(null\);/,
      "the last-searched marker (vanilla's _searched/_stale, both initialized) must start " +
      "null, so the first reveal's real key !== null and the first search always fires");
  });
});

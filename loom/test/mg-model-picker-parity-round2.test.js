import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// picker-parity-round2 (2026-07-24): two follow-ups the owner found live-testing the O12/O13
// migration, both fixed in static/mg-model-picker.js.
//
// Problem 1 (layout): the Gallery's #model-flyout showed only ~2 rows of cards then a large
// dead area -- .mg-grid had a fixed max-height:320px independent of the host panel's real
// (much taller) available height. Fixed by making the element a flex column whose .mg-grid
// is flex:1 (fills whatever room a constraining host hands down; sizes to content exactly
// like display:block used to when no host constrains it -- see mg-model-picker.js's own
// header comment for the full reasoning).
//
// Problem 3 (LoRA architecture filtering): a `base-type` opt-in attribute threads the
// selected base model's model_type into /api/model-search as base_type=, and the component
// renders the server's `compat` tag (moonglade_backup.py's annotate_lora_compat) against
// the row. Badge shape changed 2026-08-02 (DC conformance pass): only a CONFIRMED
// incompatible row ('no') is flagged now -- warning badge, dimmed cover, blocked new
// pick -- 'yes' and 'unknown' both render fully live with no badge at all.
//
// static/mg-model-picker.js is a plain global script with no jsdom harness in this runner --
// source-presence assertions are the established pattern here (see
// mg-model-picker-market.test.js, mg-model-picker-multi-select.test.js). Live visual
// verification (the grid actually filling/scrolling, the badge actually rendering) needs a
// real browser -- see the CHANGELOG / audit doc for that evidence.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");
// The actual injected CSS array only -- the file's header comment legitimately explains the
// history ("used to be a fixed max-height:320px") in prose, which must not trip a check for
// the RULE itself being gone. Isolate the CSS the browser actually receives.
const cssBlockMatch = src.match(/var MG_CSS = \[([\s\S]*?)\]\.join\(''\);/);
assert.ok(cssBlockMatch, "could not locate the MG_CSS array literal -- has it moved or been renamed?");
// Strip JS /* */ comments (this array has several, explaining the picker-parity-round2
// history) -- only the quoted string CONTENT actually reaches the page as real CSS.
const cssBlock = cssBlockMatch[1].replace(/\/\*[\s\S]*?\*\//g, "");

describe("Problem 1: .mg-grid fills its host's real height instead of a fixed 320px cap", () => {
  test("the element's own default display is a flex column, not block", () => {
    assert.match(src, /'mg-model-picker\{display:flex;flex-direction:column;min-height:0;/,
      "must be a flex column so a host that constrains this element's height can hand real " +
      "room down to .mg-grid via flex:1 -- display:block had no such mechanism");
  });

  test("the old fixed max-height:320px on .mg-grid is GONE from the actual CSS rule", () => {
    assert.doesNotMatch(cssBlock, /max-height:320px/,
      "a fixed max-height independent of the host's real available height is exactly the " +
      "owner's reported bug (grid capped at 320px, dead space below it in a taller panel)");
  });

  test(".mg-grid is a flex item that grows to fill available space and keeps its own scroll", () => {
    // Column template updated 2026-08-02 (DC conformance: fixed 1fr-1fr -> the DC's own
    // auto-fill/minmax card grid, drift item 18's same masonry philosophy applied to a
    // fixed-size card grid); the .12s transition timing was already stale before that,
    // superseded by the app-wide .18s motion-vocab pass. The FLEX/SCROLL mechanics this
    // test protects (flex:1 1 auto, min-height, overflow:auto) are unchanged.
    assert.match(src, /'mg-model-picker \.mg-grid\{display:grid;grid-template-columns:repeat\(auto-fill,minmax\(124px,1fr\)\);grid-auto-rows:min-content;',\s*\n\s*' gap:11px;align-content:start;margin-top:8px;',\s*\n\s*' flex:1 1 auto;min-height:140px;overflow:auto;transition:opacity \.18s cubic-bezier\(\.2,\.9,\.24,1\);\}',/,
      "the grid must flex-grow to fill the host's real height and remain the one scrolling " +
      "region -- not a second independent scroll container fighting the host's own overflow");
  });

  test(".mg-grid forces auto rows to size off content, not stretch to fill a definite container height", () => {
    assert.match(src, /grid-auto-rows:min-content/,
      "found live 2026-07-24: .mg-card has overflow:hidden, which per spec makes its " +
      "automatic minimum size 0 -- with a definite grid height (from the flex:1 1 auto " +
      "fix above) and default grid-auto-rows:auto, every implicit row track stretched to " +
      "divide the container's fixed height evenly instead of sizing to content, squishing " +
      "every card to a sliver and making scrollHeight never exceed clientHeight either " +
      "(the reported 'no longer scrollable' was the SAME bug, not a second one)");
  });

  test("the search input / market UI / empty message stay their natural size (flex:none), only the grid grows", () => {
    // The declared style is a JS array of string fragments joined at runtime (some rules
    // span two fragments) -- match loosely across that boundary rather than assuming each
    // selector's whole declaration lives in one JS string literal.
    assert.match(src, /mg-model-picker \.mg-q\{[\s\S]{0,320}?flex:none;\}/);
    assert.match(src, /mg-model-picker \.mg-mktsort\{[\s\S]{0,220}?flex:none;\}/);
    assert.match(src, /mg-model-picker \.mg-mktcats\{[\s\S]{0,220}?flex:none;\}/);
    assert.match(src, /mg-model-picker \.mg-empty\{[\s\S]{0,220}?flex:none;\}/);
  });
});

describe("Problem 3: base-type attribute drives architecture-aware LoRA sort/badging", () => {
  test("base-type is observed and re-searches when it changes", () => {
    assert.match(src, /static get observedAttributes\(\) \{ return \['kind', 'base-type'\]; \}/,
      "base-type must be an observed attribute so a host setting it via setAttribute (the " +
      "Gallery) or a JSX prop (the Loom) triggers attributeChangedCallback");
    // AUDIT_2026-07-21 follow-up: the re-search is now conditional on this instance being
    // VISIBLE -- a hidden one defers to the next ensureSearched() instead of fetching and
    // building ~24 cards into a display:none element (see mg-model-picker-pagination.test.js
    // for that half). The behavior THIS test protects is unchanged and still asserted: an
    // instance with results on screen re-searches immediately on a base-type change.
    assert.match(src, /if \(name === 'base-type' && this\._built && \(val \|\| ''\) !== this\._baseType\) \{\s*\n\s*this\._baseType = val \|\| '';/,
      "changing base-type must record the new base type");
    assert.match(src, /if \(this\.style\.display === 'none'\) \{ if \(this\._searched\) this\._stale = true; return; \}\s*\n\s*this\._search\(\);/,
      "changing base-type while results are already on screen must re-search so the sort/" +
      "badges reflect the NEW base immediately -- only a HIDDEN instance defers");
  });

  test("base_type= is only sent for kind=lora, and only once a base is actually selected", () => {
    assert.match(src,
      /if \(this\._kind === 'lora' && this\._baseType\) \{\s*\n\s*u \+= '&base_type=' \+ encodeURIComponent\(this\._baseType\);/,
      "a base-kind mount (nothing to compat-sort a base model against) or a lora mount with " +
      "no base picked yet must never send base_type=");
  });

  // Superseded 2026-08-02 by the DC (UI Kit v2 / Frontend Gallery) conformance pass:
  // the old compatBadge() function and its green "yes" / red "no" text badges are GONE
  // by design -- the DC has no "compatible" badge at all, only a warning treatment for
  // CONFIRMED incompatible rows. The safety invariant these tests protected is
  // unchanged and re-asserted below in its new shape: only compat==='no' gets flagged;
  // 'yes' and 'unknown' (or no base selected) both render identically -- NO badge,
  // fully live -- so an unresolved architecture is never overclaimed as compatible.
  test("only a CONFIRMED incompatible row (compat==='no') is flagged -- 'yes'/'unknown' render identically, unflagged", () => {
    assert.match(src, /var incompat = m\.compat === 'no';/,
      "'yes' and 'unknown' must fall through to the same unflagged path -- badging an " +
      "unresolved architecture would overclaim data the server doesn't have (see " +
      "annotate_lora_compat's own docstring)");
  });

  test("a confirmed-incompatible row gets the warning badge, dimmed cover, and a blocked NEW pick", () => {
    assert.match(src, /incompat && arch \? '<span class="mg-ibadge">&#9888; ' \+ esc\(arch\) \+ '<\/span>' : ''/);
    assert.match(src, /if \(!incompat \|\| self\._isSelected\(m\)\) c\.addEventListener\('click'/,
      "a fresh pick on an incompatible row must be blocked, but removing one that was " +
      "ALREADY selected before the base changed must still work (DC toggleLora order)");
  });
});

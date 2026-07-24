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
// renders the server's `compat` tag (pixai_gallery_backup.py's annotate_lora_compat) as a
// small badge.
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
    assert.match(src, /'mg-model-picker \.mg-grid\{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px;',\s*\n\s*' flex:1 1 auto;min-height:140px;overflow:auto;transition:opacity \.12s;\}',/,
      "the grid must flex-grow to fill the host's real height and remain the one scrolling " +
      "region -- not a second independent scroll container fighting the host's own overflow");
  });

  test("the search input / market UI / empty message stay their natural size (flex:none), only the grid grows", () => {
    // The declared style is a JS array of string fragments joined at runtime (some rules
    // span two fragments) -- match loosely across that boundary rather than assuming each
    // selector's whole declaration lives in one JS string literal.
    assert.match(src, /mg-model-picker \.mg-q\{[\s\S]{0,220}?flex:none;\}/);
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
    assert.match(src, /if \(name === 'base-type' && this\._built && \(val \|\| ''\) !== this\._baseType\) \{\s*\n\s*this\._baseType = val \|\| ''; this\._search\(\);/,
      "changing base-type after results are already on screen must re-search so the sort/" +
      "badges reflect the NEW base immediately");
  });

  test("base_type= is only sent for kind=lora, and only once a base is actually selected", () => {
    assert.match(src,
      /if \(this\._kind === 'lora' && this\._baseType\) \{\s*\n\s*u \+= '&base_type=' \+ encodeURIComponent\(this\._baseType\);/,
      "a base-kind mount (nothing to compat-sort a base model against) or a lora mount with " +
      "no base picked yet must never send base_type=");
  });

  test("the server's compat tag renders as a badge -- 'yes'/'no' visible, 'unknown' renders nothing", () => {
    assert.match(src, /function compatBadge\(compat\) \{/);
    assert.match(src, /if \(compat === 'yes'\) return '<span class="mg-cbadge yes">/);
    assert.match(src, /if \(compat === 'no'\) return '<span class="mg-cbadge no"/);
    assert.match(src, /return '';\s*\n\s*\}\s*\n\s*function baseLabel/,
      "'unknown' (or no base selected, i.e. no compat key at all) must render NO badge -- " +
      "badging an unresolved architecture as compatible would overclaim data the server " +
      "doesn't have (see annotate_lora_compat's own docstring)");
  });

  test("the card template actually calls compatBadge with the row's own compat field", () => {
    assert.match(src, /compatBadge\(m\.compat\)/);
  });
});

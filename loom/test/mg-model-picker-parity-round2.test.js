import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// picker-parity-round2 (2026-07-24): two follow-ups the owner found live-testing the O12/O13
// migration, both fixed in what was static/mg-model-picker.js.
//
// 2026-08-08 (static/ -> React campaign): the <mg-model-picker> custom element was ported
// FAITHFULLY to gallery/src/components/ModelPicker.jsx (React) + gallery/src/styles/
// model-picker.css, and the old file was deleted. Every behaviour survives; this test just
// re-targets its assertions at the two new sources -- the CSS layout ones at model-picker.css,
// the base-type behaviour ones at ModelPicker.jsx.
//
// Problem 1 (layout): the Gallery's #model-flyout showed only ~2 rows of cards then a large
// dead area -- .mg-grid had a fixed max-height:320px independent of the host panel's real
// (much taller) available height. Fixed by making the picker a flex column whose .mg-grid
// is flex:1 (fills whatever room a constraining host hands down; sizes to content exactly
// like display:block used to when no host constrains it). In the port the element selector
// `mg-model-picker` became the `.model-picker` class (React renders a plain <div>); the CSS
// values are spec-literal-identical.
//
// Problem 3 (LoRA architecture filtering): the vanilla `base-type` opt-in ATTRIBUTE became a
// `baseType` PROP that threads the selected base model's model_type into /api/model-search as
// base_type=, and the component renders the server's `compat` tag (moonglade_backup.py's
// annotate_lora_compat) against the row. Badge shape changed 2026-08-02 (DC conformance pass):
// only a CONFIRMED incompatible row ('no') is flagged now -- warning badge, dimmed cover,
// blocked new pick -- 'yes' and 'unknown' both render fully live with no badge at all.
//
// Both sources are plain files with no jsdom/React harness in this runner -- source-presence
// assertions are the established pattern here (see mg-model-picker-market.test.js,
// mg-model-picker-multi-select.test.js). Live visual verification (the grid actually
// filling/scrolling, the badge actually rendering) needs a real browser -- see the CHANGELOG /
// audit doc for that evidence.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/model-picker.css"), "utf8");
const jsx = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8");
// Strip CSS /* */ comments so only the rules the browser actually receives are matched
// (model-picker.css carries a header comment explaining the vanilla->React port).
const cssRules = css.replace(/\/\*[\s\S]*?\*\//g, "");

describe("Problem 1: .mg-grid fills its host's real height instead of a fixed 320px cap", () => {
  test("the picker's own default display is a flex column, not block", () => {
    assert.match(cssRules, /\.model-picker\{display:flex;flex-direction:column;min-height:0;/,
      "must be a flex column so a host that constrains this element's height can hand real " +
      "room down to .mg-grid via flex:1 -- display:block had no such mechanism");
  });

  test("the old fixed max-height:320px on .mg-grid is GONE from the actual CSS rule", () => {
    assert.doesNotMatch(cssRules, /max-height:320px/,
      "a fixed max-height independent of the host's real available height is exactly the " +
      "owner's reported bug (grid capped at 320px, dead space below it in a taller panel)");
  });

  test(".mg-grid is a flex item that grows to fill available space and keeps its own scroll", () => {
    // Column template updated 2026-08-02 (DC conformance: fixed 1fr-1fr -> the DC's own
    // auto-fill/minmax card grid). The FLEX/SCROLL mechanics this test protects (flex:1 1 auto,
    // min-height, overflow:auto) are unchanged, and carried verbatim into model-picker.css.
    assert.match(cssRules,
      /\.model-picker \.mg-grid\{display:grid;grid-template-columns:repeat\(auto-fill,minmax\(124px,1fr\)\);grid-auto-rows:min-content;\s*gap:11px;align-content:start;margin-top:8px;\s*flex:1 1 auto;min-height:140px;overflow:auto;transition:opacity \.18s cubic-bezier\(\.2,\.9,\.24,1\);\}/,
      "the grid must flex-grow to fill the host's real height and remain the one scrolling " +
      "region -- not a second independent scroll container fighting the host's own overflow");
  });

  test(".mg-grid forces auto rows to size off content, not stretch to fill a definite container height", () => {
    assert.match(cssRules, /grid-auto-rows:min-content/,
      "found live 2026-07-24: .mg-card has overflow:hidden, which per spec makes its " +
      "automatic minimum size 0 -- with a definite grid height (from the flex:1 1 auto " +
      "fix above) and default grid-auto-rows:auto, every implicit row track stretched to " +
      "divide the container's fixed height evenly instead of sizing to content, squishing " +
      "every card to a sliver and making scrollHeight never exceed clientHeight either " +
      "(the reported 'no longer scrollable' was the SAME bug, not a second one)");
  });

  test("the search input / market UI / empty message stay their natural size (flex:none), only the grid grows", () => {
    assert.match(cssRules, /\.model-picker \.mg-q\{[\s\S]{0,320}?flex:none;\}/);
    assert.match(cssRules, /\.model-picker \.mg-mktsort\{[\s\S]{0,220}?flex:none;\}/);
    assert.match(cssRules, /\.model-picker \.mg-mktcats\{[\s\S]{0,220}?flex:none;\}/);
    assert.match(cssRules, /\.model-picker \.mg-empty\{[\s\S]{0,220}?flex:none;\}/);
  });
});

describe("Problem 3: baseType prop drives architecture-aware LoRA sort/badging", () => {
  test("baseType comes down as a prop and re-searches when it changes", () => {
    // Vanilla observedAttributes(['kind','base-type']) + attributeChangedCallback -> a `baseType`
    // PROP: React re-derives searchUrl whenever it changes (baseType is a useCallback dep), so a
    // host (the Gallery, the Loom) that changes it triggers a re-search the same way setAttribute
    // drove attributeChangedCallback. This re-expresses the custom-element plumbing as its React
    // contract -- the user behaviour it protected is unchanged.
    assert.match(jsx, /kind = "base", multi = false, market = false, baseType = "",/,
      "baseType must be a declared prop so a host can drive it (setAttribute -> JSX prop)");
    assert.match(jsx,
      /\}, \[kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType\]\);/,
      "searchUrl must depend on baseType so a base-type change re-derives the request URL");
    // AUDIT_2026-07-21 follow-up: a HIDDEN instance defers instead of fetching + building ~24
    // cards into a display:none element. The element's style.display==='none' guard is now the
    // `visible` prop gate; the reveal re-runs the effect and searches with the new baseType.
    assert.match(jsx, /if \(!visible\) return;\s*\n\s*const key = searchUrl\(\);/,
      "a hidden instance must defer -- only search once visible");
    // An instance with results already on screen re-searches immediately on a base-type change:
    // the effect keyed on searchUrl re-runs; only a truly unchanged key (a plain re-reveal) is
    // skipped -- the React equivalent of ensureSearched()/_stale.
    assert.match(jsx,
      /const key = searchUrl\(\);\s*\n\s*if \(key === lastKeyRef\.current\) return;\s*\n\s*lastKeyRef\.current = key;\s*\n\s*doSearch\(\);/,
      "changing baseType while visible must re-search so the sort/badges reflect the NEW base " +
      "immediately -- only a HIDDEN instance defers");
  });

  test("base_type= is only sent for kind=lora, and only once a base is actually selected", () => {
    assert.match(jsx,
      /if \(kind === "lora" && baseType\) u \+= "&base_type=" \+ encodeURIComponent\(baseType\);/,
      "a base-kind mount (nothing to compat-sort a base model against) or a lora mount with " +
      "no base picked yet (baseType empty) must never send base_type=");
  });

  // Superseded 2026-08-02 by the DC (UI Kit v2 / Frontend Gallery) conformance pass:
  // the old compatBadge() function and its green "yes" / red "no" text badges are GONE
  // by design -- the DC has no "compatible" badge at all, only a warning treatment for
  // CONFIRMED incompatible rows. The safety invariant these tests protected is
  // unchanged and re-asserted below in its new shape: only compat==='no' gets flagged;
  // 'yes' and 'unknown' (or no base selected) both render identically -- NO badge,
  // fully live -- so an unresolved architecture is never overclaimed as compatible.
  test("only a CONFIRMED incompatible row (compat==='no') is flagged -- 'yes'/'unknown' render identically, unflagged", () => {
    assert.match(jsx, /const incompat = m\.compat === "no";/,
      "'yes' and 'unknown' must fall through to the same unflagged path -- badging an " +
      "unresolved architecture would overclaim data the server doesn't have (see " +
      "annotate_lora_compat's own docstring)");
  });

  test("a confirmed-incompatible row gets the warning badge, dimmed cover, and a blocked NEW pick", () => {
    // dimmed cover: the row gets the `incompat` class, which drives
    // `.model-picker .mg-card.incompat .mg-cov{filter:saturate(.3) brightness(.6);}` in the CSS.
    assert.match(jsx, /"mg-card" \+ \(sel \? " sel" : ""\) \+ \(incompat \? " incompat" : ""\)/,
      "a confirmed-incompatible row must carry the .incompat class (dimmed cover / .55 opacity)");
    assert.match(cssRules, /\.model-picker \.mg-card\.incompat \.mg-cov\{filter:saturate\(\.3\) brightness\(\.6\);\}/,
      "the .incompat cover dim (the DC's saturate .3 / brightness .6) must survive the port");
    assert.match(jsx, /\{incompat && arch && <span className="mg-ibadge">&#9888; \{arch\}<\/span>\}/,
      "a confirmed-incompatible row shows the warning badge with the required arch");
    assert.match(jsx, /const clickable = !incompat \|\| sel;/,
      "a fresh pick on an incompatible row must be blocked, but removing one that was " +
      "ALREADY selected before the base changed must still work (DC toggleLora order)");
    assert.match(jsx, /onClick=\{clickable \? \(\) => pick\(m\) : undefined\}/,
      "the click handler is wired only when clickable -- an incompatible unselected row is a no-op");
  });
});

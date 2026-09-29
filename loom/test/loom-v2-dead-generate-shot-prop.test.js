import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Originally the regression guard for AUDIT_2026-07-21.md's O11 finding: `generateShot` was
// threaded through LoomV2 as a prop -- destructured in its signature, passed at the <LoomV2 .../>
// call site -- but never CALLED anywhere in LoomV2's body (per-shot generation had moved to the
// Video drawer). The guard then pinned "LoomV2 never receives generateShot".
//
// Session P, Stage A2 deliberately replaces that: the Loom Handoff page's section A card has its
// own Render / Re-render button (BUILD-w5-p §3.1 entry #8 -- "the same function as #3, own price
// + confirm"), and that button is on LoomV2's board card. So LoomV2 receives generateShot again,
// and this guard now pins the NEW, stricter property: the prop is not dead AND it has exactly one
// use -- the card's Render button's onClick -- and nowhere else in LoomV2 (no effect, no other
// handler, no other prop). The whole-file caller allowlist for every render entry point lives in
// loom-no-auto-render.test.js (review F20); this file keeps LoomV2's own slice of it readable.
// A plain source-text check (master-storyboard.jsx has no JSX render harness in this suite).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");
// Comments out, so a comment that NAMES generateShot is not counted as a use of it.
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
  .replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/\s.*$/gm, "");

function loomV2Body() {
  const start = storyboardSrc.indexOf("\nfunction LoomV2(");
  assert.ok(start >= 0, "expected to find function LoomV2(");
  const end = storyboardSrc.indexOf("\nfunction ", start + 1);
  assert.ok(end > start, "expected a function after LoomV2");
  return storyboardSrc.slice(start, end);
}

describe("LoomV2 receives generateShot for the card's Render button -- and uses it nowhere else", () => {
  test("LoomV2's own signature destructures generateShot", () => {
    const sigMatch = storyboardSrc.match(/function LoomV2\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomV2's function signature");
    assert.match(codeOnly(sigMatch[1]), /\bgenerateShot\b/,
      "the card's Render / Re-render button needs generateShot (its own price + confirm)");
  });

  test("inside LoomV2, generateShot is referenced exactly once: the .lv-render button's onClick", () => {
    const body = codeOnly(loomV2Body());
    const sigEnd = body.search(/\}\)\s*\{/);
    const inside = body.slice(sigEnd);
    const uses = inside.match(/\bgenerateShot\b/g) || [];
    assert.equal(uses.length, 1,
      "generateShot may be used once in LoomV2's body -- the card's Render button -- found " + uses.length);
    assert.match(inside,
      /<button type="button" className="lv-render" disabled=\{renderBlocked\}[\s\S]{0,700}?onClick=\{\(\) => generateShot\(e\)\}>/,
      "the one use must be the card Render button's onClick, disabled while the shot's render is out");
    assert.match(inside, /const renderBlocked = goBlocked\(e\.c, paused\);/,
      "the Render button is gated by the same Go gate as the drawer and the phone");
  });

  test("the <LoomV2 .../> call site passes the real generateShot, as itself", () => {
    const loomV2Call = storyboardSrc.match(/<LoomV2\b[\s\S]*?\/>/);
    assert.ok(loomV2Call, "expected to find the <LoomV2 .../> call site");
    assert.equal((loomV2Call[0].match(/\bgenerateShot\b/g) || []).length, 2,
      "exactly one generateShot={generateShot} prop, nothing else naming it");
    assert.match(loomV2Call[0], /\sgenerateShot=\{generateShot\}\s/);
  });

  test("the REAL generateShot implementation (inside useGenerationPipeline) is untouched", () => {
    // Guard-rail against over-deletion: this must still exist and still be called internally
    // by batchGenerate.
    assert.match(
      storyboardSrc,
      /const generateShot = async \(entry, opts = \{\}\) => \{/,
      "the live generateShot implementation inside useGenerationPipeline should not be removed"
    );
    assert.match(
      storyboardSrc,
      // Session P: the batch also hands over what it confirmed (fingerprint, pool verdict).
      /await generateShot\(e, \{ skipConfirm: true, onlyIfNeeded: true, confirmedFp: fps\[i\], expectFree: covered\[i\],/,
      "generateShot should still be called internally by the generation pipeline's own batch runner"
    );
  });
});

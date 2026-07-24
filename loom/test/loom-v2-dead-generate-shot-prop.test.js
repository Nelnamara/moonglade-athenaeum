import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard for AUDIT_2026-07-21.md's O11 finding: `generateShot` was threaded through
// LoomV2 as a prop -- destructured in its own function signature, passed at the <LoomV2 .../>
// call site inside App() -- but never actually CALLED anywhere in LoomV2's body. Residue of the
// migration where per-shot generation moved to <mg-generate-drawer> owning its own submit/poll
// cycle instead (confirmed separately: that element is mounted inside LoomV2's own JSX). The
// REAL generateShot (defined inside the useGenerationPipeline hook, called internally by
// batchGenerate etc.) is a different, live thing and must not be touched -- this guard only
// targets the two dead LoomV2-specific sites. This is a plain source-text check
// (master-storyboard.jsx has no JSX render harness in this suite), mirroring
// loom-gen-drawer-loom-ctx.test.js's technique.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("LoomV2 no longer threads the dead generateShot prop", () => {
  test("LoomV2's own function signature does not destructure generateShot", () => {
    const sigMatch = storyboardSrc.match(/function LoomV2\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomV2's function signature");
    assert.doesNotMatch(
      sigMatch[1],
      /\bgenerateShot\b/,
      "LoomV2 still destructures generateShot in its own signature, but nothing inside its " +
      "body calls it -- <mg-generate-drawer> owns per-shot generation now"
    );
  });

  test("the <LoomV2 .../> call site does not pass a generateShot prop", () => {
    assert.doesNotMatch(
      storyboardSrc,
      /generateShot=\{generateShot\}/,
      "App() still passes generateShot into <LoomV2>, but LoomV2 never reads it"
    );
  });

  test("the REAL generateShot implementation (inside useGenerationPipeline) is untouched", () => {
    // Guard-rail against over-deletion: this must still exist and still be called internally
    // (e.g. by batchGenerate) -- only the LoomV2 prop-drill is dead, not the function itself.
    assert.match(
      storyboardSrc,
      /const generateShot = async \(entry, opts = \{\}\) => \{/,
      "the live generateShot implementation inside useGenerationPipeline should not be removed"
    );
    assert.match(
      storyboardSrc,
      /await generateShot\(e, \{ skipConfirm: true \}\)/,
      "generateShot should still be called internally by the generation pipeline's own batch runner"
    );
  });
});

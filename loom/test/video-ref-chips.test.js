import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner QA recording, 2026-08-25 (late-night pass on the reference-video drawer):
//  1) focus/blur of the contenteditable prompt made the @imageN chips PILE UP -- each cycle
//     nested every chip one layer deeper (icon icon icon icon @image1). Root cause: makeChip puts
//     the literal tag text inside the chip, and chipify's TreeWalker walked every text node --
//     including a chip's own label -- so blur's chipify(final=true) re-chipified the inside of
//     each chip. (The input-debounce pass skipped it only because the label sits at the end of
//     its text node and final=false skips end-of-node matches -- which is exactly why the bug
//     needed focus-out, matching the owner's repro.)
//  2) hovering a chip popped the floating thumbnail far from the chip / off-screen. Root cause:
//     .mgd-preview is position:fixed placed with viewport coords, but the dock ancestors carry a
//     permanent transform (translateX(-50%)) + backdrop-filter -- either one makes that ancestor
//     the containing block for fixed descendants, re-anchoring the preview to the dock's box.
//
// The chip DOM algorithm now lives in gallery/src/gen/refChips.js (testable, one home) and the
// preview is portaled to document.body. The suite has no DOM harness, so these are the
// established source-structure pins; the live focus/blur x N + hover verification ran in a real
// browser against the actual module (and the owner's QA is the final pass).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const mod = readFileSync(path.join(__dirname, "../../gallery/src/gen/refChips.js"), "utf8").replace(/\r\n/g, "\n");
const drawer = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8").replace(/\r\n/g, "\n");
const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/gen-drawer.css"), "utf8").replace(/\r\n/g, "\n");

describe("ref chips: no nesting, self-healing, preview out of the transformed ancestors", () => {
  test("chipify skips text that already lives inside a chip -- the nesting fix", () => {
    const i = mod.indexOf("closest(\".mgd-chip\")) continue;");
    const j = mod.indexOf("nodes.push(tn);");
    assert.ok(i >= 0, "the walker must skip chip-label text nodes");
    assert.ok(j > i, "the skip must come BEFORE the node is collected");
  });

  test("chipify self-heals chips the pre-fix code nested", () => {
    assert.match(mod, /querySelectorAll\("\.mgd-chip \.mgd-chip"\)/,
      "a chip-inside-chip from the old code must be found and flattened");
    assert.match(mod, /\{ outer\.remove\(\); return; \}/,
      "a junk data-ref is dropped, never innerHTML'd back");
  });

  test("promptText still reads data-ref and never descends into a chip (submit-text invariant)", () => {
    assert.match(mod, /contains\("mgd-chip"\)\) out \+= c\.getAttribute\("data-ref"\)/,
      "the chip's data-ref -- not its inner DOM -- is what a paid submit carries");
    assert.ok(mod.includes('out.replace(/ /g, " ").trim()'),
      "the nbsp normalization must survive the lift byte-for-byte");
  });

  test("the drawer delegates to the module -- the algorithm has exactly one home", () => {
    assert.match(drawer, /import \{ chipify as refChipify, promptText as refPromptText \} from "\.\.\/gen\/refChips\.js"/);
    assert.match(drawer, /const chipify = \(final\) => refChipify\(ceRef\.current, refMap\(\), final, chipHooks\)/);
    assert.match(drawer, /const promptText = \(\) => refPromptText\(ceRef\.current\)/);
    assert.doesNotMatch(drawer, /createTreeWalker/, "no inline copy of the walker may remain");
  });

  test("the floating preview is portaled to document.body -- immune to ancestor transforms", () => {
    assert.match(drawer, /createPortal\(<div ref=\{previewRef\} className="mgd-preview" aria-hidden="true" \/>, document\.body\)/);
  });

  test("the preview CSS is no longer scoped under .gen-drawer (it lives on body now)", () => {
    assert.match(css, /\n\.mgd-preview\{position:fixed/);
    assert.doesNotMatch(css, /\.gen-drawer \.mgd-preview/);
  });
});

// Appended after the owner's second QA pass: the first cut of this fix shipped dist/app.js but
// NOT dist/app.css. The portaled preview div then ran against the old `.gen-drawer .mgd-preview`
// selector, matched nothing, and rendered as an unstyled static div at the end of <body> -- the
// reported "no thumbnails at all / sometimes behind the prompt text". dist is a committed
// artifact in this repo, so pin the BUILT stylesheet too.
test("the BUILT stylesheets ship the unscoped preview rule -- both dists actually deploy the fix", () => {
  // Two committed build artifacts serve this component: vite's gallery/dist (minified) and
  // esbuild's loom/dist (unminified -- `.mgd-preview {` with a space), because the Loom bundles
  // its OWN copy of VideoDrawer (loom/master-storyboard.jsx imports it). The first cut shipped
  // neither artifact's CSS and the second nearly missed the Loom's, so pin both, format-tolerant.
  for (const rel of ["../../gallery/dist/app.css", "../../loom/dist/master-storyboard.bundle.css"]) {
    const dist = readFileSync(path.join(__dirname, rel), "utf8");
    assert.match(dist, /\.mgd-preview\s*\{\s*position:\s*fixed/, rel + " must carry the unscoped rule");
    assert.doesNotMatch(dist, /\.gen-drawer\s+\.mgd-preview/, rel + " must not keep the old scoped selector");
  }
});

test("the BUILT loom bundle carries the module fix, not the old inline chipify", () => {
  const js = readFileSync(path.join(__dirname, "../../loom/dist/master-storyboard.bundle.js"), "utf8");
  assert.ok(!js.includes("const chipify = (final) => {"), "the old inline chipify must be gone from the loom bundle");
  assert.ok(js.includes('closest(".mgd-chip")'), "the nesting guard must be IN the loom bundle");
});


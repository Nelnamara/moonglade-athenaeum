import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard for AUDIT_2026-07-21.md row (`state-owner-defects`): ".lv-df-veil really
// does render inside .lv-overlay" -- .lv-df-veil (Deep Focus's full-screen veil) is a JSX
// descendant of .lv-overlay, so its z-index:450 only ever competes inside .lv-overlay's OWN
// stacking context, not the root one. .lv-overlay itself is only z-index:400 at the root,
// which loses to the body-level corner FABs (#jobs-fab/#jobs-tray, z-index 401/402 -- see
// pixai_gallery.py's "Lift the Activity chip" comment), so those FABs painted over Deep
// Focus and everything nested inside it. Fixed without a DOM move: .lv-overlay itself picks
// up a `.lv-overlay-df` modifier class while Deep Focus is open, raising its OWN root-context
// z-index to 450 (matching .lv-df-veil's own intended value) so the corner FABs lose the
// comparison the way every other 400+ overlay in this file already does. This is a plain
// source-text check (master-storyboard.jsx has no JSX render harness in this suite),
// mirroring the technique in loom-gen-drawer-loom-ctx.test.js.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("Deep Focus veil no longer loses to the corner FABs' stacking", () => {
  test("the .lv-overlay mount toggles a modifier class while Deep Focus is open", () => {
    const match = storyboardSrc.match(/<div className=\{"lv-overlay"[^}]*\}>/);
    assert.ok(match, "expected to find the .lv-overlay mount's dynamic className expression");
    assert.match(
      match[0],
      /deepFocus/,
      "the .lv-overlay mount's className no longer reacts to deepFocus -- Deep Focus's veil " +
      "will again be contained inside .lv-overlay's z-index:400 root-context stacking and " +
      "lose to the body-level corner FABs (#jobs-fab/#jobs-tray, z-index 401/402)"
    );
  });

  test("a raised z-index rule exists for the Deep-Focus-open modifier class", () => {
    assert.match(
      storyboardSrc,
      /\.lv-overlay\.lv-overlay-df\s*\{[^}]*z-index:\s*45\d/,
      "expected a .lv-overlay.lv-overlay-df rule raising z-index above the corner FABs' " +
      "401/402 (to .lv-df-veil's own intended 450) while Deep Focus is open"
    );
  });
});

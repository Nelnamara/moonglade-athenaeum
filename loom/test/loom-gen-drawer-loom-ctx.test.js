import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard for AUDIT_2026-07-21.md row: "data-loom-ctx has zero callers, so the
// Loom's Video panel renders two Camera controls and two quality controls." The video drawer
// (since the no-vanilla port, the React <VideoDrawer> in gallery/src/components/VideoDrawer.jsx)
// hides its own Camera + Basic/Professional controls only when the host passes the `loomCtx`
// prop, which renders data-loom-ctx on the root node (see gen-drawer.css's
// `.gen-drawer[data-loom-ctx] .mgd-cam-wrap,...`). master-storyboard.jsx is the only host that
// mounts <VideoDrawer>, and it owns equivalent Camera / Draft controls of its own -- if that
// prop is ever dropped from the JSX again, the drawer silently grows a second, redundant Camera
// control and a second quality control with no test to catch it. This is a plain source-text
// check (master-storyboard.jsx has no JSX render harness in this suite), mirroring the technique
// in mg-generate-drawer-parity.test.js.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("<VideoDrawer> mount sets loomCtx", () => {
  test("the JSX tag carries loomCtx so the shared drawer hides its own Camera/quality controls", () => {
    // Require a space after the tag name so this only matches the real JSX mount (which has
    // attributes/props) and not the several bare "<VideoDrawer>" mentions in prose comments.
    const match = storyboardSrc.match(/<VideoDrawer\s[^>]*>/);
    assert.ok(match, "expected to find a <VideoDrawer ...> mount in master-storyboard.jsx");
    assert.match(
      match[0],
      /loomCtx/,
      "the <VideoDrawer> mount is missing the loomCtx prop -- its own Camera and " +
      "Basic/Professional controls will render alongside the Loom's equivalent controls"
    );
  });
});

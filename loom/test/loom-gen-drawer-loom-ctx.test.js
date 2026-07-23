import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard for AUDIT_2026-07-21.md row: "data-loom-ctx has zero callers, so the
// Loom's Video panel renders two Camera controls and two quality controls." static/mg-
// generate-drawer.js hides its own Camera + Basic/Professional controls only when the host
// sets data-loom-ctx on the <mg-generate-drawer> element (see that file's CSS comment next
// to `mg-generate-drawer[data-loom-ctx] .mgd-cam-wrap,...`). master-storyboard.jsx is the
// only host that mounts <mg-generate-drawer>, and it owns equivalent Camera / Draft controls
// of its own -- if this attribute is ever dropped from the JSX again, the drawer silently
// grows a second, redundant Camera control and a second quality control with no test to
// catch it. This is a plain source-text check (master-storyboard.jsx has no JSX render
// harness in this suite), mirroring the technique in mg-generate-drawer-parity.test.js.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("<mg-generate-drawer> mount sets data-loom-ctx", () => {
  test("the JSX tag carries data-loom-ctx so the shared drawer hides its own Camera/quality controls", () => {
    // Require a space after the tag name so this only matches the real JSX mount (which has
    // attributes) and not the several bare "<mg-generate-drawer>" mentions in prose comments
    // elsewhere in this file.
    const match = storyboardSrc.match(/<mg-generate-drawer\s[^>]*>/);
    assert.ok(match, "expected to find a <mg-generate-drawer ...> mount in master-storyboard.jsx");
    assert.match(
      match[0],
      /data-loom-ctx/,
      "the <mg-generate-drawer> mount is missing data-loom-ctx -- its own Camera and " +
      "Basic/Professional controls will render alongside the Loom's equivalent controls"
    );
  });
});

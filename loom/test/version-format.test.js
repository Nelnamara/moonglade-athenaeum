import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fullVersion } from "../../gallery/src/help/helpCore.js";

/* One version format everywhere (2026-11-18): the phone's About row printed "v3.21" while the
   desktop Panel printed "v3.21.0". Both now print the build stamp's version whole, and the
   guide's display_version is the full x.y.z too (dev/tests/test_help_guide.py). */
const src = (p) => readFileSync(new URL("../../gallery/src/" + p, import.meta.url), "utf8");

test("the phone About row prints the full version, the way the desktop does", () => {
  const mobile = src("components/ControlMobile.jsx");
  assert.match(mobile, /const aboutVer = versionFromStamp\([^;]*\);/);
  assert.ok(!/const aboutVer[^;]*\.replace\(/.test(mobile), "the phone trims the version again");
  assert.match(src("components/ControlPanelOverlay.jsx"), /const aboutVer = versionFromStamp\(/);
});

test("an old stored x.y reads as x.y.0", () => {
  assert.equal(fullVersion("3.21"), "3.21.0");
  assert.equal(fullVersion("3.21.4"), "3.21.4");
  assert.equal(fullVersion(undefined), "");
});

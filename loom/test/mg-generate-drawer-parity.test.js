import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { friendlyGenErr } from "../src/loom-mutations.js";

// static/mg-generate-drawer.js is a plain host-agnostic <script> with no build step, so it
// can't import loom-mutations.js -- its friendlyGenErr is a deliberate, hand-maintained LOCAL
// COPY (see that file's own duplication-risk comment next to the function). The only guard
// against the two silently drifting apart on a future edit to either one is this test:
// extract the drawer's copy as a live function and assert it stays byte-identical to the
// real one across a fixed case list. If this ever fails, someone edited one copy without
// updating the other.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const drawerSrc = readFileSync(path.join(__dirname, "../../static/mg-generate-drawer.js"), "utf8");

const match = drawerSrc.match(/function friendlyGenErr\(raw\) \{[\s\S]*?\n  \}/);
if (!match) {
  throw new Error(
    "static/mg-generate-drawer.js's local friendlyGenErr(raw) was not found by this test's " +
    "regex -- its signature or indentation changed. Update this test's extraction pattern " +
    "to match, don't just delete the test."
  );
}
const localFriendlyGenErr = new Function("return (" + match[0] + ")")();

// pixai_gallery.py's Gen IIFE (the Image tab's own inline <script>) is a THIRD hand-copy,
// same reason as the drawer's -- see its own duplication-risk comment right above
// renderResultInto(). Extracted the same way: pull the function's source as text out of
// the Python file (it's a plain JS function embedded in a Python string, no Python syntax
// inside it) and turn it into a live function.
const gallerySrc = readFileSync(path.join(__dirname, "../../pixai_gallery.py"), "utf8");
const galleryMatch = gallerySrc.match(/function friendlyGenErr\(raw\)\{[\s\S]*?\n  \}/);
if (!galleryMatch) {
  throw new Error(
    "pixai_gallery.py's local friendlyGenErr(raw) was not found by this test's regex -- " +
    "its signature or indentation changed. Update this test's extraction pattern to match, " +
    "don't just delete the test."
  );
}
// The Python source escapes JS's own backslash-u unicode escapes as \\uXXXX (so the
// PYTHON string literal contains a real backslash before "u"); collapsing that to a
// single backslash here is what makes the extracted text valid standalone JS again.
const localFriendlyGenErrPy = new Function(
  "return (" + galleryMatch[0].replace(/\\\\u/g, "\\u") + ")"
)();

const CASES = [
  "INSUFFICIENT_BALANCE", "insufficient balance for this task", "40300010",
  "content policy violation", "flagged as sensitive content", "Sensitive content.",
  "prohibited content detected", "not allowed here", "violates our terms",
  'unknown inferenceProfile "ultra" for model type "SDXL_MODEL"', "InferenceProfile rejected",
  "some other random failure", "task failed", "cancelled", "rejected",
  "", null, undefined, 0, false,
];

describe("mg-generate-drawer.js's local friendlyGenErr stays in parity with loom-mutations.js's real one", () => {
  CASES.forEach((c) => {
    test(`matches real friendlyGenErr for input ${JSON.stringify(c)}`, () => {
      assert.equal(localFriendlyGenErr(c), friendlyGenErr(c));
    });
  });
});

describe("pixai_gallery.py's local friendlyGenErr (Gen IIFE) stays in parity with loom-mutations.js's real one", () => {
  CASES.forEach((c) => {
    test(`matches real friendlyGenErr for input ${JSON.stringify(c)}`, () => {
      assert.equal(localFriendlyGenErrPy(c), friendlyGenErr(c));
    });
  });
});

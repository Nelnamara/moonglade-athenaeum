import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// D-11: a raw mouseenter re-triggered an instant, un-animated, freshly-repositioned
// preview popup on EVERY card the mouse passed over while scanning the grid -- which is
// what "browsing" actually is. Fixed with a short hover-intent delay so only a genuine
// pause-to-look opens it. This is fundamentally a feel/timing bug a text assertion can't
// fully prove (the real verification is manual, in a real browser) -- this test only
// guards against someone reverting to the raw, un-debounced wiring without noticing.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");

test("mg-model-picker.js's card hover is debounced, not instant", () => {
  assert.match(src, /mouseenter.*self\._schedulePreview/,
    "card mouseenter must go through the debounced scheduler, not straight to _showPreview");
  assert.match(src, /_schedulePreview\(m, anchor\)\s*\{[\s\S]*?setTimeout/,
    "_schedulePreview must actually delay via setTimeout");
  assert.match(src, /_cancelPreview\(\)\s*\{[\s\S]*?clearTimeout/,
    "_cancelPreview must clear the pending timer, or a fast scan still opens a stale popup");
});

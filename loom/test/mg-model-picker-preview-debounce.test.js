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
//
// The <mg-model-picker> custom element was ported to a React component
// (gallery/src/components/ModelPicker.jsx); the debounced hover-preview survives
// verbatim, so these assertions were retargeted to the React source:
//   card mouseenter  -> onMouseEnter={(e) => schedulePreview(m, e.currentTarget)}
//   _schedulePreview -> const schedulePreview = (m, anchorEl) => { ... setTimeout(..., 130) }
//   _cancelPreview   -> const hidePreview   = () => { clearTimeout(...) }  (wired to onMouseLeave)
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8");

test("ModelPicker card hover is debounced, not instant", () => {
  assert.match(src, /onMouseEnter=\{[^}]*schedulePreview\(m,/,
    "card onMouseEnter must go through the debounced scheduler, not straight to showPreview");
  assert.match(src, /schedulePreview\s*=\s*\(m,\s*anchorEl\)\s*=>\s*\{[\s\S]*?setTimeout\([\s\S]*?,\s*130\)/,
    "schedulePreview must actually delay via setTimeout, and keep the 130ms hover-intent delay");
  assert.match(src, /hidePreview\s*=\s*\(\)\s*=>\s*\{[\s\S]*?clearTimeout/,
    "hidePreview must clear the pending timer, or a fast scan still opens a stale popup");
  assert.match(src, /onMouseLeave=\{hidePreview\}/,
    "leaving a card must cancel any pending preview, so a fast scan can't fire a stale popup");
});

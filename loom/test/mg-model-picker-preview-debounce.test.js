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

// Owner walk 2026-09-29 (screenshot 09): hovering a model card 3 s+ on the desktop showed
// nothing. The preview is position:fixed, but the dock's model palette is transformed
// (.mgx-dock-host .mfly { transform: translateX(-50%); overflow: hidden }), which makes the
// palette the containing block for fixed descendants -- the card was placed against the
// palette and clipped by it. Portaled to <body> it draws at viewport coordinates, above the
// palette (z 500 over 335).
test("the hover preview is portaled to <body>, out of the transformed, clipping dock palette", () => {
  assert.match(src, /import \{ createPortal \} from "react-dom";/);
  assert.match(src, /createPortal\(\s*<div className="model-picker" style=\{\{ display: "contents" \}\}>\s*<div className=\{"mg-preview"/,
    "the preview renders through a portal, inside a box-less .model-picker wrapper its CSS still matches");
  assert.match(src, /<\/div>, document\.body\) : null\}/, "the portal target is document.body");
  const dockCss = readFileSync(path.join(__dirname, "../../gallery/src/styles/dock.css"), "utf8");
  assert.match(dockCss, /\.mgx-dock-host \.mfly \{[^}]*transform: translateX\(-50%\)/,
    "the palette really is transformed -- the reason the preview cannot live inside it");
  const pickerCss = readFileSync(path.join(__dirname, "../../gallery/src/styles/model-picker.css"), "utf8");
  assert.match(pickerCss, /\.model-picker \.mg-preview\{position:fixed;z-index:500;/,
    "the preview stays fixed and above the palette (335)");
});

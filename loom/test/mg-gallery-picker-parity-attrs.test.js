import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// O13: the gallery's own picker has an upload button, a Source filter, and a copy-prompt-on-
// pick checkbox that a 2026-07-24 dead-code sweep once removed (as "zero callers outside the
// dev harness") and were restored the same night when the gallery migration needed them.
// Losing them would be a real regression on the app's most-used surface, not a consolidation.
// This locks the restoration in. Since 2026-08-08 the picker is the React GalleryPicker
// (ported out of static/mg-gallery-picker.js); the three surfaces are opt-in PROPS now.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/GalleryPicker.jsx"), "utf8");

test("all three gallery-parity surfaces are opt-in props (default OFF)", () => {
  assert.match(src, /showSource = false/);
  assert.match(src, /showUpload = false/);
  assert.match(src, /showCopyPrompt = false/);
});

test("the render only shows each surface when its prop is on", () => {
  assert.match(src, /\{showSource && \(/);
  assert.match(src, /\{showUpload && \(/);
  assert.match(src, /\{showCopyPrompt && \(/);
});

test("upload POSTs to /api/upload and picks the result", () => {
  assert.match(src, /const doUpload = \(\) =>/);
  // Re-anchored 2026-08-23: the multipart POST is api.js's apiUpload now -- same route, same
  // FormData, one place that decides what an error answer is.
  assert.match(src, /apiUpload\("\/api\/upload", fd\)/);
  assert.match(src, /pick\(\{ media_id: d\.media_id, prompt: "", thumb: URL\.createObjectURL\(f\) \}\)/);
});

test("copy-prompt persists to the SAME localStorage key the gallery's own picker used", () => {
  // Cross-surface continuity: an account's "copy prompt on pick" preference must not reset
  // just because the picker's implementation changed underneath it.
  assert.match(src, /const COPY_KEY = "pick-copyprompt";/);
  assert.match(src, /localStorage\.getItem\(COPY_KEY\) === "1"/);
  assert.match(src, /localStorage\.setItem\(COPY_KEY, checked \? "1" : "0"\)/);
});

test("a pick copies the prompt to the clipboard only when the checkbox is on and a prompt exists", () => {
  assert.match(src, /if \(copyOn && m\.prompt\) \{/);
  assert.match(src, /navigator\.clipboard && navigator\.clipboard\.writeText\(m\.prompt\)/);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// O13 (Phase 2): the gallery's own #pick-modal has an upload button, a Source filter, and
// a copy-prompt-on-pick checkbox that <mg-gallery-picker> never had. A 2026-07-24 dead-code
// sweep had already removed all three (show-source/show-upload/show-copy-prompt) as
// "zero callers outside the dev harness" -- true at the time, and no longer true the
// moment the gallery's own picker migration needs them, since losing them would be a real
// regression on the app's most-used surface, not a consolidation. Restored the same night;
// this locks the restoration in so a future dead-code pass doesn't re-delete them without
// checking for the gallery's real usage first.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-gallery-picker.js"), "utf8");

test("all three gallery-parity attributes are read as opt-in booleans", () => {
  assert.match(src, /this\._showSource = this\.hasAttribute\('show-source'\)/);
  assert.match(src, /this\._showUpload = this\.hasAttribute\('show-upload'\)/);
  assert.match(src, /this\._showCopy = this\.hasAttribute\('show-copy-prompt'\)/);
});

test("the skeleton only renders each surface when its flag is on", () => {
  assert.match(src, /var sourceSel = this\._showSource\s*\n\s*\? '<select data-f="source">'/);
  assert.match(src, /var uploadBtn = this\._showUpload\s*\n\s*\? '<button type="button" class="mg-pk-upload">/);
  assert.match(src, /var copyCk = this\._showCopy\s*\n\s*\? '<label class="mg-pk-copy">/);
});

test("upload POSTs to /api/upload and picks the result", () => {
  assert.match(src, /_upload\(\)\s*\{/);
  assert.match(src, /fetch\('\/api\/upload', \{ method: 'POST', body: fd \}\)/);
  assert.match(src, /self\._pick\(\{ media_id: d\.media_id, prompt: '', thumb: URL\.createObjectURL\(f\) \}\)/);
});

test("copy-prompt persists to the SAME localStorage key the gallery's own #pick-modal used", () => {
  // Cross-surface continuity: an account's "copy prompt on pick" preference must not reset
  // just because the picker's implementation changed underneath it.
  assert.match(src, /var COPY_KEY = 'pick-copyprompt';/);
  assert.match(src, /this\._copyEl\.checked = localStorage\.getItem\(COPY_KEY\) === '1'/);
  assert.match(src, /localStorage\.setItem\(COPY_KEY, this\.checked \? '1' : '0'\)/);
});

test("a pick copies the prompt to the clipboard only when the checkbox is on and a prompt exists", () => {
  assert.match(src, /if \(this\._copyEl && this\._copyEl\.checked && m\.prompt\) \{/);
  assert.match(src, /navigator\.clipboard && navigator\.clipboard\.writeText\(m\.prompt\)/);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// D-11: mg-model-picker.js gained an opt-in `multi` attribute for the Loom's LoRA
// picker (single-value mode, the default, is unchanged -- the Gallery's own mount
// doesn't use this component at all yet, so there's zero regression risk to it).
// mg-model-picker.js is a plain <script>, no build step, no module exports -- the
// established pattern for testing it (mg-model-picker-preview-debounce.test.js) is
// source-presence assertions, not full instantiation (no jsdom in this test runner).
// This locks in the shape of the toggle/resolve logic; real interaction verification
// (does the chip actually render, does weight-editing work) needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");

test("mg-model-picker.js supports an opt-in multi-select mode", () => {
  assert.match(src, /this\._multi\s*=\s*this\.hasAttribute\('multi'\)/,
    "multi must be an opt-in attribute, read once at connect -- not always-on");
  assert.match(src, /_toggleMulti\(m, card\)\s*\{/,
    "multi-select needs its own toggle path, not a straight replace like single-value _pick");
  assert.match(src, /_isSelected\(m\)\s*\{[\s\S]*?this\._multi/,
    "card selection state must branch on _multi, or the .sel class breaks in one mode");
});

test("a picked LoRA resolves version_id/lora_base_type/trigger_words via /api/model-version", () => {
  assert.match(src, /fetch\('\/api\/model-version\?model_id='/,
    "each multi-select pick must resolve real generation metadata, the same endpoint " +
    "the Gallery's own toggleLora() already uses -- without it, version_id stays '' " +
    "and the LoRA can never actually be submitted");
  assert.match(src, /entry\.lora_base_type\s*=\s*d\.lora_base_model_type/);
});

test("an unresolved/failed LoRA is marked failed, never silently dropped", () => {
  // Mirrors the Gallery's fail-open fix (audit 2026-07-21, fail-open/high): a LoRA that
  // never resolves must not be able to vanish from a submit unnoticed. Both the
  // "resolved but empty" and the network-failure paths must set entry.failed.
  assert.match(src, /entry\.failed\s*=\s*!entry\.version_id/);
  assert.match(src, /\.catch\(function \(\) \{\s*entry\.failed = true;/);
});

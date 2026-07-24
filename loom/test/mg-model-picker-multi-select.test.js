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

test("a picked LoRA resolves version_id/lora_base_type/trigger_words via /api/model-version?all=1", () => {
  // &all=1 (per-LoRA version selection): every published release, not just resolve_version_meta's
  // silently-assumed rows[0] -- entry.versions is stashed so a per-chip selector (the host's job,
  // same split as the base model's #gen-version/.lv-versel) can offer a real choice, mirroring
  // exactly how onBasePick/bindPicker already do it for base models.
  assert.match(src, /fetch\('\/api\/model-version\?model_id=' \+ encodeURIComponent\(m\.model_id\) \+ '&all=1'\)/,
    "each multi-select pick must resolve real generation metadata AND every published " +
    "version, the same endpoint/param the base-model picker already uses -- without it, " +
    "version_id stays '' and the LoRA can never actually be submitted, and there's no " +
    "version list for a per-chip selector to offer");
  assert.match(src, /var versions = \(d && d\.versions\) \|\| \[\], v = versions\[0\] \|\| \{\};/);
  assert.match(src, /entry\.version_id = v\.version_id \|\| '';/);
  assert.match(src, /entry\.lora_base_type\s*=\s*v\.lora_base_model_type/);
  assert.match(src, /entry\.versions = versions;/,
    "the full version list must ride the entry so a host can render a per-chip selector");
});

test("an unresolved/failed LoRA is marked failed, never silently dropped", () => {
  // Mirrors the Gallery's fail-open fix (audit 2026-07-21, fail-open/high): a LoRA that
  // never resolves must not be able to vanish from a submit unnoticed. Both the
  // "resolved but empty" and the network-failure paths must set entry.failed.
  assert.match(src, /entry\.failed\s*=\s*!entry\.version_id/);
  assert.match(src, /\.catch\(function \(\) \{\s*entry\.failed = true;/);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Audit 2026-07-21, O12 (Phase 1): <mg-model-picker> sent size=12 while the gallery's
// own hand-rolled #model-flyout (pixai_gallery.py's Gen.search()) sends size=24 -- a
// silent gap that would have made the shared component a strict downgrade the moment
// the gallery tried to adopt it (half as many results per page, no pagination on
// either side to make up the difference -- see O12's "neither picker paginates" note).
// Page-size parity is a precondition for the Phase 2 gallery migration, not the whole
// fix -- the LoRA half of O12 (multi-select, weights, compat gate, trigger words) was
// already fixed 2026-07-22 (see mg-model-picker-multi-select.test.js).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");

test("mg-model-picker.js requests size=24, matching the gallery's #model-flyout", () => {
  assert.match(src, /&size=24&q=/,
    "the model-search fetch must request 24 results per page, same as pixai_gallery.py's " +
    "Gen.search() -- a mismatched page size makes the shared component a downgrade");
  assert.doesNotMatch(src, /size=12/,
    "no lingering size=12 request anywhere in the component");
});

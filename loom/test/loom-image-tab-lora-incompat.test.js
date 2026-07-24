import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// L536 + D-11: the base-model architecture-compat warning was EXPLICITLY deferred in the
// D-11 audit note ("would need the Loom to additionally resolve the selected base model's
// own type, which it doesn't today") -- functionally safe to defer at the time since
// PixAI's own server already rejects a real mismatch, but it left loraIncompat() imported
// into master-storyboard.jsx with zero call sites (dead weight since the D-11 LoRA-support
// pass). L536's Advanced-section work made bindPicker resolve model_type on every base
// pick anyway (for the model-defaults prefill), so the blocker D-11 named is gone -- this
// wires the warning up, closing that deferred item as a side effect rather than leaving
// the now-usable import sitting there unused.
//
// master-storyboard.jsx has no jsdom/React test harness in this runner -- source-presence
// assertions are the established pattern here (see loom-lora-toggle-chrome.test.js,
// loom-cost-badges.test.js); real interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("Image tab LoRA↔base compatibility warning (L536 closes the D-11 deferral)", () => {
  test("bindPicker resolves the selected base model's model_type", () => {
    assert.match(src, /setImgModel\(\(cur\) => \(cur && cur\.model_id === m\.model_id\) \? \{ \.\.\.cur, model_type: d\.model_type \|\| "" \} : cur\)/,
      "bindPicker must capture the base model's model_type from /api/model-version, or " +
      "loraIncompat has nothing real to compare a picked LoRA against");
  });

  test("each LoRA chip computes incompat via the (previously dead) imported loraIncompat()", () => {
    assert.match(src, /const incompat = loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\);/,
      "the LoRA chip list must call loraIncompat per-chip, using the base's model_type");
    assert.match(src, /className=\{"lv-lchip" \+ \(\(l\.failed \|\| incompat\) \? " failed" : ""\)\}/,
      "an incompatible chip must get the same visual warning treatment as a failed-to-resolve one");
  });

  test("the Generate button is disabled while any attached LoRA is incompatible with the selected base", () => {
    assert.match(src,
      /disabled=\{busyI \|\| anyLoraUnresolved\(imgLoras\) \|\| imgLoras\.some\(\(l\) => loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\)\)\}/,
      "Go must stay gated on incompatibility, not just unresolved -- an incompatible-but-" +
      "RESOLVED LoRA is still not safe to submit");
  });
});

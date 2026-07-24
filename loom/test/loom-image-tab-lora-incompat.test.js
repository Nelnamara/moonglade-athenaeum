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
    // picker-parity-round2 (problem 4/5): bindPicker's fetch grew from the single-version
    // shape (`d.model_type`) to ?all=1's version LIST (`v.model_type`, v = versions[0], the
    // same "latest" the old fetch always resolved) so the version picker + sampling_method +
    // capabilities can be shown too -- model_type capture itself is unchanged in spirit,
    // just reading from the new shape.
    assert.match(src,
      /setImgModel\(\(cur\) => \(cur && cur\.model_id === m\.model_id\) \? \{\s*\n\s*\.\.\.cur, version_id: v\.version_id \|\| "", model_type: v\.model_type \|\| "",/,
      "bindPicker must capture the base model's model_type from /api/model-version?all=1, " +
      "or loraIncompat has nothing real to compare a picked LoRA against");
  });

  test("each LoRA chip computes incompat via the (previously dead) imported loraIncompat()", () => {
    assert.match(src, /const incompat = loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\);/,
      "the LoRA chip list must call loraIncompat per-chip, using the base's model_type");
    assert.match(src, /className=\{"lv-lchip" \+ \(\(l\.failed \|\| incompat\) \? " failed" : ""\)\}/,
      "an incompatible chip must get the same visual warning treatment as a failed-to-resolve one");
  });

  test("the Generate button is disabled while any attached LoRA is incompatible with the selected base", () => {
    assert.match(src,
      /disabled=\{busyI \|\| anyLoraUnresolved\(imgLoras\) \|\| imgLoras\.some\(\(l\) => loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\)\) \|\| overLoraCap\(imgLoras, acct && acct\.lora_cap\)\}/,
      "Go must stay gated on incompatibility, not just unresolved -- an incompatible-but-" +
      "RESOLVED LoRA is still not safe to submit -- and now also on the account's real LoRA cap");
  });
});

describe("Image tab real per-account LoRA cap (mirrors the gallery's overLoraCap)", () => {
  test("a live cap indicator renders next to + add LoRA once acct.lora_cap is known", () => {
    assert.match(src,
      /\{acct && acct\.lora_cap != null && \(\s*\n\s*<span className=\{"lv-loracap" \+ \(overLoraCap\(imgLoras, acct\.lora_cap\) \? " over" : ""\)\}>/,
      "the indicator must stay hidden entirely (not show a false '0 / null') until a real " +
      "cap is known -- an unknown cap must never read as 'no limit'");
  });

  test("the Go button's label explains the real cap when exceeded, with correct singular/plural", () => {
    assert.match(src,
      /overLoraCap\(imgLoras, acct && acct\.lora_cap\) \? "remove " \+ \(imgLoras\.length - acct\.lora_cap\) \+ " LoRA" \+ \(\(imgLoras\.length - acct\.lora_cap\) === 1 \? "" : "s"\) \+ " to continue"/,
      "over-cap must tell the owner exactly how many to remove, not just refuse silently");
  });

  test("overLoraCap is imported from loom-mutations.js, not redefined locally", () => {
    assert.match(src, /loraIncompat, resolveLoraPayload, anyLoraUnresolved, overLoraCap,/);
  });
});

describe("Per-LoRA version selection (mirrors the base model's #gen-version/.lv-versel)", () => {
  test("a version <select> renders per-chip only when the LoRA has more than one release", () => {
    assert.match(src, /\{l\.versions && l\.versions\.length > 1 && \(/,
      "the common single-version case must render nothing extra, same as the base model's " +
      "own #gen-version wrapper");
    assert.match(src, /<select className="lv-lorver" value=\{l\.version_id \|\| ""\}/);
  });

  test("picking a different version applies its OWN version_id/lora_base_type/trigger_words, no new fetch", () => {
    assert.match(src,
      /setImgLoras\(\(cur\) => cur\.map\(\(x\) => x\.model_id === l\.model_id\s*\n\s*\? \{ \.\.\.x, version_id: v\.version_id \|\| "", lora_base_type: v\.lora_base_model_type \|\| "",/,
      "switching versions must update the SAME entry in imgLoras by model_id, using the " +
      "version's own fields -- the full version list already rode the entry from pick time");
  });
});

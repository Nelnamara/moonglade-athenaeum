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
      /setImgModel\(\(cur\) => cur \? \{\s*\n\s*\.\.\.cur, version_id: v\.version_id \|\| "", model_type: v\.model_type \|\| "",/,
      "bindPicker must capture the base model's model_type from /api/model-version?all=1, " +
      "or loraIncompat has nothing real to compare a picked LoRA against");
  });

  test("the version-resolve updater guards ONLY on the sequence counter, not a redundant model_id re-check", () => {
    // Owner report 2026-07-24: the version dropdown never appeared on the Loom for a model
    // confirmed (same model, same account) to show one on the Gallery. The extra
    // cur.model_id===m.model_id condition this updater used to carry, on top of the mySeq
    // guard, could silently drop a legitimate versions/compatibility/restrictions payload
    // for any reason imgModel changed mid-fetch that wasn't "a newer pick" -- the ONE thing
    // mySeq already exists to prevent, correctly. The Gallery's own onBasePick has never
    // had this second condition. Pin the simpler, matching shape so it can't regress back.
    assert.doesNotMatch(src, /cur && cur\.model_id === m\.model_id/,
      "no code path should re-check model_id equality here -- mySeq is the only guard needed");
    assert.match(src, /if \(mySeq !== imgModelSeqRef\.current\) return;/,
      "the sequence guard itself must stay -- it's what correctly rejects a stale response");
  });

  test("each LoRA chip computes incompat via the (previously dead) imported loraIncompat()", () => {
    assert.match(src, /const incompat = loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\);/,
      "the LoRA chip list must call loraIncompat per-chip, using the base's model_type");
    assert.match(src, /className=\{"lv-lchip" \+ \(\(l\.failed \|\| incompat\) \? " failed" : ""\)\}/,
      "an incompatible chip must get the same visual warning treatment as a failed-to-resolve one");
  });

  test("the Generate button is disabled while any attached LoRA is incompatible with the selected base", () => {
    // Asserted clause by clause rather than as one exact string. The guarantee is that
    // each of these gates is PRESENT on the Image tab's Go button; pinning the whole
    // expression verbatim also failed whenever a NEW gate was added beside them, which
    // is the opposite of what this test is for.
    const go = src.match(/disabled=\{busyI[^}]*\}/);
    assert.ok(go, "the Image tab's Go button must still carry a disabled={busyI ...} gate");
    const d = go[0];
    assert.match(d, /anyLoraUnresolved\(imgLoras\)/,
      "an unresolved LoRA must still gate Go");
    assert.match(d, /imgLoras\.some\(\(l\) => loraIncompat\(imgModel && imgModel\.model_type, l\.lora_base_type\)\)/,
      "Go must stay gated on incompatibility, not just unresolved -- an incompatible-but-" +
      "RESOLVED LoRA is still not safe to submit");
    assert.match(d, /overLoraCap\(imgLoras, acct && acct\.lora_cap\)/,
      "and on the account's real LoRA cap");
    assert.match(d, /!imgModel/,
      "and on a model being picked at all -- genImage() rejects without one, so offering " +
      "an enabled button is a dead-end click the sibling tabs never had");
    assert.match(d, /imgPrompt/,
      "and on a non-empty prompt, for the same reason");
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

describe("Image tab Advanced-panel capability gating (extra.compatibility, mirrors the Gallery's gateField())", () => {
  test("compatibility/restrictions ride imgModel from both resolve paths (initial pick + version switch)", () => {
    const matches = src.match(/compatibility: v\.compatibility \|\| \{\}, restrictions: v\.restrictions \|\| \{\},/g) || [];
    assert.equal(matches.length, 2,
      "both bindPicker's initial resolve AND pickVersion's switch must capture compatibility/restrictions -- " +
      "missing either one leaves the drawer showing stale gating after a version switch or the first pick");
  });

  test("a field is disabled ONLY on an explicit false -- unknown/absent compatibility fails open", () => {
    assert.match(src, /const negOff = compat\.negativePrompt === false;/);
    assert.match(src, /const stepsOff = compat\.samplingSteps === false;/);
    assert.match(src, /const cfgOff = compat\.cfgScale === false;/);
  });

  test("disabled fields carry the cap-off dimming class and an explanatory title, not silent removal", () => {
    assert.match(src, /disabled=\{negOff\} title=\{negOff \? offTitle : ""\}/);
    assert.match(src, /disabled=\{stepsOff\} title=\{stepsOff \? offTitle : ""\}/);
    assert.match(src, /disabled=\{cfgOff\} title=\{cfgOff \? offTitle : ""\}/);
    assert.match(src, /\.cap-off\{opacity:\.4;cursor:not-allowed;\}/);
  });

  test("restrictions clamp the field's own hardcoded min/max when the model publishes tighter bounds", () => {
    assert.match(src, /min=\{stepsB\.min != null \? stepsB\.min : 1\} max=\{stepsB\.max != null \? stepsB\.max : 150\}/);
    assert.match(src, /min=\{cfgB\.min != null \? cfgB\.min : 1\} max=\{cfgB\.max != null \? cfgB\.max : 30\}/);
  });
});

describe("Picker: don't search the hidden tab on open (owner report 2026-07-24, \"still slow\")", () => {
  test("both picker elements are captured in refs the ensureSearched effect can reach later", () => {
    assert.match(src, /const basePickerElRef = useRef\(null\);/);
    assert.match(src, /const loraPickerElRef = useRef\(null\);/);
    assert.match(src, /basePickerElRef\.current = el;\s*\n\s*if \(el && !el\._mgBound\) \{/,
      "must be set unconditionally on every callback invocation, not only the first bind, " +
      "or the ref goes stale across a remount");
    assert.match(src, /loraPickerElRef\.current = el;\s*\n\s*if \(el && !el\._mgBound\) \{/);
  });

  test("an effect calls ensureSearched() on whichever picker is visible whenever the mounted tab changes", () => {
    assert.match(src,
      /useEffect\(\(\) => \{\s*\n\s*if \(!pickerMounted\) return;\s*\n\s*const vis = pickerKind === "base" \? basePickerElRef\.current : loraPickerElRef\.current;\s*\n\s*if \(vis && vis\.ensureSearched\) vis\.ensureSearched\(\);\s*\n\s*\}, \[pickerMounted, pickerKind\]\);/,
      "must key on [pickerMounted, pickerKind] -- the hidden tab needs its OWN search the " +
      "moment it's revealed, not just once on initial mount");
  });
});

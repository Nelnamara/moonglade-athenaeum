import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard: the LoRA picker show/hide toggle (D-11, next to the second
// <mg-model-picker kind="lora">) shipped with a bespoke one-off class,
// `.lv-loratoggle`, whose declared chrome (9px text, background matching the panel
// base, a border the same color as every other surface1 hairline) reads as plain
// link text rather than a control -- the owner's own words: "TINY and unformatted
// web wink text." Every other small toggle/status control in this same shell reuses
// one of a handful of established classes (`.lv-chip` for the Video tab's
// Continuity/Mode toggle chips, `.lv-draft` for the top-strip Draft toggle,
// `.lv-st` for status badges, `.lv-routebtn`/`.lv-mini2` for other small buttons) --
// the toggle should reuse one of those instead of inventing its own under-styled
// rule. Same technique as the suite's other guards over the JSX
// (loom-picker-video-import.test.js, loom-v2-dead-generate-shot-prop.test.js):
// source-presence assertions, no jsdom.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

// The established small-button/chip classes actually defined and used elsewhere in
// this same shell -- see the neighboring Draft toggle (.lv-draft), .lv-st status
// badges, and the Video tab's .lv-chip toggle chips.
const KNOWN_CONTROL_CLASSES = ["lv-chip", "lv-draft", "lv-mini2", "lv-routebtn", "lv-tab"];

describe("LoRA picker show/hide toggle carries real control chrome", () => {
  test("the toggle button's className reuses an existing small-button/chip class", () => {
    // Grab the LoRA toggle button itself, not any other className in the file.
    const btnMatch = storyboardSrc.match(
      /<button[^>]*className=\{?"([^"{]*)"?\}?[^>]*onClick=\{\(\) => setLoraOpen/
    );
    assert.ok(btnMatch, "could not locate the LoRA picker's show/hide <button> " +
      "(onClick={() => setLoraOpen...}) in master-storyboard.jsx -- has it moved or " +
      "been renamed?");
    const classAttr = btnMatch[1];
    const classes = classAttr.split(/\s+/).filter(Boolean);
    const reusesKnownControl = classes.some((c) => KNOWN_CONTROL_CLASSES.includes(c));
    assert.ok(reusesKnownControl,
      `the LoRA toggle's className ("${classAttr}") does not include any of the ` +
      `shell's established small-button/chip classes (${KNOWN_CONTROL_CLASSES.join(", ")}) -- ` +
      "it is styled by a bespoke one-off rule instead of reading as a native control.");
  });

  test("no bespoke .lv-loratoggle rule reintroduces its own under-styled button chrome", () => {
    // The fix removes (or reduces to a pure layout/spacing override, never its own
    // background+border+color+font declarations) the one-off rule that made the
    // toggle look like plain link text. Guard against a future edit quietly
    // reinstating a full custom button skin under this name.
    const ruleMatch = storyboardSrc.match(/\.lv-loratoggle\s*\{([^}]*)\}/);
    if (!ruleMatch) return; // rule removed entirely -- passes
    const body = ruleMatch[1];
    assert.doesNotMatch(body, /background\s*:/,
      ".lv-loratoggle must not declare its own background -- that re-creates the " +
      "under-styled one-off skin instead of relying on a reused chip/button class");
    assert.doesNotMatch(body, /border\s*:/,
      ".lv-loratoggle must not declare its own border -- that re-creates the " +
      "under-styled one-off skin instead of relying on a reused chip/button class");
  });
});

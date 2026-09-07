import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { MODES, modeAfterApply, modeOffered } from "../../gallery/src/gen/genCore.js";

/* THE TUNING BARS DIM FOR A MODE THE MODEL DOES NOT OFFER (SCOPE 2026-08-17 §4b).

   The five bars are a fixed list in genCore.js; the real allowed set is per model VERSION
   and arrives as `model.profiles` (PROBE 2026-08-25: Tsubaki.2 offers lite/standard/pro/
   ultra, Tsubaki.3 only pro/ultra). Before this every bar was always clickable, so you
   could pick a mode the model rejects -- the submit then dropped the profile and re-ran on
   the model's own default, which is not the tier the cost badge quoted.

   Two things are pinned here. The LOGIC (modeOffered, imported and exercised directly) and
   the WIRING (a source read of GenerateDrawer.jsx): the drawer has no test harness that can
   render it, so the only guard that the gate is actually attached to the bars -- as
   `disabled`, which dims in place, and never as a filter that would REMOVE a bar -- is that
   the JSX still says so. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read: the repo stores LF, Windows checks out CRLF.
const drawer = readFileSync(
  path.resolve(__dirname, "../../gallery/src/components/GenerateDrawer.jsx"), "utf8",
).replace(/\r\n/g, "\n");
const hook = readFileSync(
  path.resolve(__dirname, "../../gallery/src/gen/useGenerate.js"), "utf8",
).replace(/\r\n/g, "\n");
const phone = readFileSync(
  path.resolve(__dirname, "../../gallery/src/components/CreateMobile.jsx"), "utf8",
).replace(/\r\n/g, "\n");

/** The `<div className="mgdock-modebars">…</div>` block, bars and all. */
function modebarsBlock() {
  const i = drawer.indexOf('className="mgdock-modebars"');
  assert.ok(i > 0, "GenerateDrawer.jsx no longer has a .mgdock-modebars block");
  const j = drawer.indexOf("</div>", i);
  assert.ok(j > i, ".mgdock-modebars block is not closed");
  return drawer.slice(i, j);
}

/** The phone Create tab's Mode chip row -- from its `Mode` label to the row's close. */
function phoneModeBlock() {
  const i = phone.indexOf('<div className="cm-lbl">Mode</div>');
  assert.ok(i > 0, "CreateMobile.jsx no longer has a Mode chip row");
  const j = phone.indexOf("GEN_MODES.map(", i);
  assert.ok(j > i, "CreateMobile.jsx's Mode row no longer maps GEN_MODES");
  const k = phone.indexOf("</div>", phone.indexOf("</button>", j));
  assert.ok(k > j, "CreateMobile.jsx's Mode chip row is not closed");
  return phone.slice(i, k);
}

describe("modeOffered fails open on every uncertain input", () => {
  const TSUBAKI2 = ["lite", "standard", "pro", "ultra"];
  const TSUBAKI3 = ["pro", "ultra"];

  test("auto is offered by every model, whatever the profile set says", () => {
    for (const p of [TSUBAKI3, [], null, undefined, ["pro"], ["nonsense"]]) {
      assert.equal(modeOffered("auto", p), true);
    }
  });

  test("a profile the model lists is offered; one it does not is not", () => {
    assert.equal(modeOffered("lite", TSUBAKI2), true);
    assert.equal(modeOffered("ultra", TSUBAKI2), true);   // membershipOnly stays OFFERED
    assert.equal(modeOffered("lite", TSUBAKI3), false);
    assert.equal(modeOffered("standard", TSUBAKI3), false);
    assert.equal(modeOffered("pro", TSUBAKI3), true);
  });

  test("an unknown profile set (null) dims nothing", () => {
    for (const [v] of MODES) assert.equal(modeOffered(v, null), true);
    for (const [v] of MODES) assert.equal(modeOffered(v, undefined), true);
  });

  test("an empty list -- SDXL's definitive answer -- also dims nothing", () => {
    for (const [v] of MODES) assert.equal(modeOffered(v, []), true);
  });

  test("a non-array (a malformed server answer) dims nothing", () => {
    for (const p of ["pro", 7, {}, { profiles: ["pro"] }]) {
      for (const [v] of MODES) assert.equal(modeOffered(v, p), true);
    }
  });

  test("matching is case-insensitive on both sides", () => {
    assert.equal(modeOffered("pro", ["PRO"]), true);
    assert.equal(modeOffered("Ultra", ["ultra"]), true);
  });
});

describe("the drawer's mode bars carry the gate", () => {
  test("every bar is still rendered -- the gate dims, it does not filter", () => {
    const block = modebarsBlock();
    assert.match(block, /MODES\.map\(/, "the bars no longer map the full MODES list");
    assert.doesNotMatch(block, /MODES\s*\n?\s*\.filter\(|MODES\.filter\(/,
      "the bars are being FILTERED -- an unavailable mode must dim, not disappear");
  });

  test("the disabled gate is keyed on the model's profiles", () => {
    const block = modebarsBlock();
    assert.match(block, /modeOffered\(\s*v\s*,\s*m\s*&&\s*m\.profiles\s*\)/,
      "the bars no longer ask modeOffered about the selected model's `profiles`");
    assert.match(block, /disabled=\{/,
      "the bars no longer carry a `disabled` attribute");
    assert.match(block, /title=\{[^}]*Not offered for this model/,
      "a dimmed bar no longer says why it is dimmed");
  });

  test("modeOffered is imported from genCore, not re-implemented in the drawer", () => {
    assert.match(drawer, /import\s*\{[^}]*\bmodeOffered\b[^}]*\}\s*from\s*"\.\.\/gen\/genCore\.js"/,
      "GenerateDrawer.jsx no longer imports modeOffered from genCore.js");
  });

  test("auto is never the mode that gets disabled", () => {
    // Belt and braces on the two halves together: whatever the drawer passes, the first
    // bar (auto) can never come back false.
    assert.equal(MODES[0][0], "auto", "auto is no longer the first mode bar");
    assert.equal(modeOffered(MODES[0][0], ["pro"]), true);
  });
});

/* THE SELECTED MODE IS RE-CHECKED WHEN A MODEL APPLIES (red team 2026-09-07).

   Dimming a bar governs the next CLICK only. Pick Ultra on a model that offers it, switch to a
   model whose profiles are ["pro"], and the first cut left `mode: "ultra"` selected: buildPayload
   still sent it, /api/price still quoted that tier, and the submit was rejected and silently
   re-run on the model's own default -- the quote-vs-charge divergence this whole feature exists
   to close, reached by a model switch instead of a click. genCore.modeAfterApply is the rule;
   useGenerate applies it at BOTH seams where a version lands (applyModelRow for a new model,
   pickVersion for another version of the same one). */
describe("a mode the newly applied model does not offer falls back to auto", () => {
  test("the brief's case: profiles [pro, ultra] while the mode is lite yields auto", () => {
    assert.equal(modeAfterApply("lite", ["pro", "ultra"]), "auto");
  });

  test("every mode the new model does not offer lands on auto, never on another paid tier", () => {
    for (const m of ["lite", "standard"]) assert.equal(modeAfterApply(m, ["pro", "ultra"]), "auto");
    for (const m of ["lite", "standard", "ultra"]) assert.equal(modeAfterApply(m, ["pro"]), "auto");
    assert.equal(modeAfterApply("ultra", ["pro"]), "auto");
  });

  test("a mode the new model DOES offer is left exactly as it was", () => {
    assert.equal(modeAfterApply("pro", ["pro", "ultra"]), "pro");
    assert.equal(modeAfterApply("ultra", ["lite", "standard", "pro", "ultra"]), "ultra");
    assert.equal(modeAfterApply("auto", ["pro"]), "auto");
  });

  test("it fails open on an unknown or empty profile set, exactly like modeOffered", () => {
    for (const p of [null, undefined, [], "pro", 7, {}]) {
      for (const [v] of MODES) assert.equal(modeAfterApply(v, p), v);
    }
  });

  test("the rule is genCore's -- there is no second copy in the hook", () => {
    assert.match(hook, /import\s*\{[^}]*\bmodeAfterApply\b[^}]*\}\s*from\s*"\.\/genCore\.js"/,
      "useGenerate.js no longer imports modeAfterApply from genCore.js");
    assert.doesNotMatch(hook, /function\s+modeAfterApply|const\s+modeAfterApply\s*=/,
      "useGenerate.js re-implements modeAfterApply instead of using genCore's");
  });

  test("BOTH apply seams reset the mode -- a new model AND another version of one", () => {
    // applyModelRow (a fresh model pick) and pickVersion (the version dropdown) are the two
    // places a profile set changes underneath an already-selected mode. Neither may be left out.
    const uses = hook.match(/mode:\s*modeAfterApply\(\s*old\.mode\s*,\s*model\.profiles\s*\)/g) || [];
    assert.equal(uses.length, 2,
      "expected the mode reset at BOTH useGenerate apply seams (applyModelRow, pickVersion); found "
      + uses.length);
  });
});

/* THE PHONE CARRIES THE SAME GATE (red team 2026-09-07).

   The dimming shipped for the dock only, and the phone's Create tab maps the identical
   MODES list to fully clickable chips -- with the model meta already in hand (it gates
   steps/CFG/upscale/negative off the same `m` two rows down) and no submit-time clamp
   anywhere, so the UI dim was the ONLY guard and it was missing on one of the two surfaces.
   Same gate, same wording, one shared modeOffered. */
describe("the phone Create tab's mode chips carry the same gate", () => {
  test("every chip is still rendered -- the gate dims, it does not filter", () => {
    const block = phoneModeBlock();
    assert.match(block, /GEN_MODES\.map\(/, "the chips no longer map the full MODES list");
    assert.doesNotMatch(block, /GEN_MODES\s*\n?\s*\.filter\(/,
      "the chips are being FILTERED -- an unavailable mode must dim, not disappear");
  });

  test("the disabled gate is keyed on the model's profiles, with the same title", () => {
    const block = phoneModeBlock();
    assert.match(block, /modeOffered\(\s*v\s*,\s*m\s*&&\s*m\.profiles\s*\)/,
      "the chips no longer ask modeOffered about the selected model's `profiles`");
    assert.match(block, /disabled=\{/, "the chips no longer carry a `disabled` attribute");
    assert.match(block, /title=\{[^}]*Not offered for this model/,
      "a dimmed chip no longer says why it is dimmed, or no longer says it the dock's way");
  });

  test("modeOffered is imported from genCore, not re-implemented on the phone", () => {
    assert.match(phone, /import\s*\{[\s\S]*?\bmodeOffered\b[\s\S]*?\}\s*from\s*"\.\.\/gen\/genCore\.js"/,
      "CreateMobile.jsx no longer imports modeOffered from genCore.js");
    assert.doesNotMatch(phone, /function\s+modeOffered|const\s+modeOffered\s*=/,
      "CreateMobile.jsx re-implements modeOffered instead of using genCore's");
  });

  test("the dock and the phone gate on the SAME expression and the same words", () => {
    // Two renderers, one rule. If either surface starts asking a different question -- or
    // says something different when it refuses -- this is where it shows up.
    const gate = /modeOffered\(\s*v\s*,\s*m\s*&&\s*m\.profiles\s*\)/;
    const dockGate = modebarsBlock().match(gate);
    const phoneGate = phoneModeBlock().match(gate);
    assert.ok(dockGate && phoneGate, "one of the two surfaces no longer carries the gate");
    assert.equal(dockGate[0].replace(/\s+/g, ""), phoneGate[0].replace(/\s+/g, ""));
    const title = /title=\{[^}]*"Not offered for this model"/;
    assert.match(modebarsBlock(), title, "the dock's dimmed-bar wording changed");
    assert.match(phoneModeBlock(), title, "the phone's dimmed-chip wording changed");
  });
});

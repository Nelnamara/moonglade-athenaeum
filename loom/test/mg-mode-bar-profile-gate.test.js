import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  GEN_DEFAULTS, MODES, modeAfterApply, modeOffered, modeOnVersion, versionPatch,
} from "../../gallery/src/gen/genCore.js";
import { render, query, one } from "../test-support/render.mjs";

/* THE TUNING BARS DIM FOR A MODE THE MODEL DOES NOT OFFER (SCOPE 2026-08-17 §4b).

   The five bars are a fixed list in genCore.js; the real allowed set is per model VERSION and
   arrives as `model.profiles` (PROBE 2026-08-25: Tsubaki.2 offers lite/standard/pro/
   ultra, Tsubaki.3 only pro/ultra). Before this every bar was always clickable, so you
   could pick a mode the model rejects -- the submit then dropped the profile and re-ran on
   the model's own default, which is not the tier the cost badge quoted.

   Two things are pinned here. The LOGIC (modeOffered, imported and exercised directly) and
   the WIRING, by RENDERING the two surfaces that draw the bars (loom/test-support/render.mjs):
   the dock's ModeBars (GenerateDrawer.jsx) and the phone's Create -> Advanced fields
   (CreateMobile.jsx ImageAdvanced), each given a selected model, and read back as markup --
   every bar still drawn, the ones the model does not offer `disabled` with the reason as their
   title. A dimmed bar is the only guard on the click; a filtered-away bar would hide the tier.
   One hop is NOT rendered: that the drawer's TUNING slab mounts ModeBars with its live s/set.
   GenerateDrawer itself is not statically renderable (it reaches `document`), so that hop is a
   source pin on the mount line. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read: the repo stores LF, Windows checks out CRLF.
const read = (rel) => readFileSync(path.resolve(__dirname, "../..", rel), "utf8").replace(/\r\n/g, "\n");
const drawer = read("gallery/src/components/GenerateDrawer.jsx");
const hook = read("gallery/src/gen/useGenerate.js");
const phone = read("gallery/src/components/CreateMobile.jsx");

const DRAWER = "gallery/src/components/GenerateDrawer.jsx";
const PHONE = "gallery/src/components/CreateMobile.jsx";
const NOT_OFFERED = "Not offered for this model";
const LABELS = MODES.map(([, l]) => l);
const TSUBAKI2 = ["lite", "standard", "pro", "ultra"];
const TSUBAKI3 = ["pro", "ultra"];

/** A selected model as the dock keeps it on s.model: a version row run through versionPatch. */
const modelWith = (profiles) => ({
  model_id: "m1", title: "Model", thumb: "", version_id: "v1", model_type: "SDXL_MODEL",
  ...versionPatch({ version_id: "v1", profiles }),
});

const bar = (b) => ({ disabled: b.attr("disabled") !== undefined, title: b.attr("title") });

/** The dock's TUNING mode bars as rendered for the selected model `m`, one entry per bar. */
async function dockBars(m) {
  const $ = query(await render(DRAWER, "ModeBars", { s: { ...GEN_DEFAULTS, model: m }, set() {} }));
  const row = one($.byClass("mgdock-modebars"), "dock mode-bar row");
  return row.byTag("button").map((b) => ({ ...bar(b), isBar: b.hasClass("mgdock-modebar") }));
}

/** The phone Create tab's Mode chips (Create -> Advanced) as rendered for `m`, one per chip. */
async function phoneChips(m) {
  const $ = query(await render(PHONE, "ImageAdvanced",
    { s: { ...GEN_DEFAULTS, model: m }, set() {}, setLora() {}, m, power: null }));
  const label = one($.find((e) => e.hasClass("cm-lbl") && e.text === "Mode"), "Mode label");
  const siblings = label.parent.children.filter((c) => typeof c !== "string");
  const row = siblings[siblings.indexOf(label) + 1];
  assert.ok(row && row.hasClass("cm-chiprow"), "the phone's Mode label is no longer followed by its chip row");
  return row.byTag("button").map((b) => ({ ...bar(b), text: b.text }));
}

describe("modeOffered fails open on every uncertain input", () => {
  test("auto is offered by every model, whatever the profile set says", () => {
    // The first bar is auto: the gate can never dim it, so it must stay the first bar.
    assert.equal(MODES[0][0], "auto", "auto is no longer the first mode bar");
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
  test("every bar is still rendered -- the gate dims, it does not filter", async () => {
    // A model offering ONE profile is the hardest case: four of five bars are dimmed, and all
    // five must still be drawn, in MODES order.
    for (const profiles of [["pro"], TSUBAKI3, TSUBAKI2]) {
      const bars = await dockBars(modelWith(profiles));
      assert.equal(bars.length, MODES.length,
        "the dock draws " + bars.length + " bars for " + JSON.stringify(profiles)
        + " -- an unavailable mode must dim, not disappear");
      assert.ok(bars.every((b) => b.isBar), "every bar keeps its .mgdock-modebar face");
    }
    const single = await dockBars(modelWith(["pro"]));
    assert.deepEqual(single.map((b) => b.disabled), [false, true, true, false, true]);
  });

  test("the disabled gate is keyed on the model's profiles", async () => {
    const t3 = await dockBars(modelWith(TSUBAKI3));
    assert.deepEqual(t3.map((b) => b.disabled), [false, true, true, false, false],
      "on Tsubaki.3 (pro/ultra) exactly Lite and Standard are dimmed");
    assert.deepEqual(t3.map((b) => b.title), ["Auto", NOT_OFFERED, NOT_OFFERED, "Pro", "Ultra"],
      "a dimmed bar says why it is dimmed; an offered one names its mode");
    // The same bars on another profile set: the gate follows the model, not a fixed list.
    const t2 = await dockBars(modelWith(TSUBAKI2));
    assert.deepEqual(t2.map((b) => b.disabled), [false, false, false, false, false]);
    assert.deepEqual(t2.map((b) => b.title), LABELS);
    // Fails open: no model yet, or a model whose profile set is unknown, dims nothing.
    for (const m of [null, modelWith(null)]) {
      assert.deepEqual((await dockBars(m)).map((b) => b.disabled), [false, false, false, false, false]);
    }
  });

  test("modeOffered is imported from genCore, not re-implemented in the drawer", () => {
    assert.match(drawer, /import\s*\{[^}]*\bmodeOffered\b[^}]*\}\s*from\s*"\.\.\/gen\/genCore\.js"/,
      "GenerateDrawer.jsx no longer imports modeOffered from genCore.js");
  });

  test("the drawer mounts ModeBars with its live s/set", () => {
    // Text, not a render: the tests above render ModeBars by name, which proves the bars but not
    // that the TUNING slab draws them. GenerateDrawer cannot be rendered in node (it reaches
    // `document`), so the drawer -> ModeBars hop is pinned on its mount line.
    assert.match(drawer, /<ModeBars\s+s=\{s\}\s+set=\{set\}\s*\/>/,
      "GenerateDrawer.jsx no longer mounts ModeBars with the live s/set");
  });
});

/* THE SELECTED MODE IS RE-CHECKED WHEN A MODEL APPLIES (red team 2026-09-07).

   Dimming a bar governs the next CLICK only. Pick Ultra on a model that offers it, switch to a
   model whose profiles are ["pro"], and the first cut left `mode: "ultra"` selected: buildPayload
   still sent it, /api/price still quoted that tier, and the submit was rejected and silently
   re-run on the model's own default -- the quote-vs-charge divergence this whole feature exists
   to close, reached by a model switch instead of a click. genCore.modeAfterApply is the rule;
   genCore.modeOnVersion adds Session H's members-only drop to it, and useGenerate applies that
   at EVERY seam where a mode meets a model: applyModelRow (a new model), pickVersion (another
   version of the same one) and restoreComposer (a saved mode onto the model now selected). */
describe("a mode the newly applied model does not offer falls back to auto", () => {
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
    assert.match(hook, /import\s*\{[^}]*\bmodeOnVersion\b[^}]*\}\s*from\s*"\.\/genCore\.js"/,
      "useGenerate.js no longer imports modeOnVersion from genCore.js");
    for (const fn of ["modeAfterApply", "rowSafeMode", "modeOnVersion"]) {
      assert.doesNotMatch(hook, new RegExp("function\\s+" + fn + "\\b|const\\s+" + fn + "\\s*="),
        "useGenerate.js re-implements " + fn + " instead of using genCore's");
    }
  });

  test("BOTH apply seams reset the mode -- a new model AND another version of one", () => {
    // The step itself, on the model each seam builds. A version row goes through versionPatch,
    // exactly as useGenerate builds s.model, so `profiles` arrives the way it does live.
    const T2_ROW = { version_id: "t2", model_type: "SDXL_MODEL", profiles: TSUBAKI2 };
    const T3_ROW = { version_id: "t3", model_type: "SDXL_MODEL", profiles: TSUBAKI3 };
    const base = { model_id: "m1", title: "Tsubaki", thumb: "", versions: [T2_ROW, T3_ROW] };
    const landed = (row) => ({ ...base, version_id: row.version_id, model_type: row.model_type, ...versionPatch(row) });

    // applyModelRow: a NEW model lands on its latest version.
    const fresh = landed(T3_ROW);
    for (const mode of ["lite", "standard"]) assert.equal(modeOnVersion(mode, fresh, null), "auto", mode);
    for (const mode of ["auto", "pro", "ultra"]) assert.equal(modeOnVersion(mode, fresh, null), mode, mode);

    // pickVersion: ANOTHER VERSION of the model already applied (Tsubaki.2 -> .3 is one model,
    // two profile sets). Lite stands on .2 and drops to auto on .3, never onto another tier.
    assert.equal(modeOnVersion("lite", landed(T2_ROW), null), "lite");
    assert.equal(modeOnVersion("lite", landed(T3_ROW), null), "auto");
    assert.equal(modeOnVersion("standard", landed(T3_ROW), true), "auto");

    // Unknown profiles fail open; a members-only row drops to auto for a known non-member only.
    for (const [v] of MODES) assert.equal(modeOnVersion(v, landed({ version_id: "x" }), null), v);
    const rows = landed({ ...T3_ROW, profile_rows: [{ name: "pro", flag: "default" }, { name: "ultra", flag: "membershipOnly" }] });
    assert.equal(modeOnVersion("ultra", rows, false), "auto");
    assert.equal(modeOnVersion("ultra", rows, true), "ultra");
    assert.equal(modeOnVersion("ultra", rows, null), "ultra");

    // The wiring: no harness can call the hook's callbacks (a static render runs none), so the
    // two seams are read from source -- each must hand its NEW model to that one step.
    const seam = (from, to) => {
      const a = hook.indexOf(from), b = hook.indexOf(to, a + 1);
      assert.ok(a > 0 && b > a, "useGenerate.js no longer has the seam " + from);
      return hook.slice(a, b);
    };
    const call = /mode:\s*modeOnVersion\(\s*old\.mode\s*,\s*model\s*,\s*old\.member\s*\)/g;
    for (const [name, body] of [
      ["applyModelRow", seam("const applyModelRow = useCallback(", "const pickVersion = useCallback(")],
      ["pickVersion", seam("const pickVersion = useCallback(", "}, []);")],
    ]) {
      assert.equal((body.match(call) || []).length, 1,
        name + " no longer resets the mode through genCore.modeOnVersion when a version lands");
    }
    // restoreComposer: a saved mode lands on the model selected NOW (the snapshot's own model
    // may be gone, or another version of it), so it runs the same step on old.model.
    const restore = seam("const restoreComposer = useCallback(", "const restoreLast = useCallback(");
    assert.equal((restore.match(/mode:\s*modeOnVersion\(\s*snap\.mode\s*,\s*old\.model\s*,\s*old\.member\s*\)/g) || []).length, 1,
      "restoreComposer no longer resets a restored mode through genCore.modeOnVersion");
  });
});

/* THE PHONE CARRIES THE SAME GATE (red team 2026-09-07).

   The dimming shipped for the dock only, and the phone's Create tab maps the identical
   MODES list to fully clickable chips -- with the model meta already in hand (it gates
   steps/CFG/upscale/negative off the same `m` two rows down) and no submit-time clamp
   anywhere, so the UI dim was the ONLY guard and it was missing on one of the two surfaces.
   Same gate, same wording, one shared modeOffered. */
describe("the phone Create tab's mode chips carry the same gate", () => {
  test("every chip is still rendered -- the gate dims, it does not filter", async () => {
    for (const profiles of [["pro"], TSUBAKI3, TSUBAKI2]) {
      const chips = await phoneChips(modelWith(profiles));
      assert.deepEqual(chips.map((c) => c.text), LABELS,
        "the phone's Mode row for " + JSON.stringify(profiles)
        + " is not every mode in order -- an unavailable mode must dim, not disappear");
    }
  });

  test("the disabled gate is keyed on the model's profiles, with the same title", async () => {
    const t3 = await phoneChips(modelWith(TSUBAKI3));
    assert.deepEqual(t3.map((c) => c.disabled), [false, true, true, false, false],
      "on Tsubaki.3 (pro/ultra) exactly Lite and Standard are dimmed");
    assert.deepEqual(t3.map((c) => c.title), ["Auto", NOT_OFFERED, NOT_OFFERED, "Pro", "Ultra"],
      "a dimmed chip no longer says why it is dimmed, or no longer says it the dock's way");
    const t2 = await phoneChips(modelWith(TSUBAKI2));
    assert.deepEqual(t2.map((c) => c.disabled), [false, false, false, false, false]);
    for (const m of [null, modelWith(null)]) {
      assert.deepEqual((await phoneChips(m)).map((c) => c.disabled), [false, false, false, false, false]);
    }
  });

  test("modeOffered is imported from genCore, not re-implemented on the phone", () => {
    assert.match(phone, /import\s*\{[\s\S]*?\bmodeOffered\b[\s\S]*?\}\s*from\s*"\.\.\/gen\/genCore\.js"/,
      "CreateMobile.jsx no longer imports modeOffered from genCore.js");
    assert.doesNotMatch(phone, /function\s+modeOffered|const\s+modeOffered\s*=/,
      "CreateMobile.jsx re-implements modeOffered instead of using genCore's");
  });

  test("the dock and the phone gate on the SAME expression and the same words", async () => {
    // Two renderers, one rule. Render both for the same model and compare what each draws: if
    // either surface starts asking a different question -- or says something different when it
    // refuses -- this is where it shows up.
    let refusals = 0;
    const malformed = { ...modelWith(null), profiles: "pro" };   // a non-array, past versionPatch
    for (const m of [null, malformed, ...[TSUBAKI2, TSUBAKI3, ["pro"], ["PRO"], ["ultra"], [], null].map(modelWith)]) {
      const what = JSON.stringify(m && m.profiles);
      const dock = (await dockBars(m)).map(({ disabled, title }) => ({ disabled, title }));
      const chips = (await phoneChips(m)).map(({ disabled, title }) => ({ disabled, title }));
      assert.deepEqual(chips, dock, "the phone and the dock disagree for profiles " + what);
      assert.deepEqual(dock.map((b) => b.disabled), MODES.map(([v]) => !modeOffered(v, m && m.profiles)),
        "the bars no longer follow modeOffered for profiles " + what);
      refusals += dock.filter((b) => b.title === NOT_OFFERED).length;
    }
    assert.ok(refusals > 0, "no case above dimmed a bar, so the comparison proved nothing");
  });
});

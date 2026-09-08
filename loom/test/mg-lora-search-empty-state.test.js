import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// When a LoRA search comes back with nothing and a BASE filter is on, the empty line has to say
// so (owner walk, 2026-09-07: "searching for a known LoRA fails").
//
// WHAT WAS WRONG. Two different things came back as one sentence. The server half of that walk
// was the feed -- a keyword went to the trending RANKING instead of the search index, so a real
// LoRA could be missing from a list that was never a search (fixed in moonglade_backup.py,
// pinned by tests/test_model_grid.py). This is the other half: even with the search working, a
// base filter narrows a LoRA search server-side, so "Perfect Hands" under a DiT.2 base can
// legitimately match nothing while the same term matches plenty with the filter off. "No results
// — try another search." sends you to change the one thing that was already right, and never
// mentions the filter that is actually hiding the match.
//
// The base's name comes from archLabel -- the SAME helper the cards' ⚠ badge and their
// "needs <arch>" line use -- so the sentence and the grid can never call one base two names.
//
// The component cannot be rendered here (no browser, no JSX transform in the node test runner),
// so the string builders are lifted out of the source and run for real, in the style of
// med4-mode-aware-panel.test.js. The wiring around them is a source-presence guard.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; the patterns assume LF

/** A top-level `function name(...) { ... }` declaration, whole. */
function extractFn(name) {
  const m = jsx.match(new RegExp("\\nfunction " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}"));
  assert.ok(m, `expected a top-level function ${name}() in ModelPicker.jsx -- if it moved, update this pattern`);
  return m[0];
}

/** A `const name = ...;` at the component's 2-space indent, however many lines it spans. */
function extractConst(name) {
  const m = jsx.match(new RegExp("\\n  const " + name + " = [\\s\\S]*?;(?=\\n)"));
  assert.ok(m, `expected "const ${name} = " at the component's indent in ModelPicker.jsx`);
  return m[0];
}

const build = new Function("kind", "baseType", "qDebounced", `
  ${extractFn("tyShort")}
  ${extractFn("baseLabel")}
  ${extractFn("archLabel")}
  ${extractConst("baseFilterLabel")}
  ${extractConst("emptyLine")}
  return { baseFilterLabel, emptyLine };
`);

const GENERIC = "No results — try another search.";

describe("the LoRA picker's empty line names the base filter when one is on", () => {
  test("a name search that finds nothing says so, and never blames the base", () => {
    // Since 2026-09-07 a name search is NOT base-filtered (a match the base cannot run shows
    // greyed with what it needs), so an empty result means the words matched nothing.
    for (const bt of ["MMDIT26A_MODEL", ""]) {
      const { emptyLine } = build("lora", bt, "Perfect Hands");
      assert.equal(emptyLine, "No LoRAs match “Perfect Hands” — try other words.");
      assert.doesNotMatch(emptyLine, /pick another base|clear the search/, "that advice would be wrong now");
    }
  });

  test("the base is named in archLabel's words, the same ones the cards use", () => {
    // The cards' ⚠ badge and "needs <arch>" both render archLabel(m, kind); a row whose
    // lora_base_model_type is the filtered base must therefore read the same as the sentence.
    const arch = new Function("m", "kind", `
      ${extractFn("tyShort")}
      ${extractFn("baseLabel")}
      ${extractFn("archLabel")}
      return archLabel(m, kind);
    `);
    for (const bt of ["MMDIT26A_MODEL", "SDXL_MODEL", "SD_V1_MODEL", "DIT7_MODEL"]) {
      const { baseFilterLabel } = build("lora", bt, "eyes");
      assert.equal(baseFilterLabel, arch({ lora_base_model_type: bt }, "lora"), bt);
      assert.ok(baseFilterLabel, "every whitelisted base must produce a label, never an empty one");
    }
    // and it is genuinely archLabel doing it, not a second table that can drift
    assert.match(extractConst("baseFilterLabel"), /archLabel\(/);
  });

  test("a browse with no search term is still base-filtered, and its empty line says so", () => {
    // an empty grid with an empty search box under a base filter is the filter's doing
    const browse = build("lora", "MMDIT26A_MODEL", "").emptyLine;
    assert.match(browse, /^No LoRAs for MMDiT here/);
    assert.match(browse, /pick another base or search by name/);
    // no base picked and nothing typed: the generic line
    assert.equal(build("lora", "", "").emptyLine, GENERIC);
  });

  test("the base picker never claims a base filter -- base_type is a LoRA concept", () => {
    // the route ignores base_type for kind=base, so the sentence must not invent one
    assert.equal(build("base", "MMDIT26A_MODEL", "Tsubaki").emptyLine, GENERIC);
    assert.equal(build("base", "MMDIT26A_MODEL", "Tsubaki").baseFilterLabel, "");
  });

  test("the empty <div> renders the computed line, and the old literal is gone from the JSX", () => {
    assert.match(jsx, /className="mg-empty" style=\{\{ display: "block" \}\}>\{emptyLine\}</);
    // exactly one place still spells the generic sentence: the fallback arm of emptyLine
    assert.equal((jsx.match(/No results — try another search\./g) || []).length, 1);
  });
});

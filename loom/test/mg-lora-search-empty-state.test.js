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
  test("a keyword search under a base filter says which base, and offers both ways out", () => {
    const { emptyLine } = build("lora", "MMDIT26A_MODEL", "Perfect Hands");
    assert.equal(emptyLine,
      "No LoRAs for MMDiT match “Perfect Hands” — clear the search or pick another base.");
    // both escape routes are named: the search is one of the two things narrowing the list
    assert.match(emptyLine, /clear the search/);
    assert.match(emptyLine, /pick another base/);
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

  test("no base filter, or no search, keeps the generic line", () => {
    // nothing found with the filter off really is "try another search"
    assert.equal(build("lora", "", "Perfect Hands").emptyLine, GENERIC);
    // an empty grid with an empty search box is a browse, not a failed search
    assert.equal(build("lora", "MMDIT26A_MODEL", "").emptyLine, GENERIC);
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

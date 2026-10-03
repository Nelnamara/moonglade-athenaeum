import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  OPERATOR_CHIPS, operatorSuggestions, pickOperator, aspectSuggestions,
} from "../../gallery/src/curation/aspectCore.js";

/* The owner's walk, 2026-10-03: the Filters tray's "Operators" row of chips (ar:tall, ar:wide,
   ar:square, ★4+, keeper, -reject, type:video, type:loom) moves into the search box's own
   suggestion dropdown, as an "Operators" group shown when you click into the field. Picking one
   does what the chip did: it toggles that operator in the search and runs it. The row goes. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");
const tokens = (list) => list.map((o) => o.token);

describe("the Operators group", () => {
  test("clicking into the field offers every operator, whatever is already typed", () => {
    assert.deepEqual(tokens(operatorSuggestions("", { fresh: true })), OPERATOR_CHIPS);
    assert.deepEqual(tokens(operatorSuggestions("night", { fresh: true })), OPERATOR_CHIPS);
  });
  test("an empty field or a finished word offers them too", () => {
    assert.deepEqual(tokens(operatorSuggestions("")), OPERATOR_CHIPS);
    assert.deepEqual(tokens(operatorSuggestions("night ")), OPERATOR_CHIPS);
    assert.deepEqual(tokens(operatorSuggestions("night keeper")), OPERATOR_CHIPS, "one just picked");
  });
  test("while a word is typed, only the operators it begins", () => {
    assert.deepEqual(tokens(operatorSuggestions("night ke")), ["keeper"]);
    assert.deepEqual(tokens(operatorSuggestions("ty")), ["type:video", "type:loom"]);
    assert.deepEqual(tokens(operatorSuggestions("-r")), ["-reject"]);
    assert.deepEqual(operatorSuggestions("night"), [], "a plain word is a search, not an operator");
    assert.deepEqual(operatorSuggestions("k"), [], "one letter is just a letter");
  });
  test("each says what it does, and whether it is already in the search", () => {
    const all = operatorSuggestions("night keeper ar:wide ");
    for (const o of all) assert.ok(o.hint && typeof o.hint === "string", o.token);
    const on = all.filter((o) => o.on).map((o) => o.token);
    assert.deepEqual(on, ["ar:wide", "keeper"]);
  });
  test("an ar: being typed is the Aspect list's, not this one's", () => {
    assert.ok(aspectSuggestions("ar:t").length > 0);
  });
});

describe("picking one does what the chip did", () => {
  test("it adds the operator, or takes it out when it is already there", () => {
    assert.equal(pickOperator("night", "keeper"), "night keeper ");
    assert.equal(pickOperator("night keeper ", "keeper"), "night ");
    assert.equal(pickOperator("", "type:video"), "type:video ");
  });
  test("an ar: replaces any other ar: (a picture has one shape)", () => {
    assert.equal(pickOperator("night ar:tall", "ar:wide"), "night ar:wide ");
  });
  test("a half-typed operator is completed, not left beside it", () => {
    assert.equal(pickOperator("night ke", "keeper"), "night keeper ");
    assert.equal(pickOperator("ty", "type:loom"), "type:loom ");
    assert.equal(pickOperator("night", "keeper"), "night keeper ", "a whole word is not a half-typed operator");
  });
});

describe("the screens", () => {
  const panel = src("components/FiltersPanel.jsx");
  test("the Filters tray no longer has the Operators row", () => {
    assert.doesNotMatch(panel, /mgcu-opchips"/);
    assert.doesNotMatch(panel, /OPERATOR_CHIPS\.map/);
  });
  test("the search field's dropdown carries the Operators group, in its existing look", () => {
    assert.match(panel, /operatorSuggestions\(/);
    assert.match(panel, /pickOperator\(/);
    assert.match(panel, /<div className="mgcu-ac" role="listbox"/);
    assert.match(panel, /className="mgcu-ac-cap">Operators</);
  });
  test("a picked operator runs the search, the way the chip did", () => {
    assert.match(panel, /const next = pickOperator\(query, token\);\s*setQuery\(next\);\s*submitQuery\(next\.trim\(\)\);/);
  });
  test("Tab only takes an operator someone highlighted", () => {
    assert.match(panel, /if \(e\.key === "Tab" && \(aspectList \|\| acIdx >= 0\)\)/);
  });
});

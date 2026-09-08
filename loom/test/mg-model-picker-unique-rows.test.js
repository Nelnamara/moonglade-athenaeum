/* One row per model in the picker (gallery/src/picker/mergeRows.js).

   Owner, 2026-09-07, on the LoRA picker: "of my bookmarked Lora its always the SAME lora
   exactly", "Search is still shit", "It does but its slow". Measured live on the dev server the
   same night: twelve trending pages, 288 rows, 281 distinct model_ids -- PixAI's ranking feeds
   repeat a model across page boundaries. The card key is model_id, so a repeat is a repeated
   React key, and React silently loses the card behind it: on the next fresh list (a search, a tab
   switch) it cannot remove that card, which stays in the grid ABOVE the new results. Every search
   added a few more. Twenty-two such leftovers were counted in his tab, on top of the 24 real
   "Perfect Hands" hits React's own state held. Vanilla JS rewrote the grid wholesale and never
   had the problem, which is why the picker felt right until the 2026-08-08 switch. */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { uniqueRows, appendRows, rowKey } from "../../gallery/src/picker/mergeRows.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(here, "../../gallery/src/components/ModelPicker.jsx"), "utf8");

const row = (id, title) => ({ model_id: id, title: title || ("LoRA " + id) });

describe("the helpers: first occurrence wins, order kept, nothing else touched", () => {
  test("a fresh page with a repeat keeps one card for it", () => {
    const out = uniqueRows([row("a"), row("b"), row("a", "again"), row("c")]);
    assert.deepEqual(out.map((r) => r.model_id), ["a", "b", "c"]);
    assert.equal(out[0].title, "LoRA a", "the FIRST occurrence is the one kept");
  });

  test("a continuation adds only ids the list does not already hold -- the measured feed shape", () => {
    // page 2's first row is page 1's last row, the way a shifting ranking hands it back
    const page1 = [row("1"), row("2"), row("3")];
    const page2 = [row("3"), row("4"), row("5"), row("4")];
    const out = appendRows(page1, page2);
    assert.deepEqual(out.map((r) => r.model_id), ["1", "2", "3", "4", "5"]);
    assert.equal(out.filter((r) => r.model_id === "3").length, 1, "the boundary repeat is dropped");
    assert.equal(out.filter((r) => r.model_id === "4").length, 1, "a repeat INSIDE the new page is dropped too");
  });

  test("a continuation that brings nothing new returns the same array, so React sees no change", () => {
    const page1 = [row("1"), row("2")];
    assert.equal(appendRows(page1, [row("2"), row("1")]), page1);
    assert.equal(appendRows(page1, []), page1);
    assert.equal(appendRows(page1, null), page1);
  });

  test("rows without an id are kept -- there is nothing to collide on -- and get no key from rowKey", () => {
    const noId = { title: "unnamed" };
    assert.equal(rowKey(noId), "");
    assert.equal(rowKey({ model_id: 0 }), "0", "a numeric id is still an id");
    assert.deepEqual(uniqueRows([noId, noId]).length, 2);
    assert.deepEqual(appendRows([row("1")], [noId]).length, 2);
  });

  test("ids compare as strings: a number and its string form are the same model", () => {
    assert.equal(appendRows([{ model_id: 42 }], [{ model_id: "42" }]).length, 1);
  });
});

describe("the picker assembles its rows through the helpers, at both places rows are set", () => {
  test("a fresh search dedupes its page; a continuation merges by id", () => {
    assert.match(src, /setRows\(uniqueRows\(\(d && d\.results\) \|\| \[\]\)\);/,
      "doSearch must set rows through uniqueRows");
    assert.match(src, /setRows\(\(old\) => appendRows\(old, \(d && d\.results\) \|\| \[\]\)\);/,
      "loadMore must merge through appendRows");
    assert.doesNotMatch(src, /setRows\(\(old\) => old\.concat\(/,
      "a raw concat onto rows is how the repeated keys got in; every append goes through appendRows");
  });

  test("the card key is the model id, with a positional fallback for a row that has none", () => {
    assert.match(src, /<div key=\{rowKey\(m\) \|\| "row-" \+ i\} className=\{"mg-card"/,
      "the card key must come from rowKey (a string, so 42 and \"42\" cannot become two keys) " +
      "with a positional fallback so an id-less row never yields key=\"\" twice");
    assert.match(src, /\{rows\.map\(\(m, i\) => \{/, "the map must expose the index for that fallback");
  });
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  countClauses, savedEmptyLine, savedErrorLine, savedTabLabel, currentSet, goneLine,
  SAVED_BASES, NARROW_PX, SAVED_END_LINE,
} from "../../gallery/src/picker/savedCore.js";

/* The model and LoRA pickers' Saved tab (Session S, Saved Tab Handoff; drift 134-139). Saved
   replaces the frozen Bookmarked tab: PixAI's reserved default model collection, read live,
   with a 112 px rail of named sets beside it (a "Saved ▾" chooser below 640 px). The logic is
   importless (gallery/src/picker/savedCore.js) and pinned directly; the picker's wiring is
   pinned on its source, as the rest of the picker's node tests do (no React harness here).
   The browser proof is tests/test_render_harness.py; the server half tests/test_model_saved.py. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(__dirname, "../../gallery/src", p), "utf8");
const picker = read("components/ModelPicker.jsx");
const tab = read("picker/SavedTab.jsx");
const css = read("styles/saved-tab.css");

test("the header's count leaves out every clause that is zero (S5c)", () => {
  assert.deepEqual(countClauses({ count: 18, old: 4, gone: 2 }).map((c) => c.text),
    ["18", "4 old", "2 not available"]);
  assert.deepEqual(countClauses({ count: 1340, old: 0, gone: 9 }).map((c) => c.text),
    ["1,340", "9 not available"]);
  assert.deepEqual(countClauses({ count: 7 }).map((c) => c.key), ["count"]);
  assert.deepEqual(countClauses({}), []);
});

test("empty points at Market, a keyword miss says so, and a failure is never empty", () => {
  assert.equal(savedEmptyLine("lora", ""), "Nothing saved for LoRAs yet. Use ⊕ Save on any LoRA in Market.");
  assert.equal(savedEmptyLine("base", ""), "Nothing saved for models yet. Use ⊕ Save on any model in Market.");
  assert.equal(savedEmptyLine("lora", "glass"), "No saved LoRAs match “glass”.");
  assert.equal(savedErrorLine("Saved"), "Couldn't load Saved.");
  assert.equal(savedErrorLine("Faces"), "Couldn't load Faces.");
  assert.equal(SAVED_END_LINE, "That's everything");
});

test("the rail folds into a Saved ▾ chooser below 640 px of picker width", () => {
  assert.equal(NARROW_PX, 640);
  assert.equal(savedTabLabel(true), "Saved");
  assert.equal(savedTabLabel(false), "Saved ▾");
  assert.match(picker, /ResizeObserver/);
  assert.match(picker, /clientWidth >= NARROW_PX/);
});

test("the set on screen is Saved unless a named set was picked", () => {
  const sets = [{ id: "d", title: "Saved", reserved: true, count: 3 }, { id: "a", title: "Anime", count: 1 }];
  assert.equal(currentSet(sets, "").id, "d");
  assert.equal(currentSet(sets, "a").id, "a");
  assert.equal(currentSet([], ""), null);
  assert.match(goneLine({ saved_at: "2024-03-05T00:00:00.000Z" }), /saved 2024-03-05$/);
});

test("the base chips send values the collection accepts, one at a time", () => {
  const sent = SAVED_BASES.map(([v]) => v).filter(Boolean);
  // every one is in moonglade_backup.LORA_BASE_MODEL_TYPES (the probe: all 47 enum values 200)
  ["MMDIT26B_MODEL", "MMDIT26A_MODEL", "DIT7_MODEL", "SDXL_MODEL", "SD_V1_MODEL"].forEach((v) =>
    assert.ok(sent.includes(v), v));
  assert.equal(SAVED_BASES[0][1], "All");
  assert.match(picker, /&base=" \+ encodeURIComponent\(savedBase\)/);
  assert.match(picker, /kind === "lora" && savedBase/, "base chips are the LoRA picker's only");
});

test("the source row is Market · Saved · Mine, and Bookmarked is gone", () => {
  assert.match(picker, /\["saved", savedTabLabel\(wide\)\]/);
  assert.doesNotMatch(picker, /"Bookmarked"/);
  assert.doesNotMatch(picker, /"bookmark"/);
  assert.match(picker, /kind === "lora" \? \[\["mine", "Mine"\]\]/, "Mine stays as shipped: LoRAs only");
});

test("Saved pages through the picker's own search, by set, with no market filters", () => {
  assert.match(picker, /if \(src === "saved"\) \{\s*if \(setId\) u \+= "&set=" \+ encodeURIComponent\(setId\);/);
  assert.match(picker, /const filtersHidden = market && src === "saved"/);
  // a re-search fires when the set or the chip changes
  assert.match(picker, /\}, \[kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType, setId, savedBase\]\);/);
});

test("the rail is read once when Saved opens, and nothing is written on open", () => {
  assert.match(picker, /apiGet\("\/api\/model-saved\/sets", \{ kind \}\)/);
  assert.doesNotMatch(tab, /apiPost/);
  assert.doesNotMatch(picker.slice(0, picker.indexOf("export default")), /apiPost/);
});

test("an error is peach with Retry, empty is one line, and the end of the list says so", () => {
  assert.match(picker, /savedErrorLine\(/);
  assert.match(picker, /className="mg-saved-retry"/);
  assert.match(picker, /savedEmptyLine\(kind, qDebounced\)/);
  assert.match(picker, /SAVED_END_LINE/);
  assert.match(css, /\.mg-saved-err \{[^}]*var\(--peach\)/);
});

test("the rail is 112 px of mono 10 px at line-height 2, marked with a lavender ▸", () => {
  assert.match(css, /\.mg-rail \{[^}]*width: 112px/);
  assert.match(css, /\.mg-rail \{[^}]*font: 10px\/2 ui-monospace/);
  assert.match(css, /\.mg-rail-mark \{[^}]*color: var\(--lavender\)/);
  assert.match(tab, /"▸"/);
  // the header's count is mono 9.5 px in overlay0
  assert.match(css, /\.mg-saved-count \{[^}]*font: 9\.5px\/1\.45 ui-monospace[^}]*color: var\(--overlay0\)/);
});

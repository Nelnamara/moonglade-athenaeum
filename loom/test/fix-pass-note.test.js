import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { fixPassNote } from "../../gallery/src/gen/editCore.js";

/* #93: PixAI launched Hand Fix and Face Fix on 2026-10-21, priced per pass, and its server
   refuses face and hand boxes in one Fix. So a Fix is ONE pass of ONE kind: the Face / Hand
   pick (the Design Handoffs' fixKind) is the pass's tag, and the cost line names the pass.

   fixPassNote is the badge's whole per-pass reading, in its existing note line. The kind
   handlers are pinned as source reads (the style of price-probe-structure.test.js): "picking
   the other kind clears the boxes" is a fact about three handlers, and the phone one is also
   driven for real in loom-mobile-view.test.js. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.join(__dirname, rel), "utf8");

test("fixPassNote: the kind, then the discount when this answer's list price is above its price", () => {
  assert.equal(fixPassNote({ cost: 4800, original_cost: 8000, fix_pass: "face" }), "face pass · 40% off 8,000");
  assert.equal(fixPassNote({ cost: 4800, original_cost: 8000, fix_pass: "hand" }), "hand pass · 40% off 8,000");
  // equal or absent original: no discount words
  assert.equal(fixPassNote({ cost: 4800, original_cost: 4800, fix_pass: "face" }), "face pass");
  assert.equal(fixPassNote({ cost: 4800, fix_pass: "face" }), "face pass");
  assert.equal(fixPassNote({ cost: 8000, original_cost: 4800, fix_pass: "face" }), "face pass",
    "a list price BELOW the price is never read as a discount");
  // no fix_pass: not a Fix answer
  assert.equal(fixPassNote({ cost: 4800, original_cost: 8000 }), "");
  assert.equal(fixPassNote({ cost: 600 }), "");
  assert.equal(fixPassNote(null), "");
  assert.equal(fixPassNote(undefined), "");
  // no real price (review F7): never "100% off" -- the pass alone
  for (const cost of [undefined, null, 0, "n/a", NaN]) {
    assert.equal(fixPassNote({ cost, original_cost: 8000, fix_pass: "face" }), "face pass", "cost " + String(cost));
  }
});

test("all three Fixer surfaces clear the boxes when the kind changes (one kind per Fix)", () => {
  const fixTab = read("../../gallery/src/components/FixTab.jsx");
  assert.match(fixTab, /onClick=\{\(\) => \{ if \(t !== tag\) \{ setTag\(t\); setBoxes\(\[\]\); \} \}\}/,
    "FixTab's Face / Hand segments clear the boxes on a change of kind");
  assert.doesNotMatch(fixTab, /onClick=\{\(\) => setTag\(t\)\}/, "no segment sets the kind without clearing");

  const sb = read("../master-storyboard.jsx");
  // one handler per Loom component, each clearing on a change of kind
  const handlers = sb.match(/const pickFixKind = \(k\) => \{ if \(k !== fixTag\) \{ setFixTag\(k\); setFixBoxes\(\[\]\); \} \};/g) || [];
  assert.equal(handlers.length, 2, "LoomV2 and LoomMobile each have the clearing kind handler");
  const mobileStart = sb.indexOf("function LoomMobile({");
  const desktop = sb.slice(0, mobileStart), mobile = sb.slice(mobileStart);
  assert.match(desktop, /onClick=\{\(\) => pickFixKind\("face"\)\}>Face</);
  assert.match(desktop, /onClick=\{\(\) => pickFixKind\("hand"\)\}>Hand</);
  assert.match(mobile, /onClick=\{\(\) => pickFixKind\(t\)\}>\{t === "face" \? "Face" : "Hand"\}/);
  assert.doesNotMatch(sb, /onClick=\{\(\) => setFixTag\(/, "no Loom chip sets the kind without clearing the boxes");
});

test("the desktop Loom's cost line carries the pass note between the price and 'never card-covered'", () => {
  const sb = read("../master-storyboard.jsx");
  assert.match(sb, /import \{ scaleBoxes, fixPassNote \} from "\.\.\/gallery\/src\/gen\/editCore\.js";/);
  assert.match(sb, /"≈ " \+ Number\(fixPriceEntry\.pr\.cost\)\.toLocaleString\(\) \+ " credits" \+ \(fixNote \? " · " \+ fixNote : ""\) \+ " — never card-covered"/);
});

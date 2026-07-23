import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// D-12 increments 2-4: the Image tab already had a working submit path (confirmSpend's
// window.confirm) but no live preview of the cost before you click Go -- same gap the
// Gallery's Enhance sub-tab had (increment 1, already shipped). Fixed the same way: a
// <mg-cost-badge> per tab, kept live via a debounced read-only /api/price check.
//
// UNLIKE the Gallery's Enhance tab, these three tabs' window.confirm is NOT removed --
// confirmSpend was built as this project's fail-closed guardrail after these exact tabs
// "used to lie" about cost (see confirmSpend's own comment in master-storyboard.jsx), so
// the badge here is an ADDED preview, not a replacement for the submit-time gate. Every
// assertion below that checks for a badge is paired with one confirming confirmSpend/
// window.confirm is still wired into genImage/genEdit/genRef.
//
// master-storyboard.jsx has no jsdom/React test harness in this runner (same situation as
// mg-model-picker.js) -- source-presence assertions are the established pattern for files
// in that position; real interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

test("each of the three Deep Focus gen tabs gets its own cost-badge ref", () => {
  assert.match(src, /const imgCostRef = useRef\(null\);/);
  assert.match(src, /const editCostRef = useRef\(null\);/);
  assert.match(src, /const refCostRef = useRef\(null\);/);
});

test("a <mg-cost-badge> is actually mounted in the Image, Edit, and Reference tab JSX", () => {
  assert.match(src, /<mg-cost-badge ref=\{imgCostRef\}/,
    "the Image tab's badge must actually be in the rendered tabBody, not just declared as a ref");
  assert.match(src, /<mg-cost-badge ref=\{editCostRef\}/,
    "the Edit tab's badge must actually be in the rendered tabBody, not just declared as a ref");
  assert.match(src, /<mg-cost-badge ref=\{refCostRef\}/,
    "the Reference tab's badge must actually be in the rendered tabBody, not just declared as a ref");
});

test("badge refreshes are debounced read-only /api/price checks, not the spend endpoints", () => {
  assert.match(src, /const priceInto = \(ref, body\) => \{/);
  assert.match(src, /badge\.setChecking\(\);/);
  assert.match(src, /fetch\("\/api\/price", \{ method: "POST"/);
  // three separate setTimeout-debounced effects driving priceInto -- not a synchronous
  // call on every keystroke
  const debounceCount = (src.match(/setTimeout\(\(\) => priceInto\(/g) || []).length;
  assert.equal(debounceCount, 3, "expected one debounced priceInto call per tab (image/edit/reference)");
});

test("the Image tab's badge price body omits unresolved LoRAs from ever being submitted for pricing", () => {
  assert.match(src, /if \(!imgModel \|\| !prompt \|\| anyLoraUnresolved\(imgLoras\)\) \{ badge\.clear\(\); return; \}/);
});

test("confirmSpend's window.confirm gate is UNCHANGED and still runs at submit time for all three tabs", () => {
  // genImage calls confirmSpend directly; genEdit/genRef go through runGen, which also
  // calls confirmSpend before ever hitting the network. The badge is additive.
  assert.match(src, /if \(!\(await confirmSpend\(\{ model_id: imgModel\.model_id, prompt \}, `Generate a reference image/,
    "genImage must still gate its real submit on confirmSpend");
  assert.match(src, /const runGen = async \(setState, cardId, endpoint, body, priceBody, label\) => \{\s*\n\s*if \(priceBody && !\(await confirmSpend\(priceBody, label\)\)\) return;/,
    "runGen (genEdit/genRef's shared submit path) must still gate on confirmSpend");
  assert.match(src, /return window\.confirm\(`\$\{label\}/,
    "confirmSpend itself must still fall through to a real window.confirm");
});

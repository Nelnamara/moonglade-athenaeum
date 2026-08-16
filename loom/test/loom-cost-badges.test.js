import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// D-12 increments 2-4: the Image tab already had a working submit path (confirmSpend's
// window.confirm) but no live preview of the cost before you click Go. Fixed with a
// <CostBadge> per tab (the shared React component, ported from the vanilla <mg-cost-badge>
// element in the 2026-08-08 no-vanilla campaign), kept live via a debounced read-only
// /api/price check.
//
// These three tabs' window.confirm is NOT removed alongside it --
// confirmSpend was built as this project's fail-closed guardrail after these exact tabs
// "used to lie" about cost (see confirmSpend's own comment in master-storyboard.jsx), so
// the badge here is an ADDED preview, not a replacement for the submit-time gate. Every
// assertion below that checks for a badge is paired with one confirming confirmSpend/
// window.confirm is still wired into genImage/genEdit/genRef.
//
// master-storyboard.jsx has no jsdom/React test harness in this runner (same situation as
// the shared ModelPicker.jsx / GalleryPicker.jsx it mounts) -- source-presence assertions
// are the established pattern for files in that position; real interaction verification
// needs a real browser (done live, 2026-08-08: the Gallery drawer's CostBadge priced a
// picked model to its FREE state).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

test("each of the three Deep Focus gen tabs gets its own cost-badge ref", () => {
  assert.match(src, /const imgCostRef = useRef\(null\);/);
  assert.match(src, /const editCostRef = useRef\(null\);/);
  assert.match(src, /const refCostRef = useRef\(null\);/);
});

test("a <CostBadge> is actually mounted in the Image, Edit, and Reference tab JSX", () => {
  assert.match(src, /<CostBadge ref=\{imgCostRef\}/,
    "the Image tab's badge must actually be in the rendered tabBody, not just declared as a ref");
  assert.match(src, /<CostBadge ref=\{editCostRef\}/,
    "the Edit tab's badge must actually be in the rendered tabBody, not just declared as a ref");
  assert.match(src, /<CostBadge ref=\{refCostRef\}/,
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
  //
  // L536: genImage's confirmSpend argument changed from a narrow {model_id, prompt} to the
  // FULL buildImgGenBody() shape (size/mode/count/seed/etc now all affect real cost) -- the
  // gate itself is unchanged, only what it prices got more accurate. See
  // loom-mutations.test.js's "buildImgGenBody" suite for the body-shape coverage.
  assert.match(src, /const body = buildImgGenBody\(imgModel, imgLoras, imgAdv, prompt\);\s*\n\s*if \(!\(await confirmSpend\(body, `Generate a reference image/,
    "genImage must still gate its real submit on confirmSpend, pricing the exact body it submits");
  // The trailing `jobLabel` param (2026-07-24 Job Tracker registration fix -- see
  // loom-image-job-register.test.js) is additive and sits AFTER `label`; the gate below is
  // what this assertion is about, so the signature is matched up to `label` rather than
  // pinned to an exact arity that any future additive param would break again.
  assert.match(src, /const runGen = async \(setState, cardId, endpoint, body, priceBody, label[^)]*\) => \{\s*\n\s*if \(priceBody && !\(await confirmSpend\(priceBody, label\)\)\) return;/,
    "runGen (genEdit/genRef's shared submit path) must still gate on confirmSpend");
  assert.match(src, /return window\.confirm\(`\$\{label\}/,
    "confirmSpend itself must still fall through to a real window.confirm");
});

// issue #15 (multi-ticket free cards): /api/price's `free` is now the server's card_covers()
// -- false BOTH when no card matched and when one matched but the tickets held fall short
// of what the duration costs. The old flat "No free card covers ... it will spend ~N" was a
// FALSE sentence for the second case. OWNER RULING: the app still spends when short (the
// site does), but every surface must say exactly what happens -- nothing attaches, the
// FULL price is charged -- and the batch must count tickets against the held pool BEFORE
// its confirm. Wording lives in loom-core.js (priceIsShort / shortSpendLine /
// tallyPricesDetailed) and is unit-tested there; these pins prove the .jsx actually
// routes its confirms through them, keeping the fail-closed structure above intact.
test("confirmSpend and generateShot branch short-vs-unmatched, and still fail closed on an unverified price", () => {
  assert.match(src, /priceIsShort, shortSpendLine,/, "the .jsx must import the shared short-case helpers");
  // confirmSpend: `${label}\n\n${line}` where line is short OR the original not-matched sentence
  assert.match(src, /const line = priceIsShort\(pr\)\s*\n\s*\? shortSpendLine\(pr, "this"\)\s*\n\s*: `No free card covers it — it will spend ~\$\{pr\.cost\.toLocaleString\(\)\} credits\.`;\s*\n\s*return window\.confirm\(`\$\{label\}\\n\\n\$\{line\}\\n\\nGenerate anyway\?`\);/,
    "confirmSpend must word the short case honestly and keep the not-matched sentence otherwise");
  // generateShot (video): names the shot's duration in the short sentence
  assert.match(src, /const line = priceIsShort\(pr\)\s*\n\s*\? shortSpendLine\(pr, `this \$\{p\.duration \? `\$\{p\.duration\}s ` : ""\}shot`\)\s*\n\s*: `No free card covers this shot — it will spend ~\$\{pr\.cost\.toLocaleString\(\)\} credits\.`;/,
    "generateShot must word the short case honestly and keep the not-matched sentence otherwise");
  // fail-closed shape untouched: both gates still ask on a null/unverified price
  assert.match(src, /return window\.confirm\(`\$\{label\}\\n\\nCouldn't verify the cost or free-card coverage — it may spend credits\./);
  assert.match(src, /\} else if \(!pr \|\| !pr\.free\) \{\s*\n\s*if \(!window\.confirm\("Couldn't verify this shot's cost or free-card coverage/);
});

test("batchGenerate tallies tickets against the held pool (tallyPricesDetailed) and words the overflow before the confirm", () => {
  assert.match(src, /const \{ free, paid, credits, unknown, overflow, pools, overflowIndexes \} = tallyPricesDetailed\(prices\);/,
    "the batch confirm must use the pool-aware tally (incl. overflowIndexes), not the per-shot buckets");
  assert.match(src, /🎫 \$\{free\} covered by free cards\\n` \+\s*\n\s*`≈ \$\{paid\} will spend credits — about \$\{credits\.toLocaleString\(\)\} total`/,
    "the batch confirm must state covered vs will-spend with the credit total");
  assert.match(src, /overflowNote \+/, "the overflow explanation must be part of the confirm message");
  assert.match(src, /Once the cards run out, no card is used and each remaining shot spends its full price/,
    "overflow wording must say nothing attaches and the FULL price is charged -- never partial application");
  // Review 2026-08-16: the docs promise 'shot by shot' -- the confirm must NAME the shots that
  // may spend (overflowIndexes -> shot codes), and word it as an UPPER bound ('Up to N ... may'),
  // because the tally drains only the card each shot was priced against alone and a second
  // covering card can still fund one at submit time.
  assert.match(src, /overflowIndexes \|\| \[\]\)\.map\(\(i\) => todo\[i\] && todo\[i\]\.code\)/,
    "the confirm must map overflowIndexes to shot codes");
  assert.match(src, /Up to \$\{overflow\} of those priced free on their own may spend credits/,
    "overflow must be worded as an upper bound, not a certainty");
  // No refusal was added: the confirm is still the only gate and submission order is unchanged.
  assert.match(src, /if \(!window\.confirm\(msg\)\) \{ setBatching\(false\); return; \}/);
  assert.match(src, /for \(const e of todo\) \{[\s\S]*?try \{ r = await generateShot\(e, \{ skipConfirm: true \}\); \}/);
});

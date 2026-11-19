import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { quotedSendBody } from "../../gallery/src/gen/priceProbeCore.js";

/* A SINGLE WEB SEND CARRIES WHAT ITS BADGE SHOWED (2026-11-18). A send whose settled quote was
   FREE goes out with expect_free, and the server refuses it (nothing sent, an {error} on the
   line) if the card that quote found is gone by the time it sends -- the Loom's F13 rule, on the
   gallery's own sends. The server half is pinned in dev/tests/test_single_send_quoted_free.py. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (rel) => readFileSync(path.join(here, "..", "..", "gallery", "src", rel), "utf8")
  .split("\r\n").join("\n");

describe("quotedSendBody", () => {
  const p = { mode: "image", prompt: "a cat" };
  test("a FREE quote adds expect_free and leaves the caller's payload untouched", () => {
    const out = quotedSendBody(p, { cost: 0, free: true });
    assert.deepEqual(out, { ...p, expect_free: true });
    assert.equal("expect_free" in p, false);
  });
  test("a priced quote, an error answer, Unlimited Mode or no quote sends the payload as it is", () => {
    for (const q of [{ cost: 400, free: false }, { error: "x", cost: null, free: false },
                     { error: "x", free: true }, { cost: 0, free: true, unlimited: true },
                     null, undefined, { free: "yes" }]) {
      assert.equal(quotedSendBody(p, q), p, JSON.stringify(q));
    }
  });
});

describe("submitTask posts the quote's verdict, and every quoted single send hands it over", () => {
  test("submitTask's POST body is quotedSendBody(payload, quote)", () => {
    const s = src("gen/submitTask.js");
    assert.match(s, /body: JSON\.stringify\(quotedSendBody\(payload, quote\)\)/);
    assert.match(s, /export async function submitTask\(route, payload, \{[^}]*\bquote\b[^}]*\}\)/);
  });
  for (const [rel, route, quote] of [
    ["gen/useGenerate.js", "/api/generate", "priceAnswer"],
    ["gen/useEditGenerate.js", "/api/edit", "probe.response"],
    ["components/EditTab.jsx", "/api/edit", "probe.response"],
    ["components/TsubakiEditBar.jsx", "/api/generate", "probe.response"],
    ["components/UpscalePanel.jsx", "/api/generate", "probe.response"],
    ["components/EnhanceTab.jsx", "/api/enhance", "{ free: !!priced.free_card }"],
  ]) {
    test(rel + " hands submitTask the quote its Go was allowed on", () => {
      const s = src(rel);
      const at = s.indexOf('submitTask("' + route + '"');
      assert.ok(at > 0, rel + ": its submitTask call moved -- re-point this test, never drop it");
      const call = s.slice(at, s.indexOf(");", at));
      assert.ok(call.includes("quote: " + quote), rel + " must pass quote: " + quote);
    });
  }
  test("the gallery's own Video tab sends expect_free on a FREE quote too, not only in the Loom", () => {
    const s = src("components/VideoDrawer.jsx");
    assert.match(s, /: \(expectFree \? \{ \.\.\.p, expect_free: true \} : p\);/);
  });
});

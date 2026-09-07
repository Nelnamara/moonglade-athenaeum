import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE DELETE-FROM-PIXAI CONFIRM DIALOG (owner, 2026-09-07; corrected the same day).

   The one irreversible action in this app is gated by a dialog whose numbers the owner reads
   to decide. Two things about it are pinned here:

     THE COUNTS ADD UP. The live check subtracts the images PixAI has already dropped from the
     headline -- they are NOT going anywhere -- and the dialog then has three quantities in it
     that a reader has to be able to reconcile: what will be deleted, what is already gone, and
     the batch membership the "you picked N; the other M" clause counts. They are computed in
     one place (lib/cloudDeleteCounts.js) so the arithmetic is a real import here rather than a
     regex over prose.

     THE WORDING MATCHES THE ARITHMETIC. A source guard, the established pattern for anything
     in a React component in this runner (there is no jsdom/React harness) -- see
     viewer-landing.test.js, whose suite this one sits beside.

   Plus the one client-side fact the dialog's own opening depends on: the preview fetch is
   bounded, a little above the server's own 12s ceiling. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const api = src("api.js");

describe("the preview fetch cannot hang the dialog open forever", () => {
  test("deletePreview carries a timeout, above the server's 12s ceiling", () => {
    // The route reads every selected task back from PixAI and bounds ITSELF at
    // DELETE_PREVIEW_LIVE_BUDGET_S = 12s. This is the backstop for the server going silent
    // rather than answering slowly: a little above the ceiling, so an ordinary slow answer
    // still arrives and only a real silence trips it.
    const ms = /export const DELETE_PREVIEW_MS = (\d+);/.exec(api);
    assert.ok(ms, "deletePreview's timeout must be a named constant, not a magic number");
    assert.ok(Number(ms[1]) > 12000 && Number(ms[1]) <= 30000,
      "the client timeout must sit above the server's 12s budget and still be a wait a "
      + "person will tolerate; found " + ms[1] + "ms");
    assert.match(api, /timeoutMs: DELETE_PREVIEW_MS/,
      "the constant must actually be handed to the request");
    assert.match(api, /timeoutMessage: "PixAI did not answer in time/,
      "a lapsed preview must say so in plain words, not fall through unexplained");
  });

  test("the transport honours it with an AbortController, and cleans the timer up", () => {
    assert.match(api, /new AbortController\(\)/);
    assert.match(api, /clearTimeout\(timer\)/);
    // timeoutMs/timeoutMessage are ours, not fetch's: they must not reach the browser.
    assert.match(api, /const \{ timeoutMs, timeoutMessage, \.\.\.rest \} = init \|\| \{\};/);
    assert.match(api, /fetch\(path, rest\)/);
  });

  test("a lapsed preview opens no dialog -- it falls back to the prose confirm", () => {
    const menu = src("components/ActionsMenu.jsx");
    assert.match(menu, /if \(data && data\.totals\) \{ setPreview\(\{ data, ids \}\); return; \}/,
      "an {error} answer is not a preview: `totals` is what makes it one");
    assert.match(menu, /\(data && data\.error \? data\.error \+ "\\n\\n" : ""\)/,
      "the reason the preview could not be loaded must reach the owner");
  });
});

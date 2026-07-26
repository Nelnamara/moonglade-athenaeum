import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// static/mg-notify.js is a plain global IIFE that builds its DOM on connect, so the label
// helper is exercised here the way the rest of this suite treats that file: by pulling the
// function out of the source and running it. That is enough -- the whole behaviour is a
// lookup with a fallback, and the interesting part is WHICH string comes back.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

function loadLabelFor() {
  const table = src.slice(src.indexOf("var LABEL_ING = {"),
                          src.indexOf("function labelFor(j, terminal){"));
  const fn = src.slice(src.indexOf("function labelFor(j, terminal){"));
  const body = fn.slice(0, fn.indexOf("\n    }") + 6);
  // eslint-disable-next-line no-new-func
  return new Function(table + body + "\nreturn labelFor;")();
}

describe("activity card label tense", () => {
  const labelFor = loadLabelFor();

  test("an in-flight job reads in the PRESENT tense", () => {
    // The stored label is the completion wording, written at SUBMIT time, so the card used
    // to say "Generated" about a job still sitting in PixAI's queue. Owner-reported
    // 2026-07-25: 'says "Generated" while spinning'.
    assert.equal(labelFor({ label: "Generated" }, false), "Generating");
    assert.equal(labelFor({ label: "Edited" }, false), "Editing");
    assert.equal(labelFor({ label: "Rendered" }, false), "Rendering");
    assert.equal(labelFor({ label: "Fixed" }, false), "Fixing");
  });

  test("a finished job keeps the stored wording", () => {
    // By then it is correct, and the completion toast reads off the same field -- rewriting
    // it here would desynchronise the card from the toast beside it.
    assert.equal(labelFor({ label: "Generated" }, true), "Generated");
    assert.equal(labelFor({ label: "Edited" }, true), "Edited");
  });

  test("an unknown label passes through untouched, in either state", () => {
    // Better shown as-is than mangled by a rule that has never seen it. A future job type
    // with its own wording must not become "Somethinged" -> "Somethinging".
    assert.equal(labelFor({ label: "Synced i2v videos" }, false), "Synced i2v videos");
    assert.equal(labelFor({ label: "Synced i2v videos" }, true), "Synced i2v videos");
  });

  test("a job with no label at all still says something", () => {
    assert.equal(labelFor({}, false), "Generation");
    assert.equal(labelFor({}, true), "Generation");
  });
});

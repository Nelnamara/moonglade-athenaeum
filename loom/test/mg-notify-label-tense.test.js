import { test, describe } from "node:test";
import assert from "node:assert/strict";

// Port note 2026-08-08: static/mg-notify.js is gone (no-vanilla campaign) and with it the old
// regex-extract-the-IIFE-body loader. The label helper now lives as a real export in
// gallery/src/notify/format.js, so this suite imports and runs the ACTUAL implementation.
// The behaviour under test is unchanged: a lookup with a fallback, and the interesting part
// is WHICH string comes back.
import { labelFor, LABEL_ING } from "../../gallery/src/notify/format.js";

describe("activity card label tense", () => {
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

  test("every LABEL_ING entry actually changes tense (table sanity)", () => {
    // Port note 2026-08-08: new check, possible only now that the real table is importable.
    // Guards against a copy-paste row where past and present tense are identical, which would
    // silently reintroduce the "Generated while spinning" bug for that job type.
    for (const [past, present] of Object.entries(LABEL_ING)) {
      assert.notEqual(present, past, `LABEL_ING["${past}"] maps to itself`);
      assert.equal(labelFor({ label: past }, false), present);
      assert.equal(labelFor({ label: past }, true), past);
    }
  });
});

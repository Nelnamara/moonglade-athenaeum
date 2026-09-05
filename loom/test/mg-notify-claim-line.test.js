import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The claim's activity-tracker line (owner ask, 2026-08-31: "Yes I would still like this in
// the tracker lines"). The LINE itself is written server-side -- the tracker renders server
// truth from /api/jobs, so a client-side row would vanish on the next poll -- which leaves the
// client two jobs: name the new job type in words, and keep the tray's transition-toast rule
// from mistaking a born-terminal row for a job that just finished.
import { kindLabel, KIND_LABEL } from "../../gallery/src/notify/format.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const store = readFileSync(
  path.join(__dirname, "../../gallery/src/notify/jobsStore.js"), "utf8").replace(/\r\n/g, "\n");

describe("the claim line in the activity tracker", () => {
  test("the claim job type renders in words, not as its raw enum", () => {
    // The table's own reason for existing: an unmapped type falls through to its value, which
    // is how 'cli' once rendered as the non-word "Cli".
    assert.equal(kindLabel("claim"), "Rewards");
    assert.notEqual(kindLabel("claim"), "claim");
  });

  test("every mapped kind is a real word, claim included", () => {
    // Self-computing: asserts the property over whatever the table holds rather than
    // restating its entries, so a kind added later is covered the day it lands.
    for (const [key, label] of Object.entries(KIND_LABEL)) {
      assert.ok(label && label !== key, `${key} must map to a human label`);
      assert.match(label, /^[A-Z]/, `${key}'s label should read as a word: ${label}`);
    }
  });

  test("a claim row never fires the tray's completion toast", () => {
    // A claim is instantaneous, so its row is BORN "done" -- and the transition rule
    // (not-terminal -> terminal) would read that first sighting as a job that just finished,
    // toasting "— done / Added to your gallery." Nothing was added to the gallery, and the
    // claim already toasted its real "+N credits" at click time, seconds earlier.
    // Source-structure check, the house convention for jobsStore internals (toastTransitions
    // is not exported and there is no DOM/timer harness here).
    const i = store.indexOf("function toastTransitions(");
    assert.ok(i >= 0, "expected toastTransitions() in jobsStore.js");
    const body = store.slice(i, store.indexOf("\n}", i) + 2);
    assert.match(body, /j\.type\s*===\s*["']claim["']/,
      "toastTransitions must special-case claim rows");
    // ...and it must still RECORD the status before returning, or the row would be treated
    // as unseen forever (and re-evaluated on every single poll).
    const guard = body.slice(body.indexOf('j.type === "claim"'));
    assert.match(guard.slice(0, 120), /last\[j\.job_id\]\s*=\s*st/,
      "the claim short-circuit must still remember the row's status");
  });

  test("an update row swallows only its SUCCESS toast, never its failure", () => {
    // The Identity Chrome handoff (C2) retires the "Updated Moonglade — done / Added to
    // your gallery" toast because the update modal is the receipt for a success you were
    // watching. It retires nothing about a FAILURE, which is the outcome that routinely
    // lands with the modal closed and the tab moved on -- swallowing that one would make a
    // failed update the only job in the app that fails in silence. Same source-structure
    // check as the claim row above, and the same reason for it.
    const i = store.indexOf("function toastTransitions(");
    const body = store.slice(i, store.indexOf("\n}", i) + 2);
    const at = body.indexOf('j.type === "update"');
    assert.ok(at >= 0, "toastTransitions must special-case update rows");
    const guard = body.slice(at, at + 120);
    // The status test is what makes it success-only: an unqualified type check would take
    // the failure with it.
    assert.match(guard, /j\.type === "update"\s*&&\s*st\s*===\s*["']done["']/,
      "the update short-circuit must be conditioned on the successful terminal state");
    assert.match(guard, /last\[j\.job_id\]\s*=\s*st/,
      "the update short-circuit must still remember the row's status");
    // ...and the fall-through it leaves open is the generic sticky failure toast, which
    // only fires for a row this map calls terminal.
    assert.match(body, /TERMINAL\[st\]/,
      "a failed update must reach the shared terminal-transition rule");
  });
});

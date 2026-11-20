import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inTracker, trackerRows } from "../../gallery/src/notify/trackerRows.js";

/* Owner, 2026-11-18: "I want maint. jobs removed from the tracker." The Activity tracker lists
   what the owner set going; scheduled jobs and Control Panel maintenance stay in the Ledger. */

test("owner-started work stays in the tracker", () => {
  for (const j of [{ type: "generate" }, { type: "import" }, { type: "delete" }, { type: "claim" },
                   { type: "update" }, { type: "integrity" },
                   { type: "panel", action: "sync" }, { type: "panel", action: "sync-videos" }]) {
    assert.equal(inTracker(j), true, JSON.stringify(j));
  }
});

test("maintenance and anything the library ran by itself leave the list", () => {
  for (const j of [{ type: "panel", action: "sync", scheduled: true },
                   { type: "panel", action: "artworks-sweep", scheduled: true },
                   { type: "panel", action: "artworks-sweep" },
                   { type: "panel", action: "audit" }, { type: "panel", action: "catalog-stats" },
                   { type: "generate", scheduled: true }, null, "x"]) {
    assert.equal(inTracker(j), false, JSON.stringify(j));
  }
  assert.deepEqual(trackerRows([{ type: "generate", job_id: "a" },
                                { type: "panel", action: "audit", job_id: "b" }]).map((j) => j.job_id),
                   ["a"]);
});

test("the store lists trackerRows but still reads every row for its notices", () => {
  const src = readFileSync(new URL("../../gallery/src/notify/jobsStore.js", import.meta.url), "utf8");
  const refresh = src.slice(src.indexOf("export function refresh"), src.indexOf("function schedule"));
  assert.match(refresh, /toastTransitions\(rows\)/);
  assert.match(refresh, /jobs = trackerRows\(rows\)/);
});

// gen/seriesName.js -- the "· v3 · 2/4" dial-in suffix, two independent facts each shown
// only when known (#34): the SESSION version (from /api/series by_task) and the BATCH
// output (from the row's batch_index/batch_size, #33). Pure, so the card and Details share it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { batchLabel, seriesSuffix } from "../../gallery/src/gen/seriesName.js";

test("batchLabel is 1-based k/N, only when both fields are real", () => {
  assert.equal(batchLabel({ batch_index: "1", batch_size: "4" }), "2/4");
  assert.equal(batchLabel({ batch_index: "0", batch_size: "4" }), "1/4");
  assert.equal(batchLabel({ batch_index: "", batch_size: "4" }), "");      // non-batch output
  assert.equal(batchLabel({ batch_index: "2", batch_size: "" }), "");
  assert.equal(batchLabel({}), "");
  assert.equal(batchLabel({ batch_index: "4", batch_size: "4" }), "");     // out of range -> nothing, never nonsense
});

test("seriesSuffix: version only, batch only, both, neither", () => {
  const row = { task_id: "T1", batch_index: "1", batch_size: "4" };
  // both
  assert.equal(seriesSuffix(row, { T1: { v: 3 } }), " · v3 · 2/4");
  // version only (no batch fields)
  assert.equal(seriesSuffix({ task_id: "T1" }, { T1: { v: 3 } }), " · v3");
  // batch only (task not in a series)
  assert.equal(seriesSuffix(row, {}), " · 2/4");
  assert.equal(seriesSuffix(row, { T2: { v: 9 } }), " · 2/4");
  // neither
  assert.equal(seriesSuffix({ task_id: "T1" }, {}), "");
  assert.equal(seriesSuffix({ task_id: "" }, { "": { v: 2 } }), "");   // no task id -> no version
});

test("a singleton (absent from by_task) shows no version", () => {
  // the API returns by_task ONLY for multi-task series, so a singleton's task is simply absent
  assert.equal(seriesSuffix({ task_id: "SOLO", batch_index: "0", batch_size: "2" }, {}), " · 1/2");
});

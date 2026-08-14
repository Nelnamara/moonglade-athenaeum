import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { planLoraRestore } from "../../gallery/src/gen/genCore.js";

// Remix (issue #4) -- the pure LoRA-restore plan, pinned against the 2026-08-13
// adversarial review's spend-safety findings. The scenario behind 1.1: a task
// that used TWO VERSIONS of the same LoRA model. The composer keys LoRAs by
// model_id, so only one can ride -- the failure mode the review confirmed was
// the second add silently no-oping while its weight patch RETUNED the first
// version (v1@0.9 + v2@0.3 becoming v1@0.3: wrong weight, silent drop, chip
// claiming the recipe). The plan layer prevents it by construction: the first
// row rides at ITS OWN weight, the collision is counted into the disclosed
// note, and no cross-patching step exists at all.

const row = (model, version, weight, extra) =>
  Object.assign({ model_id: model, version_id: version, weight,
                  title: model, preview_url: "", lora_base_model_type: "SDXL",
                  model_type: "SDXL", degraded: false }, extra);

describe("planLoraRestore", () => {
  test("happy path: rows ride untouched, no notes", () => {
    const plan = planLoraRestore({ loras: [row("A", "v1", 0.9), row("B", "v9", 0.3)], unresolved: 0 }, true);
    assert.deepEqual(plan.notes, []);
    assert.deepEqual(plan.rows.map((r) => [r.model_id, r.version_id, r.weight]),
      [["A", "v1", 0.9], ["B", "v9", 0.3]]);
  });

  test("two versions of one model: first kept AT ITS OWN WEIGHT, second counted", () => {
    const plan = planLoraRestore({ loras: [row("A", "v1", 0.9), row("A", "v2", 0.3)], unresolved: 0 }, true);
    assert.deepEqual(plan.rows.map((r) => [r.version_id, r.weight]), [["v1", 0.9]]);
    assert.deepEqual(plan.notes, ["1 LoRA could not be restored"]);
  });

  test("server unresolved count carries into the note", () => {
    const plan = planLoraRestore({ loras: [row("A", "v1", 0.5)], unresolved: 2 }, true);
    assert.deepEqual(plan.notes, ["2 LoRAs could not be restored"]);
    assert.equal(plan.rows.length, 1);
  });

  test("rows missing ids are counted, never silently skipped", () => {
    const plan = planLoraRestore({ loras: [row("", "v1", 0.5), row("B", "", 0.5)], unresolved: 0 }, true);
    assert.equal(plan.rows.length, 0);
    assert.deepEqual(plan.notes, ["2 LoRAs could not be restored"]);
  });

  test("degraded compatibility data is disclosed", () => {
    const plan = planLoraRestore({ loras: [row("A", "v1", 0.5, { degraded: true })], unresolved: 0 }, true);
    assert.deepEqual(plan.notes, ["a LoRA's compatibility data is unverified"]);
    assert.equal(plan.rows.length, 1);
  });

  test("clean-empty against a catalog that names LoRAs is a FAILED restore", () => {
    const plan = planLoraRestore({ loras: [], unresolved: 0 }, true);
    assert.deepEqual(plan.notes, ["LoRAs could not be restored"]);
  });

  test("clean-empty on a genuinely LoRA-free task is silent", () => {
    const plan = planLoraRestore({ loras: [], unresolved: 0 }, false);
    assert.deepEqual(plan.notes, []);
    assert.deepEqual(plan.rows, []);
  });

  test("malformed/absent payload degrades to empty, not a throw", () => {
    assert.deepEqual(planLoraRestore(null, false), { rows: [], notes: [] });
    assert.deepEqual(planLoraRestore({}, false), { rows: [], notes: [] });
  });
});

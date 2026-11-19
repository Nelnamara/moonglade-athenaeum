import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { sendImgRun } from "../src/loom-run.js";

/* A single send through the run road carries what its quote showed (review of 52b91ed3,
   2026-11-18). The Loom's Image tab sends a template prompt or x2-4 through sendImgRun; a single
   one used to go without an ask whenever the plan's total read as 0 -- a plan whose price could
   not be read (null) included -- and carried nothing, so a card gone by then charged. Now FREE is
   a total of exactly 0, that send carries expect_free, and anything else asks. The server half
   is dev/tests/test_quoted_free_more_roads.py. */

const here = path.dirname(fileURLToPath(import.meta.url));

const deps = (plan) => {
  const seen = { asked: 0, runs: [] };
  return {
    seen,
    csrf: async () => "tok",
    post: async () => plan,
    confirm: () => { seen.asked += 1; return true; },
    run: async (body) => { seen.runs.push(body); return { data: { jobs: [{ task_id: "t1" }] } }; },
  };
};

describe("sendImgRun", () => {
  const body = { prompt: "{a|b} glade", count: 1 };
  test("a single send the plan prices FREE goes with no ask and carries expect_free", async () => {
    const d = deps({ count: 1, total: 0 });
    const out = await sendImgRun(body, "x", d, { key: "k1", runId: "r1" });
    assert.equal(out.ok, true);
    assert.equal(d.seen.asked, 0);
    assert.equal(d.seen.runs[0].expect_free, true);
  });
  test("a single send whose price could not be read asks, and carries nothing", async () => {
    const d = deps({ count: 1, total: null });
    await sendImgRun(body, "x", d, { key: "k2", runId: "r2" });
    assert.equal(d.seen.asked, 1);
    assert.equal("expect_free" in d.seen.runs[0], false);
  });
  test("a priced single send asks, and carries nothing", async () => {
    const d = deps({ count: 1, total: 400 });
    await sendImgRun(body, "x", d, { key: "k3", runId: "r3" });
    assert.equal(d.seen.asked, 1);
    assert.equal("expect_free" in d.seen.runs[0], false);
  });
  test("a run of several always asks and carries its acknowledgement, not expect_free", async () => {
    const d = deps({ count: 2, total: 0, each: 0 });
    await sendImgRun({ ...body, count: 2 }, "x", d, { key: "k4", runId: "r4" });
    assert.equal(d.seen.asked, 1);
    assert.equal("expect_free" in d.seen.runs[0], false);
    assert.ok(d.seen.runs[0].ack);
  });
});

test("the dock's single send through the run road carries its badge's verdict", () => {
  const src = readFileSync(path.join(here, "..", "..", "gallery", "src", "gen", "useGenerate.js"), "utf8");
  assert.match(src, /runs\.sendSingle\(quotedSendBody\(runBody\(\), priceAnswer\)\)/);
});

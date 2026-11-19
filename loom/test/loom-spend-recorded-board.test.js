import { test } from "node:test";
import assert from "node:assert/strict";
import { tallySends, formatSpend, spendTooltip } from "../src/loom-core.js";

/* THE SPEND PILL ON A RECORDED BOARD (2026-11-18). The owner's C: board o1362bb read
   "~97,500 cr (+1 unk) spent": two renders sent from it on 2026-09-30, charged 70,000 and
   27,500 (catalog paid_credit == PixAI's own paidCredit), plus a July dev seed -- an example
   card marked done with a result id no render ever made, which the old media-id walk counted
   as an unknown.

   The figure is now the board's send record. The record's backfill of this board (pinned
   server-side in dev/tests/test_loom_spend.py, on this same shape) finds exactly the two
   sends with a task id; the seed was never sent, so it is not in the answer at all. This is
   that answer (ids replaced) and what the header makes of it: 97,500, no "+1 unk". */

const board = {
  acts: [
    { name: "Act 1 — Setup", cards: [{ id: "ex", status: "done", resultMid: "999888777" }] },
    { name: "Act 2 — Build", cards: [] },
    { name: "Act 3 — Payoff", cards: [] },
    { name: "Act 4", cards: [] },
    { name: "Act 5 — from your selection", cards: [{ id: "e1" }, { id: "e2" }] },
  ],
};

// /api/loom/spend's answer for this board after its backfill.
const sends = [
  { task_id: "800000000000000001", card: "e1", kind: "backfill", cost: 70000 },
  { task_id: "800000000000000002", card: "e2", kind: "backfill", cost: 27500 },
];

test("the recorded board reads its two real charges and nothing else", () => {
  const s = tallySends(sends, board);
  assert.equal(s.credits, 97500);
  assert.equal(s.paid, 2);
  assert.equal(s.unpriced, 0, "the seeded card was never sent, so it is not an unknown");
  assert.equal(formatSpend(s), "~97,500 cr");
  assert.match(spendTooltip(s), /2 renders sent from this board — 2 paid \(~97,500 credits\)/);
});

test("the money sits under the act the shots are in", () => {
  const s = tallySends(sends, board);
  const byName = Object.fromEntries(s.byAct.map((a) => [a.name, a.results ? formatSpend(a) : ""]));
  assert.equal(byName["Act 1 — Setup"], "");
  assert.equal(byName["Act 5 — from your selection"], "~97,500 cr");
});

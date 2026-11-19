import { test } from "node:test";
import assert from "node:assert/strict";
import { collectSpendMids, tallySpend, formatSpend, spendTooltip } from "../src/loom-core.js";

/* THE SPEND PILL ON A RECORDED BOARD (2026-11-18). The owner's C: board o1362bb read
   "~97,500 cr (+1 unk) spent". This is that board's shape as saved (ids replaced, prompts
   dropped) and the catalog's answer for it, read-only from the library the same day:

   - two rendered takes, sent from this board on 2026-09-30, whose tasks PixAI charged 70,000
     and 27,500 credits (catalog paid_credit == PixAI's own paidCredit in raw_tasks.jsonl);
   - one card marked done whose resultMid has no catalog row and no task at all: the example
     card of a board seeded in a July dev session, carried into this account's copy.

   The figure is what the ledger's definition says (CHANGELOG 2026-09-06, LOOM.md "~N cr
   spent"): the real charges of every render the board records, unknowns beside the total.
   This pins that reading so a change to it is a deliberate one. */

const board = {
  acts: [
    { name: "Act 1 — Setup", cards: [
      // The July seed: status done, a result id that never came from a render (no takes,
      // no task, no catalog row).
      { id: "ex", status: "done", resultMid: "999888777" },
    ] },
    { name: "Act 2 — Build", cards: [] },
    { name: "Act 3 — Payoff", cards: [] },
    { name: "Act 4", cards: [] },
    { name: "Act 5 — from your selection", cards: [
      { id: "e1", status: "done", resultMid: "700000000000000001", selectedTake: 1, takeSeq: 1,
        takes: [{ id: "t1", n: 1, mid: "700000000000000001", taskId: "800000000000000001",
                  source: "render", imported: false, quoted: { cost: 70000, free: false } }] },
      { id: "e2", status: "done", resultMid: "700000000000000002", selectedTake: 1, takeSeq: 1,
        takes: [{ id: "t1", n: 1, mid: "700000000000000002", taskId: "800000000000000002",
                  source: "render", imported: false, quoted: { cost: 27500, free: false } }] },
    ] },
  ],
};

// /api/loom/spend's answer for those ids: the seed's id has no row (absent key).
const rows = {
  "700000000000000001": { paid_credit: 70000, task_id: "800000000000000001" },
  "700000000000000002": { paid_credit: 27500, task_id: "800000000000000002" },
};

test("the recorded board reads its two real charges, and the seeded card as one unknown", () => {
  const col = collectSpendMids(board);
  assert.deepEqual(col.mids, ["999888777", "700000000000000001", "700000000000000002"]);
  const s = tallySpend(col, rows);
  assert.equal(s.credits, 97500);
  assert.equal(s.paid, 2);
  assert.equal(s.missing, 1, "the seeded result id has no catalog row");
  assert.equal(s.unpriced, 0);
  assert.equal(formatSpend(s), "~97,500 cr (+1 unk)");
  assert.match(spendTooltip(s), /2 paid \(~97,500 credits\).*1 with no catalog row/s);
});

test("each act's own line names where the money went", () => {
  const s = tallySpend(collectSpendMids(board), rows);
  const byName = Object.fromEntries(s.byAct.map((a) => [a.name, formatSpend(a)]));
  assert.equal(byName["Act 1 — Setup"], "1 unpriced");
  assert.equal(byName["Act 5 — from your selection"], "~97,500 cr");
});

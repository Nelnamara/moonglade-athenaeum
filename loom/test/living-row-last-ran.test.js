/* THE "LAST RAN" CELL ON A RUNS-ITSELF ROW (red team #18).

   The published-artwork sweep only writes an Activity ledger entry when it CHANGED
   something -- a fifteen-minute heartbeat that logged every quiet pass would bury the
   events that matter under its own noise. But the Panel's "last ran" cell read the ledger
   alone, so a healthy sweep that found nothing new showed "last ran —" beside a perfectly
   live "next in 12m" driven off schedule.json's own last_run. That is the steady state the
   short-circuit is designed to reach, and it read as broken automation.

   The schedule row's own last_run is the honest fallback: _living_stamp writes it on every
   completed tick, changed or not. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { lastRanAt } from "../../gallery/src/lib/livingRow.js";

test("a ledger event is still what the cell prefers", () => {
  assert.equal(lastRanAt({ ts: 1700 }, { last_run: 1200 }), 1700);
});

test("a quiet sweep that wrote nothing falls back to the schedule's own stamp", () => {
  // the exact steady state: no ledger event for this action, but the tick stamped it
  assert.equal(lastRanAt(null, { last_run: 1200 }), 1200);
  assert.equal(lastRanAt(undefined, { last_run: 1200 }), 1200);
});

test("a job that has genuinely never run still says nothing rather than guessing", () => {
  assert.equal(lastRanAt(null, { last_run: null }), null);
  assert.equal(lastRanAt(null, {}), null);
  assert.equal(lastRanAt(null, null), null);
  assert.equal(lastRanAt(undefined, undefined), null);
});

test("junk in either source answers null, never NaN or a 1970 date", () => {
  assert.equal(lastRanAt({ ts: 0 }, { last_run: 0 }), null);
  assert.equal(lastRanAt({}, { last_run: "not a time" }), null);
  assert.equal(lastRanAt(null, { last_run: "1200" }), 1200);
});

test("the Panel row reads the cell through this function, not the ledger alone", () => {
  const src = new URL("../../gallery/src/components/ControlPanelOverlay.jsx", import.meta.url);
  const jsx = readFileSync(src, "utf8");
  const block = jsx.slice(jsx.indexOf("---- RUNS ITSELF: the living library"));
  const row = block.slice(0, block.indexOf('<div className="mgcp-grid">'));
  assert.match(row, /lastRanAt\(last, row\)/);
  assert.doesNotMatch(row, /last \? fmtWhen\(last\.ts\) : "—"/);
});

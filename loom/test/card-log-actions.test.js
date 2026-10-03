import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* #68: the Account screen's card history labelled every row that was not a refund
   "– consumed", with an empty task line. PixAI's card log has four actions (consumed |
   refunded | revoked | expired) and now carries `expired` rows (PROBE_2026-10-02_site
   CHANGED), so cards that simply ran out read as if a generation used them. The words are a
   pure helper, driven here for real; the overlay is pinned to use it. */

import { cardLogRow } from "../../gallery/src/lib/cardLog.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const acct = readFileSync(path.resolve(__dirname, "../../gallery/src/components/AccountSubOverlay.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

describe("card history rows say what happened to the card (#68)", () => {
  test("an expired row reads expired, with no task", () => {
    // the shape list_kaisuuken_logs hands over for PixAI's expired row: no taskId, no creditCost
    const row = cardLogRow({ action: "expired", task_id: "", credit_cost: null, template_name: "Tsubaki.3 Only" });
    assert.equal(row.label, "– expired");
    assert.equal(row.task, "");
    assert.equal(row.refund, false);
  });

  test("a revoked row reads revoked, with no task even if one came back", () => {
    const row = cardLogRow({ action: "revoked", task_id: "2040084122530788759" });
    assert.equal(row.label, "– revoked");
    assert.equal(row.task, "");
  });

  test("consumed and refunded keep their words and their task", () => {
    assert.deepEqual(cardLogRow({ action: "consumed", task_id: "204" }), { label: "– consumed", refund: false, task: "204" });
    assert.deepEqual(cardLogRow({ action: "refunded", task_id: "205" }), { label: "↺ refunded", refund: true, task: "205" });
  });

  test("an action PixAI adds later shows as itself, never as consumed", () => {
    assert.equal(cardLogRow({ action: "transferred", task_id: "" }).label, "– transferred");
    assert.notEqual(cardLogRow({ action: "", task_id: "" }).label, "– consumed");
  });

  test("the Account overlay draws its rows from the helper, and the task line only when there is one", () => {
    assert.match(acct, /import \{ cardLogRow \} from "\.\.\/lib\/cardLog\.js"/);
    assert.ok(!acct.includes('"– consumed"'), "the overlay must not hard-code the consumed label");
    assert.match(acct, /row\.task \? <div className="acct-rowmeta">task \{row\.task\}<\/div> : null/);
  });
});

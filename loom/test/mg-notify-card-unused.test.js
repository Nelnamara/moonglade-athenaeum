import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";
import { render, query } from "../test-support/render.mjs";

/* DESIGN_3.22 2.4 rule 7 (review F2): a send that carried a free card and completed with a
   charge -- "the Activity row says the card was not used". The server writes card_unused on the
   done event beside paid_credit (moonglade/gallery.py's /api/task-status; dev/tests/test_jobs.py
   holds that half). This is the row's half, rendered: the owner-approved words, shown only on a
   done row that says so AND carries a real charge, in the warning the row already has for
   "finished, with a problem" (done_with_errors: the at-warn tint and the at-errmsg line). */
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROW = "gallery/src/notify/ActivityRow.jsx";
const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/notify.css"), "utf8");

const doneJob = {
  job_id: "task-77", type: "generate", status: "done", label: "Edited",
  ts: 1700000000, started_at: 1699999990,
};
const WORDS = "Your free card wasn't used. PixAI charged 8,000 credits.";

test("a done row whose card went unused says so, with the charge, in the row's warning", async () => {
  const $ = query(await render(ROW, "default",
    { job: { ...doneJob, card_unused: true, paid_credit: 8000 }, expanded: false }));
  const msg = $.byClass("at-errmsg");
  assert.equal(msg.length, 1, "one warning line");
  assert.equal(msg[0].text, WORDS);
  assert.match($.byClass("at-row")[0].attr("class"), /\bat-warn\b/,
    "the row takes the existing at-warn tint, as done_with_errors does");
});

test("no line without the server's mark, without a real charge, or on a row not done", async () => {
  for (const job of [
    { ...doneJob, paid_credit: 8000 },                                   // no card_unused
    { ...doneJob, card_unused: true },                                   // charge unknown
    { ...doneJob, card_unused: true, paid_credit: 0 },
    { ...doneJob, card_unused: true, paid_credit: "8000" },
    { ...doneJob, status: "running", card_unused: true, paid_credit: 8000 },
  ]) {
    const $ = query(await render(ROW, "default", { job, expanded: false }));
    assert.equal($.byClass("at-errmsg").length, 0, JSON.stringify(job));
    assert.doesNotMatch($.byClass("at-row")[0].attr("class"), /\bat-warn\b/, JSON.stringify(job));
  }
});

test("no new style was invented for it", () => {
  assert.match(css, /\.at-row\.at-warn\{/, "the existing warning row style is gone");
  assert.match(css, /\.at-errmsg\{/, "the existing message line style is gone");
  assert.doesNotMatch(css, /card[-_]?unused/i, "a new style was invented for this line");
});

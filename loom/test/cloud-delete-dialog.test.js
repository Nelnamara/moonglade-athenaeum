import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE DELETE-FROM-PIXAI CONFIRM DIALOG (owner, 2026-09-07; corrected the same day).

   The one irreversible action in this app is gated by a dialog whose numbers the owner reads
   to decide. Two things about it are pinned here:

     THE COUNTS ADD UP. The live check subtracts the images PixAI has already dropped from the
     headline -- they are NOT going anywhere -- and the dialog then has three quantities in it
     that a reader has to be able to reconcile: what will be deleted, what is already gone, and
     the batch membership the "you picked N; the other M" clause counts. They are computed in
     one place (lib/cloudDeleteCounts.js) so the arithmetic is a real import here rather than a
     regex over prose.

     THE WORDING MATCHES THE ARITHMETIC. A source guard, the established pattern for anything
     in a React component in this runner (there is no jsdom/React harness) -- see
     viewer-landing.test.js, whose suite this one sits beside.

   Plus the one client-side fact the dialog's own opening depends on: the preview fetch is
   bounded, a little above the server's own 12s ceiling. */

import { cloudDeleteCounts } from "../../gallery/src/lib/cloudDeleteCounts.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const api = src("api.js");
const menu = src("components/ActionsMenu.jsx");

describe("the counts reconcile", () => {
  /* The route's own fixture, from tests/test_purge.py's
     test_delete_preview_reads_each_selected_task_back_from_pixai_once: T1={a1,a2,a3} with
     a3 already deleted on PixAI, T2={b1,b2}, and [a1,b1] selected. */
  const ROUTE = { totals: { selected: 2, tasks: 2, media: 5, unselected: 3, local_only: 0 },
                  already_gone: 1 };

  test("what goes plus what is already gone is the whole membership", () => {
    const c = cloudDeleteCounts(ROUTE.totals, ROUTE.already_gone);
    assert.equal(c.willDelete, 4);
    assert.equal(c.alreadyGone, 1);
    assert.equal(c.willDelete + c.alreadyGone, c.inBatches,
      "the headline and the already-gone line must add up to the files in these batches");
    assert.equal(c.picked + c.alongside, c.inBatches,
      "'you picked N; the other M' counts the SAME membership -- 2 + 3 = 5, not 4");
  });

  test("both sums hold across the shapes the route can answer with", () => {
    const shapes = [
      // no live check at all (an older server, or over the 40-task cap)
      [{ selected: 2, tasks: 1, media: 4, unselected: 2, local_only: 0 }, undefined],
      // every file in the selection is already gone on PixAI
      [{ selected: 1, tasks: 1, media: 1, unselected: 0, local_only: 0 }, 1],
      // imports mixed in: they have no task, so they can never be "already gone"
      [{ selected: 3, tasks: 1, media: 5, unselected: 2, local_only: 2 }, 1],
      // pure imports: no task at all
      [{ selected: 2, tasks: 0, media: 2, unselected: 0, local_only: 2 }, 0],
    ];
    for (const [totals, gone] of shapes) {
      const c = cloudDeleteCounts(totals, gone);
      assert.equal(c.willDelete + c.alreadyGone, c.inBatches, JSON.stringify(totals));
      assert.equal(c.picked + c.alongside, c.inBatches, JSON.stringify(totals));
      assert.ok(c.willDelete >= 0, "the headline can never go negative");
    }
  });

  test("a nonsense answer cannot make the headline lie", () => {
    // Defensive: an older server sends no already_gone at all, and no answer may drive
    // the number of files "about to be deleted" below zero or above the membership.
    assert.equal(cloudDeleteCounts({ media: 3 }, undefined).willDelete, 3);
    assert.equal(cloudDeleteCounts({ media: 3 }, "not a number").willDelete, 3);
    assert.equal(cloudDeleteCounts({ media: 3 }, 99).willDelete, 0);
    assert.equal(cloudDeleteCounts({ media: 3 }, 99).alreadyGone, 3);
    assert.equal(cloudDeleteCounts(null, 1).inBatches, 0);
  });
});

describe("the wording matches the arithmetic", () => {
  test("the dialog derives its numbers in one place, not three", () => {
    assert.match(menu, /import \{ cloudDeleteCounts \} from "\.\.\/lib\/cloudDeleteCounts\.js";/);
    assert.match(menu, /cloudDeleteCounts\(t, data\.already_gone\)/);
    assert.doesNotMatch(menu, /Math\.max\(0, t\.media - goneNow\)/,
      "the subtraction moved into cloudDeleteCounts.js so the prose can be written "
      + "against numbers that are known to reconcile");
  });

  test('the already-gone files are "more", never "of them"', () => {
    // willDelete EXCLUDES them by construction, so "N of them are already gone" said they
    // were both going and staying. They are added to the headline now, not taken out of it.
    assert.match(menu, /One more is already gone on PixAI/);
    assert.match(menu, /\{goneNow\} more are already gone on PixAI/);
    assert.doesNotMatch(menu, /of them are already gone on PixAI/);
    assert.doesNotMatch(menu, /One of them is already gone on PixAI/);
  });

  test("when the headline is not the whole membership, the membership is named", () => {
    // "You picked 2; the other 3 come with their batches" under a headline of 4 is the
    // sum that did not add up. With gone files in the selection the dialog says what the
    // 5 is before it splits it.
    assert.match(menu, /Those tasks hold \{plural\(inBatches, "file", "files"\)\} in all/);
  });

  test("all-gone says so in the headline instead of a 0 that needs explaining", () => {
    assert.match(menu, /willDelete === 0 && goneNow > 0/);
    assert.match(menu, /Nothing will be deleted\. PixAI has already deleted/);
    // ...and the "more are already gone" line is suppressed there, so it is said once.
    assert.match(menu, /\{goneNow > 0 && willDelete > 0 && \(/);
  });

  test("the unverified and estimate lines still stand on their own", () => {
    // Order, per the ruling: headline, then already-gone, then unverified, then estimate.
    const gone = menu.indexOf("more is already gone on PixAI");
    const unver = menu.indexOf("could not be checked on PixAI just now");
    const est = menu.indexOf("These counts are an ");
    assert.ok(gone > 0 && unver > gone && est > unver,
      "the dialog's paragraphs must read in the order the ruling set them out in");
  });
});

describe("the preview fetch cannot hang the dialog open forever", () => {
  test("deletePreview carries a timeout, above the server's 12s ceiling", () => {
    // The route reads every selected task back from PixAI and bounds ITSELF at
    // DELETE_PREVIEW_LIVE_BUDGET_S = 12s. This is the backstop for the server going silent
    // rather than answering slowly: a little above the ceiling, so an ordinary slow answer
    // still arrives and only a real silence trips it.
    const ms = /export const DELETE_PREVIEW_MS = (\d+);/.exec(api);
    assert.ok(ms, "deletePreview's timeout must be a named constant, not a magic number");
    assert.ok(Number(ms[1]) > 12000 && Number(ms[1]) <= 30000,
      "the client timeout must sit above the server's 12s budget and still be a wait a "
      + "person will tolerate; found " + ms[1] + "ms");
    assert.match(api, /timeoutMs: DELETE_PREVIEW_MS/,
      "the constant must actually be handed to the request");
    assert.match(api, /timeoutMessage: "PixAI did not answer in time/,
      "a lapsed preview must say so in plain words, not fall through unexplained");
  });

  test("the transport honours it with an AbortController, and cleans the timer up", () => {
    assert.match(api, /new AbortController\(\)/);
    assert.match(api, /clearTimeout\(timer\)/);
    // timeoutMs/timeoutMessage are ours, not fetch's: they must not reach the browser.
    assert.match(api, /const \{ timeoutMs, timeoutMessage, \.\.\.rest \} = init \|\| \{\};/);
    assert.match(api, /fetch\(path, rest\)/);
  });

  test("a lapsed preview opens no dialog -- it falls back to the prose confirm", () => {
    const menu = src("components/ActionsMenu.jsx");
    assert.match(menu, /if \(data && data\.totals\) \{ setPreview\(\{ data, ids \}\); return; \}/,
      "an {error} answer is not a preview: `totals` is what makes it one");
    assert.match(menu, /\(data && data\.error \? data\.error \+ "\\n\\n" : ""\)/,
      "the reason the preview could not be loaded must reach the owner");
  });
});

describe("a task strip says what the task actually is", () => {
  /* OWNER'S WALK, 2026-09-07: the delete dialog's strips said "whole batch" over a single
     thumbnail. "whole batch" is not a title -- it is a claim about the OTHER files coming
     along with the one you picked, which is the whole reason this dialog exists. Over a
     task that made one image it is simply false, and it is false in the one dialog whose
     job is to tell you the truth about an irreversible action.

     Driven, not pattern-matched: the label is a plain function of the task's own media, so
     it is lifted out of the component and called for real (the same technique
     med-mg-notify-detail-tick.test.js uses on ActivityRow's derivations). Pattern-matching
     the strings would pass on a function that returned the right words for the wrong
     input, which is exactly the bug. */
  const m = /const taskLabel = (\(media\) => \{[\s\S]*?\n  \});/.exec(menu);
  assert.ok(m, "ActionsMenu no longer defines taskLabel -- the strip's label moved, so this "
    + "guard is blind. Re-point it rather than deleting it.");
  const taskLabel = new Function("return " + m[1])();
  const img = (id) => ({ media_id: id, is_video: false });
  const vid = (id) => ({ media_id: id, is_video: true });

  test("a task that made several files is a whole batch", () => {
    assert.equal(taskLabel([img("a"), img("b")]), "whole batch");
    assert.equal(taskLabel([img("a"), img("b"), img("c"), vid("d")]), "whole batch");
  });

  test("a task that made ONE file is not a batch and does not claim to be", () => {
    assert.equal(taskLabel([img("a")]), "single image");
    assert.notEqual(taskLabel([img("a")]), "whole batch");
  });

  test("a single video says video, under the ▶ the strip already draws on it", () => {
    assert.equal(taskLabel([vid("a")]), "single video");
  });

  test("the label is what the strip renders, not a constant beside it", () => {
    // The wiring half: taskLabel must actually reach the row, fed by that row's own media.
    assert.match(menu, /<div className="cd-tlbl">\{taskLabel\(tk\.media\)\}/);
    // ...and the old literal is gone from the task rows entirely, so it cannot come back
    // as a fallback nobody notices.
    assert.doesNotMatch(menu, /className="cd-tlbl">whole batch/);
  });
});

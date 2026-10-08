import { test, describe, afterEach, mock } from "node:test";
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

     THE WORDING MATCHES THE ARITHMETIC. The dialog (ActionsMenu.jsx's CloudDeleteModal) is
     RENDERED here with route-shaped previews (loom/test-support/render.mjs), and the tests read
     the sentences it actually shows -- not how its source happens to be spelled.

   Plus the one client-side fact the dialog's own opening depends on: the preview fetch is
   bounded, a little above the server's own 12s ceiling, and a preview that lapses falls back to
   the prose confirm (lib/cloudDeleteCore.js, driven here through the real api.js transport). */

import { cloudDeleteCounts } from "../../gallery/src/lib/cloudDeleteCounts.js";
import { askCloudDelete, previewFallbackText } from "../../gallery/src/lib/cloudDeleteCore.js";
import { DELETE_PREVIEW_MS, apiPost, deletePreview } from "../../gallery/src/api.js";
import { render, query } from "../test-support/render.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const menu = src("components/ActionsMenu.jsx");

/* The route's own fixture, from dev/tests/test_purge.py's
   test_delete_preview_reads_each_selected_task_back_from_pixai_once: T1={a1,a2,a3} with
   a3 already deleted on PixAI, T2={b1,b2}, and [a1,b1] selected. */
const ROUTE = { totals: { selected: 2, tasks: 2, media: 5, unselected: 3, local_only: 0 },
                already_gone: 1 };

/* ---- rendering the dialog ---------------------------------------------------------------- */

/** A /api/delete-preview answer: `totals` plus whatever top-level fields the case needs. */
function preview(totals, extra = {}) {
  return {
    totals: { selected: 0, tasks: 0, media: 0, unselected: 0, local_only: 0, ...totals },
    tasks: [], local_only: [], ...extra,
  };
}

/** CloudDeleteModal rendered with `data`: the parsed markup and its summary paragraphs' text,
    in order (paras[0] is the opening headline). */
async function dialog(data) {
  const $ = query(await render("gallery/src/components/ActionsMenu.jsx", "CloudDeleteModal",
    { data, ids: ["a1"], onCancel() {}, onProceed() {} }));
  const paras = $.byClass("cd-summary").map((p) => p.text);
  return { $, paras, all: paras.join("\n") };
}

/** The numbers a reader sees, read back out of the rendered sentences. */
function numbersShown(paras) {
  const head = paras[0];
  const n = (s) => (s === "One" ? 1 : Number(s));
  const grab = (re, s) => { const m = re.exec(s); return m ? n(m[1]) : null; };
  const goneLine = paras.find((p) => / more (is|are) already gone on PixAI/.test(p));
  const allGone = head.startsWith("Nothing will be deleted.");
  return {
    headline: allGone ? 0 : grab(/^(\d+) files? (?:across|will be removed)/, head),
    gone: allGone ? grab(/already deleted (\d+) files?/, head)
      : goneLine ? grab(/^(One|\d+) more (?:is|are) already gone/, goneLine) : 0,
    membership: grab(/hold (\d+) files? in all/, head),
    picked: grab(/you picked (\d+)/i, head),
    alongside: grab(/the other (\d+) comes? with/, head),
  };
}

describe("the counts reconcile", () => {
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
  test("the dialog derives its numbers in one place, not three", async () => {
    // The route's fixture, read back out of the rendered dialog: 4 go + 1 already gone = the
    // 5 in all, and 2 picked + 3 alongside = the same 5.
    const route = numbersShown((await dialog(preview(ROUTE.totals, { already_gone: 1 }))).paras);
    assert.deepEqual(route, { headline: 4, gone: 1, membership: 5, picked: 2, alongside: 3 });
    assert.equal(route.headline + route.gone, route.membership);
    assert.equal(route.picked + route.alongside, route.membership);

    // Every number shown is cloudDeleteCounts' number, including the answers a hand-rolled
    // `t.media - already_gone` would get wrong: a count of gone files larger than the batch
    // (clamped: "3", never "99" or a negative headline), and one that is not a number at all.
    const shapes = [
      [ROUTE.totals, 1],
      [ROUTE.totals, 2],
      [{ selected: 2, tasks: 1, media: 4, unselected: 2 }, undefined],
      [{ selected: 1, tasks: 1, media: 1, unselected: 0 }, 1],
      [{ selected: 3, tasks: 1, media: 5, unselected: 2, local_only: 2 }, 1],
      [{ selected: 2, tasks: 0, media: 2, unselected: 0, local_only: 2 }, 0],
      [{ selected: 1, tasks: 1, media: 3, unselected: 2 }, 99],
      [{ selected: 1, tasks: 1, media: 3, unselected: 2 }, "not a number"],
    ];
    for (const [totals, gone] of shapes) {
      const c = cloudDeleteCounts(totals, gone);
      const shown = numbersShown((await dialog(preview(totals, { already_gone: gone }))).paras);
      const why = JSON.stringify([totals, gone]);
      assert.equal(shown.headline, totals.tasks === 0 ? c.inBatches : c.willDelete, why);
      assert.equal(shown.gone, c.alreadyGone, why);
      if (shown.membership !== null) assert.equal(shown.membership, c.inBatches, why);
      if (shown.picked !== null) assert.equal(shown.picked, c.picked, why);
      if (shown.alongside !== null) assert.equal(shown.alongside, c.alongside, why);
    }
    const clamped = numbersShown((await dialog(preview(
      { selected: 1, tasks: 1, media: 3, unselected: 2 }, { already_gone: 99 }))).paras);
    assert.deepEqual([clamped.headline, clamped.gone], [0, 3],
      "an already_gone above the batch is clamped to it, so the dialog never says 99 or a negative");
  });

  test('the already-gone files are "more", never "of them"', async () => {
    // willDelete EXCLUDES them by construction, so "N of them are already gone" said they
    // were both going and staying. They are added to the headline now, not taken out of it.
    const one = await dialog(preview(ROUTE.totals, { already_gone: 1 }));
    assert.equal(one.paras[1], "One more is already gone on PixAI — deleted there, not here — so it "
      + "stays in your backup, because this is the last copy of it anywhere.");
    const two = await dialog(preview(ROUTE.totals, { already_gone: 2 }));
    assert.equal(two.paras[1], "2 more are already gone on PixAI — deleted there, not here — so they "
      + "stay in your backup, because these are the last copies of them anywhere.");
    for (const d of [one, two]) {
      assert.doesNotMatch(d.all, /of them (is|are) already gone on PixAI/);
      assert.doesNotMatch(d.all, /One of them is already gone on PixAI/);
    }
  });

  test("when the headline is not the whole membership, the membership is named", async () => {
    // "You picked 2; the other 3 come with their batches" under a headline of 4 is the
    // sum that did not add up. With gone files in the selection the dialog says what the
    // 5 is before it splits it.
    const gone = await dialog(preview(ROUTE.totals, { already_gone: 1 }));
    assert.equal(gone.paras[0], "4 files across 2 tasks will be deleted from your PixAI account and "
      + "from your backup. Those tasks hold 5 files in all: you picked 2, and the other 3 come "
      + "with their batches.");
    const single = await dialog(preview(
      { selected: 1, tasks: 1, media: 2, unselected: 1 }, { already_gone: 1 }));
    assert.match(single.paras[0], /Those tasks hold 2 files in all: you picked 1, and the other 1 comes with its batch\.$/);
    // ...and with nothing gone the headline IS the membership, so the plain clause stands.
    const none = await dialog(preview(ROUTE.totals, { already_gone: 0 }));
    assert.match(none.paras[0], /^5 files across 2 tasks .* You picked 2 files; the other 3 come with their batches\.$/);
    assert.doesNotMatch(none.all, /in all/);
  });

  test("all-gone says so in the headline instead of a 0 that needs explaining", async () => {
    const lone = await dialog(preview({ selected: 1, tasks: 1, media: 1, unselected: 0 },
      { already_gone: 1 }));
    assert.equal(lone.paras[0], "Nothing will be deleted. PixAI has already deleted 1 file across "
      + "1 task — deleted there, not here — and it stays in your backup, because this is the last "
      + "copy of it anywhere.");
    const many = await dialog(preview({ selected: 2, tasks: 2, media: 3, unselected: 1 },
      { already_gone: 3 }));
    assert.match(many.paras[0], /^Nothing will be deleted\. PixAI has already deleted 3 files across 2 tasks .* they stay in your backup, because these are the last copies of them anywhere\.$/);
    for (const d of [lone, many]) {
      assert.doesNotMatch(d.all, /\b0 files?\b/, "no headline of 0 for the reader to puzzle over");
      // ...and the "more are already gone" line is suppressed there, so it is said once.
      assert.equal(d.paras.filter((p) => /already (gone|deleted)/.test(p)).length, 1, d.all);
    }
  });

  test("the unverified and estimate lines still stand on their own", async () => {
    // Order, per the ruling: headline, then already-gone, then unverified, then estimate --
    // each its own paragraph, and only when there is something to say.
    const { paras } = await dialog(preview(ROUTE.totals,
      { already_gone: 1, unverified: 1, estimate: true }));
    const at = (re) => paras.findIndex((p) => re.test(p));
    const head = at(/will be deleted from your PixAI account/);
    const gone = at(/more is already gone on PixAI/);
    const unver = at(/^One task could not be checked on PixAI just now/);
    const est = at(/^These counts are an estimate from your library/);
    assert.deepEqual([head, gone, unver, est], [0, 1, 2, 3],
      "the dialog's paragraphs must read in the order the ruling set them out in");
    const plain = await dialog(preview(ROUTE.totals, { already_gone: 1 }));
    assert.doesNotMatch(plain.all, /could not be checked|estimate/);
  });
});

describe("the preview fetch cannot hang the dialog open forever", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; mock.timers.reset(); });

  const settle = () => new Promise((r) => setImmediate(r));
  const ok = (body) => ({ ok: true, status: 200, statusText: "OK", json: async () => body });
  /** A server whose answer the test hands over (or never does): fetch settles on `answer`,
      or rejects when its signal aborts, as a browser fetch does. */
  function server() {
    const calls = [];
    let answer = null;
    globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
      calls.push({ url, init });
      answer = resolve;
      if (init && init.signal) init.signal.addEventListener("abort", () => reject(new Error("aborted")));
    });
    return { calls, answer: (body) => answer(ok(body)) };
  }
  const TIMEOUT_TEXT = "PixAI did not answer in time, so the preview could not be built.";
  const PREVIEW = preview(ROUTE.totals, { already_gone: 1 });

  test("deletePreview carries a timeout, above the server's 12s ceiling", async () => {
    // The route reads every selected task back from PixAI and bounds ITSELF at
    // DELETE_PREVIEW_LIVE_BUDGET_S = 12s. This is the backstop for the server going silent
    // rather than answering slowly: a little above the ceiling, so an ordinary slow answer
    // still arrives and only a real silence trips it.
    assert.ok(DELETE_PREVIEW_MS > 12000 && DELETE_PREVIEW_MS <= 30000,
      "the client timeout must sit above the server's 12s budget and still be a wait a "
      + "person will tolerate; found " + DELETE_PREVIEW_MS + "ms");
    mock.timers.enable({ apis: ["setTimeout"] });

    // A silent server: still waited for at the server's own ceiling and one tick short of the
    // constant, then a plain-words {error} exactly at it.
    const silent = server();
    let lapsed;
    const asked = deletePreview(["a1", "b1"]).then((d) => { lapsed = d; });
    assert.equal(silent.calls[0].url, "/api/delete-preview");
    assert.deepEqual(JSON.parse(silent.calls[0].init.body), { media_ids: ["a1", "b1"] });
    mock.timers.tick(12000);
    await settle();
    assert.equal(lapsed, undefined, "at the server's own 12s ceiling the preview is still waited for");
    mock.timers.tick(DELETE_PREVIEW_MS - 12000 - 1);
    await settle();
    assert.equal(lapsed, undefined, "the constant is the wait the request is handed");
    mock.timers.tick(1);
    await settle();   // not `await asked`: a request that never lapses must fail here, not hang
    assert.deepEqual(lapsed, { error: TIMEOUT_TEXT },
      "a lapsed preview must say so in plain words, not fall through unexplained");
    await asked;

    // A slow server that answers inside the wait: the preview arrives.
    const slow = server();
    const arrived = deletePreview(["a1"]);
    mock.timers.tick(DELETE_PREVIEW_MS - 500);
    slow.answer(PREVIEW);
    assert.deepEqual(await arrived, PREVIEW);
  });

  test("the transport honours it with an AbortController, and cleans the timer up", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    // timeoutMs/timeoutMessage are ours, not fetch's: they must not reach the browser, and the
    // request carries the controller's signal instead.
    const answered = server();
    const p = deletePreview(["a1"]);
    const init = answered.calls[0].init;
    assert.ok(init.signal instanceof AbortSignal, "the request carries an AbortController's signal");
    assert.ok(!("timeoutMs" in init) && !("timeoutMessage" in init), Object.keys(init).join(", "));
    answered.answer(PREVIEW);
    assert.deepEqual(await p, PREVIEW);
    mock.timers.tick(DELETE_PREVIEW_MS * 2);
    assert.equal(init.signal.aborted, false,
      "an answered request's timer is cleared: nothing aborts it after the answer");

    // ...on the failure path too: a network error is a network error, and its timer goes.
    let failedInit;
    globalThis.fetch = async (url, i) => { failedInit = i; throw new Error("offline"); };
    assert.deepEqual(await deletePreview(["a1"]), { error: "network error: offline" });
    mock.timers.tick(DELETE_PREVIEW_MS * 2);
    assert.equal(failedInit.signal.aborted, false, "a failed request's timer is cleared too");

    // A call without a timeout is the bare fetch every other call has always made.
    const plain = server();
    const q = apiPost("/api/x", {});
    assert.equal(plain.calls[0].init.signal, undefined);
    assert.ok(!("timeoutMs" in plain.calls[0].init));
    plain.answer({ ok: true });
    assert.deepEqual(await q, { ok: true });
  });

  test("a lapsed preview opens no dialog -- it falls back to the prose confirm", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    const ids = ["a1", "b1"];
    /* askCloud's whole decision (lib/cloudDeleteCore.js), driven through the REAL deletePreview
       and transport: `answer` is what the fake server does, `yes` is the owner's reply to the
       prose confirm. */
    async function ask(answer, yes) {
      const seen = { dialog: [], confirm: [], deleted: [] };
      const srv = server();
      const flow = askCloudDelete(ids, {
        deletePreview,
        openDialog: (data) => seen.dialog.push(data),
        confirm: (msg) => { seen.confirm.push(msg); return yes; },
        deleteCloud: async (pids) => { seen.deleted.push(pids); },
      });
      let done = false;
      const settled = flow.then(() => { done = true; });
      if (answer === "silence") mock.timers.tick(DELETE_PREVIEW_MS);
      else srv.answer(answer);
      await settle();   // a flow that never finishes must fail here, not hang the run
      assert.ok(done, "the flow finishes once the preview answers or lapses");
      await settled;
      return seen;
    }

    // A real preview opens the dialog, and nothing else happens yet.
    const real = await ask(PREVIEW, true);
    assert.deepEqual(real.dialog, [PREVIEW]);
    assert.deepEqual([real.confirm, real.deleted], [[], []]);

    // A lapsed preview -- an {error}, not a preview: `totals` is what makes it one -- opens no
    // dialog. The prose confirm asks instead, and says why.
    const lapsedNo = await ask("silence", false);
    assert.deepEqual(lapsedNo.dialog, [], "an {error} answer is not a preview");
    assert.equal(lapsedNo.confirm.length, 1);
    assert.equal(lapsedNo.confirm[0], previewFallbackText(2, TIMEOUT_TEXT));
    assert.ok(lapsedNo.confirm[0].startsWith("Delete 2 selected file(s) from your PixAI account "
      + "AND locally?\n\n" + TIMEOUT_TEXT + "\n\n"),
      "the reason the preview could not be loaded must reach the owner");
    assert.match(lapsedNo.confirm[0], /deletes the whole TASK behind each selection/);
    assert.match(lapsedNo.confirm[0], /It is IRREVERSIBLE\./);
    assert.deepEqual(lapsedNo.deleted, [], "a no to the confirm deletes nothing");

    // Only a yes goes on to the delete (which still asks for the typed DELETE itself).
    const lapsedYes = await ask("silence", true);
    assert.deepEqual(lapsedYes.dialog, []);
    assert.deepEqual(lapsedYes.deleted, [ids]);

    // An answer that is neither a preview nor an error: the same confirm, with no reason line.
    const junk = await ask({ tasks: [] }, false);
    assert.deepEqual(junk.dialog, []);
    assert.equal(junk.confirm[0], previewFallbackText(2, undefined));
    assert.ok(junk.confirm[0].startsWith("Delete 2 selected file(s) from your PixAI account AND "
      + "locally?\n\nThe preview of exactly what that takes could not be loaded"));
    assert.deepEqual(junk.deleted, []);

    // The menu's "Delete from PixAI" is this flow, with the real confirm.
    assert.match(menu, /const askCloud = run\(\(\) => askCloudDelete\(ids, \{\n\s+deletePreview,\n\s+openDialog: \(data\) => setPreview\(\{ data, ids \}\),\n\s+confirm: \(msg\) => window\.confirm\(msg\),\n\s+deleteCloud,\n\s+\}\)\);/);
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

  test("the label is what the strip renders, not a constant beside it", async () => {
    // The wiring half: each rendered task row is labelled from that row's own media.
    const { $ } = await dialog(preview({ selected: 3, tasks: 3, media: 4, unselected: 1 }, {
      tasks: [
        { task_id: "T1", media: [{ media_id: "a1", selected: true }, { media_id: "a2" }] },
        { task_id: "T2", media: [{ media_id: "b1", selected: true }] },
        { task_id: "T3", media: [{ media_id: "c1", selected: true, is_video: true }] },
      ],
    }));
    const rows = $.byClass("cd-tlbl").map((row) => [
      row.children.find((c) => typeof c === "string"),
      textOf(row, "cd-tid"),
    ]);
    assert.deepEqual(rows, [
      ["whole batch", "task T1"],
      ["single image", "task T2"],
      ["single video", "task T3"],
    ]);
  });
});

/** The text of the one element with class `cls` inside `row`. */
function textOf(row, cls) {
  const hits = row.byClass(cls);
  assert.equal(hits.length, 1, "expected one ." + cls + " in " + row.html);
  return hits[0].text;
}

/* PUBLISHED ARTWORK (SCOPE_2026-09-26 E5). PixAI's own contract says its task delete also
   deletes the task's linked artwork, and every task in this dialog goes by the whole-task
   delete. The route counts what it knows (live artworkIds, else the catalog's artwork_id);
   the dialog says so in ONE more sentence of its own text -- no badge, no thumbnail marker --
   in the same words as the per-image dialog (moonglade_gallery.published_delete_note). */
describe("the published-artwork sentence", () => {
  const TWO_TASKS = { selected: 1, tasks: 2, media: 3, unselected: 2 };
  const ONE_TASK = { selected: 1, tasks: 1, media: 2, unselected: 1 };
  const HEAD_TWO = "3 files across 2 tasks will be deleted from your PixAI account and from your "
    + "backup. You picked 1 file; the other 2 come with their batches.";

  test("it is worded from the route's own counts, in the opening lines", async () => {
    // The opening paragraph -- the headline's own -- carries it, from data.published...
    const two = await dialog(preview(TWO_TASKS, { published: 2 }));
    assert.equal(two.paras[0], HEAD_TWO + " 2 of these are published on PixAI. Deleting the tasks "
      + "may remove the published artwork too.");
    // ...read as a number, as the route's JSON may hand it over...
    const asText = await dialog(preview(ONE_TASK, { published: "1" }));
    assert.match(asText.paras[0], / 1 of these is published on PixAI\. Deleting the task may remove the published artwork too\.$/);
    // ...and from data.published_unchecked when the catalog could not answer.
    const unchecked = await dialog(preview(TWO_TASKS, { published_unchecked: true }));
    assert.equal(unchecked.paras[0], HEAD_TWO + " Whether any of these are published on PixAI was "
      + "not checked — deleting a task may remove its published artwork too.");
    // Nothing known, nothing said.
    const quiet = await dialog(preview(TWO_TASKS, { published: 0, published_unchecked: false }));
    assert.equal(quiet.paras[0], HEAD_TWO);
  });

  test("the words: N of these, may remove, and never 'none published'", async () => {
    const said = async (totals, extra) => (await dialog(preview(totals, extra))).paras[0];
    assert.ok((await said(TWO_TASKS, { published: 3 })).endsWith(
      " 3 of these are published on PixAI. Deleting the tasks may remove the published artwork too."));
    assert.ok((await said(ONE_TASK, { published: 1 })).endsWith(
      " 1 of these is published on PixAI. Deleting the task may remove the published artwork too."));
    assert.ok((await said(TWO_TASKS, { published_unchecked: true })).endsWith(
      " Whether any of these are published on PixAI was not checked — deleting a task may remove its published artwork too."));
    // A blank count is "not known", never "none": no answer the route can give makes the
    // dialog say nothing is published.
    for (const extra of [{}, { published: 0 }, { published: null }, { published: "" },
      { published: 0, published_unchecked: false }, { published: 0, published_unchecked: true },
      { published: 2, published_unchecked: true, published_unchecked_tasks: 1 }]) {
      const all = (await dialog(preview(TWO_TASKS, extra))).all;
      assert.doesNotMatch(all, /none (of these )?(is|are) published/i, JSON.stringify(extra));
      assert.doesNotMatch(all, /not published on PixAI/, JSON.stringify(extra));
    }
  });

  /* Part-checked (review fix, 2026-09-26): some tasks answered live and some fell back to a
     catalog the artworks sync never filled. "Whether any of these are published was not
     checked" would contradict the count just given, so the dialog names how many TASKS went
     unchecked -- the same words as published_delete_note's part-checked form. */
  test("a part-checked selection says how many tasks went unchecked, never 'whether any'", async () => {
    const three = { selected: 1, tasks: 3, media: 3, unselected: 2 };
    const note = async (totals, extra) => {
      const head = (await dialog(preview(totals, extra))).paras[0];
      return head.slice(head.indexOf("batches.") + "batches. ".length);
    };
    // None counted, one of three tasks unchecked.
    assert.equal(await note(three,
      { published: 0, published_unchecked: true, published_unchecked_tasks: 1 }),
      "1 of the 3 tasks was not checked for published artwork — deleting a task may remove its published artwork too.");
    // A count given, and some tasks unchecked: the count, then how many went unchecked.
    assert.equal(await note(three,
      { published: 2, published_unchecked: true, published_unchecked_tasks: 2 }),
      "2 of these are published on PixAI. Deleting the tasks may remove the published artwork too. "
      + "2 of the 3 tasks were not checked for published artwork.");
    // A count given, the route not saying how many: still never "whether any".
    assert.equal(await note(TWO_TASKS, { published: 1, published_unchecked: true }),
      "1 of these is published on PixAI. Deleting the tasks may remove the published artwork too. "
      + "Some of the tasks were not checked for published artwork.");
    for (const extra of [
      { published: 0, published_unchecked: true, published_unchecked_tasks: 1 },
      { published: 2, published_unchecked: true, published_unchecked_tasks: 2 },
      { published: 1, published_unchecked: true },
    ]) {
      assert.doesNotMatch(await note(three, extra), /Whether any/, JSON.stringify(extra));
    }
    // Every task unchecked and nothing counted: the whole-selection sentence, unchanged.
    assert.ok((await note(TWO_TASKS,
      { published: 0, published_unchecked: true, published_unchecked_tasks: 2 }))
      .startsWith("Whether any of these are published on PixAI was not checked"));
  });

  test("no badge and no thumbnail marker: the strip is untouched", () => {
    const strip = menu.slice(menu.indexOf("const strip = (media) => ("),
      menu.indexOf("const taskLabel = (media) =>"));
    assert.ok(strip.length > 0);
    assert.doesNotMatch(strip, /publish/i);
  });
});

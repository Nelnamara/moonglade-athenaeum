/* The Loom Image tab's send of more than one image (review S2, Session M's spend rule).

   /api/generate is a SINGLE send since Session M (BUILD-w5-m review F2): it refuses a count
   other than 1 and a prompt that uses the template syntax, before any network call. The Loom's
   Image tab offers a Count of 1-4 and a free-text prompt, so its ×2-4 (and a prompt with a
   `{a|b}` group or a `__list__`) goes where the Generate dock sends them: the run road.

     imgSendRoute(body)   "generate" -- a plain count-1 send, today's /api/generate, unchanged;
                          "run"      -- everything else: /api/generate/plan, then /run.
     sendImgRun(...)      /plan (read-only: it writes nothing) -> the Loom's own confirm, a
                          window.confirm carrying the SERVER's numbers (count, total, the free
                          cards) -> ONE POST of /run with the acknowledgement copied from that
                          very plan (count, jobs, each, covered, total, digest -- exactly the
                          dock's ackOf). The server re-expands, re-quotes and refuses any
                          difference; nothing here is ever posted twice, and a lost answer is
                          reported, never re-sent.

   Pure but for the transport, which the caller injects (`deps`), so the node suite drives it
   with no React and no network:
     deps.post(path, body) -> the parsed answer    (gallery/src/api.js apiPost)
     deps.run(body)        -> {data} | {lost}      (gallery/src/gen/submitTask.js submitRun --
                                                    the ONE poster of /api/generate/run)
     deps.csrf()           -> the session token    (the account store's, as the dock's)
     deps.confirm(text)    -> true to send          (window.confirm, the Loom's confirm) */

import {
  ackOf, confirmCopy, hasSyntax, newRoll, newRunId, runLine, runSeedOf,
} from "../../gallery/src/gen/templateCore.js";

export const PLAN_PATH = "/api/generate/plan";

export function imgSendRoute(body) {
  const n = Number(body && body.count) || 1;
  return n > 1 || hasSyntax(body && body.prompt) ? "run" : "generate";
}

/* The run road's body: the Image tab's own body, Random (the Loom has no Matrix), and the run
   seed -- the seed field when it holds one in range, else a fresh roll. */
export function imgRunBody(body, roll) {
  const rs = runSeedOf(body && body.seed, roll);
  return { ...body, var_mode: "random", ...(rs != null ? { run_seed: rs } : {}) };
}

/* The confirm's text, from the server's own quote (the dock's words, confirmCopy). */
export function runConfirmText(plan, label) {
  const c = confirmCopy(plan);
  const lines = [label, "", c.title, c.credits, c.cards];
  if (c.note) lines.push(c.note);
  lines.push("", "Generate?");
  return lines.join("\n");
}

export const LOST_POST_WORDS = "No answer from the server — this may have started on PixAI. "
  + "Check the Activity tray before sending again.";

const inflight = new Set();

/* One send, once. Returns {ok: true, taskIds, note} | {ok: false, error?} (no error = the
   owner cancelled). `opts.key` latches per shot; `opts.onSending` fires after the confirm,
   before the POST; `opts.roll` / `opts.runId` are for the tests. */
export async function sendImgRun(body, label, deps, opts = {}) {
  const key = opts.key || "img";
  if (inflight.has(key)) return { ok: false, error: "Still sending the last one — wait for it." };
  inflight.add(key);
  try {
    const csrf = await deps.csrf();
    const rb = imgRunBody(body, opts.roll != null ? opts.roll : newRoll());
    const plan = await deps.post(PLAN_PATH, { ...rb, csrf });
    if (!plan || plan.error) return { ok: false, error: (plan && plan.error) || "Couldn't price this — nothing was sent." };
    if (plan.read_only) return { ok: false, error: "READ_ONLY is on in config.json, so nothing can be sent." };
    const multi = Number(plan.count) > 1;
    // Every send of more than one generation confirms (NOTES 2); a single one asks unless a
    // free card covers it, as the Loom's confirmSpend always has.
    if ((multi || Number(plan.total) > 0) && !deps.confirm(runConfirmText(plan, label))) return { ok: false };
    if (opts.onSending) opts.onSending();
    const runId = opts.runId || newRunId();
    const ans = await deps.run({ ...rb, csrf, run_id: runId, ...(multi ? { ack: ackOf(plan) } : {}) });
    if (!ans || ans.lost) return { ok: false, error: LOST_POST_WORDS };
    const d = ans.data || {};
    const jobs = Array.isArray(d.jobs) ? d.jobs : [];
    const taskIds = jobs.filter((j) => j && j.task_id).map((j) => String(j.task_id));
    if (!taskIds.length) return { ok: false, error: d.error || runLine(d).text };
    const line = runLine(d);
    return { ok: true, taskIds, note: line.kind === "warn" ? line.text : "" };
  } finally {
    inflight.delete(key);
  }
}

import { test, describe, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";

/* AUTOMATED JOBS DO NOT TOAST (owner's walk, 2026-09-07: "The automated tasks in the living
   library stack up completion toasts in the corner -- with the new tracking window I would
   like to remove the notice toasts completely").

   The living library runs sync, the artworks sweep, the video pull and the rest on its own
   cadence, and every one of them ended in a corner notice for a job nobody had asked for --
   several at once after a quiet night, stacked in the corner over whatever the owner was
   actually looking at. The Activity window now lists all of it, which is where the ruling
   puts them.

   ALL FOUR TERMINAL STATES, not just the successful one -- and that is what separates this
   rule from the `update` rule beside it in toastTransitions. Retiring a SUCCESS toast leans
   on something else having been watched (the update modal is its own receipt); there is
   nothing to watch for a job that started itself at 4am, so a scheduled sweep that fails,
   stalls or finishes with errors is a LINE in the Activity window rather than a corner
   notice, exactly like one that succeeds.

   And the row still arrives. Suppressing the toast must not suppress the JOB: the tracking
   window is the whole reason the toast can go, so every case below also asserts the row
   reached the store's own state, which is what <ActivityPanel> renders.

   DRIVEN, not read: refresh() is exported and everything under it is pure, so a fake fetch
   and a real toastStore are the only stand-ins needed. jobsStore is a deliberate module
   singleton (its `seeded`/`last` transition memory is the double-toast guard), so each test
   imports its own copy under a query string -- while toastStore stays the ONE un-queried
   instance, which is the same object the store under test really calls. */

const jobsURL = new URL("../../gallery/src/notify/jobsStore.js", import.meta.url).href;
const toasts = await import(new URL("../../gallery/src/notify/toastStore.js", import.meta.url).href);

/* toastStore auto-dismisses a non-sticky toast on a 5.2s timer and unmounts it 340ms after
   that. Neither is under test here, and a pending timer would both shuffle getToasts()
   under a later test and hold the runner's process open for five seconds after the last
   assertion. So the timers are neutered for this file only, and put back after it. */
const realSetTimeout = globalThis.setTimeout;
before(() => { globalThis.setTimeout = () => 0; });
after(() => { globalThis.setTimeout = realSetTimeout; });

let payload = { jobs: [] };
globalThis.fetch = async () => ({
  ok: true, status: 200, statusText: "OK", json: async () => payload,
});

let tab = 0;
let store = null;
let baseline = 0;

beforeEach(async () => {
  store = await import(jobsURL + "?tab=" + (++tab));
  baseline = toasts.getToasts().length;
});

/** One /api/jobs poll carrying `rows`. */
async function poll(rows) {
  payload = { jobs: rows };
  await store.refresh();
}

/** The toasts this test caused, in order. */
const fired = () => toasts.getToasts().slice(baseline);

const row = (over) => ({
  job_id: "j1", type: "panel", action: "sync", label: "Sync now", ...over,
});

const TERMINAL_STATES = ["done", "done_with_errors", "stale", "failed"];

describe("a job the library started by itself never toasts", () => {
  test("the first poll is a seed, so nothing already finished toasts on arrival", async () => {
    // The guard everything below rests on: without it a reload would re-toast the whole
    // backlog, and every assertion here would be measuring the wrong thing.
    await poll([row({ status: "done" })]);
    assert.deepEqual(fired(), []);
  });

  for (const status of TERMINAL_STATES) {
    test(`a scheduled job that ends "${status}" is silent`, async () => {
      await poll([]);                                    // seed
      await poll([row({ status, scheduled: true, error: "something went wrong" })]);
      assert.deepEqual(fired(), [],
        `a scheduled job ending "${status}" must not toast -- the Activity window has it`);
      // ...and it is genuinely IN the Activity window, which is the whole trade.
      assert.equal(store.getState().jobs.length, 1);
      assert.equal(store.getState().jobs[0].status, status);
    });

    test(`an owner-started job that ends "${status}" still toasts`, async () => {
      await poll([]);                                    // seed
      await poll([row({ status, error: "something went wrong" })]);
      assert.equal(fired().length, 1,
        `a job the owner pressed must still toast when it ends "${status}"`);
    });
  }

  test("a scheduled job is silent when it finishes mid-session, not only when it arrives done", async () => {
    // The real shape of a tick-started Panel job: the row appears running and turns
    // terminal on a later poll. That is the transition the rule has to catch, and a
    // born-terminal row (the artworks sweep) is the other one.
    await poll([row({ status: "running", scheduled: true })]);
    await poll([row({ status: "done", scheduled: true })]);
    assert.deepEqual(fired(), []);
    assert.equal(store.getState().jobs[0].status, "done");
  });

  test("the same job without the flag toasts on that same transition", async () => {
    await poll([row({ status: "running" })]);
    await poll([row({ status: "done" })]);
    assert.equal(fired().length, 1);
    assert.match(fired()[0].title, /Sync now/);
  });

  test("a scheduled row is remembered, so it is not re-judged on every later poll", async () => {
    // The short-circuit must still record the status (the claim and update short-circuits
    // above it do). If it returned without writing `last`, the row would read as unseen
    // forever -- and the moment the flag ever went missing from one poll's payload, the
    // stale `prev` would fire the toast the ruling just removed.
    await poll([]);
    await poll([row({ status: "done", scheduled: true })]);
    await poll([row({ status: "done" })]);   // same job, flag gone: still not a transition
    assert.deepEqual(fired(), []);
  });

  test("one automated job going quiet does not silence an owner's job in the same poll", async () => {
    // The corner case the owner's complaint is really about: a night's worth of automatic
    // jobs land together. His own job among them must still be reported.
    await poll([]);
    await poll([
      row({ job_id: "a", status: "done", scheduled: true }),
      row({ job_id: "b", status: "failed", scheduled: true }),
      row({ job_id: "c", status: "done", label: "Rebuild ALL thumbnails" }),
    ]);
    assert.equal(fired().length, 1);
    assert.match(fired()[0].title, /Rebuild ALL thumbnails/);
    assert.equal(store.getState().jobs.length, 3, "all three still reach the tracker");
  });
});

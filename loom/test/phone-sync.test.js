import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { MAX_WAIT_MS, POLL_MS, SYNC_ACTION, syncNow } from "../../gallery/src/lib/syncNow.js";

/* The pull's "Sync now" (Session Q, Q6): the one whitelisted Panel job, started once, polled with a
   bound, never retried. Every ending is run with a fake transport and a fake clock -- no network, no
   waiting. */

function harness(statuses, startAnswer) {
  const calls = [];
  let i = 0;
  let t = 0;
  const api = {
    post: async (path, body) => { calls.push(["POST", path, body]); return startAnswer || { ok: true, action: "sync" }; },
    get: async (path) => {
      calls.push(["GET", path]);
      const st = statuses[Math.min(i, statuses.length - 1)];
      i += 1;
      return st;
    },
  };
  const opts = { sleep: async (ms) => { t += ms; }, now: () => t };
  return { api, opts, calls };
}

describe("syncNow", () => {
  test("starts the ONE whitelisted job and polls the Panel's own status until it ends", async () => {
    const h = harness([{ status: "running" }, { status: "running" }, { status: "done" }]);
    const out = await syncNow(h.api, h.opts);
    assert.deepEqual(out, { state: "done", joined: false });
    assert.equal(SYNC_ACTION, "sync");
    assert.deepEqual(h.calls[0], ["POST", "/api/panel/run", { action: "sync" }]);
    assert.deepEqual(h.calls.slice(1).map((c) => c[1]), Array(3).fill("/api/panel/status"));
    // exactly one start request, ever: no retry
    assert.equal(h.calls.filter((c) => c[0] === "POST").length, 1);
  });

  test("it only ever talks to those two routes", async () => {
    const h = harness([{ status: "done" }]);
    await syncNow(h.api, h.opts);
    const paths = new Set(h.calls.map((c) => c[1]));
    assert.deepEqual([...paths].sort(), ["/api/panel/run", "/api/panel/status"]);
  });

  test("done with warnings is still done", async () => {
    const h = harness([{ status: "done_with_errors" }]);
    assert.equal((await syncNow(h.api, h.opts)).state, "done");
  });

  test("a failed or stopped job says so", async () => {
    const bad = harness([{ status: "failed" }]);
    assert.deepEqual(await syncNow(bad.api, bad.opts), { state: "failed", joined: false, error: "" });
    const h = harness([{ status: "cancelled" }]);
    assert.deepEqual(await syncNow(h.api, h.opts), { state: "failed", joined: false, error: "it was stopped" });
  });

  test("a job already running is joined, not an error: the person asked for a sync and one is happening", async () => {
    const h = harness([{ status: "running" }, { status: "done" }],
      { error: "a job is already running", http_status: 409 });
    const out = await syncNow(h.api, h.opts);
    assert.deepEqual(out, { state: "done", joined: true });
    assert.equal(h.calls.filter((c) => c[0] === "POST").length, 1);
  });

  test("any OTHER refusal ends it at once with the server's words, and nothing is polled", async () => {
    const h = harness([{ status: "done" }], { error: "READ_ONLY is on" });
    const out = await syncNow(h.api, h.opts);
    assert.deepEqual(out, { state: "error", joined: false, error: "READ_ONLY is on" });
    assert.equal(h.calls.length, 1);
    const net = harness([{ status: "done" }], { error: "network error: unreachable" });
    assert.equal((await syncNow(net.api, net.opts)).state, "error");
  });

  test("one flaky status read is skipped; the poll goes on", async () => {
    const h = harness([{ status: "running" }, { error: "network error: x" }, undefined, { status: "done" }]);
    assert.equal((await syncNow(h.api, h.opts)).state, "done");
  });

  test("the wait is bounded: a job that never ends hands over as 'timeout' (or 'busy' when it was joined)", async () => {
    const forever = harness([{ status: "running" }]);
    const out = await syncNow(forever.api, forever.opts);
    assert.equal(out.state, "timeout");
    assert.ok(forever.calls.filter((c) => c[0] === "GET").length <= Math.ceil(MAX_WAIT_MS / POLL_MS) + 1);
    const joined = harness([{ status: "running" }], { error: "a job is already running", http_status: 409 });
    assert.equal((await syncNow(joined.api, joined.opts)).state, "busy");
  });

  test("a custom action is passed through the same door (My Art's list read does not use it)", async () => {
    const h = harness([{ status: "done" }]);
    await syncNow(h.api, { ...h.opts, action: "sync" });
    assert.deepEqual(h.calls[0][2], { action: "sync" });
  });
});

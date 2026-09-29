import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  classifySubmit, classifySubmitStatus, submitsToCheck, failRender, markUnclear, abandonSubmit,
  adoptTask, beginRender, landTake, inFlight, needsRender,
} from "../src/loom-takes-core.js";
import { cardsToResume } from "../src/loom-core.js";

// Session P, BUILD-w5-p §3.3/§3.4 and review F3, F8, F14: the pure half of one render's
// lifecycle. A lost answer is UNCLEAR, never an error: the lock stays, nothing is re-sent,
// and the only ways out are the server's own record (submit-status) or the owner's release.

describe("classifySubmit", () => {
  test("a thrown fetch or an unreadable body is unclear", () => {
    assert.equal(classifySubmit({ threw: true }).kind, "unclear");
    assert.equal(classifySubmit({ status: 200, body: null }).kind, "unclear");
  });
  test("a task id is accepted; the server's unclear answers stay unclear", () => {
    assert.deepEqual(classifySubmit({ status: 200, body: { task_id: "T" } }), { kind: "accepted", taskId: "T" });
    assert.equal(classifySubmit({ status: 200, body: { error: "timeout", unclear: true } }).kind, "unclear");
    assert.equal(classifySubmit({ status: 409, body: { state: "sending" } }).kind, "unclear");
  });
  test("a JSON error is a definite refusal; the one-render-per-shot 409 is 'busy'", () => {
    assert.deepEqual(classifySubmit({ status: 200, body: { error: "no credits" } }), { kind: "refused", error: "no credits" });
    assert.equal(classifySubmit({ status: 409, body: { error: "This shot is already rendering (task …3f9a2c)." } }).kind, "busy");
  });
});

describe("classifySubmitStatus", () => {
  test("maps the journal's states", () => {
    assert.deepEqual(classifySubmitStatus({ state: "submitted", task_id: "T" }), { kind: "accepted", taskId: "T" });
    assert.equal(classifySubmitStatus({ state: "refused", error: "x" }).kind, "refused");
    assert.equal(classifySubmitStatus({ state: "not_sent" }).kind, "refused");
    assert.equal(classifySubmitStatus({ state: "sending" }).kind, "unclear");
    assert.equal(classifySubmitStatus({ state: "may_have_started" }).kind, "unclear");
    assert.equal(classifySubmitStatus({ state: "unknown" }).kind, "unclear");
  });
});

describe("resume: an unclear card is checked, never rendered", () => {
  const board = { acts: [{ cards: [
    { id: "a", status: "wip", pendingSubmitId: "S1" },
    { id: "b", status: "wip", pendingSubmitId: "S2", pendingTaskId: "T2", genStartedAt: 9 },
    { id: "c", status: "done", pendingSubmitId: "S3" },
  ] }] };
  test("submitsToCheck returns the unclear card once; cardsToResume keeps the task case", () => {
    const seen = Object.create(null);
    assert.deepEqual(submitsToCheck(board, seen), [{ id: "a", submitId: "S1", board: null }]);
    assert.deepEqual(submitsToCheck(board, seen), []);
    assert.deepEqual(cardsToResume(board, Object.create(null)), [{ id: "b", taskId: "T2", startedAt: 9 }]);
  });
});

describe("failures describe the ★ take (F14)", () => {
  const rendered = { id: "x", status: "wip", resultMid: "M1", pendingSubmitId: "S", pendingTaskId: "T" };
  test("a failed retake on a rendered shot leaves it done, with the failure recorded", () => {
    const c = failRender(rendered, { taskId: "T", state: "failed", msg: "content policy", at: "t" });
    assert.equal(c.status, "done");
    assert.deepEqual(c.lastAttempt, { state: "failed", msg: "content policy", at: "t" });
    assert.equal(c.pendingTaskId, null);
    assert.equal(needsRender(c), false, "Generate all does not pay for it again");
  });
  test("a failure on an unrendered shot is an error", () => {
    const c = failRender({ id: "y", status: "wip", pendingSubmitId: "S" }, { submitId: "S", state: "refused", msg: "no" });
    assert.equal(c.status, "error");
    assert.equal(needsRender(c), true);
  });
  test("a failure report for a render the card is not waiting for changes nothing", () => {
    assert.equal(failRender(rendered, { taskId: "OTHER" }), rendered);
    const sup = { ...rendered, supersededTasks: ["Told"] };
    assert.equal(failRender(sup, { taskId: "Told" }).supersededTasks, undefined);
  });
});

describe("unclear, adopt, release (F3, F8)", () => {
  const b = beginRender({ id: "z", status: "todo" }, { submitId: "S", board: "B" });
  test("unclear keeps the lock", () => {
    const u = markUnclear(b, "S", "The server didn't confirm this render.", "t");
    assert.equal(u.status, "wip");
    assert.equal(u.pendingSubmitId, "S");
    assert.equal(inFlight(u), true);
    assert.equal(beginRender(u, { submitId: "S2" }), null, "no second render while unclear");
  });
  test("adoptTask: the answer for this submit attaches the task; a stale one is superseded", () => {
    const a = adoptTask(b, "S", "T1");
    assert.equal(a.pendingTaskId, "T1");
    const other = adoptTask(a, "S-old", "T0");
    assert.deepEqual(other.supersededTasks, ["T0"]);
    assert.equal(landTake(other, { mid: "M0", taskId: "T0" }).outcome, "unselected");
  });
  test("release: the card settles and a NEW render (new submit id) is allowed; nothing re-sends the old one", () => {
    const u = markUnclear(b, "S", "x", "t");
    const r = abandonSubmit(u, "S", "t2");
    assert.equal(r.pendingSubmitId, null);
    assert.equal(r.lastAttempt.state, "abandoned");
    const again = beginRender(r, { submitId: "S2" });
    assert.equal(again.pendingSubmitId, "S2");
    assert.notEqual(again.pendingSubmitId, "S");
    assert.equal(abandonSubmit(again, "S", "t3"), again, "releasing the old id cannot touch the new render");
  });
});

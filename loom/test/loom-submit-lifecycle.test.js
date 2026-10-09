import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  classifySubmit, classifySubmitStatus, submitsToCheck, failRender, markUnclear, abandonSubmit,
  adoptTask, beginRender, landTake, inFlight, needsRender, cancelRender,
  goBlocked, sendUnclear, unsendableRefs, unsendableKind, cardForSubmit, cardForTask,
} from "../src/loom-takes-core.js";
import { cardsToResume, shotPayload, flat } from "../src/loom-core.js";

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

describe("the Go gate and the paused carve-out (BUILD-w5-p §3.3 step 1, §3.4)", () => {
  const sent = adoptTask(beginRender({ id: "p", status: "todo" }, { submitId: "S1", board: "B" }), "S1", "T1");
  test("a render this build sent keeps its submit id beside the task, and may still be superseded once PAUSED", () => {
    assert.equal(sent.pendingSubmitId, "S1");
    assert.equal(sent.pendingTaskId, "T1");
    assert.equal(beginRender(sent, { submitId: "S2" }), null, "a task being polled refuses a new render");
    const again = beginRender(sent, { submitId: "S2" }, { pausedOk: true });
    assert.ok(again, "the paused carve-out works for an adopted render too");
    assert.equal(again.pendingSubmitId, "S2");
    assert.deepEqual(again.supersededTasks, ["T1"]);
    assert.equal(landTake(again, { mid: "M1", taskId: "T1" }).outcome, "unselected",
      "the paused render's late clip lands without taking ★");
    const back = cancelRender(again, "S2", sent);
    assert.equal(back.pendingTaskId, "T1", "a lock that could not be saved puts the paused task back");
  });
  test("goBlocked: an outstanding or unclear send always blocks; a polled task blocks unless paused", () => {
    assert.equal(goBlocked({ id: "a" }, false), false);
    assert.equal(goBlocked({ id: "a", status: "wip" }, false), false, "a marker-less wip is not in flight");
    const out = beginRender({ id: "a" }, { submitId: "S" });
    assert.equal(goBlocked(out, false), true);
    assert.equal(goBlocked(out, true), true, "paused never frees a send whose answer is outstanding");
    assert.equal(goBlocked(sent, false), true);
    assert.equal(goBlocked(sent, true), false, "the paused carve-out");
    assert.equal(goBlocked({ id: "old", status: "wip", pendingTaskId: "T" }, true), false, "a pre-P paused render");
  });
  test("sendUnclear: only a send with no task whose last attempt is unclear shows the way-out", () => {
    const out = beginRender({ id: "a" }, { submitId: "S" });
    assert.equal(sendUnclear(out), false, "still being answered");
    const u = markUnclear(out, "S", "x", "t");
    assert.equal(sendUnclear(u), true);
    assert.equal(sendUnclear(adoptTask(u, "S", "T")), false, "a task id settles it");
    assert.equal(sendUnclear(abandonSubmit(u, "S", "t")), false, "released");
  });
});

describe("pictures the render route cannot send (open call 4, review F16)", () => {
  test("mirrors the server: digits and data: thumbnails go, anything else is refused before pricing", () => {
    assert.deepEqual(unsendableRefs({ images: ["733917871331404290", "data:image/png;base64,AA", ""] }), []);
    assert.deepEqual(unsendableRefs({ images: ["733917871331404290", "local_0123456789ab"] }), ["local_0123456789ab"]);
    assert.deepEqual(unsendableRefs({ images: [" local_0123456789ab "] }), ["local_0123456789ab"]);
    assert.deepEqual(unsendableRefs({ images: ["/thumbs/1.jpg"] }), ["/thumbs/1.jpg"]);
    assert.deepEqual(unsendableRefs({}), []);
  });
  test("spend review S6: an imported reference VIDEO or AUDIO is refused the same way (data: is no escape there)", () => {
    assert.deepEqual(unsendableRefs({ images: ["1"], video_refs: ["2"], audio_refs: ["3"] }), []);
    assert.deepEqual(unsendableRefs({ images: ["1"], video_refs: ["local_0123456789ab"] }), ["local_0123456789ab"]);
    assert.deepEqual(unsendableRefs({ audio_refs: ["local_abcdefabcdef"] }), ["local_abcdefabcdef"]);
    assert.deepEqual(unsendableRefs({ video_refs: ["data:video/mp4;base64,AA"] }), ["data:video/mp4;base64,AA"]);
    assert.deepEqual(unsendableRefs({ images: ["local_0123456789ab"], video_refs: ["local_abcdefabcdef"] }),
      ["local_0123456789ab", "local_abcdefabcdef"]);
    assert.deepEqual(unsendableRefs(null), []);
    assert.equal(unsendableKind({ images: ["local_0123456789ab"], video_refs: ["local_abcdefabcdef"] }), "picture");
    assert.equal(unsendableKind({ images: ["1"], video_refs: ["local_abcdefabcdef"] }), "video");
    assert.equal(unsendableKind({ audio_refs: ["local_abcdefabcdef"] }), "audio");
    assert.equal(unsendableKind({ images: ["1"] }), "");
  });
  test("S6 end to end: a shot citing an imported @video carries it in its payload, and the payload is refused", () => {
    const card = { id: "c1", title: "t", mode: "R2V", duration: 5, connect: "new", prompt: "go", cast: [],
      openFrame: { thumbId: "", source: "733917871331404290", desc: "", tag: "" }, closeFrame: {},
      refs: [{ id: "v1", kind: "video", tag: "@video1", source: "local_0123456789ab" }] };
    const proj = { name: "P", acts: [{ id: "a1", name: "Act", cards: [card] }], assets: [] };
    const p = shotPayload(flat(proj)[0], proj, (t, s) => t || s || null);
    assert.deepEqual(p.video_refs, ["local_0123456789ab"], "the card shows (and the payload carries) the imported video");
    assert.deepEqual(unsendableRefs(p), ["local_0123456789ab"]);
    assert.equal(unsendableKind(p), "video");
  });
});

describe("the drawer's events find their card by id, never by selection (review F7)", () => {
  const board = { acts: [{ cards: [
    { id: "A", pendingSubmitId: "SA", pendingTaskId: "TA" },
    { id: "B", pendingSubmitId: "SB" },
    { id: "C", supersededTasks: ["Told"] },
    { id: "D", pendingTaskId: "Told" },
  ] }] };
  test("by submit id", () => {
    assert.equal(cardForSubmit(board, "SB").id, "B");
    assert.equal(cardForSubmit(board, "nope"), null);
    assert.equal(cardForSubmit(board, ""), null, "no id finds nothing (never 'the first card')");
    assert.equal(cardForSubmit(null, "SB"), null);
  });
  test("by task id: the card polling it wins over one that superseded it", () => {
    assert.equal(cardForTask(board, "TA").id, "A");
    assert.equal(cardForTask(board, "Told").id, "D");
    assert.equal(cardForTask({ acts: [{ cards: [{ id: "C", supersededTasks: ["Tx"] }] }] }, "Tx").id, "C");
    assert.equal(cardForTask(board, ""), null);
    assert.equal(cardForTask(board, "nope"), null);
  });
});

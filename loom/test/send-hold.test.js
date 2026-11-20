// 3.21.2, L1 (DESIGN_3.22 "Live in master today"): a single send whose answer cannot show
// whether PixAI made the task shows "may have started" -- never friendlyGenErr's guess -- and the
// SAME send is held for 60 s, so the next tap posts nothing. Drives the real submitTask over a
// stubbed fetch, and pins the Loom tabs to the same shared module.
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  SEND_HOLD_MS, UNCLEAR_SEND_MSG, HELD_SEND_MSG, isUnclearAnswer, sendKey, makeSendHolds, unclearText,
} from "../../gallery/src/gen/sendHold.js";
import { submitTask } from "../../gallery/src/gen/submitTask.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

function rig(answers) {
  const posts = [];
  const queue = answers.slice();
  globalThis.fetch = async (url, init) => {
    posts.push({ url, body: JSON.parse(init.body) });
    const a = queue.shift();
    if (a instanceof Error) throw a;
    return { status: a.status || 200, json: async () => a.body };
  };
  globalThis.window = {};
  const lines = [];
  const emit = (p) => lines.push(p);
  let t = 1000;
  const clock = { now: () => t, step: (ms) => { t += ms; } };
  return { posts, lines, emit, clock, holds: makeSendHolds(clock.now) };
}

const BODY = { model_id: "M1", prompt: "a cat", count: 1 };

describe("the hold table", () => {
  test("holds for SEND_HOLD_MS, then lets the same send go", () => {
    let t = 0;
    const h = makeSendHolds(() => t);
    const k = sendKey("/api/generate", { b: 1, a: [2, { d: 3, c: 4 }] });
    assert.equal(k, sendKey("/api/generate", { a: [2, { c: 4, d: 3 }], b: 1 }), "key order is not the send");
    assert.notEqual(k, sendKey("/api/edit", { b: 1, a: [2, { d: 3, c: 4 }] }));
    h.hold(k);
    t = SEND_HOLD_MS - 1;
    assert.equal(h.held(k), true);
    t = SEND_HOLD_MS;
    assert.equal(h.held(k), false);
    assert.equal(SEND_HOLD_MS, 60000);
  });
  test("reads the server's unclear answer", () => {
    assert.equal(isUnclearAnswer({ unclear: true }), true);
    assert.equal(isUnclearAnswer({ state: "may_have_started" }), true);
    assert.equal(isUnclearAnswer({ error: "PixAI refused", state: "refused" }), false);
    assert.equal(isUnclearAnswer(null), false);
  });
});

describe("submitTask", () => {
  test("an unclear answer shows the may-have-started sentence and holds the same send", async () => {
    const r = rig([{ body: { error: "502 Bad Gateway", state: "may_have_started", unclear: true } },
                   { body: { task_id: "T2" } }]);
    const out = await submitTask("/api/generate", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.equal(out, null);
    assert.equal(r.lines.at(-1).text, UNCLEAR_SEND_MSG);
    assert.equal(r.lines.at(-1).kind, "err");
    const again = await submitTask("/api/generate", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.equal(again, null);
    assert.equal(r.lines.at(-1).text, HELD_SEND_MSG);
    assert.equal(r.posts.length, 1, "the held tap posted nothing");
    r.clock.step(SEND_HOLD_MS);
    const later = await submitTask("/api/generate", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.equal(later, "T2");
    assert.equal(r.posts.length, 2);
  });
  test("PixAI's own reason follows the sentence when the server has one", async () => {
    const r = rig([{ body: { error: "x", state: "may_have_started", unclear: true,
                             detail: "HTTP 403: NSFW_DETECTED -- flagged" } }]);
    await submitTask("/api/fix", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.equal(r.lines.at(-1).text, UNCLEAR_SEND_MSG + " PixAI's answer: HTTP 403: NSFW_DETECTED -- flagged");
    assert.equal(unclearText({ held: true, error: "wait" }), "wait");
    assert.equal(unclearText({ unclear: true, detail: "  " }), UNCLEAR_SEND_MSG);
  });
  test("no answer at all holds it too", async () => {
    const r = rig([new TypeError("Failed to fetch")]);
    await submitTask("/api/edit", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.match(r.lines.at(-1).text, /MAY still have been submitted/);
    await submitTask("/api/edit", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.equal(r.lines.at(-1).text, HELD_SEND_MSG);
    assert.equal(r.posts.length, 1);
  });
  test("a refusal is shown as before and holds nothing", async () => {
    const r = rig([{ body: { error: "not enough credits (INSUFFICIENT_BALANCE)", state: "refused" } },
                   { body: { task_id: "T3" } }]);
    await submitTask("/api/fix", BODY, { label: "x", emit: r.emit, holds: r.holds });
    assert.match(r.lines.at(-1).text, /credit balance/, "friendlyGenErr still words a refusal");
    assert.equal(await submitTask("/api/fix", BODY, { label: "x", emit: r.emit, holds: r.holds }), "T3");
  });
  test("a journalled Loom render is left to its journal", async () => {
    const r = rig([{ body: { error: "No clear answer from PixAI.", state: "may_have_started", unclear: true } },
                   { body: { task_id: "T4" } }]);
    const sent = { ...BODY, submit_id: "a".repeat(32) };
    await submitTask("/api/loom/generate", sent, { label: "x", emit: r.emit, holds: r.holds });
    assert.notEqual(r.lines.at(-1).text, UNCLEAR_SEND_MSG);
    assert.equal(await submitTask("/api/loom/generate", sent, { label: "x", emit: r.emit, holds: r.holds }), "T4");
  });
});

test("the Loom's Image / Edit / Reference / Fix tabs use the same hold", () => {
  const src = readFileSync(path.join(HERE, "..", "master-storyboard.jsx"), "utf8");
  assert.match(src, /from "\.\.\/gallery\/src\/gen\/sendHold\.js"/);
  const gen = src.slice(src.indexOf("const genImage = async"), src.indexOf("const routeImg ="));
  const run = src.slice(src.indexOf("const runGen = async"), src.indexOf("const routeGen ="));
  for (const [name, body] of [["genImage", gen], ["runGen", run]]) {
    assert.match(body, /sendHolds\.held\(holdKey\)/, name + " checks the hold before it sends");
    assert.match(body, /isUnclearAnswer\(d\)[\s\S]*sendHolds\.hold\(holdKey\)/, name + " holds an unclear answer");
    assert.match(body, /catch \{[\s\S]*sendHolds\.hold\(holdKey\)/, name + " holds a lost answer");
    assert.ok(body.indexOf("sendHolds.held(holdKey)") < body.indexOf("fetch("), name + ": checked before the POST");
  }
});

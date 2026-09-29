import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { mergeBoards, landTake, deleteTake, selectTake, takesOf, selectedTakeOf } from "../src/loom-takes-core.js";
import { makeSaveQueue } from "../src/loom-store-core.js";

// Session P, BUILD-w5-p §3.5 and review F5/F6: a stale save answers 409 and the tab merges.
// Takes are never lost; the remote board wins every other field; a delete in either tab
// sticks; a resolved render's markers do not come back.

const base = () => ({ name: "B", acts: [{ id: "a", name: "Act", cards: [
  { id: "c", title: "one", status: "done", resultMid: "M1", actualDur: 5, trimIn: 0, trimOut: null },
  { id: "d", title: "dep", status: "todo", anchor: { shot: "c", take: 1 } },
] }] });
const land = (p, mid, tid) => ({ ...p, acts: p.acts.map((a) => ({ ...a, cards: a.cards.map((c) => c.id !== "c" ? c
  : landTake({ ...c, status: "wip", pendingSubmitId: "S" + tid, pendingTaskId: tid }, { mid, taskId: tid }).card) })) });
const card = (p, id) => p.acts[0].cards.find((c) => c.id === id);

describe("mergeBoards", () => {
  test("two tabs landing different takes on one card keep both, renumbered", () => {
    const local = land(base(), "ML", "TL");
    const remote = { ...land(base(), "MR", "TR"), name: "renamed elsewhere" };
    const { project, changed } = mergeBoards(local, remote);
    const c = card(project, "c");
    assert.deepEqual(takesOf(c).map((t) => [t.n, t.mid]), [[1, "M1"], [2, "MR"], [3, "ML"]]);
    assert.equal(c.resultMid, "MR", "★ stays remote's");
    assert.equal(project.name, "renamed elsewhere", "remote wins other fields");
    assert.ok(changed.some((x) => x.id === "c" && x.star && x.renumbered), "the toast can name what moved");
  });

  test("F6a: a pending marker the other tab already resolved is not re-added", () => {
    const localStale = { ...base() };
    localStale.acts[0].cards[0] = { ...localStale.acts[0].cards[0], status: "wip", pendingSubmitId: "S3", pendingTaskId: "T3" };
    const remote = land(base(), "M3", "T3");     // the other tab landed T3
    const c = card(mergeBoards(localStale, remote).project, "c");
    assert.equal(c.pendingTaskId, null);
    assert.equal(c.status, "done");
    const resolved = { ...base() };
    resolved.acts[0].cards[0] = { ...resolved.acts[0].cards[0], status: "wip", pendingSubmitId: "S4" };
    const c2 = card(mergeBoards(resolved, base(), { resolvedSubmits: ["S4"] }).project, "c");
    assert.equal(c2.pendingSubmitId, undefined, "a submit known resolved is dropped");
    const c3 = card(mergeBoards(resolved, base()).project, "c");
    assert.equal(c3.pendingSubmitId, "S4", "an unresolved render in flight survives the merge");
    assert.equal(c3.status, "wip");
  });

  test("F6b: a take deleted in one tab is not brought back by the other", () => {
    let both = land(base(), "M2", "T2");
    const staleTab = JSON.parse(JSON.stringify(both));
    let deleter = { ...both, acts: both.acts.map((a) => ({ ...a, cards: a.cards.map((c) => c.id !== "c" ? c : deleteTake(c, 1, "now").card) })) };
    const c = card(mergeBoards(staleTab, deleter).project, "c");
    assert.deepEqual(takesOf(c).map((t) => t.mid), ["M2"]);
  });

  test("F6c: ★ is remote's when it has one, and the change is reported", () => {
    const two = land(base(), "M2", "T2");
    const local = { ...two, acts: two.acts.map((a) => ({ ...a, cards: a.cards.map((c) => c.id !== "c" ? c : selectTake(c, 1)) })) };
    const { project, changed } = mergeBoards(local, two);
    assert.equal(selectedTakeOf(card(project, "c")), 2);
    assert.ok(changed.some((x) => x.id === "c" && x.star));
  });

  test("a card only this tab has, holding takes, is kept", () => {
    const local = base();
    local.acts[0].cards.push({ id: "new", status: "done", resultMid: "MN" });
    const out = mergeBoards(local, base()).project;
    assert.ok(card(out, "new"));
  });
});

describe("the per-key save queue (F5): a tab never conflicts with itself", () => {
  test("an autosave in flight when the lock flush starts: both land, no 409", async () => {
    // A fake server with compare-and-swap.
    let rev = "r0", stored = "{}";
    const writes = [];
    let release;
    const gate = new Promise((r) => { release = r; });
    const write = async (key, json, baseRev) => {
      writes.push(baseRev);
      if (writes.length === 1) await gate;                        // the autosave is slow
      if (baseRev !== undefined && baseRev !== rev) return { conflict: true, value: stored, rev };
      stored = json; rev = "r" + writes.length; return { ok: true, rev };
    };
    const q = makeSaveQueue(write);
    q.setRev("k", "r0");
    const autosave = q.save("k", '{"edit":1}');
    const lock = q.save("k", '{"edit":1,"lock":1}');
    release();
    const [a, b] = await Promise.all([autosave, lock]);
    assert.equal(a.ok, true);
    assert.equal(b.ok, true);
    assert.deepEqual(writes, ["r0", "r1"], "the second write carried the first write's rev");
    assert.equal(stored, '{"edit":1,"lock":1}');
  });

  test("writes queued behind a pending one collapse to the newest text", async () => {
    const seen = [];
    let release;
    const gate = new Promise((r) => { release = r; });
    const q = makeSaveQueue(async (k, json) => { seen.push(json); if (seen.length === 1) await gate; return { ok: true, rev: "x" + seen.length }; });
    const p1 = q.save("k", "1");
    const p2 = q.save("k", "2");
    const p3 = q.save("k", "3");
    release();
    await Promise.all([p1, p2, p3]);
    assert.deepEqual(seen, ["1", "3"]);
  });

  test("a real conflict answers every write built on the stale view, and none of them is sent", async () => {
    let calls = 0;
    let release;
    const gate = new Promise((r) => { release = r; });
    const q = makeSaveQueue(async () => { calls += 1; await gate; return { conflict: true, value: "{}", rev: "remote" }; });
    const a = q.save("k", "1");
    const b = q.save("k", "2");
    release();
    const [ra, rb] = await Promise.all([a, b]);
    assert.equal(ra.conflict, true);
    assert.equal(rb.conflict, true);
    assert.equal(calls, 1);
  });

  test("a failed write is reported, never thrown", async () => {
    const q = makeSaveQueue(async () => { throw new Error("500"); });
    const r = await q.save("k", "1");
    assert.equal(r.failed, true);
    await q.idle("k");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { mergeBoards, mergeNotice, landTake, attachTake, deleteTake, selectTake, takesOf, selectedTakeOf } from "../src/loom-takes-core.js";
import { flat } from "../src/loom-core.js";
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

  test("F6b both ways: a delete made in the tab that saved first, or in this tab, sticks", () => {
    const both = land(base(), "M2", "T2");
    const stale = JSON.parse(JSON.stringify(both));
    const deleter = { ...both, acts: both.acts.map((a) => ({ ...a, cards: a.cards.map((c) => c.id !== "c" ? c : deleteTake(c, 1, "now").card) })) };
    assert.deepEqual(takesOf(card(mergeBoards(deleter, stale).project, "c")).map((t) => t.mid), ["M2"],
      "this tab deleted it; the other tab's stale copy does not bring it back");
  });

  test("S2a: F10's older-build re-roll followed by any conflict keeps every take", () => {
    // This build materialised takes 1 and 2 with ★ on 2; an older build re-rolled the shot:
    // resultMid is the new clip, and the old ★ clip went into attempts (withResult).
    const p = base();
    p.acts[0].cards[0] = { id: "c", title: "one", status: "done", resultMid: "M3", actualDur: 5, trimIn: 0, trimOut: null,
      takes: [{ id: "t1", n: 1, mid: "M1" }, { id: "t2", n: 2, mid: "M2" }], selectedTake: 2, takeSeq: 2,
      attempts: [{ media_id: "M2", at: "then" }] };
    assert.deepEqual(takesOf(card(p, "c")).map((t) => t.mid), ["M1", "M2", "M3"], "the strip before the conflict");
    const out = card(mergeBoards(JSON.parse(JSON.stringify(p)), JSON.parse(JSON.stringify(p))).project, "c");
    assert.deepEqual(takesOf(out).map((t) => t.mid), ["M1", "M2", "M3"], "take 2 is still on the board");
    assert.equal(out.resultMid, "M3");
  });

  test("S2b: a take deleted, then re-attached, survives the next merge -- and the re-attach clears its tombstone", () => {
    let c = { id: "c", title: "one", status: "done", resultMid: "A", actualDur: 5, trimIn: 0, trimOut: null };
    c = attachTake(c, { mid: "B", imported: true, at: "1" }).card;
    c = attachTake(c, { mid: "C", imported: true, at: "2" }).card;
    const nB = takesOf(c).find((t) => t.mid === "B").n;
    c = deleteTake(c, nB, "3").card;
    assert.deepEqual(c.deletedTakes, ["B"]);
    c = attachTake(c, { mid: "B", imported: true, at: "4" }).card;
    assert.equal((c.deletedTakes || []).includes("B"), false, "a clip that is a take again is not deleted");
    c = attachTake(c, { mid: "D", imported: true, at: "5" }).card;
    const p = base();
    p.acts[0].cards[0] = c;
    const out = card(mergeBoards(JSON.parse(JSON.stringify(p)), JSON.parse(JSON.stringify(p))).project, "c");
    assert.deepEqual(takesOf(out).map((t) => t.mid).sort(), ["A", "B", "C", "D"]);
  });

  test("S2b on a board saved before the fix: a tombstone beside a live take never deletes it", () => {
    const p = base();
    p.acts[0].cards[0] = { id: "c", title: "one", status: "done", resultMid: "D", actualDur: 5, trimIn: 0, trimOut: null,
      takes: [{ id: "t1", n: 1, mid: "A" }, { id: "t4", n: 4, mid: "B" }, { id: "t5", n: 5, mid: "D" }],
      selectedTake: 5, takeSeq: 5, deletedTakes: ["B"] };
    const out = card(mergeBoards(JSON.parse(JSON.stringify(p)), JSON.parse(JSON.stringify(p))).project, "c");
    assert.deepEqual(takesOf(out).map((t) => t.mid), ["A", "B", "D"]);
    assert.equal((out.deletedTakes || []).includes("B"), false, "the merged board drops the contradicting tombstone");
  });

  test("a landed render clears its clip's tombstone too", () => {
    const c0 = { id: "c", status: "wip", resultMid: "M1", pendingSubmitId: "S9", pendingTaskId: "T9", deletedTakes: ["M9", "Mx"] };
    const c1 = landTake(c0, { mid: "M9", taskId: "T9" }).card;
    assert.deepEqual(c1.deletedTakes, ["Mx"]);
  });

  test("red team: a rendered shot the other tab DELETED stays deleted", () => {
    const synced = base();
    const deleter = { ...base(), acts: [{ ...base().acts[0], cards: [base().acts[0].cards[1]] }] };
    const stale = { ...base(), name: "retitled here" };
    const out = mergeBoards(stale, deleter, { base: synced }).project;
    assert.equal(card(out, "c"), undefined, "the deleted shot came back");
  });

  test("red team: a split made against a stale board does not double the footage", () => {
    const synced = base();
    // This tab split c at 2.0s: left half keeps c (trimOut 2), right half is a new card on M1.
    const split = base();
    split.acts[0].cards[0] = { ...split.acts[0].cards[0], trimOut: 2 };
    split.acts[0].cards.splice(1, 0, { id: "c2", title: "one (2)", status: "done", resultMid: "M1", actualDur: 5, trimIn: 2, trimOut: null });
    const other = { ...base(), name: "renamed elsewhere" };
    const out = mergeBoards(split, other, { base: synced }).project;
    assert.equal(card(out, "c2"), undefined, "the stale split half was kept beside the untrimmed shot");
  });

  test("red team: a fresh render on a shot the other tab deleted is still kept", () => {
    const synced = base();
    const deleter = { ...base(), acts: [{ ...base().acts[0], cards: [base().acts[0].cards[1]] }] };
    const rendered = land(base(), "MNEW", "TNEW");
    const out = mergeBoards(rendered, deleter, { base: synced }).project;
    assert.ok(card(out, "c"), "a new (possibly paid) clip must not vanish");
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

/* GitHub #59 (option A): a conflict that undoes something made in this tab says so. The merge
   still keeps the other tab's board (a stale split would double footage, a deleted shot must not
   come back); it now also reports what it dropped -- `reverted` -- and keeps re-added shots
   (`kept`) apart from the ★ / take-number changes, so the toast stops calling a kept shot a
   take-number change. */
describe("mergeBoards reports what it undid (#59)", () => {
  const codes = (p) => { const m = {}; flat(p).forEach((e) => { m[e.c.id] = e.code; }); return m; };
  const notice = (local, out) => mergeNotice(out, { local: codes(local), merged: codes(out.project) });
  const twoActs = () => ({ name: "B", acts: [
    { id: "a", name: "Act 1", cards: [{ id: "c", title: "one", status: "done", resultMid: "M1", actualDur: 5, trimIn: 0, trimOut: null }] },
    { id: "b", name: "Act 2", cards: [
      { id: "e", title: "two", status: "done", resultMid: "M5", actualDur: 5, trimIn: 0, trimOut: null },
      { id: "f", title: "three", status: "todo" },
    ] },
  ] });
  const mids = (p) => new Set(flat(p).flatMap((e) => takesOf(e.c).map((t) => String(t.mid))));
  // THE INVARIANT: no take is ever lost. Every clip the other tab's board holds is on the merged
  // board, and so is every clip that landed in THIS tab since the last sync.
  const noTakeLost = (local, remote, synced, out) => {
    const got = mids(out.project), before = mids(synced);
    for (const m of mids(remote)) assert.ok(got.has(m), "the other tab's clip " + m + " was lost");
    for (const m of mids(local)) if (!before.has(m)) assert.ok(got.has(m), "the clip " + m + " that landed here was lost");
  };
  const stripAct = (p, actId) => ({ ...p, acts: p.acts.filter((a) => a.id !== actId) });
  const landOn = (c, mid, n) => landTake({ ...c, status: "wip", pendingSubmitId: "S" + n, pendingTaskId: "T" + n },
    { mid, taskId: "T" + n }).card;
  const ids = (p) => p.acts.flatMap((a) => a.cards.map((c) => c.id));

  test("a stale split is reported as a split of the shot it was cut from, with that shot's code", () => {
    const synced = base();
    const split = base();
    split.acts[0].cards[0] = { ...split.acts[0].cards[0], trimOut: 2 };
    split.acts[0].cards.splice(1, 0, { id: "c2", title: "one (cont.)", status: "done", resultMid: "M1", actualDur: 5, trimIn: 2, trimOut: null });
    const other = { ...base(), name: "renamed elsewhere" };
    const out = mergeBoards(split, other, { base: synced });
    assert.equal(card(out.project, "c2"), undefined);
    assert.deepEqual(out.reverted, [{ id: "c2", kind: "split", shot: "c" }]);
    assert.deepEqual(out.changed, [], "nothing about ★ or take numbers moved");
    assert.equal(notice(split, out), "Your takes were kept; other edits from this tab were replaced."
      + " Your split of A·01 was undone because the board changed in another tab.");
    noTakeLost(split, other, synced, out);
  });

  test("a split while the other tab re-trimmed the same shot is reported too", () => {
    const synced = base();
    const split = base();
    split.acts[0].cards[0] = { ...split.acts[0].cards[0], trimOut: 2 };
    split.acts[0].cards.push({ id: "c2", title: "one (cont.)", status: "done", resultMid: "M1", actualDur: 5, trimIn: 2, trimOut: null });
    const other = base();
    other.acts[0].cards[0] = { ...other.acts[0].cards[0], trimOut: 3.5 };
    const out = mergeBoards(split, other, { base: synced });
    assert.equal(card(out.project, "c").trimOut, 3.5, "the other tab's trim wins");
    assert.deepEqual(out.reverted, [{ id: "c2", kind: "split", shot: "c" }]);
    assert.match(notice(split, out), / Your split of A·01 was undone because the board changed in another tab\.$/);
    noTakeLost(split, other, synced, out);
  });

  test("a shot the other tab deleted is reported as removed", () => {
    const synced = base();
    const deleter = { ...base(), acts: [{ ...base().acts[0], cards: [base().acts[0].cards[1]] }] };
    const stale = { ...base(), name: "retitled here" };
    const out = mergeBoards(stale, deleter, { base: synced });
    assert.deepEqual(out.reverted, [{ id: "c", kind: "removed" }]);
    assert.match(notice(stale, out), / A·01 stays deleted: the other tab removed it\.$/);
    noTakeLost(stale, deleter, synced, out);
  });

  describe("ACT DELETED in the other tab", () => {
    test("(i) every card of the deleted act with no new footage stays gone and is reported act-removed", () => {
      const synced = twoActs();
      const remote = stripAct(twoActs(), "b");
      const local = { ...twoActs(), name: "retitled here" };
      const out = mergeBoards(local, remote, { base: synced });
      assert.deepEqual(out.project.acts.map((a) => a.id), ["a"]);
      assert.deepEqual(ids(out.project), ["c"]);
      assert.deepEqual(out.reverted, [{ id: "e", kind: "act-removed" }, { id: "f", kind: "act-removed" }]);
      assert.deepEqual(out.kept, []);
      assert.match(notice(local, out), / B·01 and B·02 stay deleted: the other tab removed their act\.$/);
      noTakeLost(local, remote, synced, out);
    });
    test("(ii) a fresh render on a card in the deleted act is kept, in the merged board's first act", () => {
      const synced = twoActs();
      const remote = stripAct(twoActs(), "b");
      const local = twoActs();
      local.acts[1].cards[0] = landOn(local.acts[1].cards[0], "MNEW", 7);
      const out = mergeBoards(local, remote, { base: synced });
      const first = out.project.acts[0];
      assert.equal(first.id, "a");
      assert.deepEqual(first.cards.map((c) => c.id), ["c", "e"], "kept at the end of the first act");
      assert.ok(takesOf(first.cards[1]).some((t) => t.mid === "MNEW"));
      assert.deepEqual(out.kept, [{ id: "e", act: "Act 1", actGone: true, actRestored: false }]);
      assert.deepEqual(out.reverted, [{ id: "f", kind: "act-removed" }], "its unrendered neighbour stays gone");
      assert.deepEqual(out.changed, [], "a kept shot is not a ★ / take-number change");
      const msg = notice(local, out);
      assert.match(msg, / B·01 was kept in Act 1 because its act was deleted in the other tab\./);
      assert.match(msg, / B·02 stays deleted: the other tab removed its act\.$/);
      assert.doesNotMatch(msg, /take numbers changed/);
      noTakeLost(local, remote, synced, out);
    });
    test("(iii) the other tab deleted every act: the act is re-created holding the kept card", () => {
      const synced = twoActs();
      const remote = { ...twoActs(), acts: [] };
      const local = twoActs();
      local.acts[1].cards[0] = landOn(local.acts[1].cards[0], "MNEW", 8);
      const out = mergeBoards(local, remote, { base: synced });
      assert.deepEqual(out.project.acts.map((a) => [a.id, a.name, a.cards.map((c) => c.id)]), [["b", "Act 2", ["e"]]]);
      assert.deepEqual(out.kept, [{ id: "e", act: "Act 2", actGone: true, actRestored: true }]);
      assert.deepEqual(out.reverted.map((x) => [x.id, x.kind]), [["c", "act-removed"], ["f", "act-removed"]]);
      assert.match(notice(local, out), / B·01 was kept and its act is back: the other tab had deleted it\./);
      noTakeLost(local, remote, synced, out);
    });
    test("(iv) the other tab MOVED the card to another act: no duplicate, nothing reported", () => {
      const synced = twoActs();
      const remote = twoActs();
      const moved = remote.acts[1].cards.shift();
      remote.acts[0].cards.push(moved);
      const local = twoActs();
      local.acts[1].cards[0] = landOn(local.acts[1].cards[0], "MNEW", 9);
      const out = mergeBoards(local, remote, { base: synced });
      assert.deepEqual(ids(out.project), ["c", "e", "f"], "e once, where the other tab put it");
      assert.ok(takesOf(out.project.acts[0].cards[1]).some((t) => t.mid === "MNEW"), "its new take rode along");
      assert.deepEqual(out.reverted, []);
      assert.deepEqual(out.kept, []);
      noTakeLost(local, remote, synced, out);
    });
  });

  test("a card that landed here and survives in its own act is kept without a word about acts", () => {
    const local = base();
    local.acts[0].cards.push({ id: "new", status: "done", resultMid: "MN" });
    const out = mergeBoards(local, base(), { base: base() });
    assert.deepEqual(out.kept, [{ id: "new", act: "Act", actGone: false, actRestored: false }]);
    assert.deepEqual(out.changed, []);
    assert.equal(notice(local, out), "Your takes were kept; other edits from this tab were replaced.");
  });

  test("the notice names three shots at most, then how many more; with nothing undone it is today's sentence", () => {
    const local = { acts: [{ id: "a", cards: "pqrst".split("").map((id) => ({ id })) }] };
    const out = { project: { acts: [] }, changed: [], kept: [],
      reverted: "pqrst".split("").map((id) => ({ id, kind: "removed" })) };
    assert.match(mergeNotice(out, { local: codes(local), merged: {} }),
      / A·01, A·02, A·03 and 2 more stay deleted: the other tab removed them\.$/);
    assert.equal(mergeNotice({ changed: [], kept: [], reverted: [] }, { local: {}, merged: {} }),
      "Your takes were kept; other edits from this tab were replaced.");
    assert.equal(mergeNotice({ changed: [{ id: "x", star: true }], kept: [], reverted: [] }, { local: {}, merged: { x: "C·04" } }),
      "Your takes were kept; other edits from this tab were replaced. ★ or take numbers changed on C·04.");
    assert.equal(mergeNotice(undefined, undefined), "Your takes were kept; other edits from this tab were replaced.");
  });
});

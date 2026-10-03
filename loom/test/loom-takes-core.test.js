import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  takesOf, selectedTakeOf, takeSeqOf, selectedTakeView, withTakes, landTake, attachTake,
  selectTake, deleteTake, snapshotSettings, reuseSettingsPatch, spendMidsOf, needsRender,
  inFlight, stripInFlight, shouldSave, beginRender, cancelRender, cutPointOf, makeAnchor,
} from "../src/loom-takes-core.js";
import { ribbonPairs, frameUrl } from "../src/loom-ribbon-core.js";
import { collectSpendMids, flat, durOf } from "../src/loom-core.js";
import { buildDuplicateCard, splitCardAt, withResult, buildExportClips } from "../src/loom-mutations.js";
import { cutSegments } from "../src/loom-bed-core.js";
import { edlPlan } from "../src/loom-edl-core.js";

// Session P, P1 (BUILD-w5-p §1, review F1, F4, F9, F10, F14). The fixture is a synthetic
// copy of a populated board in the real shape: three acts; rendered (with a re-roll in
// attempts, trims and a crop), imported, split and unrendered cards; frames by mediaId and
// by thumbId; cast. Every VIEW must leave it byte-identical: opening a board writes nothing.
const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = readFileSync(path.join(here, "fixtures", "board-legacy.json"), "utf8");
const board = () => JSON.parse(FIXTURE);
const cardOf = (p, id) => flat(p).find((e) => e.c.id === id).c;

describe("legacy boards: take 1 is derived, never stored", () => {
  test("a rendered legacy card is take 1, selected, with its own trims and crop", () => {
    const c = cardOf(board(), "c1");
    const ts = takesOf(c);
    assert.equal(ts.length, 1);
    assert.deepEqual({ n: ts[0].n, mid: ts[0].mid, source: ts[0].source, imported: ts[0].imported },
      { n: 1, mid: "200000000000000001", source: "legacy", imported: false });
    assert.equal(ts[0].trimIn, 0.4);
    assert.equal(ts[0].trimOut, 4.6);
    assert.deepEqual(ts[0].crop, { x: 0.1, y: 0.05, w: 0.8, h: 0.9 });
    assert.equal(selectedTakeOf(c), 1);
    assert.equal(takeSeqOf(c), 1);
    assert.equal(c.takes, undefined, "nothing was written onto the card");
  });

  test("old re-rolls in attempts[] are NOT takes (open call 1): ledger only", () => {
    const c = cardOf(board(), "c1");
    assert.deepEqual(takesOf(c).map((t) => t.mid), ["200000000000000001"]);
    assert.deepEqual(spendMidsOf(c).mids.sort(), ["200000000000000000", "200000000000000001"]);
  });

  test("an imported legacy card's take is imported; an unrendered card has none", () => {
    const p = board();
    assert.equal(takesOf(cardOf(p, "c2"))[0].imported, true);
    assert.deepEqual(takesOf(cardOf(p, "c4")), []);
    assert.equal(selectedTakeOf(cardOf(p, "c4")), null);
  });

  test("every view leaves a copy of the populated board byte-identical", () => {
    const p = board();
    const before = JSON.stringify(p);
    flat(p).forEach(({ c }) => {
      takesOf(c); selectedTakeOf(c); takeSeqOf(c); selectedTakeView(c); spendMidsOf(c);
      needsRender(c); inFlight(c);
    });
    collectSpendMids(p);
    assert.equal(JSON.stringify(p), before);
    assert.equal(shouldSave(FIXTURE, FIXTURE), false, "the loaded text is never written back");
    assert.equal(shouldSave(before, FIXTURE), true, "a different text is");
  });

  test("the spend ledger counts an old board exactly as before", () => {
    const got = collectSpendMids(board());
    assert.deepEqual(got.mids, ["200000000000000001", "200000000000000000", "200000000000000005"]);
    assert.equal(got.imported, 1);
  });
});

const rendering = (c, extra) => ({ ...c, status: "wip", pendingSubmitId: "S2", pendingTaskId: "T2",
  pendingSettings: { mode: "I2V", sentPrompt: "p2" }, pendingAnchor: null, pendingBoard: "B", genStartedAt: 5, ...(extra || {}) });

describe("landTake: every render appends a take and selects it", () => {
  test("appends take 2, selects it, mirrors it, resets trims and crop, clears the markers", () => {
    const c0 = rendering(cardOf(board(), "c1"));
    const { card, outcome } = landTake(c0, { mid: "M2", taskId: "T2", dur: 5.2, at: "2026-09-29T00:00:00Z", board: "B" });
    assert.equal(outcome, "landed");
    assert.deepEqual(card.takes.map((t) => [t.n, t.mid, t.source]),
      [[1, "200000000000000001", "legacy"], [2, "M2", "render"]]);
    assert.equal(card.selectedTake, 2);
    assert.equal(card.takeSeq, 2);
    assert.equal(card.resultMid, "M2");
    assert.equal(card.actualDur, 5.2);
    assert.equal(card.trimIn, 0);
    assert.equal(card.trimOut, null);
    assert.equal(card.crop, undefined);
    assert.equal(card.status, "done");
    ["pendingTaskId", "pendingSubmitId", "pendingSettings", "pendingAnchor", "pendingBoard", "genStartedAt"]
      .forEach((k) => assert.equal(card[k], null, k));
    // The outgoing take kept its own cut.
    assert.equal(card.takes[0].trimIn, 0.4);
    assert.equal(card.takes[0].trimOut, 4.6);
    assert.deepEqual(card.takes[0].crop, { x: 0.1, y: 0.05, w: 0.8, h: 0.9 });
    // The snapshot the submit captured rides on the take.
    assert.deepEqual(card.takes[1].settings, { mode: "I2V", sentPrompt: "p2" });
    assert.deepEqual(card.attempts, [{ media_id: "200000000000000000", at: "2026-09-01T10:00:00Z" }], "attempts untouched");
  });

  test("an unknown task id changes nothing (not-owned)", () => {
    const c0 = rendering(cardOf(board(), "c1"));
    const r = landTake(c0, { mid: "MX", taskId: "T-other" });
    assert.equal(r.outcome, "not-owned");
    assert.equal(r.card, c0);
  });

  test("F1: a late repeat of an OLD task never clears the markers of the render in flight", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2", board: "B" }).card;
    // The owner re-renders: T3 is in flight.
    c = { ...c, status: "wip", pendingSubmitId: "S3", pendingTaskId: "T3", pendingBoard: "B", pendingSettings: { mode: "I2V" } };
    const late = landTake(c, { mid: "M2", taskId: "T2", board: "B" });
    assert.equal(late.outcome, "repeat");
    assert.equal(late.card.pendingTaskId, "T3");
    assert.equal(late.card.pendingSubmitId, "S3");
    assert.equal(late.card.status, "wip");
    const next = landTake(late.card, { mid: "M3", taskId: "T3", board: "B" });
    assert.equal(next.outcome, "landed");
    assert.equal(next.card.selectedTake, 3);
    assert.equal(next.card.resultMid, "M3");
  });

  test("a superseded (paused) task lands WITHOUT taking ★", () => {
    let c = rendering(cardOf(board(), "c1"), { supersededTasks: ["T1old"] });
    const r = landTake(c, { mid: "Mold", taskId: "T1old" });
    assert.equal(r.outcome, "unselected");
    assert.equal(r.card.resultMid, "200000000000000001");
    assert.equal(r.card.pendingTaskId, "T2", "the live render is untouched");
    assert.equal(r.card.supersededTasks, undefined);
    assert.equal(takesOf(r.card).find((t) => t.mid === "Mold").n, 2);
  });

  test("F4: a landing from another board never lands on a copy", () => {
    const c = rendering(cardOf(board(), "c1"), { pendingBoard: "A" });
    assert.equal(landTake(c, { mid: "M2", taskId: "T2", board: "COPY" }).outcome, "not-owned");
  });

  test("numbering stays monotonic after a delete", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2" }).card;
    c = selectTake(c, 1);
    c = deleteTake(c, 2, "now").card;
    c = { ...c, status: "wip", pendingSubmitId: "S3", pendingTaskId: "T3" };
    c = landTake(c, { mid: "M3", taskId: "T3" }).card;
    assert.deepEqual(c.takes.map((t) => t.n), [1, 3], "take 2 is never reissued");
  });

  test("a failed, refused or missing report never creates a take", () => {
    const c = rendering(cardOf(board(), "c1"));
    assert.equal(landTake(c, { mid: "", taskId: "T2" }).outcome, "invalid");
    assert.equal(landTake(c, null).outcome, "invalid");
  });
});

describe("F10: a render landed by an older build is never dropped", () => {
  test("an older build's withResult on a materialised card, then ★ select: M3 survives as a take", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2" }).card;
    // An older build re-rolls: it overwrites resultMid and files M2 in attempts, never
    // looking at takes[].
    const old = withResult(c, { status: "done", resultMid: "M3", trimIn: 0, trimOut: null }, "t");
    assert.deepEqual(takesOf(old).map((t) => t.mid), ["200000000000000001", "M2", "M3"]);
    assert.equal(selectedTakeOf(old), 3);
    const after = selectTake(old, 1);
    assert.deepEqual(takesOf(after).map((t) => t.mid), ["200000000000000001", "M2", "M3"]);
    assert.equal(after.resultMid, "200000000000000001");
    assert.ok(spendMidsOf(after).mids.includes("M3"), "the paid render stays in the ledger");
  });
});

describe("selectTake: trims and crop are per take (F9)", () => {
  test("round-trips each take's own cut", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2", dur: 5 }).card;
    c = { ...c, trimIn: 1, trimOut: 3, crop: { x: 0, y: 0, w: 0.5, h: 0.5 } };   // the Edit Bay trims take 2 on the card
    c = selectTake(c, 1);
    assert.equal(c.resultMid, "200000000000000001");
    assert.equal(c.trimIn, 0.4);
    assert.equal(c.trimOut, 4.6);
    c = selectTake(c, 2);
    assert.equal(c.trimIn, 1);
    assert.equal(c.trimOut, 3);
    assert.deepEqual(c.crop, { x: 0, y: 0, w: 0.5, h: 0.5 });
    assert.equal(selectedTakeView(c).trimOut, 3, "the view reads the card, never a stale stored copy");
  });

  test("an unknown take number changes nothing", () => {
    const c = cardOf(board(), "c1");
    assert.equal(selectTake(c, 9), c);
    assert.equal(selectTake(c, 1), c);
  });
});

describe("deleteTake", () => {
  test("refuses the selected take", () => {
    const c = cardOf(board(), "c1");
    assert.equal(deleteTake(c, 1).refused, "selected");
  });
  test("moves a billed mid into attempts and tombstones it; imported takes are not billed", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2" }).card;
    const r = deleteTake(c, 1, "2026-09-29");
    assert.equal(r.refused, undefined);
    assert.deepEqual(r.card.takes.map((t) => t.n), [2]);
    assert.ok(r.card.attempts.some((a) => a.media_id === "200000000000000001"));
    assert.deepEqual(r.card.deletedTakes, ["200000000000000001"]);
    assert.equal(r.card.takeSeq, 2);
    // imported
    let d = cardOf(board(), "c2");
    d = attachTake(d, { mid: "MX", dur: 4, imported: false }).card;
    const r2 = deleteTake(d, 1, "now");
    assert.equal((r2.card.attempts || []).length, 0, "an imported take never enters attempts");
  });
});

describe("attachTake", () => {
  test("the routed draft result is a billed render; an existing video is imported", () => {
    const u = cardOf(board(), "c4");
    const routed = attachTake(u, { mid: "MR", dur: 5, imported: false, settings: { mode: "R2V" } }).card;
    assert.equal(routed.resultMid, "MR");
    assert.equal(routed.takes[0].source, "render");
    assert.deepEqual(spendMidsOf(routed).mids, ["MR"]);
    const borrowed = attachTake(u, { mid: "MB", dur: 5, imported: true }).card;
    assert.equal(borrowed.takes[0].source, "attach");
    assert.equal(borrowed.imported, true);
    assert.deepEqual(spendMidsOf(borrowed), { mids: [], imported: 1 });
  });
  test("F1: attaching while a render is paused keeps that render as a superseded take-to-be", () => {
    const c = { ...cardOf(board(), "c1"), status: "wip", pendingTaskId: "Tp", genStartedAt: 1 };
    const r = attachTake(c, { mid: "MB", imported: true });
    assert.deepEqual(r.card.supersededTasks, ["Tp"]);
    assert.equal(r.card.pendingTaskId, null);
    const late = landTake(r.card, { mid: "Mlate", taskId: "Tp" });
    assert.equal(late.outcome, "unselected");
    assert.equal(late.card.resultMid, "MB");
  });
  test("an unclear send refuses an attach", () => {
    const c = { ...cardOf(board(), "c1"), status: "wip", pendingSubmitId: "S" };
    assert.equal(attachTake(c, { mid: "MB" }).outcome, "unclear");
  });
});

describe("snapshots, reuse, ledger, batch rule", () => {
  test("a snapshot never carries a data: URL", () => {
    const c = { ...cardOf(board(), "c4"), openFrame: { thumbId: "th", source: "data:image/png;base64,AAAA" },
      refs: [{ id: "r", kind: "image", tag: "@image1", source: "data:image/jpeg;base64,BBBB", thumbId: "" }] };
    const s = snapshotSettings(c, board(), "sent text", "professional");
    assert.ok(!JSON.stringify(s).includes("data:"));
    assert.equal(s.sentPrompt, "sent text");
    assert.equal(s.look, "synthetic look");
  });
  test("Reuse settings patches the take's snapshot back onto the card", () => {
    const take = { settings: snapshotSettings({ ...cardOf(board(), "c4"), prompt: "then" }, board(), "x"), anchor: null };
    const c = reuseSettingsPatch({ ...cardOf(board(), "c4"), prompt: "now" }, take);
    assert.equal(c.prompt, "then");
    assert.equal(c.status, "todo", "reuse is a board edit, never a render");
  });
  test("F14: a failed retake on a rendered shot is not re-rendered by Generate all", () => {
    const p = board();
    assert.equal(needsRender(cardOf(p, "c1")), false);
    assert.equal(needsRender({ ...cardOf(p, "c1"), status: "error" }), false);
    assert.equal(needsRender(cardOf(p, "c4")), true);
    assert.equal(needsRender(cardOf(p, "c5")), true);
    assert.equal(needsRender({ ...cardOf(p, "c4"), status: "wip" }), false);
    assert.equal(needsRender({ ...cardOf(p, "c4"), pendingSubmitId: "S" }), false);
  });
  test("the ledger counts every non-imported take once", () => {
    let c = rendering(cardOf(board(), "c1"));
    c = landTake(c, { mid: "M2", taskId: "T2" }).card;
    const p = { acts: [{ name: "A", cards: [c, { ...c, id: "twin" }] }] };
    assert.deepEqual(collectSpendMids(p).mids, ["200000000000000001", "M2", "200000000000000000"]);
  });
});

describe("the render lock markers", () => {
  test("beginRender refuses a card in flight; a paused task is superseded only on request", () => {
    const c = cardOf(board(), "c1");
    const b = beginRender(c, { submitId: "S1", board: "B" });
    assert.equal(b.status, "wip");
    assert.equal(b.pendingSubmitId, "S1");
    assert.equal(beginRender(b, { submitId: "S2" }), null);
    const paused = { ...c, status: "wip", pendingTaskId: "Tp" };
    assert.equal(beginRender(paused, { submitId: "S2" }), null);
    assert.deepEqual(beginRender(paused, { submitId: "S2" }, { pausedOk: true }).supersededTasks, ["Tp"]);
  });
  test("cancelRender restores the card exactly", () => {
    const paused = { ...cardOf(board(), "c1"), status: "wip", pendingTaskId: "Tp", genStartedAt: 7 };
    const b = beginRender(paused, { submitId: "S2" }, { pausedOk: true });
    const back = cancelRender(b, "S2", paused);
    assert.equal(back.pendingTaskId, "Tp");
    assert.equal(back.status, "wip");
    assert.equal(back.genStartedAt, 7);
    assert.equal(back.supersededTasks, undefined);
    assert.equal(back.pendingSubmitId, null);
  });
});

describe("copies never carry a render (F4, F17) and duplicate/split rules", () => {
  test("stripInFlight settles every in-flight card of a copied board", () => {
    const p = board();
    p.acts[0].cards[0] = rendering(p.acts[0].cards[0], { supersededTasks: ["Tx"] });
    p.acts[2].cards[0] = { ...p.acts[2].cards[0], status: "wip", pendingSubmitId: "S9" };
    const s = stripInFlight(p);
    const a = cardOf(s, "c1"), b = cardOf(s, "c4");
    assert.equal(a.status, "done");
    assert.equal(b.status, "error");
    [a, b].forEach((x) => ["pendingTaskId", "pendingSubmitId", "pendingBoard", "supersededTasks", "genStartedAt"]
      .forEach((k) => assert.equal(x[k], undefined, k)));
    assert.equal(cardOf(p, "c1").pendingTaskId, "T2", "the original is untouched");
    const quiet = board();
    assert.equal(JSON.stringify(stripInFlight(quiet)), JSON.stringify(quiet), "a quiet board is unchanged");
  });
  test("a duplicated card has no takes, no ★ and no markers, but keeps its anchor", () => {
    let c = rendering(cardOf(board(), "c1"), { anchor: { shot: "c0", take: 1 } });
    c = landTake(c, { mid: "M2", taskId: "T2" }).card;
    const d = JSON.parse(JSON.stringify(buildDuplicateCard(c, "dup", [])));
    assert.equal(d.takes, undefined);
    assert.equal(d.selectedTake, undefined);
    assert.equal(d.takeSeq, undefined);
    assert.equal(d.resultMid, "");
    assert.deepEqual(d.anchor, { shot: "c0", take: 1 });
    assert.deepEqual(takesOf(d), []);
  });
  test("F11: split is refused mid-render; the right half never inherits markers; anchors follow the cut", () => {
    const p = board();
    p.acts[2].cards.push({ id: "dep", anchor: { shot: "c1", take: 1 }, openFrame: {} });
    const busy = JSON.parse(JSON.stringify(p));
    busy.acts[0].cards[0] = rendering(busy.acts[0].cards[0]);
    assert.equal(splitCardAt(busy, "act1", "c1", 2, "c1r"), busy, "refused while rendering");
    const out = splitCardAt(p, "act1", "c1", 2, "c1r");
    const right = cardOf(out, "c1r");
    assert.equal(right.pendingTaskId, undefined);
    assert.equal(right.anchor, null);
    assert.deepEqual(takesOf(right).map((t) => t.mid), ["200000000000000001"]);
    assert.equal(cardOf(out, "dep").anchor.shot, "c1r");
  });
});

describe("withTakes materialises only what the views already said", () => {
  test("the materialised card reads the same", () => {
    const c = cardOf(board(), "c1");
    const m = withTakes(c);
    assert.deepEqual(takesOf(m).map((t) => [t.n, t.mid]), takesOf(c).map((t) => [t.n, t.mid]));
    assert.equal(selectedTakeOf(m), 1);
    assert.equal(m.resultMid, c.resultMid);
  });
});

/* Code review 2026-10-02: a stored take length of 0 (or below) is UNKNOWN, as landTake already
   treats `dur <= 0` -- never a 0 s clip. withTakes / writeBack copied a card's actualDur of 0
   straight into the stored take, and the readers took it at face value: the ribbon and a splice
   anchor then read the clip as ending at 0 s, i.e. its FIRST frame. Every reader now reads a
   length of 0 or below as unknown, and the next reducer the owner triggers writes null over it. */
describe("a take length of 0 or below is unknown everywhere", () => {
  const rendered = (extra = {}) => ({ id: "c", title: "one", status: "done", resultMid: "M1", actualDur: 0, trimIn: 0, trimOut: null, ...extra });
  test("the views: selectedTakeView, takesOf and the derived take read 0, '0' and -1 as unknown", () => {
    for (const z of [0, "0", -1, -0.5]) {
      assert.equal(selectedTakeView(rendered({ actualDur: z })).dur, null, JSON.stringify(z));
      assert.equal(takesOf(rendered({ actualDur: z }))[0].dur, null, "the derived take 1 of " + JSON.stringify(z));
    }
    const stored = rendered({ actualDur: 0, takes: [{ id: "t1", n: 1, mid: "M0", dur: 0 }, { id: "t2", n: 2, mid: "M1", dur: 7.5 }],
      selectedTake: 2, takeSeq: 2 });
    assert.equal(selectedTakeView(stored).dur, 7.5, "a card-level 0 never hides the take's own known length");
    assert.equal(takesOf(stored)[0].dur, null, "a stored 0 on another take reads as unknown");
    assert.equal(stored.takes[0].dur, 0, "reading wrote nothing onto the board");
    assert.equal(selectedTakeView(rendered({ actualDur: 4.2 })).dur, 4.2, "a real length is untouched");
  });
  test("the reducers heal it: withTakes, ★ select (writeBack) and the mirror write null, never 0", () => {
    assert.equal(withTakes(rendered()).takes[0].dur, null, "withTakes");
    let c = landTake(rendered({ status: "wip", pendingSubmitId: "S2", pendingTaskId: "T2" }), { mid: "M2", taskId: "T2", dur: 5 }).card;
    assert.equal(c.takes.find((t) => t.mid === "M1").dur, null, "the outgoing take's 0 was not copied");
    c = selectTake(c, 1);
    assert.equal(c.actualDur, null, "selecting take 1 mirrors unknown, not 0");
    c = selectTake(c, 2);
    assert.equal(c.takes.find((t) => t.n === 1).dur, null, "writeBack");
    assert.equal(c.actualDur, 5);
    const zeroTake = rendered({ actualDur: 5, takes: [{ id: "t1", n: 1, mid: "M0", dur: 0 }, { id: "t2", n: 2, mid: "M1", dur: 5 }],
      selectedTake: 2, takeSeq: 2 });
    const back = selectTake(zeroTake, 1);
    assert.equal(back.actualDur, null, "a stored 0 selected onto the card mirrors as unknown");
    assert.equal(withTakes(back).takes.find((t) => t.n === 1).dur, null, "and the next materialise stores null");
  });
  test("the cut point and the anchor: an untrimmed shot of length 0 cuts at its END (unknown), never at 0 s", () => {
    assert.equal(cutPointOf(rendered()), null);
    assert.equal(cutPointOf(rendered({ actualDur: -2 })), null);
    assert.equal(cutPointOf(rendered({ trimOut: 0 })), 0, "a trim at 0 is a real time, not a length");
    assert.equal(makeAnchor(rendered(), "F1", "splice").at, null, "the anchor records 'its end', not 0.0 s");
  });
  test("the ribbon reads it as unknown: the closing frame is the clip's real end", () => {
    const p = { acts: [{ id: "a", cards: [rendered({ id: "x", resultMid: "M1" }), rendered({ id: "y", resultMid: "M2", actualDur: 5 })] }] };
    const [pair] = ribbonPairs(flat(p));
    assert.equal(pair.a.at, null);
    assert.equal(frameUrl(pair.a.mid, pair.a.at), "/api/loom/frame?mid=M1&end=1");
  });
});

describe("the span readers read a length of 0 or below as unknown too (the planned length stands in)", () => {
  const shot = (actualDur) => ({ id: "s", title: "s", status: "done", mode: "I2V", duration: 6, resultMid: "M9", actualDur,
    trimIn: 0, trimOut: null, cast: [], refs: [] });
  const board1 = (c) => ({ name: "b", assets: [], acts: [{ id: "a", name: "A", cards: [c] }] });
  for (const z of [0, -1, "-2"]) {
    test("actualDur " + JSON.stringify(z) + ": durOf, the bed's cut, the local cut and the EDL all use the planned 6 s", () => {
      assert.equal(durOf(shot(z)), 6);
      const p = board1(shot(z));
      assert.equal(cutSegments(flat(p), p)[0].span, 6);
      assert.equal(buildExportClips(flat(p)).clips[0].span, 6);
      assert.equal(edlPlan(p).cutFrames, 6 * 24);
    });
  }
});

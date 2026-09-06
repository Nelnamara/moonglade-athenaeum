/* The Loom's per-project spend ledger -- the historical sibling of the cost-to-finish pill.
   Scope: moonglade-internal/scopes/SCOPE_2026-09-04_loom-spend-ledger.md.

   These guard the JOIN (board -> media ids -> catalog paid_credit) and, above all, the
   UNKNOWN handling. The one rule the whole surface exists to keep is the one
   formatCostEstimate already states for the estimate: a displayed "0 cr" must only ever mean
   a genuinely settled, zero-cost result -- never "the catalog had no row", never "PixAI never
   reported a charge", never "the request failed". Every honest-number assertion below is
   really that one rule, tested from a different direction. */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  collectSpendMids, tallySpend, formatSpend, spendTooltip, spendPillShown, makeLatestOnly,
} from "../src/loom-core.js";
import {
  withResult, buildDuplicateCard, patchCardByIdWith, attachedVideoPatch,
} from "../src/loom-mutations.js";

/* ---------- fixtures ---------- */

const card = (o = {}) => ({ id: "c1", title: "", refs: [], ...o });
const proj = (acts) => ({ name: "P", target: 60, assets: [], acts });
const act = (name, cards) => ({ id: name, name, cards });
// A catalog answer as POST /api/loom/spend renders it: an int is a real charge, null is a row
// whose paid_credit is blank, and an ABSENT key is no row at all.
const row = (credit, task) => ({ paid_credit: credit, task_id: task || "" });

const tally = (project, rows) => tallySpend(collectSpendMids(project), rows);

/* ---------- collectSpendMids: the resultMid-only walk ---------- */

describe("collectSpendMids", () => {
  test("collects shot results and nothing else -- frames and cast are inputs, not spend", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1",
        openFrame: { mediaId: "frame-in" }, closeFrame: { mediaId: "frame-out" } }),
    ])]);
    p.assets = [{ id: "as1", name: "hero", mediaId: "cast-1" }];
    assert.deepEqual(collectSpendMids(p).mids, ["m1"]);
  });

  test("a re-rolled shot's superseded attempts count too", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m3", attempts: [{ media_id: "m1" }, { media_id: "m2" }] }),
    ])]);
    assert.deepEqual(collectSpendMids(p).mids, ["m3", "m1", "m2"]);
  });

  test("a split shot bills its one clip once, not once per half", () => {
    // splitCardAt leaves BOTH halves holding the same resultMid.
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }),
      card({ id: "a2", resultMid: "m1" }),
    ])]);
    assert.deepEqual(collectSpendMids(p).mids, ["m1"]);
  });

  test("imported footage is excluded from the sum and counted for the tooltip", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }),
      card({ id: "b", resultMid: "gallery-clip", imported: true }),
    ])]);
    const c = collectSpendMids(p);
    assert.deepEqual(c.mids, ["m1"]);
    assert.equal(c.imported, 1);
  });

  test("per-act buckets keep board order; an act with no results is still listed", () => {
    const p = proj([
      act("Act 1", [card({ id: "a", resultMid: "m1" })]),
      act("Act 2", []),
      act("Act 3", [card({ id: "c", resultMid: "m2" })]),
    ]);
    const c = collectSpendMids(p);
    assert.deepEqual(c.byAct.map((b) => b.name), ["Act 1", "Act 2", "Act 3"]);
    assert.deepEqual(c.byAct.map((b) => b.mids), [["m1"], [], ["m2"]]);
  });

  test("an id spelled like an Object.prototype key is still a plain id", () => {
    // The dedup sets are keyed by data. A plain {} would report "constructor" as already
    // seen before it ever appeared, and drop the charge.
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "constructor" }), card({ id: "b", resultMid: "toString" }),
    ])]);
    assert.deepEqual(collectSpendMids(p).mids, ["constructor", "toString"]);
  });

  test("survives an empty/absent project without throwing", () => {
    assert.deepEqual(collectSpendMids(null).mids, []);
    assert.deepEqual(collectSpendMids({}).mids, []);
    assert.deepEqual(collectSpendMids(proj([])).byAct, []);
  });
});

/* ---------- tallySpend: the join, and the two kinds of "no number" ---------- */

describe("tallySpend", () => {
  test("sums real charges", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }), card({ id: "b", resultMid: "m2" }),
    ])]);
    const t = tally(p, { m1: row(120, "t1"), m2: row(80, "t2") });
    assert.equal(t.credits, 200);
    assert.equal(t.paid, 2);
    assert.equal(t.unpriced, 0);
    assert.equal(t.missing, 0);
  });

  test("paid_credit 0 is a settled free result, NOT an unknown", () => {
    const p = proj([act("Act 1", [card({ id: "a", resultMid: "m1" })])]);
    const t = tally(p, { m1: row(0, "t1") });
    assert.equal(t.zero, 1);
    assert.equal(t.credits, 0);
    assert.equal(t.unpriced, 0);
    assert.equal(t.missing, 0);
  });

  test("a blank paid_credit is `unpriced` -- never folded into zero", () => {
    const p = proj([act("Act 1", [card({ id: "a", resultMid: "m1" })])]);
    const t = tally(p, { m1: row(null, "t1") });
    assert.equal(t.unpriced, 1);
    assert.equal(t.zero, 0);
    assert.equal(t.credits, 0);
  });

  test("an id with NO catalog row is `missing` -- a different fact from unpriced", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "gone" }), card({ id: "b", resultMid: "blank" }),
    ])]);
    const t = tally(p, { blank: row(null, "t1") });
    assert.equal(t.missing, 1, "deleted/unresolved id");
    assert.equal(t.unpriced, 1, "row present, charge never reported");
    assert.equal(t.credits, 0);
    assert.equal(t.zero, 0);
  });

  test("two media from ONE task are billed once -- paid_credit is task-level", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }), card({ id: "b", resultMid: "m2" }),
    ])]);
    const t = tally(p, { m1: row(50, "same-task"), m2: row(50, "same-task") });
    assert.equal(t.credits, 50);
    assert.equal(t.paid, 1);
    assert.equal(t.results, 2, "both results are still reported as results");
  });

  test("the task dedup does not leak across acts twice", () => {
    const p = proj([
      act("Act 1", [card({ id: "a", resultMid: "m1" })]),
      act("Act 2", [card({ id: "b", resultMid: "m2" })]),
    ]);
    const t = tally(p, { m1: row(90, "T"), m2: row(90, "T") });
    assert.equal(t.credits, 90);
    assert.equal(t.byAct[0].credits, 90, "first act to reach the task owns the charge");
    assert.equal(t.byAct[1].credits, 0);
  });

  test("an act whose only shots were billed to a sibling act is NOT reported as 0 cr", () => {
    /* THE FALSE ZERO the whole surface exists to prevent. paid_credit is task-level, so
       when two acts' shots share one task the first act to reach it owns the charge --
       correct arithmetic, but the second act then had no paid, no zero and no unknown, so
       formatSpend fell through every branch to "" and the tooltip printed "0 cr" for an
       act whose shot really did cost money. The code's own comment says a displayed
       "0 cr" must only ever mean a genuinely settled, zero-cost result. */
    const p = proj([
      act("Act 1", [card({ id: "a", resultMid: "m1" })]),
      act("Act 2", [card({ id: "b", resultMid: "m2" })]),
    ]);
    const t = tally(p, { m1: row(90, "T"), m2: row(90, "T") });
    assert.equal(t.byAct[1].credits, 0);
    assert.equal(t.byAct[1].sharedElsewhere, 1, "the second act's result has its own bucket");
    assert.equal(t.byAct[1].zero, 0, "and is never mistaken for a settled free result");
    assert.equal(t.sharedElsewhere, 1);
    const tip = spendTooltip(t);
    assert.doesNotMatch(tip, /Act 2: 0 cr/);
    assert.match(tip, /Act 2: counted in Act 1/);
  });

  test("an act with a real charge AND a shared one still shows its own number", () => {
    const p = proj([
      act("Act 1", [card({ id: "a", resultMid: "m1" })]),
      act("Act 2", [card({ id: "b", resultMid: "m2" }), card({ id: "c", resultMid: "m3" })]),
    ]);
    const t = tally(p, { m1: row(90, "T"), m2: row(90, "T"), m3: row(30, "U") });
    assert.match(spendTooltip(t), /Act 2: ~30 cr/);
  });

  test("a genuinely free act still says 0 cr, and that still means free", () => {
    const p = proj([
      act("Act 1", [card({ id: "a", resultMid: "m1" })]),
      act("Act 2", [card({ id: "b", resultMid: "m2" })]),
    ]);
    const t = tally(p, { m1: row(90, "T"), m2: row(0, "U") });
    assert.equal(t.byAct[1].zero, 1);
    assert.match(spendTooltip(t), /Act 2: 0 cr/);
  });

  test("a task_id spelled like an Object.prototype key is still billed", () => {
    const p = proj([act("Act 1", [card({ id: "a", resultMid: "m1" })])]);
    assert.equal(tally(p, { m1: row(64, "constructor") }).credits, 64);
  });

  test("a rows map with no entries at all reports every result missing, not free", () => {
    const p = proj([act("Act 1", [card({ id: "a", resultMid: "m1" })])]);
    const t = tally(p, {});
    assert.equal(t.missing, 1);
    assert.equal(t.zero, 0);
    assert.equal(formatSpend(t), "1 unpriced");
  });

  test("re-rolled attempts add their own charge to the project", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m2", attempts: [{ media_id: "m1", at: "x" }] }),
    ])]);
    const t = tally(p, { m1: row(70, "t1"), m2: row(70, "t2") });
    assert.equal(t.credits, 140, "the abandoned first try was still paid for");
  });

  test("imported clips ride through to the tally untouched", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }),
      card({ id: "b", resultMid: "elsewhere", imported: true }),
    ])]);
    const t = tally(p, { m1: row(10, "t1"), elsewhere: row(999, "t9") });
    assert.equal(t.credits, 10);
    assert.equal(t.imported, 1);
  });
});

/* ---------- "Use an existing video instead" is an IMPORT, not this project's spend ---- */

describe("a clip attached from the gallery", () => {
  test("the patch marks the card imported, exactly as the Footage tab's import does", () => {
    /* Both paths attach an already-rendered gallery video through the same picker. The
       Footage tab's importedFootagePatch sets `imported: true`; the shot card's "Use an
       existing video instead" did not, so the ledger billed that clip's historical
       paid_credit to this project -- and to a second act if the shot was ever re-rolled,
       because the picked mid was filed into attempts too. */
    const patch = attachedVideoPatch("gal-1", 4.5);
    assert.equal(patch.imported, true);
    assert.equal(patch.resultMid, "gal-1");
    assert.equal(patch.status, "done");
    assert.equal(patch.actualDur, 4.5);
    // the same clearing every other done-write in the file does
    assert.equal(patch.pendingTaskId, null);
    assert.equal(patch.genStartedAt, null);
    // a blank or zero duration leaves the card's own default standing, never a lying zero
    assert.equal("actualDur" in attachedVideoPatch("gal-1", ""), false);
    assert.equal("actualDur" in attachedVideoPatch("gal-1", 0), false);
  });

  test("a board of nothing BUT imported clips still shows its pill", () => {
    /* The pill was gated on spend.results > 0, and an imported card never contributes to
       `results` -- so a project assembled purely from "Browse library" (a first-class
       workflow: importFootage's whole purpose) rendered no pill at all. The tooltip that
       names the imported clips, and the only place they are ever disclosed, was therefore
       never reachable on exactly the boards that need it. */
    const p = proj([act("Act 1", [
      card({ id: "a", ...attachedVideoPatch("gal-1", 4) }),
      card({ id: "b", ...attachedVideoPatch("gal-2", 4) }),
    ])]);
    const t = tally(p, {});
    assert.equal(t.results, 0);
    assert.equal(t.imported, 2);
    assert.equal(spendPillShown(t), true, "the imported count must still be reachable");
    assert.match(spendTooltip(t), /2 imported clip\(s\) not counted/);
  });

  test("a board with nothing on it at all still shows no pill", () => {
    assert.equal(spendPillShown(tally(proj([act("Act 1", [])]), {})), false);
    assert.equal(spendPillShown({}), false);
    assert.equal(spendPillShown(null), false);
  });

  test("the board's own toolbar reads the pill's gate through that one rule", () => {
    const jsx = readFileSync(
      new URL("../master-storyboard.jsx", import.meta.url), "utf8");
    assert.match(jsx, /\{spendPillShown\(spend\) && \(/);
    assert.doesNotMatch(jsx, /\{spend\.results > 0 && \(/);
  });

  test("an attached clip is excluded from the sum and named in the hover", () => {
    const p = proj([act("Act 1", [
      card({ id: "a", resultMid: "m1" }),
      card({ id: "b", ...attachedVideoPatch("gal-1", 4) }),
    ])]);
    const t = tally(p, { m1: row(10, "t1"), "gal-1": row(999, "t9") });
    assert.equal(t.credits, 10, "a clip rendered elsewhere is not this project's spend");
    assert.equal(t.imported, 1);
    assert.match(spendTooltip(t), /1 imported clip\(s\) not counted/);
  });

  test("re-rolling an attached shot never files the imported mid into attempts", () => {
    // withResult pushes the superseded resultMid into attempts, which is how a re-roll's
    // money stays countable. An IMPORTED mid was never this project's money, so pushing it
    // there would bill the same borrowed clip a second time.
    const before = card({ id: "a", ...attachedVideoPatch("gal-1", 4) });
    const after = withResult(before, { status: "done", resultMid: "m9" }, "T1");
    assert.deepEqual(after.attempts, []);
    assert.equal(after.imported, false, "a freshly generated result is this project's own");
    const p = proj([act("Act 1", [after])]);
    assert.equal(tally(p, { m9: row(60, "t9"), "gal-1": row(999, "t0") }).credits, 60);
  });
});

/* ---------- formatSpend: the pill's face ---------- */

describe("formatSpend", () => {
  test("credits wear the settled mark `~`, not the estimate's `≈`", () => {
    assert.equal(formatSpend({ paid: 2, credits: 1234 }), "~1,234 cr");
  });

  test("unknowns ride along with a real total instead of vanishing", () => {
    assert.equal(formatSpend({ paid: 1, credits: 40, unpriced: 1, missing: 2 }), "~40 cr (+3 unk)");
  });

  test("nothing but unknowns says so -- it never prints 0", () => {
    assert.equal(formatSpend({ unpriced: 2 }), "2 unpriced");
    assert.equal(formatSpend({ missing: 5 }), "5 unpriced");
  });

  test("`0 cr` is reachable ONLY from settled, genuinely zero-cost results", () => {
    assert.equal(formatSpend({ zero: 3 }), "0 cr");
    assert.equal(formatSpend({ zero: 3, unpriced: 1 }), "1 unpriced",
      "one unknown is enough to stop the surface claiming a settled zero");
  });

  test("nothing rendered yet -> empty, and the caller hides the pill", () => {
    assert.equal(formatSpend({}), "");
    assert.equal(formatSpend(), "");
  });

  test("only the credits shape can take the toolbar's ' spent' suffix", () => {
    // Mirrors the JSX call site's own regex, the same trick the cost-to-finish pill uses.
    const suffixed = (t) => /^~.*cr/.test(formatSpend(t));
    assert.equal(suffixed({ paid: 1, credits: 5 }), true);
    assert.equal(suffixed({ unpriced: 1 }), false);
    assert.equal(suffixed({ zero: 1 }), false);
  });
});

/* ---------- spendTooltip: the hover ---------- */

describe("spendTooltip", () => {
  test("names all four buckets and leads with the scope's phrase", () => {
    const t = spendTooltip({ paid: 2, credits: 300, zero: 1, unpriced: 1, missing: 2 });
    assert.match(t, /^Spent so far: 2 paid \(~300 credits\)/);
    assert.match(t, /1 free-card\/zero-cost/);
    assert.match(t, /1 unpriced/);
    assert.match(t, /2 with no catalog row/);
  });

  test("imported clips are named as excluded, never silently dropped", () => {
    assert.match(spendTooltip({ imported: 2 }), /2 imported clip\(s\) not counted/);
    assert.doesNotMatch(spendTooltip({ imported: 0 }), /imported/);
  });

  test("per-act breakdown appears once there is more than one act with results", () => {
    const one = spendTooltip({ byAct: [{ name: "Act 1", results: 1, credits: 10, paid: 1 }] });
    assert.doesNotMatch(one, /\n {2}Act 1/);
    const two = spendTooltip({ byAct: [
      { name: "Act 1", results: 1, credits: 10, paid: 1 },
      { name: "Act 2", results: 1, credits: 25, paid: 1 },
    ] });
    assert.match(two, /\n {2}Act 1: ~10 cr/);
    assert.match(two, /\n {2}Act 2: ~25 cr/);
  });

  test("acts with no results are left out of the breakdown", () => {
    const t = spendTooltip({ byAct: [
      { name: "Act 1", results: 2, credits: 10, paid: 1 },
      { name: "Empty", results: 0 },
      { name: "Act 3", results: 1, credits: 5, paid: 1 },
    ] });
    assert.doesNotMatch(t, /Empty/);
  });

  test("says out loud that pre-ledger re-rolls are not in the number", () => {
    assert.match(spendTooltip({ paid: 1, credits: 1 }), /re-rolls from before the ledger/i);
  });
});

/* ---------- two overlapping reads of the same board ---------- */

describe("the spend fetch's ordering guard", () => {
  test("an older response cannot overwrite a newer one for the same board", async () => {
    /* The guard used to key on the media-id list alone, which is IDENTICAL for every
       request about one board -- so it could not tell an earlier in-flight read from a
       later one. refreshSpend (a manual click) deliberately bypasses the short-circuit
       that would otherwise stop a second concurrent fetch, so two reads of the same board
       overlap routinely; if the network returned them out of order, whichever landed
       second won regardless of which was actually issued last. */
    const gate = makeLatestOnly();
    const applied = [];
    const read = (label, ms) => {
      const token = gate.begin();
      return new Promise((r) => setTimeout(r, ms)).then(() => {
        if (!gate.wins(token)) return;
        applied.push(label);
      });
    };
    const first = read("stale", 20);      // issued first, lands last
    const second = read("fresh", 1);      // issued second, lands first
    await Promise.all([first, second]);
    assert.deepEqual(applied, ["fresh"], "the last request issued is the one that applies");
  });

  test("a lone request still applies", async () => {
    const gate = makeLatestOnly();
    const token = gate.begin();
    assert.equal(gate.wins(token), true);
  });

  test("a token from a superseded request never wins again", () => {
    const gate = makeLatestOnly();
    const a = gate.begin();
    const b = gate.begin();
    assert.equal(gate.wins(a), false);
    assert.equal(gate.wins(b), true);
    gate.cancel();
    assert.equal(gate.wins(b), false, "cancel retires every token in flight");
  });

  test("the board's fetch really runs through the gate", () => {
    const jsx = readFileSync(
      new URL("../master-storyboard.jsx", import.meta.url), "utf8");
    const hook = jsx.slice(jsx.indexOf("const loadSpend = useCallback"));
    const body = hook.slice(0, hook.indexOf("const refreshSpend"));
    assert.match(body, /spendGate\.current\.begin\(\)/);
    assert.match(body, /spendGate\.current\.wins\(token\)/);
  });
});

/* ---------- withResult: the reason a re-roll's money is still countable ---------- */

describe("withResult", () => {
  test("a first result records no attempt -- there was nothing to supersede", () => {
    const c = withResult(card({ resultMid: "" }), { status: "done", resultMid: "m1" }, "T0");
    assert.equal(c.resultMid, "m1");
    assert.deepEqual(c.attempts, []);
  });

  test("a re-roll files the clip it replaced under attempts", () => {
    const c = withResult(card({ resultMid: "m1" }), { status: "done", resultMid: "m2" }, "T1");
    assert.equal(c.resultMid, "m2");
    assert.deepEqual(c.attempts, [{ media_id: "m1", at: "T1" }]);
  });

  test("attempts accumulate across repeated re-rolls, oldest first", () => {
    let c = card({ resultMid: "m1" });
    c = withResult(c, { resultMid: "m2" }, "T1");
    c = withResult(c, { resultMid: "m3" }, "T2");
    assert.deepEqual(c.attempts.map((a) => a.media_id), ["m1", "m2"]);
    assert.equal(c.resultMid, "m3");
  });

  test("re-landing the SAME mid records nothing -- one result reported twice", () => {
    // A resumed poll re-reporting a finished shot must not invent an attempt, which the
    // ledger would then bill a second time.
    const c = withResult(card({ resultMid: "m1" }), { status: "done", resultMid: "m1" }, "T1");
    assert.deepEqual(c.attempts, []);
  });

  test("never files the same superseded id twice", () => {
    let c = card({ resultMid: "m1" });
    c = withResult(c, { resultMid: "m2" }, "T1");
    c = withResult(c, { resultMid: "m1" }, "T2");   // rolled back to the first clip
    c = withResult(c, { resultMid: "m2" }, "T3");   // and away again
    assert.deepEqual(c.attempts.map((a) => a.media_id), ["m1", "m2"]);
  });

  test("the rest of the patch still applies exactly as a flat patch would", () => {
    const c = withResult(card({ resultMid: "m1", status: "wip", pendingTaskId: "t" }),
      { status: "done", resultMid: "m2", trimIn: 0, trimOut: null, pendingTaskId: null }, "T");
    assert.equal(c.status, "done");
    assert.equal(c.pendingTaskId, null);
  });

  test("end to end: a re-rolled shot's two clips both reach the ledger", () => {
    let p = proj([act("Act 1", [card({ id: "a", resultMid: "m1" })])]);
    p = patchCardByIdWith(p, "a", (c) => withResult(c, { resultMid: "m2" }, "T1"));
    const t = tally(p, { m1: row(60, "t1"), m2: row(60, "t2") });
    assert.equal(t.credits, 120);
  });
});

describe("buildDuplicateCard", () => {
  test("a duplicate inherits no result and no attempts -- that spend belongs to the original", () => {
    const orig = card({ id: "a", resultMid: "m2", attempts: [{ media_id: "m1", at: "T" }] });
    const dup = buildDuplicateCard(orig, "b", []);
    assert.equal(dup.resultMid, "");
    assert.deepEqual(dup.attempts, []);
  });

  test("duplicating a rendered shot does not double the project's spend", () => {
    const orig = card({ id: "a", resultMid: "m1" });
    const p = proj([act("Act 1", [orig, buildDuplicateCard(orig, "b", [])])]);
    const t = tally(p, { m1: row(45, "t1") });
    assert.equal(t.credits, 45);
  });
});

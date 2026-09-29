import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  CELL_CAP, ERR_STRAY, ERR_UNCLOSED, LIST_ITEM_MAX, LOST_WORDS, READBACK_LOST_MS, RUN_SEED_MAX,
  ackOf, chargeMismatch, cleanList, confirmCopy, escapeLiteral, hasSyntax, listItemsFromText,
  listProblem, listsFromPrefs, matrixGrid, matrixProduct, newRoll, parse, planJobs, previewRows,
  readBack, rng, runLine, runSeedOf, sendRoute, sendSummary, tokenLine,
} from "../../gallery/src/gen/templateCore.js";

/* Session M (Generate power tools): the dock's copy of the template rule, its send routing, the
   one confirm's words and the run's read-back. The template half is pinned against the SAME
   vector file the server's tests read (tests/fixtures/template_vectors.json), so the preview
   the dock draws is the set of jobs moonglade_runs.plan_jobs sends. Design:
   moonglade-internal/design/notes/generate-power-tools/BUILD-w5-m.md. */

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(here, "..", "..");
const VEC = JSON.parse(readFileSync(path.join(ROOT, "tests", "fixtures", "template_vectors.json"), "utf8"));

describe("the shared vectors: the dock expands exactly as the server does", () => {
  for (const c of VEC.cases) {
    test(c.name, () => {
      const got = planJobs(c.template, VEC.lists, c.var_mode, c.count, c.run_seed == null ? 0 : c.run_seed);
      assert.deepEqual(got, c.plan);
      assert.equal(parse(c.template, VEC.lists).syntax, c.syntax);
    });
  }
  test("escapes match and round-trip", () => {
    for (const e of VEC.escape) {
      assert.equal(escapeLiteral(e.text), e.escaped, e.text);
      const p = parse(e.escaped, {});
      assert.equal(p.error, null);
      assert.equal(p.vars.length, 0);
      assert.equal(p.parts.map((x) => x.lit).join(""), e.text);
    }
  });
});

describe("the syntax (NOTES 1)", () => {
  test("inline options split on |, trimmed, empties dropped; lists read from the account", () => {
    const p = parse("{ a || b } __l__", { l: [" x ", "", "y"] });
    assert.deepEqual(p.vars.map((v) => v.options), [["a", "b"], ["x", "y"]]);
    assert.equal(p.vars[1].kind, "list");
  });
  test("escapes are literal braces and underscores; a backslash elsewhere is literal", () => {
    const p = parse("\\{x\\} \\__l__ a\\|b c\\d", { l: ["q"] });
    assert.equal(p.error, null);
    assert.equal(p.vars.length, 0);
    assert.equal(p.parts[0].lit, "{x} __l__ a\\|b c\\d");
    assert.equal(p.syntax, true);
  });
  test("| outside braces is literal text, not a variable", () => {
    assert.equal(hasSyntax("a | b"), false);
    assert.equal(planJobs("a | b", {}, "random", 1, 5).jobs[0].prompt, "a | b");
  });
  test("each refusal, in its own words, the first by position", () => {
    assert.equal(parse("a {b", {}).error, ERR_UNCLOSED);
    assert.equal(parse("{a{b}}", {}).error, ERR_UNCLOSED);
    assert.equal(parse("a } {b", {}).error, ERR_STRAY);
    assert.equal(parse("{}", {}).error, "Empty variable.");
    assert.equal(parse("__nope__", {}).error, "No list named __nope__.");
    assert.equal(parse("__e__", { e: [" "] }).error, "The list __e__ is empty.");
    assert.match(parse(Array(9).fill("{a|b}").join(" "), {}).error, /Up to 8 variables/);
    assert.match(parse("{" + Array.from({ length: 65 }, (_, i) => "o" + i).join("|") + "}", {}).error, /Up to 64 options/);
    assert.match(planJobs("{a|b|a}", {}, "matrix", 1, 0).error, /twice/);
    // a repeat is allowed in Random (it weights the draw)
    assert.equal(planJobs("{a|b|a}", {}, "random", 3, 9).error, undefined);
  });
  test("list names use the page's charset; a bad list is refused, never cut", () => {
    assert.equal(cleanList(Array(201).fill("x")), null);
    assert.equal(cleanList(["x".repeat(LIST_ITEM_MAX + 1)]), null);
    assert.deepEqual(cleanList([" a ", "", "b"]), ["a", "b"]);
    assert.deepEqual(Object.keys(listsFromPrefs({ "gen.lists": { ok_1: ["a"], "Bad": ["b"] } })), ["ok_1"]);
    assert.deepEqual(listItemsFromText("a\r\n\n b \n"), ["a", "b"]);
    assert.equal(listProblem("poses", ["a"], {}), "");
    assert.match(listProblem("Poses", ["a"], {}), /lowercase/);
    assert.match(listProblem("poses", [], {}), /at least one/);
  });
  test("substitution only: literal text stays byte for byte", () => {
    const t = "  two  spaces,\ttab\n{ a }  end ";
    assert.equal(planJobs(t, {}, "random", 1, 3).jobs[0].prompt, "  two  spaces,\ttab\na  end ");
  });
});

describe("Random and Matrix", () => {
  test("Random is seeded: the same run seed draws the same values, another seed draws others", () => {
    const a = planJobs("{a|b|c|d|e|f} {1|2|3|4|5|6}", {}, "random", 4, 12345);
    const b = planJobs("{a|b|c|d|e|f} {1|2|3|4|5|6}", {}, "random", 4, 12345);
    const c = planJobs("{a|b|c|d|e|f} {1|2|3|4|5|6}", {}, "random", 4, 54321);
    assert.deepEqual(a, b);
    assert.notDeepEqual(a.jobs.map((j) => j.prompt), c.jobs.map((j) => j.prompt));
    assert.deepEqual(a.jobs.map((j) => j.seed), [12345, 12346, 12347, 12348]);
  });
  test("the LCG is the page's own rng()", () => {
    const page = (seed) => { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; };
    for (const seed of [0, 1, 1740283991, RUN_SEED_MAX]) {
      const mine = rng(seed), theirs = page(seed);
      for (let k = 0; k < 50; k++) assert.equal(mine() / 4294967296, theirs());
    }
  });
  test("Matrix: every combination, the last axis fastest", () => {
    const p = planJobs("{a|b} {x|y|z}", {}, "matrix", 1, 0);
    assert.deepEqual(p.jobs.map((j) => j.prompt), ["a x", "a y", "a z", "b x", "b y", "b z"]);
    assert.deepEqual(p.axes.map((x) => x.values), [["a", "b"], ["x", "y", "z"]]);
    assert.ok(p.jobs.every((j) => j.seed === null && j.batch === 1));
  });
  test("the cap: 24 goes, 25 is refused, and a huge product is refused without being built", () => {
    assert.equal(planJobs("{a|b|c} {1|2|3|4} {x|y}", {}, "matrix", 1, 0).images, CELL_CAP);
    assert.match(planJobs("{a|b|c|d|e} {1|2|3|4|5}", {}, "matrix", 1, 0).error, /^25 combinations is over the 24-cell cap/);
    const big = {};
    for (let i = 0; i < 8; i++) big["l" + i] = Array.from({ length: 200 }, (_, k) => "v" + k);
    const t0 = Date.now();
    const got = planJobs(Object.keys(big).map((k) => "__" + k + "__").join(" "), big, "matrix", 1, 0);
    assert.ok(Date.now() - t0 < 200, "the count must stop early, never materialise 200^8 cells");
    assert.match(got.error, /More than a million combinations/);
    assert.equal(matrixProduct(parse("__l0__ __l1__ __l2__ __l3__", big).vars), 1000001);
  });
  test("no variables: a plain batch is ONE job with batchSize N; a matrix of none is one generation", () => {
    assert.deepEqual(planJobs("plain", {}, "random", 3, 1).jobs, [{ cell: 0, prompt: "plain", vars: [], seed: null, batch: 3 }]);
    assert.equal(planJobs("plain", {}, "random", 3, 1).mode, "batch");
    assert.equal(planJobs("plain", {}, "matrix", 1, 1).mode, "single");
  });
  test("the reel grid: the last axis across, the rest down", () => {
    const p = planJobs("{p|q} {1|2} {x|y|z}", {}, "matrix", 1, 0);
    const g = matrixGrid(p.axes, p.jobs);
    assert.deepEqual(g.across, ["x", "y", "z"]);
    assert.deepEqual(g.rows.map((r) => r.label), ["p · 1", "p · 2", "q · 1", "q · 2"]);
    assert.deepEqual(g.rows[3].cells.map((c) => c.prompt), ["q 2 x", "q 2 y", "q 2 z"]);
    assert.equal(matrixGrid(null, []), null);
  });
});

describe("the dock's routing and words", () => {
  test("x1 plain -> today's /api/generate; x1 with syntax -> /run; more than one -> the confirm", () => {
    const route = (t, mode, n) => sendRoute(planJobs(t, {}, mode, n, 7), hasSyntax(t));
    assert.equal(route("plain", "random", 1), "generate");
    assert.equal(route("{a|b}", "random", 1), "run");
    assert.equal(route("\\{a\\}", "random", 1), "run");
    assert.equal(route("plain", "random", 2), "confirm");
    assert.equal(route("{a|b}", "random", 4), "confirm");
    assert.equal(route("{a|b}", "matrix", 1), "confirm");
    assert.equal(route("{solo}", "matrix", 1), "run");
    assert.equal(route("a {b", "random", 1), "blocked");
  });
  test("the run seed: the seed field when it holds one in range, else the roll", () => {
    assert.equal(runSeedOf("42", 7), 42);
    assert.equal(runSeedOf("", 7), 7);
    assert.equal(runSeedOf("-3", 7), null);
    assert.equal(runSeedOf("2147483647", 7), null);
    const r = newRoll(() => 0.999999999);
    assert.ok(r >= 0 && r <= RUN_SEED_MAX);
  });
  test("the token line tints variables and refusals; the summary and preview read the plan", () => {
    const p = parse("a {x|y} }", {});
    assert.deepEqual(tokenLine(p).map((k) => k.kind), ["lit", "var", "lit", "bad"]);
    const ok = parse("{a|b} __l__", { l: ["x", "y", "z"] });
    const plan = planJobs("{a|b} __l__", { l: ["x", "y", "z"] }, "matrix", 1, 0);
    assert.equal(sendSummary(ok, plan, "matrix", 1), "2 × 3 = 6 combinations · every one is sent, queued");
    assert.equal(previewRows(plan).length, 6);
    const many = planJobs("{a|b|c|d} {1|2}", {}, "matrix", 1, 0);
    assert.deepEqual(previewRows(many).slice(-1), ["… 2 more"]);
  });
  test("the confirm: card, no card, matrix, a batch, Unlimited, READ_ONLY", () => {
    const base = { count: 4, jobs: 4, each: 1600, covered: 2, total: 3200, digest: "d", mode: "random",
      card: { name: "Tsubaki", held: 5, needed: 1, left_after: 3 } };
    const c1 = confirmCopy(base);
    assert.equal(c1.title, "Send 4 generations?");
    assert.equal(c1.credits, "≈ 3,200 credits in total · 1,600 each × 2");
    assert.equal(c1.cards, "2 free cards cover the first 2 · 3 left after");
    assert.equal(c1.go, "Send 4");
    assert.match(c1.note, /if it refuses one, the rest aren’t sent/);
    assert.equal(confirmCopy({ ...base, covered: 0, total: 6400, card: null }).cards, "No free card covers this.");
    const m = confirmCopy({ ...base, mode: "matrix", covered: 0, total: 6400, card: null });
    assert.equal(m.title, "Send 4 generations? (matrix, queued)");
    assert.equal(m.cards, "Free cards don’t cover queued matrix runs.");
    const b = confirmCopy({ count: 3, jobs: 1, each: 4800, covered: 0, total: 4800, mode: "batch" });
    assert.equal(b.credits, "≈ 4,800 credits in total · one task of 3 images");
    assert.equal(b.note, "");
    assert.equal(confirmCopy({ ...base, covered: 1, jobs: 1, count: 3, mode: "batch", total: 0,
      card: { held: 2, needed: 1, left_after: 1 } }).cards, "A free card covers this batch · 1 left after");
    assert.equal(confirmCopy({ ...base, unlimited: true }).credits, "free · Unlimited Mode");
    const ro = confirmCopy({ ...base, read_only: true });
    assert.equal(ro.blocked, true);
    assert.match(ro.note, /READ_ONLY/);
    assert.deepEqual(ackOf(base), { count: 4, jobs: 4, each: 1600, covered: 2, total: 3200, digest: "d" });
  });
  test("the result line: the first failure named, the rest not sent, nothing offered to resend", () => {
    const jobs = [{ cell: 0, state: "sent" }, { cell: 1, state: "sent" },
      { cell: 2, state: "refused", error: "blocked" }, { cell: 3, state: "not_sent" }, { cell: 4, state: "not_sent" }];
    assert.deepEqual(runLine({ status: "stopped", jobs }),
      { text: "Sent 2 of 5. Cell 3 was refused by PixAI: blocked. Cells 4–5 were not sent.", kind: "warn" });
    const unclear = [{ cell: 0, state: "sent" }, { cell: 1, state: "may_have_started" }, { cell: 2, state: "not_sent" }];
    assert.match(runLine({ status: "stopped", jobs: unclear }).text, /Cell 2 may have started on PixAI — check the Activity tray/);
    assert.equal(runLine({ status: "sent", jobs: [{ cell: 0, state: "sent" }, { cell: 1, state: "sent" }] }).kind, "ok");
    assert.equal(runLine({ status: "sent", mode: "batch", count: 3, jobs: [{ cell: 0, state: "sent" }] }).text, "Sent — 3 images in one task.");
    assert.equal(runLine({ error: "The price moved since you confirmed — nothing was sent." }).kind, "warn");
    assert.equal(chargeMismatch(3, 0, 1600), "Cell 3 cost 1,600 credits; the confirm expected it free.");
    assert.equal(chargeMismatch(3, 1600, 1600), "");
  });
});

describe("the read-back after Go (review F4): one POST per run id, never a second", () => {
  const T = 1000;
  test("a 404 while the POST is out means 'not received yet'", () => {
    let s = readBack(null, { type: "start", at: T });
    s = readBack(s, { type: "get404", at: T + 60000 });
    assert.equal(s.phase, "posting");
  });
  test("the POST's answer ends it", () => {
    const s = readBack(readBack(null, { type: "start", at: T }), { type: "post", run: { status: "sent" }, at: T + 1 });
    assert.equal(s.phase, "done");
    assert.equal(readBack(s, { type: "get404", at: T + 99999 }).phase, "done");
  });
  test("a lost POST reads the run back; progress keeps reading; a terminal run ends it", () => {
    let s = readBack(null, { type: "start", at: T });
    s = readBack(s, { type: "postLost", at: T + 10 });
    assert.equal(s.phase, "reading");
    s = readBack(s, { type: "get", run: { status: "sending", jobs: [] }, at: T + 20 });
    assert.equal(s.phase, "reading");
    s = readBack(s, { type: "get", run: { status: "stopped", jobs: [] }, at: T + 30 });
    assert.equal(s.phase, "done");
  });
  test("a lost POST and a lasting 404 is 'may not have reached the server', never 'not sent'", () => {
    let s = readBack(readBack(null, { type: "start", at: T }), { type: "postLost", at: T });
    s = readBack(s, { type: "get404", at: T + READBACK_LOST_MS - 1 });
    assert.equal(s.phase, "reading");
    s = readBack(s, { type: "get404", at: T + READBACK_LOST_MS });
    assert.equal(s.phase, "lost");
    assert.match(LOST_WORDS, /may not have reached the server/);
    assert.doesNotMatch(LOST_WORDS, /not sent/);
  });
});

/* ---- structure: the run's one POST (s4.3) ---- */
const SRC = path.join(ROOT, "gallery", "src");
function walk(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(js|jsx)$/.test(n)) out.push(p);
  }
  return out;
}
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const read = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");

describe("the run's one POST", () => {
  test("only gen/submitTask.js posts /api/generate/run, from one call site", () => {
    const hits = walk(SRC).filter((f) => codeOnly(read(f)).includes('"/api/generate/run"'))
      .map((f) => path.relative(SRC, f).split(path.sep).join("/"));
    assert.deepEqual(hits, ["gen/submitTask.js"]);
    const road = codeOnly(read(path.join(SRC, "gen", "submitTask.js")));
    assert.equal((road.match(/"\/api\/generate\/run"/g) || []).length, 1);
  });
  test("submitRun is called once, in useRuns, behind the synchronous latch", () => {
    const callers = walk(SRC).filter((f) => /\bsubmitRun\(/.test(codeOnly(read(f))))
      .map((f) => path.relative(SRC, f).split(path.sep).join("/")).sort();
    assert.deepEqual(callers, ["gen/submitTask.js", "gen/useRuns.js"]);
    const hook = codeOnly(read(path.join(SRC, "gen", "useRuns.js")));
    assert.equal((hook.match(/\bsubmitRun\(/g) || []).length, 1);
    // both entries into the one call check the latch first, then set it
    for (const fn of ["const go = useCallback", "const sendSingle = useCallback"]) {
      const at = hook.indexOf(fn);
      assert.ok(at >= 0, fn);
      const body = hook.slice(at, at + 400);
      assert.ok(body.indexOf("if (busyRef.current) return;") < body.indexOf("busyRef.current = true;"), fn);
    }
    assert.doesNotMatch(hook, /setTimeout\([^)]*submitRun|retry\s*\(/, "a run is never posted again");
  });
  test("/api/generate itself is still only the road's single send", () => {
    const hits = walk(SRC).filter((f) => /submitTask\(\s*"\/api\/generate"/.test(read(f)))
      .map((f) => path.relative(SRC, f).split(path.sep).join("/")).sort();
    assert.deepEqual(hits, ["components/TsubakiEditBar.jsx", "components/UpscalePanel.jsx", "gen/useGenerate.js"]);
  });
});

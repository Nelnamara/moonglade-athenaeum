import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  CELL_CAP, ERR_UNCLOSED, LIST_ITEM_MAX, LOST_SEEN_WORDS, LOST_WORDS, READBACK_LOST_MS, RUN_SEED_MAX,
  ackOf, chargeMismatch, cleanList, confirmCopy, escapeLiteral, forcesNoCard, hasSyntax, listItemsFromText,
  listProblem, listsFromPrefs, matrixGrid, matrixProduct, newRoll, newRunId, parse, planJobs, previewRows,
  fmt, promptTint, quoteSends, readBack, readBackEvent, rng, runLine, runSeedOf, sendRoute, sendSummary, tokenLine, trim,
} from "../../gallery/src/gen/templateCore.js";
import {
  LOST_POST_WORDS, PLAN_PATH, imgRunBody, imgSendRoute, runConfirmText, sendImgRun,
} from "../src/loom-run.js";

/* Session M (Generate power tools): the dock's copy of the template rule, its send routing, the
   one confirm's words and the run's read-back. The template half is pinned against the SAME
   vector file the server's tests read (dev/tests/fixtures/template_vectors.json), so the preview
   the dock draws is the set of jobs moonglade_runs.plan_jobs sends. Design:
   moonglade-internal/design/notes/generate-power-tools/BUILD-w5-m.md. */

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(here, "..", "..");
const VEC = JSON.parse(readFileSync(path.join(ROOT, "dev", "tests", "fixtures", "template_vectors.json"), "utf8"));

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
  test("options and list items trim the ONE shared set (review N5)", () => {
    for (const t of VEC.trim) {
      assert.equal(trim(t.raw), t.trimmed, JSON.stringify(t.raw));
      assert.deepEqual(cleanList([t.raw]), t.trimmed ? [t.trimmed] : []);
      assert.deepEqual(parse("{" + t.raw + "|z}", {}).vars[0].options, (t.trimmed ? [t.trimmed] : []).concat(["z"]));
    }
  });
  test("the S1 invariant: no | group and no __name__ token is byte-identical, no syntax", () => {
    for (const t of VEC.invariant) {
      for (const vm of ["random", "matrix"]) {
        const got = planJobs(t, VEC.lists, vm, 1, 5);
        assert.equal(got.mode, "single", t);
        assert.equal(got.jobs[0].prompt, t);
      }
      assert.equal(parse(t, VEC.lists).syntax, false, t);
    }
  });
});

/* The same deterministic strings dev/tests/test_generate_runs.py's _lcg_strings draws, so the two
   halves are driven by the same inputs. */
function lcgStrings(alphabet, count, seed, maxLen = 14) {
  let s = seed >>> 0;
  const next = () => { s = Number((BigInt(s) * 1664525n + 1013904223n) & 0xFFFFFFFFn); return s; };
  const out = [];
  for (let i = 0; i < count; i++) {
    const n = next() % maxLen;
    let w = "";
    for (let k = 0; k < n; k++) w += alphabet[next() % alphabet.length];
    out.push(w);
  }
  return out;
}
const PROPERTY_ALPHABET = ["{", "}", "\\", "_", "a", " ", "(", ")", ",", "__x__", "é"];

describe("properties (review S1)", () => {
  test("any text with no | and no list token resolves to itself, no syntax", () => {
    let checked = 0;
    for (const t of lcgStrings(PROPERTY_ALPHABET, 4000, 20260929)) {
      if (t.includes("|") || /__([a-z0-9_]+)__/.test(t)) continue;
      checked += 1;
      assert.equal(parse(t, {}).syntax, false, t);
      assert.equal(planJobs(t, {}, "matrix", 1, 1).jobs[0].prompt, t);
    }
    assert.ok(checked > 500);
  });
  test("escapeLiteral always round-trips, whatever the text", () => {
    for (const t of lcgStrings(PROPERTY_ALPHABET.concat(["|"]), 4000, 7)) {
      const p = parse(escapeLiteral(t), { x: ["q"] });
      assert.equal(p.error, null, t);
      assert.equal(p.vars.length, 0, t);
      assert.equal(p.parts.map((x) => x.lit).join(""), t);
    }
  });
});

describe("the syntax (NOTES 1)", () => {
  test("inline options split on |, trimmed, empties dropped; lists read from the account", () => {
    const p = parse("{ a || b } __l__", { l: [" x ", "", "y"] });
    assert.deepEqual(p.vars.map((v) => v.options), [["a", "b"], ["x", "y"]]);
    assert.equal(p.vars[1].kind, "list");
  });
  test("a backslash is dropped only where it changes the parse (the S1 ruling)", () => {
    const p = parse("\\{a|b\\} \\__l__ \\{x\\} a\\_b a\\|b c\\d", { l: ["q"] });
    assert.equal(p.error, null);
    assert.equal(p.vars.length, 0);
    assert.equal(p.parts[0].lit, "{a|b} __l__ \\{x\\} a\\_b a\\|b c\\d");
    assert.equal(p.syntax, true);
  });
  test("a brace group with no | is literal text, sent exactly as typed", () => {
    for (const t of ["{masterpiece}, 1girl", "{{best quality}}", "{}", "a } b", "x {y", "\\{x}", "{a{b}c}"]) {
      assert.equal(hasSyntax(t), false, t);
      assert.equal(planJobs(t, {}, "random", 1, 5).jobs[0].prompt, t);
    }
    assert.deepEqual(parse("{solo|} x", {}).vars.map((v) => v.options), [["solo"]]);
  });
  test("| outside braces is literal text, not a variable", () => {
    assert.equal(hasSyntax("a | b"), false);
    assert.equal(hasSyntax("{a} | {b}"), false);
    assert.equal(planJobs("a | b", {}, "random", 1, 5).jobs[0].prompt, "a | b");
  });
  test("each refusal, in its own words, the first by position", () => {
    assert.equal(parse("a {b|c", {}).error, ERR_UNCLOSED);
    assert.equal(parse("{{a|b}}", {}).error, ERR_UNCLOSED);
    assert.equal(parse("{a|{b}}", {}).error, ERR_UNCLOSED);
    assert.equal(parse("a \\{b|c", {}).error, null);
    assert.equal(parse("{ | }", {}).error, "Empty variable.");
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
    const t = "  two  spaces,\ttab\n{ a | }  end ";
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
    assert.equal(route("\\{a|b\\}", "random", 1), "run");
    assert.equal(route("{masterpiece}, \\{x\\}", "random", 1), "generate");
    assert.equal(route("plain", "random", 2), "confirm");
    assert.equal(route("{a|b}", "random", 4), "confirm");
    assert.equal(route("{a|b}", "matrix", 1), "confirm");
    assert.equal(route("{solo|}", "matrix", 1), "run");
    assert.equal(route("{solo}", "matrix", 1), "generate");
    assert.equal(route("a {b|c", "random", 1), "blocked");
  });
  test("review B1: only a matrix of 2+ cells forces no card -- a one-cell matrix is a single send", () => {
    assert.equal(forcesNoCard(planJobs("{a|b} x", {}, "matrix", 1, 0)), true);
    assert.equal(forcesNoCard(planJobs("{a|} x", {}, "matrix", 1, 0)), false);
    assert.equal(forcesNoCard(planJobs("__one__ x", { one: ["a"] }, "matrix", 1, 0)), false);
    assert.equal(forcesNoCard(planJobs("{a|b} x", {}, "random", 2, 0)), false);
    assert.equal(forcesNoCard(planJobs("{a|b|a}", {}, "matrix", 1, 0)), false);
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
    const p = parse("a {x|y} } {p|", {});
    assert.deepEqual(tokenLine(p).map((k) => k.kind), ["lit", "var", "lit", "bad", "lit"]);
    // ordinary braces are never tinted: they are literal text
    assert.deepEqual(tokenLine(parse("{masterpiece} {x|y}", {})).map((k) => k.kind), ["lit", "var"]);
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
  test("review N8: a read that FAILED counts toward the lost window like a 404", () => {
    let s = readBack(readBack(null, { type: "start", at: T }), { type: "postLost", at: T });
    s = readBack(s, readBackEvent({ error: "network error: Failed to fetch" }, T + READBACK_LOST_MS - 1));
    assert.equal(s.phase, "reading");
    s = readBack(s, readBackEvent({ error: "network error: Failed to fetch" }, T + READBACK_LOST_MS));
    assert.equal(s.phase, "lost");
  });
  test("a run seen sending and then no answer at all still ends (never disabled until a reload)", () => {
    let s = readBack(readBack(null, { type: "start", at: T }), { type: "postLost", at: T });
    s = readBack(s, readBackEvent({ run_id: "r", status: "sending", jobs: [] }, T + 5000));
    s = readBack(s, readBackEvent({ error: "503 SERVICE UNAVAILABLE", http_status: 503 }, T + 5000 + READBACK_LOST_MS - 1));
    assert.equal(s.phase, "reading", "the window runs from the last read that answered");
    s = readBack(s, readBackEvent({ error: "Couldn't read the run.", http_status: 503 }, T + 5000 + READBACK_LOST_MS));
    assert.equal(s.phase, "lost");
    assert.equal(s.run.status, "sending");
    assert.doesNotMatch(LOST_SEEN_WORDS, /not sent/);
  });
  test("the events: a 404, a run, anything else a failed read; a failed read while posting waits", () => {
    assert.equal(readBackEvent({ error: "not found", http_status: 404 }, 1).type, "get404");
    assert.equal(readBackEvent({ status: "sending" }, 1).type, "get");
    assert.equal(readBackEvent(null, 1).type, "getFailed");
    const s = readBack(readBack(null, { type: "start", at: T }), { type: "getFailed", at: T + 10 * READBACK_LOST_MS });
    assert.equal(s.phase, "posting", "while the POST is out its own answer settles it");
  });
  test("a run id is 32 hex characters, uuid4", () => {
    const id = newRunId();
    assert.match(id, /^[0-9a-f]{32}$/);
    assert.equal(id[12], "4");
  });
});

describe("the Loom's Image tab: ×2-4 and template prompts ride the run road (review S2)", () => {
  const body = { model_id: "M", version_id: "V", prompt: "a glade", count: 3, seed: "" };
  const PLAN = { mode: "batch", count: 3, jobs: 1, each: 1600, covered: 0, total: 1600, digest: "dg", card: null };
  const deps = (over = {}) => {
    const calls = { post: [], run: [], confirm: [] };
    return {
      calls,
      post: async (p, b) => { calls.post.push([p, b]); return over.plan || PLAN; },
      run: async (b) => { calls.run.push(b); return over.run || { data: { status: "sent", mode: "batch", count: 3, jobs: [{ cell: 0, state: "sent", task_id: "901" }] } }; },
      csrf: async () => "tok",
      confirm: (t) => { calls.confirm.push(t); return over.confirm !== undefined ? over.confirm : true; },
    };
  };
  test("routing: a plain count 1 keeps /api/generate; more than one or a template takes the run road", () => {
    assert.equal(imgSendRoute({ prompt: "a glade", count: 1 }), "generate");
    assert.equal(imgSendRoute({ prompt: "{masterpiece}, a glade", count: 1 }), "generate");
    assert.equal(imgSendRoute({ prompt: "a glade", count: 2 }), "run");
    assert.equal(imgSendRoute({ prompt: "{dusk|dawn} glade", count: 1 }), "run");
    assert.deepEqual(imgRunBody({ prompt: "x", seed: "42" }, 7), { prompt: "x", seed: "42", var_mode: "random", run_seed: 42 });
    assert.deepEqual(imgRunBody({ prompt: "x", seed: "" }, 7), { prompt: "x", seed: "", var_mode: "random", run_seed: 7 });
  });
  test("plan -> the confirm with the server's numbers -> ONE run carrying the plan's own acknowledgement", async () => {
    const d = deps();
    const out = await sendImgRun(body, "Generate 3?", d, { roll: 9, runId: "a".repeat(32), key: "k1" });
    assert.deepEqual(out, { ok: true, taskIds: ["901"], note: "" });
    assert.equal(d.calls.post.length, 1);
    assert.equal(d.calls.post[0][0], PLAN_PATH);
    assert.equal(d.calls.post[0][1].csrf, "tok");
    assert.equal(d.calls.post[0][1].var_mode, "random");
    assert.match(d.calls.confirm[0], /Send 3 generations\?/);
    assert.match(d.calls.confirm[0], /1,600 credits in total/);
    assert.equal(d.calls.run.length, 1);
    const sent = d.calls.run[0];
    assert.deepEqual(sent.ack, { count: 3, jobs: 1, each: 1600, covered: 0, total: 1600, digest: "dg" });
    assert.equal(sent.run_id, "a".repeat(32));
    assert.equal(sent.csrf, "tok");
    assert.equal(sent.run_seed, 9);
    assert.equal(runConfirmText(PLAN, "L").split("\n")[0], "L");
  });
  test("Cancel sends nothing; a refused plan, READ_ONLY and a lost POST never post (again)", async () => {
    const c = deps({ confirm: false });
    assert.deepEqual(await sendImgRun(body, "x", c, { key: "k2" }), { ok: false });
    assert.equal(c.calls.run.length, 0);
    const e = deps({ plan: { error: "Pick 1 to 4 images." } });
    assert.equal((await sendImgRun(body, "x", e, { key: "k3" })).error, "Pick 1 to 4 images.");
    assert.equal(e.calls.run.length + e.calls.confirm.length, 0);
    const ro = deps({ plan: { ...PLAN, read_only: true } });
    assert.match((await sendImgRun(body, "x", ro, { key: "k4" })).error, /READ_ONLY/);
    assert.equal(ro.calls.run.length, 0);
    const lost = deps({ run: { lost: true } });
    assert.equal((await sendImgRun(body, "x", lost, { key: "k5" })).error, LOST_POST_WORDS);
    assert.equal(lost.calls.run.length, 1);
    const moved = deps({ run: { data: { error: "The price moved since you confirmed — nothing was sent.", plan: PLAN } } });
    assert.match((await sendImgRun(body, "x", moved, { key: "k6" })).error, /price moved/);
    assert.equal(moved.calls.run.length, 1, "a moved price is reported, never re-sent");
  });
  test("a single template send with a card covering it asks nothing and sends no acknowledgement", async () => {
    const one = { ...PLAN, mode: "random", count: 1, covered: 1, total: 0 };
    const d = deps({ plan: one });
    await sendImgRun({ ...body, count: 1, prompt: "{a|b} glade" }, "x", d, { key: "k7" });
    assert.equal(d.calls.confirm.length, 0);
    assert.equal(d.calls.run[0].ack, undefined);
  });
  test("the latch: a second send for the same shot while one is out is refused", async () => {
    let release;
    const slow = deps();
    slow.post = () => new Promise((r) => { release = () => r(PLAN); });
    const first = sendImgRun(body, "x", slow, { key: "same" });
    const second = await sendImgRun(body, "x", slow, { key: "same" });
    assert.equal(second.ok, false);
    assert.match(second.error, /Still sending/);
    while (!release) await new Promise((r) => setTimeout(r, 1));
    release();
    assert.equal((await first).ok, true);
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
  test("every caller of /api/generate in gallery/src is one of those three road calls", () => {
    // any spelling -- fetch, apiPost, submitTask -- of the bare route
    const hits = [];
    for (const f of walk(SRC)) {
      const n = (codeOnly(read(f)).match(/["']\/api\/generate["']/g) || []).length;
      if (n) hits.push(path.relative(SRC, f).split(path.sep).join("/") + ":" + n);
    }
    assert.deepEqual(hits.sort(), ["components/TsubakiEditBar.jsx:1", "components/UpscalePanel.jsx:1", "gen/useGenerate.js:1"]);
  });
});

/* ---- the Loom (review S2): every /api/generate caller under loom/ pinned too ---- */
const LOOM = path.join(ROOT, "loom");
function walkLoom(dir, out = []) {
  for (const n of readdirSync(dir)) {
    if (["node_modules", "dist", "test", "vendor", "scripts"].includes(n)) continue;
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) walkLoom(p, out);
    else if (/\.(js|jsx|mjs)$/.test(n)) out.push(p);
  }
  return out;
}
const loomRel = (f) => path.relative(LOOM, f).split(path.sep).join("/");

describe("the Loom's calls to the generate routes", () => {
  const files = walkLoom(LOOM);
  const count = (re) => {
    const hits = [];
    for (const f of files) {
      const n = (codeOnly(read(f)).match(re) || []).length;
      if (n) hits.push(loomRel(f) + ":" + n);
    }
    return hits.sort();
  };
  test("/api/generate: ONE fetch, the Image tab's plain count-1 send, behind the route check", () => {
    assert.deepEqual(count(/["']\/api\/generate["']/g), ["master-storyboard.jsx:1"]);
    const src = codeOnly(read(path.join(LOOM, "master-storyboard.jsx")));
    const at = src.indexOf("const genImage = async");
    const post = src.indexOf('fetch("/api/generate"', at);
    assert.ok(at >= 0 && post > at, "the one fetch is genImage's");
    const route = src.indexOf("if (imgSendRoute(asked) === \"run\") return genImageRun(entry, asked);", at);
    assert.ok(route > at && route < post, "the run road is taken, and returns, before the single send is reached");
    const run = src.indexOf("const genImageRun = async");
    assert.ok(run >= 0 && src.slice(run, src.indexOf("\n  };", run)).includes("await sendImgRun("),
      "genImageRun sends through loom-run.js's road");
  });
  test("/api/generate/plan only from loom-run.js; /run never posted from loom/ (submitRun is the one poster)", () => {
    assert.deepEqual(count(/["']\/api\/generate\/plan["']/g), ["src/loom-run.js:1"]);
    assert.deepEqual(count(/\/api\/generate\/run/g), []);
    assert.deepEqual(count(/\bsubmitRun\b/g), ["master-storyboard.jsx:2"], "imported once, handed over once");
    assert.match(codeOnly(read(path.join(LOOM, "master-storyboard.jsx"))), /run: submitRun,/);
    const road = codeOnly(read(path.join(LOOM, "src", "loom-run.js")));
    assert.equal((road.match(/\bdeps\.run\(/g) || []).length, 1, "one POST per send");
    assert.ok(road.indexOf("if (inflight.has(key)) return") < road.indexOf("inflight.add(key)"), "latched first");
    assert.doesNotMatch(road, /retry|setTimeout/, "a run is never posted again");
  });
});

describe("the dock's badge prices what the send will force (review B1)", () => {
  test("useGenerate prices with no_card exactly when forcesNoCard(plan)", () => {
    const hook = codeOnly(read(path.join(SRC, "gen", "useGenerate.js")));
    assert.match(hook, /const forceNoCard = forcesNoCard\(plan\);/);
    assert.match(hook, /payload: forceNoCard \? \{ \.\.\.p, no_card: true \} : p/);
    assert.match(hook, /s\.varMode, forceNoCard,/, "a change of it re-prices");
    assert.ok(hook.indexOf("const forceNoCard") < hook.indexOf("const build = useCallback"));
  });
  test("the Inspector names the shell Copy as CLI is quoted for (review S3)", () => {
    const ui = codeOnly(read(path.join(SRC, "components", "RunInspector.jsx")));
    assert.match(ui, /entry\.cli\.shell_name/);
    assert.match(ui, /tab === "cli" && shell &&/);
  });
});

describe("owner walk 2026-09-29: a Matrix of 3 is quoted as 3, not as 1 (screenshots 21a/21b)", () => {
  // Tsubaki.3, prompt "{red|blue|green} dress, {masterpiece}", Matrix: the button read
  // "Generate 3" and the cost line "≈ 3,400 credits" -- one image's price. The badge prices ONE
  // cell (the payload's count is 1 in a Matrix); the cost line now multiplies by the cells.
  const PROMPT = "{red|blue|green} dress, {masterpiece}";
  test("quoteSends: a Matrix of N cells is N sends of the one priced request; anything else is 1", () => {
    const m = planJobs(PROMPT, {}, "matrix", 1, 7);
    assert.equal(m.images, 3);
    assert.equal(quoteSends(m), 3);
    assert.equal(quoteSends(planJobs("{a} dress", {}, "matrix", 1, 7)), 1, "a one-cell Matrix is one send");
    assert.equal(quoteSends(planJobs(PROMPT, {}, "random", 3, 7)), 1, "a Random run's count is in its request");
    assert.equal(quoteSends(planJobs("plain", {}, "random", 4, 7)), 1, "a batch is one task");
    assert.equal(quoteSends(planJobs("{" + "a|".repeat(30) + "b} {c|d}", {}, "matrix", 1, 7)), 1, "over the cap sends nothing");
    assert.equal(quoteSends(null), 1);
  });
  test("the badge's total is the confirm's total: 3,400 each × 3 = 10,200 on both", () => {
    const sends = quoteSends(planJobs(PROMPT, {}, "matrix", 1, 7));
    const each = 3400;                                   // /api/price of one cell (no_card, forced)
    const badgeTotal = each * sends;
    // the server's quote for the same run: each × (jobs − covered); a Matrix is never covered
    const c = confirmCopy({ mode: "matrix", count: 3, jobs: 3, each, covered: 0, total: each * 3, card: null });
    assert.equal(badgeTotal, 10200);
    assert.equal(c.credits, "≈ 10,200 credits in total · 3,400 each × 3");
    assert.ok(c.credits.startsWith("≈ " + fmt(badgeTotal) + " credits"), "same total, same words");
  });
  test("the badge multiplies the settled price by `sends` and says 'each' beneath", () => {
    const badge = codeOnly(read(path.join(SRC, "components", "CostBadge.jsx")));
    assert.match(badge, /const sendsN = Math\.max\(1, cardCount\(props\.sends\) \|\| 1\);/);
    assert.match(badge, /const total = n \* sendsN;/);
    assert.match(badge, /\+ "≈ " \+ fmt\(total\) \+ " credits";/, "the main line is the total");
    assert.match(badge, /: \(warn \|\| short \? "⚠ " : ""\) \+ "≈ " \+ fmt\(total\);/, "and the chip's value");
    assert.match(badge, /parts\.push\(fmt\(sendsN\) \+ " images", "≈ " \+ fmt\(Number\(d\.cost\)\) \+ " each"\);/,
      "the per-image figure is only ever shown saying 'each'");
    const dock = codeOnly(read(path.join(SRC, "components", "GenerateDrawer.jsx")));
    assert.match(dock, /<CostBadge ref=\{costRef\} stack count=\{s\.varMode === "matrix" \? 1 : s\.count\}\s+sends=\{quoteSends\(g\.run\.plan\)\}/);
  });
});

describe("owner walk 2026-09-29: the desktop prompt tints its variables in the box (screenshot 22)", () => {
  const join = (runs) => runs.map((r) => r.t).join("");
  test("{red|blue|green} tints; {masterpiece} with no | does not", () => {
    const p = "{red|blue|green} dress, {masterpiece}";
    const runs = promptTint(p, {});
    assert.equal(join(runs), p, "the runs join back to the text character for character");
    assert.deepEqual(runs, [{ t: "{red|blue|green}", kind: "var" }, { t: " dress, {masterpiece}", kind: "" }]);
  });
  test("lists tint, refusals tint peach, escapes and plain text stay plain -- and every run joins back", () => {
    const lists = { poses: ["kneeling", "turning"] };
    const cases = [
      ["a __poses__ b", [["a ", ""], ["__poses__", "var"], [" b", ""]]],
      ["a __nope__ b", [["a ", ""], ["__nope__", "bad"], [" b", ""]]],
      ["\\{a|b} x", [["\\{a|b} x", ""]]],
      ["{a|{b|c}} x", [["{a|{b|c}}", "bad"], [" x", ""]]],
      ["{ | } x", [["{ | }", "bad"], [" x", ""]]],
      ["plain, {x}, (y:1.2)", [["plain, {x}, (y:1.2)", ""]]],
      ["", []],
    ];
    for (const [p, want] of cases) {
      const runs = promptTint(p, lists);
      assert.equal(join(runs), p, p);
      assert.deepEqual(runs.map((r) => [r.t, r.kind]), want, p);
    }
  });
  test("the textarea draws the tint under itself with spell-check off", () => {
    const dock = codeOnly(read(path.join(SRC, "components", "GenerateDrawer.jsx")));
    assert.match(dock, /const runs = useMemo\(\(\) => promptTint\(value, lists\), \[value, lists\]\);/);
    assert.match(dock, /<textarea ref=\{taRef\} className="mgdock-prompt" rows=\{rows\} value=\{value\} spellCheck=\{false\}/);
    assert.match(dock, /<TintedPrompt value=\{s\.prompt\} lists=\{g\.run\.lists\} rows=\{promptRows\}/);
    const css = read(path.join(SRC, "styles", "dock.css"));
    const layer = css.match(/\.mgdock-prompt-tint \{[^}]*\}/)[0];
    for (const rule of ["position: absolute", "pointer-events: none", "font-size: 16px", "line-height: 1.5",
      "font-weight: 300", "white-space: pre-wrap", "color: transparent"]) {
      assert.ok(layer.includes(rule), "the layer's metrics are the textarea's: " + rule);
    }
    assert.match(css, /\.mgdock-promptwrap > \.mgdock-prompt \{ position: relative; \}/, "the textarea is positioned...");
    assert.ok(dock.indexOf('className="mgdock-prompt-tint"') < dock.indexOf('className="mgdock-prompt" rows={rows}'),
      "...and comes after the layer, so it paints on top");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { balanceLine, spendLandedKey } from "../src/loom-core.js";

/* THE GENERATE PANEL'S BALANCE LINE (owner walk 2026-09-30). After two paid renders the Loom's
   Generate panel still read "2151263 credits · 9 cards" while the gallery header read 2,079,763:
   both Loom views read /api/account once, on mount, and printed the number raw. The line is now
   grouped like the header and re-read on a bind and whenever a spend lands. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "..", "master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/\s.*$/gm, "");
const CODE = codeOnly(SRC);

describe("balanceLine: grouped like the gallery header", () => {
  test("the walk's number reads with thousands separators", () => {
    assert.deepEqual(balanceLine({ credits: 2151263, cards: 9 }),
      { credits: Number(2151263).toLocaleString(), cards: "9 cards", claim: "" });
    assert.equal(balanceLine({ credits: 2079763, cards: 9 }).credits, Number(2079763).toLocaleString());
    assert.notEqual(balanceLine({ credits: 2151263 }).credits, "2151263", "never the raw digits");
  });
  test("one card, none, unknown credits, and a claimable amount", () => {
    assert.equal(balanceLine({ credits: 0, cards: 1 }).cards, "1 card");
    assert.equal(balanceLine({ credits: 0 }).cards, "0 cards");
    assert.equal(balanceLine({ cards: 2 }).credits, "—");
    assert.equal(balanceLine({ credits: 5, claim_credits: 12000 }).claim, "+" + Number(12000).toLocaleString() + " claimable");
    assert.equal(balanceLine(null).credits, "—");
  });
});

describe("spendLandedKey: changes when a spend lands, and only then", () => {
  const k = (...m) => spendLandedKey(...m);
  test("a render going out (accepted: charged) and landing (done, its picture) both move it", () => {
    const idle = k({}, {});
    const sub = k({ E2: { phase: "submitting", msg: "Submitting…" } }, {});
    const out = k({ E2: { phase: "running", msg: "Rendering… (task 123456)" } }, {});
    const done = k({ E2: { phase: "done", msg: "Done", mid: "V2" } }, {});
    assert.equal(sub, idle, "a send not yet answered has spent nothing");
    assert.notEqual(out, sub, "accepted: PixAI has charged it");
    assert.notEqual(done, out, "landed");
    const again = k({ E2: { phase: "done", msg: "Done", mid: "V3" } }, {});
    assert.notEqual(again, done, "a second paid take of the same shot lands too");
  });
  test("the waiting tiers and the messages do not move it (one read out, one read in)", () => {
    const run = k({ E2: { phase: "running", msg: "Rendering… (task 1)" } });
    for (const phase of ["slow", "stale", "paused"]) {
      assert.equal(k({ E2: { phase, msg: "Taking longer than expected (21m, task 1)" } }), run, phase);
    }
    const d1 = k({ E2: { phase: "done", msg: "Done", mid: "V2" } });
    assert.equal(k({ E2: { phase: "done", msg: "That render finished; its clip is in your library.", mid: "V2" } }), d1);
  });
  test("every generation state counts, each in its own slot (an image landing is a spend too)", () => {
    const shots = { E2: { phase: "done", mid: "V2" } };
    assert.notEqual(k(shots, {}), k(shots, { E2: { phase: "done", mid: "I9" } }));
    assert.notEqual(k({ A: { phase: "running" } }, {}), k({}, { A: { phase: "running" } }));
  });
});

describe("the wiring: both Loom views read through useAccountLine", () => {
  test("one hook re-reads /api/account on a bind and whenever the spend key moves", () => {
    const i = CODE.indexOf("function useAccountLine(landedKey, bind) {");
    assert.ok(i >= 0, "useAccountLine is gone -- re-point this test, never drop it");
    const body = CODE.slice(i, CODE.indexOf("\n}\n", i));
    assert.match(body, /fetch\("\/api\/account"\)/);
    assert.match(body, /\}, \[landedKey, bind\]\);/, "re-read on a bind and on a landed spend");
    assert.match(body, /if \(live\) setAcct\(d\)/, "an overtaken read is dropped");
    assert.match(body, /return \(\) => \{ live = false; \};/);
  });
  test("desktop and phone pass the board's five generation states and their bound shot", () => {
    const key = "spendLandedKey(genState, genImgState, genEditState, genRefState, genFixState)";
    assert.ok(CODE.includes("const acct = useAccountLine(" + key + ", String(selShot || \"\"));"), "LoomV2");
    assert.ok(CODE.includes("const acct = useAccountLine(" + key + ",\n    (genOpen ? \"gen:\" : \"\") + String(selShot || \"\"));"), "LoomMobile");
    assert.doesNotMatch(CODE, /useEffect\(\(\) => \{ fetch\("\/api\/account"\)\.then\(\(r\) => r\.json\(\)\)\.then\(setAcct\)/,
      "no view reads the balance once on mount any more");
  });
  test("both lines print balanceLine's pieces, never the raw number", () => {
    assert.equal((CODE.match(/const bal = balanceLine\(acct\);/g) || []).length, 2);
    assert.doesNotMatch(CODE, /acct\.credits == null \? "—" : acct\.credits\}/);
    assert.doesNotMatch(CODE, /\+\{acct\.claim_credits\} claimable/);
  });
});

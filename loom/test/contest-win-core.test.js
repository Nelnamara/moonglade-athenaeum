import { test, describe } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  tierLabel, tierPill, bestWin, dayOfTs, isDecided, rowStatus, stateLine, outcomeView,
  contestOptions, defaultContestId, canCheck,
} from "../../gallery/src/lib/contestWinCore.js";

/* Contest wins, VERIFIED (L3): the words and states the surfaces draw. The rules that decide
   what IS a win live on the server (moonglade_contest_wins.py, dev/tests/test_contest_wins.py);
   this pins what the row and the Check dialog say about them. Two laws run through it:
   a placement is a TIER plus the prize, never a numbered place, and a check that did not verify
   reads in peach ("warn"), never ruby -- while an empty list is undecided, never "lost". */

const NOW = Date.parse("2026-09-29T12:00:00Z");
const PAST = "2026-09-25T05:00:00Z";
const FUTURE = "2026-10-05T05:00:00Z";
const win = (tier, prize) => ({ artwork_id: "a1", tier, prize_amount: prize,
  label: tierLabel(tier, prize), how: "auto", receipt_url: "https://pixai.art/en/artwork/a1" });

describe("tier wording", () => {
  test("a tier plus the prize", () => {
    assert.equal(tierLabel(2, 200000), "Tier 2, 200,000 credits");
    assert.equal(tierLabel(1, 500000), "Tier 1, 500,000 credits");
    assert.equal(tierLabel(3, 0), "Tier 3");
    assert.equal(tierPill(2), "TIER 2");
  });

  test("never a numbered place, at any tier", () => {
    for (const t of [1, 2, 3, 4, 11, 12, 13, 21, 22]) {
      const texts = [tierLabel(t, 100000), tierPill(t), rowStatus({ won: true, wins: [win(t, 5)], result_at: PAST }, NOW).text];
      for (const s of texts) {
        assert.ok(!/\b\d+(st|nd|rd|th)\b/i.test(s), s + " reads as a numbered place");
        assert.ok(!/place/i.test(s), s + " says place");
      }
    }
  });

  test("the best win is the lowest tier", () => {
    assert.equal(bestWin({ wins: [win(3, 1), win(1, 9), win(2, 5)] }).tier, 1);
    assert.equal(bestWin({ wins: [] }), null);
    assert.equal(bestWin(null), null);
  });
});

describe("the My-entries status pill", () => {
  test("running and awaiting results", () => {
    assert.deepEqual(rowStatus({ active: true, result_at: FUTURE }, NOW), { cls: "", text: "RUNNING", sub: "" });
    assert.equal(rowStatus({ active: false, result_at: FUTURE }, NOW).text, "AWAITING RESULTS");
    assert.equal(rowStatus({ active: false }, NOW).text, "AWAITING RESULTS", "no result date is not decided");
  });

  test("a verified win: gold, TIER n, the prize underneath", () => {
    const s = rowStatus({ active: false, result_at: PAST, won: true, wins: [win(2, 200000)] }, NOW);
    assert.deepEqual(s, { cls: "won", text: "🏆 TIER 2", sub: "Tier 2, 200,000 credits" });
  });

  test("results are out but no win is verified: still checking, not 'not placed'", () => {
    const base = { active: false, result_at: PAST, won: false, wins: [] };
    assert.equal(rowStatus({ ...base, check: { state: "none" } }, NOW).text, "CHECKING RESULTS");
    assert.equal(rowStatus({ ...base, check: { state: "pending", decided: false } }, NOW).text, "CHECKING RESULTS");
    assert.equal(rowStatus({ ...base }, NOW).text, "CHECKING RESULTS");
  });

  test("'not placed' only once the check has finished with a decided list", () => {
    const base = { active: false, result_at: PAST, won: false, wins: [] };
    assert.equal(rowStatus({ ...base, check: { state: "settled", decided: true } }, NOW).text, "NOT PLACED");
    assert.equal(rowStatus({ ...base, check: { state: "expired", decided: true } }, NOW).text, "NOT PLACED");
  });

  test("an expired check that never saw a list says so, and never claims a loss", () => {
    const s = rowStatus({ active: false, result_at: PAST, won: false, wins: [], check: { state: "expired", decided: false } }, NOW);
    assert.equal(s.text, "NO RESULT FOUND");
    assert.ok(!/lost|not placed/i.test(s.text));
  });

  test("an old flat win the check has not confirmed is not shown as won", () => {
    const s = rowStatus({ active: false, result_at: PAST, won: false, unverified_legacy: true, check: { state: "pending" } }, NOW);
    assert.notEqual(s.cls, "won");
  });

  test("decided follows the result date", () => {
    assert.equal(isDecided({ result_at: PAST }, NOW), true);
    assert.equal(isDecided({ result_at: FUTURE }, NOW), false);
    assert.equal(isDecided({ result_at: "" }, NOW), false);
  });
});

describe("the state line under the Check row", () => {
  test("verified reads the tier and the prize", () => {
    assert.deepEqual(stateLine({ won: true, wins: [win(3, 100000)] }),
      { tone: "ok", text: "Verified · Tier 3, 100,000 credits" });
  });

  test("not verified yet says the app re-checks daily, until when", () => {
    const until = Date.parse("2026-10-09T05:00:00Z") / 1000;
    const s = stateLine({ won: false, check: { state: "pending", until } });
    assert.equal(s.tone, "quiet");
    assert.match(s.text, /^Not verified yet · the app re-checks daily until 20\d\d-\d\d-\d\d$/);
    assert.equal(s.text.split(" until ")[1], dayOfTs(until));
  });

  test("no schedule yet, settled, expired: each says what is true", () => {
    assert.match(stateLine({ check: { state: "none" } }).text, /^Not verified yet · the app checks daily/);
    assert.match(stateLine({ check: { state: "settled" } }).text, /^Not verified · the app has finished checking/);
    assert.match(stateLine({ check: { state: "expired" } }).text, /Paste your link and press Check/);
    assert.match(stateLine(null).text, /^Not verified yet/);
  });

  test("nothing is ever called lost", () => {
    for (const st of ["none", "pending", "settled", "expired"]) {
      assert.ok(!/lost|lose/i.test(stateLine({ check: { state: st } }).text));
    }
  });
});

describe("what a Check answer looks like", () => {
  test("verified: ok, the tier and prize, the receipt link", () => {
    const v = outcomeView({ verified: true, state: "verified", wins: [{ label: "Tier 2, 200,000 credits", tier: 2, prize_amount: 200000 }],
      receipt_url: "https://pixai.art/en/artwork/1" });
    assert.deepEqual(v, { tone: "ok", text: "Verified · Tier 2, 200,000 credits", receipt: "https://pixai.art/en/artwork/1" });
  });

  test("results not out yet is quiet, not an error", () => {
    const v = outcomeView({ verified: false, state: "undecided", message: "That contest hasn't published its winners yet." });
    assert.equal(v.tone, "quiet");
  });

  test("every refusal is peach ('warn'), including a failed read and a bad link", () => {
    for (const state of ["not_found", "no_placement", "not_yours", "not_pixai", "no_link", "no_contest", "failed", "cooldown"]) {
      const v = outcomeView({ verified: false, state, message: "m-" + state });
      assert.equal(v.tone, "warn", state);
      assert.equal(v.text, "m-" + state);
    }
    assert.equal(outcomeView({ error: "Your session expired." }).tone, "warn");
    assert.equal(outcomeView(null).tone, "warn");
  });

  test("peach in the styles, never ruby, for a refused check", () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const css = fs.readFileSync(path.join(here, "../../gallery/src/styles/myart-contests.css"), "utf8");
    const block = css.slice(css.indexOf("E4 · Record a win"));
    assert.match(block, /\.mgcrw-msg\.warn\s*\{[^}]*var\(--peach\)/);
    const rules = block.match(/\.mgcrw[^{]*\{[^}]*\}/g) || [];
    for (const r of rules) assert.ok(!/--red|ruby|#f38ba8/i.test(r), "ruby in " + r);
  });
});

describe("the picker and the Check button", () => {
  const rows = [
    { contest_id: "2", title: "Beta", won: false, active: false, result_at: PAST },
    { contest_id: "1", title: "Alpha", won: true, active: false, result_at: PAST },
    { contest_id: "3", title: "Gamma", won: false, active: true, result_at: FUTURE },
  ];

  test("unverified contests come first: that is what the fallback is for", () => {
    assert.deepEqual(contestOptions(rows).map((o) => o.id), ["2", "3", "1"]);
    assert.deepEqual(contestOptions([{ contest_id: "", title: "x" }]), []);
  });

  test("the picker starts on the first decided contest without a win", () => {
    assert.equal(defaultContestId(rows, NOW), "2");
    assert.equal(defaultContestId([rows[1]], NOW), "1");
    assert.equal(defaultContestId([], NOW), "");
  });

  test("Check needs a pasted link and never fires twice at once", () => {
    assert.equal(canCheck("", false), false);
    assert.equal(canCheck("   ", false), false);
    assert.equal(canCheck("pixai.art/en/artwork/1", false), true);
    assert.equal(canCheck("pixai.art/en/artwork/1", true), false);
  });
});

describe("the surfaces are wired to it", () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const read = (p) => fs.readFileSync(path.join(here, "../../gallery/src", p), "utf8");

  test("the dialog POSTs only to the check route, with the csrf token, and never on open", () => {
    const src = read("components/ContestRecordWin.jsx");
    const posts = src.match(/apiPost\(([^,]+),/g) || [];
    assert.deepEqual(posts, ['apiPost("/api/contest/check",']);
    assert.match(src, /apiPost\("\/api\/contest\/check", \{ csrf,/);
    // the only GET is the csrf token every POST on this surface carries
    assert.deepEqual(src.match(/apiGet\(([^)]+)\)/g), ['apiGet("/api/myart/items")']);
    const eff = src.slice(src.indexOf("useEffect"), src.indexOf("const row ="));
    assert.ok(!eff.includes("/api/contest/check"), "nothing is checked when the dialog opens");
  });

  test("desktop and phone both offer the link, and the row pill reads the tier", () => {
    assert.match(read("components/ContestMyEntries.jsx"), /It won but isn't shown…/);
    assert.match(read("components/ContestMyEntries.jsx"), /rowStatus\(r\)/);
    assert.match(read("components/ContestsMobile.jsx"), /It won but isn't shown…/);
    assert.match(read("components/ContestsMobile.jsx"), /<ContestRecordWin phone/);
  });

  test("the winners strip says tier, not a numbered place", () => {
    const src = read("components/ContestDetail.jsx");
    assert.match(src, /"TIER " \+ Number\(n\)/);
    assert.ok(!/"TH"|\["TH", "ST", "ND", "RD"\]/.test(src), "the ordinal suffix table is gone");
  });
});

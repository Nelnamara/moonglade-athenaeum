import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  CARD_W, CARD_H, rarestEarned, honorsCardModel, standingLine, vigilLine, shareText,
  wrapLines, drawHonorsCard,
} from "../../gallery/src/folio/honorsCardCore.js";

/* The Honors card (O6), pure. Every honor and name is invented. The rules under the tests:
   feats reach the card as ONE number ("N found") and nothing else -- never a name, an id or a
   picture -- and the three badges are the rarest EARNED honors that are not feats. */

const H = (id, over = {}) => ({ id, name: "Honor " + id, tier: "common", bucket: "ladder",
  metric: "images", threshold: 10, earned: true, points: 5, ...over });
const FEAT = (id, over = {}) => H(id, { tier: "feat", bucket: "feat", points: 0, ...over });

// a fake 2D context: records what was drawn, measures a character as 8 px
function fakeCtx() {
  const calls = [];
  const rec = (name) => (...args) => { calls.push([name, ...args]); };
  const ctx = {
    calls,
    measureText: (t) => ({ width: String(t).length * 8 }),
    createLinearGradient: () => ({ addColorStop: rec("stop") }),
  };
  for (const n of ["fillRect", "strokeRect", "fillText", "drawImage", "beginPath", "arc", "fill"]) ctx[n] = rec(n);
  return ctx;
}
const ASSETS = (over = {}) => ({
  palette: { base: "#0", mantle: "#1", text: "#2", subtext: "#3", overlay0: "#4", surface0: "#5", gold: "#6", lavender: "#7" },
  tiers: { common: "#c", rare: "#r", epic: "#e", legendary: "#l" }, mark: null, images: {}, ...over,
});
const texts = (ctx) => ctx.calls.filter((c) => c[0] === "fillText").map((c) => c[1]);

describe("the size", () => {
  test("1200 by 630", () => { assert.equal(CARD_W, 1200); assert.equal(CARD_H, 630); });
});

describe("the three rarest earned honors", () => {
  test("rarity first (legendary down), then points, then the newest", () => {
    const list = [H("c1"), H("r1", { tier: "rare" }), H("l1", { tier: "legendary", points: 100 }),
      H("e1", { tier: "epic", points: 40 }), H("e2", { tier: "epic", points: 60 }), H("l2", { tier: "legendary", points: 200 })];
    assert.deepEqual(rarestEarned(list, {}).map((b) => b.id), ["l2", "l1", "e2"]);
  });

  test("equal rarity and points: the more recently earned wins, undated last", () => {
    const list = [H("a", { tier: "epic" }), H("b", { tier: "epic" }), H("c", { tier: "epic" })];
    assert.deepEqual(rarestEarned(list, { a: "2026-01-01", b: "2026-05-01" }).map((b) => b.id), ["b", "a", "c"]);
  });

  test("only earned honors", () => {
    const list = [H("a", { tier: "legendary", earned: false }), H("b")];
    assert.deepEqual(rarestEarned(list, {}).map((b) => b.id), ["b"]);
  });

  test("a feat of any kind is never among them, even earned and even 'rarest'", () => {
    const list = [FEAT("f1"), H("m", { bucket: "meta", tier: "legendary" }), H("b", { bucket: "feat" }), H("c")];
    assert.deepEqual(rarestEarned(list, {}).map((b) => b.id), ["c"]);
  });

  test("fewer than three is fewer than three", () => {
    assert.equal(rarestEarned([H("a")], {}).length, 1);
    assert.deepEqual(rarestEarned(null, {}), []);
  });
});

describe("what the card says", () => {
  const list = [H("a"), H("b", { earned: false }), H("c", { bucket: "milestone" }), FEAT("f1"), FEAT("f2"), FEAT("f3", { earned: false })];

  test("the name, the floored completion, feats only as a count of the found", () => {
    const m = honorsCardModel({ user: "  Wren  ", achievements: list, earnedPoints: 1234.9, vigil: { day: 3, best: 7 }, date: "2026-09-29" });
    assert.equal(m.name, "Wren");
    assert.equal(m.points, 1234);
    assert.equal(m.pct, 66);          // 2 of 3 non-feat honors, floored
    assert.equal(m.found, 2);         // the two found feats; the unearned one is not counted
    assert.deepEqual(m.vigil, { day: 3, best: 7 });
    assert.equal(m.date, "2026-09-29");
  });

  test("finding a feat never moves the percentage", () => {
    const a = honorsCardModel({ achievements: list.slice(0, 4) });
    const b = honorsCardModel({ achievements: list });
    assert.equal(a.pct, b.pct);
    assert.notEqual(a.found, b.found);
  });

  test("no name falls back to the Folio's title; the name is bounded", () => {
    assert.equal(honorsCardModel({ achievements: [] }).name, "The Folio of Honors");
    assert.equal(honorsCardModel({ user: "x".repeat(200), achievements: [] }).name.length, 40);
  });

  test("the Vigil is optional and never below the day", () => {
    assert.equal(honorsCardModel({ achievements: [], vigil: null }).vigil, null);
    assert.equal(honorsCardModel({ achievements: [], vigil: { day: 0 } }).vigil, null);
    assert.deepEqual(honorsCardModel({ achievements: [], vigil: { day: 4, best: 2 } }).vigil, { day: 4, best: 4 });
  });

  test("the model has no feat in it anywhere but the count", () => {
    const named = [FEAT("secret-id", { name: "Secret Name" }), H("a")];
    const json = JSON.stringify(honorsCardModel({ achievements: named }));
    assert.ok(!json.includes("secret-id"));
    assert.ok(!json.includes("Secret Name"));
  });

  test("the lines", () => {
    const m = honorsCardModel({ achievements: list, vigil: { day: 3, best: 7 } });
    assert.equal(standingLine(m), "66% complete  ·  2 feats found");
    assert.equal(vigilLine(m), "Vigil  ·  day 3  ·  best 7");
    assert.equal(vigilLine(honorsCardModel({ achievements: [] })), "");
    assert.equal(standingLine(honorsCardModel({ achievements: [H("a")] })), "100% complete");
  });

  test("nothing about feats is said until one is found", () => {
    assert.ok(!/feat/i.test(standingLine(honorsCardModel({ achievements: [H("a"), FEAT("f", { earned: false })] }))));
  });

  test("the share text is the name and the numbers", () => {
    const m = honorsCardModel({ user: "Wren", achievements: [H("a")], earnedPoints: 2500 });
    assert.equal(shareText(m), "Wren · " + (2500).toLocaleString() + " points · 100% of the Folio");
  });
});

describe("wrapping", () => {
  test("wraps on words and stops at the line limit with an ellipsis", () => {
    const ctx = fakeCtx();
    const lines = wrapLines(ctx, "one two three four five six", 8 * 9, 2);
    assert.equal(lines.length, 2);
    assert.ok(lines[1].endsWith("…"));
    for (const l of lines) assert.ok(ctx.measureText(l).width <= 8 * 9);
  });
  test("a short line is left alone", () => {
    assert.deepEqual(wrapLines(fakeCtx(), "Honor a", 200, 2), ["Honor a"]);
  });
});

describe("drawing", () => {
  const list = [H("l", { tier: "legendary", name: "Gold One" }), H("e", { tier: "epic", name: "Purple Two" }),
    H("r", { tier: "rare", name: "Blue Three" }), H("c", { name: "Grey Four" }),
    FEAT("f1", { name: "Found Feat Name" })];
  const model = honorsCardModel({ user: "Wren", achievements: list, earnedPoints: 900, vigil: { day: 2, best: 5 }, date: "2026-09-29" });

  test("draws the name, points, completion, feats-found count, the Vigil and the three badges' names", () => {
    const ctx = fakeCtx();
    drawHonorsCard(ctx, model, ASSETS());
    const t = texts(ctx).join("|");
    for (const s of ["Wren", "900 points", "100% complete", "1 feats found", "Vigil", "day 2", "best 5", "Gold One", "Purple Two", "Blue Three"]) {
      assert.ok(t.includes(s), s);
    }
    assert.ok(!t.includes("Grey Four"), "the fourth-rarest is not drawn");
  });

  test("a found feat's name is never drawn; only its count is", () => {
    const ctx = fakeCtx();
    drawHonorsCard(ctx, model, ASSETS());
    assert.ok(!texts(ctx).join("|").includes("Found Feat Name"));
  });

  test("real badge art is drawn when it loaded, a rarity swatch when it did not", () => {
    const img = {};
    const withArt = fakeCtx();
    drawHonorsCard(withArt, model, ASSETS({ images: { l: img, e: img, r: img } }));
    assert.equal(withArt.calls.filter((c) => c[0] === "drawImage").length, 3);
    const without = fakeCtx();
    drawHonorsCard(without, model, ASSETS());
    assert.equal(without.calls.filter((c) => c[0] === "drawImage").length, 0);
  });

  test("the mark is drawn beside the name when there is one", () => {
    const ctx = fakeCtx();
    drawHonorsCard(ctx, model, ASSETS({ mark: {} }));
    assert.equal(ctx.calls.filter((c) => c[0] === "drawImage").length, 1);
  });

  test("no Vigil, no feats found: those lines are simply not drawn", () => {
    const ctx = fakeCtx();
    drawHonorsCard(ctx, honorsCardModel({ user: "Wren", achievements: [H("a")], earnedPoints: 5 }), ASSETS());
    const t = texts(ctx).join("|");
    assert.ok(!/Vigil/.test(t));
    assert.ok(!/feat/i.test(t));
  });

  test("the meter bar's width is the floored percentage of 520", () => {
    const ctx = fakeCtx();
    drawHonorsCard(ctx, honorsCardModel({ achievements: [H("a"), H("b", { earned: false }), H("c", { earned: false })] }), ASSETS());
    const bars = ctx.calls.filter((c) => c[0] === "fillRect" && c[2] === 340);
    assert.equal(bars[1][3], (520 * 33) / 100);
  });
});

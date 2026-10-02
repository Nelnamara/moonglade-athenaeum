import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  isFeatLike, JUMPS, JUMP_LABELS, jumpFor, progressOf, toGoText, jumpOf,
  completionOf, meterLine,
  SORT_KEY, SORTS, DEFAULT_SORT, readSort, loadSort, saveSort, sortNote, sortHonors,
  relicRows,
} from "../../gallery/src/folio/completionistCore.js";

/* The Folio for completionists' logic (Session O, O1-O3) and Small Calls L2's relic rows. Every
   honor below is invented: nothing in this file names a real honor, feat, riddle or line. The
   rule under every test is the same one the code keeps -- FEATS LEAK NOTHING: a feat is never in
   a total, never given a count, never sorted. */

const P = (current, threshold) => ({ current, threshold, left: Math.max(0, threshold - current),
  fraction: Math.min(1, current / threshold) });
const H = (id, over = {}) => ({ id, name: "Honor " + id, tier: "common", bucket: "ladder",
  metric: "images", threshold: 10, current: 0, earned: false, points: 5, ...over });
const FEAT = (id, over = {}) => H(id, { tier: "feat", bucket: "feat", earned: true, points: 0, ...over });

describe("what counts as a feat", () => {
  test("the feat tier, the feat bucket and the meta bucket", () => {
    assert.equal(isFeatLike(H("a", { tier: "feat" })), true);
    assert.equal(isFeatLike(H("a", { bucket: "feat" })), true);
    assert.equal(isFeatLike(H("a", { bucket: "meta" })), true);
    assert.equal(isFeatLike(H("a")), false);
    assert.equal(isFeatLike(H("a", { bucket: "streak", tier: "rare" })), false);
    assert.equal(isFeatLike(null), false);
  });
});

describe("O1: N to go, from the server's progress", () => {
  test("an unearned honor with progress reads threshold minus current and the true fraction", () => {
    const p = progressOf(H("a", { progress: P(4, 10) }));
    assert.deepEqual(p, { current: 4, threshold: 10, left: 6, fraction: 0.4 });
    assert.equal(toGoText(p), "6 to go");
  });

  test("no count, no moon, no pin for: no progress block, an earned honor, or a feat of any kind", () => {
    assert.equal(progressOf(H("a")), null);
    assert.equal(progressOf(H("a", { progress: P(4, 10), earned: true })), null);
    for (const over of [{ tier: "feat" }, { bucket: "feat" }, { bucket: "meta" }]) {
      assert.equal(progressOf(H("a", { progress: P(4, 10), ...over })), null, JSON.stringify(over));
    }
    assert.equal(progressOf(null), null);
  });

  test("numbers that are not a real count are no count", () => {
    for (const bad of [P(4, 0), P(4, -2), { current: "x", threshold: 10 }, { current: -1, threshold: 10 },
      { current: 4 }, "4/10", 7]) {
      assert.equal(progressOf(H("a", { progress: bad })), null, JSON.stringify(bad));
    }
  });

  test("left is recomputed from the two numbers, never trusted, and the fraction is clamped", () => {
    const p = progressOf(H("a", { progress: { current: 12, threshold: 10, left: 999, fraction: 5 } }));
    assert.equal(p.left, 0);
    assert.equal(p.fraction, 1);
    assert.equal(toGoText(p), "nearly there");
  });

  test("large counts are grouped like every other number in the Folio", () => {
    assert.equal(toGoText({ left: 12000 }), (12000).toLocaleString() + " to go");
  });

  test("the jump per metric: images to Generate, storyboards to the Loom, entries to Contests, published to Publish", () => {
    assert.equal(jumpFor("images"), "generate");
    assert.equal(jumpFor("storyboards"), "loom");
    assert.equal(jumpFor("contest_entries"), "contests");
    assert.equal(jumpFor("published"), "publish");
    assert.equal(jumpFor("likes"), "publish");
    assert.equal(jumpFor("shots"), "loom");
    assert.equal(jumpFor("entries"), "contests");
  });

  test("a metric with no surface has no jump, and neither do the prototype's own keys", () => {
    assert.equal(jumpFor("claims"), "");
    assert.equal(jumpFor("constructor"), "");
    assert.equal(jumpFor("__proto__"), "");
    assert.equal(jumpFor(undefined), "");
    for (const to of Object.values(JUMPS)) assert.ok(JUMP_LABELS[to], to);
  });

  test("an honor's jump exists only while it has a count", () => {
    assert.deepEqual(jumpOf(H("a", { progress: P(1, 10), metric: "images" })), { to: "generate", label: "Generate" });
    assert.equal(jumpOf(H("a", { metric: "images" })), null);                              // no count
    assert.equal(jumpOf(H("a", { progress: P(1, 10), metric: "images", earned: true })), null);
    assert.equal(jumpOf(H("a", { progress: P(1, 10), metric: "images", tier: "feat" })), null);
    assert.equal(jumpOf(H("a", { progress: P(1, 10), metric: "claims" })), null);          // count, no surface
  });
});

describe("O2: the completion meter", () => {
  const pool = [H("l1", { earned: true }), H("l2"), H("m1", { bucket: "milestone", earned: true }),
    H("s1", { bucket: "streak" }), H("k1", { bucket: "mastery", earned: true })];

  test("ladders, milestones and masteries only; the streaks fold in", () => {
    assert.deepEqual(completionOf(pool), { earned: 3, total: 5, pct: 60, found: 0 });
  });

  test("finding a feat never moves the meter: it adds to found and to nothing else", () => {
    const one = completionOf([...pool, FEAT("f1")]);
    const two = completionOf([...pool, FEAT("f1"), FEAT("f2"), FEAT("meta", { bucket: "meta" })]);
    assert.deepEqual([one.earned, one.total, one.pct], [3, 5, 60]);
    assert.deepEqual([two.earned, two.total, two.pct], [3, 5, 60]);
    assert.equal(one.found, 1);
    assert.equal(two.found, 3);
  });

  test("an unearned feat is not found and not a total either", () => {
    const c = completionOf([...pool, FEAT("f1", { earned: false })]);
    assert.deepEqual(c, { earned: 3, total: 5, pct: 60, found: 0 });
  });

  test("the percentage is floored, so 100 means done and 99.9 never rounds up to it", () => {
    const big = Array.from({ length: 1000 }, (_, i) => H("h" + i, { earned: i < 999 }));
    assert.equal(completionOf(big).pct, 99);
    assert.equal(completionOf(big.map((h) => ({ ...h, earned: true }))).pct, 100);
    assert.equal(completionOf(Array.from({ length: 3 }, (_, i) => H("t" + i, { earned: i < 2 }))).pct, 66);
  });

  test("an empty record is 0 of 0 at 0 percent, not a division by zero", () => {
    assert.deepEqual(completionOf([]), { earned: 0, total: 0, pct: 0, found: 0 });
    assert.deepEqual(completionOf(undefined), { earned: 0, total: 0, pct: 0, found: 0 });
  });

  test("the line names the three kinds, and the feats only as found and only once one is", () => {
    assert.equal(meterLine({ earned: 3, total: 5, found: 0 }), "3 of 5 ladders · milestones · masteries");
    assert.equal(meterLine({ earned: 3, total: 5, found: 2 }),
      "3 of 5 ladders · milestones · masteries   ·   Feats: 2 found");
    assert.ok(!/of\s+\d+\s+feats/i.test(meterLine({ earned: 3, total: 5, found: 2 })));
  });
});

describe("O3: the sort", () => {
  test("the four sorts, in the order the chips show them", () => {
    assert.deepEqual(SORTS.map((s) => s.key), ["default", "closest", "rarest", "newest"]);
    assert.deepEqual(SORTS.map((s) => s.label), ["Default", "Closest to earning", "Rarest", "Newest earned"]);
    assert.equal(DEFAULT_SORT, "default");
  });

  test("a stored value is a sort or the default", () => {
    assert.equal(readSort("rarest"), "rarest");
    for (const v of [undefined, null, "", "loudest", 3, {}]) assert.equal(readSort(v), "default");
    assert.equal(sortNote("closest"), SORTS[1].note);
    assert.equal(sortNote("nope"), SORTS[0].note);
  });

  test("remembered per device, in this browser's storage, and blocked storage does not break it", () => {
    const store = new Map();
    const ls = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
    assert.equal(loadSort(ls), "default");
    assert.equal(saveSort(ls, "newest"), true);
    assert.equal(store.get(SORT_KEY), "newest");
    assert.equal(loadSort(ls), "newest");
    store.set(SORT_KEY, "garbage");
    assert.equal(loadSort(ls), "default");
    const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
    assert.equal(loadSort(blocked), "default");
    assert.equal(saveSort(blocked, "rarest"), false);
    assert.equal(loadSort(null), "default");
    assert.equal(saveSort(null, "rarest"), true);
  });

  const items = [
    H("a", { progress: P(1, 10), points: 5 }),                                   // 0.1
    H("b", { progress: P(9, 10), points: 5 }),                                   // 0.9
    H("c", { progress: P(5, 10), points: 25, tier: "epic" }),                    // 0.5, more points
    H("d", { progress: P(5, 10), points: 10, tier: "rare" }),                    // 0.5
    H("e", { earned: true, tier: "legendary", points: 50 }),
    H("f", { metric: "unmeasured" }),                                            // no count
    H("g", { earned: true, tier: "common" }),
  ];

  test("default is the order it arrived in", () => {
    assert.deepEqual(sortHonors(items, "default", {}).map((h) => h.id), ["a", "b", "c", "d", "e", "f", "g"]);
    assert.deepEqual(sortHonors(items, "nonsense", {}).map((h) => h.id), ["a", "b", "c", "d", "e", "f", "g"]);
  });

  test("closest: unearned by fraction done, ties to more points, then no-count, then earned", () => {
    assert.deepEqual(sortHonors(items, "closest", {}).map((h) => h.id), ["b", "c", "d", "a", "f", "e", "g"]);
  });

  test("closest keeps arrival order among exact ties on both fraction and points", () => {
    const tie = [H("x", { progress: P(5, 10) }), H("y", { progress: P(5, 10) }), H("z", { progress: P(5, 10) })];
    assert.deepEqual(sortHonors(tie, "closest", {}).map((h) => h.id), ["x", "y", "z"]);
  });

  test("rarest: by rarity rank, legendary first, stable within a rank", () => {
    assert.deepEqual(sortHonors(items, "rarest", {}).map((h) => h.id), ["e", "c", "d", "a", "b", "f", "g"]);
    const odd = [H("p", { tier: "mystery" }), H("q", { tier: "common" })];
    assert.deepEqual(sortHonors(odd, "rarest", {}).map((h) => h.id), ["q", "p"]);
  });

  test("newest: earned ones by the day earned, undated after dated, then everything unearned", () => {
    const earned = [H("o1", { earned: true }), H("o2", { earned: true }), H("o3", { earned: true }),
      H("o4", { earned: true }), H("u1"), H("u2")];
    const at = { o1: "2026-01-05", o2: "2026-03-01", o3: "2026-03-01" };
    assert.deepEqual(sortHonors(earned, "newest", at).map((h) => h.id), ["o2", "o3", "o1", "o4", "u1", "u2"]);
  });

  test("a sort returns a new list and never touches the one it was given", () => {
    const copy = items.map((h) => h.id);
    sortHonors(items, "closest", {});
    assert.deepEqual(items.map((h) => h.id), copy);
    assert.notEqual(sortHonors(items, "default", {}), items);
  });

  test("FEATS ARE IN NONE OF THE SORTS, even handed to it", () => {
    const withFeats = [...items, FEAT("f1"), FEAT("f2", { bucket: "meta" }), H("f3", { tier: "feat" })];
    for (const key of SORTS.map((s) => s.key)) {
      const ids = sortHonors(withFeats, key, { f1: "2026-09-09" }).map((h) => h.id);
      assert.ok(!ids.some((id) => id === "f1" || id === "f2" || id === "f3"), key);
      assert.equal(ids.length, items.length, key);
    }
  });

  test("an unearned honor whose count is not known has no fraction to sort by", () => {
    const noCount = [H("n1", { metric: "unmeasured" }), H("n2", { progress: P(3, 10) })];
    assert.deepEqual(sortHonors(noCount, "closest", {}).map((h) => h.id), ["n2", "n1"]);
  });
});

describe("L2: relics by kind", () => {
  const skins = [
    { id: "free-one", name: "Free One", earned: true, unlock: null, desc: "free" },
    { id: "won-old", name: "Won Old", earned: true, unlock: "Unlock: Old", desc: "old" },
    { id: "won-new", name: "Won New", earned: true, unlock: "Unlock: New", desc: "new" },
    { id: "locked", name: "Locked", earned: false, unlock: "Unlock: Later", desc: "later" },
  ];
  const achievements = [
    H("old", { earned: true, skin: "won-old" }), H("new", { earned: true, skin: "won-new" }),
    H("later", { skin: "locked" }),
    H("ban-a", { earned: true, banner_reward: true, name: "Banner A" }),
    H("ban-b", { banner_reward: true, name: "Banner B" }),
  ];
  const earnedAt = { old: "2026-01-01", new: "2026-06-01", "ban-a": "2026-03-01", mk1: "2026-02-01", mk2: "2026-05-01" };
  const marks = [
    { id: "m-a", label: "Mark A", png: "/branding/marks/m-a.png", unlock: "mk1" },
    { id: "m-b", label: "Mark B", png: "/branding/marks/m-b.webp", animated: true, unlock: "mk2" },
  ];
  const rows = relicRows({ skins, achievements, marks, earnedAt, activeSkin: "won-old" });

  test("Skins, Banners, Marks, in that order", () => {
    assert.deepEqual(rows.map((r) => r.kind), ["skins", "banners", "marks"]);
    assert.deepEqual(rows.map((r) => r.label), ["Skins", "Banners", "Marks"]);
  });

  test("newest first within a row", () => {
    assert.deepEqual(rows[0].items.map((i) => i.id), ["won-new", "won-old"]);
    assert.deepEqual(rows[2].items.map((i) => i.id), ["m-b", "m-a"]);
  });

  test("nothing unearned is listed, and neither is a free skin", () => {
    const all = JSON.stringify(rows);
    assert.ok(!all.includes("locked") && !all.includes("Locked") && !all.includes("Banner B"));
    assert.ok(!all.includes("free-one"));
  });

  test("the active skin is marked; a mark carries its art and animation flag", () => {
    assert.equal(rows[0].items.find((i) => i.id === "won-old").active, true);
    assert.equal(rows[0].items.find((i) => i.id === "won-new").active, false);
    assert.equal(rows[2].items[0].png, "/branding/marks/m-b.webp");
    assert.equal(rows[2].items[0].animated, true);
  });

  test("a kind with nothing earned is hidden, so there are no empty slots", () => {
    const only = relicRows({ skins: [], achievements: [H("ban-a", { earned: true, banner_reward: true })], marks: [], earnedAt: {} });
    assert.deepEqual(only.map((r) => r.kind), ["banners"]);
    assert.deepEqual(relicRows({}), []);
    assert.deepEqual(relicRows({ skins: skins.slice(3), achievements: [], marks: [] }), []);
  });

  test("the model carries no placeholder, reserved slot or sealed-relic key: only earned things", () => {
    for (const row of rows) for (const it of row.items) {
      assert.deepEqual(Object.keys(it).filter((k) => /placeholder|reserved|secret|hidden|sealed|corner/i.test(k)), []);
    }
    assert.ok(rows.every((r) => r.items.length > 0));
  });

  test("an undated relic follows the dated ones", () => {
    const r = relicRows({ skins: [], achievements: [H("nb", { earned: true, banner_reward: true }),
      H("ob", { earned: true, banner_reward: true })], marks: [], earnedAt: { ob: "2026-01-01" } });
    assert.deepEqual(r[0].items.map((i) => i.id), ["ob", "nb"]);
  });
});

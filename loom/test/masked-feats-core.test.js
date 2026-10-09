import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  SEEN_KEY, SEEN_EPOCH, REVEAL, REVEAL_END, readSeen, unseenFeatIds, nextSeen, orderFeats,
  foundText, featCountText, veilState, revealFrame,
} from "../../gallery/src/folio/maskedFeatsCore.js";

/* The masked-feats logic (Session G): the seen record, the card order, the words for the
   counts, what the veil may show, and the glitch reveal's timings. Every feat here is an
   invented one -- nothing in this file names a real feat, riddle or line. */

const F = (id, earned = true) => ({ id, earned });

describe("the seen record", () => {
  test("its key is the literal folio.seen", () => {
    assert.equal(SEEN_KEY, "folio.seen");
  });

  test("a stored list is exact: every earned feat not on it is new", () => {
    const feats = [F("a"), F("b"), F("c", false)];
    assert.deepEqual(unseenFeatIds({ feats, earnedAt: {}, seen: ["a"] }), ["b"]);
    assert.deepEqual(unseenFeatIds({ feats, earnedAt: {}, seen: [] }), ["a", "b"]);
    assert.deepEqual(unseenFeatIds({ feats, earnedAt: {}, seen: ["a", "b", "zzz"] }), []);
  });

  test("with nothing ever stored, only a feat earned on or after the epoch is new", () => {
    const feats = [F("old"), F("after"), F("late"), F("undated"), F("locked", false)];
    const earnedAt = { old: "2026-09-01", after: SEEN_EPOCH, late: "2027-01-05" };
    assert.deepEqual(unseenFeatIds({ feats, earnedAt, seen: undefined }), ["after", "late"]);
    assert.deepEqual(unseenFeatIds({ feats, earnedAt, seen: null }), ["after", "late"]);
    // a value that is not a list is the same as nothing stored
    assert.deepEqual(unseenFeatIds({ feats, earnedAt, seen: "nope" }), ["after", "late"]);
    assert.deepEqual(unseenFeatIds({ feats, earnedAt, seen: undefined, since: "2027-01-01" }), ["late"]);
  });

  test("an unearned feat is never new, whatever the record says", () => {
    assert.deepEqual(unseenFeatIds({ feats: [F("x", false)], earnedAt: { x: SEEN_EPOCH }, seen: [] }), []);
  });

  test("readSeen keeps only ids", () => {
    assert.deepEqual(readSeen(["a", 3, "", null, "b"]), ["a", "b"]);
    assert.equal(readSeen(undefined), null);
    assert.equal(readSeen({}), null);
  });

  test("nextSeen adds every earned feat on the page once, keeping the old list", () => {
    assert.deepEqual(nextSeen(undefined, [F("a"), F("b"), F("c", false)]), ["a", "b"]);
    assert.deepEqual(nextSeen(["z", "a"], [F("a"), F("b")]), ["z", "a", "b"]);
    assert.deepEqual(nextSeen(["a"], [F("a")]), ["a"]);
  });

  test("the epoch is a date in earned_at's shape", () => {
    assert.match(SEEN_EPOCH, /^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("the order of the earned cards", () => {
  test("date order, oldest first; ties and undated keep the roster's order; unearned last", () => {
    const feats = [F("late"), F("none"), F("early"), F("tie1"), F("tie2"), F("locked", false)];
    const earnedAt = { late: "2026-09-21", early: "2026-09-14", tie1: "2026-09-21", tie2: "2026-09-21" };
    assert.deepEqual(orderFeats(feats, earnedAt).map((a) => a.id),
      ["none", "early", "late", "tie1", "tie2", "locked"]);
  });

  test("does not mutate its input", () => {
    const feats = [F("b"), F("a")];
    orderFeats(feats, { a: "2026-01-01", b: "2026-02-01" });
    assert.deepEqual(feats.map((a) => a.id), ["b", "a"]);
  });
});

describe("the words for the counts never say how many remain", () => {
  test("the header counts what is found and nothing else", () => {
    assert.equal(foundText(2, false), "2 found");
    assert.equal(foundText(0, false), "0 found");
    assert.equal(foundText(7, true), "7 found · all");
    assert.equal(featCountText(3), "3 found");
    for (const s of [foundText(2, false), featCountText(2)]) assert.ok(!/\d\s*\/\s*\d/.test(s), s);
  });
});

describe("what the veil may show", () => {
  const URL1 = "/feat-mask/" + "a1".repeat(16) + ".png";
  const masked = { riddle: "test riddle one", riddle_nsfw: "test riddle one, unleashed", mask_url: URL1 };

  test("a veil needs both a riddle and a mask", () => {
    assert.equal(veilState({ masked, all_found: false }).show, true);
    assert.equal(veilState({ masked: { riddle: "x" }, all_found: false }).show, false);
    assert.equal(veilState({ masked: { mask_url: URL1 }, all_found: false }).show, false);
    assert.equal(veilState(undefined).show, false);
    assert.equal(veilState(null).allFound, false);
  });

  test("only the server's own mask route is ever drawn", () => {
    for (const bad of ["/feat-mask/abc.png", "https://evil.example/" + "a1".repeat(16) + ".png", "/feat-mask/" + "A1".repeat(16) + ".png",
      "/feat-mask/" + "a1".repeat(16) + ".png)", "", null, undefined, 7]) {
      assert.equal(veilState({ masked: { riddle: "x", mask_url: bad } }).show, false, String(bad));
    }
    assert.equal(veilState({ masked }).maskUrl, URL1);
  });

  test("the unleashed twin shows only when Unleash is on and the server sent it", () => {
    assert.equal(veilState({ masked }, { unleashed: false }).riddle, "test riddle one");
    assert.equal(veilState({ masked }, { unleashed: true }).riddle, "test riddle one, unleashed");
    const plain = { riddle: "test riddle two", mask_url: URL1 };
    assert.equal(veilState({ masked: plain }, { unleashed: true }).riddle, "test riddle two");
  });

  test("search never matches the veil", () => {
    assert.equal(veilState({ masked }, { query: "riddle" }).show, false);
    assert.equal(veilState({ masked }, { query: "  " }).show, true);
    assert.equal(veilState({ masked: null, all_found: true }, { query: "x" }).allFound, false);
  });

  test("all found is a claim only the server makes, and only with no veil", () => {
    assert.equal(veilState({ masked: null, all_found: true }).allFound, true);
    assert.equal(veilState({ masked: null, all_found: false }).allFound, false);   // e.g. a pack with no riddles
    assert.equal(veilState({ masked, all_found: true }).allFound, false);
  });
});

describe("the glitch reveal (NOTES decision 3)", () => {
  test("the beats sit where the notes put them", () => {
    assert.deepEqual([REVEAL.HOLD, REVEAL.SNAP, REVEAL.RIBBON, REVEAL.VEIL, REVEAL.VEIL_FADE, REVEAL.STEP],
      [300, 540, 700, 900, 420, 60]);
    assert.equal(REVEAL.HOLD + REVEAL.STEP * REVEAL.STEPS, REVEAL.SNAP);   // 4 steps of 60 ms, .30 -> .54
    assert.equal(REVEAL_END, 1320);
  });

  test("0.00: the veil at rest, no split, no glow, no ribbon, next veil still hidden", () => {
    for (const t of [null, undefined, -5, 0, 299]) {
      const f = revealFrame(t, false);
      assert.deepEqual([f.art, f.split, f.glow, f.ribbon, f.veilIn, f.done, f.coverOpacity],
        ["veil", null, false, false, false, false, 1], String(t));
    }
  });

  test("0.30: the split, on 60 ms steps, +-4 / -+2 px", () => {
    const seen = [];
    for (let t = 300; t < 540; t += 60) {
      const f = revealFrame(t, false);
      assert.equal(f.art, "veil");
      assert.ok(f.split && Math.abs(f.split.dx) <= 4 && Math.abs(f.split.dy) <= 2);
      assert.equal(f.split.dy * 2, -f.split.dx);            // the -+2 mirror of +-4
      assert.equal(f.glow, false);
      seen.push(f.split.dx);
    }
    assert.deepEqual(seen, [-4, 0, 4, -4]);
    assert.deepEqual(revealFrame(359, false).split, revealFrame(300, false).split);   // constant within a step
    assert.notDeepEqual(revealFrame(360, false).split, revealFrame(300, false).split);
  });

  test("0.54: snap to the badge, the split collapses, the glow and band arrive", () => {
    const f = revealFrame(540, false);
    assert.deepEqual([f.art, f.split, f.glow, f.ribbon, f.veilIn, f.coverOpacity], ["badge", null, true, false, false, 0]);
  });

  test("0.70: the ribbon; 0.90: the next veil; 1.32: done", () => {
    assert.equal(revealFrame(699, false).ribbon, false);
    assert.equal(revealFrame(700, false).ribbon, true);
    assert.equal(revealFrame(899, false).veilIn, false);
    assert.equal(revealFrame(900, false).veilIn, true);
    assert.equal(revealFrame(1319, false).done, false);
    assert.equal(revealFrame(1320, false).done, true);
  });

  test("the effect always ends on a badge, never on the veil or on text", () => {
    assert.equal(revealFrame(1e6, false).art, "badge");
    assert.equal(revealFrame(1e6, false).split, null);
  });

  test("reduced motion: no split or jitter; the card at rest with its ribbon and the next veil in place", () => {
    for (const t of [null, 0, 320, 600, 5000]) {
      assert.deepEqual(revealFrame(t, true),
        { art: "badge", coverOpacity: 0, split: null, glow: true, ribbon: true, veilIn: true, done: true });
    }
  });
});

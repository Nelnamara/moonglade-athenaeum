import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  cadenceFor, POLL_MS, SLOW_AT_MS, SLOW_MS, STALE_AT_MS, STALE_MS, CEILING_MS,
} from "../../gallery/src/notify/pollCadence.js";

/* THE TIER TABLE (2026-08-23). A long video render used to be watched by two different
   hand-written schedules -- the Loom's pollShot and the video drawer's own poller, the latter
   carrying a copied set of thresholds under a literal "KEEP IN SYNC" comment. The drawer's
   poller is gone; the numbers are one pure module the gallery's single poll loop reads, which
   makes them testable without a running poller, a fake timer, or a DOM.
   Everything here is an EDGE: the exact millisecond a threshold takes effect, and the fact that
   a tier is announced once on entry rather than on every poll. */

describe("cadenceFor picks the cadence off elapsed wall-clock time", () => {
  test("a fresh task polls at the normal 3s cadence", () => {
    assert.deepEqual(cadenceFor(0), { ms: POLL_MS, tier: "normal" });
    assert.deepEqual(cadenceFor(1), { ms: POLL_MS, tier: "normal" });
  });

  test("19m59s is still normal -- the downshift has not happened yet", () => {
    assert.deepEqual(cadenceFor(SLOW_AT_MS - 1000), { ms: POLL_MS, tier: "normal" });
    assert.deepEqual(cadenceFor(SLOW_AT_MS - 1), { ms: POLL_MS, tier: "normal" });
  });

  test("20m exactly is ALREADY slow -- a threshold is the first instant of its tier", () => {
    assert.deepEqual(cadenceFor(SLOW_AT_MS), { ms: SLOW_MS, tier: "slow" });
    assert.equal(SLOW_AT_MS, 20 * 60 * 1000);
    assert.equal(SLOW_MS, 20 * 1000);
  });

  test("89m59s is still slow", () => {
    assert.deepEqual(cadenceFor(STALE_AT_MS - 1000), { ms: SLOW_MS, tier: "slow" });
    assert.deepEqual(cadenceFor(STALE_AT_MS - 1), { ms: SLOW_MS, tier: "slow" });
  });

  test("90m exactly is stale, at the 3min cadence", () => {
    assert.deepEqual(cadenceFor(STALE_AT_MS), { ms: STALE_MS, tier: "stale" });
    assert.equal(STALE_AT_MS, 90 * 60 * 1000);
    assert.equal(STALE_MS, 3 * 60 * 1000);
  });

  test("6h minus a millisecond is still stale -- still watching", () => {
    assert.deepEqual(cadenceFor(CEILING_MS - 1), { ms: STALE_MS, tier: "stale" });
  });

  test("6h exactly is stalled, and stalled schedules NOTHING", () => {
    const c = cadenceFor(CEILING_MS);
    assert.equal(c.tier, "stalled");
    assert.equal(c.ms, 0,
      "a stalled tier must not carry a cadence -- there is no next poll, and a caller that "
      + "schedules on it anyway would keep asking forever, which is the exact thing the "
      + "ceiling exists to stop");
    assert.equal(cadenceFor(CEILING_MS + 60000).tier, "stalled");
    assert.equal(CEILING_MS, 6 * 60 * 60 * 1000);
  });

  test("garbage elapsed reads as a fresh task, never as stalled", () => {
    // A caller that loses its start time must keep watching a paid render, not abandon it.
    for (const junk of [undefined, null, NaN, "", -5]) {
      assert.equal(cadenceFor(junk).tier, "normal", String(junk) + " must fall back to normal");
    }
  });

  test("the cadence only ever gets slower as a task ages", () => {
    let last = 0;
    for (const e of [0, SLOW_AT_MS - 1, SLOW_AT_MS, STALE_AT_MS - 1, STALE_AT_MS, CEILING_MS - 1]) {
      const c = cadenceFor(e);
      assert.ok(c.ms >= last, "cadence went back UP at " + e + "ms (" + c.ms + " after " + last + ")");
      last = c.ms;
    }
  });
});

/* The poller's half of the contract: notify/jobs.js threads the last tier through its own
   recursion (beside t0) and calls cb("slow"|"stale") only when the tier CHANGES. Replayed here
   against the real table -- one crossing, one announcement, however many polls happen inside
   the tier. */
describe("a tier is announced ONCE, on entry", () => {
  const walk = (elapsedSeries) => {
    const fired = [];
    let tier = "normal";
    for (const e of elapsedSeries) {
      const c = cadenceFor(e);
      if (c.tier !== tier && (c.tier === "slow" || c.tier === "stale")) fired.push(c.tier);
      tier = c.tier;
    }
    return fired;
  };

  test("crossing 20m fires slow exactly once, however many polls follow inside the tier", () => {
    const series = [0, 60000, SLOW_AT_MS - 1, SLOW_AT_MS, SLOW_AT_MS + 20000, SLOW_AT_MS + 40000, SLOW_AT_MS + 60000];
    assert.deepEqual(walk(series), ["slow"]);
  });

  test("crossing both thresholds fires slow then stale, one each", () => {
    const series = [0, SLOW_AT_MS, SLOW_AT_MS + 60000, STALE_AT_MS, STALE_AT_MS + STALE_MS, CEILING_MS - 1];
    assert.deepEqual(walk(series), ["slow", "stale"]);
  });

  test("a tab asleep across both thresholds announces only the tier it woke up in", () => {
    // Backgrounded tabs get their timers throttled; waking at 100m must not replay "slow".
    assert.deepEqual(walk([0, 100 * 60 * 1000]), ["stale"]);
  });

  test("stalled is not one of the announced tiers -- the poller reports it on its own path", () => {
    assert.deepEqual(walk([0, CEILING_MS]), [],
      "the ceiling is a terminal 'stopped watching' report, not a cadence downshift");
  });
});

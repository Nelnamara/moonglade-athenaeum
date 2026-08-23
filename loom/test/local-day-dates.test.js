// gen/dates.js: the viewer's LOCAL calendar day from PixAI's UTC timestamps.
//
// The bug this pins (placard review, 2026-08-22): the server handed the client
// created_at[:10] -- a UTC day -- so an evening (US) generation, which is the NEXT
// day in UTC, showed the wrong date and never matched the Timeline's local
// "Today" band. ~49% of the library was affected.
import { test } from "node:test";
import assert from "node:assert/strict";
import { localDay, localDayTime } from "../../gallery/src/gen/dates.js";

// Pin the timezone for the assertions: the whole point is that the answer depends
// on the viewer's zone, so the test must control it.
function withTZ(tz, fn) {
  const prev = process.env.TZ;
  process.env.TZ = tz;
  try { fn(); } finally { if (prev === undefined) delete process.env.TZ; else process.env.TZ = prev; }
}

test("an evening Pacific generation is the NEXT day in UTC -- localDay returns the LOCAL day", () => {
  // 2026-07-29 23:42 PDT == 2026-07-30T06:42:23.683Z (the artifact's own example)
  withTZ("America/Los_Angeles", () => {
    assert.equal(localDay("2026-07-30T06:42:23.683Z"), "2026-07-29");
  });
  // the naive UTC slice would have said the 30th -- that is the bug
  assert.equal("2026-07-30T06:42:23.683Z".slice(0, 10), "2026-07-30");
});

test("a midday timestamp is the same day everywhere in the US", () => {
  withTZ("America/Los_Angeles", () => {
    assert.equal(localDay("2026-07-25T20:23:00.000Z"), "2026-07-25");
  });
  withTZ("America/New_York", () => {
    assert.equal(localDay("2026-07-25T20:23:00.000Z"), "2026-07-25");
  });
});

test("localDayTime renders the local clock, not UTC", () => {
  withTZ("America/Los_Angeles", () => {
    assert.equal(localDayTime("2026-07-30T06:42:23.683Z"), "2026-07-29 · 23:42");
  });
});

test("empty and non-timestamp inputs fall back safely", () => {
  assert.equal(localDay(""), "");
  assert.equal(localDay(null), "");
  assert.equal(localDay("2026-07-30"), "2026-07-30");       // a bare day passes through
  assert.equal(localDay("not a date"), "not a date");       // garbage is returned, never NaN
  assert.equal(localDayTime(""), "");
});

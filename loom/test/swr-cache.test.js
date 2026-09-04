import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { peek, put, invalidate, _reset } from "../../gallery/src/hooks/swrStore.js";

/* THE CLIENT READ CACHE's store half (2026-09-04). Extracted importless for exactly the
   reason contestSyncFlow.js was: what is worth pinning here is not React's behaviour but
   the STORE's -- what it writes, what it REFUSES to write, and what an invalidation really
   removes -- and every one of those is a plain assertion with no renderer, DOM or fetch.

   The two refusals are the whole safety story of this cache, so they get the most tests:
   an error answer must never become the session's "last known good" (api.js's one rule is
   that a body carrying {error} is the failure answer, HTTP 200 included), and a csrf token
   must never be stored, because it is a moving value and a stale one is a POST the server
   can only refuse. */

beforeEach(() => _reset());

describe("peek / put -- the happy path", () => {
  test("what was put is what comes back", () => {
    const payload = { total_files: 12, by_month: [["2026-01", 4]] };
    assert.equal(put("/api/health", payload), true);
    assert.deepEqual(peek("/api/health"), payload);
  });

  test("a path nobody has written answers null, never undefined", () => {
    assert.equal(peek("/api/health"), null);
    assert.equal(peek(""), null);
    assert.equal(peek(undefined), null);
  });

  test("paths are keyed WHOLE, querystring included", () => {
    // The Publish strip's read is a library page with its own query; two different
    // querystrings are two different answers and must not share a slot.
    put("/api/next/library?page=1&media=image", { items: [1] });
    put("/api/next/library?page=2&media=image", { items: [2] });
    assert.deepEqual(peek("/api/next/library?page=1&media=image").items, [1]);
    assert.deepEqual(peek("/api/next/library?page=2&media=image").items, [2]);
  });

  test("a later put replaces the earlier one rather than merging into it", () => {
    put("/api/your-art", { totals: { count: 3 }, items: ["a"] });
    put("/api/your-art", { totals: { count: 4 } });
    const got = peek("/api/your-art");
    assert.equal(got.totals.count, 4);
    assert.equal("items" in got, false, "a fresh answer is the WHOLE answer");
  });

  test("the identity is stable, which is what lets a seeded useState bail out", () => {
    const payload = { a: 1 };
    put("/api/health", payload);
    assert.equal(peek("/api/health"), peek("/api/health"));
    assert.equal(peek("/api/health"), payload);
  });
});

describe("refusal 1 -- an error answer is NEVER cached", () => {
  test("a body carrying {error} is refused even though it is a plain object", () => {
    assert.equal(put("/api/health", { error: "network error: unreachable" }), false);
    assert.equal(peek("/api/health"), null);
  });

  test("an error answer cannot overwrite a good one that is already stored", () => {
    // The real shape of the bug this prevents: a working session, then one dropped read,
    // and every later reopen serving the failure as 'last known good'.
    put("/api/health", { total_files: 99 });
    put("/api/health", { error: "500 request failed", http_status: 500 });
    assert.equal(peek("/api/health").total_files, 99);
  });

  test("an {error} carrying extras is still an error", () => {
    // api.js returns {error, ...extras} verbatim; the extras must not make it look good.
    assert.equal(put("/api/contests", { error: "board down", contests: [] }), false);
    assert.equal(peek("/api/contests"), null);
  });

  test("a non-object answer is refused -- null, an array, a string, a number", () => {
    for (const bad of [null, undefined, [], ["a"], "ok", 0, 7, true]) {
      assert.equal(put("/api/health", bad), false, String(bad));
    }
    assert.equal(peek("/api/health"), null);
  });

  test("an empty object IS a valid answer (api.js turns a 204 into {})", () => {
    assert.equal(put("/api/panel/schedule", {}), true);
    assert.deepEqual(peek("/api/panel/schedule"), {});
  });

  test("a falsy `error` field does not make an otherwise good answer unstorable", () => {
    assert.equal(put("/api/health", { error: "", total_files: 5 }), true);
    assert.equal(peek("/api/health").total_files, 5);
  });
});

describe("refusal 2 -- a csrf token is NEVER cached", () => {
  test("the token is stripped from what gets stored, the rest survives", () => {
    assert.equal(put("/api/myart/items", { csrf: "T0K3N", items: [{ id: "a" }] }), true);
    const got = peek("/api/myart/items");
    assert.equal("csrf" in got, false, "a stale token is a POST the server can only refuse");
    assert.deepEqual(got.items, [{ id: "a" }]);
  });

  test("stripping does not mutate the caller's own object", () => {
    // The live read's csrf is what the caller POSTs with; taking it out from under them
    // would break the very request the cache exists to speed up.
    const live = { csrf: "T0K3N", items: [] };
    put("/api/myart/items", live);
    assert.equal(live.csrf, "T0K3N");
  });

  test("an answer with no csrf is stored as-is, not copied for nothing", () => {
    const payload = { items: [] };
    put("/api/myart/items", payload);
    assert.equal(peek("/api/myart/items"), payload);
  });
});

describe("invalidate -- prefix semantics", () => {
  const seed = () => {
    put("/api/your-art", { a: 1 });
    put("/api/achievements", { a: 1 });
    put("/api/next/detail/abc", { a: 1 });
    put("/api/next/detail/def", { a: 1 });
    put("/api/next/library?page=1", { a: 1 });
  };

  test("a prefix drops the whole family, and nothing outside it", () => {
    seed();
    assert.equal(invalidate("/api/next/detail/"), 2);
    assert.equal(peek("/api/next/detail/abc"), null);
    assert.equal(peek("/api/next/detail/def"), null);
    assert.notEqual(peek("/api/your-art"), null);
    assert.notEqual(peek("/api/achievements"), null);
  });

  test("an exact path is just a prefix of length one", () => {
    seed();
    assert.equal(invalidate("/api/your-art"), 1);
    assert.equal(peek("/api/your-art"), null);
    assert.notEqual(peek("/api/achievements"), null);
  });

  test("a prefix reaches paths that carry a querystring", () => {
    seed();
    assert.equal(invalidate("/api/next/library"), 1);
    assert.equal(peek("/api/next/library?page=1"), null);
  });

  test("an array invalidates every prefix in it, in one call", () => {
    seed();
    const n = invalidate(["/api/your-art", "/api/achievements", "/api/next/detail/"]);
    assert.equal(n, 4);
    assert.equal(peek("/api/your-art"), null);
    assert.equal(peek("/api/achievements"), null);
    assert.equal(peek("/api/next/detail/abc"), null);
    assert.notEqual(peek("/api/next/library?page=1"), null);
  });

  test("a path counted once even when two prefixes both match it", () => {
    seed();
    assert.equal(invalidate(["/api/next/detail/", "/api/next/detail/abc"]), 2);
  });

  test("a FALSY prefix removes nothing -- a mistyped call must not empty the cache", () => {
    seed();
    for (const bad of ["", null, undefined, [], [""], [null]]) {
      assert.equal(invalidate(bad), 0, JSON.stringify(bad));
    }
    assert.notEqual(peek("/api/your-art"), null);
    assert.notEqual(peek("/api/next/detail/abc"), null);
  });

  test("invalidating something that was never cached is a harmless 0", () => {
    assert.equal(invalidate("/api/nothing-here"), 0);
  });

  test("a purge is a purge -- the next put fills it again", () => {
    put("/api/health", { total_files: 1 });
    invalidate("/api/health");
    assert.equal(peek("/api/health"), null);
    put("/api/health", { total_files: 2 });
    assert.equal(peek("/api/health").total_files, 2);
  });
});

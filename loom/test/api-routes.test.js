import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { LIBRARY, DETAIL_PREFIX, detail, HISTORY } from "../../gallery/src/apiRoutes.js";
import { peek, put, invalidate, _reset } from "../../gallery/src/hooks/swrStore.js";

/* The app's three data routes live in ONE module (gallery/src/apiRoutes.js), and the read
   cache's invalidation runs on the same constants the reads are built from. The cache is
   keyed by request path and invalidated by prefix, so if a read and its invalidation ever
   name the route differently, a write silently stops invalidating its reads. These tests
   build the reads the way the app does and drop them with the prefixes the app passes. */

beforeEach(() => _reset());

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "gallery", "src");
function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(js|jsx|mjs)$/.test(name)) out.push(p);
  }
  return out;
}

describe("the names", () => {
  test("plain names, no pilot codename", () => {
    assert.equal(LIBRARY, "/api/library");
    assert.equal(DETAIL_PREFIX, "/api/detail/");
    assert.equal(HISTORY, "/api/history");
  });

  test("detail(id) is the prefix plus the id, encoded", () => {
    assert.equal(detail("700"), "/api/detail/700");
    assert.equal(detail("a b/c?d"), "/api/detail/a%20b%2Fc%3Fd");
    assert.ok(detail("x").startsWith(DETAIL_PREFIX));
  });
});

describe("a write still invalidates its reads", () => {
  const seed = () => {
    put(detail("abc"), { row: 1 });
    put(detail("def") + "?sort=newest&q=elf", { row: 2 });
    put(LIBRARY + "?page=1&page_size=24&media=image&sort=newest", { items: [1] });
    put(LIBRARY + "?collection=Keepers", { items: [2] });
    put(HISTORY + "?days=7&tz=-420", { days: [] });
    put("/api/your-art", { a: 1 });
  };

  test("DETAIL_PREFIX drops every per-picture read, query strings included, and nothing else", () => {
    seed();
    assert.equal(invalidate([DETAIL_PREFIX]), 2);
    assert.equal(peek(detail("abc")), null);
    assert.equal(peek(detail("def") + "?sort=newest&q=elf"), null);
    assert.notEqual(peek(LIBRARY + "?collection=Keepers"), null);
    assert.notEqual(peek("/api/your-art"), null);
  });

  test("LIBRARY drops every page and filter of the listing, and nothing else", () => {
    seed();
    assert.equal(invalidate([LIBRARY]), 2);
    assert.equal(peek(LIBRARY + "?page=1&page_size=24&media=image&sort=newest"), null);
    assert.equal(peek(LIBRARY + "?collection=Keepers"), null);
    assert.notEqual(peek(detail("abc")), null);
    assert.notEqual(peek(HISTORY + "?days=7&tz=-420"), null);
  });

  test("the one other route under the LIBRARY prefix, /api/library-path, is never cached", () => {
    // invalidate() matches by prefix, so LIBRARY also reaches "/api/library-path" (the old
    // "/api/next/library" could not). That is harmless only while no read of it is stored:
    // the Control Panel reads it with a plain apiGet. Pinned so caching it is a decision.
    const files = walk(SRC);
    assert.ok(files.length > 50, "the walk must see gallery/src");
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      assert.doesNotMatch(text, /(put|peek|useSwrGet)\(\s*"\/api\/library-path/, f);
    }
  });

  test("the app's mutation seam (App.jsx) list clears both families in one call", () => {
    seed();
    const n = invalidate(["/api/your-art", "/api/myart/items", DETAIL_PREFIX,
                          "/api/achievements", "/api/health", LIBRARY]);
    assert.equal(n, 5);
    assert.notEqual(peek(HISTORY + "?days=7&tz=-420"), null, "history is not in that list");
  });

  test("an old-name prefix no longer reaches a read built from the new names", () => {
    seed();
    assert.equal(invalidate(["/api/next/detail/", "/api/next/library"]), 0);
  });
});

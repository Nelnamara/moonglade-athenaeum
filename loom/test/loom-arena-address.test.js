/* THE ARENA'S OWN ADDRESS -- /loom?board=<id> (2026-09-06, owner call 1).

   Two halves, tested the two ways this suite already tests things (see
   loom-mobile-view.test.js's own note): the pure address logic in loom/src/loom-url.js is
   driven directly and asserted on behaviour, and the wiring inside master-storyboard.jsx --
   which has no React render harness here -- is pinned by source structure.

   What must stay true:
     · a named board opens
     · a bare /loom still opens the last one (storyboard:v2:active is the FALLBACK, not gone)
     · an unknown id opens the board you would have got anyway and says so, never blanks
     · the address and the stored pointer can never end up disagreeing
     · the cast hand-off's cleanup cannot erase the board parameter */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { isBoardId, readBoardId, buildLoomUrl } from "../src/loom-url.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("isBoardId -- a URL sanitiser, not a uid() shape check", () => {
  test("accepts what uid() makes", () => {
    assert.equal(isBoardId("k3f9q2z"), true);
    assert.equal(isBoardId("abc123"), true);
    assert.equal(isBoardId("A_b-9"), true);
  });

  test("rejects anything that could escape a path or a query", () => {
    for (const bad of ["a/b", "../x", "a?b", "a&b", "a b", "a<b", "a'b", 'a"b', "a\\b", "a#b"]) {
      assert.equal(isBoardId(bad), false, bad + " must not pass");
    }
  });

  test("rejects empty, null, undefined and the absurdly long", () => {
    assert.equal(isBoardId(""), false);
    assert.equal(isBoardId(null), false);
    assert.equal(isBoardId(undefined), false);
    assert.equal(isBoardId("x".repeat(65)), false);
    assert.equal(isBoardId("x".repeat(64)), true);
  });
});

describe("readBoardId", () => {
  test("reads ?board=", () => {
    assert.equal(readBoardId("?board=k3f9q2z"), "k3f9q2z");
    assert.equal(readBoardId("board=k3f9q2z"), "k3f9q2z");
  });

  test("finds it beside other parameters, in either order", () => {
    assert.equal(readBoardId("?cast=12,34&board=abc"), "abc");
    assert.equal(readBoardId("?board=abc&cast=12,34"), "abc");
  });

  test("absent, empty or junk is null -- the caller falls back, it does not crash", () => {
    assert.equal(readBoardId(""), null);
    assert.equal(readBoardId("?cast=12"), null);
    assert.equal(readBoardId("?board="), null);
    assert.equal(readBoardId("?board=a/b"), null);
    assert.equal(readBoardId(null), null);
    assert.equal(readBoardId(undefined), null);
  });
});

describe("buildLoomUrl -- ONE builder, patching only what it is handed", () => {
  test("sets the board on a bare address", () => {
    assert.equal(buildLoomUrl({ board: "abc" }, "", "/loom"), "/loom?board=abc");
  });

  test("clearing the cast KEEPS the board -- the whole reason this builder exists", () => {
    assert.equal(buildLoomUrl({ cast: null }, "?board=abc&cast=12,34", "/loom"),
      "/loom?board=abc");
  });

  test("setting the board KEEPS an unrelated parameter", () => {
    assert.equal(buildLoomUrl({ board: "zzz" }, "?cast=12", "/loom"), "/loom?cast=12&board=zzz");
  });

  test("a key the patch does not mention is left exactly as it was", () => {
    assert.equal(buildLoomUrl({}, "?board=abc&cast=12", "/loom"), "/loom?board=abc&cast=12");
  });

  test("an unusable board id drops the parameter rather than writing junk into the bar", () => {
    assert.equal(buildLoomUrl({ board: "a/b" }, "?board=abc", "/loom"), "/loom");
    assert.equal(buildLoomUrl({ board: null }, "?board=abc", "/loom"), "/loom");
    assert.equal(buildLoomUrl({ board: "" }, "?board=abc", "/loom"), "/loom");
  });

  test("emptying the query leaves no trailing '?'", () => {
    assert.equal(buildLoomUrl({ cast: null }, "?cast=12", "/loom"), "/loom");
  });

  test("values are encoded, never concatenated", () => {
    // The sanitiser already refuses these, but the builder must not be the weak link either.
    assert.equal(buildLoomUrl({ cast: "12,34" }, "", "/loom"), "/loom?cast=12%2C34");
  });

  test("defaults to /loom when handed no pathname", () => {
    assert.equal(buildLoomUrl({ board: "abc" }, "", ""), "/loom?board=abc");
  });
});

describe("master-storyboard.jsx wires the address in (source structure)", () => {
  test("the boot reads the address before it reads the stored pointer", () => {
    assert.match(src, /const wantedBoard = readBoardId\(location\.search\);/);
    const bootIdx = src.indexOf("const wantedBoard = readBoardId(location.search);");
    assert.ok(bootIdx > 0);
    const boot = src.slice(bootIdx, bootIdx + 1400);
    assert.match(boot, /keys\.includes\(PPRE \+ wantedBoard\)/,
      "a named board must be checked against the store before it is honoured");
  });

  test("a bare /loom still opens the last board -- ACTIVE_KEY survives as the fallback", () => {
    assert.match(src, /const ACTIVE_KEY = "storyboard:v2:active";/);
    const bootIdx = src.indexOf("const wantedBoard = readBoardId(location.search);");
    const boot = src.slice(bootIdx, bootIdx + 1400);
    assert.match(boot, /aid = await sGet\(ACTIVE_KEY\);/,
      "with no usable ?board=, the stored pointer must still decide");
    assert.match(boot, /aid = keys\[0\]\.slice\(PPRE\.length\)/,
      "and a pointer naming nothing must still fall through to a real board");
  });

  test("the address WINS: an honoured ?board= rewrites the stored pointer from it", () => {
    const bootIdx = src.indexOf("const wantedBoard = readBoardId(location.search);");
    const boot = src.slice(bootIdx, bootIdx + 1400);
    assert.match(boot, /if \(aid\) \{\s*\n\s*await sSet\(ACTIVE_KEY, aid\);/,
      "two ideas of which board is open must be collapsed into one at boot");
  });

  test("an unknown board id says so through the app's ordinary corner note -- no new UI", () => {
    assert.match(src, /window\.Toast\.show\(\{\s*\n\s*kind: "err", title: "No storyboard at that address",/);
    // ...and it names the board it opened instead, so the note is useful, not just an alarm.
    assert.match(src, /Opened “" \+ \(p\.name \|\| "Untitled"\) \+ "” instead\./);
  });

  test("the address follows the open board through ONE effect on activeId, via the builder", () => {
    const effIdx = src.indexOf("THE ADDRESS FOLLOWS THE OPEN BOARD");
    assert.ok(effIdx > 0, "expected the address-sync effect");
    const eff = src.slice(effIdx, effIdx + 1400);
    assert.match(eff, /buildLoomUrl\(\{ board: activeId \}, location\.search, location\.pathname\)/);
    assert.match(eff, /history\.replaceState\(null, "", next\)/,
      "switching boards replaces the address, it does not push a history entry");
    assert.match(eff, /\}, \[activeId\]\);/);
  });

  test("the cast hand-off still clears itself -- but through the builder, so ?board= survives", () => {
    assert.match(src, /history\.replaceState\(null, "", buildLoomUrl\(\{ cast: null \}, location\.search, location\.pathname\)\);/);
    assert.doesNotMatch(src, /history\.replaceState\(null, "", location\.pathname\);/,
      "a bare pathname write would erase the board parameter");
  });

  test("the cast hand-off's own reading is untouched", () => {
    // "?cast= stays exactly as shipped" -- read once, sanitised, grammar-checked, then gone.
    assert.match(src, /parseCastIdsFromSearch\(location\.search\)\.filter\(isCatalogMediaId\)/);
    assert.match(src, /if \(!project \|\| castImported\.current\) return;/);
  });

  test("no history write in this file bypasses the builder", () => {
    const writes = src.match(/history\.(replace|push)State\([^)]*\)/g) || [];
    for (const w of writes) {
      assert.match(w, /buildLoomUrl|next/,
        "every Loom history write goes through buildLoomUrl: " + w);
    }
  });
});

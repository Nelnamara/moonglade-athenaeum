/* THE RETURN TRIP REMEMBERS (2026-09-06, owner call 2: "YESSS").

   "← Gallery" went to a bare "/" and threw away the page you were on and the picture you
   had open. It hands back the library's own address now, plus how far down the page you
   were, through a per-tab snapshot the library writes on its way out
   (gallery/src/lib/loomCrossing.js, written by gallery/src/main.jsx's pagehide listener).

   The link's WORDING AND LOOK are deliberately untouched here -- the crossing chrome is the
   Design Handoff's, not this pass's. These tests are about where it lands.

   Behavioural where the logic is pure (the whole of loomCrossing.js), source-structure for
   the wiring in master-storyboard.jsx / main.jsx / App.jsx, the same split this suite uses
   everywhere else. */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  RETURN_KEY, safeLibraryPath, packReturn, unpackReturn,
  rememberLibrary, readLibraryReturn, cameFromLoom,
} from "../../gallery/src/lib/loomCrossing.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rd = (p) => readFileSync(path.resolve(__dirname, "..", p), "utf8");
const loom = rd("master-storyboard.jsx");
const mainJsx = rd("../gallery/src/main.jsx");
const appJsx = rd("../gallery/src/App.jsx");

/* A plain object stands in for sessionStorage -- no DOM needed. */
function fakeStore(seed) {
  const m = new Map(Object.entries(seed || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    _map: m,
  };
}

describe("safeLibraryPath", () => {
  test("passes an ordinary library address, query and all", () => {
    assert.equal(safeLibraryPath("/"), "/");
    assert.equal(safeLibraryPath("/?page=7&image=1234"), "/?page=7&image=1234");
  });

  test("refuses anything that is not a same-site path", () => {
    assert.equal(safeLibraryPath("//evil.example"), null);
    assert.equal(safeLibraryPath("https://evil.example/"), null);
    assert.equal(safeLibraryPath("evil.example"), null);
    assert.equal(safeLibraryPath(""), null);
    assert.equal(safeLibraryPath(null), null);
  });

  test("refuses the control characters _safe_next() refuses, for the same reason", () => {
    assert.equal(safeLibraryPath("/\t/evil.example"), null);
    assert.equal(safeLibraryPath("/a\r\n/b"), null);
    assert.equal(safeLibraryPath("/a\\b"), null);
  });

  test("refuses the Loom itself -- a back link that returns here is a loop, not a return", () => {
    assert.equal(safeLibraryPath("/loom"), null);
    assert.equal(safeLibraryPath("/loom?board=abc"), null);
    assert.equal(safeLibraryPath("/loom/anything"), null);
  });
});

describe("the snapshot round-trips", () => {
  test("page, open picture and scroll all come back", () => {
    const store = fakeStore();
    assert.equal(rememberLibrary("/?page=7&image=1234", 2480, store), true);
    assert.deepEqual(readLibraryReturn(store), { url: "/?page=7&image=1234", scrollY: 2480 });
  });

  test("the key is the one named constant", () => {
    const store = fakeStore();
    rememberLibrary("/?page=2", 10, store);
    assert.ok(store._map.has(RETURN_KEY));
  });

  test("nothing stored answers the library's front door, at the top", () => {
    assert.deepEqual(readLibraryReturn(fakeStore()), { url: "/", scrollY: 0 });
    assert.deepEqual(readLibraryReturn(null), { url: "/", scrollY: 0 });
  });

  test("junk, half-junk and a poisoned url all answer the same honest default", () => {
    assert.deepEqual(unpackReturn("not json"), { url: "/", scrollY: 0 });
    assert.deepEqual(unpackReturn("[]"), { url: "/", scrollY: 0 });
    assert.deepEqual(unpackReturn('{"url":"//evil.example","scrollY":9}'), { url: "/", scrollY: 0 });
    assert.deepEqual(unpackReturn('{"url":"/?page=3","scrollY":"nonsense"}'),
      { url: "/?page=3", scrollY: 0 });
  });

  test("a refused url is never written at all", () => {
    const store = fakeStore();
    assert.equal(rememberLibrary("//evil.example", 10, store), false);
    assert.equal(rememberLibrary("/loom?board=abc", 10, store), false);
    assert.equal(store._map.size, 0);
  });

  test("a negative or absurd scroll offset lands at the top rather than throwing", () => {
    assert.equal(packReturn({ url: "/", scrollY: -50 }), JSON.stringify({ url: "/", scrollY: 0 }));
    assert.equal(packReturn({ url: "/", scrollY: NaN }), JSON.stringify({ url: "/", scrollY: 0 }));
  });

  test("storage that throws (private mode) is a fallback, never a crash", () => {
    const hostile = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
    assert.equal(rememberLibrary("/?page=2", 10, hostile), false);
    assert.deepEqual(readLibraryReturn(hostile), { url: "/", scrollY: 0 });
  });
});

describe("cameFromLoom -- the scroll restore fires on the return trip only", () => {
  test("true when the previous page was the Loom, same origin", () => {
    assert.equal(cameFromLoom("http://localhost:5000/loom?board=abc", "http://localhost:5000"), true);
    assert.equal(cameFromLoom("http://localhost:5000/loom", "http://localhost:5000"), true);
  });

  test("false for an ordinary reload, another page, another origin, or no referrer", () => {
    assert.equal(cameFromLoom("", "http://localhost:5000"), false);
    assert.equal(cameFromLoom("http://localhost:5000/", "http://localhost:5000"), false);
    assert.equal(cameFromLoom("http://localhost:5000/login", "http://localhost:5000"), false);
    assert.equal(cameFromLoom("http://evil.example/loom", "http://localhost:5000"), false);
    assert.equal(cameFromLoom("not a url", "http://localhost:5000"), false);
  });
});

describe("the wiring (source structure)", () => {
  test("the library records where it was on the way out -- ONE listener, every door", () => {
    assert.match(mainJsx, /import \{ rememberLibrary \} from "\.\/lib\/loomCrossing\.js";/);
    assert.match(mainJsx, /window\.addEventListener\("pagehide", \(\) => \{\s*\n\s*rememberLibrary\(window\.location\.pathname \+ window\.location\.search,\s*\n\s*window\.scrollY \|\| 0, window\.sessionStorage\);/);
  });

  test("only the REAL library records -- not /login, not the first-run wizard", () => {
    assert.match(mainJsx, /if \(boot\.authenticated !== false\s*\n\s*&& !\(boot\.needs_key \|\| boot\.catalog_empty \|\| boot\.needs_assets\)\) \{/);
  });

  test("the Loom reads it back once, at module scope, into one constant", () => {
    assert.match(loom, /import \{ readLibraryReturn \} from "\.\.\/gallery\/src\/lib\/loomCrossing\.js";/);
    assert.match(loom, /const GALLERY_HREF = readLibraryReturn\(/);
  });

  test("all three ways out of the Loom use it -- desktop, phone, and the crash screen", () => {
    const backLinks = loom.match(/<a className="l[vm]-(?:close|back)"[^>]*>\s*(?:&larr;|←)[^<]*<\/a>/g) || [];
    assert.equal(backLinks.length, 3,
      "expected exactly three back links (LoomV2, LoomMobile, V2Boundary): " + JSON.stringify(backLinks));
    for (const a of backLinks) {
      assert.match(a, /href=\{GALLERY_HREF\}/, "a back link still hard-codes its destination: " + a);
    }
  });

  test("the link's wording and look are untouched -- that half is the Design Handoff's", () => {
    assert.match(loom, /href=\{GALLERY_HREF\} style=\{\{ textDecoration: "none" \}\}>← Gallery<\/a>/);
    assert.match(loom, /<a className="lm-back" href=\{GALLERY_HREF\}>&larr; Gallery<\/a>/);
    assert.match(loom, /href=\{GALLERY_HREF\} style=\{\{ textDecoration: "none" \}\}>← Back to the gallery<\/a>/);
  });

  test("the scroll is put back only when the referrer is the Loom", () => {
    assert.match(appJsx, /import \{ cameFromLoom, readLibraryReturn \} from "\.\/lib\/loomCrossing\.js";/);
    assert.match(appJsx, /cameFromLoom\(document\.referrer, window\.location\.origin\)\s*\n\s*\? readLibraryReturn\(window\.sessionStorage\)\.scrollY : 0\)/);
  });

  test("and it yields the instant the owner's own hands arrive (the library stands still)", () => {
    const idx = appJsx.indexOf("THE SAME PROMISE, ACROSS THE CROSSING");
    assert.ok(idx > 0, "expected the return-scroll block");
    const blk = appJsx.slice(idx, idx + 2600);
    for (const ev of ["wheel", "touchstart", "keydown"]) {
      assert.ok(blk.includes('addEventListener("' + ev + '", stop'),
        "expected " + ev + " to cancel the restore");
    }
    assert.match(blk, /if \(stopped\) return;/);
    assert.match(blk, /\+\+frames < 30/, "the retry must be capped, not open-ended");
  });
});

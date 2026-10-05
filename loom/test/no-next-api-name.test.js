import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The pilot codename stays out of the front-end source (the follow-up to #51).

   /next was the React app's codename through its pilot. #51 retired the page route; the three
   data routes followed: /api/library, /api/detail/<media_id>, /api/history. Their old
   /api/next/... paths answered for one release (3.17.0), as aliases on the server, and are gone
   now (tests/test_api_route_aliases.py). Nothing in the source may read them, or it breaks
   against the server: every read goes through gallery/src/apiRoutes.js, the one file allowed to
   name the old paths (to say they are gone).

   The Loom is in scope too: its bundle pulls the library read in through gallery/src/api.js
   (GalleryPicker), and its own source is loom/src plus loom/master-storyboard.jsx. */

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(here, "..", "..");
const ALLOWED = path.join(REPO, "gallery", "src", "apiRoutes.js");

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(js|jsx|mjs|cjs|ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}

const FILES = [
  ...walk(path.join(REPO, "gallery", "src")),
  ...walk(path.join(REPO, "loom", "src")),
  path.join(REPO, "loom", "master-storyboard.jsx"),
];

test("the walk sees the front end, the routes module included (so the guard is not vacuous)", () => {
  assert.ok(FILES.length > 100, "found only " + FILES.length + " files");
  assert.ok(FILES.includes(ALLOWED), "gallery/src/apiRoutes.js is missing");
  assert.ok(existsSync(path.join(REPO, "loom", "master-storyboard.jsx")));
});

test('no "/api/next" outside gallery/src/apiRoutes.js -- code or comment', () => {
  const hits = [];
  for (const f of FILES) {
    if (f === ALLOWED) continue;
    readFileSync(f, "utf8").split(/\r?\n/).forEach((line, i) => {
      if (line.includes("/api/next")) hits.push(path.relative(REPO, f) + ":" + (i + 1) + "  " + line.trim());
    });
  }
  assert.deepEqual(hits, [], "read the routes from gallery/src/apiRoutes.js instead:\n" + hits.join("\n"));
});

test("apiRoutes.js builds every route from the plain names", () => {
  const text = readFileSync(ALLOWED, "utf8");
  const code = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
  assert.doesNotMatch(code, /\/api\/next/, "the old names may appear in its comment, never in its code");
  for (const name of ["LIBRARY", "DETAIL_PREFIX", "detail", "HISTORY"]) {
    assert.match(code, new RegExp("export (const|function) " + name + "\\b"), name);
  }
});

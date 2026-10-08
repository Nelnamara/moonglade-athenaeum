import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The Folio's ladder headers say what each track counts in plain words (owner walk 2026-09-29:
   one read "THE MOONFORGE — MEASURED IN LOCAL_GENS"). The words are the server's (metric_words on
   each track, held to a full table by dev/tests/test_achievements.py); what is pinned here is that
   the desktop header draws those words and never the raw metric key, and that its fallback for
   an older server spaces the underscores out. The component is React and this suite has no
   renderer, so the header is checked at the source, and the fallback is run for real. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
const code = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const desk = code(src("components/FolioOverlay.jsx"));
const phone = code(src("components/FolioMobile.jsx"));

test("the ladder header draws the plain words, never the metric key", () => {
  assert.match(desk, /\{l\.name\} — measured in \{metricWords\(l\)\}/);
  assert.doesNotMatch(desk, /measured in \{l\.metric\}/);
  assert.doesNotMatch(phone, /measured in \{l\.metric\}/);
});

test("the words come from the server's metric_words, keyed by track", () => {
  assert.match(desk, /\(\(data && data\.ladders\) \|\| \[\]\)\.forEach\(\(t\) => \{ if \(t && t\.id\) trackWords\[t\.id\] = t\.metric_words; \}\);/);
});

test("no header shows an underscore, whether the server sent words or not", () => {
  const m = desk.match(/const metricWords = (\(l\) => [^;]+);/);
  assert.ok(m, "metricWords is defined in FolioOverlay.jsx");
  const make = new Function("trackWords", "return " + m[1] + ";");
  const withWords = make({ forge: "pictures made in the app" });
  assert.equal(withWords({ id: "forge", metric: "local_gens" }), "pictures made in the app");
  const older = make({});                                           // an older server: no words
  for (const metric of ["local_gens", "distinct_active_days", "jobs_concurrent", "images", "", undefined]) {
    const shown = older({ id: "x", metric });
    assert.ok(!shown.includes("_"), JSON.stringify(metric) + " -> " + shown);
  }
  assert.equal(older({ id: "x", metric: "local_gens" }), "local gens");
});

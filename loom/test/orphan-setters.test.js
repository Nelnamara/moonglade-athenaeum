/* Every setter App.jsx calls must be one it declared. The 2026-09-07 batch-stack rename
   (seriesFor -> stackFor) left two setSeriesFor(null) calls behind -- in showSimilar and
   goLibrary -- and nothing caught it until the render harness clicked the Similar door and
   the page threw "setSeriesFor is not defined". esbuild parses undefined identifiers happily;
   this test does not. It reads App.jsx and AppMobile.jsx, collects every useState setter they
   declare, and fails on any setXxx( call that names a setter neither file declares nor imports. */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const FILES = ["App.jsx", path.join("components", "AppMobile.jsx")].map(f => path.join(here, "..", "..", "gallery", "src", f));

function declaredSetters(src) {
  const out = new Set();
  // const [x, setX] = useState(...)   and   const [x, setX] = useReducer(...)
  for (const m of src.matchAll(/\[\s*\w+\s*,\s*(set[A-Z]\w*)\s*\]\s*=\s*use(?:State|Reducer)\b/g)) out.add(m[1]);
  // function setX( / const setX = / setX: from a destructured hook or prop
  for (const m of src.matchAll(/\b(?:function\s+|const\s+|let\s+)(set[A-Z]\w*)\b/g)) out.add(m[1]);
  for (const m of src.matchAll(/[{,]\s*(set[A-Z]\w*)\s*[,}:]/g)) out.add(m[1]);
  for (const m of src.matchAll(/import\s*\{([^}]*)\}/g)) for (const n of m[1].split(",")) { const t = n.trim().split(/\s+as\s+/).pop(); if (/^set[A-Z]/.test(t)) out.add(t); }
  return out;
}

describe("no orphan setters", () => {
  for (const file of FILES) {
    test(path.basename(file) + " calls only setters it declares", () => {
      const src = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
      const declared = declaredSetters(src);
      const called = new Set([...src.matchAll(/\b(set[A-Z]\w*)\s*\(/g)].map(m => m[1]));
      // DOM/JS builtins that look like setters
      for (const b of ["setTimeout", "setInterval", "setAttribute", "setItem", "setProperty", "setRequestHeader", "setPointerCapture", "setSelectionRange", "setState", "setDate", "setHours", "setMinutes", "setSeconds", "setMilliseconds", "setFullYear", "setMonth", "setTime", "setUTCHours", "setPrototypeOf"]) called.delete(b);
      const orphans = [...called].filter(n => !declared.has(n)).sort();
      assert.deepEqual(orphans, [], "setters called but never declared: " + orphans.join(", "));
    });
  }
});

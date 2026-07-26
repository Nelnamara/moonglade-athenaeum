import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// AUDIT_2026-07-21 follow-up: `resolveGenDims` was CALLED in master-storyboard.jsx (the
// Advanced panel's "-> W x H" readout) but never appeared in its import list from
// ./src/loom-mutations.js. The two delivery paths disagree about whether that matters:
//
//   /loom            -> pixai_gallery.py inlines every module into ONE global scope and hands
//                       it to in-browser Babel, so a missing import still resolves. Silent.
//   /loom?bundle=1   -> esbuild builds a REAL module graph. The module's own function got
//                       renamed to `resolveGenDims2` and the call site was left as a free
//                       global, so the bundle threw `ReferenceError: resolveGenDims is not
//                       defined` and the tab body never rendered.
//
// The committed bundle is served verbatim and CI rebuilds + staleness-checks it on every
// push, so this is broken code the project actively maintains. A single-identifier assertion
// would only pin the one instance; this checks the whole class -- every export of either
// pure module that the JSX actually calls is either imported (directly or aliased) or
// deliberately shadowed by a local wrapper of the same name.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(__dirname, "..", p), "utf8");
const jsx = read("master-storyboard.jsx");
// Comment LINES are dropped wholesale rather than by stripping `//` mid-line: prose
// comments in this file contain both commas (which would corrupt the import-list split) and
// helper names written as `someHelper()` (which would look like real call sites). Dropping
// whole lines keeps every real statement intact -- a URL or regex containing `//` inside a
// code line is never touched.
const COMMENT_LINE = /^\s*(?:\/\/|\{?\/\*|\*)/;
const code = jsx.split("\n").filter((l) => !COMMENT_LINE.test(l)).join("\n");

const MODULES = ["loom-core", "loom-mutations"];

/** Names bound in this file by `import { a, b as c } from "./src/<mod>.js"`. */
function importedNames() {
  const names = new Set();
  for (const mod of MODULES) {
    const re = new RegExp('import\\s*\\{([^}]*)\\}\\s*from\\s*"\\./src/' + mod + '\\.js"', "s");
    const m = code.match(re);
    assert.ok(m, `master-storyboard.jsx must import from ./src/${mod}.js`);
    for (let part of m[1].split(",")) {
      part = part.trim();
      if (!part) continue;
      names.add(part.includes(" as ") ? part.split(" as ")[1].trim() : part);
    }
  }
  return names;
}

/** `export function|const|class NAME` in a pure module. */
function exportedNames(mod) {
  const out = [];
  for (const m of read(`src/${mod}.js`).matchAll(/^export (?:function|const|class)\s+(\w+)/gm)) {
    out.push(m[1]);
  }
  return out;
}

const calledInJsx = (name) => new RegExp("(?<![\\w.$])" + name + "\\s*\\(").test(code);
const definedLocally = (name) =>
  new RegExp("(?:^|\\n)\\s*(?:function|const|let|var)\\s+" + name + "\\b").test(code);

describe("master-storyboard.jsx imports every pure-module helper it calls (esbuild vs Babel scope)", () => {
  test("no called helper is left as a free global reference", () => {
    const imported = importedNames();
    const missing = [];
    for (const mod of MODULES) {
      for (const name of exportedNames(mod)) {
        if (imported.has(name) || !calledInJsx(name)) continue;
        // A local wrapper of the same name is legitimate and intentional here -- e.g.
        // `shotPayload` (imported as buildShotPayload, re-wrapped to close over imgSrc) and
        // `moveCardToAct` (imported as mvCardToAct, wrapped with setProject).
        if (definedLocally(name)) continue;
        missing.push(`${name} (src/${mod}.js)`);
      }
    }
    assert.deepEqual(missing, [],
      "these are called in master-storyboard.jsx but neither imported nor defined locally -- " +
      "they resolve under the in-browser Babel path (one shared global scope) and throw " +
      "ReferenceError in the esbuild bundle (/loom?bundle=1): " + missing.join(", "));
  });

  test("resolveGenDims specifically is imported (the instance that shipped broken)", () => {
    assert.ok(importedNames().has("resolveGenDims"),
      "the Advanced panel's dimension readout calls resolveGenDims(imgAdv); without the " +
      "import the esbuild bundle throws before the tab body renders");
  });
});

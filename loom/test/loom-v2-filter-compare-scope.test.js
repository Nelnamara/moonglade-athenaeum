import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard: desktop Filter compare's Save and "No filter" threw
// `ReferenceError: patch is not defined`. LoomV2's fcClear/fcSave called `patch(...)`, but the
// only `patch` in LoomV2 was declared inside the later block-scoped `let gen; { ... }` section,
// invisible to them. esbuild does not flag an undeclared identifier (it assumes a global), so
// the bundle built clean and the bug only showed on click; it was found with a @babel/parser
// scope walk. The fix declares `patch` at LoomV2's own scope, above these handlers.
//
// Plain source-text check, like the other LoomV2 tests (no JSX render harness in this runner,
// see loom-v2-dead-generate-shot-prop.test.js). "In scope" is read off the file's own layout:
// a name the handlers use must be imported or declared at column 0 (module scope), be one of
// LoomV2's destructured props, or be declared at LoomV2's two-space body indentation BEFORE the
// handler. A declaration nested deeper (the old `patch`, four spaces in inside `{ ... }`) or
// after the handler does not count. The last describe block runs the checker against the
// pre-fix shape, so the guard is proven able to fire.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

const IDENT = "[A-Za-z_$][\\w$]*";
const KEYWORDS = new Set([
  "async", "await", "break", "case", "catch", "class", "const", "continue", "default", "delete",
  "do", "else", "extends", "false", "finally", "for", "function", "if", "in", "instanceof", "let",
  "new", "null", "of", "return", "super", "switch", "this", "throw", "true", "try", "typeof",
  "undefined", "var", "void", "while", "yield",
]);
// Language/runtime globals a handler may use without declaring (Math, JSON, setTimeout, ...),
// plus the browser ones node does not have.
const GLOBALS = new Set(Object.getOwnPropertyNames(globalThis).concat(
  ["window", "document", "navigator", "localStorage", "sessionStorage", "requestAnimationFrame", "cancelAnimationFrame"]));

// Comments dropped, string/template contents blanked, so braces and words inside them count
// for nothing. (A name used only inside a template `${}` is missed: a false pass, never a
// false failure.)
function codeOnly(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\n]*/g, " ")
    .replace(/"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/g, '""');
}

// Names bound by a declaration list such as `[a, setA]`, `{ a, b: c, d = 1 }` or `a, b = 2`.
function boundNames(list) {
  return codeOnly(list).split(",").map((part) => {
    const p = part.replace(/=[\s\S]*$/, "").trim();   // drop a default value
    const renamed = p.match(new RegExp(`:\\s*(${IDENT})$`));   // `{ key: local }` binds local
    const m = renamed || p.replace(/^\.\.\./, "").match(new RegExp(`^(${IDENT})$`));
    return m ? m[1] : null;
  }).filter(Boolean);
}

function moduleScopeNames(src) {
  const names = new Set();
  for (const m of src.matchAll(/^import\s+([\s\S]*?)\s+from\s+["']/gm)) {
    const clause = m[1];
    const named = clause.match(/\{([\s\S]*)\}/);
    if (named) named[1].split(",").forEach((s) => { const w = s.trim().split(/\s+as\s+/).pop(); if (w) names.add(w); });
    const rest = clause.replace(/\{[\s\S]*\}/, "");
    for (const w of rest.matchAll(new RegExp(`(?:\\*\\s*as\\s+)?(${IDENT})`, "g"))) if (w[1] !== "as") names.add(w[1]);
  }
  for (const m of src.matchAll(new RegExp(`^(?:export\\s+(?:default\\s+)?)?(?:async\\s+)?(?:function\\s*\\*?|class|const|let|var)\\s+(${IDENT})`, "gm"))) names.add(m[1]);
  for (const m of src.matchAll(/^(?:export\s+)?(?:const|let|var)\s+(\[[^\]]*\]|\{[^}]*\})/gm)) boundNames(m[1].slice(1, -1)).forEach((n) => names.add(n));
  return names;
}

function loomV2Source(src) {
  const start = src.indexOf("function LoomV2({");
  assert.ok(start >= 0, "expected to find LoomV2's function signature");
  const end = src.indexOf("\nfunction ", start + 1);
  return end < 0 ? src.slice(start) : src.slice(start, end);
}

function loomV2Props(v2) {
  const sig = v2.match(/^function LoomV2\(\{([\s\S]*?)\}\)\s*\{/);
  assert.ok(sig, "expected LoomV2's destructured-props signature");
  return new Set(boundNames(sig[1]));
}

// Names declared at LoomV2's own scope (two-space indent) in `text`.
function loomV2ScopeNames(text) {
  const names = new Set();
  for (const m of text.matchAll(new RegExp(`^  (?:const|let|var)\\s+(${IDENT})`, "gm"))) names.add(m[1]);
  for (const m of text.matchAll(/^  (?:const|let|var)\s+(\[[^\]]*\]|\{[^}]*\})/gm)) boundNames(m[1].slice(1, -1)).forEach((n) => names.add(n));
  for (const m of text.matchAll(new RegExp(`^  (?:async\\s+)?function\\s*\\*?\\s*(${IDENT})`, "gm"))) names.add(m[1]);
  return names;
}

// Where `const <name> = ...` starts at LoomV2's scope, and its full text through the closing
// `}` of an arrow's block body (or the `;` of an expression body).
function handlerAt(v2, name) {
  const start = v2.search(new RegExp(`\\n  const ${name} = `));
  assert.ok(start >= 0, `expected \`const ${name} = \` at LoomV2's two-space scope -- if LoomV2's body ` +
    "indentation changed, this test's notion of 'LoomV2 scope' needs updating with it");
  const code = codeOnly(v2.slice(start));
  const arrow = code.indexOf("=>");
  assert.ok(arrow > 0, `expected ${name} to be an arrow function`);
  const bodyStart = code.slice(arrow + 2).search(/\S/) + arrow + 2;
  if (code[bodyStart] !== "{") return { start, text: code.slice(0, code.indexOf(";", bodyStart) + 1) };
  let depth = 0;
  for (let i = bodyStart; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}" && --depth === 0) return { start, text: code.slice(0, i + 1) };
  }
  assert.fail(`unbalanced braces reading ${name}'s body`);
}

// Identifiers a handler reads from outside itself: not a property (`a.b`), not an object key
// (`{ filter: ... }`), not a keyword/global, and not bound inside the handler (arrow params,
// local declarations).
function freeNames(handlerText) {
  const body = handlerText.slice(handlerText.indexOf("=>") + 2).replace(/\.\.\./g, " ");
  const local = new Set();
  for (const m of body.matchAll(/\(([^()]*)\)\s*=>/g)) boundNames(m[1].replace(/^\s*[\[{]|[\]}]\s*$/g, "")).forEach((n) => local.add(n));
  for (const m of body.matchAll(new RegExp(`(${IDENT})\\s*=>`, "g"))) local.add(m[1]);
  for (const m of body.matchAll(new RegExp(`\\b(?:const|let|var)\\s+(${IDENT})`, "g"))) local.add(m[1]);
  for (const m of body.matchAll(/\b(?:const|let|var)\s+(\[[^\]]*\]|\{[^}]*\})/g)) boundNames(m[1].slice(1, -1)).forEach((n) => local.add(n));
  const free = new Set();
  for (const m of body.matchAll(new RegExp(`(?<![\\w$.])(${IDENT})`, "g"))) {
    const n = m[1];
    const before = body.slice(0, m.index);
    const after = body.slice(m.index + n.length);
    if (/[{,]\s*$/.test(before) && /^\s*:/.test(after)) continue;   // object key
    if (KEYWORDS.has(n) || GLOBALS.has(n) || local.has(n)) continue;
    free.add(n);
  }
  return [...free];
}

// The names `handlerName` uses that are NOT in scope and declared before it in LoomV2.
function undeclaredIn(fileSrc, handlerName) {
  const v2 = loomV2Source(fileSrc);
  const { start, text } = handlerAt(v2, handlerName);
  const visible = new Set([...moduleScopeNames(fileSrc), ...loomV2Props(v2), ...loomV2ScopeNames(v2.slice(0, start))]);
  const free = freeNames(text);
  assert.ok(free.length > 0, `read no names at all out of ${handlerName} -- the extractor is broken, not the handler`);
  return free.filter((n) => !visible.has(n));
}

describe("LoomV2's Filter compare handlers only use names in scope", () => {
  for (const handler of ["fcClear", "fcSave"]) {
    test(`${handler} references nothing undeclared at that point in LoomV2`, () => {
      assert.deepEqual(undeclaredIn(storyboardSrc, handler), [],
        `${handler} uses a name that is not declared at LoomV2's scope above it -- clicking it ` +
        "throws a ReferenceError at runtime (esbuild does not flag this)");
    });
  }

  test("the writer they use is LoomV2's own selected-shot-or-draft `patch`", () => {
    const v2 = loomV2Source(storyboardSrc);
    const decl = "\n  const patch = (fn) => { if (sel) setCard(sel.a.id, sel.c.id, fn); else setDraftCard(fn); };";
    assert.ok(v2.includes(decl), "expected `patch` declared at LoomV2's own scope, writing the selected shot or the draft card");
    assert.ok(v2.indexOf(decl) < v2.indexOf("\n  const fcClear = "), "`patch` must be declared above fcClear/fcSave");
    assert.match(handlerAt(v2, "fcClear").text, /\bpatch\(\(cc\) => \(\{ \.\.\.cc, filter: null \}\)\)/);
    assert.match(handlerAt(v2, "fcSave").text, /\bpatch\(\(cc\) => \(\{ \.\.\.cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle \}\)\)/);
  });
});

describe("the scope check can actually fire", () => {
  const shape = (patchDecl, where) => [
    'import { useState } from "react";',
    "function LoomV2({ sel, setCard, setDraftCard }) {",
    "  const [fcActive, setFcActive] = useState(null);",
    where === "before" ? patchDecl : "",
    "  const fcClear = () => { setFcActive(null); patch((cc) => ({ ...cc, filter: null })); };",
    "  let gen;",
    "  {",
    where === "nested" ? "  " + patchDecl : "",
    "  }",
    where === "after" ? patchDecl : "",
    "}",
    "function LoomMobile() {",
    "  const patch = 1;",
    "}",
  ].join("\n");
  const decl = "  const patch = (fn) => { if (sel) setCard(sel.a.id, sel.c.id, fn); else setDraftCard(fn); };";

  test("flags `patch` declared only inside the later `let gen; { ... }` block (the pre-fix shape)", () => {
    assert.deepEqual(undeclaredIn(shape(decl, "nested"), "fcClear"), ["patch"]);
  });

  test("flags `patch` declared at LoomV2 scope but after the handler", () => {
    assert.deepEqual(undeclaredIn(shape(decl, "after"), "fcClear"), ["patch"]);
  });

  test("passes once `patch` is declared at LoomV2 scope above the handler", () => {
    assert.deepEqual(undeclaredIn(shape(decl, "before"), "fcClear"), []);
  });
});

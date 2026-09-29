import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* NEVER AUTO-RENDER (Session P -- BUILD-w5-p §4, review F20; NOTES P2 "Never auto-render").

   The invariant: a render request -- anything that reaches /api/loom/generate, /api/generate,
   /api/edit, /api/fix, the image run road or the drawer's Go -- happens only from a deliberate
   click. Re-anchor, Keep, ★ select, delete a take, Reuse settings, importing, duplicating,
   opening or switching boards, the resume, Play and the local cut can NOT reach one.

   How it is checked, on the source text (there is no React harness in this runner):
     1. A TOKENIZER (below) reads master-storyboard.jsx as JavaScript + JSX at the lexical level
        -- comments, strings, template literals, regex literals, JSX text -- and extracts every
        NAMED function (`const X = (…) =>`, `const X = async (…) =>`, `const X = useCallback(…)`,
        `function X(`) with its brace-matched extent.
     2. THE WALK: from each ROOT, every identifier in its body that names another extracted
        function is followed, transitively. Any SINK reached fails the test with the path
        (reanchorShot → X → generateShot). Name collisions merge (two `tick`s are both followed),
        which can only make a path easier to find: the walk errs toward failing.
     3. NEGATIVE CONTROLS: the same walker on a synthetic source whose root calls a helper that
        calls generateShot must fail -- so the real run cannot pass vacuously.
     4. THE CALLER ALLOWLIST (review F20): the walk only proves the NAMED roots are clean. An
        anonymous effect, or a sink passed as a prop to a child that calls it on mount, would get
        past it. So every reference to every sink identifier is classified (its definition, a
        call inside a named function, a component's parameter, a JSX prop, a pass-down to a
        child) and the set must equal the allowlist below EXACTLY; no sink may appear inside a
        useEffect / useLayoutEffect callback; and a sink in a JSX prop is only ever an onClick or
        a bare pass-down to a child component whose own uses are pinned here too.
     5. PLACEMENT PINS, PURE MODULES and the DRAWER HOST API (the same walker on VideoDrawer.jsx).
   The server half is tests/test_loom_generate_guard.py (the handoff and the new routes never
   reach core.submit). */

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(here, "..", p), "utf8").replace(/\r\n/g, "\n");
const SRC = read("master-storyboard.jsx");
const DRAWER_SRC = read("../gallery/src/components/VideoDrawer.jsx");

/* ======================================================================================
   THE TOKENIZER
   scan(src) returns
     code     the source with every comment, every string / template / regex body and every
              piece of JSX text blanked to spaces (newlines kept: offsets and lines still match)
     strings  every string literal, template chunk, regex body and JSX attribute string:
              {start, end, value, regex?}
     tags     every JSX opening tag: {start, end, name, attrs:[{name, nameAt, exprStart?,
              exprEnd?, str?}]}
   JSX text is why a regex over the file is not enough: the apostrophe in <span>hasn't</span>
   is text, not a string opener, and a naive scan would swallow the braces after it.
   ====================================================================================== */
function scan(src) {
  const n = src.length;
  const out = src.split("");
  const strings = [], tags = [];
  const blank = (a, b) => { for (let k = a; k < b && k < n; k++) if (out[k] !== "\n") out[k] = " "; };
  const idStart = (ch) => /[A-Za-z_$]/.test(ch || "");
  const idPart = (ch) => /[\w$]/.test(ch || "");
  const WS = /\s/;
  // After these keywords an expression starts, so "/" opens a regex and "<" a JSX element.
  const EXPR_KW = new Set(["return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void",
    "throw", "instanceof", "yield", "await", "default", "export"]);
  const exprStart = (prev) => {
    if (!prev) return true;
    if (prev.t === "num" || prev.t === "val") return false;
    if (prev.t === "id") return EXPR_KW.has(prev.v);
    return !(prev.v === ")" || prev.v === "]");
  };
  function quoted(i, q, jsxAttr) {
    let j = i + 1;
    while (j < n && src[j] !== q) {
      if (!jsxAttr && src[j] === "\\") { j += 2; continue; }
      if (!jsxAttr && src[j] === "\n") break;
      j++;
    }
    strings.push({ start: i, end: Math.min(j + 1, n), value: src.slice(i + 1, j) });
    blank(i + 1, j);
    return src[j] === q ? j + 1 : j;
  }
  function template(i) {
    let j = i + 1, chunk = j;
    const flush = (to) => { strings.push({ start: chunk, end: to, value: src.slice(chunk, to) }); blank(chunk, to); };
    while (j < n) {
      const c = src[j];
      if (c === "\\") { j += 2; continue; }
      if (c === "`") { flush(j); return j + 1; }
      if (c === "$" && src[j + 1] === "{") { flush(j); j = js(j + 2, true) + 1; chunk = j; continue; }
      j++;
    }
    return j;
  }
  function regex(i) {
    let j = i + 1, inClass = false;
    while (j < n) {
      const c = src[j];
      if (c === "\\") { j += 2; continue; }
      if (c === "\n") break;
      if (inClass) { if (c === "]") inClass = false; } else if (c === "[") inClass = true; else if (c === "/") break;
      j++;
    }
    strings.push({ start: i, end: j + 1, value: src.slice(i + 1, j), regex: true });
    blank(i + 1, j);
    j++;
    while (j < n && /[a-z]/i.test(src[j])) j++;
    return j;
  }
  function jsxChildren(j) {
    while (j < n) {
      const c = src[j];
      if (c === "<" && src[j + 1] === "/") { const e = src.indexOf(">", j); return e < 0 ? n : e + 1; }
      if (c === "<") { j = jsxElement(j); continue; }
      if (c === "{") { j = js(j + 1, true) + 1; continue; }
      if (c !== "\n") out[j] = " ";
      j++;
    }
    return j;
  }
  function jsxElement(i) {
    let j = i + 1;
    if (src[j] === ">") return jsxChildren(j + 1);                 // <> fragment </>
    let k = j;
    while (k < n && /[\w$.:-]/.test(src[k])) k++;
    const tag = { start: i, end: -1, name: src.slice(j, k), attrs: [] };
    tags.push(tag);
    j = k;
    while (j < n) {
      const c = src[j];
      if (WS.test(c)) { j++; continue; }
      if (c === "/" && src[j + 1] === ">") { tag.end = j + 2; return j + 2; }
      if (c === ">") { tag.end = j + 1; return jsxChildren(j + 1); }
      if (c === "{") { const e = js(j + 1, true); tag.attrs.push({ name: "...", nameAt: j, exprStart: j + 1, exprEnd: e }); j = e + 1; continue; }
      if (idStart(c)) {
        let a = j;
        while (a < n && /[\w$:-]/.test(src[a])) a++;
        const attr = { name: src.slice(j, a), nameAt: j };
        tag.attrs.push(attr);
        j = a;
        while (j < n && WS.test(src[j])) j++;
        if (src[j] !== "=") continue;
        j++;
        while (j < n && WS.test(src[j])) j++;
        if (src[j] === '"' || src[j] === "'") {
          const s = strings.length;
          j = quoted(j, src[j], true);
          attr.str = strings[s].value;
        } else if (src[j] === "{") {
          const e = js(j + 1, true);
          attr.exprStart = j + 1; attr.exprEnd = e;
          j = e + 1;
        } else if (src[j] === "<") {
          j = jsxElement(j);
        }
        continue;
      }
      j++;
    }
    return j;
  }
  // JavaScript until EOF -- or, with stopAtBrace, until the "}" closing the container it is in
  // (a template's ${…}, a JSX attribute or child {…}).
  function js(i, stopAtBrace) {
    let depth = 0, prev = null;
    while (i < n) {
      const c = src[i], nx = src[i + 1];
      if (WS.test(c)) { i++; continue; }
      if (c === "/" && nx === "/") { const e = src.indexOf("\n", i); const end = e < 0 ? n : e; blank(i, end); i = end; continue; }
      if (c === "/" && nx === "*") { const e = src.indexOf("*/", i + 2); const end = e < 0 ? n : e + 2; blank(i, end); i = end; continue; }
      if (c === '"' || c === "'") { i = quoted(i, c, false); prev = { t: "val" }; continue; }
      if (c === "`") { i = template(i); prev = { t: "val" }; continue; }
      if (c === "/" && exprStart(prev)) { i = regex(i); prev = { t: "val" }; continue; }
      if (c === "<" && exprStart(prev) && /[A-Za-z>]/.test(nx || "")) { i = jsxElement(i); prev = { t: "val" }; continue; }
      if (c === "{") { depth++; prev = { t: "p", v: c }; i++; continue; }
      if (c === "}") {
        if (stopAtBrace && depth === 0) return i;
        depth--; prev = { t: "p", v: c }; i++; continue;
      }
      if (idStart(c)) { let j = i + 1; while (j < n && idPart(src[j])) j++; prev = { t: "id", v: src.slice(i, j) }; i = j; continue; }
      if (/[0-9]/.test(c)) { let j = i + 1; while (j < n && /[\w.]/.test(src[j])) j++; prev = { t: "num" }; i = j; continue; }
      prev = { t: "p", v: c }; i++;
    }
    return i;
  }
  js(0, false);
  return { src, code: out.join(""), strings, tags };
}

/* ---- named functions, with their extents ---- */
const matchClose = (code, open) => {
  const pairs = { "(": ")", "[": "]", "{": "}" };
  const stack = [];
  for (let k = open; k < code.length; k++) {
    const ch = code[k];
    if (pairs[ch]) stack.push(pairs[ch]);
    else if (ch === ")" || ch === "]" || ch === "}") {
      if (stack.pop() !== ch) return -1;
      if (!stack.length) return k;
    }
  }
  return -1;
};
// An expression-bodied arrow runs to the end of its statement.
const exprEnd = (code, from) => {
  let depth = 0;
  for (let k = from; k < code.length; k++) {
    const ch = code[k];
    if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") { if (depth === 0) return k; depth--; }
    else if (depth === 0 && (ch === ";" || ch === ",")) return k;
    else if (depth === 0 && ch === "\n"
      && /^\s*(const|let|var|function|return|if|for|while|export|import)\b/.test(code.slice(k + 1, k + 40))) return k;
  }
  return code.length;
};
function namedFunctions(code) {
  const defs = [];
  const add = (d) => { if (d.end > d.start) defs.push(d); };
  const nameIn = (m, name, after) => m.index + m[0].indexOf(name, after);
  const arrow = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)|[A-Za-z_$][\w$]*)\s*=>\s*/g;
  for (let m; (m = arrow.exec(code));) {
    const at = m.index + m[0].length;
    const pAt = m.index + m[0].indexOf(m[2], m[0].indexOf("="));
    add({ name: m[1], start: m.index, nameAt: nameIn(m, m[1], m[0].indexOf(" ")),
      params: [pAt, pAt + m[2].length], end: code[at] === "{" ? matchClose(code, at) + 1 : exprEnd(code, at) });
  }
  const cb = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:React\.)?useCallback\s*\(/g;
  for (let m; (m = cb.exec(code));) {
    const open = m.index + m[0].length - 1;
    add({ name: m[1], start: m.index, nameAt: nameIn(m, m[1], m[0].indexOf(" ")), params: [open, open], end: matchClose(code, open) + 1 });
  }
  const fn = /\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g;
  for (let m; (m = fn.exec(code));) {
    const open = m.index + m[0].length - 1;
    const pe = matchClose(code, open);
    const bo = pe < 0 ? -1 : code.indexOf("{", pe);
    add({ name: m[1], start: m.index, nameAt: nameIn(m, m[1], 8), params: [open, pe + 1], end: bo < 0 ? -1 : matchClose(code, bo) + 1 });
  }
  return defs.sort((a, b) => a.start - b.start);
}
function model(src) {
  const s = scan(src);
  const defs = namedFunctions(s.code);
  const byName = new Map();
  defs.forEach((d) => { if (!byName.has(d.name)) byName.set(d.name, []); byName.get(d.name).push(d); });
  return { ...s, defs, byName, lineOf: (p) => src.slice(0, p).split("\n").length };
}

/* ======================================================================================
   SINKS -- the render entry points, by identifier; the spend routes, by string literal; and
   the Go buttons, by class name. The allowed (free / read-only) calls are NOT sinks:
   /api/loom/handoff (a local frame + a free upload), /api/price and priceShot (a quote),
   /api/loom/submit-status and /api/loom/submit-abandon (the journal; never a send).
   ====================================================================================== */
const SINK_NAMES = ["generateShot", "batchGenerate", "genSubmit", "genImage", "genEdit", "genRef", "genFix",
  "runGen", "confirmSpend", "doGenerate", "submitTask",
  // The Image tab's run road (×2-4 and template prompts: /api/generate/plan then /run) -- the
  // same money as genImage, so the same rules. Stricter than §4's list, never looser.
  "genImageRun", "sendImgRun", "submitRun"];
const SINK_ROUTES = ["/api/loom/generate", "/api/generate", "/api/edit", "/api/fix", "/api/generate/run", "/api/generate/plan"];
const GO_SELECTORS = ["mgd-go", "mgdock-gen", "lm-genbtn", "lv-genall"];
const ALLOWED_ROUTES = ["/api/loom/handoff", "/api/price", "/api/loom/submit-status", "/api/loom/submit-abandon"];

const idRe = (name, flags) => new RegExp("(?<![\\w$])" + name.replace(/\$/g, "\\$") + "(?![\\w$])", flags);
const routeHit = (v) => SINK_ROUTES.find((r) => v === r || v.startsWith(r + "?") || v.startsWith(r + "/")) || null;
const selectorHit = (v) => GO_SELECTORS.find((g) => new RegExp("(^|\\s)" + g + "(\\s|$)").test(v)) || null;

/** The first sink inside one function's extent, or null. */
function sinkIn(m, d, sinks) {
  const body = m.code.slice(d.start, d.end);
  for (const s of sinks) if (idRe(s).test(body)) return s;
  for (const t of m.strings) {
    if (t.start < d.start || t.end > d.end || t.regex) continue;
    const r = routeHit(t.value);
    if (r) return '"' + r + '"';
    const g = selectorHit(t.value);
    if (g) return "." + g;
  }
  return null;
}
/** Walk from `root`; return the path to the first sink ("a → b → generateShot"), or null. */
function reach(m, root, sinks = SINK_NAMES) {
  if (!m.byName.has(root)) throw new Error("root missing — renamed? `" + root + "` is no longer a named function");
  const path = new Map([[root, [root]]]);
  const queue = [root];
  while (queue.length) {
    const name = queue.shift();
    for (const d of m.byName.get(name)) {
      const hit = sinkIn(m, d, sinks);
      if (hit) return path.get(name).concat([hit]).join(" → ");
      for (const x of m.code.slice(d.start, d.end).matchAll(/(?<![\w$])[A-Za-z_$][\w$]*/g)) {
        const id = x[0];
        if (id !== name && m.byName.has(id) && !path.has(id)) { path.set(id, path.get(name).concat([id])); queue.push(id); }
      }
    }
  }
  return null;
}

/* ---- where each reference to a sink sits (review F20) ----
   A site is one of:
     def <fn>                          its own definition
     call <fn> / ref <fn>              a call / a plain reference inside named function <fn>
                                       ("(module)" when it is in no function)
     param <Component>                 destructured in a component's (or hook's) parameters
     import                            an import statement
     prop <fn> onClick=<tag.cls>       inside a JSX prop's expression (not inside a named
                                       function nested in it)
     pass <fn> → <Child name={name}>   the bare identifier handed down to a child component
     propname <fn> name=<tag>          a JSX attribute CALLED like the sink with any other value */
function effectRanges(m) {
  return [...m.code.matchAll(/(?<![\w$.])(?:React\.)?use(?:Layout)?Effect\s*\(/g)].map((x) => {
    const open = x.index + x[0].length - 1;
    return [x.index, matchClose(m.code, open) + 1];
  });
}
function classesOf(m, tag) {
  const cn = tag.attrs.find((a) => a.name === "className");
  if (!cn) return [];
  const vals = cn.str != null ? [cn.str]
    : m.strings.filter((s) => s.start >= cn.exprStart && s.end <= cn.exprEnd && !s.regex).map((s) => s.value);
  return vals.join(" ").split(/\s+/).filter(Boolean);
}
function sitesOf(m, name) {
  const out = [];
  const imports = [...m.code.matchAll(/^import\b[^;]*;/gm)].map((x) => [x.index, x.index + x[0].length]);
  const effects = effectRanges(m);
  for (const x of m.code.matchAll(idRe(name, "g"))) {
    const p = x.index;
    const inner = m.defs.filter((d) => d.start <= p && p < d.end).sort((a, b) => b.start - a.start)[0] || null;
    const fn = inner ? inner.name : "(module)";
    const site = { at: p, line: m.lineOf(p), inEffect: effects.some(([a, b]) => a <= p && p < b) };
    let attr = null, tag = null;
    for (const t of m.tags) for (const a of t.attrs) {
      if (a.nameAt === p) { attr = { a, name: true }; tag = t; }
      else if (a.exprStart != null && a.exprStart <= p && p < a.exprEnd && (!attr || a.exprStart > attr.a.exprStart)) { attr = { a }; tag = t; }
    }
    // A tag is named by its element and its FIRST class -- the identity class; a conditional
    // modifier (" off", " on") is state, not identity.
    const tagDesc = (t) => "<" + t.name + (classesOf(m, t).length ? "." + classesOf(m, t)[0] : "") + ">";
    const bare = (a) => a.exprStart != null && m.code.slice(a.exprStart, a.exprEnd).trim() === name;
    if (m.defs.some((d) => d.name === name && d.nameAt === p)) site.key = "def " + name;
    else if (imports.some(([a, b]) => a <= p && p < b)) site.key = "import";
    else if (attr && attr.name) {
      // The attribute's NAME is the sink's: fine only as a bare pass-down (counted once, below).
      site.key = bare(attr.a) ? null : "propname " + fn + " " + name + "=" + tagDesc(tag);
    } else if (attr && (!inner || attr.a.exprStart > inner.start)) {
      if (attr.a.name === name && bare(attr.a)) site.key = "pass " + fn + " → <" + tag.name + " " + name + "={" + name + "}>";
      else site.key = "prop " + fn + " " + attr.a.name + "=" + tagDesc(tag);
      site.prop = attr.a.name;
      site.tag = tag.name;
    } else if (inner && inner.params && inner.params[0] <= p && p < inner.params[1]) site.key = "param " + fn;
    else site.key = (/^\s*\(/.test(m.code.slice(p + name.length, p + name.length + 4)) ? "call " : "ref ") + fn;
    if (site.key) out.push(site);
  }
  return out;
}
const siteKeys = (m, name) => sitesOf(m, name).map((s) => s.key).sort();

/** Review F20's structural rules, independent of the exact allowlist: no sink inside an effect;
 *  a sink in a JSX prop only as an onClick, or as a bare pass-down to a pinned component. */
function f20Violations(m, sinks, pinned) {
  const bad = [];
  for (const s of sinks) {
    for (const site of sitesOf(m, s)) {
      if (site.inEffect) bad.push(s + " is referenced inside a useEffect/useLayoutEffect callback (line " + site.line + ": " + site.key + ") -- an effect runs on its own, never on a click");
      if (site.prop && site.prop !== "onClick" && !(site.key.startsWith("pass ") && pinned.includes(site.tag))) {
        bad.push(s + " is handed to the JSX prop `" + site.prop + "` on <" + site.tag + "> (line " + site.line + ") -- only an onClick, or a bare pass-down to a pinned component (" + pinned.join(", ") + "), may carry a render entry point");
      }
      if (site.key.startsWith("propname ")) bad.push(s + " names a JSX prop with some other value (line " + site.line + ": " + site.key + ")");
    }
  }
  return bad;
}

const M = model(SRC);
const DM = model(DRAWER_SRC);
const lineOfDef = (m, name) => m.byName.has(name) ? m.byName.get(name).map((d) => m.lineOf(d.start)).join(", ") : "(missing)";

/* ======================================================================================
   THE ROOTS -- every code path that must never start a render. Each must be found by name.
   Session P, Stage A2 roots: the takes and re-anchor handlers, and every import / copy /
   open / resume / playback path that exists today.
   LATER STAGES APPEND THEIRS HERE when they create them (Stage B2): runFind, stepFind,
   clearFind, toggleCastTick, editLibraryMember.
   ====================================================================================== */
const ROOTS = [
  // P1 / P2 -- the takes strip, the take list and the stale-anchor box
  "reanchorShot", "keepAnchor", "selectTakeOnCard", "deleteTakeOnCard", "reuseTakeSettings",
  // importing
  "importBackup", "importJSON", "importBundle", "_adoptBackup", "importFootage", "useExistingVideo",
  "adoptCastHandoff",
  // duplicating, opening, switching, booting, resuming
  "dupCard", "duplicateProject", "openProject", "newProject", "loadBoards", "resumeInterrupted",
  // playback and the local cut (ffmpeg only)
  "playSequence", "exportCut",
  // Stage B1 -- P3, the music bed: pick (an upload of the owner's file to THIS machine), level,
  // remove, and the confirmed sweep of unused bed files. Play's mixing rides playSequence.
  "pickBed", "setBedLevel", "removeBed", "sweepUnusedBeds",
  // Stage B1 -- P4, the editor handoff: the EDL panel's plan and its zip download.
  "openEdl", "exportEdl",
  // Stage B1 -- P5, a collection as ordered shots: the /loom?shots= hand-off.
  "adoptShotsHandoff",
  // Stage B2 -- P7, the cast library: opening the Library view (a read), tick / untick, an edit
  // of a member everywhere it's used (the one multi-board write), and "+ Add".
  "openCastLibrary", "toggleCastTick", "editLibraryMember", "addLibraryMember",
];

describe("the tokenizer reads JavaScript + JSX correctly (so the walk below means something)", () => {
  test("on master-storyboard.jsx: offsets preserved, braces balanced, every component extent right", () => {
    assert.equal(M.code.length, SRC.length, "blanking must keep every offset");
    let depth = 0, low = 0;
    for (const ch of M.code) { if (ch === "{") depth++; else if (ch === "}") { depth--; low = Math.min(low, depth); } }
    assert.equal(depth, 0, "braces in the code (strings, comments, JSX text blanked) do not balance -- the tokenizer misread something");
    assert.equal(low, 0, "a brace closed before it opened -- the tokenizer misread something");
    for (const name of ["LoomV2", "LoomMobile", "App", "useProjectStore", "useShotMutations", "useTakeActions",
      "useGenerationPipeline", "useExportPipeline", "TakeList", "ShotPreview"]) {
      const d = (M.byName.get(name) || [])[0];
      assert.ok(d, "expected a named function `" + name + "`");
      assert.equal(SRC.slice(d.end - 2, d.end), "\n}", "`" + name + "` must end at its own column-0 closing brace (line " + M.lineOf(d.end) + ")");
    }
  });
  test("strings, templates, regexes, comments and JSX text are not code; the code around them is", () => {
    const syn = [
      "const a = (x) => {",
      '  const s = "generateShot(1)";',
      "  const r = /[{'\"]/g;",
      '  const t = `${x ? "}" : `{`}`;',
      "  // generateShot() in a comment",
      "  return <div title=\"it's\">It's {x} here — can't {\"}\"} </div>;",
      "};",
      "const b = async () => { await c(); };",
      "function c() { return 1; }",
    ].join("\n");
    const sm = model(syn);
    assert.deepEqual(sm.defs.map((d) => d.name), ["a", "b", "c"]);
    const a = sm.byName.get("a")[0];
    assert.equal(syn.slice(a.end - 2, a.end), "\n}", "`a` ends at its own closing brace, past the JSX text's apostrophes");
    assert.equal(sitesOf(sm, "generateShot").length, 0, "a sink named in a string or a comment is not a reference");
    assert.ok(sm.strings.some((s) => s.value === "generateShot(1)"), "the string itself is recorded");
    assert.equal(reach(sm, "b"), null);
  });
});

describe("negative controls: the walker and the F20 rules really fail", () => {
  test("a root that reaches generateShot through a helper is caught, with its path", () => {
    const fake = model("const onOpen = () => { helper(); };\nconst helper = () => { generateShot(entry); };\n");
    assert.equal(reach(fake, "onOpen"), "onOpen → helper → generateShot");
  });
  test("a spend route and a Go button are sinks too", () => {
    const route = model('const onOpen = () => poke();\nconst poke = () => fetch("/api/loom/generate", {});\n');
    assert.equal(reach(route, "onOpen"), 'onOpen → poke → "/api/loom/generate"');
    const go = model('const onOpen = () => { Panel(); };\nfunction Panel() { return <button className="lv-genall" onClick={go}>Go</button>; }\n');
    assert.equal(reach(go, "onOpen"), "onOpen → Panel → .lv-genall");
  });
  test("a renamed root fails loudly instead of passing", () => {
    assert.throws(() => reach(M, "noSuchRootAnywhere"), /root missing — renamed\?/);
  });
  test("F20: an effect that calls a sink, and a sink handed to a non-onClick prop, are both flagged", () => {
    const fake = model([
      "function Screen({ genSubmit, generateShot }) {",
      "  useEffect(() => { if (auto) genSubmit(); }, [auto]);",
      "  return <Child onMount={generateShot} />;",
      "}",
    ].join("\n"));
    const bad = f20Violations(fake, ["genSubmit", "generateShot"], []);
    assert.ok(bad.some((b) => /genSubmit is referenced inside a useEffect/.test(b)), bad.join("\n"));
    assert.ok(bad.some((b) => /generateShot is handed to the JSX prop `onMount`/.test(b)), bad.join("\n"));
  });
});

describe("never auto-render: no root can reach a render (BUILD-w5-p §4)", () => {
  for (const root of ROOTS) {
    test(root + " cannot reach a render entry point, a spend route or a Go button", () => {
      const p = reach(M, root);
      assert.equal(p, null, "a path from a no-render root reaches a render: " + p);
    });
  }
  test("the walk finds the paths that DO spend (it is not vacuous on the real file)", () => {
    assert.equal(reach(M, "genSubmit"), "genSubmit → generateShot");
    assert.equal(reach(M, "batchGenerate"), "batchGenerate → generateShot");
    assert.equal(reach(M, "generateShot", SINK_NAMES.filter((s) => s !== "generateShot")), 'generateShot → "/api/loom/generate"');
  });
  test("the allowed network calls are not sinks (the walk would otherwise stop proving anything)", () => {
    for (const r of ALLOWED_ROUTES) assert.equal(routeHit(r), null, r);
    assert.ok(!SINK_NAMES.includes("priceShot") && !SINK_NAMES.includes("beginDrawerRender"),
      "priceShot is a read-only quote; beginDrawerRender (the drawer's beforeSend) only latches and saves the board -- it POSTs no render route");
    const b = M.byName.get("beginDrawerRender");
    assert.ok(b, "beginDrawerRender is A1's drawer lock -- renamed?");
    assert.equal(sinkIn(M, b[0], SINK_NAMES), null, "the drawer's beforeSend must never reach a render route itself");
  });
});

/* ======================================================================================
   THE CALLER ALLOWLIST (review F20), derived from the code as it stands after Stage A2.
   A change here is a change to WHERE money can be spent from: it needs the owner's eye.
   ====================================================================================== */
const PASS = (fn, child, name) => "pass " + fn + " → <" + child + " " + name + "={" + name + "}>";
// The four desktop/phone tab entry points share one shape: the hook defines and returns it, App
// destructures it and hands it to both views, and each view calls it from its own Go button.
const tabSink = (name, desktopGo, phoneGo) => [
  "def " + name, "ref useGenerationPipeline", "ref App",
  PASS("App", "LoomMobile", name), PASS("App", "LoomV2", name),
  "param LoomV2", "param LoomMobile",
  "prop LoomV2 onClick=" + desktopGo, "prop LoomMobile onClick=" + phoneGo,
];
const ALLOW = {
  generateShot: [
    "def generateShot",
    "call batchGenerate",                       // Generate all (one confirm, then per shot)
    "call genSubmit",                           // the phone's Generate
    "prop LoomV2 onClick=<button.lv-render>",   // the board card's Render / Re-render (Stage A2)
    "ref useGenerationPipeline", "ref App",     // the hook returns it; App destructures it
    PASS("App", "LoomMobile", "generateShot"), PASS("App", "LoomV2", "generateShot"),
    "param LoomMobile", "param LoomV2",         // ...and each view receives it (pinned just above)
  ],
  batchGenerate: [
    "def batchGenerate", "ref useGenerationPipeline", "ref App", PASS("App", "LoomV2", "batchGenerate"),
    "param LoomV2", "prop LoomV2 onClick=<button.lv-genall>",
  ],
  genSubmit: ["def genSubmit", "prop LoomMobile onClick=<button.lm-genbtn>"],
  genImage: tabSink("genImage", "<button.lv-go>", "<button.lm-genbtn>"),
  genEdit: tabSink("genEdit", "<button.lv-go>", "<button.lm-genbtn>"),
  genRef: tabSink("genRef", "<button.lv-go>", "<button.lm-genbtn>"),
  genFix: tabSink("genFix", "<button.lv-go>", "<button.lm-genbtn>"),
  runGen: ["def runGen", "call genEdit", "call genRef", "call genFix"],
  confirmSpend: ["def confirmSpend", "call genImage", "call runGen"],
  genImageRun: ["def genImageRun", "call genImage"],
  sendImgRun: ["import", "call genImageRun"],
  // The run road's transport, bound once at module scope into LOOM_RUN_DEPS (read by genImageRun).
  submitRun: ["import", "ref (module)"],
  // Neither lives in the Loom's own file: the drawer's Go is VideoDrawer.jsx's (pinned below).
  doGenerate: [],
  submitTask: [],
};
const DRAWER_ALLOW = {
  doGenerate: ["def doGenerate", "prop VideoDrawer onClick=<button.mgd-go>", "prop VideoDrawer onClick=<button.mgdock-gen>"],
  submitTask: ["import", "call doGenerate"],
};
const PINNED_CHILDREN = ["LoomV2", "LoomMobile"];

function assertSites(m, name, allowed, file) {
  const got = siteKeys(m, name);
  const want = allowed.slice().sort();
  if (JSON.stringify(got) === JSON.stringify(want)) return;
  const left = want.slice();
  const extra = [];
  for (const g of got) { const i = left.indexOf(g); if (i >= 0) left.splice(i, 1); else extra.push(g); }
  const lines = sitesOf(m, name).filter((s) => extra.includes(s.key)).map((s) => "    + line " + s.line + ": " + s.key);
  assert.fail(file + ": the render entry point `" + name + "` is referenced where the allowlist does not allow it, or an allowed site is gone.\n"
    + (lines.length ? "  NOT ALLOWED:\n" + lines.join("\n") + "\n" : "")
    + (left.length ? "  ALLOWED BUT MISSING (renamed or moved?):\n" + left.map((k) => "    - " + k).join("\n") + "\n" : "")
    + "  A new place that can spend needs the owner's eye before it joins this list.");
}

describe("F20: every render entry point is referenced only from its allowed callers", () => {
  for (const [name, allowed] of Object.entries(ALLOW)) {
    test("master-storyboard.jsx: " + name, () => assertSites(M, name, allowed, "master-storyboard.jsx"));
  }
  for (const [name, allowed] of Object.entries(DRAWER_ALLOW)) {
    test("VideoDrawer.jsx: " + name, () => assertSites(DM, name, allowed, "VideoDrawer.jsx"));
  }
  test("no render entry point inside an effect; in JSX only as an onClick or a pinned pass-down", () => {
    const bad = f20Violations(M, SINK_NAMES, PINNED_CHILDREN).concat(f20Violations(DM, SINK_NAMES, []));
    assert.deepEqual(bad, [], "\n" + bad.join("\n"));
  });
  test("every child a render entry point is handed to has its own uses pinned (a param site above)", () => {
    for (const name of SINK_NAMES) {
      for (const s of sitesOf(M, name).filter((x) => x.key.startsWith("pass "))) {
        assert.ok(PINNED_CHILDREN.includes(s.tag), name + " is handed to <" + s.tag + "> (line " + s.line + "), whose uses are not pinned here");
        assert.ok(siteKeys(M, name).includes("param " + s.tag),
          name + " is handed to <" + s.tag + "> but <" + s.tag + "> does not receive it as a parameter -- the pass-down and the pin disagree");
      }
    }
  });
});

describe("placement pins", () => {
  const routeSites = (m) => m.strings.filter((s) => !s.regex && routeHit(s.value) === "/api/loom/generate");
  const fnAt = (m, p) => (m.defs.filter((d) => d.start <= p && p < d.end).sort((a, b) => b.start - a.start)[0] || {}).name || "(module)";
  test("the literal /api/loom/generate appears in master-storyboard.jsx exactly once, inside generateShot", () => {
    const hits = routeSites(M);
    assert.deepEqual(hits.map((s) => fnAt(M, s.start)), ["generateShot"],
      "/api/loom/generate must be named only by generateShot's one POST; found in: " + hits.map((s) => fnAt(M, s.start) + " (line " + M.lineOf(s.start) + ")").join(", "));
  });
  test("in gallery/src it appears only in VideoDrawer's doGenerate, as submitTask's route", () => {
    const root = path.join(here, "../../gallery/src");
    const found = [];
    (function walk(dir) {
      for (const name of readdirSync(dir)) {
        const p = path.join(dir, name);
        if (statSync(p).isDirectory()) { walk(p); continue; }
        if (!/\.(jsx?|mjs)$/.test(name)) continue;
        const text = readFileSync(p, "utf8").replace(/\r\n/g, "\n");
        if (!text.includes("/api/loom/generate")) continue;
        const m = model(text);
        for (const s of routeSites(m)) found.push({ file: path.relative(root, p).split(path.sep).join("/"), fn: fnAt(m, s.start),
          viaSubmitTask: /submitTask\(\s*$/.test(m.code.slice(Math.max(0, s.start - 40), s.start)), line: m.lineOf(s.start) });
      }
    })(root);
    assert.deepEqual(found.map((f) => [f.file, f.fn, f.viaSubmitTask]), [["components/VideoDrawer.jsx", "doGenerate", true]],
      "gallery/src may name /api/loom/generate only as VideoDrawer doGenerate's submitTask route; found: " + JSON.stringify(found));
  });
  test("takes / selectedTake / takeSeq are written only by loom/src/loom-takes-core.js", () => {
    const FIELD = "(takes|selectedTake|takeSeq)";
    // The Loom and the drawer never even NAME the fields: they read takes through the views.
    for (const [file, m] of [["master-storyboard.jsx", M], ["VideoDrawer.jsx", DM]]) {
      const hits = [...m.code.matchAll(new RegExp("(?<![\\w$])" + FIELD + "(?![\\w$])", "g"))];
      assert.deepEqual(hits.map((h) => h[0] + " (line " + m.lineOf(h.index) + ")"), [], file + " names a take field in code");
    }
    const WRITE = new RegExp("(?:[{,]\\s*" + FIELD + "\\s*:(?!:))|(?:\\." + FIELD + "\\s*(?:[-+*/]?=)(?!=))|(?:\\bdelete\\s+[\\w$.]+\\." + FIELD + "\\b)");
    const others = readdirSync(path.join(here, "../src")).filter((f) => f.endsWith(".js") && f !== "loom-takes-core.js");
    assert.ok(others.includes("loom-core.js") && others.includes("loom-mutations.js"), "the loom/src walk is broken");
    for (const f of others) {
      const m = model(read("src/" + f));
      const lines = m.code.split("\n").map((l, i) => [i + 1, l]).filter(([, l]) => WRITE.test(l));
      if (f === "loom-mutations.js") {
        // The one exception: a DUPLICATE clears them (to undefined) -- a fresh, unrendered shot.
        assert.deepEqual(lines.map(([, l]) => l.trim()), ["takes: undefined, selectedTake: undefined, takeSeq: undefined, deletedTakes: undefined,"],
          "loom-mutations.js may only CLEAR the take fields, in FRESH_CARD_RESET");
      } else {
        assert.deepEqual(lines.map(([n, l]) => "line " + n + ": " + l.trim()), [], "src/" + f + " writes a take field; only loom-takes-core.js may");
      }
    }
    // Strings as computed keys (card["takes"] = ...) in any of them.
    for (const [file, m] of [["master-storyboard.jsx", M], ["VideoDrawer.jsx", DM]].concat(others.map((f) => ["src/" + f, model(read("src/" + f))]))) {
      for (const s of m.strings) {
        if (!/^(takes|selectedTake|takeSeq)$/.test(s.value)) continue;
        assert.doesNotMatch(m.code.slice(s.end, s.end + 12), /^\s*\]\s*[-+*/]?=(?!=)/, file + " writes " + s.value + " through a computed key (line " + m.lineOf(s.start) + ")");
      }
    }
  });
  test("no landing reads genTargetRef (it is gone): every landing is keyed by its own submit / task id", () => {
    assert.doesNotMatch(M.code, /(?<![\w$])genTargetRef(?![\w$])/, "genTargetRef is back in master-storyboard.jsx");
  });
});

describe("the pure modules can reach nothing", () => {
  for (const [file, allowedImports] of [["src/loom-takes-core.js", ["./loom-core.js"]], ["src/loom-store-core.js", []],
    // Stage B1: the EDL plan reads the ★ take through loom-takes-core.js's selectedTakeView
    // (review F9) and the board through loom-core.js -- exactly those two (BUILD-w5-p §4).
    ["src/loom-edl-core.js", ["./loom-core.js", "./loom-takes-core.js"]],
    // the collection -> shots builder: loom-core.js's newCardShape only
    ["src/loom-shots-core.js", ["./loom-core.js"]],
    // the music bed's rules and timing: the ★ take's settings, for "own audio"
    ["src/loom-bed-core.js", ["./loom-takes-core.js"]],
    // Stage B2 -- the cast library's views and patches (P7): the board walk and tag rule only
    ["src/loom-cast-library.js", ["./loom-core.js"]]]) {
    test(file + ": no fetch / window / document / XMLHttpRequest, imports only " + (allowedImports.join(", ") || "nothing") + ", names no sink", () => {
      const m = model(read(file));
      for (const g of ["fetch", "window", "document", "XMLHttpRequest", "globalThis", "require"]) {
        const hit = m.code.search(new RegExp("(?<![\\w$.])" + g + "(?![\\w$])"));
        assert.equal(hit, -1, file + " uses `" + g + "` (line " + (hit >= 0 ? m.lineOf(hit) : "") + ") -- a pure module may not reach the network or the page");
      }
      const imports = [...m.code.matchAll(/^\s*(?:import|export)\b[^;]*?\bfrom\b[^;]*;|^\s*import\s*["'`][^;]*;/gm)];
      const specs = imports.map((x) => (m.strings.find((s) => s.start >= x.index && s.end <= x.index + x[0].length) || {}).value);
      assert.deepEqual(specs.filter((s) => !allowedImports.includes(s)), [], file + " imports something other than " + (allowedImports.join(", ") || "nothing"));
      assert.equal(m.code.search(/(?<![\w$.])import\s*\(/), -1, file + " has a dynamic import");
      for (const s of SINK_NAMES) assert.doesNotMatch(m.code, idRe(s), file + " names the render entry point " + s);
      for (const t of m.strings) {
        assert.equal(routeHit(t.value), null, file + " names the spend route " + t.value);
        assert.equal(selectorHit(t.value), null, file + " names a Go button: " + t.value);
      }
    });
  }
});

/* ======================================================================================
   NOTHING WRITES ON OPEN, FOR THE CAST LIBRARY TOO (Session P, Stage B2 -- NOTES P7,
   BUILD-w5-p §1.2). Opening the Library view reads the library and every other storyboard
   (for "in N storyboards"); the same walker, with the KV WRITERS as its sinks, proves no
   write of any kind -- a board, the library, the pointer, a thumbnail -- is reachable from it.
   The boot / open paths are A1's (loom-render-lifecycle-wiring.test.js); here they are pinned
   not to name the library's writers at all.
   ====================================================================================== */
const KV_WRITERS = ["sSet", "sDel", "writeBoard", "writeCastLibrary", "saveOtherBoard", "persistBoard", "saveBoardNow",
  "createBoard", "setProject", "storeThumb", "flushSave"];
describe("opening the cast library writes nothing (P7)", () => {
  test("openCastLibrary reaches no KV write, no board edit and no render", () => {
    assert.equal(reach(M, "openCastLibrary", KV_WRITERS), null);
    for (const r of ["readCastLibrary", "readOtherBoards"]) {
      assert.ok(M.byName.has(r), r + " is the library's read -- renamed?");
      assert.equal(reach(M, r, KV_WRITERS), null, r + " must only read");
    }
  });
  test("the walk is not vacuous: the owner's library actions DO reach their writes", () => {
    assert.match(reach(M, "toggleCastTick", ["writeCastLibrary"]) || "", /^toggleCastTick → writeCastLibrary$/);
    assert.match(reach(M, "editLibraryMember", ["saveOtherBoard"]) || "", /^editLibraryMember → saveOtherBoard$/);
    assert.match(reach(M, "addLibraryMember", ["setProject"]) || "", /^addLibraryMember → setProject$/);
  });
  test("the Library tab and the phone's Library tab call only the read when they show", () => {
    const effects = [...SRC.matchAll(/useEffect\(\(\) => \{\n?\s*if \(([^)]*)\) castApi\.openCastLibrary\(\);\n?\s*\}, \[([^\]]*)\]\);/g)];
    assert.deepEqual(effects.map((m) => m[1]), [
      '!leftCollapsed && leftTab === "library" && castApi',
      'castSheetOpen && castSheetTab === "library" && castApi',
    ], "exactly the two tab effects, each calling only openCastLibrary");
    assert.equal((M.code.match(/(?<![\w$])openCastLibrary(?![\w$])/g) || []).length, 4,
      "its definition, the hook's return and the two tab effects -- nothing else opens it");
  });
  test("the boot, open, new and duplicate paths do not name the library's writers", () => {
    for (const name of ["loadBoards", "openProject", "showBoard", "newProject", "duplicateProject", "readProjList"]) {
      for (const d of M.byName.get(name) || []) {
        const body = M.code.slice(d.start, d.end);
        assert.doesNotMatch(body, /(?<![\w$])(writeCastLibrary|saveOtherBoard|CASTLIB_KEY|castLibRef)(?![\w$])/, name);
      }
    }
    const hook = (M.byName.get("useCastLibrary") || [])[0];
    assert.ok(hook, "useCastLibrary -- renamed?");
    const body = SRC.slice(hook.start, hook.end);
    assert.match(body, /useEffect\(\(\) => \{ setOthers\(null\); setLibPhase\("idle"\); setLibNote\(""\); \}, \[activeId\]\);/,
      "switching boards only forgets the last read");
    assert.equal((body.match(/useEffect\(/g) || []).length, 1, "the hook has no other effect");
  });
});

describe("the drawer's host API cannot reach a submit (VideoDrawer.jsx, same walker)", () => {
  const HOST_API = ["prefill", "setRefs", "setBusy", "flushPromptEdit", "insertText", "setReuse", "setLoomTarget", "setHost"];
  for (const name of HOST_API) {
    test(name + " is on the node and cannot reach doGenerate or submitTask", () => {
      assert.match(DRAWER_SRC, new RegExp("node\\." + name + " = " + name + ";"), name + " is no longer the node's own " + name + " -- renamed?");
      const p = reach(DM, name, ["doGenerate", "submitTask"]);
      assert.equal(p, null, "the drawer's host API reaches a submit: " + p);
    });
  }
  test("the walk is not vacuous on the drawer: Go reaches the road", () => {
    assert.equal(reach(DM, "doGenerate", ["submitTask"]), "doGenerate → submitTask");
  });
});

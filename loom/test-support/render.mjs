/* render.mjs -- render a real React component to static HTML inside `node --test`.

   WHY THIS EXISTS. Until now the only way a node test could check a component was to read its
   SOURCE as text and regex it ("text pins"). This helper renders the component instead: it
   bundles the component's file on the fly with esbuild and runs it through react-dom/server's
   renderToStaticMarkup with the props you give it, so a test asserts on what the component
   actually RENDERS, not on how its source happens to be spelled.

   WHERE IT LIVES, AND WHY NOT loom/test/. Node's test runner, given no file list, runs EVERY
   .js/.mjs/.cjs file anywhere below a directory named `test` -- underscore prefix or not -- so a
   helper inside loom/test/ would run as a test file of its own. This folder is outside every
   default glob; tests import it as "../test-support/render.mjs".

   WHAT IT CAN TEST: what a component renders for given props and its INITIAL state -- which
   elements, classes, attributes, text and ARIA appear, which branches show or hide (a row that
   must not render without a real cost, a disabled button, a warning line) -- for a component in
   gallery/src, loom/src or loom/master-storyboard.jsx.

   WHAT IT CANNOT TEST: anything after the first render. A static render runs NO effects
   (useEffect / useLayoutEffect bodies never execute), so fetch, timers, polls, subscriptions
   and listeners set up in effects are never called: rendering here spends nothing and polls
   nothing. Refs stay null and imperative handles are never attached (CostBadge's setPrice
   cannot be called, so it renders its initial idle state only). No clicks, no input, no
   re-renders, no state changes, no layout or CSS. A createPortal throws (no DOM container
   to portal into, and the server renderer has no portals). Those stay as pure logic tests over the *Core.js modules,
   and as live browser checks.

   MODULE TOP LEVEL DOES RUN. Importing a file runs its top-level code and its imports' -- that
   part is not a render. master-storyboard.jsx calls installNotify() at module scope (it
   would start the Jobs poller and its fetches in a browser), so it loads only with
   { mocks: LOOM_MOCKS }, which swaps gallery/src/notify/index.jsx for an inert stub. Without
   that, the import stops at installNotify's first `window` read and nothing is fetched.

   NO DOM. Nothing here installs window/document/localStorage. A component (or a module it
   imports) that reads `window` while rendering or at module top level throws a
   ReferenceError: that component is not statically renderable as written.

   HOW THE BUNDLE IS BUILT.
   - JSX in .jsx and .js, automatic runtime, ESM output. One bundle per (files, mocks) set,
     cached in memory for the rest of the process. node --test runs each test file in its own
     process, so the cache is per test file: a file that renders one component ten times
     builds it once. Bundles are written to a temp folder (removed at exit) with inline source
     maps, and source maps are switched on, so a stack trace names gallery/src/... lines.
   - react / react-dom (and subpaths: react/jsx-runtime, react-dom/server, ...) are NOT
     bundled: they resolve to loom/node_modules -- the one copy this helper renders with, so
     hooks see the same React that react-dom/server drives. Nothing is ever resolved from
     gallery/node_modules (CI's loom job runs `npm ci` in loom/ only).
   - Any other package import is bundled from loom/node_modules if it is installed there, and
     otherwise replaced by a stub that throws when CALLED (importing is fine; calling it while
     rendering fails loudly and names the package -- e.g. qrcode-generator, gallery-only).
   - CSS imports become empty modules; image/font/media imports become a placeholder URL
     string ("/render-stub/<file name>").
   - Module-level state is per bundle: two separate loads get two copies of any module they
     share (a store, a context). To set a store or provide a context a component reads, load
     both from ONE bundle with loadModules([...]).

   NAMES. `name` is an export of the file ("default" for the default export), or a capitalised
   top-level function/class/const the file declares without exporting -- master-storyboard.jsx
   exports only App, and its other components (TakeList, RibbonStrip, EdlPanel, ...) are
   reachable this way.

   API
     render(source, name = "default", props = {}, { mocks } = {})  -> Promise<string markup>
     loadComponent(source, name = "default", { mocks } = {})        -> Promise<component>
     loadModule(source, { mocks } = {})                             -> Promise<exports>
     loadModules([source, ...], { mocks } = {})                     -> Promise<exports[]> (one bundle)
     bundleInputs([source, ...], { mocks } = {})                    -> Promise<repo-relative files bundled>
     renderElement(element)                                         -> string markup
     h                                                              -> React.createElement (loom's React)
     query(markup)                                                  -> El root (DOM-free queries below)
     LOOM_MOCKS                                                     -> mocks for master-storyboard.jsx
   `source` is repo-relative ("gallery/src/components/CostBadge.jsx") or absolute. `mocks` maps a
   source path to replacement module source text.

     const html = await render("gallery/src/components/StorageBars.jsx", "default", { storage });
     const $ = query(html);
     $.byClass("mgcu-stor-row").length;  $.byText("BY TYPE");  $.byAttr("disabled");
*/
import { createRequire } from "node:module";
import * as nodeModule from "node:module";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import * as esbuild from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const here = path.dirname(fileURLToPath(import.meta.url));
export const LOOM_DIR = path.resolve(here, "..");
export const REPO_ROOT = path.resolve(LOOM_DIR, "..");
const loomRequire = createRequire(path.join(LOOM_DIR, "package.json"));

const REACT_RE = /^react(-dom)?(\/.*)?$/;
const ASSET_RE = /\.(css|svg|png|jpe?g|gif|webp|avif|ico|bmp|mp4|webm|mov|mp3|wav|ogg|m4a|woff2?|ttf|otf|eot)(\?.*)?$/i;
const LOCAL_DECL_RE = /^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*|class\s+|(?:const|let|var)\s+)([A-Z][A-Za-z0-9_$]*)\b/gm;
const LOCALS = "__renderLocals";
const ENTRY_NAME = "<render-helper entry>";

/** master-storyboard.jsx runs installNotify() at module scope; this swaps the notify module
    for an inert one so the file can be imported (and nothing polls or fetches). */
export const LOOM_MOCKS = Object.freeze({
  "gallery/src/notify/index.jsx":
    "export function installNotify() {}\nexport function NotifyRoot() { return null; }\n",
});

/** Absolute path of a source file, given repo-relative ("gallery/src/x.jsx") or absolute. */
export function resolveSource(source) {
  const abs = path.isAbsolute(source) ? path.resolve(source) : path.resolve(REPO_ROOT, source);
  const rel = path.relative(REPO_ROOT, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error("render helper: " + source + " is outside the repository");
  }
  return abs;
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Capitalised top-level declarations of a file -- the names a test may ask for even when the
// file does not export them. Top-level code in this repo starts at column 0. Each is exposed
// through a getter guarded by `typeof`, so a false match (a column-0 line inside a comment or a
// template string) reads as undefined instead of breaking the build.
function localsTail(src) {
  const names = [...new Set([...src.matchAll(LOCAL_DECL_RE)].map((m) => m[1]))];
  if (!names.length) return "";
  return "\nexport const " + LOCALS + " = { "
    + names.map((n) => "get " + n + "() { return typeof " + n + " === \"undefined\" ? undefined : " + n + "; }").join(", ")
    + " };\n";
}

function helperPlugin(entries, mocks) {
  return {
    name: "render-helper",
    setup(build) {
      // react / react-dom: loom/node_modules' copy, left as an external import by absolute file
      // URL -- the same module instance react-dom/server renders with.
      build.onResolve({ filter: REACT_RE }, (args) => ({
        path: pathToFileURL(loomRequire.resolve(args.path)).href, external: true,
      }));
      // Stylesheets and media: nothing to render in them.
      build.onResolve({ filter: ASSET_RE }, (args) => ({ path: args.path, namespace: "render-stub-asset" }));
      build.onLoad({ filter: /.*/, namespace: "render-stub-asset" }, (args) => {
        const file = args.path.replace(/\?.*$/, "");
        if (/\.css$/i.test(file)) return { contents: "", loader: "js" };
        return { contents: "export default " + JSON.stringify("/render-stub/" + path.basename(file)) + ";", loader: "js" };
      });
      // Every other bare package: loom/node_modules or a stub -- never gallery/node_modules.
      build.onResolve({ filter: /^[^./]/ }, (args) => {
        if (args.kind === "entry-point" || path.isAbsolute(args.path)) return undefined;
        if (args.path.startsWith("node:")) return { path: args.path, external: true };
        try {
          return { path: loomRequire.resolve(args.path) };
        } catch {
          return { path: args.path, namespace: "render-stub-pkg" };
        }
      });
      build.onLoad({ filter: /.*/, namespace: "render-stub-pkg" }, (args) => ({
        contents: "module.exports = function renderStub() { throw new Error("
          + JSON.stringify("render helper: package '" + args.path + "' is not installed in loom/node_modules, "
            + "so it is stubbed, and this component called it while rendering") + "); };",
        loader: "js",
      }));
      // Mocked files get their replacement text; requested files also export their capitalised
      // top-level declarations (so TakeList etc. can render).
      const special = [...Object.keys(mocks), ...entries];
      if (!special.length) return;
      const filter = new RegExp("^(?:" + special.map(escapeRe).join("|") + ")$");
      build.onLoad({ filter }, (args) => {
        const resolveDir = path.dirname(args.path);
        if (Object.prototype.hasOwnProperty.call(mocks, args.path)) {
          return { contents: mocks[args.path], loader: "jsx", resolveDir };
        }
        const src = readFileSync(args.path, "utf8");
        return { contents: src + localsTail(src), loader: "jsx", resolveDir };
      });
    },
  };
}

let outDir = null;
let outN = 0;
function writeBundle(code) {
  if (!outDir) {
    outDir = mkdtempSync(path.join(tmpdir(), "loom-render-"));
    process.on("exit", () => { try { rmSync(outDir, { recursive: true, force: true }); } catch { /* best effort */ } });
    // Stack traces from a render point at gallery/src/... lines, not at the temp bundle.
    if (typeof nodeModule.setSourceMapsSupport === "function") nodeModule.setSourceMapsSupport(true);
    else if (typeof process.setSourceMapsEnabled === "function") process.setSourceMapsEnabled(true);
  }
  const file = path.join(outDir, "bundle-" + (++outN) + ".mjs");
  writeFileSync(file, code);
  return pathToFileURL(file).href;
}

const bundles = new Map();   // key: files + mocks -> Promise<{ ns: {m0, m1, ...}, inputs: [repo-relative paths] }>

function absMocks(mocks) {
  const out = {};
  for (const [k, v] of Object.entries(mocks || {})) out[resolveSource(k)] = String(v);
  return out;
}

function bundle(absPaths, mocks) {
  const key = JSON.stringify([absPaths, Object.entries(mocks).sort()]);
  if (!bundles.has(key)) {
    const job = (async () => {
      const entry = absPaths.map((p, i) => "export * as m" + i + " from " + JSON.stringify(p) + ";").join("\n");
      const result = await esbuild.build({
        stdin: { contents: entry, resolveDir: REPO_ROOT, sourcefile: ENTRY_NAME, loader: "js" },
        bundle: true,
        write: false,
        format: "esm",
        platform: "browser",
        target: ["es2022"],
        jsx: "automatic",
        loader: { ".js": "jsx", ".jsx": "jsx" },
        sourcemap: "inline",
        sourcesContent: false,
        sourceRoot: pathToFileURL(REPO_ROOT).href + "/",   // map paths are repo-relative
        absWorkingDir: REPO_ROOT,
        metafile: true,
        logLevel: "silent",
        plugins: [helperPlugin(absPaths, mocks)],
      });
      // Repo-relative files the bundle was built from (stubs and the synthetic entry left out).
      const inputs = Object.keys(result.metafile.inputs)
        .filter((p) => p !== ENTRY_NAME && !/^render-stub-(asset|pkg):/.test(p));
      try {
        return { ns: await import(writeBundle(result.outputFiles[0].text)), inputs };
      } catch (e) {
        if (e instanceof ReferenceError && /\b(window|document|localStorage|sessionStorage|navigator)\b/.test(e.message)) {
          e.message += " -- while IMPORTING " + absPaths.map((p) => path.relative(REPO_ROOT, p).split(path.sep).join("/")).join(", ")
            + ": some module's top-level code needs a browser. The render helper has no DOM; mock that module"
            + " ({ mocks }) or move the read into an effect. See loom/test-support/render.mjs.";
        }
        throw e;
      }
    })();
    bundles.set(key, job);
    job.catch(() => bundles.delete(key));   // a failed build is not cached
  }
  return bundles.get(key);
}

// A module's own exports, plus its unexported capitalised declarations under their own names.
function surface(mod) {
  const out = {};
  for (const [k, v] of Object.entries(mod)) if (k !== LOCALS) out[k] = v;
  for (const [k, v] of Object.entries(mod[LOCALS] || {})) if (!(k in out) && v !== undefined) out[k] = v;
  return out;
}

/** Several source files bundled TOGETHER, so a store or context module they share is one
    instance: set the store / build the provider from the returned exports, then render. */
export async function loadModules(sources, { mocks } = {}) {
  const abs = sources.map(resolveSource);
  const { ns } = await bundle(abs, absMocks(mocks));
  return abs.map((_, i) => surface(ns["m" + i]));
}

/** The repo-relative source files a load of `sources` bundles (react/react-dom, stubbed
    packages and stubbed CSS/assets are not bundled, so they never appear). */
export async function bundleInputs(sources, { mocks } = {}) {
  return (await bundle(sources.map(resolveSource), absMocks(mocks))).inputs.slice();
}

/** The bundled exports of one source file, plus its unexported capitalised top-level names. */
export async function loadModule(source, options = {}) {
  return (await loadModules([source], options))[0];
}

/** The component `name` from `source` ("default" for the default export). */
export async function loadComponent(source, name = "default", options = {}) {
  const mod = await loadModule(source, options);
  if (typeof mod[name] === "undefined") {
    throw new Error("render helper: " + source + " has no export or top-level component named '" + name
      + "' (has: " + Object.keys(mod).sort().join(", ") + ")");
  }
  return mod[name];
}

/** Static markup of any React element (build it with `h`). */
export function renderElement(element) {
  return renderToStaticMarkup(element);
}

/** Render `<name {...props} />` from `source`; returns its static markup. Pass children as
    props.children. */
export async function render(source, name = "default", props = {}, options = {}) {
  const Component = await loadComponent(source, name, options);
  return renderToStaticMarkup(createElement(Component, props));
}

/** React.createElement from the one React this helper renders with. */
export const h = createElement;

/* ---------------------------------------------------------------------------------------
   A tiny DOM-free query layer over the markup. renderToStaticMarkup emits well-formed HTML
   (quoted attributes, escaped text, void elements unclosed), which is all this parses.
   --------------------------------------------------------------------------------------- */

const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);
const RAW = new Set(["script", "style"]);
const ENT = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " " };

/** HTML entities -> characters (the ones React emits, numeric ones, and nbsp). */
export function decode(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") return String.fromCodePoint(e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENT[e.toLowerCase()] ?? m;
  });
}

const textMatch = (text, want) => (want instanceof RegExp ? want.test(text) : text.includes(want));
const valueMatch = (v, want) => (want === undefined ? v !== undefined
  : v !== undefined && (want instanceof RegExp ? want.test(v) : v === String(want)));

/** One element of the parsed markup. Queries search its descendants. */
export class El {
  constructor(tag, attrs, parent, source, start) {
    this.tag = tag; this.attrs = attrs; this.parent = parent; this.children = [];
    this._src = source; this._start = start; this._end = start;
  }
  /** Decoded text content of this element and everything inside it. */
  get text() { return this.children.map((c) => (typeof c === "string" ? c : c.text)).join(""); }
  /** The element's own markup, exactly as rendered. */
  get html() { return this._src.slice(this._start, this._end); }
  get classes() { return (this.attrs.class || "").split(/\s+/).filter(Boolean); }
  attr(name) { return this.attrs[name]; }
  hasClass(c) { return this.classes.includes(c); }
  /** Every element below this one, in document order. */
  all() {
    const out = [];
    const walk = (n) => { for (const c of n.children) if (typeof c !== "string") { out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  find(pred) { return this.all().filter(pred); }
  byTag(tag) { return this.find((e) => e.tag === tag.toLowerCase()); }
  byClass(c) { return this.find((e) => e.hasClass(c)); }
  /** byAttr("disabled") = has the attribute; byAttr("data-state", "free") or a RegExp = its value. */
  byAttr(name, value) { return this.find((e) => valueMatch(e.attrs[name], value)); }
  /** The innermost elements whose text contains `want` (string) or matches it (RegExp). */
  byText(want) {
    return this.find((e) => textMatch(e.text, want)
      && !e.children.some((c) => typeof c !== "string" && textMatch(c.text, want)));
  }
}

/** Exactly one element, or a throw that says how many there were. */
export function one(list, what = "element") {
  if (list.length !== 1) throw new Error("expected exactly one " + what + ", found " + list.length);
  return list[0];
}

/** Parse static markup into a root El (tag "#root") carrying the query methods above. */
export function query(markup) {
  const root = new El("#root", {}, null, markup, 0);
  root._end = markup.length;
  const tagRe = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w:-]*)\s*>|<([a-zA-Z][\w:-]*)((?:\s+[^\s"'>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>/g;
  const attrRe = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let cur = root, last = 0, m;
  const pushText = (t) => { if (t) cur.children.push(decode(t)); };
  while ((m = tagRe.exec(markup))) {
    pushText(markup.slice(last, m.index));
    last = tagRe.lastIndex;
    if (m[0].startsWith("<!--")) continue;
    if (m[1]) {                                    // a closing tag: close up to its opener
      const tag = m[1].toLowerCase();
      let n = cur;
      while (n !== root && n.tag !== tag) n = n.parent;
      if (n !== root) { n._end = tagRe.lastIndex; cur = n.parent; }
      continue;
    }
    const tag = m[2].toLowerCase(), attrs = {};
    for (const a of (m[3] || "").matchAll(attrRe)) attrs[a[1]] = decode(a[2] ?? a[3] ?? a[4] ?? "");
    const el = new El(tag, attrs, cur, markup, m.index);
    cur.children.push(el);
    if (VOID.has(tag) || m[4]) { el._end = tagRe.lastIndex; continue; }
    if (RAW.has(tag)) {                            // raw text up to its own closing tag
      const close = markup.toLowerCase().indexOf("</" + tag, last);
      const stop = close === -1 ? markup.length : close;
      if (stop > last) el.children.push(markup.slice(last, stop));
      const end = close === -1 ? markup.length : markup.indexOf(">", close) + 1;
      el._end = end; tagRe.lastIndex = end; last = end;
      continue;
    }
    cur = el;
  }
  pushText(markup.slice(last));
  return root;
}

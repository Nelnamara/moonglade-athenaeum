/* mount.mjs -- MOUNT the real <LoomV2> in node, with its effects running, under a just-enough fake DOM.

   WHY THIS EXISTS. render.mjs is renderToStaticMarkup: it runs NO effects, and the repo has no
   jsdom, so no test could ask "what does the Generate drawer do when the shot changes, the panel
   opens, a commit event arrives" -- every one of those lives in a useEffect or a ref callback of
   loom/master-storyboard.jsx's LoomV2 (the drawer prefill effect, bindGenDrawer's listeners).
   This file is the smallest DOM that react-dom/client + React.act can mount into, plus
   mountLoomV2(props), which mounts the REAL component (from source, bundled by render.mjs) with
   all of its ~96 props filled in.

   NOTHING LEAVES THE PROCESS. fetch is a stub (below): GET /api/account and GET
   /api/account/prefs get a canned answer; every other request is recorded in fetchLog and
   answered 503 {error}. No PixAI call, no network, no spend.

   API
     const m = await mountLoomV2(overrides)    props to override on top of the recipe (below)
     m.node             the Generate drawer's root DOM node (prefill/payload/flushPromptEdit/...
                        hung on it, exactly what bindGenDrawer holds), or null while the right
                        panel is collapsed. A getter: it is a NEW node after every reopen.
     m.rerender(patch)  re-render with patch merged over the props so far (a key set to
                        undefined drops that override); resolves once effects have run
     m.dispatch(name, detail)  fire a bubbling CustomEvent from the drawer node, like the
                        drawer's own emit() ("mg-model-commit", "mg-dirty", ...); resolves with
                        the event once React has settled; throws if the panel is collapsed
     m.prefillCalls     every node.prefill(o) call since mount, oldest first, each a SHALLOW COPY
                        of the object the host passed (live array: read .length before and after)
     m.unmount()        unmount and remove the container (idempotent)
     -- conveniences the mounted tests all need --
     m.openPanel(tab = "Video")  click the rail button titled `tab`; resolves with the drawer node
     m.collapse()        click the panel's collapse arrow and wait out its 340 ms slide-out;
                        throws if the panel is still mounted afterwards
     m.props()          the full props object of the latest render (project, thumbs, ...)
     m.container        the root container node
   Also exported: core (loom/src/loom-core.js, from the SAME bundle as LoomV2), LoomV2, act,
   FEvent, fetchLog, storage (the window.storage shim, seed it before mounting if a test
   wants a board), installFakeDom.

   THE PROP RECIPE. LoomV2 takes ~96 props. The names are READ FROM THE SOURCE'S destructured
   signature, so a prop added later arrives as a no-op without touching this file; only a prop
   that must be a real object/array/string/number needs a line in recipeDefaults() below (a
   no-op in its place breaks the render or trips a React warning). Your overrides win. Defaults: one act with one blank shot "c1",
   selShot null (the draft card is active), thumbs {}, the five gen*State dicts {},
   projectApi {activeId:"b1"}, draftTarget "", draftAttachedInfo null, mobileUI false, batchTally null, costEstimate, spend
   {status:"loading"}, frameFix {}, imgLoras [], durOf () => 8, scale 1. Every default object is
   made ONCE per mount, so its identity is stable across re-renders.

   GOTCHAS (each one cost a verifier a wrong answer on 2026-10-25; keep them true)
   1. INSTALL THE DOM BEFORE ANYTHING LOADS react-dom/client OR THE BUNDLE. react-dom reads
      canUseDOM when it loads, and master-storyboard.jsx reads window.storage at module top
      (hasStore). This file installs the DOM as it is imported, then loads the rest. So:
      import mount.mjs FIRST in a test file, and import render.mjs / the Loom only through it
      (or after it). A static import of something that loads react-dom ahead of it is the bug.
   2. fetch MUST BE STUBBED. LoomV2 fires GET /api/account and GET /api/account/prefs on mount
      (and the price probe POSTs /api/price 250 ms after a reprice). All answered here; assert on
      fetchLog.calls / fetchLog.stray to prove nothing spent.
   3. KEEP project / assets / cast / refs IDENTITY STABLE across a re-render that is not an edit.
      The prefill effect lists project.assets and the active card's cast/refs as deps, so
      rebuilding the project object per render re-runs it by itself and MASKS the very bugs
      these tests exist to catch (the thumbs race passed on the unfixed file for exactly this
      reason). Deliver thumbs with rerender({thumbs}) alone. For a card edit do what App's
      setCard does -- a new card/act/project object that keeps the card's cast/refs arrays and
      project.assets (loom-mutations.js patchCard does) -- and pass it as rerender({project}).
      entries is memoised by project identity here for the same reason; draftCard is one
      object per mount (App holds it in useState).
   4. THE RIGHT PANEL STARTS COLLAPSED (master-storyboard.jsx rightCollapsed useState(true)), so
      m.node is null until openPanel(): the drawer is not mounted at page load. Collapsing
      unmounts it after 340 ms and reopening mounts a NEW node, which is exactly the "mount gap"
      the prefill effect has to cover. The Generate tab defaults to "Video".
   5. setCard is (actId, cardId, fn) where fn maps the old card to the new one. A no-op setCard
      (the default) writes nothing, so a test that needs the board to follow a commit passes a
      recording setCard, applies patchCard itself, and rerenders with the result.
   6. A SPY ON prefill must be on the prototype BEFORE the drawer mounts: the drawer assigns
      node.prefill once, when it first mounts (VideoDrawer's useImperativeHandle). Done at
      import here. prefillCalls is per mount (found by walking up from the node to its container).
   7. A SHOT WITH A THUMB-ONLY PICTURE needs window.getSelection, createTreeWalker, createRange,
      NodeFilter and fragment moves for the drawer's chipify; they exist below. Add any further
      DOM the next feature needs HERE, not in a test.
   8. THE DOM IS ONLY WHAT REACT AND THE LOOM TOUCH. selectors are one compound at a time
      (tag.class[attr=value], no descendant/child combinators): chain querySelector calls.
      Every size is 0 and there is no layout or CSS. A click has no default action, so a
      checkbox needs el.checked = !el.checked set BEFORE the click for React's onChange to see it;
      a text input needs el.value set, then an "input" event.
   9. act() WARNINGS FROM TIMERS (the price probe's 250 ms debounce, the account refresh's 600
      ms) land outside any act and are noise; they are filtered below. Any OTHER console.error
      is real: the recipe's no-op props have already tripped one (a function as the draft target
      select's value), fixed by giving that prop its real initial value.
  10. LOOM_SRC (repo-relative) points the mount at another copy of master-storyboard.jsx -- how
      a mutation proof runs the same test against a variant. The copy must sit inside the repo.
      The default is the real file, from source, so a test sees the working tree before any
      bundle rebuild.
*/
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";

/* ---------------------------------------------------------------------------------------------
   THE FAKE DOM. Just enough for react-dom/client to mount, run its effects and re-render.
   --------------------------------------------------------------------------------------------- */
class FEvent {
  constructor(type, init = {}) {
    this.type = type; this.bubbles = !!init.bubbles; this.cancelable = !!init.cancelable;
    this.detail = init.detail; this.target = null; this.currentTarget = null;
    this.defaultPrevented = false; this._stop = false; this.timeStamp = Date.now();
    this.eventPhase = 0; this.isTrusted = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
  stopImmediatePropagation() { this._stop = true; }
  composedPath() { const p = []; let n = this.target; while (n) { p.push(n); n = n.parentNode; } return p; }
}

class FNode {
  constructor(doc, nodeType) {
    this.ownerDocument = doc; this.nodeType = nodeType; this.parentNode = null; this.childNodes = [];
    this._l = {};
  }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; return p.childNodes[p.childNodes.indexOf(this) + 1] || null; }
  get previousSibling() { const p = this.parentNode; if (!p) return null; return p.childNodes[p.childNodes.indexOf(this) - 1] || null; }
  _detach(c) { if (c.parentNode) c.parentNode.removeChild(c); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  appendChild(c) {
    if (c.nodeType === 11) { c.childNodes.slice().forEach((k) => this.appendChild(k)); return c; }
    this._detach(c); c.parentNode = this; this.childNodes.push(c); return c;
  }
  insertBefore(c, ref) {
    if (c.nodeType === 11) { c.childNodes.slice().forEach((k) => this.insertBefore(k, ref)); return c; }
    if (!ref) return this.appendChild(c);
    this._detach(c); const i = this.childNodes.indexOf(ref);
    c.parentNode = this; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  replaceChild(n, o) { this.insertBefore(n, o); this.removeChild(o); return o; }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  get isConnected() { let n = this; while (n) { if (n === this.ownerDocument) return true; n = n.parentNode; } return false; }
  addEventListener(t, fn, opts) {
    const cap = typeof opts === "boolean" ? opts : !!(opts && opts.capture);
    (this._l[t] || (this._l[t] = [])).push({ fn, cap });
  }
  removeEventListener(t, fn, opts) {
    const cap = typeof opts === "boolean" ? opts : !!(opts && opts.capture);
    const a = this._l[t]; if (!a) return;
    const i = a.findIndex((x) => x.fn === fn && x.cap === cap); if (i >= 0) a.splice(i, 1);
  }
  dispatchEvent(ev) {
    ev.target = ev.target || this;
    const path = []; for (let n = this; n; n = n.parentNode) path.push(n);
    const call = (n, cap) => {
      for (const x of (n._l[ev.type] || []).slice()) {
        if (x.cap !== cap && !(n === ev.target)) continue;
        ev.currentTarget = n;
        typeof x.fn === "function" ? x.fn.call(n, ev) : x.fn.handleEvent(ev);
        if (ev._stop) return true;
      }
      return false;
    };
    for (let i = path.length - 1; i > 0; i--) if (call(path[i], true)) return !ev.defaultPrevented;
    if (call(path[0], false)) return !ev.defaultPrevented;
    if (ev.bubbles) for (let i = 1; i < path.length; i++) if (call(path[i], false)) break;
    return !ev.defaultPrevented;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes.slice().forEach((c) => this.removeChild(c)); if (v !== "" && v != null) this.appendChild(this.ownerDocument.createTextNode(String(v))); }
  cloneNode() { return this; }
  getRootNode() { let n = this; while (n.parentNode) n = n.parentNode; return n; }
}

class FText extends FNode {
  constructor(doc, data) { super(doc, 3); this.data = String(data); this.nodeName = "#text"; }
  get nodeValue() { return this.data; } set nodeValue(v) { this.data = String(v); }
  get textContent() { return this.data; } set textContent(v) { this.data = String(v); }
}

class FElement extends FNode {
  constructor(doc, tag, ns) {
    super(doc, 1);
    this.tagName = ns ? tag : tag.toUpperCase(); this.nodeName = this.tagName; this.localName = tag; this.namespaceURI = ns || "http://www.w3.org/1999/xhtml";
    this._a = {};
    const store = {};
    this.style = new Proxy(store, {
      get: (t, k) => (k === "setProperty" ? (n, v) => { t[n] = v; } : k === "removeProperty" ? (n) => { delete t[n]; } : k === "getPropertyValue" ? (n) => t[n] || "" : t[k] ?? ""),
      set: (t, k, v) => { t[k] = v; return true; },
    });
    this.value = ""; this.checked = false; this.disabled = false; this.selected = false;
    this.scrollTop = 0; this.scrollLeft = 0; this.contentEditable = "inherit";
    this.dataset = {};
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get id() { return this._a.id || ""; } set id(v) { this._a.id = String(v); }
  get className() { return this._a.class || ""; } set className(v) { this._a.class = String(v); }
  get classList() {
    const self = this;
    const get = () => (self._a.class || "").split(/\s+/).filter(Boolean);
    const set = (a) => { self._a.class = a.join(" "); };
    return { add: (...c) => set([...new Set([...get(), ...c])]), remove: (...c) => set(get().filter((x) => !c.includes(x))),
      contains: (c) => get().includes(c), toggle: (c, f) => { const h = get().includes(c); const w = f === undefined ? !h : f; w ? set([...new Set([...get(), c])]) : set(get().filter((x) => x !== c)); return w; } };
  }
  setAttribute(n, v) { this._a[n] = String(v); if (n === "value") this.value = String(v); }
  setAttributeNS(ns, n, v) { this._a[n] = String(v); }
  getAttribute(n) { return n in this._a ? this._a[n] : null; }
  hasAttribute(n) { return n in this._a; }
  removeAttribute(n) { delete this._a[n]; }
  removeAttributeNS(ns, n) { delete this._a[n]; }
  get attributes() { return Object.entries(this._a).map(([name, value]) => ({ name, value })); }
  get options() { return this.querySelectorAll("option"); }
  get innerHTML() { return this._html || ""; } set innerHTML(v) { this._html = String(v); this.childNodes.slice().forEach((c) => this.removeChild(c)); }
  get offsetHeight() { return 0; } get offsetWidth() { return 0; } get clientHeight() { return 0; } get clientWidth() { return 0; } get scrollHeight() { return 0; }
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }; }
  getClientRects() { return []; }
  focus() { this.ownerDocument.activeElement = this; } blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null; }
  click() { this.dispatchEvent(new FEvent("click", { bubbles: true })); }
  scrollIntoView() {} scrollTo() {} animate() { return { cancel() {}, finished: Promise.resolve() }; } getAnimations() { return []; }
  closest(sel) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n._matches(sel)) return n; return null; }
  // One compound selector (or a comma list of them): tag, .class, [attr] / [attr=value]. No combinators.
  _matches(sel) {
    return sel.split(",").some((s) => {
      s = s.trim(); if (!s) return false;
      const m = s.match(/^([a-zA-Z][\w-]*)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/); if (!m) return false;
      if (m[1] && m[1].toLowerCase() !== this.localName.toLowerCase()) return false;
      for (const c of (m[2] || "").split(".").filter(Boolean)) if (!this.classList.contains(c)) return false;
      for (const a of (m[3] || "").match(/\[[^\]]+\]/g) || []) { const [k, v] = a.slice(1, -1).split("="); if (v === undefined ? !this.hasAttribute(k) : this.getAttribute(k) !== v.replace(/^["']|["']$/g, "")) return false; }
      return true;
    });
  }
  querySelectorAll(sel) { const out = []; const w = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (c._matches(sel)) out.push(c); w(c); } }; w(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  matches(sel) { return this._matches(sel); }
  getElementsByTagName(t) { return this.querySelectorAll(t); }
}

class FFragment extends FNode { constructor(doc) { super(doc, 11); this.nodeName = "#document-fragment"; } }

class FDocument extends FNode {
  constructor() {
    super(null, 9); this.ownerDocument = null; this.nodeName = "#document"; this.activeElement = null;
    this.documentElement = new FElement(this, "html"); this.body = new FElement(this, "body"); this.head = new FElement(this, "head");
    this.documentElement.appendChild(this.head); this.documentElement.appendChild(this.body); this.appendChild(this.documentElement);
    this.readyState = "complete"; this.visibilityState = "visible"; this.hidden = false; this.cookie = "";
    this.defaultView = null; this.fonts = { ready: Promise.resolve() };
  }
  createElement(t) { return new FElement(this, t); }
  createElementNS(ns, t) { return new FElement(this, t, ns); }
  createTextNode(d) { return new FText(this, d); }
  createComment(d) { const n = new FText(this, d); n.nodeType = 8; return n; }
  createDocumentFragment() { return new FFragment(this); }
  createRange() { return { setStart() {}, setEnd() {}, collapse() {}, selectNodeContents() {}, startContainer: null }; }
  createTreeWalker(root) {
    const nodes = [];
    const w = (n) => { for (const c of n.childNodes) { if (c.nodeType === 3) nodes.push(c); else if (c.nodeType === 1) w(c); } };
    w(root);
    let i = 0;
    return { nextNode: () => nodes[i++] || null };
  }
  getElementById(id) { const f = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (c._a.id === id) return c; const r = f(c); if (r) return r; } return null; }; return f(this); }
  querySelector(s) { return this.documentElement.querySelector(s); }
  querySelectorAll(s) { return this.documentElement.querySelectorAll(s); }
  getElementsByTagName(t) { return this.documentElement.querySelectorAll(t); }
  hasFocus() { return true; }
}

/* ---------------------------------------------------------------------------------------------
   THE STUBS: fetch (nothing leaves the process) and the window.storage shim.
   --------------------------------------------------------------------------------------------- */

/** Every fetch the page made. `calls` is all of them; `stray` is the ones nothing stubs (answered
    503 {error}). A call is { url, method, path, body } -- body is the string a POST would send. */
export const fetchLog = { calls: [], stray: [] };

// The only requests the Loom's mount makes that want a real answer. Own-origin GETs only.
const STUBBED_GETS = Object.freeze({
  "/api/account": { credits: 0, cards: 0 },
  "/api/account/prefs": { csrf: "fakedom-csrf" },
});

function stubResponse(status, body) {
  return {
    ok: status >= 200 && status < 300, status, statusText: status === 200 ? "OK" : "fakedom", headers: { get: () => null },
    json: async () => body, text: async () => JSON.stringify(body), blob: async () => ({}),
    arrayBuffer: async () => new ArrayBuffer(0), clone() { return this; },
  };
}

async function stubFetch(url, init) {
  const method = String((init && init.method) || "GET").toUpperCase();
  let u;
  try { u = new URL(String(url), "http://localhost"); } catch { u = new URL("http://localhost/?bad-url"); }
  const call = { url: String(url), method, path: u.pathname, body: init && typeof init.body === "string" ? init.body : undefined };
  fetchLog.calls.push(call);
  if (method === "GET" && u.origin === "http://localhost" && Object.prototype.hasOwnProperty.call(STUBBED_GETS, u.pathname)) {
    return stubResponse(200, structuredClone(STUBBED_GETS[u.pathname]));
  }
  fetchLog.stray.push(call);
  return stubResponse(503, { error: "fakedom: " + method + " " + u.pathname + " is not stubbed" });
}

/** The page's window.storage (moonglade/gallery.py's _LOOM_SHELL shim) over a Map: get -> {value, rev}
    or {value:null, missing:true, rev:"missing"}; set(k, v, shared, {base_rev}) -> {ok, rev} or
    {conflict, value, rev}; list(prefix) -> {keys}; delete -> {ok}. `kv` is the Map (seed it). */
export function makeStorageShim() {
  const kv = new Map();   // key -> { value, rev }
  let n = 0;
  return {
    kv,
    async get(k) { const e = kv.get(k); return e ? { value: e.value, rev: e.rev } : { value: null, missing: true, rev: "missing" }; },
    async set(k, v, shared, opts) {
      const cur = kv.get(k);
      if (opts && opts.base_rev != null && opts.base_rev !== (cur ? cur.rev : "missing")) {
        return { conflict: true, value: cur ? cur.value : null, rev: cur ? cur.rev : "missing" };
      }
      const rev = "r" + (++n);
      kv.set(k, { value: v, rev });
      return { ok: true, rev };
    },
    async list(prefix) { return { keys: [...kv.keys()].filter((k) => k.startsWith(prefix || "")) }; },
    async delete(k) { kv.delete(k); return { ok: true }; },
  };
}

export function installFakeDom({ storage } = {}) {
  const doc = new FDocument();
  const g = globalThis;
  const def = (k, v) => Object.defineProperty(g, k, { value: v, configurable: true, writable: true });
  def("window", g); def("self", g); def("document", doc); doc.defaultView = g;
  const mem = new Map();
  def("localStorage", { getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => { mem.set(k, String(v)); }, removeItem: (k) => { mem.delete(k); }, clear: () => mem.clear(), key: (i) => [...mem.keys()][i] ?? null, get length() { return mem.size; } });
  def("sessionStorage", g.localStorage);
  const wl = new FNode(null, 0); // window-level listener registry
  def("addEventListener", (...a) => wl.addEventListener(...a)); def("removeEventListener", (...a) => wl.removeEventListener(...a));
  def("dispatchEvent", (e) => wl.dispatchEvent(e));
  def("Event", FEvent); def("CustomEvent", FEvent); def("MouseEvent", FEvent); def("KeyboardEvent", FEvent);
  for (const k of ["HTMLElement", "HTMLIFrameElement", "HTMLInputElement", "HTMLTextAreaElement", "HTMLSelectElement", "HTMLImageElement", "SVGElement", "Element", "Node", "Text", "HTMLVideoElement", "HTMLCanvasElement", "ShadowRoot"]) def(k, class {});
  def("HTMLElement", FElement); def("Element", FElement); def("Node", FNode);
  def("getSelection", () => ({ rangeCount: 0, getRangeAt() { return null; }, removeAllRanges() {}, addRange() {}, toString() { return ""; } }));
  def("NodeFilter", { SHOW_ALL: -1, SHOW_ELEMENT: 1, SHOW_TEXT: 4 });
  def("getComputedStyle", () => new Proxy({}, { get: (t, k) => (k === "getPropertyValue" ? () => "" : "") }));
  def("matchMedia", (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
  def("requestAnimationFrame", (fn) => setTimeout(() => fn(Date.now()), 0)); def("cancelAnimationFrame", (id) => clearTimeout(id));
  def("requestIdleCallback", (fn) => setTimeout(() => fn({ timeRemaining: () => 10, didTimeout: false }), 0)); def("cancelIdleCallback", (id) => clearTimeout(id));
  for (const k of ["ResizeObserver", "IntersectionObserver", "MutationObserver"]) def(k, class { constructor() {} observe() {} unobserve() {} disconnect() {} takeRecords() { return []; } });
  def("innerWidth", 1440); def("innerHeight", 900); def("devicePixelRatio", 1); def("scrollX", 0); def("scrollY", 0);
  def("scrollTo", () => {}); def("open", () => null); def("alert", () => {}); def("confirm", () => true); def("prompt", () => null);
  def("location", { href: "http://localhost/loom", origin: "http://localhost", pathname: "/loom", search: "", hash: "", host: "localhost", hostname: "localhost", protocol: "http:", assign() {}, replace() {}, reload() {} });
  def("history", { pushState() {}, replaceState() {}, back() {}, forward() {}, state: null });
  Object.defineProperty(g, "navigator", { value: { userAgent: "node-fakedom", platform: "Win32", language: "en-US", languages: ["en-US"], maxTouchPoints: 0, onLine: true, clipboard: { writeText: async () => {} } }, configurable: true, writable: true });
  def("fetch", stubFetch);
  def("Image", class { constructor() { this.onload = null; this.onerror = null; } set src(v) { this._s = v; } get src() { return this._s; } });
  if (!g.URL.createObjectURL) g.URL.createObjectURL = () => "blob:fake";
  if (!g.URL.revokeObjectURL) g.URL.revokeObjectURL = () => {};
  def("IS_REACT_ACT_ENVIRONMENT", true);
  if (storage) def("storage", storage);
  return { doc, g };
}

export { FEvent, FElement, FText };

/* ---------------------------------------------------------------------------------------------
   INSTALL, THEN LOAD (gotcha 1: this order is the point).
   --------------------------------------------------------------------------------------------- */
export const storage = makeStorageShim();
const dom = installFakeDom({ storage });

// Timer-driven updates land outside act(); React says so on console.error. Drop only that line.
const realConsoleError = console.error;
console.error = (...a) => {
  if (typeof a[0] === "string" && /not wrapped in act|inside a test was not/.test(a[0])) return;
  realConsoleError(...a);
};

// The spy (gotcha 6): every node.prefill = fn assignment is wrapped. The call goes to the
// mount whose container is an ancestor of the node; anything else lands in `orphanPrefills`.
const orphanPrefills = [];
Object.defineProperty(FElement.prototype, "prefill", {
  configurable: true,
  set(fn) {
    this._prefill = (o) => {
      let n = this;
      while (n && !n._prefillSink) n = n.parentNode;
      (n ? n._prefillSink : orphanPrefills).push({ ...o });
      return fn(o);
    };
  },
  get() { return this._prefill; },
});

const { loadModules, LOOM_MOCKS, LOOM_DIR, REPO_ROOT } = await import("./render.mjs");
const loomRequire = createRequire(path.join(LOOM_DIR, "package.json"));
const React = loomRequire("react");
const { createRoot } = loomRequire("react-dom/client");
const { createElement: h, act } = React;

const SRC = process.env.LOOM_SRC || "loom/master-storyboard.jsx";
const [sb, core] = await loadModules([SRC, "loom/src/loom-core.js"], { mocks: LOOM_MOCKS });
export { core, act, h };
export const LoomV2 = sb.LoomV2;
if (typeof LoomV2 !== "function") throw new Error("mount.mjs: " + SRC + " has no top-level LoomV2 component");

// LoomV2's prop names, off its destructured signature (gotcha: new props arrive as no-ops).
function loomPropNames() {
  const src = readFileSync(path.resolve(REPO_ROOT, SRC), "utf8");
  const head = "function LoomV2({";
  const i0 = src.indexOf(head);
  if (i0 < 0) throw new Error("mount.mjs: could not find `" + head + "` in " + SRC);
  const body = src.slice(i0 + head.length, src.indexOf("}) {", i0 + head.length)).replace(/\/\/[^\n]*/g, "");
  const names = body.split(",").map((s) => s.trim()).filter(Boolean);
  const bad = names.filter((n) => !/^[A-Za-z_$][\w$]*$/.test(n));
  if (bad.length || names.length < 50) {
    throw new Error("mount.mjs: LoomV2's signature no longer parses as a plain name list (" + (bad[0] || names.length + " names") + ")");
  }
  return names;
}
const PROP_NAMES = loomPropNames();
const noop = () => {};

// The props that are not a no-op. Made ONCE per mount (identity stays stable across renders).
function recipeDefaults() {
  const card = core.newCardShape("c1", { title: "Shot one" });
  return {
    project: { name: "T", target: 480, look: "", draft: false, assets: [],
      acts: [{ id: "act1", name: "Act 1", collapsed: false, cards: [card] }] },
    thumbs: {}, selShot: null,
    genState: {}, genImgState: {}, genEditState: {}, genRefState: {}, genFixState: {},
    projectApi: { activeId: "b1" }, draftCard: core.newCardShape("__draft__"), draftTarget: "", draftAttachedInfo: null,
    mobileUI: false, batchTally: null, costEstimate: { ...core.tallyPrices([]), pending: 0, notDoneCount: 0 },
    spend: { status: "loading" }, batching: false, bundling: false, frameFix: {},
    imgLoras: [], imgAdv: {}, modelDefaults: {}, imgModel: "", scale: 1, durOf: () => 8,
  };
}

/* ---------------------------------------------------------------------------------------------
   mountLoomV2
   --------------------------------------------------------------------------------------------- */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const RIGHT_PANEL_CLOSE_MS = 340;   // master-storyboard.jsx closeRightPanel's slide-out timer

export async function mountLoomV2(overrides = {}) {
  const container = dom.doc.createElement("div");
  dom.doc.body.appendChild(container);
  const prefillCalls = [];
  container._prefillSink = prefillCalls;
  const root = createRoot(container);
  const defaults = recipeDefaults();
  const over = {};
  let entriesFor = null, entries = null;
  let live = true;

  const apply = (patch) => {
    for (const [k, v] of Object.entries(patch || {})) { if (v === undefined) delete over[k]; else over[k] = v; }
  };
  const build = () => {
    const props = {};
    for (const n of PROP_NAMES) props[n] = noop;
    Object.assign(props, defaults, over);
    if (!("entries" in over)) {
      if (entriesFor !== props.project) { entriesFor = props.project; entries = core.flat(props.project); }
      props.entries = entries;
    }
    return props;
  };
  let latest = null;
  const render = async () => {
    if (!live) throw new Error("mountLoomV2: already unmounted");
    latest = build();
    await act(async () => { root.render(h(LoomV2, latest)); });
  };

  const drawerNode = () => {
    let hit = null;
    const walk = (n) => { for (const c of n.childNodes) { if (c.nodeType !== 1 || hit) continue; if (typeof c.prefill === "function") { hit = c; return; } walk(c); } };
    walk(container);
    return hit;
  };
  const findAll = (sel) => container.querySelectorAll(sel);

  const api = {
    container, prefillCalls,
    get node() { return drawerNode(); },
    props: () => latest,
    async rerender(patch) { apply(patch); await render(); },
    async dispatch(name, detail) {
      const n = drawerNode();
      if (!n) throw new Error("mountLoomV2.dispatch: no drawer node -- the right panel is collapsed (openPanel() first)");
      const ev = new FEvent(name, { bubbles: true, detail: detail || {} });
      await act(async () => { n.dispatchEvent(ev); });
      return ev;
    },
    async openPanel(tab = "Video") {
      const btn = findAll(".lv-railbtn").find((b) => b.getAttribute("title") === tab);
      if (!btn) throw new Error("mountLoomV2.openPanel: no rail button titled " + tab);
      await act(async () => { btn.dispatchEvent(new FEvent("click", { bubbles: true })); });
      return drawerNode();
    },
    async collapse() {
      const panel = findAll(".lv-panel").find((p) => p.classList.contains("right"));
      const arrow = panel && panel.querySelector(".lv-col");
      if (!arrow) throw new Error("mountLoomV2.collapse: the right panel is not open");
      await act(async () => { arrow.dispatchEvent(new FEvent("click", { bubbles: true })); await sleep(RIGHT_PANEL_CLOSE_MS + 60); });
      if (drawerNode()) throw new Error("mountLoomV2.collapse: the drawer is still mounted " + (RIGHT_PANEL_CLOSE_MS + 60) + " ms after the collapse click");
    },
    async unmount() {
      if (!live) return;
      live = false;
      await act(async () => { root.unmount(); });
      container.remove();
    },
  };
  apply(overrides);
  await render();
  return api;
}

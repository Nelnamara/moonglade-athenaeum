import { test, describe, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadModules, renderElement, query, one, decode, LOOM_MOCKS } from "../test-support/render.mjs";
import {
  cardsToResume, flat, newCardShape, emptyFrameShape, isCatalogMediaId, positionTag, refBudget, shotText,
  shotPayload, tallyPrices, formatCostEstimate, costTooltip, CONNECT,
} from "../src/loom-core.js";
import {
  patchCard, patchAssets, setShotMode, setShotConnect, clearPromptOverride, buildNewRef,
  buildImgGenBody, resolveGenDims, genStepFor,
} from "../src/loom-mutations.js";
import { emptyFrameFix } from "../src/loom-frames-core.js";
import { LOOM_VIEW_KEY } from "../src/loom-url.js";
import { FIX_COLORS, FIX_MIN_PX, FIX_MAX_BOXES, scaleBoxes } from "../../gallery/src/gen/editCore.js";

/* LOOM MOBILE, RENDERED (the phone board/reel view in loom/master-storyboard.jsx, its wiring in
   App(), and the Mobile-view switch on both sides).

   Until 2026-10 every test here regexed the .jsx SOURCE, because nothing could render a
   component under `node --test`. Now the render helper (loom/test-support/render.mjs) bundles
   the real file, and each test renders the real component and asserts on what it shows and
   what its handlers call.

   THE HOOKS HARNESS (`mount`, below). Almost every phone screen sits behind the component's own
   state -- Shot Detail behind dfOpen, Generate behind genOpen, Review behind reviewOpen, the
   kebab sheet behind actionsOpen -- which a plain static render never sets. So `mount` calls the
   component function itself under a small test dispatcher (React 18's hooks dispatcher slot,
   which is what a shallow renderer does) and:
     - can START a piece of state at a given value, named as the source declares it
       (`state: { dfOpen: true }` for `const [dfOpen, setDfOpen] = useState(false)`; the name is
       read off the hook's call-site line through the bundle's source map), and likewise a ref
       (`refs: { fixImgRef: fakeImg }`), since no DOM ever attaches one;
     - keeps the real handlers on the element tree, so a test clicks them and sees what they call;
     - re-renders on a state change the way React does (a setState during render re-runs the
       component; one from a handler marks it stale and the next act() re-renders);
     - runs effects only when a test asks (`flush()`), so a render on its own spends and polls
       nothing, exactly like the helper's static render.
   The static markup a test reads comes from the helper's renderElement over that tree, so every
   nested component (FrameSlot, ModelPicker, RibbonStrip, ...) renders for real.

   KEPT AS SOURCE PINS, on purpose (each says so): a handful of spend and delete guards whose
   whole point is where a line sits in the code or that a second, parallel path does NOT exist
   -- an absent call has no render to show. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SB_PATH = path.join(__dirname, "../master-storyboard.jsx");
const src = readFileSync(SB_PATH, "utf8");

// The kept source pins slice LoomMobile's own source out by a landmark, so a negative check can
// never match LoomV2's own copy elsewhere in the same file.
const mobileStart = src.indexOf("function LoomMobile({");
const mobileEnd = src.indexOf("COMPOSED HOOKS (Phase 2", mobileStart);
assert.ok(mobileStart > 0, "expected to find LoomMobile's function declaration");
assert.ok(mobileEnd > mobileStart, "expected to find the COMPOSED HOOKS banner after LoomMobile");
const loomMobileSrc = src.slice(mobileStart, mobileEnd);

/* ---------- the real bundle: the Loom, plus two modules it imports (one bundle, one instance) ---------- */

const [SB, MP, ARTF] = await loadModules(
  ["loom/master-storyboard.jsx", "gallery/src/components/ModelPicker.jsx", "gallery/src/art/artFilters.js"],
  { mocks: LOOM_MOCKS });
const { LoomMobile, LoomV2, ProjectSwitcher, FrameSlot, MODES, LOOM_MOBILE_STYLES } = SB;
const App = SB.default;
const ModelPicker = MP.default;
const AF = ARTF.default;

/* ---------- the hooks harness ---------- */

const loomRequire = createRequire(path.join(__dirname, "../package.json"));
const React = loomRequire("react");   // the same copy the bundle and react-dom/server use
const DISPATCHER = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
assert.ok(DISPATCHER && "current" in DISPATCHER, "React 18's hooks dispatcher slot moved -- the harness needs updating");
const SB_LINES = src.split(/\r?\n/);

// The source line of the hook call that created a slot: the stack frame just past React's own
// useState/useRef/useEffect frame, mapped back to master-storyboard.jsx by the bundle's source map.
function hookLine(err) {
  const frames = String(err.stack).split("\n").filter((l) => /^\s+at /.test(l));
  const i = frames.findIndex((l) => /[\\/]node_modules[\\/]react[\\/]/.test(l));
  const m = i >= 0 && frames[i + 1] ? /master-storyboard\.jsx:(\d+):\d+\)?\s*$/.exec(frames[i + 1]) : null;
  return m ? +m[1] : 0;
}
const stateNameAt = (line) => { const m = /const \[\s*(\w+)\s*,/.exec(SB_LINES[line - 1] || ""); return m ? m[1] : null; };
const refNameAt = (line) => { const m = /const (\w+)\s*=\s*useRef\(/.exec(SB_LINES[line - 1] || ""); return m ? m[1] : null; };
const sameDeps = (a, b) => !!a && !!b && a.length === b.length && a.every((x, i) => Object.is(x, b[i]));
const has = (o, k) => !!k && Object.prototype.hasOwnProperty.call(o, k);

function mount(Component, props, { state = {}, refs = {} } = {}) {
  const slots = [];
  let cursor = 0, rendering = false, dirty = false, pending = [];
  const h = { props, tree: null, stale: false, names: [] };
  const slot = (make) => { const i = cursor++; if (!slots[i]) slots[i] = make(); return slots[i]; };
  const dispatcher = {
    useReducer(reducer, initArg, init, isState) {
      const err = new Error();
      const s = slot(() => {
        const name = stateNameAt(hookLine(err));
        h.names.push(name);
        const value = has(state, name) ? state[name]
          : isState ? (typeof initArg === "function" ? initArg() : initArg) : (init ? init(initArg) : initArg);
        const st = { kind: "state", name, value };
        st.dispatch = (action) => {
          const next = st.isState ? (typeof action === "function" ? action(st.value) : action) : st.reducer(st.value, action);
          if (Object.is(next, st.value)) return;
          st.value = next;
          if (rendering) dirty = true; else h.stale = true;
        };
        return st;
      });
      s.reducer = reducer; s.isState = !!isState;
      return [s.value, s.dispatch];
    },
    useState(init) { return dispatcher.useReducer(null, init, undefined, true); },
    useRef(init) {
      const err = new Error();
      return slot(() => { const name = refNameAt(hookLine(err)); return { current: has(refs, name) ? refs[name] : init }; });
    },
    useMemo(fn, deps) {
      const s = slot(() => ({ deps: null, value: undefined }));
      if (!deps || !sameDeps(s.deps, deps)) { s.value = fn(); s.deps = deps; }
      return s.value;
    },
    useCallback(fn, deps) { return dispatcher.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const err = new Error();
      const s = slot(() => ({ kind: "effect", deps: undefined, ran: false, cleanup: null, err }));
      pending.push({ s, fn, deps });
    },
    useLayoutEffect(fn, deps) { dispatcher.useEffect(fn, deps); },
    useInsertionEffect(fn, deps) { dispatcher.useEffect(fn, deps); },
    useContext(ctx) { return ctx._currentValue; },
    useId() { return slot(() => ({ id: ":h" + cursor + ":" })).id; },
    useSyncExternalStore(subscribe, getSnapshot) { return getSnapshot(); },
    useTransition() { return [false, (cb) => cb()]; },
    useDeferredValue(v) { return v; },
    useImperativeHandle() { slot(() => ({})); },
    useDebugValue() {},
  };
  /** Render (again), with new props if given. A setState during render re-runs it, like React. */
  h.render = (next) => {
    if (next) h.props = next;
    let n = 0;
    do {
      if (++n > 50) throw new Error("too many re-renders");
      dirty = false; cursor = 0; pending = [];
      rendering = true;
      const prev = DISPATCHER.current;
      DISPATCHER.current = dispatcher;
      try { h.tree = Component(h.props); } finally { DISPATCHER.current = prev; rendering = false; }
    } while (dirty);
    h.stale = false;
    return h.tree;
  };
  /** Run the last render's effects whose deps changed (all on the first call), then re-render if
      they set state. `at` limits it to effects whose call line matches the RegExp. */
  h.flush = (at) => {
    for (const { s, fn, deps } of pending) {
      if (s.ran && deps && sameDeps(s.deps, deps)) continue;
      if (at && !at.test(SB_LINES[hookLine(s.err) - 1] || "")) continue;
      if (typeof s.cleanup === "function") s.cleanup();
      s.cleanup = fn(); s.deps = deps; s.ran = true;
    }
    if (h.stale) h.render();
  };
  h.unmount = () => { for (const s of slots) if (s && s.kind === "effect" && typeof s.cleanup === "function") s.cleanup(); };
  h.stateSlots = (name) => slots.filter((x) => x && x.kind === "state" && x.name === name);
  h.state = (name) => one(h.stateSlots(name), "state named " + name).value;
  h.setter = (name) => one(h.stateSlots(name), "state named " + name).dispatch;
  h.setProps = (patch) => { h.props = { ...h.props, ...patch }; h.stale = true; };
  /** Run fn (a handler call), then re-render if it changed anything. */
  h.act = (fn) => { const r = fn(); if (h.stale) h.render(); return r; };
  h.fire = (el, handler, ev) => h.act(() => el.props[handler](ev || event()));
  h.click = (el, ev) => h.fire(el, "onClick", ev);
  h.render();
  return h;
}

/* ---------- reading the tree ---------- */

/** Every element below `node`, in order -- children and elements handed in other props alike. */
function els(node, out = []) {
  if (node == null || typeof node === "boolean") return out;
  if (Array.isArray(node)) { for (const n of node) els(n, out); return out; }
  if (typeof node !== "object" || !node.$$typeof) return out;
  out.push(node);
  for (const [k, v] of Object.entries(node.props || {})) {
    if (k === "children" || (v && typeof v === "object" && (Array.isArray(v) || v.$$typeof))) els(v, out);
  }
  return out;
}
const textOf = (n) => (n == null || typeof n === "boolean" ? "" : typeof n === "string" || typeof n === "number" ? String(n)
  : Array.isArray(n) ? n.map(textOf).join("") : n.props ? textOf(n.props.children) : "");
const tree = (x) => (x && x.tree !== undefined ? x.tree : x);
const classOf = (e) => (typeof e.props.className === "string" ? e.props.className.split(/\s+/) : []);
const cls = (x, c) => els(tree(x)).filter((e) => classOf(e).includes(c));
const btns = (x, label) => els(tree(x)).filter((e) => e.type === "button"
  && (label instanceof RegExp ? label.test(textOf(e)) : textOf(e).includes(label)));
const btn = (x, label) => one(btns(x, label), "button " + label);
const ofType = (x, type) => els(tree(x)).filter((e) => e.type === type);
/** The static markup of what the harness rendered, parsed for queries. */
const markup = (x) => query(renderElement(tree(x)));
const event = (extra = {}) => ({
  button: 0, pointerId: 1, clientX: 0, clientY: 0,
  stopPropagation() { this.stopped = true; }, preventDefault() {},
  target: {}, currentTarget: { setPointerCapture() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) },
  ...extra,
});
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
const near = (a, b, what) => assert.ok(Math.abs(a - b) < 1e-9, (what || "value") + ": " + a + " is not " + b);

/* ---------- a stand-in browser: storage, confirm/alert, and a recording fetch ---------- */

const browser = { store: new Map(), trail: [], answer: false, alerts: [], reply: () => ({}) };
const realFetch = globalThis.fetch;
before(() => {
  const ls = {
    getItem: (k) => (browser.store.has(k) ? browser.store.get(k) : null),
    setItem: (k, v) => { browser.store.set(k, String(v)); },
    removeItem: (k) => { browser.store.delete(k); },
  };
  globalThis.window = {
    localStorage: ls, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    addEventListener() {}, removeEventListener() {},
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    location: { search: "", pathname: "/loom", href: "http://127.0.0.1/loom", reload() {} },
    history: { replaceState() {}, pushState() {} },
    confirm: (text) => { browser.trail.push(["confirm", text]); return browser.answer; },
  };
  globalThis.localStorage = ls;
  globalThis.document = { body: { style: {} }, documentElement: {}, querySelector: () => null, addEventListener() {}, removeEventListener() {} };
  globalThis.alert = (text) => { browser.alerts.push(text); };
  globalThis.fetch = async (url, init) => {
    const body = init && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    browser.trail.push(["fetch", String(url), body]);
    const reply = browser.reply(String(url), body);
    return { ok: true, status: 200, json: async () => { if (reply instanceof Error) throw reply; return reply; } };
  };
});
after(() => {
  delete globalThis.window; delete globalThis.localStorage; delete globalThis.document; delete globalThis.alert;
  globalThis.fetch = realFetch;
});
beforeEach(() => {
  browser.store.clear(); browser.trail = []; browser.answer = false; browser.alerts = []; browser.reply = () => ({});
  window.Toast = undefined; window.MG_LORA = undefined;
  document.body.style = {};
});
const fetched = (route) => browser.trail.filter((x) => x[0] === "fetch" && x[1].split("?")[0] === route);

/* ---------- fixtures ---------- */

const MID = { open1: "100001", res2: "200002", her: "300001" };
const frame = (extra = {}) => ({ ...emptyFrameShape(), ...extra });
// One three-shot act (R2V with a frame and a cast member, a rendered I2V, an empty FLF) and one empty act.
function makeBoard(cards = {}) {
  return {
    name: "Test board", target: 30, look: "", draft: false,
    assets: [
      { id: "as1", name: "Her", kind: "image", tag: "@image1", thumbId: "", source: "", mediaId: MID.her, lock: true },
      { id: "as2", name: "The room", kind: "image", tag: "@image2", thumbId: "", source: "", lock: false },
      { id: "as3", name: "The song", kind: "audio", tag: "@audio1", thumbId: "", source: "", lock: false },
    ],
    acts: [
      { id: "a1", name: "Act 1 — Setup", collapsed: false, cards: [
        newCardShape("c1", { title: "Arrival", mode: "R2V", duration: 4, prompt: "she walks in", cast: ["as1"],
          openFrame: frame({ mediaId: MID.open1 }), ...cards.c1 }),
        newCardShape("c2", { title: "Doorway", mode: "I2V", duration: 6, status: "done", resultMid: MID.res2, ...cards.c2 }),
        newCardShape("c3", { title: "", mode: "FLF", duration: 2, ...cards.c3 }),
      ] },
      { id: "a2", name: "Act 2 — Turn", collapsed: false, cards: [] },
    ],
  };
}
// The component's own picture resolver (LoomMobile's imgSrc), for computing what it should show.
const imgSrcOf = (thumbs) => (thumbId, source) => (thumbId ? thumbs[thumbId]
  : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null));
// useGenerationPipeline's own starting Image-tab settings.
const IMG_ADV = {
  negative: "", steps: 25, cfg: 7, aspectW: 1, aspectH: 1, size: 1024, customW: "", customH: "",
  mode: "auto", count: 1, seed: "", highPriority: false, promptHelper: true,
};
const PHONE_FNS = ["addCard", "addAct", "setDraft", "addRef", "setRef", "delRef", "storeThumb", "openPick", "copyShot",
  "selectTakeOnCard", "deleteTakeOnCard", "reuseTakeSettings", "reanchorShot", "keepAnchor", "splitShot",
  "moveCard", "dupCard", "delCard", "setMobileUI", "setDraftCard", "setDraftTarget", "setDraftAttachedInfo",
  "generateShot", "useExistingVideo", "recheckSubmit", "releaseSubmit", "setImgModel", "setImgLoras", "setImgAdv",
  "setModelDefaults", "genImage", "routeImg", "setGenEditState", "setGenRefState", "genEdit", "genRef", "routeGen",
  "setGenFixState", "genFix"];

/** LoomMobile on `board`, with every function prop a recorder (h.calls(name)). setSelShot, setCard
    and setAssets behave like App's: they change the props the next render gets. */
function phone({ board = makeBoard(), sel = null, state = {}, refs = {}, props = {} } = {}) {
  const log = [];
  let h = null;
  const p = {
    project: board, entries: flat(board), thumbs: {}, frameFix: emptyFrameFix(), genState: {}, selShot: sel,
    anchorWork: {}, activeId: "b1", mobileUI: true, draftCard: null, draftTarget: "", draftAttachedInfo: null,
    genImgState: {}, imgModel: null, imgLoras: [], imgAdv: IMG_ADV, modelDefaults: null,
    genEditState: {}, genRefState: {}, genFixState: {},
  };
  for (const n of PHONE_FNS) p[n] = (...args) => { log.push([n, ...args]); };
  const setBoard = (next) => h.setProps({ project: next, entries: flat(next) });
  p.setSelShot = (id) => { log.push(["setSelShot", id]); h.setProps({ selShot: id }); };
  p.setCard = (a, c, fn) => { log.push(["setCard", a, c, fn]); setBoard(patchCard(h.props.project, a, c, fn)); };
  p.setAssets = (fn) => { log.push(["setAssets", fn]); setBoard(patchAssets(h.props.project, fn)); };
  p.priceShot = (entry) => { log.push(["priceShot", entry]); return new Promise(() => {}); };
  Object.assign(p, props);
  h = mount(LoomMobile, p, { state, refs });
  h.calls = (name) => log.filter((x) => x[0] === name).map((x) => x.slice(1));
  h.entry = (id) => h.props.entries.find((e) => e.c.id === id);
  h.card = (id) => h.entry(id).c;
  return h;
}

/** App() on `board`, opened in `view` ("mobile" | "desktop"), its store already loaded. */
function app({ board = makeBoard(), view = "mobile" } = {}) {
  browser.store.set(LOOM_VIEW_KEY, view);
  return mount(App, {}, { state: { project: board, activeId: "b1" }, refs: { projectRef: board, activeIdRef: "b1" } });
}
const viewOf = (h) => one(els(h.tree).filter((e) => e.type === LoomMobile || e.type === LoomV2), "Loom view");
const boardOf = (h) => h.state("project");

/* ======================================================================================== */

describe("LoomMobile exists as a real component, inline (matching this file's own convention)", () => {
  test("LoomMobile renders a real phone board: top bar, reel, and every act with its shots", () => {
    const $ = markup(phone());
    const root = one($.byClass("lm-root"), "phone root");
    assert.equal(root.parent.tag, "#root", "the phone root is what LoomMobile returns");
    assert.equal(one(root.byClass("lm-title")).text, "▪ The Loom");
    assert.equal(one(root.byClass("lm-reelbar")).byClass("lm-seg").length, 3);
    assert.deepEqual(root.byClass("lm-actname").map((e) => e.text), ["Act 1 — Setup", "Act 2 — Turn"]);
    assert.deepEqual(root.byClass("lm-actcount").map((e) => e.text), ["3 shots", "0 shots"]);
    assert.deepEqual(root.byClass("lm-code").map((e) => e.text), ["A·01", "A·02", "A·03"]);
    assert.equal(one(root.byClass("lm-empty")).text, "No shots yet — tap + Shot.");
  });

  test("its own styles are defined and actually injected", () => {
    assert.match(LOOM_MOBILE_STYLES, /\.lm-root\s*\{/);
    const style = markup(phone()).byTag("style")[0];
    assert.equal(style.parent.attr("class"), "lm-root", "the phone styles ride inside the phone root");
    // react-dom escapes a <style>'s text like any text node (' -> &#x27;); the query layer keeps it raw.
    assert.equal(decode(style.text), LOOM_MOBILE_STYLES);
  });

  test("locks the body scroll while mounted, and gives it back on unmount", () => {
    document.body.style.overflow = "auto";
    const h = phone();
    assert.equal(document.body.style.overflow, "auto", "a render alone changes nothing");
    h.flush();
    assert.equal(document.body.style.overflow, "hidden");
    h.unmount();
    assert.equal(document.body.style.overflow, "auto");
  });
});

describe("the Mobile-view toggle: a persisted, manual owner-preference switch on both views", () => {
  // The hook behind it (useLoomView over loom-url.js's LOOM_VIEW_KEY) and its auto-open half are
  // tested in loom-phone-auto-open.test.js; here the two switches are driven for real.
  test("the Mobile-view switch is a row in LoomV2's storyboards popover, and it flips the view", () => {
    const h = app({ view: "desktop" });
    const v2 = mount(LoomV2, viewOf(h).props);
    const sw = one(ofType(v2, ProjectSwitcher), "ProjectSwitcher in LoomV2's bar");
    const row = sw.props.extra;
    assert.equal(row.type, "label");
    assert.deepEqual(classOf(row), ["sb-projrow"], "desktop view: the row is not ticked");
    assert.match(textOf(row), /Mobile view/);
    const box = one(ofType(row, "input"));
    assert.equal(box.props.type, "checkbox");
    assert.equal(box.props.checked, false);
    // No second Mobile-view control anywhere else in the desktop view.
    const inRow = new Set(els(row));
    const elsewhere = els(v2.tree).filter((e) => !inRow.has(e) && (e.type === "label" || e.type === "button")
      && /Mobile view/.test(textOf(e)));
    assert.deepEqual(elsewhere.map((e) => e.type), [], "the Mobile-view switch is back in the bar itself");
    // The popover draws the host's row under + New / Duplicate.
    const $ = query(renderElement(React.createElement(ProjectSwitcher, { ...sw.props, api: { ...sw.props.api, projMenu: true } })));
    const pop = one($.byClass("sb-projpop"));
    const kids = pop.children.filter((c) => typeof c !== "string");
    assert.deepEqual(kids.map((c) => c.attr("class")), ["sb-projpoph", "sb-projlist", "sb-projacts", "sb-projrow"]);
    // Ticking it is a real, persisted flip to the phone view.
    box.props.onChange({ target: { checked: true } });
    assert.equal(browser.store.get(LOOM_VIEW_KEY), "mobile");
    h.render();
    assert.equal(viewOf(h).type, LoomMobile);
  });

  test("App() actually renders ONE of LoomMobile / LoomV2, gated on the stored choice, and both switches flip it", () => {
    const h = app({ view: "mobile" });
    assert.equal(ofType(h, LoomMobile).length, 1);
    assert.equal(ofType(h, LoomV2).length, 0);
    // LoomMobile's own Desktop chip is the way back (never a one-way trap).
    const phoneView = mount(LoomMobile, viewOf(h).props);
    phoneView.click(btn(phoneView, "Desktop"));
    assert.equal(browser.store.get(LOOM_VIEW_KEY), "desktop");
    h.render();
    assert.equal(ofType(h, LoomMobile).length, 0);
    assert.equal(ofType(h, LoomV2).length, 1);
    // A stored "desktop" choice opens desktop.
    const d = app({ view: "desktop" });
    assert.deepEqual([ofType(d, LoomMobile).length, ofType(d, LoomV2).length], [0, 1]);
  });
});

describe("draftCard/draftTarget/draftAttachedInfo: lifted from LoomV2 to App(), unchanged behavior", () => {
  const TRIO = ["draftCard", "draftTarget", "draftAttachedInfo"];
  const SETTERS = ["setDraftCard", "setDraftTarget", "setDraftAttachedInfo"];

  test("each of the three is ONE piece of state, held by App(); neither view keeps a copy of its own", () => {
    const h = app({ view: "mobile" });
    for (const n of TRIO) assert.equal(h.stateSlots(n).length, 1, n + " is held once in App()'s tree");
    const phoneView = mount(LoomMobile, viewOf(h).props);
    const d = app({ view: "desktop" });
    const desk = mount(LoomV2, viewOf(d).props);
    // (The harness does read both views' state names: their own state is there.)
    assert.ok(phoneView.names.includes("dfOpen") && desk.names.includes("deepFocus") && desk.names.includes("tab"));
    for (const n of TRIO) {
      assert.ok(!phoneView.names.includes(n), "LoomMobile declares its own " + n);
      assert.ok(!desk.names.includes(n), "LoomV2 declares its own " + n);
    }
  });

  test("App() starts the trio as the blank draft, keyed __draft__", () => {
    const h = app();
    assert.equal(h.state("draftCard").id, "__draft__");
    assert.equal(h.state("draftTarget"), "");
    assert.equal(h.state("draftAttachedInfo"), null);
  });

  test("LoomV2 receives App's own trio and setters as props", () => {
    const h = app({ view: "desktop" });
    const p = viewOf(h).props;
    TRIO.forEach((n, i) => {
      assert.equal(p[n], h.state(n), n);
      assert.equal(p[SETTERS[i]], h.setter(n), SETTERS[i]);
    });
  });

  test("LoomMobile receives the SAME trio and setters (threaded for the phone's Generate)", () => {
    const h = app({ view: "mobile" });
    const p = viewOf(h).props;
    TRIO.forEach((n, i) => {
      assert.equal(p[n], h.state(n), n);
      assert.equal(p[SETTERS[i]], h.setter(n), SETTERS[i]);
    });
  });

  test("a draft set on one view is the draft the other view gets after a switch", () => {
    const h = app({ view: "mobile" });
    const p = viewOf(h).props;
    const draft = { ...p.draftCard, prompt: "a lantern sways" };
    h.act(() => { p.setDraftCard(draft); p.setDraftTarget("c2"); p.setDraftAttachedInfo({ mid: "9", code: "A·02" }); });
    p.setMobileUI(false);
    h.render();
    const q = viewOf(h);
    assert.equal(q.type, LoomV2);
    assert.equal(q.props.draftCard, draft);
    assert.equal(q.props.draftTarget, "c2");
    assert.deepEqual(q.props.draftAttachedInfo, { mid: "9", code: "A·02" });
  });
});

describe("the reel's pointer-drag scrub: real fraction-of-width math, no gesture library", () => {
  // The reel bar sits at x=100..700 on screen; the board's shots run 4 s, 6 s and 2 s (12 s).
  const bar = (h) => one(cls(h, "lm-reelbar"), "reel bar");
  const at = (frac, extra = {}) => event({
    pointerId: 7, clientX: 100 + 600 * frac,
    currentTarget: { getBoundingClientRect: () => ({ left: 100, width: 600 }), setPointerCapture() {} }, ...extra,
  });

  test("the reel bar's pointer handlers drive a whole scrub: down starts it, move follows, up selects, leave cancels", () => {
    const h = phone();
    h.fire(bar(h), "onPointerDown", at(0.25));
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·01");
    h.fire(bar(h), "onPointerMove", at(0.9));
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·03");
    h.fire(bar(h), "onPointerUp");
    assert.deepEqual(h.calls("setSelShot"), [["c3"]]);
    assert.equal(cls(h, "lm-preview").length, 0);
    // Leaving the bar mid-drag cancels without selecting anything.
    h.fire(bar(h), "onPointerDown", at(0.5));
    h.fire(bar(h), "onPointerLeave");
    assert.equal(cls(h, "lm-preview").length, 0);
    assert.deepEqual(h.calls("setSelShot"), [["c3"]]);
  });

  test("onReelDown captures the pointer with the event's own pointerId", () => {
    const h = phone();
    const captured = [];
    h.fire(bar(h), "onPointerDown", at(0.5, { pointerId: 42,
      currentTarget: { getBoundingClientRect: () => ({ left: 100, width: 600 }), setPointerCapture: (id) => captured.push(id) } }));
    assert.deepEqual(captured, [42]);
  });

  test("the fraction comes from the bar's own rect and the pointer's clientX", () => {
    const h = phone();
    h.fire(bar(h), "onPointerDown", at(0.7));
    assert.equal(one(cls(h, "lm-scrubline")).props.style.left, "calc(16px + (100% - 32px) * 0.7)");
    assert.equal(one(cls(h, "lm-preview")).props.style.left, "clamp(8px, calc(70.000% - 86px), calc(100% - 8px - 172px))");
    // Past either end clamps to the bar.
    h.fire(bar(h), "onPointerMove", at(-0.5));
    assert.equal(one(cls(h, "lm-scrubline")).props.style.left, "calc(16px + (100% - 32px) * 0)");
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·01");
  });

  test("the fraction resolves to a shot INDEX by cumulative duration, not by equal-width slots", () => {
    const h = phone();
    // 70% of 12 s is 8.4 s: inside the 6 s second shot (4..10 s). Equal-width slots would say the third.
    h.fire(bar(h), "onPointerDown", at(0.7));
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·02");
    h.fire(bar(h), "onPointerMove", at(0.32));   // 3.84 s: still the first shot
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·01");
    h.fire(bar(h), "onPointerMove", at(0.34));   // 4.08 s: the second
    assert.equal(one(cls(h, "lm-prevcode")).props.children, "A·02");
  });

  test("releasing the drag selects the shot it landed on", () => {
    const h = phone();
    h.fire(bar(h), "onPointerDown", at(0.7));
    h.fire(bar(h), "onPointerUp");
    assert.deepEqual(h.calls("setSelShot"), [["c2"]]);
    assert.ok(classOf(one(cls(h, "lm-seg").filter((s) => s.key === "c2"))).includes("sel"), "the reel marks the selected shot");
  });

  test("a floating preview card renders only while scrubbing, showing the live shot under the pointer", () => {
    const h = phone();
    assert.equal(markup(h).byClass("lm-preview").length, 0);
    h.fire(bar(h), "onPointerDown", at(0.7));
    const card = one(markup(h).byClass("lm-preview"));
    assert.equal(one(card.byClass("lm-prevcode")).text, "A·02");
    assert.equal(one(card.byClass("lm-prevtitle")).text, "Doorway");
    assert.equal(one(card.byClass("lm-prevmeta")).text, "I2V · 6s");
    h.fire(bar(h), "onPointerUp");
    assert.equal(markup(h).byClass("lm-preview").length, 0);
  });

  test("the target-duration tick is placed from project.target over the cut's length", () => {
    const tick = (target) => cls(phone({ board: { ...makeBoard(), target } }), "lm-tick");
    assert.equal(one(tick(6)).props.style.left, "calc(16px + (100% - 32px) * 0.5)");   // 6 of 12 s
    assert.equal(one(tick(30)).props.style.left, "calc(16px + (100% - 32px) * 1)");    // capped at the end
    assert.equal(one(tick(0)).props.style.left, "calc(16px + (100% - 32px) * 0)");
    const empty = { ...makeBoard(), acts: [{ id: "a1", name: "Act 1", cards: [] }] };
    assert.equal(cls(phone({ board: empty }), "lm-tick").length, 0, "no shots, no cut, no tick");
  });
});

describe("the act-grouped shot board: add-shot / add-act / tap-to-select", () => {
  test("+ Shot adds a shot to THAT act (addCard(act.id))", () => {
    const h = phone();
    const [first, second] = btns(h, "+ Shot");
    h.click(second);
    h.click(first);
    assert.deepEqual(h.calls("addCard"), [["a2"], ["a1"]]);
  });

  test("+ New act calls addAct", () => {
    const h = phone();
    h.click(btn(h, "+ New act"));
    assert.equal(h.calls("addAct").length, 1);
  });

  test("tapping a shot card selects it AND opens Shot Detail", () => {
    const h = phone();
    assert.equal(cls(h, "lm-df").length, 0);
    h.click(one(cls(h, "lm-card").filter((e) => e.props["data-card-id"] === "c2")));
    assert.deepEqual(h.calls("setSelShot"), [["c2"]]);
    const df = one(cls(h, "lm-df"), "Shot Detail");
    assert.equal(textOf(one(cls(df, "lm-code"))), "A·02");
  });

  test("cards show a thumbnail resolved the way LoomV2's board does: the open frame, else the rendered clip", () => {
    const thumbs = { t9: "data:image/png;base64,AAAA" };
    const board = makeBoard({ c3: { openFrame: frame({ thumbId: "t9" }) } });
    const $ = markup(phone({ board, props: { thumbs } }));
    const thumb = (id) => one(one($.byAttr("data-card-id", id)).byClass("lm-thumb"));
    assert.equal(thumb("c1").attr("style"), "background-image:url(/thumbs/" + MID.open1 + ".jpg)");
    assert.equal(thumb("c2").attr("style"), "background-image:url(/thumbs/" + MID.res2 + ".jpg)");
    assert.equal(thumb("c3").attr("style"), "background-image:url(" + thumbs.t9 + ")");
    // Neither: no picture, the mode instead.
    const bare = markup(phone({ board: makeBoard({ c1: { openFrame: frame() } }) }));
    const t1 = one(one(bare.byAttr("data-card-id", "c1")).byClass("lm-thumb"));
    assert.equal(t1.attr("style"), undefined);
    assert.equal(t1.text, "R2V");
    // Both an open frame and a rendered clip: the open frame wins.
    const both = markup(phone({ board: makeBoard({ c2: { openFrame: frame({ mediaId: MID.open1 }) } }) }));
    assert.equal(one(one(both.byAttr("data-card-id", "c2")).byClass("lm-thumb")).attr("style"),
      "background-image:url(/thumbs/" + MID.open1 + ".jpg)");
  });

  test("the status pill and the reel segment always show the same status (one statusOf)", () => {
    const genState = {
      c1: { phase: "paused", msg: "Paused auto-checking" },
      c2: { phase: "running", msg: "Rendering…" },
      c3: { phase: "error", msg: "it failed" },
    };
    const $ = markup(phone({ board: makeBoard({ c3: { status: "wip" } }), props: { genState } }));
    const segs = one($.byClass("lm-reelbar")).byClass("lm-seg");
    const pills = $.byClass("lm-stpill");
    const statuses = ["paused", "wip", "wip"];   // paused; any live phase reads wip; a settled one, the shot's own
    statuses.forEach((st, i) => {
      assert.ok(segs[i].hasClass(st), "segment " + i + " is " + st + ": " + segs[i].attr("class"));
      assert.ok(pills[i].hasClass(st), "pill " + i + " is " + st + ": " + pills[i].attr("class"));
    });
    assert.deepEqual(pills.map((p) => p.text), ["Paused auto-checking", "Rendering…", "it failed"]);
    // With nothing in flight, both fall back to the shot's own persisted status.
    const calm = markup(phone());
    assert.deepEqual(one(calm.byClass("lm-reelbar")).byClass("lm-seg").map((s) => s.classes[1]), ["todo", "done", "todo"]);
    assert.deepEqual(calm.byClass("lm-stpill").map((p) => p.classes[1]), ["todo", "done", "todo"]);
  });
});

// Shot Detail (Deep Focus's mobile equivalent), the Cast & assets sheet and the Frame picker.
describe("Shot Detail (mobile Deep Focus): opens from the board, edits the REAL shot", () => {
  const detail = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, ...opts.state } });
  const df = (h) => one(cls(h, "lm-df"), "Shot Detail");

  test("renders only while it is open AND its shot is live -- never an empty screen", () => {
    assert.equal(cls(detail(), "lm-df").length, 1);
    assert.equal(cls(phone({ sel: "c1" }), "lm-df").length, 0, "closed");
    assert.equal(cls(phone({ sel: null, state: { dfOpen: true } }), "lm-df").length, 0, "no shot selected");
  });

  test("a stale reference (the shot vanished out from under it) closes Shot Detail instead of rendering blank", () => {
    const h = phone({ sel: "gone", state: { dfOpen: true } });
    assert.equal(cls(h, "lm-df").length, 0);
    assert.equal(h.state("dfOpen"), false, "it closed itself, so a later shot with that id does not pop it open");
    h.setProps({ selShot: "c1" });
    h.render();
    assert.equal(cls(h, "lm-df").length, 0);
  });

  test("Mode chips render the real MODES array and write through the real setShotMode reducer", () => {
    const h = detail();
    const chips = els(one(cls(df(h), "lm-modechips"))).filter((e) => e.type === "button");
    assert.deepEqual(chips.map(textOf), MODES);
    assert.deepEqual(chips.filter((c) => classOf(c).includes("on")).map(textOf), ["R2V"]);
    const before = h.card("c1");
    h.click(chips.find((c) => textOf(c) === "FLF"));
    assert.deepEqual(h.card("c1"), setShotMode(before, "FLF"));
  });

  test("Duration and Discreet show and write the shot's own duration/discreet fields", () => {
    const h = detail({ board: makeBoard({ c1: { duration: 7, discreet: true } }) });
    const dur = one(els(df(h)).filter((e) => e.type === "input" && e.props.type === "number"));
    assert.equal(dur.props.value, 7);
    const discreet = one(els(df(h)).filter((e) => e.type === "label" && /blur previews/.test(textOf(e))));
    const box = one(ofType(discreet, "input"));
    assert.equal(box.props.checked, true);
    h.fire(dur, "onChange", { target: { value: "9" } });
    h.fire(one(ofType(one(els(df(h)).filter((e) => e.type === "label" && /blur previews/.test(textOf(e)))), "input")),
      "onChange", { target: { checked: false } });
    assert.equal(h.card("c1").duration, 9);
    assert.equal(h.card("c1").discreet, false);
  });

  test("Prompt shows c.prompt, and typing it clears an active promptOverride exactly like LoomV2's Deep Focus", () => {
    const h = detail({ board: makeBoard({ c1: { promptOverride: true, promptOverrideText: "hand-written" } }) });
    const ta = one(els(df(h)).filter((e) => e.type === "textarea" && e.props.placeholder === "what happens in this shot"));
    assert.equal(ta.props.value, "she walks in");
    const before = h.card("c1");
    h.fire(ta, "onChange", { target: { value: "she runs in" } });
    assert.deepEqual(h.card("c1"), { ...clearPromptOverride(before), prompt: "she runs in" });
  });

  test("the status pill cycles the persisted 3-state c.status (todo->wip->done->todo); 'paused' is display-only", () => {
    const h = detail({ props: { genState: { c1: { phase: "paused" } } } });
    const pill = () => one(cls(df(h), "lm-df-st"));
    assert.equal(textOf(pill()), "paused", "a paused poll shows as paused...");
    const seen = [];
    for (let i = 0; i < 3; i++) { h.click(pill()); seen.push(h.card("c1").status); }
    assert.deepEqual(seen, ["wip", "done", "todo"], "...but the tap cycles the shot's own status");
  });

  test("Shot Detail and the Reference tab each mount the real FrameSlot pair, with the live @image slot", () => {
    const openPick = () => {};
    const storeThumb = () => {};
    const h = phone({ sel: "c1", state: { dfOpen: true, genOpen: true, genTab: "Reference" }, props: { openPick, storeThumb } });
    const slots = ofType(h, FrameSlot);
    assert.deepEqual(slots.map((s) => s.props.which), ["open", "close", "open", "close"],
      "two pairs: Shot Detail's own, plus the Generate > Reference tab's");
    const entry = h.entry("c1");
    const want = (key) => positionTag(entry, h.props.project, imgSrcOf({}), key);
    for (const s of slots) {
      assert.equal(s.props.frame, entry.c[s.props.which + "Frame"]);
      assert.equal(s.props.liveTag, want(s.props.which + "Frame"));
      assert.equal(s.props.openPick, openPick, "the gallery picker is the one App handed down");
      assert.equal(s.props.storeThumb, storeThumb);
    }
    assert.equal(want("openFrame"), "@image1");
    // And it is what renders: the slot label and its live tag.
    const frames = one(markup(h).byClass("lm-df")).byClass("sb-frame");
    assert.deepEqual(frames.map((f) => one(f.byClass("sb-lab")).text), ["Opening frame", "Closing frame"]);
    assert.deepEqual(frames.map((f) => one(f.byClass("sb-tagin")).text), ["@image1", "—"]);
  });

  test("the opening frame's inherit/splice button appears only with a real previous shot, and splices through /api/loom/handoff", async () => {
    const extra = (h) => one(ofType(h, FrameSlot).filter((s) => s.props.which === "open")).props.extraBtn;
    assert.equal(extra(phone({ sel: "c1", state: { dfOpen: true } })), null, "the first shot has no previous shot");
    // The previous shot has no render yet: copy its closing frame.
    const h2 = phone({ sel: "c2", board: makeBoard({ c1: { closeFrame: frame({ mediaId: "777" }) } }), state: { dfOpen: true } });
    assert.equal(textOf(extra(h2)), "↳ inherit A·01 close");
    h2.click(extra(h2));
    assert.equal(h2.card("c2").openFrame.mediaId, "777");
    // The previous shot rendered: splice its last frame.
    browser.reply = (url) => (url === "/api/loom/handoff" ? { frame_media_id: "888" } : {});
    const h3 = phone({ sel: "c3", state: { dfOpen: true } });
    assert.equal(textOf(extra(h3)), "✂ splice A·02's last frame");
    h3.click(extra(h3));
    assert.deepEqual(fetched("/api/loom/handoff").map((x) => x[2]), [{ video_media_id: MID.res2, trim_out: null }]);
    assert.equal(textOf(extra(h3)), "✂ splicing…");
    assert.equal(extra(h3).props.disabled, true);
    await settle();
    h3.render();
    assert.equal(h3.card("c3").openFrame.mediaId, "888");
  });

  test("Other references & @tags add, and remove, through the real addRef/delRef over c.refs", () => {
    const ref = { ...buildNewRef("video", "r1"), tag: "@video1" };
    const h = detail({ board: makeBoard({ c1: { refs: [ref] } }) });
    const card = h.card("c1");
    for (const k of ["+ Image", "+ Video", "+ Audio"]) h.click(btn(df(h), k));
    assert.deepEqual(h.calls("addRef"), [["a1", card, "image"], ["a1", card, "video"], ["a1", card, "audio"]]);
    h.click(one(cls(df(h), "lm-refx")));
    assert.deepEqual(h.calls("delRef"), [["a1", "c1", ref]]);
  });

  test("the Cast button shows the shot's own cast count and opens the Cast & assets sheet", () => {
    const h = detail({ board: makeBoard({ c1: { cast: ["as1", "as2"] } }) });
    const cast = one(cls(df(h), "lm-df-cast"));
    assert.equal(textOf(cast), "👥 2");
    assert.equal(cls(h, "lm-sheet").length, 0);
    h.click(cast);
    assert.equal(cls(h, "lm-sheet").length, 1);
  });

  test("Copy shot copies the live shot (copyShot(dfLive))", () => {
    const h = detail();
    h.click(btn(df(h), "Copy shot"));
    assert.deepEqual(h.calls("copyShot"), [[h.entry("c1")]]);
  });
});

describe("Cast & assets sheet: real project.assets, mode-aware budget, and a Footage tab off real finished shots", () => {
  const sheet = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, castSheetOpen: true, ...opts.state } });

  test("the sheet has its own Cast & assets / Footage tab strip", () => {
    const h = sheet();
    const tabs = els(one(cls(one(cls(h, "lm-sheet")), "lm-tabsrow"))).filter((e) => e.type === "button");
    assert.deepEqual(tabs.map(textOf), ["Cast & assets", "Footage"]);
    assert.deepEqual(tabs.map((t) => classOf(t).includes("on")), [true, false]);
    h.click(tabs[1]);
    assert.equal(h.state("castSheetTab"), "footage");
    assert.equal(cls(h, "lm-castrow").length, 0);
  });

  test("cast rows toggle the shot's own c.cast (project.assets ids), in and out", () => {
    const h = sheet();
    const row = (name) => one(cls(h, "lm-castrow").filter((r) => textOf(r).includes(name)));
    assert.ok(classOf(one(cls(row("Her"), "lm-castbox"))).includes("on"));
    h.click(row("The room"));
    assert.deepEqual(h.card("c1").cast, ["as1", "as2"]);
    h.click(row("Her"));
    assert.deepEqual(h.card("c1").cast, ["as2"]);
  });

  test("the budget line is the mode-aware refBudget(); I2V and First & Last say what they send instead", () => {
    const h = sheet();
    const b = refBudget(h.entry("c1"), h.props.project, imgSrcOf({}));
    const want = b.used + " of " + b.budget + " reference slot" + (b.budget === 1 ? "" : "s") + " used"
      + (b.frames ? " · " + b.frames + " of 6 held by attached frame" + (b.frames === 1 ? "" : "s") : "");
    assert.equal(one(markup(h).byClass("lm-budget")).text, want);
    assert.equal(b.frames, 1, "the R2V shot's open frame holds a slot");
    const i2v = markup(sheet({ sel: "c2" }));
    assert.equal(i2v.byClass("lm-budget").length, 0);
    assert.match(one(i2v.byClass("lm-i2vnote")).text, /^I2V sends the opening frame only/);
    assert.match(one(markup(sheet({ sel: "c3" })).byClass("lm-i2vnote")).text, /^First & Last sends the start & end frames only/);
  });

  test("+ Image ref / + Audio ref append real, taggable project.assets entries, numbered by nextTag", () => {
    const h = sheet();
    h.click(btn(h, "+ Image ref"));
    h.click(btn(h, "+ Audio ref"));
    const added = h.props.project.assets.slice(3);
    assert.deepEqual(added.map(({ id, ...rest }) => rest), [
      { name: "New reference", kind: "image", tag: "@image3", thumbId: "", source: "", lock: false },
      { name: "New audio", kind: "audio", tag: "@audio2", thumbId: "", source: "", lock: false },
    ]);
    assert.ok(added.every((a) => typeof a.id === "string" && a.id.length > 0));
  });

  test("the Footage tab lists the board's finished shots (entries with a resultMid), not made-up rows", () => {
    const $ = markup(sheet({ state: { castSheetTab: "footage" } }));
    const clip = one($.byClass("lm-fclip"));
    assert.equal(one(clip.byTag("img")).attr("src"), "/thumbs/" + MID.res2 + ".jpg");
    assert.equal(one(clip.byClass("lm-fclipmeta")).text, "A·026s");
    const none = markup(sheet({ board: makeBoard({ c2: { resultMid: undefined, status: "todo" } }), state: { castSheetTab: "footage" } }));
    assert.equal(none.byClass("lm-fclip").length, 0);
    assert.equal(one(none.byText("no rendered shots yet")).text, "no rendered shots yet");
  });

  test("picking a finished shot appends it as the next @videoN reference on the open shot, and closes the sheet", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const old = { ...buildNewRef("video", "r0"), tag: "@video1", source: "55" };
    // A non-video ref whose hand-typed tag sits in the @video namespace: only VIDEO refs number
    // the next @videoN, so it must not push the new tag to @video4.
    const stray = { ...buildNewRef("image", "r1"), tag: "@video3", source: "66" };
    const h = sheet({ board: makeBoard({ c1: { refs: [old, stray] } }), state: { castSheetTab: "footage" } });
    h.click(one(cls(h, "lm-fclip")));
    const added = h.card("c1").refs[2];
    assert.deepEqual({ ...added, id: "x" }, { ...buildNewRef("video", "x"), tag: "@video2", source: MID.res2, role: "footage from A·02" });
    assert.ok(classOf(one(cls(h, "lm-sheet"))).includes("closing"), "the sheet plays its close");
    t.mock.timers.tick(280);
    h.render();
    assert.equal(cls(h, "lm-sheet").length, 0);
  });
});

describe("scope discipline: every screen of the locked design is built (Loom Mobile is complete)", () => {
  test("Shot Detail / Cast & assets / Review & trim / Filter compare / Fixer each render their own title or hint", () => {
    const shot = markup(phone({ sel: "c1", state: { dfOpen: true, castSheetOpen: true } }));
    assert.equal(one(shot.byText("Cast & assets")).tag, "button");
    assert.equal(one(shot.byText("Other references & @tags")).attr("class"), "lm-microlab");
    assert.equal(one(shot.byText("Music / audio cue")).attr("class"), "lm-microlab");
    const review = markup(phone({ sel: "c2", state: { reviewOpen: true } }));
    assert.equal(one(review.byClass("lm-gen-title")).text, "Review & trim");
    const filters = markup(phone({ sel: "c1", state: { dfOpen: true, fcOpen: true } }));
    assert.equal(one(one(filters.byClass("lm-fc")).byClass("lm-gen-title")).text, "Art filters");
    const fixer = markup(phone({ sel: "c1", state: { dfOpen: true, genOpen: true, genTab: "Edit", editSub: "fixer" } }));
    assert.equal(one(fixer.byClass("lm-fixhint")).text, "Drag a box over the hand or face on the source.");
  });
});

/* Fixer (face/hand touch-up repair): a port of gallery/src/components/FixTab.jsx -- the same
   FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleBoxes values (editCore.js), the same Pointer-Events
   box drawing, and a confirm-gated submit through /api/fix (genFix, useGenerationPipeline). */
const fixerState = (extra = {}) => ({ dfOpen: true, genOpen: true, genTab: "Edit", editSub: "fixer", ...extra });
// A canvas and its <img> as a browser would lay them out: the canvas at (100, 50) on screen.
function fakeCanvas() {
  const ops = [];
  const ctx = {
    clearRect: (...a) => ops.push(["clearRect", ...a]),
    strokeRect: (...a) => ops.push(["strokeRect", ctx.strokeStyle, ...a]),
    fillText: (...a) => ops.push(["fillText", ctx.fillStyle, ...a]),
  };
  return { width: 0, height: 0, ops, getContext: () => ctx, getBoundingClientRect: () => ({ left: 100, top: 50, width: 400, height: 300 }) };
}
const fakeImg = (extra = {}) => ({ clientWidth: 400, clientHeight: 300, naturalWidth: 1600, ...extra });
function fixer(opts = {}) {
  const canvas = fakeCanvas();
  const h = phone({ sel: "c1", ...opts, state: fixerState(opts.state), refs: { fixCanvasRef: canvas, fixImgRef: fakeImg(), ...opts.refs } });
  h.canvas = canvas;
  return h;
}
// Drag on the Fixer canvas, in canvas coordinates.
function drag(h, from, to, extra = {}) {
  const canvas = () => one(ofType(h, "canvas"), "the Fixer canvas");
  const at = ([x, y]) => event({ clientX: 100 + x, clientY: 50 + y, pointerId: 5, ...extra });
  h.fire(canvas(), "onPointerDown", at(from));
  h.fire(canvas(), "onPointerMove", at(to));
  h.fire(canvas(), "onPointerUp", at(to));
}

describe("Fixer: local, verbatim copies of FixTab.jsx's own real editCore.js constants", () => {
  // Kept as a source pin: a drift guard between two copies of the same constants.
  test("FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES match editCore.js's own real values exactly", () => {
    // The expected literals are built from editCore.js's own exports, so a change on either
    // side alone breaks this (the Loom copies use double quotes, as JSON.stringify does).
    assert.match(src, new RegExp("const FIX_COLORS = \\{ face: " + JSON.stringify(FIX_COLORS.face)
      + ", hand: " + JSON.stringify(FIX_COLORS.hand) + " \\};"));
    assert.match(src, new RegExp("const FIX_MIN_PX = " + FIX_MIN_PX + ";"));
    assert.match(src, new RegExp("const FIX_MAX_BOXES = " + FIX_MAX_BOXES + ";"));
  });

  test("the boxes the Fix button sends are scaled exactly as editCore.js's scaleBoxes scales them", () => {
    const boxes = [{ x: 10, y: 20, w: 30, h: 41, tag: "face" }, { x: 1, y: 2, w: 3, h: 5, tag: "hand" }];
    for (const img of [fakeImg({ naturalWidth: 1000, clientWidth: 400 }), fakeImg({ naturalWidth: 1600, clientWidth: 400 }),
      fakeImg({ clientWidth: 0 }), null]) {
      const h = fixer({ state: { fixBoxes: boxes }, refs: { fixImgRef: img } });
      h.click(btn(h, "✦ Fix face"));
      assert.deepEqual(h.calls("genFix")[0][1], scaleBoxes(boxes, img), "img " + JSON.stringify(img));
    }
    // ...which means original-image pixels, {x,y,width,height,tag}: here 2.5x, rounded.
    const h = fixer({ state: { fixBoxes: boxes }, refs: { fixImgRef: fakeImg({ naturalWidth: 1000, clientWidth: 400 }) } });
    h.click(btn(h, "✦ Fix face"));
    assert.deepEqual(h.calls("genFix")[0][1], [
      { x: 25, y: 50, width: 75, height: 103, tag: "face" }, { x: 3, y: 5, width: 8, height: 13, tag: "hand" },
    ]);
  });
});

describe("Fixer: the Edit/Fixer/Enhance sub-strip is the design's three-way chip row", () => {
  test("a real Fixer chip exists in the Edit sub-strip, and tapping it opens the Fixer", () => {
    const h = phone({ sel: "c1", state: { dfOpen: true, genOpen: true, genTab: "Edit" } });
    const strip = one(cls(h, "lm-tabsrow").filter((r) => textOf(r) === "EditFixerEnhance"), "Edit sub-strip");
    h.click(btn(strip, "Fixer"));
    assert.equal(h.state("editSub"), "fixer");
    const now = one(cls(h, "lm-tabsrow").filter((r) => textOf(r) === "EditFixerEnhance"));
    assert.deepEqual(els(now).filter((e) => e.type === "button").filter((b) => classOf(b).includes("on")).map(textOf), ["Fixer"]);
    assert.equal(cls(h, "lm-fixwrap").length, 1);
  });
});

describe("Fixer: source is this shot's real open frame -- same convention as the Edit sub-tab", () => {
  test("the Fixer body renders only on the Fixer chip, over the shot's own open frame (or says there is none)", () => {
    const $ = markup(fixer());
    assert.ok($.byText("Source — this shot's open frame").length >= 1);
    const wrap = one($.byClass("lm-fixwrap"));
    assert.equal(one(wrap.byTag("img")).attr("src"), "/thumbs/" + MID.open1 + ".jpg");
    const none = markup(fixer({ sel: "c3" }));
    assert.equal(none.byClass("lm-fixwrap").length, 0);
    assert.equal(none.byTag("canvas").length, 0);
    assert.match(one(none.byClass("lm-gen")).byClass("lm-empty")[0].text, /^No open-frame image yet/);
    // The Edit chip shows the Edit body, not the Fixer.
    assert.equal(markup(fixer({ state: { editSub: "edit" } })).byClass("lm-fixwrap").length, 0);
  });
});

describe("Fixer: box-drawing canvas -- a port of FixTab.jsx's paint()/onDown/onMove/onUp", () => {
  test("the canvas sits over a same-sized <img> in .lm-fixwrap, and a drag on it draws a box", () => {
    const h = fixer();
    const wrap = one(markup(h).byClass("lm-fixwrap"));
    assert.deepEqual(wrap.children.filter((c) => typeof c !== "string").map((c) => c.tag), ["img", "canvas"]);
    drag(h, [10, 20], [70, 100]);
    assert.deepEqual(h.state("fixBoxes"), [{ x: 10, y: 20, w: 60, h: 80, tag: "face" }]);
    assert.equal(textOf(btn(h, "Clear 1 box")), "Clear 1 box");
  });

  test("each paint sizes the canvas to the rendered <img>'s own clientWidth/clientHeight", () => {
    const img = fakeImg({ clientWidth: 320, clientHeight: 180 });
    const h = fixer({ refs: { fixImgRef: img } });
    h.flush();
    assert.deepEqual([h.canvas.width, h.canvas.height], [320, 180]);
    img.clientWidth = 640; img.clientHeight = 360;
    drag(h, [10, 10], [50, 50]);
    assert.deepEqual([h.canvas.width, h.canvas.height], [640, 360]);
  });

  test("boxes are stroked in the per-tag FIX_COLORS and labelled with their tag", () => {
    const h = fixer();
    h.flush();
    drag(h, [10, 10], [60, 60]);
    h.click(btn(h, "Hand"));
    drag(h, [100, 100], [140, 150]);
    h.canvas.ops.length = 0;
    h.flush();
    assert.deepEqual(h.canvas.ops.filter((o) => o[0] === "strokeRect"), [
      ["strokeRect", FIX_COLORS.face, 10, 10, 50, 50], ["strokeRect", FIX_COLORS.hand, 100, 100, 40, 50]]);
    assert.deepEqual(h.canvas.ops.filter((o) => o[0] === "fillText").map((o) => [o[1], o[2]]),
      [[FIX_COLORS.face, "face"], [FIX_COLORS.hand, "hand"]]);
  });

  test("the box coordinates are the pointer's position inside the canvas's own rect", () => {
    const h = fixer();
    const canvas = one(ofType(h, "canvas"));
    // clientX/clientY are screen coordinates; the canvas starts at (100, 50).
    h.fire(canvas, "onPointerDown", event({ clientX: 160, clientY: 90 }));
    h.fire(one(ofType(h, "canvas")), "onPointerMove", event({ clientX: 130, clientY: 150 }));
    h.fire(one(ofType(h, "canvas")), "onPointerUp", event());
    assert.deepEqual(h.state("fixBoxes"), [{ x: 30, y: 40, w: 30, h: 60, tag: "face" }], "a drag up-left still makes a positive box");
  });

  test("a stray tap is not a box (FIX_MIN_PX), and a Fix never carries more than FIX_MAX_BOXES", () => {
    const h = fixer();
    drag(h, [10, 10], [10 + FIX_MIN_PX, 10 + FIX_MIN_PX]);
    assert.deepEqual(h.state("fixBoxes"), []);
    drag(h, [10, 10], [11 + FIX_MIN_PX, 11 + FIX_MIN_PX]);
    assert.equal(h.state("fixBoxes").length, 1);

    const full = Array.from({ length: FIX_MAX_BOXES }, (_, i) => ({ x: i, y: i, w: 20, h: 20, tag: "face" }));
    const shown = [];
    window.Toast = { show: (t) => shown.push(t) };
    const f = fixer({ state: { fixBoxes: full } });
    drag(f, [10, 10], [80, 80]);
    assert.equal(f.state("fixBoxes"), full, "the box past the limit is not added");
    assert.equal(shown.length, 1);
    assert.equal(shown[0].title, "That's the limit");
    assert.match(shown[0].msg, new RegExp("at most " + FIX_MAX_BOXES + " boxes"));
  });

  test("a drag on the canvas captures the pointer with the event's own pointerId", () => {
    const h = fixer();
    const captured = [];
    h.fire(one(ofType(h, "canvas")), "onPointerDown", event({ pointerId: 31, currentTarget: { setPointerCapture: (id) => captured.push(id) } }));
    assert.deepEqual(captured, [31]);
  });

  test("boxes reset whenever the source image changes (another shot, or this shot's open frame replaced)", () => {
    const h = fixer();
    h.flush();
    drag(h, [10, 10], [60, 60]);
    h.flush();
    assert.equal(h.state("fixBoxes").length, 1, "nothing changed: the box stays");
    const replaced = makeBoard({ c1: { openFrame: frame({ mediaId: "999" }) } });
    h.setProps({ project: replaced, entries: flat(replaced) });
    h.render(); h.flush();
    assert.deepEqual(h.state("fixBoxes"), [], "a new open frame on the same shot");
    drag(h, [10, 10], [60, 60]);
    h.flush();
    assert.equal(h.state("fixBoxes").length, 1, "a box on the new frame");
    h.setProps({ selShot: "c2" }); h.render(); h.flush();
    assert.deepEqual(h.state("fixBoxes"), [], "another shot");
  });

  test("the Face/Hand tag chips are .lm-modechip chips, the active one in its own FIX_COLORS colour", () => {
    const h = fixer();
    const chips = () => markup(h).byClass("lm-modechip").filter((c) => c.text === "Face" || c.text === "Hand");
    assert.deepEqual(chips().map((c) => [c.text, c.hasClass("on"), c.attr("style")]),
      [["Face", true, "border-color:" + FIX_COLORS.face + ";color:" + FIX_COLORS.face], ["Hand", false, undefined]]);
    assert.ok(chips().every((c) => c.parent.hasClass("lm-modechips")));
    h.click(btn(h, "Hand"));
    assert.deepEqual(chips().map((c) => [c.text, c.hasClass("on"), c.attr("style")]),
      [["Face", false, undefined], ["Hand", true, "border-color:" + FIX_COLORS.hand + ";color:" + FIX_COLORS.hand]]);
  });
});

describe("Fixer: the real, mandatory spend warning and confirm-gated submit through the real /api/fix endpoint", () => {
  test("the Fixer always shows the spend warning: a fix can't be card-covered, always spends, always asks", () => {
    const $ = markup(fixer());
    assert.equal(one($.byClass("lm-fixwarn")).text, "A fix can't be card-covered — it always spends, and always asks first.");
    // Even before any box, and with no source at all.
    assert.equal(markup(fixer({ sel: "c3" })).byClass("lm-fixwarn").length, 1);
  });

  test("the Fix button says what it will fix (the lowercase tag), or the job's own progress while it runs", () => {
    const h = fixer({ state: { fixBoxes: [{ x: 1, y: 1, w: 9, h: 9, tag: "face" }] } });
    assert.equal(textOf(btn(h, /^✦ Fix /)), "✦ Fix face");
    h.click(btn(h, "Hand"));
    assert.equal(textOf(btn(h, /^✦ Fix /)), "✦ Fix hand");
    // A running fix shuts its own button even with boxes drawn (no double submit of a paid fix);
    // the same boxes without the running job leave it live, so the busy state is what shut it.
    const box = { x: 1, y: 1, w: 9, h: 9, tag: "face" };
    const busy = fixer({ state: { fixBoxes: [box] }, props: { genFixState: { c1: { phase: "running", msg: "fixing 40%" } } } });
    assert.equal(one(btns(busy, "fixing 40%")).props.disabled, true);
    assert.equal(btn(fixer({ state: { fixBoxes: [box] } }), "✦ Fix face").props.disabled, false);
  });

  test("the Fix button submits the live shot and its boxes in ORIGINAL-image pixels through genFix -- once, and only when it can", () => {
    const boxes = [{ x: 40, y: 20, w: 100, h: 60, tag: "hand" }];
    const h = fixer({ state: { fixBoxes: boxes }, refs: { fixImgRef: fakeImg({ naturalWidth: 2000, clientWidth: 400 }) } });
    const go = btn(h, "✦ Fix face");
    assert.equal(go.props.disabled, false);
    h.click(go);
    const calls = h.calls("genFix");
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], h.entry("c1"), "the live shot itself, not a copy");
    assert.deepEqual(calls[0][1], [{ x: 200, y: 100, width: 500, height: 300, tag: "hand" }]);
    // No box, or no source: the button is shut and says why.
    const empty = btn(fixer(), "✦ Fix face");
    assert.deepEqual([empty.props.disabled, empty.props.title], [true, "Drag at least one box"]);
    const nosrc = btn(fixer({ sel: "c3", state: { fixBoxes: boxes } }), "✦ Fix face");
    assert.deepEqual([nosrc.props.disabled, nosrc.props.title], [true, "This shot has no open-frame image yet"]);
  });

  // Kept as a source pin: where the one /api/fix POST is made (and that it rides runGen).
  test("genFix lives in useGenerationPipeline, submits to the real /api/fix endpoint via runGen (the same submit/poll/register machinery genEdit/genRef already share)", () => {
    assert.match(src, /const genFix = async \(entry, scaledBoxes\) => \{/);
    assert.match(src, /runGen\(setGenFixState, c\.id, "\/api\/fix", \{ source: src, boxes: scaledBoxes \}, null, "",/);
  });

  test("genFix asks for THIS fix's price, fresh, before its confirm -- and sends nothing when the owner says no", async () => {
    const h = app({ view: "mobile" });
    const { genFix, entries } = viewOf(h).props;
    const boxes = [{ x: 4, y: 8, width: 40, height: 60, tag: "face" }];
    browser.reply = (url) => (url === "/api/price" ? { cost: 900, free: false } : { error: "refused in test" });
    browser.answer = false;
    await genFix(entries[0], boxes);
    assert.deepEqual(browser.trail, [
      ["fetch", "/api/price", { mode: "fix", source: MID.open1, boxes }],
      ["confirm", "Repair 1 area?\n\nThis will spend 900 credits — a Fix is never covered by a free card."],
    ]);
    // A price that could not be verified still asks -- and only a yes sends the fix.
    browser.trail = [];
    browser.reply = (url) => (url === "/api/price" ? new Error("dropped") : { error: "refused in test" });
    browser.answer = true;
    await genFix(entries[0], boxes);
    assert.deepEqual(browser.trail.map((x) => x[0] + " " + x[1]), ["fetch /api/price", "confirm Repair 1 area?\n\n"
      + "The price could not be verified, and a Fix ALWAYS spends credits (no free card can ever cover it).", "fetch /api/fix"]);
    assert.deepEqual(fetched("/api/fix")[0][2], { source: MID.open1, boxes });
  });

  // Kept as a source pin: the wording is the whole contract (FixTab.jsx's own run()).
  test("the confirm wording is ported VERBATIM from FixTab.jsx's own run() -- 'ALWAYS spends' / 'never covered by a free card', never confirmSpend's generic phrasing", () => {
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// Batch-generate the whole board"));
    assert.match(genFixBlock, /"The price could not be verified, and a Fix ALWAYS spends credits \(no free card can ever cover it\)\."/);
    assert.match(genFixBlock, /"This will spend " \+ Number\(priced\)\.toLocaleString\(\) \+ " credits — a Fix is never covered by a free card\."/);
    assert.match(genFixBlock, /if \(!window\.confirm\(/, "the real window.confirm gate must fire before any submit");
  });

  // Kept as a source pin: a null argument at one call site, which no render can show.
  test("genFix passes quoteBody:null to runGen -- it must never trigger runGen's OWN confirmSpend gate on top of its own real, Fix-correct confirm above", () => {
    // The parameter is positional and unchanged; only its NAME moved (priceBody -> quoteBody,
    // 2026-08-23), because priceBody is now the Loom's one price call site.
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// Batch-generate the whole board"));
    assert.match(genFixBlock, /runGen\(setGenFixState, c\.id, "\/api\/fix", \{ source: src, boxes: scaledBoxes \}, null,/,
      "quoteBody must be null so runGen's own confirmSpend (generic, free-card-implying wording) never runs a second confirm");
  });

  test("a missing open-frame source or an empty box list is refused BEFORE any price check or confirm", async () => {
    const h = app({ view: "mobile" });
    const { genFix, entries } = viewOf(h).props;
    const c3 = entries.find((e) => e.c.id === "c3");
    await genFix(c3, [{ x: 1, y: 1, width: 9, height: 9, tag: "face" }]);
    await genFix(entries[0], []);
    await genFix(entries[0], null);
    assert.deepEqual(browser.trail, [], "no price check, no confirm, no fix");
    const st = h.state("genFixState");
    assert.equal(st.c3.phase, "error");
    assert.match(st.c3.msg, /open frame needs a gallery image/);
    assert.equal(st.c1.phase, "error");
    assert.match(st.c1.msg, /drag a box/);
  });
});

describe("Fixer: real cost PREVIEW and real result routing, mirroring the Edit/Reference tabs' own conventions", () => {
  test("the price preview prices the same mode:\"fix\" body genFix submits, debounced 250 ms, only on the Fixer chip", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const h = fixer({ refs: { fixImgRef: fakeImg({ naturalWidth: 800, clientWidth: 400 }) } });
    h.flush();
    drag(h, [10, 10], [60, 70]);
    h.flush();
    t.mock.timers.tick(249);
    assert.deepEqual(fetched("/api/price"), []);
    t.mock.timers.tick(1);
    assert.deepEqual(fetched("/api/price").map((x) => x[2]),
      [{ mode: "fix", source: MID.open1, boxes: [{ x: 20, y: 20, width: 100, height: 120, tag: "face" }] }]);
    // No box: no price check.
    browser.trail = [];
    const empty = fixer();
    empty.flush();
    t.mock.timers.tick(1000);
    assert.deepEqual(fetched("/api/price"), []);
    // Off the Fixer chip (or with Generate shut, or on another tab) nothing is priced -- even with
    // a box drawn, so it is the gate itself that refuses, not the missing box.
    const box = { x: 10, y: 10, w: 50, h: 60, tag: "face" };
    for (const state of [{ editSub: "edit" }, { genOpen: false }, { genTab: "Video" }]) {
      browser.trail = [];
      const idle = fixer({ state: { ...state, fixBoxes: [box] } });
      idle.flush();
      t.mock.timers.tick(1000);
      assert.deepEqual(fetched("/api/price"), [], JSON.stringify(state));
    }
  });

  test("the preview line uses the same priceLine/priceTitle as the other tabs: the tally, its tooltip, or a hint", () => {
    const pr = { cost: 850, free: false, cards: [], note: "" };
    const tally = tallyPrices([pr]);
    const line = (genFixPrice) => one(markup(fixer({ state: { genFixPrice } })).byClass("lm-gencosttext"));
    assert.equal(line({ c1: { loading: false, pr } }).text, formatCostEstimate(tally));
    assert.equal(line({ c1: { loading: false, pr } }).attr("title"), costTooltip(tally));
    assert.equal(line({ c1: { loading: true } }).text, "checking…");
    assert.equal(line({}).text, "Drag a box over a hand or face to see the cost.");
  });

  test("a finished Fix routes into open/close frame or cast through the shared routeGen", () => {
    const genFixState = { c1: { phase: "done", mid: "600006" } };
    const setGenFixState = () => {};
    const h = fixer({ props: { genFixState, setGenFixState } });
    const route = cls(h, "lm-route")[0];
    for (const [label, target] of [["open frame", "open"], ["close frame", "close"], ["cast", "cast"]]) h.click(btn(route, label));
    const entry = h.entry("c1");
    assert.deepEqual(h.calls("routeGen"), ["open", "close", "cast"].map((tg) => [genFixState, setGenFixState, entry, tg, "c1"]));
  });
});

// Review & trim: the crop rectangle, two trim handles, a scrub track and a real <video>, opened
// from the board's ▶ badge on a finished shot.
describe("Review & trim: the board's own real ▶ affordance opens it on a finished shot", () => {
  test("the ▶ badge shows only on a shot that is done AND has a rendered clip (statusOf, not the bare status)", () => {
    const badged = (board, genState = {}) => markup(phone({ board, props: { genState } })).byClass("lm-reviewbadge")
      .map((b) => b.parent.byClass("lm-card")[0].attr("data-card-id"));
    assert.deepEqual(badged(makeBoard()), ["c2"]);
    assert.deepEqual(badged(makeBoard({ c2: { resultMid: undefined } })), [], "done but nothing to review");
    assert.deepEqual(badged(makeBoard({ c1: { resultMid: "1" } })), ["c2"], "a clip but not done");
    assert.deepEqual(badged(makeBoard(), { c2: { phase: "running" } }), [], "a re-render in flight reads wip");
  });

  test("the badge is a sibling <button> beside the .lm-card <button>, never nested inside it", () => {
    const badge = one(markup(phone()).byClass("lm-reviewbadge"));
    assert.equal(badge.tag, "button");
    assert.ok(badge.parent.hasClass("lm-cardrow"));
    assert.equal(badge.parent.byClass("lm-card")[0].byTag("button").length, 0);
  });

  test("tapping the badge selects the shot and opens Review, resetting the last shot's playback/crop state", () => {
    const h = phone({ state: { reviewCropping: true, reviewPlaying: true, reviewDur: 9, reviewCur: 3 } });
    const ev = event();
    h.click(one(cls(h, "lm-reviewbadge")), ev);
    assert.ok(ev.stopped, "the tap does not fall through to the card beneath");
    assert.deepEqual(h.calls("setSelShot"), [["c2"]]);
    assert.deepEqual(["reviewOpen", "reviewCropping", "reviewPlaying", "reviewDur", "reviewCur"].map(h.state), [true, false, false, 0, 0]);
    assert.equal(cls(h, "lm-review").length, 1);
  });
});

describe("Review & trim: real data, real live-lookup safety (mirrors dfLive exactly)", () => {
  const review = (opts = {}) => phone({ sel: "c2", ...opts, state: { reviewOpen: true, ...opts.state },
    refs: { reviewVidRef: { currentTime: 0, pause() {}, play: async () => {} }, ...opts.refs } });

  test("Review follows the selected shot (selShot), with no second 'which shot' id of its own", () => {
    const h = review({ board: makeBoard({ c1: { resultMid: "111", status: "done" } }) });
    assert.equal(textOf(one(cls(one(cls(h, "lm-review")), "lm-gen-back"))), "‹ A·02");
    h.setProps({ selShot: "c1" }); h.render();
    assert.equal(textOf(one(cls(one(cls(h, "lm-review")), "lm-gen-back"))), "‹ A·01");
  });

  test("a stale reference (the shot vanished out from under it) closes Review instead of rendering blank", () => {
    const h = review({ sel: "gone" });
    assert.equal(cls(h, "lm-review").length, 0);
    assert.equal(h.state("reviewOpen"), false);
  });

  test("the <video> plays this shot's rendered clip from /video-file/", () => {
    assert.equal(one(markup(review()).byTag("video")).attr("src"), "/video-file/" + MID.res2);
  });

  test("trim and crop read the card's own trimIn/trimOut/crop, with the planned length and the design's box as fallbacks", () => {
    const readout = (h) => one(markup(h).byClass("lm-review-trimreadout")).text;
    assert.equal(readout(review()), "0.0s → 6.0s", "no trim yet: the whole clip");
    assert.equal(readout(review({ board: makeBoard({ c2: { trimIn: 1.24, trimOut: 3.4 } }) })), "1.2s → 3.4s");
    const rect = (h) => one(cls(h, "lm-review-croprect")).props.style;
    const fallback = rect(review({ state: { reviewCropping: true } }));
    for (const k of ["left", "top"]) near(parseFloat(fallback[k]), 35, k);
    for (const k of ["width", "height"]) near(parseFloat(fallback[k]), 30, k);
    const own = rect(review({ board: makeBoard({ c2: { crop: { x: 0.1, y: 0.2, w: 0.3, h: 0.3 } } }), state: { reviewCropping: true } }));
    near(parseFloat(own.left), 10, "left"); near(parseFloat(own.top), 20, "top");
  });
});

describe("Review & trim: trim-handle drags -- fraction of the track, the design's own clamp", () => {
  // The trim track is 300px wide at x=0; the clip is 6 s.
  const TRACK = { getBoundingClientRect: () => ({ left: 0, width: 300 }) };
  const review = (cards) => phone({ sel: "c2", board: makeBoard({ c2: cards }), state: { reviewOpen: true },
    refs: { reviewTrimTrackRef: TRACK, reviewVidRef: { currentTime: 0, pause() {} } } });
  const handles = (h) => cls(h, "lm-review-trimhandle");
  // A handle's own rect is a moving 18px target; the math must never read it.
  const onHandle = (clientX, extra = {}) => event({ clientX, pointerId: 3,
    currentTarget: { setPointerCapture() {}, getBoundingClientRect: () => ({ left: 9999, width: 18 }) }, ...extra });

  test("all four review drags (trim in, trim out, scrub, crop) capture the pointer", () => {
    const captured = [];
    const cap = (n) => ({ setPointerCapture: () => captured.push(n), getBoundingClientRect: () => ({ left: 0, width: 300 }) });
    const h = phone({ sel: "c2", state: { reviewOpen: true, reviewCropping: true },
      refs: { reviewTrimTrackRef: TRACK, reviewVidRef: { currentTime: 0, pause() {} } } });
    h.fire(handles(h)[0], "onPointerDown", event({ currentTarget: cap("trim-in") }));
    h.fire(handles(h)[1], "onPointerDown", event({ currentTarget: cap("trim-out") }));
    h.fire(one(cls(h, "lm-review-scrubtrack")), "onPointerDown", event({ currentTarget: cap("scrub") }));
    h.fire(one(cls(h, "lm-review-croprect")), "onPointerDown", event({ currentTarget: cap("crop") }));
    assert.deepEqual(captured, ["trim-in", "trim-out", "scrub", "crop"]);
  });

  test("the fraction is read off the STATIC track, not the handle being dragged", () => {
    const h = review();
    h.fire(handles(h)[0], "onPointerDown", onHandle(75));   // 75 of 300px
    near(h.card("c2").trimIn, 1.5, "trimIn");
  });

  test("the handles keep the design's minimum gap (0.05 of the clip) between in and out", () => {
    const h = review({ trimOut: 3 });                       // out at 0.5
    h.fire(handles(h)[0], "onPointerDown", onHandle(270));  // in asks for 0.9
    near(h.card("c2").trimIn, 0.45 * 6, "trimIn stops 0.05 short of out");
    const g = review({ trimIn: 3 });                        // in at 0.5
    g.fire(handles(g)[1], "onPointerDown", onHandle(30));   // out asks for 0.1
    near(g.card("c2").trimOut, 0.55 * 6, "trimOut stops 0.05 past in");
  });

  test("the fraction is stored on the card as ABSOLUTE SECONDS (this codebase's trimIn/trimOut unit)", () => {
    const vid = { currentTime: 0, pause() {} };
    const h = phone({ sel: "c2", state: { reviewOpen: true, reviewDur: 8 }, refs: { reviewTrimTrackRef: TRACK, reviewVidRef: vid } });
    h.fire(handles(h)[1], "onPointerDown", onHandle(225));   // 0.75 of an 8 s clip
    near(h.card("c2").trimOut, 6, "trimOut in seconds");
    near(vid.currentTime, 6, "the video jumps to the new out point");
    h.fire(handles(h)[1], "onPointerMove", onHandle(150));
    near(h.card("c2").trimOut, 4, "a move keeps writing seconds");
    assert.deepEqual(h.calls("setCard").map((c) => [c[0], c[1]]), [["a1", "c2"], ["a1", "c2"]]);
  });

  test("the readout shows both trim points in seconds, one decimal", () => {
    assert.equal(one(markup(review({ trimIn: 0.25, trimOut: 4 })).byClass("lm-review-trimreadout")).text, "0.3s → 4.0s");
  });
});

describe("Review & trim: crop-rectangle drag -- a port of the design's own _cropFrac/_cropDragMove", () => {
  const cropping = () => phone({ sel: "c2", state: { reviewOpen: true, reviewCropping: true }, refs: { reviewVidRef: { currentTime: 0 } } });
  // The preview box is 100x100 at (0, 0); the crop rect itself is a moving target the math must not read.
  const over = (clientX, clientY) => event({ clientX, clientY, currentTarget: {
    setPointerCapture() {}, getBoundingClientRect: () => ({ left: 777, top: 777, width: 5, height: 5 }),
    parentElement: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }) } } });
  const dragCrop = (h, x, y) => {
    h.fire(one(cls(h, "lm-review-croprect")), "onPointerDown", over(x, y));
    h.fire(one(cls(h, "lm-review-croprect")), "onPointerMove", over(x, y));
    return h.card("c2").crop;
  };

  test("the fraction is read off the preview box the rect sits in (parentElement), not the rect", () => {
    const crop = dragCrop(cropping(), 50, 60);
    near(crop.x, 0.35, "x"); near(crop.y, 0.45, "y");
    assert.deepEqual([crop.w, crop.h], [0.3, 0.3]);
  });

  test("the box centres on the pointer (minus 0.15) and stays on the frame (0 .. 0.68)", () => {
    const far = dragCrop(cropping(), 100, 100);
    assert.deepEqual([far.x, far.y], [0.68, 0.68]);
    const near0 = dragCrop(cropping(), 5, 0);
    assert.deepEqual([near0.x, near0.y], [0, 0]);
  });

  test("the crop rect renders only while cropping", () => {
    assert.equal(markup(phone({ sel: "c2", state: { reviewOpen: true } })).byClass("lm-review-croprect").length, 0);
    assert.equal(markup(cropping()).byClass("lm-review-croprect").length, 1);
  });

  test("the Crop/Done button flips its label and the cropping state", () => {
    const h = phone({ sel: "c2", state: { reviewOpen: true } });
    const b = () => one(cls(h, "lm-review-cropbtn"));
    assert.equal(textOf(b()), "⛶ Crop");
    h.click(b());
    assert.equal(textOf(b()), "⛶ Done");
    assert.ok(classOf(b()).includes("on"));
    assert.equal(cls(h, "lm-review-croprect").length, 1);
  });
});

describe("Review & trim: split-at-playhead calls the splitCardAt-backed mutator App hands down", () => {
  const review = (t) => phone({ sel: "c2", state: { reviewOpen: true }, refs: { reviewVidRef: { currentTime: t, pause() {} } } });

  test("Split at playhead splits the live shot at the video's own time through splitShot, then closes Review", () => {
    const h = review(2.5);
    h.click(btn(h, "Split at playhead"));
    assert.deepEqual(h.calls("splitShot"), [[h.entry("c2"), 2.5]]);
    assert.equal(cls(h, "lm-review").length, 0);
    // ...and that splitShot is App's own (useShotMutations), on the phone.
    const a = app({ view: "mobile" });
    const p = viewOf(a).props;
    a.act(() => p.splitShot(p.entries[1], 2.5));
    assert.equal(boardOf(a).acts[0].cards.length, 4, "App's board now has the two halves");
  });

  test("a split too near either edge (0.15 s) is refused with ShotPreview's own message", () => {
    for (const t of [0.1, 5.9]) {
      browser.alerts = [];
      const h = review(t);
      h.click(btn(h, "Split at playhead"));
      assert.deepEqual(h.calls("splitShot"), []);
      assert.deepEqual(browser.alerts, ["Move the playhead to where you want the cut first (not at either edge)."]);
      assert.equal(cls(h, "lm-review").length, 1, "Review stays open");
    }
  });
});

describe("Generate: real submit, real cost preview, real generation-state tracking", () => {
  const gen = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, genOpen: true, ...opts.state } });
  const screen = (h) => one(cls(h, "lm-gen"), "Generate");

  test("Shot Detail's 'Select in Generate →' opens the Generate screen on that shot", () => {
    const h = phone({ sel: "c1", state: { dfOpen: true } });
    assert.equal(cls(h, "lm-gen").length, 0);
    h.click(btn(one(cls(h, "lm-df")), "Select in Generate"));
    assert.equal(textOf(one(cls(screen(h), "lm-gen-back"))), "‹ A·01");
  });

  test("priceShot (handed down from useGenerationPipeline) prices the shot-shaped payload, read-only", async () => {
    const h = app({ view: "mobile" });
    const { priceShot, entries, project } = viewOf(h).props;
    browser.reply = () => ({ cost: 300, free: false });
    assert.deepEqual(await priceShot(entries[0]), { cost: 300, free: false });
    assert.deepEqual(browser.trail, [["fetch", "/api/price", JSON.parse(JSON.stringify(shotPayload(entries[0], project, imgSrcOf({}))))]]);
  });

  test("Mode chips render the real MODES array inside the Generate screen too, writing through setShotMode", () => {
    const h = gen();
    const chips = els(cls(screen(h), "lm-modechips")[0]).filter((e) => e.type === "button");
    assert.deepEqual(chips.map(textOf), MODES);
    const before = h.card("c1");
    h.click(els(cls(screen(h), "lm-modechips")[0]).find((e) => e.type === "button" && textOf(e) === "V2V"));
    assert.deepEqual(h.card("c1"), setShotMode(before, "V2V"));
  });

  test("Continuity chips render the real CONNECT map, writing through setShotConnect", () => {
    const h = gen();
    const row = () => els(cls(screen(h), "lm-modechips")[1]).filter((e) => e.type === "button");
    assert.deepEqual(row().map(textOf), Object.keys(CONNECT).map((k) => CONNECT[k].label));
    assert.deepEqual(row().filter((c) => classOf(c).includes("on")).map(textOf), [CONNECT.cut.label]);
    const key = Object.keys(CONNECT).find((k) => k !== "cut");
    const before = h.card("c1");
    h.click(row().find((c) => textOf(c) === CONNECT[key].label));
    assert.deepEqual(h.card("c1"), setShotConnect(before, key));
  });

  test("which frame previews show is mode-aware (usesCloseFrame): I2V one, FLF/R2V both", () => {
    const frames = (sel) => {
      const g = one(markup(gen({ sel })).byClass("lm-gen"));
      return [g.byText(/^Start( \/ end)? frame$/)[0].text, g.byClass("lm-genframecol").length];
    };
    assert.deepEqual(frames("c2"), ["Start frame", 1]);
    assert.deepEqual(frames("c3"), ["Start / end frame", 2]);
    assert.deepEqual(frames("c1"), ["Start / end frame", 2]);
  });

  test("'What will be sent' is shotText() itself", () => {
    const h = gen();
    assert.equal(one(markup(h).byClass("lm-genpreview")).text, shotText(h.entry("c1"), h.props.project, imgSrcOf({})));
  });

  test("Generate audio shows and writes c.audioGen, with the five audio_language values the drawer uses", () => {
    const h = gen();
    const box = () => one(els(screen(h)).filter((e) => e.type === "label" && /Generate audio/.test(textOf(e)))
      .flatMap((l) => ofType(l, "input")));
    assert.equal(box().props.checked, false);
    assert.equal(markup(h).byTag("select").filter((s) => s.byTag("option").some((o) => o.attr("value") === "korean")).length, 0,
      "no language picker while audio is off");
    h.fire(box(), "onChange", { target: { checked: true } });
    assert.equal(h.card("c1").audioGen, true);
    const lang = one(markup(h).byTag("select").filter((s) => s.byTag("option").some((o) => o.attr("value") === "korean")));
    assert.deepEqual(lang.byTag("option").map((o) => o.attr("value")), ["english", "japanese", "chinese", "korean", "none"]);
    assert.deepEqual(lang.byAttr("selected").map((o) => o.attr("value")), ["english"]);
  });

  test("the cost line is tallyPrices/formatCostEstimate/costTooltip over the shot's price -- or says why there is none", () => {
    const pr = { cost: 1200, free: false, cards: [], note: "" };
    const tally = tallyPrices([pr]);
    const cost = (genPrice) => one(markup(gen({ state: { genPrice } })).byClass("lm-gencosttext"));
    assert.equal(cost({ c1: { loading: false, pr } }).text, formatCostEstimate(tally));
    assert.equal(cost({ c1: { loading: false, pr } }).attr("title"), costTooltip(tally));
    const free = { cost: 0, free: true, cards: [{}], note: "" };
    assert.equal(cost({ c1: { loading: false, pr: free } }).text, formatCostEstimate(tallyPrices([free])));
    assert.equal(cost({ c1: { loading: true } }).text, "checking…");
    assert.equal(cost({ c1: { noInput: true } }).text, "attach a frame or cast image first");
    assert.equal(cost({}).text, "—", "unpriced is never a number");
    assert.equal(btn(gen({ state: { genPrice: { c1: { noInput: true } } } }), "Generate video").props.disabled, true);
  });

  test("the Video tab's cost line is priced by priceShot(dfLive), debounced, and never for a shot with nothing to send", async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const pr = { cost: 400, free: false, cards: [], note: "" };
    const asked = [];
    const h = gen({ props: { priceShot: (entry) => { asked.push(entry); return Promise.resolve(pr); } } });
    h.flush();
    assert.equal(one(markup(h).byClass("lm-gencosttext")).text, "checking…");
    t.mock.timers.tick(299);
    assert.deepEqual(asked, []);
    t.mock.timers.tick(1);
    assert.deepEqual(asked, [h.entry("c1")], "the live shot itself");
    await settle(); h.render();
    assert.equal(one(markup(h).byClass("lm-gencosttext")).text, formatCostEstimate(tallyPrices([pr])));
    // The empty FLF shot has no frame and no cast: nothing is priced, and the button stays shut.
    const asked3 = [];
    const e = gen({ sel: "c3", props: { priceShot: (x) => { asked3.push(x); return Promise.resolve(pr); } } });
    e.flush();
    t.mock.timers.tick(1000);
    assert.deepEqual(asked3, []);
    assert.equal(one(markup(e).byClass("lm-gencosttext")).text, "attach a frame or cast image first");
    // A shot that is NOT the board's first, with something to send: it is the one priced.
    const asked2 = [];
    const second = gen({ sel: "c2", board: makeBoard({ c2: { openFrame: frame({ mediaId: "100002" }) } }),
      props: { priceShot: (x) => { asked2.push(x); return Promise.resolve(pr); } } });
    second.flush();
    t.mock.timers.tick(300);
    assert.deepEqual(asked2, [second.entry("c2")], "the selected shot, not the first one");
  });

  // Kept as a source pin: what the submit must NOT do (a second confirm skipped, a second POST).
  test("the real submit button calls generateShot(dfLive) UNMODIFIED -- no skipConfirm, no new confirm dialog, no new endpoint", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /className="lm-genbtn"[\s\S]*?onClick=\{genSubmit\}/);
    assert.doesNotMatch(loomMobileSrc, /generateShot\(dfLive, \{\s*skipConfirm/,
      "a single, owner-initiated tap must still go through generateShot's own real price-check + confirm, same as it would for any other real single submit");
    assert.match(loomMobileSrc, /r = await generateShot\(dfLive\);/);
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/loom\/generate["']/,
      "Loom Mobile must not submit through a second, independent /api/loom/generate call -- generateShot is the one real submit path");
  });

  test("'Use an existing video instead' attaches through useExistingVideo(dfLive) -- no spend", () => {
    const h = gen();
    h.click(btn(screen(h), "Use an existing video instead"));
    assert.deepEqual(h.calls("useExistingVideo"), [[h.entry("c1")]]);
    assert.deepEqual(browser.trail, []);
  });

  // Kept as a source pin: the absence of a second, local genState -- nothing to render.
  test("closing Generate or Shot Detail never touches genState/pollShot/generateShot -- both are plain local LoomMobile booleans", () => {
    // The credit-safety contract this increment's own report explains in full: genOpen/dfOpen
    // gate JSX only. The real generation-tracking state (genState) and its poll loop
    // (pollShot's recursive setTimeout chain, inside useGenerationPipeline) live in App(),
    // are passed down as a read-only prop, and are never declared or reset anywhere in
    // LoomMobile -- so no LoomMobile-local state transition (this screen closing, Shot Detail
    // closing, or the Mobile-view toggle unmounting LoomMobile entirely) can ever orphan an
    // in-flight generation.
    assert.match(loomMobileSrc, /const \[genOpen, setGenOpen\] = useState\(false\);/);
    assert.doesNotMatch(loomMobileSrc, /const \[genState, setGenState\] = useState/,
      "genState must remain a prop LoomMobile reads, never a second local copy of its own");
  });
});

describe("Image/Edit/Reference tabs -- LoomV2's own GEN_ICONS rail, ported", () => {
  const gen = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, genOpen: true, ...opts.state } });
  const tabRow = (h) => one(cls(one(cls(h, "lm-gen")), "lm-tabsrow").filter((r) => textOf(r) === "ImageEditReferenceVideo"));

  test("a 4-tab strip in LoomV2's GEN_ICONS order (Image, Edit, Reference, Video), opening on Video", () => {
    const h = gen();
    const tabs = () => els(tabRow(h)).filter((e) => e.type === "button");
    assert.deepEqual(tabs().map(textOf), ["Image", "Edit", "Reference", "Video"]);
    assert.deepEqual(tabs().filter((t) => classOf(t).includes("on")).map(textOf), ["Video"]);
    h.click(tabs()[0]);
    assert.deepEqual(tabs().filter((t) => classOf(t).includes("on")).map(textOf), ["Image"]);
    assert.ok(markup(h).byText("Image prompt").length >= 1);
  });

  test("App hands LoomMobile the pipeline's own Image/Edit/Reference/Fix state, setters and entry points", () => {
    const h = app({ view: "mobile" });
    const p = viewOf(h).props;
    for (const n of ["genImgState", "imgModel", "imgLoras", "imgAdv", "modelDefaults", "genEditState", "genRefState", "genFixState"]) {
      assert.equal(p[n], h.state(n), n + " is App's own state");
    }
    for (const n of ["imgModel", "imgLoras", "imgAdv", "modelDefaults", "genEditState", "genRefState", "genFixState"]) {
      assert.equal(p["set" + n[0].toUpperCase() + n.slice(1)], h.setter(n), "set" + n);
    }
    for (const n of ["genImage", "routeImg", "genEdit", "genRef", "routeGen", "genFix", "generateShot", "priceShot", "useExistingVideo"]) {
      assert.equal(typeof p[n], "function", n);
    }
    assert.equal(p.genState, h.state("genState"), "genState is App's own state");
    // Kept as a source pin for the money path's entry points: a typeof check cannot tell
    // generateShot from batchGenerate (or a no-op), or genEdit from genRef, and every other test
    // here hands LoomMobile recorder props -- so the call site is read for its exact wiring.
    // ('Generate video' calls generateShot; the Image/Edit/Reference Go buttons call genImage/
    // genEdit/genRef. genFix, priceShot and the board mutators are driven through App elsewhere.)
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const n of ["generateShot", "useExistingVideo", "genImage", "genEdit", "genRef", "routeImg", "routeGen"]) {
      assert.ok(loomMobileCall[0].includes(n + "={" + n + "}"), "expected \"" + n + "={" + n + "}\" at the <LoomMobile .../> call site");
    }
  });

  test("the same props reach LoomMobile and LoomV2 from ONE useGenerationPipeline: a model picked on one is the other's", () => {
    const h = app({ view: "mobile" });
    const model = { model_id: "m1", title: "Model one" };
    h.act(() => viewOf(h).props.setImgModel(model));
    viewOf(h).props.setMobileUI(false);
    h.render();
    assert.equal(viewOf(h).type, LoomV2);
    assert.equal(viewOf(h).props.imgModel, model);
    assert.equal(viewOf(h).props.setImgModel, h.setter("imgModel"));
  });

  test("Image/Edit/Reference Go buttons submit the live shot through genImage/genEdit/genRef -- no confirm or request of their own", () => {
    const model = { model_id: "m1", title: "Model one", model_type: "SDXL", version_id: "v1" };
    const img = gen({ board: makeBoard({ c1: { imgPrompt: "neon alley" } }), state: { genTab: "Image" }, props: { imgModel: model } });
    img.click(btn(img, "✦ Generate reference image"));
    const edit = gen({ state: { genTab: "Edit" } });
    edit.click(btn(edit, "✦ Edit the open frame"));
    const ref = gen({ state: { genTab: "Reference" } });
    ref.click(btn(ref, "✦ Generate from references"));
    assert.deepEqual(img.calls("genImage"), [[img.entry("c1")]]);
    assert.deepEqual(edit.calls("genEdit"), [[edit.entry("c1")]]);
    assert.deepEqual(ref.calls("genRef"), [[ref.entry("c1")]]);
    assert.deepEqual(browser.trail, [], "the gate (confirmSpend) and the POST live inside genImage/genEdit/genRef");
    // Kept as source pins beside the clicks: a forked submit or confirm in ANOTHER handler or an
    // effect has no click to show it, so its absence is read from LoomMobile's own source.
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/generate["']/,
      "genImage() already owns the real /api/generate submit -- LoomMobile must not duplicate it");
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/edit["']/,
      "genEdit()/genRef() already own the real submit via runGen() -- LoomMobile must not duplicate it");
    // Scoped to the Generate screen's own block: the kebab sheet's Delete legitimately confirms.
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.doesNotMatch(genBlock, /window\.confirm\(/,
      "confirmSpend's fail-closed window.confirm gate lives inside genImage/genEdit/genRef themselves -- LoomMobile must not re-implement it");
  });

  test("a result routes into open/close frame or cast through routeImg / routeGen, bound to the live shot", () => {
    const genImgState = { c1: { phase: "done", mid: "500005" } };
    const genEditState = { c1: { phase: "done", mid: "500006" } };
    const genRefState = { c1: { phase: "done", mid: "500007" } };
    const setGenEditState = () => {}, setGenRefState = () => {};
    const props = { genImgState, genEditState, genRefState, setGenEditState, setGenRefState };
    const routes = (tab) => {
      const h = gen({ state: { genTab: tab }, props });
      for (const label of ["open frame", "close frame", "cast"]) h.click(btn(one(cls(h, "lm-route")), label));
      return h;
    };
    const i = routes("Image");
    assert.deepEqual(i.calls("routeImg"), ["open", "close", "cast"].map((tg) => [i.entry("c1"), tg, "c1"]));
    const e = routes("Edit");
    assert.deepEqual(e.calls("routeGen"), ["open", "close", "cast"].map((tg) => [genEditState, setGenEditState, e.entry("c1"), tg, "c1"]));
    const r = routes("Reference");
    assert.deepEqual(r.calls("routeGen"), ["open", "close", "cast"].map((tg) => [genRefState, setGenRefState, r.entry("c1"), tg, "c1"]));
  });

  test("the Image/Edit/Reference previews price LoomV2's own priceInto bodies, and show them through tallyPrices", async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const pr = { cost: 70, free: false, cards: [], note: "" };
    browser.reply = (url) => (url === "/api/price" ? pr : {});
    const model = { model_id: "m1", title: "Model one", model_type: "SDXL", version_id: "v1" };
    const board = makeBoard({ c1: { imgPrompt: "neon alley", editPrompt: "make it night", refPrompt: "two of them" } });
    const bodies = {};
    for (const tab of ["Image", "Edit", "Reference"]) {
      browser.trail = [];
      const h = gen({ board, state: { genTab: tab }, props: { imgModel: model } });
      h.flush();
      t.mock.timers.tick(250);
      bodies[tab] = fetched("/api/price").map((x) => x[2]);
      await settle(); h.render();
      assert.equal(one(markup(h).byClass("lm-gencosttext")).text, formatCostEstimate(tallyPrices([pr])), tab);
    }
    assert.deepEqual(bodies.Image, [JSON.parse(JSON.stringify(buildImgGenBody(model, [], IMG_ADV, "neon alley")))]);
    assert.deepEqual(bodies.Edit, [{ mode: "edit", source: MID.open1, instruction: "make it night", edit_model: "edit-pro" }]);
    assert.deepEqual(bodies.Reference, [{ mode: "edit", source: MID.her, sources: [MID.her], instruction: "two of them", edit_model: "reference-pro" }]);
  });

  test("the model/LoRA sheet mounts the shared <ModelPicker> twice: base (controlled value, onPick) and LoRA (multi, selected, onToggle)", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const model = { model_id: "m1", title: "Model one", model_type: "SDXL" };
    const loras = [{ model_id: "l1", title: "Lora one", weight: 0.8 }];
    const h = gen({ state: { genTab: "Image", pickerOpen: true, pickerMounted: true }, props: { imgModel: model, imgLoras: loras } });
    const [base, lora] = ofType(h, ModelPicker);
    assert.deepEqual([base.props.kind, base.props.visible, base.props.value], ["base", true, model]);
    assert.equal(base.props.value, model);
    assert.deepEqual([lora.props.kind, lora.props.multi, lora.props.baseType, lora.props.visible], ["lora", true, "SDXL", false]);
    assert.equal(lora.props.selected, loras);
    // onPick sets the model (and closes the sheet); onToggle adds/removes a LoRA.
    h.act(() => base.props.onPick({ model_id: "m2", title: "Model two", preview_url: "/p.png" }));
    assert.deepEqual(h.calls("setImgModel")[0], [{ model_id: "m2", title: "Model two", preview_url: "/p.png" }]);
    assert.deepEqual(fetched("/api/model-version").map((x) => x[1]), ["/api/model-version?model_id=m2&all=1"]);
    h.act(() => lora.props.onToggle({ model_id: "l2", title: "Lora two" }, true));
    const updater = h.calls("setImgLoras").at(-1)[0];
    assert.deepEqual(updater(loras).map((l) => l.model_id), ["l1", "l2"]);
    h.act(() => lora.props.onToggle({ model_id: "l1" }, false));
    assert.deepEqual(h.calls("setImgLoras").at(-1)[0](loras), []);
  });

  test("Image tab field parity: Aspect, Size, Custom W×H, Seed, High priority, Prompt helper, and the W × H readout", () => {
    const model = { model_id: "m1", title: "Model one", model_type: "SDXL" };
    const $ = one(markup(gen({ state: { genTab: "Image" }, props: { imgModel: model } })).byClass("lm-gen"));
    for (const label of ["Aspect", "Size · long edge", "Custom W×H", "Seed · blank = random"]) {
      assert.equal($.byText(label).filter((e) => e.attr("class") === "lm-microlab").length, 1, label);
    }
    for (const label of ["High priority · Turbo (faster)", "Prompt helper"]) {
      assert.equal($.byText(label).filter((e) => e.tag === "label").length, 1, label);
    }
    // The readout uses the picked model's own size grid (SCOPE_2026-09-26 G1).
    const d = resolveGenDims(IMG_ADV, genStepFor("SDXL"));
    assert.equal(one($.byText(/^→ \d+ × \d+/)).text, "→ " + d.w + " × " + d.h + " px");
  });
});

describe("Credit safety: generation polls live above both views, so the Mobile-view flip never orphans one", () => {
  test("the resume scan re-attaches a poll for every wip shot with a live task id, and never twice for one task", () => {
    /* WHAT the effect does, run rather than read. This used to assert the hook's whole
       destructuring signature character for character, which a harmless param reorder
       breaks and a genuinely mis-wired hook does not.

       The scan is idempotent by TASK ID, not by trigger: that is what lets it be re-run on
       every "📱 Mobile view" flip -- which unmounts LoomV2 and any <mg-generate-drawer>
       inside it outright, with no 'mg-paused' event -- without any double-poll risk. */
    const resumed = Object.create(null);
    const board = { acts: [{ cards: [
      { id: "a", status: "wip", pendingTaskId: "T1", genStartedAt: 111 },
      { id: "b", status: "done", resultMid: "m1" },
      { id: "c", status: "wip" },                       // never submitted: nothing to resume
      { id: "d", status: "wip", pendingTaskId: "T2" },
    ] }] };
    assert.deepEqual(cardsToResume(board, resumed), [
      { id: "a", taskId: "T1", startedAt: 111 },
      { id: "d", taskId: "T2", startedAt: undefined },
    ]);
    // the flip fires it again: a genuine no-op for everything already polling
    assert.deepEqual(cardsToResume(board, resumed), []);
    // ...and a shot submitted AFTER that flip is picked up on the next one
    board.acts[0].cards.push({ id: "e", status: "wip", pendingTaskId: "T3" });
    assert.deepEqual(cardsToResume(board, resumed).map((c) => c.taskId), ["T3"]);
    // a task id spelled like an Object.prototype key is still a task id
    board.acts[0].cards.push({ id: "f", status: "wip", pendingTaskId: "constructor" });
    assert.deepEqual(cardsToResume(board, resumed).map((c) => c.taskId), ["constructor"]);
    assert.deepEqual(cardsToResume(null, resumed), []);
  });

  test("App's own mobileUI drives the resume scan: a Mobile-view flip re-attaches a render left in flight, once", async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    browser.reply = (url) => (url.startsWith("/api/task-status") ? { status: "running" } : {});
    const board = makeBoard({ c1: { status: "wip", pendingTaskId: "T1" } });
    const h = app({ board, view: "mobile" });
    const RESUME = /resumeInterrupted\(\)/;
    const phaseOf = (id) => (h.state("genState")[id] || {}).phase;
    h.flush(RESUME);
    assert.equal(phaseOf("c1"), "running", "the board's own in-flight render is polled on open");
    // A render the desktop drawer started lands on the board as wip + task id...
    h.act(() => viewOf(h).props.setCard("a1", "c2", (c) => ({ ...c, status: "wip", pendingTaskId: "T2" })));
    h.flush(RESUME);
    assert.equal(phaseOf("c2"), undefined, "nothing re-scans without a trigger");
    // ...and the flip that unmounts that drawer is the trigger that picks it up.
    viewOf(h).props.setMobileUI(false);
    h.render();
    h.flush(RESUME);
    assert.equal(phaseOf("c2"), "running", "the Mobile-view flip re-ran the resume scan and picked up T2");
    t.mock.timers.tick(2500);
    await settle();
    assert.deepEqual(fetched("/api/task-status").map((x) => x[1]).sort(),
      ["/api/task-status?task_id=T1", "/api/task-status?task_id=T2"], "one poll per task, never two");
  });

  // Kept as a source pin: a banned pattern (a poll tied to a DOM element's lifecycle).
  test("genImage/genEdit/genRef's own polls are plain setTimeout chains (pollImg/pollTaskWithCeiling), never a DOM element's lifecycle -- confirmed, not just asserted", () => {
    // pollTaskWithCeiling is a closure inside useGenerationPipeline itself -- no
    // connectedCallback/disconnectedCallback anywhere near it, unlike mg-generate-drawer.js's
    // own _poll (which explicitly tears down _pollTimers on disconnect -- see that file).
    assert.match(src, /const pollTaskWithCeiling = \(tid, setState, cardId\) => \{/);
    assert.doesNotMatch(src.slice(src.indexOf("const pollTaskWithCeiling"), src.indexOf("const pollImg = (cardId, tid)")),
      /disconnectedCallback|connectedCallback/,
      "pollTaskWithCeiling must never be tied to a custom element's connect lifecycle");
  });
});

// Filter compare (the locked design's "Art filters" screen): PixAI's free, client-side art-filter
// engine (gallery/src/art/artFilters.js) over the shot's open frame, saved as card fields.
describe("Filter compare: the real art-filter engine, not a fork", () => {
  const compare = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, fcOpen: true, ...opts.state }, refs: opts.refs });
  const firstId = () => AF.groups()[0].ids[0];

  test("the swatch grid is the engine's own AF.groups(): its labels, its ids, its names", () => {
    const fc = one(markup(compare()).byClass("lm-fc"));
    const groups = AF.groups();
    assert.ok(groups.length >= 2 && groups.every((g) => g.ids.length > 0));
    assert.deepEqual(fc.byClass("lm-fc-grouplabel").map((g) => g.text), groups.map((g) => g.label));
    assert.deepEqual(fc.byClass("lm-fc-grid").map((g) => g.byClass("lm-fc-tile").length), groups.map((g) => g.ids.length));
    const names = groups.flatMap((g) => g.ids.map((id) => ((AF.get(id) || {}).name || id).replace("Filter ", "")));
    assert.deepEqual(fc.byClass("lm-fc-name").map((n) => n.text), names);
  });

  test("each tile paints itself through AF.renderSwatch(el, id), once per element", (t) => {
    const painted = [];
    t.mock.method(AF, "renderSwatch", (el, id) => painted.push([el, id]));
    const swatches = cls(compare(), "lm-fc-swatch");
    const el = {};
    swatches[0].ref(el);
    swatches[0].ref(el);
    swatches[0].ref(null);
    assert.deepEqual(painted, [[el, firstId()]]);
  });

  test("the live preview composites through AF.applyPreview / AF.clearPreview on the preview stage", (t) => {
    const log = [];
    t.mock.method(AF, "clearPreview", (host) => log.push(["clear", host]));
    t.mock.method(AF, "applyPreview", (host, id, o) => log.push(["apply", host, id, o]));
    const stage = {};
    const h = compare({ state: { fcActive: firstId(), fcStrength: 0.6, fcAngle: 45 }, refs: { fcStageRef: stage } });
    h.flush();
    assert.deepEqual(log, [["clear", stage], ["apply", stage, firstId(), { strength: 0.6, angle: 45 }]]);
    log.length = 0;
    h.unmount();
    assert.deepEqual(log, [["clear", stage]]);
  });

  test("a real <img> renders on BOTH sides (Original and Preview)", () => {
    const imgs = one(markup(compare()).byClass("lm-fc")).byClass("lm-fc-img");
    assert.deepEqual(imgs.map((i) => [i.tag, i.attr("alt")]), [["img", "original"], ["img", "preview"]]);
  });

  test("both images are this shot's own open frame (frameSrc), and a shot without one says so", () => {
    const thumbs = { t1: "data:image/png;base64,BBBB" };
    const own = one(markup(compare({ board: makeBoard({ c1: { openFrame: frame({ thumbId: "t1" }) } }), props: { thumbs } })).byClass("lm-fc"));
    assert.deepEqual(own.byClass("lm-fc-img").map((i) => i.attr("src")), [thumbs.t1, thumbs.t1]);
    const none = one(markup(compare({ sel: "c3" })).byClass("lm-fc"));
    assert.equal(none.byClass("lm-fc-img").length, 0);
    assert.equal(none.byText("No open-frame image yet").length, 2);
  });
});

describe("Filter compare: reached from Generate's Edit tab via the Edit/Fixer/Enhance sub-strip", () => {
  const editTab = (opts = {}) => phone({ sel: "c1", ...opts, state: { dfOpen: true, genOpen: true, genTab: "Edit", ...opts.state } });
  const strip = (h) => one(cls(h, "lm-tabsrow").filter((r) => textOf(r) === "EditFixerEnhance"), "Edit sub-strip");

  test("the Edit tab opens on its Edit chip", () => {
    const h = editTab();
    assert.equal(h.state("editSub"), "edit");
    assert.deepEqual(els(strip(h)).filter((e) => e.type === "button" && classOf(e).includes("on")).map(textOf), ["Edit"]);
    assert.ok(markup(h).byText("Edit instruction").length >= 1);
  });

  test("the sub-strip uses the same .lm-tabsrow/.lm-tabbtn chrome as the Cast sheet's own tab strip", () => {
    const sub = one(markup(editTab()).byClass("lm-tabsrow").filter((r) => r.text === "EditFixerEnhance"));
    assert.deepEqual(sub.byTag("button").map((b) => b.classes), [["lm-tabbtn", "on"], ["lm-tabbtn"], ["lm-tabbtn"]]);
    const castStrip = markup(phone({ sel: "c1", state: { dfOpen: true, castSheetOpen: true } })).byClass("lm-tabsrow")[0];
    assert.deepEqual(castStrip.byTag("button").map((b) => b.classes[0]), ["lm-tabbtn", "lm-tabbtn"]);
  });

  test("the Enhance chip's 'Open filters' button opens Filter compare", () => {
    const h = editTab({ state: { editSub: "enhance" } });
    assert.equal(cls(h, "lm-fc").length, 0);
    h.click(btn(h, "Open filters"));
    assert.equal(cls(h, "lm-fc").length, 1);
  });
});

describe("Filter compare: saved onto the real shot/card data (no fake 'saved' state)", () => {
  const editTab = (board) => phone({ sel: "c1", board, state: { dfOpen: true, genOpen: true, genTab: "Edit", editSub: "enhance" } });
  const open = (h) => { h.click(btn(h, "Open filters")); return h; };
  const fc = (h) => one(cls(h, "lm-fc"));

  test("opening shows the card's ALREADY-SAVED filter, strength and angle (or the defaults)", () => {
    const id = AF.groups()[0].ids[1];
    const saved = open(editTab(makeBoard({ c1: { filter: id, filterStrength: 0.4, filterAngle: 90 } })));
    const name = (AF.get(id) || {}).name || id;
    assert.equal(textOf(one(cls(fc(saved), "lm-fc-previewcap").filter((c) => /Preview/.test(textOf(c))))), "Preview · " + name);
    assert.deepEqual(cls(fc(saved), "lm-fc-sliderlab").map(textOf), ["Strength — 0.40", "Angle — 90°"]);
    const blank = open(editTab());
    assert.deepEqual(cls(fc(blank), "lm-fc-sliderlab").map(textOf), ["Strength — 1.00", "Angle — 180°"]);
    assert.equal(textOf(one(cls(fc(blank), "lm-fc-spendnote"))), "No filter · nothing sent, nothing spent");
  });

  test("filter/filterStrength/filterAngle stay OUT of a new card's base shape (read with a fallback)", () => {
    const keys = Object.keys(newCardShape("x"));
    for (const k of ["filter", "filterStrength", "filterAngle"]) assert.ok(!keys.includes(k), k + " in newCardShape");
    // ...and the Loom's own newCard() (App's addCard) makes a card without them too.
    const h = app();
    h.act(() => viewOf(h).props.addCard("a2"));
    const added = boardOf(h).acts[1].cards[0];
    assert.ok(added && added.id, "addCard added a shot to the empty act");
    for (const k of ["filter", "filterStrength", "filterAngle"]) assert.ok(!(k in added), k + " on a new card");
  });

  test("Save writes filter, filterStrength and filterAngle onto the card through setCard, and closes", () => {
    const id = AF.groups()[1].ids[0];
    const h = open(editTab());
    h.click(one(cls(fc(h), "lm-fc-tile").filter((t) => t.key === id)));
    const slider = (i) => els(fc(h)).filter((e) => e.type === "input" && e.props.type === "range")[i];
    h.fire(slider(0), "onChange", { target: { value: "0.35" } });   // strength
    h.fire(slider(1), "onChange", { target: { value: "270" } });    // angle
    assert.equal(h.card("c1").filter, undefined, "nothing is written until Save");
    h.click(btn(fc(h), "Save"));
    const c = h.card("c1");
    assert.deepEqual([c.filter, c.filterStrength, c.filterAngle], [id, 0.35, 270]);
    assert.equal(cls(h, "lm-fc").length, 0);
    assert.deepEqual(browser.trail, [], "nothing sent");
  });

  test("'No filter' removes the SAVED filter at once -- not a pending reset Close would discard", () => {
    const id = AF.groups()[0].ids[0];
    const h = open(editTab(makeBoard({ c1: { filter: id } })));
    h.click(btn(fc(h), "No filter"));
    assert.equal(h.card("c1").filter, null);
    assert.equal(cls(h, "lm-fc").length, 1, "still open");
  });

  test("Close/back is a plain cancel: it writes nothing to the card", () => {
    const h = open(editTab());
    h.click(cls(fc(h), "lm-fc-tile")[0]);
    h.click(one(cls(fc(h), "lm-gen-back")));
    assert.equal(cls(h, "lm-fc").length, 0);
    assert.deepEqual(h.calls("setCard"), []);
  });

  // Kept as a source pin: the absence of any network call in the block.
  test("no new /api endpoint, no fetch, backs Filter compare -- these are plain card fields, matching mg-art-filters.js's own 'nothing sent, nothing spent' contract", () => {
    const fcBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("Filter compare -- sixth and FINAL increment"));
    assert.doesNotMatch(fcBlock, /fetch\(/, "Filter compare must never touch the network -- it is free, offline, client-side compositing only");
  });
});

describe("Filter compare: real live-lookup safety (reuses dfLive, no second 'which shot' id invented)", () => {
  test("the screen renders only while it is open AND Shot Detail's shot is live", () => {
    assert.equal(cls(phone({ sel: "c1", state: { dfOpen: true, fcOpen: true } }), "lm-fc").length, 1);
    assert.equal(cls(phone({ sel: "c1", state: { fcOpen: true } }), "lm-fc").length, 0, "no Shot Detail underneath");
    assert.equal(cls(phone({ sel: "c1", state: { dfOpen: true } }), "lm-fc").length, 0, "not opened");
  });

  test("Filter compare never shows for a shot that vanished, and writes nothing to it", () => {
    // What this proves is the render gate (the screen draws only while dfLive is live). The
    // button clicked was captured before the shot went, so its closure still holds the old
    // dfLive: openFilterCompare's own `if (!dfLive) return;` is not reached from here, and no
    // rendered button can reach it.
    const h = phone({ sel: "c1", state: { dfOpen: true, genOpen: true, genTab: "Edit", editSub: "enhance" } });
    const openBtn = btn(h, "Open filters");
    const gone = makeBoard();
    gone.acts[0].cards = gone.acts[0].cards.filter((c) => c.id !== "c1");
    h.setProps({ project: gone, entries: flat(gone) });
    h.render();
    h.click(openBtn);
    assert.equal(cls(h, "lm-fc").length, 0);
    assert.equal(cls(h, "lm-df").length, 0);
    assert.deepEqual(h.calls("setCard"), []);
  });
});

// The per-shot-card kebab (⋮) actions sheet: Move up / Move down / Duplicate / Delete / Cancel,
// through the same moveCard/dupCard/delCard App hands LoomV2's own board-card buttons.
describe("Kebab actions sheet: App's own moveCard/dupCard/delCard, no forked logic", () => {
  const cardsOf = (h) => boardOf(h).acts[0].cards.map((c) => c.id);

  test("LoomMobile's moveCard/dupCard/delCard are App's own board mutators", () => {
    const h = app({ view: "mobile" });
    const p = () => viewOf(h).props;
    // The rows address a shot by flat()'s own a / ci / c: the entries App hands down ARE flat(board).
    assert.deepEqual(p().entries, flat(boardOf(h)));
    h.act(() => p().moveCard("a1", 0, 1));
    assert.deepEqual(cardsOf(h), ["c2", "c1", "c3"]);
    h.act(() => p().dupCard("a1", p().entries[0].c));
    assert.equal(cardsOf(h).length, 4);
    assert.deepEqual([cardsOf(h)[0], cardsOf(h)[2], cardsOf(h)[3]], ["c2", "c1", "c3"]);
    h.act(() => p().delCard("a1", boardOf(h).acts[0].cards[1]));
    assert.deepEqual(cardsOf(h), ["c2", "c1", "c3"]);
  });

  test("LoomV2 gets the very same mutators: they edit the one board App holds", () => {
    const h = app({ view: "desktop" });
    h.act(() => viewOf(h).props.delCard("a1", boardOf(h).acts[0].cards[0]));
    assert.deepEqual(cardsOf(h), ["c2", "c3"]);
    viewOf(h).props.setMobileUI(true);
    h.render();
    h.act(() => viewOf(h).props.moveCard("a1", 1, -1));
    assert.deepEqual(cardsOf(h), ["c3", "c2"]);
  });

  test("the kebab rows call the props App handed down (no local copy): a Move down on the phone moves App's shot", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const h = app({ view: "mobile" });
    const phoneView = mount(LoomMobile, { ...viewOf(h).props, selShot: "c1" }, { state: { actionsOpen: true } });
    phoneView.click(btn(phoneView, "Move down"));
    assert.deepEqual(cardsOf(h), ["c2", "c1", "c3"]);
  });
});

describe("Kebab actions sheet: the board-card ⋮ button", () => {
  test("every board card has a ⋮ <button> beside it -- a sibling in .lm-cardrow, never inside .lm-card", () => {
    const rows = markup(phone()).byClass("lm-cardrow");
    assert.equal(rows.length, 3);
    for (const row of rows) {
      const kebab = one(row.byClass("lm-kebab"));
      assert.equal(kebab.tag, "button");
      assert.equal(kebab.parent, row);
      assert.equal(kebab.text, "⋮");
      assert.equal(kebab.attr("title"), "More actions for this shot");
      assert.equal(one(row.byClass("lm-card")).byClass("lm-kebab").length, 0);
    }
  });

  test("tapping the kebab selects the shot and opens the actions sheet (and does not open the card)", () => {
    const h = phone();
    const ev = event();
    h.click(cls(h, "lm-kebab")[2], ev);
    assert.ok(ev.stopped);
    assert.deepEqual(h.calls("setSelShot"), [["c3"]]);
    assert.equal(cls(h, "lm-sheet").length, 1);
    assert.equal(cls(h, "lm-df").length, 0);
  });

  test("the kebab is unconditional: every card has one, reviewable or not", () => {
    const $ = markup(phone());
    assert.equal($.byClass("lm-kebab").length, $.byClass("lm-card").length);
    assert.equal($.byClass("lm-reviewbadge").length, 1, "only the finished shot is reviewable");
  });
});

describe("Kebab actions sheet: real live-lookup safety (mirrors dfLive/reviewLive exactly)", () => {
  test("the sheet acts on the selected shot (selShot), with no 'which shot' id of its own", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const h = phone({ sel: "c2", state: { actionsOpen: true } });
    h.click(btn(h, "Duplicate"));
    assert.deepEqual(h.calls("dupCard"), [["a1", h.card("c2")]]);
  });

  test("a stale reference (the shot vanished out from under it) closes the sheet instead of acting on it", () => {
    const h = phone({ sel: "gone", state: { actionsOpen: true } });
    assert.equal(cls(h, "lm-sheet").length, 0);
    assert.equal(h.state("actionsOpen"), false);
  });

  test("the sheet renders only while open AND its shot is live -- never an empty sheet", () => {
    assert.equal(cls(phone({ sel: "c1", state: { actionsOpen: true } }), "lm-sheet").length, 1);
    assert.equal(cls(phone({ sel: "c1" }), "lm-sheet").length, 0);
    assert.equal(cls(phone({ sel: null, state: { actionsOpen: true } }), "lm-sheet").length, 0);
  });
});

describe("Kebab actions sheet: the Cast sheet's own bottom-sheet convention, not a new one", () => {
  const frameOf = ($) => [one($.byClass("lm-scrim")).attr("class"), one($.byClass("lm-sheet")).attr("class"), one($.byClass("lm-sheethandle")).attr("class")];

  test("the sheet wraps with the same .lm-scrim/.lm-sheet/.lm-sheethandle as the Cast & assets sheet, closing state included", () => {
    const actions = markup(phone({ sel: "c1", state: { actionsOpen: true } }));
    const cast = markup(phone({ sel: "c1", state: { dfOpen: true, castSheetOpen: true } }));
    assert.deepEqual(frameOf(actions), ["lm-scrim", "lm-sheet", "lm-sheethandle"]);
    assert.deepEqual(frameOf(actions), frameOf(cast));
    const closing = markup(phone({ sel: "c1", state: { actionsOpen: true, actionsClosing: true } }));
    assert.deepEqual(frameOf(closing), ["lm-scrim closing", "lm-sheet closing", "lm-sheethandle"]);
  });

  test("Cancel is the same .lm-sheetclose button as the Cast sheet's Done", () => {
    const actions = one(markup(phone({ sel: "c1", state: { actionsOpen: true } })).byClass("lm-sheetclose"));
    assert.deepEqual([actions.tag, actions.text], ["button", "Cancel"]);
    const cast = one(markup(phone({ sel: "c1", state: { dfOpen: true, castSheetOpen: true } })).byClass("lm-sheetclose"));
    assert.deepEqual([cast.tag, cast.text], ["button", "Done"]);
  });
});

describe("Kebab actions sheet: the rows call the mutators with flat()'s own a.id / ci / c", () => {
  const sheet = (t, sel = "c2") => { t.mock.timers.enable({ apis: ["setTimeout"] }); return phone({ sel, state: { actionsOpen: true } }); };

  test("Move up calls moveCard(the shot's act id, its index, -1) and closes", (t) => {
    const h = sheet(t);
    h.click(btn(h, "Move up"));
    assert.deepEqual(h.calls("moveCard"), [["a1", 1, -1]]);
    assert.equal(h.state("actionsClosing"), true);
  });

  test("Move down calls moveCard(the shot's act id, its index, 1) and closes", (t) => {
    const h = sheet(t, "c3");
    h.click(btn(h, "Move down"));
    assert.deepEqual(h.calls("moveCard"), [["a1", 2, 1]]);
    assert.equal(h.state("actionsClosing"), true);
  });

  test("Duplicate calls dupCard(the shot's act id, the card itself) and closes", (t) => {
    const h = sheet(t);
    h.click(btn(h, "Duplicate"));
    assert.deepEqual(h.calls("dupCard"), [["a1", h.card("c2")]]);
    assert.equal(h.state("actionsClosing"), true);
  });

  test("a shot in the SECOND act is addressed by its own act id, never the board's first act", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const board = makeBoard();
    board.acts[1].cards = [newCardShape("c4", { title: "Turn", duration: 3 }), newCardShape("c5", { title: "After", duration: 3 })];
    const row = (label) => {
      const h = phone({ board, sel: "c5", state: { actionsOpen: true } });
      h.click(btn(h, label));
      return h;
    };
    assert.deepEqual(row("Move up").calls("moveCard"), [["a2", 1, -1]]);
    assert.deepEqual(row("Move down").calls("moveCard"), [["a2", 1, 1]]);
    const dup = row("Duplicate");
    assert.deepEqual(dup.calls("dupCard"), [["a2", dup.card("c5")]]);
  });

  test("Cancel and the scrim both play the 280 ms close: the closing state first, then the sheet goes", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    for (const which of ["Cancel", "scrim"]) {
      const h = phone({ sel: "c2", state: { actionsOpen: true } });
      h.click(which === "Cancel" ? btn(h, "Cancel") : one(cls(h, "lm-scrim")));
      assert.deepEqual([h.state("actionsOpen"), h.state("actionsClosing")], [true, true], which);
      t.mock.timers.tick(279);
      assert.equal(h.state("actionsOpen"), true);
      t.mock.timers.tick(1);
      h.render();
      assert.deepEqual([h.state("actionsOpen"), h.state("actionsClosing")], [false, false], which);
      assert.equal(cls(h, "lm-sheet").length, 0);
      assert.deepEqual(h.calls("moveCard").concat(h.calls("dupCard"), h.calls("delCard")), []);
    }
  });
});

// Kept as source pins, all four: the delete gate's wording, its position before the delete,
// and the absence of any second, confirm-less delete path -- what a render cannot show.
describe("Kebab actions sheet: Delete keeps the REAL window.confirm gate -- not silently dropped for mobile", () => {
  test("the confirm message is byte-for-byte the same text LoomV2's own real desktop ✕ button uses", () => {
    // LoomV2's own real delete button (verified against the exact source above this
    // component in the same file): window.confirm(`Delete shot ${e.code}${e.c.title ? ` —
    // "${e.c.title}"` : ""}? This can't be undone.`). This assertion pulls BOTH occurrences
    // out of the live source and checks they are identical, rather than hand-copying the
    // string a second time into the test (which could silently drift from either real site).
    const msgRe = /Delete shot \$\{[^}]+\.code\}\$\{[^}]+\.c\.title \? ` — "\$\{[^}]+\.c\.title\}"` : ""\}\? This can't be undone\./g;
    const hits = src.match(msgRe) || [];
    assert.equal(hits.length, 2, "expected the exact same delete-confirm message text at BOTH LoomV2's real button and the mobile kebab sheet's Delete row");
  });

  test("Delete is gated behind window.confirm before delCard ever runs -- an early return, not a fire-then-ask", () => {
    assert.match(loomMobileSrc,
      /if \(!window\.confirm\(`Delete shot \$\{actionsLive\.code\}\$\{actionsLive\.c\.title \? ` — "\$\{actionsLive\.c\.title\}"` : ""\}\? This can't be undone\.`\)\) return;/);
  });

  test("cancelling the confirm (the early return) never reaches delCard -- delCard is called only AFTER the confirm line, not before it", () => {
    const delBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('className="lm-actionrow danger"'), loomMobileSrc.indexOf("Delete</button>") + 20);
    const confirmIdx = delBlock.indexOf("window.confirm(");
    const delCallIdx = delBlock.indexOf("delCard(actionsLive.a.id, actionsLive.c);");
    assert.ok(confirmIdx > -1 && delCallIdx > -1 && delCallIdx > confirmIdx,
      "expected window.confirm to be checked BEFORE delCard is ever called");
  });

  test("LoomMobile does not define a second, parallel confirm-less delete path for this row", () => {
    const delBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('className="lm-actionrow danger"'), loomMobileSrc.indexOf("Delete</button>") + 20);
    const delCardHits = delBlock.match(/delCard\(/g) || [];
    assert.equal(delCardHits.length, 1, "expected exactly one delCard( call in the Delete row, guarded by the confirm above it");
  });
});

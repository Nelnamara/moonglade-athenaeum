import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { loadModule, renderElement, query, one, LOOM_MOCKS } from "../test-support/render.mjs";
import { newCardShape, flat, shotPayload as buildShotPayload, priceFingerprint } from "../src/loom-core.js";
import { patchCardByIdWith } from "../src/loom-mutations.js";
import { attachTake, splicePatch, tookOf, cutPointOf } from "../src/loom-takes-core.js";

/* THE RENDER LIFECYCLE, AS WIRED (Session P, Stage A1 -- BUILD-w5-p §1.2, §3.3-§3.5 and review
   F1, F3-F8, F12-F17). The pure reducers are unit-tested in loom-takes-core.test.js,
   loom-submit-lifecycle.test.js and loom-board-merge.test.js; this file proves that the app
   actually CALLS them, in the order the design requires, and that no path the owner did not
   click can reach a render.

   TWO KINDS OF TEST LIVE HERE.

   1. BEHAVIOUR (most of the file, since 2026-10-08). The Loom's own hooks run -- useProjectStore,
      useGenerationPipeline, useShotMutations, useTakeActions, App itself, and the shared
      <VideoDrawer> -- out of master-storyboard.jsx exactly as it ships, against a recorded
      browser: the storyboard KV (compare-and-swap included), fetch (routed per test, every
      request logged), window.confirm, Toast and Jobs. Timers are node:test's mock timers, so a
      poll or an autosave moves only when a test ticks it. Every guard is asserted as what it
      DOES: the order of the price, the lock's save and the POST in the log; what was sent; what
      the card says. A guard that breaks fails here whatever its source happens to look like.

      How the hooks run without a DOM: the render helper (loom/test-support/render.mjs) bundles
      master-storyboard.jsx with one line appended that exports the hooks it already declares
      and the VideoDrawer/CostBadge it already imports -- nothing in the app changes for the test
      -- and mountHook() below serves React's hooks from a small dispatcher: useState, useRef,
      useMemo, useCallback, the effects (run after each render, cleanups on re-run and unmount)
      and useImperativeHandle, the way React runs them for one component. A static render can
      run no effects and no clicks; this can, and that is what a lifecycle needs.

   2. LINT (kept as source-text checks, on code with its comments stripped -- the comments here
      legitimately NAME the things they explain). Each says something about EVERY path rather
      than one: the reachability walker (no resume, landing or load path can reach a render),
      the one literal of the spend route, the single writer of takes and of boards, the banned
      selected-shot reads in the event handlers, and the drawer's host hooks that only store.
      A few behaviour pins also stay as text, each saying why where it stands: the Go gate (an
      effect inside LoomV2 that writes into the drawer's handle), the two splice buttons
      (handlers inside the LoomV2 and LoomMobile components), and two second layers that no
      test can see while the layer in front of them holds (the resume's in-flight filter behind
      checkSubmit's own refusal; the boot's failed-legacy check behind its parse check).

   Each behaviour test here was checked against the code it guards: with the guarded line
   broken (in the bundled text only), the test fails. */

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(here, "..", p), "utf8").replace(/\r\n/g, "\n");
const SRC = read("master-storyboard.jsx");
const DRAWER = read("../gallery/src/components/VideoDrawer.jsx");

// Comments out: block comments, whole comment lines, and trailing " // ..." after code (the
// leading whitespace keeps "https://" and a regex's "//" intact).
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/\s.*$/gm, "");
const CODE = codeOnly(SRC);
const DCODE = codeOnly(DRAWER);

/** A hook-level `const NAME = ...` (2-space indent) through its own closing line. */
function hookFn(code, name) {
  const at = code.search(new RegExp("\\n  const " + name + " = "));
  assert.ok(at >= 0, "expected `const " + name + " = ` at hook level -- renamed? re-point this test, never drop it");
  const ends = ["\n  };", "\n  }, ["].map((e) => code.indexOf(e, at + 1)).filter((i) => i > at);
  assert.ok(ends.length, "could not find the end of " + name);
  return code.slice(at, Math.min(...ends));
}

/* ---- a small reachability walker over this file's hook-level functions ----
   Every `  const NAME = ` block is a node, bounded to its own statement (a one-line const ends
   with its line; a function ends at its own 2-space closing line). A node's edges are the other
   block names its CODE mentions, with string contents removed (a "done" phase string is not a
   call). A sink is a render entry point (by name) or a spend route (by literal, looked for in
   the unstripped text). Name collisions across components MERGE blocks, which can only make a
   path easier to find -- the walker errs toward failing. */
const SINK_NAMES = ["generateShot", "batchGenerate", "genSubmit", "genImage", "genImageRun", "genEdit",
  "genRef", "genFix", "runGen", "confirmSpend", "doGenerate", "submitTask", "sendImgRun"];
const SINK_ROUTES = ["/api/loom/generate", "/api/generate", "/api/edit", "/api/fix"];
const noStrings = (s) => s.replace(/`(?:[^`\\]|\\.)*`/g, "``").replace(/"(?:[^"\\\n]|\\.)*"/g, '""')
  .replace(/'(?:[^'\\\n]|\\.)*'/g, "''");
function bound(body) {
  const first = body.split("\n")[0];
  const flat = noStrings(first);
  const depth = [...flat].reduce((d, ch) => d + ("([{".includes(ch) ? 1 : ")]}".includes(ch) ? -1 : 0), 0);
  if (/;\s*$/.test(first) && depth === 0) return first;
  const ends = ["\n  };", "\n  }, [", "\n  );", "\n  }));"].map((e) => body.indexOf(e)).filter((i) => i >= 0);
  return ends.length ? body.slice(0, Math.min(...ends)) : body;
}
function blocksOf(code) {
  const parts = code.split(/^  const (\w+) = /m);
  const out = new Map();
  for (let i = 1; i < parts.length; i += 2) out.set(parts[i], (out.get(parts[i]) || "") + "\n" + bound(parts[i + 1]));
  return out;
}
function sinkIn(body) {
  const code = noStrings(body);
  for (const s of SINK_NAMES) if (new RegExp("\\b" + s + "\\b").test(code)) return s;
  for (const r of SINK_ROUTES) if (body.includes('"' + r + '"') || body.includes("'" + r + "'") || body.includes("`" + r)) return r;
  return null;
}
function reach(blocks, root) {
  assert.ok(blocks.has(root), "root missing -- renamed? " + root);
  const seen = new Map([[root, [root]]]);
  const queue = [root];
  while (queue.length) {
    const name = queue.shift();
    const body = blocks.get(name) || "";
    const hit = sinkIn(body);
    if (hit) return seen.get(name).concat([hit]).join(" -> ");
    for (const m of noStrings(body).matchAll(/\b[A-Za-z_$][\w$]*\b/g)) {
      const id = m[0];
      if (id !== name && blocks.has(id) && !seen.has(id)) { seen.set(id, seen.get(name).concat([id])); queue.push(id); }
    }
  }
  return null;
}
const BLOCKS = blocksOf(CODE);

/* =================================================================================================
   THE HARNESS: a recorded browser, the Loom's bundle, and a hook runtime.
   ================================================================================================= */

// Everything the paths under test do to the outside world, in order: storage reads and writes,
// fetches, confirms, toasts, Jobs calls. Each mount starts it afresh.
const EVENTS = [];
let backend = null;                         // this test's storyboard KV (makeStorage)
const browser = { confirm: () => true };    // this test's answer to window.confirm

// The bundle reads `window.storage` at import (`hasStore`), so the browser is installed first.
// Storage calls go to whichever backend the current test made.
globalThis.window = {
  storage: {
    get: (k) => backend.get(k),
    set: (k, v, shared, opts) => backend.set(k, v, shared, opts),
    list: (p) => backend.list(p),
    delete: (k) => backend.delete(k),
  },
  confirm: (text) => { EVENTS.push({ kind: "confirm", text }); return browser.confirm(text); },
  alert: (text) => { EVENTS.push({ kind: "alert", text }); },
  Toast: { show: (o) => { EVENTS.push({ ...o, kind: "toast", tone: o && o.kind }); } },
  Jobs: {
    register: (taskId, label) => { EVENTS.push({ kind: "register", taskId: String(taskId), label }); },
    track: (taskId, label, cb) => { EVENTS.push({ kind: "track", taskId: String(taskId), label, cb }); },
  },
  JobsCard: { refresh() {} },
  location: { reload: () => { EVENTS.push({ kind: "reload" }); } },
  addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
};
globalThis.location = { search: "", pathname: "/loom" };
globalThis.history = { replaceState() {} };

// master-storyboard.jsx exactly as it ships, plus one line exporting what it already declares.
const LOOM_SRC = "loom/master-storyboard.jsx";
const UNDER_TEST = "\nexport const __lifecycleUnderTest = { useProjectStore, useGenerationPipeline, useShotMutations,"
  + " useTakeActions, VideoDrawer, CostBadge };\n";
const LOOM_MOD = await loadModule(LOOM_SRC, { mocks: { ...LOOM_MOCKS, [LOOM_SRC]: SRC + UNDER_TEST } });
const LOOM = { ...LOOM_MOD.__lifecycleUnderTest, App: LOOM_MOD.default };
// The drawer portals its ref preview into document.body; nothing else here touches a document.
globalThis.document = { body: { nodeType: 1 }, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; } };

/* ---- the hook runtime ----
   React's hooks resolve their dispatcher at call time; mountHook serves them for ONE function
   (a hook, or a component called as one) the way React does for one component: state and refs
   kept by call order, a re-render whenever state changed, effects run after the render that
   scheduled them (a cleanup before each re-run and on unmount), useImperativeHandle as a layout
   effect. `commit(value)` runs between render and effects -- where React attaches refs. */
const INTERNALS = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
assert.ok(INTERNALS && INTERNALS.ReactCurrentDispatcher,
  "the hook runtime serves React 18's dispatcher (loom's devDependency) -- a React upgrade moved it");
const DISPATCHER = INTERNALS.ReactCurrentDispatcher;
const sameDeps = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => Object.is(x, b[i]));

function mountHook(useHook, { commit } = {}) {
  const slots = [];
  const effects = [];
  let at = 0, dirty = true, live = true, value;
  const slot = (make) => { const k = at++; if (!(k in slots)) slots[k] = make(); return slots[k]; };
  const effect = (fn, deps) => {
    const s = slot(() => ({ deps: null, cleanup: null, ran: false }));
    if (s.ran && sameDeps(s.deps, deps)) return;
    effects.push(() => { if (typeof s.cleanup === "function") s.cleanup(); s.cleanup = fn(); s.deps = deps; s.ran = true; });
  };
  const stateSlot = (init, reduce) => slot(() => {
    const st = { value: init() };
    st.set = (a) => {
      if (!live) return;
      const v = reduce(st.value, a);
      if (!Object.is(v, st.value)) { st.value = v; dirty = true; }
    };
    return st;
  });
  const dispatcher = {
    useState(init) {
      const s = stateSlot(() => (typeof init === "function" ? init() : init), (v, a) => (typeof a === "function" ? a(v) : a));
      return [s.value, s.set];
    },
    useReducer(reducer, arg, init) {
      const s = stateSlot(() => (init ? init(arg) : arg), reducer);
      return [s.value, s.set];
    },
    useRef(init) { return slot(() => ({ current: init })); },
    useMemo(fn, deps) {
      const s = slot(() => ({ deps: null, value: undefined, made: false }));
      if (!s.made || !sameDeps(s.deps, deps)) { s.value = fn(); s.deps = deps; s.made = true; }
      return s.value;
    },
    useCallback(fn, deps) { return dispatcher.useMemo(() => fn, deps); },
    useEffect: effect,
    useLayoutEffect: effect,
    useInsertionEffect: effect,
    useImperativeHandle(ref, create, deps) {
      effect(() => {
        const v = create();
        if (typeof ref === "function") { ref(v); return () => ref(null); }
        if (ref) { ref.current = v; return () => { ref.current = null; }; }
        return undefined;
      }, deps);
    },
    useContext(ctx) { return ctx._currentValue; },
    useSyncExternalStore(subscribe, getSnapshot) { return getSnapshot(); },
    useDebugValue() {},
  };
  const renderOnce = () => {
    const prev = DISPATCHER.current;
    DISPATCHER.current = dispatcher;
    at = 0;
    try { value = useHook(); } finally { DISPATCHER.current = prev; }
    if (commit) commit(value);
    effects.splice(0).forEach((run) => run());
  };
  const flush = () => {
    for (let n = 0; dirty && live; n++) {
      if (n > 100) throw new Error("hook harness: the state never settles");
      dirty = false;
      renderOnce();
    }
  };
  flush();
  return {
    /** The latest render's return value (re-rendering first if any state changed). */
    get current() { flush(); return value; },
    flush,
    /** Render again with whatever the hook reads from outside (a prop changed). */
    rerender() { dirty = true; flush(); },
    unmount() {
      live = false;
      slots.forEach((s) => { if (s && typeof s.cleanup === "function") { try { s.cleanup(); } catch { /* best effort */ } } });
    },
  };
}

/** Let every promise chain that is ready run, re-rendering as state changes. */
async function settle(h) {
  for (let i = 0; i < 12; i++) {
    await new Promise((r) => setImmediate(r));
    h.flush();
  }
}

/** A request held open until the test answers it (or drops it: a network failure). */
function hold() {
  let answer, drop;
  const promise = new Promise((res, rej) => { answer = res; drop = rej; });
  promise.catch(() => {});
  return { route: () => promise, answer: (a) => answer(a), drop: () => drop(new TypeError("Failed to fetch")) };
}

/* ---- the recorded network ---- */
const PAID = { body: { cost: 900, free: false } };
const FREE = { body: { cost: 900, free: true } };
const ASK_PAID = "No free card covers this shot — it will spend ~900 credits.\n\nGenerate anyway?";
const ASK_UNVERIFIED = "Couldn't verify this shot's cost or free-card coverage — it may spend credits.\n\nGenerate anyway?";
const DEFAULT_ROUTES = {
  "/api/price": () => PAID,
  "/api/loom/generate": () => ({ body: { task_id: "T1" } }),
  "/api/loom/submit-status": () => ({ body: { state: "unknown" } }),
  "/api/task-status": () => ({ body: { phase: "running" } }),
  "/api/account/prefs": () => ({ body: { csrf: "tok-1", prefs: {} } }),
};
/** Install fetch for one test. A route answers {status?, body?, unreadable?}, throws (no
 *  answer), or returns a held promise. Every call is logged in EVENTS. */
function installNet(routes) {
  globalThis.fetch = async (url, init = {}) => {
    const u = String(url);
    let body = null;
    try { body = typeof init.body === "string" ? JSON.parse(init.body) : (init.body || null); } catch { body = init.body; }
    const call = { kind: "fetch", url: u, path: u.split("?")[0], method: String(init.method || "GET").toUpperCase(), body };
    EVENTS.push(call);
    const route = routes[call.path] || DEFAULT_ROUTES[call.path] || (() => ({ body: {} }));
    const a = (await route(call)) || {};
    const status = a.status || 200;
    return {
      status, ok: status < 400, statusText: "", headers: { get: () => null },
      json: async () => { if (a.unreadable) throw new SyntaxError("Unexpected token <"); return a.body === undefined ? {} : a.body; },
    };
  };
}

/* ---- the storyboard KV (the server's /api/loom/get|set|list shim, compare-and-swap included) ---- */
const PPRE = "storyboard:v2:proj:";
const ACTIVE_KEY = "storyboard:v2:active";
const PKEY = "storyboard:v2:project";
function makeStorage({ boards = {}, active, legacy, failList = false, unreadable = [], failGet = [] } = {}) {
  const kv = new Map();
  for (const [id, b] of Object.entries(boards)) kv.set(PPRE + id, { value: typeof b === "string" ? b : JSON.stringify(b), rev: "r0" });
  if (active) kv.set(ACTIVE_KEY, { value: active, rev: "r0" });
  if (legacy !== undefined) kv.set(PKEY, { value: legacy, rev: "r0" });
  let n = 0;
  return {
    kv, failSet: false,
    async get(k) {
      EVENTS.push({ kind: "get", key: k });
      if (unreadable.includes(k)) throw Object.assign(new Error("will not parse"), { unreadable: true });
      if (failGet.includes(k)) throw new Error("read failed");
      const e = kv.get(k);
      return e ? { value: e.value, rev: e.rev } : { value: null, rev: "missing" };
    },
    // A write is logged when it is asked ("set") and again when the server has it ("saved") --
    // a turn of the event loop later, so "saved before X" means X waited for the answer.
    async set(k, value, _shared, opts) {
      EVENTS.push({ kind: "set", key: k, value, opts });
      await new Promise((r) => setImmediate(r));
      if (this.failSet) throw new Error("write failed");
      const cur = kv.get(k), curRev = cur ? cur.rev : "missing";
      if (opts && opts.base_rev !== undefined && opts.base_rev !== curRev) return { conflict: true, value: cur ? cur.value : null, rev: curRev };
      const rev = "r" + (++n);
      kv.set(k, { value, rev });
      EVENTS.push({ kind: "saved", key: k, rev });
      return { ok: true, rev };
    },
    async list(prefix) {
      EVENTS.push({ kind: "list", prefix });
      if (failList) throw new Error("list failed");
      return { keys: [...kv.keys()].filter((k) => k.startsWith(prefix)) };
    },
    async delete(k) { kv.delete(k); },
    /** Another tab saves this board: its revision moves on. */
    otherTab(id, board) { const rev = "r-other-" + (++n); kv.set(PPRE + id, { value: JSON.stringify(board), rev }); return rev; },
    board(id) { const e = kv.get(PPRE + id); return e ? JSON.parse(e.value) : null; },
  };
}

/* ---- boards ---- */
const ASSET = { id: "a1", name: "Her", kind: "image", tag: "@image1", thumbId: "", source: "", mediaId: "123456", lock: true };
// An imported picture: its id is local to this machine, so the render route cannot send it.
const LOCAL_ASSET = { id: "a2", name: "Imported", kind: "image", tag: "@image2", thumbId: "", source: "", mediaId: "local_0123456789ab", lock: false };
const shot = (id, extra = {}) => newCardShape(id, { title: id.toUpperCase(), prompt: "she walks in", cast: ["a1"], duration: 5, ...extra });
const boardOf = (cards, extra = {}) => ({ name: "Board", target: 60, look: "", draft: false, assets: [ASSET, LOCAL_ASSET],
  acts: [{ id: "act1", name: "Act 1", collapsed: false, cards }], ...extra });
// A send from an earlier page whose answer never came: the card keeps its lock, unclear.
const UNCLEAR = { status: "wip", pendingSubmitId: "s-prev", pendingBoard: "b1", lastAttempt: { state: "unclear", msg: "", at: "" } };
// A render the server accepted: the card waits for its task.
const rendering = (taskId) => ({ status: "wip", pendingSubmitId: "s-" + taskId, pendingTaskId: taskId, pendingBoard: "b1", genStartedAt: Date.now() });
// A rendered shot: one ★ take.
const rendered = (id, mid, extra = {}) => ({ ...attachTake(shot(id, extra), { mid, dur: 6, at: "" }).card });
const PENDING_KEYS = ["pendingTaskId", "pendingSubmitId", "pendingSettings", "pendingAnchor", "pendingBoard", "pendingQuote", "genStartedAt"];
const STILL_SENDING = "Still being sent to PixAI — it can't be released until PixAI answers. Check again in a moment.";

const prepared = new WeakSet();
/** A fresh browser for this mount: an empty log, this storage, these routes, this confirm. The
 *  first mount of a test also mocks its timers and quiets console.error (storeFailed() logs
 *  every storage failure a test provokes on purpose; the lines land in EVENTS instead). */
function freshWorld(t, { routes = {}, confirm, storage = {} } = {}) {
  if (!prepared.has(t)) {
    prepared.add(t);
    t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
    const error = console.error;
    console.error = (...a) => { EVENTS.push({ kind: "console", text: a.map(String).join(" ") }); };
    t.after(() => { console.error = error; });
  }
  EVENTS.length = 0;
  backend = makeStorage(storage);
  browser.confirm = confirm || (() => true);
  installNet(routes);
}

/** Query helpers over EVENTS and a mounted Loom. */
const fetches = (p) => EVENTS.filter((x) => x.kind === "fetch" && x.path === p);
const boardSets = (id) => EVENTS.filter((x) => x.kind === "set" && x.key === PPRE + id);
const allSets = () => EVENTS.filter((x) => x.kind === "set");
const toasts = (title) => EVENTS.filter((x) => x.kind === "toast" && (!title || x.title === title));
const asked = () => EVENTS.filter((x) => x.kind === "confirm").map((x) => x.text);
const indexOf = (pred) => EVENTS.findIndex(pred);

/** Mount the Loom's store + render pipeline + shot edits + take actions, wired as App wires
 *  them, on a board read from the KV; the boot (loadBoards) and the resume have run. */
async function mountLoom(t, { boards = { b1: boardOf([shot("c1")]) }, active = "b1", storage = {}, routes, confirm } = {}) {
  freshWorld(t, { routes, confirm, storage: { boards, active, ...storage } });
  const props = { mobileUI: false, picks: [] };
  const h = mountHook(() => {
    const store = LOOM.useProjectStore(() => {});
    const gen = LOOM.useGenerationPipeline({ project: store.project, projectRef: store.projectRef, activeIdRef: store.activeIdRef,
      setProject: store.setProject, saveBoardNow: store.saveBoardNow, noteResolved: store.noteResolved,
      draftCardRef: { current: { id: "__draft__", mode: "I2V", duration: 5, cast: [], refs: [], openFrame: {}, closeFrame: {} } },
      setDraftCard() {}, thumbs: store.thumbs, setCard() {}, setCardStatus() {}, setAssets() {},
      openPick: (cb, kind) => props.picks.push({ cb, kind }), activeId: store.activeId, mobileUI: props.mobileUI });
    const muts = LOOM.useShotMutations(store.project, store.setProject);
    const takes = LOOM.useTakeActions({ projectRef: store.projectRef, activeIdRef: store.activeIdRef,
      setProject: store.setProject, activeId: store.activeId });
    return { store, gen, muts, takes };
  });
  t.after(() => h.unmount());
  await settle(h);
  const loom = {
    get store() { return h.current.store; },
    get gen() { return h.current.gen; },
    get muts() { return h.current.muts; },
    get takes() { return h.current.takes; },
    entry: (id) => flat(h.current.store.projectRef.current).find((e) => e.c.id === id),
    card: (id) => { const e = flat(h.current.store.projectRef.current).find((x) => x.c.id === id); return e ? e.c : undefined; },
    settle: () => settle(h),
    async tick(ms) { await settle(h); t.mock.timers.tick(ms); await settle(h); },
    /** The Mobile toggle (App hands mobileUI to the pipeline): a re-render with the new prop,
     *  which re-runs the resume effect. */
    async toggleMobile() { props.mobileUI = !props.mobileUI; h.rerender(); await settle(h); },
    picks: props.picks,
  };
  return loom;
}

describe("the walker is real (negative controls)", () => {
  test("on the real file it finds the paths that DO spend", () => {
    assert.equal(reach(BLOCKS, "genSubmit"), "genSubmit -> generateShot", "the phone's Generate reaches the render (as it must)");
    assert.match(reach(BLOCKS, "batchGenerate"), /^batchGenerate -> generateShot$/);
  });
  test("a root that reaches generateShot through a helper is caught", () => {
    const fake = blocksOf("\n  const onOpen = () => { helper(); };\n  const helper = () => { generateShot(entry); };\n");
    assert.equal(reach(fake, "onOpen"), "onOpen -> helper -> generateShot");
    const fake2 = blocksOf("\n  const onOpen = () => { poke(); };\n  const poke = () => fetch(\"/api/loom/generate\", {});\n");
    assert.match(reach(fake2, "onOpen"), /\/api\/loom\/generate$/);
  });
});

describe("generateShot follows BUILD-w5-p §3.3 in order", () => {
  const fn = hookFn(CODE, "generateShot");
  test("step 1: the synchronous latch (inflightRef + the card read from the store's ref) comes before the first await", async (t) => {
    const price = hold();
    const loom = await mountLoom(t, { routes: { "/api/price": price.route }, confirm: () => false });
    const e = loom.entry("c1");
    const first = loom.gen.generateShot(e);
    // Nothing is awaited before the latch: the click's price request is already out by the time
    // generateShot hands back its promise, so the latch (which comes before it) was set first.
    assert.equal(fetches("/api/price").length, 1, "latched and asking, with nothing awaited first");
    const second = loom.gen.generateShot(e);   // a double click
    await loom.settle();
    assert.equal(fetches("/api/price").length, 1, "the second click never reached the price");
    assert.deepEqual(await second, { ok: false, reason: "in-flight" }, "a double click gets nothing through");
    price.answer(PAID);
    assert.deepEqual(await first, { ok: false, reason: "cancelled" });
    // The latch reads the board's CURRENT card (cardOn -> projectRef), never the click's entry:
    // a stale entry of a shot whose render is out now is refused before anything is asked.
    const stale = loom.entry("c1");
    loom.store.setProject((p) => patchCardByIdWith(p, "c1", (c) => ({ ...c, status: "wip", pendingSubmitId: "s-other", pendingBoard: "b1" })));
    assert.deepEqual(await loom.gen.generateShot(stale), { ok: false, reason: "in-flight" });
    assert.equal(fetches("/api/price").length, 1);
    assert.equal(fetches("/api/loom/generate").length, 0);
  });
  test("step 2: ONE payload, built from the board as it is at the click, is priced, sent and snapshotted", async (t) => {
    const loom = await mountLoom(t);
    const stale = loom.entry("c1");
    // An edit the click's closure has not caught up with: the board says "she runs out" (Private) now.
    loom.store.setProject((p) => patchCardByIdWith(p, "c1", (c) => ({ ...c, prompt: "she runs out", isPrivate: true })));
    assert.deepEqual(await loom.gen.generateShot(stale), { ok: true, taskId: "T1" });
    const [priced] = fetches("/api/price");
    const [sent] = fetches("/api/loom/generate");
    assert.match(priced.body.prompt, /she runs out/, "priced from the board, not from the click's entry");
    const { hasInput, ...pricedPayload } = priced.body;
    const { origin, loom_target, submit_id, expect_free, ...sentPayload } = sent.body;
    assert.equal(hasInput, true);
    assert.deepEqual(sentPayload, pricedPayload, "what was priced is what was sent, every key");
    assert.equal(sentPayload.is_private, true, "the Private channel rides the payload (spend review S3)");
    assert.deepEqual(asked(), [ASK_PAID], "the confirm describes that same payload's price");
    const settings = loom.card("c1").pendingSettings;
    assert.equal(settings.sentPrompt, sent.body.prompt, "the take's settings snapshot is the prompt that was sent");
    assert.equal(settings.prompt, "she runs out");
  });
  test("step 2: an imported (local_) picture is refused BEFORE a price is asked or a confirm shown (open call 4, S6)", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", { cast: ["a1", "a2"] })]) } });
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: false, reason: "imported-picture" });
    assert.equal(fetches("/api/price").length, 0);
    assert.deepEqual(asked(), []);
    assert.equal(boardSets("b1").length, 0, "nothing locked");
    assert.equal(fetches("/api/loom/generate").length, 0);
    assert.deepEqual(loom.gen.genState.c1, { phase: "error", held: true,
      msg: "Imported picture — it can't be sent to PixAI yet. Nothing was sent." });
  });
  test("step 2: a batch shot whose payload changed since the confirm is not sent (F12)", async (t) => {
    const loom = await mountLoom(t);
    const e = loom.entry("c1");
    const confirmedFp = priceFingerprint(buildShotPayload(e, loom.store.projectRef.current, () => null));
    assert.deepEqual(await loom.gen.generateShot(e, { skipConfirm: true, confirmedFp: JSON.stringify(["something", "else"]) }),
      { ok: false, reason: "changed" });
    assert.equal(fetches("/api/loom/generate").length, 0);
    assert.equal(boardSets("b1").length, 0, "nothing locked");
    assert.deepEqual(await loom.gen.generateShot(e, { skipConfirm: true, confirmedFp }), { ok: true, taskId: "T1" },
      "the payload the batch confirmed is sent");
  });
  test("step 3: beginRender, then the lock is SAVED (through the queue) before the POST", async (t) => {
    const loom = await mountLoom(t);
    await loom.gen.generateShot(loom.entry("c1"));
    const priced = indexOf((x) => x.kind === "fetch" && x.path === "/api/price");
    const lockSave = indexOf((x) => x.kind === "set" && x.key === PPRE + "b1");
    const lockSaved = indexOf((x) => x.kind === "saved" && x.key === PPRE + "b1");
    const post = indexOf((x) => x.kind === "fetch" && x.path === "/api/loom/generate");
    assert.ok(priced >= 0 && lockSave > priced && lockSaved > lockSave && post > lockSaved,
      "price -> the lock written AND answered -> only then the POST");
    const saved = flat(JSON.parse(EVENTS[lockSave].value)).find((x) => x.c.id === "c1").c;
    assert.equal(saved.pendingSubmitId, EVENTS[post].body.submit_id, "what was saved is THIS render's lock");
    assert.equal(saved.status, "wip");
    assert.deepEqual(EVENTS[lockSave].opts, { base_rev: "r0" }, "a compare-and-swap save, on the revision the board was read at");
  });
  test("step 3: a failed save sends nothing and takes the lock back off (F5)", async (t) => {
    const loom = await mountLoom(t);
    backend.failSet = true;
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: false, reason: "save-failed" });
    assert.equal(fetches("/api/loom/generate").length, 0);
    const c = loom.card("c1");
    assert.equal(c.pendingSubmitId, null, "the lock came back off");
    assert.equal(c.status, "todo");
    assert.deepEqual(loom.gen.genState.c1, { phase: "error", held: true, msg: "Couldn't save the storyboard, so nothing was sent." });
  });
  test("step 3: a save conflict (another tab saved first) merges, sends nothing and leaves no lock", async (t) => {
    const loom = await mountLoom(t);
    backend.otherTab("b1", boardOf([shot("c1", { title: "RENAMED ELSEWHERE" })]));
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: false, reason: "conflict" });
    assert.equal(fetches("/api/loom/generate").length, 0);
    const c = loom.card("c1");
    assert.equal(c.title, "RENAMED ELSEWHERE", "the merged board -- the other tab's -- is the one open");
    assert.ok(!c.pendingSubmitId, "this click's lock came off the merged board");
    assert.ok(!flat(backend.board("b1")).find((x) => x.c.id === "c1").c.pendingSubmitId, "and off the saved one");
    assert.match(loom.gen.genState.c1.msg, /^This storyboard changed in another tab/);
  });
  test("step 4: ONE POST carrying loom_target and submit_id; a paid quote is not sent expect_free", async (t) => {
    const loom = await mountLoom(t);
    await loom.gen.generateShot(loom.entry("c1"));
    const posts = fetches("/api/loom/generate");
    assert.equal(posts.length, 1);
    assert.equal(posts[0].method, "POST");
    assert.deepEqual(posts[0].body.loom_target, { board_id: "b1", card_id: "c1" });
    assert.equal(posts[0].body.submit_id, loom.card("c1").pendingSubmitId);
    assert.equal("expect_free" in posts[0].body, false);
    // Accepted: the task is adopted onto the card and polled.
    assert.equal(loom.card("c1").pendingTaskId, "T1");
    await loom.tick(2500);
    assert.deepEqual(fetches("/api/task-status").map((f) => f.url), ["/api/task-status?task_id=T1"]);
  });
  test("step 4: a quote that was free asks nothing and is sent expect_free (F13)", async (t) => {
    const loom = await mountLoom(t, { routes: { "/api/price": () => FREE } });
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: true, taskId: "T1" });
    assert.deepEqual(asked(), [], "a card covers it: no confirm");
    assert.equal(fetches("/api/loom/generate")[0].body.expect_free, true);
  });
  test("step 4: a refused POST is never re-posted", async (t) => {
    const loom = await mountLoom(t, { routes: { "/api/loom/generate": () => ({ status: 400, body: { error: "prompt refused" } }) } });
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: false, reason: "refused" });
    await loom.tick(30000);
    assert.equal(fetches("/api/loom/generate").length, 1);
    const c = loom.card("c1");
    assert.equal(c.pendingSubmitId, null);
    assert.equal(c.lastAttempt.state, "refused");
  });
  test("step 5: after the answer is classified, an unclear send reads submit-status -- /api/loom/generate is never asked again", async (t) => {
    const journal = hold();
    const loom = await mountLoom(t, { routes: { "/api/loom/generate": () => { throw new TypeError("Failed to fetch"); },
      "/api/loom/submit-status": journal.route } });
    const run = loom.gen.generateShot(loom.entry("c1"));
    await loom.settle();
    // While the journal is being read, the card already holds its lock and says it is checking.
    assert.deepEqual(loom.card("c1").lastAttempt && [loom.card("c1").lastAttempt.state, loom.card("c1").lastAttempt.msg],
      ["unclear", "Checking whether the render was sent…"]);
    journal.answer({ body: { state: "unknown" } });
    assert.deepEqual(await run, { ok: false, reason: "unclear" });
    const sid = fetches("/api/loom/generate")[0].body.submit_id;
    assert.deepEqual(fetches("/api/loom/submit-status").map((f) => f.url),
      ["/api/loom/submit-status?submit_id=" + encodeURIComponent(sid)], "ONE read of the journal");
    const c = loom.card("c1");
    assert.equal(c.pendingSubmitId, sid, "the lock stays");
    assert.equal(c.lastAttempt.state, "unclear");
    assert.deepEqual(loom.gen.genState.c1, { phase: "unclear", held: true, msg: "unconfirmed" });
    // Not on a later resume, not after any poll timer: the render is never sent again.
    await loom.toggleMobile();
    await loom.tick(60000);
    assert.equal(fetches("/api/loom/generate").length, 1);
    assert.equal(reach(BLOCKS, "checkSubmit"), null, "the check can never reach a render");
  });
  test("step 5: the journal says it WAS sent -- the card adopts that task and polls it", async (t) => {
    const loom = await mountLoom(t, { routes: {
      "/api/loom/generate": () => { throw new TypeError("Failed to fetch"); },
      "/api/loom/submit-status": () => ({ body: { state: "submitted", task_id: "T9" } }),
    } });
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: true, taskId: "T9" });
    assert.equal(loom.card("c1").pendingTaskId, "T9");
    await loom.tick(2500);
    assert.deepEqual(fetches("/api/task-status").map((f) => f.url), ["/api/task-status?task_id=T9"]);
    assert.equal(fetches("/api/loom/generate").length, 1);
  });
  test("the latch lets go when the POST answers (the card's markers hold the lock after that)", async (t) => {
    const post = hold();
    const loom = await mountLoom(t, { routes: { "/api/loom/generate": post.route } });
    const run = loom.gen.generateShot(loom.entry("c1"));
    await loom.settle();
    assert.equal(fetches("/api/loom/generate").length, 1, "the POST is out");
    post.drop();
    assert.deepEqual(await run, { ok: false, reason: "unclear" });
    // checkSubmit refuses a card whose POST this tab is still waiting on (spend review B1), so the
    // journal read of the unclear answer proves the latch let go the moment the POST answered.
    assert.equal(fetches("/api/loom/submit-status").length, 1);
  });
  test("the only fetch of /api/loom/generate in the Loom is generateShot's", () => {
    assert.equal((CODE.match(/["'`]\/api\/loom\/generate["'`]/g) || []).length, 1);
    const at = CODE.indexOf('fetch("/api/loom/generate"');
    const g = CODE.indexOf("\n  const generateShot = async (entry, opts = {}) => {");
    assert.ok(g >= 0 && at > g && at < g + fn.length);
  });
});

describe("the unclear-send way-out, the resume and every landing cannot reach a render", () => {
  const ROOTS = ["checkSubmit", "recheckSubmit", "releaseSubmit", "adoptFromJournal", "resumeInterrupted",
    "pollShot", "useExistingVideo", "attachDraftVideo", "beginDrawerRender", "onVideoSubmit", "onVideoResult",
    "onVideoError", "onVideoSlow", "onVideoPaused", "loadBoards", "openProject", "newProject",
    "duplicateProject", "_adoptBackup", "persistBoard", "saveBoardNow", "splitShot"];
  for (const root of ROOTS) {
    test(root + " reaches no render entry point and no spend route", () => {
      assert.equal(reach(BLOCKS, root), null);
    });
  }
  test("the release is a POST to /api/loom/submit-abandon with the CSRF token, never a re-send", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", UNCLEAR)]) },
      routes: { "/api/loom/submit-abandon": () => ({ body: { ok: true } }) } });
    await loom.gen.releaseSubmit("c1");
    const [rel] = fetches("/api/loom/submit-abandon");
    assert.equal(rel.method, "POST");
    assert.deepEqual(rel.body, { csrf: "tok-1", submit_id: "s-prev" }, "the session's token, and the render it releases");
    const c = loom.card("c1");
    assert.equal(c.pendingSubmitId, null);
    assert.equal(c.lastAttempt.state, "abandoned");
    assert.match(loom.gen.genState.c1.msg, /^Released\. If that render was sent after all, its clip is in your library\./);
    assert.equal(fetches("/api/loom/generate").length, 0, "a release never re-sends");
  });
  test("a render the journal knows WAS sent is adopted, not released", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", UNCLEAR)]) },
      routes: { "/api/loom/submit-abandon": () => ({ status: 409, body: { error: "it was sent", task_id: "T7" } }) } });
    await loom.gen.releaseSubmit("c1");
    const c = loom.card("c1");
    assert.equal(c.pendingTaskId, "T7", "the card waits for the task the journal names");
    assert.equal(c.pendingSubmitId, "s-prev");
    assert.notEqual(c.lastAttempt && c.lastAttempt.state, "abandoned");
    await loom.tick(2500);
    assert.deepEqual(fetches("/api/task-status").map((f) => f.url), ["/api/task-status?task_id=T7"], "and it is polled");
    assert.equal(fetches("/api/loom/generate").length, 0);
  });
  test("resumeInterrupted polls the task case and CHECKS the unclear case; the effect runs it on load and on the Mobile toggle", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", rendering("T1")), shot("c2", UNCLEAR), shot("c3")]) } });
    assert.deepEqual(fetches("/api/loom/submit-status").map((f) => f.url), ["/api/loom/submit-status?submit_id=s-prev"],
      "the unclear send is checked by ONE journal read");
    await loom.tick(2500);
    assert.deepEqual(fetches("/api/task-status").map((f) => f.url), ["/api/task-status?task_id=T1"], "the accepted one is polled");
    await loom.toggleMobile();
    assert.equal(fetches("/api/loom/submit-status").length, 2, "the toggle re-ran the resume: the unclear send is checked again");
    await loom.tick(4000);
    assert.equal(fetches("/api/task-status").length, 2, "...but T1 is not polled twice (one loop: 2.5 s, then every 4 s)");
    assert.equal(fetches("/api/loom/generate").length, 0, "nothing the owner did not click was rendered");
  });
  test("the resume hands pollShot the persisted start: a render older than the ceiling is paused, not given a fresh budget", async (t) => {
    const old = shot("c1", { ...rendering("T1"), genStartedAt: Date.now() - 7 * 3600 * 1000 });
    const loom = await mountLoom(t, { boards: { b1: boardOf([old]) } });
    await loom.tick(2500);
    assert.equal(loom.gen.genState.c1.phase, "paused");
  });
  test("a send this tab is still waiting on is SLOW, never unclear: no mark, no journal read, no release (spend review B1)", async (t) => {
    // A slow PixAI, then a board switch or the Mobile toggle: the resume used to mark the card
    // unclear from submit-status "sending" and offer the release, which freed the shot for a
    // second paid render while the first POST was still inside core.submit.
    const post = hold();
    const loom = await mountLoom(t, { routes: { "/api/loom/generate": post.route } });
    const run = loom.gen.generateShot(loom.entry("c1"));
    await loom.settle();
    assert.equal(fetches("/api/loom/generate").length, 1, "the POST is out");
    loom.gen.recheckSubmit("c1");               // ↻ Check
    await loom.toggleMobile();                  // the Mobile toggle re-runs the resume
    await loom.gen.releaseSubmit("c1");         // "release this shot"
    await loom.settle();
    assert.equal(fetches("/api/loom/submit-status").length, 0, "no journal read while this tab's own POST is out");
    assert.equal(fetches("/api/loom/submit-abandon").length, 0, "the release refuses before it asks the server");
    assert.equal(loom.card("c1").lastAttempt, undefined, "not marked unclear");
    assert.deepEqual(loom.gen.genState.c1, { phase: "checking", held: true, msg: STILL_SENDING });
    post.answer({ body: { task_id: "T1" } });
    assert.deepEqual(await run, { ok: true, taskId: "T1" });
    // The resume filters such a card out before it ever calls checkSubmit. That is a second layer
    // behind checkSubmit's own refusal (driven above) and changes nothing anyone can see while the
    // first holds, so this one layer stays a text pin.
    assert.match(hookFn(CODE, "resumeInterrupted"),
      /submitsToCheck\(proj, Object\.create\(null\)\)\s*\.filter\(\(c\) => !inflightRef\.current\.has\(c\.id\)\)/);
  });
  test("the server's own still-sending refusal keeps the lock and says so", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", UNCLEAR)]) },
      routes: { "/api/loom/submit-abandon": () => ({ status: 409, body: { error: "still sending", sending: true } }) } });
    await loom.gen.releaseSubmit("c1");
    const c = loom.card("c1");
    assert.equal(c.pendingSubmitId, "s-prev", "the lock stays");
    assert.equal(c.lastAttempt.state, "unclear");
    assert.deepEqual(loom.gen.genState.c1, { phase: "unclear", held: true, msg: STILL_SENDING },
      "the still-sending answer is told apart from a failed release");
  });
  test("pollShot registers its own task, so a later resume never starts a second poll of it (F4)", async (t) => {
    const loom = await mountLoom(t);
    loom.gen.pollShot("c1", "T5", Date.now(), "b1");
    loom.gen.pollShot("c1", "T5", Date.now(), "b1");    // a second start: one live poll per task
    // The card holds the task the way an accepted send leaves it; the resume that follows (the
    // Mobile toggle, before the first tick) must not start another loop.
    loom.store.setProject((p) => patchCardByIdWith(p, "c1", (c) => ({ ...c, ...rendering("T5") })));
    await loom.toggleMobile();
    await loom.tick(2500);
    assert.equal(fetches("/api/task-status").length, 1);
    await loom.tick(4000);
    assert.equal(fetches("/api/task-status").length, 2, "one loop");
  });
});

describe("landings go through landTake / attachTake only (F1, F4, F14)", () => {
  test("no withResult( call and no genTargetRef remain in the Loom", () => {
    assert.doesNotMatch(CODE, /\bwithResult\(/);
    assert.doesNotMatch(CODE, /\bgenTargetRef\b/);
    assert.doesNotMatch(CODE, /\bsetCardResult\b/);
  });
  test("pollShot lands through landTake, on the board the render was sent from", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", rendering("T1"))]) },
      routes: { "/api/task-status": () => ({ body: { phase: "done", media_ids: ["777"], duration: 5 } }) } });
    await loom.tick(2500);
    const c = loom.card("c1");
    assert.deepEqual(c.takes.map((x) => [x.n, x.mid, x.taskId]), [[1, "777", "T1"]], "a take, from this task");
    assert.equal(c.selectedTake, 1);
    assert.equal(c.resultMid, "777");
    assert.equal(c.status, "done");
    assert.equal(c.pendingTaskId, null);
    assert.equal(loom.gen.genState.c1.phase, "done");
  });
  test("pollShot: with another board open nothing is patched there; the render lands when its own board is back", async (t) => {
    // b2 holds a stale copy of the shot: the same card id, still marked as waiting for T1 from b1.
    const loom = await mountLoom(t, {
      boards: { b1: boardOf([shot("c1", rendering("T1"))]), b2: boardOf([shot("c1", rendering("T1"))], { name: "Copy" }) },
      routes: { "/api/task-status": () => ({ body: { phase: "done", media_ids: ["777"], duration: 5 } }) } });
    await loom.store.projectApi.openProject("b2");
    await loom.settle();
    assert.equal(loom.store.activeId, "b2");
    await loom.tick(2500);                       // T1 finishes while b2 is open
    assert.equal(fetches("/api/task-status").length, 1);
    const copy = loom.card("c1");
    assert.equal(copy.takes, undefined, "nothing landed on the copy");
    assert.equal(copy.pendingTaskId, "T1");
    assert.notEqual(loom.gen.genState.c1.phase, "done");
    assert.equal(boardSets("b1").length + boardSets("b2").length, 0, "and nothing was written");
    await loom.store.projectApi.openProject("b1");
    await loom.settle();
    await loom.tick(2500);                       // b1's own resume polls T1 again
    assert.equal(loom.card("c1").resultMid, "777", "it lands on the board it was sent from");
  });
  test("pollShot: a stale copy waiting on a task of another board is never landed on", async (t) => {
    // b2's copy still names T1 from b1 (pendingBoard "b1"). Polled FROM b2, the poll's own board
    // is what keeps landTake from taking it as this copy's render (F4, a phantom take on a copy).
    const loom = await mountLoom(t, { boards: { b2: boardOf([shot("c1", rendering("T1"))]) }, active: "b2",
      routes: { "/api/task-status": () => ({ body: { phase: "done", media_ids: ["777"], duration: 5 } }) } });
    await loom.tick(2500);
    const c = loom.card("c1");
    assert.equal(c.takes, undefined, "no phantom take on a copy");
    assert.equal(c.pendingTaskId, "T1");
    assert.equal(loom.gen.genState.c1.msg, "That render finished; its clip is in your library.");
  });
  test("pollShot: a failed retake keeps a ★ shot done (F14)", async (t) => {
    const retaking = { ...rendered("c1", "500"), ...rendering("T2") };
    const loom = await mountLoom(t, { boards: { b1: boardOf([retaking]) },
      routes: { "/api/task-status": () => ({ body: { phase: "failed", error: "moderation" } }) } });
    await loom.tick(2500);
    const c = loom.card("c1");
    assert.equal(c.status, "done", "still done: it has a ★ take");
    assert.equal(c.resultMid, "500");
    assert.equal(c.lastAttempt.state, "failed");
    assert.equal(c.pendingTaskId, null);
  });
  test("the drawer's result lands by task id through landTake; the draft attach and Use an existing video through attachTake", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", rendering("T3")), shot("c2"), shot("c3", UNCLEAR)]) } });
    // mg-result carries the drawer's target (c2) and the task (T3): it lands on the card waiting for T3.
    loom.gen.onVideoResult({ task_id: "T3", media_ids: ["777"], duration: 5, board_id: "b1", card_id: "c2", submit_id: "d1" });
    assert.deepEqual(loom.card("c1").takes.map((x) => [x.mid, x.taskId]), [["777", "T3"]]);
    assert.equal(loom.card("c1").resultMid, "777");
    assert.equal(loom.card("c2").takes, undefined, "the shot the drawer was bound to gets nothing");
    // "attach to A·02": a real render made on this board -- a billed take with the draft's settings.
    assert.equal(loom.gen.attachDraftVideo("c2", { mid: "888", dur: 4, settings: { prompt: "draft" } }), "landed");
    const drafted = loom.card("c2").takes[0];
    assert.equal(drafted.mid, "888");
    assert.equal(drafted.imported, false);
    assert.deepEqual(drafted.settings, { prompt: "draft" });
    // "Use an existing video instead": borrowed footage, an imported take, selected.
    loom.gen.useExistingVideo(loom.entry("c2"));
    loom.picks[0].cb("999", "/t.jpg", true, 6);
    const borrowed = loom.card("c2").takes.find((x) => x.mid === "999");
    assert.equal(borrowed.imported, true);
    assert.equal(loom.card("c2").resultMid, "999");
    // ...and refused on a shot whose send is unclear.
    loom.gen.useExistingVideo(loom.entry("c3"));
    loom.picks[1].cb("1000", "/t.jpg", true, 6);
    assert.equal(loom.card("c3").takes, undefined);
    assert.deepEqual(loom.gen.genState.c3, { phase: "unclear", held: true,
      msg: "This shot's last render isn't confirmed yet — check it (or release it) before attaching a video." });
    assert.equal(fetches("/api/loom/generate").length, 0);
  });
  test("nothing in the Loom writes takes / selectedTake / takeSeq except the pure reducers", () => {
    const WRITE = /(?<![\w.$])(takes|selectedTake|takeSeq)\s*:(?!:)|\.(takes|selectedTake|takeSeq)\s*=(?!=)|\[\s*["'](takes|selectedTake|takeSeq)["']\s*\]\s*=(?!=)/;
    for (const [name, code] of [["master-storyboard.jsx", CODE], ["VideoDrawer.jsx", DCODE],
      ["src/loom-core.js", codeOnly(read("src/loom-core.js"))], ["src/loom-store-core.js", codeOnly(read("src/loom-store-core.js"))],
      ["src/loom-run.js", codeOnly(read("src/loom-run.js"))], ["src/loom-url.js", codeOnly(read("src/loom-url.js"))]]) {
      assert.doesNotMatch(code, WRITE, name + " writes a take field itself");
    }
    // loom-mutations.js only ever CLEARS them, on a duplicate (a fresh, unrendered shot).
    const mut = codeOnly(read("src/loom-mutations.js"));
    const hits = mut.split("\n").filter((l) => WRITE.test(l));
    assert.deepEqual(hits.map((l) => l.trim()),
      ["takes: undefined, selectedTake: undefined, takeSeq: undefined, deletedTakes: undefined,"]);
  });
});

describe("the drawer's events are resolved by their ids, never by the selected shot (F7)", () => {
  const EVENT_HANDLERS = { "mg-submit": "onVideoSubmit", "mg-result": "onVideoResult", "mg-error": "onVideoError",
    "mg-slow": "onVideoSlow", "mg-paused": "onVideoPaused" };
  // What the drawer hands beforeSend for the card's Go (the target it captured at the click).
  const DRAWER_PAYLOAD = { mode: "I2V", prompt: "she walks in", negative: "", images: ["123456"], video_refs: [], audio_refs: [],
    duration: 5, audio: false, video_model: "v4.0.1", camera_movement: "unset", quality: "professional",
    audio_language: "english", is_private: false, prompt_helper: false };
  const go = (extra = {}) => ({ card_id: "c1", board_id: "b1", submit_id: "d1", payload: DRAWER_PAYLOAD, ...extra });
  const REFUSED_BOARD = { refused: "The storyboard changed before this render went out. Nothing was sent." };
  const REFUSED_BUSY = { refused: "This shot is already rendering. Nothing was sent." };

  test("each render event's listener only hands its detail on", () => {
    for (const [evt, fn] of Object.entries(EVENT_HANDLERS)) {
      const re = new RegExp('el\\.addEventListener\\("' + evt + '", \\(e\\) => ' + fn + "\\(e\\.detail\\)\\);");
      assert.match(CODE, re, evt + " must call " + fn + "(e.detail) and nothing else");
    }
  });
  test("no render-event handler reads the selected shot (activeRef / genTargetRef / selShot)", () => {
    for (const fn of Object.values(EVENT_HANDLERS)) {
      assert.doesNotMatch(hookFn(CODE, fn), /\b(activeRef|genTargetRef|selShot)\b/, fn);
    }
    assert.match(hookFn(CODE, "onVideoSubmit"), /const card = cardForSubmit\(projectRef\.current, d\.submit_id\);/);
    assert.match(hookFn(CODE, "onVideoError"), /const card = cardForSubmit\(projectRef\.current, d\.submit_id\);/);
    assert.match(hookFn(CODE, "onVideoError"), /checkSubmit\(card\.id, d\.submit_id, activeIdRef\.current\)/, "an unclear drawer send is CHECKED, never re-sent");
  });
  test("the Go gate follows the shot's own markers (paused carve-out kept)", () => {
    // Kept as text: this is an effect inside LoomV2 that pushes goBlocked() into the drawer's own
    // handle (el.setBusy). Running it needs LoomV2 itself mounted with a drawer node, which the
    // hook harness does not do; goBlocked's rule is unit-tested in loom-submit-lifecycle.test.js, and
    // the two latches that also call it (generateShot, beginDrawerRender) are driven above and below.
    assert.match(CODE, /const stillBusy = goBlocked\(active\.c, !!\(gs && gs\.phase === "paused"\)\);/);
  });
  test("beforeSend runs the latch and saves the lock before answering ok", async (t) => {
    const price = hold();
    const loom = await mountLoom(t, { routes: { "/api/price": price.route } });
    const v = loom.gen.beginDrawerRender(go());
    v.then(() => EVENTS.push({ kind: "answered" }));
    assert.equal(fetches("/api/price").length, 1, "latched and asking, with nothing awaited first");
    const again = loom.gen.beginDrawerRender(go({ submit_id: "d2" }));
    const render = loom.gen.generateShot(loom.entry("c1"));
    await loom.settle();
    assert.equal(fetches("/api/price").length, 1, "neither a second Go nor the card's Render reached the price");
    assert.deepEqual(await again, REFUSED_BUSY, "a second Go is refused");
    assert.deepEqual(await render, { ok: false, reason: "in-flight" }, "so is the card's own Render");
    price.answer(PAID);
    assert.deepEqual(await v, { ok: true, expectFree: false });
    await loom.settle();
    const lockSave = indexOf((x) => x.kind === "set" && x.key === PPRE + "b1");
    const lockSaved = indexOf((x) => x.kind === "saved" && x.key === PPRE + "b1");
    const answered = indexOf((x) => x.kind === "answered");
    assert.ok(lockSave >= 0 && lockSaved > lockSave && answered > lockSaved, "ok only after the lock's save is answered");
    assert.equal(flat(JSON.parse(EVENTS[lockSave].value)).find((x) => x.c.id === "c1").c.pendingSubmitId, "d1",
      "the lock is the drawer's own submit id");
    assert.equal(fetches("/api/loom/generate").length, 0, "beforeSend never sends anything itself");
  });
  test("beforeSend: a failed save or a save conflict answers refused and takes the lock and the latch off", async (t) => {
    // The drawer POSTs a paid render on ok, so ok must mean the lock is durably saved: a failed
    // save or a conflict refuses, and neither leaves a lock (on the board, the merged board, or
    // the saved one) or a latch behind.
    const loom = await mountLoom(t);
    backend.failSet = true;
    assert.deepEqual(await loom.gen.beginDrawerRender(go()), { refused: "Couldn't save the storyboard, so nothing was sent." });
    assert.ok(!loom.card("c1").pendingSubmitId);
    backend.failSet = false;
    backend.otherTab("b1", boardOf([shot("c1", { title: "RENAMED ELSEWHERE" })]));
    assert.match((await loom.gen.beginDrawerRender(go({ submit_id: "d2" }))).refused, /^This storyboard changed in another tab/);
    assert.ok(!loom.card("c1").pendingSubmitId);
    assert.ok(!flat(backend.board("b1")).find((x) => x.c.id === "c1").c.pendingSubmitId);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ submit_id: "d3" })), { ok: true, expectFree: false }, "the latch came off both times");
  });
  test("beforeSend refuses another board's render and an imported picture before it locks", async (t) => {
    const loom = await mountLoom(t);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ board_id: "b2" })), REFUSED_BOARD);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ payload: { ...DRAWER_PAYLOAD, images: ["local_0123456789ab"] } })),
      { refused: "Imported picture — it can't be sent to PixAI yet. Nothing was sent." }, "S6: refused before it locks or prices");
    assert.equal(fetches("/api/price").length, 0);
    assert.equal(boardSets("b1").length, 0);
    assert.deepEqual(await loom.gen.beginDrawerRender(go()), { ok: true, expectFree: false }, "and the latch was never taken");
  });
  test("beforeSend ASKS before any credit spend, the same fail-closed ask as generateShot (owner walk 2026-09-30)", async (t) => {
    // The Video tab's Go spent 70,000 credits on the click: beforeSend locked and answered ok
    // with no ask. Now it asks through askShotSpend -- the one ask generateShot uses too -- of
    // the payload the drawer POSTs, after the latch and before the lock; a "no" takes the latch
    // off and sends nothing; the lock records the quote the owner said yes to.
    let yes = false;
    const loom = await mountLoom(t, { confirm: () => yes });
    assert.deepEqual(await loom.gen.beginDrawerRender(go()), { cancelled: true });
    assert.deepEqual(fetches("/api/price")[0].body, DRAWER_PAYLOAD,
      "priced: the payload the drawer will POST");
    assert.equal(boardSets("b1").length, 0, "a no locks nothing");
    assert.ok(!loom.card("c1").pendingSubmitId);
    await loom.gen.generateShot(loom.entry("c1"));
    await loom.gen.beginDrawerRender(go({ card_id: "__draft__", submit_id: "d9" }));
    assert.deepEqual(asked(), [ASK_PAID, ASK_PAID, ASK_PAID], "ONE ask, one wording: the drawer's Go, the card's Render, the draft");
    // A no took the latch off: a yes now goes through, and the lock records the quote that was
    // confirmed -- not the drawer's badge (which here claimed free).
    yes = true;
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ submit_id: "d3", quote: { cost: 1, free: true } })), { ok: true, expectFree: false });
    assert.deepEqual(loom.card("c1").pendingQuote, { cost: 900, free: false });
    assert.equal(asked().length, 4);
    assert.equal(reach(BLOCKS, "askShotSpend"), null, "the ask itself can never reach a render");
  });
  test("beforeSend: a price that can't be verified still asks, in the same words on every Go", async (t) => {
    const loom = await mountLoom(t, { routes: { "/api/price": () => { throw new TypeError("Failed to fetch"); } }, confirm: () => false });
    assert.deepEqual(await loom.gen.generateShot(loom.entry("c1")), { ok: false, reason: "cancelled" });
    assert.deepEqual(await loom.gen.beginDrawerRender(go()), { cancelled: true });
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ card_id: "__draft__", submit_id: "d9" })), { cancelled: true });
    assert.deepEqual(asked(), [ASK_UNVERIFIED, ASK_UNVERIFIED, ASK_UNVERIFIED]);
    assert.equal(allSets().length, 0);
  });
  test("beforeSend: a free quote asks nothing and answers expectFree", async (t) => {
    const loom = await mountLoom(t, { routes: { "/api/price": () => FREE } });
    assert.deepEqual(await loom.gen.beginDrawerRender(go()), { ok: true, expectFree: true });
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ card_id: "__draft__", submit_id: "d9" })), { ok: true, expectFree: true });
    assert.deepEqual(asked(), []);
  });
  test("beforeSend: an ask that throws still takes the latch off (review 2026-10-01, nit 2)", async (t) => {
    let boom = true;
    const loom = await mountLoom(t, { confirm: () => { if (boom) throw new Error("dialog blocked"); return true; } });
    await assert.rejects(loom.gen.beginDrawerRender(go()), /dialog blocked/);
    boom = false;
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ submit_id: "d2" })), { ok: true, expectFree: false },
      "not stranded as 'already rendering'");
  });
  test("beforeSend: the board changed during the ask -- nothing is locked or sent", async (t) => {
    const price = hold();
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1")]), b2: boardOf([shot("x1")]) },
      routes: { "/api/price": price.route } });
    const v = loom.gen.beginDrawerRender(go());
    await loom.store.projectApi.openProject("b2");
    price.answer(PAID);
    assert.deepEqual(await v, REFUSED_BOARD);
    assert.equal(boardSets("b1").length, 0, "nothing locked");
    await loom.store.projectApi.openProject("b1");
    await loom.settle();
    assert.ok(!loom.card("c1").pendingSubmitId);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ submit_id: "d3" })), { ok: true, expectFree: false }, "the latch came off");
  });
  test("beforeSend: a draft is asked the same way, locks nothing, and refuses an imported reference before pricing (S6; nit 3)", async (t) => {
    const loom = await mountLoom(t);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ card_id: "__draft__", submit_id: "d9",
      payload: { ...DRAWER_PAYLOAD, images: ["local_0123456789ab"] } })),
      { refused: "Imported picture — it can't be sent to PixAI yet. Nothing was sent." });
    assert.equal(fetches("/api/price").length, 0);
    assert.deepEqual(await loom.gen.beginDrawerRender(go({ card_id: "__draft__", submit_id: "d9" })), { ok: true, expectFree: false });
    assert.deepEqual(asked(), [ASK_PAID]);
    assert.equal(allSets().length, 0, "a draft locks nothing on the board");
  });
});

describe("board storage: nothing writes on open; every board write is the compare-and-swap queue (§1.2, F5, F15)", () => {
  test("the only board writer is the save queue's writeBoard (base_rev); no sSet of a board key anywhere", () => {
    assert.doesNotMatch(CODE, /sSet\(\s*PPRE/);
    assert.equal((CODE.match(/window\.storage\.set\(/g) || []).length, 2, "sSet (pointer, thumbs) and writeBoard");
    assert.match(CODE, /const writeBoard = \(k, json, baseRev\) =>\s*window\.storage\.set\(k, json, false, baseRev !== undefined \? \{ base_rev: baseRev \} : undefined\);/);
    assert.equal((CODE.match(/makeSaveQueue\(/g) || []).length, 1, "ONE queue per page");
  });
  test("the autosave writes only when the board differs from what was last read or written", async (t) => {
    const loom = await mountLoom(t);
    assert.equal(loom.store.busy, false, "opening a board does not even start a save");
    await loom.tick(5000);
    assert.equal(boardSets("b1").length, 0, "opening a board writes nothing");
    loom.store.setProject((p) => ({ ...p, name: "Renamed" }));
    await loom.tick(599);
    assert.equal(boardSets("b1").length, 0, "the autosave waits its 600 ms");
    await loom.tick(1);
    assert.equal(boardSets("b1").length, 1);
    assert.equal(JSON.parse(boardSets("b1")[0].value).name, "Renamed");
    assert.deepEqual(boardSets("b1")[0].opts, { base_rev: "r0" }, "through the queue, on the revision read");
    loom.store.setProject((p) => JSON.parse(JSON.stringify(p)));   // a new object, the same board
    await loom.tick(5000);
    assert.equal(boardSets("b1").length, 1, "what was last written is not written again");
    assert.deepEqual(await loom.store.saveBoardNow("b1"), { ok: true, skipped: true });
  });
  test("loadBoards: a failed list migrates and seeds nothing", async (t) => {
    const loom = await mountLoom(t, { boards: {}, active: null, storage: { failList: true } });
    assert.equal(loom.store.loadError, "list");
    assert.equal(loom.store.project, null);
    assert.equal(allSets().length, 0);
  });
  test("loadBoards: a legacy board that failed to read, or will not parse, is never seeded over", async (t) => {
    const failed = await mountLoom(t, { boards: {}, active: null, storage: { legacy: "{}", failGet: [PKEY] } });
    assert.equal(failed.store.loadError, "legacy");
    assert.equal(allSets().length, 0);
    const garbled = await mountLoom(t, { boards: {}, active: null, storage: { legacy: "{not json" } });
    assert.equal(garbled.store.loadError, "legacy");
    assert.equal(allSets().length, 0);
    // A failed read is refused twice over: by its own check, and by the parse check behind it (a
    // failed read has no value, which is not a board). The second hides the first from anything a
    // test can see, so the first one alone stays a text pin.
    const mig = hookFn(CODE, "loadBoards");
    assert.match(mig, /if \(legacy\.failed\) \{ setLoadError\("legacy"\); return; \}/);
    assert.ok(mig.indexOf("legacy.failed") < mig.indexOf("queueRef.current.save("), "never seed over a legacy read that failed");
    // The one case that cannot lose anything -- a list that SUCCEEDED and came back empty, with no
    // legacy board -- seeds one, written against the "missing" revision.
    const empty = await mountLoom(t, { boards: {}, active: null });
    assert.equal(empty.store.loadError, "");
    const seeded = allSets().filter((x) => x.key.startsWith(PPRE));
    assert.equal(seeded.length, 1);
    assert.deepEqual(seeded[0].opts, { base_rev: "missing" });
  });
  test("loadBoards: a listed board that won't read is skipped and never written over; none readable is an honest failure", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1")]), b2: boardOf([shot("c2")], { name: "Second" }) },
      storage: { unreadable: [PPRE + "b1"] } });
    assert.equal(loom.store.activeId, "b2", "the next readable board opens");
    assert.equal(loom.store.loadError, "");
    assert.equal(allSets().length, 0, "nothing is written -- above all not over b1");
    assert.equal(toasts("A storyboard couldn't be read").length, 1);
    await loom.tick(5000);
    assert.equal(allSets().length, 0, "not by the autosave either");
    const none = await mountLoom(t, { boards: { b1: boardOf([shot("c1")]) }, storage: { unreadable: [PPRE + "b1"] } });
    assert.equal(none.store.loadError, "read");
    assert.equal(none.store.project, null, "no board, and no seed");
    assert.equal(allSets().length, 0);
  });
  test("App shows an honest failure state with a Reload, never the eternal loading line", async (t) => {
    const CASES = [
      ["list", { failList: true }, "The list of storyboards didn't load."],
      ["legacy", { legacy: "{not json" }, "Your saved storyboard didn't read."],
      ["read", { boards: { b1: boardOf([shot("c1")]) }, unreadable: [PPRE + "b1"] }, "None of your storyboards would read."],
    ];
    for (const [why, storage, line] of CASES) {
      freshWorld(t, { storage });
      const app = mountHook(() => LOOM.App());
      await settle(app);
      const tree = app.current;
      const $ = query(renderElement(tree));
      const alert = one($.byAttr("role", "alert"), "failure state (" + why + ")");
      assert.equal(one(alert.byTag("b")).text, "Couldn't read your storyboards");
      assert.equal(one(alert.byTag("span")).text, line + " Nothing was changed or written — check the server, then reload.");
      const reload = one(alert.byTag("button"), "Reload button");
      assert.equal(reload.text, "↻ Reload");
      assert.equal(reload.attr("type"), "button");
      assert.equal($.byText("Loading the bay").length, 0, "not the eternal loading line");
      assert.equal(allSets().length, 0, why + ": nothing written");
      // The button really reloads the page.
      const buttons = [];
      const walk = (x) => {
        if (Array.isArray(x)) { x.forEach(walk); return; }
        if (!x || typeof x !== "object" || !x.props) return;
        if (x.type === "button") buttons.push(x);
        walk(x.props.children);
      };
      walk(tree);
      one(buttons, "button element").props.onClick();
      assert.equal(EVENTS.filter((x) => x.kind === "reload").length, 1);
      app.unmount();
    }
  });
  test("copies of a board never carry a render in flight (F4, F17)", async (t) => {
    const busy = boardOf([shot("c1", rendering("T1")), shot("c2", UNCLEAR), { ...rendered("c3", "500"), ...rendering("T3") }]);
    const loom = await mountLoom(t, { boards: { b1: busy } });
    const inFlight = (board) => flat(board).filter((x) => PENDING_KEYS.some((k) => x.c[k]) || x.c.status === "wip").map((x) => x.c.id);
    await loom.store.projectApi.duplicateProject();
    await loom.settle();
    const copyWrite = allSets().find((x) => x.key.startsWith(PPRE) && x.key !== PPRE + "b1");
    assert.ok(copyWrite, "the copy was written");
    const copy = JSON.parse(copyWrite.value);
    assert.deepEqual(inFlight(copy), [], "the duplicate holds no render of the original's");
    assert.deepEqual(flat(copy).map((x) => x.c.status), ["error", "error", "done"], "a ★ shot stays done");
    assert.equal(loom.store.activeId, copyWrite.key.slice(PPRE.length), "the copy is the board now open");
    assert.deepEqual(inFlight(loom.store.projectRef.current), []);
    // A restored backup: always a NEW board, and never with the backup's renders in flight.
    const file = { name: "board.json", type: "application/json", text: async () => JSON.stringify({ project: busy, thumbs: {} }) };
    await loom.store.importBackup(file);
    await loom.settle();
    const restored = allSets().filter((x) => x.key.startsWith(PPRE) && x.key !== PPRE + "b1" && x.key !== copyWrite.key);
    assert.equal(restored.length, 1);
    assert.deepEqual(inFlight(JSON.parse(restored[0].value)), []);
    assert.deepEqual(inFlight(backend.board("b1")), ["c1", "c2", "c3"], "the original keeps its own renders");
  });
  test("a save conflict merges (takes kept), shows it, and says what moved and what was undone (F6, #59)", async (t) => {
    // What this tab read: A·01 rendering, A·02 with a take. Then another tab renames the board
    // and deletes A·02, and A·01's render lands here.
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", rendering("T1")), rendered("c2", "500")]) },
      routes: { "/api/task-status": () => ({ body: { phase: "done", media_ids: ["777"], duration: 5 } }) } });
    const remoteRev = backend.otherTab("b1", boardOf([shot("c1")], { name: "Renamed elsewhere" }));
    await loom.tick(2500);   // T1 lands: a take only this tab has
    await loom.tick(600);    // the autosave meets the other tab's save: 409
    const merged = loom.store.projectRef.current;
    assert.equal(merged.name, "Renamed elsewhere", "the other tab's board wins its fields");
    assert.deepEqual(loom.card("c1").takes.map((x) => x.mid), ["777"], "this tab's take is kept");
    assert.equal(loom.card("c1").resultMid, "777", "and is ★ (the other tab had none)");
    assert.equal(loom.card("c2"), undefined, "a shot the other tab deleted stays deleted (the merge knew what this tab last synced)");
    const [toast] = toasts("This storyboard changed in another tab");
    assert.ok(toast, "the merge is shown");
    assert.match(toast.msg, /^Your takes were kept; other edits from this tab were replaced\./);
    assert.match(toast.msg, /A·02 stays deleted: the other tab removed it\./, "a dropped shot is named as THIS tab knew it");
    const last = boardSets("b1").at(-1);
    assert.deepEqual(last.opts, { base_rev: remoteRev }, "the merge is saved on the revision the conflict handed back");
    assert.deepEqual(flat(backend.board("b1")).map((x) => x.c.id), ["c1"]);
    assert.equal(flat(backend.board("b1"))[0].c.resultMid, "777");
    // Kept as text: the merge is handed the submits this tab saw end (F6a), so a lock that ended
    // here never comes back from the other tab's board. This landing never calls noteResolved, and
    // driving it means a render that ended while its board was NOT the open one, then a conflict
    // save of that board -- so this one argument stays a pin.
    assert.match(hookFn(CODE, "mergeAfterConflict"), /resolvedSubmits: Array\.from\(resolvedRef\.current\)/);
  });
});

describe("batchGenerate sends only what was confirmed (F12, F13, F14, §3.4)", () => {
  // A 5 s shot is covered by a card; anything longer is paid.
  const priceByLength = (call) => (call.body.duration === 5
    ? { body: { cost: 900, free: true, card_template: "video-5s", card_name: "Video card", cards_held: 3, cards_needed: 1 } }
    : PAID);
  const sentTo = () => fetches("/api/loom/generate").map((p) => p.body.loom_target.card_id);
  const generateAll = async (loom, entries) => {
    const run = loom.gen.batchGenerate(entries);
    for (let i = 0; i < 6; i++) await loom.tick(2200);   // the stagger between shots
    await run;
  };

  test("todo is the current board's needsRender shots; each is held to its confirmed fingerprint and pool verdict", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1"), shot("c2", { duration: 8 }), rendered("c3", "500"),
      shot("c4", rendering("T4"))]) }, routes: { "/api/price": priceByLength } });
    await generateAll(loom, [loom.entry("c3")]);   // the caller's view is not what is sent: the board is
    const [ask] = asked();
    assert.match(ask, /^Generate 2 shot\(s\)\?/, "ONE confirm, of the shots that need a render");
    assert.match(ask, /🎫 1 covered by free cards\n≈ 1 will spend credits — about 900 total/);
    assert.equal(asked().length, 1, "no per-shot confirm after it");
    assert.deepEqual(sentTo(), ["c1", "c2"], "not the rendered shot, not the one in flight");
    const [covered, paid] = fetches("/api/loom/generate");
    assert.equal(covered.body.expect_free, true, "covered by a card: sent expect_free");
    assert.equal("expect_free" in paid.body, false, "a paid shot is sent as one");
    assert.deepEqual(loom.card("c1").pendingQuote, { cost: 900, free: true }, "each lock records the verdict confirmed for it");
    assert.deepEqual(loom.card("c2").pendingQuote, { cost: 900, free: false });
  });
  test("Generate all: a cancelled confirm sends nothing", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1"), shot("c2")]) }, confirm: () => false });
    const run = loom.gen.batchGenerate();
    for (let i = 0; i < 4; i++) await loom.tick(2200);
    await run;
    assert.equal(asked().length, 1);
    assert.equal(fetches("/api/loom/generate").length, 0);
    assert.equal(allSets().length, 0);
  });
  test("a shot priced free on its own, past the tickets held, was confirmed as paid and is sent as paid", async (t) => {
    const oneTicket = () => ({ body: { cost: 900, free: true, card_template: "video-5s", card_name: "Video card", cards_held: 1, cards_needed: 1 } });
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1"), shot("c2")]) }, routes: { "/api/price": oneTicket } });
    await generateAll(loom);
    assert.match(asked()[0], /Up to 1 of those priced free on their own may spend credits instead/);
    const [first, second] = fetches("/api/loom/generate");
    assert.equal(first.body.expect_free, true);
    assert.equal("expect_free" in second.body, false, "the overflow shot is not sent expect_free");
  });
  test("a changed shot is skipped and named; a refusal continues", async (t) => {
    const post = hold();
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1"), shot("c2"), shot("c3")]) }, routes: {
      "/api/loom/generate": (call) => (call.body.loom_target.card_id === "c1" ? post.route()
        : call.body.loom_target.card_id === "c2" ? { status: 400, body: { error: "prompt refused" } } : { body: { task_id: "T3" } }),
    } });
    const run = loom.gen.batchGenerate();
    await loom.settle();
    assert.deepEqual(sentTo(), ["c1"], "A·01's send is out");
    // While it is out, the owner lengthens A·03: its price changed since the confirm.
    loom.store.setProject((p) => patchCardByIdWith(p, "c3", (c) => ({ ...c, duration: 10 })));
    post.answer({ body: { task_id: "T1" } });
    for (let i = 0; i < 6; i++) await loom.tick(2200);
    await run;
    assert.deepEqual(sentTo(), ["c1", "c2"], "A·02's refusal does not stop the batch; the changed A·03 is not sent");
    const [toast] = toasts("Generate all");
    assert.equal(toast.msg, "Skipped A·03: changed since you confirmed. Nothing was sent for them.");
  });
  test("a conflict / busy / unclear stops the rest", async (t) => {
    const CASES = [
      ["busy", { "/api/loom/generate": () => ({ status: 409, body: { error: "This shot is already rendering." } }) }, null,
        "Stopped at A·01 (the server says that shot is already rendering). Nothing after it was sent."],
      ["unclear", { "/api/loom/generate": () => { throw new TypeError("Failed to fetch"); } }, null,
        "Stopped at A·01 (the server didn't confirm that render). Nothing after it was sent."],
      ["conflict", {}, (b) => b.otherTab("b1", boardOf([shot("c1"), shot("c2")], { name: "Elsewhere" })),
        "Stopped at A·01 (the storyboard changed in another tab). Nothing after it was sent."],
    ];
    for (const [why, routes, before, line] of CASES) {
      const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1"), shot("c2")]) }, routes });
      if (before) before(backend);
      await generateAll(loom);
      assert.ok(fetches("/api/loom/generate").length <= 1, why + ": at most the first shot went out");
      assert.ok(!sentTo().includes("c2"), why + ": nothing after it was sent");
      assert.equal(toasts("Generate all")[0].msg, line);
    }
  });
});

describe("the ✂ splice records its anchor; Split waits for a render in flight (§2.1, F11)", () => {
  test("both splice buttons patch through splicePatch with the source captured at the click", () => {
    // Kept as text: the two splice buttons are click handlers inside the LoomV2 and LoomMobile
    // components (inheritPrev / dfInheritPrev), which the hook harness does not mount. Re-anchor,
    // the third reader of the handoff's answer, is a hook and is driven below.
    // `took` is the handoff's own answer -- where it really cut (owner walk 2026-09-30: a frame
    // taken from E·01's end was recorded "at 0.0 s"), read through the one builder, tookOf(d)
    // (code review 2026-10-02: three hand-copied {at, end} builders).
    const n = (CODE.match(/splicePatch\(c{1,2}, \{ frameMid: d\.frame_media_id, src: src\.c, srcCode: src\.code, took: tookOf\(d\) \}\)/g) || []).length;
    assert.equal(n, 2, "desktop inheritPrev and the phone's dfInheritPrev");
    assert.equal((CODE.match(/took: /g) || []).length, 3, "every `took` goes through tookOf -- no hand-built copy");
    assert.doesNotMatch(CODE, /took: \{/, "no hand-built {at, end}");
    assert.equal((CODE.match(/trim_out: src\.c\.trimOut/g) || []).length, 2, "the frame is cut where the source's ★ take is cut");
  });
  test("Re-anchor asks for the frame at the source's cut and records where the handoff really took it (tookOf)", async (t) => {
    const src = rendered("c1", "500", { duration: 8 });
    const anchored = splicePatch(shot("c2"), { frameMid: "600", src, srcCode: "A·01", took: tookOf({ at: 6, at_end: true }) });
    const loom = await mountLoom(t, { boards: { b1: boardOf([src, anchored]) },
      routes: { "/api/loom/handoff": () => ({ body: { frame_media_id: 601, at: 5.5, at_end: false } }) } });
    await loom.takes.reanchorShot("c2");
    const [req] = fetches("/api/loom/handoff");
    assert.deepEqual(req.body, { video_media_id: "500", trim_out: cutPointOf(src) }, "the cut of the source's ★ take");
    const c2 = loom.card("c2");
    assert.equal(c2.openFrame.mediaId, "601");
    assert.equal(c2.anchor.at, 5.5, "where the handoff says it cut");
    assert.equal(c2.anchor.end, false);
    assert.equal(c2.anchor.via, "reanchor");
    assert.equal(fetches("/api/loom/generate").length + fetches("/api/price").length, 0, "a board edit only");
  });
  test("Re-anchor of a source whose length is unknown asks for its last frame (null), never the frame at 0", async (t) => {
    const src = { ...rendered("c1", "500"), actualDur: null, trimOut: null };
    const anchored = splicePatch(shot("c2"), { frameMid: "600", src, srcCode: "A·01", took: tookOf({ at: 6, at_end: true }) });
    const loom = await mountLoom(t, { boards: { b1: boardOf([src, anchored]) },
      routes: { "/api/loom/handoff": () => ({ body: { frame_media_id: 601, at: 7.25, at_end: true } }) } });
    await loom.takes.reanchorShot("c2");
    assert.deepEqual(fetches("/api/loom/handoff")[0].body, { video_media_id: "500", trim_out: null });
    assert.equal(loom.card("c2").anchor.at, 7.25);
    assert.equal(loom.card("c2").anchor.end, true);
  });
  test("splitShot refuses while splitBlocked, with a plain message", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1", { ...rendering("T1"), trimIn: 0, trimOut: null }), rendered("c2", "500")]) } });
    const before = JSON.stringify(loom.store.projectRef.current);
    loom.muts.splitShot(loom.entry("c1"), 3);
    assert.equal(JSON.stringify(loom.store.projectRef.current), before, "the shot is not split");
    const [toast] = toasts("Can't split this shot yet");
    assert.ok(toast, "the owner is told why");
    assert.equal(toast.msg, "A render for this shot is still out. Split it after that take lands (or after you release it).");
    // A shot with nothing out splits.
    loom.muts.splitShot(loom.entry("c2"), 3);
    assert.deepEqual(flat(loom.store.projectRef.current).map((x) => x.c.id).length, 3);
  });
  test("splitShot judges the shot as the board holds it now, not the click's entry", async (t) => {
    const loom = await mountLoom(t, { boards: { b1: boardOf([shot("c1")]) } });
    const stale = loom.entry("c1");
    loom.store.setProject((p) => patchCardByIdWith(p, "c1", (c) => ({ ...c, status: "wip", pendingSubmitId: "s-x", pendingBoard: "b1" })));
    const before = JSON.stringify(loom.store.projectRef.current);
    loom.muts.splitShot(stale, 3);
    assert.equal(JSON.stringify(loom.store.projectRef.current), before, "the shot is not split");
  });
});

/* ---- <VideoDrawer>, driven ----
   The component runs as the hook runtime's one function, the way the Loom mounts it (loomCtx)
   or the gallery does (no loomCtx). The commit step attaches the two refs React would: the root
   node (a recording EventTarget -- the drawer dispatches its mg-* events off it and hangs its
   host API on it) and the CostBadge's handle (the price probe paints through it). Go is the real
   button's onClick from the latest render, so it carries the latest closure, as a click would. */
const isElement = (x) => !!x && typeof x === "object" && x.$$typeof === Symbol.for("react.element");
function walkTree(x, visit) {
  if (Array.isArray(x)) { x.forEach((y) => walkTree(y, visit)); return; }
  if (!isElement(x)) return;
  visit(x);
  walkTree(x.props && x.props.children, visit);
}
const textOf = (x) => (Array.isArray(x) ? x.map(textOf).join("")
  : (typeof x === "string" || typeof x === "number") ? String(x)
    : isElement(x) ? textOf(x.props && x.props.children) : "");
const DRAWER_EVENTS = ["mg-submit", "mg-result", "mg-error", "mg-slow", "mg-paused"];
async function mountDrawer(t, { loomCtx = true, routes = {}, host } = {}) {
  freshWorld(t, { routes });
  const node = new EventTarget();
  const events = [];
  for (const name of DRAWER_EVENTS) node.addEventListener(name, (e) => events.push({ name, detail: e.detail }));
  const badge = { clear() {}, setChecking() {}, setPrice() {} };
  const handle = { current: null };
  const h = mountHook(() => LOOM.VideoDrawer.render({ loomCtx }, handle), { commit: (tree) => walkTree(tree, (el) => {
    if (el.type === "div" && typeof el.ref === "function" && /\bgen-drawer\b/.test(el.props.className || "")) el.ref(node);
    else if (el.type === LOOM.CostBadge && el.ref && typeof el.ref === "object" && !el.ref.current) el.ref.current = badge;
  }) });
  t.after(() => h.unmount());
  await settle(h);
  const api = handle.current;
  assert.ok(api && api.setLoomTarget && api.setHost, "the drawer's host API is on its node");
  if (host) api.setHost(host);
  const drawer = {
    api, events,
    settle: () => settle(h),
    /** Let the price probe settle for the form as it is (its 250 ms debounce, then the answer). */
    async priced() { await settle(h); t.mock.timers.tick(250); await settle(h); },
    /** Put a picture in the start frame and let it be priced: Go is live. */
    async ready(mid = "123456") { api.setRefs([{ media_id: mid, thumb: "/t.jpg" }]); await this.priced(); },
    goButton() {
      let b = null;
      walkTree(h.current, (el) => { if (el.type === "button" && /\bmgd-go\b/.test(el.props.className || "")) b = el; });
      return b;
    },
    /** The real click on Go: the button's own handler, from the latest render. */
    go() {
      const b = this.goButton();
      assert.ok(b && !b.props.disabled, "Go is live");
      return b.props.onClick();
    },
    lines() {
      const out = [];
      walkTree(h.current, (el) => { if (el.props && el.props.className === "mgd-result-line") out.push(textOf(el.props.children)); });
      return out;
    },
    tracks: () => EVENTS.filter((x) => x.kind === "track"),
  };
  return drawer;
}

describe("<VideoDrawer> in the Loom: target at the click, beforeSend before the POST (F7, F13)", () => {
  test("the target is captured at the click and a Loom Go without one sends nothing", async (t) => {
    let decide;
    const asks = [];
    const d = await mountDrawer(t, { host: { beforeSend: (req) => { asks.push(req); return new Promise((res) => { decide = res; }); } } });
    await d.ready();
    // No target: nothing is asked, nothing is sent.
    await d.go();
    assert.equal(asks.length, 0);
    assert.equal(fetches("/api/loom/generate").length, 0);
    assert.deepEqual(d.lines(), ["This render isn't tied to a shot, so nothing was sent."]);
    // A target: captured AT THE CLICK. beforeSend is asked inside the click itself, before
    // anything is awaited, so the shot it names is the one selected when Go was pressed.
    d.api.setLoomTarget({ board_id: "b1", card_id: "c1" });
    const click = d.go();
    assert.equal(asks.length, 1, "asked synchronously, in the click");
    assert.equal(asks[0].card_id, "c1");
    d.api.setLoomTarget({ board_id: "b1", card_id: "c2" });   // another shot is selected while this one is sent
    decide({ ok: true, expectFree: false });
    await click;
    await d.settle();
    const [post] = fetches("/api/loom/generate");
    assert.deepEqual(post.body.loom_target, { board_id: "b1", card_id: "c1" }, "the target is never re-read after the click");
    assert.equal(post.body.submit_id, asks[0].submit_id);
    assert.equal(d.events.find((e) => e.name === "mg-submit").detail.card_id, "c1");
  });
  test("beforeSend is awaited BEFORE submitTask, and a refusal (or no host) returns before it", async (t) => {
    let decide;
    const d = await mountDrawer(t, { host: { beforeSend: () => new Promise((res) => { decide = res; }) } });
    await d.ready();
    d.api.setLoomTarget({ board_id: "b1", card_id: "c1" });
    const click = d.go();
    await d.settle();
    assert.equal(fetches("/api/loom/generate").length, 0, "nothing is POSTed while the host decides");
    decide({ ok: true, expectFree: false });
    await click;
    assert.equal(fetches("/api/loom/generate").length, 1);
    await d.priced();   // the accepted submit re-prices (the balance moved)
    const NO_HOST_LINE = "The storyboard didn't take this render, so nothing was sent.";
    const VERDICTS = [
      [{ refused: "This shot is already rendering. Nothing was sent." }, "This shot is already rendering. Nothing was sent."],
      [null, NO_HOST_LINE],
      [{ ok: false }, NO_HOST_LINE],
      ["throws", NO_HOST_LINE],
    ];
    for (const [verdict, line] of VERDICTS) {
      d.api.setHost({ beforeSend: async () => { if (verdict === "throws") throw new Error("host broke"); return verdict; } });
      await d.go();
      await d.settle();
      assert.equal(fetches("/api/loom/generate").length, 1, JSON.stringify(verdict) + " sends nothing");
      assert.equal(d.lines().at(-1), line);
    }
    d.api.setHost(null);
    await d.go();
    await d.settle();
    assert.equal(fetches("/api/loom/generate").length, 1, "no host: no verdict, nothing sent");
    assert.equal(d.lines().at(-1), NO_HOST_LINE);
  });
  test("the POST adds loom_target (not for a draft), submit_id and expect_free (settled verdict free); the gallery's request is unchanged", async (t) => {
    const routes = {};
    const asks = [];
    const d = await mountDrawer(t, { routes, host: { beforeSend: async (req) => { asks.push(req); return { ok: true }; } } });
    await d.ready();
    d.api.setLoomTarget({ board_id: "b1", card_id: "c1" });
    await d.go();
    const [first] = fetches("/api/loom/generate");
    const { submit_id, loom_target, ...rest } = first.body;
    assert.equal(submit_id, asks[0].submit_id);
    assert.deepEqual(loom_target, { board_id: "b1", card_id: "c1" });
    assert.deepEqual(rest, asks[0].payload, "the form's payload, every key, plus the Loom's keys");
    assert.equal("expect_free" in first.body, false, "the settled verdict was paid");
    // A settled FREE verdict (and a host answer that names none) is sent expect_free.
    routes["/api/price"] = () => FREE;
    await d.ready("123457");
    await d.go();
    assert.equal(fetches("/api/loom/generate")[1].body.expect_free, true);
    // A draft has no shot: no loom_target, still its submit id.
    await d.priced();
    d.api.setLoomTarget({ board_id: "b1", card_id: "__draft__", draft: true });
    await d.go();
    const draft = fetches("/api/loom/generate")[2].body;
    assert.equal("loom_target" in draft, false);
    assert.equal(draft.submit_id, asks[2].submit_id);
    // The gallery's own Video tab: the form's payload, byte for byte -- no host, no Loom keys.
    const g = await mountDrawer(t, { loomCtx: false });
    await g.ready();
    await g.go();
    const [priced] = fetches("/api/price").slice(-1);
    const [sent] = fetches("/api/loom/generate");
    assert.deepEqual(sent.body, priced.body);
    for (const k of ["submit_id", "loom_target", "expect_free"]) assert.equal(k in sent.body, false, k);
  });
  test("the gallery's Video tab sends no Loom key even on a free quote", async (t) => {
    // A free quote is the one case where a stray expect_free on the gallery's request would show.
    const g = await mountDrawer(t, { loomCtx: false, routes: { "/api/price": () => FREE } });
    await g.ready();
    await g.go();
    const [priced] = fetches("/api/price").slice(-1);
    const [sent] = fetches("/api/loom/generate");
    assert.deepEqual(sent.body, priced.body);
  });
  test("in the Loom, what is sent is what the host's ask confirmed; a no sends nothing and leaves no line", async (t) => {
    const routes = {};
    let verdict;
    const d = await mountDrawer(t, { routes, host: { beforeSend: async () => verdict } });
    await d.ready();
    d.api.setLoomTarget({ board_id: "b1", card_id: "c1" });
    verdict = { cancelled: true };
    await d.go();
    await d.settle();
    assert.equal(fetches("/api/loom/generate").length, 0);
    assert.deepEqual(d.lines(), [], "a no leaves no line");
    // The badge said paid; the owner's ask found a card: expect_free follows the ask.
    verdict = { ok: true, expectFree: true };
    await d.go();
    assert.equal(fetches("/api/loom/generate")[0].body.expect_free, true);
    // The badge said free; the ask found it paid (and the owner said yes): not expect_free.
    routes["/api/price"] = () => FREE;
    await d.ready("123457");
    verdict = { ok: true, expectFree: false };
    await d.go();
    assert.equal("expect_free" in fetches("/api/loom/generate")[1].body, false);
  });
  test("every Loom event names its render; a submit with no answer says unclear", async (t) => {
    const routes = {};
    const d = await mountDrawer(t, { routes, host: { beforeSend: async () => ({ ok: true, expectFree: false }) } });
    await d.ready();
    d.api.setLoomTarget({ board_id: "b1", card_id: "c1" });
    await d.go();
    const [post] = fetches("/api/loom/generate");
    const ids = { submit_id: post.body.submit_id, card_id: "c1", board_id: "b1" };
    const ev = (name) => d.events.filter((e) => e.name === name).at(-1).detail;
    const { submit_id: _sid, loom_target: _target, ...sentPayload } = post.body;
    assert.deepEqual(ev("mg-submit"), { task_id: "T1", payload: sentPayload, ...ids },
      "mg-submit names the render and carries the payload that was sent");
    const [track] = d.tracks();
    track.cb("slow", {});
    assert.equal(ev("mg-slow").tier, "slow");
    assert.deepEqual({ ...ev("mg-slow"), elapsed: 0 }, { tier: "slow", elapsed: 0, task_id: "T1", ...ids });
    track.cb("stalled", {});
    assert.deepEqual(ev("mg-paused"), { task_id: "T1", ...ids });
    track.cb("failed", { error: "boom" });
    assert.match(ev("mg-error").error, /boom/);
    assert.deepEqual({ ...ev("mg-error"), error: "" }, { error: "", task_id: "T1", ...ids });
    track.cb("done", { media_ids: ["777"], duration: 5, paid_credit: 900 });
    assert.deepEqual(ev("mg-result"), { media_ids: ["777"], is_video: false, duration: 5, paid_credit: 900, task_id: "T1", ...ids });
    // The submit's own answer, as the Loom's onVideoError reads it.
    const ANSWERS = [
      ["no answer", () => { throw new TypeError("Failed to fetch"); }, true, { threw: true }],
      ["an unreadable answer", () => ({ status: 502, unreadable: true }), true, { threw: true }],
      ["may have started", () => ({ status: 200, body: { error: "may have started", unclear: true } }), true,
        { threw: false, status: 200, body: { error: "may have started", unclear: true } }],
      ["a refusal", () => ({ status: 400, body: { error: "prompt refused" } }), false,
        { threw: false, status: 400, body: { error: "prompt refused" } }],
    ];
    for (const [what, route, unclear, answer] of ANSWERS) {
      routes["/api/loom/generate"] = route;
      await d.priced();
      const before = d.events.length;
      await d.go();
      const err = d.events.slice(before).find((e) => e.name === "mg-error");
      assert.ok(err, what + ": mg-error");
      assert.equal(err.detail.unclear, unclear, what);
      assert.deepEqual(err.detail.answer, answer, what);
      assert.equal(err.detail.card_id, "c1", what);
      assert.equal(err.detail.board_id, "b1", what);
      assert.ok(err.detail.submit_id, what);
      assert.equal(err.detail.task_id, undefined, what + ": no task");
    }
  });
  test("the host hooks only store (they cannot reach doGenerate or submitTask)", () => {
    for (const name of ["setLoomTarget", "setHost", "setBusy", "prefill", "setRefs", "flushPromptEdit"]) {
      const at = DCODE.indexOf("\n  const " + name + " = ");
      assert.ok(at >= 0, name);
      const end = Math.min(...["\n  };", "\n  const "].map((e) => DCODE.indexOf(e, at + 1)).filter((x) => x > at));
      assert.doesNotMatch(DCODE.slice(at, end), /doGenerate|submitTask|beforeSend\(/, name);
    }
  });
});

import { test, describe, before, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { loadModules, one } from "../test-support/render.mjs";

/* ONE PROBE BEHIND EVERY COST LINE (2026-08-22). Six front-end hosts each hand-rolled the same
   debounce -> POST /api/price -> sequence guard -> push into <CostBadge> loop, and only ONE of
   them (the video drawer) carried the payload-identity spend gate written after issue #15 -- a
   settled FREE for a 5s payload let Go submit a 15s one. Five paid surfaces ran without it.

   The loop is now one module (gallery/src/gen/priceProbeCore.js + gen/usePriceProbe.js) and the
   hosts are thin callers. That is a STRUCTURAL property, and structural properties rot back:
   the cheapest way to "just add a price check here" is another inline fetch. So the first two
   blocks walk the real tree rather than checking a hardcoded list -- a SEVENTH copy in a file
   nobody thought of fails them exactly like a regression in one of the six. Those stay source
   reads on purpose: "no file under gallery/src does X" is a fact about the tree, not about
   what any one component renders.

   Everything else here is BEHAVIOUR, driven on the real code (2026-10-08): the probe's own
   ordering rules run the real usePriceProbe through renders, timers and answers; the Tsubaki.3
   edit bar's spend latch presses Enter on the real component; CreateMobile's entry primes run
   its real effects. A static render cannot do any of that (it runs no effects and never
   renders twice -- see loom/test-support/render.mjs), so the components are bundled by the
   render helper and stepped by the small hook runtime below. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const PROBE = "gen/usePriceProbe.js";
// ONE PRICE TRANSPORT (2026-08-23). The request came out of the hook: the probe still owns the
// debounce, the sequence guard, the verdict and the teardown abort, but the POST -- and the
// {response} vs {failed} distinction the spend gate reads -- lives in one module the Loom's own
// nine price sites now ride too. So "the one /api/price caller" moves here.
const TRANSPORT = "gen/priceRequest.js";
const LOOM = path.resolve(__dirname, "../master-storyboard.jsx");

// The six hosts. Named here only to assert they ARE callers -- the "one fetch" rule below is
// derived from the tree, never from this list.
const HOSTS = [
  "gen/useGenerate.js",
  "gen/useEditGenerate.js",
  "components/EditTab.jsx",
  "components/FixTab.jsx",
  "components/UpscalePanel.jsx",
  "components/VideoDrawer.jsx",
  // The Tsubaki.3 edit bar in the Lightbox (w2-gen, 2026-09-28): a paid Enter-to-send host.
  "components/TsubakiEditBar.jsx",
];

function walk(dir, out = []) {
  readdirSync(dir).forEach((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(js|jsx)$/.test(name)) out.push(full);
  });
  return out;
}
const files = walk(SRC);
const rel = (f) => path.relative(SRC, f).split(path.sep).join("/");
const read = (f) => readFileSync(f, "utf8").replace(/\r\n/g, "\n");

/* ---- a small hook runtime ----------------------------------------------------------------
   Calls a REAL hook or function component across renders, the way React's own shallow renderer
   did: for the length of one call it installs a hook dispatcher of its own on React's
   ReactCurrentDispatcher, so useState/useRef/useEffect/... inside the component are answered
   here. State lives between renders, a setState re-renders on the next microtask (React 18's
   batching, near enough), effects run after each render with their cleanups, and unmount() runs
   every cleanup. Child components are NOT rendered -- a component's return value is just its
   element tree, which the tests search for the handlers they press.

   This touches React's internals, so it is written against loom's pinned react 18.3.1 and
   refuses to run on any React that does not expose the dispatcher. */
const REACT_DISPATCHER = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED
  && React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
const mounted = [];

function depsChanged(prev, next) {
  return !prev || !next || prev.length !== next.length || next.some((v, i) => !Object.is(v, prev[i]));
}

function mountHook(fn, initialProps) {
  assert.ok(REACT_DISPATCHER, "React " + React.version + " exposes no ReactCurrentDispatcher -- this "
    + "test's hook runtime was written against loom's pinned react 18.3.1");
  const slots = [];
  let props = initialProps;
  let at = 0;
  let value;
  let alive = true;
  let queued = false;
  let effects = [];

  const later = () => {
    if (!alive || queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; if (alive) run(); });
  };
  const slot = (make) => { const k = at++; if (!(k in slots)) slots[k] = make(); return slots[k]; };
  const memo = (make, deps) => {
    const k = at++;
    const s = slots[k];
    if (s && deps && !depsChanged(s.deps, deps)) return s.value;
    slots[k] = { value: make(), deps };
    return slots[k].value;
  };
  const effect = (create, deps) => {
    const k = at++;
    const prev = slots[k];
    if (prev && deps && !depsChanged(prev.deps, deps)) return;
    const s = { effect: true, deps, cleanup: prev ? prev.cleanup : undefined };
    slots[k] = s;
    effects.push(() => {
      if (s.cleanup) { const c = s.cleanup; s.cleanup = undefined; c(); }
      const out = create();
      s.cleanup = typeof out === "function" ? out : undefined;
    });
  };
  const dispatcher = {
    readContext: (ctx) => ctx._currentValue,
    useContext: (ctx) => ctx._currentValue,
    useState(init) {
      const st = slot(() => {
        const s = { value: typeof init === "function" ? init() : init };
        s.set = (u) => {
          const next = typeof u === "function" ? u(s.value) : u;
          if (Object.is(next, s.value)) return;
          s.value = next;
          later();
        };
        return s;
      });
      return [st.value, st.set];
    },
    useReducer(reducer, arg, init) {
      const st = slot(() => {
        const s = { value: init ? init(arg) : arg };
        s.dispatch = (action) => {
          const next = reducer(s.value, action);
          if (Object.is(next, s.value)) return;
          s.value = next;
          later();
        };
        return s;
      });
      return [st.value, st.dispatch];
    },
    useRef: (v) => slot(() => ({ current: v })),
    useMemo: memo,
    useCallback: (f, deps) => memo(() => f, deps),
    useEffect: effect,
    useLayoutEffect: effect,
    useInsertionEffect: effect,
    useImperativeHandle: (ref, create, deps) => effect(() => {
      if (typeof ref === "function") { ref(create()); return () => ref(null); }
      if (ref) { ref.current = create(); return () => { ref.current = null; }; }
      return undefined;
    }, deps),
    useDebugValue() {},
    useDeferredValue: (v) => v,
    useTransition: () => [false, (f) => f()],
    useSyncExternalStore: (subscribe, getSnapshot) => getSnapshot(),
    useId: () => slot(() => ":hook-runtime-" + at + ":"),
  };

  function run() {
    at = 0;
    effects = [];
    const before = REACT_DISPATCHER.current;
    REACT_DISPATCHER.current = dispatcher;
    try { value = fn(props); } finally { REACT_DISPATCHER.current = before; }
    const pending = effects;
    effects = [];
    pending.forEach((f) => f());
  }

  const handle = {
    get current() { return value; },
    rerender(next) { if (next !== undefined) props = next; run(); return value; },
    unmount() {
      if (!alive) return;
      alive = false;
      slots.forEach((s) => {
        if (s && s.effect && s.cleanup) { const c = s.cleanup; s.cleanup = undefined; c(); }
      });
    },
  };
  run();
  mounted.push(handle);
  return handle;
}

function unmountAll() { while (mounted.length) mounted.pop().unmount(); }
/** Let every pending promise, microtask and queued re-render run. */
async function settle() { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); }

/** Every element in a component's returned tree that satisfies `pred` (children only -- the
    child COMPONENTS are not rendered, their props are what the parent handed them). */
function findEls(node, pred, out = []) {
  if (node == null || typeof node !== "object") return out;
  if (Array.isArray(node)) { node.forEach((n) => findEls(n, pred, out)); return out; }
  if (pred(node)) out.push(node);
  if (node.props) findEls(node.props.children, pred, out);
  return out;
}
const hasClass = (el, c) => typeof el.type === "string"
  && String((el.props && el.props.className) || "").split(/\s+/).includes(c);

describe("the price transport is the one /api/price caller under gallery/src", () => {
  test("exactly one file asks /api/price, and it is gen/priceRequest.js", () => {
    // Re-anchored 2026-08-23: the needle was the literal `fetch("/api/price"`, which stopped
    // covering the whole tree the moment api.js became the one request module -- a stray probe
    // would now be written apiPost("/api/price", ...) and sail straight past a fetch-only
    // needle. Both spellings are the same offence, so both are the needle.
    const ASKS = /(?:fetch|apiGet|apiPost|apiUpload)\(\s*["']\/api\/price["']/;
    const callers = files.filter((f) => ASKS.test(read(f))).map(rel).sort();
    assert.deepEqual(callers, [TRANSPORT],
      "a second inline /api/price call is a second copy of the debounce, the seq guard, the abort "
      + "and -- the part that actually costs money -- the payload-identity gate. Call usePriceProbe "
      + "(or, outside React, requestPrice) instead. Found: " + JSON.stringify(callers));
  });

  test("the probe gets its request from the transport, and keeps no fetch of its own", () => {
    // The hook is still the one PROBE (debounce + seq guard + verdict); what it no longer owns
    // is the wire. If it grew its own fetch back, the {response}-vs-{failed} rule would have two
    // homes again and the Loom's copy would be free to drift from the gallery's.
    const hook = read(files.find((x) => rel(x) === PROBE));
    assert.match(hook, /import\s*\{\s*requestPrice\s*\}\s*from\s+["'][^"']*priceRequest\.js["']/,
      PROBE + " must import requestPrice from the one transport");
    assert.match(hook, /requestPrice\(p, \{ signal: c \? c\.signal : undefined \}\)/,
      "the probe must hand its OWN AbortController's signal to the transport -- stop() aborting "
      + "a request it can no longer reach is the #27 leak coming back");
    assert.doesNotMatch(hook.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, ""), /\bfetch\(/,
      PROBE + " must not fetch for itself any more");
  });

  // The transport's own two roads -- any parsed body (an HTTP-200 {error} included) is a
  // {response}; a dropped socket, an unreadable body, an abort or the timeout is {failed} -- and
  // its one-POST-per-call rule are driven against the real module with a stubbed fetch in
  // loom/test/price-request.test.js (every case there asserts exactly one call). The source pin
  // that used to sit here repeated those facts as regexes, so it was retired 2026-10-08.

  test("no host writes the CostBadge checking handshake by hand", () => {
    // setChecking() is the "blank the number FIRST, synchronously" half of the badge contract:
    // an old quote next to new settings is the one thing worse than no quote. The probe owns it,
    // paired with dropping the verdict identity in the same breath -- a host calling it alone
    // would blank the badge while leaving Go live on a stale verdict.
    const offenders = files
      .filter((f) => rel(f) !== PROBE && rel(f) !== "components/CostBadge.jsx")
      .filter((f) => /setChecking\(/.test(read(f)))
      .map(rel);
    assert.deepEqual(offenders, [],
      "setChecking() belongs to the probe (CostBadge itself declares it). Found: " + JSON.stringify(offenders));
  });
});

describe("every cost line rides the probe", () => {
  HOSTS.forEach((h) => {
    test(h + " imports usePriceProbe", () => {
      const f = files.find((x) => rel(x) === h);
      assert.ok(f, "expected " + h + " to exist");
      assert.match(read(f), /import\s+usePriceProbe\s+from\s+["'][^"']*usePriceProbe\.js["']/,
        h + " must get its price check from the shared probe, not its own loop");
    });
    test(h + " instantiates its OWN probe and owns the badge ref it drives", () => {
      // One probe instance per host is one sequence counter per host. A host that borrowed another
      // surface's probe (or badge ref) would let one surface's re-price cancel the other's.
      const src = read(files.find((x) => rel(x) === h));
      assert.match(src, /usePriceProbe\(\{/,
        h + " must instantiate its OWN probe rather than share another surface's");
      assert.ok(src.includes("costRef"), h + " must own the badge instance its probe drives");
    });
  });

  test("no host keeps a private debounce constant for pricing", () => {
    // PRICE_DEBOUNCE_MS lives in the core; six independent literal 250s is how a timing rule
    // drifts. (Other 250s in these files -- animation, polling -- are not setTimeout(fireCost).)
    HOSTS.forEach((h) => {
      const src = read(files.find((x) => rel(x) === h));
      assert.doesNotMatch(src, /setTimeout\(\s*(fireCost|firePrice|costNow|doPrice)\b/,
        h + " must not schedule its own price fire");
    });
  });
});

/* ---- a badge that remounts is re-primed with force -----------------------------------------
   The image <CostBadge> mounts and unmounts with its tab (desktop dock and mobile Create
   alike), so it comes back idle while the probe's verdict may still be settled for the very
   same payload. An un-forced refresh() short-circuits on "nothing priced changed" and leaves
   Generate LIVE beside a blank badge -- a spend control with no quote on screen. The hook's
   own contract names the remount as one of the two cases `force` exists for; pin the callers. */
describe("a badge that remounts is re-primed with force", () => {
  test("GenerateDrawer's Image-tab entry prime passes force", () => {
    // Still a source pin, deliberately: the prime is a useEffect in a 1,600-line dock whose other
    // effects need a browser (ResizeObserver, document.querySelector, window listeners, the jobs
    // poll) and whose body reads ~40 fields of a live useGenerate. Driving it would mean faking
    // all of that, which breaks on every unrelated dock change; the one line below does not.
    const src = read(path.join(SRC, "components/GenerateDrawer.jsx"));
    assert.match(src, /if \(open && tab === "image"\) g\.refreshPrice\(\{ force: true \}\);/);
  });

  describe("CreateMobile primes its own badges on every entry", () => {
    const CREATE_MOBILE = "gallery/src/components/CreateMobile.jsx";
    let CreateMobile, GEN_DEFAULTS, EDIT_DEFAULTS;
    before(async () => {
      [{ default: CreateMobile }, { GEN_DEFAULTS }, { EDIT_DEFAULTS }] = await loadModules(
        [CREATE_MOBILE, "gallery/src/gen/genCore.js", "gallery/src/gen/editCore.js"]);
    });
    let savedDocument;
    beforeEach(() => {
      // The sheet host is resolved in an effect (document.querySelector(".glm-stage") ||
      // document.body). No phone shell here, so it resolves to nothing and no sheet portals.
      savedDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
      globalThis.document = { querySelector: () => null, body: null };
    });
    afterEach(() => {
      unmountAll();
      if (savedDocument) Object.defineProperty(globalThis, "document", savedDocument);
      else delete globalThis.document;
    });

    function phone(cmode) {
      const primes = { image: [], edit: [] };
      const noop = () => {};
      const edit = {
        s: { ...EDIT_DEFAULTS }, set: noop, addRef: noop, dropRef: noop, chooseModel: noop,
        results: [], gate: null, busy: false, canSubmit: false, run: noop,
        refreshPrice: (opts) => primes.edit.push(opts),
      };
      const props = {
        account: null, costRef: { current: null }, editCostRef: { current: null },
        cmode, setCmode: noop, edit,
        s: { ...GEN_DEFAULTS }, set: noop, busy: false, results: [],
        applyModelRow: noop, pickVersion: noop, addLora: noop, removeLora: noop, setLora: noop,
        generate: noop, refreshPrice: (opts) => primes.image.push(opts),
        addContext: noop, removeContext: noop, sizeContext: noop,
        canSubmit: false, priceAnswer: null,
        run: { parsed: null, plan: null, images: 0, longest: null, templateGate: null, lists: [],
          confirm: null, busy: false, go: noop, cancel: noop, saveLists: noop },
        power: { favModels: [], favLoras: [], toggleQuickFav: noop, modelChips: [], loraChips: [] },
      };
      const screen = mountHook((p) => CreateMobile(p), props);
      return { primes, screen, go: (next) => screen.rerender({ ...props, cmode: next }) };
    }

    test("CreateMobile's Image and Edit entry primes pass force", () => {
      const p = phone("image");
      assert.deepEqual(p.primes.image, [{ force: true }],
        "entering Image mode must prime the Image badge with force -- it mounted idle");
      assert.deepEqual(p.primes.edit, [], "Image mode does not touch Edit's own badge");

      p.go("edit");                 // Edit opens on its Edit sub-tab, where its badge lives
      assert.deepEqual(p.primes.edit, [{ force: true }],
        "entering Edit/Edit must prime Edit's OWN badge with force");

      p.go("image");                // back again: the verdict may still be settled for this draft
      assert.deepEqual(p.primes.image, [{ force: true }, { force: true }],
        "RE-entering Image must prime with force again -- an un-forced refresh short-circuits on "
        + "the unchanged draft and leaves Generate live beside a blank badge");
      p.go("edit");
      assert.deepEqual(p.primes.edit, [{ force: true }, { force: true }]);
    });

    test("the Edit prime fires on the Edit sub-tab only -- the Fixer sub-tab has no Edit badge", async () => {
      const p = phone("edit");
      assert.deepEqual(p.primes.edit, [{ force: true }], "precondition: Edit opens on its Edit sub-tab");
      // Edit's own Edit/Fixer row is the second segmented row (the first is the Image/Edit/... modes).
      const subTab = (label) => {
        const rows = findEls(p.screen.current, (e) => hasClass(e, "cm-seg3"));
        assert.equal(rows.length, 2, "expected the mode row and Edit's own Edit/Fixer row");
        return one(findEls(rows[1], (e) => hasClass(e, "cm-segbtn") && e.props.children === label),
          "the " + label + " sub-tab button");
      };
      subTab("Fixer").props.onClick();
      await settle();
      assert.deepEqual(p.primes.edit, [{ force: true }], "the Fixer sub-tab must not prime Edit's badge");
      subTab("Edit").props.onClick();
      await settle();
      assert.deepEqual(p.primes.edit, [{ force: true }, { force: true }],
        "back on the Edit sub-tab, its remounted badge is primed with force again");
    });
  });
});

/* ---- usePriceProbe's host half of the CostBadge contract, run for real --------------------
   The real hook, through renders: a fake badge records what the probe tells it, a stubbed
   fetch is the server (the probe's own transport, gen/priceRequest.js, really runs), and the
   debounce and the 25s bound run on node's mock clock. Each test is a review finding from
   2026-08-16 that cost, or nearly cost, money. */
describe("usePriceProbe's host half of the CostBadge contract", () => {
  let usePriceProbe, PRICE_DEBOUNCE_MS, PRICE_FETCH_TIMEOUT_MS, priceKey;
  before(async () => {
    const [hook, core] = await loadModules(["gallery/src/gen/usePriceProbe.js", "gallery/src/gen/priceProbeCore.js"]);
    usePriceProbe = hook.default;
    ({ PRICE_DEBOUNCE_MS, PRICE_FETCH_TIMEOUT_MS, priceKey } = core);
  });

  // Payloads. Only the prompt differs between P1 and P1_RETYPED, and the prompt never prices.
  const P1 = { mode: "image", model_id: "m-1", width: 1024, height: 1024, prompt: "a lantern" };
  const P1_RETYPED = { ...P1, prompt: "a lantern at dusk" };
  const P2 = { ...P1, width: 768 };
  const P3 = { ...P1, width: 512 };
  const settledOn = (p) => ({ settled: true, pricedKey: priceKey(p), pendingTimer: false });
  const SCHEDULED = { settled: false, pricedKey: null, pendingTimer: true };
  const FIRED = { settled: false, pricedKey: null, pendingTimer: false };

  // The server: every POST is recorded and stays open until the test answers or drops it.
  const realFetch = globalThis.fetch;
  let fetches = [];
  beforeEach(() => {
    mock.timers.enable({ apis: ["setTimeout"] });
    fetches = [];
    globalThis.fetch = (url, init = {}) => {
      const call = { url, payload: JSON.parse(init.body), signal: init.signal };
      fetches.push(call);
      return new Promise((resolve, reject) => {
        call.answer = (body) => resolve({ json: async () => body });
        call.drop = () => reject(new TypeError("Failed to fetch"));
        if (init.signal) init.signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
    };
  });
  afterEach(() => {
    unmountAll();
    mock.timers.reset();
    globalThis.fetch = realFetch;
  });
  const sent = (p) => fetches.filter((c) => JSON.stringify(c.payload) === JSON.stringify(p));

  function fakeBadge() {
    const log = [];
    return {
      log,
      setChecking() { log.push(["checking"]); },
      setPrice(d) { log.push(["price", d]); },
      clear(...hint) { log.push(["clear", ...hint]); },
    };
  }

  /** A host: its draft (what build() returns), the badge ref it owns, and the probe it runs. */
  function probeHost({ payload, idle = null, badge = fakeBadge() } = {}) {
    const draft = { payload, idle };
    const costRef = { current: badge };
    let props = { build: () => ({ payload: draft.payload, idle: draft.idle }), costRef, enabled: true };
    const r = mountHook((p) => usePriceProbe(p), props);
    return {
      draft, costRef,
      get badge() { return costRef.current; },
      // a fresh render each read: canSubmit is measured against what build() returns NOW
      get probe() { return r.rerender(); },
      setEnabled(enabled) { props = { ...props, enabled }; r.rerender(props); },
      unmount: () => r.unmount(),
    };
  }

  /** The debounce runs out, the probe asks once, the server answers `body`. */
  async function answerNext(body) {
    const before = fetches.length;
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    assert.equal(fetches.length, before + 1, "the debounce ran out: exactly one price request goes out");
    const call = fetches[fetches.length - 1];
    call.answer(body);
    await settle();
    return call;
  }

  test("refresh() short-circuits BEFORE it blanks the badge, and `force` bypasses it", async () => {
    // prompt/negative are outside priceKey ("never prices") yet their handlers refresh, so every
    // typing pause used to blank the badge, disable the submit control and re-POST /api/price for
    // a byte-identical payload. `force` exists for the ONE case where the payload is identical but
    // the verdict is stale anyway -- right after a submit debited the tickets.
    const host = probeHost({ payload: P1 });
    await answerNext({ cost: 120 });
    assert.equal(host.probe.canSubmit, true, "precondition: settled for this payload");

    host.badge.log.length = 0;
    host.draft.payload = P1_RETYPED;          // a keystroke in the prompt
    host.probe.refresh();
    assert.deepEqual(host.badge.log, [],
      "nothing that prices changed, so the badge keeps its quote -- blanking it first was the bug");
    assert.equal(host.probe.canSubmit, true, "...and the submit control stays live");
    mock.timers.tick(PRICE_DEBOUNCE_MS * 4);
    assert.equal(fetches.length, 1, "...and nothing is asked again");

    host.probe.refresh({ force: true });      // same payload, but the tickets were just debited
    assert.deepEqual(host.badge.log, [["checking"]], "force must bypass the short-circuit");
    assert.equal(host.probe.canSubmit, false);
    await answerNext({ cost: 120 });
    assert.equal(host.probe.canSubmit, true);
  });

  test("refresh() blanks the badge SYNCHRONOUSLY, before scheduling -- and drops the verdict identity", async () => {
    const host = probeHost({ payload: P1 });
    await answerNext({ cost: 120 });

    // A priced field changes: the number goes at once, not 250ms later in the fire step.
    host.badge.log.length = 0;
    host.draft.payload = P2;
    host.probe.refresh();
    assert.deepEqual(host.badge.log, [["checking"]],
      "setChecking() must run inside refresh(), before the debounce -- 250ms of stale FREE was the bug");
    assert.equal(fetches.length, 1, "the request itself still waits for the debounce");
    assert.deepEqual(host.probe.verdict, SCHEDULED, "refresh must un-settle the verdict and mark it pending");

    // The identity is dropped even when the payload is byte-identical (a forced re-price after a
    // debit): the old verdict for this very payload must not keep Go live through the debounce.
    await answerNext({ cost: 90 });
    assert.equal(host.probe.canSubmit, true);
    host.probe.refresh({ force: true });
    assert.equal(host.probe.canSubmit, false, "a scheduled re-price drops the verdict the same instant");
    assert.deepEqual(host.probe.verdict, SCHEDULED);

    // An answer already in flight was priced off a payload that stopped being true.
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const stale = fetches[fetches.length - 1];
    host.draft.payload = P3;
    host.probe.refresh();
    host.badge.log.length = 0;
    stale.answer({ cost: 999 });
    await settle();
    assert.deepEqual(host.badge.log, [], "refresh must invalidate the answer already in flight");
    assert.deepEqual(host.probe.verdict, SCHEDULED, "...and it must not settle anything");
    await answerNext({ cost: 30 });
    assert.deepEqual(host.badge.log.at(-1), ["price", { cost: 30 }]);
    assert.deepEqual(host.probe.verdict, settledOn(P3));
  });

  test("the fire step clears pendingTimer BEFORE any early bail, and the request stays bounded", async () => {
    // (a) an early return (no badge mounted) that ran before the verdict write left
    // {pendingTimer:true} forever, so the gate never opened again.
    const bare = probeHost({ payload: P1, badge: null });
    assert.deepEqual(bare.probe.verdict, SCHEDULED, "the mount prime scheduled a price");
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    assert.deepEqual(bare.probe.verdict, FIRED,
      "the timer fired: pendingTimer must be cleared even though there was no badge to paint");
    assert.equal(fetches.length, 0, "no badge, nothing asked");
    bare.costRef.current = fakeBadge();       // the badge mounts; the next refresh goes through
    bare.probe.refresh();
    await answerNext({ cost: 40 });
    assert.equal(bare.probe.canSubmit, true);

    // (b) an unbounded request that hung left the control disabled forever on a muted "Checking
    // cost…" -- fail-silent-closed. The bound lives in the transport and is unconditional, so it
    // must hold for the probe, which always supplies its own signal.
    const host = probeHost({ payload: P2 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const hung = one(sent(P2), "price request for the hung payload");
    mock.timers.tick(PRICE_FETCH_TIMEOUT_MS - 1);
    await settle();
    assert.equal(hung.signal.aborted, false);
    assert.equal(host.probe.canSubmit, false, "still checking just short of the bound");
    mock.timers.tick(1);
    await settle();
    assert.equal(hung.signal.aborted, true, "a hung price request is aborted at the shared bound");
    assert.deepEqual(host.badge.log.at(-1), ["price", null], "...onto the red could-not-verify");
    assert.deepEqual(host.probe.verdict, settledOn(P2), "...which settles for the payload it judged");
    assert.equal(host.probe.canSubmit, true, "fail-closed-but-live, never a control stuck shut");
    assert.equal(sent(P2).length, 1, "a timeout is never a retry");

    // (c) the request is abortable from the probe -- stop() owns the controller.
    const leaving = probeHost({ payload: P3 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const out = one(sent(P3), "price request in flight");
    leaving.unmount();
    assert.equal(out.signal.aborted, true,
      "the probe must hand the transport its own signal, so teardown reaches the request in flight");
  });

  test("every exit settles for the payload it judged, under the sequence guard", async () => {
    // A FAILED check settles too: the badge's red "couldn't verify — may spend" IS this payload's
    // verdict, whereas a verdict for a DIFFERENT payload is exactly what canSubmit refuses.
    const answered = probeHost({ payload: P1 });
    const d = { cost: 300, free: false };
    await answerNext(d);
    assert.deepEqual(answered.badge.log.at(-1), ["price", d]);
    assert.deepEqual(answered.probe.response, d);
    assert.deepEqual(answered.probe.verdict, settledOn(P1));
    assert.equal(answered.probe.canSubmit, true);
    answered.unmount();

    const failed = probeHost({ payload: P1 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    fetches[fetches.length - 1].drop();
    await settle();
    assert.deepEqual(failed.badge.log.at(-1), ["price", null], "a failed check paints could-not-verify");
    assert.equal(failed.probe.response, null);
    assert.deepEqual(failed.probe.verdict, settledOn(P1), "a failed check settles too -- fail-closed-but-live");
    assert.equal(failed.probe.canSubmit, true);
    failed.unmount();

    // An idle build settles as well, clearing the badge to its own hint or to a one-shot one: an
    // unsettled idle dead-disables the submit control with no message on screen.
    const asked = fetches.length;
    const idle = probeHost({ payload: null, idle: true });
    const hinted = probeHost({ payload: null, idle: "Pick a source image first" });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    await settle();
    assert.equal(fetches.length, asked, "nothing to price, nothing asked");
    assert.deepEqual(idle.badge.log.at(-1), ["clear"]);
    assert.deepEqual(hinted.badge.log.at(-1), ["clear", "Pick a source image first"]);
    for (const h of [idle, hinted]) {
      assert.equal(h.probe.response, null);
      assert.deepEqual(h.probe.verdict, settledOn(null));
      assert.equal(h.probe.canSubmit, true, "the host's own refusal message stays reachable");
    }

    // The key is taken off the SAME payload that is sent, at the moment it is sent.
    const moved = probeHost({ payload: P2 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const call = one(sent(P2), "price request");
    moved.draft.payload = P3;                 // the form moved on before the answer came back
    call.answer({ cost: 50 });
    await settle();
    assert.deepEqual(moved.probe.verdict, settledOn(P2), "the verdict is FOR the payload that was priced");
    assert.equal(moved.probe.canSubmit, false, "...so it can never carry a different submit");

    // There used to be TWO guards because the answer arrived in .then and the failure in .catch.
    // requestPrice never rejects -- it RESOLVES onto one road or the other -- so both join at one
    // guard, which must stand before either of them touches the badge.
    for (const road of ["answer", "drop"]) {
      const host = probeHost({ payload: P1 });
      mock.timers.tick(PRICE_DEBOUNCE_MS);
      const stale = fetches[fetches.length - 1];
      host.draft.payload = P2;
      host.probe.refresh();                   // the payload stopped being true
      host.badge.log.length = 0;
      if (road === "answer") stale.answer({ cost: 1 }); else stale.drop();
      await settle();
      assert.deepEqual(host.badge.log, [], "a stale " + road + " must not touch the badge");
      assert.deepEqual(host.probe.verdict, SCHEDULED, "...nor settle a verdict");
      assert.equal(host.probe.response, null);
      host.unmount();
    }
  });

  test("the sequence counter is owned inside the hook", async () => {
    // Each cost surface owns its OWN sequence (the classic's editCost once shared `costSeq` with the
    // Generate tab's debouncedCost(), so an '?edit=' deep link cancelled the Generate tab's first
    // price check before it ever fired). One probe instance per host is one counter per host.
    const generate = probeHost({ payload: P1 });
    const edit = probeHost({ payload: P2 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);      // both surfaces ask
    const first = one(sent(P1), "the Generate tab's first price check");
    edit.draft.payload = P3;
    edit.probe.refresh();                     // the other surface re-prices meanwhile
    first.answer({ cost: 10 });
    await settle();
    assert.deepEqual(generate.badge.log.at(-1), ["price", { cost: 10 }],
      "another surface's re-price must not cancel this surface's answer");
    assert.deepEqual(generate.probe.verdict, settledOn(P1));
  });

  test("a badge that unmounts mid-flight is not written to", async () => {
    // The join-point guard's other half: the badge can go (its ref cleared) while a request is in
    // flight and `enabled` never went false. Writing to it then throws inside the answer's .then
    // -- an unhandled rejection and a verdict stuck unsettled.
    const host = probeHost({ payload: P1 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const call = one(sent(P1), "price request");
    host.costRef.current = null;
    call.answer({ cost: 5 });
    await settle();
    assert.deepEqual(host.probe.verdict, FIRED, "nothing settled");
  });

  test("disabling (or unmounting) clears the timer AND aborts the request in flight", async () => {
    // #27: leaving a tab used to leave the armed timer, so one stray /api/price fired ~250ms
    // after the tab was gone. Coming back forces a re-price -- the badge remounted idle.
    const host = probeHost({ payload: P1 });
    host.setEnabled(false);                   // the debounce was armed by the mount prime
    mock.timers.tick(PRICE_DEBOUNCE_MS * 4);
    assert.equal(fetches.length, 0, "a disabled probe must not fire its armed timer");

    host.badge.log.length = 0;
    host.setEnabled(true);
    assert.deepEqual(host.badge.log, [["checking"]], "enabled again: a fresh price is scheduled");
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const inFlight = one(sent(P1), "price request");
    host.badge.log.length = 0;
    host.setEnabled(false);
    assert.equal(inFlight.signal.aborted, true, "disabling aborts the request in flight");
    await settle();
    assert.deepEqual(host.badge.log, [], "...and its late end writes nothing");

    host.setEnabled(true);                    // settled on this exact payload, then hidden again:
    await answerNext({ cost: 70 });
    host.setEnabled(false);
    host.badge.log.length = 0;
    host.setEnabled(true);                    // ...coming back still re-prices (force)
    assert.deepEqual(host.badge.log, [["checking"]], "enabled true forces a fresh price");
    assert.equal(host.probe.canSubmit, false);
    await answerNext({ cost: 70 });

    // Unmount runs the same teardown: an armed timer never fires, a request in flight is aborted.
    const armed = probeHost({ payload: P2 });
    armed.unmount();
    mock.timers.tick(PRICE_DEBOUNCE_MS * 4);
    assert.equal(sent(P2).length, 0, "an unmounted probe must not fire its armed timer");
    const gone = probeHost({ payload: P3 });
    mock.timers.tick(PRICE_DEBOUNCE_MS);
    const last = one(sent(P3), "price request");
    gone.unmount();
    assert.equal(last.signal.aborted, true, "unmount aborts the request in flight");
  });
});

/* ---- the Loom's nine sites ---------------------------------------------------------------
   master-storyboard.jsx carried NINE hand-rolled
   `fetch("/api/price", {method:"POST", ...}).then(r => r.json()).catch(...)` blocks -- LoomV2's
   priceInto and its Fixer preview, LoomMobile's Image / Edit / Reference / Fixer previews, and
   useGenerationPipeline's priceShot, confirmSpend and genFix. Nine copies of one transport is
   nine private answers to "what does a dropped socket mean here", on the app's most expensive
   surface. They ride one function now, over the same gen/priceRequest.js the gallery's probe
   uses. This is a STRUCTURAL property and structural properties rot back -- the cheapest way to
   "just price this too" is a tenth inline fetch -- so it is walked, not listed. */
describe("the Loom asks for a price in exactly one place", () => {
  const loom = readFileSync(LOOM, "utf8").replace(/\r\n/g, "\n");
  // A "no code may do X" assertion has to read CODE only: the comments explaining what was
  // removed name the route, and would otherwise trip the guard they document.
  const loomCode = loom.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  test("no /api/price URL survives in the Loom's code -- the route belongs to the transport", () => {
    assert.doesNotMatch(loomCode, /["']\/api\/price["']/,
      "a hand-written /api/price in the Loom is a tenth copy of the transport, and it would be "
      + "free to disagree with the gallery about whether a failed check may imply free");
  });

  test("requestPrice is called from exactly ONE function, and it is priceBody", () => {
    // Walk: find every call and name its enclosing declaration, rather than checking a list.
    const hosts = [];
    const re = /requestPrice\(/g;
    let m;
    while ((m = re.exec(loomCode)) !== null) {
      const decls = [...loomCode.slice(0, m.index)
        .matchAll(/(?:^|\n)\s*(?:const|let|var|function)\s+(\w+)/g)];
      hosts.push(decls.length ? decls[decls.length - 1][1] : "(module top level)");
    }
    assert.deepEqual(hosts, ["priceBody"],
      "every price the Loom asks for must go through its one call site. Found callers in: "
      + JSON.stringify(hosts));
  });

  test("priceShot is the shot-shaped face of that one call, not a second one", () => {
    assert.match(loomCode, /const priceShot = \(entry\) => priceBody\(shotPayload\(entry\)\);/,
      "priceShot must delegate to priceBody -- batchGenerate, generateShot and the cost-to-finish "
      + "pill all reach the wire through it");
  });

  test("the collapse actually happened -- the old sites are real callers now", () => {
    // Guards against this suite passing vacuously if the nine were deleted rather than migrated.
    // The floor is deliberately below the real count; the count itself is not written down here.
    const callers = (loomCode.match(/\bpriceBody\(/g) || []).length;
    assert.ok(callers >= 8,
      "expected the Loom's price sites to have collapsed onto priceBody, found " + callers);
  });

  test("each caller keeps its OWN staleness contract -- only the transport is shared", () => {
    // DECISIONS: "Cost-to-finish pill deliberately does NOT share the batch's pre-confirm
    // pricing" -- a browsing estimate may be slightly stale, the number shown at the moment of
    // spending may not. Unifying the transport must not quietly unify those two, so pin both.
    assert.match(loomCode, /const \[priceCache, setPriceCache\] = useState\(\{\}\);/,
      "the cost-to-finish pill keeps its own warm per-shot cache");
    assert.match(loomCode, /priceDebounceRef\.current = setTimeout\(\(\) => notDone\.forEach\(\(e\) => ensurePriced\(e\)\), PRICE_DEBOUNCE_MS\);/,
      "the pill keeps its own board debounce");
    assert.match(loomCode, /const prices = await Promise\.all\(todo\.map\(\(e\) => priceShot\(e\)\)\);/,
      "batchGenerate must keep pricing every shot FRESH right before the confirm -- never off "
      + "the pill's cache");
    const batchAt = loomCode.indexOf("const prices = await Promise.all(todo.map((e) => priceShot(e)));");
    const confirmAt = loomCode.indexOf("if (!window.confirm(msg)) { setBatching(false); return; }");
    assert.ok(batchAt >= 0 && confirmAt > batchAt,
      "the batch's fresh pricing pass must run BEFORE its confirm, not after");
    assert.doesNotMatch(loomCode, /priceCache\[[^\]]*\][\s\S]{0,120}tallyPricesDetailed/,
      "the batch must never tally the pill's cached prices");
  });
});

/* ---- the Tsubaki.3 edit bar's spend latch (w2-gen blocker B1; waves 2+3 review, F3) --------
   The bar sends a PAID edit on Enter, from a text field where a held key auto-repeats and an
   IME commits with Enter. These press keys on the REAL component: its probe, its submit and
   its one metadata read are stubbed (the probe's own rules are driven above, against the real
   hook), so what is under test is the handler's own latch, verdict check and re-price. */
describe("TsubakiEditBar's spend latch", () => {
  const TEB = "gallery/src/components/TsubakiEditBar.jsx";

  // The stubs are reached through one global the mocked modules read at call time.
  const MOCKS = {
    "gallery/src/gen/usePriceProbe.js":
      "export default function usePriceProbe(opts) { return globalThis.__tsubakiBarTest.probe(opts); }\n",
    "gallery/src/gen/submitTask.js":
      "export function submitTask(route, payload, opts) { return globalThis.__tsubakiBarTest.submit(route, payload, opts); }\n",
    "gallery/src/hooks/useAccountPrefs.js":
      "export default function useAccountPrefs() { return { get: () => null }; }\n",
    "gallery/src/api.js":
      "export function apiGet(url) { return globalThis.__tsubakiBarTest.apiGet(url); }\n",
  };
  const PICTURE = { media_id: "m-1", tsubaki_edit: true, w: 1024, h: 1024, thumb: "" };
  const META = { versions: [{ version_id: "v-1", is_latest: true, model_type: "MMDIT", context_images: true }] };
  let renderBar;
  before(async () => {
    const [mod] = await loadModules([TEB], { mocks: MOCKS });
    renderBar = mod.default.render;           // forwardRef: the function component inside it
  });
  afterEach(() => { unmountAll(); delete globalThis.__tsubakiBarTest; });

  const keydown = (extra = {}) => ({
    key: "Enter", shiftKey: false, repeat: false, nativeEvent: { isComposing: false },
    preventDefault() {}, stopPropagation() {}, currentTarget: { blur() {} }, ...extra,
  });

  /** The bar on a still picture, Tsubaki.3 read, words typed. */
  async function editBar({ canSubmit = true } = {}) {
    const probe = { canSubmit, verdict: null, response: null, refreshes: [] };
    probe.refresh = (opts) => { probe.refreshes.push(opts === undefined ? "plain" : opts); };
    const sends = [];
    globalThis.__tsubakiBarTest = {
      probe: () => probe,
      submit: (route, payload) => new Promise((resolve) => sends.push({ route, payload, resolve })),
      apiGet: async () => META,
    };
    const bar = mountHook((props) => renderBar(props, null), { item: PICTURE, member: true });
    await settle();                           // Tsubaki.3's metadata arrives
    const el = {
      get field() { return one(findEls(bar.current, (e) => e.type === "input"), "the edit field"); },
      get go() { return one(findEls(bar.current, (e) => hasClass(e, "mgteb-go")), "the send button"); },
    };
    const type = async (text) => { el.field.props.onChange({ target: { value: text } }); await settle(); };
    await type("make it night");
    return { bar, probe, sends, el, type };
  }

  test("the latch is checked and SET before send()'s first await", async () => {
    const { el, sends, type } = await editBar();
    assert.equal(el.go.props.disabled, false, "precondition: words typed, picture ready, price settled");
    // Two Enters in one tick both run against the SAME render (no repaint between them), and the
    // button's click in that render too. Only a latch set synchronously, before the POST's await,
    // stops the second and third.
    const { onKeyDown } = el.field.props;
    const { onClick } = el.go.props;
    onKeyDown(keydown());
    onKeyDown(keydown());
    onClick();
    assert.equal(sends.length, 1, "a second Enter in the same tick must find the latch set -- one paid send");

    sends[0].resolve("task-1");               // the server answered: the latch is released
    await settle();
    await type("now add rain");
    el.field.props.onKeyDown(keydown());
    assert.equal(sends.length, 2, "after the answer, the next deliberate send goes through");
  });

  test("send() checks the probe's verdict itself, before anything is sent", async () => {
    const { el, sends, probe, bar } = await editBar();
    // An Enter against a stale render: the field's handler was drawn while the verdict allowed a
    // send, and the verdict has moved on with no repaint yet.
    const { onKeyDown } = el.field.props;
    probe.canSubmit = false;
    // Typing the words already ran the bar's own refresh() effect, so the refusal's own re-price
    // is measured as a delta, not read off the last entry.
    const askedBefore = probe.refreshes.length;
    onKeyDown(keydown());
    assert.equal(sends.length, 0, "send() must refuse on !probe.canSubmit inside the handler, not only via the button");
    assert.equal(probe.refreshes.length, askedBefore + 1, "...and ask for a fresh quote instead");
    assert.equal(probe.refreshes.at(-1), "plain");

    bar.rerender();                           // repainted: the button is off, and its handler still refuses
    assert.equal(el.go.props.disabled, true);
    el.go.props.onClick();
    assert.equal(sends.length, 0);
  });

  test("send() ends with a FORCED re-price", async () => {
    const { el, sends, probe, type } = await editBar();
    const forced = () => probe.refreshes.filter((r) => r && r.force === true).length;
    el.field.props.onKeyDown(keydown());
    assert.equal(sends.length, 1);
    assert.equal(forced(), 0, "nothing is re-primed before the server answers");
    sends[0].resolve("task-1");
    await settle();
    assert.deepEqual(probe.refreshes.at(-1), { force: true },
      "after the send, the quote must be re-primed with force -- an un-forced refresh "
      + "short-circuits on an unchanged payload and leaves a stale verdict live");

    await type("make it night");              // a send the server refused re-primes as well
    el.field.props.onKeyDown(keydown());
    sends[1].resolve(null);
    await settle();
    assert.deepEqual(probe.refreshes.at(-1), { force: true });
    assert.equal(forced(), 2);
  });

  test("Enter ignores an auto-repeat and an IME commit before it can call send()", async () => {
    const { el, sends, probe } = await editBar();
    const asked = probe.refreshes.length;
    el.field.props.onKeyDown(keydown({ repeat: true }));
    el.field.props.onKeyDown(keydown({ nativeEvent: { isComposing: true } }));
    assert.equal(sends.length, 0, "a held Enter's auto-repeat and an IME's committing Enter must not send");
    assert.equal(probe.refreshes.length, asked, "...nor reach any other branch of the handler");
    el.field.props.onKeyDown(keydown());
    assert.equal(sends.length, 1, "a plain Enter on the same bar does send");
  });
});

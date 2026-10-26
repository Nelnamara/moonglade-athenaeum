import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { loadModule } from "../test-support/render.mjs";

/* ISSUE #90 -- what <VideoDrawer> tells its host about a shot's settings (SPEC_final B, J).

   The drawer kept the engine, the channel and the prompt helper in its own state and told the
   Loom nothing, so the board priced and sent V4.0 Lite whatever the drawer showed. Three commit
   events now leave from the three controls, and the Loom-only "Use these settings for every
   shot" button asks the host to copy the five settings to every shot:

     mg-model-commit       { model, duration }      the engine chip (duration AS GATED)
     mg-channel-commit     { isPrivate }            Normal | Private
     mg-helper-commit      { videoHelper }          the Video prompt helper switch
     mg-apply-all-request  { model, isPrivate, audioGen, audioLanguage, videoHelper }

   Like mg-mode-commit they come only from a direct user action, never from prefill or gating:
   the host answers each one with a prefill, so an emit on that road would loop.

   HOW IT RUNS. The real component, bundled by the render helper, runs under a small hook
   dispatcher (the loom-render-lifecycle-wiring.test.js technique): state and refs by call
   order, effects after the render, useImperativeHandle as a layout effect. The commit step hands
   the root <div>'s ref a recording EventTarget, so emit() dispatches onto it and the host API
   is hung on it. A click is the real handler from the latest render. The CostBadge ref is left
   unattached, so the price probe's fire step returns before any request: nothing is fetched. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "../../gallery/src/components/VideoDrawer.jsx"), "utf8").replace(/\r\n/g, "\n");
const CSS = readFileSync(path.join(here, "../../gallery/src/styles/gen-drawer.css"), "utf8");
// Code with its comments out (the header comment names every event it explains).
const CODE = SRC.replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const VideoDrawer = (await loadModule("gallery/src/components/VideoDrawer.jsx")).default;
// The drawer portals its ref preview into document.body; nothing else here touches a document.
globalThis.document = globalThis.document || { body: { nodeType: 1 }, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; } };

const DISPATCHER = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
const sameDeps = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => Object.is(x, b[i]));
const isElement = (x) => !!x && typeof x === "object" && x.$$typeof === Symbol.for("react.element");
function walk(x, visit) {
  if (Array.isArray(x)) { x.forEach((y) => walk(y, visit)); return; }
  if (!isElement(x)) return;
  visit(x);
  walk(x.props && x.props.children, visit);
}
const textOf = (x) => (Array.isArray(x) ? x.map(textOf).join("")
  : (typeof x === "string" || typeof x === "number") ? String(x)
    : isElement(x) ? textOf(x.props && x.props.children) : "");

const EVENTS = ["mg-model-commit", "mg-channel-commit", "mg-helper-commit", "mg-apply-all-request",
  "mg-mode-commit", "mg-duration-commit", "mg-audio-commit", "mg-prompt-commit"];

function mountDrawer(t, props) {
  const slots = [], effects = [];
  let at = 0, dirty = true, live = true, tree = null;
  const slot = (make) => { const k = at++; if (!(k in slots)) slots[k] = make(); return slots[k]; };
  const effect = (fn, deps) => {
    const s = slot(() => ({ deps: null, cleanup: null, ran: false }));
    if (s.ran && sameDeps(s.deps, deps)) return;
    effects.push(() => { if (typeof s.cleanup === "function") s.cleanup(); s.cleanup = fn(); s.deps = deps; s.ran = true; });
  };
  const dispatcher = {
    useState(init) {
      const s = slot(() => {
        const c = { value: typeof init === "function" ? init() : init };
        c.set = (a) => { if (!live) return; const v = typeof a === "function" ? a(c.value) : a; if (!Object.is(v, c.value)) { c.value = v; dirty = true; } };
        return c;
      });
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
    useImperativeHandle(ref, create, deps) { effect(() => { ref.current = create(); return () => { ref.current = null; }; }, deps); },
  };
  const node = new EventTarget();
  const events = [];
  for (const name of EVENTS) node.addEventListener(name, (e) => events.push({ name, detail: e.detail }));
  const handle = { current: null };
  const flush = () => {
    for (let n = 0; dirty && live; n++) {
      assert.ok(n < 50, "the drawer never settles");
      dirty = false;
      const prev = DISPATCHER.current;
      DISPATCHER.current = dispatcher;
      at = 0;
      try { tree = VideoDrawer.render(props, handle); } finally { DISPATCHER.current = prev; }
      walk(tree, (el) => { if (el.type === "div" && typeof el.ref === "function" && /\bgen-drawer\b/.test(el.props.className || "")) el.ref(node); });
      effects.splice(0).forEach((run) => run());
    }
  };
  flush();
  t.after(() => {
    live = false;
    slots.forEach((s) => { if (s && typeof s.cleanup === "function") { try { s.cleanup(); } catch { /* best effort */ } } });
  });
  const find = (pred) => { flush(); const out = []; walk(tree, (el) => { if (pred(el)) out.push(el); }); return out; };
  const cls = (c) => (el) => typeof el.props.className === "string" && el.props.className.split(/\s+/).includes(c);
  return {
    api: handle.current, events, find,
    /** The real handler of the one element matching, from the latest render; then re-render. */
    click(pred, arg) {
      const [el, ...more] = find(pred);
      assert.ok(el && !more.length, "expected exactly one element to click");
      const h = el.props.onClick || el.props.onChange;
      h(arg);
      flush();
    },
    engine: (value) => (el) => cls("mgd-engchip")(el) && el.key === value,
    channel: (label) => (el) => cls("mgd-channel")(el) && textOf(el.props.children) === label,
    helper: cls("mgd-helper"),
    applyAll: cls("mgd-applyall"),
    commits: () => events.filter((e) => e.name !== "mg-prompt-commit"),
  };
}

const ref = (id) => ({ media_id: String(id), thumb: "/t/" + id + ".jpg" });

describe("the three shot-setting commits leave from their own control, carrying the gated value", () => {
  test("an engine pick: mg-model-commit { model, duration } with the duration AFTER gating", (t) => {
    const d = mountDrawer(t, { loomCtx: true });
    d.api.prefill({ mode: "r2v", video_model: "tbkv1.0.1", duration: 15, images: [ref(1), ref(2)] });
    assert.deepEqual(d.events, [], "a prefill commits nothing");
    d.click(d.engine("v3.2"));
    assert.deepEqual(d.commits(), [{ name: "mg-model-commit", detail: { model: "v3.2", duration: 10 } }],
      "15 s clamps to V3.2's 10 s cap; no mode rides the event");
    assert.equal(d.api.mode, "flf", "the drawer itself still gates the mode (the host computes its own)");
    d.click(d.engine("tbkv1.0"));
    assert.deepEqual(d.commits()[1], { name: "mg-model-commit", detail: { model: "tbkv1.0", duration: 10 } });
  });

  test("Normal | Private: mg-channel-commit { isPrivate }, and a click on the lit one says nothing", (t) => {
    const d = mountDrawer(t, { loomCtx: true });
    d.click(d.channel("Private"));
    d.click(d.channel("Private"));
    d.click(d.channel("Normal"));
    assert.deepEqual(d.commits(), [
      { name: "mg-channel-commit", detail: { isPrivate: true } },
      { name: "mg-channel-commit", detail: { isPrivate: false } },
    ]);
  });

  test("the prompt helper switch: mg-helper-commit { videoHelper }", (t) => {
    const d = mountDrawer(t, { loomCtx: true });
    d.click(d.helper, { target: { checked: true } });
    d.click(d.helper, { target: { checked: false } });
    assert.deepEqual(d.commits(), [
      { name: "mg-helper-commit", detail: { videoHelper: true } },
      { name: "mg-helper-commit", detail: { videoHelper: false } },
    ]);
  });

  test("prefill and gating emit none of them, whatever they change", (t) => {
    const d = mountDrawer(t, { loomCtx: true });
    d.api.prefill({ mode: "r2v", video_model: "v2.7", duration: 15, is_private: true, prompt_helper: true, audio: true, images: [ref(3)] });
    d.api.prefill({ mode: "flf", video_model: "v4.0", duration: 6, is_private: false, prompt_helper: false, images: [ref(4), ref(5)], same_shot: true });
    d.api.setRefs([ref(6)]);
    assert.deepEqual(d.commits(), []);
  });
});

describe("\"Use these settings for every shot\" (J's button)", () => {
  test("renders in the Loom only, under the engine meta row, worded and titled", (t) => {
    const loom = mountDrawer(t, { loomCtx: true });
    const [btn, ...more] = loom.find(loom.applyAll);
    assert.ok(btn && !more.length, "the Loom's drawer has the button, once");
    assert.equal(btn.type, "button");
    assert.equal(btn.props.type, "button");
    assert.equal(textOf(btn.props.children).trim(), "Use these settings for every shot");
    assert.match(btn.props.title, /engine/);
    assert.match(btn.props.title, /channel/);
    assert.match(btn.props.title, /audio/);
    assert.match(btn.props.title, /prompt helper/);
    // Placement: in the ENGINE slab, right after .mgd-engmeta.
    const [slab] = loom.find((el) => el.type === "div" && el.props.className === "mgd-slab"
      && React.Children.toArray(el.props.children).some((c) => isElement(c) && c.props.className === "mgd-enggrid"));
    const kids = React.Children.toArray(slab.props.children).filter(isElement);
    const meta = kids.findIndex((c) => c.props.className === "mgd-engmeta");
    assert.ok(meta >= 0 && kids[meta + 1] && kids[meta + 1].props.className === "mgd-applyall", "directly under the engine meta row");

    for (const props of [{}, { loomCtx: false }, { dock: { topEl: null, promptEl: null, negativeEl: null, goEl: null, expanded: true } }]) {
      const g = mountDrawer(t, props);
      assert.equal(g.find(g.applyAll).length, 0, "the gallery's drawer has no shots to copy to: " + JSON.stringify(Object.keys(props)));
    }
  });

  test("its click asks the host with the five settings as the form holds them, and changes nothing", (t) => {
    const d = mountDrawer(t, { loomCtx: true });
    d.api.prefill({ mode: "i2v", video_model: "tbkv1.0.1", duration: 10, is_private: true, audio: true, audio_language: "japanese", prompt_helper: true, images: [ref(8)] });
    const before = JSON.stringify(d.api.payload());
    d.click(d.applyAll);
    assert.deepEqual(d.commits(), [{ name: "mg-apply-all-request",
      detail: { model: "tbkv1.0.1", isPrivate: true, audioGen: true, audioLanguage: "japanese", videoHelper: true } }]);
    assert.equal(JSON.stringify(d.api.payload()), before, "the request changed the form");
  });

  test("styled on the Loom panel's small text action (.lv-unbind), right-aligned", () => {
    const rule = (sel) => { const m = CSS.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\{([^}]*)\\}")); return m ? m[1] : ""; };
    const base = rule(".gen-drawer .mgd-applyall");
    assert.match(base, /font:700 10\.5px\/1 system-ui/);
    assert.match(base, /background:none/);
    assert.match(base, /border:0/);
    assert.match(base, /color:var\(--subtext/);
    assert.match(base, /align-self:flex-end/, "right-aligned on its own line in the slab's column");
    assert.match(rule(".gen-drawer .mgd-applyall:hover"), /color:var\(--accent/);
  });
});

describe("each new event has exactly one emit, inside its own handler", () => {
  const emitsOf = (name) => [...CODE.matchAll(new RegExp("emit\\(\"" + name + "\"", "g"))].length;
  test("one emit apiece, none in the prefill / gating / setRefs road", () => {
    for (const name of ["mg-model-commit", "mg-channel-commit", "mg-helper-commit", "mg-apply-all-request"]) {
      assert.equal(emitsOf(name), 1, name + " must be emitted from exactly one place");
    }
    assert.match(CODE, /const pickVideoModel = \(v\) => \{ st\.current\.model = v; applyModelGating\(true\); reprice\(\); emit\("mg-model-commit", \{ model: v, duration: st\.current\.duration \}\); \};/);
    assert.match(CODE, /className=\{"mgd-channel"[^\n]*onClick=\{\(\) => \{ if \(st\.current\.channel === v\) return; st\.current\.channel = v; rerender\(\); reprice\(\); emit\("mg-channel-commit", \{ isPrivate: v === "enhanced" \}\); \}\}/);
    assert.match(CODE, /className="mgd-helper"[^\n]*\n[^\n]*onChange=\{\(e\) => \{ st\.current\.videoHelper = e\.target\.checked; rerender\(\); reprice\(\); emit\("mg-helper-commit", \{ videoHelper: e\.target\.checked \}\); \}\}/);
    assert.match(CODE, /const requestApplyAll = \(\) => \{[^}]*emit\("mg-apply-all-request"/);
    assert.match(CODE, /className="mgd-applyall" onClick=\{requestApplyAll\}/);
    // The roads a host drives: none of them may emit at all.
    for (const fn of ["prefill", "setRefs", "applyModelGating", "setMode"]) {
      const start = CODE.indexOf("const " + fn + " = (");
      assert.ok(start >= 0, "expected " + fn + " in VideoDrawer.jsx");
      const body = CODE.slice(start, CODE.indexOf("\n  };", start));
      assert.ok(!/emit\(/.test(body), fn + " emits an event -- a host prefill would loop on it");
    }
  });

  test("the header's event count matches the events the drawer emits", () => {
    const names = new Set([...CODE.matchAll(/emit\("(mg-[a-z-]+)"/g)].map((m) => m[1]));
    assert.match(SRC, new RegExp("The " + names.size + " events stay BUBBLING"));
    assert.match(SRC, /all fifteen DOM events/);
    assert.equal(names.size, 15);
    for (const n of names) assert.ok(SRC.slice(0, SRC.indexOf("let lineSeq")).includes(n), "the header lists " + n);
  });
});

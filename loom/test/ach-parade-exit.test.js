// gallery/src/notify/ach.js -- THE EXIT from the achievement flood parade.
//
// Owner ruling 2026-09-04 (moonglade-internal/DECISIONS.md, "The achievement parade gets an
// exit"): when a wave of achievements plays one after another, the person can end it early --
// Escape, or a skip control. Presentation only; every achievement is recorded as earned
// whether or not its moment played.
//
// Two things make this worth real behavioural tests rather than the source-text assertions
// most of ach.js gets (mg-notify-roast-gate.test.js):
//
//   1. The parade's pending queue used to live inside _floodParade's closure, where NOTHING
//      outside could stop it. An exit that only cleared the trail would leave the flood
//      stepping on behind it -- exactly the two-layers-at-once bug the replay takeover was
//      written to kill in the first place. So "the queue is actually emptied" has to be
//      observed, not grepped.
//   2. Escape is shared. Every other Escape handler in the app (App.jsx's overlay closer,
//      useCommandPalette's one global listener, the drawer/picker/panel ladders) registers
//      from a React effect, so ach.js's module-load capture listener runs FIRST and must
//      consume the key ONLY while a parade is up. A regression here is silent: Escape would
//      quietly stop closing overlays, and nothing would fail.
//
// ach.js is imperative DOM, so this file stands a small fake document/window up before
// importing it -- the same "stand in for the element" move badge-anim-chain.test.js makes for
// <img>, one size larger. The module is then driven through its REAL entry points, check()
// and replay(), with fetch stubbed: nothing test-only is exported from the engine.
import { test, describe, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ACH = path.join(__dirname, "../../gallery/src/notify/ach.js");

// ---- the fake DOM ---------------------------------------------------------------------
// Everything ach.js touches on an element and nothing else. querySelector never returns
// null (the engine reads .cap/.toast/.r off freshly built markup); nothing here asserts on
// what comes back from it, only on what is attached to document.body.
function el(tag) {
  const e = {
    tagName: String(tag || "div").toUpperCase(),
    children: [], parentNode: null, _ls: {}, _cls: new Set(),
    style: { setProperty() {} },
    textContent: "", innerHTML: "",
    appendChild(c) { c.parentNode = e; e.children.push(c); return c; },
    insertBefore(c) { c.parentNode = e; e.children.unshift(c); return c; },
    replaceChild(n, o) { const i = e.children.indexOf(o); if (i >= 0) e.children[i] = n; n.parentNode = e; return o; },
    remove() {
      const p = e.parentNode;
      if (p) { const i = p.children.indexOf(e); if (i >= 0) p.children.splice(i, 1); }
      e.parentNode = null;
    },
    querySelector() { return el("div"); },
    setAttribute() {}, removeAttribute() {},
    addEventListener(t, fn) { (e._ls[t] = e._ls[t] || []).push(fn); },
    fire(t, ev) { (e._ls[t] || []).slice().forEach((fn) => fn(ev || { stopPropagation() {} })); },
    click() { e.fire("click"); },
  };
  // The engine writes .className on build and .classList afterwards; both have to land in
  // the same place or "is this element still an .ach-m2" answers wrongly.
  Object.defineProperty(e, "className", {
    get() { return [...e._cls].join(" "); },
    set(v) { e._cls = new Set(String(v).split(/\s+/).filter(Boolean)); },
  });
  e.classList = {
    add(...c) { c.forEach((x) => e._cls.add(x)); },
    remove(...c) { c.forEach((x) => e._cls.delete(x)); },
    contains(c) { return e._cls.has(c); },
    toggle(c, on) { if (on) e._cls.add(c); else e._cls.delete(c); },
  };
  return e;
}

const keyListeners = [];          // every keydown listener, in REGISTRATION order
let body, ach;

function sendEscape() {
  const seen = [];
  let stopped = false;
  const ev = {
    key: "Escape", defaults: 0, bubbles: 0,
    preventDefault() { ev.defaults++; },
    stopPropagation() { ev.bubbles++; },
    stopImmediatePropagation() { stopped = true; },
  };
  for (const l of keyListeners) {
    if (stopped) break;
    seen.push(l.tag);
    l.fn(ev);
  }
  return { ev, seen };
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const tick = () => wait(0);

// A flood is >3 newly-earned; the engine reads `newly` (ids) against `achievements`.
function flood(n) {
  const achievements = Array.from({ length: n }, (_, i) => ({
    id: "ach" + i, name: "Achievement " + i, tier: i === 0 ? "legendary" : "common",
    desc: "did a thing", roast: "did a thing, badly", points: 10,
  }));
  return { achievements, newly: achievements.map((a) => a.id), skins: [], skin: "moonglade" };
}
let nextPayload = flood(5);

const moments = () => body.children.filter((c) => c.classList.contains("ach-m2"));
const chips = () => body.children.filter((c) => c.classList.contains("ach-trailchip"));
const skipChip = () => body.children.filter((c) => c.classList.contains("ach-skipchip"))[0] || null;

before(async () => {
  body = el("body");
  globalThis.document = { body, documentElement: el("html"), createElement: (t) => el(t) };
  globalThis.window = {
    addEventListener(t, fn, capture) { if (t === "keydown") keyListeners.push({ fn, capture, tag: "ach" }); },
    removeEventListener() {},
  };
  // No Audio, no AudioContext, no localStorage on purpose: _chime/_synth/unleashed() all
  // fail soft, which is the same path a locked-down browser takes.
  globalThis.fetch = async () => ({ ok: true, status: 200, statusText: "OK", json: async () => nextPayload });

  // Dynamic, not a static import: the fake globals above have to be standing before the
  // module evaluates, because it registers its Escape listener at module load.
  ach = await import("../../gallery/src/notify/ach.js");

  // The app's OWN Escape handlers all mount after installNotify() runs, so they register
  // after ach.js does. This stands in for every one of them.
  globalThis.window.addEventListener("keydown", () => {}, true);
  keyListeners[keyListeners.length - 1].tag = "app";
});

afterEach(async () => {
  sendEscape();                   // leave no parade running for the next test
  await wait(600);                // the 500ms fade-out removals settle
  body.children.length = 0;
});

// Walks a fresh flood up to the point where the parade is unmistakably a parade: two moments
// shown, the counter chip up, three still queued.
async function paradeInFlight() {
  nextPayload = flood(5);
  ach.check();
  await tick();
  assert.equal(moments().length, 1, "the first moment should be on screen after check()");
  moments()[0].fire("click");     // click = next, the shipped advance gesture
  assert.equal(moments().length, 2, "clicking should have advanced to the second moment");
}

describe("the flood parade can be ended early", () => {
  test("Escape mid-parade skips the rest and runs the one teardown", async () => {
    await paradeInFlight();
    assert.equal(chips().length, 2, "counter + skip chip are both up from the second moment on");
    assert.match(skipChip().textContent, /^skip ×3 · Esc$/,
      "the skip chip counts what skipping COSTS -- the three moments still queued");

    const { ev, seen } = sendEscape();

    // Every layer on screen is fading, not gone: .out is the same class, on the same 500ms,
    // as the click-dismiss that has always shipped.
    assert.ok(moments().length > 0, "the moments must still be in the DOM, fading");
    moments().forEach((m) => assert.ok(m.classList.contains("out"),
      "a moment ripped out mid-frame instead of fading is the exact thing the ruling rules out"));
    chips().forEach((c) => assert.ok(c.classList.contains("out"), "the chips fade with the layer"));

    await wait(600);
    assert.equal(moments().length, 0, "the parade layer is gone after its fade");
    assert.equal(chips().length, 0, "both chips left with it");

    // The real proof the QUEUE was skipped, not just the screen cleared: nothing new
    // arrives when the dwell that would have advanced the parade comes and goes.
    await wait(2600);
    assert.equal(moments().length, 0,
      "a moment appearing after the exit means the step loop survived it -- the pending " +
      "queue lived in _floodParade's closure and nothing outside could reach it");
    assert.equal(seen.join(","), "ach", "the parade consumed Escape; nothing downstream saw it");
    assert.equal(ev.defaults, 1, "and it claimed the key");
  });

  test("the skip chip is the same exit, for mouse and touch", async () => {
    await paradeInFlight();
    const skip = skipChip();
    assert.ok(skip, "there must be a visible affordance -- keyboard-only is not the ruling");
    assert.equal(skip.tagName, "BUTTON", "a real button, so touch and assistive tech get the exit too");

    skip.fire("click", { stopPropagation() {} });

    moments().forEach((m) => assert.ok(m.classList.contains("out"), "same fade as Escape"));
    await wait(600);
    assert.equal(moments().length, 0, "same teardown as Escape");
    assert.equal(chips().length, 0);
    await wait(2600);
    assert.equal(moments().length, 0, "the chip skips the queue, not just the screen");
  });

  test("a replay still works after a parade was skipped", async () => {
    await paradeInFlight();
    sendEscape();
    await wait(600);

    // The Folio's click-an-earned-card path. It takes over rather than joining, and a
    // skipped parade must leave nothing behind for that takeover to trip over.
    const h = ach.replay({ id: "ach0", name: "Achievement 0", tier: "rare" }, {});
    assert.equal(typeof h.setText, "function", "replay must hand back its driver handle");
    assert.equal(moments().length, 1, "the replayed moment is on screen, alone");
    assert.equal(chips().length, 0, "and carries none of the skipped parade's chips");
  });

  test("Escape with no parade up leaves the app's Escape ladder alone", async () => {
    assert.equal(moments().length, 0, "nothing on screen");
    const { ev, seen } = sendEscape();
    assert.deepEqual(seen, ["ach", "app"],
      "with no parade up the key must reach the app's own handlers -- swallowing it here " +
      "would silently stop Escape closing overlays, and no test would fail for it");
    assert.equal(ev.defaults, 0, "and the event is untouched");
    assert.equal(ev.bubbles, 0);
  });

  test("a replay's Escape belongs to the Folio, not to this module", async () => {
    const h = ach.replay({ id: "ach0", name: "Achievement 0", tier: "rare" }, {});
    assert.equal(moments().length, 1);
    const { seen } = sendEscape();
    assert.deepEqual(seen, ["ach", "app"],
      "a replay is a single moment, not a parade: Escape closes the Folio, which dismisses " +
      "the moment through useFolio's unmount cleanup (useFolio.js's belt-and-suspenders)");
    h.dismiss();
    await wait(600);
  });

  test("the listener is registered in CAPTURE, which is what puts it ahead of the app's", () => {
    const ours = keyListeners.filter((l) => l.tag === "ach");
    assert.equal(ours.length, 1, "one listener, registered once at module load");
    assert.equal(ours[0].capture, true,
      "bubble phase would let App.jsx's capture-phase overlay closer fire first, and Escape " +
      "would close the overlay UNDER the parade instead of ending the parade");
  });
});

describe("there is exactly one teardown path", () => {
  const src = readFileSync(ACH, "utf8");

  test("only _clearParade empties the trail", () => {
    const n = (src.match(/_trail\.splice\(/g) || []).length;
    assert.equal(n, 1,
      "found " + n + " places emptying _trail. A second teardown is how the replay/parade " +
      "overlap bug worked: two paths removing the same DOM, whichever finished first winning. " +
      "The exit reuses _clearParade for exactly that reason.");
  });

  test("the exit and the replay takeover call the same teardown", () => {
    assert.match(src, /function _endParade\(\)[\s\S]*?_clearParade\(\);\r?\n\}/,
      "_endParade must finish through _clearParade, not its own removal loop");
    const replayBody = src.match(/export function replay\(a, opts\) \{[\s\S]*$/)[0];
    assert.match(replayBody, /_endParade\(\);/,
      "replay's takeover must route through the exit, so a parade still IN FLIGHT is stopped " +
      "and not merely cleared of its trail");
    assert.doesNotMatch(replayBody, /_clearParade\(\);/,
      "and it must not also call the teardown directly -- one call, one path");
  });
});

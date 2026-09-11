// The Konami starfall, pinned to its committed Design Handoff page, plus the sequence rule
// that keeps a bespoke celebration and the standard achievement toast off each other.
//
// The spec is moonglade-internal/design/handoff-2026-09-04/briefs/nel-starfall-easter-egg.html
// -- a PRIVATE page, so this file cannot read it and cannot quote its copy. What it can do is
// pin the facts the rebuild was measured against, in the two public files that implement them
// (gallery/src/App.jsx's Konami handler, gallery/src/styles.css's .ee-* block), so a later
// edit that quietly drifts back toward the pre-2026-09-10 port fails here instead of being
// noticed months later on a live cast.
//
// Why these particular facts and not a screenshot diff: every one of them was WRONG in the
// first port and looked fine -- 46 stars instead of 40, no orb at all, the toast centred
// instead of bottom-anchored, Nel drifting through a 6s keyframe instead of popping in .65s,
// and a stacking order that only worked because appendChild happened to run in the same order
// as the z-index numbers. None of that throws; it just isn't the design.
//
// Structure/text assertions in the style of submit-road-structure.test.js and the source half
// of ach-parade-exit.test.js, plus one BEHAVIOURAL section: the hold/release contract is the
// thing the owner ruling actually turns on ("a first-earn overlap must be impossible by
// construction"), and grepping for a function call cannot show that a celebration really does
// not reach the screen. That half drives the real engine through its real entry points, the
// same fake-DOM move ach-parade-exit.test.js makes.
import { test, describe, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const read = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const app = read(path.join(SRC, "App.jsx"));
const css = read(path.join(SRC, "styles.css"));
const achSrc = read(path.join(SRC, "notify/ach.js"));

// The handler, isolated: everything between the effect that owns the key sequence and the
// listener teardown. Assertions below must not be able to pass on some unrelated part of a
// 6000-line component.
const konami = (() => {
  const i = app.indexOf("const seq = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];");
  assert.ok(i > 0, "the Konami sequence is gone from App.jsx -- this whole file is about it");
  const j = app.indexOf('document.addEventListener("keydown", onKey);', i);
  assert.ok(j > i, "the handler no longer ends by registering its keydown listener");
  return app.slice(i, j);
})();

// The .ee-* block, split at the reduced-motion rule: the media query repeats the same class
// names, so a z-index read that wandered into it would answer about the wrong declaration.
const eeStart = css.indexOf(".ee-layer{");
assert.ok(eeStart > 0, "styles.css has no .ee-layer -- the cast has no stage to fade");
const rmStart = css.indexOf("@media (prefers-reduced-motion: reduce)", eeStart);
assert.ok(rmStart > eeStart, "the .ee-* block has no reduced-motion rule after it");
const eeRules = css.slice(eeStart, rmStart);
const rmBlock = css.slice(rmStart, css.indexOf("\n}", rmStart) + 2);

/** The declaration body of `.<cls>{...}` -- the element's OWN rule, not a grouped selector. */
function rule(cls) {
  const m = eeRules.match(new RegExp("\\." + cls + "\\s*\\{([^}]*)\\}"));
  assert.ok(m, "styles.css has no ." + cls + " rule");
  return m[1];
}
function zIndex(cls) {
  const m = rule(cls).match(/z-index\s*:\s*(-?\d+)/);
  assert.ok(m, "." + cls + " declares no z-index -- the ladder must be explicit");
  return Number(m[1]);
}

describe("the cast is built the way the handoff page builds it", () => {
  test("an orb glow is created, and it is the element the page pulses", () => {
    assert.match(konami, /className\s*=\s*"ee-orb"/,
      "no orb element -- the handoff's .orbglow is the cast's light source and the first " +
      "port simply did not have one");
    const orb = rule("ee-orb");
    assert.match(orb, /width\s*:\s*340px/, "the page's orb is a 340px circle");
    assert.match(orb, /height\s*:\s*340px/);
    assert.match(orb, /margin\s*:\s*-170px/, "centred on its point the way the page centres it");
    assert.match(orb, /filter\s*:\s*blur\(8px\)/, "the page's blur, not a sharp disc");
    assert.match(orb, /--lavender/, "lavender core");
    assert.match(orb, /--emerald/, "emerald at the 45% stop");
    assert.match(orb, /45%/);
    assert.match(orb, /transparent 68%/);
    assert.match(orb, /animation\s*:\s*ee-orb 2\.6s ease-in-out \.3s infinite/,
      "the page's orbP cadence: 2.6s, eased, .3s in, forever");
    assert.match(css, /@keyframes ee-orb\{0%,100%\{opacity:\.35;transform:scale\(\.92\);\}50%\{opacity:\.9;transform:scale\(1\.1\);\}\}/,
      "and the page's orbP keyframes verbatim");
  });

  test("forty stars, at the page's size, duration and delay ranges", () => {
    assert.match(konami, /for \(let i = 0; i < 40; i\+\+\)/,
      "the page casts 40 stars; the first port cast 46");
    assert.match(konami, /fontSize = 13 \+ Math\.random\(\) \* 24/);
    assert.match(konami, /animationDuration = 2\.2 \+ Math\.random\(\) \* 2\.4/,
      "the page's fall is 2.2 + rand*2.4s; the first port used 2.6 and nobody could see it");
    assert.match(konami, /animationDelay = Math\.random\(\) \* 1\.6/,
      "and its delay is rand*1.6s, not 1.8");
    assert.match(konami, /\["✦", "✧", "★", "✪", "✺"\]/, "the page's five glyphs");
  });

  test("the stacking ladder is z-index VALUES: scrim < orb < Nel < stars < toast", () => {
    const ladder = ["ee-scrim", "ee-orb", "ee-nel", "ee-star", "ee-toast"].map(zIndex);
    ladder.forEach((z, i) => {
      if (i === 0) return;
      assert.ok(z > ladder[i - 1],
        "the ladder broke at position " + i + " (" + ladder.join(" < ") + "). The page's order " +
        "is scrim < orb < Nel < stars < toast -- the stars fall IN FRONT of Nel, which is the " +
        "whole picture. The first port got that by accident of append order and painted Nel " +
        "over the starfall the moment anyone moved an appendChild.");
    });
    // And the accident is actively ruled out: Nel is appended AFTER the stars, as the page
    // does it, so if append order were still deciding, the assertion above would be a lie.
    assert.ok(konami.indexOf('className = "ee-nel"') > konami.indexOf('className = "ee-star"'),
      "Nel must be appended after the stars (as the page's cast() does) -- that is what makes " +
      "the z-index ladder load-bearing rather than decorative");
    assert.ok(zIndex("ee-layer") < 520,
      "the whole layer must sit UNDER the achievement moment's .ach-m2 (z-index 520)");
  });

  test("the toast is bottom-anchored glass, entering on its own short animation", () => {
    const t = rule("ee-toast");
    assert.match(t, /bottom\s*:\s*20px/, "the page anchors the toast to the bottom, not mid-screen");
    assert.doesNotMatch(t, /\btop\s*:/, "a leftover top: is the centred first port coming back");
    assert.match(t, /backdrop-filter\s*:\s*blur\(/, "glass, not an opaque slab");
    assert.match(t, /background\s*:\s*rgba\(10,\s*8,\s*24,\s*\.82\)/, "at the page's alpha");
    assert.match(t, /border-radius\s*:\s*14px/);
    assert.match(t, /padding\s*:\s*14px 26px/);
    assert.match(t, /box-shadow\s*:\s*0 0 60px rgba\(182,146,230,\.5\)/);
    assert.match(t, /animation\s*:\s*ee-toastin \.5s ease \.35s forwards/,
      "an ENTRANCE, not a 6s hold-and-fade keyframe: the hold belongs to the JS timeline");
  });

  test("Nel pops in and then rests -- she does not fade herself out", () => {
    const n = rule("ee-nel");
    assert.match(n, /animation\s*:\s*ee-nel \.65s cubic-bezier\(\.18,\.9,\.2,1\.08\) forwards/,
      "the page's nelpop: .65s on its own curve, not a 6s drift");
    const kf = css.match(/@keyframes ee-nel\{([\s\S]*?)\}\}/);
    assert.ok(kf, "no ee-nel keyframes");
    const frames = kf[1] + "}";
    assert.match(frames, /0%\{opacity:0;transform:translateX\(-50%\) translateY\(26px\) scale\(\.86\);\}/);
    assert.match(frames, /60%\{opacity:1;transform:translateX\(-50%\) translateY\(0\) scale\(1\.02\);\}/);
    assert.match(frames, /100%\{opacity:1;transform:translateX\(-50%\) translateY\(0\) scale\(1\);\}/);
    assert.doesNotMatch(frames, /100%\{opacity:0/,
      "closing at opacity 0 is the first port's self-fade: the whole layer leaves together now");
  });

  test("hold 6000ms, then ONE .6s fade of the whole layer, then removal", () => {
    assert.match(konami, /}, 6000\);/, "the page holds for 6000ms");
    assert.match(konami, /classList\.add\("ee-out"\)/,
      "the fade is a class on the LAYER -- fading each element by inline opacity cannot work, " +
      "a filling CSS animation outranks an inline style and the stars and Nel would stay lit");
    assert.match(konami, /setTimeout\(teardown, 600\)/, "and removal lands after the .6s fade");
    assert.match(rule("ee-layer.ee-out") + rule("ee-layer"), /transition\s*:\s*opacity \.6s/,
      "the .6s belongs to the layer's own transition, matched by the timer above");
    assert.doesNotMatch(konami, /}, 7000\);/,
      "the 7000ms single-timeout timeline is the first port's; the rebuild is 6000 + 600");
  });

  test("reduced motion stills the whole layer", () => {
    ["ee-scrim", "ee-orb", "ee-nel", "ee-star", "ee-toast"].forEach((cls) => {
      assert.ok(rmBlock.includes("." + cls),
        "." + cls + " is not covered by the reduced-motion rule -- the page's own rule covers " +
        "every animated part of the cast, the orb included");
    });
    assert.match(rmBlock, /animation\s*:\s*none\s*!important/);
    assert.match(rmBlock, /opacity\s*:\s*1\s*!important/, "everything sits at its rest opacity");
  });

  test("the things that were NOT up for redesign are untouched", () => {
    assert.match(konami, /ee_starfall_cast\.ogg/, "audio unchanged: the two real tracks stay");
    assert.match(konami, /ee_starfall_loop\.ogg/);
    assert.match(konami, /"✺ Elune-adore, Nelnamara ✺"/, "the fixed greeting is a literal");
    assert.match(konami, /sub\.textContent = \(feat && feat\.desc\)/,
      "the punchline still comes from the SEALED roster via textContent -- it is not in this " +
      "public tree, and this wave does not change it");
    assert.doesNotMatch(konami, /\.innerHTML\s*=/,
      "DOM methods only: fetched roster text must never reach an HTML parser");
    assert.match(konami, /nel\.onerror = \(\) => nel\.remove\(\)/, "the missing-art fail-soft");
    assert.match(konami, /if \(busy\) return;/, "the re-trigger guard");
  });
});

describe("the bespoke-moment sequence rule, in source", () => {
  test("the set is exactly the two feats with a celebration of their own", () => {
    const m = achSrc.match(/export const BESPOKE_FEATS = new Set\(\[([^\]]*)\]\)/);
    assert.ok(m, "ach.js must expose the bespoke set -- both hosts load this file and both " +
      "have to agree on which feats bring their own moment");
    const ids = m[1].split(",").map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
    assert.deepEqual(ids.sort(), ["the-konami-code", "under-the-hood"]);
  });

  test("the fanfare has exactly one gate, not three call sites to keep in step", () => {
    const calls = (achSrc.match(/_fanfare\(/g) || []).length;
    assert.equal(calls, 2,
      "found " + calls + " mentions of _fanfare (expected its definition plus ONE call, " +
      "inside _flair). The parade step, the queue and the Folio replay all fire the flair; " +
      "guarding them one by one is how a feat earned in a >3 flood still gets confetti over " +
      "a celebration that was supposed to replace it.");
    assert.match(achSrc, /function _flair\(built, a\) \{\s*\n\s*if \(BESPOKE_FEATS\.has\(a\.id\)\) return;/,
      "and the gate must be the first thing _flair does");
    ["_floodParade", "_next", "replay"].forEach((fn) => {
      const from = achSrc.indexOf("function " + fn + "(");
      assert.ok(from > 0, "ach.js no longer has a " + fn);
      const tail = achSrc.slice(from + 1);
      const end = tail.search(/\n(?:export )?function /);
      const body = achSrc.slice(from, end < 0 ? achSrc.length : from + 1 + end);
      assert.match(body, /_flair\(built, a\);/, fn + " must raise its flair through _flair");
    });
  });

  test("the Konami handler arms the moment before the beacon and releases it at the end", () => {
    assert.ok(konami.indexOf("beginBespokeMoment()") < konami.indexOf('sendAchEvent("konami")'),
      "the beacon is what EARNS the feat, so a check() -- the cast's own, or one a finishing " +
      "generation fires -- can land while this chain is still in the air; arming after the DOM " +
      "is built leaves that gap open");
    assert.match(konami, /endBespokeMoment\(\)/, "and it must release");
    assert.match(konami, /const release = \(\) => \{\s*\n\s*if \(released\) return;/,
      "release must be idempotent: four paths reach it and a double release would unbalance " +
      "the depth count, un-holding a moment that is still on screen");
    // Teardown is reachable from the timer and from a failed beacon, but it does not EXIST
    // until the beacon has landed and the DOM is built. Unmounting inside the arm-to-beacon
    // window therefore has to reach the release directly, or _bespoke never returns to 0 and
    // every later achievement is held forever with nothing left to release it. apiGet makes a
    // bare fetch with no timeout and no AbortController (gallery/src/api.js), so a request that
    // never settles never rejects either: the .catch below cannot stand in for this path.
    assert.match(konami, /\.catch\(\(\) => \{ if \(teardown\) teardown\(\); else release\(\); \}\)/,
      "a beacon or roster read that rejects must still release");
    assert.ok(konami.indexOf("pendingRelease = release;") < konami.indexOf('sendAchEvent("konami")'),
      "the release must be published to the effect's scope BEFORE the beacon goes out -- that " +
      "is the whole window this assertion exists for");
    assert.match(app, /let pendingRelease = null;/,
      "and it must live beside teardown in the effect scope, not inside onKey's closure where " +
      "the cleanup cannot see it");
    const cl = app.indexOf('document.removeEventListener("keydown", onKey);');
    const cleanup = app.slice(cl, cl + 300);
    assert.match(cleanup, /if \(teardown\) teardown\(\);/,
      "unmounting with the layer up must take it down (teardown releases)");
    assert.match(cleanup, /else if \(pendingRelease\) pendingRelease\(\);/,
      "and unmounting BEFORE the layer exists must still release: without this branch an " +
      "unmount (or a fetch that never settles) in the arm-to-beacon window wedges the engine " +
      "above zero forever and silently swallows every later achievement");
  });

  test("the cast fires the marking check() itself, from inside the moment", () => {
    // Without this the hold is inert for the very feat it was built for. Nothing in the app
    // polls achievements: check() runs once per boot (notify/index.jsx) and after a generation,
    // so the standard toast for a freshly cast egg would otherwise wait for the next page load
    // and the ruled "starfall, then the toast" sequence would exist only in the test below.
    assert.match(app, /import \{[^}]*check as achCheck[^}]*\} from "\.\/notify\/ach\.js"/,
      "App.jsx must import ach.js's check() -- window.Ach is a compat surface, not the contract");
    assert.match(konami, /\n\s*achCheck\(\);/, "and the cast must call it");
    const marked = konami.indexOf("achCheck();");
    assert.ok(marked > konami.indexOf("document.body.appendChild(layer);"),
      "it fires once the layer is UP: the celebration it builds is parked by the moment, and " +
      "arriving before the moment is on screen is the overlap the ruling forbids");
    assert.ok(marked < konami.indexOf("}, 6000);"),
      "and well inside the hold, so the held celebration is drained by this cast's release");
    assert.match(konami, /apiGet\("\/api\/achievements"\)/,
      "the desc read stays UNMARKED -- it only wants the now-unmasked flavor; marking is " +
      "check()'s job and doing it twice would consume `newly` before the toast is built");
  });
});

// ---- behaviour: the hold is real ---------------------------------------------------------
// ach.js is imperative DOM, so the fake document/window below stands in for a browser, exactly
// as ach-parade-exit.test.js does. The engine is then driven through its real entry points.
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

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const tick = () => wait(0);
let body, ach, nextPayload;
const keyListeners = [];

/* The engine's own exit, used as this file's teardown: a moment left on screen keeps
   _playing true and the NEXT test's celebration would silently never build -- which looks
   exactly like the hold failing, and would have this file lying about the thing it exists
   to prove. Escape ends a parade; a click dismisses a single moment. */
function sendEscape() {
  const ev = {
    key: "Escape",
    preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {},
  };
  keyListeners.forEach((fn) => fn(ev));
}

function payload(list) {
  return { achievements: list, newly: list.map((a) => a.id), skins: [], skin: "moonglade" };
}
const moments = () => body.children.filter((c) => c.classList.contains("ach-m2"));
const starsIn = (m) => m.children.filter((c) => c.classList.contains("ee-star")).length;
const confIn = (m) => m.children.filter((c) => c.classList.contains("m2-conf")).length;

before(async () => {
  body = el("body");
  globalThis.document = { body, documentElement: el("html"), createElement: (t) => el(t) };
  globalThis.window = {
    addEventListener(t, fn) { if (t === "keydown") keyListeners.push(fn); },
    removeEventListener() {},
  };
  globalThis.fetch = async () => ({ ok: true, status: 200, statusText: "OK", json: async () => nextPayload });
  ach = await import("../../gallery/src/notify/ach.js");
});

afterEach(async () => {
  for (let i = 0; i < 4; i++) ach.endBespokeMoment();   // depth back to rest, whatever happened
  await tick();
  sendEscape();                                        // ends a parade, if one is running
  await wait(600);
  moments().forEach((m) => m.click());                 // dismisses a single moment
  await wait(700);                                     // .out fade + the queue draining
  body.children.length = 0;
});

describe("a bespoke moment owns the screen while it plays", () => {
  test("a newly-earned celebration is HELD, then plays when the moment ends", async () => {
    nextPayload = payload([{ id: "the-konami-code", name: "A Feat", tier: "feat", desc: "x", points: 10 }]);
    ach.beginBespokeMoment();          // the starfall is on screen
    ach.check();
    await tick();
    assert.equal(moments().length, 0,
      "the standard toast must not be BUILT while the bespoke moment is up. This is the " +
      "construction the ruling asks for: .ach-m2 (z-index 520) would otherwise paint straight " +
      "over the starfall layer on a first earn, and no amount of timer tuning makes that safe.");

    ach.endBespokeMoment();            // the cast has faded and been removed
    await tick();
    assert.equal(moments().length, 1, "and the held celebration plays after it, not instead of it");
  });

  test("a flood is held the same way -- the parade is not a second door", async () => {
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "a" + i, name: "A" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.beginBespokeMoment();
    ach.check();
    await tick();
    assert.equal(moments().length, 0, ">3 earns route to _floodParade instead of celebrate(); " +
      "holding only one of the two leaves the other wide open");
    ach.endBespokeMoment();
    await tick();
    assert.equal(moments().length, 1, "the parade starts once the screen is free");
  });

  test("overlapping moments compose -- the release belongs to the last one out", async () => {
    nextPayload = payload([{ id: "solo", name: "Solo", tier: "rare", desc: "x" }]);
    ach.beginBespokeMoment();
    ach.beginBespokeMoment();          // e.g. the starfall, then the reveal it hands off to
    ach.check();
    await tick();
    assert.equal(moments().length, 0);
    ach.endBespokeMoment();
    await tick();
    assert.equal(moments().length, 0, "one moment is still on screen -- a bool would have " +
      "released here and put the toast over it");
    ach.endBespokeMoment();
    await tick();
    assert.equal(moments().length, 1);
  });

  test("with no moment up nothing is held", async () => {
    nextPayload = payload([{ id: "plain", name: "Plain", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(moments().length, 1, "the ordinary path must be untouched by all of this");
  });
});

describe("a bespoke feat never gets the generic fanfare", () => {
  test("its own moment is the celebration", () => {
    const h = ach.replay({ id: "the-konami-code", name: "A Feat", tier: "feat", desc: "x" }, {});
    const m = moments()[0];
    assert.ok(m, "the moment itself still plays -- suppressed FANFARE, not a suppressed toast");
    assert.equal(starsIn(m), 0, "no star rain over a celebration that already had one");
    assert.equal(confIn(m), 0, "and no confetti");
    h.dismiss();
  });

  test("every other feat keeps it", () => {
    const h = ach.replay({ id: "some-other-feat", name: "Other", tier: "feat", desc: "x" }, {});
    const m = moments()[0];
    assert.ok(starsIn(m) > 0, "the ordinary feat fanfare must survive this change");
    assert.ok(confIn(m) > 0);
    h.dismiss();
  });
});

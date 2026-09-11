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
/** Every `selector { body }` pair inside a slab of CSS, as {selector, body}. Flat rules only,
    which is all the .ee-* block and its media query contain. */
function rules(slab) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(slab))) {
    const sel = m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (sel && !sel.startsWith("@")) out.push({ selector: sel, body: m[2] });
  }
  return out;
}
/** A comma-separated selector list, split and trimmed: ".a, .b.go" -> [".a", ".b.go"]. */
function selectors(sel) {
  return sel.split(",").map((s) => s.trim()).filter(Boolean);
}
function zIndex(cls) {
  const m = rule(cls).match(/z-index\s*:\s*(-?\d+)/);
  assert.ok(m, "." + cls + " declares no z-index -- the ladder must be explicit");
  return Number(m[1]);
}
/** The body of a top-level `function <name>(` in ach.js, up to the next top-level function. */
function achFn(name) {
  const from = achSrc.indexOf("function " + name + "(");
  assert.ok(from > 0, "ach.js no longer has a " + name);
  const tail = achSrc.slice(from + 1).search(/\n(?:export )?function /);
  return { from, to: tail < 0 ? achSrc.length : from + 1 + tail };
}
function achBody(name) {
  const r = achFn(name);
  return achSrc.slice(r.from, r.to);
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
    assert.match(orb, /--mauve[^;]*?75%/,
      "the page's core stop is rgba(196,166,240,.75) -- #c4a6f0, which is --mauve, not " +
      "--lavender. The block's header lists the rgba->token swap as the one adaptation here; " +
      "swapping the HUE as well is the kind of quiet drift that list exists to stop");
    assert.match(orb, /--emerald[^;]*?20%/, "emerald at the page's .2 alpha");
    assert.match(orb, /45%/);
    assert.match(orb, /transparent 68%/);
    // The orb tracks NEL, not the viewport. The page centres Nel at the stage's horizontal
    // middle and puts the orb's centre at 60% of the stage width -- +10% of the width to her
    // right -- and 40% down. Written against Nel's own left:50% so the offset stays +10% of
    // the viewport on any monitor; a bare 60vw is the same thing on a laptop and slides the
    // glow off her on an ultrawide.
    assert.match(orb, /left\s*:\s*calc\(50% \+ 10vw\)/,
      "the orb must be offset from Nel's own left:50%, not measured from the viewport edge");
    assert.match(orb, /top\s*:\s*40vh/, "and 40% down, as on the page");
    assert.match(rule("ee-nel"), /left\s*:\s*50%/,
      "...which only tracks her while Nel herself is centred -- if she moves, the calc above " +
      "is measuring from nothing");
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
    // Pinned by SELECTOR, not by "the name appears somewhere in the media query". A rule that
    // merely mentions .ee-star -- resetting its transform, say -- while the animation:none
    // declaration lists only three classes ships full motion to a user who asked for none, and
    // a substring check cannot tell the two apart. So: find the rule that actually stills, read
    // ITS selector list, and require every animated part of the cast to be in it.
    const stilling = rules(rmBlock).filter((r) => /animation\s*:\s*none\s*!important/.test(r.body));
    assert.ok(stilling.length, "no rule in the reduced-motion block stills an animation");
    const stilled = new Set(stilling.flatMap((r) => selectors(r.selector)));
    ["ee-scrim", "ee-orb", "ee-nel", "ee-star", "ee-toast"].forEach((cls) => {
      assert.ok(stilled.has("." + cls),
        "." + cls + " does not appear in the SELECTOR of a rule that sets animation:none " +
        "!important (stilled: " + [...stilled].join(", ") + "). The page's own rule covers " +
        "every animated part of the cast -- the orb and the stars included, and those two are " +
        "the whole motion of the effect.");
    });
    const rest = rules(rmBlock).filter((r) => /opacity\s*:\s*1\s*!important/.test(r.body));
    const lit = new Set(rest.flatMap((r) => selectors(r.selector)));
    ["ee-scrim", "ee-orb", "ee-nel", "ee-star", "ee-toast"].forEach((cls) => {
      assert.ok(lit.has("." + cls),
        "." + cls + " is not forced to its rest opacity -- its entrance animation starts at " +
        "opacity 0 and stilling it there would leave the element invisible rather than at rest");
    });
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
    assert.match(achSrc, /function _flair\(built, a, opts\) \{\s*\n\s*if \(_bespoke\) return;\s*[^\n]*\n\s*if \(BESPOKE_FEATS\.has\(a\.id\) && !\(opts && opts\.replay\)\) return;/,
      "the two gates must be the first thing _flair does, in this order: nothing layers over a " +
      "moment that is on screen, and an EARN of a bespoke feat is quiet because its own moment " +
      "is the fanfare");
    // One build point means one flair call: the definition, and the single raise inside the
    // dequeue. Anything else is a second place that has to remember the rule.
    assert.equal((achSrc.match(/[^\w]_flair\(/g) || []).length, 2,
      "expected exactly two mentions of _flair -- its definition and ONE call, inside _drain. " +
      "The parade step, the queue and the Folio replay all celebrate; guarding them one by " +
      "one is how a feat earned in a >3 flood still gets confetti over a celebration that " +
      "was supposed to replace it.");
    assert.match(achBody("_drain"), /_flair\(built, a, e\.replay \? \{ replay: true \} : undefined\)/,
      "and only the REPLAY entry may declare itself a replay. If an earn path ever passed " +
      "that flag it would hand a bespoke feat back the confetti its own moment replaces.");
  });

  test("one queue, one dequeue: _drain is the only place a moment is built", () => {
    // The invariant behind every hold assertion below. A second build point is a second door
    // onto the screen, and one gate cannot cover two doors -- which is exactly how the
    // round-2 mechanism ended up parking three separate continuations.
    const def = achSrc.indexOf("function _mkMoment(") + "function ".length;
    const d = achFn("_drain");
    const stray = [];
    const re = /_mkMoment\(/g;
    let m;
    while ((m = re.exec(achSrc))) {
      if (m.index === def) continue;                       // the definition itself
      if (m.index >= d.from && m.index < d.to) continue;   // the one dequeue
      stray.push(achSrc.slice(Math.max(0, m.index - 60), m.index + 12).split("\n").pop());
    }
    assert.deepEqual(stray, [],
      "a moment is built outside _drain: " + stray.join(" | ") + ". Every moment -- a queued " +
      "earn, a parade step, a Folio replay -- must come out of the one dequeue, because the " +
      "bespoke hold is a gate on that dequeue and nothing else.");
  });

  test("the parade ENQUEUES; it does not run a loop of its own", () => {
    // The shape that made the old parade a second door: it kept its own pending list in a
    // closure and stepped itself, so the hold had to be written twice (and the second copy
    // was the one nothing tested). It now pushes flood-tagged entries into the same _q.
    const body = achBody("_floodParade");
    assert.match(body, /_q\.push\(\{ a, flood: true \}\)/,
      "a flood's moments must be entries in the ONE queue");
    assert.match(body, /_drain\(\);/, "and it starts them by asking the one dequeue to run");
    assert.doesNotMatch(body, /_playFlood\(/,
      "_floodParade must not present a moment itself -- that is the dequeue's job, and it is " +
      "where the hold lives");
    assert.doesNotMatch(body, /const step = /,
      "no step loop of its own: start and step have to be the same code path, or the gate " +
      "that covers the start does not cover the step");
  });

  test("the hold is ONE gate on the dequeue, and the release just calls it", () => {
    const drain = achBody("_drain");
    assert.match(drain, /if \(_cur\) return;/,
      "refusal 1: a moment is already being presented. Its teardown re-enters; a dequeue that " +
      "runs anyway is the second .ach-m2 the ruling forbids");
    assert.match(drain, /if \(_bespoke && !\(head && head\.replay\)\) \{ _pendingDrain = true; return; \}/,
      "refusal 2, THE hold: record that the queue wants to run and build nothing. Written " +
      "once, here, and exempting only the replay entry");
    const rel = achSrc.slice(achSrc.indexOf("export function endBespokeMoment()"));
    assert.match(rel.slice(0, rel.indexOf("\n}")), /_drain\(\);/,
      "the release must call the dequeue");
    assert.equal((rel.slice(0, rel.indexOf("\n}")).match(/_drain\(/g) || []).length, 1,
      "...exactly once. Draining a list of parked callers in a loop is what let two moments " +
      "be built from one release");
    assert.doesNotMatch(achSrc, /_playing/,
      "the round-2 'a moment is playing' flag is gone for good: it had to be lowered while a " +
      "caller was parked, which is what made a release able to start a moment over one that " +
      "was still on screen. _cur -- the element itself -- is the serialization now");
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
    // until the beacon has landed and the DOM is built. Every other way out of the
    // arm-to-beacon window therefore has to reach the release directly, or _bespoke never
    // returns to 0 and every later achievement is held forever with nothing left to release it.
    assert.match(konami, /\.catch\(\(\) => \{ if \(teardown\) teardown\(\); else release\(\); \}\)/,
      "a throw anywhere in the chain -- and that includes the cast's own DOM building, which " +
      "runs inside this promise -- must still release");
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
      "and unmounting BEFORE the layer exists must still release");
  });

  test("a beacon that never answers cannot wedge the engine", () => {
    // The hole the cleanup branch above does NOT cover, and the one that actually bites: the
    // root App never unmounts, so its cleanup never runs. apiGet/apiPost make a bare fetch with
    // no AbortController unless a caller passes timeoutMs (gallery/src/api.js), and a network
    // failure RESOLVES with {error} rather than rejecting -- so a request that never settles
    // never reaches .then, never reaches .catch, and leaves _bespoke above zero for the rest of
    // the session with every later achievement silently swallowed. Only wall-clock time can end
    // that, so the arm carries a ceiling from the moment it is armed.
    const cap = konami.match(/const ARM_CEILING_MS = (\d+);/);
    assert.ok(cap, "the arm needs a wall-clock ceiling, named once");
    assert.ok(Number(cap[1]) > 0,
      "ARM_CEILING_MS is " + cap[1] + "ms. A zero ceiling fires in the same turn it is armed " +
      "and releases the arm before the beacon can answer, so every cast would build over an " +
      "engine that had already been let go -- the exact overlap the arm exists to prevent. " +
      "The value is a failsafe for a fetch that never settles, so it belongs far past any " +
      "answer a local server plausibly takes.");
    assert.match(konami, /armT = setTimeout\(\(\) => \{ if \(!teardown\) release\(\); \}, ARM_CEILING_MS\);/,
      "the ceiling must RELEASE, and must stand down once the cast's own timeline exists " +
      "(teardown) -- a live cast owns the screen for as long as it holds it");
    assert.ok(konami.indexOf("armT = setTimeout") < konami.indexOf('sendAchEvent("konami")'),
      "armed before the beacon goes out: a ceiling started after the answer is a ceiling on " +
      "nothing");
    assert.match(konami, /clearTimeout\(armT\)/,
      "and release must cancel it, or a later cast's arm is released by the previous one's timer");
    const built = konami.indexOf("document.body.appendChild(layer);");
    const answered = konami.indexOf(".then((data) => {");
    assert.ok(answered > 0 && built > answered,
      "the cast's DOM must be built INSIDE the beacon's .then, after the answer. The ee_* art " +
      "is served under the unlock this beacon records, so a layer built before the answer " +
      "lands 404s its own images on the very first cast -- and the `if (released) return` " +
      "below, which is the whole point of the assertion that follows, only guards code that " +
      "runs in there.");
    assert.match(konami.slice(answered, built), /if \(released\) return;/,
      "a chain that answers AFTER the ceiling expired must build nothing -- otherwise a hung " +
      "beacon that finally lands pops a starfall over whatever the page is doing minutes later, " +
      "and overwrites a newer cast's teardown on its way past");
  });

  test("the cast waits for a moment already on screen, and arms inside that wait", () => {
    // The reverse direction. Arming stops a celebration being BUILT over the cast, but it can
    // do nothing about one that is already painted -- .ach-m2 is z-index 520 and the cast's
    // layer is 449, so a cast entered mid-celebration would play underneath it. So the key
    // sequence does not cast: it hands the cast to ach.js's whenClear hook, which runs it now
    // if the layer is empty and otherwise the instant that moment tears down.
    assert.match(app, /import \{[^}]*whenClear[^}]*\} from "\.\/notify\/ach\.js"/,
      "App.jsx must import ach.js's whenClear -- the hold alone closes only one direction");
    assert.match(konami, /whenClear\(startCast\);/,
      "the keydown handler must hand the cast to whenClear rather than running it");
    assert.doesNotMatch(konami, /\n\s*startCast\(\);/,
      "and it must not also call startCast() directly -- a second entry point would paint " +
      "the starfall under whatever is on screen, which is the case this hook exists for");
    const armed = konami.indexOf("beginBespokeMoment()");
    const castFn = konami.indexOf("const startCast = ");
    const handoff = konami.indexOf("whenClear(startCast);");
    assert.ok(castFn > 0 && handoff > castFn,
      "startCast must be defined before the handler hands it over");
    assert.ok(armed > castFn && armed < handoff,
      "the arm has to happen INSIDE the callback. Arming on the keypress instead would hold " +
      "the celebration the cast is waiting for, and the cast would wait for a moment that " +
      "was itself waiting on the cast");
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
// A parade's spent moments stay in the DOM as the receded TRAIL; only the one front-and-centre
// is a moment being presented, so a parade assertion has to say which it means.
const front = () => moments().filter((c) => !c.classList.contains("trail"));
const starsIn = (m) => m.children.filter((c) => c.classList.contains("ee-star")).length;
const confIn = (m) => m.children.filter((c) => c.classList.contains("m2-conf")).length;

/* THE INVARIANT, watched rather than sampled. "At no instant two moments" cannot be checked by
   looking after the fact -- the overlap the round-2 mechanism allowed opened and closed inside
   one turn of the event loop. A moment can only appear by being appended to the body, so the
   count is taken at every append and the high-water mark is what the tests assert on. */
let peak = 0;
const peakReset = () => { peak = 0; };
function watchAppends(b) {
  const raw = b.appendChild;
  b.appendChild = (c) => {
    const r = raw(c);
    const n = front().length;
    if (n > peak) peak = n;
    return r;
  };
}

before(async () => {
  body = el("body");
  watchAppends(body);
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
  // Dismiss until the layer is genuinely empty: dismissing one moment lets the NEXT queued
  // one build, and leaving that one behind would strand the engine's _cur on an element this
  // teardown is about to drop -- which looks exactly like the hold failing in the next test.
  for (let i = 0; i < 10 && moments().length; i++) {
    moments().forEach((m) => m.click());
    await wait(700);                                   // .out fade + the queue draining
  }
  assert.equal(moments().length, 0, "the fake DOM was not emptied between tests");
  body.children.length = 0;
  peakReset();
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
      "a parade that started its own loop would walk straight onto the screen");
    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "the parade starts once the screen is free");
    assert.equal(peak, 1, "and one moment at a time, not the whole flood at once");
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

  test("a celebration already QUEUED when the moment arms is held too", async () => {
    // The shape the front-door hold alone does not catch, and the likely one: a generation
    // finishes, check() queues two earns, the first is on screen, and the owner casts the code
    // while it plays. The queue re-enters itself through _play's `after` -- never through
    // celebrate() -- so without a hold at that re-entry the SECOND moment builds .ach-m2
    // (z-index 520) straight over the starfall layer (449) the instant the first ends.
    nextPayload = payload([
      { id: "q1", name: "One", tier: "common", desc: "x" },
      { id: "q2", name: "Two", tier: "common", desc: "x" },
    ]);
    ach.check();
    await tick();
    assert.equal(moments().length, 1, "the first plays; the second is queued behind it");

    ach.beginBespokeMoment();                  // the cast lands mid-celebration
    moments()[0].click();                      // ...and the first moment ends normally
    await wait(600);
    assert.equal(moments().length, 0,
      "the queued celebration must NOT take the screen while the cast owns it");

    ach.endBespokeMoment();
    await tick();
    assert.equal(moments().length, 1, "and it plays once the cast has gone");
  });

  test("a parade already RUNNING is held at its next step", async () => {
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "p" + i, name: "P" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the parade is up and stepping");

    ach.beginBespokeMoment();
    peakReset();
    front()[0].click();                        // advance: this one recedes into the trail
    await tick();
    assert.equal(front().length, 0,
      "the parade's next moment comes out of the same dequeue as a queued celebration, so " +
      "the one gate must stop it: a parade that stepped itself would build over the cast");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "and the parade resumes where it stopped");
    assert.equal(peak, 1, "at no instant two moments being presented");
  });

  test("with no moment up nothing is held", async () => {
    nextPayload = payload([{ id: "plain", name: "Plain", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(moments().length, 1, "the ordinary path must be untouched by all of this");
  });

  test("held, then EXACTLY ONE, then the next after its hold", async () => {
    // The release drains a queue, not a list of parked callers. Round 2 parked a continuation
    // per entry point and replayed them all on release, so two celebrations could be built in
    // the same turn -- and the "playing" flag had been lowered while they waited, so nothing
    // stopped them. Deleting the gate in _drain fails the first assertion; deleting the
    // _drain() call in endBespokeMoment fails the second.
    nextPayload = payload([
      { id: "h1", name: "One", tier: "common", desc: "x" },
      { id: "h2", name: "Two", tier: "common", desc: "x" },
    ]);
    ach.beginBespokeMoment();
    ach.check();
    await tick();
    assert.equal(front().length, 0,
      "a celebration queued while the hold is armed must not be BUILT -- that is the whole " +
      "construction the ruling asks for");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1,
      "the release builds exactly one: the second is still an entry in the queue, not a " +
      "second parked caller waiting to be replayed alongside the first");
    assert.equal(peak, 1, "and at no instant were there two .ach-m2 moments on screen");

    front()[0].click();                        // the first ends normally
    await wait(600);
    assert.equal(front().length, 1, "the next arrives only once the first has left the DOM");
    assert.equal(peak, 1, "still one at a time across the handover");
  });

  test("a moment on screen when the hold arms: its natural end dequeues nothing", async () => {
    // The hole round 2's front-door hold could not see, and the one that bites: by the time
    // the cast lands the first celebration is already playing and the second is queued behind
    // it. The queue re-enters itself when the first ends, so the gate has to be there and not
    // at the point a celebration first arrives.
    nextPayload = payload([
      { id: "s1", name: "One", tier: "common", desc: "x" },
      { id: "s2", name: "Two", tier: "common", desc: "x" },
    ]);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the first plays; the second is queued behind it");

    ach.beginBespokeMoment();                  // the cast lands mid-celebration
    peakReset();
    front()[0].click();                        // ...and the first ends naturally
    await wait(600);
    assert.equal(front().length, 0,
      "the natural end must dequeue NOTHING while the gate is closed -- .ach-m2 is z-index " +
      "520 and would paint straight over the cast's 449");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "and the release builds it");
    assert.equal(peak, 1, "at no instant two .ach-m2 moments");
  });

  test("a REPLAY takes the layer over instead of opening a second one", async () => {
    // Not a hold case: a replay is a click and is deliberately exempt. But it must still be
    // the only moment on screen. Before this it cleared the parade only, so a replay clicked
    // while a QUEUED celebration was playing opened a second .ach-m2 beside it and whichever
    // ended first tore down the other's DOM.
    nextPayload = payload([{ id: "r1", name: "One", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(front().length, 1);
    peakReset();
    const h = ach.replay({ id: "r2", name: "Replayed", tier: "rare", desc: "x" }, {});
    assert.equal(front().length, 1, "one moment, not two");
    assert.equal(peak, 1, "and never two, not even for the length of one turn");
    h.dismiss();
  });
});

describe("whenClear: a cast never paints under a moment already on screen", () => {
  test("with the layer empty it fires at once, synchronously", () => {
    let fired = 0;
    ach.whenClear(() => { fired++; });
    assert.equal(fired, 1,
      "an empty celebration layer must not delay the cast by even a tick -- the ordinary " +
      "case is 'the owner enters the code while nothing is celebrating'");
  });

  test("mid-moment it waits for that moment's teardown", async () => {
    nextPayload = payload([{ id: "w1", name: "One", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(front().length, 1);

    let fired = 0;
    ach.whenClear(() => { fired++; });
    assert.equal(fired, 0,
      "the moment is on screen and the cast's layer is BELOW it (449 vs 520); firing now " +
      "would put the starfall underneath a toast, which is the ruling read backwards");

    front()[0].click();
    await wait(600);
    assert.equal(fired, 1, "and it fires the instant that moment has been torn down");
  });

  test("the callback runs BEFORE the dequeue, so its hold catches the next moment", async () => {
    // The ordering that makes the two directions one mechanism. If the dequeue ran first, the
    // next queued celebration would already be on screen by the time the cast armed, and the
    // cast would paint under it -- the same overlap, one link further along the chain.
    nextPayload = payload([
      { id: "c1", name: "One", tier: "common", desc: "x" },
      { id: "c2", name: "Two", tier: "common", desc: "x" },
    ]);
    ach.check();
    await tick();
    assert.equal(front().length, 1);

    ach.whenClear(() => ach.beginBespokeMoment());   // exactly what the Konami handler does
    front()[0].click();
    await wait(600);
    assert.equal(front().length, 0,
      "the cast armed inside the callback, so the second celebration must still be held");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "and it plays once the cast has gone");
  });
});

describe("a bespoke feat's EARN never gets the generic fanfare", () => {
  test("its own moment is the celebration", async () => {
    nextPayload = payload([{ id: "the-konami-code", name: "A Feat", tier: "feat", desc: "x" }]);
    ach.check();
    await tick();
    const m = moments()[0];
    assert.ok(m, "the moment itself still plays -- suppressed FANFARE, not a suppressed toast");
    assert.equal(starsIn(m), 0, "no star rain over a celebration that already had one");
    assert.equal(confIn(m), 0, "and no confetti");
  });

  test("every other feat keeps it", async () => {
    nextPayload = payload([{ id: "some-other-feat", name: "Other", tier: "feat", desc: "x" }]);
    ach.check();
    await tick();
    const m = moments()[0];
    assert.ok(starsIn(m) > 0, "the ordinary feat fanfare must survive this change");
    assert.ok(confIn(m) > 0);
  });

  test("a FOLIO REPLAY of one keeps it -- a replay is not an earn", () => {
    // replay() builds the standard moment and casts no starfall, so gating it here would not
    // "replace" the fanfare with anything: it would just make that card's celebration thinner
    // than the one that shipped before the bespoke rule existed, permanently and for no reason
    // the rule states. The suppression is about the EARN, where a cast really does play.
    const h = ach.replay({ id: "the-konami-code", name: "A Feat", tier: "feat", desc: "x" }, {});
    const m = moments()[0];
    assert.ok(starsIn(m) > 0,
      "the Konami card in the Folio of Honors must still celebrate like the feat it is");
    assert.ok(confIn(m) > 0);
    h.dismiss();
  });

  test("...but not while a bespoke moment is actually on screen", () => {
    ach.beginBespokeMoment();
    const h = ach.replay({ id: "some-other-feat", name: "Other", tier: "feat", desc: "x" }, {});
    const m = moments()[0];
    assert.ok(m, "a replay is a click and still takes over the layer, moment or no moment");
    assert.equal(starsIn(m), 0,
      "but nothing layers flair over a cast that is still fading underneath -- that is rule 2 " +
      "read as what it means");
    assert.equal(confIn(m), 0);
    h.dismiss();
  });
});

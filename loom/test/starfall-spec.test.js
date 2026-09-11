// The Konami starfall, pinned to its committed Design Handoff page, plus the sequence rule
// that keeps a bespoke celebration and the standard achievement toast off each other.
//
// The spec is this cast's brief in the handoff-2026-09-04 set of the private
// moonglade-internal repo -- which this public file deliberately does not name any more
// precisely than that, and could not read in any case, so it cannot quote its copy. What it
// can do is pin the facts the rebuild was measured against, in the two public files that
// implement them
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

/** indexOf, for ORDER assertions, that cannot answer -1.
    `a.indexOf(x) < a.indexOf(y)` is true for free once x is gone: -1 is less than everything,
    so the pin passes vacuously on exactly the edit it exists to catch. Deleting
    `pendingRelease = release;` left all 33 tests in this file green for that reason. Every
    order pin below goes through here, so the line has to BE there before its position is
    asserted. */
function at(hay, needle, why) {
  const i = hay.indexOf(needle);
  assert.ok(i >= 0, why || ("`" + needle + "` is gone. An order assertion on a line that no " +
    "longer exists passes vacuously -- which is not a pin, it is a comment."));
  return i;
}

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
    assert.ok(at(konami, 'className = "ee-nel"') > at(konami, 'className = "ee-star"'),
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
      "the sub-line still takes the roster's own text through textContent, with a literal " +
      "fallback -- this wave does not change where it comes from");
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
    assert.match(achSrc, /function _flair\(built, a, opts\) \{\s*\n\s*if \(BESPOKE_FEATS\.has\(a\.id\) && !\(opts && opts\.replay\)\) return;/,
      "the EARN gate must be the first thing _flair does: a bespoke feat's own moment IS its " +
      "fanfare, and only the REPLAY entry is exempt");
    // _flair used to carry a second gate above that one -- "a bespoke moment is on screen,
    // never layer on it". It is deliberately gone: the dequeue now builds NOTHING while a
    // moment owns the screen (no caller is exempt any more), so that gate could not fire,
    // and an unreachable guard is one nobody can check. If a build path past the hold is
    // ever reintroduced, the gate belongs back in the DEQUEUE, not here.
    assert.doesNotMatch(achBody("_flair"), /_bespoke/,
      "_flair must not re-check _bespoke: whether a moment may be built at all is the one " +
      "gate's decision, and a copy of it here would go stale the first time the gate moves");
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
    assert.match(drain, /if \(_heldOff\(\)\) \{ _pendingDrain = true; return; \}/,
      "THE hold: record that the queue wants to run and build nothing. One statement, no " +
      "entry kind named in it -- the moment a caller is named here it is a caller that is " +
      "exempt, and one door ajar is the whole invariant");
    assert.doesNotMatch(drain, /replay\b(?=[^\n]*_pendingDrain)/,
      "no exemption may be written into the gate. The Folio replay had one -- it is a click " +
      "and its driver handle has to come back synchronously -- and it put a .ach-m2 (520) " +
      "straight over a cast (449). The handle waits with the entry instead (_driver).");
    // The gate is one predicate so that the two holds cannot drift apart: a bespoke moment
    // owning the screen, and a cast WAITING to take it. Leaving the second one out lets the
    // dequeue build one more moment in front of a cast that is about to arm.
    const gate = achBody("_heldOff");
    assert.match(gate, /_bespoke > 0/, "a bespoke moment owning the screen holds the dequeue");
    assert.match(gate, /_whenClear\.length > 0/,
      "...and so does a cast that is waiting for the screen: it is about to arm, and the " +
      "moment built in the gap between the wait and the arm is painted over by definition");
    const rel = achBody("_resume");
    assert.match(rel, /if \(_heldOff\(\)\) return;/,
      "the release re-reads the SAME gate rather than assuming its own hold was the last one");
    assert.equal((rel.match(/_drain\(/g) || []).length, 1,
      "the release calls the dequeue exactly once. Draining a list of parked callers in a " +
      "loop is what let two moments be built from one release");
    const end = achSrc.slice(achSrc.indexOf("export function endBespokeMoment()"));
    assert.match(end.slice(0, end.indexOf("\n}")), /_resume\(\);/,
      "and lifting a bespoke hold goes through that one release, not into the dequeue direct");
    assert.doesNotMatch(achSrc, /_playing/,
      "the round-2 'a moment is playing' flag is gone for good: it had to be lowered while a " +
      "caller was parked, which is what made a release able to start a moment over one that " +
      "was still on screen. _cur -- the element itself -- is the serialization now");
  });

  test("the exit tells the queue the layer is free only once it really is", () => {
    // The regression this round's review caught: _endParade used to call _settled() on the
    // moment it had just started FADING, so a plain celebration queued behind the parade was
    // built across that 500ms fade -- two full-screen .ach-m2 scrims (notify.css:27), the one
    // thing this layer must never show. The behavioural proof is further down; this pins the
    // shape, because the source is where the mistake is legible.
    const end = achBody("_endParade");
    const settles = end.split("\n").filter((l) => l.includes("_settled(")).map((l) => l.trim());
    assert.deepEqual(settles, ["setTimeout(() => { _unmount(m); _settled(m); }, 500);"],
      "the ONLY settle in _endParade must be the one inside the removal timer: removed " +
      "first, settled second, on the same 500ms as the .out fade the ruling asks for. " +
      "Settling the skipped moment where it stands tells the dequeue the layer is free " +
      "while a full-screen .ach-m2 is still painted on it. Found: " + settles.join(" | "));
    assert.match(end, /m\.classList\.add\("out"\);/,
      "and it fades rather than vanishing mid-frame (owner ruling 2026-09-04)");
  });

  test("a parade with nothing on screen yet does not own Escape", () => {
    // _parade is published at ENQUEUE time so the exit can reach a flood whose moments are
    // all still queued. If "a parade is up" reads that alone, then a flood held behind a cast
    // swallows Escape while the owner is looking at the starfall -- and the exit it runs
    // discards the whole held flood on the way past.
    const up = achBody("_paradeUp");
    assert.match(up, /_parade\.m && _parade\.m === _cur/,
      "'the parade is up' has to mean a moment of it is BEING PRESENTED (or its history is " +
      "still on screen) -- not merely that a flood was enqueued");
    assert.match(up, /_trail\.length \|\| _clearTimer/,
      "its receded history and the linger before it bows out still count: Escape belongs to " +
      "the parade for as long as any of it is painted");
  });

  test("the Konami handler arms the moment before the beacon and releases it at the end", () => {
    assert.ok(at(konami, "beginBespokeMoment()") < at(konami, 'sendAchEvent("konami")'),
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
    assert.ok(at(konami, "pendingRelease = release;",
      "the cast never publishes its release to the effect's scope. Without that line an " +
      "unmount inside the arm-to-beacon window has nothing to call: _bespoke never returns " +
      "to 0 and every later achievement in the session is held forever with nothing left to " +
      "release it. (This assertion used to be a bare indexOf comparison, which -1 satisfied " +
      "for free -- deleting the line left every test in this file green.)")
      < at(konami, 'sendAchEvent("konami")'),
      "the release must be published to the effect's scope BEFORE the beacon goes out -- that " +
      "is the whole window this assertion exists for");
    assert.match(app, /let pendingRelease = null;/,
      "and it must live beside teardown in the effect scope, not inside onKey's closure where " +
      "the cleanup cannot see it");
    const cl = at(app, 'document.removeEventListener("keydown", onKey);');
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
    assert.ok(at(konami, "armT = setTimeout") < at(konami, 'sendAchEvent("konami")'),
      "armed before the beacon goes out: a ceiling started after the answer is a ceiling on " +
      "nothing");
    assert.match(konami, /clearTimeout\(armT\)/,
      "and release must cancel it, or a later cast's arm is released by the previous one's timer");
    const built = at(konami, "document.body.appendChild(layer);");
    const answered = at(konami, ".then((data) => {");
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
    const armed = at(konami, "beginBespokeMoment()");
    const castFn = at(konami, "const startCast = ");
    const handoff = at(konami, "whenClear(startCast);");
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
    // so the standard toast for a fresh cast would otherwise wait for the next page load
    // and the ruled "starfall, then the toast" sequence would exist only in the test below.
    assert.match(app, /import \{[^}]*check as achCheck[^}]*\} from "\.\/notify\/ach\.js"/,
      "App.jsx must import ach.js's check() -- window.Ach is a compat surface, not the contract");
    assert.match(konami, /\n\s*achCheck\(\);/, "and the cast must call it");
    const marked = at(konami, "achCheck();");
    assert.ok(marked > at(konami, "document.body.appendChild(layer);"),
      "it fires once the layer is UP: the celebration it builds is parked by the moment, and " +
      "arriving before the moment is on screen is the overlap the ruling forbids");
    assert.ok(marked < at(konami, "}, 6000);"),
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
    // STABLE per selector, unlike ach-parade-exit.test.js's throwaway stand-in: a real
    // querySelector answers with the same node every time, and the replay driver depends on
    // exactly that -- _bind writes the settled line onto `.toast .tbody .r` and the handle
    // reads it back through the same call. Handing out a fresh element each time would make
    // the driver untestable and let a gutted _bind pass.
    querySelector(sel) {
      const k = String(sel);
      e._qs = e._qs || {};
      if (!e._qs[k]) e._qs[k] = el("div");
      return e._qs[k];
    },
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
  const seen = { prevented: false, stopped: false };
  const ev = {
    key: "Escape",
    preventDefault() { seen.prevented = true; },
    stopPropagation() { seen.stopped = true; },
    stopImmediatePropagation() { seen.stopped = true; },
  };
  keyListeners.forEach((fn) => fn(ev));
  return seen;      // whether the engine CLAIMED the key -- see the held-flood test below
}

function payload(list) {
  return { achievements: list, newly: list.map((a) => a.id), skins: [], skin: "moonglade" };
}
const moments = () => body.children.filter((c) => c.classList.contains("ach-m2"));
// A parade's spent moments stay in the DOM as the receded TRAIL; only the one front-and-centre
// is a moment being presented, so a parade assertion has to say which it means.
const front = () => moments().filter((c) => c.classList.contains("trail") === false);
const trail = () => moments().filter((c) => c.classList.contains("trail"));
/* EVERYTHING this module paints, which is what the cast's layer has to be clear of. A trail
   card is not a moment, but it still carries .ach-m2 (z-index 520) and the parade's two chips
   sit at 519/521 -- all three above .ee-layer's 449, so all three are "on top of the cast". */
const painted = () => body.children.filter((c) => c.classList.contains("ach-m2")
  || c.classList.contains("ach-trailchip"));
/* Which achievement a moment is showing: _mkMoment writes the name into .tw's innerHTML, and
   the fake DOM keeps that as a plain string. Used to pin QUEUE ORDER -- a parade step and a
   plain celebration coming out in FIFO is what "one queue" means in observable terms. */
const nameOf = (m) => {
  const tw = twOf(m);
  return tw ? tw.innerHTML : "";
};
const twOf = (m) => {
  const stage = m.children[0];
  return stage && stage.children.filter((c) => c.classList.contains("tw"))[0];
};
/* The roast line of a built moment -- the node the Folio's scramble driver writes through.
   The same selector the engine uses, answered by the same cached element (see el() above). */
const lineOf = (m) => {
  const tw = twOf(m);
  return tw && tw.querySelector(".toast .tbody .r");
};
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

  test("a HELD flood owns nothing, so it neither eats Escape nor is thrown away by it", async () => {
    // The parade is published the moment a flood is enqueued, so the exit can reach one whose
    // moments are all still queued. If "a parade is up" reads that alone, then while the cast
    // holds the screen a parade with NOTHING on it swallows Escape -- and the exit it runs
    // splices the entire held flood out of the queue. The owner would have pressed Escape at
    // something else entirely and silently lost every one of those celebrations.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "e" + i, name: "E" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.beginBespokeMoment();
    ach.check();
    await tick();
    assert.equal(painted().length, 0, "none of the flood is on screen: it is all queued");

    const claimed = sendEscape();
    assert.equal(claimed.prevented, false,
      "with nothing of the parade painted, Escape belongs to whatever IS on screen -- this " +
      "module's listener is registered in CAPTURE on window, so claiming the key here stops " +
      "every overlay in the app closing and nothing else fails for it");
    assert.equal(claimed.stopped, false);

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1,
      "and the held flood still plays: an exit nobody asked for must not have discarded it");
  });

  test("overlapping moments compose -- the release belongs to the last one out", async () => {
    nextPayload = payload([{ id: "solo", name: "Solo", tier: "rare", desc: "x" }]);
    ach.beginBespokeMoment();
    ach.beginBespokeMoment();          // two bespoke moments back to back
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

  test("a REPLAY clicked MID-PARADE takes the layer over too", async () => {
    // The same claim, on the path that actually broke it. _takeover ends the parade first and
    // then removes the moment on screen -- but the exit used to hand the moment off to the
    // trail and null _cur on its way past, so by the time the takeover looked there was
    // nothing left to remove and it opened a second .ach-m2 beside the one still fading.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "t" + i, name: "T" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    front()[0].click();                        // advance: one in the trail, one front-and-centre
    await tick();
    assert.equal(front().length, 1, "the parade is mid-step");
    peakReset();

    const h = ach.replay({ id: "t9", name: "Replayed", tier: "rare", desc: "x" }, {});
    assert.equal(front().length, 1, "one moment, not two");
    assert.equal(peak, 1, "and never two, not even for the length of one turn");
    await wait(600);
    assert.equal(trail().length, 0, "and the parade's trail left with it");
    h.dismiss();
    await wait(700);
    // ...its presented HISTORY, that is. The steps it had not shown yet are first earns with
    // their marks already consumed, so the click does not get to throw them away: the parade
    // picks up where it stopped once the replay is done with the screen.
    assert.equal(front().length, 1, "the parade resumes behind the replay");
    assert.match(nameOf(front()[0]), /T\d/);
  });

  test("skipping a parade does not build the celebration queued behind it ON TOP of it", async () => {
    // The exit drops the parade's own entries and nothing else, so a plain celebration that
    // arrived behind the flood still has to play. It must not be built while the skipped
    // moment is still on screen: both are full-screen scrims (notify.css:27) and the skipped
    // one fades for 500ms, so "the layer is free" said at skip time is said 500ms too early.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "k" + i, name: "K" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the parade is up");

    nextPayload = payload([{ id: "behind", name: "Behind", tier: "common", desc: "x" }]);
    ach.check();                               // a generation finishes mid-parade
    await tick();
    assert.equal(front().length, 1, "still just the parade's moment; the earn is queued");
    peakReset();

    sendEscape();
    assert.equal(front().length, 1,
      "the skipped moment is FADING, not gone -- and nothing may be built across that fade");

    await wait(700);
    assert.equal(front().length, 1, "the queued celebration plays once the layer is really empty");
    assert.match(nameOf(front()[0]), /Behind/, "...and it is the one the skip did not touch");
    // peak is sampled at every append, so it is the only way to see an overlap that opened
    // and closed inside one turn -- which is what the skip path's did.
    assert.equal(peak, 1, "at no instant two .ach-m2 moments (skip path)");
  });

  test("the parade's next step and a plain earn come out of ONE queue, in order", async () => {
    // What "the parade is not a second door" means in observable terms. A parade that kept a
    // pending list of its own would step from its own loop while celebrate() drained the
    // queue, so the release would start two moments in the same turn -- and the order of a
    // flood step against an earn queued behind it would be whichever timer won. The gate
    // catching the step is not enough on its own to show that; sharing the queue is.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "f" + i, name: "F" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the parade is up and stepping");

    ach.beginBespokeMoment();                  // the cast lands mid-parade
    front()[0].click();                        // that moment recedes; the next step is held
    await tick();
    assert.equal(front().length, 0, "the step is held by the one gate");

    nextPayload = payload([{ id: "tail", name: "Tail", tier: "common", desc: "x" }]);
    ach.check();                               // ...and an earn arrives behind the flood
    await tick();
    assert.equal(front().length, 0,
      "the plain earn is held by the SAME gate -- if it had a door of its own it would be on " +
      "screen right now, over the cast");
    peakReset();

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "the release builds exactly one");
    assert.equal(peak, 1, "not the parade's step AND the queued earn in the same turn");
    assert.match(nameOf(front()[0]), /F\d/, "and FIFO: the flood's remaining moments go first");

    for (let i = 0; i < 4; i++) { front()[0].click(); await tick(); }   // walk the rest of the flood
    assert.equal(front().length, 1);
    assert.match(nameOf(front()[0]), /Tail/,
      "the earn queued behind the flood comes out last, which is only true of one queue");
    assert.equal(peak, 1, "one moment at a time the whole way down");
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
    //
    // PINNED WHERE IT IS WRITTEN, because the behaviour below cannot see it: _heldOff() also
    // counts a cast that is merely WAITING, so a swapped _settled refuses the dequeue on that
    // gate instead and reaches the same end state. The order is the second line of that
    // defence -- what keeps _settled correct if the gate's second clause ever moves -- and a
    // second line of defence can only be pinned at the line. `at()` refuses -1, so deleting
    // either call fails here rather than passing vacuously.
    const settle = achBody("_settled");
    assert.ok(at(settle, "_flushClear();", "_settled no longer flushes the waiting casts at all")
      < at(settle, "_drain();", "_settled no longer re-enters the dequeue"),
      "_settled must flush the waiting casts BEFORE it re-enters the dequeue. Reversed, " +
      "whether the next queued moment is built over a cast that is about to arm depends on " +
      "the gate alone, and the two halves of the mechanism drift apart the day it changes.");

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

  test("it waits for the parade's TRAIL too, and the trail does not outlive the wait", async () => {
    // A receded card is presented history, but it is still .ach-m2 at z-index 520 over the
    // cast's 449: firing while four of them are stacked down-screen puts the starfall under
    // them for its whole life. Waiting for the whole parade instead would cost the cast every
    // earn still queued, so the wait takes the history DOWN rather than sitting behind it.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "u" + i, name: "U" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    front()[0].click();                        // one receded, one front-and-centre, chips up
    await tick();
    assert.equal(trail().length, 1, "there is presented history on screen");
    assert.ok(painted().length > 1, "and the parade's chips with it");

    let atArm = null;
    ach.whenClear(() => { atArm = painted().length; ach.beginBespokeMoment(); });  // what App.jsx does
    assert.equal(atArm, null, "a moment is presenting: the cast waits");

    front()[0].click();                        // it ends naturally and recedes
    await wait(700);
    assert.equal(atArm, 0,
      "the cast must arm on a screen this module has left EMPTY -- 'no moment presenting' is " +
      "not the same as clear, and the difference is four dimmed cards on top of the starfall");
    assert.equal(painted().length, 0,
      "and nothing may drift back onto it: the linger timer that bows a parade out sits ahead " +
      "of the gate precisely so it can still run while a cast holds the screen");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "the parade resumes where it stopped once the cast is gone");
  });

  test("a parade LINGERING with nothing presenting is not 'clear' either", async () => {
    // The window the assertion above cannot reach: every moment has receded, so nothing is
    // being presented and whenClear's own front door would fire on the spot -- with four
    // dimmed trail cards and the parade's two chips still painted over the cast. "Nothing is
    // presenting" and "the screen is empty" differ for the whole 3.2s a parade lingers.
    const list = Array.from({ length: 4 }, (_, i) => ({ id: "l" + i, name: "L" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    for (let i = 0; i < 4; i++) { front()[0].click(); await tick(); }   // walk the whole flood
    assert.equal(front().length, 0, "every moment has receded: the parade is lingering");
    assert.ok(painted().length > 0, "...with its trail and its chips still on screen");

    let atFire = null;
    ach.whenClear(() => { atFire = painted().length; });
    assert.equal(atFire, null,
      "the cast must not start here. .ach-m2.trail drops the scrim (notify.css:35) but keeps " +
      "z-index 520, so those cards sit on top of the starfall's 449 for as long as they last");

    await wait(700);
    assert.equal(atFire, 0, "the wait takes the history down and fires on an empty screen");
  });

  test("the wait's own release is what restarts a queue held behind it", async () => {
    // _flushClear fires the waiting casts and then calls _resume(). That call is reached from
    // _unmount -- the last thing painted leaving the DOM -- where NOTHING follows it: _settled
    // is not involved, no timer is pending, no caller is left to ask again. Delete it and the
    // queue that was held only because a cast was waiting stays held for the rest of the
    // session, which looks exactly like the engine having died.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "z" + i, name: "Z" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    front()[0].click();                        // one receded, one front-and-centre, chips up
    await tick();
    assert.equal(trail().length, 1, "there is presented history on screen");

    let fired = 0;
    ach.whenClear(() => { fired++; });          // a waiter that does NOT arm: the release under
    front()[0].click();                         // test is the flush's own, not a bespoke one
    await tick();
    assert.equal(fired, 0, "the history is still painted, so the wait has not fired");
    assert.equal(front().length, 0,
      "and the parade's next step is held -- a cast waiting for the screen closes the gate");

    await wait(700);
    assert.equal(fired, 1, "the wait took the history down and fired on an empty screen");
    assert.equal(front().length, 1,
      "and the held queue ran again. The ONLY thing that can restart it here is the _resume() " +
      "_flushClear makes after firing its waiters: this release arrives from _unmount, and " +
      "nothing follows _unmount to ask the dequeue a second time.");
  });

  test("a SKIPPED parade is empty before the cast starts, not merely settled", async () => {
    // The exit reaches the same hook every other teardown does. It used to reach it with the
    // skipped moment still painted, so a cast waiting behind the skip started underneath it.
    const list = Array.from({ length: 5 }, (_, i) => ({ id: "v" + i, name: "V" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    front()[0].click();
    await tick();
    assert.equal(front().length, 1);

    let atFire = null;
    ach.whenClear(() => { atFire = painted().length; });
    sendEscape();
    assert.equal(atFire, null,
      "the skipped moment is fading through the same 500ms .out the ruling asks for; the " +
      "layer is not free yet and the cast must not be told that it is");
    await wait(700);
    assert.equal(atFire, 0, "and the cast starts on an empty screen");
  });
});

describe("a replay takes the SCREEN over, never somebody else's first earn", () => {
  test("a replay clicked while a cast is WAITING does not strand the cast", async () => {
    // The hole the takeover had: it emptied the queue, ended the parade and removed the
    // moment on screen, but it nulled _cur by hand AFTER unmounting, so the flush _unmount
    // fires saw a moment still presenting and returned -- and nothing ever flushed again.
    // _heldOff() then answered true for the rest of the session: no starfall, no replay, no
    // celebration, and not one error. The fix is that the takeover finishes through _settled,
    // the same settle path every other teardown uses.
    nextPayload = payload([{ id: "sw1", name: "Onscreen", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "a moment is presenting");

    let fired = 0;
    ach.whenClear(() => { fired++; ach.beginBespokeMoment(); });   // what App.jsx does
    assert.equal(fired, 0, "the cast waits while that moment is up");

    const h = ach.replay({ id: "sw2", name: "Replayed", tier: "rare", desc: "x" }, {});
    await tick();
    assert.equal(fired, 1,
      "the takeover emptied the layer, so the waiting cast must have been flushed. Left " +
      "unflushed it waits forever -- _heldOff() stays true, the dequeue builds nothing ever " +
      "again, and the session is silently over.");
    assert.equal(moments().length, 0,
      "and the replay is held behind the cast it just let through, like any other entry -- " +
      "a click is not an exemption from the gate (owner ruling 2026-09-10, both directions)");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "and it plays the moment the cast releases");
    assert.match(nameOf(front()[0]), /Replayed/);
    h.dismiss();
    await wait(600);
  });

  test("the earns already queued keep their turn behind it", async () => {
    // A pending entry is a FIRST EARN whose mark the server already consumed, so dropping
    // one is a celebration the owner can never get back. The takeover used to empty the
    // whole queue: clicking a Folio card while two unlocks were waiting silently destroyed
    // the second one's only toast.
    nextPayload = payload([
      { id: "d1", name: "First", tier: "common", desc: "x" },
      { id: "d2", name: "Second", tier: "common", desc: "x" },
    ]);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the first earn plays; the second is queued behind it");

    const h = ach.replay({ id: "dr", name: "Replayed", tier: "rare", desc: "x" }, {});
    assert.equal(front().length, 1, "one moment, not two");
    assert.equal(peak, 1);
    assert.match(nameOf(front()[0]), /Replayed/,
      "the click is immediate in the only way it still can be: the entry goes to the FRONT " +
      "of the queue and is the next thing built");

    h.dismiss();
    await wait(700);
    assert.equal(front().length, 1,
      "and the earn that was waiting still plays -- the replay took the screen, not the queue");
    assert.match(nameOf(front()[0]), /Second/);
  });

  test("a takeover from a DRAINED parade ends it, so Escape belongs to the Folio", async () => {
    // The takeover's parade-ending branch, pinned by its observable consequence rather than
    // by its text. A parade whose queue has run dry has nothing left but the history the
    // takeover just removed -- but the LINGER it armed is still counting down, and the linger
    // is half of what _paradeUp() answers on. Leave the branch out and _paradeUp() keeps
    // saying "a parade is up" for 3.2s while a Folio replay is the only thing on screen, so
    // this module swallows the Escape that is supposed to close the Folio. Nothing else in
    // the suite reaches this state: every other replay test replays with no parade at all,
    // where _paradeUp() is false whether the branch is there or not.
    const list = Array.from({ length: 4 }, (_, i) => ({ id: "tk" + i, name: "TK" + i, tier: "common", desc: "x" }));
    nextPayload = payload(list);
    ach.check();
    await tick();
    for (let i = 0; i < 4; i++) { front()[0].click(); await tick(); }
    assert.equal(front().length, 0, "every moment has receded: the parade is lingering");
    assert.ok(painted().length > 0, "...with its trail and its chips still painted");

    const h = ach.replay({ id: "tkr", name: "Replayed", tier: "rare", desc: "x" }, {});
    assert.equal(typeof h.setText, "function", "replay must hand back its driver handle");
    assert.equal(front().length, 1, "the replay took the layer over");
    assert.match(nameOf(front()[0]), /Replayed/);

    const claimed = sendEscape();
    assert.equal(claimed.prevented, false,
      "a replay is not a parade: the takeover must END a parade that had nothing left but " +
      "its linger, or this module eats the Escape that closes the Folio -- for the rest of " +
      "the linger, on a screen showing one replayed card and nothing else");
    assert.equal(claimed.stopped, false,
      "...and it must not stop the key propagating to the app's own Escape ladder either");
    assert.equal(front().length, 1,
      "and the replay is still on screen: the key never reached the exit");

    h.dismiss();
    await wait(700);
  });
});

describe("a parade's linger belongs to the parade that armed it", () => {
  test("every place that publishes or drops a parade takes the linger with it", () => {
    // _clearParade ends whichever parade is LIVE, which is only safe while no timer outlives
    // the parade that armed it. The behavioural test below pins the one path that reaches
    // that state today; this is what keeps the rule findable from the other two sites, and
    // from a fourth somebody adds later.
    ["_floodParade", "_endParade", "_takeover"].forEach((fn) => {
      assert.match(achBody(fn), /_cancelLinger\(\);/,
        fn + " publishes or drops a parade without cancelling the linger. A timer left " +
        "behind fires against whatever parade is live THEN -- nulling it, and taking every " +
        "pending first earn off the queue with it through _drain's stale-flood guard");
    });
  });

  test("a second flood arriving inside the first's linger loses none of its earns", async () => {
    // A parade whose queue runs dry arms a 3.2s linger before it bows out. That timer used to
    // be anonymous: a flood arriving inside the window published a NEW parade over the old
    // one and the old one's timer went on running, so _clearParade nulled the LIVE parade --
    // and the dequeue's stale-flood guard then shifted every one of its pending entries off
    // the queue. Those are first earns whose marks the server has already consumed: no toast,
    // no error, nothing to replay from. The wall-clock waits are the test: click straight
    // through and the timer never gets to fire in the window it breaks.
    const a = Array.from({ length: 4 }, (_, i) => ({ id: "fa" + i, name: "FA" + i, tier: "common", desc: "x" }));
    nextPayload = payload(a);
    ach.check();
    await tick();
    for (let i = 0; i < 4; i++) { front()[0].click(); await tick(); }
    assert.equal(front().length, 0, "the first parade has run dry and is lingering");

    await wait(2900);                          // still inside its 3.2s linger, only just
    const b = Array.from({ length: 4 }, (_, i) => ({ id: "fb" + i, name: "FB" + i, tier: "common", desc: "x" }));
    nextPayload = payload(b);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "the second parade's first moment is presenting");
    await wait(500);                           // ...and now the first parade's timer has fired

    const shown = [nameOf(front()[0])];
    for (let i = 0; i < 3; i++) {
      front()[0].click();
      await tick();
      assert.equal(front().length, 1,
        "the second parade stopped after " + shown.length + " of its 4 earns. A timer armed " +
        "by the parade BEFORE it fired inside this one, ended it, and the dequeue dropped " +
        "every entry still waiting -- marks the server has already consumed, so those toasts " +
        "are gone for good");
      shown.push(nameOf(front()[0]));
    }
    assert.deepEqual(shown.map((n) => (n.match(/FB\d/) || [""])[0]), ["FB0", "FB1", "FB2", "FB3"],
      "every earn of the second flood must present, in order");
  });
});

describe("the replay driver drives an entry that is not on screen yet", () => {
  test("what the scramble settled on while it waited is on the moment when it builds", async () => {
    // useFolio starts driving the instant replay() returns and does not wait for a moment to
    // exist: it spreads the handle and calls setText/setGlitching/setSettledNsfw through a
    // 26-tick scramble. A held entry therefore has to RECORD what it is told, and _bind is
    // what replays that onto the element the dequeue finally builds -- without it the
    // celebration arrives on the clean line, or on a half-scrambled one, whichever the
    // scramble happened to leave behind.
    ach.beginBespokeMoment();
    const h = ach.replay({ id: "some-other-feat", name: "Other", tier: "feat", desc: "x" }, {});
    assert.equal(moments().length, 0, "held: nothing is built while the moment owns the screen");
    h.setText("the line the scramble settled on");
    h.setGlitching(true);
    h.setSettledNsfw(true);
    h.setGlitching(false);                     // ...and the scramble finishing before it builds

    ach.endBespokeMoment();
    await tick();
    const m = front()[0];
    assert.ok(m, "the celebration plays once the screen is free");
    const r = lineOf(m);
    assert.equal(r.textContent, "the line the scramble settled on",
      "the moment must be built carrying the driver's recorded text. Empty here means the " +
      "entry's state was never replayed onto the element -- _bind gone or gutted -- and the " +
      "owner's card celebrates on a line the reveal had already moved past.");
    assert.equal(r.classList.contains("settled-nsfw"), true,
      "the settled-nsfw flag is recorded state too, not a live call against a live element");
    assert.equal(r.classList.contains("glitch"), false,
      "and the LAST value wins: replaying the first call instead of the settled one would " +
      "leave the moment glitching forever");

    h.setText("and it keeps driving after it is built");
    assert.equal(r.textContent, "and it keeps driving after it is built",
      "once bound, the handle drives the real element -- the recording is a bridge, not a " +
      "replacement for the live path useFolio's toggleUnleash still uses");
    h.dismiss();
    await wait(600);
  });

  test("a replay dismissed before it was ever built leaves the queue and never plays", async () => {
    // The Folio dismisses the previous handle on every card click (useFolio's replayToast),
    // and Escape closes the Folio through the same call. A held entry has no element to
    // click, so dismiss() has to reach into the queue and take it out -- a no-op there is a
    // celebration that pops up later for a card the owner already clicked away, and the
    // suite stays green because nothing else ever looks at that branch.
    ach.beginBespokeMoment();
    const h = ach.replay({ id: "some-other-feat", name: "Ghost", tier: "feat", desc: "x" }, {});
    assert.equal(moments().length, 0, "held, and never built");
    h.dismiss();

    ach.endBespokeMoment();
    await tick();
    assert.equal(moments().length, 0,
      "a dismissed-before-built replay must have LEFT the queue. Still there, it is built by " +
      "the release and the dismissed card celebrates anyway.");
    await wait(700);
    assert.equal(moments().length, 0, "and it does not arrive late either");
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

  /* CHANGED 2026-09-11, and this is what it used to say: "a replay is a click and still takes
     over the layer, moment or no moment" -- it asserted that a replay BUILDS while a bespoke
     moment owns the screen, and only its fanfare was suppressed. That pinned the exemption
     the dequeue's gate carried for replay entries, and the exemption is the overlap: .ach-m2
     is z-index 520 and the cast's layer is 449, .ee-layer takes no pointer events, so an open
     Folio stays clickable for the whole 6000ms hold and one click put a toast over the
     starfall. Owner ruling 2026-09-10 says impossible by construction in BOTH directions, and
     a gate with one caller written out of it is not a construction. The click is not refused
     either -- it is HELD, like everything else, and its driver handle waits with it. */
  test("a replay during a bespoke moment is HELD, and plays when the screen is free", async () => {
    ach.beginBespokeMoment();
    peakReset();
    const h = ach.replay({ id: "some-other-feat", name: "Other", tier: "feat", desc: "x" }, {});
    assert.equal(moments().length, 0,
      "nothing may be built while a bespoke moment owns the screen -- not even a click's " +
      "moment. This is the reverse direction of the ruling and the one the gate used to leave " +
      "open for exactly one caller.");
    assert.equal(typeof h.setText, "function",
      "...and the click still gets a REAL driver handle back, synchronously: useFolio spreads " +
      "it and calls setText/setGlitching unguarded through its 26-tick scramble, so handing " +
      "back a bare {} would throw on the first tick");
    h.setText("a line the scramble settled on while it waited");

    ach.endBespokeMoment();
    await tick();
    const m = moments()[0];
    assert.ok(m, "and the celebration plays once the screen is free, rather than being dropped");
    assert.equal(peak, 1, "one moment, never two");
    assert.ok(starsIn(m) > 0,
      "with its ordinary feat fanfare: a replay is not an earn (rule 2), and by the time it " +
      "is built there is nothing on screen left to layer over");
    assert.ok(confIn(m) > 0);
    h.dismiss();
  });
});

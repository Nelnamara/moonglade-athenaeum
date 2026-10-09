// The starfall moment's TRIGGER and the sequence rule that keeps a bespoke celebration and the
// standard achievement toast off each other.
//
// REWRITTEN for the celebration-videos build. The starfall is no longer a DOM cast App.jsx
// builds itself (the scrim, the orb, the still, the forty stars and the .ee-* block in
// styles.css are gone); it is a CLIP MOMENT -- gallery/src/moments/, one stage and one clock,
// ported number for number from its locked Design Handoff page in the private
// moonglade-internal repo. The page's own numbers are pinned in moment-stage.test.js. What
// stays here is everything about the moment that is NOT pixels:
//
//   * the trigger (App.jsx's key-sequence handler): armed before the beacon, released on
//     every way out, gated by whenClear, never naming an id -- the feat is the one whose
//     roster object carries `moment`, and a v5 roster says so;
//   * the sequence rule in notify/ach.js: one queue, one dequeue, one gate, and the MOMENT
//     HOST (review amendment 1) -- an earn that brings its own moment is handed to the host and
//     its hold is armed BEFORE any toast from the same answer can be queued;
//   * the behaviour of that rule, driven through the engine's real entry points against a
//     fake DOM, the same move ach-parade-exit.test.js makes.
//
// No id is named in this file (the id-free public source, pack v5): a feat with a moment is
// any achievement object carrying the `moment` flag, which is exactly how the engine decides.
import { test, describe, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const read = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");

// The trigger moved out of App.jsx on 2026-09-26 (moments/starfallTrigger.js), so every shell --
// the desktop gallery and the phone -- installs the same one; `app` is that module now.
const app = read(path.join(SRC, "moments/starfallTrigger.js"));
const appShell = read(path.join(SRC, "App.jsx"));
const css = read(path.join(SRC, "styles.css"));
const achSrc = read(path.join(SRC, "notify/ach.js"));

// The handler, isolated: everything between the effect that owns the key sequence and the
// listener teardown. Assertions below must not be able to pass on some unrelated part of a
// very long component.
const trigger = (() => {
  const i = app.indexOf("const seq = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];");
  assert.ok(i > 0, "the key sequence is gone from moments/starfallTrigger.js -- this whole file is about it");
  const j = app.indexOf('document.addEventListener("keydown", onKey);', i);
  assert.ok(j > i, "the handler no longer ends by registering its keydown listener");
  return app.slice(i, j);
})();

/** indexOf, for ORDER assertions, that cannot answer -1.
    `a.indexOf(x) < a.indexOf(y)` is true for free once x is gone: -1 is less than everything,
    so the pin passes vacuously on exactly the edit it exists to catch. Every order pin below
    goes through here, so the line has to BE there before its position is asserted. */
function at(hay, needle, why) {
  const i = hay.indexOf(needle);
  assert.ok(i >= 0, why || ("`" + needle + "` is gone. An order assertion on a line that no " +
    "longer exists passes vacuously -- which is not a pin, it is a comment."));
  return i;
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

describe("the trigger plays the clip moment; the DOM cast is gone", () => {
  test("no cast is built in App.jsx any more", () => {
    assert.doesNotMatch(trigger, /document\.createElement\(/,
      "the handler builds DOM again -- the starfall is a clip moment (moments/ClipMoment.jsx), " +
      "and a second, hand-built cast beside it is two starfalls with two sets of numbers");
    assert.doesNotMatch(trigger, /\bee-(layer|scrim|orb|nel|star|toast)\b/,
      "the retired .ee-* cast nodes are back in the handler");
    assert.doesNotMatch(trigger, /document\.body\.appendChild/);
    assert.doesNotMatch(css, /\.ee-layer\s*\{/,
      "styles.css still carries the retired cast's .ee-* block -- dead CSS for a layer nothing builds");
  });

  test("the feat is found by its `moment` flag, never by an id", () => {
    assert.match(trigger, /a\.moment === "starfall"/,
      "the trigger must find its feat by the roster's own flag (the id-free public source)");
    assert.doesNotMatch(trigger, /\ba\.id\s*===/,
      "an id comparison is back in the trigger -- hidden-feat ids leave public source with pack v5");
    assert.match(trigger, /playMoment\(feat \|\| \{ moment: "starfall" \}\)/,
      "and a roster with no flag yet still gets the moment (in its no-video fallback) rather " +
      "than nothing");
    assert.match(app, /import \{[^}]*playMoment[^}]*\} from "\.\/momentStore\.js"/,
      "App.jsx plays the moment through the shared store -- the same one the moment host is");
  });

  test("the trigger arms the moment before the beacon and releases it at the end", () => {
    assert.ok(at(trigger, "beginBespokeMoment()") < at(trigger, "sendAchEvent("),
      "the beacon is what EARNS the feat, so a check() -- the trigger's own, or one a " +
      "finishing generation fires -- can land while this chain is still in the air; arming " +
      "after the moment is requested leaves that gap open");
    assert.match(trigger, /endBespokeMoment\(\)/, "and it must release");
    assert.match(trigger, /const release = \(\) => \{\s*\n\s*if \(released\) return;/,
      "release must be idempotent: four paths reach it and a double release would unbalance " +
      "the depth count, un-holding a moment that is still on screen");
    assert.match(trigger, /\.catch\(\(\) => \{ if \(teardown\) teardown\(\); else release\(\); \}\)/,
      "a throw anywhere in the chain must still release");
    assert.ok(at(trigger, "pendingRelease = release;",
      "the trigger never publishes its release to the effect's scope. Without that line an " +
      "unmount inside the arm-to-beacon window has nothing to call: _bespoke never returns " +
      "to 0 and every later achievement in the session is held forever.")
      < at(trigger, "sendAchEvent("),
      "the release must be published to the effect's scope BEFORE the beacon goes out");
    assert.match(app, /let pendingRelease = null;/,
      "and it must live beside teardown in the effect scope, not inside onKey's closure where " +
      "the cleanup cannot see it");
    const cl = at(app, 'document.removeEventListener("keydown", onKey);');
    const cleanup = app.slice(cl, cl + 300);
    assert.match(cleanup, /if \(teardown\) teardown\(\);/,
      "unmounting with the moment up must end it (teardown releases)");
    assert.match(cleanup, /else if \(pendingRelease\) pendingRelease\(\);/,
      "and unmounting BEFORE the moment is requested must still release");
    assert.match(trigger, /teardown = \(\) => \{ skipMoment\(\); release\(\); \};/,
      "the teardown ends the moment it requested (a fading skip) and releases");
    assert.match(trigger, /ended\.then\(release, release\);/,
      "and the moment ENDING -- played out, skipped or fallen back -- is what releases on the " +
      "normal path: the hold lasts exactly as long as the moment");
  });

  test("the beacon posts the moment's neutral event name and nothing else", () => {
    // Served JS is public, so the event name must not describe the gesture (scope 2026-10-02,
    // platform item 3). The server's whitelist takes the same word; the old one is refused.
    const posted = [...trigger.matchAll(/sendAchEvent\(\s*([^)]*)\)/g)].map((m) => m[1].trim());
    assert.deepEqual(posted, ['"starfall"'],
      "the key-sequence trigger must post exactly one beacon, with the literal event name " +
      "\"starfall\" -- found " + JSON.stringify(posted));
  });

  test("a beacon that never answers cannot wedge the engine", () => {
    // The root App never unmounts, so its cleanup never runs, and apiGet/apiPost make a bare
    // fetch that a hung request neither resolves nor rejects -- only wall-clock time can end
    // that, so the arm carries a ceiling from the moment it is armed.
    const cap = trigger.match(/const ARM_CEILING_MS = (\d+);/);
    assert.ok(cap, "the arm needs a wall-clock ceiling, named once");
    assert.ok(Number(cap[1]) > 0, "ARM_CEILING_MS must be a real ceiling, not zero");
    assert.match(trigger, /armT = setTimeout\(\(\) => \{ if \(!teardown\) release\(\); \}, ARM_CEILING_MS\);/,
      "the ceiling must RELEASE, and stand down once the moment has been requested (teardown)");
    assert.ok(at(trigger, "armT = setTimeout") < at(trigger, "sendAchEvent("),
      "armed before the beacon goes out: a ceiling started after the answer is a ceiling on nothing");
    assert.match(trigger, /clearTimeout\(armT\)/,
      "and release must cancel it, or a later cast's arm is released by the previous one's timer");
    const answered = at(trigger, ".then((data) => {");
    const played = at(trigger, "playMoment(");
    assert.ok(played > answered,
      "the moment must be requested INSIDE the beacon's .then, after the answer: the clip is " +
      "served under the unlock this beacon records, and the feat's clip and copy only exist " +
      "in the answer once it has");
    assert.match(trigger.slice(answered, played), /if \(released\) return;/,
      "a chain that answers AFTER the ceiling expired must play nothing");
  });

  test("the trigger waits for a moment already on screen, and arms inside that wait", () => {
    assert.match(app, /import \{[^}]*whenClear[^}]*\} from "\.\.\/notify\/ach\.js"/);
    assert.match(trigger, /whenClear\(startCast\);/,
      "the keydown handler must hand the cast to whenClear rather than running it");
    assert.doesNotMatch(trigger, /\n\s*startCast\(\);/,
      "and it must not also call startCast() directly");
    const armed = at(trigger, "beginBespokeMoment()");
    const castFn = at(trigger, "const startCast = ");
    const handoff = at(trigger, "whenClear(startCast);");
    assert.ok(castFn > 0 && handoff > castFn);
    assert.ok(armed > castFn && armed < handoff,
      "the arm has to happen INSIDE the callback, or the cast waits for a moment that was " +
      "itself waiting on the cast");
    assert.match(trigger, /if \(busy\) return;/, "the re-trigger guard");
  });

  test("the trigger fires the marking check() itself, from inside the moment", () => {
    assert.match(app, /import \{[^}]*check as achCheck[^}]*\} from "\.\.\/notify\/ach\.js"/);
    assert.ok(at(trigger, "achCheck();") > at(trigger, "playMoment("),
      "it fires once the moment is REQUESTED: the celebration it builds is parked by the hold, " +
      "and the answer's own copy of this feat is handed to the host, which joins the moment " +
      "already playing instead of starting a second one");
    assert.match(trigger, /apiGet\("\/api\/achievements"\)/,
      "the feat read stays UNMARKED -- it only wants the now-unmasked flags; marking is " +
      "check()'s job and doing it twice would consume `newly` before the toast is built");
  });
});

describe("the bespoke-moment sequence rule, in source", () => {
  test("bespoke is the roster's `moment` flag, never a list of ids", () => {
    assert.match(achSrc, /export function isBespoke\(a\) \{ return !!\(a && a\.moment\); \}/,
      "which feats bring their own moment is the sealed roster's to say (the `moment` flag), " +
      "not a set of id literals in public source");
    assert.doesNotMatch(achSrc, /BESPOKE_FEATS/, "the id set is gone for good");
  });

  test("the fanfare has exactly one gate, not three call sites to keep in step", () => {
    const calls = (achSrc.match(/_fanfare\(/g) || []).length;
    assert.equal(calls, 2,
      "found " + calls + " mentions of _fanfare (expected its definition plus ONE call, " +
      "inside _flair)");
    assert.match(achSrc, /function _flair\(built, a, opts\) \{\s*\n\s*if \(isBespoke\(a\) && !\(opts && opts\.replay\)\) return;/,
      "the EARN gate must be the first thing _flair does: a bespoke feat's own moment IS its " +
      "fanfare, and only the REPLAY entry is exempt");
    assert.doesNotMatch(achBody("_flair"), /_bespoke/,
      "_flair must not re-check _bespoke: whether a moment may be built at all is the one " +
      "gate's decision");
    assert.equal((achSrc.match(/[^\w]_flair\(/g) || []).length, 2,
      "expected exactly two mentions of _flair -- its definition and ONE call, inside _drain");
    assert.match(achBody("_drain"), /_flair\(built, a, e\.replay \? \{ replay: true \} : undefined\)/);
  });

  test("the moment host: registered once, handed every bespoke earn BEFORE any toast", () => {
    assert.match(achSrc, /export function registerMomentHost\(fn\) \{/,
      "ach.js exposes the host API the lane contract names (registerMomentHost)");
    const toast = achBody("toastNew");
    const handed = at(toast, "_toMoment(_momentHost, a)",
      "toastNew no longer hands a bespoke earn to the moment host");
    assert.ok(handed < at(toast, "_floodParade(newly)") && handed < at(toast, "celebrate(a)"),
      "the hand-off must come BEFORE the parade or a celebration is queued: that is what " +
      "arms the hold before any toast from the same answer can reach the screen");
    const to = achBody("_toMoment");
    assert.ok(at(to, "whenClear(") < at(to, "beginBespokeMoment();"),
      "the hold is armed inside whenClear, like the trigger's: a moment never starts under a " +
      "celebration already on screen");
    assert.match(to, /ended\.then\(\(\) => endBespokeMoment\(\), \(\) => endBespokeMoment\(\)\);/,
      "a host that rejects must still release, or every later achievement is held forever");
    assert.match(to, /try \{ ended = Promise\.resolve\(host\(a\)\); \} catch \{ ended = Promise\.resolve\(\); \}/,
      "and one that throws");
    const idx = read(path.join(SRC, "notify/index.jsx"));
    assert.ok(at(idx, "ach.registerMomentHost(playMoment);") < at(idx, "ach.check();"),
      "installNotify -- which the desktop gallery, the phone and the Loom all run -- registers " +
      "the host BEFORE its own first check() can answer");
    assert.match(idx, /<MomentHost \/>/, "and NotifyRoot renders the host on every shell");
  });

  test("unmarked reads carrying a bespoke earn go through the same gate", () => {
    const notice = achBody("noticeAchievements");
    assert.match(notice, /if \(bespoke\) check\(\);/,
      "an unmarked read that lists a bespoke earn asks for the MARKING check, whose answer " +
      "goes through toastNew -- it never toasts on its own");
    assert.doesNotMatch(notice, /celebrate\(|_toMoment\(|toastNew\(/,
      "noticeAchievements must not become a second door onto the screen");
    for (const f of ["hooks/useControlPanel.js", "hooks/useFolio.js"]) {
      assert.match(read(path.join(SRC, f)), /noticeAchievements\(d\);/,
        f + "'s own /api/achievements read can be the read that earns the feat");
    }
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
   card is not a moment, but it still carries .ach-m2 (z-index 519) and the parade's two chips
   sit at 519/521 -- all three above a moment's 515/516, so all three are "on top of the cast". */
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
    nextPayload = payload([{ id: "a-feat-with-a-moment", moment: "starfall", name: "A Feat", tier: "feat", desc: "x", points: 10 }]);
    ach.beginBespokeMoment();          // the starfall is on screen
    ach.check();
    await tick();
    assert.equal(moments().length, 0,
      "the standard toast must not be BUILT while the bespoke moment is up. This is the " +
      "construction the ruling asks for: .ach-m2 (z-index 519) would otherwise paint straight " +
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
      "520 and would paint straight over the moment's 515/516");

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
      "the moment is on screen and the cast's layer is BELOW it (515/516 vs 520); firing now " +
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

    ach.whenClear(() => ach.beginBespokeMoment());   // exactly what the key-sequence trigger does
    front()[0].click();
    await wait(600);
    assert.equal(front().length, 0,
      "the cast armed inside the callback, so the second celebration must still be held");

    ach.endBespokeMoment();
    await tick();
    assert.equal(front().length, 1, "and it plays once the cast has gone");
  });

  test("it waits for the parade's TRAIL too, and the trail does not outlive the wait", async () => {
    // A receded card is presented history, but it is still .ach-m2 at z-index 519 over the
    // moment's 515/516: firing while four of them are stacked down-screen puts the starfall under
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
      "z-index 519, so those cards sit on top of the starfall's 515/516 for as long as they last");

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
    nextPayload = payload([{ id: "a-feat-with-a-moment", moment: "starfall", name: "A Feat", tier: "feat", desc: "x" }]);
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
    const h = ach.replay({ id: "a-feat-with-a-moment", moment: "starfall", name: "A Feat", tier: "feat", desc: "x" }, {});
    const m = moments()[0];
    assert.ok(starsIn(m) > 0,
      "a moment feat's card in the Folio of Honors must still celebrate like the feat it is");
    assert.ok(confIn(m) > 0);
    h.dismiss();
  });

  /* CHANGED 2026-09-11, and this is what it used to say: "a replay is a click and still takes
     over the layer, moment or no moment" -- it asserted that a replay BUILDS while a bespoke
     moment owns the screen, and only its fanfare was suppressed. That pinned the exemption
     the dequeue's gate carried for replay entries, and the exemption is the overlap: .ach-m2
     is z-index 519 and the cast's layer is 449, .ee-layer takes no pointer events, so an open
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

// ---- the moment host (review amendment 1): the hold is armed before any toast -------------
// The host is what a shell registers to play a feat's own moment; notify/index.jsx registers
// moments/momentStore.js's playMoment on every shell. Here a stand-in host records when it was
// called and what was on screen at that instant, and settles when the test says the moment has
// ended -- the only contract ach.js has with it.
function hostProbe() {
  const calls = [];
  let settle = null;
  const fn = (a) => {
    calls.push({ id: a.id, painted: painted().length, built: moments().length });
    return new Promise((resolve, reject) => { settle = { resolve, reject }; });
  };
  return { fn, calls, end: () => settle.resolve("done"), fail: () => settle.reject(new Error("x")) };
}
const withMoment = (id, name, extra) => ({ id, name, tier: "feat", desc: "x", moment: "keyturn", ...(extra || {}) });

describe("the moment host: an earn with its own moment plays it first, alone", () => {
  test("the host gets the earn before anything is built, and the toast plays after it", async () => {
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      nextPayload = payload([withMoment("mh1", "Moment Feat")]);
      ach.check();
      await tick();
      assert.equal(h.calls.length, 1, "the earn carrying a `moment` must be handed to the host");
      assert.equal(h.calls[0].painted, 0, "...onto an empty celebration layer");
      assert.equal(moments().length, 0,
        "and its standard toast must NOT be built while the moment plays: the hold is armed " +
        "before the toast is queued, so a first earn cannot overlap its own moment");
      h.end();
      await tick(); await tick();
      assert.equal(front().length, 1, "the standard toast plays once the moment has ended");
      assert.match(nameOf(front()[0]), /Moment Feat/);
      assert.equal(starsIn(front()[0]), 0, "without the generic fanfare: the moment was the fanfare");
      assert.equal(confIn(front()[0]), 0);
    } finally { off(); }
  });

  test("every toast in the same answer waits for the moment, and the moment's own feat is first", async () => {
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      nextPayload = payload([
        { id: "p1", name: "Plain One", tier: "common", desc: "x" },
        withMoment("mh2", "Moment Feat"),
        { id: "p2", name: "Plain Two", tier: "common", desc: "x" },
      ]);
      ach.check();
      await tick();
      assert.equal(h.calls.length, 1);
      assert.equal(moments().length, 0,
        "a PLAIN earn in the same answer must not reach the screen ahead of the moment either -- " +
        "the arm happens before any of the answer's toasts is queued");
      h.end();
      await tick(); await tick();
      assert.match(nameOf(front()[0]), /Moment Feat/,
        "the toast that follows a moment is that moment's own feat");
      for (const want of [/Plain One/, /Plain Two/]) {
        front()[0].click();
        await wait(600);
        assert.match(nameOf(front()[0]), want, "and the rest follow in the answer's order");
      }
      assert.equal(peak, 1, "one moment at a time throughout");
    } finally { off(); }
  });

  test("a flood carrying a moment is held the same way, then parades", async () => {
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      const list = Array.from({ length: 4 }, (_, i) => ({ id: "fm" + i, name: "FM" + i, tier: "common", desc: "x" }));
      nextPayload = payload(list.concat([withMoment("fmx", "Moment Feat")]));
      ach.check();
      await tick();
      assert.equal(h.calls.length, 1);
      assert.equal(painted().length, 0, "the parade is a queue like any other and waits");
      h.end();
      await tick(); await tick();
      assert.equal(front().length, 1, "the parade starts once the moment has ended");
      assert.match(nameOf(front()[0]), /Moment Feat/, "led by the moment's own feat");
      assert.equal(peak, 1);
    } finally { off(); }
  });

  test("a moment never starts UNDER a celebration already on screen", async () => {
    nextPayload = payload([{ id: "up1", name: "Already Up", tier: "common", desc: "x" }]);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "a celebration is presenting");
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      nextPayload = payload([withMoment("mh3", "Moment Feat")]);
      ach.check();
      await tick();
      assert.equal(h.calls.length, 0,
        "the moment's layer (515/516) sits UNDER .ach-m2 (520): starting it now paints it " +
        "beneath the toast on screen, so the hand-off waits on whenClear");
      front()[0].click();
      await wait(600);
      assert.equal(h.calls.length, 1, "it starts the instant that celebration has left the DOM");
      assert.equal(h.calls[0].painted, 0, "...onto an empty layer");
      assert.equal(moments().length, 0, "and the waiting itself held the queue: nothing was built in the gap");
      h.end();
      await tick(); await tick();
      assert.match(nameOf(front()[0]), /Moment Feat/);
    } finally { off(); }
  });

  test("a host that fails still releases -- the engine is never wedged", async () => {
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      nextPayload = payload([withMoment("mh4", "Moment Feat")]);
      ach.check();
      await tick();
      h.fail();
      await tick(); await tick();
      assert.equal(front().length, 1, "a rejected moment must still let its toast play");
    } finally { off(); }
    const off2 = ach.registerMomentHost(() => { throw new Error("no stage"); });
    try {
      await wait(700);
      front().forEach((m) => m.click());
      await wait(700);
      nextPayload = payload([withMoment("mh5", "Thrown Feat")]);
      ach.check();
      await tick(); await tick();
      assert.equal(front().length, 1, "and so must one that throws");
    } finally { off2(); }
  });

  test("with no host registered, the earn gets its plain toast as it always did", async () => {
    nextPayload = payload([withMoment("mh6", "Moment Feat")]);
    ach.check();
    await tick();
    assert.equal(front().length, 1, "nothing holds it: there is no moment to wait for");
  });

  test("an UNMARKED answer listing a moment earn asks for the marking check", async () => {
    const urls = [];
    const real = globalThis.fetch;
    globalThis.fetch = async (u) => { urls.push(String(u)); return real(u); };
    const h = hostProbe();
    const off = ach.registerMomentHost(h.fn);
    try {
      const earned = withMoment("mh7", "Moment Feat");
      nextPayload = payload([earned]);
      ach.noticeAchievements({ achievements: [earned], newly: ["mh7"] });
      await tick(); await tick();
      assert.ok(urls.some((u) => /mark=1/.test(u)),
        "the read that earned it (the Folio's, the Panel's) is unmarked, so it cannot toast; " +
        "it asks for the marking check, whose answer goes through the one gate");
      assert.equal(h.calls.length, 1, "and the moment plays from that answer");
      h.end();
      await tick(); await tick();
      urls.length = 0;
      ach.noticeAchievements({ achievements: [{ id: "pl", name: "Plain", tier: "common" }], newly: ["pl"] });
      await tick();
      assert.equal(urls.length, 0, "a plain earn keeps today's timing: no extra marking read");
    } finally { off(); globalThis.fetch = real; }
  });
});

describe("every shell installs the one trigger (2026-09-26)", () => {
  test("the desktop gallery and the phone both install moments/starfallTrigger.js", () => {
    assert.match(appShell, /useEffect\(\(\) => installStarfallTrigger\(\), \[\]\);/,
      "App.jsx no longer installs the starfall trigger");
    const mob = read(path.join(SRC, "components/AppMobile.jsx"));
    assert.match(mob, /useEffect\(\(\) => installStarfallTrigger\(\), \[\]\);/,
      "the phone shell no longer installs it -- the phone has no arrow keys, so its only way " +
      "to cast is the touch form the trigger reads");
    assert.match(app, /const offTouch = installTouchCode\(fire\);/,
      "the trigger stopped reading the code's touch form");
    assert.match(app, /offTouch\(\);/, "and its teardown must remove the touch listeners");
  });
});
